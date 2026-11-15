from __future__ import annotations

import copy
import importlib.util
import io
import json
import re
import shutil
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_qwen_mole_report.py"
SUMMARY_PATH = ROOT / "results" / "moletrain" / "qwen_mole_summary.json"
REPORT_MD_PATH = ROOT / "docs" / "reports" / "qwen_mole_training.md"
TEST_PATH = Path(__file__).resolve()


def _load_report_module():
    spec = importlib.util.spec_from_file_location("build_qwen_mole_report", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rep = _load_report_module()


def _make_verda_eval(
    model: str,
    base_valid: float,
    base_rew: float,
    base_reg: float,
    ad_rew: float,
    ad_reg: float,
    ad_catch: float,
    diff_mean: float,
    diff_ci: list[float],
    actions: list[list[str]],
) -> dict:
    return {
        "model": model,
        "adapter": "/root/runs/mock/lora-step200",
        "tier": "hard",
        "n": len(actions),
        "seeds": [400000, 400000 + len(actions) - 1],
        "heldout_seed_base": 400000,
        "base": {
            "reward": {"mean": base_rew, "ci95": [base_rew - 0.05, base_rew + 0.05], "n": len(actions)},
            "valid": {"mean": base_valid, "ci95": [max(0.0, base_valid - 0.03), min(1.0, base_valid + 0.03)], "n": len(actions)},
            "solver_catch": {"mean": 0.10 if base_valid < 0.5 else 0.95, "ci95": [0.05, 0.99], "n": len(actions)},
            "regret": {"mean": base_reg, "ci95": [base_reg - 0.05, base_reg + 0.05], "n": max(1, int(len(actions) * base_valid))},
        },
        "adapter_result": {
            "reward": {"mean": ad_rew, "ci95": [ad_rew - 0.05, ad_rew + 0.05], "n": len(actions)},
            "valid": {"mean": 1.0, "ci95": [1.0, 1.0], "n": len(actions)},
            "solver_catch": {"mean": ad_catch, "ci95": [ad_catch - 0.03, min(1.0, ad_catch + 0.03)], "n": len(actions)},
            "regret": {"mean": ad_reg, "ci95": [ad_reg - 0.05, ad_reg + 0.05], "n": len(actions)},
        },
        "reward_diff_adapter_minus_base": {
            "mean": diff_mean,
            "ci95": diff_ci,
            "n": len(actions),
        },
        "actions_adapter": actions,
        "sec": 42.0,
    }


def _make_v100_eval_summary(
    name: str,
    model: str,
    solver_acc_800k: float,
    solver_acc_200k: float,
    qwen_min_regret_800k: float,
    default_grok_score_800k: float,
    reg_diff_ci_800k: list[float],
    distinct_actions: int,
) -> dict:
    default_solver_800k = 0.56
    qwen_solver_800k = 0.55
    qwen_grok_800k = round(qwen_solver_800k - qwen_min_regret_800k, 4)
    profile = (
        {"most_recipients/random_peer": 0.6, "newest/most_restricted_peer": 0.4}
        if distinct_actions >= 2
        else {"random_seeded/none": 1.0}
    )
    return {
        "name": name,
        "model": model,
        "smoke_tiny": False,
        "winner_checkpoint": "grpo_step60",
        "total_seconds": 612.4,
        "sft_examples": {"carbon_transcripts": 331, "counterfactual_expert": 88, "total": 507},
        "heldout_800k_summary": {
            "solver": {"score": qwen_solver_800k, "acc": solver_acc_800k},
            "grok_tactics": {"score": qwen_grok_800k, "acc": 0.72},
            "heuristic": {"score": 0.05, "acc": 0.65},
            "hinted_heuristic": {"score": qwen_grok_800k - 0.04, "acc": 0.70},
            "min_regret": qwen_min_regret_800k,
            "strongest_inv": "grok_tactics",
            "catchable_85": solver_acc_800k >= 0.85,
            "distinct_actions": distinct_actions,
            "action_entropy_nats": 0.673 if distinct_actions >= 2 else 0.0,
            "action_profile": profile,
            "unique_prompts_generated": 240,
            "invalid_generations": 0,
            "eval_sec": 95.0,
        },
        "heldout_200k_summary": {
            "solver": {"score": 0.54, "acc": solver_acc_200k},
            "grok_tactics": {"score": 0.30, "acc": 0.75},
            "heuristic": {"score": 0.04, "acc": 0.62},
            "hinted_heuristic": {"score": 0.28, "acc": 0.70},
            "min_regret": 0.24,
            "strongest_inv": "grok_tactics",
            "catchable_85": solver_acc_200k >= 0.85,
            "distinct_actions": distinct_actions,
            "action_entropy_nats": 0.673 if distinct_actions >= 2 else 0.0,
            "action_profile": profile,
            "unique_prompts_generated": 235,
            "invalid_generations": 0,
            "eval_sec": 93.0,
        },
        "paired_800k_vs_default": {
            "comparison": "qwen_vs_default_800k",
            "n": 40,
            "qwen_mole": {
                "solver": {"score": [qwen_solver_800k, 0.48, 0.62], "acc": [solver_acc_800k, solver_acc_800k - 0.05, min(1.0, solver_acc_800k + 0.05)]},
                "grok_tactics": {"score": [qwen_grok_800k, qwen_grok_800k - 0.06, qwen_grok_800k + 0.06], "acc": [0.72, 0.60, 0.84]},
                "heuristic": {"score": [0.05, -0.05, 0.15], "acc": [0.65, 0.52, 0.78]},
                "hinted_heuristic": {"score": [qwen_grok_800k - 0.04, 0.15, 0.35], "acc": [0.70, 0.58, 0.82]},
                "regret": {"grok_tactics": [qwen_min_regret_800k, qwen_min_regret_800k - 0.05, qwen_min_regret_800k + 0.05]},
            },
            "baseline": {
                "solver": {"score": [default_solver_800k, 0.50, 0.62], "acc": [0.95, 0.90, 1.0]},
                "grok_tactics": {"score": [default_grok_score_800k, 0.30, 0.42], "acc": [0.85, 0.78, 0.92]},
                "heuristic": {"score": [0.08, -0.02, 0.18], "acc": [0.80, 0.70, 0.88]},
                "hinted_heuristic": {"score": [default_grok_score_800k - 0.02, 0.28, 0.40], "acc": [0.82, 0.74, 0.90]},
                "regret": {"grok_tactics": [round(default_solver_800k - default_grok_score_800k, 4), 0.12, 0.28]},
            },
            "diff_qwen_minus_baseline": {
                "solver_score": [-0.01, -0.06, 0.04],
                "grok_tactics_score": [-0.08, -0.14, -0.02],
                "heuristic_score": [-0.03, -0.10, 0.04],
                "hinted_heuristic_score": [-0.06, -0.12, 0.00],
                "solver_acc": [round(solver_acc_800k - 0.95, 4), -0.10, 0.02],
                "regret_grok_tactics": reg_diff_ci_800k,
                "regret_heuristic": [0.02, -0.04, 0.08],
                "regret_hinted_heuristic": [0.05, 0.01, 0.09],
            },
        },
        "paired_200k_vs_default": {
            "comparison": "qwen_vs_default_200k",
            "n": 40,
            "qwen_mole": {
                "solver": {"score": [0.54, 0.47, 0.61], "acc": [solver_acc_200k, solver_acc_200k - 0.05, min(1.0, solver_acc_200k + 0.05)]},
                "grok_tactics": {"score": [0.30, 0.22, 0.38], "acc": [0.75, 0.64, 0.86]},
                "heuristic": {"score": [0.04, -0.06, 0.14], "acc": [0.62, 0.50, 0.74]},
                "hinted_heuristic": {"score": [0.28, 0.20, 0.36], "acc": [0.70, 0.58, 0.82]},
                "regret": {"grok_tactics": [0.24, 0.16, 0.32]},
            },
            "baseline": {
                "solver": {"score": [0.5681, 0.50, 0.62], "acc": [0.97, 0.93, 1.0]},
                "grok_tactics": {"score": [0.3724, 0.31, 0.43], "acc": [0.86, 0.79, 0.92]},
                "heuristic": {"score": [0.0755, -0.04, 0.18], "acc": [0.80, 0.72, 0.87]},
                "hinted_heuristic": {"score": [0.3591, 0.27, 0.44], "acc": [0.81, 0.73, 0.88]},
                "regret": {"grok_tactics": [0.1957, 0.11, 0.28]},
            },
            "diff_qwen_minus_baseline": {
                "solver_score": [-0.0281, -0.08, 0.02],
                "solver_acc": [round(solver_acc_200k - 0.97, 4), -0.12, 0.00],
                "regret_grok_tactics": [0.0443, 0.005, 0.09],
                "regret_heuristic": [0.01, -0.05, 0.07],
                "regret_hinted_heuristic": [0.05, 0.01, 0.10],
            },
        },
        "paired_200k_vs_rl_mole": {
            "comparison": "qwen_vs_rl_mole_200k",
            "n": 40,
            "diff_qwen_minus_baseline": {
                "solver_acc": [round(solver_acc_200k - 0.75, 4), 0.06, 0.26],
                "regret_grok_tactics": [0.01, -0.05, 0.07],
            },
        },
    }


def test_committed_artifacts_and_clean_clone_check(tmp_path: Path):
    assert SUMMARY_PATH.is_file()
    assert REPORT_MD_PATH.is_file()
    assert rep.MAX_SUMMARY_BYTES == 45_000
    assert SUMMARY_PATH.stat().st_size < rep.MAX_SUMMARY_BYTES

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert rep.validate_summary(summary) == []

    md_text = REPORT_MD_PATH.read_text(encoding="utf-8")
    assert md_text == rep.render_markdown(summary)

    linked_rel_paths: list[Path] = []
    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", md_text):
        target = m.group(1)
        if target.startswith(("http://", "https://")):
            continue
        resolved = (REPORT_MD_PATH.parent / target).resolve()
        assert resolved.exists(), f"broken markdown link: {target} -> {resolved}"
        linked_rel_paths.append(resolved.relative_to(ROOT))

    rl_info = summary["baseline_vs_cpu_rl_mole"]["cpu_rl_mole"]
    assert rl_info["solver_acc"] == 0.75
    assert rl_info["catchable_75"] is True
    assert rl_info["catchable_85"] is False

    v2_sec = summary["cpu_rl_mole_v2"]
    assert v2_sec["catchable_85_both_sets"] is True
    ws3_v2 = v2_sec["ws3_heldout"]
    assert ws3_v2["seeds"] == "200000-200059"
    assert ws3_v2["n"] == 60
    assert ws3_v2["rl_mole_v2"]["solver_acc"] == 0.9667
    assert ws3_v2["rl_mole_v2"]["solver_acc_ci95"] == [0.9167, 1.0]
    assert ws3_v2["rl_mole_v2"]["catchable_85"] is True
    assert ws3_v2["rl_mole_v2"]["min_regret"] == 0.2937
    assert ws3_v2["default_mole"]["min_regret"] == 0.2322
    assert ws3_v2["rl_mole_v1"]["solver_acc"] == 0.75
    assert ws3_v2["rl_mole_v1"]["catchable_85"] is False
    assert ws3_v2["rl_mole_v2"]["wide_unrestricted_none_rate"] == 0.0

    rules_v2 = v2_sec["rules_heldout"]
    assert rules_v2["seeds"] == "800000-800059"
    assert rules_v2["n"] == 60
    assert rules_v2["rl_mole_v2"]["solver_acc"] == 0.95
    assert rules_v2["rl_mole_v2"]["catchable_85"] is True
    assert rules_v2["rl_mole_v2"]["min_regret"] == 0.2095
    assert rules_v2["default_mole"]["min_regret"] == 0.1766

    verda = summary["verda_vanilla_grpo_heldout"]
    assert verda["n_runs"] == 11
    assert verda["claims_stronger_mole"] is False
    assert verda["overall_verdict"] == "negative_vanilla_grpo_collapse_baseline"
    by_scale = verda["by_scale"]
    assert by_scale["0.5B"]["n_runs"] == 3
    assert by_scale["1.5B"]["n_runs"] == 6
    assert by_scale["3B"]["n_runs"] == 2
    for r in verda["runs"]:
        assert r["claims_stronger_mole"] is False
        if r["scale"] == "0.5B":
            assert r["verdict"] == "format_validity_only_collapsed_silent"
            assert r["greedy_actions"]["top_action"] == "none/decoy"
            assert r["greedy_actions"]["top_action_share"] == 1.0

    v100_by_id = {r["run_id"]: r for r in summary["v100_regularized_sft_grpo"]["runs"]}
    r_v1 = v100_by_id["canary-qwen-mole-v1"]
    assert r_v1["grpo_curve"]["steps_logged"] == 80
    assert r_v1["validation_25seed"]["seeds"] == "195000-195024"
    assert r_v1["validation_25seed"]["n"] == 25
    assert r_v1["validation_25seed"]["split"] == "validation_25seed_not_heldout"
    assert "sft" in r_v1["validation_25seed"]["checkpoints"]
    assert "grpo_step40" in r_v1["validation_25seed"]["checkpoints"]

    r_17b = v100_by_id["canary-qwen3-1p7b-mole-v1"]
    assert r_17b["grpo_curve"]["steps_logged"] >= 40
    sft_17b = r_17b["validation_25seed"]["checkpoints"]["sft"]
    assert sft_17b["min_regret"] == 0.2496
    assert sft_17b["solver_acc"] == 0.96
    assert sft_17b["action_entropy_nats"] == 1.0894

    for r in summary["v100_regularized_sft_grpo"]["runs"]:
        if r["eval_summary"] is None:
            assert r["status"] == "in_progress"
            assert r["claims_stronger_mole"] is False

    clean_clone = tmp_path / "judge_clean_clone"
    needed_files = set(linked_rel_paths) | {
        Path("results/moletrain/qwen_mole_summary.json"),
        Path("docs/reports/qwen_mole_training.md"),
        Path("data/rl_mole/heldout_paired.json"),
        Path("data/rl_mole/eval_heldout_rl.json"),
        Path("data/rl_mole/eval_heldout_default.json"),
        Path("results/moletrain/rl_mole_v2_heldout.json"),
        Path("data/grpo_mole/curve-44424.jsonl"),
        Path("data/grpo_mole/curve-44425.jsonl"),
        Path("data/grpo_mole/curve-44426.jsonl"),
    }
    for rel in needed_files:
        src_p = ROOT / rel
        dst_p = clean_clone / rel
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_p, dst_p)

    rc = rep.main([
        "--check",
        "--repo-root", str(clean_clone),
        "--verda-dir", str(tmp_path / "no_momin_verda"),
        "--board-dir", str(tmp_path / "no_momin_board"),
        "--logs-dir", str(tmp_path / "no_momin_logs"),
    ])
    assert rc == 0


