from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np

from canary import rules as canary_rules
from canary.analysis.gap import mean_ci
from canary.baselines import (
    AccuseMostLogs,
    DoNothing,
    LogsOnly,
    RandomPolicy,
    StopEarly,
    StopEarlyQuit,
)
from canary.env import ERRORS as ENV_ERRORS, Env
from canary.eval import parse_seeds, run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.rl_mole import N_FEAT, N_FRAME, N_LEAK, RLMole
from canary.forge_track import _strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy, StrategyError
from canary.rules import TIERS, TierParams, tier_params
from canary.solver.policy import SolverPolicy
from canary.solver.regret import attribute as attribute_step_regret
from canary.types import EpisodeResult, Step

__all__ = [
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MIN_PAIRED_REGRET",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "DEFAULT_MIN_SOLVER_SCORE",
    "DROP_REASONS",
    "FORBIDDEN_SIDE_CHANNEL_TOKENS",
    "GATE_NAMES",
    "PublicToolFirewall",
    "audit_beatability",
    "audit_hof_beatability",
    "check_anti_side_channel",
    "check_blind_diligence",
    "evaluate_candidate",
    "filter_candidates",
    "luck_adjusted_episode_score",
    "main",
    "summarize_candidates",
]

DEFAULT_MIN_SOLVER_ACC: float = 0.85
DEFAULT_MIN_SOLVER_SCORE: float = 0.25
DEFAULT_MIN_SOLVER_RATIO: float = 0.50
DEFAULT_MAX_LOGS_ACC: float = 0.20
DEFAULT_MIN_PAIRED_REGRET: float = 0.0

GATE_NAMES: tuple[str, ...] = (
    "valid_strategy",
    "anti_side_channel",
    "blind_diligence",
    "solver_beatable",
    "paired_regret",
)

DROP_REASONS: tuple[str, ...] = (
    "invalid_strategy",
    "side_channel",
    "blind_diligence_wins",
    "unbeatable",
    "no_gap",
    "solver_not_better",
)

FORBIDDEN_SIDE_CHANNEL_TOKENS: tuple[str, ...] = (
    "strategy_json",
    "most_recipients",
    "fewest_recipients",
    "most_restricted_peer",
    "random_peer",
    "random_seeded",
    "MoleView",
    "select_weights",
    "_world",
)

_DEFAULT_PAIRED_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


class PublicToolFirewall:
    __slots__ = ("_call_fn", "_done_fn", "_hist_fn", "_ins_fn", "_res_fn", "_score_fn", "_spec_fn")

    def __init__(self, env: Env):
        object.__setattr__(self, "_spec_fn", env.tools_spec)
        object.__setattr__(self, "_ins_fn", env.instruction)
        object.__setattr__(self, "_done_fn", lambda: bool(env.done))
        object.__setattr__(self, "_hist_fn", lambda: list(env.history))
        object.__setattr__(self, "_call_fn", env.call)
        object.__setattr__(self, "_score_fn", env.score)
        object.__setattr__(self, "_res_fn", env.result)

    def tools_spec(self) -> list[dict[str, Any]]:
        return list(self._spec_fn())

    def instruction(self) -> str:
        return str(self._ins_fn())

    @property
    def done(self) -> bool:
        return bool(self._done_fn())

    @property
    def history(self) -> list[Step]:
        return list(self._hist_fn())

    def call(self, tool: str, args: dict[str, Any]):
        return self._call_fn(tool, args)

    def score(self) -> float:
        return float(self._score_fn())

    def result(self, agent_name: str) -> EpisodeResult:
        return self._res_fn(agent_name)


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


def _is_default_strategy(parsed: MoleStrategy | RLMole) -> bool:
    return (
        isinstance(parsed, MoleStrategy)
        and parsed.rules == DEFAULT_STRATEGY.rules
        and parsed.default == DEFAULT_STRATEGY.default
    )


def _validate_rl_mole_params(parsed: RLMole) -> None:
    expected_keys = {"W1", "b1", "Wl", "bl", "Wf", "bf"}
    if set(parsed.p) != expected_keys:
        raise ValueError(f"rl_mole params keys mismatch: {sorted(parsed.p)}")
    for key, arr in parsed.p.items():
        if not np.all(np.isfinite(arr)):
            raise ValueError(f"rl_mole parameter {key} contains non-finite values")
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


def _validate_strategy_input(strategy_obj: Any) -> tuple[dict[str, Any], MoleStrategy | RLMole | None]:
    try:
        if isinstance(strategy_obj, MoleStrategy):
            if len(strategy_obj.rules) > MAX_RULES:
                raise StrategyError(f"too many rules: {len(strategy_obj.rules)} > {MAX_RULES}")
            parsed: MoleStrategy | RLMole = _strategy(strategy_obj.to_json())
        elif isinstance(strategy_obj, RLMole):
            _validate_rl_mole_params(strategy_obj)
            parsed = _strategy(strategy_obj.to_json())
        elif isinstance(strategy_obj, dict):
            payload = strategy_obj.get("strategy_json", strategy_obj.get("strategy", strategy_obj))
            if not isinstance(payload, dict):
                raise StrategyError("strategy payload must be a dict")
            if payload.get("kind") != "rl_mole":
                raw_rules = payload.get("rules", [])
                if not isinstance(raw_rules, list) or len(raw_rules) > MAX_RULES:
                    raise StrategyError("bad rules")
            parsed = _strategy(payload)
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
            },
            None,
        )


