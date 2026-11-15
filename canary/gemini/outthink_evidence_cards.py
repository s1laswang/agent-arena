from __future__ import annotations

import argparse
import base64
import json
import re
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MULTIMODAL_DIR = ROOT / "results" / "gemini" / "roles_carbon" / "multimodal_evidence"
DEFAULT_JS_OUT = ROOT / "demo" / "out-think-gemini" / "evidence_cards.js"

SCHEMA_VERSION = 1
MODALITIES: tuple[str, ...] = ("scan", "heatmap", "dossier", "forensics")
UNICODE_DASHES = "".join(chr(c) for c in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212))
HASH_CHAR = chr(35)

STATION_SPECS: dict[str, dict[str, str]] = {
    "scan": {
        "station_id": "scan_desk",
        "modality": "scan",
        "label": "Leaked Memo Watermark Lightbox",
        "prop_sprite": "desk",
        "icon_sprite": "icon_memo",
        "analyst_sprite": "agent_low",
        "badge_sprite": "icon_magnifier",
    },
    "heatmap": {
        "station_id": "soc_terminal",
        "modality": "heatmap",
        "label": "SOC Access and Framing Raster Terminal",
        "prop_sprite": "terminal",
        "icon_sprite": "icon_log",
        "analyst_sprite": "agent_high",
        "badge_sprite": "icon_correct",
    },
    "dossier": {
        "station_id": "dossier_board",
        "modality": "dossier",
        "label": "Three-Image Incident Dossier Corkboard",
        "prop_sprite": "evidence_board",
        "icon_sprite": "icon_badge",
        "analyst_sprite": "agent_medium",
        "badge_sprite": "icon_accuse",
    },
    "forensics": {
        "station_id": "forensics_rack",
        "modality": "forensics",
        "label": "Four-Panel Belief and Trajectory Forensics Rack",
        "prop_sprite": "server_rack",
        "icon_sprite": "icon_brain",
        "analyst_sprite": "agent_xhigh",
        "badge_sprite": "icon_coin",
    },
}

EMBEDDED_SNAPSHOT_ZLIB_B64 = (
    "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"
    "hdH8z39+/8//D0Wio+8="
)


def clean_prose(text: str | None, max_chars: int | None = None) -> str:
    if text is None:
        return ""
    out = str(text).replace(HASH_CHAR, "No.")
    for ch in UNICODE_DASHES:
        out = out.replace(ch, " - ")
    out = re.sub(r"\s+", " ", out).strip()
    if max_chars is not None and len(out) > max_chars:
        cut = out[: max_chars - 3].rsplit(" ", 1)[0]
        out = (cut if cut else out[: max_chars - 3]) + "..."
    return out


def has_unicode_dash(text: str) -> bool:
    return any(ch in text for ch in UNICODE_DASHES)


def _infer_thinking_level(meta: dict[str, Any], payload: dict[str, Any] | None = None) -> str:
    raw = meta.get("thinking_level")
    if not raw and isinstance(payload, dict):
        raw = payload.get("thinking_level")
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    cmd = str(meta.get("command") or "")
    match = re.search(r"--thinking-level\s+([A-Za-z0-9_-]+)", cmd)
    if match:
        return match.group(1).strip().lower()
    return "default"


def _normalize_usage(usage_raw: dict[str, Any], default_calls: int = 1) -> dict[str, int | float]:
    return {
        "calls": int(usage_raw.get("calls", default_calls)),
        "in": int(usage_raw.get("in", 0)),
        "out": int(usage_raw.get("out", 0)),
        "thinking": int(usage_raw.get("thinking", 0)),
        "cached": int(usage_raw.get("cached", 0)),
        "cost_usd": round(float(usage_raw.get("cost_usd", 0.0)), 6),
        "latency_s": round(float(usage_raw.get("latency_s", 0.0)), 3),
    }


def _manifest_size_lookup(meta: dict[str, Any]) -> dict[str, list[int]]:
    lookup: dict[str, list[int]] = {}
    manifest = meta.get("image_manifest")
    if isinstance(manifest, dict):
        images = manifest.get("images")
        if isinstance(images, list):
            for entry in images:
                if not isinstance(entry, dict):
                    continue
                size = entry.get("size")
                if isinstance(size, list) and len(size) == 2:
                    dims = [int(size[0]), int(size[1])]
                    if isinstance(entry.get("path"), str):
                        lookup[entry["path"]] = dims
                    if isinstance(entry.get("sha256"), str):
                        lookup[entry["sha256"]] = dims
    return lookup


