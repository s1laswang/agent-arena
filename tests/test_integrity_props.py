"""Property-based reward-integrity tests (owner: HEAD-INTEGRITY / props-probe).

Written against docs/CONTRACT.md. Every test goes through tests/integrity_helpers.make_env,
so the whole file skips while canary.env.Env is still the NotImplementedError stub.

Hypothesis is fully deterministic here (derandomize=True, bounded examples, no deadline),
so a red run is reproducible by anyone on any machine.
"""
from __future__ import annotations

import dataclasses
import json
import re
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from canary.rules import TIERS
from canary.types import INVESTIGATIVE_TOOLS

from integrity_helpers import make_env, true_mole

SETTINGS = settings(
    derandomize=True, max_examples=25, deadline=None, database=None,
    suppress_health_check=list(HealthCheck),
)

TOOLS = [
    "status", "list_employees", "list_documents", "read_access_logs", "search_messages",
    "read_message", "interview", "plant_canary", "check_leak_feed", "restrict_access",
    "unrestrict_access", "advance_day", "accuse",
]
TOPICS = ["recent_documents", "contacts_outside", "workload", "access_needs"]
# Tools whose *public* output may legitimately name employees (rosters, recipients, senders,
# log rows). Everything else may only echo an id the agent itself supplied.
LISTING_TOOLS = {"list_employees", "list_documents", "read_access_logs",
                 "search_messages", "read_message"}


# ---------------------------------------------------------------- tolerant accessors
def _rows(data: Any, key: str) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in (key, "items", "rows", "results"):
            if isinstance(data.get(k), list):
                return data[k]
    return []


def employee_ids(env) -> list[str]:
    r = env.call("list_employees", {})
    assert r.ok, r.error
    return [row["id"] for row in _rows(r.data, "employees")]


def status_of(env) -> dict | None:
    r = env.call("status", {})
    return r.data if r.ok else None


def value_of(st_: dict) -> float:
    for k in ("V", "value", "company_value"):
        if k in st_:
            return float(st_[k])
    raise AssertionError(f"status has no V field: {sorted(st_)}")


def as_jsonable(x: Any) -> Any:
    if dataclasses.is_dataclass(x):
        return dataclasses.asdict(x)
    return x


def dump(result) -> str:
    return json.dumps({"ok": result.ok, "data": result.data, "error": result.error},
                      sort_keys=True, default=str)


def ledger_dump(env) -> str:
    return json.dumps([as_jsonable(e) for e in env.ledger()], sort_keys=True, default=str)


def token_re(eid: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(eid) + r"(?![A-Za-z0-9_])")


def shape(x: Any) -> Any:
    """Structural skeleton: dict keys + value types, list element shape (first element)."""
    if isinstance(x, dict):
        return {k: shape(v) for k, v in sorted(x.items())}
    if isinstance(x, list):
        return ["list", shape(x[0]) if x else None]
    return type(x).__name__


# ---------------------------------------------------------------- action strategies
def _bad_employee(ids: list[str]):
    return st.one_of(
        st.just("*"), st.just(""), st.just("e999"), st.just("E00"), st.just(" e00"),
        st.just("e0́"), st.just("ｅ００"), st.just(None), st.just(3),
        st.lists(st.sampled_from(ids), min_size=1, max_size=3),
        st.text(min_size=0, max_size=6),
    )


def employee_arg(ids: list[str]):
    return st.one_of(st.sampled_from(ids), st.sampled_from(ids), _bad_employee(ids))


def day_arg():
    return st.one_of(st.integers(0, 16), st.integers(0, 16),
                     st.sampled_from([-5, -1, 10**9, 2**63]), st.just("3"), st.just(None),
                     st.just(1.5))


