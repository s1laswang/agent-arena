from __future__ import annotations

import ast
import copy
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tokenize
from pathlib import Path

import pytest

from canary import world as canary_world
from canary.env import Env
from canary.eval import run_episode
import scripts.tiebreak_addendum_pack as addendum_mod
import scripts.tiebreak_experiment_ledger as ledger_mod
import scripts.verify_tiebreak_submission as gate
import train.compact_dagger_ablation as mod

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "train" / "compact_dagger_ablation.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "dagger_ablation" / "summary.json"
TABLE_PATH = REPO_ROOT / "results" / "tiebreak" / "dagger_ablation" / "table.md"
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

    mod_dst = dst / "train" / "compact_dagger_ablation.py"
    mod_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MODULE_PATH, mod_dst)
    return dst


def _build_scoped_gate_root(dst: Path, led_entry: dict[str, object]) -> Path:
    art_dir = dst / "results" / "tiebreak" / "dagger_ablation"
    art_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SUMMARY_PATH, art_dir / "summary.json")
    shutil.copy2(TABLE_PATH, art_dir / "table.md")

    mod_dst = dst / "train" / "compact_dagger_ablation.py"
    mod_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MODULE_PATH, mod_dst)

    rid = str(led_entry["run_id"])
    mini_ledger = {
        "summary_counts": {
            "historical_runs": 0,
            "discovered_runs": 1,
            "verified_improvements": 1,
            "verified_run_ids": [rid],
        },
        "calibrated_v14_dataset": {},
        "historical_runs": [],
        "discovered_runs": [led_entry],
    }
    (dst / "results" / "tiebreak" / "experiment_ledger.json").write_text(
        json.dumps(mini_ledger, indent=2) + "\n",
        encoding="utf-8",
    )

    bef = float(led_entry["before_mean_score"])
    aft = float(led_entry["after_mean_score"])
    dl = float(led_entry["paired_mean_delta"])
    lo = float(led_entry["paired_ci95_low"])
    hi = float(led_entry["paired_ci95_high"])
    vcb = float(led_entry["before_valid_call_rate"])
    vca = float(led_entry["after_valid_call_rate"])
    hn = int(led_entry["heldout_n"])
    sec = str(led_entry["after_world_secret_tag"])
    st = str(led_entry["status"])

    rep_dst = dst / "docs" / "reports" / "tiebreak_small_model.md"
    rep_dst.parent.mkdir(parents=True, exist_ok=True)
    rep_dst.write_text(
        "Tiebreak Small Model Scoped Check\n"
        "=================================\n\n"
        "- Historical runs logged: `0`\n"
        "- Dynamically discovered squad runs: `1`\n"
        "- Verified improvements passing all 4 strict gates: `1`\n\n"
        "| Split | Tier | Nat | Corr | NatAbs | AugAbs | Rej | SFT | DPO | TopAcc | TopAbs |\n"
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|\n\n"
        "| Run ID | Model | Seeds | Held-out n | Score | Valid Call | Secret | Status |\n"
        "|---|---|---|---:|---|---|---|---|\n"
        f"| {rid} | CompactLinearDAggerPolicy | 800000..800059 | {hn} | "
        f"{bef:.3f} -> {aft:.3f} (delta {dl:+.3f} [{lo:+.3f}, {hi:+.3f}]) | "
        f"{vcb:.2f} -> {vca:.2f} | {sec} | {st} |\n",
        encoding="utf-8",
    )
    return dst