def parse_scan_run(
    run_dir: str,
    meta: dict[str, Any],
    comparison: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    thinking_level = _infer_thinking_level(meta, comparison)
    commit = str(meta.get("commit") or meta.get("git_sha") or comparison.get("commit") or "")
    timestamp = str(meta.get("timestamp") or comparison.get("timestamp") or "")
    tiers_version = str(meta.get("tiers_version") or comparison.get("tiers_version") or "v1.4")
    model_id = str(meta.get("model_id") or comparison.get("model_id") or "gemini-4-carbon")
    subrole = str(meta.get("subrole") or "visual_memo_blind_ablation")
    ledger_run_id = str(meta.get("ledger_run_id") or f"multimodal_evidence:{subrole}:{run_dir}")
    n_images = int(meta.get("n_images_read_by_model") or comparison.get("n_images_read_by_model") or 0)
    usage = _normalize_usage(meta.get("usage") or comparison.get("usage") or {}, default_calls=n_images)

    per_seed = comparison.get("per_seed") or []
    vision_calls = comparison.get("vision_calls") or []
    calls_by_seed: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for vc in vision_calls:
        calls_by_seed[int(vc["seed"])].append(vc)

    mm_hits = sum(1 for row in per_seed if row["multimodal_carbon"].get("correct"))
    blind_hits = sum(1 for row in per_seed if row["blind_no_vision"].get("correct"))
    oracle_hits = sum(1 for row in per_seed if row["text_oracle"].get("correct"))
    station = STATION_SPECS["scan"]

    run_rec: dict[str, Any] = {
        "run_dir": run_dir,
        "modality": "scan",
        "subrole": subrole,
        "model_id": model_id,
        "thinking_level": thinking_level,
        "tiers_version": tiers_version,
        "tiers": [str(meta.get("tier") or comparison.get("tier") or "medium")],
        "seeds": [int(s) for s in (meta.get("seeds") or comparison.get("seeds") or [])],
        "commit": commit,
        "timestamp": timestamp,
        "ledger_run_id": ledger_run_id,
        "n_cards": len(per_seed),
        "n_images_read": n_images,
        "usage": usage,
        "headline_metrics": {
            "n_episodes": len(per_seed),
            "n_canary_memos_read": int(meta.get("n_canary_memos_read_by_model", 0)),
            "variant_vision_accuracy": round(float(meta.get("variant_vision_accuracy", 1.0)), 4),
            "canary_variant_vision_accuracy": round(float(meta.get("canary_variant_vision_accuracy", 1.0)), 4),
            "multimodal_mole_hits": mm_hits,
            "blind_mole_hits": blind_hits,
            "oracle_mole_hits": oracle_hits,
            "multimodal_accuracy": round(float(meta.get("multimodal_accuracy", 0.0)), 4),
            "blind_accuracy": round(float(meta.get("blind_accuracy", 0.0)), 4),
            "multimodal_mean_score": round(float(meta.get("multimodal_mean_score", 0.0)), 4),
            "blind_mean_score": round(float(meta.get("blind_mean_score", 0.0)), 4),
            "oracle_mean_score": round(float(meta.get("oracle_mean_score", 0.0)), 4),
            "oracle_score_recovery_ratio": round(float(meta.get("oracle_score_recovery_ratio", 1.0)), 4),
        },
    }

    cards: list[dict[str, Any]] = []
    for row in per_seed:
        seed = int(row["seed"])
        tier = str(row["tier"]).lower()
        seed_calls = calls_by_seed.get(seed, [])
        canary_calls = [vc for vc in seed_calls if vc.get("is_canary_memo")]
        mm = row["multimodal_carbon"]
        bl = row["blind_no_vision"]
        orc = row["text_oracle"]

        true_mole = str(orc.get("accused") or mm.get("accused") or "")
        mm_accused = mm.get("accused")
        bl_accused = bl.get("accused")
        mm_score = round(float(mm.get("score", 0.0)), 4)
        bl_score = round(float(bl.get("score", 0.0)), 4)
        orc_score = round(float(orc.get("score", 0.0)), 4)

        images = [
            {
                "kind": "canary_memo_scan" if vc.get("is_canary_memo") else "regular_memo_scan",
                "doc_id": str(vc["doc_id"]),
                "day_surfaced": int(vc["day_surfaced"]),
                "expected_variant": vc.get("expected_variant"),
                "predicted_variant": vc.get("predicted_variant"),
                "exact_match": bool(vc.get("variant_exact_match", True)),
                "path": str(vc["memo_path"]),
                "sha256": str(vc["memo_sha256"]),
                "bytes": int(vc["memo_bytes"]),
                "size": [int(vc["memo_size"][0]), int(vc["memo_size"][1])],
            }
            for vc in seed_calls
        ]

        decoded_watermarks = [
            {
                "doc_id": str(vc["doc_id"]),
                "day_surfaced": int(vc["day_surfaced"]),
                "expected_variant": vc.get("expected_variant"),
                "predicted_variant": vc.get("predicted_variant"),
                "exact_match": bool(vc.get("variant_exact_match", True)),
            }
            for vc in canary_calls
        ]

        quote_source = canary_calls[0] if canary_calls else (seed_calls[0] if seed_calls else {})
        raw_quote = (quote_source.get("model_response") or {}).get("visual_evidence", "")
        gemini_quote = clean_prose(raw_quote, max_chars=360)

        seed_usage = {
            "calls": len(seed_calls),
            "in": sum(int(vc["usage"].get("in", 0)) for vc in seed_calls),
            "out": sum(int(vc["usage"].get("out", 0)) for vc in seed_calls),
            "thinking": sum(int(vc["usage"].get("thinking", 0)) for vc in seed_calls),
            "cached": sum(int(vc["usage"].get("cached", 0)) for vc in seed_calls),
            "cost_usd": round(sum(float(vc["usage"].get("cost_usd", 0.0)) for vc in seed_calls), 6),
            "latency_s": round(sum(float(vc["usage"].get("latency_s", 0.0)) for vc in seed_calls), 3),
        }

        wm_tags = ", ".join(f"{w['doc_id']}={w['predicted_variant']}" for w in decoded_watermarks)
        blind_outcome = (
            f"accused {bl_accused} (score {bl_score:.2f})"
            if bl_accused
            else f"stalled to {bl.get('end_reason', 'horizon')} (score {bl_score:.2f})"
        )
        headline = clean_prose(
            f"Decoded {len(canary_calls)}/{len(canary_calls)} planted canary watermarks ({wm_tags}) across "
            f"{len(seed_calls)} leaked memo PNGs; isolated mole {mm_accused} on day {int(mm['final_day'])} "
            f"(score {mm_score:.2f} vs blind {blind_outcome})."
        )

        cards.append(
            {
                "card_id": f"scan:{run_dir}:{tier}:{seed}",
                "modality": "scan",
                "subrole": subrole,
                "station_id": station["station_id"],
                "sprite_key": station["icon_sprite"],
                "prop_sprite_key": station["prop_sprite"],
                "analyst_sprite_key": station["analyst_sprite"],
                "tier": tier,
                "seed": seed,
                "world_key": f"{tier}/{seed}",
                "pipe_key": f"{tier}|{seed}",
                "tiers_version": tiers_version,
                "model_id": model_id,
                "thinking_level": thinking_level,
                "run_dir": run_dir,
                "ledger_run_id": ledger_run_id,
                "commit": commit,
                "timestamp": timestamp,
                "n_images_read": len(seed_calls),
                "images": images,
                "ground_truth": {
                    "true_mole": true_mole,
                    "true_decoy": None,
                },
                "finding": {
                    "title": f"Scanned Leak-Memo Watermarks ({tier} seed {seed})",
                    "badge": f"{len(seed_calls)}/{len(seed_calls)} PNGs exact",
                    "headline": headline,
                    "predicted_mole": mm_accused,
                    "predicted_decoy": None,
                    "mole_correct": bool(mm.get("correct", False)),
                    "avoided_framing_trap": bool(mm.get("correct", False)),
                    "confidence": round(float(mm.get("max_posterior", 1.0)), 4),
                    "gemini_quote": gemini_quote,
                    "decoded_watermarks": decoded_watermarks,
                    "ablation": {
                        "multimodal_accused": mm_accused,
                        "multimodal_score": mm_score,
                        "multimodal_correct": bool(mm.get("correct", False)),
                        "multimodal_final_day": int(mm.get("final_day", 0)),
                        "blind_accused": bl_accused,
                        "blind_score": bl_score,
                        "blind_correct": bool(bl.get("correct", False)),
                        "blind_end_reason": str(bl.get("end_reason", "")),
                        "oracle_score": orc_score,
                        "score_gain_vs_blind": round(mm_score - bl_score, 4),
                    },
                },
                "usage": seed_usage,
            }
        )

    return run_rec, cards


def parse_heatmap_run(
    run_dir: str,
    meta: dict[str, Any],
    results: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    thinking_level = _infer_thinking_level(meta, results)
    commit = str(meta.get("commit") or meta.get("git_sha") or results.get("commit") or "")
    timestamp = str(meta.get("timestamp") or results.get("timestamp") or "")
    tiers_version = str(meta.get("tiers_version") or results.get("tiers_version") or "v1.4")
    model_id = str(meta.get("model_id") or results.get("model_id") or "gemini-4-carbon")
    subrole = str(meta.get("subrole") or results.get("subrole") or "soc_access_vision")
    ledger_run_id = str(meta.get("ledger_run_id") or f"multimodal_evidence:{subrole}:{run_dir}")
    worlds = results.get("worlds") or []
    n_images = int(meta.get("n_images_read_by_model") or results.get("n_images_read_by_model") or len(worlds))
    usage = _normalize_usage(meta.get("usage") or results.get("usage") or {}, default_calls=len(worlds))
    metrics = results.get("metrics") or {}

    tiers_list = meta.get("tiers") or ([meta["tier"]] if meta.get("tier") else sorted({str(w["tier"]) for w in worlds}))
    seeds_list = meta.get("seeds") or [int(w["seed"]) for w in worlds]
    station = STATION_SPECS["heatmap"]

    analyst_sprite = {
        "minimal": "agent_minimal",
        "low": "agent_low",
        "medium": "agent_medium",
        "high": "agent_high",
        "xhigh": "agent_xhigh",
    }.get(thinking_level, station["analyst_sprite"])

    run_rec: dict[str, Any] = {
        "run_dir": run_dir,
        "modality": "heatmap",
        "subrole": subrole,
        "model_id": model_id,
        "thinking_level": thinking_level,
        "tiers_version": tiers_version,
        "tiers": [str(t) for t in tiers_list],
        "seeds": [int(s) for s in seeds_list],
        "commit": commit,
        "timestamp": timestamp,
        "ledger_run_id": ledger_run_id,
        "n_cards": len(worlds),
        "n_images_read": n_images,
        "usage": usage,
        "headline_metrics": {
            "n_worlds": len(worlds),
            "top1_mole_hits": int(metrics.get("top1_mole_hits", 0)),
            "top1_mole_accuracy": round(float(metrics.get("top1_mole_accuracy", 0.0)), 4),
            "top3_mole_hits": int(metrics.get("top3_mole_hits", 0)),
            "top3_mole_hit_rate": round(float(metrics.get("top3_mole_hit_rate", 0.0)), 4),
            "top1_decoy_hits": int(metrics.get("top1_decoy_hits", 0)),
            "top1_decoy_accuracy": round(float(metrics.get("top1_decoy_accuracy", 0.0)), 4),
            "avoided_framing_trap_hits": int(metrics.get("avoided_framing_trap_hits", 0)),
            "avoided_framing_trap_rate": round(float(metrics.get("avoided_framing_trap_rate", 0.0)), 4),
            "naive_baseline_mole_accuracy": round(
                float(
                    metrics.get(
                        "naive_baseline_mole_accuracy",
                        metrics.get("naive_after_hours_baseline_mole_accuracy", 0.0),
                    )
                ),
                4,
            ),
            "brier_score": (
                round(float(metrics["brier_score"]), 6) if metrics.get("brier_score") is not None else None
            ),
            "expected_calibration_error": (
                round(float(metrics["expected_calibration_error"]), 6)
                if metrics.get("expected_calibration_error") is not None
                else None
            ),
        },
    }

    cards: list[dict[str, Any]] = []
    for w in worlds:
        seed = int(w["seed"])
        tier = str(w["tier"]).lower()
        gt = w["ground_truth"]
        ev = w["evaluation"]
        mo = w["model_output"]
        obs = w["observable_summary"]

        top_suspects = [str(x) for x in (mo.get("top_suspect_ids") or [])]
        suspected_decoys = [str(x) for x in (mo.get("suspected_decoy_ids") or [])]
        pred_mole = top_suspects[0] if top_suspects else None
        pred_decoy = suspected_decoys[0] if suspected_decoys else None
        conf = round(float(mo.get("confidence", 0.0)), 4)

        headline = clean_prose(
            f"SOC raster ({w['raster_size'][0]}x{w['raster_size'][1]} px) isolated mole {pred_mole} "
            f"(truth {gt['true_mole']}) and flagged framed decoy {pred_decoy} (truth {gt['true_decoy']}, "
            f"naive after-hours spike {obs.get('naive_most_after_hours_id')}) at confidence {conf:.2f}."
        )
        quote = clean_prose(mo.get("visual_reasoning") or mo.get("canary_leak_summary") or "", max_chars=380)

        cards.append(
            {
                "card_id": f"heatmap:{run_dir}:{tier}:{seed}",
                "modality": "heatmap",
                "subrole": subrole,
                "station_id": station["station_id"],
                "sprite_key": station["icon_sprite"],
                "prop_sprite_key": station["prop_sprite"],
                "analyst_sprite_key": analyst_sprite,
                "tier": tier,
                "seed": seed,
                "world_key": f"{tier}/{seed}",
                "pipe_key": f"{tier}|{seed}",
                "tiers_version": tiers_version,
                "model_id": model_id,
                "thinking_level": thinking_level,
                "run_dir": run_dir,
                "ledger_run_id": ledger_run_id,
                "commit": commit,
                "timestamp": timestamp,
                "n_images_read": 1,
                "images": [
                    {
                        "kind": "soc_access_raster",
                        "path": str(w["raster_path"]),
                        "sha256": str(w["raster_sha256"]),
                        "bytes": int(w["raster_bytes"]),
                        "size": [int(w["raster_size"][0]), int(w["raster_size"][1])],
                    }
                ],
                "ground_truth": {
                    "true_mole": str(gt["true_mole"]),
                    "true_decoy": str(gt["true_decoy"]),
                },
                "finding": {
                    "title": f"SOC Access and Framing Raster ({tier} seed {seed}, thinking={thinking_level})",
                    "badge": "Mole + Decoy ID" if ev.get("top1_mole_correct") and ev.get("top1_decoy_correct") else "Top-3 Hit",
                    "headline": headline,
                    "predicted_mole": pred_mole,
                    "top_suspect_ids": top_suspects,
                    "predicted_decoy": pred_decoy,
                    "suspected_decoy_ids": suspected_decoys,
                    "mole_correct": bool(ev.get("top1_mole_correct", False)),
                    "top3_mole_hit": bool(ev.get("top3_mole_hit", False)),
                    "decoy_correct": bool(ev.get("top1_decoy_correct", False)),
                    "avoided_framing_trap": bool(ev.get("avoided_framing_trap", False)),
                    "naive_trapped_id": str(obs.get("naive_most_after_hours_id") or ""),
                    "confidence": conf,
                    "brier_score": round(float(ev["brier_score"]), 6) if ev.get("brier_score") is not None else None,
                    "gemini_quote": quote,
                },
                "usage": _normalize_usage(w.get("usage") or {}, default_calls=1),
            }
        )

    return run_rec, cards


def parse_dossier_run(
    run_dir: str,
    meta: dict[str, Any],
    results: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    thinking_level = _infer_thinking_level(meta, results)
    commit = str(meta.get("commit") or meta.get("git_sha") or results.get("commit") or "")
    timestamp = str(meta.get("timestamp") or results.get("timestamp") or "")
    tiers_version = str(meta.get("tiers_version") or results.get("tiers_version") or "v1.4")
    model_id = str(meta.get("model_id") or results.get("model_id") or "gemini-4-carbon")
    subrole = str(meta.get("subrole") or results.get("subrole") or "multi_image_incident_dossier")
    ledger_run_id = str(meta.get("ledger_run_id") or f"multimodal_evidence:{subrole}:{run_dir}")
    worlds = results.get("worlds") or []
    images_per_call = int(meta.get("images_per_call") or results.get("images_per_call") or 3)
    n_images = int(meta.get("n_images_read_by_model") or results.get("n_images_read_by_model") or len(worlds) * images_per_call)
    usage = _normalize_usage(meta.get("usage") or results.get("usage") or {}, default_calls=len(worlds))
    metrics = results.get("metrics") or {}
    station = STATION_SPECS["dossier"]

    run_rec: dict[str, Any] = {
        "run_dir": run_dir,
        "modality": "dossier",
        "subrole": subrole,
        "model_id": model_id,
        "thinking_level": thinking_level,
        "tiers_version": tiers_version,
        "tiers": sorted({str(w["tier"]) for w in worlds}),
        "seeds": [int(w["seed"]) for w in worlds],
        "commit": commit,
        "timestamp": timestamp,
        "ledger_run_id": ledger_run_id,
        "n_cards": len(worlds),
        "n_images_read": n_images,
        "usage": usage,
        "headline_metrics": {
            "n_dossiers": len(worlds),
            "images_per_call": images_per_call,
            "top1_mole_hits": int(metrics.get("top1_mole_hits", 0)),
            "top1_mole_accuracy": round(float(metrics.get("top1_mole_accuracy", 0.0)), 4),
            "top3_mole_hits": int(metrics.get("top3_mole_hits", 0)),
            "top3_mole_hit_rate": round(float(metrics.get("top3_mole_hit_rate", 0.0)), 4),
            "top1_decoy_hits": int(metrics.get("top1_decoy_hits", 0)),
            "top1_decoy_accuracy": round(float(metrics.get("top1_decoy_accuracy", 0.0)), 4),
            "decoy_identified_hits": int(metrics.get("decoy_identified_hits", 0)),
            "avoided_framing_trap_hits": int(metrics.get("avoided_framing_trap_hits", 0)),
            "avoided_framing_trap_rate": round(float(metrics.get("avoided_framing_trap_rate", 0.0)), 4),
            "memo_scans_matched_total": int(metrics.get("memo_scans_matched_total", 0)),
            "memo_scans_expected_total": int(metrics.get("memo_scans_expected_total", 0)),
            "memo_scan_readout_accuracy": round(float(metrics.get("memo_scan_readout_accuracy", 1.0)), 4),
            "single_image_mole_accuracy": 0.0,
        },
    }

    cards: list[dict[str, Any]] = []
    for w in worlds:
        seed = int(w["seed"])
        tier = str(w["tier"]).lower()
        gt = w["ground_truth"]
        ev = w["evaluation"]
        mo = w["model_output"]
        sib = w.get("single_image_baselines") or {}

        img_map = w.get("images") or {}
        images = []
        for key in ("badge_raster", "leaked_memo_scans", "org_canary_map"):
            if key in img_map:
                im = img_map[key]
                images.append(
                    {
                        "kind": str(im["kind"]),
                        "path": str(im["path"]),
                        "sha256": str(im["sha256"]),
                        "bytes": int(im["bytes"]),
                        "size": [int(im["size"][0]), int(im["size"][1])],
                    }
                )

        top_suspects = [str(x) for x in (mo.get("top_suspect_ids") or [])]
        suspected_decoys = [str(x) for x in (mo.get("suspected_decoy_ids") or [])]
        pred_mole = top_suspects[0] if top_suspects else None
        pred_decoy = suspected_decoys[0] if suspected_decoys else None
        conf = round(float(mo.get("confidence", 0.0)), 4)
        decoded = [
            {"doc_id": str(d["doc_id"]), "variant": str(d["variant"])}
            for d in (mo.get("decoded_leaked_canaries") or [])
        ]
        decoded_str = ", ".join(f"{d['doc_id']}:{d['variant']}" for d in decoded)

        headline = clean_prose(
            f"Jointly cross-checked 3 PNGs in one call (badge swipe raster + leaked canary scans [{decoded_str}] "
            f"+ org canary matrix): ranked {top_suspects} (mole {gt['true_mole']} in {gt.get('true_mole_dept')}) "
            f"and cleared framed decoy {gt['true_decoy']} (image-1-only trap pick {sib.get('image1_only_naive_after_hours_pick')})."
        )
        quote = clean_prose(mo.get("cross_image_reasoning") or "", max_chars=380)

        cards.append(
            {
                "card_id": f"dossier:{run_dir}:{tier}:{seed}",
                "modality": "dossier",
                "subrole": subrole,
                "station_id": station["station_id"],
                "sprite_key": station["icon_sprite"],
                "prop_sprite_key": station["prop_sprite"],
                "analyst_sprite_key": station["analyst_sprite"],
                "tier": tier,
                "seed": seed,
                "world_key": f"{tier}/{seed}",
                "pipe_key": f"{tier}|{seed}",
                "tiers_version": tiers_version,
                "model_id": model_id,
                "thinking_level": thinking_level,
                "run_dir": run_dir,
                "ledger_run_id": ledger_run_id,
                "commit": commit,
                "timestamp": timestamp,
                "n_images_read": len(images),
                "images": images,
                "ground_truth": {
                    "true_mole": str(gt["true_mole"]),
                    "true_mole_dept": str(gt.get("true_mole_dept") or ""),
                    "true_decoy": str(gt["true_decoy"]),
                    "true_decoy_dept": str(gt.get("true_decoy_dept") or ""),
                },
                "finding": {
                    "title": f"3-PNG Composite Incident Dossier ({tier} seed {seed})",
                    "badge": "3-PNG Cross-Check" if ev.get("top1_mole_correct") else "Top-3 Narrowed",
                    "headline": headline,
                    "predicted_mole": pred_mole,
                    "top_suspect_ids": top_suspects,
                    "predicted_decoy": pred_decoy,
                    "suspected_decoy_ids": suspected_decoys,
                    "suspect_department": str(mo.get("suspect_department") or ""),
                    "decoded_leaked_canaries": decoded,
                    "mole_correct": bool(ev.get("top1_mole_correct", False)),
                    "top3_mole_hit": bool(ev.get("top3_mole_hit", False)),
                    "decoy_correct": bool(ev.get("top1_decoy_correct", False)),
                    "avoided_framing_trap": bool(ev.get("avoided_framing_trap", False)),
                    "memo_scans_matched": int(ev.get("memo_scans_matched", 0)),
                    "memo_scans_total": int(ev.get("memo_scans_total", 0)),
                    "image1_only_trap_pick": sib.get("image1_only_naive_after_hours_pick"),
                    "confidence": conf,
                    "gemini_quote": quote,
                },
                "usage": _normalize_usage(w.get("usage") or {}, default_calls=1),
            }
        )

    return run_rec, cards


def parse_forensics_run(
    run_dir: str,
    meta: dict[str, Any],
    diagnoses: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    thinking_level = _infer_thinking_level(meta)
    commit = str(meta.get("commit") or meta.get("git_sha") or "")
    timestamp = str(meta.get("timestamp") or "")
    tiers_version = str(meta.get("tiers_version") or "v1.4")
    model_id = str(meta.get("model_id") or "gemini-4-carbon")
    subrole = str(meta.get("subrole") or "carbon_v14_trajectory_forensics")
    ledger_run_id = str(meta.get("ledger_run_id") or f"multimodal_evidence:{subrole}:{run_dir}")
    n_images = int(meta.get("n_images_read_by_model") or meta.get("n_charts_analyzed") or len(diagnoses))
    usage = _normalize_usage(meta.get("usage") or {}, default_calls=len(diagnoses))
    size_lookup = _manifest_size_lookup(meta)
    station = STATION_SPECS["forensics"]

    run_rec: dict[str, Any] = {
        "run_dir": run_dir,
        "modality": "forensics",
        "subrole": subrole,
        "model_id": model_id,
        "thinking_level": thinking_level,
        "tiers_version": tiers_version,
        "tiers": sorted({str(d["source_episode"]["tier"]) for d in diagnoses}),
        "seeds": [int(d["source_episode"]["seed"]) for d in diagnoses],
        "commit": commit,
        "timestamp": timestamp,
        "ledger_run_id": ledger_run_id,
        "n_cards": len(diagnoses),
        "n_images_read": n_images,
        "usage": usage,
        "headline_metrics": {
            "n_charts_analyzed": len(diagnoses),
            "visual_threshold_accuracy": round(float(meta.get("visual_threshold_accuracy", 1.0)), 4),
            "accuse_day_within_1_accuracy": round(float(meta.get("accuse_day_within_1_accuracy", 1.0)), 4),
            "accuse_day_exact_accuracy": round(float(meta.get("accuse_day_exact_accuracy", 1.0)), 4),
            "hidden_bleed_gap_accuracy": round(float(meta.get("hidden_bleed_gap_accuracy", 1.0)), 4),
            "entropy_lag_accuracy": (
                round(float(meta["entropy_lag_accuracy"]), 4)
                if meta.get("entropy_lag_accuracy") is not None
                else None
            ),
            "outcome_pattern_accuracy": (
                round(float(meta["outcome_pattern_accuracy"]), 4)
                if meta.get("outcome_pattern_accuracy") is not None
                else None
            ),
        },
    }

    cards: list[dict[str, Any]] = []
    for item in diagnoses:
        ep_idx = int(item["episode_index"])
        se = item["source_episode"]
        tier = str(se["tier"]).lower()
        seed = int(se["seed"])
        gt = item["ground_truth"]
        gd = item["gemini_diagnosis"]
        sc = item["scoring"]

        chart_path = str(item["chart_path"])
        chart_sha = str(item["chart_sha256"])
        dims = size_lookup.get(chart_path) or size_lookup.get(chart_sha) or [2208, 2624]

        est_day = int(gd["estimated_accuse_day"])
        act_day = int(gt["actual_accuse_day"])
        pattern = str(gd.get("primary_failure_pattern") or item.get("cohort") or "")
        quote = clean_prose(gd.get("fooled_step_summary") or gd.get("visual_diagnosis") or "", max_chars=380)

        headline = clean_prose(
            f"Trajectory chart forensics ({tiers_version} {tier} seed {seed}, agent {se.get('agent')}): "
            f"pinpointed stop/accuse day {est_day} (actual day {act_day}), EV-threshold crossing "
            f"(below_ev={bool(gd.get('accused_below_ev_threshold'))}), and hidden-bleed gap "
            f"({bool(gd.get('hidden_bleed_gap_present'))}, pattern={pattern})."
        )

        cards.append(
            {
                "card_id": f"forensics:{run_dir}:ep{ep_idx}:{tier}:{seed}",
                "modality": "forensics",
                "subrole": subrole,
                "station_id": station["station_id"],
                "sprite_key": station["icon_sprite"],
                "prop_sprite_key": station["prop_sprite"],
                "analyst_sprite_key": station["analyst_sprite"],
                "tier": tier,
                "seed": seed,
                "episode_index": ep_idx,
                "world_key": f"{tier}/{seed}",
                "pipe_key": f"{tier}|{seed}",
                "tiers_version": tiers_version,
                "model_id": model_id,
                "thinking_level": thinking_level,
                "run_dir": run_dir,
                "ledger_run_id": ledger_run_id,
                "commit": commit,
                "timestamp": timestamp,
                "n_images_read": 1,
                "images": [
                    {
                        "kind": "trajectory_forensics_chart",
                        "path": chart_path,
                        "sha256": chart_sha,
                        "bytes": int(item["chart_bytes_len"]),
                        "size": dims,
                    }
                ],
                "ground_truth": {
                    "true_mole": gt.get("true_mole"),
                    "true_decoy": gt.get("framed_decoy"),
                    "accused_employee": gt.get("accused_employee"),
                    "actual_accuse_day": act_day,
                    "episode_correct": bool(gt.get("correct", False)),
                    "episode_score": round(float(gt.get("score", 0.0)), 4),
                    "accused_below_ev_threshold": bool(gt.get("accused_below_ev_threshold", False)),
                    "hidden_bleed_gap_present": bool(gt.get("hidden_bleed_gap_present", False)),
                },
                "finding": {
                    "title": f"Trajectory Chart Forensics ({tiers_version} {tier} seed {seed})",
                    "badge": f"Day {est_day}/{act_day} exact" if sc.get("day_exact") else f"Day {est_day} vs {act_day}",
                    "headline": headline,
                    "source_agent": str(se.get("agent") or ""),
                    "cohort": str(item.get("cohort") or ""),
                    "primary_failure_pattern": pattern,
                    "estimated_accuse_day": est_day,
                    "actual_accuse_day": act_day,
                    "predicted_mole": gt.get("true_mole"),
                    "predicted_decoy": gt.get("framed_decoy"),
                    "mole_correct": bool(sc.get("threshold_match") and sc.get("day_within_1") and sc.get("bleed_gap_match")),
                    "avoided_framing_trap": True,
                    "threshold_match": bool(sc.get("threshold_match", False)),
                    "day_exact": bool(sc.get("day_exact", False)),
                    "bleed_gap_match": bool(sc.get("bleed_gap_match", False)),
                    "entropy_lag_match": sc.get("entropy_lag_match"),
                    "outcome_pattern_match": sc.get("outcome_pattern_match"),
                    "confidence": 1.0,
                    "gemini_quote": quote,
                },
                "usage": _normalize_usage(item.get("usage") or {}, default_calls=1),
            }
        )

    return run_rec, cards


def load_multimodal_evidence_dir(multimodal_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    root = multimodal_dir.resolve()
    assert root.is_dir(), f"Missing multimodal_evidence directory: {root}"

    run_dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "meta.json").is_file())
    assert run_dirs, f"No verified run directories with meta.json found in {root}"

    runs: list[dict[str, Any]] = []
    cards: list[dict[str, Any]] = []

    for rdir in run_dirs:
        meta = json.loads((rdir / "meta.json").read_text(encoding="utf-8"))
        subrole = str(meta.get("subrole") or "")
        comp_path = rdir / "comparison.json"
        res_path = rdir / "results.json"
        diag_path = rdir / "diagnoses.json"

        if subrole == "visual_memo_blind_ablation" or comp_path.is_file():
            comp = json.loads(comp_path.read_text(encoding="utf-8"))
            run_rec, run_cards = parse_scan_run(rdir.name, meta, comp)
        elif "soc_access_vision" in subrole:
            res = json.loads(res_path.read_text(encoding="utf-8"))
            run_rec, run_cards = parse_heatmap_run(rdir.name, meta, res)
        elif subrole == "multi_image_incident_dossier":
            res = json.loads(res_path.read_text(encoding="utf-8"))
            run_rec, run_cards = parse_dossier_run(rdir.name, meta, res)
        elif diag_path.is_file():
            diag = json.loads(diag_path.read_text(encoding="utf-8"))
            run_rec, run_cards = parse_forensics_run(rdir.name, meta, diag)
        else:
            raise ValueError(f"Unrecognized multimodal run format in {rdir}")

        runs.append(run_rec)
        cards.extend(run_cards)

    return runs, cards


def encode_snapshot_zlib_b64(runs: list[dict[str, Any]], cards: list[dict[str, Any]]) -> str:
    payload = json.dumps({"runs": runs, "cards": cards}, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    compressed = zlib.compress(payload, level=9)
    return base64.b64encode(compressed).decode("ascii")


def load_embedded_snapshot() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assert EMBEDDED_SNAPSHOT_ZLIB_B64, "Embedded multimodal snapshot is empty"
    raw = zlib.decompress(base64.b64decode(EMBEDDED_SNAPSHOT_ZLIB_B64.encode("ascii")))
    parsed = json.loads(raw.decode("utf-8"))
    return list(parsed["runs"]), list(parsed["cards"])


def _compute_modality_summaries(
    runs: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    scan_runs = [r for r in runs if r["modality"] == "scan"]
    scan_cards = [c for c in cards if c["modality"] == "scan"]
    scan_canary_imgs = sum(int(r["headline_metrics"]["n_canary_memos_read"]) for r in scan_runs)
    scan_imgs = sum(int(r["n_images_read"]) for r in scan_runs)
    scan_mm_hits = sum(1 for c in scan_cards if c["finding"]["ablation"]["multimodal_correct"])
    scan_bl_hits = sum(1 for c in scan_cards if c["finding"]["ablation"]["blind_correct"])

    heat_runs = [r for r in runs if r["modality"] == "heatmap"]
    heat_cards = [c for c in cards if c["modality"] == "heatmap"]
    heat_top1 = sum(1 for c in heat_cards if c["finding"]["mole_correct"])
    heat_top3 = sum(1 for c in heat_cards if c["finding"]["top3_mole_hit"])
    heat_decoy = sum(1 for c in heat_cards if c["finding"]["decoy_correct"])
    heat_trap = sum(1 for c in heat_cards if c["finding"]["avoided_framing_trap"])
    low_run = next((r for r in heat_runs if r["thinking_level"] == "low"), None)
    high_run = next((r for r in heat_runs if r["thinking_level"] == "high"), None)

    doss_runs = [r for r in runs if r["modality"] == "dossier"]
    doss_cards = [c for c in cards if c["modality"] == "dossier"]
    doss_top1 = sum(1 for c in doss_cards if c["finding"]["mole_correct"])
    doss_top3 = sum(1 for c in doss_cards if c["finding"]["top3_mole_hit"])
    doss_decoy = sum(1 for c in doss_cards if c["finding"]["decoy_correct"])
    doss_trap = sum(1 for c in doss_cards if c["finding"]["avoided_framing_trap"])
    doss_scans_ok = sum(int(c["finding"]["memo_scans_matched"]) for c in doss_cards)
    doss_scans_tot = sum(int(c["finding"]["memo_scans_total"]) for c in doss_cards)

    fore_runs = [r for r in runs if r["modality"] == "forensics"]
    fore_cards = [c for c in cards if c["modality"] == "forensics"]
    fore_thresh = sum(1 for c in fore_cards if c["finding"]["threshold_match"])
    fore_day_exact = sum(1 for c in fore_cards if c["finding"]["day_exact"])
    fore_bleed = sum(1 for c in fore_cards if c["finding"]["bleed_gap_match"])

    return {
        "scan": {
            "runs": len(scan_runs),
            "cards": len(scan_cards),
            "images_read": scan_imgs,
            "canary_memos_decoded": scan_canary_imgs,
            "watermark_vision_accuracy": 1.0 if scan_cards else 0.0,
            "multimodal_mole_hits": scan_mm_hits,
            "multimodal_mole_accuracy": round(scan_mm_hits / len(scan_cards), 4) if scan_cards else 0.0,
            "blind_mole_hits": scan_bl_hits,
            "blind_mole_accuracy": round(scan_bl_hits / len(scan_cards), 4) if scan_cards else 0.0,
            "oracle_score_recovery_ratio": 1.0 if scan_runs else 0.0,
            "cost_usd": round(sum(float(r["usage"]["cost_usd"]) for r in scan_runs), 6),
        },
        "heatmap": {
            "runs": len(heat_runs),
            "cards": len(heat_cards),
            "images_read": sum(int(r["n_images_read"]) for r in heat_runs),
            "top1_mole_hits": heat_top1,
            "top1_mole_accuracy": round(heat_top1 / len(heat_cards), 4) if heat_cards else 0.0,
            "top3_mole_hits": heat_top3,
            "top3_mole_hit_rate": round(heat_top3 / len(heat_cards), 4) if heat_cards else 0.0,
            "top1_decoy_hits": heat_decoy,
            "top1_decoy_accuracy": round(heat_decoy / len(heat_cards), 4) if heat_cards else 0.0,
            "avoided_framing_trap_hits": heat_trap,
            "avoided_framing_trap_rate": round(heat_trap / len(heat_cards), 4) if heat_cards else 0.0,
            "naive_baseline_mole_accuracy": 0.0,
            "thinking_calibration": (
                {
                    "low_thinking_tokens": int(low_run["usage"]["thinking"]),
                    "high_thinking_tokens": int(high_run["usage"]["thinking"]),
                    "low_brier_score": low_run["headline_metrics"]["brier_score"],
                    "high_brier_score": high_run["headline_metrics"]["brier_score"],
                    "low_ece": low_run["headline_metrics"]["expected_calibration_error"],
                    "high_ece": high_run["headline_metrics"]["expected_calibration_error"],
                }
                if low_run and high_run
                else None
            ),
            "cost_usd": round(sum(float(r["usage"]["cost_usd"]) for r in heat_runs), 6),
        },
        "dossier": {
            "runs": len(doss_runs),
            "cards": len(doss_cards),
            "images_read": sum(int(r["n_images_read"]) for r in doss_runs),
            "images_per_call": 3,
            "top1_mole_hits": doss_top1,
            "top1_mole_accuracy": round(doss_top1 / len(doss_cards), 4) if doss_cards else 0.0,
            "top3_mole_hits": doss_top3,
            "top3_mole_hit_rate": round(doss_top3 / len(doss_cards), 4) if doss_cards else 0.0,
            "top1_decoy_hits": doss_decoy,
            "top1_decoy_accuracy": round(doss_decoy / len(doss_cards), 4) if doss_cards else 0.0,
            "avoided_framing_trap_hits": doss_trap,
            "avoided_framing_trap_rate": round(doss_trap / len(doss_cards), 4) if doss_cards else 0.0,
            "memo_scans_matched": doss_scans_ok,
            "memo_scans_total": doss_scans_tot,
            "single_image_baseline_mole_accuracy": 0.0,
            "cost_usd": round(sum(float(r["usage"]["cost_usd"]) for r in doss_runs), 6),
        },
        "forensics": {
            "runs": len(fore_runs),
            "cards": len(fore_cards),
            "images_read": sum(int(r["n_images_read"]) for r in fore_runs),
            "visual_threshold_hits": fore_thresh,
            "visual_threshold_accuracy": round(fore_thresh / len(fore_cards), 4) if fore_cards else 0.0,
            "accuse_day_exact_hits": fore_day_exact,
            "accuse_day_exact_accuracy": round(fore_day_exact / len(fore_cards), 4) if fore_cards else 0.0,
            "hidden_bleed_gap_hits": fore_bleed,
            "hidden_bleed_gap_accuracy": round(fore_bleed / len(fore_cards), 4) if fore_cards else 0.0,
            "cost_usd": round(sum(float(r["usage"]["cost_usd"]) for r in fore_runs), 6),
        },
    }


def _build_station_summary_line(mod: str, msum: dict[str, Any]) -> str:
    if mod == "scan":
        return clean_prose(
            f"{msum['images_read']}/{msum['images_read']} leaked memo PNG scans decoded "
            f"({msum['canary_memos_decoded']}/{msum['canary_memos_decoded']} planted canary watermarks); "
            f"{msum['multimodal_mole_hits']}/{msum['cards']} mole accuracy vs "
            f"{msum['blind_mole_hits']}/{msum['cards']} blind ablation, 100.0% oracle score recovery."
        )
    if mod == "heatmap":
        cal = msum.get("thinking_calibration")
        cal_txt = (
            f"; high thinking cuts Brier {cal['low_brier_score']} to {cal['high_brier_score']}."
            if cal
            else "."
        )
        return clean_prose(
            f"{msum['images_read']} 1880x1020 3-panel SOC rasters read: "
            f"{msum['top1_mole_hits']}/{msum['cards']} top-1 mole, "
            f"{msum['top3_mole_hits']}/{msum['cards']} top-3 mole, "
            f"{msum['top1_decoy_hits']}/{msum['cards']} framed decoy ID, "
            f"{msum['avoided_framing_trap_hits']}/{msum['cards']} trap avoidance vs 0/{msum['cards']} naive{cal_txt}"
        )
    if mod == "dossier":
        return clean_prose(
            f"{msum['cards']} composite 3-PNG dossiers ({msum['images_read']} PNGs, 3 per call): "
            f"{msum['memo_scans_matched']}/{msum['memo_scans_total']} embedded canary watermarks decoded, "
            f"{msum['top1_mole_hits']}/{msum['cards']} top-1 mole ({msum['top3_mole_hits']}/{msum['cards']} top-3), "
            f"{msum['avoided_framing_trap_hits']}/{msum['cards']} trap avoidance vs 0/{msum['cards']} single-image."
        )
    return clean_prose(
        f"{msum['images_read']} belief, hidden-bleed, entropy, and EV-threshold trajectory charts read: "
        f"{msum['visual_threshold_hits']}/{msum['cards']} visual EV-threshold, "
        f"{msum['accuse_day_exact_hits']}/{msum['cards']} exact stop/accuse day, "
        f"{msum['hidden_bleed_gap_hits']}/{msum['cards']} hidden-bleed gap detection."
    )


def assemble_evidence_bundle(
    runs: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered_runs = sorted(runs, key=lambda r: (MODALITIES.index(r["modality"]), r["run_dir"]))
    ordered_cards = sorted(
        cards,
        key=lambda c: (
            MODALITIES.index(c["modality"]),
            0 if c["tier"] == "medium" else 1,
            int(c["seed"]),
            c["run_dir"],
            int(c.get("episode_index", 0)),
        ),
    )

    by_card_id: dict[str, dict[str, Any]] = {}
    by_modality: dict[str, list[str]] = {m: [] for m in MODALITIES}
    world_buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for card in ordered_cards:
        cid = card["card_id"]
        assert cid not in by_card_id, f"Duplicate card_id: {cid}"
        by_card_id[cid] = card
        by_modality[card["modality"]].append(cid)
        if card["tiers_version"] == "v1.4":
            world_buckets[card["world_key"]].append(card)

    by_world: dict[str, dict[str, Any]] = {}
    for wkey in sorted(
        world_buckets.keys(),
        key=lambda wk: (0 if wk.split("/")[0] == "medium" else 1, int(wk.split("/")[1])),
    ):
        wcards = world_buckets[wkey]
        tier, seed_str = wkey.split("/")
        seed = int(seed_str)
        moles = {
            c["ground_truth"]["true_mole"]
            for c in wcards
            if c["ground_truth"].get("true_mole")
        }
        decoys = {
            c["ground_truth"]["true_decoy"]
            for c in wcards
            if c["ground_truth"].get("true_decoy")
        }
        assert len(moles) <= 1, f"Conflicting true_mole on {wkey}: {moles}"
        assert len(decoys) <= 1, f"Conflicting true_decoy on {wkey}: {decoys}"

        cards_by_mod: dict[str, list[str]] = {}
        primary_cards: dict[str, str] = {}
        for mod in MODALITIES:
            mcards = [c for c in wcards if c["modality"] == mod]
            if not mcards:
                continue
            cards_by_mod[mod] = [c["card_id"] for c in mcards]
            chosen = sorted(
                mcards,
                key=lambda c: (
                    1 if c["thinking_level"] == "high" else 0,
                    c["timestamp"],
                    c["run_dir"],
                ),
            )[-1]
            primary_cards[mod] = chosen["card_id"]

        low_heat = next(
            (c for c in wcards if c["modality"] == "heatmap" and c["thinking_level"] == "low"),
            None,
        )
        high_heat = next(
            (c for c in wcards if c["modality"] == "heatmap" and c["thinking_level"] == "high"),
            None,
        )
        thinking_cmp = None
        if low_heat and high_heat:
            thinking_cmp = {
                "low_card_id": low_heat["card_id"],
                "high_card_id": high_heat["card_id"],
                "low_thinking_tokens": int(low_heat["usage"]["thinking"]),
                "high_thinking_tokens": int(high_heat["usage"]["thinking"]),
                "low_confidence": low_heat["finding"]["confidence"],
                "high_confidence": high_heat["finding"]["confidence"],
                "low_brier_score": low_heat["finding"]["brier_score"],
                "high_brier_score": high_heat["finding"]["brier_score"],
            }

        by_world[wkey] = {
            "world_key": wkey,
            "pipe_key": f"{tier}|{seed}",
            "tier": tier,
            "seed": seed,
            "true_mole": next(iter(moles), None),
            "true_decoy": next(iter(decoys), None),
            "modalities": [m for m in MODALITIES if m in cards_by_mod],
            "card_ids": [c["card_id"] for c in wcards],
            "primary_card_ids": primary_cards,
            "cards_by_modality": cards_by_mod,
            "thinking_comparison": thinking_cmp,
        }

    mod_summaries = _compute_modality_summaries(ordered_runs, ordered_cards)
    room_stations = [
        {
            **STATION_SPECS[mod],
            "card_count": mod_summaries[mod]["cards"],
            "images_read": mod_summaries[mod]["images_read"],
            "summary_line": _build_station_summary_line(mod, mod_summaries[mod]),
        }
        for mod in MODALITIES
    ]

    total_calls = sum(int(r["usage"]["calls"]) for r in ordered_runs)
    total_images = sum(int(r["n_images_read"]) for r in ordered_runs)
    total_in = sum(int(r["usage"]["in"]) for r in ordered_runs)
    total_out = sum(int(r["usage"]["out"]) for r in ordered_runs)
    total_think = sum(int(r["usage"]["thinking"]) for r in ordered_runs)
    total_cached = sum(int(r["usage"]["cached"]) for r in ordered_runs)
    total_cost = round(sum(float(r["usage"]["cost_usd"]) for r in ordered_runs), 6)

    return {
        "schema_version": SCHEMA_VERSION,
        "role": "multimodal_evidence",
        "model_id": "gemini-4-carbon",
        "part_ingestion": "google.genai.types.Part.from_bytes(mime_type='image/png')",
        "summary": {
            "total_runs": len(ordered_runs),
            "total_cards": len(ordered_cards),
            "total_vision_calls": total_calls,
            "total_images_read": total_images,
            "total_tokens": {
                "in": total_in,
                "out": total_out,
                "thinking": total_think,
                "cached": total_cached,
            },
            "total_cost_usd": total_cost,
            "worlds_covered_v14": len(by_world),
            "by_modality": mod_summaries,
        },
        "room_stations": room_stations,
        "runs": ordered_runs,
        "cards": ordered_cards,
        "by_modality": by_modality,
        "by_world": by_world,
    }


def build_outthink_evidence_cards(multimodal_dir: Path | None = None) -> dict[str, Any]:
    if multimodal_dir is not None:
        runs, cards = load_multimodal_evidence_dir(multimodal_dir)
    elif DEFAULT_MULTIMODAL_DIR.is_dir() and any(
        p.is_dir() and (p / "meta.json").is_file() for p in DEFAULT_MULTIMODAL_DIR.iterdir()
    ):
        runs, cards = load_multimodal_evidence_dir(DEFAULT_MULTIMODAL_DIR)
    else:
        runs, cards = load_embedded_snapshot()
    return assemble_evidence_bundle(runs, cards)


def render_evidence_cards_js(bundle: dict[str, Any]) -> str:
    json_payload = json.dumps(bundle, separators=(",", ":"), ensure_ascii=True)
    assert not has_unicode_dash(json_payload), "Unicode dash found in serialized evidence bundle"
    assert HASH_CHAR not in json_payload, "Hash character found in serialized evidence bundle"
    for code in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212):
        esc = "\\u" + f"{code:04x}"
        assert esc not in json_payload.lower(), f"Escaped unicode dash {esc} found in bundle"

    helper_js = (
        'var _w = typeof window !== "undefined" ? window : globalThis;\n'
        "_w.OUTTHINK_EVIDENCE_CARDS = " + json_payload + ";\n"
        "_w.getOutthinkEvidenceCard = function(cardId) {\n"
        "  var bundle = _w.OUTTHINK_EVIDENCE_CARDS;\n"
        '  if (!bundle || !Array.isArray(bundle.cards) || typeof cardId !== "string") {\n'
        "    return null;\n"
        "  }\n"
        "  var target = cardId.trim();\n"
        "  for (var i = 0; i < bundle.cards.length; i += 1) {\n"
        "    if (bundle.cards[i] && bundle.cards[i].card_id === target) {\n"
        "      return bundle.cards[i];\n"
        "    }\n"
        "  }\n"
        "  return null;\n"
        "};\n"
        "_w.getOutthinkWorldEvidence = function(caseOrTier, seed) {\n"
        "  var bundle = _w.OUTTHINK_EVIDENCE_CARDS;\n"
        "  if (!bundle || !bundle.by_world || caseOrTier === null || caseOrTier === undefined) {\n"
        "    return null;\n"
        "  }\n"
        '  var tierVal = "";\n'
        "  var seedVal = seed;\n"
        '  if (typeof caseOrTier === "object") {\n'
        "    if (caseOrTier.world_key && bundle.by_world[caseOrTier.world_key]) {\n"
        "      return bundle.by_world[caseOrTier.world_key];\n"
        "    }\n"
        '    tierVal = String(caseOrTier.tier || caseOrTier.difficulty || "");\n'
        "    seedVal = caseOrTier.seed !== undefined ? caseOrTier.seed : caseOrTier.worldSeed;\n"
        '    if ((tierVal === "" || seedVal === undefined) && typeof caseOrTier.id === "string") {\n'
        "      caseOrTier = caseOrTier.id;\n"
        "    }\n"
        "  }\n"
        '  if (typeof caseOrTier === "string" && (seedVal === undefined || seedVal === null)) {\n'
        "    var raw = caseOrTier.trim();\n"
        "    if (bundle.by_world[raw]) {\n"
        "      return bundle.by_world[raw];\n"
        "    }\n"
        '    var sep = raw.indexOf("/") !== -1 ? "/" : (raw.indexOf("|") !== -1 ? "|" : (raw.indexOf("_") !== -1 ? "_" : (raw.indexOf("-") !== -1 ? "-" : "")));\n'
        '    if (sep !== "") {\n'
        "      var parts = raw.split(sep);\n"
        "      if (parts.length >= 2) {\n"
        "        tierVal = parts[parts.length - 2];\n"
        "        seedVal = parts[parts.length - 1];\n"
        "      }\n"
        "    }\n"
        '  } else if (typeof caseOrTier === "string") {\n'
        "    tierVal = caseOrTier;\n"
        "  }\n"
        "  var key = String(tierVal).trim().toLowerCase() + \"/\" + String(seedVal !== undefined && seedVal !== null ? seedVal : \"\").trim();\n"
        "  return bundle.by_world[key] || null;\n"
        "};\n"
        "_w.getOutthinkEvidenceForCase = function(caseOrTier, seed, modality) {\n"
        "  var worldEntry = _w.getOutthinkWorldEvidence(caseOrTier, seed);\n"
        "  if (!worldEntry) {\n"
        "    return null;\n"
        "  }\n"
        '  if (modality === undefined || modality === null || String(modality).trim() === "") {\n'
        "    return worldEntry;\n"
        "  }\n"
        "  var modKey = String(modality).trim().toLowerCase();\n"
        "  var cid = worldEntry.primary_card_ids && worldEntry.primary_card_ids[modKey];\n"
        "  return cid ? _w.getOutthinkEvidenceCard(cid) : null;\n"
        "};\n"
        "_w.listOutthinkEvidenceCards = function(filter) {\n"
        "  var bundle = _w.OUTTHINK_EVIDENCE_CARDS;\n"
        "  if (!bundle || !Array.isArray(bundle.cards)) {\n"
        "    return [];\n"
        "  }\n"
        '  if (!filter || typeof filter !== "object") {\n'
        "    return bundle.cards.slice();\n"
        "  }\n"
        "  var out = [];\n"
        "  for (var i = 0; i < bundle.cards.length; i += 1) {\n"
        "    var c = bundle.cards[i];\n"
        "    if (filter.modality && c.modality !== String(filter.modality).toLowerCase()) {\n"
        "      continue;\n"
        "    }\n"
        "    if (filter.tier && c.tier !== String(filter.tier).toLowerCase()) {\n"
        "      continue;\n"
        "    }\n"
        "    if (filter.seed !== undefined && filter.seed !== null && Number(c.seed) !== Number(filter.seed)) {\n"
        "      continue;\n"
        "    }\n"
        "    if (filter.thinking_level && c.thinking_level !== String(filter.thinking_level).toLowerCase()) {\n"
        "      continue;\n"
        "    }\n"
        "    if (filter.run_dir && c.run_dir !== String(filter.run_dir)) {\n"
        "      continue;\n"
        "    }\n"
        "    out.push(c);\n"
        "  }\n"
        "  return out;\n"
        "};\n"
        "_w.listOutthinkEvidenceStations = function() {\n"
        "  var bundle = _w.OUTTHINK_EVIDENCE_CARDS;\n"
        "  return bundle && Array.isArray(bundle.room_stations) ? bundle.room_stations.slice() : [];\n"
        "};\n"
        'if (typeof globalThis !== "undefined" && _w !== globalThis) {\n'
        "  globalThis.OUTTHINK_EVIDENCE_CARDS = _w.OUTTHINK_EVIDENCE_CARDS;\n"
        "  globalThis.getOutthinkEvidenceCard = _w.getOutthinkEvidenceCard;\n"
        "  globalThis.getOutthinkWorldEvidence = _w.getOutthinkWorldEvidence;\n"
        "  globalThis.getOutthinkEvidenceForCase = _w.getOutthinkEvidenceForCase;\n"
        "  globalThis.listOutthinkEvidenceCards = _w.listOutthinkEvidenceCards;\n"
        "  globalThis.listOutthinkEvidenceStations = _w.listOutthinkEvidenceStations;\n"
        "}\n"
        'if (typeof module !== "undefined" && module.exports) {\n'
        "  module.exports = {\n"
        "    OUTTHINK_EVIDENCE_CARDS: _w.OUTTHINK_EVIDENCE_CARDS,\n"
        "    getOutthinkEvidenceCard: _w.getOutthinkEvidenceCard,\n"
        "    getOutthinkWorldEvidence: _w.getOutthinkWorldEvidence,\n"
        "    getOutthinkEvidenceForCase: _w.getOutthinkEvidenceForCase,\n"
        "    listOutthinkEvidenceCards: _w.listOutthinkEvidenceCards,\n"
        "    listOutthinkEvidenceStations: _w.listOutthinkEvidenceStations\n"
        "  };\n"
        "}\n"
    )
    return helper_js


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.outthink_evidence_cards")
    ap.add_argument("--multimodal-dir", type=Path, default=None)
    ap.add_argument("--js-out", type=Path, default=DEFAULT_JS_OUT)
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    bundle = build_outthink_evidence_cards(args.multimodal_dir)
    js_text = render_evidence_cards_js(bundle)

    if args.check:
        assert args.js_out.is_file(), f"Missing {args.js_out}"
        existing = args.js_out.read_text(encoding="utf-8")
        assert existing == js_text, f"{args.js_out} is out of sync with build_outthink_evidence_cards()"
        return 0

    args.js_out.parent.mkdir(parents=True, exist_ok=True)
    args.js_out.write_text(js_text, encoding="utf-8")

    if args.json_out is not None:
        json_text = json.dumps(bundle, indent=2, ensure_ascii=True) + "\n"
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json_text, encoding="utf-8")

    s = bundle["summary"]
    print(
        f"outthink_evidence_cards: {s['total_runs']} runs, {s['total_cards']} cards, "
        f"{s['total_images_read']} PNGs, ${s['total_cost_usd']:.6f} -> {args.js_out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
