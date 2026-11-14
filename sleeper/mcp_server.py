import atexit
import inspect
import json
import os

from mcp.server.mcpserver import MCPServer

from sleeper.company import BUDGET, DEPUTY, World, tools_for
from sleeper.day import play_round
from sleeper.verifier import dump_state

STALL = 8
TYPES = {"number": float, "array": list | str, "object": dict, "string": str | int | float | bool}


def build_server(world, seat, team=None, out=None):
    out = out or os.environ.get("SLEEPER_OUT", "/tmp/sleeper_state.json")
    mcp = MCPServer("sleeper-" + seat)
    st = {"done": False, "n": 0}

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
            kw = {k: [v] if isinstance(v, str) and props[k]["type"] == "array" else v for k, v in kw.items()}
            res = world.call(seat, name, kw)
            st["n"] = 0 if name == "end_turn" else st["n"] + 1
            if team is not None and (name == "end_turn" or st["n"] >= STALL):
                st["n"] = 0
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

    specs = {t["name"]: t for t in tools_for(seat)}
    if seat == "ceo_assistant":
        full = {t["name"]: t for t in tools_for("controller")}
        specs.update({n: full[n] for n in DEPUTY if n in full})
    for spec in specs.values():
        mcp.add_tool(make(spec), name=spec["name"], description=spec["description"])
    mcp.finish = finish
    return mcp


def main():
    import argparse

    from sleeper.tickets import make_day

    e = os.environ.get
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=e("SLEEPER_SEAT", "finance_ap"))
    ap.add_argument("--day", type=int, default=int(e("SLEEPER_SEED", "0")))
    ap.add_argument("--team", default=e("SLEEPER_TEAM", "oracle"))
    ap.add_argument("--transport", default=e("SLEEPER_TRANSPORT", "stdio"))
    ap.add_argument("--sleeper-seat", default=e("SLEEPER_SLEEPER_SEAT") or None)
    ap.add_argument("--goal", default=e("SLEEPER_GOAL") or None)
    ap.add_argument("--out", default=e("SLEEPER_OUT", "/tmp/sleeper_state.json"))
    a = ap.parse_args()
    if a.sleeper_seat == a.seat:
        ap.error("seat under test cannot be the sleeper")
    world = World(make_day(a.day, a.sleeper_seat, a.goal))
    team = None
    if a.team == "staff":
        try:
            from agents.staff import make_team
            team = make_team(world.day, a.day)
        except Exception:
            team = None
    if team is None:
        from sleeper.scripted import OracleAgent, make_team
        team = make_team(OracleAgent)
    srv = build_server(world, a.seat, team, a.out)
    atexit.register(srv.finish)
    srv.run(transport=a.transport)


if __name__ == "__main__":
    main()
