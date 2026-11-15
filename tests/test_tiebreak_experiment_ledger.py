from __future__ import annotations

import ast
import copy
import importlib.util
import io
import json
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_experiment_ledger.py"
EXPORT_PATH = REPO_ROOT / "train" / "export_calibrated_sft.py"
SELF_PATH = Path(__file__).resolve()
LEDGER_JSON_PATH = REPO_ROOT / "results" / "tiebreak" / "experiment_ledger.json"
TRAIN_MANIFEST_PATH = REPO_ROOT / "results" / "tiebreak" / "cal_v14_train_manifest.json"
VAL_MANIFEST_PATH = REPO_ROOT / "results" / "tiebreak" / "cal_v14_val_manifest.json"
REPORT_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_small_model.md"

_SPEC = importlib.util.spec_from_file_location("tiebreak_experiment_ledger", SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
ledger_mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ledger_mod)


def _valid_summary_fixture() -> dict[str, Any]:
    before_scores = [0.0] * 30
    after_scores = [0.65 if i % 4 != 0 else 0.0 for i in range(30)]
    b_mean = round(sum(before_scores) / len(before_scores), 4)
    a_mean = round(sum(after_scores) / len(after_scores), 4)
    return {
        "run_id": "compact-cal-0.5b-v1",
        "model": "Qwen2.5-0.5B-Instruct+compact-cal-LoRA",
        "tiers_version": "v1.4",
        "tiers": ["hard"],
        "train_seeds": {"start": 100_000, "stop": 100_420},
        "eval_seeds": list(range(800_000, 800_030)),
        "n": 30,
        "replay_verified": True,
        "invalid_episodes": 0,
        "error_episodes": 0,
        "before": {
            "n": 30,
            "mean_score": b_mean,
            "valid_call_rate": 0.12,
            "world_secret_tag": "a1b2c3d4e5f60718",
            "scores": before_scores,
            "end_reasons": {"horizon": 30},
        },
        "after": {
            "n": 30,
            "mean_score": a_mean,
            "valid_call_rate": 0.99,
            "world_secret_tag": "a1b2c3d4e5f60718",
            "scores": after_scores,
            "end_reasons": {"accused": 22, "horizon": 8},
        },
        "notes": "Synthetic paired improvement fixture.",
    }


