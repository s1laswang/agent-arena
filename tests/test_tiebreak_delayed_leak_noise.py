from __future__ import annotations

import ast
import copy
import io
import json
import os
from pathlib import Path
import time
import tokenize

import pytest

from canary.env import Env
from canary.eval import run_episode
import scripts.tiebreak_addendum_pack as addendum_mod
import scripts.tiebreak_delayed_leak_noise_audit as mod
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.verify_tiebreak_submission as gate

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_delayed_leak_noise_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "delayed_leak_noise" / "noise_audit_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_delayed_leak_noise.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_ast_isolation_and_ledger_disjointness() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src

    iso = gate.check_ast_inference_isolation(root=REPO_ROOT, extra_paths=[SCRIPT_PATH], strict=True)
    assert iso.passed is True, iso.errors
    assert "scripts/tiebreak_delayed_leak_noise_audit.py" in iso.metrics["modules_checked"]

    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    discovered_addendum = addendum_mod.discover_run_summaries(repo_root=REPO_ROOT)
    discovered_paths = {r["summary_path"] for r in discovered_addendum}
    assert "results/tiebreak/delayed_leak_noise/noise_audit_summary.json" not in discovered_paths

    ledger = json.loads((REPO_ROOT / "results" / "tiebreak" / "experiment_ledger.json").read_text(encoding="utf-8"))
    ledger_paths = {
        r.get("summary_path")
        for r in (list(ledger.get("historical_runs") or []) + list(ledger.get("discovered_runs") or []))
        if isinstance(r, dict)
    }
    assert "results/tiebreak/delayed_leak_noise/noise_audit_summary.json" not in ledger_paths
    assert ledger_mod is not None


