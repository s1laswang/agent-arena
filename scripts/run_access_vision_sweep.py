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
from canary.gemini.access_vision import DEFAULT_MODEL, FEATURE, evaluate_world_seed
from canary.gemini.sdk import genai_client
from canary.rules import TIERS_VERSION

SUBROLE = "soc_access_vision_v14_sweep"
DEFAULT_TIERS = "medium,hard"
DEFAULT_SEEDS = "3,4,5,6,7"
DEFAULT_OUT = Path("results/gemini_roles/multimodal_evidence/access-heatmap-v14-sweep-carbon")
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _clean(text: str) -> str:
    return (text or "").replace(EM_DASH, "-").replace(EN_DASH, "-")


def _parse_tiers(spec: str) -> list[str]:
    out: list[str] = []
    for part in (spec or "").split(","):
        t = part.strip().lower()
        if t and t not in out:
            out.append(t)
    if not out:
        raise ValueError(f"empty tier list: {spec!r}")
    return out


def _sum_usage(worlds: list[dict[str, Any]]) -> dict[str, Any]:
    tot = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}
    for w in worlds:
        u = w.get("usage") or {}
        tot["calls"] += 1
        tot["in"] += int(u.get("in", 0))
        tot["out"] += int(u.get("out", 0))
        tot["thinking"] += int(u.get("thinking", 0))
        tot["cached"] += int(u.get("cached", 0))
        tot["cost_usd"] = round(tot["cost_usd"] + float(u.get("cost_usd", 0.0)), 6)
        tot["latency_s"] = round(tot["latency_s"] + float(u.get("latency_s", 0.0)), 3)
    return tot


def compute_calibration_bins(worlds: list[dict[str, Any]], n_bins: int = 5) -> list[dict[str, Any]]:
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins!r}")
    bins: list[dict[str, Any]] = []
    for idx in range(n_bins):
        lo = idx / n_bins
        hi = (idx + 1) / n_bins
        if idx < n_bins - 1:
            members = [
                w for w in worlds
                if lo <= float(w["model_output"]["confidence"]) < hi
            ]
        else:
            members = [
                w for w in worlds
                if lo <= float(w["model_output"]["confidence"]) <= 1.0
            ]
        cnt = len(members)
        if cnt == 0:
            bins.append({
                "bin_index": idx,
                "lo": round(lo, 4),
                "hi": round(hi, 4),
                "count": 0,
                "mean_confidence": None,
                "empirical_accuracy": None,
                "calibration_gap": None,
                "signed_gap": None,
            })
            continue
        mean_conf = sum(float(w["model_output"]["confidence"]) for w in members) / cnt
        emp_acc = sum(1.0 if w["evaluation"]["top1_mole_correct"] else 0.0 for w in members) / cnt
        bins.append({
            "bin_index": idx,
            "lo": round(lo, 4),
            "hi": round(hi, 4),
            "count": cnt,
            "mean_confidence": round(mean_conf, 6),
            "empirical_accuracy": round(emp_acc, 6),
            "calibration_gap": round(abs(mean_conf - emp_acc), 6),
            "signed_gap": round(mean_conf - emp_acc, 6),
        })
    return bins


