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

from canary.gemini.carbon_forensics import (
    DEFAULT_MODEL,
    DEFAULT_VERSION,
    FEATURE,
    SUBROLE,
    analyze_carbon_chart_bytes,
    render_carbon_forensic_chart,
    sanitize_text,
    score_carbon_diagnosis,
    select_carbon_episodes,
    summarize_carbon_forensics,
)

DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "multimodal_evidence" / "carbon-trajectory-forensics"
DEFAULT_RUNS_DIR = ROOT / "data" / "runs" / "committed" / "v1.4"


def git_rev_parse(ref: str = "HEAD") -> str:
    res = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    return res.stdout.strip()


def normalize_runs_label(runs_dir: Path) -> str:
    posix = runs_dir.as_posix()
    marker = "data/runs/committed/v1.4"
    if marker in posix:
        return posix[posix.index(marker):]
    try:
        return runs_dir.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return posix


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
    lag_cnt = sum(1 for r in records if r["scoring"]["entropy_lag_match"])
    pat_cnt = sum(1 for r in records if r["scoring"]["outcome_pattern_match"])

    lines = [
        f"{h1} Multimodal 4-Panel Trajectory Forensics on Real v1.4 Investigator Runs ({meta['model_id']})",
        "",
        f"- **Role:** `{meta['role']}` (`{meta['subrole']}`)",
        f"- **Model:** `{meta['model_id']}` via `google.genai.types.Part.from_bytes(mime_type=\"image/png\")`",
        f"- **Commit:** `{meta['commit']}`",
        f"- **Source v1.4 investigator runs:** `{meta['source_runs_dir']}` (branch `{meta['source_runs_branch']}`, commit `{meta['source_runs_commit']}`)",
        f"- **Timestamp:** `{meta['timestamp']}`",
        f"- **Ledger run_id:** `{meta['ledger_run_id']}`",
        f"- **Replay rules:** `canary.rules.tiers_version(\"{meta['tiers_version']}\")` (hard: 40 staff, 21 days, up to 2 canaries/day; medium: 20 staff, 14 days)",
        f"- **Charts analyzed:** `{n}`",
        f"- **Visual EV-threshold accuracy:** `{thr_cnt}/{n}` (`{meta['visual_threshold_accuracy']:.3f}`)",
        f"- **Accusation/stop-day accuracy (|est - actual| <= 1):** `{day1_cnt}/{n}` (`{meta['accuse_day_within_1_accuracy']:.3f}`; exact match `{day0_cnt}/{n}`)",
        f"- **Hidden-bleed gap accuracy:** `{gap_cnt}/{n}` (`{meta['hidden_bleed_gap_accuracy']:.3f}`)",
        f"- **Entropy-lag vs SolverPolicy accuracy:** `{lag_cnt}/{n}` (`{meta['entropy_lag_accuracy']:.3f}`)",
        f"- **Failure/outcome pattern consistency:** `{pat_cnt}/{n}` (`{meta['outcome_pattern_accuracy']:.3f}`)",
        f"- **Total Gemini usage:** `{usage['calls']}` calls, `{usage['in']}` input tokens, `{usage['out']}` output tokens, `{usage['thinking']}` thinking tokens, `${usage['cost_usd']:.6f}` USD, `{usage['latency_s']:.2f}` s",
        "",
        f"{h2} Visual Forensics vs Exact v1.4 Solver Ground Truth",
        "",
        "| Chart | Cohort | Tier / Seed | Score | GT P(stop) vs 1/(1+V) | GT Below EV | Gemini Below EV | Stop Day (GT / Gem) | Solver Day | GT Lag / Gem Lag | GT Bleed | Gem Bleed | Primary Pattern |",
        "|---|---|---|---:|---|---|---|---|---:|---|---|---|---|",
    ]

    for rec in records:
        src = rec["source_episode"]
        gt = rec["ground_truth"]
        gm = rec["gemini_diagnosis"]
        lines.append(
            f"| `{rec['chart_path']}` | {rec['cohort']} | `{src['tier']}` / `{src['seed']}` | "
            f"{gt['score']:+.3f} | {gt['accused_posterior_at_accuse']:.3f} vs {gt['ev_threshold_at_accuse']:.3f} | "
            f"`{gt['accused_below_ev_threshold']}` | `{gm['accused_below_ev_threshold']}` | "
            f"{gt['actual_accuse_day']} / {gm['estimated_accuse_day']} | {gt['solver_accuse_day']} | "
            f"`{gt['entropy_lags_solver']}` / `{gm['entropy_lags_solver']}` | "
            f"`{gt['hidden_bleed_gap_present']}` ({gt['max_bleed_gap']:.3f}) | `{gm['hidden_bleed_gap_present']}` | "
            f"`{gm['primary_failure_pattern']}` |"
        )

    lines.extend(["", f"{h2} Per-Episode 4-Panel Trajectory Forensic Readings", ""])
    for rec in records:
        src = rec["source_episode"]
        gt = rec["ground_truth"]
        gm = rec["gemini_diagnosis"]
        sc = rec["scoring"]
        lines.extend(
            [
                f"{h3} Episode {rec['episode_index']} (`{rec['chart_path']}`): `{src['agent']}` on `{src['tier']}` seed `{src['seed']}` ({rec['cohort']})",
                f"- **Ground truth:** end=`{gt['end_reason']}`, accused=`{gt['accused_employee']}`, true_mole=`{gt['true_mole']}`, decoy=`{gt['framed_decoy']}`, day=`{gt['actual_accuse_day']}` (correct=`{gt['correct']}`, score=`{gt['score']:+.3f}`), `P(stop)={gt['accused_posterior_at_accuse']:.3f}` vs `1/(1+V)={gt['ev_threshold_at_accuse']:.3f}` (`below_ev={gt['accused_below_ev_threshold']}`), `max_bleed_gap={gt['max_bleed_gap']:.3f}`, canaries=`{gt['total_canaries_planted']}` (max `{gt['max_daily_canaries_planted']}`/day), `H_end={gt['final_entropy_bits']:.2f}` bits vs Solver day `{gt['solver_accuse_day']}` (`score={gt['solver_score']:+.3f}`, `entropy_lags_solver={gt['entropy_lags_solver']}`).",
                f"- **Gemini visual diagnosis:** `accused_below_ev_threshold={gm['accused_below_ev_threshold']}` (match=`{sc['threshold_match']}`), `estimated_accuse_day={gm['estimated_accuse_day']}` (abs_err=`{sc['day_abs_error']}`), `hidden_bleed_gap_present={gm['hidden_bleed_gap_present']}` (match=`{sc['bleed_gap_match']}`), `entropy_lags_solver={gm['entropy_lags_solver']}` (match=`{sc['entropy_lag_match']}`), pattern=`{gm['primary_failure_pattern']}` (match=`{sc['outcome_pattern_match']}`).",
                f"- **Fooled-step / trajectory summary:** {sanitize_text(gm['fooled_step_summary'])}",
                "",
            ]
        )

    return sanitize_text("\n".join(lines).rstrip() + "\n")


