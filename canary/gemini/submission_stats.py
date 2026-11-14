from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

from canary.gemini.provenance import (
    ENV_KEY_RE,
    GOOGLE_KEY_RE,
    OAUTH_RE,
    REQUIRED_ROLES,
    SK_KEY_RE,
    TARGET_MODEL,
    _has_env_secret,
    audit_provenance,
)
from canary.gemini.roles_dashboard import (
    ROLE_SPECS,
    collect_roles_data,
    git_head,
)

DEFAULT_OUT_MD = "docs/gemini/ROLES_REPORT.md"
DEFAULT_OUT_JSON = "results/gemini_roles/submission_stats.json"

TODO_TBD_RE = re.compile(r"\b(?:TODO|TBD)\b", re.IGNORECASE)
RUN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])((?:results/gemini_roles|data/runs/committed)/[A-Za-z0-9_.\-/]+)"
)
BACKTICK_RE = re.compile(r"`([^`]+)`")
EXTRA_COUNT_SUFFIX_RE = re.compile(r"\s*\(\+\d+\s+more\)\s*$")

FILE_SUFFIXES = frozenset({
    ".json",
    ".jsonl",
    ".md",
    ".html",
    ".txt",
    ".py",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".csv",
    ".pdf",
})

NON_FOLDER_CELLS = frozenset({
    "",
    "-",
    "none",
    "unverified",
    "n/a",
    "pending",
})


def _is_num(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and not math.isnan(float(val))


def _redact_env_secrets(text: str) -> str:
    if not _has_env_secret(text):
        return text
    return ENV_KEY_RE.sub("[redacted]", text)


def sanitize_report_str(val: Any) -> str:
    if val is None:
        return ""
    s = str(val)
    s = _redact_env_secrets(s)
    s = GOOGLE_KEY_RE.sub("[redacted]", s)
    s = SK_KEY_RE.sub("[redacted]", s)
    s = OAUTH_RE.sub("[redacted]", s)
    s = s.replace("\u2014", "-").replace("\u2013", "-")
    s = s.replace("\u27e8", "[").replace("\u27e9", "]")
    s = TODO_TBD_RE.sub("unspecified", s)
    return s


def _md_cell(val: Any) -> str:
    txt = sanitize_report_str(val).replace("\r", " ").replace("\n", " ").strip()
    return txt.replace("|", "\\|")


def _fmt_pct(val: float) -> str:
    ratio = val / 100.0 if val > 1.0001 else val
    return f"{ratio * 100.0:.0f}%"


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, UnicodeDecodeError, ValueError):
        return {}


def _count_jsonl_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        return sum(1 for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip())
    except OSError:
        return 0


def _extract_calls(run_dir: Path, meta: dict[str, Any], dash_calls: int) -> int:
    if dash_calls > 0:
        return int(dash_calls)
    usage = meta.get("usage")
    if isinstance(usage, dict):
        for key in ("calls", "n_calls", "api_calls", "calls_total"):
            val = usage.get(key)
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                return val
    for key in ("calls", "n_calls", "api_calls", "mole_decisions_count"):
        val = meta.get(key)
        if isinstance(val, int) and not isinstance(val, bool) and val > 0:
            return val
    for fname in ("vision_calls.jsonl", "mole_decisions.jsonl"):
        n_lines = _count_jsonl_lines(run_dir / fname)
        if n_lines > 0:
            return n_lines
    return 0


def _is_paired_or_ablation(
    role: str,
    meta: dict[str, Any],
    companions: dict[str, Any],
    dash_key_metric: str,
) -> bool:
    if role == "multimodal_evidence":
        if (
            _is_num(meta.get("multimodal_mean_score"))
            and (_is_num(meta.get("blind_ablation_mean_score")) or _is_num(meta.get("blind_mean_score")))
        ):
            return True
        comp = companions.get("comparison")
        if isinstance(comp, dict) and isinstance(comp.get("summary"), dict):
            return True
        return False

    if role == "investigators":
        lvl = meta.get("levels_summary")
        if isinstance(lvl, dict) and len(lvl) >= 2:
            return True
        if "vs solver" in dash_key_metric.lower():
            return True
        if _is_num(meta.get("solver_mean_score")) or isinstance(meta.get("solver_baseline"), dict):
            return True
        return False

    if role == "adaptive_mole":
        for key in (
            "solver_score",
            "solver_mean",
            "fresh_solver_accuracy",
            "kept_solver_mean",
            "solver_accuracy",
            "eval_full_solver_mean",
            "design_solver_mean",
        ):
            if _is_num(meta.get(key)):
                return True
        if _is_num(meta.get("n_kept")) and _is_num(meta.get("n_llm_valid")):
            return True
        if isinstance(meta.get("baseline_default_mole"), dict) or isinstance(meta.get("fresh_confirmation"), dict):
            return True
        return False

    if role == "world_text":
        for key in ("carbon_biased_mean", "solver_episodes_verified", "solver_mean_score"):
            if _is_num(meta.get(key)):
                return True
        if meta.get("solver_parity_ok") is True or meta.get("solver_all_clean") is True:
            return True
        return False

    if role == "failure_analyst":
        if _is_num(meta.get("verified_quotes_pct")):
            return True
        return False

    if role == "exploit_hunter":
        if _is_num(meta.get("ledger_verified")) or _is_num(meta.get("attempts")):
            return True
        return False

    return False


