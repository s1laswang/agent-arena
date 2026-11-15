from __future__ import annotations

import copy
import io
import json
import re
import tokenize
from pathlib import Path

import pytest
from PIL import Image

from canary.env import Env
from canary.gemini.incident_dossier import (
    build_badge_view,
    build_memo_scans_view,
    build_org_map_view,
    collect_dossier_observations,
    dossier_filenames,
    png_sha256,
    render_incident_dossier_pngs,
)
from canary.gemini.provenance import COMMIT_RE, _inspect_run, scan_file_secrets
import scripts.run_incident_dossier as runner

REPO_ROOT = Path(__file__).resolve().parents[1]
ORIG_DIR = REPO_ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "multi-image-dossier-carbon"
EXPANDED_DIR = (
    REPO_ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "multi-image-dossier-v14-expanded-carbon"
)


def test_dynamic_summary_formatting_preserves_original_and_formats_expanded() -> None:
    orig_meta = json.loads((ORIG_DIR / "meta.json").read_text(encoding="utf-8"))
    orig_results = json.loads((ORIG_DIR / "results.json").read_text(encoding="utf-8"))
    orig_summary = (ORIG_DIR / "summary.md").read_text(encoding="utf-8")
    assert runner._build_summary_md(orig_meta, orig_results) == orig_summary

    exp_meta = json.loads((EXPANDED_DIR / "meta.json").read_text(encoding="utf-8"))
    exp_results = json.loads((EXPANDED_DIR / "results.json").read_text(encoding="utf-8"))
    exp_summary = (EXPANDED_DIR / "summary.md").read_text(encoding="utf-8")
    assert runner._build_summary_md(exp_meta, exp_results) == exp_summary
    assert (
        "- Tiers version: `v1.4` (`6` composite dossiers across `medium` seeds `3,4,5` and `hard` seeds `2,3,4`)"
        in exp_summary
    )
    assert "`medium` seeds `0,1,2` and `hard` seeds `0,1`" not in exp_summary
    assert "\u2014" not in exp_summary and "\u2013" not in exp_summary

    assert runner._format_worlds_provenance([]) == "no worlds"
    assert runner._format_worlds_provenance([{"tier": "medium", "seed": 7}]) == "`medium` seed `7`"
    assert (
        runner._format_worlds_provenance([
            {"tier": "easy", "seed": 0},
            {"tier": "medium", "seed": 3},
            {"tier": "medium", "seed": 4},
            {"tier": "hard", "seed": 2},
        ])
        == "`easy` seed `0`, `medium` seeds `3,4`, and `hard` seed `2`"
    )

    single_meta = copy.deepcopy(exp_meta)
    single_results = copy.deepcopy(exp_results)
    single_meta["episode_count"] = 1
    single_results["episode_count"] = 1
    single_results["worlds"] = [single_results["worlds"][0]]
    rendered_single = runner._build_summary_md(single_meta, single_results)
    assert "- Tiers version: `v1.4` (`1` composite dossier across `medium` seed `3`)" in rendered_single


