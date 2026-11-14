"""Game API for the Canary browser game. Owner: HARNESS (WS6).

The page (game/app.js) runs this exact file in Pyodide; tests/test_game.py runs it in CPython. All game
logic stays in the real `canary` package: this module only wraps one Env episode with JSON in and out.

Rules of the page:
  * medium tier, PUBLIC dev seeds 3000-9999 only. Judge, held-out and train seeds are refused, so the
    page can never be used to explore a benchmark world.
  * The page calls a tool only when the player presses its button. It never calls `status` or anything
    else on its own, because that would spend the player's budget and change the episode.
  * The truth (who the mole was, the solver's score on the same seed) is revealed only after the
    episode is over.
"""
from __future__ import annotations

import json
from typing import Any

from canary.env import Env
from canary.rules import TIERS_VERSION

TIER = "medium"
SEED_MIN, SEED_MAX = 3000, 9999


def check_seed(seed: Any) -> int:
    try:
        s = int(seed)
    except (TypeError, ValueError):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX}") from None
    if not SEED_MIN <= s <= SEED_MAX or str(seed).strip() != str(s):
        raise ValueError(f"seed must be an integer in {SEED_MIN}..{SEED_MAX} (public dev seeds)")
    return s


class Game:
    def __init__(self, seed: Any):
        self.seed = check_seed(seed)
        self.env = Env(TIER, self.seed)
        self.actions: list[list[Any]] = []

    def spec_json(self) -> str:
        return json.dumps({"tier": TIER, "seed": self.seed, "tiers_version": TIERS_VERSION,
                           "tools": self.env.tools_spec(), "instruction": self.env.instruction()})

    def call_json(self, tool: str, args_json: str) -> str:
        try:
            args = json.loads(args_json) if args_json else {}
        except ValueError:
            return json.dumps({"ok": False, "data": {}, "error": "arguments are not valid JSON", "done": self.env.done})
        res = self.env.call(tool, args)
        self.actions.append([tool, args])
        return json.dumps({"ok": res.ok, "data": res.data, "error": res.error, "done": self.env.done},
                          default=str)

    def reveal_json(self) -> str:
        """Only after the episode ends: the truth, your result and the solver's on the same seed."""
        if not self.env.done:
            return json.dumps({"error": "the episode is not over yet"})
        v = self.env.verdict()
        return json.dumps({"seed": self.seed, "tier": TIER, "tiers_version": TIERS_VERSION,
                           "you": {"score": v["score"], "end_reason": v["end_reason"], "accused": v["accused"],
                                   "correct": v["correct"], "final_day": v["final_day"],
                                   "tool_calls": len(self.actions)},
                           "mole": self.env._world.mole,
                           "solver": solver_result(self.seed)})

    def actions_json(self) -> str:
        return json.dumps({"tier": TIER, "seed": self.seed, "tiers_version": TIERS_VERSION, "actions": self.actions})


def solver_result(seed: int) -> dict[str, Any]:
    from canary.solver.policy import SolverPolicy
    env = Env(TIER, check_seed(seed))
    pol = SolverPolicy()
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        env.call(*pol.act(env.history))
    v = env.verdict()
    return {"score": v["score"], "correct": v["correct"], "final_day": v["final_day"], "tool_calls": len(env.history)}


def replay(seed: Any, actions: list[list[Any]]) -> dict[str, Any]:
    """Replay a recorded action list; returns the verdict. Used by the browser-vs-Python parity test."""
    g = Game(seed)
    for tool, args in actions:
        g.call_json(tool, json.dumps(args))
    return g.env.verdict()
