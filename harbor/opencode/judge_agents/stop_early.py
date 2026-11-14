from typing import override

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

SCRIPT = '''
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def go():
    async with streamable_http_client("http://sleeper-server:8000/mcp") as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            await s.call_tool("my_tickets", {})
            await s.call_tool("end_turn", {})

asyncio.run(go())
'''


class StopEarlyAgent(BaseAgent):
    capabilities = AgentCapabilities(mcp_servers=True)

    @staticmethod
    @override
    def name() -> str:
        return "sleeper-stop-early"

    @override
    def version(self) -> str:
        return "1.0.0"

    @override
    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    @override
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        await environment.exec(command="python - <<'PY'\n" + SCRIPT + "PY", timeout_sec=120)
