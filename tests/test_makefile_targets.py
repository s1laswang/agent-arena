import ast
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_PORT_SH = ROOT / "scripts" / "mcp_port.sh"
OWNED_FILES = (
    "Makefile",
    "scripts/mcp_port.sh",
    "tests/test_makefile_targets.py",
)
ENDPOINT_RE = re.compile(r"http://127\.0\.0\.1:(\d+)/mcp\s+reward :(\d+)")


def _run_make(args: list[str], env_overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    for key in (
        "MCP_PORT",
        "MCP_PORT_FALLBACK",
        "MCP_REWARD_PORT",
        "MCP_AVOID_PORT",
        "MCP_DRY_RUN",
        "SLEEPER_REPRODUCE_ACTIVE",
        "SLEEPER_SALT",
        "SLEEPER_SEED",
        "SLEEPER_SEAT",
        "SLEEPER_OUT",
        "VERIFY_TOKEN",
    ):
        env.pop(key, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["make", *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_mcp_port_script_is_executable() -> None:
    assert MCP_PORT_SH.is_file()
    assert os.access(MCP_PORT_SH, os.X_OK)


def test_make_dry_run_targets() -> None:
    expected = {
        "setup": ("scripts/setup_env.sh",),
        "reproduce": ("lab.reproduce", "SLEEPER_REPRODUCE_ACTIVE=1", "SLEEPER_OFFLINE=1"),
        "mcp": (
            "scripts/mcp_port.sh",
            "MCP_AVOID_PORT=",
            "SLEEPER_SALT=",
            "SLEEPER_SECRETS_FILE=",
            "SLEEPER_SECRETS_UNLINK=1",
            "env -u SLEEPER_SALT -u SLEEPER_SEED -u VERIFY_TOKEN",
            "harbor.sidecar",
        ),
        "frontier-replay": ("lab.frontier_replay", "--strict", "SLEEPER_REPRODUCE_ACTIVE"),
        "accept": ("scripts/judge_accept.sh",),
        "test": ("pytest",),
        "probes": ("scripts.probes", "--out-dir"),
    }
    for target, substrings in expected.items():
        proc = _run_make(["-n", target])
        assert proc.returncode == 0, f"{target} failed: {proc.stderr}"
        for sub in substrings:
            assert sub in proc.stdout, f"missing {sub!r} in make -n {target}: {proc.stdout}"


def test_frontier_replay_noop_when_reproduce_active() -> None:
    proc = _run_make(
        ["frontier-replay", "PY=/nonexistent/python"],
        {"SLEEPER_REPRODUCE_ACTIVE": "1"},
    )
    assert proc.returncode == 0, proc.stderr


def test_make_mcp_dry_run_prints_endpoints() -> None:
    proc = _run_make(["mcp", "MCP_DRY_RUN=1", f"PY={sys.executable}"])
    assert proc.returncode == 0, proc.stderr
    assert "http://127.0.0.1:" in proc.stdout
    assert "reward :" in proc.stdout
    match = ENDPOINT_RE.search(proc.stdout)
    assert match is not None, proc.stdout
    mcp_port, reward_port = int(match.group(1)), int(match.group(2))
    assert mcp_port != reward_port


def test_make_mcp_busy_port_without_fallback_exits_nonzero() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = sock.getsockname()[1]
        proc = _run_make(
            [
                "mcp",
                f"MCP_PORT={busy_port}",
                "MCP_PORT_FALLBACK=0",
                "MCP_DRY_RUN=1",
                f"PY={sys.executable}",
            ]
        )
    assert proc.returncode != 0
    assert "already in use" in proc.stderr


def test_make_mcp_busy_port_fallback_avoids_reward_collision() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = sock.getsockname()[1]
        proc = _run_make(
            [
                "mcp",
                f"MCP_PORT={busy_port}",
                f"MCP_REWARD_PORT={busy_port + 2}",
                "MCP_PORT_FALLBACK=1",
                "MCP_DRY_RUN=1",
                f"PY={sys.executable}",
            ]
        )
    assert proc.returncode == 0, proc.stderr
    assert "falling back to" in proc.stderr
    match = ENDPOINT_RE.search(proc.stdout)
    assert match is not None, proc.stdout
    mcp_port, reward_port = int(match.group(1)), int(match.group(2))
    assert mcp_port != busy_port
    assert mcp_port != reward_port


def test_make_mcp_passes_secrets_file_and_strips_env_for_sidecar(tmp_path: Path) -> None:
    stub = tmp_path / "fake_py"
    stub.write_text(
        chr(35)
        + f"!{sys.executable}\n"
        + "import json, os, stat, sys\n"
        + "from pathlib import Path\n"
        + "if sys.argv[1:2] == ['-']:\n"
        + "    sys.argv = ['stdin', *sys.argv[2:]]\n"
        + "    exec(sys.stdin.read())\n"
        + "    raise SystemExit(0)\n"
        + "if sys.argv[1:2] == ['-c'] and len(sys.argv) >= 3:\n"
        + "    exec(sys.argv[2])\n"
        + "    raise SystemExit(0)\n"
        + "if sys.argv[1:3] == ['-m', 'harbor.sidecar']:\n"
        + "    sfile = os.environ['SLEEPER_SECRETS_FILE']\n"
        + "    mode = stat.S_IMODE(os.stat(sfile).st_mode)\n"
        + "    secrets = json.loads(Path(sfile).read_text(encoding='utf-8'))\n"
        + "    proc_env = Path('/proc/self/environ').read_bytes()\n"
        + "    keys = (\n"
        + "        'SLEEPER_SALT',\n"
        + "        'SLEEPER_SEED',\n"
        + "        'VERIFY_TOKEN',\n"
        + "        'SLEEPER_SECRETS_FILE',\n"
        + "        'SLEEPER_SECRETS_UNLINK',\n"
        + "        'SLEEPER_SEAT',\n"
        + "        'SLEEPER_OUT',\n"
        + "        'SIDECAR_MCP_PORT',\n"
        + "        'SIDECAR_REWARD_PORT',\n"
        + "    )\n"
        + "    out = {\n"
        + "        'env': {k: os.environ.get(k) for k in keys},\n"
        + "        'mode': mode,\n"
        + "        'secrets': secrets,\n"
        + "        'leaked': any(t in proc_env for t in (b'SLEEPER_SALT=', b'SLEEPER_SEED=', b'VERIFY_TOKEN=')),\n"
        + "    }\n"
        + "    print('SIDECAR_CHECK=' + json.dumps(out))\n"
        + "    raise SystemExit(0)\n"
        + "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    for parent_env, expected_secrets in (
        (
            None,
            {
                "SLEEPER_SALT": "judge-local-salt",
                "SLEEPER_SEED": "1000",
                "VERIFY_TOKEN": "judge-local",
            },
        ),
        (
            {
                "SLEEPER_SALT": "parent-salt",
                "SLEEPER_SEED": "4242",
                "VERIFY_TOKEN": "parent-token",
            },
            {
                "SLEEPER_SALT": "parent-salt",
                "SLEEPER_SEED": "4242",
                "VERIFY_TOKEN": "parent-token",
            },
        ),
    ):
        proc = _run_make(["mcp", f"PY={stub}"], parent_env)
        assert proc.returncode == 0, proc.stderr
        match = ENDPOINT_RE.search(proc.stdout)
        assert match is not None, proc.stdout
        mcp_port, reward_port = match.group(1), match.group(2)
        check_lines = [line for line in proc.stdout.splitlines() if line.startswith("SIDECAR_CHECK=")]
        assert len(check_lines) == 1, proc.stdout
        payload = json.loads(check_lines[0].removeprefix("SIDECAR_CHECK="))
        env_map = payload["env"]
        assert env_map["SLEEPER_SALT"] is None
        assert env_map["SLEEPER_SEED"] is None
        assert env_map["VERIFY_TOKEN"] is None
        assert payload["leaked"] is False
        assert payload["mode"] == 0o600
        assert payload["secrets"] == expected_secrets
        assert env_map["SLEEPER_SECRETS_UNLINK"] == "1"
        assert env_map["SLEEPER_SEAT"] == "finance_ap"
        assert env_map["SLEEPER_OUT"] == "/tmp/sleeper-mcp-state.json"
        assert env_map["SIDECAR_MCP_PORT"] == mcp_port
        assert env_map["SIDECAR_REWARD_PORT"] == reward_port
        assert mcp_port != reward_port
        assert not Path(env_map["SLEEPER_SECRETS_FILE"]).exists()


def test_probes_target_handles_out_dir_flag_detection(tmp_path: Path) -> None:
    for supports_out_dir in (True, False):
        stub = tmp_path / f"probes_py_{int(supports_out_dir)}"
        help_line = "--days N --out-dir DIR" if supports_out_dir else "--days N"
        stub.write_text(
            chr(35)
            + f"!{sys.executable}\n"
            + "import json, os, sys\n"
            + "if sys.argv[1:4] == ['-m', 'scripts.probes', '--help']:\n"
            + f"    print({help_line!r})\n"
            + "    raise SystemExit(0)\n"
            + "if sys.argv[1:3] == ['-m', 'scripts.probes']:\n"
            + "    print(json.dumps({'args': sys.argv[3:], 'key': os.environ.get('GEMINI_API_KEY')}))\n"
            + "    raise SystemExit(0)\n"
            + "raise SystemExit(2)\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
        proc = _run_make(["probes", f"PY={stub}"], {"GEMINI_API_KEY": "should-be-cleared"})
        assert proc.returncode == 0, proc.stderr
        payload = json.loads(proc.stdout.strip())
        assert payload["key"] == ""
        if supports_out_dir:
            assert payload["args"] == ["--days", "3", "--out-dir", "results/eval"]
        else:
            assert payload["args"] == ["--days", "3"]


def test_makefile_single_phony_covers_all_targets() -> None:
    lines = (ROOT / "Makefile").read_text(encoding="utf-8").splitlines()
    phony_lines = [line for line in lines if line.startswith(".PHONY:")]
    assert len(phony_lines) == 1
    phony_targets = set(phony_lines[0].removeprefix(".PHONY:").split())
    defined_targets = {
        line.split(":", 1)[0].strip()
        for line in lines
        if line and not line.startswith(("\t", ".PHONY:")) and ":" in line and "=" not in line.split(":", 1)[0]
    }
    assert defined_targets == phony_targets


def test_owned_files_have_no_comments_docstrings_or_em_dashes() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    for rel in OWNED_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        assert em_dash not in text, f"em dash found in {rel}"
        lines = text.splitlines()
        if rel == "scripts/mcp_port.sh":
            assert lines[0] == hash_char + "!/usr/bin/env bash"
            assert all(hash_char not in line for line in lines[1:]), f"comment found in {rel}"
        else:
            assert hash_char not in text, f"comment found in {rel}"
    tree = ast.parse((ROOT / "tests" / "test_makefile_targets.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            assert ast.get_docstring(node) is None
