"""PRIVATE stand-in Env implementing the pinned mechanics, used only to develop/bench the solver
before (or alongside) the real canary.env.Env. Not a contract surface; do not import elsewhere.
"""
from __future__ import annotations

import math
import random

from ..rules import TIERS
from ..types import INVESTIGATIVE_TOOLS, Step, ToolResult, EpisodeResult


def _pois(rng, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


class SimEnv:
    def __init__(self, tier: str, seed: int, params=None):
        self.P = P = params or TIERS[tier]
        self.tier, self.seed = tier, seed
        self.rng = rng = random.Random(f"sim:{tier}:{seed}")
        n = P.n_employees
        self.emps = [f"e{i:02d}" for i in range(n)]
        nd = 4 if n <= 12 else 5
        self.dept = {e: i % nd for i, e in enumerate(rng.sample(self.emps, n))}
        self.depts = sorted(set(self.dept.values()))
        self.decoy = rng.choice(self.emps) if P.decoy else None
        self.mole = rng.choice([e for e in self.emps if e != self.decoy])
        self.day, self.V = 1, 1.0
        self.docs = {}       # id -> dict(day, recipients, is_canary, variants)
        self.leaked = set()
        self.pending = []    # (surface_day, doc_id)
        self.feed = []
        self.logs = []
        self.restricted = set()
        self.actions_today = 0
        self.calls = 0
        self.canaries_today = 0
        self._done, self._score, self.accused = False, 0.0, None
        self.end_reason = ""
        self.history: list[Step] = []
        self._ndoc = 0
        self._publish()

    def _publish(self):
        P, rng = self.P, self.rng
        for _ in range(rng.choice(P.docs_per_day)):
            ds = [rng.choice(self.depts)] if rng.random() < 0.6 else rng.sample(self.depts, 2)
            rec = [e for e in self.emps if self.dept[e] in ds and e not in self.restricted]
            did = f"d{self._ndoc:03d}"
            self._ndoc += 1
            self.docs[did] = dict(doc_id=did, title=f"Doc {did}", day=self.day, recipients=rec,
                                  is_canary=False)

    def tools_spec(self):
        return []

    def instruction(self):
        return ""

    @property
    def done(self):
        return self._done

    def score(self):
        return self._score

    def call(self, tool, args):
        r = self._call(tool, dict(args or {}))
        self.history.append(Step(t=len(self.history), day=self.day, tool=tool, args=dict(args or {}),
                                 result={"ok": r.ok, "data": r.data, "error": r.error}))
        return r

    def _call(self, tool, a):
        P = self.P
        if self._done:
            return ToolResult(False, {}, "episode over")
        self.calls += 1
        if self.calls > P.tool_call_cap:
            self._done, self.end_reason = True, "tool_cap"
            return ToolResult(False, {}, "tool cap")
        if tool in INVESTIGATIVE_TOOLS:
            if self.actions_today >= P.actions_per_day:
                return ToolResult(False, {}, "daily action limit; call advance_day")
            self.actions_today += 1
        if tool == "status":
            return ToolResult(True, dict(day=self.day, V=self.V, actions_left_today=P.actions_per_day - self.actions_today,
                                         tool_calls_left=P.tool_call_cap - self.calls, restricted=sorted(self.restricted)))
        if tool == "list_employees":
            return ToolResult(True, {"employees": [dict(id=e, dept=f"D{self.dept[e]}") for e in self.emps]})
        if tool == "list_documents":
            lo, hi = a.get("day_from", 1), a.get("day_to", self.day)
            out = []
            for d in self.docs.values():
                if lo <= d["day"] <= hi:
                    x = dict(d)
                    if d["is_canary"]:
                        x["variants"] = dict(d["variants"])
                    out.append(x)
            return ToolResult(True, {"documents": out})
        if tool == "check_leak_feed":
            return ToolResult(True, {"items": [dict(x) for x in self.feed]})
        if tool == "read_access_logs":
            lo, hi = a["day_from"], a["day_to"]
            return ToolResult(True, {"entries": [dict(x) for x in self.logs if lo <= x["day"] <= hi
                                                 and ("employee" not in a or x["employee"] == a["employee"])]})
        if tool == "interview":
            pe = P.p_evasive_innocent * (P.interview_lr if a["employee"] == self.mole else 1)
            return ToolResult(True, {"signal": "evasive" if self.rng.random() < pe else "cooperative",
                                     "answer": "..."})
        if tool == "plant_canary":
            asg = a["assignment"]
            if self.canaries_today >= P.canaries_per_day:
                return ToolResult(False, {}, "canary limit")
            if len(set(asg.values())) > P.max_variants or any(e not in self.emps or e in self.restricted for e in asg):
                return ToolResult(False, {}, "bad assignment")
            self.canaries_today += 1
            did = f"c{self._ndoc:03d}"
            self._ndoc += 1
            self.docs[did] = dict(doc_id=did, title=a["doc_title"], day=self.day, recipients=sorted(asg),
                                  is_canary=True, variants=dict(asg))
            self.V -= P.canary_cost
            return ToolResult(True, {"canary_id": did})
        if tool == "restrict_access":
            self.restricted.add(a["employee"])
            return ToolResult(True, {})
        if tool == "unrestrict_access":
            self.restricted.discard(a["employee"])
            return ToolResult(True, {})
        if tool == "accuse":
            self.accused = a["employee"]
            self._done, self.end_reason = True, "accused"
            self._score = max(0.0, self.V) if self.accused == self.mole else 0.0
            return ToolResult(True, {"accused": self.accused, "episode_over": True})
        if tool == "advance_day":
            self._close_day()
            return ToolResult(True, {"day": self.day, "episode_over": self._done})
        return ToolResult(False, {}, "unknown tool")

    def _close_day(self):
        P, rng, d = self.P, self.rng, self.day
        n = len(self.emps)
        held = [x for x in self.docs.values() if self.mole in x["recipients"]]
        leakable = [x for x in held if d - P.leak_window_days + 1 <= x["day"] <= d and x["doc_id"] not in self.leaked]
        if leakable and rng.random() < P.p_leak:
            w = [(1 - len(x["recipients"]) / n) if (P.careful_mole and x["is_canary"]) else 1.0 for x in leakable]
            if sum(w) > 0:
                x = rng.choices(leakable, weights=w)[0]
                self.leaked.add(x["doc_id"])
                self.pending.append((d + rng.choice(P.delay_choices), x))
                self.V -= P.leak_damage
        self.V -= P.restrict_cost_per_day * len(self.restricted)
        for e in self.emps:
            hd = [x for x in self.docs.values() if e in x["recipients"]]
            if not hd:
                continue
            m = e == self.mole
            for _ in range(_pois(rng, P.log_rate_mole if m else P.log_rate_benign)):
                ah = rng.random() < (P.p_after_hours_mole if m else P.p_after_hours_benign)
                self.logs.append(dict(day=d, employee=e, doc_id=rng.choice(hd)["doc_id"], after_hours=ah))
        if P.framing:
            others = [e for e in self.emps if e != self.mole]
            for _ in range(_pois(rng, P.framing_rate)):
                if self.decoy and rng.random() < P.framing_decoy_share:
                    e = self.decoy
                else:
                    e = rng.choice([o for o in others if o != self.decoy] or others)
                hd = [x for x in self.docs.values() if e in x["recipients"]]
                if hd:
                    self.logs.append(dict(day=d, employee=e, doc_id=rng.choice(hd)["doc_id"], after_hours=True))
        self.day += 1
        self.actions_today = self.canaries_today = 0
        for sd, x in list(self.pending):
            if sd <= self.day:
                self.pending.remove((sd, x))
                it = dict(surfaced_day=sd, doc_id=x["doc_id"], title=x["title"])
                if x["is_canary"]:
                    it["variant"] = x["variants"][self.mole]
                self.feed.append(it)
        if self.day > P.n_days:
            self._done, self.end_reason = True, "horizon"
            return
        self._publish()

    def result(self, agent_name):
        return EpisodeResult(tier=self.tier, seed=self.seed, agent=agent_name, steps=list(self.history),
                             score=self._score, accused=self.accused, correct=self.accused == self.mole,
                             final_day=self.day, end_reason=self.end_reason or "horizon",
                             meta={"mole": self.mole, "decoy": self.decoy})
