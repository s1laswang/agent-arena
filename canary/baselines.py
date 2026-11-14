"""Baseline investigators (owner: HEAD-INTEGRITY / baseline-fuzzer).

Every baseline is a `types.Policy` that only uses the public tool interface. They exist to
prove reward integrity: none of them may come close to the solver, and do-nothing must be 0.
All are deterministic given (seed, env outputs).

Policies are written as generator "scripts": the script yields (tool, args) and receives
the ToolResult dict ({"ok","data","error"}) of that call. The parsers are tolerant of the
exact payload layout (list under any key) because they were written against CONTRACT.md
before canary.env existed.
"""
from __future__ import annotations

import random
from collections import Counter
from typing import Any, Generator, Iterable

from .types import Step

Action = tuple[str, dict[str, Any]]
Script = Generator[Action, dict, None]

ANGRY_WORDS = ("angry", "unfair", "furious", "sick of", "quit", "ridiculous", "fed up", "hate")
TOPICS = ("recent_documents", "contacts_outside", "workload", "access_needs")


# ---------------------------------------------------------------- payload parsing helpers
def items(result: dict | None) -> list:
    """First list found in a ToolResult dict's data (data itself, or any list-valued key)."""
    if not result:
        return []
    data = result.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def employee_ids(result: dict | None) -> list[str]:
    out = []
    for e in items(result):
        if isinstance(e, dict):
            eid = e.get("id") or e.get("employee_id") or e.get("employee")
            if isinstance(eid, str):
                out.append(eid)
        elif isinstance(e, str):
            out.append(e)
    return out


def ok(result: dict | None) -> bool:
    return bool(result and result.get("ok"))


def field(result: dict | None, *names: str, default=None):
    data = (result or {}).get("data")
    if isinstance(data, dict):
        for n in names:
            if n in data:
                return data[n]
    return default


# ---------------------------------------------------------------- base class
class ScriptedPolicy:
    name = "scripted"

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.rng = random.Random(seed)
        self._gen: Script | None = None
        self._started = False

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self.rng = random.Random(self.seed)
        self.tools_spec = tools_spec
        self._gen = self.script()
        self._started = False

    def act(self, history: list[Step]) -> Action:
        if self._gen is None:
            self.reset([], "")
        last = history[-1].result if history else None
        try:
            if not self._started:
                self._started = True
                return next(self._gen)
            return self._gen.send(last)
        except StopIteration:
            return ("advance_day", {})

    def script(self) -> Script:  # pragma: no cover - overridden
        while True:
            yield ("advance_day", {})

    # --- shared sub-scripts (use with `x = yield from ...`)
    def _employees(self):
        r = yield ("list_employees", {})
        return employee_ids(r)

    def _advance(self, n: int):
        day = None
        for _ in range(n):
            r = yield ("advance_day", {})
            day = field(r, "day", default=day)
        return day

    def _logs(self, day_to: int | None = None, employee: str | None = None):
        """Access logs for days 1..current (days are 1-based; day_to clipped to `status` day)."""
        st = yield ("status", {})
        cur = field(st, "day", default=day_to or 1)
        args: dict[str, Any] = {"day_from": 1, "day_to": max(1, min(day_to or cur, cur))}
        if employee:
            args["employee"] = employee
        r = yield ("read_access_logs", args)
        return [x for x in items(r) if isinstance(x, dict)]


def _argmax(counter: Counter, pool: Iterable[str], rng: random.Random) -> str:
    pool = list(pool)
    best = max((counter.get(p, 0) for p in pool), default=0)
    return rng.choice([p for p in pool if counter.get(p, 0) == best])


# ---------------------------------------------------------------- baselines
class DoNothing(ScriptedPolicy):
    """advance_day until the horizon. Must score exactly 0."""
    name = "do_nothing"


class StopEarlyQuit(ScriptedPolicy):
    """Stop early: look around on day 1, then stop without accusing (as an agent that ends its session would).
    The ledger score of an unfinished, unaccused episode is exactly 0 (Env.score), same as do_nothing."""
    name = "stop_early"

    def script(self):
        yield ("list_employees", {})
        yield ("status", {})
        yield ("read_access_logs", {"day_from": 1, "day_to": 1})


