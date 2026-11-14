from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.runlog import git_sha, parse_seeds
from canary.gemini.memo_vision import (
    DEFAULT_MODEL,
    FEATURE,
    SUBROLE,
    run_paired_ablation_seed,
    sanitize_text,
)
from canary.gemini.sdk import genai_client
from canary.rules import TIERS_VERSION

DEFAULT_OUT = Path("results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon")


def _agg_condition(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    n = len(rows)
    if n == 0:
        return {
            "n": 0,
            "mean_score": 0.0,
            "accuracy": 0.0,
            "accused_count": 0,
            "mean_accuse_day": None,
            "scores": [],
        }
    scores = [float(r[key]["score"]) for r in rows]
    hits = sum(1 for r in rows if r[key]["correct"])
    accused_days = [int(r[key]["final_day"]) for r in rows if r[key]["end_reason"] == "accused"]
    return {
        "n": n,
        "mean_score": round(sum(scores) / n, 4),
        "accuracy": round(hits / n, 4),
        "accused_count": len(accused_days),
        "mean_accuse_day": round(sum(accused_days) / len(accused_days), 2) if accused_days else None,
        "scores": [round(x, 4) for x in scores],
    }


def _build_summary_md(meta: dict[str, Any], comparison: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    s = comparison["summary"]
    mm = s["multimodal_carbon"]
    bl = s["blind_no_vision"]
    orc = s["text_oracle"]
    u = meta["usage"]

    mm_day = f"{mm['mean_accuse_day']:.2f}" if mm["mean_accuse_day"] is not None else "n/a (horizon)"
    bl_day = f"{bl['mean_accuse_day']:.2f}" if bl["mean_accuse_day"] is not None else "n/a (horizon)"
    orc_day = f"{orc['mean_accuse_day']:.2f}" if orc["mean_accuse_day"] is not None else "n/a (horizon)"
    rec_pct = f"{s['oracle_score_recovery_ratio']:.1%}" if s["oracle_score_recovery_ratio"] is not None else "n/a"

    lines = [
        f"{h1} Role 6 ({meta['role']}) - In-Game Visual Leak-Memo Watermark Vision + Blind Ablation",
        "",
        f"{h2} Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` (`{meta['tier']}`, seeds `{meta['seeds']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Episodes per condition: `{meta['n_episodes']}` (3 conditions x {meta['n_episodes']} seeds = {3 * int(meta['n_episodes'])} paired episodes)",
        f"- Leaked memo PNGs read via `Part.from_bytes(..., mime_type='image/png')`: `{meta['n_images_read_by_model']}` (`{meta['n_canary_memos_read_by_model']}` watermarked canary scans)",
        f"- Vision watermark readout accuracy: `{meta['variant_vision_accuracy']:.1%}` overall (`{meta['canary_variant_vision_accuracy']:.1%}` on planted canary memos)",
        f"- Token usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`",
        "",
        f"{h2} Paired 3-Condition Comparison (`{meta['tier']}` seeds `{meta['seeds']}`)",
        "| Condition | Variant Source | Mean Score | Mole Accuracy | Accusations | Mean Accuse Day |",
        "|---|---|---:|---:|---:|---:|",
        f"| `multimodal_carbon` | `gemini-4-carbon` reading memo PNGs (`Part.from_bytes`) | {mm['mean_score']:+.4f} | {mm['accuracy']:.1%} | {mm['accused_count']}/{mm['n']} | {mm_day} |",
        f"| `blind_no_vision` | Text `variant` redacted, vision disabled | {bl['mean_score']:+.4f} | {bl['accuracy']:.1%} | {bl['accused_count']}/{bl['n']} | {bl_day} |",
        f"| `text_oracle` | Unredacted text `check_leak_feed` upper bound | {orc['mean_score']:+.4f} | {orc['accuracy']:.1%} | {orc['accused_count']}/{orc['n']} | {orc_day} |",
        "",
        f"- Multimodal gain over blind ablation: `{s['multimodal_minus_blind']:+.4f}`",
        f"- Oracle Bayesian solver performance recovered by vision: `{rec_pct}` (`{mm['mean_score']:+.4f}` vs `{orc['mean_score']:+.4f}`)",
        "",
        f"{h2} Per-Seed Paired Episodes",
        "| Seed | `multimodal_carbon` Score (Accused, Day, Max P) | `blind_no_vision` Score (Accused, Day, Max P) | `text_oracle` Score (Accused, Day, Max P) | Memos Read | Vision Exact |",
        "|---:|---|---|---|---:|---:|",
    ]

    for row in comparison["per_seed"]:
        mc = row["multimodal_carbon"]
        bn = row["blind_no_vision"]
        to = row["text_oracle"]
        mc_cell = f"`{mc['score']:+.4f}` (`{mc['accused'] or 'none'}`, d{mc['final_day']}, P={mc['max_posterior']:.2f})"
        bn_cell = f"`{bn['score']:+.4f}` (`{bn['accused'] or 'none'}`, d{bn['final_day']}, P={bn['max_posterior']:.2f})"
        to_cell = f"`{to['score']:+.4f}` (`{to['accused'] or 'none'}`, d{to['final_day']}, P={to['max_posterior']:.2f})"
        lines.append(
            f"| {row['seed']} | {mc_cell} | {bn_cell} | {to_cell} "
            f"| {mc['n_memos_inspected']} | {mc['vision_exact_matches']}/{mc['n_memos_inspected']} |"
        )

    lines.extend([
        "",
        f"{h2} Rendered Leak-Memo Scans & `gemini-4-carbon` Vision Readouts",
        "| Seed | Doc ID | Day Surfaced | Expected Copy-Code | Predicted Copy-Code | Match | PNG Path | Size | Bytes | SHA-256 |",
        "|---:|---|---:|---|---|---|---|---|---:|---|",
    ])

    for vc in comparison["vision_calls"]:
        w, h = vc["memo_size"]
        exp_lbl = vc["expected_variant"] or "NONE"
        pred_lbl = vc["predicted_variant"] or "NONE"
        ok_lbl = "YES" if vc["variant_exact_match"] else "NO"
        lines.append(
            f"| {vc['seed']} | `{vc['doc_id']}` | {vc['day_surfaced']} | `{exp_lbl}` | `{pred_lbl}` | {ok_lbl} "
            f"| `{vc['memo_path']}` | {w}x{h} | {vc['memo_bytes']} | `{vc['memo_sha256']}` |"
        )

    return sanitize_text("\n".join(lines)) + "\n"


def run_ablation(
    *,
    seeds: list[int],
    tier: str = "medium",
    model_id: str = DEFAULT_MODEL,
    out_dir: Path = DEFAULT_OUT,
    vision_mode: str = "gemini",
    sdk_client: Any = None,
    stub_reader: Any = None,
    thinking_level: str | None = None,
    max_retries: int | None = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    memos_dir = out_dir / "memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    for old_png in memos_dir.glob("*.png"):
        old_png.unlink()

    if vision_mode == "gemini" and sdk_client is None:
        sdk_client = genai_client()

    ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = git_sha()
    run_id = f"{FEATURE}:{SUBROLE}:{model_id}:{int(time.time())}"

    per_seed: list[dict[str, Any]] = []
    vision_calls: list[dict[str, Any]] = []
    memo_manifest: list[dict[str, Any]] = []
    tot_usage = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}

    for seed in seeds:
        seed_res = run_paired_ablation_seed(
            seed,
            tier=tier,
            model_id=model_id,
            vision_mode=vision_mode,
            sdk_client=sdk_client,
            stub_reader=stub_reader,
            run_id=run_id,
            out_memos_dir=memos_dir,
            rel_memos_prefix="memos",
            thinking_level=thinking_level,
            max_retries=max_retries,
        )
        per_seed.append({
            "seed": seed_res["seed"],
            "tier": seed_res["tier"],
            "tiers_version": seed_res["tiers_version"],
            "multimodal_carbon": seed_res["multimodal_carbon"],
            "blind_no_vision": seed_res["blind_no_vision"],
            "text_oracle": seed_res["text_oracle"],
        })

        for row in seed_res["vision_calls"]:
            call_idx = len(vision_calls)
            vc_entry = {
                "call_index": call_idx,
                "seed": row["seed"],
                "tier": tier,
                "doc_id": row["doc_id"],
                "day_surfaced": row["day_surfaced"],
                "is_canary_memo": row["is_canary_memo"],
                "expected_variant": row["expected_variant"],
                "predicted_variant": row["variant"],
                "variant_exact_match": row["variant_exact_match"],
                "memo_path": row["memo_path"],
                "memo_sha256": row["memo_sha256"],
                "memo_bytes": row["memo_bytes"],
                "memo_size": row["memo_size"],
                "model_id": model_id,
                "model_version": row["model_version"],
                "model_response": row["model_response"],
                "usage": row["usage"],
            }
            vision_calls.append(vc_entry)
            memo_manifest.append({
                "seed": row["seed"],
                "doc_id": row["doc_id"],
                "day_surfaced": row["day_surfaced"],
                "is_canary_memo": row["is_canary_memo"],
                "path": row["memo_path"],
                "sha256": row["memo_sha256"],
                "bytes": row["memo_bytes"],
                "size": row["memo_size"],
            })

        u = seed_res["usage"]
        tot_usage["calls"] += int(u["calls"])
        tot_usage["in"] += int(u["in"])
        tot_usage["out"] += int(u["out"])
        tot_usage["thinking"] += int(u["thinking"])
        tot_usage["cached"] += int(u["cached"])
        tot_usage["cost_usd"] = round(tot_usage["cost_usd"] + float(u["cost_usd"]), 6)
        tot_usage["latency_s"] = round(tot_usage["latency_s"] + float(u["latency_s"]), 3)

    mm_agg = _agg_condition(per_seed, "multimodal_carbon")
    bl_agg = _agg_condition(per_seed, "blind_no_vision")
    orc_agg = _agg_condition(per_seed, "text_oracle")

    n_images = len(vision_calls)
    canary_calls = [c for c in vision_calls if c["is_canary_memo"]]
    vision_acc = round(sum(1 for c in vision_calls if c["variant_exact_match"]) / max(1, n_images), 4)
    canary_vision_acc = round(sum(1 for c in canary_calls if c["variant_exact_match"]) / max(1, len(canary_calls)), 4)
    rec_ratio = round(mm_agg["mean_score"] / orc_agg["mean_score"], 4) if orc_agg["mean_score"] > 1e-9 else None

    cmd = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])

    meta: dict[str, Any] = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seeds": list(seeds),
        "commit": sha,
        "git_sha": sha,
        "timestamp": ts_iso,
        "command": sanitize_text(cmd),
        "ledger_run_id": run_id,
        "n_episodes": len(seeds),
        "n_images_read_by_model": n_images,
        "n_canary_memos_read_by_model": len(canary_calls),
        "variant_vision_accuracy": vision_acc,
        "canary_variant_vision_accuracy": canary_vision_acc,
        "multimodal_mean_score": mm_agg["mean_score"],
        "blind_mean_score": bl_agg["mean_score"],
        "blind_ablation_mean_score": bl_agg["mean_score"],
        "oracle_mean_score": orc_agg["mean_score"],
        "multimodal_accuracy": mm_agg["accuracy"],
        "blind_accuracy": bl_agg["accuracy"],
        "oracle_accuracy": orc_agg["accuracy"],
        "oracle_score_recovery_ratio": rec_ratio,
        "memos": memo_manifest,
        "usage": tot_usage,
    }

    comparison: dict[str, Any] = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seeds": list(seeds),
        "commit": sha,
        "timestamp": ts_iso,
        "n_episodes": len(seeds),
        "n_images_read_by_model": n_images,
        "summary": {
            "multimodal_carbon": mm_agg,
            "blind_no_vision": bl_agg,
            "text_oracle": orc_agg,
            "multimodal_minus_blind": round(mm_agg["mean_score"] - bl_agg["mean_score"], 4),
            "multimodal_minus_oracle": round(mm_agg["mean_score"] - orc_agg["mean_score"], 4),
            "oracle_score_recovery_ratio": rec_ratio,
            "variant_vision_accuracy": vision_acc,
            "canary_variant_vision_accuracy": canary_vision_acc,
        },
        "per_seed": per_seed,
        "vision_calls": vision_calls,
        "memos": memo_manifest,
        "usage": tot_usage,
    }

    (out_dir / "meta.json").write_text(sanitize_text(json.dumps(meta, indent=2)) + "\n", encoding="utf-8")
    (out_dir / "comparison.json").write_text(sanitize_text(json.dumps(comparison, indent=2)) + "\n", encoding="utf-8")
    jsonl_lines = [sanitize_text(json.dumps(vc, sort_keys=False)) for vc in vision_calls]
    (out_dir / "vision_calls.jsonl").write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")
    (out_dir / "summary.md").write_text(_build_summary_md(meta, comparison), encoding="utf-8")

    return {"meta": meta, "comparison": comparison}


