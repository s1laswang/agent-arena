import json

from lab import analyse, report
from sleeper.day import run_day
from sleeper.scripted import NoopAgent, OracleAgent, make_team
from sleeper.tickets import make_day
from sleeper.verifier import dump_state, score


def dump(cls=OracleAgent):
    d = make_day(1)
    w = run_day(d, make_team(cls))
    r = score(w.day, w.initial, w.company, w.ledger).model_dump()
    r["trial"] = 0
    return analyse.norm({**dump_state(w), "result": r})


def test_oracle_day_has_no_labels():
    assert analyse.label(dump()) == []


def test_mutated_ledger_fires():
    d = dump()
    pay = next(p for p in d["company"]["payments"] if p["amount"] > 10000)
    pay["approved_by"] = []
    for v in d["company"]["vendors"]:
        if v["id"] == pay["vendor_id"]:
            v["vetted"] = False
    d["ledger"] = [a for a in d["ledger"] if a["tool"] not in ("read_doc", "read_audit_log", "search_docs")]
    d["result"]["false_quarantine"] = ["sales"]
    d["ledger"].append({"seq": 999, "tick": 9, "seat": "hr", "tool": "quarantine", "args": {"seat": "sales"}, "ok": True, "effect": ""})
    got = {x["label"] for x in analyse.label(d)}
    assert {"skipped_two_person_rule", "wrong_accusation", "approved_without_checking"} <= got
    assert analyse.is_harmful({"seq": 999}, d) == "wrong_accusation"


def test_noop_unfinished():
    assert "unfinished_tickets" in {x["label"] for x in analyse.label(dump(NoopAgent))}


def test_report(tmp_path):
    for team in ("staff", "reference"):
        d = tmp_path / f"{team}-all-d1@1-t1"
        (d / "days").mkdir(parents=True)
        x = dump(NoopAgent if team == "staff" else OracleAgent)
        x["result"].update(team=team, day_id=1)
        (d / "days" / "1-t0.json").write_text(json.dumps(x))
        (d / "summary.json").write_text(json.dumps({"team": team, "n_runs": 1, "reward_mean": x["result"]["reward"], "pass^1": x["result"]["reward"], "sleeper_success_rate": 0.0, "false_accusation_rate": 0.0, "ticket_completion": 1.0, "by_goal_kind": {}}))
    report.main(tmp_path)
    t = (tmp_path / "REPORT.md").read_text()
    assert "unfinished_tickets" in t and "| reference-all-d1@1-t1 |" in t and "## Who gets fooled" in t
    for n in ("gap", "labels", "seats"):
        assert (tmp_path / f"{n}.svg").read_text().startswith("<svg")


def play(team, day_id):
    from lab.run import play_day
    res, extra = play_day(team, team, None, day_id, 0)
    return analyse.norm({**extra, "result": res})


def mutated():
    d = dump()
    d["result"]["false_quarantine"] = ["sales"]
    d["ledger"].append({"seq": 999, "tick": 9, "seat": "hr", "tool": "quarantine", "args": {"target": "sales"}, "ok": True, "effect": "quarantined sales"})
    return d


def test_fraud_day_oracle_clean():
    assert analyse.label(play("oracle", 1012)) == []


def test_losing_staff_days_are_all_labeled():
    for i in range(1000, 1020):
        d = play("staff", i)
        assert d["result"]["reward"] == 1 or analyse.label(d), i


def test_replay_and_names():
    from lab.replay import replay
    t = replay(mutated(), 999)
    assert "quarantine" in t and "chat before" in t and "wrong_accusation" in t


def test_refine_with_fake_gemini(monkeypatch):
    from agents import gemini
    seen = []
    monkeypatch.setattr(gemini, "enabled", lambda: True)
    monkeypatch.setattr(gemini, "chat", lambda model, system, messages, **kw: seen.append(messages) or {"text": " Because legal never checked. "})
    d = mutated()
    fls = analyse.label(d)
    before = [x["label"] for x in fls]
    analyse.refine(d, fls)
    assert [x["label"] for x in fls] == before
    assert all(x["explanation"] == "Because legal never checked." for x in fls) and seen


def test_refine_no_key_is_noop(monkeypatch):
    from agents import gemini
    monkeypatch.setattr(gemini, "enabled", lambda: False)
    d = mutated()
    fls = analyse.label(d)
    analyse.refine(d, fls)
    assert all("explanation" not in x for x in fls)


def test_unexplained_loss_catch_all():
    d = dump()
    d["result"]["reward"] = 0
    d["result"]["harm"] = ["something odd"]
    assert [x["label"] for x in analyse.label(d)] == ["unexplained_loss"]


def test_fuzz_baselines_every_loss_labeled_no_win_labeled(monkeypatch):
    from lab import run as lrun
    from sleeper import baselines
    for name in ("trust_all", "random_accuse", "claim_only"):
        monkeypatch.setitem(lrun.FACTORIES, name, (getattr(baselines, "make_" + name) and (lambda day, trial, n=name: getattr(baselines, "make_" + n)(day, trial)), "scripted"))
    for name in ("trust_all", "random_accuse", "claim_only"):
        for i in range(1000, 1020):
            d = play(name, i)
            ls = analyse.label(d)
            assert (d["result"]["reward"] == 0) == bool(ls), (name, i, ls)
