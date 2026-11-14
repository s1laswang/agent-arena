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
from canary.gemini.incident_dossier import (
    DEFAULT_MODEL,
    FEATURE,
    SUBROLE,
    evaluate_dossier_world,
    seed_tag_for,
)
from canary.gemini.sdk import genai_client
from canary.rules import TIERS_VERSION

DEFAULT_OUT = Path("results/gemini_roles/multimodal_evidence/multi-image-dossier-carbon")
DEFAULT_WORLDS = "medium:0,medium:1,medium:2,hard:0,hard:1"


def _clean(text: str) -> str:
    return (text or "").replace("\u2014", "-").replace("\u2013", "-")


def parse_world_specs(worlds_spec: str | None, tier: str | None = None, seeds: str | None = None) -> list[tuple[str, int]]:
    if worlds_spec and worlds_spec.strip():
        out: list[tuple[str, int]] = []
        for token in worlds_spec.split(","):
            tok = token.strip()
            if not tok:
                continue
            if ":" not in tok:
                raise ValueError(f"world token must be <tier>:<seed>, got {tok!r}")
            t_raw, s_raw = tok.split(":", 1)
            t_clean = t_raw.strip().lower()
            for s in parse_seeds(s_raw.strip()):
                out.append((t_clean, int(s)))
        if not out:
            raise ValueError("no worlds parsed from --worlds")
        return out
    resolved_tier = (tier or "medium").strip().lower()
    seed_list = parse_seeds(seeds or "0,1,2")
    return [(resolved_tier, int(s)) for s in seed_list]


