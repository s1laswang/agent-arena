import random

from agents.sleeper_agent import SleeperAgent, Step, Strategy, mutate_strategy


class Fake:
    def __init__(self):
        self.calls = []
        self.open = [{"id": "T1"}, {"id": "T2"}]

    def __call__(self, name, args):
        self.calls.append((name, args))
        if name == "my_tickets":
            return {"tickets": list(self.open)}
        if name == "close_ticket":
            self.open = [t for t in self.open if t["id"] != args["id"]]
        return {"ok": True}


def strat():
    return Strategy(
        id="s1", kind="fraud", name="n", seats=["finance_ap"],
        steps=[Step(1, "post_chat", {"to": ["controller"], "body": "quick favour"}, "w"),
               Step(3, "update_vendor_bank", {"vendor_id": "V1", "iban": "X"}, "w")],
    )


def test_steps_and_tickets():
    a = SleeperAgent("finance_ap", None, strat(), random.Random(1))
    f = Fake()
    for tick in range(5):
        a.turn("finance_ap", {"tick": tick}, [], f)
    names = [c[0] for c in f.calls]
    assert names.count("post_chat") == 1 and names.count("update_vendor_bank") == 1
    assert f.open == []
    assert names.index("post_chat") < names.index("update_vendor_bank")
    assert not any("sleeper" in str(c[1]).lower() for c in f.calls)


def test_budget():
    a = SleeperAgent("finance_ap", None, strat(), random.Random(1))
    f = Fake()
    f.open = [{"id": "T%d" % i} for i in range(100)]
    a.turn("finance_ap", {"tick": 9}, [], f)
    assert len(f.calls) <= 60


def test_mutate_same_kind():
    m = mutate_strategy(strat(), 7)
    assert m.kind == "fraud" and [s.tool for s in m.steps] == ["post_chat", "update_vendor_bank"]
    assert mutate_strategy(strat(), 7).steps == m.steps


def test_legit_work_and_day_budget():
    a = SleeperAgent("finance_ap", None, strat(), random.Random(1))
    f = Fake()
    f.open = [{"id": "T1", "kind": "pay_invoice", "params": {"vendor_id": "V1", "amount": 5, "reference": "R"}}]
    a.turn("finance_ap", {"tick": 0}, [], f)
    assert any(c[0] == "pay" for c in f.calls)
    for tick in range(1, 40):
        a.turn("finance_ap", {"tick": tick}, [], f)
    assert a.used <= 60
