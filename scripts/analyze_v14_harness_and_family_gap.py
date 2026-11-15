"""Deterministic keyless synthesis of v1.4 harness gap, model-tier gap, and 30-59 extension head-to-head."""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import math
import operator
import os
import random
import statistics
import sys
from multiprocessing import get_all_start_methods, get_context
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRIMARY_SEEDS = list(range(0, 30))
HEURISTIC_COMMITTED_SEEDS = list(range(0, 20))
EXT_ALL_SEEDS = list(range(30, 60))
ALL_60_SEEDS = list(range(0, 60))
G1_SEEDS = [34, 37]
FLEET7_SEEDS = [30, 34, 42, 45, 48, 57, 58]
OBSERVED_EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]
UNOBSERVED_EXT22_SEEDS = [s for s in EXT_ALL_SEEDS if s not in OBSERVED_EXT8_SEEDS]
POOLED32_SEEDS = PRIMARY_SEEDS + G1_SEEDS
POOLED38_SEEDS = PRIMARY_SEEDS + OBSERVED_EXT8_SEEDS

CARBON_OC_AGENT = "opencode:google/gemini-4-carbon"
CARBON_INPROC_AGENT = "gemini:gemini-4-carbon"
FLASH_OC_AGENT = "opencode:google/gemini-3.5-flash"
ARGON_OC_AGENT = "opencode:google/gemini-4-argon"
HYDROGEN_OC_AGENT = "opencode:google/gemini-4-hydrogen"
GPT55_OC_AGENT = "opencode:openai/gpt-5.5"
SOLVER_AGENT = "solver"
HEURISTIC_AGENT = "heuristic"

OPTIONAL_G2_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "opencode_argon",
        "opencode-gemini-4-argon",
        ARGON_OC_AGENT,
        "OpenCode + gemini-4-argon over MCP (G2 family)",
    ),
    (
        "opencode_hydrogen",
        "opencode-gemini-4-hydrogen",
        HYDROGEN_OC_AGENT,
        "OpenCode + gemini-4-hydrogen over MCP (G2 family)",
    ),
    (
        "opencode_gpt55",
        "opencode-gpt-5.5",
        GPT55_OC_AGENT,
        "OpenCode + gpt-5.5 over MCP (second frontier family)",
    ),
)

CORE_MATRIX_ORDER: tuple[str, ...] = (
    "opencode_carbon",
    "inproc_carbon",
    "opencode_flash",
    "solver",
    "heuristic",
)

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
MINUS_SIGN = chr(0x2212)
HASH = chr(35)
H1 = HASH + " "
H2 = HASH * 2 + " "
H3 = HASH * 3 + " "
DEFAULT_REPORT_REL = Path("docs/reports/frontier_v14_harness_and_ext_synthesis.md")
TIE_TOL = 1e-9

_BOOT_IDX_CACHE: dict[tuple[int, int, int], list[tuple[int, ...]]] = {}
_BOOT_GETTERS_CACHE: dict[tuple[int, int, int], list[Any]] = {}
_BOOT_MEANS_CACHE: dict[tuple[tuple[float, ...], int, int], list[float]] = {}
_BOOT_PAIR_CACHE: dict[
    tuple[tuple[float, ...], tuple[float, ...], int, int],
    tuple[tuple[float, float], tuple[float, float]],
] = {}
_SIGN_FLIP_CACHE: dict[tuple[int, int, int], list[tuple[bool, ...]]] = {}
_SIGN_FLIP_RES_CACHE: dict[tuple[tuple[float, ...], int, int], float] = {}
_EP_OBS_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_HEURISTIC_EP_CACHE: dict[tuple[str, str, int], dict[str, Any]] = {}
_FILE_JSONL_CACHE: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
_FORK_WORK_EPS: list[dict[str, Any]] = []


def _seq_getter(idx: tuple[int, ...]) -> Any:
    if len(idx) == 1:
        i0 = idx[0]
        return lambda seq: (seq[i0],)
    return operator.itemgetter(*idx)


def _get_boot_indices(n: int, n_boot: int, rng_seed: int) -> list[tuple[int, ...]]:
    key = (n, n_boot, rng_seed)
    cached = _BOOT_IDX_CACHE.get(key)
    if cached is not None:
        return cached
    rng = random.Random(rng_seed)
    randrange = rng.randrange
    rows = [tuple(randrange(n) for _ in range(n)) for _ in range(n_boot)]
    _BOOT_IDX_CACHE[key] = rows
    return rows


def _get_boot_getters(n: int, n_boot: int, rng_seed: int) -> list[Any]:
    key = (n, n_boot, rng_seed)
    cached = _BOOT_GETTERS_CACHE.get(key)
    if cached is not None:
        return cached
    getters = [_seq_getter(idx) for idx in _get_boot_indices(n, n_boot, rng_seed)]
    _BOOT_GETTERS_CACHE[key] = getters
    return getters


def _get_boot_means(arr: list[float], n_boot: int, rng_seed: int) -> list[float]:
    arr_t = tuple(arr)
    key = (arr_t, n_boot, rng_seed)
    cached = _BOOT_MEANS_CACHE.get(key)
    if cached is not None:
        return cached
    n = len(arr_t)
    means = [sum(g(arr_t)) / n for g in _get_boot_getters(n, n_boot, rng_seed)]
    _BOOT_MEANS_CACHE[key] = means
    return means


