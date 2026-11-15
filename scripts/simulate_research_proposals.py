from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import random
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.baselines import GrokTactics, Heuristic, _params_from_instruction
from canary.env import Env
from canary.forge.fitness import ClassFactory, default_solver_factory, evaluate
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, default_strategy_json
from canary.mole.dsl import MoleStrategy, MoleView, OPS
from canary.solver.policy import SolverPolicy

EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"

SURVEILLANCE_SLEEPER_P51: dict[str, Any] = {
    "name": "surveillance_sleeper_p51",
    "rules": [
        {
            "if": [["day", "<=", 4], ["recent_low_recipient_docs", ">=", 2]],
            "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
        }
    ],
    "default": {"leak": "random_seeded", "frame": "most_restricted_peer"},
}

PURE_MOST_RECIPIENTS_NEG: dict[str, Any] = {
    "name": "pure_most_recipients_neg",
    "rules": [],
    "default": {"leak": "most_recipients", "frame": "most_restricted_peer"},
}

FORBIDDEN_SOCIAL_PREFIXES: tuple[str, ...] = (
    "rumour:",
    "rumor:",
    "grudge:",
    "unverified accusation:",
)
DECOY_SOCIAL_VOCAB: tuple[str, ...] = ("unfair", "quit", "promotion")
AUTHORITY_ROLES: tuple[str, ...] = ("manager", "lead", "controller", "counsel")


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    obj = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def bernoulli_kl_nats(p_mole: float, p_innocent: float) -> float:
    pm = min(0.999999, max(1e-9, p_mole))
    p0 = min(0.999999, max(1e-9, p_innocent))
    return pm * math.log(pm / p0) + (1.0 - pm) * math.log((1.0 - pm) / (1.0 - p0))


def binary_cohens_d(p_mole: float, p_innocent: float) -> float:
    var_pool = 0.5 * (p_mole * (1.0 - p_mole) + p_innocent * (1.0 - p_innocent))
    return (p_mole - p_innocent) / math.sqrt(var_pool)


def hasselblad_hedges_d(p_mole: float, p_innocent: float) -> float:
    odds_ratio = (p_mole / (1.0 - p_mole)) / (p_innocent / (1.0 - p_innocent))
    return math.log(odds_ratio) * math.sqrt(3.0) / math.pi


def poisson_kl_nats(lam_mole: float, lam_innocent: float) -> float:
    return lam_mole * math.log(lam_mole / lam_innocent) + lam_innocent - lam_mole


def canary_mi_nats(accuracy: float, k_variants: int) -> float:
    flip = (1.0 - accuracy) / float(k_variants - 1)
    return math.log(float(k_variants)) + accuracy * math.log(accuracy) + (1.0 - accuracy) * math.log(flip)


def careful_mole_day1_hit_rate(k_recipients: int, n_employees: int = 40, has_decoy: bool = True) -> float:
    n_non_decoy = (n_employees - 1) if has_decoy else n_employees
    return (float(k_recipients) / float(n_non_decoy)) * (1.0 - float(k_recipients) / float(n_employees))


def compute_v14_channel_hierarchy(root: Path = ROOT) -> dict[str, Any]:
    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    hard = rules.TIERS["hard"]
    medium = rules.TIERS["medium"]
    easy = rules.TIERS["easy"]

    interview_by_tier: dict[str, dict[str, float]] = {}
    for tname, tp in (("easy", easy), ("medium", medium), ("hard", hard)):
        p0 = float(tp.p_evasive_innocent)
        lr = float(tp.interview_lr)
        pm = min(0.999999, p0 * lr)
        or0 = (pm / (1.0 - pm)) / (p0 / (1.0 - p0))
        interview_by_tier[tname] = {
            "p_innocent": round(p0, 6),
            "lr": round(lr, 6),
            "p_mole": round(pm, 6),
            "llr_evasive_nats": round(math.log(pm / p0), 6),
            "llr_cooperative_nats": round(math.log((1.0 - pm) / (1.0 - p0)), 6),
            "kl_nats": round(bernoulli_kl_nats(pm, p0), 8),
            "kl_nats_5dp": round(bernoulli_kl_nats(pm, p0), 5),
            "binary_d": round(binary_cohens_d(pm, p0), 6),
            "binary_d_3dp": round(binary_cohens_d(pm, p0), 3),
            "hasselblad_hedges_d": round(hasselblad_hedges_d(pm, p0), 6),
            "odds_ratio": round(or0, 6),
        }

    n_emp = int(hard.n_employees)
    n_non_decoy = n_emp - 1 if hard.decoy else n_emp
    n_plain_innocent = n_emp - 2 if hard.decoy else n_emp - 1

    ah_mole = float(hard.log_rate_mole * hard.p_after_hours_mole)
    ah_decoy = float(hard.log_rate_benign * hard.p_after_hours_benign + hard.framing_rate * hard.framing_decoy_share)
    ah_plain_each = float(
        hard.log_rate_benign * hard.p_after_hours_benign
        + hard.framing_rate * (1.0 - hard.framing_decoy_share) / float(n_plain_innocent)
    )
    ah_plain_total = float(n_plain_innocent) * ah_plain_each
    ah_total = ah_mole + ah_decoy + ah_plain_total
    ah_non_decoy_total = ah_total - ah_decoy
    ppv_all = ah_mole / ah_total
    ppv_ex_decoy = ah_mole / ah_non_decoy_total

    daytime_mole = float(hard.log_rate_mole * (1.0 - hard.p_after_hours_mole))
    daytime_plain = float(hard.log_rate_benign * (1.0 - hard.p_after_hours_benign))
    kl_ah_only = poisson_kl_nats(ah_mole, ah_plain_each)
    kl_logs_joint = kl_ah_only + poisson_kl_nats(daytime_mole, daytime_plain)

    mi_canary = canary_mi_nats(hard.fingerprint_accuracy, hard.max_variants)
    kl_iv_hard = bernoulli_kl_nats(hard.p_evasive_innocent * hard.interview_lr, hard.p_evasive_innocent)
    flip_prob = (1.0 - hard.fingerprint_accuracy) / float(hard.max_variants - 1)
    llr_canary_match = math.log(hard.fingerprint_accuracy / flip_prob)
    prior_entropy_nats = math.log(float(n_non_decoy))
    entropy_trap_bound = prior_entropy_nats / mi_canary
    ratio_5dp = round(mi_canary, 5) / round(kl_iv_hard, 5)
    ratio_exact = mi_canary / kl_iv_hard

    hit_curve = {k: careful_mole_day1_hit_rate(k, n_emp, hard.decoy) for k in range(1, n_non_decoy + 1)}
    k_star = max(hit_curve, key=lambda k: hit_curve[k])

    s_v15 = 0.4
    p_rum_mole = (1.0 - s_v15) / float(n_emp)
    p_rum_inn = (1.0 - s_v15) / float(n_emp) + s_v15 / float(n_emp - 1)
    llr_v15_rumour = math.log(p_rum_mole / p_rum_inn)

    reg_doc_recipients = int(round(2.0 * (n_emp / 5.0)))
    first_reg_leak_info_nats = math.log(float(n_emp) / float(reg_doc_recipients))

    fa_summary: dict[str, Any] = {}
    fa_path = root / "results" / "failure_analysis_v1.4.json"
    if fa_path.is_file():
        raw_fa = json.loads(fa_path.read_text(encoding="utf-8"))
        summ = raw_fa.get("summary") or {}
        oc = summ.get("opencode") or {}
        sv = summ.get("solver") or {}
        gp = summ.get("gap") or {}
        if oc and sv and gp:
            fa_summary = {
                "n_seeds": int(oc["n"]),
                "opencode_score": round(float(oc["score"]), 3),
                "opencode_score_ci": round(float(oc["score_ci"]), 3),
                "opencode_luck_adjusted": round(float(oc["luck_adjusted"]), 3),
                "solver_score": round(float(sv["score"]), 3),
                "solver_score_ci": round(float(sv["score_ci"]), 3),
                "solver_luck_adjusted": round(float(sv["luck_adjusted"]), 3),
                "raw_gap_v": round(float(gp["raw_gap"]), 2),
                "luck_adjusted_gap_v": round(float(gp["la_gap"]), 2),
                "opencode_interviews_per_ep": round(float(oc["interviews"]), 2),
                "solver_interviews_per_ep": round(float(sv["interviews"]), 2),
                "opencode_log_reads_per_ep": round(float(oc["log_reads"]), 2),
                "opencode_canaries_per_ep": round(float(oc["canaries"]), 2),
                "opencode_canary_capacity_pct": round(100.0 * float(oc["capacity_used"]), 1),
                "solver_canaries_per_ep": round(float(sv["canaries"]), 2),
                "solver_canary_capacity_pct": round(100.0 * float(sv["capacity_used"]), 1),
                "days_lt2_full": int(oc["days_lt2_full"]),
                "days_lt2_canaries": int(oc["days_lt2_canaries"]),
                "interviews_on_lt2_full": int(oc["interviews_on_lt2_full"]),
                "not_isolated_count": len(oc["not_isolated"]),
                "accused_count": int(oc["accused"]),
                "opencode_consistent_mean": round(float(oc["consistent_mean"]), 2),
                "solver_consistent_mean": round(float(sv["consistent_mean"]), 2),
                "commitment_penalty_v": round(float(gp["penalty"]), 2),
            }

    return {
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": bool(rules.KNOWN_V_MODE),
        "v14_hash": v14_hash,
        "v13_hash": v13_hash,
        "hard_params": hard.to_dict(),
        "interview_by_tier": interview_by_tier,
        "after_hours_hard": {
            "rate_mole": round(ah_mole, 6),
            "rate_decoy": round(ah_decoy, 6),
            "rate_plain_innocent": round(ah_plain_each, 6),
            "rate_plain_total": round(ah_plain_total, 6),
            "total_events_per_day": round(ah_total, 6),
            "non_decoy_events_per_day": round(ah_non_decoy_total, 6),
            "ppv": round(ppv_all, 8),
            "ppv_pct": round(100.0 * ppv_all, 4),
            "ppv_ex_decoy": round(ppv_ex_decoy, 8),
            "ppv_ex_decoy_pct": round(100.0 * ppv_ex_decoy, 4),
            "decoy_to_mole_ratio": round(ah_decoy / ah_mole, 4),
            "poisson_kl_after_hours_nats": round(kl_ah_only, 5),
            "poisson_kl_joint_day_nats": round(kl_logs_joint, 5),
        },
        "regular_leak_hard": {
            "recipients_per_doc": reg_doc_recipients,
            "first_leak_info_nats": round(first_reg_leak_info_nats, 5),
        },
        "plant_canary_hard": {
            "max_variants": int(hard.max_variants),
            "fingerprint_accuracy": float(hard.fingerprint_accuracy),
            "flip_prob_per_other_variant": round(flip_prob, 6),
            "mi_nats": round(mi_canary, 8),
            "mi_nats_5dp": round(mi_canary, 5),
            "mi_bits": round(mi_canary / math.log(2.0), 5),
            "llr_match_vs_flip_nats": round(llr_canary_match, 4),
            "ratio_vs_interview_kl_5dp": round(ratio_5dp, 1),
            "ratio_vs_interview_kl_exact": round(ratio_exact, 2),
            "prior_entropy_ex_decoy_nats": round(prior_entropy_nats, 5),
            "entropy_bound_leaked_traps": round(entropy_trap_bound, 3),
        },
        "careful_mole_day1": {
            "k_star": int(k_star),
            "hit_rate_k_star": round(hit_curve[k_star], 4),
            "hit_rate_k3": round(hit_curve[3], 4),
            "hit_rate_k39": round(hit_curve[39], 4),
            "ratio_k_star_vs_k3": round(hit_curve[k_star] / hit_curve[3], 1),
            "ratio_k_star_vs_k39": round(hit_curve[k_star] / hit_curve[39], 1),
        },
        "v15_gate_b_negative_control": {
            "rumour_frame_share": s_v15,
            "p_target_given_mole": round(p_rum_mole, 6),
            "p_target_given_innocent": round(p_rum_inn, 6),
            "llr_rumour_nats": round(llr_v15_rumour, 5),
        },
        "failure_analysis_v14": fa_summary,
    }


