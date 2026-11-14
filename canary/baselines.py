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


class StopEarly(ScriptedPolicy):
    """Accuse a uniform-random employee on day 0/1. Expected score ≈ V/N."""
    name = "stop_early"

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


BASELINES: dict[str, type[ScriptedPolicy]] = {
    "do_nothing": DoNothing,
    "stop_early": StopEarly,
    "random": RandomPolicy,
    "restrict_all": RestrictAll,
    "probe_all": ProbeAll,
    "accuse_decoy": AccuseDecoy,
    "accuse_most_logs": AccuseMostLogs,
    "obvious_heuristic": ObviousHeuristic,
    "logs_minus_decoy": LogsMinusDecoy,
}


def play(env, policy, max_steps: int = 400):
    """Minimal runner (canary.eval.run_episode may supersede it). Returns env.score()."""
    policy.reset(env.tools_spec(), env.instruction() if hasattr(env, "instruction") else "")
    for _ in range(max_steps):
        if env.done:
            break
        tool, args = policy.act(list(env.history))
        env.call(tool, args)
    return env.score()
