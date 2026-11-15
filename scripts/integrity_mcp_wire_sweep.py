from __future__ import annotations

import argparse
import asyncio
import concurrent.futures as cf
import contextlib
import copy
import http.client
import itertools
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canary import world as canary_world
from canary.mcp_server import (
    BOOT_FD,
    PLAIN_SECRET_VARS,
    SECRET_FILE_VARS,
    Episode,
    _cfg_to_boot,
    build_app,
    clean_launch_env,
    consume_secret_files as mcp_consume_secret_files,
    load_config,
    verify_ledger,
)
from canary.rules import tier_params

DEFAULT_TMP_ROOT = Path("/tmp/opencode/w2-mcp")
ALL_TIERS = ("easy", "medium", "hard", "hard_forge")
ALL_SEEDS = tuple(range(900005, 900013))
PAIRED_SEEDS = {
    "easy": (900005, 900006),
    "medium": (900007, 900008),
    "hard": (900009, 900010),
    "hard_forge": (900011, 900012),
}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def write_0600(path: Path, content: str) -> str:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return str(path)


def base_clean_env() -> dict[str, str]:
    env = clean_launch_env()
    for var in (*SECRET_FILE_VARS, *PLAIN_SECRET_VARS, "CANARY_BOOTSTRAPPED", "CANARY_CONSUME_SECRET_FILES",
                "CANARY_ALLOW_DEV", "CANARY_LEDGER_LIVE"):
        env.pop(var, None)
    return env


class ManagedMCPServer:
    def __init__(
        self,
        tier: str,
        seed: int,
        tmp_root: Path = DEFAULT_TMP_ROOT,
        with_admin_token: bool = True,
        with_ledger_key: bool = True,
        with_world_secret: bool = True,
        consume_secret_files: bool = True,
        marker_prefix: str = "w2sec",
        extra_env: dict[str, str] | None = None,
        startup_timeout: float = 30.0,
        inproc: bool = False,
        fast_boot: bool = False,
        wait_ready: bool = True,
    ) -> None:
        tmp_root.mkdir(parents=True, exist_ok=True)
        self.workdir = tmp_root / f"srv-{secrets.token_hex(6)}"
        self.workdir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.workdir, 0o700)
        self.tier = tier
        self.seed = seed
        self.marker_prefix = marker_prefix
        self.world_secret = f"{marker_prefix}-ws-{secrets.token_hex(16)}" if with_world_secret else None
        self.ledger_token = f"{marker_prefix}-ltok-{secrets.token_hex(12)}"
        self.admin_token = f"{marker_prefix}-atok-{secrets.token_hex(12)}" if with_admin_token else None
        self.ledger_key = f"{marker_prefix}-lkey-{secrets.token_hex(16)}" if with_ledger_key else None
        self.log_path = self.workdir / "server.log"
        self._log_fh = open(self.log_path, "w", encoding="utf-8")
        self.secret_paths: dict[str, Path] = {}
        self.proc: subprocess.Popen[bytes] | None = None
        self._inproc_server: Any = None
        self._inproc_thread: threading.Thread | None = None
        self._prev_world_secret: bytes | None = None
        self._has_prev_world_secret = False
        self._fast_boot = fast_boot
        self._startup_timeout = startup_timeout
        self._ready = False
        self.port = 0

        sdir = self.workdir / f"sec-{marker_prefix}"
        sdir.mkdir(parents=True, exist_ok=True)
        os.chmod(sdir, 0o700)
        last_err: Exception | None = None
        try:
            for _ in range(5):
                port = free_port()
                pdir = sdir / f"p-{port}"
                pdir.mkdir(parents=True, exist_ok=True)
                os.chmod(pdir, 0o700)
                self.secret_paths = {}
                env = base_clean_env()
                env["CANARY_HOST"] = "127.0.0.1"
                env["CANARY_PORT"] = str(port)
                ep_path = pdir / f"{marker_prefix}-episode.json"
                write_0600(ep_path, json.dumps({"tier": tier, "seed": int(seed)}))
                env["CANARY_EPISODE_FILE"] = str(ep_path)
                self.secret_paths["CANARY_EPISODE_FILE"] = ep_path

                lt_path = pdir / f"{marker_prefix}-ledger-token"
                write_0600(lt_path, self.ledger_token)
                env["CANARY_LEDGER_TOKEN_FILE"] = str(lt_path)
                self.secret_paths["CANARY_LEDGER_TOKEN_FILE"] = lt_path

                if self.world_secret is not None:
                    ws_path = pdir / f"{marker_prefix}-world-secret"
                    write_0600(ws_path, self.world_secret)
                    env["CANARY_WORLD_SECRET_FILE"] = str(ws_path)
                    self.secret_paths["CANARY_WORLD_SECRET_FILE"] = ws_path

                if self.admin_token is not None:
                    at_path = pdir / f"{marker_prefix}-admin-token"
                    write_0600(at_path, self.admin_token)
                    env["CANARY_ADMIN_TOKEN_FILE"] = str(at_path)
                    self.secret_paths["CANARY_ADMIN_TOKEN_FILE"] = at_path

                if self.ledger_key is not None:
                    lk_path = pdir / f"{marker_prefix}-ledger-key"
                    write_0600(lk_path, self.ledger_key)
                    env["CANARY_LEDGER_KEY_FILE"] = str(lk_path)
                    self.secret_paths["CANARY_LEDGER_KEY_FILE"] = lk_path

                if inproc:
                    import uvicorn

                    cfg = load_config(env)
                    if consume_secret_files:
                        mcp_consume_secret_files(env)
                    self._prev_world_secret = canary_world._SET_SECRET
                    self._has_prev_world_secret = True
                    if cfg["world_secret"] is not None:
                        canary_world.set_world_secret(cfg["world_secret"])
                    ep_obj = Episode(cfg["tier"], cfg["seed"], "template")
                    app = build_app(
                        ep_obj,
                        host="127.0.0.1",
                        ledger_token=cfg["ledger_token"],
                        admin_token=cfg["admin_token"],
                        ledger_key=cfg["ledger_key"],
                    )

                    class _QuietMCPServer(uvicorn.Server):
                        @contextlib.contextmanager
                        def capture_signals(self):
                            yield

                    u_cfg = uvicorn.Config(
                        app,
                        host="127.0.0.1",
                        port=port,
                        log_level="error",
                        access_log=False,
                        lifespan="on",
                    )
                    self._inproc_server = _QuietMCPServer(u_cfg)
                    srv_inst = self._inproc_server
                    self._inproc_thread = threading.Thread(
                        target=lambda: asyncio.run(srv_inst.serve()),
                        daemon=True,
                    )
                    self._inproc_thread.start()
                    self.port = port
                    if wait_ready:
                        self._wait_healthy(port, startup_timeout)
                        self._ready = True
                    break

                if fast_boot and consume_secret_files:
                    cfg = load_config(env)
                    mcp_consume_secret_files(env)
                    boot_env = base_clean_env()
                    boot_env["CANARY_HOST"] = "127.0.0.1"
                    boot_env["CANARY_PORT"] = str(port)
                    boot_env["CANARY_BOOTSTRAPPED"] = "1"
                    if extra_env:
                        boot_env.update(extra_env)
                    boot_bytes = _cfg_to_boot(cfg)
                    if hasattr(os, "memfd_create"):
                        mfd = os.memfd_create("canary-cfg", 0)
                    else:
                        r_p, mfd = os.pipe()
                        os.write(mfd, boot_bytes)
                        os.close(mfd)
                        mfd = r_p
                        boot_bytes = b""
                    if boot_bytes:
                        os.write(mfd, boot_bytes)
                        os.lseek(mfd, 0, os.SEEK_SET)
                    saved_73: int | None = None
                    try:
                        try:
                            os.fstat(BOOT_FD)
                            saved_73 = os.dup(BOOT_FD)
                        except OSError:
                            saved_73 = None
                        if mfd != BOOT_FD:
                            os.dup2(mfd, BOOT_FD)
                            os.close(mfd)
                        os.set_inheritable(BOOT_FD, True)
                        self.proc = subprocess.Popen(
                            [sys.executable, "-m", "canary.mcp_server"],
                            env=boot_env,
                            cwd=str(REPO),
                            pass_fds=(BOOT_FD,),
                            stdout=self._log_fh,
                            stderr=subprocess.STDOUT,
                        )
                    finally:
                        with contextlib.suppress(OSError):
                            os.close(BOOT_FD)
                        if saved_73 is not None:
                            os.dup2(saved_73, BOOT_FD)
                            os.close(saved_73)
                    self.port = port
                    if wait_ready:
                        self._wait_healthy(port, startup_timeout)
                        self._ready = True
                    break

                if consume_secret_files:
                    env["CANARY_CONSUME_SECRET_FILES"] = "1"
                if extra_env:
                    env.update(extra_env)

                self.proc = subprocess.Popen(
                    [sys.executable, "-m", "canary.mcp_server"],
                    env=env,
                    cwd=str(REPO),
                    stdout=self._log_fh,
                    stderr=subprocess.STDOUT,
                )
                try:
                    self.port = port
                    if wait_ready:
                        self._wait_healthy(port, startup_timeout)
                        self._ready = True
                    break
                except RuntimeError as exc:
                    last_err = exc
                    rc = self.proc.poll()
                    if rc is None:
                        self.proc.kill()
                        self.proc.wait(timeout=5)
                    if rc == 2:
                        raise RuntimeError(f"server refused to start (exit 2): {exc}") from exc
            else:
                raise RuntimeError(f"server failed to start after 5 attempts: {last_err}")
        except BaseException:
            self.stop()
            raise

        self.base = f"http://127.0.0.1:{self.port}"
        self.url = f"{self.base}/mcp"

    def ensure_ready(self) -> None:
        if not self._ready:
            self._wait_healthy(self.port, self._startup_timeout)
            self._ready = True

    def _wait_healthy(self, port: int, timeout: float) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc is not None and self.proc.poll() is not None:
                raise RuntimeError(f"server exited early with code {self.proc.returncode}")
            if self._inproc_thread is not None and not self._inproc_thread.is_alive():
                raise RuntimeError("in-process MCP server thread exited early")
            code, _, _ = self.raw_http("GET", "/healthz", port_override=port, timeout=1.0)
            if code == 200 and (self.proc is None or self.proc.poll() is None):
                return
            time.sleep(0.01)
        raise RuntimeError("server did not become healthy before timeout")

    def raw_http(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        port_override: int | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, bytes, dict[str, str]]:
        port = port_override or self.port
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return int(resp.status), data, hdrs
        except (http.client.HTTPException, OSError):
            return 0, b"", {}
        finally:
            conn.close()

    def reset(self, tier: str, seed: int) -> str:
        if not self.admin_token:
            raise RuntimeError("admin_token not configured")
        q = urllib.parse.urlencode({"token": self.admin_token})
        payload = json.dumps({"tier": tier, "seed": int(seed)}).encode("utf-8")
        code, raw, _ = self.raw_http(
            "POST",
            f"/admin/reset?{q}",
            body=payload,
            headers={"Content-Type": "application/json"},
        )
        if code != 200:
            raise RuntimeError(f"reset({tier}, {seed}) failed with HTTP {code}: {raw!r}")
        self.tier = tier
        self.seed = seed
        obj = json.loads(raw.decode("utf-8"))
        return str(obj["episode"])

    def ledger(self, token: str | None = None) -> tuple[int, dict[str, Any]]:
        tok = self.ledger_token if token is None else token
        q = urllib.parse.urlencode({"token": tok})
        code, raw, _ = self.raw_http("GET", f"/ledger?{q}")
        if not raw:
            return code, {}
        try:
            return code, json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return code, {"_raw": raw.decode("utf-8", errors="replace")}

    def check_invariants(self) -> tuple[bool, str]:
        if self._inproc_thread is not None:
            alive = self._inproc_thread.is_alive()
        else:
            alive = self.proc is not None and self.proc.poll() is None
        h_code, _, _ = self.raw_http("GET", "/healthz")
        healthy = alive and h_code == 200
        l_code, led = self.ledger()
        if not healthy or l_code != 200 or not isinstance(led, dict):
            return False, f"healthy={healthy} ledger_http={l_code}"
        sig_ok = True
        if self.ledger_key is not None:
            sig_ok = verify_ledger(led, self.ledger_key)
        done = bool(led.get("done"))
        score = float(led.get("score", 0.0))
        if not done:
            redacted_ok = (
                score == 0.0
                and led.get("ledger") == []
                and led.get("redacted") == "episode in progress"
                and all(k not in led for k in ("V", "final_day", "accused", "correct", "accused_correct"))
            )
            ok = healthy and sig_ok and redacted_ok
            return ok, f"healthy={healthy} sig={sig_ok} done=False redacted={redacted_ok} score={score:+.2f}"
        entries = led.get("ledger", [])
        accs = [e for e in entries if isinstance(e, dict) and e.get("event") == "accused"]
        ends = [e for e in entries if isinstance(e, dict) and e.get("event") == "episode_end"]
        v_val = float(led.get("V", -1.0))
        v_ok = 0.0 <= v_val <= 1.0
        correct = bool(led.get("correct"))
        if len(accs) == 0:
            score_ok = score == 0.0 and not correct
        elif len(accs) == 1:
            if correct:
                score_ok = 0.0 <= score <= 1.0 and abs(score - v_val) <= 1e-9
            else:
                score_ok = score == -1.0
        else:
            score_ok = False
        ok = healthy and sig_ok and v_ok and len(accs) <= 1 and len(ends) == 1 and score_ok
        return ok, f"healthy={healthy} sig={sig_ok} accs={len(accs)} ends={len(ends)} score={score:+.2f} V={v_val:.2f}"

    def stop(self) -> bool:
        crashed = False
        if self._inproc_server is not None:
            self._inproc_server.should_exit = True
            if self._inproc_thread is not None:
                self._inproc_thread.join(timeout=0.01)
            self._inproc_server = None
            self._inproc_thread = None
        if self._has_prev_world_secret:
            canary_world.set_world_secret(self._prev_world_secret)
            self._has_prev_world_secret = False
        if self.proc is not None:
            crashed = self.proc.poll() is not None
            if not crashed:
                if self._fast_boot:
                    self.proc.kill()
                    self.proc.wait(timeout=2)
                else:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                        self.proc.wait(timeout=5)
            self.proc = None
        if not self._log_fh.closed:
            self._log_fh.close()
        shutil.rmtree(self.workdir, ignore_errors=True)
        return crashed


