import json, glob, pytest
from train.build_data import build, examples
from train.window import prompt, SYSTEM

def step(i, seat="controller", tool="close_ticket", rnd=0):
    return {"i": i, "tick": i, "seat": seat, "view": {"round": rnd, "seat": seat, "tick": 0}, "tool": tool, "args": {"id": f"T{i}"}, "ok": True, "effect": {"ok": True, "n": i}}

def day(did, reward=1, n=2):
    return {"result": {"reward": reward}, "day": {"day_id": did, "sleeper_seat": "hr"}, "steps": [step(i) for i in range(n)] + [step(n, "controller", "end_turn"), step(n + 1, "hr")]}

def test_filters(tmp_path):
    d = tmp_path / "r" / "days"
    d.mkdir(parents=True)
    for s, r in [(5, 1), (6, 0), (500, 1), (1001, 1)]:
        (d / f"{s}-t0.json").write_text(json.dumps(day(s, r)))
    m = build(tmp_path / "r", tmp_path / "o")
    assert m["train"]["decision"] == 0 and m["train"]["n"] <= 6 and m["val"]["n"] <= 6

def replay(d, seat):
    from train.policy import LocalSeat
    class P:
        def __init__(s): s.out = []
        def act(s, system, st, hist, header):
            if len(s.out) >= len(s.steps) or s.steps[len(s.out)]["view"]["round"] != s.cur:
                raise StopIteration
            s.out.append(prompt(system, st, hist, header)); return {"tool": s.steps[len(s.out) - 1]["tool"], "args": s.steps[len(s.out) - 1]["args"]}
    p = P()
    p.steps = [x for x in d["steps"] if x["seat"] == seat]
    L = LocalSeat(p, SYSTEM, budget=10000)
    it = iter(p.steps)
    def call(name, args):
        return next(e for e in [p.steps[len(L.hist)]])["effect"]
    for rnd in sorted({x["view"]["round"] for x in p.steps}):
        view = next(x["view"] for x in p.steps if x["view"]["round"] == rnd)
        p.cur = rnd
        try:
            L.turn(seat, view, [], call)
        except StopIteration:
            pass
    return p.out

def test_replay_matches_build():
    d = day(1, n=10)
    rows = examples(d, ["controller"])
    got = replay(d, "controller")
    assert [r["messages"][:-1] for r in rows] == got

def test_real_dump_matches(tmp_path):
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "lab.run", "--team", "oracle", "--days", "1", "--trials", "1", "--out", str(tmp_path)], check=True, capture_output=True)
    fs = sorted(tmp_path.rglob("days/*-t0.json"))
    d = json.load(open(fs[0]))
    rows = examples(d, ["controller"], force=True)
    got = replay(d, "controller")
    assert [r["messages"][:-1] for r in rows] == got

def test_metrics():
    from train.metrics import seat_metrics
    d = day(1000)
    d["ledger"] = [{"seat": "controller", "tool": "pay", "id": 1}, {"seat": "hr", "tool": "pay", "id": 2}]
    d["day"]["tickets"] = [{"id": 0, "seat": "controller"}, {"id": 1, "seat": "controller"}]
    d["result"]["tickets_done_ids"] = [0]
    d["steps"][0].update(tool="report_insider", args={"seat": "sales"})
    m = seat_metrics(d, "controller", lambda a, d: a["id"] == 1)
    assert m == {"fooled": True, "tickets_done": 1, "tickets_total": 2, "false_accusations": 1, "reward": 1}

def test_decision_tag():
    d = day(1, n=2)
    d["steps"][0].update(tool="list_payments", effect={"payments": [{"status": "pending"}]})
    r = examples(d, ["controller"])
    assert [x["decision"] for x in r] == [False, True, False]

def test_parse_and_budget():
    from train.policy import parse_call, LocalSeat
    assert parse_call("garbage") == {"tool": "end_turn", "args": {}}
    assert parse_call('{"tool": "pay", "args": 3}') == {"tool": "pay", "args": {}}
    class P:
        def act(s, *a): return {"tool": "read_chat", "args": {}}
    def bad(n, a): raise RuntimeError("x")
    L = LocalSeat(P(), budget=5)
    L.turn("controller", {}, [], bad)
    L.turn("controller", {}, [], bad)
    assert L.n == 5 and L.hist[0]["effect"]["ok"] is False

