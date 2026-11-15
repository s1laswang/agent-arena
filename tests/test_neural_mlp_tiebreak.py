from __future__ import annotations

import ast
import copy
import io
import json
import os
import shutil
import sys
import time
import tokenize
from pathlib import Path

import numpy as np
import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

from canary.env import Env
from canary.eval import run_episode
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
import scripts.tiebreak_addendum_pack as addendum_mod
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.verify_tiebreak_submission as gate
import train.neural_mlp_tiebreak as mod

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "neural_mlp_tiebreak.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "neural_mlp_dagger" / "mlp_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_neural_mlp_dagger.md"
SELF_PATH = Path(__file__).resolve()


def _build_scoped_ast_root(dst: Path) -> Path:
    stubs = {
        "train/compact_render.py": "CompactStubPolicy",
        "train/empirical_bayes_policy.py": "EmpiricalBayesStubPolicy",
        "scripts/tiebreak_scaling_calibration.py": "ScalingStubPolicy",
    }
    for rel_mod, cls_name in stubs.items():
        p = dst / rel_mod
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"class {cls_name}:\n"
            "    def reset(self, tools_spec, instruction):\n"
            "        self.ready = True\n"
            "    def act(self, history):\n"
            "        return ('status', {})\n",
            encoding="utf-8",
        )
    hf_stub = dst / "train" / "eval_compact_hf.py"
    hf_stub.parent.mkdir(parents=True, exist_ok=True)
    hf_stub.write_text("def run_compact_eval():\n    return {}\n", encoding="utf-8")

    mod_dst = dst / "train" / "neural_mlp_tiebreak.py"
    mod_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MODULE_PATH, mod_dst)
    return dst


def test_source_hygiene_and_ast_inference_isolation(tmp_path: Path) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers", "peft"}

    for py_path in (MODULE_PATH, SELF_PATH):
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
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    assert _IMPORT_DELTA_HEAVY == frozenset()

    scoped_root = _build_scoped_ast_root(tmp_path / "ast_scope")
    iso = gate.check_ast_inference_isolation(root=scoped_root, strict=True)
    assert iso.passed is True, iso.errors
    assert "train/neural_mlp_tiebreak.py" in iso.metrics["modules_checked"]
    assert "train/neural_mlp_tiebreak.py:TinyMLPPolicy" in iso.metrics["policy_classes_checked"]

    add_errs, add_classes = addendum_mod.audit_inference_module_ast("train/neural_mlp_tiebreak.py", MODULE_PATH)
    assert add_errs == []
    assert "train/neural_mlp_tiebreak.py:TinyMLPPolicy" in add_classes
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()


