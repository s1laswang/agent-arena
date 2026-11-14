import asyncio, json, sys, urllib.request

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

URL, TOKEN, STATE = sys.argv[1], sys.argv[2], sys.argv[3]
REWARD = URL.rsplit(":", 1)[0] + ":8001/reward"


def get_reward():
    return json.loads(urllib.request.urlopen(urllib.request.Request(REWARD, headers={"X-Verify-Token": TOKEN}), timeout=60).read())


async def call(s, name, args=None):
    try:
        r = await s.call_tool(name, args or {})
        return "".join(getattr(c, "text", "") for c in r.content)
    except Exception as e:
        return repr(e)


async def main():
    async with streamable_http_client(URL) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tasks = [asyncio.create_task(call(s, "post_chat", {"to": ["all"], "body": f"race {i}"})) for i in range(40)]
            rew = await asyncio.get_running_loop().run_in_executor(None, get_reward)
            res = await asyncio.gather(*tasks)
            print("racing calls: ok", sum('"ok": true' in o for o in res), "day over", sum("day over" in o for o in res))
            print("reward", rew["reward"], "steps", rew["steps"])
            st = json.load(open(STATE))
            print("state ledger", len(st["ledger"]), "tick", st["company"]["tick"], "day ticks", st["day"]["ticks"])
            outs = [await call(s, "end_turn") for _ in range(300)]
            print("end_turn replay: ok", sum('"ok": true' in o for o in outs), "day over", sum("day over" in o for o in outs))
            print("after finalise:", (await call(s, "post_chat", {"to": ["all"], "body": "late"}))[:60].replace("\n", " "))
            r2 = get_reward()
            print("reward idempotent", r2 == rew, "state unchanged", len(json.load(open(STATE))["ledger"]) == len(st["ledger"]))

asyncio.run(main())