def luck_adjusted_episode_score(
    episode: EpisodeResult,
    params: TierParams | None = None,
) -> tuple[float, float | None]:
    p = params or tier_params(episode.tier)
    if episode.end_reason != "accused" or not episode.accused:
        return 0.0, None
    sp = SolverPolicy(p)
    accuse_idx = len(episode.steps)
    for idx, st in enumerate(episode.steps):
        if st.tool == "accuse":
            accuse_idx = idx
            break
    for prev in episode.steps[:accuse_idx]:
        sp._ingest(prev)
    sp.seen = accuse_idx
    if not sp.obs.employees:
        sp.obs.employees = [f"e{i:02d}" for i in range(p.n_employees)]
    post = sp.belief()
    p_accused = float(post.get(episode.accused, 0.0))
    raw_v = (episode.meta or {}).get("V")
    if raw_v is None:
        true_v = max(0.0, float(episode.score)) if episode.correct else float(sp.expected_true_V())
    else:
        true_v = round(max(0.0, float(raw_v)), 10)
    wrong_score = float(p.wrong_accusation_score)
    luck_adj = p_accused * true_v + (1.0 - p_accused) * wrong_score
    return float(luck_adj), p_accused


def _scan_episode_surfaces(
    instruction: str,
    tools_spec: list[dict[str, Any]],
    steps: list[Step],
    true_mole: str | None,
    allowed_tools: set[str],
    tag: str,
) -> tuple[int, int, list[str]]:
    violations: list[str] = []
    spec_blob = _canonical_json(tools_spec)
    for surf_name, text in (("instruction", instruction), ("tools_spec", spec_blob)):
        for tok in FORBIDDEN_SIDE_CHANNEL_TOKENS:
            if tok in text:
                violations.append(f"{tag}:{surf_name} leaked token {tok}")

    err_count = 0
    for st in steps:
        if allowed_tools and st.tool not in allowed_tools and not st.tool.startswith("unknown_"):
            violations.append(f"{tag}:step[{st.t}] used non-public tool {st.tool!r}")
        blob = _canonical_json(st.result)
        for tok in FORBIDDEN_SIDE_CHANNEL_TOKENS:
            if tok in blob:
                violations.append(f"{tag}:step[{st.t}]({st.tool}) leaked token {tok}")
        err = st.result.get("error")
        if not st.result.get("ok") or err:
            err_count += 1
            err_str = str(err or "")
            if true_mole and true_mole in err_str:
                violations.append(f"{tag}:step[{st.t}]({st.tool}) error leaked mole id {true_mole}")
            if err_str and err_str not in ENV_ERRORS:
                violations.append(f"{tag}:step[{st.t}]({st.tool}) non-canonical error {err_str!r}")
    return len(steps), err_count, violations


def _day1_snapshot(tier: str, seed: int, parsed: MoleStrategy | RLMole) -> dict[str, Any]:
    env = Env(tier, seed, mole_strategy=_clone_strategy(parsed))
    return {
        "instruction": env.instruction(),
        "tools_spec": env.tools_spec(),
        "status": asdict(env.call("status", {})),
        "employees": asdict(env.call("list_employees", {})),
        "documents": asdict(env.call("list_documents", {"day_from": 1, "day_to": 1})),
        "logs": asdict(env.call("read_access_logs", {"day_from": 1, "day_to": 1})),
        "messages": asdict(env.call("search_messages", {"query": "e"})),
    }


def _run_error_isolation_probe(tier: str, seed: int, parsed: MoleStrategy | RLMole) -> tuple[int, int, list[str]]:
    env = Env(tier, seed, mole_strategy=_clone_strategy(parsed))
    true_mole = str(env._world.mole)
    innocent = next(e for e in env._ids if e != true_mole)
    allowed = {spec["name"] for spec in env.tools_spec()}

    env.call("unknown_tool_probe", {})
    r_mole_bad = env.call("interview", {"employee": true_mole, "topic": "invalid_topic"})
    r_inn_bad = env.call("interview", {"employee": innocent, "topic": "invalid_topic"})
    r_unres_m = env.call("unrestrict_access", {"employee": true_mole})
    r_unres_i = env.call("unrestrict_access", {"employee": innocent})
    env.call("read_message", {"id": "missing-msg-id"})
    env.call("search_messages", {"query": "*"})
    for _ in range(env.p.actions_per_day + 1):
        env.call("check_leak_feed", {})
    env.call("accuse", {"employee": innocent})
    env.call("status", {})

    steps_n, err_n, violations = _scan_episode_surfaces(
        env.instruction(),
        env.tools_spec(),
        list(env.history),
        true_mole,
        allowed,
        f"error_probe:{seed}",
    )
    if r_mole_bad.error != r_inn_bad.error or set(r_mole_bad.data) != set(r_inn_bad.data):
        violations.append(f"error_probe:{seed} interview error or schema differs between mole and innocent")
    if r_unres_m.error != r_unres_i.error or set(r_unres_m.data) != set(r_unres_i.data):
        violations.append(f"error_probe:{seed} unrestrict error or schema differs between mole and innocent")
    return steps_n, err_n, violations


