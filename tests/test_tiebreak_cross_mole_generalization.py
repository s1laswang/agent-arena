from __future__ import annotations

import ast
import io
import json
import shutil
import sys
import time
import tokenize
from pathlib import Path

import pytest

_BEFORE_IMPORT_HEAVY = frozenset(m for m in ("torch", "transformers") if m in sys.modules)

import scripts.tiebreak_cross_mole_generalization as cmg
import scripts.verify_tiebreak_submission as sub_gate

_IMPORT_DELTA_HEAVY = (
    frozenset(m for m in ("torch", "transformers") if m in sys.modules) - _BEFORE_IMPORT_HEAVY
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_cross_mole_generalization.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "cross_mole_generalization" / "generalization_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_cross_mole_generalization.md"
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

    script_dst = dst / "scripts" / "tiebreak_cross_mole_generalization.py"
    script_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_PATH, script_dst)
    return dst


def test_source_hygiene_and_ast_inference_isolation(tmp_path: Path) -> None:
    fn_heavy = {m for m in ("torch", "transformers") if m in sys.modules}
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
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
    iso = sub_gate.check_ast_inference_isolation(
        root=scoped_root,
        extra_paths=[scoped_root / "scripts" / "tiebreak_cross_mole_generalization.py"],
        strict=True,
    )
    assert iso.passed is True, iso.errors
    assert "scripts/tiebreak_cross_mole_generalization.py:UncalibratedEmpiricalBayesPolicy" in (
        iso.metrics["policy_classes_checked"]
    )
    assert ({m for m in ("torch", "transformers") if m in sys.modules} - fn_heavy) == set()


