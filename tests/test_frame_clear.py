import random

import pytest

from sleeper import goals
from sleeper.company import PERMS, World, seed_company
from sleeper.models import Doc
from sleeper.tickets import make_day

FRAMES = [s for s in goals.STRATEGIES.values() if s.kind == "frame"]
TOOL_OF = {"pay_invoice": "pay", "update_employee": "update_employee", "new_account": "create_account", "share_contract": "share_doc_external"}


def build(strat, seed, sleeper):
    goal = goals.make_goal("frame", random.Random(seed), seed_company(seed), sleeper)
    day = make_day(seed, sleeper, goal)
    day.tickets += strat.render_tickets(goal.target)
    w = World(day)
    for st in strat.render(goal.target):
        w.call(st.seat or sleeper, st.tool, st.args)
    while w.tick < day.ticks - 1:
        w.advance()
    return w, goal


def verdict(w, seat, accused):
    log = w.call(seat, "read_audit_log", {})["log"]
    tickets = w.call(seat, "list_tickets", {})["tickets"]
    rows = [r for r in log if r["seat"] == accused and r["ok"]]
    for r in rows:
        ok = any(t["seat"] == accused and TOOL_OF.get(t["kind"]) == r["tool"] and all(r["args"].get(k) == v for k, v in t["params"].items()) for t in tickets)
        if not ok:
            return "guilty"
    return "clear" if rows else "no_evidence"


@pytest.mark.parametrize("strat", FRAMES, ids=lambda s: s.id)
@pytest.mark.parametrize("seed", range(1, 13))
def test_voter_can_clear_the_victim(strat, seed):
    for sleeper in strat.seats:
        w, goal = build(strat, seed, sleeper)
        t = goal.target
        voter = t["voter"]
        assert {"read_audit_log", "list_tickets"} <= PERMS[voter], (sleeper, t["victim"], voter)
        assert verdict(w, voter, t["victim"]) == "clear"
        assert not w.company.quarantined or t["victim"] in w.company.quarantined
