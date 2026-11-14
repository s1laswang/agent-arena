# MCP notes for `pinbox/mcp_server.py`

Research notes for the MCP builder. Checked on 2026-11-14 with the venv
`scratchpad/venv` (Python 3.14.5, Windows 11). All code below was run there.
Throwaway test scripts are in the scratchpad folder `mcp tests ö/` (not in the repo).

## 0. Short version

- **Installed versions:** `mcp` 2.3.0, `mcp-types` 2.3.0, `starlette` 1.10.0, `uvicorn` 0.54.0,
  `httpx2` 2.16.0 (the SDK now uses `httpx2`, not `httpx`), `pydantic` 2.14.3, `anyio` 4.16.0.
  `mcp` 2.3.0 is the latest on PyPI (2026-10-02). 2.0.0 came out 2026-07-28. The last 1.x is 1.30.0.
- **FastMCP is gone in mcp 2.x.** `from mcp.server.fastmcp import FastMCP` raises `ModuleNotFoundError`.
  It was renamed to `mcp.server.mcpserver.MCPServer` (also `from mcp.server import MCPServer`).
  SPEC section 11 says "FastMCP". On mcp 2.x that means `MCPServer`, or better, the low-level `Server`.
- **Use the low-level `mcp.server.Server`** (option A below). Our tools are dicts with a ready JSON Schema.
  `MCPServer` builds schemas from Python function signatures, so it fits badly. The SDK docs say to use the
  low-level server for "an exact schema loaded from a file or generated".
- **Pin it:** `mcp>=2.3,<3`. A plain `pip install mcp` gets 2.x now, so v1 code (FastMCP, decorators) breaks.
- **Import `mcp` lazily** (inside `serve` only), so `python -m pinbox eval` works on bare Python (SPEC section 2).
- **Never raise in the call handler.** In 2.x an exception in a low-level handler becomes a JSON-RPC error
  `-32603 Internal server error`. The model never sees the message. Return `is_error=True` instead.
- **In Docker, bind `0.0.0.0`.** If you bind `127.0.0.1`/`localhost`, the SDK turns on a Host-header check
  and any other host name gets `421 Invalid Host header` on `/mcp`.

## 1. Dynamic tool list with explicit JSON Schemas

### Option A (recommended): low-level `Server`, verified

In 2.x the low-level server takes handlers as constructor arguments (no more `@server.list_tools()`
decorators; those now fail with `AttributeError`). Each handler is `async (ctx, params) -> full result`.
The schema you give is sent to clients as is. The SDK does **not** check arguments against it;
our dispatcher already does that (SPEC section 5).

`server_lowlevel.py` (verified over stdio, streamable HTTP and in-process):

```python
import sys

import anyio
import uvicorn
from mcp.server import Server, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from fake_env import TOOL_SPECS, FakeEpisode, dumps

EPISODE = FakeEpisode()  # state lives only in this server process


def build_server(specs, episode):
    tools = [Tool(name=s["name"], description=s["description"], input_schema=s["parameters"]) for s in specs]

    async def on_list_tools(ctx: ServerRequestContext, params: PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    async def on_call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        out = episode.call(params.name, **(params.arguments or {}))  # sync, no await: atomic on the event loop
        return CallToolResult(
            content=[TextContent(type="text", text=dumps(out))],
            structured_content=out,
            is_error=not out["ok"],
        )

    return Server("pinbox-test", version="0.1", on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def run_stdio(server):
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run_http(server, host, port, admin_token):
    async def admin_grade(request: Request):
        if not admin_token or request.query_params.get("token") != admin_token:
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse(EPISODE.grade())

    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        host=host,  # 127.0.0.1/localhost turns on DNS-rebinding (Host header) checks
        custom_starlette_routes=[Route("/admin/grade", admin_grade, methods=["GET"])],
    )
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    srv = build_server(TOOL_SPECS, EPISODE)
    if sys.argv[1] == "stdio":
        anyio.run(run_stdio, srv)
    else:
        run_http(srv, sys.argv[2], int(sys.argv[3]), sys.argv[4] if len(sys.argv) > 4 else None)
```

`fake_env.py` stands in for pinbox: `TOOL_SPECS` = `tool_specs(family)` (list of
`{"name", "description", "parameters"}`), `FakeEpisode.call(name, **args)` = `EpisodeClient.call`
(returns `{"ok", "result", "error"}`, never raises), `grade()` = the GradeReport. `dumps` is
`json.dumps(obj, ensure_ascii=False)`.

