from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import shutil
import sys
import time
import tokenize

import pytest

import scripts.tiebreak_dagger_mechanism_audit as mod
import scripts.tiebreak_experiment_ledger as ledger_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_dagger_mechanism_audit.py"
SUMMARY_JSON_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "dagger_mechanism" / "dagger_mechanism_summary.json"
)
REPORT_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_dagger_mechanism.md"
SELF_PATH = Path(__file__).resolve()


def test_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    unicode_minus = chr(0x2212)
    forbidden_imports = {"torch", "transformers", "peft", "vllm", "google", "openai"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert unicode_minus not in src
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    assert SUMMARY_JSON_PATH.is_file()
    assert REPORT_MD_PATH.is_file()
    assert not (SUMMARY_JSON_PATH.parent / "summary.json").exists()

    for art in (SUMMARY_JSON_PATH, REPORT_MD_PATH):
        txt = art.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert unicode_minus not in txt


def test_seed_hygiene_and_train_only_guards() -> None:
    jobs = mod.build_train_jobs()
    assert len(jobs) == 45
    seeds = [s for _, s in jobs]
    assert seeds == list(range(108_000, 108_045))
    assert len(set(seeds)) == 45
    for tier in ("easy", "medium", "hard"):
        assert sum(1 for t, _ in jobs if t == tier) == 15

    for bad_seed in (0, 29, 9999, 99_999, 200_000, 800_000, 800_059, 900_000):
        with pytest.raises(ValueError):
            mod.assert_train_only_seed(bad_seed)

    data = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    assert data["train_seed_range"] == "108000..108044"
    assert data["train_seeds_unique_count"] == 45
    assert data["episodes_per_tier"] == 15
    iso = data["seed_isolation"]
    assert iso["train_only_verified"] is True
    assert iso["heldout_episodes_touched_in_train_measurement"] == 0
    assert iso["dev_episodes_touched"] == 0
    assert iso["judge_episodes_touched"] == 0
    assert "post-hoc locked, not pre-registered" in iso["panel_fix_a_disclosure"]


def test_qwen25_plant_canary_token_formula_and_x2_cap96_truncation() -> None:
    templates = mod.build_roster_template_stats()
    assert templates["easy"]["full_roster_call"]["qwen_tokens"] == 125
    assert templates["medium"]["full_roster_call"]["qwen_tokens"] == 189
    assert templates["hard"]["full_roster_call"]["qwen_tokens"] == 349
    assert templates["easy"]["balanced_uniform_call"]["qwen_tokens"] == 101
    assert templates["medium"]["balanced_uniform_call"]["qwen_tokens"] == 149
    assert templates["hard"]["balanced_uniform_call"]["qwen_tokens"] == 269

    small_8 = {f"e{i:02d}": "ABC"[i % 3] for i in range(8)}
    args_8 = {"doc_title": "Board memo draft 1", "assignment": small_8}
    assert mod.estimate_qwen_plant_canary_tokens(args_8) == 93

    small_9 = {f"e{i:02d}": "ABC"[i % 3] for i in range(9)}
    args_9 = {"doc_title": "Board memo draft 1", "assignment": small_9}
    assert mod.estimate_qwen_plant_canary_tokens(args_9) == 101

    data = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    bt = data["token_cap_audit"]["by_tier"]

    for tier, n_emp in (("easy", 12), ("medium", 20), ("hard", 40)):
        assert bt[tier]["n_employees"] == n_emp
        assert bt[tier]["episodes_measured"] == 15
        assert bt[tier]["full_roster_template"]["exceeds_cap96"] is True
        assert bt[tier]["dagger_student_state_relabel"]["exceed_cap256_count"] == 0
        assert bt[tier]["solver_trajectory_all_days"]["exceed_cap256_count"] == 0

    assert bt["hard"]["full_roster_template"]["exceeds_cap256"] is True
    assert bt["hard"]["dagger_student_state_relabel"]["exceed_cap96_rate"] > 0.60
    assert bt["hard"]["solver_trajectory_days_1_to_5"]["exceed_cap96_rate"] > 0.60

    c_contrast = data["token_cap_audit"]["compact_action_parameterization_contrast"]
    assert c_contrast["compact_linear_dagger_generated_json_tokens"] == 0
    assert c_contrast["tiny_mlp_dagger_generated_json_tokens"] == 0


def test_stopping_calibration_contrast_and_cross_track_claims() -> None:
    data = json.loads(SUMMARY_JSON_PATH.read_text(encoding="utf-8"))
    sc_all = data["stopping_calibration_contrast"]["all"]
    assert sc_all["n_episodes"] == 45
    assert sc_all["daily_decision_states"] >= 250
    assert sc_all["below_breakeven_rate"] > 0.70

    unc = sc_all["uncalibrated_sft"]
    cal = sc_all["ev_calibrated_breakeven"]
    assert unc["positive_commit_rate"] > 0.50
    assert unc["negative_ev_commit_instances"] > 0
    assert cal["positive_commit_rate"] < 0.25
    assert cal["negative_ev_commit_instances"] == 0
    assert cal["dagger_wrong_commit_penalty_weight"] == 3.0

    ct = data["cross_track_dagger_comparison"]
    rq = ct["raw_qwen_dagger_r1"]
    assert rq["is_open_weight_llm"] is True
    assert rq["expert_state_agreement_before"] == pytest.approx(0.43)
    assert rq["expert_state_agreement_after"] == pytest.approx(0.68)
    assert rq["eval_8k"]["n"] == 50
    assert rq["eval_8k"]["mean_score"] == pytest.approx(-0.542)
    assert rq["eval_8k"]["ci95"] == pytest.approx(0.214)
    assert rq["eval_8k"]["whom_precision_before_8k"] == pytest.approx(0.10)
    assert rq["eval_8k"]["whom_precision_after_8k"] == pytest.approx(0.22)
    assert rq["eval_8k"]["accused_rate"] == pytest.approx(0.92)
    assert rq["eval_4k"]["n"] == 41
    assert rq["eval_4k"]["mean_score"] == pytest.approx(-0.101)
    assert rq["eval_4k"]["ci95"] == pytest.approx(0.112)

    cl = ct["structured_compact_dagger"]["compact_linear_dagger"]
    assert cl["is_open_weight_llm"] is False
    assert cl["dagger_r2_minus_calibrated_bc"]["mean_delta"] == pytest.approx(0.1505, abs=1e-4)
    assert cl["dagger_r2_minus_calibrated_bc"]["ci95_low"] == pytest.approx(0.0869, abs=1e-4)
    assert cl["dagger_r2_minus_calibrated_bc"]["ci95_high"] == pytest.approx(0.2141, abs=1e-4)

    tm = ct["structured_compact_dagger"]["tiny_mlp_dagger"]
    assert tm["is_open_weight_llm"] is False
    assert tm["dagger_r2_minus_uncalibrated_sft"]["mean_delta"] == pytest.approx(0.8922, abs=1e-4)
    assert tm["dagger_r2_minus_uncalibrated_sft"]["ci95_low"] == pytest.approx(0.7556, abs=1e-4)
    assert tm["dagger_r2_minus_uncalibrated_sft"]["ci95_high"] == pytest.approx(1.0288, abs=1e-4)


def test_offline_check_cli_speed_tamper_detection_and_ledger_disjointness(tmp_path: Path) -> None:
    t0 = time.perf_counter()
    rc = mod.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 10.0

    rel_files = [
        "scripts/tiebreak_dagger_mechanism_audit.py",
        "tests/test_tiebreak_dagger_mechanism.py",
        "results/tiebreak/experiment_ledger.json",
        "results/tiebreak/dagger_ablation/summary.json",
        "results/tiebreak/neural_mlp_dagger/mlp_summary.json",
        "results/tiebreak/dagger_mechanism/dagger_mechanism_summary.json",
        "docs/reports/tiebreak_dagger_mechanism.md",
    ]
    for rel in rel_files:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    t1 = time.perf_counter()
    assert mod.main(["--root", str(tmp_path), "--check"]) == 0
    assert (time.perf_counter() - t1) < 10.0

    bad_md = tmp_path / "docs" / "reports" / "tiebreak_dagger_mechanism.md"
    orig_md = bad_md.read_text(encoding="utf-8")
    bad_md.write_text(orig_md.replace("-0.542 +/- 0.214", "-0.123 +/- 0.214"), encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    bad_md.write_text(orig_md, encoding="utf-8")

    bad_json = tmp_path / "results" / "tiebreak" / "dagger_mechanism" / "dagger_mechanism_summary.json"
    j_obj = json.loads(bad_json.read_text(encoding="utf-8"))
    j_obj["token_cap_audit"]["by_tier"]["hard"]["dagger_student_state_relabel"]["exceed_cap96_rate"] = 0.25
    bad_json.write_text(json.dumps(j_obj, indent=2) + "\n", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1

    assert ledger_mod.main(["--check"]) == 0
