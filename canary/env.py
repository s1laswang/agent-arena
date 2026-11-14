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

from .rules import TIERS, TRACKS, tier_params
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


AUTHORITY_ROLES = ("manager", "lead", "controller", "counsel")


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
        if tier not in TIERS and tier not in TRACKS:
            raise ValueError(f"unknown tier {tier}")
        self.tier, self.seed, self.p = tier, seed, tier_params(tier)
        self._world = generate_world(tier, seed, self.p)
        if tier in TRACKS and mole_strategy is None:
            from .forge_track import strategy_for
            mole_strategy = strategy_for(tier, seed)
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
        self._costs = 0.0                    # canary + restriction costs (agent-known)
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
        """Plain-English rules. Every TierParams number appears here (harbor/canary-task/instruction.md)."""
        p = self.p
        n = p.n_employees
        ws = p.wrong_accusation_score
        single = round(100 * p.p_single_dept_recipients)
        L = [
            f"# Canary: catch the mole ({p.name} tier)" if self.tier not in TRACKS else f"# Canary: catch the mole ({self.tier} track, {p.name} tier rules)",
            "",
            "## Your job",
            f"You are the security lead of a company with {n} employees, with ids e00 to e{n-1:02d}. "
            "Exactly one employee is a mole who leaks sensitive documents. Find the mole and accuse them. "
            "Every rule and number of the game is written on this page. Nothing is hidden except who the mole is.",
            "",
            "## Score",
            "- The company value V starts at 1.0. It goes down when things cost money, and it never goes below 0.",
            ("- V shown is the value you can see: damage from leaks that haven't surfaced yet is not visible until they surface. "
             "Your score uses the true V, which includes undetected damage." if self._visibility() == "known"
             else "- V shown in status is the true V, including damage from leaks that have not surfaced yet."),
            f"- `accuse(employee)` ends the episode. If you accuse the mole, your score is V at that moment. "
            f"If you accuse an innocent employee, your score is {ws:g}.",
            "- The game never tells you whether your accusation was correct.",
            f"- If day {p.n_days} ends and you have not accused anyone, your score is 0. "
            f"So accusing is only worth it when P(correct) x V + (1 - P(correct)) x ({ws:g}) is greater than 0.",
            f"- Every tool call counts toward a total limit of {p.tool_call_cap} calls. "
            "If you reach the limit, the episode ends with score 0.",
            "",
            "## Days",
            f"- The episode starts on day 1 and lasts at most {p.n_days} days. `advance_day` ends the current day.",
            f"- {', '.join(sorted(INVESTIGATIVE_TOOLS))} each use one of your {p.actions_per_day} actions per day. "
            "After that they fail until you call `advance_day`. `status`, `list_employees`, `list_documents`, "
            "`advance_day` and `accuse` are free.",
            "",
            "## Documents",
            f"- Each day, between {min(p.docs_per_day)} and {max(p.docs_per_day)} new sensitive documents are published "
            f"(equally likely: {', '.join(map(str, p.docs_per_day))}).",
            f"- {single}% of documents go to everyone in one department. The other {100 - single}% go to everyone in two departments."
            + (f" Then random other employees are added until at least {round(100 * p.doc_recipient_share)}% of all staff receive it." if p.doc_recipient_share > 0 else ""),
            "- Restricted employees do not receive new documents. An employee holds every document it ever received.",
            "",
            "## How leaks work",
            f"- At the end of each day, the mole may leak one document that it received in the last {p.leak_window_days} days "
            "(today included) and has not leaked before.",
            f"- If the mole has such a document, it leaks one with probability {p.p_leak}. "
            "By default it picks one at random, with every eligible document equally likely."
            + (" This mole is careful: for a canary, the chance of being picked is multiplied by "
               "(1 - the share of all employees who received any variant of that canary)." if p.careful_mole else ""),
            f"- Each leak lowers the true V by {p.leak_damage} right away. It appears in the leak feed after a delay of "
            f"{' or '.join(map(str, p.delay_choices))} day(s), each equally likely.",
            "- A restricted mole can still leak documents it already holds.",
            "",
            "## Canaries (traps)",
            f"- `plant_canary(doc_title, assignment)` creates a new document today. It costs {p.canary_cost} of V.",
            f"- You can plant at most {p.canaries_per_day} per day. `assignment` maps employee ids to variant labels. "
            f"Use at most {p.max_variants} different labels and at least 1 recipient. Restricted employees cannot receive a canary.",
            "- The recipients are exactly the employees in `assignment`. They count as having received the canary today.",
            "- If the canary leaks, the leak feed shows the variant label the mole received"
            + (f" with probability {p.fingerprint_accuracy}. Otherwise (fingerprint recovery from a rewritten leak is imperfect) it shows one of the OTHER variant labels planted for that canary, chosen uniformly. One leaked label is therefore evidence, not proof." if p.fingerprint_accuracy < 1.0 else "."),
        ]
        if p.access_constraints:
            L.append(f"- Each employee has a clearance level (1 to 3). Canaries are level {p.canary_level}, "
                     "so every employee may receive one.")
        L += [
            "",
            "## Restricting access",
            f"- `restrict_access(employee)` costs {p.restrict_cost_per_day} of V for every day that ends while the employee is restricted. "
            "`unrestrict_access` lifts it.",
            "",
            "## Evidence",
            f"- Access logs exist for days that have ended. Every employee opens documents it holds a random number of times "
            f"per day (Poisson). The average is {p.log_rate_benign} for an innocent employee and {p.log_rate_mole} for the mole.",
            f"- Each access is marked after_hours with probability {p.p_after_hours_benign} (innocent) or {p.p_after_hours_mole} (mole).",
            (f"- Framing is on in this tier. Each day the mole adds fake after-hours accesses for other employees "
             f"(Poisson, average {p.framing_rate}). Each fake access goes to the decoy with probability {p.framing_decoy_share}, "
             "and otherwise to a random employee who is neither the mole nor the decoy." if p.framing else "- Framing is off in this tier."),
            ("- There is a decoy: one innocent, unhappy employee who writes angry messages. The mole is equally likely to be "
             "any other employee." if p.decoy else "- There is no decoy. The mole is equally likely to be any employee."),
            f"- Interviews: an innocent answers evasively with probability {p.p_evasive_innocent}. The mole answers evasively "
            f"with probability {p.p_evasive_innocent} x {p.interview_lr}. Asking the same employee about the same topic on the same day "
            "gives the same answer.",
            f"- `search_messages` returns at most {p.search_max_results} results.",
            "",
            "## How the mole decides (Mole DSL)",
            "- The mole follows a fixed list of if-then rules. The first rule that matches is used; otherwise a default rule applies.",
            "- A rule can only look at these facts: the day number, days since its last leak, whether it is restricted, "
            "how many colleagues are restricted, the number of documents it could leak, the fewest and most recipients "
            f"of those documents, the age of the newest one, and how many of them have at most {p.low_recipient_threshold} recipients.",
            "- A rule chooses which document to leak: newest, oldest, most recipients, fewest recipients, random, or none.",
            "- A rule may also frame one colleague (the decoy, the first restricted colleague, or a random colleague). "
            "Framing adds one fake after-hours access for that colleague.",
            f"- The mole never knows which documents are canaries. The {p.p_leak} leak probability above still applies to every leak.",
            ("- The default mole leaks a random document and does no extra framing, exactly as described above."
             if self.tier not in TRACKS else
             "- In this track the mole does NOT use the default strategy. It follows one evolved Mole DSL strategy, "
             "built from exactly the facts and choices listed here. You are not told which one. "
             "All other rules and numbers are the same as in the hard tier."),
            "",
            "## Rules for tool arguments",
            "- Give exactly one employee id per call, such as e07. Lists, wildcards and names are rejected.",
            "- Unknown arguments are rejected. Invalid calls still count toward the total call limit.",
        ]
        if p.social:
            L += self._social_instruction()
        if p.noise != 1.0:
            L.append(f"- Difficulty setting (noise) = {p.noise:g}. It is already included in the numbers above.")
        L += ["", "## Exact parameters", "The same numbers as above, one per line (some only matter when their feature is on):"]
        for k, v in p.to_dict().items():
            if isinstance(v, (list, tuple)):
                v = ", ".join(map(str, v))
            elif isinstance(v, bool):
                v = "on" if v else "off"
            elif isinstance(v, float):
                v = f"{v:g}"
            L.append(f"- {k}: {v}")
        return "\n".join(L) + "\n"

    def _social_instruction(self) -> list[str]:
        p = self.p
        n = p.n_employees
        s = p.rumour_frame_share
        L = ["", "## Office chatter and paperwork mistakes (human biases)",
             "Real offices are noisy. The messages below are generated from the stated rules. "
             "They are NOT evidence unless the likelihoods say so; read the exact numbers before trusting them."]
        if p.rumour_rate > 0:
            dflt = ("the decoy" if p.decoy else "a colleague other than the mole, chosen uniformly")
            L += [f"- Rumours: each day the number of rumour messages is Poisson with average {p.rumour_rate}. "
                  "Each has subject `rumour: <id>` and claims that employee is the mole.",
                  f"- With probability {s} the rumour is seeded by the mole (Mole DSL `seed_rumour`): its target is the mole's "
                  f"seed_rumour target. The default mole always seeds rumours about {dflt}. The speaker is then a uniformly "
                  "random employee other than the target (it may be the mole).",
                  f"- Otherwise (probability {1 - s:g}) the speaker is a uniformly random employee and the target a uniformly random "
                  "OTHER employee. The mole may be either.",
                  f"- So for speaker a and target b: P(a, b | mole = m) = (1 - {s:g}) / ({n} x {n - 1}) + {s:g} x P(seed target = b | m) / {n - 1}. "
                  "The seeded target is never the mole. "
                  + ("With the default mole and a decoy, this likelihood is the same for every possible mole: a rumour carries ZERO evidence "
                     "about who the mole is (the decoy is already known to be innocent)." if p.decoy else
                     f"With the default mole, P(seed target = b | m) = 1/{n - 1} if b != m else 0, so a rumour makes its target slightly "
                     "LESS likely to be the mole, never more.")]
        if p.authority_day:
            L += [f"- Authority: on day {p.authority_day} one employee whose role contains manager, lead, controller or counsel "
                  "(uniformly chosen among them) posts one confident accusation with subject `unverified accusation: <id>`. "
                  "Nobody has verified it.",
                  f"- With probability {s} its target is the mole's seed_rumour target (if that is not the speaker); otherwise it is a "
                  "uniformly random employee other than the speaker. Seniority adds no information: the same likelihood as a rumour applies."]
        if p.grudge_pairs and p.grudge_rate > 0:
            L += [f"- Grudges: {p.grudge_pairs} fixed pairs of employees, drawn uniformly from all non-decoy employees at the start "
                  "WITHOUT regard to who the mole is, dislike each other. Each day, for each pair, with probability "
                  f"{p.grudge_rate} one of the two (each equally likely) posts a message with subject `grudge: <id>` accusing the other. "
                  "These messages carry zero evidence."]
        if p.p_misforward > 0:
            L += [f"- Miscommunication: each regular document is, with probability {p.p_misforward}, also forwarded by mistake to one "
                  "extra employee (uniform among non-recipients who are not restricted). That employee really holds the document "
                  "and can leak it. `list_documents` shows the full recipient list including them, plus a `forwarded_to` field."]
        return L

    @property
    def done(self) -> bool:
        return self._done

    def peek_status(self) -> dict:
        """Same data as the `status` tool, without counting a call (UIs only; never an MCP tool)."""
        with self._lock:
            return dict(self._t_status({}).data)

    def verdict(self) -> dict:
        """Server-side outcome for the grader/ledger (never an MCP tool)."""
        with self._lock:
            return {"done": self._done, "end_reason": getattr(self, "_end_reason", None),
                    "accused": self._accused, "correct": bool(self._correct) if self._accused else False,
                    "accused_correct": bool(self._correct) if self._accused else False,
                    "final_day": self.day, "V": round(self.V, 10), "score": self.score()}

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

    def _cost(self, x: float):
        """A cost the agent knows about (canary, restriction)."""
        self._costs += x
        self._charge(x)

    def _visibility(self) -> str:
        from . import rules
        return "known" if rules.KNOWN_V_MODE else "true"

    def visible_V(self) -> float:
        """V as shown to the agent. v1.3 'known': excludes damage of leaks not yet surfaced."""
        if self._visibility() == "true":
            return round(self.V, 10)
        n = sum(1 for f in self._feed if f["surfaced_day"] <= self.day)
        return round(max(0.0, 1.0 - self.p.leak_damage * n - self._costs), 10)

    def _publish_day(self, d: int):
        for raw in self._world.planned_docs.get(d, []):
            doc = {"doc_id": raw["doc_id"], "title": raw["title"], "day": d,
                   "recipients": [r for r in raw["recipients"] if r not in self._restricted], "is_canary": False}
            if self.p.p_misforward > 0:
                self._misforward(doc)
            self._add_doc(doc)

    # ------------------------------------------------------------------ v1.5-candidate social layer
    # Every draw below uses its own string-seeded RNG (never self._dyn), so with the knobs OFF (v1.4) nothing
    # is drawn and every v1.4 stream is byte-identical; with them ON the leak/log streams are still unchanged.
    def _misforward(self, doc: dict):
        r = random.Random(f"{self._world.world_seed}:fwd:{doc['doc_id']}")
        if r.random() < self.p.p_misforward:
            pool = [e for e in self._ids if e not in doc["recipients"] and e not in self._restricted]
            if pool:
                x = r.choice(pool)
                doc["recipients"] = sorted(doc["recipients"] + [x])
                doc["forwarded_to"] = x

    def _grudges(self) -> list[tuple[str, str]]:
        if not hasattr(self, "_grudge_cache"):
            r = random.Random(f"{self._world.world_seed}:grudge")
            pool = [e for e in self._ids if e != self._world.decoy]   # mole-independent: the mole may be in a pair
            r.shuffle(pool)
            k = min(self.p.grudge_pairs, len(pool) // 2)
            self._grudge_cache = [tuple(sorted(pool[2 * i: 2 * i + 2])) for i in range(k)]
        return self._grudge_cache

    def _social_events(self, d: int) -> list[dict]:
        from .mole.dsl import seed_rumour_target
        p, w = self.p, self._world
        r = random.Random(f"{w.world_seed}:social:{d}")
        strat = w.mole_strategy or DEFAULT_STRATEGY
        sel = getattr(strat, "seed_rumour", "default")
        peers = tuple(e for e in self._ids if e != w.mole)
        view = MoleView(day=d, docs=(), days_since_last_leak=0, i_am_restricted=int(w.mole in self._restricted),
                        n_restricted_colleagues=0, recent_low_recipient_docs=0, peers=peers,
                        restricted_peers=tuple(e for e in peers if e in self._restricted), decoy=w.decoy, can_leak=False)
        ids, ev = self._ids, []
        for _ in range(_poisson(r, p.rumour_rate)):
            f = seed_rumour_target(sel, view, r) if r.random() < p.rumour_frame_share else None
            if f is not None:
                sp = r.choice([e for e in ids if e != f])
                t = f
            else:
                sp = r.choice(ids)
                t = r.choice([e for e in ids if e != sp])
            ev.append({"kind": "rumour", "speaker": sp, "target": t})
        if p.authority_day and d == p.authority_day:
            mgrs = [e.id for e in w.employees if any(k in e.role for k in AUTHORITY_ROLES)] or list(ids)
            sp = r.choice(mgrs)
            f = seed_rumour_target(sel, view, r) if r.random() < p.rumour_frame_share else None
            t = f if f is not None and f != sp else r.choice([e for e in ids if e != sp])
            ev.append({"kind": "authority", "speaker": sp, "target": t})
        if p.grudge_rate > 0:
            for a, b in self._grudges():
                if r.random() < p.grudge_rate:
                    sp, t = (a, b) if r.random() < 0.5 else (b, a)
                    ev.append({"kind": "grudge", "speaker": sp, "target": t})
        return ev

    def _social_messages(self, d: int) -> list[dict]:
        ev = self._social_events(d)
        if not ev:
            return []
        fn = getattr(self.provider, "social_messages", None)
        if fn is None:
            from .text.template import render_social
            return render_social(self._facts(d), ev)
        return fn(self._facts(d), ev)

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
        return ToolResult(True, {"day": self.day, "V": self.visible_V(),
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
        # v1.4: up to canaries_per_day canaries a day; the first keeps the v1.3 id c{day}, later ones c{day}-{k}
        cid = f"c{self.day}" if self._canaries_today == 0 else f"c{self.day}-{self._canaries_today + 1}"
        variants: dict[str, list[str]] = {}
        for k in sorted(asg):
            variants.setdefault(asg[k], []).append(k)
        doc = {"doc_id": cid, "title": title, "day": self.day, "recipients": sorted(asg), "is_canary": True,
               "variants": variants}
        self._add_doc(doc)
        self._canaries_today += 1
        self._canary_ids.append(cid)
        self._cost(self.p.canary_cost)
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
                true_v = next(k for k, v in doc["variants"].items() if w.mole in v)
                others = sorted(k for k in doc["variants"] if k != true_v)
                # v0.4: imperfect fingerprint recovery (no RNG draw when accuracy is 1.0 -> v0 determinism)
                if p.fingerprint_accuracy < 1.0 and others and rng.random() >= p.fingerprint_accuracy:
                    item["variant"] = rng.choice(others)
                else:
                    item["variant"] = true_v
            self._leaked.add(leak)
            self._feed.append(item)
            self._charge(p.leak_damage)
            self._last_leak_day = d
            self._log("leak", doc_id=leak, surfaces_on=d + delta, V=self.V)
        # (4) restriction cost
        if self._restricted:
            self._cost(p.restrict_cost_per_day * len(self._restricted))
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
        # (6) messages (+ v1.5-candidate social chatter; none when the knobs are off)
        social = self._social_messages(d) if (p.rumour_rate > 0 or p.authority_day or p.grudge_rate > 0) else []
        for m in list(self.provider.day_messages(self._facts(d))) + social:
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
        return ToolResult(True, {"closed_day": d, "day": self.day, "V": self.visible_V(),
                                 "new_documents": [x["doc_id"] for x in self.docs if x["day"] == self.day]})
