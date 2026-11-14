from __future__ import annotations

import io
import json
import tokenize
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from canary.gemini.access_vision import SOC_VISION_SCHEMA, raster_sha256
from canary.gemini.ledger import read_ledger
from canary.gemini.provenance import _inspect_run, scan_file_secrets
from canary.llm.base import MissingKeyError
import scripts.run_access_vision_sweep as sweep

REPO_ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


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


def _fake_response(payload: dict | str, *, tin: int = 2050, tout: int = 420, thoughts: int = 1350):
    text = payload if isinstance(payload, str) else json.dumps(payload)
    um = SimpleNamespace(
        prompt_token_count=tin,
        candidates_token_count=tout,
        thoughts_token_count=thoughts,
        cached_content_token_count=0,
    )
    return SimpleNamespace(text=text, usage_metadata=um, model_version="gemini-4-carbon")


def _synthetic_world(
    seed: int,
    tier: str,
    *,
    conf: float,
    mole_ok: bool,
    top3_ok: bool,
    decoy_ok: bool,
    avoid_trap: bool,
    naive_mole: bool,
    naive_trapped: bool,
) -> dict:
    return {
        "seed": seed,
        "tier": tier,
        "model_output": {"confidence": conf},
        "evaluation": {
            "top1_mole_correct": mole_ok,
            "top3_mole_hit": top3_ok,
            "top1_decoy_correct": decoy_ok,
            "decoy_identified": decoy_ok,
            "avoided_framing_trap": avoid_trap,
            "naive_baseline_mole_correct": naive_mole,
            "naive_baseline_trapped_by_decoy": naive_trapped,
        },
        "usage": {
            "in": 2000,
            "out": 400,
            "thinking": 1000,
            "cached": 0,
            "cost_usd": 0.025,
            "latency_s": 12.5,
        },
    }


def test_compute_subset_metrics_brier_calibration_and_deltas():
    empty = sweep.compute_subset_metrics([])
    assert empty["n_worlds"] == 0
    assert empty["brier_score"] == 0.0
    assert empty["mean_confidence_when_correct"] is None

    worlds = [
        _synthetic_world(
            3, "medium", conf=0.90, mole_ok=True, top3_ok=True, decoy_ok=True,
            avoid_trap=True, naive_mole=False, naive_trapped=True,
        ),
        _synthetic_world(
            4, "medium", conf=0.80, mole_ok=True, top3_ok=True, decoy_ok=True,
            avoid_trap=True, naive_mole=False, naive_trapped=True,
        ),
        _synthetic_world(
            5, "hard", conf=0.70, mole_ok=False, top3_ok=True, decoy_ok=True,
            avoid_trap=True, naive_mole=False, naive_trapped=True,
        ),
        _synthetic_world(
            6, "hard", conf=0.60, mole_ok=True, top3_ok=True, decoy_ok=False,
            avoid_trap=True, naive_mole=True, naive_trapped=False,
        ),
    ]
    m = sweep.compute_subset_metrics(worlds, n_bins=5)
    assert m["n_worlds"] == 4
    assert m["top1_mole_hits"] == 3
    assert m["top1_mole_accuracy"] == 0.75
    assert m["top3_mole_hit_rate"] == 1.0
    assert m["top1_decoy_accuracy"] == 0.75
    assert m["avoided_framing_trap_rate"] == 1.0
    assert m["naive_baseline_mole_accuracy"] == 0.25
    assert m["mole_accuracy_delta_vs_naive"] == 0.5
    assert m["avoided_trap_delta_vs_naive"] == 0.75
    assert m["head_to_head_wins_vs_naive"] == 2
    assert m["head_to_head_ties_vs_naive"] == 2
    assert m["head_to_head_losses_vs_naive"] == 0
    assert m["mean_confidence"] == 0.75
    assert m["mean_confidence_when_correct"] == pytest.approx((0.9 + 0.8 + 0.6) / 3, abs=1e-4)
    assert m["mean_confidence_when_wrong"] == pytest.approx(0.7, abs=1e-4)

    expected_brier = ((0.9 - 1.0) ** 2 + (0.8 - 1.0) ** 2 + (0.7 - 0.0) ** 2 + (0.6 - 1.0) ** 2) / 4.0
    assert m["brier_score"] == pytest.approx(expected_brier, abs=1e-6)
    assert m["signed_calibration_gap"] == pytest.approx(0.0, abs=1e-6)
    assert m["usage"]["calls"] == 4
    assert m["usage"]["in"] == 8000


def test_keyless_sweep_raises_without_mock_sdk(monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)
    with pytest.raises(MissingKeyError):
        sweep.main(
            ["--tiers", "medium", "--seeds", "3", "--max-retries", "0", "--out", str(tmp_path / "out")]
        )


