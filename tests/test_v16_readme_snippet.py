from __future__ import annotations

import io
import json
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.social.biases import BIAS_TYPES
from scripts import v16_eval_matrix as V16_MATRIX
from scripts import v16_readme_snippet as SNIPPET


def _sample_v16_payload(**overrides: Any) -> dict[str, Any]:
    real_solver_0_9 = [0.64, 0.69, 0.58, 0.28, 0.73, 0.52, 0.71, 0.64, 0.26, 0.71]
    per_seed = [
        {
            "seed": s,
            "gemini_score": 0.65 if s < 5 else (-1.0 if s == 5 else 0.026),
            "solver_score": real_solver_0_9[s],
            "solver_v14_score": real_solver_0_9[s],
            "do_nothing_score": 0.0,
            "stop_early_score": 0.0,
            "replay_verified": True,
        }
        for s in range(10)
    ]
    gem_scores = [r["gemini_score"] for r in per_seed]
    sol_scores = [r["solver_score"] for r in per_seed]
    gem_mean = round(sum(gem_scores) / 10, 6)
    sol_mean = round(sum(sol_scores) / 10, 6)
    payload: dict[str, Any] = {
        "variant": "v5_full9_cocktail",
        "provider_spec": "v16:v5_full9_cocktail",
        "tier": "hard",
        "tiers_version": "v1.4",
        "harness": "opencode",
        "model": "opencode:google/gemini-4-carbon",
        "fake": False,
        "n_seeds": 10,
        "seeds": list(range(10)),
        "gemini_mean": gem_mean,
        "gemini_ci_95": [-0.08, 0.52],
        "solver_mean": sol_mean,
        "solver_v14_mean": sol_mean,
        "gemini_vs_solver_ratio": round(gem_mean / sol_mean, 6),
        "gemini_vs_solver_ratio_ci_95": [0.12, 0.69],
        "luck_adj_mean": 0.228,
        "luck_adj_ci_95": [0.08, 0.38],
        "solver_luck_adj_mean": 0.556,
        "luck_adj_ratio": 0.410072,
        "luck_adj_ratio_ci_95": [0.14, 0.68],
        "do_nothing_mean": 0.0,
        "do_nothing_v14_mean": 0.0,
        "stop_early_mean": 0.0,
        "stop_early_v14_mean": 0.0,
        "solver_calibration_diff": 0.0,
        "solver_calibration_max_abs_diff": 0.0,
        "replay_verified_count": 10,
        "replay_verified_rate": 1.0,
        "gates": {
            "do_nothing_zero": True,
            "stop_early_zero": True,
            "solver_calibration_zero": True,
            "replay_verified": True,
            "all_passed": True,
        },
        "per_seed": per_seed,
    }
    payload.update(overrides)
    return payload


def test_owned_files_have_zero_comments_and_zero_em_or_en_dashes() -> None:
    py_files = [
        ROOT / "scripts" / "v16_readme_snippet.py",
        ROOT / "tests" / "test_v16_readme_snippet.py",
    ]
    doc_file = ROOT / "docs" / "v16-readme-and-rules.md"

    for pf in py_files:
        src = pf.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, (pf.name, comment_tokens)
        assert "\x23" not in src, pf.name
        assert "\u2014" not in src, pf.name
        assert "\u2013" not in src, pf.name

    doc_text = doc_file.read_text(encoding="utf-8")
    assert "\u2014" not in doc_text
    assert "\u2013" not in doc_text


def test_docs_v16_readme_and_rules_disclosures() -> None:
    doc_text = (ROOT / "docs" / "v16-readme-and-rules.md").read_text(encoding="utf-8")
    assert "CANARY_PROVIDER=v16:<variant>" in doc_text
    assert "off by default" in doc_text
    assert "PublicDayFacts" in doc_text
    assert "likelihood ratio" in doc_text
    assert "do_nothing" in doc_text
    assert "stop_early" in doc_text
    for bias in BIAS_TYPES:
        assert bias in doc_text, bias
    assert "+0.351" in doc_text
    assert "+0.576" in doc_text
    assert "61% [3%, 104%]" in doc_text
    assert "56% [21%, 80%]" in doc_text
    assert "+0.322" in doc_text
    assert "+0.499" in doc_text
    assert "NOT PASSED" in doc_text
    assert "Social bias layer (opt-in V1.6" in doc_text


