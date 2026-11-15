"""Unit and live MCP integration tests for scripts/judge_accept.sh."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
ACCEPT_SCRIPT = ROOT / "scripts" / "judge_accept.sh"
MCP_PORT_SCRIPT = ROOT / "scripts" / "mcp_port.sh"
SOLVER_RANGE_DIR = ROOT / "results" / "solver_range"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")
H = chr(35)
H2 = H * 2


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-judge-accept-") as tmp_str:
        yield Path(tmp_str)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_judge_table(
    solver_scores: dict[str, float] | None = None,
    guess_scores: dict[str, float] | None = None,
    do_nothing_scores: dict[str, float] | None = None,
    stop_early_scores: dict[str, float] | None = None,
    tiers: tuple[str, ...] = ("medium", "hard", "easy"),
) -> str:
    s_map = {"medium": 0.630, "hard": 0.567, "easy": 0.774, **(solver_scores or {})}
    g_map = {"medium": -0.906, "hard": -0.953, "easy": -0.838, **(guess_scores or {})}
    dn_map = {"medium": 0.0, "hard": 0.0, "easy": 0.0, **(do_nothing_scores or {})}
    se_map = {"medium": 0.0, "hard": 0.0, "easy": 0.0, **(stop_early_scores or {})}

    lines = [f"{H} Canary judge table", ""]
    for tier in tiers:
        lines.extend(
            [
                f"{H2} {tier} (synthetic fixture)",
                "",
                "Paired runs (this invocation, same worlds):",
                "",
                "| agent | kind | n | invalid | score +- 95% CI | accuracy |",
                "|---|---|---:|---|---:|---:|",
                f"| solver | reference | 40 | 0 | {s_map[tier]:+.3f} +- 0.050 | 0.95 |",
                f"| guess_day1 | baseline | 40 | 0 | {g_map[tier]:+.3f} +- 0.050 | 0.03 |",
                f"| stop_early | baseline | 40 | 0 | {se_map[tier]:+.3f} +- 0.000 | 0.00 |",
                f"| do_nothing | baseline | 40 | 0 | {dn_map[tier]:+.3f} +- 0.000 | 0.00 |",
                "",
            ]
        )
    return "\n".join(lines) + "\n"


def _write_shell_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{H}!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _write_executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{H}!{sys.executable}\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _create_synthetic_repo(base: Path, warm: bool = False, live_mcp: bool = False) -> tuple[Path, Path, Path]:
    repo = base / "repo"
    bin_dir = base / "bin"
    log_path = base / "make_calls.jsonl"

    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ACCEPT_SCRIPT, repo / "scripts" / "judge_accept.sh")
    shutil.copy2(MCP_PORT_SCRIPT, repo / "scripts" / "mcp_port.sh")
    shutil.copytree(SOLVER_RANGE_DIR, repo / "results" / "solver_range")

    rules_py = repo / "canary" / "rules.py"
    rules_py.parent.mkdir(parents=True, exist_ok=True)
    rules_py.write_text("TIERS_VERSION = 'v1.4'\n", encoding="utf-8")

    committed_ex = repo / "results" / "anticheat" / "exploits.json"
    committed_ex.parent.mkdir(parents=True, exist_ok=True)
    committed_ex.write_text(json.dumps({"all_blocked": True}) + "\n", encoding="utf-8")

    headline_text = "| hard | OpenCode + gemini-4-carbon over MCP (judges' shape) | +0.322 |\n"
    committed_pt = repo / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md"
    committed_pt.parent.mkdir(parents=True, exist_ok=True)
    committed_pt.write_text(headline_text, encoding="utf-8")

    past = time.time() - 120.0
    for f in (rules_py, committed_ex, committed_pt):
        os.utime(f, (past, past))

    valid_table = _build_judge_table()
    valid_exploits = json.dumps(
        {
            "all_blocked": True,
            "replay_all_consistent": True,
            "harbor_all_consistent": True,
        }
    )

    payload_dir = base / "fixture_payloads"
    payload_dir.mkdir(parents=True, exist_ok=True)
    (payload_dir / "judge_table.md").write_text(valid_table, encoding="utf-8")
    (payload_dir / "exploits.json").write_text(valid_exploits + "\n", encoding="utf-8")
    (payload_dir / "paired_table_gemini.md").write_text(headline_text, encoding="utf-8")

    if warm:
        latest = repo / "results" / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        for name in ("judge_table.md", "exploits.json", "paired_table_gemini.md"):
            shutil.copy2(payload_dir / name, latest / name)

    _write_shell_executable(
        bin_dir / "uv",
        'if [ "${1:-}" = "--version" ]; then echo "uv 0.5.0 (stub)"; fi\nexit 0\n',
    )

    make_py = base / "make_helper.py"
    _write_executable(
        make_py,
        textwrap.dedent(
            f"""\
            import json
            import os
            import shutil
            import sys
            from pathlib import Path

            LOG = Path({str(log_path)!r})
            PAYLOADS = Path({str(payload_dir)!r})
            REAL_ROOT = Path({str(ROOT)!r})
            LIVE_MCP = {live_mcp!r}

            args = sys.argv[1:]
            target = args[0] if args else "default"
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({{"target": target}}) + "\\n")

            if target == "reproduce":
                import subprocess
                latest = Path.cwd() / "results" / "latest"
                latest.mkdir(parents=True, exist_ok=True)
                for name in ("judge_table.md", "exploits.json", "paired_table_gemini.md"):
                    shutil.copy2(PAYLOADS / name, latest / name)
                if os.environ.get("STUB_REPRODUCE_HEADLINE_DRIFT") == "1":
                    drifted = "".join(f"| hard | drifted row {{i}} | +0.000 |\\n" for i in range(35))
                    (latest / "paired_table_gemini.md").write_text(drifted, encoding="utf-8")
                probe_out = os.environ.get("STUB_SHIM_PROBE_JSON", "")
                if probe_out:
                    probe_dir = latest / "_shim_probe"
                    probe_dir.mkdir(parents=True, exist_ok=True)
                    fa = probe_dir / "a.txt"
                    fb = probe_dir / "b.txt"
                    fc = probe_dir / "c.txt"
                    missing = probe_dir / "missing.txt"
                    fa.write_text("alpha\\nbeta\\n", encoding="utf-8")
                    fb.write_text("alpha\\nbeta\\n", encoding="utf-8")
                    fc.write_text("alpha\\ngamma\\n", encoding="utf-8")
                    cmp_bin = shutil.which("cmp")
                    diff_bin = shutil.which("diff")
                    c_eq = subprocess.run(["cmp", "-s", str(fa), str(fb)], capture_output=True, text=True)
                    c_ne = subprocess.run(["cmp", "-s", str(fa), str(fc)], capture_output=True, text=True)
                    c_ms = subprocess.run(["cmp", "-s", str(missing), str(fa)], capture_output=True, text=True)
                    d_eq = subprocess.run(["diff", str(fa), str(fb)], capture_output=True, text=True)
                    d_ne = subprocess.run(["diff", str(fa), str(fc)], capture_output=True, text=True)
                    d_ms = subprocess.run(["diff", str(missing), str(fa)], capture_output=True, text=True)
                    Path(probe_out).write_text(
                        json.dumps({{
                            "cmp_bin": cmp_bin,
                            "diff_bin": diff_bin,
                            "cmp_eq": c_eq.returncode,
                            "cmp_ne": c_ne.returncode,
                            "cmp_missing": c_ms.returncode,
                            "diff_eq": d_eq.returncode,
                            "diff_eq_stdout": d_eq.stdout,
                            "diff_ne": d_ne.returncode,
                            "diff_ne_stdout": d_ne.stdout,
                            "diff_missing": d_ms.returncode,
                        }}),
                        encoding="utf-8",
                    )
                    shutil.rmtree(probe_dir)
                check_cmd = (
                    "if cmp -s results/latest/paired_table_gemini.md data/runs/committed/v1.4/paired_table_gemini.md; then "
                    "echo 'HEADLINE (README table, recomputed from committed episodes; identical to data/runs/committed/v1.4/paired_table_gemini.md):'; "
                    "else echo 'HEADLINE MISMATCH: results/latest/paired_table_gemini.md differs from data/runs/committed/v1.4/paired_table_gemini.md'; "
                    "diff results/latest/paired_table_gemini.md data/runs/committed/v1.4/paired_table_gemini.md | head -20; exit 1; fi"
                )
                rc = subprocess.call(["/bin/sh", "-c", check_cmd])
                sys.exit(rc)

            if target == "mcp":
                port = int(os.environ.get("MCP_PORT", "18765"))
                if LIVE_MCP:
                    import tempfile
                    sec_dir = Path(tempfile.mkdtemp(dir={str(base)!r}, prefix="mcp-sec-"))
                    sec_dir.chmod(0o700)
                    ep_file = sec_dir / "episode.json"
                    ep_file.write_text(
                        json.dumps({{
                            "tier": os.environ.get("CANARY_TIER", "medium"),
                            "seed": int(os.environ.get("CANARY_SEED", "900007")),
                        }}),
                        encoding="utf-8",
                    )
                    ep_file.chmod(0o600)
                    env = dict(os.environ)
                    tok = env.pop("CANARY_LEDGER_TOKEN", "")
                    env.pop("CANARY_TIER", None)
                    env.pop("CANARY_SEED", None)
                    if tok:
                        tok_file = sec_dir / "ledger_token"
                        tok_file.write_text(tok, encoding="utf-8")
                        tok_file.chmod(0o600)
                        env["CANARY_LEDGER_TOKEN_FILE"] = str(tok_file)
                    env["CANARY_EPISODE_FILE"] = str(ep_file)
                    env["CANARY_HOST"] = "127.0.0.1"
                    env["CANARY_PORT"] = str(port)
                    env["PYTHONPATH"] = str(REAL_ROOT)
                    os.execve(sys.executable, [sys.executable, "-m", "canary.mcp_server"], env)

                from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
                from urllib.parse import parse_qs, urlparse
                mode = os.environ.get("STUB_MCP_MODE", "ok")
                expected_tok = os.environ.get("CANARY_LEDGER_TOKEN", "judge-accept-demo")

                class Handler(BaseHTTPRequestHandler):
                    def log_message(self, fmt, *a):
                        return

                    def do_GET(self):
                        parsed = urlparse(self.path)
                        if parsed.path == "/mcp":
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b"missing MCP session")
                            return
                        if parsed.path == "/ledger":
                            qs = parse_qs(parsed.query)
                            given = (qs.get("token") or [None])[0]
                            if mode == "unauth_200" or given == expected_tok:
                                body = json.dumps({{"done": False, "score": 0.0}}).encode("utf-8")
                                self.send_response(200)
                                self.send_header("Content-Type", "application/json")
                                self.end_headers()
                                self.wfile.write(body)
                            else:
                                self.send_response(403)
                                self.send_header("Content-Type", "application/json")
                                self.end_headers()
                                self.wfile.write(b'{{"error":"forbidden"}}')
                            return
                        self.send_response(404)
                        self.end_headers()

                    def do_POST(self):
                        length = int(self.headers.get("Content-Length", "0"))
                        _ = self.rfile.read(length) if length > 0 else b""
                        if self.path != "/mcp":
                            self.send_response(404)
                            self.end_headers()
                            return
                        if mode == "bare_400":
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(b"bad request")
                            return
                        if mode == "missing_server_info":
                            msg = {{"jsonrpc": "2.0", "id": 1, "result": {{}}}}
                        else:
                            msg = {{
                                "jsonrpc": "2.0",
                                "id": 1,
                                "result": {{
                                    "protocolVersion": "2025-03-26",
                                    "serverInfo": {{"name": "canary", "version": "stub"}},
                                }},
                            }}
                        sse = ("event: message\\ndata: " + json.dumps(msg) + "\\n\\n").encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.end_headers()
                        self.wfile.write(sse)

                srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                srv.serve_forever()

            sys.exit(2)
            """
        ),
    )

    _write_shell_executable(
        bin_dir / "make",
        textwrap.dedent(
            f"""\
            if [ "${{1:-}}" = "--version" ]; then
              echo "GNU Make 4.4.1 (stub)"
              exit 0
            fi
            if [ "${{1:-}}" = "setup" ]; then
              printf '{{"target": "setup"}}\\n' >> "{log_path}"
              exit 0
            fi
            exec "{sys.executable}" "{make_py}" "$@"
            """
        ),
    )

    return repo, bin_dir, log_path


def _read_make_targets(log_path: Path) -> list[str]:
    if not log_path.is_file():
        return []
    return [json.loads(line)["target"] for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_accept(
    repo: Path,
    bin_dir: Path,
    tmp_base: Path,
    extra_env: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], int]:
    port = _free_port()
    scratch = tmp_base / f"scratch-{port}"
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    env["TMPDIR"] = str(scratch)
    env["MCP_PORT"] = str(port)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "judge_accept.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc, port


def test_hygiene_and_process_safety_invariants() -> None:
    self_raw = SELF_PATH.read_text(encoding="utf-8")
    assert H not in self_raw, "unexpected hash character in tests/test_judge_accept.py"
    assert chr(0x2014) not in self_raw, "unexpected em dash in tests/test_judge_accept.py"
    assert chr(0x2013) not in self_raw, "unexpected en dash in tests/test_judge_accept.py"

    accept_raw = ACCEPT_SCRIPT.read_text(encoding="utf-8")
    lines = accept_raw.splitlines()
    assert lines[0] == f"{H}!/usr/bin/env bash"
    body_after_shebang = "\n".join(lines[1:])
    assert H not in body_after_shebang, "unexpected comment or hash in scripts/judge_accept.sh body"
    assert chr(0x2014) not in accept_raw, "unexpected em dash in scripts/judge_accept.sh"
    assert chr(0x2013) not in accept_raw, "unexpected en dash in scripts/judge_accept.sh"
    assert "printf '  [%s] %s - %s\\n'" in accept_raw
    assert "_descendants()" in accept_raw
    assert "pkill" not in accept_raw
    assert "killall" not in accept_raw
    assert "RESULT: PASS" in accept_raw
    assert "RESULT: FAIL" in accept_raw


def test_cold_run_invokes_setup_and_reproduce(opencode_tmp: Path) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=False)
    proc, port = _run_accept(repo, bin_dir, opencode_tmp)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _read_make_targets(log_path) == ["setup", "reproduce", "mcp"]
    assert "[PASS] make reproduce exits 0 - see results/latest/judge_table.md" in proc.stdout
    assert (
        f"[PASS] MCP server binds - http://127.0.0.1:{port}/mcp JSON-RPC initialize=200, /ledger token=200 unauth=403"
        in proc.stdout
    )
    assert "PASS=20  FAIL=0  SKIP=1" in proc.stdout
    assert "RESULT: PASS" in proc.stdout


def test_warm_fresh_outputs_reuse_without_rerunning_reproduce(opencode_tmp: Path) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=True)
    proc, port = _run_accept(repo, bin_dir, opencode_tmp)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _read_make_targets(log_path) == ["setup", "mcp"]
    assert "reusing fresh results/latest/judge_table.md (" in proc.stdout
    assert "[PASS] make reproduce exits 0 - reused fresh results/latest/judge_table.md (" in proc.stdout
    assert "set ACCEPT_FORCE_REPRODUCE=1 to rerun)" in proc.stdout
    assert (
        f"[PASS] MCP server binds - http://127.0.0.1:{port}/mcp JSON-RPC initialize=200, /ledger token=200 unauth=403"
        in proc.stdout
    )
    assert "PASS=20  FAIL=0  SKIP=1" in proc.stdout
    assert "RESULT: PASS" in proc.stdout


@pytest.mark.parametrize(
    "invalidation",
    [
        "force_env",
        "stale_zero_budget",
        "expired_mtime",
        "all_blocked_false",
        "consistency_false",
        "headline_mismatch",
        "newer_rules_py",
        "missing_tier_section",
    ],
)
def test_cache_invalidation_forces_make_reproduce(opencode_tmp: Path, invalidation: str) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=True)
    extra_env: dict[str, str] = {}
    latest = repo / "results" / "latest"

    if invalidation == "force_env":
        extra_env["ACCEPT_FORCE_REPRODUCE"] = "1"
    elif invalidation == "stale_zero_budget":
        extra_env["ACCEPT_REUSE_MAX_AGE_S"] = "0"
    elif invalidation == "expired_mtime":
        old_ts = time.time() - 905.0
        os.utime(latest / "judge_table.md", (old_ts, old_ts))
    elif invalidation == "all_blocked_false":
        (latest / "exploits.json").write_text(
            json.dumps(
                {
                    "all_blocked": False,
                    "replay_all_consistent": True,
                    "harbor_all_consistent": True,
                }
            ),
            encoding="utf-8",
        )
    elif invalidation == "consistency_false":
        (latest / "exploits.json").write_text(
            json.dumps(
                {
                    "all_blocked": True,
                    "replay_all_consistent": True,
                    "harbor_all_consistent": False,
                }
            ),
            encoding="utf-8",
        )
    elif invalidation == "headline_mismatch":
        (latest / "paired_table_gemini.md").write_text("| hard | drifted |\n", encoding="utf-8")
    elif invalidation == "newer_rules_py":
        future_ts = time.time() + 2.0
        os.utime(repo / "canary" / "rules.py", (future_ts, future_ts))
    elif invalidation == "missing_tier_section":
        (latest / "judge_table.md").write_text(
            _build_judge_table(tiers=("medium", "easy")),
            encoding="utf-8",
        )

    proc, _ = _run_accept(repo, bin_dir, opencode_tmp, extra_env=extra_env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _read_make_targets(log_path) == ["setup", "reproduce", "mcp"]
    assert "[PASS] make reproduce exits 0 - see results/latest/judge_table.md" in proc.stdout
    assert "PASS=20  FAIL=0  SKIP=1" in proc.stdout
    assert "RESULT: PASS" in proc.stdout


def test_out_of_band_baseline_score_triggers_fail(opencode_tmp: Path) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=True)
    bad_table = _build_judge_table(
        solver_scores={"hard": 0.100},
        do_nothing_scores={"hard": 0.050},
    )
    (repo / "results" / "latest" / "judge_table.md").write_text(bad_table, encoding="utf-8")

    proc, _ = _run_accept(repo, bin_dir, opencode_tmp)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _read_make_targets(log_path) == ["setup", "mcp"]
    assert "[FAIL] solver hard -" in proc.stdout
    assert "[FAIL] do_nothing hard -" in proc.stdout
    assert "PASS=18  FAIL=2  SKIP=1" in proc.stdout
    assert "RESULT: FAIL" in proc.stdout


@pytest.mark.parametrize("bad_mode", ["bare_400", "missing_server_info", "unauth_200"])
def test_mcp_smoke_rejects_broken_protocol_or_ledger_auth(opencode_tmp: Path, bad_mode: str) -> None:
    repo, bin_dir, _ = _create_synthetic_repo(opencode_tmp, warm=True)
    proc, _ = _run_accept(repo, bin_dir, opencode_tmp, extra_env={"STUB_MCP_MODE": bad_mode})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "[FAIL] MCP server binds -" in proc.stdout
    assert "PASS=19  FAIL=1  SKIP=1" in proc.stdout
    assert "RESULT: FAIL" in proc.stdout


def test_live_real_canary_mcp_server_smoke_and_isolated_cleanup(opencode_tmp: Path) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=True, live_mcp=True)
    shutil.copy2(ROOT / "canary" / "rules.py", repo / "canary" / "rules.py")
    shutil.copy2(ROOT / "results" / "anticheat" / "exploits.json", repo / "results" / "anticheat" / "exploits.json")
    shutil.copy2(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md",
        repo / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md",
    )
    past = time.time() - 120.0
    for f in (
        repo / "canary" / "rules.py",
        repo / "results" / "anticheat" / "exploits.json",
        repo / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md",
    ):
        os.utime(f, (past, past))
    latest = repo / "results" / "latest"
    shutil.copy2(ROOT / "results" / "judge_table.md", latest / "judge_table.md")
    shutil.copy2(ROOT / "results" / "anticheat" / "exploits.json", latest / "exploits.json")
    shutil.copy2(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md",
        latest / "paired_table_gemini.md",
    )
    now = time.time()
    for f in (latest / "judge_table.md", latest / "exploits.json", latest / "paired_table_gemini.md"):
        os.utime(f, (now, now))

    bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        proc, port = _run_accept(repo, bin_dir, opencode_tmp)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert _read_make_targets(log_path) == ["setup", "mcp"]
        assert (
            f"[PASS] MCP server binds - http://127.0.0.1:{port}/mcp JSON-RPC initialize=200, /ledger token=200 unauth=403"
            in proc.stdout
        )
        assert "PASS=20  FAIL=0  SKIP=1" in proc.stdout
        assert "RESULT: PASS" in proc.stdout
        assert bystander.poll() is None, "judge_accept.sh must never kill unrelated processes"

        rebound = False
        for _ in range(20):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    sock.bind(("127.0.0.1", port))
                    rebound = True
                    break
            except OSError:
                time.sleep(0.1)
        assert rebound, f"port {port} was not released after judge_accept.sh cleanup"
    finally:
        bystander.terminate()
        bystander.wait(timeout=5)


def _build_diffutils_free_path(bin_dir: Path, tmp_base: Path) -> tuple[str, Path]:
    sys_bin = tmp_base / "sys_bin_no_diffutils"
    sys_bin.mkdir(parents=True, exist_ok=True)
    empty_home = tmp_base / "empty_home"
    empty_home.mkdir(parents=True, exist_ok=True)
    _write_shell_executable(sys_bin / "python3", f'exec "{sys.executable}" "$@"\n')
    needed_tools = (
        "awk",
        "bash",
        "cat",
        "curl",
        "dirname",
        "env",
        "grep",
        "head",
        "mkdir",
        "mktemp",
        "pgrep",
        "rm",
        "sed",
        "seq",
        "sh",
        "sleep",
        "tail",
        "tr",
        "uname",
    )
    for tool in needed_tools:
        found = shutil.which(tool)
        if found:
            dest = sys_bin / tool
            if not dest.exists():
                os.symlink(found, dest)
    isolated_path = f"{bin_dir}:{sys_bin}"
    assert shutil.which("cmp", path=isolated_path) is None
    assert shutil.which("diff", path=isolated_path) is None
    return isolated_path, empty_home


def test_strip_container_without_cmp_or_diff_passes_cold_reproduce(opencode_tmp: Path) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=False)
    isolated_path, empty_home = _build_diffutils_free_path(bin_dir, opencode_tmp)
    probe_json = opencode_tmp / "shim_probe.json"
    bash_bin = shutil.which("bash", path=isolated_path)
    assert bash_bin is not None

    port = _free_port()
    scratch = opencode_tmp / f"scratch-strip-{port}"
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    env["PATH"] = isolated_path
    env["HOME"] = str(empty_home)
    env["TMPDIR"] = str(scratch)
    env["MCP_PORT"] = str(port)
    env["STUB_SHIM_PROBE_JSON"] = str(probe_json)

    proc = subprocess.run(
        [bash_bin, str(repo / "scripts" / "judge_accept.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _read_make_targets(log_path) == ["setup", "reproduce", "mcp"]
    assert "HEADLINE (README table, recomputed from committed episodes;" in proc.stdout
    assert "[PASS] make reproduce exits 0 - see results/latest/judge_table.md" in proc.stdout
    assert "PASS=20  FAIL=0  SKIP=1" in proc.stdout
    assert "RESULT: PASS" in proc.stdout

    probe = json.loads(probe_json.read_text(encoding="utf-8"))
    assert probe["cmp_bin"] is not None and "shim-bin/cmp" in probe["cmp_bin"]
    assert probe["diff_bin"] is not None and "shim-bin/diff" in probe["diff_bin"]
    assert probe["cmp_eq"] == 0
    assert probe["cmp_ne"] == 1
    assert probe["cmp_missing"] == 2
    assert probe["diff_eq"] == 0
    assert probe["diff_eq_stdout"] == ""
    assert probe["diff_ne"] == 1
    assert "--- " in probe["diff_ne_stdout"]
    assert "+++ " in probe["diff_ne_stdout"]
    assert "@@ " in probe["diff_ne_stdout"]
    assert "-beta" in probe["diff_ne_stdout"]
    assert "+gamma" in probe["diff_ne_stdout"]
    assert probe["diff_missing"] == 2
    assert list(scratch.glob("canary-accept.*")) == []


def test_strip_container_headline_drift_surfaces_unified_diff_and_fails(opencode_tmp: Path) -> None:
    repo, bin_dir, log_path = _create_synthetic_repo(opencode_tmp, warm=False)
    isolated_path, empty_home = _build_diffutils_free_path(bin_dir, opencode_tmp)
    bash_bin = shutil.which("bash", path=isolated_path)
    assert bash_bin is not None

    port = _free_port()
    scratch = opencode_tmp / f"scratch-drift-{port}"
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(k, None)
    env["PATH"] = isolated_path
    env["HOME"] = str(empty_home)
    env["TMPDIR"] = str(scratch)
    env["MCP_PORT"] = str(port)
    env["STUB_REPRODUCE_HEADLINE_DRIFT"] = "1"

    proc = subprocess.run(
        [bash_bin, str(repo / "scripts" / "judge_accept.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _read_make_targets(log_path) == ["setup", "reproduce", "mcp"]
    assert "HEADLINE MISMATCH: results/latest/paired_table_gemini.md differs from" in proc.stdout
    assert "--- results/latest/paired_table_gemini.md" in proc.stdout
    assert "+++ data/runs/committed/v1.4/paired_table_gemini.md" in proc.stdout
    assert "@@ " in proc.stdout
    assert "BrokenPipeError" not in proc.stderr
    assert "[FAIL] make reproduce exits 0 - exit 1" in proc.stdout
    assert "RESULT: FAIL" in proc.stdout
    assert list(scratch.glob("canary-accept.*")) == []
