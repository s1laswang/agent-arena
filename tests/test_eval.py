import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ZERO = {"do_nothing", "stop_early", "quarantine_all", "refuse_all"}


def eval_into(out):
    p = subprocess.run([sys.executable, "-m", "lab.eval", "--out", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=1800)
    assert p.returncode == 0, p.stderr[-800:]
    return out


@pytest.fixture(scope="module")
def two_runs(tmp_path_factory):
    base = tmp_path_factory.mktemp("eval")
    return eval_into(base / "a"), eval_into(base / "b")


def tables(out):
    cur, head, rows = None, None, []
    for line in (out / "eval" / "gap.md").read_text().splitlines():
        if line.startswith("## "):
            cur = line[3:]
            head = None
        elif line.startswith("| team") and cur.startswith(("Team plays", "Staff background")):
            head = [x.strip() for x in line.strip("|").split("|")]
        elif line.startswith("|") and not line.startswith("|---") and head:
            c = [x.strip() for x in line.strip("|").split("|")]
            name = c[0].split(" [")[0].split(" (")[0]
            rows.append((cur, name, c[head.index("reward")]))
    return rows


@pytest.mark.slow
def test_eval_summary_identical(two_runs):
    a, b = two_runs
    assert (a / "eval" / "summary.json").read_bytes() == (b / "eval" / "summary.json").read_bytes()
    assert (a / "eval" / "gap.md").read_bytes() == (b / "eval" / "gap.md").read_bytes()


@pytest.mark.slow
def test_baselines_zero_in_team_tables(two_runs):
    rows = [r for r in tables(two_runs[0]) if r[1] in ZERO and r[0].startswith("Team plays")]
    assert rows
    assert [r for r in rows if r[2] != "0.000"] == []


@pytest.mark.slow
def test_baselines_zero_in_seat_tables(two_runs):
    rows = [r for r in tables(two_runs[0]) if r[1] in ZERO and r[0].startswith("Staff background")]
    assert rows
    assert [r for r in rows if r[2] != "0.000"] == []
