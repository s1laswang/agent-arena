"""Canary Lab Gemini gateway: a token-guarded relay for the Gemini REST API with record/replay.

    python -m canary.gemini.gateway --host 0.0.0.0 --port 8787 [--record DIR | --replay DIR]
        [--max-concurrency 64] [--model-limit gemini-4-carbon=8 ...] [--max-hours 8]

Why: FR8 compute nodes have no internet. Workers point google-genai at this relay
(`GEMINI_GATEWAY_URL`, see canary/gemini/sdk.py) and send a *gateway token* as their API key.
The gateway checks the token, swaps in the real key server-side and forwards to
https://generativelanguage.googleapis.com. Compute nodes never see the key.

Relays everything under /v1beta, /v1, /v1alpha and /upload (generateContent, streamGenerateContent
incl. alt=sse, countTokens, embedContent, caches, files incl. resumable upload, batches, models).
Not relayed: the Live API (WebSocket bidiGenerateContent).

Rate limiting: a global in-flight cap plus a per-model cap (--per-model, --model-limit M=N); requests beyond it
  queue. The per-model cap adapts (AIMD): halved on an upstream 429, +1 per 20 successes back up to the cap.
  429/5xx/transport errors are retried with exponential backoff + jitter (Retry-After honoured).
Security:
- every request needs a valid token (`x-goog-api-key` header or `key=` query param); tokens come from a
  0600 file (one token per line, or `name token` lines for per-client tokens). Anything else -> 401.
- the real key is read inside the process from a 0600 file (--key-file, default .env, var GEMINI_API_KEY).
  It never appears on argv, in logs, in stats or in recorded files.
Stats: one JSON line per request in --stats-dir (default data/gemini/gateway/stats-<host>-<pid>.jsonl):
  {ts, client, model, method, op, status, latency_s, queued_s, bytes_in, bytes_out, retries, mode, cache}.
  No bodies, no keys. Clients write the usage ledger themselves (no double counting).
Record/replay: key = sha256([x-canary-replay-tag] + method + path-without-key + canonical JSON body). --record forwards and stores
  <DIR>/<h[:2]>/<h>.json.gz (repeat identical requests -> <h>.1.json.gz, ...); --replay serves them in order
  (the last one again once exhausted) and answers 404 on a miss. Replay needs no real key.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import gzip
import hashlib
import hmac
import json
import os
import random
import re
import secrets
import signal
import socket
import stat
import sys
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

ROOT = Path(__file__).resolve().parents[2]
UPSTREAM = "https://generativelanguage.googleapis.com"
DEFAULT_TOKEN_FILE = Path(os.path.expanduser("~/agent-arena-gemini/.gateway_token"))
PREFIXES = ("/v1beta/", "/v1/", "/v1alpha/", "/upload/")
RETRY_STATUS = {429, 500, 502, 503, 504}
HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
       "proxy-authorization", "proxy-authenticate", "accept-encoding", "x-goog-api-key", "authorization",
       "x-canary-replay-tag"}
REPLAY_TAG = "x-canary-replay-tag"  # optional client label (e.g. one ladder episode) folded into the replay key
RESP_DROP = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive",
             "alt-svc", "server", "date"}
_MODEL_RE = re.compile(r"/(?:tunedModels|models)/([^/:?]+)")
_OP_RE = re.compile(r":([A-Za-z]+)$")


# ----------------------------------------------------------------------------------------- helpers
def _check_private(path: Path) -> None:
    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise SystemExit(f"gateway: {path} must be private (chmod 600); it is {oct(mode & 0o777)}")


def load_tokens(path: Path, create: bool = True) -> dict[str, str]:
    """token -> client name. File: one token per line (name 'default') or `name token` lines; '#' comments."""
    if not path.exists():
        if not create:
            raise SystemExit(f"gateway: token file {path} missing")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_urlsafe(32) + "\n")
    _check_private(path)
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        name, tok = (parts[0], parts[1]) if len(parts) >= 2 else ("default", parts[0])
        if len(tok) < 16:
            raise SystemExit(f"gateway: token for {name!r} in {path} is too short (>=16 chars)")
        out[tok] = name
    if not out:
        raise SystemExit(f"gateway: no tokens in {path}")
    return out


def load_key(path: Path, var: str = "GEMINI_API_KEY") -> str:
    """Read the real key from a dotenv-style file inside the process (never argv / printed env)."""
    if not path.exists():
        raise SystemExit(f"gateway: key file {path} missing (needs {var}=...)")
    _check_private(path)
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        k, sep, v = line.partition("=")
        if sep and k.strip() == var:
            v = v.strip().strip('"').strip("'")
            if v:
                return v
    raise SystemExit(f"gateway: {var} not found in {path}")


def strip_key(query: str) -> list[tuple[str, str]]:
    return [(k, v) for k, v in parse_qsl(query, keep_blank_values=True) if k != "key"]


def canonical_body(body: bytes) -> bytes:
    if not body:
        return b""
    try:
        return json.dumps(json.loads(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    except (ValueError, UnicodeDecodeError):
        return body


def request_key(method: str, path: str, query: list[tuple[str, str]], body: bytes, tag: str = "") -> str:
    """Identical requests from different episodes (e.g. the first turn of every seed) are told apart by `tag`."""
    q = urlencode(sorted(query))
    h = hashlib.sha256()
    if tag:
        h.update(f"tag:{tag}\n".encode())
    h.update(f"{method.upper()}\n{path}?{q}\n".encode())
    h.update(canonical_body(body))
    return h.hexdigest()


def model_of(path: str) -> str:
    m = _MODEL_RE.search(path)
    return m.group(1) if m else "-"


def op_of(path: str) -> str:
    m = _OP_RE.search(path)
    if m:
        return m.group(1)
    seg = [s for s in path.split("/") if s]
    return seg[1] if len(seg) > 1 else (seg[0] if seg else "-")


def is_stream(path: str, query: list[tuple[str, str]]) -> bool:
    return path.endswith(":streamGenerateContent") or ("alt", "sse") in query


class ReplayStore:
    """Sharded gzip files: <dir>/<h[:2]>/<h>.json.gz, then <h>.1.json.gz, ... for repeats."""

    def __init__(self, root: Path):
        self.root = root
        self.counts: dict[str, int] = {}
        self.lock = asyncio.Lock()

    def _path(self, h: str, i: int) -> Path:
        return self.root / h[:2] / (f"{h}.json.gz" if i == 0 else f"{h}.{i}.json.gz")

    async def put(self, h: str, entry: dict) -> Path:
        async with self.lock:
            i = 0
            while self._path(h, i).exists():
                i += 1
            p = self._path(h, i)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            with gzip.open(tmp, "wt", compresslevel=9) as f:
                json.dump(entry, f, separators=(",", ":"), sort_keys=True)
            os.replace(tmp, p)
            return p

    async def get(self, h: str) -> dict | None:
        async with self.lock:
            i = self.counts.get(h, 0)
            p = self._path(h, i)
            if not p.exists():
                if i == 0:
                    return None
                p = self._path(h, i - 1)  # exhausted: keep serving the last recording
            else:
                self.counts[h] = i + 1
        with gzip.open(p, "rt") as f:
            return json.load(f)


def encode_body(b: bytes) -> dict:
    try:
        return {"body": b.decode("utf-8")}
    except UnicodeDecodeError:
        return {"body_b64": base64.b64encode(b).decode()}


def decode_body(e: dict) -> bytes:
    return base64.b64decode(e["body_b64"]) if "body_b64" in e else e.get("body", "").encode("utf-8")


class AdaptiveLimit:
    """Per-model concurrency limit with AIMD: halve on an upstream 429 (at most once per `cooldown_s`),
    +1 after every `grow_after` successes, never above the configured cap or below 1."""

    def __init__(self, cap: int, grow_after: int = 20, cooldown_s: float = 5.0):
        self.cap = self.limit = max(1, cap)
        self.inflight = 0
        self.ok_streak = 0
        self.grow_after, self.cooldown_s = grow_after, cooldown_s
        self.last_cut = 0.0
        self.cond = asyncio.Condition()

    async def acquire(self) -> None:
        async with self.cond:
            await self.cond.wait_for(lambda: self.inflight < self.limit)
            self.inflight += 1

    async def release(self) -> None:
        async with self.cond:
            self.inflight -= 1
            self.cond.notify_all()

    async def throttled(self) -> None:
        now = time.time()
        if now - self.last_cut >= self.cooldown_s:
            self.limit = max(1, self.limit // 2)
            self.last_cut, self.ok_streak = now, 0

    async def succeeded(self) -> None:
        self.ok_streak += 1
        if self.limit < self.cap and self.ok_streak >= self.grow_after:
            async with self.cond:
                self.limit += 1
                self.ok_streak = 0
                self.cond.notify_all()


# ----------------------------------------------------------------------------------------- gateway
class Gateway:
    def __init__(self, tokens: dict[str, str], real_key: str | None, upstream: str = UPSTREAM,
                 mode: str = "live", store_dir: Path | None = None, max_concurrency: int = 64,
                 per_model: int | None = None, model_limits: dict[str, int] | None = None,
                 max_retries: int = 5, backoff_base: float = 1.0, backoff_max: float = 60.0,
                 stats_dir: Path | None = None, upstream_timeout_s: float = 900.0):
        if mode not in ("live", "record", "replay"):
            raise ValueError(mode)
        if mode != "replay" and not real_key:
            raise SystemExit("gateway: a real key is required unless --replay")
        self.tokens, self._key, self.upstream = tokens, real_key, upstream.rstrip("/")
        self.mode = mode
        self.store = ReplayStore(store_dir) if store_dir else None
        if mode != "live" and self.store is None:
            raise ValueError("record/replay need a store dir")
        self.global_sem = asyncio.Semaphore(max_concurrency)
        self.max_concurrency = max_concurrency
        self.per_model = per_model or max_concurrency
        self.model_limits = dict(model_limits or {})
        self.model_sems: dict[str, AdaptiveLimit] = {}
        self.max_retries, self.backoff_base, self.backoff_max = max_retries, backoff_base, backoff_max
        self.inflight = 0
        self.waiting = 0
        self.served = 0
        self.started = time.time()
        stats_dir = stats_dir or (ROOT / "data" / "gemini" / "gateway")
        stats_dir.mkdir(parents=True, exist_ok=True)
        self.stats_path = stats_dir / f"stats-{socket.gethostname().split('.')[0]}-{os.getpid()}.jsonl"
        self.client = None
        self.upstream_timeout_s = upstream_timeout_s

    def _http(self):
        if self.client is None:
            import httpx2 as httpx
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.upstream_timeout_s, connect=30.0),
                limits=httpx.Limits(max_connections=self.max_concurrency + 8,
                                    max_keepalive_connections=self.max_concurrency),
                trust_env=True)
        return self.client

    def _model_sem(self, model: str) -> AdaptiveLimit:
        s = self.model_sems.get(model)
        if s is None:
            s = self.model_sems[model] = AdaptiveLimit(self.model_limits.get(model, self.per_model))
        return s

    def auth(self, headers: dict[str, str], query: list[tuple[str, str]]) -> str | None:
        cand = headers.get("x-goog-api-key") or next((v for k, v in query if k == "key"), None)
        if not cand:
            return None
        for tok, name in self.tokens.items():
            if hmac.compare_digest(cand.encode(), tok.encode()):
                return name
        return None

    def stat(self, **row) -> None:
        row = {"ts": round(time.time(), 3), **row}
        with open(self.stats_path, "a") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    def _sleep_s(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.backoff_max)
            except ValueError:
                pass
        return min(self.backoff_max, self.backoff_base * (2 ** attempt)) * (0.5 + random.random() / 2)

    # ---- ASGI
    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    if self.client is not None:
                        await self.client.aclose()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return  # websockets (Live API) are not relayed
        await self.handle(scope, receive, send)

    async def handle(self, scope, receive, send):
        t0 = time.time()
        method, path = scope["method"], scope["path"]
        query_raw = scope.get("query_string", b"").decode("latin-1")
        query_all = parse_qsl(query_raw, keep_blank_values=True)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        if path in ("/healthz", "/health"):
            return await self._json(send, 200, {"ok": True, "mode": self.mode, "inflight": self.inflight,
                                                "waiting": self.waiting, "served": self.served,
                                                "model_limits": {m: [lim.limit, lim.cap, lim.inflight]
                                                                 for m, lim in self.model_sems.items()},
                                                "uptime_s": round(t0 - self.started)})
        client = self.auth(headers, query_all)
        if client is None:
            self.stat(client="-", model=model_of(path), method=method, op=op_of(path), status=401,
                      latency_s=0.0, queued_s=0.0, bytes_in=0, bytes_out=0, retries=0, mode=self.mode,
                      peer=(scope.get("client") or ["-"])[0])
            return await self._error(send, 401, "UNAUTHENTICATED", "gateway: missing or invalid gateway token")
        if not path.startswith(PREFIXES):
            return await self._error(send, 404, "NOT_FOUND", f"gateway: path {path} is not relayed")
        body = bytearray()
        while True:
            msg = await receive()
            body += msg.get("body", b"")
            if not msg.get("more_body"):
                break
        body = bytes(body)
        query = strip_key(query_raw)
        model, op = model_of(path), op_of(path)
        rkey = request_key(method, path, query, body, headers.get(REPLAY_TAG, ""))
        base = dict(client=client, model=model, method=method, op=op, bytes_in=len(body), mode=self.mode)

        if self.mode == "replay":
            e = await self.store.get(rkey)
            if e is None:
                self.stat(**base, status=404, latency_s=round(time.time() - t0, 4), queued_s=0.0,
                          bytes_out=0, retries=0, cache="miss")
                return await self._error(send, 404, "NOT_FOUND",
                                         f"gateway replay miss for {method} {path} (key {rkey[:16]})")
            out = decode_body(e)
            await send({"type": "http.response.start", "status": e["status"],
                        "headers": [(k.encode(), v.encode()) for k, v in e.get("headers", {}).items()]})
            await send({"type": "http.response.body", "body": out})
            self.served += 1
            self.stat(**base, status=e["status"], latency_s=round(time.time() - t0, 4), queued_s=0.0,
                      bytes_out=len(out), retries=0, cache="hit")
            return

        # live / record: queue for a slot, then forward with retries
        self.waiting += 1
        msem = self._model_sem(model)
        try:  # model slot first, so a throttled model waits without holding global slots
            await msem.acquire()
            try:
                await self.global_sem.acquire()
            except BaseException:
                await msem.release()
                raise
        finally:
            self.waiting -= 1
        queued_s = time.time() - t0
        self.inflight += 1
        try:
            await self._forward(scope, send, method, path, query, headers, body, rkey, base, t0, queued_s, msem)
        finally:
            self.inflight -= 1
            await msem.release()
            self.global_sem.release()

    async def _forward(self, scope, send, method, path, query, headers, body, rkey, base, t0, queued_s, limiter):
        import httpx2 as httpx
        fwd_headers = [(k, v) for k, v in headers.items() if k not in HOP and not k.startswith("x-forwarded")]
        fwd_headers.append(("x-goog-api-key", self._key))
        url = self.upstream + path + (("?" + urlencode(query)) if query else "")
        stream = is_stream(path, query)
        retries, resp = 0, None
        http = self._http()
        while True:
            req = http.build_request(method, url, content=body or None, headers=fwd_headers)
            try:
                resp = await http.send(req, stream=True)
            except (httpx.TransportError, httpx.TimeoutException) as ex:
                if retries < self.max_retries:
                    await asyncio.sleep(self._sleep_s(retries, None))
                    retries += 1
                    continue
                self.stat(**base, status=502, latency_s=round(time.time() - t0, 3), queued_s=round(queued_s, 3),
                          bytes_out=0, retries=retries, error=type(ex).__name__)
                return await self._error(send, 502, "UNAVAILABLE", f"gateway: upstream {type(ex).__name__}")
            if resp.status_code == 429:
                await limiter.throttled()
            if resp.status_code in RETRY_STATUS and retries < self.max_retries:
                ra = resp.headers.get("retry-after")
                await resp.aread()
                await resp.aclose()
                await asyncio.sleep(self._sleep_s(retries, ra))
                retries += 1
                continue
            break

        own_base = self._own_base(scope, headers)
        out_headers = {}
        for k, v in resp.headers.items():
            kl = k.lower()
            if kl in RESP_DROP:
                continue
            if kl == "x-goog-upload-url" or kl == "location":
                v = v.replace(self.upstream, own_base)  # resumable uploads continue through the gateway
            out_headers[kl] = v
        await send({"type": "http.response.start", "status": resp.status_code,
                    "headers": [(k.encode("latin-1"), v.encode("latin-1")) for k, v in out_headers.items()]})
        chunks: list[bytes] = []
        nout = 0
        try:
            if stream:
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    nout += len(chunk)
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})
                await send({"type": "http.response.body", "body": b""})
            else:
                data = await resp.aread()
                chunks.append(data)
                nout = len(data)
                await send({"type": "http.response.body", "body": data})
        finally:
            await resp.aclose()
        self.served += 1
        if resp.status_code < 400:
            await limiter.succeeded()
        cache = None
        if self.mode == "record" and resp.status_code < 500 and resp.status_code != 429:
            # recorded response headers: content-type + upload headers only (never anything secret)
            keep = {k: v for k, v in out_headers.items() if k == "content-type" or k.startswith("x-goog-upload")}
            await self.store.put(rkey, {"status": resp.status_code, "headers": keep, "stream": stream,
                                        "method": method, "path": path, "model": base["model"],
                                        "ts": round(time.time(), 3), **encode_body(b"".join(chunks))})
            cache = "stored"
        self.stat(**base, status=resp.status_code, latency_s=round(time.time() - t0, 3),
                  queued_s=round(queued_s, 3), bytes_out=nout, retries=retries, **({"cache": cache} if cache else {}))

    @staticmethod
    def _own_base(scope, headers) -> str:
        host = headers.get("host")
        if not host:
            h, p = scope.get("server") or ("127.0.0.1", 80)
            host = f"{h}:{p}"
        return f"{scope.get('scheme', 'http')}://{host}"

    @staticmethod
    async def _json(send, status: int, obj: dict):
        data = json.dumps(obj).encode()
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json; charset=UTF-8")]})
        await send({"type": "http.response.body", "body": data})

    async def _error(self, send, code: int, status: str, message: str):
        await self._json(send, code, {"error": {"code": code, "message": message, "status": status}})


# ----------------------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.gateway", description=__doc__.split("\n\n")[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    g = p.add_mutually_exclusive_group()
    g.add_argument("--record", type=Path, metavar="DIR", help="forward and store every response in DIR")
    g.add_argument("--replay", type=Path, metavar="DIR", help="serve stored responses; 404 on a miss (no key needed)")
    p.add_argument("--max-concurrency", type=int, default=64, help="global in-flight cap (rest queue)")
    p.add_argument("--per-model", type=int, default=None, help="default per-model cap (default = global)")
    p.add_argument("--model-limit", action="append", default=[], metavar="MODEL=N",
                   help="per-model cap override, e.g. gemini-4-carbon=8 (repeatable)")
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--token-file", type=Path,
                   default=Path(os.environ.get("GEMINI_GATEWAY_TOKEN_FILE") or DEFAULT_TOKEN_FILE),
                   help="0600 file: one token per line or `name token` lines (created if missing)")
    p.add_argument("--key-file", type=Path, default=ROOT / ".env", help="0600 dotenv file with GEMINI_API_KEY")
    p.add_argument("--upstream", default=os.environ.get("GEMINI_GATEWAY_UPSTREAM", UPSTREAM))
    p.add_argument("--stats-dir", type=Path, default=ROOT / "data" / "gemini" / "gateway")
    p.add_argument("--max-hours", type=float, default=8.0, help="hard self-exit after this many hours (0 = never)")
    p.add_argument("--pidfile", type=Path, default=None)
    return p


async def _serve(args, gw: Gateway) -> None:
    import uvicorn
    cfg = uvicorn.Config(gw, host=args.host, port=args.port, log_level="warning", access_log=False,
                         lifespan="on", timeout_keep_alive=75, server_header=False, date_header=False)
    class _Server(uvicorn.Server):
        @contextlib.contextmanager
        def capture_signals(self):  # we stop gracefully ourselves (so the pidfile is cleaned up)
            yield

    server = _Server(cfg)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):  # not SIGHUP: survive the ssh session (nohup)
        try:
            loop.add_signal_handler(sig, lambda: setattr(server, "should_exit", True))
        except (NotImplementedError, RuntimeError):
            pass

    async def deadline():
        if args.max_hours and args.max_hours > 0:
            await asyncio.sleep(args.max_hours * 3600)
            print(f"gateway: --max-hours {args.max_hours} reached, exiting", flush=True)
            server.should_exit = True
    task = asyncio.create_task(deadline())
    try:
        await server.serve()
    finally:
        task.cancel()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    mode = "record" if args.record else "replay" if args.replay else "live"
    tokens = load_tokens(args.token_file)
    key = None if mode == "replay" else load_key(args.key_file)
    limits = {}
    for s in args.model_limit:
        m, _, n = s.partition("=")
        limits[m.strip()] = int(n)

    async def run():
        gw = Gateway(tokens, key, upstream=args.upstream, mode=mode, store_dir=args.record or args.replay,
                     max_concurrency=args.max_concurrency, per_model=args.per_model, model_limits=limits,
                     max_retries=args.max_retries, stats_dir=args.stats_dir)
        print(f"gateway: {mode} on http://{args.host}:{args.port} -> "
              f"{'store ' + str(args.replay) if mode == 'replay' else args.upstream} | clients={len(tokens)} "
              f"max_concurrency={args.max_concurrency} limits={limits or '-'} stats={gw.stats_path} "
              f"max_hours={args.max_hours}", flush=True)
        await _serve(args, gw)

    if args.pidfile:
        args.pidfile.parent.mkdir(parents=True, exist_ok=True)
        args.pidfile.write_text(f"{os.getpid()}\n")
    try:
        asyncio.run(run())  # uvicorn handles SIGINT/SIGTERM gracefully
    except KeyboardInterrupt:
        pass
    finally:
        if args.pidfile and args.pidfile.exists() and args.pidfile.read_text().strip() == str(os.getpid()):
            args.pidfile.unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
