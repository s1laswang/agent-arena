"""Minimal stdlib MCP (streamable HTTP, JSON-RPC) client for red-team tests and the stub attacker.

Handles both `application/json` and `text/event-stream` responses and the Mcp-Session-Id header,
so it works against the real canary.mcp_server and the plumbing-only fake server.
"""
from __future__ import annotations

import itertools
import json
import urllib.error
import urllib.request


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, url: str, timeout: float = 30.0):
        self.url = url
        self.timeout = timeout
        self.session: str | None = None
        self._ids = itertools.count(1)

    def _post(self, payload: dict) -> dict | None:
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": "2025-06-18"}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                sid = r.headers.get("Mcp-Session-Id")
                if sid:
                    self.session = sid
                body = r.read().decode()
                ctype = r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise MCPError(f"HTTP {e.code}: {e.read()[:300]!r}") from e
        if "id" not in payload or not body.strip():
            return None
        if "text/event-stream" in ctype:
            for line in body.splitlines():
                if line.startswith("data:"):
                    msg = json.loads(line[5:].strip())
                    if msg.get("id") == payload["id"]:
                        return msg
            raise MCPError("no matching SSE response")
        return json.loads(body)

    def request(self, method: str, params: dict | None = None) -> dict:
        msg = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params or {}})
        if msg is None:
            raise MCPError("empty response")
        if "error" in msg:
            raise MCPError(json.dumps(msg["error"]))
        return msg["result"]

    def initialize(self) -> dict:
        res = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "canary-redteam", "version": "0"}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return res

    def list_tools(self) -> list[dict]:
        return self.request("tools/list")["tools"]

    def call_raw(self, name: str, args: dict | None = None) -> dict:
        return self.request("tools/call", {"name": name, "arguments": args or {}})

    def call(self, name: str, args: dict | None = None) -> dict:
        """Return the tool payload as a dict ({ok, data, error} for Canary), best effort."""
        res = self.call_raw(name, args)
        sc = res.get("structuredContent")
        if isinstance(sc, dict):
            return sc.get("result", sc) if set(sc) == {"result"} else sc
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        try:
            out = json.loads(text)
            return out if isinstance(out, dict) else {"ok": not res.get("isError"), "data": out}
        except json.JSONDecodeError:
            return {"ok": not res.get("isError", False), "data": None, "error": text, "_raw": text}

    @staticmethod
    def raw_text(res: dict) -> str:
        return json.dumps(res, sort_keys=True)


def http_get(url: str, timeout: float = 10.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
