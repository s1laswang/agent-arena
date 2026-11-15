from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini import outthink_evidence_cards as oec

MODULE_PATH = ROOT / "canary" / "gemini" / "outthink_evidence_cards.py"
LIVE_JS_PATH = ROOT / "demo" / "out-think-gemini" / "evidence_cards.js"

UNICODE_DASH_CODES = (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)

VALID_SPRITE_KEYS = frozenset(
    {
        "detective",
        "suspect_0",
        "suspect_1",
        "suspect_2",
        "suspect_3",
        "suspect_4",
        "suspect_5",
        "suspect_6",
        "suspect_7",
        "agent_minimal",
        "agent_low",
        "agent_medium",
        "agent_high",
        "agent_xhigh",
        "pod_locked",
        "pod_unlocked",
        "floor_tile",
        "wall_tile",
        "desk",
        "chair",
        "evidence_board",
        "filing_cabinet",
        "terminal",
        "server_rack",
        "icon_memo",
        "icon_log",
        "icon_chat",
        "icon_badge",
        "icon_magnifier",
        "icon_accuse",
        "icon_correct",
        "icon_wrong",
        "icon_coin",
        "icon_brain",
    }
)

HEX40_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def _extract_balanced_json(js_text: str, marker: str) -> dict:
    idx = js_text.find(marker)
    assert idx != -1, f"Marker {marker!r} not found"
    start = js_text.find("{", idx)
    assert start != -1, "Opening brace not found"
    depth = 0
    in_str: str | None = None
    i = start
    n = len(js_text)
    while i < n:
        ch = js_text[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(js_text[start : i + 1])
        i += 1
    raise AssertionError("Unbalanced braces in JS bundle")


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\" and i + 1 < n:
                if source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, SLASH + SLASH))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, SLASH + STAR))
                i += 2
                while i + 1 < n and not (source[i] == STAR and source[i + 1] == SLASH):
                    if source[i] == "\n":
                        line += 1
                    i += 1
                i += 2
                continue
        i += 1
    return hits


def _resolve_js_runtime() -> tuple[list[str], dict[str, str]] | None:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env
    candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ]
    for cand in candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    return None


def test_live_evidence_cards_js_matches_builder_and_cli_check(tmp_path: Path) -> None:
    assert LIVE_JS_PATH.is_file(), f"Missing {LIVE_JS_PATH}"
    bundle = oec.build_outthink_evidence_cards()
    expected_js = oec.render_evidence_cards_js(bundle)
    actual_js = LIVE_JS_PATH.read_text(encoding="utf-8")
    assert actual_js == expected_js
    assert oec.main(["--check"]) == 0

    out_js = tmp_path / "evidence_cards.js"
    out_json = tmp_path / "evidence_cards.json"
    rc = oec.main(["--js-out", str(out_js), "--json-out", str(out_json)])
    assert rc == 0
    assert out_js.read_text(encoding="utf-8") == expected_js
    parsed_json = json.loads(out_json.read_text(encoding="utf-8"))
    assert parsed_json == bundle


