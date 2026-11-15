from __future__ import annotations

import importlib.util
import io
import json
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "research" / "20_judge_qa_and_proposal_scorecard.md"
SCRIPT_PATH = ROOT / "scripts" / "audit_research_scorecard.py"
VERIFY_PATH = ROOT / "scripts" / "verify_research_deception.py"
SELF_PATH = Path(__file__).resolve()
HASH_CH = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"


def _load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load_mod("audit_research_scorecard", SCRIPT_PATH)
V = _load_mod("verify_research_deception_scorecard", VERIFY_PATH)


def test_pure_ascii_zero_comments_zero_hash_zero_dashes() -> None:
    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em-dash found in {py_path}"
        assert EN_DASH not in src, f"en-dash found in {py_path}"
        assert HASH_CH not in src, f"raw hash char found in {py_path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert all(tok.type != tokenize.COMMENT for tok in tokens), f"Python comment found in {py_path}"


def test_frozen_v14_hash_and_full_scorecard_audit_passes() -> None:
    from canary import rules

    assert rules.TIERS_VERSION == "v1.4"
    assert S.compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE) == S.EXPECTED_V14_HASH
    assert S.compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE) == S.EXPECTED_V13_HASH

    report = S.run_full_audit(root=ROOT)
    assert report["passed"] is True
    assert report["v14_frozen_hash"] == "a8f99c2537c91d72"
    assert report["elapsed_s"] < 15.0


def test_six_peer_review_questions_and_5f9b3297_sync() -> None:
    qa = S.audit_six_peer_review_questions(ROOT)

    q1 = qa["q1_mcp_gap_and_statistical_honesty"]
    assert q1["n_locked"] == 30
    assert q1["gemini_mcp_score"] == 0.322
    assert q1["solver_score"] == 0.499
    assert 64.5 <= q1["raw_ratio_pct"] <= 64.7
    assert 71.9 <= q1["luck_adjusted_ratio_pct"] <= 72.1
    assert q1["infra_excluded_total"] == 25
    assert q1["infra_excluded_by_reason"] == {
        "infra:cli_error_event": 13,
        "infra:empty_model_response": 6,
        "infra:provider_unavailable": 6,
    }
    assert q1["infra_excluded_unique_seeds"] == 11
    assert q1["alt_raw_ratio_pct"] < q1["raw_ratio_pct"]
    assert q1["pooled_ext_n32_score"] == 0.349

    q2 = qa["q2_harbor_rehearsal_and_cross_family"]
    assert q2["sync_5f9b3297_aa1c679e_verified"] is True
    assert q2["harbor_oracle_10_mean"] == 0.506
    assert q2["harbor_run_means"] == [0.472, 0.585, 0.626]
    assert q2["harbor_run_valid_ns"] == [10, 10, 9]
    assert q2["harbor_run_ratios_pct"] == [93.3, 115.6, 131.0]
    assert q2["harbor_valid_accusations_correct"] == 28
    assert q2["harbor_valid_accusations_total"] == 29
    assert q2["harbor_shell_trials_used"] == 20
    assert q2["harbor_shell_trials_inspected"] == 28
    assert q2["gpt55_n"] == 30
    assert q2["gpt55_score"] == 0.504
    assert q2["gpt55_accused_correct"] == 28
    assert q2["gpt55_accused_total"] == 28
    assert q2["gpt55_prose_non_accuse_seeds"] == [0, 17]

    q3 = qa["q3_causal_mechanism_and_meaningful_difficulty"]
    assert q3["canary_mi_hard_nats"] == 0.86544
    assert q3["interview_kl_hard_nats"] == 0.00477
    assert q3["canary_to_interview_ratio"] > 180.0
    assert q3["after_hours_ppv_pct"] == 4.84
    assert q3["days_lt2_full"] == 242
    assert q3["days_lt2_canaries"] == 303
    assert q3["unisolated_accusations"] == 9
    assert q3["below_breakeven_seeds"] == [5, 18, 23]
    assert q3["luck_adjusted_gap_v"] == 4.19
    assert q3["raw_gap_v"] == 5.30
    assert q3["identity_residual_v"] < 1e-12

    q4 = qa["q4_v15_gate_b_and_zero_leakage_mole_grounding"]
    assert q4["v15_gate_b_rumour_llr_nats"] == -0.52103
    assert q4["v16_babbling_social_llr_nats"] == 0.0
    assert q4["rl_mole_v1_unconstrained_acc_pct"] < q4["mole_catchability_floor_pct"]
    assert q4["rl_mole_v2_trap_gated_acc_pct_ws3"] >= 85.0
    assert q4["qwen3_1_7b_v100_acc_pct_800k"] >= 85.0

    q5 = qa["q5_reward_integrity_and_1034_redteam"]
    assert q5["wrong_accusation_score"] == -1.0
    assert q5["day1_uniform_ev_hard"] == -0.95
    assert q5["battery_all_blocked"] is True
    assert q5["battery_rows"] == 99
    assert q5["replay_consistent"] == 1051
    assert q5["replay_steps"] == 53889
    assert q5["replay_mismatches"] == 0
    assert q5["harbor_trials_consistent"] == 80
    assert q5["harbor_hmac_verified"] == 57
    assert q5["redteam_total_attempts"] == 1034
    assert q5["redteam_afterquery_final_attempts"] == 521
    assert q5["redteam_verified_exploits"] == 0
    assert q5["redteam_invariant_violations"] == 0
    assert q5["positive_controls_found"] == 16
    assert q5["positive_controls_planted"] == 16
    assert q5["hard_40_seed_random_p_gt_0"] < 1e-22

    q6 = qa["q6_small_model_tiebreaker_and_dagger_null"]
    assert q6["tiebreak_bar_met"] is False
    assert q6["readme_honest_disclosure_verified"] is True
    assert q6["trained_runs_above_base"] == 0
    assert q6["trained_runs_total"] == 7
    assert q6["v2_sft_4k"]["score"] == -0.457
    assert q6["v3_grpo_4k"]["score"] == -0.147
    assert q6["dagger_r1_8k_partial"]["score"] == -0.542


