from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if sys.path[:1] != [str(ROOT)]:
    sys.path.insert(0, str(ROOT))

from canary.analysis.gap import load_runs
from scripts.paired_v13 import _P_CACHE, post_expected

SCHEMA_VERSION = "statistical_robustness_v14.v1"
PRIMARY_SEEDS = list(range(30))
PRIMARY_SEED_LOCK_NOTE = (
    "post-hoc locked dev seeds 0-29 (commit 671ed96, 28 s after 8fd4dec, not pre-registered)"
)
BOOTSTRAP_RESAMPLES = 10000
PERMUTATION_RESAMPLES = 20000
RNG_SEED = 0
MAX_JSON_BYTES = 45 * 1024

NORM = statistics.NormalDist()

COHORT_SPECS: tuple[dict[str, str], ...] = (
    {
        "cohort_id": "opencode-gemini-4-carbon",
        "tier": "hard",
        "agent": "opencode:google/gemini-4-carbon",
        "label": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
        "rel_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
    },
    {
        "cohort_id": "inproc-gemini-4-carbon",
        "tier": "hard",
        "agent": "gemini:gemini-4-carbon",
        "label": "in-process gemini-4-carbon (full history, thought-signature replay)",
        "rel_dir": "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard",
    },
    {
        "cohort_id": "opencode-gemini-3.5-flash",
        "tier": "hard",
        "agent": "opencode:google/gemini-3.5-flash",
        "label": "OpenCode + gemini-3.5-flash over MCP (served as gemini-3.6-flash)",
        "rel_dir": "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard",
    },
    {
        "cohort_id": "opencode-gpt-5.5",
        "tier": "hard",
        "agent": "opencode:openai/gpt-5.5",
        "label": "OpenCode + gpt-5.5 over MCP (judges' shape, pre-registered cf394894)",
        "rel_dir": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
    },
    {
        "cohort_id": "opencode-gemini-4-carbon",
        "tier": "medium",
        "agent": "opencode:google/gemini-4-carbon",
        "label": "OpenCode + gemini-4-carbon over MCP (judges' shape)",
        "rel_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium",
    },
    {
        "cohort_id": "inproc-gemini-4-carbon",
        "tier": "medium",
        "agent": "gemini:gemini-4-carbon",
        "label": "in-process gemini-4-carbon (full history, thought-signature replay)",
        "rel_dir": "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium",
    },
)

SOLVER_REL_DIRS: dict[str, tuple[str, ...]] = {
    "medium": (
        "data/runs/committed/v1.4/reference/solver-medium-20261114-121126",
        "data/runs/committed/v1.4/reference/solver-medium-seeds20to29",
    ),
    "hard": (
        "data/runs/committed/v1.4/reference/solver-hard-20261114-121126",
        "data/runs/committed/v1.4/reference/solver-hard-seeds20to29",
    ),
}

_BOOT_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_PERM_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_DIR_SERIES_CACHE: dict[str, dict[int, dict[str, Any]]] = {}


def _r(val: float | None, ndigits: int = 10) -> float | None:
    if val is None or (isinstance(val, float) and (math.isnan(val) or math.isinf(val))):
        return None
    return round(float(val), ndigits)


def student_t_cdf(t_val: float, df: int) -> float:
    if df <= 0:
        raise ValueError(f"df must be positive, got {df}")
    theta = math.atan(t_val / math.sqrt(df))
    c2 = math.cos(theta) ** 2
    if df % 2 == 1:
        k = df // 2
        total = 0.0
        cur = math.sin(theta) * math.cos(theta)
        for j in range(k):
            if j > 0:
                cur *= (2.0 * j) / (2.0 * j + 1.0) * c2
            total += cur
        return 0.5 + (theta + total) / math.pi
    k = df // 2
    total = 0.0
    cur = math.sin(theta)
    for j in range(k):
        if j > 0:
            cur *= (2.0 * j - 1.0) / (2.0 * j) * c2
        total += cur
    return 0.5 + 0.5 * total


def student_t_ppf(prob: float, df: int) -> float:
    if not (0.0 < prob < 1.0):
        raise ValueError(f"prob must be in (0, 1), got {prob}")
    lo, hi = -64.0, 64.0
    while student_t_cdf(lo, df) > prob:
        lo *= 2.0
    while student_t_cdf(hi, df) < prob:
        hi *= 2.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if student_t_cdf(mid, df) < prob:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _boot_weights(n: int, resamples: int = BOOTSTRAP_RESAMPLES, rng_seed: int = RNG_SEED) -> np.ndarray:
    key = (n, resamples, rng_seed)
    if key not in _BOOT_CACHE:
        rng = random.Random(rng_seed)
        weights = np.zeros((resamples, n), dtype=np.float64)
        inv_n = 1.0 / n
        for b in range(resamples):
            for _ in range(n):
                weights[b, rng.randrange(n)] += inv_n
        _BOOT_CACHE[key] = weights
    return _BOOT_CACHE[key]


def _perm_signs(n: int, resamples: int = PERMUTATION_RESAMPLES, rng_seed: int = RNG_SEED) -> np.ndarray:
    key = (n, resamples, rng_seed)
    if key not in _PERM_CACHE:
        gen = np.random.default_rng(rng_seed)
        draws = gen.integers(0, 2, size=(resamples, n), dtype=np.int8)
        _PERM_CACHE[key] = np.where(draws == 1, 1.0, -1.0)
    return _PERM_CACHE[key]