def _build_headline_metric(
    role: str,
    meta: dict[str, Any],
    companions: dict[str, Any],
    dash_key_metric: str,
) -> str:
    explicit = meta.get("key_metric")
    if isinstance(explicit, str) and explicit.strip():
        return sanitize_report_str(explicit.strip())

    if role == "world_text":
        if _is_num(meta.get("carbon_biased_mean")) and _is_num(meta.get("carbon_template_mean")):
            ep_n = int(meta.get("episode_count", 0) or 0)
            cb = float(meta["carbon_biased_mean"])
            ct = float(meta["carbon_template_mean"])
            parts = []
            if ep_n > 0:
                parts.append(f"{ep_n} eps")
            parts.append(f"carbon {cb:+.3f} (biased) vs {ct:+.3f} (template)")
            if _is_num(meta.get("solver_biased_mean")):
                parts.append(f"solver {float(meta['solver_biased_mean']):+.3f}")
            return sanitize_report_str(", ".join(parts))

        if _is_num(meta.get("n_worlds")):
            parts = [f"{int(meta['n_worlds'])} worlds"]
            if _is_num(meta.get("n_personas_generated")):
                parts.append(f"{int(meta['n_personas_generated'])} personas")
            if _is_num(meta.get("truth_leak_violations")):
                parts.append(f"{int(meta['truth_leak_violations'])} truth leaks")
            if _is_num(meta.get("lint_violations")):
                parts.append(f"{int(meta['lint_violations'])} lint errs")
            if _is_num(meta.get("solver_mean_score")):
                parts.append(f"solver {float(meta['solver_mean_score']):+.3f}")
            return sanitize_report_str(", ".join(parts))

        if _is_num(meta.get("n_messages")):
            msg_str = f"{int(meta['n_messages'])} messages"
            if _is_num(meta.get("n_seeds")):
                msg_str += f" ({int(meta['n_seeds'])} seeds)"
            parts = [msg_str]
            if _is_num(meta.get("truth_leak_violations")):
                parts.append(f"{int(meta['truth_leak_violations'])} truth leaks")
            if _is_num(meta.get("lint_violations")):
                parts.append(f"{int(meta['lint_violations'])} lint errs")
            return sanitize_report_str(", ".join(parts))

    if role == "adaptive_mole":
        if _is_num(meta.get("solver_mean")) and _is_num(meta.get("solver_accuracy")):
            parts = []
            if _is_num(meta.get("mole_decisions_count")):
                parts.append(f"{int(meta['mole_decisions_count'])} mole decisions")
            sol_m = float(meta["solver_mean"])
            base = meta.get("baseline_default_mole")
            if isinstance(base, dict) and _is_num(base.get("solver_mean")):
                parts.append(f"solver {sol_m:+.3f} (vs {float(base['solver_mean']):+.3f} default)")
            else:
                parts.append(f"solver {sol_m:+.3f}")
            parts.append(f"solver acc {_fmt_pct(float(meta['solver_accuracy']))}")
            return sanitize_report_str(", ".join(parts))

        if _is_num(meta.get("n_kept")) and _is_num(meta.get("n_llm_valid")) and _is_num(meta.get("eval_full_solver_mean")):
            parts = [
                f"kept {int(meta['n_kept'])}/{int(meta['n_llm_valid'])} solvable scenarios",
                f"eval solver {float(meta['eval_full_solver_mean']):+.3f}",
            ]
            if _is_num(meta.get("eval_heuristic_mean")):
                parts.append(f"heuristic {float(meta['eval_heuristic_mean']):+.3f}")
            if _is_num(meta.get("n_episodes")):
                parts.append(f"n={int(meta['n_episodes'])}")
            return sanitize_report_str(", ".join(parts))

    if role == "investigators":
        lvl = meta.get("levels_summary")
        sol_base = meta.get("solver_baseline")
        if isinstance(lvl, dict) and lvl and isinstance(sol_base, dict) and _is_num(sol_base.get("mean_score")):
            n_ep = int(meta.get("n_episodes", 0) or 0)
            suffix = f" (vs solver {float(sol_base['mean_score']):+.3f}"
            if n_ep > 0:
                suffix += f", n={n_ep}"
            suffix += ")"
            return sanitize_report_str(dash_key_metric + suffix)

    if role == "failure_analyst":
        if _is_num(meta.get("n_calibrated_episodes")) and _is_num(meta.get("ece")):
            parts = [
                f"{int(meta['n_calibrated_episodes'])} calibrated eps",
                f"ECE {float(meta['ece']):.3f}",
            ]
            if _is_num(meta.get("verified_quotes_pct")):
                parts.append(f"{_fmt_pct(float(meta['verified_quotes_pct']))} verified quotes")
            return sanitize_report_str(", ".join(parts))

    if role == "exploit_hunter":
        if _is_num(meta.get("ledger_verified")) and "ledger" not in dash_key_metric.lower():
            return sanitize_report_str(f"{dash_key_metric}, {int(meta['ledger_verified'])} ledger-verified")

    if role == "multimodal_evidence":
        if _is_num(meta.get("multimodal_mean_score")) and (
            _is_num(meta.get("blind_ablation_mean_score")) or _is_num(meta.get("blind_mean_score"))
        ):
            base_metric = dash_key_metric
            if _is_num(meta.get("oracle_score_recovery_ratio")):
                rec = _fmt_pct(float(meta["oracle_score_recovery_ratio"]))
                base_metric = f"{base_metric}, {rec} oracle recovery"
            return sanitize_report_str(base_metric)

        res_doc = companions.get("results")
        metrics = res_doc.get("metrics") if isinstance(res_doc, dict) and isinstance(res_doc.get("metrics"), dict) else None
        if isinstance(metrics, dict) and _is_num(metrics.get("top1_mole_accuracy")):
            parts = []
            if _is_num(meta.get("n_images_read_by_model")):
                tier_lbl = sanitize_report_str(meta.get("tier") or "")
                img_s = f"{int(meta['n_images_read_by_model'])} images"
                if tier_lbl:
                    img_s += f" ({tier_lbl})"
                parts.append(img_s)
            parts.append(f"top-1 mole acc {_fmt_pct(float(metrics['top1_mole_accuracy']))}")
            if _is_num(metrics.get("top1_decoy_accuracy")):
                decoy_s = f"decoy acc {_fmt_pct(float(metrics['top1_decoy_accuracy']))}"
                if _is_num(metrics.get("naive_after_hours_baseline_mole_accuracy")):
                    decoy_s += f" (naive {_fmt_pct(float(metrics['naive_after_hours_baseline_mole_accuracy']))})"
                parts.append(decoy_s)
            return sanitize_report_str(", ".join(parts))

    return sanitize_report_str(dash_key_metric or "verified gemini-4-carbon run")


def _mean_ci(vals: list[float]) -> tuple[float, float]:
    if not vals:
        return 0.0, 0.0
    m = sum(vals) / len(vals)
    if len(vals) < 2:
        return m, 0.0
    var = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
    return m, 1.96 * math.sqrt(var / len(vals))


def _agg_paired_subset(label: str, subset: list[dict[str, Any]]) -> dict[str, Any]:
    c_scores = [float(r["carbon_score"]) for r in subset]
    s_scores = [float(r["solver_score"]) for r in subset]
    diffs = [float(r["diff"]) for r in subset]
    cm, cci = _mean_ci(c_scores)
    sm, sci = _mean_ci(s_scores)
    dm, dci = _mean_ci(diffs)
    c_acc = sum(1 for r in subset if r.get("carbon_correct")) / len(subset)
    s_known = [r for r in subset if r.get("solver_correct") is not None]
    s_acc = (sum(1 for r in s_known if r["solver_correct"]) / len(s_known)) if s_known else None
    c_days = [int(r["carbon_day"]) for r in subset if isinstance(r.get("carbon_day"), int) and r.get("carbon_accused")]
    s_days = [int(r["solver_day"]) for r in subset if isinstance(r.get("solver_day"), int)]
    ratio = (cm / sm) if sm > 1e-9 else None
    return {
        "tier": sanitize_report_str(label),
        "n": len(subset),
        "seeds": [int(r["seed"]) for r in subset],
        "carbon_mean": round(cm, 4),
        "carbon_ci": round(cci, 4),
        "solver_mean": round(sm, 4),
        "solver_ci": round(sci, 4),
        "paired_diff": round(dm, 4),
        "diff_ci": round(dci, 4),
        "ratio": round(ratio, 4) if ratio is not None else None,
        "carbon_accuracy": round(c_acc, 4),
        "solver_accuracy": round(s_acc, 4) if s_acc is not None else None,
        "carbon_accuse_day": round(sum(c_days) / len(c_days), 2) if c_days else None,
        "solver_accuse_day": round(sum(s_days) / len(s_days), 2) if s_days else None,
    }