def check_anti_side_channel(
    parsed: MoleStrategy | RLMole,
    tier: str,
    seeds: list[int],
    solver_episodes: list[EpisodeResult] | None = None,
    proxy_episodes: list[EpisodeResult] | None = None,
    probe_count: int = 2,
) -> dict[str, Any]:
    probe_seeds = seeds[: max(1, min(probe_count, len(seeds)))]
    violations: list[str] = []
    steps_checked = 0
    errors_checked = 0

    firewall_matches = 0
    determinism_matches = 0
    day1_invariance_matches = 0
    sol_by_seed = {int(ep.seed): ep for ep in (solver_episodes or [])}

    for idx, s in enumerate(probe_seeds):
        rnd_a = Env(tier, s, mole_strategy=_clone_strategy(parsed))
        rnd_b = Env(tier, s, mole_strategy=_clone_strategy(parsed))
        run_episode(rnd_a, RandomPolicy(seed=s))
        run_episode(rnd_b, RandomPolicy(seed=s))

        led_ok = [asdict(x) for x in rnd_a.ledger()] == [asdict(x) for x in rnd_b.ledger()]
        hist_ok = [asdict(x) for x in rnd_a.history] == [asdict(x) for x in rnd_b.history]
        if led_ok and hist_ok:
            determinism_matches += 1
        else:
            violations.append(f"determinism_mismatch:seed={s}")

        if idx == 0:
            raw_sol_env = Env(tier, s, mole_strategy=_clone_strategy(parsed))
            res_raw = run_episode(raw_sol_env, _make_solver(tier))
            res_fw = sol_by_seed.get(int(s))
            if res_fw is None:
                fw_env = PublicToolFirewall(Env(tier, s, mole_strategy=_clone_strategy(parsed)))
                res_fw = run_episode(fw_env, _make_solver(tier))
            fw_steps_ok = [asdict(x) for x in res_raw.steps] == [asdict(x) for x in res_fw.steps]
            if fw_steps_ok and res_raw.accused == res_fw.accused and res_raw.score == res_fw.score:
                firewall_matches += 1
            else:
                violations.append(f"firewall_parity_mismatch:seed={s}")

        snap_cand = _day1_snapshot(tier, s, parsed)
        snap_def = _day1_snapshot(tier, s, DEFAULT_STRATEGY)
        if snap_cand == snap_def:
            day1_invariance_matches += 1
        else:
            violations.append(f"day1_strategy_leak:seed={s}")

        st_n, er_n, viol = _run_error_isolation_probe(tier, s, parsed)
        steps_checked += st_n
        errors_checked += er_n
        violations.extend(viol)

    sample_env = Env(tier, seeds[0], mole_strategy=_clone_strategy(parsed))
    allowed_tools = {spec["name"] for spec in sample_env.tools_spec()}
    ins_text = sample_env.instruction()
    spec_list = sample_env.tools_spec()
    mole_by_seed = {
        int(s): str(Env(tier, int(s), mole_strategy=_clone_strategy(parsed))._world.mole)
        for s in seeds
    }

    for label, ep_list in (("solver", solver_episodes or []), ("proxy", proxy_episodes or [])):
        for ep in ep_list:
            true_mole = mole_by_seed.get(int(ep.seed))
            st_n, er_n, viol = _scan_episode_surfaces(
                ins_text,
                spec_list,
                list(ep.steps),
                true_mole,
                allowed_tools,
                f"{label}:{ep.seed}",
            )
            steps_checked += st_n
            errors_checked += er_n
            violations.extend(viol)

    passed = len(violations) == 0
    return {
        "passed": passed,
        "probe_seeds": probe_seeds,
        "firewall_matches": firewall_matches,
        "determinism_matches": determinism_matches,
        "day1_invariance_matches": day1_invariance_matches,
        "steps_checked": steps_checked,
        "errors_checked": errors_checked,
        "forbidden_tokens": list(FORBIDDEN_SIDE_CHANNEL_TOKENS),
        "violations": violations,
    }


