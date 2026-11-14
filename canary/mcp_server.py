"""Canary MCP server: one Env episode behind streamable HTTP (CONTRACT §3, §4). Owner: HARNESS.

    CANARY_TIER=medium CANARY_SEED=900007 CANARY_LEDGER_TOKEN=... python -m canary.mcp_server
    # MCP endpoint: http://127.0.0.1:8765/mcp

Environment variables:
    CANARY_HOST / CANARY_PORT   bind address (default 127.0.0.1:8765)
    CANARY_TIER / CANARY_SEED   the episode (default easy / 900000). The seed never appears in any tool output.
                                Only judge (900000-900029) or held-out (800000-800199) seeds are served;
                                dev/train seeds are public, so they need CANARY_ALLOW_DEV=1 (internal testing).
    CANARY_PROVIDER             text provider (default template)
    CANARY_LEDGER_TOKEN         token for GET /ledger?token=... (grader). Unset => /ledger always 403.
    CANARY_ADMIN_TOKEN          token for POST /admin/reset?token=... body {"tier","seed"}. Unset => disabled.

Secret files (EXPLOITS #25: a same-uid process can read the exec-time environment via /proc/<pid>/environ
or `ps eww`, so judge runs must not put the seed, world secret or tokens in env vars). Each names a 0600 file
read once at startup; a *_FILE var wins over its plain counterpart, which is then not needed:
    CANARY_EPISODE_FILE         JSON {"tier": ..., "seed": ...}
    CANARY_WORLD_SECRET_FILE    world secret for judge/held-out seeds (handed to canary.world in-process)
    CANARY_LEDGER_TOKEN_FILE    grader token
    CANARY_ADMIN_TOKEN_FILE     admin token
The plain env vars keep working for local dev.

Design notes:
- Built on the SDK's low-level `mcp.server.Server` (mcp 2.x; FastMCP is now MCPServer and derives tool
  schemas from Python signatures and validates arguments with pydantic). The low-level server lets us
  publish `Env.tools_spec()` 1:1 (same names, descriptions, JSON schemas) and forward raw arguments to
  `Env.call`, so all validation and every error string stays in Env (no second validator).
- Every tool returns the ToolResult as JSON text {ok, data, error}, plus the same dict as structured content.
- `Env.call` runs under a lock, so concurrent calls (e.g. parallel accuse) serialise; exactly one accusation.
- /ledger and /admin/reset are plain HTTP routes, not MCP tools; the agent never sees them in tools/list.
"""
from __future__ import annotations

import argparse
import asyncio
import hmac
import json
import logging
import os
import secrets
import sys
import threading
from dataclasses import asdict
from typing import Any

import mcp.types as types
from mcp.server import Server
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .types import ToolResult

log = logging.getLogger("canary.mcp_server")
INTERNAL_ERROR = "invalid arguments"  # an unexpected exception maps to a fixed env.ERRORS string; no traceback text


class SeedNotAllowed(ValueError):
    pass


class ConfigError(ValueError):
    pass


def _read_file_var(var: str, environ) -> str | None:
    """Contents of the file named by env var `var` (stripped), or None if `var` is unset. Never logs contents."""
    path = environ.get(var)
    if not path:
        return None
    try:
        mode = os.stat(path).st_mode
        with open(path) as fh:
            text = fh.read().strip()
    except OSError as exc:
        raise ConfigError(f"{var}: cannot read file ({type(exc).__name__})") from None
    if mode & 0o077:
        log.warning("%s is readable by group/others; chmod 600 it", var)
    if not text:
        raise ConfigError(f"{var}: file is empty")
    return text


