"""Keyless tests for canary.gemini.gateway: a fake upstream (stdlib HTTP server) stands in for Google."""
from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx2")
uvicorn = pytest.importorskip("uvicorn")

from canary.gemini.gateway import Gateway, load_key, load_tokens, request_key  # noqa: E402

REAL = "REAL-KEY-PLACEHOLDER-0123456789"
TOKEN = "tok-" + "a" * 40
OTHER = "tok-" + "b" * 40

GEN_RESPONSE = {
    "candidates": [{"content": {"role": "model", "parts": [
        {"functionCall": {"name": "lookup", "args": {"q": "mole"}}}]}, "finishReason": "STOP"}],
    "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 3, "totalTokenCount": 14},
    "modelVersion": "gemini-3.1-flash-lite"}


class Upstream:
    """Fake generativelanguage.googleapis.com. Records what it saw; behaviour switchable per test."""

    def __init__(self):
        self.seen: list[dict] = []
        self.delay = 0.0
        self.fail_first = 0
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()
        up = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def _do(self):
                n = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(n) if n else b""
                with up.lock:
                    up.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                    up.active += 1
                    up.max_active = max(up.max_active, up.active)
                    fail = up.fail_first > 0
                    if fail:
                        up.fail_first -= 1
                try:
                    if up.delay:
                        time.sleep(up.delay)
                    if fail:
                        return self._send(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})
                    if "streamGenerateContent" in self.path:
                        chunks = [b'data: {"candidates":[{"content":{"parts":[{"text":"hel"}]}}]}\r\n\r\n',
                                  b'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}\r\n\r\n']
                        self.send_response(200)
                        self.send_header("content-type", "text/event-stream")
                        self.send_header("transfer-encoding", "chunked")
                        self.end_headers()
                        for c in chunks:
                            self.wfile.write(b"%x\r\n%s\r\n" % (len(c), c))
                            self.wfile.flush()
                        self.wfile.write(b"0\r\n\r\n")
                        return
                    if self.path.startswith("/upload/"):
                        self.send_response(200)
                        self.send_header("x-goog-upload-url", f"{up.base}/upload/v1beta/files?upload_id=xyz")
                        self.send_header("content-length", "0")
                        self.end_headers()
                        return
                    self._send(200, GEN_RESPONSE)
                finally:
                    with up.lock:
                        up.active -= 1

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json; charset=UTF-8")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_DELETE = do_PATCH = _do

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class GW:
    def __init__(self, **kw):
        port = _free_port()
        self.gw_kw = kw
        self.box: dict = {}
        self.ready = threading.Event()

        def run():
            async def main():
                gw = Gateway(**kw)
                self.box["gw"] = gw
                cfg = uvicorn.Config(gw, host="127.0.0.1", port=port, log_level="error", lifespan="on")
                srv = uvicorn.Server(cfg)
                srv.install_signal_handlers = lambda: None
                self.box["srv"] = srv
                t = asyncio.create_task(srv.serve())
                while not srv.started:
                    await asyncio.sleep(0.01)
                self.ready.set()
                await t
            asyncio.run(main())

        self.th = threading.Thread(target=run, daemon=True)
        self.th.start()
        assert self.ready.wait(10)
        self.url = f"http://127.0.0.1:{port}"
        self.gw: Gateway = self.box["gw"]

    def close(self):
        self.box["srv"].should_exit = True
        self.th.join(5)


@pytest.fixture
def upstream():
    u = Upstream()
    yield u
    u.close()


def _gw(upstream, tmp_path, **kw):
    base = dict(tokens={TOKEN: "lab", OTHER: "meta"}, real_key=REAL, upstream=upstream.base,
                stats_dir=tmp_path / "stats", backoff_base=0.01, backoff_max=0.05)
    base.update(kw)
    return GW(**base)


def _stats(g, n=1, timeout=5.0):
    """Stats lines are written just after the response is sent: wait for at least n."""
    t = time.time() + timeout
    while True:
        lines = g.gw.stats_path.read_text().splitlines() if g.gw.stats_path.exists() else []
        if len(lines) >= n or time.time() > t:
            return [json.loads(x) for x in lines]
        time.sleep(0.02)


