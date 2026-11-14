"""Canary MCP server: one Env episode behind streamable HTTP (CONTRACT §3, §4). Owner: HARNESS.

    python -m canary.mcp_server --write-episode-file $d/episode.json --tier medium --seed 900007 --ledger-token-out $d/ledger_token
    CANARY_EPISODE_FILE=$d/episode.json CANARY_LEDGER_TOKEN_FILE=$d/ledger_token python -m canary.mcp_server

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
read once at startup; CLI file flags and *_FILE vars win over plain counterparts, which are then not needed:
    CANARY_EPISODE_FILE / --episode-file             JSON {"tier": ..., "seed": ...}
    CANARY_WORLD_SECRET_FILE / --world-secret-file   world secret for judge/held-out seeds (handed to canary.world in-process)
    CANARY_LEDGER_TOKEN_FILE / --ledger-token-file   grader token
    CANARY_ADMIN_TOKEN_FILE                          admin token
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
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict
from pathlib import Path
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


def _read_secret_path(path: str | os.PathLike[str], label: str) -> str:
    try:
        mode = os.stat(path).st_mode
        with open(path) as fh:
            text = fh.read().strip()
    except OSError as exc:
        raise ConfigError(f"{label}: cannot read file ({type(exc).__name__})") from None
    if mode & 0o077:
        log.warning("%s is readable by group/others; chmod 600 it", label)
    if not text:
        raise ConfigError(f"{label}: file is empty")
    return text


def _read_file_var(var: str, environ) -> str | None:
    """Contents of the file named by env var `var` (stripped), or None if `var` is unset. Never logs contents."""
    path = environ.get(var)
    if not path:
        return None
    return _read_secret_path(path, var)


def _write_0600_file(path: str | os.PathLike[str], content: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


def write_episode_files(
    episode_file: str | os.PathLike[str],
    tier: str,
    seed: int,
    ledger_token_out: str | os.PathLike[str] | None = None,
    ledger_token: str | None = None,
) -> str | None:
    if not tier or not isinstance(tier, str):
        raise ConfigError("episode tier is required")
    try:
        seed_int = int(seed)
    except (TypeError, ValueError):
        raise ConfigError("episode seed must be an integer") from None
    _write_0600_file(episode_file, json.dumps({"tier": str(tier), "seed": seed_int}) + "\n")
    if ledger_token_out is None:
        return None
    tok = ledger_token or secrets.token_hex(32)
    _write_0600_file(ledger_token_out, tok + "\n")
    return tok


def load_config(
    environ=None,
    episode_file: str | None = None,
    ledger_token_file: str | None = None,
    world_secret_file: str | None = None,
) -> dict:
    """Server config from CLI file flags, 0600 secret files, and/or env vars (files win)."""
    environ = os.environ if environ is None else environ
    tier, seed = environ.get("CANARY_TIER", "easy"), environ.get("CANARY_SEED", "900000")
    ep_label = "--episode-file" if episode_file else "CANARY_EPISODE_FILE"
    ep_text = _read_secret_path(episode_file, ep_label) if episode_file else _read_file_var("CANARY_EPISODE_FILE", environ)
    if ep_text is not None:
        try:
            obj = json.loads(ep_text)
            tier, seed = obj["tier"], obj["seed"]
        except Exception:
            raise ConfigError(f"{ep_label}: expected JSON {{\"tier\": ..., \"seed\": ...}}") from None
    try:
        seed = int(seed)
    except (TypeError, ValueError):
        raise ConfigError("episode seed must be an integer") from None
    secret = (
        _read_secret_path(world_secret_file, "--world-secret-file")
        if world_secret_file
        else _read_file_var("CANARY_WORLD_SECRET_FILE", environ)
    )
    ledger_tok = (
        (_read_secret_path(ledger_token_file, "--ledger-token-file") if ledger_token_file else _read_file_var("CANARY_LEDGER_TOKEN_FILE", environ))
        or environ.get("CANARY_LEDGER_TOKEN")
        or None
    )
    return {"tier": str(tier), "seed": seed,
            "world_secret": secret.encode() if secret is not None else None,
            "ledger_token": ledger_tok,
            "admin_token": _read_file_var("CANARY_ADMIN_TOKEN_FILE", environ) or environ.get("CANARY_ADMIN_TOKEN") or None}


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
    for k in ("CANARY_TIER", "CANARY_SEED", "CANARY_LEDGER_TOKEN", "CANARY_ADMIN_TOKEN", "CANARY_WORLD_SECRET"):
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


STRIPPED_SERVER_ENV = (
    "CANARY_SEED",
    "CANARY_TIER",
    "CANARY_LEDGER_TOKEN",
    "CANARY_WORLD_SECRET",
    "CANARY_ADMIN_TOKEN",
    "CANARY_EPISODE_FILE",
    "CANARY_LEDGER_TOKEN_FILE",
    "CANARY_WORLD_SECRET_FILE",
    "CANARY_ADMIN_TOKEN_FILE",
    "CANARY_ALLOW_DEV",
    "CANARY_HOST",
    "CANARY_PORT",
)


def _free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def spawn_isolated_server(
    tier: str,
    seed: int,
    allow_dev: bool = False,
    host: str = "127.0.0.1",
    port: int = 0,
    world_secret: str | bytes | None = None,
    timeout: float = 30.0,
) -> tuple[subprocess.Popen, dict[str, Any]]:
    tmpdir = Path(tempfile.mkdtemp(prefix="canary-mcp-"))
    try:
        os.chmod(tmpdir, 0o700)
        ep_path = tmpdir / "episode.json"
        tok_path = tmpdir / "ledger_token"
        token = write_episode_files(ep_path, tier, seed, ledger_token_out=tok_path)
        assert token is not None
        ws_path: Path | None = None
        if world_secret is not None:
            ws_path = tmpdir / "world_secret"
            ws_text = world_secret.decode("utf-8") if isinstance(world_secret, (bytes, bytearray)) else str(world_secret)
            _write_0600_file(ws_path, ws_text + "\n")

        actual_port = port or _free_port(host)
        child_env = {k: v for k, v in os.environ.items() if k not in STRIPPED_SERVER_ENV}
        repo_root = str(Path(__file__).resolve().parent.parent)
        py_parts = [p for p in child_env.get("PYTHONPATH", "").split(os.pathsep) if p]
        if repo_root not in py_parts:
            child_env["PYTHONPATH"] = os.pathsep.join([repo_root, *py_parts])
        child_env["CANARY_HOST"] = host
        child_env["CANARY_PORT"] = str(actual_port)
        child_env["CANARY_EPISODE_FILE"] = str(ep_path)
        child_env["CANARY_LEDGER_TOKEN_FILE"] = str(tok_path)
        if ws_path is not None:
            child_env["CANARY_WORLD_SECRET_FILE"] = str(ws_path)
        if allow_dev:
            child_env["CANARY_ALLOW_DEV"] = "1"

        proc = subprocess.Popen(
            [sys.executable, "-m", "canary.mcp_server"],
            cwd=str(tmpdir),
            env=child_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise

    def _stop_proc() -> str:
        err = ""
        if proc.poll() is None:
            proc.terminate()
            try:
                _, err = proc.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                _, err = proc.communicate()
        elif proc.stderr is not None and not proc.stderr.closed:
            try:
                err = proc.stderr.read()
            finally:
                proc.stderr.close()
        return err or ""

    def cleanup() -> None:
        _stop_proc()
        shutil.rmtree(tmpdir, ignore_errors=True)

    base = f"http://{host}:{actual_port}"
    health_url = f"{base}/healthz"
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as resp:
                if resp.status == 200:
                    break
        except Exception:
            pass
        if proc.poll() is not None or time.monotonic() >= deadline:
            err = _stop_proc()[-500:]
            rc = proc.returncode
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(f"canary.mcp_server failed to start (rc={rc}): {err}".strip())
        time.sleep(0.1)

    info: dict[str, Any] = {
        "host": host,
        "port": actual_port,
        "base": base,
        "url": f"{base}/mcp",
        "token": token,
        "cleanup": cleanup,
        "env": dict(child_env),
        "episode_file": str(ep_path),
        "ledger_token_file": str(tok_path),
        "world_secret_file": str(ws_path) if ws_path is not None else None,
    }
    return proc, info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mcp_server", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--play", metavar="AGENT", help="client mode: play a baseline/solver against --url")
    ap.add_argument("--url", default=None)
    ap.add_argument("--episode-file", metavar="PATH", default=None,
                    help="0600 JSON file {\"tier\": ..., \"seed\": ...}")
    ap.add_argument("--ledger-token-file", metavar="PATH", default=None,
                    help="0600 file holding the GET /ledger token")
    ap.add_argument("--world-secret-file", metavar="PATH", default=None,
                    help="0600 file holding the judge world secret (>= 16 bytes)")
    ap.add_argument("--write-episode-file", metavar="PATH", default=None,
                    help="helper mode: write 0600 episode JSON file (and optional token) and exit")
    ap.add_argument("--tier", default=None, help="episode tier (used with --write-episode-file)")
    ap.add_argument("--seed", type=int, default=None, help="episode seed (used with --write-episode-file)")
    ap.add_argument("--ledger-token-out", metavar="PATH", default=None,
                    help="with --write-episode-file: also write a fresh 0600 ledger token file")
    a = ap.parse_args(argv)
    if a.write_episode_file:
        if a.tier is None or a.seed is None:
            print("canary.mcp_server: --write-episode-file requires --tier and --seed", file=sys.stderr)
            return 2
        try:
            write_episode_files(a.write_episode_file, a.tier, a.seed, ledger_token_out=a.ledger_token_out)
        except (ConfigError, OSError, ValueError) as exc:
            msg = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
            print(f"canary.mcp_server: cannot write secret files: {msg}", file=sys.stderr)
            return 2
        return 0
    if a.tier is not None or a.seed is not None or a.ledger_token_out is not None:
        print("canary.mcp_server: refusing to start: --tier, --seed, and --ledger-token-out require --write-episode-file",
              file=sys.stderr)
        return 2
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
        cfg = load_config(
            episode_file=a.episode_file,
            ledger_token_file=a.ledger_token_file,
            world_secret_file=a.world_secret_file,
        )
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