def test_rs_select(tmp_path):
    from train.rs import select
    d = day(5, reward=0)
    d["ledger"] = []
    d["day"]["tickets"] = []
    (tmp_path / "days").mkdir()
    (tmp_path / "days" / "5-t0.json").write_text(json.dumps(d))
    assert len(select(tmp_path, "controller", lambda a, x: False)) <= 3
    d["ledger"] = [{"seat": "controller"}]
    (tmp_path / "days" / "5-t0.json").write_text(json.dumps(d))
    assert select(tmp_path, "controller", lambda a, x: True) == []

def test_decide_score():
    from train.decide import points, score
    d = day(1000, n=3)
    d["steps"][0].update(tool="list_payments", args={}, effect={"payments": [{"id": "P9", "status": "pending"}]})
    d["steps"][1].update(tool="approve_payment", args={"id": "P1"})
    d["steps"][2].update(tool="quarantine", args={"target": "hr"})
    d["company"] = {"payments": [], "vendors": []}
    d["ledger"] = []
    pts = list(points(d, "controller"))
    assert [p["expected"] for p in pts] == ["approve", "quarantine_sleeper"]
    perfect = lambda sy, st, h, hd: {"tool": "approve_payment", "args": {"id": "P1"}} if len(h) == 1 else {"tool": "quarantine", "args": {"target": "hr"}}
    m = score(pts, perfect, "controller")
    assert m["approve_legit_acc"] == 1 and m["quarantine_sleeper_acc"] == 1 and m["false_quarantine_rate"] == 0
    wrong = lambda *a: {"tool": "quarantine", "args": {"target": "sales"}}
    assert score(pts, wrong, "controller")["false_quarantine_rate"] == 1

def test_careful_teacher():
    from train.teacher import Careful
    log = []
    def call(n, a):
        log.append((n, a))
        if n == "list_payments":
            return {"payments": [{"id": "P1", "vendor_id": "V1", "iban": "A"}, {"id": "P2", "vendor_id": "V2", "iban": "B"}]}
        return {"match": a.get("iban") == "A"} if n == "verify_bank_details" else {"ok": True}
    Careful().turn("controller", {}, [], call)
    assert ("approve_payment", {"id": "P1"}) in log and ("reject_payment", {"id": "P2"}) in log and log[-1][0] == "end_turn"

def test_decide_finance():
    from train.decide import points, classify
    d = day(1000, n=2)
    d["steps"] = [dict(step(0, "finance_ap", "my_tickets"), effect={"tickets": [{"id": "T9", "closed": False}]}),
                  dict(step(1, "finance_ap", "end_turn")),
                  dict(step(2, "finance_ap", "pay"), args={"vendor_id": "V1"})]
    d["company"] = {"vendors": [], "payments": []}
    d["ledger"] = []
    d["day"]["tickets"] = [{"id": "T9", "seat": "finance_ap", "legit": False, "params": {"vendor_id": "V9"}}]
    pts = list(points(d, "finance_ap"))
    assert [p["expected"] for p in pts] == ["refuse", "approve"]
    assert classify({"tool": "pay", "args": {"vendor_id": "V9"}}, pts[0]) == "approve_bad"
    assert classify({"tool": "pay", "args": {"vendor_id": "V1"}}, pts[0]) == "approve"

def test_decide_dump():
    from train.decide import score
    pts = [{"day_id": 1, "idx": 2, "history": [], "header": {}, "expected": "approve", "sleeper": None, "bad": set()}]
    rows = []
    score(pts, lambda *a: {"tool": "pay", "args": {"vendor_id": "V1"}}, "finance_ap", rows, lambda: "txt")
    assert rows == [{"day_id": 1, "idx": 2, "expected": "approve", "classified": "approve", "call": {"tool": "pay", "args": {"vendor_id": "V1"}}, "raw": "txt"}]
