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
        "mcp": ("scripts/mcp_port.sh", "MCP_AVOID_PORT=", "SLEEPER_SALT=", "harbor.sidecar"),
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


def test_make_mcp_passes_salt_and_resolved_ports_to_sidecar(tmp_path: Path) -> None:
    stub = tmp_path / "fake_py"
    stub.write_text(
        chr(35)
        + f"!{sys.executable}\n"
        + "import json, os, sys\n"
        + "if sys.argv[1:2] == ['-']:\n"
        + "    sys.argv = ['stdin', *sys.argv[2:]]\n"
        + "    exec(sys.stdin.read())\n"
        + "    raise SystemExit(0)\n"
        + "if sys.argv[1:3] == ['-m', 'harbor.sidecar']:\n"
        + "    keys = (\n"
        + "        'SLEEPER_SALT',\n"
        + "        'SLEEPER_SEED',\n"
        + "        'SLEEPER_SEAT',\n"
        + "        'SLEEPER_OUT',\n"
        + "        'VERIFY_TOKEN',\n"
        + "        'SIDECAR_MCP_PORT',\n"
        + "        'SIDECAR_REWARD_PORT',\n"
        + "    )\n"
        + "    print('SIDECAR_ENV=' + json.dumps({k: os.environ.get(k) for k in keys}))\n"
        + "    raise SystemExit(0)\n"
        + "raise SystemExit(2)\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    proc = _run_make(["mcp", f"PY={stub}"])
    assert proc.returncode == 0, proc.stderr
    match = ENDPOINT_RE.search(proc.stdout)
    assert match is not None, proc.stdout
    mcp_port, reward_port = match.group(1), match.group(2)
    env_line = [line for line in proc.stdout.splitlines() if line.startswith("SIDECAR_ENV=")]
    assert len(env_line) == 1, proc.stdout
    payload = json.loads(env_line[0].removeprefix("SIDECAR_ENV="))
    assert payload["SLEEPER_SALT"] == "judge-local-salt"
    assert payload["SLEEPER_SEED"] == "1000"
    assert payload["SLEEPER_SEAT"] == "finance_ap"
    assert payload["SLEEPER_OUT"] == "/tmp/sleeper-mcp-state.json"
    assert payload["VERIFY_TOKEN"] == "judge-local"
    assert payload["SIDECAR_MCP_PORT"] == mcp_port
    assert payload["SIDECAR_REWARD_PORT"] == reward_port
    assert mcp_port != reward_port


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