def check_blind_diligence(
    parsed: MoleStrategy | RLMole,
    tier: str,
    seeds: list[int],
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
) -> dict[str, Any]:
    n_seeds = len(seeds)
    dn_scores = [
        float(run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), DoNothing(seed=s)).score)
        for s in seeds
    ]
    seq_scores = [
        float(run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), StopEarlyQuit(seed=s)).score)
        for s in seeds
    ]
    se_runs = [
        run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), StopEarly(seed=s))
        for s in seeds
    ]

    env_partial = Env(tier, seeds[0], mole_strategy=_clone_strategy(parsed))
    quit_pol = StopEarlyQuit(seed=seeds[0])
    quit_pol.reset(env_partial.tools_spec(), env_partial.instruction())
    for _ in range(2):
        tool, args = quit_pol.act(list(env_partial.history))
        env_partial.call(tool, args)
    partial_zero = float(env_partial.score()) == 0.0

    lo_runs = [
        run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), LogsOnly(seed=s))
        for s in seeds
    ]
    aml_runs = [
        run_episode(Env(tier, s, mole_strategy=_clone_strategy(parsed)), AccuseMostLogs(seed=s))
        for s in seeds
    ]

    dn_zero = all(x == 0.0 for x in dn_scores)
    seq_zero = all(x == 0.0 for x in seq_scores) and partial_zero
    guess_mean = sum(float(r.score) for r in se_runs) / n_seeds
    guess_acc = sum(bool(r.correct) for r in se_runs) / n_seeds

    lo_acc = sum(bool(r.correct) for r in lo_runs) / n_seeds
    lo_mean = sum(float(r.score) for r in lo_runs) / n_seeds
    aml_acc = sum(bool(r.correct) for r in aml_runs) / n_seeds
    aml_mean = sum(float(r.score) for r in aml_runs) / n_seeds

    zero_ok = bool(dn_zero and seq_zero and guess_mean < 0.0)
    logs_ok = bool(
        lo_acc <= max_logs_acc
        and lo_mean < 0.0
        and aml_acc <= max_logs_acc
        and aml_mean < 0.0
    )
    return {
        "passed": bool(zero_ok and logs_ok),
        "n_seeds": n_seeds,
        "max_logs_acc": float(max_logs_acc),
        "do_nothing_zero": dn_zero,
        "stop_early_zero": seq_zero,
        "guess_day1_mean_score": guess_mean,
        "guess_day1_acc": guess_acc,
        "logs_only_acc": lo_acc,
        "logs_only_mean_score": lo_mean,
        "accuse_most_logs_acc": aml_acc,
        "accuse_most_logs_mean_score": aml_mean,
    }


def _evaluate_paired_runs(
    tier: str,
    seeds: list[int],
    parsed: MoleStrategy | RLMole,
    proxy_factory: Callable[[int], Any],
    codex_factory: Callable[[int], Any] | None = None,
    include_step_regret: bool = False,
) -> tuple[dict[str, Any], list[EpisodeResult], list[EpisodeResult]]:
    p = tier_params(tier)
    solver_eps: list[EpisodeResult] = []
    proxy_eps: list[EpisodeResult] = []
    codex_eps: list[EpisodeResult] = []
    per_seed_rows: list[dict[str, Any]] = []

    for s in seeds:
        sol_ep = run_episode(PublicToolFirewall(Env(tier, s, mole_strategy=_clone_strategy(parsed))), _make_solver(tier))
        prx_pol = proxy_factory(s)
        prx_ep = run_episode(PublicToolFirewall(Env(tier, s, mole_strategy=_clone_strategy(parsed))), prx_pol)
        solver_eps.append(sol_ep)
        proxy_eps.append(prx_ep)

        sol_la, sol_pa = luck_adjusted_episode_score(sol_ep, p)
        prx_la, prx_pa = luck_adjusted_episode_score(prx_ep, p)
        if include_step_regret:
            prx_attr = attribute_step_regret(prx_ep)
            prx_step_reg = round(sum(float(item.get("regret", 0.0)) for item in prx_attr), 6)
        else:
            prx_step_reg = round(max(0.0, sol_la - prx_la), 6)

        row: dict[str, Any] = {
            "seed": int(s),
            "solver_score": float(sol_ep.score),
            "solver_correct": bool(sol_ep.correct),
            "solver_accused": sol_ep.accused,
            "solver_day": int(sol_ep.final_day),
            "solver_luck_adjusted": sol_la,
            "solver_p_accused": sol_pa,
            "proxy_score": float(prx_ep.score),
            "proxy_correct": bool(prx_ep.correct),
            "proxy_accused": prx_ep.accused,
            "proxy_day": int(prx_ep.final_day),
            "proxy_luck_adjusted": prx_la,
            "proxy_p_accused": prx_pa,
            "proxy_step_regret": prx_step_reg,
            "paired_diff": float(sol_ep.score) - float(prx_ep.score),
            "luck_adjusted_diff": sol_la - prx_la,
        }
        if codex_factory is not None:
            cdx_ep = run_episode(
                PublicToolFirewall(Env(tier, s, mole_strategy=_clone_strategy(parsed))),
                codex_factory(s),
            )
            codex_eps.append(cdx_ep)
            row["codex_score"] = float(cdx_ep.score)
            row["codex_correct"] = bool(cdx_ep.correct)
            row["codex_paired_diff"] = float(sol_ep.score) - float(cdx_ep.score)

        per_seed_rows.append(row)

    n = len(per_seed_rows)
    sol_scores = [r["solver_score"] for r in per_seed_rows]
    prx_scores = [r["proxy_score"] for r in per_seed_rows]
    paired_diffs = [r["paired_diff"] for r in per_seed_rows]
    la_diffs = [r["luck_adjusted_diff"] for r in per_seed_rows]

    sol_mean, sol_ci = mean_ci(sol_scores)
    prx_mean, prx_ci = mean_ci(prx_scores)
    reg_mean, reg_ci = mean_ci(paired_diffs)
    la_reg_mean, la_reg_ci = mean_ci(la_diffs)

    sol_acc = sum(1 for r in per_seed_rows if r["solver_correct"]) / n
    prx_acc = sum(1 for r in per_seed_rows if r["proxy_correct"]) / n
    prx_fails = sum(1 for r in per_seed_rows if not r["proxy_correct"])

    sol_justified = [
        r["solver_p_accused"] >= 0.60
        for r in per_seed_rows
        if r["solver_p_accused"] is not None
    ]
    proxy_name = getattr(proxy_factory(seeds[0]), "name", "gemini_carbon_proxy")

    metrics: dict[str, Any] = {
        "n_seeds": n,
        "proxy_name": str(proxy_name),
        "solver_acc": sol_acc,
        "solver_score": sol_mean,
        "solver_score_ci": sol_ci,
        "solver_luck_adjusted": sum(r["solver_luck_adjusted"] for r in per_seed_rows) / n,
        "solver_accused_rate": sum(1 for ep in solver_eps if ep.end_reason == "accused") / n,
        "solver_mean_day": sum(float(r["solver_day"]) for r in per_seed_rows) / n,
        "solver_justified_rate": (sum(sol_justified) / len(sol_justified)) if sol_justified else 0.0,
        "proxy_acc": prx_acc,
        "proxy_fails": prx_fails,
        "proxy_score": prx_mean,
        "proxy_score_ci": prx_ci,
        "proxy_luck_adjusted": sum(r["proxy_luck_adjusted"] for r in per_seed_rows) / n,
        "proxy_mean_step_regret": sum(r["proxy_step_regret"] for r in per_seed_rows) / n,
        "paired_regret": reg_mean,
        "paired_regret_ci": reg_ci,
        "luck_adjusted_regret": la_reg_mean,
        "luck_adjusted_regret_ci": la_reg_ci,
        "acc_gap": sol_acc - prx_acc,
        "paired_wins": sum(1 for d in paired_diffs if d > 1e-9),
        "paired_ties": sum(1 for d in paired_diffs if abs(d) <= 1e-9),
        "paired_losses": sum(1 for d in paired_diffs if d < -1e-9),
        "per_seed": per_seed_rows,
    }
    if codex_eps:
        cdx_scores = [r["codex_score"] for r in per_seed_rows]
        cdx_diffs = [r["codex_paired_diff"] for r in per_seed_rows]
        cdx_mean, cdx_ci = mean_ci(cdx_scores)
        cdx_reg, cdx_reg_ci = mean_ci(cdx_diffs)
        metrics["codex_acc"] = sum(1 for r in per_seed_rows if r["codex_correct"]) / n
        metrics["codex_score"] = cdx_mean
        metrics["codex_score_ci"] = cdx_ci
        metrics["codex_paired_regret"] = cdx_reg
        metrics["codex_paired_regret_ci"] = cdx_reg_ci
    return metrics, solver_eps, proxy_eps


