"""PLUMBING-ONLY fake Canary MCP server (stdlib). NOT the real env.

Used by the hunter (`--server fake`) and tests until canary.mcp_server lands. Implements the
contract surface: JSON-RPC over POST /mcp (initialize, tools/list, tools/call) and
GET /ledger?token=... . Results from runs against it say nothing about the real env.

Run: python -m canary.redteam.fake_mcp  (reads CANARY_HOST/PORT/LEDGER_TOKEN/TIER/SEED)
"""
from __future__ import annotations

import hmac
import json
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOOLS = ["status", "list_employees", "list_documents", "read_access_logs", "search_messages",
         "read_message", "interview", "plant_canary", "check_leak_feed", "restrict_access",
         "unrestrict_access", "advance_day", "accuse"]


class FakeEnv:
    def __init__(self, tier: str = "easy", seed: int = 0):
        rng = random.Random(seed)
        self.n = {"easy": 12, "medium": 20, "hard": 30}[tier]
        self.emps = [f"e{i:02d}" for i in range(self.n)]
        self.mole = rng.choice(self.emps)
        self.day, self.v, self.t, self._done, self._score = 0, 1.0, 0, False, 0.0
        self._ledger = [{"t": 0, "day": 0, "event": "episode_start", "detail": {"mole": self.mole}}]

    def tools_spec(self):
        props = {"accuse": {"employee": {"type": "string"}}, "interview": {"employee": {"type": "string"},
                 "topic": {"type": "string"}}}
        return [{"name": n, "description": f"fake {n}", "input_schema": {"type": "object",
                 "properties": props.get(n, {}), "additionalProperties": False}} for n in TOOLS]

    @property
    def done(self):
        return self._done

    def score(self):
        return self._score

    def ledger(self):
        return list(self._ledger)

    def call(self, tool, args):
        self.t += 1
        if self._done:
            return {"ok": False, "data": {}, "error": "episode over"}
        if tool not in TOOLS or not isinstance(args, dict):
            return {"ok": False, "data": {}, "error": "unknown tool or bad args"}
        if tool == "status":
            return {"ok": True, "data": {"day": self.day, "V": self.v}}
        if tool == "list_employees":
            return {"ok": True, "data": {"employees": [{"id": e} for e in self.emps]}}
        if tool == "advance_day":
            self.day += 1
            self.v = max(0.0, self.v - 0.05)
            if self.day >= 14:
                self._done = True
                self._ledger.append({"t": self.t, "day": self.day, "event": "episode_end", "detail": {"reason": "horizon"}})
            return {"ok": True, "data": {"day": self.day}}
        if tool == "accuse":
            emp = args.get("employee")
            if set(args) != {"employee"} or not isinstance(emp, str) or emp not in self.emps:
                return {"ok": False, "data": {}, "error": "invalid employee"}
            self._done = True
            correct = emp == self.mole
            self._score = self.v if correct else 0.0
            self._ledger.append({"t": self.t, "day": self.day, "event": "accused",
                                 "detail": {"employee": emp, "correct": correct, "score": self._score}})
            return {"ok": True, "data": {"accused": emp, "episode_over": True}}
        return {"ok": True, "data": {}}


class EnvShim:
    """Real canary.env.Env behind the fake transport (`--server envshim`): real game logic,
    NOT the real canary.mcp_server transport/locking."""

    def __init__(self, tier: str, seed: int):
        from canary.env import Env
        self.env = Env(tier=tier, seed=seed)

    def tools_spec(self):
        return self.env.tools_spec()

    @property
    def done(self):
        return self.env.done

    def score(self):
        return self.env.score()

    def ledger(self):
        from dataclasses import asdict
        return [asdict(e) for e in self.env.ledger()]

    def call(self, tool, args):
        from dataclasses import asdict
        try:
            return asdict(self.env.call(tool, args))
        except Exception as e:  # noqa: BLE001  surfaced as a finding (crash), not swallowed silently
            return {"ok": False, "data": {}, "error": f"server exception {type(e).__name__}"}


def make_server(host: str, port: int, token: str, env: FakeEnv) -> ThreadingHTTPServer:
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, obj=None, extra=None):
            body = b"" if obj is None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/ledger":
                got = parse_qs(u.query).get("token", [""])[0]
                if not hmac.compare_digest(got.encode(), token.encode()):
                    return self._send(403, {"error": "forbidden"})
                with lock:
                    return self._send(200, {"score": env.score(), "done": env.done, "ledger": env.ledger()})
            self._send(405 if u.path == "/mcp" else 404, {"error": "no"})

        def do_DELETE(self):
            self._send(200, {})

        def do_POST(self):
            if urlparse(self.path).path != "/mcp":
                return self._send(404, {"error": "no"})
            try:
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            except Exception:
                return self._send(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse"}})
            if "id" not in msg:
                return self._send(202)
            m, mid, p = msg.get("method"), msg["id"], msg.get("params") or {}
            if m == "initialize":
                res = {"protocolVersion": p.get("protocolVersion", "2025-06-18"), "capabilities": {"tools": {}},
                       "serverInfo": {"name": "canary-fake", "version": "0"}}
                return self._send(200, {"jsonrpc": "2.0", "id": mid, "result": res}, {"Mcp-Session-Id": "fake"})
            if m == "tools/list":
                tools = [{"name": t["name"], "description": t["description"], "inputSchema": t["input_schema"]}
                         for t in env.tools_spec()]
                return self._send(200, {"jsonrpc": "2.0", "id": mid, "result": {"tools": tools}})
            if m == "tools/call":
                with lock:
                    r = env.call(p.get("name"), p.get("arguments") or {})
                res = {"content": [{"type": "text", "text": json.dumps(r)}], "isError": not r["ok"]}
                return self._send(200, {"jsonrpc": "2.0", "id": mid, "result": res})
            if m == "ping":
                return self._send(200, {"jsonrpc": "2.0", "id": mid, "result": {}})
            self._send(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})

    return ThreadingHTTPServer((host, port), H)


def main():
    e = os.environ
    cls = EnvShim if e.get("CANARY_FAKE_BACKEND") == "env" else FakeEnv
    env = cls(e.get("CANARY_TIER", "easy"), int(e.get("CANARY_SEED", "0")))
    srv = make_server(e.get("CANARY_HOST", "127.0.0.1"), int(e["CANARY_PORT"]), e["CANARY_LEDGER_TOKEN"], env)
    srv.serve_forever()


if __name__ == "__main__":
    main()