def test_gpu_log_parsing_and_live_append_resilience(tmp_path: Path):
    board_dir = tmp_path / "board"
    logs_dir = tmp_path / "logs"
    board_dir.mkdir()
    logs_dir.mkdir()

    val_sft_obj = {
        "solver": {"score": 0.5336, "acc": 0.96},
        "grok_tactics": {"score": 0.0, "acc": 0.0},
        "heuristic": {"score": -0.1468, "acc": 0.68},
        "hinted_heuristic": {"score": 0.284, "acc": 0.72},
        "min_regret": 0.2496,
        "strongest_inv": "hinted_heuristic",
        "catchable_85": True,
        "distinct_actions": 3,
        "action_entropy_nats": 1.0894,
        "action_profile": {"none/random_peer": 0.3709, "most_recipients/random_peer": 0.3583, "random_seeded/most_restricted_peer": 0.2707},
        "unique_prompts_generated": 1464,
        "invalid_generations": 0,
        "eval_sec": 3102.9,
    }
    val_40_obj = {
        "solver": {"score": 0.5396, "acc": 0.92},
        "grok_tactics": {"score": 0.0, "acc": 0.0},
        "heuristic": {"score": 0.0216, "acc": 0.76},
        "hinted_heuristic": {"score": 0.3064, "acc": 0.72},
        "min_regret": 0.2332,
        "strongest_inv": "hinted_heuristic",
        "catchable_85": True,
        "distinct_actions": 3,
        "action_entropy_nats": 1.0559,
        "action_profile": {"random_seeded/most_restricted_peer": 0.4111, "none/random_peer": 0.387, "most_recipients/random_peer": 0.2019},
        "unique_prompts_generated": 1450,
        "invalid_generations": 0,
        "eval_sec": 3000.0,
    }
    log_file = logs_dir / "canary-qwen3-1p7b-mole-v1.log"
    log_lines = [
        "[init] device=cuda smoke_tiny=False workers=2 model=/models/Qwen3-1.7B",
        "[data] carbon_sft=331 expert_sft=88 total_sft=507 grpo_prompts=130",
        '[sft] {"epoch": 1, "step": 15, "loss": 0.1529, "sec": 11.1}',
        '[sft] {"epoch": 3, "step": 192, "loss": 0.0066, "sec": 128.6}',
        f"[val sft] {json.dumps(val_sft_obj)}",
        '[grpo] {"step": 1, "reward": 0.0756, "mean_regret": -0.03, "valid_rate": 1.0, "batch_solver_acc": 1.0, "lam_catch": 0.768, "abs_kl": 0.0005, "tok_ent": 0.0881, "top_actions": {"most_recipients/random_peer": 12, "random_seeded/most_restricted_peer": 6}, "sec": 10.4}',
        '[grpo] {"step": 40, "reward": -0.0028, "mean_regret": -0.1222, "valid_rate": 1.0, "batch_solver_acc": 0.9444, "lam_catch": 0.4, "abs_kl": 0.0136, "tok_ent": 0.0959, "top_actions": {"most_recipients/random_peer": 7, "random_seeded/decoy": 5}, "sec": 13.6}',
        f"[val step=40] {json.dumps(val_40_obj)}",
        "[grpo] {\"truncated_half_line",
    ]
    log_file.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    sec_t0 = rep.build_v100_section(board_dir, logs_dir)
    by_id = {r["run_id"]: r for r in sec_t0["runs"]}
    r17 = by_id["canary-qwen3-1p7b-mole-v1"]
    assert r17["status"] == "in_progress"
    assert r17["claims_stronger_mole"] is False
    assert r17["eval_summary"] is None
    assert r17["data_mix"] == {"carbon_sft": 331, "expert_sft": 88, "total_sft": 507, "grpo_prompts": 130}
    assert r17["grpo_curve"]["steps_logged"] == 2
    assert r17["validation_25seed"]["seeds"] == "195000-195024"
    assert r17["validation_25seed"]["checkpoints"]["sft"]["min_regret"] == 0.2496
    assert r17["validation_25seed"]["checkpoints"]["grpo_step40"]["min_regret"] == 0.2332

    log_lines[-1] = '[grpo] {"step": 41, "reward": 0.21, "mean_regret": 0.09, "valid_rate": 1.0, "batch_solver_acc": 1.0, "lam_catch": 0.4, "abs_kl": 0.015, "tok_ent": 0.098, "top_actions": {"most_recipients/random_peer": 9, "random_seeded/decoy": 9}, "sec": 11.0}'
    log_file.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    assert rep._check_v100_against_disk(sec_t0, board_dir, logs_dir, allow_live_append=True) == []
    assert rep._check_v100_against_disk(sec_t0, board_dir, logs_dir, allow_live_append=False) != []

    tampered = copy.deepcopy(sec_t0)
    for r in tampered["runs"]:
        if r["run_id"] == "canary-qwen3-1p7b-mole-v1":
            r["validation_25seed"]["checkpoints"]["sft"]["min_regret"] = 0.3999
    errs = rep._check_v100_against_disk(tampered, board_dir, logs_dir, allow_live_append=True)
    assert any("validation_25seed[sft]" in e for e in errs)


