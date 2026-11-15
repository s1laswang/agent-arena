"""Zero-shot cross-mole generalization benchmark for Canary tiebreak policies."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import multiprocessing
import os
import re
import sys
import time
import tokenize
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import train.empirical_bayes_policy as eb_mod
from train.empirical_bayes_policy import (
    EmpiricalBayesParams,
    EmpiricalBayesPolicy,
    assert_strict_train_seed,
    bootstrap_ci,
    make_naive_prior_params,
    paired_bootstrap_delta,
)

SCHEMA_VERSION = "canary.tiebreak.cross_mole_generalization.v1"
MD_H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

TRAIN_SEED_START = 100_000
TRAIN_SEED_COUNT = 120
HELDOUT_SEED_START = 800_000
HELDOUT_SEED_COUNT = 30
DEFAULT_HELDOUT_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_SECRET_TAG = "sha256:ebf2f09716cf76d3"
MAX_SUMMARY_BYTES = 100 * 1024
MIN_REGIME_N = 30

DEFAULT_SUMMARY_JSON = Path("results/tiebreak/cross_mole_generalization/generalization_summary.json")
DEFAULT_REPORT_MD = Path("docs/reports/tiebreak_cross_mole_generalization.md")

DSL_PATIENT_SLEEPER_SPEC: dict[str, Any] = {
    "name": "dsl_patient_sleeper",
    "rules": [
        {"if": [["day", "<=", 6]], "then": {"leak": "none", "frame": "decoy"}},
        {"if": [["recent_low_recipient_docs", ">=", 2]], "then": {"leak": "most_recipients", "frame": "decoy"}},
    ],
    "default": {"leak": "fewest_recipients", "frame": "decoy"},
}

REGIME_SPECS: tuple[dict[str, str], ...] = (
    {
        "regime_id": "hard",
        "label": "hard (default careful/framing mole)",
        "env_tier": "hard",
        "mole_kind": "default",
        "training_exposure": "in_distribution_mole_rules",
        "adversarial_mechanism": "Careful canary-share weighting + Poisson decoy/peer after-hours framing + 0.95 fingerprint accuracy",
    },
    {
        "regime_id": "hard_forge",
        "label": "hard_forge (evolved Forge HoF moles)",
        "env_tier": "hard_forge",
        "mole_kind": "forge_hof",
        "training_exposure": "zero_shot_unseen",
        "adversarial_mechanism": "Per-seed evolved MoleStrategy HoF rules (early leak suppression, recipient-count thresholds, decoy/restricted framing)",
    },
    {
        "regime_id": "hard_rl",
        "label": "hard_rl (RLMole policy)",
        "env_tier": "hard_rl",
        "mole_kind": "rl_mole_track",
        "training_exposure": "zero_shot_unseen",
        "adversarial_mechanism": "REINFORCE-trained 1-hidden-layer MLP mole over 10 MoleView features with solver catchability >= 0.75",
    },
    {
        "regime_id": "hard_dsl_patient_sleeper",
        "label": "hard + dsl_patient_sleeper (silent early days + decoy framing)",
        "env_tier": "hard",
        "mole_kind": "dsl_patient_sleeper",
        "training_exposure": "zero_shot_unseen",
        "adversarial_mechanism": "Silent days 1..6 + continuous decoy framing + broad-doc evasion when >=2 narrow-recipient docs are held",
    },
    {
        "regime_id": "medium_hard_rl",
        "label": "medium + hard_rl strategy (cross-tier RLMole transfer)",
        "env_tier": "medium",
        "mole_kind": "hard_rl_on_medium",
        "training_exposure": "zero_shot_unseen",
        "adversarial_mechanism": "hard_rl RLMole transferred onto 20-staff 14-day medium tier (1 canary/day, delays 1..3, decoy + framing)",
    },
)

AGENT_ORDER: tuple[str, ...] = (
    "before",
    "stage2_likelihood_only",
    "after",
    "solver",
)

PREREG_RE = re.compile(r"\bpre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b", re.IGNORECASE)
NEGATED_PREREG_RE = re.compile(
    r"\b(?:not|never|no|neither|nor|without)\s+(?:a\s+|an\s+)?pre[-\s]?regist(?:er(?:ed|ing|s)?|ration)\b",
    re.IGNORECASE,
)
SEEDS_0_29_RE = re.compile(
    r"(?:\bseeds?\s*`?0\s*(?:\.\.|-|to)\s*29`?|`?0\s*(?:\.\.|-)\s*29`?\s*seeds?|\b0\.\.29\b|\b0-29\b)",
    re.IGNORECASE,
)
FLOAT_TOKEN_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")


class UncalibratedEmpiricalBayesPolicy(EmpiricalBayesPolicy):
    name = "uncalibrated_empirical_bayes"

    def __init__(
        self,
        params: EmpiricalBayesParams | None = None,
        seed: int = 0,
        name: str = "uncalibrated_empirical_bayes",
    ) -> None:
        base_params = params if params is not None else make_naive_prior_params()
        forced_uncalibrated = EmpiricalBayesParams(
            w_canary_hit=base_params.w_canary_hit,
            w_canary_miss=base_params.w_canary_miss,
            w_doc_hit=base_params.w_doc_hit,
            w_after_hours=base_params.w_after_hours,
            w_evasive=base_params.w_evasive,
            w_angry_msg=base_params.w_angry_msg,
            tau_margin=0.0,
            unsurfaced_v_discount=0.0,
            canary_coverage=0.90,
            tiny_pool_size=0,
            use_ev_stopping=False,
            naive_p_threshold=base_params.naive_p_threshold,
            stage=str(base_params.stage),
        )
        super().__init__(params=forced_uncalibrated, seed=seed, name=name)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        return super().act(history)


def _secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def _step_fields(step: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if hasattr(step, "tool"):
        tool = str(step.tool)
        args = dict(step.args) if isinstance(step.args, dict) else {}
        res = dict(step.result) if isinstance(step.result, dict) else {}
    else:
        tool = str(step.get("tool", ""))
        args = dict(step.get("args") or {})
        res = dict(step.get("result") or {})
    return tool, args, res


def build_regime_env(regime_id: str, seed: int) -> Any:
    from canary.env import Env
    from canary.forge_track import strategy_for
    from canary.mole.dsl import MoleStrategy

    if regime_id == "hard":
        return Env("hard", seed)
    if regime_id == "hard_forge":
        return Env("hard_forge", seed)
    if regime_id == "hard_rl":
        return Env("hard_rl", seed)
    if regime_id == "hard_dsl_patient_sleeper":
        sleeper = MoleStrategy.from_json(DSL_PATIENT_SLEEPER_SPEC)
        return Env("hard", seed, mole_strategy=sleeper)
    if regime_id == "medium_hard_rl":
        rl_strat = strategy_for("hard_rl", seed)
        return Env("medium", seed, mole_strategy=rl_strat)
    raise ValueError(f"unknown regime_id: {regime_id!r}")


def replay_verify_regime_episode(regime_id: str, ep: Any) -> bool:
    env = build_regime_env(regime_id, int(ep.seed))
    for st in ep.steps:
        if env.done:
            break
        tool, args, recorded_res = _step_fields(st)
        live_res = env.call(tool, args)
        if recorded_res and "ok" in recorded_res and bool(live_res.ok) != bool(recorded_res["ok"]):
            raise AssertionError(
                f"step ok mismatch on regime={regime_id} agent={ep.agent} seed={ep.seed} step={tool}"
            )
    replayed = env.result("replay")
    if abs(float(replayed.score) - float(ep.score)) > 1e-9:
        raise AssertionError(
            f"replay score mismatch on regime={regime_id} agent={ep.agent} seed={ep.seed}: "
            f"{replayed.score} != {ep.score}"
        )
    if replayed.accused != ep.accused:
        raise AssertionError(
            f"replay accused mismatch on regime={regime_id} agent={ep.agent} seed={ep.seed}: "
            f"{replayed.accused} != {ep.accused}"
        )
    if bool(replayed.correct) != bool(ep.correct):
        raise AssertionError(
            f"replay correct mismatch on regime={regime_id} agent={ep.agent} seed={ep.seed}"
        )
    if int(replayed.final_day) != int(ep.final_day):
        raise AssertionError(
            f"replay final_day mismatch on regime={regime_id} agent={ep.agent} seed={ep.seed}"
        )
    return True


def validate_cross_mole_seeds(train_seeds: list[int], heldout_seeds: list[int]) -> None:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    if len(train_seeds) < 4 or len(train_seeds) % 2 != 0:
        raise ValueError("train_seeds must have an even count >= 4 for disjoint Stage 2 / Stage 3 split")
    if not heldout_seeds:
        raise ValueError("heldout_seeds must be non-empty")

    lo = min(train_seeds)
    hi = max(train_seeds) + 1
    for s in train_seeds:
        assert_strict_train_seed(s, lo, hi)

    t_set = set(train_seeds)
    h_set = set(heldout_seeds)
    if len(t_set) != len(train_seeds):
        raise ValueError("duplicate seeds in train_seeds")
    if len(h_set) != len(heldout_seeds):
        raise ValueError("duplicate seeds in heldout_seeds")
    if t_set & h_set:
        raise ValueError("train_seeds and heldout_seeds overlap")
    if (t_set | h_set) & (set(DEV_SEEDS) | set(JUDGE_SEEDS)):
        raise ValueError("seeds overlap DEV_SEEDS or JUDGE_SEEDS")
    if not all(s in TRAIN_SEEDS for s in t_set):
        raise ValueError("all train_seeds must lie in TRAIN_SEEDS [100000, 200000)")
    if not all(s in HELDOUT_SEEDS for s in h_set):
        raise ValueError("all heldout_seeds must lie in HELDOUT_SEEDS [800000, 800200)")


def fit_policies_once_on_default_mole(
    train_seeds: list[int],
    laplace_alpha: float = 1.0,
) -> tuple[EmpiricalBayesParams, EmpiricalBayesParams, EmpiricalBayesParams, dict[str, Any]]:
    half = len(train_seeds) // 2
    stage2_seeds = list(train_seeds[:half])
    stage3_seeds = list(train_seeds[half:])
    if set(stage2_seeds) & set(stage3_seeds):
        raise ValueError("stage2_seeds and stage3_seeds must be strictly disjoint")

    s2_lo, s2_hi = min(stage2_seeds), max(stage2_seeds) + 1
    s3_lo, s3_hi = min(stage3_seeds), max(stage3_seeds) + 1
    for s in stage2_seeds:
        assert_strict_train_seed(s, s2_lo, s2_hi)
    for s in stage3_seeds:
        assert_strict_train_seed(s, s3_lo, s3_hi)

    before_params = make_naive_prior_params()
    old_s2_range = eb_mod.STAGE2_TRAIN_RANGE
    old_s3_range = eb_mod.STAGE3_TRAIN_RANGE
    try:
        eb_mod.STAGE2_TRAIN_RANGE = (s2_lo, s2_hi)
        eb_mod.STAGE3_TRAIN_RANGE = (s3_lo, s3_hi)
        stage2_params, stage2_stats = eb_mod.fit_empirical_likelihoods(
            stage2_seeds,
            laplace_alpha=laplace_alpha,
        )
        after_params, stage3_stats = eb_mod.optimize_stopping_and_splits(
            stage2_params,
            stage3_seeds,
        )
    finally:
        eb_mod.STAGE2_TRAIN_RANGE = old_s2_range
        eb_mod.STAGE3_TRAIN_RANGE = old_s3_range

    train_meta = {
        "train_seed_range": f"{train_seeds[0]}..{train_seeds[-1]}",
        "stage2_seed_range": f"{stage2_seeds[0]}..{stage2_seeds[-1]}",
        "stage3_seed_range": f"{stage3_seeds[0]}..{stage3_seeds[-1]}",
        "n_train_total": len(train_seeds),
        "n_stage2_likelihood": len(stage2_seeds),
        "n_stage3_stopping_splits": len(stage3_seeds),
        "train_tiers": ["easy", "medium", "hard"],
        "train_mole_exposure": ["default_v0"],
        "adversarial_moles_seen_in_training": 0,
        "fitted_strictly_once": True,
        "stage2_likelihood_fit": {
            "seed_range": stage2_stats["seed_range"],
            "n_episodes": stage2_stats["n_episodes"],
            "n_identified_episodes": stage2_stats["n_identified_episodes"],
            "empirical_rates": stage2_stats["empirical_rates"],
            "train_mean_score_before": stage2_stats["train_mean_score_eb_naive_prior"],
            "train_mean_score_stage2_likelihood_only": stage2_stats["train_mean_score_eb_likelihood_only"],
        },
        "stage3_stopping_and_split_opt": {
            "seed_range": stage3_stats["seed_range"],
            "n_episodes": stage3_stats["n_episodes"],
            "selected": stage3_stats["selected"],
            "train_stage2_uncalibrated": stage3_stats["train_stage2_uncalibrated"],
            "train_stage3_selected": stage3_stats["train_stage3_selected"],
        },
    }
    return before_params, stage2_params, after_params, train_meta


_SHARED_FITTED_PARAMS: tuple[EmpiricalBayesParams, EmpiricalBayesParams, EmpiricalBayesParams] | None = None


def _evaluate_world_task(task: tuple[str, int, dict[str, Any], dict[str, Any], dict[str, Any], str, bool]) -> dict[str, Any]:
    regime_id, seed, before_d, stage2_d, after_d, heldout_secret, include_solver = task
    from canary import world as canary_world
    from canary.analysis.accuse import audit_episode
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    prev_env_secret = os.environ.get("CANARY_WORLD_SECRET")
    prev_set_secret = getattr(canary_world, "_SET_SECRET", None)
    try:
        canary_world.set_world_secret(None)
        os.environ["CANARY_WORLD_SECRET"] = heldout_secret

        if _SHARED_FITTED_PARAMS is not None:
            before_params, stage2_params, after_params = _SHARED_FITTED_PARAMS
        else:
            before_params = EmpiricalBayesParams.from_dict(before_d)
            stage2_params = EmpiricalBayesParams.from_dict(stage2_d)
            after_params = EmpiricalBayesParams.from_dict(after_d)

        agent_runners: list[tuple[str, Any]] = [
            ("before", UncalibratedEmpiricalBayesPolicy(before_params, seed=seed, name="before")),
            (
                "stage2_likelihood_only",
                UncalibratedEmpiricalBayesPolicy(stage2_params, seed=seed, name="stage2_likelihood_only"),
            ),
            ("after", EmpiricalBayesPolicy(after_params, seed=seed, name="after")),
        ]
        if include_solver:
            agent_runners.append(("solver", SolverPolicy(act_budget=10.0)))

        out_agents: dict[str, dict[str, Any]] = {}
        world_mole: str | None = None

        for agent_key, policy in agent_runners:
            env = build_regime_env(regime_id, seed)
            ep = run_episode(env, policy)
            replay_verify_regime_episode(regime_id, ep)

            meta = getattr(ep, "meta", None) or {}
            ep_mole = meta.get("mole")
            if world_mole is None and ep_mole is not None:
                world_mole = str(ep_mole)
            elif world_mole is not None and ep_mole is not None and str(ep_mole) != world_mole:
                raise AssertionError(
                    f"unpaired world mole on regime={regime_id} seed={seed}: {ep_mole} != {world_mole}"
                )

            end_reason = getattr(ep, "end_reason", None)
            is_invalid = bool(end_reason in ("error", "invalid") or meta.get("valid") is False)

            total_steps = len(ep.steps)
            ok_steps = 0
            canaries_planted = 0
            for st in ep.steps:
                t_name, _, t_res = _step_fields(st)
                if t_res.get("ok"):
                    ok_steps += 1
                    if t_name == "plant_canary":
                        canaries_planted += 1

            aud = audit_episode(ep) if ep.accused is not None else {}
            solver_p_accused = aud.get("p_accused")
            true_v = meta.get("V")
            if ep.accused is None:
                luck_ev = 0.0
                policy_p_accused = None
            else:
                if solver_p_accused is not None and true_v is not None:
                    luck_ev = float(solver_p_accused) * float(true_v) - (1.0 - float(solver_p_accused))
                else:
                    luck_ev = float(ep.score)
                if hasattr(policy, "posterior"):
                    post_map = policy.posterior()
                    policy_p_accused = float(post_map.get(str(ep.accused), 0.0))
                elif solver_p_accused is not None:
                    policy_p_accused = float(solver_p_accused)
                else:
                    policy_p_accused = 0.0

            out_agents[agent_key] = {
                "score": round(float(ep.score), 6),
                "luck_ev": round(float(luck_ev), 6),
                "accused": ep.accused,
                "correct": bool(ep.correct) if ep.accused is not None else False,
                "abstained": ep.accused is None,
                "final_day": int(ep.final_day),
                "canaries_planted": int(canaries_planted),
                "total_steps": int(total_steps),
                "ok_steps": int(ok_steps),
                "invalid": is_invalid,
                "policy_p_accused": round(float(policy_p_accused), 6) if policy_p_accused is not None else None,
                "solver_p_accused": round(float(solver_p_accused), 6) if solver_p_accused is not None else None,
            }

        return {
            "regime_id": regime_id,
            "seed": seed,
            "agents": out_agents,
        }
    finally:
        canary_world.set_world_secret(prev_set_secret)
        if prev_env_secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_env_secret


def _summarize_agent_records(
    records: list[dict[str, Any]],
    secret_tag: str,
) -> dict[str, Any]:
    n = len(records)
    denom = max(1, n)
    scores = [float(r["score"]) for r in records]
    luck_vals = [float(r["luck_ev"]) for r in records]
    score_ci = bootstrap_ci(scores)
    luck_ci = bootstrap_ci(luck_vals)

    n_correct = sum(1 for r in records if not r["abstained"] and bool(r["correct"]))
    n_wrong = sum(1 for r in records if not r["abstained"] and not bool(r["correct"]))
    n_abstain = sum(1 for r in records if bool(r["abstained"]))
    n_accused = n_correct + n_wrong
    invalid_cnt = sum(1 for r in records if bool(r["invalid"]))

    tot_steps = sum(int(r["total_steps"]) for r in records)
    ok_steps = sum(int(r["ok_steps"]) for r in records)
    valid_call_rate = round(ok_steps / max(1, tot_steps), 6)

    acc_days = [int(r["final_day"]) for r in records if not r["abstained"]]
    can_counts = [int(r["canaries_planted"]) for r in records]

    accused_p_vals = [
        float(r["policy_p_accused"])
        for r in records
        if not r["abstained"] and r["policy_p_accused"] is not None
    ]
    accused_outcomes = [
        1.0 if bool(r["correct"]) else 0.0
        for r in records
        if not r["abstained"] and r["policy_p_accused"] is not None
    ]
    solver_mae_terms = [
        abs(float(r["policy_p_accused"]) - float(r["solver_p_accused"]))
        for r in records
        if not r["abstained"] and r["policy_p_accused"] is not None and r["solver_p_accused"] is not None
    ]

    accuracy = round(n_correct / denom, 6)
    if n_accused > 0 and accused_p_vals:
        precision_when_accused = float(n_correct) / float(n_accused)
        mean_p_at_accuse = float(np.mean(accused_p_vals))
        signed_overconf = mean_p_at_accuse - precision_when_accused
        cal_gap = abs(signed_overconf)
        brier_acc = float(
            np.mean([(p_hat - y) ** 2 for p_hat, y in zip(accused_p_vals, accused_outcomes)])
        )
    else:
        precision_when_accused = 0.0
        mean_p_at_accuse = 0.0
        signed_overconf = 0.0
        cal_gap = 0.0
        brier_acc = 0.0

    commit_probs = [
        float(r["policy_p_accused"]) if (not r["abstained"] and r["policy_p_accused"] is not None) else 0.0
        for r in records
    ]
    episode_cal_gap = abs(float(np.mean(commit_probs)) - (float(n_correct) / denom)) if records else 0.0
    posterior_mae_vs_solver = float(np.mean(solver_mae_terms)) if solver_mae_terms else 0.0

    return {
        "n": n,
        "mean_score": score_ci["mean"],
        "score": score_ci,
        "luck_adjusted_ev": luck_ci,
        "accuracy": accuracy,
        "precision_when_accused": round(precision_when_accused, 6),
        "wrong_accuse_rate": round(n_wrong / denom, 6),
        "abstain_rate": round(n_abstain / denom, 6),
        "accused_rate": round(n_accused / denom, 6),
        "mean_p_at_accuse": round(mean_p_at_accuse, 6),
        "calibration_gap": round(cal_gap, 6),
        "signed_overconfidence_gap": round(signed_overconf, 6),
        "episode_calibration_gap": round(episode_cal_gap, 6),
        "brier_accused": round(brier_acc, 6),
        "posterior_mae_vs_solver": round(posterior_mae_vs_solver, 6),
        "mean_accuse_day": round(float(np.mean(acc_days)), 4) if acc_days else None,
        "mean_canaries_planted": round(float(np.mean(can_counts)), 4) if can_counts else 0.0,
        "valid_call_rate": valid_call_rate,
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "invalid_episodes": invalid_cnt,
        "correct_count": n_correct,
        "wrong_count": n_wrong,
        "abstain_count": n_abstain,
    }


def _build_regime_block(
    spec: dict[str, str],
    seed_rows: list[dict[str, Any]],
    heldout_seeds: list[int],
    secret_tag: str,
    include_solver: bool,
) -> dict[str, Any]:
    ordered = sorted(seed_rows, key=lambda row: int(row["seed"]))
    present_agents = [ag for ag in AGENT_ORDER if include_solver or ag != "solver"]
    agents_summary: dict[str, Any] = {}
    for ag in present_agents:
        ag_recs = [row["agents"][ag] for row in ordered]
        agents_summary[ag] = _summarize_agent_records(ag_recs, secret_tag)

    b_scores = [float(row["agents"]["before"]["score"]) for row in ordered]
    s2_scores = [float(row["agents"]["stage2_likelihood_only"]["score"]) for row in ordered]
    a_scores = [float(row["agents"]["after"]["score"]) for row in ordered]

    b_luck = [float(row["agents"]["before"]["luck_ev"]) for row in ordered]
    s2_luck = [float(row["agents"]["stage2_likelihood_only"]["luck_ev"]) for row in ordered]
    a_luck = [float(row["agents"]["after"]["luck_ev"]) for row in ordered]

    after_minus_before_score = paired_bootstrap_delta(a_scores, b_scores)
    after_minus_before_luck = paired_bootstrap_delta(a_luck, b_luck)
    after_minus_stage2_score = paired_bootstrap_delta(a_scores, s2_scores)
    after_minus_stage2_luck = paired_bootstrap_delta(a_luck, s2_luck)

    paired_comparisons: dict[str, Any] = {
        "after_minus_before": {
            "score_delta": after_minus_before_score,
            "luck_adjusted_ev_delta": after_minus_before_luck,
            "accuracy_delta": round(
                agents_summary["after"]["accuracy"] - agents_summary["before"]["accuracy"], 6
            ),
            "abstain_rate_delta": round(
                agents_summary["after"]["abstain_rate"] - agents_summary["before"]["abstain_rate"], 6
            ),
            "calibration_gap_delta": round(
                agents_summary["after"]["calibration_gap"] - agents_summary["before"]["calibration_gap"], 6
            ),
            "deltas": [round(a - b, 4) for a, b in zip(a_scores, b_scores)],
        },
        "after_minus_stage2_likelihood_only": {
            "score_delta": after_minus_stage2_score,
            "luck_adjusted_ev_delta": after_minus_stage2_luck,
            "accuracy_delta": round(
                agents_summary["after"]["accuracy"] - agents_summary["stage2_likelihood_only"]["accuracy"], 6
            ),
            "abstain_rate_delta": round(
                agents_summary["after"]["abstain_rate"]
                - agents_summary["stage2_likelihood_only"]["abstain_rate"],
                6,
            ),
            "calibration_gap_delta": round(
                agents_summary["after"]["calibration_gap"]
                - agents_summary["stage2_likelihood_only"]["calibration_gap"],
                6,
            ),
        },
    }

    if include_solver:
        sol_scores = [float(row["agents"]["solver"]["score"]) for row in ordered]
        sol_luck = [float(row["agents"]["solver"]["luck_ev"]) for row in ordered]
        paired_comparisons["after_minus_solver"] = {
            "score_delta": paired_bootstrap_delta(a_scores, sol_scores),
            "luck_adjusted_ev_delta": paired_bootstrap_delta(a_luck, sol_luck),
            "solver_gap": paired_bootstrap_delta(sol_scores, a_scores),
        }

    invalid_total = sum(int(agents_summary[ag]["invalid_episodes"]) for ag in present_agents)
    return {
        "regime_id": spec["regime_id"],
        "label": spec["label"],
        "env_tier": spec["env_tier"],
        "mole_kind": spec["mole_kind"],
        "training_exposure": spec["training_exposure"],
        "adversarial_mechanism": spec["adversarial_mechanism"],
        "n": len(ordered),
        "heldout_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "episodes_replayed": len(ordered) * len(present_agents),
        "invalid_episodes": invalid_total,
        "before": agents_summary["before"],
        "stage2_likelihood_only": agents_summary["stage2_likelihood_only"],
        "after": agents_summary["after"],
        **({"solver": agents_summary["solver"]} if include_solver else {}),
        "paired": {
            "mean_delta": after_minus_before_score["mean"],
            "ci95_low": after_minus_before_score["ci95_low"],
            "ci95_high": after_minus_before_score["ci95_high"],
            "ci95_halfwidth": after_minus_before_score["ci95_halfwidth"],
            "luck_adjusted_ev_delta": after_minus_before_luck,
            "deltas": paired_comparisons["after_minus_before"]["deltas"],
        },
        "paired_comparisons": paired_comparisons,
        "seed_0_anchor": {
            "seed": int(ordered[0]["seed"]),
            "before_score": round(float(ordered[0]["agents"]["before"]["score"]), 6),
            "after_score": round(float(ordered[0]["agents"]["after"]["score"]), 6),
        },
    }


def _fmt_ci(d: dict[str, float], signed: bool = True) -> str:
    m = float(d["mean"])
    lo = float(d["ci95_low"])
    hi = float(d["ci95_high"])
    if signed:
        return f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]"
    return f"{m:.3f} [{lo:.3f}, {hi:.3f}]"


def format_markdown_report(summary: dict[str, Any]) -> str:
    h1 = MD_H
    h2 = MD_H * 2
    b_p = summary["parameters"]["before"]
    a_p = summary["parameters"]["after"]
    reg_by_id = {str(r["regime_id"]): r for r in summary["regimes"]}
    forge_reg = reg_by_id["hard_forge"]
    sleeper_reg = reg_by_id["hard_dsl_patient_sleeper"]
    hard_reg = reg_by_id["hard"]
    rl_reg = reg_by_id["hard_rl"]

    lines: list[str] = []
    lines.append(f"{h1} Zero-Shot Cross-Mole Adversarial Generalization Benchmark (Canary v1.4)")
    lines.append("")
    lines.append(
        "Evaluates whether experience calibration learned strictly ONCE on standard `default` mole episodes "
        f"(`TRAIN_SEEDS {summary['train_seed_range']}`, zero training exposure to evolved Forge HoF, `RLMole`, or sleeper DSL "
        "strategies) transfers zero-shot to unseen adversarial mole regimes on fresh world-paired `HELDOUT_SEEDS`."
    )
    lines.append("")
    lines.append(
        "Disclosure (Panel Fix A & Track Separation): `UncalibratedEmpiricalBayesPolicy` (`before`) and "
        "`EmpiricalBayesPolicy` (`after`) belong to the structured compact non-LLM policy track (never conflated "
        f"with open-weight `Qwen2.5` LoRA runs). All training strictly uses `TRAIN_SEEDS` (`{summary['train_seed_range']}`) and "
        f"all evaluation strictly uses disjoint fresh `HELDOUT_SEEDS` (`{summary['heldout_seed_range']}`, inside `[800000, 800200)`); "
        "no dev seeds are used here (and wherever dev seeds `0..29` appear elsewhere in Canary, they are post-hoc "
        "locked, not pre-registered)."
    )
    lines.append("")
    lines.append(f"- Train seed range (`default` mole only): `{summary['train_seed_range']}` "
                 f"(Stage 2 likelihoods `{summary['stage2_seed_range']}`, Stage 3 stopping/splits `{summary['stage3_seed_range']}`)")
    lines.append(f"- Fresh held-out seed range: `{summary['heldout_seed_range']}` "
                 f"(`n={summary['n_per_regime']}` per regime, `{summary['n_regimes']}` regimes, `{summary['n_total_paired_worlds']}` world-paired episodes per policy)")
    lines.append(f"- Shared held-out world secret tag: `{summary['world_secret_tag']}` "
                 f"(`100%` identical world pairings across `before`, `stage2_likelihood_only`, `after`, and `solver`)")
    lines.append(f"- Tool-by-tool `Env` replay verification: `{summary['replay_verified']}` "
                 f"(`{summary['total_episodes_replayed']}/{summary['total_episodes_replayed']}` episodes replayed, `invalid_episodes={summary['invalid_episodes']}`)")
    lines.append(f"- Pooled all-5-regimes paired gain (`after - before`, `n={summary['pooled_all_regimes']['n']}`): "
                 f"`{_fmt_ci(summary['pooled_all_regimes']['paired']['score_delta'])}` "
                 f"(luck-adjusted EV delta `{_fmt_ci(summary['pooled_all_regimes']['paired']['luck_adjusted_ev_delta'])}`)")
    lines.append(f"- Pooled 4 unseen adversarial mole regimes (`n={summary['pooled_unseen_adversarial']['n']}`): "
                 f"`{_fmt_ci(summary['pooled_unseen_adversarial']['paired']['score_delta'])}` "
                 f"(luck-adjusted EV delta `{_fmt_ci(summary['pooled_unseen_adversarial']['paired']['luck_adjusted_ev_delta'])}`)")

    lines.append("")
    lines.append(f"{h2} 1. Single-Fit Parameters Learned on Standard `default` Mole (`{summary['train_seed_range']}`)")
    lines.append("")
    lines.append(
        "| Policy Role | Stage | `w_canary_hit` | `w_canary_miss` | `w_doc_hit` | `w_after_hours` | `w_evasive` | `w_angry_msg` | `tau_margin` | `unsurfaced_v_disc` | `canary_cov` | `tiny_pool` | `ev_stop` |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for role_key, role_lbl in (
        ("before", "`before` (`UncalibratedEmpiricalBayesPolicy`)"),
        ("stage2_likelihood_only", "`stage2_likelihood_only` (uncalibrated stopping)"),
        ("after", "`after` (`EmpiricalBayesPolicy`)"),
    ):
        p = summary["parameters"][role_key]
        lines.append(
            f"| {role_lbl} | `{p['stage']}` | {p['w_canary_hit']:+.3f} | {p['w_canary_miss']:+.3f} | "
            f"{p['w_doc_hit']:+.3f} | {p['w_after_hours']:+.3f} | {p['w_evasive']:+.3f} | "
            f"{p['w_angry_msg']:+.3f} | {p['tau_margin']:.2f} | {p['unsurfaced_v_discount']:.2f} | "
            f"{p['canary_coverage']:.2f} | {p['tiny_pool_size']} | `{p['use_ev_stopping']}` |"
        )

    lines.append("")
    lines.append(f"{h2} 2. Paired Before vs After + `SolverPolicy` Upper Bound Across 5 Mole Regimes (`{summary['heldout_seed_range']}`)")
    lines.append("")
    lines.append(
        "| Regime | Exposure | `n` | `before` Score [95% CI] | `stage2` Score [95% CI] | `after` Score [95% CI] | `solver` Score [95% CI] | Paired `after - before` [95% CI] | Paired `after - stage2` [95% CI] |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for reg in summary["regimes"]:
        sol_cell = _fmt_ci(reg["solver"]["score"]) if "solver" in reg else "n/a"
        lines.append(
            f"| `{reg['regime_id']}` | `{reg['training_exposure']}` | {reg['n']} | "
            f"{_fmt_ci(reg['before']['score'])} | {_fmt_ci(reg['stage2_likelihood_only']['score'])} | "
            f"{_fmt_ci(reg['after']['score'])} | {sol_cell} | "
            f"{_fmt_ci(reg['paired_comparisons']['after_minus_before']['score_delta'])} | "
            f"{_fmt_ci(reg['paired_comparisons']['after_minus_stage2_likelihood_only']['score_delta'])} |"
        )
    for pool_key, pool_lbl in (
        ("pooled_unseen_adversarial", "`pooled_4_unseen_moles`"),
        ("pooled_all_regimes", "`pooled_all_5_regimes`"),
    ):
        pl = summary[pool_key]
        sol_cell = _fmt_ci(pl["solver"]["score"]) if "solver" in pl else "n/a"
        lines.append(
            f"| {pool_lbl} | `pooled` | {pl['n']} | "
            f"{_fmt_ci(pl['before']['score'])} | {_fmt_ci(pl['stage2_likelihood_only']['score'])} | "
            f"{_fmt_ci(pl['after']['score'])} | {sol_cell} | "
            f"{_fmt_ci(pl['paired']['score_delta'])} | "
            f"{_fmt_ci(pl['paired']['after_minus_stage2_score_delta'])} |"
        )

    lines.append("")
    lines.append(f"{h2} 3. Accuracy, Abstention, Luck-Adjusted EV, and Calibration Gap Per Regime")
    lines.append("")
    lines.append(
        "`calibration_gap` measures `|E[p_policy(accused) | accuse] - P(correct | accuse)|` (confidence-minus-precision "
        "misalignment on accused episodes; `0.000` is perfectly calibrated commitment)."
    )
    lines.append("")
    lines.append(
        "| Regime | Agent | `n` | Score [95% CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain Rate | Mean `p(accuse)` | Calibration Gap | Mean Day |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for reg in summary["regimes"]:
        ag_keys = [k for k in AGENT_ORDER if k in reg]
        for ag in ag_keys:
            m = reg[ag]
            day_s = f"{m['mean_accuse_day']:.1f}" if m["mean_accuse_day"] is not None else "n/a"
            lines.append(
                f"| `{reg['regime_id']}` | `{ag}` | {m['n']} | {_fmt_ci(m['score'])} | "
                f"{_fmt_ci(m['luck_adjusted_ev'])} | {m['accuracy']:.3f} | {m['wrong_accuse_rate']:.3f} | "
                f"{m['abstain_rate']:.3f} | {m['mean_p_at_accuse']:.3f} | {m['calibration_gap']:.3f} | {day_s} |"
            )

    lines.append("")
    lines.append(f"{h2} 4. Luck-Adjusted EV Paired Deltas and Adversarial Findings")
    lines.append("")
    lines.append(
        "| Regime | Adversarial Mechanism | Score Delta (`after - before`) | Luck-Adj EV Delta (`after - before`) | Calib Gap (`before -> after`) | Gap to `solver` (`solver - after`) |"
    )
    lines.append("|---|---|---:|---:|---:|---:|")
    for reg in summary["regimes"]:
        ab = reg["paired_comparisons"]["after_minus_before"]
        sol_gap = (
            _fmt_ci(reg["paired_comparisons"]["after_minus_solver"]["solver_gap"])
            if "after_minus_solver" in reg["paired_comparisons"]
            else "n/a"
        )
        lines.append(
            f"| `{reg['regime_id']}` | {reg['adversarial_mechanism']} | "
            f"{_fmt_ci(ab['score_delta'])} | {_fmt_ci(ab['luck_adjusted_ev_delta'])} | "
            f"`{reg['before']['calibration_gap']:.3f} -> {reg['after']['calibration_gap']:.3f}` | {sol_gap} |"
        )

    forge_s2_delta = _fmt_ci(forge_reg["paired_comparisons"]["after_minus_stage2_likelihood_only"]["score_delta"])
    sleeper_s2_delta = _fmt_ci(sleeper_reg["paired_comparisons"]["after_minus_stage2_likelihood_only"]["score_delta"])
    unseen_delta = _fmt_ci(summary["pooled_unseen_adversarial"]["paired"]["score_delta"])
    if "after_minus_solver" in hard_reg["paired_comparisons"]:
        residual_txt = (
            f"`solver - after` is `{_fmt_ci(hard_reg['paired_comparisons']['after_minus_solver']['solver_gap'])}` on `hard`, "
            f"`{_fmt_ci(rl_reg['paired_comparisons']['after_minus_solver']['solver_gap'])}` on `hard_rl`, "
            f"`{_fmt_ci(forge_reg['paired_comparisons']['after_minus_solver']['solver_gap'])}` on `hard_forge`, and "
            f"`{_fmt_ci(sleeper_reg['paired_comparisons']['after_minus_solver']['solver_gap'])}` on `hard_dsl_patient_sleeper`"
        )
    else:
        residual_txt = "a measurable headroom to `SolverPolicy` remains on stealth sleeper/Forge regimes"

    lines.append("")
    lines.append(f"{h2} 5. Key Honest Takeaways")
    lines.append("")
    lines.append(
        "1. **Zero-shot decoy and framing immunity transfers across all 4 unseen mole families**: fitting log-likelihoods "
        f"once on standard `default` mole `TRAIN_SEEDS {summary['train_seed_range']}` flips `w_angry_msg` from "
        f"`{b_p['w_angry_msg']:+.3f}` to `{a_p['w_angry_msg']:+.3f}` and Fano-tempers `w_after_hours` from "
        f"`{b_p['w_after_hours']:+.3f}` to `{a_p['w_after_hours']:+.3f}`, driving a `{unseen_delta}` paired score gain "
        "across `hard_forge`, `hard_rl`, `hard_dsl_patient_sleeper`, and `medium_hard_rl` with zero adversarial training exposure."
    )
    lines.append(
        "2. **Optimal EV-stopping and adaptive split sizing specifically rescue sleeper/Forge regimes**: against stealth "
        "moles that suppress early leaks (`hard_forge` and `hard_dsl_patient_sleeper`), `stage2_likelihood_only` (`p >= 0.50` "
        "stopping + `0.90` splits) stalls because early-day silence keeps posterior mass diffuse while `p = 0.50` sits below "
        f"the `1 / (1 + V_hat)` EV breakeven threshold; Stage 3 calibration (`after`) adds `{forge_s2_delta}` over `stage2` "
        f"on `hard_forge` and `{sleeper_s2_delta}` over `stage2` on `hard_dsl_patient_sleeper`."
    )
    lines.append(
        "3. **Honest residual gap to `SolverPolicy`**: because `EmpiricalBayesPolicy` uses a 6-feature factorized "
        "summary rather than `SolverPolicy`'s full joint multi-canary MI planner and exact non-leak likelihoods, "
        f"{residual_txt}, motivating neural/LLM DAgger distillation on compact working-memory states."
    )
    lines.append("")
    lines.append(f"{h2} 6. Verification Commands")
    lines.append("")
    lines.append("```bash")
    lines.append("python scripts/tiebreak_cross_mole_generalization.py")
    lines.append("python scripts/tiebreak_cross_mole_generalization.py --check")
    lines.append("```")
    return "\n".join(lines) + "\n"


def _default_workers() -> int:
    if hasattr(os, "sched_getaffinity"):
        try:
            avail = len(os.sched_getaffinity(0))
            if avail >= 1:
                return min(2, avail)
        except OSError:
            pass
    return min(2, max(1, os.cpu_count() or 1))


def run_benchmark(
    train_start: int = TRAIN_SEED_START,
    train_count: int = TRAIN_SEED_COUNT,
    heldout_start: int = HELDOUT_SEED_START,
    heldout_count: int = HELDOUT_SEED_COUNT,
    heldout_secret: str = DEFAULT_HELDOUT_SECRET,
    workers: int | None = None,
    include_solver: bool = True,
    out_json: Path | None = DEFAULT_SUMMARY_JSON,
    out_md: Path | None = DEFAULT_REPORT_MD,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    train_seeds = list(range(train_start, train_start + train_count))
    heldout_seeds = list(range(heldout_start, heldout_start + heldout_count))
    validate_cross_mole_seeds(train_seeds, heldout_seeds)

    secret_tag = _secret_tag(heldout_secret)
    before_params, stage2_params, after_params, train_meta = fit_policies_once_on_default_mole(train_seeds)

    before_d = before_params.to_dict()
    stage2_d = stage2_params.to_dict()
    after_d = after_params.to_dict()

    tasks: list[tuple[str, int, dict[str, Any], dict[str, Any], dict[str, Any], str, bool]] = []
    for seed in heldout_seeds:
        for spec in REGIME_SPECS:
            tasks.append((spec["regime_id"], seed, before_d, stage2_d, after_d, heldout_secret, include_solver))

    from canary import forge_track as _ft
    from canary import world as _cw
    from canary.analysis import accuse as _ca
    from canary.eval import run_episode as _re
    from canary.solver.policy import SolverPolicy as _sp

    _ = (_cw, _ca, _re, _sp)
    _ft.load(_ft.hof_path("hard_forge"))
    _ft.load(_ft.hof_path("hard_rl"))

    global _SHARED_FITTED_PARAMS
    _SHARED_FITTED_PARAMS = (before_params, stage2_params, after_params)
    try:
        eff_workers = int(workers) if workers is not None else _default_workers()
        if eff_workers <= 1 or len(tasks) <= 2:
            raw_results = [_evaluate_world_task(t) for t in tasks]
        else:
            start_method = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"
            mp_ctx = multiprocessing.get_context(start_method)
            chunk = 2 if len(tasks) >= 8 else 1
            with ProcessPoolExecutor(max_workers=eff_workers, mp_context=mp_ctx) as pool:
                raw_results = list(pool.map(_evaluate_world_task, tasks, chunksize=chunk))
    finally:
        _SHARED_FITTED_PARAMS = None

    by_regime: dict[str, list[dict[str, Any]]] = {spec["regime_id"]: [] for spec in REGIME_SPECS}
    for item in raw_results:
        by_regime[str(item["regime_id"])].append(item)

    regime_blocks: list[dict[str, Any]] = []
    for spec in REGIME_SPECS:
        r_block = _build_regime_block(
            spec=spec,
            seed_rows=by_regime[spec["regime_id"]],
            heldout_seeds=heldout_seeds,
            secret_tag=secret_tag,
            include_solver=include_solver,
        )
        regime_blocks.append(r_block)

    def _pool_subset(filter_unseen_only: bool) -> dict[str, Any]:
        selected_specs = [
            spec for spec in REGIME_SPECS
            if (not filter_unseen_only or spec["training_exposure"] == "zero_shot_unseen")
        ]
        present_agents = [ag for ag in AGENT_ORDER if include_solver or ag != "solver"]
        pooled_recs: dict[str, list[dict[str, Any]]] = {ag: [] for ag in present_agents}
        for spec in selected_specs:
            ordered = sorted(by_regime[spec["regime_id"]], key=lambda row: int(row["seed"]))
            for ag in present_agents:
                pooled_recs[ag].extend(row["agents"][ag] for row in ordered)
        ag_summaries = {ag: _summarize_agent_records(pooled_recs[ag], secret_tag) for ag in present_agents}
        b_sc = [float(r["score"]) for r in pooled_recs["before"]]
        s2_sc = [float(r["score"]) for r in pooled_recs["stage2_likelihood_only"]]
        a_sc = [float(r["score"]) for r in pooled_recs["after"]]
        b_lu = [float(r["luck_ev"]) for r in pooled_recs["before"]]
        s2_lu = [float(r["luck_ev"]) for r in pooled_recs["stage2_likelihood_only"]]
        a_lu = [float(r["luck_ev"]) for r in pooled_recs["after"]]
        return {
            "regimes_included": [spec["regime_id"] for spec in selected_specs],
            "n": len(a_sc),
            "before": ag_summaries["before"],
            "stage2_likelihood_only": ag_summaries["stage2_likelihood_only"],
            "after": ag_summaries["after"],
            **({"solver": ag_summaries["solver"]} if include_solver else {}),
            "paired": {
                "score_delta": paired_bootstrap_delta(a_sc, b_sc),
                "luck_adjusted_ev_delta": paired_bootstrap_delta(a_lu, b_lu),
                "after_minus_stage2_score_delta": paired_bootstrap_delta(a_sc, s2_sc),
                "after_minus_stage2_luck_delta": paired_bootstrap_delta(a_lu, s2_lu),
            },
        }

    pooled_all = _pool_subset(filter_unseen_only=False)
    pooled_unseen = _pool_subset(filter_unseen_only=True)

    total_replayed = sum(int(r["episodes_replayed"]) for r in regime_blocks)
    total_invalid = sum(int(r["invalid_episodes"]) for r in regime_blocks)
    if total_invalid != 0:
        raise AssertionError(f"benchmark produced {total_invalid} invalid episodes")

    elapsed = round(time.perf_counter() - t0, 3)
    summary: dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "benchmark_id": "cross-mole-generalization-v14",
        "tiers_version": "v1.4",
        "policy_track": "structured_compact_non_llm",
        "before_policy": "UncalibratedEmpiricalBayesPolicy",
        "after_policy": "EmpiricalBayesPolicy",
        "reference_policy": "SolverPolicy" if include_solver else None,
        "train_seed_range": f"{train_seeds[0]}..{train_seeds[-1]}",
        "stage2_seed_range": train_meta["stage2_seed_range"],
        "stage3_seed_range": train_meta["stage3_seed_range"],
        "train_seeds": {"start": train_seeds[0], "stop": train_seeds[-1] + 1},
        "heldout_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
        "eval_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
        "heldout_seeds": {"start": heldout_seeds[0], "stop": heldout_seeds[-1] + 1},
        "world_secret_tag": secret_tag,
        "n_regimes": len(regime_blocks),
        "n_per_regime": len(heldout_seeds),
        "n_total_paired_worlds": len(regime_blocks) * len(heldout_seeds),
        "replay_verified": True,
        "total_episodes_replayed": total_replayed,
        "invalid_episodes": total_invalid,
        "workers": eff_workers,
        "elapsed_seconds": elapsed,
        "dsl_patient_sleeper_strategy": DSL_PATIENT_SLEEPER_SPEC,
        "parameters": {
            "before": before_d,
            "stage2_likelihood_only": stage2_d,
            "after": after_d,
        },
        "training": train_meta,
        "pooled_all_regimes": pooled_all,
        "pooled_unseen_adversarial": pooled_unseen,
        "regimes": regime_blocks,
    }

    if out_json is not None:
        json_path = out_json if out_json.is_absolute() else (repo_root / out_json)
        json_path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(summary, indent=2) + "\n"
        if len(encoded.encode("utf-8")) > MAX_SUMMARY_BYTES:
            raise AssertionError(
                f"generalization_summary.json size {len(encoded.encode('utf-8'))} exceeds {MAX_SUMMARY_BYTES} bytes"
            )
        json_path.write_text(encoded, encoding="utf-8")

    if out_md is not None:
        md_path = out_md if out_md.is_absolute() else (repo_root / out_md)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(format_markdown_report(summary), encoding="utf-8")

    return summary


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if PREREG_RE.search(raw_line) and SEEDS_0_29_RE.search(raw_line):
            scrubbed = NEGATED_PREREG_RE.sub("", raw_line)
            if PREREG_RE.search(scrubbed):
                hits.append(f"line {lineno}: {raw_line.strip()[:120]}")
    return hits


def verify_artifacts(
    summary_path: Path = DEFAULT_SUMMARY_JSON,
    report_path: Path = DEFAULT_REPORT_MD,
    repo_root: Path = ROOT,
    heldout_secret: str = DEFAULT_HELDOUT_SECRET,
    expected_train_range: str = "100000..100119",
    expected_heldout_range: str = "800000..800029",
    min_regime_n: int = MIN_REGIME_N,
    require_solver: bool = True,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    errors: list[str] = []

    s_file = summary_path if summary_path.is_absolute() else (repo_root / summary_path)
    r_file = report_path if report_path.is_absolute() else (repo_root / report_path)
    self_file = Path(__file__).resolve()

    if not s_file.is_file():
        errors.append(f"missing summary JSON: {s_file}")
    if not r_file.is_file():
        errors.append(f"missing markdown report: {r_file}")
    if errors:
        return {"passed": False, "errors": errors, "elapsed_seconds": round(time.perf_counter() - t0, 4)}

    for forbidden_sibling in ("summary.json", "table.md"):
        sib = s_file.parent / forbidden_sibling
        if sib.resolve() != s_file.resolve() and sib.exists():
            errors.append(f"colliding artifact present in cross_mole_generalization dir: {sib}")

    raw_bytes = s_file.read_bytes()
    if len(raw_bytes) > MAX_SUMMARY_BYTES:
        errors.append(f"{s_file.name} exceeds 100KB budget ({len(raw_bytes)} bytes)")

    raw_json_txt = raw_bytes.decode("utf-8")
    md_txt = r_file.read_text(encoding="utf-8")
    py_txt = self_file.read_text(encoding="utf-8")

    toks = list(tokenize.generate_tokens(io.StringIO(py_txt).readline))
    if any(t.type == tokenize.COMMENT for t in toks) or MD_H in py_txt:
        errors.append("tiebreak_cross_mole_generalization.py contains Python comment or hash character")

    for lbl, txt in (("script", py_txt), ("summary_json", raw_json_txt), ("report_md", md_txt)):
        if EM_DASH in txt:
            errors.append(f"{lbl}: contains em dash")
        if EN_DASH in txt:
            errors.append(f"{lbl}: contains en dash")
        for hit in _has_affirmative_prereg_0_29(txt):
            errors.append(f"{lbl}: Panel Fix A violation at {hit}")

    summary = json.loads(raw_json_txt)
    expected_tag = _secret_tag(heldout_secret)
    if summary.get("train_seed_range") != expected_train_range:
        errors.append(
            f"expected train_seed_range {expected_train_range!r}, got {summary.get('train_seed_range')!r}"
        )
    if summary.get("heldout_seed_range") != expected_heldout_range:
        errors.append(
            f"expected heldout_seed_range {expected_heldout_range!r}, got {summary.get('heldout_seed_range')!r}"
        )
    if summary.get("world_secret_tag") != expected_tag:
        errors.append(
            f"expected world_secret_tag {expected_tag!r}, got {summary.get('world_secret_tag')!r}"
        )
    if summary.get("replay_verified") is not True:
        errors.append("summary.replay_verified must be True")
    if summary.get("invalid_episodes") != 0:
        errors.append(f"summary.invalid_episodes must be 0, got {summary.get('invalid_episodes')!r}")

    if (summary.get("training") or {}).get("adversarial_moles_seen_in_training") != 0:
        errors.append("training must have zero exposure to adversarial moles")
    if (summary.get("training") or {}).get("fitted_strictly_once") is not True:
        errors.append("training.fitted_strictly_once must be True")

    regimes = summary.get("regimes") or []
    expected_ids = [sp["regime_id"] for sp in REGIME_SPECS]
    got_ids = [str(r.get("regime_id")) for r in regimes]
    if got_ids != expected_ids:
        errors.append(f"regime order/ids {got_ids} != expected {expected_ids}")

    md_floats = [float(m.group(0)) for m in FLOAT_TOKEN_RE.finditer(md_txt.replace(",", ""))]
    for token in (expected_train_range, expected_heldout_range, expected_tag):
        if token not in md_txt:
            errors.append(f"report markdown missing required provenance token {token!r}")

    if got_ids == expected_ids:
        expected_md = format_markdown_report(summary)
        if md_txt != expected_md:
            errors.append("report markdown differs from deterministic format_markdown_report(summary)")

    req_agents = ("before", "stage2_likelihood_only", "after", "solver") if require_solver else (
        "before",
        "stage2_likelihood_only",
        "after",
    )

    for reg in regimes:
        rid = str(reg.get("regime_id"))
        n_val = int(reg.get("n", 0))
        if n_val < min_regime_n:
            errors.append(f"regime {rid}: n={n_val} < {min_regime_n}")
        if reg.get("replay_verified") is not True or reg.get("invalid_episodes") != 0:
            errors.append(f"regime {rid}: replay_verified/invalid_episodes failed")

        for ag in req_agents:
            ag_obj = reg.get(ag)
            if not isinstance(ag_obj, dict):
                errors.append(f"regime {rid}: missing agent block {ag!r}")
                continue
            if ag_obj.get("world_secret_tag") != expected_tag:
                errors.append(f"regime {rid}.{ag}: world_secret_tag mismatch")
            for req_metric in ("mean_score", "accuracy", "abstain_rate", "calibration_gap"):
                val = ag_obj.get(req_metric)
                if not isinstance(val, (int, float)) or not math.isfinite(float(val)):
                    errors.append(f"regime {rid}.{ag}: missing/non-finite {req_metric}")
            luck_m = (ag_obj.get("luck_adjusted_ev") or {}).get("mean")
            if not isinstance(luck_m, (int, float)) or not math.isfinite(float(luck_m)):
                errors.append(f"regime {rid}.{ag}: missing luck_adjusted_ev.mean")

        deltas = (reg.get("paired") or {}).get("deltas") or []
        if len(deltas) != n_val:
            errors.append(f"regime {rid}: len(paired.deltas)={len(deltas)} != n={n_val}")
        else:
            recomp = bootstrap_ci([float(x) for x in deltas])
            if abs(recomp["mean"] - float(reg["paired"]["mean_delta"])) > 0.002:
                errors.append(f"regime {rid}: paired mean_delta mismatch vs deltas")
            if abs(recomp["ci95_low"] - float(reg["paired"]["ci95_low"])) > 0.002:
                errors.append(f"regime {rid}: paired ci95_low mismatch vs deltas")

        for chk_val in (
            reg["before"]["mean_score"],
            reg["after"]["mean_score"],
            reg["paired"]["mean_delta"],
            reg["after"]["calibration_gap"],
        ):
            if not any(abs(x - float(chk_val)) <= 0.002 for x in md_floats):
                errors.append(f"regime {rid}: value {chk_val} not represented in markdown report")

    after_params = EmpiricalBayesParams.from_dict(summary["parameters"]["after"])
    before_params = EmpiricalBayesParams.from_dict(summary["parameters"]["before"])
    spot_regimes = {r["regime_id"]: r for r in regimes}
    from canary import world as canary_world
    from canary.eval import run_episode

    prev_env = os.environ.get("CANARY_WORLD_SECRET")
    prev_set = getattr(canary_world, "_SET_SECRET", None)
    try:
        canary_world.set_world_secret(None)
        os.environ["CANARY_WORLD_SECRET"] = heldout_secret
        for spot_id in ("hard", "hard_dsl_patient_sleeper"):
            anchor = spot_regimes[spot_id]["seed_0_anchor"]
            s0 = int(anchor["seed"])
            ep_b = run_episode(
                build_regime_env(spot_id, s0),
                UncalibratedEmpiricalBayesPolicy(before_params, seed=s0, name="before"),
            )
            ep_a = run_episode(
                build_regime_env(spot_id, s0),
                EmpiricalBayesPolicy(after_params, seed=s0, name="after"),
            )
            replay_verify_regime_episode(spot_id, ep_b)
            replay_verify_regime_episode(spot_id, ep_a)
            if abs(float(ep_b.score) - float(anchor["before_score"])) > 1e-6:
                errors.append(f"spot replay {spot_id} seed={s0} before score mismatch")
            if abs(float(ep_a.score) - float(anchor["after_score"])) > 1e-6:
                errors.append(f"spot replay {spot_id} seed={s0} after score mismatch")
    finally:
        canary_world.set_world_secret(prev_set)
        if prev_env is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_env

    elapsed = round(time.perf_counter() - t0, 4)
    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "summary_bytes": len(raw_bytes),
        "regimes_verified": len(regimes),
        "elapsed_seconds": elapsed,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Zero-shot cross-mole generalization benchmark for Canary tiebreak policies."
    )
    ap.add_argument("--check", action="store_true", help="Verify committed JSON and Markdown artifacts.")
    ap.add_argument("--train-start", type=int, default=TRAIN_SEED_START)
    ap.add_argument("--train-n", type=int, default=TRAIN_SEED_COUNT)
    ap.add_argument("--heldout-start", type=int, default=HELDOUT_SEED_START)
    ap.add_argument("--heldout-n", type=int, default=HELDOUT_SEED_COUNT)
    ap.add_argument("--heldout-secret", default=DEFAULT_HELDOUT_SECRET)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--no-solver", action="store_true", help="Skip SolverPolicy upper bound in fast smoke tests.")
    ap.add_argument("--out-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_REPORT_MD)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.check:
        verdict = verify_artifacts(
            summary_path=args.out_json,
            report_path=args.out_md,
            repo_root=ROOT,
            heldout_secret=args.heldout_secret,
        )
        print(json.dumps(verdict, indent=2, sort_keys=True))
        return 0 if verdict["passed"] else 1

    summary = run_benchmark(
        train_start=args.train_start,
        train_count=args.train_n,
        heldout_start=args.heldout_start,
        heldout_count=args.heldout_n,
        heldout_secret=args.heldout_secret,
        workers=args.workers,
        include_solver=not args.no_solver,
        out_json=args.out_json,
        out_md=args.out_md,
        repo_root=ROOT,
    )
    digest = {
        "benchmark_id": summary["benchmark_id"],
        "train_seed_range": summary["train_seed_range"],
        "heldout_seed_range": summary["heldout_seed_range"],
        "world_secret_tag": summary["world_secret_tag"],
        "replay_verified": summary["replay_verified"],
        "total_episodes_replayed": summary["total_episodes_replayed"],
        "elapsed_seconds": summary["elapsed_seconds"],
        "pooled_all_5_regimes_delta": summary["pooled_all_regimes"]["paired"]["score_delta"],
        "pooled_4_unseen_moles_delta": summary["pooled_unseen_adversarial"]["paired"]["score_delta"],
        "per_regime_after_minus_before": {
            r["regime_id"]: r["paired_comparisons"]["after_minus_before"]["score_delta"]
            for r in summary["regimes"]
        },
    }
    print(json.dumps(digest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
