import asyncio
import contextlib
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

import anyio
import pytest

from harbor.sidecar import effective_id
from lab.run import day_for
from sleeper.company import World
from sleeper.secrets import clear_secrets, scoped_secrets
from sleeper.verifier import signed_ok

REPO_ROOT = str(Path(__file__).resolve().parents[1])
SECRET_ENV_KEYS = (
    "VERIFY_TOKEN",
    "SLEEPER_SALT",
    "SLEEPER_SEED",
    "SLEEPER_SECRETS_FILE",
    "SLEEPER_SECRETS_UNLINK",
)

pytestmark = pytest.mark.skipif(
    not Path("/proc/self/environ").exists(),
    reason="requires Linux /proc filesystem",
)


@pytest.fixture(autouse=True)
def _clean_parent_secrets(monkeypatch):
    for key in SECRET_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    clear_secrets()
    yield
    clear_secrets()


def _fresh_canaries(tag):
    tok = f"vtok_{tag}_{secrets.token_hex(16)}"
    salt = f"salt_{tag}_{secrets.token_hex(16)}"
    seed = str(secrets.randbelow(9 * 10**23) + 10**23)
    assert len({tok, salt, seed}) == 3
    return tok, salt, seed


def _assert_no_secret_bytes(blob, values, extra=()):
    forbidden = [
        b"VERIFY_TOKEN",
        b"SLEEPER_SALT",
        b"SLEEPER_SEED",
        b"SLEEPER_SECRETS_FILE",
        b"SLEEPER_SECRETS_UNLINK",
        *(v.encode("utf-8") for v in values),
        *extra,
    ]
    for item in forbidden:
        assert item not in blob


def _assert_live_proc_isolated(pid, secret_values, extra_cmdline_forbidden=()):
    os.kill(pid, 0)
    env_path = Path(f"/proc/{pid}/environ")
    if os.geteuid() != 0:
        with pytest.raises(PermissionError):
            env_path.read_bytes()
    else:
        raw_env = env_path.read_bytes()
        _assert_no_secret_bytes(raw_env, secret_values)

    cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    assert len(cmdline) > 0
    _assert_no_secret_bytes(cmdline, secret_values, extra=extra_cmdline_forbidden)


def _tool_json(result):
    if getattr(result, "structured_content", None):
        return result.structured_content
    text = "".join(getattr(part, "text", "") for part in result.content)
    return json.loads(text or "{}")


@contextlib.asynccontextmanager
async def _mcp_stdio_session(monkeypatch, cli_args, env, err_path, verify_clean_env=False):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    spawned = []
    captured_envs = []
    orig_open_process = anyio.open_process

    async def _tracked_open_process(*args, **kwargs):
        captured_envs.append(dict(kwargs.get("env") or {}))
        proc = await orig_open_process(*args, **kwargs)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(anyio, "open_process", _tracked_open_process)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "sleeper.mcp_server", *cli_args],
        env=env,
        cwd=REPO_ROOT,
    )
    with open(err_path, "w", encoding="utf-8") as err_fh:
        try:
            async with stdio_client(params, errlog=err_fh) as (read_stream, write_stream):
                monkeypatch.setattr(anyio, "open_process", orig_open_process)
                assert len(spawned) == 1
                if verify_clean_env:
                    for key in ("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED", "SLEEPER_SECRETS_FILE"):
                        assert key not in captured_envs[0]
                proc = spawned[0]
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session, proc
        finally:
            monkeypatch.setattr(anyio, "open_process", orig_open_process)
            for proc in spawned:
                if proc.returncode is None:
                    with contextlib.suppress(ProcessLookupError, OSError):
                        proc.kill()
                    with contextlib.suppress(Exception):
                        await proc.wait()


def test_mcp_server_env_var_isolation_and_signed_state(tmp_path, monkeypatch):
    tok, salt, seed = _fresh_canaries("mcp_env")
    out_path = tmp_path / "mcp_env_state.json"
    err_path = tmp_path / "mcp_env.err"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "GEMINI_API_KEY": "",
        "VERIFY_TOKEN": tok,
        "SLEEPER_SALT": salt,
        "SLEEPER_SEED": seed,
    }

    async def _exercise():
        async with _mcp_stdio_session(
            monkeypatch,
            ["--seat", "finance_ap", "--out", str(out_path)],
            env,
            err_path,
        ) as (session, proc):
            assert proc.returncode is None
            tickets_resp = _tool_json(await session.call_tool("my_tickets", {}))
            assert tickets_resp.get("ok") is True
            assert isinstance(tickets_resp.get("tickets"), list)
            turn_resp = _tool_json(await session.call_tool("end_turn", {}))
            assert turn_resp.get("ok") is True
            assert proc.returncode is None
            _assert_live_proc_isolated(proc.pid, (tok, salt, seed))

    asyncio.run(_exercise())

    assert out_path.is_file(), err_path.read_text(encoding="utf-8")
    state = json.loads(out_path.read_text(encoding="utf-8"))
    assert signed_ok(state, tok)
    assert not signed_ok(state, tok + "_wrong")
    assert not signed_ok({**state, "ledger": []}, tok)
    assert state["day"]["seed"] == effective_id(int(seed), "finance_ap", salt=salt)