def _default_paired_baseline(
    tier: str,
    seeds: list[int],
    proxy_tag: str,
    proxy_factory: Callable[[int], Any],
) -> dict[str, Any]:
    tp = tier_params(tier)
    kv = bool(canary_rules.KNOWN_V_MODE)
    missing = [s for s in seeds if (tier, s, tp, kv, proxy_tag) not in _DEFAULT_PAIRED_CACHE]
    if missing:
        computed, _, _ = _evaluate_paired_runs(tier, missing, DEFAULT_STRATEGY, proxy_factory)
        for row in computed["per_seed"]:
            _DEFAULT_PAIRED_CACHE[(tier, int(row["seed"]), tp, kv, proxy_tag)] = row
    rows = [_DEFAULT_PAIRED_CACHE[(tier, s, tp, kv, proxy_tag)] for s in seeds]
    n = len(rows)
    sol_sc = sum(r["solver_score"] for r in rows) / n
    sol_acc = sum(1 for r in rows if r["solver_correct"]) / n
    prx_sc = sum(r["proxy_score"] for r in rows) / n
    prx_acc = sum(1 for r in rows if r["proxy_correct"]) / n
    reg = sum(r["paired_diff"] for r in rows) / n
    la_reg = sum(r["luck_adjusted_diff"] for r in rows) / n
    return {
        "solver_score": sol_sc,
        "solver_acc": sol_acc,
        "proxy_score": prx_sc,
        "proxy_acc": prx_acc,
        "paired_regret": reg,
        "luck_adjusted_regret": la_reg,
    }