def test_ast_and_source_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_imports = {"torch", "transformers", "peft", "mlx", "mlx_lm"}

    for py_path in (SCRIPT_PATH, SELF_PATH, EXPORT_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"comment tokens found in {py_path}"
        assert hash_char not in src, f"hash character found in {py_path}"
        assert em_dash not in src, f"em dash found in {py_path}"
        assert en_dash not in src, f"en dash found in {py_path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    for doc_path in (REPORT_MD_PATH, LEDGER_JSON_PATH, TRAIN_MANIFEST_PATH, VAL_MANIFEST_PATH):
        assert doc_path.is_file(), f"missing expected artifact: {doc_path}"
        txt = doc_path.read_text(encoding="utf-8")
        assert em_dash not in txt, f"em dash found in {doc_path}"
        assert en_dash not in txt, f"en dash found in {doc_path}"

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_historical_runs_and_clean_clone_determinism(tmp_path: Path) -> None:
    ledger_default = ledger_mod.build_ledger(repo_root=REPO_ROOT)
    ledger_clean = ledger_mod.build_ledger(
        repo_root=REPO_ROOT,
        external_data_root=tmp_path / "absent_external_data_dir",
    )
    assert ledger_default == ledger_clean
    assert ledger_mod.render_markdown_report(ledger_default) == ledger_mod.render_markdown_report(ledger_clean)

    bare_clone = tmp_path / "bare_clone"
    for rel in (
        "results/tiebreak/cal_v14_train_manifest.json",
        "results/tiebreak/cal_v14_val_manifest.json",
        "results/tiebreak/empirical_bayes/summary.json",
    ):
        dst = bare_clone / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text((REPO_ROOT / rel).read_text(encoding="utf-8"), encoding="utf-8")

    ledger_bare = ledger_mod.build_ledger(
        repo_root=bare_clone,
        external_data_root=tmp_path / "absent_external_data_dir",
    )
    assert ledger_default == ledger_bare
    assert ledger_mod.render_markdown_report(ledger_default) == ledger_mod.render_markdown_report(ledger_bare)

    by_id = {r["run_id"]: r for r in ledger_default["historical_runs"]}
    assert tuple(by_id.keys()) == (
        "J4-pilot-44200",
        "J4-v1-44397",
        "WS4-base-44411",
        "WS4-base-pooled",
        "WS4-v2-44412",
        "WS4-v2-off30-68bb",
        "WS4-v3-44548-44550",
        "WS4-v3-44553",
        "WS4-v3-4k-s1-714d-spot",
        "WS4-v3-4k-s1-44572",
        "WS4-v3-verda-s0-eval",
        "WS4-v3-4k-s0-ctx8k",
        "WS4-v3-8k-s0-3bb7",
        "WS4-v3-8k-s1-ac58",
        "WS4-v3-8k-s2-dbd0",
        "WS4-v3-8k-s3-f437",
        "WS4-dagger-r1-verda",
        "Verda-base-backup-18ac",
    )

    assert by_id["J4-pilot-44200"]["status"] == "FAILED_OOM"
    assert by_id["J4-pilot-44200"]["details"]["ram_limit_gb"] == 28
    assert by_id["J4-pilot-44200"]["details"]["pilot_episodes"] == 20000

    r_v1 = by_id["J4-v1-44397"]
    assert r_v1["status"] == "NEGATIVE_REWARD_PROTOCOL_GAIN"
    assert r_v1["heldout_n"] == 12
    assert r_v1["before_mean_score"] == 0.0
    assert r_v1["after_mean_score"] == -0.25
    assert r_v1["after_ci95"] == 0.256
    assert r_v1["before_valid_call_rate"] == 0.08
    assert r_v1["after_valid_call_rate"] == 0.99

    r_base = by_id["WS4-base-44411"]
    assert r_base["status"] == "BASELINE_CAVEATED"
    assert r_base["heldout_n"] == 16
    assert r_base["before_mean_score"] == 0.0
    assert r_base["before_valid_call_rate"] == 0.03
    assert r_base["details"]["unpaired_urandom_secret_caveat"] is True

    r_base_pooled = by_id["WS4-base-pooled"]
    assert r_base_pooled["status"] == "BASELINE_CAVEATED"
    assert r_base_pooled["heldout_n"] == 36
    assert r_base_pooled["before_mean_score"] == 0.0
    assert r_base_pooled["before_valid_call_rate"] == 0.03
    assert r_base_pooled["details"]["n_44411"] == 16
    assert r_base_pooled["details"]["n_44584"] == 20
    assert r_base_pooled["details"]["world_secret_tags"] == ["f272803cdb679dbe", "404f83e6a15c3f1c"]

    r_v2 = by_id["WS4-v2-44412"]
    assert r_v2["status"] == "NEGATIVE_BLIND_ACCUSE"
    assert r_v2["heldout_n"] == 82
    assert r_v2["after_mean_score"] == -0.395
    assert r_v2["after_ci95"] == 0.128
    assert r_v2["details"]["accused_rate"] == 0.51
    assert r_v2["details"]["accuracy"] == 0.06
    assert r_v2["details"]["header_tokens"] == 2842
    assert r_v2["details"]["body_budget_tokens"] == 1254

    r_v2_off30 = by_id["WS4-v2-off30-68bb"]
    assert r_v2_off30["status"] == "NEGATIVE_BLIND_ACCUSE"
    assert r_v2_off30["heldout_n"] == 90
    assert r_v2_off30["after_mean_score"] == -0.514
    assert r_v2_off30["after_ci95"] == 0.115
    assert r_v2_off30["details"]["pooled_v2_n"] == 172
    assert r_v2_off30["details"]["pooled_v2_mean_score"] == -0.457
    assert r_v2_off30["details"]["pooled_v2_ci95"] == 0.086

    assert by_id["WS4-v3-44548-44550"]["status"] == "FAILED_CUDA_OOM"
    assert by_id["WS4-v3-44553"]["status"] == "FAILED_ZERO_VARIANCE"
    assert by_id["WS4-v3-44553"]["details"]["zero_variance_groups_first_10"] == 8

    r_spot = by_id["WS4-v3-4k-s1-714d-spot"]
    assert r_spot["status"] == "FAILED_SPOT_PREEMPTED"
    assert r_spot["heldout_n"] == 0
    assert r_spot["details"]["verda_instance"] == "714d8144"
    assert r_spot["details"]["spot_preempted"] is True

    r_s1_4k = by_id["WS4-v3-4k-s1-44572"]
    assert r_s1_4k["status"] == "NEGATIVE_FLAT_V100_REPLICATE"
    assert r_s1_4k["heldout_n"] == 82
    assert r_s1_4k["after_mean_score"] == -0.209
    assert r_s1_4k["after_ci95"] == 0.094
    assert r_s1_4k["after_valid_call_rate"] == 0.97
    assert r_s1_4k["details"]["grpo_steps"] == 192
    assert r_s1_4k["details"]["accused_count"] == 19
    assert r_s1_4k["details"]["accused_rate"] == 0.23
    assert r_s1_4k["details"]["correct_count"] == 1
    assert r_s1_4k["details"]["accuracy"] == 0.01
    assert r_s1_4k["details"]["abstain_rate"] == 0.77
    assert r_s1_4k["details"]["two_sample_delta_vs_v2_mean"] == 0.249
    assert r_s1_4k["details"]["two_sample_delta_vs_v2_ci95"] == 0.127
    assert r_s1_4k["details"]["partial_n25_mean_score"] == -0.24
    assert r_s1_4k["details"]["partial_n25_ci95"] == 0.171

    r_v3_eval = by_id["WS4-v3-verda-s0-eval"]
    assert r_v3_eval["status"] == "NEGATIVE_4K_TRUNCATION_PERSISTS"
    assert r_v3_eval["heldout_n"] == 180
    assert r_v3_eval["after_mean_score"] == -0.147
    assert r_v3_eval["after_ci95"] == 0.063
    assert r_v3_eval["after_valid_call_rate"] == 1.0
    assert r_v3_eval["details"]["grpo_steps"] == 609
    assert r_v3_eval["details"]["accused_count"] == 38
    assert r_v3_eval["details"]["accused_rate"] == 0.21
    assert r_v3_eval["details"]["correct_count"] == 6
    assert r_v3_eval["details"]["precision_when_accused"] == 0.16
    assert r_v3_eval["details"]["delta_vs_v2_mean"] == 0.31
    assert r_v3_eval["details"]["delta_vs_v2_ci95"] == 0.107
    assert r_v3_eval["details"]["s0_n"] == 90
    assert r_v3_eval["details"]["s0_mean_score"] == -0.103
    assert r_v3_eval["details"]["off30_n"] == 90
    assert r_v3_eval["details"]["off30_mean_score"] == -0.192

    r_ctx8k = by_id["WS4-v3-4k-s0-ctx8k"]
    assert r_ctx8k["status"] == "NEGATIVE_INFERENCE_CTX_CONFOUND"
    assert r_ctx8k["context_len"] == 8192
    assert r_ctx8k["heldout_n"] == 90
    assert r_ctx8k["after_mean_score"] == -0.716
    assert r_ctx8k["after_ci95"] == 0.105
    assert r_ctx8k["after_world_secret_tag"] == "1ca0c2a64d"
    assert r_ctx8k["details"]["two_sample_delta_vs_4k_mean"] == -0.568
    assert r_ctx8k["details"]["two_sample_delta_vs_4k_ci95"] == 0.123

    r_8k_s0 = by_id["WS4-v3-8k-s0-3bb7"]
    assert r_8k_s0["status"] == "NEGATIVE_ABSTAIN_COLLAPSE"
    assert r_8k_s0["context_len"] == 8192
    assert r_8k_s0["heldout_n"] == 90
    assert r_8k_s0["after_mean_score"] == -0.06
    assert r_8k_s0["after_ci95"] == 0.054
    assert r_8k_s0["after_valid_call_rate"] == 0.98
    assert r_8k_s0["after_world_secret_tag"] == "1ca0c2a64d"
    assert r_8k_s0["details"]["verda_instance"] == "3bb74f5a"
    assert r_8k_s0["details"]["grpo_steps"] == 637
    assert r_8k_s0["details"]["accused_count"] == 7
    assert r_8k_s0["details"]["accused_rate"] == 0.08
    assert r_8k_s0["details"]["correct_count"] == 1
    assert r_8k_s0["details"]["accuracy"] == 0.01
    assert r_8k_s0["details"]["abstain_count"] == 83
    assert r_8k_s0["details"]["abstain_rate"] == 0.92
    assert r_8k_s0["details"]["two_sample_delta_vs_v2_mean"] == 0.397
    assert r_8k_s0["details"]["two_sample_delta_vs_v2_ci95"] == 0.101
    assert r_8k_s0["details"]["paired_vs_8k_s3_mean_delta"] == 0.728
    assert r_8k_s0["details"]["paired_vs_8k_s3_ci95"] == 0.134

    r_8k_s1 = by_id["WS4-v3-8k-s1-ac58"]
    assert r_8k_s1["status"] == "NEGATIVE_OFFPOLICY_OVERACCUSE"
    assert r_8k_s1["context_len"] == 8192
    assert r_8k_s1["heldout_n"] == 90
    assert r_8k_s1["after_mean_score"] == -0.777
    assert r_8k_s1["after_ci95"] == 0.118
    assert r_8k_s1["after_valid_call_rate"] == 0.92
    assert r_8k_s1["details"]["grpo_steps"] == 371
    assert r_8k_s1["details"]["accused_rate"] == 0.94
    assert r_8k_s1["details"]["accuracy"] == 0.09

    r_8k_s2 = by_id["WS4-v3-8k-s2-dbd0"]
    assert r_8k_s2["status"] == "NEGATIVE_ABSTAIN_COLLAPSE"
    assert r_8k_s2["context_len"] == 8192
    assert r_8k_s2["heldout_n"] == 90
    assert r_8k_s2["after_mean_score"] == -0.05
    assert r_8k_s2["after_ci95"] == 0.049
    assert r_8k_s2["after_valid_call_rate"] == 0.96
    assert r_8k_s2["details"]["grpo_steps"] == 693
    assert r_8k_s2["details"]["accused_rate"] == 0.07
    assert r_8k_s2["details"]["accuracy"] == 0.01
    assert r_8k_s2["details"]["abstain_rate"] == 0.93

    r_8k_s3 = by_id["WS4-v3-8k-s3-f437"]
    assert r_8k_s3["status"] == "NEGATIVE_PAIRED_8K_NULL"
    assert r_8k_s3["context_len"] == 8192
    assert r_8k_s3["heldout_n"] == 90
    assert r_8k_s3["after_mean_score"] == -0.788
    assert r_8k_s3["after_ci95"] == 0.117
    assert r_8k_s3["after_valid_call_rate"] == 0.94
    assert r_8k_s3["after_world_secret_tag"] == "1ca0c2a64d"
    assert r_8k_s3["details"]["grpo_steps"] == 344
    assert r_8k_s3["details"]["accused_rate"] == 0.96
    assert r_8k_s3["details"]["accuracy"] == 0.09
    assert r_8k_s3["details"]["paired_vs_4k_ctx8k_mean_delta"] == -0.073
    assert r_8k_s3["details"]["paired_vs_4k_ctx8k_ci95"] == 0.173
    assert r_8k_s3["details"]["matching_step0_rosters"] == 60

    r_dagger = by_id["WS4-dagger-r1-verda"]
    assert r_dagger["status"] == "NEGATIVE_DAGGER_INTERIM_BELOW_BASE"
    assert r_dagger["context_len"] == 8192
    assert r_dagger["heldout_n"] == 50
    assert r_dagger["after_mean_score"] == -0.542
    assert r_dagger["after_ci95"] == 0.214
    assert r_dagger["after_valid_call_rate"] == 1.0
    assert r_dagger["after_world_secret_tag"] == "1ca0c2a64d"
    assert r_dagger["details"]["verda_train_instance"] == "e9ea8b2e"
    assert r_dagger["details"]["verda_eval_instance"] == "68bbe201"
    assert r_dagger["details"]["sft_steps"] == 250
    assert r_dagger["details"]["sft_examples"] == 4000
    assert r_dagger["details"]["vllm_rollout_episodes"] == 300
    assert r_dagger["details"]["relabelled_states"] == 24074
    assert r_dagger["details"]["solver_match_checked"] == 2603
    assert r_dagger["details"]["solver_match_equal"] == 2603
    assert r_dagger["details"]["inf8k_mean_score_short"] == -0.54
    assert r_dagger["details"]["inf4k_mean_score_short"] == -0.10
    assert r_dagger["details"]["inf4k_heldout_n"] == 41
    assert r_dagger["details"]["inf4k_mean_score"] == -0.101

    r_reaper = by_id["Verda-base-backup-18ac"]
    assert r_reaper["status"] == "FAILED_REAPER_DELETED"
    assert r_reaper["heldout_n"] == 0
    assert r_reaper["details"]["verda_instance"] == "18acfa5d"
    assert r_reaper["details"]["also_lost_at_reaper_instance"] == "924e81d8"
    assert r_reaper["details"]["verda_total_instances_deleted"] == 9
    assert r_reaper["details"]["verda_measured_spend_eur"] == 104.46

    for r in by_id.values():
        assert r["verified_improvement"] is False
        assert r["gates"]["all_passed"] is False


def test_markdown_diagnosis_pillars_and_panel_fix_a() -> None:
    ledger = ledger_mod.build_ledger(repo_root=REPO_ROOT)
    md = ledger_mod.render_markdown_report(ledger)

    for required_substr in (
        "Historical runs logged: `18`",
        "0 / 18",
        "2,842 / 4,096",
        "1,254",
        "0.19 -> 0.89",
        "6/38 = 0.16",
        "-0.209 +/- 0.094",
        "-0.240 +/- 0.171",
        "-0.060 +/- 0.054",
        "+0.728 +/- 0.134",
        "-0.147 -> -0.716",
        "-0.568 +/- 0.123",
        "-0.073 +/- 0.173",
        "60/60",
        "1ca0c2a64d",
        "2,603/2,603",
        "24,074",
        "-0.542 +/- 0.214",
        "-0.101 +/- 0.112",
        "18acfa5d",
        "924e81d8",
        "104.46",
        "Open-Weight Autoregressive LLM Track",
        "Structured Compact Policy Track",
        "EmpiricalBayesPolicy",
        "post-hoc locked",
        "not pre-registered",
    ):
        assert required_substr in md, f"missing diagnosis substring: {required_substr!r}"

    for run_id in ledger_mod.HISTORICAL_RUN_IDS:
        assert f"| `{run_id}` |" in md


def test_gate1_rejects_leaked_and_overlapping_seeds() -> None:
    bad_train_Specs = [
        [0, 100_001, 100_002],
        [42_000, 100_001],
        [99_999, 100_000],
        [100_000, 200_000],
        [100_000, 800_005],
        [100_000, 900_000],
        [],
        [True, 100_001],
    ]
    for bad_spec in bad_train_Specs:
        s = _valid_summary_fixture()
        s["train_seeds"] = bad_spec
        res = ledger_mod.validate_experiment_summary(s)
        assert res["gates"]["gate1_seed_hygiene"] is False
        assert res["verified_improvement"] is False
        assert res["status"] != "VERIFIED_IMPROVEMENT"

    overlap_s = _valid_summary_fixture()
    overlap_s["train_seeds"] = [100_000, 100_001, 100_002]
    overlap_s["eval_seeds"] = [100_002] + list(range(800_000, 800_029))
    res_ov = ledger_mod.validate_experiment_summary(overlap_s)
    assert res_ov["gates"]["gate1_seed_hygiene"] is False
    assert res_ov["verified_improvement"] is False


def test_gate2_rejects_unpaired_secrets_and_non_heldout_eval() -> None:
    unpaired = _valid_summary_fixture()
    unpaired["before"]["world_secret_tag"] = "f272803cdb679dbe"
    unpaired["after"]["world_secret_tag"] = "c86b9c8a54f8b269"
    r1 = ledger_mod.validate_experiment_summary(unpaired)
    assert r1["gates"]["gate2_paired_world_secret"] is False
    assert r1["verified_improvement"] is False
    assert r1["status"] != "VERIFIED_IMPROVEMENT"

    missing_sec = _valid_summary_fixture()
    del missing_sec["before"]["world_secret_tag"]
    r2 = ledger_mod.validate_experiment_summary(missing_sec)
    assert r2["gates"]["gate2_paired_world_secret"] is False
    assert r2["verified_improvement"] is False

    placeholder_sec = _valid_summary_fixture()
    placeholder_sec["before"]["world_secret_tag"] = "unpaired"
    placeholder_sec["after"]["world_secret_tag"] = "unpaired"
    r3 = ledger_mod.validate_experiment_summary(placeholder_sec)
    assert r3["gates"]["gate2_paired_world_secret"] is False

    dev_eval = _valid_summary_fixture()
    dev_eval["eval_seeds"] = list(range(0, 30))
    r4 = ledger_mod.validate_experiment_summary(dev_eval)
    assert r4["gates"]["gate2_paired_world_secret"] is False
    assert r4["verified_improvement"] is False

    judge_eval = _valid_summary_fixture()
    judge_eval["eval_seeds"] = list(range(900_000, 900_030))
    r5 = ledger_mod.validate_experiment_summary(judge_eval)
    assert r5["gates"]["gate2_paired_world_secret"] is False


def test_gate3_rejects_small_n_unverified_replay_and_invalid_episodes() -> None:
    small_n = _valid_summary_fixture()
    small_n["n"] = 29
    small_n["before"]["n"] = 29
    small_n["after"]["n"] = 29
    small_n["before"]["scores"] = small_n["before"]["scores"][:29]
    small_n["after"]["scores"] = small_n["after"]["scores"][:29]
    small_n["eval_seeds"] = list(range(800_000, 800_029))
    r1 = ledger_mod.validate_experiment_summary(small_n)
    assert r1["gates"]["gate3_sample_and_replay"] is False
    assert r1["verified_improvement"] is False

    for bad_rv in (False, None, 1, "true"):
        no_rv = _valid_summary_fixture()
        no_rv["replay_verified"] = bad_rv
        r_rv = ledger_mod.validate_experiment_summary(no_rv)
        assert r_rv["gates"]["gate3_sample_and_replay"] is False
        assert r_rv["verified_improvement"] is False

    bad_inv = _valid_summary_fixture()
    bad_inv["invalid_episodes"] = 1
    r_inv = ledger_mod.validate_experiment_summary(bad_inv)
    assert r_inv["gates"]["gate3_sample_and_replay"] is False
    assert r_inv["verified_improvement"] is False

    bad_end = _valid_summary_fixture()
    bad_end["after"]["end_reasons"] = {"accused": 21, "horizon": 8, "error": 1}
    r_end = ledger_mod.validate_experiment_summary(bad_end)
    assert r_end["gates"]["gate3_sample_and_replay"] is False
    assert r_end["verified_improvement"] is False

    no_err_accounting = _valid_summary_fixture()
    del no_err_accounting["invalid_episodes"]
    del no_err_accounting["error_episodes"]
    del no_err_accounting["before"]["end_reasons"]
    del no_err_accounting["after"]["end_reasons"]
    r_missing_acc = ledger_mod.validate_experiment_summary(no_err_accounting)
    assert r_missing_acc["gates"]["gate3_sample_and_replay"] is False


def test_gate4_rejects_negative_and_zero_crossing_ci() -> None:
    neg = _valid_summary_fixture()
    neg["after"]["scores"] = [-1.0 if i < 15 else 0.0 for i in range(30)]
    neg["after"]["mean_score"] = -0.5
    r_neg = ledger_mod.validate_experiment_summary(neg)
    assert r_neg["gates"]["gate4_paired_ci95_positive"] is False
    assert r_neg["verified_improvement"] is False
    assert r_neg["status"] == "NEGATIVE_NO_GAIN"

    cross_zero = _valid_summary_fixture()
    noisy_after = [0.8] * 4 + [-1.0] * 2 + [0.0] * 24
    cross_zero["after"]["scores"] = noisy_after
    cross_zero["after"]["mean_score"] = round(sum(noisy_after) / 30, 4)
    r_cz = ledger_mod.validate_experiment_summary(cross_zero)
    assert r_cz["paired_mean_delta"] > 0.0
    assert r_cz["paired_ci95_low"] <= 0.0
    assert r_cz["gates"]["gate4_paired_ci95_positive"] is False
    assert r_cz["verified_improvement"] is False
    assert r_cz["status"] == "INCONCLUSIVE_CI_CROSSES_ZERO"

    zero_bound = copy.deepcopy(_valid_summary_fixture())
    del zero_bound["before"]["scores"]
    del zero_bound["after"]["scores"]
    zero_bound["before"]["mean_score"] = 0.2
    zero_bound["after"]["mean_score"] = 0.3
    zero_bound["paired"] = {"mean_delta": 0.1, "ci95_low": 0.0, "ci95_high": 0.2}
    r_zb = ledger_mod.validate_experiment_summary(zero_bound)
    assert r_zb["gates"]["gate4_paired_ci95_positive"] is False
    assert r_zb["verified_improvement"] is False


def test_positive_acceptance_and_dynamic_discovery(tmp_path: Path) -> None:
    good = _valid_summary_fixture()
    res = ledger_mod.validate_experiment_summary(good, summary_path="results/tiebreak/good_exp/summary.json")
    assert res["gates"]["all_passed"] is True
    assert res["verified_improvement"] is True
    assert res["status"] == "VERIFIED_IMPROVEMENT"
    assert res["paired_ci95_low"] > 0.0

    in_repo_glob_dir = tmp_path / "repo_runs" / "tiny_mlp"
    in_repo_glob_dir.mkdir(parents=True)
    (in_repo_glob_dir / "summary.json").write_text(json.dumps(good), encoding="utf-8")

    shared_glob_dir = tmp_path / "shared_runs" / "unpaired_cand"
    shared_glob_dir.mkdir(parents=True)
    bad = _valid_summary_fixture()
    bad["run_id"] = "unpaired-cand-v1"
    bad["after"]["world_secret_tag"] = "ffffffff00000000"
    (shared_glob_dir / "summary.json").write_text(json.dumps(bad), encoding="utf-8")

    out_json = tmp_path / "out" / "experiment_ledger.json"
    out_md = tmp_path / "out" / "tiebreak_small_model.md"
    rc_write = ledger_mod.main([
        "--repo-root",
        str(REPO_ROOT),
        "--summary-glob",
        str(tmp_path / "repo_runs" / "*" / "summary.json"),
        "--extra-glob",
        str(tmp_path / "shared_runs" / "*" / "summary.json"),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ])
    assert rc_write == 0
    written = json.loads(out_json.read_text(encoding="utf-8"))
    assert written["summary_counts"]["historical_runs"] == 18
    assert written["summary_counts"]["discovered_runs"] == 2
    assert written["summary_counts"]["verified_improvements"] == 1
    assert written["summary_counts"]["verified_run_ids"] == ["compact-cal-0.5b-v1"]

    rc_check = ledger_mod.main([
        "--check",
        "--repo-root",
        str(REPO_ROOT),
        "--summary-glob",
        str(tmp_path / "repo_runs" / "*" / "summary.json"),
        "--extra-glob",
        str(tmp_path / "shared_runs" / "*" / "summary.json"),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ])
    assert rc_check == 0


def test_committed_artifacts_check_and_tamper_detection(tmp_path: Path) -> None:
    assert ledger_mod.main(["--check"]) == 0
    assert ledger_mod.main(["--check", "--external-data-root", str(tmp_path / "missing_ext")]) == 0

    proc = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is True
    assert payload["historical_runs"] == 18

    tampered_json = tmp_path / "tampered_ledger.json"
    data = json.loads(LEDGER_JSON_PATH.read_text(encoding="utf-8"))
    data["summary_counts"]["verified_improvements"] = 99
    tampered_json.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert ledger_mod.main(["--check", "--out-json", str(tampered_json)]) == 1
