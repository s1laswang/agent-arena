"""Cheap investigator population for the Forge (proxy for a competent LLM).

HintedHeuristic: evidence-only bisection. Intersects suspects with every leaked doc's recipients
(canary variant groups when the leak is a canary), splits the remaining suspects with one canary per
day, ignores logs/decoy/interviews entirely, and never gambles: it accuses only when one suspect is
left; on the last day it accuses only if P(correct)*V - (1-P) > 0 (score for a wrong accusation is -1).
"""
from __future__ import annotations

import random
import re

from canary.baselines import _employees


class HintedHeuristic:
    name = "hinted_heuristic"

    def __init__(self, seed: int = 0, n_days: int = 14):
        self.seed, self.n_days = seed, n_days

    def reset(self, tools_spec, instruction):
        self.rng = random.Random(f"hinted:{self.seed}")
        m = re.search(r"at most (\d+) days", instruction or "")
        self.n_days = int(m.group(1)) if m else self.n_days
        m = re.search(r"at most (\d+) distinct variant", instruction or "")
        self.k = max(2, min(4, int(m.group(1)))) if m else 2
        self.done: set[tuple[int, str]] = set()
        self.docs: dict[str, dict] = {}
        self.V = 1.0

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
            day = history[-1].result["data"].get("day", day)

        def once(tag):
            if (day, tag) in self.done:
                return False
            self.done.add((day, tag))
            return True

        if once("status"):
            return "status", {}
        st = self._last(history, "status") or {}
        self.V = st.get("V", st.get("value", self.V))
        if once("docs"):
            return "list_documents", {}
        for doc in (self._last(history, "list_documents") or {}).get("documents", []):
            self.docs[doc["doc_id"]] = doc
        if once("feed"):
            return "check_leak_feed", {}
        suspects = set(emps)
        for it in (self._last(history, "check_leak_feed") or {}).get("items", []):
            doc = self.docs.get(it.get("doc_id"))
            if not doc:
                continue
            if it.get("variant") and doc.get("variants"):
                grp = set(doc["variants"].get(it["variant"], []))
            else:
                grp = set(doc.get("recipients", []))
            if suspects & grp:
                suspects &= grp
        ranked = sorted(suspects)
        if len(ranked) == 1:
            return "accuse", {"employee": ranked[0]}
        if day >= self.n_days:
            p = 1.0 / len(ranked)
            if p * float(self.V or 0) - (1 - p) > 0:
                return "accuse", {"employee": self.rng.choice(ranked)}
            return "advance_day", {}
        if once("canary"):
            self.rng.shuffle(ranked)
            labels = "ABCD"[: self.k]
            assign = {e: labels[i * self.k // len(ranked)] for i, e in enumerate(ranked)}
            return "plant_canary", {"doc_title": f"Board update {day}", "assignment": assign}
        return "advance_day", {}