def test_load_committed_v14_hard_seeds_0_9_and_json_baselines() -> None:
    committed_root = ROOT / "data" / "runs" / "committed"
    v14_oc = SNIPPET.load_committed_v14_baseline(
        committed_root,
        tier="hard",
        seeds=list(range(10)),
        harness="opencode",
        model_id="gemini-4-carbon",
    )
    assert v14_oc["n_seeds"] == 10
    assert v14_oc["seeds"] == list(range(10))
    assert v14_oc["gemini_mean"] == pytest.approx(0.351, abs=1e-6)
    assert v14_oc["solver_mean"] == pytest.approx(0.576, abs=1e-6)
    assert v14_oc["gemini_vs_solver_ratio"] == pytest.approx(0.351 / 0.576, abs=1e-6)
    assert v14_oc["luck_adj_mean"] == pytest.approx(0.309555, abs=1e-4)
    assert v14_oc["luck_adj_ratio"] == pytest.approx(0.556949, abs=1e-4)

    v14_ip = SNIPPET.load_committed_v14_baseline(
        committed_root,
        tier="hard",
        seeds=list(range(10)),
        harness="inproc",
        model_id="gemini-4-carbon",
    )
    assert v14_ip["n_seeds"] == 10
    assert v14_ip["gemini_mean"] == pytest.approx(0.379, abs=1e-6)
    assert v14_ip["solver_mean"] == pytest.approx(0.576, abs=1e-6)
    assert v14_ip["gemini_vs_solver_ratio"] == pytest.approx(0.379 / 0.576, abs=1e-6)

    v14_30 = SNIPPET.load_v14_from_json(
        committed_root / "v1.4" / "paired_table_gemini.json",
        tier="hard",
        harness="opencode",
        model_id="gemini-4-carbon",
    )
    assert v14_30["n_seeds"] == 30
    assert v14_30["gemini_mean"] == pytest.approx(0.3223333, abs=1e-5)
    assert v14_30["solver_mean"] == pytest.approx(0.499, abs=1e-6)


def test_positive_ship_gate_cli_and_dynamic_numbers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p1 = _sample_v16_payload()
    v16_file_1 = tmp_path / "v16_pass_1.json"
    out_md_1 = tmp_path / "out_1.md"
    out_json_1 = tmp_path / "out_1.json"
    v16_file_1.write_text(json.dumps(p1), encoding="utf-8")

    rc1 = SNIPPET.main(
        [
            "--v16-json",
            str(v16_file_1),
            "--out-md",
            str(out_md_1),
            "--out-json",
            str(out_json_1),
            "--strict-exit",
        ]
    )
    assert rc1 == 0
    stdout_1 = capsys.readouterr().out
    md_1 = out_md_1.read_text(encoding="utf-8")
    rep_1 = json.loads(out_json_1.read_text(encoding="utf-8"))
    assert stdout_1 == md_1
    assert rep_1["ship_gates"]["ship_ready"] is True
    assert rep_1["ship_gates"]["failed_gates"] == []
    assert "Social bias layer (opt-in V1.6, `CANARY_PROVIDER=v16:v5_full9_cocktail`)" in md_1
    assert "**+0.235" in md_1
    assert "**41% [12%, 69%]**; luck-adjusted 41% [14%, 68%]" in md_1
    assert "+0.351 \u00b1 0.312" in md_1
    assert "61% [3%, 104%]; luck-adjusted 56% [21%, 80%]" in md_1
    assert "+0.576 \u00b1 0.108" in md_1
    assert "\u2014" not in md_1
    assert "\u2013" not in md_1

    p2 = _sample_v16_payload(
        variant="v1_anchoring_authority_confirmation",
        provider_spec="v16:v1_anchoring_authority_confirmation",
        gemini_mean=0.1728,
        gemini_vs_solver_ratio=0.30,
        gemini_vs_solver_ratio_ci_95=[0.07, 0.55],
        luck_adj_ratio=0.33,
        luck_adj_ratio_ci_95=[0.11, 0.58],
        per_seed=[],
        gemini_ci_half=0.222,
    )
    v16_file_2 = tmp_path / "v16_pass_2.json"
    v16_file_2.write_text(json.dumps(p2), encoding="utf-8")
    md_2, rep_2 = SNIPPET.build_report(v16_json_path=v16_file_2)
    assert rep_2["ship_gates"]["ship_ready"] is True
    assert "**+0.173 \u00b1 0.222**" in md_2
    assert "**30% [7%, 55%]**; luck-adjusted 33% [11%, 58%]" in md_2
    assert "+0.235" not in md_2


