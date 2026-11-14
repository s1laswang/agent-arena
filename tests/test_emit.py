import json
from train.eval import emit

def test_emit(tmp_path):
    emit([{"reward": 1, "harm": False, "false_quarantine": False, "day_id": 1000, "trial": 0}], tmp_path, "Q+run3c+abc", "finance_ap")
    d = json.load(open(tmp_path / "frontier/Q+run3c/abc/finance_ap-s1000-t0.json"))
    assert d["model"] == "Q+run3c" and d["commit"] == "abc" and d["scores"]["reward"] == 1 and d["seed"] == 1000
