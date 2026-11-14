import atexit
import inspect
import json
import os

from mcp.server.mcpserver import MCPServer

from sleeper.company import BUDGET, DEPUTY, STALL, World, tools_for
from sleeper.day import play_round
from sleeper.verifier import dump_state, sign

TYPES = {"number": float, "array": list | str, "object": dict, "string": str | int | float | bool}


def build_server(world, seat, team=None, out=None, token=None):
    out = out or os.environ.get("SLEEPER_OUT", "/tmp/sleeper_state.json")
    token = token if token is not None else os.environ.get("VERIFY_TOKEN")
    mcp = MCPServer("sleeper-" + seat)
    st = {"done": False, "n": 0}

    def finish():
        if not st["done"]:
            st["done"] = True
            with open(out, "w") as f:
                st_ = dump_state(world)
                json.dump(sign(st_, token) if token else st_, f)

    def make(spec):
        name = spec["name"]
        props = spec["parameters"]["properties"]
        req = spec["parameters"]["required"]

        def fn(**kw):
            if st["done"]:
                return {"ok": False, "error": "day over"}
            # omitted optional args arrive as None: drop them so the World method's own default applies
            kw = {k: [v] if isinstance(v, str) and props[k]["type"] == "array" else v for k, v in kw.items() if v is not None}
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

    from sleeper.secrets import take
    # Seed, salt and the signing token must not stay in this process's environment
    # (/proc/<pid>/environ). Read them once; the day id still uses the salt the way harbor.sidecar does.
    sec = take("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED")
    e = os.environ.get
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default=e("SLEEPER_SEAT", "finance_ap"))
    ap.add_argument("--day", type=int, default=int(sec.get("SLEEPER_SEED") or "0"))
    ap.add_argument("--team", default=e("SLEEPER_TEAM", "procedure"))
    ap.add_argument("--transport", default=e("SLEEPER_TRANSPORT", "stdio"))
    ap.add_argument("--sleeper-seat", default=e("SLEEPER_SLEEPER_SEAT") or None)
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
        from harbor.sidecar import effective_id
        day, strategy, _, _ = day_for(effective_id(a.day, salt=sec["SLEEPER_SALT"]), a.seat)
    world = World(day)
    if a.team == "oracle":
        from sleeper.scripted import OracleAgent, make_team
        team = make_team(OracleAgent)
    else:
        from sleeper.scripted import seat_team
        team = seat_team(day, a.seat, a.day, strategy)
    srv = build_server(world, a.seat, team, a.out, token=sec["VERIFY_TOKEN"])
    atexit.register(srv.finish)
    srv.run(transport=a.transport)


if __name__ == "__main__":
    main()
