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
    collect_soc_observations,
    raster_sha256,
    render_soc_raster,
)
from canary.gemini.provenance import _inspect_run, scan_file_secrets
import scripts.run_access_vision_sweep as sweep

REPO_ROOT = Path(__file__).resolve().parents[1]
V14_ROOT = REPO_ROOT / "data" / "runs" / "committed" / "v1.4"
LOW_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "access-heatmap-v14-low-s8to11-carbon"
)
HIGH_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "access-heatmap-v14-high-s8to11-carbon"
)
EXPECTED_PAIRS = [
    ("medium", 8),
    ("medium", 9),
    ("hard", 8),
    ("hard", 9),
    ("hard", 10),
    ("hard", 11),
]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


class FakeModelsAPI:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def generate_content(self, *, model: str, contents: list, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._responses.pop(0)


class FakeSDKClient:
    def __init__(self, responses: list):
        self.models = FakeModelsAPI(responses)


def _fake_response(payload: dict, *, tin: int = 2001, tout: int = 410, thoughts: int = 300):
    um = SimpleNamespace(
        prompt_token_count=tin,
        candidates_token_count=tout,
        thoughts_token_count=thoughts,
        cached_content_token_count=0,
    )
    return SimpleNamespace(text=json.dumps(payload), usage_metadata=um, model_version="gemini-4-carbon")


def _public_obs(tier: str, seed: int) -> dict:
    env = Env(tier, seed)

    class _Proxy:
        def call(self, tool: str, args: dict):
            return env.call(tool, args)

    return collect_soc_observations(_Proxy(), seed_label=seed, tier=tier)


def test_low_and_high_sweeps_pass_provenance_strict():
    for label, run_dir in (("low", LOW_DIR), ("high", HIGH_DIR)):
        meta_path = run_dir / "meta.json"
        assert meta_path.is_file(), f"missing meta.json for {label}"
        prov = _inspect_run(meta_path, REPO_ROOT, V14_ROOT)
        assert prov["verified"] is True, f"{label} provenance failed: {prov}"
        assert prov["errors"] == []
        assert prov["secret_leaks"] == []
        assert prov["role"] == "multimodal_evidence"
        assert prov["model_id"] == "gemini-4-carbon"
        assert prov["count"] == 6
        assert prov["tokens_in"] == 12606
        assert prov["tokens_out"] > 0
        assert prov["cost_usd"] > 0

    low_meta = json.loads((LOW_DIR / "meta.json").read_text(encoding="utf-8"))
    high_meta = json.loads((HIGH_DIR / "meta.json").read_text(encoding="utf-8"))
    assert low_meta["usage"]["calls"] == 6
    assert high_meta["usage"]["calls"] == 6
    assert high_meta["usage"]["thinking"] > low_meta["usage"]["thinking"]

    assert "--thinking-level low" in low_meta["command"]
    assert "--thinking-level high" in high_meta["command"]
    normalized_low_cmd = (
        low_meta["command"]
        .replace("--thinking-level low", "--thinking-level high")
        .replace("access-heatmap-v14-low-s8to11-carbon", "access-heatmap-v14-high-s8to11-carbon")
    )
    assert normalized_low_cmd == high_meta["command"]


def test_paired_rasters_and_inputs_match_bit_for_bit():
    low_meta = json.loads((LOW_DIR / "meta.json").read_text(encoding="utf-8"))
    high_meta = json.loads((HIGH_DIR / "meta.json").read_text(encoding="utf-8"))
    low_res = json.loads((LOW_DIR / "results.json").read_text(encoding="utf-8"))
    high_res = json.loads((HIGH_DIR / "results.json").read_text(encoding="utf-8"))

    assert low_meta["tiers_version"] == "v1.4"
    assert high_meta["tiers_version"] == "v1.4"
    assert low_meta["tier_seeds"] == {"medium": [8, 9], "hard": [8, 9, 10, 11]}
    assert high_meta["tier_seeds"] == {"medium": [8, 9], "hard": [8, 9, 10, 11]}
    assert low_meta["commit"] == high_meta["commit"]

    low_rasters = {(r["tier"], int(r["seed"])): r for r in low_meta["rasters"]}
    high_rasters = {(r["tier"], int(r["seed"])): r for r in high_meta["rasters"]}
    low_worlds = {(w["tier"], int(w["seed"])): w for w in low_res["worlds"]}
    high_worlds = {(w["tier"], int(w["seed"])): w for w in high_res["worlds"]}

    assert list(low_rasters.keys()) == EXPECTED_PAIRS
    assert list(high_rasters.keys()) == EXPECTED_PAIRS
    assert list(low_worlds.keys()) == EXPECTED_PAIRS
    assert list(high_worlds.keys()) == EXPECTED_PAIRS

    for tier, seed in EXPECTED_PAIRS:
        lr = low_rasters[(tier, seed)]
        hr = high_rasters[(tier, seed)]
        lw = low_worlds[(tier, seed)]
        hw = high_worlds[(tier, seed)]

        low_png = LOW_DIR / lr["path"]
        high_png = HIGH_DIR / hr["path"]
        assert low_png.is_file()
        assert high_png.is_file()

        low_bytes = low_png.read_bytes()
        high_bytes = high_png.read_bytes()
        assert low_bytes[:8] == b"\x89PNG\r\n\x1a\n"
        assert low_bytes == high_bytes

        digest = raster_sha256(low_bytes)
        assert digest == raster_sha256(high_bytes)
        assert digest == lr["sha256"] == hr["sha256"]
        assert digest == lw["raster_sha256"] == hw["raster_sha256"]
        assert lr["bytes"] == hr["bytes"] == len(low_bytes)
        assert lr["size"] == hr["size"] == lw["raster_size"] == hw["raster_size"]

        expected_dims = (1880, 1020) if tier == "medium" else (2180, 1660)
        with Image.open(io.BytesIO(low_bytes)) as im:
            assert im.size == expected_dims

        rerendered = render_soc_raster(_public_obs(tier, seed))
        assert raster_sha256(rerendered) == digest

        assert lw["observable_summary"] == hw["observable_summary"]
        assert lw["ground_truth"] == hw["ground_truth"]
        assert lw["usage"]["in"] == hw["usage"]["in"]


def test_high_thinking_strictly_exceeds_low_and_calibrates_brier():
    low_meta = json.loads((LOW_DIR / "meta.json").read_text(encoding="utf-8"))
    high_meta = json.loads((HIGH_DIR / "meta.json").read_text(encoding="utf-8"))
    low_res = json.loads((LOW_DIR / "results.json").read_text(encoding="utf-8"))
    high_res = json.loads((HIGH_DIR / "results.json").read_text(encoding="utf-8"))

    assert high_meta["usage"]["thinking"] > low_meta["usage"]["thinking"]
    assert low_meta["usage"]["in"] == high_meta["usage"]["in"] == 12606

    for tier in ("medium", "hard"):
        low_tier_think = low_res["by_tier"][tier]["usage"]["thinking"]
        high_tier_think = high_res["by_tier"][tier]["usage"]["thinking"]
        assert high_tier_think > low_tier_think

    low_worlds = {(w["tier"], int(w["seed"])): w for w in low_res["worlds"]}
    high_worlds = {(w["tier"], int(w["seed"])): w for w in high_res["worlds"]}
    for pair in EXPECTED_PAIRS:
        assert high_worlds[pair]["usage"]["thinking"] > low_worlds[pair]["usage"]["thinking"]

    recomputed_low = sweep.compute_subset_metrics(low_res["worlds"])
    recomputed_high = sweep.compute_subset_metrics(high_res["worlds"])
    assert recomputed_low["brier_score"] == pytest.approx(low_meta["brier_score"], abs=1e-6)
    assert recomputed_high["brier_score"] == pytest.approx(high_meta["brier_score"], abs=1e-6)
    assert low_meta["top1_mole_accuracy"] == 1.0
    assert high_meta["top1_mole_accuracy"] == 1.0
    assert low_meta["top1_decoy_accuracy"] == 1.0
    assert high_meta["top1_decoy_accuracy"] == 1.0
    assert high_meta["brier_score"] < low_meta["brier_score"]
    assert high_meta["expected_calibration_error"] < low_meta["expected_calibration_error"]


def test_cli_thinking_level_is_sole_config_delta(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ablation_ledger.jsonl"))

    sample_payload = {
        "top_suspect_ids": ["e02"],
        "suspected_decoy_ids": ["e01"],
        "confidence": 0.99,
        "canary_leak_summary": "e02 matches 6/6 surfaced canaries",
        "visual_reasoning": "e01 is framed decoy; e02 matches 6/6 canaries.",
    }
    low_sdk = FakeSDKClient([_fake_response(sample_payload, thoughts=295)])
    high_sdk = FakeSDKClient([_fake_response(sample_payload, thoughts=10390)])

    rc_low = sweep.main(
        [
            "--tiers", "medium",
            "--medium-seeds", "8",
            "--thinking-level", "low",
            "--out", str(tmp_path / "low_out"),
        ],
        sdk_client=low_sdk,
    )
    rc_high = sweep.main(
        [
            "--tiers", "medium",
            "--medium-seeds", "8",
            "--thinking-level", "high",
            "--out", str(tmp_path / "high_out"),
        ],
        sdk_client=high_sdk,
    )
    assert rc_low == 0 and rc_high == 0

    low_call = low_sdk.models.calls[0]
    high_call = high_sdk.models.calls[0]
    assert low_call["model"] == high_call["model"] == "gemini-4-carbon"
    assert low_call["contents"][0].inline_data.data == high_call["contents"][0].inline_data.data
    assert low_call["contents"][1] == high_call["contents"][1]
    assert low_call["config"].response_json_schema == SOC_VISION_SCHEMA
    assert high_call["config"].response_json_schema == SOC_VISION_SCHEMA
    assert str(low_call["config"].thinking_config.thinking_level).upper().endswith("LOW")
    assert str(high_call["config"].thinking_config.thinking_level).upper().endswith("HIGH")


def test_owned_files_and_artifacts_have_zero_comments_dashes_and_secrets():
    python_targets = [
        REPO_ROOT / "canary" / "gemini" / "access_vision.py",
        REPO_ROOT / "scripts" / "run_access_vision_sweep.py",
        REPO_ROOT / "tests" / "test_access_vision_sweep.py",
        REPO_ROOT / "tests" / "test_access_vision_thinking_ablation.py",
    ]
    for path in python_targets:
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text and EN_DASH not in text, f"dash found in {path}"
        assert HASH_CHAR not in text, f"hash char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment found in {path}: {comments[0]}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    for run_dir in (LOW_DIR, HIGH_DIR):
        for name in ("meta.json", "results.json"):
            fp = run_dir / name
            text = fp.read_text(encoding="utf-8")
            assert EM_DASH not in text and EN_DASH not in text, f"dash found in {fp}"
        summary_fp = run_dir / "summary.md"
        summary_text = summary_fp.read_text(encoding="utf-8")
        assert EM_DASH not in summary_text and EN_DASH not in summary_text, f"dash found in {summary_fp}"
        for artifact in sorted(run_dir.rglob("*")):
            if artifact.is_file():
                assert scan_file_secrets(artifact, REPO_ROOT) == []
