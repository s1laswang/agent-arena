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
    assert meta["tiers_version"] == "v1.4" and meta["model_id"] == "gemini-3.8-flash" and meta["launch_git_sha"]
    assert ep["meta"]["ladder"]["code_fingerprint"] == ladder.code_fingerprint()
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
    calls = {"n": 0}

    def flaky(cell):
        calls["n"] += 1
        if calls["n"] == 1:
            return [RuntimeError("500 INTERNAL ServerError")]
        return accuse_script(cell)

    cells = ladder.expand_grid(["gemini-3.5-flash"], ["minimal"], ["medium"], [3])
    r = ladder.run_grid(tmp_path / "out", cells, concurrency=1, client_factory=stub_factory(flaky),
                        log=lambda m: None, retry_delay=0.0)
    assert r["done"] == 1
    inv = list((tmp_path / "out" / "_invalid").iterdir())
    assert len(inv) == 1 and "api:" in (inv[0] / "INVALID.txt").read_text()
    assert ladder.attempts(tmp_path / "out", cells[0]) == 1
    prog = [json.loads(x) for x in (tmp_path / "out" / "_progress.jsonl").read_text().splitlines()]
    assert [bool(p["infra_invalid"]) for p in prog] == [True, False]


def test_report_reads_ladder_output(tmp_path, monkeypatch):
    from canary.gemini import ladder_report
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "out" / "_ledger" / "x.jsonl"))
    cells = ladder.expand_grid(["gemini-3.8-flash"], ["low", "medium", "high"], ["medium"], [0, 1])
    ladder.run_grid(tmp_path / "out", cells, concurrency=3, client_factory=stub_factory(accuse_script),
                    log=lambda m: None)
    rep = tmp_path / "rep"
    assert ladder_report.main(["--runs", str(tmp_path / "out"), "--out", str(rep), "--bootstrap", "200",
                               "--probe", str(tmp_path / "none.json"), "--no-figures"]) == 0
    doc = json.loads((rep / "ladder.json").read_text())
    assert {"generated_at", "git_sha", "ledger_run_ids"} <= set(doc)
    assert len(doc["rows"]) == 3 and all(r["n"] == 2 for r in doc["rows"])
    assert doc["ledger"]["calls"] == 12 and len(doc["ledger_run_ids"]) == 6
    assert any(r["agent"] == "solver" for r in doc["reference"])
    assert "low|medium" in doc["tags"]["pooled"]
    assert "gemini-3.8-flash" in (rep / "ladder.md").read_text()


def test_model_cap_never_blocks_other_models(tmp_path, monkeypatch):
    import threading
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    live, peak, lock = {"capped": 0, "all": 0}, {"capped": 0, "all": 0}, threading.Lock()
    real = ladder.run_cell

    def spy(out, c, *a, **k):
        with lock:
            live["all"] += 1
            live["capped"] += c.model == "gemini-4-carbon"
            for x in peak:
                peak[x] = max(peak[x], live[x])
        try:
            ladder.time.sleep(0.05)
            return real(out, c, *a, **k)
        finally:
            with lock:
                live["all"] -= 1
                live["capped"] -= c.model == "gemini-4-carbon"

    monkeypatch.setattr(ladder, "run_cell", spy)
    cells = ladder.expand_grid(["gemini-4-carbon", "gemini-3.8-flash"], ["low"], ["medium"], [0, 1, 2, 3])
    r = ladder.run_grid(tmp_path / "out", cells, concurrency=4, model_caps={"gemini-4-carbon": 1},
                        client_factory=stub_factory(accuse_script), log=lambda m: None)
    assert r["done"] == 8 and peak["capped"] == 1 and peak["all"] >= 3


def test_clash_matrix_stub(tmp_path, monkeypatch):
    from canary.gemini import clash
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    def cf(model, feature, run_id, meta):
        script = None if feature == "clash-mole" else accuse_script(None) + [{"text": "x"}] * 3
        return LedgeredClient(StubClient(script=script), feature=feature, run_id=run_id, meta=meta)

    rows = clash.run_matrix(tmp_path / "c", ["solver", "m1"], ["default", "m2"], [0], concurrency=2,
                            client_factory=cf, log=lambda m: None)
    assert len(rows) == 4 and not any(r.get("invalid") for r in rows)
    doc = clash.report(tmp_path / "c", tmp_path / "rep")
    assert {"generated_at", "git_sha", "ledger_run_ids"} <= set(doc) and len(doc["rows"]) == 4
    assert "detective" in (tmp_path / "rep" / "clash.md").read_text()


def test_second_process_skips_cells_held_by_a_live_process(tmp_path, monkeypatch):
    import os
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))
    cells = ladder.expand_grid(["gemini-3.8-flash"], ["low"], ["medium"], [0, 1])
    held = cells[0].dir(tmp_path / "out")
    held.mkdir(parents=True)
    (held / "RUNNING.json").write_text(json.dumps({"host": "other-name", "machine": ladder.MACHINE,
                                                    "pid": os.getppid()}))  # a live pid on this machine
    r = ladder.run_grid(tmp_path / "out", cells, concurrency=2, client_factory=stub_factory(accuse_script),
                        log=lambda m: None)
    assert r["ran"] == 1 and not ladder.is_done(tmp_path / "out", cells[0]) and ladder.is_done(tmp_path / "out", cells[1])



def test_subset_cut_from_a_recording_replays(tmp_path):
    """ladder_subset cuts one episode out of a committed ladder recording; its manifest matches the original."""
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    full = root / "results/gemini/replay-ladder"
    if not (full / "manifest.json").exists():
        pytest.skip("no committed ladder recording")
    rel = "gemini-3.1-flash-lite/low/easy/0/episodes.jsonl"
    r = subprocess.run([sys.executable, "-m", "canary.gemini.ladder_subset", "--store", str(full), "--name", "t",
                        "--dest", str(tmp_path), "--work", str(tmp_path / "work"), "--", "python", "-m",
                        "canary.gemini.ladder", "--models", "gemini-3.1-flash-lite", "--levels", "low", "--tiers",
                        "easy", "--seeds", "0", "--out", "{out}", "--run-name", "replay-showcase", "--max-attempts", "1"],
                       cwd=root, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-1500:]
    got = json.loads((tmp_path / "replay-t" / "manifest.json").read_text())
    want = json.loads((full / "manifest.json").read_text())
    assert got["episodes"][rel] == want["episodes"][rel] and got["responses"] > 0
    assert len(list((tmp_path / "replay-t").rglob("*.json.gz"))) == got["responses"]