class WireSession:
    def __init__(self, port: int, timeout: float = 15.0) -> None:
        self.port = port
        self.timeout = timeout
        self.session: str | None = None
        self.instructions: str = ""
        self._ids = itertools.count(1)
        self._conn: http.client.HTTPConnection | None = None
        self._terminated = False

    def _get_conn(self) -> http.client.HTTPConnection:
        if self._conn is None or self._conn.sock is None:
            self._conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout)
        return self._conn

    def _reset_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None

    def raw_post(
        self,
        body: bytes,
        headers: dict[str, str] | None = None,
        include_session: bool = True,
    ) -> tuple[int, str, dict[str, str]]:
        hdrs = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
        }
        if include_session and self.session is not None:
            hdrs["Mcp-Session-Id"] = self.session
        if headers is not None:
            hdrs.update(headers)
        for attempt in range(2):
            conn = self._get_conn()
            try:
                conn.request("POST", "/mcp", body=body, headers=hdrs)
                resp = conn.getresponse()
                raw = resp.read()
                resp_hdrs = {k.lower(): v for k, v in resp.getheaders()}
                sid = resp_hdrs.get("mcp-session-id")
                if sid and self.session is None:
                    self.session = sid
                if resp.status >= 400 or resp_hdrs.get("connection", "").lower() == "close":
                    self._reset_conn()
                return int(resp.status), raw.decode("utf-8", errors="replace"), resp_hdrs
            except (http.client.HTTPException, OSError):
                self._reset_conn()
                if attempt == 1:
                    raise
        raise RuntimeError("unreachable")

    @staticmethod
    def decode_rpc(status: int, text: str, ctype: str, req_id: Any = None) -> dict[str, Any] | None:
        if not text.strip():
            return None
        if "text/event-stream" in ctype:
            last_msg = None
            for line in text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if not chunk:
                        continue
                    msg = json.loads(chunk)
                    last_msg = msg
                    if req_id is None or msg.get("id") == req_id:
                        return msg
            return last_msg
        return json.loads(text)

    def rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        rid = next(self._ids)
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        status, text, hdrs = self.raw_post(json.dumps(payload).encode("utf-8"))
        if status != 200:
            raise RuntimeError(f"MCP HTTP {status}: {text[:200]}")
        msg = self.decode_rpc(status, text, hdrs.get("content-type", ""), rid)
        if msg is None:
            raise RuntimeError("empty MCP response")
        if "error" in msg:
            raise RuntimeError(f"JSONRPC error: {json.dumps(msg['error'])}")
        return dict(msg["result"])

    def initialize(self) -> dict[str, Any]:
        res = self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "w2-wire-sweep", "version": "1.0"},
            },
        )
        self.instructions = str(res.get("instructions") or "")
        self.raw_post(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode("utf-8"))
        return res

    def list_tools(self) -> list[dict[str, Any]]:
        return list(self.rpc("tools/list")["tools"])

    def call(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        res = self.rpc("tools/call", {"name": name, "arguments": {} if args is None else args})
        sc = res.get("structuredContent")
        if isinstance(sc, dict):
            return dict(sc.get("result", sc) if set(sc) == {"result"} else sc)
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        return dict(json.loads(text))

    def employee_ids(self) -> list[str]:
        rows = self.call("list_employees", {})["data"]["employees"]
        return [str(r["id"]) for r in rows]

    def delete_session(self) -> int:
        if self.session is None:
            return 0
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5.0)
        try:
            conn.request(
                "DELETE",
                "/mcp",
                headers={"Mcp-Session-Id": self.session, "MCP-Protocol-Version": "2025-06-18"},
            )
            resp = conn.getresponse()
            resp.read()
            self._terminated = True
            return int(resp.status)
        except (http.client.HTTPException, OSError):
            return 0
        finally:
            conn.close()

    def close(self) -> None:
        if self.session is not None and not self._terminated:
            self.delete_session()
        self._reset_conn()


def open_sessions(port: int, count: int) -> list[WireSession]:
    sessions = [WireSession(port) for _ in range(count)]
    try:
        if count >= 4:
            with cf.ThreadPoolExecutor(max_workers=min(count, 16)) as pool:
                list(pool.map(lambda ws: ws.initialize(), sessions))
        else:
            for ws in sessions:
                ws.initialize()
        return sessions
    except Exception:
        for ws in sessions:
            ws.close()
        raise


def close_sessions(sessions: list[WireSession]) -> None:
    for ws in sessions:
        ws.close()


def advance_to_horizon(ws: WireSession, max_days: int = 30) -> None:
    for _ in range(max_days):
        r = ws.call("advance_day", {})
        if not r.get("ok") or (r.get("data") or {}).get("episode_over"):
            break


