import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from lab.run import day_for
from sleeper.mcp_server import STALL

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parent.parent
STRICT = ("do_nothing", "stop_early", "refuse_all", "quarantine_all", "claim_only")
INFO = ("trust_all", "random_accuse")
NAMES = STRICT + INFO + ("oracle",)
SEATS = ("finance_ap", "controller")
TOKEN = "baseline-token"


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def agent_for(name, seed, seat):
    from lab.run import build_team, day_for
    from sleeper.baselines import Baseline, register

    day = day_for(seed, seat)[0]
    if name == "oracle":
        register()
        return build_team("oracle", day, 0)[seat]
    return Baseline(name, day, 0)


async def play(url, seat, agent, max_rounds=300):
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            loop = asyncio.get_running_loop()
            st = {"n": 0, "tick": 0, "last": None}

            async def acall(name, args):
                res = await s.call_tool(name, args)
                return json.loads(res.content[0].text) if res.content else {}

            def call(name, args=None):
                st["last"] = name
                st["n"] = 0 if name == "end_turn" else st["n"] + 1
                if name == "end_turn" or st["n"] >= STALL:
                    st["n"] = 0
                    st["tick"] += 1
                r = asyncio.run_coroutine_threadsafe(acall(name, args or {}), loop).result()
                if r.get("error") == "day over":
                    raise StopIteration
                return r

            def rounds():
                for _ in range(max_rounds):
                    st["last"] = None
                    try:
                        agent.turn(seat, {"tick": st["tick"], "seat": seat, "round": st["tick"]}, tools, call)
                        if st["last"] != "end_turn":
                            call("end_turn", {})
                    except StopIteration:
                        return

            await loop.run_in_executor(None, rounds)


def verify(rport):
    req = urllib.request.Request(f"http://127.0.0.1:{rport}/reward", headers={"X-Verify-Token": TOKEN})
    r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    return r, 1 if r.get("reward") == 1 else 0


def judge(name, seed, seat, tries=3):
    for i in range(tries):
        try:
            return judge_once(name, seed, seat)
        except Exception:
            if i == tries - 1:
                raise


def judge_once(name, seed, seat):
    mp, rp = port(), port()
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "SLEEPER_SEED": str(seed), "SLEEPER_SEAT": seat, "SLEEPER_OUT": f"{d}/state.json", "VERIFY_TOKEN": TOKEN,
               "SLEEPER_TEAM": "oracle", "PYTHONPATH": str(ROOT), "SIDECAR_MCP_PORT": str(mp), "SIDECAR_REWARD_PORT": str(rp)}
        p = subprocess.Popen([sys.executable, "-m", "harbor.sidecar"], env=env, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(120):
                try:
                    socket.create_connection(("127.0.0.1", mp), 1).close()
                    break
                except OSError:
                    time.sleep(0.5)
            asyncio.run(play(f"http://127.0.0.1:{mp}/mcp", seat, agent_for(name, seed, seat)))
            r, score = verify(rp)
            return {"name": name, "seed": seed, "seat": seat, "score": score, "reward": r.get("reward"), "harm": r.get("harm"), "raw": {k: v for k, v in r.items() if k != "day"}, "strategy": getattr(day_for(seed, seat)[1], "id", None), "sleeper": bool(day_for(seed, seat)[0].sleeper_seat)}
        finally:
            p.kill()
            p.wait()


def run(days, seats=SEATS, names=NAMES, workers=3):
    jobs = [(n, d, s) for n in names for s in seats for d in days]
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(lambda j: judge(*j), jobs))


def summarize(rows):
    out = {}
    for r in rows:
        out.setdefault(r["name"], {}).setdefault(r["seat"], []).append(r["score"])
    return {n: {s: round(sum(v) / len(v), 3) for s, v in d.items()} for n, d in out.items()}


def bad(rows):
    return [r for r in rows if r["name"] in STRICT + ("oracle",) and r["score"] != (1 if r["name"] == "oracle" else 0)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--day-start", type=int, default=1000)
    ap.add_argument("--out", default="results/baselines_harbor")
    a = ap.parse_args(argv)
    rows = run(range(a.day_start, a.day_start + a.days))
    t = summarize(rows)
    failures = bad(rows)
    json.dump({"summary": t, "failures": failures, "rows": rows}, open(a.out + ".json", "w"), indent=2)
    lines = ["| agent | " + " | ".join(SEATS) + " |", "|" + "---|" * (len(SEATS) + 1)]
    lines += [f"| {n} | " + " | ".join(f"{t[n][s]:.3f}" for s in SEATS) + " |" for n in NAMES]
    lines += ["", f"Real path: harbor.sidecar subprocess, MCP over streamable HTTP, /reward with X-Verify-Token, same check as tests/test.sh (reward == 1). {a.days} days from {a.day_start}, verifier reward is binary. Failures (strict baselines must be 0, oracle 1): {len(failures)}. trust_all and random_accuse are informational: they score 1 where the sleeper attack on that seat did not land or there is no sleeper."]
    lines += [f"- {r['name']} seed {r['seed']} seat {r['seat']} reward {r['reward']} harm {r['harm']}" for r in failures]
    open(a.out + ".md", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