def run_carbon_forensics(
    runs_dir: Path = DEFAULT_RUNS_DIR,
    out_dir: Path = DEFAULT_OUT,
    model_id: str = DEFAULT_MODEL,
    n_wrong: int = 3,
    n_high: int = 4,
    source_branch: str | None = None,
    source_commit: str | None = None,
    sdk_client: Any = None,
    command_str: str | None = None,
    dpi: int = 160,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = out_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    run_id = os.environ.get("CANARY_GEMINI_RUN_ID") or f"carbon-trajectory-forensics-{ts.strftime('%Y%m%dT%H%M%SZ')}"
    commit = git_rev_parse("HEAD")
    src_branch = source_branch or "HEAD"
    src_commit = source_commit or (git_rev_parse(src_branch) if src_branch != "HEAD" else commit)

    trajectories = select_carbon_episodes(runs_dir, n_wrong=n_wrong, n_high=n_high, version=DEFAULT_VERSION)
    if not trajectories:
        raise RuntimeError(f"No v1.4 {DEFAULT_MODEL} episodes found under {runs_dir}")

    records: list[dict[str, Any]] = []
    for idx, traj in enumerate(trajectories):
        rel_chart = f"charts/ep_{idx}_{traj.tier}_seed{traj.seed}.png"
        chart_file = out_dir / rel_chart
        png_bytes = render_carbon_forensic_chart(traj, out_path=chart_file, dpi=dpi)
        diagnosis, call_usage = analyze_carbon_chart_bytes(
            png_bytes=png_bytes,
            model_id=model_id,
            run_id=run_id,
            chart_label=f"ep_{idx}_{traj.tier}_seed{traj.seed}",
            sdk_client=sdk_client,
        )
        scoring = score_carbon_diagnosis(traj, diagnosis)
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
                    "tiers_version": traj.tiers_version,
                },
                "ground_truth": traj.ground_truth(),
                "gemini_diagnosis": diagnosis,
                "scoring": scoring,
                "usage": call_usage,
            }
        )
        print(
            f"[ep_{idx}] {traj.cohort} {traj.tier} seed={traj.seed} "
            f"below_ev={diagnosis['accused_below_ev_threshold']}(gt={traj.accused_below_ev_threshold}) "
            f"day={diagnosis['estimated_accuse_day']}(gt={traj.actual_accuse_day}) "
            f"bleed={diagnosis['hidden_bleed_gap_present']}(gt={traj.hidden_bleed_gap_present}) "
            f"lag={diagnosis['entropy_lags_solver']}(gt={traj.entropy_lags_solver}) "
            f"pat={diagnosis['primary_failure_pattern']}",
            flush=True,
        )

    agg = summarize_carbon_forensics(records)
    cmd = command_str or (
        "CANARY_LLM_MAX_RETRIES=10 PYTHONPATH=. /tmp/fleet-silas/canary-venv/bin/python "
        + " ".join(sys.argv)
    )
    meta = {
        "role": FEATURE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "commit": commit,
        "git_sha": commit,
        "source_runs_dir": normalize_runs_label(runs_dir),
        "source_runs_branch": src_branch,
        "source_runs_commit": src_commit,
        "timestamp": ts_iso,
        "command": sanitize_text(cmd),
        "tiers_version": DEFAULT_VERSION,
        "ledger_run_id": run_id,
        "fake_env": False,
        "smoke": False,
        "n_charts_analyzed": agg["n_charts_analyzed"],
        "n_images_read_by_model": agg["n_charts_analyzed"],
        "visual_threshold_accuracy": agg["visual_threshold_accuracy"],
        "accuse_day_within_1_accuracy": agg["accuse_day_within_1_accuracy"],
        "accuse_day_exact_accuracy": agg["accuse_day_exact_accuracy"],
        "hidden_bleed_gap_accuracy": agg["hidden_bleed_gap_accuracy"],
        "entropy_lag_accuracy": agg["entropy_lag_accuracy"],
        "outcome_pattern_accuracy": agg["outcome_pattern_accuracy"],
        "usage": agg["usage"],
    }

    (out_dir / "meta.json").write_text(sanitize_text(json.dumps(meta, indent=2) + "\n"), encoding="utf-8")
    (out_dir / "diagnoses.json").write_text(sanitize_text(json.dumps(records, indent=2) + "\n"), encoding="utf-8")
    (out_dir / "summary.md").write_text(format_summary_md(meta, records), encoding="utf-8")
    return {"meta": meta, "records": records}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-dir", type=Path, default=DEFAULT_RUNS_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--n-wrong", type=int, default=3)
    parser.add_argument("--n-high", type=int, default=4)
    parser.add_argument("--source-branch", type=str, default=None)
    parser.add_argument("--source-commit", type=str, default=None)
    args = parser.parse_args(argv)
    res = run_carbon_forensics(
        runs_dir=args.runs_dir,
        out_dir=args.out_dir,
        model_id=args.model,
        n_wrong=args.n_wrong,
        n_high=args.n_high,
        source_branch=args.source_branch,
        source_commit=args.source_commit,
    )
    print(json.dumps(res["meta"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
