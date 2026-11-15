"""Offline integrity, calibration, fuzz and final n=13 verdict audit for origin/justSilas-expert (29ca3bc5).

Supports two execution modes with zero live LLM calls:
  1. --expert-root <path>: audits a checked-out justSilas-expert@29ca3bc5 worktree against justSilas
  2. --self-test: standalone keyless verification on justSilas using embedded 29ca3bc5
     verdict snapshots, paired solver snapshots, compatibility probes, and an isolated
     in-memory expert tier fixture
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import random
import re
import statistics
import subprocess
import sys
import threading
import time
from dataclasses import asdict, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERDICT_SNAPSHOT_29CA3BC5: dict[str, Any] = {
    "tier": "expert",
    "n": 13,
    "seeds": [60001, 60002, 60003, 60004, 60005, 60010, 60011, 60012, 60013, 60015, 60016, 60019, 60020],
    "gemini_mean": 0.5307692307692308,
    "solver_mean_same_seeds": 0.29615384615384616,
    "ratio": 1.7922077922077921,
    "ratio_ci": [0.9174041297935104, 12.54385964912281],
    "luck_adj_gemini": 0.37269230769230766,
    "luck_adj_solver": 0.44133384615384585,
    "luck_adj_ratio": 0.844467993878697,
    "luck_adj_ratio_ci": [0.5239194815717949, 1.2778488323206225],
    "gemini": {
        "accused_rate": 1.0,
        "accuracy_among_accused": 1.0,
        "mean_P_at_accusation": 0.8996923076923077,
        "below_break_even": 0,
        "single_canary_hit_accusations": 2,
        "n_accused": 13,
    },
    "solver": {
        "accused_rate": 0.9230769230769231,
        "accuracy_among_accused": 0.8333333333333334,
        "mean_P_at_accusation": 0.9485,
        "below_break_even": 0,
        "single_canary_hit_accusations": 4,
        "n_accused": 12,
    },
    "per_seed": [
        {"seed": 60001, "gemini": 0.46, "gemini_correct": True, "solver": -1.0, "gemini_P": 0.995, "gemini_single_canary_hit": False},
        {"seed": 60002, "gemini": 0.42, "gemini_correct": True, "solver": 0.66, "gemini_P": 0.97, "gemini_single_canary_hit": True},
        {"seed": 60003, "gemini": 0.47, "gemini_correct": True, "solver": 0.58, "gemini_P": 0.645, "gemini_single_canary_hit": False},
        {"seed": 60004, "gemini": 0.69, "gemini_correct": True, "solver": 0.6, "gemini_P": 0.965, "gemini_single_canary_hit": False},
        {"seed": 60005, "gemini": 0.44, "gemini_correct": True, "solver": 0.39, "gemini_P": 0.982, "gemini_single_canary_hit": False},
        {"seed": 60010, "gemini": 0.41, "gemini_correct": True, "solver": -1.0, "gemini_P": 1.0, "gemini_single_canary_hit": False},
        {"seed": 60011, "gemini": 0.59, "gemini_correct": True, "solver": 0.69, "gemini_P": 0.97, "gemini_single_canary_hit": False},
        {"seed": 60012, "gemini": 0.59, "gemini_correct": True, "solver": 0.44, "gemini_P": 0.586, "gemini_single_canary_hit": False},
        {"seed": 60013, "gemini": 0.66, "gemini_correct": True, "solver": 0.0, "gemini_P": 1.0, "gemini_single_canary_hit": True},
        {"seed": 60015, "gemini": 0.41, "gemini_correct": True, "solver": 0.78, "gemini_P": 1.0, "gemini_single_canary_hit": False},
        {"seed": 60016, "gemini": 0.58, "gemini_correct": True, "solver": 0.61, "gemini_P": 1.0, "gemini_single_canary_hit": False},
        {"seed": 60019, "gemini": 0.66, "gemini_correct": True, "solver": 0.32, "gemini_P": 0.583, "gemini_single_canary_hit": False},
        {"seed": 60020, "gemini": 0.52, "gemini_correct": True, "solver": 0.78, "gemini_P": 1.0, "gemini_single_canary_hit": False},
    ],
}

PAIRED_SOLVER_SNAPSHOT_29CA3BC5: dict[int, dict[str, Any]] = {
    60001: {"score": -1.0, "accused": True, "correct": False, "p_accused": 0.971, "V": 0.5099999999999996, "luck_adj": 0.4662099999999995, "single_canary_hit": False},
    60002: {"score": 0.66, "accused": True, "correct": True, "p_accused": 1.0, "V": 0.6599999999999997, "luck_adj": 0.6599999999999997, "single_canary_hit": True},
    60003: {"score": 0.58, "accused": True, "correct": True, "p_accused": 0.943, "V": 0.5799999999999996, "luck_adj": 0.4899399999999996, "single_canary_hit": False},
    60004: {"score": 0.6, "accused": True, "correct": True, "p_accused": 1.0, "V": 0.5999999999999996, "luck_adj": 0.5999999999999996, "single_canary_hit": False},
    60005: {"score": 0.39, "accused": True, "correct": True, "p_accused": 0.917, "V": 0.38999999999999957, "luck_adj": 0.27462999999999965, "single_canary_hit": False},
    60010: {"score": -1.0, "accused": True, "correct": False, "p_accused": 0.906, "V": 0.32999999999999957, "luck_adj": 0.20497999999999966, "single_canary_hit": False},
    60011: {"score": 0.69, "accused": True, "correct": True, "p_accused": 1.0, "V": 0.6899999999999997, "luck_adj": 0.6899999999999997, "single_canary_hit": True},
    60012: {"score": 0.44, "accused": True, "correct": True, "p_accused": 0.947, "V": 0.4399999999999996, "luck_adj": 0.36367999999999956, "single_canary_hit": False},
    60013: {"score": 0.0, "accused": False, "correct": False, "p_accused": None, "V": 0.0, "luck_adj": 0.0, "single_canary_hit": None},
    60015: {"score": 0.78, "accused": True, "correct": True, "p_accused": 0.909, "V": 0.7799999999999998, "luck_adj": 0.6180199999999999, "single_canary_hit": True},
    60016: {"score": 0.61, "accused": True, "correct": True, "p_accused": 0.924, "V": 0.6099999999999997, "luck_adj": 0.48763999999999974, "single_canary_hit": False},
    60019: {"score": 0.32, "accused": True, "correct": True, "p_accused": 0.951, "V": 0.3199999999999996, "luck_adj": 0.2553199999999996, "single_canary_hit": False},
    60020: {"score": 0.78, "accused": True, "correct": True, "p_accused": 0.914, "V": 0.7799999999999998, "luck_adj": 0.6269199999999999, "single_canary_hit": True},
}

WORLD_PIN_SEEDS = (0, 1, 7, 4000)
WORLD_PIN_TIERS = ("easy", "medium", "hard", "hard_forge", "hard_rl")


def parse_seeds(spec: str) -> list[int]:
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
    return out


def ci95(xs: list[float]) -> float:
    return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def boot_ratio(f: list[float], s: list[float], resamples: int = 10000, rng_seed: int = 0) -> tuple[float, float]:
    rng = random.Random(rng_seed)
    n = len(f)
    vals: list[float] = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        ms = sum(s[i] for i in idx) / n
        if ms > 0:
            vals.append((sum(f[i] for i in idx) / n) / ms)
    if not vals:
        return (float("nan"), float("nan"))
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1])


def compute_world_digests() -> dict[str, dict[str, Any]]:
    from canary.rules import tier_params
    from canary.world import generate_world

    out: dict[str, dict[str, Any]] = {}
    for tier in WORLD_PIN_TIERS:
        for seed in WORLD_PIN_SEEDS:
            w = generate_world(tier, seed, tier_params(tier))
            d = asdict(w) if is_dataclass(w) else dict(w.__dict__)
            digest = hashlib.sha256(json.dumps(d, sort_keys=True, default=repr).encode()).hexdigest()[:16]
            out[f"{tier}:{seed}"] = {
                "digest": digest,
                "n_depts": len(w.depts),
                "depts": list(w.depts),
                "mole": w.mole,
                "decoy": w.decoy,
            }
    return out


def check_gap_md_expert_entry(gap_md_path: Path | None = None) -> dict[str, Any]:
    path = gap_md_path if gap_md_path is not None else (ROOT / "docs" / "reports" / "gap.md")
    if not path.exists():
        return {"exists": False, "ok": False}
    text = path.read_text(encoding="utf-8")
    has_sha = "29ca3bc5" in text
    has_n13 = "n=13" in text
    has_ratio = "84% [52%, 128%]" in text
    has_file = "results/expert_verdict.json" in text
    has_fa = "0.70" in text
    return {
        "exists": True,
        "has_29ca3bc5": has_sha,
        "has_n13": has_n13,
        "has_84_ci_52_128": has_ratio,
        "has_expert_verdict_json": has_file,
        "has_fa_070": has_fa,
        "ok": bool(has_sha and has_n13 and has_ratio and has_file and has_fa),
    }


def audit_verdict_payload(verdict: dict[str, Any], solver_runs: dict[int, dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = list(verdict.get("per_seed") or [])
    seeds = [int(r["seed"]) for r in rows]
    n = len(rows)
    score_violations: list[dict[str, Any]] = []
    gem_scores: list[float] = []
    sol_scores: list[float] = []
    gem_luck: list[float] = []
    gem_ps: list[float] = []
    gem_sch_seeds: list[int] = []
    true_below_break_even_seeds: list[int] = []
    per_seed_ev: list[dict[str, Any]] = []

    for r in rows:
        seed = int(r["seed"])
        gs = float(r["gemini"])
        ss = float(r["solver"])
        gc = bool(r["gemini_correct"])
        gp = r.get("gemini_P")
        gem_scores.append(gs)
        sol_scores.append(ss)

        if not (gs == 0.0 or abs(gs + 1.0) < 1e-9 or 0.0 < gs <= 1.0 + 1e-9):
            score_violations.append({"seed": seed, "party": "gemini", "kind": "score_out_of_range", "score": gs})
        if abs(round(gs * 100.0) - gs * 100.0) > 1e-6:
            score_violations.append({"seed": seed, "party": "gemini", "kind": "non_cent_grid_score", "score": gs})
        if not (ss == 0.0 or abs(ss + 1.0) < 1e-9 or 0.0 < ss <= 1.0 + 1e-9):
            score_violations.append({"seed": seed, "party": "solver", "kind": "score_out_of_range", "score": ss})
        if gc and not (0.0 < gs <= 1.0 + 1e-9):
            score_violations.append({"seed": seed, "party": "gemini", "kind": "correct_score_sign", "score": gs})
        if (not gc) and gs > 0.0:
            score_violations.append({"seed": seed, "party": "gemini", "kind": "wrong_positive_score", "score": gs})
        if gp is None or not (0.0 <= float(gp) <= 1.0 + 1e-9):
            score_violations.append({"seed": seed, "party": "gemini", "kind": "invalid_posterior", "p": gp})
        if r.get("gemini_single_canary_hit"):
            gem_sch_seeds.append(seed)

        if gc and gp is not None:
            v_true = gs
            p_val = float(gp)
            gem_ps.append(p_val)
            ev = p_val * v_true - (1.0 - p_val)
            be = 1.0 / (1.0 + v_true)
            gem_luck.append(ev)
            below = p_val < be - 1e-12
            if below:
                true_below_break_even_seeds.append(seed)
            per_seed_ev.append({
                "seed": seed,
                "score": gs,
                "V_at_accusation": v_true,
                "P": p_val,
                "break_even_P": round(be, 6),
                "luck_adjusted_ev": round(ev, 6),
                "below_break_even": below,
                "single_canary_hit": bool(r.get("gemini_single_canary_hit")),
            })

    gem_mean = sum(gem_scores) / n if n else 0.0
    sol_mean = sum(sol_scores) / n if n else 0.0
    raw_ratio = (gem_mean / sol_mean) if sol_mean else float("nan")
    raw_lo, raw_hi = boot_ratio(gem_scores, sol_scores) if n > 1 else (float("nan"), float("nan"))
    luck_gem_mean = sum(gem_luck) / len(gem_luck) if gem_luck else float("nan")
    mean_gem_p = sum(gem_ps) / len(gem_ps) if gem_ps else float("nan")

    seed_lo_0 = 60000
    seed_hi = max(seeds) if seeds else 60020
    missing_from_60000 = [s for s in range(seed_lo_0, seed_hi + 1) if s not in set(seeds)]
    missing_internal = [s for s in range(min(seeds), seed_hi + 1) if s not in set(seeds)] if seeds else []

    gem_hdr = verdict.get("gemini") or {}
    reported_bbe = int(gem_hdr.get("below_break_even", 0))
    n_accused = int(gem_hdr.get("n_accused", 0))
    correct_count = sum(1 for r in rows if r.get("gemini_correct"))
    zero_timeout_or_error_in_valid = (n_accused == n and correct_count == n)

    luck_ratio_val = float(verdict.get("luck_adj_ratio", float("nan")))
    luck_ci_val = list(verdict.get("luck_adj_ratio_ci") or [float("nan"), float("nan")])
    formatted_luck_headline = f"{round(luck_ratio_val * 100):.0f}% [{round(luck_ci_val[0] * 100):.0f}%, {round(luck_ci_val[1] * 100):.0f}%]"

    solver_match = None
    if solver_runs is not None:
        mismatches = []
        sol_luck_list: list[float] = []
        sol_sch = 0
        sol_acc_count = 0
        sol_corr_count = 0
        sol_ps: list[float] = []
        sol_bbe = 0
        for r in rows:
            s = int(r["seed"])
            sr = solver_runs[s]
            if abs(float(sr["score"]) - float(r["solver"])) > 1e-9:
                mismatches.append({"seed": s, "recorded": r["solver"], "replayed": sr["score"]})
            sol_luck_list.append(float(sr["luck_adj"]))
            if sr.get("accused"):
                sol_acc_count += 1
                if sr.get("correct"):
                    sol_corr_count += 1
                if sr.get("p_accused") is not None:
                    sol_ps.append(float(sr["p_accused"]))
                    if sr.get("V") is not None and float(sr["p_accused"]) < 1.0 / (1.0 + float(sr["V"])):
                        sol_bbe += 1
            if sr.get("single_canary_hit"):
                sol_sch += 1
        sol_luck_mean = sum(sol_luck_list) / len(sol_luck_list)
        luck_ratio = luck_gem_mean / sol_luck_mean
        luck_lo, luck_hi = boot_ratio(gem_luck, sol_luck_list)
        sol_hdr = verdict.get("solver") or {}
        solver_match = {
            "score_mismatches": mismatches,
            "recomputed_luck_adj_solver": sol_luck_mean,
            "luck_adj_solver_diff": abs(sol_luck_mean - float(verdict["luck_adj_solver"])),
            "recomputed_luck_adj_ratio": luck_ratio,
            "luck_adj_ratio_diff": abs(luck_ratio - float(verdict["luck_adj_ratio"])),
            "recomputed_luck_adj_ci": [luck_lo, luck_hi],
            "luck_adj_ci_diff": [
                abs(luck_lo - float(verdict["luck_adj_ratio_ci"][0])),
                abs(luck_hi - float(verdict["luck_adj_ratio_ci"][1])),
            ],
            "recomputed_solver_accused": sol_acc_count,
            "recomputed_solver_correct": sol_corr_count,
            "recomputed_solver_mean_P": sum(sol_ps) / len(sol_ps) if sol_ps else None,
            "solver_mean_P_diff": abs((sum(sol_ps) / len(sol_ps)) - float(sol_hdr["mean_P_at_accusation"])) if sol_ps else None,
            "recomputed_solver_single_canary_hits": sol_sch,
            "recomputed_solver_below_break_even": sol_bbe,
        }

    ship_bar_reasons: list[str] = []
    if n < 30:
        ship_bar_reasons.append(f"sample_size_below_30 (n={n} < 30 required by PLAN-95 Track 2)")
    if len(luck_ci_val) == 2 and float(luck_ci_val[1]) >= 1.0:
        ship_bar_reasons.append(
            f"luck_adjusted_ci_includes_parity ({luck_ratio_val:.3f} "
            f"[{float(luck_ci_val[0]):.3f}, {float(luck_ci_val[1]):.3f}] includes 1.00)"
        )
    if luck_ratio_val > 0.72:
        ship_bar_reasons.append(
            f"did_not_widen_v14_hard_gap (expert luck_adj_ratio {luck_ratio_val:.1%} "
            f"vs v1.4 hard 72% [52%, 91%]; {correct_count}/{n} correct)"
        )

    return {
        "n": n,
        "seeds": seeds,
        "correct_count": correct_count,
        "n_accused": n_accused,
        "zero_timeout_or_error_in_valid": zero_timeout_or_error_in_valid,
        "score_invariant_violations": score_violations,
        "recomputed_gemini_mean": gem_mean,
        "gemini_mean_diff": abs(gem_mean - float(verdict["gemini_mean"])),
        "recomputed_solver_mean": sol_mean,
        "solver_mean_diff": abs(sol_mean - float(verdict["solver_mean_same_seeds"])),
        "recomputed_raw_ratio": raw_ratio,
        "raw_ratio_diff": abs(raw_ratio - float(verdict["ratio"])),
        "recomputed_raw_ratio_ci": [raw_lo, raw_hi],
        "raw_ratio_ci_diff": [
            abs(raw_lo - float(verdict["ratio_ci"][0])),
            abs(raw_hi - float(verdict["ratio_ci"][1])),
        ],
        "recomputed_luck_adj_gemini": luck_gem_mean,
        "luck_adj_gemini_diff": abs(luck_gem_mean - float(verdict["luck_adj_gemini"])),
        "recomputed_mean_gemini_P": mean_gem_p,
        "mean_gemini_P_diff": abs(mean_gem_p - float(gem_hdr["mean_P_at_accusation"])),
        "gemini_single_canary_hit_seeds": gem_sch_seeds,
        "formatted_luck_headline": formatted_luck_headline,
        "matches_gap_md_84_52_128": formatted_luck_headline == "84% [52%, 128%]",
        "reported_gemini_below_break_even": reported_bbe,
        "true_gemini_below_break_even": len(true_below_break_even_seeds),
        "true_below_break_even_seeds": true_below_break_even_seeds,
        "below_break_even_bug_confirmed": reported_bbe != len(true_below_break_even_seeds),
        "missing_seeds_60000_60020": missing_from_60000,
        "missing_seeds_internal_60001_60020": missing_internal,
        "per_seed_ev": per_seed_ev,
        "solver_verification": solver_match,
        "fails_ship_bar": bool(ship_bar_reasons),
        "ship_bar_reasons": ship_bar_reasons,
    }


def audit_verdict_filter_semantics(episodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    if episodes is None:
        episodes = [
            {
                "tier": "expert",
                "seed": 60012,
                "agent": "opencode:google/gemini-4-carbon",
                "score": 0.59,
                "accused": "e04",
                "correct": True,
                "final_day": 11,
                "end_reason": "accused",
                "p_stub": 0.586,
                "meta": {"rc": 0, "V_final": 0.59},
            },
            {
                "tier": "expert",
                "seed": 60006,
                "agent": "opencode:google/gemini-4-carbon",
                "score": 0.0,
                "accused": None,
                "correct": False,
                "final_day": 0,
                "end_reason": "error",
                "p_stub": None,
                "meta": {"rc": 0, "V_final": None, "note": "agent stopped without ending the episode (no accusation)"},
            },
            {
                "tier": "expert",
                "seed": 60007,
                "agent": "opencode:google/gemini-4-carbon",
                "score": 0.0,
                "accused": None,
                "correct": False,
                "final_day": 0,
                "end_reason": "error",
                "p_stub": None,
                "meta": {"rc": "timeout", "V_final": None, "note": "agent stopped without ending the episode (no accusation)"},
            },
            {
                "tier": "expert",
                "seed": 60008,
                "agent": "opencode:google/gemini-4-carbon",
                "score": 0.0,
                "accused": None,
                "correct": False,
                "final_day": 0,
                "end_reason": "error",
                "p_stub": None,
                "meta": {"rc": 1, "error": "infra:provider_unavailable", "valid": False},
            },
        ]

    expert_verdict_kept = [
        e["seed"] for e in episodes
        if e.get("tier") == "expert"
        and (e.get("meta") or {}).get("valid") is not False
        and e.get("end_reason") != "error"
    ]
    canonical_kept = [
        e["seed"] for e in episodes
        if e.get("tier") == "expert"
        and (e.get("meta") or {}).get("valid") is not False
        and not str((e.get("meta") or {}).get("error") or "").startswith("infra:")
    ]
    silently_dropped_played_seeds = [s for s in canonical_kept if s not in set(expert_verdict_kept)]

    expert_verdict_bbe = 0
    canonical_bbe = 0
    for e in episodes:
        if e.get("end_reason") != "accused":
            continue
        p_val = e.get("p_stub")
        meta = e.get("meta") or {}
        if p_val is not None and meta.get("V") is not None:
            if float(p_val) < 1.0 / (1.0 + float(meta["V"])):
                expert_verdict_bbe += 1
        v_canon = meta.get("V", meta.get("V_final"))
        if p_val is not None and v_canon is not None:
            if float(p_val) < 1.0 / (1.0 + float(v_canon)):
                canonical_bbe += 1

    return {
        "expert_verdict_kept_seeds": expert_verdict_kept,
        "canonical_kept_seeds": canonical_kept,
        "silently_dropped_played_seeds": silently_dropped_played_seeds,
        "drops_unaccused_timeouts_and_abstentions": bool(silently_dropped_played_seeds),
        "expert_verdict_below_break_even": expert_verdict_bbe,
        "canonical_below_break_even": canonical_bbe,
        "meta_v_key_mismatch_confirmed": expert_verdict_bbe != canonical_bbe,
    }


def _expected_known_v(env: Any) -> float:
    surfaced = sum(1 for f in env._feed if f["surfaced_day"] <= env.day)
    return round(max(0.0, 1.0 - env.p.leak_damage * surfaced - env._costs), 10)


def run_v_and_known_v_audit(seeds: list[int], env_factory: Any) -> dict[str, Any]:
    true_rises = 0
    known_rises = 0
    formula_mismatches = 0
    hidden_leak_states = 0
    hidden_leak_exposures = 0
    steps_checked = 0
    score_uses_true_v_verified = False

    for seed in seeds:
        env = env_factory(seed)
        rng = random.Random(seed ^ 0x5A17)
        prev_true = 1.0
        prev_known = 1.0
        while not env.done:
            roll = rng.random()
            if roll < 0.20:
                emp = f"e{rng.randrange(env.p.n_employees):02d}"
                env.call("restrict_access", {"employee": emp})
            elif roll < 0.30:
                emp = f"e{rng.randrange(env.p.n_employees):02d}"
                env.call("unrestrict_access", {"employee": emp})
            elif roll < 0.50:
                emps = rng.sample([f"e{i:02d}" for i in range(env.p.n_employees)], 3)
                env.call("plant_canary", {"doc_title": f"Trap {env.day}", "assignment": {emps[0]: "A", emps[1]: "B", emps[2]: "C"}})
            elif roll < 0.65:
                env.call("check_leak_feed", {})

            st = env.call("status", {})
            if not st.ok or env.done:
                break
            steps_checked += 1
            kv = float(st.data["V"])
            tv = float(env.V)
            exp_kv = _expected_known_v(env)
            if tv > prev_true + 1e-12:
                true_rises += 1
            if kv > prev_known + 1e-12:
                known_rises += 1
            if abs(kv - exp_kv) > 1e-9:
                formula_mismatches += 1
            prev_true, prev_known = tv, kv

            has_unsurfaced = any(f["surfaced_day"] > env.day for f in env._feed)
            if has_unsurfaced:
                hidden_leak_states += 1
                if not (kv > round(tv, 10) or kv == 0.0):
                    hidden_leak_exposures += 1
                if not score_uses_true_v_verified and kv > round(tv, 10):
                    probe_env = env_factory(seed)
                    probe_rng = random.Random(seed ^ 0x5A17)
                    while not probe_env.done and probe_env.day < env.day:
                        r2 = probe_rng.random()
                        if r2 < 0.20:
                            probe_env.call("restrict_access", {"employee": f"e{probe_rng.randrange(probe_env.p.n_employees):02d}"})
                        elif r2 < 0.30:
                            probe_env.call("unrestrict_access", {"employee": f"e{probe_rng.randrange(probe_env.p.n_employees):02d}"})
                        elif r2 < 0.50:
                            es2 = probe_rng.sample([f"e{i:02d}" for i in range(probe_env.p.n_employees)], 3)
                            probe_env.call("plant_canary", {"doc_title": f"Trap {probe_env.day}", "assignment": {es2[0]: "A", es2[1]: "B", es2[2]: "C"}})
                        elif r2 < 0.65:
                            probe_env.call("check_leak_feed", {})
                        probe_env.call("status", {})
                        probe_env.call("advance_day", {})
                    if not probe_env.done and any(f["surfaced_day"] > probe_env.day for f in probe_env._feed):
                        shown_now = float(probe_env.call("status", {}).data["V"])
                        true_now = round(probe_env.V, 10)
                        if shown_now > true_now:
                            probe_env.call("accuse", {"employee": probe_env._world.mole})
                            if probe_env.score() == true_now and probe_env.score() < shown_now:
                                score_uses_true_v_verified = True

            adv = env.call("advance_day", {})
            if adv.ok and "V" in adv.data and not env.done:
                steps_checked += 1
                akv = float(adv.data["V"])
                atv = float(env.V)
                aexp = _expected_known_v(env)
                if atv > prev_true + 1e-12:
                    true_rises += 1
                if akv > prev_known + 1e-12:
                    known_rises += 1
                if abs(akv - aexp) > 1e-9:
                    formula_mismatches += 1
                prev_true, prev_known = atv, akv
                if any(f["surfaced_day"] > env.day for f in env._feed):
                    hidden_leak_states += 1
                    if not (akv > round(atv, 10) or akv == 0.0):
                        hidden_leak_exposures += 1

    return {
        "n_seeds": len(seeds),
        "steps_checked": steps_checked,
        "true_v_rises": true_rises,
        "known_v_rises": known_rises,
        "known_v_formula_mismatches": formula_mismatches,
        "hidden_leak_states": hidden_leak_states,
        "hidden_leak_exposures": hidden_leak_exposures,
        "score_uses_true_v_verified": score_uses_true_v_verified,
        "all_ok": (
            true_rises == 0
            and known_rises == 0
            and formula_mismatches == 0
            and hidden_leak_states > 0
            and hidden_leak_exposures == 0
            and score_uses_true_v_verified
        ),
    }


class SwarmW2b008Probe:
    name = "swarm_w2b008"

    def __init__(self, seed: int = 0):
        self.seed = seed

    def reset(self, tools_spec: Any, instruction: str) -> None:
        from canary.baselines import _params_from_instruction

        p = _params_from_instruction(instruction)
        self.max_variants = int(p.get("max_variants", 3))
        self.cpd = int(p.get("canaries_per_day", 1))
        self.done_today: set[tuple[int, str]] = set()
        self.docs: dict[str, dict[str, Any]] = {}
        self.suspects: set[str] | None = None
        self.used_leaks: set[str] = set()
        self.decoy_checked = False
        self.n_canaries = 0

    @staticmethod
    def _last(history: list[Any], tool: str) -> dict[str, Any] | None:
        for s in reversed(history):
            if s.tool == tool:
                return s.result.get("data") if s.result.get("ok") else None
        return None

    def _once(self, day: int, tag: str) -> bool:
        if (day, tag) in self.done_today:
            return False
        self.done_today.add((day, tag))
        return True

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        from canary.baselines import employee_ids

        if self.suspects is None:
            for s in history:
                if s.tool == "list_employees" and s.result.get("ok"):
                    self.suspects = set(employee_ids(s.result))
            if self.suspects is None:
                return ("list_employees", {})
        day = history[-1].day if history else 1
        if history[-1].tool == "advance_day" and history[-1].result.get("ok"):
            day = history[-1].result["data"]["day"]
        if self._once(day, "docs"):
            return ("list_documents", {})
        for doc in (self._last(history, "list_documents") or {}).get("documents", []):
            self.docs[doc["doc_id"]] = doc
        if day >= 2 and not self.decoy_checked:
            self.decoy_checked = True
            return ("search_messages", {"query": "CV"})
        if history[-1].tool == "search_messages":
            senders = {m.get("sender") for m in (history[-1].result.get("data") or {}).get("messages", [])}
            if len(senders) == 1 and len(self.suspects) > 1:
                self.suspects -= senders
        if day >= 2 and self._once(day, "feed"):
            return ("check_leak_feed", {})
        for it in (self._last(history, "check_leak_feed") or {}).get("items", []):
            key = f"{it.get('doc_id')}:{it.get('variant')}"
            doc = self.docs.get(it.get("doc_id"))
            if key in self.used_leaks or not doc:
                continue
            self.used_leaks.add(key)
            if doc.get("is_canary") and it.get("variant") and doc.get("variants"):
                grp = set(doc["variants"].get(it["variant"], []))
            else:
                grp = set(doc.get("recipients", []))
            if self.suspects & grp:
                self.suspects &= grp
        if len(self.suspects) == 1:
            return ("accuse", {"employee": next(iter(self.suspects))})
        ranked = sorted(self.suspects)
        for k in range(self.cpd):
            if len(ranked) < 2:
                break
            if not self._once(day, f"canary{k}"):
                continue
            if len(ranked) <= self.max_variants:
                pick = ranked
                assign = {e: "ABC"[i] for i, e in enumerate(pick)}
            else:
                size = min(len(ranked), 6 if self.n_canaries == 0 else 2 * self.max_variants)
                off = (day * size + k * size) % len(ranked)
                pick = (ranked[off:] + ranked[:off])[:size]
                assign = {e: "ABC"[i % self.max_variants] for i, e in enumerate(pick)}
            self.n_canaries += 1
            return ("plant_canary", {"doc_title": f"Targeted Memo {day}-{k}", "assignment": assign})
        return ("advance_day", {})


def run_baselines_and_ladder(
    seeds: list[int],
    env_factory: Any,
    policy_names: tuple[str, ...] = (
        "do_nothing",
        "stop_early",
        "guess_day1",
        "restrict_all",
        "logs_only",
        "accuse_decoy",
        "accuse_most_logs",
        "heuristic",
        "grok_tactics",
        "swarm_w2b008",
        "solver",
    ),
) -> dict[str, Any]:
    import logging

    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    from canary.baselines import BASELINES, CALIBRATION_POLICIES
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    stats: dict[str, Any] = {}
    for name in policy_names:
        scores: list[float] = []
        accused_count = 0
        correct_count = 0
        for s in seeds:
            if name == "solver":
                pol = SolverPolicy(None)
            elif name == "swarm_w2b008":
                pol = SwarmW2b008Probe(seed=s)
            else:
                cls = BASELINES.get(name) or CALIBRATION_POLICIES[name]
                pol = cls(seed=s)
            ep = run_episode(env_factory(s), pol)
            scores.append(float(ep.score))
            if ep.end_reason == "accused":
                accused_count += 1
            if ep.correct:
                correct_count += 1
        stats[name] = {
            "n": len(seeds),
            "mean": round(statistics.mean(scores), 4),
            "ci95": round(ci95(scores), 4),
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
            "episodes_gt_0": sum(1 for x in scores if x > 0.0),
            "accused_rate": round(accused_count / len(seeds), 4),
            "accuracy_overall": round(correct_count / len(seeds), 4),
            "accuracy_among_accused": round(correct_count / accused_count, 4) if accused_count else None,
        }

    checks: dict[str, bool] = {}
    if "do_nothing" in stats:
        checks["do_nothing_exact_zero"] = stats["do_nothing"]["min"] == 0.0 and stats["do_nothing"]["max"] == 0.0
    if "stop_early" in stats:
        checks["stop_early_exact_zero"] = stats["stop_early"]["min"] == 0.0 and stats["stop_early"]["max"] == 0.0
    if "guess_day1" in stats:
        checks["guess_day1_negative"] = stats["guess_day1"]["mean"] < 0.0
    if "restrict_all" in stats:
        checks["restrict_all_negative"] = stats["restrict_all"]["mean"] < 0.0
    if "solver" in stats:
        non_solver = [k for k in stats if k != "solver"]
        if non_solver:
            checks["all_baselines_strictly_below_solver"] = all(
                stats[k]["mean"] < stats["solver"]["mean"] for k in non_solver
            )
    if {"heuristic", "grok_tactics", "solver"} <= set(stats):
        checks["monotone_heuristic_lt_grok_lt_solver"] = (
            stats["heuristic"]["mean"] < stats["grok_tactics"]["mean"] < stats["solver"]["mean"]
        )
    if {"swarm_w2b008", "solver"} <= set(stats):
        checks["swarm_w2b008_below_solver"] = stats["swarm_w2b008"]["mean"] < stats["solver"]["mean"]

    return {"policies": stats, "checks": checks, "all_checks_pass": all(checks.values())}


def _single_canary_hit_steps(steps: list[Any]) -> bool | None:
    acc = next((s for s in reversed(steps) if s.tool == "accuse"), None)
    if acc is None:
        return None
    who = (acc.args or {}).get("employee")
    docs: dict[str, Any] = {}
    hits: set[tuple[str, str]] = set()
    for s in steps:
        res = s.result or {}
        if not res.get("ok"):
            continue
        data = res.get("data") or {}
        if s.tool == "list_documents":
            for d in data.get("documents", []):
                docs[d.get("doc_id")] = d
        elif s.tool == "plant_canary":
            did = data.get("doc_id")
            asg = (s.args or {}).get("assignment") or {}
            if did:
                groups: dict[str, list[str]] = {}
                for emp, lab in asg.items():
                    groups.setdefault(lab, []).append(emp)
                docs[did] = {"doc_id": did, "variants": groups}
        elif s.tool == "check_leak_feed":
            for it in data.get("items", []):
                lab, did = it.get("variant"), it.get("doc_id")
                if lab and did in docs and who in (docs[did].get("variants") or {}).get(lab, []):
                    hits.add((did, lab))
        if s is acc:
            break
    return len(hits) == 1


def audit_justsilas_integration_compat() -> dict[str, Any]:
    from canary import rules
    from canary.env import Env
    from canary.solver import params as solver_params
    from canary.solver.policy import SolverPolicy, tier_from_instruction

    digests = compute_world_digests()
    hard_rl_depts = sorted({digests[f"hard_rl:{s}"]["n_depts"] for s in WORLD_PIN_SEEDS})

    harbor_proc = subprocess.run(
        [sys.executable, str(ROOT / "harbor" / "build.py"), "--tiers", "expert", "--seeds", "900000"],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
    )

    solver_str_err = None
    try:
        SolverPolicy("expert")
    except Exception as exc:
        solver_str_err = f"{type(exc).__name__}: {exc}"

    hard_ins = Env("hard", 0).instruction()
    expert_ins_sim = re.sub(r"^- name: hard$", "- name: expert", hard_ins, flags=re.M)
    expert_ins_sim = re.sub(r"^- fingerprint_accuracy: .*$", "- fingerprint_accuracy: 0.7", expert_ins_sim, flags=re.M)
    expert_ins_sim = expert_ins_sim.replace("(hard tier)", "(expert tier)").replace("Tier: hard", "Tier: expert")

    exact_block = solver_params._from_exact_block(expert_ins_sim)
    param_block = solver_params._from_param_block(expert_ins_sim)
    full_parsed = solver_params.params_from_instruction(expert_ins_sim)
    prose_hdr = f"{chr(35)} Canary: catch the mole (expert tier)\nTier: expert\ncompany with 40 employees"
    prose_only = solver_params._params_from_prose(prose_hdr)
    t_from_ins = tier_from_instruction(expert_ins_sim)

    sp_none = SolverPolicy(None)
    sp_none.reset([], expert_ins_sim)
    default_thr_expert = sp_none.default_threshold() if sp_none.P is not None else None

    return {
        "expert_in_tiers": "expert" in rules.TIERS,
        "justsilas_hard_rl_depts": hard_rl_depts,
        "harbor_expert_rc": harbor_proc.returncode,
        "harbor_expert_rejected": harbor_proc.returncode != 0,
        "harbor_stderr_tail": harbor_proc.stderr.strip().splitlines()[-1] if harbor_proc.stderr.strip() else "",
        "solver_str_expert_error": solver_str_err,
        "exact_block_returns_none": exact_block is None,
        "param_block_parses_fa_070": (param_block is not None and param_block.fingerprint_accuracy == 0.70 and param_block.name == "expert"),
        "params_from_instruction_parses_fa_070": (full_parsed is not None and full_parsed.fingerprint_accuracy == 0.70),
        "prose_only_returns_none": prose_only is None,
        "tier_from_instruction_returns_none": t_from_ins is None,
        "default_threshold_on_expert": default_thr_expert,
        "ok": (
            ("expert" not in rules.TIERS)
            and hard_rl_depts == [4]
            and harbor_proc.returncode != 0
            and solver_str_err == "KeyError: 'expert'"
            and exact_block is None
            and full_parsed is not None
            and full_parsed.fingerprint_accuracy == 0.70
            and prose_only is None
            and t_from_ins is None
            and default_thr_expert == 0.9
        ),
    }


def _run_expert_worker(expert_root: Path, seeds: list[int], budget: int, baseline_digests: dict[str, Any]) -> dict[str, Any]:
    import logging

    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    from canary import rules
    from canary.analysis.accuse import audit_episode
    from canary.env import Env
    from canary.eval import run_episode
    from canary.mcp_server import Episode, SeedNotAllowed, sign_ledger, verify_ledger
    from canary.redteam.anticheat import replay_committed, replay_counts
    from canary.redteam.fuzz import hunt
    from canary.solver import params as solver_params
    from canary.solver.policy import SolverPolicy, tier_from_instruction

    t0 = time.time()
    fuzz_res = hunt("expert", seeds, budget=budget, seed=0, mode="all", workers=1)
    fuzz_summary = {
        "tier": "expert",
        "seeds": [seeds[0], seeds[-1]],
        "n_seeds": len(seeds),
        "budget": budget,
        "workers": 1,
        "best_non_solver_score": float(fuzz_res["best_non_solver_score"]),
        "best_score_per_call": round(float(fuzz_res["best_score_per_call"]), 6),
        "n_invariant_violations": len(fuzz_res["invariant_violations"]),
        "violation_kinds": list(fuzz_res["violation_kinds"]),
        "per_mode": {
            m: {
                "budget": r.get("budget"),
                "races": r.get("races"),
                "best_non_solver_score": float(r["best_non_solver_score"]),
                "n_violations": int(r["n_violations"]),
            }
            for m, r in fuzz_res["per_mode"].items()
        },
        "elapsed_s": round(time.time() - t0, 2),
    }

    t1 = time.time()
    ladder_res = run_baselines_and_ladder(seeds, lambda s: Env("expert", s))
    ladder_res["elapsed_s"] = round(time.time() - t1, 2)

    t2 = time.time()
    v_audit = run_v_and_known_v_audit(seeds, lambda s: Env("expert", s))
    v_audit["elapsed_s"] = round(time.time() - t2, 2)

    verdict_path = expert_root / "results" / "expert_verdict.json"
    if not verdict_path.exists():
        verdict_path = expert_root / "results" / "expert_verdict_partial.json"
    verdict = json.loads(verdict_path.read_text())
    verdict_seeds = [int(s) for s in verdict["seeds"]]
    all_window_seeds = list(range(60000, max(verdict_seeds) + 1))

    solver_window: dict[int, dict[str, Any]] = {}
    solver_thr085_verdict_scores: dict[int, float] = {}
    for s in all_window_seeds:
        ep = run_episode(Env("expert", s), SolverPolicy(None))
        aud = audit_episode(ep)
        p_val = aud["p_accused"]
        v_val = ep.meta.get("V")
        if ep.end_reason != "accused":
            luck_ev = 0.0
        else:
            luck_ev = float(p_val) * float(v_val) - (1.0 - float(p_val))
        solver_window[s] = {
            "score": float(ep.score),
            "accused": ep.end_reason == "accused",
            "correct": bool(ep.correct),
            "p_accused": p_val,
            "V": v_val,
            "luck_adj": luck_ev,
            "single_canary_hit": _single_canary_hit_steps(ep.steps) if ep.end_reason == "accused" else None,
        }
        if s in set(verdict_seeds):
            ep85 = run_episode(Env("expert", s), SolverPolicy(None, threshold=0.85))
            solver_thr085_verdict_scores[s] = float(ep85.score)

    verdict_audit = audit_verdict_payload(verdict, {s: solver_window[s] for s in verdict_seeds})
    verdict_audit["verdict_file"] = verdict_path.relative_to(expert_root).as_posix()
    verdict_audit["paired_solver_by_seed"] = {str(s): solver_window[s] for s in verdict_seeds}
    verdict_audit["solver_thr085_mean_same_seeds"] = round(
        sum(solver_thr085_verdict_scores[s] for s in verdict_seeds) / len(verdict_seeds), 6
    )
    verdict_audit["solver_thr085_changed_seeds"] = [
        {"seed": s, "thr090_score": solver_window[s]["score"], "thr085_score": solver_thr085_verdict_scores[s]}
        for s in verdict_seeds
        if abs(solver_window[s]["score"] - solver_thr085_verdict_scores[s]) > 1e-9
    ]

    gem_by_seed = {int(r["seed"]): float(r["gemini"]) for r in verdict["per_seed"]}
    gem_ev_by_seed = {int(r["seed"]): float(r["luck_adjusted_ev"]) for r in verdict_audit["per_seed_ev"]}
    for label, window in (("60001_60020_n20", list(range(60001, 60021))), ("60000_60020_n21", list(range(60000, 60021)))):
        gf = [gem_by_seed.get(s, 0.0) for s in window]
        sf = [solver_window[s]["score"] for s in window]
        gl = [gem_ev_by_seed.get(s, 0.0) for s in window]
        sl = [solver_window[s]["luck_adj"] for s in window]
        r_lo, r_hi = boot_ratio(gf, sf)
        l_lo, l_hi = boot_ratio(gl, sl)
        verdict_audit[f"if_missing_zero_{label}"] = {
            "n": len(window),
            "gemini_mean": round(sum(gf) / len(window), 4),
            "solver_mean": round(sum(sf) / len(window), 4),
            "raw_ratio": round(sum(gf) / sum(sf), 4),
            "raw_ratio_ci": [round(r_lo, 4), round(r_hi, 4)],
            "luck_adj_gemini": round(sum(gl) / len(window), 4),
            "luck_adj_solver": round(sum(sl) / len(window), 4),
            "luck_adj_ratio": round(sum(gl) / sum(sl), 4),
            "luck_adj_ratio_ci": [round(l_lo, 4), round(l_hi, 4)],
        }

    staging_candidates = list((expert_root / "data").rglob("*expert*")) if (expert_root / "data").exists() else []
    verdict_audit["committed_expert_episode_files"] = [p.relative_to(expert_root).as_posix() for p in staging_candidates]
    if not staging_candidates:
        verdict_audit["ship_bar_reasons"].append("zero_committed_opencode_transcripts_for_replay")
    verdict_audit["filter_semantics"] = audit_verdict_filter_semantics()

    t3 = time.time()
    rep_rows = replay_committed(expert_root)
    rep_cnt = replay_counts(rep_rows)
    rep_cnt["elapsed_s"] = round(time.time() - t3, 2)
    rep_cnt["any_mismatches"] = any(bool(r.get("mismatches")) for r in rep_rows)
    verdict_audit["committed_tree_replay"] = rep_cnt

    expert_p = rules.EXPERT_TIERS["expert"]
    hard_p = rules.TIERS["hard"]
    param_diffs = {}
    for f in fields(expert_p):
        ev = getattr(expert_p, f.name)
        hv = getattr(hard_p, f.name)
        if ev != hv:
            param_diffs[f.name] = {"hard": hv, "expert": ev}

    expert_digests = compute_world_digests()
    digest_diffs: list[dict[str, Any]] = []
    for k, base_info in sorted(baseline_digests.items()):
        exp_info = expert_digests[k]
        if base_info["digest"] != exp_info["digest"]:
            digest_diffs.append({
                "key": k,
                "justSilas": base_info,
                "justSilas_expert": exp_info,
            })

    env_cap = Env("expert", 71000)
    for _ in range(420):
        last_ok = env_cap.call("status", {})
    cap_421 = env_cap.call("status", {})
    post_cap_score = env_cap.score()
    post_cap_acc = env_cap.call("accuse", {"employee": env_cap._world.mole})

    env_day = Env("expert", 71001)
    emps = [e["id"] for e in env_day.call("list_employees", {}).data["employees"]]
    depts = sorted({e["dept"] for e in env_day.call("list_employees", {}).data["employees"]})
    clearances = sorted({e["clearance"] for e in env_day.call("list_employees", {}).data["employees"]})
    c1 = env_day.call("plant_canary", {"doc_title": "c1", "assignment": {emps[0]: "A", emps[1]: "B"}})
    c2 = env_day.call("plant_canary", {"doc_title": "c2", "assignment": {emps[2]: "A", emps[3]: "B"}})
    c3 = env_day.call("plant_canary", {"doc_title": "c3", "assignment": {emps[4]: "A", emps[5]: "B"}})
    env_var = Env("expert", 71002)
    c_4var = env_var.call("plant_canary", {"doc_title": "bad4", "assignment": {emps[0]: "A", emps[1]: "B", emps[2]: "C", emps[3]: "D"}})

    env_act = Env("expert", 71003)
    act_oks = [env_act.call("check_leak_feed", {}).ok for _ in range(8)]
    act_9th = env_act.call("check_leak_feed", {})

    old_allow = os.environ.pop("CANARY_ALLOW_DEV", None)
    try:
        dev_blocked = False
        try:
            Episode("expert", 0)
        except SeedNotAllowed:
            dev_blocked = True
        mcp_ep = Episode("expert", 900000)
        mid_ledger = mcp_ep.ledger_payload()
        barrier = threading.Barrier(8)
        race_oks: list[bool] = []

        def _race(eid: str) -> None:
            barrier.wait()
            race_oks.append(mcp_ep.call("accuse", {"employee": eid}).ok)

        threads = [threading.Thread(target=_race, args=(f"e{i:02d}",)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        end_ledger = mcp_ep.ledger_payload()
        signed = sign_ledger(end_ledger, "audit-key-0123456789abcdef")
        sig_ok = verify_ledger(signed, "audit-key-0123456789abcdef")
        sig_tamper_rejected = not verify_ledger({**signed, "score": 1.0}, "audit-key-0123456789abcdef")
    finally:
        if old_allow is not None:
            os.environ["CANARY_ALLOW_DEV"] = old_allow

    edge_bugs: list[dict[str, Any]] = []
    if digest_diffs:
        edge_bugs.append({
            "id": "EXP-BUG-01",
            "severity": "high",
            "location": "canary/world.py:121 + tests/test_expert_tier.py:16",
            "summary": "hard_rl world generation changed from 4 departments on justSilas to 5 departments on justSilas-expert (036b90c7), altering mole, decoy, roster and recipients across all hard_rl seeds while PINNED omitted hard_rl",
            "affected_keys": [d["key"] for d in digest_diffs],
        })

    expert_ins = Env("expert", 0).instruction()
    exact_block_parsed = solver_params._from_exact_block(expert_ins)
    param_block_parsed = solver_params._from_param_block(expert_ins)
    full_ins_parsed = solver_params.params_from_instruction(expert_ins)
    prose_hdr = f"{chr(35)} Canary: catch the mole (expert tier)\nTier: expert\ncompany with 40 employees"
    prose_only_parsed = solver_params._params_from_prose(prose_hdr)
    t_from_ins = tier_from_instruction(expert_ins)
    solver_str_err = None
    try:
        SolverPolicy("expert")
    except Exception as exc:
        solver_str_err = f"{type(exc).__name__}: {exc}"
    sp_none_ins = SolverPolicy(None)
    sp_none_ins.reset([], expert_ins)
    default_thr_expert = sp_none_ins.default_threshold() if sp_none_ins.P is not None else None

    sp_empty = SolverPolicy(None)
    sp_empty.act(list(env_day._history[:0]))
    env_tmp = Env("expert", 71004)
    env_tmp.call("list_employees", {})
    sp_empty._ingest(env_tmp._history[-1])
    empty_fallback_fa = sp_empty.P.fingerprint_accuracy if sp_empty.P is not None else None
    if exact_block_parsed is None or solver_str_err is not None or empty_fallback_fa != 0.70 or t_from_ins is None:
        edge_bugs.append({
            "id": "EXP-BUG-02",
            "severity": "medium",
            "location": "canary/solver/params.py:63,97 + canary/solver/policy.py:39,90,147,276",
            "summary": "SolverPolicy('expert') raises KeyError('expert') at TIERS[p], _from_exact_block and tier_from_instruction return None, SolverPolicy(None) recovers fingerprint_accuracy=0.70 only via _from_param_block, empty-instruction fallback picks TIERS['hard'] (0.95), and default_threshold falls back to 0.90 instead of 0.85",
            "details": {
                "_from_exact_block_returns": exact_block_parsed,
                "_from_param_block_fa": param_block_parsed.fingerprint_accuracy if param_block_parsed else None,
                "params_from_instruction_fa": full_ins_parsed.fingerprint_accuracy if full_ins_parsed else None,
                "_params_from_prose_without_full_block_returns": prose_only_parsed,
                "tier_from_instruction_returns": t_from_ins,
                "SolverPolicy_str_expert": solver_str_err,
                "empty_instruction_fallback_fingerprint_accuracy": empty_fallback_fa,
                "default_threshold_expert": default_thr_expert,
            },
        })

    harbor_proc = subprocess.run(
        [sys.executable, str(expert_root / "harbor" / "build.py"), "--tiers", "expert", "--seeds", "900000"],
        capture_output=True,
        text=True,
        cwd=str(expert_root),
    )
    gemini_runner_proc = subprocess.run(
        [sys.executable, str(expert_root / "scripts" / "gemini_runner.py"), "--tiers-version", "v1.6", "--tiers", "expert", "--dry-run"],
        capture_output=True,
        text=True,
        cwd=str(expert_root),
    )
    if harbor_proc.returncode != 0 or gemini_runner_proc.returncode != 0:
        edge_bugs.append({
            "id": "EXP-BUG-03",
            "severity": "medium",
            "location": "harbor/build.py:177 + scripts/gemini_runner.py:155 + canary/redteam/anticheat.py:501",
            "summary": "Harbor dataset builder rejects --tiers expert (if t not in TIERS), gemini_runner refuses --tiers-version v1.6 against TIERS_VERSION=='v1.4', and anticheat.replay_committed marks tiers_version=='v1.6' not_replayable",
            "harbor_rc": harbor_proc.returncode,
            "harbor_stderr_tail": harbor_proc.stderr.strip().splitlines()[-1] if harbor_proc.stderr.strip() else "",
            "gemini_runner_v16_rc": gemini_runner_proc.returncode,
            "gemini_runner_v16_stdout": gemini_runner_proc.stdout.strip(),
        })

    redteam_errs: dict[str, str] = {}
    try:
        from canary.redteam.encodings import audit_env_no_encoded_leak
        audit_env_no_encoded_leak("expert", [900000])
    except Exception as exc:
        redteam_errs["encodings.audit_env_no_encoded_leak"] = f"{type(exc).__name__}: {exc}"
    try:
        from canary.redteam.seed_attack import recover_world
        recover_world("expert", 0)
    except Exception as exc:
        redteam_errs["seed_attack.recover_world"] = f"{type(exc).__name__}: {exc}"
    try:
        from canary.redteam.text_probe import collect_texts
        collect_texts("expert", 0)
    except Exception as exc:
        redteam_errs["text_probe.collect_texts"] = f"{type(exc).__name__}: {exc}"
    if redteam_errs:
        edge_bugs.append({
            "id": "EXP-BUG-04",
            "severity": "low",
            "location": "canary/redteam/encodings.py:1292 + seed_attack.py:33 + text_probe.py:72 + eval.py:23",
            "summary": "Redteam leak/seed/text probes and eval --tier all omit EXPERT_TIERS",
            "errors": redteam_errs,
        })

    if verdict_audit["below_break_even_bug_confirmed"] or verdict_audit["filter_semantics"]["drops_unaccused_timeouts_and_abstentions"]:
        edge_bugs.append({
            "id": "EXP-BUG-05",
            "severity": "high",
            "location": "scripts/expert_verdict.py:40,117",
            "summary": "expert_verdict.py checks meta['V'] instead of meta['V_final'] (reporting below_break_even=0 instead of 3/13 on seeds 60003, 60012, 60019), filters end_reason!='error' on OpenCode episodes, and has zero raw expert transcripts committed in git",
            "true_below_break_even_seeds": verdict_audit["true_below_break_even_seeds"],
        })

    fresh_70k = json.loads((expert_root / "results" / "expert_fresh_70000.json").read_text())
    ac_expert = json.loads((expert_root / "results" / "anticheat_expert" / "exploits.json").read_text())

    return {
        "expert_git_sha": subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(expert_root), check=True
        ).stdout.strip(),
        "tiers_version": rules.TIERS_VERSION,
        "expert_rules_version": rules.EXPERT_RULES_VERSION,
        "expert_not_in_tiers": "expert" not in rules.TIERS,
        "param_diffs_vs_hard": param_diffs,
        "fuzz": fuzz_summary,
        "baselines_and_ladder": ladder_res,
        "v_and_known_v": v_audit,
        "verdict_audit": verdict_audit,
        "committed_reference_files": {
            "expert_fresh_70000": {
                "n": fresh_70k["n"],
                "seed0": fresh_70k["seed0"],
                "hard_solver_mean": fresh_70k["configs"][0]["solver"]["mean"],
                "hard_grok_mean": fresh_70k["configs"][0]["grok_tactics"]["mean"],
                "hard_heuristic_mean": fresh_70k["configs"][0]["heuristic"]["mean"],
                "expert_solver_mean": fresh_70k["configs"][1]["solver"]["mean"],
                "expert_solver_acc": fresh_70k["configs"][1]["solver"]["acc_among_accused"],
                "expert_solver_abstain": fresh_70k["configs"][1]["solver"]["abstain"],
                "expert_grok_mean": fresh_70k["configs"][1]["grok_tactics"]["mean"],
                "expert_heuristic_mean": fresh_70k["configs"][1]["heuristic"]["mean"],
            },
            "anticheat_expert": {
                "all_blocked": ac_expert["all_blocked"],
                "n_rows": len(ac_expert["rows"]),
                "n_seeds_per_row": ac_expert["rows"][0]["n"],
                "has_swarm_w2b008": any(r["probe"] == "swarm_w2b008" for r in ac_expert["rows"]),
                "replay_counts": ac_expert["replay_counts"],
            },
        },
        "env_and_mcp_checks": {
            "n_employees": len(emps),
            "n_depts": len(depts),
            "depts": depts,
            "clearances": clearances,
            "tool_call_cap_420_ok": bool(last_ok.ok and not cap_421.ok and env_cap.done and post_cap_score == 0.0 and not post_cap_acc.ok),
            "canaries_per_day_2_ok": bool(c1.ok and c2.ok and not c3.ok and c3.error == "canary limit for today reached"),
            "max_variants_3_ok": bool(not c_4var.ok and c_4var.error == "invalid arguments"),
            "actions_per_day_8_ok": bool(all(act_oks) and not act_9th.ok and act_9th.error == "daily action limit; call advance_day"),
            "mcp_dev_seed_blocked_by_default": dev_blocked,
            "mcp_mid_episode_ledger_redacted": bool(mid_ledger.get("redacted") == "episode in progress" and "V" not in mid_ledger),
            "mcp_parallel_accuse_single_winner": sum(race_oks) == 1,
            "mcp_ledger_hmac_ok": bool(sig_ok and sig_tamper_rejected),
        },
        "world_digest_diffs_vs_justSilas": digest_diffs,
        "edge_bugs": edge_bugs,
    }


@contextlib.contextmanager
def synthetic_expert_tier():
    from canary import rules

    expert_cfg = replace(rules.TIERS["hard"], name="expert", fingerprint_accuracy=0.70)
    had_expert = "expert" in rules.TIERS
    prev_val = rules.TIERS.get("expert")
    rules.TIERS["expert"] = expert_cfg
    try:
        yield expert_cfg
    finally:
        if had_expert and prev_val is not None:
            rules.TIERS["expert"] = prev_val
        else:
            rules.TIERS.pop("expert", None)


def run_standalone_self_test(seeds: list[int] | None = None, budget: int = 60) -> dict[str, Any]:
    from canary import rules
    from canary.env import Env
    from canary.redteam.fuzz import hunt

    test_seeds = seeds if seeds is not None else list(range(71000, 71006))
    verdict_audit = audit_verdict_payload(VERDICT_SNAPSHOT_29CA3BC5, PAIRED_SOLVER_SNAPSHOT_29CA3BC5)
    sol_ver = verdict_audit["solver_verification"] or {}
    filter_audit = audit_verdict_filter_semantics()
    compat_audit = audit_justsilas_integration_compat()
    gap_md_check = check_gap_md_expert_entry()

    with synthetic_expert_tier() as expert_cfg:
        fuzz_res = hunt("expert", test_seeds, budget=budget, seed=0, mode="all", workers=1)
        lazy_res = run_baselines_and_ladder(
            test_seeds,
            lambda s: Env("expert", s),
            policy_names=("do_nothing", "stop_early", "guess_day1", "logs_only", "heuristic", "grok_tactics", "solver"),
        )
        v_res = run_v_and_known_v_audit(test_seeds, lambda s: Env("expert", s))
        param_diff = {
            f.name: (getattr(rules.TIERS["hard"], f.name), getattr(expert_cfg, f.name))
            for f in fields(expert_cfg)
            if getattr(rules.TIERS["hard"], f.name) != getattr(expert_cfg, f.name)
        }

    tiers_clean_after = "expert" not in rules.TIERS
    ok = (
        tiers_clean_after
        and compat_audit["ok"]
        and gap_md_check["ok"]
        and fuzz_res["best_non_solver_score"] == 0.0
        and len(fuzz_res["invariant_violations"]) == 0
        and lazy_res["all_checks_pass"]
        and v_res["all_ok"]
        and verdict_audit["n"] == 13
        and verdict_audit["correct_count"] == 13
        and verdict_audit["zero_timeout_or_error_in_valid"]
        and verdict_audit["matches_gap_md_84_52_128"]
        and len(verdict_audit["score_invariant_violations"]) == 0
        and verdict_audit["gemini_mean_diff"] < 1e-9
        and verdict_audit["solver_mean_diff"] < 1e-9
        and verdict_audit["raw_ratio_diff"] < 1e-9
        and verdict_audit["luck_adj_gemini_diff"] < 1e-9
        and sol_ver.get("score_mismatches") == []
        and float(sol_ver.get("luck_adj_solver_diff", 1.0)) < 1e-9
        and float(sol_ver.get("luck_adj_ratio_diff", 1.0)) < 1e-9
        and max(sol_ver.get("luck_adj_ci_diff") or [1.0, 1.0]) < 1e-9
        and verdict_audit["below_break_even_bug_confirmed"]
        and verdict_audit["true_gemini_below_break_even"] == 3
        and verdict_audit["fails_ship_bar"]
        and filter_audit["drops_unaccused_timeouts_and_abstentions"]
        and filter_audit["meta_v_key_mismatch_confirmed"]
        and set(param_diff.keys()) == {"name", "fingerprint_accuracy"}
    )
    return {
        "ok": ok,
        "tiers_clean_after": tiers_clean_after,
        "compat_audit": compat_audit,
        "gap_md_check": gap_md_check,
        "fuzz_best_non_solver_score": float(fuzz_res["best_non_solver_score"]),
        "fuzz_violations": len(fuzz_res["invariant_violations"]),
        "lazy_baselines": lazy_res,
        "v_and_known_v": v_res,
        "verdict_audit": verdict_audit,
        "filter_audit": filter_audit,
        "param_diff_keys": sorted(param_diff.keys()),
    }


def validate_report_markdown(report_path: Path) -> dict[str, Any]:
    text = report_path.read_text(encoding="utf-8")
    bad_dashes = text.count("\u2014") + text.count("\u2013") + text.count("\u2212")
    required_tokens = [
        "29ca3bc5",
        "036b90c7",
        "244434fc",
        "f9fb7a4a",
        "fingerprint_accuracy",
        "0.70",
        "71000-71199",
        "20000",
        "84%",
        "52%",
        "128%",
        "13/13",
        "60003",
        "60005",
        "60012",
        "60019",
        "hard_rl",
        "EXP-BUG-01",
        "EXP-BUG-02",
        "EXP-BUG-03",
        "EXP-BUG-04",
        "EXP-BUG-05",
    ]
    missing = [tok for tok in required_tokens if tok not in text]
    return {
        "exists": report_path.exists(),
        "em_dash_count": bad_dashes,
        "missing_tokens": missing,
        "ok": bad_dashes == 0 and not missing,
    }


def audit_expert_tree(expert_root: Path, seeds_spec: str = "71000-71199", budget: int = 20000) -> dict[str, Any]:
    justsilas_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(ROOT), check=True
    ).stdout.strip()
    baseline_digests = compute_world_digests()
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{expert_root}:{expert_root / 'scripts'}"
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--internal-worker",
        str(expert_root),
        "--seeds",
        seeds_spec,
        "--budget",
        str(budget),
        "--baseline-digests-json",
        json.dumps(baseline_digests),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=True)
    res = json.loads(proc.stdout)
    res["justsilas_base_sha"] = justsilas_sha
    res["gap_md_check"] = check_gap_md_expert_entry()
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Audit origin/justSilas-expert@29ca3bc5 integrity, fuzz and n=13 verdict")
    ap.add_argument("--expert-root", type=Path, default=None)
    ap.add_argument("--seeds", default="71000-71199")
    ap.add_argument("--budget", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--check-report", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--internal-worker", type=Path, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--baseline-digests-json", default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise SystemExit("--workers must be 1 on shared cgroup nodes")

    if args.internal_worker is not None:
        expert_root = args.internal_worker.resolve()
        sys.path.insert(0, str(expert_root / "scripts"))
        sys.path.insert(0, str(expert_root))
        out = _run_expert_worker(
            expert_root,
            parse_seeds(args.seeds),
            args.budget,
            json.loads(args.baseline_digests_json or "{}"),
        )
        print(json.dumps(out, sort_keys=True))
        return 0

    if args.self_test:
        res = run_standalone_self_test()
        if args.check_report is not None:
            res["report_check"] = validate_report_markdown(args.check_report)
            res["ok"] = bool(res["ok"] and res["report_check"]["ok"])
        if args.out_json is not None:
            args.out_json.parent.mkdir(parents=True, exist_ok=True)
            args.out_json.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
        print(json.dumps(res, indent=2, sort_keys=True))
        return 0 if res["ok"] else 1

    if args.expert_root is None:
        raise SystemExit("pass --expert-root <path> or --self-test")

    res = audit_expert_tree(args.expert_root.resolve(), args.seeds, args.budget)
    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(res, indent=2, sort_keys=True) + "\n")
    print(json.dumps(res, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
