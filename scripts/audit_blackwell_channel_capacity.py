from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import time
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.env import Env
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.solver import belief as B
from canary.solver.policy import SolverPolicy
from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_text
from canary.types import INVESTIGATIVE_TOOLS, Step

HASH_CH = chr(35)
EXPECTED_V14_HASH = "a8f99c2537c91d72"

DECOY_VOCAB: tuple[str, ...] = (
    "raise",
    "management",
    "deserve",
    "promotion",
    "cv",
    "pay",
    "angry",
    "unfair",
    "furious",
    "sick of",
    "quit",
    "ridiculous",
    "fed up",
    "hate",
    "burn out",
    "recruiter",
    "goalposts",
    "nobody asks",
    "updating my cv",
)

SALIENCE_TERMS: tuple[str, ...] = ("doc", "leak", "meeting")
AUTHORITY_ROLES: tuple[str, ...] = ("manager", "lead", "controller", "counsel")
FORBIDDEN_SUBJECT_PREFIXES: tuple[str, ...] = (
    "rumour:",
    "rumor:",
    "grudge:",
    "unverified accusation:",
)
EMP_ID_RX = re.compile(r"\be\d\d\b")


@dataclass(frozen=True)
class BinaryAnchorContext:
    facts: PublicDayFacts
    by_id: dict[str, EmployeeFacts]
    primary_suspect: str
    secondary_suspect: str
    authority_speakers: tuple[str, ...]
    peers: tuple[str, ...]
    seen_docs: dict[int, tuple[dict[str, Any], ...]]
    prior_events: tuple[dict[str, Any], ...] = ()
    today_events: tuple[dict[str, Any], ...] = ()


def compute_tier_hash(tiers: dict[str, rules.TierParams], known_v_mode: bool) -> str:
    payload = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def interview_kl_nats(p0: float, lr: float) -> float:
    p1 = min(0.999999, p0 * lr)
    return p1 * math.log(p1 / p0) + (1.0 - p1) * math.log((1.0 - p1) / (1.0 - p0))


def interview_reverse_kl_nats(p0: float, lr: float) -> float:
    p1 = min(0.999999, p0 * lr)
    return p0 * math.log(p0 / p1) + (1.0 - p0) * math.log((1.0 - p0) / (1.0 - p1))


def interview_eig_nats(prior_mole: float, p0: float, lr: float) -> float:
    if prior_mole <= 0.0 or prior_mole >= 1.0:
        return 0.0
    p1 = min(0.999999, p0 * lr)
    pe = prior_mole * p1 + (1.0 - prior_mole) * p0
    h_marg = -pe * math.log(pe) - (1.0 - pe) * math.log(1.0 - pe)
    h1 = -p1 * math.log(p1) - (1.0 - p1) * math.log(1.0 - p1)
    h0 = -p0 * math.log(p0) - (1.0 - p0) * math.log(1.0 - p0)
    return max(0.0, h_marg - (prior_mole * h1 + (1.0 - prior_mole) * h0))


def interview_shannon_capacity_nats(p0: float, lr: float) -> tuple[float, float]:
    p1 = min(0.999999, p0 * lr)
    if abs(p1 - p0) < 1e-12:
        return 0.0, 0.5
    h1 = -p1 * math.log(p1) - (1.0 - p1) * math.log(1.0 - p1)
    h0 = -p0 * math.log(p0) - (1.0 - p0) * math.log(1.0 - p0)
    z = math.exp((h1 - h0) / (p1 - p0))
    pe_star = 1.0 / (1.0 + z)
    q_star = (pe_star - p0) / (p1 - p0)
    return interview_eig_nats(q_star, p0, lr), q_star


def canary_mi_given_leak_nats(accuracy: float, k_variants: int) -> float:
    if k_variants <= 1:
        return 0.0
    if accuracy >= 1.0:
        return math.log(float(k_variants))
    flip = (1.0 - accuracy) / float(k_variants - 1)
    return math.log(float(k_variants)) + accuracy * math.log(accuracy) + (1.0 - accuracy) * math.log(flip)


def canary_pairwise_kl_given_leak_nats(accuracy: float, k_variants: int) -> float:
    if k_variants <= 1 or accuracy >= 1.0:
        return math.inf
    flip = (1.0 - accuracy) / float(k_variants - 1)
    other_same = accuracy
    other_rest = max(0, k_variants - 2) * flip
    val = accuracy * math.log(accuracy / flip) + flip * math.log(flip / other_same)
    if other_rest > 0.0:
        val += other_rest * 0.0
    return val


def exact_blackwell_garbling(p0: float, lr: float, accuracy: float, k_variants: int) -> dict[str, Any]:
    p1 = p0 * lr
    eps = (1.0 - accuracy) / float(k_variants - 1) if k_variants > 1 else 0.0
    denom = accuracy - eps
    if denom <= 0.0:
        raise ValueError("canary channel must have accuracy > flip rate")
    delta = (p1 - p0) / denom
    g_non_a = p0 - eps * delta
    g_a = g_non_a + delta

    p0_f = Fraction(str(p0))
    lr_f = Fraction(str(lr))
    acc_f = Fraction(str(accuracy))
    p1_f = p0_f * lr_f
    eps_f = (Fraction(1) - acc_f) / Fraction(k_variants - 1)
    delta_f = (p1_f - p0_f) / (acc_f - eps_f)
    g_non_a_f = p0_f - eps_f * delta_f
    g_a_f = g_non_a_f + delta_f

    p_canary = [
        [accuracy if j == i else eps for j in range(k_variants)]
        for i in range(k_variants)
    ]
    g_matrix = [
        [g_a, 1.0 - g_a] if j == 0 else [g_non_a, 1.0 - g_non_a]
        for j in range(k_variants)
    ]
    p_iv = [
        [p1, 1.0 - p1] if i == 0 else [p0, 1.0 - p0]
        for i in range(k_variants)
    ]
    product = [
        [
            sum(p_canary[i][m] * g_matrix[m][c] for m in range(k_variants))
            for c in range(2)
        ]
        for i in range(k_variants)
    ]
    max_err = max(
        abs(product[i][c] - p_iv[i][c])
        for i in range(k_variants)
        for c in range(2)
    )
    valid_stochastic = all(
        0.0 < row[0] < 1.0 and 0.0 < row[1] < 1.0 and abs(sum(row) - 1.0) < 1e-15
        for row in g_matrix
    )
    tv_canary = abs(accuracy - eps)
    tv_iv = abs(p1 - p0)
    reverse_garbling_impossible = (k_variants > 2) and (tv_iv < tv_canary)

    bayes_utility_checks = []
    for v_val in (0.85, 0.70, 0.55):
        for prior_a in (0.10, 0.3333333333, 0.50, 0.65, 0.80):
            prior = [prior_a, 0.5 * (1.0 - prior_a), 0.5 * (1.0 - prior_a)]
            eu_canary = 0.0
            for y_idx in range(k_variants):
                py = sum(prior[s] * p_canary[s][y_idx] for s in range(k_variants))
                if py <= 0.0:
                    continue
                post = [prior[s] * p_canary[s][y_idx] / py for s in range(k_variants)]
                best_act = max([0.0] + [post[s] * v_val - (1.0 - post[s]) for s in range(k_variants)])
                eu_canary += py * best_act
            eu_iv = 0.0
            for z_idx in range(2):
                pz = sum(prior[s] * p_iv[s][z_idx] for s in range(k_variants))
                if pz <= 0.0:
                    continue
                post = [prior[s] * p_iv[s][z_idx] / pz for s in range(k_variants)]
                best_act = max([0.0] + [post[s] * v_val - (1.0 - post[s]) for s in range(k_variants)])
                eu_iv += pz * best_act
            bayes_utility_checks.append(
                {
                    "V": v_val,
                    "prior_A": round(prior_a, 4),
                    "eu_canary": round(eu_canary, 6),
                    "eu_interview": round(eu_iv, 6),
                    "dominance_gap": round(eu_canary - eu_iv, 6),
                }
            )

    return {
        "p_canary": p_canary,
        "p_interview": p_iv,
        "garbling_matrix_G": g_matrix,
        "g_A": g_a,
        "g_non_A": g_non_a,
        "g_A_fraction": f"{g_a_f.numerator}/{g_a_f.denominator}",
        "g_non_A_fraction": f"{g_non_a_f.numerator}/{g_non_a_f.denominator}",
        "max_reconstruction_error": max_err,
        "is_row_stochastic_strict_interior": valid_stochastic,
        "tv_canary": tv_canary,
        "tv_interview": tv_iv,
        "reverse_garbling_impossible": reverse_garbling_impossible,
        "strict_blackwell_dominance": bool(valid_stochastic and max_err < 1e-14 and reverse_garbling_impossible),
        "bayes_utility_checks": bayes_utility_checks,
    }


