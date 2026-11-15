"""Benchmark and validate v1.4 Mole DSL strategies under strict CONTRACT section 7 catchability and fairness gates."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import logging
import math
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import (
    AccuseMostLogs,
    DoNothing,
    GrokTactics,
    Heuristic,
    LogsOnly,
    StopEarly,
    StopEarlyQuit,
)
from canary.env import ERRORS as ENV_ERRORS, Env
from canary.eval import run_episode
from canary.forge.fitness import FEASIBLE_SOLVER_ACC, FEASIBLE_SOLVER_RATIO
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy, StrategyError
from canary.mole.evolve_v14 import behavior_hash
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION
from canary.solver.policy import SolverPolicy

MD_H = chr(35)
HOF_KEYS = ["rank", "fitness", "solver_score", "solver_acc", "per_investigator", "strategy_json"]
OUTCOME_EVENTS = ("leak", "framed")
OUTCOME_AGENTS = ("do_nothing", "solver")
CORE_INVESTIGATORS = ("grok_tactics", "heuristic", "hinted_heuristic")
FORBIDDEN_LOW_SEED_MAX = 59
RESERVED_HELDOUT_RANGE = range(30_000, 30_200)
FORBIDDEN_LEAK_TOKENS = (
    "strategy_json",
    "most_recipients",
    "fewest_recipients",
    "most_restricted_peer",
    "random_peer",
    "random_seeded",
)

BUILTIN_V14_CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "name": "two_wave_blackout",
        "description": (
            "Two-wave intermittent pulse: leaks narrow docs on days 1..6, goes dark on days 7..9 while "
            "delayed Wave 1 leaks surface, leaks aged stale docs on days 10..12 plus a day-15 newest pulse, "
            "and suppresses 2-recipient trap canaries."
        ),
        "strategy_json": {
            "rules": [
                {"if": [["min_recipient_count", "<=", 2]], "then": {"leak": "none", "frame": "random_peer"}},
                {"if": [["day", "<=", 6]], "then": {"leak": "fewest_recipients", "frame": "decoy"}},
                {"if": [["day", "<=", 9]], "then": {"leak": "none", "frame": "random_peer"}},
                {"if": [["day", "<=", 12]], "then": {"leak": "oldest", "frame": "decoy"}},
                {"if": [["day", "==", 15]], "then": {"leak": "newest", "frame": "most_restricted_peer"}},
            ],
            "default": {"leak": "none", "frame": "random_peer"},
        },
    },
    {
        "name": "frontload_oldest_d11",
        "description": (
            "Early narrow-doc leaks on days 1..7 transitioning to cooldown-paced stale-doc leaks "
            "(days 8..11 with days_since_last_leak >= 2) and a day-14 seeded pulse, while suppressing "
            "2-recipient traps and framing restricted peers late."
        ),
        "strategy_json": {
            "rules": [
                {"if": [["min_recipient_count", "<=", 2]], "then": {"leak": "none", "frame": "random_peer"}},
                {"if": [["day", "<=", 7]], "then": {"leak": "fewest_recipients", "frame": "decoy"}},
                {
                    "if": [["day", "<=", 11], ["days_since_last_leak", ">=", 2]],
                    "then": {"leak": "oldest", "frame": "decoy"},
                },
                {"if": [["day", "==", 14]], "then": {"leak": "random_seeded", "frame": "random_peer"}},
            ],
            "default": {"leak": "none", "frame": "most_restricted_peer"},
        },
    },
    {
        "name": "sleeper_d3_burst",
        "description": (
            "Opening sleeper that stays silent on days 1..2 so early un-narrowed splits age, diverts "
            "2-recipient traps onto wide regular docs, leaks actively on days 3..10, and emits sparse "
            "pulses on days 13 and 16."
        ),
        "strategy_json": {
            "rules": [
                {"if": [["day", "<=", 2]], "then": {"leak": "none", "frame": "random_peer"}},
                {"if": [["min_recipient_count", "<=", 2]], "then": {"leak": "most_recipients", "frame": "random_peer"}},
                {"if": [["day", "<=", 10]], "then": {"leak": "fewest_recipients", "frame": "decoy"}},
                {"if": [["day", "==", 13]], "then": {"leak": "oldest", "frame": "random_peer"}},
                {"if": [["day", "==", 16]], "then": {"leak": "random_seeded", "frame": "most_restricted_peer"}},
            ],
            "default": {"leak": "none", "frame": "most_restricted_peer"},
        },
    },
    {
        "name": "v13_adapted_v14",
        "description": (
            "Restriction counter-probe that halts leaks and frames restricted colleagues whenever "
            "n_restricted_colleagues >= 2, diverts 2-recipient traps to wide regular docs, pauses on "
            "days 8..9, resumes on days 10..11, and pulses on day 14."
        ),
        "strategy_json": {
            "rules": [
                {
                    "if": [["n_restricted_colleagues", ">=", 2]],
                    "then": {"leak": "none", "frame": "most_restricted_peer"},
                },
                {"if": [["min_recipient_count", "<=", 2]], "then": {"leak": "most_recipients", "frame": "random_peer"}},
                {"if": [["day", "<", 8]], "then": {"leak": "fewest_recipients", "frame": "decoy"}},
                {"if": [["day", "<=", 9]], "then": {"leak": "none", "frame": "decoy"}},
                {"if": [["day", "<=", 11]], "then": {"leak": "fewest_recipients", "frame": "random_peer"}},
                {"if": [["day", "==", 14]], "then": {"leak": "random_seeded", "frame": "none"}},
            ],
            "default": {"leak": "none", "frame": "most_restricted_peer"},
        },
    },
    {
        "name": "frontload_blackout_d9",
        "description": (
            "Front-loaded active window on days 1..9 with broad-doc trap diversion against 2-recipient "
            "canaries, followed by a sustained horizon blackout except a day-13 stale-doc pulse."
        ),
        "strategy_json": {
            "rules": [
                {"if": [["min_recipient_count", "<=", 2]], "then": {"leak": "most_recipients", "frame": "random_peer"}},
                {"if": [["day", "<=", 9]], "then": {"leak": "fewest_recipients", "frame": "decoy"}},
                {"if": [["day", "==", 13]], "then": {"leak": "oldest", "frame": "random_peer"}},
            ],
            "default": {"leak": "none", "frame": "random_peer"},
        },
    },
    {
        "name": "window_crowd_stale",
        "description": (
            "Early narrow-doc leaks on days 1..6 followed by queue-depth conditional stale-doc leaks "
            "when n_leakable >= 7 on days 7..11 to dodge freshly planted splits, plus sparse pulses on days 13 and 15."
        ),
        "strategy_json": {
            "rules": [
                {"if": [["min_recipient_count", "<=", 2]], "then": {"leak": "most_recipients", "frame": "random_peer"}},
                {"if": [["day", "<=", 6]], "then": {"leak": "fewest_recipients", "frame": "decoy"}},
                {"if": [["n_leakable", ">=", 7], ["day", "<=", 11]], "then": {"leak": "oldest", "frame": "random_peer"}},
                {"if": [["day", "==", 13]], "then": {"leak": "random_seeded", "frame": "decoy"}},
                {"if": [["day", "==", 15]], "then": {"leak": "newest", "frame": "most_restricted_peer"}},
            ],
            "default": {"leak": "none", "frame": "random_peer"},
        },
    },
)


def parse_seed_spec(spec: str | Sequence[int]) -> list[int]:
    """Parse 'a-b' (inclusive), 'a:b' (half-open), or comma-separated integers into a list of seeds."""
    if not isinstance(spec, str):
        out = [int(x) for x in spec]
        if not out:
            raise ValueError("seed list must not be empty")
        return out
    out: list[int] = []
    for part in spec.split(","):
        tok = part.strip()
        if not tok:
            continue
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi <= lo:
                raise ValueError(f"empty or reversed seed slice: {tok!r}")
            out.extend(range(lo, hi))
        elif "-" in tok:
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"reversed seed range: {tok!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(tok))
    if not out:
        raise ValueError(f"no seeds parsed from {spec!r}")
    return out


def validate_benchmark_seeds(
    dev_seeds: Sequence[int] | None,
    heldout_seeds: Sequence[int],
) -> None:
    """Enforce seed hygiene: forbid 0..59, 30000..30199, and 800000+, and forbid overlap."""
    if not heldout_seeds:
        raise ValueError("heldout_seeds must not be empty")
    groups: list[tuple[str, Sequence[int]]] = [("heldout_seeds", heldout_seeds)]
    if dev_seeds is not None:
        if not dev_seeds:
            raise ValueError("dev_seeds must not be empty when provided")
        groups.insert(0, ("dev_seeds", dev_seeds))

    for label, seq in groups:
        for s in seq:
            if isinstance(s, bool) or not isinstance(s, int):
                raise ValueError(f"{label} contains non-integer seed: {s!r}")
            if s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(f"{label} contains forbidden seed {s} (0..59 and negatives prohibited)")
            if s in RESERVED_HELDOUT_RANGE:
                raise ValueError(f"{label} contains reserved seed {s} (30000..30199 prohibited)")
            if s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
                raise ValueError(f"{label} contains forbidden judge/heldout seed {s} (800000+ prohibited)")

    if dev_seeds is not None:
        overlap = sorted(set(dev_seeds) & set(heldout_seeds))
        if overlap:
            raise ValueError(f"dev_seeds and heldout_seeds must be disjoint; overlap={overlap[:10]}")


def mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def ci_half_normal(xs: Sequence[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return 1.96 * math.sqrt(var / n)


def bootstrap_ci(xs: Sequence[float], n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Return (mean, lo_95, hi_95) via deterministic bootstrap resampling."""
    if not xs:
        return (0.0, 0.0, 0.0)
    n = len(xs)
    m = mean(xs)
    if n == 1:
        return (m, m, m)
    rng = random.Random(f"boot:{seed}:{n}")
    samples = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    lo = samples[int(0.025 * n_boot)]
    hi = samples[min(n_boot - 1, int(0.975 * n_boot))]
    return (m, lo, hi)