def _gen(url, key=TOKEN, model="gemini-3.1-flash-lite", body=None, via="header"):
    body = body or {"contents": [{"role": "user", "parts": [{"text": "hi"}]}]}
    path = f"/v1beta/models/{model}:generateContent"
    if via == "header":
        return httpx.post(url + path, json=body, headers={"x-goog-api-key": key} if key else {}, timeout=10)
    return httpx.post(url + path + f"?key={key}", json=body, timeout=10)


def test_auth_rejects_missing_and_wrong_token(upstream, tmp_path):
    g = _gw(upstream, tmp_path)
    try:
        assert _gen(g.url, key=None).status_code == 401
        assert _gen(g.url, key="wrong-token-0000000000000").status_code == 401
        assert _gen(g.url, key=REAL).status_code == 401  # even the real key is not a gateway token
        assert upstream.seen == []
        assert httpx.get(g.url + "/healthz").json()["ok"] is True
    finally:
        g.close()


def test_key_swap_header_and_query(upstream, tmp_path):
    g = _gw(upstream, tmp_path)
    try:
        r = _gen(g.url)
        assert r.status_code == 200 and r.json()["candidates"][0]["content"]["parts"][0]["functionCall"]["name"] == "lookup"
        r2 = _gen(g.url, key=OTHER, via="query")
        assert r2.status_code == 200
        for s in upstream.seen:
            hdr = {k.lower(): v for k, v in s["headers"].items()}
            assert hdr["x-goog-api-key"] == REAL
            blob = json.dumps(s["headers"]) + s["path"] + s["body"].decode()
            assert TOKEN not in blob and OTHER not in blob
            assert "key=" not in s["path"]
        stats = _stats(g, 2)
        assert {s["client"] for s in stats} == {"lab", "meta"}
        assert all(s["model"] == "gemini-3.1-flash-lite" and s["op"] == "generateContent" for s in stats)
    finally:
        g.close()


def test_record_then_replay_round_trip(upstream, tmp_path):
    store = tmp_path / "replay"
    body = {"contents": [{"role": "user", "parts": [{"text": "who is the mole?"}]}],
            "tools": [{"functionDeclarations": [{"name": "lookup"}]}]}
    g = _gw(upstream, tmp_path, mode="record", store_dir=store)
    try:
        rec = _gen(g.url, body=body).json()
        _gen(g.url, body=body)  # identical repeat -> stored as <h>.1.json.gz
    finally:
        g.close()
    files = sorted(p.name for p in store.rglob("*.json.gz"))
    assert len(files) == 2 and files[0].count(".") == 3
    for p in store.rglob("*.json.gz"):
        import gzip
        raw = gzip.open(p).read().decode()
        assert REAL not in raw and TOKEN not in raw
    n_up = len(upstream.seen)
    # replay needs no real key and never touches upstream; body key order does not matter
    g2 = _gw(upstream, tmp_path, mode="replay", store_dir=store, real_key=None)
    try:
        shuffled = json.loads(json.dumps(body))
        shuffled = {"tools": shuffled["tools"], "contents": shuffled["contents"]}
        assert _gen(g2.url, body=shuffled).json() == rec
        assert _gen(g2.url, body=body).json() == rec
        assert _gen(g2.url, body=body).status_code == 200  # exhausted -> last recording again
        miss = _gen(g2.url, body={"contents": [{"role": "user", "parts": [{"text": "new"}]}]})
        assert miss.status_code == 404 and miss.json()["error"]["status"] == "NOT_FOUND"
        assert _gen(g2.url, key="nope-nope-nope-nope-nope").status_code == 401
    finally:
        g2.close()
    assert len(upstream.seen) == n_up


def test_request_key_ignores_api_key_and_json_order():
    a = request_key("POST", "/v1beta/models/m:generateContent", [], b'{"a":1,"b":[1,2]}')
    b = request_key("post", "/v1beta/models/m:generateContent", [], b'{"b": [1, 2], "a": 1}')
    c = request_key("POST", "/v1beta/models/m2:generateContent", [], b'{"a":1,"b":[1,2]}')
    assert a == b != c


