import pytest

from lab import frontier_cli as frontier
from lab.eval import main

calls = []


def fake(agent, model, seat, seed, days, caps):
    calls.append((agent, model, seed, caps))
    return {"score": 0.5}


def test_cache_replay_and_caps(tmp_path):
    out = str(tmp_path)
    a = frontier.run_frontier("claude", "m1", "finance_ap", [1], 1, out=out, run_seat=fake)
    assert a["live_runs"] == 1 and a["rows"][0]["mode"] == "live" and a["reward_mean"] == 0.5 and a["commit"]
    b = frontier.run_frontier("claude", "m1", "finance_ap", [1], 1, out=out, run_seat=fake)
    assert b["live_runs"] == 0 and b["rows"][0]["mode"] == "replay" and len(calls) == 1
    c = frontier.run_frontier("claude", "m1", "finance_ap", [2], 1, out=out, run_seat=fake, max_total_seconds=-1)
    assert c["n_err"] == 1 and len(calls) == 1
    with pytest.raises(SystemExit):
        frontier.run_frontier("claude", "m1", "finance_ap", list(range(6)), 1, out=out, run_seat=fake)


def test_eval_flag(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(frontier.__file__).rsplit("/lab", 1)[0])
    s = main(["--agent", "codex", "--model", "gpt-x", "--no-report"], runner=fake)
    assert s["live_runs"] == 1 and s["days"] == [1000]
