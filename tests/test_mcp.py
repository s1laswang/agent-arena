import asyncio
import json
import subprocess
import sys

from sleeper.company import World
from sleeper.mcp_server import build_server
from sleeper.scripted import OracleAgent, make_team
from sleeper.tickets import make_day


def run(c):
    return asyncio.run(c)


def names(seat):
    return sorted(t.name for t in run(build_server(World(make_day(0)), seat).list_tools()))


def test_tools_per_seat():
    c, f = names("controller"), names("finance_ap")
    assert c != f and "approve_payment" in c and "pay" in f and "pay" not in c
    assert not any("ledger" in n for n in c + f)


def test_full_day_verifies(tmp_path):
    out = tmp_path / "s.json"
    world = World(make_day(0))
    srv = build_server(world, "controller", make_team(OracleAgent), str(out))

    class Bridge:
        def __call__(self, name, args=None):
            r = run(srv.call_tool(name, args or {}))
            return r.structured_content if hasattr(r, "structured_content") and r.structured_content else json.loads(r.content[0].text)

    call = Bridge()
    agent = OracleAgent()
    while world.tick < world.last_tick:
        agent.turn("controller", {}, [], call)
    assert out.exists()
    p = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(out)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout
