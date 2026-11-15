from __future__ import annotations

import ast
import io
import json
import sys
import time
import tokenize
from pathlib import Path

import pytest

import scripts.tiebreak_cross_mole_generalization as cmg
import scripts.verify_tiebreak_submission as sub_gate

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_cross_mole_generalization.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "cross_mole_generalization" / "generalization_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_cross_mole_generalization.md"
SELF_PATH = Path(__file__).resolve()


def test_source_hygiene_and_ast_inference_isolation() -> None:
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

    iso = sub_gate.check_ast_inference_isolation(
        root=REPO_ROOT,
        extra_paths=[SCRIPT_PATH],
        strict=True,
    )
    assert iso.passed is True, iso.errors
    assert "scripts/tiebreak_cross_mole_generalization.py:UncalibratedEmpiricalBayesPolicy" in (
        iso.metrics["policy_classes_checked"]
    )


def test_committed_artifacts_and_cli_check_pass(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    verdict = cmg.verify_artifacts(
        summary_path=SUMMARY_PATH,
        report_path=REPORT_PATH,
        repo_root=REPO_ROOT,
    )
    elapsed = time.perf_counter() - t0

    assert verdict["passed"] is True, verdict["errors"]
    assert verdict["errors"] == []
    assert verdict["summary_bytes"] <= cmg.MAX_SUMMARY_BYTES
    assert verdict["regimes_verified"] == 5
    assert elapsed < 3.0

    rc = cmg.main(["--check"])
    assert rc == 0
    cli_payload = json.loads(capsys.readouterr().out)
    assert cli_payload["passed"] is True

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


def test_mini_benchmark_and_tamper_detection(tmp_path: Path) -> None:
    out_json = tmp_path / "results" / "tiebreak" / "cross_mole_generalization" / "generalization_summary.json"
    out_md = tmp_path / "docs" / "reports" / "tiebreak_cross_mole_generalization.md"

    summary = cmg.run_benchmark(
        train_start=100_500,
        train_count=4,
        heldout_start=800_150,
        heldout_count=2,
        heldout_secret=cmg.DEFAULT_HELDOUT_SECRET,
        workers=1,
        include_solver=False,
        out_json=out_json,
        out_md=out_md,
        repo_root=tmp_path,
    )
    assert summary["n_regimes"] == 5
    assert summary["n_per_regime"] == 2
    assert summary["total_episodes_replayed"] == 30
    assert summary["invalid_episodes"] == 0

    clean = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800151",
        min_regime_n=2,
        require_solver=False,
    )
    assert clean["passed"] is True, clean["errors"]

    colliding = out_json.parent / "summary.json"
    colliding.write_text("{}", encoding="utf-8")
    col_res = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800151",
        min_regime_n=2,
        require_solver=False,
    )
    assert col_res["passed"] is False
    assert any("colliding artifact" in e for e in col_res["errors"])
    colliding.unlink()

    orig_md = out_md.read_text(encoding="utf-8")
    out_md.write_text(
        orig_md + f"\nBad dash {chr(0x2014)} and seeds 0..29 were pre-registered.\n",
        encoding="utf-8",
    )
    bad_md_res = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800151",
        min_regime_n=2,
        require_solver=False,
    )
    assert bad_md_res["passed"] is False
    assert any("em dash" in e for e in bad_md_res["errors"])
    assert any("Panel Fix A" in e for e in bad_md_res["errors"])
    out_md.write_text(orig_md, encoding="utf-8")

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["regimes"][0]["seed_0_anchor"]["after_score"] = -9.999
    out_json.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    spot_res = cmg.verify_artifacts(
        summary_path=out_json,
        report_path=out_md,
        repo_root=tmp_path,
        expected_train_range="100500..100503",
        expected_heldout_range="800150..800151",
        min_regime_n=2,
        require_solver=False,
    )
    assert spot_res["passed"] is False
    assert any("spot replay" in e for e in spot_res["errors"])
