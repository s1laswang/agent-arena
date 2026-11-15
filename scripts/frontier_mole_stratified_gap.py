"""Pure-CPU mole-archetype and seed-difficulty stratification audit for Canary v1.4 cohorts.

    python scripts/frontier_mole_stratified_gap.py --write
    python scripts/frontier_mole_stratified_gap.py --check
"""
from __future__ import annotations

import argparse
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

from canary.analysis.gap import load_runs, mean_ci
from canary.env import Env
from canary.mole.dsl import DEFAULT_STRATEGY
from canary.rules import TIERS_VERSION, TRACKS, tier_params
from paired_v13 import _P_CACHE, post_expected

MAX_JSON_BYTES = 45_000
EXPECTED_COMMITTED_V14_EPISODES = 472
EXPECTED_REPLICATION_V14_EPISODES = 305
EXPECTED_COMBINED_V14_EPISODES = 777

ENV_TOOLS: tuple[str, ...] = (
    "status",
    "list_employees",
    "read_access_logs",
    "read_message",
    "search_messages",
    "list_documents",
    "check_leak_feed",
    "plant_canary",
    "interview",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)

_OC_TRUNC_RE = re.compile(
    r"\A\s*\.\.\.(\d+) bytes truncated\.\.\.\s+The tool call succeeded but the output was "
    r"truncated\. Full output saved to: "
)
_OC_NO_TOOL_PREFIX = "Model tried to call unavailable tool"

MOLE_ARCHETYPES: tuple[str, ...] = (
    "decoy_entangled",
    "deep_crowd_camouflage",
    "low_tempo_stealth",
    "high_tempo_exposed",
)

DEPT_STRATA: tuple[str, ...] = (
    "compact_dept",
    "standard_dept",
    "crowded_dept",
)

SOLVER_DIFFICULTY_STRATA: tuple[str, ...] = (
    "fast_isolation",
    "mid_horizon_isolation",
    "late_or_stalled_isolation",
)

SEED_PROFILE_COLUMNS: tuple[str, ...] = (
    "seed",
    "mole_id",
    "decoy_id",
    "mole_dept",
    "mole_dept_size",
    "mole_clearance",
    "clearance_peer_count",
    "same_dept_decoy",
    "decoy_doc_overlap_count",
    "decoy_doc_overlap_share",
    "mole_planned_docs",
    "mole_doc_share",
    "realized_doc_access_density",
    "passive_leak_count",
    "dept_narrow_day",
    "solver_accuse_day",
    "solver_final_day",
    "solver_score",
    "solver_post_expected",
    "solver_correct",
    "mole_archetype",
    "dept_stratum",
    "solver_difficulty_stratum",
)

SEED_PROFILE_ENUMS: dict[str, tuple[str, ...]] = {
    "mole_archetype": MOLE_ARCHETYPES,
    "dept_stratum": DEPT_STRATA,
    "solver_difficulty_stratum": SOLVER_DIFFICULTY_STRATA,
}

STRATUM_METRIC_COLUMNS: tuple[str, ...] = (
    "n",
    "raw",
    "luck",
    "acc",
    "abst",
    "day",
    "s_raw",
    "s_luck",
    "r_gap",
    "l_gap",
    "ratio",
)


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "mole_stratified_gap.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_mole_stratified_gap_v14.md"


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    if not gap_md.exists():
        return False
    return "gemini-3.5-flash" in gap_md.read_text(encoding="utf-8")


def _r(val: float | None, nd: int = 5) -> float | None:
    if val is None or math.isnan(val) or math.isinf(val):
        return None
    return round(float(val), nd)


def clean_json(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 5)
    if isinstance(obj, dict):
        return {str(k): clean_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = 1e-5) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if math.isnan(a) and math.isnan(b):
            return True
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def norm_result(want: Any) -> Any:
    if isinstance(want, dict) and isinstance(want.get("error"), str) and want["error"].startswith("{"):
        try:
            inner = json.loads(want["error"])
        except ValueError:
            return want
        if isinstance(inner, dict) and {"ok", "data", "error"} <= set(inner):
            return inner
    return want


def client_truncated_bytes(want: Any) -> int | None:
    if isinstance(want, dict) and set(want) == {"raw"} and isinstance(want["raw"], str):
        m = _OC_TRUNC_RE.match(want["raw"])
        if m:
            return int(m.group(1))
    return None


def is_client_only_step(step: dict[str, Any]) -> bool:
    res = step.get("result")
    return (
        step.get("tool") not in ENV_TOOLS
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith(_OC_NO_TOOL_PREFIX)
    )


def step_result_matches(raw_recorded: Any, replayed: dict[str, Any]) -> tuple[bool, dict[str, bool]]:
    flags = {
        "unwrapped_mcp_error": False,
        "detail_normalized": False,
        "truncated_checked": False,
    }
    trunc = client_truncated_bytes(raw_recorded)
    if trunc is not None:
        flags["truncated_checked"] = True
        return len(json.dumps(replayed).encode("utf-8")) == trunc, flags
    rec = norm_result(raw_recorded)
    if rec is not raw_recorded:
        flags["unwrapped_mcp_error"] = True
    if rec is None:
        return True, flags
    rep = replayed
    if (
        isinstance(rep, dict)
        and rep.get("ok") is False
        and isinstance(rep.get("data"), dict)
        and set(rep["data"]) == {"detail"}
        and isinstance(rec, dict)
        and not ("detail" in (rec.get("data") or {}))
    ):
        rep = {"ok": False, "data": {}, "error": rep.get("error")}
        flags["detail_normalized"] = True
    matched = rep == rec or _canon(rep) == _canon(rec)
    return matched, flags


def is_clean_non_accuse_rc0_exit(ep: dict[str, Any], env_done: bool | None = None) -> bool:
    meta = ep.get("meta") or {}
    done_ok = True if env_done is None else (not env_done)
    rc = meta.get("rc")
    fday = ep.get("final_day")
    end_reason = str(ep.get("end_reason") or "").lower()
    return (
        done_ok
        and meta.get("valid") is not False
        and not isinstance(rc, bool)
        and rc == 0
        and meta.get("error") is None
        and "timeout" not in end_reason
        and ep.get("accused") is None
        and not bool(ep.get("correct"))
        and abs(float(ep.get("score") if ep.get("score") is not None else 1.0)) < 1e-9
        and not isinstance(fday, bool)
        and fday == 0
    )


def replay_and_verify_episode(ep: dict[str, Any]) -> dict[str, Any]:
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
        rep = replay_and_verify_episode(ep)
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
                    "recorded_final_day": ep.get("final_day"),
                    "replay_final_day": rep["replay_final_day"],
                    "step_mismatches": rep["step_mismatches"],
                    "first_bad_step": rep["first_bad_step"],
                }
            )
    if duplicates:
        raise ValueError(f"duplicate episodes in {pool_name}: {duplicates}")
    if mismatches:
        raise ValueError(f"replay mismatches in {pool_name}: {mismatches}")
    return {
        "pool": pool_name,
        "total": len(episodes),
        "verified": len(episodes),
        "mismatches": 0,
        "step_mismatches": total_step_mismatches,
        "duplicates": 0,
        "pre_1bc3e281_detail_normalized_steps": total_detail_norm,
        "unwrapped_mcp_error_steps": total_unwrapped,
        "truncated_output_steps_verified": total_truncated,
        "client_only_steps": total_client_only,
        "clean_rc0_non_accuse_zero_day_seeds": sorted(clean_zero_day_seeds),
    }


def _tier_mole_genome(tier: str) -> dict[str, Any]:
    tp = tier_params(tier)
    n_depts = 5 if tier in ("hard", "hard_forge") else 4
    mean_dept = int(tp.n_employees) // n_depts
    return clean_json(
        {
            "tier": tier,
            "is_judge_track": tier in TRACKS,
            "mole_policy_name": DEFAULT_STRATEGY.name,
            "mole_dsl_rule_count": len(DEFAULT_STRATEGY.rules),
            "mole_dsl_default_leak_selector": DEFAULT_STRATEGY.default[0],
            "mole_dsl_default_frame_selector": DEFAULT_STRATEGY.default[1],
            "n_employees": int(tp.n_employees),
            "n_depts": n_depts,
            "mean_dept_size": float(tp.n_employees) / float(n_depts),
            "crowd_dept_threshold": mean_dept + 2,
            "n_days": int(tp.n_days),
            "p_leak": float(tp.p_leak),
            "expected_passive_leaks": float(tp.n_days) * float(tp.p_leak),
            "delay_choices": list(tp.delay_choices),
            "leak_window_days": int(tp.leak_window_days),
            "careful_mole": bool(tp.careful_mole),
            "fingerprint_accuracy": float(tp.fingerprint_accuracy),
            "decoy": bool(tp.decoy),
            "framing": bool(tp.framing),
            "framing_rate": float(tp.framing_rate),
            "framing_decoy_share": float(tp.framing_decoy_share),
            "log_rate_benign": float(tp.log_rate_benign),
            "log_rate_mole": float(tp.log_rate_mole),
            "p_after_hours_benign": float(tp.p_after_hours_benign),
            "p_after_hours_mole": float(tp.p_after_hours_mole),
            "access_constraints": bool(tp.access_constraints),
            "p_single_dept_recipients": float(tp.p_single_dept_recipients),
            "canaries_per_day": int(tp.canaries_per_day),
            "max_variants": int(tp.max_variants),
        }
    )


