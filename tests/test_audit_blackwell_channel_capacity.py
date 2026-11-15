from __future__ import annotations

import importlib.util
import io
import json
import math
import random
import sys
import tokenize
from dataclasses import replace
from pathlib import Path

import pytest

from canary import rules
from canary.env import Env
from canary.mole.dsl import MoleStrategy

ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "scripts" / "audit_blackwell_channel_capacity.py"
VERIFY_PATH = ROOT / "scripts" / "verify_research_deception.py"
DOC_PATH = ROOT / "docs" / "research" / "13_blackwell_channel_capacity_and_eig.md"
SELF_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"
CO_TAG = "co-" + "authored-" + "by:"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load_module("audit_blackwell_channel_capacity", AUDIT_PATH)
V = _load_module("verify_research_deception", VERIFY_PATH)


def test_strict_hygiene_and_monograph_verification():
    for py_path in (AUDIT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em-dash found in {py_path}"
        assert EN_DASH not in src, f"en-dash found in {py_path}"
        assert HASH_CH not in src, f"hash character found in {py_path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {py_path}"
        assert CO_TAG not in src.lower()
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"forbidden comment token in {py_path}: {comments}"

    doc_src = DOC_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in doc_src
    assert EN_DASH not in doc_src
    assert CO_TAG not in doc_src.lower()

    hygiene_res = V.check_hygiene(ROOT, [DOC_PATH], extra_py_files=[AUDIT_PATH, SELF_PATH])
    assert hygiene_res.status == "PASS", hygiene_res.details

    doc_results, doc_meta = V.verify_research_repo(
        root=ROOT,
        explicit_docs=[DOC_PATH],
        check_http=False,
        require_flagship=False,
    )
    assert all(r.status == "PASS" for r in doc_results), [r for r in doc_results if r.status != "PASS"]
    assert doc_meta["unique_url_count"] >= 20
    assert doc_meta["verbatim_quote_count"] >= 10
    assert {"P13.1", "P13.2"} <= set(doc_meta["proposal_ids"])


def test_exact_blackwell_garbling_and_channel_capacities():
    report = A.run_full_audit(eval_mole_seeds=0)
    part_a = report["part_a_blackwell_and_capacity"]
    assert part_a["tiers_version"] == "v1.4"
    assert part_a["v14_hash"] == "a8f99c2537c91d72"

    expected_fractions = {
        "easy": ("3/10", "1/5"),
        "medium": ("13/50", "1/5"),
        "hard": ("224/925", "184/925"),
    }
    for tier_name, (exp_ga, exp_gnon) in expected_fractions.items():
        bw = part_a["tiers"][tier_name]["blackwell"]
        assert bw["g_A_fraction"] == exp_ga
        assert bw["g_non_A_fraction"] == exp_gnon
        assert bw["max_reconstruction_error"] < 1e-15
        assert bw["is_row_stochastic_strict_interior"] is True
        assert bw["reverse_garbling_impossible"] is True
        assert bw["strict_blackwell_dominance"] is True
        assert len(bw["bayes_utility_checks"]) == 15
        for row in bw["bayes_utility_checks"]:
            assert row["eu_canary"] > row["eu_interview"]
            assert row["dominance_gap"] > 0.20
            if tier_name == "hard" and row["prior_A"] <= 0.34:
                assert row["eu_interview"] == 0.0

    hard = part_a["tiers"]["hard"]
    assert math.isclose(hard["prior_entropy_nats"], math.log(39.0), rel_tol=1e-12)
    assert math.isclose(hard["interview_kl_nats"], 0.004774269896, rel_tol=1e-6)
    assert math.isclose(hard["interview_shannon_capacity_nats"], 0.001166924243, rel_tol=1e-6)
    assert math.isclose(hard["interview_capacity_prior_q"], 0.49454832, rel_tol=1e-5)
    assert math.isclose(hard["interview_day1_eig_nats"], 0.000119134069, rel_tol=1e-5)
    assert math.isclose(hard["canary_mi_given_leak_nats"], 0.8654396863, rel_tol=1e-6)

    ratios = hard["conditional_interviews_per_leaked_canary"]
    assert math.isclose(ratios["kl_exact_ratio"], 181.27163, rel_tol=1e-4)
    assert math.isclose(ratios["kl_5dp_table_ratio"], 181.43396, rel_tol=1e-4)
    assert math.isclose(ratios["shannon_capacity_ratio"], 741.6417, rel_tol=1e-4)
    assert math.isclose(ratios["day1_prior_eig_ratio"], 7264.4181, rel_tol=1e-4)

    unc = hard["unconditional_canary_eig"]
    assert unc["day1_window_with_regular_docs"]["optimal_k_recipients"] == 17
    assert math.isclose(unc["day1_window_with_regular_docs"]["eig_nats"], 0.4176191, rel_tol=1e-5)
    assert unc["steady_window_with_regular_docs"]["optimal_k_recipients"] == 15
    assert math.isclose(unc["steady_window_with_regular_docs"]["eig_nats"], 0.1924727, rel_tol=1e-5)

    with pytest.raises(ValueError):
        A.exact_blackwell_garbling(0.2, 1.2, 0.25, 3)


def test_lindley_eig_blackwell_monotonicity_across_priors():
    params = rules.TIERS["hard"]
    rng = random.Random(20261115)
    for _ in range(25):
        weights = [rng.random() + 0.01 for _ in range(3)]
        tot = sum(weights)
        priors = [w / tot for w in weights]
        post = {"e00": priors[0], "e01": priors[1], "e02": priors[2]}
        asg = {"e00": "A", "e01": "B", "e02": "C"}
        p_leak_1 = replace(params, p_leak=1.0, careful_mole=False, leak_window_days=1)
        eig_can = A.exact_canary_eig_nats(post, asg, {}, p_leak_1, window_days=1, use_competition=False)
        eig_iv = A.interview_eig_nats(priors[0], params.p_evasive_innocent, params.interview_lr)
        assert eig_can > eig_iv + 1e-3


def test_v14_hard_replay_audit_and_shapley_decomposition():
    report = A.run_full_audit(eval_mole_seeds=0)
    pb = report["part_b_v14_hard_replay"]
    gem = pb["opencode_gemini_4_carbon"]
    sol = pb["solver_policy"]
    fa = pb["failure_analysis_cross_check"]
    dec = pb["eig_and_3_39V_decomposition"]

    assert gem["n_episodes"] == 30
    assert sol["n_episodes"] == 30
    assert gem["canaries_planted"] == 254
    assert gem["canaries_failed"] == 1
    assert sol["canaries_planted"] == 424
    assert sol["canaries_failed"] == 0
    assert gem["interviews_ok"] == 2039
    assert gem["interviews_total_calls"] == 2041
    assert sol["interviews_total_calls"] == 0
    assert fa["days_lt2_canaries"] == 303
    assert fa["days_lt2_full_budget"] == 242

    assert math.isclose(gem["canary_eig_3d_total_nats"], 67.591189, rel_tol=1e-5)
    assert math.isclose(sol["canary_eig_3d_total_nats"], 130.351240, rel_tol=1e-5)
    assert math.isclose(gem["interview_eig_total_nats"], 1.107724, rel_tol=1e-5)
    assert math.isclose(dec["per_action_eig_ratio_solver_over_gemini"], 4.561819, rel_tol=1e-5)

    gap_nats = dec["total_canary_eig_gap_30_seeds_nats"]
    sh = dec["shapley_midpoint"]
    ox = dec["oaxaca_solver_reference"]
    assert math.isclose(sh["slot_crowding_eig_nats"] + sh["per_canary_partition_eig_nats"], gap_nats, rel_tol=1e-12)
    assert math.isclose(ox["slot_crowding_eig_nats"] + ox["per_canary_partition_eig_nats"], gap_nats, rel_tol=1e-12)
    assert math.isclose(sh["slot_crowding_share"] + sh["per_canary_partition_share"], 1.0, rel_tol=1e-12)
    assert math.isclose(
        sh["attributed_slot_crowding_V"] + sh["attributed_per_canary_partition_V"],
        fa["commit_unisolated_gap_V"],
        rel_tol=1e-12,
    )
    assert math.isclose(sh["slot_crowding_share"], 0.776781, rel_tol=1e-4)
    assert math.isclose(sh["per_canary_partition_share"], 0.223219, rel_tol=1e-4)


def test_proposals_p13_zero_leakage_lint_and_mole_dsl():
    report = A.run_full_audit(eval_mole_seeds=0)
    pc = report["part_c_proposals"]
    p1 = pc["P13_1_binary_check_anchor"]
    assert p1["protected_paths_touched"] == 0
    assert p1["lint_messages_checked"] == 24
    assert p1["lint_failures"] == 0

    for row in p1["eig_degradation_by_suspect_pool"]:
        assert row["balanced_3way_eig_nats"] > row["asymmetric_1_vs_k_minus_1_binary_eig_nats"]
        assert row["asymmetric_1_vs_k_minus_1_binary_eig_nats"] > row["confirmatory_1person_k1_eig_nats"]
        assert 30.0 < row["asymmetric_binary_loss_pct"] < 50.0
        assert 55.0 < row["confirmatory_1person_loss_pct"] < 85.0

    env = Env("hard", 0)
    facts = env._facts(1)
    by_id = {e.id: e for e in facts.employees}
    non_decoy = [e.id for e in facts.employees if e.id != facts.decoy]
    ctx = A.BinaryAnchorContext(
        facts=facts,
        by_id=by_id,
        primary_suspect=non_decoy[0],
        secondary_suspect=non_decoy[1],
        authority_speakers=tuple(non_decoy[2:6]),
        peers=tuple(non_decoy),
        seen_docs={1: facts.docs},
    )
    msg_world_a = A.gen_binary_check_anchor(ctx, random.Random("zero-leak-seed"))
    msg_world_b = A.gen_binary_check_anchor(ctx, random.Random("zero-leak-seed"))
    assert msg_world_a == msg_world_b
    assert A.validate_social_lure_message(msg_world_a, by_id[msg_world_a["target"]], facts.decoy, set(by_id)) == []

    p2 = pc["P13_2_variable_canary_and_mole"]
    sched = {row["tier_option"]: row for row in p2["variable_tier_schedule"]}
    assert sched["binary_probe"]["early_m39_eig_per_0_01V"] > sched["standard_ternary_v14"]["early_m39_eig_per_0_01V"]
    assert sched["wide_pentanary"]["endgame_m5_eig_nats"] > sched["standard_ternary_v14"]["endgame_m5_eig_nats"]

    assert p2["mole_strategy"]["dsl_valid"] is True
    parsed = MoleStrategy.from_json(A.PARTITION_AWARE_SLEEPER_V14)
    assert parsed.name == "partition_aware_sleeper_v14"

    _, fences, _ = V._parse_markdown_fences(DOC_PATH.read_text(encoding="utf-8"))
    json_fences = [json.loads(f.content) for f in fences if f.lang.lower() == "json"]
    assert len(json_fences) == 1
    assert MoleStrategy.from_json(json_fences[0]).to_json() == parsed.to_json()

    live_smoke = A.audit_proposals_p13(eval_mole_seeds=2)["P13_2_variable_canary_and_mole"]["mole_strategy"]["live_eval"]
    assert live_smoke["n_seeds"] == 2
    assert 0.0 <= live_smoke["solver_acc"] <= 1.0


def test_cli_summary_and_json_modes(capsys):
    rc_sum = A.main([])
    out_sum = capsys.readouterr().out
    assert rc_sum == 0
    assert "224/925" in out_sum
    assert "77.7%" in out_sum

    rc_json = A.main(["--json"])
    out_json = capsys.readouterr().out
    assert rc_json == 0
    payload = json.loads(out_json)
    assert payload["part_a_blackwell_and_capacity"]["v14_hash"] == "a8f99c2537c91d72"
