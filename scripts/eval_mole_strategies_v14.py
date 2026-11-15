"""Offline v1.4 Hard evaluation and counterfactual report generator for transcript-grounded Mole DSL strategies."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import math
from pathlib import Path
import random
import re
import sys
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.gap import mean_ci
from canary.baselines import (
    AccuseMostLogs,
    DoNothing,
    GrokTactics,
    Heuristic,
    LogsOnly,
    StopEarlyQuit,
)
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import validate_strategy
from canary.mole.counterfactual import evaluate_counterfactual
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import (
    DEFAULT_MAX_LOGS_ACC,
    DEFAULT_MIN_SOLVER_ACC,
    DEFAULT_MIN_SOLVER_RATIO,
    STRATEGY_SPECS,
    get_strategy,
    get_strategy_spec,
    list_strategy_names,
)
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION, tier_params
from canary.solver.policy import SolverPolicy

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3
EM_DASH = "\u2014"
EN_DASH = "\u2013"

DEFAULT_JSON_OUT = ROOT / "results" / "mole_strategies" / "v14_fresh_6000_6199.json"
DEFAULT_MD_OUT = ROOT / "docs" / "reports" / "mole_strategies_v14.md"
DEFAULT_EVAL_SEEDS_SPEC = "6000-6199"
DEFAULT_CF_SEEDS_SPEC = "0-29"
DEFAULT_BOOT_RESAMPLES = 10000
DEFAULT_BOOT_SEED = 20261114
DEFAULT_TOL = 1e-9

FORBIDDEN_LOW_MAX = 59
FORBIDDEN_RESERVED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_MIN = 800_000

INVESTIGATOR_ORDER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "heuristic",
    "hinted_heuristic",
)

INVESTIGATOR_LABELS: dict[str, str] = {
    "gemini_carbon_proxy": "GeminiCarbonProxy",
    "codex_horizon_proxy": "CodexHorizonProxy",
    "grok_tactics": "GrokTactics(hard)",
    "heuristic": "Heuristic(hard)",
    "hinted_heuristic": "HintedHeuristic(hard)",
}

BASELINE_ORDER: tuple[str, ...] = (
    "logs_only",
    "accuse_most_logs",
    "do_nothing",
    "stop_early_quit",
)

FORBIDDEN_OUTPUT_KEYS: frozenset[str] = frozenset({
    "mole",
    "true_mole",
    "decoy",
    "transcript",
    "transcripts",
    "steps",
    "world_secret",
    "ledger_token",
    "ledger_events",
})

SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)

LEDGER_START = "<!-- MOLE_STRATEGIES_V14_LEDGER_START -->"
LEDGER_END = "<!-- MOLE_STRATEGIES_V14_LEDGER_END -->"


def _parse_seed_spec(spec: str) -> list[int]:
    s = str(spec).strip()
    if not s:
        raise ValueError("eval seeds must not be empty")
    out: list[int] = []
    for raw in s.split(","):
        part = raw.strip()
        if not part:
            raise ValueError(f"empty seed token in {spec!r}")
        if "-" in part and not part.startswith("-"):
            a_str, b_str = part.split("-", 1)
            a, b = int(a_str), int(b_str)
            if b < a:
                raise ValueError(f"reversed seed range {part!r}")
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))
    return out


def validate_eval_seeds(seeds: str | Iterable[int]) -> list[int]:
    if isinstance(seeds, str):
        parsed = _parse_seed_spec(seeds)
    else:
        parsed = [int(s) for s in seeds]
    if not parsed:
        raise ValueError("eval seeds must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ValueError("eval seeds must not contain duplicates")
    for s in parsed:
        if s < 0 or s <= FORBIDDEN_LOW_MAX:
            raise ValueError(f"seed {s} violates seed hygiene: 0..{FORBIDDEN_LOW_MAX} (and <0) forbidden")
        if s in FORBIDDEN_RESERVED_RANGE:
            raise ValueError(f"seed {s} violates seed hygiene: 30000..30199 reserved")
        if s >= FORBIDDEN_HIGH_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"seed {s} violates seed hygiene: >=800000 / heldout / judge forbidden")
    return parsed


def _clean_ci_halfwidth(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    _, hw = mean_ci(xs)
    return 0.0 if (not math.isfinite(hw)) else float(hw)


def bootstrap_mean_ci(
    xs: Sequence[float],
    n_resamples: int = DEFAULT_BOOT_RESAMPLES,
    seed: int = DEFAULT_BOOT_SEED,
) -> list[float]:
    n = len(xs)
    if n == 0:
        raise ValueError("cannot bootstrap empty sequence")
    if n == 1 or n_resamples <= 0:
        val = float(xs[0])
        return [val, val]
    rng = random.Random(seed)
    means = [
        sum(xs[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_resamples)
    ]
    means.sort()
    lo = float(means[int(0.025 * n_resamples)])
    hi = float(means[max(0, int(0.975 * n_resamples) - 1)])
    return [lo, hi]


def paired_bootstrap_min_regret(
    strat_regret_by_inv: dict[str, list[float]],
    base_regret_by_inv: dict[str, list[float]],
    n_resamples: int = DEFAULT_BOOT_RESAMPLES,
    seed: int = DEFAULT_BOOT_SEED,
) -> tuple[list[float], list[float]]:
    inv_keys = list(INVESTIGATOR_ORDER)
    n = len(strat_regret_by_inv[inv_keys[0]])
    if n == 0:
        raise ValueError("cannot bootstrap empty regret arrays")
    if n == 1 or n_resamples <= 0:
        s_min = min(float(strat_regret_by_inv[k][0]) for k in inv_keys)
        b_min = min(float(base_regret_by_inv[k][0]) for k in inv_keys)
        gain = s_min - b_min
        return [s_min, s_min], [gain, gain]
    rng = random.Random(seed)
    min_vals: list[float] = []
    gain_vals: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        s_min = min(
            sum(strat_regret_by_inv[k][i] for i in idx) / n
            for k in inv_keys
        )
        b_min = min(
            sum(base_regret_by_inv[k][i] for i in idx) / n
            for k in inv_keys
        )
        min_vals.append(float(s_min))
        gain_vals.append(float(s_min - b_min))
    min_vals.sort()
    gain_vals.sort()
    lo_idx = int(0.025 * n_resamples)
    hi_idx = max(0, int(0.975 * n_resamples) - 1)
    return (
        [min_vals[lo_idx], min_vals[hi_idx]],
        [gain_vals[lo_idx], gain_vals[hi_idx]],
    )


def _eval_strategy_seed(task: tuple[str, int, dict[str, Any]]) -> dict[str, Any]:
    tier, seed, strat_json = task
    strat = MoleStrategy.from_json(strat_json)

    sol_res = run_episode(Env(tier, seed, mole_strategy=strat), SolverPolicy(tier))
    gem_res = run_episode(Env(tier, seed, mole_strategy=strat), GeminiCarbonProxy(seed=seed))
    cdx_res = run_episode(Env(tier, seed, mole_strategy=strat), CodexHorizonProxy(seed=seed))
    grk_res = run_episode(Env(tier, seed, mole_strategy=strat), GrokTactics(seed=seed))
    heu_res = run_episode(Env(tier, seed, mole_strategy=strat), Heuristic(seed=seed))
    hh_res = run_episode(Env(tier, seed, mole_strategy=strat), HintedHeuristic(seed=seed))

    lo_res = run_episode(Env(tier, seed, mole_strategy=strat), LogsOnly(seed=seed))
    aml_res = run_episode(Env(tier, seed, mole_strategy=strat), AccuseMostLogs(seed=seed))
    dn_res = run_episode(Env(tier, seed, mole_strategy=strat), DoNothing(seed=seed))
    seq_res = run_episode(Env(tier, seed, mole_strategy=strat), StopEarlyQuit(seed=seed))

    env_unf = Env(tier, seed, mole_strategy=strat)
    pol_unf = StopEarlyQuit(seed=seed)
    pol_unf.reset(env_unf.tools_spec(), env_unf.instruction())
    for _ in range(3):
        tool, args = pol_unf.act(list(env_unf.history))
        env_unf.call(tool, args)
    unf_score = float(env_unf.score())

    def _pack(res: Any) -> dict[str, Any]:
        return {
            "score": float(res.score),
            "correct": bool(res.correct),
            "final_day": int(res.final_day),
            "accused_flag": bool(res.end_reason == "accused"),
        }

    return {
        "seed": int(seed),
        "strategy": strat.name,
        "solver": _pack(sol_res),
        "investigators": {
            "gemini_carbon_proxy": _pack(gem_res),
            "codex_horizon_proxy": _pack(cdx_res),
            "grok_tactics": _pack(grk_res),
            "heuristic": _pack(heu_res),
            "hinted_heuristic": _pack(hh_res),
        },
        "baselines": {
            "logs_only": _pack(lo_res),
            "accuse_most_logs": _pack(aml_res),
            "do_nothing": _pack(dn_res),
            "stop_early_quit": {
                **_pack(seq_res),
                "unfinished_score": unf_score,
            },
        },
    }


def _mean(xs: Sequence[float]) -> float:
    return float(sum(xs) / len(xs)) if xs else 0.0


def _mean_accuse_day(rows: Sequence[dict[str, Any]], horizon: int) -> float:
    acc_days = [float(r["final_day"]) for r in rows if r["accused_flag"]]
    return _mean(acc_days) if acc_days else float(horizon)


def _summarize_counterfactual(
    cf_raw: dict[str, Any],
    strategy_names: Sequence[str],
    n_resamples: int,
    boot_seed: int,
) -> dict[str, Any]:
    default_name = DEFAULT_STRATEGY.name
    base_entry = cf_raw["strategies"][default_name]
    base_comb_eps = base_entry["combined"]["episodes"]
    base_by_key = {(e["agent"], int(e["seed"])): e for e in base_comb_eps}
    base_sol_by_seed = {
        int(r["seed"]): float(r["score"])
        for r in (base_entry["solver"]["episodes"] if base_entry["solver"] is not None else [])
    }
    sources = list(cf_raw["sources"])
    paired_seeds = [int(s) for s in cf_raw["seeds"]]

    def _per_seed_avg_ev(entry: dict[str, Any]) -> dict[int, float]:
        by_seed: dict[int, list[float]] = {s: [] for s in paired_seeds}
        for src in sources:
            for e in entry["per_source"][src]["episodes"]:
                by_seed[int(e["seed"])].append(float(e["optimal_ev"]))
        return {s: _mean(vals) for s, vals in by_seed.items()}

    base_seed_ev = _per_seed_avg_ev(base_entry)
    base_seed_cf_regret = [
        base_sol_by_seed[s] - base_seed_ev[s]
        for s in paired_seeds
        if s in base_sol_by_seed
    ]

    out_by_strategy: dict[str, Any] = {}
    for idx, name in enumerate(strategy_names):
        entry = cf_raw["strategies"][name]
        comb = entry["combined"]
        comb_eps = comb["episodes"]
        pairs = [
            (e, base_by_key[(e["agent"], int(e["seed"]))])
            for e in comb_eps
            if (e["agent"], int(e["seed"])) in base_by_key
        ]
        can_deltas = [float(e["surfaced_canaries"] - b["surfaced_canaries"]) for e, b in pairs]
        p_drops = [float(b["p_true_mole"] - e["p_true_mole"]) for e, b in pairs]
        ev_drops = [float(b["optimal_ev"] - e["optimal_ev"]) for e, b in pairs]

        sol_block = entry["solver"]
        sol_by_seed = {
            int(r["seed"]): float(r["score"])
            for r in (sol_block["episodes"] if sol_block is not None else [])
        }
        strat_seed_ev = _per_seed_avg_ev(entry)
        seed_cf_regret = [
            sol_by_seed[s] - strat_seed_ev[s]
            for s in paired_seeds
            if s in sol_by_seed
        ]
        seed_cf_gain = [
            a - b for a, b in zip(seed_cf_regret, base_seed_cf_regret)
        ]

        per_source_clean: dict[str, Any] = {}
        for src in sources:
            ps = entry["per_source"][src]
            cf_reg_src = (
                float(sol_block["score"] - ps["optimal_ev"])
                if sol_block is not None
                else 0.0
            )
            base_cf_reg_src = (
                float(base_entry["solver"]["score"] - base_entry["per_source"][src]["optimal_ev"])
                if base_entry["solver"] is not None
                else 0.0
            )
            per_source_clean[src] = {
                "n_transcripts": int(ps["n"]),
                "planted_canaries": float(ps["planted_canaries"]),
                "surfaced_canaries": float(ps["surfaced_canaries"]),
                "surfaced_canaries_delta": float(ps["surfaced_canaries_delta"]),
                "surfaced_canaries_horizon": float(ps["surfaced_canaries_horizon"]),
                "surfaced_canaries_horizon_delta": float(ps["surfaced_canaries_horizon_delta"]),
                "surfaced_total_leaks": float(ps["surfaced_total_leaks"]),
                "surfaced_total_leaks_delta": float(ps["surfaced_total_leaks_delta"]),
                "p_true_mole": float(ps["p_true_mole"]),
                "p_true_mole_drop": float(ps["p_true_mole_drop"]),
                "p_true_mole_horizon": float(ps["p_true_mole_horizon"]),
                "p_true_mole_horizon_drop": float(ps["p_true_mole_horizon_drop"]),
                "top_suspect_accuracy": float(ps["top_suspect_accuracy"]),
                "optimal_ev": float(ps["optimal_ev"]),
                "optimal_ev_drop": float(ps["optimal_ev_drop"]),
                "counterfactual_regret": cf_reg_src,
                "counterfactual_regret_gain_vs_default": float(cf_reg_src - base_cf_reg_src),
            }

        cf_regret = float(entry["counterfactual_gap"]) if entry["counterfactual_gap"] is not None else 0.0
        cf_gain = float(entry["counterfactual_gap_gain"]) if entry["counterfactual_gap_gain"] is not None else 0.0

        out_by_strategy[name] = {
            "n_transcripts": int(comb["n"]),
            "n_seeds": len(paired_seeds),
            "planted_canaries": float(comb["planted_canaries"]),
            "surfaced_canaries": float(comb["surfaced_canaries"]),
            "surfaced_canaries_delta": float(comb["surfaced_canaries_delta"]),
            "surfaced_canaries_delta_boot_ci_95": bootstrap_mean_ci(
                can_deltas, n_resamples=n_resamples, seed=boot_seed + 100 + idx
            ),
            "surfaced_canaries_horizon": float(comb["surfaced_canaries_horizon"]),
            "surfaced_canaries_horizon_delta": float(comb["surfaced_canaries_horizon_delta"]),
            "surfaced_total_leaks": float(comb["surfaced_total_leaks"]),
            "surfaced_total_leaks_delta": float(comb["surfaced_total_leaks_delta"]),
            "p_true_mole": float(comb["p_true_mole"]),
            "p_true_mole_drop": float(comb["p_true_mole_drop"]),
            "p_true_mole_drop_ci_95": _clean_ci_halfwidth(p_drops),
            "p_true_mole_drop_boot_ci_95": bootstrap_mean_ci(
                p_drops, n_resamples=n_resamples, seed=boot_seed + 200 + idx
            ),
            "p_true_mole_horizon": float(comb["p_true_mole_horizon"]),
            "p_true_mole_horizon_drop": float(comb["p_true_mole_horizon_drop"]),
            "top_suspect_accuracy": float(comb["top_suspect_accuracy"]),
            "top_suspect_accuracy_horizon": float(comb["top_suspect_accuracy_horizon"]),
            "optimal_ev": float(comb["optimal_ev"]),
            "optimal_ev_ci_95": float(comb["optimal_ev_ci"]) if math.isfinite(comb["optimal_ev_ci"]) else 0.0,
            "optimal_ev_drop": float(comb["optimal_ev_drop"]),
            "optimal_ev_drop_ci_95": _clean_ci_halfwidth(ev_drops),
            "optimal_ev_drop_boot_ci_95": bootstrap_mean_ci(
                ev_drops, n_resamples=n_resamples, seed=boot_seed + 300 + idx
            ),
            "optimal_ev_horizon": float(comb["optimal_ev_horizon"]),
            "optimal_ev_horizon_drop": float(comb["optimal_ev_horizon_drop"]),
            "solver_score_on_cf_seeds": float(sol_block["score"]) if sol_block is not None else 0.0,
            "solver_acc_on_cf_seeds": float(sol_block["accuracy"]) if sol_block is not None else 0.0,
            "solver_accuse_day_on_cf_seeds": float(sol_block["accuse_day"]) if sol_block is not None else 0.0,
            "counterfactual_regret": cf_regret,
            "counterfactual_regret_boot_ci_95": (
                bootstrap_mean_ci(seed_cf_regret, n_resamples=n_resamples, seed=boot_seed + 400 + idx)
                if seed_cf_regret
                else [0.0, 0.0]
            ),
            "counterfactual_regret_gain_vs_default": cf_gain,
            "counterfactual_regret_gain_boot_ci_95": (
                bootstrap_mean_ci(seed_cf_gain, n_resamples=n_resamples, seed=boot_seed + 500 + idx)
                if seed_cf_gain
                else [0.0, 0.0]
            ),
            "per_source": per_source_clean,
        }

    return {
        "tier": str(cf_raw["tier"]),
        "sources": sources,
        "transcript_seeds": paired_seeds,
        "n_seeds": len(paired_seeds),
        "n_transcripts_total": sum(
            int(base_entry["per_source"][src]["n"]) for src in sources
        ),
        "n_transcripts_by_source": {
            src: int(base_entry["per_source"][src]["n"]) for src in sources
        },
        "strategies": out_by_strategy,
    }


def evaluate_mole_strategies_v14(
    *,
    tier: str = "hard",
    seeds: str | Iterable[int] = DEFAULT_EVAL_SEEDS_SPEC,
    cf_seeds: str | Iterable[int] = DEFAULT_CF_SEEDS_SPEC,
    strategy_names: Sequence[str] | None = None,
    workers: int = 2,
    n_boot: int = DEFAULT_BOOT_RESAMPLES,
    boot_seed: int = DEFAULT_BOOT_SEED,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    eval_seeds = validate_eval_seeds(seeds)
    cf_seed_list = _parse_seed_spec(cf_seeds) if isinstance(cf_seeds, str) else [int(s) for s in cf_seeds]
    if not cf_seed_list:
        raise ValueError("cf_seeds must not be empty")

    selected_non_default = (
        list_strategy_names(include_default=False)
        if strategy_names is None
        else [str(x) for x in strategy_names if str(x) not in ("default", DEFAULT_STRATEGY.name)]
    )
    if not selected_non_default:
        raise ValueError("at least one non-default strategy is required")

    ordered_names = [DEFAULT_STRATEGY.name, *selected_non_default]
    strategy_objs: dict[str, MoleStrategy] = {DEFAULT_STRATEGY.name: DEFAULT_STRATEGY}
    for name in selected_non_default:
        strat = get_strategy(name)
        sj = strat.to_json()
        if MoleStrategy.from_json(json.loads(json.dumps(sj))) != strat or len(strat.rules) > MAX_RULES:
            raise ValueError(f"strategy {name!r} failed round-trip validation")
        validate_strategy({"rules": sj["rules"], "default": sj["default"]})
        if not all(is_valid_rule_conds(r["if"], tier) for r in sj["rules"]):
            raise ValueError(f"strategy {name!r} has invalid rule conditions on tier {tier!r}")
        strategy_objs[name] = strat

    all_tasks: list[tuple[str, int, dict[str, Any]]] = [
        (tier, s, strategy_objs[name].to_json())
        for name in ordered_names
        for s in eval_seeds
    ]
    if workers > 1 and len(all_tasks) > 1:
        chunk = max(1, min(8, len(all_tasks) // (workers * 4) or 1))
        with ProcessPoolExecutor(max_workers=min(workers, len(all_tasks))) as pool:
            raw_results = list(pool.map(_eval_strategy_seed, all_tasks, chunksize=chunk))
    else:
        raw_results = [_eval_strategy_seed(t) for t in all_tasks]

    rows_by_strat: dict[str, list[dict[str, Any]]] = {name: [] for name in ordered_names}
    for item in raw_results:
        rows_by_strat[str(item["strategy"])].append(item)
    for name in ordered_names:
        rows_by_strat[name].sort(key=lambda r: int(r["seed"]))

    horizon = int(tier_params(tier).n_days)
    base_rows = rows_by_strat[DEFAULT_STRATEGY.name]
    base_sol_scores = [float(r["solver"]["score"]) for r in base_rows]
    base_sol_mean = _mean(base_sol_scores)
    base_sol_acc = _mean([1.0 if r["solver"]["correct"] else 0.0 for r in base_rows])
    base_regret_by_inv: dict[str, list[float]] = {
        inv: [
            float(r["solver"]["score"]) - float(r["investigators"][inv]["score"])
            for r in base_rows
        ]
        for inv in INVESTIGATOR_ORDER
    }
    base_inv_regret_means = {inv: _mean(vals) for inv, vals in base_regret_by_inv.items()}
    base_min_regret = min(base_inv_regret_means.values())
    base_mean_regret = _mean(list(base_inv_regret_means.values()))

    cf_raw = evaluate_counterfactual(
        strategies=strategy_objs,
        seeds=cf_seed_list,
        tier=tier,
        run_solver=True,
        sources=("opencode", "inproc"),
        workers=workers,
        min_solver_acc=min_solver_acc,
    )
    cf_summary = _summarize_counterfactual(
        cf_raw,
        strategy_names=ordered_names,
        n_resamples=n_boot,
        boot_seed=boot_seed,
    )

    strategies_out: dict[str, Any] = {}
    bhashes: list[str] = []

    for s_idx, name in enumerate(ordered_names):
        is_def = name == DEFAULT_STRATEGY.name
        strat = strategy_objs[name]
        sj = strat.to_json()
        bh = behavior_hash(sj, tier)
        bhashes.append(bh)
        spec = None if is_def else get_strategy_spec(name)
        rows = rows_by_strat[name]

        sol_rows = [r["solver"] for r in rows]
        sol_scores = [float(x["score"]) for x in sol_rows]
        sol_acc = _mean([1.0 if x["correct"] else 0.0 for x in sol_rows])
        sol_mean = _mean(sol_scores)
        sol_ci = _clean_ci_halfwidth(sol_scores)
        sol_boot = bootstrap_mean_ci(sol_scores, n_resamples=n_boot, seed=boot_seed + 10 * s_idx)
        sol_accuse_day = _mean_accuse_day(sol_rows, horizon)
        sol_final_day = _mean([float(x["final_day"]) for x in sol_rows])
        sol_accused_rate = _mean([1.0 if x["accused_flag"] else 0.0 for x in sol_rows])
        sol_deltas = [a - b for a, b in zip(sol_scores, base_sol_scores)]
        sol_delta_mean = _mean(sol_deltas)
        sol_delta_boot = bootstrap_mean_ci(sol_deltas, n_resamples=n_boot, seed=boot_seed + 10 * s_idx + 1)
        sol_ratio = (sol_mean / base_sol_mean) if base_sol_mean > 0.0 else 0.0
        sol_acc_ok = bool(sol_acc >= min_solver_acc)
        sol_ratio_ok = bool(sol_mean >= min_solver_ratio * base_sol_mean)

        inv_out: dict[str, Any] = {}
        strat_regret_by_inv: dict[str, list[float]] = {}
        for i_idx, inv in enumerate(INVESTIGATOR_ORDER):
            inv_rows = [r["investigators"][inv] for r in rows]
            base_inv_scores = [float(r["investigators"][inv]["score"]) for r in base_rows]
            inv_scores = [float(x["score"]) for x in inv_rows]
            inv_acc = _mean([1.0 if x["correct"] else 0.0 for x in inv_rows])
            inv_mean = _mean(inv_scores)
            inv_ci = _clean_ci_halfwidth(inv_scores)
            inv_boot = bootstrap_mean_ci(
                inv_scores, n_resamples=n_boot, seed=boot_seed + 1000 + 20 * s_idx + i_idx
            )
            inv_day = _mean_accuse_day(inv_rows, horizon)
            inv_score_deltas = [a - b for a, b in zip(inv_scores, base_inv_scores)]
            inv_delta_boot = bootstrap_mean_ci(
                inv_score_deltas, n_resamples=n_boot, seed=boot_seed + 2000 + 20 * s_idx + i_idx
            )

            regrets = [sol - sc for sol, sc in zip(sol_scores, inv_scores)]
            strat_regret_by_inv[inv] = regrets
            regret_mean = _mean(regrets)
            regret_ci = _clean_ci_halfwidth(regrets)
            regret_boot = bootstrap_mean_ci(
                regrets, n_resamples=n_boot, seed=boot_seed + 3000 + 20 * s_idx + i_idx
            )

            regret_gains = [
                r_s - r_b for r_s, r_b in zip(regrets, base_regret_by_inv[inv])
            ]
            regret_gain_mean = _mean(regret_gains)
            regret_gain_boot = bootstrap_mean_ci(
                regret_gains, n_resamples=n_boot, seed=boot_seed + 4000 + 20 * s_idx + i_idx
            )

            inv_out[inv] = {
                "label": INVESTIGATOR_LABELS[inv],
                "score": inv_mean,
                "score_ci_95": inv_ci,
                "score_boot_ci_95": inv_boot,
                "accuracy": inv_acc,
                "mean_accuse_day": inv_day,
                "score_delta_vs_default": _mean(inv_score_deltas),
                "score_delta_boot_ci_95": inv_delta_boot,
                "regret": regret_mean,
                "regret_ci_95": regret_ci,
                "regret_boot_ci_95": regret_boot,
                "regret_gain_vs_default": regret_gain_mean,
                "regret_gain_boot_ci_95": regret_gain_boot,
            }

        strongest_inv = max(INVESTIGATOR_ORDER, key=lambda k: inv_out[k]["score"])
        strongest_score = float(inv_out[strongest_inv]["score"])
        min_regret = min(float(inv_out[k]["regret"]) for k in INVESTIGATOR_ORDER)
        min_reg_boot, min_gain_boot = paired_bootstrap_min_regret(
            strat_regret_by_inv,
            base_regret_by_inv,
            n_resamples=n_boot,
            seed=boot_seed + 5000 + s_idx,
        )
        min_regret_gain = float(min_regret - base_min_regret)

        per_seed_mean_regret = [
            sum(strat_regret_by_inv[k][i] for k in INVESTIGATOR_ORDER) / len(INVESTIGATOR_ORDER)
            for i in range(len(rows))
        ]
        per_seed_mean_gain = [
            per_seed_mean_regret[i]
            - (sum(base_regret_by_inv[k][i] for k in INVESTIGATOR_ORDER) / len(INVESTIGATOR_ORDER))
            for i in range(len(rows))
        ]
        mean_regret = _mean([float(inv_out[k]["regret"]) for k in INVESTIGATOR_ORDER])
        mean_regret_gain = float(mean_regret - base_mean_regret)
        mean_gain_boot = bootstrap_mean_ci(
            per_seed_mean_gain, n_resamples=n_boot, seed=boot_seed + 6000 + s_idx
        )

        lo_rows = [r["baselines"]["logs_only"] for r in rows]
        lo_scores = [float(x["score"]) for x in lo_rows]
        lo_mean = _mean(lo_scores)
        lo_acc = _mean([1.0 if x["correct"] else 0.0 for x in lo_rows])
        lo_ok = bool(lo_acc <= max_logs_acc and lo_mean < 0.0)

        aml_rows = [r["baselines"]["accuse_most_logs"] for r in rows]
        aml_scores = [float(x["score"]) for x in aml_rows]
        aml_mean = _mean(aml_scores)
        aml_acc = _mean([1.0 if x["correct"] else 0.0 for x in aml_rows])
        aml_ok = bool(aml_acc <= max_logs_acc and aml_mean < 0.0)

        dn_rows = [r["baselines"]["do_nothing"] for r in rows]
        dn_scores = [float(x["score"]) for x in dn_rows]
        dn_acc = _mean([1.0 if x["correct"] else 0.0 for x in dn_rows])
        dn_max_abs = max((abs(x) for x in dn_scores), default=0.0)
        dn_all_zero = bool(all(x == 0.0 for x in dn_scores) and dn_acc == 0.0)

        seq_rows = [r["baselines"]["stop_early_quit"] for r in rows]
        seq_scores = [float(x["score"]) for x in seq_rows]
        seq_unf = [float(x["unfinished_score"]) for x in seq_rows]
        seq_acc = _mean([1.0 if x["correct"] else 0.0 for x in seq_rows])
        seq_max_abs = max([*(abs(x) for x in seq_scores), *(abs(x) for x in seq_unf)], default=0.0)
        seq_all_zero = bool(
            all(x == 0.0 for x in seq_scores)
            and all(x == 0.0 for x in seq_unf)
            and seq_acc == 0.0
        )

        baselines_out = {
            "logs_only": {
                "score": lo_mean,
                "score_ci_95": _clean_ci_halfwidth(lo_scores),
                "accuracy": lo_acc,
                "max_acc_bound": float(max_logs_acc),
                "passed": lo_ok,
            },
            "accuse_most_logs": {
                "score": aml_mean,
                "score_ci_95": _clean_ci_halfwidth(aml_scores),
                "accuracy": aml_acc,
                "max_acc_bound": float(max_logs_acc),
                "passed": aml_ok,
            },
            "do_nothing": {
                "score": _mean(dn_scores),
                "accuracy": dn_acc,
                "max_abs_score": dn_max_abs,
                "all_zero": dn_all_zero,
                "passed": dn_all_zero,
            },
            "stop_early_quit": {
                "score": _mean(seq_scores),
                "unfinished_score": _mean(seq_unf),
                "accuracy": seq_acc,
                "max_abs_score": seq_max_abs,
                "all_zero": seq_all_zero,
                "passed": seq_all_zero,
            },
            "all_passed": bool(lo_ok and aml_ok and dn_all_zero and seq_all_zero),
        }

        gem_entry = inv_out["gemini_carbon_proxy"]
        strat_passed = bool(sol_acc_ok and sol_ratio_ok and baselines_out["all_passed"])

        strategies_out[name] = {
            "name": name,
            "display_name": f"DEFAULT_STRATEGY ({name})" if is_def else name,
            "is_default": is_def,
            "lever_id": "baseline_uniform_random" if is_def else spec.lever_id,
            "target_cohort": "baseline" if is_def else spec.target_cohort,
            "n_rules": len(strat.rules),
            "behavior_hash": bh,
            "empirical_finding": (
                "Uniform seeded leak selection with zero framing rules (baseline reference)."
                if is_def
                else spec.empirical_finding
            ),
            "solver_catchability_rationale": (
                "Baseline uniform leak policy with no evasion rules."
                if is_def
                else spec.solver_catchability_rationale
            ),
            "empirical_anchors": {} if is_def else dict(spec.empirical_anchors),
            "strategy_json": sj,
            "solver": {
                "score": sol_mean,
                "score_ci_95": sol_ci,
                "score_boot_ci_95": sol_boot,
                "accuracy": sol_acc,
                "mean_accuse_day": sol_accuse_day,
                "mean_final_day": sol_final_day,
                "accused_rate": sol_accused_rate,
                "score_delta_vs_default": sol_delta_mean,
                "score_delta_boot_ci_95": sol_delta_boot,
                "accuracy_delta_vs_default": float(sol_acc - base_sol_acc),
                "ratio_vs_default": sol_ratio,
                "min_solver_acc": float(min_solver_acc),
                "min_solver_ratio": float(min_solver_ratio),
                "passed_acc_gate": sol_acc_ok,
                "passed_ratio_gate": sol_ratio_ok,
                "passed": bool(sol_acc_ok and sol_ratio_ok),
            },
            "investigators": inv_out,
            "regret_summary": {
                "strongest_investigator": strongest_inv,
                "strongest_investigator_label": INVESTIGATOR_LABELS[strongest_inv],
                "strongest_investigator_score": strongest_score,
                "min_regret": min_regret,
                "min_regret_boot_ci_95": min_reg_boot,
                "min_regret_gain_vs_default": min_regret_gain,
                "min_regret_gain_boot_ci_95": min_gain_boot,
                "mean_regret": mean_regret,
                "mean_regret_gain_vs_default": mean_regret_gain,
                "mean_regret_gain_boot_ci_95": mean_gain_boot,
                "gemini_regret": float(gem_entry["regret"]),
                "gemini_regret_boot_ci_95": list(gem_entry["regret_boot_ci_95"]),
                "gemini_regret_gain_vs_default": float(gem_entry["regret_gain_vs_default"]),
                "gemini_regret_gain_boot_ci_95": list(gem_entry["regret_gain_boot_ci_95"]),
            },
            "baselines": baselines_out,
            "counterfactual": cf_summary["strategies"][name],
            "passed": strat_passed,
        }

    unique_bhashes = len(set(bhashes)) == len(bhashes)
    all_sol_ok = all(strategies_out[n]["solver"]["passed"] for n in ordered_names)
    all_logs_ok = all(
        strategies_out[n]["baselines"]["logs_only"]["passed"]
        and strategies_out[n]["baselines"]["accuse_most_logs"]["passed"]
        for n in ordered_names
    )
    all_zero_ok = all(
        strategies_out[n]["baselines"]["do_nothing"]["passed"]
        and strategies_out[n]["baselines"]["stop_early_quit"]["passed"]
        for n in ordered_names
    )

    best_by_min_regret = max(
        selected_non_default,
        key=lambda n: strategies_out[n]["regret_summary"]["min_regret"],
    )
    best_by_gemini_gain = max(
        selected_non_default,
        key=lambda n: strategies_out[n]["regret_summary"]["gemini_regret_gain_vs_default"],
    )
    best_by_cf_ev_drop = max(
        selected_non_default,
        key=lambda n: strategies_out[n]["counterfactual"]["optimal_ev_drop"],
    )

    payload: dict[str, Any] = {
        "schema_version": "mole_strategies_v14_eval.v1",
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seed_range": f"{eval_seeds[0]}-{eval_seeds[-1]}",
        "n_seeds": len(eval_seeds),
        "seeds": eval_seeds,
        "seed_hygiene": {
            "forbidden_low_range": f"0-{FORBIDDEN_LOW_MAX}",
            "forbidden_reserved_range": "30000-30199",
            "forbidden_high_min": FORBIDDEN_HIGH_MIN,
            "verified_disjoint_fresh": True,
        },
        "bootstrap": {
            "n_resamples": int(n_boot),
            "seed": int(boot_seed),
            "ci_level": 0.95,
            "method": "paired_seed_percentile",
        },
        "baseline_strategy": DEFAULT_STRATEGY.name,
        "strategy_order": ordered_names,
        "transcript_strategy_order": selected_non_default,
        "investigator_order": list(INVESTIGATOR_ORDER),
        "baseline_order": list(BASELINE_ORDER),
        "gates": {
            "min_solver_acc": float(min_solver_acc),
            "min_solver_ratio": float(min_solver_ratio),
            "max_logs_acc": float(max_logs_acc),
            "seed_hygiene_passed": True,
            "unique_behavior_hashes": unique_bhashes,
            "all_solver_acc_ge_085": all_sol_ok,
            "all_logs_only_le_010": all_logs_ok,
            "all_zero_baselines_exact": all_zero_ok,
            "all_passed": bool(unique_bhashes and all_sol_ok and all_logs_ok and all_zero_ok),
        },
        "highlights": {
            "best_min_regret_strategy": best_by_min_regret,
            "best_gemini_regret_gain_strategy": best_by_gemini_gain,
            "best_counterfactual_ev_drop_strategy": best_by_cf_ev_drop,
        },
        "counterfactual_meta": {
            "tier": cf_summary["tier"],
            "sources": cf_summary["sources"],
            "transcript_seeds": cf_summary["transcript_seeds"],
            "n_seeds": cf_summary["n_seeds"],
            "n_transcripts_total": cf_summary["n_transcripts_total"],
            "n_transcripts_by_source": cf_summary["n_transcripts_by_source"],
        },
        "strategies": strategies_out,
    }
    assert_payload_hygiene_and_invariants(payload, tol=DEFAULT_TOL)
    return payload


def approx_equal(a: Any, b: Any, tol: float = DEFAULT_TOL) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not (math.isfinite(float(a)) and math.isfinite(float(b))):
            return False
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a.keys()) == set(b.keys()) and all(approx_equal(a[k], b[k], tol=tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol=tol) for x, y in zip(a, b))
    return a == b


def assert_payload_hygiene_and_invariants(payload: dict[str, Any], tol: float = DEFAULT_TOL) -> None:
    def _walk(obj: Any, path: str = "root") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                ks = str(k)
                if ks in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden key {ks!r} at {path}.{ks}")
                _walk(v, f"{path}.{ks}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")
        elif isinstance(obj, float):
            if not math.isfinite(obj):
                raise ValueError(f"non-finite float at {path}: {obj!r}")
        elif isinstance(obj, str):
            if EM_DASH in obj or EN_DASH in obj:
                raise ValueError(f"forbidden dash character in string at {path}")

    _walk(payload)
    serialized = json.dumps(payload, sort_keys=True, allow_nan=False)
    for rx in SECRET_PATTERNS:
        if rx.search(serialized):
            raise ValueError("secret key pattern detected in JSON payload")

    validate_eval_seeds(payload["seeds"])
    if len(payload["seeds"]) != int(payload["n_seeds"]):
        raise ValueError("n_seeds mismatch")

    base_name = str(payload["baseline_strategy"])
    strats = payload["strategies"]
    if base_name not in strats:
        raise ValueError(f"missing baseline strategy {base_name!r}")
    base = strats[base_name]
    base_min_reg = float(base["regret_summary"]["min_regret"])
    min_sol_acc = float(payload["gates"]["min_solver_acc"])
    max_logs_acc = float(payload["gates"]["max_logs_acc"])

    for name in payload["strategy_order"]:
        row = strats[name]
        sol = row["solver"]
        if float(sol["accuracy"]) + tol < min_sol_acc:
            raise ValueError(f"{name} solver accuracy {sol['accuracy']} < {min_sol_acc}")

        inv_regrets: list[float] = []
        for inv in payload["investigator_order"]:
            iv = row["investigators"][inv]
            expected_reg = float(sol["score"]) - float(iv["score"])
            if abs(float(iv["regret"]) - expected_reg) > tol:
                raise ValueError(f"{name}.{inv} regret mismatch: {iv['regret']} vs {expected_reg}")
            expected_gain = float(iv["regret"]) - float(base["investigators"][inv]["regret"])
            if abs(float(iv["regret_gain_vs_default"]) - expected_gain) > tol:
                raise ValueError(f"{name}.{inv} regret_gain mismatch")
            inv_regrets.append(float(iv["regret"]))

        rs = row["regret_summary"]
        if abs(float(rs["min_regret"]) - min(inv_regrets)) > tol:
            raise ValueError(f"{name} min_regret mismatch")
        if abs(float(rs["min_regret_gain_vs_default"]) - (float(rs["min_regret"]) - base_min_reg)) > tol:
            raise ValueError(f"{name} min_regret_gain mismatch")
        gem_iv = row["investigators"]["gemini_carbon_proxy"]
        if abs(float(rs["gemini_regret"]) - float(gem_iv["regret"])) > tol:
            raise ValueError(f"{name} gemini_regret mismatch")
        if abs(float(rs["gemini_regret_gain_vs_default"]) - float(gem_iv["regret_gain_vs_default"])) > tol:
            raise ValueError(f"{name} gemini_regret_gain mismatch")

        bl = row["baselines"]
        if float(bl["logs_only"]["accuracy"]) - tol > max_logs_acc:
            raise ValueError(f"{name} logs_only accuracy exceeds {max_logs_acc}")
        if float(bl["accuse_most_logs"]["accuracy"]) - tol > max_logs_acc:
            raise ValueError(f"{name} accuse_most_logs accuracy exceeds {max_logs_acc}")
        if abs(float(bl["do_nothing"]["score"])) > tol or abs(float(bl["do_nothing"]["max_abs_score"])) > tol:
            raise ValueError(f"{name} do_nothing nonzero")
        if (
            abs(float(bl["stop_early_quit"]["score"])) > tol
            or abs(float(bl["stop_early_quit"]["unfinished_score"])) > tol
            or abs(float(bl["stop_early_quit"]["max_abs_score"])) > tol
        ):
            raise ValueError(f"{name} stop_early_quit nonzero")

        cf = row["counterfactual"]
        expected_cf_reg = float(cf["solver_score_on_cf_seeds"]) - float(cf["optimal_ev"])
        if abs(float(cf["counterfactual_regret"]) - expected_cf_reg) > tol:
            raise ValueError(f"{name} counterfactual_regret mismatch")
        expected_cf_gain = float(cf["counterfactual_regret"]) - float(base["counterfactual"]["counterfactual_regret"])
        if abs(float(cf["counterfactual_regret_gain_vs_default"]) - expected_cf_gain) > tol:
            raise ValueError(f"{name} counterfactual_regret_gain mismatch")


def extract_report_ledger(payload: dict[str, Any]) -> dict[str, Any]:
    strategies_ledger: dict[str, Any] = {}
    for name in payload["strategy_order"]:
        s = payload["strategies"][name]
        strategies_ledger[name] = {
            "display_name": s["display_name"],
            "is_default": s["is_default"],
            "lever_id": s["lever_id"],
            "target_cohort": s["target_cohort"],
            "n_rules": s["n_rules"],
            "behavior_hash": s["behavior_hash"],
            "solver": {
                "score": s["solver"]["score"],
                "score_ci_95": s["solver"]["score_ci_95"],
                "score_boot_ci_95": list(s["solver"]["score_boot_ci_95"]),
                "accuracy": s["solver"]["accuracy"],
                "mean_accuse_day": s["solver"]["mean_accuse_day"],
                "ratio_vs_default": s["solver"]["ratio_vs_default"],
                "passed": s["solver"]["passed"],
            },
            "investigators": {
                inv: {
                    "score": s["investigators"][inv]["score"],
                    "accuracy": s["investigators"][inv]["accuracy"],
                    "regret": s["investigators"][inv]["regret"],
                    "regret_boot_ci_95": list(s["investigators"][inv]["regret_boot_ci_95"]),
                    "regret_gain_vs_default": s["investigators"][inv]["regret_gain_vs_default"],
                    "regret_gain_boot_ci_95": list(s["investigators"][inv]["regret_gain_boot_ci_95"]),
                }
                for inv in payload["investigator_order"]
            },
            "regret_summary": {
                "strongest_investigator": s["regret_summary"]["strongest_investigator"],
                "strongest_investigator_label": s["regret_summary"]["strongest_investigator_label"],
                "min_regret": s["regret_summary"]["min_regret"],
                "min_regret_boot_ci_95": list(s["regret_summary"]["min_regret_boot_ci_95"]),
                "min_regret_gain_vs_default": s["regret_summary"]["min_regret_gain_vs_default"],
                "min_regret_gain_boot_ci_95": list(s["regret_summary"]["min_regret_gain_boot_ci_95"]),
                "mean_regret": s["regret_summary"]["mean_regret"],
                "mean_regret_gain_vs_default": s["regret_summary"]["mean_regret_gain_vs_default"],
                "gemini_regret": s["regret_summary"]["gemini_regret"],
                "gemini_regret_boot_ci_95": list(s["regret_summary"]["gemini_regret_boot_ci_95"]),
                "gemini_regret_gain_vs_default": s["regret_summary"]["gemini_regret_gain_vs_default"],
                "gemini_regret_gain_boot_ci_95": list(s["regret_summary"]["gemini_regret_gain_boot_ci_95"]),
            },
            "baselines": {
                "logs_only_score": s["baselines"]["logs_only"]["score"],
                "logs_only_acc": s["baselines"]["logs_only"]["accuracy"],
                "accuse_most_logs_score": s["baselines"]["accuse_most_logs"]["score"],
                "accuse_most_logs_acc": s["baselines"]["accuse_most_logs"]["accuracy"],
                "do_nothing_score": s["baselines"]["do_nothing"]["score"],
                "do_nothing_max_abs": s["baselines"]["do_nothing"]["max_abs_score"],
                "stop_early_quit_score": s["baselines"]["stop_early_quit"]["score"],
                "stop_early_quit_unfinished_score": s["baselines"]["stop_early_quit"]["unfinished_score"],
                "stop_early_quit_max_abs": s["baselines"]["stop_early_quit"]["max_abs_score"],
                "all_passed": s["baselines"]["all_passed"],
            },
            "counterfactual": {
                "n_transcripts": s["counterfactual"]["n_transcripts"],
                "surfaced_canaries": s["counterfactual"]["surfaced_canaries"],
                "surfaced_canaries_delta": s["counterfactual"]["surfaced_canaries_delta"],
                "surfaced_canaries_horizon": s["counterfactual"]["surfaced_canaries_horizon"],
                "surfaced_canaries_horizon_delta": s["counterfactual"]["surfaced_canaries_horizon_delta"],
                "surfaced_total_leaks": s["counterfactual"]["surfaced_total_leaks"],
                "p_true_mole": s["counterfactual"]["p_true_mole"],
                "p_true_mole_drop": s["counterfactual"]["p_true_mole_drop"],
                "optimal_ev": s["counterfactual"]["optimal_ev"],
                "optimal_ev_drop": s["counterfactual"]["optimal_ev_drop"],
                "counterfactual_regret": s["counterfactual"]["counterfactual_regret"],
                "counterfactual_regret_gain_vs_default": s["counterfactual"]["counterfactual_regret_gain_vs_default"],
                "opencode_optimal_ev": s["counterfactual"]["per_source"]["opencode"]["optimal_ev"],
                "opencode_optimal_ev_drop": s["counterfactual"]["per_source"]["opencode"]["optimal_ev_drop"],
                "opencode_surfaced_canaries": s["counterfactual"]["per_source"]["opencode"]["surfaced_canaries"],
                "inproc_optimal_ev": s["counterfactual"]["per_source"]["inproc"]["optimal_ev"],
                "inproc_optimal_ev_drop": s["counterfactual"]["per_source"]["inproc"]["optimal_ev_drop"],
                "inproc_surfaced_canaries": s["counterfactual"]["per_source"]["inproc"]["surfaced_canaries"],
            },
            "passed": s["passed"],
        }

    return {
        "schema_version": payload["schema_version"],
        "tiers_version": payload["tiers_version"],
        "tier": payload["tier"],
        "seed_range": payload["seed_range"],
        "n_seeds": payload["n_seeds"],
        "bootstrap_resamples": payload["bootstrap"]["n_resamples"],
        "bootstrap_seed": payload["bootstrap"]["seed"],
        "baseline_strategy": payload["baseline_strategy"],
        "strategy_order": list(payload["strategy_order"]),
        "transcript_strategy_order": list(payload["transcript_strategy_order"]),
        "investigator_order": list(payload["investigator_order"]),
        "gates": dict(payload["gates"]),
        "highlights": dict(payload["highlights"]),
        "counterfactual_meta": dict(payload["counterfactual_meta"]),
        "strategies": strategies_ledger,
    }


def _fmt_boot(ci: Sequence[float], nd: int = 3, signed: bool = False) -> str:
    fmt = f"+.{nd}f" if signed else f".{nd}f"
    return f"[{ci[0]:{fmt}}, {ci[1]:{fmt}}]"


def render_report_from_ledger(ledger: dict[str, Any]) -> str:
    strats = ledger["strategies"]
    order = ledger["strategy_order"]
    non_def = ledger["transcript_strategy_order"]
    base_name = ledger["baseline_strategy"]
    base = strats[base_name]
    cf_meta = ledger["counterfactual_meta"]
    hl = ledger["highlights"]

    best_min_s = strats[hl["best_min_regret_strategy"]]
    best_gem_s = strats[hl["best_gemini_regret_gain_strategy"]]
    best_cf_s = strats[hl["best_counterfactual_ev_drop_strategy"]]

    lines: list[str] = [
        f"{H1} Transcript-Grounded Mole DSL Strategies: v1.4 Hard Fresh-Seed & Counterfactual Report",
        "",
        (
            f"Offline CPU evaluation on **{ledger['n_seeds']} fresh disjoint v1.4 `{ledger['tier']}` seeds "
            f"(`{ledger['seed_range']}`)** (seed hygiene enforced: `0-59`, `30000-30199`, `800000+`, and `900000+` "
            f"strictly forbidden) plus counterfactual schedule replay over **{cf_meta['n_transcripts_total']} committed "
            f"v1.4 Gemini-4-carbon Hard transcripts** ({cf_meta['n_transcripts_by_source']['opencode']} OpenCode MCP + "
            f"{cf_meta['n_transcripts_by_source']['inproc']} in-proc on seeds `{cf_meta['transcript_seeds'][0]}-"
            f"{cf_meta['transcript_seeds'][-1]}`). Paired bootstrap 95% CIs use `{ledger['bootstrap_resamples']}` "
            f"paired seed resamples (`seed={ledger['bootstrap_seed']}`). Zero Gemini API calls."
        ),
        "",
        "Reproduce or verify exact JSON-to-Markdown equivalence:",
        "```bash",
        "PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python scripts/eval_mole_strategies_v14.py --check",
        "```",
        "",
        f"{H2} 1. Headline Findings",
        "",
        (
            f"- **100% fairness and catchability pass rate ({len(non_def)}/{len(non_def)} transcript strategies + "
            f"`DEFAULT_STRATEGY`)**: Every strategy keeps `SolverPolicy(\"hard\")` accuracy >= "
            f"`{ledger['gates']['min_solver_acc']:.2f}`, `LogsOnly` and `AccuseMostLogs` accuracy <= "
            f"`{ledger['gates']['max_logs_acc']:.2f}`, and `DoNothing` / `StopEarlyQuit` identically `0.0` "
            f"(`all_passed={ledger['gates']['all_passed']}`, `unique_behavior_hashes="
            f"{ledger['gates']['unique_behavior_hashes']}`)."
        ),
        (
            f"- **Strongest worst-case investigator gap (`min_regret`)**: `{hl['best_min_regret_strategy']}` "
            f"achieves `min_regret = {best_min_s['regret_summary']['min_regret']:.3f}` "
            f"{_fmt_boot(best_min_s['regret_summary']['min_regret_boot_ci_95'])} vs `DEFAULT_STRATEGY` "
            f"`{base['regret_summary']['min_regret']:.3f}` "
            f"(gain `{best_min_s['regret_summary']['min_regret_gain_vs_default']:+.3f}`, 95% CI "
            f"{_fmt_boot(best_min_s['regret_summary']['min_regret_gain_boot_ci_95'], signed=True)})."
        ),
        (
            f"- **Strongest `GeminiCarbonProxy` paired regret gain**: `{hl['best_gemini_regret_gain_strategy']}` "
            f"reaches `GeminiCarbonProxy` regret `{best_gem_s['regret_summary']['gemini_regret']:.3f}` vs "
            f"`DEFAULT_STRATEGY` `{base['regret_summary']['gemini_regret']:.3f}` "
            f"(paired gain `{best_gem_s['regret_summary']['gemini_regret_gain_vs_default']:+.3f}`, 95% CI "
            f"{_fmt_boot(best_gem_s['regret_summary']['gemini_regret_gain_boot_ci_95'], signed=True)})."
        ),
        (
            f"- **Counterfactual replay on 60 real v1.4 Gemini Hard transcripts**: `{hl['best_counterfactual_ev_drop_strategy']}` "
            f"reduces Gemini optimal Bayesian EV at accusation by `{best_cf_s['counterfactual']['optimal_ev_drop']:+.3f}` "
            f"(surfaced canaries delta `{best_cf_s['counterfactual']['surfaced_canaries_delta']:+.2f}`, "
            f"`P(true mole)` drop `{best_cf_s['counterfactual']['p_true_mole_drop']:+.3f}`, counterfactual regret "
            f"`{best_cf_s['counterfactual']['counterfactual_regret']:.3f}`, gain vs `DEFAULT_STRATEGY` "
            f"`{best_cf_s['counterfactual']['counterfactual_regret_gain_vs_default']:+.3f}`)."
        ),
        "",
        f"{H2} 2. SolverPolicy(\"hard\") Catchability & Anti-Shortcut Baselines (Seeds {ledger['seed_range']}, n={ledger['n_seeds']})",
        "",
        "| Strategy | Rules | BHash | Solver Acc | Solver Score +/- 95% CI | Accuse Day | / Default | LogsOnly Acc (Score) | AccuseMostLogs Acc (Score) | DoNothing | StopEarlyQuit | Gate |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for name in order:
        s = strats[name]
        sol = s["solver"]
        bl = s["baselines"]
        gate = "PASS" if s["passed"] else "FAIL"
        lines.append(
            f"| `{s['display_name']}` | {s['n_rules']} | `{s['behavior_hash'][:8]}` | "
            f"{sol['accuracy']:.3f} | {sol['score']:.3f} +/- {sol['score_ci_95']:.3f} | "
            f"{sol['mean_accuse_day']:.2f} | {sol['ratio_vs_default']:.3f} | "
            f"{bl['logs_only_acc']:.3f} ({bl['logs_only_score']:+.3f}) | "
            f"{bl['accuse_most_logs_acc']:.3f} ({bl['accuse_most_logs_score']:+.3f}) | "
            f"{bl['do_nothing_score']:.3f} | {bl['stop_early_quit_score']:.3f} | {gate} |"
        )

    lines.extend([
        "",
        f"{H2} 3. Paired Investigator Regret (`solver - inv`) & Bootstrap 95% CIs (Seeds {ledger['seed_range']}, n={ledger['n_seeds']})",
        "",
        "| Strategy | Strongest Inv | Min Regret [95% Boot CI] | Min Regret Gain vs Default [95% Boot CI] | GeminiProxy Regret [95% Boot CI] | GeminiProxy Regret Gain [95% Boot CI] | Mean Suite Regret (Gain) |",
        "|---|---|---|---|---|---|---|",
    ])

    for name in order:
        s = strats[name]
        rs = s["regret_summary"]
        lines.append(
            f"| `{s['display_name']}` | {rs['strongest_investigator_label']} | "
            f"{rs['min_regret']:.3f} {_fmt_boot(rs['min_regret_boot_ci_95'])} | "
            f"{rs['min_regret_gain_vs_default']:+.3f} {_fmt_boot(rs['min_regret_gain_boot_ci_95'], signed=True)} | "
            f"{rs['gemini_regret']:.3f} {_fmt_boot(rs['gemini_regret_boot_ci_95'])} | "
            f"{rs['gemini_regret_gain_vs_default']:+.3f} {_fmt_boot(rs['gemini_regret_gain_boot_ci_95'], signed=True)} | "
            f"{rs['mean_regret']:.3f} ({rs['mean_regret_gain_vs_default']:+.3f}) |"
        )

    lines.extend([
        "",
        f"{H3} 3.1 Per-Investigator Score, Accuracy, and Paired Regret Breakdown",
        "",
        "| Strategy | GeminiCarbonProxy Score / Acc / Regret | CodexHorizonProxy Score / Acc / Regret | GrokTactics Score / Acc / Regret | Heuristic Score / Acc / Regret | HintedHeuristic Score / Acc / Regret |",
        "|---|---|---|---|---|---|",
    ])

    for name in order:
        s = strats[name]
        iv = s["investigators"]
        cells = [
            f"{iv[k]['score']:+.3f} / {iv[k]['accuracy']:.2f} / {iv[k]['regret']:+.3f}"
            for k in ledger["investigator_order"]
        ]
        lines.append(f"| `{s['display_name']}` | " + " | ".join(cells) + " |")

    lines.extend([
        "",
        (
            f"{H2} 4. Counterfactual Replay on 60 Committed v1.4 Gemini Hard Transcripts "
            f"({cf_meta['n_transcripts_by_source']['opencode']} OpenCode + {cf_meta['n_transcripts_by_source']['inproc']} In-Proc)"
        ),
        "",
        "| Strategy | Surfaced Canaries (Delta) | Horizon Canaries (Delta) | P(true mole) (Drop) | Gemini Opt EV (Drop) | OpenCode EV (Drop) | In-Proc EV (Drop) | CF Regret (Gain vs Default) |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for name in order:
        s = strats[name]
        cf = s["counterfactual"]
        lines.append(
            f"| `{s['display_name']}` | "
            f"{cf['surfaced_canaries']:.2f} ({cf['surfaced_canaries_delta']:+.2f}) | "
            f"{cf['surfaced_canaries_horizon']:.2f} ({cf['surfaced_canaries_horizon_delta']:+.2f}) | "
            f"{cf['p_true_mole']:.3f} ({cf['p_true_mole_drop']:+.3f}) | "
            f"{cf['optimal_ev']:.3f} ({cf['optimal_ev_drop']:+.3f}) | "
            f"{cf['opencode_optimal_ev']:.3f} ({cf['opencode_optimal_ev_drop']:+.3f}) | "
            f"{cf['inproc_optimal_ev']:.3f} ({cf['inproc_optimal_ev_drop']:+.3f}) | "
            f"{cf['counterfactual_regret']:+.3f} ({cf['counterfactual_regret_gain_vs_default']:+.3f}) |"
        )

    lines.extend([
        "",
        f"{H2} 5. Empirical Grounding & Solver Catchability Rationale by Strategy",
        "",
    ])

    for name in non_def:
        spec = STRATEGY_SPECS[name]
        s = strats[name]
        lines.extend([
            f"{H3} `{name}` (`lever={s['lever_id']}`, `cohort={s['target_cohort']}`)",
            f"- **Empirical transcript finding**: {spec.empirical_finding}",
            f"- **Why `SolverPolicy` stays unbeaten**: {spec.solver_catchability_rationale}",
            "",
        ])

    lines.extend([
        f"{H2} 6. Machine-Verified Summary Ledger",
        "",
        LEDGER_START,
        "```json",
        json.dumps(ledger, indent=2, sort_keys=True),
        "```",
        LEDGER_END,
        "",
    ])
    report_text = "\n".join(lines)
    if EM_DASH in report_text or EN_DASH in report_text:
        raise ValueError("rendered markdown contains forbidden dash characters")
    return report_text


def render_report(payload: dict[str, Any]) -> str:
    assert_payload_hygiene_and_invariants(payload, tol=DEFAULT_TOL)
    return render_report_from_ledger(extract_report_ledger(payload))


def _parse_embedded_ledger(md_text: str) -> dict[str, Any]:
    if LEDGER_START not in md_text or LEDGER_END not in md_text:
        raise ValueError("markdown report missing machine-verified ledger markers")
    start_idx = md_text.index(LEDGER_START) + len(LEDGER_START)
    end_idx = md_text.index(LEDGER_END, start_idx)
    block = md_text[start_idx:end_idx].strip()
    if not (block.startswith("```json") and block.endswith("```")):
        raise ValueError("markdown ledger block is not a fenced json block")
    inner = block[len("```json") : -len("```")].strip()
    parsed = json.loads(inner)
    if not isinstance(parsed, dict):
        raise ValueError("parsed markdown ledger is not a JSON object")
    return parsed


def check_report_matches_json(
    json_path: str | Path = DEFAULT_JSON_OUT,
    md_path: str | Path = DEFAULT_MD_OUT,
    tol: float = DEFAULT_TOL,
) -> tuple[bool, str]:
    jp = Path(json_path)
    mp = Path(md_path)
    if not jp.is_file():
        return False, f"missing JSON results file: {jp}"
    if not mp.is_file():
        return False, f"missing Markdown report file: {mp}"

    try:
        payload = json.loads(jp.read_text(encoding="utf-8"))
        md_text = mp.read_text(encoding="utf-8")
        if EM_DASH in md_text or EN_DASH in md_text:
            return False, "markdown report contains forbidden em/en-dash character"
        assert_payload_hygiene_and_invariants(payload, tol=tol)
        expected_ledger = extract_report_ledger(payload)
        embedded_ledger = _parse_embedded_ledger(md_text)
        if not approx_equal(embedded_ledger, expected_ledger, tol=tol):
            return False, f"markdown ledger floats/fields differ from JSON beyond tol={tol:g}"
        rendered_from_embedded = render_report_from_ledger(embedded_ledger)
        if md_text != rendered_from_embedded:
            return False, "markdown prose/tables do not match embedded ledger"
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        return False, f"verification error: {exc}"

    return True, f"OK: {mp} matches {jp} within tol={tol:g}"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/eval_mole_strategies_v14.py")
    ap.add_argument("--check", action="store_true", help="verify markdown report matches JSON within float tolerance")
    ap.add_argument("--tol", type=float, default=DEFAULT_TOL)
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default=DEFAULT_EVAL_SEEDS_SPEC)
    ap.add_argument("--cf-seeds", default=DEFAULT_CF_SEEDS_SPEC)
    ap.add_argument("--strategies", default=None, help="optional comma-separated subset of transcript strategies")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--bootstrap", type=int, default=DEFAULT_BOOT_RESAMPLES)
    ap.add_argument("--boot-seed", type=int, default=DEFAULT_BOOT_SEED)
    ap.add_argument("--json-out", type=Path, default=DEFAULT_JSON_OUT)
    ap.add_argument("--md-out", type=Path, default=DEFAULT_MD_OUT)
    args = ap.parse_args(argv)

    if args.check:
        ok, msg = check_report_matches_json(json_path=args.json_out, md_path=args.md_out, tol=args.tol)
        print(msg)
        return 0 if ok else 1

    strat_subset = (
        [s.strip() for s in args.strategies.split(",") if s.strip()]
        if args.strategies
        else None
    )
    payload = evaluate_mole_strategies_v14(
        tier=args.tier,
        seeds=args.seeds,
        cf_seeds=args.cf_seeds,
        strategy_names=strat_subset,
        workers=args.workers,
        n_boot=args.bootstrap,
        boot_seed=args.boot_seed,
    )
    md_text = render_report(payload)

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.md_out.write_text(md_text, encoding="utf-8")

    ok, msg = check_report_matches_json(json_path=args.json_out, md_path=args.md_out, tol=args.tol)
    if not ok:
        print(msg, file=sys.stderr)
        return 1
    print(f"wrote {args.json_out} and {args.md_out} ({msg})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
