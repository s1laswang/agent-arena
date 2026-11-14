import pytest
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_tampered_state_fails_closed(tmp_path):
    from lab.run import build_team, day_for
    from sleeper.day import run_day
    from sleeper.verifier import dump_state, sign

    day, *_ = day_for(4, "finance_ap")
    w = run_day(day, build_team("oracle", day, 0))
    st = sign({**dump_state(w), "seat_under_test": "finance_ap"}, "key")
    ok, bad, unsigned = tmp_path / "ok.json", tmp_path / "bad.json", tmp_path / "un.json"
    ok.write_text(json.dumps(st))
    t = json.loads(json.dumps(st))
    t["ledger"] = t["ledger"][:-1]
    bad.write_text(json.dumps(t))
    unsigned.write_text(json.dumps({k: v for k, v in st.items() if k != "sig"}))

    def cli(p):
        r = subprocess.run([sys.executable, "-m", "sleeper.verifier", "--state", str(p)], capture_output=True, text=True, cwd=ROOT, env={"PYTHONPATH": str(ROOT), "PATH": "/usr/bin:/bin", "VERIFY_TOKEN": "key"})
        return json.loads(r.stdout)

    assert cli(ok)["reward"] == 1
    for p in (bad, unsigned):
        r = cli(p)
        assert r["reward"] == 0 and r["harm"] == ["state_tampered@-1"]
    m = tmp_path / "garbage.json"
    m.write_text("{")
    assert cli(m)["reward"] == 0


