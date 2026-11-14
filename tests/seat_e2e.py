import asyncio
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
TOK = "t0k"


def agent(kind, seat, seed):
    from sleeper.scripted import OracleAgent
    if kind == "staff":
        from agents.staff import make_team
        from lab.run import day_for
        return make_team(day_for(seed, seat)[0], seed=0)[seat], 100
    return OracleAgent(), 1 if kind == "stop_early" else 100


async def play(url, seat, kind, seed):
    if kind == "nop":
        return
    ag, n = agent(kind, seat, seed)
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            loop = asyncio.get_running_loop()

            def call(name, args):
                async def go():
                    res = await s.call_tool(name, args)
                    return json.loads(res.content[0].text) if res.content else {}
                out = asyncio.run_coroutine_threadsafe(go(), loop).result()
                if out.get("error") == "day over":
                    raise StopIteration
                return out

            def rounds():
                for _ in range(n):
                    try:
                        ag.turn(seat, {}, tools, call)
                    except StopIteration:
                        return

            await loop.run_in_executor(None, rounds)


def free():
    with socket.socket() as a:
        a.bind(("127.0.0.1", 0))
        return a.getsockname()[1]


def run(seat, kind, seed=4, team="staff", out="/tmp/seat_e2e.json"):
    mp, rp = free(), free()
    env = {**os.environ, "SLEEPER_SEED": str(seed), "SLEEPER_SEAT": seat, "SLEEPER_OUT": out, "VERIFY_TOKEN": TOK,
           "SLEEPER_TEAM": team, "PYTHONPATH": str(ROOT), "SIDECAR_MCP_PORT": str(mp), "SIDECAR_REWARD_PORT": str(rp)}
    p = subprocess.Popen([sys.executable, "-m", "harbor.sidecar"], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            try:
                socket.create_connection(("127.0.0.1", mp), 1).close()
                break
            except OSError:
                time.sleep(0.5)
        asyncio.run(play(f"http://127.0.0.1:{mp}/mcp", seat, kind, seed))
        req = urllib.request.Request(f"http://127.0.0.1:{rp}/reward", headers={"X-Verify-Token": TOK})
        return json.loads(urllib.request.urlopen(req, timeout=120).read())
    finally:
        p.kill()


if __name__ == "__main__":
    seats = sys.argv[1].split(",") if len(sys.argv) > 1 else ["finance_ap", "controller", "hr"]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    team = os.environ.get("SLEEPER_TEAM", "staff")
    print(f"| seat | agent | reward | done/total | harm | team={team} seed={seed} |\n|---|---|---|---|---|---|")
    for seat in seats:
        for kind in ("oracle", "nop", "stop_early", "staff"):
            r = run(seat, kind, seed, team)
            print(f"| {seat} | {kind} | {r.get('reward')} | {r.get('tickets_done')}/{r.get('tickets_total')} | {r.get('harm')} | seat={r.get('seat_under_test')} |", flush=True)
