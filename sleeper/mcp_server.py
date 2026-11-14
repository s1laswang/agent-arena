import atexit
import inspect
import json
import os
import sys

from sleeper import secrets as secrets_mod
from sleeper.company import BUDGET, DEPUTY, STALL, World, tools_for
from sleeper.day import play_round
from sleeper.verifier import dump_state, sign

TYPES = {"number": float, "array": list | str, "object": dict, "string": str | int | float | bool}


def _get_secret(name):
    fn = getattr(secrets_mod, "get_secret", None)
    if fn is None:
        return None
    try:
        return fn(name, None)
    except TypeError:
        return fn(name)


def build_server(world, seat, team=None, out=None, token=None):
    from mcp.server.mcpserver import MCPServer

    out = out or os.environ.get("SLEEPER_OUT", "/tmp/sleeper_state.json")
    if token is None:
        token = os.environ.get("VERIFY_TOKEN") or _get_secret("VERIFY_TOKEN") or None
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


def main(argv=None):
    import argparse

    from sleeper.secrets import take

    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--secrets-file", default=None)
    pa, _ = pre.parse_known_args(argv)
    if "secrets_file" in inspect.signature(take).parameters:
        sec = take("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED", secrets_file=pa.secrets_file)
    else:
        sf = pa.secrets_file or os.environ.get("SLEEPER_SECRETS_FILE")
        sec = take("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED")
        if sf and os.path.exists(sf):
            with open(sf) as f:
                data = json.load(f)
            for k in ("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED"):
                if not sec.get(k) and data.get(k) is not None:
                    sec[k] = str(data[k])
            if os.environ.pop("SLEEPER_SECRETS_UNLINK", "") == "1":
                try:
                    os.unlink(sf)
                except OSError:
                    pass
    e = os.environ.get
    ap = argparse.ArgumentParser()
    ap.add_argument("--secrets-file", default=None)
    ap.add_argument("--seat", default=e("SLEEPER_SEAT", "finance_ap"))
    ap.add_argument("--day", type=int, default=int((sec.get("SLEEPER_SEED") or "").strip() or "0"))
    ap.add_argument("--team", default=e("SLEEPER_TEAM", "procedure"))
    ap.add_argument("--transport", default=e("SLEEPER_TRANSPORT", "stdio"))
    ap.add_argument("--sleeper-seat", default=e("SLEEPER_SLEEPER_SEAT") or None)
    ap.add_argument("--goal", default=e("SLEEPER_GOAL") or None)
    ap.add_argument("--out", default=e("SLEEPER_OUT", "/tmp/sleeper_state.json"))
    a = ap.parse_args(argv)
    salt = (sec.get("SLEEPER_SALT") or "").strip()
    if not salt:
        sys.exit("SLEEPER_SALT is required")
    if hasattr(secrets_mod, "set_secret"):
        try:
            secrets_mod.set_secret(SLEEPER_SALT=salt)
        except TypeError:
            secrets_mod.set_secret("SLEEPER_SALT", salt)
    if a.sleeper_seat == a.seat:
        ap.error("seat under test cannot be the sleeper")
    from harbor.sidecar import effective_id

    day_id = effective_id(a.day, a.seat, salt=salt)
    strategy = None
    if a.sleeper_seat or a.goal:
        from sleeper.tickets import make_day

        day = make_day(day_id, a.sleeper_seat, a.goal)
    else:
        from lab.run import day_for

        day, strategy, _, _ = day_for(day_id, a.seat)
    world = World(day)
    if a.team == "oracle":
        from sleeper.scripted import OracleAgent, make_team

        team = make_team(OracleAgent)
    elif a.team in ("procedure", "seat"):
        from sleeper.scripted import seat_team

        team = seat_team(day, a.seat, day_id, strategy)
    else:
        import random

        from lab.run import build_team

        team = build_team(a.team, day, 0)
        if day.sleeper_seat and strategy:
            from agents.sleeper_agent import SleeperAgent

            kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
            team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
    srv = build_server(world, a.seat, team, a.out, token=sec.get("VERIFY_TOKEN"))
    atexit.register(srv.finish)
    srv.run(transport=a.transport)


if __name__ == "__main__":
    main()