def load_config(environ=None) -> dict:
    """Server config from env vars and/or 0600 secret files (files win)."""
    environ = os.environ if environ is None else environ
    tier, seed = environ.get("CANARY_TIER", "easy"), environ.get("CANARY_SEED", "900000")
    ep_text = _read_file_var("CANARY_EPISODE_FILE", environ)
    if ep_text is not None:
        try:
            obj = json.loads(ep_text)
            tier, seed = obj["tier"], obj["seed"]
        except Exception:
            raise ConfigError("CANARY_EPISODE_FILE: expected JSON {\"tier\": ..., \"seed\": ...}") from None
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise ConfigError("episode seed must be an integer") from None
    secret = _read_file_var("CANARY_WORLD_SECRET_FILE", environ)
    return {"tier": str(tier), "seed": seed,
            "world_secret": secret.encode() if secret is not None else None,
            "ledger_token": _read_file_var("CANARY_LEDGER_TOKEN_FILE", environ) or environ.get("CANARY_LEDGER_TOKEN") or None,
            "admin_token": _read_file_var("CANARY_ADMIN_TOKEN_FILE", environ) or environ.get("CANARY_ADMIN_TOKEN") or None}


def apply_world_secret(secret: bytes) -> None:
    """Hand the file secret to world generation in-process (never exported to os.environ / children)."""
    from . import world
    setter = getattr(world, "set_world_secret", None)
    if setter is not None:  # public API requested from HEAD-ENV
        setter(secret)
        return
    # Fallback until set_world_secret lands: world._key() uses the per-process secret only when neither
    # CANARY_WORLD_SECRET nor the SALT file is present, so refuse ambiguous setups instead of guessing.
    if os.environ.get("CANARY_WORLD_SECRET"):
        raise ConfigError("set CANARY_WORLD_SECRET_FILE or CANARY_WORLD_SECRET, not both")
    salt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(world.__file__))), "data", "worlds", "judge", "SALT")
    if os.path.exists(salt):
        raise ConfigError("CANARY_WORLD_SECRET_FILE given but data/worlds/judge/SALT exists and would take precedence")
    world._PROC_SECRET = secret


def seed_allowed(seed: int) -> bool:
    from .rules import HELDOUT_SEEDS, JUDGE_SEEDS
    return seed in JUDGE_SEEDS or seed in HELDOUT_SEEDS or os.environ.get("CANARY_ALLOW_DEV") == "1"


class Episode:
    """Holds the one live Env. Only the server process can see it."""

    def __init__(self, tier: str, seed: int, provider: str = "template"):
        self._lock = threading.Lock()
        self.provider = provider
        self.env = self._make(tier, seed)
        self.token = secrets.token_hex(8)  # opaque episode id; not derived from the seed
        self.on_reset = lambda: None

    def _make(self, tier: str, seed: int):
        from .eval import make_env
        if not seed_allowed(seed):
            raise SeedNotAllowed("only judge or held-out seeds are served; set CANARY_ALLOW_DEV=1 for dev/train seeds")
        return make_env(tier, seed, self.provider)

    def reset(self, tier: str, seed: int) -> None:
        env = self._make(tier, seed)
        with self._lock:
            self.env = env
            self.token = secrets.token_hex(8)
        self.on_reset()

    def tools_spec(self) -> list[dict]:
        return self.env.tools_spec()

    def call(self, name: str, args: Any) -> ToolResult:
        with self._lock:
            try:
                return self.env.call(name, args)
            except Exception:  # never leak internals through an error
                log.exception("env.call raised")
                return ToolResult(False, {}, INTERNAL_ERROR)

    def ledger_payload(self) -> dict:
        with self._lock:
            env = self.env
            if hasattr(env, "verdict"):  # public API (HEAD-ENV)
                out = dict(env.verdict())
            else:
                out = {"score": env.score(), "done": env.done, "end_reason": env._end_reason,
                       "accused": env._accused, "accused_correct": bool(env._correct) if env._accused else False,
                       "final_day": env.day, "V": env.V}
            out.setdefault("tier", env.tier)
            out["episode"] = self.token
            out["ledger"] = [asdict(e) for e in env.ledger()]
            return out


def _token_ok(given: str | None, expected: str | None) -> bool:
    return bool(expected) and given is not None and hmac.compare_digest(given.encode(), expected.encode())


