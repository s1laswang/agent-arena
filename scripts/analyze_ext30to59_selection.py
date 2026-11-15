"""Deterministic keyless selection and sensitivity audit for v1.4 hard extension seeds 30-59."""
from __future__ import annotations

import argparse
import itertools
import json
import math
import operator
import os
import random
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRIMARY_SEEDS = list(range(0, 30))
EXT_ALL_SEEDS = list(range(30, 60))
ALL_60_SEEDS = list(range(0, 60))
G1_SEEDS = [34, 37]
FLEET7_SEEDS = [30, 34, 42, 45, 48, 57, 58]
OBSERVED_EXT8_SEEDS = [30, 34, 37, 42, 45, 48, 57, 58]
UNOBSERVED_EXT22_SEEDS = [s for s in EXT_ALL_SEEDS if s not in OBSERVED_EXT8_SEEDS]
POOLED38_SEEDS = PRIMARY_SEEDS + OBSERVED_EXT8_SEEDS
CARBON_AGENT = "opencode:google/gemini-4-carbon"
SOLVER_AGENT = "solver"
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH = chr(35)
H1 = HASH + " "
H2 = HASH * 2 + " "
H3 = HASH * 3 + " "
DEFAULT_REPORT_REL = Path("docs/reports/frontier_ext30to59_selection_sensitivity.md")


def _load_valid_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ep = json.loads(line)
        if (ep.get("meta") or {}).get("valid") is False:
            continue
        rows.append(ep)
    return rows


_BOOT_IDX_CACHE: dict[tuple[int, int, int], list[tuple[int, ...]]] = {}
_BOOT_GETTERS_CACHE: dict[tuple[int, int, int], list[Any]] = {}
_BOOT_MEANS_CACHE: dict[tuple[tuple[float, ...], int, int], list[float]] = {}
_DONOR_SCHED_CACHE: dict[
    tuple[tuple[int, ...], tuple[tuple[int, int], ...], int, int],
    tuple[dict[int, int], int, list[tuple[int, ...]]],
] = {}
_PERM_IDX_CACHE: dict[tuple[int, int, int, int], list[tuple[tuple[int, ...], tuple[int, ...]]]] = {}
_PERM_GETTERS_CACHE: dict[tuple[int, int, int, int], list[tuple[Any, Any]]] = {}


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
    arr_f: list[float],
    arr_s: list[float],
    n_boot: int = 10000,
    rng_seed: int = 0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    mfs = _get_boot_means(arr_f, n_boot, rng_seed)
    mss = _get_boot_means(arr_s, n_boot, rng_seed)
    diffs = [mf - ms for mf, ms in zip(mfs, mss)]
    ratios = [mf / ms for mf, ms in zip(mfs, mss) if ms > 0.0]
    ratios.sort()
    diffs.sort()
    r_lo = ratios[int(0.025 * len(ratios))]
    r_hi = ratios[int(0.975 * len(ratios)) - 1]
    d_lo = diffs[int(0.025 * len(diffs))]
    d_hi = diffs[int(0.975 * len(diffs)) - 1]
    return (r_lo, r_hi), (d_lo, d_hi)


def _get_donor_schedule(
    obs_seeds_sorted: tuple[int, ...],
    pool_sizes: tuple[tuple[int, int], ...],
    n_boot: int,
    rng_seed: int,
) -> tuple[dict[int, int], int, list[tuple[int, ...]]]:
    key = (obs_seeds_sorted, pool_sizes, n_boot, rng_seed)
    cached = _DONOR_SCHED_CACHE.get(key)
    if cached is not None:
        return cached
    obs_set = set(obs_seeds_sorted)
    offsets: dict[int, int] = {}
    size_map: dict[int, int] = {}
    cursor = 60
    for seed, sz in pool_sizes:
        offsets[seed] = cursor
        size_map[seed] = sz
        cursor += sz
    rng = random.Random(rng_seed)
    randrange = rng.randrange
    rows: list[tuple[int, ...]] = []
    for _ in range(n_boot):
        idx = [randrange(60) for _ in range(60)]
        flat_idx = [
            seed if seed in obs_set else offsets[seed] + randrange(size_map[seed])
            for seed in idx
        ]
        rows.append(tuple(flat_idx))
    out = (offsets, cursor, rows)
    _DONOR_SCHED_CACHE[key] = out
    return out


def _boot_donor_imputation(
    observed_by_seed: dict[int, float],
    solver_by_seed: dict[int, float],
    donor_pools_by_unobs_seed: dict[int, list[float]],
    n_boot: int = 10000,
    rng_seed: int = 0,
) -> tuple[tuple[float, float], tuple[float, float]]:
    obs_key = tuple(sorted(observed_by_seed))
    pool_key = tuple((s, len(donor_pools_by_unobs_seed[s])) for s in sorted(donor_pools_by_unobs_seed))
    offsets, total_len, sched_rows = _get_donor_schedule(obs_key, pool_key, n_boot, rng_seed)
    flat_f = [0.0] * total_len
    flat_s = [0.0] * total_len
    for seed, val in observed_by_seed.items():
        flat_f[seed] = val
        flat_s[seed] = solver_by_seed[seed]
    for seed, pool in donor_pools_by_unobs_seed.items():
        base = offsets[seed]
        s_val = solver_by_seed[seed]
        for j, d_val in enumerate(pool):
            flat_f[base + j] = d_val
            flat_s[base + j] = s_val
    ratios: list[float] = []
    diffs: list[float] = []
    for k_row in sched_rows:
        f_sum = 0.0
        s_sum = 0.0
        for k in k_row:
            f_sum += flat_f[k]
            s_sum += flat_s[k]
        mf = f_sum / 60.0
        ms = s_sum / 60.0
        diffs.append(mf - ms)
        if ms > 0.0:
            ratios.append(mf / ms)
    ratios.sort()
    diffs.sort()
    return (
        (ratios[int(0.025 * len(ratios))], ratios[int(0.975 * len(ratios)) - 1]),
        (diffs[int(0.025 * len(diffs))], diffs[int(0.975 * len(diffs)) - 1]),
    )


def _get_perm_indices(
    n_a: int,
    n_b: int,
    n_perm: int,
    rng_seed: int,
) -> list[tuple[tuple[int, ...], tuple[int, ...]]]:
    key = (n_a, n_b, n_perm, rng_seed)
    cached = _PERM_IDX_CACHE.get(key)
    if cached is not None:
        return cached
    base = list(range(n_a + n_b))
    rng = random.Random(rng_seed)
    shuffle = rng.shuffle
    rows: list[tuple[tuple[int, ...], tuple[int, ...]]] = []
    for _ in range(n_perm):
        perm = list(base)
        shuffle(perm)
        rows.append((tuple(perm[:n_a]), tuple(perm[n_a:])))
    _PERM_IDX_CACHE[key] = rows
    return rows


def _get_perm_getters(
    n_a: int,
    n_b: int,
    n_perm: int,
    rng_seed: int,
) -> list[tuple[Any, Any]]:
    key = (n_a, n_b, n_perm, rng_seed)
    cached = _PERM_GETTERS_CACHE.get(key)
    if cached is not None:
        return cached
    getters = [
        (_seq_getter(idx_a), _seq_getter(idx_b))
        for idx_a, idx_b in _get_perm_indices(n_a, n_b, n_perm, rng_seed)
    ]
    _PERM_GETTERS_CACHE[key] = getters
    return getters


def _perm_test_two_sided(
    vals_a: list[float],
    vals_b: list[float],
    n_perm: int = 10000,
    rng_seed: int = 0,
) -> float:
    obs_diff = abs(sum(vals_a) / len(vals_a) - sum(vals_b) / len(vals_b))
    pool = tuple(vals_a) + tuple(vals_b)
    n_a = len(vals_a)
    n_b = len(vals_b)
    extreme = 0
    for get_a, get_b in _get_perm_getters(n_a, n_b, n_perm, rng_seed):
        diff = abs(sum(get_a(pool)) / n_a - sum(get_b(pool)) / n_b)
        if diff >= obs_diff - 1e-12:
            extreme += 1
    return (extreme + 1) / (n_perm + 1)


_EP_OBS_CACHE: dict[tuple[str, str], dict[str, Any]] = {}


def _episode_observables(ep: dict[str, Any]) -> dict[str, Any]:
    from canary import rules
    from canary.analysis.accuse import audit_episode
    from canary.analysis.tags import to_result

    cache_key = (str(rules.TIERS_VERSION), json.dumps(ep, sort_keys=True))
    cached = _EP_OBS_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    aud = audit_episode(to_result(ep))
    accused = ep.get("accused")
    abstained = accused is None
    correct = bool(ep.get("correct", False))
    p_acc = aud["p_accused"]
    p_top = aud["p_top"]
    meta = ep.get("meta") or {}
    v_raw = meta.get("V", meta.get("V_final"))
    if v_raw is None:
        raise ValueError(f"missing V in meta for seed={ep.get('seed')}")
    v_val = float(v_raw)
    if abstained:
        la_score = 0.0
        accuse_day = None
        horizon_day = int(ep["final_day"])
    else:
        if p_acc is None:
            raise ValueError(f"missing p_accused for accused episode seed={ep.get('seed')}")
        la_score = float(p_acc) * v_val - (1.0 - float(p_acc))
        accuse_day = int(aud["day"])
        horizon_day = int(aud["day"])
    steps = ep.get("steps") or []
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
        "raw_score": float(ep["score"]),
        "luck_adjusted_score": la_score,
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
        "verdict": str(aud["verdict"]),
    }
    _EP_OBS_CACHE[cache_key] = out
    return dict(out)


