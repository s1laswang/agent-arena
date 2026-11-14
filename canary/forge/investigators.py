"""Cheap investigator population for the Forge (proxy for a competent LLM).

HintedHeuristic: evidence-only bisection. Intersects suspects with every leaked doc's recipients
(canary variant groups when the leak is a canary), splits the remaining suspects with one canary per
day, ignores logs/decoy/interviews entirely. Bayesian over employees so noisy canary labels
(v1.2: the shown label is right with prob q) don't eliminate the mole: a canary leak with label L
multiplies L's members by q and the other variants' members by (1-q)/(k-1); non-recipients of any leaked
doc get 0. It accuses when max posterior p >= accuse_p, or on the last day if p*V - (1-p) > 0.
"""
from __future__ import annotations

import random
import re

from canary.baselines import _employees


class HintedHeuristic:
    name = "hinted_heuristic"

    def __init__(self, seed: int = 0, n_days: int = 14, accuse_p: float = 0.85,
                 max_share: float = 0.4):
        self.seed, self.n_days, self.accuse_p, self.max_share = seed, n_days, accuse_p, max_share

    def reset(self, tools_spec, instruction):
        self.rng = random.Random(f"hinted:{self.seed}")
        m = re.search(r"at most (\d+) days", instruction or "")
        self.n_days = int(m.group(1)) if m else self.n_days
        m = re.search(r"at most (\d+) (?:distinct variant|different label)", instruction or "")
        self.k = max(2, min(4, int(m.group(1)))) if m else 2
        m = re.search(r"variant label the mole received with probability ([0-9]*\.?[0-9]+)", instruction or "")
        self.q = float(m.group(1)) if m else 1.0
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
        post = {e: 1.0 for e in emps}
        for it in (self._last(history, "check_leak_feed") or {}).get("items", []):
            doc = self.docs.get(it.get("doc_id"))
            if not doc:
                continue
            if it.get("variant") and doc.get("variants"):
                groups = {lab: set(m) for lab, m in doc["variants"].items()}
                k = max(2, len(groups))
                for e in post:
                    if e in groups.get(it["variant"], ()):
                        post[e] *= self.q
                    elif any(e in g for g in groups.values()):
                        post[e] *= (1 - self.q) / (k - 1)
                    else:
                        post[e] = 0.0
            else:
                rec = set(doc.get("recipients", []))
                if any(post[e] > 0 for e in rec if e in post):
                    for e in post:
                        if e not in rec:
                            post[e] = 0.0
        z = sum(post.values()) or 1.0
        post = {e: v / z for e, v in post.items()}
        best = max(sorted(post), key=lambda e: post[e])
        pb, V = post[best], float(self.V or 0)
        if pb >= self.accuse_p and pb * V - (1 - pb) > 0:
            return "accuse", {"employee": best}
        if day >= self.n_days:
            if pb * V - (1 - pb) > 0:
                return "accuse", {"employee": best}
            return "advance_day", {}
        ranked = sorted((e for e in post if post[e] > 1e-3), key=lambda e: (-post[e], e))
        if once("canary"):
            if len(ranked) < 2:
                return "advance_day", {}
            # split posterior mass evenly: greedy assignment of suspects (high mass first) to the lightest group
            labels = "ABCD"[: self.k]
            mass = {lab: 0.0 for lab in labels}
            assign = {}
            # careful mole: canary weight x (1 - recipient share) -> cap recipients at max_share of staff
            for e in ranked[: max(2, int(self.max_share * len(emps)))]:
                lab = min(labels, key=lambda l: (mass[l], l))
                assign[e] = lab
                mass[lab] += post[e]
            return "plant_canary", {"doc_title": f"Board update {day}", "assignment": assign}
        return "advance_day", {}
