import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from sleeper.scripted import OracleAgent


async def play(url, seat):
    async with streamable_http_client(url) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
            calls = []

            async def acall(name, args):
                res = await s.call_tool(name, args)
                calls.append((name, args))
                return json.loads(res.content[0].text) if res.content else {}

            loop = asyncio.get_running_loop()

            def call(name, args):
                return asyncio.run_coroutine_threadsafe(acall(name, args), loop).result()

            def rounds():
                for _ in range(100):
                    def c(name, args):
                        r = call(name, args)
                        if r.get("error") == "day over":
                            raise StopIteration
                        return r
                    try:
                        OracleAgent().turn(seat, {}, tools, c)
                    except StopIteration:
                        return

            await loop.run_in_executor(None, rounds)


if __name__ == "__main__":
    asyncio.run(play(sys.argv[1], sys.argv[2]))
