#!/usr/bin/env python3
"""Hunt 1 — black-box HTTP only.

Does not import canary.env / canary.world / canary.solver. Talks to whatever
is listening via JSON-RPC POST /mcp and GET /ledger.

The official entry point is `python -m canary.mcp_server` (`make mcp`). If that
module is missing, the script starts the only local HTTP stand-in that serves
the real game:
  CANARY_FAKE_BACKEND=env python -m canary.redteam.fake_mcp
and labels every result with which server answered.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "hunt1_results.json"
TOKEN = os.environ.get("CANARY_HUNT_TOKEN") or __import__("secrets").token_hex(16)
HOST = "127.0.0.1"


def redact(s: str) -> str:
    return s.replace(TOKEN, "<redacted>")


def free_port() -> int:
    s = socket.socket()
    s.bind((HOST, 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Server:
    def __init__(self, tier: str, seed: int, backend_env: bool):
        self.tier, self.seed = tier, seed
        self.port = free_port()
        self.base = f"http://{HOST}:{self.port}"
        env = os.environ.copy()
        env.update({
            "CANARY_HOST": HOST,
            "CANARY_PORT": str(self.port),
            "CANARY_LEDGER_TOKEN": TOKEN,
            "CANARY_TIER": tier,
            "CANARY_SEED": str(seed),
        })
        if backend_env:
            env["CANARY_FAKE_BACKEND"] = "env"
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "canary.redteam.fake_mcp"],
            cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self._wait()

    def _wait(self):
        deadline = time.time() + 10
        last = ""
        while time.time() < deadline:
            code, body, _ = http("GET", f"{self.base}/ledger?token={TOKEN}")
            if code == 200:
                return
            last = f"{code} {body[:120]}"
            if self.proc.poll() is not None:
                err = self.proc.stdout.read().decode(errors="replace")[:500] if self.proc.stdout else ""
                raise RuntimeError(f"server exited {self.proc.returncode}: {err}")
            time.sleep(0.05)
        raise RuntimeError(f"server did not become ready: {last}")

    def stop(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def http(method: str, url: str, body: dict | list | None = None, headers: dict | None = None, timeout: float = 10.0):
    data = None if body is None else json.dumps(body).encode()
    h = {"Accept": "application/json, text/event-stream"}
    if data is not None:
        h["Content-Type"] = "application/json"
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            dt = time.perf_counter() - t0
            return r.status, raw.decode(errors="replace"), dt
    except urllib.error.HTTPError as e:
        dt = time.perf_counter() - t0
        return e.code, e.read().decode(errors="replace"), dt
    except Exception as e:  # noqa: BLE001
        dt = time.perf_counter() - t0
        return 0, f"{type(e).__name__}: {e}", dt


class MCP:
    def __init__(self, base: str):
        self.url = base + "/mcp"
        self.sid = None
        self.n = 0

    def post(self, payload: dict | list):
        h = {"MCP-Protocol-Version": "2025-06-18"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        code, body, dt = http("POST", self.url, payload, h)
        # session id is not exposed by urllib on HTTPError easily; re-read via a small custom path
        return code, body, dt

    def request(self, method: str, params: dict | None = None):
        self.n += 1
        payload = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        # use a raw opener so we can see Mcp-Session-Id
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-06-18"}
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(self.url, json.dumps(payload).encode(), h, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                sid = r.headers.get("Mcp-Session-Id")
                if sid:
                    self.sid = sid
                raw = r.read().decode()
                code = r.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            code = e.code
        dt = time.perf_counter() - t0
        try:
            msg = json.loads(raw) if raw.strip() else None
        except json.JSONDecodeError:
            msg = {"_raw": raw[:500]}
        return {"code": code, "dt_s": round(dt, 4), "bytes": len(raw), "msg": msg, "body_prefix": raw[:400]}

    def init(self):
        res = self.request("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                          "clientInfo": {"name": "hunt1", "version": "0"}})
        # notification
        http("POST", self.url, {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"MCP-Protocol-Version": "2025-06-18", **({"Mcp-Session-Id": self.sid} if self.sid else {})})
        return res

    def call(self, name: str, args: dict | None = None):
        res = self.request("tools/call", {"name": name, "arguments": args if args is not None else {}})
        msg = res.get("msg") or {}
        result = (msg.get("result") or {}) if isinstance(msg, dict) else {}
        text = ""
        if isinstance(result, dict):
            text = "".join(c.get("text", "") for c in result.get("content", []) if isinstance(c, dict))
        try:
            payload = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = {"_text": text[:500]}
        res["payload"] = payload
        res["text_bytes"] = len(text)
        return res


def ledger(base: str, query: str):
    code, body, dt = http("GET", f"{base}/ledger{query}")
    return {"code": code, "bytes": len(body), "dt_s": round(dt, 4), "body": redact(body[:1500])}


def payload_ok(res):
    p = res.get("payload")
    return p if isinstance(p, dict) else {}


def main():
    report: dict = {"server": None, "probes": []}
    # 0. official module
    imp = subprocess.run([sys.executable, "-c", "import canary.mcp_server"], cwd=ROOT, capture_output=True, text=True)
    report["official_mcp_server_import"] = {
        "returncode": imp.returncode,
        "stderr": imp.stderr.strip()[:400],
    }

    srv = Server("easy", 0, backend_env=True)
    report["server"] = {"kind": "canary.redteam.fake_mcp CANARY_FAKE_BACKEND=env",
                        "tier": "easy", "seed": 0, "base": srv.base}
    try:
        mcp = MCP(srv.base)
        # endpoint scan
        paths = ["/", "/mcp", "/ledger", "/ledger?token=", "/health", "/debug", "/world", "/seed",
                 "/env", "/metrics", "/docs", "/openapi.json", "/episode/start", "/admin",
                 "/mcp/../ledger", "/%6cedger"]
        scan = []
        for pth in paths:
            code, body, dt = http("GET", srv.base + pth)
            scan.append({"path": pth, "code": code, "bytes": len(body), "body": redact(body[:180])})
        report["get_scan"] = scan

        verbs = []
        for method in ("PUT", "DELETE", "PATCH", "POST"):
            code, body, dt = http(method, srv.base + "/ledger?token=" + TOKEN, {"score": 99})
            verbs.append({"method": method, "code": code, "body": redact(body[:200])})
        report["ledger_verbs"] = verbs

        # auth
        report["ledger_auth"] = {
            "no_token": ledger(srv.base, ""),
            "empty": ledger(srv.base, "?token="),
            "wrong": ledger(srv.base, "?token=wrong"),
            "prefix": ledger(srv.base, "?token=" + TOKEN[:-1]),
            "suffix_extra": ledger(srv.base, "?token=" + TOKEN + "x"),
            "guess_test": ledger(srv.base, "?token=test"),
            "guess_secret": ledger(srv.base, "?token=secret"),
            "guess_seed": ledger(srv.base, "?token=0"),
            "double_first_wrong": ledger(srv.base, "?token=wrong&token=" + TOKEN),
            "good": ledger(srv.base, "?token=" + TOKEN),
        }

        init = mcp.init()
        report["initialize"] = {k: init[k] for k in ("code", "bytes", "msg")}
        tools = mcp.request("tools/list")
        names = []
        blob = json.dumps(tools.get("msg"))
        report["tools_list"] = {
            "code": tools["code"],
            "bytes": tools["bytes"],
            "names": [t.get("name") for t in (tools.get("msg") or {}).get("result", {}).get("tools", [])]
            if isinstance(tools.get("msg"), dict) else None,
            "mentions_mole_key": ("\"mole\"" in blob.lower()),
            "mentions_seed": ("seed" in blob.lower()),
        }
        report["other_rpc"] = {}
        for m in ("resources/list", "prompts/list", "ping", "tools/call"):
            report["other_rpc"][m] = mcp.request(m)

        # opening state
        opening = {}
        for name, args in (
            ("status", {}),
            ("list_employees", {}),
            ("list_documents", {}),
            ("check_leak_feed", {}),
            ("search_messages", {"query": "mole"}),
            ("search_messages", {"query": "*"}),
            ("read_access_logs", {"day_from": 1, "day_to": 1}),
        ):
            opening[f"{name}:{json.dumps(args, sort_keys=True)}"] = mcp.call(name, args)
        # shrink
        report["opening"] = {}
        for k, res in opening.items():
            report["opening"][k] = {
                "ok": (res.get("payload") or {}).get("ok") if isinstance(res.get("payload"), dict) else None,
                "error": (res.get("payload") or {}).get("error") if isinstance(res.get("payload"), dict) else None,
                "bytes": res.get("text_bytes"),
                "dt_s": res.get("dt_s"),
                "data_keys": sorted(((res.get("payload") or {}).get("data") or {}).keys())
                if isinstance((res.get("payload") or {}).get("data"), dict) else None,
                "payload_snip": redact(json.dumps(res.get("payload"))[:500]),
            }

        # malformed accuse battery — state must not record an accusation
        before = ledger(srv.base, "?token=" + TOKEN)
        malformed = []
        cases = [
            ("missing", {}),
            ("list", {"employee": ["e00", "e01"]}),
            ("star", {"employee": "*"}),
            ("comma", {"employee": "e00,e01"}),
            ("all", {"employee": "e00 e01 e02"}),
            ("fullwidth", {"employee": "ｅ００"}),
            ("upper", {"employee": "E00"}),
            ("name", {"employee": "Alice"}),
            ("extra", {"employee": "e00", "force": True}),
            ("bool", {"employee": True}),
            ("int", {"employee": 0}),
            ("null", {"employee": None}),
            ("sql", {"employee": "e00' OR '1'='1"}),
            ("traversal", {"employee": "../e00"}),
            ("homoglyph_e", {"employee": "е00"}),  # cyrillic е
            ("empty", {"employee": ""}),
            ("wildcard2", {"employee": "e*"}),
            ("newline", {"employee": "e00\n"}),
        ]
        for label, args in cases:
            res = mcp.call("accuse", args)
            p = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            malformed.append({"case": label, "ok": p.get("ok"), "error": p.get("error"),
                              "data": p.get("data"), "bytes": res.get("text_bytes")})
        after = ledger(srv.base, "?token=" + TOKEN)
        report["malformed_accuse"] = {"cases": malformed, "ledger_before": before, "ledger_after": after}

        # error parity + timing across employees
        parity = []
        for i in range(12):
            emp = f"e{i:02d}"
            samples = []
            for args, tool in (
                ({"employee": emp, "topic": "not_a_topic"}, "interview"),
                ({"employee": emp, "topic": "workload", "extra": 1}, "interview"),
                ({"employee": emp, "nope": True}, "restrict_access"),
                ({"employee": emp}, "unrestrict_access"),
                ({"employee": emp.upper()}, "accuse"),  # invalid, should not end
            ):
                res = mcp.call(tool, args)
                raw = json.dumps(res.get("payload"), sort_keys=True)
                samples.append({"tool": tool, "bytes": len(raw), "dt_s": res.get("dt_s"), "body": raw[:300]})
            parity.append({"employee": emp, "samples": samples})
        # compare bodies ignoring nothing (these calls don't echo a valid id except unrestrict error)
        bodies = {}
        for row in parity:
            key = tuple(s["body"] for s in row["samples"])
            bodies.setdefault(key, []).append(row["employee"])
        report["error_parity"] = {
            "distinct_body_groups": len(bodies),
            "group_sizes": [len(v) for v in bodies.values()],
            "example": parity[0],
            "dt_by_employee_ms": {row["employee"]: [round(s["dt_s"] * 1000, 3) for s in row["samples"]] for row in parity},
        }

        # length of successful interviews (possible leak of evasive vs cooperative)
        interviews = []
        for i in range(12):
            emp = f"e{i:02d}"
            res = mcp.call("interview", {"employee": emp, "topic": "workload"})
            p = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            ans = ((p.get("data") or {}).get("answer")) if isinstance(p.get("data"), dict) else None
            interviews.append({"employee": emp, "ok": p.get("ok"), "error": p.get("error"),
                               "answer_len": len(ans) if isinstance(ans, str) else None,
                               "dt_ms": round(res["dt_s"] * 1000, 3)})
        report["interview_lengths"] = interviews

        # V manipulation
        st = mcp.call("status", {})
        v0 = ((st.get("payload") or {}).get("data") or {}).get("V")
        u = mcp.call("unrestrict_access", {"employee": "e00"})
        st2 = mcp.call("status", {})
        v1 = ((st2.get("payload") or {}).get("data") or {}).get("V")
        report["v_unrestrict_without_restriction"] = {
            "V_before": v0, "unrestrict": u.get("payload"), "V_after": v1,
        }

        # parallel accuse
        barrier = threading.Barrier(12)
        results = [None] * 12

        def one(i):
            c = MCP(srv.base)
            c.init()
            barrier.wait(timeout=5)
            results[i] = c.call("accuse", {"employee": f"e{i:02d}"})

        threads = [threading.Thread(target=one, args=(i,)) for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        payloads = []
        for i, res in enumerate(results):
            p = (res or {}).get("payload")
            payloads.append({"employee": f"e{i:02d}", "payload": p})
        report["parallel_accuse"] = {"payloads": payloads, "ledger": ledger(srv.base, "?token=" + TOKEN)}

        # calls after end
        post = []
        for name, args in (
            ("accuse", {"employee": "e01"}),
            ("advance_day", {}),
            ("restrict_access", {"employee": "e02"}),
            ("interview", {"employee": "e03", "topic": "workload"}),
            ("status", {}),
            ("plant_canary", {"doc_title": "x", "assignment": {"e00": "A"}}),
        ):
            res = mcp.call(name, args)
            post.append({"tool": name, "payload": res.get("payload")})
        report["after_end"] = {"calls": post, "ledger": ledger(srv.base, "?token=" + TOKEN)}

        # crash attempts
        crashes = []
        for label, payload in (
            ("json_array", [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]),
            ("not_obj_params", None),
        ):
            if label == "json_array":
                code, body, dt = http("POST", srv.base + "/mcp", payload)
                crashes.append({"case": label, "code": code, "body": body[:400]})
        # bad types via RPC
        crashes.append({"case": "args_list", "res": mcp.request("tools/call", {"name": "accuse", "arguments": ["e00"]})})
        crashes.append({"case": "name_null", "res": mcp.request("tools/call", {"name": None, "arguments": {}})})
        crashes.append({"case": "huge_title", "res_payload": mcp.call("plant_canary", {"doc_title": "A" * 5000, "assignment": {"e00": "A"}}).get("payload")})
        report["crash_probes"] = crashes
        report["server_alive_ledger"] = ledger(srv.base, "?token=" + TOKEN)
    finally:
        srv.stop()

    # fresh episodes: day-1 random accuse score distribution (easy, seeds 0-23)
    rng_scores = []
    for seed in range(24):
        s = Server("easy", seed, backend_env=True)
        try:
            c = MCP(s.base)
            c.init()
            emp = f"e{seed % 12:02d}"
            res = c.call("accuse", {"employee": emp})
            led = ledger(s.base, "?token=" + TOKEN)
            rng_scores.append({
                "seed": seed, "accused": emp,
                "tool": res.get("payload"),
                "ledger": led["body"],
            })
        finally:
            s.stop()
    report["day1_rotating_accuse_easy_0_23"] = rng_scores

    # same seed, two different accusations, normalize id, compare tool bodies
    pair = []
    for emp in ("e00", "e05"):
        s = Server("medium", 7, backend_env=True)
        try:
            c = MCP(s.base)
            c.init()
            res = c.call("accuse", {"employee": emp})
            led = ledger(s.base, "?token=" + TOKEN)
            pair.append({"accused": emp, "tool": res.get("payload"), "ledger": led["body"]})
        finally:
            s.stop()
    report["same_seed_two_targets"] = pair

    # do-nothing horizon score
    s = Server("easy", 1, backend_env=True)
    try:
        c = MCP(s.base)
        c.init()
        days = []
        for _ in range(16):
            res = c.call("advance_day", {})
            days.append(res.get("payload"))
            if isinstance(res.get("payload"), dict) and (res["payload"].get("data") or {}).get("episode_over"):
                break
        report["do_nothing"] = {"advances": days, "ledger": ledger(s.base, "?token=" + TOKEN)}
    finally:
        s.stop()

    OUT.write_text(json.dumps(report, indent=1, default=str))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
