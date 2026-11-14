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