def test_proposal_p20_1_scorecard_trace_and_missing_anchor_guard(tmp_path: Path) -> None:
    p1 = S.evaluate_proposal_p20_1_scorecard_trace(ROOT)
    assert p1["touches_protected_paths"] is False
    assert p1["zero_protected_surfaces_all_clean"] is True
    assert p1["research_docs_count"] >= 13
    assert p1["corpus_unique_proposals_count"] >= 26
    assert p1["scorecard_doc_exists"] is True
    assert p1["scorecard_doc_unique_urls"] >= 7
    assert p1["scorecard_doc_verbatim_quotes"] >= 7
    assert p1["all_required_literature_anchors_present"] is True
    assert p1["all_traced_artifacts_exist"] is True
    assert p1["all_six_questions_verified"] is True
    assert "P20.1" in p1["scorecard_doc_proposals"]
    assert "P20.2" in p1["scorecard_doc_proposals"]

    incomplete_doc = tmp_path / "incomplete.md"
    incomplete_doc.write_text(
        f"{HASH_CH} Partial Doc\n\nOnly https://doi.org/10.1037/a0023589\n"
        '> "Substantive verbatim quote exceeding twenty characters."\n',
        encoding="utf-8",
    )
    p1_bad = S.evaluate_proposal_p20_1_scorecard_trace(ROOT, scorecard_doc_path=incomplete_doc)
    assert p1_bad["all_required_literature_anchors_present"] is False

    prefixes = S._load_protected_prefixes(ROOT)
    assert S._surface_touches_protected("canary/env.py", prefixes) is True
    assert S._surface_touches_protected("canary/solver/policy.py", prefixes) is True
    assert S._surface_touches_protected("canary/analysis/scorecard.py", prefixes) is False


def test_proposal_p20_2_multi_axis_composite_and_anti_goodhart() -> None:
    p2 = S.evaluate_proposal_p20_2_multi_axis_composite(ROOT)
    assert p2["v14_frozen_hash_preserved_when_disabled"] is True
    assert p2["anti_goodhart_ordering_holds"] is True
    assert p2["gemini_shell_offload_raw_lift_pp"] == 48.7
    assert p2["gemini_accusation_precision_lift_pp"] == 10.34

    by_id = {row["agent_id"]: row for row in p2["profiles"]}
    assert by_id["solver"]["composite_v16_score"] == 1.0
    assert by_id["do_nothing"]["composite_v16_score"] == 0.0
    assert by_id["guess_day1"]["composite_v16_score"] == 0.0
    assert (
        by_id["synthetic:shell_dependent_wrapper"]["composite_v16_score"]
        < by_id["opencode:google/gemini-4-carbon+harbor"]["composite_v16_score"]
        < by_id["opencode:openai/gpt-5.5"]["composite_v16_score"]
        < by_id["solver"]["composite_v16_score"]
    )
    assert (
        by_id["opencode:google/gemini-4-carbon (mcp-only)"]["composite_v16_score"]
        < by_id["opencode:google/gemini-4-carbon+harbor"]["composite_v16_score"]
    )
    assert by_id["opencode:openai/gpt-5.5"]["budget_efficiency_b_eff"] > 0.90
    assert by_id["opencode:google/gemini-4-carbon+harbor"]["budget_efficiency_b_eff"] < 0.35


def test_cli_json_and_verify_research_deception_integration(tmp_path: Path, capsys) -> None:
    out_json = tmp_path / "scorecard_report.json"
    rc = S.main(["--json", "--out-json", str(out_json)])
    captured = capsys.readouterr().out
    assert rc == 0
    parsed = json.loads(captured)
    assert parsed["passed"] is True
    assert json.loads(out_json.read_text(encoding="utf-8"))["passed"] is True

    hyg = V.check_hygiene(ROOT, [DOC_PATH], extra_py_files=[SCRIPT_PATH, SELF_PATH])
    assert hyg.status == "PASS", hyg.details

    results, meta = V.verify_research_repo(
        root=ROOT,
        explicit_docs=[DOC_PATH],
        check_http=False,
        strict_http=False,
        base_ref="origin/justSilas",
    )
    assert all(r.status == "PASS" for r in results), [(r.name, r.status, r.details) for r in results]
    assert meta["unique_url_count"] >= 7
    assert meta["verbatim_quote_count"] >= 7
    assert "P20.1" in meta["proposal_ids"]
    assert "P20.2" in meta["proposal_ids"]
