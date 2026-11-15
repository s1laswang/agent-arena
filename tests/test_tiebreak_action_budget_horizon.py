from __future__ import annotations

import io
import json
from pathlib import Path
import re
import shutil
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)

import scripts.tiebreak_action_budget_horizon_audit as tabha

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_action_budget_horizon_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "action_budget_horizon" / "action_budget_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_action_budget_horizon.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tabha.check_python_source_hygiene(py_path, run_tokenize=(py_path == SELF_PATH))
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    self_toks = list(tokenize.generate_tokens(io.StringIO(SELF_PATH.read_text(encoding="utf-8")).readline))
    assert not [t for t in self_toks if t.type == tokenize.COMMENT]
    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_action_budget_horizon_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    for cls_name in (
        "BudgetCappedEmpiricalBayesPolicy",
        "BudgetCappedScalingLogisticPolicy",
        "BudgetCappedCompactLinearPolicy",
        "BudgetCappedTinyMLPPolicy",
        "BudgetCappedGreedyHeuristicPolicy",
    ):
        assert f"scripts/tiebreak_action_budget_horizon_audit.py:{cls_name}" in checked


def test_check_cli_json_mode_and_anytime_calibration_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tabha.MAX_SUMMARY_BYTES
    assert len(raw_bytes) < 75 * 1024

    t0 = time.perf_counter()
    rc_human = tabha.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < tabha.MAX_CHECK_SECONDS
    assert "OK: verified" in out_human
    assert "2250/2250 replays" in out_human
    assert "20/20 positive CIs" in out_human

    rc_json = tabha.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tabha.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0
    assert tabha.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii() and md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tabha.render_markdown_report(summary)
    assert tabha._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["max_days_caps"] == [3, 5, 7, 10, 21]
    assert summary["episodes_per_cell"] == 90
    assert summary["episodes_per_policy"] == 450
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["compact_policies_are_open_weight_llm"] is False
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"

    totals = summary["totals"]
    assert totals["trained_cells_positive_ci95_vs_heuristic"] == 20
    assert totals["trained_cells_positive_ci95_vs_abstain"] == 20
    assert totals["total_episodes_evaluated"] == 2250
    assert totals["fresh_env_replays_verified"] == 2250
    assert totals["full_parity_episodes_verified"] == 450
    assert totals["post_cap_investigative_calls_total"] == 0

    bkeys = ("3", "5", "7", "10", "21")
    for pid in tabha.TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["is_open_weight_llm"] is False
        assert pb["post_cap_investigative_calls"] == 0
        assert pb["full_parity_verified_episodes"] == 90
        ov_scores = [float(pb["by_max_days"][k]["overall"]["mean_score"]) for k in bkeys]
        can_counts = [float(pb["by_max_days"][k]["overall"]["mean_canaries_planted"]) for k in bkeys]
        assert ov_scores[0] < ov_scores[1] < ov_scores[2] < ov_scores[3] < ov_scores[4]
        assert can_counts[0] < can_counts[1] < can_counts[2] < can_counts[3] < can_counts[4]
        d3_hard = pb["by_max_days"]["3"]["by_tier"]["hard"]
        assert d3_hard["wrong_count"] == 0 and d3_hard["abstain_count"] == 30

    heur = summary["policies"][tabha.BASELINE_POLICY_ID]
    assert heur["trained"] is False
    assert heur["by_max_days"]["3"]["overall"]["mean_score"] < -0.50
    for k in bkeys:
        assert heur["by_max_days"][k]["overall"]["abstain_rate"] == 0.0


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/action_budget_horizon/action_budget_summary.json",
        "docs/reports/tiebreak_action_budget_horizon.md",
        "results/tiebreak/experiment_ledger.json",
        "results/tiebreak/frontier_comparison/comparison_summary.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    t0 = time.perf_counter()
    assert tabha.main(["--check", "--repo-root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t0) < 10.0
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("c445a4ca\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("c445a4ca\n", encoding="utf-8")
    t1 = time.perf_counter()
    assert tabha.main(["--check", "--root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t1) < 10.0
    _ = capsys.readouterr()

    forbidden_sib = no_git_root / "results" / "tiebreak" / "action_budget_horizon" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    md_copy = no_git_root / "docs" / "reports" / "tiebreak_action_budget_horizon.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29. Bad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    json_copy = no_git_root / "results" / "tiebreak" / "action_budget_horizon" / "action_budget_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")

    assert tabha.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_txt = capsys.readouterr().err
    assert "forbidden sibling" in err_txt
    assert "Panel Fix A" in err_txt
    assert "em dash" in err_txt
    assert "900000" in err_txt


def test_live_truncation_contract_and_spot_reproduction() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    eb_opt = tabha.load_eb_observer_params(REPO_ROOT)
    eb_cap, eb_base, _ = tabha.load_budget_policy_factory("empirical_bayes", REPO_ROOT)
    heur_cap, _, _ = tabha.load_budget_policy_factory(tabha.BASELINE_POLICY_ID, REPO_ROOT)

    with tabha._scoped_world_secret(tabha.HELDOUT_WORLD_SECRET):
        for pid, cap_fn, bkey, md_val in (
            ("empirical_bayes", eb_cap, "21", 21),
            (tabha.BASELINE_POLICY_ID, heur_cap, "3", 3),
        ):
            env = Env("easy", 800_000, text_provider=provider)
            spec, instr = env.tools_spec(), env.instruction()
            ep = run_episode(env, cap_fn(md_val, 800_000))
            rtp.verify_episode_replay(ep, text_provider=provider)
            rec = tabha._extract_episode_record(ep, md_val, 14, spec, instr, eb_opt)
            assert rec["post_cap_inv"] == 0
            spot = summary["policies"][pid]["by_max_days"][bkey]["spot_easy_800000"]
            assert round(rec["score"], 5) == pytest.approx(spot["score"], abs=1e-5)
            assert round(rec["public_ev"], 5) == pytest.approx(spot["public_ev"], abs=1e-5)
            assert rec["canaries_planted"] == spot["canaries_planted"]
            if md_val == 21:
                ep_ref = run_episode(Env("easy", 800_000, text_provider=provider), eb_base(800_000))
                assert tabha._canonical_ep_sha(ep) == tabha._canonical_ep_sha(ep_ref)

        ep_h3 = run_episode(Env("hard", 800_000, text_provider=provider), eb_cap(3, 800_000))
        rtp.verify_episode_replay(ep_h3, text_provider=provider)
        assert ep_h3.accused is None and ep_h3.score == 0.0

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert ({m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")} - fn_solver) == set()
