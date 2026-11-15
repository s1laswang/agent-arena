from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

import pytest

from canary.env import Env
from scripts import integrity_sidechannel_and_text_sweep as sweep

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "integrity_sidechannel_and_text_sweep.py"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "integrity_sidechannel_and_text_sweep.md"
TEST_PATH = Path(__file__).resolve()


@pytest.fixture(scope="module")
def quick_summary(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    out_dir = tmp_path_factory.mktemp("w1_sidechannel_quick")
    out_json = out_dir / "quick_summary.json"
    rc = sweep.main(
        [
            "--quick",
            "--out-json",
            str(out_json),
            "--check-report",
            str(REPORT_PATH),
        ]
    )
    assert rc == 0
    return json.loads(out_json.read_text(encoding="utf-8"))


def test_quick_sweep_zero_leaks_and_floor_bounds(quick_summary: dict[str, object]) -> None:
    assert quick_summary["ok"] is True
    assert quick_summary["report_check"]["ok"] is True
    assert set(sweep.ALL_TARGETS) <= set(quick_summary["targets"])

    hl = quick_summary["headline"]
    assert hl["primary_episodes"] >= 20
    assert hl["dev_episodes"] >= 10
    assert hl["judge_episodes"] >= 10
    assert hl["tool_parity_seed_pairs"] >= 20
    assert hl["detail_probes_checked"] >= 2500
    assert hl["deep_encoding_episodes"] >= 5
    assert hl["prose_texts_scanned"] >= 5000
    assert hl["deep_encoding_texts_scanned"] >= 1000
    assert hl["documents_checked"] >= 1000
    assert hl["access_logs_checked"] >= 10000
    assert hl["messages_checked"] >= 2000

    assert hl["non_canary_predictors_beating_fair_bar"] == 0
    assert hl["conditional_interview_leaks"] == 0
    assert hl["doc_recipient_order_inversions"] == 0
    assert hl["access_log_order_inversions"] == 0
    assert hl["message_id_sequence_gaps"] == 0
    assert hl["text_lint_violations"] == 0
    assert hl["all_13_tools_state_matched_byte_parity"] is True
    assert hl["all_13_tools_detail_parity"] is True
    assert hl["detail_mole_id_leaks"] == 0
    assert hl["detail_seed_leaks"] == 0
    assert hl["detail_hidden_v_leaks"] == 0
    assert hl["encoded_secret_leaks"] == 0
    assert hl["planted_positive_controls_all_detected"] is True
    assert hl["solver_beats_non_canary_all_targets"] is True


def test_fair_bars_and_feature_predictors_structure(quick_summary: dict[str, object]) -> None:
    bars = quick_summary["fair_bars"]
    pooled = quick_summary["feature_audit_pooled"]
    for target in sweep.ALL_TARGETS:
        tb = bars[target]
        assert 0.0 < tb["bar_chance"] <= tb["bar_decoy_excluded"] <= 1.0
        assert tb["bar_interview_budget_decoy"] >= tb["bar_decoy_excluded"] - 1e-6
        assert tb["bar_joint_non_canary"] >= tb["bar_logs_bayes"] - 1e-3

        tp = pooled[target]
        assert tp["ok"] is True
        assert tp["n_episodes"] >= 4
        assert len(tp["predictors"]) >= 24
        assert all(row["beats_fair_bar"] is False for row in tp["predictors"])
        assert tp["interview_signal_template_mismatches"] == 0
        assert len(tp["interview_conditional_strata"]) >= 8


def test_tool_parity_and_planted_controls_detect_synthetic_leaks(
    quick_summary: dict[str, object],
) -> None:
    controls = quick_summary["planted_positive_controls"]
    assert controls["all_detected"] is True
    assert controls["planted_roster_name_length_leak"]["detected"] is True
    assert controls["planted_doc_and_log_ordering_leak"]["detected"] is True
    assert controls["planted_tool_response_byte_leak"]["detected"] is True
    assert controls["planted_tool_detail_parity_leak"]["detected"] is True
    assert controls["planted_tool_detail_secret_leak"]["detected"] is True
    assert controls["planted_stego_text_leaks"]["detected"] is True

    clean_parity = sweep.audit_tool_response_parity("medium", [0], env_cls=Env)
    assert clean_parity["ok"] is True
    assert clean_parity["tools_checked"] >= 13
    assert clean_parity["all_13_tools_state_matched_exact_zero"] is True
    assert clean_parity["detail_error_audit"]["ok"] is True

    byte_leak = sweep.audit_tool_response_parity("easy", [0], env_cls=sweep.PlantedToolByteLeakEnv)
    assert byte_leak["ok"] is False
    assert byte_leak["per_tool_state_matched"]["restrict_access"]["max_abs_byte_diff"] > 0

    detail_parity_leak = sweep.audit_tool_response_parity(
        "medium", [0], env_cls=sweep.PlantedToolDetailParityEnv
    )
    assert detail_parity_leak["ok"] is False
    assert detail_parity_leak["all_13_tools_state_matched_exact_zero"] is True
    assert detail_parity_leak["detail_error_audit"]["actor_parity_mismatches"] >= 1

    detail_secret_leak = sweep.audit_tool_response_parity(
        "medium", [0], env_cls=sweep.PlantedToolDetailSecretLeakEnv
    )
    assert detail_secret_leak["ok"] is False
    ds = detail_secret_leak["detail_error_audit"]
    assert ds["mole_id_leaks"] >= 1
    assert ds["seed_leaks"] >= 1
    assert ds["hidden_v_leaks"] >= 1


def test_report_only_compat_issues_verified(quick_summary: dict[str, object]) -> None:
    issues = quick_summary["report_only_issues"]
    assert issues["text_probe_tracks_fail_without_tier_params"] is True
    assert {"hard_forge", "hard_rl"} <= set(issues["text_probe_track_keyerrors"])
    assert len(sweep.EVASIVE_TEMPLATES) >= 16
    assert issues["evasive_templates_containing_literal_evasive"] == 0
    assert issues["solver_interview_evasive_samples"] >= 1
    assert issues["solver_interview_ingested_as_evasive"] == 0
    assert issues["solver_interview_ingest_always_false_confirmed"] is True
    assert issues["hard_dept_count"] >= 5
    assert issues["hard_forge_dept_count"] >= 5
    assert issues["hard_rl_dept_count"] == 4
    assert "Research" in issues["hard_rl_missing_depts_vs_hard"]


def test_report_validator_and_owned_file_hygiene(tmp_path: Path) -> None:
    rep_res = sweep.check_report_file(REPORT_PATH)
    assert rep_res["ok"] is True

    em_dash = chr(0x2014)
    banned_kw = "pre-" + "reg"
    bad_md = tmp_path / "bad_report.md"
    bad_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8") + f"\n{banned_kw} {em_dash}\n",
        encoding="utf-8",
    )
    bad_res = sweep.check_report_file(bad_md)
    assert bad_res["ok"] is False
    assert em_dash in bad_res["bad_dashes"]
    assert banned_kw in bad_res["banned_prereg"]

    forbidden_dashes = (chr(0x2014), chr(0x2013), chr(0x2212))
    for path in (SCRIPT_PATH, REPORT_PATH, TEST_PATH):
        assert path.is_file()
        assert path.stat().st_size <= 130 * 1024
        content = path.read_text(encoding="utf-8")
        for ch in forbidden_dashes:
            assert ch not in content

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        comments = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == []

    low_md = REPORT_PATH.read_text(encoding="utf-8").lower()
    assert ("pre-" + "reg") not in low_md
    assert ("pre" + "reg") not in low_md
    assert "post-hoc lock" in low_md
