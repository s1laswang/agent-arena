from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import sys
from pathlib import Path
from typing import Any, Iterable

from canary.analysis.accuse import audit_episode
from canary.analysis.gap import mean_ci
from canary.analysis.tags import to_result
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.fitness import FEASIBLE_SOLVER_ACC, FEASIBLE_SOLVER_RATIO, tier_defaults
from canary.forge.rl_mole import RLMole
from canary.forge_track import _strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.rules import TIERS, tier_params, tier_params_for_episode
from canary.solver.belief import posterior
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step
from canary.world import generate_world

ROOT = Path(__file__).resolve().parents[2]
V14_COMMITTED_ROOT = ROOT / "data" / "runs" / "committed" / "v1.4"
FRONTIER_SOURCE_DIRS: dict[str, str] = {
    "opencode": "opencode-gemini-4-carbon",
    "inproc": "inproc-gemini-4-carbon",
}
OPENCODE_HARD_EPISODES = V14_COMMITTED_ROOT / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
INPROC_HARD_EPISODES = V14_COMMITTED_ROOT / "inproc-gemini-4-carbon" / "hard" / "episodes.jsonl"

REPLAY_TOOLS: frozenset[str] = frozenset({
    "status",
    "list_employees",
    "list_documents",
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
})

BUILTIN_CANDIDATES: dict[str, dict[str, Any]] = {
    "default_v0": DEFAULT_STRATEGY.to_json(),
    "frame_decoy_seeded": {
        "name": "frame_decoy_seeded",
        "rules": [
            {
                "if": [["recent_low_recipient_docs", ">=", 2]],
                "then": {"leak": "most_recipients", "frame": "decoy"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "decoy"},
    },
    "canary_shy_frame_decoy": {
        "name": "canary_shy_frame_decoy",
        "rules": [
            {
                "if": [["recent_low_recipient_docs", ">=", 1]],
                "then": {"leak": "most_recipients", "frame": "decoy"},
            }
        ],
        "default": {"leak": "most_recipients", "frame": "decoy"},
    },
    "paced_oldest_framer": {
        "name": "paced_oldest_framer",
        "rules": [
            {
                "if": [["days_since_last_leak", "<", 2]],
                "then": {"leak": "none", "frame": "decoy"},
            },
            {
                "if": [["recent_low_recipient_docs", ">=", 1]],
                "then": {"leak": "most_recipients", "frame": "decoy"},
            },
        ],
        "default": {"leak": "oldest", "frame": "decoy"},
    },
}

_EPISODE_CACHE: dict[str, dict[int, EpisodeResult]] = {}


def coerce_strategy(
    strategy: MoleStrategy | RLMole | dict[str, Any] | None,
    name: str | None = None,
) -> MoleStrategy | RLMole:
    if strategy is None:
        out: MoleStrategy | RLMole = DEFAULT_STRATEGY
    elif isinstance(strategy, MoleStrategy):
        out = strategy
    elif isinstance(strategy, RLMole):
        out = RLMole.from_json(strategy.to_json())
    elif isinstance(strategy, dict):
        payload = dict(strategy.get("strategy_json", strategy.get("strategy", strategy)))
        if name and "name" not in payload:
            payload["name"] = name[:80]
        out = _strategy(payload)
    else:
        raise TypeError(f"unsupported strategy type: {type(strategy).__name__}")
    if name and out.name != name:
        if isinstance(out, MoleStrategy):
            out = MoleStrategy(rules=out.rules, default=out.default, name=name[:80])
        else:
            sj = out.to_json()
            sj["name"] = name[:80]
            out = RLMole.from_json(sj)
    return out


def committed_episode_path(source: str, tier: str = "hard", root: str | Path | None = None) -> Path:
    if source not in FRONTIER_SOURCE_DIRS:
        raise ValueError(f"unknown frontier source {source!r}; expected one of {sorted(FRONTIER_SOURCE_DIRS)}")
    base = Path(root) / "data" / "runs" / "committed" / "v1.4" if root is not None else V14_COMMITTED_ROOT
    return base / FRONTIER_SOURCE_DIRS[source] / tier / "episodes.jsonl"


def load_episodes_jsonl(path: str | Path, seeds: Iterable[int] | None = None) -> dict[int, EpisodeResult]:
    resolved = Path(path).resolve()
    key = str(resolved)
    if key not in _EPISODE_CACHE:
        if not resolved.is_file():
            raise FileNotFoundError(f"committed episodes file not found: {resolved}")
        by_seed: dict[int, EpisodeResult] = {}
        for line in resolved.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            raw = json.loads(line)
            if (raw.get("meta") or {}).get("valid") is False:
                continue
            ep = to_result(raw)
            by_seed[int(ep.seed)] = ep
        _EPISODE_CACHE[key] = dict(sorted(by_seed.items()))
    cached = _EPISODE_CACHE[key]
    if seeds is None:
        return dict(cached)
    wanted = [int(s) for s in seeds]
    return {s: cached[s] for s in wanted if s in cached}


def load_v14_frontier_episodes(
    tier: str = "hard",
    sources: Iterable[str] = ("opencode", "inproc"),
    seeds: Iterable[int] | None = None,
    root: str | Path | None = None,
) -> dict[str, dict[int, EpisodeResult]]:
    out: dict[str, dict[int, EpisodeResult]] = {}
    seed_list = [int(s) for s in seeds] if seeds is not None else None
    for src in sources:
        p = committed_episode_path(src, tier=tier, root=root)
        out[src] = load_episodes_jsonl(p, seeds=seed_list)
    return out


def episode_accuse_day(episode: EpisodeResult) -> int:
    for st in episode.steps:
        if st.tool == "accuse":
            return int(st.day)
    return int(episode.final_day)


class ScheduleReplayPolicy:
    def __init__(self, episode: EpisodeResult | dict[str, Any], target_day: int | str | None = None):
        ep = to_result(episode) if isinstance(episode, dict) else episode
        self.episode: EpisodeResult = ep
        self.params = tier_params_for_episode(ep.tier, ep.steps)
        self.horizon_day: int = int(self.params.n_days)
        self.accuse_day: int = episode_accuse_day(ep)
        self.target_day: int = self._resolve_target_day(target_day)
        self.name: str = f"schedule_replay:{ep.agent}:s{ep.seed}:d{self.target_day}"
        self.schedule, self.recorded_prefix_len = self._build_schedule()
        self._cursor: int = 0
        self._base_len: int | None = None

    def _resolve_target_day(self, target_day: int | str | None) -> int:
        if target_day is None or target_day == "accuse":
            return max(1, min(self.accuse_day, self.horizon_day))
        if target_day == "horizon":
            return self.horizon_day
        if isinstance(target_day, int) and not isinstance(target_day, bool):
            if not (1 <= target_day <= self.horizon_day):
                raise ValueError(f"target_day must be in 1..{self.horizon_day}, got {target_day}")
            return int(target_day)
        raise ValueError(f"invalid target_day {target_day!r}; expected int, 'accuse', 'horizon', or None")

    def _build_schedule(self) -> tuple[list[tuple[str, dict[str, Any]]], int]:
        actions: list[tuple[str, dict[str, Any]]] = []
        sim_day = 1
        saw_employees = False
        for st in self.episode.steps:
            if st.tool == "accuse":
                break
            if st.day > self.target_day:
                break
            if st.day == self.target_day and st.tool == "advance_day":
                break
            if st.tool in REPLAY_TOOLS:
                actions.append((st.tool, dict(st.args or {})))
                if st.tool == "list_employees":
                    saw_employees = True
                elif st.tool == "advance_day":
                    sim_day += 1
        prefix_len = len(actions)
        if sim_day < self.target_day:
            while sim_day < self.target_day:
                actions.append(("advance_day", {}))
                sim_day += 1
            if not saw_employees:
                actions.append(("list_employees", {}))
            actions.append(("status", {}))
            actions.append(("list_documents", {"day_from": 1, "day_to": self.target_day}))
            actions.append(("check_leak_feed", {}))
        return actions, prefix_len

    @property
    def done(self) -> bool:
        return self._cursor >= len(self.schedule)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self._cursor = 0
        self._base_len = None

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if self._base_len is None or len(history) < self._base_len:
            self._base_len = len(history)
        idx = len(history) - self._base_len
        if idx < self._cursor:
            self._cursor = idx
        if self._cursor >= len(self.schedule):
            raise StopIteration("schedule replay complete")
        tool, args = self.schedule[self._cursor]
        self._cursor += 1
        return tool, dict(args)


def replay_schedule(env: Env, policy: ScheduleReplayPolicy) -> list[Step]:
    policy.reset(env.tools_spec(), env.instruction())
    while not env.done and not policy.done:
        tool, args = policy.act(list(env.history))
        env.call(tool, args)
    return list(env.history)


def inspect_observation_history(
    history: list[Step],
    tier: str,
    seed: int,
    recorded_accused: str | None = None,
    true_mole: str | None = None,
) -> dict[str, Any]:
    P = tier_params_for_episode(tier, history)
    if true_mole is None:
        true_mole = generate_world(tier, seed, P).mole
    sp = SolverPolicy(P)
    for st in history:
        sp._ingest(st)
    sp.seen = len(history)
    if not sp.obs.employees:
        sp.obs.employees = [f"e{i:02d}" for i in range(P.n_employees)]
    sp.obs.leak_timing_known = sp.v_drops_reveal_leaks()
    post = posterior(
        sp.obs,
        P,
        behaviour_temper=sp.behaviour_temper,
        choice_temper=sp.choice_temper,
        noleak_temper=sp.noleak_temper,
    )
    known_v = round(max(0.0, float(sp.V)), 10)
    p_true = float(post.get(true_mole, 0.0))
    best_suspect = max(sorted(post), key=lambda e: post[e]) if post else None
    max_post = float(post[best_suspect]) if best_suspect is not None else 0.0
    best_ev = max((p * known_v - (1.0 - p) for p in post.values()), default=0.0)
    optimal_ev = float(max(0.0, best_ev))
    p_rec_acc = float(post.get(recorded_accused, 0.0)) if recorded_accused else None
    rec_acc_ev = (
        float(p_rec_acc * known_v - (1.0 - p_rec_acc))
        if p_rec_acc is not None
        else 0.0
    )

    by_doc: dict[str, Any] = {}
    for it in sp.obs.feed:
        if it.doc_id not in by_doc:
            by_doc[it.doc_id] = it
    surfaced_total_leaks = len(by_doc)
    surfaced_canaries = sum(
        1
        for doc_id, it in by_doc.items()
        if it.variant is not None or bool(sp.obs.docs.get(doc_id) and sp.obs.docs[doc_id].is_canary)
    )
    planted_canaries = sum(1 for d in sp.obs.docs.values() if d.is_canary)

    return {
        "day": int(sp.obs.today),
        "steps": len(history),
        "known_V": known_v,
        "true_mole": true_mole,
        "p_true_mole": p_true,
        "best_suspect": best_suspect,
        "top_is_true_mole": bool(best_suspect == true_mole),
        "max_posterior": max_post,
        "optimal_ev": optimal_ev,
        "p_recorded_accused": p_rec_acc,
        "recorded_accused_ev": rec_acc_ev,
        "surfaced_canaries": surfaced_canaries,
        "surfaced_total_leaks": surfaced_total_leaks,
        "planted_canaries": planted_canaries,
        "posterior": dict(post),
    }


def replay_episode_counterfactual(
    episode: EpisodeResult | dict[str, Any],
    strategy: MoleStrategy | RLMole | dict[str, Any] | None = None,
) -> dict[str, Any]:
    ep = to_result(episode) if isinstance(episode, dict) else episode
    strat = coerce_strategy(strategy)
    P = tier_params_for_episode(ep.tier, ep.steps)
    true_mole = generate_world(ep.tier, ep.seed, P).mole
    rec_audit = audit_episode(ep)

    horizon_policy = ScheduleReplayPolicy(ep, target_day="horizon")
    env = Env(ep.tier, ep.seed, mole_strategy=strat)
    horizon_history = replay_schedule(env, horizon_policy)
    accuse_history = horizon_history[: horizon_policy.recorded_prefix_len]

    at_accuse = inspect_observation_history(
        accuse_history,
        tier=ep.tier,
        seed=ep.seed,
        recorded_accused=ep.accused,
        true_mole=true_mole,
    )
    if len(horizon_history) == len(accuse_history):
        at_horizon = dict(at_accuse)
    else:
        at_horizon = inspect_observation_history(
            horizon_history,
            tier=ep.tier,
            seed=ep.seed,
            recorded_accused=ep.accused,
            true_mole=true_mole,
        )

    return {
        "tier": ep.tier,
        "seed": int(ep.seed),
        "agent": ep.agent,
        "strategy": strat.name,
        "true_mole": true_mole,
        "accuse_day": horizon_policy.accuse_day,
        "horizon_day": horizon_policy.horizon_day,
        "recorded_accused": ep.accused,
        "recorded_correct": bool(ep.correct),
        "recorded_score": float(ep.score),
        "recorded_p_accused": rec_audit["p_accused"],
        "recorded_p_top": rec_audit["p_top"],
        "recorded_verdict": rec_audit["verdict"],
        "known_V": at_accuse["known_V"],
        "known_V_horizon": at_horizon["known_V"],
        "p_true_mole": at_accuse["p_true_mole"],
        "p_true_mole_horizon": at_horizon["p_true_mole"],
        "max_posterior": at_accuse["max_posterior"],
        "max_posterior_horizon": at_horizon["max_posterior"],
        "optimal_ev": at_accuse["optimal_ev"],
        "optimal_ev_horizon": at_horizon["optimal_ev"],
        "best_suspect": at_accuse["best_suspect"],
        "best_suspect_horizon": at_horizon["best_suspect"],
        "top_is_true_mole": at_accuse["top_is_true_mole"],
        "top_is_true_mole_horizon": at_horizon["top_is_true_mole"],
        "p_recorded_accused": at_accuse["p_recorded_accused"],
        "surfaced_canaries": at_accuse["surfaced_canaries"],
        "surfaced_canaries_horizon": at_horizon["surfaced_canaries"],
        "surfaced_total_leaks": at_accuse["surfaced_total_leaks"],
        "surfaced_total_leaks_horizon": at_horizon["surfaced_total_leaks"],
        "planted_canaries": at_accuse["planted_canaries"],
        "at_accuse_day": {k: v for k, v in at_accuse.items() if k != "posterior"},
        "at_horizon": {k: v for k, v in at_horizon.items() if k != "posterior"},
    }


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _summarize_paired_episodes(
    strat_eps: list[dict[str, Any]],
    base_eps: list[dict[str, Any]],
) -> dict[str, Any]:
    base_by_key = {(e["agent"], e["seed"]): e for e in base_eps}
    pairs = [(e, base_by_key[(e["agent"], e["seed"])]) for e in strat_eps if (e["agent"], e["seed"]) in base_by_key]

    p_mole = [e["p_true_mole"] for e, _ in pairs]
    p_mole_h = [e["p_true_mole_horizon"] for e, _ in pairs]
    max_p = [e["max_posterior"] for e, _ in pairs]
    max_p_h = [e["max_posterior_horizon"] for e, _ in pairs]
    opt_ev = [e["optimal_ev"] for e, _ in pairs]
    opt_ev_h = [e["optimal_ev_horizon"] for e, _ in pairs]
    known_v = [e["known_V"] for e, _ in pairs]
    surf_can = [float(e["surfaced_canaries"]) for e, _ in pairs]
    surf_can_h = [float(e["surfaced_canaries_horizon"]) for e, _ in pairs]
    surf_tot = [float(e["surfaced_total_leaks"]) for e, _ in pairs]
    surf_tot_h = [float(e["surfaced_total_leaks_horizon"]) for e, _ in pairs]
    planted = [float(e["planted_canaries"]) for e, _ in pairs]
    top_acc = [1.0 if e["top_is_true_mole"] else 0.0 for e, _ in pairs]
    top_acc_h = [1.0 if e["top_is_true_mole_horizon"] else 0.0 for e, _ in pairs]

    p_drop_list = [b["p_true_mole"] - e["p_true_mole"] for e, b in pairs]
    p_h_drop_list = [b["p_true_mole_horizon"] - e["p_true_mole_horizon"] for e, b in pairs]
    max_p_drop_list = [b["max_posterior"] - e["max_posterior"] for e, b in pairs]
    ev_drop_list = [b["optimal_ev"] - e["optimal_ev"] for e, b in pairs]
    ev_h_drop_list = [b["optimal_ev_horizon"] - e["optimal_ev_horizon"] for e, b in pairs]
    can_delta_list = [float(e["surfaced_canaries"] - b["surfaced_canaries"]) for e, b in pairs]
    can_h_delta_list = [float(e["surfaced_canaries_horizon"] - b["surfaced_canaries_horizon"]) for e, b in pairs]
    tot_delta_list = [float(e["surfaced_total_leaks"] - b["surfaced_total_leaks"]) for e, b in pairs]
    tot_h_delta_list = [float(e["surfaced_total_leaks_horizon"] - b["surfaced_total_leaks_horizon"]) for e, b in pairs]

    p_drop_m, p_drop_ci = mean_ci(p_drop_list) if pairs else (0.0, 0.0)
    ev_drop_m, ev_drop_ci = mean_ci(ev_drop_list) if pairs else (0.0, 0.0)
    opt_ev_m, opt_ev_ci = mean_ci(opt_ev) if pairs else (0.0, 0.0)

    return {
        "n": len(pairs),
        "seeds": sorted({int(e["seed"]) for e, _ in pairs}),
        "p_true_mole": _mean(p_mole),
        "p_true_mole_horizon": _mean(p_mole_h),
        "max_posterior": _mean(max_p),
        "max_posterior_horizon": _mean(max_p_h),
        "optimal_ev": opt_ev_m,
        "optimal_ev_ci": opt_ev_ci,
        "optimal_ev_horizon": _mean(opt_ev_h),
        "known_V": _mean(known_v),
        "top_suspect_accuracy": _mean(top_acc),
        "top_suspect_accuracy_horizon": _mean(top_acc_h),
        "surfaced_canaries": _mean(surf_can),
        "surfaced_canaries_horizon": _mean(surf_can_h),
        "surfaced_total_leaks": _mean(surf_tot),
        "surfaced_total_leaks_horizon": _mean(surf_tot_h),
        "planted_canaries": _mean(planted),
        "p_true_mole_drop": p_drop_m,
        "p_true_mole_drop_ci": p_drop_ci,
        "p_true_mole_horizon_drop": _mean(p_h_drop_list),
        "max_posterior_drop": _mean(max_p_drop_list),
        "optimal_ev_drop": ev_drop_m,
        "optimal_ev_drop_ci": ev_drop_ci,
        "optimal_ev_horizon_drop": _mean(ev_h_drop_list),
        "surfaced_canaries_delta": _mean(can_delta_list),
        "surfaced_canaries_horizon_delta": _mean(can_h_delta_list),
        "surfaced_total_leaks_delta": _mean(tot_delta_list),
        "surfaced_total_leaks_horizon_delta": _mean(tot_h_delta_list),
        "episodes": [e for e, _ in pairs],
    }


_SOLVER_SEED_CACHE: dict[tuple[str, int, str], dict[str, Any]] = {}


def _canonical_strategy_key(strategy: MoleStrategy | RLMole) -> str:
    sj = strategy.to_json()
    if sj.get("kind") == "rl_mole":
        payload = {k: v for k, v in sj.items() if k != "name"}
    else:
        payload = {"rules": sj["rules"], "default": sj["default"]}
    return json.dumps(payload, sort_keys=True)


def _solver_seed_worker(task: tuple[str, int, dict[str, Any]]) -> dict[str, Any]:
    tier, seed, strat_json = task
    strat = _strategy(strat_json)
    res = run_episode(Env(tier, seed, mole_strategy=strat), SolverPolicy(tier, act_budget=5.0))
    return {
        "seed": int(seed),
        "score": float(res.score),
        "correct": bool(res.correct),
        "accused": res.accused,
        "final_day": int(res.final_day),
        "end_reason": res.end_reason,
    }


def _run_live_solver(
    tier: str,
    seeds: list[int],
    strategy: MoleStrategy | RLMole,
    workers: int = 1,
) -> list[dict[str, Any]]:
    skey = _canonical_strategy_key(strategy)
    sjson = strategy.to_json()
    missing = [int(seed) for seed in seeds if (tier, int(seed), skey) not in _SOLVER_SEED_CACHE]
    if missing:
        tasks = [(tier, s, sjson) for s in missing]
        if workers and workers > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
                computed = list(pool.map(_solver_seed_worker, tasks))
        else:
            computed = [_solver_seed_worker(t) for t in tasks]
        for row in computed:
            _SOLVER_SEED_CACHE[(tier, int(row["seed"]), skey)] = row
    return [dict(_SOLVER_SEED_CACHE[(tier, int(seed), skey)]) for seed in seeds]


def _summarize_solver(
    rows: list[dict[str, Any]],
    base_rows: list[dict[str, Any]],
    tier: str,
    min_solver_acc: float | None = None,
) -> dict[str, Any]:
    scores = [r["score"] for r in rows]
    base_scores = [r["score"] for r in base_rows]
    score_m, score_ci = mean_ci(scores) if scores else (0.0, 0.0)
    base_score_m = _mean(base_scores)
    acc = _mean([1.0 if r["correct"] else 0.0 for r in rows])
    base_acc = _mean([1.0 if r["correct"] else 0.0 for r in base_rows])
    acc_days = [float(r["final_day"]) for r in rows if r["end_reason"] == "accused"]
    score_deltas = [a - b for a, b in zip(scores, base_scores)]
    delta_m, delta_ci = mean_ci(score_deltas) if score_deltas else (0.0, 0.0)
    min_acc = float(min_solver_acc) if min_solver_acc is not None else float(tier_defaults(tier)["min_solver_acc"])
    score_ok = score_m >= FEASIBLE_SOLVER_RATIO * base_score_m
    feasible = bool(acc >= min_acc and score_ok)
    strict_feasible = bool(acc >= FEASIBLE_SOLVER_ACC and score_ok)
    return {
        "n": len(rows),
        "score": score_m,
        "score_ci": score_ci,
        "accuracy": acc,
        "accuse_day": _mean(acc_days) if acc_days else float(tier_params(tier).n_days),
        "score_delta": delta_m,
        "score_delta_ci": delta_ci,
        "accuracy_delta": acc - base_acc,
        "min_solver_acc": min_acc,
        "feasible": feasible,
        "strict_feasible": strict_feasible,
        "episodes": rows,
    }


def _is_default_strategy(st: MoleStrategy | RLMole) -> bool:
    return (
        isinstance(st, MoleStrategy)
        and st.rules == DEFAULT_STRATEGY.rules
        and st.default == DEFAULT_STRATEGY.default
    )


def evaluate_counterfactual(
    strategies: dict[str, MoleStrategy | RLMole | dict[str, Any]],
    seeds: Iterable[int] = range(30),
    tier: str = "hard",
    run_solver: bool = True,
    sources: Iterable[str] = ("opencode", "inproc"),
    root: str | Path | None = None,
    workers: int = 1,
    min_solver_acc: float | None = None,
) -> dict[str, Any]:
    if not strategies:
        raise ValueError("strategies must not be empty")
    seed_list = [int(s) for s in seeds]
    if not seed_list:
        raise ValueError("seeds must not be empty")
    source_list = tuple(sources)
    loaded = load_v14_frontier_episodes(tier=tier, sources=source_list, seeds=seed_list, root=root)

    paired_seeds = sorted(set.intersection(*(set(loaded[src].keys()) for src in source_list))) if source_list else []
    if not paired_seeds:
        raise ValueError(f"no committed v1.4 {tier} episodes found for requested seeds {seed_list}")

    coerced: dict[str, MoleStrategy | RLMole] = {
        name: coerce_strategy(strat, name=name)
        for name, strat in strategies.items()
    }

    default_key = next(
        (name for name, st in coerced.items() if _is_default_strategy(st)),
        None,
    )

    eval_cache_eps: dict[str, dict[str, list[dict[str, Any]]]] = {}
    eval_cache_solver: dict[str, list[dict[str, Any]]] = {}

    def _run_for(key: str, strat: MoleStrategy | RLMole) -> None:
        eval_cache_eps[key] = {
            src: [replay_episode_counterfactual(loaded[src][s], strat) for s in paired_seeds]
            for src in source_list
        }
        if run_solver:
            eval_cache_solver[key] = _run_live_solver(tier, paired_seeds, strat, workers=workers)

    if default_key is not None:
        _run_for(default_key, coerced[default_key])
        base_eps_by_src = eval_cache_eps[default_key]
        base_solver_rows = eval_cache_solver.get(default_key, [])
    else:
        base_eps_by_src = {
            src: [replay_episode_counterfactual(loaded[src][s], DEFAULT_STRATEGY) for s in paired_seeds]
            for src in source_list
        }
        base_solver_rows = _run_live_solver(tier, paired_seeds, DEFAULT_STRATEGY, workers=workers) if run_solver else []

    for name, strat in coerced.items():
        if name not in eval_cache_eps:
            _run_for(name, strat)

    base_combined_eps = [ep for src in source_list for ep in base_eps_by_src[src]]
    base_per_source = {
        src: _summarize_paired_episodes(base_eps_by_src[src], base_eps_by_src[src])
        for src in source_list
    }
    base_combined = _summarize_paired_episodes(base_combined_eps, base_combined_eps)
    base_solver_summary = (
        _summarize_solver(base_solver_rows, base_solver_rows, tier, min_solver_acc=min_solver_acc)
        if run_solver
        else None
    )
    base_cf_gap = (
        base_solver_summary["score"] - base_combined["optimal_ev"]
        if base_solver_summary is not None
        else None
    )

    out_strategies: dict[str, dict[str, Any]] = {}
    for name, strat in coerced.items():
        per_src = {
            src: _summarize_paired_episodes(eval_cache_eps[name][src], base_eps_by_src[src])
            for src in source_list
        }
        comb_eps = [ep for src in source_list for ep in eval_cache_eps[name][src]]
        combined = _summarize_paired_episodes(comb_eps, base_combined_eps)
        solver_summary = (
            _summarize_solver(eval_cache_solver[name], base_solver_rows, tier, min_solver_acc=min_solver_acc)
            if run_solver
            else None
        )
        cf_gap = (
            solver_summary["score"] - combined["optimal_ev"]
            if solver_summary is not None
            else None
        )
        cf_gap_gain = (
            cf_gap - base_cf_gap
            if (cf_gap is not None and base_cf_gap is not None)
            else None
        )
        per_src_gaps = (
            {src: solver_summary["score"] - per_src[src]["optimal_ev"] for src in source_list}
            if solver_summary is not None
            else {}
        )
        out_strategies[name] = {
            "name": name,
            "strategy_json": strat.to_json(),
            "per_source": per_src,
            "combined": combined,
            "solver": solver_summary,
            "p_true_mole": combined["p_true_mole"],
            "p_true_mole_horizon": combined["p_true_mole_horizon"],
            "max_posterior": combined["max_posterior"],
            "max_posterior_horizon": combined["max_posterior_horizon"],
            "optimal_ev": combined["optimal_ev"],
            "optimal_ev_horizon": combined["optimal_ev_horizon"],
            "surfaced_canaries": combined["surfaced_canaries"],
            "surfaced_canaries_horizon": combined["surfaced_canaries_horizon"],
            "surfaced_total_leaks": combined["surfaced_total_leaks"],
            "surfaced_total_leaks_horizon": combined["surfaced_total_leaks_horizon"],
            "p_true_mole_drop": combined["p_true_mole_drop"],
            "p_true_mole_horizon_drop": combined["p_true_mole_horizon_drop"],
            "max_posterior_drop": combined["max_posterior_drop"],
            "optimal_ev_drop": combined["optimal_ev_drop"],
            "optimal_ev_horizon_drop": combined["optimal_ev_horizon_drop"],
            "surfaced_canaries_delta": combined["surfaced_canaries_delta"],
            "surfaced_total_leaks_delta": combined["surfaced_total_leaks_delta"],
            "solver_score": solver_summary["score"] if solver_summary is not None else None,
            "solver_acc": solver_summary["accuracy"] if solver_summary is not None else None,
            "feasible": solver_summary["feasible"] if solver_summary is not None else None,
            "strict_feasible": solver_summary["strict_feasible"] if solver_summary is not None else None,
            "counterfactual_gap": cf_gap,
            "counterfactual_gap_gain": cf_gap_gain,
            "counterfactual_gap_by_source": per_src_gaps,
        }

    return {
        "tier": tier,
        "seeds": paired_seeds,
        "sources": list(source_list),
        "run_solver": bool(run_solver),
        "baseline": {
            "name": DEFAULT_STRATEGY.name,
            "per_source": base_per_source,
            "combined": base_combined,
            "solver": base_solver_summary,
            "counterfactual_gap": base_cf_gap,
        },
        "strategies": out_strategies,
    }


def load_strategies_spec(path: str | Path | None = None, max_hof: int = 10) -> dict[str, MoleStrategy | RLMole]:
    if path is None:
        return {k: coerce_strategy(v, name=k) for k, v in BUILTIN_CANDIDATES.items()}
    fp = Path(path)
    text = fp.read_text(encoding="utf-8").strip()
    if fp.suffix == ".jsonl":
        out: dict[str, MoleStrategy | RLMole] = {"default_v0": DEFAULT_STRATEGY}
        for idx, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            if len(out) - 1 >= max_hof:
                break
            row = json.loads(line)
            sj = row.get("strategy_json", row.get("strategy", row))
            rank = row.get("rank", idx + 1)
            label = sj.get("name") if isinstance(sj, dict) and sj.get("name") not in (None, "custom", "random") else f"hof_{rank}"
            if label in out:
                label = f"{label}_{idx + 1}"
            out[label] = coerce_strategy(sj, name=label)
        return out
    parsed = json.loads(text)
    if isinstance(parsed, dict) and ("rules" in parsed or "default" in parsed or parsed.get("kind") == "rl_mole"):
        st = coerce_strategy(parsed)
        label = st.name if st.name != DEFAULT_STRATEGY.name else "candidate"
        return {"default_v0": DEFAULT_STRATEGY, label: st}
    if isinstance(parsed, dict):
        out = {k: coerce_strategy(v, name=k) for k, v in parsed.items()}
        if not any(_is_default_strategy(s) for s in out.values()):
            out = {"default_v0": DEFAULT_STRATEGY, **out}
        return out
    if isinstance(parsed, list):
        out = {"default_v0": DEFAULT_STRATEGY}
        for idx, item in enumerate(parsed[:max_hof]):
            label = f"cand_{idx + 1}"
            out[label] = coerce_strategy(item, name=label)
        return out
    raise ValueError(f"unsupported strategy file format in {fp}")


def format_counterfactual_table(report: dict[str, Any]) -> str:
    sources = report["sources"]
    has_solver = bool(report["run_solver"])
    lines = [
        f"Counterfactual Frontier Replay (tier={report['tier']}, n_seeds={len(report['seeds'])}, sources={','.join(sources)})",
        "",
    ]
    headers = [
        "strategy",
        "P(mole) acc/hor",
        "P(mole) drop",
        "opt_EV",
        "EV drop",
        "canaries/leaks",
    ]
    for src in sources:
        headers.append(f"{src} EV (drop)")
    if has_solver:
        headers += ["solver score", "solver acc", "feasible", "CF gap (gain)"]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")

    for name, row in report["strategies"].items():
        comb = row["combined"]
        cols = [
            name,
            f"{comb['p_true_mole']:.3f} / {comb['p_true_mole_horizon']:.3f}",
            f"{comb['p_true_mole_drop']:+.3f}",
            f"{comb['optimal_ev']:.3f}",
            f"{comb['optimal_ev_drop']:+.3f}",
            f"{comb['surfaced_canaries']:.2f} / {comb['surfaced_total_leaks']:.2f}",
        ]
        for src in sources:
            ps = row["per_source"][src]
            cols.append(f"{ps['optimal_ev']:.3f} ({ps['optimal_ev_drop']:+.3f})")
        if has_solver and row["solver"] is not None:
            sol = row["solver"]
            cols += [
                f"{sol['score']:+.3f}",
                f"{sol['accuracy']:.2f}",
                "yes" if sol["feasible"] else "no",
                f"{row['counterfactual_gap']:+.3f} ({row['counterfactual_gap_gain']:+.3f})",
            ]
        lines.append("| " + " | ".join(cols) + " |")
    return "\n".join(lines)


def _compact_json_report(report: dict[str, Any]) -> dict[str, Any]:
    slim_strats: dict[str, Any] = {}
    for name, row in report["strategies"].items():
        slim_row = {k: v for k, v in row.items() if k not in ("per_source", "combined", "solver")}
        slim_row["combined"] = {k: v for k, v in row["combined"].items() if k != "episodes"}
        slim_row["per_source"] = {
            src: {k: v for k, v in d.items() if k != "episodes"}
            for src, d in row["per_source"].items()
        }
        if row["solver"] is not None:
            slim_row["solver"] = {k: v for k, v in row["solver"].items() if k != "episodes"}
        else:
            slim_row["solver"] = None
        slim_strats[name] = slim_row
    return {
        "tier": report["tier"],
        "seeds": report["seeds"],
        "sources": report["sources"],
        "run_solver": report["run_solver"],
        "strategies": slim_strats,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.counterfactual")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="0-29")
    ap.add_argument("--sources", default="opencode,inproc")
    ap.add_argument("--strategy-file", default=None)
    ap.add_argument("--max-hof", type=int, default=10)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--min-solver-acc", type=float, default=None)
    ap.add_argument("--no-solver", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    strategies = load_strategies_spec(args.strategy_file, max_hof=args.max_hof)
    report = evaluate_counterfactual(
        strategies=strategies,
        seeds=seeds,
        tier=args.tier,
        run_solver=not args.no_solver,
        sources=sources,
        workers=args.workers,
        min_solver_acc=args.min_solver_acc,
    )
    output = (
        json.dumps(_compact_json_report(report), indent=2, sort_keys=True)
        if args.json
        else format_counterfactual_table(report)
    )
    print(output)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