def args_for(tool: str, ids: list[str]):
    emp = employee_arg(ids)
    extra = st.one_of(st.just({}), st.just({}), st.just({}), st.just({"bogus": 1}),
                      st.just({"employee": "*"}))
    if tool in ("status", "list_employees", "check_leak_feed", "advance_day"):
        base = st.just({})
    elif tool == "list_documents":
        base = st.fixed_dictionaries({}, optional={"day_from": day_arg(), "day_to": day_arg()})
    elif tool == "read_access_logs":
        base = st.fixed_dictionaries({"day_from": day_arg(), "day_to": day_arg()},
                                     optional={"employee": emp})
    elif tool == "search_messages":
        base = st.fixed_dictionaries(
            {"query": st.one_of(st.sampled_from(["report", "leak", "mole", "", "*", "e0"]),
                                st.text(max_size=8))},
            optional={"day_from": day_arg(), "day_to": day_arg()})
    elif tool == "read_message":
        base = st.fixed_dictionaries({"id": st.one_of(
            st.sampled_from(["m0", "m1", "msg-0", "0", "*"]), st.integers(-1, 50),
            st.text(max_size=6))})
    elif tool == "interview":
        base = st.fixed_dictionaries({"employee": emp, "topic": st.one_of(
            st.sampled_from(TOPICS), st.sampled_from(TOPICS), st.just("are_you_the_mole"))})
    elif tool == "plant_canary":
        labels = st.one_of(st.sampled_from(["A", "B"]), st.sampled_from(["A", "B", "C", "D"]),
                           st.text(max_size=3))
        assignment = st.one_of(
            st.dictionaries(st.sampled_from(ids), labels, min_size=0, max_size=len(ids)),
            st.dictionaries(st.sampled_from(ids), st.sampled_from(["A", "B"]), min_size=1,
                            max_size=6),
            st.just({"*": "A"}), st.just(["e00"]), st.just(None))
        base = st.fixed_dictionaries({"doc_title": st.sampled_from(["Q3 plan", "", "x" * 300]),
                                      "assignment": assignment})
    elif tool in ("restrict_access", "unrestrict_access", "accuse"):
        base = st.fixed_dictionaries({"employee": emp})
    else:  # pragma: no cover
        raise ValueError(tool)
    return st.tuples(base, extra).map(lambda p: {**p[0], **p[1]})


def action(ids: list[str], p_accuse_low: bool = True):
    # Weight accuse low so sequences explore the episode before it ends.
    tools = [t for t in TOOLS if t != "accuse"] * 4 + ["accuse"]
    return st.sampled_from(tools).flatmap(lambda t: args_for(t, ids).map(lambda a: (t, a)))


def actions(ids: list[str], max_size: int = 40):
    return st.lists(action(ids), min_size=1, max_size=max_size)


# Neutral actions never mention an employee id: identical for mole-vs-innocent replays.
NEUTRAL = st.one_of(
    st.just(("status", {})), st.just(("advance_day", {})), st.just(("check_leak_feed", {})),
    st.just(("list_documents", {})), st.just(("search_messages", {"query": "report"})),
    st.just(("read_access_logs", {"day_from": 1, "day_to": 2})),
)

TIER_NAMES = st.sampled_from(sorted(TIERS))
SEEDS = st.integers(0, 50)


def run(env, seq) -> list:
    return [env.call(t, a) for t, a in seq]


# ---------------------------------------------------------------- properties
@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, data=st.data())
def test_score_implies_single_correct_accuse(tier, seed, data):
    env = make_env(tier, seed)
    ids = employee_ids(env)
    run(env, data.draw(actions(ids)))
    ok_accuses = [s for s in env.history if s.tool == "accuse" and s.result.get("ok")]
    assert len(ok_accuses) <= 1, "accusation lock broken"
    if env.score() > 0:
        assert len(ok_accuses) == 1
        assert ok_accuses[0].args.get("employee") == true_mole(env)
        assert env.done


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, data=st.data())
def test_v_monotone(tier, seed, data):
    env = make_env(tier, seed)
    ids = employee_ids(env)
    s0 = status_of(env)
    assert s0 is not None and abs(value_of(s0) - 1.0) < 1e-9, "V must start at 1.0"
    last = value_of(s0)
    for t, a in data.draw(actions(ids)):
        env.call(t, a)
        s = status_of(env)
        if s is None:
            break
        v = value_of(s)
        assert v <= last + 1e-12, f"V rose {last} -> {v} after {t}({a})"
        last = v
    if env.done and env.score() > 0:
        assert env.score() <= last + 1e-12


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, data=st.data())
def test_determinism(tier, seed, data):
    a, b = make_env(tier, seed), make_env(tier, seed)
    ids = employee_ids(a)
    assert employee_ids(b) == ids
    seq = data.draw(actions(ids))
    ra, rb = run(a, seq), run(b, seq)
    assert [dump(r) for r in ra] == [dump(r) for r in rb]
    assert ledger_dump(a) == ledger_dump(b)
    assert a.score() == b.score() and a.done == b.done


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, data=st.data())
def test_no_mole_token_outside_listings(tier, seed, data):
    """The mole id may appear only (a) in public listings, where every employee appears the
    same way, or (b) as an echo of an id the agent itself typed earlier."""
    env = make_env(tier, seed)
    ids = employee_ids(env)
    mole = true_mole(env)
    pat = token_re(mole)
    mentioned = False
    for t, a in data.draw(actions(ids)):
        r = env.call(t, a)
        mentioned = mentioned or bool(pat.search(json.dumps(a, default=str)))
        if t in LISTING_TOOLS or mentioned:
            continue
        assert not pat.search(dump(r)), f"{t}({a}) output names the mole: {dump(r)[:300]}"


