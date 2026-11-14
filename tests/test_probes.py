import json

import pytest

from scripts import probes


@pytest.fixture(scope="module")
def rows():
    return probes.table()


def test_every_probe_zero_and_control_one(rows):
    for r in rows:
        want = 1.0 if r["probe"] == "control_pad" else 0.0
        assert (r["probe"], r["seat"]["reward_mean"], r["team"]["reward_mean"]) == (r["probe"], want, want)


def test_replay_rescore_matches_and_detects_tamper(tmp_path):
    from lab import run

    res, x = run.play_day("oracle", "oracle", "finance_ap", 1000, 0)
    res["seat_under_test"] = "finance_ap"
    d = tmp_path / "r" / "days"
    d.mkdir(parents=True)
    f = d / "1000-t0.json"
    f.write_text(json.dumps({**x, "result": res}))
    assert probes.replay(str(tmp_path))[:2] == (1, 0)
    res["reward"] = 1 - res["reward"]
    f.write_text(json.dumps({**x, "result": res}))
    assert probes.replay(str(tmp_path))[:2] == (1, 1)
