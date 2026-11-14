import ast
import io
import json
import os
import tokenize
from pathlib import Path

import pytest

from lab import frontier_cache, frontier_replay, frontier_rows, reproduce
from lab import run as lab_run
from scripts import gemini_cache

ROOT = Path(__file__).resolve().parent.parent


def build_real_shaped_row(dest_dir, seed, trial=0, model="gemini-4-carbon", commit="5b8ddb20", prompt_budget="200"):
    os.environ["LAB_GEMINI"] = "0"
    os.environ["GEMINI_API_KEY"] = ""
    bg = frontier_rows.bg_for("procedure")
    res, tr = lab_run.play_day(bg, "do_nothing", "finance_ap", seed, trial)
    row = {
        "invalid": None,
        "sleeper_mode": "scripted",
        "model": model,
        "commit": commit,
        "day_source": "day_for",
        "sleeper": "scripted",
        "calls_by_model": {model: 5},
        "team": "procedure",
        "bg_version": "9fa41d4",
        "prompt_budget": prompt_budget,
        "budget_calls": 400,
        "agent": "gemini",
        "seat": "finance_ap",
        "mode": "seat",
        "seed": seed,
        "trial": trial,
        "scores": frontier_rows.scores(res),
        "calls": 5,
        "capped": False,
        "cache_hits": 0,
        "in_tokens": 100,
        "out_tokens": 20,
        "cost": None,
        "provenance": "real",
        "transcript": tr,
    }
    row.update(frontier_rows.derive(row))
    run_path = dest_dir / f"finance_ap-s{seed}-t{trial}.json"
    frontier_rows.save_state(str(run_path), row)
    run_path.write_text(json.dumps(row, indent=1, sort_keys=True, default=str))
    cache_src = dest_dir / f"_csrc_{seed}_{trial}"
    cache_src.mkdir(exist_ok=True)
    (cache_src / "entry.json").write_text(json.dumps({"ok": True}))
    tar_path = dest_dir / f"cache-s{seed}-t{trial}.tar.gz"
    gemini_cache.pack(str(tar_path), cache_src)
    return run_path, row


def make_synth_frontier(base_dir):
    froot = base_dir / "frontier"
    cur = froot / "gemini-4-carbon" / "5b8ddb20"
    cur.mkdir(parents=True)
    for seed in (1000, 1001, 1002):
        build_real_shaped_row(cur, seed, trial=0)
    leg = froot / "gemini-3.5-flash" / "b06e6ad"
    leg.mkdir(parents=True)
    legacy_row = {
        "invalid": None,
        "model": "gemini-3.5-flash",
        "commit": "b06e6ad",
        "agent": "gemini",
        "seat": "finance_ap",
        "mode": "seat",
        "team": "procedure",
        "prompt_budget": "60(false)",
        "seed": 1000,
        "trial": 0,
        "scores": {"reward": 0, "harm": [], "false_quarantines": [], "tickets_done": 10, "tickets_total": 42},
        "transcript": {"steps": [], "ledger": [], "messages": []},
    }
    (leg / "finance_ap-s1000-t0.json").write_text(json.dumps(legacy_row))
    return froot


