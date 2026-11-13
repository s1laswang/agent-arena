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
    from sleeper.tickets import make_day

    seed = int(os.environ.get("SLEEPER_SEED", "0"))
    seat = os.environ.get("SLEEPER_SEAT", "controller")
    world = World(make_day(seed))
    if os.environ.get("SLEEPER_TEAM", "oracle") == "oracle":
        from sleeper.scripted import OracleAgent, make_team
        team = make_team(OracleAgent)
    else:
        from agents.staff import make_team
        team = make_team()
    srv = build_server(world, seat, team)
    atexit.register(srv.finish)
    srv.run(transport=os.environ.get("SLEEPER_TRANSPORT", "stdio"))


if __name__ == "__main__":
    main()
