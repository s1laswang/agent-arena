from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.agents.world_builder import assert_no_truth
from canary.env import Env
from canary.gemini import live_events
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    audit_env_outputs,
    extract_env_secrets,
    scan_text_for_secret,
)
from canary.gemini.world_audit import run_text_probe_audit
from canary.rules import TIERS_VERSION
from canary.text.lint import lint_messages

ROLE = "world_text"
SUBROLE = "dynamic_mid_episode_events"
DEFAULT_LLM = "gemini:gemini-4-carbon"
DEFAULT_TIER = "hard"
DEFAULT_SEEDS = (3, 4, 5, 6, 7)
DEFAULT_DAYS = (4, 9, 15)
DEFAULT_OUT = ROOT / "results" / "gemini_roles" / "world_text" / "dynamic-events-hard37-carbon"
PRIOR_HARD02_DIR = ROOT / "results" / "gemini_roles" / "world_text" / "dynamic-events-hard-carbon"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
MD_H1 = "\x23"
MD_H2 = "\x23\x23"


def scrub_dashes(val: Any) -> str:
    s = str(val or "")
    s = s.replace(f" {EM_DASH} ", " - ").replace(EM_DASH, " - ")
    s = s.replace(f" {EN_DASH} ", " - ").replace(EN_DASH, "-")
    s = s.replace(FIG_DASH, "-").replace(HORIZ_BAR, "-")
    return s


