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

from harbor.sidecar import effective_id
from sleeper.mcp_server import STALL
from sleeper.secrets import scoped_secrets, write_secrets_file

ROOT = Path(__file__).resolve().parent.parent
TOK = "t0k"
SALT = "seat-e2e-salt-1"


def agent(kind, seat, seed, salt=SALT):
    from lab.run import build_team, day_for
    from sleeper.scripted import OracleAgent

    day_id = effective_id(seed, seat, salt=salt)
    with scoped_secrets(SLEEPER_SALT=salt):
        day = day_for(day_id, seat)[0]
        if kind == "oracle":
            return build_team("oracle", day, 0)[seat], 100
        if kind == "staff":
            from agents.staff import make_team
            return make_team(day, seed=0)[seat], 100
        if kind == "stop_early":
            return OracleAgent(), 1
        return OracleAgent(), 100


async def play(url, seat, kind, seed, salt=SALT):
    if kind == "nop":
        return
    ag, n = agent(kind, seat, seed, salt=salt)
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            loop = asyncio.get_running_loop()
            st = {"n": 0, "tick": 0, "last": None}

            def call(name, args=None):
                st["last"] = name
                st["n"] = 0 if name == "end_turn" else st["n"] + 1
                if name == "end_turn" or st["n"] >= STALL:
                    st["n"] = 0
                    st["tick"] += 1
                async def go():
                    res = await s.call_tool(name, args or {})
                    return json.loads(res.content[0].text) if res.content else {}
                out = asyncio.run_coroutine_threadsafe(go(), loop).result()
                if out.get("error") == "day over":
                    raise StopIteration
                return out

            def rounds():
                for _ in range(n):
                    st["last"] = None
                    try:
                        ag.turn(seat, {"tick": st["tick"], "seat": seat, "round": st["tick"]}, tools, call)
                        if st["last"] != "end_turn":
                            call("end_turn", {})
                    except StopIteration:
                        return

            await loop.run_in_executor(None, rounds)


def free():
    with socket.socket() as a:
        a.bind(("127.0.0.1", 0))
        return a.getsockname()[1]


def run(seat, kind, seed=4, team="staff", out="/tmp/seat_e2e.json"):
    mp, rp = free(), free()
    sf = write_secrets_file(
        {"SLEEPER_SEED": str(seed), "SLEEPER_SALT": SALT, "VERIFY_TOKEN": TOK},
        dir="/localscratch" if os.path.isdir("/localscratch") else None,
    )
    base_env = {k: v for k, v in os.environ.items() if k not in ("SLEEPER_SEED", "SLEEPER_SALT", "VERIFY_TOKEN")}
    env = {**base_env, "SLEEPER_SECRETS_FILE": sf, "SLEEPER_SECRETS_UNLINK": "1", "SLEEPER_SEAT": seat, "SLEEPER_OUT": out,
           "SLEEPER_TEAM": team, "PYTHONPATH": str(ROOT), "SIDECAR_MCP_PORT": str(mp), "SIDECAR_REWARD_PORT": str(rp)}
    p = subprocess.Popen([sys.executable, "-m", "harbor.sidecar"], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.time() + 240
        while True:
            assert p.poll() is None, "sidecar exited (port taken?)"
            try:
                socket.create_connection(("127.0.0.1", mp), 1).close()
                break
            except OSError:
                assert time.time() < end, "sidecar not listening"
                time.sleep(0.5)
        asyncio.run(play(f"http://127.0.0.1:{mp}/mcp", seat, kind, seed))
        req = urllib.request.Request(f"http://127.0.0.1:{rp}/reward", headers={"X-Verify-Token": TOK})
        return json.loads(urllib.request.urlopen(req, timeout=400).read())
    finally:
        p.kill()
        p.wait()
        if os.path.exists(sf):
            try:
                os.unlink(sf)
            except OSError:
                pass


if __name__ == "__main__":
    seats = sys.argv[1].split(",") if len(sys.argv) > 1 else ["finance_ap", "controller", "hr"]
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    team = os.environ.get("SLEEPER_TEAM", "staff")
    print(f"| seat | agent | reward | done/total | harm | team={team} seed={seed} |\n|---|---|---|---|---|---|")
    for seat in seats:
        for kind in ("oracle", "nop", "stop_early", "staff"):
            r = run(seat, kind, seed, team)
            print(f"| {seat} | {kind} | {r.get('reward')} | {r.get('tickets_done')}/{r.get('tickets_total')} | {r.get('harm')} | seat={r.get('seat_under_test')} |", flush=True)