def _build_paired_solver_summary(
    raw_paired: dict[str, Any],
    verified_folders: set[str],
    meta_by_folder: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    seed_rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, int]] = set()

    for row in raw_paired.get("seeds") or []:
        folder = str(row.get("run_folder") or "")
        if folder not in verified_folders:
            continue
        tier = sanitize_report_str(row.get("tier") or "")
        seed = int(row["seed"])
        seen_pairs.add((tier, seed))
        seed_rows.append({
            "tier": tier,
            "seed": seed,
            "carbon_score": round(float(row["carbon_score"]), 4),
            "solver_score": round(float(row["solver_score"]), 4),
            "diff": round(float(row["diff"]), 4),
            "carbon_correct": bool(row.get("carbon_correct")),
            "solver_correct": row.get("solver_correct") if isinstance(row.get("solver_correct"), bool) else None,
            "carbon_accused": bool(row.get("carbon_accused")),
            "carbon_day": int(row["carbon_day"]) if isinstance(row.get("carbon_day"), int) else None,
            "solver_day": int(row["solver_day"]) if isinstance(row.get("solver_day"), int) else None,
            "run_folder": sanitize_report_str(folder),
        })

    for folder in sorted(verified_folders):
        meta = meta_by_folder.get(folder) or {}
        if meta.get("role") != "investigators" or meta.get("hint"):
            continue
        lvl_map = meta.get("levels_summary")
        sol_base = meta.get("solver_baseline")
        if not isinstance(lvl_map, dict) or not isinstance(sol_base, dict):
            continue
        chosen_lvl = None
        for pref in ("high", "medium", "low", "minimal"):
            if isinstance(lvl_map.get(pref), dict) and isinstance(lvl_map[pref].get("per_seed"), dict):
                chosen_lvl = lvl_map[pref]
                break
        if chosen_lvl is None:
            continue
        sol_per_seed = sol_base.get("per_seed") if isinstance(sol_base.get("per_seed"), dict) else {}
        tier = sanitize_report_str(chosen_lvl.get("tier") or meta.get("tier") or "")
        if not tier:
            continue
        for seed_key, ep in sorted(chosen_lvl["per_seed"].items(), key=lambda kv: str(kv[0])):
            if not isinstance(ep, dict) or not _is_num(ep.get("score")):
                continue
            seed_val = int(ep["seed"]) if isinstance(ep.get("seed"), int) else int(seed_key)
            if (tier, seed_val) in seen_pairs:
                continue
            sol_entry = sol_per_seed.get(str(seed_val)) if isinstance(sol_per_seed, dict) else None
            sol_score = (
                float(sol_entry["score"])
                if isinstance(sol_entry, dict) and _is_num(sol_entry.get("score"))
                else (float(ep["solver_score"]) if _is_num(ep.get("solver_score")) else None)
            )
            if sol_score is None:
                continue
            c_score = float(ep["score"])
            seen_pairs.add((tier, seed_val))
            seed_rows.append({
                "tier": tier,
                "seed": seed_val,
                "carbon_score": round(c_score, 4),
                "solver_score": round(sol_score, 4),
                "diff": round(c_score - sol_score, 4),
                "carbon_correct": bool(ep.get("correct")),
                "solver_correct": bool(sol_entry["correct"]) if isinstance(sol_entry, dict) and "correct" in sol_entry else None,
                "carbon_accused": bool(ep.get("accused")),
                "carbon_day": int(ep["final_day"]) if isinstance(ep.get("final_day"), int) else None,
                "solver_day": int(sol_entry["final_day"]) if isinstance(sol_entry, dict) and isinstance(sol_entry.get("final_day"), int) else None,
                "run_folder": sanitize_report_str(folder),
            })

    tier_order = {"easy": 0, "medium": 1, "hard": 2}
    seed_rows.sort(key=lambda r: (tier_order.get(r["tier"], 99), r["tier"], r["seed"]))

    tiers_present: list[str] = []
    for t in ("easy", "medium", "hard"):
        if any(r["tier"] == t for r in seed_rows):
            tiers_present.append(t)
    for r in seed_rows:
        if r["tier"] not in tiers_present:
            tiers_present.append(r["tier"])

    tier_summaries = [_agg_paired_subset(t, [r for r in seed_rows if r["tier"] == t]) for t in tiers_present]
    overall = _agg_paired_subset("overall", seed_rows) if seed_rows else None
    return {
        "tiers": tier_summaries,
        "overall": overall,
        "seeds": seed_rows,
    }


