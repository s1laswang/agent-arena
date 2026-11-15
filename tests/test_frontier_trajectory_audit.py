"""Tests for scripts/frontier_trajectory_audit.py, trajectory_audit.json, and frontier_trajectory_audit_v14.md."""
from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "frontier_trajectory_audit.py"
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "trajectory_audit.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_trajectory_audit_v14.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("frontier_trajectory_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fta = _load_module()

EXPECTED_COUNTS_GATED = [30, 30, 2, 5, 30, 30, 30, 30, 30, 30, 30]
EXPECTED_COHORT_IDS_GATED = [
    "opencode_gemini_4_carbon_medium",
    "opencode_gemini_4_carbon_hard",
    "opencode_gemini_4_carbon_hard_ext",
    "opencode_gemini_4_carbon_hard_rep",
    "opencode_gemini_3_5_flash_medium",
    "opencode_gpt_5_5_hard",
    "inproc_gemini_4_carbon_medium",
    "inproc_gemini_4_carbon_hard",
    "solver_medium",
    "solver_hard_0_29",
    "solver_hard_30_59",
]

EXPECTED_COUNTS_ALL = [30, 30, 2, 5, 30, 30, 30, 30, 30, 30, 30, 30]
EXPECTED_COHORT_IDS_ALL = [
    "opencode_gemini_4_carbon_medium",
    "opencode_gemini_4_carbon_hard",
    "opencode_gemini_4_carbon_hard_ext",
    "opencode_gemini_4_carbon_hard_rep",
    "opencode_gemini_3_5_flash_medium",
    "opencode_gemini_3_5_flash_hard",
    "opencode_gpt_5_5_hard",
    "inproc_gemini_4_carbon_medium",
    "inproc_gemini_4_carbon_hard",
    "solver_medium",
    "solver_hard_0_29",
    "solver_hard_30_59",
]

EXPECTED_SPEC_TOOLS = {
    "status",
    "list_employees",
    "read_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "read_document",
    "check_leak_feed",
    "plant_canary",
    "interview",
    "restrict",
    "unrestrict_access",
    "next_day",
    "accuse",
    "other_invalid",
}


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _strip_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CANARY_WORLD_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(scope="module")
def computed_audit():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    _strip_keys(mp)
    env_before = dict(os.environ)
    try:
        out = fta.compute_audit(root=ROOT, verify_replays=True, enforce_expected_counts=True)
        assert dict(os.environ) == env_before
    finally:
        mp.undo()
    return out


def test_approx_equal_float_tolerance():
    assert fta.approx_equal({"v": [128.03333333333333]}, {"v": [128.0333333333339]}, tol=1e-9)
    assert not fta.approx_equal({"v": [128.03333]}, {"v": [128.03349]}, tol=1e-9)
    assert not fta.approx_equal({"b": True}, {"b": 1})
    assert not fta.approx_equal({"x": None}, {"x": 0.0})
    assert fta.approx_equal({"x": None}, {"x": None})
    assert fta.approx_equal(float("nan"), float("nan"))


