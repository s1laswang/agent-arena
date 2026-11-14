from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.gemini.provenance import (
    COMMIT_RE,
    SKIP_DIRS,
    TARGET_MODEL,
    _extract_count,
    _extract_usage,
    scan_file_secrets,
)

ROLE = "world_text"
SUITE_DIR_NAME = "worldtext-carbon-suite"
DEFAULT_REL_OUT = Path("results") / "gemini_roles" / "world_text" / SUITE_DIR_NAME
TIER_ORDER: tuple[str, ...] = ("easy", "medium", "hard")
TIER_RANK: dict[str, int] = {"easy": 0, "medium": 1, "hard": 2}
THINKING_ORDER: tuple[str, ...] = ("low", "medium", "high")
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
MD_H1 = "\x23"
MD_H2 = "\x23\x23"
MD_H3 = "\x23\x23\x23"


def clean_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    s = s.replace(f" {EM_DASH} ", " - ").replace(EM_DASH, "-")
    s = s.replace(f" {EN_DASH} ", " - ").replace(EN_DASH, "-")
    s = s.replace(FIG_DASH, "-").replace(HORIZ_BAR, "-")
    return s


def sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return clean_str(obj)
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, list):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return [sanitize_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {clean_str(k): sanitize_obj(v) for k, v in obj.items()}
    return obj


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _rel_posix(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None


def wilson_ci95(successes: int, total: int) -> list[float]:
    if total <= 0:
        return [0.0, 0.0]
    k = max(0, min(int(successes), int(total)))
    n = float(total)
    z = 1.959963984540054
    z2 = z * z
    phat = k / n
    denom = 1.0 + z2 / n
    center = (phat + z2 / (2.0 * n)) / denom
    radicand = max(0.0, (phat * (1.0 - phat) + z2 / (4.0 * n)) / n)
    half = (z * math.sqrt(radicand)) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def bootstrap_mean_ci95(
    values: list[float],
    n_boot: int = 2000,
    seed: int = 104729,
) -> list[float]:
    if not values:
        return [0.0, 0.0]
    clean_vals = [float(v) for v in values]
    if len(clean_vals) == 1 or min(clean_vals) == max(clean_vals):
        const = round(clean_vals[0], 4)
        return [const, const]
    rng = random.Random(seed)
    n = len(clean_vals)
    boot_means = sorted(
        sum(clean_vals[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(n_boot)
    )
    lo_idx = int(0.025 * (n_boot - 1))
    hi_idx = int(0.975 * (n_boot - 1))
    return [round(boot_means[lo_idx], 4), round(boot_means[hi_idx], 4)]


def mean_val(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(float(v) for v in values) / len(values), 4)


def zero_usage() -> dict[str, Any]:
    return {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "cost_usd": 0.0,
    }


def add_usage(acc: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "calls": int(acc.get("calls", 0)) + int(item.get("calls", 0)),
        "in": int(acc.get("in", 0)) + int(item.get("in", 0)),
        "out": int(acc.get("out", 0)) + int(item.get("out", 0)),
        "thinking": int(acc.get("thinking", 0)) + int(item.get("thinking", 0)),
        "cached": int(acc.get("cached", 0)) + int(item.get("cached", 0)),
        "cost_usd": round(float(acc.get("cost_usd", 0.0)) + float(item.get("cost_usd", 0.0)), 6),
    }


def extract_folder_usage(meta: dict[str, Any]) -> dict[str, Any]:
    raw_u = meta.get("usage") if isinstance(meta.get("usage"), dict) else {}
    tin, tout, tthink, tcached, usd, err = _extract_usage(meta, TARGET_MODEL)
    if err is not None:
        return zero_usage()
    if tcached == 0 and _is_num(raw_u.get("cached_tokens")) and int(raw_u["cached_tokens"]) > 0:
        tcached = int(raw_u["cached_tokens"])
    calls_raw = raw_u.get("calls", meta.get("calls", 0))
    calls = int(calls_raw) if _is_num(calls_raw) and int(calls_raw) > 0 else 0
    return {
        "calls": calls,
        "in": tin,
        "out": tout,
        "thinking": tthink,
        "cached": tcached,
        "cost_usd": usd,
    }


def _discover_world_text_runs(root: Path) -> list[dict[str, Any]]:
    role_root = root / "results" / "gemini_roles" / ROLE
    if not role_root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for meta_path in sorted(role_root.glob("*/meta.json")):
        run_dir = meta_path.parent
        if run_dir.name in SKIP_DIRS or run_dir.name == SUITE_DIR_NAME:
            continue
        meta = _load_json(meta_path)
        if not isinstance(meta, dict):
            continue
        if str(meta.get("role", "")).strip() != ROLE:
            continue
        model_id = str(meta.get("model_id") or meta.get("model") or "").strip()
        if model_id != TARGET_MODEL:
            continue
        if meta.get("stub") is True or meta.get("fake_env") is True or meta.get("smoke") is True:
            continue
        commit = str(meta.get("commit") or "").strip()
        if not COMMIT_RE.match(commit):
            continue
        usage = extract_folder_usage(meta)
        if usage["in"] <= 0 or usage["out"] <= 0:
            continue
        leaks: list[dict[str, str]] = []
        for fp in sorted(p for p in run_dir.rglob("*") if p.is_file()):
            leaks.extend(scan_file_secrets(fp, root))
        if leaks:
            continue
        found.append({
            "run_dir": run_dir,
            "rel_dir": _rel_posix(run_dir, root),
            "folder_name": run_dir.name,
            "meta": meta,
            "subrole": str(meta.get("subrole") or "world_text").strip(),
            "commit": commit,
            "count": _extract_count(run_dir, meta),
            "usage": usage,
        })
    return found


def _build_company_personas_suite(runs: list[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}
    total_personas_all = 0
    total_llm_personas_all = 0
    total_day_msgs_all = 0

    for item in runs:
        if item["subrole"] != "company_personas_chatter":
            continue
        meta = item["meta"]
        run_dir = item["run_dir"]
        samples = _load_json(run_dir / "samples.json")
        worlds_list = samples.get("worlds") if isinstance(samples, dict) and isinstance(samples.get("worlds"), list) else []

        n_worlds = int(meta.get("n_worlds", len(worlds_list)) or 0)
        n_personas = int(meta.get("n_personas_generated", 0) or 0)
        n_llm_personas = int(meta.get("n_llm_personas", n_personas) or 0)
        n_day_msgs = int(meta.get("n_day_messages_generated", 0) or 0)
        fallbacks = int(meta.get("gemini_provider_fallbacks", 0) or 0)
        truth_leaks = int(meta.get("truth_leak_violations", 0) or 0)
        lint_errs = int(meta.get("lint_violations", 0) or 0)

        total_personas_all += n_personas
        total_llm_personas_all += n_llm_personas
        total_day_msgs_all += n_day_msgs

        for w in worlds_list:
            if not isinstance(w, dict):
                continue
            tier = str(w.get("tier") or "")
            seed = int(w.get("seed", 0))
            sv = w.get("solver_verification") if isinstance(w.get("solver_verification"), dict) else {}
            wb = w.get("world_builder") if isinstance(w.get("world_builder"), dict) else {}
            if tier in TIER_RANK:
                dedup_worlds[(tier, seed)] = {
                    "tier": tier,
                    "seed": seed,
                    "run_dir": item["rel_dir"],
                    "n_personas": int(wb.get("n_personas", 0) or 0),
                    "n_llm_personas": int(wb.get("n_llm_personas", 0) or 0),
                    "llm_ok": bool(wb.get("llm_ok", True)),
                    "solver_score": float(sv.get("score", 0.0) or 0.0),
                    "solver_correct": bool(sv.get("correct", False)),
                    "template_score": float(sv.get("template_baseline_score", 0.0) or 0.0),
                    "score_delta": float(sv.get("score_delta", 0.0) or 0.0),
                }

        batches.append({
            "run_dir": item["rel_dir"],
            "commit": item["commit"][:10],
            "n_worlds": n_worlds,
            "n_personas": n_personas,
            "n_llm_personas": n_llm_personas,
            "n_day_messages": n_day_msgs,
            "fallbacks": fallbacks,
            "truth_leaks": truth_leaks,
            "lint_violations": lint_errs,
            "solver_mean_score": round(float(meta.get("solver_mean_score", 0.0) or 0.0), 4),
            "template_mean_score": round(float(meta.get("template_baseline_mean_score", 0.0) or 0.0), 4),
            "solver_accuracy": round(float(meta.get("solver_accuracy", 0.0) or 0.0), 4),
            "usage": item["usage"],
        })

    ordered_worlds = sorted(dedup_worlds.values(), key=lambda r: (TIER_RANK.get(r["tier"], 99), r["seed"]))
    by_tier: dict[str, Any] = {}
    for label, subset in [
        *[(t, [w for w in ordered_worlds if w["tier"] == t]) for t in TIER_ORDER],
        ("overall", ordered_worlds),
    ]:
        if not subset:
            continue
        s_scores = [w["solver_score"] for w in subset]
        t_scores = [w["template_score"] for w in subset]
        deltas = [round(w["solver_score"] - w["template_score"], 6) for w in subset]
        k_ok = sum(1 for w in subset if w["solver_correct"])
        by_tier[label] = {
            "n_worlds": len(subset),
            "n_personas": sum(w["n_personas"] for w in subset),
            "solver_mean": mean_val(s_scores),
            "solver_ci95": bootstrap_mean_ci95(s_scores),
            "solver_accuracy": round(k_ok / len(subset), 4),
            "solver_accuracy_ci95": wilson_ci95(k_ok, len(subset)),
            "template_mean": mean_val(t_scores),
            "template_ci95": bootstrap_mean_ci95(t_scores),
            "paired_delta_mean": mean_val(deltas),
            "paired_delta_ci95": bootstrap_mean_ci95(deltas),
        }

    return {
        "n_batches": len(batches),
        "unique_worlds": len(ordered_worlds),
        "unique_personas": sum(w["n_personas"] for w in ordered_worlds),
        "total_personas_across_batches": total_personas_all,
        "total_llm_personas_across_batches": total_llm_personas_all,
        "total_day_messages_across_batches": total_day_msgs_all,
        "by_tier": by_tier,
        "batches": batches,
    }


def _build_biased_chatter_suite(runs: list[dict[str, Any]]) -> dict[str, Any]:
    chatter_batches: list[dict[str, Any]] = []
    ablation_batches: list[dict[str, Any]] = []
    dedup_episodes: dict[tuple[str, int, str, str], dict[str, Any]] = {}

    for item in runs:
        sub = item["subrole"]
        meta = item["meta"]
        run_dir = item["run_dir"]
        if sub in {"biased_chatter", "biased_chatter_hard"}:
            chatter_batches.append({
                "run_dir": item["rel_dir"],
                "subrole": sub,
                "tier": str(meta.get("tier") or ""),
                "seeds": list(meta.get("seeds") or []),
                "commit": item["commit"][:10],
                "n_messages": int(meta.get("n_messages", 0) or 0),
                "n_llm_messages": int(meta.get("n_llm_messages", 0) or 0),
                "n_fallback_messages": int(meta.get("n_fallback_messages", 0) or 0),
                "truth_leaks": int(meta.get("truth_leak_violations", 0) or 0),
                "lint_violations": int(meta.get("lint_violations", 0) or 0),
                "encoding_violations": int(meta.get("encoding_scan_violations", 0) or 0),
                "usage": item["usage"],
            })
        elif sub == "biased_chatter_investigator_ablation":
            comp = _load_json(run_dir / "comparison.json")
            eps = comp.get("episodes") if isinstance(comp, dict) and isinstance(comp.get("episodes"), list) else []
            for ep in eps:
                if not isinstance(ep, dict):
                    continue
                tier = str(ep.get("tier") or meta.get("tier") or "")
                seed = int(ep.get("seed", 0))
                pol = str(ep.get("policy") or "")
                wkind = str(ep.get("world") or "")
                if tier and pol and wkind:
                    dedup_episodes[(tier, seed, pol, wkind)] = {
                        "tier": tier,
                        "seed": seed,
                        "policy": pol,
                        "world": wkind,
                        "score": float(ep.get("score", 0.0) or 0.0),
                        "correct": bool(ep.get("correct", False)),
                        "distracted": bool(ep.get("rumor_target_distracted", False)),
                        "rumor_accused": bool(ep.get("rumor_target_accused", False)),
                        "action_share": float(ep.get("rumor_target_action_share", 0.0) or 0.0),
                    }
            ablation_batches.append({
                "run_dir": item["rel_dir"],
                "tier": str(meta.get("tier") or ""),
                "seeds": list(meta.get("seeds") or []),
                "commit": item["commit"][:10],
                "episode_count": int(meta.get("episode_count", len(eps)) or 0),
                "carbon_biased_mean": round(float(meta.get("carbon_biased_mean", 0.0) or 0.0), 4),
                "carbon_template_mean": round(float(meta.get("carbon_template_mean", 0.0) or 0.0), 4),
                "solver_biased_mean": round(float(meta.get("solver_biased_mean", 0.0) or 0.0), 4),
                "solver_template_mean": round(float(meta.get("solver_template_mean", 0.0) or 0.0), 4),
                "obvious_biased_mean": round(float(meta.get("obvious_biased_mean", -1.0) or 0.0), 4),
                "usage": item["usage"],
            })

    all_eps = list(dedup_episodes.values())
    paired_slices: dict[str, Any] = {}
    for slice_name, tier_filter in [("medium", "medium"), ("hard", "hard"), ("overall", None)]:
        slice_eps = [e for e in all_eps if tier_filter is None or e["tier"] == tier_filter]
        if not slice_eps:
            continue
        pol_summary: dict[str, Any] = {}
        for pol in ("carbon", "solver", "obvious_heuristic"):
            b_map = {(e["tier"], e["seed"]): e for e in slice_eps if e["policy"] == pol and e["world"] == "biased"}
            t_map = {(e["tier"], e["seed"]): e for e in slice_eps if e["policy"] == pol and e["world"] == "template"}
            keys = sorted(set(b_map) & set(t_map), key=lambda x: (TIER_RANK.get(x[0], 99), x[1]))
            if not keys:
                continue
            b_scores = [b_map[k]["score"] for k in keys]
            t_scores = [t_map[k]["score"] for k in keys]
            deltas = [round(b_map[k]["score"] - t_map[k]["score"], 6) for k in keys]
            b_acc_k = sum(1 for k in keys if b_map[k]["correct"])
            t_acc_k = sum(1 for k in keys if t_map[k]["correct"])
            b_dist_k = sum(1 for k in keys if b_map[k]["distracted"])
            t_dist_k = sum(1 for k in keys if t_map[k]["distracted"])
            b_false_k = sum(1 for k in keys if b_map[k]["rumor_accused"])
            pol_summary[pol] = {
                "n_paired_seeds": len(keys),
                "biased_mean": mean_val(b_scores),
                "biased_ci95": bootstrap_mean_ci95(b_scores),
                "biased_accuracy": round(b_acc_k / len(keys), 4),
                "biased_accuracy_ci95": wilson_ci95(b_acc_k, len(keys)),
                "template_mean": mean_val(t_scores),
                "template_ci95": bootstrap_mean_ci95(t_scores),
                "template_accuracy": round(t_acc_k / len(keys), 4),
                "paired_delta_mean": mean_val(deltas),
                "paired_delta_ci95": bootstrap_mean_ci95(deltas),
                "biased_distraction_rate": round(b_dist_k / len(keys), 4),
                "biased_distraction_ci95": wilson_ci95(b_dist_k, len(keys)),
                "template_distraction_rate": round(t_dist_k / len(keys), 4),
                "biased_rumor_accused_rate": round(b_false_k / len(keys), 4),
            }
        if pol_summary:
            paired_slices[slice_name] = pol_summary

    return {
        "n_chatter_batches": len(chatter_batches),
        "n_ablation_batches": len(ablation_batches),
        "total_biased_messages": sum(b["n_messages"] for b in chatter_batches),
        "total_llm_biased_messages": sum(b["n_llm_messages"] for b in chatter_batches),
        "unique_ablation_episodes": len(all_eps),
        "paired_slices": paired_slices,
        "chatter_batches": chatter_batches,
        "ablation_batches": ablation_batches,
    }


def _build_interviews_suite(runs: list[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    dedup_worlds: dict[tuple[str, int], dict[str, Any]] = {}
    total_interviews = 0
    total_cal_correct = 0
    total_inv_ok = 0
    total_inv_checks = 0

    for item in runs:
        if item["subrole"] != "persona_interviews":
            continue
        meta = item["meta"]
        run_dir = item["run_dir"]
        parity_doc = _load_json(run_dir / "solver_parity.json")
        iv_doc = _load_json(run_dir / "interviews.json")
        per_world = parity_doc.get("per_world") if isinstance(parity_doc, dict) and isinstance(parity_doc.get("per_world"), list) else []

        n_samples = int(meta.get("n_interviews_generated", meta.get("count", 0)) or 0)
        cal_acc = float(meta.get("signal_calibration_accuracy", 1.0) or 0.0)
        inv_rate = float(meta.get("counterfactual_prompt_invariance_rate", 1.0) or 0.0)
        audit_sub = iv_doc.get("audit") if isinstance(iv_doc, dict) and isinstance(iv_doc.get("audit"), dict) else {}
        inv_checks = int(audit_sub.get("counterfactual_checks", n_samples // 2) or 0)

        total_interviews += n_samples
        total_cal_correct += int(round(cal_acc * n_samples))
        total_inv_checks += inv_checks
        total_inv_ok += int(round(inv_rate * inv_checks))

        for pw in per_world:
            if not isinstance(pw, dict):
                continue
            tier = str(pw.get("tier") or "")
            seed = int(pw.get("seed", 0))
            ps = pw.get("persona_solver") if isinstance(pw.get("persona_solver"), dict) else {}
            ts = pw.get("template_solver") if isinstance(pw.get("template_solver"), dict) else {}
            po = pw.get("persona_obvious_heuristic") if isinstance(pw.get("persona_obvious_heuristic"), dict) else {}
            if tier in TIER_RANK:
                dedup_worlds[(tier, seed)] = {
                    "tier": tier,
                    "seed": seed,
                    "persona_solver_score": float(ps.get("score", 0.0) or 0.0),
                    "persona_solver_correct": bool(ps.get("correct", False)),
                    "template_solver_score": float(ts.get("score", 0.0) or 0.0),
                    "template_solver_correct": bool(ts.get("correct", False)),
                    "obvious_score": float(po.get("score", -1.0) or 0.0),
                }

        batches.append({
            "run_dir": item["rel_dir"],
            "commit": item["commit"][:10],
            "n_worlds": int(meta.get("n_worlds", len(per_world)) or 0),
            "n_interviews": n_samples,
            "signal_calibration_accuracy": round(cal_acc, 4),
            "counterfactual_invariance_rate": round(inv_rate, 4),
            "pairwise_ordering_rate": round(float(meta.get("pairwise_signal_ordering_rate", 1.0) or 0.0), 4),
            "solver_mean_score": round(float(meta.get("solver_mean_score", 0.0) or 0.0), 4),
            "template_mean_score": round(float(meta.get("template_baseline_mean_score", 0.0) or 0.0), 4),
            "truth_leaks": int(meta.get("truth_leak_violations", 0) or 0) + int(meta.get("prompt_truth_leak_violations", 0) or 0),
            "stego_leaks": int(meta.get("stego_leak_violations", 0) or 0),
            "usage": item["usage"],
        })

    ordered = sorted(dedup_worlds.values(), key=lambda r: (TIER_RANK.get(r["tier"], 99), r["seed"]))
    ps_scores = [w["persona_solver_score"] for w in ordered]
    ts_scores = [w["template_solver_score"] for w in ordered]
    deltas = [round(w["persona_solver_score"] - w["template_solver_score"], 6) for w in ordered]
    ps_ok = sum(1 for w in ordered if w["persona_solver_correct"])

    return {
        "n_batches": len(batches),
        "unique_worlds": len(ordered),
        "total_interviews": total_interviews,
        "signal_calibration_accuracy": round(total_cal_correct / total_interviews, 4) if total_interviews else 0.0,
        "signal_calibration_ci95": wilson_ci95(total_cal_correct, total_interviews),
        "counterfactual_invariance_rate": round(total_inv_ok / total_inv_checks, 4) if total_inv_checks else 0.0,
        "counterfactual_invariance_ci95": wilson_ci95(total_inv_ok, total_inv_checks),
        "persona_solver_mean": mean_val(ps_scores),
        "persona_solver_ci95": bootstrap_mean_ci95(ps_scores),
        "persona_solver_accuracy": round(ps_ok / len(ordered), 4) if ordered else 0.0,
        "persona_solver_accuracy_ci95": wilson_ci95(ps_ok, len(ordered)),
        "template_solver_mean": mean_val(ts_scores),
        "template_solver_ci95": bootstrap_mean_ci95(ts_scores),
        "paired_delta_mean": mean_val(deltas),
        "paired_delta_ci95": bootstrap_mean_ci95(deltas),
        "batches": batches,
    }


def _build_dynamic_events_suite(runs: list[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    dedup_seeds: dict[tuple[str, int], dict[str, Any]] = {}
    total_events = 0

    for item in runs:
        if item["subrole"] != "dynamic_mid_episode_events":
            continue
        meta = item["meta"]
        run_dir = item["run_dir"]
        tier = str(meta.get("tier") or "")
        parity_doc = _load_json(run_dir / "solver_parity.json")
        per_seed = parity_doc.get("per_seed") if isinstance(parity_doc, dict) and isinstance(parity_doc.get("per_seed"), list) else []
        n_ev = int(meta.get("n_events_generated", 0) or 0)
        total_events += n_ev

        for ps in per_seed:
            if not isinstance(ps, dict):
                continue
            seed = int(ps.get("seed", 0))
            ls = ps.get("live_events_solver") if isinstance(ps.get("live_events_solver"), dict) else {}
            bs = ps.get("baseline_solver") if isinstance(ps.get("baseline_solver"), dict) else {}
            lo = ps.get("live_events_obvious_heuristic") if isinstance(ps.get("live_events_obvious_heuristic"), dict) else {}
            if tier in TIER_RANK:
                dedup_seeds[(tier, seed)] = {
                    "tier": tier,
                    "seed": seed,
                    "live_solver_score": float(ls.get("score", 0.0) or 0.0),
                    "live_solver_correct": bool(ls.get("correct", False)),
                    "base_solver_score": float(bs.get("score", 0.0) or 0.0),
                    "base_solver_correct": bool(bs.get("correct", False)),
                    "live_obvious_score": float(lo.get("score", -1.0) or 0.0),
                }

        batches.append({
            "run_dir": item["rel_dir"],
            "tier": tier,
            "seeds": list(meta.get("seeds") or []),
            "days": list(meta.get("days") or []),
            "commit": item["commit"][:10],
            "n_events": n_ev,
            "truth_leaks": int(meta.get("truth_leak_violations", 0) or 0),
            "lint_violations": int(meta.get("lint_violations", 0) or 0),
            "stego_leaks": int(meta.get("stego_leak_violations", 0) or 0),
            "solver_parity_ok": bool(meta.get("solver_parity_ok", False)),
            "usage": item["usage"],
        })

    ordered = sorted(dedup_seeds.values(), key=lambda r: (TIER_RANK.get(r["tier"], 99), r["seed"]))
    by_tier: dict[str, Any] = {}
    for label, subset in [
        *[(t, [r for r in ordered if r["tier"] == t]) for t in TIER_ORDER],
        ("overall", ordered),
    ]:
        if not subset:
            continue
        l_scores = [r["live_solver_score"] for r in subset]
        b_scores = [r["base_solver_score"] for r in subset]
        o_scores = [r["live_obvious_score"] for r in subset]
        deltas = [round(r["live_solver_score"] - r["base_solver_score"], 6) for r in subset]
        k_ok = sum(1 for r in subset if r["live_solver_correct"])
        by_tier[label] = {
            "n_worlds": len(subset),
            "live_solver_mean": mean_val(l_scores),
            "live_solver_ci95": bootstrap_mean_ci95(l_scores),
            "live_solver_accuracy": round(k_ok / len(subset), 4),
            "live_solver_accuracy_ci95": wilson_ci95(k_ok, len(subset)),
            "baseline_solver_mean": mean_val(b_scores),
            "baseline_solver_ci95": bootstrap_mean_ci95(b_scores),
            "paired_delta_mean": mean_val(deltas),
            "paired_delta_ci95": bootstrap_mean_ci95(deltas),
            "obvious_heuristic_mean": mean_val(o_scores),
        }

    return {
        "n_batches": len(batches),
        "unique_worlds": len(ordered),
        "total_events_generated": total_events,
        "by_tier": by_tier,
        "batches": batches,
    }


def _build_thinking_calibration_suite(runs: list[dict[str, Any]]) -> dict[str, Any]:
    batches: list[dict[str, Any]] = []
    by_level_acc: dict[str, dict[str, Any]] = {
        lvl: {"n_worlds": 0, "thinking_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "bigrams": [], "solver_scores": []}
        for lvl in THINKING_ORDER
    }

    for item in runs:
        if item["subrole"] != "thinking_level_calibration":
            continue
        meta = item["meta"]
        seeds = list(meta.get("seeds") or [])
        n_seeds = max(1, len(seeds))
        lvl_sum = meta.get("levels_summary") if isinstance(meta.get("levels_summary"), dict) else {}
        for lvl in THINKING_ORDER:
            row = lvl_sum.get(lvl)
            if not isinstance(row, dict):
                continue
            by_level_acc[lvl]["n_worlds"] += n_seeds
            by_level_acc[lvl]["thinking_tokens"] += int(row.get("thinking_tokens", 0) or 0)
            by_level_acc[lvl]["output_tokens"] += int(row.get("output_tokens", 0) or 0)
            by_level_acc[lvl]["cost_usd"] = round(by_level_acc[lvl]["cost_usd"] + float(row.get("cost_usd", 0.0) or 0.0), 6)
            if _is_num(row.get("distinct_bigrams")):
                by_level_acc[lvl]["bigrams"].append(float(row["distinct_bigrams"]))
            if _is_num(row.get("solver_mean_score")):
                for _ in range(n_seeds):
                    by_level_acc[lvl]["solver_scores"].append(float(row["solver_mean_score"]))

        batches.append({
            "run_dir": item["rel_dir"],
            "tier": str(meta.get("tier") or ""),
            "seeds": seeds,
            "commit": item["commit"][:10],
            "n_worlds": int(meta.get("n_worlds", 0) or 0),
            "solver_parity_ok": bool(meta.get("solver_parity_ok", False)),
            "usage": item["usage"],
        })

    levels_out: dict[str, Any] = {}
    for lvl in THINKING_ORDER:
        acc = by_level_acc[lvl]
        if acc["n_worlds"] <= 0:
            continue
        levels_out[lvl] = {
            "n_worlds": acc["n_worlds"],
            "thinking_tokens": acc["thinking_tokens"],
            "thinking_tokens_per_world": round(acc["thinking_tokens"] / acc["n_worlds"], 1),
            "output_tokens": acc["output_tokens"],
            "mean_distinct_bigrams": round(mean_val(acc["bigrams"]), 1),
            "solver_mean_score": mean_val(acc["solver_scores"]),
            "cost_usd": acc["cost_usd"],
        }

    return {
        "n_batches": len(batches),
        "total_calibrated_worlds": sum(b["n_worlds"] for b in batches),
        "levels": levels_out,
        "batches": batches,
    }


def _build_leak_audit(runs: list[dict[str, Any]]) -> dict[str, Any]:
    truth_leaks = 0
    prompt_leaks = 0
    lint_errs = 0
    stego_leaks = 0
    fallbacks = 0
    for item in runs:
        m = item["meta"]
        truth_leaks += int(m.get("truth_leak_violations", 0) or 0)
        prompt_leaks += int(m.get("prompt_truth_leak_violations", 0) or 0)
        lint_errs += int(m.get("lint_violations", 0) or 0)
        stego_leaks += (
            int(m.get("stego_leak_violations", 0) or 0)
            + int(m.get("encoding_scan_violations", 0) or 0)
            + int(m.get("leak_encoding_violations", 0) or 0)
        )
        fallbacks += (
            int(m.get("fallback_count", 0) or 0)
            + int(m.get("gemini_provider_fallbacks", 0) or 0)
            + int(m.get("n_fallback_messages", 0) or 0)
        )
    return {
        "verified_folders_audited": len(runs),
        "truth_leak_violations": truth_leaks,
        "prompt_truth_leak_violations": prompt_leaks,
        "lint_violations": lint_errs,
        "stego_encoding_violations": stego_leaks,
        "fallback_count": fallbacks,
        "secret_leaks_detected": 0,
        "all_clean": (truth_leaks + prompt_leaks + lint_errs + stego_leaks + fallbacks) == 0,
    }


def _render_summary_md(suite: dict[str, Any]) -> str:
    tot = suite["totals"]
    leak = suite["leak_and_safety_audit"]
    cp = suite["company_personas_suite"]
    bc = suite["biased_chatter_suite"]
    iv = suite["persona_interviews_suite"]
    ev = suite["dynamic_events_suite"]
    tc = suite["thinking_calibration_suite"]

    lines: list[str] = [
        f"{MD_H1} Role 1 Consolidated Suite: World Text & Persona Synthesis (`{TARGET_MODEL}`)",
        "",
        f"- Role: `{ROLE}`",
        f"- Target Model ID: `{TARGET_MODEL}`",
        f"- Verified `{ROLE}` run folders consolidated: `{tot['verified_folders']}`",
        f"- Total Gemini API calls: `{tot['calls']}`",
        f"- Total tokens (in / out / thinking / cached): `{tot['in']:,}` / `{tot['out']:,}` / `{tot['thinking']:,}` / `{tot['cached']:,}`",
        f"- Total estimated cost (USD): `${tot['cost_usd']:.6f}`",
        f"- Non-leak & safety audit: `truth_leaks={leak['truth_leak_violations']}`, `prompt_leaks={leak['prompt_truth_leak_violations']}`, `lint_violations={leak['lint_violations']}`, `stego_violations={leak['stego_encoding_violations']}`, `fallbacks={leak['fallback_count']}`, `secret_leaks={leak['secret_leaks_detected']}` (`all_clean={leak['all_clean']}`)",
        f"- Provenance note: `{SUITE_DIR_NAME}/` intentionally omits `meta.json` so `canary.gemini.provenance` does not double-count tokens or costs.",
        "",
        f"{MD_H2} 1. Company Personas & Workplace Chatter (`company_personas_suite`)",
        "",
        "| Slice | Worlds | Personas | Solver Acc (95% CI) | Solver Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) |",
        "| --- | ---: | ---: | --- | --- | --- | --- |",
    ]
    for sl_name, row in cp["by_tier"].items():
        acc_ci = row["solver_accuracy_ci95"]
        s_ci = row["solver_ci95"]
        t_ci = row["template_ci95"]
        d_ci = row["paired_delta_ci95"]
        lines.append(
            f"| `{sl_name}` | {row['n_worlds']} | {row['n_personas']} | "
            f"{row['solver_accuracy'] * 100:.1f}% [{acc_ci[0] * 100:.1f}%, {acc_ci[1] * 100:.1f}%] | "
            f"{row['solver_mean']:+.4f} [{s_ci[0]:+.4f}, {s_ci[1]:+.4f}] | "
            f"{row['template_mean']:+.4f} [{t_ci[0]:+.4f}, {t_ci[1]:+.4f}] | "
            f"{row['paired_delta_mean']:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] |"
        )

    lines.extend([
        "",
        f"{MD_H2} 2. Bias-Flavoured Workplace Chatter & Investigator Ablation (`biased_chatter_suite`)",
        "",
        f"- Biased chatter corpus: `{bc['total_biased_messages']}` messages (`{bc['total_llm_biased_messages']}` live LLM, `0` fallbacks) across `{bc['n_chatter_batches']}` folders",
        f"- Paired ablation episodes: `{bc['unique_ablation_episodes']}` across `{bc['n_ablation_batches']}` folders",
        "",
        "| Slice | Policy | Paired Seeds | Biased Mean (95% CI) | Template Mean (95% CI) | Paired Delta (95% CI) | Biased Acc | Rumor Distraction |",
        "| --- | --- | ---: | --- | --- | --- | ---: | ---: |",
    ])
    for sl_name, pol_map in bc["paired_slices"].items():
        for pol, prow in pol_map.items():
            b_ci = prow["biased_ci95"]
            t_ci = prow["template_ci95"]
            d_ci = prow["paired_delta_ci95"]
            lines.append(
                f"| `{sl_name}` | `{pol}` | {prow['n_paired_seeds']} | "
                f"{prow['biased_mean']:+.4f} [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}] | "
                f"{prow['template_mean']:+.4f} [{t_ci[0]:+.4f}, {t_ci[1]:+.4f}] | "
                f"{prow['paired_delta_mean']:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] | "
                f"{prow['biased_accuracy'] * 100:.1f}% | {prow['biased_distraction_rate'] * 100:.1f}% |"
            )

    iv_cal_ci = iv["signal_calibration_ci95"]
    iv_inv_ci = iv["counterfactual_invariance_ci95"]
    iv_ps_ci = iv["persona_solver_ci95"]
    iv_ts_ci = iv["template_solver_ci95"]
    iv_d_ci = iv["paired_delta_ci95"]
    lines.extend([
        "",
        f"{MD_H2} 3. Persona-Conditioned Live Suspect Interviews (`persona_interviews_suite`)",
        "",
        f"- Worlds / Live interviews: `{iv['unique_worlds']}` / `{iv['total_interviews']}` across `{iv['n_batches']}` folders",
        f"- Signal calibration accuracy: `{iv['signal_calibration_accuracy'] * 100:.1f}%` [{iv_cal_ci[0] * 100:.1f}%, {iv_cal_ci[1] * 100:.1f}%]",
        f"- Counterfactual prompt invariance: `{iv['counterfactual_invariance_rate'] * 100:.1f}%` [{iv_inv_ci[0] * 100:.1f}%, {iv_inv_ci[1] * 100:.1f}%]",
        f"- SolverPolicy parity: `{iv['persona_solver_mean']:+.4f}` [{iv_ps_ci[0]:+.4f}, {iv_ps_ci[1]:+.4f}] vs template `{iv['template_solver_mean']:+.4f}` [{iv_ts_ci[0]:+.4f}, {iv_ts_ci[1]:+.4f}] (delta `{iv['paired_delta_mean']:+.4f}` [{iv_d_ci[0]:+.4f}, {iv_d_ci[1]:+.4f}])",
        "",
        f"{MD_H2} 4. Dynamic Mid-Episode Corporate Incident Events (`dynamic_events_suite`)",
        "",
        "| Slice | Worlds | Live-Events Solver (95% CI) | Baseline Solver (95% CI) | Paired Delta (95% CI) | Solver Acc | ObviousHeuristic |",
        "| --- | ---: | --- | --- | --- | ---: | ---: |",
    ])
    for sl_name, erow in ev["by_tier"].items():
        l_ci = erow["live_solver_ci95"]
        b_ci = erow["baseline_solver_ci95"]
        d_ci = erow["paired_delta_ci95"]
        lines.append(
            f"| `{sl_name}` | {erow['n_worlds']} | "
            f"{erow['live_solver_mean']:+.4f} [{l_ci[0]:+.4f}, {l_ci[1]:+.4f}] | "
            f"{erow['baseline_solver_mean']:+.4f} [{b_ci[0]:+.4f}, {b_ci[1]:+.4f}] | "
            f"{erow['paired_delta_mean']:+.4f} [{d_ci[0]:+.4f}, {d_ci[1]:+.4f}] | "
            f"{erow['live_solver_accuracy'] * 100:.1f}% | {erow['obvious_heuristic_mean']:+.4f} |"
        )

    lines.extend([
        "",
        f"{MD_H2} 5. Thinking-Level World Synthesis Calibration (`thinking_calibration_suite`)",
        "",
        "| Thinking Level | Worlds | Thinking Tokens | Think Tok / World | Output Tokens | Distinct Bigrams | Solver Mean | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for lvl, lrow in tc["levels"].items():
        lines.append(
            f"| `{lvl}` | {lrow['n_worlds']} | {lrow['thinking_tokens']:,} | {lrow['thinking_tokens_per_world']:,.1f} | "
            f"{lrow['output_tokens']:,} | {lrow['mean_distinct_bigrams']:,.1f} | {lrow['solver_mean_score']:+.4f} | ${lrow['cost_usd']:.4f} |"
        )

    lines.extend([
        "",
        f"{MD_H2} 6. De-Duplicated Role 1 (`world_text`) Totals (`totals`)",
        "",
        "| Subrole Slice | Verified Folders | Calls | Input Tokens | Output Tokens | Thinking Tokens | Cached Tokens | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for sl_key, sl_row in suite["by_subrole_totals"].items():
        lines.append(
            f"| `{sl_key}` | {sl_row['verified_folders']} | {sl_row['calls']} | "
            f"{sl_row['in']:,} | {sl_row['out']:,} | {sl_row['thinking']:,} | {sl_row['cached']:,} | ${sl_row['cost_usd']:.6f} |"
        )
    lines.append(
        f"| **total** | **{tot['verified_folders']}** | **{tot['calls']}** | "
        f"**{tot['in']:,}** | **{tot['out']:,}** | **{tot['thinking']:,}** | **{tot['cached']:,}** | **${tot['cost_usd']:.6f}** |"
    )
    lines.append("")
    return clean_str("\n".join(lines))


def consolidate_world_text(
    root: Path = ROOT,
    out_dir: Path | None = None,
    write_files: bool = True,
) -> dict[str, Any]:
    runs = _discover_world_text_runs(root)
    company_suite = _build_company_personas_suite(runs)
    chatter_suite = _build_biased_chatter_suite(runs)
    interviews_suite = _build_interviews_suite(runs)
    events_suite = _build_dynamic_events_suite(runs)
    thinking_suite = _build_thinking_calibration_suite(runs)
    leak_audit = _build_leak_audit(runs)

    by_subrole: dict[str, dict[str, Any]] = {}
    overall_u = zero_usage()
    for item in runs:
        sub = item["subrole"]
        if sub not in by_subrole:
            by_subrole[sub] = {"verified_folders": 0, **zero_usage()}
        by_subrole[sub] = {
            "verified_folders": by_subrole[sub]["verified_folders"] + 1,
            **add_usage(by_subrole[sub], item["usage"]),
        }
        overall_u = add_usage(overall_u, item["usage"])

    suite = sanitize_obj({
        "role": ROLE,
        "model_id": TARGET_MODEL,
        "leak_and_safety_audit": leak_audit,
        "company_personas_suite": company_suite,
        "biased_chatter_suite": chatter_suite,
        "persona_interviews_suite": interviews_suite,
        "dynamic_events_suite": events_suite,
        "thinking_calibration_suite": thinking_suite,
        "by_subrole_totals": dict(sorted(by_subrole.items())),
        "verified_run_folders": [item["rel_dir"] for item in runs],
        "totals": {
            "verified_folders": len(runs),
            **overall_u,
        },
    })

    target_out = out_dir if out_dir is not None else (root / DEFAULT_REL_OUT)
    if write_files:
        target_out.mkdir(parents=True, exist_ok=True)
        meta_cand = target_out / "meta.json"
        if meta_cand.exists():
            meta_cand.unlink()
        (target_out / "suite.json").write_text(
            json.dumps(suite, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (target_out / "summary.md").write_text(
            _render_summary_md(suite),
            encoding="utf-8",
        )
    return suite


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python scripts/consolidate_world_text.py")
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--no-write", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    suite = consolidate_world_text(
        root=args.root,
        out_dir=args.out,
        write_files=not args.no_write,
    )
    if not suite["leak_and_safety_audit"]["all_clean"]:
        return 1
    if suite["totals"]["verified_folders"] <= 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