def _build_summary_md(meta: dict[str, Any], results: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    m = results["metrics"]
    u = meta["usage"]
    n_w = results["episode_count"]
    lines = [
        f"{h1} Role 6 ({meta['role']}) - Multi-Image Composite Incident Dossier Run",
        "",
        f"{h2} Provenance",
        f"- Role: `{meta['role']}` (`{meta['subrole']}`)",
        f"- Model: `{meta['model_id']}`",
        f"- Tiers version: `{meta['tiers_version']}` (`{n_w}` composite dossiers across `medium` seeds `0,1,2` and `hard` seeds `0,1`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Command: `{meta['command']}`",
        f"- Composite dossiers evaluated (`episode_count`): `{meta['episode_count']}`",
        f"- Images read by model (`Part.from_bytes`, `image/png`, `3` distinct PNGs per single call): `{meta['n_images_read_by_model']}`",
        f"- Token usage: `calls={u['calls']}`, `in={u['in']}`, `out={u['out']}`, `thinking={u['thinking']}`, `cached={u['cached']}`, `cost_usd={u['cost_usd']:.6f}`, `latency_s={u['latency_s']:.2f}`",
        "",
        f"{h2} Multi-Image Fusion vs Single-Image Baselines",
        "| Approach | Inputs Available | Top-1 Mole Accuracy | Top-1 Framed Decoy Accuracy | Avoided Framing Trap |",
        "|---|---|---|---|---|",
        (
            f"| **Gemini 3-Image Joint Dossier (`{meta['model_id']}`)** | **Exhibit 1 + Exhibit 2 + Exhibit 3 (`3` PNGs in 1 call)** | "
            f"**{m['top1_mole_hits']}/{n_w} ({m['top1_mole_accuracy']:.1%})** | "
            f"**{m['top1_decoy_hits']}/{n_w} ({m['top1_decoy_accuracy']:.1%})** | "
            f"**{m['avoided_framing_trap_hits']}/{n_w} ({m['avoided_framing_trap_rate']:.1%})** |"
        ),
        (
            f"| Exhibit 1 Only (Naive After-Hours Swipe Pick) | `badge_raster` PNG only (no canary roster, no leak feed) | "
            f"{m['image1_only_mole_hits']}/{n_w} ({m['image1_only_mole_accuracy']:.1%}) | - | "
            f"{n_w - m['image1_only_decoy_traps']}/{n_w} ({1.0 - m['image1_only_decoy_trap_rate']:.1%}) |"
        ),
        (
            f"| Exhibit 2 Only (Leaked Memo Scans Only) | `leaked_memo_scans` PNG only (no employee IDs) | "
            f"0/{n_w} ({m['image2_only_mole_accuracy']:.1%}) | 0/{n_w} (0.0%) | - |"
        ),
        (
            f"| Exhibit 3 Only (Static Floorplan + Canary Matrix) | `org_canary_map` PNG only (no leak outcomes, uniform `1/N` prior = {m['image3_only_uniform_prior_mean']:.1%}) | "
            f"{m['image3_only_deterministic_hits']}/{n_w} ({m['image3_only_deterministic_mole_accuracy']:.1%}) | 0/{n_w} (0.0%) | - |"
        ),
        "",
        f"- Exhibit 2 visual watermark scan readout exact match (`DOC-ID` + `COPY-CODE`): `{m['memo_scans_matched_total']}/{m['memo_scans_expected_total']}` (`{m['memo_scan_readout_accuracy']:.1%}`)",
        f"- Exhibit 3 floorplan department attribution accuracy: `{m['suspect_dept_hits']}/{n_w}` (`{m['suspect_dept_accuracy']:.1%}`)",
        "",
        f"{h2} Per-World Cross-Image Breakdown",
        "| World | True Mole (Dept) | True Decoy | Img-1 Naive Pick | Leaked Canaries (Img 2) | Pred Mole Top-3 | Pred Decoy | Mole Top-1 | Decoy Top-1 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for w in results["worlds"]:
        gt = w["ground_truth"]
        mo = w["model_output"]
        ev = w["evaluation"]
        sb = w["single_image_baselines"]
        scans_str = ", ".join(f"{sc['doc_id']}={sc['variant']}" for sc in w["observable_summary"]["leaked_canary_scans"])
        lines.append(
            f"| `{w['seed_tag']}` | `{gt['true_mole']}` ({gt['true_mole_dept']}) | `{gt['true_decoy']}` "
            f"| `{sb['image1_only_naive_after_hours_pick']}` | `{scans_str}` "
            f"| `{', '.join(mo['top_suspect_ids'][:3])}` | `{', '.join(mo['suspected_decoy_ids'][:2])}` "
            f"| {'YES' if ev['top1_mole_correct'] else 'NO'} | {'YES' if ev['top1_decoy_correct'] else 'NO'} |"
        )

    lines.extend([
        "",
        f"{h2} Rendered Composite Dossier PNGs ({meta['n_images_read_by_model']} Files)",
        "| World | Exhibit | Path | Dimensions | Bytes | SHA-256 |",
        "|---|---|---|---|---|---|",
    ])
    for d_entry in meta["dossiers"]:
        for img_item in d_entry["images"]:
            iw, ih = img_item["size"]
            lines.append(
                f"| `{d_entry['seed_tag']}` | `{img_item['kind']}` | `{img_item['path']}` "
                f"| {iw}x{ih} | {img_item['bytes']} | `{img_item['sha256']}` |"
            )

    lines.append("")
    lines.append(f"{h2} Cross-Image Forensic Reasoning Excerpts")
    for w in results["worlds"]:
        mo = w["model_output"]
        lines.append(
            f"- **`{w['seed_tag']}`** (conf `{mo['confidence']:.2f}`, dept `{mo['suspect_department']}`): "
            f"{_clean(mo['cross_image_reasoning'])}"
        )

    return _clean("\n".join(lines) + "\n")


def run_dossier_evaluation(
    *,
    world_specs: list[tuple[str, int]],
    model_id: str = DEFAULT_MODEL,
    out_dir: Path = DEFAULT_OUT,
    thinking_level: str | None = None,
    max_retries: int | None = None,
    sdk_client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    out_dir = Path(out_dir)
    dossiers_dir = out_dir / "dossiers"
    dossiers_dir.mkdir(parents=True, exist_ok=True)

    if sdk_client is None:
        sdk_client = genai_client()

    ts_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sha = git_sha()
    run_id = f"{FEATURE}:{SUBROLE}:{model_id}:{int(time.time())}"

    tiers_present = {t for t, _ in world_specs}
    use_tier_prefix = len(tiers_present) > 1 or len(world_specs) != len({s for _, s in world_specs})

    worlds: list[dict[str, Any]] = []
    dossier_manifest: list[dict[str, Any]] = []
    tot_usage = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "cost_usd": 0.0, "latency_s": 0.0}

    for tier_name, seed_num in world_specs:
        s_tag = seed_tag_for(tier_name, seed_num, multi_tier=True if use_tier_prefix else True)
        row = evaluate_dossier_world(
            seed_num,
            tier=tier_name,
            seed_tag=s_tag,
            model_id=model_id,
            sdk_client=sdk_client,
            run_id=run_id,
            out_dossiers_dir=dossiers_dir,
            rel_dossiers_prefix="dossiers",
            max_retries=max_retries,
            thinking_level=thinking_level,
        )
        worlds.append(row)
        ordered_imgs = [
            row["images"]["badge_raster"],
            row["images"]["leaked_memo_scans"],
            row["images"]["org_canary_map"],
        ]
        dossier_manifest.append({
            "tier": tier_name,
            "seed": seed_num,
            "seed_tag": s_tag,
            "n_images": 3,
            "images": ordered_imgs,
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
    n_images_total = 3 * len(worlds)

    top1_mole_hits = sum(1 for w in worlds if w["evaluation"]["top1_mole_correct"])
    top3_mole_hits = sum(1 for w in worlds if w["evaluation"]["top3_mole_hit"])
    top1_decoy_hits = sum(1 for w in worlds if w["evaluation"]["top1_decoy_correct"])
    decoy_id_hits = sum(1 for w in worlds if w["evaluation"]["decoy_identified"])
    avoid_trap_hits = sum(1 for w in worlds if w["evaluation"]["avoided_framing_trap"])
    dept_hits = sum(1 for w in worlds if w["evaluation"]["suspect_dept_correct"])
    scans_matched = sum(int(w["evaluation"]["memo_scans_matched"]) for w in worlds)
    scans_total = sum(int(w["evaluation"]["memo_scans_total"]) for w in worlds)

    img1_mole_hits = sum(1 for w in worlds if w["single_image_baselines"]["image1_only_mole_correct"])
    img1_decoy_traps = sum(1 for w in worlds if w["single_image_baselines"]["image1_only_trapped_by_decoy"])
    img3_det_hits = sum(1 for w in worlds if w["single_image_baselines"]["image3_only_mole_correct"])
    img3_prior_mean = sum(float(w["single_image_baselines"]["image3_only_uniform_prior"]) for w in worlds) / n

    top1_mole_acc = round(top1_mole_hits / n, 4)
    top1_decoy_acc = round(top1_decoy_hits / n, 4)

    cmd = command_str or " ".join(shlex.quote(x) for x in [sys.executable, *sys.argv])

    meta = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "commit": sha,
        "git_sha": sha,
        "timestamp": ts_iso,
        "command": _clean(cmd),
        "tiers_version": TIERS_VERSION,
        "episode_count": len(worlds),
        "n_images_read_by_model": n_images_total,
        "images_per_call": 3,
        "top1_mole_accuracy": top1_mole_acc,
        "top1_decoy_accuracy": top1_decoy_acc,
        "fake_env": False,
        "smoke": False,
        "worlds": [{"tier": t, "seed": s, "seed_tag": seed_tag_for(t, s, multi_tier=True)} for t, s in world_specs],
        "ledger_run_id": run_id,
        "dossiers": dossier_manifest,
        "usage": tot_usage,
    }

    results = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "commit": sha,
        "timestamp": ts_iso,
        "tiers_version": TIERS_VERSION,
        "episode_count": len(worlds),
        "n_images_read_by_model": n_images_total,
        "images_per_call": 3,
        "metrics": {
            "top1_mole_hits": top1_mole_hits,
            "top1_mole_accuracy": top1_mole_acc,
            "top3_mole_hits": top3_mole_hits,
            "top3_mole_hit_rate": round(top3_mole_hits / n, 4),
            "top1_decoy_hits": top1_decoy_hits,
            "top1_decoy_accuracy": top1_decoy_acc,
            "decoy_identified_hits": decoy_id_hits,
            "decoy_identified_rate": round(decoy_id_hits / n, 4),
            "avoided_framing_trap_hits": avoid_trap_hits,
            "avoided_framing_trap_rate": round(avoid_trap_hits / n, 4),
            "memo_scans_matched_total": scans_matched,
            "memo_scans_expected_total": scans_total,
            "memo_scan_readout_accuracy": round(scans_matched / max(1, scans_total), 4),
            "suspect_dept_hits": dept_hits,
            "suspect_dept_accuracy": round(dept_hits / n, 4),
            "image1_only_mole_hits": img1_mole_hits,
            "image1_only_mole_accuracy": round(img1_mole_hits / n, 4),
            "image1_only_decoy_traps": img1_decoy_traps,
            "image1_only_decoy_trap_rate": round(img1_decoy_traps / n, 4),
            "image2_only_mole_accuracy": 0.0,
            "image2_only_decoy_accuracy": 0.0,
            "image3_only_deterministic_hits": img3_det_hits,
            "image3_only_deterministic_mole_accuracy": round(img3_det_hits / n, 4),
            "image3_only_uniform_prior_mean": round(img3_prior_mean, 4),
        },
        "usage": tot_usage,
        "worlds": worlds,
    }

    (out_dir / "meta.json").write_text(_clean(json.dumps(meta, indent=2)) + "\n", encoding="utf-8")
    (out_dir / "results.json").write_text(_clean(json.dumps(results, indent=2)) + "\n", encoding="utf-8")
    (out_dir / "summary.md").write_text(_build_summary_md(meta, results), encoding="utf-8")

    return {"meta": meta, "results": results}


def main(argv: list[str] | None = None, *, sdk_client: Any = None) -> int:
    ap = argparse.ArgumentParser(description="Run Multi-Image Composite Incident Dossier evaluation.")
    ap.add_argument("--worlds", default=None, help="Comma-separated <tier>:<seed> specs (default: medium:0,medium:1,medium:2,hard:0,hard:1)")
    ap.add_argument("--tier", default=None, help="Single tier override when --worlds is omitted")
    ap.add_argument("--seeds", default=None, help="Seeds override when --worlds is omitted")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--max-retries", type=int, default=None)
    args = ap.parse_args(argv)

    if args.worlds is None and args.tier is None and args.seeds is None:
        world_specs = parse_world_specs(DEFAULT_WORLDS)
    else:
        world_specs = parse_world_specs(args.worlds, tier=args.tier, seeds=args.seeds)

    retries = args.max_retries
    if retries is None and os.environ.get("CANARY_LLM_MAX_RETRIES"):
        retries = int(os.environ["CANARY_LLM_MAX_RETRIES"])

    raw_argv = argv if argv is not None else sys.argv[1:]
    prefix = (
        f"CANARY_LLM_MAX_RETRIES={os.environ['CANARY_LLM_MAX_RETRIES']} "
        if os.environ.get("CANARY_LLM_MAX_RETRIES")
        else ""
    )
    cmd_str = f"{prefix}PYTHONPATH=. {sys.executable} scripts/run_incident_dossier.py " + " ".join(
        shlex.quote(x) for x in raw_argv
    )
    cmd_str = cmd_str.strip()

    bundle = run_dossier_evaluation(
        world_specs=world_specs,
        model_id=args.model,
        out_dir=args.out,
        thinking_level=args.thinking_level,
        max_retries=retries,
        sdk_client=sdk_client,
        command_str=cmd_str,
    )
    m = bundle["results"]["metrics"]
    u = bundle["meta"]["usage"]
    n_ep = bundle["meta"]["episode_count"]
    print(
        f"incident_dossier: dossiers={n_ep} "
        f"images={bundle['meta']['n_images_read_by_model']} "
        f"mole_top1={m['top1_mole_hits']}/{n_ep} "
        f"decoy_top1={m['top1_decoy_hits']}/{n_ep} "
        f"in={u['in']} out={u['out']} think={u['thinking']} cost=${u['cost_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
