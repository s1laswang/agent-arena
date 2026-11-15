from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import mole_carbon as mc
from canary.gemini import mole_replay_audit as mra
from canary.gemini import roles as gemini_roles
from canary.rules import (
    DEV_SEEDS,
    HELDOUT_SEEDS,
    JUDGE_SEEDS,
    KNOWN_V_MODE,
    TIERS,
    TIERS_VERSION,
    TRAIN_SEEDS,
)

SELF_PATH = Path(__file__).resolve()
ROLES_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"
SUITE_DIR = ROLES_DIR / mc.SUITE_DIR_NAME
SUITE_JSON_PATH = SUITE_DIR / "suite.json"
SUITE_MD_PATH = SUITE_DIR / "summary.md"
ADAPTIVE_MOLE_DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "adaptive_mole.md"
ADAPTIVE_MOLE_REPLAY_DOC_PATH = ROOT / "docs" / "gemini" / "roles_carbon" / "adaptive_mole_replay.md"

HASH = chr(0x23)
DASH_CODEPOINTS: tuple[int, ...] = (*range(0x2010, 0x2016), 0x2212)
FORBIDDEN_DASHES: tuple[str, ...] = tuple(chr(c) for c in DASH_CODEPOINTS)
ESCAPED_DASH_TOKENS: tuple[str, ...] = tuple("\\" + f"u{c:04x}" for c in DASH_CODEPOINTS)

EXPECTED_SCOPE = "arena mode, not the judged v1.4 environment"
EXPECTED_V14_FINGERPRINT = "a8f99c2537c91d72"

NAMED_SEED_ARTIFACTS: tuple[str, ...] = (
    "meta.json",
    "summary.json",
    "hof.json",
    "hall_of_fame.jsonl",
    "scenarios.json",
    "design_report.json",
    "skill_gap.json",
    "generations.json",
    "holdout_generalization.json",
    "episodes.json",
    "audit_report.json",
    "mole_log.json",
    "mole_decisions.jsonl",
)

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + "za" + r"[0-9A-Za-z_-]{8,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])" + "s" + "k-" + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{12,}"),
    re.compile(r"(?<![0-9A-Za-z_])" + "ya" + r"29\.[0-9A-Za-z_-]{12,}"),
    re.compile(r"(?<![0-9A-Za-z_])(?:ws|tok)-[0-9a-fA-F]{16,}"),
    re.compile(
        r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|"
        r"OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY|"
        r"CANARY_WORLD_SECRET|CANARY_LEDGER_TOKEN|CANARY_LEDGER_KEY)"
        r"\s*[:=]\s*['\"]?[0-9A-Za-z_-]{4,}"
    ),
)

JUDGE_SEED_TEXT_RE = re.compile(r"\b900_?0[0-3][0-9]\b")

JUDGE_SEED_SET = frozenset(JUDGE_SEEDS)
HELDOUT_SEED_SET = frozenset(HELDOUT_SEEDS)
TRAIN_SEED_SET = frozenset(TRAIN_SEEDS)
DEV_SEED_SET = frozenset(DEV_SEEDS)


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in (*mc.SECRET_ENV_VARS, "GEMINI_GATEWAY_URL"):
        monkeypatch.delenv(env_var, raising=False)


def _strip_ticks(cell: str) -> str:
    val = cell.strip()
    if len(val) >= 2 and val.startswith("`") and val.endswith("`"):
        return val[1:-1].strip()
    return val


def _strip_bold(cell: str) -> str:
    val = cell.strip()
    if len(val) >= 4 and val.startswith("**") and val.endswith("**"):
        return val[2:-2].strip()
    return val


def _extract_section(doc_text: str, heading_prefix: str) -> str:
    lines = doc_text.splitlines()
    start_idx: int | None = None
    heading_level = 0
    for idx, line in enumerate(lines):
        if line.startswith(heading_prefix):
            start_idx = idx + 1
            heading_level = len(line) - len(line.lstrip(HASH))
            break
    assert start_idx is not None, f"missing heading: {heading_prefix}"
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        stripped = lines[idx]
        if stripped.startswith(HASH):
            lvl = len(stripped) - len(stripped.lstrip(HASH))
            if lvl <= heading_level:
                end_idx = idx
                break
    return "\n".join(lines[start_idx:end_idx])