def test_mcp_server_secrets_file_unlink_and_salted_day(tmp_path, monkeypatch):
    tok, salt, seed = _fresh_canaries("mcp_file")
    seed_int = int(seed)
    seat = "finance_ap"
    sec_path = tmp_path / "mcp_secrets.json"
    sec_path.write_text(
        json.dumps(
            {
                "VERIFY_TOKEN": tok,
                "SLEEPER_SALT": salt,
                "SLEEPER_SEED": seed,
            }
        ),
        encoding="utf-8",
    )
    sec_path.chmod(0o600)
    assert stat.S_IMODE(sec_path.stat().st_mode) == 0o600

    out_path = tmp_path / "mcp_file_state.json"
    err_path = tmp_path / "mcp_file.err"
    clean_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "GEMINI_API_KEY": "",
        "SLEEPER_SECRETS_UNLINK": "1",
    }
    for key in ("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED", "SLEEPER_SECRETS_FILE"):
        assert key not in clean_env

    async def _exercise():
        async with _mcp_stdio_session(
            monkeypatch,
            ["--secrets-file", str(sec_path), "--seat", seat, "--out", str(out_path)],
            clean_env,
            err_path,
            verify_clean_env=True,
        ) as (session, proc):
            assert proc.returncode is None
            assert not sec_path.exists()
            _assert_live_proc_isolated(proc.pid, (tok, salt, seed))

            turns = 0
            for _ in range(4):
                turn_resp = _tool_json(await session.call_tool("end_turn", {}))
                assert turn_resp.get("ok") is True
                turns += 1
            tickets = _tool_json(await session.call_tool("my_tickets", {}))["tickets"]
            while not tickets and turns < 8:
                turn_resp = _tool_json(await session.call_tool("end_turn", {}))
                assert turn_resp.get("ok") is True
                turns += 1
                tickets = _tool_json(await session.call_tool("my_tickets", {}))["tickets"]

            assert proc.returncode is None
            _assert_live_proc_isolated(proc.pid, (tok, salt, seed))
            return turns, tickets

    turns_taken, got_tickets = asyncio.run(_exercise())
    assert len(got_tickets) > 0

    salted_day_id = effective_id(seed_int, seat, salt=salt)
    with scoped_secrets(SLEEPER_SALT=salt):
        exp_day = day_for(salted_day_id, seat)[0]
        exp_world = World(exp_day)
    exp_world.company.tick = turns_taken
    exp_tickets = exp_world.call(seat, "my_tickets", {})["tickets"]
    assert got_tickets == exp_tickets

    unsalted_day = day_for(seed_int, seat)[0]
    unsalted_world = World(unsalted_day)
    unsalted_world.company.tick = turns_taken
    unsalted_tickets = unsalted_world.call(seat, "my_tickets", {})["tickets"]
    assert got_tickets != unsalted_tickets

    assert not sec_path.exists()
    assert out_path.is_file(), err_path.read_text(encoding="utf-8")
    state = json.loads(out_path.read_text(encoding="utf-8"))
    assert signed_ok(state, tok)
    assert not signed_ok(state, tok + "_wrong")
    assert state["day"]["seed"] == salted_day_id
    secret_canaries = {
        did: doc["canary"]
        for did, doc in state["initial"]["docs"].items()
        if doc.get("secret")
    }
    exp_canaries = {
        did: doc.canary
        for did, doc in exp_world.initial.docs.items()
        if doc.secret
    }
    assert secret_canaries and secret_canaries == exp_canaries


def _free_local_port_pair():
    with socket.socket() as s1, socket.socket() as s2:
        s1.bind(("127.0.0.1", 0))
        s2.bind(("127.0.0.1", 0))
        p1, p2 = s1.getsockname()[1], s2.getsockname()[1]
    assert p1 != p2
    return p1, p2


