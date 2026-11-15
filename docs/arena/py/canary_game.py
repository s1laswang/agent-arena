from __future__ import annotations

import json
from typing import Any

from canary.env import Env
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION

TIER = "medium"
SEED_MIN, SEED_MAX = 3000, 9999
DUEL_SEED_MIN, DUEL_SEED_MAX = 0, 59
ALLOWED_TIERS = ("medium", "hard")
MAX_SOLVER_ITERS = 1000


def _strict_int(seed: Any) -> int:
    if isinstance(seed, (bool, float)) or seed is None:
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}")
    try:
        s = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}") from None
    if str(seed).strip() != str(s):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}")
    return s


def check_seed(seed: Any) -> int:
    s = _strict_int(seed)
    if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or not (SEED_MIN <= s <= SEED_MAX):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")
    return s


def _check_extended_seed(seed: Any, tier: str, mode: str | None) -> int:
    s = _strict_int(seed)
    if s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s >= 800_000 or s < 0:
        raise ValueError("benchmark and negative seeds are refused")
    if SEED_MIN <= s <= SEED_MAX:
        return s
    if DUEL_SEED_MIN <= s <= DUEL_SEED_MAX and (mode in ("duel", "living") or (mode is None and tier == "hard")):
        return s
    raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")


class Game:
    def __init__(self, seed: Any, tier: str | None = None, mode: str | None = None) -> None:
        if tier is None and mode is None:
            resolved_tier = TIER
            resolved_seed = check_seed(seed)
        else:
            resolved_tier = TIER if tier is None else str(tier).strip()
            if resolved_tier not in ALLOWED_TIERS:
                raise ValueError(f"tier must be one of {ALLOWED_TIERS}")
            norm_mode = None if mode is None else str(mode).strip().lower()
            resolved_seed = _check_extended_seed(seed, resolved_tier, norm_mode)
        self.tier = resolved_tier
        self.seed = resolved_seed
        self.env = Env(self.tier, self.seed)
        self.actions: list[list[Any]] = []

    def spec_json(self) -> str:
        return json.dumps(
            {
                "tier": self.tier,
                "seed": self.seed,
                "tiers_version": TIERS_VERSION,
                "tools": self.env.tools_spec(),
                "instruction": self.env.instruction(),
            }
        )

    def call_json(self, tool: str, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except ValueError:
            return json.dumps(
                {
                    "ok": False,
                    "data": {},
                    "error": "arguments are not valid JSON",
                    "done": self.env.done,
                }
            )
        if not isinstance(args, dict):
            return json.dumps(
                {
                    "ok": False,
                    "data": {},
                    "error": "arguments must be a JSON object",
                    "done": self.env.done,
                }
            )
        res = self.env.call(tool, args)
        self.actions.append([tool, args])
        return json.dumps(
            {"ok": res.ok, "data": res.data, "error": res.error, "done": self.env.done},
            default=str,
        )

    def reveal_json(self) -> str:
        if not self.env.done:
            return json.dumps({"error": "the episode is not over yet"})
        v = self.env.verdict()
        return json.dumps(
            {
                "seed": self.seed,
                "tier": self.tier,
                "tiers_version": TIERS_VERSION,
                "you": {
                    "score": v["score"],
                    "end_reason": v["end_reason"],
                    "accused": v["accused"],
                    "correct": v["correct"],
                    "final_day": v["final_day"],
                    "tool_calls": len(self.actions),
                },
                "mole": self.env._world.mole,
                "solver": solver_result(self.seed, tier=self.tier),
            }
        )

    def actions_json(self) -> str:
        return json.dumps(
            {
                "tier": self.tier,
                "seed": self.seed,
                "tiers_version": TIERS_VERSION,
                "actions": self.actions,
            }
        )


def solver_result(seed: int, tier: str | None = None) -> dict[str, Any]:
    from canary.solver.policy import SolverPolicy

    if tier is None:
        resolved_tier = TIER
        resolved_seed = check_seed(seed)
    else:
        resolved_tier = str(tier).strip()
        if resolved_tier not in ALLOWED_TIERS:
            raise ValueError(f"tier must be one of {ALLOWED_TIERS}")
        resolved_seed = _check_extended_seed(seed, resolved_tier, "duel" if resolved_tier == "hard" else None)
    env = Env(resolved_tier, resolved_seed)
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(MAX_SOLVER_ITERS):
        if env.done:
            break
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    v = env.verdict()
    return {
        "score": v["score"],
        "correct": v["correct"],
        "final_day": v["final_day"],
        "tool_calls": len(env.history),
    }


def replay(seed: Any, actions: list[list[Any]], tier: str | None = None) -> dict[str, Any]:
    g = Game(seed, tier=tier, mode="duel" if tier == "hard" else None)
    for tool, args in actions:
        g.call_json(tool, json.dumps(args))
    return g.env.verdict()