def test_check_mode_speed_and_committed_artifact_invariants(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    rc = mod.main(["--check"])
    dt = time.perf_counter() - t0
    assert rc == 0
    assert dt < 1.5

    cli_out = json.loads(capsys.readouterr().out)
    assert cli_out["passed"] is True
    assert cli_out["errors"] == []
    assert cli_out["episodes_verified"] == 450
    assert cli_out["elapsed_seconds"] < 1.5
    assert SUMMARY_PATH.stat().st_size < mod.MAX_SUMMARY_BYTES

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    report_txt = REPORT_PATH.read_text(encoding="utf-8")

    assert summary["schema"] == mod.SCHEMA_VERSION
    assert summary["tiers_version"] == "v1.4"
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["eval_seeds"] == {"start": 800000, "stop": 800030}
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["eval_seeds_per_tier"] == 30
    assert summary["n_heldout_per_policy"] == 90
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["primary_episodes_verified"] == 360
    assert summary["episodes_verified"] == 450
    assert "post-hoc locked, not pre-registered" in report_txt.lower()

    tables = gate._parse_markdown_tables(report_txt)
    assert len(tables) == 5
    assert len(tables[0][1]) == 20
    assert len(tables[1][1]) == 12
    assert len(tables[2][1]) == 5
    assert len(tables[3][1]) == len(summary["hard_noise_analysis"]["primary_mismatch_events"])
    assert len(tables[4][1]) == 16


def test_hidden_leak_gap_noise_counterfactual_and_paired_regret_math() -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    hgap = summary["hidden_leak_gap"]
    noise = summary["hard_noise_analysis"]
    reg = summary["paired_regret_vs_solver"]

    for pk in mod.PRIMARY_POLICIES:
        easy_acc_gap = hgap[pk]["by_tier"]["easy"]["at_accusation_hidden_v_gap"]["mean"]
        med_gap = hgap[pk]["by_tier"]["medium"]["hidden_v_gap"]["mean"]
        hard_gap = hgap[pk]["by_tier"]["hard"]["hidden_v_gap"]["mean"]
        assert easy_acc_gap == pytest.approx(0.0, abs=1e-9)
        assert easy_acc_gap < med_gap < hard_gap

        hard_block = hgap[pk]["by_tier"]["hard"]
        assert hard_block["mean_delay_discounted_v_mae"] < hard_block["mean_uncorrected_v_mae"]
        assert hard_block["mean_breakeven_shift"] > 0.01

    assert noise["easy_and_medium_noisy_mismatches"] == 0
    pct = noise["primary_cohort_totals"]
    assert pct["observed_mismatch_episodes"] >= 4
    assert pct["naive_hard_elim_false_exculpation_rate"] == pytest.approx(1.0, abs=1e-9)
    assert pct["smoothed_false_exculpation_rate"] == pytest.approx(0.0, abs=1e-9)
    assert pct["smoothed_caught_true_mole_episodes"] >= 3
    assert pct["naive_hard_elim_caught_episodes"] == 0

    hcomp = noise["live_heuristic_hard_elim_comparator"]
    assert hcomp["observed_mismatch_episodes"] >= 5
    assert hcomp["caught_true_mole_episodes"] == 0
    assert hcomp["false_exculpation_rate"] == pytest.approx(1.0, abs=1e-9)

    for pk in ("empirical_bayes", "tiny_mlp", "compact_linear_dagger", "heuristic_hard_elim"):
        for scope in ("overall", "easy", "medium", "hard"):
            rb = reg[pk]["overall"] if scope == "overall" else reg[pk]["by_tier"][scope]
            deltas = [float(x) for x in rb["regret_deltas"]]
            recomp = mod.mean_ci95(deltas)
            assert recomp["mean"] == pytest.approx(rb["score_regret_vs_solver"]["mean"], abs=1e-6)
            assert recomp["ci95_low"] == pytest.approx(rb["score_regret_vs_solver"]["ci95_low"], abs=1e-6)
            assert recomp["ci95_high"] == pytest.approx(rb["score_regret_vs_solver"]["ci95_high"], abs=1e-6)
            dc = rb["decomposition"]
            total_parts = (
                dc["both_correct_v_gap_regret"]
                + dc["wrong_accuse_asymmetry_regret"]
                + dc["abstention_asymmetry_regret"]
            )
            assert total_parts == pytest.approx(rb["score_regret_vs_solver"]["mean"], abs=1e-5)

    for pk in mod.TRAINED_POLICIES:
        assert reg[pk]["overall"]["score_regret_vs_solver"]["mean"] < 0.08
        assert (
            reg[pk]["by_tier"]["hard"]["score_regret_vs_solver"]["mean"]
            < reg["heuristic_hard_elim"]["by_tier"]["hard"]["score_regret_vs_solver"]["mean"] - 0.50
        )


def test_seed_guards_live_single_seed_decomposition_and_tamper_detection(tmp_path: Path) -> None:
    for bad_tr_start, bad_tr_stop in ((0, 5), (800_000, 800_005), (900_000, 900_005)):
        with pytest.raises(ValueError):
            mod.assert_strict_train_range(bad_tr_start, bad_tr_stop)

    for bad_eval in ([0], [29], [102_000], [900_000], [800_000, 800_000]):
        with pytest.raises(ValueError):
            mod.assert_strict_heldout_seeds(bad_eval)

    live_slice = mod.run_delayed_leak_noise_audit(
        repo_root=REPO_ROOT,
        heldout_seeds=[800_000],
        heldout_secret=mod.HELDOUT_WORLD_SECRET,
        workers=1,
    )
    assert live_slice["replay_verified"] is True
    assert live_slice["invalid_episodes"] == 0
    assert live_slice["episodes_verified"] == 15

    prev_sec = os.environ.get("CANARY_WORLD_SECRET")
    try:
        os.environ["CANARY_WORLD_SECRET"] = mod.HELDOUT_WORLD_SECRET
        bundle = mod.load_trained_policy_bundle(repo_root=REPO_ROOT)
        pol = mod.build_policy_instance("compact_linear_dagger", 800_000, bundle)
        ep = run_episode(Env("easy", 800_000), pol)
        assert mod.verify_episode(ep) is True

        tampered = copy.deepcopy(ep)
        tampered.score = float(ep.score) - 0.25
        with pytest.raises(AssertionError, match="replay terminal mismatch"):
            mod.verify_episode(tampered)
    finally:
        if prev_sec is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_sec

    bad_json = tmp_path / "summary.json"
    bad_md = tmp_path / "rep.md"
    bad_json.write_text(SUMMARY_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    bad_md.write_text(REPORT_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    verdict_sib = mod.verify_audit_artifacts(summary_path=bad_json, report_path=bad_md, repo_root=REPO_ROOT)
    assert verdict_sib["passed"] is False
    assert any("disjointness violation" in e for e in verdict_sib["errors"])