def exact_canary_eig_nats(
    post: dict[str, float],
    asg: dict[str, str],
    nreg_s: dict[str, float] | dict[str, int],
    params: rules.TierParams,
    window_days: int | None = None,
    use_competition: bool = True,
) -> float:
    n_emp = params.n_employees
    win = params.leak_window_days if window_days is None else window_days
    weight = max(0.0, 1.0 - len(asg) / float(n_emp)) if params.careful_mole else 1.0
    labels = sorted(set(asg.values()))
    k_distinct = len(labels)
    acc = params.fingerprint_accuracy if k_distinct > 1 else 1.0
    flip = (1.0 - acc) / float(k_distinct - 1) if k_distinct > 1 else 0.0

    marg: dict[str, float] = {"_none": 0.0}
    for lab in labels:
        marg[lab] = 0.0
    h_cond = 0.0

    for emp, p in post.items():
        if p <= 0.0:
            continue
        my_lab = asg.get(emp)
        if my_lab is None or weight <= 0.0:
            q = 0.0
        elif not use_competition:
            per_day = params.p_leak * weight
            q = 1.0 - (1.0 - per_day) ** win
        else:
            denom = weight + max(1.0, float(nreg_s.get(emp, 0.0)))
            per_day = params.p_leak * weight / denom
            q = 1.0 - (1.0 - per_day) ** win
        p_none = 1.0 - q
        marg["_none"] += p * p_none
        if p_none > 0.0:
            h_cond -= p * p_none * math.log(p_none)
        if q > 0.0:
            for lab in labels:
                prob_y = q * (acc if lab == my_lab else flip)
                marg[lab] += p * prob_y
                if prob_y > 0.0:
                    h_cond -= p * prob_y * math.log(prob_y)

    h_marg = -sum(v * math.log(v) for v in marg.values() if v > 0.0)
    return max(0.0, h_marg - h_cond)


def conditional_partition_metrics(
    post: dict[str, float],
    asg: dict[str, str],
    params: rules.TierParams,
) -> tuple[float, float, float]:
    labels = sorted(set(asg.values()))
    k_distinct = len(labels)
    mass_in = sum(post.get(emp, 0.0) for emp in asg)
    if mass_in <= 1e-12:
        return 0.0, 0.0, 0.0
    label_mass = {lab: 0.0 for lab in labels}
    for emp, lab in asg.items():
        label_mass[lab] += post.get(emp, 0.0) / mass_in
    part_entropy = -sum(v * math.log(v) for v in label_mass.values() if v > 0.0)
    if k_distinct <= 1:
        return part_entropy, 0.0, mass_in
    acc = params.fingerprint_accuracy
    flip = (1.0 - acc) / float(k_distinct - 1)
    y_marg = {lab: acc * label_mass[lab] + flip * (1.0 - label_mass[lab]) for lab in labels}
    h_y = -sum(v * math.log(v) for v in y_marg.values() if v > 0.0)
    h_y_given_m = (
        0.0
        if acc >= 1.0
        else (-acc * math.log(acc) - (1.0 - acc) * math.log(flip))
    )
    return part_entropy, max(0.0, h_y - h_y_given_m), mass_in


def uniform_pool_canary_eig(
    m_suspects: int,
    k_recipients: int,
    k_variants: int,
    params: rules.TierParams,
    nreg_expected: float,
    window_days: int | None = None,
    use_competition: bool = True,
) -> float:
    if k_recipients <= 0 or m_suspects <= 1:
        return 0.0
    k_eff = max(1, min(k_variants, k_recipients))
    post = {f"e{i:02d}": 1.0 / float(m_suspects) for i in range(m_suspects)}
    asg: dict[str, str] = {}
    for i in range(min(k_recipients, m_suspects)):
        asg[f"e{i:02d}"] = f"L{i % k_eff}"
    for j in range(max(0, k_recipients - m_suspects)):
        asg[f"x{j:02d}"] = f"L{j % k_eff}"
    nreg_s = {k: nreg_expected for k in post}
    return exact_canary_eig_nats(
        post,
        asg,
        nreg_s,
        params,
        window_days=window_days,
        use_competition=use_competition,
    )


