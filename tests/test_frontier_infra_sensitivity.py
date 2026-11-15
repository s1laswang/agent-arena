"""Tests for scripts/frontier_infra_sensitivity.py, infra_sensitivity.json, and frontier_infra_sensitivity_v14.md."""
from __future__ import annotations

import copy
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
SCRIPT_PATH = SCRIPTS_DIR / "frontier_infra_sensitivity.py"
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "infra_sensitivity.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_infra_sensitivity_v14.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("frontier_infra_sensitivity", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fis = _load_module()


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _make_gitless_root(tmp_path: Path, name: str = "gitless_root", link_gap_md: bool = True) -> Path:
    syn_root = tmp_path / name
    (syn_root / "data" / "runs" / "committed").mkdir(parents=True)
    (syn_root / "results" / "frontier_replication").mkdir(parents=True)
    (syn_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        syn_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "frontier_replication" / "v1.4",
        syn_root / "results" / "frontier_replication" / "v1.4",
    )
    if link_gap_md:
        os.symlink(
            ROOT / "docs" / "reports" / "gap.md",
            syn_root / "docs" / "reports" / "gap.md",
        )
    assert not (syn_root / ".git").exists()
    return syn_root


@pytest.fixture(scope="module")
def computed_summary():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    env_before = dict(os.environ)
    try:
        out = fis.compute_summary(root=ROOT, verify_replays=True)
    finally:
        mp.undo()
    assert dict(os.environ) == env_before
    return out


def test_check_cli_offline_zero_subprocess_and_size_cap(computed_summary, monkeypatch, capsys):
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(
        fis,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary),
    )
    assert fis.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "OK infra_sensitivity=PASS committed_replays=442 replication_replays=305 excluded_attempts=71" in out
    assert JSON_PATH.stat().st_size <= fis.MAX_JSON_BYTES
    assert fis.MAX_JSON_BYTES == 45 * 1024
    assert JSON_PATH.read_bytes() == fis.serialize_summary_json(computed_summary).encode("utf-8")
    assert MD_PATH.read_bytes() == fis.render_markdown(computed_summary).encode("utf-8")