def _skipped_gates(v_gate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    msg = "skipped because valid_strategy failed"
    return {
        "valid_strategy": v_gate,
        "anti_side_channel": {"passed": False, "skipped": True, "violations": [msg]},
        "blind_diligence": {"passed": False, "skipped": True},
        "solver_beatable": {
            "passed": False,
            "skipped": True,
            "solver_acc": 0.0,
            "solver_score": 0.0,
        },
        "paired_regret": {
            "passed": False,
            "skipped": True,
            "paired_regret": 0.0,
            "luck_adjusted_regret": 0.0,
        },
    }


def audit_beatability(
    strategy_obj: Any,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(6000, 6020),
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_paired_regret: float = DEFAULT_MIN_PAIRED_REGRET,
    require_proxy_fail: bool = True,
    proxy_factory: Callable[[int], Any] | None = None,
    include_codex_proxy: bool = False,
    include_step_regret: bool = False,
    probe_count: int = 2,
) -> dict[str, Any]:
    seed_list = _normalize_seeds(seeds)
    v_gate, parsed = _validate_strategy_input(strategy_obj)
    if parsed is None:
        gates = _skipped_gates(v_gate)
        return {
            "strategy_name": v_gate["name"],
            "strategy_kind": v_gate["kind"],
            "tier": tier,
            "n_seeds": len(seed_list),
            "seeds": seed_list,
            "verdict": "dropped",
            "reason": "invalid_strategy",
            "beatable": False,
            "all_passed": False,
            "failed_gates": list(GATE_NAMES),
            "solver_acc": 0.0,
            "solver_score": 0.0,
            "proxy_name": "gemini_carbon_proxy",
            "proxy_acc": 0.0,
            "proxy_fails": 0,
            "proxy_score": 0.0,
            "paired_regret": 0.0,
            "paired_regret_ci": 0.0,
            "luck_adjusted_regret": 0.0,
            "paired_regret_gain": 0.0,
            "gates": gates,
            "per_seed": [],
        }

    p_factory = proxy_factory or (lambda s: GeminiCarbonProxy(seed=s))
    proxy_tag = getattr(p_factory(seed_list[0]), "name", repr(p_factory))
    c_factory = (lambda s: CodexHorizonProxy(seed=s)) if include_codex_proxy else None

    paired_metrics, solver_eps, proxy_eps = _evaluate_paired_runs(
        tier,
        seed_list,
        parsed,
        p_factory,
        codex_factory=c_factory,
        include_step_regret=include_step_regret,
    )
    if _is_default_strategy(parsed):
        tp = tier_params(tier)
        kv = bool(canary_rules.KNOWN_V_MODE)
        for row in paired_metrics["per_seed"]:
            _DEFAULT_PAIRED_CACHE[(tier, int(row["seed"]), tp, kv, str(proxy_tag))] = {
                k: v for k, v in row.items() if not k.startswith("codex_")
            }

    base_metrics = _default_paired_baseline(tier, seed_list, str(proxy_tag), p_factory)
    side_gate = check_anti_side_channel(
        parsed,
        tier,
        seed_list,
        solver_episodes=solver_eps,
        proxy_episodes=proxy_eps,
        probe_count=probe_count,
    )
    blind_gate = check_blind_diligence(parsed, tier, seed_list, max_logs_acc=max_logs_acc)

    sol_acc = float(paired_metrics["solver_acc"])
    sol_score = float(paired_metrics["solver_score"])
    base_sol_score = float(base_metrics["solver_score"])
    ratio_floor = float(min_solver_ratio) * base_sol_score
    beatable_ok = bool(
        sol_acc >= float(min_solver_acc)
        and sol_score >= float(min_solver_score)
        and sol_score >= ratio_floor
    )
    solver_gate = {
        "passed": beatable_ok,
        "n_seeds": len(seed_list),
        "min_solver_acc": float(min_solver_acc),
        "min_solver_score": float(min_solver_score),
        "min_solver_ratio": float(min_solver_ratio),
        "baseline_solver_score": base_sol_score,
        "baseline_solver_acc": float(base_metrics["solver_acc"]),
        "solver_acc": sol_acc,
        "solver_score": sol_score,
        "solver_score_ci": float(paired_metrics["solver_score_ci"]),
        "solver_luck_adjusted": float(paired_metrics["solver_luck_adjusted"]),
        "solver_accused_rate": float(paired_metrics["solver_accused_rate"]),
        "solver_mean_day": float(paired_metrics["solver_mean_day"]),
        "solver_justified_rate": float(paired_metrics["solver_justified_rate"]),
    }

    reg_val = float(paired_metrics["paired_regret"])
    la_reg_val = float(paired_metrics["luck_adjusted_regret"])
    prx_fails = int(paired_metrics["proxy_fails"])
    reg_gain = reg_val - float(base_metrics["paired_regret"])
    has_gap = (prx_fails > 0) if require_proxy_fail else True
    better_than_proxy = reg_val > float(min_paired_regret)
    regret_ok = bool(has_gap and better_than_proxy)

    regret_gate: dict[str, Any] = {
        "passed": regret_ok,
        "n_seeds": len(seed_list),
        "proxy_name": str(paired_metrics["proxy_name"]),
        "min_paired_regret": float(min_paired_regret),
        "require_proxy_fail": bool(require_proxy_fail),
        "proxy_acc": float(paired_metrics["proxy_acc"]),
        "proxy_fails": prx_fails,
        "proxy_score": float(paired_metrics["proxy_score"]),
        "proxy_score_ci": float(paired_metrics["proxy_score_ci"]),
        "proxy_luck_adjusted": float(paired_metrics["proxy_luck_adjusted"]),
        "proxy_mean_step_regret": float(paired_metrics["proxy_mean_step_regret"]),
        "paired_regret": reg_val,
        "paired_regret_ci": float(paired_metrics["paired_regret_ci"]),
        "luck_adjusted_regret": la_reg_val,
        "luck_adjusted_regret_ci": float(paired_metrics["luck_adjusted_regret_ci"]),
        "acc_gap": float(paired_metrics["acc_gap"]),
        "paired_wins": int(paired_metrics["paired_wins"]),
        "paired_ties": int(paired_metrics["paired_ties"]),
        "paired_losses": int(paired_metrics["paired_losses"]),
        "baseline_proxy_score": float(base_metrics["proxy_score"]),
        "baseline_proxy_acc": float(base_metrics["proxy_acc"]),
        "baseline_paired_regret": float(base_metrics["paired_regret"]),
        "paired_regret_gain": reg_gain,
    }
    if "codex_paired_regret" in paired_metrics:
        regret_gate["codex_acc"] = float(paired_metrics["codex_acc"])
        regret_gate["codex_score"] = float(paired_metrics["codex_score"])
        regret_gate["codex_paired_regret"] = float(paired_metrics["codex_paired_regret"])

    gates: dict[str, dict[str, Any]] = {
        "valid_strategy": v_gate,
        "anti_side_channel": side_gate,
        "blind_diligence": blind_gate,
        "solver_beatable": solver_gate,
        "paired_regret": regret_gate,
    }

    if not side_gate["passed"]:
        reason = "side_channel"
    elif not blind_gate["passed"]:
        reason = "blind_diligence_wins"
    elif not solver_gate["passed"]:
        reason = "unbeatable"
    elif not has_gap:
        reason = "no_gap"
    elif not better_than_proxy:
        reason = "solver_not_better"
    else:
        reason = ""

    all_passed = reason == ""
    return {
        "strategy_name": v_gate["name"],
        "strategy_kind": v_gate["kind"],
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "verdict": "kept" if all_passed else "dropped",
        "reason": reason,
        "beatable": bool(side_gate["passed"] and blind_gate["passed"] and solver_gate["passed"]),
        "all_passed": all_passed,
        "failed_gates": [g for g in GATE_NAMES if not gates[g]["passed"]],
        "solver_acc": sol_acc,
        "solver_score": sol_score,
        "proxy_name": str(paired_metrics["proxy_name"]),
        "proxy_acc": float(paired_metrics["proxy_acc"]),
        "proxy_fails": prx_fails,
        "proxy_score": float(paired_metrics["proxy_score"]),
        "paired_regret": reg_val,
        "paired_regret_ci": float(paired_metrics["paired_regret_ci"]),
        "luck_adjusted_regret": la_reg_val,
        "paired_regret_gain": reg_gain,
        "gates": gates,
        "per_seed": paired_metrics["per_seed"],
    }


def evaluate_candidate(
    candidate: Any,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(6000, 6020),
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_paired_regret: float = DEFAULT_MIN_PAIRED_REGRET,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    proxy_factory: Callable[[int], Any] | None = None,
    runner: Callable[[Any, list[int]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    seed_list = _normalize_seeds(seeds)
    if runner is not None:
        raw = runner(candidate, seed_list)
        if not raw.get("valid_strategy", True):
            reason = "invalid_strategy"
        elif not raw.get("anti_side_channel", True):
            reason = "side_channel"
        elif not raw.get("blind_diligence", True):
            reason = "blind_diligence_wins"
        elif float(raw.get("solver_acc", 0.0)) < float(min_solver_acc):
            reason = "unbeatable"
        elif int(raw.get("proxy_fails", 0)) <= 0:
            reason = "no_gap"
        elif float(raw.get("paired_regret", 0.0)) <= float(min_paired_regret):
            reason = "solver_not_better"
        else:
            reason = ""
        return {
            "strategy_name": str(raw.get("name", "candidate")),
            "tier": tier,
            "n_seeds": len(seed_list),
            "verdict": "kept" if not reason else "dropped",
            "reason": reason,
            "beatable": reason not in ("invalid_strategy", "side_channel", "blind_diligence_wins", "unbeatable"),
            "all_passed": reason == "",
            "solver_acc": float(raw.get("solver_acc", 0.0)),
            "solver_score": float(raw.get("solver_score", 0.0)),
            "proxy_acc": float(raw.get("proxy_acc", 0.0)),
            "proxy_fails": int(raw.get("proxy_fails", 0)),
            "proxy_score": float(raw.get("proxy_score", 0.0)),
            "paired_regret": float(raw.get("paired_regret", 0.0)),
        }
    return audit_beatability(
        candidate,
        tier=tier,
        seeds=seed_list,
        min_solver_acc=min_solver_acc,
        min_paired_regret=min_paired_regret,
        max_logs_acc=max_logs_acc,
        proxy_factory=proxy_factory,
    )


def filter_candidates(
    candidates: Iterable[Any],
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(6000, 6020),
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_paired_regret: float = DEFAULT_MIN_PAIRED_REGRET,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    proxy_factory: Callable[[int], Any] | None = None,
    runner: Callable[[Any, list[int]], dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str]]]:
    kept: list[dict[str, Any]] = []
    dropped: list[tuple[dict[str, Any], str]] = []
    for cand in candidates:
        entry = evaluate_candidate(
            cand,
            tier=tier,
            seeds=seeds,
            min_solver_acc=min_solver_acc,
            min_paired_regret=min_paired_regret,
            max_logs_acc=max_logs_acc,
            proxy_factory=proxy_factory,
            runner=runner,
        )
        if entry["verdict"] == "kept":
            kept.append(entry)
        else:
            dropped.append((entry, str(entry["reason"])))
    return kept, dropped


def summarize_candidates(
    kept: list[dict[str, Any]],
    dropped: list[tuple[dict[str, Any], str]],
) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    for _, reason in dropped:
        reasons[reason] = reasons.get(reason, 0) + 1
    mean_regret = (
        sum(float(item["paired_regret"]) for item in kept) / len(kept)
        if kept
        else None
    )
    mean_solver_acc = (
        sum(float(item["solver_acc"]) for item in kept) / len(kept)
        if kept
        else None
    )
    return {
        "kept": len(kept),
        "dropped": len(dropped),
        "mean_paired_regret": mean_regret,
        "mean_solver_acc": mean_solver_acc,
        "drop_reasons": reasons,
    }


def audit_hof_beatability(
    hof_path: str | Path,
    tier: str = "hard",
    seeds: str | int | Iterable[int] = range(6000, 6020),
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_score: float = DEFAULT_MIN_SOLVER_SCORE,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_paired_regret: float = DEFAULT_MIN_PAIRED_REGRET,
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
            "n_kept": 0,
            "n_beatable": 0,
            "all_passed": False,
            "summary": summarize_candidates([], []),
            "strategies": [],
            "error": "empty hall of fame",
        }

    kept: list[dict[str, Any]] = []
    dropped: list[tuple[dict[str, Any], str]] = []
    strategies: list[dict[str, Any]] = []
    for idx, ln in enumerate(lines):
        rank: Any = idx + 1
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            sj: Any = None
        else:
            if isinstance(row, dict):
                rank = row.get("rank", idx + 1)
                sj = row
            else:
                sj = None

        rep = audit_beatability(
            sj,
            tier=tier,
            seeds=seed_list,
            min_solver_acc=min_solver_acc,
            min_solver_score=min_solver_score,
            min_solver_ratio=min_solver_ratio,
            max_logs_acc=max_logs_acc,
            min_paired_regret=min_paired_regret,
        )
        rep["index"] = idx
        rep["rank"] = rank
        strategies.append(rep)
        if rep["verdict"] == "kept":
            kept.append(rep)
        else:
            dropped.append((rep, str(rep["reason"])))

    n_strategies = len(strategies)
    n_kept = len(kept)
    n_beatable = sum(1 for r in strategies if r["beatable"])
    return {
        "hof_path": str(path),
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "n_strategies": n_strategies,
        "n_kept": n_kept,
        "n_beatable": n_beatable,
        "all_passed": n_strategies > 0 and n_kept == n_strategies,
        "summary": summarize_candidates(kept, dropped),
        "strategies": strategies,
    }


def _slim_report(report: dict[str, Any]) -> dict[str, Any]:
    if "strategies" in report:
        out = dict(report)
        out["strategies"] = [
            {k: v for k, v in item.items() if k != "per_seed"}
            for item in report["strategies"]
        ]
        return out
    return {k: v for k, v in report.items() if k != "per_seed"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.beatability")
    ap.add_argument("--hof", type=Path, default=None)
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--default", action="store_true")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="6000-6019")
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--min-solver-score", type=float, default=DEFAULT_MIN_SOLVER_SCORE)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--min-paired-regret", type=float, default=DEFAULT_MIN_PAIRED_REGRET)
    ap.add_argument("--include-per-seed", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    if args.hof is not None:
        report = audit_hof_beatability(
            args.hof,
            tier=args.tier,
            seeds=seeds,
            min_solver_acc=args.min_solver_acc,
            min_solver_score=args.min_solver_score,
            min_solver_ratio=args.min_solver_ratio,
            max_logs_acc=args.max_logs_acc,
            min_paired_regret=args.min_paired_regret,
        )
    elif args.strategy is not None:
        strat_path = Path(args.strategy)
        raw_text = strat_path.read_text(encoding="utf-8") if strat_path.is_file() else args.strategy
        strat_obj = json.loads(raw_text)
        report = audit_beatability(
            strat_obj,
            tier=args.tier,
            seeds=seeds,
            min_solver_acc=args.min_solver_acc,
            min_solver_score=args.min_solver_score,
            min_solver_ratio=args.min_solver_ratio,
            max_logs_acc=args.max_logs_acc,
            min_paired_regret=args.min_paired_regret,
        )
    elif args.default:
        report = audit_beatability(
            DEFAULT_STRATEGY,
            tier=args.tier,
            seeds=seeds,
            min_solver_acc=args.min_solver_acc,
            min_solver_score=args.min_solver_score,
            min_solver_ratio=args.min_solver_ratio,
            max_logs_acc=args.max_logs_acc,
            min_paired_regret=args.min_paired_regret,
        )
    else:
        ap.error("provide one of --hof, --strategy, or --default")
        return 2

    payload = report if args.include_per_seed else _slim_report(report)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
