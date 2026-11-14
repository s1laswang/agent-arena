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
        (d / who).mkdir()
        for sd in range(4):
            for t in range(3):
                (d / who / (("reference-" if who == "reference" else "") + f"finance_ap-s{sd}-t{t}.json")).write_text(json.dumps({"model": who, "commit": "abc", "agent": "gemini", "day_source": "day_for", "sleeper": "scripted", "team": "staff_scripted", "bg_version": "x", "invalid": who != "reference" and t == 1 and sd == 0, "role": "reference" if who == "reference" else None, "seat": "finance_ap", "seed": sd, "trial": t, "mode": "seat", "capped": who != "reference" and t == 0, "scores": {"reward": rw, "harm": False, "false_quarantines": []}}))
    rows = gaptable.main([str(tmp_path), "--also", str(tmp_path / "none"), "--out", str(tmp_path)])
    r = next(x for x in rows if x["row"] == "Gemini 3.1 Pro")
    assert r["invalid"] == 1 and r["capped"] == 4 and r["unverified"] and r["paired"] is None and r["agent"] == "gemini"


def test_unknown_day_source_excluded(tmp_path):
    d = tmp_path / "m" / "abc"
    d.mkdir(parents=True)
    for t in range(3):
        (d / f"finance_ap-s1-t{t}.json").write_text(json.dumps({"model": "codex", "commit": "abc", "agent": "codex", "seat": "finance_ap", "seed": 1, "trial": t, "mode": "seat", "scores": {"reward": 1, "harm": False, "false_quarantines": []}}))
    rows = gaptable.main([str(tmp_path), "--also", str(tmp_path / "none"), "--out", str(tmp_path)])
    r = next(x for x in rows if x["row"] == "Codex")
    assert r["day_source"] == "unknown" and r["paired"] is None and r["gap_ref"] is None


def test_verify_refuses(tmp_path):
    d = tmp_path / "m" / "abc"
    d.mkdir(parents=True)
    (d / "finance_ap-s1-t0.json").write_text(json.dumps({"model": "codex", "commit": "abc", "agent": "codex", "day_source": "day_for", "sleeper": "scripted", "team": "staff_scripted", "bg_version": "x", "seat": "finance_ap", "seed": 1, "trial": 0, "mode": "seat", "scores": {"reward": 1, "harm": False, "false_quarantines": []}}))
    rows = gaptable.main([str(tmp_path), "--also", str(tmp_path / "none"), "--out", str(tmp_path)])
    r = next(x for x in rows if x["row"] == "Codex")
    assert r["verified"] is None


def test_winnable_exclusion(tmp_path):
    d = tmp_path / "m" / "abc"
    d.mkdir(parents=True)
    for who, ag in (("oracle", "scripted"), ("codex", "codex")):
        for sd in (1, 2):
            (d / f"{who}-s{sd}-t0.json").write_text(json.dumps({"model": who, "commit": "abc", "agent": ag, "day_source": "day_for", "sleeper": "scripted", "team": "procedure", "bg_version": "9fa41d4", "seat": "finance_ap", "seed": sd, "trial": 0, "mode": "seat", "scores": {"reward": 0 if who == "oracle" and sd == 1 else 1, "harm": False, "false_quarantines": []}}))
    rows = gaptable.main([str(tmp_path), "--also", str(tmp_path / "none"), "--replay", "--out", str(tmp_path)])
    r = next(x for x in rows if x["row"] == "Codex")
    assert r["excluded_seeds"] == ["1"] and r["n_excluded"] == 1 and r["n_days"] == 1 and r["unverified"] and not r["headline"]


def test_check_fails_on_missing_cache():
    import pytest

    row = {"row": "X", "mode": "m", "provenance": "real", "agent": "claude", "cache": "/nonexistent"}
    with pytest.raises(SystemExit):
        gaptable.check([row])
    with pytest.raises(SystemExit):
        gaptable.check([{**row, "provenance": "fake"}])
    gaptable.check([{**row, "cache": "."}, {"row": "Y", "status": "pending"}])


def test_pair_verdict():
    mk = lambda n, ps: {"row": n, "mode": "m", "day_source": "d", "sleeper": "s", "team": "t", "bg_version": "v", "per_seed": ps}
    rows = gaptable.pair([mk("fair reference", {str(i): 1.0 for i in range(6)}), mk("Codex", {str(i): 0.0 for i in range(6)}), mk("staff", {str(i): 0.5 for i in range(6)})])
    x = next(r for r in rows if r["row"] == "Codex")
    assert x["paired"]["verdict"] == "significant" and x["luck_adj"] == -0.5


def test_run_file_regex(tmp_path):
    run = {"model": "codex", "seed": 1, "scores": {"reward": 1}}
    for n in ("finance_ap-s1-t0.json", "reference-finance_ap-s1-t0.json", "all8-s1-t0.json"):
        (tmp_path / n).write_text(json.dumps(run))
    for n in ("summary-codex.json", "summary.json", "finance_ap-s1-t0.state.json.gz", "x.json"):
        (tmp_path / n).write_text(json.dumps(run))
    assert sorted(x["_path"].split("/")[-1] for x in gaptable.run_files(str(tmp_path))) == ["all8-s1-t0.json", "finance_ap-s1-t0.json", "reference-finance_ap-s1-t0.json"]
