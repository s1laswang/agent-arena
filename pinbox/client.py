"""EpisodeClient: the ONLY interface agents use (reference, baselines, Gemini, MCP)."""
from __future__ import annotations


class EpisodeClient:
    def __init__(self, episode):
        self._episode = episode

    def instruction(self) -> str:
        """Task text + full policy + tool notes."""
        return self._episode.instruction()

    def tools(self) -> list[dict]:
        """Tool specs: [{"name", "description", "parameters": JSON-Schema object}]."""
        return self._episode.tools()

    def call(self, _tool, /, **args) -> dict:
        """Call a tool: client.call("pay_invoice", invoice_id="INV-101", amount=120.5, iban="FI...").
        Returns {"ok": bool, "result": ..., "error": str | None}. Never raises."""
        return self._episode.call(_tool, args)

    def call_args(self, tool: str, args: dict | None = None) -> dict:
        """Same as call(), with the arguments as one dict (handy for MCP / function calling)."""
        return self._episode.call(tool, args if args is not None else {})


class AgentStopped(Exception):
    """Raised by LimitedClient when the agent reaches its call limit (stop-early baselines)."""


class LimitedClient:
    """Wraps a client and stops the agent (raises AgentStopped) after `max_calls` calls."""

    def __init__(self, inner, max_calls: int):
        self._inner = inner
        self.max_calls = int(max_calls)
        self.used = 0

    def instruction(self) -> str:
        return self._inner.instruction()

    def tools(self) -> list[dict]:
        return self._inner.tools()

    def call(self, _tool, /, **args) -> dict:
        return self.call_args(_tool, args)

    def call_args(self, tool: str, args: dict | None = None) -> dict:
        if self.used >= self.max_calls:
            raise AgentStopped()
        self.used += 1
        return self._inner.call_args(tool, args if args is not None else {})
