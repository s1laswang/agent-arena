import importlib.util, json
from pathlib import Path

spec = importlib.util.spec_from_file_location("gvr", Path(__file__).resolve().parent.parent / "scripts/gap_vs_reference.py")
gvr = importlib.util.module_from_spec(spec); spec.loader.exec_module(gvr)


def test_bootstrap_deterministic_and_sane():
    a = [0.5, 0.6, 0.2, 0.9, 0.4]; b = [0.5, 0.5, 0.5, 0.5, 0.5]
    r1, r2 = gvr.paired_bootstrap(a, b, n_boot=2000), gvr.paired_bootstrap(a, b, n_boot=2000)
    assert r1 == r2
    assert abs(r1["ratio"] - 1.04) < 1e-9 and abs(r1["diff"] - 0.02) < 1e-9
    assert r1["ratio_ci"][0] <= r1["ratio"] <= r1["ratio_ci"][1]
    assert r1["diff_ci"][0] <= r1["diff"] <= r1["diff_ci"][1]
    same = gvr.paired_bootstrap(b, b, n_boot=500)
    assert same["ratio_ci"] == [1.0, 1.0] and same["diff_ci"] == [0.0, 0.0]


def test_pairing_drops_invalid_last_wins_and_judge_seeds(tmp_path):
    f1, f2 = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    f1.write_text("\n".join(json.dumps(e) for e in [
        {"tier": "hard", "seed": 1, "score": 0.1},
        {"tier": "hard", "seed": 2, "score": 0.3, "valid": False},
        {"tier": "hard", "seed": 3, "score": None},
        {"tier": "hard", "seed": 900001, "score": 0.9},
        {"tier": "medium", "seed": 1, "score": 0.4, "end_reason": "error"}]) + "\nnot json\n")
    f2.write_text(json.dumps({"tier": "hard", "seed": 1, "score": 0.7}) + "\n")
    g, inv = gvr.collect([str(f1), str(f2)])
    assert inv == 3 and g[("hard", 1)]["score"] == 0.7
    assert gvr.pair_keys(g, "hard") == [("hard", 1)]
    assert gvr.pair_keys(g, "medium") == []


def test_dedup_newest_and_order_independent(tmp_path):
    import os
    old, new = tmp_path / "old" / "episodes.jsonl", tmp_path / "new" / "episodes.jsonl"
    for p, sc in ((old, 0.1), (new, 0.8)):
        p.parent.mkdir()
        p.write_text(json.dumps({"agent": "g", "tier": "hard", "seed": 5, "score": sc}) + "\n")
    (old.parent / "meta.json").write_text(json.dumps({"timestamp": "2026-11-14T10:00:00+0000"}))
    os.utime(new, (2e9, 2e9))  # no meta timestamp -> mtime fallback (newer)
    for order in ([str(old), str(new)], [str(new), str(old)]):
        g, _ = gvr.collect(order)
        assert g[("hard", 5)]["score"] == 0.8
        assert [x["score"] for x in gvr.collect.duplicates[("hard", 5)]] == [0.1]