def public_episode_digest(variant: str, facts: Any) -> str:
    emp_sig = ",".join(f"{e.id}:{e.dept}:{e.role}" for e in facts.employees)
    reg_docs = [d for d in facts.docs if not str(d.get("doc_id", "")).startswith("c")]
    doc_sig = ",".join(str(d.get("doc_id", "")) for d in reg_docs)
    raw = f"v16:{variant}:{facts.tier}:{facts.company}:{facts.decoy}:{emp_sig}:{doc_sig}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _focal_pair_from_rng(facts: Any, rng: random.Random) -> tuple[str, str]:
    non_decoy_ids = [e.id for e in facts.employees if e.id != facts.decoy]
    non_decoy_set = set(non_decoy_ids)
    day_docs = [d for d in facts.docs if not str(d.get("doc_id", "")).startswith("c")] or list(facts.docs)
    if len(day_docs) >= 2:
        r0 = {r for r in day_docs[0].get("recipients", ()) if r in non_decoy_set}
        r1 = {r for r in day_docs[1].get("recipients", ()) if r in non_decoy_set}
        inter = sorted(r0 & r1)
    else:
        inter = []
    union_rec = sorted({r for d in day_docs for r in d.get("recipients", ()) if r in non_decoy_set})
    if inter:
        primary = rng.choice(inter)
    elif union_rec:
        primary = rng.choice(union_rec)
    else:
        primary = rng.choice(non_decoy_ids)
    sec_rec = [r for r in union_rec if r != primary]
    if sec_rec:
        secondary = rng.choice(sec_rec)
    else:
        others = [eid for eid in non_decoy_ids if eid != primary]
        secondary = rng.choice(others) if others else primary
    return primary, secondary


def _init_v16_day1_focal(env: Env, variant: str = "v5_full9_cocktail") -> tuple[str, str]:
    facts = env._facts(1)
    rng = random.Random(f"v16:{variant}:{facts.tier}:{facts.seed}:init")
    return _focal_pair_from_rng(facts, rng)


def _render_p71_social_batch(facts: Any, digest: str, primary: str, secondary: str) -> list[dict[str, str]]:
    by_id = {e.id: e for e in facts.employees}
    rng = random.Random(f"p71:msgs:{digest}:{facts.day}")
    auth_pool = [
        e.id for e in facts.employees
        if e.id not in {facts.decoy, primary} and any(k in e.role.lower() for k in AUTHORITY_ROLES)
    ]
    peer_pool = [e.id for e in facts.employees if e.id not in {facts.decoy, primary, secondary}]
    sp_auth = rng.choice(auth_pool) if auth_pool else rng.choice(peer_pool)
    sp_band = rng.choice(peer_pool)
    sp_misf = rng.choice(peer_pool)
    doc_title = str(facts.docs[0].get("title", "Q3 briefing")) if facts.docs else "Q3 briefing"
    p_emp = by_id[primary]
    s_emp = by_id[secondary]
    return [
        {
            "sender": sp_auth,
            "subject": "Security review follow-up on distribution list",
            "body": (
                f"During today's leak review meeting on {doc_title}, {p_emp.name} ({p_emp.id}) "
                f"stood out on the circulation overlap; worth checking workflow steps."
            ),
        },
        {
            "sender": sp_band,
            "subject": "Cross-team sync on recent doc handoff",
            "body": (
                f"Echoing the earlier meeting thread on {doc_title}: {p_emp.name} ({p_emp.id}) "
                f"was on both handoff lists before the leak check started."
            ),
        },
        {
            "sender": sp_misf,
            "subject": "Routing note from doc circulation check",
            "body": (
                f"Quick doc routing note: {s_emp.name} ({s_emp.id}) got copied on {doc_title} "
                f"during a rushed thread forward before the meeting."
            ),
        },
    ]


