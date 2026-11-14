"""TEST DOUBLE ONLY. A tiny fake of canary.env.Env (CONTRACT section 2-3) for driving agent loops.

Not the game: the mole is fixed ("e03"), nothing leaks, results are canned.
"""
from __future__ import annotations

from canary.types import EpisodeResult, INVESTIGATIVE_TOOLS, LedgerEntry, Step, ToolResult

TOOLS = ["status", "list_employees", "list_documents", "read_access_logs", "search_messages",
         "read_message", "interview", "plant_canary", "check_leak_feed", "restrict_access",
         "unrestrict_access", "advance_day", "accuse"]


class FakeEnv:
    def __init__(self, tier: str = "medium", seed: int = 0, text_provider=None,
                 actions_per_day: int = 8, tool_call_cap: int = 300, n_days: int = 14, mole: str = "e03"):
        self.tier, self.seed = tier, seed
        self.actions_per_day, self.tool_call_cap, self.n_days, self.mole = actions_per_day, tool_call_cap, n_days, mole
        self.day, self.v, self.used_today = 1, 1.0, 0
        self._history: list[Step] = []
        self._ledger: list[LedgerEntry] = []
        self._done, self._accused, self._end = False, None, None

    def tools_spec(self) -> list[dict]:
        return [{"name": n, "description": f"fake {n}", "input_schema": {"type": "object", "properties": {}}} for n in TOOLS]

    def instruction(self) -> str:
        return "FAKE INSTRUCTION: find the mole among e00..e19 and accuse exactly once. Correct: score = V; wrong: score = -1.0."

    @property
    def done(self) -> bool:
        return self._done

    @property
    def history(self) -> list[Step]:
        return self._history

    def score(self) -> float:
        if self._accused is None:
            return 0.0
        return self.v if self._accused == self.mole else -1.0  # contract v0.3

    def ledger(self) -> list[LedgerEntry]:
        return list(self._ledger)

    def _end_with(self, reason: str):
        self._done, self._end = True, reason
        self._ledger.append(LedgerEntry(len(self._history), self.day, "episode_end", {"reason": reason}))

    def call(self, tool: str, args: dict) -> ToolResult:
        args = dict(args or {})
        if self._done:
            r = ToolResult(False, {}, "episode over")
        elif tool not in TOOLS:
            r = ToolResult(False, {}, f"unknown tool {tool}")
        elif tool in INVESTIGATIVE_TOOLS and self.used_today >= self.actions_per_day:
            r = ToolResult(False, {}, "daily action limit; call advance_day")
        else:
            if tool in INVESTIGATIVE_TOOLS:
                self.used_today += 1
            r = ToolResult(True, {"tool": tool})
            if tool == "status":
                r.data = {"day": self.day, "V": self.v, "actions_left_today": self.actions_per_day - self.used_today,
                          "tool_calls_left": self.tool_call_cap - len(self._history)}
            elif tool == "advance_day":
                self.day += 1
                self.used_today = 0
                r.data = {"day": self.day}
            elif tool == "accuse":
                emp = args.get("employee")
                if not isinstance(emp, str):
                    r = ToolResult(False, {}, "employee must be one id")
                else:
                    self._accused = emp
                    self._ledger.append(LedgerEntry(len(self._history), self.day, "accused", {"employee": emp}))
                    r.data = {"accused": emp, "episode_over": True}
        step = Step(t=len(self._history), day=self.day, tool=tool, args=args,
                    result={"ok": r.ok, "data": r.data, "error": r.error})
        if not (self._done and not r.ok and r.error == "episode over"):
            self._history.append(step)
        if not self._done:
            if self._accused is not None:
                self._end_with("accused")
            elif self.day > self.n_days:
                self._end_with("horizon")
            elif len(self._history) >= self.tool_call_cap:
                self._end_with("tool_cap")
        return r

    def result(self, agent_name: str) -> EpisodeResult:
        return EpisodeResult(tier=self.tier, seed=self.seed, agent=agent_name, steps=list(self._history),
                             score=self.score(), accused=self._accused, correct=self._accused == self.mole,
                             final_day=self.day, end_reason=self._end or "error", meta={"fake": True})
