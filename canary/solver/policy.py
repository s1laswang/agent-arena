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


def accuse_value(p: float, V: float, P) -> float:
    """Expected score of accusing someone with posterior p now (v0.3: wrong = wrong_accusation_score)."""
    return p * V + (1 - p) * getattr(P, "wrong_accusation_score", 0.0)


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
                 behaviour_temper: float = 0.6, choice_temper: float = 0.5, noleak_temper: float = 0.5,
                 none_group: bool = True, read_logs: bool = True, design: str = "auto",
                 coverages: tuple = (0.1, 0.15, 0.25, 0.4, 0.55, 0.7, 1.0), alternate: bool = False, adaptive: bool = False, utility: str = "mi",
                 probing: bool = False, probe_cap: int = 4, probe_extra: int = 1, probe_core: int = 4,
                 behaviour_weight: float | None = None, act_budget: float = 0.3):
        self._given = params
        self.threshold = threshold
        # behaviour_weight: public alias (FR8 sweeps it); exponent on access-log/interview likelihoods
        self.behaviour_temper = behaviour_temper if behaviour_weight is None else behaviour_weight
        self.choice_temper = choice_temper
        self.noleak_temper = noleak_temper
        self.none_group = none_group
        self.read_logs = read_logs
        self.design = design
        self.coverages = coverages
        self.alternate = alternate
        self.adaptive = adaptive
        self.utility = utility
        self.act_budget = act_budget  # wall-clock cap (s) for the canary-split search
        self.probing, self.probe_cap, self.probe_extra, self.probe_core = probing, probe_cap, probe_extra, probe_core
        self.reset([], "")

    # ---------------------------------------------------------------- Policy API
    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        p = self._given
        if isinstance(p, str):
            p = TIERS[p]
        if p is None:
            from .params import params_from_instruction
            p = params_from_instruction(instruction)
        self.P: TierParams | None = p
        self.obs = Observations()
        self.queue: list[tuple[str, dict]] = []
        self.seen = 0
        self.V_pre: float | None = 1.0
        self.V = 1.0
        self.restricted: set[str] = set()
        self.phase = "start"
        self.pending_canary: dict | None = None
        self.probe = None
        self.post: dict[str, float] = {}
        self.trace: list[dict] = []   # per-day belief snapshots (for regret/debug)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        import time as _t
        t0 = _t.perf_counter()
        try:
            return self._act(history)
        finally:
            dt = _t.perf_counter() - t0
            self.max_act_time = max(getattr(self, "max_act_time", 0.0), dt)
            if dt > 1.0:
                import logging
                logging.getLogger("canary.solver").warning("slow act(): %.2fs at step %d", dt, len(history))

    def _act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < self.seen:   # runner restarted/trimmed history: re-ingest from scratch
            P = self.P
            self.reset([], "")
            self.P = P
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
            V = float(data.get("V", data.get("value", self.V)))
            self.restricted = set(data.get("restricted", []) or [])
            if self.phase == "post_advance" and self.V_pre is not None and (day - 1) not in o.closed_days:
                self._close(day - 1, V)
            if self.phase == "post_advance":
                self.phase = "day"
            o.today = day
            self.V_pre = self.V = V
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
            if self.V_pre is not None:
                self.V_pre -= self.P.canary_cost
                self.V = self.V_pre
            if cid:
                o.docs[cid] = Doc(cid, o.today, frozenset(asg), True, dict(asg))
        elif st.tool == "advance_day":
            self.phase = "post_advance"
            if "V" in data and "closed_day" in data and self.V_pre is not None:
                self._close(int(data["closed_day"]), float(data["V"]))
                self.V_pre = self.V = float(data["V"])
                if "day" in data:
                    o.today = int(data["day"])
        elif st.tool == "restrict_access":
            self.restricted.add(st.args.get("employee"))
        elif st.tool == "unrestrict_access":
            self.restricted.discard(st.args.get("employee"))
        elif st.tool == "interview":
            sig = str(data.get("signal", data.get("answer", ""))).lower()
            o.interviews.append((st.args["employee"], "evasive" in sig))

    def _close(self, d: int, V_after: float):
        drop = self.V_pre - V_after - self.P.restrict_cost_per_day * len(self.restricted)
        self.obs.closed_days.add(d)
        if round(drop / self.P.leak_damage) >= 1:
            self.obs.leak_days.add(d)
        else:
            self.obs.leak_days.discard(d)

    # ---------------------------------------------------------------- planning
    def belief(self) -> dict[str, float]:
        return posterior(self.obs, self.P, self.behaviour_temper, self.choice_temper, self.noleak_temper)

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
            ev = accuse_value(post[best], self.V, self.P)
            if ev > 0 and (post[best] >= thr or last):
                self.queue = [("accuse", {"employee": best})]
                return
            q = self.probe_actions(post)
            asg = self.partition(post)
            if asg:
                q.append(("plant_canary", {"doc_title": f"Board memo draft {o.today}", "assignment": asg}))
            q += [("status", {}), ("advance_day", {})]
            self.queue = q
            self.phase = "advancing"
            return
        # fallback
        self.queue = [("advance_day", {})]

    def probe_actions(self, post: dict[str, float]) -> list[tuple[str, dict]]:
        """Restriction probing (strategy-independent): a restricted mole gets no new docs, so once the
        leak window passes it has nothing to leak; continued V drops then exclude the restricted group.
        The belief models this exactly (leakable set of a restricted suspect empties)."""
        if not self.probing:
            return []
        o, P = self.obs, self.P
        q = []
        if self.probe is not None:
            grp, start = self.probe
            if o.today >= start + P.leak_window_days + self.probe_extra:
                q += [("unrestrict_access", {"employee": e}) for e in sorted(grp) if e in self.restricted]
                self.probe = None
            return q
        if o.today < 3 or o.today > P.n_days - P.leak_window_days - 1:
            return q
        alive = sorted((e for e in post if post[e] > 1e-3), key=lambda e: -post[e])
        cum, core = 0.0, 0
        for e in alive:
            cum += post[e]
            core += 1
            if cum >= 0.95:
                break
        if not (self.canary_shy() or core <= self.probe_core):
            return q
        if len(alive) <= 1:
            return q
        grp, m = [], 0.0
        for e in alive:
            if m >= 0.5 or len(grp) >= self.probe_cap:
                break
            grp.append(e)
            m += post[e]
        if m > 0.9:
            grp = grp[:-1] or grp
        self.probe = (frozenset(grp), o.today)
        return [("restrict_access", {"employee": e}) for e in grp]

    def canary_shy(self) -> bool:
        """Strategy-agnostic switch: >= 3 regular leaks surfaced while our canaries were leakable,
        and no canary ever leaked => this mole avoids small/new canaries (e.g. DSL most_recipients)."""
        o = self.obs
        canary_days = sorted(d.day for d in o.docs.values() if d.is_canary)
        if not canary_days or any(o.docs.get(it.doc_id) and o.docs[it.doc_id].is_canary for it in o.feed):
            return False
        reg = [it for it in o.feed if it.doc_id in o.docs and not o.docs[it.doc_id].is_canary
               and it.surfaced_day - max(self.P.delay_choices) > canary_days[0]]
        return len(reg) >= 3

    def pad(self, asg: dict[str, str], post: dict[str, float]) -> dict[str, str]:
        """Give the canary to everyone (max recipients); non-suspects join the lightest-mass label."""
        if not asg:
            return asg
        mass = {}
        for e, l in asg.items():
            mass[l] = mass.get(l, 0.0) + post[e]
        light = min(mass, key=mass.get)
        out = dict(asg)
        for e in self.obs.employees:
            if e not in out and e not in self.restricted:
                out[e] = light
        return out

    def partition(self, post: dict[str, float]) -> dict[str, str]:
        if self.adaptive and self.canary_shy() and self.obs.today % 2 == 0:
            return self.pad(self.partition_balanced(post), post)
        if self.design == "balanced" or (self.design == "auto" and not self.P.careful_mole):
            return self.partition_balanced(post)
        return self.partition_search(post)

    def partition_search(self, post: dict[str, float], n_shuffles: int = 16) -> dict[str, str]:
        """Pick the canary assignment maximising P(canary leaks) x (Gini gain over the cells of the
        still-pending canaries). Orthogonal to pending canaries (pipelining under delay) and
        careful-mole aware (smaller groups are leaked more often)."""
        import random as _r
        P, o = self.P, self.obs
        k = P.max_variants
        n = len(o.employees) or 1
        alive = [e for e in post if post[e] > 1e-4 and e not in self.restricted]
        if len(alive) <= 1:
            return {}
        surfaced = {it.doc_id for it in o.feed}
        pend = [d for d in o.docs.values() if d.is_canary and d.variants and d.doc_id not in surfaced
                and d.day >= o.today - P.leak_window_days + 1]
        def cell_old(e):
            return tuple(d.variants.get(e, "-") for d in pend)
        def gini(keyf):
            m = {}
            for e in post:
                m[keyf(e)] = m.get(keyf(e), 0.0) + post[e]
            return 1.0 - sum(v * v for v in m.values())
        g_old = gini(cell_old)
        # expected regular leakable docs for the mole (competition for the leak choice)
        win = [d for d in o.docs.values() if not d.is_canary and d.day >= o.today - P.leak_window_days]
        nreg = sum(post[e] * sum(1 for d in win if e in d.recipients) for e in post) * P.leak_window_days / max(1, len({d.day for d in win}) or 1)
        nreg = max(1.0, nreg)
        nreg_s = {e: sum(1 for d in win if e in d.recipients) for e in post}
        rng = _r.Random(f"canary:{o.today}:{len(o.feed)}")
        best, bestu = {}, -1.0
        fracs = self.coverages
        if self.alternate and o.today % 2 == 0:
            fracs = (1.0,)   # robustness: big canaries for moles that prefer widely-shared docs (DSL)
        import time as _t
        deadline = _t.perf_counter() + self.act_budget
        for f in fracs:
            if _t.perf_counter() > deadline and best:
                break
            for t in range(n_shuffles):
                order = sorted(alive, key=lambda e: -post[e]) if t == 0 else rng.sample(alive, len(alive))
                rec, m = [], 0.0
                for e in order:
                    if m >= f - 1e-9 and rec:
                        break
                    rec.append(e)
                    m += post[e]
                ng = min(k, len(rec))
                mass, groups = [0.0] * ng, [[] for _ in range(ng)]
                for e in rec:
                    g = min(range(ng), key=lambda i: (mass[i], len(groups[i])))
                    groups[g].append(e)
                    mass[g] += post[e]
                asg = {e: LABELS[i] for i, g in enumerate(groups) for e in g}
                u = self.canary_mi(post, asg, nreg_s, n) if self.utility == "mi" else None
                if u is None:
                    w = (1.0 - len(asg) / n) if P.careful_mole else 1.0
                    if w <= 0:
                        continue
                    pl = w / (w + nreg)
                    u = pl * (gini(lambda e: (cell_old(e), asg.get(e, "-"))) - g_old)
                if u > bestu:
                    best, bestu = asg, u
        return best

    def canary_mi(self, post, asg, nreg_s, n) -> float:
        """Mutual information (nats) between the mole's identity and this canary's outcome
        (which label leaks within the leak window, or none), under the careful-mole weight."""
        P = self.P
        w = max(0.0, 1.0 - len(asg) / n) if P.careful_mole else 1.0
        win = P.leak_window_days
        po = {}
        hcond = 0.0
        for e, p in post.items():
            if p <= 0:
                continue
            lab = asg.get(e)
            if lab is None or w <= 0:
                q = 0.0
            else:
                per_day = P.p_leak * w / (w + max(1.0, nreg_s.get(e, 0)))
                q = 1 - (1 - per_day) ** win
            po["_none"] = po.get("_none", 0.0) + p * (1 - q)
            if q > 0:
                po[lab] = po.get(lab, 0.0) + p * q
                hcond -= p * (q * math.log(q) + ((1 - q) * math.log(1 - q) if q < 1 else 0.0))
        h = -sum(v * math.log(v) for v in po.values() if v > 0)
        return h - hcond

    def partition_balanced(self, post: dict[str, float]) -> dict[str, str]:
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
