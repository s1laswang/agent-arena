from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from canary.env import Env
from canary.gemini.access_vision import (
    SOC_VISION_SCHEMA,
    analyze_soc_raster,
    collect_soc_observations,
    raster_sha256,
    render_soc_raster,
)
from canary.gemini.ledger import read_ledger
from canary.llm.base import MissingKeyError
import scripts.run_access_vision as runner

ALLOWED_TOOLS = frozenset({
    "list_employees",
    "read_access_logs",
    "plant_canary",
    "check_leak_feed",
    "advance_day",
})


class StrictPublicToolProxy:
    def __init__(self, env: Env):
        object.__setattr__(self, "_inner_call", env.call)
        object.__setattr__(self, "called_tools", [])

    def call(self, tool: str, args: dict):
        assert tool in ALLOWED_TOOLS, f"disallowed tool called during SOC rendering: {tool}"
        self.called_tools.append(tool)
        return self._inner_call(tool, args)

    def __getattr__(self, name: str):
        raise AssertionError(f"hidden attribute access forbidden: {name}")


class FakeModelsAPI:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeSDKClient:
    def __init__(self, responses: list):
        self.models = FakeModelsAPI(responses)


def _fake_response(payload: dict | str, *, tin: int = 920, tout: int = 140, thoughts: int = 410):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    um = SimpleNamespace(
        prompt_token_count=tin,
        candidates_token_count=tout,
        thoughts_token_count=thoughts,
        cached_content_token_count=0,
    )
    return SimpleNamespace(text=text, usage_metadata=um, model_version="gemini-4-carbon")


def test_strict_public_tool_isolation_and_raster_determinism():
    env_a = Env("medium", 0)
    proxy_a = StrictPublicToolProxy(env_a)
    obs_a = collect_soc_observations(proxy_a, seed_label=0)
    png_a = render_soc_raster(obs_a)

    assert set(proxy_a.called_tools) == ALLOWED_TOOLS
    assert png_a[:8] == b"\x89PNG\r\n\x1a\n"

    env_b = Env("medium", 0)
    obs_b = collect_soc_observations(StrictPublicToolProxy(env_b), seed_label=0)
    png_b = render_soc_raster(obs_b)
    assert raster_sha256(png_a) == raster_sha256(png_b)

    env_c = Env("medium", 1)
    png_c = render_soc_raster(collect_soc_observations(StrictPublicToolProxy(env_c), seed_label=1))
    assert raster_sha256(png_a) != raster_sha256(png_c)

    with Image.open(io.BytesIO(png_a)) as im:
        assert im.format == "PNG"
        assert im.size == (1880, 1020)
        colors = im.getcolors(maxcolors=50000)
        assert colors is not None and len(colors) > 25


def test_analyze_soc_raster_sends_png_part_and_records_ledger(tmp_path, monkeypatch):
    ledger_file = tmp_path / "ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    png_bytes = render_soc_raster(collect_soc_observations(Env("medium", 0), seed_label=0))
    fake_sdk = FakeSDKClient([
        _fake_response({
            "top_suspect_ids": ["E05", "e02", "invalid_id"],
            "suspected_decoy_ids": ["e19"],
            "confidence": 0.96,
            "canary_leak_summary": "c5=C, c8=B, c9=B all matched e05",
            "visual_reasoning": "e19 has 13/27 after-hours framing\u2014while e05 matches all 3/3 surfaced canaries.",
        })
    ])

    res = analyze_soc_raster(
        png_bytes,
        model_id="gemini-4-carbon",
        sdk_client=fake_sdk,
        run_id="unit-test-run",
        seed=0,
        valid_ids={f"e{i:02d}" for i in range(20)},
    )

    assert len(fake_sdk.models.calls) == 1
    call = fake_sdk.models.calls[0]
    assert call["model"] == "gemini-4-carbon"
    img_part, prompt_part = call["contents"]
    assert img_part.inline_data.mime_type == "image/png"
    assert img_part.inline_data.data == png_bytes
    assert isinstance(prompt_part, str) and "Panel A" in prompt_part
    assert call["config"].response_mime_type == "application/json"
    assert call["config"].response_json_schema == SOC_VISION_SCHEMA

    pred = res["prediction"]
    assert pred["top_suspect_ids"] == ["e05", "e02"]
    assert pred["suspected_decoy_ids"] == ["e19"]
    assert "\u2014" not in pred["visual_reasoning"]

    rows = read_ledger([ledger_file])
    assert len(rows) == 1
    assert rows[0]["feature"] == "multimodal_evidence"
    assert rows[0]["model"] == "gemini-4-carbon"
    assert rows[0]["ok"] is True
    assert rows[0]["in"] == 920
    assert rows[0]["out"] == 140
    assert rows[0]["thinking"] == 410
    assert rows[0]["run_id"] == "unit-test-run"


