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

import scripts.tiebreak_learning_curve as tlc

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_learning_curve.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "learning_curve" / "learning_curve_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_learning_curve.md"
SELF_PATH = Path(__file__).resolve()


def test_check_cli_and_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    rc_human = tlc.main(["--check"])
    dt_human = time.perf_counter() - t0
    out_human = capsys.readouterr().out
    assert rc_human == 0
    assert dt_human < 10.0
    assert "OK: verified" in out_human
    assert "K=3 learning curve, 0 AST/seed leaks" in out_human

    rc_json = tlc.main(["--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["schema"] == tlc.SCHEMA_VERSION
    assert payload["passed"] is True
    assert payload["errors"] == []
    assert payload["elapsed_seconds"] < 10.0

    v_res = tlc.verify_artifacts(REPO_ROOT)
    assert v_res == {"passed": True, "errors": []}


def test_shallow_ci_git_free_root_and_negative_guards(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    no_git_root = tmp_path / "unzipped_no_git"
    sub_json = no_git_root / tlc.DEFAULT_OUT_JSON
    sub_md = no_git_root / tlc.DEFAULT_OUT_MD
    sub_json.parent.mkdir(parents=True, exist_ok=True)
    sub_md.parent.mkdir(parents=True, exist_ok=True)
    sub_json.write_bytes(SUMMARY_PATH.read_bytes())
    sub_md.write_bytes(REPORT_PATH.read_bytes())

    assert not (no_git_root / ".git").exists()
    rc_ok = tlc.main(["--check", "--root", str(no_git_root), "--json"])
    res_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert res_ok["passed"] is True

    shallow_root = tmp_path / "shallow_detached_ci"
    shutil.copytree(no_git_root, shallow_root)
    (shallow_root / ".git").mkdir()
    (shallow_root / ".git" / "shallow").write_text("c3ff6c08a3f6c335b75a7bcfc75a1a6af18e535e\n", encoding="utf-8")
    (shallow_root / ".git" / "HEAD").write_text("c3ff6c08a3f6c335b75a7bcfc75a1a6af18e535e\n", encoding="utf-8")
    rc_sh = tlc.main(["--check", "--repo-root", str(shallow_root), "--json"])
    res_sh = json.loads(capsys.readouterr().out)
    assert rc_sh == 0
    assert res_sh["passed"] is True

    forbidden_sib = shallow_root / tlc.DEFAULT_OUT_JSON.parent / "summary.json"
    forbidden_sib.write_text("{}\n", encoding="utf-8")
    errs_sib = tlc.verify_committed_artifacts(repo_root=shallow_root)
    assert any("forbidden sibling artifact" in e for e in errs_sib)
    forbidden_sib.unlink()

    with pytest.raises(ValueError, match="900000"):
        tlc.sanitize_json_numbers({"judge_leak": 900_005})

    sh_json = shallow_root / tlc.DEFAULT_OUT_JSON
    sh_md = shallow_root / tlc.DEFAULT_OUT_MD
    mutated = json.loads(sh_json.read_text(encoding="utf-8"))
    mutated["leaked_judge_id"] = 900_005
    sh_json.write_text(json.dumps(mutated, indent=2) + "\n", encoding="utf-8")
    errs_judge = tlc.verify_committed_artifacts(repo_root=shallow_root)
    assert any("900000" in e for e in errs_judge)
    sh_json.write_bytes(SUMMARY_PATH.read_bytes())

    sh_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8") + "\nPre-registered seeds 0..29 check.\n",
        encoding="utf-8",
    )
    errs_prereg = tlc.verify_committed_artifacts(repo_root=shallow_root)
    assert any("Panel Fix A" in e for e in errs_prereg)

    sh_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8").replace("+0.47974", "+0.99999", 1),
        encoding="utf-8",
    )
    errs_sync = tlc.verify_committed_artifacts(repo_root=shallow_root)
    assert any("out of sync" in e for e in errs_sync)


def test_scientific_invariants_crossover_and_track_separation() -> None:
    raw_bytes = SUMMARY_PATH.read_bytes()
    assert len(raw_bytes) <= tlc.MAX_SUMMARY_BYTES
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    raw_json = raw_bytes.decode("utf-8")
    int_tokens = [int(m.group(0)) for m in re.finditer(r"\b\d+\b", raw_json)]
    assert all(tok < 900_000 for tok in int_tokens)

    summary = json.loads(raw_json)
    assert summary["schema"] == tlc.SCHEMA_VERSION
    assert summary["tiers"] == ["easy", "medium", "hard"]
    assert summary["train_seed_range"] == "110000..111499"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["eval_seed_range"] == "800000..800029"
    assert summary["episodes_per_eval"] == 90
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0

    iso = summary["seed_isolation"]
    assert iso["heldout_world_paired"] is True
    assert iso["folds_pairwise_disjoint"] is True
    assert iso["unique_train_episodes_rolled_out"] == 864
    assert iso["heldout_episodes_rolled_out"] == 1710
    assert iso["fresh_env_replays_verified"] == 1710
    assert iso["train_episodes_in_heldout_eval"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["judge_episodes_touched"] == 0

    pe = summary["panel_fix_e_track_separation"]
    assert pe["open_weight_qwen25_runs_total"] == 19
    assert pe["open_weight_qwen25_runs_above_zero"] == 0
    assert pe["open_weight_qwen25_above_zero_ratio"] == "0 / 19"
    assert pe["qwen25_dagger_r1_relabelled_states"] == 24074
    assert pe["non_llm_policies_is_open_weight_llm"] is False

    eb = summary["empirical_bayes_curve"]
    assert eb["policy_class"] == "EmpiricalBayesPolicy"
    assert eb["param_count"] == 11
    assert eb["is_open_weight_llm"] is False
    assert eb["k_folds"] == 3
    assert eb["fold_seed_ranges"] == ["110000..110287", "110500..110787", "111000..111287"]
    assert eb["before_naive_prior"]["n"] == 90
    assert eb["before_naive_prior"]["mean_score"] == pytest.approx(-0.38567, abs=1e-4)

    budgets = eb["budgets"]
    assert [b["n_train"] for b in budgets] == [9, 18, 36, 72, 144, 288]
    for b in budgets:
        assert b["k_folds"] == 3
        assert b["param_count"] == 11
        assert b["all_folds_paired_ci95_gt_zero"] is True
        assert b["all_folds_after_ci95_gt_zero"] is True
        assert b["min_fold_paired_ci95_low_vs_naive"] > 0.0
        assert b["min_fold_after_ci95_low"] > 0.0
        if b["n_train"] >= 18:
            assert b["min_fold_hard_ci95_low"] > 0.0

    cross = summary["crossover_summary"]
    assert cross["empirical_bayes_11p_paired_vs_naive_n_train"] == 9
    assert cross["empirical_bayes_11p_after_gt_zero_n_train"] == 9
    assert cross["empirical_bayes_11p_hard_tier_gt_zero_n_train"] == 18
    assert cross["scaling_logistic_82p_pooled_gt_zero_n_train"] == 15
    assert cross["scaling_logistic_82p_all_tiers_hard_gt_zero_n_train"] == 60
    assert cross["scaling_logistic_82p_score_gt_060_n_train"] == 900

    sc_ref = summary["scaling_logistic_82p_reference"]
    sc_by_n = {pt["n_train"]: pt for pt in sc_ref["curve"]}
    assert sc_by_n[15]["mean_score"] == pytest.approx(0.32878, abs=1e-4)
    assert sc_by_n[15]["hard_tier_mean_score"] == 0.0
    assert sc_by_n[60]["hard_tier_ci95_low"] > 0.30
    assert sc_by_n[900]["mean_score"] == pytest.approx(0.61067, abs=1e-4)

    arch = summary["architecture_comparison"]
    non_llm = [r for r in arch if not r["is_open_weight_llm"]]
    llm = [r for r in arch if r["is_open_weight_llm"]]
    assert len(non_llm) == 4
    assert len(llm) == 1
    assert [r["param_count"] for r in non_llm] == [11, 82, 785, 12293]
    assert all(r["passed_panel_fix_e_bar"] is True for r in non_llm)
    assert llm[0]["runs_above_zero"] == 0
    assert llm[0]["max_relabelled_states"] == 24074
    assert llm[0]["passed_panel_fix_e_bar"] is False


def test_live_spot_replay_closed_form_fit_and_ast_isolation() -> None:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.text.template import TemplateProvider
    import scripts.run_tiebreak_policy as rtp
    import scripts.verify_tiebreak_submission as vts
    from train.empirical_bayes_policy import (
        EmpiricalBayesParams,
        EmpiricalBayesPolicy,
        make_naive_prior_params,
    )

    ast_errs, ast_classes = vts._audit_policy_module_ast(
        "scripts/tiebreak_learning_curve.py",
        SCRIPT_PATH,
    )
    assert ast_errs == []
    assert "scripts/tiebreak_learning_curve.py:SinglePassExperiencePolicy" in ast_classes

    provider = TemplateProvider()
    tlc._WORKER_STATE.clear()
    tlc._WORKER_STATE["tp"] = provider

    tr_rec = tlc._run_train_task(("easy", 110_000, 0.55, 4, 6))
    fitted_params, fit_meta = tlc.fit_eb_on_fold_budget([tr_rec], [tr_rec], n_train=2, fold_idx=0)
    assert fit_meta["n_llr_episodes"] == 1
    assert fit_meta["n_stop_episodes"] == 1
    p_dict = fitted_params.to_dict()
    scalar_vals = [v for k, v in p_dict.items() if k not in ("stage", "naive_p_threshold", "use_ev_stopping")]
    assert len(scalar_vals) == 10
    assert all(isinstance(v, (int, float)) for v in scalar_vals)

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    b144_f0 = next(b for b in summary["empirical_bayes_curve"]["budgets"] if b["n_train"] == 144)["folds"][0]
    lp = b144_f0["learned_params"]
    committed_params = EmpiricalBayesParams(
        w_canary_hit=float(lp["w_canary_hit"]),
        w_canary_miss=float(lp["w_canary_miss"]),
        w_doc_hit=float(lp["w_doc_hit"]),
        w_after_hours=float(lp["w_after_hours"]),
        w_evasive=float(lp["w_evasive"]),
        w_angry_msg=float(lp["w_angry_msg"]),
        tau_margin=float(lp["tau_margin"]),
        unsurfaced_v_discount=float(lp["unsurfaced_v_discount"]),
        canary_coverage=float(lp["canary_coverage"]),
        tiny_pool_size=int(lp["tiny_pool_size"]),
        use_ev_stopping=bool(lp["use_ev_stopping"]),
        stage="spot_b144_f0",
    )
    naive_params = make_naive_prior_params()

    with tlc._scoped_world_secret(tlc.HELDOUT_WORLD_SECRET):
        ep_naive = run_episode(
            Env("hard", 800_000, text_provider=provider),
            EmpiricalBayesPolicy(params=naive_params, seed=800_000, name="spot_naive"),
        )
        rtp.verify_episode_replay(ep_naive, text_provider=provider)

        ep_after = run_episode(
            Env("hard", 800_000, text_provider=provider),
            EmpiricalBayesPolicy(params=committed_params, seed=800_000, name="spot_b144_f0"),
        )
        rtp.verify_episode_replay(ep_after, text_provider=provider)
        assert float(ep_after.score) > float(ep_naive.score)


def test_source_and_report_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        assert src.isascii()
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        tree = ast.parse(src, filename=str(py_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
                    assert not alias.name.startswith(("canary.solver", "canary.world"))
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots
                assert not node.module.startswith(("canary.solver", "canary.world"))

    for text_path in (SUMMARY_PATH, REPORT_PATH):
        txt = text_path.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert unicode_minus not in txt
        assert txt.isascii()

    assert _IMPORT_DELTA_HEAVY == frozenset()
