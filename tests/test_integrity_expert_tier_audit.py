from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import scripts.integrity_expert_tier_audit as audit


def test_seed_parsing_and_bootstrap_helpers() -> None:
    assert audit.parse_seeds("71000-71003, 71010") == [71000, 71001, 71002, 71003, 71010]
    assert audit.ci95([0.5]) == 0.0
    assert audit.ci95([0.0, 1.0, 0.0, 1.0]) > 0.0
    lo, hi = audit.boot_ratio([0.5, 0.6, 0.4], [0.5, 0.5, 0.5], resamples=500, rng_seed=0)
    assert 0.7 <= lo <= 1.0 <= hi <= 1.3


def test_verdict_29ca3bc5_and_paired_solver_verification() -> None:
    res = audit.audit_verdict_payload(
        audit.VERDICT_SNAPSHOT_29CA3BC5,
        audit.PAIRED_SOLVER_SNAPSHOT_29CA3BC5,
    )
    assert res["n"] == 13
    assert res["correct_count"] == 13
    assert res["n_accused"] == 13
    assert res["zero_timeout_or_error_in_valid"] is True
    assert res["score_invariant_violations"] == []
    assert res["formatted_luck_headline"] == "84% [52%, 128%]"
    assert res["matches_gap_md_84_52_128"] is True
    assert res["gemini_mean_diff"] < 1e-12
    assert res["solver_mean_diff"] < 1e-12
    assert res["raw_ratio_diff"] < 1e-12
    assert max(res["raw_ratio_ci_diff"]) < 1e-12
    assert res["luck_adj_gemini_diff"] < 1e-12
    assert res["mean_gemini_P_diff"] < 1e-12
    assert res["gemini_single_canary_hit_seeds"] == [60002, 60013]
    assert res["reported_gemini_below_break_even"] == 0
    assert res["true_gemini_below_break_even"] == 3
    assert res["true_below_break_even_seeds"] == [60003, 60012, 60019]
    assert res["below_break_even_bug_confirmed"] is True
    assert res["missing_seeds_60000_60020"] == [60000, 60006, 60007, 60008, 60009, 60014, 60017, 60018]
    assert res["missing_seeds_internal_60001_60020"] == [60006, 60007, 60008, 60009, 60014, 60017, 60018]
    assert res["fails_ship_bar"] is True
    assert len(res["ship_bar_reasons"]) == 3

    sol = res["solver_verification"]
    assert sol is not None
    assert sol["score_mismatches"] == []
    assert sol["luck_adj_solver_diff"] < 1e-12
    assert sol["luck_adj_ratio_diff"] < 1e-12
    assert max(sol["luck_adj_ci_diff"]) < 1e-12
    assert sol["recomputed_solver_accused"] == 12
    assert sol["recomputed_solver_correct"] == 10
    assert sol["recomputed_solver_single_canary_hits"] == 4
    assert sol["recomputed_solver_below_break_even"] == 0
    assert sol["solver_mean_P_diff"] < 1e-12


def test_verdict_filter_semantics_and_break_even_key_mismatch() -> None:
    filt = audit.audit_verdict_filter_semantics()
    assert filt["expert_verdict_kept_seeds"] == [60012]
    assert filt["canonical_kept_seeds"] == [60012, 60006, 60007]
    assert filt["silently_dropped_played_seeds"] == [60006, 60007]
    assert filt["drops_unaccused_timeouts_and_abstentions"] is True
    assert filt["expert_verdict_below_break_even"] == 0
    assert filt["canonical_below_break_even"] == 1
    assert filt["meta_v_key_mismatch_confirmed"] is True


def test_justsilas_compatibility_and_world_pin_guards() -> None:
    compat = audit.audit_justsilas_integration_compat()
    assert compat["ok"] is True
    assert compat["expert_in_tiers"] is False
    assert compat["justsilas_hard_rl_depts"] == [4]
    assert compat["harbor_expert_rejected"] is True
    assert compat["solver_str_expert_error"] == "KeyError: 'expert'"
    assert compat["exact_block_returns_none"] is True
    assert compat["param_block_parses_fa_070"] is True
    assert compat["params_from_instruction_parses_fa_070"] is True
    assert compat["prose_only_returns_none"] is True
    assert compat["tier_from_instruction_returns_none"] is True
    assert compat["default_threshold_on_expert"] == pytest.approx(0.9)

    digests = audit.compute_world_digests()
    assert digests["hard_rl:0"]["digest"] == "746f0f2bd6fe61fe"
    assert digests["hard_rl:0"]["n_depts"] == 4
    assert digests["hard_rl:0"]["mole"] == "e20"
    assert digests["hard_rl:0"]["decoy"] == "e36"

    gap_check = audit.check_gap_md_expert_entry()
    assert gap_check["ok"] is True


def test_cli_standalone_self_test_and_report_validation(tmp_path: Path) -> None:
    from canary import rules

    out_json = tmp_path / "selftest.json"
    report_path = REPO / "docs" / "reports" / "integrity_expert_tier_audit.md"
    rc = audit.main([
        "--self-test",
        "--check-report",
        str(report_path),
        "--out-json",
        str(out_json),
    ])
    assert rc == 0
    assert "expert" not in rules.TIERS

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["tiers_clean_after"] is True
    assert payload["fuzz_best_non_solver_score"] == 0.0
    assert payload["fuzz_violations"] == 0
    assert payload["lazy_baselines"]["all_checks_pass"] is True
    assert payload["v_and_known_v"]["all_ok"] is True
    assert payload["report_check"]["ok"] is True


def test_report_and_source_hygiene_gates() -> None:
    report_path = REPO / "docs" / "reports" / "integrity_expert_tier_audit.md"
    script_path = REPO / "scripts" / "integrity_expert_tier_audit.py"
    test_path = Path(__file__).resolve()

    report_text = report_path.read_text(encoding="utf-8")
    script_text = script_path.read_text(encoding="utf-8")
    test_text = test_path.read_text(encoding="utf-8")

    for dash in ("\u2014", "\u2013", "\u2212"):
        assert dash not in report_text
        assert dash not in script_text
        assert dash not in test_text

    hash_char = chr(35)
    assert hash_char not in script_text
    assert hash_char not in test_text

    banned_model = "gemini-" + "3.5-flash"
    assert banned_model not in report_text
    assert banned_model not in script_text
    assert banned_model not in test_text

    expected_report_tokens = (
        "origin/justSilas-expert",
        "29ca3bc5",
        "036b90c7",
        "244434fc",
        "84% [52%, 128%]",
        "0.4071",
        "0.0808",
        "0.0479",
        "-0.5297",
        "5,570",
        "8,200",
        "EXP-BUG-01",
        "EXP-BUG-02",
        "EXP-BUG-03",
        "EXP-BUG-04",
        "EXP-BUG-05",
        "harbor/build.py",
        "SolverPolicy(\"expert\")",
        "hard_rl",
    )
    for tok in expected_report_tokens:
        assert tok in report_text, f"missing report token: {tok}"
