from __future__ import annotations

import importlib.util
import json
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

import pytest

from canary import rules, world
from canary.types import LedgerEntry, ToolResult

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_megahunt_and_corpus_v14.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_megahunt_and_corpus_v14.md"
TEST_PATH = Path(__file__).resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("integrity_megahunt_and_corpus_v14", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sweep_mod = _load_module()


@pytest.fixture(scope="module")
def quick_run(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("w4_quick")
    before_secret = world._SET_SECRET
    rc = sweep_mod.main([
        "--quick",
        "--workers",
        "1",
        "--out-dir",
        str(out_dir),
        "--check-report",
        str(REPORT_PATH),
    ])
    after_secret = world._SET_SECRET
    summary_file = out_dir / "megahunt_corpus_ladder_summary.json"
    assert summary_file.is_file()
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    return {
        "rc": rc,
        "before_secret": before_secret,
        "after_secret": after_secret,
        "summary": summary,
    }


def test_quick_end_to_end_megahunt_corpus_and_ladder(quick_run):
    assert quick_run["rc"] == 0
    assert quick_run["before_secret"] == quick_run["after_secret"]
    s = quick_run["summary"]
    assert s["all_passed"] is True
    assert s["tiers_version"] == "v1.4"
    assert s["known_v_mode"] is True
    assert s["quick"] is True
    assert s["workers"] == 1
    assert s["grand_total_env_calls"] >= 4000

    mh = s["megahunt"]
    assert mh["targets"] == ["easy", "medium", "hard", "hard_forge", "hard_rl"]
    assert mh["seed_bands"] == ["900000", "800000"]
    assert mh["total_violations"] == 0
    assert mh["best_non_solver_score"] == 0.0
    pc = mh["positive_control"]
    assert pc["detected"] is True
    assert {"truth_leak", "true_v_monotonicity", "post_end_effect"} <= set(pc["violation_kinds"])
    assert {"parallel_accuse_race", "barrier_16t_accuse_race"} & set(pc["violation_kinds"])

    ci = s["corpus_injection"]
    assert ci["corpus_rows_count"] >= 129
    assert ci["mined_shapes_total"] >= 90
    assert ci["mined_frontier_shapes"] >= 23
    assert ci["mined_reference_only_shapes"] >= 1
    assert ci["mined_shapes_total"] == ci["mined_frontier_shapes"] + ci["mined_reference_only_shapes"]
    assert ci["mined_unconditionally_invalid"] >= 8
    assert ci["mined_state_gated"] >= 82
    assert ci["mined_shapes_total"] == ci["mined_unconditionally_invalid"] + ci["mined_state_gated"]
    assert ci["corpus_py_missed_unconditional_frontier"] >= 6
    assert ci["illegal_acceptances_count"] == 0
    assert ci["corruptions_count"] == 0
    assert ci["panel_fix_d_parity"]["mismatches_count"] == 0
    assert ci["panel_fix_d_parity"]["checks"] >= 70

    la = s["ladder_replay"]
    assert la["files_audited"] >= 4
    assert la["total_episodes"] >= 1041
    assert la["total_replayable_episodes"] >= 1041
    assert la["total_replayed_episodes"] >= 4
    assert la["total_step_mismatches"] == 0
    assert la["all_replayed_consistent"] is True
    assert la["all_native_cells_aligned"] is True
    align_by_file = {a["file"]: a for a in la["ladder_json_alignments"]}
    assert "results/gemini/ladder.json" in align_by_file
    top = align_by_file["results/gemini/ladder.json"]
    assert top["json_episodes"] == 587
    assert top["gz_matched_native_episodes"] == 550
    assert top["imported_cells_sum_n"] == 37
    assert top["episode_total_reconciled"] is True
    assert all(c["committed_subset_exact_match"] is True for c in top["imported_cells"])

    issue_ids = [i["id"] for i in s["report_only_issues"]]
    assert issue_ids == [
        "ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER",
        "ISSUE-W4-LADDER-IMPORT-UNEXPORTED-AND-PARTIAL",
        "ISSUE-W4-LADDER-INPROC-WALL-CLOCK-TAIL",
    ]


def test_workers_guard_enforces_single_worker():
    with pytest.raises(ValueError, match="workers must be 1"):
        sweep_mod.run_all(quick=True, workers=2)
    with pytest.raises(SystemExit):
        sweep_mod.main(["--quick", "--workers", "2"])


def test_reconcile_replayed_step_and_detail_leak_detectors():
    r_fixd = ToolResult(False, {"detail": "unknown argument 'foo'"}, "invalid arguments")
    ok_old, stripped_old = sweep_mod.reconcile_replayed_step(
        r_fixd,
        {"ok": False, "data": {}, "error": "invalid arguments"},
    )
    assert ok_old is True and stripped_old is True

    ok_diff, stripped_diff = sweep_mod.reconcile_replayed_step(
        r_fixd,
        {"ok": False, "data": {"detail": "different detail"}, "error": "invalid arguments"},
    )
    assert ok_diff is False and stripped_diff is False

    @dataclass
    class _FakeWorld:
        mole: str = "e07"
        world_seed: int = 77712345

    class _LeakyDetailEnv:
        def __init__(self):
            self._world = _FakeWorld()
            self.p = rules.tier_params("easy")
            self._feed = []
            self.day = 1
            self.V = 1.0
            self.done = False
            self._costs = 0.0
            self._actions_today = 0
            self._canaries_today = 0
            self._restricted = set()
            self.docs = []

        def score(self) -> float:
            return 0.0

        def visible_V(self) -> float:
            return 1.0

        def ledger(self) -> list[LedgerEntry]:
            return []

        def call(self, tool: str, args: object) -> ToolResult:
            return ToolResult(
                False,
                {"detail": "invalid key mole=e07 on seed 77712345"},
                "invalid arguments",
            )

    aud = sweep_mod.AuditedEnvRunner(_LeakyDetailEnv(), "unit_detail_probe", check_internals=True)
    aud.call("interview", {"employee": "e00", "topic": "bad_topic"})
    kinds = {v["kind"] for v in aud.violations}
    assert "error_detail_unprompted_mole_id" in kinds
    assert "error_detail_world_seed_leak" in kinds


def test_report_hygiene_and_owned_files_strict_gates(tmp_path):
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    minus_sign = chr(0x2212)
    banned_a = "pre-" + "reg"
    banned_b = "pre" + "reg"
    co_author = "-".join(("Co", "Authored", "By"))

    bad_md = tmp_path / "bad.md"
    bad_md.write_text(f"bad {em_dash} {banned_a} {banned_b}\n", encoding="utf-8")
    bad_chk = sweep_mod.check_report_hygiene(bad_md)
    assert bad_chk["ok"] is False
    assert "em_dash" in bad_chk["problems"]
    assert f"banned_term:{banned_a}" in bad_chk["problems"]
    assert f"banned_term:{banned_b}" in bad_chk["problems"]

    rep_chk = sweep_mod.check_report_hygiene(REPORT_PATH)
    assert rep_chk == {"ok": True, "problems": []}

    rep_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert banned_a not in rep_txt.lower()
    assert banned_b not in rep_txt.lower()
    for token in (
        "post-hoc lock",
        "2,244,618",
        "1,845,969",
        "331,521",
        "67,128",
        "22,150",
        "5,475",
        "4,313",
        "1,041",
        "297",
        "900000-900039",
        "800000-800099",
        "1bc3e281",
        "ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER",
        "ISSUE-W4-LADDER-IMPORT-UNEXPORTED-AND-PARTIAL",
        "ISSUE-W4-LADDER-INPROC-WALL-CLOCK-TAIL",
    ):
        assert token in rep_txt, token

    for path in (SCRIPT_PATH, REPORT_PATH, TEST_PATH):
        assert path.is_file(), path
        assert path.stat().st_size <= 130 * 1024, (path, path.stat().st_size)
        txt = path.read_text(encoding="utf-8")
        assert em_dash not in txt, path
        assert en_dash not in txt, path
        assert minus_sign not in txt, path
        assert co_author.lower() not in txt.lower(), path

    for py_path in (SCRIPT_PATH, TEST_PATH):
        with open(py_path, "rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)
