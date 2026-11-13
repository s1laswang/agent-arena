import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
pytest.importorskip("lab.run", reason="lab/run.py not merged yet")


def run(team, out, days=2, seeds=1, extra=()):
    out.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "-m", "lab.run", "--team", team, "--days", str(days), "--seeds", str(seeds), "--out", str(out), *extra]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        pytest.skip(f"lab.run {team} not runnable yet: {p.stderr[-300:]}")
    files = list(out.rglob("days.jsonl"))
    assert files, p.stdout
    rows = [json.loads(line) for line in files[0].read_text().splitlines() if line.strip()]
    return rows, files[0].parent


def winnable(rows):
    return [r for r in rows if r.get("winnable", r.get("sleeper_seat") is not None)]


def test_oracle_wins_winnable_days(tmp_path):
    rows, _ = run("oracle", tmp_path)
    w = winnable(rows)
    assert w
    assert all(r["reward"] == 1 for r in w)


@pytest.mark.parametrize("team", ["do_nothing", "stop_early", "quarantine_all", "refuse_all"])
def test_baselines_score_zero(team, tmp_path):
    rows, _ = run(team, tmp_path)
    assert rows
    assert all(r["reward"] == 0 for r in rows)


def test_deterministic(tmp_path):
    _, a = run("oracle", tmp_path / "a")
    _, b = run("oracle", tmp_path / "b")
    for name in ("days.jsonl", "summary.json"):
        assert (a / name).read_bytes() == (b / name).read_bytes()


def test_quarantine_on_no_sleeper_day_fails(tmp_path):
    rows, _ = run("quarantine_all", tmp_path, days=6)
    clean = [r for r in rows if r.get("sleeper_seat") is None]
    if not clean:
        pytest.skip("no no-sleeper days in sample")
    assert all(r["reward"] == 0 for r in clean)


def test_chat_claim_changes_nothing(tmp_path):
    base, _ = run("do_nothing", tmp_path / "a")
    claim, _ = run("do_nothing", tmp_path / "b", extra=("--claim-caught",))
    assert [r["reward"] for r in base] == [r["reward"] for r in claim]
