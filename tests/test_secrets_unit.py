import base64
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from sleeper.canary import make_canary
from sleeper.secrets import (
    _MEM,
    clear_secrets,
    get,
    get_secret,
    load_secrets_file,
    scoped_secrets,
    set_secret,
    take,
    write_secrets_file,
)

REPO_ROOT = str(Path(__file__).resolve().parents[1])

GOLDEN_5B8DDB20 = [
    (7, "doc1", "KXQLHUZAY4BP"),
    (0, "D-merger", "KXQXELNX55B3"),
    (1000, "D-payroll", "KXZU7PYDPBRQ"),
    (1018, "D-creds", "KXHEAVUPOMVO"),
]


@pytest.fixture(autouse=True)
def _isolated_secrets(monkeypatch):
    for key in (
        "SLEEPER_SALT",
        "VERIFY_TOKEN",
        "SLEEPER_SEED",
        "SLEEPER_SECRETS_FILE",
        "SLEEPER_SECRETS_UNLINK",
    ):
        monkeypatch.delenv(key, raising=False)
    clear_secrets()
    yield
    clear_secrets()


def _legacy_unsalted_canary(seed, doc_id):
    d = hashlib.sha256(f"canary|{seed}|{doc_id}|".encode()).digest()
    return "KX" + base64.b32encode(d)[:10].decode()


def test_unsalted_make_canary_bit_for_bit_parity():
    assert "SLEEPER_SALT" not in os.environ
    assert "SLEEPER_SALT" not in _MEM
    for seed, doc_id, expected in GOLDEN_5B8DDB20:
        assert make_canary(seed, doc_id) == expected
        assert make_canary(seed, doc_id, salt="") == expected
    for seed in range(15):
        for doc_id in ("doc1", "D-merger", "D-payroll", "D-creds"):
            assert make_canary(seed, doc_id) == _legacy_unsalted_canary(seed, doc_id)


def test_setenv_and_scoped_secrets_change_canary(monkeypatch):
    unsalted = make_canary(7, "doc1")
    assert unsalted == "KXQLHUZAY4BP"

    monkeypatch.setenv("SLEEPER_SALT", "env-salt-alpha")
    salted_env = make_canary(7, "doc1")
    assert salted_env != unsalted
    assert salted_env == make_canary(7, "doc1", salt="env-salt-alpha")
    assert make_canary(7, "doc1", salt="") == unsalted

    monkeypatch.delenv("SLEEPER_SALT", raising=False)
    assert make_canary(7, "doc1") == unsalted

    with scoped_secrets(SLEEPER_SALT="mem-salt-bravo", EXTRA_NUM=99):
        assert "SLEEPER_SALT" not in os.environ
        assert "EXTRA_NUM" not in os.environ
        assert get_secret("SLEEPER_SALT") == "mem-salt-bravo"
        assert get("EXTRA_NUM") == "99"
        salted_mem = make_canary(7, "doc1")
        assert salted_mem != unsalted
        assert salted_mem != salted_env
        assert salted_mem == make_canary(7, "doc1", salt="mem-salt-bravo")
        assert make_canary(7, "doc1", salt="") == unsalted

        monkeypatch.setenv("SLEEPER_SALT", "env-overrides-mem")
        assert get_secret("SLEEPER_SALT") == "env-overrides-mem"
        assert make_canary(7, "doc1") == make_canary(7, "doc1", salt="env-overrides-mem")
        monkeypatch.delenv("SLEEPER_SALT", raising=False)
        assert get_secret("SLEEPER_SALT") == "mem-salt-bravo"

    assert _MEM == {}
    assert get_secret("SLEEPER_SALT") == ""
    assert get_secret("MISSING_KEY", "fallback") == "fallback"
    assert make_canary(7, "doc1") == unsalted


def test_set_secret_none_and_scoped_restore_on_error():
    set_secret(A="one", B=2)
    assert _MEM == {"A": "one", "B": "2"}
    set_secret(A=None)
    assert _MEM == {"B": "2"}

    with pytest.raises(RuntimeError):
        with scoped_secrets(B="override", C="temp"):
            assert get_secret("B") == "override"
            assert get_secret("C") == "temp"
            raise RuntimeError("boom")

    assert _MEM == {"B": "2"}
    clear_secrets()
    assert _MEM == {}