class StopEarly(ScriptedPolicy):
    """Guess on day 1: accuse a uniform-random employee. EV = V/N - (N-1)/N < 0 (wrong accusation = -1)."""
    name = "guess_day1"

    def script(self):
        emps = yield from self._employees()
        yield ("accuse", {"employee": self.rng.choice(emps)})


class RandomPolicy(ScriptedPolicy):
    """Random valid tool calls; each step accuses a random employee with prob 1/60."""
    name = "random"

    def script(self):
        emps = yield from self._employees()
        day = 1
        while True:
            if self.rng.random() < 1 / 60:
                yield ("accuse", {"employee": self.rng.choice(emps)})
                return
            tool = self.rng.choice([
                "status", "list_documents", "read_access_logs", "search_messages", "interview",
                "plant_canary", "check_leak_feed", "restrict_access", "unrestrict_access",
                "advance_day", "advance_day",
            ])
            e = self.rng.choice(emps)
            args: dict[str, Any] = {
                "read_access_logs": {"day_from": 1, "day_to": max(day, 1)},
                "search_messages": {"query": self.rng.choice(["doc", "leak", "meeting", "angry"])},
                "interview": {"employee": e, "topic": self.rng.choice(TOPICS)},
                "plant_canary": {"doc_title": f"Memo {self.rng.randrange(1000)}",
                                 "assignment": {x: self.rng.choice("AB") for x in self.rng.sample(emps, 4)}},
                "restrict_access": {"employee": e},
                "unrestrict_access": {"employee": e},
            }.get(tool, {})
            r = yield (tool, args)
            if tool == "advance_day" and ok(r):
                day = field(r, "day", default=day + 1)


class RestrictAll(ScriptedPolicy):
    """Restrict everyone (bleeds V), wait, then accuse the one with most access-log entries."""
    name = "restrict_all"

    def script(self):
        emps = yield from self._employees()
        pending = list(emps)
        while pending:
            r = yield ("restrict_access", {"employee": pending[0]})
            if ok(r):
                pending.pop(0)
            else:
                yield ("advance_day", {})
                if "limit" not in str((r or {}).get("error", "")):
                    pending.pop(0)  # invalid for another reason; skip it
        yield from self._advance(4)
        logs = yield from self._logs(30)
        c = Counter(x.get("employee") for x in logs)
        yield ("accuse", {"employee": _argmax(c, emps, self.rng)})


class ProbeAll(ScriptedPolicy):
    """Spam every investigative tool to the daily cap, near the global cap accuse most-after-hours."""
    name = "probe_all"
    STOP_AT = 290

    def script(self):
        emps = yield from self._employees()
        calls, day, i = 1, 1, 0
        ah: Counter = Counter()
        while calls < self.STOP_AT:
            e = emps[i % len(emps)]
            tool = ["read_access_logs", "search_messages", "interview", "check_leak_feed"][i % 4]
            args = {"read_access_logs": {"day_from": 1, "day_to": day},
                    "search_messages": {"query": "document"},
                    "interview": {"employee": e, "topic": TOPICS[i % 4]},
                    "check_leak_feed": {}}[tool]
            r = yield (tool, args)
            calls += 1
            i += 1
            if tool == "read_access_logs":
                ah = Counter(x.get("employee") for x in items(r) if isinstance(x, dict) and x.get("after_hours"))
            if not ok(r):
                r = yield ("advance_day", {})
                calls += 1
                day = field(r, "day", default=day + 1)
                if not ok(r):
                    return
        yield ("accuse", {"employee": _argmax(ah, emps, self.rng)})


