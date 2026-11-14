import atexit
import inspect
import json
import os
import signal
import sys
import traceback

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.prompts import Prompt
from mcp.types import CallToolResult, TextContent

from sleeper.company import BUDGET, DEPUTY, World, tools_for
from sleeper.day import play_round
from sleeper.verifier import dump_state, sign

STALL = 8
TYPES = {"number": float, "array": list | str, "object": dict, "string": str | int | float | bool}


def build_server(world, seat, team=None, out=None):
    out = out or os.environ.get("SLEEPER_OUT", "/tmp/sleeper_state.json")
    try:
        from harbor.opencode.instruction import seat_instruction
        text = seat_instruction(seat)
    except Exception:
        text = None
    mcp = MCPServer("sleeper-" + seat, instructions=text)
    st = {"done": False, "n": 0}

    def dump():
        tmp = out + ".tmp"
        with open(tmp, "w") as f:
            json.dump(dump_state(world), f)
        os.replace(tmp, out)

    def finish():
        if not st["done"]:
            st["done"] = True
            with open(out, "w") as f:
                st_ = dump_state(world)
                json.dump(sign(st_, os.environ["VERIFY_TOKEN"]) if os.environ.get("VERIFY_TOKEN") else st_, f)

    def make(spec):
        name = spec["name"]
        props = spec["parameters"]["properties"]
        req = spec["parameters"]["required"]

        def fn(**kw):
            if st["done"]:
                return {"ok": False, "error": "day over"}
            kw = {k: [v] if isinstance(v, str) and props[k]["type"] == "array" else v for k, v in kw.items()}
            try:
                res = world.call(seat, name, kw)
            except Exception as e:
                return {"ok": False, "error": f"{type(e).__name__}: {e}"}
            st["n"] = 0 if name == "end_turn" else st["n"] + 1
            if team is not None and (name == "end_turn" or st["n"] >= STALL):
                st["n"] = 0
                t0 = world.tick
                try:
                    play_round(world, team, skip=seat)
                except Exception:
                    traceback.print_exc(file=sys.stderr)
                    if world.tick == t0:
                        world.advance()
            if world.tick >= world.last_tick or world.calls[seat] >= BUDGET:
                finish()
            if name == "end_turn":
                dump()
            return res

        fn.__name__ = name
        fn.__signature__ = inspect.Signature([
            inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY, annotation=TYPES[v["type"]],
                              default=inspect.Parameter.empty if k in req else None)
            for k, v in props.items()])
        fn.__annotations__ = {k: TYPES[v["type"]] for k, v in props.items()}
        return fn

    specs = {t["name"]: t for t in tools_for(seat)}
    if seat == "ceo_assistant":
        full = {t["name"]: t for t in tools_for("controller")}
        specs.update({n: full[n] for n in DEPUTY if n in full})
    for spec in specs.values():
        mcp.add_tool(make(spec), name=spec["name"], description=spec["description"])
    orig = mcp.call_tool

    async def safe(name, arguments, context=None):
        try:
            return await orig(name, arguments, context)
        except Exception as e:
            err = {"ok": False, "error": str(e) or type(e).__name__}
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(err))], structured_content=err)

    mcp.call_tool = safe
    mcp.finish = finish
    mcp.dump = dump
    return mcp


def main():
    import argparse

    from sleeper.tickets import make_day

    e = os.environ.get
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=e("SLEEPER_SEAT", "finance_ap"))
    ap.add_argument("--day", type=int, default=int(e("SLEEPER_SEED", "0")))
    ap.add_argument("--team", default=e("SLEEPER_TEAM", "procedure"))
    ap.add_argument("--transport", default=e("SLEEPER_TRANSPORT", "stdio"))
    ap.add_argument("--sleeper-seat", default=e("SLEEPER_SLEEPER_SEAT") or None)
    ap.add_argument("--day-source", choices=["auto", "make_day", "day_for"], default=e("SLEEPER_DAY_SOURCE", "auto"))
    ap.add_argument("--goal", default=e("SLEEPER_GOAL") or None)
    ap.add_argument("--out", default=e("SLEEPER_OUT", "/tmp/sleeper_state.json"))
    a = ap.parse_args()
    if a.sleeper_seat == a.seat:
        ap.error("seat under test cannot be the sleeper")
    strategy = None
    if a.sleeper_seat or a.goal:
        day = make_day(a.day, a.sleeper_seat, a.goal)
    else:
        from lab.run import day_for
        day, strategy, _, _ = day_for(a.day, a.seat)
    world = World(day)
    if a.team == "oracle":
        from sleeper.scripted import OracleAgent, make_team
        team = make_team(OracleAgent)
    else:
        from sleeper.scripted import seat_team
        team = seat_team(day, a.seat, a.day, strategy)
    srv = build_server(world, a.seat, team, a.out)
    atexit.register(srv.dump)

    def bye(*_):
        srv.dump()
        os._exit(0)

    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)
    srv.dump()
    try:
        srv.run(transport=a.transport)
    finally:
        srv.dump()


if __name__ == "__main__":
    main()