def _summarize_cohort(seeds: list[int], obs_map: dict[int, dict[str, Any]], label: str) -> dict[str, Any]:
    from canary.analysis.gap import mean_ci

    rows = [obs_map[s] for s in seeds]
    n = len(rows)
    raw_vals = [r["raw_score"] for r in rows]
    la_vals = [r["luck_adjusted_score"] for r in rows]
    step_vals = [float(r["total_steps"]) for r in rows]
    can_vals = [float(r["canary_count"]) for r in rows]
    hor_vals = [float(r["horizon_day"]) for r in rows]
    v_vals = [r["company_value_v"] for r in rows]
    acc_days = [float(r["accuse_day"]) for r in rows if r["accuse_day"] is not None]
    p_vals = [float(r["p_accused"]) for r in rows if r["p_accused"] is not None]

    raw_mean, raw_ci = mean_ci(raw_vals)
    la_mean, la_ci = mean_ci(la_vals)
    steps_mean, steps_ci = mean_ci(step_vals)
    can_mean, can_ci = mean_ci(can_vals)
    hor_mean, hor_ci = mean_ci(hor_vals)
    acc_day_mean = sum(acc_days) / len(acc_days) if acc_days else float("nan")
    p_mean = sum(p_vals) / len(p_vals) if p_vals else float("nan")

    return {
        "label": label,
        "n": n,
        "seeds": list(seeds),
        "raw_mean": raw_mean,
        "raw_ci": raw_ci,
        "luck_adjusted_mean": la_mean,
        "luck_adjusted_ci": la_ci,
        "accuse_day_mean": acc_day_mean,
        "accuse_day_n": len(acc_days),
        "horizon_day_mean": hor_mean,
        "horizon_day_ci": hor_ci,
        "steps_mean": steps_mean,
        "steps_ci": steps_ci,
        "steps_median": float(statistics.median(step_vals)),
        "canary_mean": can_mean,
        "canary_ci": can_ci,
        "accuracy": sum(1 for r in rows if r["correct"]) / n,
        "correct_count": sum(1 for r in rows if r["correct"]),
        "wrong_count": sum(1 for r in rows if r["wrong"]),
        "abstention_count": sum(1 for r in rows if r["abstained"]),
        "accused_count": sum(1 for r in rows if not r["abstained"]),
        "company_value_v_mean": sum(v_vals) / n,
        "p_accused_mean": p_mean,
    }


def _build_scenario(
    scenario_id: str,
    label: str,
    seeds: list[int],
    raw_f: list[float],
    raw_s: list[float],
    la_f: list[float],
    la_s: list[float],
    observed_n: int,
    imputed_n: int,
    imputation_rule: str,
    donor_boot_raw: tuple[tuple[float, float], tuple[float, float]] | None = None,
    donor_boot_la: tuple[tuple[float, float], tuple[float, float]] | None = None,
) -> dict[str, Any]:
    from canary.analysis.gap import mean_ci

    raw_f_mean, raw_f_ci = mean_ci(raw_f)
    raw_s_mean, raw_s_ci = mean_ci(raw_s)
    raw_diff_mean, raw_diff_ci = mean_ci([x - y for x, y in zip(raw_f, raw_s)])
    raw_ratio = raw_f_mean / raw_s_mean
    (raw_r_lo, raw_r_hi), (raw_b_d_lo, raw_b_d_hi) = _boot_ratio_and_diff(raw_f, raw_s, n_boot=10000, rng_seed=0)

    la_f_mean, la_f_ci = mean_ci(la_f)
    la_s_mean, la_s_ci = mean_ci(la_s)
    la_diff_mean, la_diff_ci = mean_ci([x - y for x, y in zip(la_f, la_s)])
    la_ratio = la_f_mean / la_s_mean
    (la_r_lo, la_r_hi), (la_b_d_lo, la_b_d_hi) = _boot_ratio_and_diff(la_f, la_s, n_boot=10000, rng_seed=0)

    out: dict[str, Any] = {
        "id": scenario_id,
        "label": label,
        "n": len(seeds),
        "observed_n": observed_n,
        "imputed_n": imputed_n,
        "imputation_rule": imputation_rule,
        "raw": {
            "gemini_mean": raw_f_mean,
            "gemini_ci": raw_f_ci,
            "solver_mean": raw_s_mean,
            "solver_ci": raw_s_ci,
            "diff": raw_diff_mean,
            "diff_ci": raw_diff_ci,
            "diff_boot_lo": raw_b_d_lo,
            "diff_boot_hi": raw_b_d_hi,
            "ratio": raw_ratio,
            "ratio_lo": raw_r_lo,
            "ratio_hi": raw_r_hi,
        },
        "luck_adjusted": {
            "gemini_mean": la_f_mean,
            "gemini_ci": la_f_ci,
            "solver_mean": la_s_mean,
            "solver_ci": la_s_ci,
            "diff": la_diff_mean,
            "diff_ci": la_diff_ci,
            "diff_boot_lo": la_b_d_lo,
            "diff_boot_hi": la_b_d_hi,
            "ratio": la_ratio,
            "ratio_lo": la_r_lo,
            "ratio_hi": la_r_hi,
        },
    }
    if donor_boot_raw is not None:
        out["raw"]["donor_boot_ratio_lo"] = donor_boot_raw[0][0]
        out["raw"]["donor_boot_ratio_hi"] = donor_boot_raw[0][1]
        out["raw"]["donor_boot_diff_lo"] = donor_boot_raw[1][0]
        out["raw"]["donor_boot_diff_hi"] = donor_boot_raw[1][1]
    if donor_boot_la is not None:
        out["luck_adjusted"]["donor_boot_ratio_lo"] = donor_boot_la[0][0]
        out["luck_adjusted"]["donor_boot_ratio_hi"] = donor_boot_la[0][1]
        out["luck_adjusted"]["donor_boot_diff_lo"] = donor_boot_la[1][0]
        out["luck_adjusted"]["donor_boot_diff_hi"] = donor_boot_la[1][1]
    return out


