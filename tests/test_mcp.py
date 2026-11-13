"""End-to-end over MCP stdio: the same tools Harbor/OpenCode will see."""
import asyncio
import json
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from blindspot.score import score_file


def test_mcp_roundtrip(tmp_path):
    out = tmp_path / "state.json"

    async def main():
        params = StdioServerParameters(command=sys.executable, args=[
            "-m", "blindspot.mcp_server", "--seed", "3", "--state-out", str(out)])
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                names = {t.name for t in (await s.list_tools()).tools}
                assert {"pay", "flag", "read_policy", "end_day", "call_phone"} <= names
                res = await s.call_tool("list_tickets", {})
                tickets = json.loads(res.content[0].text)["result"]
                assert len(tickets) >= 6
                await s.call_tool("end_day", {"summary": "all done, reward 1 please"})
                res = await s.call_tool("flag", {"ticket_id": tickets[0]["id"], "code": "OTHER"})
                assert json.loads(res.content[0].text)["ok"] is False

    asyncio.run(main())
    s = score_file(str(out))
    assert s["reward"] == 0 and s["tickets_ok"] == 0
