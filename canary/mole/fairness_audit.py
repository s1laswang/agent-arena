"""Automated 7-check fairness, determinism, baseline-integrity, and solver-catchability audit for Mole strategies."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from canary import rules as canary_rules
from canary.baselines import (
    AccuseMostLogs,
    DoNothing,
    GrokTactics,
    Heuristic,
    LogsOnly,
    RandomPolicy,
    StopEarly,
    StopEarlyQuit,
)
from canary.env import ERRORS as ENV_ERRORS, Env
from canary.eval import parse_seeds, run_episode
from canary.forge.investigators import HintedHeuristic
from canary.forge.rl_mole import N_FEAT, N_FRAME, N_LEAK, RLMole
from canary.forge_track import _strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy, StrategyError
from canary.rules import TIERS, tier_params
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult

CHECK_NAMES: tuple[str, ...] = (
    "dsl_valid",
    "no_tool_leak",
    "determinism",
    "zero_baselines",
    "logs_only_bounded",
    "solver_beatable",
    "regret_gain",
)
FAIRNESS_CHECK_NAMES: tuple[str, ...] = CHECK_NAMES[:6]

FORBIDDEN_LEAK_TOKENS: tuple[str, ...] = (
    "strategy_json",
    "most_recipients",
    "fewest_recipients",
    "most_restricted_peer",
    "random_peer",
    "random_seeded",
)

_DEFAULT_SEED_CACHE: dict[tuple[Any, ...], dict[str, tuple[float, bool]]] = {}


def _is_default_strategy(parsed: MoleStrategy | RLMole) -> bool:
    return (
        isinstance(parsed, MoleStrategy)
        and parsed.rules == DEFAULT_STRATEGY.rules
        and parsed.default == DEFAULT_STRATEGY.default
    )


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _normalize_seeds(seeds: str | int | Iterable[int]) -> list[int]:
    if isinstance(seeds, str):
        out = parse_seeds(seeds)
    elif isinstance(seeds, int):
        out = list(range(seeds))
    else:
        out = [int(s) for s in seeds]
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def _make_solver(tier: str) -> SolverPolicy:
    return SolverPolicy(tier if tier in TIERS else tier_params(tier))


def _clone_strategy(parsed: MoleStrategy | RLMole) -> MoleStrategy | RLMole:
    return _strategy(parsed.to_json())


def _validate_rl_mole_params(parsed: RLMole) -> None:
    expected_keys = {"W1", "b1", "Wl", "bl", "Wf", "bf"}
    if set(parsed.p) != expected_keys:
        raise ValueError(f"rl_mole params keys mismatch: {sorted(parsed.p)}")
    for k, arr in parsed.p.items():
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"rl_mole parameter {k} contains non-finite values")
    w1, b1 = parsed.p["W1"], parsed.p["b1"]
    wl, bl = parsed.p["Wl"], parsed.p["bl"]
    wf, bf = parsed.p["Wf"], parsed.p["bf"]
    if w1.ndim != 2 or w1.shape[0] != N_FEAT:
        raise ValueError(f"invalid W1 shape: {w1.shape}")
    hidden = int(w1.shape[1])
    if hidden <= 0:
        raise ValueError("rl_mole hidden dimension must be positive")
    if b1.shape != (hidden,):
        raise ValueError(f"invalid b1 shape: {b1.shape}")
    if wl.shape != (hidden, N_LEAK) or bl.shape != (N_LEAK,):
        raise ValueError(f"invalid leak head shapes: {wl.shape}, {bl.shape}")
    if wf.shape != (hidden, N_FRAME) or bf.shape != (N_FRAME,):
        raise ValueError(f"invalid frame head shapes: {wf.shape}, {bf.shape}")


def _check_dsl_valid(strategy_obj: Any) -> tuple[dict[str, Any], MoleStrategy | RLMole | None]:
    try:
        if isinstance(strategy_obj, MoleStrategy):
            if len(strategy_obj.rules) > MAX_RULES:
                raise StrategyError(f"too many rules: {len(strategy_obj.rules)} > {MAX_RULES}")
            parsed: MoleStrategy | RLMole = _strategy(strategy_obj.to_json())
        elif isinstance(strategy_obj, RLMole):
            _validate_rl_mole_params(strategy_obj)
            parsed = _strategy(strategy_obj.to_json())
        elif isinstance(strategy_obj, dict):
            if strategy_obj.get("kind") != "rl_mole":
                raw_rules = strategy_obj.get("rules", [])
                if not isinstance(raw_rules, list) or len(raw_rules) > MAX_RULES:
                    raise StrategyError("bad rules")
            parsed = _strategy(strategy_obj)
        else:
            raise StrategyError(f"unsupported strategy type: {type(strategy_obj).__name__}")

        if isinstance(parsed, MoleStrategy):
            kind = "dsl"
            n_rules: int | None = len(parsed.rules)
            if n_rules > MAX_RULES:
                raise StrategyError(f"too many rules: {n_rules} > {MAX_RULES}")
            c1 = _canonical_json(parsed.to_json())
            re_parsed = _strategy(json.loads(c1))
            c2 = _canonical_json(re_parsed.to_json())
            round_trip_ok = isinstance(re_parsed, MoleStrategy) and re_parsed == parsed and c1 == c2
        elif isinstance(parsed, RLMole):
            kind = "rl_mole"
            n_rules = None
            _validate_rl_mole_params(parsed)
            c1 = _canonical_json(parsed.to_json())
            re_parsed = _strategy(json.loads(c1))
            c2 = _canonical_json(re_parsed.to_json())
            round_trip_ok = (
                isinstance(re_parsed, RLMole)
                and re_parsed.greedy == parsed.greedy
                and re_parsed.name == parsed.name
                and c1 == c2
                and all(np.allclose(re_parsed.p[k], parsed.p[k]) for k in parsed.p)
            )
        else:
            raise StrategyError(f"unexpected parsed strategy type: {type(parsed).__name__}")

        if not round_trip_ok:
            raise StrategyError("canonical round-trip mismatch")

        digest = hashlib.sha256(c1.encode("utf-8")).hexdigest()[:16]
        rule_desc = f"rules={n_rules}/{MAX_RULES}" if n_rules is not None else "rl_mole_mlp"
        return (
            {
                "passed": True,
                "kind": kind,
                "name": str(getattr(parsed, "name", "custom")),
                "n_rules": n_rules,
                "max_rules": MAX_RULES,
                "round_trip_ok": True,
                "canonical_sha256": digest,
                "error": None,
                "summary": f"valid {kind} ({rule_desc}, round_trip=True)",
            },
            parsed,
        )
    except (StrategyError, ValueError, TypeError, KeyError, IndexError) as exc:
        return (
            {
                "passed": False,
                "kind": "invalid",
                "name": "invalid",
                "n_rules": None,
                "max_rules": MAX_RULES,
                "round_trip_ok": False,
                "canonical_sha256": None,
                "error": str(exc),
                "summary": f"invalid strategy: {exc}",
            },
            None,
        )


def _skipped_checks() -> dict[str, dict[str, Any]]:
    reason = "skipped because dsl_valid failed"
    return {
        "no_tool_leak": {
            "passed": False,
            "skipped": True,
            "episodes_checked": 0,
            "steps_checked": 0,
            "error_steps_checked": 0,
            "forbidden_tokens": list(FORBIDDEN_LEAK_TOKENS),
            "violations": [reason],
            "summary": reason,
        },
        "determinism": {
            "passed": False,
            "skipped": True,
            "n_seeds": 0,
            "ledger_matches": 0,
            "history_matches": 0,
            "mismatched_seeds": [],
            "summary": reason,
        },
        "zero_baselines": {
            "passed": False,
            "skipped": True,
            "n_seeds": 0,
            "do_nothing_scores_all_zero": False,
            "do_nothing_max_abs_score": 0.0,
            "stop_early_scores_all_zero": False,
            "stop_early_max_abs_score": 0.0,
            "guess_day1_mean_score": 0.0,
            "guess_day1_acc": 0.0,
            "summary": reason,
        },
        "logs_only_bounded": {
            "passed": False,
            "skipped": True,
            "n_seeds": 0,
            "max_logs_acc": 0.0,
            "logs_only_acc": 0.0,
            "logs_only_mean_score": 0.0,
            "accuse_most_logs_acc": 0.0,
            "accuse_most_logs_mean_score": 0.0,
            "summary": reason,
        },
        "solver_beatable": {
            "passed": False,
            "skipped": True,
            "n_seeds": 0,
            "min_solver_acc": 0.0,
            "min_solver_score": 0.0,
            "acc": 0.0,
            "mean_score": 0.0,
            "solver_acc": 0.0,
            "solver_mean_score": 0.0,
            "accused_rate": 0.0,
            "mean_final_day": 0.0,
            "summary": reason,
        },
        "regret_gain": {
            "passed": False,
            "skipped": True,
            "n_seeds": 0,
            "min_regret_gain": None,
            "solver_score": 0.0,
            "solver_acc": 0.0,
            "investigator_scores": {},
            "investigator_accs": {},
            "max_investigator": "",
            "max_investigator_score": 0.0,
            "regret": 0.0,
            "default_solver_score": 0.0,
            "default_investigator_scores": {},
            "default_max_investigator": "",
            "default_max_investigator_score": 0.0,
            "default_regret": 0.0,
            "regret_gain": 0.0,
            "per_seed_regret": 0.0,
            "default_per_seed_regret": 0.0,
            "per_seed_regret_gain": 0.0,
            "summary": reason,
        },
    }


def _scan_env_for_leaks(env: Env, tag: str) -> tuple[int, int, list[str]]:
    violations: list[str] = []
    true_mole = str(env._world.mole)
    surfaces = [
        ("instruction", env.instruction()),
        ("tools_spec", _canonical_json(env.tools_spec())),
    ]
    for surf_name, text in surfaces:
        for tok in FORBIDDEN_LEAK_TOKENS:
            if tok in text:
                violations.append(f"{tag}:{surf_name} leaked token {tok}")

    error_steps = 0
    for step in env.history:
        blob = _canonical_json(step.result)
        for tok in FORBIDDEN_LEAK_TOKENS:
            if tok in blob:
                violations.append(f"{tag}:step[{step.t}]({step.tool}) leaked token {tok}")
        err = step.result.get("error")
        if not step.result.get("ok") or err:
            error_steps += 1
            err_str = str(err or "")
            if true_mole in err_str:
                violations.append(f"{tag}:step[{step.t}]({step.tool}) error leaked mole id {true_mole}")
            if err_str and err_str not in ENV_ERRORS:
                violations.append(f"{tag}:step[{step.t}]({step.tool}) non-canonical error string {err_str!r}")
    return len(env.history), error_steps, violations


def _run_error_probe(tier: str, seed: int, parsed: MoleStrategy | RLMole) -> tuple[int, int, list[str]]:
    env = Env(tier, seed, mole_strategy=_clone_strategy(parsed))
    true_mole = str(env._world.mole)
    innocent = next(e for e in env._ids if e != true_mole)

    env.call("unknown_tool_probe", {})
    r_mole_bad = env.call("interview", {"employee": true_mole, "topic": "invalid_topic"})
    r_inn_bad = env.call("interview", {"employee": innocent, "topic": "invalid_topic"})
    r_unres_m = env.call("unrestrict_access", {"employee": true_mole})
    r_unres_i = env.call("unrestrict_access", {"employee": innocent})
    env.call("search_messages", {"query": "*"})
    for _ in range(env.p.actions_per_day + 1):
        env.call("check_leak_feed", {})
    env.call("accuse", {"employee": innocent})
    env.call("status", {})

    steps_n, err_n, violations = _scan_env_for_leaks(env, f"error_probe:{seed}")
    if r_mole_bad.error != r_inn_bad.error:
        violations.append(f"error_probe:{seed} interview error differs between mole and innocent")
    if r_unres_m.error != r_unres_i.error:
        violations.append(f"error_probe:{seed} unrestrict error differs between mole and innocent")
    return steps_n, err_n, violations


def _summarize_seed_rows(rows: list[dict[str, tuple[float, bool]]]) -> dict[str, Any]:
    n = len(rows)
    sol_scores = [r["solver"][0] for r in rows]
    sol_score = sum(sol_scores) / n
    sol_acc = sum(r["solver"][1] for r in rows) / n
    inv_names = ("heuristic", "hinted_heuristic", "grok_tactics")
    inv_scores = {k: sum(r[k][0] for r in rows) / n for k in inv_names}
    inv_accs = {k: sum(r[k][1] for r in rows) / n for k in inv_names}
    max_inv = max(sorted(inv_scores), key=lambda k: inv_scores[k])
    max_inv_score = inv_scores[max_inv]
    regret = sol_score - max_inv_score
    per_seed_regret = (
        sum(
            sol_scores[i] - max(rows[i]["heuristic"][0], rows[i]["hinted_heuristic"][0], rows[i]["grok_tactics"][0])
            for i in range(n)
        )
        / n
    )
    return {
        "solver_score": sol_score,
        "solver_acc": sol_acc,
        "investigator_scores": inv_scores,
        "investigator_accs": inv_accs,
        "max_investigator": max_inv,
        "max_investigator_score": max_inv_score,
        "regret": regret,
        "per_seed_regret": per_seed_regret,
    }


def _eval_regret_suite(
    tier: str,
    seeds: list[int],
    parsed: MoleStrategy | RLMole,
    solver_runs: list[EpisodeResult] | None = None,
) -> tuple[dict[str, Any], list[Env]]:
    if solver_runs is None:
        solver_runs = [
            run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), _make_solver(tier))
            for s in seeds
        ]

    heuristic_envs: list[Env] = []
    rows: list[dict[str, tuple[float, bool]]] = []
    is_def = _is_default_strategy(parsed)
    tp = tier_params(tier)
    kv = bool(canary_rules.KNOWN_V_MODE)

    for i, s in enumerate(seeds):
        env_h = Env(tier, s, mole_strategy=_clone_strategy(parsed))
        heu_res = run_episode(env_h, Heuristic(seed=s))
        heuristic_envs.append(env_h)
        hh_res = run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), HintedHeuristic(seed=s))
        gt_res = run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), GrokTactics(seed=s))
        row = {
            "solver": (float(solver_runs[i].score), bool(solver_runs[i].correct)),
            "heuristic": (float(heu_res.score), bool(heu_res.correct)),
            "hinted_heuristic": (float(hh_res.score), bool(hh_res.correct)),
            "grok_tactics": (float(gt_res.score), bool(gt_res.correct)),
        }
        rows.append(row)
        if is_def:
            _DEFAULT_SEED_CACHE[(tier, s, tp, kv)] = row

    return _summarize_seed_rows(rows), heuristic_envs


def _default_regret_baseline(tier: str, seeds: list[int]) -> dict[str, Any]:
    tp = tier_params(tier)
    kv = bool(canary_rules.KNOWN_V_MODE)
    missing = [s for s in seeds if (tier, s, tp, kv) not in _DEFAULT_SEED_CACHE]
    if missing:
        _eval_regret_suite(tier, missing, DEFAULT_STRATEGY)
    rows = [_DEFAULT_SEED_CACHE[(tier, s, tp, kv)] for s in seeds]
    return _summarize_seed_rows(rows)


def audit_strategy(
    strategy_obj: Any,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(6000, 6020),
    min_solver_acc: float = 0.75,
    min_solver_score: float = 0.25,
    max_logs_acc: float = 0.20,
    min_regret_gain: float | None = None,
) -> dict[str, Any]:
    seed_list = _normalize_seeds(seeds)
    n_seeds = len(seed_list)

    c1_dsl, parsed = _check_dsl_valid(strategy_obj)
    if parsed is None:
        checks = {"dsl_valid": c1_dsl, **_skipped_checks()}
        return {
            "strategy_name": c1_dsl["name"],
            "strategy_kind": c1_dsl["kind"],
            "tier": tier,
            "n_seeds": n_seeds,
            "seeds": seed_list,
            "all_passed": False,
            "fairness_passed": False,
            "failed_checks": list(CHECK_NAMES),
            "checks": checks,
        }

    ledger_matches = 0
    history_matches = 0
    mismatched_seeds: list[int] = []
    random_envs: list[Env] = []
    for s in seed_list:
        env_a = Env(tier, s, mole_strategy=_clone_strategy(parsed))
        env_b = Env(tier, s, mole_strategy=_clone_strategy(parsed))
        run_episode(env_a, RandomPolicy(seed=s))
        run_episode(env_b, RandomPolicy(seed=s))
        random_envs.append(env_a)
        led_ok = [asdict(x) for x in env_a.ledger()] == [asdict(x) for x in env_b.ledger()]
        hist_ok = [asdict(x) for x in env_a.history] == [asdict(x) for x in env_b.history]
        if led_ok:
            ledger_matches += 1
        if hist_ok:
            history_matches += 1
        if not (led_ok and hist_ok):
            mismatched_seeds.append(s)

    det_passed = len(mismatched_seeds) == 0
    c3_det = {
        "passed": det_passed,
        "n_seeds": n_seeds,
        "ledger_matches": ledger_matches,
        "history_matches": history_matches,
        "mismatched_seeds": mismatched_seeds,
        "summary": f"ledger_matches={ledger_matches}/{n_seeds}, history_matches={history_matches}/{n_seeds}",
    }

    dn_scores: list[float] = []
    seq_scores: list[float] = []
    se_runs: list[EpisodeResult] = []
    for s in seed_list:
        dn_res = run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), DoNothing(seed=s))
        dn_scores.append(float(dn_res.score))
        seq_res = run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), StopEarlyQuit(seed=s))
        seq_scores.append(float(seq_res.score))
        se_res = run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), StopEarly(seed=s))
        se_runs.append(se_res)

    env_unfinished = Env(tier, seed_list[0], mole_strategy=_clone_strategy(parsed))
    quit_pol = StopEarlyQuit(seed=seed_list[0])
    quit_pol.reset(env_unfinished.tools_spec(), env_unfinished.instruction())
    for _ in range(3):
        tool, args = quit_pol.act(list(env_unfinished.history))
        env_unfinished.call(tool, args)
    unfinished_zero = float(env_unfinished.score()) == 0.0

    dn_all_zero = all(x == 0.0 for x in dn_scores)
    seq_all_zero = all(x == 0.0 for x in seq_scores) and unfinished_zero
    guess_mean = sum(float(r.score) for r in se_runs) / n_seeds
    guess_acc = sum(bool(r.correct) for r in se_runs) / n_seeds
    zb_passed = bool(dn_all_zero and seq_all_zero and guess_mean < 0.0)
    c4_zb = {
        "passed": zb_passed,
        "n_seeds": n_seeds,
        "do_nothing_scores_all_zero": dn_all_zero,
        "do_nothing_max_abs_score": max((abs(x) for x in dn_scores), default=0.0),
        "stop_early_scores_all_zero": seq_all_zero,
        "stop_early_max_abs_score": max(
            [abs(float(env_unfinished.score())), *(abs(x) for x in seq_scores)],
        ),
        "guess_day1_mean_score": guess_mean,
        "guess_day1_acc": guess_acc,
        "summary": (
            f"do_nothing_zero={dn_all_zero}, stop_early_zero={seq_all_zero}, "
            f"guess_day1_mean={guess_mean:.4f}"
        ),
    }

    lo_runs = [
        run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), LogsOnly(seed=s))
        for s in seed_list
    ]
    aml_runs = [
        run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), AccuseMostLogs(seed=s))
        for s in seed_list
    ]
    lo_acc = sum(bool(r.correct) for r in lo_runs) / n_seeds
    lo_mean = sum(float(r.score) for r in lo_runs) / n_seeds
    aml_acc = sum(bool(r.correct) for r in aml_runs) / n_seeds
    aml_mean = sum(float(r.score) for r in aml_runs) / n_seeds
    logs_passed = bool(
        lo_acc <= max_logs_acc
        and lo_mean < 0.0
        and aml_acc <= max_logs_acc
        and aml_mean < 0.0
    )
    c5_logs = {
        "passed": logs_passed,
        "n_seeds": n_seeds,
        "max_logs_acc": float(max_logs_acc),
        "logs_only_acc": lo_acc,
        "logs_only_mean_score": lo_mean,
        "accuse_most_logs_acc": aml_acc,
        "accuse_most_logs_mean_score": aml_mean,
        "summary": (
            f"logs_only(acc={lo_acc:.3f}, score={lo_mean:.3f}), "
            f"accuse_most_logs(acc={aml_acc:.3f}, score={aml_mean:.3f})"
        ),
    }

    solver_runs = [
        run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), _make_solver(tier))
        for s in seed_list
    ]
    sol_acc = sum(bool(r.correct) for r in solver_runs) / n_seeds
    sol_mean = sum(float(r.score) for r in solver_runs) / n_seeds
    sol_accused_rate = sum(r.end_reason == "accused" for r in solver_runs) / n_seeds
    sol_mean_day = sum(float(r.final_day) for r in solver_runs) / n_seeds
    sol_passed = bool(sol_acc >= min_solver_acc and sol_mean >= min_solver_score)
    c6_solver = {
        "passed": sol_passed,
        "n_seeds": n_seeds,
        "min_solver_acc": float(min_solver_acc),
        "min_solver_score": float(min_solver_score),
        "acc": sol_acc,
        "mean_score": sol_mean,
        "solver_acc": sol_acc,
        "solver_mean_score": sol_mean,
        "accused_rate": sol_accused_rate,
        "mean_final_day": sol_mean_day,
        "summary": (
            f"solver_acc={sol_acc:.3f} (min {min_solver_acc:.2f}), "
            f"solver_mean_score={sol_mean:.3f} (min {min_solver_score:.2f})"
        ),
    }

    strat_regret_metrics, heuristic_envs = _eval_regret_suite(
        tier, seed_list, parsed, solver_runs=solver_runs
    )
    def_metrics = _default_regret_baseline(tier, seed_list)
    regret = float(strat_regret_metrics["regret"])
    def_regret = float(def_metrics["regret"])
    gain = regret - def_regret
    per_seed_regret = float(strat_regret_metrics["per_seed_regret"])
    def_per_seed_regret = float(def_metrics["per_seed_regret"])
    per_seed_gain = per_seed_regret - def_per_seed_regret

    if min_regret_gain is None:
        regret_passed = bool(regret > 0.0 and gain > 0.0)
    else:
        regret_passed = bool(regret > 0.0 and gain >= float(min_regret_gain))

    c7_regret = {
        "passed": regret_passed,
        "n_seeds": n_seeds,
        "min_regret_gain": None if min_regret_gain is None else float(min_regret_gain),
        "solver_score": float(strat_regret_metrics["solver_score"]),
        "solver_acc": float(strat_regret_metrics["solver_acc"]),
        "investigator_scores": dict(strat_regret_metrics["investigator_scores"]),
        "investigator_accs": dict(strat_regret_metrics["investigator_accs"]),
        "max_investigator": str(strat_regret_metrics["max_investigator"]),
        "max_investigator_score": float(strat_regret_metrics["max_investigator_score"]),
        "regret": regret,
        "default_solver_score": float(def_metrics["solver_score"]),
        "default_investigator_scores": dict(def_metrics["investigator_scores"]),
        "default_max_investigator": str(def_metrics["max_investigator"]),
        "default_max_investigator_score": float(def_metrics["max_investigator_score"]),
        "default_regret": def_regret,
        "regret_gain": gain,
        "per_seed_regret": per_seed_regret,
        "default_per_seed_regret": def_per_seed_regret,
        "per_seed_regret_gain": per_seed_gain,
        "summary": (
            f"regret={regret:.4f} vs default={def_regret:.4f} "
            f"(gain={gain:+.4f}, strongest={strat_regret_metrics['max_investigator']})"
        ),
    }

    leak_violations: list[str] = []
    steps_checked = 0
    error_steps_checked = 0
    for s, env_r in zip(seed_list, random_envs):
        st_n, er_n, viol = _scan_env_for_leaks(env_r, f"random:{s}")
        steps_checked += st_n
        error_steps_checked += er_n
        leak_violations.extend(viol)
    for s, env_h in zip(seed_list, heuristic_envs):
        st_n, er_n, viol = _scan_env_for_leaks(env_h, f"heuristic:{s}")
        steps_checked += st_n
        error_steps_checked += er_n
        leak_violations.extend(viol)
    pr_steps, pr_errs, pr_viol = _run_error_probe(tier, seed_list[0], parsed)
    steps_checked += pr_steps
    error_steps_checked += pr_errs
    leak_violations.extend(pr_viol)
    episodes_checked = len(random_envs) + len(heuristic_envs) + 1
    no_leak_passed = len(leak_violations) == 0
    c2_leak = {
        "passed": no_leak_passed,
        "episodes_checked": episodes_checked,
        "steps_checked": steps_checked,
        "error_steps_checked": error_steps_checked,
        "forbidden_tokens": list(FORBIDDEN_LEAK_TOKENS),
        "violations": leak_violations,
        "summary": (
            f"episodes={episodes_checked}, steps={steps_checked}, "
            f"errors_checked={error_steps_checked}, violations={len(leak_violations)}"
        ),
    }

    checks: dict[str, dict[str, Any]] = {
        "dsl_valid": c1_dsl,
        "no_tool_leak": c2_leak,
        "determinism": c3_det,
        "zero_baselines": c4_zb,
        "logs_only_bounded": c5_logs,
        "solver_beatable": c6_solver,
        "regret_gain": c7_regret,
    }
    fairness_passed = all(checks[k]["passed"] for k in FAIRNESS_CHECK_NAMES)
    all_passed = all(checks[k]["passed"] for k in CHECK_NAMES)
    return {
        "strategy_name": c1_dsl["name"],
        "strategy_kind": c1_dsl["kind"],
        "tier": tier,
        "n_seeds": n_seeds,
        "seeds": seed_list,
        "all_passed": all_passed,
        "fairness_passed": fairness_passed,
        "failed_checks": [k for k in CHECK_NAMES if not checks[k]["passed"]],
        "checks": checks,
    }


def audit_hof(
    hof_path: str | Path,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(6000, 6020),
    min_solver_acc: float = 0.75,
    min_solver_score: float = 0.25,
    max_logs_acc: float = 0.20,
    min_regret_gain: float | None = None,
) -> dict[str, Any]:
    path = Path(hof_path)
    if not path.exists():
        raise FileNotFoundError(f"hall of fame file not found: {path}")
    seed_list = _normalize_seeds(seeds)
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return {
            "hof_path": str(path),
            "tier": tier,
            "n_seeds": len(seed_list),
            "seeds": seed_list,
            "n_strategies": 0,
            "n_passed": 0,
            "n_fairness_passed": 0,
            "all_passed": False,
            "fairness_passed": False,
            "check_pass_counts": {k: 0 for k in CHECK_NAMES},
            "strategies": [],
            "error": "empty hall of fame",
        }

    results: list[dict[str, Any]] = []
    for idx, ln in enumerate(lines):
        rank: Any = idx + 1
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            sj: Any = None
        else:
            if isinstance(row, dict):
                rank = row.get("rank", idx + 1)
                if "strategy_json" in row or "strategy" in row:
                    sj = row.get("strategy_json", row.get("strategy"))
                elif "rules" in row or "default" in row or row.get("kind") == "rl_mole":
                    sj = row
                else:
                    sj = None
            else:
                sj = None

        res = audit_strategy(
            sj,
            tier=tier,
            seeds=seed_list,
            min_solver_acc=min_solver_acc,
            min_solver_score=min_solver_score,
            max_logs_acc=max_logs_acc,
            min_regret_gain=min_regret_gain,
        )
        res["index"] = idx
        res["rank"] = rank
        results.append(res)

    n_strategies = len(results)
    n_passed = sum(1 for r in results if r["all_passed"])
    n_fairness = sum(1 for r in results if r["fairness_passed"])
    check_counts = {
        k: sum(1 for r in results if r["checks"][k]["passed"])
        for k in CHECK_NAMES
    }
    return {
        "hof_path": str(path),
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "n_strategies": n_strategies,
        "n_passed": n_passed,
        "n_fairness_passed": n_fairness,
        "all_passed": n_strategies > 0 and n_passed == n_strategies,
        "fairness_passed": n_strategies > 0 and n_fairness == n_strategies,
        "check_pass_counts": check_counts,
        "strategies": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.fairness_audit")
    ap.add_argument("--hof", type=Path, default=None, help="path to hall-of-fame JSONL file")
    ap.add_argument("--strategy", default=None, help="path to strategy JSON file or inline JSON string")
    ap.add_argument("--default", action="store_true", help="audit DEFAULT_STRATEGY")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="6000-6039")
    ap.add_argument("--min-solver-acc", type=float, default=0.75)
    ap.add_argument("--min-solver-score", type=float, default=0.25)
    ap.add_argument("--max-logs-acc", type=float, default=0.20)
    ap.add_argument("--min-regret-gain", type=float, default=None)
    ap.add_argument("--out", type=Path, default=None, help="optional path to save audit JSON")
    args = ap.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    if args.hof is not None:
        report = audit_hof(
            args.hof,
            tier=args.tier,
            seeds=seeds,
            min_solver_acc=args.min_solver_acc,
            min_solver_score=args.min_solver_score,
            max_logs_acc=args.max_logs_acc,
            min_regret_gain=args.min_regret_gain,
        )
    elif args.strategy is not None:
        strat_path = Path(args.strategy)
        raw_text = strat_path.read_text(encoding="utf-8") if strat_path.is_file() else args.strategy
        strat_obj = json.loads(raw_text)
        if isinstance(strat_obj, dict) and ("strategy_json" in strat_obj or "strategy" in strat_obj):
            strat_obj = strat_obj.get("strategy_json", strat_obj.get("strategy"))
        report = audit_strategy(
            strat_obj,
            tier=args.tier,
            seeds=seeds,
            min_solver_acc=args.min_solver_acc,
            min_solver_score=args.min_solver_score,
            max_logs_acc=args.max_logs_acc,
            min_regret_gain=args.min_regret_gain,
        )
    elif args.default:
        report = audit_strategy(
            DEFAULT_STRATEGY,
            tier=args.tier,
            seeds=seeds,
            min_solver_acc=args.min_solver_acc,
            min_solver_score=args.min_solver_score,
            max_logs_acc=args.max_logs_acc,
            min_regret_gain=args.min_regret_gain,
        )
    else:
        ap.error("provide one of --hof, --strategy, or --default")
        return 2

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
