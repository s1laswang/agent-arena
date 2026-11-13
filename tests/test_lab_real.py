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
    assert "unfinished_tickets" in t and "| reference |" in t and "## Who gets fooled" in t
    for n in ("gap", "labels", "seats"):
        assert (tmp_path / f"{n}.svg").read_text().startswith("<svg")