What the client sees (verified): `content[0].text` is the dispatch dict as JSON, `structured_content`
is the same dict, `is_error` is `True` when `ok` is false (bad args, insufficient funds, unknown tool).
Finnish letters and the euro sign survive both transports.

### Option B: `MCPServer` (ex-FastMCP) with explicit schemas, verified

`MCPServer.add_tool(fn)` always makes the schema from `fn`'s signature. Overriding its two public
methods `list_tools()` and `call_tool()` keeps our schemas and still gives `run()` and `custom_route()`:

```python
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, Tool
from starlette.requests import Request
from starlette.responses import JSONResponse

from fake_env import TOOL_SPECS, FakeEpisode, dumps


class SpecServer(MCPServer):
    def __init__(self, specs, episode, admin_token=None, **kw):
        super().__init__("pinbox-test-b", **kw)
        self._specs = specs
        self._episode = episode
        self._admin_token = admin_token

        @self.custom_route("/admin/grade", methods=["GET"])
        async def admin_grade(request: Request):
            if not self._admin_token or request.query_params.get("token") != self._admin_token:
                return JSONResponse({"error": "forbidden"}, status_code=403)
            return JSONResponse(self._episode.grade())

    async def list_tools(self):
        return [Tool(name=s["name"], description=s["description"], input_schema=s["parameters"]) for s in self._specs]

    async def call_tool(self, name, arguments, context=None):
        out = self._episode.call(name, **(arguments or {}))
        return CallToolResult(content=[TextContent(type="text", text=dumps(out))],
                              structured_content=out, is_error=not out["ok"])

# stdio:  SpecServer(TOOL_SPECS, FakeEpisode()).run("stdio")
# HTTP:   SpecServer(TOOL_SPECS, FakeEpisode(), admin_token="s3cret", log_level="WARNING").run(
#             "streamable-http", host="127.0.0.1", port=8767)
```

This works (stdio, HTTP, in-process). The downside: it overrides methods that MCPServer's own
handlers call, which is not a documented extension point, so a 2.x minor release could change it.

### FastMCP vs low-level, side by side

