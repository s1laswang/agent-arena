import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from agents.reference import make_oracle_seat
from sleeper.models import Day


async def play(url, seat, day_path):
    day = Day.model_validate_json(open(day_path).read())
    oracle = make_oracle_seat(day, seat)
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
                    print("TOOLERR", name, txt[:200], file=sys.stderr, flush=True)
                    return {"ok": False, "error": txt}

            class Over(Exception):
                pass

            def call(name, args=None):
                out = asyncio.run_coroutine_threadsafe(acall(name, args or {}), loop).result()
                if out.get("error") == "day over":
                    raise Over
                return out

            def rounds():
                for tick in range(day.ticks + 5):
                    try:
                        oracle.turn(seat, {"tick": tick, "seat": seat, "round": tick}, tools, call)
                    except Over:
                        return

            await loop.run_in_executor(None, rounds)


if __name__ == "__main__":
    asyncio.run(play(*sys.argv[1:4]))
