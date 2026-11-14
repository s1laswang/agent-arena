"""SolverPolicy: the reference investigator. Talks to the world ONLY via tool calls (history of Steps).

Daily loop:
  status -> list_documents -> check_leak_feed -> read_access_logs(yesterday)
  -> belief update -> accuse if P(max) >= threshold (or last day)
  -> plant_canary (posterior-balanced variant groups) -> advance_day -> status (V drop => leak)
"""
from __future__ import annotations

import math
from typing import Any

from ..rules import TIERS, TierParams
from ..types import Step
from .belief import Doc, FeedItem, Observations, posterior

LABELS = "ABCDEFGH"


def _items(data: dict, *keys):
    if isinstance(data, list):
        return data
    for k in keys:
        if k in data and isinstance(data[k], list):
            return data[k]
    for v in data.values():
        if isinstance(v, list):
            return v
    return []


def tier_from_instruction(instruction: str) -> str | None:
    low = (instruction or "").lower()
    for t in ("hard", "medium", "easy"):
        if f"tier: {t}" in low or f"tier={t}" in low or f"\"{t}\" tier" in low:
            return t
    return None


class SolverPolicy:
    name = "solver"

    def __init__(self, params: TierParams | str | None = None, threshold: float | None = None,
                 behaviour_temper: float = 0.3, choice_temper: float = 1.0,
                 none_group: bool = True, read_logs: bool = True):
        self._given = params
        self.threshold = threshold
        self.behaviour_temper = behaviour_temper
        self.choice_temper = choice_temper
        self.none_group = none_group
        self.read_logs = read_logs
        self.reset([], "")

    # ---------------------------------------------------------------- Policy API
    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        p = self._given
        if isinstance(p, str):
            p = TIERS[p]
        if p is None:
            t = tier_from_instruction(instruction)
            p = TIERS[t] if t else None
        self.P: TierParams | None = p
        self.obs = Observations()
        self.queue: list[tuple[str, dict]] = []
        self.seen = 0
        self.V_pre: float | None = None
        self.restricted: set[str] = set()
        self.phase = "start"
        self.pending_canary: dict | None = None
        self.post: dict[str, float] = {}
        self.trace: list[dict] = []   # per-day belief snapshots (for regret/debug)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        for st in history[self.seen:]:
            self._ingest(st)
        self.seen = len(history)
        if not self.queue:
            self._plan()
        return self.queue.pop(0)

    # ---------------------------------------------------------------- ingestion
    def _ingest(self, st: Step):
        r = st.result or {}
        data = r.get("data") or {}
        ok = r.get("ok", True)
        o = self.obs
        if not ok:
            return
        if st.tool == "list_employees":
            emps = _items(data, "employees")
            o.employees = [e["id"] if isinstance(e, dict) else e for e in emps]
            if self.P is None:
                n = len(o.employees)
                self.P = min(TIERS.values(), key=lambda t: abs(t.n_employees - n))
        elif st.tool == "status":
            day = int(data.get("day", o.today))
            V = float(data.get("V", data.get("value", 1.0)))
            self.restricted = set(data.get("restricted", []) or [])
            if self.phase == "post_advance" and self.V_pre is not None:
                closed = day - 1
                drop = self.V_pre - V - self.P.restrict_cost_per_day * len(self.restricted)
                k = round(drop / self.P.leak_damage)
                o.closed_days.add(closed)
                if k >= 1:
                    o.leak_days.add(closed)
                self.phase = "day"
            o.today = day
            self.V_pre = V
            self.V = V
        elif st.tool == "list_documents":
            for d in _items(data, "documents", "docs"):
                var = d.get("variants")
                if isinstance(var, dict) and var and all(isinstance(v, list) for v in var.values()):
                    var = {e: lab for lab, es in var.items() for e in es}  # {label: [emps]} -> {emp: label}
                if self.pending_canary and d.get("is_canary") and not var:
                    pass
                o.docs[d["doc_id"]] = Doc(d["doc_id"], int(d["day"]), frozenset(d.get("recipients", [])),
                                          bool(d.get("is_canary")), dict(var) if isinstance(var, dict) else
                                          o.docs.get(d["doc_id"], Doc("", 0, frozenset())).variants)
        elif st.tool == "check_leak_feed":
            o.feed = [FeedItem(int(x["surfaced_day"]), x["doc_id"], x.get("variant"))
                      for x in _items(data, "items", "feed", "leaks")]
        elif st.tool == "read_access_logs":
            days = set(range(int(st.args["day_from"]), int(st.args["day_to"]) + 1))
            for e in o.employees:
                o.access_counts.setdefault(e, [0, 0])
                o.access_days[e] = o.access_days.get(e, 0) + len(days)
            for x in _items(data, "entries", "logs", "accesses"):
                c = o.access_counts.setdefault(x["employee"], [0, 0])
                c[1 if x.get("after_hours") else 0] += 1
        elif st.tool == "plant_canary":
            cid = data.get("canary_id") or data.get("doc_id")
            asg = st.args["assignment"]
            if cid:
                o.docs[cid] = Doc(cid, o.today, frozenset(asg), True, dict(asg))
        elif st.tool == "advance_day":
            self.phase = "post_advance"
        elif st.tool == "interview":
            sig = str(data.get("signal", data.get("answer", ""))).lower()
            o.interviews.append((st.args["employee"], "evasive" in sig))

    # ---------------------------------------------------------------- planning
    def belief(self) -> dict[str, float]:
        return posterior(self.obs, self.P, self.behaviour_temper, self.choice_temper)

    def default_threshold(self) -> float:
        return {"easy": 0.9, "medium": 0.9, "hard": 0.85}.get(self.P.name, 0.9)

    def _plan(self):
        o = self.obs
        if self.phase == "start":
            self.phase = "day"
            self.queue = [("list_employees", {}), ("status", {})]
            return
        if self.phase == "post_advance":
            self.queue = [("status", {})]
            return
        if self.phase == "day":
            q = [("list_documents", {"day_from": max(1, o.today - 3), "day_to": o.today}),
                 ("check_leak_feed", {})]
            if self.read_logs and self.behaviour_temper > 0 and o.today > 1:
                q.append(("read_access_logs", {"day_from": o.today - 1, "day_to": o.today - 1}))
            self.queue = q
            self.phase = "decide"
            return
        if self.phase == "decide":
            post = self.belief()
            self.post = post
            best = max(post, key=post.get)
            thr = self.threshold if self.threshold is not None else self.default_threshold()
            last = o.today >= self.P.n_days
            self.trace.append({"day": o.today, "post": dict(post)})
            if post[best] >= thr or last:
                self.queue = [("accuse", {"employee": best})]
                return
            q = []
            asg = self.partition(post)
            if asg:
                q.append(("plant_canary", {"doc_title": f"Board memo draft {o.today}", "assignment": asg}))
            q += [("status", {}), ("advance_day", {})]
            self.queue = q
            self.phase = "advancing"
            return
        # fallback
        self.queue = [("advance_day", {})]

    def partition(self, post: dict[str, float]) -> dict[str, str]:
        """Split alive suspects into <= max_variants labelled groups (+ an implicit 'no canary' group)
        with balanced posterior mass."""
        k = self.P.max_variants
        alive = sorted((e for e in post if post[e] > 1e-4 and e not in self.restricted),
                       key=lambda e: -post[e])
        if len(alive) <= 1:
            return {}
        ngroups = k + 1 if (self.none_group and len(alive) > k) else k
        mass = [0.0] * ngroups
        groups: list[list[str]] = [[] for _ in range(ngroups)]
        for e in alive:
            g = min(range(ngroups), key=lambda i: (mass[i], len(groups[i])))
            groups[g].append(e)
            mass[g] += post[e]
        if ngroups > k:  # drop the heaviest-count group as the "no canary" group (fewest recipients => careful mole)
            drop = max(range(ngroups), key=lambda i: len(groups[i]))
            groups.pop(drop)
        return {e: LABELS[i] for i, g in enumerate(groups) for e in g}