def discover_proxy_factories() -> dict[str, Callable[[int], Any]]:
    """Discover GeminiCarbonProxy and CodexHorizonProxy from canary.forge.frontier_proxies."""
    found: dict[str, Callable[[int], Any]] = {}
    targets = (
        ("gemini_carbon_proxy", "GeminiCarbonProxy"),
        ("codex_horizon_proxy", "CodexHorizonProxy"),
    )
    modules = (
        "canary.forge.frontier_proxies",
        "canary.mole.proxies",
        "canary.agents.proxies",
        "canary.forge.investigators",
    )
    for key, cls_name in targets:
        for mod_name in modules:
            try:
                mod = importlib.import_module(mod_name)
            except ImportError:
                continue
            cls = getattr(mod, cls_name, None)
            if cls is not None:
                found[key] = lambda s, _cls=cls: _cls(seed=s)
                break
    return found


def make_agent_factory(agent_name: str, tier: str = "hard") -> Callable[[int], Any]:
    if agent_name == "solver":
        return lambda _s: SolverPolicy(tier)
    if agent_name == "grok_tactics":
        return lambda s: GrokTactics(seed=s)
    if agent_name == "heuristic":
        return lambda s: Heuristic(seed=s)
    if agent_name == "hinted_heuristic":
        return lambda s: HintedHeuristic(seed=s)
    if agent_name == "do_nothing":
        return lambda s: DoNothing(seed=s)
    if agent_name == "stop_early":
        return lambda s: StopEarlyQuit(seed=s)
    if agent_name == "guess_day1":
        return lambda s: StopEarly(seed=s)
    if agent_name == "logs_only":
        return lambda s: LogsOnly(seed=s)
    if agent_name == "accuse_most_logs":
        return lambda s: AccuseMostLogs(seed=s)
    proxies = discover_proxy_factories()
    if agent_name in proxies:
        return proxies[agent_name]
    raise ValueError(f"unknown agent {agent_name!r}")


