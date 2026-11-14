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
        assert se.scores == [0.0] * N and not se.accuse_days
        (gd,) = _rows(out, tier, "guess_day1")
        assert all(s == -1.0 or s > 0 for s in gd.scores) and len(gd.accuse_days) == N


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


def test_env_secret_not_shadowed_by_earlier_in_process_secret(tmp_path, monkeypatch):
    from canary import world
    if not hasattr(world, "set_world_secret"):
        pytest.skip("canary.world has no set_world_secret")
    monkeypatch.setenv("CANARY_WORLD_SECRET", "same-secret")
    a = _run(tmp_path / "a")
    world.set_world_secret(b"x" * 32)  # e.g. left behind by an MCP server test
    try:
        b = _run(tmp_path / "b")
        assert getattr(world, "_SET_SECRET", None) == b"x" * 32  # restored afterwards
    finally:
        world.set_world_secret(None)
    assert ((tmp_path / "a" / "results" / "judge_episodes.jsonl").read_text()
            == (tmp_path / "b" / "results" / "judge_episodes.jsonl").read_text())
    assert a["header"]["fingerprint"] == b["header"]["fingerprint"]


@pytest.mark.skipif(SALT.exists(), reason="a local SALT file forces exact mode")
def test_keyless_run_is_statistical_and_never_leaks_the_secret(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CANARY_WORLD_SECRET", raising=False)
    out = R.reproduce(2, tmp_path / "results", root=tmp_path, quiet=False)
    assert out["header"]["mode"] == "statistical"
    assert "CANARY_WORLD_SECRET" not in os.environ  # the secret never enters the environment
    from canary import world
    assert getattr(world, "_SET_SECRET", None) is None  # in-process secret cleared again
    printed = capsys.readouterr().out
    assert "statistical reproduction; set CANARY_WORLD_SECRET for exact numbers" in printed and "CANARY_WORLD_SECRET=<any string>" in printed
    files = printed + "".join(p.read_text() for p in (tmp_path / "results").glob("*.[jm]*"))
    assert not re.search(r"[0-9a-f]{64}", files)  # the 32-byte hex secret is never written


def test_committed_agent_runs_are_replayed_with_pass_k(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    run = tmp_path / "data" / "runs" / "committed" / R.current_tiers_version() / "openai_gpt-5.5-medium-x"
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


# ---- reported runs are grouped by tier version, never pooled; superseded builds excluded -------------
def _write_run(path: Path, agent: str, tier: str, seeds, score: float, meta: dict | None = None):
    path.mkdir(parents=True)
    lines = [json.dumps({"tier": tier, "seed": s, "agent": agent, "steps": [], "score": score,
                         "accused": "e01", "correct": score > 0, "final_day": 9, "end_reason": "accused",
                         "meta": {}}) for s in seeds]
    (path / "episodes.jsonl").write_text("\n".join(lines) + "\n")
    if meta is not None:
        (path / "meta.json").write_text(json.dumps(meta))


def _versioned_fixture(tmp_path):
    cur = R.current_tiers_version()
    assert cur not in ("v1.1", "v1.2")
    c = tmp_path / "data" / "runs" / "committed"
    seeds = list(JUDGE_SEEDS)[:4]
    # v1.2 by path (no version segment, no tiers_version in meta), with a git sha
    _write_run(c / "gpt-5.5" / "medium-0-4", "openai:gpt-5.5", "medium", seeds[:2], 0.5,
               {"git_sha": "aaaaaaa1111", "agent": "openai:gpt-5.5", "tier": "medium"})
    # v1.2 by meta
    _write_run(c / "codex" / "medium", "codex:gpt-5.5", "medium", seeds[:1], 0.4,
               {"tiers_version": "v1.2", "git_sha": "ccccccc3333"})
    # current version by path segment (meta has no tiers_version)
    _write_run(c / cur / "gpt-5.5" / "medium-0-4", "openai:gpt-5.5", "medium", seeds[:3], -1.0,
               {"git_sha": "bbbbbbb2222"})
    # current version by meta, same agent also present in v1.2
    _write_run(c / cur / "codex" / "medium", "codex:gpt-5.5", "medium", seeds[:1], 0.9,
               {"tiers_version": cur, "git_sha": "ddddddd4444"})
    # an older generic vX.Y segment, no git sha
    _write_run(c / "v1.1" / "gpt-5.5" / "medium", "openai:gpt-5.5", "medium", seeds[:1], 0.2, {})
    # superseded builds: excluded entirely, whatever version they claim
    _write_run(c / "superseded" / "old_solver" / "solver-medium", "solver", "medium", seeds, 0.99,
               {"tiers_version": cur, "git_sha": "eeeeeee5555"})
    _write_run(c / "superseded" / "x" / "gpt-medium", "openai:gpt-5.5", "medium", seeds, 0.99,
               {"tiers_version": cur})
    return cur


def test_run_tiers_version_from_meta_then_path(tmp_path):
    c = tmp_path / "data" / "runs" / "committed"
    for d in ("a/medium", "v1.3/a/medium", "v2.0/b", "superseded/v1.3/z"):
        (c / d).mkdir(parents=True)
    (c / "a" / "medium" / "meta.json").write_text(json.dumps({"tiers_version": "v1.3"}))
    assert R.run_tiers_version(c / "a" / "medium", tmp_path) == "v1.3"            # meta wins
    assert R.run_tiers_version(c / "v1.3" / "a" / "medium", tmp_path) == "v1.3"   # path segment
    assert R.run_tiers_version(c / "v2.0" / "b", tmp_path) == "v2.0"              # any vX.Y segment
    (c / "a" / "medium" / "meta.json").write_text(json.dumps({"git_sha": "x"}))
    assert R.run_tiers_version(c / "a" / "medium", tmp_path) == "v1.2"            # no segment: v1.2
    assert R.is_superseded(c / "superseded" / "v1.3" / "z", tmp_path)
    assert not R.is_superseded(c / "v1.3" / "a" / "medium", tmp_path)


def test_committed_runs_grouped_by_version_never_pooled(tmp_path):
    cur = _versioned_fixture(tmp_path)
    rows, files = R.load_committed(tmp_path)
    key = {(r.extra["tiers_version"], r.agent): r for r in rows}
    assert len(key) == len(rows) == 5  # one row per (tier, version, agent): nothing merged
    assert key[(cur, "openai:gpt-5.5")].scores == [-1.0] * 3
    assert key[("v1.2", "openai:gpt-5.5")].scores == [0.5] * 2
    assert key[("v1.1", "openai:gpt-5.5")].scores == [0.2]
    assert key[(cur, "codex:gpt-5.5")].scores == [0.9] and key[("v1.2", "codex:gpt-5.5")].scores == [0.4]
    assert "git bbbbbbb" in key[(cur, "openai:gpt-5.5")].note
    assert "git aaaaaaa" in key[("v1.2", "openai:gpt-5.5")].note
    assert "git unknown" in key[("v1.1", "openai:gpt-5.5")].note
    # superseded: no rows, no files, none of their scores
    assert len(files) == 5 and not any("superseded" in f for f in files)
    assert all(0.99 not in r.scores for r in rows) and not any(r.agent == "solver" for r in rows)


def test_table_current_version_first_then_history(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    cur = _versioned_fixture(tmp_path)
    out = _run(tmp_path)
    md = out["markdown"]
    medium = md.split("## medium")[1].split("## hard")[0]
    h_cur = f"Reported agent runs: {cur} (current rules):"
    h_12 = "History: v1.2 (earlier rules, not comparable to the paired table):"
    h_11 = "History: v1.1 (earlier rules, not comparable to the paired table):"
    assert "Reported agent runs (replayed" not in md  # the old pooled block is gone
    assert medium.index("Paired runs") < medium.index(h_cur) < medium.index(h_12) < medium.index(h_11)
    block = lambda h: medium.split(h)[1].split("\n\n")[1]
    gpt = lambda b: [l for l in b.splitlines() if l.startswith("| openai:gpt-5.5 |")]
    (cur_row,) = gpt(block(h_cur))
    (v12_row,) = gpt(block(h_12))
    assert "| reported | 3 | 0 | -1.000" in cur_row and "bbbbbbb" in cur_row
    assert "| reported | 2 | 0 | +0.500" in v12_row and "aaaaaaa" in v12_row
    assert "| 9.0 | – |" in v12_row  # no `/ solver` ratio against this run's solver for history
    # superseded excluded from the table and the rows
    assert "superseded" not in md.split("## medium")[1] and "eeeeeee" not in md and "+0.990" not in md
    assert not [r for r in out["rows"] if r.kind == "reported" and r.agent == "solver"]
    assert not [r for r in out["rows"] if r.pending]  # current-version runs exist, nothing pending


def test_only_history_runs_leave_current_rules_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    c = tmp_path / "data" / "runs" / "committed"
    _write_run(c / "gpt-5.5" / "medium", "openai:gpt-5.5", "medium", list(JUDGE_SEEDS)[:2], 0.5, {})
    out = _run(tmp_path)
    medium = out["markdown"].split("## medium")[1].split("## hard")[0]
    cur = R.current_tiers_version()
    assert (medium.index(f"Reported agent runs: {cur} (current rules)") < medium.index("pending")
            < medium.index("History: v1.2"))


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


# ---- default output dir: a judge's clone stays clean (HARNESS craft fix) ----------------------------
def test_default_output_is_gitignored_latest_and_leaves_committed_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_WORLD_SECRET", "test-reproduce")
    committed = tmp_path / "results"
    committed.mkdir()
    (committed / "judge_table.md").write_text("COMMITTED")
    out = R.reproduce(2, root=tmp_path, quiet=True)  # default results_dir
    assert out["results_dir"] == tmp_path / "results" / "latest"
    for f in ("judge_table.md", "judge_episodes.jsonl"):
        assert (tmp_path / "results" / "latest" / f).exists()
    assert (committed / "judge_table.md").read_text() == "COMMITTED"
    assert not (committed / "judge_episodes.jsonl").exists()


def test_results_dir_for_flags():
    assert R.results_dir_for() == "results/latest"
    assert R.results_dir_for(update_committed=True) == "results"
    assert R.results_dir_for(results_dir="x") == "x"
    with pytest.raises(ValueError):
        R.results_dir_for(update_committed=True, results_dir="x")


def test_cli_rejects_results_dir_with_update_committed(tmp_path, capsys):
    assert main(["--reproduce", "--update-committed", "--results-dir", str(tmp_path)]) == 2
    assert "not both" in capsys.readouterr().err


def test_results_latest_is_gitignored_and_committed_results_are_not():
    import subprocess
    ign = lambda p: subprocess.run(["git", "check-ignore", "-q", p], cwd=R.ROOT).returncode == 0
    if subprocess.run(["git", "rev-parse"], cwd=R.ROOT, capture_output=True).returncode != 0:
        pytest.skip("not a git checkout")
    assert ign("results/latest/judge_table.md")
    assert not ign("results/judge_table.md") and not ign("results/gap_chart.png")


# ---- per-seed dedupe (newest run wins) and invalid episodes out of the means --------------------------
def _ep(tier, agent, seed, score, valid=True, error=None):
    meta = {"valid": valid} if valid else {"valid": False, "error": error}
    return {"tier": tier, "seed": seed, "agent": agent, "steps": [], "score": score,
            "accused": "e01" if valid else None, "correct": score > 0, "final_day": 9,
            "end_reason": "accused" if valid else "error", "meta": meta}


def _write_eps(path: Path, eps, ts: str):
    path.mkdir(parents=True)
    (path / "episodes.jsonl").write_text("\n".join(json.dumps(e) for e in eps) + "\n")
    (path / "meta.json").write_text(json.dumps({"timestamp": ts, "git_sha": "c0ffee00",
                                                "tiers_version": R.current_tiers_version()}))


def _reported(rows, tier, agent):
    (r,) = [r for r in rows if r.tier == tier and r.agent == agent and r.kind == "reported"]
    return r


def test_dedupe_newest_run_per_seed_wins_by_timestamp_not_path(tmp_path):
    c = tmp_path / "data" / "runs" / "committed" / R.current_tiers_version()
    # the OLDER run sorts LAST by path ("zz-smoke"), so path order alone would pick the wrong one
    _write_eps(c / "zz-smoke" / "hard", [_ep("hard", "codex:gpt-5.5", 0, 0.67)], "2026-11-14T01:00:00")
    _write_eps(c / "aa-full" / "hard", [_ep("hard", "codex:gpt-5.5", 0, -1.0),
                                        _ep("hard", "codex:gpt-5.5", 1, 0.6)], "2026-11-14T05:00:00")
    rows, _ = R.load_committed(tmp_path)
    r = _reported(rows, "hard", "codex:gpt-5.5")
    assert r.n == 2 and sorted(r.seeds) == [0, 1]
    assert dict(zip(r.seeds, r.scores))[0] == -1.0          # the newer full run's seed 0, not the smoke
    assert r.extra["dropped_duplicates"] == [(0, str((c / "zz-smoke" / "hard").relative_to(tmp_path)))]
    assert "older duplicate episode(s) dropped" in r.note and "WARNING" not in r.note


def test_every_reported_row_has_n_equal_distinct_seeds_unless_warned(tmp_path):
    c = tmp_path / "data" / "runs" / "committed" / R.current_tiers_version()
    # repeats WITHIN one run are intentional (pass^k): kept, but the note warns
    _write_eps(c / "rep" / "medium", [_ep("medium", "openai:gpt-5.5", s, 0.5) for s in (0, 0, 1, 1)],
               "2026-11-14T05:00:00")
    _write_eps(c / "one" / "medium", [_ep("medium", "grok", s, 0.5) for s in (0, 1, 2)], "2026-11-14T05:00:00")
    rows, _ = R.load_committed(tmp_path)
    rep = _reported(rows, "medium", "openai:gpt-5.5")
    assert rep.n == 4 and "WARNING n=4 != 2 distinct seeds" in rep.note
    assert R.pass_k(rep) is not None                        # pass^k still measurable
    for r in rows:
        assert r.n == len(set(r.seeds)) or "WARNING" in r.note


def test_invalid_episodes_excluded_from_means_and_listed_with_reasons(tmp_path):
    c = tmp_path / "data" / "runs" / "committed" / R.current_tiers_version()
    a = "opencode:openai/gpt-5.6-sol"
    _write_eps(c / "sol" / "hard", [
        _ep("hard", a, 0, 0.0, valid=False, error="RuntimeError('MCP server died during the episode (rc=-15)')"),
        _ep("hard", a, 1, 0.635),
        _ep("hard", a, 2, 0.0, valid=False, error="infra:provider_quota"),
        _ep("hard", a, 3, 0.0, valid=False, error="infra:provider_quota"),
    ], "2026-11-14T05:00:00")
    rows, _ = R.load_committed(tmp_path)
    r = _reported(rows, "hard", a)
    assert r.n == 1 and r.scores == [0.635]                 # infra failures do not count as 0
    assert r.extra["invalid"] == [(0, "mcp server died"), (2, "infra:provider_quota"), (3, "infra:provider_quota")]
    md = R._row_md(r, None, compare=False)
    assert "| 3 (infra:provider_quota ×2, mcp server died) |" in md and "+0.635" in md


def test_row_with_only_invalid_episodes_still_renders(tmp_path):
    c = tmp_path / "data" / "runs" / "committed" / R.current_tiers_version()
    _write_eps(c / "dead" / "medium", [_ep("medium", "gemini:x", 0, 0.0, valid=False, error="infra:provider_quota")],
               "2026-11-14T05:00:00")
    rows, _ = R.load_committed(tmp_path)
    r = _reported(rows, "medium", "gemini:x")
    assert r.n == 0 and "| 1 (infra:provider_quota) |" in R._row_md(r, None, compare=False)
