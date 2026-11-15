from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tokenize

import pytest

from canary.env import Env
from canary.rules import JUDGE_SEEDS

REPO_ROOT = Path(__file__).resolve().parents[1]
MM_ROOT = REPO_ROOT / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"
LOW_DIR = MM_ROOT / "access-heatmap-v14-low-s8to11-carbon"
HIGH_DIR = MM_ROOT / "access-heatmap-v14-high-s8to11-carbon"

ACCESS_HEATMAP_RUNS = (
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-sweep-carbon",
    "access-heatmap-v14-low-s8to11-carbon",
    "access-heatmap-v14-high-s8to11-carbon",
)

EXPECTED_PAIRED_WORLDS = (
    ("medium", 8),
    ("medium", 9),
    ("hard", 8),
    ("hard", 9),
    ("hard", 10),
    ("hard", 11),
)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")
OAUTH_RE = re.compile(r"(?<![A-Za-z0-9_])ya29\.[0-9A-Za-z_\-]{12,}")


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_paired_low_and_high_compact_schema_and_provenance() -> None:
    for expected_level, run_dir in (("low", LOW_DIR), ("high", HIGH_DIR)):
        assert run_dir.is_dir(), run_dir
        files = sorted(p.name for p in run_dir.iterdir())
        assert files == ["meta.json", "results.json", "summary.md"], (run_dir, files)
        for p in run_dir.rglob("*"):
            if p.is_file():
                assert p.suffix.lower() != ".png", p

        meta = _load_json(run_dir / "meta.json")
        res = _load_json(run_dir / "results.json")
        summary_text = (run_dir / "summary.md").read_text(encoding="utf-8")

        assert meta["role"] == "multimodal_evidence"
        assert meta["subrole"] == "soc_access_vision_v14_sweep"
        assert meta["model_id"] == "gemini-4-carbon"
        assert meta["thinking_level"] == expected_level
        assert res["thinking_level"] == expected_level
        assert COMMIT_RE.fullmatch(meta["commit"]) is not None
        assert meta["commit"] == meta["git_sha"] == res["commit"]
        assert meta["tiers_version"] == "v1.4"
        assert meta["tier_seeds"] == {"medium": [8, 9], "hard": [8, 9, 10, 11]}
        assert meta["episode_count"] == 6
        assert meta["n_worlds"] == 6
        assert meta["n_images_read_by_model"] == 6
        assert meta["part_from_bytes"] is True
        assert meta["fake_env"] is False
        assert meta["smoke"] is False
        assert "results/gemini/roles_carbon/multimodal_evidence/" in meta["command"]
        assert "results/gemini_roles/" not in meta["command"]
        assert "results/gemini_roles/" not in summary_text
        assert f"--thinking-level {expected_level}" in meta["command"]

    low_meta = _load_json(LOW_DIR / "meta.json")
    high_meta = _load_json(HIGH_DIR / "meta.json")
    assert low_meta["commit"] == high_meta["commit"]
    normalized_cmd = (
        low_meta["command"]
        .replace("--thinking-level low", "--thinking-level high")
        .replace(
            "access-heatmap-v14-low-s8to11-carbon",
            "access-heatmap-v14-high-s8to11-carbon",
        )
    )
    assert normalized_cmd == high_meta["command"]


