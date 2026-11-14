from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini.visual_forensics import (
    DEFAULT_MODEL,
    FEATURE,
    SUBROLE,
    analyze_chart_bytes,
    render_forensic_chart,
    sanitize_text,
    score_diagnosis,
    select_forensic_episodes,
    summarize_forensics,
)

DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "belief-chart-forensics-carbon"
DEFAULT_V13_DIR = ROOT / "data" / "runs" / "committed" / "v1.3"


def current_git_commit() -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return res.stdout.strip()


def format_summary_md(meta: dict[str, Any], records: list[dict[str, Any]]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3
    usage = meta["usage"]
    n = meta["n_charts_analyzed"]
    thr_cnt = sum(1 for r in records if r["scoring"]["threshold_match"])
    day1_cnt = sum(1 for r in records if r["scoring"]["day_within_1"])
    day0_cnt = sum(1 for r in records if r["scoring"]["day_exact"])
    gap_cnt = sum(1 for r in records if r["scoring"]["bleed_gap_match"])

    lines = [
        f"{h1} Multimodal Belief and Value-Bleed Chart Forensics ({meta['model_id']})",
        "",
        f"- **Role:** `{meta['role']}` (`{meta['subrole']}`)",
        f"- **Model:** `{meta['model_id']}` via `google.genai.types.Part.from_bytes(mime_type=\"image/png\")`",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Ledger run_id:** `{meta['ledger_run_id']}`",
        f"- **Replay rules:** `canary.rules.tiers_version(\"{meta['tiers_version']}\")`",
        f"- **Charts analyzed:** `{n}` (3 wrong/premature accusations + 3 high-scoring episodes from `data/runs/committed/v1.3/`)",
        f"- **Visual EV-threshold accuracy:** `{thr_cnt}/{n}` (`{meta['visual_threshold_accuracy']:.3f}`)",
        f"- **Accusation-day accuracy (|est - actual| <= 1):** `{day1_cnt}/{n}` (`{meta['accuse_day_within_1_accuracy']:.3f}`; exact match `{day0_cnt}/{n}`)",
        f"- **Hidden-bleed gap accuracy:** `{gap_cnt}/{n}` (`{meta['hidden_bleed_gap_accuracy']:.3f}`)",
        f"- **Total Gemini usage:** `{usage['calls']}` calls, `{usage['in']}` input tokens, `{usage['out']}` output tokens, `{usage['thinking']}` thinking tokens, `${usage['cost_usd']:.6f}` USD, `{usage['latency_s']:.2f}` s",
        "",
        f"{h2} Visual Reading vs Solver Ground Truth",
        "",
        "| Chart | Cohort | Agent / Tier / Seed | Score | GT P(accused) vs 1/(1+V) | GT Below EV | Gemini Below EV | Actual Day | Gemini Day | GT Bleed Gap | Gemini Bleed | Primary Pattern |",
        "|---|---|---|---:|---|---|---|---|---:|---|---|---|",
    ]

    for rec in records:
        src = rec["source_episode"]
        gt = rec["ground_truth"]
        gm = rec["gemini_diagnosis"]
        lines.append(
            f"| `{rec['chart_path']}` | {rec['cohort']} | `{src['agent']}` / `{src['tier']}` / `{src['seed']}` | "
            f"{gt['score']:+.3f} | {gt['accused_posterior_at_accuse']:.3f} vs {gt['ev_threshold_at_accuse']:.3f} | "
            f"`{gt['accused_below_ev_threshold']}` | `{gm['accused_below_ev_threshold']}` | "
            f"{gt['actual_accuse_day']} | {gm['estimated_accuse_day']} | "
            f"`{gt['hidden_bleed_gap_present']}` ({gt['max_bleed_gap']:.3f}) | `{gm['hidden_bleed_gap_present']}` | "
            f"`{gm['primary_failure_pattern']}` |"
        )

    lines.extend(["", f"{h2} Per-Chart Multimodal Forensic Diagnoses", ""])
    for rec in records:
        src = rec["source_episode"]
        gt = rec["ground_truth"]
        gm = rec["gemini_diagnosis"]
        sc = rec["scoring"]
        lines.extend(
            [
                f"{h3} Episode {rec['episode_index']} (`{rec['chart_path']}`): `{src['agent']}` on `{src['tier']}` seed `{src['seed']}` ({rec['cohort']})",
                f"- **Ground truth:** accused `{gt['accused_employee']}` on day `{gt['actual_accuse_day']}` (correct=`{gt['correct']}`, score=`{gt['score']:+.3f}`), `P(accused)={gt['accused_posterior_at_accuse']:.3f}` vs `1/(1+V)={gt['ev_threshold_at_accuse']:.3f}` (`below_ev={gt['accused_below_ev_threshold']}`), `max_bleed_gap={gt['max_bleed_gap']:.3f}` (`bleed={gt['hidden_bleed_gap_present']}`), canaries planted=`{gt['total_canaries_planted']}`.",
                f"- **Gemini visual output:** `accused_below_ev_threshold={gm['accused_below_ev_threshold']}` (match=`{sc['threshold_match']}`), `estimated_accuse_day={gm['estimated_accuse_day']}` (abs_err=`{sc['day_abs_error']}`, within_1=`{sc['day_within_1']}`), `hidden_bleed_gap_present={gm['hidden_bleed_gap_present']}` (match=`{sc['bleed_gap_match']}`), pattern=`{gm['primary_failure_pattern']}`.",
                f"- **Visual diagnosis:** {sanitize_text(gm['visual_diagnosis'])}",
                "",
            ]
        )

    return sanitize_text("\n".join(lines).rstrip() + "\n")


def run_forensics(
    v13_dir: Path = DEFAULT_V13_DIR,
    out_dir: Path = DEFAULT_OUT,
    model_id: str = DEFAULT_MODEL,
    sdk_client: Any = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    run_id = os.environ.get("CANARY_GEMINI_RUN_ID") or f"multimodal-forensics-{ts.strftime('%Y%m%dT%H%M%SZ')}"
    commit = current_git_commit()

    trajectories = select_forensic_episodes(v13_dir, n_wrong=3, n_high=3)
    records: list[dict[str, Any]] = []

    for idx, traj in enumerate(trajectories):
        rel_chart = f"charts/ep_{idx}.png"
        chart_file = out_dir / rel_chart
        png_bytes = render_forensic_chart(traj, out_path=chart_file)
        diagnosis, call_usage = analyze_chart_bytes(
            png_bytes=png_bytes,
            model_id=model_id,
            run_id=run_id,
            chart_label=f"ep_{idx}",
            sdk_client=sdk_client,
        )
        scoring = score_diagnosis(traj, diagnosis)
        records.append(
            {
                "episode_index": idx,
                "cohort": traj.cohort,
                "chart_path": rel_chart,
                "chart_bytes_len": len(png_bytes),
                "chart_sha256": hashlib.sha256(png_bytes).hexdigest(),
                "source_episode": {
                    "source_file": traj.source_file,
                    "tier": traj.tier,
                    "seed": traj.seed,
                    "agent": traj.agent,
                },
                "ground_truth": traj.ground_truth(),
                "gemini_diagnosis": diagnosis,
                "scoring": scoring,
                "usage": call_usage,
            }
        )
        print(
            f"[ep_{idx}] {traj.cohort} {traj.agent} {traj.tier} seed={traj.seed} "
            f"below_ev={diagnosis['accused_below_ev_threshold']}(gt={traj.accused_below_ev_threshold}) "
            f"day={diagnosis['estimated_accuse_day']}(gt={traj.actual_accuse_day}) "
            f"bleed={diagnosis['hidden_bleed_gap_present']}(gt={traj.hidden_bleed_gap_present})",
            flush=True,
        )

    agg = summarize_forensics(records)
    cmd = command_str or (
        "CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python "
        + " ".join(sys.argv)
    )
    meta = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "commit": commit,
        "timestamp": ts_iso,
        "command": sanitize_text(cmd),
        "tiers_version": "v1.3",
        "ledger_run_id": run_id,
        "n_charts_analyzed": agg["n_charts_analyzed"],
        "visual_threshold_accuracy": agg["visual_threshold_accuracy"],
        "accuse_day_within_1_accuracy": agg["accuse_day_within_1_accuracy"],
        "accuse_day_exact_accuracy": agg["accuse_day_exact_accuracy"],
        "hidden_bleed_gap_accuracy": agg["hidden_bleed_gap_accuracy"],
        "usage": agg["usage"],
    }

    (out_dir / "meta.json").write_text(sanitize_text(json.dumps(meta, indent=2) + "\n"))
    (out_dir / "diagnoses.json").write_text(sanitize_text(json.dumps(records, indent=2) + "\n"))
    (out_dir / "summary.md").write_text(format_summary_md(meta, records))
    return {"meta": meta, "records": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v13-dir", type=Path, default=DEFAULT_V13_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    args = parser.parse_args(argv)
    res = run_forensics(v13_dir=args.v13_dir, out_dir=args.out_dir, model_id=args.model)
    print(json.dumps(res["meta"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