def test_check_cli_provenance_and_exact_episode_counts(computed_audit, monkeypatch):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    monkeypatch.setattr(
        fta,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: computed_audit,
    )
    assert fta.main(["--check"]) == 0
    assert JSON_PATH.stat().st_size <= 50_000
    assert JSON_PATH.read_bytes() == fta.serialize_audit_json(computed_audit).encode("utf-8")
    assert MD_PATH.read_bytes() == fta.render_markdown(computed_audit).encode("utf-8")

    assert computed_audit["tiers_version"] == "v1.4"
    assert computed_audit["upstream_justsilas_sync_commit"] == "5f9b3297"
    assert computed_audit["zero_live_api_calls"] is True
    assert computed_audit["zero_git_dependency"] is True
    assert computed_audit["zero_subprocesses"] is True

    rv = computed_audit["replay_verification"]
    assert rv["committed_v14"]["total"] == 472
    assert rv["committed_v14"]["verified"] == 472
    assert rv["committed_v14"]["mismatches"] == 0
    assert rv["committed_v14"]["step_mismatches"] == 0
    assert rv["committed_v14"]["duplicates"] == 0
    assert rv["committed_v14"]["pre_1bc3e281_detail_normalized_steps"] > 0
    assert rv["committed_v14"]["unwrapped_mcp_error_steps"] > 0
    assert rv["committed_v14"]["clean_rc0_non_accuse_zero_day_seeds"] == [0, 17]

    assert rv["replication_v14"]["total"] == 305
    assert rv["replication_v14"]["verified"] == 305
    assert rv["replication_v14"]["mismatches"] == 0
    assert rv["replication_v14"]["step_mismatches"] == 0
    assert rv["replication_v14"]["duplicates"] == 0

    prov = computed_audit["provenance_and_locks"]
    up_sync = prov["upstream_justsilas_sync"]
    assert up_sync["head_commit"] == "5f9b3297"
    assert up_sync["code_freeze_tag"] == "afterquery-final"
    assert up_sync["code_freeze_commit"] == "1bc3e281"
    assert up_sync["afterquery_submit_tag"] == "afterquery-submit"
    assert up_sync["afterquery_submit_commit"] == "9225f2ad"
    assert up_sync["afterquery_submit_2_tag"] == "afterquery-submit-2"
    assert up_sync["afterquery_submit_2_commit"] == "aa1c679e"
    assert up_sync["ceo_correction_commit"] == "5f9b3297"
    assert up_sync["rehearsal_final_branch_commit"] == "d0ead011"
    assert up_sync["harbor_rehearsal_ratios_pct"] == [93, 116, 131]
    assert up_sync["harbor_rehearsal_valid_trials"] == [10, 10, 9]

    assert prov["primary_0_29_lock"]["classification"] == "post_hoc_lock"
    assert prov["primary_0_29_lock"]["lock_commit"] == "671ed96"
    assert prov["primary_0_29_lock"]["episodes_commit"] == "8fd4dec"
    assert prov["primary_0_29_lock"]["lock_delay_s"] == 28
    assert prov["g1_hard_30_59_extension"]["classification"] == "pre_registered"
    assert prov["g1_hard_30_59_extension"]["prereg_commit"] == "f9fb7a4a"
    assert prov["g1_hard_30_59_extension"]["completed_seeds"] == [34, 37]
    assert prov["gpt_5_5_hard_0_29"]["classification"] == "pre_registered"
    assert prov["gpt_5_5_hard_0_29"]["prereg_commit"] == "cf394894"
    assert prov["gpt_5_5_hard_0_29"]["results_commit"] == "ca0a0dc0"
    assert prov["gpt_5_5_hard_0_29"]["upstream_sync_commit"] == "5f9b3297"
    assert prov["gpt_5_5_hard_0_29"]["timeout_cap_s"] == 7200
    assert prov["gpt_5_5_hard_0_29"]["committed_v14_episodes"] == 30
    assert prov["gpt_5_5_hard_0_29"]["clean_rc0_non_accuse_zero_day_seeds"] == [0, 17]
    assert prov["step_error_detail_compat"]["commit"] == "1bc3e281"

    s34 = computed_audit["seed_34_cross_run"]
    assert s34["shared_seeds"] == [34]
    assert s34["same_accused"] is True
    assert s34["both_correct"] is True
    assert s34["g1_ext"]["accused"] == "e29"
    assert s34["fr8_rep"]["accused"] == "e29"
    assert math.isclose(s34["g1_ext"]["score"], 0.79, abs_tol=1e-12)
    assert math.isclose(s34["fr8_rep"]["score"], 0.82, abs_tol=1e-12)
    assert math.isclose(s34["score_diff_g1_minus_fr8"], -0.03, abs_tol=1e-12)

    summary = computed_audit["summary"]
    assert summary["committed_v14_verified"] == 472
    assert summary["replication_v14_verified"] == 305
    assert summary["total_pool_episodes_replay_verified"] == 777

    ships_flash = fta.gap_ships_flash_hard(ROOT)
    expected_ids = EXPECTED_COHORT_IDS_ALL if ships_flash else EXPECTED_COHORT_IDS_GATED
    expected_counts = EXPECTED_COUNTS_ALL if ships_flash else EXPECTED_COUNTS_GATED
    assert summary["cohort_count"] == len(expected_ids)
    assert summary["episode_counts"] == expected_counts
    assert summary["total_episodes_audited"] == sum(expected_counts)
    assert summary["total_episodes_replay_verified"] == sum(expected_counts)

    cohorts = computed_audit["cohorts"]
    assert [c["cohort_id"] for c in cohorts] == expected_ids
    assert [c["n"] for c in cohorts] == expected_counts

    by_id = {c["cohort_id"]: c for c in cohorts}
    assert by_id["opencode_gemini_4_carbon_hard_ext"]["seeds"] == [34, 37]
    assert by_id["opencode_gemini_4_carbon_hard_rep"]["seeds"] == [30, 34, 42, 45, 57]
    assert by_id["solver_hard_30_59"]["seeds"] == list(range(30, 60))
    for cid in (
        "opencode_gemini_4_carbon_medium",
        "opencode_gemini_4_carbon_hard",
        "opencode_gemini_3_5_flash_medium",
        "opencode_gpt_5_5_hard",
        "inproc_gemini_4_carbon_medium",
        "inproc_gemini_4_carbon_hard",
        "solver_medium",
        "solver_hard_0_29",
    ):
        assert by_id[cid]["seeds"] == list(range(30))

    md = MD_PATH.read_text(encoding="utf-8")
    assert "post-hoc lock" in md
    assert "671ed96" in md
    assert "8fd4dec" in md
    assert "f9fb7a4a" in md
    assert "cf394894" in md
    assert "ca0a0dc0" in md
    assert "5f9b3297" in md
    assert "afterquery-submit" in md
    assert "9225f2ad" in md
    assert "afterquery-submit-2" in md
    assert "aa1c679e" in md
    assert "d0ead011" in md
    assert "93%, 116%, 131%" in md
    assert "7200 s" in md
    assert "1bc3e281" in md
    assert "+0.790" in md
    assert "+0.820" in md
    assert "OpenCode gemini-3.5-flash medium (0-29)" in md
    if not ships_flash:
        assert "OpenCode gemini-3.5-flash hard (0-29)" not in md
        assert "0.373" not in md


