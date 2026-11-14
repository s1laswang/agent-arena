"""CANARY_CONSUME_SECRET_FILES: secret files are deleted and their paths leave /proc/<pid>/environ.

The eight C-tests live in tests/test_frontier_redteam_canary.py. This file checks the stronger
re-exec: /proc/<pid>/environ no longer contains the secret-file paths.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _proc_environ(pid: int) -> str:
    raw = Path(f"/proc/{pid}/environ").read_bytes()
    return raw.replace(b"\0", b"\n").decode(errors="replace")


def test_mid_episode_ledger_hides_leaks_and_true_v():
    from canary.mcp_server import Episode

    ep = Episode("medium", 900003, "template")
    for _ in range(5):
        ep.call("advance_day", {})
    mid = ep.ledger_payload()
    assert mid["ledger"] == [] and "V" not in mid and mid["score"] == 0.0
    assert mid["redacted"] == "episode in progress" and mid["done"] is False
    emps = ep.call("list_employees", {}).data["employees"]
    ids = [e["id"] if isinstance(e, dict) else e for e in emps]
    ep.call("accuse", {"employee": ids[0]})
    end = ep.ledger_payload()
    assert end["done"] and end["ledger"] and "V" in end and "redacted" not in end


def test_consume_deletes_files_and_drops_paths_from_environ(tmp_path):
    port = _free_port()
    marker = "consume-path-marker"
    ep = tmp_path / f"{marker}-episode.json"
    tok = tmp_path / f"{marker}-ledger-token"
    token = "t" * 24
    ep.write_text(json.dumps({"tier": "medium", "seed": 900003}))
    tok.write_text(token)
    os.chmod(ep, 0o600)
    os.chmod(tok, 0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    env.update(CANARY_EPISODE_FILE=str(ep), CANARY_LEDGER_TOKEN_FILE=str(tok),
               CANARY_PORT=str(port), CANARY_HOST="127.0.0.1", CANARY_CONSUME_SECRET_FILES="1")
    proc = subprocess.Popen([sys.executable, "-m", "canary.mcp_server"], env=env, cwd=ROOT,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.time() + 30
        while True:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/ledger?token={token}", timeout=2).read()
                break
            except Exception:
                if proc.poll() is not None or time.time() > deadline:
                    err = proc.stderr.read().decode(errors="replace")[-800:]
                    raise AssertionError(f"server did not start: {err}")
                time.sleep(0.2)
        assert not ep.exists() and not tok.exists()
        leaked = _proc_environ(proc.pid)
        assert "CANARY_EPISODE_FILE" not in leaked
        assert "CANARY_LEDGER_TOKEN_FILE" not in leaked
        assert str(ep) not in leaked and str(tok) not in leaked
        assert marker not in leaked and token not in leaked
        assert "900003" not in leaked
    finally:
        proc.terminate()
        proc.wait(timeout=10)