def classify_mole_archetype(
    tier: str,
    same_dept_decoy: bool,
    mole_dept_size: int,
    passive_leak_count: int,
) -> str:
    tp = tier_params(tier)
    n_depts = 5 if tier in ("hard", "hard_forge") else 4
    crowd_threshold = (int(tp.n_employees) // n_depts) + 2
    expected_leaks = float(tp.n_days) * float(tp.p_leak)
    if same_dept_decoy:
        return "decoy_entangled"
    if mole_dept_size >= crowd_threshold:
        return "deep_crowd_camouflage"
    if float(passive_leak_count) < expected_leaks:
        return "low_tempo_stealth"
    return "high_tempo_exposed"


def classify_dept_stratum(tier: str, mole_dept_size: int) -> str:
    if tier == "medium":
        if mole_dept_size <= 4:
            return "compact_dept"
        if mole_dept_size <= 6:
            return "standard_dept"
        return "crowded_dept"
    if mole_dept_size <= 8:
        return "compact_dept"
    if mole_dept_size <= 10:
        return "standard_dept"
    return "crowded_dept"


def classify_solver_difficulty(tier: str, solver_final_day: int) -> str:
    if tier == "medium":
        if solver_final_day <= 6:
            return "fast_isolation"
        if solver_final_day <= 9:
            return "mid_horizon_isolation"
        return "late_or_stalled_isolation"
    if solver_final_day <= 8:
        return "fast_isolation"
    if solver_final_day <= 12:
        return "mid_horizon_isolation"
    return "late_or_stalled_isolation"


def extract_seed_profile(
    tier: str,
    seed: int,
    solver_ep: dict[str, Any],
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    env = Env(tier, seed)
    w = env._world
    tp = env.p
    strat_obj = w.mole_strategy if w.mole_strategy is not None else DEFAULT_STRATEGY
    mole_policy = str(getattr(strat_obj, "name", "default_v0"))

    emp_map = {e.id: e for e in w.employees}
    m_emp = emp_map[w.mole]
    d_emp = emp_map[w.decoy] if w.decoy is not None else None
    dept_emps = [e for e in w.employees if e.dept == m_emp.dept]
    mole_dept_size = len(dept_emps)
    same_dept_decoy = bool(d_emp is not None and d_emp.dept == m_emp.dept)
    mole_clearance = int(m_emp.clearance) if m_emp.clearance is not None else None
    if tp.access_constraints:
        clearance_peer_count = sum(
            1 for e in dept_emps if e.id != w.mole and e.clearance == m_emp.clearance
        )
    else:
        clearance_peer_count = mole_dept_size - 1

    all_docs = [doc for day_docs in w.planned_docs.values() for doc in day_docs]
    mole_docs = [doc for doc in all_docs if w.mole in doc["recipients"]]
    decoy_overlap = (
        sum(1 for doc in mole_docs if w.decoy in doc["recipients"])
        if w.decoy is not None
        else 0
    )
    decoy_overlap_share = (decoy_overlap / len(mole_docs)) if mole_docs else 0.0
    mole_doc_share = (len(mole_docs) / len(all_docs)) if all_docs else 0.0

    while not env.done:
        env.call("advance_day", {})

    mole_log_count = sum(1 for lg in env._logs if lg["employee"] == w.mole)
    realized_doc_access_density = float(mole_log_count) / float(tp.n_days)
    passive_leak_count = len(env._feed)

    cand = set(w.ids)
    dept_narrow_day = int(tp.n_days) + 1
    for d in range(1, int(tp.n_days) + 1):
        for item in env._feed:
            if int(item["surfaced_day"]) <= d:
                cand &= set(env._doc_by_id[item["doc_id"]]["recipients"])
        if len(cand) == mole_dept_size:
            dept_narrow_day = d
            break

    sol_accused = solver_ep.get("accused")
    sol_final_day = int(solver_ep["final_day"])
    sol_accuse_day = sol_final_day if sol_accused is not None else None
    sol_score = float(solver_ep["score"])
    sol_pe = _eval_post_expected(solver_ep, pe_memo)
    sol_correct = bool(solver_ep.get("correct"))

    mole_arch = classify_mole_archetype(
        tier=tier,
        same_dept_decoy=same_dept_decoy,
        mole_dept_size=mole_dept_size,
        passive_leak_count=passive_leak_count,
    )
    dept_stratum = classify_dept_stratum(tier=tier, mole_dept_size=mole_dept_size)
    sol_stratum = classify_solver_difficulty(tier=tier, solver_final_day=sol_final_day)

    return clean_json(
        {
            "seed": int(seed),
            "mole_policy": mole_policy,
            "mole_id": str(w.mole),
            "decoy_id": str(w.decoy) if w.decoy is not None else None,
            "mole_dept": str(m_emp.dept),
            "mole_dept_size": mole_dept_size,
            "mole_clearance": mole_clearance,
            "clearance_peer_count": clearance_peer_count,
            "same_dept_decoy": same_dept_decoy,
            "decoy_doc_overlap_count": decoy_overlap,
            "decoy_doc_overlap_share": decoy_overlap_share,
            "mole_planned_docs": len(mole_docs),
            "mole_doc_share": mole_doc_share,
            "realized_doc_access_density": realized_doc_access_density,
            "passive_leak_count": passive_leak_count,
            "dept_narrow_day": dept_narrow_day,
            "solver_accuse_day": sol_accuse_day,
            "solver_final_day": sol_final_day,
            "solver_score": sol_score,
            "solver_post_expected": sol_pe,
            "solver_correct": sol_correct,
            "mole_archetype": mole_arch,
            "dept_stratum": dept_stratum,
            "solver_difficulty_stratum": sol_stratum,
        }
    )


def _eval_post_expected(ep: dict[str, Any], pe_memo: dict[int, float] | None = None) -> float:
    if pe_memo is not None and id(ep) in pe_memo:
        return pe_memo[id(ep)]
    raw = post_expected(ep)
    if raw is None:
        raise ValueError(f"post_expected returned None on ({ep.get('tier')}, {ep.get('seed')})")
    val = float(raw)
    if pe_memo is not None:
        pe_memo[id(ep)] = val
    return val


def pack_seed_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(profiles, key=lambda p: int(p["seed"]))
    policies = sorted({str(p["mole_policy"]) for p in ordered})
    if len(policies) != 1:
        raise ValueError(f"expected single mole_policy per tier block, got {policies}")
    rows: list[list[Any]] = []
    for p in ordered:
        row: list[Any] = []
        for col in SEED_PROFILE_COLUMNS:
            val = p[col]
            if col in SEED_PROFILE_ENUMS:
                val = SEED_PROFILE_ENUMS[col].index(str(val))
            row.append(val)
        rows.append(row)
    n = len(ordered)
    arch_counts = {k: sum(1 for p in ordered if p["mole_archetype"] == k) for k in MOLE_ARCHETYPES}
    dept_counts = {k: sum(1 for p in ordered if p["dept_stratum"] == k) for k in DEPT_STRATA}
    sol_counts = {
        k: sum(1 for p in ordered if p["solver_difficulty_stratum"] == k)
        for k in SOLVER_DIFFICULTY_STRATA
    }
    return clean_json(
        {
            "n_seeds": n,
            "mole_policy": policies[0],
            "mean_mole_dept_size": sum(float(p["mole_dept_size"]) for p in ordered) / n,
            "same_dept_decoy_count": sum(1 for p in ordered if p["same_dept_decoy"]),
            "mean_decoy_doc_overlap_count": sum(float(p["decoy_doc_overlap_count"]) for p in ordered) / n,
            "mean_mole_doc_share": sum(float(p["mole_doc_share"]) for p in ordered) / n,
            "mean_realized_doc_access_density": (
                sum(float(p["realized_doc_access_density"]) for p in ordered) / n
            ),
            "mean_passive_leak_count": sum(float(p["passive_leak_count"]) for p in ordered) / n,
            "mole_archetype_counts": arch_counts,
            "dept_stratum_counts": dept_counts,
            "solver_difficulty_counts": sol_counts,
            "enums": {k: list(v) for k, v in SEED_PROFILE_ENUMS.items()},
            "columns": list(SEED_PROFILE_COLUMNS),
            "rows": rows,
        }
    )


def unpack_seed_profiles(packed: dict[str, Any]) -> list[dict[str, Any]]:
    cols = packed["columns"]
    pol = packed.get("mole_policy", "default_v0")
    enums = packed.get("enums") or {k: list(v) for k, v in SEED_PROFILE_ENUMS.items()}
    out: list[dict[str, Any]] = []
    for r in packed["rows"]:
        d = dict(zip(cols, r))
        for col, names in enums.items():
            if col in d and isinstance(d[col], int):
                d[col] = names[d[col]]
        d.setdefault("mole_policy", pol)
        out.append(d)
    return out


def pack_stratum_metrics(metrics: dict[str, Any]) -> list[Any]:
    return clean_json([metrics[col] for col in STRATUM_METRIC_COLUMNS])


def unpack_stratum_metrics(entry: list[Any] | dict[str, Any]) -> dict[str, Any]:
    if isinstance(entry, dict):
        return dict(entry)
    if len(entry) != len(STRATUM_METRIC_COLUMNS):
        raise ValueError(f"expected {len(STRATUM_METRIC_COLUMNS)} stratum cols, got {len(entry)}")
    return dict(zip(STRATUM_METRIC_COLUMNS, entry))


def compute_stratum_metrics(
    episodes: list[dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    eps = sorted(episodes, key=lambda e: int(e["seed"]))
    n = len(eps)
    if n == 0:
        return clean_json(
            {
                "n": 0,
                "raw": None,
                "luck": None,
                "acc": None,
                "abst": None,
                "day": None,
                "s_raw": None,
                "s_luck": None,
                "r_gap": None,
                "l_gap": None,
                "ratio": None,
            }
        )
    seeds = [int(e["seed"]) for e in eps]
    if len(set(seeds)) != n:
        raise ValueError(f"duplicate seeds in stratum: {seeds}")
    missing = [s for s in seeds if s not in solver_by_seed]
    if missing:
        raise ValueError(f"missing paired solver seeds: {missing}")

    f_raw = [float(e["score"]) for e in eps]
    s_raw = [float(solver_by_seed[s]["score"]) for s in seeds]
    f_pe_vals = [_eval_post_expected(e, pe_memo) for e in eps]
    s_pe_vals = [_eval_post_expected(solver_by_seed[s], pe_memo) for s in seeds]

    raw_mean = sum(f_raw) / n
    luck_adj_mean = sum(f_pe_vals) / n
    sol_raw_mean = sum(s_raw) / n
    sol_luck_mean = sum(s_pe_vals) / n
    correct_count = sum(1 for e in eps if bool(e.get("correct")))
    accused_eps = [e for e in eps if e.get("accused") is not None]
    abstention_count = n - len(accused_eps)
    accuse_day_mean = (
        sum(float(e["final_day"]) for e in accused_eps) / len(accused_eps)
        if accused_eps
        else None
    )
    luck_ratio = (luck_adj_mean / sol_luck_mean) if sol_luck_mean > 1e-12 else None

    return clean_json(
        {
            "n": n,
            "raw": raw_mean,
            "luck": luck_adj_mean,
            "acc": correct_count / n,
            "abst": abstention_count / n,
            "day": accuse_day_mean,
            "s_raw": sol_raw_mean,
            "s_luck": sol_luck_mean,
            "r_gap": sol_raw_mean - raw_mean,
            "l_gap": sol_luck_mean - luck_adj_mean,
            "ratio": luck_ratio,
        }
    )


def compute_cohort_stratification(
    cohort_id: str,
    label: str,
    agent: str,
    harness: str,
    tier: str,
    source: str,
    episodes: list[dict[str, Any]],
    profiles_by_seed: dict[int, dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
    expected_n: int | None = None,
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    eps = sorted(episodes, key=lambda e: int(e["seed"]))
    if expected_n is not None and len(eps) != expected_n:
        raise ValueError(f"cohort {cohort_id} expected n={expected_n}, got n={len(eps)}")
    seeds_seen: set[int] = set()
    for ep in eps:
        s = int(ep["seed"])
        if s in seeds_seen:
            raise ValueError(f"duplicate seed {s} in cohort {cohort_id}")
        if s not in profiles_by_seed:
            raise ValueError(f"seed {s} missing from profiles in cohort {cohort_id}")
        seeds_seen.add(s)

    overall = compute_stratum_metrics(eps, solver_by_seed, pe_memo=pe_memo)
    raw_ci_mean, raw_ci_half = mean_ci([float(e["score"]) for e in eps])
    overall["raw_ci"] = _r(raw_ci_half)
    overall["raw"] = _r(raw_ci_mean)

    by_arch: dict[str, Any] = {}
    for arch in MOLE_ARCHETYPES:
        sub = [e for e in eps if profiles_by_seed[int(e["seed"])]["mole_archetype"] == arch]
        by_arch[arch] = pack_stratum_metrics(
            compute_stratum_metrics(sub, solver_by_seed, pe_memo=pe_memo)
        )

    by_dept: dict[str, Any] = {}
    for ds in DEPT_STRATA:
        sub = [e for e in eps if profiles_by_seed[int(e["seed"])]["dept_stratum"] == ds]
        by_dept[ds] = pack_stratum_metrics(
            compute_stratum_metrics(sub, solver_by_seed, pe_memo=pe_memo)
        )

    by_sol_diff: dict[str, Any] = {}
    for sd in SOLVER_DIFFICULTY_STRATA:
        sub = [e for e in eps if profiles_by_seed[int(e["seed"])]["solver_difficulty_stratum"] == sd]
        by_sol_diff[sd] = pack_stratum_metrics(
            compute_stratum_metrics(sub, solver_by_seed, pe_memo=pe_memo)
        )

    return clean_json(
        {
            "cohort_id": cohort_id,
            "label": label,
            "agent": agent,
            "harness": harness,
            "tier": tier,
            "source": source,
            "n": len(eps),
            "seeds": [int(e["seed"]) for e in eps],
            "overall": overall,
            "by_mole_archetype": by_arch,
            "by_dept_stratum": by_dept,
            "by_solver_difficulty": by_sol_diff,
        }
    )


def _rank_gap_drivers(cohort: dict[str, Any], axis_key: str) -> list[dict[str, Any]]:
    strata_map = cohort[axis_key]
    rows: list[dict[str, Any]] = []
    for name, raw_st in strata_map.items():
        st = unpack_stratum_metrics(raw_st)
        if int(st["n"]) <= 0:
            continue
        rows.append(
            clean_json(
                {
                    "stratum": name,
                    "n": int(st["n"]),
                    "raw_gap": st["r_gap"],
                    "luck_adj_gap": st["l_gap"],
                    "accuracy": st["acc"],
                }
            )
        )
    rows.sort(key=lambda r: (-float(r["luck_adj_gap"]), -int(r["n"]), str(r["stratum"])))
    return rows


def _build_solver_solvability_summary(
    med_profiles: dict[int, dict[str, Any]],
    hard_0_29_profiles: dict[int, dict[str, Any]],
    hard_30_59_profiles: dict[int, dict[str, Any]],
    sol_med: dict[int, dict[str, Any]],
    sol_h0: dict[int, dict[str, Any]],
    sol_h30: dict[int, dict[str, Any]],
    pe_memo: dict[int, float] | None = None,
) -> dict[str, Any]:
    hard_all_profiles = {**hard_0_29_profiles, **hard_30_59_profiles}
    sol_hard_all = {**sol_h0, **sol_h30}
    hard_all_eps = [sol_hard_all[s] for s in sorted(sol_hard_all)]

    pooled_hard_by_arch: dict[str, Any] = {}
    for arch in MOLE_ARCHETYPES:
        sub = [e for e in hard_all_eps if hard_all_profiles[int(e["seed"])]["mole_archetype"] == arch]
        m = compute_stratum_metrics(sub, sol_hard_all, pe_memo=pe_memo)
        accused = [e for e in sub if e.get("accused") is not None]
        prec = (
            sum(1 for e in accused if bool(e.get("correct"))) / len(accused)
            if accused
            else None
        )
        pooled_hard_by_arch[arch] = clean_json(
            {
                "n": m["n"],
                "raw": m["raw"],
                "luck": m["luck"],
                "acc": m["acc"],
                "prec": prec,
                "abst": m["abst"],
                "day": m["day"],
            }
        )

    pooled_hard_by_dept: dict[str, Any] = {}
    for ds in DEPT_STRATA:
        sub = [e for e in hard_all_eps if hard_all_profiles[int(e["seed"])]["dept_stratum"] == ds]
        m = compute_stratum_metrics(sub, sol_hard_all, pe_memo=pe_memo)
        accused = [e for e in sub if e.get("accused") is not None]
        prec = (
            sum(1 for e in accused if bool(e.get("correct"))) / len(accused)
            if accused
            else None
        )
        pooled_hard_by_dept[ds] = clean_json(
            {
                "n": m["n"],
                "raw": m["raw"],
                "luck": m["luck"],
                "acc": m["acc"],
                "prec": prec,
                "abst": m["abst"],
                "day": m["day"],
            }
        )

    med_eps = [sol_med[s] for s in sorted(sol_med)]
    med_accused = [e for e in med_eps if e.get("accused") is not None]
    hard_accused = [e for e in hard_all_eps if e.get("accused") is not None]
    med_m = compute_stratum_metrics(med_eps, sol_med, pe_memo=pe_memo)
    hard_m = compute_stratum_metrics(hard_all_eps, sol_hard_all, pe_memo=pe_memo)

    return clean_json(
        {
            "medium_0_29_overall": {
                "n": len(med_eps),
                "accuracy": sum(1 for e in med_eps if bool(e.get("correct"))) / len(med_eps),
                "precision_when_accusing": (
                    sum(1 for e in med_accused if bool(e.get("correct"))) / len(med_accused)
                ),
                "wrong_accusations": sum(1 for e in med_accused if not bool(e.get("correct"))),
                "abstentions": len(med_eps) - len(med_accused),
                "luck_adj_mean": med_m["luck"],
            },
            "hard_0_59_pooled": {
                "n": len(hard_all_eps),
                "accuracy": sum(1 for e in hard_all_eps if bool(e.get("correct"))) / len(hard_all_eps),
                "precision_when_accusing": (
                    sum(1 for e in hard_accused if bool(e.get("correct"))) / len(hard_accused)
                ),
                "wrong_accusations": sum(1 for e in hard_accused if not bool(e.get("correct"))),
                "abstentions": len(hard_all_eps) - len(hard_accused),
                "raw_mean": hard_m["raw"],
                "luck_adj_mean": hard_m["luck"],
                "all_mole_archetypes_positive_luck_adj": all(
                    v["luck"] is not None and float(v["luck"]) > 0.30
                    for v in pooled_hard_by_arch.values()
                    if int(v["n"]) > 0
                ),
                "all_dept_strata_positive_luck_adj": all(
                    v["luck"] is not None and float(v["luck"]) > 0.45
                    for v in pooled_hard_by_dept.values()
                    if int(v["n"]) > 0
                ),
                "by_mole_archetype": pooled_hard_by_arch,
                "by_dept_stratum": pooled_hard_by_dept,
            },
        }
    )


def compute_audit(
    root: Path = ROOT,
    verify_replays: bool = True,
    enforce_expected_counts: bool = True,
) -> dict[str, Any]:
    prev_allow = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    _P_CACHE.clear()
    try:
        comm_v14 = root / "data" / "runs" / "committed" / "v1.4"
        rep_v14 = root / "results" / "frontier_replication" / "v1.4"

        comm_eps = load_runs(comm_v14)
        rep_eps = load_runs(rep_v14)

        if enforce_expected_counts:
            if len(comm_eps) != EXPECTED_COMMITTED_V14_EPISODES:
                raise ValueError(
                    f"committed v1.4 expected {EXPECTED_COMMITTED_V14_EPISODES} episodes, got {len(comm_eps)}"
                )
            if len(rep_eps) != EXPECTED_REPLICATION_V14_EPISODES:
                raise ValueError(
                    f"replication v1.4 expected {EXPECTED_REPLICATION_V14_EPISODES} episodes, got {len(rep_eps)}"
                )
            if len(comm_eps) + len(rep_eps) != EXPECTED_COMBINED_V14_EPISODES:
                raise ValueError(
                    f"combined v1.4 expected {EXPECTED_COMBINED_V14_EPISODES} episodes, got {len(comm_eps) + len(rep_eps)}"
                )

        if verify_replays:
            comm_pool_audit = verify_episode_pool(comm_eps, "data/runs/committed/v1.4")
            rep_pool_audit = verify_episode_pool(rep_eps, "results/frontier_replication/v1.4")
        else:
            comm_pool_audit = {
                "pool": "data/runs/committed/v1.4",
                "total": len(comm_eps),
                "verified": 0,
                "mismatches": 0,
                "step_mismatches": 0,
                "duplicates": 0,
                "pre_1bc3e281_detail_normalized_steps": 0,
                "unwrapped_mcp_error_steps": 0,
                "truncated_output_steps_verified": 0,
                "client_only_steps": 0,
                "clean_rc0_non_accuse_zero_day_seeds": sorted(
                    int(e["seed"]) for e in comm_eps if is_clean_non_accuse_rc0_exit(e)
                ),
            }
            rep_pool_audit = {
                "pool": "results/frontier_replication/v1.4",
                "total": len(rep_eps),
                "verified": 0,
                "mismatches": 0,
                "step_mismatches": 0,
                "duplicates": 0,
                "pre_1bc3e281_detail_normalized_steps": 0,
                "unwrapped_mcp_error_steps": 0,
                "truncated_output_steps_verified": 0,
                "client_only_steps": 0,
                "clean_rc0_non_accuse_zero_day_seeds": sorted(
                    int(e["seed"]) for e in rep_eps if is_clean_non_accuse_rc0_exit(e)
                ),
            }

        include_flash_hard = gap_ships_flash_hard(root)
        runs_cache: dict[str, list[dict[str, Any]]] = {}
        pe_memo: dict[int, float] = {}

        def _select(
            rel_dir: str,
            agent: str,
            tier: str,
            s_min: int,
            s_max: int,
        ) -> list[dict[str, Any]]:
            if rel_dir not in runs_cache:
                runs_cache[rel_dir] = load_runs(root / rel_dir)
            sub = runs_cache[rel_dir]
            return sorted(
                (
                    e
                    for e in sub
                    if e.get("agent") == agent
                    and e.get("tier") == tier
                    and s_min <= int(e["seed"]) <= s_max
                ),
                key=lambda e: int(e["seed"]),
            )

        sol_med_eps = _select("data/runs/committed/v1.4/reference", "solver", "medium", 0, 29)
        sol_h0_eps = _select("data/runs/committed/v1.4/reference", "solver", "hard", 0, 29)
        sol_h30_eps = _select(
            "data/runs/committed/v1.4/reference/solver-hard-seeds30to59",
            "solver",
            "hard",
            30,
            59,
        )

        if enforce_expected_counts:
            for name, arr in (
                ("solver_medium_0_29", sol_med_eps),
                ("solver_hard_0_29", sol_h0_eps),
                ("solver_hard_30_59", sol_h30_eps),
            ):
                if len(arr) != 30:
                    raise ValueError(f"{name} expected n=30, got n={len(arr)}")

        sol_med_map = {int(e["seed"]): e for e in sol_med_eps}
        sol_h0_map = {int(e["seed"]): e for e in sol_h0_eps}
        sol_h30_map = {int(e["seed"]): e for e in sol_h30_eps}

        med_profiles = {
            s: extract_seed_profile("medium", s, sol_med_map[s], pe_memo=pe_memo)
            for s in sorted(sol_med_map)
        }
        h0_profiles = {
            s: extract_seed_profile("hard", s, sol_h0_map[s], pe_memo=pe_memo)
            for s in sorted(sol_h0_map)
        }
        h30_profiles = {
            s: extract_seed_profile("hard", s, sol_h30_map[s], pe_memo=pe_memo)
            for s in sorted(sol_h30_map)
        }

        oc_c_h0 = _select(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
            "opencode:google/gemini-4-carbon",
            "hard",
            0,
            29,
        )
        ip_c_h0 = _select(
            "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard",
            "gemini:gemini-4-carbon",
            "hard",
            0,
            29,
        )
        gpt55_hard_dir = root / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"
        oc_gpt55_h0 = (
            _select(
                "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
                "opencode:openai/gpt-5.5",
                "hard",
                0,
                29,
            )
            if gpt55_hard_dir.is_dir() or enforce_expected_counts
            else []
        )
        oc_f_h0 = (
            _select(
                "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard",
                "opencode:google/gemini-3.5-flash",
                "hard",
                0,
                29,
            )
            if include_flash_hard
            else []
        )

        oc_c_m0 = _select(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium",
            "opencode:google/gemini-4-carbon",
            "medium",
            0,
            29,
        )
        ip_c_m0 = _select(
            "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium",
            "gemini:gemini-4-carbon",
            "medium",
            0,
            29,
        )
        oc_f_m0 = _select(
            "results/frontier_replication/v1.4/opencode-gemini-3.5-flash",
            "opencode:google/gemini-3.5-flash",
            "medium",
            0,
            29,
        )

        grok_h30 = _select(
            "results/frontier_replication/v1.4/reference/grok_tactics-hard-seeds30to59",
            "grok_tactics",
            "hard",
            30,
            59,
        )
        heur_h30 = _select(
            "results/frontier_replication/v1.4/reference/heuristic-hard-seeds30to59",
            "heuristic",
            "hard",
            30,
            59,
        )
        g1_ext_h30 = _select(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
            "opencode:google/gemini-4-carbon",
            "hard",
            30,
            59,
        )
        fr8_rep_h30 = _select(
            "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
            "opencode:google/gemini-4-carbon",
            "hard",
            30,
            59,
        )

        union_map: dict[int, dict[str, Any]] = {int(e["seed"]): e for e in fr8_rep_h30}
        for e in g1_ext_h30:
            union_map[int(e["seed"])] = e
        union_ext_h30 = [union_map[s] for s in sorted(union_map)]

        exp = (lambda k: k) if enforce_expected_counts else (lambda _k: None)

        hard_0_29_cohorts = [
            compute_cohort_stratification(
                "solver_hard_0_29",
                "reference solver hard (0-29)",
                "solver",
                "reference",
                "hard",
                "committed",
                sol_h0_eps,
                h0_profiles,
                sol_h0_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_hard_0_29",
                "OpenCode gemini-4-carbon hard (0-29)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "committed",
                oc_c_h0,
                h0_profiles,
                sol_h0_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "inproc_carbon_hard_0_29",
                "in-process gemini-4-carbon hard (0-29)",
                "gemini:gemini-4-carbon",
                "inproc",
                "hard",
                "committed",
                ip_c_h0,
                h0_profiles,
                sol_h0_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
        ]
        if oc_gpt55_h0 or enforce_expected_counts:
            hard_0_29_cohorts.append(
                compute_cohort_stratification(
                    "opencode_gpt55_hard_0_29",
                    "OpenCode gpt-5.5 hard (0-29)",
                    "opencode:openai/gpt-5.5",
                    "opencode",
                    "hard",
                    "committed",
                    oc_gpt55_h0,
                    h0_profiles,
                    sol_h0_map,
                    expected_n=exp(30),
                    pe_memo=pe_memo,
                )
            )
        if include_flash_hard:
            hard_0_29_cohorts.append(
                compute_cohort_stratification(
                    "opencode_flash_hard_0_29",
                    "OpenCode gemini-3.5-flash hard (0-29)",
                    "opencode:google/gemini-3.5-flash",
                    "opencode",
                    "hard",
                    "committed",
                    oc_f_h0,
                    h0_profiles,
                    sol_h0_map,
                    expected_n=exp(30),
                    pe_memo=pe_memo,
                )
            )

        medium_0_29_cohorts = [
            compute_cohort_stratification(
                "solver_medium_0_29",
                "reference solver medium (0-29)",
                "solver",
                "reference",
                "medium",
                "committed",
                sol_med_eps,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_medium_0_29",
                "OpenCode gemini-4-carbon medium (0-29)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "medium",
                "committed",
                oc_c_m0,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "inproc_carbon_medium_0_29",
                "in-process gemini-4-carbon medium (0-29)",
                "gemini:gemini-4-carbon",
                "inproc",
                "medium",
                "committed",
                ip_c_m0,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_flash_medium_0_29",
                "OpenCode gemini-3.5-flash medium (0-29)",
                "opencode:google/gemini-3.5-flash",
                "opencode",
                "medium",
                "replication",
                oc_f_m0,
                med_profiles,
                sol_med_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
        ]

        ext_hard_30_59_cohorts = [
            compute_cohort_stratification(
                "solver_hard_30_59",
                "reference solver hard (30-59)",
                "solver",
                "reference",
                "hard",
                "committed",
                sol_h30_eps,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "grok_tactics_hard_30_59",
                "grok_tactics hard (30-59)",
                "grok_tactics",
                "reference",
                "hard",
                "replication",
                grok_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "heuristic_hard_30_59",
                "heuristic hard (30-59)",
                "heuristic",
                "reference",
                "hard",
                "replication",
                heur_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(30),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_g1_ext_hard",
                "OpenCode gemini-4-carbon hard G1 ext (34,37)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "committed",
                g1_ext_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(2),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_fr8_rep_hard",
                "OpenCode gemini-4-carbon hard FR8 rep (30,34,42,45,57)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "replication",
                fr8_rep_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(5),
                pe_memo=pe_memo,
            ),
            compute_cohort_stratification(
                "opencode_carbon_union_ext_hard",
                "OpenCode gemini-4-carbon hard 6-seed union (30,34,37,42,45,57; G1 precedence on 34)",
                "opencode:google/gemini-4-carbon",
                "opencode",
                "hard",
                "union_committed_precedence",
                union_ext_h30,
                h30_profiles,
                sol_h30_map,
                expected_n=exp(6),
                pe_memo=pe_memo,
            ),
        ]

        g1_map = {int(e["seed"]): e for e in g1_ext_h30}
        fr8_map = {int(e["seed"]): e for e in fr8_rep_h30}
        overlap_ext_seeds = sorted(set(g1_map) & set(fr8_map))
        union_seeds = [int(e["seed"]) for e in union_ext_h30]
        union_dept_sizes = [int(h30_profiles[s]["mole_dept_size"]) for s in union_seeds]

        h0_by_id = {c["cohort_id"]: c for c in hard_0_29_cohorts}
        carbon_hard_row = h0_by_id["opencode_carbon_hard_0_29"]
        gpt55_hard_row = h0_by_id.get("opencode_gpt55_hard_0_29")
        flash_hard_row = h0_by_id.get("opencode_flash_hard_0_29")
        flash_med_row = medium_0_29_cohorts[3]
        grok_ext_row = ext_hard_30_59_cohorts[1]
        heur_ext_row = ext_hard_30_59_cohorts[2]

        gap_drivers: dict[str, Any] = {
            "primary_carbon_hard_by_mole_archetype": _rank_gap_drivers(
                carbon_hard_row, "by_mole_archetype"
            ),
            "primary_carbon_hard_by_dept_stratum": _rank_gap_drivers(
                carbon_hard_row, "by_dept_stratum"
            ),
            "primary_carbon_hard_by_solver_difficulty": _rank_gap_drivers(
                carbon_hard_row, "by_solver_difficulty"
            ),
            "fr8_flash_medium_by_mole_archetype": _rank_gap_drivers(
                flash_med_row, "by_mole_archetype"
            ),
            "ext_grok_tactics_hard_by_mole_archetype": _rank_gap_drivers(
                grok_ext_row, "by_mole_archetype"
            ),
            "ext_heuristic_hard_by_mole_archetype": _rank_gap_drivers(
                heur_ext_row, "by_mole_archetype"
            ),
            "extension_6_seed_union_selection_profile": clean_json(
                {
                    "union_seeds": union_seeds,
                    "overlap_seeds_committed_precedence": overlap_ext_seeds,
                    "seed_34_selected_source": "committed_g1_f9fb7a4a",
                    "seed_34_g1_score": float(g1_map[34]["score"]) if 34 in g1_map else None,
                    "seed_34_g1_luck_adj": (
                        _eval_post_expected(g1_map[34], pe_memo) if 34 in g1_map else None
                    ),
                    "seed_34_fr8_score": float(fr8_map[34]["score"]) if 34 in fr8_map else None,
                    "seed_34_fr8_luck_adj": (
                        _eval_post_expected(fr8_map[34], pe_memo) if 34 in fr8_map else None
                    ),
                    "mean_mole_dept_size_union_6": (
                        sum(union_dept_sizes) / len(union_dept_sizes) if union_dept_sizes else None
                    ),
                    "mean_mole_dept_size_hard_30_59": (
                        sum(float(p["mole_dept_size"]) for p in h30_profiles.values())
                        / len(h30_profiles)
                    ),
                    "mean_mole_dept_size_hard_0_29": (
                        sum(float(p["mole_dept_size"]) for p in h0_profiles.values())
                        / len(h0_profiles)
                    ),
                    "deep_crowd_camouflage_count_in_union_6": sum(
                        1
                        for s in union_seeds
                        if h30_profiles[s]["mole_archetype"] == "deep_crowd_camouflage"
                    ),
                    "crowded_dept_count_in_union_6": sum(
                        1 for s in union_seeds if h30_profiles[s]["dept_stratum"] == "crowded_dept"
                    ),
                }
            ),
        }
        if gpt55_hard_row is not None:
            gap_drivers["primary_gpt55_hard_by_mole_archetype"] = _rank_gap_drivers(
                gpt55_hard_row, "by_mole_archetype"
            )
        if include_flash_hard and flash_hard_row is not None:
            gap_drivers["primary_flash_hard_by_mole_archetype"] = _rank_gap_drivers(
                flash_hard_row, "by_mole_archetype"
            )

        solver_solvability = _build_solver_solvability_summary(
            med_profiles=med_profiles,
            hard_0_29_profiles=h0_profiles,
            hard_30_59_profiles=h30_profiles,
            sol_med=sol_med_map,
            sol_h0=sol_h0_map,
            sol_h30=sol_h30_map,
            pe_memo=pe_memo,
        )

        all_cohorts = hard_0_29_cohorts + medium_0_29_cohorts + ext_hard_30_59_cohorts
        distinct_eps_evaluated = (
            sum(c["n"] for c in hard_0_29_cohorts)
            + sum(c["n"] for c in medium_0_29_cohorts)
            + sum(
                c["n"]
                for c in ext_hard_30_59_cohorts
                if c["cohort_id"] != "opencode_carbon_union_ext_hard"
            )
        )

        return clean_json(
            {
                "schema_version": "v1.4-frontier-mole-stratified-gap-1",
                "tiers_version": TIERS_VERSION,
                "zero_live_api_calls": True,
                "zero_git_dependency": True,
                "flash_hard_shipped_in_gap_md": include_flash_hard,
                "stratum_metric_columns": list(STRATUM_METRIC_COLUMNS),
                "provenance_and_locks": {
                    "primary_0_29_lock": {
                        "classification": "post_hoc_lock",
                        "episodes_commit": "8fd4dec",
                        "lock_commit": "671ed96",
                        "lock_delay_s": 28,
                        "solver_reference_layout": (
                            "20+10 split dirs (0-19 in 20261114-121126 + 20-29 in seeds20to29)"
                        ),
                        "note": (
                            "Post-hoc lock against later reruns and cherry-picking, not a pre-registration."
                        ),
                    },
                    "g1_hard_30_59_extension": {
                        "classification": "pre_registered",
                        "prereg_commit": "f9fb7a4a",
                        "run_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
                        "completed_seeds": [int(e["seed"]) for e in g1_ext_h30],
                        "n": len(g1_ext_h30),
                        "stopped_reason": "quota_preserved_for_harbor_rehearsal",
                    },
                    "gpt_5_5_hard_0_29": {
                        "classification": "pre_registered",
                        "prereg_commit": "cf394894",
                        "results_commit": "ca0a0dc0",
                        "upstream_sync_commit": "5f9b3297",
                        "run_dir": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
                        "timeout_cap_s": 7200,
                        "spend_cap_usd": 200,
                        "opencode_version": "1.19.5",
                        "committed_v14_episodes": sum(
                            1 for e in comm_eps if "gpt-5.5" in str(e.get("agent") or "")
                        ),
                        "clean_rc0_non_accuse_zero_day_seeds": sorted(
                            int(e["seed"])
                            for e in comm_eps
                            if "gpt-5.5" in str(e.get("agent") or "")
                            and is_clean_non_accuse_rc0_exit(e)
                        ),
                    },
                    "step_error_detail_compat": {
                        "commit": "1bc3e281",
                        "rule": (
                            "Unwrap OpenCode stringified MCP error JSON via norm_result first, then match "
                            "pre-1bc3e281 data={} against live Env.call data={'detail': ...} when 'detail' "
                            "is absent from recorded data; allow final_day=0 on clean rc=0 non-accuse exits "
                            "(is_clean_non_accuse_rc0_exit) while rejecting timeouts, rc!=0, and tampered scores."
                        ),
                    },
                },
                "mole_policy_and_genome": {
                    "medium": _tier_mole_genome("medium"),
                    "hard": _tier_mole_genome("hard"),
                    "taxonomy_definitions": {
                        "mole_archetype": {
                            "decoy_entangled": (
                                "same_dept_decoy is True (100% regular-document overlap between mole and "
                                "angry-message decoy plus 50% framed after-hours decoy share)"
                            ),
                            "deep_crowd_camouflage": (
                                "not decoy_entangled and mole_dept_size >= floor(n_employees / n_depts) + 2 "
                                "(>=7 of 20 on medium, >=10 of 40 on hard)"
                            ),
                            "low_tempo_stealth": (
                                "neither above and passive_leak_count < n_days * p_leak "
                                "(<=10 on medium, <=13 on hard)"
                            ),
                            "high_tempo_exposed": (
                                "neither above and passive_leak_count >= n_days * p_leak "
                                "(>=11 on medium, >=14 on hard)"
                            ),
                        },
                        "dept_stratum": {
                            "compact_dept": "mole_dept_size <= 4 on medium, <= 8 on hard",
                            "standard_dept": "mole_dept_size in 5..6 on medium, 9..10 on hard",
                            "crowded_dept": "mole_dept_size >= 7 on medium, >= 11 on hard",
                        },
                        "solver_difficulty_stratum": {
                            "fast_isolation": "reference solver final_day <= 6 on medium, <= 8 on hard",
                            "mid_horizon_isolation": (
                                "reference solver final_day in 7..9 on medium, 9..12 on hard"
                            ),
                            "late_or_stalled_isolation": (
                                "reference solver final_day >= 10 on medium, >= 13 on hard"
                            ),
                        },
                    },
                    "notes": (
                        "Standard medium and hard v1.4 tiers run DEFAULT_STRATEGY (default_v0: 0 conditional "
                        "DSL rules, random_seeded leak selection weighted by careful_mole 1 - share, Poisson "
                        "framing, and 95% canary fingerprint accuracy on hard), whereas evolved HoF DSL and RL "
                        "moles apply only on hard_forge and hard_rl judge tracks. Because p_single_dept_recipients "
                        "is 0.0 on medium and hard, 100% of regular documents go to two whole departments, so "
                        "regular leaks can never separate colleagues inside mole_dept."
                    ),
                },
                "replay_verification": {
                    "committed_v14": comm_pool_audit,
                    "replication_v14": rep_pool_audit,
                },
                "summary": {
                    "worlds_extracted": len(med_profiles) + len(h0_profiles) + len(h30_profiles),
                    "cohort_count": len(all_cohorts),
                    "cohort_episode_counts": [int(c["n"]) for c in all_cohorts],
                    "distinct_cohort_episodes_evaluated": distinct_eps_evaluated,
                    "committed_v14_total": int(comm_pool_audit["total"]),
                    "committed_v14_verified": int(comm_pool_audit["verified"]),
                    "replication_v14_total": int(rep_pool_audit["total"]),
                    "replication_v14_verified": int(rep_pool_audit["verified"]),
                    "total_pool_episodes_replay_verified": (
                        int(comm_pool_audit["verified"]) + int(rep_pool_audit["verified"])
                    ),
                    "flash_hard_held_pending_gap_md": not include_flash_hard,
                },
                "seed_profiles": {
                    "medium_0_29": pack_seed_profiles(list(med_profiles.values())),
                    "hard_0_29": pack_seed_profiles(list(h0_profiles.values())),
                    "hard_30_59": pack_seed_profiles(list(h30_profiles.values())),
                },
                "blocks": {
                    "primary_hard_0_29": hard_0_29_cohorts,
                    "primary_and_fr8_medium_0_29": medium_0_29_cohorts,
                    "extension_hard_30_59": ext_hard_30_59_cohorts,
                },
                "solver_solvability": solver_solvability,
                "gap_drivers": gap_drivers,
            }
        )
    finally:
        _P_CACHE.clear()
        if prev_allow is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_allow


def _fmt_json_compact(obj: Any, depth: int = 0, max_expand_depth: int = 2) -> str:
    if depth >= max_expand_depth or not isinstance(obj, (dict, list)) or not obj:
        return json.dumps(obj, sort_keys=True, allow_nan=False, separators=(",", ":"))
    pad = " " * depth
    inner_pad = " " * (depth + 1)
    if isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            return json.dumps(obj, allow_nan=False, separators=(",", ":"))
        items = [inner_pad + _fmt_json_compact(v, depth + 1, max_expand_depth) for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    items = [
        f"{inner_pad}{json.dumps(k)}: {_fmt_json_compact(obj[k], depth + 1, max_expand_depth)}"
        for k in sorted(obj.keys())
    ]
    return "{\n" + ",\n".join(items) + "\n" + pad + "}"


def serialize_audit_json(audit: dict[str, Any]) -> str:
    blob = _fmt_json_compact(audit, depth=0, max_expand_depth=2) + "\n"
    size = len(blob.encode("utf-8"))
    if size > MAX_JSON_BYTES:
        raise ValueError(
            f"serialized mole_stratified_gap.json is {size} bytes, exceeding {MAX_JSON_BYTES}"
        )
    return blob


def _md_heading(level: int, title: str) -> str:
    return (chr(35) * level) + " " + title


def _f(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:.{nd}f}"


def _signed(val: float | None, nd: int = 3) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:+.{nd}f}"


def _pct(val: float | None, nd: int = 1) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{100.0 * val:.{nd}f}%"


def _render_stratum_rows(cohorts: list[dict[str, Any]], axis_key: str, keys: tuple[str, ...]) -> list[str]:
    lines = [
        "| cohort | stratum | n | raw score | luck-adj. score | solver luck-adj. | luck-adj. gap (S - F) | luck-adj. / solver | accuracy | abstain | accuse day |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in cohorts:
        ov = c["overall"]
        is_sol = c["agent"] == "solver"
        lines.append(
            f"| **{c['label']}** | **ALL** | {ov['n']} | {_signed(ov['raw'])} | "
            f"{_signed(ov['luck'])} | {_signed(ov['s_luck'])} | "
            f"{'n/a' if is_sol else _signed(ov['l_gap'])} | "
            f"{'n/a' if is_sol else _pct(ov['ratio'])} | "
            f"{_pct(ov['acc'])} | {_pct(ov['abst'])} | "
            f"{_f(ov['day'], 1)} |"
        )
        smap = c[axis_key]
        for k in keys:
            st = unpack_stratum_metrics(smap[k])
            if int(st["n"]) == 0:
                lines.append(
                    f"| {c['label']} | `{k}` | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |"
                )
            else:
                lines.append(
                    f"| {c['label']} | `{k}` | {st['n']} | {_signed(st['raw'])} | "
                    f"{_signed(st['luck'])} | {_signed(st['s_luck'])} | "
                    f"{'n/a' if is_sol else _signed(st['l_gap'])} | "
                    f"{'n/a' if is_sol else _pct(st['ratio'])} | "
                    f"{_pct(st['acc'])} | {_pct(st['abst'])} | "
                    f"{_f(st['day'], 1)} |"
                )
    return lines


def render_markdown(audit: dict[str, Any]) -> str:
    s = audit["summary"]
    rv = audit["replay_verification"]
    prov = audit["provenance_and_locks"]
    gen = audit["mole_policy_and_genome"]
    sp = audit["seed_profiles"]
    blocks = audit["blocks"]
    solv = audit["solver_solvability"]
    drv = audit["gap_drivers"]
    include_flash_hard = bool(audit.get("flash_hard_shipped_in_gap_md"))

    h0_cohorts = blocks["primary_hard_0_29"]
    m0_cohorts = blocks["primary_and_fr8_medium_0_29"]
    h30_cohorts = blocks["extension_hard_30_59"]

    h0_by_id = {c["cohort_id"]: c for c in h0_cohorts}
    sol_h0 = h0_by_id["solver_hard_0_29"]
    oc_c_h0 = h0_by_id["opencode_carbon_hard_0_29"]
    oc_gpt55_h0 = h0_by_id.get("opencode_gpt55_hard_0_29")
    oc_f_h0 = h0_by_id.get("opencode_flash_hard_0_29") if include_flash_hard else None

    sol_m0 = m0_cohorts[0]
    oc_c_m0 = m0_cohorts[1]
    ip_c_m0 = m0_cohorts[2]
    oc_f_m0 = m0_cohorts[3]

    g1_h30 = h30_cohorts[3]
    fr8_h30 = h30_cohorts[4]
    u6_h30 = h30_cohorts[5]

    comm_rv = rv["committed_v14"]
    rep_rv = rv["replication_v14"]
    u6_sel = drv["extension_6_seed_union_selection_profile"]
    hard_pooled = solv["hard_0_59_pooled"]
    med_solv = solv["medium_0_29_overall"]
    hp_arch = hard_pooled["by_mole_archetype"]
    hp_dept = hard_pooled["by_dept_stratum"]

    c_arch_top = drv["primary_carbon_hard_by_mole_archetype"]
    c_dept_top = drv["primary_carbon_hard_by_dept_stratum"]
    c_sol_top = drv["primary_carbon_hard_by_solver_difficulty"]
    g_arch_top = drv["ext_grok_tactics_hard_by_mole_archetype"]
    h_arch_top = drv["ext_heuristic_hard_by_mole_archetype"]

    oc_c_decoy = unpack_stratum_metrics(oc_c_h0["by_mole_archetype"]["decoy_entangled"])
    sol_h0_decoy = unpack_stratum_metrics(sol_h0["by_mole_archetype"]["decoy_entangled"])
    sol_h0_top_arch = unpack_stratum_metrics(
        sol_h0["by_mole_archetype"][c_arch_top[0]["stratum"]]
    )
    oc_f_m0_stealth = unpack_stratum_metrics(oc_f_m0["by_mole_archetype"]["low_tempo_stealth"])
    ip_c_m0_crowd = unpack_stratum_metrics(ip_c_m0["by_dept_stratum"]["crowded_dept"])

    if oc_gpt55_h0 is not None:
        gpt_crowd = unpack_stratum_metrics(oc_gpt55_h0["by_mole_archetype"]["deep_crowd_camouflage"])
        gpt_cdept = unpack_stratum_metrics(oc_gpt55_h0["by_dept_stratum"]["crowded_dept"])
        gpt_stealth = unpack_stratum_metrics(oc_gpt55_h0["by_mole_archetype"]["low_tempo_stealth"])
        gpt_contrast = (
            f" By contrast, OpenCode `gpt-5.5` (`n={oc_gpt55_h0['n']}`, raw `{_signed(oc_gpt55_h0['overall']['raw'])}`, "
            f"luck-adjusted `{_signed(oc_gpt55_h0['overall']['luck'])}`, `{_pct(oc_gpt55_h0['overall']['ratio'])}` of solver "
            f"luck-adjusted, `{_pct(oc_gpt55_h0['overall']['acc'])}` accuracy) plants about 2 canaries/day and reaches "
            f"`{_pct(gpt_crowd['acc'])}` accuracy on `deep_crowd_camouflage` (`n={gpt_crowd['n']}`, raw `{_signed(gpt_crowd['raw'])}`, "
            f"luck-adjusted `{_signed(gpt_crowd['luck'])}`) and `{_pct(gpt_cdept['acc'])}` on `crowded_dept` (`n={gpt_cdept['n']}`, "
            f"raw `{_signed(gpt_cdept['raw'])}`, luck-adjusted `{_signed(gpt_cdept['luck'])}`), while both of its clean `rc=0` "
            f"non-accuse `final_day=0` prose stops (`seeds {prov['gpt_5_5_hard_0_29']['clean_rc0_non_accuse_zero_day_seeds']}`) "
            f"occur in `low_tempo_stealth` (`n={gpt_stealth['n']}`, abstain `{_pct(gpt_stealth['abst'])}`)."
        )
    else:
        gpt_contrast = ""

    arch_lucks = [float(hp_arch[a]["luck"]) for a in MOLE_ARCHETYPES if hp_arch[a]["luck"] is not None]
    min_arch_luck = min(arch_lucks) if arch_lucks else None
    max_arch_luck = max(arch_lucks) if arch_lucks else None

    if include_flash_hard and oc_f_h0 is not None:
        f_arch_top = drv["primary_flash_hard_by_mole_archetype"]
        flash_gate_bullet = (
            f"- **Cross-model hard stratification (`OpenCode gemini-3.5-flash` hard `0-29`, `n=30`):** "
            f"`docs/reports/gap.md` ships `gemini-3.5-flash`, so its primary hard cohort is included below "
            f"(overall raw `{_signed(oc_f_h0['overall']['raw'])}`, luck-adjusted "
            f"`{_signed(oc_f_h0['overall']['luck'])}`, gap `{_signed(oc_f_h0['overall']['l_gap'])}`; "
            f"largest mole-archetype luck-adjusted gap on `{f_arch_top[0]['stratum']}` at "
            f"`{_signed(f_arch_top[0]['luck_adj_gap'])}`)."
        )
    else:
        flash_gate_bullet = (
            "- **`docs/reports/gap.md` hard-row gate (`gap_ships_flash_hard(root)`):** "
            "`opencode:google/gemini-3.5-flash` hard (`seeds 0-29`) is replay-verified inside "
            f"`data/runs/committed/v1.4` (`{comm_rv['verified']}/{comm_rv['total']}`) and gated out of "
            "primary hard tables here until `docs/reports/gap.md` ships it; FR8 `gemini-3.5-flash` "
            "medium (`seeds 0-29`, `n=30`) is reported in full below."
        )

    clean_zero_seeds = comm_rv.get("clean_rc0_non_accuse_zero_day_seeds") or []
    clean_zero_clause = (
        f" and verifying `{len(clean_zero_seeds)}` clean `rc=0` non-accuse `final_day=0` exits (`seeds {clean_zero_seeds}`)"
        if clean_zero_seeds
        else ""
    )

    lines: list[str] = [
        _md_heading(1, "Canary v1.4 Mole-Archetype and Seed-Difficulty Stratified Gap Audit"),
        "",
        (
            "Every figure in this report is deterministically computed on pure CPU by "
            "`scripts/frontier_mole_stratified_gap.py` from `Env(tier, seed)` world/mole attributes "
            f"across `{s['worlds_extracted']}` worlds (`medium 0-29`, `hard 0-29`, `hard 30-59`) and "
            f"`{s['cohort_count']}` stratified cohorts after full step-and-ledger replay verification "
            f"of `{comm_rv['verified']}/{comm_rv['total']}` committed `v1.4` episodes and "
            f"`{rep_rv['verified']}/{rep_rv['total']}` FR8 replication episodes "
            "(`0` live API calls, `0` `.git` runtime dependency)."
        ),
        "",
        (
            "**Complementary scope:** `docs/reports/failure_analysis_v1.4.md` decomposes within-episode "
            "agent decision mistakes on primary hard `seeds 0-29`, and `docs/reports/reference_optimality.md` "
            "establishes aggregate solver calibration and stopping optimality on dev `seeds 8000-9399`. "
            "This report addresses the orthogonal **across-seed structural and mole-archetype question**: "
            "(1) whether every mole archetype and department-anonymity stratum is reliably solvable by the "
            "Bayesian reference solver, and (2) which specific mole archetypes and world difficulty strata "
            "drive the luck-adjusted frontier gap across `gemini-4-carbon`, `gpt-5.5`, `gemini-3.5-flash`, and "
            "non-Bayesian baselines."
        ),
        "",
        "Reproduce and verify:",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/frontier_mole_stratified_gap.py --check",
        "```",
        "",
        _md_heading(2, "1. Provenance Honesty (Panel Fixes A/C/D), Replay Integrity, and Headline Findings"),
        "",
        (
            f"- **Provenance & registration honesty (Panel Fixes A/C/D, synced through `{prov['gpt_5_5_hard_0_29']['upstream_sync_commit']}`):** Primary `seeds 0-29` "
            f"(`data/runs/committed/v1.4/`, committed in `{prov['primary_0_29_lock']['episodes_commit']}`) "
            f"are governed by a **post-hoc lock** (`{prov['primary_0_29_lock']['lock_commit']}`, committed "
            f"`{prov['primary_0_29_lock']['lock_delay_s']} s` after `{prov['primary_0_29_lock']['episodes_commit']}`) "
            "against later reruns and cherry-picking, not a pre-registration (`20+10` solver reference split "
            "directories cover `0-19` and `20-29`). By contrast, the committed G1 hard extension on `seeds 30-59` "
            f"(`{prov['g1_hard_30_59_extension']['prereg_commit']}`, `opencode-gemini-4-carbon-ext/hard`, "
            f"`n={prov['g1_hard_30_59_extension']['n']}`, completed `seeds {prov['g1_hard_30_59_extension']['completed_seeds']}` "
            "before stopping to preserve shared carbon quota for the Harbor rehearsal) and the second frontier "
            f"family `gpt-5.5` (`{prov['gpt_5_5_hard_0_29']['prereg_commit']}`, shipped in `{prov['gpt_5_5_hard_0_29']['results_commit']}` "
            f"at `{prov['gpt_5_5_hard_0_29']['run_dir']}`, OpenCode "
            f"`{prov['gpt_5_5_hard_0_29']['opencode_version']}`, `{prov['gpt_5_5_hard_0_29']['timeout_cap_s']} s` "
            f"per-episode cap, `${prov['gpt_5_5_hard_0_29']['spend_cap_usd']}` spend cap, "
            f"`{prov['gpt_5_5_hard_0_29']['committed_v14_episodes']}` committed `v1.4` episodes with `0` infra exclusions "
            f"and `{len(prov['gpt_5_5_hard_0_29']['clean_rc0_non_accuse_zero_day_seeds'])}` clean `rc=0` non-accuse "
            f"`final_day=0` exits on `seeds {prov['gpt_5_5_hard_0_29']['clean_rc0_non_accuse_zero_day_seeds']}`) were "
            "**pre-registered** before any episode ran."
        ),
        (
            f"- **100% replay integrity (`{prov['step_error_detail_compat']['commit']}` `norm_result` order):** "
            f"`{comm_rv['verified']}/{comm_rv['total']}` committed `v1.4` episodes and "
            f"`{rep_rv['verified']}/{rep_rv['total']}` FR8 replication episodes "
            f"(`{s['total_pool_episodes_replay_verified']}/{comm_rv['total'] + rep_rv['total']}` total) pass "
            "step-by-step and ledger replay with `0` mismatches and `0` duplicates, unwrapping OpenCode "
            f"MCP error JSON first (`{comm_rv['unwrapped_mcp_error_steps']}` committed, "
            f"`{rep_rv['unwrapped_mcp_error_steps']}` replication steps) before matching pre-`1bc3e281` "
            f"`data={{}}` against live `data={{'detail': ...}}` (`{comm_rv['pre_1bc3e281_detail_normalized_steps']}` "
            f"committed, `{rep_rv['pre_1bc3e281_detail_normalized_steps']}` replication steps){clean_zero_clause}."
        ),
        (
            "- **Every mole archetype and department stratum is reliably solved by the reference solver:** "
            f"Across all `{hard_pooled['n']}` hard worlds (`0-59`), the Bayesian reference solver achieves "
            f"`{_pct(hard_pooled['accuracy'])}` accuracy (`{_pct(hard_pooled['precision_when_accusing'])}` precision "
            f"when accusing, raw `{_signed(hard_pooled['raw_mean'])}`, luck-adjusted "
            f"`{_signed(hard_pooled['luck_adj_mean'])}`), with strongly positive luck-adjusted scores across every "
            f"mole archetype (`{_signed(hp_arch['decoy_entangled']['luck'])}` on `decoy_entangled`, "
            f"`{_signed(hp_arch['deep_crowd_camouflage']['luck'])}` and `{_pct(hp_arch['deep_crowd_camouflage']['acc'])}` "
            f"`{hp_arch['deep_crowd_camouflage']['n']}/{hp_arch['deep_crowd_camouflage']['n']}` accuracy on "
            f"`deep_crowd_camouflage`, `{_signed(hp_arch['low_tempo_stealth']['luck'])}` on `low_tempo_stealth`, "
            f"`{_signed(hp_arch['high_tempo_exposed']['luck'])}` on `high_tempo_exposed`) and "
            f"every department-size stratum (`{_signed(hp_dept['compact_dept']['luck'])}` compact, "
            f"`{_signed(hp_dept['standard_dept']['luck'])}` standard, `{_signed(hp_dept['crowded_dept']['luck'])}` and "
            f"`{_pct(hp_dept['crowded_dept']['acc'])}` `{hp_dept['crowded_dept']['n']}/{hp_dept['crowded_dept']['n']}` "
            f"accuracy on `crowded_dept`). On `medium 0-29`, the solver achieves `{_pct(med_solv['precision_when_accusing'])}` "
            f"precision when accusing (`{med_solv['wrong_accusations']}` wrong accusations, `{med_solv['abstentions']}` "
            "calibrated abstentions)."
        ),
        (
            "- **Primary hard frontier gap is concentrated in crowded departments and low-tempo stealth moles, NOT decoy traps:** "
            f"On primary hard `0-29`, OpenCode `gemini-4-carbon` trails the solver by "
            f"`{_signed(oc_c_h0['overall']['l_gap'])}` V/episode luck-adjusted (`{_signed(oc_c_h0['overall']['r_gap'])}` raw). "
            f"Stratification shows the gap is driven by **`{c_arch_top[0]['stratum']}`** "
            f"(`n={c_arch_top[0]['n']}`, luck-adjusted gap `{_signed(c_arch_top[0]['luck_adj_gap'])}`, raw gap "
            f"`{_signed(c_arch_top[0]['raw_gap'])}`, accuracy `{_pct(c_arch_top[0]['accuracy'])}` vs solver "
            f"`{_pct(sol_h0_top_arch['acc'])}`) and **`{c_arch_top[1]['stratum']}`** "
            f"(`n={c_arch_top[1]['n']}`, luck-adjusted gap `{_signed(c_arch_top[1]['luck_adj_gap'])}`), and structurally by "
            f"**`{c_dept_top[0]['stratum']}`** (`mole_dept_size >= 11`, `n={c_dept_top[0]['n']}`, luck-adjusted gap "
            f"`{_signed(c_dept_top[0]['luck_adj_gap'])}`, raw gap `{_signed(c_dept_top[0]['raw_gap'])}`) and "
            f"**`{c_sol_top[0]['stratum']}`** (`solver_day 9-12`, `n={c_sol_top[0]['n']}`, luck-adjusted gap "
            f"`{_signed(c_sol_top[0]['luck_adj_gap'])}`). On `decoy_entangled` (`n={oc_c_decoy['n']}`), "
            "`gemini-4-carbon` is not fooled by the angry-message decoy "
            f"(luck-adjusted `{_signed(oc_c_decoy['luck'])}` vs solver `{_signed(sol_h0_decoy['luck'])}`).{gpt_contrast}"
        ),
        (
            "- **Extension hard `30-59` confirms both baseline scaling fragility and partial-cohort selection structure:** "
            f"Across full `seeds 30-59` (`n=30`), `grok_tactics` suffers its largest luck-adjusted deficit on "
            f"`{g_arch_top[0]['stratum']}` (`{_signed(g_arch_top[0]['luck_adj_gap'])}` V/ep) while `heuristic` "
            f"collapses on `{h_arch_top[0]['stratum']}` (`{_signed(h_arch_top[0]['luck_adj_gap'])}` V/ep) "
            f"and `{h_arch_top[1]['stratum']}` (`{_signed(h_arch_top[1]['luck_adj_gap'])}` V/ep). Meanwhile, the "
            f"deduplicated `6`-seed OpenCode `gemini-4-carbon` extension union (`seeds {u6_sel['union_seeds']}`, "
            f"committed G1 precedence on shared `seed 34`: G1 raw `{_signed(u6_sel['seed_34_g1_score'])}` / "
            f"luck-adj `{_signed(u6_sel['seed_34_g1_luck_adj'])}` vs FR8 raw `{_signed(u6_sel['seed_34_fr8_score'])}` / "
            f"luck-adj `{_signed(u6_sel['seed_34_fr8_luck_adj'])}`) contains "
            f"**`{u6_sel['deep_crowd_camouflage_count_in_union_6']}/{len(u6_sel['union_seeds'])}` `deep_crowd_camouflage` seeds** "
            f"and **`{u6_sel['crowded_dept_count_in_union_6']}/{len(u6_sel['union_seeds'])}` `crowded_dept` (`>=11`) seeds** "
            f"(mean `mole_dept_size = {_f(u6_sel['mean_mole_dept_size_union_6'], 2)}` vs "
            f"`{_f(u6_sel['mean_mole_dept_size_hard_0_29'], 2)}` on `hard 0-29` and "
            f"`{_f(u6_sel['mean_mole_dept_size_hard_30_59'], 2)}` on `hard 30-59`), structurally explaining why "
            "early quota-constrained completions outperform the full-distribution primary benchmark."
        ),
        flash_gate_bullet,
        "",
        _md_heading(2, "2. Deterministic World & Mole Policy Genome Extraction (90 Seeds)"),
        "",
        (
            "In `canary/env.py`, standard `medium` and `hard` episodes (`tier not in TRACKS`) run "
            f"`DEFAULT_STRATEGY` (`{gen['hard']['mole_policy_name']}`: `{gen['hard']['mole_dsl_rule_count']}` conditional "
            f"Mole DSL rules, `{gen['hard']['mole_dsl_default_leak_selector']}` leak selector weighted by `careful_mole` "
            "`1 - share`, and Poisson framing), whereas evolved HoF DSL and RL policies apply on the `hard_forge` "
            "and `hard_rl` tracks. Because `p_single_dept_recipients = 0.0` on both `medium` (`4` depts, `20` staff) "
            "and `hard` (`5` depts, `40` staff), **100% of regular documents are sent to two whole departments**: "
            "regular document leaks narrow suspects down to `mole_dept`, after which **only canary variants** (and weak "
            "after-hours/interview LRs) can separate the `mole_dept_size` colleagues."
        ),
        "",
        "| seed block | n | mole policy | mean mole dept size | same-dept decoy seeds | mean decoy doc overlap | mean mole doc share | realized mole log density / day | mean passive leaks (expected) | archetype counts (`decoy` / `crowd` / `stealth` / `exposed`) | dept counts (`compact` / `standard` / `crowded`) |",
        "|---|---:|---|---:|---:|---:|---:|---:|---|---|---|",
    ]

    for blk_label, tier_key, blk_key in (
        ("medium (0-29)", "medium", "medium_0_29"),
        ("hard (0-29)", "hard", "hard_0_29"),
        ("hard (30-59)", "hard", "hard_30_59"),
    ):
        pk = sp[blk_key]
        gm = gen[tier_key]
        ac = pk["mole_archetype_counts"]
        dc = pk["dept_stratum_counts"]
        lines.append(
            f"| {blk_label} | {pk['n_seeds']} | `{gm['mole_policy_name']}` | "
            f"{_f(pk['mean_mole_dept_size'], 2)} | {pk['same_dept_decoy_count']}/{pk['n_seeds']} | "
            f"{_f(pk['mean_decoy_doc_overlap_count'], 1)} | {_pct(pk['mean_mole_doc_share'])} | "
            f"{_f(pk['mean_realized_doc_access_density'], 2)} | "
            f"{_f(pk['mean_passive_leak_count'], 2)} ({_f(gm['expected_passive_leaks'], 2)}) | "
            f"{ac['decoy_entangled']} / {ac['deep_crowd_camouflage']} / "
            f"{ac['low_tempo_stealth']} / {ac['high_tempo_exposed']} | "
            f"{dc['compact_dept']} / {dc['standard_dept']} / {dc['crowded_dept']} |"
        )

    lines.extend(
        [
            "",
            "Seed-intrinsic stratification rules (zero dependence on frontier trajectories):",
            "- **`decoy_entangled`:** `same_dept_decoy == True` (`100%` regular-document overlap between mole and angry-message decoy, plus `50%` framed after-hours log share on the decoy).",
            "- **`deep_crowd_camouflage`:** non-entangled mole in a department of size `>= floor(n_employees / n_depts) + 2` (`>= 7` on `medium`, `>= 10` on `hard`), requiring multi-round 3-variant canary splitting inside `mole_dept`.",
            "- **`low_tempo_stealth`:** non-entangled mole in a compact/standard department with realized passive leaks `< n_days * p_leak` (`<= 10` on `medium`, `<= 13` on `hard`).",
            "- **`high_tempo_exposed`:** non-entangled mole in a compact/standard department with realized passive leaks `>= n_days * p_leak` (`>= 11` on `medium`, `>= 14` on `hard`).",
            "",
            _md_heading(2, "3. Primary Hard Seeds 0-29 Stratified Gap (Locked Headline Block)"),
            "",
            _md_heading(3, "3.1 By Realized Mole Behavioral Archetype"),
            "",
            *_render_stratum_rows(h0_cohorts, "by_mole_archetype", MOLE_ARCHETYPES),
            "",
            _md_heading(3, "3.2 By Mole Department Size & Solver Isolation Horizon"),
            "",
            *_render_stratum_rows(h0_cohorts, "by_dept_stratum", DEPT_STRATA),
            "",
            *_render_stratum_rows(h0_cohorts, "by_solver_difficulty", SOLVER_DIFFICULTY_STRATA),
            "",
            _md_heading(2, "4. Primary + FR8 Medium Seeds 0-29 Stratified Gap"),
            "",
            (
                f"On `medium` (`seeds 0-29`, `n={oc_c_m0['n']}`), OpenCode `gemini-4-carbon` achieves "
                f"`{_pct(oc_c_m0['overall']['acc'])}` accuracy across all four mole archetypes "
                f"(`{_signed(oc_c_m0['overall']['luck'])}` luck-adjusted vs solver "
                f"`{_signed(sol_m0['overall']['luck'])}`), whereas FR8 OpenCode `gemini-3.5-flash` "
                f"(`{_signed(oc_f_m0['overall']['luck'])}` luck-adjusted, gap "
                f"`{_signed(oc_f_m0['overall']['l_gap'])}`) collapses specifically on `low_tempo_stealth` "
                f"(`n={oc_f_m0_stealth['n']}`, accuracy `{_pct(oc_f_m0_stealth['acc'])}`, "
                f"luck-adjusted `{_signed(oc_f_m0_stealth['luck'])}`, gap `{_signed(oc_f_m0_stealth['l_gap'])}`), "
                f"and in-process `gemini-4-carbon` (`{_signed(ip_c_m0['overall']['luck'])}` luck-adjusted) "
                "drops most in `crowded_dept` (`>= 7` colleagues, luck-adjusted gap "
                f"`{_signed(ip_c_m0_crowd['l_gap'])}`):"
            ),
            "",
            *_render_stratum_rows(m0_cohorts, "by_mole_archetype", MOLE_ARCHETYPES),
            "",
            _md_heading(2, "5. Extension Hard Seeds 30-59: Reference, Baselines, G1, FR8, and 6-Seed Union"),
            "",
            (
                "Extension cohorts on `hard` (`seeds 30-59`) pair `solver` (`n=30`), `grok_tactics` (`n=30`), and "
                "`heuristic` (`n=30`) on all 30 seeds, alongside pre-registered G1 `opencode-gemini-4-carbon-ext` "
                f"(`seeds {g1_h30['seeds']}`, `n={g1_h30['n']}`), FR8 `opencode:google/gemini-4-carbon` replication "
                f"(`seeds {fr8_h30['seeds']}`, `n={fr8_h30['n']}`), and their deduplicated `{u6_h30['n']}`-seed union "
                f"(`seeds {u6_h30['seeds']}`, `n={u6_h30['n']}`, committed G1 precedence on `seed 34`), each paired "
                "against the exact same seeds in `solver_hard_30_59`:"
            ),
            "",
            _md_heading(3, "5.1 Extension Hard 30-59 by Mole Archetype"),
            "",
            *_render_stratum_rows(h30_cohorts, "by_mole_archetype", MOLE_ARCHETYPES),
            "",
            _md_heading(3, "5.2 Extension Hard 30-59 by Mole Department Size Stratum"),
            "",
            *_render_stratum_rows(h30_cohorts, "by_dept_stratum", DEPT_STRATA),
            "",
            _md_heading(2, "6. Pooled Hard 0-59 Reference Solver Solvability Proof (n=60)"),
            "",
            "| pooled hard 0-59 stratum | n | solver raw score | solver luck-adj. score | solver accuracy | precision when accusing | abstention rate | mean accuse day |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )

    for arch in MOLE_ARCHETYPES:
        st = hp_arch[arch]
        lines.append(
            f"| mole archetype: `{arch}` | {st['n']} | {_signed(st['raw'])} | "
            f"{_signed(st['luck'])} | {_pct(st['acc'])} | "
            f"{_pct(st['prec'])} | {_pct(st['abst'])} | "
            f"{_f(st['day'], 1)} |"
        )
    for ds in DEPT_STRATA:
        st = hp_dept[ds]
        lines.append(
            f"| dept size: `{ds}` | {st['n']} | {_signed(st['raw'])} | "
            f"{_signed(st['luck'])} | {_pct(st['acc'])} | "
            f"{_pct(st['prec'])} | {_pct(st['abst'])} | "
            f"{_f(st['day'], 1)} |"
        )

    lines.extend(
        [
            "",
            (
                f"Conclusion: across all `{hard_pooled['n']}` evaluated hard worlds (`0-59`) and "
                f"`{med_solv['n']}` medium worlds (`0-29`), no mole archetype or department stratum is broken "
                f"or unsolvable. The Bayesian reference solver maintains `{_signed(min_arch_luck)}` to "
                f"`{_signed(max_arch_luck)}` luck-adjusted value across every hard mole archetype "
                f"(`{_pct(hp_arch['deep_crowd_camouflage']['acc'])}` accuracy on all "
                f"`{hp_arch['deep_crowd_camouflage']['n']}/{hp_arch['deep_crowd_camouflage']['n']}` "
                f"`deep_crowd_camouflage` worlds and `{_pct(hp_dept['crowded_dept']['acc'])}` on all "
                f"`{hp_dept['crowded_dept']['n']}/{hp_dept['crowded_dept']['n']}` `crowded_dept` worlds), "
                "whereas frontier models that under-invest daily actions in `plant_canary` lose posterior "
                "resolution precisely where intra-departmental anonymity pools (`>= 10-14` staff) or below-average "
                "leak tempo (`low_tempo_stealth`) demand sustained multi-canary bisection."
            ),
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(root: Path = ROOT, out_json: Path | None = None, out_md: Path | None = None) -> int:
    jpath = out_json or default_json_path(root)
    mpath = out_md or default_md_path(root)
    audit = compute_audit(root=root, verify_replays=True, enforce_expected_counts=True)
    jblob = serialize_audit_json(audit)
    mblob = render_markdown(audit)
    jpath.parent.mkdir(parents=True, exist_ok=True)
    mpath.parent.mkdir(parents=True, exist_ok=True)
    jpath.write_text(jblob, encoding="utf-8")
    mpath.write_text(mblob, encoding="utf-8")
    return 0


def check_outputs(root: Path = ROOT, out_json: Path | None = None, out_md: Path | None = None) -> int:
    jpath = out_json or default_json_path(root)
    mpath = out_md or default_md_path(root)
    if not jpath.exists() or not mpath.exists():
        print(f"missing output file(s): {jpath}, {mpath}", file=sys.stderr)
        return 1
    raw_bytes = jpath.read_bytes()
    if len(raw_bytes) > MAX_JSON_BYTES:
        print(
            f"JSON output {jpath} is {len(raw_bytes)} bytes, exceeding {MAX_JSON_BYTES}",
            file=sys.stderr,
        )
        return 1
    try:
        disk_json = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        print(f"invalid JSON in {jpath}: {exc}", file=sys.stderr)
        return 1
    expected_audit = compute_audit(root=root, verify_replays=True, enforce_expected_counts=True)
    expected_json = json.loads(serialize_audit_json(expected_audit))
    if not approx_equal(disk_json, expected_json, tol=1e-6):
        print(f"JSON mismatch in {jpath}", file=sys.stderr)
        return 1
    disk_md = mpath.read_text(encoding="utf-8")
    expected_md = render_markdown(expected_audit)
    if disk_md != expected_md:
        print(f"Markdown mismatch in {mpath}", file=sys.stderr)
        return 1
    summ = expected_audit["summary"]
    print(
        f"OK mole_stratified_gap=PASS worlds={summ['worlds_extracted']} "
        f"committed_replays={summ['committed_v14_verified']} "
        f"replication_replays={summ['replication_v14_verified']} "
        f"combined_replays={summ['total_pool_episodes_replay_verified']}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Pure-CPU mole-archetype and seed-difficulty stratification audit for Canary v1.4."
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    grp = ap.add_mutually_exclusive_group(required=True)
    grp.add_argument("--write", action="store_true")
    grp.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    if args.write:
        return write_outputs(root=args.root, out_json=args.out_json, out_md=args.out_md)
    return check_outputs(root=args.root, out_json=args.out_json, out_md=args.out_md)


if __name__ == "__main__":
    raise SystemExit(main())
