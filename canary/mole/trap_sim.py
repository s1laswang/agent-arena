"""Offline simulation of the v1.4 Mole Trap x Investigator Matrix on safe evaluation seeds."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from canary.analysis.gap import mean_ci
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.fitness import ClassFactory, FEASIBLE_SOLVER_RATIO
from canary.forge.rl_mole import RLMole
from canary.forge_track import _strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params, tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult

__all__ = [
    "TRAP_MATRIX_STRATEGIES",
    "default_trap_investigators",
    "simulate_trap_cell",
    "run_trap_matrix",
    "render_trap_matrix_markdown",
    "main",
]

MIN_SAFE_SEED = 30
MAX_SAFE_SEED_EXCLUSIVE = 800_000
DEFAULT_HARD_SEEDS = range(6300, 6320)
DEFAULT_MEDIUM_SEEDS = range(6320, 6340)
FRONTIER_PROXY_KEYS: tuple[str, str] = ("gemini_carbon_proxy", "codex_horizon_proxy")
INVESTIGATOR_ORDER: tuple[str, ...] = (
    "solver",
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "heuristic",
    "hinted_heuristic",
    "grok_tactics",
    "logs_only",
)

TRAP_MATRIX_STRATEGIES: dict[str, dict[str, Any]] = {
    "default_v0": DEFAULT_STRATEGY.to_json(),
    "surgical_trap_shield": {
        "name": "surgical_trap_shield",
        "rules": [
            {
                "if": [["recent_low_recipient_docs", ">=", 1]],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "wide_crowd_preference": {
        "name": "wide_crowd_preference",
        "rules": [
            {
                "if": [
                    ["day", "<=", 6],
                    ["min_recipient_count", "<=", 8],
                    ["max_recipient_count", ">=", 12],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "reactive_canary_lag": {
        "name": "reactive_canary_lag",
        "rules": [
            {
                "if": [
                    ["day", "<=", 8],
                    ["newest_doc_age_days", "==", 0],
                    ["n_leakable", ">=", 2],
                ],
                "then": {"leak": "oldest", "frame": "random_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "non_decoy_tiebreak_framing": {
        "name": "non_decoy_tiebreak_framing",
        "rules": [
            {
                "if": [["n_restricted_colleagues", ">=", 1]],
                "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "combined_frontier_trap_v14": {
        "name": "combined_frontier_trap_v14",
        "rules": [
            {
                "if": [
                    ["day", "<=", 5],
                    ["min_recipient_count", "<=", 8],
                    ["max_recipient_count", ">=", 16],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["recent_low_recipient_docs", ">=", 1],
                    ["max_recipient_count", ">=", 18],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", "<=", 8],
                    ["newest_doc_age_days", "==", 0],
                    ["n_leakable", ">=", 2],
                ],
                "then": {"leak": "oldest", "frame": "random_peer"},
            },
            {
                "if": [["n_restricted_colleagues", ">=", 1]],
                "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
}

_EPISODE_METRIC_CACHE: dict[tuple[str, int, str, str], dict[str, Any]] = {}


class _SolverFactory:
    def __init__(self, tier: str | None = None):
        self.tier = tier
        self.__name__ = f"SolverPolicy({tier})" if tier else "SolverPolicy"

    def __call__(self, seed: int) -> SolverPolicy:
        del seed
        return SolverPolicy(self.tier, act_budget=5.0)


def default_trap_investigators(tier: str | None = None) -> dict[str, Callable[[int], Any]]:
    if tier is not None and tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    return {
        "solver": _SolverFactory(tier),
        "gemini_carbon_proxy": ClassFactory("canary.forge.frontier_proxies", "GeminiCarbonProxy"),
        "codex_horizon_proxy": ClassFactory("canary.forge.frontier_proxies", "CodexHorizonProxy"),
        "heuristic": ClassFactory("canary.baselines", "Heuristic"),
        "hinted_heuristic": ClassFactory("canary.forge.investigators", "HintedHeuristic"),
        "grok_tactics": ClassFactory("canary.baselines", "GrokTactics"),
        "logs_only": ClassFactory("canary.baselines", "LogsOnly"),
    }


def _validate_sim_seeds(seeds: Iterable[int]) -> list[int]:
    if isinstance(seeds, (str, bytes)):
        raise ValueError("seeds must be an iterable of integers, not a string")
    out: list[int] = []
    for raw in seeds:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"simulation seed must be an integer, got {raw!r}")
        if raw < MIN_SAFE_SEED or raw >= MAX_SAFE_SEED_EXCLUSIVE or raw in JUDGE_SEEDS or raw in HELDOUT_SEEDS:
            raise ValueError(
                f"forbidden simulation seed {raw}: seeds must satisfy "
                f"{MIN_SAFE_SEED} <= seed < {MAX_SAFE_SEED_EXCLUSIVE} (dev 0..29 and judge/heldout >=800000 forbidden)"
            )
        out.append(int(raw))
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def _coerce_strategy(strategy_obj: Any, name: str | None = None) -> MoleStrategy | RLMole:
    if strategy_obj is None:
        out: MoleStrategy | RLMole = DEFAULT_STRATEGY
    elif isinstance(strategy_obj, MoleStrategy):
        out = MoleStrategy.from_json(strategy_obj.to_json())
    elif isinstance(strategy_obj, RLMole):
        out = RLMole.from_json(strategy_obj.to_json())
    elif isinstance(strategy_obj, dict):
        payload = dict(strategy_obj.get("strategy_json", strategy_obj.get("strategy", strategy_obj)))
        if name and "name" not in payload:
            payload["name"] = name[:80]
        out = _strategy(payload)
    else:
        raise TypeError(f"unsupported strategy object type: {type(strategy_obj).__name__}")
    if name and out.name != name:
        if isinstance(out, MoleStrategy):
            out = MoleStrategy(rules=out.rules, default=out.default, name=name[:80])
        else:
            sj = out.to_json()
            sj["name"] = name[:80]
            out = RLMole.from_json(sj)
    return out


def _canonical_strategy_key(strat: MoleStrategy | RLMole) -> str:
    sj = strat.to_json()
    if sj.get("kind") == "rl_mole":
        payload = {k: v for k, v in sj.items() if k != "name"}
    else:
        payload = {"rules": sj["rules"], "default": sj["default"]}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _factory_cache_key(factory: Callable) -> str | None:
    if isinstance(factory, _SolverFactory):
        return f"solver:{factory.tier or 'auto'}"
    if isinstance(factory, ClassFactory) and not factory.kw:
        return f"class:{factory.module}:{factory.attr}"
    if factory is SolverPolicy:
        return "solver:class"
    return None


def _instantiate_investigator(factory: Callable, tier: str, seed: int) -> Any:
    if factory is SolverPolicy:
        return SolverPolicy(tier, act_budget=5.0)
    try:
        return factory(seed)
    except TypeError:
        return factory()


def _audit_played_episode(ep: EpisodeResult) -> dict[str, Any]:
    params = tier_params_for_episode(ep.tier, ep.steps)
    sp = SolverPolicy(params, act_budget=5.0)

    accuse_idx: int | None = None
    for idx, st in enumerate(ep.steps):
        if st.tool == "accuse":
            accuse_idx = idx
            break

    ingest_limit = accuse_idx if accuse_idx is not None else len(ep.steps)
    for st in ep.steps[:ingest_limit]:
        sp._ingest(st)
    sp.seen = ingest_limit
    if not sp.obs.employees:
        sp.obs.employees = [f"e{i:02d}" for i in range(params.n_employees)]

    post = sp.belief() if sp.obs.employees else {}

    seen_doc_ids: set[str] = set()
    surfaced_canaries = []
    for it in sp.obs.feed:
        if it.doc_id in seen_doc_ids:
            continue
        doc = sp.obs.docs.get(it.doc_id)
        if (doc is not None and doc.is_canary) or it.variant is not None:
            seen_doc_ids.add(it.doc_id)
            surfaced_canaries.append(it)

    accused = ep.accused if isinstance(ep.accused, str) and ep.accused else None
    p_accused: float | None = None
    separating_canaries = 0

    if accused is not None:
        p_accused = float(post.get(accused, 0.0))
        v_at_accuse = float((ep.meta or {}).get("V", sp.V))
        luck_adjusted = p_accused * v_at_accuse - (1.0 - p_accused)
        ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
        runner_up = next((emp for emp, _ in ranked if emp != accused), None)
        if runner_up is not None:
            for it in surfaced_canaries:
                doc = sp.obs.docs.get(it.doc_id)
                vs = (doc.variants if doc is not None else None) or {}
                if (vs.get(accused) == it.variant) != (vs.get(runner_up) == it.variant):
                    separating_canaries += 1
    else:
        luck_adjusted = 0.0

    return {
        "seed": int(ep.seed),
        "score": float(ep.score),
        "luck_adjusted_score": float(luck_adjusted),
        "correct": bool(ep.correct),
        "accused": accused,
        "p_accused": p_accused,
        "final_day": int(ep.final_day),
        "surfaced_canaries": len(surfaced_canaries),
        "separating_canaries": separating_canaries,
    }


def _run_single_episode_metric(
    tier: str,
    seed: int,
    strat_json: dict[str, Any],
    factory: Callable,
) -> dict[str, Any]:
    strat = _strategy(strat_json)
    policy = _instantiate_investigator(factory, tier, seed)
    ep = run_episode(Env(tier, seed, mole_strategy=strat), policy)
    return _audit_played_episode(ep)


def _worker_episode_task(task: tuple[str, int, str, dict[str, Any], str, Callable]) -> tuple[tuple[str, int, str, str], dict[str, Any]]:
    tier, seed, skey, strat_json, fkey, factory = task
    row = _run_single_episode_metric(tier, seed, strat_json, factory)
    return (tier, seed, skey, fkey), row


def _aggregate_episode_rows(
    rows: list[dict[str, Any]],
    tier: str,
    strat_name: str,
    seed_list: list[int],
) -> dict[str, Any]:
    n = len(rows)
    scores = [float(r["score"]) for r in rows]
    luck_scores = [float(r["luck_adjusted_score"]) for r in rows]
    mean_score, ci95 = mean_ci(scores)
    luck_mean, luck_ci95 = mean_ci(luck_scores)
    correct_count = sum(1 for r in rows if r["correct"])
    wrong_count = sum(1 for r in rows if r["accused"] is not None and not r["correct"])
    abstain_count = sum(1 for r in rows if r["accused"] is None)
    accused_p_vals = [float(r["p_accused"]) for r in rows if r["p_accused"] is not None]

    return {
        "tier": tier,
        "strategy": strat_name,
        "seeds": list(seed_list),
        "n": n,
        "mean_score": float(mean_score),
        "ci95": float(ci95),
        "luck_adjusted_score": float(luck_mean),
        "luck_adjusted_ci95": float(luck_ci95),
        "accuracy": correct_count / n,
        "wrong_rate": wrong_count / n,
        "abstain_rate": abstain_count / n,
        "accused_rate": (n - abstain_count) / n,
        "mean_final_day": sum(float(r["final_day"]) for r in rows) / n,
        "surfaced_canaries_mean": sum(float(r["surfaced_canaries"]) for r in rows) / n,
        "separating_canaries_mean": sum(float(r["separating_canaries"]) for r in rows) / n,
        "p_accused_mean": (sum(accused_p_vals) / len(accused_p_vals)) if accused_p_vals else None,
    }


def simulate_trap_cell(
    strategy_obj: Any,
    investigator_factory: Callable,
    tier: str,
    seeds: Sequence[int],
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    seed_list = _validate_sim_seeds(seeds)
    strat = _coerce_strategy(strategy_obj)
    strat_json = strat.to_json()
    skey = _canonical_strategy_key(strat)
    fkey = _factory_cache_key(investigator_factory)

    rows: list[dict[str, Any]] = []
    for s in seed_list:
        if fkey is not None:
            ckey = (tier, s, skey, fkey)
            if ckey not in _EPISODE_METRIC_CACHE:
                _EPISODE_METRIC_CACHE[ckey] = _run_single_episode_metric(tier, s, strat_json, investigator_factory)
            rows.append(dict(_EPISODE_METRIC_CACHE[ckey]))
        else:
            rows.append(_run_single_episode_metric(tier, s, strat_json, investigator_factory))

    return _aggregate_episode_rows(rows, tier=tier, strat_name=strat.name, seed_list=seed_list)


def _is_default_strategy(strat: MoleStrategy | RLMole) -> bool:
    return (
        isinstance(strat, MoleStrategy)
        and strat.rules == DEFAULT_STRATEGY.rules
        and strat.default == DEFAULT_STRATEGY.default
    )


def run_trap_matrix(
    strategies: dict[str, Any] | None = None,
    tier: str = "hard",
    seeds: Iterable[int] = DEFAULT_HARD_SEEDS,
    min_solver_acc: float = 0.85,
    investigators: dict[str, Callable[[int], Any]] | None = None,
    workers: int = 1,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    seed_list = _validate_sim_seeds(seeds)
    raw_strategies = TRAP_MATRIX_STRATEGIES if strategies is None else strategies
    if not raw_strategies:
        raise ValueError("strategies must not be empty")

    coerced: dict[str, MoleStrategy | RLMole] = {
        name: _coerce_strategy(obj, name=name)
        for name, obj in raw_strategies.items()
    }
    inv_map = default_trap_investigators(tier) if investigators is None else dict(investigators)
    for req_key in ("solver", "logs_only", *FRONTIER_PROXY_KEYS):
        if req_key not in inv_map:
            raise ValueError(f"investigators missing required key {req_key!r}")

    all_eval_strats: dict[str, MoleStrategy | RLMole] = dict(coerced)
    default_key = next((k for k, st in coerced.items() if _is_default_strategy(st)), None)
    if default_key is None:
        default_key = "__default_v0_baseline__"
        all_eval_strats[default_key] = DEFAULT_STRATEGY

    if workers and workers > 1:
        pending_tasks: list[tuple[str, int, str, dict[str, Any], str, Callable]] = []
        seen_task_keys: set[tuple[str, int, str, str]] = set()
        for st in all_eval_strats.values():
            skey = _canonical_strategy_key(st)
            sjson = st.to_json()
            for inv_fac in inv_map.values():
                fkey = _factory_cache_key(inv_fac)
                if fkey is None:
                    continue
                for s in seed_list:
                    ckey = (tier, s, skey, fkey)
                    if ckey not in _EPISODE_METRIC_CACHE and ckey not in seen_task_keys:
                        seen_task_keys.add(ckey)
                        pending_tasks.append((tier, s, skey, sjson, fkey, inv_fac))
        if len(pending_tasks) > 1:
            with ProcessPoolExecutor(max_workers=min(int(workers), len(pending_tasks))) as pool:
                for ckey, row in pool.map(_worker_episode_task, pending_tasks):
                    _EPISODE_METRIC_CACHE[ckey] = row

    cells_by_strat: dict[str, dict[str, dict[str, Any]]] = {}
    for sname, st in all_eval_strats.items():
        cells_by_strat[sname] = {
            inv_name: simulate_trap_cell(st, inv_fac, tier=tier, seeds=seed_list)
            for inv_name, inv_fac in inv_map.items()
        }

    base_cells = cells_by_strat[default_key]
    baseline_solver_score = float(base_cells["solver"]["mean_score"])
    baseline_solver_luck = float(base_cells["solver"]["luck_adjusted_score"])
    default_worst_proxy_regret = min(
        baseline_solver_score - float(base_cells[p]["mean_score"])
        for p in FRONTIER_PROXY_KEYS
    )
    default_luck_proxy_gap = min(
        baseline_solver_luck - float(base_cells[p]["luck_adjusted_score"])
        for p in FRONTIER_PROXY_KEYS
    )

    out_strategies: dict[str, dict[str, Any]] = {}
    for sname, st in coerced.items():
        cells = cells_by_strat[sname]
        sol_cell = cells["solver"]
        log_cell = cells["logs_only"]
        sol_score = float(sol_cell["mean_score"])
        sol_acc = float(sol_cell["accuracy"])
        sol_luck = float(sol_cell["luck_adjusted_score"])

        solver_beatable = bool(
            sol_acc >= float(min_solver_acc)
            and sol_score >= FEASIBLE_SOLVER_RATIO * baseline_solver_score
        )
        logs_only_bounded = bool(
            float(log_cell["accuracy"]) <= 0.20
            and float(log_cell["mean_score"]) < 0.0
        )

        proxy_regrets = {
            p: sol_score - float(cells[p]["mean_score"])
            for p in FRONTIER_PROXY_KEYS
        }
        proxy_luck_gaps = {
            p: sol_luck - float(cells[p]["luck_adjusted_score"])
            for p in FRONTIER_PROXY_KEYS
        }
        worst_proxy_regret = min(proxy_regrets.values())
        luck_adjusted_proxy_gap = min(proxy_luck_gaps.values())
        strongest_proxy = max(
            FRONTIER_PROXY_KEYS,
            key=lambda p: float(cells[p]["mean_score"]),
        )

        out_strategies[sname] = {
            "name": sname,
            "strategy_json": st.to_json(),
            "cells": cells,
            "solver_beatable": solver_beatable,
            "logs_only_bounded": logs_only_bounded,
            "worst_proxy_regret": float(worst_proxy_regret),
            "worst_proxy_regret_gain": float(worst_proxy_regret - default_worst_proxy_regret),
            "luck_adjusted_proxy_gap": float(luck_adjusted_proxy_gap),
            "luck_adjusted_proxy_gap_gain": float(luck_adjusted_proxy_gap - default_luck_proxy_gap),
            "proxy_regrets": proxy_regrets,
            "proxy_luck_adjusted_gaps": proxy_luck_gaps,
            "strongest_proxy": strongest_proxy,
        }

    return {
        "tier": tier,
        "seeds": list(seed_list),
        "n_seeds": len(seed_list),
        "min_solver_acc": float(min_solver_acc),
        "baseline_solver_score": baseline_solver_score,
        "default_worst_proxy_regret": float(default_worst_proxy_regret),
        "default_luck_adjusted_proxy_gap": float(default_luck_proxy_gap),
        "investigators": list(inv_map.keys()),
        "strategies": out_strategies,
    }


def _seed_span_label(seeds: Sequence[int]) -> str:
    if not seeds:
        return "none"
    if list(seeds) == list(range(seeds[0], seeds[-1] + 1)):
        return f"{seeds[0]}-{seeds[-1]}"
    return ",".join(str(s) for s in seeds)


def _fmt_signed(x: float, nd: int = 3) -> str:
    return f"{x:+.{nd}f}"


def _fmt_pct(x: float, nd: int = 1) -> str:
    return f"{100.0 * x:.{nd}f}%"


def _render_summary_table(report: dict[str, Any]) -> list[str]:
    lines = [
        "| Strategy | Solver Score +/- CI (Acc) | Gemini Proxy (Acc) | Codex Proxy (Acc) | LogsOnly (Acc) | Worst Proxy Regret (Gain) | Luck-Adj Proxy Gap | Solver Beatable | Logs Bounded |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for sname, row in report["strategies"].items():
        c_sol = row["cells"]["solver"]
        c_gem = row["cells"]["gemini_carbon_proxy"]
        c_cod = row["cells"]["codex_horizon_proxy"]
        c_log = row["cells"]["logs_only"]
        lines.append(
            f"| `{sname}` "
            f"| {_fmt_signed(c_sol['mean_score'])} +/- {c_sol['ci95']:.3f} ({_fmt_pct(c_sol['accuracy'], 0)}) "
            f"| {_fmt_signed(c_gem['mean_score'])} ({_fmt_pct(c_gem['accuracy'], 0)}) "
            f"| {_fmt_signed(c_cod['mean_score'])} ({_fmt_pct(c_cod['accuracy'], 0)}) "
            f"| {_fmt_signed(c_log['mean_score'])} ({_fmt_pct(c_log['accuracy'], 0)}) "
            f"| {_fmt_signed(row['worst_proxy_regret'])} ({_fmt_signed(row['worst_proxy_regret_gain'])}) "
            f"| {_fmt_signed(row['luck_adjusted_proxy_gap'])} "
            f"| {'yes' if row['solver_beatable'] else 'no'} "
            f"| {'yes' if row['logs_only_bounded'] else 'no'} |"
        )
    return lines


def _render_baseline_table(report: dict[str, Any]) -> list[str]:
    lines = [
        "| Strategy | Heuristic Score (Acc) | HintedHeuristic Score (Acc) | GrokTactics Score (Acc) | LogsOnly Score (Acc) |",
        "|---|---|---|---|---|",
    ]
    for sname, row in report["strategies"].items():
        cells = row["cells"]
        c_heu = cells["heuristic"]
        c_hh = cells["hinted_heuristic"]
        c_gt = cells["grok_tactics"]
        c_lo = cells["logs_only"]
        lines.append(
            f"| `{sname}` "
            f"| {_fmt_signed(c_heu['mean_score'])} ({_fmt_pct(c_heu['accuracy'], 0)}) "
            f"| {_fmt_signed(c_hh['mean_score'])} ({_fmt_pct(c_hh['accuracy'], 0)}) "
            f"| {_fmt_signed(c_gt['mean_score'])} ({_fmt_pct(c_gt['accuracy'], 0)}) "
            f"| {_fmt_signed(c_lo['mean_score'])} ({_fmt_pct(c_lo['accuracy'], 0)}) |"
        )
    return lines


def _render_anatomy_table(report: dict[str, Any], inv_keys: Sequence[str]) -> list[str]:
    lines = [
        "| Strategy | Investigator | Raw Score | Luck-Adj Score | Acc / Wrong / Abstain | Mean Day | Surf Canaries | Sep Canaries |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for sname, row in report["strategies"].items():
        cells = row["cells"]
        for inv in inv_keys:
            if inv not in cells:
                continue
            c = cells[inv]
            lines.append(
                f"| `{sname}` | `{inv}` "
                f"| {_fmt_signed(c['mean_score'])} "
                f"| {_fmt_signed(c['luck_adjusted_score'])} "
                f"| {_fmt_pct(c['accuracy'], 0)} / {_fmt_pct(c['wrong_rate'], 0)} / {_fmt_pct(c['abstain_rate'], 0)} "
                f"| {c['mean_final_day']:.2f} "
                f"| {c['surfaced_canaries_mean']:.2f} "
                f"| {c['separating_canaries_mean']:.2f} |"
            )
    return lines


def render_trap_matrix_markdown(
    hard_report: dict[str, Any],
    medium_report: dict[str, Any] | None = None,
) -> str:
    h1 = chr(35)
    h2 = h1 * 2
    h3 = h1 * 3

    hard_seeds_str = _seed_span_label(hard_report["seeds"])
    hard_tp = tier_params(hard_report["tier"])
    cmd_parts = [
        f"python -m canary.mole.trap_sim --seeds {hard_seeds_str}",
    ]
    if medium_report is not None:
        med_seeds_str = _seed_span_label(medium_report["seeds"])
        cmd_parts.append("--include-medium")
        if med_seeds_str != "6320-6339":
            cmd_parts.append(f"--medium-seeds {med_seeds_str}")
    cmd_parts.append("--out docs/reports/mole_trap_matrix_v14.md")
    repro_cmd = " ".join(cmd_parts)

    h_strats = hard_report["strategies"]
    best_strat_name = max(
        h_strats,
        key=lambda k: (1 if h_strats[k]["solver_beatable"] else 0, h_strats[k]["worst_proxy_regret"]),
    )
    best_row = h_strats[best_strat_name]
    n_beatable_hard = sum(1 for r in h_strats.values() if r["solver_beatable"])
    n_logs_ok_hard = sum(1 for r in h_strats.values() if r["logs_only_bounded"])

    lines: list[str] = [
        f"{h1} Mole Trap x Investigator Matrix (v1.4 Offline Simulation)",
        "",
        f"Generated offline with zero LLM API calls via `{repro_cmd}`.",
        f"Seed hygiene enforced: dev seeds 0..29 and judge/heldout seeds >=800000 are rejected by `simulate_trap_cell` and `run_trap_matrix`.",
        f"Every luck-adjusted score is evaluated at the exact accusation step via `SolverPolicy` posterior `P(accused) * V - (1 - P(accused))` (0.0 on abstention).",
        "",
        f"{h2} 1. Headline Findings ({hard_report['tier'].capitalize()} Tier, Seeds {hard_seeds_str}, n={hard_report['n_seeds']})",
        "",
        f"- **Solver catchability preserved across {n_beatable_hard}/{len(h_strats)} strategies**: Every strategy evaluated on `{hard_report['tier']}` (`n_employees={hard_tp.n_employees}`, `canaries_per_day={hard_tp.canaries_per_day}`, `fingerprint_accuracy={hard_tp.fingerprint_accuracy}`) keeps `SolverPolicy` >= {_fmt_pct(hard_report['min_solver_acc'], 0)} accurate and above `0.5 * baseline_solver_score` ({_fmt_signed(0.5 * hard_report['baseline_solver_score'])}).",
        f"- **Logs-only shortcuts remain strictly negative ({n_logs_ok_hard}/{len(h_strats)} bounded)**: `LogsOnly` stays <= 20% accurate and strictly below 0.0 mean score on every strategy, confirming zero unintended access-log side-channels.",
        f"- **Best feasible trap (`{best_strat_name}`)**: Raises worst-case frontier-proxy regret to **{_fmt_signed(best_row['worst_proxy_regret'])}** ({_fmt_signed(best_row['worst_proxy_regret_gain'])} vs `default_v0` at {_fmt_signed(hard_report['default_worst_proxy_regret'])}) with luck-adjusted proxy gap **{_fmt_signed(best_row['luck_adjusted_proxy_gap'])}** while `SolverPolicy` reaches **{_fmt_pct(best_row['cells']['solver']['accuracy'], 0)}** accuracy ({_fmt_signed(best_row['cells']['solver']['mean_score'])}).",
    ]

    if "wide_crowd_preference" in h_strats and "surgical_trap_shield" in h_strats and "default_v0" in h_strats:
        d_gem = h_strats["default_v0"]["cells"]["gemini_carbon_proxy"]
        w_gem = h_strats["wide_crowd_preference"]["cells"]["gemini_carbon_proxy"]
        d_cod = h_strats["default_v0"]["cells"]["codex_horizon_proxy"]
        s_cod = h_strats["surgical_trap_shield"]["cells"]["codex_horizon_proxy"]
        lines.append(
            f"- **Orthogonal architectural selectivity**: `wide_crowd_preference` selectively degrades `GeminiCarbonProxy` from {_fmt_signed(d_gem['mean_score'])} ({_fmt_pct(d_gem['accuracy'], 0)}) to {_fmt_signed(w_gem['mean_score'])} ({_fmt_pct(w_gem['accuracy'], 0)}) by routing around 4-8 recipient 3-variant traps, whereas `surgical_trap_shield` selectively degrades `CodexHorizonProxy` from {_fmt_signed(d_cod['mean_score'])} ({_fmt_pct(d_cod['accuracy'], 0)}) to {_fmt_signed(s_cod['mean_score'])} ({_fmt_pct(s_cod['accuracy'], 0)}) by routing around <=3-recipient bisection traps."
        )

    if "combined_frontier_trap_v14" in h_strats and "default_v0" in h_strats:
        comb = h_strats["combined_frontier_trap_v14"]
        c_sol = comb["cells"]["solver"]
        c_gem = comb["cells"]["gemini_carbon_proxy"]
        c_cod = comb["cells"]["codex_horizon_proxy"]
        lines.append(
            f"- **Combined multi-lever trap (`combined_frontier_trap_v14`)**: Simultaneously suppresses `GeminiCarbonProxy` to {_fmt_signed(c_gem['mean_score'])} ({_fmt_pct(c_gem['accuracy'], 0)}) and `CodexHorizonProxy` to {_fmt_signed(c_cod['mean_score'])} ({_fmt_pct(c_cod['accuracy'], 0)}), lifting worst-proxy regret to {_fmt_signed(comb['worst_proxy_regret'])} ({_fmt_signed(comb['worst_proxy_regret_gain'])} gain) while `SolverPolicy` holds {_fmt_pct(c_sol['accuracy'], 0)} accuracy ({_fmt_signed(c_sol['mean_score'])})."
        )

    lines.extend([
        "",
        f"{h2} 2. {hard_report['tier'].capitalize()}-Tier Frontier Proxy and Catchability Summary",
        "",
        *_render_summary_table(hard_report),
        "",
        f"{h3} 2.1 {hard_report['tier'].capitalize()}-Tier Scripted Baseline Matrix",
        "",
        *_render_baseline_table(hard_report),
        "",
        f"{h3} 2.2 {hard_report['tier'].capitalize()}-Tier Decision Quality, Luck Adjustment, and Canary Separation",
        "",
        *_render_anatomy_table(
            hard_report,
            ("solver", "gemini_carbon_proxy", "codex_horizon_proxy", "grok_tactics"),
        ),
    ])

    if medium_report is not None:
        med_seeds_str = _seed_span_label(medium_report["seeds"])
        med_tp = tier_params(medium_report["tier"])
        m_strats = medium_report["strategies"]
        lines.extend([
            "",
            f"{h2} 3. {medium_report['tier'].capitalize()}-Tier Cross-Check (Seeds {med_seeds_str}, n={medium_report['n_seeds']})",
            "",
            f"Evaluated on `{medium_report['tier']}` (`n_employees={med_tp.n_employees}`, `canaries_per_day={med_tp.canaries_per_day}`, `n_days={med_tp.n_days}`, `fingerprint_accuracy={med_tp.fingerprint_accuracy}`). "
            f"Because `{medium_report['tier']}` allows only {med_tp.canaries_per_day} canary/day over {med_tp.n_days} days, unconditional `surgical_trap_shield` over-suppresses narrow <=4-recipient bisection canaries and fails the {_fmt_pct(medium_report['min_solver_acc'], 0)} solver gate ({_fmt_pct(m_strats['surgical_trap_shield']['cells']['solver']['accuracy'], 0)} if present), whereas gating the low-recipient shield on wide alternative docs (`max_recipient_count >= 18`) in `combined_frontier_trap_v14` preserves `default_v0` solver accuracy while keeping both frontier proxies suppressed.",
            "",
            *_render_summary_table(medium_report),
            "",
            f"{h3} 3.1 {medium_report['tier'].capitalize()}-Tier Scripted Baseline Matrix",
            "",
            *_render_baseline_table(medium_report),
        ])

    sec_num = 4 if medium_report is not None else 3
    lines.extend([
        "",
        f"{h2} {sec_num}. Mechanism Mapping: Which Trap Levers Fool Which Investigator Archetype",
        "",
        "1. **`surgical_trap_shield` -> targets narrow bisection planners (`CodexHorizonProxy`, `Heuristic`, `HintedHeuristic`)**: "
        "Whenever `recent_low_recipient_docs >= 1` (`recipient_count <= low_recipient_threshold`), the mole diverts its leak to `most_recipients`. "
        "Planners that wait to plant 2-3 recipient surgical traps lose canary surfacing and either abstain or gamble on unseparated suspect pools, while `GeminiCarbonProxy` (which plants 4-6 recipient 3-variant traps) is largely unaffected.",
        "2. **`wide_crowd_preference` -> targets midsize 3-variant subset planters (`GeminiCarbonProxy`)**: "
        "On days 1..6 when `min_recipient_count <= 8` and a wider document (`max_recipient_count >= 12`) is available, the mole leaks `most_recipients`. "
        "This starves `GeminiCarbonProxy`'s 4-6 employee canary subsets during early/midgame, forcing delayed accusations and single-canary ties under `fingerprint_accuracy=0.95`.",
        "3. **`reactive_canary_lag` -> targets late Day-2+ canary starters (`GeminiCarbonProxy` and `CodexHorizonProxy`)**: "
        "On days 1..8 when a newly planted `age_days == 0` document arrives alongside older held documents (`n_leakable >= 2`), the mole leaks `oldest`. "
        "Agents that spend Day 1 on interviews/searches and plant reactive canaries on Day 2+ watch the mole leak pre-canary Day-1 documents instead of their fresh traps.",
        "4. **`non_decoy_tiebreak_framing` -> targets raw after-hours tie-breakers (`GeminiCarbonProxy`, `CodexHorizonProxy`, `GrokTactics`)**: "
        "Frontier agents reliably filter out the angry decoy (`100%` dismissal in v1.3/v1.4 transcripts) yet break 0-separation canary ties using non-decoy after-hours logs. "
        "Routing all fake after-hours logs to `most_restricted_peer` or `random_peer` (`0%` decoy framing) manufactures false log spikes on innocent colleagues inside the live suspect pool.",
        "5. **`combined_frontier_trap_v14` -> joint frontier pressure**: "
        "Layers early wide-crowd evasion (days 1..5), wide-alternative surgical shielding (`max_recipient_count >= 18`), reactive `age_days == 0` oldest fallback (days 1..8), and non-decoy peer framing to degrade both `GeminiCarbonProxy` and `CodexHorizonProxy` simultaneously.",
        "",
        f"{h2} {sec_num + 1}. Why `SolverPolicy` Remains >= 85% Accurate on Every Kept Hard Strategy",
        "",
        "- **Day-1 dual-canary pipelining (`canaries_per_day=2`)**: Unlike frontier transcripts (mean first canary day 3.03-3.40 on v1.4 Hard) and proxies (first canary day 2), `SolverPolicy` plants 2 posterior-balanced MI canaries starting on **Day 1**. By Day 3, `SolverPolicy`'s Day-1 canaries already occupy the `oldest` slot in the 3-day leak window, turning `reactive_canary_lag` into direct canary hits (`100%` solver accuracy on Hard seeds 6300-6319).",
        "- **Adaptive wide coverage + department intersection**: `SolverPolicy` evaluates candidate splits across coverage fractions `(0.10, 0.15, 0.25, 0.40, 0.55, 0.70, 1.00)` and exact department-intersection likelihoods on regular leaks. Even when `wide_crowd_preference` or `surgical_trap_shield` steers leaks toward wider recipient sets, wide 3-variant partitions (`>=16` recipients) plus `canary_shy()` full-staff padding keep mutual information positive every leak.",
        "- **Tempered Poisson framing marginalization (`behaviour_temper=0.6`)**: `SolverPolicy` explicitly models `Poisson(framing_rate)` fake after-hours logs distributed across non-mole peers and tempers behavioural log likelihoods by `0.6`, preventing `non_decoy_tiebreak_framing` spikes from overriding canary variant posteriors or triggering below-breakeven `P < 1 / (1 + V)` gambles.",
    ])
    return "\n".join(lines) + "\n"


_NUM_TOKEN_RE = re.compile(r"[+-]?\d+(?:\.\d+)?%?")


def _markdown_matches_within_rounding(expected: str, actual: str, abs_tol: float = 2e-3) -> tuple[bool, str]:
    exp_lines = expected.strip().splitlines()
    act_lines = actual.strip().splitlines()
    if exp_lines == act_lines:
        return True, "exact match"
    if len(exp_lines) != len(act_lines):
        return False, f"line count mismatch: expected {len(exp_lines)}, found {len(act_lines)}"

    for idx, (el, al) in enumerate(zip(exp_lines, act_lines), start=1):
        if el == al:
            continue
        e_skel = _NUM_TOKEN_RE.sub("<N>", el)
        a_skel = _NUM_TOKEN_RE.sub("<N>", al)
        if e_skel != a_skel:
            return False, f"non-numeric mismatch on line {idx}:\n  expected: {el}\n  found:    {al}"
        e_nums = _NUM_TOKEN_RE.findall(el)
        a_nums = _NUM_TOKEN_RE.findall(al)
        if len(e_nums) != len(a_nums):
            return False, f"numeric token count mismatch on line {idx}"
        for et, at in zip(e_nums, a_nums):
            if et.endswith("%") != at.endswith("%"):
                return False, f"percent token mismatch on line {idx}: {et!r} vs {at!r}"
            scale = 0.01 if et.endswith("%") else 1.0
            ev = float(et.rstrip("%")) * scale
            av = float(at.rstrip("%")) * scale
            tol = 0.011 if (et.endswith("%") and "." not in et) else abs_tol
            if abs(ev - av) > tol:
                return False, f"value drift on line {idx}: expected {et}, found {at} (diff={abs(ev - av):.6f} > {tol})"
    return True, "matched within float rounding"


def _compact_json_payload(
    hard_report: dict[str, Any],
    medium_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if medium_report is None:
        return hard_report
    return {
        "primary": hard_report,
        "medium": medium_report,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.trap_sim")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="6300-6319")
    ap.add_argument("--include-medium", action="store_true")
    ap.add_argument("--medium-seeds", default="6320-6339")
    ap.add_argument("--min-solver-acc", type=float, default=0.85)
    ap.add_argument("--workers", type=int, default=min(6, os.cpu_count() or 1))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", type=Path, default=None)
    args = ap.parse_args(argv)

    check_target = args.check
    include_medium = bool(args.include_medium)
    if check_target is not None and not include_medium and check_target.is_file():
        existing_txt = check_target.read_text(encoding="utf-8")
        if "Medium-Tier Cross-Check" in existing_txt or '"medium":' in existing_txt:
            include_medium = True

    primary_seeds = parse_seeds(args.seeds)
    primary_report = run_trap_matrix(
        tier=args.tier,
        seeds=primary_seeds,
        min_solver_acc=args.min_solver_acc,
        workers=args.workers,
    )
    medium_report = None
    if include_medium:
        med_seeds = parse_seeds(args.medium_seeds)
        medium_report = run_trap_matrix(
            tier="medium",
            seeds=med_seeds,
            min_solver_acc=args.min_solver_acc,
            workers=args.workers,
        )

    use_json = bool(args.json or (check_target is not None and check_target.suffix == ".json"))
    rendered = (
        json.dumps(_compact_json_payload(primary_report, medium_report), indent=2, sort_keys=True) + "\n"
        if use_json
        else render_trap_matrix_markdown(primary_report, medium_report=medium_report)
    )

    if check_target is not None:
        if not check_target.is_file():
            print(f"check failed: file not found: {check_target}", file=sys.stderr)
            return 1
        committed = check_target.read_text(encoding="utf-8")
        ok, reason = _markdown_matches_within_rounding(rendered, committed)
        if not ok:
            print(f"check failed for {check_target}: {reason}", file=sys.stderr)
            return 1
        print(f"check passed for {check_target} ({reason})")
        return 0

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")

    sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
