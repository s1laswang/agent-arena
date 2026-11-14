import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.procedure import make_procedure_team
from agents.sleeper_agent import SleeperAgent
from lab.run import day_for
from sleeper.company import World, tools_for
from sleeper.mcp_server import build_server


class Abort(Exception):
    pass


def build_day(seat, day_id):
    day, strategy, _, _ = day_for(day_id, seat)
    team = make_procedure_team(day, seed=0)
    if day.sleeper_seat and strategy:
        kw = {"ticks": day.ticks} if "ticks" in SleeperAgent.__init__.__code__.co_varnames else {}
        team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    return World(day), team, strategy


def play(seat, day_id, agent_for, out, max_calls=150, max_usd=2.0, spend=lambda: 0.0, name=None):
    world, team, _ = build_day(seat, day_id)
    Path(out).mkdir(parents=True, exist_ok=True)
    state = Path(out) / f"{name or f'reference-{seat}-s{day_id}-t0'}.state.json"
    srv = build_server(world, seat, team, str(state))
    tools = tools_for(seat)
    st = {"calls": 0, "abort": None}
    mcp = []

    def call(name, args=None):
        if st["calls"] >= max_calls:
            st["abort"] = "max_calls"
            raise Abort
        if spend() >= max_usd:
            st["abort"] = "max_usd"
            raise Abort
        st["calls"] += 1
        try:
            r = asyncio.run(srv.call_tool(name, args or {}))
            res = r.structured_content if getattr(r, "structured_content", None) else json.loads(r.content[0].text)
        except Exception as e:
            res = {"ok": False, "error": "tool error: %s" % (e.__cause__ or e)}
        mcp.append({"tool": name, "args": args or {}, "result": res})
        return res

    agent = agent_for(world.day, seat)
    try:
        while world.tick < world.last_tick and not st["abort"]:
            t = world.tick
            agent.turn(seat, {"tick": t, "seat": seat, "round": t}, tools, call)
            if world.tick == t:
                call("end_turn", {})
    except Abort:
        pass
    srv.finish()
    return state, st, mcp, agent