def reconstruct_ledger_v(tier: str, led: dict[str, Any]) -> tuple[bool, float, float]:
    p = tier_params(tier)
    entries = led.get("ledger", [])
    final_day = int(led.get("final_day", 1))
    end_reason = led.get("end_reason")
    closed_days = p.n_days if end_reason == "horizon" else final_day - 1
    v = 1.0
    active: set[str] = set()
    prev_logged_v = 1.0
    monotone = True

    for d in range(1, final_day + 1):
        for e in entries:
            if int(e.get("day", 0)) != d:
                continue
            ev = e.get("event")
            det = e.get("detail") or {}
            if ev == "restricted":
                active.add(str(det["employee"]))
            elif ev == "unrestricted":
                active.discard(str(det["employee"]))
            elif ev == "canary_planted":
                v = max(0.0, v - p.canary_cost)
                lv = float(det.get("V", v))
                if lv > prev_logged_v + 1e-9 or abs(round(v, 10) - round(lv, 10)) > 1e-9:
                    monotone = False
                prev_logged_v = lv
            elif ev == "leak":
                v = max(0.0, v - p.leak_damage)
                lv = float(det.get("V", v))
                if lv > prev_logged_v + 1e-9 or abs(round(v, 10) - round(lv, 10)) > 1e-9:
                    monotone = False
                prev_logged_v = lv
        if d <= closed_days and active:
            v = max(0.0, v - p.restrict_cost_per_day * len(active))

    reported_v = float(led.get("V", -1.0))
    if reported_v > prev_logged_v + 1e-9:
        monotone = False
    exact = monotone and abs(round(v, 10) - reported_v) <= 1e-9
    return exact, round(v, 10), reported_v