def main(argv: list[str] | None = None, *, sdk_client: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Run In-Game Visual Leak-Memo Watermark Vision + Blind Ablation.")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="3,4,5")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--max-retries", type=int, default=None)
    args = ap.parse_args(argv)

    seeds = parse_seeds(args.seeds)
    retries = args.max_retries
    if retries is None and os.environ.get("CANARY_LLM_MAX_RETRIES"):
        retries = int(os.environ["CANARY_LLM_MAX_RETRIES"])

    raw_argv = argv if argv is not None else sys.argv[1:]
    prefix = f"CANARY_LLM_MAX_RETRIES={os.environ['CANARY_LLM_MAX_RETRIES']} " if os.environ.get("CANARY_LLM_MAX_RETRIES") else ""
    cmd_str = f"{prefix}PYTHONPATH=. {sys.executable} scripts/run_memo_vision_ablation.py " + " ".join(shlex.quote(x) for x in raw_argv)
    cmd_str = cmd_str.strip()

    bundle = run_ablation(
        seeds=seeds,
        tier=args.tier,
        model_id=args.model,
        out_dir=args.out,
        vision_mode="gemini",
        sdk_client=sdk_client,
        thinking_level=args.thinking_level,
        max_retries=retries,
        command_str=cmd_str,
    )
    meta = bundle["meta"]
    u = meta["usage"]
    print(
        f"memo_vision_ablation: episodes={meta['n_episodes']} images={meta['n_images_read_by_model']} "
        f"vision_acc={meta['variant_vision_accuracy']:.1%} "
        f"multimodal={meta['multimodal_mean_score']:+.4f} "
        f"blind={meta['blind_mean_score']:+.4f} "
        f"oracle={meta['oracle_mean_score']:+.4f} "
        f"in={u['in']} out={u['out']} think={u['thinking']} cost=${u['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
