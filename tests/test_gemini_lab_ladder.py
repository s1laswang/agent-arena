"""Gemini Ladder: grid expansion, sharding, resume/skip, infra re-queue, output format (keyless, stub backend)."""
import json

import pytest

from canary.analysis.gap import load_runs
from canary.gemini import ladder
from canary.gemini.ledger import LedgeredClient
from canary.llm.stub import StubClient


def stub_factory(script_fn):
    def f(cell, run_id, meta):
        return LedgeredClient(StubClient(script=script_fn(cell)), feature="ladder", run_id=run_id, meta=meta)
    return f


def accuse_script(cell):
    return [{"tool_calls": [{"name": "status", "args": {}}]},
            {"tool_calls": [{"name": "accuse", "args": {"employee": "e01"}}]}]


def test_grid_expansion_overrides_and_order():
    cells = ladder.expand_grid(["gemini-3.8-flash", "gemini-4-carbon"], ["low", "high"], ["medium", "hard"],
                               [0, 1, 2], seeds_for=ladder.parse_overrides(["gemini-4=0-1"]),
                               levels_for=ladder.parse_overrides(["gemini-3.8-flash=low|medium|high"]))
    assert len(cells) == 3 * 2 * 3 + 2 * 2 * 2
    assert len(set(cells)) == len(cells)
    assert cells[0].model == "gemini-4-carbon" and cells[0].level == "high" and cells[0].tier == "hard"
    assert {c.level for c in cells if c.model == "gemini-3.8-flash"} == {"low", "medium", "high"}
    assert {c.seed for c in cells if c.model == "gemini-4-carbon"} == {0, 1}
    assert cells == ladder.expand_grid(["gemini-3.8-flash", "gemini-4-carbon"], ["low", "high"], ["medium", "hard"],
                                       [0, 1, 2], ladder.parse_overrides(["gemini-4=0-1"]),
                                       ladder.parse_overrides(["gemini-3.8-flash=low|medium|high"]))


def test_refuses_judge_and_heldout_seeds_and_bad_levels():
    for bad in (900000, 800005, 10_000):
        with pytest.raises(ValueError):
            ladder.expand_grid(["m"], ["low"], ["medium"], [bad])
    with pytest.raises(ValueError):
        ladder.expand_grid(["m"], ["ultra"], ["medium"], [0])


def test_shards_are_disjoint_and_cover():
    cells = ladder.expand_grid(["a", "b"], ["low", "high"], ["medium", "hard"], list(range(5)))
    parts = [ladder.shard(cells, f"{i}/3") for i in range(3)]
    flat = [c for p in parts for c in p]
    assert sorted(flat, key=str) == sorted(cells, key=str) and len(flat) == len(set(flat))
    with pytest.raises(ValueError):
        ladder.shard(cells, "3/3")


def test_run_resume_and_report_format(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    cells = ladder.expand_grid(["gemini-3.8-flash"], ["low", "high"], ["medium"], [0, 1])
    r = ladder.run_grid(tmp_path / "out", cells, concurrency=2, client_factory=stub_factory(accuse_script),
                        log=lambda m: None)
    assert r["done"] == 4 and r["ran"] == 4
    c = cells[0]
    d = c.dir(tmp_path / "out")
    ep = json.loads((d / "episodes.jsonl").read_text())
    assert ep["end_reason"] == "accused" and ep["meta"]["ladder"]["thinking_level"] == c.level
    assert ep["meta"]["ladder"]["model"] == "gemini-3.8-flash" and ep["meta"]["ladder"]["tokens"]["calls"] == 2
    meta = json.loads((d / "meta.json").read_text())
    assert meta["thinking_level"] == c.level and meta["agent"] == "gemini:gemini-3.8-flash"
    assert (d / "transcripts" / f"{c.seed}.json").exists() and not (d / "RUNNING.json").exists()
    rows = [json.loads(x) for x in (tmp_path / "ledger.jsonl").read_text().splitlines()]
    assert len(rows) == 8 and all(x["feature"] == "ladder" and x["run_id"].startswith("ladder:") for x in rows)
    # data/runs format: canary.analysis.gap.load_runs reads every cell
    assert len(load_runs(tmp_path / "out")) == 4
    # resume: nothing left to run
    r2 = ladder.run_grid(tmp_path / "out", cells, concurrency=2, client_factory=stub_factory(accuse_script),
                         log=lambda m: None)
    assert r2["ran"] == 0 and r2["done"] == 4


def test_infra_failure_is_moved_aside_and_requeued(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    monkeypatch.setattr(ladder.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky(cell):
        calls["n"] += 1
        if calls["n"] == 1:
            return [RuntimeError("500 INTERNAL ServerError")]
        return accuse_script(cell)

    cells = ladder.expand_grid(["gemini-3.5-flash"], ["minimal"], ["medium"], [3])
    r = ladder.run_grid(tmp_path / "out", cells, concurrency=1, client_factory=stub_factory(flaky),
                        log=lambda m: None)
    assert r["done"] == 1
    inv = list((tmp_path / "out" / "_invalid").iterdir())
    assert len(inv) == 1 and "api:" in (inv[0] / "INVALID.txt").read_text()
    assert ladder.attempts(tmp_path / "out", cells[0]) == 1
    prog = [json.loads(x) for x in (tmp_path / "out" / "_progress.jsonl").read_text().splitlines()]
    assert [bool(p["infra_invalid"]) for p in prog] == [True, False]