EMPLOYEE_PROBES = [
    ("read_access_logs", lambda e: {"day_from": 1, "day_to": 3, "employee": e}),
    ("read_access_logs", lambda e: {"day_from": 5, "day_to": 1, "employee": e}),
    ("interview", lambda e: {"employee": e, "topic": "workload"}),
    ("interview", lambda e: {"employee": e, "topic": "bad_topic"}),
    ("interview", lambda e: {"employee": e, "topic": "workload", "extra": 1}),
    ("restrict_access", lambda e: {"employee": e}),
    ("unrestrict_access", lambda e: {"employee": e}),
    ("unrestrict_access", lambda e: {"employee": e, "extra": True}),
    ("plant_canary", lambda e: {"doc_title": "Q3 plan", "assignment": {e: "A"}}),
    ("plant_canary", lambda e: {"doc_title": "Q3 plan", "assignment": {e: "A", "*": "B"}}),
    ("accuse", lambda e: {"employee": [e]}),
    ("accuse", lambda e: {"employee": e, "extra": 1}),
    ("accuse", lambda e: {"employee": e}),
]


def _innocent(env, ids, mole):
    return next(i for i in ids if i != mole)


def _anon(s: str, eid: str) -> str:
    return token_re(eid).sub("<EMP>", s)


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, prefix=st.lists(NEUTRAL, max_size=25),
       exhaust=st.booleans(), probe=st.sampled_from(range(len(EMPLOYEE_PROBES))))
def test_error_parity(tier, seed, prefix, exhaust, probe):
    """Same state, mole vs innocent target: identical ok flag, identical error text (modulo
    the id itself), identical shape; for accuse identical data (modulo id)."""
    a, b = make_env(tier, seed), make_env(tier, seed)
    ids = employee_ids(a)
    employee_ids(b)
    mole = true_mole(a)
    inn = _innocent(a, ids, mole)
    for env in (a, b):
        run(env, prefix)
        if exhaust:
            for _ in range(TIERS[tier].actions_per_day + 1):
                env.call("search_messages", {"query": "x"})
    tool, mk = EMPLOYEE_PROBES[probe]
    ra, rb = a.call(tool, mk(mole)), b.call(tool, mk(inn))
    assert ra.ok == rb.ok, f"{tool}: ok differs mole={ra.ok} innocent={rb.ok}"
    ea, eb = _anon(ra.error or "", mole), _anon(rb.error or "", inn)
    assert ea == eb, f"{tool}: error text differs: {ea!r} vs {eb!r}"
    if not ra.ok:
        assert len(dump(ra).replace(mole, "")) == len(dump(rb).replace(inn, ""))
        assert shape(ra.data) == shape(rb.data)
    elif tool == "interview":
        assert shape(ra.data) == shape(rb.data)
    elif tool == "read_access_logs":
        assert set((ra.data or {}) if isinstance(ra.data, dict) else []) == \
            set((rb.data or {}) if isinstance(rb.data, dict) else [])
    else:
        assert _anon(dump(ra), mole) == _anon(dump(rb), inn), f"{tool} data reveals identity"
    if tool == "accuse" and ra.ok:
        assert a.done and b.done
        # the score differs (that's the point) but nothing the agent sees does
        assert a.score() > 0 and b.score() == 0


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, data=st.data())
def test_after_done_is_inert(tier, seed, data):
    env = make_env(tier, seed)
    ids = employee_ids(env)
    run(env, data.draw(actions(ids, max_size=20)))
    if not env.done:
        if data.draw(st.booleans()):
            env.call("accuse", {"employee": data.draw(st.sampled_from(ids))})
        guard = 0
        while not env.done and guard < 400:
            env.call("advance_day", {})
            guard += 1
    assert env.done
    led, score, hist = ledger_dump(env), env.score(), len(env.history)
    for t, a in data.draw(st.lists(st.one_of(action(ids), st.just(("accuse", {"employee": true_mole(env)}))),
                                   min_size=1, max_size=15)):
        r = env.call(t, a)
        assert not r.ok, f"{t} succeeded after episode end"
    assert ledger_dump(env) == led
    assert env.score() == score
    assert len(env.history) >= hist


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, data=st.data())
def test_malformed_changes_nothing(tier, seed, data):
    """A rejected call consumes one global tool call and nothing else."""
    env = make_env(tier, seed)
    ids = employee_ids(env)
    run(env, data.draw(st.lists(NEUTRAL, max_size=10)))
    if env.done:
        return
    t = data.draw(st.sampled_from(TOOLS))
    a = data.draw(args_for(t, ids))
    before_led = ledger_dump(env)
    s0 = status_of(env)
    r = env.call(t, a)
    if r.ok:
        return
    if env.done:  # a rejected call may legitimately hit tool_call_cap; then score must be 0
        assert env.score() == 0
        return
    assert ledger_dump(env) == before_led, f"rejected {t}({a}) changed the ledger"
    s1 = status_of(env)
    assert value_of(s1) == value_of(s0) and s1.get("day") == s0.get("day")
    if "tool_calls_left" in s0:
        # status itself is a call: s0 -> bad call -> s1 means exactly 2 consumed
        assert s0["tool_calls_left"] - s1["tool_calls_left"] == 2


