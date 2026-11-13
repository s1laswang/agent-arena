import json
from train.build_data import build, examples

def day(seed, reward=1):
    return {"seed": seed, "reward": reward, "sleeper_seat": "hr", "steps": [
        {"seat": "controller", "obs": "ticket 1", "tool": "close_ticket", "args": {"id": 1}},
        {"seat": "hr", "obs": "x", "tool": "read_chat", "args": {}}]}

def test_filters(tmp_path):
    d = tmp_path / "r" / "days"
    d.mkdir(parents=True)
    for i, (s, r) in enumerate([(5, 1), (6, 0), (500, 1), (1001, 1)]):
        (d / f"{i}.json").write_text(json.dumps(day(s, r)))
    n = build(tmp_path / "r", tmp_path / "o")
    assert n == {"train": 1, "val": 1}
    row = json.loads((tmp_path / "o" / "train.jsonl").read_text())
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    assert json.loads(row["messages"][2]["content"])["tool"] == "close_ticket"
    assert len(examples(day(1))) == 1

def test_window_matches_inference():
    from train.build_data import system_for
    from train.window import prompt
    steps = [{"seat": "controller", "obs": f"o{i}", "tool": "read_chat", "args": {}} for i in range(10)]
    d = {"seed": 1, "reward": 1, "steps": steps}
    rows = examples(d)
    assert len(rows) == 10
    for i, r in enumerate(rows):
        want = prompt(system_for(steps[i]), "controller", steps[:i], steps[i]["obs"])
        assert r["messages"][:-1] == want
    assert len(rows[9]["messages"]) == 2 + 2 * 6 + 1
