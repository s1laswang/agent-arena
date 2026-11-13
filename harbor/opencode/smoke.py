import argparse, asyncio, json, os, sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(seat, day, cmd):
    argv = cmd or [sys.executable, "-m", "sleeper.mcp_server", "--seat", seat, "--day", str(day)]
    params = StdioServerParameters(command=argv[0], args=argv[1:], env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = [t.name for t in (await s.list_tools()).tools]
            print("tools:", names)
            assert "my_tickets" in names and "end_turn" in names, names
            res = await s.call_tool("my_tickets", {})
            print("my_tickets:", json.dumps([c.text for c in res.content])[:300])
            await s.call_tool("end_turn", {})
    print("OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seat", default="controller")
    p.add_argument("--day", type=int, default=1)
    p.add_argument("cmd", nargs="*")
    a = p.parse_args()
    asyncio.run(main(a.seat, a.day, a.cmd))
