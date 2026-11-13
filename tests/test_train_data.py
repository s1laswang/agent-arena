import json, glob, pytest
from train.build_data import build, examples
from train.window import prompt, SYSTEM

def step(i, seat="controller", tool="close_ticket", rnd=0):
    return {"i": i, "tick": i, "seat": seat, "view": {"round": rnd, "seat": seat, "tick": i}, "tool": tool, "args": {"id": f"T{i}"}, "ok": True, "effect": {"ok": True, "n": i}}

def day(did, reward=1, n=2):
    return {"result": {"reward": reward}, "day": {"day_id": did, "sleeper_seat": "hr"}, "steps": [step(i) for i in range(n)] + [step(n, "controller", "end_turn"), step(n + 1, "hr")]}

def test_filters(tmp_path):
    d = tmp_path / "r" / "days"
    d.mkdir(parents=True)
    for s, r in [(5, 1), (6, 0), (500, 1), (1001, 1)]:
        (d / f"{s}-t0.json").write_text(json.dumps(day(s, r)))
    assert build(tmp_path / "r", tmp_path / "o") == {"train": 2, "val": 2}
    row = json.loads((tmp_path / "o" / "train.jsonl").read_text().splitlines()[0])
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]

def replay(d, seat):
    from train.policy import LocalSeat
    class P:
        def __init__(s): s.out = []
        def act(s, system, st, hist, header):
            s.out.append(prompt(system, st, hist, header)); return {"tool": s.steps[len(s.out) - 1]["tool"], "args": s.steps[len(s.out) - 1]["args"]}
    p = P()
    p.steps = [x for x in d["steps"] if x["seat"] == seat]
    L = LocalSeat(p, SYSTEM)
    it = iter(p.steps)
    def call(name, args):
        return next(e for e in [p.steps[len(L.hist)]])["effect"]
    for rnd in sorted({x["view"]["round"] for x in p.steps}):
        view = next(x["view"] for x in p.steps if x["view"]["round"] == rnd)
        L.turn(seat, view, [], call)
    return p.out

def test_replay_matches_build():
    d = day(1, n=10)
    rows = examples(d, ["controller"])
    got = replay(d, "controller")
    assert [r["messages"][:-1] for r in rows] == got

def test_real_dump_matches():
    fs = glob.glob("/private/tmp/**/oracle-all-*/days/*-t0.json", recursive=True)
    if not fs:
        pytest.skip("no dump")
    d = json.load(open(fs[0]))
    rows = examples(d, ["controller"])
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