def compute_subset_metrics(worlds: list[dict[str, Any]], n_bins: int = 5) -> dict[str, Any]:
    n = len(worlds)
    if n == 0:
        return {
            "n_worlds": 0,
            "seeds": [],
            "top1_mole_hits": 0,
            "top1_mole_accuracy": 0.0,
            "top3_mole_hits": 0,
            "top3_mole_hit_rate": 0.0,
            "top1_decoy_hits": 0,
            "top1_decoy_accuracy": 0.0,
            "decoy_identified_hits": 0,
            "decoy_identified_rate": 0.0,
            "avoided_framing_trap_hits": 0,
            "avoided_framing_trap_rate": 0.0,
            "naive_baseline_mole_hits": 0,
            "naive_baseline_mole_accuracy": 0.0,
            "naive_after_hours_baseline_mole_accuracy": 0.0,
            "naive_baseline_decoy_traps": 0,
            "naive_baseline_decoy_trap_rate": 0.0,
            "naive_after_hours_baseline_decoy_trap_rate": 0.0,
            "naive_baseline_avoided_trap_hits": 0,
            "naive_baseline_avoided_trap_rate": 0.0,
            "mole_accuracy_delta_vs_naive": 0.0,
            "avoided_trap_delta_vs_naive": 0.0,
            "head_to_head_wins_vs_naive": 0,
            "head_to_head_ties_vs_naive": 0,
            "head_to_head_losses_vs_naive": 0,
            "mean_confidence": 0.0,
            "mean_confidence_when_correct": None,
            "mean_confidence_when_wrong": None,
            "brier_score": 0.0,
            "expected_calibration_error": 0.0,
            "mean_calibration_gap": 0.0,
            "signed_calibration_gap": 0.0,
            "usage": _sum_usage([]),
        }

    top1_mole_hits = sum(1 for w in worlds if w["evaluation"]["top1_mole_correct"])
    top3_mole_hits = sum(1 for w in worlds if w["evaluation"]["top3_mole_hit"])
    top1_decoy_hits = sum(1 for w in worlds if w["evaluation"]["top1_decoy_correct"])
    decoy_id_hits = sum(1 for w in worlds if w["evaluation"]["decoy_identified"])
    avoid_trap_hits = sum(1 for w in worlds if w["evaluation"]["avoided_framing_trap"])
    naive_mole_hits = sum(1 for w in worlds if w["evaluation"]["naive_baseline_mole_correct"])
    naive_decoy_traps = sum(1 for w in worlds if w["evaluation"]["naive_baseline_trapped_by_decoy"])
    naive_avoid_hits = n - naive_decoy_traps

    h2h_wins = sum(
        1 for w in worlds
        if w["evaluation"]["top1_mole_correct"] and not w["evaluation"]["naive_baseline_mole_correct"]
    )
    h2h_ties = sum(
        1 for w in worlds
        if bool(w["evaluation"]["top1_mole_correct"]) == bool(w["evaluation"]["naive_baseline_mole_correct"])
    )
    h2h_losses = sum(
        1 for w in worlds
        if (not w["evaluation"]["top1_mole_correct"]) and w["evaluation"]["naive_baseline_mole_correct"]
    )

    confs = [max(0.0, min(1.0, float(w["model_output"]["confidence"]))) for w in worlds]
    outcomes = [1.0 if w["evaluation"]["top1_mole_correct"] else 0.0 for w in worlds]
    correct_confs = [c for c, y in zip(confs, outcomes) if y > 0.5]
    wrong_confs = [c for c, y in zip(confs, outcomes) if y < 0.5]

    mean_conf = sum(confs) / n
    emp_acc = top1_mole_hits / n
    brier = sum((c - y) ** 2 for c, y in zip(confs, outcomes)) / n

    bins = compute_calibration_bins(worlds, n_bins=n_bins)
    ece = sum((b["count"] / n) * float(b["calibration_gap"]) for b in bins if b["count"] > 0)

    naive_acc = naive_mole_hits / n
    avoid_rate = avoid_trap_hits / n
    naive_avoid_rate = naive_avoid_hits / n

    return {
        "n_worlds": n,
        "seeds": [int(w["seed"]) for w in worlds],
        "top1_mole_hits": top1_mole_hits,
        "top1_mole_accuracy": round(emp_acc, 4),
        "top3_mole_hits": top3_mole_hits,
        "top3_mole_hit_rate": round(top3_mole_hits / n, 4),
        "top1_decoy_hits": top1_decoy_hits,
        "top1_decoy_accuracy": round(top1_decoy_hits / n, 4),
        "decoy_identified_hits": decoy_id_hits,
        "decoy_identified_rate": round(decoy_id_hits / n, 4),
        "avoided_framing_trap_hits": avoid_trap_hits,
        "avoided_framing_trap_rate": round(avoid_rate, 4),
        "naive_baseline_mole_hits": naive_mole_hits,
        "naive_baseline_mole_accuracy": round(naive_acc, 4),
        "naive_after_hours_baseline_mole_accuracy": round(naive_acc, 4),
        "naive_baseline_decoy_traps": naive_decoy_traps,
        "naive_baseline_decoy_trap_rate": round(naive_decoy_traps / n, 4),
        "naive_after_hours_baseline_decoy_trap_rate": round(naive_decoy_traps / n, 4),
        "naive_baseline_avoided_trap_hits": naive_avoid_hits,
        "naive_baseline_avoided_trap_rate": round(naive_avoid_rate, 4),
        "mole_accuracy_delta_vs_naive": round(emp_acc - naive_acc, 4),
        "avoided_trap_delta_vs_naive": round(avoid_rate - naive_avoid_rate, 4),
        "head_to_head_wins_vs_naive": h2h_wins,
        "head_to_head_ties_vs_naive": h2h_ties,
        "head_to_head_losses_vs_naive": h2h_losses,
        "mean_confidence": round(mean_conf, 4),
        "mean_confidence_when_correct": round(sum(correct_confs) / len(correct_confs), 4) if correct_confs else None,
        "mean_confidence_when_wrong": round(sum(wrong_confs) / len(wrong_confs), 4) if wrong_confs else None,
        "brier_score": round(brier, 6),
        "expected_calibration_error": round(ece, 6),
        "mean_calibration_gap": round(abs(mean_conf - emp_acc), 6),
        "signed_calibration_gap": round(mean_conf - emp_acc, 6),
        "usage": _sum_usage(worlds),
    }


