from __future__ import annotations

import ast
import copy
import io
import json
import sys
import tokenize
from pathlib import Path

import pytest

import scripts.tiebreak_forensics as tf
from scripts.tiebreak_forensics import (
    MAX_JSON_BYTES,
    SCHEMA_VERSION,
    analyze_ws4_v2_root_causes,
    build_forensics_report,
    build_verda_v3_complete_matrix,
    main,
    render_markdown,
    validate_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_forensics.py"
SELF_PATH = Path(__file__).resolve()
COMMITTED_JSON = REPO_ROOT / "results" / "tiebreak" / "forensics_prior_runs.json"
COMMITTED_MD = REPO_ROOT / "results" / "tiebreak" / "forensics_prior_runs.md"


def test_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)

    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"comment tokens found in {path}"
        assert hash_char not in src, f"hash character found in {path}"
        assert em_dash not in src, f"em dash found in {path}"
        assert en_dash not in src, f"en dash found in {path}"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    assert root not in ("torch", "transformers")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                assert root not in ("torch", "transformers")

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    for artifact in (COMMITTED_JSON, COMMITTED_MD):
        assert artifact.exists(), f"missing committed artifact: {artifact}"
        text = artifact.read_text(encoding="utf-8")
        assert em_dash not in text, f"em dash found in {artifact}"
        assert en_dash not in text, f"en dash found in {artifact}"
        assert text.isascii(), f"non-ASCII character found in {artifact}"
    assert COMMITTED_JSON.stat().st_size <= MAX_JSON_BYTES


def test_verify_committed_json_and_md_offline(tmp_path: Path) -> None:
    rc = main(["--verify-json", str(COMMITTED_JSON)])
    assert rc == 0

    report = json.loads(COMMITTED_JSON.read_text(encoding="utf-8"))
    assert report["schema_version"] == SCHEMA_VERSION

    p44200 = report["j4_runs"]["pilot_44200"]
    assert p44200["status"] == "host_ram_oom_killed"
    assert p44200["oom_kill_events"] == 1

    v1 = report["j4_runs"]["v1_44397"]
    assert v1["eval"]["raw_total_episodes_across_subdirs"] == 19
    v1_dedup = v1["eval"]["eval_lora_dedup_first_seen"]["overall"]
    assert v1_dedup["n"] == 12
    assert v1_dedup["mean_score"] == pytest.approx(-0.25, abs=1e-3)
    assert v1_dedup["ci95"] == pytest.approx(0.2559, abs=1e-3)
    assert v1["eval"]["eval_base"]["overall"]["parse_valid_call_rate"] == pytest.approx(0.0817, abs=1e-3)
    assert v1_dedup["env_ok_step_rate"] >= 0.99

    v2_tr = report["j4_runs"]["ws4_v2_44410"]["train"]
    assert v2_tr["header_tokens"] == 2842
    assert v2_tr["body_budget_tokens"] == 1254
    assert v2_tr["max_len"] == 4096
    assert v2_tr["header_frac"] == pytest.approx(0.6938, abs=1e-3)
    assert v2_tr["loss_token_frac_logged"] == pytest.approx(0.027, abs=1e-3)

    b14 = report["j4_runs"]["ws4_v2_44410"]["eval_base_44411"]["episodes"]["overall"]
    assert b14["n"] == 16
    assert b14["mean_score"] == 0.0
    assert b14["parse_valid_call_rate"] == pytest.approx(0.0297, abs=1e-3)

    v2_all = report["j4_runs"]["ws4_v2_44410"]["eval_v2_44412"]["episodes"]["overall"]
    assert v2_all["n"] == 82
    assert v2_all["mean_score"] == pytest.approx(-0.395, abs=1e-3)
    assert v2_all["ci95"] == pytest.approx(0.1283, abs=1e-3)
    assert v2_all["accused_rate"] == pytest.approx(0.5122, abs=1e-3)
    assert v2_all["accuracy"] == pytest.approx(0.061, abs=1e-3)
    assert v2_all["abstain_rate"] == pytest.approx(0.4878, abs=1e-3)
    assert v2_all["parse_valid_call_rate"] == pytest.approx(0.9222, abs=1e-3)

    sec = report["unpaired_secret_audit"]
    assert sec["paired"] is False
    assert sec["eval_44411_base_sha256"] == "f272803cdb679dbe"
    assert sec["eval_44412_v2_sha256"] == "c86b9c8a54f8b269"

    rc_all = report["ws4_v2_root_cause"]["overall"]
    assert rc_all["accused_episodes"] == 42
    assert rc_all["dropped_plant_canary_turns"] == 54
    assert rc_all["total_plant_canary_turns"] == 80
    assert rc_all["dropped_list_employees_turns"] == 68
    assert rc_all["total_list_employees_turns"] == 70
    assert rc_all["below_breakeven_count"] == 40
    assert rc_all["below_breakeven_frac"] == pytest.approx(40 / 42, abs=1e-4)
    assert rc_all["p_le_005_count"] == 25
    assert rc_all["p_le_005_frac"] == pytest.approx(25 / 42, abs=1e-4)

    bad_report = copy.deepcopy(report)
    bad_report["unpaired_secret_audit"]["paired"] = True
    assert validate_report(bad_report) != []

    bad_md = tmp_path / "drifted.md"
    bad_md.write_text(render_markdown(report) + "\nextra drift line\n", encoding="utf-8")
    assert main(["--verify-json", str(COMMITTED_JSON), "--verify-md", str(bad_md)]) == 1
    assert main(["--verify-json", str(tmp_path / "missing.json")]) == 1


