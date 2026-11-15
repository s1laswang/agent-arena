from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import shutil
import time
import tokenize

import pytest

import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.tiebreak_failure_taxonomy_matrix as mod

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_failure_taxonomy_matrix.py"
MATRIX_JSON_PATH = (
    REPO_ROOT / "results" / "tiebreak" / "failure_taxonomy" / "failure_taxonomy_matrix.json"
)
REPORT_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_failure_taxonomy.md"
SELF_PATH = Path(__file__).resolve()


def test_source_and_artifact_hygiene_and_budget() -> None:
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

    assert MATRIX_JSON_PATH.is_file()
    assert REPORT_MD_PATH.is_file()
    assert MATRIX_JSON_PATH.stat().st_size < 80 * 1024
    assert not (MATRIX_JSON_PATH.parent / "summary.json").exists()
    assert not (MATRIX_JSON_PATH.parent / "table.md").exists()

    for art in (MATRIX_JSON_PATH, REPORT_MD_PATH):
        txt = art.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert unicode_minus not in txt


def test_mece_19_run_partition_and_bucket_counts() -> None:
    matrix = json.loads(MATRIX_JSON_PATH.read_text(encoding="utf-8"))
    ledger = json.loads((REPO_ROOT / "results" / "tiebreak" / "experiment_ledger.json").read_text(encoding="utf-8"))

    ht = matrix["headline_totals"]
    assert ht["historical_open_weight_runs"] == 19
    assert ht["root_cause_bucket_count"] == 9
    assert ht["runs_beating_base_zero"] == 0
    assert ht["verified_open_weight_improvements"] == 0
    assert ht["n0_failed_or_lost_runs"] == 5
    assert ht["untrained_base_runs"] == 2
    assert ht["trained_eval_runs"] == 12
    assert ht["best_trained_open_weight_run_id"] == "WS4-v3-8k-s2-dbd0"
    assert ht["best_trained_open_weight_score"] == pytest.approx(-0.05)
    assert ht["worst_trained_open_weight_run_id"] == "WS4-v3-8k-s3-f437"
    assert ht["worst_trained_open_weight_score"] == pytest.approx(-0.788)

    expected_bucket_counts = {
        "infra_oom_zerovar_spot_reaper_n0": 5,
        "untrained_base_protocol_stall": 2,
        "prefix_4k_sft_v13_sparse_loss": 1,
        "dense_4k_sft_blind_accuse": 2,
        "grpo_4k_offpolicy_evidence_shift": 2,
        "same_weights_8k_inference_confound": 1,
        "grpo_8k_high_step_abstention_collapse": 2,
        "grpo_8k_low_step_over_accuse": 2,
        "verda_x2_dagger_r1_honest_null": 2,
    }
    buckets_by_id = {b["bucket_id"]: b for b in matrix["buckets"]}
    assert set(buckets_by_id.keys()) == set(expected_bucket_counts.keys())
    for bid, exp_cnt in expected_bucket_counts.items():
        b_obj = buckets_by_id[bid]
        assert b_obj["run_count"] == exp_cnt
        assert len(b_obj["run_ids"]) == exp_cnt
        assert b_obj["runs_above_base_zero"] == 0

    all_bucket_rids = [rid for b in matrix["buckets"] for rid in b["run_ids"]]
    assert len(all_bucket_rids) == 19
    assert len(set(all_bucket_rids)) == 19
    ledger_rids = [r["run_id"] for r in ledger["historical_runs"]]
    assert set(all_bucket_rids) == set(ledger_rids)
    assert [r["run_id"] for r in matrix["runs"]] == ledger_rids

    for r in matrix["runs"]:
        assert r["beats_base_zero"] is False
        assert r["verified_improvement"] is False
        if r["bucket_id"] == "infra_oom_zerovar_spot_reaper_n0":
            assert r["heldout_n"] == 0
            assert r["mean_score"] is None
        elif r["bucket_id"] == "untrained_base_protocol_stall":
            assert r["mean_score"] == pytest.approx(0.0)
        else:
            assert r["mean_score"] < 0.0


