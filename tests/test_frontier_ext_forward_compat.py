from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
import posixpath
import re
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import analyze_ext30to59_selection as selection_mod
from scripts import check_frontier_ext_replication as checker
from scripts import paired_gemini
from scripts import verify_replay

EXT_REL = Path("results") / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext"
COMM_V14_REL = Path("data") / "runs" / "committed" / "v1.4"
SELECTION_REPORT_PATH = ROOT / "docs" / "reports" / "frontier_ext30to59_selection_sensitivity.md"

G1_SEEDS = [34, 37]
FLEET_SEEDS = [30, 34, 42, 45, 48, 57, 58]
EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
MINUS_SIGN = chr(0x2212)
HASH_CHAR = chr(35)

G2_ARGON_TUPLE = (
    "OpenCode + gemini-4-argon over MCP (second Gemini 4 family; the API reports modelVersion "
    "gemini-4-argon for this id)",
    "v1.4/opencode-gemini-4-argon",
    "opencode:google/gemini-4-argon",
)
G2_HYDROGEN_TUPLE = (
    "OpenCode + gemini-4-hydrogen over MCP (third Gemini 4 family; the API reports modelVersion "
    "gemini-4-hydrogen for this id)",
    "v1.4/opencode-gemini-4-hydrogen",
    "opencode:google/gemini-4-hydrogen",
)
GPT55_V14_TUPLE = (
    "OpenCode + gpt-5.5 over MCP (second frontier family, OpenAI; pre-registered at cf394894; episodes where "
    "the agent announced an accusation but never called accuse score 0 and are valid)",
    "v1.4/opencode-gpt-5.5",
    "opencode:openai/gpt-5.5",
)

TOUCHED_PY_FILES = (
    Path("tests/test_frontier_ext_forward_compat.py"),
    Path("tests/test_frontier_ext_combined_parity.py"),
    Path("tests/test_frontier_replication_v14.py"),
    Path("tests/test_check_frontier_ext_replication.py"),
    Path("tests/test_ext30to59_selection_sensitivity.py"),
    Path("scripts/check_frontier_ext_replication.py"),
    Path("scripts/analyze_ext30to59_selection.py"),
)