def test_synthetic_fixtures_in_progress_and_completed_gates(tmp_path: Path):
    verda_dir = tmp_path / "verda"
    board_dir = tmp_path / "board"
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    out_json = tmp_path / "out" / "qwen_mole_summary.json"
    out_md = tmp_path / "out" / "qwen_mole_training.md"

    r05 = verda_dir / "10.0.0.1" / "0.5B-s0"
    r05.mkdir(parents=True)
    (r05 / "eval.json").write_text(
        json.dumps(
            _make_verda_eval(
                model="Qwen/Qwen2.5-0.5B-Instruct",
                base_valid=0.10,
                base_rew=-0.91,
                base_reg=-0.06,
                ad_rew=-0.057,
                ad_reg=-0.032,
                ad_catch=0.95,
                diff_mean=0.853,
                diff_ci=[0.78, 0.92],
                actions=[["none", "decoy"]] * 20,
            )
        ),
        encoding="utf-8",
    )

    r15 = verda_dir / "10.0.0.2" / "1.5B-s0"
    r15.mkdir(parents=True)
    (r15 / "eval.json").write_text(
        json.dumps(
            _make_verda_eval(
                model="Qwen/Qwen2.5-1.5B-Instruct",
                base_valid=1.0,
                base_rew=-0.055,
                base_reg=-0.028,
                ad_rew=-0.066,
                ad_reg=-0.036,
                ad_catch=0.94,
                diff_mean=-0.011,
                diff_ci=[-0.031, 0.009],
                actions=[["random_seeded", "none"]] * 20,
            )
        ),
        encoding="utf-8",
    )

    b_inprog = board_dir / "canary-qwen-mole-v1"
    b_inprog.mkdir(parents=True)
    (b_inprog / "sft_curve.jsonl").write_text(
        '{"epoch": 1, "step": 15, "loss": 0.14, "sec": 5.0}\n'
        '{"epoch": 3, "step": 66, "loss": 0.09, "sec": 20.0}\n',
        encoding="utf-8",
    )
    (b_inprog / "grpo_curve.jsonl").write_text(
        '{"step": 1, "reward": 0.18, "mean_regret": 0.03, "valid_rate": 1.0, "batch_solver_acc": 0.95, "lam_catch": 0.6, "abs_kl": 0.002, "tok_ent": 0.11, "top_actions": {"most_recipients/random_peer": 4, "newest/decoy": 2}, "sec": 8.0}\n',
        encoding="utf-8",
    )

    b_win = board_dir / "canary-qwen3-0p6b-mole-v1"
    b_win.mkdir(parents=True)
    (b_win / "eval_summary.json").write_text(
        json.dumps(
            _make_v100_eval_summary(
                name="canary-qwen3-0p6b-mole-v1",
                model="Qwen3-0.6B",
                solver_acc_800k=0.90,
                solver_acc_200k=0.925,
                qwen_min_regret_800k=0.27,
                default_grok_score_800k=0.36,
                reg_diff_ci_800k=[0.07, 0.015, 0.125],
                distinct_actions=4,
            )
        ),
        encoding="utf-8",
    )
    (b_win / "eval_mole_400k.json").write_text(
        json.dumps(
            _make_verda_eval(
                model="Qwen/Qwen3-0.6B",
                base_valid=0.80,
                base_rew=-0.22,
                base_reg=-0.03,
                ad_rew=0.04,
                ad_reg=0.05,
                ad_catch=0.91,
                diff_mean=0.26,
                diff_ci=[0.18, 0.34],
                actions=[["most_recipients", "random_peer"]] * 12 + [["newest", "most_restricted_peer"]] * 8,
            )
        ),
        encoding="utf-8",
    )

    b_uncatchable = board_dir / "canary-qwen3-1p7b-mole-v1"
    b_uncatchable.mkdir(parents=True)
    (b_uncatchable / "eval_summary.json").write_text(
        json.dumps(
            _make_v100_eval_summary(
                name="canary-qwen3-1p7b-mole-v1",
                model="Qwen3-1.7B",
                solver_acc_800k=0.80,
                solver_acc_200k=0.90,
                qwen_min_regret_800k=0.31,
                default_grok_score_800k=0.36,
                reg_diff_ci_800k=[0.11, 0.04, 0.18],
                distinct_actions=3,
            )
        ),
        encoding="utf-8",
    )

    b_collapsed = board_dir / "canary-qwen-mole-v2"
    b_collapsed.mkdir(parents=True)
    (b_collapsed / "eval_summary.json").write_text(
        json.dumps(
            _make_v100_eval_summary(
                name="canary-qwen-mole-v2",
                model="Qwen2.5-1.5B-Instruct",
                solver_acc_800k=0.925,
                solver_acc_200k=0.925,
                qwen_min_regret_800k=0.28,
                default_grok_score_800k=0.36,
                reg_diff_ci_800k=[0.08, 0.02, 0.14],
                distinct_actions=1,
            )
        ),
        encoding="utf-8",
    )

    rc = rep.main([
        "--verda-dir", str(verda_dir),
        "--board-dir", str(board_dir),
        "--logs-dir", str(logs_dir),
        "--out-json", str(out_json),
        "--out-md", str(out_md),
    ])
    assert rc == 0
    assert out_json.stat().st_size < rep.MAX_SUMMARY_BYTES

    md_parent_links_dir = tmp_path / "docs" / "reports"
    md_parent_links_dir.mkdir(parents=True)
    out_md_rel = md_parent_links_dir / "qwen_mole_training.md"
    shutil.copy2(out_md, out_md_rel)
    for m in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", out_md_rel.read_text(encoding="utf-8")):
        target = m.group(1)
        if target.startswith(("http://", "https://")):
            continue
        src_target = (REPORT_MD_PATH.parent / target).resolve()
        dst_target = (out_md_rel.parent / target).resolve()
        dst_target.parent.mkdir(parents=True, exist_ok=True)
        if not dst_target.exists():
            shutil.copy2(src_target, dst_target)

    rc_check = rep.main([
        "--check",
        "--verda-dir", str(verda_dir),
        "--board-dir", str(board_dir),
        "--logs-dir", str(logs_dir),
        "--out-json", str(out_json),
        "--out-md", str(out_md_rel),
    ])
    assert rc_check == 0

    built = json.loads(out_json.read_text(encoding="utf-8"))
    assert built["verda_vanilla_grpo_heldout"]["claims_stronger_mole"] is False

    by_run = {r["run_id"]: r for r in built["v100_regularized_sft_grpo"]["runs"]}
    assert by_run["canary-qwen-mole-v1"]["status"] == "in_progress"
    assert by_run["canary-qwen-mole-v1"]["eval_summary"] is None
    assert by_run["canary-qwen-mole-v1"]["claims_stronger_mole"] is False

    assert by_run["canary-qwen3-0p6b-mole-v1"]["status"] == "completed"
    assert by_run["canary-qwen3-0p6b-mole-v1"]["verdict"] == "positive_catchable_heldout_gain"
    assert by_run["canary-qwen3-0p6b-mole-v1"]["claims_stronger_mole"] is True
    assert by_run["canary-qwen3-0p6b-mole-v1"]["eval_mole_400k"]["catchable_85"] is True

    assert by_run["canary-qwen3-1p7b-mole-v1"]["status"] == "completed"
    assert by_run["canary-qwen3-1p7b-mole-v1"]["verdict"] == "fails_catchability_85"
    assert by_run["canary-qwen3-1p7b-mole-v1"]["claims_stronger_mole"] is False

    assert by_run["canary-qwen-mole-v2"]["status"] == "completed"
    assert by_run["canary-qwen-mole-v2"]["verdict"] == "collapsed_action_space"
    assert by_run["canary-qwen-mole-v2"]["claims_stronger_mole"] is False

    bad_summary = copy.deepcopy(built)
    bad_summary["verda_vanilla_grpo_heldout"]["runs"][0]["claims_stronger_mole"] = True
    bad_summary["verda_vanilla_grpo_heldout"]["claims_stronger_mole"] = True
    errs = rep.validate_summary(bad_summary)
    assert any("collapsed adapter" in e or "format-validity-only" in e for e in errs)

    bad_v2 = copy.deepcopy(built)
    bad_v2["cpu_rl_mole_v2"]["ws3_heldout"]["rl_mole_v2"]["solver_acc"] = 0.78
    bad_v2["cpu_rl_mole_v2"]["ws3_heldout"]["rl_mole_v2"]["catchable_85"] = True
    errs_v2 = rep.validate_summary(bad_v2)
    assert any("cpu_rl_mole_v2" in e for e in errs_v2)

    out_md_rel.write_text(out_md_rel.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    rc_tampered = rep.main([
        "--check",
        "--verda-dir", str(verda_dir),
        "--board-dir", str(board_dir),
        "--logs-dir", str(logs_dir),
        "--out-json", str(out_json),
        "--out-md", str(out_md_rel),
    ])
    assert rc_tampered == 1


def test_eval_400k_catchability_gate_blocks_false_positive(tmp_path: Path):
    board_dir = tmp_path / "board"
    b_run = board_dir / "canary-qwen-mole-v2"
    b_run.mkdir(parents=True)
    (b_run / "eval_summary.json").write_text(
        json.dumps(
            _make_v100_eval_summary(
                name="canary-qwen-mole-v2",
                model="Qwen2.5-1.5B-Instruct",
                solver_acc_800k=0.90,
                solver_acc_200k=0.90,
                qwen_min_regret_800k=0.28,
                default_grok_score_800k=0.36,
                reg_diff_ci_800k=[0.08, 0.02, 0.14],
                distinct_actions=3,
            )
        ),
        encoding="utf-8",
    )
    (b_run / "eval_mole_400k.json").write_text(
        json.dumps(
            _make_verda_eval(
                model="Qwen/Qwen2.5-1.5B-Instruct",
                base_valid=1.0,
                base_rew=-0.05,
                base_reg=-0.02,
                ad_rew=0.02,
                ad_reg=0.05,
                ad_catch=0.79,
                diff_mean=0.07,
                diff_ci=[0.02, 0.12],
                actions=[["most_recipients", "random_peer"]] * 10 + [["newest", "decoy"]] * 10,
            )
        ),
        encoding="utf-8",
    )
    sec = rep.build_v100_section(board_dir, None)
    by_id = {r["run_id"]: r for r in sec["runs"]}
    assert by_id["canary-qwen-mole-v2"]["verdict"] == "fails_catchability_85"
    assert by_id["canary-qwen-mole-v2"]["claims_stronger_mole"] is False


def test_style_hygiene_zero_comments_zero_em_dashes_zero_torch():
    hash_ch = chr(35)
    em_dash = "\u2014"
    en_dash = "\u2013"

    for py_file in (SCRIPT_PATH, TEST_PATH):
        src = py_file.read_text(encoding="utf-8")
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_toks = [t for t in toks if t.type == tokenize.COMMENT]
        assert comment_toks == [], f"found comment token in {py_file}"
        assert hash_ch not in src, f"found literal hash char in {py_file}"

    for fpath in (SCRIPT_PATH, SUMMARY_PATH, REPORT_MD_PATH, TEST_PATH):
        txt = fpath.read_text(encoding="utf-8")
        assert em_dash not in txt, f"found em dash in {fpath}"
        assert en_dash not in txt, f"found en dash in {fpath}"

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