def test_analyze_soc_raster_retries_transient_failures(tmp_path, monkeypatch):
    ledger_file = tmp_path / "retry_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))

    class RateLimitError(Exception):
        status_code = 429

    fake_sdk = FakeSDKClient([
        RateLimitError("429 RESOURCE_EXHAUSTED"),
        _fake_response(""),
        _fake_response({
            "top_suspect_ids": ["e09"],
            "suspected_decoy_ids": ["e05"],
            "confidence": 0.91,
            "canary_leak_summary": "5/5 canaries matched e09",
            "visual_reasoning": "e09 matches all 5 surfaced canary variants.",
        }),
    ])

    sleeps: list[float] = []
    res = analyze_soc_raster(
        b"\x89PNG\r\n\x1a\nstub",
        sdk_client=fake_sdk,
        max_retries=3,
        sleep_fn=sleeps.append,
    )
    assert res["prediction"]["top_suspect_ids"] == ["e09"]
    assert len(sleeps) == 2

    rows = read_ledger([ledger_file])
    assert [r["ok"] for r in rows] == [False, False, True]


def test_keyless_raises_missing_key_error(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    with pytest.raises(MissingKeyError):
        analyze_soc_raster(b"\x89PNG\r\n\x1a\n", max_retries=0)


def test_run_access_vision_cli_writes_all_artifacts(tmp_path, monkeypatch):
    ledger_file = tmp_path / "cli_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "access-heatmap-carbon"

    fake_sdk = FakeSDKClient([
        _fake_response({
            "top_suspect_ids": ["e05"],
            "suspected_decoy_ids": ["e19"],
            "confidence": 0.98,
            "canary_leak_summary": "c5=C, c8=B, c9=B -> e05",
            "visual_reasoning": "Seed 0: e19 is framed decoy; e05 matches all 3/3 surfaced canaries.",
        }),
        _fake_response({
            "top_suspect_ids": ["e02", "e09"],
            "suspected_decoy_ids": ["e00"],
            "confidence": 0.90,
            "canary_leak_summary": "c7=A, c12=B -> e02 and e09; regular leaks favor e02",
            "visual_reasoning": "Seed 1: e00 is framed decoy cleared by c12; e02 leads e09 on regular leak opens.",
        }),
        _fake_response({
            "top_suspect_ids": ["e09"],
            "suspected_decoy_ids": ["e05"],
            "confidence": 0.99,
            "canary_leak_summary": "5/5 surfaced canaries -> e09",
            "visual_reasoning": "Seed 2: e05 shows framing spike with 0/5 canary hits; e09 matches 5/5.",
        }),
    ])

    rc = runner.main(["--seeds", "0,1,2", "--out", str(out_dir)], sdk_client=fake_sdk)
    assert rc == 0

    meta = json.loads((out_dir / "meta.json").read_text())
    results = json.loads((out_dir / "results.json").read_text())
    summary_md = (out_dir / "summary.md").read_text()

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "soc_access_vision"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["n_images_read_by_model"] == 3
    assert meta["commit"]
    assert meta["timestamp"]
    assert "run_access_vision.py" in meta["command"]
    assert meta["usage"]["calls"] == 3

    assert results["metrics"]["top1_mole_accuracy"] == 1.0
    assert results["metrics"]["top1_decoy_accuracy"] == 1.0
    assert results["metrics"]["naive_after_hours_baseline_mole_accuracy"] == 0.0
    assert results["metrics"]["naive_after_hours_baseline_decoy_trap_rate"] == 1.0

    for item in meta["rasters"]:
        p = out_dir / item["path"]
        assert p.exists()
        assert raster_sha256(p.read_bytes()) == item["sha256"]

    assert "\u2014" not in summary_md and "\u2013" not in summary_md


def test_no_comments_or_em_dashes_in_created_python_files():
    root = Path(__file__).resolve().parents[1]
    targets = [
        root / "canary/gemini/access_vision.py",
        root / "scripts/run_access_vision.py",
        root / "tests/test_access_vision.py",
    ]
    for path in targets:
        text = path.read_text()
        assert "\u2014" not in text and "\u2013" not in text, f"dash found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment found in {path}: {comments[0]}"
