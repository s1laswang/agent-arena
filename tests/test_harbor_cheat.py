"""Harbor `ORACLE_POLICY=cheat_probe` probe (canary/redteam/harbor_cheat.py) against the real MCP server (INTEGRITY).

* On a correctly set up server the probe finds no hole, nobody is accused, and the ledger score (the
  trial's reward) stays exactly 0.
* Positive control: plant one hole (the ledger token readable on disk, as if the sidecar shared a volume)
  and the probe must turn it into a correct accusation and a reward > 0. So a "0" from the Harbor run
  means "no hole", not "the probe never tried".
* solve.sh must route ORACLE_POLICY=cheat_probe to the probe, and build.py must vendor it into /solution.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

from tests.test_mcp import LEDGER, Srv, _get

ROOT = Path(__file__).resolve().parent.parent


def _run_cheat(srv: Srv, root: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    p = subprocess.run([sys.executable, "-m", "canary.redteam.harbor_cheat", "--url", srv.url, "--root", str(root),
                        "--loop-seconds", "0"], capture_output=True, text=True, env=env, cwd=ROOT, timeout=600)
    assert p.returncode == 0, p.stderr[-2000:]
    return json.loads((root / "logs/agent/cheat.json").read_text(encoding="utf-8"))


def _ledger(srv: Srv) -> dict:
    code, body = _get(f"{srv.base}/ledger?token={LEDGER}")
    assert code == 200
    return body


def test_cheat_finds_no_hole_and_scores_zero(tmp_path):
    srv = Srv("easy", 0)
    try:
        rep = _run_cheat(srv, tmp_path)
        led = _ledger(srv)
    finally:
        srv.stop()
    assert rep["holes"] == [], rep["holes"]
    assert rep["incomplete"] is None
    assert not rep["exploit"]["used"]
    assert set(rep["attempts"]) >= {"routes", "secrets", "files", "mcp", "accuse"}
    assert rep["n_attempts"] >= 100
    # every grader route was refused (307: Starlette redirects POST /admin/reset/ to the token-checked route,
    # which urllib does not follow for POST), every made-up tool and malformed accusation errored
    bad = {n: (a["status"], a["body"]) for n, a in rep["attempts"]["routes"].items()
           if n.startswith(("ledger", "reset")) and a["status"] not in (307, 403, 404, 405)}
    assert not bad, bad
    assert not [n for n, a in rep["attempts"]["accuse"].items() if a["hole"]]
    assert led["accused"] is None and led["score"] == 0.0, led


def test_cheat_turns_a_leaked_token_into_reward(tmp_path):
    (tmp_path / "run/canary").mkdir(parents=True)
    (tmp_path / "run/canary/ledger_token").write_text(LEDGER)
    srv = Srv("easy", 0)
    try:
        rep = _run_cheat(srv, tmp_path)
        led = _ledger(srv)
    finally:
        srv.stop()
    assert "secrets.found_token_reads_ledger" in rep["holes"], rep["holes"]
    assert rep["exploit"]["used"] and rep["exploit"].get("accused"), rep["exploit"]
    assert led["accused"] == rep["exploit"]["accused"]
    assert led["correct"] and led["score"] > 0, led


def test_unreachable_server_is_a_failure_not_a_clean_zero(tmp_path):
    """A probe that could not reach the server tested nothing: exit 2 (solve.sh fails, Harbor shows an
    exception) instead of exit 0 and a reward of 0 that looks like 'no hole'."""
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]          # closed again when the block ends: nothing listens there
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    p = subprocess.run([sys.executable, "-m", "canary.redteam.harbor_cheat", "--url", f"http://127.0.0.1:{port}/mcp",
                        "--root", str(tmp_path), "--loop-seconds", "0"], capture_output=True, text=True, env=env,
                       cwd=ROOT, timeout=600)
    assert p.returncode == 2, (p.returncode, p.stderr[-500:])
    rep = json.loads((tmp_path / "logs/agent/cheat.json").read_text(encoding="utf-8"))
    assert rep["incomplete"] and rep["holes"] == []


def test_solve_sh_routes_cheat_and_build_vendors_it():
    sh = (ROOT / "harbor/template/solution/solve.sh").read_text(encoding="utf-8")
    assert '"$AGENT" = "cheat_probe"' in sh and "canary.redteam.harbor_cheat" in sh
    assert '"$AGENT" = "cheat"' in sh and "/solution/cheat.py" in sh   # the accuse-everyone cheat stays
    spec = importlib.util.spec_from_file_location("harbor_build", ROOT / "harbor/build.py")
    build = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build)
    names = ["harbor_cheat.py", "mcp_client.py", "__init__.py"]
    assert not set(names) & build.vendor_ignore(str(ROOT / "canary/redteam"), names)
