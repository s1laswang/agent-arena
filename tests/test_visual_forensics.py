from __future__ import annotations

import io
import json
from pathlib import Path
import re
from types import SimpleNamespace

from PIL import Image
import pytest

from canary.gemini import read_ledger
from canary.gemini.visual_forensics import (
    DEFAULT_MODEL,
    FEATURE,
    FORENSIC_PROMPT,
    analyze_chart_bytes,
    rational_ev_threshold,
    render_forensic_chart,
    score_diagnosis,
    select_forensic_episodes,
    summarize_forensics,
)
from canary.llm import MissingKeyError

REPO_ROOT = Path(__file__).resolve().parents[1]
V13_DIR = REPO_ROOT / "data" / "runs" / "committed" / "v1.3"


class FakeServerError(RuntimeError):
    status_code = 503


class FakeModels:
    def __init__(self, payloads: list[dict | BaseException]):
        self._payloads = list(payloads)
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._payloads.pop(0)
        if isinstance(item, BaseException):
            raise item
        usage = SimpleNamespace(
            prompt_token_count=1420,
            candidates_token_count=185,
            thoughts_token_count=310,
            cached_content_token_count=0,
        )
        return SimpleNamespace(text=json.dumps(item), usage_metadata=usage, candidates=[])


class FakeGenAIClient:
    def __init__(self, payloads: list[dict | BaseException]):
        self.models = FakeModels(payloads)


def test_select_and_extract_trajectories_v13():
    selected = select_forensic_episodes(V13_DIR, n_wrong=3, n_high=3)
    assert len(selected) == 6

    wrong = [t for t in selected if t.cohort == "wrong_or_premature"]
    high = [t for t in selected if t.cohort == "high_scoring"]
    assert len(wrong) == 3
    assert len(high) == 3

    for t in wrong:
        assert not t.correct
        assert t.score == -1.0
        assert t.accused_below_ev_threshold is True
        assert t.accused_posterior_at_accuse < t.ev_threshold_at_accuse

    for t in high:
        assert t.correct
        assert t.score >= 0.70
        assert t.accused_below_ev_threshold is False
        assert t.accused_posterior_at_accuse >= t.ev_threshold_at_accuse

    assert any(t.hidden_bleed_gap_present for t in selected)
    assert any(not t.hidden_bleed_gap_present for t in selected)

    for t in selected:
        expected_emp = 20 if t.tier == "medium" else 30
        assert len(t.employees) == expected_emp
        assert len(t.posterior_matrix) == expected_emp
        assert len(t.days) == t.actual_accuse_day
        for col_idx, tv in enumerate(t.true_v):
            col_sum = sum(t.posterior_matrix[row_idx][col_idx] for row_idx in range(expected_emp))
            assert col_sum == pytest.approx(1.0, abs=1e-5)
            assert t.known_v[col_idx] >= tv - 1e-9
            assert t.ev_threshold[col_idx] == pytest.approx(rational_ev_threshold(tv, -1.0), abs=1e-9)


def test_render_forensic_chart_png_bytes(tmp_path):
    traj = select_forensic_episodes(V13_DIR, n_wrong=1, n_high=0)[0]
    out_png = tmp_path / "charts" / "ep_0.png"
    png_bytes = render_forensic_chart(traj, out_path=out_png)

    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"
    assert out_png.exists()
    assert out_png.read_bytes() == png_bytes

    img = Image.open(io.BytesIO(png_bytes))
    assert img.format == "PNG"
    assert img.size[0] >= 1600
    assert img.size[1] >= 1400


