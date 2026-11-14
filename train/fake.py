"""Tiny stand-in Env + policy that follow the contract (canary.env.Env / types.Policy).

Used by tests and the CPU smoke path so train/ is provable before the real Env/solver land.
NOT the game: the 'mole' is just announced by a clue in check_leak_feed.
"""
from __future__ import annotations

import random

from canary.types import EpisodeResult, Step, ToolResult


class FakeEnv:
    def __init__(self, tier: str = "easy", seed: int = 0, text_provider=None):
        self.tier, self.seed = tier, seed
        rng = random.Random(seed)
        self.n = {"easy": 4, "medium": 6, "hard": 8}.get(tier, 4)
        self.mole = f"e{rng.randrange(self.n):02d}"
        self.day, self.v, self._done, self._score, self._accused = 1, 1.0, False, 0.0, None
        self._hist: list[Step] = []

    def tools_spec(self) -> list[dict]:
        emp = {"type": "object", "properties": {"employee": {"type": "string"}},
               "required": ["employee"], "additionalProperties": False}
        empty = {"type": "object", "properties": {}, "additionalProperties": False}
        return [
            {"name": "status", "description": "Day, value, caps.", "input_schema": empty},
            {"name": "list_employees", "description": "All staff.", "input_schema": empty},
            {"name": "check_leak_feed", "description": "Leaked docs.", "input_schema": empty},
            {"name": "advance_day", "description": "Close the day.", "input_schema": empty},
            {"name": "accuse", "description": "Accuse one employee, once.", "input_schema": emp},
        ]

    def instruction(self) -> str:
        return "Fake Canary. Find the mole among the employees and accuse them."

    @property
    def done(self) -> bool:
        return self._done

    @property
    def history(self) -> list[Step]:
        return list(self._hist)

    def score(self) -> float:
        return self._score

    def ledger(self):
        return []

    def call(self, tool: str, args: dict) -> ToolResult:
        if self._done:
            r = ToolResult(False, {}, "episode over")
        elif tool == "status":
            r = ToolResult(True, {"day": self.day, "V": round(self.v, 3)})
        elif tool == "list_employees":
            r = ToolResult(True, {"employees": [{"id": f"e{i:02d}"} for i in range(self.n)]})
        elif tool == "check_leak_feed":
            feed = [{"surfaced_day": self.day, "variant": self.mole}] if self.day >= 2 else []
            r = ToolResult(True, {"leaks": feed})
        elif tool == "advance_day":
            self.day += 1
            self.v -= 0.05
            r = ToolResult(True, {"day": self.day})
            if self.day > 14:
                self._done = True
        elif tool == "accuse" and set(args) == {"employee"}:
            self._accused = args["employee"]
            self._score = self.v if self._accused == self.mole else 0.0
            self._done = True
            r = ToolResult(True, {"accused": self._accused, "episode_over": True})
        else:
            r = ToolResult(False, {}, f"bad call {tool}")
        self._hist.append(Step(len(self._hist), self.day, tool, dict(args),
                               {"ok": r.ok, "data": r.data, "error": r.error}))
        if len(self._hist) >= 60:
            self._done = True
        return r

    def result(self, agent_name: str) -> EpisodeResult:
        end = "accused" if self._accused else ("horizon" if self.day > 14 else "tool_cap")
        return EpisodeResult(self.tier, self.seed, agent_name, self.history, self._score,
                             self._accused, self._accused == self.mole, self.day, end)


class FakeSolver:
    """Reads the feed, advances until the leak shows, accuses the variant."""
    name = "fake_solver"

    def reset(self, tools_spec, instruction):
        pass

    def act(self, history):
        if not history:
            return "list_employees", {}
        last = history[-1]
        if last.tool == "check_leak_feed" and last.result["data"].get("leaks"):
            return "accuse", {"employee": last.result["data"]["leaks"][0]["variant"]}
        if last.tool == "check_leak_feed":
            return "advance_day", {}
        return "check_leak_feed", {}