def test_source_artifact_hygiene_and_ast_inference_isolation(tmp_path: Path) -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    banned_flash = "gemini-" + "3.5" + "-flash"
    banned_prereg_hyphen = "pre-" + "regist"
    banned_prereg_compact = "prere" + "gist"
    forbidden_imports = {"torch", "transformers", "peft", "mlx", "mlx_lm", "google", "genai"}

    assert mod.DEFAULT_CKPT_PATH == "/tmp/fleet-silas/shared/tiebreak-v100/dagger_ablation_ckpt.json"

    for py_path in (MODULE_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        low = src.lower()
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in toks if tok.type == tokenize.COMMENT]
        assert not comments, f"comment token found in {py_path}"
        assert hash_char not in src, f"hash char found in {py_path}"
        assert em_dash not in src, f"em dash found in {py_path}"
        assert en_dash not in src, f"en dash found in {py_path}"
        assert banned_flash not in low, f"forbidden flash reference in {py_path}"
        assert banned_prereg_hyphen not in low, f"forbidden wording in {py_path}"
        assert banned_prereg_compact not in low, f"forbidden wording in {py_path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_imports
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_imports

    for art_path in (SUMMARY_PATH, TABLE_PATH):
        assert art_path.is_file(), f"missing artifact: {art_path}"
        assert art_path.stat().st_size < 1_000_000
        txt = art_path.read_text(encoding="utf-8")
        low = txt.lower()
        assert hash_char not in txt, f"hash char found in {art_path}"
        assert em_dash not in txt, f"em dash found in {art_path}"
        assert en_dash not in txt, f"en dash found in {art_path}"
        assert banned_flash not in low, f"forbidden flash row in {art_path}"
        assert banned_prereg_hyphen not in low, f"forbidden wording in {art_path}"
        assert banned_prereg_compact not in low, f"forbidden wording in {art_path}"

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    scoped_ast_root = _build_scoped_ast_root(tmp_path / "ast_scope")
    iso = gate.check_ast_inference_isolation(root=scoped_ast_root, strict=True)
    assert iso.passed is True, iso.errors
    assert "train/compact_dagger_ablation.py" in iso.metrics["modules_checked"]
    assert "train/compact_dagger_ablation.py:CompactLinearDAggerPolicy" in iso.metrics["policy_classes_checked"]

    add_errs, add_classes = addendum_mod.audit_inference_module_ast(
        "train/compact_dagger_ablation.py", MODULE_PATH
    )
    assert add_errs == []
    assert add_classes == ["train/compact_dagger_ablation.py:CompactLinearDAggerPolicy"]


