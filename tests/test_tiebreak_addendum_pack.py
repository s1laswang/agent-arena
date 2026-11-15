from __future__ import annotations

import ast
import io
import json
import shutil
import sys
import time
import tokenize
from pathlib import Path
from typing import Any

import pytest

import scripts.tiebreak_addendum_pack as pack

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_addendum_pack.py"
READINESS_JSON_PATH = REPO_ROOT / "results" / "tiebreak" / "addendum_readiness.json"
ADDENDUM_MD_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_panel_e_addendum.md"
SELF_PATH = Path(__file__).resolve()


def _clone_minimal_repo(dst_root: Path) -> Path:
    rel_files = [
        "train/compact_render.py",
        "train/eval_compact_hf.py",
        "train/eval_hf.py",
        "train/empirical_bayes_policy.py",
        "scripts/tiebreak_scaling_calibration.py",
        "results/tiebreak/empirical_bayes/summary.json",
        "results/tiebreak/scaling/scaling_summary.json",
    ]
    for rel in rel_files:
        src = REPO_ROOT / rel
        target = dst_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return dst_root


def _make_passing_qwen_summary(
    run_id: str = "qwen15b-compact-dagger-r1",
    model: str = "Qwen2.5-1.5B-Instruct LoRA r=16 + Compact DAgger r1",
    explicit_after_ci: bool = True,
) -> dict[str, Any]:
    deltas = [0.65 if i % 3 != 0 else (-1.0 if i % 15 == 0 else 0.0) for i in range(90)]
    mean_d, hw_d = pack._mean_ci95(deltas)
    after_obj: dict[str, Any] = {
        "n": 90,
        "mean_score": round(mean_d, 6),
        "valid_call_rate": 0.995,
        "world_secret_tag": "sha256:ebf2f09716cf76d3",
        "replay_verified": True,
        "invalid_episodes": 0,
    }
    if explicit_after_ci:
        after_obj["ci95_low"] = round(mean_d - hw_d, 6)
        after_obj["ci95_high"] = round(mean_d + hw_d, 6)

    return {
        "run_id": run_id,
        "model": model,
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "n": 90,
        "train_seeds": {"start": 115000, "stop": 115600},
        "eval_seeds": {"start": 800000, "stop": 800030},
        "replay_verified": True,
        "invalid_episodes": 0,
        "before": {
            "n": 90,
            "mean_score": 0.0,
            "ci95": 0.0,
            "accuse_rate": 0.0,
            "valid_call_rate": 0.03,
            "world_secret_tag": "sha256:ebf2f09716cf76d3",
            "replay_verified": True,
            "invalid_episodes": 0,
        },
        "after": after_obj,
        "paired": {
            "mean_delta": round(mean_d, 6),
            "ci95_low": round(mean_d - hw_d, 6),
            "ci95_high": round(mean_d + hw_d, 6),
            "deltas": deltas,
        },
        "notes": "On-policy compact-memory DAgger r1 evaluated under shared world secret.",
    }


