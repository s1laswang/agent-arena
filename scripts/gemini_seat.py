import argparse
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if os.environ.get("OFFLINE") == "1":
    os.environ["SLEEPER_OFFLINE"] = "1"

from agents import gemini
from harbor.opencode.instruction import seat_instruction
from sleeper.company import World
from sleeper.mcp_server import build_server
from sleeper.scripted import OracleAgent, make_team
from sleeper.tickets import make_day
from sleeper.verifier import score

PRICE = {"in": float(os.environ.get("SLEEPER_PRICE_IN_PER_M") or 2.0), "out": float(os.environ.get("SLEEPER_PRICE_OUT_PER_M") or 12.0)}


class Abort(Exception):
    pass


def commit():
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "nogit"


def usage_total(cache):
    i = o = 0
    p = cache / "usage.jsonl"
    for line in p.read_text().splitlines() if p.is_file() else []:
        d = json.loads(line)
        i, o = i + d["in"], o + d["out"]
    return {"in_tokens": i, "out_tokens": o, "usd": round((i * PRICE["in"] + o * PRICE["out"]) / 1e6, 4)}


def run_seat(agent="gemini", model=None, seat="finance_ap", seed=0, days=1, max_calls=60, max_usd=2.0, trial=0, mode="seat", com=None, base=None):
    import time

    assert days == 1 and mode == "seat", "ponytail: 1 day, seat mode only"
    model = model or os.environ.get("SLEEPER_MODEL_STAFF") or "gemini-4-carbon"
    com = com or commit()
    out_dir = Path(base or ROOT / "results" / "frontier") / model / com
    gemini.CACHE = out_dir / "cache"
    gemini.reset_usage()
    world = World(make_day(seed))
    srv = build_server(world, seat, make_team(OracleAgent), str(out_dir / f"{seat}-s{seed}-t{trial}.state.json"))
    tools = [{"name": t.name, "description": t.description or "", "parameters": t.input_schema} for t in asyncio.run(srv.list_tools())]
    st = {"calls": 0, "abort": None}
    mcp = []

    def call(name, args):
        if st["calls"] >= max_calls:
            st["abort"] = "max_calls"
            raise Abort
        if usage_total(gemini.CACHE)["usd"] >= max_usd:
            st["abort"] = "max_usd"
            raise Abort
        st["calls"] += 1
        r = asyncio.run(srv.call_tool(name, args or {}))
        res = r.structured_content if getattr(r, "structured_content", None) else json.loads(r.content[0].text)
        mcp.append({"tool": name, "args": args, "result": res})
        return res

    log = []
    t0 = time.time()
    try:
        gemini.run_tool_loop(model, seat_instruction(seat), "Begin your working day.", tools, call, max_steps=max_calls + 5, role="staff", seed=seed + 1000 * trial, log=log.append)
    except Abort:
        pass
    wall = round(time.time() - t0, 1)
    srv.finish()
    r = score(world.day, world.initial, world.company, world.ledger, agent=agent, seat_under_test=seat, model=model)
    out = {"model": model, "commit": com, "agent": agent, "seat": seat, "seed": seed, "trial": trial, "mode": mode,
           "scores": {"reward": r.reward, "harm": r.harm, "false_quarantines": r.false_quarantine, "sleeper_caught": r.sleeper_caught,
                      "tickets_done": r.tickets_done, "tickets_total": r.tickets_total},
           "calls": st["calls"], "aborted": st["abort"], **usage_total(gemini.CACHE), "wall_s": wall, "mcp_calls": mcp, "transcript": log}
    p = out_dir / f"{seat}-s{seed}-t{trial}.json"
    p.write_text(json.dumps(out, sort_keys=True, indent=1, default=str))
    return out, p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seat", default="finance_ap")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--model", default=os.environ.get("SLEEPER_MODEL_STAFF") or "gemini-4-carbon")
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--max-usd", type=float, default=2.0)
    ap.add_argument("--trial", type=int, default=0)
    ap.add_argument("--commit")
    a = ap.parse_args()
    row, p = run_seat("gemini", a.model, a.seat, a.seed, 1, a.max_calls, a.max_usd, a.trial, com=a.commit)
    sc = row["scores"]
    print("reward=%s harm=%s tickets=%s/%s calls=%s cost=$%s model=%s commit=%s%s -> %s" % (
        sc["reward"], sc["harm"], sc["tickets_done"], sc["tickets_total"], row["calls"], row["usd"], row["model"], row["commit"],
        " ABORTED:" + row["aborted"] if row["aborted"] else "", p))


if __name__ == "__main__":
    main()