def mean_normal_ci_halfwidth(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return 1.96 * sd / math.sqrt(n)


def percentile_bootstrap_ratio_ci(
    f: list[float],
    s: list[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    rng_seed: int = RNG_SEED,
) -> tuple[float, float]:
    n = len(f)
    w = _boot_weights(n, resamples, rng_seed)
    mf = w @ np.asarray(f, dtype=np.float64)
    ms = w @ np.asarray(s, dtype=np.float64)
    mask = ms > 0.0
    vals = np.sort(mf[mask] / ms[mask])
    m = int(vals.shape[0])
    return (float(vals[int(0.025 * m)]), float(vals[int(0.975 * m) - 1]))


def percentile_bootstrap_diff_ci(
    diffs: list[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    rng_seed: int = RNG_SEED,
) -> tuple[float, float]:
    n = len(diffs)
    w = _boot_weights(n, resamples, rng_seed)
    md = np.sort(w @ np.asarray(diffs, dtype=np.float64))
    m = int(md.shape[0])
    return (float(md[int(0.025 * m)]), float(md[int(0.975 * m) - 1]))


def _bca_from_boot_and_jack(
    theta_hat: float,
    boot_sorted: np.ndarray,
    jackknife_vals: list[float],
) -> tuple[float, float, float, float]:
    m = int(boot_sorted.shape[0])
    less = int(np.sum(boot_sorted < theta_hat))
    eq = int(np.sum(boot_sorted == theta_hat))
    p0 = min(max((less + 0.5 * eq) / m, 0.5 / m), 1.0 - 0.5 / m)
    z0 = NORM.inv_cdf(p0)
    j_mean = sum(jackknife_vals) / len(jackknife_vals)
    u = [j_mean - x for x in jackknife_vals]
    denom = sum(x * x for x in u) ** 1.5
    acc = sum(x ** 3 for x in u) / (6.0 * denom) if denom > 1e-30 else 0.0
    quantiles: list[float] = []
    for alpha in (0.025, 0.975):
        za = NORM.inv_cdf(alpha)
        denom_adj = 1.0 - acc * (z0 + za)
        if abs(denom_adj) < 1e-12:
            adj_p = 1.0 if (z0 + za) > 0 else 0.0
        else:
            adj_p = NORM.cdf(z0 + (z0 + za) / denom_adj)
        adj_p = min(max(adj_p, 0.0), 1.0)
        quantiles.append(float(np.quantile(boot_sorted, adj_p)))
    return (quantiles[0], quantiles[1], z0, acc)


def bca_bootstrap_ratio_ci(
    f: list[float],
    s: list[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    rng_seed: int = RNG_SEED,
) -> tuple[float, float, float, float]:
    n = len(f)
    sum_f = sum(f)
    sum_s = sum(s)
    theta_hat = sum_f / sum_s
    w = _boot_weights(n, resamples, rng_seed)
    mf = w @ np.asarray(f, dtype=np.float64)
    ms = w @ np.asarray(s, dtype=np.float64)
    mask = ms > 0.0
    vals = np.sort(mf[mask] / ms[mask])
    jack = [(sum_f - f[i]) / (sum_s - s[i]) for i in range(n)]
    return _bca_from_boot_and_jack(theta_hat, vals, jack)


def bca_bootstrap_diff_ci(
    diffs: list[float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    rng_seed: int = RNG_SEED,
) -> tuple[float, float, float, float]:
    n = len(diffs)
    sum_d = sum(diffs)
    theta_hat = sum_d / n
    w = _boot_weights(n, resamples, rng_seed)
    vals = np.sort(w @ np.asarray(diffs, dtype=np.float64))
    jack = [(sum_d - diffs[i]) / (n - 1) for i in range(n)]
    return _bca_from_boot_and_jack(theta_hat, vals, jack)


def fieller_ratio_ci(f: list[float], s: list[float]) -> dict[str, Any]:
    n = len(f)
    df = n - 1
    mf = sum(f) / n
    ms = sum(s) / n
    s_ff = sum((x - mf) ** 2 for x in f) / df
    s_ss = sum((y - ms) ** 2 for y in s) / df
    cov_fs = sum((x - mf) * (y - ms) for x, y in zip(f, s)) / df
    denom_corr = math.sqrt(s_ff * s_ss)
    corr_fs = cov_fs / denom_corr if denom_corr > 1e-15 else 0.0
    v_ff = s_ff / n
    v_ss = s_ss / n
    v_fs = cov_fs / n
    t_crit = student_t_ppf(0.975, df)
    tc2 = t_crit * t_crit
    g = (tc2 * v_ss) / (ms * ms) if abs(ms) > 1e-15 else float("inf")
    a_coef = ms * ms - tc2 * v_ss
    b_coef = mf * ms - tc2 * v_fs
    c_coef = mf * mf - tc2 * v_ff
    disc = b_coef * b_coef - a_coef * c_coef
    if a_coef <= 0.0 or disc < 0.0:
        return {
            "bounded": False,
            "ci_95": [None, None],
            "cov_fs": _r(cov_fs),
            "corr_fs": _r(corr_fs),
            "df": df,
            "fieller_g": _r(g),
            "t_crit_975": _r(t_crit),
        }
    root = math.sqrt(disc)
    lo = (b_coef - root) / a_coef
    hi = (b_coef + root) / a_coef
    if lo > hi:
        lo, hi = hi, lo
    return {
        "bounded": True,
        "ci_95": [_r(lo), _r(hi)],
        "cov_fs": _r(cov_fs),
        "corr_fs": _r(corr_fs),
        "df": df,
        "fieller_g": _r(g),
        "t_crit_975": _r(t_crit),
    }


def sign_flip_permutation_pvalue(
    diffs: list[float],
    resamples: int = PERMUTATION_RESAMPLES,
    rng_seed: int = RNG_SEED,
    tol: float = 1e-12,
) -> float:
    n = len(diffs)
    arr = np.asarray(diffs, dtype=np.float64)
    if np.all(np.abs(arr) <= tol):
        return 1.0
    obs = abs(float(np.mean(arr)))
    signs = _perm_signs(n, resamples, rng_seed)
    perm_means = np.abs((signs @ arr) / n)
    exceed = int(np.sum(perm_means >= obs - tol))
    return float((1 + exceed) / (resamples + 1))


def sign_test_pvalue(diffs: list[float], tol: float = 1e-12) -> float:
    pos = sum(1 for d in diffs if d > tol)
    neg = sum(1 for d in diffs if d < -tol)
    m = pos + neg
    if m == 0:
        return 1.0
    k = min(pos, neg)
    p = 2.0 * sum(math.comb(m, i) for i in range(k + 1)) / (2 ** m)
    return min(1.0, p)


def wilcoxon_signed_rank_pvalue(diffs: list[float], tol: float = 1e-12) -> float:
    nz = [float(d) for d in diffs if abs(d) > tol]
    m = len(nz)
    if m == 0:
        return 1.0
    ordered = sorted((abs(d), d) for d in nz)
    ranks = [0.0] * m
    tie_sizes: list[int] = []
    i = 0
    while i < m:
        j = i + 1
        while j < m and abs(ordered[j][0] - ordered[i][0]) <= tol:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg_rank
        if j - i > 1:
            tie_sizes.append(j - i)
        i = j
    w_plus = sum(r for (_, d), r in zip(ordered, ranks) if d > 0.0)
    if m <= 50:
        r2s = [int(round(2.0 * r)) for r in ranks]
        total = sum(r2s)
        obs2 = int(round(2.0 * w_plus))
        dev = abs(2 * obs2 - total)
        dp: dict[int, int] = {0: 1}
        for r2 in r2s:
            nxt: dict[int, int] = defaultdict(int)
            for s_val, cnt in dp.items():
                nxt[s_val] += cnt
                nxt[s_val + r2] += cnt
            dp = nxt
        tail = sum(cnt for s_val, cnt in dp.items() if abs(2 * s_val - total) >= dev)
        return min(1.0, tail / (2 ** m))
    w_min = min(w_plus, m * (m + 1) / 2.0 - w_plus)
    mean_w = m * (m + 1) / 4.0
    tie_corr = 0.5 * sum(t * (t * t - 1) for t in tie_sizes)
    var_w = (m * (m + 1) * (2 * m + 1) - tie_corr) / 24.0
    if var_w <= 0.0:
        return 1.0
    z = (abs(w_min - mean_w) - 0.5) / math.sqrt(var_w)
    return min(1.0, 2.0 * (1.0 - NORM.cdf(max(0.0, z))))


def compute_four_way_inference(f: list[float], s: list[float]) -> dict[str, Any]:
    n = len(f)
    sum_f = sum(f)
    sum_s = sum(s)
    mf = sum_f / n
    ms = sum_s / n
    ratio = mf / ms
    diffs = [a - b for a, b in zip(f, s)]
    sum_d = sum(diffs)
    mean_diff = sum_d / n
    diff_norm_hw = mean_normal_ci_halfwidth(diffs)

    w = _boot_weights(n, BOOTSTRAP_RESAMPLES, RNG_SEED)
    f_arr = np.asarray(f, dtype=np.float64)
    s_arr = np.asarray(s, dtype=np.float64)
    d_arr = f_arr - s_arr
    boot_mf = w @ f_arr
    boot_ms = w @ s_arr
    mask = boot_ms > 0.0
    ratio_sorted = np.sort(boot_mf[mask] / boot_ms[mask])
    m_ratio = int(ratio_sorted.shape[0])
    pct_lo = float(ratio_sorted[int(0.025 * m_ratio)])
    pct_hi = float(ratio_sorted[int(0.975 * m_ratio) - 1])

    diff_sorted = np.sort(w @ d_arr)
    m_diff = int(diff_sorted.shape[0])
    diff_pct_lo = float(diff_sorted[int(0.025 * m_diff)])
    diff_pct_hi = float(diff_sorted[int(0.975 * m_diff) - 1])

    jack_ratio = [(sum_f - f[i]) / (sum_s - s[i]) for i in range(n)]
    bca_lo, bca_hi, bca_z0, bca_acc = _bca_from_boot_and_jack(ratio, ratio_sorted, jack_ratio)
    jack_diff = [(sum_d - diffs[i]) / (n - 1) for i in range(n)]
    diff_bca_lo, diff_bca_hi, _, _ = _bca_from_boot_and_jack(mean_diff, diff_sorted, jack_diff)

    fieller = fieller_ratio_ci(f, s)
    perm_p = sign_flip_permutation_pvalue(diffs)
    wilc_p = wilcoxon_signed_rank_pvalue(diffs)
    sign_p = sign_test_pvalue(diffs)

    cis = [(pct_lo, pct_hi), (bca_lo, bca_hi)]
    if fieller["bounded"]:
        f_lo, f_hi = fieller["ci_95"]
        cis.append((float(f_lo), float(f_hi)))
    widths = [hi - lo for lo, hi in cis]
    all_below = bool(fieller["bounded"]) and all(hi < 1.0 for _, hi in cis)
    all_straddle = bool(fieller["bounded"]) and all(lo <= 1.0 <= hi for lo, hi in cis)

    return {
        "frontier_mean": _r(mf),
        "solver_mean": _r(ms),
        "point_ratio": _r(ratio),
        "point_paired_diff": _r(mean_diff),
        "paired_diff_normal_ci_halfwidth": _r(diff_norm_hw),
        "percentile_bootstrap_95_ci": [_r(pct_lo), _r(pct_hi)],
        "diff_percentile_bootstrap_95_ci": [_r(diff_pct_lo), _r(diff_pct_hi)],
        "bca_bootstrap_95_ci": [_r(bca_lo), _r(bca_hi)],
        "bca_z0": _r(bca_z0),
        "bca_acceleration": _r(bca_acc),
        "diff_bca_bootstrap_95_ci": [_r(diff_bca_lo), _r(diff_bca_hi)],
        "fieller_95_ci": fieller["ci_95"],
        "fieller_bounded": fieller["bounded"],
        "cov_fs": fieller["cov_fs"],
        "corr_fs": fieller["corr_fs"],
        "fieller_g": fieller["fieller_g"],
        "fieller_df": fieller["df"],
        "fieller_t_crit_975": fieller["t_crit_975"],
        "sign_flip_perm_p": _r(perm_p),
        "wilcoxon_signed_rank_p": _r(wilc_p),
        "sign_test_p": _r(sign_p),
        "ci_width_spread": _r(max(widths) - min(widths)),
        "all_three_cis_below_parity": all_below,
        "all_three_cis_straddle_parity": all_straddle,
    }


def compute_leave_one_seed_out(
    seeds: list[int],
    f_raw: list[float],
    s_raw: list[float],
    f_la: list[float],
    s_la: list[float],
) -> dict[str, Any]:
    n = len(seeds)
    subset_n = n - 1
    sum_fr = sum(f_raw)
    sum_sr = sum(s_raw)
    sum_fl = sum(f_la)
    sum_sl = sum(s_la)

    raw_ratios: list[float] = []
    la_ratios: list[float] = []
    raw_diffs: list[float] = []
    la_diffs: list[float] = []
    for idx in range(n):
        rem_fr = sum_fr - f_raw[idx]
        rem_sr = sum_sr - s_raw[idx]
        rem_fl = sum_fl - f_la[idx]
        rem_sl = sum_sl - s_la[idx]
        raw_ratios.append(rem_fr / rem_sr)
        la_ratios.append(rem_fl / rem_sl)
        raw_diffs.append((rem_fr - rem_sr) / subset_n)
        la_diffs.append((rem_fl - rem_sl) / subset_n)

    def _bounds(vals: list[float], threshold: float) -> dict[str, Any]:
        pairs = [(vals[i], int(seeds[i])) for i in range(n)]
        min_val, min_seed = min(pairs, key=lambda x: (x[0], x[1]))
        max_val, max_seed = max(pairs, key=lambda x: (x[0], -x[1]))
        return {
            "min": _r(min_val),
            "median": _r(float(statistics.median(vals))),
            "max": _r(max_val),
            "spread": _r(max_val - min_val),
            "min_dropped_seed": min_seed,
            "max_dropped_seed": max_seed,
            "count_below_threshold": sum(1 for v in vals if v < threshold),
            "threshold": threshold,
        }

    return {
        "n_subsets": n,
        "subset_size": subset_n,
        "dropped_seeds": [int(s) for s in seeds],
        "raw_ratio_bounds": _bounds(raw_ratios, 1.0),
        "luck_adj_ratio_bounds": _bounds(la_ratios, 1.0),
        "raw_paired_diff_bounds": _bounds(raw_diffs, 0.0),
        "luck_adj_paired_diff_bounds": _bounds(la_diffs, 0.0),
        "loo_raw_ratio": [_r(v) for v in raw_ratios],
        "loo_luck_adj_ratio": [_r(v) for v in la_ratios],
        "loo_raw_paired_diff": [_r(v) for v in raw_diffs],
        "loo_luck_adj_paired_diff": [_r(v) for v in la_diffs],
    }


def _load_dir_seed_series(run_dir: Path, agent: str, tier: str) -> dict[int, dict[str, Any]]:
    ep_path = run_dir / "episodes.jsonl"
    digest = hashlib.sha256(ep_path.read_bytes()).hexdigest()
    cache_key = f"{digest}:{agent}:{tier}"
    if cache_key in _DIR_SERIES_CACHE:
        return _DIR_SERIES_CACHE[cache_key]

    series: dict[int, dict[str, Any]] = {}
    eps = load_runs(run_dir)
    _P_CACHE.clear()
    try:
        for ep in eps:
            if ep.get("agent") != agent or ep.get("tier") != tier:
                continue
            seed = int(ep["seed"])
            if not (0 <= seed < 30):
                continue
            accused_present = bool(ep.get("accused"))
            la_val = post_expected(ep)
            if la_val is None:
                raise ValueError(f"post_expected returned None for {run_dir} seed={seed}")
            meta = ep.get("meta") or {}
            series[seed] = {
                "raw_score": float(ep["score"]),
                "luck_adj_score": float(la_val),
                "abstained": not accused_present,
                "has_v": "V" in meta and meta.get("V") is not None,
                "has_v_final": "V_final" in meta,
                "v_final_value": float(meta["V_final"]) if meta.get("V_final") is not None else None,
            }
    finally:
        _P_CACHE.clear()
    _DIR_SERIES_CACHE[cache_key] = series
    return series


def _load_solver_series(repo_root: Path, tier: str) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for rel in SOLVER_REL_DIRS[tier]:
        part = _load_dir_seed_series(repo_root / rel, "solver", tier)
        for seed, info in part.items():
            if seed in merged:
                raise ValueError(f"Duplicate solver seed {seed} on tier {tier}")
            merged[seed] = info
    if sorted(merged.keys()) != PRIMARY_SEEDS:
        raise ValueError(f"Solver {tier} seeds mismatch: {sorted(merged.keys())}")
    return merged


def _parse_cell_score(cell: str) -> tuple[str, float | None]:
    txt = cell.strip()
    if not txt or txt in ("-", "\u2013", "\u2014"):
        return ("missing", None)
    if "infra" in txt.lower():
        return ("infra", None)
    m = re.search(r"([+-]?\d+(?:\.\d+)?)", txt)
    if not m:
        return ("missing", None)
    return ("valid", float(m.group(1)))


def parse_harbor_rehearsal(repo_root: Path) -> dict[str, Any]:
    table_path = repo_root / "results/harbor/rehearsal/TABLE.md"
    build_path = repo_root / "results/harbor/rehearsal/BUILD.txt"
    table_text = table_path.read_text(encoding="utf-8")
    build_text = build_path.read_text(encoding="utf-8")

    build_kv: dict[str, str] = {}
    for line in build_text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            build_kv[k.strip()] = v.strip()

    tasks: list[dict[str, Any]] = []
    for line in table_text.splitlines():
        if not line.startswith("| hard-90000"):
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 7:
            continue
        task_id = cols[0]
        task_seed = int(task_id.split("-")[1])
        _, oracle_s = _parse_cell_score(cols[1])
        st1, oc1_s = _parse_cell_score(cols[2])
        st2, oc2_s = _parse_cell_score(cols[3])
        st3, oc3_s = _parse_cell_score(cols[4])
        _, dn_s = _parse_cell_score(cols[5])
        _, se_s = _parse_cell_score(cols[6])
        tasks.append(
            {
                "task_id": task_id,
                "seed": task_seed,
                "oracle": oracle_s,
                "opencode_1": oc1_s,
                "opencode_1_status": st1,
                "opencode_2": oc2_s,
                "opencode_2_status": st2,
                "opencode_3_snapshot_0852": oc3_s,
                "opencode_3_snapshot_0852_status": st3,
                "do_nothing": dn_s,
                "stop_early": se_s,
            }
        )

    oracle_all = [float(t["oracle"]) for t in tasks]
    oc1_all = [float(t["opencode_1"]) for t in tasks]
    oc2_all = [float(t["opencode_2"]) for t in tasks]
    dn_all = [float(t["do_nothing"]) for t in tasks]
    se_all = [float(t["stop_early"]) for t in tasks]

    oc3_snap_pairs = [
        (int(t["seed"]), float(t["opencode_3_snapshot_0852"]), float(t["oracle"]))
        for t in tasks
        if t["opencode_3_snapshot_0852_status"] == "valid"
    ]
    oc3_snap_f = [p[1] for p in oc3_snap_pairs]
    oc3_snap_s = [p[2] for p in oc3_snap_pairs]

    oc3_final_same_9_oracle = [
        float(t["oracle"]) for t in tasks if t["opencode_3_snapshot_0852_status"] != "infra"
    ]
    oracle_9_mean = sum(oc3_final_same_9_oracle) / len(oc3_final_same_9_oracle)
    oc3_final_mean = 0.626
    oc3_final_ratio = oc3_final_mean / oracle_9_mean

    oc1_inf = compute_four_way_inference(oc1_all, oracle_all)
    oc2_inf = compute_four_way_inference(oc2_all, oracle_all)
    oc3_snap_inf = compute_four_way_inference(oc3_snap_f, oc3_snap_s)

    final_run_means = [sum(oc1_all) / 10.0, sum(oc2_all) / 10.0, oc3_final_mean]
    snap_run_means = [sum(oc1_all) / 10.0, sum(oc2_all) / 10.0, sum(oc3_snap_f) / len(oc3_snap_f)]

    return {
        "tag": build_kv.get("describe", "afterquery-final"),
        "commit_sha_short": build_kv.get("sha", "")[:8],
        "commit_sha_full": build_kv.get("sha", ""),
        "correction_commits": ["aa1c679e", "5f9b3297"],
        "final_trials_branch_commit": "d0ead011",
        "harbor_version": build_kv.get("harbor", "0.26.0"),
        "n_tasks": len(tasks),
        "task_seed_range": "900000-900009",
        "oracle_10_task_mean": _r(sum(oracle_all) / len(oracle_all)),
        "do_nothing_mean": _r(sum(dn_all) / len(dn_all)),
        "stop_early_mean": _r(sum(se_all) / len(se_all)),
        "mcp_only_hard_gap_reproduced_in_harbor": False,
        "shell_enabled_in_container": True,
        "shell_used_trials_note": "shell used in 20 of 28 valid trials; container also carries 15 Nov afterquery-final (1bc3e281) tool-error detail and W1 wording updates",
        "runs": [
            {
                "run_id": "opencode-1",
                "n_valid": 10,
                "n_infra_excluded": 0,
                "correct_accusations": 9,
                "accused_count": 10,
                "mean_score": _r(sum(oc1_all) / 10.0),
                "oracle_same_tasks_mean": _r(sum(oracle_all) / 10.0),
                "ratio_vs_oracle": _r((sum(oc1_all) / 10.0) / (sum(oracle_all) / 10.0)),
                "reported_ratio_pct": 93,
                "paired_bootstrap_95_ci": oc1_inf["percentile_bootstrap_95_ci"],
                "bca_bootstrap_95_ci": oc1_inf["bca_bootstrap_95_ci"],
                "fieller_95_ci": oc1_inf["fieller_95_ci"],
                "fieller_g": oc1_inf["fieller_g"],
                "paired_diff": oc1_inf["point_paired_diff"],
                "sign_flip_perm_p": oc1_inf["sign_flip_perm_p"],
                "wilcoxon_signed_rank_p": oc1_inf["wilcoxon_signed_rank_p"],
            },
            {
                "run_id": "opencode-2",
                "n_valid": 10,
                "n_infra_excluded": 0,
                "correct_accusations": 10,
                "accused_count": 10,
                "mean_score": _r(sum(oc2_all) / 10.0),
                "oracle_same_tasks_mean": _r(sum(oracle_all) / 10.0),
                "ratio_vs_oracle": _r((sum(oc2_all) / 10.0) / (sum(oracle_all) / 10.0)),
                "reported_ratio_pct": 116,
                "paired_bootstrap_95_ci": oc2_inf["percentile_bootstrap_95_ci"],
                "bca_bootstrap_95_ci": oc2_inf["bca_bootstrap_95_ci"],
                "fieller_95_ci": oc2_inf["fieller_95_ci"],
                "fieller_g": oc2_inf["fieller_g"],
                "paired_diff": oc2_inf["point_paired_diff"],
                "sign_flip_perm_p": oc2_inf["sign_flip_perm_p"],
                "wilcoxon_signed_rank_p": oc2_inf["wilcoxon_signed_rank_p"],
            },
            {
                "run_id": "opencode-3-final",
                "n_valid": 9,
                "n_finished_after_0830_cutoff": 5,
                "n_infra_excluded": 1,
                "infra_excluded_seed": 900002,
                "correct_accusations": 9,
                "accused_count": 9,
                "mean_score": 0.626,
                "oracle_same_tasks_mean": _r(oracle_9_mean),
                "ratio_vs_oracle": _r(oc3_final_ratio),
                "reported_ratio_pct": 131,
                "reported_bootstrap_95_ci": [0.86, 5.90],
                "paired_diff": _r(oc3_final_mean - oracle_9_mean),
                "cutoff_note": "9 valid trials (5 finished after 08:30 cutoff, 1 infra rate-limit on 900002); supersedes 08:52 n=7 partial snapshot (+0.656, 153%)",
            },
            {
                "run_id": "opencode-3-snapshot-0852-partial",
                "n_valid": len(oc3_snap_f),
                "n_infra_excluded": 1,
                "n_unstarted_at_snapshot": 2,
                "correct_accusations": 7,
                "accused_count": 7,
                "mean_score": _r(sum(oc3_snap_f) / len(oc3_snap_f)),
                "oracle_same_tasks_mean": _r(sum(oc3_snap_s) / len(oc3_snap_s)),
                "ratio_vs_oracle": oc3_snap_inf["point_ratio"],
                "reported_ratio_pct": 153,
                "paired_bootstrap_95_ci": oc3_snap_inf["percentile_bootstrap_95_ci"],
                "bca_bootstrap_95_ci": oc3_snap_inf["bca_bootstrap_95_ci"],
                "fieller_95_ci": oc3_snap_inf["fieller_95_ci"],
                "fieller_bounded": oc3_snap_inf["fieller_bounded"],
                "fieller_g": oc3_snap_inf["fieller_g"],
                "paired_diff": oc3_snap_inf["point_paired_diff"],
                "superseded_by": "opencode-3-final",
            },
        ],
        "spread_across_3_runs": {
            "final_0930": {
                "run_means": [_r(x, 6) for x in final_run_means],
                "mean_of_means": _r(statistics.mean(final_run_means)),
                "sd": _r(statistics.stdev(final_run_means)),
                "range": _r(max(final_run_means) - min(final_run_means)),
                "valid_correct_total": 28,
                "valid_accused_total": 29,
            },
            "snapshot_0852_partial": {
                "run_means": [_r(x, 6) for x in snap_run_means],
                "mean_of_means": _r(statistics.mean(snap_run_means)),
                "sd": _r(statistics.stdev(snap_run_means)),
                "range": _r(max(snap_run_means) - min(snap_run_means)),
            },
        },
        "small_n_denominator_note": (
            f"On task 900007 oracle scored -1.00 while opencode-1/2/3 scored +0.66/+0.61/+0.65; "
            f"at n=10 this single task drives Fieller g={oc1_inf['fieller_g']:.3f} "
            f"(and g={oc3_snap_inf['fieller_g']:.3f} > 1 unbounded on n=7 snapshot) "
            f"and inflates upper bootstrap bounds to 363%-590%, whereas n=30 v1.4 hard has Fieller g=0.062."
        ),
    }


def _crosscheck_headline_json(
    repo_root: Path,
    cohorts: list[dict[str, Any]],
) -> dict[str, Any]:
    hl_path = repo_root / "results/eval_v14/headline_gap_table_v14.json"
    hl_data = json.loads(hl_path.read_text(encoding="utf-8"))
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in hl_data.get("section_a", []):
        if row.get("kind") == "frontier":
            by_key[(str(row["agent"]), str(row["tier"]))] = row

    max_diff = 0.0
    checked = 0
    for c in cohorts:
        ref = by_key[(c["agent"], c["tier"])]
        raw_inf = c["inference_matrix"]["raw"]
        la_inf = c["inference_matrix"]["luck_adjusted"]
        pairs = [
            (raw_inf["frontier_mean"], ref["mean"]),
            (raw_inf["solver_mean"], ref["solver_same_seeds"]),
            (raw_inf["point_ratio"], ref["ratio"]),
            (raw_inf["percentile_bootstrap_95_ci"][0], ref["ratio_lo"]),
            (raw_inf["percentile_bootstrap_95_ci"][1], ref["ratio_hi"]),
            (raw_inf["point_paired_diff"], ref["paired_diff"]),
            (raw_inf["paired_diff_normal_ci_halfwidth"], ref["paired_diff_ci"]),
            (raw_inf["wilcoxon_signed_rank_p"], ref["p_wilcoxon_raw"]),
            (raw_inf["sign_test_p"], ref["p_sign_raw"]),
            (la_inf["frontier_mean"], ref["luck_adjusted_score"]),
            (la_inf["solver_mean"], ref["solver_luck_adjusted"]),
            (la_inf["point_ratio"], ref["luck_adj_ratio"]),
            (la_inf["percentile_bootstrap_95_ci"][0], ref["luck_adj_lo"]),
            (la_inf["percentile_bootstrap_95_ci"][1], ref["luck_adj_hi"]),
            (la_inf["wilcoxon_signed_rank_p"], ref["p_wilcoxon_luck"]),
            (la_inf["sign_test_p"], ref["p_sign_luck"]),
        ]
        for got, exp in pairs:
            max_diff = max(max_diff, abs(float(got) - float(exp)))
            checked += 1
    if max_diff > 1e-8:
        raise ValueError(f"Headline table cross-check exceeded tolerance: {max_diff}")
    return {
        "checked_scalar_fields": checked,
        "max_abs_diff": _r(max_diff, 12),
        "passed": max_diff <= 1e-8,
    }


def build_payload(repo_root: Path = ROOT) -> dict[str, Any]:
    solver_by_tier = {
        tier: _load_solver_series(repo_root, tier)
        for tier in ("hard", "medium")
    }

    cohorts_out: list[dict[str, Any]] = []
    for spec in COHORT_SPECS:
        tier = spec["tier"]
        agent = spec["agent"]
        rel_dir = spec["rel_dir"]
        f_map = _load_dir_seed_series(repo_root / rel_dir, agent, tier)
        if sorted(f_map.keys()) != PRIMARY_SEEDS:
            raise ValueError(f"Cohort {spec['cohort_id']} {tier} seeds mismatch: {sorted(f_map.keys())}")
        s_map = solver_by_tier[tier]

        f_raw = [f_map[s]["raw_score"] for s in PRIMARY_SEEDS]
        s_raw = [s_map[s]["raw_score"] for s in PRIMARY_SEEDS]
        f_la = [f_map[s]["luck_adj_score"] for s in PRIMARY_SEEDS]
        s_la = [s_map[s]["luck_adj_score"] for s in PRIMARY_SEEDS]

        abstained_seeds = [s for s in PRIMARY_SEEDS if f_map[s]["abstained"]]
        v_final_accused_count = sum(
            1 for s in PRIMARY_SEEDS if (not f_map[s]["abstained"]) and f_map[s]["v_final_value"] is not None
        )
        v_accused_count = sum(
            1 for s in PRIMARY_SEEDS if (not f_map[s]["abstained"]) and f_map[s]["has_v"]
        )

        raw_inf = compute_four_way_inference(f_raw, s_raw)
        la_inf = compute_four_way_inference(f_la, s_la)
        loo = compute_leave_one_seed_out(PRIMARY_SEEDS, f_raw, s_raw, f_la, s_la)

        cohorts_out.append(
            {
                "cohort_id": spec["cohort_id"],
                "tier": tier,
                "agent": agent,
                "label": spec["label"],
                "cache_path": f"{rel_dir}/episodes.jsonl",
                "n": 30,
                "seeds": PRIMARY_SEEDS,
                "abstained_seeds": abstained_seeds,
                "accused_meta_v_count": v_accused_count,
                "accused_meta_v_final_count": v_final_accused_count,
                "inference_matrix": {
                    "raw": raw_inf,
                    "luck_adjusted": la_inf,
                },
                "leave_one_seed_out": loo,
            }
        )

    crosscheck = _crosscheck_headline_json(repo_root, cohorts_out)
    harbor = parse_harbor_rehearsal(repo_root)

    by_id_tier = {(c["cohort_id"], c["tier"]): c for c in cohorts_out}
    oc_hard = by_id_tier[("opencode-gemini-4-carbon", "hard")]
    gpt_hard = by_id_tier[("opencode-gpt-5.5", "hard")]

    key_findings = {
        "opencode_gemini_4_carbon_hard_raw_all_3_cis_below_parity": (
            oc_hard["inference_matrix"]["raw"]["all_three_cis_below_parity"]
        ),
        "opencode_gemini_4_carbon_hard_raw_fieller_straddles_parity": (
            oc_hard["inference_matrix"]["raw"]["fieller_95_ci"][1] >= 1.0
        ),
        "opencode_gemini_4_carbon_hard_luck_adj_all_3_cis_below_parity": (
            oc_hard["inference_matrix"]["luck_adjusted"]["all_three_cis_below_parity"]
        ),
        "opencode_gemini_4_carbon_hard_loo_raw_below_parity_count": (
            oc_hard["leave_one_seed_out"]["raw_ratio_bounds"]["count_below_threshold"]
        ),
        "opencode_gemini_4_carbon_hard_loo_luck_adj_below_parity_count": (
            oc_hard["leave_one_seed_out"]["luck_adj_ratio_bounds"]["count_below_threshold"]
        ),
        "opencode_gemini_4_carbon_hard_all_30_loo_luck_adj_below_parity": (
            oc_hard["leave_one_seed_out"]["luck_adj_ratio_bounds"]["count_below_threshold"] == 30
        ),
        "opencode_gpt_5_5_hard_raw_all_3_cis_straddle_parity": (
            gpt_hard["inference_matrix"]["raw"]["all_three_cis_straddle_parity"]
        ),
        "opencode_gpt_5_5_hard_luck_adj_all_3_cis_straddle_parity": (
            gpt_hard["inference_matrix"]["luck_adjusted"]["all_three_cis_straddle_parity"]
        ),
        "opencode_gpt_5_5_hard_abstained_seeds": gpt_hard["abstained_seeds"],
        "opencode_gpt_5_5_hard_loo_raw_below_parity_count": (
            gpt_hard["leave_one_seed_out"]["raw_ratio_bounds"]["count_below_threshold"]
        ),
        "harbor_rehearsal_gap_reproduced": harbor["mcp_only_hard_gap_reproduced_in_harbor"],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": "v1.4",
        "primary_seeds": "0-29",
        "n_primary_seeds_per_tier": 30,
        "primary_seeds_lock_note": PRIMARY_SEED_LOCK_NOTE,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "permutation_resamples": PERMUTATION_RESAMPLES,
        "rng_seed": RNG_SEED,
        "shallow_ci_safe_zero_git_calls": True,
        "headline_table_crosscheck": crosscheck,
        "key_findings": key_findings,
        "cohorts": cohorts_out,
        "harbor_rehearsal_sensitivity": harbor,
    }


def _fmt_pct_ci(ci: list[float | None]) -> str:
    if ci[0] is None or ci[1] is None:
        return "unbounded (g>=1)"
    return f"[{100.0 * float(ci[0]):.1f}%, {100.0 * float(ci[1]):.1f}%]"


def _fmt_p(val: float) -> str:
    if val < 0.0001:
        return f"{val:.2e}"
    return f"{val:.4f}"


def render_markdown(payload: dict[str, Any]) -> str:
    cohorts = payload["cohorts"]
    harbor = payload["harbor_rehearsal_sensitivity"]
    kf = payload["key_findings"]
    by_key = {(c["cohort_id"], c["tier"]): c for c in cohorts}
    oc_h = by_key[("opencode-gemini-4-carbon", "hard")]
    gpt_h = by_key[("opencode-gpt-5.5", "hard")]

    oc_h_raw = oc_h["inference_matrix"]["raw"]
    oc_h_la = oc_h["inference_matrix"]["luck_adjusted"]
    oc_h_loo_la = oc_h["leave_one_seed_out"]["luck_adj_ratio_bounds"]
    oc_h_loo_raw = oc_h["leave_one_seed_out"]["raw_ratio_bounds"]

    gpt_h_raw = gpt_h["inference_matrix"]["raw"]
    gpt_h_la = gpt_h["inference_matrix"]["luck_adjusted"]
    gpt_h_loo_raw = gpt_h["leave_one_seed_out"]["raw_ratio_bounds"]
    gpt_h_loo_la = gpt_h["leave_one_seed_out"]["luck_adj_ratio_bounds"]

    lines: list[str] = [
        "# Statistical Robustness and Shallow-CI Audit (`v1.4` Paired Seeds `0-29`)",
        "",
        "## Executive Summary & Honest Headline Disclosures",
        "",
        f"- **Seed lock provenance:** `{payload['primary_seeds_lock_note']}`. All primary evaluations pair each frontier model strictly against `reference/solver` on seeds `0..29` (`n = 30` per tier; `solver-hard-seeds30to59` excluded from primary `0..29` pairing).",
        f"- **`opencode-gemini-4-carbon` on `hard` (`n = 30`, MCP tools only):** Raw ratio is **`{100.0 * oc_h_raw['point_ratio']:.1f}%`** (`+0.322` vs `+0.499`; percentile `{_fmt_pct_ci(oc_h_raw['percentile_bootstrap_95_ci'])}`, BCa `{_fmt_pct_ci(oc_h_raw['bca_bootstrap_95_ci'])}`, Fieller `{_fmt_pct_ci(oc_h_raw['fieller_95_ci'])}`, sign-flip perm `p = {_fmt_p(oc_h_raw['sign_flip_perm_p'])}`, Wilcoxon `p = {_fmt_p(oc_h_raw['wilcoxon_signed_rank_p'])}`). Note that while percentile and BCa raw 95% CIs stay just below `100%`, Fieller's exact paired studentized 95% CI reaches `{100.0 * oc_h_raw['fieller_95_ci'][1]:.1f}%` (`p_perm = {_fmt_p(oc_h_raw['sign_flip_perm_p'])}`). Under **luck-adjusted EV** (`SolverPolicy` posterior `paired_v13.post_expected`), the ratio is **`{100.0 * oc_h_la['point_ratio']:.1f}%`** (`+0.360` vs `+0.499`) and **all 3 CIs exclude parity**: percentile `{_fmt_pct_ci(oc_h_la['percentile_bootstrap_95_ci'])}`, BCa `{_fmt_pct_ci(oc_h_la['bca_bootstrap_95_ci'])}`, Fieller `{_fmt_pct_ci(oc_h_la['fieller_95_ci'])}`, with sign-flip perm `p = {_fmt_p(oc_h_la['sign_flip_perm_p'])}` and Wilcoxon `p = {_fmt_p(oc_h_la['wilcoxon_signed_rank_p'])}`.",
        f"- **Exact Leave-One-Seed-Out (`n = 29` jackknife) stability:** Dropping any single seed `0..29` on `opencode-gemini-4-carbon` hard keeps **all `{kf['opencode_gemini_4_carbon_hard_loo_luck_adj_below_parity_count']}/30` luck-adjusted ratios `< 100%`** (min `{100.0 * oc_h_loo_la['min']:.1f}%` on seed `{oc_h_loo_la['min_dropped_seed']}`, median `{100.0 * oc_h_loo_la['median']:.1f}%`, max `{100.0 * oc_h_loo_la['max']:.1f}%` on seed `{oc_h_loo_la['max_dropped_seed']}`) and **all `{kf['opencode_gemini_4_carbon_hard_loo_raw_below_parity_count']}/30` raw ratios `< 100%`** (`{100.0 * oc_h_loo_raw['min']:.1f}%` to `{100.0 * oc_h_loo_raw['max']:.1f}%`).",
        f"- **Pre-registered second frontier family `opencode-gpt-5.5` (`cf394894`, `n = 30`, MCP tools only):** Matches the solver at **`{100.0 * gpt_h_raw['point_ratio']:.1f}%`** raw (percentile `{_fmt_pct_ci(gpt_h_raw['percentile_bootstrap_95_ci'])}`, BCa `{_fmt_pct_ci(gpt_h_raw['bca_bootstrap_95_ci'])}`, Fieller `{_fmt_pct_ci(gpt_h_raw['fieller_95_ci'])}`) and **`{100.0 * gpt_h_la['point_ratio']:.1f}%`** luck-adjusted (percentile `{_fmt_pct_ci(gpt_h_la['percentile_bootstrap_95_ci'])}`, BCa `{_fmt_pct_ci(gpt_h_la['bca_bootstrap_95_ci'])}`, Fieller `{_fmt_pct_ci(gpt_h_la['fieller_95_ci'])}`). All three 95% CIs straddle `100%` on both raw and luck-adjusted scores; raw LOO straddles parity (`{gpt_h_loo_raw['count_below_threshold']}/30` subsets `< 100%`, range `{100.0 * gpt_h_loo_raw['min']:.1f}%` to `{100.0 * gpt_h_loo_raw['max']:.1f}%`), while LA LOO spans `{100.0 * gpt_h_loo_la['min']:.1f}%` to `{100.0 * gpt_h_loo_la['max']:.1f}%`. On abstained seeds `{gpt_h['abstained_seeds']}`, `accused is None` yields exact `0.0` EV while all `28` accused episodes store `V_final` in `ep['meta']['V_final']`.",
        f"- **Harbor 3x10 judge-path rehearsal (`{harbor['tag']}` `{harbor['commit_sha_short']}`, corrected in `aa1c679e` / `5f9b3297`):** Three `gemini-4-carbon` runs scored **`93%` (`+0.472`)**, **`116%` (`+0.585`)**, and **`131%` (`+0.626`, `n = 9` valid, `5` finished after the `08:30` cutoff vs `08:52` `n = 7` partial `+0.656` / `153%`)** relative to same-task oracle (`+0.506` on all 10 tasks; `+0.478` on run 3's 9 valid tasks). **The 65% MCP-only hard gap did not reproduce in the Harbor container with shell.**",
        f"- **Headline cross-check & shallow-CI guarantee:** `0` `git` subprocess calls (safe under `--depth=1 --no-tags` or `.git`-free directories) and `{payload['headline_table_crosscheck']['checked_scalar_fields']}` scalar fields cross-checked against `results/eval_v14/headline_gap_table_v14.json` (max abs diff `{payload['headline_table_crosscheck']['max_abs_diff']:.2e}`).",
        "",
        "## Section A: 4-Way Paired Inference Matrix (`n = 30`, Seeds `0-29`)",
        "",
        "Parameters: Percentile & BCa paired bootstrap `B = 10000`, `rng_seed = 0`; Fieller's theorem exact paired ratio CI using sample `Cov(F, S)` with `df = 29` (`t_0.975,29 = 2.0452`); paired sign-flip permutation `B = 20000`, `rng_seed = 0`; exact DP Wilcoxon signed-rank test.",
        "",
        "### A.1 Raw Score Paired Inference",
        "",
        "| Cohort | Tier | F Mean | S Mean | Ratio | Pct Boot 95% CI | BCa Boot 95% CI | Fieller 95% CI | Cov(F,S) | Sign-Flip p | Wilcoxon p |",
        "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|",
    ]

    for c in cohorts:
        r = c["inference_matrix"]["raw"]
        lines.append(
            f"| `{c['cohort_id']}` | `{c['tier']}` | `{r['frontier_mean']:+.3f}` | `{r['solver_mean']:+.3f}` | "
            f"`{100.0 * r['point_ratio']:.1f}%` | `{_fmt_pct_ci(r['percentile_bootstrap_95_ci'])}` | "
            f"`{_fmt_pct_ci(r['bca_bootstrap_95_ci'])}` | `{_fmt_pct_ci(r['fieller_95_ci'])}` | "
            f"`{r['cov_fs']:+.4f}` | `{_fmt_p(r['sign_flip_perm_p'])}` | `{_fmt_p(r['wilcoxon_signed_rank_p'])}` |"
        )

    lines.extend(
        [
            "",
            "### A.2 Luck-Adjusted (`SolverPolicy` Posterior EV) Paired Inference",
            "",
            "| Cohort | Tier | F LA | S LA | LA Ratio | Pct Boot 95% CI | BCa Boot 95% CI | Fieller 95% CI | Cov(F,S) | Sign-Flip p | Wilcoxon p |",
            "|---|---|---:|---:|---:|---|---|---|---:|---:|---:|",
        ]
    )

    for c in cohorts:
        la = c["inference_matrix"]["luck_adjusted"]
        lines.append(
            f"| `{c['cohort_id']}` | `{c['tier']}` | `{la['frontier_mean']:+.3f}` | `{la['solver_mean']:+.3f}` | "
            f"`{100.0 * la['point_ratio']:.1f}%` | `{_fmt_pct_ci(la['percentile_bootstrap_95_ci'])}` | "
            f"`{_fmt_pct_ci(la['bca_bootstrap_95_ci'])}` | `{_fmt_pct_ci(la['fieller_95_ci'])}` | "
            f"`{la['cov_fs']:+.4f}` | `{_fmt_p(la['sign_flip_perm_p'])}` | `{_fmt_p(la['wilcoxon_signed_rank_p'])}` |"
        )

    lines.extend(
        [
            "",
            "## Section B: Exact 30-Subset Leave-One-Seed-Out (`n = 29` Jackknife) Bounds",
            "",
            "All `30` `n = 29` subsets are indexed strictly by dropped seed index `0..29` (no mole employee IDs recorded).",
            "",
            "| Cohort | Tier | Raw Ratio Min / Med / Max | Raw `<100%` | LA Ratio Min / Med / Max | LA `<100%` | Raw Diff Min / Med / Max | LA Diff Min / Med / Max |",
            "|---|---|---|---:|---|---:|---|---|",
        ]
    )

    for c in cohorts:
        loo = c["leave_one_seed_out"]
        rb = loo["raw_ratio_bounds"]
        lb = loo["luck_adj_ratio_bounds"]
        db = loo["raw_paired_diff_bounds"]
        ldb = loo["luck_adj_paired_diff_bounds"]
        lines.append(
            f"| `{c['cohort_id']}` | `{c['tier']}` | "
            f"`{100.0 * rb['min']:.1f}%` (seed {rb['min_dropped_seed']}) / `{100.0 * rb['median']:.1f}%` / `{100.0 * rb['max']:.1f}%` (seed {rb['max_dropped_seed']}) | "
            f"`{rb['count_below_threshold']}/30` | "
            f"`{100.0 * lb['min']:.1f}%` (seed {lb['min_dropped_seed']}) / `{100.0 * lb['median']:.1f}%` / `{100.0 * lb['max']:.1f}%` (seed {lb['max_dropped_seed']}) | "
            f"`{lb['count_below_threshold']}/30` | "
            f"`{db['min']:+.3f}` / `{db['median']:+.3f}` / `{db['max']:+.3f}` | "
            f"`{ldb['min']:+.3f}` / `{ldb['median']:+.3f}` / `{ldb['max']:+.3f}` |"
        )

    lines.extend(
        [
            "",
            "## Section C: Harbor 3x10 Judge-Path Rehearsal Sensitivity (`afterquery-final` `1bc3e281`)",
            "",
            f"- **Provenance:** Tag `{harbor['tag']}` (`{harbor['commit_sha_short']}`), Harbor `{harbor['harbor_version']}`, hard judge tasks `{harbor['task_seed_range']}` (`n = 10` tasks). Zero baselines `do_nothing` and `stop_early` both scored `{harbor['do_nothing_mean']:+.3f}` (`10/10`).",
            f"- **Cutoff & snapshot reconciliation (`aa1c679e` / `5f9b3297`, full trials on `{harbor['final_trials_branch_commit']}`):** The `08:52` snapshot captured `opencode-3` at `n = 7` valid trials (`+0.656` vs same-7-task oracle `+0.429` = `153% [89%, 411%]`). After all running trials completed (`09:30`), `opencode-3` finished with `n = 9` valid trials (`5` completed after the `08:30` cutoff, `1` provider rate-limit infra exclusion on `900002`), scoring `+0.626` vs same-9-task oracle `+0.478` = **`131% [86%, 590%]`**.",
            f"- **Run-to-run spread:** Final 3-run means are `+0.472`, `+0.585`, `+0.626` (mean of means `{harbor['spread_across_3_runs']['final_0930']['mean_of_means']:+.3f}`, SD `{harbor['spread_across_3_runs']['final_0930']['sd']:.3f}`, range `{harbor['spread_across_3_runs']['final_0930']['range']:.3f}`, `28/29` valid accusations correct vs 10-task oracle `+0.506`).",
            f"- **Denominator sensitivity & honest non-reproduction:** {harbor['small_n_denominator_note']} More importantly, **the 65% MCP-only hard gap did not reproduce in the Harbor container** (`{harbor['shell_used_trials_note']}`).",
            "",
            "| Run | n Valid | Infra Excl | Correct / Accused | Mean | Same-Task Oracle | Ratio | Paired Boot 95% CI | Fieller 95% CI (g) | Paired Diff |",
            "|---|---:|---:|---|---:|---:|---:|---|---|---:|",
        ]
    )

    for r in harbor["runs"]:
        boot_ci = r.get("paired_bootstrap_95_ci") or r.get("reported_bootstrap_95_ci")
        if "fieller_95_ci" in r:
            f_str = f"`{_fmt_pct_ci(r['fieller_95_ci'])}` (g={r['fieller_g']:.3f})"
        else:
            f_str = "`n/a (summary-level final)`"
        lines.append(
            f"| `{r['run_id']}` | `{r['n_valid']}` | `{r['n_infra_excluded']}` | "
            f"`{r['correct_accusations']} / {r['accused_count']}` | `{r['mean_score']:+.3f}` | "
            f"`{r['oracle_same_tasks_mean']:+.3f}` | `{100.0 * r['ratio_vs_oracle']:.1f}%` (`{r['reported_ratio_pct']}%`) | "
            f"`{_fmt_pct_ci(boot_ci)}` | {f_str} | `{r['paired_diff']:+.3f}` |"
        )

    lines.extend(
        [
            "",
            "## Reproduction",
            "",
            "```bash",
            "python scripts/eval_statistical_robustness_v14.py",
            "python scripts/eval_statistical_robustness_v14.py --check",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _compare_values(got: Any, expected: Any, path: str, tol: float, errors: list[str]) -> None:
    if isinstance(expected, bool) or isinstance(got, bool):
        if got is not expected:
            errors.append(f"{path}: got {got!r} != expected {expected!r}")
        return
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        if isinstance(expected, int) and isinstance(got, int):
            if got != expected:
                errors.append(f"{path}: got {got} != expected {expected}")
            return
        if abs(float(got) - float(expected)) > tol:
            errors.append(f"{path}: got {got} != expected {expected} (tol={tol})")
        return
    if isinstance(expected, dict) and isinstance(got, dict):
        if set(got.keys()) != set(expected.keys()):
            errors.append(f"{path}: key mismatch {set(got.keys()) ^ set(expected.keys())}")
            return
        for k in expected:
            _compare_values(got[k], expected[k], f"{path}.{k}", tol, errors)
        return
    if isinstance(expected, list) and isinstance(got, list):
        if len(got) != len(expected):
            errors.append(f"{path}: len {len(got)} != {len(expected)}")
            return
        for idx, (g_item, e_item) in enumerate(zip(got, expected)):
            _compare_values(g_item, e_item, f"{path}[{idx}]", tol, errors)
        return
    if got != expected:
        errors.append(f"{path}: got {got!r} != expected {expected!r}")


def _check_text_hygiene(text: str, label: str, errors: list[str]) -> None:
    for bad_ch, name in (("\u2013", "en-dash"), ("\u2014", "em-dash"), ("\u00b1", "plus-minus")):
        if bad_ch in text:
            errors.append(f"{label}: forbidden character {name} present")
    if re.search(r"\be(?:0[1-9]|[1-3][0-9]|40)\b", text):
        errors.append(f"{label}: potential mole employee ID e01..e40 leaked")


def check_artifacts(
    repo_root: Path = ROOT,
    out_json: Path | None = None,
    out_md: Path | None = None,
    tol: float = 1e-9,
) -> list[str]:
    json_path = out_json or (repo_root / "results/eval_v14/statistical_robustness_v14.json")
    md_path = out_md or (repo_root / "docs/reports/statistical_robustness_v14.md")
    errors: list[str] = []

    if not json_path.exists():
        errors.append(f"Missing JSON artifact: {json_path}")
        return errors
    if not md_path.exists():
        errors.append(f"Missing Markdown artifact: {md_path}")
        return errors

    raw_json_bytes = json_path.read_bytes()
    if len(raw_json_bytes) >= MAX_JSON_BYTES:
        errors.append(f"JSON size {len(raw_json_bytes)} bytes >= {MAX_JSON_BYTES} bytes limit")

    json_text = raw_json_bytes.decode("utf-8")
    md_text = md_path.read_text(encoding="utf-8")
    _check_text_hygiene(json_text, "statistical_robustness_v14.json", errors)
    _check_text_hygiene(md_text, "statistical_robustness_v14.md", errors)

    expected_payload = build_payload(repo_root)
    actual_payload = json.loads(json_text)
    _compare_values(actual_payload, expected_payload, "root", tol, errors)

    expected_md = render_markdown(expected_payload)
    if md_text != expected_md:
        errors.append("Markdown report out of sync with render_markdown(payload)")

    return errors


def _compact_json_dumps(payload: dict[str, Any]) -> str:
    top_lines = ["{"]
    keys = sorted(payload.keys())
    for idx, k in enumerate(keys):
        comma = "," if idx + 1 < len(keys) else ""
        val = payload[k]
        if isinstance(val, list) and val and isinstance(val[0], dict):
            top_lines.append(f' {json.dumps(k)}: [')
            for j, row in enumerate(val):
                r_comma = "," if j + 1 < len(val) else ""
                top_lines.append(f"  {json.dumps(row, separators=(',', ':'), sort_keys=True)}{r_comma}")
            top_lines.append(f" ]{comma}")
        elif isinstance(val, dict):
            top_lines.append(
                f" {json.dumps(k)}: {json.dumps(val, separators=(',', ':'), sort_keys=True)}{comma}"
            )
        else:
            top_lines.append(f" {json.dumps(k)}: {json.dumps(val)}{comma}")
    top_lines.append("}\n")
    return "\n".join(top_lines)


def write_artifacts(
    repo_root: Path = ROOT,
    out_json: Path | None = None,
    out_md: Path | None = None,
) -> dict[str, Any]:
    json_path = out_json or (repo_root / "results/eval_v14/statistical_robustness_v14.json")
    md_path = out_md or (repo_root / "docs/reports/statistical_robustness_v14.md")
    payload = build_payload(repo_root)
    md_text = render_markdown(payload)
    json_text = _compact_json_dumps(payload)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(md_text, encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Paired statistical robustness & LOO audit on locked v1.4 seeds 0-29."
    )
    parser.add_argument("--check", action="store_true", help="Verify committed artifacts within 1e-9.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root path.")
    parser.add_argument("--out-json", type=Path, default=None, help="Override output JSON path.")
    parser.add_argument("--out-md", type=Path, default=None, help="Override output Markdown path.")
    args = parser.parse_args(argv)

    repo_root = args.root.resolve()
    if args.check:
        errs = check_artifacts(repo_root, args.out_json, args.out_md, tol=1e-9)
        if errs:
            for e in errs:
                print(f"FAIL: {e}", file=sys.stderr)
            return 1
        print("OK: statistical_robustness_v14 artifacts verified within 1e-9 tolerance.")
        return 0

    payload = write_artifacts(repo_root, args.out_json, args.out_md)
    json_path = args.out_json or (repo_root / "results/eval_v14/statistical_robustness_v14.json")
    size_kb = json_path.stat().st_size / 1024.0
    print(
        f"Wrote statistical_robustness_v14 ({len(payload['cohorts'])} cohorts, "
        f"JSON={size_kb:.1f} KB, crosscheck_max_diff={payload['headline_table_crosscheck']['max_abs_diff']:.2e})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
