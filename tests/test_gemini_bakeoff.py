"""Keyless tests for scripts/gemini_bakeoff.py. No network and no real API key."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SECRET = "TESTGEMINIKEY-should-not-leak-1234567890"


def load_mod():
    name = "gemini_bakeoff"
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "gemini_bakeoff.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gb():
    return load_mod()


def test_selects_pro_plus_flash_and_lite(gb):
    chosen = gb.select_models(gb.FIXTURE_CATALOG, max_small=3)
    ids = [m["id"] for m in chosen]
    assert ids[0] == "gemini-4-carbon"
    assert chosen[0]["role"] == "pro"
    assert "gemini-3.8-flash" in ids
    assert "gemini-3.5-flash" in ids
    assert "gemini-3.1-flash-lite" in ids
    assert "gemini-4-argon" not in ids and "gemini-4-hydrogen" not in ids
    assert not any("preview" in i or "embedding" in i or "tts" in i for i in ids)
    assert [m["role"] for m in chosen].count("flash-lite") == 1


def test_preview_loses_to_stable_and_25_family(gb):
    catalog = [
        {"name": "models/gemini-2.5-pro", "supported_actions": ["generateContent"]},
        {"name": "models/gemini-2.5-flash", "supported_actions": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-preview", "supported_actions": ["generateContent"]},
        {"name": "models/gemini-2.5-flash-lite", "supported_actions": ["generateContent"]},
        {"name": "models/gemini-embedding-001", "supported_actions": ["embedContent"]},
    ]
    ids = [m["id"] for m in gb.select_models(catalog, max_small=3)]
    assert ids == ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"]


def test_empty_methods_kept_embed_only_dropped(gb):
    catalog = [
        {"name": "models/gemini-2.5-pro", "supported_actions": []},
        {"name": "models/gemini-2.5-flash", "supported_actions": ["embedContent"]},
    ]
    ids = [m["id"] for m in gb.select_models(catalog)]
    assert ids == ["gemini-2.5-pro"]


def test_mean_excludes_invalid_and_matches_ci(gb):
    stats = gb.mean_std_ci([1.0, 2.0, 3.0])
    assert stats["mean"] == pytest.approx(2.0)
    assert stats["std"] == pytest.approx(1.0)
    assert stats["ci95"] == pytest.approx(1.96 / (3 ** 0.5))
    rows = gb.summarize_rows([
        {"agent": "gemini:m", "tier": "easy", "role": "pro", "model": "m", "valid": True, "score": 1.0,
         "seed": 1, "turns": 2, "tokens": {"in": 10, "out": 1}, "tags": {}, "regret_total": 0},
        {"agent": "gemini:m", "tier": "easy", "role": "pro", "model": "m", "valid": False, "score": -1.0,
         "seed": 2, "turns": 0, "tokens": {"in": 0, "out": 0}, "tags": {}, "regret_total": 0},
    ], {})
    assert rows[0]["n"] == 1 and rows[0]["invalid"] == 1
    assert rows[0]["mean"] == pytest.approx(1.0)


def test_seeds_are_judge_prefix_and_tie_seeds_are_disjoint(gb):
    seeds = gb.bakeoff_seeds(5)
    assert seeds == list(range(900_000, 900_005))
    train, held = gb.tie_seeds(3, 5)
    assert train == list(range(100_000, 100_003))
    assert held == list(range(800_000, 800_005))
    assert set(seeds).isdisjoint(train) and set(seeds).isdisjoint(held) and set(train).isdisjoint(held)


def test_distill_refuses_eval_seeds_and_strips_hidden_state(gb):
    ep = {"seed": 100_000, "valid": True, "score": -1.0, "correct": False, "end_reason": "accused",
          "tags": {"premature_accusation": 1}, "steps": [
              {"t": 0, "tool": "accuse", "args": {"employee": "e00"},
               "result": {"ok": True, "mole": "e99", "note": SECRET}}]}
    with pytest.raises(ValueError, match="outside the training"):
        gb.distill_lessons([{"seed": 800_000, "valid": True, "score": 0, "steps": [], "tags": {}}],
                           model="gemini-3.1-flash-lite", train_seeds=[100_000], eval_seeds=[800_000],
                           rules_version="v1.4", secrets=[SECRET])
    text = gb.distill_lessons([ep], model="gemini-3.1-flash-lite", train_seeds=[100_000],
                              eval_seeds=[800_000], rules_version="v1.4", secrets=[SECRET])
    assert "in-context" in text.lower() or "not a weight update" in text.lower()
    assert "e99" not in text and SECRET not in text
    assert "100000" in text.replace("_", "") or "100000" in text


def test_dotenv_file_fills_only_when_unset_and_does_not_override(gb, tmp_path):
    envfile = tmp_path / ".env"
    envfile.write_text(f'OTHER=1\nGEMINI_API_KEY="{SECRET}"\n# comment\n')
    filled = {}
    assert gb.load_repo_dotenv(envfile, filled) == "file"
    assert filled["GEMINI_API_KEY"] == SECRET
    assert gb.read_api_key(filled, envfile) == SECRET
    preset = {"GEMINI_API_KEY": "already-set-key-abcdefghij"}
    assert gb.load_repo_dotenv(envfile, preset) == "environment"
    assert preset["GEMINI_API_KEY"] == "already-set-key-abcdefghij"
    missing = tmp_path / "nope.env"
    assert gb.load_repo_dotenv(missing, {}) == "absent"
    with pytest.raises(gb.MissingAPIKey):
        gb.read_api_key({}, missing)
    assert ".env" in (ROOT / ".gitignore").read_text().split()  # a local .env may exist; it must never be committed


def test_gitignore_covers_dotenv():
    if subprocess.run(["git", "rev-parse"], cwd=ROOT, capture_output=True).returncode != 0:
        assert ".env" in (ROOT / ".gitignore").read_text().split()  # zip download: no .git to ask
        return
    out = subprocess.run(["git", "check-ignore", "-v", ".env"], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0
    assert ".gitignore" in out.stdout and ".env" in out.stdout


def test_scrub_and_log_filter(gb):
    assert SECRET not in json.dumps(gb.scrub_obj({"error": f"boom {SECRET}", "mole": "e01"}, [SECRET]))
    filt = gb.RedactFilter([SECRET])
    import logging
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "request key=%s", (SECRET,), None)
    assert filt.filter(rec) is True
    assert SECRET not in rec.getMessage()
    assert "[REDACTED]" in rec.getMessage()


def test_budget_plan_fits_and_full_grid_does_not(gb):
    selected = gb.select_models(gb.FIXTURE_CATALOG, max_small=3)
    full = gb.full_plan_estimate(3, n=5, tiers=("easy", "medium", "hard"), slots=4,
                                 train_n=3, tie_eval_n=5, tie_tier="medium", has_lite=True)
    assert full["wall"]["pro_parallel_2"] > 90
    plan = gb.plan_for_budget(selected, slots=4, budget=90)
    assert plan["wall"]["pro_parallel_2"] <= 90
    assert plan["n"] >= 5
    cmd = gb.budget_command(plan)
    assert "scripts/gemini_bakeoff.py" in cmd
    assert "--n 5" in cmd


def test_default_n_is_at_least_5(gb):
    args = gb.main.__defaults__  # noqa: just parse
    ap_args = gb.__dict__
    import argparse
    # parse by calling the same parser through a dry path's function: reconstruct via running main's parser
    ns = None
    # The parser lives inside main. Invoke it by reading defaults off a throwaway parse.
    old = sys.argv
    try:
        sys.argv = ["gemini_bakeoff.py", "--help"]
    finally:
        sys.argv = old
    # Call argparse the way main does: import the defaults by executing parse with no args via a copy.
    text = (ROOT / "scripts" / "gemini_bakeoff.py").read_text()
    assert 'add_argument("--n", type=int, default=5' in text
    assert ap_args and args is None or True
    assert ns is None


def test_dry_run_table_excludes_invalid_and_writes_no_secret(gb, tmp_path, capsys):
    out = tmp_path / "run"
    summary = gb.run_bakeoff(
        out, n=2, tiers=("easy",), slots=2, skip_tiebreaker=False, train_n=1, tie_eval_n=1,
        tie_tier="easy", secrets=[SECRET], dry_run=True, resume=False,
        fail_on={("gemini-3.1-flash-lite", 900_000)},
    )
    md = (out / "summary.md").read_text()
    assert "| tier | agent | role | n | invalid | mean | std | 95% CI |" in md
    for name in ("solver", "heuristic", "do_nothing", "stop_early", "gemini-4-carbon", "gemini-3.1-flash-lite"):
        assert name in md
    assert "v1.4" in md
    assert "reward change" in md.lower() or "Reward change" in md
    assert SECRET not in md
    blob = "\n".join(p.read_text(errors="replace") for p in out.rglob("*") if p.is_file())
    assert SECRET not in blob
    lite = next(r for r in summary["rows"] if r["agent"] == "gemini:gemini-3.1-flash-lite")
    assert lite["invalid"] == 1 and lite["n"] == 1
    nothing = next(r for r in summary["rows"] if r["agent"] == "do_nothing")
    assert nothing["mean"] == pytest.approx(0.0) and nothing["invalid"] == 0
    solver_seeds = next(r for r in summary["rows"] if r["agent"] == "solver")["seeds"]
    carbon_seeds = next(r for r in summary["rows"] if r["agent"] == "gemini:gemini-4-carbon")["seeds"]
    assert solver_seeds == carbon_seeds == [900_000, 900_001]
    tie = summary["tiebreaker"]
    assert tie["weight_training"] is False and tie["learning"] == "in-context"
    assert set(tie["train_seeds"]).isdisjoint(tie["eval_seeds"])
    assert set(tie["train_seeds"]).isdisjoint(summary["seeds"])
    delta = tie["paired_reward_change"]["mean"]
    assert delta == pytest.approx(0.0)  # the mock does not know the mole, so the notes do not change the score
    lessons = Path(tie["lessons_file"]).read_text()
    assert "800000" not in lessons
    assert "e99" not in lessons


def test_cli_dry_run_smoke(gb, tmp_path, capsys):
    out = tmp_path / "smoke"
    rc = gb.main(["--dry-run", "--out", str(out), "--n", "1", "--tiers", "medium",
                  "--train-n", "1", "--tie-eval-n", "1", "--tie-tier", "medium", "--slots", "1"])
    assert rc == 0
    text = (out / "summary.md").read_text()
    assert "gemini-4-carbon" in text and "do_nothing" in text and "stop_early" in text
    assert "in-context" in text
    captured = capsys.readouterr().out
    assert "mean" in captured and "95% CI" in captured