def test_source_and_generated_artifacts_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_imports = {"torch", "transformers", "peft", "google"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    for artifact in (READINESS_JSON_PATH, ADDENDUM_MD_PATH):
        assert artifact.is_file()
        txt = artifact.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert pack._has_affirmative_prereg_0_29(txt) == []


def test_live_repo_check_mode_and_latency(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    rc = pack.main(["--repo-root", str(REPO_ROOT), "--check"])
    elapsed = time.perf_counter() - t0

    assert rc == 0
    assert elapsed < 1.0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["track1_llm_dagger_status"] == "AWAITING_V100_COMPLETION"
    assert out["readme_qwen_addendum_eligible"] is False
    assert out["track2_passing_count"] >= 2

    readiness = json.loads(READINESS_JSON_PATH.read_text(encoding="utf-8"))
    rs = readiness["readiness_summary"]
    assert rs["unclassified_runs_count"] == 0
    assert "empirical-bayes-v14" in rs["track2_passing_run_ids"]
    assert "scaling-logistic-v14" in rs["track2_passing_run_ids"]
    for t2 in readiness["track_2_runs"]:
        assert t2["track"] == "track_2"
        assert t2["is_open_weight_llm"] is False
        assert t2["verdict"] == "PASS_NON_LLM_CONTROL"


def test_stale_artifacts_rejected_in_check_mode(tmp_path: Path) -> None:
    syn = _clone_minimal_repo(tmp_path)
    assert pack.main(["--repo-root", str(syn)]) == 0
    assert pack.main(["--repo-root", str(syn), "--check"]) == 0

    md_path = syn / "docs" / "reports" / "tiebreak_panel_e_addendum.md"
    md_path.write_text(md_path.read_text(encoding="utf-8") + "\nextra stale line\n", encoding="utf-8")
    assert pack.main(["--repo-root", str(syn), "--check"]) == 1


def test_synthetic_passing_track1_qwen_dagger_auto_promotes(tmp_path: Path) -> None:
    syn = _clone_minimal_repo(tmp_path)

    q15_dir = syn / "results" / "tiebreak" / "qwen15b_compact_dagger"
    q15_dir.mkdir(parents=True, exist_ok=True)
    q15_summary = _make_passing_qwen_summary(
        run_id="qwen15b-compact-dagger-r1",
        model="Qwen2.5-1.5B-Instruct LoRA r=16 + Compact DAgger r1",
        explicit_after_ci=False,
    )
    (q15_dir / "summary.json").write_text(json.dumps(q15_summary, indent=2), encoding="utf-8")

    q05_dir = syn / "results" / "tiebreak" / "qwen05b_compact_dagger"
    q05_dir.mkdir(parents=True, exist_ok=True)
    q05_summary = _make_passing_qwen_summary(
        run_id="qwen05b-compact-dagger-r1",
        model="Qwen2.5-0.5B-Instruct LoRA + Compact DAgger r1",
        explicit_after_ci=True,
    )
    (q05_dir / "summary.json").write_text(json.dumps(q05_summary, indent=2), encoding="utf-8")

    raw_dir = syn / "results" / "tiebreak" / "frugal_raw_dagger"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_summary = _make_passing_qwen_summary(
        run_id="qwen15b-frugal-raw4k-dagger-r1",
        model="Qwen2.5-1.5B-Instruct Frugal Raw4k DAgger r1",
        explicit_after_ci=True,
    )
    (raw_dir / "summary.json").write_text(json.dumps(raw_summary, indent=2), encoding="utf-8")

    assert pack.main(["--repo-root", str(syn)]) == 0
    assert pack.main(["--repo-root", str(syn), "--check"]) == 0

    readiness = json.loads((syn / "results" / "tiebreak" / "addendum_readiness.json").read_text(encoding="utf-8"))
    md_text = (syn / "docs" / "reports" / "tiebreak_panel_e_addendum.md").read_text(encoding="utf-8")

    rs = readiness["readiness_summary"]
    assert rs["track1_llm_dagger_status"] == "PROMOTED_FOR_ADDENDUM"
    assert rs["readme_qwen_addendum_eligible"] is True
    assert rs["readme_addendum_action"] == "APPEND_TO_README"
    assert rs["track1_passing_count"] == 3
    assert rs["track1_llm_passing_count"] == 3
    assert set(rs["promoted_track1_llm_run_ids"]) == {
        "qwen15b-compact-dagger-r1",
        "qwen05b-compact-dagger-r1",
        "qwen15b-frugal-raw4k-dagger-r1",
    }

    by_id = {r["run_id"]: r for r in readiness["track_1_runs"]}
    assert by_id["qwen15b-compact-dagger-r1"]["after_ci95_source"] == "paired_deltas_deterministic_before"
    assert by_id["qwen05b-compact-dagger-r1"]["family"] == "Qwen2.5-0.5B"
    assert by_id["qwen15b-frugal-raw4k-dagger-r1"]["inference_modules_checked"] == ["train/eval_hf.py"]

    assert "AWAITING_V100_COMPLETION" not in md_text
    assert "PROMOTED_ADDENDUM_READY" in md_text
    assert "qwen15b-compact-dagger-r1" in md_text
    assert "qwen05b-compact-dagger-r1" in md_text


def test_synthetic_failing_track1_qwen_dagger_all_five_gates(tmp_path: Path) -> None:
    syn = _clone_minimal_repo(tmp_path)

    c1_fail_v3_vs_v2 = _make_passing_qwen_summary(run_id="fail-c1-still-negative")
    neg_after_scores = [-0.05 if i % 4 != 0 else -0.20 for i in range(90)]
    v2_before_scores = [-0.50 for _ in range(90)]
    pos_deltas = [a - b for b, a in zip(v2_before_scores, neg_after_scores)]
    md_p, hw_p = pack._mean_ci95(pos_deltas)
    ma_n, hwa_n = pack._mean_ci95(neg_after_scores)
    c1_fail_v3_vs_v2["before"]["mean_score"] = -0.50
    c1_fail_v3_vs_v2["before"]["scores"] = v2_before_scores
    c1_fail_v3_vs_v2["after"]["mean_score"] = round(ma_n, 6)
    c1_fail_v3_vs_v2["after"]["ci95_low"] = round(ma_n - hwa_n, 6)
    c1_fail_v3_vs_v2["after"]["ci95_high"] = round(ma_n + hwa_n, 6)
    c1_fail_v3_vs_v2["paired"] = {
        "mean_delta": round(md_p, 6),
        "ci95_low": round(md_p - hw_p, 6),
        "ci95_high": round(md_p + hw_p, 6),
        "deltas": pos_deltas,
    }

    c1_fail_ci_crosses_zero = _make_passing_qwen_summary(run_id="fail-c1-ci-crosses-zero")
    noisy_scores = ([0.85] * 33) + ([-1.0] * 25) + ([0.0] * 32)
    m_nz, hw_nz = pack._mean_ci95(noisy_scores)
    assert m_nz > 0.0 and (m_nz - hw_nz) < 0.0
    c1_fail_ci_crosses_zero["after"]["mean_score"] = round(m_nz, 6)
    c1_fail_ci_crosses_zero["after"]["ci95_low"] = round(m_nz - hw_nz, 6)
    c1_fail_ci_crosses_zero["after"]["ci95_high"] = round(m_nz + hw_nz, 6)
    c1_fail_ci_crosses_zero["paired"] = {
        "mean_delta": round(m_nz, 6),
        "ci95_low": round(m_nz - hw_nz, 6),
        "ci95_high": round(m_nz + hw_nz, 6),
        "deltas": noisy_scores,
    }

    c2_fail_unpaired = _make_passing_qwen_summary(run_id="fail-c2-unpaired-secret")
    c2_fail_unpaired["before"]["world_secret_tag"] = "sha256:f272803cdb679dbe"
    c2_fail_unpaired["after"]["world_secret_tag"] = "sha256:c86b9c8a54f8b269"

    c3_fail_seeds = _make_passing_qwen_summary(run_id="fail-c3-seed-overlap")
    c3_fail_seeds["train_seeds"] = [100000, 100001, 800005]

    c4_fail_replay = _make_passing_qwen_summary(run_id="fail-c4-invalid-and-small-n")
    d24 = [0.65] * 24
    m24, hw24 = pack._mean_ci95(d24)
    c4_fail_replay["n"] = 24
    c4_fail_replay["before"]["n"] = 24
    c4_fail_replay["after"]["n"] = 24
    c4_fail_replay["after"]["mean_score"] = round(m24, 6)
    c4_fail_replay["after"]["ci95_low"] = round(m24 - hw24, 6)
    c4_fail_replay["after"]["ci95_high"] = round(m24 + hw24, 6)
    c4_fail_replay["paired"] = {
        "mean_delta": round(m24, 6),
        "ci95_low": round(m24 - hw24, 6),
        "ci95_high": round(m24 + hw24, 6),
        "deltas": d24,
    }
    c4_fail_replay["replay_verified"] = False
    c4_fail_replay["after"]["invalid_episodes"] = 2

    leaky_mod = syn / "train" / "leaky_qwen_dagger.py"
    leaky_mod.write_text(
        "\n".join([
            "from canary.solver.policy import SolverPolicy",
            "",
            "class LeakyQwenPolicy:",
            "    def __init__(self):",
            "        self.teacher = SolverPolicy()",
            "    def reset(self, tools_spec, instruction):",
            "        self.teacher.reset(tools_spec, instruction)",
            "    def act(self, history):",
            "        return self.teacher.act(history)",
            "",
        ]),
        encoding="utf-8",
    )
    c5_fail_ast = _make_passing_qwen_summary(run_id="fail-c5-solver-leak")
    c5_fail_ast["inference_module"] = "train/leaky_qwen_dagger.py"

    fixtures = [
        ("f1_neg", c1_fail_v3_vs_v2, ["heldout_mean_gt_zero"]),
        ("f1_ci", c1_fail_ci_crosses_zero, ["heldout_mean_gt_zero", "paired_delta_ci95_gt_zero"]),
        ("f2_sec", c2_fail_unpaired, ["paired_delta_ci95_gt_zero"]),
        ("f3_seed", c3_fail_seeds, ["train_eval_disjoint"]),
        ("f4_rep", c4_fail_replay, ["replay_and_zero_errors"]),
        ("f5_ast", c5_fail_ast, ["autonomous_inference"]),
    ]

    for folder, payload, _ in fixtures:
        d = syn / "results" / "tiebreak" / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert pack.main(["--repo-root", str(syn)]) == 0
    assert pack.main(["--repo-root", str(syn), "--check"]) == 0

    readiness = json.loads((syn / "results" / "tiebreak" / "addendum_readiness.json").read_text(encoding="utf-8"))
    rs = readiness["readiness_summary"]
    assert rs["track1_discovered_count"] == 6
    assert rs["track1_passing_count"] == 0
    assert rs["track1_llm_passing_count"] == 0
    assert rs["readme_qwen_addendum_eligible"] is False
    assert rs["track1_llm_dagger_status"] == "AWAITING_V100_COMPLETION"
    assert rs["readme_addendum_action"] == "DO_NOT_APPEND_YET"

    by_id = {r["run_id"]: r for r in readiness["track_1_runs"]}
    for _, payload, expected_failed in fixtures:
        rec = by_id[payload["run_id"]]
        assert rec["passed_panel_fix_e_bar"] is False
        assert rec["verdict"] == "BAR_NOT_MET"
        assert rec["failed_criteria"] == expected_failed

    assert by_id["fail-c1-still-negative"]["criteria"]["paired_delta_ci95_gt_zero"] is True
    assert by_id["fail-c1-still-negative"]["criteria"]["heldout_mean_gt_zero"] is False


def test_tinymlp_and_track2_controls_never_conflated_with_qwen_llm(tmp_path: Path) -> None:
    syn = _clone_minimal_repo(tmp_path)

    mlp_mod = syn / "train" / "neural_mlp_tiebreak.py"
    mlp_mod.write_text(
        "\n".join([
            "class TinyMLPPolicy:",
            "    def __init__(self):",
            "        self.steps = 0",
            "    def reset(self, tools_spec, instruction):",
            "        self.steps = 0",
            "    def act(self, history):",
            "        self.steps += 1",
            "        return 'advance_day', {}",
            "",
        ]),
        encoding="utf-8",
    )

    mlp_dir = syn / "results" / "tiebreak" / "neural_mlp"
    mlp_dir.mkdir(parents=True, exist_ok=True)
    mlp_summary = _make_passing_qwen_summary(
        run_id="tiny-mlp-dagger-v14",
        model="TinyMLPPolicy (2-layer compact neural MLP + DAgger)",
        explicit_after_ci=True,
    )
    (mlp_dir / "summary.json").write_text(json.dumps(mlp_summary, indent=2), encoding="utf-8")

    lin_dir = syn / "results" / "tiebreak" / "linear_dagger"
    lin_dir.mkdir(parents=True, exist_ok=True)
    lin_summary = _make_passing_qwen_summary(
        run_id="compact-linear-dagger-v14",
        model="CompactLinearDAggerPolicy (ridge/logistic baseline)",
        explicit_after_ci=True,
    )
    lin_summary["notes"] = "Non-LLM control compared against Qwen2.5-1.5B on held-out seeds."
    (lin_dir / "summary.json").write_text(json.dumps(lin_summary, indent=2), encoding="utf-8")

    assert pack.main(["--repo-root", str(syn)]) == 0
    assert pack.main(["--repo-root", str(syn), "--check"]) == 0

    readiness = json.loads((syn / "results" / "tiebreak" / "addendum_readiness.json").read_text(encoding="utf-8"))
    rs = readiness["readiness_summary"]

    assert rs["track1_passing_count"] == 1
    assert rs["track1_neural_mlp_passing_count"] == 1
    assert rs["track1_llm_passing_count"] == 0
    assert rs["readme_qwen_addendum_eligible"] is False
    assert rs["track1_llm_dagger_status"] == "AWAITING_V100_COMPLETION"
    assert rs["track1_overall_status"] == "PASS_NEURAL_MLP_AWAITING_V100_LLM"
    assert rs["promoted_track1_run_ids"] == ["tiny-mlp-dagger-v14"]
    assert rs["promoted_track1_llm_run_ids"] == []

    t2_ids = {r["run_id"]: r for r in readiness["track_2_runs"]}
    assert "compact-linear-dagger-v14" in t2_ids
    assert t2_ids["compact-linear-dagger-v14"]["family"] == "CompactLinearDAggerPolicy"
    assert t2_ids["compact-linear-dagger-v14"]["is_open_weight_llm"] is False
    assert t2_ids["compact-linear-dagger-v14"]["verdict"] == "PASS_NON_LLM_CONTROL"


def test_unclassified_policy_and_panel_fix_a_guard(tmp_path: Path) -> None:
    syn = _clone_minimal_repo(tmp_path)
    unk_dir = syn / "results" / "tiebreak" / "mystery_agent"
    unk_dir.mkdir(parents=True, exist_ok=True)
    unk_summary = _make_passing_qwen_summary(
        run_id="mystery-box-v1",
        model="OpaqueHeuristicBox",
    )
    (unk_dir / "summary.json").write_text(json.dumps(unk_summary, indent=2), encoding="utf-8")

    assert pack.main(["--repo-root", str(syn)]) == 1

    assert pack._has_affirmative_prereg_0_29("Evaluated on pre-registered seeds 0..29.") != []
    assert pack._has_affirmative_prereg_0_29("Dev seeds 0..29 are post-hoc locked (not pre-registered).") == []


def test_registry_mappings_with_modules_present_and_absent(tmp_path: Path) -> None:
    syn_absent = _clone_minimal_repo(tmp_path / "absent")
    absent_specs = [
        ("qwen15b_dpo_dagger", "qwen15b-dpo-dagger-v14", "Qwen2.5-1.5B-Instruct DPO DAgger", "track_1", "Qwen2.5-1.5B", True),
        ("qwen15b_compact_dagger", "qwen15b-compact-dagger-v14", "Qwen2.5-1.5B-Instruct Compact DAgger", "track_1", "Qwen2.5-1.5B", True),
        ("compact_lora_sft", "qwen05b-compact-dagger-v14", "Qwen2.5-0.5B-Instruct Compact DAgger", "track_1", "Qwen2.5-0.5B", True),
        ("qwen15b_raw", "qwen15b-raw-dagger-v14", "Qwen2.5-1.5B-Instruct Raw DAgger", "track_1", "Qwen2.5-1.5B", True),
        ("frugal_raw", "frugal-raw-dagger-v14", "Frugal Raw4k LoRA DAgger", "track_1", "Qwen2.5-1.5B", True),
        ("compact_dagger_ablation", "compact-linear-dagger-v14", "CompactLinearDAggerPolicy", "track_2", "CompactLinearDAggerPolicy", False),
    ]
    for folder, run_id, model_name, _, _, _ in absent_specs:
        rdir = syn_absent / "results" / "tiebreak" / folder
        rdir.mkdir(parents=True, exist_ok=True)
        payload = _make_passing_qwen_summary(run_id=run_id, model=model_name, explicit_after_ci=True)
        (rdir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert pack.main(["--repo-root", str(syn_absent)]) == 0
    assert pack.main(["--repo-root", str(syn_absent), "--check"]) == 0
    r_abs = json.loads((syn_absent / "results" / "tiebreak" / "addendum_readiness.json").read_text(encoding="utf-8"))
    by_id_abs = {r["run_id"]: r for r in [*r_abs["track_1_runs"], *r_abs["track_2_runs"]]}
    for _, run_id, _, exp_track, exp_fam, exp_llm in absent_specs:
        rec = by_id_abs[run_id]
        assert rec["track"] == exp_track
        assert rec["family"] == exp_fam
        assert rec["is_open_weight_llm"] is exp_llm
        assert rec["passed_panel_fix_e_bar"] is True

    syn_present = _clone_minimal_repo(tmp_path / "present")
    mod_Bodies = {
        "train/qwen15b_dpo_dagger.py": (
            "from canary.solver.policy import SolverPolicy\n"
            "from train.compact_render import CompactHFPolicy\n"
            "def relabel(sp):\n"
            "    return sp.belief()\n"
            "def build_eval_policy(name):\n"
            "    return CompactHFPolicy(name=name)\n"
        ),
        "train/qwen15b_compact_dagger.py": (
            "class Qwen15BCompactPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ok = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n"
        ),
        "train/compact_lora_sft.py": (
            "class Qwen05BCompactPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ok = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n"
        ),
        "train/frugal_raw_dagger.py": (
            "class FrugalRawPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ok = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n"
        ),
        "train/neural_mlp_tiebreak.py": (
            "class TinyMLPPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ok = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n"
        ),
        "train/compact_dagger_ablation.py": (
            "class CompactLinearDAggerPolicy:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ok = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n"
        ),
    }
    for rel_m, code in mod_Bodies.items():
        mp = syn_present / rel_m
        mp.parent.mkdir(parents=True, exist_ok=True)
        mp.write_text(code, encoding="utf-8")

    present_specs = [
        *absent_specs,
        ("neural_mlp", "tiny-mlp-dagger-v14", "TinyMLPPolicy", "track_1", "TinyMLP", False),
    ]
    for folder, run_id, model_name, _, _, _ in present_specs:
        rdir = syn_present / "results" / "tiebreak" / folder
        rdir.mkdir(parents=True, exist_ok=True)
        payload = _make_passing_qwen_summary(run_id=run_id, model=model_name, explicit_after_ci=True)
        (rdir / "summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    assert pack.main(["--repo-root", str(syn_present)]) == 0
    assert pack.main(["--repo-root", str(syn_present), "--check"]) == 0
    r_pres = json.loads((syn_present / "results" / "tiebreak" / "addendum_readiness.json").read_text(encoding="utf-8"))
    by_id_pres = {r["run_id"]: r for r in [*r_pres["track_1_runs"], *r_pres["track_2_runs"]]}

    assert "train/qwen15b_dpo_dagger.py" in by_id_pres["qwen15b-dpo-dagger-v14"]["inference_modules_checked"]
    assert "train/qwen15b_compact_dagger.py" in by_id_pres["qwen15b-compact-dagger-v14"]["inference_modules_checked"]
    assert "train/compact_lora_sft.py" in by_id_pres["qwen05b-compact-dagger-v14"]["inference_modules_checked"]
    assert "train/frugal_raw_dagger.py" in by_id_pres["qwen15b-raw-dagger-v14"]["inference_modules_checked"]
    assert "train/frugal_raw_dagger.py" in by_id_pres["frugal-raw-dagger-v14"]["inference_modules_checked"]
    assert by_id_pres["tiny-mlp-dagger-v14"]["inference_modules_checked"] == ["train/neural_mlp_tiebreak.py"]
    assert by_id_pres["compact-linear-dagger-v14"]["inference_modules_checked"] == ["train/compact_dagger_ablation.py"]