def test_analyze_chart_bytes_uses_part_from_bytes_and_ledgers_keyless(tmp_path, monkeypatch):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    traj = select_forensic_episodes(V13_DIR, n_wrong=1, n_high=0)[0]
    png_bytes = render_forensic_chart(traj)

    fake_payload = {
        "accused_below_ev_threshold": True,
        "estimated_accuse_day": traj.actual_accuse_day,
        "hidden_bleed_gap_present": True,
        "visual_diagnosis": "Posterior stays diffuse\u2014accused well below 1/(1+V) threshold.",
        "primary_failure_pattern": "premature_early_accusation",
    }
    fake_client = FakeGenAIClient([fake_payload])

    diag, usage = analyze_chart_bytes(
        png_bytes,
        model_id=DEFAULT_MODEL,
        run_id="keyless-test-run",
        chart_label="ep_0",
        sdk_client=fake_client,
    )

    assert diag["accused_below_ev_threshold"] is True
    assert diag["estimated_accuse_day"] == traj.actual_accuse_day
    assert diag["hidden_bleed_gap_present"] is True
    assert "\u2014" not in diag["visual_diagnosis"]
    assert diag["primary_failure_pattern"] == "premature_early_accusation"
    assert usage["in"] == 1420
    assert usage["out"] == 185
    assert usage["thinking"] == 310
    assert usage["cost_usd"] > 0.0

    assert len(fake_client.models.calls) == 1
    sent = fake_client.models.calls[0]
    assert sent["model"] == "gemini-4-carbon"
    parts = sent["contents"][0].parts
    assert len(parts) == 2
    assert parts[0].inline_data is not None
    assert parts[0].inline_data.mime_type == "image/png"
    assert parts[0].inline_data.data == png_bytes
    assert parts[1].text == FORENSIC_PROMPT
    assert not re.search(r"0\.183|0\.33|0\.498|seed", parts[1].text)

    rows = read_ledger([led])
    assert len(rows) == 1
    assert rows[0]["feature"] == FEATURE
    assert rows[0]["model"] == "gemini-4-carbon"
    assert rows[0]["ok"] is True
    assert rows[0]["run_id"] == "keyless-test-run"


def test_retries_and_missing_key_behavior(tmp_path, monkeypatch):
    led = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(led))
    monkeypatch.setenv("CANARY_LLM_MAX_RETRIES", "3")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setattr("canary.llm.base.load_env", lambda: None)

    traj = select_forensic_episodes(V13_DIR, n_wrong=0, n_high=1)[0]
    png_bytes = render_forensic_chart(traj)

    with pytest.raises(MissingKeyError):
        analyze_chart_bytes(png_bytes, max_retries=0)

    fake_payload = {
        "accused_below_ev_threshold": False,
        "estimated_accuse_day": traj.actual_accuse_day,
        "hidden_bleed_gap_present": traj.hidden_bleed_gap_present,
        "visual_diagnosis": "Top suspect posterior reaches certainty above 1/(1+V) before accusation.",
        "primary_failure_pattern": "none_justified_accusation",
    }
    flaky_client = FakeGenAIClient([FakeServerError("503 overloaded"), fake_payload])
    sleeps: list[float] = []
    diag, _ = analyze_chart_bytes(
        png_bytes,
        run_id="retry-test",
        sdk_client=flaky_client,
        sleep_fn=sleeps.append,
    )
    assert len(sleeps) == 1
    assert diag["accused_below_ev_threshold"] is False
    rows = read_ledger([led])
    assert [r["ok"] for r in rows] == [False, True]


def test_scoring_and_summary_metrics():
    selected = select_forensic_episodes(V13_DIR, n_wrong=1, n_high=1)
    records = []
    for i, traj in enumerate(selected):
        diag = {
            "accused_below_ev_threshold": traj.accused_below_ev_threshold,
            "estimated_accuse_day": traj.actual_accuse_day + (1 if i == 0 else 0),
            "hidden_bleed_gap_present": traj.hidden_bleed_gap_present,
            "visual_diagnosis": "Clean trajectory reading.",
            "primary_failure_pattern": "none_justified_accusation",
        }
        records.append(
            {
                "scoring": score_diagnosis(traj, diag),
                "usage": {"in": 100, "out": 50, "thinking": 20, "cached": 0, "cost_usd": 0.001, "latency_s": 1.2},
            }
        )
    summary = summarize_forensics(records)
    assert summary["n_charts_analyzed"] == 2
    assert summary["visual_threshold_accuracy"] == 1.0
    assert summary["accuse_day_within_1_accuracy"] == 1.0
    assert summary["accuse_day_exact_accuracy"] == 0.5
    assert summary["hidden_bleed_gap_accuracy"] == 1.0
    assert summary["usage"]["calls"] == 2