def test_expanded_eighteen_png_digests_dimensions_and_rerender_determinism() -> None:
    meta = json.loads((EXPANDED_DIR / "meta.json").read_text(encoding="utf-8"))
    results = json.loads((EXPANDED_DIR / "results.json").read_text(encoding="utf-8"))

    assert meta["episode_count"] == 6
    assert meta["n_images_read_by_model"] == 18
    assert meta["images_per_call"] == 3
    assert len(meta["dossiers"]) == 6
    assert len(results["worlds"]) == 6

    expected_specs = [
        ("medium", 3, "medium_3"),
        ("medium", 4, "medium_4"),
        ("medium", 5, "medium_5"),
        ("hard", 2, "hard_2"),
        ("hard", 3, "hard_3"),
        ("hard", 4, "hard_4"),
    ]
    assert [(d["tier"], d["seed"], d["seed_tag"]) for d in meta["dossiers"]] == expected_specs
    assert [(w["tier"], w["seed"], w["seed_tag"]) for w in results["worlds"]] == expected_specs

    expected_rel_paths = {img["path"] for d in meta["dossiers"] for img in d["images"]}
    actual_rel_paths = {p.relative_to(EXPANDED_DIR).as_posix() for p in (EXPANDED_DIR / "dossiers").glob("*.png")}
    assert len(expected_rel_paths) == 18
    assert actual_rel_paths == expected_rel_paths

    seen_shas: set[str] = set()
    for d_entry, w_row in zip(meta["dossiers"], results["worlds"]):
        tier = d_entry["tier"]
        seed = d_entry["seed"]
        seed_tag = d_entry["seed_tag"]
        assert d_entry["n_images"] == 3
        assert w_row["n_images_read"] == 3

        obs = collect_dossier_observations(Env(tier, seed), seed_label=seed, tier=tier, seed_tag=seed_tag)
        rerendered = render_incident_dossier_pngs(obs)
        fnames = dossier_filenames(seed_tag)

        badge_json = json.dumps(build_badge_view(obs))
        memos_json = json.dumps(build_memo_scans_view(obs))
        org_json = json.dumps(build_org_map_view(obs))
        assert "variant" not in badge_json
        assert re.search(r"\be\d{2}\b", memos_json) is None
        assert "day_surfaced" not in org_json and "after_hours" not in org_json

        by_kind = {img["kind"]: img for img in d_entry["images"]}
        assert set(by_kind) == {"badge_raster", "leaked_memo_scans", "org_canary_map"}

        for kind in ("badge_raster", "leaked_memo_scans", "org_canary_map"):
            img_meta = by_kind[kind]
            world_img = w_row["images"][kind]
            assert img_meta == world_img
            assert img_meta["path"] == f"dossiers/{fnames[kind]}"

            png_path = EXPANDED_DIR / img_meta["path"]
            assert png_path.is_file()
            raw = png_path.read_bytes()
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            assert len(raw) == img_meta["bytes"]

            digest = png_sha256(raw)
            assert len(digest) == 64
            assert digest == img_meta["sha256"]
            assert digest == png_sha256(rerendered[kind])
            seen_shas.add(digest)

            with Image.open(io.BytesIO(raw)) as im:
                assert im.format == "PNG"
                assert list(im.size) == img_meta["size"]
                w_px, h_px = im.size
                assert w_px >= 1200 and h_px >= 600
                if kind == "badge_raster":
                    assert [w_px, h_px] == ([1274, 996] if tier == "medium" else [1530, 1636])
                elif kind == "org_canary_map":
                    assert w_px == (1320 if tier == "medium" else 2144)

    assert len(seen_shas) == 18