def test_tiny_mlp_forward_backward_gradients_and_checkpoint_roundtrip(tmp_path: Path) -> None:
    rng = np.random.default_rng(42)
    bsz, n_emp = 3, 5
    x_b = rng.normal(0.0, 0.5, size=(bsz, n_emp, mod.D_IN)).astype(np.float32)
    raw_p = rng.uniform(0.1, 1.0, size=(bsz, n_emp)).astype(np.float32)
    p_b = raw_p / np.sum(raw_p, axis=1, keepdims=True)
    y_c = np.zeros((bsz, n_emp), dtype=np.float32)
    y_c[0, 1] = 1.0
    w_c = rng.uniform(0.5, 2.0, size=(bsz, n_emp)).astype(np.float32)
    y_v = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.5]], dtype=np.float32)
    o_i = np.array([1, 2, 0], dtype=np.int64)
    s_wt = np.array([[1.0], [1.5], [1.2]], dtype=np.float32)

    wt0 = mod.init_untrained_weights(rng_seed=107_000)
    assert wt0.param_count() == 12293
    w1, b1, w2, b2, w3, b3 = (
        wt0.w1.copy() + np.float32(0.15),
        wt0.b1.copy() + np.float32(0.25),
        wt0.w2.copy() + np.float32(0.10),
        wt0.b2.copy() + np.float32(0.25),
        wt0.w3.copy(),
        wt0.b3.copy(),
    )

    loss0, p_hat, p_cm, grads = mod.forward_backward_batch(
        x_b, p_b, y_c, w_c, y_v, o_i, s_wt, w1, b1, w2, b2, w3, b3, is_dagger=False, wd=1e-3
    )
    assert np.isfinite(loss0)
    assert p_hat.shape == (bsz, n_emp)
    assert p_cm.shape == (bsz, n_emp)
    assert np.allclose(np.sum(p_hat, axis=1), 1.0, atol=1e-5)

    eps = np.float32(1e-3)
    for p_arr, g_arr in ((w3, grads[4]), (b3, grads[5]), (b2, grads[3]), (b1, grads[1])):
        flat_p = p_arr.reshape(-1)
        flat_g = g_arr.reshape(-1)
        for idx in range(min(4, flat_p.size)):
            orig = flat_p[idx]
            flat_p[idx] = orig + eps
            l_pos, _, _, _ = mod.forward_backward_batch(
                x_b, p_b, y_c, w_c, y_v, o_i, s_wt, w1, b1, w2, b2, w3, b3, is_dagger=False, wd=1e-3
            )
            flat_p[idx] = orig - eps
            l_neg, _, _, _ = mod.forward_backward_batch(
                x_b, p_b, y_c, w_c, y_v, o_i, s_wt, w1, b1, w2, b2, w3, b3, is_dagger=False, wd=1e-3
            )
            flat_p[idx] = orig
            num_g = (l_pos - l_neg) / (2.0 * float(eps))
            assert abs(float(flat_g[idx]) - num_g) < 5e-3

    synth_samples = [
        {
            "x": x_b[i],
            "post": p_b[i],
            "oracle_idx": int(o_i[i]),
            "student_idx": int((o_i[i] + 1) % n_emp),
            "commit": bool(i == 0),
            "cov": i % 3,
            "ev": 0.25 if i == 0 else -0.40,
            "wt": 1.5,
        }
        for i in range(bsz)
    ]
    wt_trained = mod._train_mlp_adam(synth_samples, wt0, epochs=12, lr=8e-3, mode="dagger", stage_name="unit_dagger", rng_seed=7)
    loss_after, _, _, _ = mod.forward_backward_batch(
        x_b,
        p_b,
        y_c,
        w_c,
        y_v,
        o_i,
        s_wt,
        wt_trained.w1,
        wt_trained.b1,
        wt_trained.w2,
        wt_trained.b2,
        wt_trained.w3,
        wt_trained.b3,
        is_dagger=False,
        wd=1e-4,
    )
    loss_init, _, _, _ = mod.forward_backward_batch(
        x_b, p_b, y_c, w_c, y_v, o_i, s_wt, wt0.w1, wt0.b1, wt0.w2, wt0.b2, wt0.w3, wt0.b3, is_dagger=False, wd=1e-4
    )
    assert loss_after < loss_init

    ckpt_file = tmp_path / "tiny_ckpt.npz"
    mod.save_checkpoint_npz(ckpt_file, {"unit_dagger": wt_trained}, dataset_sizes={"stage1_states": 3})
    pol = mod.TinyMLPPolicy.from_checkpoint(ckpt_file, stage="unit_dagger", seed=107_000)
    assert np.allclose(pol.weights.w1, wt_trained.w1)
    assert pol.name == "unit_dagger"


def test_dagger_relabeling_live_env_rollout_and_verify_episode() -> None:
    t0 = time.perf_counter()
    for bad_train in (0, 29, 800_000, 900_000):
        assert bad_train in DEV_SEEDS or bad_train in HELDOUT_SEEDS or bad_train in JUDGE_SEEDS
        with pytest.raises(ValueError, match="TRAIN_SEEDS"):
            mod.assert_train_seed(bad_train)

    for bad_eval in (0, 107_000, 900_000):
        with pytest.raises(ValueError, match="HELDOUT_SEEDS"):
            mod.assert_heldout_seed(bad_eval)

    assert mod.assert_train_seed(107_000) in TRAIN_SEEDS
    assert mod.assert_heldout_seed(800_000) in HELDOUT_SEEDS

    _, s2_samples = mod._collect_solver_trajectories([107_000, 107_001])
    assert len(s2_samples) >= 4
    wt0 = mod.init_untrained_weights(rng_seed=107_000)
    wt_bc = mod._train_mlp_adam(s2_samples, wt0, epochs=10, lr=5e-3, mode="bc", stage_name="stage2_calibrated_bc", rng_seed=11)

    env_tr = Env("easy", 107_002)
    student = mod.TinyMLPPolicy(weights=wt_bc, seed=107_002)
    student.reset(env_tr.tools_spec(), env_tr.instruction())
    for _ in range(5):
        if env_tr.done:
            break
        t_name, t_args = student.act(list(env_tr.history))
        env_tr.call(t_name, t_args)

    relabeled = mod.relabel_dagger_state(107_002, env_tr.tools_spec(), env_tr.instruction(), list(env_tr.history), student)
    assert relabeled["x"].shape[1] == mod.D_IN
    assert np.isclose(float(np.sum(relabeled["post"])), 1.0, atol=1e-5)
    assert 0 <= int(relabeled["oracle_idx"]) < relabeled["x"].shape[0]
    assert int(relabeled["cov"]) in (0, 1, 2)

    with pytest.raises(ValueError, match="TRAIN_SEEDS"):
        mod.relabel_dagger_state(800_000, env_tr.tools_spec(), env_tr.instruction(), list(env_tr.history), student)

    dagger_samples = mod._collect_dagger_rollouts(wt_bc, [107_002], override_premature=True)
    assert len(dagger_samples) >= 1
    wt_dag = mod._train_mlp_adam(
        s2_samples + dagger_samples, wt_bc, epochs=10, lr=3e-3, mode="dagger", stage_name="stage3_onpolicy_dagger_r2", rng_seed=12
    )

    prev_sec = os.environ.get("CANARY_WORLD_SECRET")
    try:
        os.environ["CANARY_WORLD_SECRET"] = mod.HELDOUT_WORLD_SECRET
        for tier in ("easy", "medium"):
            env_ev = Env(tier, 800_000)
            pol_ev = mod.TinyMLPPolicy(weights=wt_dag, seed=800_000, name="stage3_onpolicy_dagger_r2")
            ep = run_episode(env_ev, pol_ev)
            assert ep.end_reason in ("accused", "horizon")
            assert all(bool(st.result.get("ok")) for st in ep.steps)
            assert sum(pol_ev.belief().values()) == pytest.approx(1.0, abs=1e-5)
            assert mod.verify_episode(ep) is True

            tampered = copy.deepcopy(ep)
            tampered.score = float(ep.score) + 0.25
            with pytest.raises(AssertionError, match="replay mismatch"):
                mod.verify_episode(tampered)
    finally:
        if prev_sec is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_sec

    assert (time.perf_counter() - t0) < 8.0


