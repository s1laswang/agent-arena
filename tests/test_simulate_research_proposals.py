from __future__ import annotations

import importlib.util
import io
import math
import random
import sys
import tokenize
from dataclasses import replace
from pathlib import Path

import pytest

from canary.env import Env
from canary.mole.dsl import MoleStrategy

ROOT = Path(__file__).resolve().parents[1]
SIM_PATH = ROOT / "scripts" / "simulate_research_proposals.py"
DOC_PATH = ROOT / "docs" / "research" / "10_proposal_simulations_and_zero_leakage_proofs.md"
VERIFY_PATH = ROOT / "scripts" / "verify_research_deception.py"
SELF_PATH = Path(__file__).resolve()
HASH_CH = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


SIM = _load_module("simulate_research_proposals", SIM_PATH)
VER = _load_module("verify_research_deception", VERIFY_PATH)


@pytest.fixture(scope="module")
def fast_payload() -> dict:
    return SIM.run_all_simulations(fast=True, workers=2)


def test_owned_python_files_hygiene_zero_comments_pure_ascii():
    for path in (SIM_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em-dash in {path}"
        assert EN_DASH not in src, f"en-dash in {path}"
        assert HASH_CH not in src, f"raw hash character in {path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII character in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"Python comment token in {path}: {comments}"


def test_frozen_v14_hash_and_channel_hierarchy(fast_payload: dict):
    ch = fast_payload["channel_hierarchy"]
    assert ch["tiers_version"] == "v1.4"
    assert ch["known_v_mode"] is True
    assert ch["v14_hash"] == "a8f99c2537c91d72"
    assert ch["v13_hash"] == "8df71cf570bb48bc"

    iv = ch["interview_by_tier"]
    assert iv["easy"]["kl_nats_5dp"] == pytest.approx(0.02817, abs=1e-5)
    assert iv["medium"]["kl_nats_5dp"] == pytest.approx(0.01052, abs=1e-5)
    assert iv["hard"]["kl_nats_5dp"] == pytest.approx(0.00477, abs=1e-5)
    assert iv["hard"]["binary_d_3dp"] == pytest.approx(0.097, abs=1e-3)

    ah = ch["after_hours_hard"]
    assert ah["rate_mole"] == pytest.approx(0.30, abs=1e-6)
    assert ah["rate_decoy"] == pytest.approx(1.10, abs=1e-6)
    assert ah["total_events_per_day"] == pytest.approx(6.20, abs=1e-6)
    assert ah["ppv_pct"] == pytest.approx(4.8387, abs=1e-3)
    assert ah["ppv_ex_decoy_pct"] == pytest.approx(5.8824, abs=1e-3)
    assert ah["poisson_kl_joint_day_nats"] == pytest.approx(0.10989, abs=1e-4)

    pc = ch["plant_canary_hard"]
    assert pc["mi_nats_5dp"] == pytest.approx(0.86544, abs=1e-5)
    assert pc["llr_match_vs_flip_nats"] == pytest.approx(3.6376, abs=1e-4)
    assert pc["ratio_vs_interview_kl_5dp"] == pytest.approx(181.4, abs=0.2)
    assert pc["entropy_bound_leaked_traps"] == pytest.approx(4.233, abs=1e-3)

    cm = ch["careful_mole_day1"]
    assert cm["k_star"] == 20
    assert cm["hit_rate_k_star"] == pytest.approx(0.2564, abs=1e-4)
    assert cm["ratio_k_star_vs_k3"] == pytest.approx(3.6, abs=0.1)

    fa = ch["failure_analysis_v14"]
    assert fa["opencode_score"] == pytest.approx(0.322, abs=1e-3)
    assert fa["solver_score"] == pytest.approx(0.499, abs=1e-3)
    assert fa["raw_gap_v"] == pytest.approx(5.30, abs=1e-2)
    assert fa["luck_adjusted_gap_v"] == pytest.approx(4.19, abs=1e-2)
    assert fa["days_lt2_full"] == 242
    assert fa["days_lt2_canaries"] == 303


def test_zero_leakage_invariance_p71_and_v15_negative_control(fast_payload: dict):
    p71 = fast_payload["social_p71"]
    assert p71["secret_seed_invariance_pct"] == 100.0
    assert p71["public_facts_mole_absent_worlds"] == p71["n_worlds"]
    assert p71["exact_conditional_mi_nats"] == 0.0
    assert p71["exact_solver_social_loglik_nats"] == 0.0
    assert p71["forbidden_subject_prefix_hits"] == 0
    assert p71["non_decoy_vocab_hits"] == 0
    assert p71["snippet_salience_pct"] == 100.0

    neg = p71["v15_negative_control"]
    assert neg["uniform_peer_llr_nats"] == pytest.approx(-0.52103, abs=1e-5)
    assert neg["uniform_peer_mi_nats"] == pytest.approx(0.00239, abs=1e-5)
    assert neg["single_restricted_peer_llr_nats"] == pytest.approx(-3.32023, abs=1e-5)
    assert neg["restricted_peer_rate_ratio"] == pytest.approx(27.67, abs=1e-2)

    env = Env("hard", 0)
    facts = env._facts(1)
    assert not hasattr(facts, "mole")
    base_dig = SIM.public_episode_digest("v5_full9_cocktail", facts)
    base_pair = SIM._focal_pair_from_rng(facts, random.Random(f"p71:v5_full9_cocktail:{base_dig}:init"))
    base_msgs = SIM._render_p71_social_batch(facts, base_dig, base_pair[0], base_pair[1])

    for alt_seed in (1, 999999, int(facts.seed) ^ 0x7F7F7F7F):
        alt_facts = replace(facts, seed=alt_seed)
        alt_dig = SIM.public_episode_digest("v5_full9_cocktail", alt_facts)
        alt_pair = SIM._focal_pair_from_rng(alt_facts, random.Random(f"p71:v5_full9_cocktail:{alt_dig}:init"))
        alt_msgs = SIM._render_p71_social_batch(alt_facts, alt_dig, alt_pair[0], alt_pair[1])
        assert alt_dig == base_dig
        assert alt_pair == base_pair
        assert alt_msgs == base_msgs


def test_p41_p73_dynamic_pretext_survival_and_conditional_uniformity(fast_payload: dict):
    p41 = fast_payload["pretext_p41_p73"]
    d1 = p41["checkpoints"]["day_1"]
    d6 = p41["checkpoints"]["day_6"]
    d12 = p41["checkpoints"]["day_12"]

    assert d1["dynamic_survival_c_reg_pct"] == 100.0
    assert d6["static_survival_pct"] < 80.0
    assert d12["static_survival_pct"] < d6["static_survival_pct"]
    assert d6["dynamic_survival_c_reg_pct"] == 100.0
    assert d12["dynamic_survival_c_reg_pct"] == 100.0
    assert d6["dynamic_survival_p_d_pct"] == 100.0
    assert d12["dynamic_survival_p_d_pct"] == 100.0

    assert d6["focal_restricted_probe_static_in_p_d_pct"] == 0.0
    assert d12["focal_restricted_probe_static_in_p_d_pct"] == 0.0
    assert d6["focal_restricted_probe_dyn_in_p_d_pct"] == 100.0
    assert d12["focal_restricted_probe_dyn_in_p_d_pct"] == 100.0

    assert d6["exact_conditional_mi_nats"] == 0.0
    assert d12["exact_conditional_mi_nats"] == 0.0
    assert d6["exact_conditional_llr_nats"] == 0.0
    assert d12["exact_conditional_llr_nats"] == 0.0


def test_p11_sue_kl_and_p12_p72_othello_scrutiny_drift(fast_payload: dict):
    iv = fast_payload["interviews_p11_p12_p72"]
    p11 = iv["p11_sue"]
    assert p11["regimes"]["p11_ungrounded"]["kl_nats"] == pytest.approx(0.00031, abs=1e-5)
    assert p11["regimes"]["p11_sue_grounded"]["kl_nats"] == pytest.approx(0.06879, abs=1e-5)
    assert p11["sue_vs_ungrounded_kl_ratio"] == pytest.approx(222.8, abs=0.2)
    assert p11["sue_vs_v14_kl_ratio"] == pytest.approx(14.4, abs=0.2)
    assert p11["canary_vs_sue_mi_ratio"] == pytest.approx(12.6, abs=0.2)
    assert p11["sue_eligible_worlds_day6_pct"] >= 90.0
    assert p11["sue_eligible_worlds_day12_pct"] >= 90.0
    assert p11["anti_farming_repeat_invariance_ok"] is True

    p12 = iv["p12_p72_othello"]
    assert p12["mole_odds_ratio_num"] == 24
    assert p12["mole_odds_ratio_den"] == 19
    assert p12["mole_odds_ratio"] == pytest.approx(24.0 / 19.0, abs=1e-6)
    assert p12["solver_public_conditioned_bias_nats"] == 0.0

    by_state = {st["state"]: st for st in p12["states"]}
    calm = by_state["calm_unmentioned"]
    rf = by_state["restricted_focal"]
    assert calm["p_evasive_mole"] == pytest.approx(0.24, abs=1e-4)
    assert rf["p_evasive_innocent"] == pytest.approx(0.52, abs=1e-4)
    assert rf["p_evasive_innocent"] > calm["p_evasive_mole"]
    assert rf["naive_flat_lr_drift_innocent_4dp"] == pytest.approx(0.0702, abs=1e-4)
    assert p12["restricted_focal_10iv_false_drift_nats"] == pytest.approx(0.7019, abs=1e-3)
    assert rf["calibrated_drift_innocent_nats"] < 0.0
    for st in p12["states"]:
        assert st["solver_calibration_bias_nats"] == 0.0


def test_p51_sleeper_and_p82_proxy_catchability_gate(fast_payload: dict):
    parsed = MoleStrategy.from_json(SIM.SURVEILLANCE_SLEEPER_P51)
    assert parsed.name == "surveillance_sleeper_p51"

    mp = fast_payload["mole_p51_p82"]
    neg = mp["unconstrained_most_recipients_neg"]
    assert neg["feasible_at_85pct"] is False
    assert neg["solver_acc"] < 0.85

    for suite_key in ("core_3inv", "augmented_p82_4inv"):
        for strat_key in ("default_v0", "surveillance_sleeper_p51"):
            entry = mp[suite_key][strat_key]
            assert entry["feasible"] is True
            assert entry["solver_acc"] >= 0.85
            assert entry["solver_score"] >= 0.5 * entry["baseline_solver_score"] - 1e-9

    aug_def = mp["augmented_p82_4inv"]["default_v0"]
    aug_p51 = mp["augmented_p82_4inv"]["surveillance_sleeper_p51"]
    proxy_def = aug_def["per_investigator"]["interview_crowded_proxy"]
    proxy_p51 = aug_p51["per_investigator"]["interview_crowded_proxy"]
    assert proxy_p51["score"] < proxy_def["score"]
    assert proxy_p51["regret"] > proxy_def["regret"]
    assert aug_p51["mean_regret"] > aug_def["mean_regret"]
    assert mp["p82_proxy_telemetry"]["default_interviews_per_ep"] >= 40.0
    assert mp["p82_proxy_telemetry"]["p51_restricted_frames_vs_p82_proxy_total"] > 0

    report = SIM.format_human_report(fast_payload)
    assert EM_DASH not in report and EN_DASH not in report
    for marker in ("a8f99c2537c91d72", "P7.1", "P4.1 / P7.3", "P1.1", "P1.2 / P7.2", "P5.1", "P8.2"):
        assert marker in report
    assert math.isfinite(fast_payload["elapsed_s"])


def test_monograph_10_passes_strict_research_verifier():
    assert DOC_PATH.is_file()
    hyg = VER.check_hygiene(ROOT, [DOC_PATH], extra_py_files=[SIM_PATH, SELF_PATH])
    assert hyg.status == "PASS", hyg.details
    results, meta = VER.verify_research_repo(root=ROOT, explicit_docs=[DOC_PATH], check_http=False)
    for res in results:
        assert res.status == "PASS", f"{res.name}: {res.summary} -> {res.details}"
    assert meta["unique_url_count"] >= 16
    assert meta["verbatim_quote_count"] >= 8
    assert {"P1.1", "P1.2", "P4.1", "P5.1", "P7.1", "P7.2", "P7.3", "P8.2"} <= set(meta["proposal_ids"])
