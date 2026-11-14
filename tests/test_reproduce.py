"""make reproduce / canary.reproduce (HARNESS): judge table from a keyless checkout, small seed counts."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from canary import reproduce as R
from canary.eval import main
from canary.rules import JUDGE_SEEDS

N = 3  # seeds per tier in these tests (the real run uses all JUDGE_SEEDS)
SALT = R.ROOT / "data" / "worlds" / "judge" / "SALT"


def _run(tmp_path, root=None, **kw):
    return R.reproduce(N, tmp_path / "results", root=root or tmp_path, quiet=True, **kw)


def _rows(out, tier, agent):
    return [r for r in out["rows"] if r.tier == tier and r.agent == agent]


def test_outputs_and_every_agent_on_every_tier(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    out = _run(tmp_path)
    res = tmp_path / "results"
    md = (res / "judge_table.md").read_text()
    assert md == out["markdown"]
    for tier in ("medium", "hard", "easy"):
        assert f"## {tier}" in md
        for agent in R.REPRO_AGENTS:
            (row,) = _rows(out, tier, agent)
            assert row.n == N and row.seeds == list(JUDGE_SEEDS)[:N]
    eps = [json.loads(x) for x in (res / "judge_episodes.jsonl").read_text().splitlines()]
    assert len(eps) == 3 * len(R.REPRO_AGENTS) * N
    assert "FAST MODE" in md  # fewer than JUDGE_SEEDS is labelled as not the reported numbers
    if out["chart_skipped"] is None:
        assert (res / "gap_chart.png").stat().st_size > 1000


def test_baseline_integrity_in_table(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    out = _run(tmp_path)
    for tier in ("medium", "hard", "easy"):
        (dn,) = _rows(out, tier, "do_nothing")
        assert dn.scores == [0.0] * N and not dn.accuse_days
        (se,) = _rows(out, tier, "stop_early")
        assert all(s == -1.0 or s > 0 for s in se.scores) and len(se.accuse_days) == N


def test_frontier_rows_pending_without_committed_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    out = _run(tmp_path)
    pend = [r for r in out["rows"] if r.pending]
    assert {r.tier for r in pend} == {"medium", "hard"}
    assert "pending" in out["markdown"]


def test_exact_mode_is_bit_for_bit(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "same-secret")
    a = _run(tmp_path / "a")
    b = _run(tmp_path / "b")
    ea = (tmp_path / "a" / "results" / "judge_episodes.jsonl").read_text()
    eb = (tmp_path / "b" / "results" / "judge_episodes.jsonl").read_text()
    assert ea == eb
    assert a["header"]["mode"] == "exact" and a["header"]["fingerprint"] == b["header"]["fingerprint"]


@pytest.mark.skipif(SALT.exists(), reason="a local SALT file forces exact mode")
def test_keyless_run_is_statistical_and_never_leaks_the_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CANARY_WORLD_SECRET", raising=False)
    out = R.reproduce(2, tmp_path / "results", root=tmp_path, quiet=False)
    assert out["header"]["mode"] == "statistical"
    assert "CANARY_WORLD_SECRET" not in os.environ  # generated secret removed again
    printed = capsys.readouterr().out
    assert "statistically reproducible" in printed and "CANARY_WORLD_SECRET=<any string>" in printed
    files = printed + "".join(p.read_text() for p in (tmp_path / "results").glob("*.[jm]*"))
    assert not re.search(r"[0-9a-f]{64}", files)  # the 32-byte hex secret is never written


def test_committed_agent_runs_are_replayed_with_pass_k(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    run = tmp_path / "data" / "runs" / "committed" / "openai_gpt-5.5-medium-x"
    run.mkdir(parents=True)
    lines = []
    for rep in range(3):
        for seed in (900000, 900001):
            correct = not (seed == 900001 and rep == 0)
            lines.append(json.dumps({"tier": "medium", "seed": seed, "agent": "openai:gpt-5.5", "steps": [],
                                     "score": 0.5 if correct else -1.0, "accused": "e01", "correct": correct,
                                     "final_day": 9, "end_reason": "accused", "meta": {}}))
    (run / "episodes.jsonl").write_text("\n".join(lines) + "\n")
    out = _run(tmp_path)
    (row,) = _rows(out, "medium", "openai:gpt-5.5")
    assert row.kind == "frontier" and row.n == 6
    assert R.pass_k(row) == (3, 0.5)  # seed 900000 always right, 900001 fails once
    assert not [r for r in out["rows"] if r.pending]
    assert "pass^3=0.50" in out["markdown"] and "replayed, judge seeds" in out["markdown"]


def test_seed_count_controls(monkeypatch):
    monkeypatch.delenv("REPRO_SEEDS", raising=False)
    monkeypatch.delenv("REPRO_FAST", raising=False)
    assert R.seeds_per_tier() == list(JUDGE_SEEDS)
    monkeypatch.setenv("REPRO_FAST", "1")
    assert len(R.seeds_per_tier()) == R.FAST_SEEDS
    monkeypatch.setenv("REPRO_SEEDS", "2")
    assert R.seeds_per_tier() == list(JUDGE_SEEDS)[:2]
    assert len(R.seeds_per_tier(7)) == 7


def test_chart_skipped_gracefully_without_matplotlib(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    reason = R.gap_chart([], tmp_path / "x.png")
    assert reason and "matplotlib" in reason and not (tmp_path / "x.png").exists()


def test_cli_reproduce(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    assert main(["--reproduce", "--repro-seeds", "2", "--results-dir", str(tmp_path)]) == 0
    assert "## medium (headline)" in capsys.readouterr().out
    assert (Path(tmp_path) / "judge_table.md").exists()
