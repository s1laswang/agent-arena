from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.integrity_cost_and_trajectory_boundary_sweep as cost_sweep


@pytest.fixture(scope="module")
def quick_sweep_report() -> dict:
    t0 = time.perf_counter()
    c0 = time.process_time()
    rep = cost_sweep.run_cost_and_trajectory_boundary_sweep(quick=True)
    rep["_fixture_wall_s"] = time.perf_counter() - t0
    rep["_fixture_cpu_s"] = time.process_time() - c0
    return rep


def test_quick_sweep_all_nine_cells_and_eight_families(quick_sweep_report: dict) -> None:
    assert quick_sweep_report["_fixture_cpu_s"] < 2.5
    assert quick_sweep_report["mode"] == "quick"
    assert quick_sweep_report["live_llm_calls"] == 0
    assert quick_sweep_report["v14_tier_hash_preserved"] is True
    assert quick_sweep_report["v14_tier_hash_after"] == "a8f99c2537c91d72"
    assert quick_sweep_report["working_tree_unchanged"] is True
    assert quick_sweep_report["v15_available"] is True
    assert quick_sweep_report["v15_commit_sha"] == "de9cc50e"
    assert tuple(quick_sweep_report["v14_targets"]) == ("easy", "medium", "hard", "hard_forge", "hard_rl")
    assert tuple(quick_sweep_report["v15_targets"]) == ("easy", "medium", "hard", "hard_forge")
    assert quick_sweep_report["total_cells"] == 9
    assert quick_sweep_report["total_trajectories"] == 18
    assert quick_sweep_report["total_steps"] >= 900
    assert quick_sweep_report["total_rejected_calls"] >= 120
    assert quick_sweep_report["total_post_end_calls"] >= 20
    assert quick_sweep_report["total_invariant_violations"] == 0
    assert quick_sweep_report["max_rounded_v_drift"] == 0.0
    assert quick_sweep_report["max_vis_v_drift"] == 0.0
    assert quick_sweep_report["saturation_v_zero_reached"] == quick_sweep_report["saturation_trajectories_total"] >= 2
    assert quick_sweep_report["total_v_zero_pre_done_steps"] > 0
    assert quick_sweep_report["total_hidden_leak_masked_steps"] > 0

    for fname in cost_sweep.FAMILY_NAMES:
        ftot = quick_sweep_report["family_totals"][fname]
        assert ftot["trajectories"] >= 2
        assert ftot["steps"] > 0
        assert ftot["violations"] == 0
        assert ftot["max_rounded_v_drift"] == 0.0


def test_full_schedule_exceeds_2500_trajectories() -> None:
    sched = cost_sweep._cell_schedule(quick=False)
    per_cell = (
        sched["saturation_seeds"] * 4
        + sched["post_end_seeds"] * 4
        + sched["tool_cap_seeds"] * 2
        + sched["restrict_toggle_seeds"] * 2
        + sched["invalid_arg_seeds"] * 2
        + sched["float_seeds"] * 1
        + sched["known_v_dual_seeds"] * 2
        + sched["stateful_fuzz_walks"]
    )
    total_cells = len(cost_sweep.V14_TARGETS) + len(cost_sweep.V15_TARGETS)
    total_full_trajectories = per_cell * total_cells
    assert per_cell == 320
    assert total_cells == 9
    assert total_full_trajectories == 2880
    assert total_full_trajectories >= 2500


def test_six_planted_accounting_positive_controls(quick_sweep_report: dict) -> None:
    pc = quick_sweep_report["positive_controls"]
    assert pc["controls_total"] == 6
    assert pc["controls_caught"] == 6
    assert pc["all_caught"] is True

    controls = pc["controls"]
    assert set(controls.keys()) == set(cost_sweep.POSITIVE_CONTROL_NAMES)

    expected_signatures = {
        "PC1_negative_tool_cost": "v_monotone_or_range_violation",
        "PC2_post_done_accuse_overwrite": "post_end_state_mutation",
        "PC3_free_interview_on_error": "history_not_incremented",
        "PC4_visible_v_hidden_leak_sidechannel": "visible_v_hidden_leak_sidechannel",
        "PC5_score_gt_one_minus_loss_inflation": "score_exceeds_one_minus_loss",
        "PC6_action_budget_and_horizon_bypass": "day_out_of_bounds",
    }
    for cname, req_kind in expected_signatures.items():
        assert controls[cname]["caught"] is True
        assert controls[cname]["violation_count"] >= 2
        assert req_kind in controls[cname]["violation_kinds"]


def test_five_diagnostic_issue_probes(quick_sweep_report: dict) -> None:
    diag = quick_sweep_report["diagnostics"]

    d1 = diag["ISS-COST-01_peek_status_and_cap_boundary"]
    assert d1["v14_easy_cap"] == 300 and d1["v14_easy_peek_t0"] == 299
    assert d1["v14_hard_cap"] == 420 and d1["v14_hard_peek_t0"] == 419
    assert d1["v15_easy_peek_t0"] == 299
    assert d1["peek_at_exact_cap"] == -1
    assert d1["peek_at_cap_plus_one"] == -2
    assert d1["cap_step_result_omits_episode_over"] is True

    d2 = diag["ISS-COST-02_float_vs_decimal_closed_form"]
    assert d2["nonzero_raw_self_v_ulp_drift_steps"] > 0
    assert 0.0 < d2["max_raw_self_v_drift"] < 1e-12
    assert d2["max_rounded_10dp_v_drift"] == 0.0
    assert d2["max_visible_v_10dp_drift"] == 0.0

    d3 = diag["ISS-COST-03_v_zero_saturation_incentive"]
    assert d3["solver_accuse_ev_at_v0_p100"] == 0.0
    assert d3["solver_accuse_ev_at_v0_p095"] < 0.0
    assert d3["solver_strict_ev_gt_zero_blocks_v0_accuse"] is True

    d4 = diag["ISS-COST-04_regret_known_v_and_horizon"]
    assert d4["hard_seeds_probed"] == 1
    assert d4["sp_leak_days_mismatch_vs_true_leak_days"] == 1
    assert d4["horizon_advance_day_omits_v_field_count"] == 1
    assert d4["mean_sp_v_minus_true_v_day5"] > 0.0

    d5 = diag["ISS-COST-05_v15_branch_divergence_guards"]
    assert d5["v14_tiers_version_v12_sets_known_v_false"] is True
    assert d5["v14_known_v_restored_after_context"] is True
    assert d5["v15_tiers_version_v12_raises_keyerror"] is True
    assert d5["v15_hard_rl_raises_value_error"] is True
    assert d5["v14_invalid_arg_has_detail"] is True
    assert d5["v15_invalid_arg_has_detail"] is False