def test_committed_artifacts_and_cli_check_pass(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    rc = cmg.main(["--check"])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    verdict = json.loads(capsys.readouterr().out)

    assert verdict["passed"] is True, verdict["errors"]
    assert verdict["errors"] == []
    assert verdict["summary_bytes"] <= cmg.MAX_SUMMARY_BYTES
    assert verdict["regimes_verified"] == 5
    assert elapsed < 10.0

    summary = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert summary["train_seed_range"] == "100000..100119"
    assert summary["heldout_seed_range"] == "800000..800029"
    assert summary["world_secret_tag"] == "sha256:ebf2f09716cf76d3"
    assert summary["replay_verified"] is True
    assert summary["invalid_episodes"] == 0
    assert summary["total_episodes_replayed"] == 600
    assert summary["pooled_unseen_adversarial"]["paired"]["score_delta"]["ci95_low"] > 0.0
    assert summary["pooled_all_regimes"]["paired"]["score_delta"]["ci95_low"] > 0.0

    for reg in summary["regimes"]:
        assert reg["n"] == 30
        assert reg["paired"]["ci95_low"] > 0.0
        assert reg["after"]["calibration_gap"] < reg["before"]["calibration_gap"]


def test_seed_hygiene_rejections() -> None:
    cmg.validate_cross_mole_seeds([100_000, 100_001, 100_002, 100_003], [800_000, 800_001])

    with pytest.raises(ValueError, match="even count"):
        cmg.validate_cross_mole_seeds([100_000, 100_001, 100_002], [800_000])

    with pytest.raises(ValueError):
        cmg.validate_cross_mole_seeds([0, 1, 2, 3], [800_000])

    with pytest.raises(ValueError):
        cmg.validate_cross_mole_seeds([100_000, 100_001, 100_002, 100_003], [15])

    with pytest.raises(ValueError):
        cmg.validate_cross_mole_seeds([100_000, 100_001, 100_002, 100_003], [900_000])

    with pytest.raises(ValueError):
        cmg.validate_cross_mole_seeds([100_000, 100_000, 100_002, 100_003], [800_000])


def test_mini_benchmark_and_tamper_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out_json = tmp_path / "results" / "tiebreak" / "cross_mole_generalization" / "generalization_summary.json"
    out_md = tmp_path / "docs" / "reports" / "tiebreak_cross_mole_generalization.md"

    def _fast_fit(seeds: list[int], laplace_alpha: float = 1.0):
        for s in seeds:
            assert 100_000 <= int(s) < 200_000
        s2 = cmg.EmpiricalBayesParams(
            w_canary_hit=4.2,
            w_canary_miss=-3.1,
            w_doc_hit=1.8,
            w_after_hours=0.25,
            w_evasive=1.1,
            w_angry_msg=-2.4,
            tau_margin=0.0,
            unsurfaced_v_discount=0.0,
            canary_coverage=0.90,
            tiny_pool_size=0,
            use_ev_stopping=False,
            naive_p_threshold=0.50,
            stage="eb_likelihood_only",
        )
        return s2, {
            "seed_range": f"{seeds[0]}..{seeds[-1]}",
            "n_episodes": len(seeds),
            "n_identified_episodes": len(seeds),
            "empirical_rates": {},
            "train_mean_score_eb_naive_prior": -0.2,
            "train_mean_score_eb_likelihood_only": 0.3,
            "laplace_alpha": laplace_alpha,
        }

    def _fast_opt(stage2_params: cmg.EmpiricalBayesParams, seeds: list[int]):
        opt = cmg.EmpiricalBayesParams(
            w_canary_hit=stage2_params.w_canary_hit,
            w_canary_miss=stage2_params.w_canary_miss,
            w_doc_hit=stage2_params.w_doc_hit,
            w_after_hours=stage2_params.w_after_hours,
            w_evasive=stage2_params.w_evasive,
            w_angry_msg=stage2_params.w_angry_msg,
            tau_margin=0.65,
            unsurfaced_v_discount=1.0,
            canary_coverage=0.55,
            tiny_pool_size=4,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="eb_experience_opt",
        )
        stats = {
            "seed_range": f"{seeds[0]}..{seeds[-1]}",
            "n_episodes": len(seeds) * 3,
            "selected": opt.to_dict(),
            "train_stage2_uncalibrated": {"mean_score": -0.2},
            "train_stage3_selected": {"mean_score": 0.6},
        }
        return opt, stats

    monkeypatch.setattr(cmg.eb_mod, "fit_empirical_likelihoods", _fast_fit)
    monkeypatch.setattr(cmg.eb_mod, "optimize_stopping_and_splits", _fast_opt)

    summary = cmg.run_benchmark(
        train_start=100_500,
        train_count=4,
        heldout_start=800_150,
        heldout_count=1,
        heldout_secret=cmg.DEFAULT_HELDOUT_SECRET,
        workers=1,
        include_solver=False,
        out_json=out_json,
        out_md=out_md,
        repo_root=tmp_path,
    )
    assert summary["n_regimes"] == 5
    assert summary["n_per_regime"] == 1
    assert summary["total_episodes_replayed"] == 15
    assert summary["invalid_episodes"] == 0

    clean = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800150",
        min_regime_n=1,
        require_solver=False,
    )
    assert clean["passed"] is True, clean["errors"]

    colliding = out_json.parent / "summary.json"
    colliding.write_text("{}", encoding="utf-8")
    orig_md = out_md.read_text(encoding="utf-8")
    out_md.write_text(
        orig_md + f"\nBad dash {chr(0x2014)} and seeds 0..29 were pre-registered.\n",
        encoding="utf-8",
    )
    hyg_res = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800150",
        min_regime_n=1,
        require_solver=False,
    )
    assert hyg_res["passed"] is False
    assert any("colliding artifact" in e for e in hyg_res["errors"])
    assert any("em dash" in e for e in hyg_res["errors"])
    assert any("Panel Fix A" in e for e in hyg_res["errors"])
    colliding.unlink()
    out_md.write_text(orig_md, encoding="utf-8")

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["regimes"][0]["seed_0_anchor"]["after_score"] = -9.999
    out_json.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    spot_res = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800150",
        min_regime_n=1,
        require_solver=False,
    )
    assert spot_res["passed"] is False
    assert any("spot replay" in e for e in spot_res["errors"])