def _build_multimodal_ablation_summary(
    mm_runs: list[dict[str, Any]],
    meta_by_folder: dict[str, dict[str, Any]],
    companions_by_folder: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    ablation_runs: list[dict[str, Any]] = []
    soc_raster_runs: list[dict[str, Any]] = []
    unique_seed_map: dict[tuple[str, int], dict[str, Any]] = {}

    for run in mm_runs:
        folder = run["run_folder"]
        meta = meta_by_folder.get(folder) or {}
        comps = companions_by_folder.get(folder) or {}
        comp_doc = comps.get("comparison") if isinstance(comps.get("comparison"), dict) else {}
        comp_sum = comp_doc.get("summary") if isinstance(comp_doc.get("summary"), dict) else {}

        mm_score: float | None = None
        bl_score: float | None = None
        orc_score: float | None = None

        if _is_num(meta.get("multimodal_mean_score")):
            mm_score = float(meta["multimodal_mean_score"])
        elif isinstance(comp_sum.get("multimodal_carbon"), dict) and _is_num(comp_sum["multimodal_carbon"].get("mean_score")):
            mm_score = float(comp_sum["multimodal_carbon"]["mean_score"])

        if _is_num(meta.get("blind_ablation_mean_score")):
            bl_score = float(meta["blind_ablation_mean_score"])
        elif _is_num(meta.get("blind_mean_score")):
            bl_score = float(meta["blind_mean_score"])
        elif isinstance(comp_sum.get("blind_no_vision"), dict) and _is_num(comp_sum["blind_no_vision"].get("mean_score")):
            bl_score = float(comp_sum["blind_no_vision"]["mean_score"])

        if _is_num(meta.get("oracle_mean_score")):
            orc_score = float(meta["oracle_mean_score"])
        elif isinstance(comp_sum.get("text_oracle"), dict) and _is_num(comp_sum["text_oracle"].get("mean_score")):
            orc_score = float(comp_sum["text_oracle"]["mean_score"])

        if mm_score is not None and bl_score is not None:
            tier = sanitize_report_str(meta.get("tier") or comp_doc.get("tier") or "unspecified")
            raw_seeds = meta.get("seeds") if isinstance(meta.get("seeds"), list) else comp_doc.get("seeds")
            seeds = [int(s) for s in raw_seeds if isinstance(s, int) and not isinstance(s, bool)] if isinstance(raw_seeds, list) else []
            n_eps = int(meta.get("n_episodes") or comp_doc.get("n_episodes") or len(seeds) or run["count"])
            n_imgs = int(meta.get("n_images_read_by_model") or comp_doc.get("n_images_read_by_model") or 0)
            n_can_imgs = int(meta.get("n_canary_memos_read_by_model") or 0)
            vis_acc = float(meta["variant_vision_accuracy"]) if _is_num(meta.get("variant_vision_accuracy")) else (
                float(comp_sum["variant_vision_accuracy"]) if _is_num(comp_sum.get("variant_vision_accuracy")) else None
            )
            can_vis_acc = float(meta["canary_variant_vision_accuracy"]) if _is_num(meta.get("canary_variant_vision_accuracy")) else (
                float(comp_sum["canary_variant_vision_accuracy"]) if _is_num(comp_sum.get("canary_variant_vision_accuracy")) else None
            )
            mm_acc = float(meta["multimodal_accuracy"]) if _is_num(meta.get("multimodal_accuracy")) else (
                float(comp_sum["multimodal_carbon"]["accuracy"])
                if isinstance(comp_sum.get("multimodal_carbon"), dict) and _is_num(comp_sum["multimodal_carbon"].get("accuracy"))
                else None
            )
            bl_acc = float(meta["blind_accuracy"]) if _is_num(meta.get("blind_accuracy")) else (
                float(comp_sum["blind_no_vision"]["accuracy"])
                if isinstance(comp_sum.get("blind_no_vision"), dict) and _is_num(comp_sum["blind_no_vision"].get("accuracy"))
                else None
            )
            orc_acc = float(meta["oracle_accuracy"]) if _is_num(meta.get("oracle_accuracy")) else (
                float(comp_sum["text_oracle"]["accuracy"])
                if isinstance(comp_sum.get("text_oracle"), dict) and _is_num(comp_sum["text_oracle"].get("accuracy"))
                else None
            )
            rec_ratio: float | None = None
            if _is_num(meta.get("oracle_score_recovery_ratio")):
                rec_ratio = float(meta["oracle_score_recovery_ratio"])
            elif orc_score is not None and orc_score > 1e-9:
                rec_ratio = round(mm_score / orc_score, 4)

            ablation_runs.append({
                "run_folder": folder,
                "subrole": run["subrole"],
                "model_id": run["model_id"],
                "commit": run["commit"],
                "tier": tier,
                "seeds": seeds,
                "n_episodes": n_eps,
                "n_images_read": n_imgs,
                "n_canary_memos_read": n_can_imgs,
                "vision_accuracy": round(vis_acc, 4) if vis_acc is not None else None,
                "canary_vision_accuracy": round(can_vis_acc, 4) if can_vis_acc is not None else None,
                "multimodal_mean_score": round(mm_score, 4),
                "blind_mean_score": round(bl_score, 4),
                "vision_gain": round(mm_score - bl_score, 4),
                "oracle_mean_score": round(orc_score, 4) if orc_score is not None else None,
                "oracle_recovery_ratio": round(rec_ratio, 4) if rec_ratio is not None else None,
                "multimodal_accuracy": round(mm_acc, 4) if mm_acc is not None else None,
                "blind_accuracy": round(bl_acc, 4) if bl_acc is not None else None,
                "oracle_accuracy": round(orc_acc, 4) if orc_acc is not None else None,
            })

            for ps in comp_doc.get("per_seed") or []:
                if not isinstance(ps, dict) or not isinstance(ps.get("seed"), int):
                    continue
                ps_tier = sanitize_report_str(ps.get("tier") or tier)
                key = (ps_tier, int(ps["seed"]))
                if key not in unique_seed_map:
                    mm_ep = ps.get("multimodal_carbon") if isinstance(ps.get("multimodal_carbon"), dict) else {}
                    bl_ep = ps.get("blind_no_vision") if isinstance(ps.get("blind_no_vision"), dict) else {}
                    orc_ep = ps.get("text_oracle") if isinstance(ps.get("text_oracle"), dict) else {}
                    if _is_num(mm_ep.get("score")) and _is_num(bl_ep.get("score")):
                        unique_seed_map[key] = {
                            "tier": ps_tier,
                            "seed": int(ps["seed"]),
                            "run_folder": folder,
                            "mm_score": float(mm_ep["score"]),
                            "bl_score": float(bl_ep["score"]),
                            "orc_score": float(orc_ep["score"]) if _is_num(orc_ep.get("score")) else None,
                            "mm_correct": bool(mm_ep.get("correct")),
                            "bl_correct": bool(bl_ep.get("correct")),
                            "n_memos": int(mm_ep.get("n_memos_inspected") or 0),
                            "vision_exact": int(mm_ep.get("vision_exact_matches") or 0),
                        }

        res_doc = comps.get("results") if isinstance(comps.get("results"), dict) else {}
        res_metrics = res_doc.get("metrics") if isinstance(res_doc.get("metrics"), dict) else {}
        if _is_num(res_metrics.get("top1_mole_accuracy")):
            soc_raster_runs.append({
                "run_folder": folder,
                "subrole": run["subrole"],
                "model_id": run["model_id"],
                "commit": run["commit"],
                "tier": sanitize_report_str(meta.get("tier") or res_doc.get("tier") or "unspecified"),
                "n_images_read": int(meta.get("n_images_read_by_model") or res_doc.get("n_images_read_by_model") or run["count"]),
                "top1_mole_accuracy": round(float(res_metrics["top1_mole_accuracy"]), 4),
                "top1_decoy_accuracy": round(float(res_metrics["top1_decoy_accuracy"]), 4)
                if _is_num(res_metrics.get("top1_decoy_accuracy"))
                else None,
                "naive_baseline_mole_accuracy": round(
                    float(res_metrics["naive_after_hours_baseline_mole_accuracy"]), 4
                )
                if _is_num(res_metrics.get("naive_after_hours_baseline_mole_accuracy"))
                else None,
            })

    pooled: dict[str, Any] | None = None
    if unique_seed_map:
        u_rows = [unique_seed_map[k] for k in sorted(unique_seed_map)]
        n_u = len(u_rows)
        mm_m = sum(r["mm_score"] for r in u_rows) / n_u
        bl_m = sum(r["bl_score"] for r in u_rows) / n_u
        orc_vals = [r["orc_score"] for r in u_rows if r["orc_score"] is not None]
        orc_m = (sum(orc_vals) / len(orc_vals)) if len(orc_vals) == n_u else None
        tot_memos = sum(r["n_memos"] for r in u_rows)
        tot_exact = sum(r["vision_exact"] for r in u_rows)
        pooled = {
            "n_episodes": n_u,
            "tiers": sorted({r["tier"] for r in u_rows}),
            "n_images_read": tot_memos,
            "vision_accuracy": round(tot_exact / tot_memos, 4) if tot_memos > 0 else None,
            "multimodal_mean_score": round(mm_m, 4),
            "blind_mean_score": round(bl_m, 4),
            "vision_gain": round(mm_m - bl_m, 4),
            "oracle_mean_score": round(orc_m, 4) if orc_m is not None else None,
            "oracle_recovery_ratio": round(mm_m / orc_m, 4) if orc_m is not None and orc_m > 1e-9 else None,
            "multimodal_accuracy": round(sum(1 for r in u_rows if r["mm_correct"]) / n_u, 4),
            "blind_accuracy": round(sum(1 for r in u_rows if r["bl_correct"]) / n_u, 4),
        }

    return {
        "available": len(ablation_runs) > 0,
        "canonical_ablation_run": ablation_runs[0] if ablation_runs else None,
        "runs": ablation_runs,
        "pooled_unique_seeds": pooled,
        "soc_raster_runs": soc_raster_runs,
    }


def build_submission_stats(
    root: str | Path = ".",
    *,
    provenance_report: dict[str, Any] | None = None,
    roles_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    prov = provenance_report if provenance_report is not None else audit_provenance(root_path)
    dash = roles_data if roles_data is not None else collect_roles_data(root_path)

    dash_by_folder: dict[str, dict[str, Any]] = {
        str(r["run_folder"]): r for r in (dash.get("runs") or [])
    }
    secret_leaks = prov.get("secret_leaks") or []
    no_repo_leaks = len(secret_leaks) == 0

    meta_by_folder: dict[str, dict[str, Any]] = {}
    companions_by_folder: dict[str, dict[str, Any]] = {}
    verified_candidates_by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in REQUIRED_ROLES}

    for prov_run in prov.get("runs") or []:
        if not prov_run.get("verified") or not no_repo_leaks:
            continue
        role = prov_run.get("role")
        if role not in REQUIRED_ROLES:
            continue
        folder = str(prov_run["run_dir"])
        dash_run = dash_by_folder.get(folder)
        if dash_run is not None and dash_run.get("model_id") != TARGET_MODEL:
            continue

        run_dir = root_path / folder
        meta = _load_json(run_dir / "meta.json")
        if bool(meta.get("plumbing_only")) or str(meta.get("source") or "").startswith("fallback"):
            continue
        if dash_run is None:
            parent_folders = [
                p.relative_to(root_path).as_posix()
                for p in run_dir.parents
                if p != root_path and root_path in p.parents
            ]
            if any(pf in dash_by_folder for pf in parent_folders) and not (meta.get("role") and meta.get("subrole")):
                continue

        companions: dict[str, Any] = {}
        for cname in ("swarm", "summary", "report", "results", "diagnoses", "comparison", "solver_check"):
            cdoc = _load_json(run_dir / f"{cname}.json")
            if cdoc:
                companions[cname] = cdoc

        meta_by_folder[folder] = meta
        companions_by_folder[folder] = companions

        dash_usage = (dash_run.get("usage") or {}) if dash_run else {}
        subrole_raw = (
            dash_run.get("subrole")
            if dash_run and dash_run.get("subrole")
            else (meta.get("subrole") or (run_dir.name if run_dir.name != role else "primary"))
        )
        subrole = sanitize_report_str(subrole_raw)
        dash_metric = str(dash_run.get("key_metric") or "") if dash_run else ""

        tin = int(prov_run["tokens_in"])
        tout = int(prov_run["tokens_out"])
        tthink = int(prov_run["thinking_tokens"] or dash_usage.get("thinking", 0) or 0)
        tcached = int(prov_run["cached_tokens"] or dash_usage.get("cached", 0) or 0)
        calls = _extract_calls(run_dir, meta, int(dash_usage.get("calls", 0) or 0))
        usd = round(float(prov_run["cost_usd"]), 6)
        count = int(prov_run["count"])

        headline_metric = _build_headline_metric(role, meta, companions, dash_metric)
        paired_flag = _is_paired_or_ablation(role, meta, companions, dash_metric)
        images_read = int(meta.get("n_images_read_by_model") or meta.get("n_charts_analyzed") or 0)
        is_hinted = bool(meta.get("hint"))

        verified_candidates_by_role[role].append({
            "role": role,
            "subrole": subrole,
            "run_folder": sanitize_report_str(folder),
            "model_id": sanitize_report_str(prov_run["model_id"]),
            "commit": sanitize_report_str(prov_run["commit"]),
            "count": count,
            "calls": calls,
            "tokens_in": tin,
            "tokens_out": tout,
            "thinking_tokens": tthink,
            "cached_tokens": tcached,
            "cost_usd": usd,
            "headline_metric": headline_metric,
            "_sort_key": (
                0 if paired_flag else 1,
                1 if is_hinted else 0,
                -count,
                -images_read,
                -calls,
                -tin,
                folder,
            ),
        })

    roles_out: dict[str, dict[str, Any]] = {}
    verified_roles: list[str] = []
    missing_roles: list[str] = []
    verified_folder_set: set[str] = set()

    for role in REQUIRED_ROLES:
        spec = ROLE_SPECS[role]
        ranked_raw = sorted(verified_candidates_by_role[role], key=lambda item: item["_sort_key"])
        clean_runs: list[dict[str, Any]] = [
            {k: v for k, v in item.items() if not k.startswith("_")}
            for item in ranked_raw
        ]
        for r in clean_runs:
            verified_folder_set.add(r["run_folder"])

        if clean_runs:
            verified_roles.append(role)
            canonical = clean_runs[0]
            supporting = clean_runs[1:]
        else:
            missing_roles.append(role)
            canonical = None
            supporting = []

        roles_out[role] = {
            "role": role,
            "index": spec["index"],
            "title": sanitize_report_str(spec["title"]),
            "stage": sanitize_report_str(spec["stage"]),
            "verified": canonical is not None,
            "n_verified_runs": len(clean_runs),
            "canonical_run": canonical,
            "supporting_runs": supporting,
            "all_verified_runs": clean_runs,
            "count": sum(r["count"] for r in clean_runs),
            "calls": sum(r["calls"] for r in clean_runs),
            "tokens_in": sum(r["tokens_in"] for r in clean_runs),
            "tokens_out": sum(r["tokens_out"] for r in clean_runs),
            "thinking_tokens": sum(r["thinking_tokens"] for r in clean_runs),
            "cached_tokens": sum(r["cached_tokens"] for r in clean_runs),
            "cost_usd": round(sum(r["cost_usd"] for r in clean_runs), 6),
        }

    paired_summary = _build_paired_solver_summary(
        dash.get("paired_comparison") or {},
        verified_folder_set,
        meta_by_folder,
    )
    mm_ablation = _build_multimodal_ablation_summary(
        roles_out["multimodal_evidence"]["all_verified_runs"],
        meta_by_folder,
        companions_by_folder,
    )

    all_clean_runs = [r for role in REQUIRED_ROLES for r in roles_out[role]["all_verified_runs"]]
    tot_in = sum(r["tokens_in"] for r in all_clean_runs)
    tot_out = sum(r["tokens_out"] for r in all_clean_runs)
    tot_think = sum(r["thinking_tokens"] for r in all_clean_runs)
    tot_cached = sum(r["cached_tokens"] for r in all_clean_runs)
    tot_calls = sum(r["calls"] for r in all_clean_runs)
    tot_count = sum(r["count"] for r in all_clean_runs)
    tot_cost = round(sum(r["cost_usd"] for r in all_clean_runs), 6)
    all_ok = len(missing_roles) == 0 and no_repo_leaks and bool(prov.get("verified"))

    return {
        "target_model": TARGET_MODEL,
        "git_head": sanitize_report_str(git_head(root_path)),
        "provenance": {
            "verified": all_ok,
            "scanned_runs": int((prov.get("totals") or {}).get("scanned_runs", 0)),
            "verified_runs": len(all_clean_runs),
            "secret_leaks_count": len(secret_leaks),
        },
        "totals": {
            "target_model": TARGET_MODEL,
            "required_roles": list(REQUIRED_ROLES),
            "verified_roles": verified_roles,
            "missing_roles": missing_roles,
            "n_roles_required": len(REQUIRED_ROLES),
            "n_roles_verified": len(verified_roles),
            "all_roles_verified": all_ok,
            "n_verified_carbon_runs": len(all_clean_runs),
            "n_canonical_runs": sum(1 for role in REQUIRED_ROLES if roles_out[role]["canonical_run"] is not None),
            "n_supporting_runs": sum(len(roles_out[role]["supporting_runs"]) for role in REQUIRED_ROLES),
            "count": tot_count,
            "calls": tot_calls,
            "tokens_in": tot_in,
            "tokens_out": tot_out,
            "thinking_tokens": tot_think,
            "cached_tokens": tot_cached,
            "total_tokens": tot_in + tot_out + tot_think,
            "cost_usd": tot_cost,
        },
        "roles": roles_out,
        "paired_solver_comparison": paired_summary,
        "multimodal_ablation": mm_ablation,
    }


def extract_cited_run_folders(text: str) -> list[str]:
    cited: list[str] = []
    seen: set[str] = set()

    def _add(raw_path: str) -> None:
        cleaned = EXTRA_COUNT_SUFFIX_RE.sub("", raw_path.strip())
        cleaned = cleaned.strip("`\"'").rstrip(".,;:!?)>'\"`/")
        if not cleaned or cleaned.lower() in NON_FOLDER_CELLS:
            return
        p = Path(cleaned)
        parts = p.parts
        if len(parts) == 3 and parts[:2] == ("results", "gemini_roles") and p.suffix.lower() in FILE_SUFFIXES:
            return
        if parts and parts[-1] == "meta.json" and len(parts) >= 2:
            cleaned = p.parent.as_posix()
            p = Path(cleaned)
        elif p.suffix.lower() in FILE_SUFFIXES:
            return
        if cleaned not in seen:
            seen.add(cleaned)
            cited.append(cleaned)

    for match in RUN_PATH_RE.finditer(text):
        _add(match.group(1))

    lines = text.splitlines()
    run_col_idx: int | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            run_col_idx = None
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if all(set(c) <= {"-", ":", " "} for c in cells if c):
            continue
        lower_cells = [c.lower() for c in cells]
        if any(lbl in ("run folder", "run_folder", "run dir", "run_dir") for lbl in lower_cells):
            for idx, lbl in enumerate(lower_cells):
                if lbl in ("run folder", "run_folder", "run dir", "run_dir"):
                    run_col_idx = idx
                    break
            continue
        if run_col_idx is not None and run_col_idx < len(cells):
            cell_val = cells[run_col_idx]
            bt_matches = BACKTICK_RE.findall(cell_val)
            if bt_matches:
                for bt in bt_matches:
                    _add(bt)
            else:
                _add(cell_val)

    return cited


def validate_report_text(text: str, root: str | Path = ".") -> list[str]:
    root_path = Path(root).resolve()
    errors: list[str] = []

    if "\u27e8" in text or "\u27e9" in text:
        errors.append("angle_bracket_placeholder")
    if TODO_TBD_RE.search(text):
        errors.append("todo_or_tbd_placeholder")
    if "\u2014" in text:
        errors.append("em_dash")
    if "\u2013" in text:
        errors.append("en_dash")

    if GOOGLE_KEY_RE.search(text):
        errors.append("secret_leak:google_api_key")
    if SK_KEY_RE.search(text):
        errors.append("secret_leak:sk_api_key")
    if OAUTH_RE.search(text):
        errors.append("secret_leak:oauth_token")
    if _has_env_secret(text):
        errors.append("secret_leak:env_api_key")

    for folder in extract_cited_run_folders(text):
        cand = (root_path / folder).resolve()
        try:
            cand.relative_to(root_path)
        except ValueError:
            errors.append(f"missing_run_folder:{folder}")
            continue
        if not cand.is_dir():
            errors.append(f"missing_run_folder:{folder}")

    return errors


def assert_valid_report_text(text: str, root: str | Path = ".") -> None:
    errs = validate_report_text(text, root)
    if errs:
        raise ValueError(f"Report validation failed: {', '.join(errs)}")


def render_submission_stats_json(stats: dict[str, Any]) -> str:
    return json.dumps(stats, indent=2, sort_keys=False) + "\n"


def render_submission_report_md(stats: dict[str, Any]) -> str:
    tot = stats["totals"]
    prov = stats["provenance"]
    roles_map = stats["roles"]
    paired = stats["paired_solver_comparison"]
    mm = stats["multimodal_ablation"]

    status_txt = "VERIFIED" if tot["all_roles_verified"] else f"INCOMPLETE ({tot['n_roles_verified']}/{tot['n_roles_required']} roles verified)"
    missing_txt = ", ".join(f"`{r}`" for r in tot["missing_roles"]) if tot["missing_roles"] else "none"

    lines: list[str] = [
        "# Gemini 6-Role Submission Report",
        "",
        "Machine-generated provenance and evaluation ledger across all six required Canary roles.",
        "Every number below is extracted programmatically from committed run files with zero hand-typed metrics.",
        "",
        "## Executive Summary",
        "",
        f"- Provenance status: **{status_txt}**",
        f"- Target model: `{_md_cell(stats['target_model'])}`",
        f"- Repository HEAD at build: `{_md_cell(stats['git_head'])}`",
        f"- Verified roles: **{tot['n_roles_verified']} / {tot['n_roles_required']}** (missing: {missing_txt})",
        f"- Verified `{_md_cell(stats['target_model'])}` run folders: **{tot['n_verified_carbon_runs']}** ({tot['n_canonical_runs']} canonical headline + {tot['n_supporting_runs']} supporting; scanned {prov['scanned_runs']} folders)",
        f"- Total verified episodes / samples: **{tot['count']:,}**",
        f"- Total Gemini API calls: **{tot['calls']:,}**",
        f"- Total tokens (in / out / thinking / cached): **{tot['tokens_in']:,} / {tot['tokens_out']:,} / {tot['thinking_tokens']:,} / {tot['cached_tokens']:,}**",
        f"- Total estimated API cost (USD): **${tot['cost_usd']:.4f}**",
        f"- Secret leaks detected: **{prov['secret_leaks_count']}**",
        "",
        "## 1. Canonical Headline Runs (One Labelled Real Run per Role)",
        "",
        "| Role | Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Headline Metric |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]

    for role in REQUIRED_ROLES:
        r_info = roles_map[role]
        canon = r_info["canonical_run"]
        if canon is None:
            lines.append(
                f"| `{_md_cell(role)}` | unverified | none | none | none | 0 | 0 | 0 | 0 | 0 | 0 | $0.0000 | unverified (0 verified carbon runs) |"
            )
        else:
            lines.append(
                f"| `{_md_cell(canon['role'])}` | `{_md_cell(canon['subrole'])}` | `{_md_cell(canon['run_folder'])}` | "
                f"`{_md_cell(canon['model_id'])}` | `{_md_cell(canon['commit'])}` | {canon['count']:,} | {canon['calls']:,} | "
                f"{canon['tokens_in']:,} | {canon['tokens_out']:,} | {canon['thinking_tokens']:,} | {canon['cached_tokens']:,} | "
                f"${canon['cost_usd']:.4f} | {_md_cell(canon['headline_metric'])} |"
            )

    lines.extend([
        "",
        "## 2. Role-by-Role Provenance & Supporting Runs",
    ])

    for role in REQUIRED_ROLES:
        r_info = roles_map[role]
        canon = r_info["canonical_run"]
        supporting = r_info["supporting_runs"]
        badge = "VERIFIED" if r_info["verified"] else "UNVERIFIED"
        lines.extend([
            "",
            f"### {r_info['index']}. `{_md_cell(role)}` - {_md_cell(r_info['title'])} ({badge})",
            "",
            f"- Stage: {_md_cell(r_info['stage'])}",
            f"- Verified `{_md_cell(stats['target_model'])}` runs: **{r_info['n_verified_runs']}** (count: {r_info['count']:,}, calls: {r_info['calls']:,}, in: {r_info['tokens_in']:,}, out: {r_info['tokens_out']:,}, thinking: {r_info['thinking_tokens']:,}, cached: {r_info['cached_tokens']:,}, cost: ${r_info['cost_usd']:.4f})",
        ])
        if canon is None:
            lines.append("- Canonical headline run: none")
            continue

        lines.append(
            f"- Canonical headline run: `{_md_cell(canon['run_folder'])}` (`{_md_cell(canon['subrole'])}`, commit `{_md_cell(canon['commit'])}`, count={canon['count']:,}, calls={canon['calls']:,}, cost=${canon['cost_usd']:.4f}) - {_md_cell(canon['headline_metric'])}"
        )
        if not supporting:
            lines.append("- Supporting verified runs: 0 (canonical run is the sole verified run folder for this role)")
        else:
            lines.extend([
                f"- Supporting verified runs: **{len(supporting)}**",
                "",
                "| Subrole | Run Folder | Model ID | Commit | Count | Calls | Tokens In | Tokens Out | Thinking | Cached | Cost (USD) | Headline Metric |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
            ])
            for sr in supporting:
                lines.append(
                    f"| `{_md_cell(sr['subrole'])}` | `{_md_cell(sr['run_folder'])}` | `{_md_cell(sr['model_id'])}` | "
                    f"`{_md_cell(sr['commit'])}` | {sr['count']:,} | {sr['calls']:,} | {sr['tokens_in']:,} | "
                    f"{sr['tokens_out']:,} | {sr['thinking_tokens']:,} | {sr['cached_tokens']:,} | "
                    f"${sr['cost_usd']:.4f} | {_md_cell(sr['headline_metric'])} |"
                )

    lines.extend([
        "",
        "## 3. Paired gemini-4-carbon vs SolverPolicy Comparison",
        "",
    ])
    if not paired["tiers"]:
        lines.append("No verified `gemini-4-carbon` investigator episodes paired with `SolverPolicy` are committed in this root yet.")
    else:
        lines.extend([
            "| Tier | Paired Seeds | gemini-4-carbon Mean | SolverPolicy Mean | Score / Solver | Paired Diff +/- 95% CI | Carbon Accuracy | Solver Accuracy | Mean Accuse Day (Carbon / Solver) |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        rows_to_render = list(paired["tiers"])
        if paired["overall"] and len(paired["tiers"]) > 1:
            rows_to_render.append(paired["overall"])
        for pr in rows_to_render:
            ratio_txt = f"{pr['ratio'] * 100.0:.1f}%" if pr["ratio"] is not None else "n/a"
            s_acc_txt = f"{pr['solver_accuracy'] * 100.0:.0f}%" if pr["solver_accuracy"] is not None else "n/a"
            c_day_txt = f"{pr['carbon_accuse_day']:.2f}" if pr["carbon_accuse_day"] is not None else "n/a"
            s_day_txt = f"{pr['solver_accuse_day']:.2f}" if pr["solver_accuse_day"] is not None else "n/a"
            lines.append(
                f"| {_md_cell(pr['tier'])} | {pr['n']} | {pr['carbon_mean']:+.4f} | {pr['solver_mean']:+.4f} | "
                f"{ratio_txt} | {pr['paired_diff']:+.4f} +/- {pr['diff_ci']:.4f} | "
                f"{pr['carbon_accuracy'] * 100.0:.0f}% | {s_acc_txt} | {c_day_txt} / {s_day_txt} |"
            )

        if paired["seeds"]:
            lines.extend([
                "",
                "### Per-Seed Paired Investigator Ledger",
                "",
                "| Tier | Seed | Run Folder | Carbon Score | Solver Score | Diff | Carbon Correct | Solver Correct | Accuse Day (Carbon / Solver) |",
                "| --- | ---: | --- | ---: | ---: | ---: | --- | --- | --- |",
            ])
            for sr in paired["seeds"]:
                c_ok = "yes" if sr["carbon_correct"] else "no"
                s_ok = "yes" if sr["solver_correct"] else ("no" if sr["solver_correct"] is False else "n/a")
                c_d = str(sr["carbon_day"]) if sr["carbon_day"] is not None else "n/a"
                s_d = str(sr["solver_day"]) if sr["solver_day"] is not None else "n/a"
                lines.append(
                    f"| {_md_cell(sr['tier'])} | {sr['seed']} | `{_md_cell(sr['run_folder'])}` | "
                    f"{sr['carbon_score']:+.4f} | {sr['solver_score']:+.4f} | {sr['diff']:+.4f} | "
                    f"{c_ok} | {s_ok} | {c_d} / {s_d} |"
                )

    lines.extend([
        "",
        "## 4. Multimodal Vision-vs-Blind Ablation Summary",
        "",
    ])
    if not mm["available"]:
        lines.append("No verified multimodal Vision-vs-Blind ablation runs are committed in this root yet.")
    else:
        lines.extend([
            "In-game leaked-memo pixel watermark ablation: text `variant` fields are redacted from `check_leak_feed`, requiring `gemini-4-carbon` to inspect rendered scan PNGs (`Part.from_bytes`) to identify canary copy-codes.",
            "",
            "| Run Folder | Subrole | Commit | Tier | Episodes | Images Read | Vision Acc | Multimodal Mean | Blind Mean | Vision Gain | Text Oracle Mean | Oracle Recovery | Multimodal Acc | Blind Acc |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ])
        for ar in mm["runs"]:
            v_acc = f"{ar['vision_accuracy'] * 100.0:.1f}%" if ar["vision_accuracy"] is not None else "n/a"
            orc_m = f"{ar['oracle_mean_score']:+.4f}" if ar["oracle_mean_score"] is not None else "n/a"
            rec_r = f"{ar['oracle_recovery_ratio'] * 100.0:.1f}%" if ar["oracle_recovery_ratio"] is not None else "n/a"
            mm_acc = f"{ar['multimodal_accuracy'] * 100.0:.0f}%" if ar["multimodal_accuracy"] is not None else "n/a"
            bl_acc = f"{ar['blind_accuracy'] * 100.0:.0f}%" if ar["blind_accuracy"] is not None else "n/a"
            lines.append(
                f"| `{_md_cell(ar['run_folder'])}` | `{_md_cell(ar['subrole'])}` | `{_md_cell(ar['commit'])}` | "
                f"{_md_cell(ar['tier'])} | {ar['n_episodes']} | {ar['n_images_read']} | {v_acc} | "
                f"{ar['multimodal_mean_score']:+.4f} | {ar['blind_mean_score']:+.4f} | {ar['vision_gain']:+.4f} | "
                f"{orc_m} | {rec_r} | {mm_acc} | {bl_acc} |"
            )

        pooled = mm["pooled_unique_seeds"]
        if pooled is not None:
            p_vacc = f"{pooled['vision_accuracy'] * 100.0:.1f}%" if pooled["vision_accuracy"] is not None else "n/a"
            p_rec = f"{pooled['oracle_recovery_ratio'] * 100.0:.1f}%" if pooled["oracle_recovery_ratio"] is not None else "n/a"
            tiers_joined = ", ".join(pooled["tiers"])
            lines.extend([
                "",
                f"- Pooled unique `(tier, seed)` ablation episodes: **{pooled['n_episodes']}** across tiers `{_md_cell(tiers_joined)}` ({pooled['n_images_read']} memo scans read, vision accuracy **{p_vacc}**, multimodal mean **{pooled['multimodal_mean_score']:+.4f}** vs blind **{pooled['blind_mean_score']:+.4f}**, gain **{pooled['vision_gain']:+.4f}**, oracle recovery **{p_rec}**).",
            ])

    if mm["soc_raster_runs"]:
        lines.extend([
            "",
            "### SOC Access-Log & Canary Matrix Raster Forensics",
            "",
            "| Run Folder | Subrole | Commit | Tier | Rasters Read | Top-1 Mole Acc | Top-1 Decoy Acc | Naive After-Hours Mole Acc |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ])
        for sr in mm["soc_raster_runs"]:
            m_acc = f"{sr['top1_mole_accuracy'] * 100.0:.0f}%"
            d_acc = f"{sr['top1_decoy_accuracy'] * 100.0:.0f}%" if sr["top1_decoy_accuracy"] is not None else "n/a"
            n_acc = (
                f"{sr['naive_baseline_mole_accuracy'] * 100.0:.0f}%"
                if sr["naive_baseline_mole_accuracy"] is not None
                else "n/a"
            )
            lines.append(
                f"| `{_md_cell(sr['run_folder'])}` | `{_md_cell(sr['subrole'])}` | `{_md_cell(sr['commit'])}` | "
                f"{_md_cell(sr['tier'])} | {sr['n_images_read']} | {m_acc} | {d_acc} | {n_acc} |"
            )

    lines.extend([
        "",
        "## 5. Aggregate Token & Cost Ledger by Role",
        "",
        "| Role | Verified Runs | Count | Calls | Tokens In | Tokens Out | Thinking Tokens | Cached Tokens | Cost (USD) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for role in REQUIRED_ROLES:
        rs = roles_map[role]
        lines.append(
            f"| `{_md_cell(role)}` | {rs['n_verified_runs']} | {rs['count']:,} | {rs['calls']:,} | "
            f"{rs['tokens_in']:,} | {rs['tokens_out']:,} | {rs['thinking_tokens']:,} | "
            f"{rs['cached_tokens']:,} | ${rs['cost_usd']:.4f} |"
        )
    lines.append(
        f"| **total** | **{tot['n_verified_carbon_runs']}** | **{tot['count']:,}** | **{tot['calls']:,}** | "
        f"**{tot['tokens_in']:,}** | **{tot['tokens_out']:,}** | **{tot['thinking_tokens']:,}** | "
        f"**{tot['cached_tokens']:,}** | **${tot['cost_usd']:.4f}** |"
    )

    lines.extend([
        "",
        "## 6. Keyless Offline Verification",
        "",
        "```bash",
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. python scripts/build_gemini_submission_stats.py --root . --out-md docs/gemini/ROLES_REPORT.md --out-json results/gemini_roles/submission_stats.json --strict",
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. python -m canary.gemini.provenance --root . --strict",
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. pytest -q tests/test_submission_stats.py tests/test_gemini_provenance.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def _resolve_output_path(root_path: Path, raw_out: str | Path) -> Path:
    out_p = Path(raw_out)
    if not out_p.is_absolute():
        out_p = root_path / out_p
    if out_p.name == "meta.json":
        raise ValueError("Summary output file must never be named meta.json")
    return out_p


def write_submission_outputs(
    root: str | Path = ".",
    out_md: str | Path = DEFAULT_OUT_MD,
    out_json: str | Path = DEFAULT_OUT_JSON,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    root_path = Path(root).resolve()
    md_path = _resolve_output_path(root_path, out_md)
    json_path = _resolve_output_path(root_path, out_json)

    stats = build_submission_stats(root_path)
    md_text = render_submission_report_md(stats)
    json_text = render_submission_stats_json(stats)

    md_errors = validate_report_text(md_text, root_path)
    json_errors = validate_report_text(json_text, root_path)
    stats["validation"] = {
        "md_valid": len(md_errors) == 0,
        "md_errors": md_errors,
        "json_valid": len(json_errors) == 0,
        "json_errors": json_errors,
    }
    json_text = render_submission_stats_json(stats)

    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json_text, encoding="utf-8")

    if strict:
        if not stats["totals"]["all_roles_verified"]:
            raise ValueError(
                f"Strict submission stats check failed: missing roles {stats['totals']['missing_roles']} "
                f"(secret_leaks={stats['provenance']['secret_leaks_count']})"
            )
        if md_errors or json_errors:
            raise ValueError(f"Strict report validation failed: md={md_errors}, json={json_errors}")

    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build 6-role Gemini submission stats JSON and docs/gemini/ROLES_REPORT.md."
    )
    ap.add_argument("--root", default=".", help="repository root directory")
    ap.add_argument("--out-md", default=DEFAULT_OUT_MD, help="output Markdown report path")
    ap.add_argument("--out-json", default=DEFAULT_OUT_JSON, help="output JSON stats path")
    ap.add_argument("--strict", action="store_true", help="exit non-zero if any role or report check fails")
    args = ap.parse_args(argv)

    root_path = Path(args.root).resolve()
    try:
        md_path = _resolve_output_path(root_path, args.out_md)
        json_path = _resolve_output_path(root_path, args.out_json)
        stats = write_submission_outputs(
            root=root_path,
            out_md=md_path,
            out_json=json_path,
            strict=False,
        )
    except ValueError as exc:
        sys.stderr.write(f"submission_stats error: {exc}\n")
        return 1

    tot = stats["totals"]
    val = stats["validation"]
    print(
        f"submission_stats: {tot['n_roles_verified']}/{tot['n_roles_required']} roles verified, "
        f"{tot['n_verified_carbon_runs']} carbon runs, "
        f"calls={tot['calls']}, in={tot['tokens_in']}, out={tot['tokens_out']}, "
        f"thinking={tot['thinking_tokens']}, cost=${tot['cost_usd']:.4f} -> "
        f"{md_path} & {json_path}"
    )

    if args.strict:
        if not tot["all_roles_verified"] or not val["md_valid"] or not val["json_valid"]:
            sys.stderr.write(
                f"strict check failed: verified_roles={tot['verified_roles']} "
                f"missing_roles={tot['missing_roles']} "
                f"md_errors={val['md_errors']} json_errors={val['json_errors']}\n"
            )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
