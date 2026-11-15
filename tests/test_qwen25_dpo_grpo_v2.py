from __future__ import annotations

import ast
import importlib.util
import io
import json
import math
import sys
import tokenize
from pathlib import Path

from canary.mole.dsl import FRAME_SELECTORS, LEAK_SELECTORS

ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = ROOT / "results" / "moletrain" / "canary-qwen25-1p5b-dpo-grpo-v2"
SUMMARY_PATH = ROOT / "results" / "moletrain" / "qwen_mole_summary.json"
REPORT_MD_PATH = ROOT / "docs" / "reports" / "qwen_mole_training.md"
REPORT_SCRIPT_PATH = ROOT / "scripts" / "build_qwen_mole_report.py"
VERIFY_SCRIPT_PATH = ROOT / "scripts" / "verify_moletrain_submission.py"
TEST_PATH = Path(__file__).resolve()


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rep = _load_module("build_qwen_mole_report_v2_test", REPORT_SCRIPT_PATH)
ver = _load_module("verify_moletrain_submission_v2_test", VERIFY_SCRIPT_PATH)


def test_qwen25_dpo_grpo_v2_committed_metric_files_and_no_weights():
    assert RUN_DIR.is_dir()
    entries = {p.name for p in RUN_DIR.iterdir()}
    expected = {"eval_summary.json", "sft_curve.jsonl", "dpo_curve.jsonl", "grpo_curve.jsonl"}
    assert entries == expected

    forbidden_exts = {".safetensors", ".bin", ".pt", ".pth", ".ckpt"}
    total_bytes = 0
    for p in RUN_DIR.rglob("*"):
        assert p.is_file()
        assert p.suffix.lower() not in forbidden_exts
        sz = p.stat().st_size
        assert 0 < sz < 100 * 1024
        total_bytes += sz
    assert total_bytes < 80 * 1024

    sft_rows = [json.loads(ln) for ln in (RUN_DIR / "sft_curve.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(sft_rows) == 15
    assert sft_rows[0]["step"] == 15
    assert sft_rows[-1]["step"] == 219
    assert sft_rows[-1]["epoch"] == 3
    assert sft_rows[0]["loss"] == 0.089
    assert sft_rows[-1]["loss"] == 0.083

    dpo_rows = [json.loads(ln) for ln in (RUN_DIR / "dpo_curve.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(dpo_rows) == 16
    assert [r["step"] for r in dpo_rows] == list(range(1, 17))
    assert dpo_rows[0]["loss"] == 0.6891
    assert dpo_rows[-1]["loss"] == 0.4842
    assert dpo_rows[0]["margin"] == 0.0082
    assert dpo_rows[-1]["margin"] == 0.6456

    grpo_rows = [json.loads(ln) for ln in (RUN_DIR / "grpo_curve.jsonl").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(grpo_rows) == 60
    assert [r["step"] for r in grpo_rows] == list(range(1, 61))
    for r in grpo_rows:
        assert 0.0 <= float(r["valid_rate"]) <= 1.0
        assert 0.0 <= float(r["batch_solver_acc"]) <= 1.0
        assert isinstance(r["top_actions"], dict) and len(r["top_actions"]) >= 1


def test_qwen25_dpo_grpo_v2_eval_summary_and_paired_cis():
    es = json.loads((RUN_DIR / "eval_summary.json").read_text(encoding="utf-8"))
    assert es["name"] == "canary-qwen25-1p5b-dpo-grpo-v2"
    assert Path(es["model"]).name == "Qwen2.5-1.5B-Instruct"
    assert es["smoke_tiny"] is False
    assert es["winner_checkpoint"] == "grpo_step60"
    assert es["sft_examples"] == {
        "carbon_transcripts": 432,
        "counterfactual_expert": 75,
        "total": 582,
        "dpo_pairs": 146,
    }

    vc = es["val_candidates"]
    assert set(vc.keys()) == {"sft", "sft_dpo", "grpo_step30", "grpo_step60"}
    feasible = [
        (k, v)
        for k, v in vc.items()
        if v["solver"]["acc"] >= 0.85 and v["distinct_actions"] >= 2
    ]
    best_k, best_v = max(feasible, key=lambda kv: (kv[1]["min_regret"], kv[1]["solver"]["acc"]))
    assert best_k == "grpo_step60"
    assert best_v["min_regret"] == 0.3916
    assert best_v["solver"]["acc"] == 0.96
    assert best_v["distinct_actions"] == 6
    assert best_v["invalid_generations"] == 0

    h8 = es["heldout_800k_summary"]
    assert h8["solver"] == {"score": 0.5655, "acc": 0.9667}
    assert h8["catchable_85"] is True
    assert h8["grok_tactics"]["score"] == 0.1223
    assert h8["frontier_proxy_gap"] == 0.2748
    assert h8["min_regret"] == 0.2478
    assert h8["distinct_actions"] == 6
    assert h8["action_entropy_nats"] == 1.1061
    assert h8["invalid_generations"] == 0

    h2 = es["heldout_200k_summary"]
    assert h2["solver"] == {"score": 0.6033, "acc": 1.0}
    assert h2["catchable_85"] is True
    assert h2["grok_tactics"]["score"] == 0.1025
    assert h2["frontier_proxy_gap"] == 0.2061
    assert h2["min_regret"] == 0.2243
    assert h2["distinct_actions"] == 6
    assert h2["invalid_generations"] == 0

    for prof in (h8["action_profile"], h2["action_profile"]):
        assert math.isclose(sum(prof.values()), 1.0, abs_tol=1e-3)
        for pair in prof:
            leak_sel, frame_sel = pair.split("/", 1)
            assert leak_sel in LEAK_SELECTORS
            assert frame_sel in FRAME_SELECTORS

    p8 = es["paired_800k_vs_default"]
    assert p8["n"] == 60
    assert p8["qwen_mole"]["frontier_proxy_gap"] == [0.2748, 0.1237, 0.4313]
    assert p8["baseline"]["grok_tactics"]["score"][0] == 0.3175
    assert p8["diff_qwen_minus_baseline"]["grok_tactics_score"] == [-0.1952, -0.3028, -0.0855]
    assert p8["diff_qwen_minus_baseline"]["regret_grok_tactics"] == [0.1732, 0.0605, 0.2848]

    for pkey in (
        "paired_800k_vs_default",
        "paired_200k_vs_default",
        "paired_200k_vs_rl_mole",
        "paired_800k_vs_rl_mole_v2",
        "paired_200k_vs_rl_mole_v2",
    ):
        blk = es[pkey]
        assert blk["n"] == 60
        ci_violations: list[str] = []
        checked = ver._validate_cis_recursive(
            blk,
            pkey,
            triple_order="mean_lo_hi",
            parent_key="",
            violations=ci_violations,
        )
        assert checked >= 20
        assert ci_violations == []


def test_report_headlines_qwen25_dpo_grpo_v2_alongside_qwen3(tmp_path: Path):
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert rep.validate_summary(summary) == []

    v100 = summary["v100_regularized_sft_grpo"]
    assert v100["headline_v100_run"] == "canary-qwen25-1p5b-dpo-grpo-v2"
    assert summary["overall_honest_verdict"]["headline_v100_run"] == "canary-qwen25-1p5b-dpo-grpo-v2"
    assert v100["n_completed"] == 4
    assert v100["n_in_progress"] == 0

    by_id = {r["run_id"]: r for r in v100["runs"]}
    r_v2 = by_id["canary-qwen25-1p5b-dpo-grpo-v2"]
    assert r_v2["model"] == "Qwen2.5-1.5B-Instruct"
    assert r_v2["status"] == "completed"
    assert r_v2["dpo_curve"] == {
        "logged_points": 16,
        "last_step": 16,
        "initial_loss": 0.6891,
        "final_loss": 0.4842,
        "min_loss": 0.4766,
        "initial_margin": 0.0082,
        "final_margin": 0.6456,
        "max_margin": 0.6456,
        "sec": 52.9,
    }
    es_v2 = r_v2["eval_summary"]
    assert es_v2["winner_checkpoint"] == "grpo_step60"
    assert es_v2["heldout_800k"]["n"] == 60
    assert es_v2["heldout_800k"]["qwen_solver_score"] == 0.5655
    assert es_v2["heldout_800k"]["qwen_solver_acc"] == 0.9667
    assert es_v2["heldout_800k"]["frontier_proxy_gap"] == 0.2748
    assert es_v2["heldout_800k"]["frontier_proxy_gap_ci95"] == [0.1237, 0.4313]
    assert es_v2["heldout_800k"]["qwen_grok_tactics_score"] == 0.1223
    assert es_v2["heldout_800k"]["default_grok_tactics_score"] == 0.3175
    assert es_v2["heldout_800k"]["paired_diff_grok_tactics_score"] == [-0.1952, -0.3028, -0.0855]
    assert es_v2["heldout_800k"]["distinct_actions"] == 6
    assert es_v2["heldout_800k"]["invalid_generations"] == 0
    assert es_v2["heldout_200k"]["qwen_solver_score"] == 0.6033
    assert es_v2["heldout_200k"]["qwen_solver_acc"] == 1.0

    for peer_id, exp_model in (
        ("canary-qwen3-1p7b-mole-v1", "Qwen3-1.7B"),
        ("canary-qwen3-0p6b-mole-v1", "Qwen3-0.6B"),
    ):
        pr = by_id[peer_id]
        assert pr["model"] == exp_model
        assert pr["status"] == "completed"
        assert pr["eval_summary"]["heldout_800k"]["catchable_85"] is True
        assert pr["eval_summary"]["heldout_200k"]["catchable_85"] is True
        assert pr["eval_summary"]["heldout_800k"]["distinct_actions"] >= 4

    md = REPORT_MD_PATH.read_text(encoding="utf-8")
    assert md == rep.render_markdown(summary)
    for token in (
        "canary-qwen25-1p5b-dpo-grpo-v2",
        "Qwen2.5-1.5B-Instruct",
        "grpo_step60",
        "+0.5655",
        "0.9667",
        "+0.2748 [+0.1237, +0.4313]",
        "+0.1223",
        "+0.3175",
        "-0.1952",
        "+0.6033",
        "Qwen3-1.7B",
        "Qwen3-0.6B",
    ):
        assert token in md

    mock_log = tmp_path / "dpo_v2.log"
    val_dpo = {
        "solver": {"score": 0.5108, "acc": 0.92},
        "grok_tactics": {"score": 0.0844, "acc": 0.24},
        "heuristic": {"score": -0.0424, "acc": 0.64},
        "hinted_heuristic": {"score": 0.2884, "acc": 0.68},
        "min_regret": 0.2224,
        "strongest_inv": "hinted_heuristic",
        "catchable_85": True,
        "distinct_actions": 6,
        "action_entropy_nats": 1.1743,
        "action_profile": {"random_seeded/random_peer": 0.5, "most_recipients/random_peer": 0.5},
        "invalid_generations": 2,
    }
    mock_log.write_text(
        "\n".join([
            "[init] device=cuda model=/models/Qwen2.5-1.5B-Instruct",
            "[data] carbon_sft=432 expert_sft=75 total_sft=582 dpo_pairs=146 grpo_prompts=110",
            '[dpo] {"step": 4, "loss": 0.5964, "margin": 0.2092, "sec": 13.2}',
            f"[val sft_dpo] {json.dumps(val_dpo)}",
        ])
        + "\n",
        encoding="utf-8",
    )
    plog = rep.parse_v100_gpu_log(mock_log)
    assert plog["data_mix"] == {
        "carbon_sft": 432,
        "expert_sft": 75,
        "total_sft": 582,
        "dpo_pairs": 146,
        "grpo_prompts": 110,
    }
    assert len(plog["dpo_rows"]) == 1
    assert "sft_dpo" in plog["val_checkpoints"]


def test_hygiene_and_submission_verifier_with_new_test_registered(tmp_path: Path):
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    co_author = "co-authored" + "-by"
    forbidden_imports = {"torch", "transformers", "peft", "trl"}

    for py_path in (REPORT_SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert hash_ch not in src
        assert em_dash not in src
        assert en_dash not in src
        assert co_author not in src.lower()
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert [t for t in toks if t.type == tokenize.COMMENT] == []
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    for art_path in (*RUN_DIR.iterdir(), SUMMARY_PATH, REPORT_MD_PATH):
        txt = art_path.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert co_author not in txt.lower()

    gate_out = tmp_path / "gate_check.json"
    report = ver.run_all_gates(
        root=ROOT,
        out_path=gate_out,
        py_files=(*ver.MOLETRAIN_PY_FILES, "tests/test_qwen25_dpo_grpo_v2.py"),
    )
    assert report["all_passed"] is True
    assert report["gates_passed"] == 4
