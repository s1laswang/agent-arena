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
    CANARY_LEDGER_KEY           HMAC-SHA256 key: when set, every /ledger payload carries
                                "sig": {"alg": "HMAC-SHA256", "mac": <hex>} over its canonical JSON (sign_ledger).

Secret files (EXPLOITS #25: a same-uid process can read the exec-time environment via /proc/<pid>/environ
or `ps eww`, so judge runs must not put the seed, world secret or tokens in env vars). Each names a 0600 file
read once at startup; a *_FILE var wins over its plain counterpart, which is then not needed:
    CANARY_EPISODE_FILE         JSON {"tier": ..., "seed": ...}
    CANARY_WORLD_SECRET_FILE    world secret for judge/held-out seeds (handed to canary.world in-process)
    CANARY_LEDGER_TOKEN_FILE    grader token
    CANARY_ADMIN_TOKEN_FILE     admin token
    CANARY_LEDGER_KEY_FILE      ledger signing key (Harbor: build-time, sidecar + verifier only; PLAN-95 C1)
The plain env vars keep working for local dev.

CANARY_CONSUME_SECRET_FILES=1 (make mcp, the frontier runner, the hunter; not the Harbor sidecar)
reads those files, deletes them, and re-execs. /proc/<pid>/environ is the block from exec time, so
clearing os.environ cannot remove a path; the re-exec is what drops it. The Harbor sidecar must not
set this flag: collect still reads /run/canary/ledger_token. Mid-episode GET /ledger omits leak events
and true V unless CANARY_LEDGER_LIVE=1.

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
import base64
import hashlib
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
            "admin_token": _read_file_var("CANARY_ADMIN_TOKEN_FILE", environ) or environ.get("CANARY_ADMIN_TOKEN") or None,
            "ledger_key": _read_file_var("CANARY_LEDGER_KEY_FILE", environ) or environ.get("CANARY_LEDGER_KEY") or None}


# Paths a same-uid reader could open out of /proc/<pid>/environ. Values cross a re-exec in an
# anonymous memfd (closed before the server listens), never in the new environ.
SECRET_FILE_VARS = ("CANARY_EPISODE_FILE", "CANARY_WORLD_SECRET_FILE", "CANARY_LEDGER_TOKEN_FILE",
                    "CANARY_ADMIN_TOKEN_FILE", "CANARY_LEDGER_KEY_FILE")
PLAIN_SECRET_VARS = ("CANARY_TIER", "CANARY_SEED", "CANARY_LEDGER_TOKEN", "CANARY_ADMIN_TOKEN",
                     "CANARY_WORLD_SECRET", "CANARY_LEDGER_KEY")
BOOT_FD = 73


def consume_secret_files(environ=None) -> list[str]:
    """Unlink 0600 secret files named by SECRET_FILE_VARS. Returns the vars whose files were removed."""
    environ = os.environ if environ is None else environ
    gone = []
    for var in SECRET_FILE_VARS:
        path = environ.get(var)
        if path and os.path.isfile(path):
            try:
                os.unlink(path)
                gone.append(var)
            except OSError:
                pass
    return gone


def _cfg_to_boot(cfg: dict) -> bytes:
    secret = cfg.get("world_secret")
    payload = {"tier": cfg["tier"], "seed": int(cfg["seed"]),
               "world_secret_b64": base64.b64encode(secret).decode("ascii") if secret else None,
               "ledger_token": cfg.get("ledger_token"), "admin_token": cfg.get("admin_token"),
               "ledger_key": cfg.get("ledger_key")}
    return json.dumps(payload).encode()


def _cfg_from_boot(raw: bytes) -> dict:
    obj = json.loads(raw.decode())
    b64 = obj.get("world_secret_b64")
    return {"tier": str(obj["tier"]), "seed": int(obj["seed"]),
            "world_secret": base64.b64decode(b64) if b64 else None,
            "ledger_token": obj.get("ledger_token"), "admin_token": obj.get("admin_token"),
            "ledger_key": obj.get("ledger_key")}


def _read_boot_fd() -> dict:
    chunks = []
    while True:
        block = os.read(BOOT_FD, 65536)
        if not block:
            break
        chunks.append(block)
    os.close(BOOT_FD)
    return _cfg_from_boot(b"".join(chunks))


def _reexec_without_secret_paths() -> None:
    """Replace this process so the exec-time environment has no secret values and no secret-file paths."""
    try:
        cfg = load_config()
    except (SeedNotAllowed, ConfigError, ValueError) as exc:
        print(f"canary.mcp_server: refusing to start: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    consume_secret_files()
    fd = os.memfd_create("canary-cfg", 0)
    os.write(fd, _cfg_to_boot(cfg))
    os.lseek(fd, 0, os.SEEK_SET)
    if fd != BOOT_FD:
        os.dup2(fd, BOOT_FD)
        os.close(fd)
    os.set_inheritable(BOOT_FD, True)
    drop = set(SECRET_FILE_VARS) | set(PLAIN_SECRET_VARS) | {"CANARY_CONSUME_SECRET_FILES"}
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["CANARY_BOOTSTRAPPED"] = "1"
    override = os.environ.get("CANARY_TIERS_OVERRIDE")
    if override:
        wrapper = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "with_tiers.py")
        argv = [sys.executable, wrapper, override, "-m", "canary.mcp_server", *sys.argv[1:]]
    else:
        argv = [sys.executable, "-m", "canary.mcp_server", *sys.argv[1:]]
    os.execve(sys.executable, argv, env)


