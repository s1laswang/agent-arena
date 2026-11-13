import json

from sleeper.day import run_day
from sleeper.models import Day
from sleeper.scripted import NoopAgent, OracleAgent, make_team
from sleeper.tickets import make_day
from sleeper.transcript import transcript, write


def test_rows_ordered_and_no_secrets(tmp_path):
    day = make_day(0, sleeper_seat="controller")
    w = run_day(day, make_team(OracleAgent))
    rows = transcript(w)
    assert rows
    assert [r["tick"] for r in rows] == sorted(r["tick"] for r in rows)
    assert {r["type"] for r in rows} <= {"action", "message"}
    p = tmp_path / "d.jsonl"
    write(w, p)
    text = p.read_text()
    assert len(text.splitlines()) == len(rows)
    assert "sleeper_seat" not in text and "goal" not in text
    assert all(json.loads(l) for l in text.splitlines())


def test_noop_has_only_end_turns():
    w = run_day(make_day(1), make_team(NoopAgent))
    assert all(r["tool"] == "end_turn" for r in transcript(w) if r["type"] == "action")


def test_team_spec_and_cli(tmp_path):
    import subprocess, sys
    from sleeper.transcript import build_team
    day = make_day(0)
    assert set(build_team("noop", day)) == set(build_team("oracle", day))
    r = subprocess.run([sys.executable, "-m", "sleeper.transcript", "--team", "agents.reference:make_oracle_team",
                        "--sleeper-seat", "controller", "--out", str(tmp_path / "o.jsonl")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-400:]
    assert (tmp_path / "o.jsonl").stat().st_size > 0
    r = subprocess.run([sys.executable, "-m", "sleeper.transcript", "--goal", "x"], capture_output=True, text=True)
    assert r.returncode != 0