def _make_synthetic_accused_episode() -> dict:
    employees = [{"id": f"e{i:02d}", "name": f"Emp {i}", "dept": "Eng", "role": "eng"} for i in range(12)]
    assignment = {f"e{i:02d}": ("A" if i == 0 else "B") for i in range(12)}
    steps = [
        {
            "t": 0,
            "day": 1,
            "tool": "list_employees",
            "args": {},
            "result": {"ok": True, "data": {"employees": employees}, "error": None},
        },
        {
            "t": 1,
            "day": 1,
            "tool": "status",
            "args": {},
            "result": {"ok": True, "data": {"day": 1, "V": 1.0, "restricted": []}, "error": None},
        },
        {
            "t": 2,
            "day": 1,
            "tool": "plant_canary",
            "args": {"doc_title": "Memo 1", "assignment": assignment},
            "result": {"ok": True, "data": {"canary_id": "c1-1"}, "error": None},
        },
        {
            "t": 3,
            "day": 1,
            "tool": "advance_day",
            "args": {},
            "result": {"ok": True, "data": {"closed_day": 1, "day": 2, "V": 0.94}, "error": None},
        },
    ]
    big_blob = "x" * 1200
    for idx in range(6):
        steps.append(
            {
                "t": 4 + idx,
                "day": 2,
                "tool": "status",
                "args": {},
                "result": {"ok": True, "data": {"day": 2, "V": 0.69, "pad": big_blob}, "error": None},
            }
        )
    steps.append(
        {
            "t": 10,
            "day": 2,
            "tool": "check_leak_feed",
            "args": {},
            "result": {
                "ok": True,
                "data": {"items": [{"surfaced_day": 2, "doc_id": "c1-1", "variant": "A"}]},
                "error": None,
            },
        }
    )
    steps.append(
        {
            "t": 11,
            "day": 2,
            "tool": "accuse",
            "args": {"employee": "e01"},
            "result": {"ok": True, "data": {"accused": "e01", "episode_over": True}, "error": None},
        }
    )
    return {
        "tier": "easy",
        "seed": 800_000,
        "agent": "hf-lora:lora",
        "steps": steps,
        "score": -1.0,
        "accused": "e01",
        "correct": False,
        "final_day": 2,
        "end_reason": "accused",
        "meta": {"invalid_calls": 0, "V": 0.94},
    }


def test_root_cause_replay_synthetic_fixture() -> None:
    ep = _make_synthetic_accused_episode()
    instr = {"easy": "Tier: easy. Known V mode: true V is hidden until leaks surface.", "medium": "", "hard": ""}
    res = analyze_ws4_v2_root_causes(
        [ep],
        instr_by_tier=instr,
        header_tokens=2842,
        max_len=4096,
        chars_per_token=4.0,
    )
    ov = res["overall"]
    assert ov["accused_episodes"] == 1
    assert ov["total_plant_canary_turns"] == 1
    assert ov["dropped_plant_canary_turns"] == 1
    assert ov["total_list_employees_turns"] == 1
    assert ov["dropped_list_employees_turns"] == 1
    assert ov["episodes_missing_employee_roster_at_accuse"] == 1
    assert ov["below_breakeven_count"] == 1
    assert ov["p_le_005_count"] == 1
    assert ov["ruled_out_by_surfaced_canary_count"] == 1
    case = res["sample_ruled_out_cases"][0]
    assert case["accused"] == "e01"
    assert case["top_emp_full"] == "e00"
    assert case["p_full_accused"] <= 0.05


