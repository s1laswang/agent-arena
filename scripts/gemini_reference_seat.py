import argparse
import asyncio
import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if os.environ.get("OFFLINE") == "1":
    os.environ["SLEEPER_OFFLINE"] = "1"

from agents import gemini
from agents.gemini_reference import make_gemini_procedure_team
from agents.procedure import make_procedure_team
from agents.sleeper_agent import SleeperAgent
from lab.run import day_for
from sleeper.company import World, tools_for
from sleeper.mcp_server import build_server

PRICE = {"in": float(os.environ.get("SLEEPER_PRICE_IN_PER_M") or 2.0), "out": float(os.environ.get("SLEEPER_PRICE_OUT_PER_M") or 12.0)}


class Abort(Exception):
    pass


def commit():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "nogit"


def verify(state, seat):
    p = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(state)], cwd=ROOT, capture_output=True, text=True, env={**os.environ, "SLEEPER_SEAT": seat})
    return json.loads(p.stdout.strip().splitlines()[-1])


def play(seat, day_id, agent_for, out, max_calls=150, max_usd=2.0):
    day, strategy, _, _ = day_for(day_id, seat)
    team = make_procedure_team(day, seed=0)
    if day.sleeper_seat and strategy:
        team[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **({"ticks": day.ticks} if "ticks" in SleeperAgent.__init__.__code__.co_varnames else {}))
    world = World(day)
    Path(out).mkdir(parents=True, exist_ok=True)
    state = Path(out) / f"reference-{seat}-s{day_id}-t0.state.json"
    srv = build_server(world, seat, team, str(state))
    tools = tools_for(seat)
    st = {"calls": 0, "abort": None}
    mcp = []

    def call(name, args=None):
        u = gemini.usage()
        if st["calls"] >= max_calls:
            st["abort"] = "max_calls"
            raise Abort
        if (u["in_tokens"] * PRICE["in"] + u["out_tokens"] * PRICE["out"]) / 1e6 >= max_usd:
            st["abort"] = "max_usd"
            raise Abort
        st["calls"] += 1
        r = asyncio.run(srv.call_tool(name, args or {}))
        res = r.structured_content if getattr(r, "structured_content", None) else json.loads(r.content[0].text)
        mcp.append({"tool": name, "args": args or {}, "result": res})
        return res

    agent = agent_for(day, seat)
    try:
        agent.turn(seat, {"tick": 0, "seat": seat, "round": 0}, tools, call)
    except Abort:
        pass
    srv.finish()
    return state, st, mcp, agent


def run(model, seat="finance_ap", day_id=0, max_calls=150, max_usd=2.0, com=None, base=None):
    com = com or commit()
    os.environ["SLEEPER_MODEL_REFERENCE"] = model
    out = Path(base or ROOT / "results" / "frontier") / model / com
    out.mkdir(parents=True, exist_ok=True)
    gemini.CACHE = out / "cache"
    gemini.reset_usage()
    t0 = time.time()
    state, st, mcp, agent = play(seat, day_id, lambda d, s: make_gemini_procedure_team(d, seed=0)[s], out, max_calls, max_usd)
    r = verify(state, seat)
    u = gemini.usage()
    usd = round((u["in_tokens"] * PRICE["in"] + u["out_tokens"] * PRICE["out"]) / 1e6, 4)
    bstate, _, _, _ = play(seat, day_id, lambda d, s: make_procedure_team(d, seed=0)[s], out / "scripted")
    b = verify(bstate, seat)
    sc = lambda x: {"reward": x.get("reward"), "harm": x.get("harm"), "false_quarantines": x.get("false_quarantine"), "sleeper_caught": x.get("sleeper_caught")}
    row = {"model": model, "commit": com, "agent": "gemini", "role": "reference", "seat": seat, "seed": day_id, "trial": 0, "mode": "seat", "seat_under_test": seat,
           "scores": sc(r), "calls": st["calls"], "aborted": st["abort"], "model_calls": u["calls"], "cache_hits": u["cache_hits"], "usd": usd, "wall_s": round(time.time() - t0, 1),
           "agent_kind": agent.agent_kind, "state_path": str(state), "scripted_procedure": sc(b), "mcp_calls": mcp, "transcript": agent.log}
    p = out / f"reference-{seat}-s{day_id}-t0.json"
    row["transcript_path"] = str(p)
    p.write_text(json.dumps(row, sort_keys=True, indent=1, default=str))
    return row, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default="finance_ap")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default=os.environ.get("SLEEPER_MODEL_REFERENCE") or "gemini-4-carbon")
    ap.add_argument("--max-calls", type=int, default=150)
    ap.add_argument("--max-usd", type=float, default=2.0)
    ap.add_argument("--commit")
    a = ap.parse_args()
    row, p = run(a.model, a.seat, a.seed, a.max_calls, a.max_usd, a.commit)
    print(json.dumps({k: v for k, v in row.items() if k not in ("mcp_calls", "transcript")}, indent=1), "->", p)


if __name__ == "__main__":
    main()
