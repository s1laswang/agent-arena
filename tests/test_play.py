import json

import pytest

from canary.env import Env
from canary.play import main, parse, session


@pytest.mark.parametrize("line,want", [
    ("status", ("status", {})),
    ("staff", ("list_employees", {})),
    ("employees", ("list_employees", {})),
    ("docs", ("list_documents", {})),
    ("docs 1-3", ("list_documents", {"day_from": 1, "day_to": 3})),
    ("logs 2-4", ("read_access_logs", {"day_from": 2, "day_to": 4})),
    ("logs 2-4 e07", ("read_access_logs", {"day_from": 2, "day_to": 4, "employee": "e07"})),
    ("search budget", ("search_messages", {"query": "budget"})),
    ("search vendor call 1-2", ("search_messages", {"query": "vendor call", "day_from": 1, "day_to": 2})),
    ("read m3-1", ("read_message", {"id": "m3-1"})),
    ("interview e03 docs", ("interview", {"employee": "e03", "topic": "recent_documents"})),
    ("interview e03 contacts", ("interview", {"employee": "e03", "topic": "contacts_outside"})),
    ("interview e03 workload", ("interview", {"employee": "e03", "topic": "workload"})),
    ("interview e03 access", ("interview", {"employee": "e03", "topic": "access_needs"})),
    ('canary "Q3 plan" e01,e02=A e03=B', ("plant_canary", {"doc_title": "Q3 plan",
                                          "assignment": {"e01": "A", "e02": "A", "e03": "B"}})),
    ("feed", ("check_leak_feed", {})),
    ("restrict e04", ("restrict_access", {"employee": "e04"})),
    ("unrestrict e04", ("unrestrict_access", {"employee": "e04"})),
    ("next", ("advance_day", {})),
    ("advance", ("advance_day", {})),
    ("accuse e05", ("accuse", {"employee": "e05"})),
])
def test_parse(line, want):
    assert parse(line) == want


@pytest.mark.parametrize("bad", ["", "dance", "logs", "logs x-y", "logs 1-2 bob", "interview e01 vibes",
                                  "interview bob docs", 'canary "t" e01', 'canary "t" x1=A', "accuse",
                                  "restrict all", "docs yesterday", 'canary "unterminated', "status now"])
def test_parse_bad(bad):
    assert parse(bad) is None


def test_unknown_input_does_not_touch_env(tmp_path):
    env = Env("easy", 3001)
    session(env, ["dance", "help", "rules", "quit"], "t", "easy", 3001, out=lambda *_: None, out_dir=str(tmp_path))
    assert len(env.history) == 0


def test_scripted_session_saves_jsonl(tmp_path):
    env = Env("easy", 3002)
    lines = ["status", "staff", "logs 1-1", "interview e01 docs", 'canary "Plan" e00,e01=A e02=B',
             "next", "feed", "accuse e01", "n", "accuse e01", "y"]
    out = []
    path = session(env, lines, "bot", "easy", 3002, out=out.append, out_dir=str(tmp_path))
    assert env.done
    assert "cancelled" in out
    rows = [json.loads(l) for l in open(path)]
    assert len(rows) == 1 and rows[0]["agent"] == "human:bot" and rows[0]["accused"] == "e01"
    assert not any("correct=" in o for o in out)
    from canary.eval import episode_from_dict
    episode_from_dict(rows[0])


def test_rejects_judge_seed():
    with pytest.raises(SystemExit):
        main(["--seed", "900001"])
    with pytest.raises(SystemExit):
        main(["--seed", "12"])
