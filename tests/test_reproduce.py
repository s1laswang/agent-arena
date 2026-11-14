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
    assert "statistical reproduction; set CANARY_WORLD_SECRET for exact numbers" in printed and "CANARY_WORLD_SECRET=<any string>" in printed
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
    assert row.kind == "reported" and row.n == 6
    assert R.pass_k(row) == (3, 0.5)  # seed 900000 always right, 900001 fails once
    assert not [r for r in out["rows"] if r.pending]
    md = out["markdown"]
    assert "pass^3=0.50" in md and "replayed, judge seeds" in md
    medium = md.split("## medium")[1].split("## hard")[0]
    # reported runs sit in their own unpaired block, after the paired block
    assert medium.index("Paired runs") < medium.index("Reported agent runs") < medium.index("openai:gpt-5.5")


def test_timeout_guard_scores_zero_and_is_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    import canary.eval as E

    real = E.run_episode

    def slow(env, policy, *a, **k):
        if getattr(policy, "name", "") == "random":
            import time
            time.sleep(5)
        return real(env, policy, *a, **k)

    monkeypatch.setattr(E, "run_episode", slow)
    eps: list[dict] = []
    rows = R.run_in_process(["easy"], [900000], agents=("do_nothing", "random"), episodes_out=eps, timeout_s=0.3)
    by = {r.agent: r for r in rows}
    assert by["random"].extra["timeouts"] == [900000] and by["random"].scores == [0.0]
    assert "TIMEOUT" in by["random"].note and "timeouts" not in by["do_nothing"].extra
    assert [e["end_reason"] for e in eps] == ["horizon", "timeout"]
    md = R.table_md(rows, {"n_seeds": 1, "seed_range": "900000..900000", "fast": True, "mode": "exact",
                           "fingerprint": "x", "git_sha": "abc", "timestamp": "t", "seconds": 0.0, "timeout_s": 0.3})
    assert "1 timed out" in md and "easy/random/900000" in md


def test_determinism_two_subprocesses_fixed_secret(tmp_path):
    """CEO requirement: with a fixed CANARY_WORLD_SECRET, two separate processes give identical scores."""
    import subprocess
    env = {**os.environ, "CANARY_WORLD_SECRET": "determinism-check", "REPRO_SEEDS": "2"}
    outs = []
    for name in ("a", "b"):
        d = tmp_path / name
        subprocess.run([sys.executable, "-m", "canary.eval", "--reproduce", "--results-dir", str(d)],
                       cwd=R.ROOT, env=env, check=True, capture_output=True, timeout=300)
        outs.append((d / "judge_episodes.jsonl").read_text())
    assert outs[0] == outs[1] and len(outs[0].splitlines()) == 3 * len(R.REPRO_AGENTS) * 2


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
