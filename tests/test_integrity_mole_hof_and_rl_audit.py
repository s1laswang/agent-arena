from __future__ import annotations

import io
import json
import random
import tokenize
from pathlib import Path

import pytest

from canary import rules
from canary.mole.dsl import MoleDoc, MoleView
from canary.world import generate_world
from scripts import integrity_mole_hof_and_rl_audit as audit

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "integrity_mole_hof_and_rl_audit.py"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "integrity_mole_hof_and_rl_audit.md"
TEST_PATH = Path(__file__).resolve()


@pytest.fixture(scope="module")
def quick_bundle(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    out_dir = tmp_path_factory.mktemp("w6_quick")
    assert audit.main(["--quick", "--only-part", "a", "--out-dir", str(out_dir), "--workers", "1"]) == 0
    assert audit.main(["--quick", "--only-part", "b_dedupe", "--out-dir", str(out_dir), "--workers", "1"]) == 0
    assert (
        audit.main(
            [
                "--quick",
                "--only-part",
                "b_matrix",
                "--only-mole",
                "default_hard_5dept",
                "--out-dir",
                str(out_dir),
                "--workers",
                "1",
            ]
        )
        == 0
    )
    assert (
        audit.main(
            [
                "--quick",
                "--only-part",
                "b_matrix",
                "--only-mole",
                "rl_final_hard_rl_4dept",
                "--out-dir",
                str(out_dir),
                "--workers",
                "1",
            ]
        )
        == 0
    )
    rc = audit.main(
        [
            "--quick",
            "--only-part",
            "c",
            "--resume",
            "--out-dir",
            str(out_dir),
            "--workers",
            "1",
            "--check-report",
            str(REPORT_PATH),
        ]
    )
    assert rc == 0
    summary = json.loads((out_dir / "audit_summary_quick.json").read_text(encoding="utf-8"))
    return {"out_dir": out_dir, "summary": summary}


def test_part_a_zero_leak_and_canary_peeking_controls(quick_bundle: dict[str, object]) -> None:
    summary = quick_bundle["summary"]
    part_a = summary["part_a"]
    assert part_a["all_ok"] is True
    assert part_a["schema_forbidden_hits"] == []
    assert all(v == 0 for v in part_a["secret_exposures"].values())
    assert all(v == 0 for k, v in part_a["canary_mutation_probes"].items() if k != "n_seeds_probed")
    assert part_a["interview_and_belief_non_interference"]["divergences"] == 0
    assert part_a["action_boundary_enforcement"]["p_leak_bypass_count"] == 0
    assert part_a["action_boundary_enforcement"]["unheld_or_window_or_repeat_violations"] == 0
    assert part_a["action_boundary_enforcement"]["framing_cap_violations"] == 0
    assert part_a["action_boundary_enforcement"]["restricted_mole_post_window_leaks"] == 0
    assert part_a["action_boundary_enforcement"]["panel_fix_a_clearance_never_binds"] is True
    assert part_a["lawful_moles_all_clean"] is True
    assert part_a["positive_controls_caught_below_1e6"] is True

    cheater = audit.CheatingCanaryPeekMole(use_doc_id_prefix=True)
    view_both = MoleView(
        day=1,
        docs=(MoleDoc("c0", "Memo", 12, 0), MoleDoc("d1-0", "Memo", 12, 0)),
        days_since_last_leak=1,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=2,
        peers=("e01", "e02"),
        restricted_peers=(),
        decoy="e01",
        can_leak=True,
        select_weights=(1.0, 1.0),
    )
    assert cheater.decide(view_both, random.Random(0))["leak"] == "d1-0"
    view_only_can = MoleView(
        day=1,
        docs=(MoleDoc("c0", "Memo", 12, 0),),
        days_since_last_leak=1,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=1,
        peers=("e01", "e02"),
        restricted_peers=(),
        decoy="e01",
        can_leak=True,
        select_weights=(1.0,),
    )
    assert cheater.decide(view_only_can, random.Random(0))["leak"] is None


def test_part_b_dedupe_matrix_and_hard_rl_dept_issue(quick_bundle: dict[str, object]) -> None:
    summary = quick_bundle["summary"]
    dedupe = summary["part_b"]["deduplication"]
    assert dedupe["configs_and_files"]["hard_forge_unset_env_matches_hof_v12"] is True
    assert dedupe["rl_hof_vs_policy_final_max_abs_diff"] == 0.0
    assert dedupe["rl_final_vs_policy_it80_max_abs_diff"] == 0.0
    assert dedupe["v12_survivor_source_ranks"] == [2]
    assert dedupe["v13_survivor_source_ranks"] == [8]

    matrix = summary["part_b"]["matrix"]
    row_5d = matrix["default_hard_5dept"]
    row_4d = matrix["rl_final_hard_rl_4dept"]
    assert row_5d["dept_count"] == 5
    assert row_4d["dept_count"] == 4
    assert "Research" in row_5d["depts"]
    assert "Research" not in row_4d["depts"]
    for row in (row_5d, row_4d):
        assert row["checks"]["do_nothing_exact_zero"] is True
        assert row["checks"]["stop_early_exact_zero"] is True
        assert row["checks"]["non_canary_zero_canary_calls"] is True
        assert row["checks"]["zero_non_solver_positive_exploits"] is True

    w_hard = generate_world("hard", 0, rules.tier_params("hard"))
    w_rl = generate_world("hard_rl", 0, rules.tier_params("hard_rl"))
    assert len(w_hard.depts) == 5
    assert len(w_rl.depts) == 4

    issue_ids = {item["id"] for item in summary["report_only_issues"]}
    assert {
        "ISSUE-W1-HARD-RL-DEPTS",
        "ISSUE-W6-DEFAULT-HOF-V12-AND-NO-V14",
        "ISSUE-W6-ARENA-LLM-MOLE-SURFACE",
    } <= issue_ids


def test_part_c_fuzz_all_moles_clean(quick_bundle: dict[str, object]) -> None:
    part_c = quick_bundle["summary"]["part_c"]
    assert part_c["fuzz_complete"] is True
    assert part_c["all_clean"] is True
    assert part_c["total_invariant_violations"] == 0
    assert part_c["best_non_solver_score"] == 0.0
    assert set(part_c["per_mole"]) == set(audit.FUZZ_MOLE_ORDER)
    assert part_c["total_genomes"] == len(audit.FUZZ_MOLE_ORDER) * audit.PART_C_QUICK_BUDGET


def test_workers_guard_and_report_validator(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="workers must be 1"):
        audit.run_audit(quick=True, out_dir=tmp_path, workers=2)
    with pytest.raises(SystemExit):
        audit.main(["--quick", "--out-dir", str(tmp_path), "--workers", "2"])

    clean_res = audit.check_report_text(REPORT_PATH)
    assert clean_res["ok"] is True

    em_dash = chr(0x2014)
    bad_kw = "pre-" + "reg"
    bad_report = tmp_path / "bad.md"
    bad_report.write_text(
        REPORT_PATH.read_text(encoding="utf-8") + f"\n{bad_kw}istered {em_dash} test\n",
        encoding="utf-8",
    )
    bad_res = audit.check_report_text(bad_report)
    assert bad_res["ok"] is False
    assert em_dash in bad_res["forbidden_dashes"]
    assert bad_kw in bad_res["forbidden_prereg"]


def test_owned_files_strict_hygiene() -> None:
    forbidden_dashes = (chr(0x2014), chr(0x2013), chr(0x2212))
    for path in (SCRIPT_PATH, REPORT_PATH, TEST_PATH):
        assert path.is_file()
        assert path.stat().st_size <= 130 * 1024
        text = path.read_text(encoding="utf-8")
        for ch in forbidden_dashes:
            assert ch not in text

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        comments = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == []

    md_low = REPORT_PATH.read_text(encoding="utf-8").lower()
    assert "pre-reg" not in md_low
    assert "prereg" not in md_low
    assert "post-hoc lock" in md_low
