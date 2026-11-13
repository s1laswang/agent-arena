import json

from lab.results import load_days, pass_hat_k, summarise
from lab.run import run


def row(day, seed, reward, sleeper=True, harm=False, fq=(), done=5, total=5, goal="fraud"):
    return {"day_id": day, "seed": seed, "reward": reward, "has_sleeper": sleeper, "harm": ["x"] if harm else [], "false_quarantine": list(fq), "tickets_done": done, "tickets_total": total, "goal_kind": goal if sleeper else None, "agent": "t"}


def test_pass_hat_k():
    assert pass_hat_k(3, 2, 1) == 2 / 3
    assert pass_hat_k(3, 2, 2) == 1 / 3
    assert pass_hat_k(3, 2, 3) == 0
    assert pass_hat_k(3, 3, 3) == 1


def test_summarise():
    rows = [row(0, 0, 1), row(0, 1, 1), row(0, 2, 0, harm=True), row(1, 0, 0, sleeper=False, fq=["hr"], done=3), row(1, 1, 0, sleeper=False), row(1, 2, 0, sleeper=False)]
    s = summarise(rows)
    assert s["n_days"] == 2 and s["n_runs"] == 6
    assert abs(s["pass^1"] - (2 / 3 + 0) / 2) < 1e-9
    assert abs(s["pass^3"]) < 1e-9
    assert abs(s["sleeper_success_rate"] - 1 / 3) < 1e-9
    assert abs(s["false_accusation_rate"] - 1 / 6) < 1e-9
    assert s["no_sleeper_days"]["n"] == 3
    assert s["by_goal_kind"]["fraud"]["n"] == 3
    assert abs(s["ticket_completion"] - 28 / 30) < 1e-9


def fake(team, agent, seat, day_id, trial):
    return row(day_id, 0, int(trial != 2)), {"day": {"day_id": day_id}, "company": {}, "ledger": [], "messages": [], "steps": []}


def test_run_and_eval(tmp_path):
    d1, s1 = run("oracle", 2, 3, out=str(tmp_path / "a"), runner=fake, day_start=1000)
    d2, s2 = run("oracle", 2, 3, out=str(tmp_path / "b"), runner=fake, day_start=1000)
    assert d1.endswith("oracle-all-d2@1000-t3")
    assert s1 == s2 and s1["deterministic"] is False and s1["agent_kind"] == "scripted"
    rows = load_days(d1 + "/days.jsonl")
    assert len(rows) == 6 and rows[0]["day_id"] == 1000
    assert json.load(open(d1 + "/" + rows[0]["transcript_path"]))["result"]["day_id"] == 1000
    from lab.eval import main as ev

    out = ev(["--days", "1", "--trials", "2", "--out", str(tmp_path / "e"), "--web-out", str(tmp_path / "w")], runner=fake)
    assert "oracle" in json.load(open(tmp_path / "w/summary.json"))
    assert set(out[0]) >= {"oracle", "refuse_all"} and set(out[1]) == {"staff", "reference", "oracle", "do_nothing"}
    assert "gap vs reference" in open(tmp_path / "e/eval/gap.md").read()


def test_recorder():
    from lab.run import Recorder

    class A:
        def turn(self, seat, view, tools, call):
            call("read_chat")

    steps = []
    Recorder("hr", A(), steps).turn("hr", {"tick": 3}, [], lambda t, *a, **k: {"ok": False})
    assert steps[0]["seat"] == "hr" and steps[0]["ok"] is False and steps[0]["tick"] == 3


def test_eval_missing_team(tmp_path):
    def boom(team, agent, seat, day_id, trial):
        if team == "reference":
            raise ImportError("missing")
        return fake(team, agent, seat, day_id, trial)

    from lab.eval import main as ev

    ev(["--days", "1", "--trials", "1", "--out", str(tmp_path), "--web-out", ""], runner=boom)
    md = open(tmp_path / "eval/gap.md").read()
    assert "| reference | NOT FOUND" in md


def test_jobs_identical(tmp_path):

    _, a = run("oracle", 3, 2, out=str(tmp_path / "a"), day_start=0)
    _, b = run("oracle", 3, 2, out=str(tmp_path / "b"), day_start=0, jobs=2)
    assert a == b
    assert (tmp_path / "a/oracle-all-d3@0-t2/days.jsonl").read_bytes() == (tmp_path / "b/oracle-all-d3@0-t2/days.jsonl").read_bytes()


def test_run_wipes_stale(tmp_path):
    import os

    run("oracle", 3, 1, out=str(tmp_path), runner=fake, day_start=0)
    d, _ = run("oracle", 3, 1, out=str(tmp_path), runner=fake, day_start=0)
    open(d + "/days/stale.json", "w").write("{}")
    d, _ = run("oracle", 3, 1, out=str(tmp_path), runner=fake, day_start=0)
    assert "stale.json" not in os.listdir(d + "/days")
