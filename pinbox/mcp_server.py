"""MCP server: serves one episode's tools over MCP (stdio or streamable HTTP). SPEC section 11.

    python -m pinbox serve ap_run:7:2 --transport stdio
    python -m pinbox serve ap_run:7:2 --transport http --host 0.0.0.0 --port 8765 --admin-token SECRET
    python -m pinbox.mcp_server ap_run:7:2 --transport http --port 8765 --state-dir DIR   (same, plus --state-dir)

- The tools are exactly tool_specs(family), with their JSON Schemas. Each call goes to
  EpisodeClient.call; the reply is the dispatch dict {"ok", "result", "error"} as JSON text.
- The server "instructions" are the episode instruction. The get_task tool returns the same text,
  for agents whose MCP client ignores server instructions.
- State lives only in the server process and its state folder (default: a fresh temp folder,
  or $PINBOX_STATE_DIR). It is saved after every call. If the folder already holds a state.json
  for the same episode, the server resumes from it.
- HTTP only: GET /healthz (no token), GET /admin/grade?token=T (GradeReport JSON),
  GET /admin/trajectory?token=T (trajectory JSONL). A missing or wrong token gets 403.
  The token can also come from $PINBOX_ADMIN_TOKEN. Without a token the admin routes are off (403).

Needs the `mcp` package (2.x, tested with 2.3.0). It is imported lazily, so the rest of pinbox
stays stdlib only.
"""
from __future__ import annotations

import argparse
import contextlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

ENV_STATE_DIR = "PINBOX_STATE_DIR"
ENV_ADMIN_TOKEN = "PINBOX_ADMIN_TOKEN"
SERVER_NAME = "pinbox"


def _log(msg: str) -> None:
    """Logs go to stderr only: in stdio mode stdout is the JSON-RPC stream."""
    try:
        print(f"[pinbox-mcp] {msg}", file=sys.stderr, flush=True)
    except Exception:
        pass


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


# ---------------------------------------------------------------- episode

def load_episode(spec, state_dir=None):
    """Open the episode to serve, saving into `state_dir` after every call.

    spec: 'FAMILY:SEED:DIFFICULTY' (or 'family-sS-dD'), or an existing episode folder (copied, never changed).
    state_dir: where the server keeps state.json / trajectory.jsonl / meta.json.
               None -> $PINBOX_STATE_DIR, else a fresh temp folder.
               If it already holds state.json for the same episode, that state is resumed.
    """
    from .episode import Episode, parse_spec
    from .state import episode_id

    spec = str(spec)
    src = Path(spec)
    is_folder = (src / "state.json").exists()
    parsed = None if is_folder else parse_spec(spec)
    if not is_folder and parsed is None:
        raise ValueError(f"not an episode folder or a spec like ap_run:7:2 -> {spec!r}")
    if parsed is not None:
        from .tasks import get_task
        get_task(parsed[0])  # unknown family -> KeyError before any folder is made

    if state_dir is None:
        state_dir = os.environ.get(ENV_STATE_DIR) or None
    if state_dir is None:
        state_dir = tempfile.mkdtemp(prefix="pinbox-mcp-")
    state_dir = Path(state_dir).resolve()

    if (state_dir / "state.json").exists():
        ep = Episode.load(state_dir, autosave=True)
        want = episode_id(*parsed) if parsed else Episode.load(src).episode_id
        if ep.episode_id != want:
            raise ValueError(f"state folder {state_dir} holds episode {ep.episode_id}, not {want}; "
                             f"use an empty folder")
        _log(f"resuming {ep.episode_id} from {state_dir} ({len(ep.trajectory)} calls so far)")
        return ep

    if is_folder:
        ep = Episode.load(src, autosave=True)
    else:
        family, seed, difficulty = parsed
        ep = Episode.create(family, seed, difficulty, autosave=True)
    ep.save(state_dir)  # sets ep.path; from now on every call is saved there
    return ep


# ---------------------------------------------------------------- MCP server

def _error_out(msg: str) -> dict:
    return {"ok": False, "result": None, "error": msg}


def build_server(episode):
    """A low-level mcp Server whose tools are exactly tool_specs(family), forwarding to EpisodeClient."""
    from mcp.server import Server
    from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

    from . import __version__
    from .client import EpisodeClient

    client = EpisodeClient(episode)
    specs = client.tools()
    tools = [Tool(name=s["name"], description=s["description"], input_schema=s["parameters"]) for s in specs]

    async def on_list_tools(ctx, params) -> ListToolsResult:
        return ListToolsResult(tools=tools)

    async def on_call_tool(ctx, params) -> CallToolResult:
        # Synchronous inside (no await), so concurrent HTTP requests can never interleave on the state.
        try:
            args = params.arguments
            if args is None:
                args = {}
            out = client.call_args(params.name, dict(args) if isinstance(args, dict) else args)
            if not isinstance(out, dict) or "ok" not in out:
                out = _error_out("internal error: bad dispatch result")
        except Exception as e:  # never raise here: the model would only see "-32603 Internal error"
            out = _error_out(f"internal server error: {type(e).__name__}")
        return CallToolResult(content=[TextContent(type="text", text=_dumps(out))],
                              structured_content=out, is_error=not out.get("ok"))

    return Server(SERVER_NAME, version=__version__, title="Poisoned Inbox",
                  instructions=episode.instruction(),
                  on_list_tools=on_list_tools, on_call_tool=on_call_tool)


