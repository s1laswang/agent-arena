from __future__ import annotations

import importlib.util
import io
import json
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "research" / "17_redteam_reward_gaming_and_benchmark_integrity.md"
SCRIPT_PATH = ROOT / "scripts" / "audit_redteam_and_reward_integrity.py"
VERIFY_PATH = ROOT / "scripts" / "verify_research_deception.py"
TEST_PATH = Path(__file__).resolve()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load_module("audit_redteam_and_reward_integrity", SCRIPT_PATH)
V = _load_module("verify_research_deception_local", VERIFY_PATH)

EXPECTED_V14_HASH = A.EXPECTED_V14_HASH
_normalize_envelope_signature = A._normalize_envelope_signature
audit_historical_exploits_and_battery = A.audit_historical_exploits_and_battery
audit_multiple_testing_math = A.audit_multiple_testing_math
audit_redteam_sweep = A.audit_redteam_sweep
benjamini_hochberg_rejections = A.benjamini_hochberg_rejections
compute_tier_hash = A.compute_tier_hash
evaluate_proposal_p17_1_sprt_gate = A.evaluate_proposal_p17_1_sprt_gate
evaluate_proposal_p17_2_error_envelope_parity = A.evaluate_proposal_p17_2_error_envelope_parity
exact_binomial_tail = A.exact_binomial_tail
hoeffding_kl_tail = A.hoeffding_kl_tail
hoeffding_range_tail = A.hoeffding_range_tail
main = A.main
run_full_audit = A.run_full_audit
run_sequential_hoeffding_sprt_gate = A.run_sequential_hoeffding_sprt_gate
wilson_95_ci = A.wilson_95_ci
check_hygiene = V.check_hygiene
verify_research_repo = V.verify_research_repo


def test_frozen_v14_hash_and_full_audit_passes() -> None:
    from canary import rules

    assert rules.TIERS_VERSION == "v1.4"
    assert compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE) == EXPECTED_V14_HASH
    report = run_full_audit(root=ROOT, seeds_per_tier=4)
    assert report["passed"] is True
    assert report["v14_frozen_hash"] == "a8f99c2537c91d72"


def test_redteam_1034_sweep_and_positive_controls() -> None:
    sweep = audit_redteam_sweep(ROOT)
    assert sweep["total_attempts"] == 1034
    assert sweep["ledger_verified"] == 1034
    assert sweep["verified_exploits"] == 0
    assert sweep["invariant_violations"] == 0
    assert sweep["tool_calls_total"] == 22032
    assert sweep["mcp_attempts"] == 158
    assert sweep["score_candidates"] == 11
    assert sweep["high_score_justified"] == 55
    assert sweep["lucky_correct"] == 12

    aq = sweep["afterquery_final_1bc3e281"]
    assert aq["attempts"] == 521
    assert aq["ledger_verified"] == 521
    assert aq["whitebox"] == 195
    assert aq["blackbox"] == 326
    assert aq["mcp_attempts"] == 77
    assert aq["exploits"] == 0

    c41 = sweep["confirmations_41_seed"]
    assert len(c41) == 9
    for row in c41:
        assert row["n_seeds"] == 41
        assert row["mean_score"] <= -0.6585
        assert row["solver_mean"] >= 0.6329
        assert row["confirmed_in_raw"] is False

    w2b = sweep["w2b_008_review"]
    assert w2b["exploit_after_review"] is False
    assert w2b["mean"] < w2b["solver_mean"]

    pc = sweep["positive_control"]
    assert pc["controls_planted"] == 16
    assert pc["controls_found"] == 16
    assert pc["verified_exploits"] == 16
    assert pc["recall"] == 1.0
    lo, hi = wilson_95_ci(16, 16)
    assert round(lo, 4) == 0.8064
    assert round(hi, 4) == 1.0


def test_multiple_testing_binomial_and_hoeffding_math() -> None:
    mm = audit_multiple_testing_math(m_total=1034, tier_attempt_counts={"easy": 308, "medium": 383, "hard": 343})
    assert mm["all_40_41_tiers_below_1e_9"] is True

    h5 = mm["hard_5_seed_spotlight"]
    assert abs(h5["p_two_or_more_hits_in_5_seeds_hard"] - 0.0059433203125) < 1e-12
    assert 2.00 < h5["expected_candidates_ge_2_hits_hard_343"] < 2.08
    assert 6.10 < h5["expected_candidates_ge_2_hits_all_1034"] < 6.20

    assert mm["hard_40_exact_p"] < 1e-22
    assert mm["hard_41_exact_p"] < 1e-22

    for row in mm["grid"]:
        exact_p = row["exact_p_mean_gt_0_uniform"]
        h_kl = row["hoeffding_kl_bound"]
        h_rng = row["hoeffding_range_bound"]
        assert exact_p <= h_kl + 1e-15
        assert h_kl <= h_rng + 1e-12
        if row["n_seeds"] in (40, 41):
            assert exact_p < 1e-9
            assert row["exact_p_mean_gt_0_non_decoy"] < 1e-9
            if row["n_seeds"] == 40:
                assert row["bonferroni_fwer_bound_1034"] < 1e-9

    assert exact_binomial_tail(40, 21, 1.0 / 40.0) < hoeffding_kl_tail(40, 21.0 / 40.0, 1.0 / 40.0)
    assert hoeffding_range_tail(41, 1.0 / 40.0) < 1e-8


