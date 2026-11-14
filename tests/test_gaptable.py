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


def test_paired_capped(tmp_path):
    d = tmp_path / "m" / "abc"
    d.mkdir(parents=True)
    for who, rw in (("reference", 1), ("gemini-3.1-pro-preview", 0)):
        for sd in range(4):
            for t in range(3):
                (d / f"{who}-s{sd}-t{t}.json").write_text(json.dumps({"model": who, "commit": "abc", "agent": "gemini", "role": "reference" if who == "reference" else None, "seat": "finance_ap", "seed": sd, "trial": t, "mode": "seat", "capped": who != "reference" and t == 0, "scores": {"reward": rw, "harm": False, "false_quarantines": []}}))
    rows = gaptable.main([str(tmp_path), "--also", str(tmp_path / "none"), "--out", str(tmp_path)])
    r = next(x for x in rows if x["row"] == "Gemini 3.1 Pro")
    assert r["capped"] == 4 and r["paired"]["verdict"] == "significant" and r["agent"] == "gemini"
