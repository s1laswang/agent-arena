from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tokenize

import pytest

from canary.rules import TIERS, TIERS_VERSION
from canary.world import generate_world

REPO_ROOT = Path(__file__).resolve().parents[1]
MM_ROOT = REPO_ROOT / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"

RUN_MED6TO8 = "multi-image-dossier-med6to8-hard5to7-carbon"
DOSSIER_RUNS = (
    "multi-image-dossier-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "multi-image-dossier-med6to8-hard5to7-carbon",
)

TARGET_MODEL = "gemini-4-carbon"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GOOGLE_KEY_RE = re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{8,60}(?![A-Za-z0-9_\-=])")
SK_KEY_RE = re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}")


@pytest.fixture(autouse=True)
def _keyless_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_API_KEY", "")


def test_med6to8_hard5to7_dossier_run_schema_and_provenance() -> None:
    run_dir = MM_ROOT / RUN_MED6TO8
    assert run_dir.is_dir()

    for p in run_dir.rglob("*"):
        if p.is_dir():
            assert p.name != "dossiers"
            continue
        assert p.suffix.lower() != ".png"
        text = p.read_text(encoding="utf-8")
        assert EM_DASH not in text
        assert EN_DASH not in text
        assert "results/gemini_roles/" not in text
        assert not GOOGLE_KEY_RE.search(text)
        assert not SK_KEY_RE.search(text)

    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    summary_text = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert len(summary_text) > 500
    assert "results/gemini/roles_carbon/multimodal_evidence/multi-image-dossier-med6to8-hard5to7-carbon" in summary_text

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "multi_image_incident_dossier"
    assert meta["model_id"] == TARGET_MODEL
    assert COMMIT_RE.fullmatch(meta["commit"]) is not None
    assert meta["tiers_version"] == "v1.4"
    assert meta["episode_count"] == 6
    assert meta["n_images_read_by_model"] == 18
    assert meta["images_per_call"] == 3
    assert meta["part_from_bytes"] is True
    assert meta["fake_env"] is False
    assert meta["smoke"] is False

    expected_tags = ["medium_6", "medium_7", "medium_8", "hard_5", "hard_6", "hard_7"]
    assert [w["seed_tag"] for w in meta["worlds"]] == expected_tags
    assert [w["seed_tag"] for w in results["worlds"]] == expected_tags

    manifest = meta["image_manifest"]
    assert manifest["count"] == 18
    assert manifest["mime_type"] == "image/png"
    assert manifest["total_bytes"] == 2411361
    assert len(manifest["images"]) == 18

    manifest_by_path = {}
    for img in manifest["images"]:
        w = img["width"]
        h = img["height"]
        assert isinstance(w, int) and w > 0
        assert isinstance(h, int) and h > 0
        assert img["size"] == [w, h]
        assert isinstance(img["bytes"], int) and img["bytes"] > 0
        assert SHA256_RE.fullmatch(img["sha256"]) is not None
        manifest_by_path[img["path"]] = img

    assert len(manifest_by_path) == 18
    assert sum(x["bytes"] for x in manifest_by_path.values()) == 2411361
    assert len({x["sha256"] for x in manifest_by_path.values()}) == 18

    for d in meta["dossiers"]:
        assert d["n_images"] == 3
        for d_img in d["images"]:
            m_img = manifest_by_path[d_img["path"]]
            assert d_img["sha256"] == m_img["sha256"]
            assert d_img["bytes"] == m_img["bytes"]
            assert d_img["size"] == m_img["size"]

    usage = meta["usage"]
    assert usage == results["usage"]
    assert usage["calls"] == 6
    assert usage["in"] == 27055
    assert usage["out"] == 2345
    assert usage["thinking"] == 25336
    assert usage["cost_usd"] == pytest.approx(0.33092, abs=1e-6)

    metrics = results["metrics"]
    assert metrics["top1_mole_hits"] == 4
    assert metrics["top3_mole_hits"] == 5
    assert metrics["top1_decoy_hits"] == 5
    assert metrics["decoy_identified_hits"] == 6
    assert metrics["avoided_framing_trap_hits"] == 6
    assert metrics["memo_scans_matched_total"] == 12
    assert metrics["memo_scans_expected_total"] == 12
    assert metrics["memo_scan_readout_accuracy"] == pytest.approx(1.0, abs=1e-9)
    assert metrics["suspect_dept_hits"] == 4
    assert metrics["image1_only_mole_hits"] == 0
    assert metrics["image2_only_mole_accuracy"] == 0.0
    assert metrics["image3_only_deterministic_hits"] == 0


