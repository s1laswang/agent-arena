import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DIRS = ["sleeper", "lab", "agents", "harbor", "scripts", "web", "redteam", "train", "arena"]
SELF = {"sleeper/verifier.py"}
TXT_OK = {"harbor/build.py", "harbor/opencode/judge_agents/exploit_agent.py", "redteam/logs_race.sh", "redteam/logs_symlink.sh"}
LITERAL = re.compile(r"""["']reward["']\s*:\s*([1-9]|int\(|bool\()|\breward\s*=\s*([1-9]|int\()|\bResult\(""")


def files():
    for d in DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix in (".py", ".sh") and ".venv" not in p.parts and "__pycache__" not in p.parts:
                yield p, str(p.relative_to(ROOT))


def test_no_reward_computed_outside_verifier():
    bad = []
    for p, rel in files():
        if rel in SELF or rel == "sleeper/models.py" or Path(rel).name.startswith("test_"):
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
    assert "sleeper.verifier --require-seat --state /srv/state.json" in t
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


def test_rescore_and_row_fields(tmp_path):
    from lab.run import play_day

    d = tmp_path / "run" / "days"
    d.mkdir(parents=True)
    for seed, seat in ((4, "finance_ap"), (5, "controller")):
        res, extra = play_day("oracle", "staff", seat, seed, 0)
        assert res["verifier_commit"] and res["model"] and res["seat_under_test"] == seat
        (d / f"{seed}.json").write_text(json.dumps({**extra, "result": res}))
    cmd = [sys.executable, "-m", "sleeper.verifier", "rescore", str(tmp_path / "run")]
    assert subprocess.run(cmd, cwd=ROOT).returncode == 0
    f = d / "4.json"
    x = json.loads(f.read_text())
    x["result"]["reward"] = 1 - x["result"]["reward"]
    f.write_text(json.dumps(x))
    assert subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode == 1


def test_rescore_frontier_layout(tmp_path):
    from lab.run import play_day

    res, extra = play_day("oracle", "staff", "finance_ap", 4, 0)
    d = tmp_path / "m" / "abc"
    d.mkdir(parents=True)
    (d / "st.json").write_text(json.dumps(extra))
    (d / "finance_ap-s4-t0.json").write_text(json.dumps({**res, "state_path": "st.json"}))
    p = subprocess.run([sys.executable, "-m", "sleeper.verifier", "rescore", str(tmp_path)], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout
