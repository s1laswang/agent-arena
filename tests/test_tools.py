import inspect
import json
import warnings

import pytest

from sleeper.company import BUDGET, PERMS, World, tools_for
from sleeper.models import SEATS
from sleeper.tickets import make_day

ALL_TOOLS = sorted(set().union(*PERMS.values()))
BAD = [None, "", "x", "V99", "E99", "K99", "P999", -1, -1e18, 1e300, 0, 10**30, [], {}, [1], {"a": 1}, True, "external:a@b.c", float("inf")]


def world(seed=1):
    return World(make_day(seed))


def params(tool):
    return [p for p in list(inspect.signature(getattr(World, f"t_{tool}")).parameters.values())[2:]]


def state(w):
    return w.company.model_dump(mode="json")


def jsonable(x):
    json.dumps(x)


@pytest.mark.parametrize("seat", SEATS)
def test_permission_matrix(seat):
    for tool in ALL_TOOLS:
        w = world()
        before = state(w)
        out = w.call(seat, tool, {})
        assert isinstance(out, dict) and "ok" in out
        if tool not in PERMS[seat]:
            assert out["ok"] is False
            assert state(w) == before
            assert w.calls[seat] == 0


def test_tools_for_matches_perms():
    for seat in SEATS:
        assert [t["name"] for t in tools_for(seat)] == sorted(PERMS[seat])


GOOD = {"vendor_id": "V01", "amount": 5, "reference": "r", "id": "D-K01", "to": "all", "body": "b", "target": "sales",
        "employee_id": "E05", "field": "iban", "value": 1, "contract_id": "K01", "terms": {"a": 1}, "doc_id": "D-K01",
        "account_id": "acc_hr", "role": "sales", "owner": "o", "name": "n", "iban": "FI1", "customer": "c", "suspect": "hr"}
RAISES = {"post_chat", "search_docs", "send_email", "share_doc_external"}
UNTYPED = {"update_employee", "update_vendor_bank", "grant_role", "update_crm"}


def fuzz(tool, strict):
    seat = next(s for s in SEATS if tool in PERMS[s])
    ps = params(tool)
    for p in ps:
        for bad in BAD:
            w = world()
            args = {q.name: GOOD.get(q.name, "x") for q in ps}
            args[p.name] = bad
            out = w.call(seat, tool, args)
            assert isinstance(out, dict) and "ok" in out
            jsonable(out)
            with warnings.catch_warnings():
                warnings.simplefilter("error")
                jsonable(state(w))
    w = world()
    jsonable(w.call(seat, tool, {"bogus": 1}))
    jsonable(w.call(seat, tool, None))


def mark(tool):
    return tool


@pytest.mark.parametrize("tool", [mark(t) for t in ALL_TOOLS])
def test_fuzz_never_raises(tool):
    fuzz(tool, True)


def outputs(w):
    for seat in SEATS:
        for tool in sorted(PERMS[seat]):
            ps = params(tool)
            for val in ("D-merger", "V01", "", "CANARY", "Confidential", "all"):
                yield seat, tool, w.call(seat, tool, {p.name: val for p in ps if p.default is inspect.Parameter.empty})


def test_no_canary_or_hint_words():
    w = world()
    canaries = [d.canary for d in w.company.docs.values() if d.canary]
    assert canaries
    for seat, tool, out in outputs(w):
        if tool in {"share_doc_external", "read_doc"}:
            continue
        s = json.dumps(out).lower()
        for c in canaries:
            assert c.lower() not in s, (seat, tool)
        for word in ("sleeper", "goal", "legit"):
            assert word not in s, (seat, tool, word)


def test_read_doc_hint_words():
    w = world()
    for doc in w.company.docs:
        s = json.dumps(w.call("legal", "read_doc", {"id": doc})).lower()
        assert '"canary"' not in s and '"secret"' not in s
        for word in ("sleeper", "goal", "legit"):
            assert word not in s


def test_budget_and_quarantine():
    w = world()
    for _ in range(BUDGET):
        assert w.call("hr", "read_chat")["ok"]
    assert w.call("hr", "read_chat")["ok"] is False
    assert w.call("sales", "read_chat")["ok"]
    w = world()
    w.company.quarantined.append("hr")
    before = state(w)
    assert w.call("hr", "update_employee", {"employee_id": "E05", "field": "iban", "value": 1})["ok"] is False
    assert state(w) == before


def test_quarantine_needs_two_seats():
    w = world()
    assert w.call("hr", "quarantine", {"target": "sales"})["ok"]
    assert "sales" not in w.company.quarantined
    w.call("legal", "quarantine", {"target": "sales"})
    assert "sales" in w.company.quarantined
    assert w.call("sales", "pay", {"vendor_id": "V01", "amount": 5, "reference": "r"})["ok"] is False


def test_ledger_only_via_filtered_audit_log():
    w = world()
    w.call("finance_ap", "pay", {"vendor_id": "V01", "amount": 100, "reference": "R"})
    w.call("hr", "read_chat")
    w.call("hr", "post_chat", {"to": "all", "body": "hi"})
    for seat in SEATS:
        out = w.call(seat, "read_audit_log", {})
        if seat in {"it_admin", "controller"}:
            assert out["ok"]
            assert all("effect" not in r for r in out["log"])
            assert all(r["tool"] in {"pay"} for r in out["log"])
        else:
            assert out["ok"] is False and "log" not in out
    for seat, tool, out in outputs(w):
        if tool != "read_audit_log":
            assert '"seq"' not in json.dumps(out), (seat, tool)