| | low-level `Server` (A) | `MCPServer` (B, ex-FastMCP) |
|---|---|---|
| Explicit JSON Schema from a dict | Yes, documented | Only by overriding `list_tools`/`call_tool` |
| Argument checking | None (our dispatcher does it) | None in B (the override skips it) |
| Handler raises | JSON-RPC error -32603, model sees nothing | `is_error=True` result with the exception text (MCPServer's wrapper still runs) |
| stdio | `stdio_server()` + `server.run(...)` (3 lines) | `.run("stdio")` |
| Streamable HTTP | `server.streamable_http_app(...)` + `uvicorn.run` | `.run("streamable-http", host=, port=)` |
| Extra HTTP route | `custom_starlette_routes=[Route(...)]` | `@server.custom_route(path, methods=[...])` |
| `mcp dev` / `mcp run` CLI | Not supported | Supported (not needed by us) |

What does **not** work (verified): `MCPServer.add_tool(def f(**kwargs))` makes a schema with one
required string field called `kwargs`, and every real call fails validation. `def f(args: dict)` makes a
schema with one required field `args`. Do not use `add_tool` for dict specs.

## 2. Transports

### stdio (verified)

- Code: see `run_stdio` above. The server exits by itself (code 0) when stdin closes. Verified with `< /dev/null`.
- **Do not print to stdout in stdio mode.** Stdout is the JSON-RPC stream. Logs go to stderr.
  So `serve --transport stdio` must not print the run folder the way `new` does.
- The SDK re-wraps stdin/stdout as UTF-8 itself, so no `PYTHONIOENCODING` is needed for the server.
  (A plain `print` in a client on this Windows console is cp1252 and shows `?`; that is only the console.)
- Spawned from a folder with a space and `ö` in the path: works.

### Streamable HTTP (verified)

- Endpoint is `/mcp` by default (`streamable_http_path`). Clients use `http://HOST:PORT/mcp`.
- Low-level: `app = server.streamable_http_app(host=..., custom_starlette_routes=[...])`, then
  `uvicorn.run(app, host=..., port=...)`. The app's lifespan starts the session manager for you.
- MCPServer: in 2.x `host`/`port` go to `run()`, **not** the constructor:
  `server.run("streamable-http", host="0.0.0.0", port=8000)`.
- Sessions are stateful by default (`mcp-session-id` header). Each client connection is its own MCP
  session, but our handler closes over one episode, so all sessions share the same world. Verified:
  two client runs in a row kept lowering the same balance.
- **Host check:** `host` in `127.0.0.1`/`localhost`/`::1` auto-enables DNS-rebinding protection.
  Verified: bound to 127.0.0.1, a POST to `/mcp` with `Host: env-server:8765` gets `421 Invalid Host header`.
  Bound to `0.0.0.0`, the same request works. The check only guards `/mcp`; custom routes answer any Host.
  For Docker/Harbor, bind `0.0.0.0` (or pass `transport_security=TransportSecuritySettings(allowed_hosts=[...])`).
- `GET /mcp` with no session gives `400 Missing session ID`. Use a custom route for health checks.

### Custom route `GET /admin/grade?token=...` (verified)

Both variants are in the code above. Results: no/bad token gives `403 {"error":"forbidden"}`, the right
token gives `200` with the grade JSON. Custom routes are not behind MCP auth or the Host check, so the
token check is the only guard. Use `hmac.compare_digest` for the compare in the real file.

Tip: also add `GET /health` (no token, returns `{"ok": true}`) so Harbor/scripts can wait until the
server is up. On this laptop, Python starts in about 2 s and `import mcp` takes about 5-6 s more.

### Raw HTTP walk-through (what a non-Python client like OpenCode does), verified with curl

```bash
U=http://127.0.0.1:8769/mcp; H=(-H "Content-Type: application/json" -H "Accept: application/json, text/event-stream")
# 1. initialize -> read the mcp-session-id response header
curl -s -D - "${H[@]}" -X POST -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"0"}}}' $U
# 2. initialized notification -> 202
curl -s "${H[@]}" -H "Mcp-Session-Id: $SID" -X POST -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' $U
# 3. tools/list and tools/call -> SSE "event: message / data: {...}"
curl -s "${H[@]}" -H "Mcp-Session-Id: $SID" -H "MCP-Protocol-Version: 2025-03-26" -X POST -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"pay_invoice","arguments":{"invoice_id":"INV-9","amount":12.34,"iban":"FI00"}}}' $U
# 4. DELETE ends the session -> 200
```

On the wire the keys are camelCase (`inputSchema`, `isError`, `structuredContent`).
Older protocol versions (2025-03-26, 2025-06-18) still work against the 2.x server.

## 3. Client side for tests

In 2.x the Python attributes are snake_case: `tool.input_schema`, `result.is_error`,
`result.structured_content`, `init.server_info`, `init.protocol_version`. Constructors accept both
spellings. `model_dump()` needs `by_alias=True` to get wire (camelCase) keys.
`streamablehttp_client` (no underscore) was removed; use `streamable_http_client`.

### `ClientSession` over stdio and streamable HTTP (verified)

```python
import json, os, sys
import anyio
from mcp import ClientSession, StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client


async def exercise(session: ClientSession):
    init = await session.initialize()                      # negotiated 2025-11-25
    print(init.server_info.name, init.protocol_version)
    for t in (await session.list_tools()).tools:
        print(t.name, t.input_schema)
    r = await session.call_tool("pay_invoice", {"invoice_id": "INV-101", "amount": 250.5, "iban": "FI00 1234"})
    print(json.loads(r.content[0].text), r.is_error, r.structured_content)


async def main():
    if sys.argv[1] == "stdio":
        script = os.path.abspath(sys.argv[2])
        params = StdioServerParameters(command=sys.executable, args=[script, "stdio"], cwd=os.path.dirname(script))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await exercise(session)
    else:
        async with streamable_http_client(sys.argv[2]) as (read, write):   # e.g. http://127.0.0.1:8765/mcp
            async with ClientSession(read, write) as session:
                await exercise(session)

anyio.run(main)
```

`StdioServerParameters` fields: `command`, `args`, `env` (merged over a safe default env), `cwd`,
`encoding="utf-8"`. Use `sys.executable` as the command so the child uses the same venv.

### High-level `mcp.Client` (verified, simplest)

```python
from mcp import Client, StdioServerParameters

async with Client(build_server(TOOL_SPECS, episode)) as c:   # in-process: no subprocess, no port
    ...
async with Client(StdioServerParameters(command=sys.executable, args=[script, "stdio"], cwd=folder)) as c:
    ...
async with Client("http://127.0.0.1:8768/mcp") as c:          # a URL string means streamable HTTP
    tools = (await c.list_tools()).tools
    r = await c.call_tool("pay_invoice", {"invoice_id": "INV-1", "amount": 10, "iban": "FI00"})
    print(r.content[0].text, r.is_error)
```

- `Client` negotiates protocol `2026-07-28` with our server (it probes `server/discover` first, then
  falls back to `initialize` on old servers). No `initialize()` call needed.
- A tool result with `is_error=True` is **returned**, not raised. A handler that raises gives
  `mcp.shared.exceptions.MCPError` (code -32603) on the client. Verified.
- `Client(server, raise_exceptions=True)` shows the real server exception in tests.
- `Client` has a response cache, but by default it only stores results the server marks with a TTL
  (`default_ttl_ms=0`). Our server sends no TTL, so nothing is cached.

### unittest pattern for `tests/test_mcp.py` (verified, also skips on bare Python)

```python
import importlib.util, json, os, sys, unittest

HAS_MCP = importlib.util.find_spec("mcp") is not None


@unittest.skipUnless(HAS_MCP, "mcp not installed")
class InProcessTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_and_call(self):
        from mcp import Client
        from fake_env import TOOL_SPECS, FakeEpisode      # in pinbox: tool_specs(family), an Episode
        from server_lowlevel import build_server          # in pinbox: the builder in mcp_server.py
        ep = FakeEpisode()
        async with Client(build_server(TOOL_SPECS, ep), raise_exceptions=True) as c:
            tools = {t.name: t for t in (await c.list_tools()).tools}
            self.assertEqual(tools["pay_invoice"].input_schema, TOOL_SPECS[1]["parameters"])
            r = await c.call_tool("pay_invoice", {"invoice_id": "INV-1", "amount": 1.5, "iban": "FI"})
            self.assertFalse(r.is_error)
            r = await c.call_tool("pay_invoice", {"invoice_id": "INV-1"})   # missing args
            self.assertTrue(r.is_error)
        self.assertEqual(ep.balance, 998.5)
```

Timing here: in-process test about 6 s (mostly `import mcp`), stdio subprocess test about 13 s.
Under `IsolatedAsyncioTestCase` asyncio debug mode prints "Executing <Task ...> took 0.6 seconds"
lines. That is noise, not a failure. On system Python without `mcp` both tests show as skipped.

## 4. OpenCode config (`opencode.json`)

OpenCode's config schema (`https://opencode.ai/config.json`, downloaded 2026-11-14) accepts **two**
forms. I validated each example below against that schema with `jsonschema` (Draft 2020-12).

### New form: `mcp.servers.<name>` (current docs)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "pinbox": {
        "type": "local",
        "command": ["python", "-m", "pinbox", "serve", "ap_run:7:2", "--transport", "stdio"],
        "environment": {"PYTHONUTF8": "1"},
        "timeout": {"startup": 30000, "execution": 120000},
        "codemode": false
      }
    }
  }
}
```

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "servers": {
      "pinbox": {"type": "remote", "url": "http://env:8000/mcp", "oauth": false, "codemode": false}
    }
  }
}
```

