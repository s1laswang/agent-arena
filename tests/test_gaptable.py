import json

from lab import gaptable


def test_real_rows_and_replay(tmp_path):
    d = tmp_path / "m" / "abc"
    d.mkdir(parents=True)
    for t in range(3):
        (d / f"finance_ap-s1-t{t}.json").write_text(json.dumps({"model": "claude-opus-5-5", "commit": "abc", "agent": "claude", "seat": "finance_ap", "seed": 1, "trial": t, "mode": "seat", "scores": {"reward": 1 if t < 2 else 0, "harm": False, "false_quarantines": []}, "calls": 2}))
    rows = gaptable.main([str(tmp_path), "--also", str(tmp_path / "none"), "--replay", "--out", str(tmp_path)])
    r = next(x for x in rows if x["row"] == "Claude Opus 5.5")
    assert r["provenance"] == "real" and abs(r["pass1"] - 2 / 3) < 1e-9 and r["pass3"] == 0.0
    assert next(x for x in rows if x["row"] == "Codex")["status"] == "pending"
