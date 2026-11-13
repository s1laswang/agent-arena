import atexit
import inspect
import json
import os

from mcp.server.mcpserver import MCPServer

from sleeper.company import BUDGET, World, tools_for
from sleeper.day import play_round
from sleeper.verifier import dump_state

TYPES = {"number": float, "array": list, "object": dict, "string": str}


def build_server(world, seat, team=None, out=None):
    out = out or os.environ.get("SLEEPER_OUT", "/tmp/sleeper_state.json")
    mcp = MCPServer("sleeper-" + seat)
    st = {"done": False}

    def finish():
        if not st["done"]:
            st["done"] = True
            with open(out, "w") as f:
                json.dump(dump_state(world), f)

    def make(spec):
        name = spec["name"]
        props = spec["parameters"]["properties"]
        req = spec["parameters"]["required"]

        def fn(**kw):
            if st["done"]:
                return {"ok": False, "error": "day over"}
            res = world.call(seat, name, kw)
            if name == "end_turn" and team is not None:
                play_round(world, team, skip=seat)
            if world.tick >= world.last_tick or world.calls[seat] >= BUDGET:
                finish()
            return res

        fn.__name__ = name
        fn.__signature__ = inspect.Signature([
            inspect.Parameter(k, inspect.Parameter.KEYWORD_ONLY, annotation=TYPES[v["type"]],
                              default=inspect.Parameter.empty if k in req else None)
            for k, v in props.items()])
        fn.__annotations__ = {k: TYPES[v["type"]] for k, v in props.items()}
        return fn

    for spec in tools_for(seat):
        mcp.add_tool(make(spec), name=spec["name"], description=spec["description"])
    mcp.finish = finish
    return mcp


def main():
    import argparse

    from sleeper.tickets import make_day

    e = os.environ.get
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=e("SLEEPER_SEAT", "controller"))
    ap.add_argument("--day", type=int, default=int(e("SLEEPER_SEED", "0")))
    ap.add_argument("--team", default=e("SLEEPER_TEAM", "oracle"))
    ap.add_argument("--transport", default=e("SLEEPER_TRANSPORT", "stdio"))
    ap.add_argument("--out", default=e("SLEEPER_OUT", "/tmp/sleeper_state.json"))
    a = ap.parse_args()
    world = World(make_day(a.day))
    if a.team == "oracle":
        from sleeper.scripted import OracleAgent, make_team
        team = make_team(OracleAgent)
    else:
        from agents.staff import make_team
        team = make_team()
    srv = build_server(world, a.seat, team, a.out)
    atexit.register(srv.finish)
    srv.run(transport=a.transport)


if __name__ == "__main__":
    main()