def test_paired_low_and_high_identical_png_sha256_manifests_and_inputs() -> None:
    low_meta = _load_json(LOW_DIR / "meta.json")
    high_meta = _load_json(HIGH_DIR / "meta.json")
    low_res = _load_json(LOW_DIR / "results.json")
    high_res = _load_json(HIGH_DIR / "results.json")

    low_manifest = low_meta["image_manifest"]
    high_manifest = high_meta["image_manifest"]
    assert low_manifest == high_manifest
    assert low_manifest["count"] == 6
    assert low_manifest["mime_type"] == "image/png"
    assert low_manifest["dimensions"] == [[1880, 1020], [2180, 1660]]
    assert low_manifest["total_bytes"] == 1463377

    manifest_images = low_manifest["images"]
    assert len(manifest_images) == 6
    assert sum(img["bytes"] for img in manifest_images) == 1463377
    for img in manifest_images:
        assert img["path"].startswith("rasters/") and img["path"].endswith(".png")
        assert img["size"] == [img["width"], img["height"]]
        assert img["size"] in ([1880, 1020], [2180, 1660])
        assert SHA256_RE.fullmatch(img["sha256"]) is not None

    assert low_meta["rasters"] == high_meta["rasters"]
    low_rasters = {(r["tier"], int(r["seed"])): r for r in low_meta["rasters"]}
    low_worlds = {(w["tier"], int(w["seed"])): w for w in low_res["worlds"]}
    high_worlds = {(w["tier"], int(w["seed"])): w for w in high_res["worlds"]}
    manifest_by_path = {img["path"]: img for img in manifest_images}

    assert tuple(low_rasters.keys()) == EXPECTED_PAIRED_WORLDS
    assert tuple(low_worlds.keys()) == EXPECTED_PAIRED_WORLDS
    assert tuple(high_worlds.keys()) == EXPECTED_PAIRED_WORLDS

    for tier, seed in EXPECTED_PAIRED_WORLDS:
        assert seed not in JUDGE_SEEDS
        raster = low_rasters[(tier, seed)]
        lw = low_worlds[(tier, seed)]
        hw = high_worlds[(tier, seed)]
        m_img = manifest_by_path[raster["path"]]

        expected_size = [1880, 1020] if tier == "medium" else [2180, 1660]
        expected_in_tokens = 2001 if tier == "medium" else 2151

        assert raster["size"] == expected_size
        assert m_img["size"] == expected_size
        assert lw["raster_size"] == expected_size
        assert hw["raster_size"] == expected_size

        assert raster["sha256"] == m_img["sha256"] == lw["raster_sha256"] == hw["raster_sha256"]
        assert raster["bytes"] == m_img["bytes"] == lw["raster_bytes"] == hw["raster_bytes"]
        assert lw["observable_summary"] == hw["observable_summary"]
        assert lw["ground_truth"] == hw["ground_truth"]
        assert lw["usage"]["in"] == hw["usage"]["in"] == expected_in_tokens


def test_paired_thinking_tokens_43x_and_brier_calibration_drop() -> None:
    low_meta = _load_json(LOW_DIR / "meta.json")
    high_meta = _load_json(HIGH_DIR / "meta.json")
    low_res = _load_json(LOW_DIR / "results.json")
    high_res = _load_json(HIGH_DIR / "results.json")

    assert low_meta["usage"]["calls"] == 6
    assert high_meta["usage"]["calls"] == 6
    assert low_meta["usage"]["in"] == 12606
    assert high_meta["usage"]["in"] == 12606

    assert low_meta["usage"]["thinking"] == 1983
    assert high_meta["usage"]["thinking"] == 85629
    thinking_ratio = high_meta["usage"]["thinking"] / low_meta["usage"]["thinking"]
    assert round(thinking_ratio, 1) == 43.2
    assert thinking_ratio == pytest.approx(85629 / 1983, rel=1e-9)

    for tier in ("medium", "hard"):
        assert high_res["by_tier"][tier]["usage"]["thinking"] > low_res["by_tier"][tier]["usage"]["thinking"]

    low_worlds = {(w["tier"], int(w["seed"])): w for w in low_res["worlds"]}
    high_worlds = {(w["tier"], int(w["seed"])): w for w in high_res["worlds"]}
    for pair in EXPECTED_PAIRED_WORLDS:
        assert high_worlds[pair]["usage"]["thinking"] > low_worlds[pair]["usage"]["thinking"]

    low_brier_recomputed = sum(
        (float(w["model_output"]["confidence"]) - (1.0 if w["evaluation"]["top1_mole_correct"] else 0.0)) ** 2
        for w in low_res["worlds"]
    ) / 6.0
    high_brier_recomputed = sum(
        (float(w["model_output"]["confidence"]) - (1.0 if w["evaluation"]["top1_mole_correct"] else 0.0)) ** 2
        for w in high_res["worlds"]
    ) / 6.0

    assert low_meta["brier_score"] == pytest.approx(0.002117, abs=1e-6)
    assert high_meta["brier_score"] == pytest.approx(0.000254, abs=1e-6)
    assert low_brier_recomputed == pytest.approx(low_meta["brier_score"], abs=1e-6)
    assert high_brier_recomputed == pytest.approx(high_meta["brier_score"], abs=1e-6)
    assert high_meta["brier_score"] < low_meta["brier_score"]
    assert low_meta["expected_calibration_error"] == pytest.approx(0.025333, abs=1e-6)
    assert high_meta["expected_calibration_error"] == pytest.approx(0.012667, abs=1e-6)
    assert high_meta["expected_calibration_error"] < low_meta["expected_calibration_error"]