def analyze_selection(
    repo: Path | str = ROOT,
    committed_ext_jsonl: Path | str | None = None,
    fleet_ext_jsonl: Path | str | None = None,
) -> dict[str, Any]:
    os.environ.setdefault("CANARY_ALLOW_DEV", "1")
    from canary import rules

    repo_path = Path(repo).resolve()
    ref_root = repo_path / "data" / "runs" / "committed" / "v1.4" / "reference"
    primary_jsonl = repo_path / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    comm_ext_path = (
        Path(committed_ext_jsonl).resolve()
        if committed_ext_jsonl is not None
        else repo_path / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    )
    fleet_ext_path = (
        Path(fleet_ext_jsonl).resolve()
        if fleet_ext_jsonl is not None
        else repo_path / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    )

    solver_files = sorted(ref_root.glob("solver-hard-*/episodes.jsonl"))
    if not solver_files:
        raise FileNotFoundError(f"no solver-hard-*/episodes.jsonl found under {ref_root}")
    if not primary_jsonl.is_file():
        raise FileNotFoundError(f"missing primary episodes file: {primary_jsonl}")
    if not comm_ext_path.is_file():
        raise FileNotFoundError(f"missing committed extension episodes file: {comm_ext_path}")

    solver_by_seed: dict[int, dict[str, Any]] = {}
    for sf in solver_files:
        for ep in _load_valid_jsonl(sf):
            if ep.get("agent") != SOLVER_AGENT or ep.get("tier") != "hard":
                raise ValueError(f"unexpected solver record in {sf}: agent={ep.get('agent')} tier={ep.get('tier')}")
            seed = int(ep["seed"])
            if seed in solver_by_seed:
                raise ValueError(f"duplicate solver hard seed={seed} across solver-hard-* shards")
            solver_by_seed[seed] = ep
    if sorted(solver_by_seed) != ALL_60_SEEDS:
        raise ValueError(f"expected solver hard seeds 0..59, got {sorted(solver_by_seed)}")

    primary_eps = _load_valid_jsonl(primary_jsonl)
    primary_by_seed = {int(ep["seed"]): ep for ep in primary_eps}
    if len(primary_eps) != 30 or sorted(primary_by_seed) != PRIMARY_SEEDS:
        raise ValueError(f"expected 30 primary seeds 0..29, got {sorted(primary_by_seed)}")
    for ep in primary_eps:
        if ep.get("agent") != CARBON_AGENT or ep.get("tier") != "hard":
            raise ValueError(f"unexpected primary record seed={ep.get('seed')}")

    comm_ext_eps = _load_valid_jsonl(comm_ext_path)
    comm_ext_seeds = [int(ep["seed"]) for ep in comm_ext_eps]
    if comm_ext_seeds not in (G1_SEEDS, OBSERVED_EXT8_SEEDS):
        raise ValueError(
            f"committed ext seeds {comm_ext_seeds} must be either {G1_SEEDS} (justSilas) or {OBSERVED_EXT8_SEEDS} (PR {HASH}3)"
        )
    for ep in comm_ext_eps:
        if ep.get("agent") != CARBON_AGENT or ep.get("tier") != "hard":
            raise ValueError(f"unexpected committed ext record seed={ep.get('seed')}")
    comm_by_seed = {int(ep["seed"]): ep for ep in comm_ext_eps}

    fleet_eps: list[dict[str, Any]] = []
    if fleet_ext_path.is_file():
        fleet_eps = _load_valid_jsonl(fleet_ext_path)
        fleet_seeds = [int(ep["seed"]) for ep in fleet_eps]
        if fleet_seeds != FLEET7_SEEDS:
            raise ValueError(f"expected fleet seeds {FLEET7_SEEDS}, got {fleet_seeds}")
        for ep in fleet_eps:
            if ep.get("agent") != CARBON_AGENT or ep.get("tier") != "hard":
                raise ValueError(f"unexpected fleet ext record seed={ep.get('seed')}")
    elif comm_ext_seeds != OBSERVED_EXT8_SEEDS:
        raise FileNotFoundError(f"missing fleet extension episodes file: {fleet_ext_path}")
    fleet_by_seed = {int(ep["seed"]): ep for ep in fleet_eps}

    dedup_by_seed: dict[int, dict[str, Any]] = dict(fleet_by_seed)
    for seed, ep in comm_by_seed.items():
        dedup_by_seed[seed] = ep

    if sorted(dedup_by_seed) != OBSERVED_EXT8_SEEDS:
        raise ValueError(f"deduplicated extension seeds {sorted(dedup_by_seed)} != {OBSERVED_EXT8_SEEDS}")
    if dedup_by_seed[34] is not comm_by_seed[34]:
        raise ValueError("G1 precedence violated on overlapping seed 34")
    if int(dedup_by_seed[34]["final_day"]) != 5 or abs(float(dedup_by_seed[34]["score"]) - 0.79) > 1e-9:
        raise ValueError("seed 34 in deduplicated ext8 does not match committed G1 episode (day=5, score=0.79)")

    if fleet_by_seed:
        if int(fleet_by_seed[34]["final_day"]) != 8 or abs(float(fleet_by_seed[34]["score"]) - 0.82) > 1e-9:
            raise ValueError("fleet seed 34 does not match expected replication episode (day=8, score=0.82)")
        shared_non34 = sorted((set(comm_by_seed) & set(fleet_by_seed)) - {34})
        for seed in shared_non34:
            ce = comm_by_seed[seed]
            fe = fleet_by_seed[seed]
            if (
                abs(float(ce["score"]) - float(fe["score"])) > 1e-9
                or ce.get("accused") != fe.get("accused")
                or bool(ce.get("correct", False)) != bool(fe.get("correct", False))
                or int(ce["final_day"]) != int(fe["final_day"])
                or len(ce.get("steps") or []) != len(fe.get("steps") or [])
            ):
                raise ValueError(f"PR {HASH}3 committed ext seed {seed} diverges from fleet replication episode")

    with rules.tiers_version("v1.4"):
        sol_obs = {s: _episode_observables(solver_by_seed[s]) for s in ALL_60_SEEDS}
        gem_primary_obs = {s: _episode_observables(primary_by_seed[s]) for s in PRIMARY_SEEDS}
        gem_ext8_obs = {s: _episode_observables(dedup_by_seed[s]) for s in OBSERVED_EXT8_SEEDS}
        gem_fleet34_obs = _episode_observables(fleet_by_seed[34]) if 34 in fleet_by_seed else None

    g1_unobs28 = [s for s in EXT_ALL_SEEDS if s not in G1_SEEDS]
    solver_cohorts = {
        "observed_ext8": _summarize_cohort(OBSERVED_EXT8_SEEDS, sol_obs, "Observed extension seeds (ext8)"),
        "unobserved_ext22": _summarize_cohort(UNOBSERVED_EXT22_SEEDS, sol_obs, "Unobserved extension seeds (unobs22)"),
        "g1_observed2": _summarize_cohort(G1_SEEDS, sol_obs, "Initial G1 pre-stop seeds ([34, 37])"),
        "g1_unobserved28": _summarize_cohort(g1_unobs28, sol_obs, "G1 unobserved seeds (28 seeds)"),
        "fleet_observed7": _summarize_cohort(FLEET7_SEEDS, sol_obs, "Fleet replication seeds (fleet7)"),
        "ext30to59_all": _summarize_cohort(EXT_ALL_SEEDS, sol_obs, "Full extension cohort (seeds 30-59)"),
        "primary0to29": _summarize_cohort(PRIMARY_SEEDS, sol_obs, "Primary cohort (seeds 0-29)"),
        "pooled0to59_all": _summarize_cohort(ALL_60_SEEDS, sol_obs, "Full pooled cohort (seeds 0-59)"),
    }
    gemini_cohorts = {
        "primary0to29": _summarize_cohort(PRIMARY_SEEDS, gem_primary_obs, "Gemini primary (seeds 0-29)"),
        "g1_observed2": _summarize_cohort(G1_SEEDS, gem_ext8_obs, "Gemini G1 pre-stop ([34, 37])"),
        "observed_ext8": _summarize_cohort(OBSERVED_EXT8_SEEDS, gem_ext8_obs, "Gemini deduplicated extension (ext8)"),
    }

    obs_vs_unobs_metrics: dict[str, dict[str, Any]] = {}
    for metric_key, field_name in (
        ("raw_score", "raw_score"),
        ("luck_adjusted_score", "luck_adjusted_score"),
        ("horizon_day", "horizon_day"),
        ("total_steps", "total_steps"),
        ("canary_count", "canary_count"),
        ("accuracy", "correct"),
        ("abstention_rate", "abstained"),
        ("company_value_v", "company_value_v"),
    ):
        va = [float(sol_obs[s][field_name]) for s in OBSERVED_EXT8_SEEDS]
        vb = [float(sol_obs[s][field_name]) for s in UNOBSERVED_EXT22_SEEDS]
        ma = sum(va) / len(va)
        mb = sum(vb) / len(vb)
        obs_vs_unobs_metrics[metric_key] = {
            "obs8_mean": ma,
            "unobs22_mean": mb,
            "diff_obs_minus_unobs": ma - mb,
            "perm_p_two_sided": _perm_test_two_sided(va, vb, n_perm=10000, rng_seed=0),
        }

    va_acc = [float(sol_obs[s]["accuse_day"]) for s in OBSERVED_EXT8_SEEDS if sol_obs[s]["accuse_day"] is not None]
    vb_acc = [float(sol_obs[s]["accuse_day"]) for s in UNOBSERVED_EXT22_SEEDS if sol_obs[s]["accuse_day"] is not None]
    obs_vs_unobs_metrics["accuse_day_accused_only"] = {
        "obs8_mean": sum(va_acc) / len(va_acc),
        "unobs22_mean": sum(vb_acc) / len(vb_acc),
        "diff_obs_minus_unobs": sum(va_acc) / len(va_acc) - sum(vb_acc) / len(vb_acc),
        "perm_p_two_sided": _perm_test_two_sided(va_acc, vb_acc, n_perm=10000, rng_seed=0),
    }

    all_pairs_count = 0
    g1_steps_mean = (sol_obs[34]["total_steps"] + sol_obs[37]["total_steps"]) / 2.0
    g1_day_mean = (sol_obs[34]["horizon_day"] + sol_obs[37]["horizon_day"]) / 2.0
    g1_raw_mean = (sol_obs[34]["raw_score"] + sol_obs[37]["raw_score"]) / 2.0
    le_steps_pairs = 0
    le_day_pairs = 0
    ge_raw_pairs = 0
    for s_a, s_b in itertools.combinations(EXT_ALL_SEEDS, 2):
        all_pairs_count += 1
        if (sol_obs[s_a]["total_steps"] + sol_obs[s_b]["total_steps"]) / 2.0 <= g1_steps_mean + 1e-12:
            le_steps_pairs += 1
        if (sol_obs[s_a]["horizon_day"] + sol_obs[s_b]["horizon_day"]) / 2.0 <= g1_day_mean + 1e-12:
            le_day_pairs += 1
        if (sol_obs[s_a]["raw_score"] + sol_obs[s_b]["raw_score"]) / 2.0 >= g1_raw_mean - 1e-12:
            ge_raw_pairs += 1

    g1_exact_pair_test = {
        "total_pairs": all_pairs_count,
        "g1_solver_steps_mean": g1_steps_mean,
        "pairs_le_g1_steps": le_steps_pairs,
        "frac_le_g1_steps": le_steps_pairs / all_pairs_count,
        "g1_solver_day_mean": g1_day_mean,
        "pairs_le_g1_day": le_day_pairs,
        "frac_le_g1_day": le_day_pairs / all_pairs_count,
        "g1_solver_raw_mean": g1_raw_mean,
        "pairs_ge_g1_raw": ge_raw_pairs,
        "frac_ge_g1_raw": ge_raw_pairs / all_pairs_count,
    }

    med_steps_0to29 = float(statistics.median(sol_obs[s]["total_steps"] for s in PRIMARY_SEEDS))
    med_day_0to29 = float(statistics.median(sol_obs[s]["horizon_day"] for s in PRIMARY_SEEDS))

    fast_steps_le = [s for s in PRIMARY_SEEDS if sol_obs[s]["total_steps"] <= med_steps_0to29]
    slow_steps_gt = [s for s in PRIMARY_SEEDS if sol_obs[s]["total_steps"] > med_steps_0to29]
    fast_steps_lt = [s for s in PRIMARY_SEEDS if sol_obs[s]["total_steps"] < med_steps_0to29]
    slow_steps_ge = [s for s in PRIMARY_SEEDS if sol_obs[s]["total_steps"] >= med_steps_0to29]
    fast_day_le = [s for s in PRIMARY_SEEDS if sol_obs[s]["horizon_day"] <= med_day_0to29]
    slow_day_gt = [s for s in PRIMARY_SEEDS if sol_obs[s]["horizon_day"] > med_day_0to29]

    def _stratum_info(name: str, threshold_desc: str, fast_seeds: list[int], slow_seeds: list[int], pred) -> dict[str, Any]:
        unobs_fast = [s for s in UNOBSERVED_EXT22_SEEDS if pred(sol_obs[s])]
        unobs_slow = [s for s in UNOBSERVED_EXT22_SEEDS if not pred(sol_obs[s])]
        obs_fast = [s for s in OBSERVED_EXT8_SEEDS if pred(sol_obs[s])]
        obs_slow = [s for s in OBSERVED_EXT8_SEEDS if not pred(sol_obs[s])]
        return {
            "name": name,
            "threshold": threshold_desc,
            "primary_fast_n": len(fast_seeds),
            "primary_slow_n": len(slow_seeds),
            "primary_fast_seeds": fast_seeds,
            "primary_slow_seeds": slow_seeds,
            "primary_fast_gemini_raw": sum(gem_primary_obs[s]["raw_score"] for s in fast_seeds) / len(fast_seeds),
            "primary_fast_gemini_la": sum(gem_primary_obs[s]["luck_adjusted_score"] for s in fast_seeds) / len(fast_seeds),
            "primary_fast_solver_raw": sum(sol_obs[s]["raw_score"] for s in fast_seeds) / len(fast_seeds),
            "primary_fast_solver_la": sum(sol_obs[s]["luck_adjusted_score"] for s in fast_seeds) / len(fast_seeds),
            "primary_slow_gemini_raw": sum(gem_primary_obs[s]["raw_score"] for s in slow_seeds) / len(slow_seeds),
            "primary_slow_gemini_la": sum(gem_primary_obs[s]["luck_adjusted_score"] for s in slow_seeds) / len(slow_seeds),
            "primary_slow_solver_raw": sum(sol_obs[s]["raw_score"] for s in slow_seeds) / len(slow_seeds),
            "primary_slow_solver_la": sum(sol_obs[s]["luck_adjusted_score"] for s in slow_seeds) / len(slow_seeds),
            "ext8_fast_n": len(obs_fast),
            "ext8_slow_n": len(obs_slow),
            "unobs22_fast_n": len(unobs_fast),
            "unobs22_slow_n": len(unobs_slow),
            "unobs22_fast_seeds": unobs_fast,
            "unobs22_slow_seeds": unobs_slow,
        }

    stratification = {
        "median_solver_steps_0to29": med_steps_0to29,
        "median_solver_day_0to29": med_day_0to29,
        "steps_le_median": _stratum_info(
            "steps_le_median",
            f"solver total_steps <= {int(med_steps_0to29)} vs > {int(med_steps_0to29)}",
            fast_steps_le,
            slow_steps_gt,
            lambda r: r["total_steps"] <= med_steps_0to29,
        ),
        "steps_lt_median": _stratum_info(
            "steps_lt_median",
            f"solver total_steps < {int(med_steps_0to29)} vs >= {int(med_steps_0to29)}",
            fast_steps_lt,
            slow_steps_ge,
            lambda r: r["total_steps"] < med_steps_0to29,
        ),
        "day_le_median": _stratum_info(
            "day_le_median",
            f"solver horizon_day <= {int(med_day_0to29)} vs > {int(med_day_0to29)}",
            fast_day_le,
            slow_day_gt,
            lambda r: r["horizon_day"] <= med_day_0to29,
        ),
    }

    obs38_gem: dict[int, dict[str, Any]] = dict(gem_primary_obs)
    obs38_gem.update(gem_ext8_obs)
    obs38_raw_map = {s: obs38_gem[s]["raw_score"] for s in POOLED38_SEEDS}
    obs38_la_map = {s: obs38_gem[s]["luck_adjusted_score"] for s in POOLED38_SEEDS}
    sol60_raw_map = {s: sol_obs[s]["raw_score"] for s in ALL_60_SEEDS}
    sol60_la_map = {s: sol_obs[s]["luck_adjusted_score"] for s in ALL_60_SEEDS}
    sol60_raw_list = [sol60_raw_map[s] for s in ALL_60_SEEDS]
    sol60_la_list = [sol60_la_map[s] for s in ALL_60_SEEDS]

    def _pool60(
        scenario_id: str,
        label: str,
        imp_raw: dict[int, float],
        imp_la: dict[int, float],
        rule_desc: str,
        donor_pools_raw: dict[int, list[float]] | None = None,
        donor_pools_la: dict[int, list[float]] | None = None,
    ) -> dict[str, Any]:
        rf = [obs38_raw_map[s] if s in obs38_raw_map else imp_raw[s] for s in ALL_60_SEEDS]
        lf = [obs38_la_map[s] if s in obs38_la_map else imp_la[s] for s in ALL_60_SEEDS]
        db_r = (
            _boot_donor_imputation(obs38_raw_map, sol60_raw_map, donor_pools_raw, n_boot=10000, rng_seed=0)
            if donor_pools_raw is not None
            else None
        )
        db_l = (
            _boot_donor_imputation(obs38_la_map, sol60_la_map, donor_pools_la, n_boot=10000, rng_seed=0)
            if donor_pools_la is not None
            else None
        )
        return _build_scenario(
            scenario_id=scenario_id,
            label=label,
            seeds=ALL_60_SEEDS,
            raw_f=rf,
            raw_s=sol60_raw_list,
            la_f=lf,
            la_s=sol60_la_list,
            observed_n=38,
            imputed_n=22,
            imputation_rule=rule_desc,
            donor_boot_raw=db_r,
            donor_boot_la=db_l,
        )

    prim_raw_pool = [gem_primary_obs[s]["raw_score"] for s in PRIMARY_SEEDS]
    prim_la_pool = [gem_primary_obs[s]["luck_adjusted_score"] for s in PRIMARY_SEEDS]
    prim_raw_mean = sum(prim_raw_pool) / 30.0
    prim_la_mean = sum(prim_la_pool) / 30.0

    st_steps = stratification["steps_le_median"]
    st_steps_strict = stratification["steps_lt_median"]
    st_day = stratification["day_le_median"]

    fast_steps_raw_pool = [gem_primary_obs[s]["raw_score"] for s in fast_steps_le]
    fast_steps_la_pool = [gem_primary_obs[s]["luck_adjusted_score"] for s in fast_steps_le]
    slow_steps_raw_pool = [gem_primary_obs[s]["raw_score"] for s in slow_steps_gt]
    slow_steps_la_pool = [gem_primary_obs[s]["luck_adjusted_score"] for s in slow_steps_gt]

    slow_strict_raw_pool = [gem_primary_obs[s]["raw_score"] for s in slow_steps_ge]
    slow_strict_la_pool = [gem_primary_obs[s]["luck_adjusted_score"] for s in slow_steps_ge]

    fast_day_raw_pool = [gem_primary_obs[s]["raw_score"] for s in fast_day_le]
    fast_day_la_pool = [gem_primary_obs[s]["luck_adjusted_score"] for s in fast_day_le]
    slow_day_raw_pool = [gem_primary_obs[s]["raw_score"] for s in slow_day_gt]
    slow_day_la_pool = [gem_primary_obs[s]["luck_adjusted_score"] for s in slow_day_gt]

    ext8_raw_pool = [gem_ext8_obs[s]["raw_score"] for s in OBSERVED_EXT8_SEEDS]
    ext8_la_pool = [gem_ext8_obs[s]["luck_adjusted_score"] for s in OBSERVED_EXT8_SEEDS]
    ext8_raw_mean = sum(ext8_raw_pool) / 8.0
    ext8_la_mean = sum(ext8_la_pool) / 8.0

    scenarios = [
        _build_scenario(
            scenario_id="baseline_primary30",
            label="Primary headline (seeds 0-29, authoritative)",
            seeds=PRIMARY_SEEDS,
            raw_f=[gem_primary_obs[s]["raw_score"] for s in PRIMARY_SEEDS],
            raw_s=[sol_obs[s]["raw_score"] for s in PRIMARY_SEEDS],
            la_f=[gem_primary_obs[s]["luck_adjusted_score"] for s in PRIMARY_SEEDS],
            la_s=[sol_obs[s]["luck_adjusted_score"] for s in PRIMARY_SEEDS],
            observed_n=30,
            imputed_n=0,
            imputation_rule="None (complete 30/30 primary cohort)",
        ),
        _build_scenario(
            scenario_id="s1_observed_pool38",
            label="Scenario 1: Observed n=38 pool (0-29 + ext8)",
            seeds=POOLED38_SEEDS,
            raw_f=[obs38_raw_map[s] for s in POOLED38_SEEDS],
            raw_s=[sol_obs[s]["raw_score"] for s in POOLED38_SEEDS],
            la_f=[obs38_la_map[s] for s in POOLED38_SEEDS],
            la_s=[sol_obs[s]["luck_adjusted_score"] for s in POOLED38_SEEDS],
            observed_n=38,
            imputed_n=0,
            imputation_rule="Complete-case pool on 38 observed seeds (22 unobserved omitted)",
        ),
        _pool60(
            scenario_id="s2_primary_mean_continuation",
            label="Scenario 2: Primary-mean continuation (0-29 mean on 22 unobserved)",
            imp_raw={s: prim_raw_mean for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: prim_la_mean for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc=(
                f"Impute 0-29 primary mean ({_fsign(prim_raw_mean)} raw, "
                f"{_fsign(prim_la_mean)} luck-adj.) on all 22 unobserved seeds"
            ),
            donor_pools_raw={s: prim_raw_pool for s in UNOBSERVED_EXT22_SEEDS},
            donor_pools_la={s: prim_la_pool for s in UNOBSERVED_EXT22_SEEDS},
        ),
        _pool60(
            scenario_id="s3a_stratified_steps_median",
            label="Scenario 3a: Solver-steps-stratified imputation (median steps <= 72 vs > 72)",
            imp_raw={
                s: (
                    st_steps["primary_fast_gemini_raw"]
                    if sol_obs[s]["total_steps"] <= med_steps_0to29
                    else st_steps["primary_slow_gemini_raw"]
                )
                for s in UNOBSERVED_EXT22_SEEDS
            },
            imp_la={
                s: (
                    st_steps["primary_fast_gemini_la"]
                    if sol_obs[s]["total_steps"] <= med_steps_0to29
                    else st_steps["primary_slow_gemini_la"]
                )
                for s in UNOBSERVED_EXT22_SEEDS
            },
            rule_desc="Match each unobserved seed to 0-29 fast (steps <= 72, n=16) or slow (steps > 72, n=14) stratum",
            donor_pools_raw={
                s: (fast_steps_raw_pool if sol_obs[s]["total_steps"] <= med_steps_0to29 else slow_steps_raw_pool)
                for s in UNOBSERVED_EXT22_SEEDS
            },
            donor_pools_la={
                s: (fast_steps_la_pool if sol_obs[s]["total_steps"] <= med_steps_0to29 else slow_steps_la_pool)
                for s in UNOBSERVED_EXT22_SEEDS
            },
        ),
        _pool60(
            scenario_id="s3b_stratified_day_median",
            label="Scenario 3b: Solver-day-stratified imputation (median day <= 9 vs > 9)",
            imp_raw={
                s: (
                    st_day["primary_fast_gemini_raw"]
                    if sol_obs[s]["horizon_day"] <= med_day_0to29
                    else st_day["primary_slow_gemini_raw"]
                )
                for s in UNOBSERVED_EXT22_SEEDS
            },
            imp_la={
                s: (
                    st_day["primary_fast_gemini_la"]
                    if sol_obs[s]["horizon_day"] <= med_day_0to29
                    else st_day["primary_slow_gemini_la"]
                )
                for s in UNOBSERVED_EXT22_SEEDS
            },
            rule_desc="Match each unobserved seed to 0-29 fast (day <= 9, n=19) or slow (day > 9, n=11) stratum",
            donor_pools_raw={
                s: (fast_day_raw_pool if sol_obs[s]["horizon_day"] <= med_day_0to29 else slow_day_raw_pool)
                for s in UNOBSERVED_EXT22_SEEDS
            },
            donor_pools_la={
                s: (fast_day_la_pool if sol_obs[s]["horizon_day"] <= med_day_0to29 else slow_day_la_pool)
                for s in UNOBSERVED_EXT22_SEEDS
            },
        ),
        _pool60(
            scenario_id="s4a_conservative_slow_steps_gt72",
            label="Scenario 4a: Quota-truncation conservative (0-29 slow steps > 72 on all 22)",
            imp_raw={s: st_steps["primary_slow_gemini_raw"] for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: st_steps["primary_slow_gemini_la"] for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc=(
                f"Impute 0-29 slow-solver half (steps > 72, n={st_steps['primary_slow_n']}: "
                f"{_fsign(st_steps['primary_slow_gemini_raw'])} raw, "
                f"{_fsign(st_steps['primary_slow_gemini_la'])} luck-adj.) on all 22 unobserved"
            ),
            donor_pools_raw={s: slow_steps_raw_pool for s in UNOBSERVED_EXT22_SEEDS},
            donor_pools_la={s: slow_steps_la_pool for s in UNOBSERVED_EXT22_SEEDS},
        ),
        _pool60(
            scenario_id="s4a_strict_slow_steps_ge72",
            label="Scenario 4a-alt: Quota-truncation conservative strict (0-29 steps >= 72 on all 22)",
            imp_raw={s: st_steps_strict["primary_slow_gemini_raw"] for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: st_steps_strict["primary_slow_gemini_la"] for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc=(
                f"Impute 0-29 slow-or-median half (steps >= 72, n={st_steps_strict['primary_slow_n']}: "
                f"{_fsign(st_steps_strict['primary_slow_gemini_raw'])} raw, "
                f"{_fsign(st_steps_strict['primary_slow_gemini_la'])} luck-adj.) on all 22 unobserved"
            ),
            donor_pools_raw={s: slow_strict_raw_pool for s in UNOBSERVED_EXT22_SEEDS},
            donor_pools_la={s: slow_strict_la_pool for s in UNOBSERVED_EXT22_SEEDS},
        ),
        _pool60(
            scenario_id="s4b_optimistic_ext8_mean",
            label="Scenario 4b: Optimistic continuation (ext8 mean on all 22)",
            imp_raw={s: ext8_raw_mean for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: ext8_la_mean for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc=(
                f"Impute observed ext8 mean ({_fsign(ext8_raw_mean)} raw, "
                f"{_fsign(ext8_la_mean)} luck-adj.) on all 22 unobserved seeds"
            ),
            donor_pools_raw={s: ext8_raw_pool for s in UNOBSERVED_EXT22_SEEDS},
            donor_pools_la={s: ext8_la_pool for s in UNOBSERVED_EXT22_SEEDS},
        ),
        _pool60(
            scenario_id="s4c_manski_lower_abstain_zero",
            label="Scenario 4c: Manski lower bound (abstain = 0.000 on all 22)",
            imp_raw={s: 0.0 for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: 0.0 for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc="All 22 unobserved episodes abstain without accusing (score = 0.000, luck-adj. = 0.000)",
        ),
        _pool60(
            scenario_id="s4d_manski_lower_wrong_minus1",
            label="Scenario 4d: Manski worst-case lower bound (wrong = -1.000 on all 22)",
            imp_raw={s: -1.0 for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: -1.0 for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc="All 22 unobserved episodes accuse an innocent at P=0.0 (score = -1.000, luck-adj. = -1.000)",
        ),
        _pool60(
            scenario_id="s4e_manski_upper_solver_v",
            label="Scenario 4e: Manski solver-V upper bound (V_solver(s) at P=1.0 on all 22)",
            imp_raw={s: sol_obs[s]["company_value_v"] for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: sol_obs[s]["company_value_v"] for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc="Each unobserved seed achieves solver stopping company value V_solver(s) with P(mole)=1.0",
        ),
        _pool60(
            scenario_id="s4f_manski_upper_unit_v",
            label="Scenario 4f: Manski algebraic support ceiling (V = 1.000 on all 22)",
            imp_raw={s: 1.0 for s in UNOBSERVED_EXT22_SEEDS},
            imp_la={s: 1.0 for s in UNOBSERVED_EXT22_SEEDS},
            rule_desc="Theoretical game support maximum (day-1 zero-cost accusation V = 1.000 at P=1.0 on all 22)",
        ),
    ]

    per_seed_30to59: list[dict[str, Any]] = []
    for seed in EXT_ALL_SEEDS:
        sr = sol_obs[seed]
        if seed in G1_SEEDS:
            status = "observed_g1"
        elif seed in OBSERVED_EXT8_SEEDS:
            status = "observed_fleet"
        else:
            status = "unobserved"
        gr = gem_ext8_obs.get(seed)
        per_seed_30to59.append({
            "seed": seed,
            "status": status,
            "solver_raw": sr["raw_score"],
            "solver_luck_adjusted": sr["luck_adjusted_score"],
            "solver_accuse_day": sr["accuse_day"],
            "solver_final_day": sr["final_day"],
            "solver_steps": sr["total_steps"],
            "solver_canaries": sr["canary_count"],
            "solver_company_v": sr["company_value_v"],
            "solver_p_accused": sr["p_accused"],
            "solver_correct": sr["correct"],
            "solver_abstained": sr["abstained"],
            "steps_stratum": "fast" if sr["total_steps"] <= med_steps_0to29 else "slow",
            "day_stratum": "fast" if sr["horizon_day"] <= med_day_0to29 else "slow",
            "gemini_raw": gr["raw_score"] if gr is not None else None,
            "gemini_luck_adjusted": gr["luck_adjusted_score"] if gr is not None else None,
            "gemini_accuse_day": gr["accuse_day"] if gr is not None else None,
            "gemini_steps": gr["total_steps"] if gr is not None else None,
            "gemini_canaries": gr["canary_count"] if gr is not None else None,
            "gemini_p_accused": gr["p_accused"] if gr is not None else None,
        })

    return {
        "schema_version": "v1.4-ext30to59-selection-sensitivity-1",
        "provenance": {
            "tiers_version": "v1.4",
            "tier": "hard",
            "frontier_agent": CARBON_AGENT,
            "solver_agent": SOLVER_AGENT,
            "committed_ext_seeds_present": comm_ext_seeds,
            "fleet_ext_seeds_present": [int(ep["seed"]) for ep in fleet_eps],
            "dedup_ext8_seeds": OBSERVED_EXT8_SEEDS,
            "unobserved_ext22_seeds": UNOBSERVED_EXT22_SEEDS,
            "seed34_g1_precedence": {
                "kept_source": "committed_g1",
                "g1_final_day": gem_ext8_obs[34]["final_day"],
                "g1_raw_score": gem_ext8_obs[34]["raw_score"],
                "g1_luck_adjusted_score": gem_ext8_obs[34]["luck_adjusted_score"],
                "g1_steps": gem_ext8_obs[34]["total_steps"],
                "fleet_final_day": gem_fleet34_obs["final_day"] if gem_fleet34_obs else 8,
                "fleet_raw_score": gem_fleet34_obs["raw_score"] if gem_fleet34_obs else 0.82,
                "fleet_luck_adjusted_score": (
                    gem_fleet34_obs["luck_adjusted_score"] if gem_fleet34_obs else 0.183
                ),
                "fleet_steps": gem_fleet34_obs["total_steps"] if gem_fleet34_obs else 83,
            },
        },
        "solver_cohorts": solver_cohorts,
        "gemini_cohorts": gemini_cohorts,
        "obs8_vs_unobs22": obs_vs_unobs_metrics,
        "g1_exact_pair_test": g1_exact_pair_test,
        "stratification": stratification,
        "scenarios": scenarios,
        "scenarios_by_id": {sc["id"]: sc for sc in scenarios},
        "per_seed_30to59": per_seed_30to59,
    }


def _validate_invariants(data: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    sc_obs8 = data["solver_cohorts"]["observed_ext8"]
    sc_unobs22 = data["solver_cohorts"]["unobserved_ext22"]
    sc_all30 = data["solver_cohorts"]["ext30to59_all"]

    if sc_obs8["n"] != 8 or sc_unobs22["n"] != 22 or sc_all30["n"] != 30:
        errs.append("unexpected cohort counts in 30-59 split")

    for key in (
        "raw_mean",
        "luck_adjusted_mean",
        "horizon_day_mean",
        "steps_mean",
        "canary_mean",
        "accuracy",
        "company_value_v_mean",
    ):
        weighted = (8.0 * sc_obs8[key] + 22.0 * sc_unobs22[key]) / 30.0
        if abs(weighted - sc_all30[key]) > 1e-12:
            errs.append(f"weighted 8+22 != 30 identity failed for {key}: {weighted} vs {sc_all30[key]}")

    if sc_obs8["abstention_count"] + sc_unobs22["abstention_count"] != sc_all30["abstention_count"]:
        errs.append("abstention count sum mismatch across obs8 + unobs22")

    by_id = data["scenarios_by_id"]
    la_order = [
        "s4d_manski_lower_wrong_minus1",
        "s4c_manski_lower_abstain_zero",
        "s4a_conservative_slow_steps_gt72",
        "s4a_strict_slow_steps_ge72",
        "s2_primary_mean_continuation",
        "s3a_stratified_steps_median",
        "s4b_optimistic_ext8_mean",
        "s4e_manski_upper_solver_v",
        "s4f_manski_upper_unit_v",
    ]
    for prev_id, next_id in zip(la_order, la_order[1:]):
        prev_v = by_id[prev_id]["luck_adjusted"]["gemini_mean"]
        next_v = by_id[next_id]["luck_adjusted"]["gemini_mean"]
        if not (prev_v < next_v):
            errs.append(f"luck-adjusted monotonicity failed: {prev_id} ({prev_v}) >= {next_id} ({next_v})")

    for sc in data["scenarios"]:
        for side in ("raw", "luck_adjusted"):
            blk = sc[side]
            if not (blk["ratio_lo"] <= blk["ratio"] + 1e-12 and blk["ratio"] <= blk["ratio_hi"] + 1e-12):
                errs.append(f"{sc['id']}.{side}: ratio outside bootstrap 95% CI")
    return errs


def _fsign(val: float, nd: int = 3) -> str:
    return f"{val:+.{nd}f}"


def _fnum(val: float, nd: int = 3) -> str:
    return f"{val:.{nd}f}"


def _fpct(val: float, nd: int = 1) -> str:
    return f"{100.0 * val:.{nd}f}%"


def _fci_pct(lo: float, hi: int | float) -> str:
    return f"[{100.0 * lo:.0f}%, {100.0 * hi:.0f}%]"


def render_markdown(data: dict[str, Any]) -> str:
    sc_sol = data["solver_cohorts"]
    sc_gem = data["gemini_cohorts"]
    cmp_m = data["obs8_vs_unobs22"]
    g1_pair = data["g1_exact_pair_test"]
    strat = data["stratification"]
    by_id = data["scenarios_by_id"]

    prim = by_id["baseline_primary30"]
    s1 = by_id["s1_observed_pool38"]
    s2 = by_id["s2_primary_mean_continuation"]
    s3a = by_id["s3a_stratified_steps_median"]
    s3b = by_id["s3b_stratified_day_median"]
    s4a = by_id["s4a_conservative_slow_steps_gt72"]
    s4a_alt = by_id["s4a_strict_slow_steps_ge72"]
    s4b = by_id["s4b_optimistic_ext8_mean"]
    s4c = by_id["s4c_manski_lower_abstain_zero"]
    s4d = by_id["s4d_manski_lower_wrong_minus1"]
    s4e = by_id["s4e_manski_upper_solver_v"]
    s4f = by_id["s4f_manski_upper_unit_v"]

    obs8_s = sc_sol["observed_ext8"]
    unobs22_s = sc_sol["unobserved_ext22"]
    g1_s = sc_sol["g1_observed2"]
    g1_u_s = sc_sol["g1_unobserved28"]
    all30_s = sc_sol["ext30to59_all"]
    prim30_s = sc_sol["primary0to29"]
    all60_s = sc_sol["pooled0to59_all"]

    st_steps = strat["steps_le_median"]
    st_strict = strat["steps_lt_median"]
    st_day = strat["day_le_median"]
    s34_info = data["provenance"]["seed34_g1_precedence"]

    per_seed_map = {row["seed"]: row for row in data["per_seed_30to59"]}
    gem_ext8_c = sc_gem["observed_ext8"]
    s38 = per_seed_map[38]
    s32 = per_seed_map[32]
    max_pp_delta = max(abs(sc["luck_adjusted"]["ratio"] - prim["luck_adjusted"]["ratio"]) for sc in (s2, s3a, s3b)) * 100.0

    lines: list[str] = []
    add = lines.append

    add(H1 + "v1.4 Hard Extension (Seeds 30-59): Partial-Completion Selection and Sensitivity Audit")
    add("")
    add(H2 + "1. Scope, Non-Primary Headline Rule, and Provenance")
    add("")
    add(
        "This report audits partial-completion selection bias and bounds full-cohort `n=60` (`0-59`) outcomes for "
        "`opencode:google/gemini-4-carbon` on rules `v1.4` `hard`, directly testing the quota-truncation caveat "
        "documented in [`docs/reports/gap.md`](gap.md) (\"Under quota pressure, episodes that complete may be the "
        "shorter ones\"). Every number in this report is computed deterministically with `0` API calls by "
        "[`scripts/analyze_ext30to59_selection.py`](../../scripts/analyze_ext30to59_selection.py) and verified in "
        "[`tests/test_ext30to59_selection_sensitivity.py`](../../tests/test_ext30to59_selection_sensitivity.py)."
    )
    add("")
    add(H3 + "Non-primary caveat (primary `0-29` headline unchanged)")
    add("")
    add(
        f"- **Authoritative `v1.4` `hard` headline (`n=30`, seeds `0-29`) is unchanged:** "
        f"`{_fsign(prim['raw']['gemini_mean'])} +/- {_fnum(prim['raw']['gemini_ci'])}` vs reference solver "
        f"`{_fsign(prim['raw']['solver_mean'])} +/- {_fnum(prim['raw']['solver_ci'])}` "
        f"(paired diff `{_fsign(prim['raw']['diff'])} +/- {_fnum(prim['raw']['diff_ci'])}`), giving "
        f"**`{_fpct(prim['raw']['ratio'], 0)} {_fci_pct(prim['raw']['ratio_lo'], prim['raw']['ratio_hi'])}`** raw "
        f"(`{_fpct(prim['raw']['ratio'], 1)}`) and "
        f"**`{_fpct(prim['luck_adjusted']['ratio'], 0)} {_fci_pct(prim['luck_adjusted']['ratio_lo'], prim['luck_adjusted']['ratio_hi'])}`** "
        f"luck-adjusted (`{_fpct(prim['luck_adjusted']['ratio'], 1)}`, "
        f"`{_fsign(prim['luck_adjusted']['gemini_mean'])}` vs `{_fsign(prim['luck_adjusted']['solver_mean'])}`) in "
        "[`data/runs/committed/v1.4/paired_table_gemini.md`](../../data/runs/committed/v1.4/paired_table_gemini.md) and "
        "[`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md)."
    )
    add(
        "- **Why `30-59` remains exploratory:** Only `8/30` extension seeds (`[30, 34, 37, 42, 45, 48, 57, 58]`) "
        "completed valid replay-verified OpenCode episodes before shared `gemini-4-carbon` quota cutoffs, leaving "
        "`22/30` seeds (`[31, 32, 33, 35, 36, 38, 39, 40, 41, 43, 44, 46, 47, 49, 50, 51, 52, 53, 54, 55, 56, 59]`) "
        "unobserved. Per the pre-registered extension rule in [`docs/reports/gap.md`](gap.md), incomplete extension "
        "shards never replace the `n=30` primary row."
    )
    add("")
    add(H3 + "Input files and Seed 34 G1 precedence")
    add("")
    add(
        "- **Reference solver (`n=60`, seeds `0-59`):** "
        "[`data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl) (`0-19`), "
        "[`data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl) (`20-29`), and "
        "[`data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl`](../../data/runs/committed/v1.4/reference/solver-hard-seeds30to59/episodes.jsonl) (`30-59`)."
    )
    add(
        "- **Gemini primary (`n=30`, seeds `0-29`):** "
        "[`data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl)."
    )
    add(
        "- **Gemini extension (`n=8` deduplicated seeds `[30, 34, 37, 42, 45, 48, 57, 58]`):** combined from "
        "[`data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) "
        f"(`G1` seeds `[34, 37]` on `justSilas`, or all `8` deduplicated seeds when PR {HASH}3 `v14-runs` is merged) and "
        "[`results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/hard/episodes.jsonl) "
        "(`7` fleet seeds `[30, 34, 42, 45, 48, 57, 58]`). On overlapping seed `34`, committed `G1` precedence holds "
        f"(`day {s34_info['g1_final_day']}`, `{s34_info['g1_steps']}` steps, raw `{_fsign(s34_info['g1_raw_score'])}`, "
        f"luck-adjusted `{_fsign(s34_info['g1_luck_adjusted_score'])}` kept over fleet `day {s34_info['fleet_final_day']}`, "
        f"`{s34_info['fleet_steps']}` steps, raw `{_fsign(s34_info['fleet_raw_score'])}`, "
        f"luck-adjusted `{_fsign(s34_info['fleet_luck_adjusted_score'])}`; trajectory comparison in "
        "[`docs/reports/frontier_ext30to59_trajectories.md`](frontier_ext30to59_trajectories.md))."
    )
    add("")
    add(H2 + "2. Selection Audit on Seeds 30-59: Observed 8 vs Unobserved 22 on Solver Observables")
    add("")
    add(
        "Because the deterministic reference solver ran to completion on all `30` seeds `30-59` (`0` missing episodes), "
        "its per-seed observables measure intrinsic world difficulty and investigation duration without missingness. "
        "Luck-adjusted scores (`P*V - (1-P)` on accused episodes, `0.0` on abstentions) are computed via "
        "[`canary/analysis/accuse.py`](../../canary/analysis/accuse.py)."
    )
    add("")
    add(H3 + "Table 2A: Reference solver observables across extension and baseline cohorts")
    add("")
    add(
        "| Solver cohort | `n` | Raw score +/- 95% CI | Luck-adj. +/- 95% CI | Mean accuse day (accused) | Mean horizon day (all) | Mean steps +/- 95% CI (median) | Mean canaries +/- 95% CI | Accuracy (`ok/n`) | Abstain / wrong |"
    )
    add("|---|---:|---|---|---:|---:|---|---|---|---:|")
    for cohort in (g1_s, g1_u_s, obs8_s, unobs22_s, all30_s, prim30_s, all60_s):
        add(
            f"| {cohort['label']} | {cohort['n']} | `{_fsign(cohort['raw_mean'])} +/- {_fnum(cohort['raw_ci'])}` | "
            f"`{_fsign(cohort['luck_adjusted_mean'])} +/- {_fnum(cohort['luck_adjusted_ci'])}` | "
            f"`{_fnum(cohort['accuse_day_mean'], 2)}` (`{cohort['accuse_day_n']}`) | "
            f"`{_fnum(cohort['horizon_day_mean'], 2)}` | "
            f"`{_fnum(cohort['steps_mean'], 2)} +/- {_fnum(cohort['steps_ci'], 2)}` (`{cohort['steps_median']:.1f}`) | "
            f"`{_fnum(cohort['canary_mean'], 2)} +/- {_fnum(cohort['canary_ci'], 2)}` | "
            f"`{_fpct(cohort['accuracy'], 1)}` (`{cohort['correct_count']}/{cohort['n']}`) | "
            f"`{cohort['abstention_count']}` / `{cohort['wrong_count']}` |"
        )
    add("")
    add(H3 + "Table 2B: Two-sample balance test (`ext8` `n=8` minus `unobs22` `n=22`, 10,000 permutations, `rng_seed=0`)")
    add("")
    add("| Solver observable | Observed `ext8` (`n=8`) | Unobserved `unobs22` (`n=22`) | Diff (`obs8 - unobs22`) | Two-sided permutation `p` |")
    add("|---|---:|---:|---:|---:|")
    metric_rows = [
        ("Raw score", "raw_score", 3),
        ("Luck-adjusted score (`P*V - (1-P)`)", "luck_adjusted_score", 3),
        ("Accuse day (accused episodes: `8` vs `21`)", "accuse_day_accused_only", 2),
        ("Horizon day (all episodes, abstention = `21`)", "horizon_day", 2),
        ("Total solver steps", "total_steps", 2),
        ("Canaries planted", "canary_count", 2),
        ("Company value `V` at end", "company_value_v", 3),
        ("Solver accuracy", "accuracy", 3),
        ("Solver abstention rate", "abstention_rate", 3),
    ]
    for title, mkey, nd in metric_rows:
        m = cmp_m[mkey]
        add(
            f"| {title} | `{_fnum(m['obs8_mean'], nd)}` | `{_fnum(m['unobs22_mean'], nd)}` | "
            f"`{_fsign(m['diff_obs_minus_unobs'], nd)}` | `{_fnum(m['perm_p_two_sided'], 4)}` |"
        )
    add("")
    add(H3 + "Findings on the `gap.md` quota-truncation caveat")
    add("")
    add(
        f"1. **Why the caveat held sharply on `justSilas` `G1` (`n=2`, seeds `[34, 37]`):** Under single-bucket sequential "
        f"execution in `G1` (where `31` attempts hit `infra:provider_quota`), the two completed worlds (`34` and `37`) "
        f"averaged `{_fnum(g1_pair['g1_solver_steps_mean'], 1)}` solver steps and day `{_fnum(g1_pair['g1_solver_day_mean'], 1)}` "
        f"(solver raw `{_fsign(g1_pair['g1_solver_raw_mean'])}`). Across all `C(30, 2) = {g1_pair['total_pairs']}` seed pairs "
        f"in `30-59`, only `{g1_pair['pairs_le_g1_steps']}/{g1_pair['total_pairs']}` (`{_fpct(g1_pair['frac_le_g1_steps'], 1)}`) "
        f"are at or below `{_fnum(g1_pair['g1_solver_steps_mean'], 1)}` solver steps (and `{g1_pair['pairs_le_g1_day']}/{g1_pair['total_pairs']}` "
        f"= `{_fpct(g1_pair['frac_le_g1_day'], 1)}` at or below day `{_fnum(g1_pair['g1_solver_day_mean'], 1)}`), directly "
        "confirming Silas's duration-selection warning for `n=2`."
    )
    add(
        f"2. **How the 6 fleet shard-head seeds changed world-level balance in `ext8` (`n=8`):** Because the fleet run "
        "partitioned `30-59` into parallel worker seed ranges (`[30, 42, 45, 48, 57, 58]` completed at shard heads), "
        f"the combined `8` observed seeds are slightly *longer* and *harder* for the solver than the `22` unobserved seeds: "
        f"`{_fnum(obs8_s['steps_mean'], 2)}` vs `{_fnum(unobs22_s['steps_mean'], 2)}` steps "
        f"(`{_fsign(cmp_m['total_steps']['diff_obs_minus_unobs'], 2)}`, `p = {_fnum(cmp_m['total_steps']['perm_p_two_sided'], 4)}`), "
        f"accuse day `{_fnum(obs8_s['accuse_day_mean'], 2)}` vs `{_fnum(unobs22_s['accuse_day_mean'], 2)}` "
        f"(`{_fsign(cmp_m['accuse_day_accused_only']['diff_obs_minus_unobs'], 2)}`, `p = {_fnum(cmp_m['accuse_day_accused_only']['perm_p_two_sided'], 4)}`), "
        f"canaries `{_fnum(obs8_s['canary_mean'], 2)}` vs `{_fnum(unobs22_s['canary_mean'], 2)}`, and solver luck-adjusted score "
        f"`{_fsign(obs8_s['luck_adjusted_mean'])}` vs `{_fsign(unobs22_s['luck_adjusted_mean'])}` "
        f"(`{_fsign(cmp_m['luck_adjusted_score']['diff_obs_minus_unobs'])}`, `p = {_fnum(cmp_m['luck_adjusted_score']['perm_p_two_sided'], 4)}`)."
    )
    add(
        "3. **Why sensitivity bounds are still required (`22/30` missing):** World-level solver balance does not rule out "
        "agent-side truncation within fixed seeds (e.g., an interview-heavy Gemini trajectory hitting provider quota on a "
        f"seed the solver finishes quickly), nor does `n={gem_ext8_c['n']}` (`{_fpct(gem_ext8_c['accuracy'], 1)}` Gemini "
        f"accuracy, `{_fsign(gem_ext8_c['raw_mean'])}` raw, `{_fsign(gem_ext8_c['luck_adjusted_mean'])}` luck-adjusted vs "
        f"`{_fsign(sc_gem['primary0to29']['raw_mean'])}` raw, `{_fsign(sc_gem['primary0to29']['luck_adjusted_mean'])}` "
        "luck-adjusted on `0-29`) eliminate small-sample variance. Moreover, the sole solver abstention in `30-59` "
        f"(`seed 38`: `{s38['solver_steps']}` solver steps, day `{s38['solver_final_day']}`, `{s38['solver_canaries']}` "
        f"canaries, `V = {_fnum(s38['solver_company_v'], 3)}`) and one solver wrong accusation "
        f"(`seed 32`: `{_fsign(s32['solver_raw'])}` raw, `{_fsign(s32['solver_luck_adjusted'])}` luck-adjusted) sit in "
        "the `22` unobserved seeds."
    )
    add("")
    add(H2 + "3. Primary `0-29` Solver-Duration Strata Used for Imputation")
    add("")
    add(
        f"On the complete `0-29` primary cohort (`n=30`), median solver step count is `{strat['median_solver_steps_0to29']:.1f}` "
        f"steps and median solver accuse/horizon day is `{strat['median_solver_day_0to29']:.1f}`:"
    )
    add("")
    add(
        "| `0-29` stratification rule | Fast `n` / Slow `n` (`0-29`) | Fast Gemini raw / luck-adj. | Slow Gemini raw / luck-adj. | Fast solver raw / luck-adj. | Slow solver raw / luck-adj. | `unobs22` fast / slow |"
    )
    add("|---|---|---|---:|---|---|---:|")
    for sblk in (st_steps, st_strict, st_day):
        add(
            f"| `{sblk['threshold']}` | `{sblk['primary_fast_n']}` / `{sblk['primary_slow_n']}` | "
            f"`{_fsign(sblk['primary_fast_gemini_raw'])}` / `{_fsign(sblk['primary_fast_gemini_la'])}` | "
            f"`{_fsign(sblk['primary_slow_gemini_raw'])}` / `{_fsign(sblk['primary_slow_gemini_la'])}` | "
            f"`{_fsign(sblk['primary_fast_solver_raw'])}` / `{_fsign(sblk['primary_fast_solver_la'])}` | "
            f"`{_fsign(sblk['primary_slow_solver_raw'])}` / `{_fsign(sblk['primary_slow_solver_la'])}` | "
            f"`{sblk['unobs22_fast_n']}` / `{sblk['unobs22_slow_n']}` |"
        )
    add("")
    add(
        f"Why luck-adjusted Gemini score drops sharply on slow-solver worlds (`{_fsign(st_steps['primary_fast_gemini_la'])}` "
        f"-> `{_fsign(st_steps['primary_slow_gemini_la'])}` on `steps > 72`) while raw score slightly rises "
        f"(`{_fsign(st_steps['primary_fast_gemini_raw'])}` -> `{_fsign(st_steps['primary_slow_gemini_raw'])}` on `steps > 72`, "
        f"vs `{_fsign(st_strict['primary_fast_gemini_raw'])}` -> `{_fsign(st_strict['primary_slow_gemini_raw'])}` when "
        "boundary seed `15` at `72` steps is grouped into `steps >= 72`): on `0-29`, two disclosed 5% canary fingerprint "
        "flips (`seeds 1, 26` at `60` solver steps, `P >= 0.95`, `-1.000` raw) fell in the fast stratum while two "
        "negative-EV day-21 gambles (`seeds 5, 23` in `steps > 72`) happened to guess right (`+0.160`, `+0.230` raw vs "
        "`-0.408`, `-0.444` luck-adjusted; see [`docs/reports/failure_analysis_v1.4.md`](failure_analysis_v1.4.md)). "
        f"We report both `steps > 72` (`n={st_steps['primary_slow_n']}`) and `steps >= 72` "
        f"(`n={st_strict['primary_slow_n']}`) in Scenario 4 so neither realization quirk is hidden."
    )
    add("")
    add(H2 + "4. Pooled `n=60` (`0-59`) Sensitivity Scenarios and Manski Bounds")
    add("")
    add(
        "All `n=60` scenarios keep the `38` observed episodes (`0-29` primary + `8` deduplicated `ext8` seeds) fixed, "
        f"pair every seed `0-59` against the exact `n=60` reference solver (`{_fsign(all60_s['raw_mean'])}` raw "
        f"[`{_fnum(all60_s['raw_mean'], 4)}`], `{_fsign(all60_s['luck_adjusted_mean'])}` luck-adjusted "
        f"[`{_fnum(all60_s['luck_adjusted_mean'], 4)}`]), and compute `10,000`-resample paired bootstrap 95% CIs (`rng_seed=0`, matching "
        "[`results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled38.md`](../../results/frontier_replication/v1.4/opencode-gemini-4-carbon-ext/paired_table_pooled38.md)). "
        "For empirical imputation rules (`Scenarios 2, 3a, 3b, 4a, 4b`), we also report two-stage donor-resampling bootstrap "
        "CIs (`rng_seed=0`) that draw i.i.d. `0-29` / `ext8` donors on each resampled unobserved seed so plug-in mean "
        "imputation never artificially narrows confidence intervals."
    )
    add("")
    add(H3 + "Table 4A: Deterministic sensitivity battery (`raw` and `luck-adjusted`)")
    add("")
    add(
        "| Scenario | `n` (`obs`+`imp`) | Gemini raw | Solver raw | Raw diff | Raw ratio [95% CI] | Gemini luck-adj. | Solver luck-adj. | Luck-adj. diff | Luck-adj. ratio [95% CI] |"
    )
    add("|---|---:|---:|---:|---:|---|---:|---:|---:|---|")
    for sc in (prim, s1, s2, s3a, s3b, s4a, s4a_alt, s4b, s4c, s4d, s4e, s4f):
        r = sc["raw"]
        la = sc["luck_adjusted"]
        add(
            f"| {sc['label']} | `{sc['n']}` (`{sc['observed_n']}+{sc['imputed_n']}`) | "
            f"`{_fsign(r['gemini_mean'])}` | `{_fsign(r['solver_mean'])}` | `{_fsign(r['diff'])}` | "
            f"`{_fpct(r['ratio'], 1)}` `{_fci_pct(r['ratio_lo'], r['ratio_hi'])}` | "
            f"`{_fsign(la['gemini_mean'])}` | `{_fsign(la['solver_mean'])}` | `{_fsign(la['diff'])}` | "
            f"**`{_fpct(la['ratio'], 1)}`** `{_fci_pct(la['ratio_lo'], la['ratio_hi'])}` |"
        )
    add("")
    add(H3 + "Table 4B: Donor-resampling paired bootstrap 95% CIs (`rng_seed=0`, `B=10,000`) on empirical imputations")
    add("")
    add(
        "| Empirical imputation scenario (`n=60`) | Imputation law on 22 unobserved seeds | Plug-in raw ratio [95% CI] | Donor-boot raw [95% CI] | Plug-in luck-adj. ratio [95% CI] | Donor-boot luck-adj. [95% CI] |"
    )
    add("|---|---|---|---|---|---|")
    for sc in (s2, s3a, s3b, s4a, s4a_alt, s4b):
        r = sc["raw"]
        la = sc["luck_adjusted"]
        add(
            f"| {sc['label']} | {sc['imputation_rule']} | "
            f"`{_fpct(r['ratio'], 1)}` `{_fci_pct(r['ratio_lo'], r['ratio_hi'])}` | "
            f"`{_fci_pct(r['donor_boot_ratio_lo'], r['donor_boot_ratio_hi'])}` | "
            f"`{_fpct(la['ratio'], 1)}` `{_fci_pct(la['ratio_lo'], la['ratio_hi'])}` | "
            f"**`{_fci_pct(la['donor_boot_ratio_lo'], la['donor_boot_ratio_hi'])}`** |"
        )
    add("")
    add(H3 + "Key conclusions from the sensitivity battery")
    add("")
    add(
        f"1. **Every baseline and solver-stratified `n=60` continuation confirms a ~25-27% frontier shortfall:** "
        f"Primary-mean continuation (`Scenario 2`: `{_fpct(s2['raw']['ratio'], 1)}` raw, `{_fpct(s2['luck_adjusted']['ratio'], 1)}` "
        f"luck-adjusted), solver-steps stratification (`Scenario 3a`: `{_fpct(s3a['raw']['ratio'], 1)}` raw, "
        f"`{_fpct(s3a['luck_adjusted']['ratio'], 1)}` luck-adjusted; donor-boot CI "
        f"`{_fci_pct(s3a['luck_adjusted']['donor_boot_ratio_lo'], s3a['luck_adjusted']['donor_boot_ratio_hi'])}`), and "
        f"solver-day stratification (`Scenario 3b`: `{_fpct(s3b['raw']['ratio'], 1)}` raw, "
        f"`{_fpct(s3b['luck_adjusted']['ratio'], 1)}` luck-adjusted; donor-boot CI "
        f"`{_fci_pct(s3b['luck_adjusted']['donor_boot_ratio_lo'], s3b['luck_adjusted']['donor_boot_ratio_hi'])}`) all sit within "
        f"`{max_pp_delta:.1f}` percentage points of the `0-29` luck-adjusted headline (`{_fpct(prim['luck_adjusted']['ratio'], 1)}`) and exclude "
        "luck-adjusted parity (`100%`) under both plug-in and donor-resampling bootstrap CIs."
    )
    add(
        f"2. **Adversarial quota-truncation adjustment widens the luck-adjusted gap further:** If all `22` unobserved seeds "
        f"behaved like the slow-solver half of `0-29` (`Scenario 4a`), pooled `n=60` luck-adjusted performance drops to "
        f"**`{_fpct(s4a['luck_adjusted']['ratio'], 1)}` `{_fci_pct(s4a['luck_adjusted']['ratio_lo'], s4a['luck_adjusted']['ratio_hi'])}`** "
        f"(`steps > 72`, `{_fsign(s4a['luck_adjusted']['diff'])}` V/seed) or "
        f"**`{_fpct(s4a_alt['luck_adjusted']['ratio'], 1)}` `{_fci_pct(s4a_alt['luck_adjusted']['ratio_lo'], s4a_alt['luck_adjusted']['ratio_hi'])}`** "
        f"(`steps >= 72`, `{_fpct(s4a_alt['raw']['ratio'], 1)}` raw)."
    )
    add(
        f"3. **Even optimistic `ext8` continuation and solver-`V` upper bounds stay below `100%` point parity:** Extrapolating "
        f"`ext8`'s `8/8` streak (`{_fsign(gem_ext8_c['raw_mean'])}` raw, `{_fsign(gem_ext8_c['luck_adjusted_mean'])}` luck-adjusted) "
        f"across all `22` unobserved seeds (`Scenario 4b`) yields "
        f"`{_fpct(s4b['raw']['ratio'], 1)}` raw and `{_fpct(s4b['luck_adjusted']['ratio'], 1)}` luck-adjusted, while granting "
        f"Gemini the solver's stopping `V` at `P=1.0` on every unobserved seed (`Scenario 4e`) yields "
        f"`{_fpct(s4e['raw']['ratio'], 1)}` raw and `{_fpct(s4e['luck_adjusted']['ratio'], 1)}` luck-adjusted. On the downside, "
        f"Manski no-assumption bounds span `{_fpct(s4c['luck_adjusted']['ratio'], 1)}` (all-abstain `0.0`) down to "
        f"`{_fpct(s4d['luck_adjusted']['ratio'], 1)}` (all-wrong `-1.0`), with only the unachievable day-1 zero-cost "
        f"`V = 1.0` algebraic support ceiling (`Scenario 4f`: `{_fpct(s4f['luck_adjusted']['ratio'], 1)}`) exceeding parity."
    )
    add("")
    add(H2 + "5. Complete Per-Seed Extension Table (`30-59`, `n=30`)")
    add("")
    add(
        "| Seed | Status | Solver raw | Solver luck-adj. | Solver day (`fin`) | Solver steps (`stratum`) | Solver canaries | Solver `V` | Solver `P(acc)` | Gemini raw | Gemini luck-adj. | Gemini day / steps |"
    )
    add("|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|")
    for row in data["per_seed_30to59"]:
        s_day_txt = (
            f"abstain (`{row['solver_final_day']}`)"
            if row["solver_abstained"]
            else f"`d{row['solver_accuse_day']}` (`{row['solver_final_day']}`)"
        )
        s_p_txt = "-" if row["solver_p_accused"] is None else f"`{_fnum(row['solver_p_accused'], 3)}`"
        if row["gemini_raw"] is None:
            g_raw_txt = "-"
            g_la_txt = "-"
            g_ds_txt = "-"
        else:
            g_raw_txt = f"`{_fsign(row['gemini_raw'])}`"
            g_la_txt = f"`{_fsign(row['gemini_luck_adjusted'])}`"
            g_ds_txt = f"`d{row['gemini_accuse_day']}` / `{row['gemini_steps']}`"
        add(
            f"| {row['seed']} | `{row['status']}` | `{_fsign(row['solver_raw'])}` | `{_fsign(row['solver_luck_adjusted'])}` | "
            f"{s_day_txt} | `{row['solver_steps']}` (`{row['steps_stratum']}`) | `{row['solver_canaries']}` | "
            f"`{_fnum(row['solver_company_v'], 3)}` | {s_p_txt} | {g_raw_txt} | {g_la_txt} | {g_ds_txt} |"
        )
    add("")
    add(H2 + "6. Keyless Reproduction Commands")
    add("")
    add("```bash")
    add("CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_ext30to59_selection.py --check")
    add("CANARY_ALLOW_DEV=1 PYTHONPATH=. python scripts/analyze_ext30to59_selection.py --json")
    add("CANARY_ALLOW_DEV=1 PYTHONPATH=. pytest -q tests/test_ext30to59_selection_sensitivity.py")
    add("```")
    add("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless selection and sensitivity audit for v1.4 gemini-4-carbon hard extension seeds 30-59."
    )
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--committed-ext-jsonl", default=None)
    ap.add_argument("--fleet-ext-jsonl", default=None)
    ap.add_argument("--report-md", default=None)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--write-md", action="store_true")
    args = ap.parse_args(argv)

    repo_path = Path(args.repo).resolve()
    report_path = Path(args.report_md).resolve() if args.report_md else (repo_path / DEFAULT_REPORT_REL)

    data = analyze_selection(
        repo=repo_path,
        committed_ext_jsonl=args.committed_ext_jsonl,
        fleet_ext_jsonl=args.fleet_ext_jsonl,
    )
    inv_errs = _validate_invariants(data)
    rendered_md = render_markdown(data)

    if EM_DASH in rendered_md or EN_DASH in rendered_md:
        inv_errs.append("rendered markdown contains forbidden unicode em/en dash")

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
            if EM_DASH in actual_md or EN_DASH in actual_md:
                check_errs.append(f"unicode em/en dash present in {report_path}")
            if actual_md != rendered_md:
                check_errs.append(f"{report_path} does not match deterministic render_markdown(data)")
        if args.as_json:
            print(json.dumps({"ok": not check_errs, "errors": check_errs, "data": data}, indent=2))
        elif check_errs:
            for err in check_errs:
                print(f"[FAIL] {err}")
        else:
            print(
                "PASS: ext30-59 selection & sensitivity audit verified "
                f"(obs8={data['provenance']['dedup_ext8_seeds']}, scenarios={len(data['scenarios'])})"
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