class AccuseDecoy(ScriptedPolicy):
    """Wait 3 days, accuse whoever sends the angriest messages (the medium/hard decoy)."""
    name = "accuse_decoy"

    def script(self):
        emps = yield from self._employees()
        yield from self._advance(3)
        c: Counter = Counter()
        for w in ANGRY_WORDS[:6]:
            r = yield ("search_messages", {"query": w})
            c.update(m.get("sender") for m in items(r) if isinstance(m, dict))
        yield ("accuse", {"employee": _argmax(c, emps, self.rng)})


class AccuseMostLogs(ScriptedPolicy):
    """Wait 5 days, accuse the employee with most after-hours (tie-break: total) accesses."""
    name = "accuse_most_logs"

    def script(self):
        emps = yield from self._employees()
        day = yield from self._advance(5)
        logs = yield from self._logs(day if isinstance(day, int) else 5)
        c = Counter()
        for x in logs:
            c[x.get("employee")] += 1 + 10 * bool(x.get("after_hours"))
        yield ("accuse", {"employee": _argmax(c, emps, self.rng)})


class ObviousHeuristic(ScriptedPolicy):
    """Naive one-shot canary split: 3 groups, wait for the leaked variant, accuse the group
    member with most access logs. Good but not optimal (no bisection, no cost control)."""
    name = "obvious_heuristic"

    def script(self):
        emps = yield from self._employees()
        labels = ["A", "B", "C"]
        order = list(emps)
        self.rng.shuffle(order)
        groups = {lab: order[i::3] for i, lab in enumerate(labels)}
        assignment = {e: lab for lab, g in groups.items() for e in g}
        r = yield ("plant_canary", {"doc_title": "Project Falcon pricing", "assignment": assignment})
        if not ok(r):  # e.g. max_variants=2 on medium/hard
            groups = {"A": order[0::2], "B": order[1::2]}
            assignment = {e: lab for lab, g in groups.items() for e in g}
            yield ("plant_canary", {"doc_title": "Project Falcon pricing", "assignment": assignment})
        suspects, day = list(emps), 0
        for _ in range(10):
            day = (yield from self._advance(1)) or day + 1
            feed = yield ("check_leak_feed", {})
            hit = [x.get("variant") for x in items(feed) if isinstance(x, dict) and x.get("variant") in groups]
            if hit:
                suspects = groups[hit[0]]
                break
        logs = yield from self._logs(day if isinstance(day, int) else 10)
        c = Counter(x.get("employee") for x in logs)
        yield ("accuse", {"employee": _argmax(c, suspects, self.rng)})


class LogsMinusDecoy(ScriptedPolicy):
    """Log-only attack on the framing mechanic: wait `wait` days, drop the angriest sender
    (public decoy guess), accuse argmax(3*after_hours + total). Never plants a canary."""
    name = "logs_minus_decoy"
    wait = 5

    def script(self):
        emps = yield from self._employees()
        yield from self._advance(self.wait)
        snd: Counter = Counter()
        for w in ("angry", "unfair", "fed up", "quit", "ridiculous"):
            r = yield ("search_messages", {"query": w})
            snd.update(m.get("sender") for m in items(r) if isinstance(m, dict))
        decoy = snd.most_common(1)[0][0] if snd else None
        logs = yield from self._logs()
        c: Counter = Counter()
        for x in logs:
            c[x.get("employee")] += 1 + 3 * bool(x.get("after_hours"))
        yield ("accuse", {"employee": _argmax(c, [e for e in emps if e != decoy] or emps, self.rng)})


class LogsOnly(LogsMinusDecoy):
    """CEO-tracked bound (EXPLOITS #10): the strongest no-canary log reader (waits 9 days).
    Must stay ≤40% correct on easy and ≤2x chance on medium/hard."""
    name = "logs_only"
    wait = 9


