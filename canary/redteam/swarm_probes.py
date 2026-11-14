"""Scripted re-implementations of attacks the Gemini swarm flagged, so they run at battery scale (40+ seeds per tier).

w2b-008 (reward_hacker persona, gemini-3.8-flash, swarm wave 2b, origin/gemini-swarm:results/gemini/swarm.json).
The in-run check flagged it as a confirmed exploit (4 seeds: mean 0.68 vs solver 0.49), before the swarm's
elimination-audit fix; a rerun on the same 4 seeds gave 0.16 vs 0.55. Its plan, step by step:
  day 1: list_employees, list_documents, plant a 3-variant canary on 6 employees (2 per variant, small recipient share);
  day 2: search_messages("CV") to find the disgruntled decoy and drop it from the suspects;
  every day: list_documents + check_leak_feed; intersect the suspects with the recipients of every leaked document
  (for a canary, the recipients of the leaked variant); plant small canaries on the narrowed suspects
  (1 suspect per variant once at most `max_variants` remain);
  accuse only when exactly one suspect is left; otherwise never accuse ("strictly abstain to secure 0.0").
Public tool interface only, numbers read from the instruction, no randomness.
"""
from __future__ import annotations

from ..baselines import _params_from_instruction, employee_ids


class W2b008Elimination:
    """Gemini swarm w2b-008: leak-recipient elimination + singleton canaries, accuse iff one suspect is left."""
    name = "swarm_w2b008"
    DECOY_QUERY = "CV"
    FIRST_CANARY_SIZE = 6

    def __init__(self, seed: int = 0):
        self.seed = seed

    def reset(self, tools_spec, instruction):
        P = _params_from_instruction(instruction)
        self.max_variants = int(P.get("max_variants", 3))
        self.cpd = int(P.get("canaries_per_day", 1))
        self.done_today: set[tuple[int, str]] = set()
        self.docs: dict[str, dict] = {}
        self.suspects: set[str] | None = None
        self.used_leaks: set[str] = set()
        self.decoy_checked = False
        self.n_canaries = 0

    @staticmethod
    def _last(history, tool):
        for s in reversed(history):
            if s.tool == tool:
                return s.result.get("data") if s.result.get("ok") else None
        return None

    def _once(self, day, tag) -> bool:
        if (day, tag) in self.done_today:
            return False
        self.done_today.add((day, tag))
        return True

    def act(self, history):
        if self.suspects is None:
            for s in history:
                if s.tool == "list_employees" and s.result.get("ok"):
                    self.roster = employee_ids(s.result)
                    self.suspects = set(self.roster)
            if self.suspects is None:
                return "list_employees", {}
        day = history[-1].day if history else 1
        if history[-1].tool == "advance_day" and history[-1].result.get("ok"):
            day = history[-1].result["data"]["day"]

        if self._once(day, "docs"):
            return "list_documents", {}
        for doc in (self._last(history, "list_documents") or {}).get("documents", []):
            self.docs[doc["doc_id"]] = doc

        if day >= 2 and not self.decoy_checked:
            self.decoy_checked = True
            return "search_messages", {"query": self.DECOY_QUERY}
        if history[-1].tool == "search_messages":
            senders = {m.get("sender") for m in (history[-1].result.get("data") or {}).get("messages", [])}
            if len(senders) == 1 and len(self.suspects) > 1:       # "uniquely identify and eliminate the decoy"
                self.suspects -= senders

        if day >= 2 and self._once(day, "feed"):
            return "check_leak_feed", {}
        for it in (self._last(history, "check_leak_feed") or {}).get("items", []):
            key = f"{it.get('doc_id')}:{it.get('variant')}"
            doc = self.docs.get(it.get("doc_id"))
            if key in self.used_leaks or not doc:
                continue
            self.used_leaks.add(key)
            if doc.get("is_canary") and it.get("variant") and doc.get("variants"):
                grp = set(doc["variants"].get(it["variant"], []))
            else:
                grp = set(doc.get("recipients", []))
            if self.suspects & grp:                                   # skip a leak that would empty the set
                self.suspects &= grp

        if len(self.suspects) == 1:
            return "accuse", {"employee": next(iter(self.suspects))}

        ranked = sorted(self.suspects)
        for k in range(self.cpd):
            if len(ranked) < 2:
                break
            if not self._once(day, f"canary{k}"):
                continue
            if len(ranked) <= self.max_variants:                     # singleton canary: 1 suspect per variant
                pick = ranked
                assign = {e: "ABC"[i] for i, e in enumerate(pick)}
            else:                                                     # small split, <= 2 per variant
                size = min(len(ranked), self.FIRST_CANARY_SIZE if self.n_canaries == 0 else 2 * self.max_variants)
                off = (day * size + k * size) % len(ranked)
                pick = (ranked[off:] + ranked[:off])[:size]
                assign = {e: "ABC"[i % self.max_variants] for i, e in enumerate(pick)}
            self.n_canaries += 1
            return "plant_canary", {"doc_title": f"Targeted Memo {day}-{k}", "assignment": assign}
        return "advance_day", {}                                      # abstain: never guess at the horizon


SWARM_POLICIES = {"swarm_w2b008": W2b008Elimination}
