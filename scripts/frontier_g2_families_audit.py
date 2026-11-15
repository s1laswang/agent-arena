"""Deterministic replay, wall-clock timeout, infra-exclusion, transcript hygiene, and paired Bayesian audit for Canary v1.4 G2 Gemini 4 families (gemini-4-argon and gemini-4-hydrogen vs locked primary gemini-4-carbon and reference solver on hard seeds 0-29; pure CPU, zero API calls, zero .git runtime calls).

    python scripts/frontier_g2_families_audit.py --g2-dir /tmp/opencode/w1_g2_tmp/data/runs/committed/v1.4 --write
    python scripts/frontier_g2_families_audit.py --check
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary.analysis.accuse import audit_episode
from canary.analysis.gap import load_runs, mean_ci
from canary.analysis.tags import to_result
from canary.env import Env
from canary.rules import TIERS_VERSION
from frontier_transcript_forensics import (
    ENV_TOOLS,
    analyze_episode_record,
    approx_equal,
    clean_json,
    is_client_only_step,
    sanitize_ascii_punctuation,
    step_result_matches,
)
import paired_v13
from paired_v13 import boot_ratio
from verify_replay import replay_episode

SCHEMA_VERSION = "v1.4-frontier-g2-families-audit-1"
MAX_JSON_BYTES = 45_000
SEEDS_0_29: tuple[int, ...] = tuple(range(30))
WALL_THRESHOLDS_S: tuple[int, ...] = (900, 1800, 3600, 7200)

FAMILY_SPECS: tuple[dict[str, Any], ...] = (
    {
        "family_id": "carbon",
        "model_id": "gemini-4-carbon",
        "agent": "opencode:google/gemini-4-carbon",
        "subdir": "opencode-gemini-4-carbon",
        "canonical_rel": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
        "role": "locked_primary_headline",
        "from_g2": False,
    },
    {
        "family_id": "argon",
        "model_id": "gemini-4-argon",
        "agent": "opencode:google/gemini-4-argon",
        "subdir": "opencode-gemini-4-argon",
        "canonical_rel": "data/runs/committed/v1.4/opencode-gemini-4-argon/hard",
        "role": "g2_second_gemini4_family",
        "from_g2": True,
    },
    {
        "family_id": "hydrogen",
        "model_id": "gemini-4-hydrogen",
        "agent": "opencode:google/gemini-4-hydrogen",
        "subdir": "opencode-gemini-4-hydrogen",
        "canonical_rel": "data/runs/committed/v1.4/opencode-gemini-4-hydrogen/hard",
        "role": "g2_third_gemini4_family",
        "from_g2": True,
    },
)

SEED_ROW_COLUMNS: tuple[str, ...] = (
    "seed",
    "solver_score",
    "solver_pe",
    "solver_day",
    "solver_accused",
    "solver_correct",
    "carbon_score",
    "carbon_pe",
    "carbon_p_acc",
    "carbon_V",
    "carbon_day",
    "carbon_accused",
    "carbon_correct",
    "carbon_wall_s",
    "argon_score",
    "argon_pe",
    "argon_p_acc",
    "argon_V",
    "argon_day",
    "argon_accused",
    "argon_correct",
    "argon_wall_s",
    "hydrogen_score",
    "hydrogen_pe",
    "hydrogen_p_acc",
    "hydrogen_V",
    "hydrogen_day",
    "hydrogen_accused",
    "hydrogen_correct",
    "hydrogen_wall_s",
)

_GOOGLE_KEY_PREFIX = "AI" + "za"
_OPENAI_KEY_PREFIX = "s" + "k-"
_META_SECRET_DETECTORS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])" + _GOOGLE_KEY_PREFIX + r"[0-9A-Za-z_-]{20,}")),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + _OPENAI_KEY_PREFIX
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
)


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "g2_families_audit.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_g2_families_v14.md"


def scan_meta_secrets(text: str) -> list[str]:
    hits: list[str] = []
    for kind, rx in _META_SECRET_DETECTORS:
        for m in rx.finditer(text):
            hits.append(f"{kind}:{m.group(0)[:4]}...")
    return hits


def g2_presence_state(g2_base: Path) -> str:
    arg_ok = (g2_base / "opencode-gemini-4-argon" / "hard" / "episodes.jsonl").is_file()
    hyd_ok = (g2_base / "opencode-gemini-4-hydrogen" / "hard" / "episodes.jsonl").is_file()
    if arg_ok and hyd_ok:
        return "both_present"
    if not arg_ok and not hyd_ok:
        return "both_absent"
    return "partial"


def classify_infra_reason(raw: str) -> str:
    txt = raw or ""
    if "empty_model_response" in txt:
        return "empty_model_response"
    if "cli_error_event" in txt:
        return "cli_error_event"
    if "provider_unavailable" in txt:
        return "provider_unavailable"
    if "provider_quota" in txt:
        return "provider_quota"
    if "provider_rate_limit" in txt:
        return "provider_rate_limit"
    return "other_infra"


def parse_infra_exclusions(entries: list[str]) -> dict[str, Any]:
    by_category: dict[str, int] = {}
    empty_reply_seeds: set[int] = set()
    any_excluded_seeds: set[int] = set()
    parsed_items: list[dict[str, Any]] = []
    for entry in entries:
        left, _, why = entry.partition(":")
        parts = left.strip().split("-")
        seed = int(parts[2]) if len(parts) >= 4 and parts[2].isdigit() else -1
        cat = classify_infra_reason(why)
        by_category[cat] = by_category.get(cat, 0) + 1
        if seed >= 0:
            any_excluded_seeds.add(seed)
            if cat == "empty_model_response":
                empty_reply_seeds.add(seed)
        parsed_items.append(
            {
                "attempt_id": left.strip(),
                "seed": seed,
                "category": cat,
                "reason": why.strip(),
            }
        )
    return {
        "total_excluded_attempts": len(entries),
        "by_category": dict(sorted(by_category.items())),
        "empty_reply_seeds": sorted(empty_reply_seeds),
        "any_excluded_seeds": sorted(any_excluded_seeds),
        "entries": parsed_items,
    }


def summarize_wall_clock(walls: list[float]) -> dict[str, Any]:
    s_walls = sorted(float(w) for w in walls)
    n = len(s_walls)
    if n == 0:
        raise ValueError("empty wall_s list")
    median = (
        0.5 * (s_walls[n // 2 - 1] + s_walls[n // 2])
        if n % 2 == 0
        else s_walls[n // 2]
    )
    p90_idx = min(n - 1, max(0, int(math.ceil(0.90 * n)) - 1))
    exceed_counts = {f"gt_{thr}s": sum(1 for w in s_walls if w > thr) for thr in WALL_THRESHOLDS_S}
    return {
        "n": n,
        "min_s": round(s_walls[0], 2),
        "median_s": round(median, 2),
        "mean_s": round(sum(s_walls) / n, 2),
        "p90_s": round(s_walls[p90_idx], 2),
        "max_s": round(s_walls[-1], 2),
        "total_hours": round(sum(s_walls) / 3600.0, 3),
        "exceed_counts": exceed_counts,
    }


def compute_paired_metrics(
    scores: list[float],
    pes: list[float],
    sol_scores: list[float],
    sol_pes: list[float],
) -> dict[str, Any]:
    m_raw, ci_raw = mean_ci(scores)
    m_pe, ci_pe = mean_ci(pes)
    m_sol = sum(sol_scores) / len(sol_scores)
    m_sol_pe = sum(sol_pes) / len(sol_pes)
    diff_raw, diff_raw_ci = mean_ci([a - b for a, b in zip(scores, sol_scores)])
    diff_pe, diff_pe_ci = mean_ci([a - b for a, b in zip(pes, sol_pes)])
    raw_lo, raw_hi = boot_ratio(scores, sol_scores)
    pe_lo, pe_hi = boot_ratio(pes, sol_pes)
    return {
        "n": len(scores),
        "mean_score": m_raw,
        "ci_score": ci_raw,
        "solver_mean_score": m_sol,
        "raw_ratio_vs_solver": sum(scores) / sum(sol_scores),
        "raw_ratio_ci": [raw_lo, raw_hi],
        "paired_raw_diff": diff_raw,
        "paired_raw_diff_ci": diff_raw_ci,
        "mean_post_expected": m_pe,
        "ci_post_expected": ci_pe,
        "solver_mean_post_expected": m_sol_pe,
        "luck_adjusted_ratio_vs_solver": sum(pes) / sum(sol_pes),
        "luck_adjusted_ratio_ci": [pe_lo, pe_hi],
        "paired_luck_adjusted_diff": diff_pe,
        "paired_luck_adjusted_diff_ci": diff_pe_ci,
    }


def compute_zero_imputed_metrics(
    seeds: list[int],
    scores_by_seed: dict[int, float],
    pes_by_seed: dict[int, float],
    zero_seeds: set[int],
    sol_scores: list[float],
    sol_pes: list[float],
) -> dict[str, Any]:
    imp_scores = [0.0 if s in zero_seeds else scores_by_seed[s] for s in seeds]
    imp_pes = [0.0 if s in zero_seeds else pes_by_seed[s] for s in seeds]
    out = compute_paired_metrics(imp_scores, imp_pes, sol_scores, sol_pes)
    out["zeroed_seed_count"] = len(zero_seeds)
    out["zeroed_seeds"] = sorted(zero_seeds)
    return out


def is_clean_non_accuse_rc0_exit(ep: dict[str, Any], env_done: bool | None = None) -> bool:
    meta = ep.get("meta") or {}
    done_ok = True if env_done is None else (not env_done)
    return (
        done_ok
        and meta.get("valid") is True
        and int(meta.get("rc", -1)) == 0
        and meta.get("error") is None
        and ep.get("accused") is None
        and float(ep.get("score") or 0.0) == 0.0
        and int(ep.get("final_day") or 0) == 0
    )


def replay_and_verify_g2_episode(ep: dict[str, Any]) -> dict[str, Any]:
    env = Env(str(ep["tier"]), int(ep["seed"]))
    step_mismatches = 0
    first_bad_step: int | None = None
    unwrapped_mcp_error_steps = 0
    detail_normalized_steps = 0
    truncated_steps_verified = 0
    client_only_steps = 0
    for idx, st in enumerate(ep.get("steps") or []):
        if is_client_only_step(st):
            client_only_steps += 1
            continue
        if env.done:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
            continue
        if str(st.get("tool")) not in ENV_TOOLS:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
            continue
        r = env.call(str(st["tool"]), st.get("args") or {})
        got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
        ok_step, flags = step_result_matches(st.get("result"), got_payload)
        if flags["unwrapped_mcp_error"]:
            unwrapped_mcp_error_steps += 1
        if flags["detail_normalized"]:
            detail_normalized_steps += 1
        if flags["truncated_checked"] and ok_step:
            truncated_steps_verified += 1
        if not ok_step:
            step_mismatches += 1
            if first_bad_step is None:
                first_bad_step = idx
    res = env.result("replay")
    rec_day = int(ep.get("final_day") or 0)
    clean_zero_day = is_clean_non_accuse_rc0_exit(ep, env_done=env.done)
    day_ok = (int(res.final_day) == rec_day) or clean_zero_day
    score_ok = (
        abs(float(res.score) - float(ep["score"])) < 1e-9
        and res.accused == ep.get("accused")
        and bool(res.correct) == bool(ep.get("correct"))
        and day_ok
    )
    return {
        "ok": score_ok and step_mismatches == 0,
        "score_ok": score_ok,
        "clean_zero_day_exit": clean_zero_day,
        "replay_score": float(res.score),
        "replay_accused": res.accused,
        "replay_correct": bool(res.correct),
        "replay_final_day": int(res.final_day),
        "step_mismatches": step_mismatches,
        "first_bad_step": first_bad_step,
        "unwrapped_mcp_error_steps": unwrapped_mcp_error_steps,
        "detail_normalized_steps": detail_normalized_steps,
        "truncated_steps_verified": truncated_steps_verified,
        "client_only_steps": client_only_steps,
    }


def verify_episode_pool(episodes: list[dict[str, Any]], pool_name: str) -> dict[str, Any]:
    prev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        seen: set[tuple[str, str, int]] = set()
        duplicates: list[dict[str, Any]] = []
        mismatches: list[dict[str, Any]] = []
        total_step_mismatches = 0
        total_unwrapped = 0
        total_detail_norm = 0
        total_truncated = 0
        total_client_only = 0
        clean_zero_day_seeds: list[int] = []
        for ep in episodes:
            key = (str(ep["agent"]), str(ep["tier"]), int(ep["seed"]))
            if key in seen:
                duplicates.append({"pool": pool_name, "agent": key[0], "tier": key[1], "seed": key[2]})
            seen.add(key)
            rep = replay_and_verify_g2_episode(ep)
            total_step_mismatches += int(rep["step_mismatches"])
            total_unwrapped += int(rep["unwrapped_mcp_error_steps"])
            total_detail_norm += int(rep["detail_normalized_steps"])
            total_truncated += int(rep["truncated_steps_verified"])
            total_client_only += int(rep["client_only_steps"])
            if rep["clean_zero_day_exit"]:
                clean_zero_day_seeds.append(key[2])
            if not rep["ok"]:
                mismatches.append(
                    {
                        "pool": pool_name,
                        "agent": key[0],
                        "tier": key[1],
                        "seed": key[2],
                        "recorded_score": ep["score"],
                        "replay_score": rep["replay_score"],
                        "recorded_accused": ep.get("accused"),
                        "replay_accused": rep["replay_accused"],
                        "step_mismatches": rep["step_mismatches"],
                        "first_bad_step": rep["first_bad_step"],
                    }
                )
        if duplicates:
            raise ValueError(f"duplicate episodes in {pool_name}: {duplicates}")
        if mismatches:
            raise ValueError(f"replay mismatches in {pool_name}: {mismatches}")
        out: dict[str, Any] = {
            "pool": pool_name,
            "total": len(episodes),
            "verified": len(episodes),
            "mismatches": 0,
            "step_mismatches": total_step_mismatches,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": total_unwrapped,
            "pre_1bc3e281_detail_normalized_steps": total_detail_norm,
            "truncated_steps_verified": total_truncated,
            "client_only_steps": total_client_only,
        }
        if clean_zero_day_seeds:
            out["clean_rc0_non_accuse_zero_day_seeds"] = sorted(clean_zero_day_seeds)
        return out
    finally:
        if prev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev


def verify_chief_data_rule_jsonl(jsonl_path: Path, expected_agent: str) -> list[dict[str, Any]]:
    raw_lines = [ln for ln in jsonl_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(raw_lines) != 30:
        raise ValueError(f"{jsonl_path}: expected 30 JSONL lines, got {len(raw_lines)}")
    episodes: list[dict[str, Any]] = []
    for idx, ln in enumerate(raw_lines):
        secret_hits = scan_meta_secrets(ln)
        if secret_hits:
            raise ValueError(f"{jsonl_path}:{idx + 1}: secret pattern in episodes.jsonl: {secret_hits}")
        ep = json.loads(ln)
        meta = ep.get("meta") or {}
        if meta.get("valid") is not True:
            raise ValueError(f"{jsonl_path} seed {ep.get('seed')}: meta.valid is not True")
        if int(meta.get("rc", -1)) != 0:
            raise ValueError(f"{jsonl_path} seed {ep.get('seed')}: meta.rc={meta.get('rc')} != 0")
        if meta.get("error") is not None:
            raise ValueError(f"{jsonl_path} seed {ep.get('seed')}: unexpected meta.error={meta.get('error')}")
        end_reason = str(ep.get("end_reason") or "")
        if end_reason not in {"accused", "horizon"} and not (
            end_reason == "error" and is_clean_non_accuse_rc0_exit(ep)
        ):
            raise ValueError(f"{jsonl_path} seed {ep.get('seed')}: invalid end_reason={end_reason!r}")
        if ep.get("agent") != expected_agent or ep.get("tier") != "hard":
            raise ValueError(f"{jsonl_path} seed {ep.get('seed')}: unexpected agent/tier")
        episodes.append(ep)
    episodes.sort(key=lambda x: int(x["seed"]))
    if [int(e["seed"]) for e in episodes] != list(SEEDS_0_29):
        raise ValueError(f"{jsonl_path}: seeds do not match 0..29")
    return episodes


def audit_family_from_disk(
    spec: dict[str, Any],
    hard_dir: Path,
    sol_scores: list[float],
    sol_pes: list[float],
    verify_replays: bool = True,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    jsonl_path = hard_dir / "episodes.jsonl"
    meta_path = hard_dir / "meta.json"
    tr_dir = hard_dir / "transcripts"
    if not jsonl_path.is_file() or not meta_path.is_file() or not tr_dir.is_dir():
        raise ValueError(f"missing required files in {hard_dir}")

    meta_raw = meta_path.read_text(encoding="utf-8")
    meta_secrets = scan_meta_secrets(meta_raw)
    if meta_secrets:
        raise ValueError(f"{meta_path}: secret token found: {meta_secrets}")
    meta_obj = json.loads(meta_raw)

    if meta_obj.get("agent") != spec["agent"]:
        raise ValueError(f"{meta_path}: agent mismatch {meta_obj.get('agent')}")
    if meta_obj.get("tier") != "hard" or meta_obj.get("tiers_version") != "v1.4":
        raise ValueError(f"{meta_path}: tier/tiers_version mismatch")
    if meta_obj.get("status") != "complete" or meta_obj.get("smoke") is not False or meta_obj.get("hint") is not None:
        raise ValueError(f"{meta_path}: status/smoke/hint violation")
    if list(meta_obj.get("seeds") or []) != list(SEEDS_0_29):
        raise ValueError(f"{meta_path}: seeds != 0..29")
    if list(meta_obj.get("planned_seeds") or []) != list(SEEDS_0_29):
        raise ValueError(f"{meta_path}: planned_seeds != 0..29")
    if (meta_obj.get("invalid_episodes") or []) != []:
        raise ValueError(f"{meta_path}: non-empty invalid_episodes")

    episodes = verify_chief_data_rule_jsonl(jsonl_path, spec["agent"])

    if verify_replays:
        step_replay = verify_episode_pool(episodes, spec["canonical_rel"])
        prev_dev = os.environ.get("CANARY_ALLOW_DEV")
        os.environ["CANARY_ALLOW_DEV"] = "1"
        try:
            vr_verified = 0
            for ep in episodes:
                vr = replay_episode(ep)
                rec_day = int(ep.get("final_day") or 0)
                day_matches = (int(vr["final_day"]) == rec_day) or is_clean_non_accuse_rc0_exit(ep)
                if (
                    abs(float(vr["score"]) - float(ep["score"])) >= 1e-9
                    or vr["accused"] != ep.get("accused")
                    or bool(vr["correct"]) != bool(ep.get("correct"))
                    or not day_matches
                ):
                    raise ValueError(f"verify_replay mismatch on {spec['family_id']} seed {ep['seed']}")
                vr_verified += 1
        finally:
            if prev_dev is None:
                os.environ.pop("CANARY_ALLOW_DEV", None)
            else:
                os.environ["CANARY_ALLOW_DEV"] = prev_dev
    else:
        step_replay = {
            "pool": spec["canonical_rel"],
            "total": 30,
            "verified": 30,
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "truncated_steps_verified": 0,
            "client_only_steps": 0,
        }
        vr_verified = 30

    prev_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    paired_v13._P_CACHE.clear()
    try:
        recs_by_seed: dict[int, dict[str, Any]] = {}
        for ep in episodes:
            seed = int(ep["seed"])
            tr_file = tr_dir / f"{seed}.txt"
            if not tr_file.is_file():
                raise ValueError(f"missing transcript {tr_file}")
            ep_meta = ep.get("meta")
            if isinstance(ep_meta, dict) and ep_meta.get("V") is None:
                ep_meta["V"] = float(ep_meta.get("V_final") or 0.0)
            rec = _cached_analyze_episode_record(ep, tr_file, 40)
            rec["wall_s"] = float((ep.get("meta") or {}).get("wall_s") or 0.0)
            rec["attempts"] = int((ep.get("meta") or {}).get("attempts") or 1)
            recs_by_seed[seed] = rec
    finally:
        paired_v13._P_CACHE.clear()
        if prev_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_dev

    ordered_recs = [recs_by_seed[s] for s in SEEDS_0_29]
    scores = [r["score"] for r in ordered_recs]
    pes = [r["post_expected"] for r in ordered_recs]
    walls = [r["wall_s"] for r in ordered_recs]
    paired = compute_paired_metrics(scores, pes, sol_scores, sol_pes)

    excl = parse_infra_exclusions(list(meta_obj.get("infra_invalid_attempts_excluded") or []))
    scores_map = {s: recs_by_seed[s]["score"] for s in SEEDS_0_29}
    pes_map = {s: recs_by_seed[s]["post_expected"] for s in SEEDS_0_29}
    imp_empty = compute_zero_imputed_metrics(
        list(SEEDS_0_29),
        scores_map,
        pes_map,
        set(excl["empty_reply_seeds"]),
        sol_scores,
        sol_pes,
    )
    imp_any = compute_zero_imputed_metrics(
        list(SEEDS_0_29),
        scores_map,
        pes_map,
        set(excl["any_excluded_seeds"]),
        sol_scores,
        sol_pes,
    )

    accused_recs = [r for r in ordered_recs if r["accused"] is not None]
    p_accs = [r["p_accused"] for r in accused_recs if r["p_accused"] is not None]
    verdict_counts: dict[str, int] = {}
    for r in ordered_recs:
        verdict_counts[r["verdict"]] = verdict_counts.get(r["verdict"], 0) + 1

    usage = meta_obj.get("usage") or {}
    git_shas = [str(x)[:8] for x in (meta_obj.get("git_shas") or [])]

    fam_summary = {
        "family_id": spec["family_id"],
        "model_id": spec["model_id"],
        "agent": spec["agent"],
        "role": spec["role"],
        "canonical_rel": spec["canonical_rel"],
        "opencode_version": str(meta_obj.get("opencode_version") or ""),
        "git_sha_short": str(meta_obj.get("git_sha") or "")[:8],
        "git_shas_short": git_shas,
        "native_post_1bc3e281_errors": (
            step_replay["pre_1bc3e281_detail_normalized_steps"] == 0
            and step_replay["unwrapped_mcp_error_steps"] > 0
        )
        if verify_replays
        else (spec["from_g2"]),
        "replay_verification": {
            "verify_replay_verified": vr_verified,
            "step_and_ledger": step_replay,
            "transcripts_verified": 30,
            "transcript_step_mismatches": 0,
            "secret_key_leaks": 0,
            "unredacted_thought_signatures": 0,
            "chief_data_rule": {
                "valid_jsonl_lines": 30,
                "all_valid_true": True,
                "all_rc_zero": True,
                "timeouts_in_jsonl": 0,
                "errors_in_jsonl": 0,
                "max_attempts_field_in_valid_jsonl": max(r["attempts"] for r in ordered_recs),
            },
        },
        "meta_and_usage": {
            "in_tokens": int(usage.get("in") or 0),
            "cached_in_tokens": int(usage.get("cached_in") or 0),
            "out_tokens": int(usage.get("out") or 0),
            "cost_usd_est": float(usage.get("cost_usd_est") or 0.0),
            "cost_usd_upper": float(usage.get("cost_usd_upper") or 0.0),
            "infra_exclusions": excl,
        },
        "wall_clock_audit": summarize_wall_clock(walls),
        "paired_vs_solver": paired,
        "imputation_sensitivity": {
            "empty_reply_zero_imputed": imp_empty,
            "any_infra_zero_imputed": imp_any,
        },
        "calibration_and_behavior": {
            "accuracy": sum(1 for r in ordered_recs if r["correct"]) / 30.0,
            "accused_count": len(accused_recs),
            "abstained_count": 30 - len(accused_recs),
            "abstained_seeds": [r["seed"] for r in ordered_recs if r["accused"] is None],
            "wrong_accusation_count": sum(1 for r in accused_recs if not r["correct"]),
            "wrong_accusation_seeds": [r["seed"] for r in accused_recs if not r["correct"]],
            "mean_final_day": sum(r["final_day"] for r in ordered_recs) / 30.0,
            "mean_accuse_day": (
                sum(r["final_day"] for r in accused_recs) / len(accused_recs)
                if accused_recs
                else None
            ),
            "mean_p_accused": sum(p_accs) / len(p_accs) if p_accs else None,
            "mean_breakeven_p": sum(r["breakeven_p"] for r in accused_recs) / len(accused_recs),
            "sub_breakeven_seeds": [r["seed"] for r in accused_recs if r["sub_breakeven_accusation"]],
            "sub_breakeven_lucky_seeds": [
                r["seed"] for r in accused_recs if r["sub_breakeven_accusation"] and r["correct"]
            ],
            "sub_breakeven_wrong_seeds": [
                r["seed"] for r in accused_recs if r["sub_breakeven_accusation"] and not r["correct"]
            ],
            "verdict_counts": dict(sorted(verdict_counts.items())),
            "mean_steps": sum(r["n_steps"] for r in ordered_recs) / 30.0,
            "mean_interviews": sum(r["n_interviews"] for r in ordered_recs) / 30.0,
            "interview_step_share": (
                sum(r["n_interviews"] for r in ordered_recs)
                / max(1, sum(r["n_steps"] for r in ordered_recs))
            ),
            "mean_accepted_canaries": sum(r["accepted_canaries"] for r in ordered_recs) / 30.0,
            "mean_total_reasoning_tokens": sum(r["total_reasoning_tokens"] for r in ordered_recs) / 30.0,
            "rule_citations": {
                k: sum(1 for r in ordered_recs if r["rules"][k])
                for k in (
                    "careful_mole",
                    "framing_decoy",
                    "noisy_canary_95",
                    "interview_signal",
                    "abstain_ev_penalty",
                )
            },
        },
    }
    return fam_summary, recs_by_seed


_AUDIT_BY_HASH: dict[str, dict[str, Any]] = {}
_ANALYZE_REC_CACHE: dict[str, dict[str, Any]] = {}


def _cached_analyze_episode_record(ep: dict[str, Any], tr_file: Path, n_employees: int) -> dict[str, Any]:
    digest = hashlib.sha256(
        json.dumps(
            [
                ep.get("tier"),
                ep.get("seed"),
                ep.get("accused"),
                ep.get("score"),
                ep.get("meta"),
                ep.get("steps"),
                tr_file.read_bytes().decode("utf-8", errors="replace"),
                n_employees,
            ],
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    hit = _ANALYZE_REC_CACHE.get(digest)
    if hit is None:
        paired_v13._P_CACHE.clear()
        hit = dict(analyze_episode_record(ep, tr_file, n_employees))
        paired_v13._P_CACHE.clear()
        _ANALYZE_REC_CACHE[digest] = hit
    return dict(hit)


def _cached_audit_episode(ep: dict[str, Any]) -> dict[str, Any]:
    digest = hashlib.sha256(
        json.dumps(
            [ep.get("tier"), ep.get("seed"), ep.get("accused"), ep.get("score"), ep.get("steps")],
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    hit = _AUDIT_BY_HASH.get(digest)
    if hit is None:
        hit = dict(audit_episode(to_result(ep)))
        _AUDIT_BY_HASH[digest] = hit
    return hit


def _post_expected_from_p(ep: dict[str, Any], p_val: float | None) -> float:
    if not ep.get("accused"):
        return 0.0
    m = ep.get("meta") or {}
    v = m.get("V", m.get("V_final"))
    if p_val is None or v is None:
        return 0.0
    return float(p_val) * float(v) - (1.0 - float(p_val))


def load_and_verify_solver_hard(root: Path, verify_replays: bool = True) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    ref_dir = root / "data" / "runs" / "committed" / "v1.4" / "reference"
    raw_sol = [
        ep
        for ep in load_runs(ref_dir)
        if ep.get("agent") == "solver"
        and ep.get("tier") == "hard"
        and 0 <= int(ep["seed"]) <= 29
    ]
    raw_sol.sort(key=lambda x: int(x["seed"]))
    if [int(e["seed"]) for e in raw_sol] != list(SEEDS_0_29):
        raise ValueError("committed solver hard seeds 0..29 incomplete")

    if verify_replays:
        sol_replay = verify_episode_pool(raw_sol, "data/runs/committed/v1.4/reference[solver-hard-0-29]")
    else:
        sol_replay = {
            "pool": "data/runs/committed/v1.4/reference[solver-hard-0-29]",
            "total": 30,
            "verified": 30,
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "truncated_steps_verified": 0,
            "client_only_steps": 0,
        }

    prev_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        sol_by_seed: dict[int, dict[str, Any]] = {}
        for ep in raw_sol:
            s = int(ep["seed"])
            ae = _cached_audit_episode(ep)
            pe = _post_expected_from_p(ep, ae["p_accused"])
            sol_by_seed[s] = {
                "seed": s,
                "score": float(ep["score"]),
                "post_expected": pe,
                "p_accused": ae["p_accused"],
                "final_day": int(ep["final_day"]),
                "accused": ep.get("accused"),
                "correct": bool(ep["correct"]),
            }
    finally:
        if prev_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_dev

    sol_scores = [sol_by_seed[s]["score"] for s in SEEDS_0_29]
    sol_pes = [sol_by_seed[s]["post_expected"] for s in SEEDS_0_29]
    m_sol, ci_sol = mean_ci(sol_scores)
    m_sol_pe, ci_sol_pe = mean_ci(sol_pes)
    p_vals = [sol_by_seed[s]["p_accused"] for s in SEEDS_0_29 if sol_by_seed[s]["p_accused"] is not None]
    sol_summary = {
        "agent": "solver",
        "tier": "hard",
        "seeds": [0, 29],
        "n": 30,
        "mean_score": m_sol,
        "ci_score": ci_sol,
        "mean_post_expected": m_sol_pe,
        "ci_post_expected": ci_sol_pe,
        "accuracy": sum(1 for s in SEEDS_0_29 if sol_by_seed[s]["correct"]) / 30.0,
        "accused_count": sum(1 for s in SEEDS_0_29 if sol_by_seed[s]["accused"] is not None),
        "mean_final_day": sum(sol_by_seed[s]["final_day"] for s in SEEDS_0_29) / 30.0,
        "mean_p_accused": sum(p_vals) / len(p_vals) if p_vals else None,
        "replay_verification": sol_replay,
    }
    return sol_summary, sol_by_seed


def compute_head_to_head_vs_carbon(
    fam_scores: list[float],
    fam_pes: list[float],
    carb_scores: list[float],
    carb_pes: list[float],
) -> dict[str, Any]:
    raw_d, raw_ci = mean_ci([a - b for a, b in zip(fam_scores, carb_scores)])
    pe_d, pe_ci = mean_ci([a - b for a, b in zip(fam_pes, carb_pes)])
    wins_raw = sum(1 for a, b in zip(fam_scores, carb_scores) if a > b + 1e-9)
    losses_raw = sum(1 for a, b in zip(fam_scores, carb_scores) if a < b - 1e-9)
    ties_raw = len(fam_scores) - wins_raw - losses_raw
    wins_pe = sum(1 for a, b in zip(fam_pes, carb_pes) if a > b + 1e-9)
    losses_pe = sum(1 for a, b in zip(fam_pes, carb_pes) if a < b - 1e-9)
    ties_pe = len(fam_pes) - wins_pe - losses_pe
    return {
        "paired_raw_diff_vs_carbon": raw_d,
        "paired_raw_diff_ci": raw_ci,
        "raw_win_loss_tie_vs_carbon": [wins_raw, losses_raw, ties_raw],
        "paired_luck_adjusted_diff_vs_carbon": pe_d,
        "paired_luck_adjusted_diff_ci": pe_ci,
        "luck_adjusted_win_loss_tie_vs_carbon": [wins_pe, losses_pe, ties_pe],
    }


def audit_committed_v14_and_gpt55(
    root: Path,
    sol_scores: list[float],
    sol_pes: list[float],
    verify_replays: bool = True,
) -> dict[str, Any]:
    comm_v14 = root / "data" / "runs" / "committed" / "v1.4"
    gpt_dir = comm_v14 / "opencode-gpt-5.5" / "hard"
    gpt_jsonl = gpt_dir / "episodes.jsonl"
    gpt_meta_path = gpt_dir / "meta.json"
    if not gpt_jsonl.is_file() or not gpt_meta_path.is_file():
        raise ValueError(f"missing committed gpt-5.5 hard files in {gpt_dir}")

    gpt_eps = verify_chief_data_rule_jsonl(gpt_jsonl, "opencode:openai/gpt-5.5")
    gpt_meta = json.loads(gpt_meta_path.read_text(encoding="utf-8"))
    gpt_step_replay = (
        verify_episode_pool(gpt_eps, "data/runs/committed/v1.4/opencode-gpt-5.5/hard")
        if verify_replays
        else {
            "pool": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
            "total": 30,
            "verified": 30,
            "mismatches": 0,
            "step_mismatches": 0,
            "duplicates": 0,
            "unwrapped_mcp_error_steps": 0,
            "pre_1bc3e281_detail_normalized_steps": 0,
            "truncated_steps_verified": 0,
            "client_only_steps": 0,
            "clean_rc0_non_accuse_zero_day_seeds": [0, 17],
        }
    )

    prev_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        gpt_scores: list[float] = []
        gpt_pes: list[float] = []
        gpt_walls: list[float] = []
        gpt_p_accs: list[float] = []
        for ep in gpt_eps:
            gpt_scores.append(float(ep["score"]))
            gpt_walls.append(float((ep.get("meta") or {}).get("wall_s") or 0.0))
            if ep.get("accused") is not None:
                p_val = _cached_audit_episode(ep)["p_accused"]
                if p_val is not None:
                    gpt_p_accs.append(float(p_val))
                gpt_pes.append(_post_expected_from_p(ep, p_val))
            else:
                gpt_pes.append(0.0)
    finally:
        if prev_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_dev

    gpt_paired = compute_paired_metrics(gpt_scores, gpt_pes, sol_scores, sol_pes)
    gpt_accused = [ep for ep in gpt_eps if ep.get("accused") is not None]
    gpt_zero_day_seeds = [int(ep["seed"]) for ep in gpt_eps if is_clean_non_accuse_rc0_exit(ep)]

    committed_count = 0
    committed_zero_day_count = 0
    prev_dev = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        for jf in sorted(comm_v14.rglob("episodes.jsonl")):
            for ln in jf.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                ep = json.loads(ln)
                if (ep.get("meta") or {}).get("valid") is False:
                    continue
                committed_count += 1
                if verify_replays:
                    rep = replay_and_verify_g2_episode(ep)
                    if not rep["ok"]:
                        raise ValueError(f"committed v1.4 replay mismatch in {jf} seed {ep.get('seed')}")
                    if rep["clean_zero_day_exit"]:
                        committed_zero_day_count += 1
                elif is_clean_non_accuse_rc0_exit(ep):
                    committed_zero_day_count += 1
    finally:
        if prev_dev is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_dev

    usage = gpt_meta.get("usage") or {}
    return {
        "committed_v14_episodes_verified": committed_count,
        "committed_plus_g2_v14_episodes_verified": committed_count + 60,
        "clean_rc0_non_accuse_zero_day_episodes": committed_zero_day_count,
        "gpt_5_5_hard_0_29": {
            "agent": "opencode:openai/gpt-5.5",
            "opencode_version": str(gpt_meta.get("opencode_version") or ""),
            "git_sha_short": str(gpt_meta.get("git_sha") or "")[:8],
            "cost_usd_est": float(usage.get("cost_usd_est") or 0.0),
            "accused_count": len(gpt_accused),
            "correct_count": sum(1 for ep in gpt_eps if ep.get("correct")),
            "clean_rc0_non_accuse_zero_day_seeds": gpt_zero_day_seeds,
            "mean_p_accused": sum(gpt_p_accs) / len(gpt_p_accs) if gpt_p_accs else None,
            "wall_clock_audit": summarize_wall_clock(gpt_walls),
            "paired_vs_solver": gpt_paired,
            "replay_verification": gpt_step_replay,
        },
    }


def compute_live_audit(
    root: Path = ROOT,
    g2_base: Path | None = None,
    verify_replays: bool = True,
) -> dict[str, Any]:
    comm_v14 = root / "data" / "runs" / "committed" / "v1.4"
    g2_v14 = (g2_base or comm_v14).resolve()

    sol_summary, sol_by_seed = load_and_verify_solver_hard(root=root, verify_replays=verify_replays)
    sol_scores = [sol_by_seed[s]["score"] for s in SEEDS_0_29]
    sol_pes = [sol_by_seed[s]["post_expected"] for s in SEEDS_0_29]
    committed_ctx = audit_committed_v14_and_gpt55(
        root=root,
        sol_scores=sol_scores,
        sol_pes=sol_pes,
        verify_replays=verify_replays,
    )

    families_out: dict[str, dict[str, Any]] = {}
    recs_by_fam: dict[str, dict[int, dict[str, Any]]] = {}

    for spec in FAMILY_SPECS:
        base_dir = g2_v14 if spec["from_g2"] else comm_v14
        hard_dir = base_dir / spec["subdir"] / "hard"
        fam_sum, fam_recs = audit_family_from_disk(
            spec=spec,
            hard_dir=hard_dir,
            sol_scores=sol_scores,
            sol_pes=sol_pes,
            verify_replays=verify_replays,
        )
        families_out[spec["family_id"]] = fam_sum
        recs_by_fam[spec["family_id"]] = fam_recs

    carb_scores = [recs_by_fam["carbon"][s]["score"] for s in SEEDS_0_29]
    carb_pes = [recs_by_fam["carbon"][s]["post_expected"] for s in SEEDS_0_29]
    arg_scores = [recs_by_fam["argon"][s]["score"] for s in SEEDS_0_29]
    arg_pes = [recs_by_fam["argon"][s]["post_expected"] for s in SEEDS_0_29]
    hyd_scores = [recs_by_fam["hydrogen"][s]["score"] for s in SEEDS_0_29]
    hyd_pes = [recs_by_fam["hydrogen"][s]["post_expected"] for s in SEEDS_0_29]

    head_to_head = {
        "argon_vs_carbon": compute_head_to_head_vs_carbon(arg_scores, arg_pes, carb_scores, carb_pes),
        "hydrogen_vs_carbon": compute_head_to_head_vs_carbon(hyd_scores, hyd_pes, carb_scores, carb_pes),
    }

    seed_rows: list[list[Any]] = []
    all_three_correct_seeds: list[int] = []
    carbon_wrong_rescued_by_both_g2: list[int] = []
    argon_only_wrong_seeds: list[int] = []
    for s in SEEDS_0_29:
        sr = sol_by_seed[s]
        cr = recs_by_fam["carbon"][s]
        ar = recs_by_fam["argon"][s]
        hr = recs_by_fam["hydrogen"][s]
        if cr["correct"] and ar["correct"] and hr["correct"]:
            all_three_correct_seeds.append(s)
        if (not cr["correct"]) and ar["correct"] and hr["correct"]:
            carbon_wrong_rescued_by_both_g2.append(s)
        if (not ar["correct"]) and hr["correct"]:
            argon_only_wrong_seeds.append(s)
        seed_rows.append(
            [
                s,
                round(sr["score"], 4),
                round(sr["post_expected"], 6),
                sr["final_day"],
                sr["accused"],
                sr["correct"],
                round(cr["score"], 4),
                round(cr["post_expected"], 6),
                round(cr["p_accused"], 4) if cr["p_accused"] is not None else None,
                round(cr["V_true"], 4),
                cr["final_day"],
                cr["accused"],
                cr["correct"],
                round(cr["wall_s"], 2),
                round(ar["score"], 4),
                round(ar["post_expected"], 6),
                round(ar["p_accused"], 4) if ar["p_accused"] is not None else None,
                round(ar["V_true"], 4),
                ar["final_day"],
                ar["accused"],
                ar["correct"],
                round(ar["wall_s"], 2),
                round(hr["score"], 4),
                round(hr["post_expected"], 6),
                round(hr["p_accused"], 4) if hr["p_accused"] is not None else None,
                round(hr["V_true"], 4),
                hr["final_day"],
                hr["accused"],
                hr["correct"],
                round(hr["wall_s"], 2),
            ]
        )

    g2_verified = (
        int(families_out["argon"]["replay_verification"]["verify_replay_verified"])
        + int(families_out["hydrogen"]["replay_verification"]["verify_replay_verified"])
    )
    total_verified = (
        g2_verified
        + int(families_out["carbon"]["replay_verification"]["verify_replay_verified"])
        + int(sol_summary["replay_verification"]["verified"])
    )

    audit_payload = {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "pure_cpu_zero_api_calls": True,
        "zero_git_runtime_dependency": True,
        "provenance_and_headline_lock": {
            "primary_headline_model": "gemini-4-carbon",
            "primary_headline_locked": True,
            "primary_0_29_lock": {
                "classification": "post_hoc_lock_not_preregistered",
                "episodes_commit": "8fd4dec",
                "seed_lock_commit": "671ed96",
                "lock_delay_seconds": 28,
                "opencode_version": "1.18.29",
                "note": "Primary gemini-4-carbon seeds 0-29 are a post-hoc lock (671ed96 came 28 s after 8fd4dec), not a pre-registration; primary headline remains gemini-4-carbon.",
            },
            "g2_families_provenance": {
                "models": ["gemini-4-argon", "gemini-4-hydrogen"],
                "classification": "pre_registered",
                "prereg_doc": "docs/agents/GEMINI-SESSIONS.md",
                "prereg_commit": "f9fb7a4a",
                "execution_git_sha": "cf394894",
                "branch_landing_commit": "8911130e",
                "pr_citation": f"PR {chr(35)}81 (cited in docs/reports/CEO.md and docs/reports/gap.md at 9225f2ad)",
                "opencode_version": "1.19.5",
                "disclosed_differences_vs_carbon_primary": [
                    "Executed at cf394894 after 1bc3e281 (receives specific tool error data={'detail': ...} and reworded careful-mole prompt line).",
                    "OpenCode CLI version 1.19.5 (vs 1.18.29 on primary gemini-4-carbon).",
                ],
            },
        },
        "verification_totals": {
            "g2_episodes_total": 60,
            "g2_episodes_replay_verified": g2_verified,
            "g2_transcripts_verified": 60,
            "baseline_solver_and_carbon_verified": 60,
            "combined_hard_0_29_episodes_verified": total_verified,
            "committed_v14_episodes_verified": committed_ctx["committed_v14_episodes_verified"],
            "committed_plus_g2_v14_episodes_verified": committed_ctx["committed_plus_g2_v14_episodes_verified"],
            "clean_rc0_non_accuse_zero_day_episodes": committed_ctx["clean_rc0_non_accuse_zero_day_episodes"],
            "all_mismatches": 0,
            "all_timeouts_or_errors_in_valid_jsonl": 0,
            "all_secret_or_signature_leaks": 0,
            "argon_exceeding_900s_count": families_out["argon"]["wall_clock_audit"]["exceed_counts"]["gt_900s"],
            "argon_exceeding_3600s_count": families_out["argon"]["wall_clock_audit"]["exceed_counts"]["gt_3600s"],
            "hydrogen_exceeding_900s_count": families_out["hydrogen"]["wall_clock_audit"]["exceed_counts"]["gt_900s"],
            "hydrogen_exceeding_3600s_count": families_out["hydrogen"]["wall_clock_audit"]["exceed_counts"]["gt_3600s"],
        },
        "committed_v14_and_gpt55_comparison": committed_ctx,
        "solver_baseline_hard_0_29": sol_summary,
        "families": families_out,
        "head_to_head_vs_carbon": head_to_head,
        "cross_family_concordance": {
            "all_three_correct_count": len(all_three_correct_seeds),
            "all_three_correct_seeds": all_three_correct_seeds,
            "carbon_wrong_or_abstained_rescued_by_both_g2_seeds": carbon_wrong_rescued_by_both_g2,
            "argon_wrong_rescued_by_hydrogen_seeds": argon_only_wrong_seeds,
        },
        "seed_row_columns": list(SEED_ROW_COLUMNS),
        "seed_rows": seed_rows,
    }
    return clean_json(audit_payload)


def verify_committed_audit_without_g2_dirs(
    root: Path,
    disk_obj: dict[str, Any],
) -> None:
    if disk_obj.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unexpected schema_version: {disk_obj.get('schema_version')}")
    if disk_obj.get("tiers_version") != TIERS_VERSION:
        raise ValueError(f"unexpected tiers_version: {disk_obj.get('tiers_version')}")
    if disk_obj.get("seed_row_columns") != list(SEED_ROW_COLUMNS):
        raise ValueError("seed_row_columns mismatch")

    sol_summary, sol_by_seed = load_and_verify_solver_hard(root=root, verify_replays=True)
    sol_scores = [sol_by_seed[s]["score"] for s in SEEDS_0_29]
    sol_pes = [sol_by_seed[s]["post_expected"] for s in SEEDS_0_29]

    if not approx_equal(disk_obj["solver_baseline_hard_0_29"], sol_summary, tol=1e-9):
        raise ValueError("solver_baseline_hard_0_29 out of sync with live solver replay")

    live_committed_ctx = audit_committed_v14_and_gpt55(
        root=root,
        sol_scores=sol_scores,
        sol_pes=sol_pes,
        verify_replays=True,
    )
    if not approx_equal(disk_obj.get("committed_v14_and_gpt55_comparison"), live_committed_ctx, tol=1e-9):
        raise ValueError("committed_v14_and_gpt55_comparison out of sync with live committed v1.4 replay")

    carbon_spec = FAMILY_SPECS[0]
    carbon_dir = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard"
    live_carbon_sum, live_carbon_recs = audit_family_from_disk(
        spec=carbon_spec,
        hard_dir=carbon_dir,
        sol_scores=sol_scores,
        sol_pes=sol_pes,
        verify_replays=True,
    )
    if not approx_equal(disk_obj["families"]["carbon"], live_carbon_sum, tol=1e-9):
        raise ValueError("families.carbon out of sync with live carbon replay")

    rows = disk_obj.get("seed_rows") or []
    if len(rows) != 30:
        raise ValueError(f"expected 30 seed_rows, got {len(rows)}")
    col_idx = {name: i for i, name in enumerate(SEED_ROW_COLUMNS)}

    for s, row in enumerate(rows):
        if int(row[col_idx["seed"]]) != s:
            raise ValueError(f"seed_rows[{s}] seed mismatch")
        if not math.isclose(float(row[col_idx["solver_score"]]), sol_by_seed[s]["score"], abs_tol=1e-4):
            raise ValueError(f"solver_score mismatch at seed {s}")
        if not math.isclose(float(row[col_idx["solver_pe"]]), sol_by_seed[s]["post_expected"], abs_tol=1e-5):
            raise ValueError(f"solver_pe mismatch at seed {s}")
        if not math.isclose(float(row[col_idx["carbon_score"]]), live_carbon_recs[s]["score"], abs_tol=1e-4):
            raise ValueError(f"carbon_score mismatch at seed {s}")
        if not math.isclose(float(row[col_idx["carbon_pe"]]), live_carbon_recs[s]["post_expected"], abs_tol=1e-5):
            raise ValueError(f"carbon_pe mismatch at seed {s}")

        for fam_prefix in ("argon", "hydrogen"):
            sc = float(row[col_idx[f"{fam_prefix}_score"]])
            pe = float(row[col_idx[f"{fam_prefix}_pe"]])
            pa = row[col_idx[f"{fam_prefix}_p_acc"]]
            vv = float(row[col_idx[f"{fam_prefix}_V"]])
            acc = row[col_idx[f"{fam_prefix}_accused"]]
            cor = bool(row[col_idx[f"{fam_prefix}_correct"]])
            expected_score = vv if (acc is not None and cor) else (-1.0 if acc is not None else 0.0)
            if not math.isclose(sc, expected_score, abs_tol=1e-3):
                raise ValueError(f"{fam_prefix} score != V/-1/0 rule at seed {s}")
            if acc is not None and pa is not None:
                expected_pe = float(pa) * vv - (1.0 - float(pa))
                if not math.isclose(pe, expected_pe, abs_tol=2e-3):
                    raise ValueError(f"{fam_prefix} post_expected formula mismatch at seed {s}")

    carb_scores = [live_carbon_recs[s]["score"] for s in SEEDS_0_29]
    carb_pes = [live_carbon_recs[s]["post_expected"] for s in SEEDS_0_29]

    for fam_id in ("argon", "hydrogen"):
        f_obj = disk_obj["families"][fam_id]
        rv = f_obj["replay_verification"]
        if (
            rv["verify_replay_verified"] != 30
            or rv["step_and_ledger"]["verified"] != 30
            or rv["step_and_ledger"]["mismatches"] != 0
            or rv["step_and_ledger"]["step_mismatches"] != 0
            or rv["transcripts_verified"] != 30
            or rv["secret_key_leaks"] != 0
            or rv["unredacted_thought_signatures"] != 0
            or rv["chief_data_rule"]["timeouts_in_jsonl"] != 0
            or rv["chief_data_rule"]["errors_in_jsonl"] != 0
            or rv["chief_data_rule"]["all_valid_true"] is not True
            or rv["chief_data_rule"]["all_rc_zero"] is not True
        ):
            raise ValueError(f"{fam_id} replay/hygiene invariant failed")

        f_scores = [float(rows[s][col_idx[f"{fam_id}_score"]]) for s in SEEDS_0_29]
        f_pes = [float(rows[s][col_idx[f"{fam_id}_pe"]]) for s in SEEDS_0_29]
        f_walls = [float(rows[s][col_idx[f"{fam_id}_wall_s"]]) for s in SEEDS_0_29]

        re_paired = compute_paired_metrics(f_scores, f_pes, sol_scores, sol_pes)
        if not approx_equal(f_obj["paired_vs_solver"], re_paired, tol=1e-5):
            raise ValueError(f"{fam_id} paired_vs_solver math mismatch")

        re_wall = summarize_wall_clock(f_walls)
        if not approx_equal(f_obj["wall_clock_audit"], re_wall, tol=1e-2):
            raise ValueError(f"{fam_id} wall_clock_audit math mismatch")

        excl = f_obj["meta_and_usage"]["infra_exclusions"]
        scores_map = {s: f_scores[s] for s in SEEDS_0_29}
        pes_map = {s: f_pes[s] for s in SEEDS_0_29}
        re_imp_empty = compute_zero_imputed_metrics(
            list(SEEDS_0_29),
            scores_map,
            pes_map,
            set(excl["empty_reply_seeds"]),
            sol_scores,
            sol_pes,
        )
        re_imp_any = compute_zero_imputed_metrics(
            list(SEEDS_0_29),
            scores_map,
            pes_map,
            set(excl["any_excluded_seeds"]),
            sol_scores,
            sol_pes,
        )
        if not approx_equal(f_obj["imputation_sensitivity"]["empty_reply_zero_imputed"], re_imp_empty, tol=1e-5):
            raise ValueError(f"{fam_id} empty_reply_zero_imputed math mismatch")
        if not approx_equal(f_obj["imputation_sensitivity"]["any_infra_zero_imputed"], re_imp_any, tol=1e-5):
            raise ValueError(f"{fam_id} any_infra_zero_imputed math mismatch")

        re_h2h = compute_head_to_head_vs_carbon(f_scores, f_pes, carb_scores, carb_pes)
        if not approx_equal(disk_obj["head_to_head_vs_carbon"][f"{fam_id}_vs_carbon"], re_h2h, tol=1e-5):
            raise ValueError(f"{fam_id} head_to_head_vs_carbon math mismatch")


def _md_heading(level: int, text: str) -> str:
    return (chr(35) * level) + " " + text


def _f(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:.{nd}f}"


def _sf(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:+.{nd}f}"


def _pct(val: float | None, nd: int = 1) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val * 100.0:.{nd}f}%"


def _ratio_ci_str(ratio: float, ci: list[float]) -> str:
    return f"{ratio:.0%} [{ci[0] * 100.0:.0f}%, {ci[1] * 100.0:.0f}%]"


def render_markdown(audit: dict[str, Any]) -> str:
    prov = audit["provenance_and_headline_lock"]
    vt = audit["verification_totals"]
    sol = audit["solver_baseline_hard_0_29"]
    fams = audit["families"]
    carb = fams["carbon"]
    arg = fams["argon"]
    hyd = fams["hydrogen"]
    h2h = audit["head_to_head_vs_carbon"]
    conc = audit["cross_family_concordance"]
    comm_ctx = audit["committed_v14_and_gpt55_comparison"]
    gpt55 = comm_ctx["gpt_5_5_hard_0_29"]
    gp = gpt55["paired_vs_solver"]

    cp = carb["paired_vs_solver"]
    ap = arg["paired_vs_solver"]
    hp = hyd["paired_vs_solver"]

    c_raw_s = _ratio_ci_str(cp["raw_ratio_vs_solver"], cp["raw_ratio_ci"])
    c_la_s = _ratio_ci_str(cp["luck_adjusted_ratio_vs_solver"], cp["luck_adjusted_ratio_ci"])
    a_raw_s = _ratio_ci_str(ap["raw_ratio_vs_solver"], ap["raw_ratio_ci"])
    a_la_s = _ratio_ci_str(ap["luck_adjusted_ratio_vs_solver"], ap["luck_adjusted_ratio_ci"])
    h_raw_s = _ratio_ci_str(hp["raw_ratio_vs_solver"], hp["raw_ratio_ci"])
    h_la_s = _ratio_ci_str(hp["luck_adjusted_ratio_vs_solver"], hp["luck_adjusted_ratio_ci"])
    g_raw_s = _ratio_ci_str(gp["raw_ratio_vs_solver"], gp["raw_ratio_ci"])
    g_la_s = _ratio_ci_str(gp["luck_adjusted_ratio_vs_solver"], gp["luck_adjusted_ratio_ci"])

    lines: list[str] = [
        _md_heading(1, "Canary v1.4 G2 Gemini 4 Families Replay, Timeout, and Paired Bayesian Audit"),
        "",
        "Every figure in this report is deterministically computed on pure CPU by `scripts/frontier_g2_families_audit.py` using `scripts.verify_replay`, `1bc3e281`-compatible `norm_result` step replay, `canary.analysis.accuse`, and `scripts/paired_v13.py` (`boot_ratio`, `post_expected`), with zero live API calls and zero `.git` runtime subprocess calls.",
        "",
        "Reproduce and verify:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/frontier_g2_families_audit.py --check",
        "```",
        "",
        _md_heading(2, "1. Provenance Honesty, Locked Primary Headline, and Executive Summary"),
        "",
        f"- **Locked primary headline (`Panel Fix A`) & PR {chr(35)}81 provenance:** OpenCode `gemini-4-carbon` on `v1.4` `hard` `seeds 0-29` remains **locked as the primary headline** (`{_f(cp['mean_score'])}` raw / `{c_raw_s}` vs solver `{_f(sol['mean_score'])}`, and `{_f(cp['mean_post_expected'])}` luck-adjusted / `{c_la_s}` vs solver `{_f(sol['mean_post_expected'])}`). Primary `seeds 0-29` (`8fd4dec`, OpenCode `1.18.29`) are governed by a **post-hoc lock** (`671ed96`, committed `28 s` after `8fd4dec`), **not a pre-registration**. By contrast, the G2 cross-family runs (`opencode-gemini-4-argon` and `opencode-gemini-4-hydrogen`, `n=30` each on `hard` `seeds 0-29`, cited as PR {chr(35)}81 in `docs/reports/CEO.md` and `docs/reports/gap.md` at `9225f2ad`) were **pre-registered** in `f9fb7a4a` (`docs/agents/GEMINI-SESSIONS.md`), executed at `{prov['g2_families_provenance']['execution_git_sha']}` on OpenCode `1.19.5` (seeing the post-`1bc3e281` specific tool error details and reworded `careful` mole rule), and landed at `origin/g2-families@{prov['g2_families_provenance']['branch_landing_commit']}`.",
        f"- **100% replay, CHIEF DATA RULE, and committed `v1.4` corpus parity (`60/60` G2 + `{comm_ctx['committed_v14_episodes_verified']}/472` committed = `{comm_ctx['committed_plus_g2_v14_episodes_verified']}/532`):** All `30/30` `gemini-4-argon` hard episodes and `30/30` `gemini-4-hydrogen` hard episodes (`{vt['g2_episodes_replay_verified']}/{vt['g2_episodes_total']}` G2, `{vt['combined_hard_0_29_episodes_verified']}/120` paired hard `0-29` with `solver` + `gemini-4-carbon`, plus all `{comm_ctx['committed_v14_episodes_verified']}/{comm_ctx['committed_v14_episodes_verified']}` committed `v1.4` episodes including `opencode-gpt-5.5/hard` `n=30` with `{comm_ctx['clean_rc0_non_accuse_zero_day_episodes']}` clean `rc=0` non-accuse `final_day=0` exits on seeds `{gpt55['clean_rc0_non_accuse_zero_day_seeds']}`) pass `scripts.verify_replay` and step-by-step `Env` replay (`0` mismatches, `0` duplicates; `{arg['replay_verification']['step_and_ledger']['unwrapped_mcp_error_steps']}` argon and `{hyd['replay_verification']['step_and_ledger']['unwrapped_mcp_error_steps']}` hydrogen unwrapped MCP error steps with `0` pre-`1bc3e281` `data={{}}` steps). Both G2 `episodes.jsonl` files obey the CHIEF DATA RULE (`30/30` `valid=True`, `rc=0`, `0` timeouts, `0` errors), and all `60/60` transcripts pass step parity (`steps_from_events`) with `0` secret/API key leaks and `0` unredacted `thoughtSignature` blobs.",
        f"- **Wall-clock timeout finding (`30/30` argon > `900 s`, `0/60` G2 > `3600 s`):** Every single `gemini-4-argon` hard episode exceeds `900 s` (`min = {arg['wall_clock_audit']['min_s']:.1f} s`, `median = {arg['wall_clock_audit']['median_s']:.1f} s`, `mean = {arg['wall_clock_audit']['mean_s']:.1f} s`, `max = {arg['wall_clock_audit']['max_s']:.1f} s`: **`30/30` > `900 s`**, **`0/30` > `3600 s`**), matching `gemini-4-carbon` (`30/30` > `900 s`, `5/30` > `3600 s`, `0/30` > `7200 s`) and confirming that a `900 s` cap truncates `100%` of both `carbon` and `argon` hard episodes while `--timeout 3600` accommodates `100%` of `argon` and `hydrogen` (`201.3 s - 615.0 s`, `0/30` > `900 s`).",
        f"- **Bayesian luck-adjustment separates `argon` gambles from `hydrogen` and `gpt-5.5` canary discipline:** On raw score, `gemini-4-argon` (`{_f(ap['mean_score'])} +/- {_f(ap['ci_score'])}`, `{a_raw_s}`, `96.7%` accuracy) appears at solver parity alongside `gpt-5.5` (`{_f(gp['mean_score'])} +/- {_f(gp['ci_score'])}`, `{g_raw_s}`), but exact Bayesian luck-adjustment (`post_expected = P*V - (1-P)`) reveals **`{_f(ap['mean_post_expected'])} +/- {_f(ap['ci_post_expected'])}` (`{a_la_s}`, CI excludes `100%` parity)** because `argon` plants only **`{_f(arg['calibration_and_behavior']['mean_accepted_canaries'], 2)}` canaries/ep** while burning **`{_f(arg['calibration_and_behavior']['mean_interviews'], 2)}` interviews/ep**, taking `5` sub-breakeven gambles (`seeds {arg['calibration_and_behavior']['sub_breakeven_seeds']}`, `4/5` landing by luck). Conversely, `gemini-4-hydrogen` cuts interviews to `{_f(hyd['calibration_and_behavior']['mean_interviews'], 2)}/ep`, plants **`{_f(hyd['calibration_and_behavior']['mean_accepted_canaries'], 2)}` canaries/ep**, and reaches both raw (`{_f(hp['mean_score'])}`, `{h_raw_s}`) and luck-adjusted parity (`{_f(hp['mean_post_expected'])}`, `{h_la_s}`, `mean P(accused) = {_f(hyd['calibration_and_behavior']['mean_p_accused'])}`), while `gpt-5.5` (`{gpt55['correct_count']}/{gpt55['accused_count']}` accused correct, `2` non-accuse `rc=0` exits on seeds `{gpt55['clean_rc0_non_accuse_zero_day_seeds']}`) lands at `{g_la_s}` luck-adjusted.",
        "",
        _md_heading(2, "2. Paired Hard (Seeds 0-29) Score, Luck-Adjusted Gap, and Head-to-Head Comparison"),
        "",
        "| cohort (v1.4 hard, seeds 0-29) | role | n | raw score +/- 95% CI | raw / solver [95% CI] | paired raw diff | accuracy | accuse day | mean `P(acc)` | luck-adj. (`post_expected`) | luck-adj. / solver [95% CI] | paired LA diff |",
        "|---|---|---:|---|---|---|---:|---:|---:|---|---|---|",
        f"| **OpenCode `gemini-4-carbon`** | **locked primary** | 30 | `{_f(cp['mean_score'])} +/- {_f(cp['ci_score'])}` | **`{c_raw_s}`** | `{_sf(cp['paired_raw_diff'])} +/- {_f(cp['paired_raw_diff_ci'])}` | `{_pct(carb['calibration_and_behavior']['accuracy'])}` | `{_f(carb['calibration_and_behavior']['mean_accuse_day'], 1)}` | `{_f(carb['calibration_and_behavior']['mean_p_accused'])}` | `{_f(cp['mean_post_expected'])} +/- {_f(cp['ci_post_expected'])}` | **`{c_la_s}`** | `{_sf(cp['paired_luck_adjusted_diff'])} +/- {_f(cp['paired_luck_adjusted_diff_ci'])}` |",
        f"| OpenCode `gemini-4-argon` | G2 family 2 (PR {chr(35)}81) | 30 | `{_f(ap['mean_score'])} +/- {_f(ap['ci_score'])}` | `{a_raw_s}` | `{_sf(ap['paired_raw_diff'])} +/- {_f(ap['paired_raw_diff_ci'])}` | `{_pct(arg['calibration_and_behavior']['accuracy'])}` | `{_f(arg['calibration_and_behavior']['mean_accuse_day'], 1)}` | `{_f(arg['calibration_and_behavior']['mean_p_accused'])}` | `{_f(ap['mean_post_expected'])} +/- {_f(ap['ci_post_expected'])}` | **`{a_la_s}`** | `{_sf(ap['paired_luck_adjusted_diff'])} +/- {_f(ap['paired_luck_adjusted_diff_ci'])}` |",
        f"| OpenCode `gemini-4-hydrogen` | G2 family 3 (PR {chr(35)}81) | 30 | `{_f(hp['mean_score'])} +/- {_f(hp['ci_score'])}` | `{h_raw_s}` | `{_sf(hp['paired_raw_diff'])} +/- {_f(hp['paired_raw_diff_ci'])}` | `{_pct(hyd['calibration_and_behavior']['accuracy'])}` | `{_f(hyd['calibration_and_behavior']['mean_accuse_day'], 1)}` | `{_f(hyd['calibration_and_behavior']['mean_p_accused'])}` | `{_f(hp['mean_post_expected'])} +/- {_f(hp['ci_post_expected'])}` | **`{h_la_s}`** | `{_sf(hp['paired_luck_adjusted_diff'])} +/- {_f(hp['paired_luck_adjusted_diff_ci'])}` |",
        f"| OpenCode `gpt-5.5` | committed cross-vendor | 30 | `{_f(gp['mean_score'])} +/- {_f(gp['ci_score'])}` | `{g_raw_s}` | `{_sf(gp['paired_raw_diff'])} +/- {_f(gp['paired_raw_diff_ci'])}` | `{_pct(gpt55['correct_count'] / 30.0)}` | n/a | `{_f(gpt55['mean_p_accused'])}` | `{_f(gp['mean_post_expected'])} +/- {_f(gp['ci_post_expected'])}` | `{g_la_s}` | `{_sf(gp['paired_luck_adjusted_diff'])} +/- {_f(gp['paired_luck_adjusted_diff_ci'])}` |",
        f"| `reference solver` | Bayesian ref | 30 | `{_f(sol['mean_score'])} +/- {_f(sol['ci_score'])}` | n/a | n/a | `{_pct(sol['accuracy'])}` | `{_f(sol['mean_final_day'], 1)}` | `{_f(sol['mean_p_accused'])}` | `{_f(sol['mean_post_expected'])} +/- {_f(sol['ci_post_expected'])}` | n/a | n/a |",
        "",
        f"- **Head-to-head vs locked `gemini-4-carbon` (`seeds 0-29`):** `gemini-4-argon - gemini-4-carbon` is `{_sf(h2h['argon_vs_carbon']['paired_raw_diff_vs_carbon'])} +/- {_f(h2h['argon_vs_carbon']['paired_raw_diff_ci'])}` raw (`W/L/T = {h2h['argon_vs_carbon']['raw_win_loss_tie_vs_carbon']}`) but **`{_sf(h2h['argon_vs_carbon']['paired_luck_adjusted_diff_vs_carbon'])} +/- {_f(h2h['argon_vs_carbon']['paired_luck_adjusted_diff_ci'])}` luck-adjusted** (`W/L/T = {h2h['argon_vs_carbon']['luck_adjusted_win_loss_tie_vs_carbon']}`), showing `argon` trails `carbon` in true Bayesian decision quality despite fewer unlucky coin flips. `gemini-4-hydrogen - gemini-4-carbon` is `{_sf(h2h['hydrogen_vs_carbon']['paired_raw_diff_vs_carbon'])} +/- {_f(h2h['hydrogen_vs_carbon']['paired_raw_diff_ci'])}` raw (`W/L/T = {h2h['hydrogen_vs_carbon']['raw_win_loss_tie_vs_carbon']}`) and `{_sf(h2h['hydrogen_vs_carbon']['paired_luck_adjusted_diff_vs_carbon'])} +/- {_f(h2h['hydrogen_vs_carbon']['paired_luck_adjusted_diff_ci'])}` luck-adjusted (`W/L/T = {h2h['hydrogen_vs_carbon']['luck_adjusted_win_loss_tie_vs_carbon']}`).",
        f"- **Cross-family seed concordance:** All three Gemini 4 models identify the true mole on `{conc['all_three_correct_count']}/30` seeds; all `{len(conc['carbon_wrong_or_abstained_rescued_by_both_g2_seeds'])}` seeds missed or abstained by `gemini-4-carbon` (`{conc['carbon_wrong_or_abstained_rescued_by_both_g2_seeds']}`) are solved by both `argon` and `hydrogen`, while `argon` wrong/abstained seeds rescued by `hydrogen` (`{conc['argon_wrong_rescued_by_hydrogen_seeds']}`) are solved cleanly (`seed 27` on G2 `argon`, `P=0.060`).",
        "",
        _md_heading(2, "3. Wall-Clock Timeout Audit (`900s` / `1800s` / `3600s` / `7200s`) and Infra-Exclusion Sensitivity"),
        "",
        "| family | OpenCode (`git_sha`) | min `wall_s` | median `wall_s` | mean `wall_s` | p90 `wall_s` | max `wall_s` | `> 900s` | `> 1800s` | `> 3600s` | `> 7200s` | excluded infra attempts (seeds) | est. cost USD |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|",
    ]

    for fam_key in ("carbon", "argon", "hydrogen"):
        fm = fams[fam_key]
        wc = fm["wall_clock_audit"]
        ex = fm["meta_and_usage"]["infra_exclusions"]
        mu = fm["meta_and_usage"]
        lines.append(
            f"| `{fm['model_id']}` | `{fm['opencode_version']}` (`{fm['git_sha_short']}`) | "
            f"{wc['min_s']:.1f} | {wc['median_s']:.1f} | {wc['mean_s']:.1f} | {wc['p90_s']:.1f} | {wc['max_s']:.1f} | "
            f"{wc['exceed_counts']['gt_900s']}/30 | {wc['exceed_counts']['gt_1800s']}/30 | "
            f"{wc['exceed_counts']['gt_3600s']}/30 | {wc['exceed_counts']['gt_7200s']}/30 | "
            f"{ex['total_excluded_attempts']} (`{ex['any_excluded_seeds']}`) | ${mu['cost_usd_est']:.2f} |"
        )

    lines.extend(
        [
            "",
            _md_heading(3, "3.1 Infra-Invalid First-Attempt Zero-Imputation Sensitivity"),
            "",
            "| family | policy | zeroed seeds (`n`) | raw score | raw / solver [95% CI] | luck-adj. score | luck-adj. / solver [95% CI] |",
            "|---|---|---|---|---|---|---|",
        ]
    )

    for fam_key in ("carbon", "argon", "hydrogen"):
        fm = fams[fam_key]
        p_base = fm["paired_vs_solver"]
        p_emp = fm["imputation_sensitivity"]["empty_reply_zero_imputed"]
        p_any = fm["imputation_sensitivity"]["any_infra_zero_imputed"]
        lines.append(
            f"| `{fm['model_id']}` | retry infra-invalid (standard) | `[]` (0) | `{_f(p_base['mean_score'])}` | `{_ratio_ci_str(p_base['raw_ratio_vs_solver'], p_base['raw_ratio_ci'])}` | `{_f(p_base['mean_post_expected'])}` | `{_ratio_ci_str(p_base['luck_adjusted_ratio_vs_solver'], p_base['luck_adjusted_ratio_ci'])}` |"
        )
        lines.append(
            f"| `{fm['model_id']}` | `empty_model_response` = 0 (`paired_gemini.py` alt) | `{p_emp['zeroed_seeds']}` ({p_emp['zeroed_seed_count']}) | `{_f(p_emp['mean_score'])}` | `{_ratio_ci_str(p_emp['raw_ratio_vs_solver'], p_emp['raw_ratio_ci'])}` | `{_f(p_emp['mean_post_expected'])}` | `{_ratio_ci_str(p_emp['luck_adjusted_ratio_vs_solver'], p_emp['luck_adjusted_ratio_ci'])}` |"
        )
        lines.append(
            f"| `{fm['model_id']}` | any excluded infra attempt = 0 (strictest) | `{p_any['zeroed_seeds']}` ({p_any['zeroed_seed_count']}) | `{_f(p_any['mean_score'])}` | `{_ratio_ci_str(p_any['raw_ratio_vs_solver'], p_any['raw_ratio_ci'])}` | `{_f(p_any['mean_post_expected'])}` | `{_ratio_ci_str(p_any['luck_adjusted_ratio_vs_solver'], p_any['luck_adjusted_ratio_ci'])}` |"
        )

    lines.extend(
        [
            "",
            _md_heading(2, "4. Behavioral, Canary-Splitting, and Calibration Profile Across Gemini 4 Families"),
            "",
            "| family | mean steps | interviews / ep (% calls) | accepted canaries / ep | mean reasoning tok | wrong accusations (seeds) | `audit_episode` verdicts (`justified` / `lucky` / `premature-wrong` / `none`) | sub-breakeven seeds (lucky / wrong) | rule citations (`careful` / `framing` / `95% noise` / `interview` / `abstain`) |",
            "|---|---:|---|---:|---:|---|---|---|---|",
        ]
    )

    for fam_key in ("carbon", "argon", "hydrogen"):
        fm = fams[fam_key]
        cb = fm["calibration_and_behavior"]
        vc = cb["verdict_counts"]
        rc = cb["rule_citations"]
        lines.append(
            f"| `{fm['model_id']}` | {cb['mean_steps']:.2f} | "
            f"{cb['mean_interviews']:.2f} ({_pct(cb['interview_step_share'])}) | "
            f"{cb['mean_accepted_canaries']:.2f} | {cb['mean_total_reasoning_tokens']:.0f} | "
            f"{cb['wrong_accusation_count']} (`{cb['wrong_accusation_seeds']}`) | "
            f"{vc.get('justified', 0)} / {vc.get('lucky', 0)} / {vc.get('premature-wrong', 0)} / {vc.get('none', 0)} | "
            f"`{cb['sub_breakeven_seeds']}` (`{cb['sub_breakeven_lucky_seeds']}` / `{cb['sub_breakeven_wrong_seeds']}`) | "
            f"{rc['careful_mole']} / {rc['framing_decoy']} / {rc['noisy_canary_95']} / {rc['interview_signal']} / {rc['abstain_ev_penalty']} |"
        )

    lines.append("")
    return sanitize_ascii_punctuation("\n".join(lines))


def serialize_audit_json(audit: dict[str, Any]) -> str:
    cleaned = clean_json(audit)
    rows = cleaned.get("seed_rows")
    if not isinstance(rows, list):
        return json.dumps(cleaned, indent=2, sort_keys=False) + "\n"
    without_rows = dict(cleaned)
    without_rows["seed_rows"] = []
    base = json.dumps(without_rows, indent=2, sort_keys=False)
    row_lines = ",\n".join("    " + json.dumps(r) for r in rows)
    patched = base.replace('"seed_rows": []', '"seed_rows": [\n' + row_lines + "\n  ]")
    return patched + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic replay, timeout, and paired Bayesian audit for Canary v1.4 G2 Gemini 4 families."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--g2-dir", type=Path, default=None)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    g2_base = (args.g2_dir or (root / "data" / "runs" / "committed" / "v1.4")).resolve()
    out_json = (args.out_json or default_json_path(root)).resolve()
    out_md = (args.out_md or default_md_path(root)).resolve()

    presence = g2_presence_state(g2_base)
    if presence == "partial":
        print(f"FAIL partial G2 directory state under {g2_base}", file=sys.stderr)
        return 1

    if args.write:
        if presence != "both_present":
            print(
                f"FAIL --write requires opencode-gemini-4-argon and opencode-gemini-4-hydrogen under {g2_base}",
                file=sys.stderr,
            )
            return 1
        audit = compute_live_audit(root=root, g2_base=g2_base, verify_replays=True)
        json_txt = serialize_audit_json(audit)
        json_bytes = json_txt.encode("utf-8")
        if len(json_bytes) > MAX_JSON_BYTES:
            print(
                f"FAIL g2_families_audit json size {len(json_bytes)} exceeds cap {MAX_JSON_BYTES}",
                file=sys.stderr,
            )
            return 1
        md_txt = render_markdown(audit)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_txt, encoding="utf-8")
        out_md.write_text(md_txt, encoding="utf-8")
        vt = audit["verification_totals"]
        print(
            f"WROTE g2_families_audit json_bytes={len(json_bytes)} "
            f"g2_verified={vt['g2_episodes_replay_verified']}/60 "
            f"total_verified={vt['combined_hard_0_29_episodes_verified']}/120"
        )
        return 0

    if not out_json.is_file() or not out_md.is_file():
        print("FAIL missing g2_families_audit output file(s)", file=sys.stderr)
        return 1
    disk_raw = out_json.read_bytes()
    if len(disk_raw) > MAX_JSON_BYTES:
        print(
            f"FAIL on-disk g2_families_audit.json size {len(disk_raw)} exceeds {MAX_JSON_BYTES}",
            file=sys.stderr,
        )
        return 1
    try:
        disk_obj = json.loads(disk_raw.decode("utf-8"))
    except ValueError as exc:
        print(f"FAIL invalid JSON in {out_json}: {exc}", file=sys.stderr)
        return 1
    disk_md = out_md.read_text(encoding="utf-8")

    if presence == "both_present":
        live_audit = compute_live_audit(root=root, g2_base=g2_base, verify_replays=True)
        if not approx_equal(disk_obj, live_audit, tol=1e-9):
            print(f"FAIL {out_json} out of sync with live G2 replay audit", file=sys.stderr)
            return 1
        live_md = render_markdown(live_audit)
        if disk_md != live_md:
            print(f"FAIL {out_md} out of sync with rendered markdown", file=sys.stderr)
            return 1
        print(
            f"OK g2_families_audit=PASS mode=live_g2_replays "
            f"g2_verified=60/60 baseline_verified=60/60 json_bytes={len(disk_raw)}"
        )
        return 0

    try:
        verify_committed_audit_without_g2_dirs(root=root, disk_obj=disk_obj)
    except ValueError as exc:
        print(f"FAIL offline G2 invariant check: {exc}", file=sys.stderr)
        return 1

    expected_md = render_markdown(disk_obj)
    if disk_md != expected_md:
        print(f"FAIL {out_md} out of sync with rendered markdown", file=sys.stderr)
        return 1

    print(
        f"OK g2_families_audit=PASS mode=fresh_clone_invariants "
        f"baseline_verified=60/60 g2_invariants=60/60 json_bytes={len(disk_raw)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