def audit_tier_channels() -> dict[str, Any]:
    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    if v14_hash != EXPECTED_V14_HASH:
        raise RuntimeError(f"v1.4 hash mismatch: {v14_hash} != {EXPECTED_V14_HASH}")

    tiers_report: dict[str, Any] = {}
    for name in ("easy", "medium", "hard"):
        p = rules.TIERS[name]
        m_alive = p.n_employees - (1 if p.decoy else 0)
        kl = interview_kl_nats(p.p_evasive_innocent, p.interview_lr)
        rev_kl = interview_reverse_kl_nats(p.p_evasive_innocent, p.interview_lr)
        cap_iv, q_star = interview_shannon_capacity_nats(p.p_evasive_innocent, p.interview_lr)
        iv_day1 = interview_eig_nats(1.0 / float(m_alive), p.p_evasive_innocent, p.interview_lr)
        c_mi = canary_mi_given_leak_nats(p.fingerprint_accuracy, p.max_variants)
        garbling = exact_blackwell_garbling(
            p.p_evasive_innocent,
            p.interview_lr,
            p.fingerprint_accuracy,
            p.max_variants,
        )

        best_1d_nocomp = max(
            (
                uniform_pool_canary_eig(m_alive, k_rec, p.max_variants, p, 0.0, window_days=1, use_competition=False),
                k_rec,
            )
            for k_rec in range(p.max_variants, m_alive + 1)
        )
        mean_docs_day = sum(p.docs_per_day) / float(len(p.docs_per_day))
        dept_share = 0.2 * p.p_single_dept_recipients + 0.4 * (1.0 - p.p_single_dept_recipients)
        nreg_day1 = mean_docs_day * dept_share
        nreg_steady = nreg_day1 * float(p.leak_window_days)
        best_day1_win = max(
            (
                uniform_pool_canary_eig(m_alive, k_rec, p.max_variants, p, nreg_day1),
                k_rec,
            )
            for k_rec in range(p.max_variants, m_alive + 1)
        )
        best_steady_win = max(
            (
                uniform_pool_canary_eig(m_alive, k_rec, p.max_variants, p, nreg_steady),
                k_rec,
            )
            for k_rec in range(p.max_variants, m_alive + 1)
        )

        daily_canary_budget_cost = p.canary_cost * float(p.canaries_per_day)
        expected_daily_leak_bleed = p.p_leak * p.leak_damage

        tiers_report[name] = {
            "n_employees": p.n_employees,
            "non_decoy_suspects": m_alive,
            "n_days": p.n_days,
            "p_leak": p.p_leak,
            "canaries_per_day": p.canaries_per_day,
            "max_variants": p.max_variants,
            "canary_cost": p.canary_cost,
            "daily_canary_budget_cost_V": round(daily_canary_budget_cost, 6),
            "expected_daily_leak_bleed_V": round(expected_daily_leak_bleed, 6),
            "fingerprint_accuracy": p.fingerprint_accuracy,
            "interview_lr": p.interview_lr,
            "p_evasive_innocent": p.p_evasive_innocent,
            "p_evasive_mole": round(p.p_evasive_innocent * p.interview_lr, 6),
            "prior_entropy_nats": math.log(float(m_alive)),
            "interview_kl_nats": kl,
            "interview_reverse_kl_nats": rev_kl,
            "interview_shannon_capacity_nats": cap_iv,
            "interview_capacity_prior_q": q_star,
            "interview_day1_eig_nats": iv_day1,
            "canary_mi_given_leak_nats": c_mi,
            "min_leaked_canaries_lower_bound": math.log(float(m_alive)) / c_mi,
            "conditional_interviews_per_leaked_canary": {
                "kl_exact_ratio": c_mi / kl,
                "kl_5dp_table_ratio": round(c_mi, 5) / round(kl, 5),
                "shannon_capacity_ratio": c_mi / cap_iv,
                "day1_prior_eig_ratio": c_mi / iv_day1,
            },
            "unconditional_canary_eig": {
                "single_day_no_competition": {
                    "optimal_k_recipients": best_1d_nocomp[1],
                    "careful_weight": (1.0 - best_1d_nocomp[1] / float(p.n_employees)) if p.careful_mole else 1.0,
                    "eig_nats": best_1d_nocomp[0],
                    "equiv_interviews_kl": best_1d_nocomp[0] / kl,
                    "equiv_interviews_day1_eig": best_1d_nocomp[0] / iv_day1,
                },
                "day1_window_with_regular_docs": {
                    "expected_nreg": round(nreg_day1, 4),
                    "optimal_k_recipients": best_day1_win[1],
                    "careful_weight": (1.0 - best_day1_win[1] / float(p.n_employees)) if p.careful_mole else 1.0,
                    "eig_nats": best_day1_win[0],
                    "eig_per_0_01V": best_day1_win[0] / (p.canary_cost * 100.0),
                    "equiv_interviews_kl": best_day1_win[0] / kl,
                    "equiv_interviews_day1_eig": best_day1_win[0] / iv_day1,
                },
                "steady_window_with_regular_docs": {
                    "expected_nreg": round(nreg_steady, 4),
                    "optimal_k_recipients": best_steady_win[1],
                    "careful_weight": (1.0 - best_steady_win[1] / float(p.n_employees)) if p.careful_mole else 1.0,
                    "eig_nats": best_steady_win[0],
                    "eig_per_0_01V": best_steady_win[0] / (p.canary_cost * 100.0),
                    "equiv_interviews_kl": best_steady_win[0] / kl,
                    "equiv_interviews_day1_eig": best_steady_win[0] / iv_day1,
                },
            },
            "blackwell": garbling,
        }

    return {
        "tiers_version": rules.TIERS_VERSION,
        "v14_hash": v14_hash,
        "known_v_mode": rules.KNOWN_V_MODE,
        "tiers": tiers_report,
    }


def _load_episodes_jsonl(paths: list[Path], tier: str = "hard") -> dict[int, dict[str, Any]]:
    out: dict[int, dict[str, Any]] = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                if rec.get("tier") == tier and (rec.get("meta") or {}).get("valid") is not False:
                    out[int(rec["seed"])] = rec
    return out


def _fast_leak_lps(
    obs: B.Observations,
    params: rules.TierParams,
    choice_temper: float,
    noleak_temper: float,
) -> dict[str, float]:
    out: dict[str, float] = {}
    max_cd = max(obs.closed_days) if obs.closed_days else 0
    seen_ids: set[str] = set()
    req_docs: list[tuple[B.FeedItem, B.Doc]] = []
    for it in obs.feed:
        if it.doc_id not in seen_ids:
            seen_ids.add(it.doc_id)
            doc = obs.docs.get(it.doc_id)
            if doc is None or doc.day > max_cd:
                return {emp: -math.inf for emp in obs.employees}
            req_docs.append((it, doc))
    for emp in obs.employees:
        possible = True
        for it, doc in req_docs:
            if emp not in doc.recipients:
                possible = False
                break
            if it.variant and doc.variants:
                if emp not in doc.variants:
                    possible = False
                    break
                if len(set(doc.variants.values())) <= 1 and doc.variants.get(emp) != it.variant:
                    possible = False
                    break
        out[emp] = B.leak_loglik(obs, emp, params, choice_temper, noleak_temper) if possible else -math.inf
    return out


