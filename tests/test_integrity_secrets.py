"""EXPLOITS #25 (found by the external Grok judge run): a same-uid process could read the
MCP server's environment (/proc/<pid>/environ, `ps eww`) and get CANARY_SEED,
CANARY_WORLD_SECRET and CANARY_LEDGER_TOKEN, then regenerate the world and score 1.0.

Design under test (owner: HARNESS mcp_server; primary mitigation is the Harbor sidecar,
which has no shared PID namespace): secrets reach the server ONLY through 0600 files named by
CANARY_WORLD_SECRET_FILE, CANARY_LEDGER_TOKEN_FILE and CANARY_EPISODE_FILE ({"tier","seed"}).
Deleting from os.environ at runtime does NOT help: /proc/<pid>/environ is the exec-time block.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

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