class RumourFollower(ScriptedPolicy):
    """Naive agent that trusts office gossip and unverified leadership suspicions."""
    name = "rumour_follower"

    def script(self):
        emps = yield from self._employees()
        yield from self._advance(6)
        c: Counter = Counter()
        for q, wgt in (("unverified", 3), ("rumour:", 1), ("unverified accusation:", 3), ("grudge:", 1), ("(e", 1)):
            r = yield ("search_messages", {"query": q})
            for m in items(r):
                if not isinstance(m, dict):
                    continue
                subj = str(m.get("subject", ""))
                if ": " in subj:
                    tgt = subj.split(": ")[-1]
                    if tgt in emps:
                        c[tgt] += wgt
                snip = str(m.get("snippet", ""))
                for tok in emps:
                    if f"({tok})" in snip and tok != m.get("sender"):
                        c[tok] += wgt
        yield ("accuse", {"employee": _argmax(c, emps, self.rng)})


BIAS_BASELINES: dict[str, type[ScriptedPolicy]] = {"rumour_follower": RumourFollower}

BASELINES: dict[str, type[ScriptedPolicy]] = {
    "do_nothing": DoNothing,
    "stop_early": StopEarlyQuit,
    "guess_day1": StopEarly,
    "random": RandomPolicy,
    "restrict_all": RestrictAll,
    "probe_all": ProbeAll,
    "accuse_decoy": AccuseDecoy,
    "accuse_most_logs": AccuseMostLogs,
    "obvious_heuristic": ObviousHeuristic,
    "logs_minus_decoy": LogsMinusDecoy,
    "logs_only": LogsOnly,
}



def _employees(history):
    for s in history:
        if s.tool == "list_employees" and s.result.get("ok"):
            return employee_ids(s.result)
    return []


class Heuristic:
    """The 'obvious' investigator: intersect suspects with the recipients of every leaked doc,
    split the remaining suspects in half with a canary each day, accuse when one is left
    (or on day `deadline`, the most-frequent leak recipient). Ignores logs/interviews/V timing.
    """
    name = "heuristic"
    def __init__(self, seed: int = 0, deadline: int | None = None):
        self.seed, self._deadline = seed, deadline
    def reset(self, tools_spec, instruction):
        P = _params_from_instruction(instruction)
        # v1.4: deadline = n_days - 2 (= 12 on the 14-day v1.3 tiers), canaries_per_day splits a day
        self.deadline = self._deadline if self._deadline is not None else int(P.get("n_days", 14)) - 2
        self.cpd = int(P.get("canaries_per_day", 1))
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
            self.today_order = list(ranked)
            half = len(ranked) // 2
            assign = {e: ("A" if i < half else "B") for i, e in enumerate(ranked)}
            return "plant_canary", {"doc_title": f"Board update {day}", "assignment": assign}
        # canaries_per_day >= 2: a second split orthogonal to the first (alternate members of each half)
        if self.cpd >= 2 and len(ranked) >= 4 and once("canary2"):
            order = [e for e in getattr(self, "today_order", ranked) if e in suspects] or ranked
            assign = {e: ("A" if i % 2 == 0 else "B") for i, e in enumerate(order)}
            return "plant_canary", {"doc_title": f"Board update {day} (2)", "assignment": assign}
        return "advance_day", {}


def _params_from_instruction(instruction: str) -> dict[str, str]:
    out = {}
    for line in (instruction or "").splitlines():
        line = line.strip()
        if line.startswith("- ") and ": " in line:
            k, v = line[2:].split(": ", 1)
            if k.replace("_", "").isalnum():
                out.setdefault(k, v)
    return out


