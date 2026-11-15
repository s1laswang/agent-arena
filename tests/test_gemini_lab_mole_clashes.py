from __future__ import annotations

import dataclasses
import io
import json
import re
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.mole_arena import view_to_dict
from canary.env import Env
from canary.mole.dsl import MoleView
from canary.rules import JUDGE_SEEDS

ADAPTIVE_MOLE_ROOT = ROOT / "results" / "gemini" / "roles_carbon" / "adaptive_mole"

EXPECTED_CLASH_RUNS = (
    "carbon-vs-carbon-easy-seed0",
    "carbon-vs-carbon-seed0",
    "carbon-vs-carbon-med-seed1",
    "carbon-vs-carbon-med-seed2",
    "carbon-vs-carbon-med-seed3",
    "carbon-vs-carbon-med-seed4",
    "carbon-vs-carbon-med-seed5",
    "carbon-vs-carbon-med-seed6",
    "carbon-vs-carbon-med-seed7",
    "carbon-vs-carbon-med-seed8",
    "carbon-vs-carbon-med-seed9",
    "carbon-vs-carbon-hard-seed0",
    "carbon-vs-carbon-hard-seed1",
    "carbon-vs-carbon-hard-seed2",
    "carbon-vs-carbon-hard-seed3",
    "carbon-vs-carbon-hard-seed4",
)

COMPACT_FILES = frozenset({"meta.json", "mole_log.json", "summary.md"})
DROPPED_FILES = frozenset({"solver_check.json", "investigator_transcript.json"})
FORBIDDEN_MOLE_VIEW_KEYS = frozenset({"is_canary", "variant", "belief", "posterior"})

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
ESCAPED_EM_DASH = "\\" + "u2014"
ESCAPED_EN_DASH = "\\" + "u2013"

COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + "AI" + "za" + r"[0-9A-Za-z_-]{16,}")),
    ("sk_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + "s" + "k-" + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{12,}")),
    ("oauth_token", re.compile(r"(?<![0-9A-Za-z_])" + "ya" + r"29\.[0-9A-Za-z_-]{12,}")),
    ("world_secret", re.compile(r"\bCANARY_WORLD_SECRET\s*[:=]\s*['\"]?[0-9A-Za-z_-]{4,}")),
)
ENV_SECRET_RE = re.compile(
    r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|GOOGLE_GENERATIVE_AI_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|XAI_API_KEY)\b"
    r"[\"']?[ \t]*[:=][ \t]*(\"[^\"]+\"|'[^']+'|[^\s\"',}\]]+)"
)
SAFE_PLACEHOLDERS = frozenset({"", "null", "none", "false", "true", "unset", "redacted", "[redacted]", "<redacted>"})


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)


def _collect_dict_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k))
            keys.update(_collect_dict_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_collect_dict_keys(item))
    return keys


def _find_forbidden_mole_view_keys(obj: Any) -> set[str]:
    return _collect_dict_keys(obj) & FORBIDDEN_MOLE_VIEW_KEYS


def _scan_secrets(text: str) -> list[str]:
    hits: list[str] = []
    for name, rx in SECRET_PATTERNS:
        if rx.search(text):
            hits.append(name)
    for match in ENV_SECRET_RE.finditer(text):
        raw = match.group(1).strip().strip("\"'").strip()
        if raw.lower() in SAFE_PLACEHOLDERS or raw.startswith("$") or set(raw) <= {"*"}:
            continue
        if len(raw) >= 4:
            hits.append("env_api_key")
    return hits


def test_clash_directory_inventory_and_compact_layout() -> None:
    assert ADAPTIVE_MOLE_ROOT.is_dir()
    found_clash_dirs = sorted(
        p.name for p in ADAPTIVE_MOLE_ROOT.iterdir() if p.is_dir() and p.name.startswith("carbon-vs-carbon-")
    )
    assert "carbon-vs-carbon-suite" not in found_clash_dirs
    assert found_clash_dirs == sorted(EXPECTED_CLASH_RUNS)
    assert len(found_clash_dirs) == 16

    scenarios: list[tuple[str, int]] = []
    for run_name in EXPECTED_CLASH_RUNS:
        run_dir = ADAPTIVE_MOLE_ROOT / run_name
        files = {p.name for p in run_dir.iterdir() if p.is_file()}
        subdirs = [p.name for p in run_dir.iterdir() if p.is_dir()]
        assert subdirs == []
        assert files == COMPACT_FILES
        assert not (files & DROPPED_FILES)

        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        tier = meta["tier"]
        seed = meta["seed"]
        assert tier in {"easy", "medium", "hard"}
        assert isinstance(seed, int) and not isinstance(seed, bool)
        assert seed not in JUDGE_SEEDS
        scenarios.append((tier, seed))

    assert len(set(scenarios)) == 16
    assert sorted(s for t, s in scenarios if t == "easy") == [0]
    assert sorted(s for t, s in scenarios if t == "medium") == list(range(10))
    assert sorted(s for t, s in scenarios if t == "hard") == list(range(5))