def clean_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return scrub_dashes(obj)
    if isinstance(obj, list):
        return [clean_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return [clean_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {scrub_dashes(k): clean_obj(v) for k, v in obj.items()}
    return obj


def git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def parse_int_list(spec: str | Sequence[int]) -> list[int]:
    if not isinstance(spec, str):
        return [int(x) for x in spec]
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            out.extend(range(int(lo_s), int(hi_s) + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError(f"empty integer list: {spec!r}")
    return out


def mean_ci95(vals: Sequence[float]) -> tuple[float, float]:
    if not vals:
        return 0.0, 0.0
    m = statistics.mean(vals)
    if len(vals) < 2:
        return round(m, 4), 0.0
    sd = statistics.stdev(vals)
    return round(m, 4), round(1.96 * sd / math.sqrt(len(vals)), 4)


def _generate_seed_worker(
    tier: str,
    seed: int,
    days: list[int],
    llm: str,
    run_id_prefix: str,
    require_live: bool,
) -> dict[str, Any]:
    env = Env(tier, seed)
    world = env._world
    seed_run_id = f"{run_id_prefix}:s{seed}"
    client = live_events.resolve_live_events_client(llm, run_id=seed_run_id)
    model_id = str(getattr(client, "model", "") or (llm.split(":", 1)[1] if ":" in llm else llm))

    bundles: list[dict[str, Any]] = []
    max_tries = 3 if require_live else 1
    for attempt in range(max_tries):
        cand = live_events.generate_mid_episode_events(
            env,
            days=days,
            llm=client,
            run_id=f"{seed_run_id}:a{attempt}" if attempt else seed_run_id,
            seed=seed,
        )
        cand = clean_obj(cand)
        aud = live_events.audit_event_bundles(cand, world=world)
        all_llm_ok = all(bool((b.get("meta") or {}).get("llm_ok")) for b in cand)
        if aud["truth_leak_violations"] == 0 and aud["lint_violations"] == 0 and (not require_live or all_llm_ok):
            bundles = cand
            break
        bundles = cand
        if attempt + 1 < max_tries:
            time.sleep(2.0 * (attempt + 1))

    audit = live_events.audit_event_bundles(bundles, world=world)
    _, world_secrets = extract_env_secrets(env)
    mole_id = str(world.mole)

    stego_hits = 0
    for b in bundles:
        stego_hits += len(scan_text_for_secret(b["messages"], mole_id))
        stego_hits += len(scan_text_for_secret(b, world_secrets))

    live_env = Env(tier, seed, text_provider=live_events.LiveEventsTextProvider(bundles))
    env_stego = audit_env_outputs(live_env)
    stego_hits += len(env_stego)

    usage = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "total_tokens": 0, "cost_usd": 0.0}
    for b in bundles:
        u = (b.get("meta") or {}).get("usage") or {}
        usage["calls"] += 1
        for k in ("in", "out", "thinking", "cached", "total_tokens"):
            usage[k] += int(u.get(k, 0) or 0)
        usage["cost_usd"] = round(usage["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)

    return {
        "seed": seed,
        "tier": tier,
        "company": bundles[0]["company"] if bundles else scrub_dashes(world.company),
        "model_id": model_id,
        "bundles": bundles,
        "audit": audit,
        "stego_violations": stego_hits,
        "llm_ok_count": sum(1 for b in bundles if (b.get("meta") or {}).get("llm_ok")),
        "fallback_count": sum(1 for b in bundles if (b.get("meta") or {}).get("used_fallback")),
        "usage": usage,
    }


def build_pooled_hard_parity(
    current_parity: dict[str, Any],
    prior_parity_path: Path | None = None,
) -> dict[str, Any]:
    rows_by_seed: dict[int, dict[str, Any]] = {}
    if prior_parity_path is not None and prior_parity_path.is_file():
        prior_doc = json.loads(prior_parity_path.read_text(encoding="utf-8"))
        if prior_doc.get("tier") == current_parity.get("tier"):
            for r in prior_doc.get("per_seed") or []:
                rows_by_seed[int(r["seed"])] = copy.deepcopy(r)
    for r in current_parity.get("per_seed") or []:
        rows_by_seed[int(r["seed"])] = copy.deepcopy(r)

    ordered = [rows_by_seed[s] for s in sorted(rows_by_seed)]
    n = len(ordered)
    base_scores = [float(r["baseline_solver"]["score"]) for r in ordered]
    live_scores = [float(r["live_events_solver"]["score"]) for r in ordered]
    obv_scores = [float(r["live_events_obvious_heuristic"]["score"]) for r in ordered]
    deltas = [l - b for l, b in zip(live_scores, base_scores)]
    gaps = [l - o for l, o in zip(live_scores, obv_scores)]

    base_m, base_ci = mean_ci95(base_scores)
    live_m, live_ci = mean_ci95(live_scores)
    obv_m, obv_ci = mean_ci95(obv_scores)
    delta_m, delta_ci = mean_ci95(deltas)
    gap_m, gap_ci = mean_ci95(gaps)

    base_acc = round(sum(1 for r in ordered if r["baseline_solver"]["correct"]) / max(1, n), 4)
    live_acc = round(sum(1 for r in ordered if r["live_events_solver"]["correct"]) / max(1, n), 4)
    obv_acc = round(sum(1 for r in ordered if r["live_events_obvious_heuristic"]["correct"]) / max(1, n), 4)
    dn_zero = all(float(r["live_events_do_nothing_score"]) == 0.0 for r in ordered)

    return {
        "tier": current_parity["tier"],
        "tiers_version": TIERS_VERSION,
        "seeds": [int(r["seed"]) for r in ordered],
        "n_seeds": n,
        "baseline_solver_mean": base_m,
        "baseline_solver_ci95": base_ci,
        "baseline_solver_accuracy": base_acc,
        "live_events_solver_mean": live_m,
        "live_events_solver_ci95": live_ci,
        "live_events_solver_accuracy": live_acc,
        "solver_score_delta_mean": delta_m,
        "solver_score_delta_ci95": delta_ci,
        "live_events_obvious_mean": obv_m,
        "live_events_obvious_ci95": obv_ci,
        "live_events_obvious_accuracy": obv_acc,
        "solver_vs_obvious_gap_mean": gap_m,
        "solver_vs_obvious_gap_ci95": gap_ci,
        "do_nothing_all_zero": dn_zero,
        "parity_ok": bool(dn_zero and abs(delta_m) <= 0.05 and live_acc >= base_acc - 1e-9 and gap_m > 0.20),
        "per_seed": ordered,
    }


def render_summary_markdown(
    meta: dict[str, Any],
    events_doc: dict[str, Any],
    parity: dict[str, Any],
    probe: dict[str, Any],
    pooled: dict[str, Any],
) -> str:
    usage = meta["usage"]
    lines = [
        f"{MD_H1} Role 1 (world_text): Dynamic Mid-Episode Corporate Incident Events (v1.4 Hard Seeds 3-7)",
        "",
        f"- Model: `{meta['model_id']}` (`{meta['llm_spec']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Tier / version: `{meta['tier']}` (`{meta['tiers_version']}`, 40 staff, 21 days)",
        f"- Seeds: `{meta['seeds']}` | Arrival days: `{meta['days']}`",
        f"- Events generated: `{meta['n_events_generated']}` (`llm_ok={meta['llm_ok_count']}`, `fallbacks={meta['fallback_count']}`, `{meta['n_messages_generated']}` workplace messages)",
        f"- Non-leak & stego audit: `truth_leak_violations={meta['truth_leak_violations']}`, `lint_violations={meta['lint_violations']}`, `stego_leak_violations={meta['stego_leak_violations']}` across `{meta['encodings_checked']}` encodings",
        f"- Text-only probe audit: `{probe['correct']}/{probe['n']}` (`accuracy={probe['accuracy']:.3f}`, `fair_bar={probe['fair_bar']:.3f}`, `p={probe['p_value_vs_bar']:.4f}`, `text_leak={probe['text_leak']}`)",
        f"- Token usage: `{usage['calls']}` calls, `{usage['in']}` input, `{usage['out']}` output, `{usage['thinking']}` thinking, `{usage['total_tokens']}` total tokens (`${usage['cost_usd']:.6f}` est., `{usage['latency_s']:.2f}s`)",
        "",
        f"{MD_H2} Generated Mid-Episode Event Bundles (Seeds 3-7)",
        "",
        "| Seed | Day | Company | Category | Headline | Reactions | LLM OK |",
        "|---:|---:|---|---|---|---:|---|",
    ]
    for s_entry in events_doc["seeds"]:
        s_val = s_entry["seed"]
        for ev in s_entry["events"]:
            llm_ok = "yes" if ev["meta"]["llm_ok"] else "fallback"
            hl = ev["headline"].replace("|", "/")
            lines.append(
                f"| {s_val} | {ev['day']} | {ev['company']} | `{ev['category']}` | {hl} | {len(ev['reactions'])} | {llm_ok} |"
            )

    lines.extend([
        "",
        f"{MD_H2} SolverPolicy vs ObviousHeuristic Catchability Parity (Seeds 3-7, n={len(parity['per_seed'])})",
        "",
        "| Seed | Baseline Solver | Live-Events Solver | Baseline ObviousHeuristic | Live-Events ObviousHeuristic | DoNothing | Event Msgs |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in parity["per_seed"]:
        bs = row["baseline_solver"]
        ls = row["live_events_solver"]
        bo = row["baseline_obvious_heuristic"]
        lo = row["live_events_obvious_heuristic"]
        lines.append(
            f"| {row['seed']} | {bs['score']:+.4f} (d{bs['final_day']}, {'ok' if bs['correct'] else 'wrong'}) "
            f"| {ls['score']:+.4f} (d{ls['final_day']}, {'ok' if ls['correct'] else 'wrong'}) "
            f"| {bo['score']:+.4f} (d{bo['final_day']}, {'ok' if bo['correct'] else 'wrong'}) "
            f"| {lo['score']:+.4f} (d{lo['final_day']}, {'ok' if lo['correct'] else 'wrong'}) "
            f"| {row['live_events_do_nothing_score']:+.4f} | {row['event_messages_delivered']} |"
        )

    lines.extend([
        "",
        f"- Seeds 3-7 `SolverPolicy`: `{parity['live_events_solver_mean_score']:+.4f}` vs baseline `{parity['baseline_solver_mean_score']:+.4f}` (`delta={parity['solver_score_delta']:+.4f}`, accuracy `{parity['live_events_solver_accuracy']:.0%}`)",
        f"- Pooled v1.4 Hard Seeds `{pooled['seeds']}` (`n={pooled['n_seeds']}`): live-events `SolverPolicy` `{pooled['live_events_solver_mean']:+.4f} +/- {pooled['live_events_solver_ci95']:.4f}` vs baseline `{pooled['baseline_solver_mean']:+.4f} +/- {pooled['baseline_solver_ci95']:.4f}` (paired delta `{pooled['solver_score_delta_mean']:+.4f} +/- {pooled['solver_score_delta_ci95']:.4f}`, accuracy `{pooled['live_events_solver_accuracy']:.0%}`), `ObviousHeuristic` `{pooled['live_events_obvious_mean']:+.4f}`, gap `{pooled['solver_vs_obvious_gap_mean']:+.4f} +/- {pooled['solver_vs_obvious_gap_ci95']:.4f}` (`parity_ok={pooled['parity_ok']}`)",
        "",
        f"{MD_H2} Reproduction",
        "",
        "```bash",
        meta["command"],
        "```",
        "",
    ])
    return scrub_dashes("\n".join(lines))


def run_hard37_experiment(
    *,
    llm: str = DEFAULT_LLM,
    tier: str = DEFAULT_TIER,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    days: Sequence[int] = DEFAULT_DAYS,
    out_dir: Path | str = DEFAULT_OUT,
    jobs: int = 5,
    require_live: bool = False,
    prior_parity_path: Path | None = PRIOR_HARD02_DIR / "solver_parity.json",
    command_str: str | None = None,
) -> dict[str, Any]:
    seed_list = [int(s) for s in seeds]
    day_list = [int(d) for d in days]
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"live-events-{tier}-{stamp}"
    t0 = time.time()

    max_workers = max(1, min(int(jobs), len(seed_list), 8))
    by_seed: dict[int, dict[str, Any]] = {}
    if max_workers == 1 or str(llm).startswith("stub"):
        for s in seed_list:
            by_seed[s] = _generate_seed_worker(tier, s, day_list, llm, run_id, require_live)
    else:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = {
                pool.submit(_generate_seed_worker, tier, s, day_list, llm, run_id, require_live): s
                for s in seed_list
            }
            for fut in cf.as_completed(futs):
                by_seed[futs[fut]] = fut.result()

    ordered_results = [by_seed[s] for s in seed_list]
    events_by_seed = {r["seed"]: r["bundles"] for r in ordered_results}
    providers = {
        s: live_events.LiveEventsTextProvider(events_by_seed[s], name=f"gemini-live-events:{s}")
        for s in seed_list
    }

    parity = clean_obj(live_events.verify_solver_parity(tier=tier, seeds=seed_list, events_by_seed=events_by_seed))
    raw_probe = run_text_probe_audit(tier, seed_list, providers, backend="stub")
    safe_probe = clean_obj({
        "backend": raw_probe["backend"],
        "n": raw_probe["n"],
        "correct": raw_probe["correct"],
        "accuracy": raw_probe["accuracy"],
        "ci95": raw_probe["ci95"],
        "chance": raw_probe["chance"],
        "interviews_per_employee": raw_probe["interviews_per_employee"],
        "fair_bar": raw_probe["fair_bar"],
        "p_value_vs_bar": raw_probe["p_value_vs_bar"],
        "p_value_vs_chance": raw_probe["p_value_vs_chance"],
        "text_leak": raw_probe["text_leak"],
        "rows": [{"seed": int(r["seed"]), "correct": bool(r["correct"])} for r in raw_probe["rows"]],
    })
    pooled = clean_obj(build_pooled_hard_parity(parity, prior_parity_path=prior_parity_path))

    agg_usage = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "total_tokens": 0, "cost_usd": 0.0}
    for r in ordered_results:
        u = r["usage"]
        for k in ("calls", "in", "out", "thinking", "cached", "total_tokens"):
            agg_usage[k] += int(u.get(k, 0) or 0)
        agg_usage["cost_usd"] = round(agg_usage["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)
    agg_usage["latency_s"] = round(time.time() - t0, 3)

    truth_v = sum(int(r["audit"]["truth_leak_violations"]) for r in ordered_results)
    raw_v = sum(int(r["audit"]["raw_llm_violations"]) for r in ordered_results)
    lint_v = sum(int(r["audit"]["lint_violations"]) for r in ordered_results)
    stego_v = sum(int(r["stego_violations"]) for r in ordered_results)
    llm_ok_n = sum(int(r["llm_ok_count"]) for r in ordered_results)
    fb_n = sum(int(r["fallback_count"]) for r in ordered_results)
    n_events = sum(len(r["bundles"]) for r in ordered_results)
    n_msgs = sum(len(b["messages"]) for r in ordered_results for b in r["bundles"])

    model_id = ordered_results[0]["model_id"] if ordered_results else "stub"
    is_stub = model_id == "stub" or str(llm).startswith("stub")

    if require_live:
        if is_stub:
            raise AssertionError("require_live set on stub client")
        if llm_ok_n != n_events or fb_n != 0:
            raise AssertionError(f"expected {n_events}/{n_events} llm_ok and 0 fallbacks, got {llm_ok_n} and {fb_n}")
        if agg_usage["in"] <= 0 or agg_usage["out"] <= 0 or agg_usage["cost_usd"] <= 0.0:
            raise AssertionError(f"expected positive token usage and cost, got {agg_usage}")

    cmd = command_str or (
        f"PYTHONPATH=. python scripts/run_live_events_hard37.py --llm {llm} "
        f"--tier {tier} --seeds {','.join(map(str, seed_list))} --days {','.join(map(str, day_list))} --out {out_path}"
    )

    meta = clean_obj({
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "llm_spec": llm,
        "commit": git_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": scrub_dashes(cmd),
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seed_list,
        "days": day_list,
        "ledger_run_id": run_id,
        "stub": is_stub,
        "fake_env": False,
        "smoke": False,
        "usage": agg_usage,
        "n_events_generated": n_events,
        "n_messages_generated": n_msgs,
        "llm_ok_count": llm_ok_n,
        "fallback_count": fb_n,
        "truth_leak_violations": truth_v,
        "raw_llm_violations": raw_v,
        "lint_violations": lint_v,
        "stego_leak_violations": stego_v,
        "encodings_checked": len(SUPPORTED_ENCODINGS),
        "text_probe_leak": bool(safe_probe["text_leak"]),
        "solver_parity_ok": bool(parity["parity_ok"]),
        "pooled_hard_n": pooled["n_seeds"],
        "pooled_solver_mean": pooled["live_events_solver_mean"],
        "pooled_baseline_solver_mean": pooled["baseline_solver_mean"],
        "key_metric": (
            f"{n_events} events ({len(seed_list)} hard seeds, {n_msgs} msgs), "
            f"0 leaks, solver {parity['live_events_solver_mean_score']:+.3f} vs base {parity['baseline_solver_mean_score']:+.3f} "
            f"(pooled n={pooled['n_seeds']}: {pooled['live_events_solver_mean']:+.3f} +/- {pooled['live_events_solver_ci95']:.3f})"
        ),
    })

    events_doc = clean_obj({
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "days": day_list,
        "n_events_generated": n_events,
        "text_probe": safe_probe,
        "seeds": [
            {
                "seed": r["seed"],
                "tier": r["tier"],
                "company": r["company"],
                "events": r["bundles"],
            }
            for r in ordered_results
        ],
    })

    assert_no_truth(events_doc, {})
    for s_entry in events_doc["seeds"]:
        for b in s_entry["events"]:
            assert not lint_messages(b["messages"])

    summary_md = render_summary_markdown(meta, events_doc, parity, safe_probe, pooled)

    (out_path / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_path / "events.json").write_text(json.dumps(events_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_path / "solver_parity.json").write_text(json.dumps(parity, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_path / "pooled_hard07.json").write_text(json.dumps(pooled, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_path / "summary.md").write_text(summary_md, encoding="utf-8")

    return {
        "meta": meta,
        "events": events_doc,
        "solver_parity": parity,
        "pooled_hard07": pooled,
    }


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="python scripts/run_live_events_hard37.py")
    ap.add_argument("--llm", default=DEFAULT_LLM)
    ap.add_argument("--tier", default=DEFAULT_TIER)
    ap.add_argument("--seeds", default="3,4,5,6,7")
    ap.add_argument("--days", default="4,9,15")
    ap.add_argument("--jobs", type=int, default=5)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--require-live", action="store_true")
    args = ap.parse_args(raw)

    cmd = (
        "PYTHONPATH=. python scripts/run_live_events_hard37.py " + " ".join(raw)
        if raw
        else "PYTHONPATH=. python scripts/run_live_events_hard37.py"
    )
    res = run_hard37_experiment(
        llm=args.llm,
        tier=args.tier,
        seeds=parse_int_list(args.seeds),
        days=parse_int_list(args.days),
        out_dir=args.out,
        jobs=args.jobs,
        require_live=args.require_live,
        command_str=cmd,
    )
    meta = res["meta"]
    print(json.dumps({
        "out": str(args.out),
        "model_id": meta["model_id"],
        "n_events_generated": meta["n_events_generated"],
        "llm_ok_count": meta["llm_ok_count"],
        "truth_leak_violations": meta["truth_leak_violations"],
        "lint_violations": meta["lint_violations"],
        "stego_leak_violations": meta["stego_leak_violations"],
        "text_probe_leak": meta["text_probe_leak"],
        "solver_parity_ok": meta["solver_parity_ok"],
        "usage": meta["usage"],
    }, sort_keys=True))
    if (
        meta["truth_leak_violations"] > 0
        or meta["lint_violations"] > 0
        or meta["stego_leak_violations"] > 0
        or meta["text_probe_leak"]
        or not meta["solver_parity_ok"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