def test_pooled_17_world_51_png_composite_dossier_totals_and_world_replay() -> None:
    assert TIERS_VERSION == "v1.4"

    pooled_worlds: dict[tuple[str, int], dict[str, object]] = {}
    all_hashes: set[str] = set()
    total_images = 0
    total_bytes = 0
    total_calls = 0
    total_in = 0
    total_out = 0
    total_thinking = 0
    total_cost = 0.0

    for run_name in DOSSIER_RUNS:
        run_dir = MM_ROOT / run_name
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))

        assert meta["role"] == "multimodal_evidence"
        assert meta["subrole"] == "multi_image_incident_dossier"
        assert meta["model_id"] == TARGET_MODEL
        assert meta["part_from_bytes"] is True
        assert meta["images_per_call"] == 3
        assert meta["n_images_read_by_model"] == meta["episode_count"] * 3

        manifest = meta["image_manifest"]
        assert manifest["count"] == meta["n_images_read_by_model"]
        total_images += int(meta["n_images_read_by_model"])
        total_bytes += int(manifest["total_bytes"])
        for img in manifest["images"]:
            all_hashes.add(str(img["sha256"]))

        usage = meta["usage"]
        total_calls += int(usage["calls"])
        total_in += int(usage["in"])
        total_out += int(usage["out"])
        total_thinking += int(usage["thinking"])
        total_cost += float(usage["cost_usd"])

        for w in results["worlds"]:
            tier = str(w["tier"])
            seed = int(w["seed"])
            key = (tier, seed)
            assert key not in pooled_worlds
            pooled_worlds[key] = w

            world = generate_world(tier, seed, TIERS[tier])
            emp_by_id = {e.id: e for e in world.employees}
            gt = w["ground_truth"]
            assert gt["true_mole"] == world.mole
            assert gt["true_decoy"] == world.decoy
            assert gt["true_mole_dept"] == emp_by_id[world.mole].dept
            assert gt["true_decoy_dept"] == emp_by_id[str(world.decoy)].dept

            out = w["model_output"]
            ev = w["evaluation"]
            top_suspects = list(out["top_suspect_ids"])
            decoy_preds = list(out["suspected_decoy_ids"])
            assert ev["top1_mole_correct"] is (bool(top_suspects) and top_suspects[0] == world.mole)
            assert ev["top3_mole_hit"] is (world.mole in top_suspects[:3])
            assert ev["top1_decoy_correct"] is (bool(decoy_preds) and decoy_preds[0] == world.decoy)
            assert ev["decoy_identified"] is (world.decoy in decoy_preds)
            assert ev["avoided_framing_trap"] is (not top_suspects or top_suspects[0] != world.decoy)
            assert ev["suspect_dept_correct"] is (out["suspect_department"] == emp_by_id[world.mole].dept)

            expected_scans = {(s["doc_id"], s["variant"]) for s in w["observable_summary"]["leaked_canary_scans"]}
            decoded_scans = {(s["doc_id"], s["variant"]) for s in out["decoded_leaked_canaries"]}
            assert ev["memo_scans_total"] == len(expected_scans)
            assert ev["memo_scans_matched"] == len(expected_scans & decoded_scans)

    expected_keys = {("medium", s) for s in range(9)} | {("hard", s) for s in range(8)}
    assert set(pooled_worlds.keys()) == expected_keys
    assert len(pooled_worlds) == 17
    assert total_images == 51
    assert len(all_hashes) == 51
    assert total_bytes == 6903017

    assert total_calls == 17
    assert total_in == 76652
    assert total_out == 6876
    assert total_thinking == 66726
    assert total_cost == pytest.approx(0.889324, abs=1e-6)

    ws = list(pooled_worlds.values())
    assert sum(1 for w in ws if w["evaluation"]["top1_mole_correct"]) == 14
    assert sum(1 for w in ws if w["evaluation"]["top3_mole_hit"]) == 16
    assert sum(1 for w in ws if w["evaluation"]["top1_decoy_correct"]) == 16
    assert sum(1 for w in ws if w["evaluation"]["decoy_identified"]) == 17
    assert sum(1 for w in ws if w["evaluation"]["avoided_framing_trap"]) == 17
    assert sum(int(w["evaluation"]["memo_scans_matched"]) for w in ws) == 43
    assert sum(int(w["evaluation"]["memo_scans_total"]) for w in ws) == 43
    assert sum(1 for w in ws if w["evaluation"]["suspect_dept_correct"]) == 15
    assert sum(1 for w in ws if w["single_image_baselines"]["image1_only_mole_correct"]) == 0
    assert sum(1 for w in ws if w["single_image_baselines"]["image1_only_trapped_by_decoy"]) == 16
    assert sum(1 for w in ws if w["single_image_baselines"]["image2_only_mole_correct"]) == 0
    assert sum(1 for w in ws if w["single_image_baselines"]["image3_only_mole_correct"]) == 0


def test_dossier_med6to8_test_file_has_zero_comments_or_dashes() -> None:
    src = Path(__file__).resolve().read_text(encoding="utf-8")
    assert EM_DASH not in src
    assert EN_DASH not in src
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []
    assert not GOOGLE_KEY_RE.search(src)
    assert not SK_KEY_RE.search(src)