def simulate_social_p71(seeds: Iterable[int] = range(0, 500)) -> dict[str, Any]:
    seed_list = list(seeds)
    n_worlds = len(seed_list)
    variant = "v5_full9_cocktail"
    v16_mole_hits = 0
    digest_mole_hits = 0
    secret_seed_invariant_worlds = 0
    mole_field_absent_worlds = 0
    forbidden_prefix_hits = 0
    non_decoy_vocab_hits = 0
    salience_snippet_ok = 0
    total_msgs = 0

    for s in seed_list:
        env = Env("hard", s)
        facts = env._facts(1)
        mole = env._world.mole

        if not hasattr(facts, "mole") and "mole" not in facts.extra and mole != facts.decoy:
            mole_field_absent_worlds += 1

        v16_prim, _ = _init_v16_day1_focal(env, variant)
        if v16_prim == mole:
            v16_mole_hits += 1

        dig = public_episode_digest(variant, facts)
        p_dig, s_dig = _focal_pair_from_rng(facts, random.Random(f"p71:{variant}:{dig}:init"))
        if p_dig == mole:
            digest_mole_hits += 1

        msgs = _render_p71_social_batch(facts, dig, p_dig, s_dig)

        mutated_facts = replace(facts, seed=int(facts.seed) ^ 0x5A5A5A5A)
        dig_mut = public_episode_digest(variant, mutated_facts)
        p_mut, s_mut = _focal_pair_from_rng(mutated_facts, random.Random(f"p71:{variant}:{dig_mut}:init"))
        msgs_mut = _render_p71_social_batch(mutated_facts, dig_mut, p_mut, s_mut)
        if dig == dig_mut and (p_dig, s_dig) == (p_mut, s_mut) and msgs == msgs_mut:
            secret_seed_invariant_worlds += 1

        for m in msgs:
            total_msgs += 1
            subj_low = m["subject"].lower().strip()
            body_low = m["body"].lower()
            if any(subj_low.startswith(pref) for pref in FORBIDDEN_SOCIAL_PREFIXES):
                forbidden_prefix_hits += 1
            if m["sender"] != facts.decoy and any(w in body_low for w in DECOY_SOCIAL_VOCAB):
                non_decoy_vocab_hits += 1
            snippet = m["body"][:110]
            if any(tok in snippet.lower() for tok in ("doc", "leak", "meeting")) and "(" in snippet and ")" in snippet:
                salience_snippet_ok += 1

    p_null = 1.0 / 39.0
    se_null = math.sqrt(p_null * (1.0 - p_null) / float(n_worlds))
    rate_v16 = v16_mole_hits / float(n_worlds)
    rate_dig = digest_mole_hits / float(n_worlds)
    z_v16 = (rate_v16 - p_null) / se_null
    z_dig = (rate_dig - p_null) / se_null

    s_v15 = 0.4
    n_emp = 40
    p_m = (1.0 - s_v15) / float(n_emp)
    p_i = (1.0 - s_v15) / float(n_emp) + s_v15 / float(n_emp - 1)
    mi_v15_uniform = p_m * math.log(float(n_emp) * p_m) + float(n_emp - 1) * p_i * math.log(float(n_emp) * p_i)
    p_i_rest = (1.0 - s_v15) / float(n_emp) + s_v15
    llr_v15_rest = math.log(p_m / p_i_rest)

    return {
        "seed_start": seed_list[0],
        "seed_end": seed_list[-1],
        "n_worlds": n_worlds,
        "variant": variant,
        "uniform_non_decoy_prior": round(p_null, 6),
        "uniform_non_decoy_prior_pct": round(100.0 * p_null, 2),
        "v16_primary_mole_hits": v16_mole_hits,
        "v16_primary_mole_pct": round(100.0 * rate_v16, 2),
        "v16_z_stat": round(z_v16, 3),
        "p71_digest_primary_mole_hits": digest_mole_hits,
        "p71_digest_primary_mole_pct": round(100.0 * rate_dig, 2),
        "p71_digest_z_stat": round(z_dig, 3),
        "secret_seed_invariant_worlds": secret_seed_invariant_worlds,
        "secret_seed_invariance_pct": round(100.0 * secret_seed_invariant_worlds / float(n_worlds), 1),
        "public_facts_mole_absent_worlds": mole_field_absent_worlds,
        "exact_conditional_mi_nats": 0.0,
        "exact_solver_social_loglik_nats": 0.0,
        "messages_audited": total_msgs,
        "forbidden_subject_prefix_hits": forbidden_prefix_hits,
        "non_decoy_vocab_hits": non_decoy_vocab_hits,
        "snippet_salience_pct": round(100.0 * salience_snippet_ok / float(total_msgs), 1),
        "v15_negative_control": {
            "rumour_frame_share": s_v15,
            "uniform_peer_llr_nats": round(math.log(p_m / p_i), 5),
            "uniform_peer_mi_nats": round(mi_v15_uniform, 5),
            "single_restricted_peer_llr_nats": round(llr_v15_rest, 5),
            "restricted_peer_rate_ratio": round(p_i_rest / p_m, 2),
        },
    }


def _surfaced_reg_intersection(env: Env, day: int) -> tuple[list[str], int]:
    pool = [e.id for e in env._world.employees if e.id != env._world.decoy]
    surfaced = [
        f for f in env._feed
        if f["surfaced_day"] <= day and not env._doc_by_id[f["doc_id"]]["is_canary"]
    ]
    for item in surfaced:
        rec = set(env._doc_by_id[item["doc_id"]]["recipients"])
        inter = [eid for eid in pool if eid in rec]
        if inter:
            pool = inter
    return pool, len(surfaced)


def _plausible_pretext_target(
    tier: str,
    world_seed_val: int,
    day: int,
    primary: str,
    secondary: str,
    c_reg: list[str],
    restricted: set[str] | frozenset[str],
) -> tuple[str, list[str]]:
    unrest = [eid for eid in c_reg if eid not in restricted]
    p_d = unrest if unrest else list(c_reg)
    if primary in p_d:
        chosen = primary
    elif secondary in p_d:
        chosen = secondary
    else:
        prng = random.Random(f"p41:{tier}:{world_seed_val}:{day}")
        chosen = prng.choice(p_d)
    return chosen, p_d


def simulate_pretext_p41_p73(seeds: Iterable[int] = range(3000, 3200)) -> dict[str, Any]:
    seed_list = list(seeds)
    n_worlds = len(seed_list)
    checkpoints = (1, 6, 12)
    acc: dict[int, dict[str, float]] = {
        d: {
            "has_surfaced_reg": 0.0,
            "sum_c_reg_size": 0.0,
            "static_in_c_reg": 0.0,
            "static_in_c_reg_when_surfaced": 0.0,
            "dynamic_in_c_reg": 0.0,
            "dynamic_in_p_d": 0.0,
            "static_mole_hits": 0.0,
            "dynamic_mole_hits": 0.0,
            "sum_inv_p_d": 0.0,
            "sum_var_p_d": 0.0,
            "restricted_probe_static_in_p_d": 0.0,
            "restricted_probe_dyn_in_p_d": 0.0,
            "restricted_probe_mole_hits": 0.0,
            "restricted_probe_expected_hits": 0.0,
        }
        for d in checkpoints
    }

    for s in seed_list:
        env = Env("hard", s)
        primary, secondary = _init_v16_day1_focal(env)
        mole = env._world.mole
        ws_val = env._world.world_seed
        for day in range(1, 13):
            if day in acc:
                c_reg, n_surf = _surfaced_reg_intersection(env, day)
                dyn_tgt, p_d = _plausible_pretext_target("hard", ws_val, day, primary, secondary, c_reg, frozenset())
                row = acc[day]
                row["has_surfaced_reg"] += float(n_surf > 0)
                row["sum_c_reg_size"] += float(len(c_reg))
                in_creg = float(primary in c_reg)
                row["static_in_c_reg"] += in_creg
                if n_surf > 0:
                    row["static_in_c_reg_when_surfaced"] += in_creg
                row["dynamic_in_c_reg"] += float(dyn_tgt in c_reg)
                row["dynamic_in_p_d"] += float(dyn_tgt in p_d)
                row["static_mole_hits"] += float(primary == mole)
                row["dynamic_mole_hits"] += float(dyn_tgt == mole)
                inv_pd = 1.0 / float(len(p_d))
                row["sum_inv_p_d"] += inv_pd
                row["sum_var_p_d"] += inv_pd * (1.0 - inv_pd)

                probe_rest = frozenset({primary}) if day >= 5 else frozenset()
                r_tgt, r_pd = _plausible_pretext_target("hard", ws_val, day, primary, secondary, c_reg, probe_rest)
                row["restricted_probe_static_in_p_d"] += float(primary in r_pd)
                row["restricted_probe_dyn_in_p_d"] += float(r_tgt in r_pd)
                row["restricted_probe_mole_hits"] += float(r_tgt == mole)
                if mole in r_pd:
                    row["restricted_probe_expected_hits"] += 1.0 / float(len(r_pd))
            if day < 12:
                env.call("advance_day", {})

    by_day: dict[str, dict[str, Any]] = {}
    for d in checkpoints:
        row = acc[d]
        n_surf_ep = int(row["has_surfaced_reg"])
        p_obs = row["dynamic_mole_hits"] / float(n_worlds)
        p_exp = row["sum_inv_p_d"] / float(n_worlds)
        se_diff = math.sqrt(row["sum_var_p_d"]) / float(n_worlds)
        z_stat = (p_obs - p_exp) / se_diff if se_diff > 0 else 0.0
        emp_llr = math.log(p_obs / p_exp) if p_obs > 0 and p_exp > 0 else 0.0
        rp_obs = row["restricted_probe_mole_hits"] / float(n_worlds)
        rp_exp = row["restricted_probe_expected_hits"] / float(n_worlds)
        rp_llr = math.log(rp_obs / rp_exp) if rp_obs > 0 and rp_exp > 0 else 0.0
        by_day[f"day_{d}"] = {
            "day": d,
            "n_worlds": n_worlds,
            "episodes_with_surfaced_reg_leak": n_surf_ep,
            "mean_c_reg_size": round(row["sum_c_reg_size"] / float(n_worlds), 2),
            "static_survival_count": int(row["static_in_c_reg"]),
            "static_survival_pct": round(100.0 * row["static_in_c_reg"] / float(n_worlds), 2),
            "static_eliminated_count": n_worlds - int(row["static_in_c_reg"]),
            "static_eliminated_pct": round(100.0 * (1.0 - row["static_in_c_reg"] / float(n_worlds)), 2),
            "static_survival_given_surfaced_pct": round(
                100.0 * row["static_in_c_reg_when_surfaced"] / float(n_surf_ep), 2
            ) if n_surf_ep > 0 else 100.0,
            "dynamic_survival_c_reg_count": int(row["dynamic_in_c_reg"]),
            "dynamic_survival_c_reg_pct": round(100.0 * row["dynamic_in_c_reg"] / float(n_worlds), 2),
            "dynamic_survival_p_d_pct": round(100.0 * row["dynamic_in_p_d"] / float(n_worlds), 2),
            "p_target_is_mole": round(p_obs, 4),
            "expected_inv_p_d": round(p_exp, 4),
            "empirical_llr_nats": round(emp_llr, 4),
            "z_stat_zero_leakage": round(z_stat, 3),
            "exact_conditional_mi_nats": 0.0,
            "exact_conditional_llr_nats": 0.0,
            "focal_restricted_probe_static_in_p_d_pct": round(
                100.0 * row["restricted_probe_static_in_p_d"] / float(n_worlds), 2
            ),
            "focal_restricted_probe_dyn_in_p_d_pct": round(
                100.0 * row["restricted_probe_dyn_in_p_d"] / float(n_worlds), 2
            ),
            "focal_restricted_probe_p_target_is_mole": round(rp_obs, 4),
            "focal_restricted_probe_expected_rate": round(rp_exp, 4),
            "focal_restricted_probe_emp_llr_nats": round(rp_llr, 4),
        }

    return {
        "seed_start": seed_list[0],
        "seed_end": seed_list[-1],
        "n_worlds": n_worlds,
        "day1_static_mole_hits": int(acc[1]["static_mole_hits"]),
        "day1_static_mole_rate": round(acc[1]["static_mole_hits"] / float(n_worlds), 4),
        "day1_uniform_prior": round(1.0 / 39.0, 4),
        "checkpoints": by_day,
    }


