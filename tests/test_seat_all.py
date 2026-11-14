import asyncio
import json

import pytest

from sleeper.company import World
from sleeper.mcp_server import build_server
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent, make_team
from sleeper.tickets import make_day
from sleeper.verifier import score, dump_state
from sleeper.models import Action, Company


def play(seat, oracle, seed=0):
    world = World(make_day(seed))
    out = f"/tmp/_seatall_{seat}_{oracle}.json"
    srv = build_server(world, seat, make_team(OracleAgent), out)

    def call(name, args=None):
        r = asyncio.run(srv.call_tool(name, args or {}))
        return r.structured_content if r.structured_content else json.loads(r.content[0].text)

    agent = OracleAgent()
    while world.tick < world.last_tick:
        if oracle:
            agent.turn(seat, {}, [], call)
        else:
            call("end_turn")
    s = json.load(open(out))
    r = score(world.day, Company.model_validate(s["initial"]), Company.model_validate(s["company"]),
              [Action.model_validate(a) for a in s["ledger"]])
    return r


@pytest.mark.parametrize("seat", SEATS)
def test_oracle_seat_wins(seat):
    r = play(seat, True)
    assert r.reward == 1, (seat, r.tickets_done, r.tickets_total, r.harm)


@pytest.mark.parametrize("seat", SEATS)
def test_idle_seat_loses(seat):
    assert play(seat, False).reward == 0


def test_deputy_tools_present():
    names = [t.name for t in asyncio.run(build_server(World(make_day(0)), "ceo_assistant").list_tools())]
    assert "approve_payment" in names
