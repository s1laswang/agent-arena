import random

from agents import fake_gemini
from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff
from lab.run import day_for
from sleeper.company import World
from sleeper.models import SEATS


def _setup():
    day, st, _, _ = day_for(2, None)
    w = World(day)
    ag = SleeperAgent(day.sleeper_seat, day.goal, st, random.Random(2), ticks=day.ticks)
    return day, w, ag


def test_guess_blocked_true_ticket_allowed(monkeypatch):
    day, w, ag = _setup()
    seat = day.sleeper_seat
    t = next(t for t in day.tickets if t.seat == seat and t.hidden and t.kind == "update_employee")
    while w.tick < t.tick:
        w.advance()
    guess = dict(employee_id=t.params["employee_id"], field=t.params["field"], value="FI0000000000000000")
    fake_gemini.install(monkeypatch, [[("update_employee", guess)], [("end_turn", {})]])
    ag.turn(seat, {"tick": t.tick}, [], lambda n, a=None: w.call(seat, n, a))
    assert ag.blocked and not any(a.tool == "update_employee" for a in w.ledger if a.seat == seat)
    good = {**guess, "value": t.params["value"]}
    w.call("controller", "post_chat", {"to": [seat], "body": "For ticket %s: value %s" % (t.id, t.params["value"])})
    fake_gemini.install(monkeypatch, [[("read_chat", {})], [("update_employee", good)], [("end_turn", {})]])
    ag.blocked.clear()
    ag.turn(seat, {"tick": t.tick}, [], lambda n, a=None: w.call(seat, n, a))
    assert not ag.blocked and any(a.tool == "update_employee" and a.args.get("value") == t.params["value"] for a in w.ledger)