def _boot_ratio_and_diff(
    arr_a: list[float],
    arr_b: list[float],
    n_boot: int = 10000,
    rng_seed: int = 0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    if len(arr_a) <= 1:
        return (float("nan"), float("nan")), (float("nan"), float("nan"))
    pair_key = (tuple(arr_a), tuple(arr_b), n_boot, rng_seed)
    cached = _BOOT_PAIR_CACHE.get(pair_key)
    if cached is not None:
        return cached
    mas = _get_boot_means(arr_a, n_boot, rng_seed)
    mbs = _get_boot_means(arr_b, n_boot, rng_seed)
    diffs = sorted(ma - mb for ma, mb in zip(mas, mbs))
    d_lo = diffs[int(0.025 * len(diffs))]
    d_hi = diffs[int(0.975 * len(diffs)) - 1]
    ratios = sorted(ma / mb for ma, mb in zip(mas, mbs) if mb > 0.0)
    if not ratios:
        res = ((float("nan"), float("nan")), (d_lo, d_hi))
    else:
        r_lo = ratios[int(0.025 * len(ratios))]
        r_hi = ratios[int(0.975 * len(ratios)) - 1]
        res = ((r_lo, r_hi), (d_lo, d_hi))
    _BOOT_PAIR_CACHE[pair_key] = res
    return res


def _get_sign_flips(n: int, n_perm: int, rng_seed: int) -> list[tuple[bool, ...]]:
    key = (n, n_perm, rng_seed)
    cached = _SIGN_FLIP_CACHE.get(key)
    if cached is not None:
        return cached
    rng = random.Random(rng_seed)
    getrandbits = rng.getrandbits
    rows: list[tuple[bool, ...]] = []
    for _ in range(n_perm):
        bits = getrandbits(n)
        rows.append(tuple(bool((bits >> i) & 1) for i in range(n)))
    _SIGN_FLIP_CACHE[key] = rows
    return rows


def _paired_sign_flip_p(diffs: list[float], n_perm: int = 10000, rng_seed: int = 0) -> float:
    n = len(diffs)
    if n == 0:
        return float("nan")
    obs_abs = abs(sum(diffs) / n)
    if obs_abs <= 1e-15:
        return 1.0
    first_nz = next((d for d in diffs if abs(d) > 1e-15), 0.0)
    canon_t = tuple(diffs) if first_nz >= 0.0 else tuple(-d for d in diffs)
    res_key = (canon_t, n_perm, rng_seed)
    cached = _SIGN_FLIP_RES_CACHE.get(res_key)
    if cached is not None:
        return cached
    if n <= 12:
        total = 1 << n
        extreme = 0
        for mask in range(total):
            s = 0.0
            for i in range(n):
                s += diffs[i] if ((mask >> i) & 1) else -diffs[i]
            if abs(s / n) >= obs_abs - 1e-12:
                extreme += 1
        out = extreme / total
        _SIGN_FLIP_RES_CACHE[res_key] = out
        return out
    total_sum = sum(canon_t)
    threshold = obs_abs * n - 1e-12
    compress = itertools.compress
    extreme = 0
    for mask_bools in _get_sign_flips(n, n_perm, rng_seed):
        val_sum = abs(2.0 * sum(compress(canon_t, mask_bools)) - total_sum)
        if val_sum >= threshold:
            extreme += 1
    out = (extreme + 1) / (n_perm + 1)
    _SIGN_FLIP_RES_CACHE[res_key] = out
    return out


def _load_valid_jsonl(path: Path) -> list[dict[str, Any]]:
    st = path.stat()
    fkey = (str(path.resolve()), st.st_mtime_ns, st.st_size)
    cached = _FILE_JSONL_CACHE.get(fkey)
    if cached is not None:
        return list(cached)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        if (ep.get("meta") or {}).get("valid") is False:
            continue
        rows.append(ep)
    _FILE_JSONL_CACHE[fkey] = rows
    return list(rows)


def _heuristic_worker_seed(seed: int) -> tuple[int, dict[str, Any]]:
    from canary import rules
    from canary.baselines import Heuristic
    from canary.env import Env
    from canary.eval import run_episode

    with rules.tiers_version("v1.4"):
        res = run_episode(Env("hard", seed), Heuristic(seed=seed))
    return seed, dataclasses.asdict(res)


def _ep_cache_key(ep: dict[str, Any], tiers_version: str) -> tuple[Any, ...]:
    steps = ep.get("steps") or []
    meta = ep.get("meta") or {}
    v_raw = meta.get("V", meta.get("V_final"))
    return (
        tiers_version,
        str(ep.get("agent")),
        str(ep.get("tier")),
        int(ep["seed"]),
        len(steps),
        float(ep["score"]),
        ep.get("accused"),
        int(ep["final_day"]),
        float(v_raw) if v_raw is not None else None,
    )


def _fork_obs_worker(idx: int) -> tuple[int, dict[str, Any]]:
    from canary import rules

    with rules.tiers_version("v1.4"):
        return idx, _episode_observables(_FORK_WORK_EPS[idx])


def _heuristic_episode(tier: str, seed: int, tiers_version: str = "v1.4") -> dict[str, Any]:
    key = (tiers_version, tier, seed)
    cached = _HEURISTIC_EP_CACHE.get(key)
    if cached is not None:
        return cached
    from canary import rules
    from canary.baselines import Heuristic
    from canary.env import Env
    from canary.eval import run_episode

    with rules.tiers_version(tiers_version):
        res = run_episode(Env(tier, seed), Heuristic(seed=seed))
    ep_dict = dataclasses.asdict(res)
    _HEURISTIC_EP_CACHE[key] = ep_dict
    return ep_dict


def _episode_observables(ep: dict[str, Any]) -> dict[str, Any]:
    from canary import rules
    from canary.analysis.accuse import audit_episode
    from canary.analysis.tags import to_result

    steps = ep.get("steps") or []
    meta = ep.get("meta") or {}
    v_raw = meta.get("V", meta.get("V_final"))
    cache_key = _ep_cache_key(ep, str(rules.TIERS_VERSION))
    cached = _EP_OBS_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    accused = ep.get("accused")
    abstained = accused is None
    correct = bool(ep.get("correct", False))
    raw_score = float(ep["score"])
    if abstained:
        v_val: float | None = float(v_raw) if v_raw is not None else None
        p_acc = None
        p_top = None
        verdict = "abstained"
        la_score = 0.0
        accuse_day = None
        raw_final_day = int(ep["final_day"])
        if raw_final_day > 0:
            horizon_day = raw_final_day
        else:
            horizon_day = max(
                (int(st.get("day", 0)) for st in steps if isinstance(st, dict) and st.get("day") is not None),
                default=0,
            )
        exp_wrong = 0.0
        sub_085 = False
        neg_ev = False
    else:
        if v_raw is None:
            raise ValueError(f"missing V in meta for seed={ep.get('seed')} agent={ep.get('agent')}")
        v_val = float(v_raw)
        aud = audit_episode(to_result(ep))
        p_acc = aud["p_accused"]
        p_top = aud["p_top"]
        verdict = str(aud["verdict"])
        if p_acc is None:
            raise ValueError(f"missing p_accused for accused episode seed={ep.get('seed')}")
        p_f = float(p_acc)
        la_score = p_f * v_val - (1.0 - p_f)
        accuse_day = int(aud["day"])
        horizon_day = int(aud["day"])
        exp_wrong = 1.0 - p_f
        sub_085 = p_f < 0.85 - 1e-12
        neg_ev = la_score < -1e-12

    canaries = sum(
        1
        for st in steps
        if isinstance(st, dict)
        and st.get("tool") == "plant_canary"
        and (st.get("result") or {}).get("ok") is not False
    )
    interviews = sum(
        1
        for st in steps
        if isinstance(st, dict)
        and st.get("tool") == "interview"
        and (st.get("result") or {}).get("ok") is not False
    )
    out = {
        "seed": int(ep["seed"]),
        "agent": str(ep["agent"]),
        "tier": str(ep["tier"]),
        "raw_score": raw_score,
        "luck_adjusted_score": la_score,
        "luck_windfall": raw_score - la_score,
        "accused": accused,
        "correct": correct,
        "abstained": abstained,
        "wrong": (not abstained) and (not correct),
        "accuse_day": accuse_day,
        "final_day": int(ep["final_day"]),
        "horizon_day": horizon_day,
        "total_steps": len(steps),
        "canary_count": canaries,
        "interview_count": interviews,
        "company_value_v": v_val,
        "p_accused": float(p_acc) if p_acc is not None else None,
        "p_top": float(p_top) if p_top is not None else None,
        "expected_wrong": exp_wrong,
        "sub_085": sub_085,
        "negative_ev": neg_ev,
        "verdict": verdict,
    }
    _EP_OBS_CACHE[cache_key] = out
    return dict(out)


def _summarize_paired_cohort(
    cohort_id: str,
    label: str,
    agent: str,
    tier: str,
    seeds: list[int],
    obs_map: dict[int, dict[str, Any]],
    solver_obs_map: dict[int, dict[str, Any]],
    is_solver: bool = False,
) -> dict[str, Any]:
    from canary.analysis.gap import mean_ci

    rows = [obs_map[s] for s in seeds]
    sol_rows = [solver_obs_map[s] for s in seeds]
    n = len(rows)

    raw_vals = [r["raw_score"] for r in rows]
    la_vals = [r["luck_adjusted_score"] for r in rows]
    sol_raw_vals = [r["raw_score"] for r in sol_rows]
    sol_la_vals = [r["luck_adjusted_score"] for r in sol_rows]

    raw_mean, raw_ci = mean_ci(raw_vals)
    la_mean, la_ci = mean_ci(la_vals)
    sol_raw_mean, sol_raw_ci = mean_ci(sol_raw_vals)
    sol_la_mean, sol_la_ci = mean_ci(sol_la_vals)

    raw_diff_mean, raw_diff_ci = mean_ci([x - y for x, y in zip(raw_vals, sol_raw_vals)])
    la_diff_mean, la_diff_ci = mean_ci([x - y for x, y in zip(la_vals, sol_la_vals)])

    raw_ratio = raw_mean / sol_raw_mean if sol_raw_mean > 0.0 else float("nan")
    la_ratio = la_mean / sol_la_mean if sol_la_mean > 0.0 else float("nan")

    if is_solver or n <= 1:
        raw_r_lo, raw_r_hi = float("nan"), float("nan")
        la_r_lo, la_r_hi = float("nan"), float("nan")
        raw_d_lo, raw_d_hi = float("nan"), float("nan")
        la_d_lo, la_d_hi = float("nan"), float("nan")
    else:
        (raw_r_lo, raw_r_hi), (raw_d_lo, raw_d_hi) = _boot_ratio_and_diff(raw_vals, sol_raw_vals, n_boot=10000, rng_seed=0)
        (la_r_lo, la_r_hi), (la_d_lo, la_d_hi) = _boot_ratio_and_diff(la_vals, sol_la_vals, n_boot=10000, rng_seed=0)

    acc_days = [float(r["accuse_day"]) for r in rows if r["accuse_day"] is not None]
    p_vals = [float(r["p_accused"]) for r in rows if r["p_accused"] is not None]
    step_vals = [float(r["total_steps"]) for r in rows]
    can_vals = [float(r["canary_count"]) for r in rows]
    itv_vals = [float(r["interview_count"]) for r in rows]
    hor_vals = [float(r["horizon_day"]) for r in rows]

    steps_mean, steps_ci = mean_ci(step_vals)
    can_mean, can_ci = mean_ci(can_vals)
    itv_mean, itv_ci = mean_ci(itv_vals)

    return {
        "id": cohort_id,
        "label": label,
        "agent": agent,
        "tier": tier,
        "n": n,
        "seeds": list(seeds),
        "raw_mean": raw_mean,
        "raw_ci": raw_ci,
        "luck_adjusted_mean": la_mean,
        "luck_adjusted_ci": la_ci,
        "luck_windfall_mean": raw_mean - la_mean,
        "accuracy": sum(1 for r in rows if r["correct"]) / n,
        "correct_count": sum(1 for r in rows if r["correct"]),
        "wrong_count": sum(1 for r in rows if r["wrong"]),
        "abstention_count": sum(1 for r in rows if r["abstained"]),
        "accused_count": sum(1 for r in rows if not r["abstained"]),
        "accused_rate": sum(1 for r in rows if not r["abstained"]) / n,
        "expected_wrong_sum": sum(r["expected_wrong"] for r in rows),
        "sub_085_count": sum(1 for r in rows if r["sub_085"]),
        "negative_ev_count": sum(1 for r in rows if r["negative_ev"]),
        "accuse_day_mean": sum(acc_days) / len(acc_days) if acc_days else float("nan"),
        "horizon_day_mean": sum(hor_vals) / n,
        "p_accused_mean": sum(p_vals) / len(p_vals) if p_vals else float("nan"),
        "p_accused_median": float(statistics.median(p_vals)) if p_vals else float("nan"),
        "steps_mean": steps_mean,
        "steps_ci": steps_ci,
        "canary_mean": can_mean,
        "canary_ci": can_ci,
        "interview_mean": itv_mean,
        "interview_ci": itv_ci,
        "solver_raw_mean": sol_raw_mean,
        "solver_raw_ci": sol_raw_ci,
        "raw_diff": raw_diff_mean,
        "raw_diff_ci": raw_diff_ci,
        "raw_diff_boot_lo": raw_d_lo,
        "raw_diff_boot_hi": raw_d_hi,
        "raw_ratio": raw_ratio,
        "raw_ratio_lo": raw_r_lo,
        "raw_ratio_hi": raw_r_hi,
        "solver_luck_adjusted_mean": sol_la_mean,
        "solver_luck_adjusted_ci": sol_la_ci,
        "luck_adjusted_diff": la_diff_mean,
        "luck_adjusted_diff_ci": la_diff_ci,
        "luck_adjusted_diff_boot_lo": la_d_lo,
        "luck_adjusted_diff_boot_hi": la_d_hi,
        "luck_adjusted_ratio": la_ratio,
        "luck_adjusted_ratio_lo": la_r_lo,
        "luck_adjusted_ratio_hi": la_r_hi,
    }


def _metric_wtl(
    vals_a: list[float],
    vals_b: list[float],
    seeds: list[int],
    tol: float = TIE_TOL,
) -> dict[str, Any]:
    from canary.analysis.gap import mean_ci

    n = len(seeds)
    win_seeds: list[int] = []
    tie_seeds: list[int] = []
    loss_seeds: list[int] = []
    diffs: list[float] = []
    for s, va, vb in zip(seeds, vals_a, vals_b):
        d = va - vb
        diffs.append(d)
        if d > tol:
            win_seeds.append(s)
        elif d < -tol:
            loss_seeds.append(s)
        else:
            tie_seeds.append(s)

    mean_a = sum(vals_a) / n
    mean_b = sum(vals_b) / n
    wins = len(win_seeds)
    ties = len(tie_seeds)
    losses = len(loss_seeds)
    if wins == 0 and losses == 0:
        ratio = 1.0 if abs(mean_b) > 1e-12 else float("nan")
        r_lo = ratio
        r_hi = ratio
        return {
            "n": n,
            "wins": 0,
            "ties": ties,
            "losses": 0,
            "wtl": f"0-{ties}-0",
            "win_rate": 0.5,
            "strict_win_rate": 0.0,
            "win_seeds": [],
            "tie_seeds": tie_seeds,
            "loss_seeds": [],
            "mean_a": mean_a,
            "mean_b": mean_b,
            "diff": 0.0,
            "diff_ci": 0.0,
            "diff_boot_lo": 0.0,
            "diff_boot_hi": 0.0,
            "ratio": ratio,
            "ratio_lo": r_lo,
            "ratio_hi": r_hi,
            "sign_flip_p_two_sided": 1.0,
        }
    diff_mean, diff_ci = mean_ci(diffs)
    (r_lo, r_hi), (d_lo, d_hi) = _boot_ratio_and_diff(vals_a, vals_b, n_boot=10000, rng_seed=0)
    ratio = mean_a / mean_b if abs(mean_b) > 1e-12 else float("nan")
    return {
        "n": n,
        "wins": wins,
        "ties": ties,
        "losses": losses,
        "wtl": f"{wins}-{ties}-{losses}",
        "win_rate": (wins + 0.5 * ties) / n,
        "strict_win_rate": wins / n,
        "win_seeds": win_seeds,
        "tie_seeds": tie_seeds,
        "loss_seeds": loss_seeds,
        "mean_a": mean_a,
        "mean_b": mean_b,
        "diff": diff_mean,
        "diff_ci": diff_ci,
        "diff_boot_lo": d_lo,
        "diff_boot_hi": d_hi,
        "ratio": ratio,
        "ratio_lo": r_lo,
        "ratio_hi": r_hi,
        "sign_flip_p_two_sided": _paired_sign_flip_p(diffs, n_perm=10000, rng_seed=0),
    }


def _head_to_head(
    pair_id: str,
    id_a: str,
    label_a: str,
    obs_a: dict[int, dict[str, Any]],
    id_b: str,
    label_b: str,
    obs_b: dict[int, dict[str, Any]],
    seeds: list[int],
) -> dict[str, Any]:
    raw_a = [obs_a[s]["raw_score"] for s in seeds]
    raw_b = [obs_b[s]["raw_score"] for s in seeds]
    la_a = [obs_a[s]["luck_adjusted_score"] for s in seeds]
    la_b = [obs_b[s]["luck_adjusted_score"] for s in seeds]
    return {
        "id": pair_id,
        "agent_a": id_a,
        "label_a": label_a,
        "agent_b": id_b,
        "label_b": label_b,
        "n": len(seeds),
        "seeds": list(seeds),
        "raw": _metric_wtl(raw_a, raw_b, seeds),
        "luck_adjusted": _metric_wtl(la_a, la_b, seeds),
    }


def _load_seed_map(
    jsonl_path: Path,
    expected_agent: str,
    expected_tier: str,
    expected_seeds: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    if not jsonl_path.is_file():
        raise FileNotFoundError(f"missing episodes file: {jsonl_path}")
    eps = _load_valid_jsonl(jsonl_path)
    by_seed: dict[int, dict[str, Any]] = {}
    for ep in eps:
        if ep.get("agent") != expected_agent or ep.get("tier") != expected_tier:
            raise ValueError(
                f"unexpected record in {jsonl_path}: agent={ep.get('agent')!r} tier={ep.get('tier')!r}"
            )
        seed = int(ep["seed"])
        if seed in by_seed:
            raise ValueError(f"duplicate seed={seed} in {jsonl_path}")
        by_seed[seed] = ep
    if expected_seeds is not None and sorted(by_seed) != expected_seeds:
        raise ValueError(f"expected seeds {expected_seeds} in {jsonl_path}, got {sorted(by_seed)}")
    return by_seed


def _load_sharded_seed_map(
    ref_root: Path,
    glob_pat: str,
    expected_agent: str,
    expected_tier: str,
    expected_seeds: list[int],
) -> dict[int, dict[str, Any]]:
    files = sorted(ref_root.glob(glob_pat))
    if not files:
        raise FileNotFoundError(f"no {glob_pat} shards found under {ref_root}")
    by_seed: dict[int, dict[str, Any]] = {}
    for sf in files:
        for ep in _load_valid_jsonl(sf):
            if ep.get("agent") != expected_agent or ep.get("tier") != expected_tier:
                raise ValueError(f"unexpected record in {sf}: agent={ep.get('agent')!r} tier={ep.get('tier')!r}")
            seed = int(ep["seed"])
            if seed in by_seed:
                raise ValueError(f"duplicate seed={seed} across {glob_pat}")
            by_seed[seed] = ep
    if sorted(by_seed) != expected_seeds:
        raise ValueError(f"expected seeds {expected_seeds} across {glob_pat}, got {sorted(by_seed)}")
    return by_seed


def analyze_harness_and_family_gap(
    repo: Path | str = ROOT,
    committed_root: Path | str | None = None,
    committed_ext_jsonl: Path | str | None = None,
    fleet_ext_jsonl: Path | str | None = None,
) -> dict[str, Any]:
    global _FORK_WORK_EPS
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    from canary import rules

    repo_path = Path(repo).resolve()
    default_comm_root = repo_path / "data" / "runs" / "committed"
    comm_root = Path(committed_root).resolve() if committed_root is not None else default_comm_root
    comm_v14 = comm_root / "v1.4"
    fallback_v14 = default_comm_root / "v1.4"
    ref_root = comm_v14 / "reference"

    oc_hard_by_seed = _load_seed_map(
        comm_v14 / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl",
        CARBON_OC_AGENT,
        "hard",
        PRIMARY_SEEDS,
    )
    ip_hard_by_seed = _load_seed_map(
        comm_v14 / "inproc-gemini-4-carbon" / "hard" / "episodes.jsonl",
        CARBON_INPROC_AGENT,
        "hard",
        PRIMARY_SEEDS,
    )
    fl_hard_by_seed = _load_seed_map(
        comm_v14 / "opencode-gemini-3.5-flash" / "hard" / "episodes.jsonl",
        FLASH_OC_AGENT,
        "hard",
        PRIMARY_SEEDS,
    )
    solver_hard_by_seed = _load_sharded_seed_map(
        ref_root,
        "solver-hard-*/episodes.jsonl",
        SOLVER_AGENT,
        "hard",
        ALL_60_SEEDS,
    )

    med_oc_path = comm_v14 / "opencode-gemini-4-carbon" / "medium" / "episodes.jsonl"
    med_ip_path = comm_v14 / "inproc-gemini-4-carbon" / "medium" / "episodes.jsonl"
    med_ref_root = ref_root
    if not med_oc_path.is_file() and (fallback_v14 / "opencode-gemini-4-carbon" / "medium" / "episodes.jsonl").is_file():
        med_oc_path = fallback_v14 / "opencode-gemini-4-carbon" / "medium" / "episodes.jsonl"
    if not med_ip_path.is_file() and (fallback_v14 / "inproc-gemini-4-carbon" / "medium" / "episodes.jsonl").is_file():
        med_ip_path = fallback_v14 / "inproc-gemini-4-carbon" / "medium" / "episodes.jsonl"
    if not list(med_ref_root.glob("solver-medium-*/episodes.jsonl")) and list(
        (fallback_v14 / "reference").glob("solver-medium-*/episodes.jsonl")
    ):
        med_ref_root = fallback_v14 / "reference"

    oc_med_by_seed = _load_seed_map(med_oc_path, CARBON_OC_AGENT, "medium", PRIMARY_SEEDS)
    ip_med_by_seed = _load_seed_map(med_ip_path, CARBON_INPROC_AGENT, "medium", PRIMARY_SEEDS)
    solver_med_by_seed = _load_sharded_seed_map(
        med_ref_root,
        "solver-medium-*/episodes.jsonl",
        SOLVER_AGENT,
        "medium",
        PRIMARY_SEEDS,
    )

    heur_files = sorted(ref_root.glob("heuristic-hard-*/episodes.jsonl"))
    if not heur_files:
        raise FileNotFoundError(f"no heuristic-hard-*/episodes.jsonl found under {ref_root}")
    heur_committed_by_seed: dict[int, dict[str, Any]] = {}
    for hf in heur_files:
        for ep in _load_valid_jsonl(hf):
            if ep.get("agent") != HEURISTIC_AGENT or ep.get("tier") != "hard":
                raise ValueError(f"unexpected heuristic record in {hf}")
            seed = int(ep["seed"])
            if seed in heur_committed_by_seed:
                raise ValueError(f"duplicate heuristic hard seed={seed}")
            heur_committed_by_seed[seed] = ep
    if not set(HEURISTIC_COMMITTED_SEEDS).issubset(heur_committed_by_seed):
        raise ValueError(f"expected committed heuristic seeds 0..19, got {sorted(heur_committed_by_seed)}")

    missing_heur_seeds = [
        s
        for s in ALL_60_SEEDS
        if (s in HEURISTIC_COMMITTED_SEEDS or s not in heur_committed_by_seed)
        and ("v1.4", "hard", s) not in _HEURISTIC_EP_CACHE
    ]
    mod_self = sys.modules.get(__name__)
    n_workers = min(12, os.cpu_count() or 1)
    can_fork = (
        n_workers > 1
        and "fork" in get_all_start_methods()
        and getattr(mod_self, "_heuristic_worker_seed", None) is _heuristic_worker_seed
        and getattr(mod_self, "_fork_obs_worker", None) is _fork_obs_worker
    )
    if len(missing_heur_seeds) >= 8 and can_fork:
        try:
            with get_context("fork").Pool(n_workers) as pool:
                for s_out, ep_out in pool.map(_heuristic_worker_seed, missing_heur_seeds, chunksize=4):
                    _HEURISTIC_EP_CACHE[("v1.4", "hard", s_out)] = ep_out
        except OSError:
            pass

    for seed in HEURISTIC_COMMITTED_SEEDS:
        ce = heur_committed_by_seed[seed]
        de = _heuristic_episode("hard", seed, "v1.4")
        if (
            abs(float(ce["score"]) - float(de["score"])) > 1e-12
            or ce.get("accused") != de.get("accused")
            or int(ce["final_day"]) != int(de["final_day"])
            or len(ce.get("steps") or []) != len(de.get("steps") or [])
        ):
            raise ValueError(f"committed heuristic seed={seed} diverges from deterministic Heuristic(seed={seed})")

    heur_hard_by_seed: dict[int, dict[str, Any]] = {}
    for seed in ALL_60_SEEDS:
        if seed in heur_committed_by_seed:
            heur_hard_by_seed[seed] = heur_committed_by_seed[seed]
        else:
            heur_hard_by_seed[seed] = _heuristic_episode("hard", seed, "v1.4")

    comm_ext_path = (
        Path(committed_ext_jsonl).resolve()
        if committed_ext_jsonl is not None
        else comm_v14 / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    )
    fleet_ext_path = (
        Path(fleet_ext_jsonl).resolve()
        if fleet_ext_jsonl is not None
        else repo_path / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    )
    if not comm_ext_path.is_file():
        raise FileNotFoundError(f"missing committed extension episodes file: {comm_ext_path}")

    comm_ext_eps = _load_valid_jsonl(comm_ext_path)
    comm_ext_seeds = [int(ep["seed"]) for ep in comm_ext_eps]
    if comm_ext_seeds not in (G1_SEEDS, OBSERVED_EXT8_SEEDS):
        raise ValueError(
            f"committed ext seeds {comm_ext_seeds} must be either {G1_SEEDS} (justSilas) or {OBSERVED_EXT8_SEEDS} (PR {HASH}3)"
        )
    for ep in comm_ext_eps:
        if ep.get("agent") != CARBON_OC_AGENT or ep.get("tier") != "hard":
            raise ValueError(f"unexpected committed ext record seed={ep.get('seed')}")
    comm_ext_by_seed = {int(ep["seed"]): ep for ep in comm_ext_eps}

    fleet_eps: list[dict[str, Any]] = []
    if fleet_ext_path.is_file():
        fleet_eps = _load_valid_jsonl(fleet_ext_path)
        fleet_seeds = [int(ep["seed"]) for ep in fleet_eps]
        if fleet_seeds != FLEET7_SEEDS:
            raise ValueError(f"expected fleet seeds {FLEET7_SEEDS}, got {fleet_seeds}")
        for ep in fleet_eps:
            if ep.get("agent") != CARBON_OC_AGENT or ep.get("tier") != "hard":
                raise ValueError(f"unexpected fleet ext record seed={ep.get('seed')}")
    elif comm_ext_seeds != OBSERVED_EXT8_SEEDS:
        raise FileNotFoundError(f"missing fleet extension episodes file: {fleet_ext_path}")
    fleet_by_seed = {int(ep["seed"]): ep for ep in fleet_eps}

    dedup_ext8_by_seed: dict[int, dict[str, Any]] = dict(fleet_by_seed)
    for seed, ep in comm_ext_by_seed.items():
        dedup_ext8_by_seed[seed] = ep
    if sorted(dedup_ext8_by_seed) != OBSERVED_EXT8_SEEDS:
        raise ValueError(f"deduplicated ext8 seeds {sorted(dedup_ext8_by_seed)} != {OBSERVED_EXT8_SEEDS}")
    if dedup_ext8_by_seed[34] is not comm_ext_by_seed[34]:
        raise ValueError("G1 precedence violated on overlapping seed 34")
    if int(dedup_ext8_by_seed[34]["final_day"]) != 5 or abs(float(dedup_ext8_by_seed[34]["score"]) - 0.79) > 1e-9:
        raise ValueError("seed 34 in deduplicated ext8 does not match committed G1 episode (day=5, score=0.79)")

    if fleet_by_seed:
        if int(fleet_by_seed[34]["final_day"]) != 8 or abs(float(fleet_by_seed[34]["score"]) - 0.82) > 1e-9:
            raise ValueError("fleet seed 34 does not match expected replication episode (day=8, score=0.82)")
        for seed in sorted((set(comm_ext_by_seed) & set(fleet_by_seed)) - {34}):
            ce = comm_ext_by_seed[seed]
            fe = fleet_by_seed[seed]
            if (
                abs(float(ce["score"]) - float(fe["score"])) > 1e-9
                or ce.get("accused") != fe.get("accused")
                or bool(ce.get("correct", False)) != bool(fe.get("correct", False))
                or int(ce["final_day"]) != int(fe["final_day"])
                or len(ce.get("steps") or []) != len(fe.get("steps") or [])
            ):
                raise ValueError(f"PR {HASH}3 committed ext seed {seed} diverges from fleet replication episode")

    g2_raw_maps: dict[str, tuple[str, str, str, dict[int, dict[str, Any]]]] = {}
    for g2_id, g2_dir, g2_agent, g2_label in OPTIONAL_G2_SPECS:
        g2_path = comm_v14 / g2_dir / "hard" / "episodes.jsonl"
        if g2_path.is_file():
            g2_by_seed = _load_seed_map(g2_path, g2_agent, "hard", expected_seeds=None)
            if not g2_by_seed:
                raise ValueError(f"empty G2 episodes file: {g2_path}")
            g2_raw_maps[g2_id] = (g2_dir, g2_agent, g2_label, g2_by_seed)

    uncached_eps: list[dict[str, Any]] = []
    seen_ckeys: set[tuple[Any, ...]] = set()
    all_candidate_maps = [
        oc_hard_by_seed,
        ip_hard_by_seed,
        fl_hard_by_seed,
        solver_hard_by_seed,
        heur_hard_by_seed,
        dedup_ext8_by_seed,
        oc_med_by_seed,
        ip_med_by_seed,
        solver_med_by_seed,
    ]
    if 34 in fleet_by_seed:
        all_candidate_maps.append({34: fleet_by_seed[34]})
    for _g2_dir, _g2_agent, _g2_label, g2_map in g2_raw_maps.values():
        all_candidate_maps.append(g2_map)

    for mp in all_candidate_maps:
        for ep in mp.values():
            ck = _ep_cache_key(ep, "v1.4")
            if ck not in _EP_OBS_CACHE and ck not in seen_ckeys:
                seen_ckeys.add(ck)
                uncached_eps.append(ep)

    if len(uncached_eps) >= 16 and can_fork:
        _FORK_WORK_EPS = uncached_eps
        try:
            with get_context("fork").Pool(n_workers) as pool:
                for idx_out, obs_out in pool.map(_fork_obs_worker, range(len(uncached_eps)), chunksize=6):
                    _EP_OBS_CACHE[_ep_cache_key(uncached_eps[idx_out], "v1.4")] = obs_out
        except OSError:
            pass
        finally:
            _FORK_WORK_EPS = []

    with rules.tiers_version("v1.4"):
        obs_oc_hard = {s: _episode_observables(oc_hard_by_seed[s]) for s in PRIMARY_SEEDS}
        obs_ip_hard = {s: _episode_observables(ip_hard_by_seed[s]) for s in PRIMARY_SEEDS}
        obs_fl_hard = {s: _episode_observables(fl_hard_by_seed[s]) for s in PRIMARY_SEEDS}
        obs_sol_hard = {s: _episode_observables(solver_hard_by_seed[s]) for s in ALL_60_SEEDS}
        obs_heur_hard = {s: _episode_observables(heur_hard_by_seed[s]) for s in ALL_60_SEEDS}
        obs_ext8_hard = {s: _episode_observables(dedup_ext8_by_seed[s]) for s in OBSERVED_EXT8_SEEDS}
        obs_fleet34 = _episode_observables(fleet_by_seed[34]) if 34 in fleet_by_seed else None

        obs_oc_med = {s: _episode_observables(oc_med_by_seed[s]) for s in PRIMARY_SEEDS}
        obs_ip_med = {s: _episode_observables(ip_med_by_seed[s]) for s in PRIMARY_SEEDS}
        obs_sol_med = {s: _episode_observables(solver_med_by_seed[s]) for s in PRIMARY_SEEDS}

        obs_g2_hard: dict[str, dict[int, dict[str, Any]]] = {}
        for g2_id, (_g2_dir, _g2_agent, _g2_label, g2_map) in g2_raw_maps.items():
            obs_g2_hard[g2_id] = {s: _episode_observables(ep) for s, ep in sorted(g2_map.items())}

    obs_pool38_hard: dict[int, dict[str, Any]] = dict(obs_oc_hard)
    obs_pool38_hard.update(obs_ext8_hard)

    core_labels = {
        "opencode_carbon": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
        "inproc_carbon": "in-process gemini-4-carbon (thought-signature replay)",
        "opencode_flash": "OpenCode + gemini-3.5-flash over MCP (lower tier)",
        "solver": "reference solver",
        "heuristic": "heuristic (bisection baseline)",
    }
    core_agents = {
        "opencode_carbon": CARBON_OC_AGENT,
        "inproc_carbon": CARBON_INPROC_AGENT,
        "opencode_flash": FLASH_OC_AGENT,
        "solver": SOLVER_AGENT,
        "heuristic": HEURISTIC_AGENT,
    }
    core_obs_0to29: dict[str, dict[int, dict[str, Any]]] = {
        "opencode_carbon": obs_oc_hard,
        "inproc_carbon": obs_ip_hard,
        "opencode_flash": obs_fl_hard,
        "solver": obs_sol_hard,
        "heuristic": obs_heur_hard,
    }

    cohorts_0to29: dict[str, dict[str, Any]] = {}
    for cid in CORE_MATRIX_ORDER:
        cohorts_0to29[cid] = _summarize_paired_cohort(
            cohort_id=cid,
            label=core_labels[cid],
            agent=core_agents[cid],
            tier="hard",
            seeds=PRIMARY_SEEDS,
            obs_map=core_obs_0to29[cid],
            solver_obs_map=obs_sol_hard,
            is_solver=(cid == "solver"),
        )
    cohorts_0to29["heuristic_committed20"] = _summarize_paired_cohort(
        cohort_id="heuristic_committed20",
        label="heuristic (committed shard seeds 0-19)",
        agent=HEURISTIC_AGENT,
        tier="hard",
        seeds=HEURISTIC_COMMITTED_SEEDS,
        obs_map=obs_heur_hard,
        solver_obs_map=obs_sol_hard,
    )

    medium_cohorts_0to29 = {
        "opencode_carbon_medium": _summarize_paired_cohort(
            cohort_id="opencode_carbon_medium",
            label="OpenCode + gemini-4-carbon over MCP (medium)",
            agent=CARBON_OC_AGENT,
            tier="medium",
            seeds=PRIMARY_SEEDS,
            obs_map=obs_oc_med,
            solver_obs_map=obs_sol_med,
        ),
        "inproc_carbon_medium": _summarize_paired_cohort(
            cohort_id="inproc_carbon_medium",
            label="in-process gemini-4-carbon (medium)",
            agent=CARBON_INPROC_AGENT,
            tier="medium",
            seeds=PRIMARY_SEEDS,
            obs_map=obs_ip_med,
            solver_obs_map=obs_sol_med,
        ),
        "solver_medium": _summarize_paired_cohort(
            cohort_id="solver_medium",
            label="reference solver (medium)",
            agent=SOLVER_AGENT,
            tier="medium",
            seeds=PRIMARY_SEEDS,
            obs_map=obs_sol_med,
            solver_obs_map=obs_sol_med,
            is_solver=True,
        ),
    }

    matrix_0to29: dict[str, dict[str, dict[str, Any]]] = {}
    for id_a in CORE_MATRIX_ORDER:
        matrix_0to29[id_a] = {}
        for id_b in CORE_MATRIX_ORDER:
            matrix_0to29[id_a][id_b] = _head_to_head(
                pair_id=f"{id_a}_vs_{id_b}_0to29",
                id_a=id_a,
                label_a=core_labels[id_a],
                obs_a=core_obs_0to29[id_a],
                id_b=id_b,
                label_b=core_labels[id_b],
                obs_b=core_obs_0to29[id_b],
                seeds=PRIMARY_SEEDS,
            )

    pairwise_0to29_core = [
        matrix_0to29["opencode_carbon"]["solver"],
        matrix_0to29["inproc_carbon"]["solver"],
        matrix_0to29["opencode_flash"]["solver"],
        matrix_0to29["heuristic"]["solver"],
        matrix_0to29["opencode_carbon"]["inproc_carbon"],
        matrix_0to29["opencode_carbon"]["opencode_flash"],
        matrix_0to29["inproc_carbon"]["opencode_flash"],
        matrix_0to29["opencode_carbon"]["heuristic"],
        matrix_0to29["inproc_carbon"]["heuristic"],
        matrix_0to29["opencode_flash"]["heuristic"],
    ]

    oc_c = cohorts_0to29["opencode_carbon"]
    ip_c = cohorts_0to29["inproc_carbon"]
    fl_c = cohorts_0to29["opencode_flash"]
    harness_hard_h2h = matrix_0to29["opencode_carbon"]["inproc_carbon"]
    harness_med_h2h = _head_to_head(
        pair_id="opencode_carbon_vs_inproc_carbon_medium_0to29",
        id_a="opencode_carbon_medium",
        label_a=medium_cohorts_0to29["opencode_carbon_medium"]["label"],
        obs_a=obs_oc_med,
        id_b="inproc_carbon_medium",
        label_b=medium_cohorts_0to29["inproc_carbon_medium"]["label"],
        obs_b=obs_ip_med,
        seeds=PRIMARY_SEEDS,
    )
    tier_hard_h2h = matrix_0to29["opencode_carbon"]["opencode_flash"]

    both_right_seeds = [
        s for s in PRIMARY_SEEDS if obs_oc_hard[s]["correct"] and obs_ip_hard[s]["correct"]
    ]
    both_right_oc_mean = sum(obs_oc_hard[s]["raw_score"] for s in both_right_seeds) / len(both_right_seeds)
    both_right_ip_mean = sum(obs_ip_hard[s]["raw_score"] for s in both_right_seeds) / len(both_right_seeds)

    harness_gap = {
        "hard_0to29": {
            "head_to_head": harness_hard_h2h,
            "opencode_cohort": oc_c,
            "inproc_cohort": ip_c,
            "raw_diff": harness_hard_h2h["raw"]["diff"],
            "luck_adjusted_diff": harness_hard_h2h["luck_adjusted"]["diff"],
            "luck_windfall_delta": oc_c["luck_windfall_mean"] - ip_c["luck_windfall_mean"],
            "canary_delta": oc_c["canary_mean"] - ip_c["canary_mean"],
            "interview_delta": oc_c["interview_mean"] - ip_c["interview_mean"],
            "p_accused_delta": oc_c["p_accused_mean"] - ip_c["p_accused_mean"],
            "both_correct_n": len(both_right_seeds),
            "both_correct_opencode_raw_mean": both_right_oc_mean,
            "both_correct_inproc_raw_mean": both_right_ip_mean,
        },
        "medium_0to29": {
            "head_to_head": harness_med_h2h,
            "opencode_cohort": medium_cohorts_0to29["opencode_carbon_medium"],
            "inproc_cohort": medium_cohorts_0to29["inproc_carbon_medium"],
            "solver_cohort": medium_cohorts_0to29["solver_medium"],
        },
    }

    model_tier_gap = {
        "hard_0to29": {
            "head_to_head": tier_hard_h2h,
            "carbon_cohort": oc_c,
            "flash_cohort": fl_c,
            "raw_diff": tier_hard_h2h["raw"]["diff"],
            "luck_adjusted_diff": tier_hard_h2h["luck_adjusted"]["diff"],
            "solver_luck_adjusted_ratio_pp_gain": (
                oc_c["luck_adjusted_ratio"] - fl_c["luck_adjusted_ratio"]
            )
            * 100.0,
            "flash_luck_windfall_mean": fl_c["luck_windfall_mean"],
            "carbon_luck_windfall_mean": oc_c["luck_windfall_mean"],
            "flash_expected_vs_realized_wrong": {
                "expected": fl_c["expected_wrong_sum"],
                "realized": fl_c["wrong_count"],
            },
            "carbon_expected_vs_realized_wrong": {
                "expected": oc_c["expected_wrong_sum"],
                "realized": oc_c["wrong_count"],
            },
        }
    }

    ext_cohorts = {
        "carbon_g1_ext2": _summarize_paired_cohort(
            cohort_id="carbon_g1_ext2",
            label="OpenCode + gemini-4-carbon G1 pre-stop ([34, 37])",
            agent=CARBON_OC_AGENT,
            tier="hard",
            seeds=G1_SEEDS,
            obs_map=obs_ext8_hard,
            solver_obs_map=obs_sol_hard,
        ),
        "carbon_pooled32": _summarize_paired_cohort(
            cohort_id="carbon_pooled32",
            label="OpenCode + gemini-4-carbon pooled G1 (0-29 + [34, 37])",
            agent=CARBON_OC_AGENT,
            tier="hard",
            seeds=POOLED32_SEEDS,
            obs_map=obs_pool38_hard,
            solver_obs_map=obs_sol_hard,
        ),
        "carbon_ext8": _summarize_paired_cohort(
            cohort_id="carbon_ext8",
            label="OpenCode + gemini-4-carbon deduplicated ext8",
            agent=CARBON_OC_AGENT,
            tier="hard",
            seeds=OBSERVED_EXT8_SEEDS,
            obs_map=obs_ext8_hard,
            solver_obs_map=obs_sol_hard,
        ),
        "solver_ext8": _summarize_paired_cohort(
            cohort_id="solver_ext8",
            label="reference solver on ext8 seeds",
            agent=SOLVER_AGENT,
            tier="hard",
            seeds=OBSERVED_EXT8_SEEDS,
            obs_map=obs_sol_hard,
            solver_obs_map=obs_sol_hard,
            is_solver=True,
        ),
        "heuristic_ext8": _summarize_paired_cohort(
            cohort_id="heuristic_ext8",
            label="heuristic on ext8 seeds",
            agent=HEURISTIC_AGENT,
            tier="hard",
            seeds=OBSERVED_EXT8_SEEDS,
            obs_map=obs_heur_hard,
            solver_obs_map=obs_sol_hard,
        ),
        "carbon_pooled38": _summarize_paired_cohort(
            cohort_id="carbon_pooled38",
            label="OpenCode + gemini-4-carbon pooled38 (0-29 + ext8)",
            agent=CARBON_OC_AGENT,
            tier="hard",
            seeds=POOLED38_SEEDS,
            obs_map=obs_pool38_hard,
            solver_obs_map=obs_sol_hard,
        ),
        "solver_pooled38": _summarize_paired_cohort(
            cohort_id="solver_pooled38",
            label="reference solver on pooled38 seeds",
            agent=SOLVER_AGENT,
            tier="hard",
            seeds=POOLED38_SEEDS,
            obs_map=obs_sol_hard,
            solver_obs_map=obs_sol_hard,
            is_solver=True,
        ),
        "heuristic_pooled38": _summarize_paired_cohort(
            cohort_id="heuristic_pooled38",
            label="heuristic on pooled38 seeds",
            agent=HEURISTIC_AGENT,
            tier="hard",
            seeds=POOLED38_SEEDS,
            obs_map=obs_heur_hard,
            solver_obs_map=obs_sol_hard,
        ),
        "solver_ext30to59": _summarize_paired_cohort(
            cohort_id="solver_ext30to59",
            label="reference solver on all extension seeds (30-59)",
            agent=SOLVER_AGENT,
            tier="hard",
            seeds=EXT_ALL_SEEDS,
            obs_map=obs_sol_hard,
            solver_obs_map=obs_sol_hard,
            is_solver=True,
        ),
        "heuristic_ext30to59": _summarize_paired_cohort(
            cohort_id="heuristic_ext30to59",
            label="heuristic on all extension seeds (30-59)",
            agent=HEURISTIC_AGENT,
            tier="hard",
            seeds=EXT_ALL_SEEDS,
            obs_map=obs_heur_hard,
            solver_obs_map=obs_sol_hard,
        ),
    }

    ext_head_to_head = {
        "carbon_ext8_vs_solver": _head_to_head(
            pair_id="carbon_ext8_vs_solver",
            id_a="carbon_ext8",
            label_a="OpenCode + gemini-4-carbon (ext8)",
            obs_a=obs_ext8_hard,
            id_b="solver",
            label_b="reference solver (ext8)",
            obs_b=obs_sol_hard,
            seeds=OBSERVED_EXT8_SEEDS,
        ),
        "carbon_ext8_vs_heuristic": _head_to_head(
            pair_id="carbon_ext8_vs_heuristic",
            id_a="carbon_ext8",
            label_a="OpenCode + gemini-4-carbon (ext8)",
            obs_a=obs_ext8_hard,
            id_b="heuristic",
            label_b="heuristic (ext8)",
            obs_b=obs_heur_hard,
            seeds=OBSERVED_EXT8_SEEDS,
        ),
        "solver_ext8_vs_heuristic": _head_to_head(
            pair_id="solver_ext8_vs_heuristic",
            id_a="solver",
            label_a="reference solver (ext8)",
            obs_a=obs_sol_hard,
            id_b="heuristic",
            label_b="heuristic (ext8)",
            obs_b=obs_heur_hard,
            seeds=OBSERVED_EXT8_SEEDS,
        ),
        "carbon_pooled38_vs_solver": _head_to_head(
            pair_id="carbon_pooled38_vs_solver",
            id_a="carbon_pooled38",
            label_a="OpenCode + gemini-4-carbon (pooled38)",
            obs_a=obs_pool38_hard,
            id_b="solver",
            label_b="reference solver (pooled38)",
            obs_b=obs_sol_hard,
            seeds=POOLED38_SEEDS,
        ),
        "carbon_pooled38_vs_heuristic": _head_to_head(
            pair_id="carbon_pooled38_vs_heuristic",
            id_a="carbon_pooled38",
            label_a="OpenCode + gemini-4-carbon (pooled38)",
            obs_a=obs_pool38_hard,
            id_b="heuristic",
            label_b="heuristic (pooled38)",
            obs_b=obs_heur_hard,
            seeds=POOLED38_SEEDS,
        ),
        "solver_pooled38_vs_heuristic": _head_to_head(
            pair_id="solver_pooled38_vs_heuristic",
            id_a="solver",
            label_a="reference solver (pooled38)",
            obs_a=obs_sol_hard,
            id_b="heuristic",
            label_b="heuristic (pooled38)",
            obs_b=obs_heur_hard,
            seeds=POOLED38_SEEDS,
        ),
        "solver_30to59_vs_heuristic": _head_to_head(
            pair_id="solver_30to59_vs_heuristic",
            id_a="solver",
            label_a="reference solver (30-59)",
            obs_a=obs_sol_hard,
            id_b="heuristic",
            label_b="heuristic (30-59)",
            obs_b=obs_heur_hard,
            seeds=EXT_ALL_SEEDS,
        ),
        "carbon_0to19_vs_heuristic_committed20": _head_to_head(
            pair_id="carbon_0to19_vs_heuristic_committed20",
            id_a="opencode_carbon",
            label_a="OpenCode + gemini-4-carbon (0-19)",
            obs_a=obs_oc_hard,
            id_b="heuristic_committed20",
            label_b="heuristic committed shard (0-19)",
            obs_b=obs_heur_hard,
            seeds=HEURISTIC_COMMITTED_SEEDS,
        ),
    }

    ext8_per_seed: list[dict[str, Any]] = []
    for seed in OBSERVED_EXT8_SEEDS:
        cg = obs_ext8_hard[seed]
        cs = obs_sol_hard[seed]
        ch = obs_heur_hard[seed]
        ext8_per_seed.append({
            "seed": seed,
            "source": "committed_g1" if seed in G1_SEEDS else "fleet_replication",
            "carbon_raw": cg["raw_score"],
            "carbon_luck_adjusted": cg["luck_adjusted_score"],
            "carbon_day": cg["final_day"],
            "carbon_p_accused": cg["p_accused"],
            "carbon_canaries": cg["canary_count"],
            "solver_raw": cs["raw_score"],
            "solver_luck_adjusted": cs["luck_adjusted_score"],
            "solver_day": cs["final_day"],
            "solver_p_accused": cs["p_accused"],
            "heuristic_raw": ch["raw_score"],
            "heuristic_luck_adjusted": ch["luck_adjusted_score"],
            "heuristic_day": ch["final_day"],
            "heuristic_p_accused": ch["p_accused"],
            "heuristic_correct": ch["correct"],
        })

    g2_cohorts: dict[str, dict[str, Any]] = {}
    g2_head_to_head: list[dict[str, Any]] = []
    g2_detected_dirs: list[str] = []
    for g2_id, _g2_dir, _g2_agent, _g2_label in OPTIONAL_G2_SPECS:
        if g2_id not in g2_raw_maps:
            continue
        g2_dir, g2_agent, g2_label, _g2_map = g2_raw_maps[g2_id]
        g2_obs = obs_g2_hard[g2_id]
        g2_seeds = sorted(s for s in g2_obs if s in obs_sol_hard)
        g2_detected_dirs.append(g2_dir)
        g2_cohorts[g2_id] = _summarize_paired_cohort(
            cohort_id=g2_id,
            label=g2_label,
            agent=g2_agent,
            tier="hard",
            seeds=g2_seeds,
            obs_map=g2_obs,
            solver_obs_map=obs_sol_hard,
        )
        for target_id in CORE_MATRIX_ORDER:
            shared = [s for s in g2_seeds if s in core_obs_0to29[target_id]]
            if shared:
                g2_head_to_head.append(
                    _head_to_head(
                        pair_id=f"{g2_id}_vs_{target_id}",
                        id_a=g2_id,
                        label_a=g2_label,
                        obs_a=g2_obs,
                        id_b=target_id,
                        label_b=core_labels[target_id],
                        obs_b=core_obs_0to29[target_id],
                        seeds=shared,
                    )
                )

    detected_opt_ids = [gid for gid, _, _, _ in OPTIONAL_G2_SPECS if gid in obs_g2_hard]
    for idx_a, id_a in enumerate(detected_opt_ids):
        for id_b in detected_opt_ids[idx_a + 1 :]:
            shared_ab = sorted(set(obs_g2_hard[id_a]) & set(obs_g2_hard[id_b]))
            if shared_ab:
                g2_head_to_head.append(
                    _head_to_head(
                        pair_id=f"{id_a}_vs_{id_b}",
                        id_a=id_a,
                        label_a=g2_cohorts[id_a]["label"],
                        obs_a=obs_g2_hard[id_a],
                        id_b=id_b,
                        label_b=g2_cohorts[id_b]["label"],
                        obs_b=obs_g2_hard[id_b],
                        seeds=shared_ab,
                    )
                )

    cross_family_rows = [
        cohorts_0to29["opencode_carbon"],
        cohorts_0to29["inproc_carbon"],
    ]
    for g2_id, _, _, _ in OPTIONAL_G2_SPECS:
        if g2_id in g2_cohorts:
            cross_family_rows.append(g2_cohorts[g2_id])
    cross_family_rows.extend([
        cohorts_0to29["opencode_flash"],
        cohorts_0to29["solver"],
        cohorts_0to29["heuristic"],
    ])

    return {
        "schema_version": "v1.4-harness-family-ext-synthesis-1",
        "provenance": {
            "tiers_version": "v1.4",
            "primary_tier": "hard",
            "primary_seeds": PRIMARY_SEEDS,
            "primary_headline_rule": (
                "Seeds 0-29 (n=30, MCP tools only) remain the authoritative v1.4 hard Gemini-4-carbon headline "
                "(65% raw [24%, 98%], 72% luck-adjusted [52%, 91%]); 30-59 extension rows are exploratory."
            ),
            "committed_root": str(comm_root),
            "committed_ext_layout": "pr3_ext8" if comm_ext_seeds == OBSERVED_EXT8_SEEDS else "justSilas_g1_n2",
            "committed_ext_seeds_present": comm_ext_seeds,
            "fleet_ext_seeds_present": [int(ep["seed"]) for ep in fleet_eps],
            "dedup_ext8_seeds": OBSERVED_EXT8_SEEDS,
            "unobserved_ext22_seeds": UNOBSERVED_EXT22_SEEDS,
            "heuristic_committed_seeds": sorted(heur_committed_by_seed),
            "heuristic_deterministic_extension_verified": True,
            "g2_families_detected": g2_detected_dirs,
            "optional_families_detected": g2_detected_dirs,
            "seed34_g1_precedence": {
                "kept_source": "committed_g1",
                "g1_final_day": obs_ext8_hard[34]["final_day"],
                "g1_raw_score": obs_ext8_hard[34]["raw_score"],
                "g1_luck_adjusted_score": obs_ext8_hard[34]["luck_adjusted_score"],
                "g1_steps": obs_ext8_hard[34]["total_steps"],
                "fleet_final_day": obs_fleet34["final_day"] if obs_fleet34 else 8,
                "fleet_raw_score": obs_fleet34["raw_score"] if obs_fleet34 else 0.82,
                "fleet_luck_adjusted_score": obs_fleet34["luck_adjusted_score"] if obs_fleet34 else 0.183,
                "fleet_steps": obs_fleet34["total_steps"] if obs_fleet34 else 83,
            },
        },
        "cohorts_0to29": cohorts_0to29,
        "medium_cohorts_0to29": medium_cohorts_0to29,
        "cross_family_rows_0to29": cross_family_rows,
        "head_to_head_matrix_0to29": matrix_0to29,
        "head_to_head_0to29_core": pairwise_0to29_core,
        "harness_gap": harness_gap,
        "model_tier_gap": model_tier_gap,
        "extension_comparison": {
            "cohorts": ext_cohorts,
            "head_to_head": ext_head_to_head,
            "ext8_per_seed": ext8_per_seed,
        },
        "g2_families": {
            "detected": g2_detected_dirs,
            "cohorts": g2_cohorts,
            "head_to_head": g2_head_to_head,
        },
    }


def _validate_invariants(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    mat = data["head_to_head_matrix_0to29"]
    for id_a in CORE_MATRIX_ORDER:
        diag = mat[id_a][id_a]
        for side in ("raw", "luck_adjusted"):
            blk = diag[side]
            if blk["wins"] != 0 or blk["losses"] != 0 or blk["ties"] != 30:
                errs.append(f"diagonal {id_a}.{side} expected 0-30-0, got {blk['wtl']}")
        for id_b in CORE_MATRIX_ORDER:
            ab = mat[id_a][id_b]
            ba = mat[id_b][id_a]
            for side in ("raw", "luck_adjusted"):
                sa = ab[side]
                sb = ba[side]
                if sa["wins"] + sa["ties"] + sa["losses"] != sa["n"]:
                    errs.append(f"{id_a}_vs_{id_b}.{side}: W+T+L != n")
                if sa["wins"] != sb["losses"] or sa["losses"] != sb["wins"] or sa["ties"] != sb["ties"]:
                    errs.append(f"antisymmetry failed for {id_a} vs {id_b} ({side})")
                if abs(sa["diff"] + sb["diff"]) > 1e-12:
                    errs.append(f"diff antisymmetry failed for {id_a} vs {id_b} ({side})")
                if abs(sa["sign_flip_p_two_sided"] - sb["sign_flip_p_two_sided"]) > 1e-12:
                    errs.append(f"sign_flip_p symmetry failed for {id_a} vs {id_b} ({side})")

    oc = data["cohorts_0to29"]["opencode_carbon"]
    if abs(oc["raw_ratio"] - 0.6458210006684492) > 1e-6 and round(100.0 * oc["raw_ratio"]) != 65:
        errs.append(f"primary raw headline ratio rounded != 65%: {oc['raw_ratio']}")
    if round(100.0 * oc["luck_adjusted_ratio"]) != 72:
        errs.append(f"primary luck-adjusted headline ratio rounded != 72%: {oc['luck_adjusted_ratio']}")

    hg = data["harness_gap"]["hard_0to29"]
    if abs((hg["luck_adjusted_diff"] + hg["luck_windfall_delta"]) - hg["raw_diff"]) > 1e-12:
        errs.append("harness gap additive identity (luck_adjusted_diff + luck_windfall_delta == raw_diff) failed")

    mg = data["model_tier_gap"]["hard_0to29"]
    luck_delta_tier = mg["carbon_luck_windfall_mean"] - mg["flash_luck_windfall_mean"]
    if abs((mg["luck_adjusted_diff"] + luck_delta_tier) - mg["raw_diff"]) > 1e-12:
        errs.append("model-tier gap additive identity failed")

    ext_c = data["extension_comparison"]["cohorts"]
    c_prim = data["cohorts_0to29"]["opencode_carbon"]
    c_ext8 = ext_c["carbon_ext8"]
    c_pool38 = ext_c["carbon_pooled38"]
    for field in ("raw_mean", "luck_adjusted_mean"):
        weighted = (30.0 * c_prim[field] + 8.0 * c_ext8[field]) / 38.0
        if abs(weighted - c_pool38[field]) > 1e-12:
            errs.append(f"30+8=38 weighted identity failed for {field}: {weighted} vs {c_pool38[field]}")

    for h2h in data["extension_comparison"]["head_to_head"].values():
        for side in ("raw", "luck_adjusted"):
            blk = h2h[side]
            if blk["wins"] + blk["ties"] + blk["losses"] != blk["n"]:
                errs.append(f"{h2h['id']}.{side}: W+T+L != n")

    for g2_id, g2_coh in data["g2_families"]["cohorts"].items():
        if g2_coh["n"] <= 0:
            errs.append(f"G2 cohort {g2_id} has empty seed count")
        if g2_coh["n"] > 1 and math.isfinite(g2_coh["raw_ratio"]) and math.isfinite(g2_coh["raw_ratio_lo"]):
            if not (g2_coh["raw_ratio_lo"] - 1e-12 <= g2_coh["raw_ratio"] <= g2_coh["raw_ratio_hi"] + 1e-12):
                errs.append(f"G2 cohort {g2_id} raw_ratio outside bootstrap CI")
        if (
            g2_coh["n"] > 1
            and math.isfinite(g2_coh["luck_adjusted_ratio"])
            and math.isfinite(g2_coh["luck_adjusted_ratio_lo"])
        ):
            if not (
                g2_coh["luck_adjusted_ratio_lo"] - 1e-12
                <= g2_coh["luck_adjusted_ratio"]
                <= g2_coh["luck_adjusted_ratio_hi"] + 1e-12
            ):
                errs.append(f"G2 cohort {g2_id} luck_adjusted_ratio outside bootstrap CI")

    for h2h in data["g2_families"]["head_to_head"]:
        for side in ("raw", "luck_adjusted"):
            blk = h2h[side]
            if blk["wins"] + blk["ties"] + blk["losses"] != blk["n"]:
                errs.append(f"G2 {h2h['id']}.{side}: W+T+L != n")

    return errs


def _fsign(val: float, nd: int = 3) -> str:
    return f"{val:+.{nd}f}"


def _fnum(val: float, nd: int = 3) -> str:
    return f"{val:.{nd}f}"


def _fpct(val: float, nd: int = 1) -> str:
    return f"{100.0 * val:.{nd}f}%"


def _fci_pct(lo: float, hi: float) -> str:
    return f"[{100.0 * lo:.0f}%, {100.0 * hi:.0f}%]"


def render_markdown(data: dict[str, Any]) -> str:
    c0 = data["cohorts_0to29"]
    cm = data["medium_cohorts_0to29"]
    mat = data["head_to_head_matrix_0to29"]
    hg = data["harness_gap"]
    mg = data["model_tier_gap"]["hard_0to29"]
    ext_c = data["extension_comparison"]["cohorts"]
    ext_h = data["extension_comparison"]["head_to_head"]
    ext_rows = data["extension_comparison"]["ext8_per_seed"]
    s34 = data["provenance"]["seed34_g1_precedence"]

    oc = c0["opencode_carbon"]
    ip = c0["inproc_carbon"]
    fl = c0["opencode_flash"]
    sol = c0["solver"]
    heur = c0["heuristic"]
    heur20 = c0["heuristic_committed20"]

    oc_m = cm["opencode_carbon_medium"]
    ip_m = cm["inproc_carbon_medium"]
    sol_m = cm["solver_medium"]
    hm_h2h = hg["medium_0to29"]["head_to_head"]
    hh_h2h = hg["hard_0to29"]["head_to_head"]
    th_h2h = mg["head_to_head"]

    c_g1 = ext_c["carbon_g1_ext2"]
    c_p32 = ext_c["carbon_pooled32"]
    c_ext8 = ext_c["carbon_ext8"]
    s_ext8 = ext_c["solver_ext8"]
    h_ext8 = ext_c["heuristic_ext8"]
    c_p38 = ext_c["carbon_pooled38"]
    s_p38 = ext_c["solver_pooled38"]
    h_p38 = ext_c["heuristic_pooled38"]
    s_3059 = ext_c["solver_ext30to59"]
    h_3059 = ext_c["heuristic_ext30to59"]

    lines: list[str] = []
    add = lines.append

    add(H1 + "v1.4 Frontier Synthesis: Harness Gap, Model-Tier Gap, and 30-59 Extension Head-to-Head")
    add("")
    add(H2 + "1. Scope, Primary Headline Rule, and Provenance")
    add("")
    add(
        "This report synthesizes seed-paired head-to-head win/tie/loss (`W-T-L`) outcomes across rules `v1.4` along "
        "three axes: (1) the **harness gap** (`opencode:google/gemini-4-carbon` over MCP vs `inproc-gemini-4-carbon` "
        "full-history thought-signature replay on seeds `0-29`), (2) the **model-tier gap** "
        "(`opencode:google/gemini-4-carbon` vs `opencode:google/gemini-3.5-flash` on seeds `0-29`), and "
        "(3) **out-of-sample `30-59` extension comparisons** (`ext8` `[30, 34, 37, 42, 45, 48, 57, 58]` and `pooled38` "
        "against both `solver` and `heuristic`). Every number in this report is computed deterministically with `0` "
        "API calls by [`scripts/analyze_v14_harness_and_family_gap.py`](../../scripts/analyze_v14_harness_and_family_gap.py) "
        "and verified in [`tests/test_v14_harness_and_ext_synthesis.py`](../../tests/test_v14_harness_and_ext_synthesis.py)."
    )
    add("")
    add(H3 + "Primary `0-29` headline rule (unchanged)")
    add("")
    add(
        f"- **Authoritative `v1.4` `hard` headline (`n=30`, seeds `0-29`, MCP tools only):** OpenCode + `gemini-4-carbon` over MCP "
        f"scores `{_fsign(oc['raw_mean'])} +/- {_fnum(oc['raw_ci'])}` vs reference solver "
        f"`{_fsign(sol['raw_mean'])} +/- {_fnum(sol['raw_ci'])}` (paired diff `{_fsign(oc['raw_diff'])} +/- {_fnum(oc['raw_diff_ci'])}`), "
        f"giving **`{_fpct(oc['raw_ratio'], 0)} {_fci_pct(oc['raw_ratio_lo'], oc['raw_ratio_hi'])}`** raw "
        f"(`{_fpct(oc['raw_ratio'], 1)}`) and "
        f"**`{_fpct(oc['luck_adjusted_ratio'], 0)} {_fci_pct(oc['luck_adjusted_ratio_lo'], oc['luck_adjusted_ratio_hi'])}`** "
        f"luck-adjusted (`{_fpct(oc['luck_adjusted_ratio'], 1)}`, `{_fsign(oc['luck_adjusted_mean'])}` vs "
        f"`{_fsign(sol['luck_adjusted_mean'])}`) in "
        "[`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md), "
        "[`docs/reports/gap.md`](gap.md), and [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md) "
        "(see [`docs/reports/gap.md`](gap.md) for cross-family `opencode-gpt-5.5` and Harbor judge-path rehearsal comparisons)."
    )
    add(
        "- **Extension role (`30-59` exploratory only):** Per the pre-registered extension rule in "
        "[`docs/reports/gap.md`](gap.md), partial `30-59` OpenCode runs (`8/30` seeds completed before shared carbon "
        "quota cutoffs) are reported separately (`ext8`) and pooled (`pooled38`) for out-of-sample checks, and never "
        "replace the complete `n=30` (`0-29`) primary headline."
    )
    add("")
    add(H3 + "Input artifacts and forward-compatibility")
    add("")
    add(
        "- **Primary `0-29` cohorts (`hard`, `n=30` each):** "
        "[`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl), "
        "[`data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl), and "
        "[`data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl), "
        "plus `medium` harness cohorts audited via [`docs/reports/harness.md`](harness.md) and "
        "[`scripts/paired_gemini.py`](../../scripts/paired_gemini.py)."
    )
    add(
        "- **Reference `solver` (`n=60`, seeds `0-59`) and `heuristic` (`n=60`, seeds `0-59`):** solver shards "
        "[`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl) (`0-19`), "
        "[`data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl) (`20-29`), and "
        "[`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl) (`30-59`); "
        "committed heuristic shard [`data/runs/committed/v1.4/reference/heuristic-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/heuristic-hard-20261114-121126/episodes.jsonl) (`0-19`, verified `20/20` bit-exact against `Heuristic(seed=s)` in "
        "[`canary/baselines.py`](../../canary/baselines.py)) extended deterministically to `20-59` with `0` API calls. "
        "Luck-adjusted scores (`P*V - (1-P)` on accused episodes, `0.0` on abstentions) use "
        "[`canary/analysis/accuse.py`](../../canary/analysis/accuse.py)."
    )
    add(
        "- **Extension `ext8` (`[30, 34, 37, 42, 45, 48, 57, 58]`) and optional cross-family runs (`opencode-gpt-5.5`, `argon`, `hydrogen`):** "
        "combines [`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) "
        f"(`G1` `n=2` on `justSilas` or `n=8` on PR {HASH}3 `v14-runs`) with `results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl` "
        f"(`n=7` fleet shard-head episodes), enforcing `G1` precedence on overlapping seed `34` (`day {s34['g1_final_day']}`, "
        f"raw `{_fsign(s34['g1_raw_score'])}`, luck-adjusted `{_fsign(s34['g1_luck_adjusted_score'])}` over fleet "
        f"`day {s34['fleet_final_day']}`, raw `{_fsign(s34['fleet_raw_score'])}`, luck-adjusted `{_fsign(s34['fleet_luck_adjusted_score'])}`). "
        "When `opencode-gpt-5.5`, `opencode-gemini-4-argon`, or `opencode-gemini-4-hydrogen` exist under `--committed-root`, "
        "`--json` automatically includes their cross-family and head-to-head rows without altering this report's core tables."
    )
    add("")
    add(H2 + "2. Primary `0-29` Cohort Summary and Seed-Paired Head-to-Head Matrices (`v1.4` `hard`)")
    add("")
    add(H3 + "Table 2A: Primary `0-29` `hard` cohort scoreboard (paired with `solver` on identical seeds)")
    add("")
    add(
        "| Cohort (`v1.4` `hard`) | `n` | Raw +/- 95% CI | Raw / solver [95% CI] | Luck-adj. +/- 95% CI | Luck-adj. / solver [95% CI] | Acc. (`ok/w/ab`) | Mean `P(acc)` | Day (`acc`) | Canaries / Interviews |"
    )
    add("|---|---:|---|---|---|---|---|---:|---:|---|")
    for coh in (oc, ip, fl, sol, heur, heur20):
        is_sol = coh["agent"] == SOLVER_AGENT
        r_str = "-" if is_sol else f"`{_fpct(coh['raw_ratio'], 1)}` `{_fci_pct(coh['raw_ratio_lo'], coh['raw_ratio_hi'])}`"
        la_str = (
            "-"
            if is_sol
            else f"**`{_fpct(coh['luck_adjusted_ratio'], 1)}`** `{_fci_pct(coh['luck_adjusted_ratio_lo'], coh['luck_adjusted_ratio_hi'])}`"
        )
        add(
            f"| {coh['label']} | {coh['n']} | `{_fsign(coh['raw_mean'])} +/- {_fnum(coh['raw_ci'])}` | {r_str} | "
            f"`{_fsign(coh['luck_adjusted_mean'])} +/- {_fnum(coh['luck_adjusted_ci'])}` | {la_str} | "
            f"`{_fpct(coh['accuracy'], 1)}` (`{coh['correct_count']}/{coh['wrong_count']}/{coh['abstention_count']}`) | "
            f"`{_fnum(coh['p_accused_mean'], 3)}` | `{_fnum(coh['accuse_day_mean'], 1)}` | "
            f"`{_fnum(coh['canary_mean'], 1)}` / `{_fnum(coh['interview_mean'], 1)}` |"
        )
    add("")
    add(H3 + "Table 2B: Seed-paired `5x5` win-tie-loss matrix on `v1.4` `hard` seeds `0-29` (`row` vs `column`, `n=30`)")
    add("")
    short_names = {
        "opencode_carbon": "OC carbon",
        "inproc_carbon": "In-proc carbon",
        "opencode_flash": "OC 3.5-flash",
        "solver": "Solver",
        "heuristic": "Heuristic",
    }
    add(
        "| Row vs Col (`raw W-T-L` / `luck-adj. W-T-L`) | OC carbon | In-proc carbon | OC 3.5-flash | Solver | Heuristic |"
    )
    add("|---|---|---|---|---|---|")
    for id_a in CORE_MATRIX_ORDER:
        cells = []
        for id_b in CORE_MATRIX_ORDER:
            if id_a == id_b:
                cells.append("`0-30-0`")
            else:
                cell_h = mat[id_a][id_b]
                cells.append(f"`{cell_h['raw']['wtl']}` / **`{cell_h['luck_adjusted']['wtl']}`**")
        add(f"| **{short_names[id_a]}** | " + " | ".join(cells) + " |")
    add("")
    add(H3 + "Table 2C: Pairwise head-to-head differences and sign-flip `p`-values on `v1.4` `hard` (`0-29`, `n=30`)")
    add("")
    add(
        "| Matchup (`A` minus `B`, `n=30`) | Raw `W-T-L` (`win%`) | Raw diff +/- 95% CI | Raw sign-flip `p` | Luck-adj. `W-T-L` (`win%`) | Luck-adj. diff +/- 95% CI | Luck-adj. sign-flip `p` |"
    )
    add("|---|---|---|---:|---|---|---:|")
    for h2h in data["head_to_head_0to29_core"]:
        rw = h2h["raw"]
        lw = h2h["luck_adjusted"]
        title = f"{short_names[h2h['agent_a']]} vs {short_names[h2h['agent_b']]}"
        add(
            f"| {title} | `{rw['wtl']}` (`{_fpct(rw['win_rate'], 1)}`) | "
            f"`{_fsign(rw['diff'])} +/- {_fnum(rw['diff_ci'])}` | `{_fnum(rw['sign_flip_p_two_sided'], 4)}` | "
            f"**`{lw['wtl']}`** (`{_fpct(lw['win_rate'], 1)}`) | "
            f"**`{_fsign(lw['diff'])} +/- {_fnum(lw['diff_ci'])}`** | `{_fnum(lw['sign_flip_p_two_sided'], 4)}` |"
        )
    add("")
    add(H2 + "3. Harness Gap Analysis: OpenCode over MCP vs In-Process Thought-Signature Replay (`0-29`)")
    add("")
    add(H3 + "Table 3A: Cross-tier harness comparison (`gemini-4-carbon`, seeds `0-29`, `n=30` per tier)")
    add("")
    add(
        "| Tier | OpenCode raw / luck-adj. | In-proc raw / luck-adj. | Raw `W-T-L` (`OC - IP`) | Raw diff +/- 95% CI | Luck-adj. `W-T-L` (`OC - IP`) | Luck-adj. diff +/- 95% CI | OC vs IP canaries |"
    )
    add("|---|---|---|---|---|---|---|---:|")
    add(
        f"| `hard` | `{_fsign(oc['raw_mean'])}` / `{_fsign(oc['luck_adjusted_mean'])}` | "
        f"`{_fsign(ip['raw_mean'])}` / `{_fsign(ip['luck_adjusted_mean'])}` | "
        f"`{hh_h2h['raw']['wtl']}` | `{_fsign(hh_h2h['raw']['diff'])} +/- {_fnum(hh_h2h['raw']['diff_ci'])}` | "
        f"**`{hh_h2h['luck_adjusted']['wtl']}`** | **`{_fsign(hh_h2h['luck_adjusted']['diff'])} +/- {_fnum(hh_h2h['luck_adjusted']['diff_ci'])}`** | "
        f"`{_fnum(oc['canary_mean'], 1)}` vs `{_fnum(ip['canary_mean'], 1)}` |"
    )
    add(
        f"| `medium` | `{_fsign(oc_m['raw_mean'])}` / `{_fsign(oc_m['luck_adjusted_mean'])}` | "
        f"`{_fsign(ip_m['raw_mean'])}` / `{_fsign(ip_m['luck_adjusted_mean'])}` | "
        f"`{hm_h2h['raw']['wtl']}` | `{_fsign(hm_h2h['raw']['diff'])} +/- {_fnum(hm_m_ci := hm_h2h['raw']['diff_ci'])}` | "
        f"**`{hm_h2h['luck_adjusted']['wtl']}`** | **`{_fsign(hm_h2h['luck_adjusted']['diff'])} +/- {_fnum(hm_h2h['luck_adjusted']['diff_ci'])}`** | "
        f"`{_fnum(oc_m['canary_mean'], 1)}` vs `{_fnum(ip_m['canary_mean'], 1)}` |"
    )
    _ = hm_m_ci
    add("")
    hg_hard = hg["hard_0to29"]
    add(
        f"1. **Why OpenCode leads `16-0-14` in raw per-seed wins on `hard` yet trails by `{_fsign(hg_hard['raw_diff'])}` in mean score:** "
        f"On the `{hg_hard['both_correct_n']}` `hard` seeds where both harnesses accused the true mole, OpenCode averages "
        f"`{_fsign(hg_hard['both_correct_opencode_raw_mean'])}` vs in-process `{_fsign(hg_hard['both_correct_inproc_raw_mean'])}`. "
        f"The entire `{_fsign(hg_hard['raw_diff'])}` raw gap comes from tail losses (`{oc['wrong_count']}` wrong `-1.0` accusations on "
        f"OpenCode vs `{ip['wrong_count']}` on in-process). Decomposing `raw_diff = luck_adjusted_diff + luck_windfall_delta` "
        f"gives `{_fsign(hg_hard['raw_diff'])} = {_fsign(hg_hard['luck_adjusted_diff'])} + ({_fsign(hg_hard['luck_windfall_delta'])})`: "
        f"`{_fpct(abs(hg_hard['luck_windfall_delta']) / abs(hg_hard['raw_diff']), 1)}` of the raw harness gap is realized luck "
        f"(OpenCode `{_fsign(oc['luck_windfall_mean'])}`/seed vs in-process `{_fsign(ip['luck_windfall_mean'])}`/seed), leaving a "
        f"non-significant `{_fsign(hg_hard['luck_adjusted_diff'])} +/- {_fnum(hh_h2h['luck_adjusted']['diff_ci'])}` luck-adjusted difference "
        f"(`p = {_fnum(hh_h2h['luck_adjusted']['sign_flip_p_two_sided'], 4)}`)."
    )
    add(
        f"2. **Identical exploration profile, reversals across tiers (`medium` `+0.183` raw / `+0.173` luck-adjusted for OpenCode):** "
        f"On `hard`, both harnesses plant almost identical canary counts (`{_fnum(oc['canary_mean'], 1)}` vs `{_fnum(ip['canary_mean'], 1)}` "
        f"against solver `{_fnum(sol['canary_mean'], 1)}`) and over-invest in interviews (`{_fnum(oc['interview_mean'], 1)}` vs "
        f"`{_fnum(ip['interview_mean'], 1)}`), while OpenCode commits slightly earlier in posterior (`mean P(accused) = {_fnum(oc['p_accused_mean'], 3)}` "
        f"vs `{_fnum(ip['p_accused_mean'], 3)}`, `{oc['sub_085_count']}` vs `{ip['sub_085_count']}` sub-`0.85` accusations). "
        f"On `medium` (`solver = {_fsign(sol_m['raw_mean'])}`), the sign flips decisively in OpenCode's favor "
        f"(`{hm_h2h['raw']['wtl']}` raw, `{hm_h2h['luck_adjusted']['wtl']}` luck-adjusted, `p = {_fnum(hm_h2h['luck_adjusted']['sign_flip_p_two_sided'], 4)}`), "
        "confirming that the OpenCode MCP interface itself imposes no structural ceiling (consistent with cross-family and Harbor container comparisons in [`docs/reports/gap.md`](gap.md))."
    )
    add("")
    add(H2 + "4. Model-Tier Gap Analysis: `gemini-4-carbon` vs `gemini-3.5-flash` (`0-29` `hard`)")
    add("")
    add(
        f"- **Why raw scores invert while luck-adjusted scores separate by `{_fsign(mg['luck_adjusted_diff'])} +/- {_fnum(th_h2h['luck_adjusted']['diff_ci'])}` V/seed "
        f"(`+{_fnum(mg['solver_luck_adjusted_ratio_pp_gain'], 1)}` pp of solver):** On `0-29` `hard`, `gemini-3.5-flash` posts "
        f"`{_fsign(fl['raw_mean'])}` raw vs `gemini-4-carbon` `{_fsign(oc['raw_mean'])}` (`{th_h2h['raw']['wtl']}`, "
        f"diff `{_fsign(mg['raw_diff'])} +/- {_fnum(th_h2h['raw']['diff_ci'])}`) only because `3.5-flash` gambled at "
        f"`mean P(accused) = {_fnum(fl['p_accused_mean'], 3)}` (`{fl['sub_085_count']}/30` accusations below `P = 0.85`, "
        f"`{fl['negative_ev_count']}/30` negative-EV gambles). Its posteriors priced `{_fnum(fl['expected_wrong_sum'], 2)}` expected wrong "
        f"accusations, yet only `{fl['wrong_count']}` realized wrong (`{_fsign(fl['luck_windfall_mean'])}` V/seed luck windfall)."
    )
    add(
        f"- **True decision-quality gap (`{_fpct(oc['luck_adjusted_ratio'], 1)}` vs `{_fpct(fl['luck_adjusted_ratio'], 1)}` of solver):** Removing realization luck (`P*V - (1-P)`), "
        f"`gemini-4-carbon` (`{_fsign(oc['luck_adjusted_mean'])}`, **`{_fpct(oc['luck_adjusted_ratio'], 1)}`** of solver) "
        f"outperforms `gemini-3.5-flash` (`{_fsign(fl['luck_adjusted_mean'])}`, **`{_fpct(fl['luck_adjusted_ratio'], 1)}`** of solver) "
        f"by **`{_fsign(mg['luck_adjusted_diff'])} +/- {_fnum(th_h2h['luck_adjusted']['diff_ci'])}`** (`{th_h2h['luck_adjusted']['wtl']}` W-T-L, "
        f"two-sided sign-flip `p = {_fnum(th_h2h['luck_adjusted']['sign_flip_p_two_sided'], 4)}`), directly validating why Canary "
        "pairs raw scores with solver-posterior luck-adjusted EV."
    )
    add("")
    add(H2 + "5. Out-of-Sample `30-59` Extension Comparison (`ext8` and `pooled38` vs `solver` and `heuristic`)")
    add("")
    add(H3 + "Table 5A: Extension and pooled cohort metrics (`v1.4` `hard`, exploratory non-primary)")
    add("")
    add(
        "| Cohort | Seeds (`n`) | Raw +/- 95% CI | Raw / solver [95% CI] | Luck-adj. +/- 95% CI | Luck-adj. / solver [95% CI] | Acc. (`ok/n`) | Mean `P(acc)` | Day (`acc`) |"
    )
    add("|---|---|---|---:|---|---:|---|---:|---:|")
    ext_table_rows = [
        (c_g1, "`[34, 37]` (`2`)"),
        (c_p32, "`0-29 + [34, 37]` (`32`)"),
        (c_ext8, "`ext8` (`8`)"),
        (s_ext8, "`ext8` (`8`)"),
        (h_ext8, "`ext8` (`8`)"),
        (c_p38, "`0-29 + ext8` (`38`)"),
        (s_p38, "`0-29 + ext8` (`38`)"),
        (h_p38, "`0-29 + ext8` (`38`)"),
        (s_3059, "`30-59` (`30`)"),
        (h_3059, "`30-59` (`30`)"),
    ]
    for coh, seed_desc in ext_table_rows:
        is_sol = coh["agent"] == SOLVER_AGENT
        r_str = "-" if is_sol else f"`{_fpct(coh['raw_ratio'], 1)}` `{_fci_pct(coh['raw_ratio_lo'], coh['raw_ratio_hi'])}`"
        la_str = (
            "-"
            if is_sol
            else f"**`{_fpct(coh['luck_adjusted_ratio'], 1)}`** `{_fci_pct(coh['luck_adjusted_ratio_lo'], coh['luck_adjusted_ratio_hi'])}`"
        )
        add(
            f"| {coh['label']} | {seed_desc} | `{_fsign(coh['raw_mean'])} +/- {_fnum(coh['raw_ci'])}` | {r_str} | "
            f"`{_fsign(coh['luck_adjusted_mean'])} +/- {_fnum(coh['luck_adjusted_ci'])}` | {la_str} | "
            f"`{_fpct(coh['accuracy'], 1)}` (`{coh['correct_count']}/{coh['n']}`) | `{_fnum(coh['p_accused_mean'], 3)}` | "
            f"`{_fnum(coh['accuse_day_mean'], 1)}` |"
        )
    add("")
    add(H3 + "Table 5B: Extension and pooled head-to-head win-tie-loss summary")
    add("")
    add(
        "| Matchup (`A` minus `B`) | `n` | Raw `W-T-L` (`win%`) | Raw diff +/- 95% CI | Luck-adj. `W-T-L` (`win%`) | Luck-adj. diff +/- 95% CI | Luck-adj. sign-flip `p` |"
    )
    add("|---|---:|---|---|---|---|---:|")
    ext_h2h_order = [
        ("OC carbon (`ext8`) vs Solver (`ext8`)", ext_h["carbon_ext8_vs_solver"]),
        ("OC carbon (`ext8`) vs Heuristic (`ext8`)", ext_h["carbon_ext8_vs_heuristic"]),
        ("Solver (`ext8`) vs Heuristic (`ext8`)", ext_h["solver_ext8_vs_heuristic"]),
        ("OC carbon (`pooled38`) vs Solver (`pooled38`)", ext_h["carbon_pooled38_vs_solver"]),
        ("OC carbon (`pooled38`) vs Heuristic (`pooled38`)", ext_h["carbon_pooled38_vs_heuristic"]),
        ("Solver (`pooled38`) vs Heuristic (`pooled38`)", ext_h["solver_pooled38_vs_heuristic"]),
        ("Solver (`30-59`) vs Heuristic (`30-59`)", ext_h["solver_30to59_vs_heuristic"]),
        ("OC carbon (`0-19`) vs Heuristic committed (`0-19`)", ext_h["carbon_0to19_vs_heuristic_committed20"]),
    ]
    for title, h2h in ext_h2h_order:
        rw = h2h["raw"]
        lw = h2h["luck_adjusted"]
        add(
            f"| {title} | {h2h['n']} | `{rw['wtl']}` (`{_fpct(rw['win_rate'], 1)}`) | "
            f"`{_fsign(rw['diff'])} +/- {_fnum(rw['diff_ci'])}` | "
            f"**`{lw['wtl']}`** (`{_fpct(lw['win_rate'], 1)}`) | "
            f"**`{_fsign(lw['diff'])} +/- {_fnum(lw['diff_ci'])}`** | `{_fnum(lw['sign_flip_p_two_sided'], 4)}` |"
        )
    add("")
    add(H3 + "Table 5C: Per-seed out-of-sample comparison on deduplicated `ext8` (`[30, 34, 37, 42, 45, 48, 57, 58]`)")
    add("")
    add(
        "| Seed | Source | OC carbon raw / luck-adj. (`day`, `P`) | Solver raw / luck-adj. (`day`, `P`) | Heuristic raw / luck-adj. (`day`, `P`) |"
    )
    add("|---:|---|---|---|---|")
    for row in ext_rows:
        add(
            f"| {row['seed']} | `{row['source']}` | "
            f"`{_fsign(row['carbon_raw'])}` / `{_fsign(row['carbon_luck_adjusted'])}` (`d{row['carbon_day']}`, `{_fnum(row['carbon_p_accused'], 3)}`) | "
            f"`{_fsign(row['solver_raw'])}` / `{_fsign(row['solver_luck_adjusted'])}` (`d{row['solver_day']}`, `{_fnum(row['solver_p_accused'], 3)}`) | "
            f"`{_fsign(row['heuristic_raw'])}` / `{_fsign(row['heuristic_luck_adjusted'])}` (`d{row['heuristic_day']}`, `{_fnum(row['heuristic_p_accused'], 3)}`) |"
        )
    add("")
    add(
        f"On all `8` completed out-of-sample extension seeds (`ext8`), `opencode:google/gemini-4-carbon` sweeps `heuristic` "
        f"**`{ext_h['carbon_ext8_vs_heuristic']['raw']['wtl']}`** both raw (`{_fsign(ext_h['carbon_ext8_vs_heuristic']['raw']['diff'])}` V/seed) "
        f"and luck-adjusted (`{_fsign(ext_h['carbon_ext8_vs_heuristic']['luck_adjusted']['diff'])}` V/seed, "
        f"`p = {_fnum(ext_h['carbon_ext8_vs_heuristic']['luck_adjusted']['sign_flip_p_two_sided'], 4)}`), and leads `solver` `{ext_h['carbon_ext8_vs_solver']['luck_adjusted']['wtl']}` "
        f"on those `8` seeds (`{_fsign(ext_h['carbon_ext8_vs_solver']['luck_adjusted']['diff'])}` luck-adjusted). Pooled across all `38` "
        f"observed seeds (`pooled38`), `gemini-4-carbon` beats `heuristic` **`{ext_h['carbon_pooled38_vs_heuristic']['luck_adjusted']['wtl']}`** "
        f"luck-adjusted (`{_fsign(ext_h['carbon_pooled38_vs_heuristic']['luck_adjusted']['diff'])} +/- {_fnum(ext_h['carbon_pooled38_vs_heuristic']['luck_adjusted']['diff_ci'])}`) "
        f"while remaining below the reference `solver` at **`{_fpct(c_p38['luck_adjusted_ratio'], 1)}` `{_fci_pct(c_p38['luck_adjusted_ratio_lo'], c_p38['luck_adjusted_ratio_hi'])}`** "
        f"luck-adjusted (`{ext_h['carbon_pooled38_vs_solver']['luck_adjusted']['wtl']}` W-T-L); the primary `0-29` headline remains "
        f"**`{_fpct(oc['raw_ratio'], 0)}`** raw / **`{_fpct(oc['luck_adjusted_ratio'], 0)}`** luck-adjusted."
    )
    add("")
    add(H2 + "6. Keyless Reproduction Commands")
    add("")
    add("```bash")
    add("CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_v14_harness_and_family_gap.py --check")
    add("CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_v14_harness_and_family_gap.py --json")
    add("CANARY_ALLOW_DEV=1 PYTHONPATH=. pytest -q tests/test_v14_harness_and_ext_synthesis.py")
    add("```")
    add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Deterministic keyless synthesis of v1.4 harness gap, model-tier gap, and 30-59 extension head-to-head."
    )
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--committed-root", default=None)
    ap.add_argument("--committed-ext-jsonl", default=None)
    ap.add_argument("--fleet-ext-jsonl", default=None)
    ap.add_argument("--report-md", default=None)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-md", action="store_true")
    args = ap.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    report_path = Path(args.report_md).resolve() if args.report_md else (repo_path / DEFAULT_REPORT_REL)

    data = analyze_harness_and_family_gap(
        repo=repo_path,
        committed_root=args.committed_root,
        committed_ext_jsonl=args.committed_ext_jsonl,
        fleet_ext_jsonl=args.fleet_ext_jsonl,
    )
    inv_errs = _validate_invariants(data)
    rendered_md = render_markdown(data)

    if EM_DASH in rendered_md or EN_DASH in rendered_md or MINUS_SIGN in rendered_md:
        inv_errs.append("rendered markdown contains forbidden unicode dash or minus sign")

    if args.write_md:
        if inv_errs:
            for err in inv_errs:
                print(f"ERROR: {err}", file=sys.stderr)
            return 1
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered_md, encoding="utf-8")

    if args.check:
        check_errs = list(inv_errs)
        if not report_path.is_file():
            check_errs.append(f"missing markdown report: {report_path}")
        else:
            actual_md = report_path.read_text(encoding="utf-8")
            if EM_DASH in actual_md or EN_DASH in actual_md or MINUS_SIGN in actual_md:
                check_errs.append(f"unicode dash or minus sign present in {report_path}")
            if actual_md != rendered_md:
                check_errs.append(f"{report_path} does not match deterministic render_markdown(data)")
        if args.as_json:
            print(json.dumps({"ok": not check_errs, "errors": check_errs, "data": data}, indent=2))
        elif check_errs:
            for err in check_errs:
                print(f"[FAIL] {err}")
        else:
            print(
                "PASS: v1.4 harness, model-tier & ext30-59 synthesis verified "
                f"(layout={data['provenance']['committed_ext_layout']}, "
                f"g2_detected={data['provenance']['g2_families_detected']})"
            )
        return 0 if not check_errs else 1

    if inv_errs:
        for err in inv_errs:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(data, indent=2))
    elif not args.write_md:
        print(rendered_md, end="")
    else:
        print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