def _parse_markdown_table(section_text: str) -> list[dict[str, str]]:
    table_lines = [ln.strip() for ln in section_text.splitlines() if ln.strip().startswith("|")]
    assert len(table_lines) >= 3, "expected markdown table with header, divider, and data rows"
    headers = [c.strip() for c in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for raw_line in table_lines[2:]:
        cells = [c.strip() for c in raw_line.strip("|").split("|")]
        if len(cells) != len(headers):
            break
        rows.append(dict(zip(headers, cells, strict=True)))
    assert rows, "parsed zero data rows from markdown table"
    return rows


def _extract_fenced_block(section_text: str, fence_lang: str) -> str:
    open_marker = f"```{fence_lang}"
    in_block = False
    collected: list[str] = []
    for line in section_text.splitlines():
        if not in_block:
            if line.strip() == open_marker:
                in_block = True
        else:
            if line.strip() == "```":
                return "\n".join(collected)
            collected.append(line)
    raise AssertionError(f"missing fenced block {open_marker}")


def _tiers_v14_fingerprint() -> str:
    payload = {
        "tiers": {k: v.to_dict() for k, v in TIERS.items()},
        "known_v_mode": KNOWN_V_MODE,
    }
    encoded = json.dumps(payload, sort_keys=True, default=list).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _is_int_seed(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _walk_seeds_and_ints(
    obj: Any,
    path: str,
    seed_entries: list[tuple[str, Any]],
    judge_int_hits: list[tuple[str, int]],
    scope_violations: list[str],
) -> None:
    if _is_int_seed(obj):
        if obj in JUDGE_SEED_SET:
            judge_int_hits.append((path, obj))
        return
    if isinstance(obj, str):
        if "data/worlds/judge" in obj:
            scope_violations.append(f"{path}:judge_world_path")
        if JUDGE_SEED_TEXT_RE.search(obj):
            scope_violations.append(f"{path}:judge_seed_string_token")
        return
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            _walk_seeds_and_ints(item, f"{path}[{idx}]", seed_entries, judge_int_hits, scope_violations)
        return
    if isinstance(obj, dict):
        for raw_k, val in obj.items():
            key = str(raw_k)
            norm = key.strip().lower()
            sub_path = f"{path}.{key}"
            if norm == "environment_scope":
                if val != EXPECTED_SCOPE:
                    scope_violations.append(f"{sub_path}:bad_environment_scope:{val!r}")
            elif norm == "mode" and isinstance(val, str) and val.strip().lower() == "judge":
                scope_violations.append(f"{sub_path}:judge_mode")
            elif norm == "judge" and val is True:
                scope_violations.append(f"{sub_path}:judge_flag_true")

            if norm in {"seed", "world_seed"} or norm.endswith("_seed"):
                if isinstance(val, dict):
                    for sub_k in val:
                        if isinstance(sub_k, str) and sub_k.isdigit():
                            seed_entries.append((f"{sub_path}.{sub_k}", int(sub_k)))
                elif val is not None:
                    seed_entries.append((sub_path, val))
            elif norm == "seeds" or norm.endswith("_seeds"):
                if isinstance(val, list):
                    for idx, item in enumerate(val):
                        seed_entries.append((f"{sub_path}[{idx}]", item))
                elif val is not None and not isinstance(val, dict):
                    seed_entries.append((sub_path, val))

            _walk_seeds_and_ints(val, sub_path, seed_entries, judge_int_hits, scope_violations)


def _load_artifact_payload(file_path: Path) -> Any:
    text = file_path.read_text(encoding="utf-8")
    if file_path.suffix == ".jsonl":
        return [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    return json.loads(text)


def _audit_run_folder_non_contamination(run_dir: Path) -> dict[str, Any]:
    violations: list[str] = []
    seed_entries: list[tuple[str, Any]] = []
    judge_int_hits: list[tuple[str, int]] = []
    scope_violations: list[str] = []

    meta_path = run_dir / "meta.json"
    if not meta_path.is_file():
        violations.append("missing_meta_json")
        return {
            "passed": False,
            "seeds": set(),
            "seed_ref_count": 0,
            "files_audited": [],
            "violations": violations,
        }

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not isinstance(meta, dict):
        violations.append("invalid_meta_json")
        return {
            "passed": False,
            "seeds": set(),
            "seed_ref_count": 0,
            "files_audited": [],
            "violations": violations,
        }

    if meta.get("environment_scope") != EXPECTED_SCOPE:
        scope_violations.append(f"meta.json.environment_scope:{meta.get('environment_scope')!r}")
    if meta.get("role") != mc.ROLE:
        scope_violations.append(f"meta.json.role:{meta.get('role')!r}")
    if meta.get("model_id") != mc.TARGET_MODEL:
        scope_violations.append(f"meta.json.model_id:{meta.get('model_id')!r}")

    candidate_files: list[Path] = []
    seen_files: set[Path] = set()
    for artifact_name in NAMED_SEED_ARTIFACTS:
        named_path = run_dir / artifact_name
        if named_path.is_file():
            resolved = named_path.resolve()
            seen_files.add(resolved)
            candidate_files.append(named_path)

    for extra_path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        rel_parts = extra_path.relative_to(run_dir).parts
        if any(part in mc.SKIP_DIRS for part in rel_parts):
            continue
        raw_text = extra_path.read_text(encoding="utf-8")
        if JUDGE_SEED_TEXT_RE.search(raw_text):
            violations.append(f"judge_seed_text:{extra_path.name}")
        if extra_path.suffix in {".json", ".jsonl"} and extra_path.resolve() not in seen_files:
            seen_files.add(extra_path.resolve())
            candidate_files.append(extra_path)

    for artifact_path in candidate_files:
        rel_name = artifact_path.relative_to(run_dir).as_posix()
        payload = _load_artifact_payload(artifact_path)
        _walk_seeds_and_ints(payload, rel_name, seed_entries, judge_int_hits, scope_violations)

    extracted_seeds: set[int] = set()
    for loc, val in seed_entries:
        if not _is_int_seed(val):
            violations.append(f"non_int_seed:{loc}:{val!r}")
            continue
        extracted_seeds.add(val)
        if val in JUDGE_SEED_SET:
            violations.append(f"judge_seed_contamination:{loc}:{val}")
        if val in HELDOUT_SEED_SET:
            violations.append(f"heldout_seed_contamination:{loc}:{val}")
        if val in TRAIN_SEED_SET:
            violations.append(f"train_seed_contamination:{loc}:{val}")
        if val not in DEV_SEED_SET:
            violations.append(f"outside_dev_seeds:{loc}:{val}")

    for loc, val in judge_int_hits:
        violations.append(f"judge_seed_contamination:{loc}:{val}")
    for sv in scope_violations:
        violations.append(f"scope_violation:{sv}")
    if not extracted_seeds:
        violations.append("zero_seeds_extracted")

    return {
        "passed": len(violations) == 0,
        "seeds": extracted_seeds,
        "seed_ref_count": len(seed_entries),
        "files_audited": [p.relative_to(run_dir).as_posix() for p in candidate_files],
        "violations": violations,
    }


def _check_split_disjointness(train_seeds: set[int], holdout_seeds: set[int]) -> set[int]:
    return train_seeds & holdout_seeds


def test_self_hygiene_zero_comments_hashes_forbidden_dashes_or_secrets() -> None:
    self_src = SELF_PATH.read_text(encoding="utf-8")
    assert HASH not in self_src
    tokens = list(tokenize.generate_tokens(io.StringIO(self_src).readline))
    assert [tok for tok in tokens if tok.type == tokenize.COMMENT] == []

    for dash in FORBIDDEN_DASHES:
        assert dash not in self_src
    lower_self = self_src.lower()
    for esc in ESCAPED_DASH_TOKENS:
        assert esc not in lower_self
    for pat in SECRET_PATTERNS:
        assert pat.search(self_src) is None
    assert mc.scan_file_secrets(SELF_PATH, ROOT) == []

    for artifact in (ADAPTIVE_MOLE_DOC_PATH, ADAPTIVE_MOLE_REPLAY_DOC_PATH, SUITE_JSON_PATH, SUITE_MD_PATH):
        assert artifact.is_file(), f"missing committed artifact: {artifact}"
        text = artifact.read_text(encoding="utf-8")
        for dash in FORBIDDEN_DASHES:
            assert dash not in text, f"forbidden dash in {artifact}"
        lower_text = text.lower()
        for esc in ESCAPED_DASH_TOKENS:
            assert esc not in lower_text, f"escaped forbidden dash in {artifact}"
        for pat in SECRET_PATTERNS:
            assert pat.search(text) is None, f"secret pattern in {artifact}"
        assert mc.scan_file_secrets(artifact, ROOT) == []


def test_judged_v14_benchmark_frozen_and_judge_seed_partition_disjoint() -> None:
    assert TIERS_VERSION == "v1.4"
    assert _tiers_v14_fingerprint() == EXPECTED_V14_FINGERPRINT
    assert list(JUDGE_SEEDS) == list(range(900_000, 900_040))
    assert len(JUDGE_SEED_SET) == 40

    assert DEV_SEED_SET.isdisjoint(JUDGE_SEED_SET)
    assert DEV_SEED_SET.isdisjoint(HELDOUT_SEED_SET)
    assert DEV_SEED_SET.isdisjoint(TRAIN_SEED_SET)
    assert HELDOUT_SEED_SET.isdisjoint(JUDGE_SEED_SET)
    assert TRAIN_SEED_SET.isdisjoint(JUDGE_SEED_SET)

    for judge_seed in (min(JUDGE_SEEDS), max(JUDGE_SEEDS)):
        with pytest.raises(ValueError, match="judge seeds"):
            mra.validate_dev_seeds([0, judge_seed])
        with pytest.raises(SystemExit):
            gemini_roles.dev_only([0, judge_seed])


def test_all_39_committed_folders_judge_seed_disjoint_and_arena_scope() -> None:
    assert ROLES_DIR.is_dir()
    all_dirs = sorted(p for p in ROLES_DIR.iterdir() if p.is_dir())
    verified_dirs = [p for p in all_dirs if p.name != mc.SUITE_DIR_NAME]

    assert len(all_dirs) == 40
    assert SUITE_DIR in all_dirs
    assert len(verified_dirs) == 39

    suite_payload = json.loads(SUITE_JSON_PATH.read_text(encoding="utf-8"))
    assert suite_payload.get("environment_scope") == EXPECTED_SCOPE
    assert EXPECTED_SCOPE in SUITE_MD_PATH.read_text(encoding="utf-8")

    suite_seeds: list[tuple[str, Any]] = []
    suite_judge_ints: list[tuple[str, int]] = []
    suite_scope_viols: list[str] = []
    _walk_seeds_and_ints(suite_payload, "suite.json", suite_seeds, suite_judge_ints, suite_scope_viols)
    assert suite_judge_ints == []
    assert suite_scope_viols == []
    assert all(_is_int_seed(v) and v not in JUDGE_SEED_SET for _, v in suite_seeds)

    pooled_seeds: set[int] = set()
    total_seed_refs = 0
    audited_artifact_kinds: set[str] = set()

    for run_dir in verified_dirs:
        report = _audit_run_folder_non_contamination(run_dir)
        assert report["passed"] is True, f"{run_dir.name} failed non-contamination audit: {report['violations']}"
        assert report["seeds"].isdisjoint(JUDGE_SEED_SET)
        assert report["seeds"].isdisjoint(HELDOUT_SEED_SET)
        assert report["seeds"].isdisjoint(TRAIN_SEED_SET)
        assert report["seeds"] <= DEV_SEED_SET
        pooled_seeds |= report["seeds"]
        total_seed_refs += report["seed_ref_count"]
        audited_artifact_kinds.update(report["files_audited"])

    assert total_seed_refs >= 5000
    assert len(pooled_seeds) == 350
    assert min(pooled_seeds) == 0
    assert max(pooled_seeds) == 5399
    assert max(pooled_seeds) < min(JUDGE_SEEDS)
    for expected_file in (
        "meta.json",
        "hall_of_fame.jsonl",
        "design_report.json",
        "skill_gap.json",
        "generations.json",
        "holdout_generalization.json",
        "episodes.json",
        "audit_report.json",
        "mole_log.json",
        "mole_decisions.jsonl",
    ):
        assert expected_file in audited_artifact_kinds


@pytest.mark.parametrize(
    ("artifact_name", "payload"),
    [
        (
            "meta.json",
            {
                "role": "adaptive_mole",
                "model_id": "gemini-4-carbon",
                "environment_scope": EXPECTED_SCOPE,
                "seed": 900000,
            },
        ),
        ("summary.json", {"seeds": [0, 1, 900015]}),
        ("hof.json", {"entries": [{"rank": 1, "eval_seed": 900022}]}),
        ("scenarios.json", {"scenarios": [{"name": "leak_probe", "design_seeds": [2, 900039]}]}),
        ("mole_log.json", {"tier": "hard", "seed": 900007, "clash_mole_log": []}),
        ("mole_decisions.jsonl", [{"day": 1, "tier": "medium", "seed": 900031, "leak": None, "frame": None}]),
    ],
)
def test_non_contamination_audit_catches_judge_seeds_and_bad_scope(
    tmp_path: Path,
    artifact_name: str,
    payload: Any,
) -> None:
    run_dir = tmp_path / "contaminated-run"
    run_dir.mkdir(parents=True)
    clean_meta = {
        "role": "adaptive_mole",
        "model_id": "gemini-4-carbon",
        "environment_scope": EXPECTED_SCOPE,
        "seeds": [0, 1, 2],
    }
    (run_dir / "meta.json").write_text(json.dumps(clean_meta, indent=2) + "\n", encoding="utf-8")

    target = run_dir / artifact_name
    if artifact_name.endswith(".jsonl"):
        target.write_text("\n".join(json.dumps(r) for r in payload) + "\n", encoding="utf-8")
    else:
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    rep = _audit_run_folder_non_contamination(run_dir)
    assert rep["passed"] is False
    assert any(v.startswith("judge_seed_contamination:") for v in rep["violations"])

    bad_scope_dir = tmp_path / "bad-scope-run"
    bad_scope_dir.mkdir(parents=True)
    bad_meta = dict(clean_meta, environment_scope="judged v1.4 benchmark")
    (bad_scope_dir / "meta.json").write_text(json.dumps(bad_meta, indent=2) + "\n", encoding="utf-8")
    bad_rep = _audit_run_folder_non_contamination(bad_scope_dir)
    assert bad_rep["passed"] is False
    assert any(v.startswith("scope_violation:") for v in bad_rep["violations"])


def test_mole_forge_4_runs_train_vs_holdout_seed_disjointness() -> None:
    forge_dirs = sorted(p for p in ROLES_DIR.iterdir() if p.is_dir() and p.name.startswith("mole-forge-"))
    assert [d.name for d in forge_dirs] == [
        "mole-forge-carbon-easy-deep",
        "mole-forge-carbon-hard-deep",
        "mole-forge-carbon-med-deep",
        "mole-forge-carbon-v14",
    ]

    expected_confirm = list(range(5020, 5060))
    allowed_dev_pool = set(range(0, 20)) | set(range(4000, 4020))
    pooled_dev: set[int] = set()
    pooled_confirm: set[int] = set()

    for rdir in forge_dirs:
        meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
        gens = json.loads((rdir / "generations.json").read_text(encoding="utf-8"))
        holdout = json.loads((rdir / "holdout_generalization.json").read_text(encoding="utf-8"))

        dev_seeds = meta["dev_seeds"]
        fresh_seeds = meta["fresh_seeds"]
        splits = holdout["splits"]
        unseen_seeds = splits["unseen_seeds"]
        confirm_seeds = splits["confirm_seeds"]
        combined_seeds = splits["combined_seeds"]

        assert isinstance(dev_seeds, list) and len(dev_seeds) >= 10
        assert gens["dev_seeds"] == dev_seeds
        assert isinstance(fresh_seeds, list) and len(fresh_seeds) >= 10
        assert confirm_seeds == expected_confirm
        assert len(confirm_seeds) == 40
        assert all(s >= 5000 for s in confirm_seeds)

        dev_set = set(dev_seeds)
        fresh_set = set(fresh_seeds)
        unseen_set = set(unseen_seeds)
        confirm_set = set(confirm_seeds)
        combined_set = set(combined_seeds)

        assert dev_set <= allowed_dev_pool
        assert all(s < 5000 for s in dev_set)
        assert combined_set == (unseen_set | confirm_set)
        assert _check_split_disjointness(unseen_set, confirm_set) == set()
        assert _check_split_disjointness(dev_set, fresh_set) == set()
        assert _check_split_disjointness(dev_set, unseen_set) == set()
        assert _check_split_disjointness(dev_set, confirm_set) == set()
        assert _check_split_disjointness(dev_set, combined_set) == set()
        assert _check_split_disjointness(fresh_set, confirm_set) == set()

        for split_set in (dev_set, fresh_set, unseen_set, confirm_set):
            assert split_set.isdisjoint(JUDGE_SEED_SET)
            assert split_set <= DEV_SEED_SET

        pooled_dev |= dev_set
        pooled_confirm |= confirm_set

    assert _check_split_disjointness(set(range(0, 20)), pooled_confirm) == set()
    assert _check_split_disjointness(pooled_dev, pooled_confirm) == set()
    assert pooled_confirm == set(range(5020, 5060))


def test_paired_designer_10_runs_train_vs_holdout_seed_disjointness() -> None:
    paired_dirs = sorted(p for p in ROLES_DIR.iterdir() if p.is_dir() and p.name.startswith("paired-"))
    assert len(paired_dirs) == 10

    dev_0_19 = set(range(0, 20))
    pooled_design: set[int] = set()
    pooled_holdout: set[int] = set()
    runs_with_5000_plus_holdout = 0

    for rdir in paired_dirs:
        meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
        design_doc = json.loads((rdir / "design_report.json").read_text(encoding="utf-8"))
        sg_doc = json.loads((rdir / "skill_gap.json").read_text(encoding="utf-8"))

        meta_design = meta.get("design_seeds") if "design_seeds" in meta else meta.get("seeds")
        doc_design = design_doc.get("design_seeds") if "design_seeds" in design_doc else design_doc.get("seeds")
        assert isinstance(meta_design, list) and len(meta_design) >= 5
        assert meta_design == doc_design

        design_tree_seeds: list[tuple[str, Any]] = []
        _walk_seeds_and_ints(design_doc, "design_report.json", design_tree_seeds, [], [])
        design_episode_seeds = {int(v) for _, v in design_tree_seeds if _is_int_seed(v)}
        design_set = set(meta_design)
        assert design_episode_seeds <= design_set
        assert design_set <= dev_0_19

        sg_seeds = sg_doc["seeds"]
        assert isinstance(sg_seeds, list) and len(sg_seeds) >= 20
        assert sg_seeds == list(range(int(sg_doc["seed_start"]), int(sg_doc["seed_end"]) + 1))
        if "eval_seeds" in meta:
            assert meta["eval_seeds"] == sg_seeds

        holdout_set = set(sg_seeds)
        assert all(s >= 20 for s in holdout_set)
        if min(holdout_set) >= 5000:
            runs_with_5000_plus_holdout += 1
            assert len(sg_seeds) in {20, 40}
        else:
            assert rdir.name == "paired-skill-designer-carbon-hard"
            assert sg_seeds == list(range(20, 40))

        assert _check_split_disjointness(design_set, holdout_set) == set()
        assert _check_split_disjointness(dev_0_19, holdout_set) == set()
        assert design_set.isdisjoint(JUDGE_SEED_SET)
        assert holdout_set.isdisjoint(JUDGE_SEED_SET)
        assert design_set <= DEV_SEED_SET
        assert holdout_set <= DEV_SEED_SET

        pooled_design |= design_set
        pooled_holdout |= holdout_set

    assert runs_with_5000_plus_holdout == 9
    assert pooled_design == dev_0_19
    assert _check_split_disjointness(pooled_design, pooled_holdout) == set()
    assert _check_split_disjointness({0, 14, 19}, {14, 5200}) == {14}


def test_cross_doc_and_consolidator_parity_14_runs_57_hof_49_paired(tmp_path: Path) -> None:
    recomputed_suite = mc.consolidate_adaptive_mole(
        root=ROOT,
        out_dir=tmp_path / "suite_check",
        doc_path=tmp_path / "adaptive_mole_check.md",
    )
    committed_suite = json.loads(SUITE_JSON_PATH.read_text(encoding="utf-8"))
    committed_summary_md = SUITE_MD_PATH.read_text(encoding="utf-8")
    carbon_doc_text = ADAPTIVE_MOLE_DOC_PATH.read_text(encoding="utf-8")
    replay_doc_text = ADAPTIVE_MOLE_REPLAY_DOC_PATH.read_text(encoding="utf-8")

    assert recomputed_suite == committed_suite
    assert (tmp_path / "suite_check" / "summary.md").read_text(encoding="utf-8") == committed_summary_md
    assert (tmp_path / "adaptive_mole_check.md").read_text(encoding="utf-8") == carbon_doc_text

    for doc_txt in (carbon_doc_text, replay_doc_text):
        assert EXPECTED_SCOPE in doc_txt
        assert EXPECTED_V14_FINGERPRINT in doc_txt

    loaded_runs = mra.load_strategy_runs(ROLES_DIR)
    assert len(loaded_runs) == 14
    mra_forge = {r.run_id: r for r in loaded_runs if r.source_kind == "mole_forge"}
    mra_paired = {r.run_id: r for r in loaded_runs if r.source_kind == "paired_designer"}
    assert len(mra_forge) == 4
    assert len(mra_paired) == 10

    mc_forge = {Path(r["run_dir"]).name: r for r in committed_suite["mole_forge_suite"]["runs"]}
    mc_paired = {Path(r["run_dir"]).name: r for r in committed_suite["paired_designer_suite"]["runs"]}
    assert set(mc_forge.keys()) == set(mra_forge.keys())
    assert set(mc_paired.keys()) == set(mra_paired.keys())

    carbon_forge_sec = _extract_section(
        carbon_doc_text,
        f"{HASH}{HASH} 3. Mole Forge Evolutionary DSL Suite",
    )
    carbon_forge_rows = {
        Path(_strip_ticks(r["Run Folder"])).name: r for r in _parse_markdown_table(carbon_forge_sec)
    }
    carbon_paired_sec = _extract_section(
        carbon_doc_text,
        f"{HASH}{HASH} 4. PAIRED Solvable Scenario Designer Suite",
    )
    carbon_paired_rows = {
        Path(_strip_ticks(r["Run Folder"])).name: r for r in _parse_markdown_table(carbon_paired_sec)
    }

    replay_per_run_sec = _extract_section(
        replay_doc_text,
        f"{HASH}{HASH} 2. Per-Run Deterministic Replay & Privilege Audit",
    )
    replay_rows = _parse_markdown_table(replay_per_run_sec)
    assert len(replay_rows) == 14
    replay_by_id = {Path(_strip_ticks(r["Run Folder"])).name: r for r in replay_rows}
    assert set(replay_by_id.keys()) == (set(mc_forge.keys()) | set(mc_paired.keys()))

    assert set(carbon_forge_rows.keys()) == set(mra_forge.keys())
    assert set(carbon_paired_rows.keys()) == set(mra_paired.keys())

    for run_id, mra_run in sorted(mra_forge.items()):
        mc_row = mc_forge[run_id]
        c_doc_row = carbon_forge_rows[run_id]
        r_doc_row = replay_by_id[run_id]
        meta = json.loads((mra_run.run_dir / "meta.json").read_text(encoding="utf-8"))

        assert mc_row["tier"] == mra_run.tier
        assert _strip_ticks(c_doc_row["Tier"]) == mra_run.tier
        assert _strip_ticks(r_doc_row["Tier"]) == mra_run.tier
        assert _strip_ticks(r_doc_row["Source Kind"]) == "mole_forge"
        assert mra_run.top_entry.label == "rank_1"
        assert _strip_ticks(r_doc_row["Top Strategy Label"]) == mra_run.top_entry.label
        assert int(r_doc_row["Entries"]) == len(mra_run.entries)
        assert mra.canonical_strategy_json(meta["top_strategy"]) == mra.canonical_strategy_json(mra_run.top_strategy)

    for run_id, mra_run in sorted(mra_paired.items()):
        mc_row = mc_paired[run_id]
        c_doc_row = carbon_paired_rows[run_id]
        r_doc_row = replay_by_id[run_id]
        sg_doc = json.loads((mra_run.run_dir / "skill_gap.json").read_text(encoding="utf-8"))

        assert mc_row["tier"] == mra_run.tier
        assert _strip_ticks(c_doc_row["Tier"]) == mra_run.tier
        assert _strip_ticks(r_doc_row["Tier"]) == mra_run.tier
        assert _strip_ticks(r_doc_row["Source Kind"]) == "paired_designer"

        assert mc_row["top_scenario_name"] == mra_run.top_entry.label
        assert _strip_ticks(c_doc_row["Top Scenario"]) == mra_run.top_entry.label
        assert _strip_ticks(r_doc_row["Top Strategy Label"]) == mra_run.top_entry.label

        kept_str, valid_str = c_doc_row["Kept / Valid"].split("/")
        assert int(kept_str) == mc_row["n_kept"] == len(mra_run.entries) == int(r_doc_row["Entries"])
        assert int(valid_str) == mc_row["n_llm_valid"]
        assert mra.canonical_strategy_json(sg_doc["selected_scenario"]) == mra.canonical_strategy_json(
            mra_run.top_strategy
        )

    hof_count_mra = sum(len(r.entries) for r in mra_forge.values())
    paired_count_mra = sum(len(r.entries) for r in mra_paired.values())
    iso_summary = mc.audit_committed_mole_runs(ROLES_DIR, ROOT)

    assert hof_count_mra == 57
    assert iso_summary["strategies_checked"] == 57
    assert committed_suite["repo_isolation_audit"]["strategies_checked"] == 57
    assert "`57`\n   Hall-of-Fame DSL strategies" in carbon_doc_text
    assert "`57` `mole_forge` Hall-of-Fame strategies" in replay_doc_text

    assert paired_count_mra == 49
    assert committed_suite["paired_designer_suite"]["overall"]["total_kept"] == 49
    assert committed_suite["paired_designer_suite"]["overall"]["total_llm_valid"] == 56
    assert "`49/56` (`87.50%`)" in carbon_doc_text
    assert "`49` `paired_designer` kept strategies" in replay_doc_text

    all_entries = [entry for run in loaded_runs for entry in run.entries]
    eq_all = mra.compute_equivalence_classes(all_entries)
    assert eq_all.n_strategies == hof_count_mra + paired_count_mra == 106
    assert eq_all.n_syntactic_unique == 105
    assert eq_all.n_equivalence_classes == 93

    replay_kind_sec = _extract_section(replay_doc_text, f"{HASH}{HASH}{HASH} By Source Kind")
    replay_kind_rows = {_strip_ticks(r["Source Kind"]): r for r in _parse_markdown_table(replay_kind_sec)}
    assert int(replay_kind_rows["mole_forge"]["Runs"]) == 4
    assert int(replay_kind_rows["mole_forge"]["Loaded Entries"]) == 57
    assert int(replay_kind_rows["paired_designer"]["Runs"]) == 10
    assert int(replay_kind_rows["paired_designer"]["Loaded Entries"]) == 49
    assert int(replay_kind_rows["overall"]["Runs"]) == 14
    assert int(replay_kind_rows["overall"]["Loaded Entries"]) == 106

    cli_sec = _extract_section(replay_doc_text, f"{HASH}{HASH} 4. Verbatim CLI Summary & Keyless Reproduction")
    cli_lines = _extract_fenced_block(cli_sec, "text").splitlines()
    assert "runs=14 (mole_forge=4, paired_designer=10)" in cli_lines[-1]
    assert "all_strategies_classes=93/106" in cli_lines[-1]


def test_suite_omits_meta_json_and_deduplicated_totals_match_exact_39_folder_sum(tmp_path: Path) -> None:
    assert SUITE_DIR.is_dir()
    assert SUITE_JSON_PATH.is_file()
    assert SUITE_MD_PATH.is_file()
    assert not (SUITE_DIR / "meta.json").exists()

    discovered_meta_files = sorted(ROLES_DIR.rglob("meta.json"))
    verified_dirs = sorted(p for p in ROLES_DIR.iterdir() if p.is_dir() and p.name != mc.SUITE_DIR_NAME)
    assert len(discovered_meta_files) == 39
    assert [p.parent for p in discovered_meta_files] == verified_dirs

    raw_calls = 0
    raw_in = 0
    raw_out = 0
    raw_thinking = 0
    raw_cached = 0
    raw_cost = 0.0
    normalized_usages: list[dict[str, Any]] = []

    for meta_file in discovered_meta_files:
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        u = meta["usage"]
        raw_calls += int(u["calls"])
        raw_in += int(u["in"])
        raw_out += int(u["out"])
        raw_thinking += int(u["thinking"])
        raw_cached += int(u["cached"])
        raw_cost = round(raw_cost + float(u["cost_usd"]), 6)
        normalized_usages.append(mc.normalize_usage(u, meta["model_id"]))

    summed = mc.sum_usages(normalized_usages)
    assert raw_calls == summed["calls"] == 2257
    assert raw_in == summed["in"] == 37_033_571
    assert raw_out == summed["out"] == 152_090
    assert raw_thinking == summed["thinking"] == 641_214
    assert raw_cached == summed["cached"] == 33_025_731
    assert summed["total_tokens"] == raw_in + raw_out + raw_thinking == 37_826_875
    assert raw_cost == summed["cost_usd"] == pytest.approx(19.251309, abs=1e-9)

    suite = json.loads(SUITE_JSON_PATH.read_text(encoding="utf-8"))
    tot = suite["totals"]
    assert tot["verified_folders"] == 39
    assert tot["n_verified_runs"] == 39
    assert tot["calls"] == 2257
    assert tot["in"] == 37_033_571
    assert tot["out"] == 152_090
    assert tot["thinking"] == 641_214
    assert tot["cached"] == 33_025_731
    assert tot["total_tokens"] == 37_826_875
    assert tot["cost_usd"] == pytest.approx(19.251309, abs=1e-9)

    by_suite = tot["by_suite"]
    expected_slices = ("clash_suite", "live_arena_suite", "mole_forge_suite", "paired_designer_suite", "other_verified_runs")
    assert set(by_suite.keys()) == set(expected_slices)
    assert [by_suite[k]["verified_folders"] for k in expected_slices] == [16, 8, 4, 10, 1]
    assert sum(by_suite[k]["verified_folders"] for k in expected_slices) == 39
    assert sum(by_suite[k]["calls"] for k in expected_slices) == 2257
    assert sum(by_suite[k]["in"] for k in expected_slices) == 37_033_571
    assert sum(by_suite[k]["out"] for k in expected_slices) == 152_090
    assert sum(by_suite[k]["thinking"] for k in expected_slices) == 641_214
    assert sum(by_suite[k]["cached"] for k in expected_slices) == 33_025_731
    assert round(sum(by_suite[k]["cost_usd"] for k in expected_slices), 6) == pytest.approx(19.251309, abs=1e-9)

    carbon_doc_text = ADAPTIVE_MOLE_DOC_PATH.read_text(encoding="utf-8")
    for expected_snippet in (
        "`39` folders, `2257` Gemini API calls",
        "`37,033,571` input / `152,090` output / `641,214` thinking / `33,025,731` cached tokens",
        "`$19.251309`",
        "`carbon-vs-carbon-suite/` omits `meta.json` so role scanners do not double-count tokens or costs.",
    ):
        assert expected_snippet in carbon_doc_text
        if "omits `meta.json`" in expected_snippet or "$19.251309" in expected_snippet:
            assert expected_snippet in SUITE_MD_PATH.read_text(encoding="utf-8")

    totals_sec = _extract_section(carbon_doc_text, f"{HASH}{HASH} 5. De-Duplicated Totals")
    totals_rows = _parse_markdown_table(totals_sec)
    assert len(totals_rows) == 6
    for row, key in zip(totals_rows[:5], expected_slices, strict=True):
        bs = by_suite[key]
        assert _strip_ticks(row["Suite Slice"]) == key
        assert int(row["Verified Folders"]) == bs["verified_folders"]
        assert int(row["Calls"]) == bs["calls"]
        assert int(row["Input Tokens"].replace(",", "")) == bs["in"]
        assert int(row["Output Tokens"].replace(",", "")) == bs["out"]
        assert int(row["Thinking Tokens"].replace(",", "")) == bs["thinking"]
        assert int(row["Cached Tokens"].replace(",", "")) == bs["cached"]
        assert row["Cost (USD)"] == f"${bs['cost_usd']:.6f}"

    grand_row = totals_rows[5]
    assert _strip_bold(grand_row["Suite Slice"]) == "total"
    assert int(_strip_bold(grand_row["Verified Folders"])) == 39
    assert int(_strip_bold(grand_row["Calls"])) == 2257
    assert int(_strip_bold(grand_row["Input Tokens"]).replace(",", "")) == 37_033_571
    assert int(_strip_bold(grand_row["Output Tokens"]).replace(",", "")) == 152_090
    assert int(_strip_bold(grand_row["Thinking Tokens"]).replace(",", "")) == 641_214
    assert int(_strip_bold(grand_row["Cached Tokens"]).replace(",", "")) == 33_025_731
    assert _strip_bold(grand_row["Cost (USD)"]) == "$19.251309"

    guard_suite_dir = tmp_path / "guard_suite"
    guard_suite_dir.mkdir(parents=True)
    bogus_meta = {
        "role": "adaptive_mole",
        "model_id": "gemini-4-carbon",
        "commit": "abcdef1234567890",
        "usage": {"calls": 99999, "in": 99999999, "out": 999999, "cost_usd": 9999.0},
    }
    (guard_suite_dir / "meta.json").write_text(json.dumps(bogus_meta), encoding="utf-8")
    guarded = mc.consolidate_adaptive_mole(root=ROOT, out_dir=guard_suite_dir, doc_path=False)
    assert not (guard_suite_dir / "meta.json").exists()
    assert guarded["totals"]["verified_folders"] == 39
    assert guarded["totals"]["calls"] == 2257
    assert guarded["totals"]["cost_usd"] == pytest.approx(19.251309, abs=1e-9)