def test_mlp_summary_and_report_parity_seed_secret_ci_and_gates(capsys: pytest.CaptureFixture[str]) -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()
    assert SUMMARY_PATH.stat().st_size < mod.MAX_SUMMARY_BYTES

    verdict = mod.verify_artifacts(summary_path=SUMMARY_PATH, report_path=REPORT_PATH, repo_root=REPO_ROOT)
    assert verdict["passed"] is True, verdict["errors"]
    assert verdict["errors"] == []

    rc = mod.main(["--check"])
    assert rc == 0
    cli_out = json.loads(capsys.readouterr().out)
    assert cli_out["passed"] is True

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    report_txt = REPORT_PATH.read_text(encoding="utf-8")
    assert summary["run_id"] == "tiny-mlp-dagger-v14"
    assert summary["n"] == 180
    assert summary["param_count"] == 12293
    assert summary["train_seeds"] == {"start": 107000, "stop": 107600}
    assert summary["eval_seeds"] == {"start": 800000, "stop": 800060}
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["before"]["world_secret_tag"] == summary["after"]["world_secret_tag"]
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["after"]["mean_score"] > 0.5
    assert summary["after"]["ci95_low"] > 0.5
    assert summary["paired"]["ci95_low"] > 1.0
    assert "post-hoc locked, not pre-registered" in report_txt.lower()
    assert "strictly separated from open-weight" in report_txt.lower()

    generic_errs: list[str] = []
    checked = gate._audit_generic_summary_table(REPORT_PATH, SUMMARY_PATH, generic_errs)
    assert generic_errs == []
    assert checked == 4

    tables = gate._parse_markdown_tables(report_txt)
    assert len(tables) == 3
    stage_rows = {r[0]: r for r in tables[0][1]}
    for st in mod.STAGE_NAMES:
        ref = summary["stages"][st]["overall"]
        nums = gate._extract_floats(stage_rows[st][3])
        assert int(stage_rows[st][2]) == ref["n"]
        assert abs(nums[0] - ref["mean_score"]) <= 1e-3
        assert abs(float(stage_rows[st][4]) - ref["accuracy"]) <= 1e-3

    delta_rows = {r[0]: r for r in tables[1][1]}
    for d_key, d_ref in summary["stage_deltas"].items():
        assert abs(float(delta_rows[d_key][1]) - d_ref["mean_delta"]) <= 1e-3
        assert abs(float(delta_rows[d_key][2]) - d_ref["ci95_low"]) <= 1e-3
        assert abs(float(delta_rows[d_key][3]) - d_ref["ci95_high"]) <= 1e-3

    led_entry = ledger_mod.validate_experiment_summary(
        summary, summary_path="results/tiebreak/neural_mlp_dagger/mlp_summary.json"
    )
    assert led_entry["status"] == "VERIFIED_IMPROVEMENT"
    assert led_entry["gates"]["all_passed"] is True

    add_entry = addendum_mod.evaluate_run_summary(
        summary, summary_path="results/tiebreak/neural_mlp_dagger/mlp_summary.json", repo_root=REPO_ROOT
    )
    assert add_entry["verdict"] == "PROMOTED_TRACK1_NEURAL"
    assert add_entry["passed_panel_fix_e_bar"] is True
    assert add_entry["is_open_weight_llm"] is False