# ---------------------------------------------------------------- HTTP app

def _token_ok(request, admin_token) -> bool:
    if not admin_token:
        return False
    given = request.query_params.get("token")
    if not given:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
    if not given:
        return False
    return hmac.compare_digest(given.encode("utf-8"), str(admin_token).encode("utf-8"))


def build_http_app(server, episode, host="0.0.0.0", admin_token=None):
    """Starlette app: MCP at /mcp, plus /healthz, /admin/grade and /admin/trajectory."""
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    async def healthz(request):
        return JSONResponse({"ok": True})

    async def admin_grade(request):
        if not _token_ok(request, admin_token):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        from .grader import grade
        try:
            report = grade(episode).to_dict()
        except Exception as e:
            return JSONResponse({"error": f"grader failed: {type(e).__name__}: {e}"}, status_code=500)
        return Response(_dumps(report), media_type="application/json")

    async def admin_trajectory(request):
        if not _token_ok(request, admin_token):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        text = "".join(_dumps(r) + "\n" for r in episode.trajectory)
        return Response(text, media_type="application/x-ndjson")

    routes = [
        Route("/healthz", healthz, methods=["GET"]),
        Route("/health", healthz, methods=["GET"]),
        Route("/admin/grade", admin_grade, methods=["GET"]),
        Route("/admin/trajectory", admin_trajectory, methods=["GET"]),
    ]
    # host 127.0.0.1/localhost turns on the SDK's Host-header check for /mcp; 0.0.0.0 does not.
    return server.streamable_http_app(streamable_http_path="/mcp", host=host, custom_starlette_routes=routes)


# ---------------------------------------------------------------- entry points

def serve(spec=None, transport: str = "stdio", host: str = "0.0.0.0", port: int = 8765,
          admin_token: str | None = None, state_dir=None, runs_dir=None, *, episode_spec=None) -> int:
    """Serve one episode over MCP until stopped. Returns an exit code.

    spec / episode_spec: 'FAMILY:SEED:DIFFICULTY' or an existing episode folder.
    runs_dir is accepted for the CLI but not used: state goes to state_dir (see load_episode).
    """
    spec = spec if spec is not None else episode_spec
    if spec is None:
        raise ValueError("serve() needs an episode spec like ap_run:7:2 or an episode folder")
    if transport not in ("stdio", "http", "streamable-http"):
        raise ValueError(f"transport must be stdio or http, not {transport!r}")
    if admin_token is None:
        admin_token = os.environ.get(ENV_ADMIN_TOKEN) or None
    try:
        import anyio
        import mcp  # noqa: F401
    except ImportError as e:
        print(f"error: the MCP server needs the 'mcp' package (pip install 'mcp>=2.3,<3'): {e}", file=sys.stderr)
        return 2

    # Nothing may reach stdout before the stdio transport owns it.
    with contextlib.redirect_stdout(sys.stderr):
        episode = load_episode(spec, state_dir)
        server = build_server(episode)

    _log(f"serving {episode.episode_id} over {transport}; state in {episode.path}")

    if transport == "stdio":
        from mcp.server.stdio import stdio_server

        async def run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())

        anyio.run(run_stdio)
        return 0

    import uvicorn
    app = build_http_app(server, episode, host=host, admin_token=admin_token)
    _log(f"MCP endpoint http://{host}:{port}/mcp" + ("  (admin routes on)" if admin_token else ""))
    uvicorn.run(app, host=host, port=int(port), log_level="warning")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m pinbox.mcp_server", description="Serve a Poisoned Inbox episode over MCP")
    p.add_argument("episode", help="spec like ap_run:7:2, or an episode folder")
    p.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--admin-token", default=None, help=f"enables /admin/* (or set ${ENV_ADMIN_TOKEN})")
    p.add_argument("--state-dir", default=None, help=f"state folder (default ${ENV_STATE_DIR} or a new temp folder)")
    a = p.parse_args(argv)
    try:
        return serve(a.episode, transport=a.transport, host=a.host, port=a.port,
                     admin_token=a.admin_token, state_dir=a.state_dir)
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except ImportError as e:
        print(f"error: the MCP server needs the 'mcp' package (pip install 'mcp>=2.3,<3'): {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