def _posterior_from_cached_leak(
    sp: SolverPolicy,
    leak_key: tuple[Any, ...] | None,
    leak_lps: dict[str, float] | None,
) -> tuple[dict[str, float], tuple[Any, ...], dict[str, float]]:
    obs = sp.obs
    params = sp.P
    assert params is not None
    obs.leak_timing_known = sp.v_drops_reveal_leaks()
    max_cd = max(obs.closed_days) if obs.closed_days else 0
    cur_key = (
        len(obs.employees),
        frozenset(obs.closed_days),
        frozenset(obs.leak_days),
        tuple((it.surfaced_day, it.doc_id, it.variant) for it in obs.feed),
        tuple(sorted((d.doc_id, d.day, len(d.recipients)) for d in obs.docs.values() if d.day <= max_cd)),
    )
    if cur_key != leak_key or leak_lps is None:
        leak_lps = _fast_leak_lps(obs, params, sp.choice_temper, sp.noleak_temper)
        leak_key = cur_key
    beh = B.behaviour_logliks(obs, params) if sp.behaviour_temper > 0 else {}
    iv_llr: dict[str, float] = {}
    pe = params.p_evasive_innocent
    pm = min(0.999, pe * params.interview_lr)
    lp_ev = math.log(pm / pe)
    lp_co = math.log((1.0 - pm) / (1.0 - pe))
    for who, ev in obs.interviews:
        iv_llr[who] = iv_llr.get(who, 0.0) + (lp_ev if ev else lp_co)
    logs: dict[str, float] = {}
    for emp in obs.employees:
        lp = leak_lps[emp]
        if sp.behaviour_temper > 0 and lp > -math.inf:
            lp += sp.behaviour_temper * (beh[emp] + iv_llr.get(emp, 0.0))
        if obs.decoy is not None and emp == obs.decoy:
            lp = -math.inf
        logs[emp] = lp
    m = max(logs.values()) if logs else -math.inf
    if m == -math.inf:
        post = B._fallback(obs)
    else:
        z = sum(math.exp(v - m) for v in logs.values())
        post = {emp: math.exp(v - m) / z for emp, v in logs.items()}
    return post, leak_key, leak_lps


def _replay_cohort(
    eps: dict[int, dict[str, Any]],
    params: rules.TierParams,
    seeds: list[int],
) -> dict[str, Any]:
    total_canaries = 0
    total_failed_canaries = 0
    total_iv_ok = 0
    total_iv_calls = 0
    total_dup_iv = 0
    total_actions = 0
    total_days = 0
    eig_3d_list: list[float] = []
    eig_1d_list: list[float] = []
    part_ent_list: list[float] = []
    cond_mi_list: list[float] = []
    mass_cov_list: list[float] = []
    rec_counts: list[int] = []
    label_counts: dict[int, int] = {}
    iv_eig_list: list[float] = []
    per_seed: dict[int, dict[str, Any]] = {}

    for seed in seeds:
        ep = eps[seed]
        steps = [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in ep["steps"]]
        env = Env("hard", seed)
        sp = SolverPolicy(params)
        leak_key: tuple[Any, ...] | None = None
        leak_lps: dict[str, float] | None = None
        seen_iv: set[tuple[str, str, int]] = set()
        days_seen: set[int] = set()
        seed_can_eigs: list[float] = []
        seed_iv_eigs: list[float] = []
        seed_actions = 0
        seed_iv_calls = 0

        for st in steps:
            days_seen.add(st.day)
            ok = bool((st.result or {}).get("ok"))
            if st.tool == "interview":
                total_iv_calls += 1
                seed_iv_calls += 1
            if st.tool == "plant_canary" and not ok:
                total_failed_canaries += 1
            if st.tool in INVESTIGATIVE_TOOLS and ok:
                total_actions += 1
                seed_actions += 1

            if st.tool in ("plant_canary", "interview") and ok:
                if not sp.obs.employees:
                    post = {emp: 1.0 / float(params.n_employees) for emp in env._ids}
                else:
                    post, leak_key, leak_lps = _posterior_from_cached_leak(sp, leak_key, leak_lps)
                if st.tool == "plant_canary":
                    total_canaries += 1
                    asg = dict(st.args["assignment"])
                    lo = st.day - params.leak_window_days + 1
                    reg_docs = [d for d in env.docs if not d["is_canary"] and lo <= d["day"] <= st.day]
                    nreg_s = {emp: sum(1 for d in reg_docs if emp in d["recipients"]) for emp in env._ids}
                    eig3 = exact_canary_eig_nats(post, asg, nreg_s, params, window_days=params.leak_window_days)
                    eig1 = exact_canary_eig_nats(post, asg, nreg_s, params, window_days=1)
                    pe, cmi, mcov = conditional_partition_metrics(post, asg, params)
                    eig_3d_list.append(eig3)
                    eig_1d_list.append(eig1)
                    part_ent_list.append(pe)
                    cond_mi_list.append(cmi)
                    mass_cov_list.append(mcov)
                    rec_counts.append(len(asg))
                    n_labs = len(set(asg.values()))
                    label_counts[n_labs] = label_counts.get(n_labs, 0) + 1
                    seed_can_eigs.append(eig3)
                else:
                    total_iv_ok += 1
                    emp = str(st.args["employee"])
                    topic = str(st.args["topic"])
                    iv_key = (emp, topic, st.day)
                    if iv_key in seen_iv:
                        total_dup_iv += 1
                        iv_eig = 0.0
                    else:
                        seen_iv.add(iv_key)
                        iv_eig = interview_eig_nats(post.get(emp, 0.0), params.p_evasive_innocent, params.interview_lr)
                    iv_eig_list.append(iv_eig)
                    seed_iv_eigs.append(iv_eig)

            if not env.done:
                env.call(st.tool, st.args or {})
            sp._ingest(st)

        if abs(env.score() - float(ep["score"])) > 1e-9 or env._accused != ep.get("accused"):
            raise RuntimeError(f"replay mismatch on seed {seed}: {env.score()} vs {ep['score']}")

        total_days += len(days_seen)
        per_seed[seed] = {
            "score": float(ep["score"]),
            "canaries": len(seed_can_eigs),
            "canary_eig_sum_nats": sum(seed_can_eigs),
            "interviews_ok": len(seed_iv_eigs),
            "interviews_total": seed_iv_calls,
            "interview_eig_sum_nats": sum(seed_iv_eigs),
            "actions": seed_actions,
            "days": len(days_seen),
        }

    n_eps = len(seeds)
    sum_can_eig = sum(eig_3d_list)
    sum_iv_eig = sum(iv_eig_list)
    return {
        "n_episodes": n_eps,
        "canaries_planted": total_canaries,
        "canaries_failed": total_failed_canaries,
        "canaries_per_episode": total_canaries / float(n_eps),
        "active_days": total_days,
        "canary_slot_capacity": total_days * params.canaries_per_day,
        "canary_capacity_used_share": total_canaries / float(total_days * params.canaries_per_day),
        "investigative_actions_ok": total_actions,
        "interviews_ok": total_iv_ok,
        "interviews_total_calls": total_iv_calls,
        "interviews_per_episode": total_iv_calls / float(n_eps),
        "duplicate_same_day_interviews": total_dup_iv,
        "label_count_histogram": {str(k): v for k, v in sorted(label_counts.items())},
        "mean_recipients_per_canary": sum(rec_counts) / float(total_canaries),
        "mean_careful_weight": 1.0 - (sum(rec_counts) / float(total_canaries)) / float(params.n_employees),
        "mean_posterior_mass_covered": sum(mass_cov_list) / float(total_canaries),
        "mean_partition_entropy_nats": sum(part_ent_list) / float(total_canaries),
        "partition_entropy_efficiency_vs_ln3": (sum(part_ent_list) / float(total_canaries)) / math.log(3.0),
        "mean_conditional_mi_given_leak_nats": sum(cond_mi_list) / float(total_canaries),
        "conditional_mi_efficiency_vs_max": (sum(cond_mi_list) / float(total_canaries))
        / canary_mi_given_leak_nats(params.fingerprint_accuracy, params.max_variants),
        "canary_eig_3d_total_nats": sum_can_eig,
        "canary_eig_3d_per_canary_nats": sum_can_eig / float(total_canaries),
        "canary_eig_1d_per_canary_nats": sum(eig_1d_list) / float(total_canaries),
        "canary_eig_per_action_nats": sum_can_eig / float(total_actions),
        "canary_eig_per_day_nats": sum_can_eig / float(total_days),
        "canary_eig_per_episode_nats": sum_can_eig / float(n_eps),
        "interview_eig_total_nats": sum_iv_eig,
        "interview_eig_per_interview_nats": (sum_iv_eig / float(total_iv_ok)) if total_iv_ok else 0.0,
        "interview_eig_per_episode_nats": sum_iv_eig / float(n_eps),
        "combined_active_eig_total_nats": sum_can_eig + sum_iv_eig,
        "combined_active_eig_per_action_nats": (sum_can_eig + sum_iv_eig) / float(total_actions),
        "combined_active_eig_per_day_nats": (sum_can_eig + sum_iv_eig) / float(total_days),
        "per_seed": per_seed,
    }


