from __future__ import annotations

import json
import math
from typing import Any

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION
from canary.solver.policy import SolverPolicy

ALLOWED_TIERS = ("medium", "hard")
ALLOWED_MODES = ("duel", "solver", "mole", "living")
PUBLIC_SEED_MIN = 3000
PUBLIC_SEED_MAX = 9999
DUEL_SEED_MIN = 0
DUEL_SEED_MAX = 59
MAX_SOLVER_ITERS = 1000

_SOLVER_ROLLOUT_CACHE: dict[tuple[str, int], dict[str, Any]] = {}


def parse_strict_int(value: Any) -> int:
    if isinstance(value, (bool, float)) or value is None:
        raise ValueError("seed must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError("seed must be an integer") from None
    if str(value).strip() != str(parsed):
        raise ValueError("seed must be an integer")
    return parsed


def check_tier(tier: Any) -> str:
    if not isinstance(tier, str) or tier.strip() not in ALLOWED_TIERS:
        raise ValueError(f"tier must be one of {ALLOWED_TIERS}")
    return tier.strip()


def check_mode(mode: Any) -> str | None:
    if mode is None:
        return None
    if not isinstance(mode, str) or mode.strip().lower() not in ALLOWED_MODES:
        raise ValueError(f"mode must be one of {ALLOWED_MODES}")
    return mode.strip().lower()


def check_seed(seed: Any, tier: Any = "hard", mode: Any = None) -> int:
    s = parse_strict_int(seed)
    check_tier("hard" if tier is None else tier)
    mode_val = check_mode(mode)
    if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s >= 800_000 or s < 0:
        raise ValueError("benchmark and negative seeds are refused")
    if PUBLIC_SEED_MIN <= s <= PUBLIC_SEED_MAX:
        return s
    if DUEL_SEED_MIN <= s <= DUEL_SEED_MAX and mode_val in (None, "duel", "living"):
        return s
    raise ValueError(
        f"seed must be in {PUBLIC_SEED_MIN}..{PUBLIC_SEED_MAX} (or {DUEL_SEED_MIN}..{DUEL_SEED_MAX} in duel mode)"
    )


validate_seed = check_seed
check_arena_seed = check_seed


def _normalize_tier_seed(first: Any, second: Any = "hard", mode: Any = None) -> tuple[str, int, str]:
    mode_val = check_mode(mode)
    if isinstance(first, str) and first.strip() in ALLOWED_TIERS:
        tier_val = check_tier(first)
        seed_val = check_seed(second, tier=tier_val, mode=mode_val)
    else:
        tier_val = check_tier("hard" if second is None else second)
        seed_val = check_seed(first, tier=tier_val, mode=mode_val)
    resolved_mode = mode_val or ("duel" if seed_val <= DUEL_SEED_MAX else "solver")
    return tier_val, seed_val, resolved_mode


def _posterior_metrics(post: dict[str, float], n_employees: int) -> tuple[float, float]:
    probs = [float(p) for p in post.values() if float(p) > 0.0]
    if not probs:
        n = max(1, int(n_employees))
        return round(1.0 / n, 6), round(math.log2(n), 6)
    top_prob = round(max(probs), 6)
    entropy = -sum(p * math.log2(p) for p in probs if p > 0.0)
    return top_prob, round(max(0.0, entropy), 6)


def _build_solver_rollout(tier_val: str, seed_val: int) -> dict[str, Any]:
    key = (tier_val, seed_val)
    cached = _SOLVER_ROLLOUT_CACHE.get(key)
    if cached is not None:
        return cached

    env = Env(tier_val, seed_val)
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    n_emp = TIERS[tier_val].n_employees
    n_days = TIERS[tier_val].n_days

    canaries_planted = 0
    interviews_done = 0
    day_snapshots: dict[int, dict[str, Any]] = {}

    def capture(day_num: int) -> None:
        top_p, ent = _posterior_metrics(pol.post, n_emp)
        day_snapshots[day_num] = {
            "day": int(day_num),
            "visible_V": float(env.visible_V()),
            "canaries_planted": int(canaries_planted),
            "interviews_done": int(interviews_done),
            "restricted_count": int(len(env._restricted)),
            "tool_calls_so_far": int(len(env.history)),
            "top_posterior_prob": top_p,
            "entropy_bits": ent,
            "finished": bool(env.done),
        }

    capture(1)
    for _ in range(MAX_SOLVER_ITERS):
        if env.done:
            break
        cur_day = env.day
        tool, args = pol.act(list(env.history))
        res = env.call(tool, args)
        if res.ok:
            if tool == "plant_canary":
                canaries_planted += 1
            elif tool == "interview":
                interviews_done += 1
        capture(cur_day)
        if env.day != cur_day:
            capture(env.day)

    verdict = env.verdict()
    final_day = int(verdict["final_day"])
    last_snap = day_snapshots.get(final_day) or day_snapshots[max(day_snapshots)]
    for d in range(1, n_days + 1):
        if d not in day_snapshots:
            prev_days = [k for k in day_snapshots if k < d]
            src = day_snapshots[max(prev_days)] if prev_days else last_snap
            snap_copy = dict(src)
            snap_copy["day"] = min(d, final_day) if src["finished"] else d
            day_snapshots[d] = snap_copy

    final_payload = {
        "accused": verdict["accused"],
        "score": verdict["score"],
        "correct": verdict["correct"],
        "final_day": final_day,
        "tool_calls": len(env.history),
    }
    rollout = {
        "tier": tier_val,
        "seed": seed_val,
        "n_days": n_days,
        "days": day_snapshots,
        "final": final_payload,
    }
    _SOLVER_ROLLOUT_CACHE[key] = rollout
    return rollout


def solver_result(first: Any, second: Any = "hard") -> dict[str, Any]:
    tier_val, seed_val, _ = _normalize_tier_seed(first, second, mode="duel")
    rollout = _build_solver_rollout(tier_val, seed_val)
    return dict(rollout["final"])


def solver_day_state(first: Any, second: Any, day: Any = 1, done: bool = False) -> dict[str, Any]:
    tier_val, seed_val, _ = _normalize_tier_seed(first, second, mode="duel")
    day_int = max(1, parse_strict_int(day))
    rollout = _build_solver_rollout(tier_val, seed_val)
    clamped = min(day_int, int(rollout["n_days"]))
    snap = rollout["days"][clamped]
    is_done = bool(done)
    if is_done:
        status = "done"
    elif snap["finished"]:
        status = "sealed_accusation"
    else:
        status = "hunting"
    return {
        "day": int(snap["day"]),
        "visible_V": snap["visible_V"],
        "canaries_planted": snap["canaries_planted"],
        "interviews_done": snap["interviews_done"],
        "restricted_count": snap["restricted_count"],
        "tool_calls_so_far": snap["tool_calls_so_far"],
        "top_posterior_prob": snap["top_posterior_prob"],
        "entropy_bits": snap["entropy_bits"],
        "status": status,
        "final": dict(rollout["final"]) if is_done else None,
    }


def solver_day_state_json(first: Any, second: Any, day: Any = 1, done: bool = False) -> str:
    return json.dumps(solver_day_state(first, second, day=day, done=done))


class SolverSession:
    def __init__(self, first: Any, second: Any = "hard") -> None:
        tier_val, seed_val, _ = _normalize_tier_seed(first, second, mode="duel")
        runtime = Env(tier_val, seed_val)
        policy = SolverPolicy()
        policy.reset(runtime.tools_spec(), runtime.instruction())
        n_emp = TIERS[tier_val].n_employees
        counts = {"canaries": 0, "interviews": 0}

        def _step() -> dict[str, Any]:
            if runtime.done:
                top_p, ent = _posterior_metrics(policy.post, n_emp)
                return {
                    "step_index": len(runtime.history),
                    "day": runtime.day,
                    "tool": "[SEALED]",
                    "ok": True,
                    "done": True,
                    "visible_V": runtime.visible_V(),
                    "top_posterior_prob": top_p,
                    "entropy_bits": ent,
                    "sealed": True,
                }
            day_before = runtime.day
            tool, args = policy.act(list(runtime.history))
            res = runtime.call(tool, args)
            if res.ok:
                if tool == "plant_canary":
                    counts["canaries"] += 1
                elif tool == "interview":
                    counts["interviews"] += 1
            top_p, ent = _posterior_metrics(policy.post, n_emp)
            is_accuse = tool == "accuse"
            return {
                "step_index": len(runtime.history) - 1,
                "day": day_before,
                "tool": "[SEALED]" if is_accuse else tool,
                "ok": res.ok,
                "done": runtime.done,
                "visible_V": runtime.visible_V(),
                "canaries_planted": counts["canaries"],
                "interviews_done": counts["interviews"],
                "tool_calls_so_far": len(runtime.history),
                "top_posterior_prob": top_p,
                "entropy_bits": ent,
                "sealed": is_accuse,
            }

        def _reveal(human_done: bool = False) -> dict[str, Any]:
            if not human_done or not runtime.done:
                return {"error": "the episode is not over yet"}
            v = runtime.verdict()
            return {
                "accused": v["accused"],
                "score": v["score"],
                "correct": v["correct"],
                "final_day": v["final_day"],
                "tool_calls": len(runtime.history),
            }

        self.tier = tier_val
        self.seed = seed_val
        self.step = _step
        self.reveal = _reveal


def solver_step(target: Any, policy: SolverPolicy | None = None) -> dict[str, Any]:
    if isinstance(target, SolverSession):
        return target.step()
    if isinstance(target, Env):
        pol = policy
        if pol is None:
            pol = SolverPolicy()
            pol.reset(target.tools_spec(), target.instruction())
        if target.done:
            return {"tool": "[SEALED]", "ok": True, "done": True, "sealed": True}
        day_before = target.day
        tool, args = pol.act(list(target.history))
        res = target.call(tool, args)
        is_accuse = tool == "accuse"
        return {
            "step_index": len(target.history) - 1,
            "day": day_before,
            "tool": "[SEALED]" if is_accuse else tool,
            "ok": res.ok,
            "done": target.done,
            "visible_V": target.visible_V(),
            "sealed": is_accuse,
        }
    raise TypeError("target must be a SolverSession or Env")


class ArenaGame:
    def __init__(self, first: Any, second: Any = "hard", mode: Any = None) -> None:
        tier_val, seed_val, mode_val = _normalize_tier_seed(first, second, mode=mode)
        runtime = Env(tier_val, seed_val)
        actions: list[list[Any]] = []

        def _spec_json() -> str:
            return json.dumps(
                {
                    "tier": tier_val,
                    "seed": seed_val,
                    "mode": mode_val,
                    "tiers_version": TIERS_VERSION,
                    "tools": runtime.tools_spec(),
                    "instruction": runtime.instruction(),
                }
            )

        def _call_json(tool: str, args_json: str = "{}") -> str:
            try:
                args = json.loads(args_json) if args_json else {}
            except ValueError:
                return json.dumps(
                    {
                        "ok": False,
                        "data": {},
                        "error": "arguments are not valid JSON",
                        "done": runtime.done,
                    }
                )
            if not isinstance(args, dict):
                return json.dumps(
                    {
                        "ok": False,
                        "data": {},
                        "error": "arguments must be a JSON object",
                        "done": runtime.done,
                    }
                )
            res = runtime.call(tool, args)
            actions.append([tool, args])
            return json.dumps(
                {
                    "ok": res.ok,
                    "data": res.data,
                    "error": res.error,
                    "done": runtime.done,
                },
                default=str,
            )

        def _call_tool(tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
            return json.loads(_call_json(tool, json.dumps(args or {})))

        def _actions_json() -> str:
            return json.dumps(
                {
                    "tier": tier_val,
                    "seed": seed_val,
                    "tiers_version": TIERS_VERSION,
                    "actions": list(actions),
                }
            )

        def _reveal_json() -> str:
            if not runtime.done:
                return json.dumps({"error": "the episode is not over yet"})
            v = runtime.verdict()
            return json.dumps(
                {
                    "seed": seed_val,
                    "tier": tier_val,
                    "tiers_version": TIERS_VERSION,
                    "you": {
                        "score": v["score"],
                        "end_reason": v["end_reason"],
                        "accused": v["accused"],
                        "correct": v["correct"],
                        "final_day": v["final_day"],
                        "tool_calls": len(actions),
                    },
                    "mole": runtime._world.mole,
                    "solver": solver_result(seed_val, tier_val),
                }
            )

        self.tier = tier_val
        self.seed = seed_val
        self.mode = mode_val
        self.tiers_version = TIERS_VERSION
        self.spec_json = _spec_json
        self.call_json = _call_json
        self.callTool = _call_tool
        self.actions_json = _actions_json
        self.reveal_json = _reveal_json
        self.history_len = lambda: len(runtime.history)
        self.is_done = lambda: bool(runtime.done)
        self.visible_v = lambda: float(runtime.visible_V())


Game = ArenaGame


def replay(first: Any, actions: list[list[Any]], tier: str = "hard") -> dict[str, Any]:
    tier_val, seed_val, _ = _normalize_tier_seed(first, tier, mode="duel")
    runtime = Env(tier_val, seed_val)
    for tool, args in actions:
        runtime.call(tool, args if isinstance(args, dict) else {})
    return runtime.verdict()
