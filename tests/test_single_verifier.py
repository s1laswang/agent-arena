import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIRS = ["sleeper", "lab", "agents", "harbor", "scripts", "web", "redteam", "train", "arena"]
SELF = {"sleeper/verifier.py"}
TXT_OK = {"harbor/build.py", "harbor/opencode/judge_agents/exploit_agent.py", "redteam/logs_race.sh"}
LITERAL = re.compile(r"""["']reward["']\s*:\s*(\d|int\(|bool\()|\breward\s*=\s*(\d|int\()|\bResult\(""")


def files():
    for d in DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix in (".py", ".sh") and ".venv" not in p.parts and "__pycache__" not in p.parts:
                yield p, str(p.relative_to(ROOT))


def test_no_reward_computed_outside_verifier():
    bad = []
    for p, rel in files():
        if rel in SELF or rel == "sleeper/models.py":
            continue
        for i, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if LITERAL.search(line):
                bad.append(f"{rel}:{i}: {line.strip()}")
    assert not bad, bad


def test_reward_txt_written_only_by_allowed_files():
    bad = [rel for p, rel in files() if rel not in TXT_OK and any("reward.txt" in l and re.search(r">|write|open\(", l) and "cat " not in l for l in p.read_text(errors="ignore").splitlines())]
    assert not bad, bad


def test_harbor_template_reads_sidecar_reward():
    t = (ROOT / "harbor/build.py").read_text()
    assert "sleeper-server:8001/reward" in t and 'r.get("reward") == 1' in t
    assert "sleeper.verifier" in (ROOT / "harbor/sidecar.py").read_text()


@pytest.mark.parametrize("team,seed,seat", [("oracle", 4, "finance_ap"), ("staff", 5, "finance_ap"), ("trust_all", 4, "controller"), ("staff", 7, None)])
def test_inprocess_equals_cli(team, seed, seat, tmp_path):
    from lab.run import build_team, day_for
    from sleeper.day import run_day
    from sleeper.models import Company
    from sleeper.verifier import dump_state, score

    day, *_ = day_for(seed, seat)
    w = run_day(day, build_team(team, day, 0))
    a = score(day, w.initial, w.company, w.ledger, seat_under_test=seat).model_dump()
    p = tmp_path / "s.json"
    st = dump_state(w)
    st["seat_under_test"] = seat
    p.write_text(json.dumps(st))
    r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(p)], capture_output=True, text=True, cwd=ROOT, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin"})
    assert json.loads(r.stdout) == a
