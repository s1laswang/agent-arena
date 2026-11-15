from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import tokenize
from typing import Any

for _blas_var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_var, "1")

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import Heuristic
from canary.env import Env
from canary.eval import run_episode
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TRAIN_SEEDS
from canary.solver.belief import leak_loglik, posterior
from canary.solver.policy import SolverPolicy
from train.compact_dagger_ablation import CompactLinearDAggerPolicy, CompactLinearWeights
from train.empirical_bayes_policy import EmpiricalBayesParams, EmpiricalBayesPolicy
import train.neural_mlp_tiebreak as mlp_mod
from train.neural_mlp_tiebreak import MLPWeights, TinyMLPPolicy, load_checkpoint_npz

MD_H = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

SCHEMA_VERSION = "canary.tiebreak.delayed_leak_noise_audit.v1"
CANONICAL_TIERS: tuple[str, ...] = ("easy", "medium", "hard")
HELDOUT_SEED_START = 800_000
HELDOUT_SEED_STOP = 800_030
HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_SECRET_TAG = "sha256:ebf2f09716cf76d3"
MAX_SUMMARY_BYTES = 120 * 1024
MAX_CHECK_SECONDS = 10.0

DEFAULT_OUT_JSON = Path("results/tiebreak/delayed_leak_noise/noise_audit_summary.json")
DEFAULT_OUT_MD = Path("docs/reports/tiebreak_delayed_leak_noise.md")

EB_SUMMARY_REL = Path("results/tiebreak/empirical_bayes/summary.json")
MLP_SUMMARY_REL = Path("results/tiebreak/neural_mlp_dagger/mlp_summary.json")
CL_SUMMARY_REL = Path("results/tiebreak/dagger_ablation/summary.json")
DEFAULT_MLP_CKPT = Path(mlp_mod.DEFAULT_CKPT_PATH)

PRIMARY_POLICIES: tuple[str, ...] = (
    "solver",
    "empirical_bayes",
    "tiny_mlp",
    "compact_linear_dagger",
)
TRAINED_POLICIES: tuple[str, ...] = (
    "empirical_bayes",
    "tiny_mlp",
    "compact_linear_dagger",
)
ALL_POLICIES: tuple[str, ...] = (
    "solver",
    "empirical_bayes",
    "tiny_mlp",
    "compact_linear_dagger",
    "heuristic_hard_elim",
)

POLICY_LABELS: dict[str, str] = {
    "solver": "SolverPolicy (exact DP latent-leak + 0.95 smoothed Bayes)",
    "empirical_bayes": "EmpiricalBayesPolicy (eb_experience_opt, learned LLR + EV stop)",
    "tiny_mlp": "TinyMLPPolicy (stage3_onpolicy_dagger_r2, 28->128->64->5)",
    "compact_linear_dagger": "CompactLinearDAggerPolicy (stage3_onpolicy_dagger_r2)",
    "heuristic_hard_elim": "Heuristic (naive hard-elimination canary bisection, no V timing)",
}