def test_expanded_single_image_vs_three_image_baselines_and_provenance() -> None:
    meta_path = EXPANDED_DIR / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    results = json.loads((EXPANDED_DIR / "results.json").read_text(encoding="utf-8"))

    assert meta["role"] == "multimodal_evidence"
    assert meta["subrole"] == "multi_image_incident_dossier"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["tiers_version"] == "v1.4"
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert COMMIT_RE.fullmatch(meta["commit"])
    assert meta["git_sha"] == meta["commit"] == results["commit"]
    assert "multi-image-dossier-v14-expanded-carbon" in meta["command"]
    assert "--worlds medium:3,medium:4,medium:5,hard:2,hard:3,hard:4" in meta["command"]

    u = meta["usage"]
    assert u == results["usage"]
    assert u["calls"] == 6
    assert u["in"] == sum(w["usage"]["in"] for w in results["worlds"]) > 20000
    assert u["out"] == sum(w["usage"]["out"] for w in results["worlds"]) > 1500
    assert u["thinking"] == sum(w["usage"]["thinking"] for w in results["worlds"]) > 0
    assert u["cost_usd"] == pytest.approx(sum(w["usage"]["cost_usd"] for w in results["worlds"]), abs=1e-5)
    assert u["cost_usd"] > 0.0
    assert u["latency_s"] > 0.0

    m = results["metrics"]
    assert m["top1_mole_hits"] >= 5
    assert m["top1_mole_accuracy"] == pytest.approx(m["top1_mole_hits"] / 6, abs=1e-4)
    assert m["top3_mole_hits"] == 6
    assert m["top3_mole_hit_rate"] == 1.0
    assert m["top1_decoy_hits"] == 6
    assert m["top1_decoy_accuracy"] == 1.0
    assert m["decoy_identified_hits"] == 6
    assert m["avoided_framing_trap_hits"] == 6
    assert m["avoided_framing_trap_rate"] == 1.0

    hard_worlds = [w for w in results["worlds"] if w["tier"] == "hard"]
    assert len(hard_worlds) == 3
    assert all(w["evaluation"]["top1_mole_correct"] for w in hard_worlds)
    assert all(w["evaluation"]["top1_decoy_correct"] for w in hard_worlds)

    assert m["memo_scans_expected_total"] == 16
    assert m["memo_scans_matched_total"] == 16
    assert m["memo_scan_readout_accuracy"] == 1.0
    assert m["suspect_dept_hits"] == 6
    assert m["suspect_dept_accuracy"] == 1.0

    assert m["image1_only_mole_hits"] == 0
    assert m["image1_only_mole_accuracy"] == 0.0
    assert m["image1_only_decoy_traps"] == 6
    assert m["image1_only_decoy_trap_rate"] == 1.0
    assert m["image2_only_mole_accuracy"] == 0.0
    assert m["image2_only_decoy_accuracy"] == 0.0
    assert m["image3_only_deterministic_hits"] == 0
    assert m["image3_only_deterministic_mole_accuracy"] == 0.0
    assert m["image3_only_uniform_prior_mean"] == pytest.approx(0.0375, abs=1e-4)

    for w in results["worlds"]:
        sb = w["single_image_baselines"]
        gt = w["ground_truth"]
        assert sb["image1_only_naive_after_hours_pick"] == gt["true_decoy"]
        assert sb["image1_only_mole_correct"] is False
        assert sb["image1_only_trapped_by_decoy"] is True
        assert sb["image2_only_mole_correct"] is False
        assert sb["image3_only_mole_correct"] is False

    assert m["top1_mole_accuracy"] > m["image1_only_mole_accuracy"]
    assert m["top1_mole_accuracy"] > m["image2_only_mole_accuracy"]
    assert m["top1_mole_accuracy"] > m["image3_only_deterministic_mole_accuracy"]
    assert m["top1_mole_accuracy"] > m["image3_only_uniform_prior_mean"]
    assert m["top1_decoy_accuracy"] > m["image2_only_decoy_accuracy"]
    assert m["avoided_framing_trap_rate"] > (1.0 - m["image1_only_decoy_trap_rate"])

    inspected = _inspect_run(meta_path, REPO_ROOT, REPO_ROOT / "data" / "runs" / "committed" / "v1.4")
    assert inspected["verified"] is True, f"provenance errors: {inspected['errors']}"
    assert inspected["errors"] == []
    assert inspected["secret_leaks"] == []
    assert inspected["role"] == "multimodal_evidence"
    assert inspected["model_id"] == "gemini-4-carbon"
    assert inspected["commit"] == meta["commit"]
    assert inspected["count"] == 6
    assert inspected["tokens_in"] == u["in"]
    assert inspected["tokens_out"] == u["out"]
    assert inspected["thinking_tokens"] == u["thinking"]


def test_expanded_files_have_zero_comments_em_en_dashes_or_secrets() -> None:
    hash_char = chr(35)
    py_targets = [
        REPO_ROOT / "canary" / "gemini" / "incident_dossier.py",
        REPO_ROOT / "scripts" / "run_incident_dossier.py",
        REPO_ROOT / "tests" / "test_incident_dossier.py",
        REPO_ROOT / "tests" / "test_incident_dossier_expanded.py",
    ]
    for path in py_targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, f"dash found in {path}"
        assert hash_char not in text, f"hash char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"comment found in {path}: {comments[0]}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    for artifact in sorted(p for p in EXPANDED_DIR.rglob("*") if p.is_file()):
        assert scan_file_secrets(artifact, REPO_ROOT) == []
        if artifact.suffix in {".json", ".jsonl", ".md"}:
            txt = artifact.read_text(encoding="utf-8")
            assert "\u2014" not in txt and "\u2013" not in txt, f"dash found in {artifact}"