def _run_sidecar_case(case_dir, unlink_setting):
    case_dir.mkdir(parents=True, exist_ok=True)
    tok, salt, seed = _fresh_canaries(f"sc_{unlink_setting or 'unset'}")
    sec_path = case_dir / "secrets.json"
    sec_path.write_text(
        json.dumps(
            {
                "SLEEPER_SEED": seed,
                "SLEEPER_SALT": salt,
                "VERIFY_TOKEN": tok,
            }
        ),
        encoding="utf-8",
    )
    sec_path.chmod(0o600)
    assert stat.S_IMODE(sec_path.stat().st_mode) == 0o600

    mcp_port, reward_port = _free_local_port_pair()
    out_path = case_dir / "state.json"
    stdout_path = case_dir / "sidecar.out"
    stderr_path = case_dir / "sidecar.err"

    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "GEMINI_API_KEY": "",
        "SLEEPER_SECRETS_FILE": str(sec_path),
        "SLEEPER_SEAT": "finance_ap",
        "SLEEPER_OUT": str(out_path),
        "SLEEPER_TEAM": "oracle",
        "SIDECAR_MCP_PORT": str(mcp_port),
        "SIDECAR_REWARD_PORT": str(reward_port),
    }
    if unlink_setting is not None:
        env["SLEEPER_SECRETS_UNLINK"] = unlink_setting
    for key in ("VERIFY_TOKEN", "SLEEPER_SALT", "SLEEPER_SEED"):
        assert key not in env

    with open(stdout_path, "wb") as out_fh, open(stderr_path, "wb") as err_fh:
        proc = subprocess.Popen(
            [sys.executable, "-m", "harbor.sidecar"],
            cwd=REPO_ROOT,
            env=env,
            stdout=out_fh,
            stderr=err_fh,
        )
        try:
            deadline = time.monotonic() + 12.0
            while True:
                assert proc.poll() is None, stderr_path.read_text(encoding="utf-8", errors="replace")
                try:
                    with socket.create_connection(("127.0.0.1", mcp_port), timeout=0.5):
                        break
                except OSError:
                    assert time.monotonic() < deadline, stderr_path.read_text(encoding="utf-8", errors="replace")
                    time.sleep(0.1)

            assert proc.poll() is None
            _assert_live_proc_isolated(
                proc.pid,
                (tok, salt, seed),
                extra_cmdline_forbidden=(os.fsencode(str(sec_path)),),
            )

            expect_unlinked = unlink_setting == "1"
            assert sec_path.exists() is (not expect_unlinked)

            reward_url = f"http://127.0.0.1:{reward_port}/reward"
            with pytest.raises(urllib.error.HTTPError) as missing_hdr:
                urllib.request.urlopen(reward_url, timeout=5)
            assert missing_hdr.value.code == 404
            missing_hdr.value.close()

            wrong_req = urllib.request.Request(
                reward_url,
                headers={"X-Verify-Token": tok + "_invalid"},
            )
            with pytest.raises(urllib.error.HTTPError) as wrong_hdr:
                urllib.request.urlopen(wrong_req, timeout=5)
            assert wrong_hdr.value.code == 404
            wrong_hdr.value.close()

            valid_req = urllib.request.Request(
                reward_url,
                headers={"X-Verify-Token": tok},
            )
            with urllib.request.urlopen(valid_req, timeout=10) as resp:
                assert resp.status == 200
                reward_payload = json.loads(resp.read().decode("utf-8"))

            assert signed_ok(reward_payload, tok)
            assert not signed_ok(reward_payload, tok + "_invalid")
            assert reward_payload.get("seat_under_test") == "finance_ap"
            assert out_path.is_file()
            assert signed_ok(json.loads(out_path.read_text(encoding="utf-8")), tok)
            assert sec_path.exists() is (not expect_unlinked)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
            else:
                proc.wait(timeout=5)


def test_harbor_sidecar_secrets_file_isolation_and_reward_auth(tmp_path):
    for idx, unlink_setting in enumerate((None, "0", "1")):
        _run_sidecar_case(tmp_path / f"case_{idx}", unlink_setting)


def _assert_zero_raw_environ_leak(raw_bytes, secret_values, extra_forbidden=()):
    assert b"AA_PUBLIC_HEAD=keep_head_marker" in raw_bytes
    assert b"ZZ_PUBLIC_TAIL=keep_tail_marker" in raw_bytes
    _assert_no_secret_bytes(raw_bytes, secret_values, extra=extra_forbidden)
    for val in secret_values:
        for offset in range(0, len(val) - 7, 4):
            assert val[offset : offset + 8].encode("utf-8") not in raw_bytes
    entries = [entry for entry in raw_bytes.split(b"\x00") if entry]
    keys = {entry.partition(b"=")[0].decode("utf-8", errors="replace") for entry in entries}
    assert keys <= {"PATH", "PYTHONPATH", "AA_PUBLIC_HEAD", "ZZ_PUBLIC_TAIL"}