def test_committed_summary_table_parity_gates_and_covariate_shift(tmp_path: Path) -> None:
    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    table_md = TABLE_PATH.read_text(encoding="utf-8")

    expected_sha_tag = (
        "sha256:" + hashlib.sha256(mod.HELDOUT_WORLD_SECRET.encode("utf-8")).hexdigest()[:16]
    )

    assert mod.format_markdown_table(summary) == table_md
    assert summary["run_id"] == "compact-linear-dagger-v14"
    assert summary["inference_module"] == "train/compact_dagger_ablation.py"
    assert summary["tiers_version"] == "v1.4"
    assert summary["tiers"] == ["easy", "medium", "hard"]
    assert summary["n"] == 180
    assert summary["policy_architecture"]["class_name"] == "CompactLinearDAggerPolicy"
    assert summary["policy_architecture"]["param_count"] == 785
    assert summary["train_seeds"] == {"start": 109000, "stop": 109510}
    assert summary["eval_seeds"] == {"start": 800000, "stop": 800060}
    assert summary["train_seed_range"] == "109000..109509"
    assert summary["offline_seed_range"] == "109000..109149"
    assert summary["dagger_r1_seed_range"] == "109150..109299"
    assert summary["dagger_r2_seed_range"] == "109300..109449"
    assert summary["val_seed_range"] == "109450..109509"
    assert summary["eval_seed_range"] == "800000..800059"
    assert summary["world_secret_tag"] == expected_sha_tag
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["total_episodes_replayed"] == 1530

    for side_key in ("before", "after"):
        side = summary[side_key]
        assert side["n"] == 180
        assert side["valid_call_rate"] == 1.0
        assert side["cap_stall_rate"] == 0.0
        assert side["world_secret_tag"] == expected_sha_tag
        assert side["replay_verified"] is True
        assert side["invalid_episodes"] == 0

    assert summary["before"]["stage"] == "stage0_untrained"
    assert summary["before"]["mean_score"] == 0.0
    assert summary["before"]["abstain_rate"] == 1.0
    assert summary["after"]["stage"] == "stage3_onpolicy_dagger_r2"
    assert summary["after"]["mean_score"] > 0.60
    assert summary["after"]["accuracy"] > 0.90

    paired = summary["paired"]
    assert isinstance(paired["deltas"], list) and len(paired["deltas"]) == 180
    assert paired["mean_delta"] == pytest.approx(sum(paired["deltas"]) / 180.0, abs=1e-5)
    assert paired["mean_delta"] > 0.60
    assert paired["ci95_low"] > 0.55
    assert paired["ci95_high"] > paired["mean_delta"]
    assert paired["luck_adjusted_mean_delta"] > 0.60
    assert paired["luck_adjusted_ci95_low"] > 0.55

    ho = summary["heldout_ablation"]
    pd = ho["paired_deltas"]
    assert pd["stage3_r2_minus_stage2"]["mean_delta"] > 0.12
    assert pd["stage3_r2_minus_stage2"]["ci95_low"] > 0.05
    assert pd["stage3_r2_minus_stage1"]["mean_delta"] > 0.08
    assert pd["stage3_r2_minus_stage1"]["ci95_low"] > 0.03
    assert pd["stage3_r2_minus_heuristic"]["mean_delta"] > 0.35
    assert pd["stage3_r2_minus_heuristic"]["ci95_low"] > 0.25

    cs = summary["covariate_shift_diagnostics"]
    assert cs["stage3_onpolicy_dagger_r2"]["agreement_on_student_states"] > 0.95
    assert cs["stage3_onpolicy_dagger_r2"]["student_valid_call_rate"] == 1.0
    assert (
        cs["stage3_onpolicy_dagger_r2"]["covariate_shift_agreement_drop"]
        < cs["stage1_survivorship_sft"]["covariate_shift_agreement_drop"]
    )
    assert (
        cs["stage3_onpolicy_dagger_r2"]["covariate_shift_agreement_drop"]
        < cs["stage2_calibrated_bc"]["covariate_shift_agreement_drop"]
    )

    dev_hard = ho["dev_hard"]
    assert dev_hard["protocol_label"] == "post-hoc locked dev hard 0..29"
    assert "post-hoc locked dev hard 0..29" in table_md
    dev_agents = set(dev_hard["agents"].keys())
    assert "stage3_onpolicy_dagger_r2" in dev_agents
    assert "opencode:google/gemini-4-carbon" in dev_agents
    assert "gemini:gemini-4-carbon" in dev_agents
    assert "solver" in dev_agents

    led_entry = ledger_mod.validate_experiment_summary(
        summary, summary_path="results/tiebreak/dagger_ablation/summary.json"
    )
    assert led_entry["verified_improvement"] is True
    assert led_entry["status"] == "VERIFIED_IMPROVEMENT"
    assert led_entry["heldout_n"] == 180
    assert led_entry["gates"]["all_passed"] is True
    assert led_entry["gates"]["reasons"] == []

    scoped_gate_root = _build_scoped_gate_root(tmp_path / "gate_scope", led_entry)
    for gate_fn in (
        gate.check_seed_and_secret_provenance,
        gate.check_claim_number_audit,
        gate.check_hygiene_and_panel_fix_a,
    ):
        out = gate_fn(root=scoped_gate_root, strict=True)
        assert out.passed is True, out.errors

    add_entry = addendum_mod.evaluate_run_summary(
        summary, summary_path="results/tiebreak/dagger_ablation/summary.json", repo_root=REPO_ROOT
    )
    assert add_entry["verdict"] == "PASS_NON_LLM_CONTROL"
    assert add_entry["passed_panel_fix_e_bar"] is True
    assert add_entry["family"] == "CompactLinearDAggerPolicy"
    assert add_entry["is_open_weight_llm"] is False
    assert all(add_entry["criteria"].values())


def test_seed_hygiene_guards_and_rejections() -> None:
    mod.assert_strict_seed_hygiene(
        train_seeds=[109_000, 109_509],
        eval_seeds=[800_000, 800_059],
        dev_seeds=[0, 29],
    )

    with pytest.raises(ValueError, match="non-empty"):
        mod.assert_strict_seed_hygiene([], [800_000])

    for bad_train in (0, 29, 99_999, 200_000, 800_000, 900_000, True):
        with pytest.raises(ValueError):
            mod.assert_strict_seed_hygiene([bad_train], [800_000])

    for bad_eval in (0, 109_000, 799_999, 800_200, 900_000, False):
        with pytest.raises(ValueError):
            mod.assert_strict_seed_hygiene([109_000], [bad_eval])

    for bad_dev in (-1, 10_000, 109_000, 800_000, 900_000, True):
        with pytest.raises(ValueError):
            mod.assert_strict_seed_hygiene([109_000], [800_000], dev_seeds=[bad_dev])

    with pytest.raises(ValueError, match="mutually disjoint"):
        mod.run_ablation_pipeline(
            offline_count=160,
            dagger_r1_count=3,
            dagger_r2_count=3,
            val_count=3,
            heldout_count=1,
            dev_count=0,
        )


