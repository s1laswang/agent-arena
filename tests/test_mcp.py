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
    import os
    out = tmp_path / "s.json"
    world = World(make_day(0))
    srv = build_server(world, "controller", make_team(OracleAgent), str(out), token="mcp-key")

    class Bridge:
        def __call__(self, name, args=None):
            r = run(srv.call_tool(name, args or {}))
            return r.structured_content if hasattr(r, "structured_content") and r.structured_content else json.loads(r.content[0].text)

    call = Bridge()
    agent = OracleAgent()
    while world.tick < world.last_tick:
        agent.turn("controller", {}, [], call)
    assert out.exists()
    p = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(out)], capture_output=True, text=True, env={**os.environ, "VERIFY_TOKEN": "mcp-key"})
    assert p.returncode == 0, p.stdout


def test_stall_advances():
    world = World(make_day(0))
    srv = build_server(world, "controller", make_team(OracleAgent), "/tmp/_stall.json")
    for _ in range(8):
        run(srv.call_tool("read_chat", {}))
    assert world.tick == 1


def test_http_smoke():
    import socket
    import threading
    import time

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    world = World(make_day(0))
    srv = build_server(world, "controller", make_team(OracleAgent), "/tmp/_http.json")
    threading.Thread(target=lambda: srv.run(transport="streamable-http", host="127.0.0.1", port=port), daemon=True).start()
    time.sleep(1.5)

    async def go():
        async with streamable_http_client(f"http://127.0.0.1:{port}/mcp") as (r, w, *_):
            async with ClientSession(r, w) as c:
                await c.initialize()
                assert "end_turn" in [t.name for t in (await c.list_tools()).tools]
                await c.call_tool("end_turn", {})
                await c.call_tool("end_turn", {})

    run(go())
    assert world.tick == 2


def test_ceo_has_deputy_tools():
    assert "approve_payment" in names("ceo_assistant")


def test_string_for_list_arg():
    world = World(make_day(0))
    srv = build_server(world, "controller", None, "/tmp/_s.json")
    run(srv.call_tool("post_chat", {"to": "finance_ap", "body": "hi"}))
    assert world.ledger[-1].args["to"] == ["finance_ap"] and world.ledger[-1].ok