def _fmt_hit(hits: int, total: int, rate: float) -> str:
    return f"{hits}/{total} ({rate:.1%})"


def _build_summary_md(meta: dict[str, Any], results: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    ov = results["metrics"]
    by_tier = results["by_tier"]
    u = meta["usage"]
    tiers = results["tiers"]
    tier_desc = ", ".join(f"{t} seeds {results['tier_seeds'][t]}" for t in tiers)

    lines = [
        f"{h1} Role 6 ({meta['role']}) - Multi-Tier v1.4 SOC Access & Framing Raster Vision Sweep",
        "",
        f"{h2} Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` ({tier_desc})",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Episode count: `{meta['episode_count']}`",
        f"- Images read by model (`Part.from_bytes`, `image/png`): `{meta['n_images_read_by_model']}`",
        f"- Token usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`",
        "",
        f"{h2} Per-Tier & Overall Aggregate Results vs Naive After-Hours Log Baseline",
    ]

    col_headers = ["Metric"]
    for t in tiers:
        col_headers.append(f"`{t}` (`n={by_tier[t]['n_worlds']}`)")
    col_headers.extend([
        f"Overall Vision (`n={ov['n_worlds']}`)",
        f"Naive After-Hours Baseline (`n={ov['n_worlds']}`)",
        "Vision vs Naive Delta",
    ])
    lines.append("| " + " | ".join(col_headers) + " |")
    lines.append("|" + "|".join(["---"] * len(col_headers)) + "|")

    def _row(label: str, tier_fn, ov_cell: str, naive_cell: str, delta_cell: str) -> str:
        cells = [label] + [tier_fn(by_tier[t]) for t in tiers] + [ov_cell, naive_cell, delta_cell]
        return "| " + " | ".join(cells) + " |"

    lines.extend([
        _row(
            "Top-1 Mole Accuracy",
            lambda m: _fmt_hit(m["top1_mole_hits"], m["n_worlds"], m["top1_mole_accuracy"]),
            _fmt_hit(ov["top1_mole_hits"], ov["n_worlds"], ov["top1_mole_accuracy"]),
            _fmt_hit(ov["naive_baseline_mole_hits"], ov["n_worlds"], ov["naive_baseline_mole_accuracy"]),
            f"{ov['mole_accuracy_delta_vs_naive']:+.1%} ({ov['head_to_head_wins_vs_naive']}W-{ov['head_to_head_ties_vs_naive']}T-{ov['head_to_head_losses_vs_naive']}L)",
        ),
        _row(
            "Top-3 Mole Hit Rate",
            lambda m: _fmt_hit(m["top3_mole_hits"], m["n_worlds"], m["top3_mole_hit_rate"]),
            _fmt_hit(ov["top3_mole_hits"], ov["n_worlds"], ov["top3_mole_hit_rate"]),
            "-",
            "-",
        ),
        _row(
            "Top-1 Framed Decoy Accuracy",
            lambda m: _fmt_hit(m["top1_decoy_hits"], m["n_worlds"], m["top1_decoy_accuracy"]),
            _fmt_hit(ov["top1_decoy_hits"], ov["n_worlds"], ov["top1_decoy_accuracy"]),
            "-",
            "-",
        ),
        _row(
            "Framed Decoy in Suspected List",
            lambda m: _fmt_hit(m["decoy_identified_hits"], m["n_worlds"], m["decoy_identified_rate"]),
            _fmt_hit(ov["decoy_identified_hits"], ov["n_worlds"], ov["decoy_identified_rate"]),
            "-",
            "-",
        ),
        _row(
            "Avoided Framing Trap Rate",
            lambda m: _fmt_hit(m["avoided_framing_trap_hits"], m["n_worlds"], m["avoided_framing_trap_rate"]),
            _fmt_hit(ov["avoided_framing_trap_hits"], ov["n_worlds"], ov["avoided_framing_trap_rate"]),
            _fmt_hit(ov["naive_baseline_avoided_trap_hits"], ov["n_worlds"], ov["naive_baseline_avoided_trap_rate"]),
            f"{ov['avoided_trap_delta_vs_naive']:+.1%}",
        ),
        _row(
            "Mean Confidence",
            lambda m: f"{m['mean_confidence']:.4f}",
            f"{ov['mean_confidence']:.4f}",
            "-",
            "-",
        ),
        _row(
            "Brier Score (lower is better)",
            lambda m: f"{m['brier_score']:.4f}",
            f"{ov['brier_score']:.4f}",
            "-",
            "-",
        ),
        _row(
            "Expected Calibration Error (ECE, 5-bin)",
            lambda m: f"{m['expected_calibration_error']:.4f}",
            f"{ov['expected_calibration_error']:.4f}",
            "-",
            "-",
        ),
    ])

    conf_ok = f"{ov['mean_confidence_when_correct']:.4f}" if ov["mean_confidence_when_correct"] is not None else "n/a"
    conf_err = f"{ov['mean_confidence_when_wrong']:.4f}" if ov["mean_confidence_when_wrong"] is not None else "n/a"
    lines.extend([
        "",
        f"{h2} Confidence Calibration & Head-to-Head Summary",
        f"- Overall Brier score: `{ov['brier_score']:.6f}` (ECE `{ov['expected_calibration_error']:.6f}`, signed confidence gap `{ov['signed_calibration_gap']:+.6f}`)",
        f"- Mean posterior confidence: `{ov['mean_confidence']:.4f}` overall (`{conf_ok}` when Top-1 correct, `{conf_err}` when Top-1 wrong)",
        f"- Head-to-head vs Naive After-Hours Log Baseline: `{ov['head_to_head_wins_vs_naive']}` wins, `{ov['head_to_head_ties_vs_naive']}` ties, `{ov['head_to_head_losses_vs_naive']}` losses (`{ov['mole_accuracy_delta_vs_naive']:+.1%}` Top-1 mole accuracy delta; Naive trapped by framed decoy on `{ov['naive_baseline_decoy_traps']}/{ov['n_worlds']}` worlds)",
        "",
        f"{h2} Rendered SOC Evidence Rasters",
        "| Tier | Seed | Raster Path | Size | Bytes | SHA-256 |",
        "|---|---:|---|---|---:|---|",
    ])

    for r in meta["rasters"]:
        w, h = r["size"]
        lines.append(f"| `{r['tier']}` | {r['seed']} | `{r['path']}` | {w}x{h} | {r['bytes']} | `{r['sha256']}` |")

    lines.extend([
        "",
        f"{h2} Per-World Breakdown",
        "| Tier | Seed | Staff | Surfaced Canaries | True Mole | True Decoy | Naive Pick | Pred Suspects | Pred Decoys | Conf | Brier | Mole Top-1 | Decoy Top-1 |",
        "|---|---:|---:|---:|---|---|---|---|---|---:|---:|---|---|",
    ])
    for w in results["worlds"]:
        gt = w["ground_truth"]
        mo = w["model_output"]
        ev = w["evaluation"]
        obs = w["observable_summary"]
        lines.append(
            f"| `{w['tier']}` | {w['seed']} | {obs['n_employees']} | {obs['n_surfaced_canary_leaks']}/{obs['n_canaries_planted']} "
            f"| `{gt['true_mole']}` | `{gt['true_decoy']}` | `{obs['naive_most_after_hours_id']}` "
            f"| `{', '.join(mo['top_suspect_ids'][:3])}` | `{', '.join(mo['suspected_decoy_ids'][:3])}` "
            f"| {mo['confidence']:.2f} | {ev['brier_score']:.4f} "
            f"| {'YES' if ev['top1_mole_correct'] else 'NO'} | {'YES' if ev['top1_decoy_correct'] else 'NO'} |"
        )

    lines.append("")
    lines.append(f"{h2} Visual Reasoning Excerpts")
    for w in results["worlds"]:
        mo = w["model_output"]
        lines.append(
            f"- **{w['tier'].upper()} Seed {w['seed']}** (`{w['raster_path']}`, conf `{mo['confidence']:.2f}`): "
            f"{_clean(mo['visual_reasoning'])}"
        )

    return _clean("\n".join(lines) + "\n")


def run_sweep(
    *,
    tier_seeds: dict[str, list[int]],
    tiers: list[str] | None = None,
    model_id: str = DEFAULT_MODEL,
    out_dir: Path = DEFAULT_OUT,
    thinking_level: str | None = None,
    max_retries: int | None = None,
    sdk_client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    ordered_tiers = list(tiers) if tiers is not None else list(tier_seeds.keys())
    out_dir = Path(out_dir)
    rasters_dir = out_dir / "rasters"
    rasters_dir.mkdir(parents=True, exist_ok=True)
    for old_png in rasters_dir.glob("*.png"):
        old_png.unlink()

    if sdk_client is None:
        sdk_client = genai_client()

    ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = git_sha()
    run_id = f"{FEATURE}:{SUBROLE}:{model_id}:{int(time.time())}"

    worlds: list[dict[str, Any]] = []
    raster_manifest: list[dict[str, Any]] = []

    for tier in ordered_tiers:
        for seed in tier_seeds[tier]:
            rel_png = f"rasters/{tier}_seed_{seed}.png"
            dst_png = out_dir / rel_png
            row = evaluate_world_seed(
                seed,
                tier=tier,
                model_id=model_id,
                sdk_client=sdk_client,
                run_id=run_id,
                out_raster_path=dst_png,
                max_retries=max_retries,
                thinking_level=thinking_level,
            )
            row["raster_path"] = rel_png
            conf = max(0.0, min(1.0, float(row["model_output"]["confidence"])))
            outcome = 1.0 if row["evaluation"]["top1_mole_correct"] else 0.0
            row["evaluation"] = dict(row["evaluation"])
            row["evaluation"]["brier_score"] = round((conf - outcome) ** 2, 6)
            row["evaluation"]["calibration_error"] = round(abs(conf - outcome), 6)
            row["evaluation"]["signed_confidence_gap"] = round(conf - outcome, 6)
            row["evaluation"]["mole_delta_vs_naive"] = int(row["evaluation"]["top1_mole_correct"]) - int(
                row["evaluation"]["naive_baseline_mole_correct"]
            )
            worlds.append(row)
            raster_manifest.append({
                "tier": tier,
                "seed": seed,
                "path": rel_png,
                "sha256": row["raster_sha256"],
                "bytes": row["raster_bytes"],
                "size": row["raster_size"],
            })

    by_tier = {
        t: compute_subset_metrics([w for w in worlds if w["tier"] == t])
        for t in ordered_tiers
    }
    overall_metrics = compute_subset_metrics(worlds)
    calibration_bins = compute_calibration_bins(worlds, n_bins=5)
    tot_usage = overall_metrics["usage"]

    cmd = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])
    tier_counts_txt = " + ".join(f"{len(tier_seeds[t])} {t}" for t in ordered_tiers)
    key_metric = (
        f"{len(worlds)} images ({tier_counts_txt}), "
        f"mole acc {overall_metrics['top1_mole_accuracy']:.0%} vs naive {overall_metrics['naive_baseline_mole_accuracy']:.0%}, "
        f"decoy acc {overall_metrics['top1_decoy_accuracy']:.0%}, Brier {overall_metrics['brier_score']:.4f}"
    )

    by_tier_summary = {
        t: {
            "n_worlds": by_tier[t]["n_worlds"],
            "seeds": by_tier[t]["seeds"],
            "top1_mole_accuracy": by_tier[t]["top1_mole_accuracy"],
            "top3_mole_hit_rate": by_tier[t]["top3_mole_hit_rate"],
            "top1_decoy_accuracy": by_tier[t]["top1_decoy_accuracy"],
            "avoided_framing_trap_rate": by_tier[t]["avoided_framing_trap_rate"],
            "naive_baseline_mole_accuracy": by_tier[t]["naive_baseline_mole_accuracy"],
            "mole_accuracy_delta_vs_naive": by_tier[t]["mole_accuracy_delta_vs_naive"],
            "mean_confidence": by_tier[t]["mean_confidence"],
            "brier_score": by_tier[t]["brier_score"],
            "expected_calibration_error": by_tier[t]["expected_calibration_error"],
        }
        for t in ordered_tiers
    }

    meta = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "commit": sha,
        "git_sha": sha,
        "timestamp": ts_iso,
        "command": _clean(cmd),
        "episode_count": len(worlds),
        "n_worlds": len(worlds),
        "n_images_read_by_model": len(worlds),
        "tiers_version": TIERS_VERSION,
        "tiers": ordered_tiers,
        "tier_seeds": {t: list(tier_seeds[t]) for t in ordered_tiers},
        "top1_mole_accuracy": overall_metrics["top1_mole_accuracy"],
        "top3_mole_hit_rate": overall_metrics["top3_mole_hit_rate"],
        "naive_baseline_mole_accuracy": overall_metrics["naive_baseline_mole_accuracy"],
        "mole_accuracy_delta_vs_naive": overall_metrics["mole_accuracy_delta_vs_naive"],
        "top1_decoy_accuracy": overall_metrics["top1_decoy_accuracy"],
        "avoided_framing_trap_rate": overall_metrics["avoided_framing_trap_rate"],
        "mean_confidence": overall_metrics["mean_confidence"],
        "brier_score": overall_metrics["brier_score"],
        "expected_calibration_error": overall_metrics["expected_calibration_error"],
        "by_tier": by_tier_summary,
        "key_metric": key_metric,
        "fake_env": False,
        "smoke": False,
        "ledger_run_id": run_id,
        "rasters": raster_manifest,
        "usage": tot_usage,
    }

    results = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "commit": sha,
        "timestamp": ts_iso,
        "tiers_version": TIERS_VERSION,
        "tiers": ordered_tiers,
        "tier_seeds": {t: list(tier_seeds[t]) for t in ordered_tiers},
        "episode_count": len(worlds),
        "n_worlds": len(worlds),
        "n_images_read_by_model": len(worlds),
        "metrics": overall_metrics,
        "by_tier": by_tier,
        "calibration_bins": calibration_bins,
        "usage": tot_usage,
        "worlds": worlds,
    }

    (out_dir / "meta.json").write_text(_clean(json.dumps(meta, indent=2)) + "\n", encoding="utf-8")
    (out_dir / "results.json").write_text(_clean(json.dumps(results, indent=2)) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(_build_summary_md(meta, results), encoding="utf-8")

    return {"meta": meta, "results": results}


def main(argv: list[str] | None = None, *, sdk_client: Any = None) -> int:
    ap = argparse.ArgumentParser(
        description="Run multi-tier v1.4 Security-SOC Access & Framing Raster Vision sweep."
    )
    ap.add_argument("--tiers", default=DEFAULT_TIERS)
    ap.add_argument("--seeds", default=DEFAULT_SEEDS)
    ap.add_argument("--medium-seeds", default=None)
    ap.add_argument("--hard-seeds", default=None)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--max-retries", type=int, default=None)
    args = ap.parse_args(argv)

    tiers = _parse_tiers(args.tiers)
    default_seed_list = parse_seeds(args.seeds)
    tier_seeds: dict[str, list[int]] = {}
    for t in tiers:
        if t == "medium" and args.medium_seeds is not None:
            tier_seeds[t] = parse_seeds(args.medium_seeds)
        elif t == "hard" and args.hard_seeds is not None:
            tier_seeds[t] = parse_seeds(args.hard_seeds)
        else:
            tier_seeds[t] = list(default_seed_list)

    retries = args.max_retries
    if retries is None and os.environ.get("CANARY_LLM_MAX_RETRIES"):
        retries = int(os.environ["CANARY_LLM_MAX_RETRIES"])

    raw_argv = argv if argv is not None else sys.argv[1:]
    prefix = (
        f"CANARY_LLM_MAX_RETRIES={os.environ['CANARY_LLM_MAX_RETRIES']} "
        if os.environ.get("CANARY_LLM_MAX_RETRIES")
        else ""
    )
    cmd_str = (
        f"{prefix}PYTHONPATH=. {sys.executable} scripts/run_access_vision_sweep.py "
        + " ".join(shlex.quote(x) for x in raw_argv)
    ).strip()

    bundle = run_sweep(
        tier_seeds=tier_seeds,
        tiers=tiers,
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
        f"access_vision_sweep: worlds={bundle['results']['n_worlds']} "
        f"mole_top1={m['top1_mole_hits']}/{bundle['results']['n_worlds']} ({m['top1_mole_accuracy']:.1%}) "
        f"naive_mole={m['naive_baseline_mole_hits']}/{bundle['results']['n_worlds']} ({m['naive_baseline_mole_accuracy']:.1%}) "
        f"decoy_top1={m['top1_decoy_hits']}/{bundle['results']['n_worlds']} ({m['top1_decoy_accuracy']:.1%}) "
        f"brier={m['brier_score']:.4f} "
        f"images={bundle['meta']['n_images_read_by_model']} "
        f"in={u['in']} out={u['out']} think={u['thinking']} cost=${u['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