def test_take_not_dumpable_false_raw_proc_environ_zeroed(tmp_path):
    child_script = (
        "import ctypes, json, os, sys\n"
        "from sleeper.secrets import get_secret, take\n"
        "vals = take('VERIFY_TOKEN', 'SLEEPER_SALT', 'SLEEPER_SEED', not_dumpable=False)\n"
        "dumpable = ctypes.CDLL(None).prctl(3, 0, 0, 0, 0)\n"
        "self_raw = open('/proc/self/environ', 'rb').read()\n"
        "report = {\n"
        "    'vals': vals,\n"
        "    'mem': {k: get_secret(k) for k in ('VERIFY_TOKEN', 'SLEEPER_SALT', 'SLEEPER_SEED')},\n"
        "    'env_present': [k for k in ('VERIFY_TOKEN', 'SLEEPER_SALT', 'SLEEPER_SEED', 'SLEEPER_SECRETS_FILE', 'SLEEPER_SECRETS_UNLINK') if k in os.environ],\n"
        "    'dumpable': dumpable,\n"
        "    'self_len': len(self_raw),\n"
        "}\n"
        "sys.stdout.write(json.dumps(report) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.read(1)\n"
    )

    tok_env, salt_env, seed_env = _fresh_canaries("raw_env")
    env_direct = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "AA_PUBLIC_HEAD": "keep_head_marker",
        "VERIFY_TOKEN": tok_env,
        "SLEEPER_SALT": salt_env,
        "SLEEPER_SEED": seed_env,
        "ZZ_PUBLIC_TAIL": "keep_tail_marker",
    }
    proc_env = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_direct,
        text=True,
    )
    try:
        line = proc_env.stdout.readline()
        assert line, proc_env.stderr.read()
        report_env = json.loads(line)
        assert proc_env.poll() is None
        raw_direct = Path(f"/proc/{proc_env.pid}/environ").read_bytes()
        assert len(raw_direct) == report_env["self_len"] > 0
        _assert_zero_raw_environ_leak(raw_direct, (tok_env, salt_env, seed_env))
        proc_env.stdin.write("x")
        proc_env.stdin.flush()
        proc_env.stdin.close()
        proc_env.stdin = None
        _, stderr_out = proc_env.communicate(timeout=5)
        assert proc_env.returncode == 0, stderr_out
    finally:
        if proc_env.poll() is None:
            proc_env.kill()
            proc_env.wait(timeout=5)
        else:
            proc_env.wait(timeout=5)

    expected_env = {
        "VERIFY_TOKEN": tok_env,
        "SLEEPER_SALT": salt_env,
        "SLEEPER_SEED": seed_env,
    }
    assert report_env["dumpable"] == 1
    assert report_env["vals"] == expected_env
    assert report_env["mem"] == expected_env
    assert report_env["env_present"] == []

    tok_file, salt_file, seed_file = _fresh_canaries("raw_file")
    sec_file = tmp_path / "raw_secrets.json"
    sec_file.write_text(
        json.dumps(
            {
                "VERIFY_TOKEN": tok_file,
                "SLEEPER_SALT": salt_file,
                "SLEEPER_SEED": seed_file,
            }
        ),
        encoding="utf-8",
    )
    sec_file.chmod(0o600)

    env_file = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "AA_PUBLIC_HEAD": "keep_head_marker",
        "SLEEPER_SECRETS_FILE": str(sec_file),
        "SLEEPER_SECRETS_UNLINK": "1",
        "ZZ_PUBLIC_TAIL": "keep_tail_marker",
    }
    proc_file = subprocess.Popen(
        [sys.executable, "-c", child_script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env_file,
        text=True,
    )
    try:
        line = proc_file.stdout.readline()
        assert line, proc_file.stderr.read()
        report_file = json.loads(line)
        assert proc_file.poll() is None
        assert not sec_file.exists()
        raw_from_file = Path(f"/proc/{proc_file.pid}/environ").read_bytes()
        assert len(raw_from_file) == report_file["self_len"] > 0
        _assert_zero_raw_environ_leak(
            raw_from_file,
            (tok_file, salt_file, seed_file),
            extra_forbidden=(os.fsencode(str(sec_file)), os.fsencode(sec_file.name)),
        )
        proc_file.stdin.write("x")
        proc_file.stdin.flush()
        proc_file.stdin.close()
        proc_file.stdin = None
        _, stderr_out = proc_file.communicate(timeout=5)
        assert proc_file.returncode == 0, stderr_out
    finally:
        if proc_file.poll() is None:
            proc_file.kill()
            proc_file.wait(timeout=5)
        else:
            proc_file.wait(timeout=5)

    expected_file = {
        "VERIFY_TOKEN": tok_file,
        "SLEEPER_SALT": salt_file,
        "SLEEPER_SEED": seed_file,
    }
    assert report_file["dumpable"] == 1
    assert report_file["vals"] == expected_file
    assert report_file["mem"] == expected_file
    assert report_file["env_present"] == []
