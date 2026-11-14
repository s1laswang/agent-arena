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
        id="s1", kind="fraud", name="n", seats=["finance_ap"], tells=[], counter="",
        steps=[Step(tick=1, tool="post_chat", args={"to": ["controller"], "body": "quick favour"}, why="w"),
               Step(tick=3, tool="update_vendor_bank", args={"vendor_id": "V1", "iban": "X"}, why="w")],
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


def test_gemini_path(monkeypatch):
    import json
    import agents.gemini as g

    seen = {}

    def fake_chat(model, system, messages, tools=None, temperature=0, seed=None):
        seen["system"] = system
        steps = json.loads(messages[0]["text"])["steps"]
        for s in steps:
            s["tick"] += 1
        return {"text": json.dumps(steps), "tool_calls": []}

    def fake_loop(model, system, view_text, tools, call, max_steps=60, temperature=0, seed=None, **kw):
        seen["loop"] = system
        call("my_tickets", {})
        call("end_turn", {})
        return {"text": "", "messages": []}

    monkeypatch.setattr(g, "enabled", lambda: True)
    monkeypatch.setattr(g, "chat", fake_chat)
    monkeypatch.setattr(g, "run_tool_loop", fake_loop)
    m = mutate_strategy(strat(), 3)
    assert [s.tick for s in m.steps] == [2, 4] and "tool" not in seen.get("loop", "")
    a = SleeperAgent("finance_ap", None, m, random.Random(1))
    f = Fake()
    a.turn("finance_ap", {"tick": 5}, [], f)
    names = [c[0] for c in f.calls]
    assert "update_vendor_bank" in names and "post_chat" in names
    assert "audit log" in seen["loop"]


def test_variants_keep_shape():
    from agents.sleeper_agent import variants
    from sleeper import goals

    sid = "fraud.bank_swap"
    base = goals.STRATEGIES[sid]
    vs = variants(sid, 1)
    assert len(vs) == 3
    for v in vs:
        assert v.seats == base.seats and v.tells == base.tells and v.counter == base.counter
        assert [(s.tool, s.seat) for s in v.steps] == [(s.tool, s.seat) for s in base.steps]


def test_gemini_variant_must_keep_placeholders(monkeypatch):
    import json
    import agents.gemini as g
    from sleeper import goals

    base = goals.STRATEGIES["fraud.bank_swap"]

    def bad(model, system, messages, **kw):
        steps = json.loads(messages[0]["text"])["steps"]
        steps[0]["args"] = {"to": ["procurement"], "body": "plain text no holes"}
        return {"text": json.dumps(steps), "tool_calls": []}

    monkeypatch.setattr(g, "enabled", lambda: True)
    monkeypatch.setattr(g, "chat", bad)
    m = mutate_strategy(base, 1)
    assert m.steps[0].args == base.steps[0].args