def test_verified_multimodal_summary_rollups_and_four_modalities() -> None:
    bundle = oec.build_outthink_evidence_cards()
    assert bundle["schema_version"] == 1
    assert bundle["role"] == "multimodal_evidence"
    assert bundle["model_id"] == "gemini-4-carbon"

    summary = bundle["summary"]
    assert summary["total_runs"] == 17
    assert summary["total_cards"] == 100
    assert summary["total_vision_calls"] == 226
    assert summary["total_images_read"] == 260
    assert summary["total_tokens"] == {
        "in": 486594,
        "out": 47941,
        "thinking": 206845,
        "cached": 0,
    }
    assert summary["total_cost_usd"] == pytest.approx(3.521048, abs=1e-6)
    assert summary["worlds_covered_v14"] == 27

    by_mod = summary["by_modality"]
    assert set(by_mod.keys()) == {"scan", "heatmap", "dossier", "forensics"}

    scan = by_mod["scan"]
    assert scan["runs"] == 6
    assert scan["cards"] == 30
    assert scan["images_read"] == 156
    assert scan["canary_memos_decoded"] == 49
    assert scan["watermark_vision_accuracy"] == 1.0
    assert scan["multimodal_mole_hits"] == 30
    assert scan["multimodal_mole_accuracy"] == 1.0
    assert scan["blind_mole_hits"] == 10
    assert scan["blind_mole_accuracy"] == pytest.approx(0.3333, abs=1e-4)
    assert scan["oracle_score_recovery_ratio"] == 1.0

    heat = by_mod["heatmap"]
    assert heat["runs"] == 5
    assert heat["cards"] == 28
    assert heat["images_read"] == 28
    assert heat["top1_mole_hits"] == 27
    assert heat["top3_mole_hits"] == 28
    assert heat["top1_decoy_hits"] == 28
    assert heat["avoided_framing_trap_hits"] == 28
    assert heat["naive_baseline_mole_accuracy"] == 0.0
    cal = heat["thinking_calibration"]
    assert cal is not None
    assert cal["low_thinking_tokens"] == 1983
    assert cal["high_thinking_tokens"] == 85629
    assert cal["low_brier_score"] == pytest.approx(0.002117, abs=1e-6)
    assert cal["high_brier_score"] == pytest.approx(0.000254, abs=1e-6)
    assert cal["low_ece"] == pytest.approx(0.025333, abs=1e-6)
    assert cal["high_ece"] == pytest.approx(0.012667, abs=1e-6)

    doss = by_mod["dossier"]
    assert doss["runs"] == 3
    assert doss["cards"] == 17
    assert doss["images_read"] == 51
    assert doss["images_per_call"] == 3
    assert doss["top1_mole_hits"] == 14
    assert doss["top3_mole_hits"] == 16
    assert doss["top1_decoy_hits"] == 16
    assert doss["avoided_framing_trap_hits"] == 17
    assert doss["memo_scans_matched"] == 43
    assert doss["memo_scans_total"] == 43
    assert doss["single_image_baseline_mole_accuracy"] == 0.0

    fore = by_mod["forensics"]
    assert fore["runs"] == 3
    assert fore["cards"] == 25
    assert fore["images_read"] == 25
    assert fore["visual_threshold_hits"] == 25
    assert fore["accuse_day_exact_hits"] == 25
    assert fore["hidden_bleed_gap_hits"] == 25


def test_room_stations_and_card_sprites_align_with_outthink_assets_schema() -> None:
    bundle = oec.build_outthink_evidence_cards()
    stations = bundle["room_stations"]
    assert len(stations) == 4
    assert [s["modality"] for s in stations] == ["scan", "heatmap", "dossier", "forensics"]

    for st in stations:
        assert st["prop_sprite"] in VALID_SPRITE_KEYS
        assert st["icon_sprite"] in VALID_SPRITE_KEYS
        assert st["analyst_sprite"] in VALID_SPRITE_KEYS
        assert st["badge_sprite"] in VALID_SPRITE_KEYS
        assert st["card_count"] > 0
        assert st["images_read"] > 0
        assert isinstance(st["summary_line"], str) and len(st["summary_line"]) > 20

    for card in bundle["cards"]:
        assert card["sprite_key"] in VALID_SPRITE_KEYS
        assert card["prop_sprite_key"] in VALID_SPRITE_KEYS
        assert card["analyst_sprite_key"] in VALID_SPRITE_KEYS


def test_every_card_has_cryptographic_provenance_sha256_dims_and_verbatim_quote() -> None:
    bundle = oec.build_outthink_evidence_cards()
    cards = bundle["cards"]
    assert len(cards) == 100

    seen_ids: set[str] = set()
    total_images = 0
    total_cost = 0.0

    for card in cards:
        cid = card["card_id"]
        assert cid not in seen_ids
        seen_ids.add(cid)

        assert card["modality"] in ("scan", "heatmap", "dossier", "forensics")
        assert card["tier"] in ("medium", "hard")
        assert isinstance(card["seed"], int) and card["seed"] >= 0
        assert card["model_id"] == "gemini-4-carbon"
        assert HEX40_RE.fullmatch(card["commit"]), f"Invalid commit on {cid}: {card['commit']!r}"
        assert card["ledger_run_id"]
        assert "2026-11-14T" in card["timestamp"]

        imgs = card["images"]
        assert len(imgs) == card["n_images_read"] >= 1
        if card["modality"] == "dossier":
            assert len(imgs) == 3
        for img in imgs:
            assert HEX64_RE.fullmatch(img["sha256"]), f"Invalid sha256 on {cid}: {img['sha256']!r}"
            assert isinstance(img["bytes"], int) and img["bytes"] > 0
            assert (
                isinstance(img["size"], list)
                and len(img["size"]) == 2
                and all(isinstance(d, int) and d > 0 for d in img["size"])
            )
        total_images += len(imgs)

        finding = card["finding"]
        assert isinstance(finding["headline"], str) and len(finding["headline"]) >= 25
        assert isinstance(finding["gemini_quote"], str) and len(finding["gemini_quote"]) >= 25

        usage = card["usage"]
        assert usage["calls"] >= 1
        assert usage["in"] > 0
        assert usage["out"] > 0
        assert usage["cost_usd"] > 0.0
        total_cost += float(usage["cost_usd"])

    assert total_images == 260
    assert total_cost == pytest.approx(3.521048, abs=1e-4)