def test_concurrency_cap_and_queueing(upstream, tmp_path):
    upstream.delay = 0.15
    g = _gw(upstream, tmp_path, max_concurrency=2)
    try:
        with ThreadPoolExecutor(6) as ex:
            rs = list(ex.map(lambda i: _gen(g.url, body={"contents": [{"parts": [{"text": str(i)}]}]}), range(6)))
        assert all(r.status_code == 200 for r in rs)
        assert upstream.max_active <= 2
        stats = _stats(g, 6)
        assert max(s["queued_s"] for s in stats) >= 0.1
    finally:
        g.close()


def test_per_model_limit(upstream, tmp_path):
    upstream.delay = 0.1
    g = _gw(upstream, tmp_path, max_concurrency=8, model_limits={"gemini-4-carbon": 1})
    try:
        with ThreadPoolExecutor(4) as ex:
            list(ex.map(lambda i: _gen(g.url, model="gemini-4-carbon",
                                       body={"contents": [{"parts": [{"text": str(i)}]}]}), range(4)))
        assert upstream.max_active == 1
    finally:
        g.close()


def test_retries_429_with_backoff(upstream, tmp_path):
    upstream.fail_first = 2
    g = _gw(upstream, tmp_path)
    try:
        assert _gen(g.url).status_code == 200
        stats = _stats(g, 1)
        assert stats[-1]["retries"] == 2 and stats[-1]["status"] == 200
    finally:
        g.close()


def test_streaming_sse_relay(upstream, tmp_path):
    g = _gw(upstream, tmp_path)
    try:
        r = httpx.post(g.url + "/v1beta/models/gemini-3.8-flash:streamGenerateContent?alt=sse",
                       json={"contents": []}, headers={"x-goog-api-key": TOKEN}, timeout=10)
        assert r.status_code == 200 and r.text.count("data:") == 2
        assert "alt=sse" in upstream.seen[-1]["path"]
    finally:
        g.close()


def test_upload_url_rewritten_to_gateway(upstream, tmp_path):
    g = _gw(upstream, tmp_path)
    try:
        r = httpx.post(g.url + "/upload/v1beta/files", content=b"\x00\x01binary",
                       headers={"x-goog-api-key": TOKEN, "x-goog-upload-protocol": "resumable"}, timeout=10)
        assert r.status_code == 200
        assert r.headers["x-goog-upload-url"].startswith(g.url + "/upload/v1beta/files")
    finally:
        g.close()


def test_stats_have_no_secrets_or_bodies(upstream, tmp_path):
    g = _gw(upstream, tmp_path)
    try:
        _gen(g.url, body={"contents": [{"parts": [{"text": "SECRET-PROMPT"}]}]})
        _gen(g.url, key="bad-bad-bad-bad-bad-bad")
        _stats(g, 2)
        text = g.gw.stats_path.read_text()
        assert REAL not in text and TOKEN not in text and "SECRET-PROMPT" not in text and "bad-bad" not in text
        assert {"ts", "model", "method", "status", "latency_s", "queued_s", "bytes_in", "bytes_out",
                "retries"} <= set(json.loads(text.splitlines()[0]))
    finally:
        g.close()


def test_token_and_key_files_must_be_private(tmp_path):
    tf = tmp_path / "tok"
    toks = load_tokens(tf)  # created 0600 with one random token
    assert oct(tf.stat().st_mode & 0o777) == "0o600" and len(toks) == 1
    tf.write_text(f"lab {TOKEN}\nmeta {OTHER}\n# c\n")
    assert load_tokens(tf) == {TOKEN: "lab", OTHER: "meta"}
    os.chmod(tf, 0o644)
    with pytest.raises(SystemExit):
        load_tokens(tf)
    kf = tmp_path / "key.env"
    kf.write_text(f'OTHER=1\nGEMINI_API_KEY="{REAL}"\n')
    os.chmod(kf, 0o600)
    assert load_key(kf) == REAL
    os.chmod(kf, 0o640)
    with pytest.raises(SystemExit):
        load_key(kf)


