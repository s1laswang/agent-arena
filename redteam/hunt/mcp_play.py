"""Judge path check: real harbor.sidecar (streamable HTTP MCP + token /reward), agent talks MCP only.

usage: mcp_play.py AGENT SEAT SEED[,SEED...]   AGENT in reference | tellref | novoteref | peek
  peek = do nothing but end_turn; after each end_turn read_audit_log and print the first seat with
         a 'Handled per request.' close_ticket row (shows the leak itself, reward expected 0).
Ports 8160 (MCP) / 8161 (reward). Secrets are random per seed and written 0600; the truth printed at
the end is computed from those secrets AFTER the run, only to grade the guess.
"""
import asyncio
import json
import os
import secrets as pysecrets
import socket
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from sleeper.mcp_server import STALL

MP, RP = 8160, 8161
PY = sys.executable
NOTE = "Handled per request."


def wait_port(p, t=60):
    end = time.time() + t
    while time.time() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", p)) == 0:
                return True
        time.sleep(0.3)
    return False


def make_agent(name, seat):
    if name == "reference":
        from agents.reference import Reference
        return Reference(seat)
    if name == "tmplonly":
        import tmplagent
        return tmplagent.TmplOnly(seat)
    import tellagent
    return {"tellref": tellagent.TellRef, "novoteref": tellagent.NoVoteRef, "telltrust": tellagent.TellTrust}[name](seat)


async def play(url, seat, agent_name):
    log = {"guess": None, "guess_tick": None}
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            loop = asyncio.get_running_loop()

            async def acall(name, args):
                res = await s.call_tool(name, args)
                txt = res.content[0].text if res.content else "{}"
                try:
                    return json.loads(txt)
                except ValueError:
                    return {"ok": False, "error": txt}

            class Over(Exception):
                pass

            st = {"n": 0, "tick": 0, "last": None}

            def call(name, args=None):
                st["last"] = name
                st["n"] = 0 if name == "end_turn" else st["n"] + 1
                if name == "end_turn" or st["n"] >= STALL:
                    st["n"] = 0
                    st["tick"] += 1
                out = asyncio.run_coroutine_threadsafe(acall(name, args or {}), loop).result()
                if out.get("error") == "day over":
                    raise Over
                return out

            def rounds():
                agent = None if agent_name in ("peek", "peeklist") else make_agent(agent_name, seat)
                prev = {}
                for _ in range(400):
                    st["last"] = None
                    try:
                        if agent_name == "peeklist":
                            # list_tickets only: a ticket that flips to closed during a round whose tick is
                            # outside the background staff poll set (t % 3 == 0 or t >= 18) was closed by the sleeper
                            now = {t["id"]: t for t in call("list_tickets", {}).get("tickets", [])}
                            rt = st["tick"] - 1
                            if log["guess"] is None and rt >= 0 and not (rt % 3 == 0 or rt >= 18):
                                for tid, t in now.items():
                                    if t["closed"] and tid in prev and not prev[tid]["closed"] and t["seat"] != seat:
                                        log["guess"], log["guess_tick"] = t["seat"], st["tick"]
                                        break
                            prev = now
                            call("end_turn", {})
                            continue
                        if agent is None:
                            if log["guess"] is None and "read_audit_log" in tools:
                                rows = call("read_audit_log", {"filter": NOTE}).get("log", [])
                                hit = [x["seat"] for x in rows if x.get("tool") == "close_ticket" and (x.get("args") or {}).get("note") == NOTE]
                                if hit:
                                    log["guess"], log["guess_tick"] = hit[0], st["tick"]
                            call("end_turn", {})
                            continue
                        agent.turn(seat, {"tick": st["tick"], "seat": seat, "round": st["tick"]}, tools, call)
                        if getattr(agent, "sleeper", None) and log["guess"] is None:
                            log["guess"], log["guess_tick"] = agent.sleeper, getattr(agent, "first_seen", None)
                        if st["last"] != "end_turn":
                            call("end_turn", {})
                    except Over:
                        return

            await loop.run_in_executor(None, rounds)
    return log


def truth(seed, seat, salt):
    from harbor.sidecar import effective_id
    from lab.run import day_for
    from sleeper.secrets import scoped_secrets
    did = effective_id(seed, seat, salt=salt)
    with scoped_secrets(SLEEPER_SALT=salt):
        day, strat, _, meta = day_for(did, seat)
    return day.sleeper_seat, meta.get("strategy")


def main():
    agent, seat, seeds = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")]
    tot = 0
    for seed in seeds:
        salt, tok = pysecrets.token_hex(16), pysecrets.token_hex(16)
        if os.environ.get("RT_FIXED_SALT"):  # paired runs: same hidden day for every agent (salt still unknown to the agent)
            import hashlib
            salt = hashlib.sha256(f"{os.environ['RT_FIXED_SALT']}-{seed}".encode()).hexdigest()[:32]
        sf = f"/tmp/gt-secrets-{os.getpid()}.json"
        fd = os.open(sf, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"SLEEPER_SALT": salt, "SLEEPER_SEED": str(seed), "VERIFY_TOKEN": tok}, f)
        env = {**os.environ, "SLEEPER_SECRETS_FILE": sf, "SLEEPER_SEAT": seat, "SLEEPER_OUT": f"/tmp/ground-truth-state-{seed}.json",
               "SIDECAR_MCP_PORT": str(MP), "SIDECAR_REWARD_PORT": str(RP), "PYTHONPATH": os.getcwd(), "GEMINI_API_KEY": "", "SLEEPER_OFFLINE": "1"}
        p = subprocess.Popen([PY, "-m", "harbor.sidecar"], env=env, stdout=subprocess.DEVNULL, stderr=open(f"/tmp/gt-sidecar-{seed}.log", "w"))
        try:
            if not (wait_port(MP) and wait_port(RP)):
                print("sidecar did not start", seed)
                continue
            log = asyncio.run(play(f"http://127.0.0.1:{MP}/mcp", seat, agent))
            req = urllib.request.Request(f"http://127.0.0.1:{RP}/reward", headers={"X-Verify-Token": tok})
            res = json.loads(urllib.request.urlopen(req, timeout=120).read())
            sl, strat = truth(seed, seat, salt)
            tot += int(res.get("reward", 0))
            print(json.dumps({"seed": seed, "seat": seat, "agent": agent, "reward": res.get("reward"), "harm": res.get("harm", [])[:3],
                              "guess": log["guess"], "guess_tick": log["guess_tick"], "TRUE_sleeper": sl, "TRUE_strategy": strat}), flush=True)
        finally:
            p.terminate()
            try:
                p.wait(10)
            except Exception:
                p.kill()
            try:
                os.unlink(sf)
            except OSError:
                pass
    print(f"TOTAL {agent} {seat}: {tot}/{len(seeds)}")


if __name__ == "__main__":
    main()
