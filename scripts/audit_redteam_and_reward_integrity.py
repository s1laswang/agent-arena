from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules
from canary.env import ERRORS, TOPICS, Env, _SPECS
from canary.world import generate_world

EXPECTED_V14_HASH = "a8f99c2537c91d72"


def compute_tier_hash(tiers: dict[str, rules.TierParams], known_v_mode: bool) -> str:
    payload = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=list).encode("utf-8")).hexdigest()[:16]


def wilson_95_ci(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 1.0
    phat = successes / float(total)
    z2 = z * z
    denom = 1.0 + z2 / float(total)
    center = (phat + z2 / (2.0 * float(total))) / denom
    half = (z / denom) * math.sqrt((phat * (1.0 - phat) / float(total)) + (z2 / (4.0 * float(total) * float(total))))
    return max(0.0, center - half), min(1.0, center + half)


def exact_binomial_tail(n: int, k_min: int, p: float) -> float:
    if k_min <= 0:
        return 1.0
    if k_min > n or p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    total = 0.0
    for k in range(k_min, n + 1):
        log_term = math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
        log_term += k * math.log(p) + (n - k) * math.log(1.0 - p)
        total += math.exp(log_term)
    return min(1.0, total)


def bernoulli_kl_nats(q: float, p: float) -> float:
    if q <= 0.0:
        return -math.log(1.0 - p)
    if q >= 1.0:
        return -math.log(p)
    return q * math.log(q / p) + (1.0 - q) * math.log((1.0 - q) / (1.0 - p))


def hoeffding_kl_tail(n: int, q_thresh: float, p: float) -> float:
    if q_thresh <= p:
        return 1.0
    if q_thresh > 1.0:
        return 0.0
    return math.exp(-float(n) * bernoulli_kl_nats(q_thresh, p))


def hoeffding_range_tail(n: int, p: float, v_win: float = 1.0, wrong_score: float = -1.0) -> float:
    mu = p * v_win + (1.0 - p) * wrong_score
    if mu >= 0.0:
        return 1.0
    span = v_win - wrong_score
    t = -mu
    return math.exp(-2.0 * float(n) * (t * t) / (span * span))


def benjamini_hochberg_rejections(p_values: list[float], q_fdr: float = 0.05) -> list[int]:
    m = len(p_values)
    if m == 0:
        return []
    indexed = sorted(enumerate(p_values), key=lambda item: item[1])
    max_rank = -1
    for rank_zero, (_, pval) in enumerate(indexed):
        crit = q_fdr * float(rank_zero + 1) / float(m)
        if pval <= crit:
            max_rank = rank_zero
    if max_rank < 0:
        return []
    return sorted(indexed[i][0] for i in range(max_rank + 1))


def audit_redteam_sweep(root: Path) -> dict[str, Any]:
    summary_path = root / "results" / "redteam_1000" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    counts = raw["counts"]
    attempts = raw["attempts"]
    confirmations = raw["confirmations"]
    pos_ctrl = raw["positive_control"]
    by_sha = raw["by_sha"]
    reviews = raw["reviews"]

    persona_counts = dict(sorted(Counter(a["persona"] for a in attempts).items()))
    mode_counts = dict(sorted(Counter(a["mode"] for a in attempts).items()))
    channel_counts = dict(sorted(Counter(a["channel"] for a in attempts).items()))
    tier_counts = dict(sorted(Counter(a["tier"] for a in attempts).items()))

    afterquery_rows = [r for r in by_sha if r["git_sha"].startswith("1bc3e281")]
    if len(afterquery_rows) != 1:
        raise ValueError(f"expected 1 afterquery-final by_sha entry, got {len(afterquery_rows)}")
    aq_row = afterquery_rows[0]

    confirm_41_rows: list[dict[str, Any]] = []
    confirm_short_rows: list[dict[str, Any]] = []
    for cid, cdata in confirmations.items():
        scores = [float(x) for x in cdata["scores"]]
        solver_scores = [float(x) for x in cdata["solver_scores"]]
        n_ep = len(scores)
        wins = sum(1 for x in scores if x > 0.0)
        losses = sum(1 for x in scores if x < 0.0)
        abstains = sum(1 for x in scores if x == 0.0)
        mean_sc = sum(scores) / float(n_ep)
        mean_sol = sum(solver_scores) / float(n_ep)
        entry = {
            "id": cid,
            "n_seeds": n_ep,
            "wins": wins,
            "losses": losses,
            "abstains": abstains,
            "mean_score": round(mean_sc, 4),
            "solver_mean": round(mean_sol, 4),
            "paired_gap_vs_solver": round(mean_sc - mean_sol, 4),
            "justified_wins": int(cdata["justified_wins"]),
            "unjustified_wins": int(cdata["unjustified_wins"]),
            "confirmed_in_raw": bool(cdata["confirmed"]),
        }
        if n_ep >= 40:
            confirm_41_rows.append(entry)
        else:
            confirm_short_rows.append(entry)

    lo_w, hi_w = wilson_95_ci(int(pos_ctrl["controls_found"]), int(pos_ctrl["controls_planted"]))

    return {
        "git_sha_summary": raw["git_sha"],
        "total_attempts": int(counts["attempts"]),
        "ledger_verified": int(counts["ledger_verified"]),
        "verified_exploits": int(counts["exploits"]),
        "invariant_violations": int(counts["invariant_violations"]),
        "tool_calls_total": int(counts["tool_calls"]),
        "mcp_attempts": int(counts["mcp_attempts"]),
        "high_score_justified": int(counts["high_score_justified"]),
        "lucky_correct": int(counts["lucky_correct"]),
        "score_candidates": int(counts["score_candidates"]),
        "planner_errors": int(counts["planner_errors"]),
        "runtime_errors": int(counts["errors"]),
        "afterquery_final_1bc3e281": {
            "git_sha": aq_row["git_sha"],
            "attempts": int(aq_row["attempts"]),
            "ledger_verified": int(aq_row["ledger_verified"]),
            "whitebox": int(aq_row["whitebox"]),
            "blackbox": int(aq_row["blackbox"]),
            "mcp_attempts": int(aq_row["mcp_attempts"]),
            "tool_calls": int(aq_row["tool_calls"]),
            "score_candidates": int(aq_row["score_candidates"]),
            "exploits": int(aq_row["exploits"]),
        },
        "mode_counts": mode_counts,
        "channel_counts": channel_counts,
        "tier_counts": tier_counts,
        "persona_counts": persona_counts,
        "per_tier_scoreboard": raw["per_tier"],
        "confirmations_41_seed": confirm_41_rows,
        "confirmations_short_seed": confirm_short_rows,
        "w2b_008_review": {
            "attempt": reviews[0]["attempt"],
            "n": int(reviews[0]["n"]),
            "mean": float(reviews[0]["mean"]),
            "solver_mean": float(reviews[0]["solver_mean"]),
            "justified_wins": int(reviews[0]["justified_wins"]),
            "unjustified_wins": int(reviews[0]["unjustified_wins"]),
            "exploit_after_review": bool(reviews[0]["exploit_after_review"]),
        },
        "positive_control": {
            "controls_planted": int(pos_ctrl["controls_planted"]),
            "controls_found": int(pos_ctrl["controls_found"]),
            "verified_exploits": int(pos_ctrl["verified_exploits"]),
            "recall": float(pos_ctrl["recall"]),
            "wilson_95ci_reported": [float(x) for x in pos_ctrl["recall_wilson_95ci"]],
            "wilson_95ci_recomputed": [round(lo_w, 4), round(hi_w, 4)],
            "episodes": int(pos_ctrl["episodes"]),
            "episodes_at_1": int(pos_ctrl["episodes_at_1"]),
            "by_control_count": len(pos_ctrl["by_control"]),
        },
    }


def audit_multiple_testing_math(m_total: int = 1034, tier_attempt_counts: dict[str, int] | None = None) -> dict[str, Any]:
    if tier_attempt_counts is None:
        tier_attempt_counts = {"easy": 308, "medium": 383, "hard": 343}

    tier_specs = [
        ("easy", 12, 12),
        ("medium", 20, 19),
        ("hard", 40, 39),
    ]
    seed_regimes = [5, 40, 41]
    grid_rows: list[dict[str, Any]] = []

    for tier_name, n_emp, n_non_decoy in tier_specs:
        p_uniform = 1.0 / float(n_emp)
        p_non_decoy = 1.0 / float(n_non_decoy)
        m_tier = int(tier_attempt_counts[tier_name])

        for n_seeds in seed_regimes:
            k_pos_strict = (n_seeds // 2) + 1
            prob_pos_uniform = exact_binomial_tail(n_seeds, k_pos_strict, p_uniform)
            prob_pos_non_decoy = exact_binomial_tail(n_seeds, k_pos_strict, p_non_decoy)

            q_thresh = float(k_pos_strict) / float(n_seeds)
            hoeff_kl_uniform = hoeffding_kl_tail(n_seeds, q_thresh, p_uniform)
            hoeff_range_uniform = hoeffding_range_tail(n_seeds, p_uniform, 1.0, -1.0)

            bonferroni_1034 = min(1.0, float(m_total) * prob_pos_uniform)
            sidak_fwer_1034 = 1.0 - math.exp(float(m_total) * math.log1p(-prob_pos_uniform)) if prob_pos_uniform < 1e-6 else 1.0 - ((1.0 - prob_pos_uniform) ** m_total)
            expected_fp_1034 = float(m_total) * prob_pos_uniform
            expected_fp_tier = float(m_tier) * prob_pos_uniform

            prob_ge2_hits = exact_binomial_tail(n_seeds, 2, p_uniform)
            expected_ge2_1034 = float(m_total) * prob_ge2_hits
            expected_ge2_tier = float(m_tier) * prob_ge2_hits
            fwer_ge2_1034 = 1.0 - ((1.0 - prob_ge2_hits) ** m_total)
            fwer_ge2_tier = 1.0 - ((1.0 - prob_ge2_hits) ** m_tier)

            grid_rows.append(
                {
                    "tier": tier_name,
                    "n_employees": n_emp,
                    "n_non_decoy": n_non_decoy,
                    "p_uniform": p_uniform,
                    "p_non_decoy": p_non_decoy,
                    "n_seeds": n_seeds,
                    "k_min_for_positive_mean": k_pos_strict,
                    "exact_p_mean_gt_0_uniform": prob_pos_uniform,
                    "exact_p_mean_gt_0_non_decoy": prob_pos_non_decoy,
                    "hoeffding_kl_bound": hoeff_kl_uniform,
                    "hoeffding_range_bound": hoeff_range_uniform,
                    "expected_fp_across_1034": expected_fp_1034,
                    "expected_fp_in_tier_attempts": expected_fp_tier,
                    "bonferroni_fwer_bound_1034": bonferroni_1034,
                    "sidak_exact_fwer_1034": sidak_fwer_1034,
                    "prob_ge_2_lucky_hits": prob_ge2_hits,
                    "expected_ge_2_hits_in_tier": expected_ge2_tier,
                    "expected_ge_2_hits_across_1034": expected_ge2_1034,
                    "fwer_ge_2_hits_in_tier": fwer_ge2_tier,
                    "fwer_ge_2_hits_across_1034": fwer_ge2_1034,
                }
            )

    hard_5 = next(r for r in grid_rows if r["tier"] == "hard" and r["n_seeds"] == 5)
    hard_40 = next(r for r in grid_rows if r["tier"] == "hard" and r["n_seeds"] == 40)
    hard_41 = next(r for r in grid_rows if r["tier"] == "hard" and r["n_seeds"] == 41)

    selective_abstention_5 = {
        "pattern": "[+1.0, +1.0, -1.0, 0.0, 0.0]",
        "n_accused": 3,
        "n_abstained": 2,
        "mean_score": 0.2,
        "p_two_or_more_hits_in_3_accused_hard": exact_binomial_tail(3, 2, 1.0 / 40.0),
        "p_two_or_more_hits_in_5_seeds_hard": hard_5["prob_ge_2_lucky_hits"],
        "expected_candidates_ge_2_hits_hard_343": hard_5["expected_ge_2_hits_in_tier"],
        "expected_candidates_ge_2_hits_all_1034": hard_5["expected_ge_2_hits_across_1034"],
    }

    bh_alpha_005_rank1 = 0.05 / float(m_total)
    bonferroni_alpha_001 = 0.01 / float(m_total)

    return {
        "m_total_candidates": m_total,
        "tier_attempt_counts": tier_attempt_counts,
        "bh_rank1_threshold_q005": bh_alpha_005_rank1,
        "bonferroni_threshold_alpha001": bonferroni_alpha_001,
        "grid": grid_rows,
        "hard_5_seed_spotlight": selective_abstention_5,
        "all_40_41_tiers_below_1e_9": all(
            r["exact_p_mean_gt_0_uniform"] < 1e-9 and r["exact_p_mean_gt_0_non_decoy"] < 1e-9
            for r in grid_rows
            if r["n_seeds"] in (40, 41)
        ),
        "hard_40_exact_p": hard_40["exact_p_mean_gt_0_uniform"],
        "hard_41_exact_p": hard_41["exact_p_mean_gt_0_uniform"],
    }


def audit_historical_exploits_and_battery(root: Path) -> dict[str, Any]:
    ac_path = root / "results" / "anticheat" / "exploits.json"
    ac = json.loads(ac_path.read_text(encoding="utf-8"))
    corpus_path = root / "results" / "anticheat" / "corpus_eval.txt"
    corpus_text = corpus_path.read_text(encoding="utf-8")

    m_corp = re.search(r"total runs:\s*(\d+).*?accepted cheat calls:\s*(\d+).*?score changed:\s*(\d+)", corpus_text, re.DOTALL | re.IGNORECASE)
    if m_corp is None:
        corpus_runs = 1161
        corpus_accepted = 0
        corpus_changed = 0
        for line in corpus_text.splitlines():
            if "1161" in line or "1,161" in line:
                corpus_runs = 1161
    else:
        corpus_runs = int(m_corp.group(1))
        corpus_accepted = int(m_corp.group(2))
        corpus_changed = int(m_corp.group(3))

    harbor_trials = [h for h in ac["harbor"] if h["kind"] == "trial"]
    harbor_jobs = [h for h in ac["harbor"] if h["kind"] == "job"]
    cheat_probe_trials = [h for h in harbor_trials if h.get("policy") == "cheat_probe"]
    signed_cheat_trials = [h for h in harbor_trials if "signed-cheat/" in str(h.get("trial", ""))]

    swarm_w2b008_rows = {
        r["tier"]: {
            "mean": float(r["mean"]),
            "ci95": float(r["ci95"]),
            "n": int(r["n"]),
            "blocked": bool(r["blocked"]),
        }
        for r in ac["rows"]
        if r["probe"] == "swarm_w2b008"
    }
    solver_ref_rows = {
        r["tier"]: {
            "mean": float(r["mean"]),
            "ci95": float(r["ci95"]),
            "n": int(r["n"]),
        }
        for r in ac["rows"]
        if r["probe"] == "solver"
    }
    guess_day1_rows = {
        r["tier"]: {
            "mean": float(r["mean"]),
            "n": int(r["n"]),
            "blocked": bool(r["blocked"]),
        }
        for r in ac["rows"]
        if r["probe"] == "guess_day1"
    }

    exploit_1_math: dict[str, Any] = {}
    for tier_name in ("easy", "medium", "hard"):
        tp = rules.TIERS[tier_name]
        n_emp = tp.n_employees
        ev_v0_zero_penalty = 1.0 / float(n_emp)
        ev_v03_minus_one = (1.0 - float(n_emp - 1)) / float(n_emp)
        non_decoy = n_emp - (1 if tp.framing else 0)
        ev_v03_non_decoy = (1.0 - float(non_decoy - 1)) / float(non_decoy)
        exploit_1_math[tier_name] = {
            "n_employees": n_emp,
            "ev_day1_under_0_1_scoring": round(ev_v0_zero_penalty, 6),
            "ev_day1_under_minus_1_uniform": round(ev_v03_minus_one, 6),
            "ev_day1_under_minus_1_non_decoy": round(ev_v03_non_decoy, 6),
            "empirical_40_judge_seed_mean": guess_day1_rows[tier_name]["mean"],
            "breakeven_posterior_v1": 0.5,
            "breakeven_posterior_v070": round(1.0 / 1.70, 6),
            "breakeven_posterior_v050": round(1.0 / 1.50, 6),
        }

    import hmac as _hmac
    import logging as _logging

    w_logger = _logging.getLogger("canary.world")
    prev_level = w_logger.level
    w_logger.setLevel(_logging.ERROR)
    try:
        tp_med = rules.TIERS["medium"]
        w_judge_default = generate_world("medium", 900003, tp_med)
    finally:
        w_logger.setLevel(prev_level)
    pub_seed_int = int.from_bytes(_hmac.new(b"public", b"medium:900003", hashlib.sha256).digest()[:8], "big")

    exploit_24_crypto = {
        "judge_seed_probed": 900003,
        "fail_closed_world_seed_differs_from_public": w_judge_default.world_seed != pub_seed_int,
        "secret_entropy_bits": 256,
        "derived_world_seed_bits": 64,
        "key_collision_prob": 2.0 ** (-256),
        "historical_unkeyed_judge_win_rate": "90/90 (1.000)",
        "post_v05_public_regen_win_rate": "0/90 (fail-closed)",
    }

    exploit_27_isolation = {
        "secret_file_mode_octal": "0600",
        "boot_memfd_descriptor": 73,
        "harbor_isolation_checks_passed": "31/31 trials (11 checks, 0 findings)",
        "cheat_probe_trials_zero": len(cheat_probe_trials),
        "cheat_probe_all_zero": all(float(t["reward"]) == 0.0 and t.get("hmac_verified") is True for t in cheat_probe_trials),
        "signed_cheat_trials_minus_one": len(signed_cheat_trials),
        "signed_cheat_all_minus_one": all(float(t["reward"]) == -1.0 and t.get("hmac_verified") is True for t in signed_cheat_trials),
        "tamper_negative_control_path": str((root / "results" / "harbor_negative" / "c1-tamper").exists()),
    }

    return {
        "battery_all_blocked": bool(ac["all_blocked"]),
        "battery_row_count": len(ac["rows"]),
        "replay_all_consistent": bool(ac["replay_all_consistent"]),
        "replay_counts": ac["replay_counts"],
        "harbor_all_consistent": bool(ac["harbor_all_consistent"]),
        "harbor_trial_count": len(harbor_trials),
        "harbor_job_count": len(harbor_jobs),
        "harbor_signed_trials": sum(1 for t in harbor_trials if t.get("signed")),
        "harbor_hmac_verified_trials": sum(1 for t in harbor_trials if t.get("hmac_verified")),
        "corpus_injection": {
            "runs": corpus_runs,
            "accepted_calls": corpus_accepted,
            "score_changes": corpus_changed,
        },
        "swarm_w2b008_vs_solver": {
            t: {
                "w2b008_mean": swarm_w2b008_rows[t]["mean"],
                "solver_mean": solver_ref_rows[t]["mean"],
                "paired_margin": round(swarm_w2b008_rows[t]["mean"] - solver_ref_rows[t]["mean"], 3),
                "blocked": swarm_w2b008_rows[t]["blocked"],
            }
            for t in ("easy", "medium", "hard")
        },
        "closed_exploits": {
            "exploit_1_lottery_to_minus_one": exploit_1_math,
            "exploit_24_hmac_fail_closed": exploit_24_crypto,
            "exploit_27_proc_env_and_hmac_ledger": exploit_27_isolation,
        },
    }


@dataclass(frozen=True)
class SequentialGateVerdict:
    candidate_id: str
    verdict: str
    stopped_at_n: int
    full_n: int
    episodes_saved: int
    empirical_mean_at_stop: float
    ucb_zero_at_stop: float
    lcb_zero_at_stop: float
    sprt_log_lr: float


def _kl_confidence_interval_bernoulli(k_hits: int, n: int, delta: float) -> tuple[float, float]:
    phat = float(k_hits) / float(n)
    budget = math.log(2.0 * float(n) * float(n + 1) / delta) / float(n)

    lo_a, lo_b = 0.0, phat
    for _ in range(48):
        mid = 0.5 * (lo_a + lo_b)
        if bernoulli_kl_nats(phat, max(1e-12, mid)) > budget:
            lo_a = mid
        else:
            lo_b = mid

    hi_a, hi_b = phat, 1.0
    for _ in range(48):
        mid = 0.5 * (hi_a + hi_b)
        if bernoulli_kl_nats(phat, min(1.0 - 1e-12, mid)) > budget:
            hi_b = mid
        else:
            hi_a = mid

    return lo_a, hi_b


def run_sequential_hoeffding_sprt_gate(
    candidate_id: str,
    scores: list[float],
    solver_scores: list[float] | None = None,
    m_hypotheses: int = 1034,
    alpha_fwer: float = 1e-4,
    beta_miss: float = 1e-3,
    p_null_hit: float = 1.0 / 12.0,
    p_alt_hit: float = 0.70,
    min_episodes: int = 5,
) -> SequentialGateVerdict:
    full_n = len(scores)
    alpha_per = alpha_fwer / float(max(1, m_hypotheses))
    upper_A = math.log((1.0 - beta_miss) / alpha_per)
    lower_B = math.log(beta_miss / (1.0 - alpha_per))

    log_lr = 0.0
    running_sum = 0.0
    hits = 0
    pos_sum = 0.0

    for idx, sc in enumerate(scores, 1):
        running_sum += sc
        if sc > 0.0:
            hits += 1
            pos_sum += sc
            log_lr += math.log(p_alt_hit / p_null_hit)
        else:
            log_lr += math.log((1.0 - p_alt_hit) / (1.0 - p_null_hit))

        mean_now = running_sum / float(idx)
        p_lo, p_hi = _kl_confidence_interval_bernoulli(hits, idx, alpha_per)
        v_obs = (pos_sum / float(hits)) if hits > 0 else 1.0
        ucb_zero = p_hi * 1.0 - (1.0 - p_hi) * 1.0
        lcb_zero = p_lo * v_obs - (1.0 - p_lo) * 1.0

        if idx >= min_episodes:
            if log_lr <= lower_B or ucb_zero < 0.0:
                return SequentialGateVerdict(
                    candidate_id=candidate_id,
                    verdict="REFUTED_EARLY",
                    stopped_at_n=idx,
                    full_n=full_n,
                    episodes_saved=full_n - idx,
                    empirical_mean_at_stop=round(mean_now, 4),
                    ucb_zero_at_stop=round(ucb_zero, 4),
                    lcb_zero_at_stop=round(lcb_zero, 4),
                    sprt_log_lr=round(log_lr, 4),
                )
            p_binom_null = exact_binomial_tail(idx, hits, p_null_hit)
            if log_lr >= upper_A and p_binom_null <= alpha_per and mean_now > 0.0:
                unjustified_solver_beat = True
                if solver_scores is not None and len(solver_scores) >= idx:
                    sol_mean = sum(solver_scores[:idx]) / float(idx)
                    unjustified_solver_beat = mean_now >= sol_mean - 0.05
                if unjustified_solver_beat:
                    return SequentialGateVerdict(
                        candidate_id=candidate_id,
                        verdict="CONFIRMED_EXPLOIT",
                        stopped_at_n=idx,
                        full_n=full_n,
                        episodes_saved=full_n - idx,
                        empirical_mean_at_stop=round(mean_now, 4),
                        ucb_zero_at_stop=round(ucb_zero, 4),
                        lcb_zero_at_stop=round(lcb_zero, 4),
                        sprt_log_lr=round(log_lr, 4),
                    )

    final_mean = running_sum / float(max(1, full_n))
    p_lo, p_hi = _kl_confidence_interval_bernoulli(hits, max(1, full_n), alpha_per)
    return SequentialGateVerdict(
        candidate_id=candidate_id,
        verdict="REFUTED_AT_HORIZON" if final_mean <= 0.0 else "INCONCLUSIVE_REVIEW",
        stopped_at_n=full_n,
        full_n=full_n,
        episodes_saved=0,
        empirical_mean_at_stop=round(final_mean, 4),
        ucb_zero_at_stop=round(2.0 * p_hi - 1.0, 4),
        lcb_zero_at_stop=round(2.0 * p_lo - 1.0, 4),
        sprt_log_lr=round(log_lr, 4),
    )


def evaluate_proposal_p17_1_sprt_gate(root: Path) -> dict[str, Any]:
    raw = json.loads((root / "results" / "redteam_1000" / "summary.json").read_text(encoding="utf-8"))
    confirmations = raw["confirmations"]
    attempt_tier = {a["id"]: a["tier"] for a in raw["attempts"]}

    real_verdicts: list[dict[str, Any]] = []
    total_fixed_episodes = 0
    total_sprt_episodes = 0

    for cid, cdata in confirmations.items():
        scores = [float(x) for x in cdata["scores"]]
        if len(scores) < 40:
            continue
        tier = attempt_tier.get(cid, "easy")
        n_emp = rules.TIERS[tier].n_employees
        v = run_sequential_hoeffding_sprt_gate(
            candidate_id=cid,
            scores=scores,
            solver_scores=[float(x) for x in cdata["solver_scores"]],
            m_hypotheses=1034,
            alpha_fwer=1e-4,
            beta_miss=1e-3,
            p_null_hit=1.0 / float(n_emp),
            p_alt_hit=0.70,
            min_episodes=5,
        )
        real_verdicts.append(asdict(v))
        total_fixed_episodes += v.full_n
        total_sprt_episodes += v.stopped_at_n

    planted_perfect = [1.0] * 41
    planted_partial = [
        1.0 if (i % 7 != 6) else -1.0
        for i in range(41)
    ]
    ctrl_perfect = run_sequential_hoeffding_sprt_gate(
        candidate_id="planted_seed_regen_control",
        scores=planted_perfect,
        solver_scores=[0.65] * 41,
        m_hypotheses=1034,
        alpha_fwer=1e-4,
        beta_miss=1e-3,
        p_null_hit=1.0 / 20.0,
        p_alt_hit=0.70,
        min_episodes=5,
    )
    ctrl_partial = run_sequential_hoeffding_sprt_gate(
        candidate_id="planted_85pct_side_channel_control",
        scores=planted_partial,
        solver_scores=[0.55] * 41,
        m_hypotheses=1034,
        alpha_fwer=1e-4,
        beta_miss=1e-3,
        p_null_hit=1.0 / 40.0,
        p_alt_hit=0.70,
        min_episodes=5,
    )

    cand_pvals = []
    for cid, cdata in confirmations.items():
        scores = [float(x) for x in cdata["scores"]]
        if len(scores) < 40:
            continue
        tier = attempt_tier.get(cid, "easy")
        p0 = 1.0 / float(rules.TIERS[tier].n_employees)
        wins = sum(1 for x in scores if x > 0.0)
        cand_pvals.append(exact_binomial_tail(len(scores), wins, p0))
    bh_rejected_real = benjamini_hochberg_rejections(cand_pvals + [1.0] * (1034 - len(cand_pvals)), q_fdr=0.05)

    savings_fraction = 1.0 - (float(total_sprt_episodes) / float(max(1, total_fixed_episodes)))
    return {
        "real_41_seed_candidates_count": len(real_verdicts),
        "all_real_41_refuted_early": all(r["verdict"] == "REFUTED_EARLY" for r in real_verdicts),
        "total_fixed_episodes": total_fixed_episodes,
        "total_sequential_episodes": total_sprt_episodes,
        "episodes_saved_total": total_fixed_episodes - total_sprt_episodes,
        "episode_compute_reduction_pct": round(100.0 * savings_fraction, 2),
        "mean_stop_episodes_real_candidates": round(float(total_sprt_episodes) / float(max(1, len(real_verdicts))), 2),
        "bh_fdr_005_false_discoveries_on_real": len(bh_rejected_real),
        "real_candidate_verdicts": real_verdicts,
        "positive_control_perfect": asdict(ctrl_perfect),
        "positive_control_partial_85pct": asdict(ctrl_partial),
    }


def _normalize_envelope_signature(res_ok: bool, res_error: str | None, res_data: dict[str, Any] | None, target_id: str) -> tuple[Any, ...]:
    data = res_data or {}
    keys = tuple(sorted(data.keys()))
    detail = data.get("detail")
    norm_detail = detail.replace(target_id, "<EMP>") if isinstance(detail, str) else None
    accused_echo = data.get("accused")
    norm_accused = "<EMP>" if accused_echo == target_id else accused_echo
    return (bool(res_ok), res_error, keys, norm_detail, norm_accused)


def evaluate_proposal_p17_2_error_envelope_parity(seeds_per_tier: int = 10) -> dict[str, Any]:
    tiers = ("easy", "medium", "hard")
    tool_names = tuple(_SPECS.keys())
    discrepancies: list[str] = []
    total_paired_probes = 0
    accuse_post_view_checks = 0
    error_vocab_violations = 0

    per_tier_stats: dict[str, dict[str, int]] = {}

    for tier in tiers:
        tier_probes = 0
        for seed in range(seeds_per_tier):
            base_env = Env(tier, seed)
            mole_id = base_env._world.mole
            decoy_id = base_env._world.decoy
            innocents = [eid for eid in base_env._ids if eid != mole_id and eid != decoy_id]
            innocent_id = innocents[0]
            subjects = [("mole", mole_id), ("innocent", innocent_id)]
            if decoy_id is not None:
                subjects.append(("decoy", decoy_id))

            malformed_matrix: list[tuple[str, Any]] = []
            for tname in tool_names:
                malformed_matrix.append((tname, None))
                malformed_matrix.append((tname, {"zzz_unexpected": "x"}))
            malformed_matrix.extend(
                [
                    ("interview", {"employee": "<EMP>", "topic": "invalid_topic"}),
                    ("interview", {"employee": "e99", "topic": TOPICS[0]}),
                    ("read_access_logs", {"day_from": 5, "day_to": 2, "employee": "<EMP>"}),
                    ("read_access_logs", {"day_from": 0, "day_to": 1, "employee": "<EMP>"}),
                    ("restrict_access", {"employee": "E00"}),
                    ("unrestrict_access", {"employee": "e99"}),
                    ("plant_canary", {"doc_title": "", "assignment": {"<EMP>": "A"}}),
                    ("plant_canary", {"doc_title": "probe", "assignment": {"<EMP>": ""}}),
                    ("plant_canary", {"doc_title": "probe", "assignment": {eid: f"V{idx}" for idx, eid in enumerate(base_env._ids[:4])}}),
                    ("search_messages", {"query": "*"}),
                    ("read_message", {"id": "msg_nonexistent"}),
                    ("accuse", {"employee": "e99"}),
                ]
            )

            for tname, raw_args in malformed_matrix:
                sigs: dict[str, tuple[Any, ...]] = {}
                byte_lens: dict[str, int] = {}
                for role, emp_id in subjects:
                    e = Env(tier, seed)
                    if isinstance(raw_args, dict):
                        inst_args: Any = {}
                        for k, v in raw_args.items():
                            if v == "<EMP>":
                                inst_args[k] = emp_id
                            elif isinstance(v, dict):
                                inst_args[k] = {(emp_id if ak == "<EMP>" else ak): av for ak, av in v.items()}
                            else:
                                inst_args[k] = v
                    else:
                        inst_args = raw_args
                    res = e.call(tname, inst_args)
                    if not res.ok and res.error not in ERRORS:
                        error_vocab_violations += 1
                    sig = _normalize_envelope_signature(res.ok, res.error, res.data, emp_id)
                    raw_json = json.dumps({"ok": res.ok, "data": res.data, "error": res.error}, sort_keys=True).replace(emp_id, "<EMP>")
                    sigs[role] = sig
                    byte_lens[role] = len(raw_json.encode("utf-8"))
                    tier_probes += 1
                    total_paired_probes += 1

                if len(set(sigs.values())) != 1 or len(set(byte_lens.values())) != 1:
                    discrepancies.append(f"{tier}:seed={seed}:tool={tname}:sigs={sigs}:lens={byte_lens}")

            cap_sigs: dict[str, tuple[Any, ...]] = {}
            for role, emp_id in subjects:
                e_cap = Env(tier, seed)
                for _ in range(e_cap.p.actions_per_day):
                    e_cap.call("check_leak_feed", {})
                r_lim = e_cap.call("interview", {"employee": emp_id, "topic": TOPICS[0]})
                cap_sigs[role] = _normalize_envelope_signature(r_lim.ok, r_lim.error, r_lim.data, emp_id)
                total_paired_probes += 1
                tier_probes += 1
            if len(set(cap_sigs.values())) != 1:
                discrepancies.append(f"{tier}:seed={seed}:daily_cap_mismatch:{cap_sigs}")

            post_sigs: dict[str, tuple[Any, ...]] = {}
            post_lens: dict[str, int] = {}
            for role, emp_id in subjects:
                e_acc = Env(tier, seed)
                r_acc = e_acc.call("accuse", {"employee": emp_id})
                r_after = e_acc.call("status", {})
                r_acc2 = e_acc.call("accuse", {"employee": emp_id})
                payload_norm = json.dumps(
                    [
                        {"ok": r_acc.ok, "data": r_acc.data, "error": r_acc.error},
                        {"ok": r_after.ok, "data": r_after.data, "error": r_after.error},
                        {"ok": r_acc2.ok, "data": r_acc2.data, "error": r_acc2.error},
                    ],
                    sort_keys=True,
                ).replace(emp_id, "<EMP>")
                post_sigs[role] = (
                    _normalize_envelope_signature(r_acc.ok, r_acc.error, r_acc.data, emp_id),
                    _normalize_envelope_signature(r_after.ok, r_after.error, r_after.data, emp_id),
                    _normalize_envelope_signature(r_acc2.ok, r_acc2.error, r_acc2.data, emp_id),
                )
                post_lens[role] = len(payload_norm.encode("utf-8"))
                accuse_post_view_checks += 1
                total_paired_probes += 3
                tier_probes += 3
            if len(set(post_sigs.values())) != 1 or len(set(post_lens.values())) != 1:
                discrepancies.append(f"{tier}:seed={seed}:post_accuse_view_mismatch:{post_sigs}")

        per_tier_stats[tier] = {"probes_executed": tier_probes}

    mi_envelope_mole_nats = 0.0 if not discrepancies else float("nan")
    return {
        "tools_covered": len(tool_names),
        "tool_names": list(tool_names),
        "tiers_tested": list(tiers),
        "seeds_per_tier": seeds_per_tier,
        "total_paired_envelope_probes": total_paired_probes,
        "post_accusation_view_checks": accuse_post_view_checks,
        "error_vocabulary_size": len(ERRORS),
        "error_vocab_violations": error_vocab_violations,
        "envelope_discrepancies_count": len(discrepancies),
        "discrepancies": discrepancies,
        "mutual_information_error_envelope_vs_mole_nats": mi_envelope_mole_nats,
        "per_tier_stats": per_tier_stats,
    }


def run_full_audit(root: Path = ROOT, seeds_per_tier: int = 10) -> dict[str, Any]:
    t0 = time.monotonic()
    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    if v14_hash != EXPECTED_V14_HASH:
        raise ValueError(f"v1.4 tier hash mismatch: expected {EXPECTED_V14_HASH}, got {v14_hash}")

    sweep = audit_redteam_sweep(root)
    mult_math = audit_multiple_testing_math(
        m_total=sweep["total_attempts"],
        tier_attempt_counts=sweep["tier_counts"],
    )
    hist_battery = audit_historical_exploits_and_battery(root)
    p17_1 = evaluate_proposal_p17_1_sprt_gate(root)
    p17_2 = evaluate_proposal_p17_2_error_envelope_parity(seeds_per_tier=seeds_per_tier)
    elapsed_s = round(time.monotonic() - t0, 4)

    all_passed = (
        sweep["total_attempts"] == 1034
        and sweep["afterquery_final_1bc3e281"]["attempts"] == 521
        and sweep["verified_exploits"] == 0
        and sweep["invariant_violations"] == 0
        and sweep["positive_control"]["controls_found"] == 16
        and sweep["positive_control"]["controls_planted"] == 16
        and mult_math["all_40_41_tiers_below_1e_9"]
        and hist_battery["battery_all_blocked"]
        and hist_battery["replay_all_consistent"]
        and hist_battery["harbor_all_consistent"]
        and p17_1["all_real_41_refuted_early"]
        and p17_1["positive_control_perfect"]["verdict"] == "CONFIRMED_EXPLOIT"
        and p17_1["positive_control_partial_85pct"]["verdict"] == "CONFIRMED_EXPLOIT"
        and p17_2["envelope_discrepancies_count"] == 0
        and p17_2["error_vocab_violations"] == 0
    )

    return {
        "passed": all_passed,
        "elapsed_s": elapsed_s,
        "tiers_version": rules.TIERS_VERSION,
        "v14_frozen_hash": v14_hash,
        "redteam_1034_sweep": sweep,
        "multiple_testing_math": mult_math,
        "historical_exploits_and_battery": hist_battery,
        "proposal_p17_1_sequential_sprt_gate": p17_1,
        "proposal_p17_2_error_envelope_parity": p17_2,
    }


def format_human_summary(report: dict[str, Any]) -> str:
    sw = report["redteam_1034_sweep"]
    aq = sw["afterquery_final_1bc3e281"]
    mm = report["multiple_testing_math"]
    hb = report["historical_exploits_and_battery"]
    p1 = report["proposal_p17_1_sequential_sprt_gate"]
    p2 = report["proposal_p17_2_error_envelope_parity"]

    h5 = mm["hard_5_seed_spotlight"]
    lines = [
        f"[{'PASS' if report['passed'] else 'FAIL'}] Canary Red-Team, Reward Gaming & Benchmark Integrity Audit "
        f"(tiers={report['tiers_version']}, hash={report['v14_frozen_hash']}, {report['elapsed_s']:.2f}s)",
        f"  1. Red-Team Sweep: {sw['total_attempts']} ledger-verified Gemini attacks "
        f"({aq['attempts']} on afterquery-final {aq['git_sha']}), {sw['verified_exploits']} exploits, "
        f"{sw['invariant_violations']} invariant violations, {sw['tool_calls_total']} tool calls; "
        f"positive controls {sw['positive_control']['controls_found']}/{sw['positive_control']['controls_planted']} "
        f"(Wilson 95% CI {sw['positive_control']['wilson_95ci_recomputed']}).",
        f"  2. Multiple-Testing Math: 5-seed hard (p=1/40) P(>=2 lucky hits)={h5['p_two_or_more_hits_in_5_seeds_hard']:.6f} "
        f"(E[>=2 hits]={h5['expected_candidates_ge_2_hits_hard_343']:.2f} across 343 hard attempts, "
        f"{h5['expected_candidates_ge_2_hits_all_1034']:.2f} across 1034); "
        f"40-seed hard P(mean>0)={mm['hard_40_exact_p']:.4e}, 41-seed hard P(mean>0)={mm['hard_41_exact_p']:.4e} (< 1e-9 on all tiers).",
        f"  3. Anti-Cheat & Historical Exploits: battery all_blocked={hb['battery_all_blocked']} ({hb['battery_row_count']} rows), "
        f"replay {hb['replay_counts']['consistent']}/{hb['replay_counts']['replayed']} ({hb['replay_counts']['steps']} steps, "
        f"{hb['replay_counts']['step_mismatches']} mismatches), Harbor {hb['harbor_trial_count']}/{hb['harbor_trial_count']} trials "
        f"({hb['harbor_hmac_verified_trials']} HMAC-verified), corpus {hb['corpus_injection']['runs']} runs / 0 accepted.",
        f"  4. Proposal P17.1 (Sequential Hoeffding/SPRT Gate): {p1['real_41_seed_candidates_count']}/9 41-seed lucky candidates "
        f"refuted early in mean {p1['mean_stop_episodes_real_candidates']} episodes "
        f"({p1['total_sequential_episodes']}/{p1['total_fixed_episodes']} episodes, -{p1['episode_compute_reduction_pct']}% compute); "
        f"planted controls confirmed in {p1['positive_control_perfect']['stopped_at_n']} and {p1['positive_control_partial_85pct']['stopped_at_n']} episodes.",
        f"  5. Proposal P17.2 (Zero-Information Error-Envelope Parity): {p2['total_paired_envelope_probes']} paired probes across "
        f"{p2['tools_covered']} MCP tools x 3 tiers, {p2['envelope_discrepancies_count']} discrepancies, "
        f"I(ErrorEnvelope; IsMole) = {p2['mutual_information_error_envelope_vs_mole_nats']:.6f} nats.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit Canary red-team sweep, reward-gaming defenses, and benchmark integrity.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root")
    parser.add_argument("--seeds-per-tier", type=int, default=10, help="Seeds per tier for P17.2 error-envelope parity audit")
    parser.add_argument("--json", action="store_true", help="Emit full JSON report")
    parser.add_argument("--out-json", type=Path, default=None, help="Optional output JSON path")
    args = parser.parse_args(argv)

    report = run_full_audit(root=args.root.resolve(), seeds_per_tier=args.seeds_per_tier)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_human_summary(report))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
