"""Tests for scripts/frontier_trajectory_audit.py, trajectory_audit.json, and frontier_trajectory_audit_v14.md."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
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

EXPECTED_COUNTS = [30, 30, 5, 30, 30, 30, 30, 30, 30, 30]
EXPECTED_COHORT_IDS = [
    "opencode_gemini_4_carbon_medium",
    "opencode_gemini_4_carbon_hard",
    "opencode_gemini_4_carbon_hard_rep",
    "opencode_gemini_3_5_flash_medium",
    "opencode_gemini_3_5_flash_hard",
    "inproc_gemini_4_carbon_medium",
    "inproc_gemini_4_carbon_hard",
    "solver_medium",
    "solver_hard_0_29",
    "solver_hard_30_59",
]
EXPECTED_PROMPT_TOOLS = {
    "status",
    "list_employees",
    "read_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "read_document",
    "plant_canary",
    "interview",
    "restrict",
    "next_day",
    "accuse",
}


@pytest.fixture(scope="module")
def computed_audit():
    env_before = dict(os.environ)
    out = fta.compute_audit(root=ROOT, verify_replays=True, enforce_expected_counts=True)
    assert dict(os.environ) == env_before
    return out


def test_approx_equal_float_tolerance():
    assert fta.approx_equal({"v": [128.03333333333333]}, {"v": [128.0333333333339]}, tol=1e-9)
    assert not fta.approx_equal({"v": [128.03333]}, {"v": [128.03349]}, tol=1e-9)
    assert not fta.approx_equal({"b": True}, {"b": 1})
    assert not fta.approx_equal({"x": None}, {"x": 0.0})
    assert fta.approx_equal({"x": None}, {"x": None})
    assert fta.approx_equal(float("nan"), float("nan"))


def test_check_cli_and_exact_episode_counts(computed_audit, monkeypatch):
    monkeypatch.setattr(
        fta,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: copy.deepcopy(computed_audit),
    )
    assert fta.main(["--check"]) == 0

    assert computed_audit["tiers_version"] == "v1.4"
    assert computed_audit["zero_live_api_calls"] is True
    assert computed_audit["zero_git_dependency"] is True

    summary = computed_audit["summary"]
    assert summary["cohort_count"] == 10
    assert summary["episode_counts"] == EXPECTED_COUNTS
    assert summary["total_episodes_audited"] == 275
    assert summary["total_episodes_replay_verified"] == 275
    assert summary["opencode_cohort_count"] == 5
    assert summary["inproc_cohort_count"] == 2
    assert summary["reference_cohort_count"] == 3

    cohorts = computed_audit["cohorts"]
    assert [c["cohort_id"] for c in cohorts] == EXPECTED_COHORT_IDS
    assert [c["n"] for c in cohorts] == EXPECTED_COUNTS

    by_id = {c["cohort_id"]: c for c in cohorts}
    assert by_id["opencode_gemini_4_carbon_hard_rep"]["seeds"] == [30, 34, 42, 45, 57]
    assert by_id["solver_hard_30_59"]["seeds"] == list(range(30, 60))
    for cid in (
        "opencode_gemini_4_carbon_medium",
        "opencode_gemini_4_carbon_hard",
        "opencode_gemini_3_5_flash_medium",
        "opencode_gemini_3_5_flash_hard",
        "inproc_gemini_4_carbon_medium",
        "inproc_gemini_4_carbon_hard",
        "solver_medium",
        "solver_hard_0_29",
    ):
        assert by_id[cid]["seeds"] == list(range(30))


def test_metric_invariants_across_all_cohorts(computed_audit):
    cohorts = computed_audit["cohorts"]
    for c in cohorts:
        n = c["n"]
        tp = c["tier_params"]
        rv = c["replay_verification"]
        oc = c["outcomes"]
        tu = c["tool_use"]
        cd = c["canary_design"]
        ch = c["collateral_and_horizon"]
        tc = c["token_and_cache"]

        assert rv["verified"] == n
        assert rv["mismatches"] == 0
        assert rv["duplicates"] == 0

        assert math.isclose(
            tu["mean_ok_tool_calls"] + tu["mean_failed_tool_calls"],
            tu["mean_total_tool_calls"],
            rel_tol=1e-12,
            abs_tol=1e-12,
        )
        assert math.isclose(
            sum(tu["by_env_tool"].values()),
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
        assert set(tu["by_prompt_tool"].keys()) == EXPECTED_PROMPT_TOOLS
        assert tu["by_prompt_tool"]["read_document"] == 0.0
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
        assert 1.0 <= ch["mean_accusation_day"] <= ch["mean_final_day_all_episodes"] <= float(tp["n_days"])
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
            assert tu["by_env_tool"]["interview"] == 0.0
            assert ch["mean_restrict_calls_per_episode"] == 0.0
            assert tu["mean_failed_tool_calls"] == 0.0
            assert cd["targeted_2_3_split_share"] > 0.99

    by_id = {c["cohort_id"]: c for c in cohorts}
    assert (
        by_id["opencode_gemini_4_carbon_hard"]["tool_use"]["by_env_tool"]["interview"]
        > by_id["opencode_gemini_3_5_flash_hard"]["tool_use"]["by_env_tool"]["interview"]
        > by_id["solver_hard_0_29"]["tool_use"]["by_env_tool"]["interview"]
    )
    assert by_id["opencode_gemini_3_5_flash_hard"]["canary_design"]["full_staff_zero_leak_count"] == 2
    assert by_id["opencode_gemini_3_5_flash_medium"]["canary_design"]["single_variant_count"] == 2
    assert by_id["opencode_gemini_3_5_flash_hard"]["canary_design"]["single_variant_count"] == 1


def test_write_check_roundtrip_tamper_and_zero_git_dependency(computed_audit, monkeypatch, tmp_path):
    no_git_root = tmp_path / "clean_tree_without_git"
    (no_git_root / "data" / "runs" / "committed").mkdir(parents=True)
    (no_git_root / "results" / "frontier_replication").mkdir(parents=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        no_git_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "frontier_replication" / "v1.4",
        no_git_root / "results" / "frontier_replication" / "v1.4",
    )
    assert not (no_git_root / ".git").exists()

    out_json = tmp_path / "out" / "trajectory_audit.json"
    out_md = tmp_path / "out" / "frontier_trajectory_audit_v14.md"

    orig_compute = fta.compute_audit
    no_git_audit = orig_compute(root=no_git_root, verify_replays=True, enforce_expected_counts=True)
    assert no_git_audit["summary"]["episode_counts"] == EXPECTED_COUNTS
    assert fta.approx_equal(no_git_audit, computed_audit, tol=1e-12)

    monkeypatch.setattr(
        fta,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: copy.deepcopy(no_git_audit),
    )

    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data = json.loads(out_json.read_text(encoding="utf-8"))
    orig_val = data["cohorts"][0]["tool_use"]["mean_total_tool_calls"]
    data["cohorts"][0]["tool_use"]["mean_total_tool_calls"] = orig_val + 5e-11
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data["cohorts"][0]["tool_use"]["mean_total_tool_calls"] = orig_val + 1e-5
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    data["cohorts"][0]["tool_use"]["mean_total_tool_calls"] = orig_val
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert fta.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

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
        "final_day": 14,
        "end_reason": "horizon",
        "steps": [
            {"t": 1, "day": 1, "tool": "read_access_logs", "args": {"day_from": 1, "day_to": 1}, "result": {"ok": True}},
            {"t": 2, "day": 1, "tool": "advance_day", "args": {}, "result": {"ok": True}},
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
    assert row["collateral_and_horizon"]["abstention_rate"] == 0.5
    assert row["collateral_and_horizon"]["mean_accusation_day"] == 5.0
    assert row["collateral_and_horizon"]["mean_final_day_all_episodes"] == 9.5
    assert row["collateral_and_horizon"]["mean_restrict_calls_per_episode"] == 0.5
    assert math.isclose(row["token_and_cache"]["cached_input_pct"], 87.5)
    assert row["token_and_cache"]["episodes_over_2400s"] == 1
    assert row["token_and_cache"]["episodes_over_3600s"] == 0

    with pytest.raises(ValueError, match="duplicate seeds"):
        fta.compute_cohort_metrics(spec, [ep1, ep1], verify_replays=True)

    bad_ep = dict(ep1, score=0.99)
    with pytest.raises(ValueError, match="replay mismatches"):
        fta.compute_cohort_metrics(spec, [bad_ep], verify_replays=True)


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