def test_subprocess_take_wipes_proc_environ_and_preserves_salted_canary():
    tok_val = "vtok_deadbeefcafebabe99112233"
    salt_val = "salt_secret_val_778899aabb"
    seed_val = "7"
    code = (
        "import json, os, sys\n"
        "from sleeper.secrets import get_secret, take\n"
        "from sleeper.canary import make_canary\n"
        "vals = take('VERIFY_TOKEN', 'SLEEPER_SALT', 'SLEEPER_SEED', not_dumpable=False)\n"
        "raw = open(f'/proc/{os.getpid()}/environ', 'rb').read()\n"
        "out = {\n"
        "    'vals': vals,\n"
        "    'env_has': [k for k in ('VERIFY_TOKEN', 'SLEEPER_SALT', 'SLEEPER_SEED', 'SLEEPER_SECRETS_FILE', 'SLEEPER_SECRETS_UNLINK') if k in os.environ],\n"
        "    'mem_salt': get_secret('SLEEPER_SALT'),\n"
        "    'mem_token': get_secret('VERIFY_TOKEN'),\n"
        "    'mem_seed': get_secret('SLEEPER_SEED'),\n"
        "    'canary': make_canary(7, 'doc1'),\n"
        "    'self_raw_len': len(raw),\n"
        "}\n"
        "sys.stdout.write(json.dumps(out) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.read(1)\n"
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "PUBLIC_MARKER": "keep_me_visible",
        "VERIFY_TOKEN": tok_val,
        "SLEEPER_SALT": salt_val,
        "SLEEPER_SEED": seed_val,
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line, proc.stderr.read()
        payload = json.loads(line)
        raw_proc = Path(f"/proc/{proc.pid}/environ").read_bytes()
        assert b"PUBLIC_MARKER=keep_me_visible" in raw_proc
        for forbidden in (
            tok_val.encode(),
            salt_val.encode(),
            b"VERIFY_TOKEN",
            b"SLEEPER_SALT",
            b"SLEEPER_SEED",
            b"SLEEPER_SECRETS_FILE",
            b"SLEEPER_SECRETS_UNLINK",
        ):
            assert forbidden not in raw_proc
        proc.stdin.write("x")
        proc.stdin.flush()
        proc.stdin.close()
        proc.stdin = None
        _, err = proc.communicate(timeout=5)
        assert proc.returncode == 0, err
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert payload["vals"] == {
        "VERIFY_TOKEN": tok_val,
        "SLEEPER_SALT": salt_val,
        "SLEEPER_SEED": seed_val,
    }
    assert payload["env_has"] == []
    assert payload["mem_salt"] == salt_val
    assert payload["mem_token"] == tok_val
    assert payload["mem_seed"] == seed_val
    assert payload["canary"] == make_canary(7, "doc1", salt=salt_val)
    assert payload["canary"] != "KXQLHUZAY4BP"


def test_take_default_not_dumpable():
    code = (
        "import ctypes, json, sys\n"
        "from sleeper.secrets import take\n"
        "libc = ctypes.CDLL(None)\n"
        "before = libc.prctl(3, 0, 0, 0, 0)\n"
        "vals = take('VERIFY_TOKEN', 'SLEEPER_SALT')\n"
        "after = libc.prctl(3, 0, 0, 0, 0)\n"
        "sys.stdout.write(json.dumps({'before': before, 'after': after, 'vals': vals}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "sys.stdin.read(1)\n"
    )
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "VERIFY_TOKEN": "tok_nd",
        "SLEEPER_SALT": "salt_nd",
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
    )
    try:
        line = proc.stdout.readline()
        assert line, proc.stderr.read()
        data = json.loads(line)
        assert data["before"] == 1
        assert data["after"] == 0
        assert data["vals"] == {"VERIFY_TOKEN": "tok_nd", "SLEEPER_SALT": "salt_nd"}
        if os.geteuid() != 0:
            with pytest.raises(PermissionError):
                Path(f"/proc/{proc.pid}/environ").read_bytes()
        proc.stdin.write("x")
        proc.stdin.flush()
        proc.stdin.close()
        proc.stdin = None
        _, err = proc.communicate(timeout=5)
        assert proc.returncode == 0, err
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_write_secrets_file_mode_and_contents(tmp_path):
    path = write_secrets_file(
        {
            "VERIFY_TOKEN": "tok_0600",
            "SLEEPER_SALT": "salt_0600",
            "SLEEPER_SEED": 12,
            "IGNORED": None,
        },
        dir=tmp_path,
    )
    assert isinstance(path, str)
    p = Path(path)
    assert p.parent == tmp_path
    assert p.name.startswith("sleeper-secrets-")
    assert p.name.endswith(".json")
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert json.loads(p.read_text(encoding="utf-8")) == {
        "VERIFY_TOKEN": "tok_0600",
        "SLEEPER_SALT": "salt_0600",
        "SLEEPER_SEED": "12",
    }