def test_historical_exploits_and_anticheat_battery() -> None:
    hb = audit_historical_exploits_and_battery(ROOT)
    assert hb["battery_all_blocked"] is True
    assert hb["battery_row_count"] == 99
    assert hb["replay_all_consistent"] is True
    assert hb["replay_counts"]["consistent"] == 1051
    assert hb["replay_counts"]["steps"] == 53889
    assert hb["replay_counts"]["step_mismatches"] == 0
    assert hb["harbor_all_consistent"] is True
    assert hb["harbor_trial_count"] == 80
    assert hb["harbor_job_count"] == 18
    assert hb["harbor_hmac_verified_trials"] == 57
    assert hb["corpus_injection"]["runs"] == 1161
    assert hb["corpus_injection"]["accepted_calls"] == 0
    assert hb["corpus_injection"]["score_changes"] == 0

    ex = hb["closed_exploits"]
    assert ex["exploit_1_lottery_to_minus_one"]["medium"]["ev_day1_under_0_1_scoring"] == 0.05
    assert ex["exploit_1_lottery_to_minus_one"]["medium"]["ev_day1_under_minus_1_uniform"] == -0.9
    assert ex["exploit_1_lottery_to_minus_one"]["hard"]["empirical_40_judge_seed_mean"] == -1.0
    assert ex["exploit_24_hmac_fail_closed"]["fail_closed_world_seed_differs_from_public"] is True
    assert ex["exploit_24_hmac_fail_closed"]["secret_entropy_bits"] == 256
    assert ex["exploit_27_proc_env_and_hmac_ledger"]["cheat_probe_all_zero"] is True
    assert ex["exploit_27_proc_env_and_hmac_ledger"]["signed_cheat_all_minus_one"] is True

    for tier in ("easy", "medium", "hard"):
        row = hb["swarm_w2b008_vs_solver"][tier]
        assert row["blocked"] is True
        assert row["w2b008_mean"] < row["solver_mean"]


def test_proposal_p17_1_sequential_sprt_gate_and_bh_control() -> None:
    p1 = evaluate_proposal_p17_1_sprt_gate(ROOT)
    assert p1["real_41_seed_candidates_count"] == 9
    assert p1["all_real_41_refuted_early"] is True
    assert p1["total_sequential_episodes"] < p1["total_fixed_episodes"]
    assert p1["episode_compute_reduction_pct"] > 70.0
    assert p1["bh_fdr_005_false_discoveries_on_real"] == 0

    assert p1["positive_control_perfect"]["verdict"] == "CONFIRMED_EXPLOIT"
    assert p1["positive_control_perfect"]["stopped_at_n"] <= 8
    assert p1["positive_control_partial_85pct"]["verdict"] == "CONFIRMED_EXPLOIT"
    assert p1["positive_control_partial_85pct"]["stopped_at_n"] <= 10

    lucky_trace = [1.0] + [-1.0] * 40
    verdict = run_sequential_hoeffding_sprt_gate("synthetic_lucky", lucky_trace, p_null_hit=1.0 / 40.0)
    assert verdict.verdict == "REFUTED_EARLY"
    assert verdict.stopped_at_n <= 12

    pvals_null = [0.25, 0.50, 0.90] + [1.0] * 20
    assert benjamini_hochberg_rejections(pvals_null, q_fdr=0.05) == []
    pvals_signal = [1e-9, 2e-9] + [1.0] * 100
    assert benjamini_hochberg_rejections(pvals_signal, q_fdr=0.05) == [0, 1]


def test_proposal_p17_2_error_envelope_parity_and_leak_detector() -> None:
    p2 = evaluate_proposal_p17_2_error_envelope_parity(seeds_per_tier=3)
    assert p2["tools_covered"] == 13
    assert p2["envelope_discrepancies_count"] == 0
    assert p2["error_vocab_violations"] == 0
    assert p2["mutual_information_error_envelope_vs_mole_nats"] == 0.0

    sig_clean_mole = _normalize_envelope_signature(False, "invalid arguments", {"detail": "bad topic for e04"}, "e04")
    sig_clean_inn = _normalize_envelope_signature(False, "invalid arguments", {"detail": "bad topic for e11"}, "e11")
    assert sig_clean_mole == sig_clean_inn

    sig_leaky_mole = _normalize_envelope_signature(False, "invalid arguments", {"detail": "mole e04 rejected"}, "e04")
    assert sig_leaky_mole != sig_clean_inn


def test_cli_json_and_doc_hygiene_and_verifier(tmp_path: Path) -> None:
    out_file = tmp_path / "audit_out.json"
    rc = main(["--seeds-per-tier", "2", "--out-json", str(out_file)])
    assert rc == 0
    payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert payload["passed"] is True

    for py_file in (SCRIPT_PATH, TEST_PATH):
        raw = py_file.read_text(encoding="utf-8")
        assert "\u2014" not in raw
        assert "\u2013" not in raw
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        assert all(tok.type != tokenize.COMMENT for tok in tokens)

    hyg = check_hygiene(ROOT, [DOC_PATH], extra_py_files=[SCRIPT_PATH, TEST_PATH])
    assert hyg.status == "PASS", hyg.details

    results, meta = verify_research_repo(
        root=ROOT,
        explicit_docs=[DOC_PATH],
        check_http=False,
        strict_http=False,
        base_ref="origin/justSilas",
    )
    assert all(r.status == "PASS" for r in results), [(r.name, r.status, r.details) for r in results]
    assert meta["unique_url_count"] >= 6
    assert meta["verbatim_quote_count"] >= 6
    assert "P17.1" in meta["proposal_ids"]
    assert "P17.2" in meta["proposal_ids"]