def test_frontier_replay_paired_gap_and_legacy(tmp_path, monkeypatch, capsys):
    froot = make_synth_frontier(tmp_path)

    def fake_rerun(row, cache_dir):
        assert (Path(cache_dir) / "entry.json").is_file()
        return {**row, "calls": 0, "cache_hits": 5}

    monkeypatch.setattr(frontier_cache, "rerun", fake_rerun)
    json_out = tmp_path / "fr.json"
    md_out = tmp_path / "fr.md"
    res = frontier_replay.main([str(froot), "--strict", "--json-out", str(json_out), "--md-out", str(md_out)])
    out = capsys.readouterr().out
    assert res["cache_replayed"] == "3/3"
    assert res["legacy_skipped"] == 1
    assert res["replay_failures"] == []
    assert len(res["groups"]) == 1
    grp = res["groups"][0]
    assert grp["cache_replayed"] == "3/3"
    assert grp["n_days"] == 3
    assert grp["n_runs"] == 3
    assert grp["frontier_mean"] == 0.0
    assert grp["ref_mean"] == 1.0
    assert grp["paired_diff"] == 1.0
    assert grp["verdict"] == "GAP (CI excludes 0)"
    assert json_out.is_file() and md_out.is_file()
    assert "## Frontier vs Reference (paired on same seeds)" in out
    assert "frontier_replay: cache_replayed=3/3 legacy_skipped=1 failures=0" in out

    sample_run = froot / "gemini-4-carbon" / "5b8ddb20" / "finance_ap-s1000-t0.json"
    single = frontier_replay.main(["--run", str(sample_run)])
    assert single["ok"] is True
    assert "REPLAY OK" in capsys.readouterr().out


def test_frontier_replay_strict_rejects_cache_miss_and_tampering(tmp_path, monkeypatch):
    froot = tmp_path / "frontier_miss"
    cur = froot / "gemini-4-carbon" / "5b8ddb20"
    cur.mkdir(parents=True)
    run_path, _ = build_real_shaped_row(cur, 1000, trial=0)

    def miss_rerun(row, cache_dir):
        raise SystemExit("replay failed (cache miss = not replayable)")

    monkeypatch.setattr(frontier_cache, "rerun", miss_rerun)
    with pytest.raises(SystemExit) as exc_miss:
        frontier_replay.main([str(froot), "--strict"])
    assert exc_miss.value.code not in (None, 0)

    tampered = json.loads(run_path.read_text())
    tampered["scores"]["reward"] = 1
    tampered["result"]["reward"] = 1
    run_path.write_text(json.dumps(tampered))
    with pytest.raises(SystemExit) as exc_tamper:
        frontier_replay.main([str(froot), "--strict", "--skip-cache-rerun"])
    assert exc_tamper.value.code not in (None, 0)


def test_reproduce_cmd_writes_outputs_and_prints_unified_table(tmp_path, capsys):
    synth_frontier = make_synth_frontier(tmp_path)
    out_dir = tmp_path / "out"
    res = reproduce.main(
        [
            "--days",
            "1",
            "--trials",
            "1",
            "--day-start",
            "1000",
            "--out",
            str(out_dir),
            "--frontier-root",
            str(synth_frontier),
            "--skip-probes",
            "--skip-gaptable",
            "--skip-cache-rerun",
        ]
    )
    printed = capsys.readouterr().out
    assert (out_dir / "eval" / "summary.json").is_file()
    assert (out_dir / "eval" / "gap.md").is_file()
    assert (out_dir / "runs" / "frontier_replay.json").is_file()
    assert (out_dir / "runs" / "frontier_replay.md").is_file()
    assert not (out_dir / "eval" / "frontier_replay.json").exists()
    assert "==== SLEEPER REPRODUCE TABLE ====" in printed
    assert "### All 8 seats" in printed
    assert "### Judge seat" in printed
    assert "## Frontier vs Reference" in printed
    assert res["frontier_replay"]["legacy_skipped"] == 1


def test_owned_files_have_no_comments_docstrings_or_em_dashes():
    triple_dq = chr(34) * 3
    triple_sq = chr(39) * 3
    em_dash = chr(8212)
    targets = [
        ROOT / "lab" / "frontier_replay.py",
        ROOT / "lab" / "reproduce.py",
        ROOT / "tests" / "test_reproduce_cmd.py",
    ]
    for path in targets:
        src = path.read_text(encoding="utf-8")
        assert em_dash not in src, f"em dash in {path}"
        assert triple_dq not in src, f"triple double-quote in {path}"
        assert triple_sq not in src, f"triple single-quote in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"comment in {path}: {comments[0]}"
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                assert ast.get_docstring(node) is None, f"docstring in {path}"