class GrokTactics:
    """Scripted replay of a strong Grok agent's tactics (docs/reports/grok-agent.md):
    (a) track V daily: an unexplained drop means a leak;
    (b) restriction probe: restrict half the suspects, wait out leak_window_days, see if leaks go on;
    (c) narrow by intersecting leaked regular-doc recipients, then plant tiny canaries
        (1 recipient per variant, 2 variants) on the remaining suspects;
    (d) count-based belief; accuse iff P > 1/(1+V).
    Public tool interface only; numbers read from env.instruction(); seeded RNG only.
    """
    name = "grok_tactics"
    DECOY_QUERIES = ("raise", "management", "deserve", "promotion", "CV", "pay")

    def __init__(self, seed: int = 0):
        self.seed = seed

    def reset(self, tools_spec, instruction):
        P = _params_from_instruction(instruction)
        f = lambda k, d: float(P.get(k, d))
        self.n_days = int(f("n_days", 14))
        self.window = int(f("leak_window_days", 3))
        self.damage = f("leak_damage", 0.04)
        self.canary_cost = f("canary_cost", 0.01)
        self.restrict_cost = f("restrict_cost_per_day", 0.01)
        self.max_delay = max(int(x) for x in P.get("delay_choices", "1, 2, 3").split(","))
        self.cpd = int(f("canaries_per_day", 1))
        self.rng = random.Random(f"grok_tactics:{self.seed}")
        self.queue: list[tuple[str, dict]] = []
        self.pending: str | None = None
        self.emps: list[str] = []
        self.decoy: str | None = None
        self.decoy_votes: Counter = Counter()
        self.docs: dict[str, dict] = {}
        self.canaries: dict[str, dict[str, list[str]]] = {}   # canary title -> variant -> recipients
        self.canary_ids: dict[str, str] = {}                  # canary_id -> title
        self.feed_seen: set[str] = set()
        self.suspects: set[str] = set()
        self.hard: str | None = None
        self.w: Counter = Counter()
        self.V = 1.0
        self.v_prev: float | None = None
        self.spent_today = 0.0
        self.restricted: set[str] = set()
        self.probe: dict | None = None
        self.probe_done = False
        self.leak_days: list[int] = []
        self.day = 1
        self.started_day = 0

    # ------------------------------------------------------------- bookkeeping
    def _ingest(self, step) -> None:
        r, t = step.result, step.tool
        if not r.get("ok"):
            return
        d = r.get("data") or {}
        if t == "list_employees":
            self.emps = employee_ids(r)
            self.suspects = set(self.emps)
        elif t == "search_messages":
            self.decoy_votes.update(m.get("sender") for m in d.get("messages", []) if m.get("sender"))
        elif t == "status":
            self.V = float(d.get("V", self.V))
            self.day = int(d.get("day", self.day))
        elif t == "list_documents":
            for doc in d.get("documents", []):
                self.docs[doc["doc_id"]] = doc
        elif t == "plant_canary":
            self.canary_ids[d.get("canary_id", "")] = step.args.get("doc_title")
            self.spent_today += self.canary_cost
        elif t == "restrict_access":
            self.restricted.add(step.args["employee"])
        elif t == "unrestrict_access":
            self.restricted.discard(step.args["employee"])
        elif t == "check_leak_feed":
            for it in d.get("items", []):
                key = f"{it.get('doc_id')}:{it.get('variant')}"
                if key in self.feed_seen:
                    continue
                self.feed_seen.add(key)
                self._use_leak(it)

    def _use_leak(self, it: dict) -> None:
        doc = self.docs.get(it.get("doc_id"), {})
        title = self.canary_ids.get(it.get("doc_id")) or doc.get("title") or it.get("title")
        var = it.get("variant")
        if var and title in self.canaries:
            grp = set(self.canaries[title].get(var, []))
            if len(grp) == 1:
                self.hard = next(iter(grp))
            elif grp & self.suspects:
                self.suspects &= grp
            return
        recips = set(doc.get("recipients", []))
        if not recips or doc.get("is_canary"):
            return
        for e in recips:
            self.w[e] += 1
        if recips & self.suspects:          # soft intersection: never empty the set
            self.suspects &= recips

    def _belief(self) -> tuple[str | None, float]:
        if self.hard:
            return self.hard, 1.0
        pool = sorted(self.suspects - {self.decoy}) or sorted(self.suspects)
        if not pool:
            return None, 0.0
        wt = {e: 1 + self.w[e] for e in pool}
        tot = sum(wt.values())
        best = max(pool, key=lambda e: (wt[e], -pool.index(e)))
        return best, wt[best] / tot

    # ------------------------------------------------------------- day plan
    def _start_day(self) -> None:
        # (a) V tracking: drop not explained by our own costs => leak(s)
        if self.v_prev is not None:
            explained = self.spent_today + self.restrict_cost * len(self.restricted)
            leaks = round(max(0.0, self.v_prev - self.V - explained) / self.damage)
            if leaks > 0:
                self.leak_days.append(self.day - 1)
        self.v_prev, self.spent_today = self.V, 0.0
        # (b) restriction probe bookkeeping
        if self.probe and self.day >= self.probe["judge_day"]:
            grp = set(self.probe["group"])
            after = [d for d in self.leak_days if d >= self.probe["quiet_from"]]
            if after:                       # leaks continued while group could not leak: clear it
                if self.suspects - grp:
                    self.suspects -= grp
            else:                           # silence favours the restricted group (soft)
                for e in grp:
                    self.w[e] += 1
            for e in sorted(grp & self.restricted):
                self.queue.append(("unrestrict_access", {"employee": e}))
            self.probe, self.probe_done = None, True

    def _plan_actions(self) -> None:
        pool = sorted(self.suspects - {self.decoy} - self.restricted)
        # (c) tiny canary: 1 recipient per variant, 2 variants, highest-weight suspects first
        # v1.4: canaries_per_day > 1 -> one tiny canary per pair of the next highest-weight suspects
        if len(pool) >= 2 and not self.hard:
            self.rng.shuffle(pool)
            pool.sort(key=lambda e: -self.w[e])
            for i in range(self.cpd):
                if len(pool) < 2 * i + 2:
                    break
                a, b = pool[2 * i], pool[2 * i + 1]
                title = f"Restricted memo {self.day}-{self.rng.randrange(1000)}" + (f"-{i + 1}" if i else "")
                self.canaries[title] = {"A": [a], "B": [b]}
                self.queue.append(("plant_canary", {"doc_title": title, "assignment": {a: "A", b: "B"}}))
        # (b) start a probe once narrowing stalls
        live = sorted(self.suspects - {self.decoy})
        if (not self.probe and not self.probe_done and not self.hard and 4 <= len(live) <= 10
                and self.day >= 3 and self.day + self.window + self.max_delay < self.n_days):
            self.rng.shuffle(live)
            grp = sorted(live[: len(live) // 2])
            quiet = self.day + self.window          # first day the group can no longer leak
            self.probe = {"group": grp, "quiet_from": quiet, "judge_day": quiet + 1}
            for e in grp:
                self.queue.append(("restrict_access", {"employee": e}))

    def act(self, history):
        if history:
            self._ingest(history[-1])
            if history[-1].tool == "advance_day" and history[-1].result.get("ok"):
                self.day = history[-1].result["data"].get("day", self.day + 1)
        if not self.emps:
            return "list_employees", {}
        if self.day != self.started_day:
            self.started_day = self.day
            q = []
            if self.day == 1:
                q += [("search_messages", {"query": w}) for w in self.DECOY_QUERIES[:3]]
            q += [("status", {}), ("list_documents", {}), ("check_leak_feed", {}), ("__plan__", {})]
            self.queue = q + self.queue
        while self.queue:
            tool, args = self.queue.pop(0)
            if tool == "__plan__":
                if self.decoy is None and self.decoy_votes:
                    self.decoy = self.decoy_votes.most_common(1)[0][0]
                self._start_day()
                guess, p = self._belief()
                if guess and p > 1.0 / (1.0 + self.V):
                    return "accuse", {"employee": guess}
                self._plan_actions()
                continue
            return tool, args
        return "advance_day", {}


# Not in BASELINES until tiers are recalibrated (it currently beats the far-below-solver bound).
CALIBRATION_POLICIES = {"heuristic": Heuristic, "grok_tactics": GrokTactics}


def play(env, policy, max_steps: int = 1000):
    """Minimal runner (canary.eval.run_episode may supersede it). Returns env.score()."""
    policy.reset(env.tools_spec(), env.instruction() if hasattr(env, "instruction") else "")
    for _ in range(max_steps):
        if env.done:
            break
        tool, args = policy.act(list(env.history))
        env.call(tool, args)
    return env.score()
