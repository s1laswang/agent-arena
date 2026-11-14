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
from canary.gemini.access_vision import DEFAULT_MODEL, FEATURE, evaluate_world_seed, subrole_for_tier
from canary.gemini.sdk import genai_client
from canary.rules import TIERS_VERSION

DEFAULT_OUT = Path("results/gemini_roles/multimodal_evidence/access-heatmap-carbon")


def _clean(text: str) -> str:
    return (text or "").replace("\u2014", "-").replace("\u2013", "-")


def _build_summary_md(meta: dict[str, Any], results: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    m = results["metrics"]
    u = meta["usage"]
    lines = [
        f"{h1} Role 6 ({meta['role']}) - Security-SOC Access & Framing Raster Vision Run",
        "",
        f"{h2} Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` (`{meta['tier']}`, seeds `{meta['seeds']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Images read by model (`Part.from_bytes`, `image/png`): `{meta['n_images_read_by_model']}`",
        f"- Token usage: `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`",
        "",
        f"{h2} Aggregate Results",
        "| Metric | Gemini SOC Vision (`gemini-4-carbon`) | Naive After-Hours Log Baseline |",
        "|---|---|---|",
        f"| Top-1 Mole Accuracy | {m['top1_mole_hits']}/{results['n_worlds']} ({m['top1_mole_accuracy']:.1%}) | {m['naive_baseline_mole_hits']}/{results['n_worlds']} ({m['naive_after_hours_baseline_mole_accuracy']:.1%}) |",
        f"| Top-3 Mole Hit Rate | {m['top3_mole_hits']}/{results['n_worlds']} ({m['top3_mole_hit_rate']:.1%}) | - |",
        f"| Top-1 Framed Decoy Identified | {m['top1_decoy_hits']}/{results['n_worlds']} ({m['top1_decoy_accuracy']:.1%}) | - |",
        f"| Framed Decoy in Suspected Decoy List | {m['decoy_identified_hits']}/{results['n_worlds']} ({m['decoy_identified_rate']:.1%}) | - |",
        f"| Avoided Framing Decoy Trap | {m['avoided_framing_trap_hits']}/{results['n_worlds']} ({m['avoided_framing_trap_rate']:.1%}) | {results['n_worlds'] - m['naive_baseline_decoy_traps']}/{results['n_worlds']} ({1.0 - m['naive_after_hours_baseline_decoy_trap_rate']:.1%}) |",
        "",
        f"{h2} Rendered SOC Evidence Rasters",
        "| Seed | Raster Path | Size | Bytes | SHA-256 |",
        "|---|---|---|---|---|",
    ]
    for r in meta["rasters"]:
        w, h = r["size"]
        lines.append(f"| {r['seed']} | `{r['path']}` | {w}x{h} | {r['bytes']} | `{r['sha256']}` |")

    lines.extend([
        "",
        f"{h2} Per-World Breakdown",
        "| Seed | True Mole | True Decoy | Naive Log Pick | Pred Top Suspects | Pred Decoys | Mole Top-1 | Decoy Top-1 |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for w in results["worlds"]:
        gt = w["ground_truth"]
        mo = w["model_output"]
        ev = w["evaluation"]
        obs = w["observable_summary"]
        lines.append(
            f"| {w['seed']} | `{gt['true_mole']}` | `{gt['true_decoy']}` | `{obs['naive_most_after_hours_id']}` "
            f"| `{', '.join(mo['top_suspect_ids'][:3])}` | `{', '.join(mo['suspected_decoy_ids'][:3])}` "
            f"| {'YES' if ev['top1_mole_correct'] else 'NO'} | {'YES' if ev['top1_decoy_correct'] else 'NO'} |"
        )

    lines.append("")
    lines.append(f"{h2} Visual Reasoning Excerpts")
    for w in results["worlds"]:
        mo = w["model_output"]
        lines.append(f"- **Seed {w['seed']}** (`{w['raster_path']}`, conf `{mo['confidence']:.2f}`): {_clean(mo['visual_reasoning'])}")

    return _clean("\n".join(lines) + "\n")


def run_evaluation(
    *,
    seeds: list[int],
    tier: str = "medium",
    model_id: str = DEFAULT_MODEL,
    out_dir: Path = DEFAULT_OUT,
    thinking_level: str | None = None,
    max_retries: int | None = None,
    sdk_client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    rasters_dir = out_dir / "rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)

    if sdk_client is None:
        sdk_client = genai_client()

    ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = git_sha()
    subrole_name = subrole_for_tier(tier)
    run_id = f"{FEATURE}:{subrole_name}:{model_id}:{int(time.time())}"

    worlds: list[dict[str, Any]] = []
    raster_manifest: list[dict[str, Any]] = []
    tot_usage = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}

    for s in seeds:
        rel_png = f"rasters/{tier}_seed_{s}.png"
        dst_png = out_dir / rel_png
        row = evaluate_world_seed(
            s,
            tier=tier,
            model_id=model_id,
            sdk_client=sdk_client,
            run_id=run_id,
            out_raster_path=dst_png,
            max_retries=max_retries,
            thinking_level=thinking_level,
        )
        row["raster_path"] = rel_png
        worlds.append(row)
        raster_manifest.append({
            "seed": s,
            "path": rel_png,
            "sha256": row["raster_sha256"],
            "bytes": row["raster_bytes"],
            "size": row["raster_size"],
        })
        u = row["usage"]
        tot_usage["calls"] += 1
        tot_usage["in"] += int(u["in"])
        tot_usage["out"] += int(u["out"])
        tot_usage["thinking"] += int(u["thinking"])
        tot_usage["cached"] += int(u["cached"])
        tot_usage["cost_usd"] = round(tot_usage["cost_usd"] + float(u["cost_usd"]), 6)
        tot_usage["latency_s"] = round(tot_usage["latency_s"] + float(u["latency_s"]), 3)

    n = max(1, len(worlds))
    top1_mole_hits = sum(1 for w in worlds if w["evaluation"]["top1_mole_correct"])
    top3_mole_hits = sum(1 for w in worlds if w["evaluation"]["top3_mole_hit"])
    top1_decoy_hits = sum(1 for w in worlds if w["evaluation"]["top1_decoy_correct"])
    decoy_id_hits = sum(1 for w in worlds if w["evaluation"]["decoy_identified"])
    avoid_trap_hits = sum(1 for w in worlds if w["evaluation"]["avoided_framing_trap"])
    naive_mole_hits = sum(1 for w in worlds if w["evaluation"]["naive_baseline_mole_correct"])
    naive_decoy_traps = sum(1 for w in worlds if w["evaluation"]["naive_baseline_trapped_by_decoy"])

    cmd = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])

    meta = {
        "role": FEATURE,
        "subrole": subrole_name,
        "model_id": model_id,
        "commit": sha,
        "git_sha": sha,
        "timestamp": ts_iso,
        "command": _clean(cmd),
        "n_images_read_by_model": len(worlds),
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "seeds": list(seeds),
        "ledger_run_id": run_id,
        "rasters": raster_manifest,
        "usage": tot_usage,
    }

    results = {
        "role": FEATURE,
        "subrole": subrole_name,
        "model_id": model_id,
        "commit": sha,
        "timestamp": ts_iso,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "n_worlds": len(worlds),
        "n_images_read_by_model": len(worlds),
        "metrics": {
            "top1_mole_hits": top1_mole_hits,
            "top1_mole_accuracy": round(top1_mole_hits / n, 4),
            "top3_mole_hits": top3_mole_hits,
            "top3_mole_hit_rate": round(top3_mole_hits / n, 4),
            "top1_decoy_hits": top1_decoy_hits,
            "top1_decoy_accuracy": round(top1_decoy_hits / n, 4),
            "decoy_identified_hits": decoy_id_hits,
            "decoy_identified_rate": round(decoy_id_hits / n, 4),
            "avoided_framing_trap_hits": avoid_trap_hits,
            "avoided_framing_trap_rate": round(avoid_trap_hits / n, 4),
            "naive_baseline_mole_hits": naive_mole_hits,
            "naive_after_hours_baseline_mole_accuracy": round(naive_mole_hits / n, 4),
            "naive_baseline_decoy_traps": naive_decoy_traps,
            "naive_after_hours_baseline_decoy_trap_rate": round(naive_decoy_traps / n, 4),
        },
        "usage": tot_usage,
        "worlds": worlds,
    }

    (out_dir / "meta.json").write_text(_clean(json.dumps(meta, indent=2)) + "\n")
    (out_dir / "results.json").write_text(_clean(json.dumps(results, indent=2)) + "\n")
    (out_dir / "summary.md").write_text(_build_summary_md(meta, results))

    return {"meta": meta, "results": results}


def main(argv: list[str] | None = None, *, sdk_client: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Run Security-SOC Access & Framing Raster Vision evaluation.")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="0,1,2")
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
    cmd_str = f"{prefix}PYTHONPATH=. {sys.executable} scripts/run_access_vision.py " + " ".join(shlex.quote(x) for x in raw_argv)
    cmd_str = cmd_str.strip()

    bundle = run_evaluation(
        seeds=seeds,
        tier=args.tier,
        model_id=args.model,
        out_dir=args.out,
        thinking_level=args.thinking_level,
        max_retries=retries,
        sdk_client=sdk_client,
        command_str=cmd_str,
    )
    m = bundle["results"]["metrics"]
    u = bundle["meta"]["usage"]
    print(
        f"access_vision: worlds={bundle['results']['n_worlds']} "
        f"mole_top1={m['top1_mole_hits']}/{bundle['results']['n_worlds']} "
        f"decoy_top1={m['top1_decoy_hits']}/{bundle['results']['n_worlds']} "
        f"images={bundle['meta']['n_images_read_by_model']} "
        f"in={u['in']} out={u['out']} think={u['thinking']} cost=${u['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