@pytest.mark.parametrize("run_name", EXPECTED_CLASH_RUNS)
def test_clash_folder_meta_and_usage(run_name: str) -> None:
    run_dir = ADAPTIVE_MOLE_ROOT / run_name
    meta_txt = (run_dir / "meta.json").read_text(encoding="utf-8")
    summary_txt = (run_dir / "summary.md").read_text(encoding="utf-8")

    meta = json.loads(meta_txt)
    assert isinstance(meta, dict)
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["llm"] == "gemini:gemini-4-carbon"
    assert meta["role"] == "adaptive_mole"
    assert meta["subrole"] == "carbon_vs_carbon_clash"
    assert meta["tiers_version"] == "v1.4"
    assert meta["environment_scope"] == "arena mode, not the judged v1.4 environment"
    assert meta["episode_count"] == 2
    assert isinstance(meta["commit"], str) and COMMIT_RE.fullmatch(meta["commit"])
    assert meta["mole_clash_errors"] == 0
    assert meta["mole_solver_errors"] == 0
    assert "results/gemini_roles/" not in meta_txt
    assert "results/gemini/roles_carbon/" in meta["command"]

    usage = meta["usage"]
    assert isinstance(usage, dict)
    assert usage["calls"] > 0
    assert usage["in"] > 0
    assert usage["out"] > 0
    assert usage["thinking"] >= 0
    assert usage["cost_usd"] > 0.0

    inv_u = usage["clash_investigator"]
    mole_u = usage["clash_mole"]
    assert inv_u["calls"] > 0 and inv_u["in"] > 0 and inv_u["out"] > 0 and inv_u["cost_usd"] > 0.0
    assert mole_u["calls"] > 0 and mole_u["in"] > 0 and mole_u["out"] > 0 and mole_u["cost_usd"] > 0.0
    assert usage["calls"] == inv_u["calls"] + mole_u["calls"]
    assert usage["in"] == inv_u["in"] + mole_u["in"]
    assert usage["out"] == inv_u["out"] + mole_u["out"]

    assert summary_txt.startswith("# Head-to-Head Adversarial Clash Summary")
    assert "results/gemini_roles/" not in summary_txt
    assert f"results/gemini/roles_carbon/adaptive_mole/{run_name}" in summary_txt


@pytest.mark.parametrize("run_name", EXPECTED_CLASH_RUNS)
def test_clash_mole_log_clean_and_mole_view_keys(run_name: str) -> None:
    run_dir = ADAPTIVE_MOLE_ROOT / run_name
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    mlog_txt = (run_dir / "mole_log.json").read_text(encoding="utf-8")
    mlog = json.loads(mlog_txt)

    assert isinstance(mlog, dict)
    assert "results/gemini_roles/" not in mlog_txt
    assert mlog["model_id"] == "gemini-4-carbon"
    assert mlog["tier"] == meta["tier"]
    assert mlog["seed"] == meta["seed"]
    assert _find_forbidden_mole_view_keys(mlog) == set()

    clash_entries = mlog["clash_mole_log"]
    solver_entries = mlog["solver_mole_log"]
    assert mlog["log"] == clash_entries
    assert len(clash_entries) == meta["mole_clash_days"] > 0
    assert len(solver_entries) == meta["mole_solver_days"] > 0

    for entry in [*clash_entries, *solver_entries]:
        assert isinstance(entry, dict)
        assert entry["error"] is None
        assert isinstance(entry["day"], int) and entry["day"] >= 1
        move = entry["move"]
        assert set(move.keys()) == {"leak", "frame"}
        assert isinstance(entry["rejected"], list)

    mole_u = mlog["usage"]["clash_mole"]
    assert mole_u == meta["usage"]["clash_mole"]

    env = Env(tier=meta["tier"], seed=meta["seed"])
    raw_view = env._mole_view(1)
    dataclass_fields = {f.name for f in dataclasses.fields(MoleView)}
    assert not (dataclass_fields & FORBIDDEN_MOLE_VIEW_KEYS)
    serialized_view = view_to_dict(raw_view)
    assert _find_forbidden_mole_view_keys(serialized_view) == set()


def test_mole_view_key_audit_catches_privileged_keys() -> None:
    for bad_key in FORBIDDEN_MOLE_VIEW_KEYS:
        tampered = {
            "clash_mole_log": [
                {
                    "day": 1,
                    "mole_view": {"held_docs": [{"doc_id": "c1", bad_key: True}]},
                    "move": {"leak": None, "frame": None},
                    "error": None,
                }
            ]
        }
        assert _find_forbidden_mole_view_keys(tampered) == {bad_key}


def test_zero_secret_leaks_and_zero_forbidden_dashes() -> None:
    targets: list[Path] = [Path(__file__).resolve()]
    for run_name in EXPECTED_CLASH_RUNS:
        run_dir = ADAPTIVE_MOLE_ROOT / run_name
        for fname in sorted(COMPACT_FILES):
            targets.append(run_dir / fname)

    assert len(targets) == 1 + 16 * 3

    for fp in targets:
        txt = fp.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash in {fp}"
        assert EN_DASH not in txt, f"en dash in {fp}"
        assert ESCAPED_EM_DASH not in txt, f"escaped em dash in {fp}"
        assert ESCAPED_EN_DASH not in txt, f"escaped en dash in {fp}"
        assert _scan_secrets(txt) == [], f"secret pattern in {fp}"

    src = Path(__file__).resolve().read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
