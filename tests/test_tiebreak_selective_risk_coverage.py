from __future__ import annotations

import ast
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

import scripts.tiebreak_selective_risk_coverage_audit as tsrc

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)
_IMPORT_DELTA_SOLVER = (
    frozenset(m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver."))
    - _BEFORE_IMPORT_SOLVER
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_selective_risk_coverage_audit.py"
SUMMARY_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "selective_risk_coverage" / "selective_risk_summary.json"
)
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_selective_risk_coverage.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_policy_isolation() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers", "subprocess"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        errs = tsrc.check_python_source_hygiene(py_path, run_tokenize=(py_path == SELF_PATH))
        assert errs == [], errs
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()

    self_toks = list(tokenize.generate_tokens(io.StringIO(SELF_PATH.read_text(encoding="utf-8")).readline))
    assert not [t for t in self_toks if t.type == tokenize.COMMENT]

    self_tree = ast.parse(SELF_PATH.read_text(encoding="utf-8"), filename=str(SELF_PATH))
    for node in ast.walk(self_tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden_roots
                assert not alias.name.startswith(("canary.solver", "canary.world"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_roots
            assert not node.module.startswith(("canary.solver", "canary.world"))
            if node.module == "canary":
                imported = {a.name for a in node.names}
                assert "solver" not in imported
                assert "world" not in imported

    assert _IMPORT_DELTA_HEAVY == frozenset()
    assert _IMPORT_DELTA_SOLVER == frozenset()

    import scripts.verify_tiebreak_submission as vts

    ast_errs, ast_classes = vts._audit_policy_module_ast(
        "scripts/tiebreak_selective_risk_coverage_audit.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    assert "scripts/tiebreak_selective_risk_coverage_audit.py:ConformalEmpiricalBayesPolicy" in ast_classes


def test_check_cli_json_mode_and_selective_conformal_invariants(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) < tsrc.MAX_SUMMARY_BYTES
    assert len(raw_bytes) < 75 * 1024

    t0 = time.perf_counter()
    rc_human = tsrc.main(["--check"])
    dt = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt < 10.0
    assert "OK: verified" in out_human
    assert "845/845 replays" in out_human
    assert "16/16 positive CIs" in out_human

    rc_json = tsrc.main(["--check", "--json"])
    verdict = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert verdict["schema"] == tsrc.SCHEMA_VERSION
    assert verdict["passed"] is True
    assert verdict["errors"] == []
    assert verdict["elapsed_seconds"] < 10.0

    assert tsrc.verify_artifacts(REPO_ROOT) == {"passed": True, "errors": []}

    raw_json = raw_bytes.decode("utf-8")
    md_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert raw_json.isascii()
    assert md_txt.isascii()

    summary = json.loads(raw_json)
    assert md_txt == tsrc.render_markdown_report(summary)
    assert tsrc._scan_json_for_judge_numbers(summary, raw_json) == []
    for tok_match in re.finditer(r"\b\d{6,}\b", raw_json):
        prefix2 = raw_json[max(0, tok_match.start() - 2) : tok_match.start()]
        if prefix2.lower() != "0x":
            assert int(tok_match.group(0)) < 900_000

    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["calibration_train_seed_range"] == "109600..109629"
    assert summary["train_seed_range"] == "109600..109629"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["calibration_episodes"] == 90
    assert summary["heldout_episodes"] == 90
    assert summary["alpha_targets"] == [0.02, 0.05, 0.1, 0.2]
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["judge_episodes_touched"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["calibration_policy_train_overlap"] == 0
    assert iso["calibration_heldout_overlap"] == 0
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]

    pe = summary["panel_fix_e_track_separation"]
    assert pe["compact_policies_are_open_weight_llm"] is False
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["readme_qwen_addendum_status"] == "HOLD_README_QWEN_ADDENDUM_UNTIL_V100"

    t1 = summary["track1_llm_extremes"]
    v2 = t1["ws4_v2_blind_over_coverage"]
    s2 = t1["ws4_v3_8k_s2_dbd0"] if "ws4_v3_8k_s2_dbd0" in t1 else t1["ws4_v3_8k_s2_under_coverage"]
    assert v2["is_open_weight_llm"] is True
    assert v2["coverage"] == pytest.approx(0.55, abs=1e-3)
    assert v2["conditional_error_rate"] == pytest.approx(0.91, abs=1e-3)
    assert v2["mean_score"] == pytest.approx(-0.457, abs=1e-4)
    assert s2["is_open_weight_llm"] is True
    assert s2["coverage"] == pytest.approx(0.07, abs=1e-3)
    assert s2["abstain_rate"] == pytest.approx(0.93, abs=1e-3)
    assert s2["mean_score"] == pytest.approx(-0.05, abs=1e-4)

    heur = summary["uncalibrated_heuristic_baseline"]
    assert heur["coverage"] == 1.0
    assert heur["false_accuse_rate"] > 0.20

    totals = summary["totals"]
    assert totals["trained_policies_audited"] == 4
    assert totals["conformal_cells_total"] == 16
    assert totals["conformal_cells_positive_score_ci95"] == 16
    assert totals["conformal_cells_within_1se_bound"] == 16
    assert totals["conformal_cells_exact_le_alpha"] >= 15

    for pid in tsrc.TRAINED_POLICY_ORDER:
        pb = summary["policies"][pid]
        assert pb["is_open_weight_llm"] is False
        assert pb["replay_verified"] is True
        assert pb["invalid_episodes"] == 0
        sc = pb["selective_curve"]
        assert 0.0 <= sc["oracle_aurc"] <= sc["aurc"] < 0.01
        assert sc["excess_aurc"] < 0.005
        assert sc["ausc"] > 0.34
        assert sc["peak_net_score"] >= pb["forced_full_coverage_point"]["mean_score"]
        assert pb["native_operating_point"]["paired_vs_heuristic"]["ci95_low"] > 0.0

        prev_cov = 0.0
        for a_key, alpha in zip(tsrc.ALPHA_KEYS, tsrc.ALPHA_TARGETS):
            crow = pb["conformal_abstention"][a_key]
            assert crow["conformal_crc_upper_bound"] <= alpha + 1e-12
            assert crow["heldout_ci95_low"] > 0.0
            assert crow["within_finite_sample_1se"] is True
            assert crow["heldout_coverage"] >= prev_cov - 1e-12
            prev_cov = crow["heldout_coverage"]


def test_shallow_ci_gitless_archive_and_tamper_guards(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_judge_export"
    for rel in (
        "results/tiebreak/selective_risk_coverage/selective_risk_summary.json",
        "docs/reports/tiebreak_selective_risk_coverage.md",
        "results/tiebreak/experiment_ledger.json",
    ):
        dst = no_git_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    assert not (no_git_root / ".git").exists()
    monkeypatch.setenv("PATH", "")

    t0 = time.perf_counter()
    assert tsrc.main(["--check", "--repo-root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t0) < 10.0
    _ = capsys.readouterr()

    (no_git_root / ".git").mkdir()
    (no_git_root / ".git" / "shallow").write_text("e9802f15\n", encoding="utf-8")
    (no_git_root / ".git" / "HEAD").write_text("e9802f15\n", encoding="utf-8")
    t1 = time.perf_counter()
    assert tsrc.main(["--check", "--root", str(no_git_root)]) == 0
    assert (time.perf_counter() - t1) < 10.0
    _ = capsys.readouterr()

    for bad_name in ("summary.json", "table.md"):
        forbidden_sib = no_git_root / "results" / "tiebreak" / "selective_risk_coverage" / bad_name
        forbidden_sib.write_text("{}\n", encoding="utf-8")
        assert tsrc.main(["--check", "--repo-root", str(no_git_root)]) == 1
        assert "forbidden sibling" in capsys.readouterr().err
        forbidden_sib.unlink()

    md_copy = no_git_root / "docs" / "reports" / "tiebreak_selective_risk_coverage.md"
    orig_md = md_copy.read_text(encoding="utf-8")
    md_copy.write_text(
        orig_md + "\nPre-registered seeds 0..29 claim.\nBad " + chr(0x2014) + " dash.\n",
        encoding="utf-8",
    )
    assert tsrc.main(["--check", "--repo-root", str(no_git_root)]) == 1
    err_md = capsys.readouterr().err
    assert "Panel Fix A" in err_md
    assert "em dash" in err_md
    md_copy.write_text(orig_md, encoding="utf-8")

    json_copy = no_git_root / "results" / "tiebreak" / "selective_risk_coverage" / "selective_risk_summary.json"
    bad_summary = json.loads(json_copy.read_text(encoding="utf-8"))
    bad_summary["leaked_judge_seed"] = 900_000
    json_copy.write_text(json.dumps(bad_summary, indent=2) + "\n", encoding="utf-8")
    assert tsrc.main(["--check", "--repo-root", str(no_git_root)]) == 1
    assert "900000" in capsys.readouterr().err


def test_conformal_policy_wrapper_and_spot_replay_parity() -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    fn_solver = {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}

    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    from train.empirical_bayes_policy import EmpiricalBayesParams
    import scripts.run_tiebreak_policy as rtp

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    eb_sum = json.loads((REPO_ROOT / "results/tiebreak/empirical_bayes/summary.json").read_text(encoding="utf-8"))
    eb_opt = EmpiricalBayesParams.from_dict(eb_sum["parameters"]["eb_experience_opt"])
    provider = TemplateProvider()

    with tsrc._scoped_world_secret(tsrc.HELDOUT_WORLD_SECRET):
        env_open = Env("easy", 800_000, text_provider=provider)
        spec, instr = env_open.tools_spec(), env_open.instruction()
        pol_open = tsrc.ConformalEmpiricalBayesPolicy(params=eb_opt, tau_margin=0.0, seed=800_000)
        ep_open = run_episode(env_open, pol_open)
        rtp.verify_episode_replay(ep_open, text_provider=provider)

        spot_eb = summary["policies"]["empirical_bayes"]["spot_easy_800000"]
        assert ep_open.accused == spot_eb["suspect"]
        assert bool(ep_open.correct) is spot_eb["native_correct"]
        assert round(float(ep_open.score), 5) == pytest.approx(spot_eb["native_score"], abs=1e-5)

        pre_steps = [s for s in ep_open.steps if s.tool != "accuse"]
        emp, p_top, be_p, margin = tsrc.extract_policy_margin(
            "empirical_bayes", pol_open, pre_steps, spec, instr, str(ep_open.accused)
        )
        assert emp == spot_eb["suspect"]
        assert p_top == pytest.approx(spot_eb["p_top"], abs=1e-5)
        assert be_p == pytest.approx(spot_eb["breakeven_p"], abs=1e-5)
        assert margin == pytest.approx(spot_eb["margin"], abs=1e-5)

        pol_strict = tsrc.ConformalEmpiricalBayesPolicy(params=eb_opt, tau_margin=0.99, seed=800_000)
        pol_strict.reset(spec, instr)
        pol_strict.tracker.ingest_steps(pre_steps)
        pol_strict.planned_day = pol_strict.tracker.today
        pol_strict.queue = [("__decide__", {})]
        assert pol_strict.act(pre_steps) == ("advance_day", {})

    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()
    assert (
        {m for m in sys.modules if m == "canary.solver" or m.startswith("canary.solver.")}
        - fn_solver
    ) == set()