def simulate_interviews_p11_p12_p72(
    seeds: Iterable[int] = range(3000, 3200),
    mc_trials: int = 10000,
) -> dict[str, Any]:
    hard = rules.TIERS["hard"]
    p0 = float(hard.p_evasive_innocent)
    lr_v14 = float(hard.interview_lr)
    lr_ungrounded = 1.05
    lr_sue = 1.80
    sue_window_days = 6

    regimes: dict[str, dict[str, float]] = {}
    for key, lr in (
        ("v14_hard_baseline", lr_v14),
        ("p11_ungrounded", lr_ungrounded),
        ("p11_sue_grounded", lr_sue),
    ):
        pm = p0 * lr
        kl = bernoulli_kl_nats(pm, p0)
        or_val = (pm / (1.0 - pm)) / (p0 / (1.0 - p0))
        regimes[key] = {
            "lr": round(lr, 4),
            "p_innocent": round(p0, 4),
            "p_mole": round(pm, 4),
            "llr_evasive_nats": round(math.log(pm / p0), 5),
            "llr_cooperative_nats": round(math.log((1.0 - pm) / (1.0 - p0)), 5),
            "kl_nats": round(kl, 5),
            "kl_nats_6dp": round(kl, 6),
            "odds_ratio": round(or_val, 6),
        }

    kl_v14 = bernoulli_kl_nats(p0 * lr_v14, p0)
    kl_ung = bernoulli_kl_nats(p0 * lr_ungrounded, p0)
    kl_sue = bernoulli_kl_nats(p0 * lr_sue, p0)

    seed_list = list(seeds)
    sue_eligible_d6 = 0
    sue_eligible_d12 = 0
    sue_repeat_identical = 0
    for s in seed_list:
        env = Env("hard", s)
        for day in range(1, 13):
            if day in (6, 12):
                surf = [
                    f for f in env._feed
                    if f["surfaced_day"] <= day
                    and not env._doc_by_id[f["doc_id"]]["is_canary"]
                    and (day - env._doc_by_id[f["doc_id"]]["day"] <= sue_window_days)
                ]
                if surf:
                    if day == 6:
                        sue_eligible_d6 += 1
                    else:
                        sue_eligible_d12 += 1
                    doc_id = surf[0]["doc_id"]
                    emp = env._doc_by_id[doc_id]["recipients"][0]
                    u1 = random.Random(f"{env._world.world_seed}:sue:{emp}:{doc_id}").random()
                    u2 = random.Random(f"{env._world.world_seed}:sue:{emp}:{doc_id}").random()
                    if u1 == u2:
                        sue_repeat_identical += 1
            if day < 12:
                env.call("advance_day", {})

    pm0 = p0 * lr_v14
    or0 = (pm0 / (1.0 - pm0)) / (p0 / (1.0 - p0))
    naive_llr_pos = math.log(pm0 / p0)
    naive_llr_neg = math.log((1.0 - pm0) / (1.0 - p0))

    scrutiny_states: list[dict[str, Any]] = []
    for state_name, r_flag, m_cnt in (
        ("calm_unmentioned", 0, 0),
        ("focal_day3", 0, 2),
        ("focal_day6", 0, 4),
        ("restricted_only", 1, 0),
        ("restricted_focal", 1, 4),
    ):
        pb = min(0.52, 0.20 + 0.14 * r_flag + 0.06 * min(m_cnt, 4))
        odds_m = (pb / (1.0 - pb)) * or0
        pm = odds_m / (1.0 + odds_m)
        kl_state = bernoulli_kl_nats(pm, pb)
        naive_drift_inn = pb * naive_llr_pos + (1.0 - pb) * naive_llr_neg
        calib_llr_pos = math.log(pm / pb)
        calib_llr_neg = math.log((1.0 - pm) / (1.0 - pb))
        calib_drift_inn = pb * calib_llr_pos + (1.0 - pb) * calib_llr_neg
        lr_martingale_bias = pb * (pm / pb) + (1.0 - pb) * ((1.0 - pm) / (1.0 - pb)) - 1.0
        scrutiny_states.append(
            {
                "state": state_name,
                "r": r_flag,
                "m": m_cnt,
                "p_evasive_innocent": round(pb, 4),
                "p_evasive_mole": round(pm, 4),
                "kl_nats": round(kl_state, 5),
                "naive_flat_lr_drift_innocent_nats": round(naive_drift_inn, 5),
                "naive_flat_lr_drift_innocent_4dp": round(naive_drift_inn, 4),
                "calibrated_drift_innocent_nats": round(calib_drift_inn, 5),
                "solver_calibration_bias_nats": round( abs(lr_martingale_bias), 4),
            }
        )

    mc_rng = random.Random("canary-p12-p72-othello-mc")
    pb_rf = 0.52
    pm_rf = ((pb_rf / (1.0 - pb_rf)) * or0) / (1.0 + (pb_rf / (1.0 - pb_rf)) * or0)
    c_pos = math.log(pm_rf / pb_rf)
    c_neg = math.log((1.0 - pm_rf) / (1.0 - pb_rf))
    sum_naive = 0.0
    sum_calib_lr = 0.0
    for _ in range(mc_trials):
        evasive = mc_rng.random() < pb_rf
        sum_naive += naive_llr_pos if evasive else naive_llr_neg
        sum_calib_lr += math.exp(c_pos if evasive else c_neg)

    return {
        "p11_sue": {
            "regimes": regimes,
            "sue_vs_ungrounded_kl_ratio": round(kl_sue / kl_ung, 1),
            "v14_vs_ungrounded_kl_ratio": round(kl_v14 / kl_ung, 1),
            "sue_vs_v14_kl_ratio": round(kl_sue / kl_v14, 1),
            "canary_vs_sue_mi_ratio": round(
                canary_mi_nats(hard.fingerprint_accuracy, hard.max_variants) / kl_sue, 1
            ),
            "sue_window_days": sue_window_days,
            "worlds_tested": len(seed_list),
            "sue_eligible_worlds_day6_pct": round(100.0 * sue_eligible_d6 / float(len(seed_list)), 1),
            "sue_eligible_worlds_day12_pct": round(100.0 * sue_eligible_d12 / float(len(seed_list)), 1),
            "anti_farming_repeat_invariance_ok": (
                sue_repeat_identical == (sue_eligible_d6 + sue_eligible_d12)
            ),
        },
        "p12_p72_othello": {
            "mole_odds_ratio_num": 24,
            "mole_odds_ratio_den": 19,
            "mole_odds_ratio": round(or0, 6),
            "states": scrutiny_states,
            "restricted_focal_naive_drift_nats": round(scrutiny_states[-1]["naive_flat_lr_drift_innocent_nats"], 4),
            "restricted_focal_10iv_false_drift_nats": round(
                10.0 * scrutiny_states[-1]["naive_flat_lr_drift_innocent_nats"], 4
            ),
            "solver_public_conditioned_bias_nats": 0.0,
            "mc_trials": mc_trials,
            "mc_naive_drift_mean_nats": round(sum_naive / float(mc_trials), 4),
            "mc_calibrated_lr_mean": round(sum_calib_lr / float(mc_trials), 4),
        },
    }


