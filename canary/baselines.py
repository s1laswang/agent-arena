"""Simple baseline investigators (owner: HEAD-ENV, shared with INTEGRITY).

All play through the public tool interface only (types.Policy).
"""
from __future__ import annotations

import random
from typing import Any

from .types import Step


def _employees(history: list[Step]) -> list[str]:
    for s in history:
        if s.tool == "list_employees" and s.result.get("ok"):
            data = s.result["data"]
            rows = data.get("employees", data) if isinstance(data, dict) else data
            return [r["id"] for r in rows]
    return []


class DoNothing:
    """Only advances days. Must score 0."""
    name = "do_nothing"
    def reset(self, tools_spec, instruction): pass
    def act(self, history):
        return "advance_day", {}


class StopEarly:
    """Accuses a uniformly random employee on day 1. Expected ≈ V/N."""
    name = "stop_early"
    def __init__(self, seed: int = 0):
        self.seed = seed
    def reset(self, tools_spec, instruction):
        self.rng = random.Random(f"stop_early:{self.seed}")
    def act(self, history):
        emps = _employees(history)
        if not emps:
            return "list_employees", {}
        return "accuse", {"employee": self.rng.choice(emps)}


class RestrictAll:
    """Restricts everyone it can, then accuses at random. Should be far below the solver."""
    name = "restrict_all"
    def __init__(self, seed: int = 0):
        self.seed = seed
    def reset(self, tools_spec, instruction):
        self.rng = random.Random(f"restrict_all:{self.seed}")
        self.i = 0
    def act(self, history):
        emps = _employees(history)
        if not emps:
            return "list_employees", {}
        if history and history[-1].tool == "restrict_access" and not history[-1].result.get("ok") \
                and "daily" in (history[-1].result.get("error") or ""):
            return "advance_day", {}
        if self.i < len(emps):
            self.i += 1
            return "restrict_access", {"employee": emps[self.i - 1]}
        return "accuse", {"employee": self.rng.choice(emps)}


class RandomPolicy:
    """Uniformly random valid-ish tool calls; accuses with small prob per step."""
    name = "random"
    def __init__(self, seed: int = 0, p_accuse: float = 0.02):
        self.seed, self.p_accuse = seed, p_accuse
    def reset(self, tools_spec, instruction):
        self.rng = random.Random(f"random:{self.seed}")
    def act(self, history) -> tuple[str, dict[str, Any]]:
        r = self.rng
        emps = _employees(history)
        if not emps:
            return "list_employees", {}
        day = 1
        for s in reversed(history):
            day = s.day; break
        if r.random() < self.p_accuse:
            return "accuse", {"employee": r.choice(emps)}
        e = r.choice(emps)
        choices = [
            ("status", {}), ("advance_day", {}), ("advance_day", {}), ("check_leak_feed", {}),
            ("list_documents", {}),
            ("read_access_logs", {"day_from": max(1, day - 2), "day_to": max(1, day - 1)}),
            ("interview", {"employee": e, "topic": r.choice(
                ["recent_documents", "contacts_outside", "workload", "access_needs"])}),
            ("plant_canary", {"doc_title": "Q3 plan", "assignment": {
                x: r.choice(["A", "B"]) for x in r.sample(emps, min(4, len(emps)))}}),
            ("search_messages", {"query": "report"}),
        ]
        return choices[r.randrange(len(choices))]


BASELINES = {"do_nothing": DoNothing, "stop_early": StopEarly, "random": RandomPolicy,
             "restrict_all": RestrictAll}


class Heuristic:
    """The 'obvious' investigator: intersect suspects with the recipients of every leaked doc,
    split the remaining suspects in half with a canary each day, accuse when one is left
    (or on day `deadline`, the most-frequent leak recipient). Ignores logs/interviews/V timing.
    """
    name = "heuristic"
    def __init__(self, seed: int = 0, deadline: int = 12):
        self.seed, self.deadline = seed, deadline
    def reset(self, tools_spec, instruction):
        self.rng = random.Random(f"heuristic:{self.seed}")
        self.day_done: set[tuple[int, str]] = set()
        self.docs: dict[str, dict] = {}
    def _last(self, history, tool):
        for s in reversed(history):
            if s.tool == tool and s.result.get("ok"):
                return s.result["data"]
        return None
    def act(self, history):
        emps = _employees(history)
        if not emps:
            return "list_employees", {}
        day = history[-1].day if history else 1
        if history[-1].tool == "advance_day" and history[-1].result.get("ok"):
            day = history[-1].result["data"]["day"]
        def once(tag):
            k = (day, tag)
            if k in self.day_done:
                return False
            self.day_done.add(k); return True
        if once("docs"):
            return "list_documents", {}
        d = self._last(history, "list_documents")
        for doc in (d or {}).get("documents", []):
            self.docs[doc["doc_id"]] = doc
        if once("feed"):
            return "check_leak_feed", {}
        suspects = set(emps)
        feed = (self._last(history, "check_leak_feed") or {}).get("items", [])
        for it in feed:
            doc = self.docs.get(it["doc_id"])
            if not doc:
                continue
            if doc.get("is_canary") and it.get("variant") and doc.get("variants"):
                grp = set(doc["variants"].get(it["variant"], []))
            else:
                grp = set(doc["recipients"])
            if suspects & grp:
                suspects &= grp
        ranked = sorted(suspects)
        if len(ranked) == 1 or day >= self.deadline:
            return "accuse", {"employee": ranked[0] if len(ranked) == 1 else self.rng.choice(ranked)}
        if once("canary") and len(ranked) >= 2:
            self.rng.shuffle(ranked)
            half = len(ranked) // 2
            assign = {e: ("A" if i < half else "B") for i, e in enumerate(ranked)}
            return "plant_canary", {"doc_title": f"Board update {day}", "assignment": assign}
        return "advance_day", {}


BASELINES["heuristic"] = Heuristic