def test_secrets_file_int_seed_and_unlink_controls(tmp_path):
    sec_file = tmp_path / "run_secrets.json"
    sec_file.write_text(
        json.dumps(
            {
                "SLEEPER_SEED": 4,
                "SLEEPER_SALT": "file_salt_value",
                "VERIFY_TOKEN": "file_verify_token",
                "UNUSED_NULL": None,
            }
        ),
        encoding="utf-8",
    )

    code = (
        "import json, os\n"
        "from sleeper.secrets import take\n"
        "from sleeper.canary import make_canary\n"
        "vals = take('VERIFY_TOKEN', 'SLEEPER_SALT', 'SLEEPER_SEED', 'MISSING_ONE', not_dumpable=False)\n"
        "raw = open(f'/proc/{os.getpid()}/environ', 'rb').read()\n"
        "print(json.dumps({\n"
        "    'vals': vals,\n"
        "    'canary': make_canary(4, 'doc1'),\n"
        "    'leaked_key': any(k in raw for k in (b'SLEEPER_SECRETS_FILE', b'SLEEPER_SECRETS_UNLINK', b'VERIFY_TOKEN', b'SLEEPER_SALT', b'SLEEPER_SEED')),\n"
        "    'leaked_path': os.fsencode(repr_path) in raw,\n"
        "    'env_keys': [k for k in os.environ if k.startswith('SLEEPER_') or k == 'VERIFY_TOKEN'],\n"
        "}))\n"
    ).replace("repr_path", repr(str(sec_file)))

    base_env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": REPO_ROOT,
        "SLEEPER_SECRETS_FILE": str(sec_file),
    }
    res_default = subprocess.run(
        [sys.executable, "-c", code],
        env=base_env,
        capture_output=True,
        text=True,
        check=True,
    )
    out_default = json.loads(res_default.stdout)
    assert out_default["vals"] == {
        "VERIFY_TOKEN": "file_verify_token",
        "SLEEPER_SALT": "file_salt_value",
        "SLEEPER_SEED": "4",
        "MISSING_ONE": None,
    }
    assert out_default["canary"] == make_canary(4, "doc1", salt="file_salt_value")
    assert not out_default["leaked_key"]
    assert not out_default["leaked_path"]
    assert out_default["env_keys"] == []
    assert sec_file.is_file()

    res_keep = subprocess.run(
        [sys.executable, "-c", code],
        env={**base_env, "SLEEPER_SECRETS_UNLINK": "0"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(res_keep.stdout)["vals"]["SLEEPER_SEED"] == "4"
    assert sec_file.is_file()

    res_env_override = subprocess.run(
        [sys.executable, "-c", code],
        env={**base_env, "SLEEPER_SALT": "override_from_env", "VERIFY_TOKEN": ""},
        capture_output=True,
        text=True,
        check=True,
    )
    override_vals = json.loads(res_env_override.stdout)["vals"]
    assert override_vals["SLEEPER_SALT"] == "override_from_env"
    assert override_vals["VERIFY_TOKEN"] == "file_verify_token"
    assert sec_file.is_file()

    loaded_no_unlink = load_secrets_file(str(sec_file), unlink=False)
    assert loaded_no_unlink == {
        "SLEEPER_SEED": "4",
        "SLEEPER_SALT": "file_salt_value",
        "VERIFY_TOKEN": "file_verify_token",
    }
    assert sec_file.is_file()

    res_unlink = subprocess.run(
        [sys.executable, "-c", code],
        env={**base_env, "SLEEPER_SECRETS_UNLINK": "1"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(res_unlink.stdout)["vals"]["SLEEPER_SEED"] == "4"
    assert not sec_file.exists()

    p2 = write_secrets_file({"VERIFY_TOKEN": "t2"}, dir=tmp_path)
    assert load_secrets_file(p2, unlink=True) == {"VERIFY_TOKEN": "t2"}
    assert not Path(p2).exists()


def test_missing_secrets_file_raises(tmp_path, monkeypatch):
    assert load_secrets_file() == {}

    missing = str(tmp_path / "does_not_exist.json")
    with pytest.raises(FileNotFoundError):
        load_secrets_file(missing)

    with pytest.raises(FileNotFoundError):
        take("VERIFY_TOKEN", secrets_file=missing, not_dumpable=False)

    monkeypatch.setenv("SLEEPER_SECRETS_FILE", missing)
    with pytest.raises(FileNotFoundError):
        load_secrets_file()

    with pytest.raises(FileNotFoundError):
        take("VERIFY_TOKEN", not_dumpable=False)
