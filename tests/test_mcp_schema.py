import asyncio
import json

import pytest

from sleeper.company import World
from sleeper.day import play_round
from sleeper.mcp_server import build_server
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent
from sleeper.tickets import make_day
from sleeper.verifier import score


class Team(dict):
    pass


def through_mcp(day):
    world = World(day)
    servers = {s: build_server(world, s) for s in SEATS}
    errors = []

    class Agent(OracleAgent):
        def turn(self, seat, view, tools, call):
            def bridge(name, args=None):
                try:
                    r = asyncio.run(servers[seat].call_tool(name, args or {}))
                except Exception as e:
                    errors.append((seat, name, args, repr(e)[:200]))
                    return {"ok": False, "error": repr(e)}
                return r.structured_content if getattr(r, "structured_content", None) else json.loads(r.content[0].text)
            super().turn(seat, view, tools, bridge)

    team = {s: Agent() for s in SEATS}
    while world.tick < day.ticks:
        play_round(world, team)
    return world, errors


@pytest.mark.parametrize("seed", range(20))
def test_every_ticket_param_passes_schema(seed):
    day = make_day(seed)
    world, errors = through_mcp(day)
    assert not errors, errors[:5]
    assert score(day, world.initial, world.company, world.ledger).reward == 1
