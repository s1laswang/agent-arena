import json
import os

from scripts import frontier_replay

F = os.path.join(os.path.dirname(__file__), "fixtures", "frontier_replay.json")


def test_replay_matches():
    assert frontier_replay.check(F) == {}


def test_replay_detects_tamper(tmp_path):
    rec = json.load(open(F))
    rec["scores"]["reward"] = 0.123
    p = tmp_path / "x.json"
    p.write_text(json.dumps(rec))
    assert "reward" in frontier_replay.check(str(p))