New-form fields: `type` (`"local"`/`"remote"`, required), `command` (string **array**, required for local),
`cwd`, `environment` (string map), `url` (required for remote), `headers` (string map), `oauth`
(object or `false`), `disabled` (bool, default false; there is no `enabled` here), `codemode` (bool,
default true), `timeout` (object in ms: `startup` 30 s, `catalog` 30 s, `execution` 12 h by default),
`protocol` (`"legacy"` default / `"auto"` / `"2026-07-28"`), `pool` (bool). Env values can use `{env:NAME}`.

### Legacy form: `mcp.<name>` (deprecated but still valid; this is what Harbor writes)

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "pinbox": {"type": "local", "command": ["python", "-m", "pinbox", "serve", "ap_run:7:2", "--transport", "stdio"],
               "environment": {"PYTHONUTF8": "1"}, "enabled": true, "timeout": 30000}
  }
}
```

```jsonc
{"mcp": {"pinbox": {"type": "remote", "url": "http://env:8000/mcp", "oauth": false}}}
```

Legacy fields: `type`, `command`/`url`, `environment`, `headers`, `oauth`, `enabled` (bool), and
`timeout` as a single **integer** in ms (request timeout, default 5000).
Harbor 0.25.0 (`harbor/agents/installed/opencode.py`) writes exactly the legacy form to
`~/.config/opencode/opencode.json`: `{"type": "local", "command": [cmd, *args]}` for stdio and
`{"type": "remote", "url": ..., "oauth": false}` for SSE/streamable-http. It installs
`opencode-ai@latest` by default.

Schema checks that fail (so avoid them): `disabled` in the legacy form, `enabled` in the new form,
an integer `timeout` in the new form, `command` as one string.

Other facts from the OpenCode docs:
- Local servers use stdio. Remote servers use Streamable HTTP and need an absolute URL.
- Tools are named `<server>_<tool>` (so `pinbox_pay_invoice`). With Code Mode (default on in the new
  form) the model calls them as `tools.<server>.<tool>(...)`. `"codemode": false` exposes them directly.
- OpenCode's default `protocol` is `legacy` (plain `initialize`). Our 2.x server handles that (checked
  with curl and `ClientSession`).
- Deny tools with `permissions`, e.g. `{"action": "pinbox_*", "resource": "*", "effect": "deny"}`.
  The old top-level `"tools": {"name": false}` map is still in the schema but marked deprecated.

## 5. Gotchas for the builder

1. `EpisodeClient.call(name, **args)`: a tool argument literally called `name` would clash with the first
   parameter (TypeError). No current tool has one, but catch `TypeError` and return an error result anyway.
2. Wrap the whole call handler in `try/except Exception` and return
   `CallToolResult(content=[TextContent(text=json.dumps({"ok": False, "result": None, "error": "..."}))], is_error=True)`.
3. `params.arguments` can be `None` (client sent no arguments). Use `params.arguments or {}`.
4. Keep the handler synchronous inside (no `await` between reading and writing state). Then concurrent
   HTTP requests cannot interleave. If you add awaits, add an `anyio.Lock`.
5. The MCP spec requires `"type": "object"` at the root of `input_schema`. The SDK does not check it
   (verified: `Tool(input_schema={"properties": {}})` is accepted), so make sure every spec has it.
6. SPEC CLI `serve EP_SPEC --transport stdio|http --port P [--admin-token T]` has no `--host`.
   Suggest adding `--host` (default `127.0.0.1`; Harbor uses `0.0.0.0`).
7. Optional: pass `get_tool_input_schema=lambda n: schemas.get(n)` to `Server(...)`. It is only used for
   `Mcp-Param-*` header checks on 2026-07-28 HTTP connections. Not needed for us.

## Sources

- Installed package source (primary): `scratchpad/venv/Lib/site-packages/mcp/` — `server/lowlevel/server.py`,
  `server/mcpserver/server.py`, `server/fastmcp.py`, `client/client.py`, `client/stdio.py`, `client/streamable_http.py`.
- SDK repo: https://github.com/modelcontextprotocol/python-sdk
- SDK docs v2: https://py.sdk.modelcontextprotocol.io/ — migration guide https://py.sdk.modelcontextprotocol.io/v2/migration/ ,
  low-level server https://py.sdk.modelcontextprotocol.io/advanced/low-level-server/ ,
  testing https://py.sdk.modelcontextprotocol.io/get-started/testing/ , v1 docs https://py.sdk.modelcontextprotocol.io/v1/
- PyPI release list: https://pypi.org/pypi/mcp/json
- OpenCode MCP docs: https://opencode.ai/docs/mcp-servers/ ; config schema: https://opencode.ai/config.json
  (sha256 of the copy checked: b0e0a39a0a7cc3e91763bbc73092b2b7dba99b4810bf90750e6df5b077cfa8e7)
- Harbor 0.25.0 OpenCode adapter source (copy saved by the Harbor researcher in the scratchpad `hsrc/`).

## UNVERIFIED

- OpenCode itself was not installed or run. Config examples are checked only against the published JSON
  Schema and docs, not against a live `opencode` binary.
- Whether OpenCode merges or prefers the new `mcp.servers` form over the legacy `mcp.<name>` form when both appear.
- Whether `"codemode": false` changes how well agents use our tools (no test run).
- mcp 1.x / FastMCP code paths: not tested (no 1.x venv). If someone pins `mcp<2`, the API is different
  (decorators, camelCase attributes, `FastMCP(host=, port=)` in the constructor).
- Mounting the MCP app inside a bigger Starlette app (`Mount("/x", app=...)`) was not tested. The docs say the
  outer app then needs `lifespan` that enters `server.session_manager.run()`. Using `custom_starlette_routes`
  (tested) avoids this.
- `stateless_http=True` and `json_response=True` were not tested.
- Linux/Docker run of the server: not tested here (only Windows). Nothing in the code is Windows-specific.