def check_dsl_valid(strategy_obj: dict[str, Any]) -> tuple[bool, dict[str, Any], str | None]:
    try:
        if not isinstance(strategy_obj, dict):
            raise StrategyError("strategy must be a JSON object")
        norm = validate_strategy(strategy_obj)
        parsed = MoleStrategy.from_json(norm)
        if len(parsed.rules) > MAX_RULES:
            raise StrategyError(f"too many rules: {len(parsed.rules)} > {MAX_RULES}")
        c1 = canonical(parsed.to_json())
        reparsed = MoleStrategy.from_json(json.loads(c1))
        if reparsed != parsed or canonical(reparsed.to_json()) != c1:
            raise StrategyError("canonical round-trip mismatch")
        return True, norm, None
    except (StrategyError, ValueError, TypeError) as exc:
        return False, {}, str(exc)


def _scan_steps_for_leaks(steps: Sequence[Any]) -> list[str]:
    violations: list[str] = []
    for st in steps:
        res = st.result if hasattr(st, "result") else st.get("result", {})
        if not isinstance(res, dict):
            continue
        if not res.get("ok", True):
            err = res.get("error")
            if err not in ENV_ERRORS:
                violations.append(f"unexpected tool error: {err!r}")
        blob = json.dumps(res, sort_keys=True)
        for tok in FORBIDDEN_LEAK_TOKENS:
            if tok in blob:
                violations.append(f"forbidden DSL token {tok!r} in tool result")
    return violations


def _eval_candidate_task(args: tuple[str, str, dict[str, Any], str, list[int], tuple[str, ...]]) -> dict[str, Any]:
    name, description, raw_strategy, tier, seeds, investigators = args
    dsl_ok, norm_sj, dsl_err = check_dsl_valid(raw_strategy)
    if not dsl_ok:
        return {
            "name": name,
            "description": description,
            "strategy_json": raw_strategy,
            "dsl_valid": False,
            "dsl_error": dsl_err,
            "all_gates_passed": False,
        }

    ms = MoleStrategy.from_json(norm_sj)
    all_agents = list(
        dict.fromkeys(
            [
                "do_nothing",
                "solver",
                *investigators,
                "stop_early",
                "guess_day1",
                "logs_only",
                "accuse_most_logs",
            ]
        )
    )
    per_agent: dict[str, list[tuple[float, bool, str | None, int]]] = {ag: [] for ag in all_agents}
    outcome_events: list[tuple[Any, ...]] = []
    leak_violations: list[str] = []
    det_seeds = seeds[: min(2, len(seeds))]
    det_ok = True

    for ag in all_agents:
        fac = make_agent_factory(ag, tier=tier)
        for idx, s in enumerate(seeds):
            env = Env(tier, s, mole_strategy=ms)
            ep = run_episode(env, fac(s))
            per_agent[ag].append((float(ep.score), bool(ep.correct), ep.accused, int(ep.final_day)))
            if ag in OUTCOME_AGENTS:
                outcome_events.extend(
                    (ag, s, e.day, e.event, e.detail.get("doc_id") or e.detail.get("employee"))
                    for e in env.ledger()
                    if e.event in OUTCOME_EVENTS
                )
            if ag in ("solver", "heuristic") and idx < 5:
                leak_violations.extend(_scan_steps_for_leaks(ep.steps))
            if ag == "solver" and s in det_seeds:
                env2 = Env(tier, s, mole_strategy=MoleStrategy.from_json(norm_sj))
                ep2 = run_episode(env2, make_agent_factory("solver", tier=tier)(s))
                if (
                    ep2.score != ep.score
                    or ep2.correct != ep.correct
                    or ep2.accused != ep.accused
                    or env2.ledger() != env.ledger()
                ):
                    det_ok = False

    sol_scores = [x[0] for x in per_agent["solver"]]
    sol_accs = [float(x[1]) for x in per_agent["solver"]]
    sol_nones = [float(x[2] in (None, "")) for x in per_agent["solver"]]
    sol_days = [float(x[3]) for x in per_agent["solver"]]

    per_inv: dict[str, dict[str, Any]] = {}
    for inv in investigators:
        inv_scores = [x[0] for x in per_agent[inv]]
        inv_accs = [float(x[1]) for x in per_agent[inv]]
        regs = [a - b for a, b in zip(sol_scores, inv_scores)]
        reg_mean, reg_lo, reg_hi = bootstrap_ci(regs, n_boot=2000, seed=17)
        per_inv[inv] = {
            "score": mean(inv_scores),
            "score_ci": ci_half_normal(inv_scores),
            "acc": mean(inv_accs),
            "regret": reg_mean,
            "regret_ci": ci_half_normal(regs),
            "regret_boot_lo": reg_lo,
            "regret_boot_hi": reg_hi,
            "seed_scores": inv_scores,
            "seed_regrets": regs,
        }

    strongest = min(investigators, key=lambda inv: per_inv[inv]["regret"])
    min_regret = per_inv[strongest]["regret"]
    mean_regret = mean([per_inv[inv]["regret"] for inv in investigators])
    core_present = [inv for inv in CORE_INVESTIGATORS if inv in per_inv]
    core_min_regret = min((per_inv[inv]["regret"] for inv in core_present), default=min_regret)

    dn_scores = [x[0] for x in per_agent["do_nothing"]]
    se_scores = [x[0] for x in per_agent["stop_early"]]
    gd_scores = [x[0] for x in per_agent["guess_day1"]]
    lo_scores = [x[0] for x in per_agent["logs_only"]]
    lo_accs = [float(x[1]) for x in per_agent["logs_only"]]
    aml_scores = [x[0] for x in per_agent["accuse_most_logs"]]
    aml_accs = [float(x[1]) for x in per_agent["accuse_most_logs"]]

    outcome_hash = hashlib.sha256(json.dumps(outcome_events).encode("utf-8")).hexdigest()[:10]
    b_hash = behavior_hash(norm_sj, tier)
    canon_hash = hashlib.sha256(canonical(norm_sj).encode("utf-8")).hexdigest()[:10]
    sol_mean, sol_lo, sol_hi = bootstrap_ci(sol_scores, n_boot=2000, seed=11)

    return {
        "name": name,
        "description": description,
        "strategy_json": norm_sj,
        "n_rules": len(norm_sj.get("rules", [])),
        "n_seeds": len(seeds),
        "dsl_valid": True,
        "dsl_error": None,
        "no_tool_leak": len(leak_violations) == 0,
        "leak_violations": leak_violations[:5],
        "determinism": det_ok,
        "do_nothing_score": mean(dn_scores),
        "do_nothing_all_zero": all(x == 0.0 for x in dn_scores),
        "stop_early_score": mean(se_scores),
        "stop_early_all_zero": all(x == 0.0 for x in se_scores),
        "guess_day1_score": mean(gd_scores),
        "guess_day1_negative": mean(gd_scores) < 0.0,
        "logs_only_score": mean(lo_scores),
        "logs_only_acc": mean(lo_accs),
        "accuse_most_logs_score": mean(aml_scores),
        "accuse_most_logs_acc": mean(aml_accs),
        "solver_score": sol_mean,
        "solver_ci": ci_half_normal(sol_scores),
        "solver_boot_lo": sol_lo,
        "solver_boot_hi": sol_hi,
        "solver_acc": mean(sol_accs),
        "solver_none_rate": mean(sol_nones),
        "solver_mean_day": mean(sol_days),
        "seed_solver_scores": sol_scores,
        "per_investigator": per_inv,
        "strongest_investigator": strongest,
        "min_regret": min_regret,
        "core_min_regret": core_min_regret,
        "mean_regret": mean_regret,
        "outcome_hash": outcome_hash,
        "behavior_hash": b_hash,
        "canon_hash": canon_hash,
    }