def test_episode_step_verda_spend_and_panel_disclosures() -> None:
    matrix = json.loads(MATRIX_JSON_PATH.read_text(encoding="utf-8"))
    md_txt = REPORT_MD_PATH.read_text(encoding="utf-8")
    acct = matrix["episode_step_spend_accounting"]

    ep = acct["episodes"]
    assert ep["raw_ledger_heldout_episodes_sum"] == 1039
    assert ep["deduplicated_unique_heldout_episodes"] == 1023
    assert ep["untrained_base_unique_episodes"] == 36
    assert ep["untrained_base_overlap_episodes_44411"] == 16
    assert ep["trained_open_weight_heldout_episodes"] == 987
    assert ep["v13_trained_heldout_episodes"] + ep["v14_trained_heldout_episodes"] == 987
    assert ep["verda_multiseed_belief_replayed_episodes"] == 712
    assert ep["verda_multiseed_replay_invariant_errors"] == 0
    assert ep["context_confound_verda_audited_episodes"] == 450
    assert ep["dagger_r1_vllm_train_rollout_episodes"] == 300
    assert ep["dagger_r1_relabelled_states"] == 24074
    assert ep["dagger_mechanism_train_audit_episodes"] == 45

    st = acct["steps"]
    assert st["unique_sft_and_dagger_steps"] == 1587
    assert st["j4_v1_44397_sft_steps"] + st["ws4_v2_44410_sft_steps"] + st["ws4_dagger_r1_sft_steps"] == 1587
    assert st["completed_grpo_steps_6_seeds"] == 2846
    assert st["aborted_zerovar_grpo_steps_44553"] == 6
    assert st["total_unique_ledger_optimizer_steps"] == 4439

    vs = acct["verda_spend"]
    assert vs["start_balance_eur"] == pytest.approx(200.0)
    assert vs["end_balance_eur"] == pytest.approx(95.54)
    assert vs["measured_spend_eur"] == pytest.approx(104.46)
    assert vs["deleted_instances_count"] == 9
    assert len(vs["instances"]) == 9
    assert vs["h100_instances_count"] + vs["a100_instances_count"] == 9
    assert vs["instance_table_max_gpu_hours_sum"] == pytest.approx(44.16)
    assert vs["instance_table_max_cost_eur_sum"] == pytest.approx(103.92)

    disc = matrix["disclosures"]
    assert "post-hoc locked, not pre-registered" in disc["panel_fix_a"]
    assert "1ca0c2a64d" in disc["panel_fix_a"]
    assert "is_open_weight_llm=False" in disc["panel_fix_e"]
    assert "0 / 19" in disc["panel_fix_e"]

    eur_tok = f"{chr(0x20AC)}104.46"
    assert eur_tok in md_txt
    assert "post-hoc locked, not pre-registered" in md_txt
    assert "is_open_weight_llm = False" in md_txt


def test_cross_artifact_mechanistic_numbers() -> None:
    matrix = json.loads(MATRIX_JSON_PATH.read_text(encoding="utf-8"))
    rec = matrix["cross_artifact_reconciliation"]
    assert rec["mece_partition_verified"] is True
    assert rec["ledger_vs_forensics_verified"] is True
    assert rec["ledger_vs_multiseed_712ep_2846st_verified"] is True
    assert rec["ledger_vs_context_confound_450ep_verified"] is True
    assert rec["ledger_vs_dagger_mechanism_verified"] is True

    km = rec["key_mechanistic_numbers"]
    assert km["raw_4k_header_tokens_44410"] == 2842
    assert km["raw_4k_body_budget_tokens_44410"] == 1254
    assert km["pooled_v2_below_breakeven_ratio"] == "90/94"
    assert km["v3_4k_s0_heldout_precision_ratio"] == "6/38"
    assert km["same_weights_4k_to_8k_two_sample_delta"] == pytest.approx(-0.568)
    assert km["paired_8k_s0_minus_s3_delta"] == pytest.approx(0.728)
    assert km["paired_8k_s3_minus_4k_at_8k_delta"] == pytest.approx(-0.073)
    assert km["paired_8k_s0_minus_4k_at_8k_delta"] == pytest.approx(0.655)
    assert km["high_step_8k_missed_commits_ratio"] == "21/167"
    assert km["low_step_8k_below_breakeven_ratio"] == "167/171"
    assert km["hard_dagger_cap96_truncation_ratio"] == "133/180"
    assert km["train_below_breakeven_daily_states_ratio"] == "250/322"
    assert km["dagger_r1_accuse_sft_labels_ratio"] == "159/4000"
    assert km["dagger_r1_own_state_agreement_before_after"] == [0.43, 0.68]
    assert km["dagger_r1_8k_whom_precision_before_after"] == [0.10, 0.22]

    nl = matrix["non_llm_structured_contrast"]
    assert nl["is_open_weight_llm"] is False
    assert nl["compact_linear_dagger"]["after_mean_score"] == pytest.approx(0.6267, abs=1e-4)
    assert nl["tiny_mlp_dagger"]["after_mean_score"] == pytest.approx(0.6141, abs=1e-4)
    assert nl["empirical_bayes"]["after_mean_score"] == pytest.approx(0.6073, abs=1e-4)