def test_pooled_28_episode_soc_access_vision_accuracy_and_env_truth() -> None:
    expected_counts = {
        "access-heatmap-carbon": 3,
        "access-heatmap-hard-carbon": 3,
        "access-heatmap-v14-sweep-carbon": 10,
        "access-heatmap-v14-low-s8to11-carbon": 6,
        "access-heatmap-v14-high-s8to11-carbon": 6,
    }
    all_episodes: list[dict] = []
    unique_worlds: dict[tuple[str, int], dict[str, str]] = {}

    for run_name in ACCESS_HEATMAP_RUNS:
        run_dir = MM_ROOT / run_name
        meta = _load_json(run_dir / "meta.json")
        res = _load_json(run_dir / "results.json")
        worlds = res["worlds"]

        assert meta["role"] == "multimodal_evidence"
        assert meta["model_id"] == "gemini-4-carbon"
        assert meta["part_from_bytes"] is True
        assert meta["n_images_read_by_model"] == expected_counts[run_name]
        assert len(worlds) == expected_counts[run_name]

        for w in worlds:
            tier = str(w["tier"])
            seed = int(w["seed"])
            assert seed not in JUDGE_SEEDS
            env = Env(tier, seed)
            gt = w["ground_truth"]
            assert gt["true_mole"] == env._world.mole
            assert gt["true_decoy"] == env._world.decoy

            preds = w["model_output"]["top_suspect_ids"]
            decoys = w["model_output"]["suspected_decoy_ids"]
            ev = w["evaluation"]
            assert ev["top1_mole_correct"] is (bool(preds) and preds[0] == gt["true_mole"])
            assert ev["top3_mole_hit"] is (gt["true_mole"] in preds[:3])
            assert ev["top1_decoy_correct"] is (bool(decoys) and decoys[0] == gt["true_decoy"])
            assert ev["avoided_framing_trap"] is (not preds or preds[0] != gt["true_decoy"])

            naive_id = w["observable_summary"]["naive_most_after_hours_id"]
            assert ev["naive_baseline_mole_correct"] is (naive_id == gt["true_mole"])
            assert ev["naive_baseline_trapped_by_decoy"] is (naive_id == gt["true_decoy"])

            key = (tier, seed)
            if key in unique_worlds:
                assert unique_worlds[key] == gt
            else:
                unique_worlds[key] = gt
            all_episodes.append(w)

    assert len(all_episodes) == 28
    assert len(unique_worlds) == 22
    expected_unique = {("medium", s) for s in range(10)} | {("hard", s) for s in range(12)}
    assert set(unique_worlds.keys()) == expected_unique

    top1_mole_hits = sum(1 for w in all_episodes if w["evaluation"]["top1_mole_correct"])
    top3_mole_hits = sum(1 for w in all_episodes if w["evaluation"]["top3_mole_hit"])
    top1_decoy_hits = sum(1 for w in all_episodes if w["evaluation"]["top1_decoy_correct"])
    avoided_trap_hits = sum(1 for w in all_episodes if w["evaluation"]["avoided_framing_trap"])
    naive_mole_hits = sum(1 for w in all_episodes if w["evaluation"]["naive_baseline_mole_correct"])
    naive_trapped_hits = sum(1 for w in all_episodes if w["evaluation"]["naive_baseline_trapped_by_decoy"])

    assert top1_mole_hits == 27
    assert top3_mole_hits == 28
    assert top1_decoy_hits == 28
    assert avoided_trap_hits == 28
    assert naive_mole_hits == 0
    assert naive_trapped_hits == 28
    assert top1_mole_hits / len(all_episodes) == pytest.approx(27 / 28, abs=1e-9)


def test_zero_comments_zero_unicode_dashes_and_zero_secrets() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")
    assert HASH_CHAR not in src
    assert EM_DASH not in src
    assert EN_DASH not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    assert [t for t in tokens if t.type == tokenize.COMMENT] == []

    for p in [self_path, *sorted(LOW_DIR.rglob("*")), *sorted(HIGH_DIR.rglob("*"))]:
        if p.is_file():
            txt = p.read_text(encoding="utf-8")
            assert EM_DASH not in txt, p
            assert EN_DASH not in txt, p
            assert GOOGLE_KEY_RE.search(txt) is None, p
            assert SK_KEY_RE.search(txt) is None, p
            assert OAUTH_RE.search(txt) is None, p