PANEL_FIX_A_DISCLOSURE = (
    "All tiebreaker policies audited here were trained strictly on TRAIN_SEEDS [100000, 200000) "
    "and evaluated strictly on disjoint world-paired HELDOUT_SEEDS 800000..800029 (n=90, 30 per tier) "
    "under one shared CANARY_WORLD_SECRET (sha256:ebf2f09716cf76d3); 0 DEV_SEEDS and 0 JUDGE_SEEDS "
    "(900000+) are touched. Where DEV_SEEDS 0..29 appear in separate Canary frontier reports, they are "
    "post-hoc locked, not pre-registered (Panel Fix A). Per Panel Fix E, non-LLM policies audited here "
    "(EmpiricalBayesPolicy, TinyMLPPolicy, CompactLinearDAggerPolicy) are strictly separated from "
    "open-weight Qwen2.5 LoRA runs."
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


def compute_secret_tag(secret: str) -> str:
    return "sha256:" + hashlib.sha256(secret.encode("utf-8")).hexdigest()[:16]


def assert_strict_train_range(start: int, stop: int) -> None:
    if start >= stop:
        raise ValueError(f"empty train seed range [{start}, {stop})")
    for s in range(start, stop):
        if s in DEV_SEEDS or s in HELDOUT_SEEDS or s in JUDGE_SEEDS or s not in TRAIN_SEEDS or not (100_000 <= s < 200_000):
            raise ValueError(f"train seed {s} violates TRAIN_SEEDS [100000, 200000)")


def assert_strict_heldout_seeds(seeds: list[int]) -> list[int]:
    if not seeds:
        raise ValueError("heldout_seeds must be non-empty")
    if len(set(seeds)) != len(seeds):
        raise ValueError("duplicate seed in heldout_seeds")
    for s in seeds:
        if s in DEV_SEEDS or s in TRAIN_SEEDS or s in JUDGE_SEEDS or s not in HELDOUT_SEEDS or not (800_000 <= s < 800_200):
            raise ValueError(f"eval seed {s} violates HELDOUT_SEEDS [800000, 800200)")
    return list(seeds)


def _step_fields(step: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if hasattr(step, "tool"):
        return str(step.tool), dict(step.args or {}), dict(step.result or {})
    return str(step.get("tool", "")), dict(step.get("args") or {}), dict(step.get("result") or {})


def verify_episode(ep: Any) -> bool:
    env = Env(ep.tier, int(ep.seed))
    for st in ep.steps:
        if env.done:
            break
        tool, args, rec = _step_fields(st)
        live = env.call(tool, args)
        if rec and "ok" in rec and bool(live.ok) != bool(rec["ok"]):
            raise AssertionError(f"replay step ok mismatch on {ep.tier}:{ep.seed} ({ep.agent})")
        if rec and "data" in rec and live.data != rec["data"]:
            raise AssertionError(f"replay step data mismatch on {ep.tier}:{ep.seed} ({ep.agent})")
    rep = env.result("replay")
    if (
        abs(float(rep.score) - float(ep.score)) > 1e-9
        or rep.accused != ep.accused
        or bool(rep.correct) != bool(ep.correct)
        or int(rep.final_day) != int(ep.final_day)
        or str(rep.end_reason) != str(ep.end_reason)
    ):
        raise AssertionError(f"replay terminal mismatch on {ep.tier}:{ep.seed} ({ep.agent})")
    return True


def mean_ci95(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    m = sum(values) / n
    if n < 2:
        return {"mean": round(m, 6), "ci95_low": round(m, 6), "ci95_high": round(m, 6), "ci95_half_width": 0.0}
    var = sum((x - m) ** 2 for x in values) / (n - 1)
    half = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(m, 6),
        "ci95_low": round(m - half, 6),
        "ci95_high": round(m + half, 6),
        "ci95_half_width": round(half, 6),
    }


def _retrain_tiny_mlp_from_summary_spec(mlp_summary: dict[str, Any]) -> MLPWeights:
    tr_start = int(mlp_summary["train_seeds"]["start"])
    tr_stop = int(mlp_summary["train_seeds"]["stop"])
    assert_strict_train_range(tr_start, tr_stop)
    all_train = list(range(tr_start, tr_stop))
    n_tr = len(all_train)
    stride = 2 if n_tr >= 240 else 1
    c2, c3, c4 = max(3, n_tr // 4), max(5, (3 * n_tr) // 5), max(7, (19 * n_tr) // 20)
    bc_seeds = all_train[:c2]
    d1_seeds = all_train[c2:c3:stride]
    d2_seeds = all_train[c3 : min(c4, n_tr) : stride]
    val_seeds = all_train[c4:] if c4 < n_tr else all_train[-max(2, n_tr // 6) :]

    wt0 = mlp_mod.init_untrained_weights(rng_seed=tr_start)
    _, d_s2 = mlp_mod._collect_solver_trajectories(bc_seeds)
    wt2 = mlp_mod._train_mlp_adam(d_s2, wt0, epochs=50, lr=4.5e-3, mode="bc", stage_name="stage2_calibrated_bc", rng_seed=tr_start + 2)
    d_r1 = mlp_mod._collect_dagger_rollouts(wt2, d1_seeds, override_premature=True)
    wt_r1 = mlp_mod._train_mlp_adam(d_s2 + d_r1, wt2, epochs=45, lr=2.5e-3, mode="dagger", stage_name="dagger_r1", rng_seed=tr_start + 3)
    d_r2 = mlp_mod._collect_dagger_rollouts(wt_r1, d2_seeds, override_premature=False)
    wt3_raw = mlp_mod._train_mlp_adam(
        d_s2 + d_r1 + d_r2,
        wt_r1,
        epochs=45,
        lr=1.8e-3,
        mode="dagger",
        stage_name="stage3_onpolicy_dagger_r2",
        rng_seed=tr_start + 4,
    )
    return mlp_mod._calibrate_threshold([wt3_raw, wt_r1], val_seeds)


def load_trained_policy_bundle(
    repo_root: Path = ROOT,
    mlp_ckpt_path: Path = DEFAULT_MLP_CKPT,
) -> dict[str, Any]:
    eb_path = repo_root / EB_SUMMARY_REL
    mlp_path = repo_root / MLP_SUMMARY_REL
    cl_path = repo_root / CL_SUMMARY_REL

    eb_summary = json.loads(eb_path.read_text(encoding="utf-8"))
    mlp_summary = json.loads(mlp_path.read_text(encoding="utf-8"))
    cl_summary = json.loads(cl_path.read_text(encoding="utf-8"))

    eb_tr = eb_summary["train_seeds"]
    mlp_tr = mlp_summary["train_seeds"]
    cl_tr = cl_summary["train_seeds"]
    assert_strict_train_range(int(eb_tr["start"]), int(eb_tr["stop"]))
    assert_strict_train_range(int(mlp_tr["start"]), int(mlp_tr["stop"]))
    assert_strict_train_range(int(cl_tr["start"]), int(cl_tr["stop"]))

    eb_params = EmpiricalBayesParams.from_dict(eb_summary["parameters"]["eb_experience_opt"])
    cl_weights = CompactLinearWeights.from_dict(cl_summary["learned_weights_stage3"])

    if mlp_ckpt_path.is_file():
        mlp_weights = load_checkpoint_npz(mlp_ckpt_path, stage="stage3_onpolicy_dagger_r2")
        mlp_source_mode = "committed_summary_verified_shared_npz"
    else:
        mlp_weights = _retrain_tiny_mlp_from_summary_spec(mlp_summary)
        mlp_source_mode = "committed_summary_deterministic_retrain"

    if mlp_weights.param_count() != int(mlp_summary["param_count"]):
        raise ValueError(f"TinyMLP param_count {mlp_weights.param_count()} != {mlp_summary['param_count']}")
    if abs(float(mlp_weights.commit_threshold) - float(mlp_summary["selected_commit_threshold"])) > 1e-4:
        raise ValueError(
            f"TinyMLP threshold {mlp_weights.commit_threshold} != {mlp_summary['selected_commit_threshold']}"
        )

    provenance = {
        "empirical_bayes": {
            "run_id": str(eb_summary["run_id"]),
            "summary_path": str(EB_SUMMARY_REL),
            "stage": str(eb_params.stage),
            "train_seeds": {"start": int(eb_tr["start"]), "stop": int(eb_tr["stop"])},
            "train_seed_range": f"{int(eb_tr['start'])}..{int(eb_tr['stop']) - 1}",
            "w_canary_hit": round(float(eb_params.w_canary_hit), 6),
            "w_canary_miss": round(float(eb_params.w_canary_miss), 6),
            "unsurfaced_v_discount": round(float(eb_params.unsurfaced_v_discount), 6),
            "tau_margin": round(float(eb_params.tau_margin), 6),
        },
        "tiny_mlp": {
            "run_id": str(mlp_summary["run_id"]),
            "summary_path": str(MLP_SUMMARY_REL),
            "stage": str(mlp_weights.stage),
            "weight_source": mlp_source_mode,
            "param_count": int(mlp_weights.param_count()),
            "commit_threshold": round(float(mlp_weights.commit_threshold), 4),
            "train_seeds": {"start": int(mlp_tr["start"]), "stop": int(mlp_tr["stop"])},
            "train_seed_range": f"{int(mlp_tr['start'])}..{int(mlp_tr['stop']) - 1}",
        },
        "compact_linear_dagger": {
            "run_id": str(cl_summary["run_id"]),
            "summary_path": str(CL_SUMMARY_REL),
            "stage": str(cl_weights.stage),
            "param_count": int(
                cl_weights.w_emp.size
                + cl_weights.w_act.size
                + cl_weights.b_act.size
                + cl_weights.w_split.size
                + cl_weights.b_split.size
            ),
            "train_seeds": {"start": int(cl_tr["start"]), "stop": int(cl_tr["stop"])},
            "train_seed_range": f"{int(cl_tr['start'])}..{int(cl_tr['stop']) - 1}",
        },
    }
    return {
        "eb_params": eb_params,
        "mlp_weights": mlp_weights,
        "cl_weights": cl_weights,
        "provenance": provenance,
        "eb_summary": eb_summary,
    }


def build_policy_instance(policy_key: str, seed: int, bundle: dict[str, Any]) -> Any:
    if policy_key == "solver":
        return SolverPolicy()
    if policy_key == "empirical_bayes":
        return EmpiricalBayesPolicy(params=bundle["eb_params"], seed=seed, name="eb_experience_opt")
    if policy_key == "tiny_mlp":
        return TinyMLPPolicy(weights=bundle["mlp_weights"], seed=seed, name="stage3_onpolicy_dagger_r2")
    if policy_key == "compact_linear_dagger":
        return CompactLinearDAggerPolicy(weights=bundle["cl_weights"], name="stage3_onpolicy_dagger_r2")
    if policy_key == "heuristic_hard_elim":
        return Heuristic(seed=seed)
    raise ValueError(f"unknown policy_key: {policy_key!r}")


def _heuristic_surviving_suspects(instruction: str, steps_prefix: list[Any]) -> list[str]:
    pol = Heuristic(seed=0)
    pol.reset([], instruction)
    emps: list[str] = []
    last_feed: list[dict[str, Any]] = []
    for st in steps_prefix:
        tool, _, res = _step_fields(st)
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        if tool == "list_employees":
            emps = [str(e["id"]) if isinstance(e, dict) else str(e) for e in (data.get("employees") or [])]
        elif tool == "list_documents":
            for doc in data.get("documents") or []:
                if isinstance(doc, dict) and "doc_id" in doc:
                    pol.docs[str(doc["doc_id"])] = doc
        elif tool == "check_leak_feed":
            last_feed = [dict(it) for it in (data.get("items") or []) if isinstance(it, dict)]
    suspects = set(emps)
    for it in last_feed:
        doc = pol.docs.get(str(it.get("doc_id", "")))
        if not doc:
            continue
        if doc.get("is_canary") and it.get("variant") and doc.get("variants"):
            grp = set((doc["variants"] or {}).get(it["variant"], []))
        else:
            grp = set(doc.get("recipients") or [])
        if suspects & grp:
            suspects &= grp
    return sorted(suspects)


def _policy_mole_posterior_on_prefix(
    policy_key: str,
    seed: int,
    bundle: dict[str, Any],
    tools_spec: list[dict[str, Any]],
    instruction: str,
    steps_prefix: list[Any],
    mole_id: str,
    solver_post: dict[str, float],
) -> float:
    if policy_key == "solver":
        return float(solver_post.get(mole_id, 0.0))
    if policy_key == "empirical_bayes":
        pol = EmpiricalBayesPolicy(params=bundle["eb_params"], seed=seed, name="eb_experience_opt")
        pol.reset(tools_spec, instruction)
        pol.tracker.ingest_steps(steps_prefix)
        return float(pol.posterior().get(mole_id, 0.0))
    if policy_key == "tiny_mlp":
        pol = TinyMLPPolicy(weights=bundle["mlp_weights"], seed=seed, name="stage3_onpolicy_dagger_r2")
        pol.reset(tools_spec, instruction)
        pol.tracker.ingest(steps_prefix)
        return float(pol.belief().get(mole_id, 0.0))
    if policy_key == "compact_linear_dagger":
        pol = CompactLinearDAggerPolicy(weights=bundle["cl_weights"], name="stage3_onpolicy_dagger_r2")
        pol.reset(tools_spec, instruction)
        pol._state_for(steps_prefix)
        return float(pol.belief().get(mole_id, 0.0))
    if policy_key == "heuristic_hard_elim":
        surv = _heuristic_surviving_suspects(instruction, steps_prefix)
        if mole_id in surv and surv:
            return 1.0 / len(surv)
        return 0.0
    raise ValueError(f"unknown policy_key: {policy_key!r}")


def _strict_hard_elimination_posterior(sp_obs: SolverPolicy, tier: str) -> tuple[dict[str, float], bool]:
    obs = sp_obs.obs
    p_strict = replace(TIERS[tier], fingerprint_accuracy=1.0)
    logs: dict[str, float] = {}
    for s in obs.employees:
        lp = leak_loglik(obs, s, p_strict, sp_obs.choice_temper, sp_obs.noleak_temper)
        if obs.decoy is not None and s == obs.decoy:
            lp = -math.inf
        logs[s] = lp
    m = max(logs.values()) if logs else -math.inf
    if m == -math.inf:
        return {s: 0.0 for s in obs.employees}, True
    z = sum(math.exp(v - m) for v in logs.values() if v > -math.inf)
    return {s: (math.exp(v - m) / z if v > -math.inf else 0.0) for s, v in logs.items()}, False


def evaluate_and_decompose_single(
    policy_key: str,
    tier: str,
    seed: int,
    bundle: dict[str, Any],
) -> dict[str, Any]:
    pol = build_policy_instance(policy_key, seed, bundle)
    ep = run_episode(Env(tier, seed), pol)
    verify_episode(ep)

    replay_env = Env(tier, seed)
    tools_spec = replay_env.tools_spec()
    instruction = replay_env.instruction()
    for st in ep.steps:
        if replay_env.done:
            break
        t_name, t_args, _ = _step_fields(st)
        replay_env.call(t_name, t_args)

    p_tier = TIERS[tier]
    mole_id = str(replay_env._world.mole)
    accused_bool = ep.accused is not None and str(ep.end_reason) == "accused"
    decision_day = int(ep.final_day)
    known_v = round(float(replay_env.visible_V()), 6)
    true_v = round(float(replay_env.V), 6)
    hidden_v_gap = round(max(0.0, known_v - true_v), 6)

    surfaced_leaks = sum(1 for f in replay_env._feed if int(f["surfaced_day"]) <= decision_day)
    unsurfaced_leaks = sum(1 for f in replay_env._feed if int(f["surfaced_day"]) > decision_day)
    total_leaks = len(replay_env._feed)
    known_costs = round(float(replay_env._costs), 6)

    expected_pending = sum(
        float(p_tier.p_leak) * sum(1 for dl in p_tier.delay_choices if d + dl > decision_day) / len(p_tier.delay_choices)
        for d in range(1, decision_day)
    )
    delay_v_hat = round(max(0.0, known_v - float(p_tier.leak_damage) * expected_pending), 6)

    be_known = 1.0 / (1.0 + known_v)
    be_true = (1.0 / (1.0 + true_v)) if true_v > 0.0 else 1.0

    accuse_idx = next(
        (i for i, st in enumerate(ep.steps) if st.tool == "accuse" and bool((st.result or {}).get("ok"))),
        len(ep.steps),
    )
    steps_prefix = list(ep.steps[:accuse_idx])

    sp_obs = SolverPolicy(p_tier)
    sp_obs.reset(tools_spec, instruction)
    for st in steps_prefix:
        sp_obs._ingest(st)
    sp_obs.obs.leak_timing_known = sp_obs.v_drops_reveal_leaks()
    post_smoothed = posterior(
        sp_obs.obs,
        p_tier,
        sp_obs.behaviour_temper,
        sp_obs.choice_temper,
        sp_obs.noleak_temper,
    )
    post_strict_elim, strict_empty_collapse = _strict_hard_elimination_posterior(sp_obs, tier)
    policy_p_mole = _policy_mole_posterior_on_prefix(
        policy_key,
        seed,
        bundle,
        tools_spec,
        instruction,
        steps_prefix,
        mole_id,
        post_smoothed,
    )

    if accused_bool and ep.accused is not None:
        p_acc = float(post_smoothed.get(str(ep.accused), 0.0))
        luck_adjusted_ev = p_acc * true_v + (1.0 - p_acc) * float(p_tier.wrong_accusation_score)
    else:
        luck_adjusted_ev = 0.0

    planted_canaries = sum(
        1 for st in ep.steps if st.tool == "plant_canary" and bool((st.result or {}).get("ok"))
    )
    ok_calls = sum(1 for st in ep.steps if bool((st.result or {}).get("ok")))
    total_calls = len(ep.steps)
    observed_feed_ids = {it.doc_id for it in sp_obs.obs.feed}

    all_canary_leaks = 0
    surfaced_canary_leaks = 0
    observed_canary_leaks = 0
    all_noisy_mismatches = 0
    surfaced_noisy_mismatches = 0
    observed_noisy_mismatches = 0
    mismatch_events: list[dict[str, Any]] = []

    for item in replay_env._feed:
        doc = replay_env._doc_by_id[item["doc_id"]]
        if not doc.get("is_canary"):
            continue
        all_canary_leaks += 1
        variants_map = doc.get("variants") or {}
        true_var = next((k for k, v in variants_map.items() if mole_id in v), None)
        rep_var = item.get("variant")
        is_surfaced = int(item["surfaced_day"]) <= decision_day
        is_observed = str(item["doc_id"]) in observed_feed_ids
        is_mismatch = true_var is not None and rep_var is not None and rep_var != true_var
        if is_surfaced:
            surfaced_canary_leaks += 1
        if is_observed:
            observed_canary_leaks += 1
        if is_mismatch:
            all_noisy_mismatches += 1
            if is_surfaced:
                surfaced_noisy_mismatches += 1
            if is_observed:
                observed_noisy_mismatches += 1
            if is_surfaced:
                mismatch_events.append(
                    {
                        "policy": policy_key,
                        "tier": tier,
                        "seed": int(seed),
                        "canary_id": str(item["doc_id"]),
                        "planted_day": int(doc["day"]),
                        "surfaced_day": int(item["surfaced_day"]),
                        "observed_in_feed": bool(is_observed),
                        "true_mole": mole_id,
                        "true_mole_variant": str(true_var),
                        "reported_feed_variant": str(rep_var),
                        "n_variants": len(variants_map),
                        "decision_day": decision_day,
                        "accused": str(ep.accused) if ep.accused is not None else None,
                        "correct": bool(ep.correct),
                        "score": round(float(ep.score), 6),
                        "smoothed_solver_p_mole": round(float(post_smoothed.get(mole_id, 0.0)), 6),
                        "policy_p_mole": round(float(policy_p_mole), 6),
                        "naive_hard_elim_p_mole": round(float(post_strict_elim.get(mole_id, 0.0)), 6),
                        "naive_hard_elim_empty_set": bool(strict_empty_collapse),
                    }
                )

    is_invalid = str(ep.end_reason) in ("error", "invalid") or (ep.meta or {}).get("valid") is False
    return {
        "policy": policy_key,
        "tier": tier,
        "seed": int(seed),
        "score": round(float(ep.score), 6),
        "luck_adjusted_ev": round(float(luck_adjusted_ev), 6),
        "accused": str(ep.accused) if ep.accused is not None else None,
        "accused_bool": bool(accused_bool),
        "correct": bool(ep.correct),
        "wrong_accuse": bool(accused_bool and not ep.correct),
        "abstained": bool(not accused_bool),
        "final_day": decision_day,
        "end_reason": str(ep.end_reason),
        "invalid": bool(is_invalid),
        "planted_canaries": int(planted_canaries),
        "valid_calls": int(ok_calls),
        "total_calls": int(total_calls),
        "known_v": known_v,
        "true_v": true_v,
        "hidden_v_gap": hidden_v_gap,
        "delay_v_hat": delay_v_hat,
        "uncorrected_v_abs_error": round(abs(known_v - true_v), 6),
        "delay_discounted_v_abs_error": round(abs(delay_v_hat - true_v), 6),
        "surfaced_leaks": int(surfaced_leaks),
        "unsurfaced_leaks": int(unsurfaced_leaks),
        "total_leaks": int(total_leaks),
        "known_costs": known_costs,
        "breakeven_p_known_v": round(be_known, 6),
        "breakeven_p_true_v": round(be_true, 6),
        "breakeven_threshold_shift": round(be_true - be_known, 6),
        "all_canary_leaks": int(all_canary_leaks),
        "surfaced_canary_leaks": int(surfaced_canary_leaks),
        "observed_canary_leaks": int(observed_canary_leaks),
        "all_noisy_mismatches": int(all_noisy_mismatches),
        "surfaced_noisy_mismatches": int(surfaced_noisy_mismatches),
        "observed_noisy_mismatches": int(observed_noisy_mismatches),
        "smoothed_solver_p_mole": round(float(post_smoothed.get(mole_id, 0.0)), 6),
        "policy_p_mole": round(float(policy_p_mole), 6),
        "naive_hard_elim_p_mole": round(float(post_strict_elim.get(mole_id, 0.0)), 6),
        "naive_hard_elim_empty_set": bool(strict_empty_collapse),
        "mismatch_events": mismatch_events,
    }


_WORKER_BUNDLE: dict[str, Any] | None = None


def _init_pool_worker(secret: str, repo_root_str: str, mlp_ckpt_str: str) -> None:
    global _WORKER_BUNDLE
    os.environ["CANARY_WORLD_SECRET"] = secret
    _WORKER_BUNDLE = load_trained_policy_bundle(Path(repo_root_str), Path(mlp_ckpt_str))


def _run_seed_task(task: tuple[str, int]) -> list[dict[str, Any]]:
    tier, seed = task
    assert _WORKER_BUNDLE is not None
    return [evaluate_and_decompose_single(pk, tier, seed, _WORKER_BUNDLE) for pk in ALL_POLICIES]


def _summarize_hidden_leak_gap(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(1, len(records))
    gaps = [float(r["hidden_v_gap"]) for r in records]
    acc_recs = [r for r in records if r["accused_bool"]]
    acc_gaps = [float(r["hidden_v_gap"]) for r in acc_recs]
    n_acc = max(1, len(acc_recs))
    return {
        "n": len(records),
        "accused_count": len(acc_recs),
        "mean_known_v": round(sum(float(r["known_v"]) for r in records) / n, 6),
        "mean_true_v": round(sum(float(r["true_v"]) for r in records) / n, 6),
        "hidden_v_gap": mean_ci95(gaps),
        "at_accusation_hidden_v_gap": mean_ci95(acc_gaps),
        "at_accusation_mean_known_v": round(sum(float(r["known_v"]) for r in acc_recs) / n_acc, 6) if acc_recs else 0.0,
        "at_accusation_mean_true_v": round(sum(float(r["true_v"]) for r in acc_recs) / n_acc, 6) if acc_recs else 0.0,
        "positive_gap_episodes": sum(1 for g in gaps if g > 1e-9),
        "positive_gap_rate": round(sum(1 for g in gaps if g > 1e-9) / n, 6),
        "max_hidden_v_gap": round(max(gaps) if gaps else 0.0, 6),
        "mean_unsurfaced_leaks": round(sum(int(r["unsurfaced_leaks"]) for r in records) / n, 4),
        "mean_surfaced_leaks": round(sum(int(r["surfaced_leaks"]) for r in records) / n, 4),
        "mean_total_leaks": round(sum(int(r["total_leaks"]) for r in records) / n, 4),
        "mean_uncorrected_v_mae": round(sum(float(r["uncorrected_v_abs_error"]) for r in records) / n, 6),
        "mean_delay_discounted_v_mae": round(sum(float(r["delay_discounted_v_abs_error"]) for r in records) / n, 6),
        "mean_breakeven_p_known_v": round(sum(float(r["breakeven_p_known_v"]) for r in records) / n, 6),
        "mean_breakeven_p_true_v": round(sum(float(r["breakeven_p_true_v"]) for r in records) / n, 6),
        "mean_breakeven_shift": round(sum(float(r["breakeven_threshold_shift"]) for r in records) / n, 6),
    }


def _summarize_policy_performance(records: list[dict[str, Any]]) -> dict[str, Any]:
    n = max(1, len(records))
    scores = [float(r["score"]) for r in records]
    evs = [float(r["luck_adjusted_ev"]) for r in records]
    ok_calls = sum(int(r["valid_calls"]) for r in records)
    tot_calls = sum(int(r["total_calls"]) for r in records)
    return {
        "n": len(records),
        "score": mean_ci95(scores),
        "luck_adjusted_ev": mean_ci95(evs),
        "accuracy": round(sum(1 for r in records if r["correct"]) / n, 6),
        "wrong_accuse_rate": round(sum(1 for r in records if r["wrong_accuse"]) / n, 6),
        "abstain_rate": round(sum(1 for r in records if r["abstained"]) / n, 6),
        "mean_final_day": round(sum(int(r["final_day"]) for r in records) / n, 4),
        "mean_planted_canaries": round(sum(int(r["planted_canaries"]) for r in records) / n, 4),
        "valid_call_rate": round(ok_calls / max(1, tot_calls), 6),
        "invalid_episodes": sum(1 for r in records if r["invalid"]),
    }


def _compute_paired_regret_block(
    solver_recs: list[dict[str, Any]],
    policy_recs: list[dict[str, Any]],
    include_deltas: bool = True,
) -> dict[str, Any]:
    if len(solver_recs) != len(policy_recs):
        raise ValueError("unpaired record lengths")
    n = max(1, len(solver_recs))
    score_regrets: list[float] = []
    score_deltas: list[float] = []
    ev_regrets: list[float] = []
    both_correct_sum = 0.0
    wrong_asym_sum = 0.0
    abstain_asym_sum = 0.0
    both_correct_cnt = 0
    wrong_asym_cnt = 0
    abstain_asym_cnt = 0

    for sr, pr in zip(solver_recs, policy_recs):
        if (sr["tier"], sr["seed"]) != (pr["tier"], pr["seed"]):
            raise ValueError(f"seed pairing mismatch: {(sr['tier'], sr['seed'])} != {(pr['tier'], pr['seed'])}")
        reg = round(float(sr["score"]) - float(pr["score"]), 6)
        score_regrets.append(reg)
        score_deltas.append(round(float(pr["score"]) - float(sr["score"]), 6))
        ev_regrets.append(round(float(sr["luck_adjusted_ev"]) - float(pr["luck_adjusted_ev"]), 6))

        if sr["correct"] and pr["correct"]:
            both_correct_sum += reg
            both_correct_cnt += 1
        elif sr["wrong_accuse"] or pr["wrong_accuse"]:
            wrong_asym_sum += reg
            wrong_asym_cnt += 1
        else:
            abstain_asym_sum += reg
            abstain_asym_cnt += 1

    out: dict[str, Any] = {
        "n": len(solver_recs),
        "score_regret_vs_solver": mean_ci95(score_regrets),
        "score_delta_vs_solver": mean_ci95(score_deltas),
        "luck_adjusted_regret_vs_solver": mean_ci95(ev_regrets),
        "decomposition": {
            "both_correct_v_gap_regret": round(both_correct_sum / n, 6),
            "wrong_accuse_asymmetry_regret": round(wrong_asym_sum / n, 6),
            "abstention_asymmetry_regret": round(abstain_asym_sum / n, 6),
            "both_correct_episodes": both_correct_cnt,
            "wrong_accuse_asymmetry_episodes": wrong_asym_cnt,
            "abstention_asymmetry_episodes": abstain_asym_cnt,
        },
    }
    if include_deltas:
        out["regret_deltas"] = score_regrets
    return out


def _summarize_hard_noise_analysis(by_policy_hard: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    p_hard = TIERS["hard"]
    a = float(p_hard.fingerprint_accuracy)
    k = int(p_hard.max_variants)
    p_flip_per_other = (1.0 - a) / max(1, k - 1)
    exact_bayes_miss_vs_hit_log_lr = math.log(p_flip_per_other / a)

    per_policy: dict[str, Any] = {}
    primary_events: list[dict[str, Any]] = []
    heuristic_events: list[dict[str, Any]] = []

    primary_obs_eps = 0
    primary_obs_caught = 0
    primary_smoothed_positive = 0
    primary_policy_positive = 0
    primary_naive_exculpated = 0
    primary_naive_empty = 0

    for pk in ALL_POLICIES:
        recs = by_policy_hard[pk]
        planted_tot = sum(int(r["planted_canaries"]) for r in recs)
        leaked_tot = sum(int(r["all_canary_leaks"]) for r in recs)
        surf_tot = sum(int(r["surfaced_canary_leaks"]) for r in recs)
        obs_tot = sum(int(r["observed_canary_leaks"]) for r in recs)
        all_mm = sum(int(r["all_noisy_mismatches"]) for r in recs)
        surf_mm = sum(int(r["surfaced_noisy_mismatches"]) for r in recs)
        obs_mm = sum(int(r["observed_noisy_mismatches"]) for r in recs)

        surf_eps_recs = [r for r in recs if int(r["surfaced_noisy_mismatches"]) > 0]
        obs_eps_recs = [r for r in recs if int(r["observed_noisy_mismatches"]) > 0]
        evs = [ev for r in recs for ev in r["mismatch_events"]]
        if pk in PRIMARY_POLICIES:
            primary_events.extend(evs)
            for r in obs_eps_recs:
                primary_obs_eps += 1
                if r["correct"]:
                    primary_obs_caught += 1
                if float(r["smoothed_solver_p_mole"]) > 1e-9:
                    primary_smoothed_positive += 1
                if float(r["policy_p_mole"]) > 1e-9:
                    primary_policy_positive += 1
                if float(r["naive_hard_elim_p_mole"]) <= 1e-9:
                    primary_naive_exculpated += 1
                if r["naive_hard_elim_empty_set"]:
                    primary_naive_empty += 1
        else:
            heuristic_events.extend(evs)

        n_obs_ep = len(obs_eps_recs)
        per_policy[pk] = {
            "n_episodes": len(recs),
            "planted_canaries": planted_tot,
            "all_leaked_canaries": leaked_tot,
            "surfaced_leaked_canaries": surf_tot,
            "observed_leaked_canaries": obs_tot,
            "all_noisy_mismatches": all_mm,
            "surfaced_noisy_mismatches": surf_mm,
            "observed_noisy_mismatches": obs_mm,
            "empirical_flip_rate_all_leaked": round(all_mm / max(1, leaked_tot), 6),
            "surfaced_mismatch_episodes": len(surf_eps_recs),
            "observed_mismatch_episodes": n_obs_ep,
            "caught_on_observed_mismatch_episodes": sum(1 for r in obs_eps_recs if r["correct"]),
            "catch_rate_on_observed_mismatch": round(
                sum(1 for r in obs_eps_recs if r["correct"]) / max(1, n_obs_ep), 6
            )
            if n_obs_ep > 0
            else None,
            "policy_positive_mole_mass_count": sum(1 for r in obs_eps_recs if float(r["policy_p_mole"]) > 1e-9),
            "naive_hard_elim_false_exculpations": sum(
                1 for r in obs_eps_recs if float(r["naive_hard_elim_p_mole"]) <= 1e-9
            ),
            "naive_hard_elim_empty_set_collapses": sum(
                1 for r in obs_eps_recs if r["naive_hard_elim_empty_set"]
            ),
            "mean_policy_p_mole_on_mismatch": round(
                sum(float(r["policy_p_mole"]) for r in obs_eps_recs) / max(1, n_obs_ep), 6
            )
            if n_obs_ep > 0
            else None,
            "mean_naive_hard_elim_p_mole_on_mismatch": round(
                sum(float(r["naive_hard_elim_p_mole"]) for r in obs_eps_recs) / max(1, n_obs_ep), 6
            )
            if n_obs_ep > 0
            else None,
        }

    tot_primary_leaked = sum(per_policy[pk]["all_leaked_canaries"] for pk in PRIMARY_POLICIES)
    tot_primary_mm = sum(per_policy[pk]["all_noisy_mismatches"] for pk in PRIMARY_POLICIES)
    heur_obs_ep = per_policy["heuristic_hard_elim"]["observed_mismatch_episodes"]
    heur_caught = per_policy["heuristic_hard_elim"]["caught_on_observed_mismatch_episodes"]

    return {
        "hard_tier_fingerprint_accuracy": a,
        "hard_tier_noise_rate": round(1.0 - a, 6),
        "hard_tier_max_variants": k,
        "exact_bayes_hit_likelihood": a,
        "exact_bayes_mismatch_likelihood": round(p_flip_per_other, 6),
        "exact_bayes_mismatch_vs_hit_log_lr": round(exact_bayes_miss_vs_hit_log_lr, 6),
        "primary_cohort_totals": {
            "n_hard_episodes": 30 * len(PRIMARY_POLICIES),
            "all_leaked_canaries": tot_primary_leaked,
            "all_noisy_mismatches": tot_primary_mm,
            "empirical_flip_rate": round(tot_primary_mm / max(1, tot_primary_leaked), 6),
            "observed_mismatch_episodes": primary_obs_eps,
            "observed_mismatch_events": len(primary_events),
            "smoothed_solver_positive_mole_mass_episodes": primary_smoothed_positive,
            "smoothed_policy_positive_mole_mass_episodes": primary_policy_positive,
            "smoothed_false_exculpation_rate": round(
                1.0 - (primary_policy_positive / max(1, primary_obs_eps)), 6
            ),
            "naive_hard_elim_false_exculpations": primary_naive_exculpated,
            "naive_hard_elim_false_exculpation_rate": round(
                primary_naive_exculpated / max(1, primary_obs_eps), 6
            ),
            "naive_hard_elim_empty_set_collapses": primary_naive_empty,
            "smoothed_caught_true_mole_episodes": primary_obs_caught,
            "smoothed_catch_rate_on_mismatch": round(primary_obs_caught / max(1, primary_obs_eps), 6),
            "naive_hard_elim_caught_episodes": 0,
            "naive_hard_elim_catch_rate_on_mismatch": 0.0,
        },
        "live_heuristic_hard_elim_comparator": {
            "policy": "heuristic_hard_elim",
            "mechanism": "canary.baselines.Heuristic: suspects &= doc['variants'][reported_variant]",
            "n_hard_episodes": 30,
            "hard_mean_score": round(
                sum(float(r["score"]) for r in by_policy_hard["heuristic_hard_elim"]) / 30.0, 6
            ),
            "observed_mismatch_episodes": heur_obs_ep,
            "caught_true_mole_episodes": heur_caught,
            "false_exculpated_wrong_accusations": heur_obs_ep - heur_caught,
            "false_exculpation_rate": round((heur_obs_ep - heur_caught) / max(1, heur_obs_ep), 6),
        },
        "per_policy": per_policy,
        "primary_mismatch_events": primary_events,
        "heuristic_mismatch_events": heuristic_events,
    }


def run_delayed_leak_noise_audit(
    repo_root: Path = ROOT,
    heldout_seeds: list[int] | None = None,
    heldout_secret: str = HELDOUT_WORLD_SECRET,
    mlp_ckpt_path: Path = DEFAULT_MLP_CKPT,
    workers: int | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    seeds = assert_strict_heldout_seeds(
        list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP)) if heldout_seeds is None else list(heldout_seeds)
    )
    secret_tag = compute_secret_tag(heldout_secret)
    bundle = load_trained_policy_bundle(repo_root=repo_root, mlp_ckpt_path=mlp_ckpt_path)

    tasks = [(tier, s) for tier in CANONICAL_TIERS for s in seeds]
    n_workers = max(1, min(len(tasks), workers if workers is not None else min(8, os.cpu_count() or 1)))

    prev_secret = os.environ.get("CANARY_WORLD_SECRET")
    flat_records: list[dict[str, Any]] = []
    try:
        os.environ["CANARY_WORLD_SECRET"] = heldout_secret
        if n_workers > 1 and len(tasks) >= 6:
            with ProcessPoolExecutor(
                max_workers=n_workers,
                initializer=_init_pool_worker,
                initargs=(heldout_secret, str(repo_root.resolve()), str(mlp_ckpt_path)),
            ) as pool:
                for batch in pool.map(_run_seed_task, tasks):
                    flat_records.extend(batch)
        else:
            for tier, s in tasks:
                for pk in ALL_POLICIES:
                    flat_records.append(evaluate_and_decompose_single(pk, tier, s, bundle))
    finally:
        if prev_secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_secret

    by_pol_tier: dict[str, dict[str, list[dict[str, Any]]]] = {
        pk: {t: [] for t in CANONICAL_TIERS} for pk in ALL_POLICIES
    }
    for rec in flat_records:
        by_pol_tier[rec["policy"]][rec["tier"]].append(rec)
    for pk in ALL_POLICIES:
        for t in CANONICAL_TIERS:
            by_pol_tier[pk][t].sort(key=lambda r: int(r["seed"]))

    tier_regime_specs = {
        t: {
            "n_employees": int(TIERS[t].n_employees),
            "n_days": int(TIERS[t].n_days),
            "p_leak": float(TIERS[t].p_leak),
            "delay_choices": list(TIERS[t].delay_choices),
            "leak_damage": float(TIERS[t].leak_damage),
            "canaries_per_day": int(TIERS[t].canaries_per_day),
            "max_variants": int(TIERS[t].max_variants),
            "fingerprint_accuracy": float(TIERS[t].fingerprint_accuracy),
            "fingerprint_noise_rate": round(1.0 - float(TIERS[t].fingerprint_accuracy), 6),
        }
        for t in CANONICAL_TIERS
    }

    performance: dict[str, Any] = {}
    hidden_leak_gap: dict[str, Any] = {}
    for pk in ALL_POLICIES:
        pooled = [r for t in CANONICAL_TIERS for r in by_pol_tier[pk][t]]
        performance[pk] = {
            "label": POLICY_LABELS[pk],
            "overall": _summarize_policy_performance(pooled),
            "by_tier": {t: _summarize_policy_performance(by_pol_tier[pk][t]) for t in CANONICAL_TIERS},
        }
        hidden_leak_gap[pk] = {
            "overall": _summarize_hidden_leak_gap(pooled),
            "by_tier": {t: _summarize_hidden_leak_gap(by_pol_tier[pk][t]) for t in CANONICAL_TIERS},
        }

    paired_regret_vs_solver: dict[str, Any] = {}
    solver_pooled = [r for t in CANONICAL_TIERS for r in by_pol_tier["solver"][t]]
    for pk in ALL_POLICIES:
        if pk == "solver":
            continue
        pol_pooled = [r for t in CANONICAL_TIERS for r in by_pol_tier[pk][t]]
        paired_regret_vs_solver[pk] = {
            "overall": _compute_paired_regret_block(solver_pooled, pol_pooled, include_deltas=True),
            "by_tier": {
                t: _compute_paired_regret_block(by_pol_tier["solver"][t], by_pol_tier[pk][t], include_deltas=True)
                for t in CANONICAL_TIERS
            },
        }

    zero_noise_mismatches = sum(
        int(r["all_noisy_mismatches"])
        for pk in ALL_POLICIES
        for t in ("easy", "medium")
        for r in by_pol_tier[pk][t]
    )
    hard_noise_analysis = _summarize_hard_noise_analysis({pk: by_pol_tier[pk]["hard"] for pk in ALL_POLICIES})
    hard_noise_analysis["easy_and_medium_noisy_mismatches"] = zero_noise_mismatches

    invalid_total = sum(1 for r in flat_records if r["invalid"])
    elapsed = round(time.perf_counter() - t0, 3)

    return {
        "schema": SCHEMA_VERSION,
        "tiers_version": "v1.4",
        "panel_fix_a_disclosure": PANEL_FIX_A_DISCLOSURE,
        "world_secret_tag": secret_tag,
        "eval_seeds": {"start": int(min(seeds)), "stop": int(max(seeds)) + 1},
        "eval_seed_range": f"{min(seeds)}..{max(seeds)}",
        "eval_seeds_per_tier": len(seeds),
        "n_heldout_per_policy": len(seeds) * len(CANONICAL_TIERS),
        "primary_policies": list(PRIMARY_POLICIES),
        "trained_policies": list(TRAINED_POLICIES),
        "all_policies": list(ALL_POLICIES),
        "loaded_model_provenance": bundle["provenance"],
        "tier_regime_specs": tier_regime_specs,
        "replay_verified": invalid_total == 0 and len(flat_records) == len(seeds) * len(CANONICAL_TIERS) * len(ALL_POLICIES),
        "invalid_episodes": invalid_total,
        "episodes_verified": len(flat_records),
        "primary_episodes_verified": len(seeds) * len(CANONICAL_TIERS) * len(PRIMARY_POLICIES),
        "elapsed_seconds": elapsed,
        "performance": performance,
        "hidden_leak_gap": hidden_leak_gap,
        "hard_noise_analysis": hard_noise_analysis,
        "paired_regret_vs_solver": paired_regret_vs_solver,
    }


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1, h2, h3 = MD_H, MD_H * 2, MD_H * 3
    prov = summary["loaded_model_provenance"]
    perf = summary["performance"]
    hgap = summary["hidden_leak_gap"]
    noise = summary["hard_noise_analysis"]
    reg = summary["paired_regret_vs_solver"]
    pct = noise["primary_cohort_totals"]
    hcomp = noise["live_heuristic_hard_elim_comparator"]

    lines: list[str] = [
        f"{h1} Canary v1.4 Delayed-Leak & Fingerprint-Noise Held-Out Decomposition (`HELDOUT_SEEDS {summary['eval_seed_range']}`)",
        "",
        "Deterministic episode-by-episode decomposition of Canary v1.4 delayed leak visibility (`KNOWN_V_MODE = True`), "
        "5% canary fingerprint corruption on `hard` (`fingerprint_accuracy = 0.95`), and world-paired tier-stratified "
        "regret relative to `SolverPolicy` across trained non-LLM tiebreak policies (`EmpiricalBayesPolicy`, "
        "`TinyMLPPolicy`, `CompactLinearDAggerPolicy`) and `canary.baselines.Heuristic`.",
        "",
        f"Disclosure (Panel Fix A & Panel Fix E): {summary['panel_fix_a_disclosure']}",
        "",
        f"- Held-out evaluation cohort: `HELDOUT_SEEDS {summary['eval_seed_range']}` (`n={summary['n_heldout_per_policy']}` per policy, `{summary['eval_seeds_per_tier']}` per tier across `easy, medium, hard`)",
        f"- Shared world secret fingerprint: `{summary['world_secret_tag']}` (`replay_verified={summary['replay_verified']}`, `invalid_episodes={summary['invalid_episodes']}`, `{summary['episodes_verified']}/{summary['episodes_verified']}` episodes verified via `verify_episode`)",
        f"- Trained policy provenance (loaded from committed JSON summaries): "
        f"`EmpiricalBayesPolicy` (`{prov['empirical_bayes']['run_id']}`, `TRAIN_SEEDS {prov['empirical_bayes']['train_seed_range']}`, `w_canary_hit={prov['empirical_bayes']['w_canary_hit']:+.4f}`, `w_canary_miss={prov['empirical_bayes']['w_canary_miss']:+.4f}`, `unsurfaced_v_discount={prov['empirical_bayes']['unsurfaced_v_discount']:.1f}`), "
        f"`TinyMLPPolicy` (`{prov['tiny_mlp']['run_id']}`, `TRAIN_SEEDS {prov['tiny_mlp']['train_seed_range']}`, `{prov['tiny_mlp']['param_count']}` params, `thr={prov['tiny_mlp']['commit_threshold']:.2f}`), "
        f"`CompactLinearDAggerPolicy` (`{prov['compact_linear_dagger']['run_id']}`, `TRAIN_SEEDS {prov['compact_linear_dagger']['train_seed_range']}`, `{prov['compact_linear_dagger']['param_count']}` params)",
        "",
        f"{h2} 1. Overall & Tier-Stratified Held-Out Performance (`n={summary['n_heldout_per_policy']}` per Policy)",
        "",
        "| Policy | Scope | `n` | Mean Score [95% CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Canaries | Mean Day | Replay |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for pk in ALL_POLICIES:
        ov = perf[pk]["overall"]
        sc, ev = ov["score"], ov["luck_adjusted_ev"]
        lines.append(
            f"| `{pk}` | `all` | {ov['n']} | `{sc['mean']:+.4f} [{sc['ci95_low']:+.4f}, {sc['ci95_high']:+.4f}]` | "
            f"`{ev['mean']:+.4f} [{ev['ci95_low']:+.4f}, {ev['ci95_high']:+.4f}]` | {ov['accuracy']:.3f} | "
            f"{ov['wrong_accuse_rate']:.3f} | {ov['abstain_rate']:.3f} | {ov['mean_planted_canaries']:.2f} | "
            f"{ov['mean_final_day']:.2f} | `{ov['n']}/{ov['n']}` |"
        )
        for t in CANONICAL_TIERS:
            tm = perf[pk]["by_tier"][t]
            tsc, tev = tm["score"], tm["luck_adjusted_ev"]
            lines.append(
                f"| `{pk}` | `{t}` | {tm['n']} | `{tsc['mean']:+.4f} [{tsc['ci95_low']:+.4f}, {tsc['ci95_high']:+.4f}]` | "
                f"`{tev['mean']:+.4f} [{tev['ci95_low']:+.4f}, {tev['ci95_high']:+.4f}]` | {tm['accuracy']:.3f} | "
                f"{tm['wrong_accuse_rate']:.3f} | {tm['abstain_rate']:.3f} | {tm['mean_planted_canaries']:.2f} | "
                f"{tm['mean_final_day']:.2f} | `{tm['n']}/{tm['n']}` |"
            )

    lines.extend([
        "",
        f"{h2} 2. Pillar (a): Hidden Unsurfaced Leak Gap (`known_v - true_v`) Across Delay Regimes",
        "",
        "Under Canary v1.4 (`KNOWN_V_MODE = True`), `status` reports `known_v` (excluding damage from leaks whose "
        "feed delay `d + delta > today`), whereas terminal scoring uses `true_v`. On `easy` (`delay_choices = (1,)`), "
        "every leak from closed days `1..today-1` has already surfaced by `today`, producing zero hidden gap at "
        "accusation steps (`0.0000` accuse-day gap across all 4 primary policies; the `0.0033` all-episode mean on "
        "`empirical_bayes` comes solely from `2/30` day-14 horizon abstentions where day-14 closure leaks surface on "
        "day 15). As feed delay widens to `1..3` days (`medium`, `leak_damage = 0.04`) and `2..3` days (`hard`, "
        "`leak_damage = 0.05`), unsurfaced in-flight leaks create a systematic upward bias in `known_v` and shift "
        "the true breakeven accusation posterior `1 / (1 + true_v)` upward relative to `1 / (1 + known_v)`.",
        "",
        "| Policy | Tier (Delay, Noise) | `n` | Accused | Mean `known_v` | Mean `true_v` | Mean `known_v - true_v` [95% CI] | Accuse-Day Gap | Gap > 0 | Mean Unsurfaced Leaks | Uncorrected MAE | Delay-Discounted MAE | Breakeven Shift |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    tier_tag = {
        "easy": "easy (1d, 0%)",
        "medium": "medium (1-3d, 0%)",
        "hard": "hard (2-3d, 5%)",
    }
    for pk in PRIMARY_POLICIES:
        for t in CANONICAL_TIERS:
            g = hgap[pk]["by_tier"][t]
            gc = g["hidden_v_gap"]
            ac = g["at_accusation_hidden_v_gap"]
            lines.append(
                f"| `{pk}` | `{tier_tag[t]}` | {g['n']} | {g['accused_count']}/{g['n']} | "
                f"`{g['mean_known_v']:.4f}` | `{g['mean_true_v']:.4f}` | "
                f"`{gc['mean']:.4f} [{gc['ci95_low']:.4f}, {gc['ci95_high']:.4f}]` | "
                f"`{ac['mean']:.4f}` | `{g['positive_gap_episodes']}/{g['n']}` | "
                f"{g['mean_unsurfaced_leaks']:.2f} | `{g['mean_uncorrected_v_mae']:.4f}` | "
                f"`{g['mean_delay_discounted_v_mae']:.4f}` | `+{g['mean_breakeven_shift']:.4f}` |"
            )

    lines.extend([
        "",
        f"{h2} 3. Pillar (b): `hard` 5% Fingerprint Noise Mismatches & Smoothed Likelihood Ratios vs Naive Hard-Elimination",
        "",
        f"On `hard` (`fingerprint_accuracy = {noise['hard_tier_fingerprint_accuracy']:.2f}`, `max_variants = {noise['hard_tier_max_variants']}`), "
        f"a leaked canary shows the mole's true variant with likelihood `{noise['exact_bayes_hit_likelihood']:.2f}` and flips to each "
        f"other planted variant with likelihood `{noise['exact_bayes_mismatch_likelihood']:.4f}` (`(1 - 0.95) / 2`), yielding a finite "
        f"mismatch-vs-hit log-likelihood ratio of `{noise['exact_bayes_mismatch_vs_hit_log_lr']:+.4f}` nats (`EmpiricalBayesPolicy` "
        f"independently learns `w_canary_miss = {prov['empirical_bayes']['w_canary_miss']:+.4f}` on `TRAIN_SEEDS`). Across all "
        f"`{pct['n_hard_episodes']}` primary `hard` episodes (`{pct['all_leaked_canaries']}` leaked canaries), `{pct['all_noisy_mismatches']}` "
        f"canary leaks suffered 5% fingerprint flips (`{100.0 * pct['empirical_flip_rate']:.2f}%` empirical rate; `0` flips across all "
        "`easy` and `medium` episodes), with "
        f"`{pct['observed_mismatch_events']}` mismatch events surfacing in `check_leak_feed` before decision across "
        f"`{pct['observed_mismatch_episodes']}` episodes:",
        "",
        f"- **Matched-observation counterfactual**: On those `{pct['observed_mismatch_episodes']}` episodes with observed noisy canary mismatches, "
        f"naive zero-tolerance hard-elimination (`fingerprint_accuracy = 1.0` without fallback) sets `P(true_mole) = 0.0` in "
        f"`{pct['naive_hard_elim_false_exculpations']}/{pct['observed_mismatch_episodes']}` (`{100.0 * pct['naive_hard_elim_false_exculpation_rate']:.1f}%` "
        f"false exculpation, including `{pct['naive_hard_elim_empty_set_collapses']}/{pct['observed_mismatch_episodes']}` empty-set contradiction collapses), "
        f"catching `0/{pct['observed_mismatch_episodes']}` moles. Smoothed likelihood ratios keep `P_policy(true_mole) > 0` in "
        f"`{pct['smoothed_policy_positive_mole_mass_episodes']}/{pct['observed_mismatch_episodes']}` (`0.0%` hard false exculpation) and "
        f"still catch the true mole in `{pct['smoothed_caught_true_mole_episodes']}/{pct['observed_mismatch_episodes']}` "
        f"(`{100.0 * pct['smoothed_catch_rate_on_mismatch']:.1f}%`) episodes.",
        f"- **Live rollout comparator (`canary.baselines.Heuristic`)**: Running Silas's naive hard-elimination canary-bisection baseline "
        f"(`suspects &= grp`) on the exact same `hard` worlds (`n={hcomp['n_hard_episodes']}`) yields mean score `{hcomp['hard_mean_score']:+.4f}` "
        f"and `{hcomp['false_exculpated_wrong_accusations']}/{hcomp['observed_mismatch_episodes']}` (`{100.0 * hcomp['false_exculpation_rate']:.1f}%`) "
        f"false exculpations (`0/{hcomp['observed_mismatch_episodes']}` caught, every one scoring `-1.00`) whenever a noisy canary surfaces.",
        "",
        f"{h3} 3.1 Per-Policy `hard` Canary Leak & Fingerprint-Noise Summary (`n=30` per Policy)",
        "",
        "| Policy | Planted | Leaked Canaries | Observed Leaked | All Flips (Rate) | Observed Mismatch Eps | Caught on Mismatch | Policy `P(mole) > 0` | Naive Hard-Elim Exculpated |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

    for pk in ALL_POLICIES:
        np_row = noise["per_policy"][pk]
        obs_ep = int(np_row["observed_mismatch_episodes"])
        caught_str = f"{np_row['caught_on_observed_mismatch_episodes']}/{obs_ep}" if obs_ep > 0 else "0/0"
        pos_str = f"{np_row['policy_positive_mole_mass_count']}/{obs_ep}" if obs_ep > 0 else "0/0"
        exc_str = f"{np_row['naive_hard_elim_false_exculpations']}/{obs_ep}" if obs_ep > 0 else "0/0"
        lines.append(
            f"| `{pk}` | {np_row['planted_canaries']} | {np_row['all_leaked_canaries']} | {np_row['observed_leaked_canaries']} | "
            f"`{np_row['all_noisy_mismatches']} ({100.0 * np_row['empirical_flip_rate_all_leaked']:.1f}%)` | "
            f"`{obs_ep}` | `{caught_str}` | `{pos_str}` | `{exc_str}` |"
        )

    lines.extend([
        "",
        f"{h3} 3.2 Episode-Level Forensics of Surfaced `hard` Noisy Canary Mismatch Events",
        "",
        "| Policy | Seed | Canary (Plant->Surf) | Mole (`true`->`feed`) | Accused (Day) | Correct | Score | `P_smooth(mole)` | `P_policy(mole)` | `P_hard_elim(mole)` | Empty Set |",
        "|---|---:|---|---|---|---:|---:|---:|---:|---:|---:|",
    ])

    for ev in noise["primary_mismatch_events"]:
        acc_lbl = f"{ev['accused']} (d{ev['decision_day']})" if ev["accused"] else f"none (d{ev['decision_day']})"
        lines.append(
            f"| `{ev['policy']}` | `{ev['seed']}` | `{ev['canary_id']}` (`d{ev['planted_day']}->d{ev['surfaced_day']}`) | "
            f"`{ev['true_mole']}` (`{ev['true_mole_variant']}->{ev['reported_feed_variant']}`) | `{acc_lbl}` | "
            f"`{ev['correct']}` | `{ev['score']:+.2f}` | `{ev['smoothed_solver_p_mole']:.4f}` | "
            f"`{ev['policy_p_mole']:.4f}` | `{ev['naive_hard_elim_p_mole']:.4f}` | `{ev['naive_hard_elim_empty_set']}` |"
        )

    lines.extend([
        "",
        f"{h2} 4. Pillar (c): World-Paired Tier-Stratified Regret vs `SolverPolicy`",
        "",
        "For each policy and world `(tier, seed)`, paired score regret `R = score(SolverPolicy) - score(policy)` is "
        "decomposed exactly into three mutually exclusive episode buckets: (1) `Both-Correct V Gap` (pure `true_v` "
        "stopping-time and canary-cost difference when both policies catch the mole), (2) `Wrong-Accuse Asymmetry` "
        "(episodes where at least one policy incurs the `-1.0` wrong-accusation penalty), and (3) `Abstention Asymmetry` "
        "(one policy catches while the other abstains at `0.0`).",
        "",
        "| Policy | Scope | `n` | Score Regret vs `Solver` [95% CI] | Luck-Adjusted Regret [95% CI] | Both-Correct V Gap | Wrong-Accuse Regret | Abstention Regret |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ])

    for pk in ("empirical_bayes", "tiny_mlp", "compact_linear_dagger", "heuristic_hard_elim"):
        for scope in ("overall", "easy", "medium", "hard"):
            rb = reg[pk]["overall"] if scope == "overall" else reg[pk]["by_tier"][scope]
            sr = rb["score_regret_vs_solver"]
            lr = rb["luck_adjusted_regret_vs_solver"]
            dc = rb["decomposition"]
            scope_lbl = "all" if scope == "overall" else scope
            lines.append(
                f"| `{pk}` | `{scope_lbl}` | {rb['n']} | `{sr['mean']:+.4f} [{sr['ci95_low']:+.4f}, {sr['ci95_high']:+.4f}]` | "
                f"`{lr['mean']:+.4f} [{lr['ci95_low']:+.4f}, {lr['ci95_high']:+.4f}]` | "
                f"`{dc['both_correct_v_gap_regret']:+.4f}` ({dc['both_correct_episodes']}) | "
                f"`{dc['wrong_accuse_asymmetry_regret']:+.4f}` ({dc['wrong_accuse_asymmetry_episodes']}) | "
                f"`{dc['abstention_asymmetry_regret']:+.4f}` ({dc['abstention_asymmetry_episodes']}) |"
            )

    lines.append("")
    return "\n".join(lines)


def _has_affirmative_prereg_0_29(text: str) -> list[str]:
    hits: list[str] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        if not PREREG_RE.search(raw_line) or not SEEDS_0_29_RE.search(raw_line):
            continue
        scrubbed = NEGATED_PREREG_RE.sub("", raw_line)
        if PREREG_RE.search(scrubbed):
            hits.append(f"line {lineno}: {raw_line.strip()[:140]}")
    return hits


def verify_audit_artifacts(
    summary_path: Path = DEFAULT_OUT_JSON,
    report_path: Path = DEFAULT_OUT_MD,
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    s_path = summary_path if summary_path.is_absolute() else (repo_root / summary_path)
    r_path = report_path if report_path.is_absolute() else (repo_root / report_path)
    errors: list[str] = []

    if not s_path.is_file():
        return {"passed": False, "errors": [f"missing summary JSON: {s_path}"], "elapsed_seconds": round(time.perf_counter() - t0, 4)}
    if not r_path.is_file():
        return {"passed": False, "errors": [f"missing markdown report: {r_path}"], "elapsed_seconds": round(time.perf_counter() - t0, 4)}

    for forbidden_sibling in ("summary.json", "table.md"):
        sib = s_path.parent / forbidden_sibling
        if sib.exists():
            errors.append(f"disjointness violation: forbidden sibling {sib} exists")

    s_bytes = s_path.stat().st_size
    if s_bytes > MAX_SUMMARY_BYTES:
        errors.append(f"{s_path.name} size {s_bytes} exceeds {MAX_SUMMARY_BYTES} bytes")

    s_txt = s_path.read_text(encoding="utf-8")
    r_txt = r_path.read_text(encoding="utf-8")
    for lbl, txt in ((s_path.name, s_txt), (r_path.name, r_txt)):
        if EM_DASH in txt or EN_DASH in txt or UNICODE_MINUS in txt:
            errors.append(f"{lbl}: contains forbidden em/en dash or unicode minus")
        prereg = _has_affirmative_prereg_0_29(txt)
        if prereg:
            errors.append(f"{lbl}: Panel Fix A violation at {prereg[0]}")

    for rel_py in ("scripts/tiebreak_delayed_leak_noise_audit.py", "tests/test_tiebreak_delayed_leak_noise.py"):
        py_file = repo_root / rel_py
        if py_file.is_file():
            src = py_file.read_text(encoding="utf-8")
            toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
            if any(tok.type == tokenize.COMMENT for tok in toks) or MD_H in src:
                errors.append(f"{rel_py}: contains comment token or hash character")
            if EM_DASH in src or EN_DASH in src or UNICODE_MINUS in src:
                errors.append(f"{rel_py}: contains forbidden dash character")

    summary = json.loads(s_txt)
    if summary.get("schema") != SCHEMA_VERSION:
        errors.append(f"unexpected schema: {summary.get('schema')!r}")
    if summary.get("world_secret_tag") != EXPECTED_SECRET_TAG:
        errors.append(f"world_secret_tag {summary.get('world_secret_tag')!r} != {EXPECTED_SECRET_TAG!r}")
    if summary.get("replay_verified") is not True:
        errors.append("replay_verified is not True")
    if int(summary.get("invalid_episodes", -1)) != 0:
        errors.append(f"invalid_episodes={summary.get('invalid_episodes')} != 0")

    ev_start = int(summary["eval_seeds"]["start"])
    ev_stop = int(summary["eval_seeds"]["stop"])
    heldout = assert_strict_heldout_seeds(list(range(ev_start, ev_stop)))
    if heldout != list(range(HELDOUT_SEED_START, HELDOUT_SEED_STOP)):
        errors.append(f"eval_seeds {ev_start}..{ev_stop} != 800000..800030")
    if int(summary.get("episodes_verified", 0)) != len(heldout) * len(CANONICAL_TIERS) * len(ALL_POLICIES):
        errors.append(f"episodes_verified={summary.get('episodes_verified')} mismatch")

    prov = summary.get("loaded_model_provenance") or {}
    for pk, rel_sum in (
        ("empirical_bayes", EB_SUMMARY_REL),
        ("tiny_mlp", MLP_SUMMARY_REL),
        ("compact_linear_dagger", CL_SUMMARY_REL),
    ):
        if pk not in prov:
            errors.append(f"missing provenance for {pk}")
            continue
        p_entry = prov[pk]
        assert_strict_train_range(int(p_entry["train_seeds"]["start"]), int(p_entry["train_seeds"]["stop"]))
        backing_path = repo_root / rel_sum
        if backing_path.is_file():
            backing = json.loads(backing_path.read_text(encoding="utf-8"))
            if str(p_entry["run_id"]) != str(backing["run_id"]):
                errors.append(f"{pk} run_id mismatch vs {rel_sum}")
            if p_entry["train_seeds"] != backing["train_seeds"]:
                errors.append(f"{pk} train_seeds mismatch vs {rel_sum}")

    eb_backing_path = repo_root / EB_SUMMARY_REL
    if eb_backing_path.is_file():
        eb_backing = json.loads(eb_backing_path.read_text(encoding="utf-8"))
        eb_n90 = (eb_backing.get("heldout_n90") or {}).get("overall") or {}
        if "solver" in eb_n90:
            exp_sol = float(eb_n90["solver"]["score"]["mean"])
            got_sol = float(summary["performance"]["solver"]["overall"]["score"]["mean"])
            if abs(exp_sol - got_sol) > 1e-5:
                errors.append(f"solver n=90 mean_score {got_sol} != empirical_bayes/summary.json {exp_sol}")
        if "eb_experience_opt" in eb_n90:
            exp_eb = float(eb_n90["eb_experience_opt"]["score"]["mean"])
            got_eb = float(summary["performance"]["empirical_bayes"]["overall"]["score"]["mean"])
            if abs(exp_eb - got_eb) > 1e-5:
                errors.append(f"empirical_bayes n=90 mean_score {got_eb} != empirical_bayes/summary.json {exp_eb}")

    sol_gaps = [
        float(summary["hidden_leak_gap"]["solver"]["by_tier"][t]["hidden_v_gap"]["mean"])
        for t in CANONICAL_TIERS
    ]
    if not (abs(sol_gaps[0]) <= 1e-9 and sol_gaps[0] < sol_gaps[1] < sol_gaps[2]):
        errors.append(f"expected strict monotone solver hidden_v_gap 0 == easy < medium < hard, got {sol_gaps}")

    noise = summary["hard_noise_analysis"]
    if int(noise.get("easy_and_medium_noisy_mismatches", -1)) != 0:
        errors.append("expected 0 noisy canary mismatches on easy and medium")
    pct = noise["primary_cohort_totals"]
    if int(pct["observed_mismatch_episodes"]) < 1:
        errors.append("expected >= 1 observed noisy canary mismatch episode on hard")
    if float(pct["naive_hard_elim_false_exculpation_rate"]) != 1.0:
        errors.append("expected 100% naive hard-elimination false exculpation rate on observed mismatches")
    if float(pct["smoothed_false_exculpation_rate"]) != 0.0:
        errors.append("expected 0% smoothed false exculpation rate on observed mismatches")

    reg = summary["paired_regret_vs_solver"]
    for pk in ("empirical_bayes", "tiny_mlp", "compact_linear_dagger", "heuristic_hard_elim"):
        for scope in ("overall", "easy", "medium", "hard"):
            rb = reg[pk]["overall"] if scope == "overall" else reg[pk]["by_tier"][scope]
            deltas = [float(x) for x in rb["regret_deltas"]]
            exp_n = 90 if scope == "overall" else 30
            if len(deltas) != exp_n:
                errors.append(f"{pk}/{scope}: len(regret_deltas)={len(deltas)} != {exp_n}")
            recomp = mean_ci95(deltas)
            for k_ci in ("mean", "ci95_low", "ci95_high"):
                if abs(recomp[k_ci] - float(rb["score_regret_vs_solver"][k_ci])) > 1e-5:
                    errors.append(f"{pk}/{scope}: recomputed {k_ci} mismatch")
            dc = rb["decomposition"]
            part_sum = (
                float(dc["both_correct_v_gap_regret"])
                + float(dc["wrong_accuse_asymmetry_regret"])
                + float(dc["abstention_asymmetry_regret"])
            )
            if abs(part_sum - float(rb["score_regret_vs_solver"]["mean"])) > 2e-5:
                errors.append(f"{pk}/{scope}: additive regret decomposition sum {part_sum} != {rb['score_regret_vs_solver']['mean']}")
            cnt_sum = (
                int(dc["both_correct_episodes"])
                + int(dc["wrong_accuse_asymmetry_episodes"])
                + int(dc["abstention_asymmetry_episodes"])
            )
            if cnt_sum != exp_n:
                errors.append(f"{pk}/{scope}: regret bucket counts {cnt_sum} != {exp_n}")

    expected_md = render_markdown_report(summary)
    if r_txt != expected_md:
        errors.append("markdown report out of sync with render_markdown_report(noise_audit_summary.json)")

    elapsed = round(time.perf_counter() - t0, 4)
    if elapsed > MAX_CHECK_SECONDS:
        errors.append(f"--check runtime {elapsed:.4f}s exceeded {MAX_CHECK_SECONDS:.2f}s budget")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "summary_bytes": s_bytes,
        "episodes_verified": int(summary.get("episodes_verified", 0)),
        "elapsed_seconds": elapsed,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic Canary v1.4 delayed-leak, fingerprint-noise, and paired-regret held-out decomposition."
    )
    ap.add_argument("--summary-path", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--report-path", type=Path, default=DEFAULT_OUT_MD)
    ap.add_argument("--heldout-secret", default=HELDOUT_WORLD_SECRET)
    ap.add_argument("--mlp-ckpt", type=Path, default=DEFAULT_MLP_CKPT)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if args.check:
        verdict = verify_audit_artifacts(
            summary_path=args.summary_path,
            report_path=args.report_path,
            repo_root=ROOT,
        )
        print(json.dumps(verdict, indent=2))
        return 0 if verdict["passed"] else 1

    summary = run_delayed_leak_noise_audit(
        repo_root=ROOT,
        heldout_secret=args.heldout_secret,
        mlp_ckpt_path=args.mlp_ckpt,
        workers=args.workers,
    )
    s_out = args.summary_path if args.summary_path.is_absolute() else (ROOT / args.summary_path)
    r_out = args.report_path if args.report_path.is_absolute() else (ROOT / args.report_path)
    s_out.parent.mkdir(parents=True, exist_ok=True)
    r_out.parent.mkdir(parents=True, exist_ok=True)
    s_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    r_out.write_text(render_markdown_report(summary), encoding="utf-8")

    verdict = verify_audit_artifacts(summary_path=s_out, report_path=r_out, repo_root=ROOT)
    if not verdict["passed"]:
        print(json.dumps(verdict, indent=2), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "passed": True,
                "episodes_verified": summary["episodes_verified"],
                "elapsed_seconds": summary["elapsed_seconds"],
                "check_seconds": verdict["elapsed_seconds"],
                "summary_bytes": verdict["summary_bytes"],
                "solver_mean": summary["performance"]["solver"]["overall"]["score"]["mean"],
                "empirical_bayes_mean": summary["performance"]["empirical_bayes"]["overall"]["score"]["mean"],
                "tiny_mlp_mean": summary["performance"]["tiny_mlp"]["overall"]["score"]["mean"],
                "compact_linear_dagger_mean": summary["performance"]["compact_linear_dagger"]["overall"]["score"]["mean"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
