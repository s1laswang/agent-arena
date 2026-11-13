"""Play the day through a live MCP server with any scripted policy.

  python -m blindspot.mcp_client http://localhost:8000/mcp oracle
  python -m blindspot.mcp_client stdio:3 autopilot        (spawns a stdio server, seed 3)

`McpEnv` gives an MCP connection the same `.call(tool, args)` interface as the
in-process Env, so the oracle in Harbor's solution/ is exactly the same code
that proves solvability in the tests.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading


class McpEnv:
    def __init__(self, target: str, state_out: str | None = None):
        self.target = target
        self.state_out = state_out
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._stop = None
        self._err = None
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self._fut = asyncio.run_coroutine_threadsafe(self._session(), self.loop)
        self._ready.wait(60)
        if self._err:
            raise self._err
        self.done = False

    async def _session(self):
        from mcp.client.session import ClientSession
        try:
            if self.target.startswith("stdio:"):
                from mcp.client.stdio import StdioServerParameters, stdio_client
                seed = self.target.split(":", 1)[1]
                args = ["-m", "blindspot.mcp_server", "--seed", seed]
                if self.state_out:
                    args += ["--state-out", self.state_out]
                cm = stdio_client(StdioServerParameters(command=sys.executable, args=args))
            else:
                from mcp.client.streamable_http import streamable_http_client
                cm = streamable_http_client(self.target)
            async with cm as streams:
                r, w = streams[0], streams[1]
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    self.session = s
                    self._stop = asyncio.Event()
                    self._ready.set()
                    await self._stop.wait()
        except Exception as e:  # surface connection errors to the caller
            self._err = e
            self._ready.set()

    async def _call(self, tool, args):
        res = await self.session.call_tool(tool, args)
        return json.loads(res.content[0].text)

    def call(self, tool: str, args: dict | None = None) -> dict:
        out = asyncio.run_coroutine_threadsafe(self._call(tool, args or {}), self.loop).result(120)
        if tool == "end_day" and out.get("ok"):
            self.done = True
        return out

    def close(self):
        if self._stop is not None:
            self.loop.call_soon_threadsafe(self._stop.set)
            try:
                self._fut.result(10)
            except Exception:
                pass


def main(argv=None):
    from .baselines import POLICIES
    argv = argv if argv is not None else sys.argv[1:]
    target, policy = argv[0], argv[1] if len(argv) > 1 else "oracle"
    env = McpEnv(target, state_out=argv[2] if len(argv) > 2 else None)
    try:
        POLICIES[policy](env)
    finally:
        env.close()
    print(f"{policy} finished over MCP")


if __name__ == "__main__":
    main()