def w01_concurrent_plant_canary_race(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    cap = p.canaries_per_day
    n_sess = max(cap + 3, 4) if srv._inproc_server is not None else 16
    sessions = open_sessions(srv.port, n_sess)
    try:
        emps = sessions[0].employee_ids()
        barrier = threading.Barrier(n_sess)

        def worker(idx: int) -> dict[str, Any]:
            barrier.wait(timeout=10)
            return sessions[idx].call(
                "plant_canary",
                {"doc_title": f"race-canary-{idx}", "assignment": {emps[0]: "v1", emps[1]: "v2"}},
            )

        with cf.ThreadPoolExecutor(max_workers=n_sess) as ex:
            results = list(ex.map(worker, range(n_sess)))

        oks = [r for r in results if r.get("ok") is True]
        errs = [r for r in results if not r.get("ok")]
        err_msgs_ok = all(r.get("error") == "canary limit for today reached" for r in errs)
        st = sessions[0].call("status", {})["data"]
        st_ok = (
            len(st["canaries_planted"]) == cap
            and st["actions_left_today"] == p.actions_per_day - cap
            and abs(float(st["V"]) - round(1.0 - p.canary_cost * cap, 10)) <= 1e-9
        )
        advance_to_horizon(sessions[0], p.n_days + 2)
    finally:
        close_sessions(sessions)

    inv_ok, inv_msg = srv.check_invariants()
    _, led = srv.ledger()
    planted = [e for e in led.get("ledger", []) if e.get("event") == "canary_planted"]
    passed = inv_ok and len(oks) == cap and len(errs) == n_sess - cap and err_msgs_ok and st_ok and len(planted) == cap
    return passed, f"ok={len(oks)}/{cap} rejected={len(errs)} ledger_planted={len(planted)} {inv_msg}"


def w02_concurrent_action_cap_race(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    cap = p.actions_per_day
    sessions = open_sessions(srv.port, 16)
    try:
        emps = sessions[0].employee_ids()
        barrier = threading.Barrier(16)

        def worker(idx: int) -> dict[str, Any]:
            barrier.wait(timeout=10)
            if idx % 2 == 0:
                return sessions[idx].call("check_leak_feed", {})
            return sessions[idx].call("interview", {"employee": emps[idx % len(emps)], "topic": "workload"})

        with cf.ThreadPoolExecutor(max_workers=16) as ex:
            results = list(ex.map(worker, range(16)))

        oks = [r for r in results if r.get("ok") is True]
        errs = [r for r in results if not r.get("ok")]
        err_msgs_ok = all(r.get("error") == "daily action limit; call advance_day" for r in errs)
        st_before = sessions[0].call("status", {})["data"]
        extra_fail = sessions[0].call("check_leak_feed", {})
        sessions[0].call("advance_day", {})
        st_after = sessions[0].call("status", {})["data"]
    finally:
        close_sessions(sessions)

    inv_ok, inv_msg = srv.check_invariants()
    passed = (
        inv_ok
        and len(oks) == cap
        and len(errs) == 16 - cap
        and err_msgs_ok
        and st_before["actions_left_today"] == 0
        and not extra_fail.get("ok")
        and st_after["actions_left_today"] == cap
    )
    return passed, f"ok={len(oks)}/{cap} rejected={len(errs)} next_day_budget={st_after['actions_left_today']} {inv_msg}"


def w03_concurrent_restrict_unrestrict_advance(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    sessions = open_sessions(srv.port, 16)
    try:
        emps = sessions[0].employee_ids()[:6]
        barrier = threading.Barrier(16)

        def worker(idx: int) -> list[dict[str, Any]]:
            barrier.wait(timeout=10)
            out: list[dict[str, Any]] = []
            for step in range(3):
                target = emps[(idx + step) % len(emps)]
                if idx < 6:
                    out.append(sessions[idx].call("restrict_access", {"employee": target}))
                elif idx < 12:
                    out.append(sessions[idx].call("unrestrict_access", {"employee": target}))
                elif idx < 14:
                    out.append(sessions[idx].call("status", {}))
                else:
                    out.append(sessions[idx].call("advance_day", {}))
            return out

        with cf.ThreadPoolExecutor(max_workers=16) as ex:
            batches = list(ex.map(worker, range(16)))

        v_bounds_ok = True
        for batch in batches:
            for res in batch:
                data = res.get("data") or {}
                if "V" in data:
                    vv = float(data["V"])
                    if not (0.0 <= vv <= 1.0):
                        v_bounds_ok = False
        for emp in emps:
            sessions[0].call("unrestrict_access", {"employee": emp})
        advance_to_horizon(sessions[0], p.n_days + 2)
    finally:
        close_sessions(sessions)

    inv_ok, inv_msg = srv.check_invariants()
    _, led = srv.ledger()
    exact_v, calc_v, rep_v = reconstruct_ledger_v(srv.tier, led)
    passed = inv_ok and v_bounds_ok and exact_v
    return passed, f"v_bounds={v_bounds_ok} exact_cost={exact_v} calc_V={calc_v:.2f} rep_V={rep_v:.2f} {inv_msg}"


def w04_concurrent_tool_cap_cliff_race(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    sessions = open_sessions(srv.port, 16)
    try:
        emps = sessions[0].employee_ids()
        st0 = sessions[0].call("status", {})["data"]
        remaining = int(st0["tool_calls_left"])
        pad_calls = max(0, remaining - 6)
        for _ in range(pad_calls):
            sessions[0].call("status", {})
        barrier = threading.Barrier(16)

        def worker(idx: int) -> dict[str, Any]:
            barrier.wait(timeout=10)
            if idx % 2 == 0:
                return sessions[idx].call("status", {})
            return sessions[idx].call("accuse", {"employee": emps[idx % len(emps)]})

        with cf.ThreadPoolExecutor(max_workers=16) as ex:
            results = list(ex.map(worker, range(16)))

        acc_oks = sum(1 for idx, r in enumerate(results) if idx % 2 == 1 and r.get("ok") is True)
    finally:
        close_sessions(sessions)

    inv_ok, inv_msg = srv.check_invariants()
    _, led = srv.ledger()
    end_reason = led.get("end_reason")
    accs = [e for e in led.get("ledger", []) if e.get("event") == "accused"]
    ends = [e for e in led.get("ledger", []) if e.get("event") == "episode_end"]
    consistent = (
        bool(led.get("done"))
        and len(ends) == 1
        and acc_oks == len(accs)
        and ((end_reason == "tool_cap" and len(accs) == 0 and float(led.get("score", -9.0)) == 0.0)
             or (end_reason == "accused" and len(accs) == 1))
    )
    passed = inv_ok and consistent
    return passed, f"end_reason={end_reason} acc_oks={acc_oks} {inv_msg}"


def w05_concurrent_delete_session_persistence(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    inproc = srv._inproc_server is not None
    n_del = 2 if inproc else 4
    n_post = 2 if inproc else 4
    n_obs = 2 if inproc else 5
    n_tot = n_del + n_post + n_obs
    req_timeout = 0.35 if inproc else 10.0
    sa = WireSession(srv.port)
    sa.initialize()
    observers = open_sessions(srv.port, n_obs)
    try:
        emps = sa.employee_ids()
        assert sa.call("plant_canary", {"doc_title": "persist-check", "assignment": {emps[0]: "v1"}})["ok"]
        assert sa.call("restrict_access", {"employee": emps[1]})["ok"]
        sid_a = sa.session
        assert sid_a is not None
        barrier = threading.Barrier(n_tot)

        def race_worker(idx: int) -> int:
            barrier.wait(timeout=10)
            if idx < n_del:
                c, _, _ = srv.raw_http(
                    "DELETE",
                    "/mcp",
                    headers={"Mcp-Session-Id": sid_a, "MCP-Protocol-Version": "2025-06-18"},
                    timeout=req_timeout,
                )
                return c
            if idx < n_del + n_post:
                body = json.dumps({
                    "jsonrpc": "2.0",
                    "id": 100 + idx,
                    "method": "tools/call",
                    "params": {"name": "status", "arguments": {}},
                }).encode("utf-8")
                c, _, _ = srv.raw_http(
                    "POST",
                    "/mcp",
                    body=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                        "MCP-Protocol-Version": "2025-06-18",
                        "Mcp-Session-Id": sid_a,
                    },
                    timeout=req_timeout,
                )
                return c
            st = observers[idx - (n_del + n_post)].call("status", {})
            return 200 if st.get("ok") else 500

        with cf.ThreadPoolExecutor(max_workers=n_tot) as ex:
            codes = list(ex.map(race_worker, range(n_tot)))
        sa._terminated = True

        post_after, _, _ = srv.raw_http(
            "POST",
            "/mcp",
            body=b'{"jsonrpc":"2.0","id":99,"method":"tools/list","params":{}}',
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
                "Mcp-Session-Id": sid_a,
            },
        )
        st_b = observers[-1].call("status", {})["data"]
        state_kept = (
            emps[1] in st_b["restricted"]
            and len(st_b["canaries_planted"]) == 1
            and abs(float(st_b["V"]) - round(1.0 - p.canary_cost, 10)) <= 1e-9
            and st_b["actions_left_today"] == p.actions_per_day - 2
        )
    finally:
        sa.close()
        close_sessions(observers)

    inv_ok, inv_msg = srv.check_invariants()
    del_codes = codes[:n_del]
    obs_ok = all(c == 200 for c in codes[n_del + n_post :])
    passed = inv_ok and (200 in del_codes) and obs_ok and post_after == 404 and state_kept
    return passed, f"del_codes={sorted(set(del_codes))} post_after_del={post_after} state_kept={state_kept} {inv_msg}"


def w06_json_unicode_escaped_keys(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        p1 = (
            b'{"jsonrpc":"2.0","id":10,"method":"tools/call","params":{"name":"restrict_access","arguments":'
            + b'{"\\u0065mployee":"' + emps[0].encode() + b'","employee":"' + emps[1].encode() + b'"}}}'
        )
        p2 = (
            b'{"jsonrpc":"2.0","id":11,"method":"tools/call","params":{"name":"accuse","arguments":'
            + b'{"\\u0065mployee":"' + emps[0].encode() + b'","\\u0073core":1.0}}}'
        )
        p3 = (
            b'{"jsonrpc":"2.0","id":12,"method":"tools/call","params":{"name":"accuse","arguments":'
            + b'{"\\u0065mployee":"\\u0065\\u0030\\u0030\\u0020"}}}'
        )
        p4 = (
            b'{"jsonrpc":"2.0","id":13,"\\u006dethod":"tools/call","params":{"name":"\\u0061ccuse","arguments":'
            + b'{"\\u0065mployee":"' + emps[0].encode() + b'","\\u0063orrect":true}}}'
        )
        statuses = []
        accepted_accuse = 0
        for idx, raw in enumerate((p1, p2, p3, p4)):
            st_code, text, hdrs = ws.raw_post(raw)
            statuses.append(st_code)
            if idx >= 1 and st_code == 200:
                msg = ws.decode_rpc(st_code, text, hdrs.get("content-type", ""), 10 + idx)
                sc = ((msg or {}).get("result") or {}).get("structuredContent") or {}
                if sc.get("ok"):
                    accepted_accuse += 1
        cur = ws.call("status", {})["data"]
        restricted_cnt = len(cur["restricted"])
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    passed = inv_ok and accepted_accuse == 0 and restricted_cnt <= 1
    return passed, f"http={statuses} accepted_accuse={accepted_accuse} restricted={restricted_cnt} {inv_msg}"


def w07_duplicate_nested_keys_plant_canary(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        assert ws.call("restrict_access", {"employee": emps[0]})["ok"]
        b_over_variants = (
            b'{"jsonrpc":"2.0","id":20,"method":"tools/call","params":{"name":"plant_canary","arguments":'
            b'{"doc_title":"dup1","assignment":'
            + (
                f'{{"{emps[1]}":"v1","{emps[1]}":"v2","{emps[2]}":"v3","{emps[3]}":"v4","{emps[4]}":"v5"}}'
            ).encode("utf-8")
            + b"}}}"
        )
        b_dup_outer = (
            b'{"jsonrpc":"2.0","id":21,"method":"tools/call","params":{"name":"plant_canary","arguments":'
            + (
                f'{{"doc_title":"dup2","assignment":{{"{emps[1]}":"v1"}},'
                f'"assignment":{{"{emps[1]}":"v1","{emps[2]}":"v2","{emps[3]}":"v3","{emps[4]}":"v4"}}}}'
            ).encode("utf-8")
            + b"}}"
        )
        b_restricted_dup = (
            b'{"jsonrpc":"2.0","id":22,"method":"tools/call","params":{"name":"plant_canary","arguments":'
            + f'{{"doc_title":"dup3","assignment":{{"{emps[0]}":"v1","{emps[0]}":"v2"}}}}'.encode("utf-8")
            + b"}}"
        )
        bad_accepted = 0
        for req_id, raw in ((20, b_over_variants), (21, b_dup_outer), (22, b_restricted_dup)):
            code, text, hdrs = ws.raw_post(raw)
            if code == 200:
                msg = ws.decode_rpc(code, text, hdrs.get("content-type", ""), req_id)
                sc = ((msg or {}).get("result") or {}).get("structuredContent") or {}
                if sc.get("ok"):
                    bad_accepted += 1

        b_same_emp_dup = (
            b'{"jsonrpc":"2.0","id":23,"method":"tools/call","params":{"name":"plant_canary","arguments":'
            + f'{{"doc_title":"dup4","assignment":{{"{emps[1]}":"v1","{emps[1]}":"v2"}}}}'.encode("utf-8")
            + b"}}"
        )
        c4, t4, h4 = ws.raw_post(b_same_emp_dup)
        m4 = ws.decode_rpc(c4, t4, h4.get("content-type", ""), 23)
        sc4 = ((m4 or {}).get("result") or {}).get("structuredContent") or {}
        docs = ws.call("list_documents", {"day_from": 1, "day_to": 1})["data"]["documents"]
        c_docs = [d for d in docs if d.get("is_canary")]
        single_variant_ok = len(c_docs) == 1 and c_docs[0]["variants"] == {"v2": [emps[1]]}
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    passed = inv_ok and bad_accepted == 0 and bool(sc4.get("ok")) and single_variant_ok
    return passed, f"bad_accepted={bad_accepted} collapsed_single_variant={single_variant_ok} {inv_msg}"


def w08_ieee754_numbers_and_types(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        bad_numbers = [
            b"NaN",
            b"Infinity",
            b"-Infinity",
            b"-0.0",
            b"1e309",
            b"-1e309",
            b"1.0",
            b"true",
            b"false",
            b"999999999999999999999999999999",
        ]
        tool_accepted = 0
        server_500s = 0
        for idx, tok in enumerate(bad_numbers):
            raw = (
                f'{{"jsonrpc":"2.0","id":{30 + idx},"method":"tools/call","params":'
                f'{{"name":"read_access_logs","arguments":{{"day_from":'.encode("utf-8")
                + tok
                + b',"day_to":1}}}'
            )
            code, text, hdrs = ws.raw_post(raw)
            if code >= 500:
                server_500s += 1
            if code == 200:
                msg = ws.decode_rpc(code, text, hdrs.get("content-type", ""), 30 + idx)
                sc = ((msg or {}).get("result") or {}).get("structuredContent") or {}
                if sc.get("ok"):
                    tool_accepted += 1

        id_probes = [b"NaN", b"Infinity", b"-0.0", b"1e309"]
        id_codes = []
        for tok in id_probes:
            raw = (
                b'{"jsonrpc":"2.0","id":'
                + tok
                + b',"method":"tools/call","params":{"name":"accuse","arguments":{"employee":"'
                + emps[0].encode("utf-8")
                + b'"}}}'
            )
            code, _, _ = ws.raw_post(raw)
            id_codes.append(code)
            if code >= 500:
                server_500s += 1

        alive_ok = bool(ws.call("status", {}).get("ok"))
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    passed = inv_ok and tool_accepted == 0 and server_500s == 0 and alive_ok
    return passed, f"bad_num_accepted={tool_accepted} id_codes={sorted(set(id_codes))} 500s={server_500s} {inv_msg}"


def w09_nul_bytes_in_strings_and_wire(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        r_acc1 = ws.call("accuse", {"employee": f"{emps[0]}\x00"})
        r_acc2 = ws.call("accuse", {"employee": f"\x00{emps[0]}"})
        r_emp_nul = ws.call("plant_canary", {"doc_title": "t", "assignment": {f"{emps[0]}\x00": "v1"}})
        r_msg_nul = ws.call("read_message", {"id": "m1\x00"})
        r_q1 = ws.call("search_messages", {"query": "\x00"})
        r_q2 = ws.call("search_messages", {"query": "roadmap\x00"})
        r_can = ws.call("plant_canary", {"doc_title": "doc\x00title", "assignment": {emps[0]: "v\x001"}})

        raw_unescaped_nul = (
            b'{"jsonrpc":"2.0","id":55,"method":"tools/call","params":{"name":"accuse","arguments":{"employee":"'
            + emps[0].encode("utf-8")
            + b'\x00"}}}'
        )
        raw_code, _, _ = ws.raw_post(raw_unescaped_nul)
        advance_to_horizon(ws, p.n_days + 2)
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    rejected_bad = not any(x.get("ok") for x in (r_acc1, r_acc2, r_emp_nul, r_msg_nul))
    survived_queries = isinstance(r_q1.get("ok"), bool) and isinstance(r_q2.get("ok"), bool) and bool(r_can.get("ok"))
    passed = inv_ok and rejected_bad and survived_queries and raw_code == 400
    return passed, f"bad_nul_rejected={rejected_bad} raw_nul_http={raw_code} {inv_msg}"


def w10_plant_canary_schema_and_unicode_boundaries(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        cases: list[dict[str, Any]] = [
            {"doc_title": "", "assignment": {emps[0]: "v1"}},
            {"doc_title": "   \t\n  ", "assignment": {emps[0]: "v1"}},
            {"doc_title": "x" * 121, "assignment": {emps[0]: "v1"}},
            {"doc_title": "ok", "assignment": {}},
            {"doc_title": "ok", "assignment": {emps[0]: ""}},
            {"doc_title": "ok", "assignment": {emps[0]: "   "}},
            {"doc_title": "ok", "assignment": {emps[0]: "v" * 21}},
            {"doc_title": "ok", "assignment": {emps[0]: 123}},
            {"doc_title": "ok", "assignment": {emps[0]: None}},
            {"doc_title": "ok", "assignment": {emps[0]: ["v1"]}},
            {"doc_title": "ok", "assignment": {"\u043500": "v1"}},
            {"doc_title": "ok", "assignment": {f"{emps[0]}\u200b": "v1"}},
            {
                "doc_title": "ok",
                "assignment": {emps[0]: "v1", emps[1]: "v2", emps[2]: "v3", emps[3]: "v4"},
            },
        ]
        accepted = sum(1 for c in cases if ws.call("plant_canary", c).get("ok"))
        st = ws.call("status", {})["data"]
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    untouched = accepted == 0 and float(st["V"]) == 1.0 and len(st["canaries_planted"]) == 0
    passed = inv_ok and untouched
    return passed, f"cases={len(cases)} accepted={accepted} V={st['V']} {inv_msg}"


def w11_mcp_delete_transport_matrix(srv: ManagedMCPServer) -> tuple[bool, str]:
    c_no_sid, _, _ = srv.raw_http("DELETE", "/mcp")
    c_forged, _, _ = srv.raw_http("DELETE", "/mcp", headers={"Mcp-Session-Id": "forged-sid-999"})
    c_ctrl, _, _ = srv.raw_http("DELETE", "/mcp", headers={"Mcp-Session-Id": "bad sid"})

    ws = WireSession(srv.port)
    ws.initialize()
    sid = ws.session
    assert sid is not None
    c_valid = ws.delete_session()
    c_second, _, _ = srv.raw_http("DELETE", "/mcp", headers={"Mcp-Session-Id": sid})
    c_post_dead, _, _ = srv.raw_http(
        "POST",
        "/mcp",
        body=b'{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-06-18",
            "Mcp-Session-Id": sid,
        },
    )
    ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    passed = (
        inv_ok
        and c_no_sid == 400
        and c_forged == 404
        and c_ctrl in (400, 404)
        and c_valid == 200
        and c_second == 404
        and c_post_dead == 404
    )
    return passed, f"codes=({c_no_sid},{c_forged},{c_ctrl},{c_valid},{c_second},{c_post_dead}) {inv_msg}"


def w12_mcp_get_sse_transport_matrix(srv: ManagedMCPServer) -> tuple[bool, str]:
    c_no_acc, _, _ = srv.raw_http("GET", "/mcp", headers={"Accept": "application/json"})
    c_no_sid, _, _ = srv.raw_http("GET", "/mcp", headers={"Accept": "text/event-stream"})
    c_forged, _, _ = srv.raw_http(
        "GET",
        "/mcp",
        headers={"Accept": "text/event-stream", "Mcp-Session-Id": "forged-sse-sid"},
    )

    ws = WireSession(srv.port)
    ws.initialize()
    sid = ws.session
    assert sid is not None
    sse_conn1 = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=8.0)
    try:
        sse_conn1.request(
            "GET",
            "/mcp",
            headers={"Accept": "text/event-stream", "Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"},
        )
        r1 = sse_conn1.getresponse()
        c_sse1 = int(r1.status)
        ct_sse1 = r1.getheader("Content-Type", "")
        c_dup = 0
        inproc = srv._inproc_server is not None
        for _ in range(10):
            time.sleep(0.005 if inproc else 0.03)
            c_dup, _, _ = srv.raw_http(
                "GET",
                "/mcp",
                headers={"Accept": "text/event-stream", "Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"},
                timeout=0.4 if inproc else 10.0,
            )
            if c_dup == 409:
                break
    finally:
        sse_conn1.close()

    alive_after = bool(ws.call("status", {}).get("ok"))
    ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    passed = (
        inv_ok
        and c_no_acc == 406
        and c_no_sid == 400
        and c_forged == 404
        and c_sse1 == 200
        and "text/event-stream" in ct_sse1
        and c_dup == 409
        and alive_after
    )
    return passed, f"no_acc={c_no_acc} no_sid={c_no_sid} forged={c_forged} sse1={c_sse1} dup={c_dup} {inv_msg}"


def w13_wrong_content_type_and_accept(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        sid = ws.session
        assert sid is not None
        acc_body = json.dumps({
            "jsonrpc": "2.0",
            "id": 70,
            "method": "tools/call",
            "params": {"name": "accuse", "arguments": {"employee": emps[0]}},
        }).encode("utf-8")

        header_variants = [
            {"Content-Type": "text/plain", "Accept": "application/json, text/event-stream", "Mcp-Session-Id": sid},
            {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": sid,
            },
            {
                "Content-Type": "multipart/form-data; boundary=xyz",
                "Accept": "application/json, text/event-stream",
                "Mcp-Session-Id": sid,
            },
            {"Accept": "application/json, text/event-stream", "Mcp-Session-Id": sid},
            {"Content-Type": "application/json", "Accept": "application/json", "Mcp-Session-Id": sid},
            {"Content-Type": "application/json", "Accept": "text/html", "Mcp-Session-Id": sid},
        ]
        codes = [srv.raw_http("POST", "/mcp", body=acc_body, headers=h)[0] for h in header_variants]
        still_alive = bool(ws.call("status", {}).get("ok"))
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    expected = all(c in (400, 415) for c in codes[:4]) and codes[4:] == [406, 406]
    passed = inv_ok and expected and still_alive
    return passed, f"codes={codes} alive={still_alive} {inv_msg}"


def _raw_socket_send(port: int, payload: bytes, read_reply: bool = True) -> bytes:
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(payload)
        if not read_reply:
            return b""
        chunks: list[bytes] = []
        while True:
            try:
                blk = sock.recv(4096)
            except OSError:
                break
            if not blk:
                break
            chunks.append(blk)
        return b"".join(chunks)


def w14_chunked_and_truncated_json(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        sid = ws.session
        assert sid is not None

        valid_json = b'{"jsonrpc":"2.0","id":81,"method":"tools/call","params":{"name":"status","arguments":{}}}'
        c1, c2, c3 = valid_json[:18], valid_json[18:45], valid_json[45:]
        chunked_ok_req = (
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n"
            f"Content-Type: application/json\r\nAccept: application/json, text/event-stream\r\n"
            f"MCP-Protocol-Version: 2025-06-18\r\nMcp-Session-Id: {sid}\r\n"
            f"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
            f"{len(c1):x}\r\n".encode("ascii") + c1 + b"\r\n"
            + f"{len(c2):x}\r\n".encode("ascii") + c2 + b"\r\n"
            + f"{len(c3):x}\r\n".encode("ascii") + c3 + b"\r\n0\r\n\r\n"
        )
        rep_ok = _raw_socket_send(srv.port, chunked_ok_req, read_reply=True)

        trunc_json = (
            b'{"jsonrpc":"2.0","id":82,"method":"tools/call","params":{"name":"accuse","arguments":{"employee":"'
            + emps[0].encode("utf-8")
        )
        chunked_trunc_req = (
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n"
            f"Content-Type: application/json\r\nAccept: application/json, text/event-stream\r\n"
            f"MCP-Protocol-Version: 2025-06-18\r\nMcp-Session-Id: {sid}\r\n"
            f"Transfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
            f"{len(trunc_json):x}\r\n".encode("ascii") + trunc_json + b"\r\n0\r\n\r\n"
        )
        rep_trunc = _raw_socket_send(srv.port, chunked_trunc_req, read_reply=True)

        abrupt_chunk = (
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n"
            f"Content-Type: application/json\r\nAccept: application/json, text/event-stream\r\n"
            f"Mcp-Session-Id: {sid}\r\nTransfer-Encoding: chunked\r\n\r\nff\r\n{{\"jsonrpc\":".encode("ascii")
        )
        _raw_socket_send(srv.port, abrupt_chunk, read_reply=False)

        abrupt_cl = (
            f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{srv.port}\r\n"
            f"Content-Type: application/json\r\nAccept: application/json, text/event-stream\r\n"
            f"Mcp-Session-Id: {sid}\r\nContent-Length: 500\r\n\r\n{{\"jsonrpc\":\"2.0\"".encode("ascii")
        )
        _raw_socket_send(srv.port, abrupt_cl, read_reply=False)

        concat_body = (
            b'{"jsonrpc":"2.0","id":83,"method":"tools/list","params":{}}'
            b'{"jsonrpc":"2.0","id":84,"method":"tools/call","params":{"name":"accuse","arguments":{"employee":"'
            + emps[0].encode("utf-8")
            + b'"}}}'
        )
        c_concat, _, _ = ws.raw_post(concat_body)
        c_empty, _, _ = ws.raw_post(b"")
        alive = bool(ws.call("status", {}).get("ok"))
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    ok_200 = rep_ok.startswith(b"HTTP/1.1 200")
    trunc_400 = rep_trunc.startswith(b"HTTP/1.1 400")
    passed = inv_ok and ok_200 and trunc_400 and c_concat == 400 and c_empty == 400 and alive
    return passed, f"chunk_ok={ok_200} chunk_trunc_400={trunc_400} concat={c_concat} empty={c_empty} {inv_msg}"


def w15_http_methods_and_dns_rebinding(srv: ManagedMCPServer) -> tuple[bool, str]:
    c_put, _, _ = srv.raw_http("PUT", "/mcp", body=b"{}")
    c_patch, _, _ = srv.raw_http("PATCH", "/mcp", body=b"{}")
    c_opt, _, _ = srv.raw_http("OPTIONS", "/mcp")
    c_head_led, b_head_led, _ = srv.raw_http("HEAD", "/ledger")

    init_body = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "r", "version": "0"}},
    }).encode("utf-8")
    c_evil_host, _, _ = srv.raw_http(
        "POST",
        "/mcp",
        body=init_body,
        headers={
            "Host": "evil.attacker.invalid",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    c_evil_origin, _, _ = srv.raw_http(
        "POST",
        "/mcp",
        body=init_body,
        headers={
            "Origin": "http://evil.attacker.invalid",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    inv_ok, inv_msg = srv.check_invariants()
    passed = (
        inv_ok
        and c_put == 405
        and c_patch == 405
        and c_opt == 405
        and c_head_led in (403, 405)
        and b_head_led == b""
        and c_evil_host in (403, 421)
        and c_evil_origin == 403
    )
    return passed, f"methods=({c_put},{c_patch},{c_opt}) host={c_evil_host} origin={c_evil_origin} {inv_msg}"


def w16_jsonrpc_methods_versions_and_ids(srv: ManagedMCPServer) -> tuple[bool, str]:
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        bad_methods = [
            "resources/list",
            "resources/read",
            "prompts/list",
            "prompts/get",
            "roots/list",
            "completion/complete",
            "admin/reset",
            "ledger/get",
        ]
        unexpected_ok = 0
        for idx, m in enumerate(bad_methods):
            body = json.dumps({"jsonrpc": "2.0", "id": 200 + idx, "method": m, "params": {}}).encode("utf-8")
            code, text, hdrs = ws.raw_post(body)
            if code == 200:
                msg = ws.decode_rpc(code, text, hdrs.get("content-type", ""), 200 + idx)
                if msg and "result" in msg and "error" not in msg:
                    unexpected_ok += 1

        id_cases: list[Any] = [None, "", -999, 9007199254740993, "x" * 2048, {"nested": 1}, [1, 2]]
        server_500s = 0
        for raw_id in id_cases:
            body = json.dumps({
                "jsonrpc": "2.0",
                "id": raw_id,
                "method": "tools/call",
                "params": {"name": "status", "arguments": {}},
            }).encode("utf-8")
            code, _, _ = ws.raw_post(body)
            if code >= 500:
                server_500s += 1

        c_ver, _, _ = ws.raw_post(
            b'{"jsonrpc":"2.0","id":301,"method":"tools/list","params":{}}',
            headers={"MCP-Protocol-Version": "1999-01-01"},
        )
        alive = bool(ws.call("status", {}).get("ok"))
    finally:
        ws.close()

    inv_ok, inv_msg = srv.check_invariants()
    passed = inv_ok and unexpected_ok == 0 and server_500s == 0 and c_ver < 500 and alive
    return passed, f"unexpected_method_ok={unexpected_ok} id_500s={server_500s} bad_ver={c_ver} {inv_msg}"


def w17_ledger_hpp_and_header_spoofing(srv: ManagedMCPServer) -> tuple[bool, str]:
    real_tok = srv.ledger_token
    admin_tok = srv.admin_token or "no-admin"
    paths = [
        "/ledger?token=wrong1&token=wrong2",
        "/ledger?token=&token=wrong",
        "/ledger?token=wrong&token=",
        f"/ledger?TOKEN={urllib.parse.quote(real_tok)}",
        f"/ledger?token[]={urllib.parse.quote(real_tok)}",
        f"/ledger?token={urllib.parse.quote(real_tok)}%00",
        f"/ledger?token={urllib.parse.quote(real_tok)}%20",
        "/ledger?token=%ff%fe",
        f"/ledger?token={urllib.parse.quote(real_tok)}&token=wrong",
        f"/ledger?token={urllib.parse.quote(admin_tok)}",
        "/ledger;token=wrong",
    ]
    codes = [srv.raw_http("GET", p)[0] for p in paths]

    spoof_hdrs = [
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-Real-IP": "127.0.0.1", "Forwarded": "for=127.0.0.1;host=127.0.0.1"},
        {"X-Original-URL": "/healthz", "X-Rewrite-URL": "/healthz"},
        {"Authorization": f"Bearer {real_tok}"},
        {"Cookie": f"token={real_tok}"},
    ]
    for h in spoof_hdrs:
        c, raw, _ = srv.raw_http("GET", "/ledger?token=wrong", headers=h)
        codes.append(c)
        if b"accused" in raw or b"episode" in raw:
            return False, "forbidden response leaked ledger fields"

    inv_ok, inv_msg = srv.check_invariants()
    blocked_all = all(c in (403, 404) for c in codes) and 200 not in codes and codes[:10] == [403] * 10
    passed = inv_ok and blocked_all
    return passed, f"probes={len(codes)} codes={sorted(set(codes))} {inv_msg}"


def w18_mid_episode_ledger_redaction_and_hmac(srv: ManagedMCPServer) -> tuple[bool, str]:
    p = tier_params(srv.tier)
    ws = WireSession(srv.port)
    ws.initialize()
    try:
        emps = ws.employee_ids()
        assert ws.call("plant_canary", {"doc_title": "mid-check", "assignment": {emps[0]: "v1"}})["ok"]
        for _ in range(1 if srv._inproc_server is not None else min(4, p.n_days - 1)):
            ws.call("advance_day", {})
        c_mid, mid_led = srv.ledger()
        mid_sig = verify_ledger(mid_led, srv.ledger_key or "")
        mid_redacted = (
            c_mid == 200
            and mid_led.get("done") is False
            and mid_led.get("redacted") == "episode in progress"
            and mid_led.get("ledger") == []
            and float(mid_led.get("score", -1.0)) == 0.0
            and all(k not in mid_led for k in ("V", "final_day", "accused", "correct", "accused_correct"))
        )
        advance_to_horizon(ws, p.n_days + 2)
    finally:
        ws.close()

    c_end, end_led = srv.ledger()
    end_sig = verify_ledger(end_led, srv.ledger_key or "")
    tamper_checks = []
    for field, bad_val in (("score", 1.0), ("V", 1.0), ("accused", "e00"), ("correct", True)):
        forged = copy.deepcopy(end_led)
        forged[field] = bad_val
        tamper_checks.append(not verify_ledger(forged, srv.ledger_key or ""))

    inv_ok, inv_msg = srv.check_invariants()
    passed = (
        inv_ok
        and mid_sig
        and mid_redacted
        and c_end == 200
        and end_led.get("done") is True
        and "V" in end_led
        and end_sig
        and all(tamper_checks)
    )
    return passed, f"mid_redacted={mid_redacted} mid_sig={mid_sig} end_sig={end_sig} tamper_blocked={all(tamper_checks)} {inv_msg}"


def w19_admin_reset_unset_vs_wrong_token(tier: str, seed: int, tmp_root: Path) -> tuple[bool, str]:
    srv_unset = ManagedMCPServer(tier, seed, tmp_root=tmp_root, with_admin_token=False)
    try:
        body = json.dumps({"tier": tier, "seed": seed}).encode("utf-8")
        unset_probes = [
            "/admin/reset",
            "/admin/reset?token=",
            "/admin/reset?token=admin",
            f"/admin/reset?token={urllib.parse.quote(srv_unset.ledger_token)}",
            "/admin/reset?token=a&token=b",
        ]
        unset_codes = [
            srv_unset.raw_http("POST", path, body=body, headers={"Content-Type": "application/json"})[0]
            for path in unset_probes
        ]
        inv_unset, _ = srv_unset.check_invariants()
    finally:
        srv_unset.stop()

    srv_set = ManagedMCPServer(tier, seed, tmp_root=tmp_root, with_admin_token=True)
    try:
        atok = srv_set.admin_token
        assert atok is not None
        ep_before = srv_set.ledger()[1].get("episode")
        auth_fail_paths = [
            "/admin/reset",
            "/admin/reset?token=wrong",
            f"/admin/reset?token={urllib.parse.quote(srv_set.ledger_token)}",
            f"/admin/reset?token={urllib.parse.quote(atok)}&token=wrong",
        ]
        auth_codes = [
            srv_set.raw_http(
                "POST",
                path,
                body=json.dumps({"tier": tier, "seed": seed}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )[0]
            for path in auth_fail_paths
        ]
        q_ok = urllib.parse.urlencode({"token": atok})
        bad_bodies = [
            json.dumps({"tier": tier, "seed": 7}).encode("utf-8"),
            json.dumps({"tier": "nonexistent_tier", "seed": seed}).encode("utf-8"),
            json.dumps({"tier": tier, "seed": "not_an_int"}).encode("utf-8"),
            b"{broken_json",
            b"[1, 2, 3]",
        ]
        bad_body_codes = [
            srv_set.raw_http("POST", f"/admin/reset?{q_ok}", body=b, headers={"Content-Type": "application/json"})[0]
            for b in bad_bodies
        ]
        ep_still = srv_set.ledger()[1].get("episode")
        inv_set, inv_msg = srv_set.check_invariants()
    finally:
        srv_set.stop()

    passed = (
        inv_unset
        and inv_set
        and all(c == 403 for c in unset_codes)
        and all(c == 403 for c in auth_codes)
        and all(c == 400 for c in bad_body_codes)
        and ep_before == ep_still
    )
    return passed, f"unset={sorted(set(unset_codes))} wrong={sorted(set(auth_codes))} bad_body={sorted(set(bad_body_codes))} {inv_msg}"


def w20_cross_tier_reset_and_leak_audit(srv: ManagedMCPServer) -> tuple[bool, str]:
    orig_tier, orig_seed = srv.tier, srv.seed
    expected_counts = {"easy": 12, "medium": 20, "hard": 40, "hard_forge": 40}
    seen_tokens: set[str] = set()
    leaks_found: list[str] = []
    counts_ok = True
    try:
        for t_name in ALL_TIERS:
            ep_tok = srv.reset(t_name, orig_seed)
            seen_tokens.add(ep_tok)
            ws = WireSession(srv.port)
            try:
                ws.initialize()
                emps = ws.employee_ids()
                if len(emps) != expected_counts[t_name]:
                    counts_ok = False
                blob = json.dumps({
                    "instructions": ws.instructions,
                    "tools": ws.list_tools(),
                    "status": ws.call("status", {}),
                    "docs": ws.call("list_documents", {}),
                })
                needles = [
                    str(orig_seed),
                    f"{t_name}:{orig_seed}",
                    srv.ledger_token,
                    srv.admin_token or "",
                    srv.ledger_key or "",
                    srv.world_secret or "",
                ]
                for n in needles:
                    if n and n in blob:
                        leaks_found.append(n[:8])
            finally:
                ws.close()
        srv.reset(orig_tier, orig_seed)
    except Exception:
        srv.reset(orig_tier, orig_seed)
        raise

    inv_ok, inv_msg = srv.check_invariants()
    passed = inv_ok and counts_ok and len(seen_tokens) == len(ALL_TIERS) and not leaks_found
    return passed, f"unique_ep_tokens={len(seen_tokens)} counts_ok={counts_ok} leaks={len(leaks_found)} {inv_msg}"


def w21_proc_environ_cmdline_fd_secret_hygiene(tier: str, seed: int, tmp_root: Path) -> tuple[bool, str]:
    marker = f"w2proc{secrets.token_hex(4)}"
    srv = ManagedMCPServer(tier, seed, tmp_root=tmp_root, marker_prefix=marker)
    try:
        assert srv.proc is not None
        pid = srv.proc.pid
        files_deleted = all(not p.exists() for p in srv.secret_paths.values())

        fd_dir = Path(f"/proc/{pid}/fd")
        fdinfo_73 = Path(f"/proc/{pid}/fdinfo/{BOOT_FD}")
        open_fds = {}
        for entry in fd_dir.iterdir():
            try:
                open_fds[entry.name] = os.readlink(entry)
            except OSError:
                continue
        boot_fd_closed = str(BOOT_FD) not in open_fds and not fdinfo_73.exists()
        bad_fd_targets = [
            target for target in open_fds.values()
            if "canary-cfg" in target or marker in target or any(str(p) in target for p in srv.secret_paths.values())
        ]

        raw_env = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", errors="replace")
        raw_cmd = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", errors="replace")
        env_entries = [x for x in raw_env.split("\x00") if x]
        env_keys = {x.split("=", 1)[0] for x in env_entries if "=" in x}

        forbidden_vars = (set(SECRET_FILE_VARS) | set(PLAIN_SECRET_VARS) | {"CANARY_CONSUME_SECRET_FILES"}) & env_keys
        bootstrapped_present = "CANARY_BOOTSTRAPPED=1" in env_entries

        secret_strings = [
            marker,
            str(seed),
            srv.ledger_token,
            srv.admin_token or "",
            srv.ledger_key or "",
            srv.world_secret or "",
            *(str(p) for p in srv.secret_paths.values()),
        ]
        env_leaks = [s[:10] for s in secret_strings if s and s in raw_env]
        cmd_leaks = [s[:10] for s in secret_strings if s and s in raw_cmd]
        log_text = srv.log_path.read_text(encoding="utf-8", errors="replace") if srv.log_path.exists() else ""
        log_leaks = [s[:10] for s in secret_strings if s and s in log_text]

        inv_ok, inv_msg = srv.check_invariants()
    finally:
        srv.stop()

    passed = (
        inv_ok
        and files_deleted
        and boot_fd_closed
        and not bad_fd_targets
        and not forbidden_vars
        and bootstrapped_present
        and not env_leaks
        and not cmd_leaks
        and not log_leaks
    )
    detail = (
        f"files_deleted={files_deleted} fd73_closed={boot_fd_closed} open_fds={len(open_fds)} "
        f"bad_fds={len(bad_fd_targets)} env_leaks={len(env_leaks)} cmd_leaks={len(cmd_leaks)} "
        f"log_leaks={len(log_leaks)} {inv_msg}"
    )
    return passed, detail


def w22_spoofed_bootstrapped_without_fd73(tier: str, seed: int, tmp_root: Path) -> tuple[bool, str]:
    port1 = free_port()
    env1 = base_clean_env()
    env1.update({"CANARY_HOST": "127.0.0.1", "CANARY_PORT": str(port1), "CANARY_BOOTSTRAPPED": "1"})
    p1 = subprocess.run(
        [sys.executable, "-m", "canary.mcp_server"],
        env=env1,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=15,
    )

    port2 = free_port()
    env2 = base_clean_env()
    env2.update({
        "CANARY_HOST": "127.0.0.1",
        "CANARY_PORT": str(port2),
        "CANARY_BOOTSTRAPPED": "1",
        "CANARY_TIER": tier,
        "CANARY_SEED": str(seed),
        "CANARY_LEDGER_TOKEN": "fallback-must-not-work",
    })
    p2 = subprocess.run(
        [sys.executable, "-m", "canary.mcp_server"],
        env=env2,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=15,
    )

    passed = p1.returncode != 0 and p2.returncode != 0 and "fallback-must-not-work" not in p2.stderr
    return passed, f"rc_bare={p1.returncode} rc_with_plain_env={p2.returncode}"


def _run_with_fd73_bytes(payload: bytes) -> subprocess.CompletedProcess[str]:
    port = free_port()
    env = base_clean_env()
    env.update({"CANARY_HOST": "127.0.0.1", "CANARY_PORT": str(port), "CANARY_BOOTSTRAPPED": "1"})
    r_fd, w_fd = os.pipe()
    os.write(w_fd, payload)
    os.close(w_fd)
    saved_73: int | None = None
    try:
        try:
            os.fstat(BOOT_FD)
            saved_73 = os.dup(BOOT_FD)
        except OSError:
            saved_73 = None
        if r_fd != BOOT_FD:
            os.dup2(r_fd, BOOT_FD)
            os.close(r_fd)
        os.set_inheritable(BOOT_FD, True)
        return subprocess.run(
            [sys.executable, "-m", "canary.mcp_server"],
            env=env,
            cwd=str(REPO),
            pass_fds=(BOOT_FD,),
            capture_output=True,
            text=True,
            timeout=15,
        )
    finally:
        try:
            os.close(BOOT_FD)
        except OSError:
            pass
        if saved_73 is not None:
            os.dup2(saved_73, BOOT_FD)
            os.close(saved_73)


def w23_spoofed_bootstrapped_corrupt_or_dev_fd73(tier: str, seed: int, tmp_root: Path) -> tuple[bool, str]:
    dev_boot = json.dumps({
        "tier": tier,
        "seed": 7,
        "world_secret_b64": None,
        "ledger_token": "tok",
        "admin_token": None,
        "ledger_key": None,
    }).encode("utf-8")
    cases = [
        ("empty", b""),
        ("bad_utf8", b"\xff\xfe{not-utf8"),
        ("missing_keys", b"{}"),
        ("dev_seed", dev_boot),
    ]
    rcs: dict[str, int] = {}
    for label, raw in cases:
        res = _run_with_fd73_bytes(raw)
        rcs[label] = res.returncode
    passed = all(rc != 0 for rc in rcs.values()) and rcs["dev_seed"] == 2
    return passed, f"rcs={rcs}"


def w24_consume_secret_files_fail_closed(tier: str, seed: int, tmp_root: Path) -> tuple[bool, str]:
    d = tmp_root / f"w24-{secrets.token_hex(5)}"
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    try:
        def run_env(extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
            env = base_clean_env()
            env.update({
                "CANARY_HOST": "127.0.0.1",
                "CANARY_PORT": str(free_port()),
                "CANARY_CONSUME_SECRET_FILES": "1",
                **extra,
            })
            return subprocess.run(
                [sys.executable, "-m", "canary.mcp_server"],
                env=env,
                cwd=str(REPO),
                capture_output=True,
                text=True,
                timeout=15,
            )

        p_missing = run_env({"CANARY_EPISODE_FILE": str(d / "missing.json")})

        empty_tok = d / "empty_tok"
        write_0600(empty_tok, "   \n")
        valid_ep = d / "valid_ep.json"
        write_0600(valid_ep, json.dumps({"tier": tier, "seed": seed}))
        p_empty = run_env({"CANARY_EPISODE_FILE": str(valid_ep), "CANARY_LEDGER_TOKEN_FILE": str(empty_tok)})

        bad_ep = d / "bad_ep.json"
        canary_secret = "ULTRA_SECRET_PAYLOAD_99182"
        write_0600(bad_ep, f"not-json-{canary_secret}")
        p_bad_ep = run_env({"CANARY_EPISODE_FILE": str(bad_ep)})

        short_ws = d / "short_ws"
        short_secret = "SHORT_SEC_771"
        write_0600(short_ws, short_secret)
        valid_ep2 = d / "valid_ep2.json"
        write_0600(valid_ep2, json.dumps({"tier": tier, "seed": seed}))
        p_short = run_env({"CANARY_EPISODE_FILE": str(valid_ep2), "CANARY_WORLD_SECRET_FILE": str(short_ws)})

        rcs = [p_missing.returncode, p_empty.returncode, p_bad_ep.returncode, p_short.returncode]
        combined_out = p_bad_ep.stdout + p_bad_ep.stderr + p_short.stdout + p_short.stderr
        no_leak = canary_secret not in combined_out and short_secret not in combined_out
    finally:
        shutil.rmtree(d, ignore_errors=True)

    passed = all(rc == 2 for rc in rcs) and no_leak
    return passed, f"rcs={rcs} secret_echo_blocked={no_leak}"


EPISODE_VECTORS: tuple[tuple[str, str, str, Callable[[ManagedMCPServer], tuple[bool, str]]], ...] = (
    ("W01", "concurrent_plant_canary_race", "16 threads race plant_canary on day 1 against canaries_per_day cap", w01_concurrent_plant_canary_race),
    ("W02", "concurrent_action_cap_race", "16 threads race investigative calls against 8 actions_per_day cap", w02_concurrent_action_cap_race),
    ("W03", "concurrent_restrict_unrestrict_advance", "16 threads interleave restrict/unrestrict/status/advance_day + exact ledger V check", w03_concurrent_restrict_unrestrict_advance),
    ("W04", "concurrent_tool_cap_cliff_race", "16 threads race status + accuse across the global tool_call_cap cliff", w04_concurrent_tool_cap_cliff_race),
    ("W05", "concurrent_delete_session_persistence", "concurrent DELETE /mcp + in-flight calls; verify episode state/costs persist", w05_concurrent_delete_session_persistence),
    ("W06", "json_unicode_escaped_keys", "raw JSON unicode-escaped keys (\\u0065mployee, \\u0073core, \\u006dethod)", w06_json_unicode_escaped_keys),
    ("W07", "duplicate_nested_keys_plant_canary", "duplicate nested keys in plant_canary assignment + restricted/max_variants check", w07_duplicate_nested_keys_plant_canary),
    ("W08", "ieee754_numbers_and_types", "bare NaN, Infinity, -Infinity, -0.0, 1e309, booleans, 10^30 in args and JSON-RPC id", w08_ieee754_numbers_and_types),
    ("W09", "nul_bytes_in_strings_and_wire", "escaped and raw NUL bytes in doc_title, query, employee, message id", w09_nul_bytes_in_strings_and_wire),
    ("W10", "plant_canary_schema_and_unicode_boundaries", "13 boundary/unicode/homoglyph/type-confusion plant_canary payloads", w10_plant_canary_schema_and_unicode_boundaries),
    ("W11", "mcp_delete_transport_matrix", "DELETE /mcp with missing, forged, invalid, valid, and already-terminated sessions", w11_mcp_delete_transport_matrix),
    ("W12", "mcp_get_sse_transport_matrix", "GET /mcp SSE Accept/session validation + 409 Conflict on duplicate SSE stream", w12_mcp_get_sse_transport_matrix),
    ("W13", "wrong_content_type_and_accept", "POST /mcp with wrong/missing Content-Type (415) and incomplete Accept (406)", w13_wrong_content_type_and_accept),
    ("W14", "chunked_and_truncated_json", "HTTP/1.1 chunked valid/truncated JSON, mid-stream socket drops, concatenated JSON", w14_chunked_and_truncated_json),
    ("W15", "http_methods_and_dns_rebinding", "PUT/PATCH/OPTIONS /mcp, HEAD /ledger, and DNS-rebinding Host/Origin headers", w15_http_methods_and_dns_rebinding),
    ("W16", "jsonrpc_methods_versions_and_ids", "non-tool MCP methods, extreme/typed JSON-RPC ids, bogus MCP-Protocol-Version", w16_jsonrpc_methods_versions_and_ids),
    ("W17", "ledger_hpp_and_header_spoofing", "16 /ledger query-param pollution, cross-token, URL-byte, and proxy-header probes", w17_ledger_hpp_and_header_spoofing),
    ("W18", "mid_episode_ledger_redaction_and_hmac", "mid-episode /ledger redaction + end-of-episode HMAC-SHA256 tamper verification", w18_mid_episode_ledger_redaction_and_hmac),
    ("W20", "cross_tier_reset_and_leak_audit", "admin reset across easy/medium/hard/hard_forge checking token rotation and zero secret leak", w20_cross_tier_reset_and_leak_audit),
)

PROCESS_VECTORS: tuple[tuple[str, str, str, Callable[[str, int, Path], tuple[bool, str]]], ...] = (
    ("W19", "admin_reset_unset_vs_wrong_token", "POST /admin/reset on unset-token server vs wrong/cross-token/dev-seed/corrupt body", w19_admin_reset_unset_vs_wrong_token),
    ("W21", "proc_environ_cmdline_fd_secret_hygiene", "Linux /proc/<pid>/{environ,cmdline,fd,fdinfo} audit on CANARY_CONSUME_SECRET_FILES=1", w21_proc_environ_cmdline_fd_secret_hygiene),
    ("W22", "spoofed_bootstrapped_without_fd73", "spoofed CANARY_BOOTSTRAPPED=1 without fd 73 (bare and with plain env vars)", w22_spoofed_bootstrapped_without_fd73),
    ("W23", "spoofed_bootstrapped_corrupt_or_dev_fd73", "spoofed CANARY_BOOTSTRAPPED=1 with empty, non-UTF8, incomplete, and dev-seed fd 73", w23_spoofed_bootstrapped_corrupt_or_dev_fd73),
    ("W24", "consume_secret_files_fail_closed", "CANARY_CONSUME_SECRET_FILES=1 fail-closed exit 2 and zero secret echo on bad files", w24_consume_secret_files_fail_closed),
)


def run_full_sweep(
    tiers: tuple[str, ...] = ALL_TIERS,
    seeds: tuple[int, ...] = ALL_SEEDS,
    tmp_root: Path = DEFAULT_TMP_ROOT,
    vectors: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    wanted = set(vectors) if vectors is not None else None
    ep_vecs = tuple(v for v in EPISODE_VECTORS if wanted is None or v[0] in wanted)
    proc_vecs = tuple(v for v in PROCESS_VECTORS if wanted is None or v[0] in wanted)
    tmp_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    try:
        if ep_vecs:
            for tier in tiers:
                srv = ManagedMCPServer(tier, seeds[0], tmp_root=tmp_root)
                try:
                    for seed in seeds:
                        for vid, vname, vdesc, vfn in ep_vecs:
                            srv.reset(tier, seed)
                            vt0 = time.time()
                            try:
                                held, note = vfn(srv)
                            except Exception as exc:
                                held, note = False, f"exception {type(exc).__name__}: {str(exc)[:140]}"
                            records.append({
                                "id": vid,
                                "name": vname,
                                "how": vdesc,
                                "tier": tier,
                                "seed": seed,
                                "held": bool(held),
                                "secs": round(time.time() - vt0, 3),
                                "note": note,
                            })
                finally:
                    srv.stop()

        if proc_vecs:
            for tier in tiers:
                p_seeds = tuple(s for s in PAIRED_SEEDS.get(tier, seeds[:1])[:1] if s in seeds) or seeds[:1]
                for seed in p_seeds:
                    for vid, vname, vdesc, pfn in proc_vecs:
                        vt0 = time.time()
                        try:
                            held, note = pfn(tier, seed, tmp_root)
                        except Exception as exc:
                            held, note = False, f"exception {type(exc).__name__}: {str(exc)[:140]}"
                        records.append({
                            "id": vid,
                            "name": vname,
                            "how": vdesc,
                            "tier": tier,
                            "seed": seed,
                            "held": bool(held),
                            "secs": round(time.time() - vt0, 3),
                            "note": note,
                        })
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    all_specs = sorted(
        [(v[0], v[1], v[2]) for v in ep_vecs] + [(v[0], v[1], v[2]) for v in proc_vecs],
        key=lambda x: x[0],
    )
    vector_rows: list[dict[str, Any]] = []
    for vid, vname, vdesc in all_specs:
        sub = [r for r in records if r["id"] == vid]
        held_cnt = sum(1 for r in sub if r["held"])
        by_tier = {}
        for tier in tiers:
            tsub = [r for r in sub if r["tier"] == tier]
            by_tier[tier] = f"{sum(1 for r in tsub if r['held'])}/{len(tsub)}"
        sample_note = next((r["note"] for r in sub if not r["held"]), sub[0]["note"] if sub else "")
        vector_rows.append({
            "id": vid,
            "name": vname,
            "how": vdesc,
            "runs": len(sub),
            "held_runs": held_cnt,
            "all_held": held_cnt == len(sub),
            "by_tier": by_tier,
            "total_secs": round(sum(r["secs"] for r in sub), 2),
            "sample_note": sample_note,
        })

    elapsed = round(time.time() - t0, 2)
    total_runs = len(records)
    total_held = sum(1 for r in records if r["held"])
    vectors_held = sum(1 for v in vector_rows if v["all_held"])
    return {
        "tiers": list(tiers),
        "seeds": list(seeds),
        "total_vectors": len(vector_rows),
        "vectors_held": vectors_held,
        "total_runs": total_runs,
        "runs_held": total_held,
        "elapsed_secs": elapsed,
        "vectors": vector_rows,
        "failures": [r for r in records if not r["held"]],
    }


def format_summary_table(summary: dict[str, Any]) -> str:
    lines = [
        "| ID | Vector | Runs (held/total) | easy | medium | hard | hard_forge | Time (s) | Sample observation | Held |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for v in summary["vectors"]:
        bt = v["by_tier"]
        note = str(v["sample_note"]).replace("|", "/")
        lines.append(
            f"| {v['id']} | `{v['name']}` | {v['held_runs']}/{v['runs']} | "
            f"{bt.get('easy', '-')} | {bt.get('medium', '-')} | {bt.get('hard', '-')} | {bt.get('hard_forge', '-')} | "
            f"{v['total_secs']:.2f} | {note} | {'yes' if v['all_held'] else 'NO'} |"
        )
    lines.append("")
    lines.append(
        f"Summary: {summary['vectors_held']}/{summary['total_vectors']} vectors held across "
        f"{summary['runs_held']}/{summary['total_runs']} live subprocess runs "
        f"(tiers={','.join(summary['tiers'])}, seeds={summary['seeds'][0]}-{summary['seeds'][-1]}, "
        f"elapsed={summary['elapsed_secs']:.2f}s)."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_mcp_wire_sweep.py")
    ap.add_argument("--tiers", default=",".join(ALL_TIERS))
    ap.add_argument("--seeds", default="900005-900012")
    ap.add_argument("--vectors", default=None)
    ap.add_argument("--tmp-root", type=Path, default=DEFAULT_TMP_ROOT)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)

    tiers = tuple(t.strip() for t in args.tiers.split(",") if t.strip())
    if "-" in args.seeds:
        lo_s, hi_s = args.seeds.split("-", 1)
        seeds = tuple(range(int(lo_s), int(hi_s) + 1))
    else:
        seeds = tuple(int(x.strip()) for x in args.seeds.split(",") if x.strip())
    vectors = tuple(v.strip() for v in args.vectors.split(",") if v.strip()) if args.vectors else None

    summary = run_full_sweep(tiers=tiers, seeds=seeds, tmp_root=args.tmp_root, vectors=vectors)
    print(format_summary_table(summary))
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["runs_held"] == summary["total_runs"] else 1


if __name__ == "__main__":
    sys.exit(main())