def evaluate_suite(
    candidates: Sequence[dict[str, Any]],
    seeds: Sequence[int],
    tier: str = "hard",
    investigators: Sequence[str] = CORE_INVESTIGATORS,
    workers: int = 1,
    min_solver_acc: float = FEASIBLE_SOLVER_ACC,
    min_solver_ratio: float = FEASIBLE_SOLVER_RATIO,
    max_logs_acc: float = 0.10,
) -> dict[str, Any]:
    """Evaluate DEFAULT_STRATEGY plus all candidates on a seed slice and compute gates and paired gains."""
    seed_list = [int(s) for s in seeds]
    inv_tuple = tuple(investigators)
    default_entry = {
        "name": "default",
        "description": "Default v0 MoleStrategy (random_seeded leak under careful_mole weights, no extra DSL rules).",
        "strategy_json": validate_strategy(DEFAULT_STRATEGY.to_json()),
    }
    all_entries = [default_entry, *candidates]
    tasks = [
        (
            str(c["name"]),
            str(c.get("description", "")),
            c["strategy_json"],
            tier,
            seed_list,
            inv_tuple,
        )
        for c in all_entries
    ]

    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
            rows = list(pool.map(_eval_candidate_task, tasks))
    else:
        rows = [_eval_candidate_task(t) for t in tasks]

    base = rows[0]
    base_solver = float(base["solver_score"])
    base_min_regret = float(base["min_regret"])
    base_core_regret = float(base["core_min_regret"])
    base_outcome = str(base["outcome_hash"])
    base_bhash = str(base["behavior_hash"])

    outcome_groups: dict[str, list[str]] = {}
    behavior_groups: dict[str, list[str]] = {}
    for r in rows:
        if not r.get("dsl_valid"):
            r["all_gates_passed"] = False
            continue
        ratio = r["solver_score"] / base_solver if base_solver > 0 else 0.0
        zero_baselines = bool(
            r["do_nothing_all_zero"] and r["stop_early_all_zero"] and r["guess_day1_negative"]
        )
        logs_ok = bool(
            float(r["logs_only_acc"]) <= max_logs_acc
            and float(r["logs_only_score"]) < 0.0
            and float(r["accuse_most_logs_acc"]) <= max_logs_acc
            and float(r["accuse_most_logs_score"]) < 0.0
        )
        strict_s7 = (
            float(r["solver_acc"]) >= min_solver_acc
            and float(r["solver_score"]) >= max(0.25, min_solver_ratio * base_solver)
        )
        fairness_ok = bool(
            r["dsl_valid"]
            and r["no_tool_leak"]
            and r["determinism"]
            and zero_baselines
            and logs_ok
            and strict_s7
        )
        min_regret_gain = float(r["min_regret"]) - base_min_regret
        core_regret_gain = float(r["core_min_regret"]) - base_core_regret
        paired_strongest_diffs = [
            a - b
            for a, b in zip(
                r["per_investigator"][r["strongest_investigator"]]["seed_regrets"],
                base["per_investigator"][r["strongest_investigator"]]["seed_regrets"],
            )
        ]
        _, gain_lo, gain_hi = bootstrap_ci(paired_strongest_diffs, n_boot=2000, seed=23)

        is_default = r["name"] == "default"
        beats_default = (
            (not is_default)
            and (float(r["min_regret"]) > base_min_regret)
            and (float(r["core_min_regret"]) > base_core_regret)
        )
        distinct_from_default = (
            (not is_default)
            and (r["outcome_hash"] != base_outcome)
            and (r["behavior_hash"] != base_bhash)
        )

        r["ratio_vs_default"] = ratio
        r["zero_baselines_ok"] = zero_baselines
        r["logs_only_ok"] = logs_ok
        r["strict_s7"] = strict_s7
        r["fairness_passed"] = fairness_ok
        r["beats_default_regret"] = beats_default
        r["distinct_from_default"] = distinct_from_default
        r["min_regret_gain"] = min_regret_gain
        r["core_regret_gain"] = core_regret_gain
        r["strongest_regret_gain_ci"] = (gain_lo, gain_hi)
        r["all_gates_passed"] = bool(fairness_ok and beats_default and distinct_from_default)
        if not is_default:
            outcome_groups.setdefault(r["outcome_hash"], []).append(r["name"])
            behavior_groups.setdefault(r["behavior_hash"], []).append(r["name"])

    return {
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seed_list,
        "investigators": list(inv_tuple),
        "default": base,
        "candidates": rows[1:],
        "all_rows": rows,
        "outcome_groups": outcome_groups,
        "behavior_groups": behavior_groups,
        "gates": {
            "min_solver_acc": min_solver_acc,
            "min_solver_ratio": min_solver_ratio,
            "max_logs_acc": max_logs_acc,
        },
    }