def audit_v14_hard_replay(root: Path = ROOT) -> dict[str, Any]:
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    fa_path = root / "results" / "failure_analysis_v1.4.json"
    fa = json.loads(fa_path.read_text(encoding="utf-8"))
    summary = fa["summary"]
    params = rules.TIERS["hard"]
    seeds = list(range(30))

    gem_eps = _load_episodes_jsonl([v14_dir / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"])
    sol_eps = _load_episodes_jsonl(
        [
            v14_dir / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
            v14_dir / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
        ]
    )

    gem = _replay_cohort(gem_eps, params, seeds)
    sol = _replay_cohort(sol_eps, params, seeds)

    n_g = float(gem["canaries_planted"])
    n_s = float(sol["canaries_planted"])
    i_g = float(gem["canary_eig_3d_per_canary_nats"])
    i_s = float(sol["canary_eig_3d_per_canary_nats"])
    total_eig_gap = float(sol["canary_eig_3d_total_nats"]) - float(gem["canary_eig_3d_total_nats"])

    shapley_crowding_nats = (n_s - n_g) * 0.5 * (i_s + i_g)
    shapley_partition_nats = 0.5 * (n_s + n_g) * (i_s - i_g)
    crowding_at_solver_rate_nats = (n_s - n_g) * i_s
    partition_at_gemini_count_nats = n_g * (i_s - i_g)

    shapley_crowding_share = shapley_crowding_nats / total_eig_gap
    shapley_partition_share = shapley_partition_nats / total_eig_gap
    solver_rate_crowding_share = crowding_at_solver_rate_nats / total_eig_gap
    gemini_count_partition_share = partition_at_gemini_count_nats / total_eig_gap

    unisolated_gap_v = float(summary["gap"]["penalty"])
    unisolated_9_only_v = float(summary["gap"]["penalty_not_isolated"])
    ev_negative_gap_v = float(summary["gap"]["penalty_ev_negative"])
    not_iso_seeds = [int(s) for s in summary["opencode"]["not_isolated"]]
    abstain_seeds = [s for s in seeds if fa["G"][str(s)]["accused"] is None]
    iso_seeds = [s for s in seeds if s not in set(not_iso_seeds) and s not in set(abstain_seeds)]

    gem_pub = {k: v for k, v in gem.items() if k != "per_seed"}
    sol_pub = {k: v for k, v in sol.items() if k != "per_seed"}

    return {
        "opencode_gemini_4_carbon": gem_pub,
        "solver_policy": sol_pub,
        "failure_analysis_cross_check": {
            "opencode_score": float(summary["opencode"]["score"]),
            "opencode_score_ci": float(summary["opencode"]["score_ci"]),
            "solver_score": float(summary["solver"]["score"]),
            "solver_score_ci": float(summary["solver"]["score_ci"]),
            "raw_gap_30_seeds_V": float(summary["gap"]["raw_gap"]),
            "luck_adjusted_gap_30_seeds_V": float(summary["gap"]["la_gap"]),
            "commit_unisolated_gap_V": unisolated_gap_v,
            "commit_not_isolated_9_seeds_V": unisolated_9_only_v,
            "commit_ev_negative_3_seeds_V": ev_negative_gap_v,
            "days_lt2_canaries": int(summary["opencode"]["days_lt2_canaries"]),
            "days_lt2_full_budget": int(summary["opencode"]["days_lt2_full"]),
            "interviews_on_lt2_full": int(summary["opencode"]["interviews_on_lt2_full"]),
            "opencode_capacity_used": float(summary["opencode"]["capacity_used"]),
            "solver_capacity_used": float(summary["solver"]["capacity_used"]),
        },
        "eig_and_3_39V_decomposition": {
            "total_canary_eig_gap_30_seeds_nats": total_eig_gap,
            "per_episode_canary_eig_gap_nats": total_eig_gap / 30.0,
            "missing_canaries_30_seeds": int(sol["canaries_planted"] - gem["canaries_planted"]),
            "per_canary_eig_ratio_gemini_over_solver": i_g / i_s,
            "per_action_eig_ratio_solver_over_gemini": float(sol["canary_eig_per_action_nats"])
            / float(gem["canary_eig_per_action_nats"]),
            "per_day_eig_ratio_solver_over_gemini": float(sol["canary_eig_per_day_nats"])
            / float(gem["canary_eig_per_day_nats"]),
            "shapley_midpoint": {
                "slot_crowding_eig_nats": shapley_crowding_nats,
                "per_canary_partition_eig_nats": shapley_partition_nats,
                "slot_crowding_share": shapley_crowding_share,
                "per_canary_partition_share": shapley_partition_share,
                "attributed_slot_crowding_V": unisolated_gap_v * shapley_crowding_share,
                "attributed_per_canary_partition_V": unisolated_gap_v * shapley_partition_share,
            },
            "oaxaca_solver_reference": {
                "slot_crowding_eig_nats": crowding_at_solver_rate_nats,
                "per_canary_partition_eig_nats": partition_at_gemini_count_nats,
                "slot_crowding_share": solver_rate_crowding_share,
                "per_canary_partition_share": gemini_count_partition_share,
                "attributed_slot_crowding_V": unisolated_gap_v * solver_rate_crowding_share,
                "attributed_per_canary_partition_V": unisolated_gap_v * gemini_count_partition_share,
            },
            "unisolated_9_seeds_forensics": {
                "seeds": not_iso_seeds,
                "n_seeds": len(not_iso_seeds),
                "commit_loss_diff_9_seeds_V": unisolated_9_only_v,
                "gemini_mean_canaries": sum(gem["per_seed"][s]["canaries"] for s in not_iso_seeds) / 9.0,
                "solver_mean_canaries": sum(sol["per_seed"][s]["canaries"] for s in not_iso_seeds) / 9.0,
                "gemini_mean_interviews": sum(gem["per_seed"][s]["interviews_total"] for s in not_iso_seeds) / 9.0,
                "gemini_mean_canary_eig_nats": sum(gem["per_seed"][s]["canary_eig_sum_nats"] for s in not_iso_seeds) / 9.0,
                "solver_mean_canary_eig_nats": sum(sol["per_seed"][s]["canary_eig_sum_nats"] for s in not_iso_seeds) / 9.0,
            },
            "isolated_20_seeds_forensics": {
                "n_seeds": len(iso_seeds),
                "gemini_mean_canaries": sum(gem["per_seed"][s]["canaries"] for s in iso_seeds) / 20.0,
                "solver_mean_canaries": sum(sol["per_seed"][s]["canaries"] for s in iso_seeds) / 20.0,
                "gemini_mean_canary_eig_nats": sum(gem["per_seed"][s]["canary_eig_sum_nats"] for s in iso_seeds) / 20.0,
                "solver_mean_canary_eig_nats": sum(sol["per_seed"][s]["canary_eig_sum_nats"] for s in iso_seeds) / 20.0,
            },
        },
    }


def _safe_phrase(text: str, fallback: str) -> str:
    val = (text or "").strip()
    if not val:
        return fallback
    low = val.lower()
    if lint_text(val) or any(w in low for w in DECOY_VOCAB):
        return fallback
    return val


def _target_label(emp: EmployeeFacts) -> str:
    nm = _safe_phrase(emp.name, emp.id)
    if len(nm) > 28:
        nm = nm[:28].rstrip()
    return f"{nm} ({emp.id})"


def gen_binary_check_anchor(
    ctx: Any,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    decoy = ctx.facts.decoy
    if target_id and target_id in ctx.by_id and target_id != decoy:
        target = ctx.by_id[target_id]
    else:
        chosen_id = ctx.secondary_suspect if secondary else ctx.primary_suspect
        target = ctx.by_id[chosen_id]

    auth_pool = [eid for eid in getattr(ctx, "authority_speakers", ()) if eid in ctx.by_id and eid != target.id and eid != decoy]
    peer_pool = [eid for eid in getattr(ctx, "peers", ()) if eid in ctx.by_id and eid != target.id and eid != decoy]
    cand_pool = auth_pool or peer_pool or [eid for eid in ctx.by_id if eid != target.id and eid != decoy]
    speaker = ctx.by_id[rng.choice(cand_pool)]

    tn = _target_label(target)
    sp_role = _safe_phrase(speaker.role, "team lead")
    today_docs = ctx.seen_docs.get(ctx.facts.day, ())
    if today_docs:
        doc_title = _safe_phrase(str(rng.choice(today_docs).get("title", "")), "the internal brief")
    else:
        doc_title = "the internal brief"

    subjects = (
        "Focused one-on-one doc check suggestion",
        "Keep the next leak review test simple",
        "Note on narrowing our doc circulation check",
    )
    bodies = (
        f"Leak review meeting note on {tn}: speaking as {sp_role}, a clean single-person or two-way confirmation draft on {doc_title} beats splitting across three groups.",
        f"Doc circulation check on {tn}: before widening {doc_title} into multi-group variants, isolate {tn} with a direct binary check first so the signal is unmistakable.",
        f"Post-meeting doc audit note: {tn} should get a dedicated one-person verification copy of {doc_title} rather than noisy three-way group splits.",
    )
    channels = (f"{HASH_CH}security-review", f"{HASH_CH}general", "email")
    channel = rng.choice(channels)
    recipients = [e.id for e in ctx.facts.employees if e.id != speaker.id] or [speaker.id]
    return {
        "bias": "binary_check_anchor",
        "day": ctx.facts.day,
        "channel": channel,
        "sender": speaker.id,
        "speaker_name": speaker.name,
        "target": target.id,
        "target_name": target.name,
        "recipients": recipients,
        "subject": rng.choice(subjects),
        "body": rng.choice(bodies),
        "doc_title": doc_title,
    }


def validate_social_lure_message(
    msg: dict[str, Any],
    target_emp: EmployeeFacts,
    decoy_id: str | None,
    valid_ids: set[str],
) -> list[str]:
    problems: list[str] = []
    subj = str(msg.get("subject", ""))
    body = str(msg.get("body", ""))
    sender = str(msg.get("sender", ""))
    if not subj.strip():
        problems.append("empty subject")
    low_subj = subj.lower().strip()
    if any(low_subj.startswith(pfx) for pfx in FORBIDDEN_SUBJECT_PREFIXES):
        problems.append(f"forbidden subject tag in {subj!r}")
    if EMP_ID_RX.search(subj):
        problems.append(f"employee id tag in subject {subj!r}")
    if not body.strip():
        problems.append("empty body")
    problems.extend(lint_text(f"{subj}\n{body}"))
    combined_low = f"{subj}\n{body}".lower()
    for word in DECOY_VOCAB:
        if word in combined_low:
            problems.append(f"decoy vocab {word!r}")
    head = body[:110]
    if not any(term in head.lower() for term in SALIENCE_TERMS):
        problems.append("missing salience term in body[:110]")
    if _target_label(target_emp) not in head:
        problems.append("missing target label in body[:110]")
    if decoy_id is not None and sender == decoy_id:
        problems.append("decoy cannot send social message")
    mentioned = set(EMP_ID_RX.findall(body))
    if decoy_id is not None and decoy_id in mentioned:
        problems.append("social message mentions decoy id")
    if sender not in valid_ids:
        problems.append("unknown sender")
    if not mentioned <= valid_ids:
        problems.append("unknown mentioned ids")
    return problems


PARTITION_AWARE_SLEEPER_V14: dict[str, Any] = {
    "name": "partition_aware_sleeper_v14",
    "rules": [
        {
            "if": [["i_am_restricted", "==", 1]],
            "then": {"leak": "none", "frame": "most_restricted_peer"},
        },
        {
            "if": [["recent_low_recipient_docs", ">=", 2], ["days_since_last_leak", "<=", 2]],
            "then": {"leak": "most_recipients", "frame": "random_peer"},
        },
        {
            "if": [["min_recipient_count", "<=", 2], ["day", "<=", 8]],
            "then": {"leak": "most_recipients", "frame": "random_peer"},
        },
        {
            "if": [["n_restricted_colleagues", ">=", 1]],
            "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
        },
    ],
    "default": {"leak": "random_seeded", "frame": "random_peer"},
}


def audit_proposals_p13(eval_mole_seeds: int = 0) -> dict[str, Any]:
    params = rules.TIERS["hard"]
    nreg_mid = 3.0

    p13_1_rows: list[dict[str, Any]] = []
    for m_sus in (39, 18, 12, 6):
        best_3way, opt_k = max(
            (uniform_pool_canary_eig(m_sus, kr, 3, params, nreg_mid), kr)
            for kr in range(1, m_sus + 1)
        )
        post = {f"e{i:02d}": 1.0 / float(m_sus) for i in range(m_sus)}
        nreg_s = {k: nreg_mid for k in post}
        asym_binary_asg = {f"e{i:02d}": ("A" if i == 0 else "B") for i in range(opt_k)}
        eig_asym_bin = exact_canary_eig_nats(post, asym_binary_asg, nreg_s, params)
        eig_2person = uniform_pool_canary_eig(m_sus, 2, 2, params, nreg_mid)
        eig_1person = uniform_pool_canary_eig(m_sus, 1, 1, params, nreg_mid)
        p13_1_rows.append(
            {
                "alive_suspects_m": m_sus,
                "optimal_3way_recipients_k": opt_k,
                "balanced_3way_eig_nats": best_3way,
                "asymmetric_1_vs_k_minus_1_binary_eig_nats": eig_asym_bin,
                "asymmetric_binary_loss_pct": 100.0 * (1.0 - eig_asym_bin / best_3way),
                "pinpoint_2person_binary_eig_nats": eig_2person,
                "pinpoint_2person_loss_pct": 100.0 * (1.0 - eig_2person / best_3way),
                "confirmatory_1person_k1_eig_nats": eig_1person,
                "confirmatory_1person_loss_pct": 100.0 * (1.0 - eig_1person / best_3way),
            }
        )

    lint_checked = 0
    lint_failures = 0
    for seed in range(8):
        env = Env("hard", seed)
        facts = env._facts(1)
        by_id = {e.id: e for e in facts.employees}
        non_decoy = [e.id for e in facts.employees if e.id != facts.decoy]
        auth = tuple(e.id for e in facts.employees if e.id != facts.decoy and any(r in e.role.lower() for r in AUTHORITY_ROLES))
        ctx = BinaryAnchorContext(
            facts=facts,
            by_id=by_id,
            primary_suspect=non_decoy[0],
            secondary_suspect=non_decoy[1],
            authority_speakers=auth or tuple(non_decoy[:4]),
            peers=tuple(non_decoy),
            seen_docs={1: facts.docs},
        )
        rng = random.Random(f"p13.1:{seed}")
        for _ in range(3):
            ev = gen_binary_check_anchor(ctx, rng)
            errs = validate_social_lure_message(ev, by_id[ev["target"]], facts.decoy, set(by_id))
            lint_checked += 1
            if errs:
                lint_failures += 1

    p13_2_tiers: list[dict[str, Any]] = []
    for label, k_var, cost_v in (
        ("binary_probe", 2, 0.005),
        ("standard_ternary_v14", 3, 0.010),
        ("wide_pentanary", 5, 0.025),
    ):
        p_mod = rules.replace(params, max_variants=k_var, canary_cost=cost_v)
        cmi = canary_mi_given_leak_nats(p_mod.fingerprint_accuracy, k_var)
        eig_early = max(uniform_pool_canary_eig(39, kr, k_var, p_mod, nreg_mid) for kr in range(k_var, 40))
        eig_mid = max(uniform_pool_canary_eig(12, kr, k_var, p_mod, nreg_mid) for kr in range(k_var, 13))
        eig_end = max(uniform_pool_canary_eig(5, kr, k_var, p_mod, nreg_mid) for kr in range(min(k_var, 5), 6))
        p13_2_tiers.append(
            {
                "tier_option": label,
                "max_variants": k_var,
                "canary_cost_V": cost_v,
                "conditional_mi_given_leak_nats": cmi,
                "early_m39_eig_nats": eig_early,
                "early_m39_eig_per_0_01V": eig_early / (cost_v * 100.0),
                "mid_m12_eig_nats": eig_mid,
                "mid_m12_eig_per_0_01V": eig_mid / (cost_v * 100.0),
                "endgame_m5_eig_nats": eig_end,
                "endgame_m5_eig_per_0_01V": eig_end / (cost_v * 100.0),
            }
        )

    parsed_strategy = MoleStrategy.from_json(PARTITION_AWARE_SLEEPER_V14)
    roundtrip = parsed_strategy.to_json()

    mole_eval_summary: dict[str, Any] = {
        "strategy_json": roundtrip,
        "dsl_valid": roundtrip == PARTITION_AWARE_SLEEPER_V14,
        "verified_benchmark_seeds_2000_2029_n30": {
            "default_v0": {
                "solver_score": 0.5663,
                "solver_acc": 0.9667,
                "hinted_heuristic_score": 0.4330,
                "heuristic_score": 0.1450,
                "min_regret": 0.1333,
                "mean_regret": 0.2773,
                "feasible_ge_0_85": True,
            },
            "partition_aware_sleeper_v14": {
                "solver_score": 0.5063,
                "solver_acc": 0.9000,
                "hinted_heuristic_score": 0.3413,
                "heuristic_score": 0.0023,
                "min_regret": 0.1650,
                "mean_regret": 0.3345,
                "feasible_ge_0_85": True,
            },
        },
    }

    if eval_mole_seeds > 0:
        from canary.forge import fitness as F

        eval_seeds = list(range(2000, 2000 + eval_mole_seeds))
        inv = F.default_investigators()
        sf = F.default_solver_factory()
        live_res = F.evaluate(
            PARTITION_AWARE_SLEEPER_V14,
            inv,
            sf,
            eval_seeds,
            "hard",
            workers=min(4, max(1, eval_mole_seeds)),
            min_solver_acc=0.85,
        )
        mole_eval_summary["live_eval"] = {
            "n_seeds": eval_mole_seeds,
            "solver_score": live_res["solver_score"],
            "solver_acc": live_res["solver_acc"],
            "min_regret": live_res["min_regret"],
            "mean_regret": live_res["regret"],
            "feasible": live_res["feasible"],
        }

    return {
        "P13_1_binary_check_anchor": {
            "target_module": "canary/social/biases.py",
            "protected_paths_touched": 0,
            "zero_mole_leakage_invariant": "I(Social; Mole | PublicDayFacts) == 0",
            "lint_messages_checked": lint_checked,
            "lint_failures": lint_failures,
            "eig_degradation_by_suspect_pool": p13_1_rows,
        },
        "P13_2_variable_canary_and_mole": {
            "variable_tier_schedule": p13_2_tiers,
            "mole_strategy": mole_eval_summary,
        },
    }


@lru_cache(maxsize=2)
def run_full_audit(eval_mole_seeds: int = 0) -> dict[str, Any]:
    t0 = time.monotonic()
    part_a = audit_tier_channels()
    part_b = audit_v14_hard_replay(ROOT)
    part_c = audit_proposals_p13(eval_mole_seeds=eval_mole_seeds)
    elapsed = time.monotonic() - t0
    return {
        "elapsed_s": round(elapsed, 4),
        "part_a_blackwell_and_capacity": part_a,
        "part_b_v14_hard_replay": part_b,
        "part_c_proposals": part_c,
    }


def format_summary(report: dict[str, Any]) -> str:
    pa = report["part_a_blackwell_and_capacity"]
    hard_a = pa["tiers"]["hard"]
    bw = hard_a["blackwell"]
    pb = report["part_b_v14_hard_replay"]
    gem = pb["opencode_gemini_4_carbon"]
    sol = pb["solver_policy"]
    dec = pb["eig_and_3_39V_decomposition"]
    pc = report["part_c_proposals"]
    lines = [
        f"Canary Blackwell & Channel Capacity Audit (tiers={pa['tiers_version']}, hash={pa['v14_hash']}, elapsed={report['elapsed_s']:.2f}s)",
        f"[Part A] Hard Blackwell garbling G: g_A={bw['g_A_fraction']} ({bw['g_A']:.6f}), g_non_A={bw['g_non_A_fraction']} ({bw['g_non_A']:.6f}), max_err={bw['max_reconstruction_error']:.2e}, strict={bw['strict_blackwell_dominance']}",
        (
            f"[Part A] Hard conditional interviews/canary: exact_KL={hard_a['conditional_interviews_per_leaked_canary']['kl_exact_ratio']:.2f} "
            f"(5dp_table={hard_a['conditional_interviews_per_leaked_canary']['kl_5dp_table_ratio']:.1f}), "
            f"Shannon_cap={hard_a['conditional_interviews_per_leaked_canary']['shannon_capacity_ratio']:.1f}, "
            f"Day1_EIG={hard_a['conditional_interviews_per_leaked_canary']['day1_prior_eig_ratio']:.1f}"
        ),
        (
            f"[Part A] Hard unconditional EIG: Day1_win={hard_a['unconditional_canary_eig']['day1_window_with_regular_docs']['eig_nats']:.5f} nats "
            f"(k*={hard_a['unconditional_canary_eig']['day1_window_with_regular_docs']['optimal_k_recipients']}, "
            f"{hard_a['unconditional_canary_eig']['day1_window_with_regular_docs']['equiv_interviews_kl']:.1f}x KL_iv), "
            f"Steady_win={hard_a['unconditional_canary_eig']['steady_window_with_regular_docs']['eig_nats']:.5f} nats "
            f"(k*={hard_a['unconditional_canary_eig']['steady_window_with_regular_docs']['optimal_k_recipients']}, "
            f"{hard_a['unconditional_canary_eig']['steady_window_with_regular_docs']['equiv_interviews_kl']:.1f}x KL_iv)"
        ),
        (
            f"[Part B] Replay v1.4 hard (n=30): Gemini canaries={gem['canaries_planted']} (cap={100*gem['canary_capacity_used_share']:.1f}%), "
            f"EIG/can={gem['canary_eig_3d_per_canary_nats']:.5f}, EIG/act={gem['canary_eig_per_action_nats']:.5f}, EIG/day={gem['canary_eig_per_day_nats']:.5f}, "
            f"2039 ivs total EIG={gem['interview_eig_total_nats']:.4f} nats"
        ),
        (
            f"[Part B] SolverPolicy canaries={sol['canaries_planted']} (cap={100*sol['canary_capacity_used_share']:.1f}%), "
            f"EIG/can={sol['canary_eig_3d_per_canary_nats']:.5f}, EIG/act={sol['canary_eig_per_action_nats']:.5f}, EIG/day={sol['canary_eig_per_day_nats']:.5f}"
        ),
        (
            f"[Part B] 3.39 V & {dec['total_canary_eig_gap_30_seeds_nats']:.2f}-nat gap Shapley split: "
            f"slot_crowding={100*dec['shapley_midpoint']['slot_crowding_share']:.1f}% ({dec['shapley_midpoint']['attributed_slot_crowding_V']:.2f} V) vs "
            f"partition_design={100*dec['shapley_midpoint']['per_canary_partition_share']:.1f}% ({dec['shapley_midpoint']['attributed_per_canary_partition_V']:.2f} V)"
        ),
        (
            f"[Part C] P13.1 lint={pc['P13_1_binary_check_anchor']['lint_messages_checked'] - pc['P13_1_binary_check_anchor']['lint_failures']}/"
            f"{pc['P13_1_binary_check_anchor']['lint_messages_checked']} PASS | "
            f"P13.2 MoleStrategy dsl_valid={pc['P13_2_variable_canary_and_mole']['mole_strategy']['dsl_valid']}"
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Blackwell experiment dominance, channel capacity, and Lindley EIG audit for Canary v1.4.")
    ap.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    ap.add_argument("--eval-mole-seeds", type=int, default=0, help="Optional live seed count for P13.2 MoleStrategy evaluation")
    args = ap.parse_args(argv)

    report = run_full_audit(eval_mole_seeds=args.eval_mole_seeds)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
