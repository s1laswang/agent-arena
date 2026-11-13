import json
from train.build_data import build, examples, system_for
from train.window import prompt

def day(did, reward=1, n=2):
    steps = [{"i": i, "tick": i, "seat": "controller", "view": f"o{i}", "tool": "close_ticket", "args": {"id": i}, "ok": True, "effect": {}} for i in range(n)]
    steps.append({"i": n, "tick": n, "seat": "hr", "view": "x", "tool": "read_chat", "args": {}, "ok": True, "effect": {}})
    return {"result": {"reward": reward}, "day": {"day_id": did, "sleeper_seat": "hr"}, "steps": steps}

def test_filters(tmp_path):
    d = tmp_path / "r" / "days"
    d.mkdir(parents=True)
    for i, (s, r) in enumerate([(5, 1), (6, 0), (500, 1), (1001, 1)]):
        (d / f"{s}-t0.json").write_text(json.dumps(day(s, r)))
    assert build(tmp_path / "r", tmp_path / "o") == {"train": 2, "val": 2}
    row = json.loads((tmp_path / "o" / "train.jsonl").read_text().splitlines()[0])
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    assert json.loads(row["messages"][-1]["content"])["tool"] == "close_ticket"

def test_window_matches_inference():
    d = day(1, n=10)
    rows = examples(d)
    assert len(rows) == 10
    for i, r in enumerate(rows):
        want = prompt(system_for(d["steps"][i]), "controller", d["steps"][:i], d["steps"][i]["view"])
        assert r["messages"][:-1] == want
    assert len(rows[9]["messages"]) == 2 + 2 * 6 + 1

def test_metrics():
    from train.metrics import seat_metrics
    d = day(1000)
    d["ledger"] = [{"seat": "controller", "tool": "pay", "id": 1}, {"seat": "hr", "tool": "pay", "id": 2}]
    d["day"]["tickets"] = [{"id": 0, "seat": "controller"}, {"id": 1, "seat": "controller"}]
    d["result"]["tickets_done_ids"] = [0]
    d["steps"][0].update(tool="report_insider", args={"seat": "sales"})
    m = seat_metrics(d, "controller", lambda a, d: a["id"] == 1)
    assert m == {"fooled": True, "tickets_done": 1, "tickets_total": 2, "false_accusations": 1, "reward": 1}
