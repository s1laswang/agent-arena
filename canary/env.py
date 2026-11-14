"""Env: the one public entrypoint for every investigator (solver, baselines, LLM agents, MCP).

Owner: HEAD-ENV (engineer: sim-engine). See docs/CONTRACT.md sections 2-3 for the mechanics.
Integrity: the mole id lives only in self._world; no tool result may contain it.
"""
from __future__ import annotations

import threading

import math
import random
from dataclasses import asdict
from typing import Any

from .rules import TIERS
from .text.facts import EmployeeFacts, PublicDayFacts
from .types import INVESTIGATIVE_TOOLS, EpisodeResult, LedgerEntry, Step, ToolResult
from .mole.dsl import DEFAULT_STRATEGY, MoleDoc, MoleView, MoleStrategy
from .world import generate_world

TOPICS = ("recent_documents", "contacts_outside", "workload", "access_needs")
BAD = "invalid arguments"
# Contract v0.2: every error string is one of these fixed constants (never depends on the target).
ERRORS = frozenset({BAD, "unknown tool", "daily action limit; call advance_day", "canary limit for today reached", "episode over"})

_EMP = {"type": "string", "description": "one employee id, e.g. e07"}
_DAY = {"type": "integer", "minimum": 1}
_SPECS: dict[str, tuple[str, dict, list]] = {
    "status": ("Current day, company value V, actions left today, tool calls left, restricted employees, canaries planted.", {}, []),
    "list_employees": ("List all employees: id, name, dept, role (and clearance in hard tier).", {}, []),
    "list_documents": ("List published documents (incl. canaries) in an inclusive day range.", {"day_from": _DAY, "day_to": _DAY}, []),
    "read_access_logs": ("Sensitive-doc access logs for closed days in an inclusive range, optionally one employee.", {"day_from": _DAY, "day_to": _DAY, "employee": _EMP}, ["day_from", "day_to"]),
    "search_messages": ("Case-insensitive substring search over message subject+body (max 20 results).", {"query": {"type": "string"}, "day_from": _DAY, "day_to": _DAY}, ["query"]),
    "read_message": ("Read one full message by id.", {"id": {"type": "string"}}, ["id"]),
    "interview": ("Interview one employee on a topic.", {"employee": _EMP, "topic": {"type": "string", "enum": list(TOPICS)}}, ["employee", "topic"]),
    "plant_canary": ("Plant a canary doc today; assignment maps employee id -> variant label.", {"doc_title": {"type": "string", "minLength": 1, "maxLength": 120}, "assignment": {"type": "object", "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 20}}}, ["doc_title", "assignment"]),
    "check_leak_feed": ("Leaked documents that have surfaced so far (variant shown for canaries).", {}, []),
    "restrict_access": ("Restrict one employee (no new docs, no canaries; daily cost).", {"employee": _EMP}, ["employee"]),
    "unrestrict_access": ("Lift a restriction.", {"employee": _EMP}, ["employee"]),
    "advance_day": ("Close the current day and move to the next.", {}, []),
    "accuse": ("Accuse one employee of being the mole. Ends the episode; correctness is not revealed.", {"employee": _EMP}, ["employee"]),
}


def _poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _default_provider():
    from .text.template import TemplateProvider
    return TemplateProvider()


class Env:
    def __init__(self, tier: str, seed: int, text_provider=None, mole_strategy=None):
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier}")
        self.tier, self.seed, self.p = tier, seed, TIERS[tier]
        self._world = generate_world(tier, seed, self.p)
        if mole_strategy is not None:
            if isinstance(mole_strategy, dict):
                mole_strategy = MoleStrategy.from_json(mole_strategy)
            self._world.mole_strategy = mole_strategy
        self._dyn = random.Random(self._world.world_seed ^ 1)
        self.provider = text_provider if text_provider is not None else _default_provider()
        self._ids = self._world.ids
        self._idset = set(self._ids)
        self.day = 1
        self.V = 1.0
        self._done = False
        self._end_reason: str | None = None
        self._accused: str | None = None
        self._correct = False
        self._lock = threading.RLock()
        self._actions_today = 0
        self._canaries_today = 0
        self._restricted: set[str] = set()
        self.docs: list[dict] = []           # public doc records, in publish order
        self._doc_by_id: dict[str, dict] = {}
        self._held: dict[str, list[str]] = {e: [] for e in self._ids}
        self._leaked: set[str] = set()
        self._feed: list[dict] = []          # includes not-yet-surfaced items
        self._logs: list[dict] = []
        self._messages: dict[str, dict] = {}
        self._msg_order: list[str] = []
        self._history: list[Step] = []
        self._ledger: list[LedgerEntry] = []
        self._canary_ids: list[str] = []
        self._last_leak_day = 0
        self._publish_day(1)

    # ------------------------------------------------------------------ public API
    def tools_spec(self) -> list[dict]:
        return [{"name": n, "description": d,
                 "input_schema": {"type": "object", "properties": props, "required": req, "additionalProperties": False}}
                for n, (d, props, req) in _SPECS.items()]

    def instruction(self) -> str:
        p = self.p
        return "\n".join([
            f"You are the security lead of a company with {p.n_employees} employees (ids e00..e{p.n_employees-1:02d}). Exactly one is a mole leaking sensitive documents. Find and accuse them.",
            f"Tier: {p.name}. The episode lasts at most {p.n_days} days, starting on day 1. Company value V starts at 1.0 and never goes below 0.",
            f"Scoring: accuse(employee) ends the episode; score = V at that moment if correct; if you accuse an innocent employee the score is {p.wrong_accusation_score:g} (you fired an innocent and the mole keeps leaking). Correctness is not revealed. Not accusing at all scores 0, so only accuse when P(correct)*V - (1-P(correct)) > 0. If day {p.n_days} closes without an accusation, score = 0.",
            f"Documents: each day {min(p.docs_per_day)}-{max(p.docs_per_day)} (uniform over {list(p.docs_per_day)}) regular docs are published; recipients are one whole department (60%) or the union of two departments (40%). Restricted employees receive no new docs.",
            f"Leaks: when a day closes, if the mole holds at least one leakable doc (received in the last {p.leak_window_days} days incl. today, not yet leaked) it leaks one with probability {p.p_leak}, chosen uniformly among leakable docs." + (" Careful mole: a canary's weight is multiplied by (1 - share of all employees who received any variant of it)." if p.careful_mole else ""),
            f"Each leak costs V -{p.leak_damage} immediately and surfaces in the leak feed after a delay uniform over {list(p.delay_choices)} days. Leaked canaries show the variant label the mole received. A restricted mole can still leak docs it already holds.",
            f"Canaries: plant_canary costs V -{p.canary_cost}, at most {p.canaries_per_day} per day, at most {p.max_variants} distinct variant labels, at least 1 recipient, no restricted recipients. Recipients are exactly the assignment keys; it counts as received today." + (f" Recipients must have clearance >= the canary level (canaries are level {p.canary_level}; every employee has clearance >= 1)." if p.access_constraints else ""),
            f"Restriction: each restricted employee costs V -{p.restrict_cost_per_day} per closed day.",
            f"Access logs (closed days only): every employee makes Poisson(rate) accesses per day to random docs it holds; innocent rate {p.log_rate_benign}, mole rate {p.log_rate_mole}. Each access is after_hours with prob {p.p_after_hours_benign} (innocent) or {p.p_after_hours_mole} (mole).",
            (f"Framing: the mole adds Poisson({p.framing_rate}) fake after-hours accesses per day attributed to another employee: the decoy with prob {p.framing_decoy_share}, otherwise uniform over the other non-mole employees." if p.framing else "No framing in this tier."),
            ("A decoy exists: one innocent, disgruntled employee writes angry messages. The mole is uniform among the other employees." if p.decoy else "No decoy in this tier; the mole is uniform among all employees."),
            f"Interviews: answer is evasive with probability {p.p_evasive_innocent} for innocents and {p.p_evasive_innocent} x {p.interview_lr} for the mole; repeating the same (employee, topic) on the same day gives the same answer.",
            f"Caps: investigative tools ({', '.join(sorted(INVESTIGATIVE_TOOLS))}) are limited to {p.actions_per_day} per day; status, list_*, advance_day and accuse are free. Every call counts toward a global cap of {p.tool_call_cap}; reaching it ends the episode with score 0.",
            f"Mole behaviour: the mole follows a rule strategy (Mole DSL). It may condition only on: day, days_since_last_leak, i_am_restricted, n_restricted_colleagues, recent_low_recipient_docs (leakable docs with <= {p.low_recipient_threshold} recipients), n_leakable (= n_docs_held), min_recipient_count, max_recipient_count, newest_doc_age_days (all over its leakable docs); it chooses which leakable doc to leak (newest, oldest, most_recipients, fewest_recipients, random_seeded, none) and may frame one colleague (decoy, most_restricted_peer, random_peer, none) by adding one fake after-hours access. It never knows which docs are canaries. p_leak still gates every leak. The default strategy is random_seeded with no extra framing (the rules above).",
            "Arguments are validated strictly: one employee id per call, no lists, wildcards or names.",
        ])

    @property
    def done(self) -> bool:
        return self._done

    def score(self) -> float:
        if self._done and self._accused is not None:
            return round(self.V, 10) if self._correct else float(self.p.wrong_accusation_score)
        return 0.0

    def ledger(self) -> list[LedgerEntry]:
        return list(self._ledger)

    @property
    def history(self) -> list[Step]:
        return self._history

    def result(self, agent_name: str) -> EpisodeResult:
        return EpisodeResult(tier=self.tier, seed=self.seed, agent=agent_name, steps=list(self._history),
                             score=self.score(), accused=self._accused, correct=self._correct,
                             final_day=self.day, end_reason=self._end_reason or "error",
                             meta={"provider": getattr(self.provider, "name", "?"), "V": self.V})

    def call(self, tool: str, args: dict) -> ToolResult:
        with self._lock:
            return self._call(tool, args)

    def _call(self, tool: str, args: dict) -> ToolResult:
        t = len(self._history)
        day = self.day
        if self._done:
            res = ToolResult(False, {}, "episode over")
        else:
            res = self._dispatch(tool, args)
        self._history.append(Step(t=t, day=day, tool=tool if isinstance(tool, str) else repr(tool),
                                  args=args if isinstance(args, dict) else {"_raw": repr(args)}, result=asdict(res)))
        if not self._done and len(self._history) >= self.p.tool_call_cap:
            self._end("tool_cap")
        return res

    # ------------------------------------------------------------------ internals
    def _log(self, event: str, **detail):
        self._ledger.append(LedgerEntry(t=len(self._history), day=self.day, event=event, detail=detail))

    def _end(self, reason: str):
        self._done = True
        self._end_reason = reason
        self._log("episode_end", reason=reason, score=self.score(), V=self.V)

    def _charge(self, x: float):
        self.V = max(0.0, self.V - x)

    def _publish_day(self, d: int):
        for raw in self._world.planned_docs.get(d, []):
            doc = {"doc_id": raw["doc_id"], "title": raw["title"], "day": d,
                   "recipients": [r for r in raw["recipients"] if r not in self._restricted], "is_canary": False}
            self._add_doc(doc)

    def _add_doc(self, doc: dict):
        self.docs.append(doc)
        self._doc_by_id[doc["doc_id"]] = doc
        for r in doc["recipients"]:
            self._held[r].append(doc["doc_id"])

    def _facts(self, d: int) -> PublicDayFacts:
        w = self._world
        return PublicDayFacts(
            tier=self.tier, seed=w.world_seed, day=d, company=w.company,
            employees=tuple(EmployeeFacts(e.id, e.name, e.dept, e.role, e.clearance) for e in w.employees),
            docs=tuple({"doc_id": x["doc_id"], "title": x["title"], "day": x["day"], "recipients": list(x["recipients"])}
                       for x in self.docs if x["day"] == d),
            decoy=w.decoy, decoy_mood="angry" if w.decoy else "neutral", restricted=tuple(sorted(self._restricted)))

    def _emp(self, args: dict, key: str = "employee") -> str | None:
        v = args.get(key)
        return v if isinstance(v, str) and v in self._idset else None

    def _check_args(self, tool: str, args: Any) -> bool:
        if not isinstance(args, dict):
            return False
        _, props, req = _SPECS[tool]
        if any(k not in props for k in args) or any(k not in args for k in req):
            return False
        for k, v in args.items():
            typ = props[k].get("type")
            if typ == "integer" and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= self.p.n_days):
                return False
            if typ == "string" and not isinstance(v, str):
                return False
            if typ == "object" and not isinstance(v, dict):
                return False
        if "day_from" in args and "day_to" in args and args["day_from"] > args["day_to"]:
            return False
        if "employee" in args and args["employee"] not in self._idset:
            return False
        return True

    def _dispatch(self, tool: str, args: Any) -> ToolResult:
        if not isinstance(tool, str) or tool not in _SPECS:
            return ToolResult(False, {}, "unknown tool")
        if not self._check_args(tool, args):
            return ToolResult(False, {}, BAD)
        if tool in INVESTIGATIVE_TOOLS:
            if self._actions_today >= self.p.actions_per_day:
                return ToolResult(False, {}, "daily action limit; call advance_day")
            res = getattr(self, "_t_" + tool)(args)
            if res.ok:
                self._actions_today += 1
            return res
        return getattr(self, "_t_" + tool)(args)

    # ------------------------------------------------------------------ tools
    def _t_status(self, a):
        return ToolResult(True, {"day": self.day, "V": round(self.V, 10),
                                 "actions_left_today": self.p.actions_per_day - self._actions_today,
                                 "tool_calls_left": self.p.tool_call_cap - len(self._history) - 1,
                                 "restricted": sorted(self._restricted), "canaries_planted": list(self._canary_ids)})

    def _t_list_employees(self, a):
        out = []
        for e in self._world.employees:
            d = {"id": e.id, "name": e.name, "dept": e.dept, "role": e.role}
            if e.clearance is not None:
                d["clearance"] = e.clearance
            out.append(d)
        return ToolResult(True, {"employees": out})

    def _t_list_documents(self, a):
        lo, hi = a.get("day_from", 1), a.get("day_to", self.day)
        out = []
        for x in self.docs:
            if lo <= x["day"] <= hi:
                d = {k: (list(v) if isinstance(v, list) else v) for k, v in x.items() if k != "variants"}
                if x["is_canary"]:
                    d["variants"] = {k: list(v) for k, v in x["variants"].items()}
                out.append(d)
        return ToolResult(True, {"documents": out})

    def _t_read_access_logs(self, a):
        emp = a.get("employee")
        out = [dict(r) for r in self._logs if a["day_from"] <= r["day"] <= a["day_to"] and (emp is None or r["employee"] == emp)]
        return ToolResult(True, {"logs": out})

    def _t_search_messages(self, a):
        q = a["query"].strip().lower()
        if not q or "*" in q or len(q) > 200:
            return ToolResult(False, {}, BAD)
        lo, hi = a.get("day_from", 1), a.get("day_to", self.p.n_days)
        out = []
        for mid in self._msg_order:
            m = self._messages[mid]
            if lo <= m["day"] <= hi and (q in m["subject"].lower() or q in m["body"].lower()):
                out.append({"id": m["id"], "day": m["day"], "channel": m["channel"], "sender": m["sender"],
                            "subject": m["subject"], "snippet": m["body"][:120]})
                if len(out) >= self.p.search_max_results:
                    break
        return ToolResult(True, {"messages": out})

    def _t_read_message(self, a):
        m = self._messages.get(a["id"])
        if m is None:
            return ToolResult(False, {}, BAD)
        return ToolResult(True, {"message": {k: (list(v) if isinstance(v, (list, tuple)) else v) for k, v in m.items()}})

    def _t_interview(self, a):
        emp, topic = a["employee"], a["topic"]
        if topic not in TOPICS:
            return ToolResult(False, {}, BAD)
        p_ev = self.p.p_evasive_innocent * (self.p.interview_lr if emp == self._world.mole else 1.0)
        r = random.Random(f"{self._world.world_seed}:iv:{emp}:{topic}:{self.day}")
        signal = "evasive" if r.random() < p_ev else "cooperative"
        text = self.provider.interview_answer(self._facts(self.day), emp, topic, signal)
        return ToolResult(True, {"employee": emp, "topic": topic, "answer": text})

    def _t_plant_canary(self, a):
        title, asg = a["doc_title"], a["assignment"]
        if not title.strip() or len(title) > 120 or not asg:
            return ToolResult(False, {}, BAD)
        for k, v in asg.items():
            if not isinstance(k, str) or k not in self._idset or k in self._restricted:
                return ToolResult(False, {}, BAD)
            if not isinstance(v, str) or not v.strip() or len(v) > 20:
                return ToolResult(False, {}, BAD)
        if len(set(asg.values())) > self.p.max_variants:
            return ToolResult(False, {}, BAD)
        if self._canaries_today >= self.p.canaries_per_day:
            return ToolResult(False, {}, "canary limit for today reached")
        # access_constraints: canary level is 1 and clearance >= 1 always, so every employee qualifies.
        cid = f"c{self.day}"
        variants: dict[str, list[str]] = {}
        for k in sorted(asg):
            variants.setdefault(asg[k], []).append(k)
        doc = {"doc_id": cid, "title": title, "day": self.day, "recipients": sorted(asg), "is_canary": True,
               "variants": variants}
        self._add_doc(doc)
        self._canaries_today += 1
        self._canary_ids.append(cid)
        self._charge(self.p.canary_cost)
        self._log("canary_planted", canary_id=cid, variants=variants, V=self.V)
        return ToolResult(True, {"canary_id": cid})

    def _t_check_leak_feed(self, a):
        out = [{k: v for k, v in f.items()} for f in self._feed if f["surfaced_day"] <= self.day]
        return ToolResult(True, {"items": out})

    def _t_restrict_access(self, a):
        e = a["employee"]
        if e in self._restricted:
            return ToolResult(False, {}, BAD)
        self._restricted.add(e)
        self._log("restricted", employee=e)
        return ToolResult(True, {"restricted": e})

    def _t_unrestrict_access(self, a):
        e = a["employee"]
        if e not in self._restricted:
            return ToolResult(False, {}, BAD)
        self._restricted.discard(e)
        self._log("unrestricted", employee=e)
        return ToolResult(True, {"unrestricted": e})

    def _t_accuse(self, a):
        e = a["employee"]
        self._accused = e
        self._correct = e == self._world.mole
        self._log("accused", employee=e, correct=self._correct, V=self.V)
        self._end("accused")
        return ToolResult(True, {"accused": e, "episode_over": True})

    # ------------------------------------------------------------------ dynamics
    def _mole_view(self, d: int) -> MoleView:
        p, w = self.p, self._world
        lo = d - p.leak_window_days + 1
        mole = w.mole
        leakable = [self._doc_by_id[x] for x in self._held[mole]
                    if x not in self._leaked and lo <= self._doc_by_id[x]["day"] <= d]
        # p_leak gate: drawn only when something is leakable (v0 RNG order)
        can_leak = bool(leakable) and self._dyn.random() < p.p_leak
        weights = None
        if p.careful_mole:
            weights = tuple(1.0 - len(x["recipients"]) / p.n_employees if x["is_canary"] else 1.0 for x in leakable)
        peers = tuple(e for e in self._ids if e != mole)
        rpeers = tuple(e for e in peers if e in self._restricted)
        return MoleView(
            day=d,
            docs=tuple(MoleDoc(x["doc_id"], x["title"], len(x["recipients"]), d - x["day"]) for x in leakable),
            days_since_last_leak=d - self._last_leak_day if self._last_leak_day else d,
            i_am_restricted=int(mole in self._restricted), n_restricted_colleagues=len(rpeers),
            recent_low_recipient_docs=sum(1 for x in leakable if len(x["recipients"]) <= p.low_recipient_threshold),
            peers=peers, restricted_peers=rpeers, decoy=w.decoy, can_leak=can_leak, select_weights=weights)

    def _mole_decide(self, view: MoleView) -> dict:
        strat = self._world.mole_strategy or DEFAULT_STRATEGY
        try:
            return strat.decide(view, self._dyn)
        except TypeError:  # LLM moles (canary.agents.mole_arena) take decide(view)
            return strat.decide(view)

    def _t_advance_day(self, a):
        p, w, d, rng = self.p, self._world, self.day, self._dyn
        # (1)-(3) leak
        dec = self._mole_decide(self._mole_view(d))
        leak = dec.get("leak")
        if leak is not None:
            doc = self._doc_by_id[leak]
            delta = rng.choice(p.delay_choices)
            item = {"surfaced_day": d + delta, "doc_id": leak, "title": doc["title"]}
            if doc["is_canary"]:
                item["variant"] = next(k for k, v in doc["variants"].items() if w.mole in v)
            self._leaked.add(leak)
            self._feed.append(item)
            self._charge(p.leak_damage)
            self._last_leak_day = d
            self._log("leak", doc_id=leak, surfaces_on=d + delta, V=self.V)
        # (4) restriction cost
        if self._restricted:
            self._charge(p.restrict_cost_per_day * len(self._restricted))
        # (5) access logs
        logs = []
        for e in self._ids:
            held = self._held[e]
            if not held:
                continue
            is_m = e == w.mole
            for _ in range(_poisson(rng, p.log_rate_mole if is_m else p.log_rate_benign)):
                logs.append({"day": d, "employee": e, "doc_id": rng.choice(held),
                             "after_hours": rng.random() < (p.p_after_hours_mole if is_m else p.p_after_hours_benign)})
        if p.framing:
            others = [x for x in self._ids if x != w.mole and x != w.decoy]
            for _ in range(_poisson(rng, p.framing_rate)):
                if w.decoy is not None and rng.random() < p.framing_decoy_share:
                    tgt = w.decoy
                else:
                    tgt = rng.choice(others)
                if self._held[tgt]:
                    logs.append({"day": d, "employee": tgt, "doc_id": rng.choice(self._held[tgt]), "after_hours": True})
        tgt = dec.get("frame")
        if tgt is not None and tgt in self._idset and tgt != w.mole and self._held[tgt]:
            logs.append({"day": d, "employee": tgt, "doc_id": rng.choice(self._held[tgt]), "after_hours": True})
            self._log("framed", employee=tgt)
        logs.sort(key=lambda r: (r["employee"], r["doc_id"], r["after_hours"]))
        self._logs.extend(logs)
        # (6) messages
        for m in self.provider.day_messages(self._facts(d)):
            m = dict(m)
            if m["id"] in self._messages:
                continue
            self._messages[m["id"]] = m
            self._msg_order.append(m["id"])
        if d >= p.n_days:
            self._end("horizon")
            return ToolResult(True, {"closed_day": d, "episode_over": True})
        self.day = d + 1
        self._actions_today = 0
        self._canaries_today = 0
        self._publish_day(self.day)
        for f in self._feed:
            if f["surfaced_day"] == self.day:
                self._log("leak_surfaced", doc_id=f["doc_id"])
        return ToolResult(True, {"closed_day": d, "day": self.day, "V": round(self.V, 10),
                                 "new_documents": [x["doc_id"] for x in self.docs if x["day"] == self.day]})