def test_gitless_root_write_check_roundtrip_and_byte_identity(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    no_git_root = _make_gitless_root(tmp_path, name="zip_export_tree", link_gap_md=True)
    out_json = tmp_path / "out" / "infra_sensitivity.json"
    out_md = tmp_path / "out" / "frontier_infra_sensitivity_v14.md"

    assert fis.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert fis.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert out_json.is_file() and out_md.is_file()
    assert out_json.stat().st_size <= fis.MAX_JSON_BYTES
    assert out_json.read_bytes() == JSON_PATH.read_bytes()
    assert out_md.read_bytes() == MD_PATH.read_bytes()

    fresh_written = json.loads(out_json.read_text(encoding="utf-8"))
    monkeypatch.setattr(
        fis,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: copy.deepcopy(fresh_written),
    )
    assert fis.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0


def test_replay_provenance_and_meta_exclusion_invariants(computed_summary):
    assert computed_summary["schema_version"] == "v1.4-frontier-infra-sensitivity-1"
    assert computed_summary["tiers_version"] == "v1.4"
    assert computed_summary["pure_cpu_zero_api_calls"] is True

    sl = computed_summary["seed_lock_and_replay"]
    assert sl["primary_seeds"] == [0, 29]
    assert sl["primary_lock_classification"] == "post_hoc_lock_not_preregistered"
    assert sl["primary_commits"] == {
        "episodes_commit": "8fd4dec",
        "seed_lock_commit": "671ed96",
        "lock_delay_seconds": 28,
    }
    assert sl["extension_preregistration_commit"] == "f9fb7a4a"
    assert sl["gpt55_preregistration_commit"] == "cf394894"
    assert sl["gpt55_runner_guards"] == {
        "timeout_s": 7200,
        "max_spend_usd": 200.0,
        "stop_launch_at_helsinki": "08:15",
        "hard_drop_at_helsinki": "08:45",
    }

    comm_rep = sl["committed_v14_replay"]
    assert comm_rep == {
        "cohort": "data/runs/committed/v1.4",
        "total": 442,
        "verified": 442,
        "mismatches": 0,
        "duplicates": 0,
    }
    fr8_rep = sl["replication_v14_replay"]
    assert fr8_rep == {
        "cohort": "results/frontier_replication/v1.4",
        "total": 305,
        "verified": 305,
        "mismatches": 0,
        "duplicates": 0,
    }

    cm = computed_summary["cohort_meta_audit"]
    assert cm["committed_excluded_attempts_total"] == 71
    assert cm["committed_excluded_by_category"] == {
        "provider_quota": 31,
        "cli_error_event": 19,
        "empty_model_response": 12,
        "provider_unavailable": 7,
        "mcp_server_error": 2,
    }
    assert sum(cm["committed_excluded_by_category"].values()) == 71

    by_id = {c["cohort_id"]: c for c in cm["committed_cohorts"]}
    assert by_id["committed_opencode_carbon_medium_0_29"]["excluded_attempts_total"] == 15
    assert by_id["committed_opencode_carbon_medium_0_29"]["affected_seeds"] == [7, 12, 13, 17, 19, 22, 27, 29]
    assert by_id["committed_opencode_carbon_medium_0_29"]["empty_reply_seeds"] == [7, 12, 13, 17, 22, 29]
    assert by_id["committed_opencode_carbon_medium_0_29"]["completed_valid_count"] == 30

    assert by_id["committed_opencode_carbon_hard_0_29"]["excluded_attempts_total"] == 25
    assert by_id["committed_opencode_carbon_hard_0_29"]["affected_seeds"] == [
        3,
        14,
        15,
        18,
        19,
        23,
        24,
        25,
        26,
        27,
        29,
    ]
    assert by_id["committed_opencode_carbon_hard_0_29"]["empty_reply_seeds"] == [3, 19, 25, 26, 27]
    assert by_id["committed_opencode_carbon_hard_0_29"]["completed_valid_count"] == 30

    assert by_id["committed_opencode_carbon_ext_hard_30_59"]["excluded_attempts_total"] == 31
    assert by_id["committed_opencode_carbon_ext_hard_30_59"]["category_counts"] == {"provider_quota": 31}
    assert by_id["committed_opencode_carbon_ext_hard_30_59"]["completed_valid_count"] == 2
    assert by_id["committed_opencode_carbon_ext_hard_30_59"]["excluded_without_completion_seeds"] == [
        30,
        31,
        32,
        33,
        35,
        36,
        38,
        39,
        40,
    ]
    assert by_id["committed_opencode_carbon_ext_hard_30_59"]["unstarted_planned_seeds_count"] == 19

    assert by_id["committed_inproc_carbon_medium_0_29"]["excluded_attempts_total"] == 0
    assert by_id["committed_inproc_carbon_hard_0_29"]["excluded_attempts_total"] == 0

    flash_hard_meta = fis.summarize_run_dir_meta(
        ROOT,
        ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-3.5-flash" / "hard",
        "committed_opencode_flash_hard_0_29",
    )
    assert flash_hard_meta["excluded_attempts_total"] == 0
    assert flash_hard_meta["completed_valid_count"] == 30

    rep_by_id = {c["cohort_id"]: c for c in cm["replication_sharded_cohorts"]}
    assert rep_by_id["replication_opencode_carbon_hard_30_59"]["excluded_attempts_total"] == 0
    assert rep_by_id["replication_opencode_carbon_hard_30_59"]["completed_seeds"] == [30, 34, 42, 45, 57]
    assert rep_by_id["replication_opencode_carbon_hard_30_59"]["shard_count"] == 5
    assert rep_by_id["replication_opencode_flash_medium_0_29"]["excluded_attempts_total"] == 0
    assert rep_by_id["replication_opencode_flash_medium_0_29"]["completed_valid_count"] == 30
    assert rep_by_id["replication_opencode_flash_medium_0_29"]["completed_seeds"] == list(range(30))


def test_imputation_regimes_exact_figures_and_monotonicity(computed_summary):
    imp = computed_summary["imputation_sensitivity_0_29"]
    assert imp["monotonic_retry_helps_frontier"] is True

    h1, h2, h3 = imp["hard_0_29_regimes"]
    assert h1["zeroed_seeds"] == []
    assert h1["n"] == 30
    assert round(h1["mean"], 3) == 0.322
    assert round(h1["ci"], 3) == 0.199
    assert round(h1["solver_same_seeds"], 3) == 0.499
    assert round(h1["ratio"] * 100) == 65
    assert round(h1["post_expected"], 3) == 0.360
    assert round(h1["post_expected_ratio"] * 100) == 72

    assert h2["zeroed_seeds"] == [3, 19, 25, 26, 27]
    assert h2["zeroed_count"] == 5
    assert round(h2["mean"], 3) == 0.279
    assert round(h2["ratio"] * 100) == 56
    assert round(h2["post_expected"], 3) == 0.277
    assert round(h2["post_expected_ratio"] * 100) == 55

    assert h3["zeroed_seeds"] == [3, 14, 15, 18, 19, 23, 24, 25, 26, 27, 29]
    assert h3["zeroed_count"] == 11
    assert round(h3["mean"], 3) == 0.277
    assert round(h3["ratio"] * 100) == 56
    assert round(h3["post_expected"], 3) == 0.237
    assert round(h3["post_expected_ratio"] * 100) == 47

    assert h1["mean"] > h2["mean"] > h3["mean"]
    assert h1["post_expected"] > h2["post_expected"] > h3["post_expected"]
    assert imp["hard_non_empty_retried_seeds_detail"] == {
        "seeds": [14, 15, 18, 23, 24, 29],
        "wrong_accusation_seeds_on_retry": [15, 18],
    }

    m1, m2, m3 = imp["medium_0_29_regimes"]
    assert m1["zeroed_seeds"] == []
    assert m2["zeroed_seeds"] == [7, 12, 13, 17, 22, 29]
    assert m3["zeroed_seeds"] == [7, 12, 13, 17, 19, 22, 27, 29]
    assert [round(m1["mean"], 3), round(m2["mean"], 3), round(m3["mean"], 3)] == [0.713, 0.579, 0.534]
    assert [
        round(m1["post_expected"], 3),
        round(m2["post_expected"], 3),
        round(m3["post_expected"], 3),
    ] == [0.652, 0.558, 0.513]
    assert m1["mean"] > m2["mean"] > m3["mean"]
    assert m1["post_expected"] > m2["post_expected"] > m3["post_expected"]

    fl_play, fl_z28 = imp["flash_medium_s28_rerun_sensitivity"]
    assert fl_play["zeroed_seeds"] == []
    assert fl_z28["zeroed_seeds"] == [28]
    assert round(fl_play["mean"], 3) == 0.434
    assert round(fl_z28["mean"], 3) == 0.410
    assert fl_play["mean"] > fl_z28["mean"]


def test_timeout_sweep_and_quota_survivor_bias(computed_summary):
    wc = computed_summary["wall_clock_timeout_sweep"]
    assert wc["thresholds_s"] == [900, 1800, 2400, 3600, 7200]
    assert wc["zero_truncation_at_7200s"] is True
    assert math.isclose(wc["max_observed_opencode_wall_s"], 6591.7, abs_tol=1e-9)
    assert wc["max_observed_opencode_wall_s"] < 7200.0

    wc_by_id = {c["cohort_id"]: c for c in wc["cohorts"]}
    hard_wc = wc_by_id["opencode_carbon_hard_0_29"]["thresholds"]
    med_wc = wc_by_id["opencode_carbon_medium_0_29"]["thresholds"]

    assert [hard_wc[k]["exceeded_count"] for k in ("900", "1800", "2400", "3600", "7200")] == [30, 24, 13, 5, 0]
    assert hard_wc["3600"]["exceeded_seeds"] == [5, 11, 19, 24, 29]
    assert hard_wc["900"]["counterfactual_mean"] == 0.0
    assert round(hard_wc["7200"]["counterfactual_mean"], 3) == 0.322

    assert [med_wc[k]["exceeded_count"] for k in ("900", "1800", "2400", "3600", "7200")] == [26, 7, 2, 1, 0]
    assert med_wc["3600"]["exceeded_seeds"] == [29]
    assert round(med_wc["7200"]["counterfactual_mean"], 3) == 0.713

    for cohort in wc["cohorts"]:
        assert cohort["thresholds"]["7200"]["exceeded_count"] == 0

    ext = computed_summary["ext_survivor_duration_audit"]
    assert ext["attempted_seed_window"] == list(range(30, 41))
    assert ext["completed_seeds"] == [34, 37]
    assert ext["quota_blocked_seeds"] == [30, 31, 32, 33, 35, 36, 38, 39, 40]
    assert ext["quota_excluded_attempts"] == 31
    assert ext["unstarted_seeds_count"] == 19

    sol_comp = ext["solver_on_ext_completed_seeds"]
    sol_blk = ext["solver_on_ext_quota_blocked_seeds"]
    sol_all = ext["solver_on_ext_all_30_59"]
    assert sol_comp["n"] == 2
    assert sol_comp["seeds"] == [34, 37]
    assert math.isclose(sol_comp["mean_final_day"], 5.50, abs_tol=1e-9)
    assert math.isclose(sol_comp["mean_score"], 0.735, abs_tol=1e-9)

    assert sol_blk["n"] == 9
    assert round(sol_blk["mean_final_day"], 2) == 10.56
    assert round(sol_blk["mean_score"], 3) == 0.194
    assert sol_comp["mean_final_day"] < sol_blk["mean_final_day"]
    assert sol_comp["mean_score"] > sol_blk["mean_score"]

    assert sol_all["n"] == 30
    assert round(sol_all["mean_score"], 3) == 0.498
    assert round(sol_all["mean_final_day"], 2) == 8.83

    ext_surv = ext["ext_carbon_hard_survivors"]
    prim_hard = ext["primary_carbon_hard_0_29"]
    assert ext_surv["mean_wall_s"] < prim_hard["mean_wall_s"]
    assert ext_surv["mean_final_day"] < prim_hard["mean_final_day"]
    assert ext_surv["mean_steps"] < prim_hard["mean_steps"]
    assert round(ext["wall_s_ratio_ext_over_primary"], 2) == 0.57
    assert round(ext["final_day_ratio_ext_over_primary"], 2) == 0.41
    assert round(ext["steps_ratio_ext_over_primary"], 2) == 0.45

    assert ext["shared_seed_ext_vs_fr8_replication"] == [
        {
            "seed": 34,
            "ext_score": 0.79,
            "ext_final_day": 5,
            "ext_steps": 51,
            "ext_wall_s": 1391.8,
            "fr8_rep_score": 0.82,
            "fr8_rep_final_day": 8,
            "fr8_rep_steps": 83,
            "fr8_rep_wall_s": 1499.2,
        }
    ]


def test_gap_ships_flash_hard_false_and_true(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    syn_root = _make_gitless_root(tmp_path, name="flash_gate_root", link_gap_md=False)
    gap_file = syn_root / "docs" / "reports" / "gap.md"
    assert fis.gap_ships_flash_hard(syn_root) is False

    gap_file.write_text("Primary headline: gemini-4-carbon hard 65% [24%, 98%]\n", encoding="utf-8")
    assert fis.gap_ships_flash_hard(syn_root) is False
    sum_false = fis.compute_summary(root=syn_root, verify_replays=False)
    assert sum_false["seed_lock_and_replay"]["flash_hard_held_pending_gap_md"] is True
    assert len(sum_false["cohort_meta_audit"]["committed_cohorts"]) == 5
    assert len(sum_false["wall_clock_timeout_sweep"]["cohorts"]) == 5
    md_false = fis.render_markdown(sum_false)
    assert "does not yet ship `gemini-3.5-flash` hard" in md_false
    assert "OpenCode gemini-3.5-flash hard (0-29)" not in md_false
    assert len(fis.serialize_summary_json(sum_false).encode("utf-8")) <= fis.MAX_JSON_BYTES

    gap_file.write_text(
        "Primary headline: gemini-4-carbon and opencode:google/gemini-3.5-flash hard (0-29)\n",
        encoding="utf-8",
    )
    assert fis.gap_ships_flash_hard(syn_root) is True
    sum_true = fis.compute_summary(root=syn_root, verify_replays=False)
    assert sum_true["seed_lock_and_replay"]["flash_hard_held_pending_gap_md"] is False
    assert len(sum_true["cohort_meta_audit"]["committed_cohorts"]) == 6
    assert sum_true["cohort_meta_audit"]["committed_cohorts"][-1]["cohort_id"] == "committed_opencode_flash_hard_0_29"
    assert sum_true["cohort_meta_audit"]["committed_cohorts"][-1]["excluded_attempts_total"] == 0
    assert sum_true["cohort_meta_audit"]["committed_excluded_attempts_total"] == 71
    assert len(sum_true["wall_clock_timeout_sweep"]["cohorts"]) == 6
    assert sum_true["wall_clock_timeout_sweep"]["cohorts"][-1]["cohort_id"] == "opencode_flash_hard_0_29"
    assert sum_true["wall_clock_timeout_sweep"]["zero_truncation_at_7200s"] is True

    json_true_bytes = len(fis.serialize_summary_json(sum_true).encode("utf-8"))
    assert json_true_bytes <= fis.MAX_JSON_BYTES
    md_true = fis.render_markdown(sum_true)
    assert "includes `gemini-3.5-flash` hard (`0-29`)" in md_true
    assert "OpenCode gemini-3.5-flash hard (0-29)" in md_true

    out_json = tmp_path / "flash_true_out" / "infra_sensitivity.json"
    out_md = tmp_path / "flash_true_out" / "frontier_infra_sensitivity_v14.md"
    monkeypatch.setattr(
        fis,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: copy.deepcopy(sum_true),
    )
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0
    assert out_json.stat().st_size <= fis.MAX_JSON_BYTES


def test_tamper_detection_json_md_and_replay(computed_summary, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    syn_root = _make_gitless_root(tmp_path, name="tamper_root", link_gap_md=True)
    out_json = tmp_path / "tamper_out" / "infra_sensitivity.json"
    out_md = tmp_path / "tamper_out" / "frontier_infra_sensitivity_v14.md"

    monkeypatch.setattr(
        fis,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary),
    )

    with pytest.raises(SystemExit):
        fis.main(["--write", "--check"])

    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data = json.loads(out_json.read_text(encoding="utf-8"))
    orig_mean = data["imputation_sensitivity_0_29"]["hard_0_29_regimes"][0]["mean"]

    data["imputation_sensitivity_0_29"]["hard_0_29_regimes"][0]["mean"] = orig_mean + 5e-11
    out_json.write_text(fis.serialize_summary_json(data), encoding="utf-8")
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data["imputation_sensitivity_0_29"]["hard_0_29_regimes"][0]["mean"] = orig_mean + 1e-4
    out_json.write_text(fis.serialize_summary_json(data), encoding="utf-8")
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    data["imputation_sensitivity_0_29"]["hard_0_29_regimes"][0]["mean"] = orig_mean
    oversized = fis.serialize_summary_json(data).rstrip("\n") + (" " * 12_000) + "\n"
    assert len(oversized.encode("utf-8")) > fis.MAX_JSON_BYTES
    out_json.write_text(oversized, encoding="utf-8")
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    out_json.write_text(fis.serialize_summary_json(data), encoding="utf-8")
    orig_md = out_md.read_text(encoding="utf-8")
    out_md.write_text(orig_md + "\ntampered line\n", encoding="utf-8")
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    out_md.unlink()
    assert fis.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    sample_file = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    first_ep = fis.read_jsonl(sample_file)[0]
    assert fis.verify_episode_list([first_ep], "unit_single")["verified"] == 1

    tampered_score_ep = dict(first_ep, score=float(first_ep["score"]) + 0.125)
    with pytest.raises(ValueError, match="replay mismatches"):
        fis.verify_episode_list([tampered_score_ep], "unit_tampered_score")

    tampered_acc_ep = dict(first_ep, accused="e99")
    with pytest.raises(ValueError, match="replay mismatches"):
        fis.verify_episode_list([tampered_acc_ep], "unit_tampered_accused")

    with pytest.raises(ValueError, match="duplicate episodes"):
        fis.verify_episode_list([first_ep, dict(first_ep)], "unit_duplicate")


def test_helper_classifiers_and_clean_json():
    assert fis.classify_exclusion_reason("infra:empty_model_response") == "empty_model_response"
    assert fis.classify_exclusion_reason("infra:provider_quota") == "provider_quota"
    assert fis.classify_exclusion_reason("infra:provider_rate_limit") == "provider_rate_limit"
    assert fis.classify_exclusion_reason("infra:provider_unavailable") == "provider_unavailable"
    assert fis.classify_exclusion_reason("infra:cli_error_event") == "cli_error_event"
    assert fis.classify_exclusion_reason("sqlite database is locked") == "opencode_db_locked"
    assert fis.classify_exclusion_reason("TimeoutError talking to MCP server") == "mcp_server_error"
    assert fis.classify_exclusion_reason("unexpected network reset") == "other_infra"

    parsed = fis.parse_exclusion_entry("opencode-hard-19-214512: infra:empty_model_response")
    assert parsed == {
        "attempt_id": "opencode-hard-19-214512",
        "harness": "opencode",
        "tier": "hard",
        "seed": 19,
        "timestamp_hhmmss": "214512",
        "category": "empty_model_response",
    }

    assert fis.clean_json({"nan": float("nan"), "inf": float("inf"), "ok": [1, True, None]}) == {
        "nan": None,
        "inf": None,
        "ok": [1, True, None],
    }
    assert fis.approx_equal({"a": [0.1 + 0.2]}, {"a": [0.3]}, tol=1e-9)
    assert not fis.approx_equal({"a": True}, {"a": 1})
    assert fis.approx_equal(float("nan"), float("nan"))

    imputed = fis.impute_zero_for_seeds(
        [{"tier": "hard", "seed": 0, "agent": "x", "score": 0.8, "correct": True, "accused": "e01"}],
        {0, 1},
        "hard",
        "x",
        {0, 1},
    )
    assert [e["seed"] for e in imputed] == [0, 1]
    assert all(e["score"] == 0.0 and e["correct"] is False and e["accused"] is None for e in imputed)


def test_strict_hygiene_no_hash_in_py_and_no_em_en_dashes():
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    this_test = Path(__file__).resolve()
    py_files = [SCRIPT_PATH, this_test]
    owned_files = [SCRIPT_PATH, JSON_PATH, MD_PATH, this_test]

    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
        src = pf.read_text(encoding="utf-8")
        assert hash_char not in src, f"found {hash_char!r} character in {pf}"

    for f in owned_files:
        txt = f.read_text(encoding="utf-8")
        assert em_dash not in txt, f"found em dash in {f}"
        assert en_dash not in txt, f"found en dash in {f}"

    assert JSON_PATH.stat().st_size <= fis.MAX_JSON_BYTES