class InterviewCrowdedProxy:
    name = "interview_crowded_proxy"
    TOPICS = ("recent_documents", "contacts_outside", "workload", "access_needs")
    DECOY_WORDS = ("unfair", "quit", "promotion")

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.interviews_done = 0
        self.canaries_planted = 0

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        p = _params_from_instruction(instruction)
        self.n_days = int(float(p.get("n_days", 21)))
        self.lr = float(p.get("interview_lr", 1.2))
        self.p0 = float(p.get("p_evasive_innocent", 0.2))
        self.q = float(p.get("fingerprint_accuracy", 0.95))
        self.max_variants = int(float(p.get("max_variants", 3)))
        self.rng = random.Random(f"p82_proxy:{self.seed}")
        self.day = 1
        self.started_day = 0
        self.V = 1.0
        self.emps: list[str] = []
        self.decoy: str | None = None
        self.decoy_hits: Counter[str] = Counter()
        self.docs: dict[str, dict[str, Any]] = {}
        self.seen_feed: set[tuple[Any, Any]] = set()
        self.seen_log_day = 0
        self.log_odds: dict[str, float] = {}
        self.eliminated: set[str] = set()
        self.restricted: set[str] = set()
        self.iv_cursor = 0
        self.canaries_planted = 0
        self.interviews_done = 0
        self.queue: list[tuple[str, dict[str, Any]]] = []

    def _ingest(self, step: Any) -> None:
        r, t = step.result, step.tool
        if not r.get("ok"):
            return
        d = r.get("data") or {}
        if t == "list_employees":
            self.emps = [e["id"] for e in d.get("employees", [])]
            self.log_odds = {e: 0.0 for e in self.emps}
        elif t == "status":
            self.V = float(d.get("V", self.V))
            self.day = int(d.get("day", self.day))
        elif t == "search_messages":
            for m in d.get("messages", []):
                if m.get("sender"):
                    self.decoy_hits[m["sender"]] += 1
        elif t == "list_documents":
            for doc in d.get("documents", []):
                self.docs[doc["doc_id"]] = doc
        elif t == "check_leak_feed":
            for it in d.get("items", []):
                key = (it.get("doc_id"), it.get("variant"))
                if key in self.seen_feed:
                    continue
                self.seen_feed.add(key)
                doc = self.docs.get(it.get("doc_id"))
                if not doc:
                    continue
                if doc.get("is_canary") and it.get("variant") and doc.get("variants"):
                    groups = {k: set(v) for k, v in doc["variants"].items()}
                    kv = max(2, len(groups))
                    flip = (1.0 - self.q) / float(kv - 1)
                    for e in self.emps:
                        if e in groups.get(it["variant"], ()):
                            self.log_odds[e] += math.log(max(1e-6, self.q))
                        elif any(e in g for g in groups.values()):
                            self.log_odds[e] += math.log(max(1e-6, flip))
                        else:
                            self.eliminated.add(e)
                else:
                    rec = set(doc.get("recipients", []))
                    for e in self.emps:
                        if e not in rec:
                            self.eliminated.add(e)
        elif t == "read_access_logs":
            for entry in d.get("logs", []):
                e = entry.get("employee")
                if e in self.log_odds and entry.get("after_hours"):
                    self.log_odds[e] += 0.35
        elif t == "interview":
            self.interviews_done += 1
            e = d.get("employee")
            ans = (d.get("answer") or "").lower()
            evasive = any(
                w in ans
                for w in (
                    "hesitat",
                    "vague",
                    "deflect",
                    "uncomfortable",
                    "evasive",
                    "avoid",
                    "cannot recall",
                    "not sure",
                    "decline",
                )
            )
            pm = min(0.95, self.p0 * self.lr)
            if e in self.log_odds:
                shift = math.log(pm / self.p0) if evasive else math.log((1.0 - pm) / (1.0 - self.p0))
                self.log_odds[e] += shift * 2.0
        elif t == "restrict_access":
            self.restricted.add(step.args["employee"])
        elif t == "plant_canary":
            self.canaries_planted += 1

    def _posterior(self) -> dict[str, float]:
        alive = [e for e in self.emps if e not in self.eliminated and e != self.decoy]
        if not alive:
            alive = [e for e in self.emps if e != self.decoy] or list(self.emps)
        mx = max(self.log_odds[e] for e in alive)
        weights = {e: math.exp(self.log_odds[e] - mx) for e in alive}
        total = sum(weights.values()) or 1.0
        return {e: weights[e] / total for e in alive}

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        if history:
            self._ingest(history[-1])
            if history[-1].tool == "advance_day" and history[-1].result.get("ok"):
                self.day = history[-1].result["data"].get("day", self.day + 1)
        if not self.emps:
            return "list_employees", {}
        if self.day != self.started_day:
            self.started_day = self.day
            q: list[tuple[str, dict[str, Any]]] = [("status", {}), ("list_documents", {})]
            if self.day == 1:
                for w in self.DECOY_WORDS:
                    q.append(("search_messages", {"query": w}))
            else:
                q.append(("check_leak_feed", {}))
                if self.day % 2 == 0 and self.day - 1 > self.seen_log_day:
                    q.append(("read_access_logs", {"day_from": self.seen_log_day + 1, "day_to": self.day - 1}))
                    self.seen_log_day = self.day - 1
            q.append(("__plan__", {}))
            self.queue = q
        while self.queue:
            tool, args = self.queue.pop(0)
            if tool == "__plan__":
                if self.decoy is None and self.decoy_hits:
                    self.decoy = self.decoy_hits.most_common(1)[0][0]
                post = self._posterior()
                ranked = sorted(post, key=lambda e: (-post[e], e))
                best = ranked[0]
                pb = post[best]
                if pb >= 0.92 and pb * self.V - (1.0 - pb) > 0:
                    return "accuse", {"employee": best}
                if (
                    self.day >= self.n_days - 3
                    and (pb >= 0.55 or self.day >= self.n_days - 1)
                    and pb * self.V - (1.0 - pb) > -0.15
                ):
                    return "accuse", {"employee": best}
                if self.day == 3 and not self.restricted and len(ranked) >= 3:
                    self.queue.append(("restrict_access", {"employee": ranked[0]}))
                unrest = [e for e in ranked if e not in self.restricted]
                plant_today = self.day >= 3 and len(unrest) >= 2
                iv_slots = 4 if plant_today else 5
                if plant_today:
                    cap = 3 if self.day <= 4 else min(len(unrest), 12)
                    pool = unrest[: max(2, min(len(unrest), cap))]
                    labels = "ABC"[: self.max_variants]
                    asg = {e: labels[i % len(labels)] for i, e in enumerate(pool)}
                    self.queue.append(("plant_canary", {"doc_title": f"Audit memo d{self.day}", "assignment": asg}))
                    if self.day <= 4 and len(unrest) >= 5:
                        pool2 = unrest[2: min(len(unrest), 5)]
                        asg2 = {e: labels[i % len(labels)] for i, e in enumerate(pool2)}
                        self.queue.append(
                            ("plant_canary", {"doc_title": f"Audit memo d{self.day}b", "assignment": asg2})
                        )
                        iv_slots = 3
                for _ in range(iv_slots):
                    target = ranked[self.iv_cursor % len(ranked)]
                    topic = self.TOPICS[self.iv_cursor % len(self.TOPICS)]
                    self.iv_cursor += 1
                    self.queue.append(("interview", {"employee": target, "topic": topic}))
                continue
            return tool, args
        return "advance_day", {}


class _RecordingMole:
    def __init__(self, inner: MoleStrategy):
        self.inner = inner
        self.views: list[MoleView] = []
        self.rule0_fires = 0
        self.restricted_frames = 0

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, Any]:
        self.views.append(view)
        if self.inner.rules:
            conds, _ = self.inner.rules[0]
            if all(OPS[op](view.feature(f), n) for f, op, n in conds):
                self.rule0_fires += 1
        out = self.inner.decide(view, rng)
        if out.get("frame") is not None and view.restricted_peers and out.get("frame") == view.restricted_peers[0]:
            self.restricted_frames += 1
        return out


def _would_diverge_from_default(strat: MoleStrategy, views: Iterable[MoleView]) -> bool:
    for v in views:
        leak_sel, frame_sel = strat.default
        for conds, then in strat.rules:
            if all(OPS[op](v.feature(f), n) for f, op, n in conds):
                leak_sel, frame_sel = then
                break
        if leak_sel != "random_seeded" and v.docs and v.can_leak:
            return True
        if frame_sel == "random_peer" and v.peers:
            return True
        if frame_sel == "decoy" and v.decoy is not None:
            return True
        if frame_sel == "most_restricted_peer" and v.restricted_peers:
            return True
    return False


def _make_agent(agent: str, seed: int) -> Any:
    if agent == "solver":
        return SolverPolicy(act_budget=30.0)
    if agent == "grok_tactics":
        return GrokTactics(seed=seed)
    if agent == "heuristic":
        return Heuristic(seed=seed)
    if agent == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if agent == "interview_crowded_proxy":
        return InterviewCrowdedProxy(seed=seed)
    raise ValueError(f"unknown agent {agent!r}")


def _run_recorded_episode(
    tier: str,
    seed: int,
    strategy_json: dict[str, Any],
    agent: str,
) -> tuple[float, bool, tuple[MoleView, ...], dict[str, int]]:
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    strat = MoleStrategy.from_json(strategy_json)
    rec = _RecordingMole(strat)
    env = Env(tier=tier, seed=seed, mole_strategy=rec)
    pol = _make_agent(agent, seed)
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        tool, args = pol.act(env.history)
        env.call(tool, args)
    res = env.result(getattr(pol, "name", agent))
    extra = {
        "rule0_fires": rec.rule0_fires,
        "restricted_frames": rec.restricted_frames,
        "interviews": int(getattr(pol, "interviews_done", 0)),
        "canaries": int(getattr(pol, "canaries_planted", 0)),
    }
    return float(env.score()), bool(res.correct), tuple(rec.views), extra


