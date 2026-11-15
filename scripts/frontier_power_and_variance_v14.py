"""Pure-CPU statistical power, luck-adjustment variance reduction, MDE curves, and n=10 Harbor subsample reconciliation for Canary v1.4.

    PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --write
    PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --check
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import numpy as np

try:
    from pydantic_core import from_json as _loads_json
except ImportError:
    _loads_json = json.loads

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (str(ROOT), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from canary.analysis.gap import mean_ci
from canary.rules import TIERS_VERSION, tier_params_for_episode
from canary.solver.belief import _fallback, behaviour_logliks, leak_loglik
from canary.solver.policy import SolverPolicy
from canary.types import Step

SCHEMA_VERSION = "v1.4-power-and-variance-1"
MAX_JSON_BYTES = 38_000
EXPECTED_COMMITTED_V14, EXPECTED_REPLICATION_V14, EXPECTED_COMBINED_V14 = 472, 305, 777
SAMPLE_SIZES: tuple[int, ...] = (6, 9, 10, 20, 30, 32, 35, 36, 60)
SAMPLE_SIZE_LABELS: dict[int, str] = {
    6: "carbon_hard_30_59_dedup_union",
    9: "harbor_rehearsal_opencode_3_valid",
    10: "harbor_rehearsal_opencode_1_2_and_v13_planned",
    20: "v12_and_initial_solver_0_19",
    30: "v14_locked_primary_0_29",
    32: "v14_pooled_0_29_plus_g1_ext",
    35: "v14_0_29_plus_fr8_rep",
    36: "v14_0_29_plus_dedup_union",
    60: "v14_full_0_59_target",
}
MDE_CURVE_COLUMNS: tuple[str, ...] = (
    "n",
    "mde_z_score",
    "mde_z_pct_solver",
    "mde_t_score",
    "mde_t_pct_solver",
    "power_t_at_obs_gap",
    "power_z_at_obs_gap",
    "power_t_at_15pct_solver",
)
RATIO_TAIL_THRESHOLDS: tuple[tuple[int, int], ...] = ((85, 100), (93, 100), (100, 100), (116, 100), (131, 100))
BOOT_RESAMPLES = 10_000
BOOT_SEED = 0
SUBSAMPLE_DRAWS = 10_000
SUBSAMPLE_SEED = 20261115
ALPHA_TWO_SIDED = 0.05
TARGET_POWER = 0.80
Z_ALPHA_TWO_SIDED = 1.959963984540054
Z_BETA_80 = 0.8416212335729143
DELTA_MDE_Z_80 = Z_ALPHA_TWO_SIDED + Z_BETA_80
H1, H2, H3 = chr(35), chr(35) * 2, chr(35) * 3
EM_DASH, EN_DASH = chr(0x2014), chr(0x2013)
_INGEST_TOOLS = frozenset({
    "list_employees", "status", "list_documents", "check_leak_feed",
    "read_access_logs", "search_messages", "plant_canary", "advance_day",
    "restrict_access", "unrestrict_access", "interview",
})

_EP_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_FILE_COUNT_CACHE: dict[tuple[str, int, int], int] = {}
_FILE_BUCKET_CACHE: dict[tuple[Any, ...], tuple[int, dict[str, list[dict[str, Any]]]]] = {}
_SCAN_CACHE: dict[tuple[Any, ...], tuple[int, dict[str, list[dict[str, Any]]]]] = {}
_BOOT_COUNTS_CACHE: dict[tuple[int, int, int], np.ndarray] = {}
_PPF_CACHE: dict[tuple[float, int], float] = {}
_T_GRID_CACHE: dict[int, tuple[float, tuple[tuple[float, float], ...]]] = {}
_DELTA_T_CACHE: dict[int, float] = {}
_HALF15_TABLES: tuple[np.ndarray, tuple[np.ndarray, ...]] | None = None
_HARBOR_RECON_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


def default_json_path(root: Path = ROOT) -> Path:
    return root / "results" / "frontier_replication" / "v1.4" / "power_and_variance_v14.json"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "reports" / "frontier_power_and_variance_v14.md"


def gap_ships_flash_hard(root: Path = ROOT) -> bool:
    gap_md = root / "docs" / "reports" / "gap.md"
    return gap_md.exists() and ("gemini-3.5-flash" in gap_md.read_text(encoding="utf-8"))


def clean_json(obj: Any, nd: int = 5) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else round(obj, nd)
    if isinstance(obj, dict):
        return {str(k): clean_json(v, nd) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_json(v, nd) for v in obj]
    return obj


def approx_equal(a: Any, b: Any, tol: float = 1e-5) -> bool:
    if isinstance(a, bool) or isinstance(b, bool) or a is None or b is None:
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return (math.isnan(a) and math.isnan(b)) or math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def norm_cdf(x: float) -> float:
    return 0.5 * math.erfc(-x * 0.7071067811865475)


def _betainc_reg(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _betainc_reg(b, a, 1.0 - x)
    lbeta = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    front = math.exp(a * math.log(x) + b * math.log(1.0 - x) - lbeta) / a
    c = 1.0
    d = 1.0 - (a + b) * x / (a + 1.0)
    d = 1.0 / (1e-30 if abs(d) < 1e-30 else d)
    f = d
    for m in range(1, 200):
        m2 = 2 * m
        num = m * (b - m) * x / ((a + m2 - 1.0) * (a + m2))
        d = 1.0 + num * d
        d = 1.0 / (1e-30 if abs(d) < 1e-30 else d)
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        f *= c * d
        num = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1.0))
        d = 1.0 + num * d
        d = 1.0 / (1e-30 if abs(d) < 1e-30 else d)
        c = 1.0 + num / c
        if abs(c) < 1e-30:
            c = 1e-30
        delta = c * d
        f *= delta
        if abs(delta - 1.0) < 1e-14:
            break
    return front * f


def student_t_cdf(t: float, df: int) -> float:
    x = df / (df + t * t)
    ib = 0.5 * _betainc_reg(0.5 * df, 0.5, x)
    return 1.0 - ib if t >= 0.0 else ib


def student_t_ppf(p: float, df: int) -> float:
    if p == 0.5:
        return 0.0
    ckey = (round(p, 12), df)
    if ckey in _PPF_CACHE:
        return _PPF_CACHE[ckey]
    sign = 1.0 if p > 0.5 else -1.0
    target = p if p > 0.5 else 1.0 - p
    if df >= 5 and abs(target - 0.975) < 1e-9:
        z = Z_ALPHA_TWO_SIDED
        g = z + (z ** 3 + z) / (4.0 * df) + (5.0 * z ** 5 + 16.0 * z ** 3 + 3.0 * z) / (96.0 * df * df)
        lo, hi = max(0.0, g - 0.05), g + 0.05
        iters = 26
    else:
        lo, hi = 0.0, 40.0
        iters = 52
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if student_t_cdf(mid, df) < target:
            lo = mid
        else:
            hi = mid
    ans = sign * 0.5 * (lo + hi)
    _PPF_CACHE[ckey] = ans
    return ans


def _t_quadrature_grid(df: int) -> tuple[float, tuple[tuple[float, float], ...]]:
    if df in _T_GRID_CACHE:
        return _T_GRID_CACHE[df]
    tcrit = student_t_ppf(1.0 - ALPHA_TWO_SIDED / 2.0, df)
    s_max = 1.0 + 10.0 / math.sqrt(df)
    steps = 50
    h = s_max / steps
    log_c = math.log(2.0) + (0.5 * df) * math.log(0.5 * df) - math.lgamma(0.5 * df)
    pts: list[tuple[float, float]] = []
    for j in range(1, steps + 1):
        s = (j - 0.5) * h
        w = math.exp(log_c + (df - 1.0) * math.log(s) - 0.5 * df * s * s) * h
        if w > 1e-16:
            pts.append((tcrit * s, w))
    res = (tcrit, tuple(pts))
    _T_GRID_CACHE[df] = res
    return res


def two_sided_t_power(delta: float, df: int) -> float:
    _, pts = _t_quadrature_grid(df)
    d = abs(delta)
    erfc = math.erfc
    inv_rt2 = 0.7071067811865475
    acc = 0.0
    for ts, w in pts:
        acc += w * 0.5 * (erfc((ts - d) * inv_rt2) + erfc((ts + d) * inv_rt2))
    return acc


def two_sided_z_power(delta: float) -> float:
    d = abs(delta)
    return (1.0 - norm_cdf(Z_ALPHA_TWO_SIDED - d)) + norm_cdf(-Z_ALPHA_TWO_SIDED - d)


def delta_mde_t_80(df: int) -> float:
    if df in _DELTA_T_CACHE:
        return _DELTA_T_CACHE[df]
    lo, hi = 2.5, 5.0
    for _ in range(42):
        mid = 0.5 * (lo + hi)
        if two_sided_t_power(mid, df) < TARGET_POWER:
            lo = mid
        else:
            hi = mid
    ans = 0.5 * (lo + hi)
    _DELTA_T_CACHE[df] = ans
    return ans


def required_n_z_80(sd_diff: float, effect_abs: float) -> int | None:
    if effect_abs <= 1e-12:
        return None
    if sd_diff <= 1e-12:
        return 2
    return max(2, int(math.ceil(((DELTA_MDE_Z_80 * sd_diff) / effect_abs) ** 2 - 1e-12)))


def required_n_t_80(sd_diff: float, effect_abs: float) -> int | None:
    nz = required_n_z_80(sd_diff, effect_abs)
    if nz is None:
        return None
    if sd_diff <= 1e-12:
        return 2
    if nz >= 400:
        return nz + 2
    if nz >= 12:
        c2 = nz + 2
        if two_sided_t_power(effect_abs * math.sqrt(c2) / sd_diff, c2 - 1) >= TARGET_POWER:
            c1 = nz + 1
            return c1 if two_sided_t_power(effect_abs * math.sqrt(c1) / sd_diff, c1 - 1) >= TARGET_POWER else c2
        c3 = nz + 3
        if two_sided_t_power(effect_abs * math.sqrt(c3) / sd_diff, c3 - 1) >= TARGET_POWER:
            return c3
    n = max(3, nz + 1)
    for cand in range(n, n + 6):
        if two_sided_t_power(effect_abs * math.sqrt(cand) / sd_diff, cand - 1) >= TARGET_POWER:
            return cand
    return n + 6


def _boot_counts(n: int, resamples: int = BOOT_RESAMPLES, seed: int = BOOT_SEED) -> np.ndarray:
    ckey = (n, resamples, seed)
    if ckey in _BOOT_COUNTS_CACHE:
        return _BOOT_COUNTS_CACHE[ckey]
    rng = random.Random(seed)
    total_draws = resamples * n
    k_bits = n.bit_length()
    gb = rng.getrandbits
    draws: list[int] = []
    append = draws.append
    if n & (n - 1) == 0:
        km = k_bits - 1
        for _ in range(total_draws):
            append(gb(km))
    else:
        for _ in range(total_draws):
            r = gb(k_bits)
            while r >= n:
                r = gb(k_bits)
            append(r)
    flat = np.asarray(draws, dtype=np.intp)
    offsets = np.repeat(np.arange(0, total_draws, n, dtype=np.intp), n)
    res = np.bincount(offsets + flat, minlength=total_draws).reshape(resamples, n).astype(np.float64)
    _BOOT_COUNTS_CACHE[ckey] = res
    return res


def fast_boot_ratio(
    f: list[float],
    s: list[float],
    denoms: np.ndarray | None = None,
    resamples: int = BOOT_RESAMPLES,
    seed: int = BOOT_SEED,
) -> tuple[float, float]:
    counts = _boot_counts(len(f), resamples=resamples, seed=seed)
    f_arr = np.asarray(f, dtype=np.float64)
    if denoms is None:
        denoms = counts @ np.asarray(s, dtype=np.float64)
    pos = denoms > 0.0
    if not np.any(pos):
        return float("nan"), float("nan")
    nums = counts @ f_arr
    vals = np.sort(nums[pos] / denoms[pos])
    m = int(vals.shape[0])
    return float(vals[int(0.025 * m)]), float(vals[int(0.975 * m) - 1])


def _fast_belief(sp: SolverPolicy) -> dict[str, float]:
    obs, P = sp.obs, sp.P
    obs.leak_timing_known = sp.v_drops_reveal_leaks()
    emps = obs.employees
    impossible: set[str] = {obs.decoy} if obs.decoy is not None else set()
    exact_fp_tier = getattr(P, "fingerprint_accuracy", 1.0) >= 1.0
    for it in obs.feed:
        doc = obs.docs.get(it.doc_id)
        if doc is None:
            return _fallback(obs)
        rec = doc.recipients
        if it.variant and doc.variants:
            vmap = doc.variants
            must_match = exact_fp_tier or len(set(vmap.values())) <= 1
            impossible.update(
                e for e in emps if e not in rec or vmap.get(e) is None or (must_match and vmap.get(e) != it.variant)
            )
        else:
            impossible.update(e for e in emps if e not in rec)
    if not (cand := [s for s in emps if s not in impossible]):
        return _fallback(obs)
    bt, ct, nt = sp.behaviour_temper, sp.choice_temper, sp.noleak_temper
    lps = {s: leak_loglik(obs, s, P, ct, nt) for s in cand}
    alive = [s for s, v in lps.items() if v > -math.inf]
    if not alive:
        return _fallback(obs)
    if len(alive) == 1:
        s0 = alive[0]
        return {s: (1.0 if s == s0 else 0.0) for s in emps}
    beh = behaviour_logliks(obs, P) if bt > 0 else {}
    logs: dict[str, float] = {s: -math.inf for s in emps}
    pe, pm = P.p_evasive_innocent, min(0.999, P.p_evasive_innocent * P.interview_lr)
    iv_pos, iv_neg = math.log(pm / pe), math.log((1 - pm) / (1 - pe))
    for s in alive:
        lp = lps[s]
        if bt > 0:
            lp += bt * beh[s] + sum(bt * (iv_pos if ev else iv_neg) for who, ev in obs.interviews if who == s)
        logs[s] = lp
    mx = max(logs.values())
    z = sum(math.exp(v - mx) for v in logs.values())
    return {s: math.exp(v - mx) / z for s, v in logs.items()}


def _scan_pool(pool_dir: Path, wanted: tuple[tuple[str, str, str, str, set[int]], ...]) -> tuple[int, dict[str, list[dict[str, Any]]]]:
    if not pool_dir.exists():
        return 0, {w[0]: [] for w in wanted}
    resolved = pool_dir.resolve()
    files = [
        (f, f.relative_to(resolved).parts[:-1])
        for f in sorted(resolved.rglob("episodes.jsonl"))
        if not any(x == "superseded" or x.startswith("v1.") or x.endswith("-smoke") for x in f.relative_to(resolved).parts[:-1])
    ]
    sig = tuple((str(f), st.st_mtime_ns, st.st_size) for f, _ in files for st in (f.stat(),))
    w_sig = tuple((w[0], w[1], w[2], w[3], len(w[4]), min(w[4]), max(w[4])) for w in wanted)
    ckey = (str(resolved), sig, w_sig)
    if ckey in _SCAN_CACHE:
        return _SCAN_CACHE[ckey]
    buckets: dict[str, list[dict[str, Any]]] = {w[0]: [] for w in wanted}
    seen: dict[str, set[int]] = {w[0]: set() for w in wanted}
    total = 0
    for f, rel_parts in files:
        rel_dir, run_id = "/".join(rel_parts), f.parent.name
        st = f.stat()
        f_sig = (str(f), st.st_mtime_ns, st.st_size)
        active = [
            (key, agent, tier, seeds, f'"{agent}"'.encode(), f'"{tier}"'.encode(), tuple(f'"seed": {s}'.encode() for s in seeds) if len(seeds) <= 8 else ())
            for key, prefix, agent, tier, seeds in wanted
            if (rel_dir == prefix or ((rel_dir.startswith(prefix + "/") or rel_dir.startswith(prefix + "-")) and not (key == "sol_hard" and "seeds30to59" in rel_dir)))
        ]
        if not active:
            if f_sig in _FILE_COUNT_CACHE:
                total += _FILE_COUNT_CACHE[f_sig]
                continue
            raw = f.read_bytes()
            if b'"valid": false' not in raw and b'"valid":false' not in raw and b"\n\n" not in raw:
                cnt = (raw.count(b"\n") + (0 if raw.endswith(b"\n") else 1)) if raw.strip() else 0
            else:
                cnt = sum(
                    1
                    for ln in raw.splitlines()
                    if ln.strip() and not ((b'"valid": false' in ln or b'"valid":false' in ln) and (_loads_json(ln).get("meta") or {}).get("valid") is False)
                )
            _FILE_COUNT_CACHE[f_sig] = cnt
            total += cnt
            continue
        fb_key = (f_sig, tuple((w[0], w[1], w[2], len(w[3]), min(w[3]), max(w[3])) for w in active))
        if fb_key in _FILE_BUCKET_CACHE:
            f_cnt, f_bks = _FILE_BUCKET_CACHE[fb_key]
            total += f_cnt
            for k, eps_k in f_bks.items():
                for ep in eps_k:
                    sd = int(ep["seed"])
                    if sd in seen[k]:
                        raise ValueError(f"duplicate seed {sd} in bucket {k}")
                    seen[k].add(sd)
                    buckets[k].append(ep)
            continue
        raw = f.read_bytes()
        f_cnt = 0
        f_bks: dict[str, list[dict[str, Any]]] = {w[0]: [] for w in active}
        for raw_line in raw.splitlines():
            if not raw_line.strip():
                continue
            if not (cand := [w for w in active if w[4] in raw_line and w[5] in raw_line and (not w[6] or any(sb in raw_line for sb in w[6]))]):
                if (b'"valid": false' in raw_line or b'"valid":false' in raw_line) and (_loads_json(raw_line).get("meta") or {}).get("valid") is False:
                    continue
                f_cnt += 1
                continue
            ep = _loads_json(raw_line)
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            f_cnt += 1
            sd = int(ep["seed"])
            for key, agent, tier, seeds, _, _, _ in cand:
                if ep.get("agent") == agent and ep.get("tier") == tier and sd in seeds:
                    if sd in seen[key]:
                        raise ValueError(f"duplicate seed {sd} in bucket {key}")
                    seen[key].add(sd)
                    ep.setdefault("meta", {})["run_id"] = run_id
                    buckets[key].append(ep)
                    f_bks[key].append(ep)
        _FILE_COUNT_CACHE[f_sig] = f_cnt
        _FILE_BUCKET_CACHE[fb_key] = (f_cnt, f_bks)
        total += f_cnt
    for rows in buckets.values():
        rows.sort(key=lambda x: int(x["seed"]))
    if len(_SCAN_CACHE) >= 8:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[ckey] = (total, buckets)
    return total, buckets


def _eval_episode(ep: dict[str, Any]) -> dict[str, Any]:
    meta, steps_raw = ep.get("meta") or {}, ep.get("steps") or []
    ckey = (str(ep["agent"]), str(ep["tier"]), int(ep["seed"]), str(meta.get("run_id") or ""), len(steps_raw), round(float(ep["score"]), 9))
    if ckey in _EP_CACHE:
        return _EP_CACHE[ckey]
    acc = ep.get("accused")
    v_raw = meta.get("V", meta.get("V_final"))
    if not acc and v_raw is not None:
        res = {
            "seed": int(ep["seed"]),
            "accused": acc,
            "correct": bool(ep.get("correct")),
            "raw": float(ep["score"]),
            "v_true": float(v_raw),
            "p_accused": None,
            "luck": 0.0,
        }
        if len(_EP_CACHE) >= 1024:
            _EP_CACHE.clear()
        _EP_CACHE[ckey] = res
        return res
    acc_idx = next((i for i, s in enumerate(steps_raw) if s.get("tool") == "accuse"), len(steps_raw))
    steps_pre = [Step(s.get("t", 0), s.get("day", 0), tl, s.get("args") or {}, s.get("result")) for s in steps_raw[:acc_idx] if (tl := s.get("tool", "")) in _INGEST_TOOLS]
    sp = SolverPolicy(tier_params_for_episode(str(ep["tier"]), steps_pre))
    for st in steps_pre:
        sp._ingest(st)
    sp.seen = acc_idx
    post = _fast_belief(sp) if (acc and sp.obs.employees) else {}
    v_known = float(sp.V)
    v_true = float(v_raw) if v_raw is not None else v_known
    p_acc = round(float(post.get(acc, 0.0)), 3) if (acc and post) else None
    res = {
        "seed": int(ep["seed"]),
        "accused": acc,
        "correct": bool(ep.get("correct")),
        "raw": float(ep["score"]),
        "v_true": v_true,
        "p_accused": p_acc,
        "luck": (p_acc * v_true - (1.0 - p_acc)) if (acc and p_acc is not None) else 0.0,
    }
    if len(_EP_CACHE) >= 1024:
        _EP_CACHE.clear()
    _EP_CACHE[ckey] = res
    return res


def _sample_var(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def _pearson_r(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 1e-18 or vy <= 1e-18:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / math.sqrt(vx * vy)


def _build_mde_rows(sd_diff: float, solver_mean: float, obs_diff: float) -> list[list[Any]]:
    obs_abs = abs(obs_diff)
    p15_abs = 0.15 * solver_mean
    rows: list[list[Any]] = []
    for n in SAMPLE_SIZES:
        df = n - 1
        se = sd_diff / math.sqrt(n)
        d_t = delta_mde_t_80(df)
        mde_z = DELTA_MDE_Z_80 * se
        mde_t = d_t * se
        delta_obs = (obs_abs / se) if se > 1e-12 else (1e9 if obs_abs > 0 else 0.0)
        delta_15 = (p15_abs / se) if se > 1e-12 else 1e9
        rows.append([
            n,
            mde_z,
            (mde_z / solver_mean) if solver_mean > 0 else None,
            mde_t,
            (mde_t / solver_mean) if solver_mean > 0 else None,
            two_sided_t_power(delta_obs, df),
            two_sided_z_power(delta_obs),
            two_sided_t_power(delta_15, df),
        ])
    return rows


def _mde_row_dict(row: list[Any]) -> dict[str, Any]:
    return dict(zip(MDE_CURVE_COLUMNS, row))


def _analyze_paired_cohort(
    cid: str,
    label: str,
    harness: str,
    agent: str,
    tier: str,
    source_note: str,
    frows: list[dict[str, Any]],
    srows: list[dict[str, Any]],
    denoms_raw: np.ndarray,
    denoms_la: np.ndarray,
) -> dict[str, Any]:
    n = len(frows)
    fr = [r["raw"] for r in frows]
    sr = [r["raw"] for r in srows]
    fl = [r["luck"] for r in frows]
    sl = [r["luck"] for r in srows]
    dr = [a - b for a, b in zip(fr, sr)]
    dl = [a - b for a, b in zip(fl, sl)]

    (raw_m, raw_ci), (la_m, la_ci) = mean_ci(fr), mean_ci(fl)
    (dr_m, dr_ci), (dl_m, dl_ci) = mean_ci(dr), mean_ci(dl)
    s_raw_m, s_la_m = sum(sr) / n, sum(sl) / n

    var_fr, var_sr = _sample_var(fr), _sample_var(sr)
    var_fl, var_sl = _sample_var(fl), _sample_var(sl)
    var_dr, var_dl = _sample_var(dr), _sample_var(dl)
    sd_dr, sd_dl = math.sqrt(var_dr), math.sqrt(var_dl)

    raw_r_lo, raw_r_hi = fast_boot_ratio(fr, sr, denoms_raw)
    la_r_lo, la_r_hi = fast_boot_ratio(fl, sl, denoms_la)
    raw_span_pp = (raw_r_hi - raw_r_lo) * 100.0
    la_span_pp = (la_r_hi - la_r_lo) * 100.0
    raw_round_lo, raw_round_hi = int(round(raw_r_lo * 100.0)), int(round(raw_r_hi * 100.0))
    la_round_lo, la_round_hi = int(round(la_r_lo * 100.0)), int(round(la_r_hi * 100.0))

    vrf_diff = var_dr / var_dl
    vrf_unpaired_f = (var_fr / var_fl) if var_fl > 1e-18 else None

    wrong_seeds = [r["seed"] for r in frows if r["accused"] and not r["correct"]]
    sol_wrong_seeds = [r["seed"] for r in srows if r["accused"] and not r["correct"]]
    abstain_seeds = [r["seed"] for r in frows if not r["accused"]]
    cond_bern_vars = [
        (r["p_accused"] * (1.0 - r["p_accused"]) * ((1.0 + r["v_true"]) ** 2)) if (r["accused"] and r["p_accused"] is not None) else 0.0
        for r in frows
    ]
    cliff_residuals = [r["raw"] - r["luck"] for r in frows]
    ss_fr = sum((x - raw_m) ** 2 for x in fr)
    ss_wrong = sum((r["raw"] - raw_m) ** 2 for r in frows if r["accused"] and not r["correct"])

    return {
        "cohort_id": cid,
        "label": label,
        "harness": harness,
        "agent": agent,
        "tier": tier,
        "source": source_note,
        "n": n,
        "accused_count": n - len(abstain_seeds),
        "abstain_seeds": abstain_seeds,
        "accuracy": sum(1 for r in frows if r["correct"]) / n,
        "wrong_cliff_count": len(wrong_seeds),
        "wrong_cliff_seeds": wrong_seeds,
        "solver_wrong_cliff_seeds": sol_wrong_seeds,
        "raw": {
            "mean": raw_m,
            "sd": math.sqrt(var_fr),
            "var": var_fr,
            "ci95_halfwidth": raw_ci,
            "solver_mean": s_raw_m,
            "solver_var": var_sr,
            "ratio_vs_solver": raw_m / s_raw_m,
            "ratio_ci95": [raw_r_lo, raw_r_hi],
            "ratio_ci_span_pp": raw_span_pp,
            "ratio_ci_rounded_pct": [raw_round_lo, raw_round_hi],
            "ratio_ci_rounded_span_pp": raw_round_hi - raw_round_lo,
            "paired_diff_mean": dr_m,
            "paired_diff_sd": sd_dr,
            "paired_diff_var": var_dr,
            "paired_diff_ci95_halfwidth": dr_ci,
            "paired_corr_with_solver": _pearson_r(fr, sr),
        },
        "luck_adjusted": {
            "mean": la_m,
            "sd": math.sqrt(var_fl),
            "var": var_fl,
            "ci95_halfwidth": la_ci,
            "solver_mean": s_la_m,
            "solver_var": var_sl,
            "ratio_vs_solver": la_m / s_la_m,
            "ratio_ci95": [la_r_lo, la_r_hi],
            "ratio_ci_span_pp": la_span_pp,
            "ratio_ci_rounded_pct": [la_round_lo, la_round_hi],
            "ratio_ci_rounded_span_pp": la_round_hi - la_round_lo,
            "paired_diff_mean": dl_m,
            "paired_diff_sd": sd_dl,
            "paired_diff_var": var_dl,
            "paired_diff_ci95_halfwidth": dl_ci,
            "paired_corr_with_solver": _pearson_r(fl, sl),
        },
        "variance_reduction": {
            "vrf_paired_diff": vrf_diff,
            "n_eff_multiplier": vrf_diff,
            "n_eff_at_30": 30.0 * vrf_diff,
            "paired_var_reduction_pct": 1.0 - (var_dl / var_dr),
            "unpaired_frontier_vrf": vrf_unpaired_f,
            "ratio_ci_span_compression": raw_span_pp / la_span_pp,
            "ratio_ci_rounded_span_delta_pp": (raw_round_hi - raw_round_lo) - (la_round_hi - la_round_lo),
            "mean_conditional_bernoulli_cliff_var": sum(cond_bern_vars) / n,
            "realized_cliff_noise_var": _sample_var(cliff_residuals),
            "wrong_cliff_share_of_raw_ss": (ss_wrong / ss_fr) if ss_fr > 1e-18 else 0.0,
        },
        "sample_size_requirements_80pct_power": {
            "raw_n_req_t_obs_gap": required_n_t_80(sd_dr, abs(dr_m)),
            "raw_n_req_z_obs_gap": required_n_z_80(sd_dr, abs(dr_m)),
            "la_n_req_t_obs_gap": required_n_t_80(sd_dl, abs(dl_m)),
            "la_n_req_z_obs_gap": required_n_z_80(sd_dl, abs(dl_m)),
            "raw_n_req_t_15pct_solver": required_n_t_80(sd_dr, 0.15 * s_raw_m),
            "la_n_req_t_15pct_solver": required_n_t_80(sd_dl, 0.15 * s_la_m),
            "raw_n_req_t_25pct_solver": required_n_t_80(sd_dr, 0.25 * s_raw_m),
            "la_n_req_t_25pct_solver": required_n_t_80(sd_dl, 0.25 * s_la_m),
        },
        "mde_curve": {
            "raw": _build_mde_rows(sd_dr, s_raw_m, dr_m),
            "post_expected": _build_mde_rows(sd_dl, s_la_m, dl_m),
        },
    }


def _half15_tables() -> tuple[np.ndarray, tuple[np.ndarray, ...]]:
    global _HALF15_TABLES
    if _HALF15_TABLES is not None:
        return _HALF15_TABLES
    u = np.arange(1 << 15, dtype=np.uint32)[:, None]
    bits = ((u >> np.arange(15, dtype=np.uint32)) & 1).astype(np.int64)
    pop = bits.sum(axis=1)
    by_k = tuple(np.flatnonzero(pop == k) for k in range(11))
    _HALF15_TABLES = (bits, by_k)
    return _HALF15_TABLES


def _exact_wor_ratio_tails_pair(
    f_int: list[int],
    s_int: list[int],
    thresholds: tuple[tuple[int, int], ...] = RATIO_TAIL_THRESHOLDS,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    bits, by_k_idx = _half15_tables()
    tot10, tot9 = math.comb(30, 10), math.comb(30, 9)
    f_arr = np.asarray(f_int, dtype=np.int64)
    s_arr = np.asarray(s_int, dtype=np.int64)
    p_arr = np.asarray([p for p, _ in thresholds], dtype=np.int64)
    q_arr = np.asarray([q for _, q in thresholds], dtype=np.int64)
    vals_mat = f_arr[:, None] * q_arr[None, :] - s_arr[:, None] * p_arr[None, :]
    sum_l = bits @ vals_mat[:15]
    sum_r = bits @ vals_mat[15:]
    out10: dict[str, dict[str, Any]] = {}
    out9: dict[str, dict[str, Any]] = {}
    for t_idx, (p_num, q_den) in enumerate(thresholds):
        sl_t = sum_l[:, t_idx]
        sr_t = sum_r[:, t_idx]
        sr_by_k = [np.sort(sr_t[idx_k]) for idx_k in by_k_idx]
        sl_by_k = [sl_t[idx_k] for idx_k in by_k_idx]
        hits10 = sum(
            int(sr_by_k[10 - kl].shape[0] * sl_by_k[kl].shape[0] - int(np.searchsorted(sr_by_k[10 - kl], -sl_by_k[kl], side="left").sum()))
            for kl in range(11)
        )
        hits9 = sum(
            int(sr_by_k[9 - kl].shape[0] * sl_by_k[kl].shape[0] - int(np.searchsorted(sr_by_k[9 - kl], -sl_by_k[kl], side="left").sum()))
            for kl in range(10)
        )
        thr = p_num / q_den
        key = f"ge_{thr:.2f}"
        out10[key] = {"threshold": thr, "favorable_subsets": hits10, "total_subsets": tot10, "exact_prob": hits10 / tot10}
        out9[key] = {"threshold": thr, "favorable_subsets": hits9, "total_subsets": tot9, "exact_prob": hits9 / tot9}
    return out10, out9


def _quantiles(sorted_xs: np.ndarray) -> dict[str, float]:
    m = int(sorted_xs.shape[0])
    return {
        "p025": float(sorted_xs[int(0.025 * m)]),
        "p05": float(sorted_xs[int(0.05 * m)]),
        "p25": float(sorted_xs[int(0.25 * m)]),
        "p50": float(sorted_xs[int(0.50 * m)]),
        "p75": float(sorted_xs[int(0.75 * m)]),
        "p95": float(sorted_xs[int(0.95 * m) - 1]),
        "p975": float(sorted_xs[int(0.975 * m) - 1]),
    }


def _subsample_mc(
    frows: list[dict[str, Any]],
    srows: list[dict[str, Any]],
    n_sub: int,
    with_replacement: bool,
    draws: int = SUBSAMPLE_DRAWS,
    seed: int = SUBSAMPLE_SEED,
) -> dict[str, Any]:
    rng = np.random.Generator(np.random.PCG64(seed + (1000 if with_replacement else 0) + n_sub))
    n_pop = len(frows)
    fr_a = np.asarray([r["raw"] for r in frows], dtype=np.float64)
    sr_a = np.asarray([s["raw"] for s in srows], dtype=np.float64)
    fl_a = np.asarray([r["luck"] for r in frows], dtype=np.float64)
    sl_a = np.asarray([s["luck"] for s in srows], dtype=np.float64)
    wf_a = np.asarray([1 if (r["accused"] and not r["correct"]) else 0 for r in frows], dtype=np.int32)
    ws_a = np.asarray([1 if (s["accused"] and not s["correct"]) else 0 for s in srows], dtype=np.int32)

    if with_replacement:
        idx = rng.integers(0, n_pop, size=(draws, n_sub))
    else:
        idx = np.argpartition(rng.random((draws, n_pop)), n_sub, axis=1)[:, :n_sub]

    f_s = fr_a[idx].sum(axis=1)
    s_s = sr_a[idx].sum(axis=1)
    fl_s = fl_a[idx].sum(axis=1)
    sl_s = sl_a[idx].sum(axis=1)
    wrongs = wf_a[idx].sum(axis=1)
    ws_cnt = ws_a[idx].sum(axis=1)

    pos_r = s_s > 0.0
    pos_l = sl_s > 0.0
    raw_ratios = f_s[pos_r] / s_s[pos_r]
    la_ratios = fl_s[pos_l] / sl_s[pos_l]
    wrongs_pos = wrongs[pos_r]
    ws_pos = ws_cnt[pos_r]

    sr_sorted = np.sort(raw_ratios)
    sl_sorted = np.sort(la_ratios)
    nr = int(raw_ratios.shape[0])
    nl = int(la_ratios.shape[0])

    by_w_mean: dict[str, float | None] = {}
    for k in (0, 1, 2):
        mask_k = wrongs_pos == k
        by_w_mean[str(k)] = float(raw_ratios[mask_k].mean()) if np.any(mask_k) else None
    mask_3p = wrongs_pos >= 3
    by_w_mean["3_plus"] = float(raw_ratios[mask_3p].mean()) if np.any(mask_3p) else None

    sol_mask = ws_pos > 0
    no_sol_mask = ~sol_mask

    return {
        "n_sub": n_sub,
        "with_replacement": with_replacement,
        "draws": draws,
        "valid_positive_solver_draws": nr,
        "empirical_p_zero_wrong": float(np.sum(wrongs == 0)) / draws,
        "empirical_p_le_one_wrong": float(np.sum(wrongs <= 1)) / draws,
        "raw_ratio_mean": float(raw_ratios.mean()),
        "raw_ratio_sd": float(raw_ratios.std(ddof=1)) if nr > 1 else 0.0,
        "raw_ratio_quantiles": _quantiles(sr_sorted),
        "la_ratio_mean": float(la_ratios.mean()),
        "la_ratio_sd": float(la_ratios.std(ddof=1)) if nl > 1 else 0.0,
        "la_ratio_quantiles": _quantiles(sl_sorted),
        "tail_probs_raw_ratio": {
            f"ge_{p / q:.2f}": float(np.sum(raw_ratios >= (p / q))) / nr
            for p, q in RATIO_TAIL_THRESHOLDS
        },
        "tail_probs_la_ratio": {
            f"ge_{p / q:.2f}": float(np.sum(la_ratios >= (p / q))) / nl
            for p, q in RATIO_TAIL_THRESHOLDS
        },
        "mean_raw_ratio_by_wrong_count": by_w_mean,
        "mean_raw_ratio_when_solver_cliff_included": float(raw_ratios[sol_mask].mean()) if np.any(sol_mask) else None,
        "mean_raw_ratio_when_no_solver_cliff": float(raw_ratios[no_sol_mask].mean()) if np.any(no_sol_mask) else None,
    }


def _build_harbor_subsample_reconciliation(c_hard_rows: list[dict[str, Any]], s_hard_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rkey = (
        tuple((r["seed"], r["raw"], r["luck"], r["correct"]) for r in c_hard_rows),
        tuple((s["seed"], s["raw"], s["luck"], s["correct"]) for s in s_hard_rows),
    )
    if rkey in _HARBOR_RECON_CACHE:
        return _HARBOR_RECON_CACHE[rkey]
    n_pop = len(c_hard_rows)
    wrong_seeds = [r["seed"] for r in c_hard_rows if r["accused"] and not r["correct"]]
    k_wrong = len(wrong_seeds)
    k_ok = n_pop - k_wrong
    non_wrong_f = [r["raw"] for r in c_hard_rows if not (r["accused"] and not r["correct"])]
    non_wrong_s = [s["raw"] for r, s in zip(c_hard_rows, s_hard_rows) if not (r["accused"] and not r["correct"])]

    f_int = [int(round(r["raw"] * 100.0)) for r in c_hard_rows]
    s_int = [int(round(s["raw"] * 100.0)) for s in s_hard_rows]
    s_sorted = sorted(s_int)
    tails10, tails9 = _exact_wor_ratio_tails_pair(f_int, s_int)
    tails_by_n = {10: tails10, 9: tails9}

    exact_wrong_dist: dict[str, Any] = {}
    for n_sub in (10, 9):
        tot_c = math.comb(n_pop, n_sub)
        hyp_pmf = {
            str(w): (math.comb(k_wrong, w) * math.comb(k_ok, n_sub - w)) / tot_c
            for w in range(min(k_wrong, n_sub) + 1)
        }
        p_w = k_wrong / n_pop
        bin_pmf = {
            str(w): math.comb(n_sub, w) * (p_w ** w) * ((1.0 - p_w) ** (n_sub - w))
            for w in range(5)
        }
        exact_wrong_dist[f"n_{n_sub}"] = {
            "n_sub": n_sub,
            "total_combinations": tot_c,
            "min_possible_solver_score_sum": sum(s_sorted[:n_sub]) / 100.0,
            "all_subsets_positive_solver_sum": sum(s_sorted[:n_sub]) > 0,
            "hypergeometric_pmf": hyp_pmf,
            "p_zero_wrong_hypergeom": hyp_pmf["0"],
            "p_le_one_wrong_hypergeom": hyp_pmf["0"] + hyp_pmf["1"],
            "binomial_pmf_0_to_4": bin_pmf,
            "p_zero_wrong_binomial": bin_pmf["0"],
            "p_le_one_wrong_binomial": bin_pmf["0"] + bin_pmf["1"],
            "exact_wor_ratio_tails": tails_by_n[n_sub],
        }

    mc_n10_wor = _subsample_mc(c_hard_rows, s_hard_rows, 10, False)
    mc_n10_wr = _subsample_mc(c_hard_rows, s_hard_rows, 10, True)
    sol_cliff_9_plus_1_denom = (9.0 * (sum(non_wrong_s) / len(non_wrong_s)) - 1.0) / 10.0
    analytic_ratio_w0_with_1_oracle_cliff = (sum(non_wrong_f) / len(non_wrong_f)) / sol_cliff_9_plus_1_denom

    ex10 = exact_wrong_dist["n_10"]
    res = {
        "population_cohort": "opencode_gemini_4_carbon_hard",
        "population_n": n_pop,
        "population_raw_ratio_vs_solver": (sum(r["raw"] for r in c_hard_rows) / n_pop) / (sum(s["raw"] for s in s_hard_rows) / n_pop),
        "population_la_ratio_vs_solver": (sum(r["luck"] for r in c_hard_rows) / n_pop) / (sum(s["luck"] for s in s_hard_rows) / n_pop),
        "population_wrong_count": k_wrong,
        "population_wrong_seeds": wrong_seeds,
        "non_wrong_26_seeds_mean_raw": sum(non_wrong_f) / len(non_wrong_f),
        "non_wrong_26_seeds_solver_mean_raw": sum(non_wrong_s) / len(non_wrong_s),
        "non_wrong_26_seeds_ratio_vs_solver": sum(non_wrong_f) / sum(non_wrong_s),
        "analytic_ratio_if_zero_wrong_vs_one_oracle_cliff": analytic_ratio_w0_with_1_oracle_cliff,
        "single_wrong_cliff_impact_on_n10_mean": -(1.0 + sum(r["v_true"] for r in c_hard_rows if r["accused"] and not r["correct"]) / k_wrong) / 10.0,
        "headline_n10_exact_metrics": {
            "p_zero_wrong_wor_hypergeom": ex10["p_zero_wrong_hypergeom"],
            "p_le_one_wrong_wor_hypergeom": ex10["p_le_one_wrong_hypergeom"],
            "p_zero_wrong_wr_binomial": ex10["p_zero_wrong_binomial"],
            "p_le_one_wrong_wr_binomial": ex10["p_le_one_wrong_binomial"],
            "p_ratio_ge_0_93_wor_exact": ex10["exact_wor_ratio_tails"]["ge_0.93"]["exact_prob"],
            "p_ratio_ge_1_00_wor_exact": ex10["exact_wor_ratio_tails"]["ge_1.00"]["exact_prob"],
            "p_ratio_ge_1_16_wor_exact": ex10["exact_wor_ratio_tails"]["ge_1.16"]["exact_prob"],
            "p_ratio_ge_1_31_wor_exact": ex10["exact_wor_ratio_tails"]["ge_1.31"]["exact_prob"],
            "p_ratio_ge_0_93_wr_mc10k": mc_n10_wr["tail_probs_raw_ratio"]["ge_0.93"],
            "p_ratio_ge_1_00_wr_mc10k": mc_n10_wr["tail_probs_raw_ratio"]["ge_1.00"],
        },
        "exact_combinatorial": exact_wrong_dist,
        "monte_carlo_10k": {
            "n10_without_replacement": mc_n10_wor,
            "n10_with_replacement": mc_n10_wr,
        },
        "harbor_rehearsal_reference": {
            "table_path": "results/harbor/rehearsal/TABLE.md",
            "final_commit": "d0ead011",
            "tag": "afterquery-final (1bc3e281)",
            "judge_tasks": "hard-900000..hard-900009 (10 fixed worlds)",
            "oracle_10_task_mean": 0.506,
            "oracle_9_task_mean_opencode3": 0.478889,
            "oracle_cliff_task": "hard-900007 (-1.00 on d15)",
            "runs": [
                {"run": "opencode-1", "n_valid": 10, "correct": 9, "accused": 10, "mean": 0.472, "oracle_mean": 0.506, "ratio_pct": 93, "ci95_pct": [20, 371]},
                {"run": "opencode-2", "n_valid": 10, "correct": 10, "accused": 10, "mean": 0.585, "oracle_mean": 0.506, "ratio_pct": 116, "ci95_pct": [78, 363]},
                {"run": "opencode-3", "n_valid": 9, "correct": 9, "accused": 9, "mean": 0.626, "oracle_mean": 0.478889, "ratio_pct": 131, "ci95_pct": [86, 590]},
            ],
            "pooled_valid_trials": 29,
            "pooled_correct_trials": 28,
            "pooled_wrong_trials": 1,
            "shell_used_trials": "20/28",
            "disclosed_differences_vs_mcp_primary": [
                "Harbor container provides bash shell (used in 20/28 trials) alongside MCP tools.",
                "Tag 1bc3e281 includes explicit MCP tool error detail and reworded careful-mole prompt sentence.",
                "All 3 runs share the same 10 fixed judge worlds (including oracle -1.00 cliff on hard-900007).",
            ],
        },
    }
    _HARBOR_RECON_CACHE[rkey] = res
    return res


def _load_g2_and_hard_rows(root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    g2_path = root / "results" / "frontier_replication" / "v1.4" / "g2_families_audit.json"
    if not g2_path.exists():
        raise FileNotFoundError(f"missing G2 audit JSON: {g2_path}")
    g2 = _loads_json(g2_path.read_bytes())
    cols = {name: idx for idx, name in enumerate(g2["seed_row_columns"])}
    seed_rows = g2["seed_rows"]
    if len(seed_rows) != 30:
        raise ValueError(f"expected 30 G2 seed rows, got {len(seed_rows)}")
    sol_hard_rows: list[dict[str, Any]] = []
    c_hard_rows: list[dict[str, Any]] = []
    argon_rows: list[dict[str, Any]] = []
    hydrogen_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(seed_rows):
        sd = int(row[cols["seed"]])
        if sd != idx:
            raise ValueError(f"unexpected G2 seed order {sd} != {idx}")
        sol_hard_rows.append({
            "seed": sd,
            "accused": row[cols["solver_accused"]],
            "correct": bool(row[cols["solver_correct"]]),
            "raw": float(row[cols["solver_score"]]),
            "v_true": float(row[cols["solver_score"]]) if row[cols["solver_correct"]] else 0.0,
            "p_accused": None,
            "luck": float(row[cols["solver_pe"]]),
        })
        c_hard_rows.append({
            "seed": sd,
            "accused": row[cols["carbon_accused"]],
            "correct": bool(row[cols["carbon_correct"]]),
            "raw": float(row[cols["carbon_score"]]),
            "v_true": float(row[cols["carbon_V"]]),
            "p_accused": float(row[cols["carbon_p_acc"]]) if row[cols["carbon_p_acc"]] is not None else None,
            "luck": float(row[cols["carbon_pe"]]),
        })
        argon_rows.append({
            "seed": sd,
            "accused": row[cols["argon_accused"]],
            "correct": bool(row[cols["argon_correct"]]),
            "raw": float(row[cols["argon_score"]]),
            "v_true": float(row[cols["argon_V"]]),
            "p_accused": float(row[cols["argon_p_acc"]]) if row[cols["argon_p_acc"]] is not None else None,
            "luck": float(row[cols["argon_pe"]]),
        })
        hydrogen_rows.append({
            "seed": sd,
            "accused": row[cols["hydrogen_accused"]],
            "correct": bool(row[cols["hydrogen_correct"]]),
            "raw": float(row[cols["hydrogen_score"]]),
            "v_true": float(row[cols["hydrogen_V"]]),
            "p_accused": float(row[cols["hydrogen_p_acc"]]) if row[cols["hydrogen_p_acc"]] is not None else None,
            "luck": float(row[cols["hydrogen_pe"]]),
        })
    return sol_hard_rows, c_hard_rows, argon_rows, hydrogen_rows


def _load_gpt55_rows_if_present(root: Path) -> list[dict[str, Any]] | None:
    p = root / "results" / "frontier_replication" / "v1.4" / "gpt55_vs_carbon_forensics.json"
    if not p.exists():
        return None
    obj = _loads_json(p.read_bytes())
    sm = obj.get("seed_matrix")
    if not isinstance(sm, list) or len(sm) != 30:
        return None
    rows: list[dict[str, Any]] = []
    for idx, r in enumerate(sm):
        sd = int(r["seed"])
        if sd != idx:
            return None
        g = r["gpt55"]
        rows.append({
            "seed": sd,
            "accused": g["accused"],
            "correct": bool(g["correct"]),
            "raw": float(g["score"]),
            "v_true": float(g["v_at_end"]),
            "p_accused": float(g["p_accused"]) if g["p_accused"] is not None else None,
            "luck": float(g["post_expected"]),
        })
    return rows


def compute_audit(root: Path = ROOT, enforce_expected_counts: bool = True) -> dict[str, Any]:
    s0_29, s30_59, ships_flash = set(range(30)), set(range(30, 60)), gap_ships_flash_hard(root)
    gpt55_cached = _load_gpt55_rows_if_present(root)
    comm_list: list[tuple[str, str, str, str, set[int]]] = [
        ("sol_med", "reference/solver-medium", "solver", "medium", s0_29),
        ("oc_c_med", "opencode-gemini-4-carbon/medium", "opencode:google/gemini-4-carbon", "medium", s0_29),
        ("ip_c_med", "inproc-gemini-4-carbon/medium", "gemini:gemini-4-carbon", "medium", s0_29),
        ("ip_c_hard", "inproc-gemini-4-carbon/hard", "gemini:gemini-4-carbon", "hard", s0_29),
        ("g1_ext", "opencode-gemini-4-carbon-ext/hard", "opencode:google/gemini-4-carbon", "hard", s30_59),
    ]
    if gpt55_cached is None:
        comm_list.append(("oc_gpt", "opencode-gpt-5.5/hard", "opencode:openai/gpt-5.5", "hard", s0_29))
    if ships_flash:
        comm_list.append(("fl_hard", "opencode-gemini-3.5-flash/hard", "opencode:google/gemini-3.5-flash", "hard", s0_29))
    rep_wanted: tuple[tuple[str, str, str, str, set[int]], ...] = (
        ("fl_med", "opencode-gemini-3.5-flash", "opencode:google/gemini-3.5-flash", "medium", s0_29),
        ("fr8_ext", "opencode-gemini-4-carbon", "opencode:google/gemini-4-carbon", "hard", s30_59),
    )
    comm_n, cb = _scan_pool(root / "data/runs/committed/v1.4", tuple(comm_list))
    rep_n, rb = _scan_pool(root / "results/frontier_replication/v1.4", rep_wanted)
    if enforce_expected_counts and (comm_n != EXPECTED_COMMITTED_V14 or rep_n != EXPECTED_REPLICATION_V14):
        raise ValueError(f"pool count mismatch: committed={comm_n}, replication={rep_n}")

    sol_med_rows = [_eval_episode(e) for e in cb["sol_med"]]
    sol_hard_rows, c_hard_rows, argon_rows, hydrogen_rows = _load_g2_and_hard_rows(root)
    gpt55_rows = gpt55_cached if gpt55_cached is not None else [_eval_episode(e) for e in cb["oc_gpt"]]

    counts_30 = _boot_counts(30)
    den_hard_raw = counts_30 @ np.asarray([r["raw"] for r in sol_hard_rows], dtype=np.float64)
    den_hard_la = counts_30 @ np.asarray([r["luck"] for r in sol_hard_rows], dtype=np.float64)
    den_med_raw = counts_30 @ np.asarray([r["raw"] for r in sol_med_rows], dtype=np.float64)
    den_med_la = counts_30 @ np.asarray([r["luck"] for r in sol_med_rows], dtype=np.float64)

    cohort_specs: list[tuple[str, str, str, str, str, str, list[dict[str, Any]], list[dict[str, Any]], np.ndarray, np.ndarray]] = [
        ("opencode_gemini_4_carbon_hard", "OpenCode gemini-4-carbon hard (0-29)", "opencode", "opencode:google/gemini-4-carbon", "hard", "committed_v14_primary_lock_671ed96", c_hard_rows, sol_hard_rows, den_hard_raw, den_hard_la),
        ("opencode_gemini_4_carbon_medium", "OpenCode gemini-4-carbon medium (0-29)", "opencode", "opencode:google/gemini-4-carbon", "medium", "committed_v14_primary_lock_671ed96", [_eval_episode(e) for e in cb["oc_c_med"]], sol_med_rows, den_med_raw, den_med_la),
        ("inproc_gemini_4_carbon_hard", "in-process gemini-4-carbon hard (0-29)", "inproc", "gemini:gemini-4-carbon", "hard", "committed_v14_primary_lock_671ed96", [_eval_episode(e) for e in cb["ip_c_hard"]], sol_hard_rows, den_hard_raw, den_hard_la),
        ("inproc_gemini_4_carbon_medium", "in-process gemini-4-carbon medium (0-29)", "inproc", "gemini:gemini-4-carbon", "medium", "committed_v14_primary_lock_671ed96", [_eval_episode(e) for e in cb["ip_c_med"]], sol_med_rows, den_med_raw, den_med_la),
        ("opencode_gpt_5_5_hard", "OpenCode gpt-5.5 hard (0-29)", "opencode", "opencode:openai/gpt-5.5", "hard", "committed_v14_prereg_cf394894_ca0a0dc0", gpt55_rows, sol_hard_rows, den_hard_raw, den_hard_la),
        ("opencode_gemini_3_5_flash_medium", "FR8 OpenCode gemini-3.5-flash medium (0-29)", "opencode", "opencode:google/gemini-3.5-flash", "medium", "fr8_replication_v14", [_eval_episode(e) for e in rb["fl_med"]], sol_med_rows, den_med_raw, den_med_la),
        ("g2_opencode_gemini_4_argon_hard", "G2 OpenCode gemini-4-argon hard (0-29)", "opencode", "opencode:google/gemini-4-argon", "hard", "g2_families_audit_prereg_f9fb7a4a_8911130e", argon_rows, sol_hard_rows, den_hard_raw, den_hard_la),
        ("g2_opencode_gemini_4_hydrogen_hard", "G2 OpenCode gemini-4-hydrogen hard (0-29)", "opencode", "opencode:google/gemini-4-hydrogen", "hard", "g2_families_audit_prereg_f9fb7a4a_8911130e", hydrogen_rows, sol_hard_rows, den_hard_raw, den_hard_la),
    ]
    if ships_flash:
        cohort_specs.append(("opencode_gemini_3_5_flash_hard", "OpenCode gemini-3.5-flash hard (0-29)", "opencode", "opencode:google/gemini-3.5-flash", "hard", "committed_held_until_gap_md", [_eval_episode(e) for e in cb["fl_hard"]], sol_hard_rows, den_hard_raw, den_hard_la))

    cohorts = [_analyze_paired_cohort(*sp) for sp in cohort_specs]
    by_id = {c["cohort_id"]: c for c in cohorts}
    ch = by_id["opencode_gemini_4_carbon_hard"]
    gp = by_id["opencode_gpt_5_5_hard"]

    mde_constants = [
        {
            "n": n,
            "df": n - 1,
            "meaning": SAMPLE_SIZE_LABELS[n],
            "t_crit_two_sided_0975": student_t_ppf(1.0 - ALPHA_TWO_SIDED / 2.0, n - 1),
            "delta_mde_t_80": delta_mde_t_80(n - 1),
            "delta_mde_z_80": DELTA_MDE_Z_80,
        }
        for n in SAMPLE_SIZES
    ]

    harbor_reconcil = _build_harbor_subsample_reconciliation(c_hard_rows, sol_hard_rows)
    hard_cohorts = [c for c in cohorts if c["tier"] == "hard"]
    g1_seeds = sorted(int(e["seed"]) for e in cb["g1_ext"])
    fr8_seeds = sorted(int(e["seed"]) for e in rb["fr8_ext"])
    union_seeds = sorted(set(g1_seeds) | set(fr8_seeds))

    return clean_json({
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "upstream_justsilas_sync_commit": "5f9b3297",
        "zero_live_api_calls": True,
        "zero_subprocesses": True,
        "zero_git_dependency": True,
        "flash_hard_shipped_in_gap_md": ships_flash,
        "mde_curve_columns": list(MDE_CURVE_COLUMNS),
        "parameters": {
            "alpha_two_sided": ALPHA_TWO_SIDED,
            "target_power": TARGET_POWER,
            "sample_sizes": list(SAMPLE_SIZES),
            "boot_resamples": BOOT_RESAMPLES,
            "boot_seed": BOOT_SEED,
            "subsample_draws": SUBSAMPLE_DRAWS,
            "subsample_seed": SUBSAMPLE_SEED,
        },
        "provenance": {
            "upstream_head_commit": "5f9b3297",
            "committed_v14_episodes": comm_n,
            "replication_v14_episodes": rep_n,
            "combined_v14_episodes": comm_n + rep_n,
            "replay_mismatches": 0,
            "valid_jsonl_timeout_error_episodes": 0,
            "g2_hard_0_29_episodes": 60,
            "primary_0_29_lock_classification": "post_hoc_lock",
            "primary_0_29_lock_commit": "671ed96",
            "primary_0_29_episodes_commit": "8fd4dec",
            "primary_0_29_lock_delay_s": 28,
            "gpt_5_5_prereg_commit": "cf394894",
            "gpt_5_5_results_commit": "ca0a0dc0",
            "gpt_5_5_clean_rc0_non_accuse_seeds": gp["abstain_seeds"],
            "g2_prereg_commit": "f9fb7a4a",
            "g2_landing_commit": "8911130e",
            "g1_seeds": g1_seeds,
            "fr8_rep_seeds": fr8_seeds,
            "carbon_hard_30_59_dedup_union_seeds": union_seeds,
            "harbor_rehearsal_final_commit": "d0ead011",
            "harbor_rehearsal_ratios_pct": [93, 116, 131],
            "harbor_rehearsal_valid_trials": [10, 10, 9],
        },
        "mde_critical_constants": mde_constants,
        "summary": {
            "paired_cohort_count": len(cohorts),
            "primary_carbon_hard_vrf_paired_diff": ch["variance_reduction"]["vrf_paired_diff"],
            "primary_carbon_hard_n_eff_at_30": ch["variance_reduction"]["n_eff_at_30"],
            "primary_carbon_hard_raw_ci_rounded_pct": ch["raw"]["ratio_ci_rounded_pct"],
            "primary_carbon_hard_raw_ci_rounded_span_pp": ch["raw"]["ratio_ci_rounded_span_pp"],
            "primary_carbon_hard_la_ci_rounded_pct": ch["luck_adjusted"]["ratio_ci_rounded_pct"],
            "primary_carbon_hard_la_ci_rounded_span_pp": ch["luck_adjusted"]["ratio_ci_rounded_span_pp"],
            "hard_cohorts_min_vrf": min(c["variance_reduction"]["vrf_paired_diff"] for c in hard_cohorts),
            "hard_cohorts_max_vrf": max(c["variance_reduction"]["vrf_paired_diff"] for c in hard_cohorts),
            "vrf_gt_one_cohort_count": sum(1 for c in cohorts if c["variance_reduction"]["vrf_paired_diff"] > 1.0),
            "n10_p_zero_wrong_hypergeom": harbor_reconcil["headline_n10_exact_metrics"]["p_zero_wrong_wor_hypergeom"],
            "n10_p_le_one_wrong_hypergeom": harbor_reconcil["headline_n10_exact_metrics"]["p_le_one_wrong_wor_hypergeom"],
            "n10_p_ratio_ge_0_93_wor_exact": harbor_reconcil["headline_n10_exact_metrics"]["p_ratio_ge_0_93_wor_exact"],
            "n10_p_ratio_ge_1_00_wor_exact": harbor_reconcil["headline_n10_exact_metrics"]["p_ratio_ge_1_00_wor_exact"],
        },
        "cohorts": cohorts,
        "harbor_n10_subsample_reconciliation": harbor_reconcil,
    })


def serialize_json(data: dict[str, Any]) -> str:
    items = [
        f" {json.dumps(k)}: {json.dumps(data[k], sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(',', ':'))}"
        for k in sorted(data)
    ]
    blob = "{\n" + ",\n".join(items) + "\n}\n"
    if (size := len(blob.encode("utf-8"))) > MAX_JSON_BYTES:
        raise ValueError(f"JSON size {size} exceeds {MAX_JSON_BYTES} bytes")
    return blob


def _pct(x: float | None, nd: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{nd}f}%"


def render_markdown(data: dict[str, Any]) -> str:
    prov, cohorts, hr = data["provenance"], data["cohorts"], data["harbor_n10_subsample_reconciliation"]
    by_id = {c["cohort_id"]: c for c in cohorts}
    ch = by_id["opencode_gemini_4_carbon_hard"]
    cm = by_id["opencode_gemini_4_carbon_medium"]
    gp = by_id["opencode_gpt_5_5_hard"]
    hm = hr["headline_n10_exact_metrics"]
    mc10_wor = hr["monte_carlo_10k"]["n10_without_replacement"]
    mc10_wr = hr["monte_carlo_10k"]["n10_with_replacement"]
    ex9 = hr["exact_combinatorial"]["n_9"]

    ch_mde_raw = {r[0]: _mde_row_dict(r) for r in ch["mde_curve"]["raw"]}
    ch_mde_la = {r[0]: _mde_row_dict(r) for r in ch["mde_curve"]["post_expected"]}

    lines = [
        f"{H1} Canary v1.4 Statistical Power, Luck-Adjustment Variance Reduction, and Harbor n=10 Subsample Reconciliation",
        "",
        f"Synced to `justSilas@{prov['upstream_head_commit']}` across the replay-verified `{prov['combined_v14_episodes']}`-episode v1.4 corpus (`{prov['committed_v14_episodes']}` committed + `{prov['replication_v14_episodes']}` FR8 replication; `{prov['replay_mismatches']}` mismatches, `{prov['valid_jsonl_timeout_error_episodes']}` timeout/error episodes in valid JSONL) plus `{prov['g2_hard_0_29_episodes']}` replay-verified G2 hard `0-29` episodes (`gemini-4-argon` `103%/60%`, `gemini-4-hydrogen` `115%/97%` from `results/frontier_replication/v1.4/g2_families_audit.json`, pre-registered `{prov['g2_prereg_commit']}`, landed `{prov['g2_landing_commit']}`). Primary `gemini-4-carbon` `0-29` carries post-hoc lock `{prov['primary_0_29_lock_commit']}` (`{prov['primary_0_29_lock_delay_s']}s` after `{prov['primary_0_29_episodes_commit']}`); pre-registered OpenCode `gpt-5.5` (`{prov['gpt_5_5_prereg_commit']}` -> `{prov['gpt_5_5_results_commit']}`, `101%/84%`) has clean `rc=0` non-accuse seeds `{prov['gpt_5_5_clean_rc0_non_accuse_seeds']}`. Pure CPU, zero live API calls, zero subprocesses, zero `.git` runtime calls.",
        "",
        f"{H2} Headline Findings",
        "",
        f"1. **Luck-adjustment (`post_expected`) yields a `{ch['variance_reduction']['vrf_paired_diff']:.2f}x` paired variance reduction (`N_eff = {ch['variance_reduction']['n_eff_at_30']:.1f}` raw episodes at `n=30`) on primary OpenCode `gemini-4-carbon` hard (`0-29`):** Four `-1.0` cliff realizations (`seeds {ch['wrong_cliff_seeds']}`) contribute `{_pct(ch['variance_reduction']['wrong_cliff_share_of_raw_ss'])}` of Carbon hard's raw score sum-of-squares, inflating paired diff SD from `{ch['luck_adjusted']['paired_diff_sd']:.3f}` to `{ch['raw']['paired_diff_sd']:.3f}` and widening the paired bootstrap 95% ratio CI from `[{ch['luck_adjusted']['ratio_ci_rounded_pct'][0]}%, {ch['luck_adjusted']['ratio_ci_rounded_pct'][1]}%]` (`{ch['luck_adjusted']['ratio_ci_rounded_span_pp']} pp` rounded / `{ch['luck_adjusted']['ratio_ci_span_pp']:.1f} pp` exact) to `[{ch['raw']['ratio_ci_rounded_pct'][0]}%, {ch['raw']['ratio_ci_rounded_pct'][1]}%]` (`{ch['raw']['ratio_ci_rounded_span_pp']} pp` rounded / `{ch['raw']['ratio_ci_span_pp']:.1f} pp` exact; `{ch['variance_reduction']['ratio_ci_span_compression']:.2f}x` CI compression). Across all `{len([c for c in cohorts if c['tier'] == 'hard'])}` hard `0-29` cohorts, `Var(raw_diff) / Var(la_diff)` exceeds `1.0` (`{data['summary']['hard_cohorts_min_vrf']:.2f}x` to `{data['summary']['hard_cohorts_max_vrf']:.2f}x`), including zero-wrong `gpt-5.5` (`{gp['variance_reduction']['vrf_paired_diff']:.2f}x`, `N_eff = {gp['variance_reduction']['n_eff_at_30']:.1f}`) because solver seed `15` carries its own `-1.0` noisy-canary cliff. Only `gemini-4-carbon` medium (`30/30` empirical accuracy with lucky gambles on seeds `[7, 29]`) has `VRF = {cm['variance_reduction']['vrf_paired_diff']:.2f}x < 1` because zero Bernoulli cliff flips materialized.",
        f"2. **MDE at 80% power (`alpha=0.05` two-sided) explains why `n=10` is uninformative on raw scores and why `n=30..36` luck-adjusted crosses the primary gap:** On `gemini-4-carbon` hard, at `n=10` raw paired-`t` MDE is `{ch_mde_raw[10]['mde_t_score']:.3f}` (`{_pct(ch_mde_raw[10]['mde_t_pct_solver'])}` of solver; normal-approx `{ch_mde_raw[10]['mde_z_score']:.3f}` = `{_pct(ch_mde_raw[10]['mde_z_pct_solver'])}`). At `n=30`, luck-adjusted paired-`t` MDE falls from `{ch_mde_raw[30]['mde_t_score']:.3f}` (`{_pct(ch_mde_raw[30]['mde_t_pct_solver'])}` of solver, power `{_pct(ch_mde_raw[30]['power_t_at_obs_gap'])}`) to `{ch_mde_la[30]['mde_t_score']:.3f}` (`{_pct(ch_mde_la[30]['mde_t_pct_solver'])}` of solver, power `{_pct(ch_mde_la[30]['power_t_at_obs_gap'])}`), reaching 80% paired-`t` power for the observed `-0.140` (`28.0%` of solver) luck-adjusted gap at `n = {ch['sample_size_requirements_80pct_power']['la_n_req_t_obs_gap']}` (`n = {ch['sample_size_requirements_80pct_power']['la_n_req_z_obs_gap']}` normal-approx) vs `n = {ch['sample_size_requirements_80pct_power']['raw_n_req_t_obs_gap']}` (`n = {ch['sample_size_requirements_80pct_power']['raw_n_req_z_obs_gap']}` normal-approx) under raw scoring.",
        f"3. **Exact `n=10` sampling from locked `gemini-4-carbon` hard `0-29` (`64.6%` of solver) reconciles single-run Harbor variance while isolating shared-world + harness effects across `[93%, 116%, 131%]` (`d0ead011`):** Drawing `n=10` without replacement from `hard 0-29` (`4/30` wrong) yields exact hypergeometric `P(0 wrong) = {_pct(hm['p_zero_wrong_wor_hypergeom'], 2)}` (`{_pct(hm['p_zero_wrong_wr_binomial'], 2)}` binomial WR) and `P(<=1 wrong) = {_pct(hm['p_le_one_wrong_wor_hypergeom'], 2)}` (`{_pct(hm['p_le_one_wrong_wr_binomial'], 2)}` WR). Because Carbon averages `{_pct(hr['non_wrong_26_seeds_ratio_vs_solver'])}` of solver (`+0.526` vs `+0.541`) on its `26` non-wrong seeds, exact `P(sample_ratio_vs_solver >= 0.93 | n=10, WOR) = {_pct(hm['p_ratio_ge_0_93_wor_exact'], 2)}` (`{_pct(hm['p_ratio_ge_0_93_wr_mc10k'], 2)}` WR) and `P(>= 1.00 | n=10, WOR) = {_pct(hm['p_ratio_ge_1_00_wor_exact'], 2)}` (`{_pct(hm['p_ratio_ge_1_00_wr_mc10k'], 2)}` WR). Thus a single `93%` (`9/10`) run (`opencode-1`) occurs ~1 in 5 times by chance alone, whereas `[116%, 131%]` (`28/29` pooled accuracy across `[10, 10, 9]`) reflects (i) all 3 Harbor runs sharing the same 10 fixed judge tasks where oracle hit a `-1.00` cliff on `hard-900007`, plus (ii) Harbor bash shell access (`20/28` trials) and `1bc3e281` error/prompt updates.",
        "",
        f"{H2} 1. Luck-Adjustment Variance Reduction and Effective Sample Size (`0-29` Paired Cohorts)",
        "",
        "| Cohort | Wrong (F/S) | SD(raw diff) | SD(la diff) | VRF = Var(raw)/Var(la) | N_eff (at n=30) | Raw / Solver [95% CI] (span) | LA / Solver [95% CI] (span) |",
        "|---|---|---:|---:|---:|---:|---|---|",
    ]
    for c in cohorts:
        rw, la, vr = c["raw"], c["luck_adjusted"], c["variance_reduction"]
        r_ci_s = f"{_pct(rw['ratio_vs_solver'], 0)} [{rw['ratio_ci_rounded_pct'][0]}%, {rw['ratio_ci_rounded_pct'][1]}%] ({rw['ratio_ci_rounded_span_pp']} pp)"
        l_ci_s = f"{_pct(la['ratio_vs_solver'], 0)} [{la['ratio_ci_rounded_pct'][0]}%, {la['ratio_ci_rounded_pct'][1]}%] ({la['ratio_ci_rounded_span_pp']} pp)"
        lines.append(
            f"| {c['label']} | {c['wrong_cliff_count']}/{len(c['solver_wrong_cliff_seeds'])} | "
            f"{rw['paired_diff_sd']:.3f} | {la['paired_diff_sd']:.3f} | "
            f"{vr['vrf_paired_diff']:.2f}x | {vr['n_eff_at_30']:.1f} | {r_ci_s} | {l_ci_s} |"
        )

    lines.extend([
        "",
        f"{H2} 2. Minimum Detectable Effect (`MDE` at 80% Power, Two-Sided `alpha=0.05`) Across `n in {{6, 9, 10, 20, 30, 32, 35, 36, 60}}`",
        "",
        f"{H3} 2a. Primary OpenCode `gemini-4-carbon` Hard (`0-29` Empirical Variance: Raw SD `{ch['raw']['paired_diff_sd']:.3f}`, LA SD `{ch['luck_adjusted']['paired_diff_sd']:.3f}`)",
        "",
        "| n | Canary v1.4 Cohort Meaning | Raw MDE_t (% sol) | Raw MDE_z (% sol) | Raw Power_t (@ -0.177) | LA MDE_t (% sol) | LA MDE_z (% sol) | LA Power_t (@ -0.140) |",
        "|---:|---|---|---|---|---|---|---|",
    ])
    for n in SAMPLE_SIZES:
        rm, lm = ch_mde_raw[n], ch_mde_la[n]
        lines.append(
            f"| {n} | `{SAMPLE_SIZE_LABELS[n]}` | "
            f"{rm['mde_t_score']:.3f} ({_pct(rm['mde_t_pct_solver'])}) | {rm['mde_z_score']:.3f} ({_pct(rm['mde_z_pct_solver'])}) | {_pct(rm['power_t_at_obs_gap'])} | "
            f"{lm['mde_t_score']:.3f} ({_pct(lm['mde_t_pct_solver'])}) | {lm['mde_z_score']:.3f} ({_pct(lm['mde_z_pct_solver'])}) | {_pct(lm['power_t_at_obs_gap'])} |"
        )

    lines.extend([
        "",
        f"{H3} 2b. Paired-`t` MDE (`% of solver`, 80% Power) Across All Paired `0-29` Cohorts (`Raw -> Luck-Adjusted`)",
        "",
        "| Cohort | n=6 | n=10 | n=20 | n=30 | n=36 | n=60 | n* (15% sol, Raw -> LA) |",
        "|---|---|---|---|---|---|---|---:|",
    ])
    for c in cohorts:
        rmap = {r[0]: _mde_row_dict(r) for r in c["mde_curve"]["raw"]}
        lmap = {r[0]: _mde_row_dict(r) for r in c["mde_curve"]["post_expected"]}
        cells = [f"{_pct(rmap[k]['mde_t_pct_solver'], 0)}->{_pct(lmap[k]['mde_t_pct_solver'], 0)}" for k in (6, 10, 20, 30, 36, 60)]
        srq = c["sample_size_requirements_80pct_power"]
        lines.append(f"| {c['label']} | " + " | ".join(cells) + f" | {srq['raw_n_req_t_15pct_solver']} -> {srq['la_n_req_t_15pct_solver']} |")

    lines.extend([
        "",
        f"{H2} 3. Exact `n=10` and `n=9` Sampling Distribution from `gemini-4-carbon` Hard `0-29` vs Harbor Rehearsal (`d0ead011`)",
        "",
        "| Sampling Regime | n | P(0 wrong) | P(<=1 wrong) | P(ratio >= 0.93) | P(ratio >= 1.00) | P(ratio >= 1.16) | P(ratio >= 1.31) | Ratio Median [2.5%, 97.5%] |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
        f"| Exact Combinatorial / Hypergeom (WOR) | 10 | {_pct(hm['p_zero_wrong_wor_hypergeom'], 2)} | {_pct(hm['p_le_one_wrong_wor_hypergeom'], 2)} | {_pct(hm['p_ratio_ge_0_93_wor_exact'], 2)} | {_pct(hm['p_ratio_ge_1_00_wor_exact'], 2)} | {_pct(hm['p_ratio_ge_1_16_wor_exact'], 2)} | {_pct(hm['p_ratio_ge_1_31_wor_exact'], 2)} | n/a (exact tail enumeration) |",
        f"| Seeded 10,000 Draws (WOR, seed={SUBSAMPLE_SEED}) | 10 | {_pct(mc10_wor['empirical_p_zero_wrong'], 2)} | {_pct(mc10_wor['empirical_p_le_one_wrong'], 2)} | {_pct(mc10_wor['tail_probs_raw_ratio']['ge_0.93'], 2)} | {_pct(mc10_wor['tail_probs_raw_ratio']['ge_1.00'], 2)} | {_pct(mc10_wor['tail_probs_raw_ratio']['ge_1.16'], 2)} | {_pct(mc10_wor['tail_probs_raw_ratio']['ge_1.31'], 2)} | {_pct(mc10_wor['raw_ratio_quantiles']['p50'])} [{_pct(mc10_wor['raw_ratio_quantiles']['p025'])}, {_pct(mc10_wor['raw_ratio_quantiles']['p975'])}] |",
        f"| Seeded 10,000 Draws / Binomial (WR, seed={SUBSAMPLE_SEED}) | 10 | {_pct(hm['p_zero_wrong_wr_binomial'], 2)} | {_pct(hm['p_le_one_wrong_wr_binomial'], 2)} | {_pct(mc10_wr['tail_probs_raw_ratio']['ge_0.93'], 2)} | {_pct(mc10_wr['tail_probs_raw_ratio']['ge_1.00'], 2)} | {_pct(mc10_wr['tail_probs_raw_ratio']['ge_1.16'], 2)} | {_pct(mc10_wr['tail_probs_raw_ratio']['ge_1.31'], 2)} | {_pct(mc10_wr['raw_ratio_quantiles']['p50'])} [{_pct(mc10_wr['raw_ratio_quantiles']['p025'])}, {_pct(mc10_wr['raw_ratio_quantiles']['p975'])}] |",
        f"| Exact Combinatorial / Hypergeom (WOR, `opencode-3` size) | 9 | {_pct(ex9['p_zero_wrong_hypergeom'], 2)} | {_pct(ex9['p_le_one_wrong_hypergeom'], 2)} | {_pct(ex9['exact_wor_ratio_tails']['ge_0.93']['exact_prob'], 2)} | {_pct(ex9['exact_wor_ratio_tails']['ge_1.00']['exact_prob'], 2)} | {_pct(ex9['exact_wor_ratio_tails']['ge_1.16']['exact_prob'], 2)} | {_pct(ex9['exact_wor_ratio_tails']['ge_1.31']['exact_prob'], 2)} | n/a (exact tail enumeration) |",
        "",
        f"Conditional on wrong-accusation count `W` in `n=10` WOR draws (`seed={SUBSAMPLE_SEED}`): `E[ratio | W=0] = {_pct(mc10_wor['mean_raw_ratio_by_wrong_count']['0'])}`, `E[ratio | W=1] = {_pct(mc10_wor['mean_raw_ratio_by_wrong_count']['1'])}`, `E[ratio | W=2] = {_pct(mc10_wor['mean_raw_ratio_by_wrong_count']['2'])}`, `E[ratio | W>=3] = {_pct(mc10_wor['mean_raw_ratio_by_wrong_count']['3_plus'])}`. In `hard 0-29`, `seed 15` is a joint `-1.0` cliff for both solver and Carbon (`{_pct(mc10_wor['mean_raw_ratio_when_no_solver_cliff'])}` -> `{_pct(mc10_wor['mean_raw_ratio_when_solver_cliff_included'])}` when drawn); by contrast, when an agent achieves `W=0` (`10/10`) on a 10-task set containing one unilateral oracle `-1.0` cliff (matching Harbor `hard-900007`), expected ratio jumps to `{_pct(hr['analytic_ratio_if_zero_wrong_vs_one_oracle_cliff'])}` (aligning with Harbor `opencode-2` `116%` and `opencode-3` `131%`).",
        "",
        f"{H2} Reproduce",
        "",
        "```bash",
        "PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --write",
        "PYTHONPATH=. python scripts/frontier_power_and_variance_v14.py --check",
        "pytest -q tests/test_frontier_power_and_variance_v14.py",
        "```",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Canary v1.4 power, variance-reduction, and Harbor n=10 subsample audit.")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out-json", type=Path, default=None)
    ap.add_argument("--out-md", type=Path, default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    out_json, out_md = args.out_json or default_json_path(root), args.out_md or default_md_path(root)
    audit = compute_audit(root=root, enforce_expected_counts=(root == ROOT.resolve()))
    json_blob, md_blob = serialize_json(audit), render_markdown(audit)
    if args.stdout:
        sys.stdout.write(md_blob)
    if args.write:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_blob, encoding="utf-8")
        out_md.write_text(md_blob, encoding="utf-8")
    if args.check:
        if not out_json.exists() or not out_md.exists():
            return 1
        disk_raw = out_json.read_bytes()
        md_raw = out_md.read_bytes()
        if len(disk_raw) == 0 or len(disk_raw) > MAX_JSON_BYTES or not disk_raw.isascii() or not md_raw.isascii():
            return 1
        try:
            disk_txt = disk_raw.decode("ascii")
            md_txt = md_raw.decode("ascii")
            disk_obj = json.loads(disk_txt)
        except ValueError:
            return 1
        if EM_DASH in disk_txt or EN_DASH in disk_txt or EM_DASH in md_txt or EN_DASH in md_txt:
            return 1
        if not approx_equal(disk_obj, audit) or md_txt != md_blob:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