def test_world_index_consistency_and_thinking_comparison_pairs() -> None:
    bundle = oec.build_outthink_evidence_cards()
    by_world = bundle["by_world"]
    assert len(by_world) == 27

    expected_worlds = {f"medium/{s}" for s in range(12)} | {f"hard/{s}" for s in range(15)}
    assert set(by_world.keys()) == expected_worlds

    full_four_mod_worlds = [wk for wk, w in by_world.items() if len(w["modalities"]) == 4]
    assert len(full_four_mod_worlds) == 10

    paired_worlds = ["medium/8", "medium/9", "hard/8", "hard/9", "hard/10", "hard/11"]
    for wk in paired_worlds:
        w = by_world[wk]
        cmp_obj = w["thinking_comparison"]
        assert cmp_obj is not None, f"Missing thinking_comparison on {wk}"
        assert cmp_obj["high_thinking_tokens"] > cmp_obj["low_thinking_tokens"]
        assert w["primary_card_ids"]["heatmap"] == cmp_obj["high_card_id"]


def test_directory_loader_roundtrip_and_prose_sanitization(tmp_path: Path) -> None:
    em = chr(0x2014)
    en = chr(0x2013)
    commit_sha = "a" * 40
    png_sha = "b" * 64

    scan_dir = tmp_path / "scan-run"
    scan_dir.mkdir()
    (scan_dir / "meta.json").write_text(
        json.dumps(
            {
                "role": "multimodal_evidence",
                "subrole": "visual_memo_blind_ablation",
                "model_id": "gemini-4-carbon",
                "tiers_version": "v1.4",
                "tier": "medium",
                "seeds": [0],
                "commit": commit_sha,
                "timestamp": "2026-11-14T18:00:00+00:00",
                "command": "python scripts/run_memo_vision_ablation.py --thinking-level LOW",
                "ledger_run_id": "scan-test-1",
                "n_images_read_by_model": 1,
                "n_canary_memos_read_by_model": 1,
                "variant_vision_accuracy": 1.0,
                "canary_variant_vision_accuracy": 1.0,
                "multimodal_accuracy": 1.0,
                "blind_accuracy": 0.0,
                "multimodal_mean_score": 0.75,
                "blind_mean_score": 0.0,
                "oracle_mean_score": 0.75,
                "oracle_score_recovery_ratio": 1.0,
                "usage": {"calls": 1, "in": 1900, "out": 140, "thinking": 0, "cached": 0, "cost_usd": 0.0052, "latency_s": 8.1},
            }
        ),
        encoding="utf-8",
    )
    (scan_dir / "comparison.json").write_text(
        json.dumps(
            {
                "per_seed": [
                    {
                        "seed": 0,
                        "tier": "medium",
                        "tiers_version": "v1.4",
                        "multimodal_carbon": {"score": 0.75, "correct": True, "accused": "e05", "final_day": 8, "max_posterior": 0.96},
                        "blind_no_vision": {"score": 0.0, "correct": False, "accused": None, "final_day": 14, "end_reason": "horizon"},
                        "text_oracle": {"score": 0.75, "correct": True, "accused": "e05", "final_day": 8},
                    }
                ],
                "vision_calls": [
                    {
                        "seed": 0,
                        "tier": "medium",
                        "doc_id": "c1",
                        "day_surfaced": 4,
                        "is_canary_memo": True,
                        "expected_variant": "B",
                        "predicted_variant": "B",
                        "variant_exact_match": True,
                        "memo_path": "memos/seed_0_c1.png",
                        "memo_sha256": png_sha,
                        "memo_bytes": 31000,
                        "memo_size": [880, 620],
                        "model_response": {
                            "visual_evidence": f"Stamp {HASH_CHAR}2 {em} variant B {en} verified across footer ticks."
                        },
                        "usage": {"in": 1900, "out": 140, "thinking": 0, "cached": 0, "cost_usd": 0.0052, "latency_s": 8.1},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    heat_dir = tmp_path / "heat-run"
    heat_dir.mkdir()
    (heat_dir / "meta.json").write_text(
        json.dumps(
            {
                "role": "multimodal_evidence",
                "subrole": "soc_access_vision",
                "model_id": "gemini-4-carbon",
                "thinking_level": "high",
                "tiers_version": "v1.4",
                "tier": "medium",
                "seeds": [0],
                "commit": commit_sha,
                "timestamp": "2026-11-14T18:05:00+00:00",
                "ledger_run_id": "heat-test-1",
                "n_images_read_by_model": 1,
                "usage": {"calls": 1, "in": 2000, "out": 400, "thinking": 9000, "cached": 0, "cost_usd": 0.098, "latency_s": 40.0},
            }
        ),
        encoding="utf-8",
    )
    (heat_dir / "results.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "top1_mole_hits": 1,
                    "top1_mole_accuracy": 1.0,
                    "top3_mole_hits": 1,
                    "top3_mole_hit_rate": 1.0,
                    "top1_decoy_hits": 1,
                    "top1_decoy_accuracy": 1.0,
                    "avoided_framing_trap_hits": 1,
                    "avoided_framing_trap_rate": 1.0,
                },
                "worlds": [
                    {
                        "seed": 0,
                        "tier": "medium",
                        "raster_path": "rasters/medium_seed_0.png",
                        "raster_sha256": png_sha,
                        "raster_bytes": 150000,
                        "raster_size": [1880, 1020],
                        "observable_summary": {"naive_most_after_hours_id": "e19"},
                        "model_output": {
                            "top_suspect_ids": ["e05"],
                            "suspected_decoy_ids": ["e19"],
                            "confidence": 0.99,
                            "visual_reasoning": f"Panel B {em} e05 matches all canary rows {HASH_CHAR}1..3 while e19 is decoy.",
                        },
                        "ground_truth": {"true_mole": "e05", "true_decoy": "e19"},
                        "evaluation": {
                            "top1_mole_correct": True,
                            "top3_mole_hit": True,
                            "top1_decoy_correct": True,
                            "avoided_framing_trap": True,
                            "brier_score": 0.0001,
                        },
                        "usage": {"in": 2000, "out": 400, "thinking": 9000, "cached": 0, "cost_usd": 0.098, "latency_s": 40.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    doss_dir = tmp_path / "dossier-run"
    doss_dir.mkdir()
    (doss_dir / "meta.json").write_text(
        json.dumps(
            {
                "role": "multimodal_evidence",
                "subrole": "multi_image_incident_dossier",
                "model_id": "gemini-4-carbon",
                "tiers_version": "v1.4",
                "commit": commit_sha,
                "timestamp": "2026-11-14T18:10:00+00:00",
                "ledger_run_id": "doss-test-1",
                "images_per_call": 3,
                "n_images_read_by_model": 3,
                "usage": {"calls": 1, "in": 4500, "out": 410, "thinking": 12000, "cached": 0, "cost_usd": 0.133, "latency_s": 55.0},
            }
        ),
        encoding="utf-8",
    )
    (doss_dir / "results.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "top1_mole_hits": 1,
                    "top1_mole_accuracy": 1.0,
                    "top3_mole_hits": 1,
                    "top3_mole_hit_rate": 1.0,
                    "top1_decoy_hits": 1,
                    "top1_decoy_accuracy": 1.0,
                    "decoy_identified_hits": 1,
                    "avoided_framing_trap_hits": 1,
                    "avoided_framing_trap_rate": 1.0,
                    "memo_scans_matched_total": 1,
                    "memo_scans_expected_total": 1,
                    "memo_scan_readout_accuracy": 1.0,
                },
                "worlds": [
                    {
                        "seed": 0,
                        "tier": "medium",
                        "images": {
                            "badge_raster": {"kind": "badge_raster", "path": "d/b.png", "sha256": png_sha, "bytes": 100000, "size": [1274, 996]},
                            "leaked_memo_scans": {"kind": "leaked_memo_scans", "path": "d/m.png", "sha256": png_sha, "bytes": 50000, "size": [1510, 644]},
                            "org_canary_map": {"kind": "org_canary_map", "path": "d/o.png", "sha256": png_sha, "bytes": 120000, "size": [1320, 1204]},
                        },
                        "single_image_baselines": {"image1_only_naive_after_hours_pick": "e19"},
                        "model_output": {
                            "top_suspect_ids": ["e05"],
                            "suspected_decoy_ids": ["e19"],
                            "confidence": 0.94,
                            "decoded_leaked_canaries": [{"doc_id": "c1", "variant": "B"}],
                            "suspect_department": "Engineering",
                            "cross_image_reasoning": f"Exhibit 1 {en} Exhibit 3 {em} isolate e05 over decoy e19.",
                        },
                        "ground_truth": {"true_mole": "e05", "true_mole_dept": "Engineering", "true_decoy": "e19", "true_decoy_dept": "Finance"},
                        "evaluation": {
                            "top1_mole_correct": True,
                            "top3_mole_hit": True,
                            "top1_decoy_correct": True,
                            "avoided_framing_trap": True,
                            "memo_scans_matched": 1,
                            "memo_scans_total": 1,
                        },
                        "usage": {"in": 4500, "out": 410, "thinking": 12000, "cached": 0, "cost_usd": 0.133, "latency_s": 55.0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    fore_dir = tmp_path / "forensics-run"
    fore_dir.mkdir()
    (fore_dir / "meta.json").write_text(
        json.dumps(
            {
                "role": "multimodal_evidence",
                "subrole": "carbon_v14_trajectory_forensics",
                "model_id": "gemini-4-carbon",
                "tiers_version": "v1.4",
                "commit": commit_sha,
                "timestamp": "2026-11-14T18:15:00+00:00",
                "ledger_run_id": "fore-test-1",
                "n_charts_analyzed": 1,
                "n_images_read_by_model": 1,
                "visual_threshold_accuracy": 1.0,
                "accuse_day_within_1_accuracy": 1.0,
                "accuse_day_exact_accuracy": 1.0,
                "hidden_bleed_gap_accuracy": 1.0,
                "image_manifest": {"images": [{"path": "charts/ep_0.png", "size": [2208, 2624], "sha256": png_sha}]},
                "usage": {"calls": 1, "in": 2300, "out": 320, "thinking": 700, "cached": 0, "cost_usd": 0.0148, "latency_s": 12.0},
            }
        ),
        encoding="utf-8",
    )
    (fore_dir / "diagnoses.json").write_text(
        json.dumps(
            [
                {
                    "episode_index": 0,
                    "cohort": "high_scoring",
                    "chart_path": "charts/ep_0.png",
                    "chart_bytes_len": 410000,
                    "chart_sha256": png_sha,
                    "source_episode": {"tier": "medium", "seed": 0, "agent": "gemini:gemini-4-carbon"},
                    "ground_truth": {
                        "actual_accuse_day": 8,
                        "accused_employee": "e05",
                        "true_mole": "e05",
                        "framed_decoy": "e19",
                        "correct": True,
                        "score": 0.75,
                        "accused_below_ev_threshold": False,
                        "hidden_bleed_gap_present": False,
                    },
                    "gemini_diagnosis": {
                        "estimated_accuse_day": 8,
                        "accused_below_ev_threshold": False,
                        "hidden_bleed_gap_present": False,
                        "primary_failure_pattern": "clean_stop",
                        "fooled_step_summary": f"Panel 1 {em} clean stop on day 8 above EV threshold {HASH_CHAR}1.",
                    },
                    "scoring": {"threshold_match": True, "day_within_1": True, "day_exact": True, "bleed_gap_match": True},
                    "usage": {"in": 2300, "out": 320, "thinking": 700, "cached": 0, "cost_usd": 0.0148, "latency_s": 12.0},
                }
            ]
        ),
        encoding="utf-8",
    )

    bundle = oec.build_outthink_evidence_cards(tmp_path)
    js_out = oec.render_evidence_cards_js(bundle)
    assert HASH_CHAR not in js_out
    assert not any(chr(c) in js_out for c in UNICODE_DASH_CODES)
    assert bundle["summary"]["total_runs"] == 4
    assert bundle["summary"]["total_cards"] == 4
    assert bundle["by_world"]["medium/0"]["true_mole"] == "e05"
    assert bundle["by_world"]["medium/0"]["true_decoy"] == "e19"
    assert bundle["by_world"]["medium/0"]["modalities"] == ["scan", "heatmap", "dossier", "forensics"]

    bad_cards = json.loads(json.dumps(bundle["cards"]))
    bad_cards[1]["ground_truth"]["true_mole"] = "e11"
    with pytest.raises(AssertionError, match="Conflicting true_mole"):
        oec.assemble_evidence_bundle(bundle["runs"], bad_cards)


def test_js_bundle_parses_cleanly_and_helper_api_executes() -> None:
    js_src = LIVE_JS_PATH.read_text(encoding="utf-8")
    parsed_bundle = _extract_balanced_json(js_src, "_w.OUTTHINK_EVIDENCE_CARDS")
    assert parsed_bundle["summary"]["total_cards"] == 100
    assert len(parsed_bundle["room_stations"]) == 4

    rt = _resolve_js_runtime()
    if rt is None:
        pytest.skip("No local JS runtime available")
    cmd_prefix, env = rt
    run_env = dict(env)
    run_env["OUTTHINK_EVIDENCE_JS"] = str(LIVE_JS_PATH)
    script = (
        "globalThis.window = {};\n"
        "const mod = require(process.env.OUTTHINK_EVIDENCE_JS);\n"
        "const w1 = mod.getOutthinkWorldEvidence('hard', 8);\n"
        "const w2 = window.getOutthinkWorldEvidence('gemini-4-carbon/high/hard/8');\n"
        "const w3 = globalThis.getOutthinkWorldEvidence({ difficulty: 'HARD', worldSeed: 8 });\n"
        "const w4 = mod.getOutthinkWorldEvidence('medium|3');\n"
        "const scanCard = mod.getOutthinkEvidenceForCase('hard', 10, 'scan');\n"
        "const dossCard = window.getOutthinkEvidenceForCase({ tier: 'medium', seed: 3 }, null, 'dossier');\n"
        "const highHeat = mod.listOutthinkEvidenceCards({ modality: 'heatmap', thinking_level: 'high' });\n"
        "const stations = window.listOutthinkEvidenceStations();\n"
        "process.stdout.write(JSON.stringify({\n"
        "  totalCards: window.OUTTHINK_EVIDENCE_CARDS.summary.total_cards,\n"
        "  globalTotalCards: globalThis.OUTTHINK_EVIDENCE_CARDS.summary.total_cards,\n"
        "  sameWorld12: w1.world_key === w2.world_key,\n"
        "  sameWorld13: w1.world_key === w3.world_key,\n"
        "  w1Mole: w1.true_mole,\n"
        "  w4Mole: w4.true_mole,\n"
        "  scanMole: scanCard.finding.predicted_mole,\n"
        "  dossImages: dossCard.images.length,\n"
        "  highHeatLen: highHeat.length,\n"
        "  stationLen: stations.length\n"
        "}));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, script],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS execution failed: {proc.stderr}"
    res = json.loads(proc.stdout)
    assert res == {
        "totalCards": 100,
        "globalTotalCards": 100,
        "sameWorld12": True,
        "sameWorld13": True,
        "w1Mole": "e06",
        "w4Mole": "e14",
        "scanMole": "e10",
        "dossImages": 3,
        "highHeatLen": 6,
        "stationLen": 4,
    }


def test_zero_comments_zero_unicode_dashes_and_zero_network_sdk_imports() -> None:
    self_path = Path(__file__).resolve()
    for py_path in (MODULE_PATH, self_path):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"Hash character found in {py_path.name}"
        for code in UNICODE_DASH_CODES:
            assert chr(code) not in src, f"Unicode dash U+{code:04X} found in {py_path.name}"

        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"Comment tokens found in {py_path.name}: {comments}"

        tree = ast.parse(src)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        forbidden = ("google", "genai", "atlas_gemini", "gateway", "httpx", "requests", "urllib", "socket", "aiohttp")
        for mod in imported:
            assert not any(f in mod for f in forbidden), f"Forbidden module {mod!r} in {py_path.name}"

    js_src = LIVE_JS_PATH.read_text(encoding="utf-8")
    assert HASH_CHAR not in js_src, "Hash character found in evidence_cards.js"
    for code in UNICODE_DASH_CODES:
        assert chr(code) not in js_src, f"Unicode dash U+{code:04X} found in evidence_cards.js"
        assert ("\\u" + f"{code:04x}") not in js_src.lower()
    js_comments = _find_js_comments(js_src)
    assert js_comments == [], f"JS comments found in evidence_cards.js: {js_comments}"