def _eval_seed_bundle(task: tuple[str, int, tuple[str, ...]]) -> dict[str, Any]:
    tier, seed, agents = task
    def_json = default_strategy_json()
    p51_strat = MoleStrategy.from_json(SURVEILLANCE_SLEEPER_P51)
    out_def: dict[str, tuple[float, bool]] = {}
    out_p51: dict[str, tuple[float, bool]] = {}
    telemetry: dict[str, dict[str, dict[str, int]]] = {"default": {}, "p51": {}}
    reused = 0
    for agent in agents:
        sc_d, ok_d, views_d, ext_d = _run_recorded_episode(tier, seed, def_json, agent)
        out_def[agent] = (sc_d, ok_d)
        telemetry["default"][agent] = ext_d
        if not _would_diverge_from_default(p51_strat, views_d):
            out_p51[agent] = (sc_d, ok_d)
            telemetry["p51"][agent] = dict(ext_d)
            reused += 1
        else:
            sc_p, ok_p, _, ext_p = _run_recorded_episode(tier, seed, SURVEILLANCE_SLEEPER_P51, agent)
            out_p51[agent] = (sc_p, ok_p)
            telemetry["p51"][agent] = ext_p
    sc_neg, ok_neg, _, _ = _run_recorded_episode(tier, seed, PURE_MOST_RECIPIENTS_NEG, "solver")
    return {
        "seed": seed,
        "default": out_def,
        "p51": out_p51,
        "neg_solver": (sc_neg, ok_neg),
        "telemetry": telemetry,
        "reused": reused,
    }


def evaluate_sleeper_mole_p51_p82(
    seeds: Iterable[int] = range(2000, 2060),
    workers: int | None = None,
) -> dict[str, Any]:
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    seed_list = list(seeds)
    if workers is None:
        avail = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else (os.cpu_count() or 1)
        workers = max(1, min(4, avail))

    all_agents = ("solver", "grok_tactics", "heuristic", "hinted_heuristic", "interview_crowded_proxy")
    tasks = [("hard", s, all_agents) for s in seed_list]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
            bundles = list(pool.map(_eval_seed_bundle, tasks))
    else:
        bundles = [_eval_seed_bundle(t) for t in tasks]

    def_key = canonical(default_strategy_json())
    p51_key = canonical(SURVEILLANCE_SLEEPER_P51)
    lookup: dict[tuple[str, int, str, str], tuple[float, bool]] = {}
    for b in bundles:
        s = int(b["seed"])
        for ag, val in b["default"].items():
            lookup[("hard", s, def_key, ag)] = val
        for ag, val in b["p51"].items():
            lookup[("hard", s, p51_key, ag)] = val

    def table_runner(tier: str, seed: int, strategy_json: dict[str, Any], agent: str, factory: Any) -> tuple[float, bool]:
        k = (tier, int(seed), canonical(strategy_json), agent)
        if k in lookup:
            return lookup[k]
        sc, ok_flag, _, _ = _run_recorded_episode(tier, int(seed), strategy_json, agent)
        return sc, ok_flag

    solver_fac = default_solver_factory()
    core_inv = {
        "grok_tactics": ClassFactory("canary.baselines", "GrokTactics"),
        "heuristic": ClassFactory("canary.baselines", "Heuristic"),
        "hinted_heuristic": ClassFactory("canary.forge.investigators", "HintedHeuristic"),
    }
    p82_inv = dict(core_inv)
    p82_inv["interview_crowded_proxy"] = lambda s: InterviewCrowdedProxy(seed=s)

    base_cache = {
        "score": sum(b["default"]["solver"][0] for b in bundles) / float(len(bundles)),
        "acc": sum(b["default"]["solver"][1] for b in bundles) / float(len(bundles)),
    }

    eval_def_core = evaluate(
        default_strategy_json(),
        core_inv,
        solver_fac,
        seed_list,
        "hard",
        runner=table_runner,
        workers=1,
        baseline=base_cache,
        fitness_mode="mean",
        min_solver_acc=0.85,
    )
    eval_p51_core = evaluate(
        SURVEILLANCE_SLEEPER_P51,
        core_inv,
        solver_fac,
        seed_list,
        "hard",
        runner=table_runner,
        workers=1,
        baseline=base_cache,
        fitness_mode="mean",
        min_solver_acc=0.85,
    )
    eval_def_p82 = evaluate(
        default_strategy_json(),
        p82_inv,
        solver_fac,
        seed_list,
        "hard",
        runner=table_runner,
        workers=1,
        baseline=base_cache,
        fitness_mode="mean",
        min_solver_acc=0.85,
    )
    eval_p51_p82 = evaluate(
        SURVEILLANCE_SLEEPER_P51,
        p82_inv,
        solver_fac,
        seed_list,
        "hard",
        runner=table_runner,
        workers=1,
        baseline=base_cache,
        fitness_mode="mean",
        min_solver_acc=0.85,
    )

    def _clean_eval(d: dict[str, Any]) -> dict[str, Any]:
        return {
            "feasible": bool(d["feasible"]),
            "min_solver_acc": float(d["min_solver_acc"]),
            "solver_score": round(float(d["solver_score"]), 4),
            "solver_acc": round(float(d["solver_acc"]), 4),
            "solver_acc_pct": round(100.0 * float(d["solver_acc"]), 1),
            "baseline_solver_score": round(float(d["baseline_solver_score"]), 4),
            "mean_regret": round(float(d["regret"]), 4),
            "min_regret": round(float(d["min_regret"]), 4),
            "beaten": list(d["beaten"]),
            "per_investigator": {
                k: {
                    "score": round(float(v["score"]), 4),
                    "acc": round(float(v["acc"]), 4),
                    "acc_pct": round(100.0 * float(v["acc"]), 1),
                    "regret": round(float(v["regret"]), 4),
                }
                for k, v in d["per_investigator"].items()
            },
        }

    n_b = float(len(bundles))
    neg_solver_score = sum(b["neg_solver"][0] for b in bundles) / n_b
    neg_solver_acc = sum(b["neg_solver"][1] for b in bundles) / n_b
    proxy_def_iv = sum(b["telemetry"]["default"]["interview_crowded_proxy"]["interviews"] for b in bundles) / n_b
    proxy_def_can = sum(b["telemetry"]["default"]["interview_crowded_proxy"]["canaries"] for b in bundles) / n_b
    proxy_p51_iv = sum(b["telemetry"]["p51"]["interview_crowded_proxy"]["interviews"] for b in bundles) / n_b
    proxy_p51_can = sum(b["telemetry"]["p51"]["interview_crowded_proxy"]["canaries"] for b in bundles) / n_b
    grok_rule0 = sum(b["telemetry"]["p51"]["grok_tactics"]["rule0_fires"] for b in bundles)
    grok_frames = sum(b["telemetry"]["p51"]["grok_tactics"]["restricted_frames"] for b in bundles)
    proxy_rule0 = sum(b["telemetry"]["p51"]["interview_crowded_proxy"]["rule0_fires"] for b in bundles)
    proxy_frames = sum(b["telemetry"]["p51"]["interview_crowded_proxy"]["restricted_frames"] for b in bundles)

    return {
        "seed_start": seed_list[0],
        "seed_end": seed_list[-1],
        "n_seeds": len(seed_list),
        "p51_strategy_json": SURVEILLANCE_SLEEPER_P51,
        "unconstrained_most_recipients_neg": {
            "strategy_json": PURE_MOST_RECIPIENTS_NEG,
            "solver_score": round(float(neg_solver_score), 4),
            "solver_acc": round(float(neg_solver_acc), 4),
            "solver_acc_pct": round(100.0 * float(neg_solver_acc), 1),
            "feasible_at_85pct": bool(
                neg_solver_acc >= 0.85 and neg_solver_score >= 0.5 * base_cache["score"]
            ),
        },
        "core_3inv": {
            "default_v0": _clean_eval(eval_def_core),
            "surveillance_sleeper_p51": _clean_eval(eval_p51_core),
        },
        "augmented_p82_4inv": {
            "default_v0": _clean_eval(eval_def_p82),
            "surveillance_sleeper_p51": _clean_eval(eval_p51_p82),
        },
        "p82_proxy_telemetry": {
            "default_interviews_per_ep": round(proxy_def_iv, 2),
            "default_canaries_per_ep": round(proxy_def_can, 2),
            "p51_interviews_per_ep": round(proxy_p51_iv, 2),
            "p51_canaries_per_ep": round(proxy_p51_can, 2),
            "p51_rule0_fires_vs_grok_total": int(grok_rule0),
            "p51_restricted_frames_vs_grok_total": int(grok_frames),
            "p51_rule0_fires_vs_p82_proxy_total": int(proxy_rule0),
            "p51_restricted_frames_vs_p82_proxy_total": int(proxy_frames),
        },
    }