def test_shallow_ci_detached_and_nogit_fallback(tmp_path: Path) -> None:
    shallow_tmp = tmp_path / "shallow_detached_repo"
    git_dir = shallow_tmp / ".git"
    (git_dir / "objects" / "info").mkdir(parents=True)
    (git_dir / "objects" / "pack").mkdir(parents=True)
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "tags").mkdir(parents=True)
    detached_sha = "1111111111111111111111111111111111111111"
    (git_dir / "HEAD").write_text(detached_sha + "\n", encoding="utf-8")
    (git_dir / "shallow").write_text(detached_sha + "\n", encoding="utf-8")
    (git_dir / "config").write_text(
        "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n",
        encoding="utf-8",
    )
    (shallow_tmp / "README.txt").write_text("detached shallow checkout\n", encoding="utf-8")

    rep_shallow = cost_sweep.run_cost_and_trajectory_boundary_sweep(
        quick=True,
        repo_root=shallow_tmp,
        v14_targets=("easy", "hard_forge"),
        v15_targets=("easy", "hard_forge"),
    )
    assert rep_shallow["shallow_checkout_fallback"] is True
    assert rep_shallow["v15_source_mode"] == "embedded_zlib_b64"
    assert rep_shallow["v15_commit_sha"] == "de9cc50e"
    assert rep_shallow["v14_head_sha"] == "11111111"
    assert rep_shallow["total_cells"] == 4
    assert rep_shallow["total_trajectories"] == 8
    assert rep_shallow["total_invariant_violations"] == 0
    assert rep_shallow["positive_controls"]["all_caught"] is True
    assert rep_shallow["v14_tier_hash_preserved"] is True
    assert rep_shallow["working_tree_unchanged"] is True

    nogit_tmp = tmp_path / "nogit_dir"
    nogit_tmp.mkdir(parents=True)
    (nogit_tmp / "marker.txt").write_text("no git metadata\n", encoding="utf-8")
    assert cost_sweep.resolve_head_commit(nogit_tmp) == "nogit0000"
    assert cost_sweep.try_resolve_git_commit(repo_root=nogit_tmp) is None


def test_cli_quick_json_smoke(tmp_path: Path) -> None:
    out_file = tmp_path / "quick_smoke.json"
    rc = cost_sweep.main(
        [
            "--quick",
            "--v14-targets",
            "easy,hard_rl",
            "--v15-targets",
            "easy",
            "--json-out",
            str(out_file),
        ]
    )
    assert rc == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["total_cells"] == 3
    assert payload["total_trajectories"] == 6
    assert payload["total_invariant_violations"] == 0
    assert payload["positive_controls"]["all_caught"] is True
    assert payload["v14_tier_hash_preserved"] is True
    assert payload["working_tree_unchanged"] is True


def test_owned_files_hygiene_size_and_report_alignment() -> None:
    script_path = REPO_ROOT / "scripts" / "integrity_cost_and_trajectory_boundary_sweep.py"
    report_path = REPO_ROOT / "docs" / "reports" / "integrity_cost_and_trajectory_boundary_sweep.md"
    test_path = Path(__file__).resolve()

    for fpath in (script_path, report_path, test_path):
        assert fpath.is_file()
        assert fpath.stat().st_size <= 180 * 1024

    script_txt = script_path.read_text(encoding="utf-8")
    report_txt = report_path.read_text(encoding="utf-8")
    test_txt = test_path.read_text(encoding="utf-8")

    for dash_char in ("\u2014", "\u2013"):
        assert dash_char not in script_txt
        assert dash_char not in report_txt
        assert dash_char not in test_txt

    coauthor_tok = "co-authored" + "-by"
    assert coauthor_tok not in script_txt.lower()
    assert coauthor_tok not in report_txt.lower()
    assert coauthor_tok not in test_txt.lower()

    hash_char = chr(35)
    assert hash_char not in script_txt
    assert hash_char not in test_txt

    for py_src in (script_txt, test_txt):
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(py_src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == []

    idx_65 = report_txt.find("65% [24%, 98%]")
    idx_72 = report_txt.find("72% [52%, 91%]")
    assert idx_65 != -1 and idx_72 != -1 and idx_65 < idx_72

    for tok in (
        "2,880",
        "223,411",
        "de9cc50e",
        "a8f99c2537c91d72",
        "ISS-COST-01",
        "ISS-COST-02",
        "ISS-COST-03",
        "ISS-COST-04",
        "ISS-COST-05",
        *cost_sweep.FAMILY_NAMES,
        *cost_sweep.POSITIVE_CONTROL_NAMES,
    ):
        assert tok in report_txt
