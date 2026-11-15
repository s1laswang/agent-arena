from __future__ import annotations

from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tokenize
from types import SimpleNamespace

from PIL import Image
import pytest

from canary.gemini.carbon_forensics import (
    DEFAULT_MODEL,
    FEATURE,
    SUBROLE,
    analyze_carbon_chart_bytes,
    rational_ev_threshold,
    render_carbon_forensic_chart,
    score_carbon_diagnosis,
    select_carbon_episodes,
    summarize_carbon_forensics,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.llm import MissingKeyError
from scripts.run_carbon_trajectory_forensics import run_carbon_forensics

REPO_ROOT = Path(__file__).resolve().parents[1]
V14_RUNS_ROOT = REPO_ROOT / "data" / "runs" / "committed" / "v1.4"
EXPANDED_OUT = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "carbon-trajectory-forensics-v14-expanded"
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


class _MockModels:
    def __init__(self, payloads: list[dict]):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        payload = self._payloads.pop(0)
        usage = SimpleNamespace(
            prompt_token_count=2299,
            candidates_token_count=330,
            thoughts_token_count=680,
            cached_content_token_count=0,
        )
        return SimpleNamespace(text=json.dumps(payload), usage_metadata=usage, candidates=[])


class _MockClient:
    def __init__(self, payloads: list[dict]):
        self.models = _MockModels(payloads)


def test_ev_threshold_formula_and_stop_day_scoring_keyless():
    for v_val in (1.0, 0.85, 0.72, 0.67, 0.56, 0.25, 0.05):
        expected = 1.0 / (1.0 + v_val)
        assert rational_ev_threshold(v_val, -1.0) == pytest.approx(expected, abs=1e-12)
    assert rational_ev_threshold(0.0, -1.0) == pytest.approx(1.0, abs=1e-12)
    assert rational_ev_threshold(-1.0, -1.0) == 1.0
    assert rational_ev_threshold(-1.5, -1.0) == 1.0

    selected = select_carbon_episodes(V14_RUNS_ROOT, n_wrong=4, n_high=8)
    assert len(selected) == 12
    assert sum(1 for t in selected if t.cohort == "wrong_or_fooled") == 4
    assert sum(1 for t in selected if t.cohort == "high_scoring") == 8
    assert len({(t.agent, t.tier, t.seed) for t in selected}) == 12
    assert {t.tier for t in selected} == {"hard", "medium"}

    wrong_traj = next(t for t in selected if not t.correct)
    high_traj = next(t for t in selected if t.correct)

    exact_diag = {
        "accused_below_ev_threshold": wrong_traj.accused_below_ev_threshold,
        "estimated_accuse_day": wrong_traj.actual_accuse_day,
        "hidden_bleed_gap_present": wrong_traj.hidden_bleed_gap_present,
        "entropy_lags_solver": wrong_traj.entropy_lags_solver,
        "fooled_step_summary": "Exact stop day and EV threshold match.",
        "primary_failure_pattern": "fooled_wrong_suspect",
    }
    sc_exact = score_carbon_diagnosis(wrong_traj, exact_diag)
    assert sc_exact == {
        "threshold_match": True,
        "day_abs_error": 0,
        "day_within_1": True,
        "day_exact": True,
        "bleed_gap_match": True,
        "entropy_lag_match": True,
        "outcome_pattern_match": True,
    }

    off_by_one_diag = {
        **exact_diag,
        "accused_below_ev_threshold": not wrong_traj.accused_below_ev_threshold,
        "estimated_accuse_day": wrong_traj.actual_accuse_day - 1,
        "primary_failure_pattern": "none_justified_accusation",
    }
    sc_off1 = score_carbon_diagnosis(wrong_traj, off_by_one_diag)
    assert sc_off1["threshold_match"] is False
    assert sc_off1["day_abs_error"] == 1
    assert sc_off1["day_within_1"] is True
    assert sc_off1["day_exact"] is False
    assert sc_off1["outcome_pattern_match"] is False

    off_by_three_diag = {
        "accused_below_ev_threshold": high_traj.accused_below_ev_threshold,
        "estimated_accuse_day": high_traj.actual_accuse_day + 3,
        "hidden_bleed_gap_present": not high_traj.hidden_bleed_gap_present,
        "entropy_lags_solver": not high_traj.entropy_lags_solver,
        "fooled_step_summary": "Shifted stop day by three days.",
        "primary_failure_pattern": "none_justified_accusation",
    }
    sc_off3 = score_carbon_diagnosis(high_traj, off_by_three_diag)
    assert sc_off3["threshold_match"] is True
    assert sc_off3["day_abs_error"] == 3
    assert sc_off3["day_within_1"] is False
    assert sc_off3["day_exact"] is False
    assert sc_off3["bleed_gap_match"] is False
    assert sc_off3["entropy_lag_match"] is False
    assert sc_off3["outcome_pattern_match"] is True

    sub_ev_traj = replace(
        high_traj,
        true_v_at_accuse=0.60,
        ev_threshold_at_accuse=rational_ev_threshold(0.60, -1.0),
        accused_posterior_at_accuse=0.55,
        accused_below_ev_threshold=True,
        correct=False,
    )
    assert sub_ev_traj.ev_threshold_at_accuse == pytest.approx(1.0 / 1.60, abs=1e-12)
    sc_sub_ev = score_carbon_diagnosis(
        sub_ev_traj,
        {
            "accused_below_ev_threshold": True,
            "estimated_accuse_day": sub_ev_traj.actual_accuse_day,
            "hidden_bleed_gap_present": sub_ev_traj.hidden_bleed_gap_present,
            "entropy_lags_solver": sub_ev_traj.entropy_lags_solver,
            "fooled_step_summary": "Sub-EV star sits below 1/(1+V).",
            "primary_failure_pattern": "premature_early_accusation",
        },
    )
    assert sc_sub_ev["threshold_match"] is True
    assert sc_sub_ev["day_exact"] is True
    assert sc_sub_ev["outcome_pattern_match"] is True


def test_keyless_guard_and_mocked_runner_provenance(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)

    ledger_path = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_path))

    sample = select_carbon_episodes(V14_RUNS_ROOT, n_wrong=1, n_high=1)
    assert len(sample) == 2
    png_bytes = render_carbon_forensic_chart(sample[0], dpi=80)
    assert png_bytes[:8] == PNG_MAGIC

    with pytest.raises(MissingKeyError):
        analyze_carbon_chart_bytes(png_bytes, max_retries=0)

    payloads = [
        {
            "accused_below_ev_threshold": t.accused_below_ev_threshold,
            "estimated_accuse_day": t.actual_accuse_day,
            "hidden_bleed_gap_present": t.hidden_bleed_gap_present,
            "entropy_lags_solver": t.entropy_lags_solver,
            "fooled_step_summary": f"Panel 1 to Panel 4 summary{EM_DASH}clean ASCII output.",
            "primary_failure_pattern": (
                "none_justified_accusation" if t.correct else "fooled_wrong_suspect"
            ),
        }
        for t in sample
    ]
    out_dir = tmp_path / "results" / "gemini_roles" / "multimodal_evidence" / "mock-expanded"
    res = run_carbon_forensics(
        runs_dir=V14_RUNS_ROOT,
        out_dir=out_dir,
        model_id=DEFAULT_MODEL,
        n_wrong=1,
        n_high=1,
        sdk_client=_MockClient(payloads),
        command_str="python scripts/run_carbon_trajectory_forensics.py --n-wrong 1 --n-high 1",
        dpi=80,
    )
    assert res["meta"]["n_charts_analyzed"] == 2
    assert res["meta"]["n_images_read_by_model"] == 2
    prov = _inspect_run(out_dir / "meta.json", tmp_path, V14_RUNS_ROOT)
    assert prov["verified"] is True
    assert prov["errors"] == []
    assert prov["secret_leaks"] == []
    assert prov["count"] == 2


