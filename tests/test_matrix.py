import asyncio
import json

import pytest

from agents.reference import Oracle
from sleeper.company import World
from sleeper.day import run_day
from sleeper.daymix import day_spec
from sleeper.mcp_server import build_server
from sleeper.models import SEATS, Action, Company
from sleeper.scripted import NoopAgent
from sleeper.tickets import make_day
from sleeper.verifier import dump_state, score

DAYS = range(20)


def make(day_id, seat=None):
    spec = day_spec(day_id, seat)
    return make_day(day_id, spec.get("sleeper_seat"), spec.get("goal"))


def team_of(day):
    o = Oracle(day)
    return o, {s: o for s in SEATS if s != day.sleeper_seat}


def grade(day, w):
    return score(day, w.initial, w.company, w.ledger, agent="oracle")


def msg(r):
    return (r.tickets_done, r.tickets_total, r.harm, r.false_quarantine)


@pytest.mark.parametrize("day_id", DAYS)
def test_oracle_team_wins(day_id):
    day = make(day_id)
    o, team = team_of(day)
    if day.sleeper_seat:
        team[day.sleeper_seat] = NoopAgent()
    r = grade(day, run_day(day, team))
    assert r.reward == 1, (day_id, day.sleeper_seat, msg(r))


@pytest.mark.parametrize("day_id", DAYS)
def test_idle_seat_loses(day_id):
    for s in SEATS:
        day = make(day_id)
        if s == day.sleeper_seat or not any(t.seat == s and t.legit and day.sleeper_seat not in t.needs for t in day.tickets):
            continue
        o, team = team_of(day)
        team[s] = NoopAgent()
        r = grade(day, run_day(day, team))
        assert r.reward == 0, (day_id, s)


def seat_play(day_id, seat, tmp):
    day = make(day_id, seat)
    world = World(day)
    o, team = team_of(day)
    out = str(tmp / f"{day_id}_{seat}.json")
    srv = build_server(world, seat, team, out)

    def call(name, args=None):
        r = asyncio.run(srv.call_tool(name, args or {}))
        res = r.structured_content if r.structured_content else json.loads(r.content[0].text)
        over.append(res.get("error") == "day over")
        return res

    over = []
    while world.tick < world.last_tick and not (over and over[-1]):
        o.turn(seat, {"tick": world.tick}, [], call)
        call("end_turn")
    s = json.load(open(out))
    r = score(day, Company.model_validate(s["initial"]), Company.model_validate(s["company"]), [Action.model_validate(a) for a in s["ledger"]])
    return day, r


@pytest.mark.parametrize("seat", SEATS)
def test_seat_mode_wins(seat, tmp_path):
    bad = []
    for d in DAYS:
        day, r = seat_play(d, seat, tmp_path)
        if r.reward != 1:
            bad.append((d, day.sleeper_seat, msg(r)))
    assert not bad, bad