def test_multi_tier_sweep_cli_writes_verified_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.delenv("GEMINI_GATEWAY_URL", raising=False)

    ledger_file = tmp_path / "sweep_ledger.jsonl"
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(ledger_file))
    out_dir = tmp_path / "results" / "gemini_roles" / "multimodal_evidence" / "access-heatmap-v14-sweep-carbon"

    fake_sdk = FakeSDKClient([
        _fake_response({
            "top_suspect_ids": ["E14", "e15"],
            "suspected_decoy_ids": ["e13"],
            "confidence": 0.94,
            "canary_leak_summary": "medium seed 3 canary match on e14",
            "visual_reasoning": f"e13 shows framing spike{EM_DASH}while e14 matches surfaced leak correlation.",
        }),
        _fake_response({
            "top_suspect_ids": ["e17"],
            "suspected_decoy_ids": ["e03"],
            "confidence": 0.98,
            "canary_leak_summary": "medium seed 4 4/4 canaries -> e17",
            "visual_reasoning": "e03 is framed decoy; e17 matches 4/4 surfaced canaries.",
        }),
        _fake_response({
            "top_suspect_ids": ["e29", "e18"],
            "suspected_decoy_ids": ["e12"],
            "confidence": 0.97,
            "canary_leak_summary": "hard seed 3 H6/6 -> e29",
            "visual_reasoning": "e12 has massive after-hours framing spike; e29 matches 6/6 canaries.",
        }),
        _fake_response({
            "top_suspect_ids": ["e05", "e11"],
            "suspected_decoy_ids": ["e31"],
            "confidence": 0.55,
            "canary_leak_summary": "hard seed 4 ambiguous candidate test",
            "visual_reasoning": "e31 is framed decoy; e11 is second candidate.",
        }),
    ])

    rc = sweep.main(
        [
            "--tiers", "medium,hard",
            "--medium-seeds", "3,4",
            "--hard-seeds", "3,4",
            "--out", str(out_dir),
        ],
        sdk_client=fake_sdk,
    )
    assert rc == 0
    assert len(fake_sdk.models.calls) == 4

    for idx, expected_tier in enumerate(("medium", "medium", "hard", "hard")):
        call = fake_sdk.models.calls[idx]
        assert call["model"] == "gemini-4-carbon"
        img_part, prompt_part = call["contents"]
        assert img_part.inline_data.mime_type == "image/png"
        assert img_part.inline_data.data[:8] == b"\x89PNG\r\n\x1a\n"
        assert call["config"].response_mime_type == "application/json"
        assert call["config"].response_json_schema == SOC_VISION_SCHEMA
        with Image.open(io.BytesIO(img_part.inline_data.data)) as im:
            expected_size = (1880, 1020) if expected_tier == "medium" else (2180, 1660)
            assert im.size == expected_size
        if expected_tier == "hard":
            assert "hard-tier" in prompt_part
        else:
            assert "medium-tier" in prompt_part

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "soc_access_vision_v14_sweep"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["commit"]
    assert meta["episode_count"] == 4
    assert meta["n_images_read_by_model"] == 4
    assert meta["tiers"] == ["medium", "hard"]
    assert meta["tier_seeds"] == {"medium": [3, 4], "hard": [3, 4]}
    assert meta["top1_mole_accuracy"] == 0.75
    assert meta["top3_mole_hit_rate"] == 1.0
    assert meta["naive_baseline_mole_accuracy"] == 0.0
    assert meta["mole_accuracy_delta_vs_naive"] == 0.75
    assert meta["top1_decoy_accuracy"] == 1.0
    assert meta["avoided_framing_trap_rate"] == 1.0
    assert meta["usage"]["calls"] == 4

    assert results["by_tier"]["medium"]["top1_mole_accuracy"] == 1.0
    assert results["by_tier"]["hard"]["top1_mole_accuracy"] == 0.5
    assert results["by_tier"]["hard"]["top3_mole_hit_rate"] == 1.0
    assert results["metrics"]["brier_score"] > 0.0
    assert len(results["calibration_bins"]) == 5

    for item in meta["rasters"]:
        png_path = out_dir / item["path"]
        assert png_path.is_file()
        assert raster_sha256(png_path.read_bytes()) == item["sha256"]

    assert EM_DASH not in summary_md and EN_DASH not in summary_md
    assert EM_DASH not in (out_dir / "results.json").read_text(encoding="utf-8")

    prov = _inspect_run(out_dir / "meta.json", tmp_path, tmp_path / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True
    assert prov["errors"] == []
    assert prov["count"] == 4

    rows = read_ledger([ledger_file])
    assert len(rows) == 4
    assert all(r["feature"] == "multimodal_evidence" and r["ok"] is True for r in rows)


def test_committed_v14_sweep_artifacts_if_present():
    committed_dir = REPO_ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "access-heatmap-v14-sweep-carbon"
    meta_path = committed_dir / "meta.json"
    if not meta_path.is_file():
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    results = json.loads((committed_dir / "results.json").read_text(encoding="utf-8"))
    summary_md = (committed_dir / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "soc_access_vision_v14_sweep"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["episode_count"] == 10
    assert meta["n_images_read_by_model"] == 10
    assert meta["tier_seeds"] == {"medium": [3, 4, 5, 6, 7], "hard": [3, 4, 5, 6, 7]}
    assert len(meta["rasters"]) == 10
    assert len(results["worlds"]) == 10

    for item in meta["rasters"]:
        png_path = committed_dir / item["path"]
        assert png_path.is_file()
        assert raster_sha256(png_path.read_bytes()) == item["sha256"]

    for text in (meta_path.read_text(encoding="utf-8"), (committed_dir / "results.json").read_text(encoding="utf-8"), summary_md):
        assert EM_DASH not in text and EN_DASH not in text

    prov = _inspect_run(meta_path, REPO_ROOT, REPO_ROOT / "data" / "runs" / "committed" / "v1.4")
    assert prov["verified"] is True
    assert prov["errors"] == []
    assert prov["secret_leaks"] == []


def test_sweep_python_files_have_zero_comments_zero_hashes_zero_em_dashes_and_zero_secrets():
    targets = [
        REPO_ROOT / "scripts" / "run_access_vision_sweep.py",
        REPO_ROOT / "tests" / "test_access_vision_sweep.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert EM_DASH not in text and EN_DASH not in text, f"dash found in {path}"
        assert HASH_CHAR not in text, f"hash char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment found in {path}: {comments[0]}"
        assert scan_file_secrets(path, REPO_ROOT) == []