def test_expanded_v14_committed_charts_sha256_scoring_and_provenance():
    meta_path = EXPANDED_OUT / "meta.json"
    records_path = EXPANDED_OUT / "diagnoses.json"
    summary_path = EXPANDED_OUT / "summary.md"
    charts_dir = EXPANDED_OUT / "charts"

    assert meta_path.is_file()
    assert records_path.is_file()
    assert summary_path.is_file()
    assert charts_dir.is_dir()

    meta_text = meta_path.read_text(encoding="utf-8")
    records_text = records_path.read_text(encoding="utf-8")
    summary_text = summary_path.read_text(encoding="utf-8")

    for txt in (meta_text, records_text, summary_text):
        assert EM_DASH not in txt
        assert EN_DASH not in txt

    meta = json.loads(meta_text)
    records = json.loads(records_text)

    assert meta["role"] == FEATURE
    assert meta["subrole"] == SUBROLE
    assert meta["model_id"] == DEFAULT_MODEL
    assert meta["tiers_version"] == "v1.4"
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert meta["n_charts_analyzed"] == 12
    assert meta["n_images_read_by_model"] == 12
    assert len(records) == meta["n_charts_analyzed"]

    assert sum(1 for r in records if r["cohort"] == "wrong_or_fooled") == 4
    assert sum(1 for r in records if r["cohort"] == "high_scoring") == 8

    png_files_on_disk = sorted(charts_dir.glob("*.png"))
    assert len(png_files_on_disk) == meta["n_charts_analyzed"]

    referenced_paths: list[Path] = []
    for idx, rec in enumerate(records):
        assert rec["episode_index"] == idx
        chart_fp = EXPANDED_OUT / rec["chart_path"]
        assert chart_fp.is_file()
        referenced_paths.append(chart_fp)

        raw = chart_fp.read_bytes()
        assert raw[:8] == PNG_MAGIC
        assert len(raw) == rec["chart_bytes_len"]
        assert hashlib.sha256(raw).hexdigest() == rec["chart_sha256"]

        with Image.open(io.BytesIO(raw)) as img:
            assert img.format == "PNG"
            assert img.size[0] >= 1800
            assert img.size[1] >= 2000

        gt = rec["ground_truth"]
        diag = rec["gemini_diagnosis"]
        sc = rec["scoring"]

        expected_ev = rational_ev_threshold(gt["true_v_at_accuse"], -1.0)
        assert gt["ev_threshold_at_accuse"] == pytest.approx(expected_ev, abs=1e-5)
        assert gt["accused_below_ev_threshold"] is (
            gt["accused_posterior_at_accuse"] < gt["ev_threshold_at_accuse"]
        )

        day_err = abs(int(diag["estimated_accuse_day"]) - int(gt["actual_accuse_day"]))
        assert sc["threshold_match"] is (
            bool(diag["accused_below_ev_threshold"]) == bool(gt["accused_below_ev_threshold"])
        )
        assert sc["day_abs_error"] == day_err
        assert sc["day_within_1"] is (day_err <= 1)
        assert sc["day_exact"] is (day_err == 0)
        assert sc["bleed_gap_match"] is (
            bool(diag["hidden_bleed_gap_present"]) == bool(gt["hidden_bleed_gap_present"])
        )
        assert sc["entropy_lag_match"] is (
            bool(diag["entropy_lags_solver"]) == bool(gt["entropy_lags_solver"])
        )

        assert rec["usage"]["in"] > 0
        assert rec["usage"]["out"] > 0
        assert rec["usage"]["cost_usd"] > 0.0

    assert sorted(referenced_paths) == png_files_on_disk

    recomputed = summarize_carbon_forensics(records)
    for key in (
        "n_charts_analyzed",
        "visual_threshold_accuracy",
        "accuse_day_within_1_accuracy",
        "accuse_day_exact_accuracy",
        "hidden_bleed_gap_accuracy",
        "entropy_lag_accuracy",
        "outcome_pattern_accuracy",
    ):
        assert meta[key] == pytest.approx(recomputed[key], abs=1e-6)
    assert meta["usage"]["calls"] == 12
    assert meta["usage"]["in"] == recomputed["usage"]["in"] > 0
    assert meta["usage"]["out"] == recomputed["usage"]["out"] > 0
    assert meta["usage"]["thinking"] == recomputed["usage"]["thinking"] > 0
    assert meta["usage"]["cost_usd"] == pytest.approx(recomputed["usage"]["cost_usd"], abs=1e-6)

    prov = _inspect_run(meta_path, REPO_ROOT, V14_RUNS_ROOT)
    assert prov["verified"] is True
    assert prov["errors"] == []
    assert prov["secret_leaks"] == []
    assert prov["role"] == FEATURE
    assert prov["model_id"] == DEFAULT_MODEL
    assert prov["count"] == 12
    assert prov["tokens_in"] == meta["usage"]["in"]
    assert prov["tokens_out"] == meta["usage"]["out"]
    assert prov["thinking_tokens"] == meta["usage"]["thinking"]
    assert prov["cost_usd"] == pytest.approx(meta["usage"]["cost_usd"], abs=1e-6)

    for fp in sorted(p for p in EXPANDED_OUT.rglob("*") if p.is_file()):
        assert scan_file_secrets(fp, REPO_ROOT) == []


def test_source_files_have_zero_comments_zero_hashes_zero_dashes_and_zero_secrets():
    targets = [
        REPO_ROOT / "canary" / "gemini" / "carbon_forensics.py",
        REPO_ROOT / "scripts" / "run_carbon_trajectory_forensics.py",
        REPO_ROOT / "tests" / "test_carbon_forensics.py",
        REPO_ROOT / "tests" / "test_carbon_forensics_expanded.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text
        assert EN_DASH not in text
        assert HASH_CHAR not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == []
        assert scan_file_secrets(path, REPO_ROOT) == []