def build_server(ep: Episode) -> Server:
    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
            for t in ep.tools_spec()])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        args = params.arguments if params.arguments is not None else {}
        res = ep.call(params.name, args)
        payload = {"ok": res.ok, "data": res.data, "error": res.error}
        return types.CallToolResult(content=[types.TextContent(type="text", text=json.dumps(payload))],
                                    structured_content=payload, is_error=not res.ok)

    server = Server("canary", instructions=ep.env.instruction(), on_list_tools=list_tools, on_call_tool=call_tool)
    ep.on_reset = lambda: setattr(server, "instructions", ep.env.instruction())  # new sessions see the new tier
    return server


def build_app(ep: Episode, host: str = "127.0.0.1", ledger_token: str | None = None,
              admin_token: str | None = None):
    async def ledger(request: Request):
        if not _token_ok(request.query_params.get("token"), ledger_token):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        return JSONResponse(ep.ledger_payload())

    async def admin_reset(request: Request):
        if not _token_ok(request.query_params.get("token"), admin_token):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        try:
            body = await request.json()
            ep.reset(str(body["tier"]), int(body["seed"]))
        except Exception:  # bad body, unknown tier, or a seed outside the served set
            return JSONResponse({"error": "bad request"}, status_code=400)
        return JSONResponse({"ok": True, "episode": ep.token})

    async def healthz(request: Request):
        return JSONResponse({"ok": True})

    routes = [Route("/ledger", ledger, methods=["GET"]), Route("/admin/reset", admin_reset, methods=["POST"]),
              Route("/healthz", healthz, methods=["GET"])]
    return build_server(ep).streamable_http_app(host=host, custom_starlette_routes=routes)


# --------------------------------------------------------------------------- client side helper
async def play_policy(url: str, policy, max_iters: int = 1000) -> list:
    """Drive a types.Policy against a running server over MCP (used by tests and Harbor's solve.sh)."""
    from mcp import Client

    from .types import Step

    history: list[Step] = []
    day = 1
    async with Client(url) as client:
        tools = (await client.list_tools()).tools
        spec = [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in tools]
        policy.reset(spec, client.instructions or "")
        for _ in range(max_iters):
            tool, args = policy.act(history)
            r = await client.call_tool(tool, args)
            result = json.loads(r.content[0].text)
            history.append(Step(t=len(history), day=day, tool=tool, args=args, result=result))
            data = result.get("data") or {}
            if tool == "advance_day" and result.get("ok"):
                day = data.get("day", day)
            if data.get("episode_over") or result.get("error") == "episode over":
                break
    return history


# --------------------------------------------------------------------------- entrypoint
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mcp_server", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--play", metavar="AGENT", help="client mode: play a baseline/solver against --url")
    ap.add_argument("--url", default=None)
    a = ap.parse_args(argv)
    host = os.environ.get("CANARY_HOST", "127.0.0.1")
    port = int(os.environ.get("CANARY_PORT", "8765"))
    if a.play:
        from .eval import make_policy_factory
        url = a.url or f"http://{host}:{port}/mcp"
        hist = asyncio.run(play_policy(url, make_policy_factory(a.play)(0)))
        print(f"played {len(hist)} tool calls; last: {hist[-1].tool} -> {json.dumps(hist[-1].result)}" if hist else "no calls")
        return 0

    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    try:
        cfg = load_config()
        if cfg["world_secret"] is not None:
            apply_world_secret(cfg["world_secret"])
        tier, ledger_token, admin_token = cfg["tier"], cfg["ledger_token"], cfg["admin_token"]
        ep = Episode(tier, cfg["seed"], os.environ.get("CANARY_PROVIDER", "template"))
    except (SeedNotAllowed, ConfigError, ValueError) as exc:
        print(f"canary.mcp_server: refusing to start: {exc}", file=sys.stderr)
        return 2
    if not ledger_token:
        log.warning("CANARY_LEDGER_TOKEN unset: GET /ledger is disabled (always 403)")
    log.info("canary MCP server: tier=%s episode=%s url=http://%s:%d/mcp", tier, ep.token, host, port)
    uvicorn.run(build_app(ep, host, ledger_token, admin_token), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
