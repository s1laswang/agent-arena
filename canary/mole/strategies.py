"""Empirical transcript-grounded Mole DSL strategies and fast catchability/fairness slice verifier."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Iterable, Sequence

from canary.baselines import AccuseMostLogs, Heuristic, LogsOnly
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import (
    FORBIDDEN_LOW_SEED_MAX,
    RESERVED_HELDOUT_EVAL_SEEDS,
    behavior_hash,
    is_valid_rule_conds,
)
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params
from canary.solver.policy import SolverPolicy

__all__ = [
    "DEFAULT_DEV_SEEDS",
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "STRATEGIES",
    "STRATEGY_JSONS",
    "STRATEGY_SPECS",
    "StrategySpec",
    "TRANSCRIPT_STRATEGIES",
    "all_strategies",
    "all_strategy_jsons",
    "export_hof_rows",
    "get_strategy",
    "get_strategy_json",
    "get_strategy_spec",
    "list_strategy_names",
    "main",
    "verify_all_strategies",
    "verify_strategy_slice",
    "write_hof_jsonl",
]

DEFAULT_DEV_SEEDS = range(6000, 6010)
DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_MIN_SOLVER_RATIO = 0.50

_SOLVER_BASELINE_CACHE: dict[tuple[str, tuple[int, ...]], dict[str, float]] = {}


@dataclass(frozen=True)
class StrategySpec:
    name: str
    lever_id: str
    target_cohort: str
    empirical_finding: str
    solver_catchability_rationale: str
    empirical_anchors: dict[str, float | int]
    strategy_json: dict[str, Any]

    def to_strategy(self) -> MoleStrategy:
        return MoleStrategy.from_json(self.strategy_json)

    def to_json(self) -> dict[str, Any]:
        return copy.deepcopy(self.strategy_json)

    def to_hof_row(self, rank: int = 1) -> dict[str, Any]:
        return {
            "rank": int(rank),
            "name": self.name,
            "lever_id": self.lever_id,
            "target_cohort": self.target_cohort,
            "behavior_hash": behavior_hash(self.strategy_json, "hard"),
            "empirical_anchors": dict(self.empirical_anchors),
            "strategy_json": copy.deepcopy(self.strategy_json),
        }


def _build_specs() -> dict[str, StrategySpec]:
    items = (
        StrategySpec(
            name="surgical_trap_shield",
            lever_id="low_recipient_surgical_shield",
            target_cohort="codex_gpt55",
            empirical_finding=(
                "Codex and GPT-5.5 place 30.6% to 75.3% of planted canaries into <=3-recipient surgical "
                "traps while dismissing the angry decoy in 100.0% of 159 frontier episodes."
            ),
            solver_catchability_rationale=(
                "Early surgical-trap deflection ends after day 7 and defaults to random_seeded, allowing "
                "SolverPolicy wide balanced partitions and mid-to-late game canaries to isolate the mole."
            ),
            empirical_anchors={
                "codex_medium_le3_share": 0.753,
                "codex_hard_le3_share": 0.306,
                "gpt55_medium_le3_share": 0.734,
                "gpt55_hard_le3_share": 0.435,
                "frontier_decoy_dismissal_rate": 1.0,
            },
            strategy_json={
                "name": "surgical_trap_shield",
                "rules": [
                    {
                        "if": [
                            ["day", "<=", 7],
                            ["recent_low_recipient_docs", ">=", 2],
                            ["n_restricted_colleagues", ">=", 1],
                        ],
                        "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
                    },
                    {
                        "if": [
                            ["day", "<=", 7],
                            ["recent_low_recipient_docs", ">=", 2],
                        ],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [["n_restricted_colleagues", ">=", 1]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
        StrategySpec(
            name="gemini_midsize_shield",
            lever_id="midsize_canary_evasion",
            target_cohort="gemini_4_carbon",
            empirical_finding=(
                "Gemini-4-carbon places 0.0% to 0.6% of canaries in <=3 recipients and concentrates "
                "43.6% to 73.6% of canaries in 4-8 recipient 3-variant cells, failing on 0-hit seeds."
            ),
            solver_catchability_rationale=(
                "Crowd preference is restricted to days 1-6 when wide documents coexist with 1-8 recipient "
                "traps; SolverPolicy still narrows via regular leaks and wide >=9-recipient partitions."
            ),
            empirical_anchors={
                "gemini_opencode_hard_le3_share": 0.0,
                "gemini_opencode_hard_4_to_8_share": 0.496,
                "gemini_inproc_hard_4_to_8_share": 0.436,
                "gemini_inproc_medium_4_to_8_share": 0.736,
                "gemini_opencode_hard_3var_share": 1.0,
            },
            strategy_json={
                "name": "gemini_midsize_shield",
                "rules": [
                    {
                        "if": [
                            ["day", "<=", 6],
                            ["min_recipient_count", "<=", 8],
                            ["max_recipient_count", ">=", 14],
                        ],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [["n_restricted_colleagues", ">=", 1]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
        StrategySpec(
            name="reactive_canary_lag",
            lever_id="reactive_canary_lag_oldest",
            target_cohort="gemini_4_carbon",
            empirical_finding=(
                "On v1.4 Hard, Gemini delays its first canary to mean day 3.03 (OpenCode) and 3.40 (in-proc) "
                "versus Solver day 1.00, planting reactive age-0 canaries and making 7/10 Hard wrong accusations "
                "with <=1 separating canary under 0.95 fingerprint accuracy."
            ),
            solver_catchability_rationale=(
                "SolverPolicy plants 2 canaries per day starting day 1.00 (14.13 per episode on Hard), so its "
                "earlier canaries already occupy the oldest leak-window slot when oldest is selected."
            ),
            empirical_anchors={
                "gemini_opencode_hard_first_canary_day": 3.03,
                "gemini_inproc_hard_first_canary_day": 3.40,
                "solver_hard_first_canary_day": 1.00,
                "wrong_with_le_1_separating_canary": 10,
                "wrong_fp95_single_separating_canary": 7,
            },
            strategy_json={
                "name": "reactive_canary_lag",
                "rules": [
                    {
                        "if": [
                            ["day", "<=", 7],
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
        ),
        StrategySpec(
            name="non_decoy_tiebreak_framer",
            lever_id="non_decoy_peer_framing",
            target_cohort="frontier_all",
            empirical_finding=(
                "Frontier investigators dismissed the angry decoy in 100.0% of 159 decoy-enabled episodes "
                "(0 accusations, 0 restrictions), whereas non-decoy framed after-hours logs broke 0-separation "
                "canary ties into -1.0 wrong accusations in 5/10 total frontier wrong accusations."
            ),
            solver_catchability_rationale=(
                "SolverPolicy marginalises Poisson framing across peers with behaviour_temper=0.6 and never "
                "allows after-hours log spikes to override primary document and canary likelihoods."
            ),
            empirical_anchors={
                "frontier_decoy_episodes_total": 159,
                "frontier_decoy_accused_total": 0,
                "frontier_decoy_dismissal_rate": 1.0,
                "wrong_non_decoy_framed_tiebreak": 5,
                "wrong_with_zero_separating_canary": 8,
            },
            strategy_json={
                "name": "non_decoy_tiebreak_framer",
                "rules": [
                    {
                        "if": [
                            ["n_restricted_colleagues", ">=", 1],
                            ["recent_low_recipient_docs", ">=", 2],
                        ],
                        "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
                    },
                    {
                        "if": [["n_restricted_colleagues", ">=", 1]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    },
                    {
                        "if": [
                            ["day", "<=", 4],
                            ["max_recipient_count", ">=", 12],
                        ],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
        StrategySpec(
            name="early_burst_midgame_pace",
            lever_id="early_burst_midgame_quiet_pacing",
            target_cohort="gemini_4_carbon",
            empirical_finding=(
                "Gemini spends 57.27 to 68.03 calls per Hard episode on low-LR interviews (64.4% to 68.0% of "
                "investigative budget), lags Solver by +1.97 to +2.52 days, and makes 22 below-breakeven gambles."
            ),
            solver_catchability_rationale=(
                "Early leaks on days 1-2 hit Solver day-1 canaries, and midgame pacing only throttles consecutive "
                "days inside days 5-8, preserving ample leak volume over 21 days for >=0.85 Solver accuracy."
            ),
            empirical_anchors={
                "gemini_opencode_hard_interviews": 68.03,
                "gemini_inproc_hard_interviews": 57.27,
                "gemini_opencode_hard_day_lag": 2.52,
                "frontier_below_breakeven_gambles_total": 22,
                "frontier_horizon_gambles_total": 13,
            },
            strategy_json={
                "name": "early_burst_midgame_pace",
                "rules": [
                    {
                        "if": [
                            ["day", "<=", 2],
                            ["max_recipient_count", ">=", 12],
                        ],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [
                            ["day", ">=", 5],
                            ["day", "<=", 8],
                            ["days_since_last_leak", "<", 2],
                        ],
                        "then": {"leak": "none", "frame": "random_peer"},
                    },
                    {
                        "if": [["n_restricted_colleagues", ">=", 1]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
        StrategySpec(
            name="frontier_synthesis_v14",
            lever_id="composite_frontier_synthesis",
            target_cohort="frontier_all",
            empirical_finding=(
                "Combines early surgical-trap deflection, reactive age-0 canary evasion on days 1-7, "
                "bounded midgame pacing on days 5-8, and non-decoy peer framing across restricted and peer pools."
            ),
            solver_catchability_rationale=(
                "All four conditional rules relax to random_seeded after day 8 while framing only non-decoy peers, "
                "keeping SolverPolicy above 0.90 accuracy while reducing Gemini and Codex proxy scores."
            ),
            empirical_anchors={
                "frontier_episodes_total": 159,
                "frontier_wrong_accusations_total": 10,
                "frontier_decoy_dismissal_rate": 1.0,
                "gemini_opencode_hard_first_canary_day": 3.03,
                "codex_hard_le3_share": 0.306,
            },
            strategy_json={
                "name": "frontier_synthesis_v14",
                "rules": [
                    {
                        "if": [
                            ["day", "<=", 6],
                            ["recent_low_recipient_docs", ">=", 2],
                        ],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [
                            ["day", "<=", 7],
                            ["newest_doc_age_days", "==", 0],
                            ["n_leakable", ">=", 2],
                        ],
                        "then": {"leak": "oldest", "frame": "random_peer"},
                    },
                    {
                        "if": [
                            ["day", ">=", 5],
                            ["day", "<=", 8],
                            ["days_since_last_leak", "<", 2],
                        ],
                        "then": {"leak": "none", "frame": "random_peer"},
                    },
                    {
                        "if": [["n_restricted_colleagues", ">=", 1]],
                        "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
    )
    return {spec.name: spec for spec in items}


STRATEGY_SPECS: dict[str, StrategySpec] = _build_specs()
TRANSCRIPT_STRATEGIES: dict[str, MoleStrategy] = {
    name: spec.to_strategy() for name, spec in STRATEGY_SPECS.items()
}
STRATEGIES: dict[str, MoleStrategy] = dict(TRANSCRIPT_STRATEGIES)
STRATEGY_JSONS: dict[str, dict[str, Any]] = {
    name: spec.to_json() for name, spec in STRATEGY_SPECS.items()
}


def list_strategy_names(include_default: bool = False) -> list[str]:
    names = list(STRATEGY_SPECS.keys())
    return [DEFAULT_STRATEGY.name, *names] if include_default else names


def get_strategy_spec(name: str) -> StrategySpec:
    if name not in STRATEGY_SPECS:
        raise KeyError(f"unknown mole strategy {name!r}; expected one of {sorted(STRATEGY_SPECS)}")
    return STRATEGY_SPECS[name]


def get_strategy(name: str) -> MoleStrategy:
    if name in ("default", DEFAULT_STRATEGY.name):
        return DEFAULT_STRATEGY
    if name in TRANSCRIPT_STRATEGIES:
        return TRANSCRIPT_STRATEGIES[name]
    raise KeyError(f"unknown mole strategy {name!r}; expected one of {sorted(TRANSCRIPT_STRATEGIES)}")


def get_strategy_json(name: str) -> dict[str, Any]:
    if name in ("default", DEFAULT_STRATEGY.name):
        return DEFAULT_STRATEGY.to_json()
    return get_strategy_spec(name).to_json()


def all_strategies(include_default: bool = False) -> dict[str, MoleStrategy]:
    if include_default:
        return {DEFAULT_STRATEGY.name: DEFAULT_STRATEGY, **TRANSCRIPT_STRATEGIES}
    return dict(TRANSCRIPT_STRATEGIES)


def all_strategy_jsons(include_default: bool = False) -> list[dict[str, Any]]:
    out = [spec.to_json() for spec in STRATEGY_SPECS.values()]
    if include_default:
        return [DEFAULT_STRATEGY.to_json(), *out]
    return out


def export_hof_rows(names: Sequence[str] | None = None) -> list[dict[str, Any]]:
    selected = list(STRATEGY_SPECS.keys()) if names is None else list(names)
    return [get_strategy_spec(name).to_hof_row(rank=idx + 1) for idx, name in enumerate(selected)]


def write_hof_jsonl(path: str | Path, names: Sequence[str] | None = None) -> Path:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = export_hof_rows(names=names)
    out_path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    return out_path


def _normalize_dev_seeds(seeds: str | int | Iterable[int], enforce_hygiene: bool = True) -> list[int]:
    if isinstance(seeds, str):
        seed_list = parse_seeds(seeds)
    elif isinstance(seeds, int):
        seed_list = list(range(6000, 6000 + int(seeds)))
    else:
        seed_list = [int(s) for s in seeds]
    if not seed_list:
        raise ValueError("seeds must not be empty")
    if enforce_hygiene:
        for s in seed_list:
            if s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(f"seed {s} violates dev seed hygiene (0..{FORBIDDEN_LOW_SEED_MAX} reserved)")
            if s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
                raise ValueError(f"seed {s} violates judge/heldout seed hygiene")
            if s in RESERVED_HELDOUT_EVAL_SEEDS:
                raise ValueError(f"seed {s} falls in reserved held-out eval range 30000..30199")
    return seed_list


def _make_solver(tier: str) -> SolverPolicy:
    return SolverPolicy(tier if tier in TIERS else tier_params(tier))


def _eval_single_seed(args: tuple[str, int, dict[str, Any], bool]) -> dict[str, tuple[float, bool]]:
    tier, seed, sj, include_proxies = args
    strat = MoleStrategy.from_json(sj)
    sol_res = run_episode(Env(tier, seed, mole_strategy=strat), _make_solver(tier))
    lo_res = run_episode(Env(tier, seed, mole_strategy=strat), LogsOnly(seed=seed))
    row: dict[str, tuple[float, bool]] = {
        "solver": (float(sol_res.score), bool(sol_res.correct)),
        "logs_only": (float(lo_res.score), bool(lo_res.correct)),
    }
    if include_proxies:
        aml_res = run_episode(Env(tier, seed, mole_strategy=strat), AccuseMostLogs(seed=seed))
        gem_res = run_episode(Env(tier, seed, mole_strategy=strat), GeminiCarbonProxy(seed=seed))
        cdx_res = run_episode(Env(tier, seed, mole_strategy=strat), CodexHorizonProxy(seed=seed))
        hh_res = run_episode(Env(tier, seed, mole_strategy=strat), HintedHeuristic(seed=seed))
        heu_res = run_episode(Env(tier, seed, mole_strategy=strat), Heuristic(seed=seed))
        row["accuse_most_logs"] = (float(aml_res.score), bool(aml_res.correct))
        row["gemini_proxy"] = (float(gem_res.score), bool(gem_res.correct))
        row["codex_proxy"] = (float(cdx_res.score), bool(cdx_res.correct))
        row["hinted_heuristic"] = (float(hh_res.score), bool(hh_res.correct))
        row["heuristic"] = (float(heu_res.score), bool(heu_res.correct))
    return row


def _solver_baseline(tier: str, seed_list: Sequence[int], workers: int = 1) -> dict[str, float]:
    key = (tier, tuple(seed_list))
    if key not in _SOLVER_BASELINE_CACHE:
        default_sj = DEFAULT_STRATEGY.to_json()
        tasks = [(tier, s, default_sj, False) for s in seed_list]
        if workers > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
                rows = list(pool.map(_eval_single_seed, tasks))
        else:
            rows = [_eval_single_seed(t) for t in tasks]
        n = len(rows)
        _SOLVER_BASELINE_CACHE[key] = {
            "score": sum(r["solver"][0] for r in rows) / n,
            "acc": sum(r["solver"][1] for r in rows) / n,
        }
    return dict(_SOLVER_BASELINE_CACHE[key])


def verify_strategy_slice(
    strategy: str | dict[str, Any] | MoleStrategy,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = DEFAULT_DEV_SEEDS,
    workers: int = 1,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    include_proxies: bool = False,
    enforce_seed_hygiene: bool = True,
) -> dict[str, Any]:
    seed_list = _normalize_dev_seeds(seeds, enforce_hygiene=enforce_seed_hygiene)
    if isinstance(strategy, str):
        parsed = get_strategy(strategy)
    elif isinstance(strategy, MoleStrategy):
        parsed = strategy
    elif isinstance(strategy, dict):
        payload = strategy.get("strategy_json", strategy.get("strategy", strategy))
        parsed = MoleStrategy.from_json(payload)
    else:
        raise TypeError(f"unsupported strategy type: {type(strategy).__name__}")

    sj = parsed.to_json()
    re_parsed = MoleStrategy.from_json(json.loads(json.dumps(sj)))
    if re_parsed != parsed or len(parsed.rules) > MAX_RULES:
        raise ValueError(f"strategy {parsed.name!r} failed MoleStrategy round-trip validation")
    validate_strategy({"rules": sj["rules"], "default": sj["default"]})
    conds_valid = all(is_valid_rule_conds(r["if"], tier) for r in sj.get("rules", []))

    baseline = _solver_baseline(tier, seed_list, workers=workers)
    tasks = [(tier, s, sj, include_proxies) for s in seed_list]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
            rows = list(pool.map(_eval_single_seed, tasks))
    else:
        rows = [_eval_single_seed(t) for t in tasks]

    n = len(rows)
    sol_score = sum(r["solver"][0] for r in rows) / n
    sol_acc = sum(r["solver"][1] for r in rows) / n
    lo_score = sum(r["logs_only"][0] for r in rows) / n
    lo_acc = sum(r["logs_only"][1] for r in rows) / n

    solver_ok = sol_acc >= min_solver_acc and sol_score >= min_solver_ratio * baseline["score"]
    logs_ok = lo_acc <= max_logs_acc and lo_score < 0.0
    aml_acc: float | None = None
    aml_score: float | None = None
    if include_proxies:
        aml_score = sum(r["accuse_most_logs"][0] for r in rows) / n
        aml_acc = sum(r["accuse_most_logs"][1] for r in rows) / n
        logs_ok = logs_ok and aml_acc <= max_logs_acc and aml_score < 0.0

    out: dict[str, Any] = {
        "name": parsed.name,
        "tier": tier,
        "n_seeds": n,
        "seeds": seed_list,
        "behavior_hash": behavior_hash(sj, tier),
        "n_rules": len(parsed.rules),
        "conds_valid": conds_valid,
        "solver_acc": sol_acc,
        "solver_score": sol_score,
        "baseline_solver_score": baseline["score"],
        "baseline_solver_acc": baseline["acc"],
        "logs_only_acc": lo_acc,
        "logs_only_score": lo_score,
        "accuse_most_logs_acc": aml_acc,
        "accuse_most_logs_score": aml_score,
        "min_solver_acc": float(min_solver_acc),
        "max_logs_acc": float(max_logs_acc),
        "min_solver_ratio": float(min_solver_ratio),
        "solver_passed": bool(solver_ok),
        "logs_passed": bool(logs_ok),
        "passed": bool(conds_valid and solver_ok and logs_ok),
    }
    if include_proxies:
        proxies: dict[str, dict[str, float]] = {}
        for pname in ("gemini_proxy", "codex_proxy", "hinted_heuristic", "heuristic"):
            pscore = sum(r[pname][0] for r in rows) / n
            pacc = sum(r[pname][1] for r in rows) / n
            proxies[pname] = {
                "score": pscore,
                "acc": pacc,
                "regret": sol_score - pscore,
            }
        out["proxies"] = proxies
        out["min_proxy_regret"] = min(v["regret"] for v in proxies.values())
        out["mean_proxy_regret"] = sum(v["regret"] for v in proxies.values()) / len(proxies)
    return out


def verify_all_strategies(
    names: Sequence[str] | None = None,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = DEFAULT_DEV_SEEDS,
    workers: int = 1,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    include_proxies: bool = False,
) -> dict[str, Any]:
    seed_list = _normalize_dev_seeds(seeds, enforce_hygiene=True)
    selected = list(STRATEGY_SPECS.keys()) if names is None else list(names)
    results = [
        verify_strategy_slice(
            name,
            tier=tier,
            seeds=seed_list,
            workers=workers,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
            include_proxies=include_proxies,
        )
        for name in selected
    ]
    hashes = [r["behavior_hash"] for r in results]
    default_bh = behavior_hash(DEFAULT_STRATEGY.to_json(), tier)
    unique_behaviors = len(set(hashes)) == len(hashes) and default_bh not in set(hashes)
    all_passed = bool(results) and all(r["passed"] for r in results) and unique_behaviors
    return {
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "n_strategies": len(results),
        "n_passed": sum(1 for r in results if r["passed"]),
        "unique_behaviors": unique_behaviors,
        "default_behavior_hash": default_bh,
        "all_passed": all_passed,
        "strategies": results,
    }


def _format_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Mole Strategy Slice Verification (tier={report['tier']}, n_seeds={report['n_seeds']}, "
        f"passed={report['n_passed']}/{report['n_strategies']}, unique_behaviors={report['unique_behaviors']})",
        "| strategy | rules | bhash | solver_acc | solver_score | logs_only_acc | status |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in report["strategies"]:
        status = "PASS" if row["passed"] else "FAIL"
        lines.append(
            f"| {row['name']} | {row['n_rules']} | {row['behavior_hash'][:8]} | "
            f"{row['solver_acc']:.2f} | {row['solver_score']:+.3f} | "
            f"{row['logs_only_acc']:.2f} | {status} |"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.strategies")
    ap.add_argument("--list", action="store_true", help="list strategy names and empirical targets")
    ap.add_argument("--strategy", default=None, help="verify or print a single named strategy")
    ap.add_argument("--verify", action="store_true", help="run fast slice verification")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="6000-6009")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--include-proxies", action="store_true")
    ap.add_argument("--export-hof", type=Path, default=None, help="write JSONL hall-of-fame rows")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    names = [args.strategy] if args.strategy else None

    if args.export_hof is not None:
        write_hof_jsonl(args.export_hof, names=names)

    if args.list and not args.verify:
        payload = [
            {
                "name": s.name,
                "lever_id": s.lever_id,
                "target_cohort": s.target_cohort,
                "n_rules": len(s.strategy_json["rules"]),
                "behavior_hash": behavior_hash(s.strategy_json, args.tier),
                "empirical_anchors": s.empirical_anchors,
                "canonical_json": canonical(s.strategy_json),
            }
            for s in (
                [get_strategy_spec(args.strategy)] if args.strategy else list(STRATEGY_SPECS.values())
            )
        ]
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for item in payload:
                print(
                    f"{item['name']} (lever={item['lever_id']}, cohort={item['target_cohort']}, "
                    f"rules={item['n_rules']}, bhash={item['behavior_hash'][:8]})"
                )
        return 0

    if args.verify:
        rep = verify_all_strategies(
            names=names,
            tier=args.tier,
            seeds=args.seeds,
            workers=args.workers,
            min_solver_acc=args.min_solver_acc,
            max_logs_acc=args.max_logs_acc,
            min_solver_ratio=args.min_solver_ratio,
            include_proxies=args.include_proxies,
        )
        if args.json:
            print(json.dumps(rep, indent=2, sort_keys=True))
        else:
            print(_format_summary(rep))
        return 0 if rep["all_passed"] else 1

    if args.strategy:
        print(json.dumps(get_strategy_json(args.strategy), indent=2, sort_keys=True))
        return 0

    if args.export_hof is not None:
        print(f"wrote {len(export_hof_rows(names=names))} strategies to {args.export_hof}")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
