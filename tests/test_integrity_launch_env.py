"""INTEGRITY item 2 (bake-off note): non-Harbor launches keep the seed and ledger token out of the server env."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess

from canary.mcp_server import clean_launch_env, load_config, write_secret_files


def test_secret_files_are_0600_and_load(tmp_path):
    env = write_secret_files("medium", 4242, "tok-abc")
    for var in ("CANARY_EPISODE_FILE", "CANARY_LEDGER_TOKEN_FILE"):
        assert stat.S_IMODE(os.stat(env[var]).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(os.path.dirname(env["CANARY_EPISODE_FILE"])).st_mode) == 0o700
    cfg = load_config(env)
    assert (cfg["tier"], cfg["seed"], cfg["ledger_token"]) == ("medium", 4242, "tok-abc")


def test_clean_launch_env_strips_plain_vars():
    base = {"CANARY_TIER": "hard", "CANARY_SEED": "7", "CANARY_LEDGER_TOKEN": "t", "CANARY_WORLD_SECRET": "s", "PATH": "/bin"}
    assert clean_launch_env(base) == {"PATH": "/bin"}


def test_frontier_server_env_has_no_seed_or_token():
    from canary.agents.frontier.common import Server
    s = Server("easy", 4321).start(timeout=60)
    try:
        if shutil.which("ps"):
            out = subprocess.run(["ps", "eww", "-p", str(s.proc.pid)], capture_output=True, text=True).stdout
        else:
            with open(f"/proc/{s.proc.pid}/environ", "rb") as fh:
                out = fh.read().replace(b"\x00", b" ").decode("utf-8", "replace")
        assert "CANARY_EPISODE_FILE" in out
        assert "CANARY_SEED=" not in out and "CANARY_TIER=" not in out and "CANARY_LEDGER_TOKEN=" not in out
        assert s.token not in out
    finally:
        s.stop()


def test_make_mcp_uses_episode_file():
    mk = open(os.path.join(os.path.dirname(__file__), "..", "Makefile")).read()
    recipe = mk.split("\nmcp:", 1)[1].split("\n\n", 1)[0]
    assert "CANARY_EPISODE_FILE" in recipe and "-u CANARY_SEED" in recipe and "-u CANARY_LEDGER_TOKEN" in recipe