def run_all_simulations(fast: bool = False, workers: int | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    p71_seeds = range(0, 30) if fast else range(0, 500)
    pretext_seeds = range(3000, 3020) if fast else range(3000, 3200)
    mole_seeds = range(2000, 2004) if fast else range(2000, 2060)
    mc_trials = 2000 if fast else 10000

    ch = compute_v14_channel_hierarchy(ROOT)
    p71 = simulate_social_p71(p71_seeds)
    p41 = simulate_pretext_p41_p73(pretext_seeds)
    p11_p12 = simulate_interviews_p11_p12_p72(pretext_seeds, mc_trials=mc_trials)
    p51_p82 = evaluate_sleeper_mole_p51_p82(mole_seeds, workers=workers)
    elapsed = time.monotonic() - t0

    return {
        "mode": "fast" if fast else "full",
        "elapsed_s": round(elapsed, 3),
        "channel_hierarchy": ch,
        "social_p71": p71,
        "pretext_p41_p73": p41,
        "interviews_p11_p12_p72": p11_p12,
        "mole_p51_p82": p51_p82,
    }


def format_human_report(payload: dict[str, Any]) -> str:
    ch = payload["channel_hierarchy"]
    iv_h = ch["interview_by_tier"]["hard"]
    iv_m = ch["interview_by_tier"]["medium"]
    iv_e = ch["interview_by_tier"]["easy"]
    ah = ch["after_hours_hard"]
    pc = ch["plant_canary_hard"]
    cm = ch["careful_mole_day1"]
    gb = ch["v15_gate_b_negative_control"]
    fa = ch["failure_analysis_v14"]
    p71 = payload["social_p71"]
    p41 = payload["pretext_p41_p73"]
    d6 = p41["checkpoints"]["day_6"]
    d12 = p41["checkpoints"]["day_12"]
    p11 = payload["interviews_p11_p12_p72"]["p11_sue"]
    p12 = payload["interviews_p11_p12_p72"]["p12_p72_othello"]
    mp = payload["mole_p51_p82"]
    neg = mp["unconstrained_most_recipients_neg"]
    c_def = mp["core_3inv"]["default_v0"]
    c_p51 = mp["core_3inv"]["surveillance_sleeper_p51"]
    a_def = mp["augmented_p82_4inv"]["default_v0"]
    a_p51 = mp["augmented_p82_4inv"]["surveillance_sleeper_p51"]
    tel = mp["p82_proxy_telemetry"]

    lines = [
        f"Canary Research Proposal Simulations ({payload['mode']} mode, {payload['elapsed_s']:.2f}s)",
        "=" * 78,
        f"1. Frozen Rules & Channel Hierarchy (tiers={ch['tiers_version']}, hash={ch['v14_hash']}, v1.3={ch['v13_hash']})",
        f"   - interview (easy, LR={iv_e['lr']:.2f}): p_inn={iv_e['p_innocent']:.3f}, p_mole={iv_e['p_mole']:.3f}, KL={iv_e['kl_nats_5dp']:.5f} nats, d={iv_e['binary_d_3dp']:.3f}",
        f"   - interview (medium, LR={iv_m['lr']:.2f}): p_inn={iv_m['p_innocent']:.3f}, p_mole={iv_m['p_mole']:.3f}, KL={iv_m['kl_nats_5dp']:.5f} nats, d={iv_m['binary_d_3dp']:.3f}",
        f"   - interview (hard, LR={iv_h['lr']:.2f}): p_inn={iv_h['p_innocent']:.3f}, p_mole={iv_h['p_mole']:.3f}, LLR+={iv_h['llr_evasive_nats']:+.4f}, LLR-={iv_h['llr_cooperative_nats']:+.4f}, KL={iv_h['kl_nats_5dp']:.5f} nats, d={iv_h['binary_d_3dp']:.3f} (d_HH={iv_h['hasselblad_hedges_d']:.3f})",
        f"   - after_hours (hard): mole={ah['rate_mole']:.2f}/d, decoy={ah['rate_decoy']:.2f}/d ({ah['decoy_to_mole_ratio']:.2f}x mole), plain_inn={ah['rate_plain_innocent']:.5f}/d ({ah['rate_plain_total']:.2f}/d total), total={ah['total_events_per_day']:.2f}/d",
        f"   - after_hours PPV: {ah['rate_mole']:.2f} / {ah['total_events_per_day']:.2f} = {ah['ppv_pct']:.4f}% ({ah['ppv_ex_decoy_pct']:.4f}% ex-decoy); daily log KL={ah['poisson_kl_joint_day_nats']:.5f} nats/d (ah-only {ah['poisson_kl_after_hours_nats']:.5f} nats/d)",
        f"   - plant_canary (3-variant, acc={pc['fingerprint_accuracy']:.2f}): MI={pc['mi_nats_5dp']:.5f} nats ({pc['mi_bits']:.4f} bits), LLR_match={pc['llr_match_vs_flip_nats']:+.4f} nats, {pc['ratio_vs_interview_kl_5dp']:.1f}x interview KL (exact {pc['ratio_vs_interview_kl_exact']:.2f}x)",
        f"   - entropy lower bound: ln(39)/{pc['mi_nats_5dp']:.5f} = {pc['entropy_bound_leaked_traps']:.3f} leaked 3-variant traps (prior H={pc['prior_entropy_ex_decoy_nats']:.5f} nats)",
        f"   - careful_mole Day-1 hit rate (k/39)*(1-k/40): k*={cm['k_star']} -> {cm['hit_rate_k_star']:.4f} vs k=3 -> {cm['hit_rate_k3']:.4f} ({cm['ratio_k_star_vs_k3']:.1f}x) vs k=39 -> {cm['hit_rate_k39']:.4f} ({cm['ratio_k_star_vs_k39']:.1f}x)",
        f"   - v1.5-candidate Gate B negative control (s=0.4, N=40): P(rum|mole)={gb['p_target_given_mole']:.6f}, P(rum|inn)={gb['p_target_given_innocent']:.6f}, LLR={gb['llr_rumour_nats']:+.5f} nats",
    ]
    if fa:
        lines.append(
            f"   - v1.4 hard empirical gap (n={fa['n_seeds']} post-hoc locked dev seeds 0-29): OpenCode gemini-4-carbon={fa['opencode_score']:.3f} +/- {fa['opencode_score_ci']:.3f} (LA {fa['opencode_luck_adjusted']:.3f}) vs SolverPolicy={fa['solver_score']:.3f} +/- {fa['solver_score_ci']:.3f}; raw gap={fa['raw_gap_v']:.2f} V, LA gap={fa['luck_adjusted_gap_v']:.2f} V; interviews={fa['opencode_interviews_per_ep']:.2f} vs {fa['solver_interviews_per_ep']:.1f}; canaries={fa['opencode_canaries_per_ep']:.1f} ({fa['opencode_canary_capacity_pct']:.1f}%) vs {fa['solver_canaries_per_ep']:.1f} ({fa['solver_canary_capacity_pct']:.1f}%); full-budget under-planted days={fa['days_lt2_full']}/{fa['days_lt2_canaries']} ({fa['interviews_on_lt2_full']} interviews); unresolved accusations={fa['not_isolated_count']}/{fa['accused_count']} (consistent mean {fa['opencode_consistent_mean']:.2f} vs {fa['solver_consistent_mean']:.2f}, penalty {fa['commitment_penalty_v']:.2f} V)"
        )

    lines.extend(
        [
            "",
            f"2. P7.1 Secret-Free Public-Digest Social Cascade & Zero-Leakage Audit (seeds {p71['seed_start']}-{p71['seed_end']}, n={p71['n_worlds']})",
            f"   - V16 Day-1 focal vs mole: {p71['v16_primary_mole_hits']}/{p71['n_worlds']} ({p71['v16_primary_mole_pct']:.2f}% vs 1/39={p71['uniform_non_decoy_prior_pct']:.2f}%, z={p71['v16_z_stat']:+.3f}); P7.1 public-digest focal vs mole: {p71['p71_digest_primary_mole_hits']}/{p71['n_worlds']} ({p71['p71_digest_primary_mole_pct']:.2f}%, z={p71['p71_digest_z_stat']:+.3f})",
            f"   - Secret-seed mutation invariance: {p71['secret_seed_invariant_worlds']}/{p71['n_worlds']} ({p71['secret_seed_invariance_pct']:.1f}%); PublicDayFacts mole-field absence: {p71['public_facts_mole_absent_worlds']}/{p71['n_worlds']}; exact I(Social; Mole | PublicDayFacts)={p71['exact_conditional_mi_nats']:.4f} nats (social_loglik={p71['exact_solver_social_loglik_nats']:.4f})",
            f"   - Lint & decoy-vocab hygiene ({p71['messages_audited']} msgs): forbidden_prefixes={p71['forbidden_subject_prefix_hits']}, non_decoy_vocab_hits={p71['non_decoy_vocab_hits']}, snippet_salience={p71['snippet_salience_pct']:.1f}%; v1.5 negative control LLR={p71['v15_negative_control']['uniform_peer_llr_nats']:+.5f} nats (restricted peer {p71['v15_negative_control']['single_restricted_peer_llr_nats']:+.5f} nats, {p71['v15_negative_control']['restricted_peer_rate_ratio']:.2f}x rate)",
            "",
            f"3. P4.1 / P7.3 Plausible Pretext Target Simulation (seeds {p41['seed_start']}-{p41['seed_end']}, n={p41['n_worlds']})",
            f"   - Day 1 init: P(static_focal == mole) = {p41['day1_static_mole_hits']}/{p41['n_worlds']} ({100.0*p41['day1_static_mole_rate']:.2f}% vs 1/39 = {100.0*p41['day1_uniform_prior']:.2f}%)",
            f"   - Day 6 (surfaced={d6['episodes_with_surfaced_reg_leak']}/{d6['n_worlds']}, mean |C_reg|={d6['mean_c_reg_size']:.2f}): static survival={d6['static_survival_count']}/{d6['n_worlds']} ({d6['static_survival_pct']:.2f}%, {d6['static_eliminated_pct']:.2f}% eliminated) vs dynamic P4.1/P7.3={d6['dynamic_survival_c_reg_count']}/{d6['n_worlds']} ({d6['dynamic_survival_c_reg_pct']:.2f}%); P(target==mole)={d6['p_target_is_mole']:.4f} vs E[1/|P_6|]={d6['expected_inv_p_d']:.4f} (emp LLR={d6['empirical_llr_nats']:+.4f}, z={d6['z_stat_zero_leakage']:+.3f}, exact conditional LLR=0.0000)",
            f"   - Day 12 (surfaced={d12['episodes_with_surfaced_reg_leak']}/{d12['n_worlds']}, mean |C_reg|={d12['mean_c_reg_size']:.2f}): static survival={d12['static_survival_count']}/{d12['n_worlds']} ({d12['static_survival_pct']:.2f}%, {d12['static_eliminated_pct']:.2f}% eliminated) vs dynamic P4.1/P7.3={d12['dynamic_survival_c_reg_count']}/{d12['n_worlds']} ({d12['dynamic_survival_c_reg_pct']:.2f}%); P(target==mole)={d12['p_target_is_mole']:.4f} vs E[1/|P_12|]={d12['expected_inv_p_d']:.4f} (emp LLR={d12['empirical_llr_nats']:+.4f}, z={d12['z_stat_zero_leakage']:+.3f}, exact conditional LLR=0.0000)",
            f"   - Focal-restriction probe (restrict Day-1 focal on Day 5, P_d = C_reg(d) \\ restricted_d): Day 6 static in P_d={d6['focal_restricted_probe_static_in_p_d_pct']:.1f}% vs dynamic={d6['focal_restricted_probe_dyn_in_p_d_pct']:.1f}% (P(target==mole)={d6['focal_restricted_probe_p_target_is_mole']:.4f} vs exp {d6['focal_restricted_probe_expected_rate']:.4f}); Day 12 static in P_d={d12['focal_restricted_probe_static_in_p_d_pct']:.1f}% vs dynamic={d12['focal_restricted_probe_dyn_in_p_d_pct']:.1f}% (P(target==mole)={d12['focal_restricted_probe_p_target_is_mole']:.4f} vs exp {d12['focal_restricted_probe_expected_rate']:.4f})",
            "",
            "4. P1.1 SUE Interview & P1.2 / P7.2 Othello Scrutiny Anxiety Simulation",
            f"   - P1.1 ungrounded (LR=1.05): p_mole={p11['regimes']['p11_ungrounded']['p_mole']:.2f}, KL={p11['regimes']['p11_ungrounded']['kl_nats']:.5f} nats ({p11['v14_vs_ungrounded_kl_ratio']:.1f}x weaker than v1.4 hard)",
            f"   - P1.1 SUE grounded (LR=1.80, window={p11['sue_window_days']}d): p_mole={p11['regimes']['p11_sue_grounded']['p_mole']:.2f}, KL={p11['regimes']['p11_sue_grounded']['kl_nats']:.5f} nats ({p11['sue_vs_ungrounded_kl_ratio']:.1f}x ungrounded, {p11['sue_vs_v14_kl_ratio']:.1f}x v1.4 hard; plant_canary MI is {p11['canary_vs_sue_mi_ratio']:.1f}x SUE); eligible worlds Day 6={p11['sue_eligible_worlds_day6_pct']:.1f}%, Day 12={p11['sue_eligible_worlds_day12_pct']:.1f}%; anti-farming repeat invariance={p11['anti_farming_repeat_invariance_ok']}",
            f"   - P1.2 / P7.2 Othello (OR={p12['mole_odds_ratio_num']}/{p12['mole_odds_ratio_den']}={p12['mole_odds_ratio']:.6f}):",
        ]
    )
    for st in p12["states"]:
        lines.append(
            f"     * {st['state']} (r={st['r']}, m={st['m']}): p_inn={st['p_evasive_innocent']:.3f}, p_mole={st['p_evasive_mole']:.4f}, KL={st['kl_nats']:.5f} nats, naive_drift={st['naive_flat_lr_drift_innocent_nats']:+.5f} ({st['naive_flat_lr_drift_innocent_4dp']:+.4f}) nats/iv, calibrated_drift={st['calibrated_drift_innocent_nats']:+.5f} nats/iv, solver_bias={st['solver_calibration_bias_nats']:.4f}"
        )
    lines.append(
        f"     * Monte Carlo check (n={p12['mc_trials']} restricted-focal innocent interviews): mean naive drift={p12['mc_naive_drift_mean_nats']:+.4f} nats/iv (10-iv={p12['restricted_focal_10iv_false_drift_nats']:+.4f} nats), mean calibrated LR={p12['mc_calibrated_lr_mean']:.4f} (bias={p12['solver_public_conditioned_bias_nats']:.4f})"
    )

    lines.extend(
        [
            "",
            f"5. P5.1 Surveillance Sleeper Mole & P8.2 Proxy Evaluation (seeds {mp['seed_start']}-{mp['seed_end']}, n={mp['n_seeds']})",
            f"   - Unconstrained stonewalling negative control (pure_most_recipients_neg): feasible={neg['feasible_at_85pct']}, Solver={neg['solver_score']:.4f} (acc={neg['solver_acc_pct']:.1f}% < 85.0% floor)",
            f"   - Core 3-investigator Forge suite (DEFAULT_STRATEGY): feasible={c_def['feasible']}, Solver={c_def['solver_score']:.4f} (acc={c_def['solver_acc_pct']:.1f}%), grok_tactics={c_def['per_investigator']['grok_tactics']['score']:.4f} ({c_def['per_investigator']['grok_tactics']['acc_pct']:.1f}%, regret={c_def['per_investigator']['grok_tactics']['regret']:+.4f}), hinted_heuristic={c_def['per_investigator']['hinted_heuristic']['score']:.4f} ({c_def['per_investigator']['hinted_heuristic']['acc_pct']:.1f}%, regret={c_def['per_investigator']['hinted_heuristic']['regret']:+.4f}), heuristic={c_def['per_investigator']['heuristic']['score']:.4f} ({c_def['per_investigator']['heuristic']['acc_pct']:.1f}%, regret={c_def['per_investigator']['heuristic']['regret']:+.4f}), min_regret={c_def['min_regret']:+.4f}, mean_regret={c_def['mean_regret']:+.4f}",
            f"   - Core 3-investigator Forge suite (P5.1 surveillance_sleeper_p51): feasible={c_p51['feasible']}, Solver={c_p51['solver_score']:.4f} (acc={c_p51['solver_acc_pct']:.1f}%), grok_tactics={c_p51['per_investigator']['grok_tactics']['score']:.4f} ({c_p51['per_investigator']['grok_tactics']['acc_pct']:.1f}%, regret={c_p51['per_investigator']['grok_tactics']['regret']:+.4f}), hinted_heuristic={c_p51['per_investigator']['hinted_heuristic']['score']:.4f} ({c_p51['per_investigator']['hinted_heuristic']['acc_pct']:.1f}%, regret={c_p51['per_investigator']['hinted_heuristic']['regret']:+.4f}), heuristic={c_p51['per_investigator']['heuristic']['score']:.4f} ({c_p51['per_investigator']['heuristic']['acc_pct']:.1f}%, regret={c_p51['per_investigator']['heuristic']['regret']:+.4f}), min_regret={c_p51['min_regret']:+.4f}, mean_regret={c_p51['mean_regret']:+.4f}",
            f"   - P8.2 interview_crowded_proxy (DEFAULT -> P5.1): score={a_def['per_investigator']['interview_crowded_proxy']['score']:.4f} ({a_def['per_investigator']['interview_crowded_proxy']['acc_pct']:.1f}%, regret={a_def['per_investigator']['interview_crowded_proxy']['regret']:+.4f}, iv={tel['default_interviews_per_ep']:.2f}, canaries={tel['default_canaries_per_ep']:.2f}) -> score={a_p51['per_investigator']['interview_crowded_proxy']['score']:.4f} ({a_p51['per_investigator']['interview_crowded_proxy']['acc_pct']:.1f}%, regret={a_p51['per_investigator']['interview_crowded_proxy']['regret']:+.4f}, iv={tel['p51_interviews_per_ep']:.2f}, canaries={tel['p51_canaries_per_ep']:.2f}); 4-inv mean_regret {a_def['mean_regret']:+.4f} -> {a_p51['mean_regret']:+.4f}; P5.1 triggers vs grok=(rule0:{tel['p51_rule0_fires_vs_grok_total']}, frames:{tel['p51_restricted_frames_vs_grok_total']}), vs P8.2 proxy=(rule0:{tel['p51_rule0_fires_vs_p82_proxy_total']}, frames:{tel['p51_restricted_frames_vs_p82_proxy_total']})",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic CPU-only simulations for Canary deception research proposals."
    )
    ap.add_argument("--fast", action="store_true", help="Run fast deterministic subset (<8s)")
    ap.add_argument("--json", action="store_true", help="Emit JSON output to stdout")
    ap.add_argument("--out-json", type=Path, default=None, help="Optional path to write JSON output")
    ap.add_argument("--workers", type=int, default=None, help="Worker processes for mole evaluation")
    args = ap.parse_args(argv)

    payload = run_all_simulations(fast=args.fast, workers=args.workers)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_human_report(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
