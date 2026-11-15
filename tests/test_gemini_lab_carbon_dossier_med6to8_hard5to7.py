from __future__ import annotations

import io
import json
import re
import struct
import tokenize
from pathlib import Path

import pytest

from canary.rules import TIERS_VERSION

REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_DIR = (
    REPO_ROOT
    / "results"
    / "gemini_roles"
    / "multimodal_evidence"
    / "multi-image-dossier-med6to8-hard5to7-carbon"
)
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SECRET_RE = re.compile(r"AIza[0-9A-Za-z_-]{20,}")
EXPECTED_WORLDS = [
    ("medium", 6, "medium_6"),
    ("medium", 7, "medium_7"),
    ("medium", 8, "medium_8"),
    ("hard", 5, "hard_5"),
    ("hard", 6, "hard_6"),
    ("hard", 7, "hard_7"),
]


def test_dossier_med6to8_hard5to7_provenance_and_usage() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((RUN_DIR / "results.json").read_text(encoding="utf-8"))
    summary = (RUN_DIR / "summary.md").read_text(encoding="utf-8")

    assert meta["role"] == results["role"] == "multimodal_evidence"
    assert meta["subrole"] == results["subrole"] == "multi_image_incident_dossier"
    assert meta["model_id"] == results["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == results["tiers_version"] == TIERS_VERSION == "v1.4"
    assert meta["episode_count"] == results["episode_count"] == 6
    assert meta["n_images_read_by_model"] == results["n_images_read_by_model"] == 18
    assert meta["images_per_call"] == results["images_per_call"] == 3
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert COMMIT_RE.fullmatch(meta["commit"])
    assert meta["git_sha"] == meta["commit"] == results["commit"]
    assert "--worlds medium:6,medium:7,medium:8,hard:5,hard:6,hard:7" in meta["command"]
    assert "multi-image-dossier-med6to8-hard5to7-carbon" in meta["command"]

    assert [(w["tier"], w["seed"], w["seed_tag"]) for w in meta["worlds"]] == EXPECTED_WORLDS
    assert [(d["tier"], d["seed"], d["seed_tag"]) for d in meta["dossiers"]] == EXPECTED_WORLDS
    assert [(w["tier"], w["seed"], w["seed_tag"]) for w in results["worlds"]] == EXPECTED_WORLDS

    prior_worlds = {
        ("medium", 0),
        ("medium", 1),
        ("medium", 2),
        ("medium", 3),
        ("medium", 4),
        ("medium", 5),
        ("hard", 0),
        ("hard", 1),
        ("hard", 2),
        ("hard", 3),
        ("hard", 4),
    }
    assert prior_worlds.isdisjoint({(w["tier"], w["seed"]) for w in results["worlds"]})

    u = meta["usage"]
    assert u == results["usage"]
    assert u["calls"] == 6
    assert u["in"] == sum(w["usage"]["in"] for w in results["worlds"]) > 0
    assert u["out"] == sum(w["usage"]["out"] for w in results["worlds"]) > 0
    assert u["thinking"] == sum(w["usage"]["thinking"] for w in results["worlds"]) > 0
    assert u["cached"] == sum(w["usage"]["cached"] for w in results["worlds"]) >= 0
    assert u["cost_usd"] == pytest.approx(
        sum(w["usage"]["cost_usd"] for w in results["worlds"]), abs=1e-5
    )
    assert u["cost_usd"] > 0.0
    assert u["latency_s"] == pytest.approx(
        sum(w["usage"]["latency_s"] for w in results["worlds"]), abs=1e-2
    )
    assert u["latency_s"] > 0.0

    for w in results["worlds"]:
        wu = w["usage"]
        assert wu["in"] > 0
        assert wu["out"] > 0
        assert wu["thinking"] > 0
        assert wu["cost_usd"] > 0.0
        assert wu["latency_s"] > 0.0
        assert w["model_version"] == "gemini-4-carbon"

    assert (
        "- Tiers version: `v1.4` (`6` composite dossiers across `medium` seeds `6,7,8` and `hard` seeds `5,6,7`)"
        in summary
    )
    assert "- Model: `gemini-4-carbon`" in summary
    assert "- Composite dossiers evaluated (`episode_count`): `6`" in summary
    assert f"calls={u['calls']}" in summary
    assert f"in={u['in']}" in summary
    assert f"out={u['out']}" in summary
    assert f"thinking={u['thinking']}" in summary
    assert f"cost_usd={u['cost_usd']:.6f}" in summary


def test_dossier_med6to8_hard5to7_png_headers_dimensions_and_sizes() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((RUN_DIR / "results.json").read_text(encoding="utf-8"))
    summary = (RUN_DIR / "summary.md").read_text(encoding="utf-8")

    expected_rel_paths = {img["path"] for d in meta["dossiers"] for img in d["images"]}
    actual_rel_paths = {
        p.relative_to(RUN_DIR).as_posix() for p in (RUN_DIR / "dossiers").glob("*.png")
    }
    assert len(expected_rel_paths) == 18
    assert actual_rel_paths == expected_rel_paths

    for d_entry, w_row in zip(meta["dossiers"], results["worlds"]):
        tier = d_entry["tier"]
        seed_tag = d_entry["seed_tag"]
        assert d_entry["n_images"] == 3
        assert w_row["n_images_read"] == 3

        by_kind = {img["kind"]: img for img in d_entry["images"]}
        assert set(by_kind) == {"badge_raster", "leaked_memo_scans", "org_canary_map"}

        for kind in ("badge_raster", "leaked_memo_scans", "org_canary_map"):
            img_meta = by_kind[kind]
            assert img_meta == w_row["images"][kind]
            assert img_meta["path"] == f"dossiers/{kind}_seed_{seed_tag}.png"
            assert SHA256_RE.fullmatch(img_meta["sha256"])
            assert img_meta["bytes"] > 0
            assert img_meta["path"] in summary

            png_path = RUN_DIR / img_meta["path"]
            assert png_path.is_file()
            raw = png_path.read_bytes()
            assert len(raw) > 0
            assert len(raw) == img_meta["bytes"]
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            assert raw[12:16] == b"IHDR"

            w_px, h_px = struct.unpack(">II", raw[16:24])
            assert [w_px, h_px] == img_meta["size"]
            assert w_px >= 1200 and h_px >= 600
            if kind == "badge_raster":
                assert [w_px, h_px] == ([1274, 996] if tier == "medium" else [1530, 1636])
            elif kind == "leaked_memo_scans":
                assert w_px == 1510
            elif kind == "org_canary_map":
                assert w_px == (1320 if tier == "medium" else 2144)


def test_dossier_med6to8_hard5to7_metric_and_baseline_consistency() -> None:
    meta = json.loads((RUN_DIR / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((RUN_DIR / "results.json").read_text(encoding="utf-8"))
    summary = (RUN_DIR / "summary.md").read_text(encoding="utf-8")

    worlds = results["worlds"]
    n = len(worlds)
    assert n == 6

    for w in worlds:
        gt = w["ground_truth"]
        mo = w["model_output"]
        ev = w["evaluation"]
        sb = w["single_image_baselines"]
        obs = w["observable_summary"]

        assert obs["n_employees"] == (20 if w["tier"] == "medium" else 40)
        assert 0.0 <= float(mo["confidence"]) <= 1.0
        assert bool(mo["cross_image_reasoning"].strip())

        assert ev["top1_mole_correct"] is (
            bool(mo["top_suspect_ids"]) and mo["top_suspect_ids"][0] == gt["true_mole"]
        )
        assert ev["top3_mole_hit"] is (gt["true_mole"] in mo["top_suspect_ids"][:3])
        assert ev["top1_decoy_correct"] is (
            bool(mo["suspected_decoy_ids"]) and mo["suspected_decoy_ids"][0] == gt["true_decoy"]
        )
        assert ev["decoy_identified"] is (gt["true_decoy"] in mo["suspected_decoy_ids"][:2])
        assert ev["avoided_framing_trap"] is (
            bool(mo["top_suspect_ids"]) and mo["top_suspect_ids"][0] != gt["true_decoy"]
        )
        assert ev["suspect_dept_correct"] is (
            ev["top1_mole_correct"] and mo["suspect_department"] == gt["true_mole_dept"]
        )

        expected_pairs = {(sc["doc_id"], sc["variant"]) for sc in obs["leaked_canary_scans"]}
        decoded_pairs = {(sc["doc_id"], sc["variant"]) for sc in mo["decoded_leaked_canaries"]}
        assert ev["memo_scans_total"] == len(expected_pairs)
        assert ev["memo_scans_matched"] == len(expected_pairs & decoded_pairs)
        assert ev["memo_scans_exact_match"] is (decoded_pairs == expected_pairs)

        assert sb["image1_only_mole_correct"] is (
            sb["image1_only_naive_after_hours_pick"] == gt["true_mole"]
        )
        assert sb["image1_only_trapped_by_decoy"] is (
            sb["image1_only_naive_after_hours_pick"] == gt["true_decoy"]
        )
        assert sb["image2_only_pick"] is None
        assert sb["image2_only_mole_correct"] is False
        assert sb["image2_only_decoy_correct"] is False
        assert sb["image3_only_mole_correct"] is (sb["image3_only_prior_pick"] == gt["true_mole"])
        assert sb["image3_only_uniform_prior"] == pytest.approx(1.0 / obs["n_employees"], abs=1e-6)

    m = results["metrics"]
    top1_mole_hits = sum(1 for w in worlds if w["evaluation"]["top1_mole_correct"])
    top3_mole_hits = sum(1 for w in worlds if w["evaluation"]["top3_mole_hit"])
    top1_decoy_hits = sum(1 for w in worlds if w["evaluation"]["top1_decoy_correct"])
    decoy_id_hits = sum(1 for w in worlds if w["evaluation"]["decoy_identified"])
    avoid_trap_hits = sum(1 for w in worlds if w["evaluation"]["avoided_framing_trap"])
    dept_hits = sum(1 for w in worlds if w["evaluation"]["suspect_dept_correct"])
    scans_matched = sum(int(w["evaluation"]["memo_scans_matched"]) for w in worlds)
    scans_total = sum(int(w["evaluation"]["memo_scans_total"]) for w in worlds)
    img1_mole_hits = sum(1 for w in worlds if w["single_image_baselines"]["image1_only_mole_correct"])
    img1_traps = sum(1 for w in worlds if w["single_image_baselines"]["image1_only_trapped_by_decoy"])
    img3_hits = sum(1 for w in worlds if w["single_image_baselines"]["image3_only_mole_correct"])
    img3_prior = sum(float(w["single_image_baselines"]["image3_only_uniform_prior"]) for w in worlds) / n

    assert m["top1_mole_hits"] == top1_mole_hits == 4
    assert m["top1_mole_accuracy"] == meta["top1_mole_accuracy"] == round(top1_mole_hits / n, 4)
    assert m["top3_mole_hits"] == top3_mole_hits == 5
    assert m["top3_mole_hit_rate"] == round(top3_mole_hits / n, 4)
    assert m["top1_decoy_hits"] == top1_decoy_hits == 5
    assert m["top1_decoy_accuracy"] == meta["top1_decoy_accuracy"] == round(top1_decoy_hits / n, 4)
    assert m["decoy_identified_hits"] == decoy_id_hits == 6
    assert m["decoy_identified_rate"] == round(decoy_id_hits / n, 4) == 1.0
    assert m["avoided_framing_trap_hits"] == avoid_trap_hits == 6
    assert m["avoided_framing_trap_rate"] == round(avoid_trap_hits / n, 4) == 1.0
    assert m["memo_scans_matched_total"] == scans_matched == 12
    assert m["memo_scans_expected_total"] == scans_total == 12
    assert m["memo_scan_readout_accuracy"] == round(scans_matched / max(1, scans_total), 4) == 1.0
    assert m["suspect_dept_hits"] == dept_hits == 4
    assert m["suspect_dept_accuracy"] == round(dept_hits / n, 4)

    assert m["image1_only_mole_hits"] == img1_mole_hits == 0
    assert m["image1_only_mole_accuracy"] == round(img1_mole_hits / n, 4) == 0.0
    assert m["image1_only_decoy_traps"] == img1_traps == 5
    assert m["image1_only_decoy_trap_rate"] == round(img1_traps / n, 4)
    assert m["image2_only_mole_accuracy"] == 0.0
    assert m["image2_only_decoy_accuracy"] == 0.0
    assert m["image3_only_deterministic_hits"] == img3_hits == 0
    assert m["image3_only_deterministic_mole_accuracy"] == round(img3_hits / n, 4) == 0.0
    assert m["image3_only_uniform_prior_mean"] == round(img3_prior, 4) == pytest.approx(0.0375, abs=1e-4)

    assert m["top1_mole_accuracy"] > m["image1_only_mole_accuracy"]
    assert m["top1_mole_accuracy"] > m["image2_only_mole_accuracy"]
    assert m["top1_mole_accuracy"] > m["image3_only_deterministic_mole_accuracy"]
    assert m["top1_mole_accuracy"] > m["image3_only_uniform_prior_mean"]
    assert m["top1_decoy_accuracy"] > m["image2_only_decoy_accuracy"]
    assert m["avoided_framing_trap_rate"] > (1.0 - m["image1_only_decoy_trap_rate"])

    assert f"**{top1_mole_hits}/{n} ({m['top1_mole_accuracy']:.1%})**" in summary
    assert f"**{top1_decoy_hits}/{n} ({m['top1_decoy_accuracy']:.1%})**" in summary
    assert f"**{avoid_trap_hits}/{n} ({m['avoided_framing_trap_rate']:.1%})**" in summary


def test_dossier_med6to8_hard5to7_zero_em_dashes_comments_or_secrets() -> None:
    test_file = Path(__file__).resolve()
    py_text = test_file.read_text(encoding="utf-8")
    assert "\u2014" not in py_text and "\u2013" not in py_text
    assert SECRET_RE.search(py_text) is None
    tokens = list(tokenize.generate_tokens(io.StringIO(py_text).readline))
    comments = [t for t in tokens if t.type == tokenize.COMMENT]
    assert not comments

    for artifact in sorted(p for p in RUN_DIR.rglob("*") if p.is_file()):
        if artifact.suffix in {".json", ".jsonl", ".md"}:
            txt = artifact.read_text(encoding="utf-8")
            assert "\u2014" not in txt and "\u2013" not in txt, f"dash in {artifact}"
            assert SECRET_RE.search(txt) is None, f"secret in {artifact}"