@pytest.fixture(scope="module")
def computed_audit_all_cohorts():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    _strip_keys(mp)
    mp.setattr(fta, "gap_ships_flash_hard", lambda root=ROOT: True)
    try:
        return fta.compute_audit(root=ROOT, verify_replays=False, enforce_expected_counts=True)
    finally:
        mp.undo()


def test_gap_ships_flash_hard_false_and_true(computed_audit_all_cohorts, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    mock_root = tmp_path / "workspace"
    (mock_root / "data" / "runs" / "committed").mkdir(parents=True)
    (mock_root / "results" / "frontier_replication").mkdir(parents=True)
    (mock_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        mock_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "frontier_replication" / "v1.4",
        mock_root / "results" / "frontier_replication" / "v1.4",
    )
    gap_file = mock_root / "docs" / "reports" / "gap.md"

    gap_file.write_text("Primary headline: gemini-4-carbon hard 65% [24%, 98%]\n", encoding="utf-8")
    assert fta.gap_ships_flash_hard(mock_root) is False
    audit_false = fta.compute_audit(root=mock_root, verify_replays=False, enforce_expected_counts=True)
    assert audit_false["flash_hard_shipped_in_gap_md"] is False
    assert audit_false["summary"]["flash_hard_held_pending_gap_md"] is True
    assert [c["cohort_id"] for c in audit_false["cohorts"]] == EXPECTED_COHORT_IDS_GATED
    assert [c["n"] for c in audit_false["cohorts"]] == EXPECTED_COUNTS_GATED
    assert "carbon_vs_flash_opencode_medium" in audit_false["comparisons"]
    assert "carbon_vs_flash_opencode_hard" not in audit_false["comparisons"]
    assert "flash_opencode_vs_solver_hard_0_29" not in audit_false["comparisons"]
    json_false = fta.serialize_audit_json(audit_false)
    assert len(json_false.encode("utf-8")) <= 50_000
    md_false = fta.render_markdown(audit_false)
    assert "OpenCode gemini-3.5-flash medium (0-29)" in md_false
    assert "OpenCode gemini-3.5-flash hard (0-29)" not in md_false
    assert "0.373" not in md_false

    gap_file.write_text(
        "Primary headline: gemini-4-carbon and opencode:google/gemini-3.5-flash hard\n",
        encoding="utf-8",
    )
    assert fta.gap_ships_flash_hard(mock_root) is True
    audit_true = fta.compute_audit(root=mock_root, verify_replays=False, enforce_expected_counts=True)
    assert audit_true == computed_audit_all_cohorts
    assert audit_true["flash_hard_shipped_in_gap_md"] is True
    assert audit_true["summary"]["flash_hard_held_pending_gap_md"] is False
    assert [c["cohort_id"] for c in audit_true["cohorts"]] == EXPECTED_COHORT_IDS_ALL
    assert [c["n"] for c in audit_true["cohorts"]] == EXPECTED_COUNTS_ALL
    assert "carbon_vs_flash_opencode_medium" in audit_true["comparisons"]
    assert "carbon_vs_flash_opencode_hard" in audit_true["comparisons"]
    assert "flash_opencode_vs_solver_hard_0_29" in audit_true["comparisons"]
    json_true = fta.serialize_audit_json(audit_true)
    assert len(json_true.encode("utf-8")) <= 50_000
    md_true = fta.render_markdown(audit_true)
    assert "OpenCode gemini-3.5-flash medium (0-29)" in md_true
    assert "OpenCode gemini-3.5-flash hard (0-29)" in md_true
    assert "0.373" in md_true


def test_metric_invariants_across_all_cohorts(computed_audit_all_cohorts):
    all_audit = computed_audit_all_cohorts
    cohorts = all_audit["cohorts"]
    tier_params_map = all_audit["tier_params"]
    assert len(cohorts) == 12

    for c in cohorts:
        n = c["n"]
        tp = tier_params_map[c["tier"]]
        rv = c["replay_verification"]
        oc = c["outcomes"]
        tu = c["tool_use"]
        cd = c["canary_design"]
        ch = c["collateral_and_horizon"]
        tc = c["token_and_cache"]

        assert rv["mismatches"] == 0
        assert rv["duplicates"] == 0

        assert math.isclose(
            tu["mean_ok_tool_calls"] + tu["mean_failed_tool_calls"],
            tu["mean_total_tool_calls"],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        assert math.isclose(
            sum(tu["by_spec_tool"].values()),
            tu["mean_total_tool_calls"],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        assert set(tu["by_spec_tool"].keys()) == EXPECTED_SPEC_TOOLS
        assert tu["by_spec_tool"]["read_document"] == 0.0
        assert tu["mean_calls_per_simulated_day"] > 0.0
        assert 0.0 < tu["mean_investigative_actions_per_day"] <= float(tp["actions_per_day"])

        assert cd["total_accepted_canaries"] > 0
        assert math.isclose(
            cd["mean_accepted_canaries"] + cd["mean_failed_plant_canary_calls"],
            cd["mean_plant_canary_calls"],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        assert sum(int(v) for v in cd["variant_count_distribution"].values()) == cd["total_accepted_canaries"]
        assert 1.0 <= cd["mean_distinct_variants"] <= float(tp["max_variants"])
        assert 1.0 <= cd["mean_recipients_per_canary"] <= float(tp["n_employees"])
        assert math.isclose(
            cd["mean_recipient_staff_share"] + cd["mean_careful_mole_weight"],
            1.0,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        assert (
            cd["uninformative_broad_or_single_count"] + cd["targeted_2_3_split_count"]
            == cd["total_accepted_canaries"]
        )
        assert math.isclose(
            cd["uninformative_broad_or_single_share"] + cd["targeted_2_3_split_share"],
            1.0,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        assert cd["targeted_2_variant_count"] + cd["targeted_3_variant_count"] == cd["targeted_2_3_split_count"]
        assert 0.0 < cd["canary_slot_utilization"] <= 1.0
        assert 0.0 < cd["days_with_canary_share"] <= 1.0

        assert ch["accused_count"] + ch["abstention_count"] == n
        assert math.isclose(ch["accused_rate"] + ch["abstention_rate"], 1.0, rel_tol=1e-12, abs_tol=1e-12)
        assert 0.0 <= ch["abstention_rate"] <= 1.0
        assert 1.0 <= ch["mean_accusation_day"] <= float(tp["n_days"])
        assert 1.0 <= ch["mean_final_day_all_episodes"] <= float(tp["n_days"])
        assert oc["correct_count"] + oc["wrong_accusation_count"] == ch["accused_count"]
        assert math.isclose(
            oc["accuracy"] + oc["wrong_accusation_rate"] + ch["abstention_rate"],
            1.0,
            rel_tol=1e-12,
            abs_tol=1e-12,
        )

        if c["harness"] == "opencode":
            assert tc["is_opencode_cohort"] is True
            assert tc["usage_available"] is True
            assert tc["wall_s_available"] is True
            assert 0.0 < tc["mean_usage_cached_in"] <= tc["mean_usage_in"]
            assert math.isclose(
                tc["mean_usage_cached_in"] + tc["mean_usage_uncached_in"],
                tc["mean_usage_in"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            assert 0.0 < tc["cached_input_pct"] <= 100.0
            assert 0.0 < tc["mean_episode_cached_input_pct"] <= 100.0
            assert tc["mean_usage_out"] > 0.0
            assert 0.0 < tc["min_wall_s"] <= tc["mean_wall_s"] <= tc["max_wall_s"]
        elif c["harness"] == "inproc":
            assert tc["is_opencode_cohort"] is False
            assert tc["usage_available"] is True
            assert tc["wall_s_available"] is False
            assert tc["mean_wall_s"] is None
        else:
            assert c["harness"] == "reference"
            assert tc["usage_available"] is False
            assert tc["wall_s_available"] is False
            assert tu["by_spec_tool"]["interview"] == 0.0
            assert ch["mean_restrict_calls_per_episode"] == 0.0
            assert tu["mean_failed_tool_calls"] == 0.0
            assert cd["targeted_2_3_split_share"] > 0.99

    by_id = {c["cohort_id"]: c for c in cohorts}
    assert (
        by_id["opencode_gemini_4_carbon_hard"]["tool_use"]["by_spec_tool"]["interview"]
        > by_id["opencode_gemini_3_5_flash_hard"]["tool_use"]["by_spec_tool"]["interview"]
        > by_id["solver_hard_0_29"]["tool_use"]["by_spec_tool"]["interview"]
    )
    assert by_id["opencode_gemini_4_carbon_hard_ext"]["canary_design"]["targeted_2_3_split_share"] == 1.0
    assert by_id["opencode_gemini_3_5_flash_hard"]["canary_design"]["full_staff_zero_leak_count"] == 2
    assert by_id["opencode_gemini_3_5_flash_medium"]["canary_design"]["single_variant_count"] == 2
    assert by_id["opencode_gemini_3_5_flash_hard"]["canary_design"]["single_variant_count"] == 1


def test_step_result_normalization_1bc3e281_unwrap_order():
    live_err = {
        "ok": False,
        "data": {"detail": "unknown topic 'leaks'; allowed: alibi, contacts_outside"},
        "error": "invalid arguments",
    }

    pre_direct = {"ok": False, "data": {}, "error": "invalid arguments"}
    ok1, flags1 = fta.step_result_matches(pre_direct, live_err)
    assert ok1 is True
    assert flags1["unwrapped_mcp_error"] is False
    assert flags1["detail_normalized"] is True

    post_direct = dict(live_err)
    ok2, flags2 = fta.step_result_matches(post_direct, live_err)
    assert ok2 is True
    assert flags2["unwrapped_mcp_error"] is False
    assert flags2["detail_normalized"] is False

    bad_post_direct = {
        "ok": False,
        "data": {"detail": "different detail"},
        "error": "invalid arguments",
    }
    ok_bad, _ = fta.step_result_matches(bad_post_direct, live_err)
    assert ok_bad is False

    pre_oc_wrapped = {"ok": False, "error": json.dumps(pre_direct)}
    ok3, flags3 = fta.step_result_matches(pre_oc_wrapped, live_err)
    assert ok3 is True
    assert flags3["unwrapped_mcp_error"] is True
    assert flags3["detail_normalized"] is True

    post_oc_wrapped = {"ok": False, "error": json.dumps(post_direct)}
    ok4, flags4 = fta.step_result_matches(post_oc_wrapped, live_err)
    assert ok4 is True
    assert flags4["unwrapped_mcp_error"] is True
    assert flags4["detail_normalized"] is False

    bad_post_oc_wrapped = {"ok": False, "error": json.dumps(bad_post_direct)}
    ok5, _ = fta.step_result_matches(bad_post_oc_wrapped, live_err)
    assert ok5 is False

    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        from canary.env import Env

        env = Env("medium", 0)
        r_bad = env.call("interview", {"employee": "e00", "topic": "leaks"})
        assert r_bad.ok is False
        assert isinstance(r_bad.data, dict) and set(r_bad.data) == {"detail"}
        live_payload = {"ok": r_bad.ok, "data": r_bad.data, "error": r_bad.error}

        pre_step = {
            "t": 1,
            "day": 1,
            "tool": "interview",
            "args": {"employee": "e00", "topic": "leaks"},
            "result": {"ok": False, "error": json.dumps({"ok": False, "data": {}, "error": r_bad.error})},
        }
        post_step = {
            "t": 1,
            "day": 1,
            "tool": "interview",
            "args": {"employee": "e00", "topic": "leaks"},
            "result": {"ok": False, "error": json.dumps(live_payload)},
        }
        for step_variant in (pre_step, post_step):
            ep_doc = {
                "tier": "medium",
                "seed": 0,
                "agent": "opencode:google/gemini-4-carbon",
                "score": 0.0,
                "correct": False,
                "accused": None,
                "final_day": 1,
                "end_reason": "stop_early",
                "steps": [step_variant],
                "meta": {},
            }
            rep_out = fta.replay_and_verify_episode(ep_doc)
            assert rep_out["ok"] is True
            assert rep_out["step_mismatches"] == 0

        env2 = Env("medium", 0)
        r_iv = env2.call("interview", {"employee": "e00", "topic": "workload"})
        r_adv = env2.call("advance_day", {})
        r_msg = env2.call("read_message", {"id": "m1-0"})
        msg_ep = {
            "tier": "medium",
            "seed": 0,
            "agent": "opencode:google/gemini-4-carbon",
            "score": 0.0,
            "correct": False,
            "accused": None,
            "final_day": 2,
            "end_reason": "stop_early",
            "steps": [
                {
                    "t": 0,
                    "day": 1,
                    "tool": "interview",
                    "args": {"employee": "e00", "topic": "workload"},
                    "result": {"ok": r_iv.ok, "data": r_iv.data, "error": r_iv.error},
                },
                {
                    "t": 1,
                    "day": 1,
                    "tool": "advance_day",
                    "args": {},
                    "result": {"ok": r_adv.ok, "data": r_adv.data, "error": r_adv.error},
                },
                {
                    "t": 2,
                    "day": 2,
                    "tool": "read_message",
                    "args": {"id": "m1-0"},
                    "result": {"ok": r_msg.ok, "data": r_msg.data, "error": r_msg.error},
                },
            ],
            "meta": {},
        }
        assert fta.replay_and_verify_episode(msg_ep)["ok"] is True
        tampered_iv = dict(
            msg_ep,
            steps=[
                {**msg_ep["steps"][0], "result": {"ok": True, "data": {"answer": "tampered"}, "error": None}},
                msg_ep["steps"][1],
                msg_ep["steps"][2],
            ],
        )
        assert fta.replay_and_verify_episode(tampered_iv)["ok"] is False
        tampered_msg = dict(
            msg_ep,
            steps=[
                msg_ep["steps"][0],
                msg_ep["steps"][1],
                {**msg_ep["steps"][2], "result": {"ok": True, "data": {"message": {}}, "error": None}},
            ],
        )
        assert fta.replay_and_verify_episode(tampered_msg)["ok"] is False
    finally:
        if prev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev


def test_write_check_roundtrip_tamper_and_zero_git_dependency(computed_audit, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    no_git_root = tmp_path / "clean_tree_without_git"
    (no_git_root / "data" / "runs" / "committed").mkdir(parents=True)
    (no_git_root / "results" / "frontier_replication").mkdir(parents=True)
    (no_git_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        no_git_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "frontier_replication" / "v1.4",
        no_git_root / "results" / "frontier_replication" / "v1.4",
    )
    os.symlink(
        ROOT / "docs" / "reports" / "gap.md",
        no_git_root / "docs" / "reports" / "gap.md",
    )
    assert not (no_git_root / ".git").exists()

    out_json = tmp_path / "out" / "trajectory_audit.json"
    out_md = tmp_path / "out" / "frontier_trajectory_audit_v14.md"

    orig_compute = fta.compute_audit
    no_git_audit = orig_compute(root=no_git_root, verify_replays=False, enforce_expected_counts=True)
    assert no_git_audit["summary"]["episode_counts"] == computed_audit["summary"]["episode_counts"]
    assert no_git_audit["seed_34_cross_run"] == computed_audit["seed_34_cross_run"]

    monkeypatch.setattr(
        fta,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: computed_audit,
    )

    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0
    assert out_json.stat().st_size <= 50_000

    data = json.loads(out_json.read_text(encoding="utf-8"))
    orig_val = data["cohorts"][0]["tool_use"]["mean_total_tool_calls"]
    data["cohorts"][0]["tool_use"]["mean_total_tool_calls"] = orig_val + 5e-11
    out_json.write_text(fta.serialize_audit_json(data), encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data["cohorts"][0]["tool_use"]["mean_total_tool_calls"] = orig_val + 1e-5
    out_json.write_text(fta.serialize_audit_json(data), encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    data["cohorts"][0]["tool_use"]["mean_total_tool_calls"] = orig_val
    out_json.write_text(fta.serialize_audit_json(data), encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    oversized = out_json.read_text(encoding="utf-8").rstrip("\n") + (" " * 20_000) + "\n"
    out_json.write_text(oversized, encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    out_json.write_text(fta.serialize_audit_json(data), encoding="utf-8")
    orig_md = out_md.read_text(encoding="utf-8")
    out_md.write_text(orig_md + "\ntampered\n", encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1


def test_synthetic_edge_cases_and_negative_controls():
    spec = {
        "cohort_id": "synthetic_opencode_med",
        "label": "Synthetic OpenCode medium",
        "harness": "opencode",
        "agent": "opencode:google/gemini-4-carbon",
        "model_family": "gemini-4-carbon",
        "tier": "medium",
        "source": "committed",
        "source_rel": "data/runs/committed/v1.4",
        "seed_min": 0,
        "seed_max": 1,
        "expected_n": 2,
    }
    broad_asg = {f"e{i:02d}": f"v{i % 3}" for i in range(12)}
    ep0 = {
        "tier": "medium",
        "seed": 0,
        "agent": "opencode:google/gemini-4-carbon",
        "score": 0.65,
        "correct": True,
        "accused": "e01",
        "final_day": 5,
        "end_reason": "accused",
        "steps": [
            {"t": 1, "day": 1, "tool": "status", "args": {}, "result": {"ok": True}},
            {
                "t": 2,
                "day": 1,
                "tool": "plant_canary",
                "args": {"doc_title": "Single", "assignment": {"e00": "A", "e01": "A"}},
                "result": {"ok": True},
            },
            {
                "t": 3,
                "day": 2,
                "tool": "plant_canary",
                "args": {"doc_title": "Broad", "assignment": broad_asg},
                "result": {"ok": True},
            },
            {
                "t": 4,
                "day": 3,
                "tool": "plant_canary",
                "args": {"doc_title": "Targeted", "assignment": {"e00": "A", "e01": "B", "e02": "C"}},
                "result": {"ok": True},
            },
            {
                "t": 5,
                "day": 3,
                "tool": "plant_canary",
                "args": {"doc_title": "OverLimit", "assignment": {"e00": "A", "e01": "B"}},
                "result": {"ok": False, "error": "canary limit for today reached"},
            },
            {"t": 6, "day": 4, "tool": "restrict_access", "args": {"employee": "e03"}, "result": {"ok": True}},
            {"t": 7, "day": 5, "tool": "unrestrict_access", "args": {"employee": "e03"}, "result": {"ok": True}},
            {"t": 8, "day": 5, "tool": "accuse", "args": {"employee": "e01"}, "result": {"ok": True}},
        ],
        "meta": {
            "wall_s": 500.0,
            "usage": {"in": 1000, "cached_in": 800, "out": 100, "llm_calls": 8},
        },
    }
    ep1 = {
        "tier": "medium",
        "seed": 1,
        "agent": "opencode:google/gemini-4-carbon",
        "score": 0.0,
        "correct": False,
        "accused": None,
        "final_day": 1,
        "end_reason": "stop_early",
        "steps": [
            {"t": 1, "day": 1, "tool": "status", "args": {}, "result": None},
        ],
        "meta": {
            "wall_s": 2500.0,
            "usage": {"in": 3000, "cached_in": 2700, "out": 200, "llm_calls": 4},
        },
    }

    row = fta.compute_cohort_metrics(spec, [ep0, ep1], verify_replays=False)
    assert row["n"] == 2
    assert row["canary_design"]["total_plant_canary_calls"] == 4
    assert row["canary_design"]["total_accepted_canaries"] == 3
    assert row["canary_design"]["single_variant_count"] == 1
    assert row["canary_design"]["broad_over_half_staff_count"] == 1
    assert row["canary_design"]["uninformative_broad_or_single_count"] == 2
    assert row["canary_design"]["targeted_2_3_split_count"] == 1
    assert math.isclose(row["canary_design"]["uninformative_broad_or_single_share"], 2.0 / 3.0)
    assert math.isclose(row["canary_design"]["targeted_2_3_split_share"], 1.0 / 3.0)
    assert row["collateral_and_horizon"]["accused_rate"] == 0.5
    assert row["collateral_and_horizon"]["mean_accusation_day"] == 5.0
    assert row["collateral_and_horizon"]["mean_final_day_all_episodes"] == 3.0
    assert row["collateral_and_horizon"]["mean_restrict_calls_per_episode"] == 0.5
    assert math.isclose(row["token_and_cache"]["cached_input_pct"], 87.5)
    assert row["token_and_cache"]["episodes_over_2400s"] == 1
    assert row["token_and_cache"]["episodes_over_3600s"] == 0

    with pytest.raises(ValueError, match="duplicate seeds"):
        fta.compute_cohort_metrics(spec, [ep1, ep1], verify_replays=False)

    bad_ep = dict(ep1, score=0.99)
    with pytest.raises(ValueError, match="replay mismatches"):
        fta.compute_cohort_metrics(spec, [bad_ep], verify_replays=True)

    clean_zero_ep = {
        "tier": "medium",
        "seed": 1,
        "agent": "opencode:openai/gpt-5.5",
        "score": 0.0,
        "correct": False,
        "accused": None,
        "final_day": 0,
        "end_reason": "stop_early",
        "steps": [{"t": 1, "day": 1, "tool": "status", "args": {}, "result": None}],
        "meta": {"rc": 0, "valid": True, "error": None},
    }
    assert fta.is_clean_non_accuse_rc0_exit(clean_zero_ep, env_done=False) is True
    clean_ver = fta.verify_episode_pool([clean_zero_ep], "synthetic_clean_zero")
    assert clean_ver["verified"] == 1
    assert clean_ver["clean_rc0_non_accuse_zero_day_seeds"] == [1]

    timeout_zero_ep = dict(
        clean_zero_ep,
        end_reason="timeout",
        meta={"rc": 124, "valid": True, "error": "timeout"},
    )
    assert fta.is_clean_non_accuse_rc0_exit(timeout_zero_ep, env_done=False) is False
    with pytest.raises(ValueError, match="replay mismatches"):
        fta.verify_episode_pool([timeout_zero_ep], "synthetic_timeout_zero")


def test_file_hygiene_no_comments_or_em_dashes():
    hash_char = chr(35)
    py_files = [SCRIPT_PATH, Path(__file__).resolve()]
    all_files = py_files + [JSON_PATH, MD_PATH]
    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
        assert hash_char not in pf.read_text(encoding="utf-8"), f"found hash char in {pf}"
    for f in all_files:
        txt = f.read_text(encoding="utf-8")
        assert "\u2014" not in txt, f"found em dash in {f}"
        assert "\u2013" not in txt, f"found en dash in {f}"
        assert txt.isascii(), f"found non-ASCII characters in {f}"
    assert JSON_PATH.stat().st_size <= 50_000