def test_end_to_end_cli_synthetic_tree_with_git_fallback(tmp_path: Path) -> None:
    j4 = tmp_path / "j4"
    v3 = tmp_path / "v3"
    (j4 / "run-44397" / "runs" / "eval-base").mkdir(parents=True)
    (j4 / "run-44397" / "runs" / "eval-lora").mkdir(parents=True)
    (j4 / "run-44397" / "runs" / "eval-lora-par").mkdir(parents=True)
    (j4 / "runs" / "ws4-base-v14").mkdir(parents=True)
    (j4 / "runs" / "ws4-v2-44410").mkdir(parents=True)
    (j4 / "runs" / "ws4-base-v14-off6").mkdir(parents=True)
    (v3 / "run-44555").mkdir(parents=True)
    (v3 / "run-44572").mkdir(parents=True)

    (j4 / "slurm-44200.out").write_text(
        "cuda True Tesla V100-PCIE-32GB\n"
        "line 40: 123 Killed python -m train.lora_sft --pilot\n"
        "error: Detected 1 oom_kill event in StepId=44200.batch.\n",
        encoding="utf-8",
    )
    (j4 / "slurm-44397.out").write_text(
        "[data] episodes=10 windows=20 tokens=1000 loss_tokens=20 max_window=4096\n"
        "trainable params: 18,464,768 || all params: 1,562,179,072 || trainable%: 1.1820\n"
        "[train] {'step': 10, 'loss': 0.5, 'lr': 1e-4, 'tok_per_s': 1400.0, 'elapsed_s': 10.0}\n"
        "[train] time box hit at step 10\n"
        "[summary] {\"device\": \"cuda\", \"steps\": 10, \"tokens\": 1000, \"seconds\": 10.0, "
        "\"tokens_per_s\": 1400.0, \"windows\": 20, \"steps_per_epoch\": 20, \"full_run_steps\": 20, \"est_full_run_hours\": 1.0}\n"
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 aaaa1111bbbb2222)\n"
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 cccc3333dddd4444)\n"
        "*** JOB 44397 ON node CANCELLED AT 2026-11-14T06:17:46 DUE TO TIME LIMIT ***\n",
        encoding="utf-8",
    )
    (j4 / "run-44397" / "eval-lora-par.log").write_text(
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 eeee5555ffff6666)\n",
        encoding="utf-8",
    )

    abstain_ep = {
        "tier": "easy",
        "seed": 800_000,
        "agent": "hf:base",
        "steps": [{"t": 0, "day": 1, "tool": "status", "args": {}, "result": {"ok": True, "data": {"day": 1, "V": 1.0}}}],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 1,
        "end_reason": "eval_cap",
        "meta": {"invalid_calls": 1},
    }
    accused_ep = _make_synthetic_accused_episode()
    med_ep = copy.deepcopy(abstain_ep)
    med_ep["tier"] = "medium"
    hard_ep = copy.deepcopy(abstain_ep)
    hard_ep["tier"] = "hard"

    (j4 / "run-44397" / "runs" / "eval-base" / "episodes.jsonl").write_text(json.dumps(abstain_ep) + "\n", encoding="utf-8")
    (j4 / "run-44397" / "runs" / "eval-lora" / "episodes.jsonl").write_text(json.dumps(accused_ep) + "\n", encoding="utf-8")
    (j4 / "run-44397" / "runs" / "eval-lora-par" / "episodes.jsonl").write_text(json.dumps(abstain_ep) + "\n", encoding="utf-8")

    (j4 / "slurm-44410.out").write_text(
        "[data] accuse_loss_share=0.0503 oversample_endings=3\n"
        "[data] episodes=800 windows=100 tokens=40000 loss_tokens=1080 loss_frac=0.027 mode=dense max_len=4096 max_window=4096\n"
        "[data] header(system+tools+kickoff)=2842 tokens, body budget=1254\n"
        "trainable params: 18,464,768 || all params: 1,562,179,072 || trainable%: 1.1820\n"
        "[train] {'step': 10, 'loss': 0.25, 'lr': 1e-4, 'tok_per_s': 1480.0, 'elapsed_s': 10.0}\n"
        "[train] time box hit at step 10\n"
        "[summary] {\"device\": \"cuda\", \"steps\": 10, \"tokens\": 4000, \"seconds\": 10.0, "
        "\"tokens_per_s\": 1480.0, \"windows\": 100, \"steps_per_epoch\": 20, \"full_run_steps\": 20, \"est_full_run_hours\": 1.0}\n",
        encoding="utf-8",
    )
    (j4 / "eval-44411.out").write_text(
        "[j4-eval] host=node model=base run=ws4-base-v14\n"
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 1111222233334444)\n"
        "[ep] easy 800000 score=0.000 correct=False steps=1 invalid=1 t=10s\n",
        encoding="utf-8",
    )
    (j4 / "eval-44412.out").write_text(
        "[j4-eval] host=node model=lora run=ws4-v2-44410\n"
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 5555666677778888)\n"
        "[ep] easy 800000 score=-1.000 correct=False steps=11 invalid=0 t=10s\n",
        encoding="utf-8",
    )
    (j4 / "eval-44583.out").write_text(
        "[j4-eval] host=node model=base run=ws4-base-v14-n30\n"
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 99990000aaaabbbb)\n"
        "*** JOB 44583 ON node CANCELLED AT 2026-11-14T22:37:45 DUE to SIGNAL Terminated ***\n",
        encoding="utf-8",
    )
    (j4 / "eval-44584.out").write_text(
        "[j4-eval] host=node model=base run=ws4-base-v14-off6\n"
        "no CANARY_WORLD_SECRET/SALT: judge worlds use a fresh per-process secret (sha256 ccccddddeeeeffff)\n"
        "[ep] easy 800006 score=0.000 correct=False steps=1 invalid=1 t=10s\n",
        encoding="utf-8",
    )

    (j4 / "runs" / "ws4-base-v14" / "episodes.jsonl").write_text(json.dumps(abstain_ep) + "\n", encoding="utf-8")
    (j4 / "runs" / "ws4-v2-44410" / "episodes.jsonl").write_text(
        "\n".join(json.dumps(x) for x in (accused_ep, med_ep, hard_ep)) + "\n",
        encoding="utf-8",
    )
    (j4 / "runs" / "ws4-base-v14-off6" / "episodes.jsonl").write_text(json.dumps(abstain_ep) + "\n", encoding="utf-8")

    oom_txt = (
        "[v3] adapter=/path/lora seed=0 out=/path/out\n"
        "[v3] 2000 states from TRAIN seeds 150000+ tiers=['easy', 'medium'] (18.0s)\n"
        "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 5.49 GiB. "
        "GPU 0 has a total capacity of 31.73 GiB of which 5.09 GiB is free. "
        "Including non-PyTorch memory, this process has 26.63 GiB memory in use. "
        "Of the allocated memory 20.63 GiB is allocated by PyTorch, and 5.64 GiB is reserved\n"
    )
    (v3 / "slurm-44548.out").write_text(oom_txt, encoding="utf-8")
    (v3 / "slurm-44550.out").write_text(oom_txt.replace("seed=0", "seed=1"), encoding="utf-8")

    curve_line = json.dumps(
        {
            "step": 0,
            "reward": 0.4,
            "reward_valid": 0.4,
            "gain_vs_solver_valid": -0.3,
            "valid": 1.0,
            "accuse_frac": 0.25,
            "accuse_correct": 0.5,
            "continue_frac": 0.75,
            "zero_var_groups": 2,
            "kl": 0.01,
            "sec": 75.0,
            "elapsed_h": 0.02,
        }
    )
    (v3 / "slurm-44553.out").write_text(
        curve_line + "\n*** JOB 44553 ON node CANCELLED AT 2026-11-14T20:28:16 DUE to SIGNAL Terminated ***\n",
        encoding="utf-8",
    )
    (v3 / "slurm-44555.out").write_text(
        curve_line + "\n*** JOB 44555 ON node CANCELLED AT 2026-11-14T21:29:40 DUE to SIGNAL Terminated ***\n",
        encoding="utf-8",
    )
    (v3 / "run-44555" / "curve.jsonl").write_text(curve_line + "\n", encoding="utf-8")
    (v3 / "slurm-44572.out").write_text(curve_line + "\n", encoding="utf-8")
    (v3 / "run-44572" / "curve.jsonl").write_text(curve_line + "\n", encoding="utf-8")

    out_json = tmp_path / "out" / "forensics_prior_runs.json"
    out_md = tmp_path / "out" / "forensics_prior_runs.md"
    rc_gen = main(
        [
            "--j4-dir",
            str(j4),
            "--v3-dir",
            str(v3),
            "--verda-git-spec",
            "refs/does-not-exist:missing/curve.jsonl",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )
    assert rc_gen == 0
    gen_data = json.loads(out_json.read_text(encoding="utf-8"))
    assert gen_data["v3_grpo_runs"]["verda_curve_s0"]["available"] is False
    assert gen_data["v3_grpo_runs"]["verda_curve_s0"]["status"] == "git_ref_unavailable_fallback"
    assert main(["--verify-json", str(out_json)]) == 0


def test_validate_report_catches_dashes_and_accounting_drift() -> None:
    report = json.loads(COMMITTED_JSON.read_text(encoding="utf-8"))
    em_dash = chr(0x2014)

    dash_report = copy.deepcopy(report)
    dash_report["lessons_for_tiebreak_v4"][0] = "bad" + em_dash + "dash"
    errs_dash = validate_report(dash_report)
    assert any("dash" in e for e in errs_dash)

    drift_report = copy.deepcopy(report)
    drift_report["ws4_v2_root_cause"]["overall"]["below_breakeven_count"] = 39
    errs_drift = validate_report(drift_report)
    assert any("below_breakeven_frac" in e for e in errs_drift)

    header_drift = copy.deepcopy(report)
    header_drift["j4_runs"]["ws4_v2_44410"]["train"]["header_tokens"] = 2800
    errs_hdr = validate_report(header_drift)
    assert any("header_tokens" in e for e in errs_hdr)

    verda_drift = copy.deepcopy(report)
    verda_drift["verda_v3_complete_matrix"]["v3_8k_replicates"]["v3_8k_s3"]["truly_paired_8k_vs_4k_at_8k"]["mean_delta"] = 0.25
    errs_verda = validate_report(verda_drift)
    assert any("v3_8k_s3" in e for e in errs_verda)


def test_verda_v3_complete_matrix_and_fresh_clone_safety(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = json.loads(COMMITTED_JSON.read_text(encoding="utf-8"))
    for key in (
        "j4_runs",
        "unpaired_secret_audit",
        "ws4_v2_root_cause",
        "v3_grpo_runs",
        "verda_v3_complete_matrix",
        "lessons_for_tiebreak_v4",
    ):
        assert key in report

    vm = report["verda_v3_complete_matrix"]
    assert vm["fresh_clone_safe"] is True
    assert "post-hoc locked" in vm["panel_fix_a_disclosure"]

    pbase = vm["pooled_base"]
    assert pbase["n"] == 36
    assert pbase["mean_score"] == 0.0
    assert pbase["valid_call_rate"] == pytest.approx(0.03, abs=1e-3)
    assert pbase["components"]["eval_44411"]["n"] == 16
    assert pbase["components"]["eval_44584"]["n"] == 20

    pv2 = vm["pooled_v2"]
    assert pv2["n"] == 172
    assert pv2["mean_score"] == pytest.approx(-0.457, abs=1e-3)
    assert pv2["ci95"] == pytest.approx(0.086, abs=1e-3)
    assert pv2["components"]["eval_44412"]["n"] == 82
    assert pv2["components"]["eval_44412"]["mean_score"] == pytest.approx(-0.395, abs=1e-3)
    assert pv2["components"]["eval_44412"]["ci95"] == pytest.approx(0.128, abs=1e-3)
    assert pv2["components"]["v2_off30"]["n"] == 90
    assert pv2["components"]["v2_off30"]["mean_score"] == pytest.approx(-0.514, abs=1e-3)
    assert pv2["components"]["v2_off30"]["ci95"] == pytest.approx(0.115, abs=1e-3)

    v3_fam = vm["v3_4k_family"]
    ps0 = v3_fam["pooled_v3_4k_s0"]
    assert ps0["n"] == 180
    assert ps0["mean_score"] == pytest.approx(-0.147, abs=1e-3)
    assert ps0["ci95"] == pytest.approx(0.063, abs=1e-3)
    assert ps0["valid_call_rate"] == pytest.approx(1.0, abs=1e-3)
    assert ps0["accused_count"] == 38
    assert ps0["accused_rate"] == pytest.approx(0.21, abs=1e-2)
    assert ps0["correct_count"] == 6
    assert ps0["precision_when_accused"] == pytest.approx(0.16, abs=1e-2)
    assert ps0["two_sample_delta_vs_v2"]["mean_delta"] == pytest.approx(0.310, abs=1e-3)
    assert ps0["two_sample_delta_vs_v2"]["ci95"] == pytest.approx(0.107, abs=1e-3)

    s1_part = v3_fam["v3_4k_s1_partial"]
    assert s1_part["grpo_steps"] == 192
    assert s1_part["n"] == 25
    assert s1_part["mean_score"] == pytest.approx(-0.240, abs=1e-3)
    assert s1_part["ci95"] == pytest.approx(0.171, abs=1e-3)

    spot_714d = v3_fam["v3_4k_s1_spot_714d"]
    assert spot_714d["verda_instance"] == "714d8144"
    assert spot_714d["spot_preempted"] is True
    assert spot_714d["n"] == 0

    c8k = vm["v3_4k_s0_at_8k_confound"]
    assert c8k["shared_world_secret"] == "1ca0c2a64d"
    assert c8k["n"] == 90
    assert c8k["mean_score"] == pytest.approx(-0.716, abs=1e-3)
    assert c8k["ci95"] == pytest.approx(0.105, abs=1e-3)
    assert c8k["two_sample_delta_vs_4k"]["mean_delta"] == pytest.approx(-0.568, abs=1e-3)
    assert c8k["two_sample_delta_vs_4k"]["ci95"] == pytest.approx(0.123, abs=1e-3)

    r8k = vm["v3_8k_replicates"]
    assert r8k["v3_8k_s1"]["n"] == 90
    assert r8k["v3_8k_s1"]["mean_score"] == pytest.approx(-0.777, abs=1e-3)
    assert r8k["v3_8k_s1"]["ci95"] == pytest.approx(0.118, abs=1e-3)
    assert r8k["v3_8k_s2"]["n"] == 90
    assert r8k["v3_8k_s2"]["mean_score"] == pytest.approx(-0.050, abs=1e-3)
    assert r8k["v3_8k_s2"]["ci95"] == pytest.approx(0.049, abs=1e-3)
    assert r8k["v3_8k_s3"]["shared_world_secret"] == "1ca0c2a64d"
    assert r8k["v3_8k_s3"]["n"] == 90
    assert r8k["v3_8k_s3"]["mean_score"] == pytest.approx(-0.788, abs=1e-3)
    assert r8k["v3_8k_s3"]["ci95"] == pytest.approx(0.117, abs=1e-3)
    paired_8k = r8k["v3_8k_s3"]["truly_paired_8k_vs_4k_at_8k"]
    assert paired_8k["mean_delta"] == pytest.approx(-0.073, abs=1e-3)
    assert paired_8k["ci95"] == pytest.approx(0.173, abs=1e-3)

    bare_root = tmp_path / "bare_clone"
    bare_root.mkdir(parents=True)
    bare_vm = build_verda_v3_complete_matrix(repo_root=bare_root)
    assert bare_vm["verda_dir_present"] is False
    assert bare_vm["in_tree_verda_files_present"] == 0
    assert bare_vm["pooled_base"] == vm["pooled_base"]
    assert bare_vm["pooled_v2"] == vm["pooled_v2"]
    assert bare_vm["v3_4k_family"] == vm["v3_4k_family"]
    assert bare_vm["v3_4k_s0_at_8k_confound"] == vm["v3_4k_s0_at_8k_confound"]
    assert bare_vm["v3_8k_replicates"] == vm["v3_8k_replicates"]

    fallback_json = bare_root / "results" / "tiebreak" / "forensics_prior_runs.json"
    fallback_json.parent.mkdir(parents=True)
    fallback_json.write_text(COMMITTED_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    missing_j4 = tmp_path / "no_j4"
    missing_v3 = tmp_path / "no_v3"
    monkeypatch.setattr(tf, "DEFAULT_J4_DIR", missing_j4)
    monkeypatch.setattr(tf, "DEFAULT_V3_DIR", missing_v3)
    rebuilt = build_forensics_report(j4_dir=missing_j4, v3_dir=missing_v3, repo_root=bare_root)
    assert validate_report(rebuilt, md_text=render_markdown(rebuilt)) == []


