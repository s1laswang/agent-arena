"""EXPLOITS #25 (found by the external Grok judge run): a same-uid process could read the
MCP server's environment (/proc/<pid>/environ, `ps eww`) and get CANARY_SEED,
CANARY_WORLD_SECRET and CANARY_LEDGER_TOKEN, then regenerate the world and score 1.0.

Design under test (owner: HARNESS mcp_server; primary mitigation is the Harbor sidecar,
which has no shared PID namespace): secrets reach the server ONLY through 0600 files named by
CANARY_WORLD_SECRET_FILE, CANARY_LEDGER_TOKEN_FILE and CANARY_EPISODE_FILE ({"tier","seed"}).
Deleting from os.environ at runtime does NOT help: /proc/<pid>/environ is the exec-time block.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from canary.mcp_server import spawn_isolated_server

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def _proc_environ(pid: int) -> str:
    """What a same-uid attacker sees of the server's environment."""
    p = Path(f"/proc/{pid}/environ")
    if p.exists():
        return p.read_bytes().replace(b"\0", b"\n").decode(errors="replace")
    out = subprocess.run(["ps", "eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True)
    return out.stdout


def _supports_file_secrets() -> bool:
    src = (ROOT / "canary" / "mcp_server.py")
    return src.exists() and "CANARY_WORLD_SECRET_FILE" in src.read_text()


@pytest.mark.xfail(not _supports_file_secrets(), strict=True,
                   reason="#25 open: mcp_server reads secrets from env, not CANARY_*_FILE (HARNESS)")
def test_25_server_environ_holds_no_secrets(tmp_path):
    world_secret = "ws-" + secrets.token_hex(16)
    token = "tok-" + secrets.token_hex(16)
    seed = 900_017
    files = {
        "CANARY_WORLD_SECRET_FILE": world_secret,
        "CANARY_LEDGER_TOKEN_FILE": token,
        "CANARY_EPISODE_FILE": json.dumps({"tier": "medium", "seed": seed}),
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    for k, val in files.items():
        f = tmp_path / k.lower()
        f.write_text(val)
        f.chmod(0o600)
        env[k] = str(f)
    port = _free_port()
    env.update(CANARY_HOST="127.0.0.1", CANARY_PORT=str(port), PYTHONPATH=str(ROOT))
    proc = subprocess.Popen([sys.executable, "-m", "canary.mcp_server"], cwd=tmp_path, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 30
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
                break
            except Exception:
                if proc.poll() is not None or time.time() > deadline:
                    pytest.fail(f"server did not start: {proc.stderr.read().decode()[-500:]}")
                time.sleep(0.2)
        leaked = _proc_environ(proc.pid)
        assert world_secret not in leaked, "world secret visible in server environment"
        assert token not in leaked, "ledger token visible in server environment"
        assert str(seed) not in leaked, "episode seed visible in server environment"
        # the files really configured the server: the token unlocks the grader endpoint
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ledger?token={token}", timeout=5) as r:
            assert r.status == 200
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_25_attack_model_reads_env_of_same_uid_process(tmp_path):
    """Sanity: the attacker primitive works on this OS, so the test above is meaningful."""
    marker = "probe-" + secrets.token_hex(8)
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                         env={**os.environ, "CANARY_PROBE": marker})
    try:
        time.sleep(0.3)
        assert marker in _proc_environ(p.pid)
    finally:
        p.terminate(); p.wait()


def _http_get(url: str) -> tuple[int, dict | None]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, None


def _call_mcp_tools(url: str) -> tuple[list[str], dict, dict]:
    from mcp import Client

    async def go():
        async with Client(url) as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            st = json.loads((await client.call_tool("status", {})).content[0].text)
            emps = json.loads((await client.call_tool("list_employees", {})).content[0].text)
            return tools, st, emps

    return asyncio.run(go())


def test_spawn_isolated_server_strips_env_and_serves_mcp_and_ledger(monkeypatch):
    parent_seed = 900_005
    parent_token = "parent-tok-" + secrets.token_hex(16)
    parent_secret = "parent-ws-" + secrets.token_hex(16)
    parent_admin = "parent-adm-" + secrets.token_hex(16)
    monkeypatch.setenv("CANARY_SEED", str(parent_seed))
    monkeypatch.setenv("CANARY_TIER", "easy")
    monkeypatch.setenv("CANARY_LEDGER_TOKEN", parent_token)
    monkeypatch.setenv("CANARY_WORLD_SECRET", parent_secret)
    monkeypatch.setenv("CANARY_ADMIN_TOKEN", parent_admin)

    seed = 900_019
    proc, info = spawn_isolated_server("medium", seed)
    ep_file = Path(info["episode_file"])
    tok_file = Path(info["ledger_token_file"])
    try:
        assert stat.S_IMODE(ep_file.stat().st_mode) == 0o600
        assert stat.S_IMODE(tok_file.stat().st_mode) == 0o600

        child_env = info["env"]
        forbidden_vars = {
            "CANARY_SEED",
            "CANARY_TIER",
            "CANARY_LEDGER_TOKEN",
            "CANARY_WORLD_SECRET",
            "CANARY_ADMIN_TOKEN",
        }
        assert not (set(child_env) & forbidden_vars)
        assert "CANARY_EPISODE_FILE" in child_env
        assert "CANARY_LEDGER_TOKEN_FILE" in child_env

        env_blob = "\n".join(f"{k}={v}" for k, v in child_env.items())
        for needle in (
            "CANARY_SEED",
            "CANARY_WORLD_SECRET",
            str(seed),
            str(parent_seed),
            info["token"],
            parent_token,
            parent_secret,
            parent_admin,
        ):
            assert needle not in env_blob

        leaked = _proc_environ(proc.pid)
        if sys.platform.startswith("linux"):
            proc_env_path = Path(f"/proc/{proc.pid}/environ")
            assert proc_env_path.exists()
            raw_entries = [
                entry.decode(errors="replace")
                for entry in proc_env_path.read_bytes().split(b"\0")
                if entry
            ]
            proc_keys = {entry.split("=", 1)[0] for entry in raw_entries if "=" in entry}
            assert not (proc_keys & forbidden_vars)
            cmdline_path = Path(f"/proc/{proc.pid}/cmdline")
            if cmdline_path.exists():
                leaked = leaked + "\n" + cmdline_path.read_bytes().replace(b"\0", b" ").decode(errors="replace")

        for needle in (
            "CANARY_SEED",
            "CANARY_TIER",
            "CANARY_WORLD_SECRET",
            "CANARY_LEDGER_TOKEN=",
            str(seed),
            str(parent_seed),
            info["token"],
            parent_token,
            parent_secret,
            parent_admin,
        ):
            assert needle not in leaked

        tools, st, emps = _call_mcp_tools(info["url"])
        assert "status" in tools and "accuse" in tools and len(tools) == 13
        assert st["ok"] is True and emps["ok"] is True
        assert str(seed) not in json.dumps([st, emps])

        assert _http_get(f"{info['base']}/ledger")[0] == 403
        assert _http_get(f"{info['base']}/ledger?token={parent_token}")[0] == 403
        code, ledger = _http_get(f"{info['base']}/ledger?token={info['token']}")
        assert code == 200 and ledger is not None
        assert ledger["tier"] == "medium" and isinstance(ledger["ledger"], list)
    finally:
        info["cleanup"]()

    assert proc.poll() is not None
    assert not ep_file.exists() and not tok_file.exists()


def test_spawn_isolated_server_allow_dev_flag():
    with pytest.raises(RuntimeError):
        spawn_isolated_server("easy", 7, allow_dev=False)

    proc, info = spawn_isolated_server("easy", 7, allow_dev=True)
    try:
        assert "CANARY_SEED" not in info["env"]
        assert "CANARY_WORLD_SECRET" not in info["env"]
        assert info["token"] not in _proc_environ(proc.pid)
        code, ledger = _http_get(f"{info['base']}/ledger?token={info['token']}")
        assert code == 200 and ledger is not None and ledger["tier"] == "easy"
    finally:
        info["cleanup"]()


def test_cli_write_episode_file_and_file_flags(tmp_path):
    seed = 900_021
    world_secret = "cli-ws-" + secrets.token_hex(16)
    ep_path = tmp_path / "episode.json"
    tok_path = tmp_path / "ledger_token"
    ws_path = tmp_path / "world_secret"
    ws_path.write_text(world_secret + "\n")
    ws_path.chmod(0o600)

    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    clean_env["PYTHONPATH"] = str(ROOT)

    bad = subprocess.run(
        [sys.executable, "-m", "canary.mcp_server", "--tier", "medium", "--seed", str(seed)],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert bad.returncode == 2

    wr = subprocess.run(
        [
            sys.executable,
            "-m",
            "canary.mcp_server",
            "--write-episode-file",
            str(ep_path),
            "--tier",
            "medium",
            "--seed",
            str(seed),
            "--ledger-token-out",
            str(tok_path),
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wr.returncode == 0
    assert str(seed) not in (wr.stdout + wr.stderr)
    assert stat.S_IMODE(ep_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tok_path.stat().st_mode) == 0o600
    assert json.loads(ep_path.read_text()) == {"tier": "medium", "seed": seed}
    token = tok_path.read_text().strip()
    assert len(token) >= 32 and token not in (wr.stdout + wr.stderr)

    port = _free_port()
    srv_env = dict(clean_env, CANARY_HOST="127.0.0.1", CANARY_PORT=str(port))
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "canary.mcp_server",
            "--episode-file",
            str(ep_path),
            "--ledger-token-file",
            str(tok_path),
            "--world-secret-file",
            str(ws_path),
        ],
        cwd=tmp_path,
        env=srv_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.time() + 30
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1)
                break
            except Exception:
                if proc.poll() is not None or time.time() > deadline:
                    err = proc.stderr.read()[-500:] if proc.stderr else ""
                    pytest.fail(f"server did not start: {err}")
                time.sleep(0.1)

        leaked = _proc_environ(proc.pid)
        for needle in ("CANARY_SEED", "CANARY_WORLD_SECRET", str(seed), token, world_secret):
            assert needle not in leaked

        tools, st, _ = _call_mcp_tools(f"http://127.0.0.1:{port}/mcp")
        assert len(tools) == 13 and st["ok"] is True
        code, ledger = _http_get(f"http://127.0.0.1:{port}/ledger?token={token}")
        assert code == 200 and ledger is not None and ledger["tier"] == "medium"
    finally:
        proc.terminate()
        proc.communicate(timeout=10)
