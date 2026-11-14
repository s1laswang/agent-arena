from lab.run import day_for
from sleeper.company import World


def test_scan_doc_in_world():
    day, _, _, _ = day_for(1000, "procurement")
    assert day.docs
    w = World(day)
    for d in day.docs:
        assert d["id"] in w.company.docs and d["id"] in w.initial.docs
    assert w.company.docs[day.docs[0]["id"]].image