def test_from_summary_checkpoint_live_rollouts_and_replay_tamper(tmp_path: Path) -> None:
    pol = mod.CompactLinearDAggerPolicy.from_summary(SUMMARY_PATH)
    assert pol.weights.param_count() == 785
    assert pol.weights.stage == "stage3_onpolicy_dagger_r2"

    roundtrip_w = mod.CompactLinearWeights.from_dict(pol.weights.to_dict(decimals=6))
    assert roundtrip_w.param_count() == 785
    assert roundtrip_w.l2_norm() == pytest.approx(pol.weights.l2_norm(), abs=1e-4)

    ckpt_file = tmp_path / "ckpt.json"
    ckpt_file.write_text(
        json.dumps({"run_id": mod.RUN_ID, "stages": {"stage3_onpolicy_dagger_r2": pol.weights.to_dict()}}),
        encoding="utf-8",
    )
    pol_ckpt = mod.CompactLinearDAggerPolicy.from_checkpoint(ckpt_file, stage="stage3_onpolicy_dagger_r2")
    assert pol_ckpt.weights.param_count() == 785
    with pytest.raises(KeyError, match="not found in checkpoint"):
        mod.CompactLinearDAggerPolicy.from_checkpoint(ckpt_file, stage="missing_stage")

    last_ep = None
    for tier, seed in (("easy", 109_000), ("medium", 109_001), ("hard", 109_002)):
        live_pol = mod.CompactLinearDAggerPolicy(pol.weights, name="stage3_onpolicy_dagger_r2")
        ep = run_episode(Env(tier, seed), live_pol)
        last_ep = ep
        assert mod.replay_verify_episode(ep) is True
        assert ep.end_reason in ("accused", "horizon")
        assert all(bool(st.result.get("ok")) for st in ep.steps)
        belief = live_pol.belief()
        assert belief
        assert math.isclose(sum(belief.values()), 1.0, rel_tol=1e-6)
        forced_emp = live_pol.forced_accuse_target(list(ep.steps))
        assert forced_emp in belief
        assert math.isfinite(mod.luck_adjusted_ev(ep))

    assert last_ep is not None
    tampered_score = copy.deepcopy(last_ep)
    tampered_score.score = float(tampered_score.score) + 0.25
    with pytest.raises(AssertionError, match="replay score mismatch"):
        mod.replay_verify_episode(tampered_score)

    tampered_acc = copy.deepcopy(last_ep)
    tampered_acc.accused = "e99"
    with pytest.raises(AssertionError, match="replay accused mismatch"):
        mod.replay_verify_episode(tampered_acc)


def test_mini_end_to_end_cli_and_world_secret_restoration(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prior_env_secret = os.environ.get("CANARY_WORLD_SECRET")
    prior_set_secret = b"test-prior-secret-dagger-16bytes"
    os.environ["CANARY_WORLD_SECRET"] = "caller-env-secret-dagger-preserved"
    canary_world.set_world_secret(prior_set_secret)
    try:
        sum_out = tmp_path / "mini_summary.json"
        tbl_out = tmp_path / "mini_table.md"
        ckpt_out = tmp_path / "mini_ckpt.json"
        rc = mod.main([
            "--offline-count",
            "1",
            "--dagger-r1-count",
            "1",
            "--dagger-r2-count",
            "1",
            "--val-count",
            "1",
            "--heldout-count",
            "1",
            "--dev-count",
            "0",
            "--summary-out",
            str(sum_out),
            "--table-out",
            str(tbl_out),
            "--ckpt-out",
            str(ckpt_out),
        ])
        assert rc == 0
        stdout_txt = capsys.readouterr().out
        assert "[compact-linear-dagger-v14]" in stdout_txt
        assert os.environ.get("CANARY_WORLD_SECRET") == "caller-env-secret-dagger-preserved"
        assert getattr(canary_world, "_SET_SECRET", None) == prior_set_secret

        assert sum_out.is_file()
        assert tbl_out.is_file()
        assert ckpt_out.is_file()
        mini_sum = json.loads(sum_out.read_text(encoding="utf-8"))
        assert mini_sum["n"] == 3
        assert mini_sum["replay_verified"] is True
        assert mini_sum["invalid_episodes"] == 0
        assert len(mini_sum["paired"]["deltas"]) == 3
        assert mini_sum["before"]["world_secret_tag"] == mini_sum["after"]["world_secret_tag"]
        assert mod.format_markdown_table(mini_sum) == tbl_out.read_text(encoding="utf-8")
    finally:
        canary_world.set_world_secret(None)
        if prior_env_secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prior_env_secret
