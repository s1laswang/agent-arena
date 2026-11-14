import glob
import json
import os

import pytest

from lab import run as labrun

SCRIPTED = "scripted"


def check_run(d):
    s = json.load(open(os.path.join(d, "summary.json")))
    rows = [json.loads(x) for x in open(os.path.join(d, "days.jsonl"))]
    bad = []
    kinds = {s.get("agent_kind")} | {r.get("agent_kind") for r in rows}
    models = {s.get("model")} | {r.get("model") for r in rows}
    if None in kinds or None in models:
        bad.append("missing agent_kind or model")
    if SCRIPTED in kinds and (len(kinds) > 1 or models != {SCRIPTED}):
        bad.append("scripted mixed with real labels")
    if SCRIPTED not in kinds and kinds != {None}:
        if not s.get("run_id"):
            bad.append("real without run_id")
        if SCRIPTED in models or not all(models):
            bad.append("real without model id")
        u = s.get("gemini_usage") or {}
        if kinds == {"gemini"} and u.get("calls", 0) + u.get("cache_hits", 0) < 1:
            bad.append("real without a model call")
        for r in rows:
            if not r.get("transcript_path") or not os.path.exists(os.path.join(d, r["transcript_path"])):
                bad.append("real without transcript")
                break
            t = json.load(open(os.path.join(d, r["transcript_path"])))
            if not t.get("steps") and not t.get("ledger"):
                bad.append("empty transcript")
                break
    return bad


def test_scripted_never_real(tmp_path):
    for team in ("oracle", "do_nothing", "stop_early"):
        d, s = labrun.run(team, 1, 1, out=str(tmp_path))
        assert (s["agent_kind"], s["model"]) == (SCRIPTED, SCRIPTED)
        assert check_run(d) == []


def test_scripted_factories_never_gemini(monkeypatch):
    monkeypatch.setenv("LAB_GEMINI", "1")
    for n, (_, k) in labrun.FACTORIES.items():
        if k == SCRIPTED:
            assert labrun.agent_kind(n) == SCRIPTED and labrun.agent_model(n) == SCRIPTED


def test_missing_or_fake_provenance_fails(tmp_path):
    d, _ = labrun.run("oracle", 1, 1, out=str(tmp_path))
    sp = os.path.join(d, "summary.json")
    s = json.load(open(sp))
    rows = [json.loads(x) for x in open(os.path.join(d, "days.jsonl"))]

    def write(s2, rows2):
        json.dump(s2, open(sp, "w"))
        open(os.path.join(d, "days.jsonl"), "w").write("".join(json.dumps(r) + "\n" for r in rows2))
        return check_run(d)

    assert write({**s, "agent_kind": "gemini", "model": "gemini-4-carbon"}, [{**r, "agent_kind": "gemini", "model": "gemini-4-carbon"} for r in rows])
    assert write({**s, "agent_kind": "gemini", "model": SCRIPTED, "gemini_usage": {"calls": 3}}, [{**r, "agent_kind": "gemini", "model": SCRIPTED} for r in rows])
    assert write({k: v for k, v in s.items() if k != "model"}, rows)
    assert write({**s, "agent_kind": "gemini", "model": "m", "gemini_usage": {"calls": 3}, "run_id": ""}, [{**r, "agent_kind": "gemini", "model": "m"} for r in rows])
    assert write({**s, "agent_kind": "gemini", "model": "m", "gemini_usage": {"calls": 3}}, [{**r, "agent_kind": "gemini", "model": "m", "transcript_path": "nope.json"} for r in rows])
    ok = write({**s, "agent_kind": "gemini", "model": "m", "gemini_usage": {"calls": 3}}, [{**r, "agent_kind": "gemini", "model": "m"} for r in rows])
    assert ok == []


def test_committed_runs_labelled():
    for sp in glob.glob("results/**/summary.json", recursive=True):
        d = os.path.dirname(sp)
        if os.path.exists(os.path.join(d, "days.jsonl")):
            assert check_run(d) == [], d


def _rows(t):
    return t if isinstance(t, list) else t.get("rows", [])


def test_frontier_provenance():
    gp = "web/results/frontier/gaptable.json"
    if not os.path.exists(gp):
        pytest.skip("no frontier results yet")
    for row in _rows(json.load(open(gp))):
        if row.get("status") == "pending":
            continue
        prov, model, commit = row.get("provenance"), row.get("model"), row.get("commit")
        assert prov in ("real", SCRIPTED), f"row has no valid provenance: {row}"
        if prov == "real":
            assert model and commit and model != SCRIPTED, row
            assert row.get("agent", "x") != SCRIPTED, row
            files = [json.load(open(f)) for f in glob.glob(f"results/frontier/{model}/{commit}/*.json")]
            assert files, row
            assert all(f.get("agent") not in (None, SCRIPTED) and f.get("model") == model and f.get("commit") == commit for f in files), row
        elif row.get("agent") not in (None, SCRIPTED):
            raise AssertionError(f"non-scripted agent labeled scripted: {row}")
    for f in glob.glob("results/frontier/*/*/*.json"):
        r = json.load(open(f))
        if r.get("agent") == SCRIPTED:
            assert r.get("provenance", SCRIPTED) == SCRIPTED, f


@pytest.mark.xfail(reason="real per-run files lack mcp_calls until lead-lab backfills", strict=False)
def test_real_rows_have_mcp_calls():
    gp = "web/results/frontier/gaptable.json"
    if not os.path.exists(gp):
        pytest.skip("no frontier results yet")
    for row in _rows(json.load(open(gp))):
        if row.get("provenance") == "real":
            files = [json.load(open(f)) for f in glob.glob(f"results/frontier/{row['model']}/{row['commit']}/*.json")]
            assert any(f.get("mcp_calls") for f in files), row
@pytest.mark.slow
def test_eval_without_gemini_flag_makes_no_calls(tmp_path, monkeypatch):
    from agents import gemini
    from lab import eval as labeval

    def boom(*a, **k):
        raise AssertionError("live Gemini call without --gemini")

    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("LAB_GEMINI", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    monkeypatch.setattr(gemini, "_generate", boom)
    monkeypatch.setattr(gemini, "_get_client", boom)
    before = gemini._usage["calls"]
    labeval.main(["--days", "1", "--trials", "1", "--exploit-days", "1", "--out", str(tmp_path), "--web-out", str(tmp_path / "w"), "--no-report"])
    assert gemini._usage["calls"] == before


def _perrun():
    return [f for f in glob.glob("results/frontier/*/*/*-s*.json") if "/summary-" not in f]


def test_perrun_frontier_files():
    fs = _perrun()
    if not fs:
        pytest.skip("no per-run frontier files")
    for f in fs:
        r = json.load(open(f))
        if r.get("agent") == SCRIPTED:
            assert r.get("provenance", SCRIPTED) == SCRIPTED, f
            continue
        assert r.get("agent") and r.get("model") and r.get("commit"), f
        assert r["transcript"], f
        assert r.get("provenance", "real") == "real", f


@pytest.mark.xfail(reason="per-run files lack mcp_calls and provenance, asked lead-lab", strict=False)
def test_perrun_real_has_mcp_calls_and_provenance():
    fs = [json.load(open(f)) for f in _perrun()]
    fs = [r for r in fs if r.get("agent") not in (None, SCRIPTED)]
    if not fs:
        pytest.skip("no real per-run files")
    for r in fs:
        assert r.get("provenance") == "real" and r.get("mcp_calls"), r.get("seed")