def write_secret_files(tier: str, seed: int, ledger_token: str | None = None, directory=None) -> dict[str, str]:
    """Write the episode (and ledger token) to 0600 files in a fresh 0700 dir and return the *_FILE env vars
    to launch the server with. Launchers use this instead of CANARY_TIER/CANARY_SEED/CANARY_LEDGER_TOKEN so the
    seed and token never sit in the server's exec-time environment (/proc/<pid>/environ, `ps eww`; EXPLOITS #27)."""
    import tempfile
    d = directory or tempfile.mkdtemp(prefix="canary-ep-")
    os.chmod(d, 0o700)
    out = {}
    for name, var, text in (("episode.json", "CANARY_EPISODE_FILE", json.dumps({"tier": tier, "seed": int(seed)})),
                            ("ledger_token", "CANARY_LEDGER_TOKEN_FILE", ledger_token)):
        if text is None:
            continue
        path = os.path.join(d, name)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        out[var] = path
    return out


def clean_launch_env(base=None) -> dict[str, str]:
    """os.environ minus the plain episode/token vars (a *_FILE launch must not also carry them)."""
    base = dict(os.environ if base is None else base)
    for k in ("CANARY_TIER", "CANARY_SEED", "CANARY_LEDGER_TOKEN", "CANARY_ADMIN_TOKEN", "CANARY_WORLD_SECRET",
              "CANARY_LEDGER_KEY"):
        base.pop(k, None)
    return base


def apply_world_secret(secret: bytes) -> None:
    """Hand the file secret to world generation in-process (never exported to os.environ / children).
    canary.world checks it before CANARY_WORLD_SECRET and SALT; it must be >= 16 bytes."""
    from .world import set_world_secret
    set_world_secret(secret)


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
            out = dict(env.verdict())  # public server-side outcome (HEAD-ENV)
            out.setdefault("tier", env.tier)
            out["episode"] = self.token
            if not out.get("done") and os.environ.get("CANARY_LEDGER_LIVE") != "1":
                # Mid-episode: a stolen grader token must not show unsurfaced leaks or true V.
                # Score of an unfinished episode is already 0. CANARY_LEDGER_LIVE=1 keeps the full payload.
                for k in ("V", "final_day", "accused", "correct", "accused_correct"):
                    out.pop(k, None)
                out["ledger"] = []
                out["redacted"] = "episode in progress"
                return out
            out["ledger"] = [asdict(e) for e in env.ledger()]
            return out


# --------------------------------------------------------------------------- ledger signing (PLAN-95 C1)
# Defence in depth for the grader: the verifier (harbor/template/tests/test.sh, which re-implements these two
# functions with the stdlib; tests/test_harbor_ledger_sig.py pins them together) accepts a ledger only if its
# "sig" verifies under the build-time key, so a ledger.json forged or edited anywhere between the server and the
# verifier scores 0. The MAC covers every top-level field except "sig" itself.
SIG_ALG = "HMAC-SHA256"


def ledger_canonical(payload: dict) -> bytes:
    body = {k: v for k, v in payload.items() if k != "sig"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def sign_ledger(payload: dict, key: str | bytes) -> dict:
    """payload plus "sig" = HMAC-SHA256(key, canonical JSON of payload without "sig")."""
    k = key.encode() if isinstance(key, str) else key
    mac = hmac.new(k, ledger_canonical(payload), hashlib.sha256).hexdigest()
    return {**{k2: v for k2, v in payload.items() if k2 != "sig"}, "sig": {"alg": SIG_ALG, "mac": mac}}


def verify_ledger(payload, key: str | bytes) -> bool:
    if not isinstance(payload, dict) or not key:
        return False
    sig = payload.get("sig")
    if not isinstance(sig, dict) or sig.get("alg") != SIG_ALG or not isinstance(sig.get("mac"), str):
        return False
    return hmac.compare_digest(sign_ledger(payload, key)["sig"]["mac"], sig["mac"])


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
              admin_token: str | None = None, ledger_key: str | None = None):
    async def ledger(request: Request):
        if not _token_ok(request.query_params.get("token"), ledger_token):
            return JSONResponse({"error": "forbidden"}, status_code=403)
        payload = ep.ledger_payload()
        return JSONResponse(sign_ledger(payload, ledger_key) if ledger_key else payload)

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
        if os.environ.get("CANARY_BOOTSTRAPPED") == "1":
            cfg = _read_boot_fd()
        elif os.environ.get("CANARY_CONSUME_SECRET_FILES") == "1":
            _reexec_without_secret_paths()  # does not return
            cfg = {}
        else:
            cfg = load_config()
        if cfg["world_secret"] is not None:
            apply_world_secret(cfg["world_secret"])
        tier, ledger_token, admin_token, ledger_key = cfg["tier"], cfg["ledger_token"], cfg["admin_token"], cfg["ledger_key"]
        ep = Episode(tier, cfg["seed"], os.environ.get("CANARY_PROVIDER", "template"))
    except (SeedNotAllowed, ConfigError, ValueError) as exc:
        print(f"canary.mcp_server: refusing to start: {exc}", file=sys.stderr)
        return 2
    if not ledger_token:
        log.warning("CANARY_LEDGER_TOKEN unset: GET /ledger is disabled (always 403)")
    log.info("ledger signing: %s", "HMAC-SHA256" if ledger_key else "off (CANARY_LEDGER_KEY[_FILE] unset)")
    log.info("canary MCP server: tier=%s episode=%s url=http://%s:%d/mcp", tier, ep.token, host, port)
    uvicorn.run(build_app(ep, host, ledger_token, admin_token, ledger_key), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