def test_fast_check_cli_root_isolation_and_tamper_detection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    t0 = time.perf_counter()
    rc = mod.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 10.0
    capsys.readouterr()

    rel_files = [
        "scripts/tiebreak_failure_taxonomy_matrix.py",
        "tests/test_tiebreak_failure_taxonomy.py",
        "results/tiebreak/experiment_ledger.json",
        "results/tiebreak/forensics_prior_runs.json",
        "results/tiebreak/verda_multiseed/multiseed_summary.json",
        "results/tiebreak/context_confound/audit_summary.json",
        "results/tiebreak/dagger_mechanism/dagger_mechanism_summary.json",
        "results/tiebreak/failure_taxonomy/failure_taxonomy_matrix.json",
        "docs/reports/tiebreak_failure_taxonomy.md",
    ]
    for rel in rel_files:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, dst)

    t1 = time.perf_counter()
    assert mod.main(["--root", str(tmp_path), "--check", "--json"]) == 0
    assert (time.perf_counter() - t1) < 10.0
    chk_json = json.loads(capsys.readouterr().out)
    assert chk_json["passed"] is True
    assert chk_json["errors"] == []

    bad_md = tmp_path / "docs" / "reports" / "tiebreak_failure_taxonomy.md"
    orig_md = bad_md.read_text(encoding="utf-8")
    bad_md.write_text(orig_md.replace("-0.788 +/- 0.117", "-0.123 +/- 0.117"), encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    bad_md.write_text(orig_md, encoding="utf-8")

    bad_json = tmp_path / "results" / "tiebreak" / "failure_taxonomy" / "failure_taxonomy_matrix.json"
    orig_json = bad_json.read_text(encoding="utf-8")
    j_obj = json.loads(orig_json)
    j_obj["episode_step_spend_accounting"]["verda_spend"]["measured_spend_eur"] = 99.99
    bad_json.write_text(json.dumps(j_obj, indent=2) + "\n", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    bad_json.write_text(orig_json, encoding="utf-8")

    forbidden_sum = tmp_path / "results" / "tiebreak" / "failure_taxonomy" / "summary.json"
    forbidden_sum.write_text("{}\n", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    forbidden_sum.unlink()

    forbidden_tbl = tmp_path / "results" / "tiebreak" / "failure_taxonomy" / "table.md"
    forbidden_tbl.write_text("| a | b |\n", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    forbidden_tbl.unlink()

    ms_path = tmp_path / "results" / "tiebreak" / "verda_multiseed" / "multiseed_summary.json"
    orig_ms = ms_path.read_text(encoding="utf-8")
    ms_obj = json.loads(orig_ms)
    ms_obj["totals"]["total_training_curve_steps_audited"] = 9999
    ms_path.write_text(json.dumps(ms_obj, indent=2) + "\n", encoding="utf-8")
    assert mod.main(["--root", str(tmp_path), "--check"]) == 1
    ms_path.write_text(orig_ms, encoding="utf-8")

    assert mod.main(["--root", str(tmp_path)]) == 0
    assert mod.main(["--root", str(tmp_path), "--check"]) == 0
    assert ledger_mod.main(["--check"]) == 0