def test_negative_result_and_each_individual_ship_gate_failure(tmp_path: Path) -> None:
    v14_control = {
        "variant": "v0_v14_control",
        "tier": "hard",
        "harness": "opencode",
        "model": "opencode:google/gemini-4-carbon",
        "n_seeds": 10,
        "seeds": list(range(10)),
        "gemini_mean": 0.351,
        "gemini_ci_half": 0.312,
        "solver_mean": 0.576,
        "solver_ci_half": 0.108,
        "gemini_vs_solver_ratio": 0.351 / 0.576,
        "gemini_vs_solver_ratio_ci_95": [0.03, 1.04],
        "luck_adj_mean": 0.310,
        "solver_luck_adj_mean": 0.556,
        "luck_adj_ratio": 0.56,
        "luck_adj_ratio_ci_95": [0.21, 0.80],
    }
    v14_path = tmp_path / "v14_base.json"
    v14_path.write_text(json.dumps(v14_control), encoding="utf-8")

    higher_ratio_path = tmp_path / "higher_ratio.json"
    higher_ratio_path.write_text(
        json.dumps(_sample_v16_payload(gemini_mean=0.432, gemini_vs_solver_ratio=0.75)),
        encoding="utf-8",
    )
    assert SNIPPET.main(["--v16-json", str(higher_ratio_path), "--v14-json", str(v14_path)]) == 0
    assert (
        SNIPPET.main(
            ["--v16-json", str(higher_ratio_path), "--v14-json", str(v14_path), "--strict-exit"]
        )
        == 1
    )
    md_hi, rep_hi = SNIPPET.build_report(v16_json_path=higher_ratio_path, v14_json_path=v14_path)
    assert rep_hi["ship_gates"]["ship_ready"] is False
    assert rep_hi["ship_gates"]["failed_gates"] == ["ratio_below_v14"]
    assert "NOT PASSED (`ratio_below_v14`)" in md_hi
    assert "negative / non-ship result" in md_hi

    tie_path = tmp_path / "tie_ratio.json"
    tie_path.write_text(
        json.dumps(
            _sample_v16_payload(gemini_mean=0.351, gemini_vs_solver_ratio=0.351 / 0.576)
        ),
        encoding="utf-8",
    )
    _, rep_tie = SNIPPET.build_report(v16_json_path=tie_path, v14_json_path=v14_path)
    assert rep_tie["ship_gates"]["ratio_below_v14"] is False
    assert rep_tie["ship_gates"]["ship_ready"] is False

    dn_fail_path = tmp_path / "dn_fail.json"
    dn_fail_path.write_text(
        json.dumps(_sample_v16_payload(do_nothing_mean=0.01)),
        encoding="utf-8",
    )
    md_dn, rep_dn = SNIPPET.build_report(v16_json_path=dn_fail_path, v14_json_path=v14_path)
    assert rep_dn["ship_gates"]["failed_gates"] == ["do_nothing_zero"]
    assert "NOT PASSED (`do_nothing_zero`)" in md_dn

    se_fail_path = tmp_path / "se_fail.json"
    se_fail_path.write_text(
        json.dumps(_sample_v16_payload(stop_early_mean=-1.0)),
        encoding="utf-8",
    )
    md_se, rep_se = SNIPPET.build_report(v16_json_path=se_fail_path, v14_json_path=v14_path)
    assert rep_se["ship_gates"]["failed_gates"] == ["stop_early_zero"]
    assert "NOT PASSED (`stop_early_zero`)" in md_se

    cal_fail_path = tmp_path / "cal_fail.json"
    cal_fail_path.write_text(
        json.dumps(_sample_v16_payload(solver_calibration_diff=0.02)),
        encoding="utf-8",
    )
    md_cal, rep_cal = SNIPPET.build_report(v16_json_path=cal_fail_path, v14_json_path=v14_path)
    assert rep_cal["ship_gates"]["failed_gates"] == ["solver_calibration_zero"]
    assert "NOT PASSED (`solver_calibration_zero`)" in md_cal

    rep_fail_path = tmp_path / "rep_fail.json"
    rep_fail_path.write_text(
        json.dumps(_sample_v16_payload(replay_verified_count=9, replay_verified_rate=0.9)),
        encoding="utf-8",
    )
    md_rep, rep_rep = SNIPPET.build_report(v16_json_path=rep_fail_path, v14_json_path=v14_path)
    assert rep_rep["ship_gates"]["failed_gates"] == ["replay_verified"]
    assert "NOT PASSED (`replay_verified`)" in md_rep
    assert "`9/10` episodes replay-verified" in md_rep


