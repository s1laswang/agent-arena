from __future__ import annotations

import ast
import json
from pathlib import Path
import re
import shutil
import sys
import time

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)
_BEFORE_IMPORT_SOLVER = frozenset(
    m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")
)

import scripts.tiebreak_stopping_counterfactual_audit as tsca

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_stopping_counterfactual_audit.py"
SUMMARY_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "stopping_counterfactual" / "stopping_counterfactual_summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_stopping_counterfactual.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_cross_test_safe_ast_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_test_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tsca.check_python_source_hygiene(py_path, run_tokenize=True)
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    assert tsca.audit_module_ast_isolation(SCRIPT_PATH)["passed"] is True
    test_tree = ast.parse(SELF_PATH.read_text(encoding="utf-8"), filename=str(SELF_PATH))
    for node in ast.walk(test_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_test_roots
                assert not alias.name.startswith(("canary.solver", "canary.world"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_test_roots
            assert not node.module.startswith(("canary.solver", "canary.world"))
            if node.module == "canary":
                imported = {a.name for a in node.names}
                assert "solver" not in imported
                assert "world" not in imported

    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, checked_list = vts._audit_policy_module_ast(
        "scripts/tiebreak_stopping_counterfactual_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    checked = set(checked_list)
    assert "scripts/tiebreak_stopping_counterfactual_audit.py:StoppingCounterfactualPolicy" in checked
    assert (
        "scripts/tiebreak_stopping_counterfactual_audit.py:StoppingCounterfactualEmpiricalBayesPolicy"
        in checked
    )
    assert (
        "scripts/tiebreak_stopping_counterfactual_audit.py:StoppingCounterfactualCompactLinearDAggerPolicy"
        in checked
    )


def test_check_cli_json_regret_decomposition_and_cross_links(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tsca.MAX_SUMMARY_BYTES

    t0 = time.perf_counter()
    rc_default = tsca.main([])
    dt = time.perf_counter() - t0
    out_default = capsys.readouterr().out
    assert rc_default == 0
    assert dt < 30.0
    assert "OK: verified" in out_default
    assert "1080 episodes" in out_default

    rc_json = tsca.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tsca.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 30.0

    assert tsca.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    summary = json.loads(raw_json)
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert md_txt == tsca.render_markdown_report(summary)
    assert tsca._scan_json_for_judge_numbers(summary, raw_json) == []
    for dig_match in re.finditer(r"\d+", raw_json):
        assert int(dig_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["episodes_per_rule"] == 90
    assert summary["stopping_rules"] == list(tsca.STOPPING_RULE_ORDER)

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_rolled_out"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"
    assert pe["audited_policies_are_open_weight_llm"] is False

    for pid, expected_params, expected_cal in (
        ("empirical_bayes", 11, 0.62233),
        ("compact_linear_dagger", 785, 0.66322),
    ):
        pb = summary["policies"][pid]
        assert pb["is_open_weight_llm"] is False
        assert pb["param_count"] == expected_params
        rmap = pb["rules"]
        assert rmap["calibrated_ev_breakeven"]["overall"]["mean_score"] == pytest.approx(
            expected_cal, abs=2e-4
        )
        assert rmap["always_abstain"]["overall"]["mean_score"] == pytest.approx(0.0, abs=1e-6)
        assert rmap["always_abstain"]["overall"]["abstain_count"] == 90
        assert rmap["reckless_p35"]["regret_vs_calibrated"]["total_regret"] > 0.30
        assert rmap["reckless_p35"]["regret_vs_calibrated"]["premature_wrong_accusation_regret"] > 0.35
        assert rmap["uncalibrated_p55"]["regret_vs_calibrated"]["total_regret"] > 0.05
        assert rmap["hyper_conservative_p99"]["regret_vs_calibrated"]["total_regret"] > 0.05

        for rid in tsca.STOPPING_RULE_ORDER:
            rg = rmap[rid]["regret_vs_calibrated"]
            sum_parts = (
                rg["premature_wrong_accusation_regret"]
                + rg["late_stopping_value_leakage_regret"]
                + rg["over_abstention_missed_catch_regret"]
            )
            assert rg["total_regret"] == pytest.approx(sum_parts, abs=2e-4)
            assert rg["decomposition_residual"] == pytest.approx(0.0, abs=1e-7)

    xref = summary["empirical_cross_links"]
    verda_by_id = {r["cohort_id"]: r for r in xref["verda_qwen25_cohorts"]}
    assert verda_by_id["verda_8k_low_step_s1_s3"]["mean_score"] == pytest.approx(-0.7824, abs=1e-3)
    assert verda_by_id["verda_8k_high_step_s0_s2"]["mean_score"] == pytest.approx(-0.0551, abs=1e-3)
    assert verda_by_id["v3_4k_s0"]["mean_score"] == pytest.approx(-0.1474, abs=1e-3)

    fdev = xref["frontier_dev_hard_posthoc"]
    assert fdev["protocol_status"] == "post-hoc locked, not pre-registered"
    f_by_id = {r["cohort_id"]: r for r in fdev["rows"]}
    assert f_by_id["opencode_gemini_4_carbon_hard"]["mean_score"] == pytest.approx(0.3223, abs=1e-3)
    assert f_by_id["opencode_gpt_5_5_hard"]["mean_score"] == pytest.approx(0.5037, abs=1e-3)


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/stopping_counterfactual/stopping_counterfactual_summary.json",
        "docs/reports/tiebreak_stopping_counterfactual.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    assert tsca.main(["--check", "--root", str(no_git_root)]) == 0
    _ = capsys.readouterr()
    assert tsca.main(["--check", "--repo-root", str(no_git_root)]) == 0
    _ = capsys.readouterr()

    shallow_root = no_git_root
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("c445a4ca\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("c445a4ca\n", encoding="utf-8")
    assert tsca.main(["--check", "--root", str(shallow_root)]) == 0
    _ = capsys.readouterr()

    forbidden_sib = shallow_root / "results" / "tiebreak" / "stopping_counterfactual" / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    assert tsca.main(["--check", "--root", str(shallow_root)]) == 1
    assert "forbidden sibling" in capsys.readouterr().err
    forbidden_sib.unlink()

    md_copy = shallow_root / "docs" / "reports" / "tiebreak_stopping_counterfactual.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(orig_md + "\nPre-registered seeds 0..29 claim.\n", encoding="utf-8")
    assert tsca.main(["--check", "--root", str(shallow_root)]) == 1
    assert "Panel Fix A" in capsys.readouterr().err

    md_copy.write_text(orig_md + "\nBad " + chr(0x2014) + " dash.\n", encoding="utf-8")
    assert tsca.main(["--check", "--root", str(shallow_root)]) == 1
    assert "em dash" in capsys.readouterr().err
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = (
        shallow_root / "results" / "tiebreak" / "stopping_counterfactual" / "stopping_counterfactual_summary.json"
    )
    orig_json_txt = json_copy.read_text(encoding="utf-8")
    bad_reg = json.loads(orig_json_txt)
    bad_reg["policies"]["empirical_bayes"]["rules"]["reckless_p35"]["regret_vs_calibrated"]["total_regret"] = 0.0
    json_copy.write_text(json.dumps(bad_reg, indent=2) + "\n", encoding="utf-8")
    assert tsca.main(["--check", "--root", str(shallow_root)]) == 1
    assert "total_regret" in capsys.readouterr().err

    bad_judge = json.loads(orig_json_txt)
    bad_judge["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_judge, indent=2) + "\n", encoding="utf-8")
    assert tsca.main(["--check", "--root", str(shallow_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_stopping_counterfactual_policy_mechanics_and_live_spot_parity() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    from scripts.verify_replay import replay_episode

    with pytest.raises(ValueError):
        tsca.StoppingCounterfactualPolicy("empirical_bayes", stopping_rule="invalid_rule")
    with pytest.raises(ValueError):
        tsca.StoppingCounterfactualPolicy("unknown_policy_kind", stopping_rule="calibrated_ev_breakeven")

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    provider = TemplateProvider()
    eb_fac, eb_meta = tsca.load_policy_factory("empirical_bayes", repo_root=REPO_ROOT)
    cd_fac, cd_meta = tsca.load_policy_factory("compact_linear_dagger", repo_root=REPO_ROOT)
    assert eb_meta["is_open_weight_llm"] is False
    assert cd_meta["is_open_weight_llm"] is False

    spot_cases = (
        ("empirical_bayes", eb_fac, "reckless_p35"),
        ("compact_linear_dagger", cd_fac, "calibrated_ev_breakeven"),
    )
    with tsca._fast_compact_dagger_features(), tsca._scoped_world_secret(tsca.HELDOUT_WORLD_SECRET):
        for pid, fac, rid in spot_cases:
            pol = fac(800_000, stopping_rule=rid, name=f"{pid}:{rid}")
            ep = run_episode(Env("easy", 800_000, text_provider=provider), pol)
            rep_dict = replay_episode(
                {
                    "tier": ep.tier,
                    "seed": ep.seed,
                    "steps": [{"tool": st.tool, "args": st.args} for st in ep.steps],
                }
            )
            assert rep_dict["score"] == pytest.approx(ep.score, abs=1e-9)
            assert rep_dict["accused"] == ep.accused

            rblock = summary["policies"][pid]["rules"][rid]
            expected_score = float(rblock["episode_scores_csv"].split(",")[0])
            expected_oc = rblock["episode_outcomes_csv"].split(",")[0]
            actual_oc = "C" if (ep.correct and ep.accused is not None) else ("W" if ep.accused is not None else "A")
            assert round(float(ep.score), 4) == pytest.approx(expected_score, abs=1e-4)
            assert actual_oc == expected_oc

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