def select_hof_survivors(
    eval_result: dict[str, Any],
    top_k: int = 4,
    dev_eval: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Deduplicate feasible candidates by both outcome_hash and behavior_hash and rank top_k survivors."""
    dev_passed_names: set[str] | None = None
    if dev_eval is not None:
        dev_passed_names = {r["name"] for r in dev_eval["candidates"] if r.get("all_gates_passed")}
    feasible = [
        r
        for r in eval_result["candidates"]
        if r.get("all_gates_passed") and (dev_passed_names is None or r["name"] in dev_passed_names)
    ]
    ordered_candidates = sorted(
        feasible,
        key=lambda r: (
            float(r["min_regret"]),
            float(r["core_min_regret"]),
            float(r["solver_score"]),
            -int(r["n_rules"]),
            str(r["name"]),
        ),
        reverse=True,
    )

    seen_outcomes: set[str] = set()
    seen_behaviors: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for r in ordered_candidates:
        oh = str(r["outcome_hash"])
        bh = str(r["behavior_hash"])
        if oh in seen_outcomes or bh in seen_behaviors:
            continue
        seen_outcomes.add(oh)
        seen_behaviors.add(bh)
        ranked.append(r)
        if len(ranked) >= max(0, int(top_k)):
            break

    hof_rows: list[dict[str, Any]] = []
    for idx, r in enumerate(ranked, start=1):
        per_inv_clean = {
            inv: {
                "score": float(r["per_investigator"][inv]["score"]),
                "acc": float(r["per_investigator"][inv]["acc"]),
                "regret": float(r["per_investigator"][inv]["regret"]),
            }
            for inv in sorted(r["per_investigator"])
        }
        row = {
            "rank": idx,
            "fitness": float(r["min_regret"]),
            "solver_score": float(r["solver_score"]),
            "solver_acc": float(r["solver_acc"]),
            "per_investigator": per_inv_clean,
            "strategy_json": validate_strategy(r["strategy_json"]),
        }
        assert list(row.keys()) == HOF_KEYS
        hof_rows.append(row)

    return hof_rows, ranked


def _public_summary_row(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": r["name"],
        "description": r.get("description", ""),
        "n_rules": r.get("n_rules", 0),
        "n_seeds": r.get("n_seeds", 0),
        "solver_score": round(float(r["solver_score"]), 6),
        "solver_ci": round(float(r["solver_ci"]), 6),
        "solver_acc": round(float(r["solver_acc"]), 6),
        "solver_none_rate": round(float(r["solver_none_rate"]), 6),
        "solver_mean_day": round(float(r["solver_mean_day"]), 4),
        "min_regret": round(float(r["min_regret"]), 6),
        "core_min_regret": round(float(r["core_min_regret"]), 6),
        "mean_regret": round(float(r["mean_regret"]), 6),
        "min_regret_gain": round(float(r.get("min_regret_gain", 0.0)), 6),
        "core_regret_gain": round(float(r.get("core_regret_gain", 0.0)), 6),
        "strongest_investigator": r["strongest_investigator"],
        "per_investigator": {
            inv: {
                "score": round(float(v["score"]), 6),
                "acc": round(float(v["acc"]), 6),
                "regret": round(float(v["regret"]), 6),
                "regret_ci": round(float(v["regret_ci"]), 6),
            }
            for inv, v in sorted(r["per_investigator"].items())
        },
        "logs_only_score": round(float(r["logs_only_score"]), 6),
        "logs_only_acc": round(float(r["logs_only_acc"]), 6),
        "accuse_most_logs_score": round(float(r["accuse_most_logs_score"]), 6),
        "accuse_most_logs_acc": round(float(r["accuse_most_logs_acc"]), 6),
        "do_nothing_score": round(float(r["do_nothing_score"]), 6),
        "stop_early_score": round(float(r["stop_early_score"]), 6),
        "guess_day1_score": round(float(r["guess_day1_score"]), 6),
        "outcome_hash": r["outcome_hash"],
        "behavior_hash": r["behavior_hash"],
        "canon_hash": r["canon_hash"],
        "strict_s7": bool(r.get("strict_s7", False)),
        "fairness_passed": bool(r.get("fairness_passed", False)),
        "beats_default_regret": bool(r.get("beats_default_regret", False)),
        "distinct_from_default": bool(r.get("distinct_from_default", False)),
        "all_gates_passed": bool(r.get("all_gates_passed", False)),
    }


def write_hof_v14(
    hof_rows: Sequence[dict[str, Any]],
    hof_path: str | Path,
    meta: dict[str, Any],
) -> Path:
    """Write hall_of_fame_v1.4.jsonl with exact HOF_KEYS order and companion .meta.json."""
    out_path = Path(hof_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for idx, row in enumerate(hof_rows, start=1):
        ordered = {
            "rank": int(idx),
            "fitness": float(row["fitness"]),
            "solver_score": float(row["solver_score"]),
            "solver_acc": float(row["solver_acc"]),
            "per_investigator": row["per_investigator"],
            "strategy_json": validate_strategy(row["strategy_json"]),
        }
        if list(ordered.keys()) != HOF_KEYS:
            raise ValueError("HOF key order mismatch")
        MoleStrategy.from_json(ordered["strategy_json"])
        lines.append(json.dumps(ordered))
    out_path.write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")

    meta_str = str(out_path)
    if meta_str.endswith(".jsonl"):
        meta_path = Path(meta_str[:-6] + ".meta.json")
    else:
        meta_path = Path(meta_str + ".meta.json")
    full_meta = {**meta, "n_survivors": len(lines)}
    meta_path.write_text(json.dumps(full_meta, indent=2) + "\n", encoding="utf-8")
    return meta_path


def _format_table(eval_result: dict[str, Any], survivor_names: set[str]) -> list[str]:
    invs = eval_result["investigators"]
    headers = [
        "strategy",
        "solver_score",
        "solver_acc",
        *[f"{inv}_score" for inv in invs],
        *[f"{inv}_regret" for inv in invs],
        "min_regret",
        "gain_vs_def",
        "logs_only_acc",
        "do_nothing",
        "stop_early",
        "guess_day1",
        "outcome_hash",
        "behavior_hash",
        "fairness",
        "selected",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "---|" * len(headers),
    ]
    for r in eval_result["all_rows"]:
        if not r.get("dsl_valid"):
            continue
        is_sel = "yes" if r["name"] in survivor_names else "no"
        fair = "PASS" if r.get("fairness_passed") else "FAIL"
        cells = [
            f"`{r['name']}`",
            f"{r['solver_score']:.3f} +/- {r['solver_ci']:.3f}",
            f"{r['solver_acc']:.3f}",
            *[f"{r['per_investigator'][inv]['score']:.3f}" for inv in invs],
            *[f"{r['per_investigator'][inv]['regret']:.3f}" for inv in invs],
            f"{r['min_regret']:.3f}",
            f"{r.get('min_regret_gain', 0.0):+.3f}",
            f"{r['logs_only_acc']:.3f}",
            f"{r['do_nothing_score']:.2f}",
            f"{r['stop_early_score']:.2f}",
            f"{r['guess_day1_score']:.3f}",
            f"`{r['outcome_hash']}`",
            f"`{r['behavior_hash'][:10]}`",
            fair,
            is_sel,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def render_markdown_report(
    dev_eval: dict[str, Any] | None,
    heldout_eval: dict[str, Any],
    survivor_rows: Sequence[dict[str, Any]],
    ranked_survivors: Sequence[dict[str, Any]],
    code_sha: str,
    workers: int,
) -> str:
    h1 = MD_H
    h2 = MD_H * 2
    survivor_names = {r["name"] for r in ranked_survivors}
    h_seeds = heldout_eval["seeds"]
    gates = heldout_eval["gates"]
    base_h = heldout_eval["default"]

    out: list[str] = [
        f"{h1} Mole Strategy Benchmark and Hall of Fame (v1.4 hard)",
        "",
        f"- Code SHA: `{code_sha}` | Tiers version: `{heldout_eval['tiers_version']}` | Tier: `{heldout_eval['tier']}` | Workers: `{workers}`",
        (
            f"- Seed hygiene: dev tuning slice `{dev_eval['seeds'][0]}..{dev_eval['seeds'][-1]}` (`n={len(dev_eval['seeds'])}`), "
            f"held-out slice `{h_seeds[0]}..{h_seeds[-1]}` (`n={len(h_seeds)}`), zero overlap, seeds `0..59`, `30000..30199`, and `800000+` untouched."
            if dev_eval is not None
            else f"- Seed hygiene: held-out slice `{h_seeds[0]}..{h_seeds[-1]}` (`n={len(h_seeds)}`), seeds `0..59`, `30000..30199`, and `800000+` untouched."
        ),
        (
            f"- Strict CONTRACT section 7 + fairness gate on held-out: `solver_acc >= {gates['min_solver_acc']:.2f}`, "
            f"`solver_score >= {gates['min_solver_ratio']:.2f} * default_solver_score` "
            f"(`>= {gates['min_solver_ratio'] * base_h['solver_score']:.3f}`), "
            f"`min_regret > default_min_regret` (`> {base_h['min_regret']:.3f}`), "
            f"`logs_only_acc <= {gates['max_logs_acc']:.2f}`, `do_nothing == 0`, `stop_early == 0`, `guess_day1 < 0`, "
            "zero tool leaks, exact replay determinism, and 100% distinct outcome and behavior hashes."
        ),
        f"- Selected Hall of Fame survivors (`data/forge/hall_of_fame_v1.4.jsonl`): **{len(survivor_rows)}** behavior-distinct strategies.",
        "",
        f"{h2} 1. Held-out Evaluation (`{h_seeds[0]}..{h_seeds[-1]}`, `n={len(h_seeds)}`)",
        "",
        *_format_table(heldout_eval, survivor_names),
    ]

    if dev_eval is not None:
        d_seeds = dev_eval["seeds"]
        out.extend(
            [
                "",
                f"{h2} 2. Dev Tuning Benchmark (`{d_seeds[0]}..{d_seeds[-1]}`, `n={len(d_seeds)}`)",
                "",
                *_format_table(dev_eval, survivor_names),
            ]
        )

    sec_num = 3 if dev_eval is not None else 2
    out.extend(
        [
            "",
            f"{h2} {sec_num}. Selected Hall of Fame Archetypes",
            "",
        ]
    )
    for idx, r in enumerate(ranked_survivors, start=1):
        out.append(
            f"{idx}. **`{r['name']}`** (rank {idx}, outcome `{r['outcome_hash']}`, behavior `{r['behavior_hash'][:10]}`, "
            f"held-out `min_regret={r['min_regret']:.3f}` vs default `{base_h['min_regret']:.3f}`, "
            f"`solver_score={r['solver_score']:.3f}`, `solver_acc={r['solver_acc']:.3f}`, "
            f"`logs_only_acc={r['logs_only_acc']:.3f}`): {r['description']}"
        )

    return "\n".join(out) + "\n"


def load_extra_candidates(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    items: list[Any]
    if p.suffix == ".jsonl":
        items = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    else:
        parsed = json.loads(text)
        items = parsed if isinstance(parsed, list) else [parsed]
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        sj = item.get("strategy_json", item.get("strategy", item if "rules" in item or "default" in item else None))
        if sj is None:
            continue
        name = str(item.get("name") or sj.get("name") or f"cand_{idx}")
        desc = str(item.get("description") or f"Loaded from {p.name}")
        out.append({"name": name, "description": desc, "strategy_json": sj})
    return out


def discover_library_candidates() -> list[dict[str, Any]]:
    """Load handcrafted transcript-grounded strategies from canary.mole.strategies when available."""
    try:
        mod = importlib.import_module("canary.mole.strategies")
    except ImportError:
        return []
    out: list[dict[str, Any]] = []
    specs = getattr(mod, "STRATEGY_SPECS", None)
    if isinstance(specs, dict):
        for spec in specs.values():
            sj = spec.to_json() if hasattr(spec, "to_json") else getattr(spec, "strategy_json", None)
            if isinstance(sj, dict):
                desc = str(getattr(spec, "empirical_finding", "") or "Library strategy")
                out.append({"name": str(spec.name), "description": desc, "strategy_json": sj})
        if out:
            return out
    for attr in ("list_strategies", "all_strategies", "STRATEGIES"):
        obj = getattr(mod, attr, None)
        if obj is None:
            continue
        raw = obj() if callable(obj) else obj
        entries = raw.values() if isinstance(raw, dict) else raw
        for idx, item in enumerate(entries, start=1):
            if isinstance(item, MoleStrategy):
                out.append({"name": item.name or f"lib_{idx}", "description": "Library strategy", "strategy_json": item.to_json()})
            elif isinstance(item, dict):
                sj = item.get("strategy_json", item if "rules" in item or "default" in item else None)
                if sj is not None:
                    out.append(
                        {
                            "name": str(item.get("name") or sj.get("name") or f"lib_{idx}"),
                            "description": str(item.get("description") or "Library strategy"),
                            "strategy_json": sj,
                        }
                    )
        if out:
            break
    return out


def _git_short_sha() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() or "unknown"


def run_benchmark(
    dev_seeds: Sequence[int] | None,
    heldout_seeds: Sequence[int],
    tier: str = "hard",
    workers: int = 1,
    top_k: int = 4,
    min_solver_acc: float = FEASIBLE_SOLVER_ACC,
    min_solver_ratio: float = FEASIBLE_SOLVER_RATIO,
    max_logs_acc: float = 0.10,
    include_proxies: bool = True,
    include_library: bool = True,
    extra_candidates_path: str | Path | None = None,
    hof_out: str | Path | None = None,
    report_out: str | Path | None = None,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    validate_benchmark_seeds(dev_seeds, heldout_seeds)

    candidates: list[dict[str, Any]] = [dict(c) for c in BUILTIN_V14_CANDIDATES]
    seen_names = {c["name"] for c in candidates}
    if include_library:
        for c in discover_library_candidates():
            if c["name"] not in seen_names and c["name"] != "default_v0":
                seen_names.add(c["name"])
                candidates.append(c)
    if extra_candidates_path is not None:
        for c in load_extra_candidates(extra_candidates_path):
            if c["name"] not in seen_names:
                seen_names.add(c["name"])
                candidates.append(c)

    investigators = list(CORE_INVESTIGATORS)
    if include_proxies:
        for pname in sorted(discover_proxy_factories()):
            if pname not in investigators:
                investigators.append(pname)

    dev_eval: dict[str, Any] | None = None
    if dev_seeds is not None:
        dev_eval = evaluate_suite(
            candidates,
            seeds=dev_seeds,
            tier=tier,
            investigators=investigators,
            workers=workers,
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
            max_logs_acc=max_logs_acc,
        )

    heldout_eval = evaluate_suite(
        candidates,
        seeds=heldout_seeds,
        tier=tier,
        investigators=investigators,
        workers=workers,
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
        max_logs_acc=max_logs_acc,
    )

    hof_rows, ranked_survivors = select_hof_survivors(heldout_eval, top_k=top_k, dev_eval=dev_eval)
    sha = _git_short_sha()
    h_list = list(heldout_seeds)
    d_list = list(dev_seeds) if dev_seeds is not None else None

    meta_payload: dict[str, Any] = {
        "code_sha": sha,
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seeds": f"{h_list[0]}:{h_list[-1] + 1}",
        "heldout_seeds": f"{h_list[0]}-{h_list[-1]}",
        "n_heldout_seeds": len(h_list),
        "dev_seeds": f"{d_list[0]}-{d_list[-1]}" if d_list else None,
        "n_dev_seeds": len(d_list) if d_list else 0,
        "forbidden_seed_ranges": ["0-29", "30-44", "45-59", "30000-30199", "800000+", "900000+"],
        "workers": int(workers),
        "investigators": investigators,
        "feasibility": (
            f"solver_acc >= {min_solver_acc} AND solver_score >= {min_solver_ratio} * default_solver_score "
            f"AND min_regret > default_min_regret AND core_min_regret > default_core_min_regret "
            f"AND logs_only_acc <= {max_logs_acc} AND accuse_most_logs_acc <= {max_logs_acc} "
            "AND do_nothing == 0 AND stop_early == 0 AND guess_day1 < 0 (required on both dev and held-out slices)"
        ),
        "dedupe_method": (
            f"outcome + behavior: sha256[:10] of (agent, seed, day, event, doc_id|employee) for leak/framed ledger "
            f"events under do_nothing and solver on {tier} seeds {h_list[0]}..{h_list[-1]} AND "
            "canary.mole.evolve_v14.behavior_hash across 64 representative MoleViews"
        ),
        "outcome_groups": heldout_eval["outcome_groups"],
        "behavior_groups": heldout_eval["behavior_groups"],
        "survivor_names": [r["name"] for r in ranked_survivors],
        "survivor_outcome_hashes": {r["name"]: r["outcome_hash"] for r in ranked_survivors},
        "survivor_behavior_hashes": {r["name"]: r["behavior_hash"] for r in ranked_survivors},
        "default_heldout": _public_summary_row(heldout_eval["default"]),
        "default_dev": _public_summary_row(dev_eval["default"]) if dev_eval is not None else None,
        "heldout_candidates": [_public_summary_row(r) for r in heldout_eval["candidates"] if r.get("dsl_valid")],
        "dev_candidates": (
            [_public_summary_row(r) for r in dev_eval["candidates"] if r.get("dsl_valid")]
            if dev_eval is not None
            else None
        ),
    }

    if hof_out is not None:
        write_hof_v14(hof_rows, hof_out, meta_payload)

    md_text = render_markdown_report(
        dev_eval=dev_eval,
        heldout_eval=heldout_eval,
        survivor_rows=hof_rows,
        ranked_survivors=ranked_survivors,
        code_sha=sha,
        workers=workers,
    )
    if report_out is not None:
        rp = Path(report_out)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(md_text, encoding="utf-8")

    return {
        "dev_eval": dev_eval,
        "heldout_eval": heldout_eval,
        "hof_rows": hof_rows,
        "ranked_survivors": ranked_survivors,
        "meta": meta_payload,
        "markdown": md_text,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Benchmark v1.4 Mole DSL strategies on dev and held-out seeds with strict section 7 gates."
    )
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--dev-seeds", default="10000-10019")
    ap.add_argument("--skip-dev", action="store_true")
    ap.add_argument("--heldout-seeds", default="6200-6219")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--top-k", type=int, default=4)
    ap.add_argument("--min-solver-acc", type=float, default=FEASIBLE_SOLVER_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=FEASIBLE_SOLVER_RATIO)
    ap.add_argument("--max-logs-acc", type=float, default=0.10)
    ap.add_argument("--no-proxies", action="store_true")
    ap.add_argument("--include-library", action="store_true", default=True)
    ap.add_argument("--no-library", action="store_true")
    ap.add_argument("--candidates", default=None)
    ap.add_argument("--hof-out", default=str(ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"))
    ap.add_argument("--report-out", default=None)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args(argv)

    if not args.verbose:
        logging.getLogger("canary.solver").setLevel(logging.ERROR)

    t0 = time.monotonic()
    dev_list = None if args.skip_dev else parse_seed_spec(args.dev_seeds)
    heldout_list = parse_seed_spec(args.heldout_seeds)

    res = run_benchmark(
        dev_seeds=dev_list,
        heldout_seeds=heldout_list,
        tier=args.tier,
        workers=args.workers,
        top_k=args.top_k,
        min_solver_acc=args.min_solver_acc,
        min_solver_ratio=args.min_solver_ratio,
        max_logs_acc=args.max_logs_acc,
        include_proxies=not args.no_proxies,
        include_library=bool(args.include_library and not args.no_library),
        extra_candidates_path=args.candidates,
        hof_out=args.hof_out,
        report_out=args.report_out,
    )
    elapsed = time.monotonic() - t0
    summary = {
        "elapsed_s": round(elapsed, 2),
        "tier": args.tier,
        "workers": args.workers,
        "n_dev_seeds": len(dev_list) if dev_list else 0,
        "n_heldout_seeds": len(heldout_list),
        "n_survivors": len(res["hof_rows"]),
        "survivors": [
            {
                "rank": r["rank"],
                "name": s["name"],
                "fitness": round(r["fitness"], 4),
                "core_min_regret": round(s["core_min_regret"], 4),
                "solver_score": round(r["solver_score"], 4),
                "solver_acc": round(r["solver_acc"], 4),
                "logs_only_acc": round(s["logs_only_acc"], 4),
                "accuse_most_logs_acc": round(s["accuse_most_logs_acc"], 4),
                "outcome_hash": s["outcome_hash"],
                "behavior_hash": s["behavior_hash"][:10],
            }
            for r, s in zip(res["hof_rows"], res["ranked_survivors"])
        ],
        "hof_out": args.hof_out,
        "report_out": args.report_out,
    }
    print(json.dumps(summary, indent=2))
    return 0 if res["hof_rows"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