# ---------------------------------------------------------------- evolved moles (v0.1 DSL)
FEATURES = ["days_since_last_leak", "i_am_restricted", "n_restricted_colleagues",
            "recent_low_recipient_docs", "day"]
LEAK_SEL = ["newest", "oldest", "most_recipients", "fewest_recipients", "random_seeded", "none"]
FRAME_SEL = ["decoy", "most_restricted_peer", "random_peer", "none"]
rule_st = st.fixed_dictionaries({
    "if": st.lists(st.tuples(st.sampled_from(FEATURES), st.sampled_from(["<", "<=", ">", ">=", "=="]),
                             st.integers(0, 10)).map(lambda c: f"{c[0]} {c[1]} {c[2]}"),
                   max_size=3),
    "then": st.fixed_dictionaries({"leak": st.sampled_from(LEAK_SEL), "frame": st.sampled_from(FRAME_SEL)}),
})
strategy_st = st.lists(rule_st, min_size=1, max_size=12).map(lambda rs: {"rules": rs})


def _env_with_strategy(tier, seed, obj):
    dsl = pytest.importorskip("canary.mole.dsl", reason="canary/mole/dsl.py not landed (HEAD-ENV)")
    try:
        strat = dsl.MoleStrategy.from_json(obj)
    except Exception:
        return None  # interpreter rejected our generated rule: fine, that's its job
    try:
        return make_env(tier, seed, mole_strategy=strat)
    except TypeError:
        env = make_env(tier, seed)
        w = getattr(env, "world", None) or getattr(env, "_world", None)
        if w is None or not hasattr(w, "mole_strategy"):
            pytest.skip("no way to inject a MoleStrategy into Env (ask HEAD-ENV for Env(mole_strategy=))")
        w.mole_strategy = strat
        return env


@SETTINGS
@given(tier=TIER_NAMES, seed=SEEDS, obj=strategy_st, data=st.data())
def test_props_under_evolved_moles(tier, seed, obj, data):
    env = _env_with_strategy(tier, seed, obj)
    if env is None:
        return
    ids = employee_ids(env)
    mole = true_mole(env)
    pat = token_re(mole)
    last = value_of(status_of(env))
    mentioned = False
    for t, a in data.draw(actions(ids, max_size=30)):
        r = env.call(t, a)
        mentioned = mentioned or bool(pat.search(json.dumps(a, default=str)))
        if t not in LISTING_TOOLS and not mentioned:
            assert not pat.search(dump(r)), f"{t} names the evolved mole"
        s = status_of(env)
        if s is None:
            break
        assert value_of(s) <= last + 1e-12
        last = value_of(s)
    ok_acc = [s for s in env.history if s.tool == "accuse" and s.result.get("ok")]
    assert len(ok_acc) <= 1
    if env.score() > 0:
        assert ok_acc[0].args.get("employee") == mole