def test_sdk_and_lab_client_go_through_gateway(upstream, tmp_path, monkeypatch):
    pytest.importorskip("google.genai")
    from canary.gemini import lab_client, read_ledger
    from canary.gemini.sdk import gateway_http_options
    g = _gw(upstream, tmp_path)
    try:
        monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
        assert gateway_http_options() is None
        monkeypatch.setenv("GEMINI_GATEWAY_URL", g.url)
        monkeypatch.setenv("GEMINI_GATEWAY_TOKEN", TOKEN)
        monkeypatch.setenv("GEMINI_API_KEY", "")  # no real key on the worker side
        monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
        assert gateway_http_options(5)["base_url"] == g.url
        c = lab_client("gemini:gemini-3.1-flash-lite", feature="test")
        r = c.chat([{"role": "user", "content": "who?"}],
                   tools=[{"name": "lookup", "description": "d", "parameters": {"type": "object", "properties": {}}}])
        assert r.tool_calls and r.tool_calls[0].name == "lookup"
        rows = read_ledger([tmp_path / "ledger.jsonl"])
        assert len(rows) == 1 and rows[0]["in"] == 11
        hdr = {k.lower(): v for k, v in upstream.seen[-1]["headers"].items()}
        assert hdr["x-goog-api-key"] == REAL
    finally:
        g.close()


def test_sdk_token_file(tmp_path, monkeypatch):
    from canary.gemini.sdk import gateway_token
    monkeypatch.delenv("GEMINI_GATEWAY_TOKEN", raising=False)
    f = tmp_path / "t"
    f.write_text(f"lab {TOKEN}\nmeta {OTHER}\n")
    monkeypatch.setenv("GEMINI_GATEWAY_TOKEN_FILE", str(f))
    assert gateway_token() == TOKEN
    monkeypatch.setenv("GEMINI_GATEWAY_CLIENT", "meta")
    assert gateway_token() == OTHER


def test_committed_showcase_replays_keyless(tmp_path):
    """`make lab-replay` in miniature: the committed recording reproduces through a replay gateway, no key."""
    pytest.importorskip("google.genai")
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    store = root / "results" / "gemini" / "replay"
    if not (store / "showcase.json").exists():
        pytest.skip("no committed showcase recording")
    env = {k: v for k, v in os.environ.items() if not k.startswith("GEMINI_")}
    env["GEMINI_API_KEY"] = ""
    r = subprocess.run([sys.executable, "-m", "canary.gemini.with_gateway", "--replay", str(store),
                        "--ledger", str(tmp_path / "ledger.jsonl"), "--",
                        sys.executable, "-m", "canary.gemini.showcase", "--check", str(store / "showcase.json")],
                       cwd=root, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-2000:]
    assert "REPLAY OK" in r.stdout


def test_tcprelay_forwards_to_gateway(upstream, tmp_path):
    """ssh -R fallback piece: a byte relay in front of the gateway keeps auth end to end."""
    from canary.gemini.tcprelay import serve
    g = _gw(upstream, tmp_path)
    port = _free_port()
    gport = int(g.url.rsplit(":", 1)[1])
    th = threading.Thread(target=lambda: asyncio.run(serve(("127.0.0.1", port), ("127.0.0.1", gport), 0.002)),
                          daemon=True)
    th.start()
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            try:
                httpx.get(url + "/healthz", timeout=1)
                break
            except httpx.TransportError:
                time.sleep(0.05)
        assert _gen(url).status_code == 200
        assert _gen(url, key=None).status_code == 401
    finally:
        g.close()


def test_adaptive_limit_halves_on_429_and_regrows():
    from canary.gemini.gateway import AdaptiveLimit

    async def go():
        lim = AdaptiveLimit(8, grow_after=2, cooldown_s=0.0)
        await lim.throttled()
        assert lim.limit == 4
        await lim.throttled()
        await lim.throttled()
        await lim.throttled()
        assert lim.limit == 1
        for _ in range(4):
            await lim.succeeded()
        assert lim.limit == 3
        await lim.acquire()
        await lim.acquire()
        await lim.acquire()
        waiter = asyncio.create_task(lim.acquire())
        await asyncio.sleep(0.01)
        assert not waiter.done()  # at the limit: queued
        await lim.release()
        await asyncio.wait_for(waiter, 1)
    asyncio.run(go())


def test_429_shrinks_model_limit(upstream, tmp_path):
    upstream.fail_first = 1
    g = _gw(upstream, tmp_path, max_concurrency=8)
    try:
        assert _gen(g.url, model="gemini-4-carbon").status_code == 200
        lim = httpx.get(g.url + "/healthz").json()["model_limits"]["gemini-4-carbon"]
        assert lim[0] == 4 and lim[1] == 8
    finally:
        g.close()