def test_end_to_end_with_real_v16_eval_matrix_fake_output(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch_matrix"
    matrix_json = tmp_path / "matrix_v1.json"
    V16_MATRIX.evaluate_matrix(
        variant="v1_anchoring_authority_confirmation",
        tier="hard",
        seeds=[0, 1],
        harness="opencode",
        jobs=2,
        scratch_dir=scratch,
        out_path=matrix_json,
        fake=True,
    )
    md, summary = SNIPPET.build_report(
        v16_json_path=matrix_json,
        v14_seeds_spec="match",
    )
    assert summary["v16_seeds"] == [0, 1]
    assert summary["v14_seeds"] == [0, 1]
    assert summary["ship_gates"]["do_nothing_zero"] is True
    assert summary["ship_gates"]["stop_early_zero"] is True
    assert summary["ship_gates"]["solver_calibration_zero"] is True
    assert summary["ship_gates"]["replay_verified"] is True
    assert "[fake stub]" in md
    assert "\u2014" not in md
    assert "\u2013" not in md


def test_hygiene_and_malformed_inputs_rejected(tmp_path: Path) -> None:
    bad_mole = tmp_path / "bad_mole.json"
    bad_mole.write_text(json.dumps({**_sample_v16_payload(), "mole": "e04"}), encoding="utf-8")
    with pytest.raises(ValueError, match="forbidden key 'mole'"):
        SNIPPET.build_report(v16_json_path=bad_mole)

    bad_key = tmp_path / "bad_key.json"
    bad_key.write_text(
        json.dumps({**_sample_v16_payload(), "note": "AIzaSyFakeSecretKeyValue999999999"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="secret key pattern"):
        SNIPPET.build_report(v16_json_path=bad_key)

    bad_missing = tmp_path / "bad_missing.json"
    missing_payload = _sample_v16_payload()
    del missing_payload["gemini_vs_solver_ratio"]
    bad_missing.write_text(json.dumps(missing_payload), encoding="utf-8")
    with pytest.raises(ValueError, match="gemini_vs_solver_ratio"):
        SNIPPET.build_report(v16_json_path=bad_missing)