TOUCHED_MD_FILES = (
    EXT_REL / "README.md",
    Path("docs/reports/frontier_ext30to59_selection_sensitivity.md"),
    Path("docs/reports/frontier_ext30to59_trajectories.md"),
    EXT_REL / "accuse_ext8_combined.md",
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _build_g1_and_pr3_episodes() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fleet_eps = _read_jsonl(ROOT / EXT_REL / "hard" / "episodes.jsonl")
    comm_eps = _read_jsonl(ROOT / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl")
    assert [ep["seed"] for ep in fleet_eps] == FLEET_SEEDS
    assert [ep["seed"] for ep in comm_eps] in (G1_SEEDS, EXT8_SEEDS)

    g1_eps = [ep for ep in comm_eps if ep["seed"] in G1_SEEDS]
    assert [ep["seed"] for ep in g1_eps] == G1_SEEDS
    assert g1_eps[0]["seed"] == 34 and g1_eps[0]["final_day"] == 5 and abs(g1_eps[0]["score"] - 0.79) < 1e-12

    by_seed = {ep["seed"]: ep for ep in fleet_eps}
    for ep in g1_eps:
        by_seed[ep["seed"]] = ep
    pr3_eps = [by_seed[seed] for seed in sorted(by_seed)]
    assert [ep["seed"] for ep in pr3_eps] == EXT8_SEEDS
    assert pr3_eps[1] == g1_eps[0]
    return fleet_eps, g1_eps, pr3_eps


def _make_staged_repo(base_dir: Path, committed_ext_episodes: list[dict[str, Any]]) -> Path:
    repo = base_dir / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "docs").symlink_to(ROOT / "docs")

    ext_dst = repo / EXT_REL
    ext_dst.mkdir(parents=True)
    for item in (ROOT / EXT_REL).iterdir():
        (ext_dst / item.name).symlink_to(item)

    comm_v14_dst = repo / COMM_V14_REL
    comm_v14_dst.mkdir(parents=True)
    for item in (ROOT / COMM_V14_REL).iterdir():
        if item.name == "opencode-gemini-4-carbon-ext":
            continue
        (comm_v14_dst / item.name).symlink_to(item)

    comm_ext_hard_dst = comm_v14_dst / "opencode-gemini-4-carbon-ext" / "hard"
    comm_ext_hard_dst.mkdir(parents=True)
    (comm_ext_hard_dst / "episodes.jsonl").write_text(
        "\n".join(json.dumps(ep) for ep in committed_ext_episodes) + "\n",
        encoding="utf-8",
    )
    return repo


def _strip_elapsed(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if k != "elapsed_s"}


_CACHED_G1_CHK: dict[str, Any] | None = None
_CACHED_PR3_CHK: dict[str, Any] | None = None
_CACHED_G1_SEL: dict[str, Any] | None = None


def test_forward_compat_justsilas_g1_two_seed_layout(tmp_path: Path, monkeypatch):
    global _CACHED_G1_CHK, _CACHED_G1_SEL
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    _, g1_eps, _ = _build_g1_and_pr3_episodes()
    g1_repo = _make_staged_repo(tmp_path, g1_eps)

    g1_ep_file = g1_repo / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    fleet_ep_file = g1_repo / EXT_REL / "hard" / "episodes.jsonl"

    buf_g1 = io.StringIO()
    with redirect_stdout(buf_g1):
        assert verify_replay.main([str(g1_ep_file)]) == 0
    assert "2/2 episodes replay-verified" in buf_g1.getvalue()

    buf_fleet = io.StringIO()
    with redirect_stdout(buf_fleet):
        assert verify_replay.main([str(fleet_ep_file)]) == 0
    assert "7/7 episodes replay-verified" in buf_fleet.getvalue()

    chk_report = checker.verify_frontier_ext_replication(g1_repo)
    _CACHED_G1_CHK = chk_report
    assert chk_report["ok"] is True
    assert chk_report["dedup_seeds"] == EXT8_SEEDS
    assert chk_report["replayed_episodes"] == 39
    assert [c["name"] for c in chk_report["checks"]] == [
        "manifests_and_dedup",
        "env_replay",
        "paired_tables",
        "tags_and_accuse",
    ]
    assert all(c["passed"] for c in chk_report["checks"])

    buf_sel = io.StringIO()
    with redirect_stdout(buf_sel):
        assert selection_mod.main(["--check", "--json", "--repo", str(g1_repo)]) == 0
    sel_payload = json.loads(buf_sel.getvalue())
    assert sel_payload["ok"] is True
    assert sel_payload["errors"] == []
    sel_data = sel_payload["data"]
    _CACHED_G1_SEL = sel_data
    assert sel_data["provenance"]["committed_ext_seeds_present"] == G1_SEEDS
    assert sel_data["provenance"]["dedup_ext8_seeds"] == EXT8_SEEDS
    assert sel_data["provenance"]["seed34_g1_precedence"]["g1_final_day"] == 5
    assert abs(sel_data["provenance"]["seed34_g1_precedence"]["g1_raw_score"] - 0.79) < 1e-12
    assert selection_mod.render_markdown(sel_data) == SELECTION_REPORT_PATH.read_text(encoding="utf-8")


def test_forward_compat_pr3_v14_runs_eight_seed_layout_and_seed34_precedence(tmp_path: Path, monkeypatch):
    global _CACHED_PR3_CHK
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    fleet_eps, g1_eps, pr3_eps = _build_g1_and_pr3_episodes()

    pr3_repo = _make_staged_repo(tmp_path / "pr3", pr3_eps)

    pr3_ep_file = pr3_repo / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    buf_replay = io.StringIO()
    with redirect_stdout(buf_replay):
        assert verify_replay.main([str(pr3_ep_file)]) == 0
    assert "8/8 episodes replay-verified" in buf_replay.getvalue()

    chk_pr3 = checker.verify_frontier_ext_replication(pr3_repo)
    _CACHED_PR3_CHK = chk_pr3
    assert chk_pr3["ok"] is True
    assert chk_pr3["dedup_seeds"] == EXT8_SEEDS
    assert chk_pr3["replayed_episodes"] == 45
    assert all(c["passed"] for c in chk_pr3["checks"])

    sel_g1 = (
        _CACHED_G1_SEL
        if _CACHED_G1_SEL is not None
        else selection_mod.analyze_selection(repo=_make_staged_repo(tmp_path / "justsilas", g1_eps))
    )
    buf_sel = io.StringIO()
    with redirect_stdout(buf_sel):
        assert selection_mod.main(["--check", "--json", "--repo", str(pr3_repo)]) == 0
    sel_pr3_payload = json.loads(buf_sel.getvalue())
    assert sel_pr3_payload["ok"] is True
    assert sel_pr3_payload["errors"] == []
    sel_pr3 = sel_pr3_payload["data"]
    assert sel_pr3["provenance"]["committed_ext_seeds_present"] == EXT8_SEEDS
    assert sel_pr3["provenance"]["dedup_ext8_seeds"] == EXT8_SEEDS
    assert sel_pr3["provenance"]["seed34_g1_precedence"] == sel_g1["provenance"]["seed34_g1_precedence"]
    assert sel_pr3["scenarios"] == sel_g1["scenarios"]
    assert sel_pr3["solver_cohorts"] == sel_g1["solver_cohorts"]
    assert sel_pr3["gemini_cohorts"] == sel_g1["gemini_cohorts"]
    assert sel_pr3["obs8_vs_unobs22"] == sel_g1["obs8_vs_unobs22"]
    assert sel_pr3["stratification"] == sel_g1["stratification"]
    assert sel_pr3["per_seed_30to59"] == sel_g1["per_seed_30to59"]
    assert selection_mod.render_markdown(sel_pr3) == selection_mod.render_markdown(sel_g1)

    fleet_seed34 = next(ep for ep in fleet_eps if ep["seed"] == 34)
    wrong_precedence_eps = [fleet_seed34 if ep["seed"] == 34 else ep for ep in pr3_eps]
    bad_repo = _make_staged_repo(tmp_path / "bad_seed34", wrong_precedence_eps)
    with pytest.raises(ValueError, match="seed 34"):
        selection_mod.analyze_selection(repo=bad_repo)


def test_forward_compat_g2_families_paired_gemini_groups_expansion(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    _, g1_eps, pr3_eps = _build_g1_and_pr3_episodes()
    root_comm_eps = _read_jsonl(ROOT / COMM_V14_REL / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl")
    is_pr3_root = len(root_comm_eps) == 8
    active_eps = pr3_eps if is_pr3_root else g1_eps

    cached_chk = _CACHED_PR3_CHK if is_pr3_root else _CACHED_G1_CHK
    baseline_chk = cached_chk if cached_chk is not None else checker.verify_frontier_ext_replication(ROOT)
    assert baseline_chk["ok"] is True
    baseline_sel = (
        _CACHED_G1_SEL
        if (_CACHED_G1_SEL is not None and not is_pr3_root)
        else selection_mod.analyze_selection(repo=ROOT)
    )
    baseline_md = selection_mod.render_markdown(baseline_sel)

    g2_repo = _make_staged_repo(tmp_path / "g2", active_eps)
    solver_seed0 = _read_jsonl(
        ROOT / COMM_V14_REL / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl"
    )[0]
    g2_min_root = tmp_path / "g2_min_committed"
    (g2_min_root / "v1.4" / "reference" / "solver-hard-s0").mkdir(parents=True)
    (g2_min_root / "v1.4" / "reference" / "solver-hard-s0" / "episodes.jsonl").write_text(
        json.dumps(solver_seed0) + "\n",
        encoding="utf-8",
    )
    for sub_dir, agent_id in (
        ("opencode-gemini-4-argon", "opencode:google/gemini-4-argon"),
        ("opencode-gemini-4-hydrogen", "opencode:google/gemini-4-hydrogen"),
        ("opencode-gpt-5.5", "opencode:openai/gpt-5.5"),
    ):
        for dst_root in (g2_repo / COMM_V14_REL, g2_min_root / "v1.4"):
            fam_hard = dst_root / sub_dir / "hard"
            if fam_hard.exists() or fam_hard.is_symlink():
                continue
            fam_hard.mkdir(parents=True)
            synth_ep = dict(solver_seed0, agent=agent_id)
            (fam_hard / "episodes.jsonl").write_text(json.dumps(synth_ep) + "\n", encoding="utf-8")

    orig_groups = paired_gemini.groups

    def _expanded_groups(version: str, model: str) -> list[tuple[str, str, str]]:
        base = list(orig_groups(version, model))
        if version != "v1.4":
            return base
        present_subs = {item[1] for item in base}
        extra_g2 = [t for t in (G2_ARGON_TUPLE, G2_HYDROGEN_TUPLE) if t[1] not in present_subs]
        flash_idx = next(
            (i for i, item in enumerate(base) if item[1] == "v1.4/opencode-gemini-3.5-flash"),
            len(base),
        )
        out = base[:flash_idx] + extra_g2 + base[flash_idx:]
        if GPT55_V14_TUPLE[1] not in present_subs:
            after_flash = next(
                (i + 1 for i, item in enumerate(out) if item[1] == "v1.4/opencode-gemini-3.5-flash"),
                len(out),
            )
            out = out[:after_flash] + [GPT55_V14_TUPLE] + out[after_flash:]
        return out

    monkeypatch.setattr(paired_gemini, "groups", _expanded_groups)
    expanded = paired_gemini.groups("v1.4", "gemini-4-carbon")
    expanded_subs = [item[1] for item in expanded]
    assert "v1.4/opencode-gemini-4-argon" in expanded_subs
    assert "v1.4/opencode-gemini-4-hydrogen" in expanded_subs
    assert "v1.4/opencode-gpt-5.5" in expanded_subs

    g2_rows = paired_gemini.rows_for(g2_min_root, "v1.4", "gemini-4-carbon", {0})
    g2_row_groups = {r["group"] for r in g2_rows if r["tier"] == "hard"}
    assert "v1.4/opencode-gemini-4-argon" in g2_row_groups
    assert "v1.4/opencode-gemini-4-hydrogen" in g2_row_groups
    assert "v1.4/opencode-gpt-5.5" in g2_row_groups

    buf_chk_json = io.StringIO()
    with redirect_stdout(buf_chk_json):
        rc_chk = checker.main(["--repo", str(g2_repo), "--json"])
    assert rc_chk == 0
    g2_chk = json.loads(buf_chk_json.getvalue())
    assert _strip_elapsed(g2_chk) == _strip_elapsed(baseline_chk)

    buf_sel_check = io.StringIO()
    with redirect_stdout(buf_sel_check):
        assert selection_mod.main(["--check", "--json", "--repo", str(g2_repo)]) == 0
    g2_sel_payload = json.loads(buf_sel_check.getvalue())
    assert g2_sel_payload["ok"] is True
    assert g2_sel_payload["errors"] == []
    g2_sel = g2_sel_payload["data"]
    assert g2_sel == baseline_sel
    assert selection_mod.render_markdown(g2_sel) == baseline_md


def test_strict_hygiene_comments_dashes_and_relative_links():
    for rel_py in TOUCHED_PY_FILES:
        py_path = ROOT / rel_py
        assert py_path.is_file(), f"missing python file: {rel_py}"
        src = py_path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {rel_py}"
        assert EN_DASH not in src, f"en dash in {rel_py}"
        assert MINUS_SIGN not in src, f"unicode minus in {rel_py}"
        comments = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == [], f"comments found in {rel_py}: {comments}"

    link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    link_counts: dict[str, int] = {}
    for rel_md in TOUCHED_MD_FILES:
        md_path = ROOT / rel_md
        assert md_path.is_file(), f"missing markdown file: {rel_md}"
        txt = md_path.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash in {rel_md}"
        assert EN_DASH not in txt, f"en dash in {rel_md}"
        assert MINUS_SIGN not in txt, f"unicode minus in {rel_md}"

        in_fence = False
        count = 0
        parent_posix = rel_md.parent.as_posix()
        for line in txt.splitlines():
            if line.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in link_re.finditer(line):
                raw_target = match.group(1).strip()
                target = raw_target.split(HASH_CHAR, 1)[0]
                if not target or target.startswith(("http://", "https://", "mailto:")):
                    continue
                resolved = posixpath.normpath(posixpath.join(parent_posix, target))
                assert not resolved.startswith(".."), f"link escapes repo in {rel_md}: {raw_target}"
                assert (ROOT / resolved).exists(), f"broken link in {rel_md}: {raw_target} -> {resolved}"
                count += 1
        link_counts[rel_md.as_posix()] = count

    readme_key = (EXT_REL / "README.md").as_posix()
    assert link_counts[readme_key] >= 23
    assert link_counts["docs/reports/frontier_ext30to59_selection_sensitivity.md"] >= 15
    assert link_counts["docs/reports/frontier_ext30to59_trajectories.md"] >= 20
