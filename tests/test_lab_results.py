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
    assert set(out[0]) >= {"oracle", "refuse_all"} and {k.split(" ")[0] for k in out[1]} == {"staff", "reference", "oracle", "do_nothing"}
    assert "gap vs reference" in open(tmp_path / "e/eval/gap.md").read()


def test_eval_summary_block(tmp_path, capsys):
    from lab.eval import main as ev

    (tmp_path / "e/runs/stale-all-d1@0-t1/days").mkdir(parents=True)
    ev(["--days", "2", "--trials", "1", "--out", str(tmp_path / "e"), "--web-out", ""], runner=fake)
    assert not (tmp_path / "e/runs/stale-all-d1@0-t1").exists()
    tail = capsys.readouterr().out.split("\nSUMMARY ")[1].splitlines()
    assert tail[0].startswith("(2 days x 1 trials)") and len(tail) == 6
    assert tail[1].startswith("all 8 seats: oracle") and tail[2].startswith("do_nothing")
    assert "needs-seat days: oracle" in tail[3] and tail[4].startswith("self-checks:") and tail[5].startswith("full table:")


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


def test_gemini_usage_and_budget(tmp_path, monkeypatch):
    from agents import gemini
    from lab.run import main

    monkeypatch.setenv("LAB_GEMINI", "1")
    monkeypatch.delenv("SLEEPER_MAX_CALLS", raising=False)

    def g(team, agent, seat, day_id, trial):
        gemini._usage["calls"] += 2
        gemini._usage["cache_hits"] += 1
        return fake(team, agent, seat, day_id, trial)

    _, s = run("staff", 2, 2, out=str(tmp_path), runner=g)
    assert s["gemini_usage"]["calls"] == 8 and s["gemini_usage"]["cache_hits"] == 4
    assert s["agent_kind"] == "gemini"
    assert s["gemini_usage"]["budget_exhausted"] is False
    monkeypatch.delenv("LAB_GEMINI")
    monkeypatch.delenv("SLEEPER_MAX_CALLS", raising=False)
    _, s = run("staff", 1, 1, out=str(tmp_path / "x"), runner=fake)
    assert s["agent_kind"] == "scripted" and "gemini_usage" not in s


def test_strategy_table(tmp_path):
    from lab.eval import strategy_table

    def mk(harm):
        def r(team, agent, seat, day_id, trial):
            x = row(day_id, 0, 0, harm=harm)
            x["strategy"] = "s1" if day_id % 2 else "s2"
            return x, {}
        return r

    runs = {"trust_all": run("do_nothing", 2, 1, out=str(tmp_path / "a"), runner=mk(False), day_start=0),
            "staff": run("staff", 2, 1, out=str(tmp_path / "b"), runner=mk(True), day_start=0)}
    t = strategy_table(runs)
    assert "| s1 | fraud | 1 | 0.00 | 1.00 | n/a | DEAD vs trust_all |" in t


def test_replace_hook():
    from lab.run import play_day

    base, _ = play_day("oracle", "oracle", None, 1000, 0)
    swapped, _ = play_day("oracle", "oracle", None, 1000, 0, replace={"finance_ap": "do_nothing"})
    assert swapped["seat_under_test"] is None
    assert swapped["day_id"] == base["day_id"] and swapped["sleeper_seat"] == base["sleeper_seat"]
    assert swapped["tickets_done"] < base["tickets_done"] or swapped["reward"] <= base["reward"]


class Noisy:
    def __init__(self, agent, rng, p):
        self.agent, self.rng, self.p = agent, rng, p

    def turn(self, seat, view, tools, call):
        if self.rng.random() < self.p:
            return call("end_turn", {})
        return self.agent.turn(seat, view, tools, call)


def test_passk_shape_with_noise(tmp_path, monkeypatch):
    import random

    import lab.run as lr

    real = lr.build_team

    def noisy(name, day, trial):
        return {s: Noisy(a, random.Random(f"{day.seed}-{trial}-{s}"), 0.7) for s, a in real(name, day, trial).items()}

    monkeypatch.setattr(lr, "build_team", noisy)
    _, s = run("oracle", 6, 4, out=str(tmp_path), day_start=1000)
    assert s["deterministic"] is False
    assert 0 < s["pass^1"] < 1
    assert s["pass^1"] >= s["pass^2"] >= s["pass^3"] >= s["pass^4"]
    assert s["pass^1"] > s["pass^4"]


def test_day_type_and_seat_tables():
    from lab.eval import day_type_table, seat_split_table

    rows = [dict(row(0, 0, 1), sleeper_seat="legal"), dict(row(1, 0, 0), sleeper_seat="hr"), dict(row(2, 0, 1, sleeper=False), sleeper_seat=None)]
    s = {"trust_all": summarise(rows), "missing": None}
    t = day_type_table(s)
    assert "| trust_all | 0.667 | 0.500 (n=2) | 1.000 (n=1) |" in t and "| missing | NOT FOUND" in t
    assert "| trust_all | 0.00 (n=1) | 1.00 (n=1) |" in seat_split_table(s)


def test_eval_strict(tmp_path, monkeypatch):
    import sys
    import types

    import pytest

    from lab.eval import main as ev

    mod = types.ModuleType("lab.check")
    mod.append = lambda runs, gap: ["PASS a", "FAIL b"]
    monkeypatch.setitem(sys.modules, "lab.check", mod)
    import lab

    monkeypatch.setattr(lab, "check", mod, raising=False)
    args = ["--days", "1", "--trials", "1", "--exploit-days", "1", "--out", str(tmp_path), "--web-out", "", "--no-report"]
    ev(args, runner=fake)
    with pytest.raises(SystemExit):
        ev(args + ["--strict"], runner=fake)


def test_eval_extra_seat(tmp_path):
    from lab.eval import main as ev

    ev(["--days", "1", "--trials", "1", "--exploit-days", "1", "--out", str(tmp_path), "--web-out", "", "--no-report", "--full"], runner=fake)
    md = open(tmp_path / "eval/gap.md").read()
    assert "finance_ap seat swapped" in md and "controller seat swapped" in md
