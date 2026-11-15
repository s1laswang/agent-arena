from __future__ import annotations

import argparse
import json
import math
import random
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.analysis.gap import load_runs, mean_ci
from canary.analysis.tags import to_result
from scripts.v16_eval_matrix import (
    FORBIDDEN_OUTPUT_KEYS,
    KEY_PATTERNS,
    episode_posterior_and_luck,
    parse_seed_spec,
)

TOL = 1e-12
FORBIDDEN_DASHES = ("\u2014", "\u2013")


def _check_hygiene(obj: Any, *, allow_nan: bool = False) -> None:
    def _walk(val: Any, path: str) -> None:
        if isinstance(val, dict):
            for k, v in val.items():
                ks = str(k)
                if ks in FORBIDDEN_OUTPUT_KEYS:
                    raise ValueError(f"forbidden key {ks!r} at {path}.{ks}")
                _walk(v, f"{path}.{ks}")
        elif isinstance(val, list):
            for idx, item in enumerate(val):
                _walk(item, f"{path}[{idx}]")
        elif isinstance(val, float) and not allow_nan and not math.isfinite(val):
            raise ValueError(f"non-finite float at {path}: {val!r}")

    _walk(obj, "root")
    dumped = json.dumps(obj, sort_keys=True, allow_nan=allow_nan)
    for rx in KEY_PATTERNS:
        if rx.search(dumped):
            raise ValueError("secret key pattern detected in JSON input")


def _req_float(raw: dict[str, Any], key: str) -> float:
    if key not in raw or raw[key] is None:
        raise ValueError(f"missing required numeric field {key!r}")
    val = float(raw[key])
    if not math.isfinite(val):
        raise ValueError(f"non-finite float for {key!r}: {val!r}")
    return val


def _opt_float(val: Any) -> float | None:
    if val is None:
        return None
    f = float(val)
    return f if math.isfinite(f) else None


def _opt_ci_pair(val: Any) -> tuple[float | None, float | None]:
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        return None, None
    return _opt_float(val[0]), _opt_float(val[1])


def _boot_ratio_ci(
    num: list[float],
    den: list[float],
    n_resamples: int = 10000,
    rng_seed: int = 0,
) -> tuple[float | None, float | None]:
    if len(num) != len(den) or len(num) < 2:
        return None, None
    n = len(num)
    rng = random.Random(rng_seed)
    vals: list[float] = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        den_m = sum(den[i] for i in idx) / n
        if den_m > 0.0:
            vals.append((sum(num[i] for i in idx) / n) / den_m)
    if not vals:
        return None, None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[max(0, int(0.975 * len(vals)) - 1)]


def _extract_model_id(model_str: str) -> str:
    m = str(model_str or "gemini-4-carbon").strip()
    if m.startswith("opencode:"):
        m = m.split(":", 1)[1]
    if "/" in m:
        m = m.split("/", 1)[1]
    if ":" in m:
        m = m.split(":", 1)[1]
    return m or "gemini-4-carbon"


def _harness_label(harness: str, fake: bool = False) -> str:
    base = "OpenCode over MCP" if harness == "opencode" else "in-process"
    return f"{base} [fake stub]" if fake else base


def _seed_span_label(seeds: list[int]) -> str:
    if not seeds:
        return "unknown"
    if len(seeds) == 1:
        return str(seeds[0])
    if seeds == list(range(seeds[0], seeds[-1] + 1)):
        return f"{seeds[0]}-{seeds[-1]}"
    return ",".join(str(s) for s in seeds)


def _fmt_signed(val: float, digits: int = 3) -> str:
    clean = 0.0 if abs(val) < TOL else float(val)
    return f"{clean:+.{digits}f}"


def _fmt_pm_ci(mean: float, ci_half: float | None, digits: int = 3) -> str:
    if ci_half is None or not math.isfinite(ci_half):
        return _fmt_signed(mean, digits)
    half = 0.0 if abs(ci_half) < TOL else abs(float(ci_half))
    return f"{_fmt_signed(mean, digits)} \u00b1 {half:.{digits}f}"


def _fmt_pct(ratio: float, decimals: int = 0) -> str:
    pct = 0.0 if abs(ratio) < TOL else 100.0 * float(ratio)
    if decimals <= 0:
        r = round(pct)
        return f"{0 if r == 0 else r}%"
    return f"{pct:.{decimals}f}%"


def _fmt_ratio_with_ci(
    ratio: float,
    lo: float | None,
    hi: float | None,
    decimals: int = 0,
) -> str:
    head = _fmt_pct(ratio, decimals=decimals)
    if lo is None or hi is None:
        return head
    return f"{head} [{_fmt_pct(lo, decimals=decimals)}, {_fmt_pct(hi, decimals=decimals)}]"


def _fmt_ratio_cell(
    stats: dict[str, Any],
    *,
    bold_primary: bool = False,
    decimals: int = 0,
) -> str:
    primary = _fmt_ratio_with_ci(
        stats["gemini_vs_solver_ratio"],
        stats["ratio_lo"],
        stats["ratio_hi"],
        decimals=decimals,
    )
    if bold_primary:
        primary = f"**{primary}**"
    luck_ratio = stats.get("luck_adj_ratio")
    if luck_ratio is None:
        return primary
    luck_part = _fmt_ratio_with_ci(
        luck_ratio,
        stats.get("luck_lo"),
        stats.get("luck_hi"),
        decimals=decimals,
    )
    return f"{primary}; luck-adjusted {luck_part}"


def load_v16_result(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("v16 JSON payload must be a JSON object")
    _check_hygiene(raw, allow_nan=False)

    variant = str(raw.get("variant") or "").strip()
    if not variant:
        raise ValueError("missing required field 'variant' in v16 JSON")
    provider_spec = str(
        raw.get("provider_spec") or (variant if ":" in variant else f"v16:{variant}")
    ).strip()
    tier = str(raw.get("tier") or "hard").strip()
    harness = str(raw.get("harness") or "opencode").strip()
    model = str(raw.get("model") or "opencode:google/gemini-4-carbon").strip()
    fake = bool(raw.get("fake", False))

    if "n_seeds" not in raw or raw["n_seeds"] is None:
        raise ValueError("missing required field 'n_seeds' in v16 JSON")
    n_seeds = int(raw["n_seeds"])
    if n_seeds <= 0:
        raise ValueError(f"n_seeds must be positive, got {n_seeds}")

    per_seed = raw.get("per_seed") if isinstance(raw.get("per_seed"), list) else []
    raw_seeds = raw.get("seeds")
    if isinstance(raw_seeds, list) and raw_seeds:
        seeds = [int(s) for s in raw_seeds]
    elif per_seed and all(isinstance(r, dict) and "seed" in r for r in per_seed):
        seeds = [int(r["seed"]) for r in per_seed]
    else:
        raise ValueError("missing 'seeds' list in v16 JSON")
    if len(seeds) != n_seeds:
        raise ValueError(f"len(seeds)={len(seeds)} does not match n_seeds={n_seeds}")

    gemini_mean = _req_float(raw, "gemini_mean")
    solver_mean = _req_float(raw, "solver_mean")
    solver_v14_mean = _opt_float(raw.get("solver_v14_mean"))
    gemini_vs_solver_ratio = _req_float(raw, "gemini_vs_solver_ratio")
    ratio_lo, ratio_hi = _opt_ci_pair(raw.get("gemini_vs_solver_ratio_ci_95"))

    luck_adj_mean = _opt_float(raw.get("luck_adj_mean"))
    solver_luck_adj_mean = _opt_float(raw.get("solver_luck_adj_mean"))
    luck_adj_ratio = _opt_float(raw.get("luck_adj_ratio"))
    luck_lo, luck_hi = _opt_ci_pair(raw.get("luck_adj_ratio_ci_95"))

    do_nothing_mean = _req_float(raw, "do_nothing_mean")
    do_nothing_v14_mean = _opt_float(raw.get("do_nothing_v14_mean"))
    stop_early_mean = _req_float(raw, "stop_early_mean")
    stop_early_v14_mean = _opt_float(raw.get("stop_early_v14_mean"))

    solver_calibration_diff = _opt_float(raw.get("solver_calibration_diff"))
    solver_calibration_max_abs_diff = _opt_float(raw.get("solver_calibration_max_abs_diff"))

    replay_verified_count = (
        int(raw["replay_verified_count"])
        if raw.get("replay_verified_count") is not None
        else None
    )
    replay_verified_rate = _opt_float(raw.get("replay_verified_rate"))

    if len(per_seed) == n_seeds and all(isinstance(r, dict) and "gemini_score" in r for r in per_seed):
        _, gemini_ci_half = mean_ci([float(r["gemini_score"]) for r in per_seed])
    elif raw.get("gemini_ci_half") is not None:
        gemini_ci_half = _opt_float(raw.get("gemini_ci_half"))
    else:
        gem_lo, gem_hi = _opt_ci_pair(raw.get("gemini_ci_95"))
        gemini_ci_half = ((gem_hi - gem_lo) / 2.0) if (gem_lo is not None and gem_hi is not None) else None

    if len(per_seed) == n_seeds and all(isinstance(r, dict) and "solver_score" in r for r in per_seed):
        _, solver_ci_half = mean_ci([float(r["solver_score"]) for r in per_seed])
    else:
        solver_ci_half = _opt_float(raw.get("solver_ci_half"))

    if len(per_seed) == n_seeds and all(isinstance(r, dict) and "do_nothing_score" in r for r in per_seed):
        _, dn_ci_half = mean_ci([float(r["do_nothing_score"]) for r in per_seed])
    else:
        dn_ci_half = 0.0 if abs(do_nothing_mean) <= TOL else None

    if len(per_seed) == n_seeds and all(isinstance(r, dict) and "stop_early_score" in r for r in per_seed):
        _, se_ci_half = mean_ci([float(r["stop_early_score"]) for r in per_seed])
    else:
        se_ci_half = 0.0 if abs(stop_early_mean) <= TOL else None

    raw_gates = raw.get("gates") if isinstance(raw.get("gates"), dict) else {}

    return {
        "variant": variant,
        "provider_spec": provider_spec,
        "tier": tier,
        "harness": harness,
        "model": model,
        "model_id": _extract_model_id(model),
        "fake": fake,
        "n_seeds": n_seeds,
        "seeds": seeds,
        "gemini_mean": gemini_mean,
        "gemini_ci_half": gemini_ci_half,
        "solver_mean": solver_mean,
        "solver_ci_half": solver_ci_half,
        "solver_v14_mean": solver_v14_mean,
        "gemini_vs_solver_ratio": gemini_vs_solver_ratio,
        "ratio_lo": ratio_lo,
        "ratio_hi": ratio_hi,
        "luck_adj_mean": luck_adj_mean,
        "solver_luck_adj_mean": solver_luck_adj_mean,
        "luck_adj_ratio": luck_adj_ratio,
        "luck_lo": luck_lo,
        "luck_hi": luck_hi,
        "accuracy": _opt_float(raw.get("accuracy")),
        "accusation_rate": _opt_float(raw.get("accusation_rate")),
        "mean_accuse_day": _opt_float(raw.get("mean_accuse_day")),
        "mean_p_accused": _opt_float(raw.get("mean_p_accused")),
        "do_nothing_mean": do_nothing_mean,
        "do_nothing_v14_mean": do_nothing_v14_mean,
        "dn_ci_half": dn_ci_half,
        "stop_early_mean": stop_early_mean,
        "stop_early_v14_mean": stop_early_v14_mean,
        "se_ci_half": se_ci_half,
        "solver_calibration_diff": solver_calibration_diff,
        "solver_calibration_max_abs_diff": solver_calibration_max_abs_diff,
        "replay_verified_count": replay_verified_count,
        "replay_verified_rate": replay_verified_rate,
        "raw_gates": dict(raw_gates),
        "top_solver_calibration_zero": raw.get("solver_calibration_zero"),
        "top_replay_verified": raw.get("replay_verified"),
        "per_seed": per_seed,
    }


def load_v14_from_json(
    path: Path,
    *,
    tier: str = "hard",
    harness: str = "opencode",
    model_id: str = "gemini-4-carbon",
) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        _check_hygiene(raw, allow_nan=True)
        expected_agent = (
            f"gemini:{model_id}" if harness == "inproc" else f"opencode:google/{model_id}"
        )
        frontier_rows = [
            r
            for r in raw
            if isinstance(r, dict)
            and r.get("tier") == tier
            and r.get("agent") == expected_agent
            and "alternative (NOT the headline)" not in str(r.get("label", ""))
        ]
        if not frontier_rows:
            raise ValueError(
                f"no v1.4 baseline row for tier={tier!r} agent={expected_agent!r} in {path}"
            )
        frow = frontier_rows[0]
        solver_rows = [
            r
            for r in raw
            if isinstance(r, dict) and r.get("tier") == tier and r.get("agent") == "solver"
        ]
        srow = solver_rows[0] if solver_rows else {}
        seeds = [int(s) for s in frow.get("seeds", [])]
        n_seeds = int(frow["n"])
        return {
            "source": str(path),
            "tier": tier,
            "harness": harness,
            "model_id": model_id,
            "n_seeds": n_seeds,
            "seeds": seeds,
            "gemini_mean": _req_float(frow, "mean"),
            "gemini_ci_half": _opt_float(frow.get("ci")),
            "solver_mean": _req_float(frow, "solver_same_seeds"),
            "solver_ci_half": _opt_float(srow.get("ci")) if srow.get("seeds") == frow.get("seeds") else None,
            "gemini_vs_solver_ratio": _req_float(frow, "ratio"),
            "ratio_lo": _opt_float(frow.get("ratio_lo")),
            "ratio_hi": _opt_float(frow.get("ratio_hi")),
            "luck_adj_mean": _opt_float(frow.get("post_expected")),
            "solver_luck_adj_mean": _opt_float(frow.get("solver_post_expected")),
            "luck_adj_ratio": _opt_float(frow.get("post_expected_ratio")),
            "luck_lo": _opt_float(frow.get("post_expected_lo")),
            "luck_hi": _opt_float(frow.get("post_expected_hi")),
        }

    if isinstance(raw, dict) and "gemini_vs_solver_ratio" in raw:
        parsed = load_v16_result(
            {
                "variant": raw.get("variant", "v0_v14_control"),
                "tier": raw.get("tier", tier),
                "harness": raw.get("harness", harness),
                "model": raw.get("model", f"opencode:google/{model_id}"),
                "n_seeds": raw["n_seeds"],
                "seeds": raw.get("seeds") or list(range(int(raw["n_seeds"]))),
                "gemini_mean": raw["gemini_mean"],
                "gemini_ci_95": raw.get("gemini_ci_95"),
                "gemini_ci_half": raw.get("gemini_ci_half"),
                "solver_mean": raw["solver_mean"],
                "solver_ci_half": raw.get("solver_ci_half"),
                "gemini_vs_solver_ratio": raw["gemini_vs_solver_ratio"],
                "gemini_vs_solver_ratio_ci_95": raw.get("gemini_vs_solver_ratio_ci_95"),
                "luck_adj_mean": raw.get("luck_adj_mean"),
                "solver_luck_adj_mean": raw.get("solver_luck_adj_mean"),
                "luck_adj_ratio": raw.get("luck_adj_ratio"),
                "luck_adj_ratio_ci_95": raw.get("luck_adj_ratio_ci_95"),
                "do_nothing_mean": raw.get("do_nothing_mean", 0.0),
                "stop_early_mean": raw.get("stop_early_mean", 0.0),
                "per_seed": raw.get("per_seed", []),
            }
        )
        parsed["source"] = str(path)
        return parsed

    raise ValueError(f"unsupported v1.4 baseline JSON format in {path}")


def load_committed_v14_baseline(
    committed_root: Path,
    *,
    tier: str = "hard",
    seeds: list[int],
    harness: str = "opencode",
    model_id: str = "gemini-4-carbon",
) -> dict[str, Any]:
    if not seeds:
        raise ValueError("v1.4 baseline seeds must be non-empty")
    v14_dir = Path(committed_root) / "v1.4"
    frontier_sub = f"inproc-{model_id}" if harness == "inproc" else f"opencode-{model_id}"
    expected_agent = f"gemini:{model_id}" if harness == "inproc" else f"opencode:google/{model_id}"

    frontier_dir = v14_dir / frontier_sub
    ref_dir = v14_dir / "reference"
    if not frontier_dir.is_dir():
        raise FileNotFoundError(f"committed v1.4 frontier directory not found: {frontier_dir}")
    if not ref_dir.is_dir():
        raise FileNotFoundError(f"committed v1.4 reference directory not found: {ref_dir}")

    frontier_by_seed = {
        int(e["seed"]): e
        for e in load_runs(frontier_dir)
        if e.get("tier") == tier
        and e.get("agent") == expected_agent
        and (e.get("meta") or {}).get("valid") is not False
    }
    solver_by_seed = {
        int(e["seed"]): e
        for e in load_runs(ref_dir)
        if e.get("tier") == tier and e.get("agent") == "solver"
    }

    missing_f = [s for s in seeds if s not in frontier_by_seed]
    missing_s = [s for s in seeds if s not in solver_by_seed]
    if missing_f or missing_s:
        raise ValueError(
            f"committed v1.4 {tier} baseline missing seeds (frontier={missing_f}, solver={missing_s})"
        )

    gem_eps = [frontier_by_seed[s] for s in seeds]
    sol_eps = [solver_by_seed[s] for s in seeds]

    gem_scores = [float(e["score"]) for e in gem_eps]
    sol_scores = [float(e["score"]) for e in sol_eps]
    gem_mean, gem_ci = mean_ci(gem_scores)
    sol_mean, sol_ci = mean_ci(sol_scores)
    if sol_mean <= 0.0:
        raise ValueError(f"committed v1.4 solver mean is non-positive: {sol_mean}")
    ratio = gem_mean / sol_mean
    ratio_lo, ratio_hi = _boot_ratio_ci(gem_scores, sol_scores, n_resamples=10000, rng_seed=0)

    gem_luck = [episode_posterior_and_luck(to_result(e))[2] for e in gem_eps]
    sol_luck = [episode_posterior_and_luck(to_result(e))[2] for e in sol_eps]
    luck_mean = sum(gem_luck) / len(gem_luck)
    sol_luck_mean = sum(sol_luck) / len(sol_luck)
    luck_ratio = (luck_mean / sol_luck_mean) if sol_luck_mean > 0.0 else None
    luck_lo, luck_hi = (
        _boot_ratio_ci(gem_luck, sol_luck, n_resamples=10000, rng_seed=0)
        if luck_ratio is not None
        else (None, None)
    )

    return {
        "source": str(frontier_dir),
        "tier": tier,
        "harness": harness,
        "model_id": model_id,
        "n_seeds": len(seeds),
        "seeds": list(seeds),
        "gemini_mean": gem_mean,
        "gemini_ci_half": gem_ci,
        "solver_mean": sol_mean,
        "solver_ci_half": sol_ci,
        "gemini_vs_solver_ratio": ratio,
        "ratio_lo": ratio_lo,
        "ratio_hi": ratio_hi,
        "luck_adj_mean": luck_mean,
        "solver_luck_adj_mean": sol_luck_mean,
        "luck_adj_ratio": luck_ratio,
        "luck_lo": luck_lo,
        "luck_hi": luck_hi,
    }


def evaluate_ship_gates(v16: dict[str, Any], v14: dict[str, Any]) -> dict[str, Any]:
    raw_gates = v16.get("raw_gates") or {}
    per_seed = v16.get("per_seed") or []
    n_seeds = int(v16["n_seeds"])

    v16_ratio = float(v16["gemini_vs_solver_ratio"])
    v14_ratio = float(v14["gemini_vs_solver_ratio"])
    ratio_below_v14 = bool(
        math.isfinite(v16_ratio) and math.isfinite(v14_ratio) and v16_ratio < v14_ratio
    )

    dn_ok = abs(float(v16["do_nothing_mean"])) <= TOL
    if v16.get("do_nothing_v14_mean") is not None:
        dn_ok = dn_ok and abs(float(v16["do_nothing_v14_mean"])) <= TOL
    if "do_nothing_zero" in raw_gates:
        dn_ok = dn_ok and (raw_gates["do_nothing_zero"] is True)
    if per_seed and any("do_nothing_score" in r for r in per_seed if isinstance(r, dict)):
        dn_ok = dn_ok and all(
            abs(float(r["do_nothing_score"])) <= TOL
            for r in per_seed
            if isinstance(r, dict) and "do_nothing_score" in r
        )

    se_ok = abs(float(v16["stop_early_mean"])) <= TOL
    if v16.get("stop_early_v14_mean") is not None:
        se_ok = se_ok and abs(float(v16["stop_early_v14_mean"])) <= TOL
    if "stop_early_zero" in raw_gates:
        se_ok = se_ok and (raw_gates["stop_early_zero"] is True)
    if per_seed and any("stop_early_score" in r for r in per_seed if isinstance(r, dict)):
        se_ok = se_ok and all(
            abs(float(r["stop_early_score"])) <= TOL
            for r in per_seed
            if isinstance(r, dict) and "stop_early_score" in r
        )

    raw_cal = (
        raw_gates["solver_calibration_zero"]
        if "solver_calibration_zero" in raw_gates
        else v16.get("top_solver_calibration_zero")
    )
    cal_diff = v16.get("solver_calibration_diff")
    cal_max = v16.get("solver_calibration_max_abs_diff")
    has_cal_signal = (raw_cal is not None) or (cal_diff is not None)
    cal_ok = bool(has_cal_signal)
    if raw_cal is not None:
        cal_ok = cal_ok and (raw_cal is True)
    if cal_diff is not None:
        cal_ok = cal_ok and (abs(float(cal_diff)) <= TOL)
    if cal_max is not None:
        cal_ok = cal_ok and (abs(float(cal_max)) <= TOL)
    if v16.get("solver_v14_mean") is not None:
        cal_ok = cal_ok and (abs(float(v16["solver_mean"]) - float(v16["solver_v14_mean"])) <= 1e-9)

    raw_rep = (
        raw_gates["replay_verified"]
        if "replay_verified" in raw_gates
        else v16.get("top_replay_verified")
    )
    rep_cnt = v16.get("replay_verified_count")
    rep_rate = v16.get("replay_verified_rate")
    has_rep_signal = (raw_rep is not None) or (rep_cnt is not None) or (rep_rate is not None)
    rep_ok = bool(has_rep_signal)
    if raw_rep is not None:
        rep_ok = rep_ok and (raw_rep is True)
    if rep_cnt is not None:
        rep_ok = rep_ok and (int(rep_cnt) == n_seeds)
    if rep_rate is not None:
        rep_ok = rep_ok and (abs(float(rep_rate) - 1.0) <= TOL)
    if per_seed and any("replay_verified" in r for r in per_seed if isinstance(r, dict)):
        rep_ok = rep_ok and all(
            r["replay_verified"] is True
            for r in per_seed
            if isinstance(r, dict) and "replay_verified" in r
        )

    gates = {
        "ratio_below_v14": bool(ratio_below_v14),
        "do_nothing_zero": bool(dn_ok),
        "stop_early_zero": bool(se_ok),
        "solver_calibration_zero": bool(cal_ok),
        "replay_verified": bool(rep_ok),
    }
    failed = [name for name, passed in gates.items() if not passed]
    return {
        **gates,
        "failed_gates": failed,
        "ship_ready": len(failed) == 0,
    }


def render_markdown_snippet(
    v16: dict[str, Any],
    v14: dict[str, Any],
    gate_report: dict[str, Any],
) -> str:
    ship = bool(gate_report["ship_ready"])
    spec = v16["provider_spec"]
    tier = v16["tier"]
    n16 = int(v16["n_seeds"])
    n14 = int(v14["n_seeds"])
    seeds16_lbl = _seed_span_label(v16["seeds"])
    seeds14_lbl = _seed_span_label(v14["seeds"])
    h_lbl_16 = _harness_label(v16["harness"], fake=bool(v16.get("fake", False)))
    h_lbl_14 = _harness_label(v14["harness"], fake=False)
    model_id = v16["model_id"]

    v16_r = float(v16["gemini_vs_solver_ratio"])
    v14_r = float(v14["gemini_vs_solver_ratio"])
    pct_decimals = (
        1
        if round(100.0 * v16_r) == round(100.0 * v14_r) and abs(v16_r - v14_r) > 1e-6
        else 0
    )

    same_solver_row = (
        v16["seeds"] == v14["seeds"]
        and abs(float(v16["solver_mean"]) - float(v14["solver_mean"])) <= 1e-9
    )

    solver_ci_16 = v16["solver_ci_half"] if v16["solver_ci_half"] is not None else v14.get("solver_ci_half")
    v16_solver_str = _fmt_pm_ci(v16["solver_mean"], solver_ci_16)
    v14_solver_str = _fmt_pm_ci(v14["solver_mean"], v14.get("solver_ci_half"))
    v16_gem_str = _fmt_pm_ci(v16["gemini_mean"], v16["gemini_ci_half"])
    v14_gem_str = _fmt_pm_ci(v14["gemini_mean"], v14.get("gemini_ci_half"))
    dn_str = _fmt_pm_ci(v16["do_nothing_mean"], v16["dn_ci_half"])
    se_str = _fmt_pm_ci(v16["stop_early_mean"], v16["se_ci_half"])

    dn_ratio_pct = (
        _fmt_pct(v16["do_nothing_mean"] / v16["solver_mean"])
        if v16["solver_mean"] > 0.0 and abs(v16["do_nothing_mean"]) > TOL
        else "0%"
    )
    se_ratio_pct = (
        _fmt_pct(v16["stop_early_mean"] / v16["solver_mean"])
        if v16["solver_mean"] > 0.0 and abs(v16["stop_early_mean"]) > TOL
        else "0%"
    )

    lines: list[str] = []
    if ship:
        lines.append(f"\x23\x23 Social bias layer (opt-in V1.6, `CANARY_PROVIDER={spec}`)")
    else:
        lines.append(
            f"\x23\x23\x23 V1.6 social bias candidate (negative / non-ship result, `CANARY_PROVIDER={spec}`)"
        )
    lines.append("")
    lines.append("| agent | score \u00b1 95% CI | % of solver [95% CI] | n |")
    lines.append("|---|---:|---:|---:|")

    if same_solver_row:
        lines.append(
            f"| reference solver (paired seeds {seeds16_lbl}, v1.4 = {spec}) | {v16_solver_str} | 100% | {n16} |"
        )
    else:
        lines.append(
            f"| reference solver (v1.4, seeds {seeds14_lbl}) | {v14_solver_str} | 100% | {n14} |"
        )
        lines.append(
            f"| reference solver ({spec}, seeds {seeds16_lbl}) | {v16_solver_str} | 100% | {n16} |"
        )

    v14_cell = _fmt_ratio_cell(v14, bold_primary=False, decimals=pct_decimals)
    lines.append(
        f"| {model_id}, {h_lbl_14} (v1.4 baseline, seeds {seeds14_lbl}) | {v14_gem_str} | {v14_cell} | {n14} |"
    )

    if ship:
        v16_cell = _fmt_ratio_cell(v16, bold_primary=True, decimals=pct_decimals)
        lines.append(
            f"| **{model_id}, {h_lbl_16} ({spec}, seeds {seeds16_lbl})** | **{v16_gem_str}** | {v16_cell} | {n16} |"
        )
    else:
        v16_cell = _fmt_ratio_cell(v16, bold_primary=False, decimals=pct_decimals)
        lines.append(
            f"| {model_id}, {h_lbl_16} ({spec}, seeds {seeds16_lbl}) | {v16_gem_str} | {v16_cell} | {n16} |"
        )

    lines.append(f"| do_nothing ({spec}) | {dn_str} | {dn_ratio_pct} | {n16} |")
    lines.append(
        f"| stop_early (stops on day 1, no accusation, {spec}) | {se_str} | {se_ratio_pct} | {n16} |"
    )
    lines.append("")

    v14_ratio_txt = _fmt_ratio_with_ci(v14_r, v14["ratio_lo"], v14["ratio_hi"], decimals=pct_decimals)
    v16_ratio_txt = _fmt_ratio_with_ci(v16_r, v16["ratio_lo"], v16["ratio_hi"], decimals=pct_decimals)
    cal_diff_val = (
        v16["solver_calibration_diff"]
        if v16["solver_calibration_diff"] is not None
        else (v16["solver_mean"] - (v16["solver_v14_mean"] if v16["solver_v14_mean"] is not None else v16["solver_mean"]))
    )
    cal_diff_txt = _fmt_signed(float(cal_diff_val), digits=3)
    rep_cnt = v16["replay_verified_count"] if v16["replay_verified_count"] is not None else (n16 if gate_report["replay_verified"] else 0)

    luck_clause = ""
    if v14.get("luck_adj_ratio") is not None and v16.get("luck_adj_ratio") is not None:
        luck_clause = (
            f" (luck-adjusted {_fmt_pct(v14['luck_adj_ratio'], decimals=pct_decimals)} "
            f"to {_fmt_pct(v16['luck_adj_ratio'], decimals=pct_decimals)})"
        )

    if ship:
        lines.append(
            f"- **What `{spec}` adds (off by default).** Setting `CANARY_PROVIDER={spec}` injects multi-day "
            f"workplace cognitive biases generated strictly from `PublicDayFacts` with zero access to mole identity. "
            f"Every social message has exact Bayesian likelihood ratio `1`, so the unmodified `v1.4` reference solver "
            f"keeps its exact posterior and policy (`solver_calibration_diff = {cal_diff_txt}`)."
        )
        lines.append(
            f"- **Paired result and honest reading.** On {tier} dev seeds {seeds16_lbl} (`n = {n16}`, "
            f"`{rep_cnt}/{n16}` episodes replay-verified), `{model_id}` ({h_lbl_16}) moves from "
            f"{v14_ratio_txt} of the solver on the committed `v1.4` baseline (`{v14_gem_str}`, seeds {seeds14_lbl}, `n = {n14}`) "
            f"to **{v16_ratio_txt}** (`{v16_gem_str}`) under `{spec}`{luck_clause}, while `do_nothing` (`{dn_str}`) "
            f"and `stop_early` (`{se_str}`) score `0`. `v1.4` (`n = 30`) remains the default environment and "
            f"`CANARY_PROVIDER={spec}` is available as an opt-in social track; see [docs/v16-social-design.md](docs/v16-social-design.md)."
        )
    else:
        failed_csv = ", ".join(gate_report["failed_gates"])
        lines.append(
            f"- **Pre-registered ship gate: NOT PASSED (`{failed_csv}`).** On {tier} dev seeds {seeds16_lbl} "
            f"(`n = {n16}`), `{model_id}` ({h_lbl_16}) reached {v16_ratio_txt} of the solver under "
            f"`CANARY_PROVIDER={spec}` (`{v16_gem_str}`) versus {v14_ratio_txt} on the committed `v1.4` baseline "
            f"(`{v14_gem_str}`, seeds {seeds14_lbl}, `n = {n14}`){luck_clause}, with "
            f"`solver_calibration_diff = {cal_diff_txt}`, `do_nothing = {_fmt_signed(v16['do_nothing_mean'])}`, "
            f"`stop_early = {_fmt_signed(v16['stop_early_mean'])}`, and `{rep_cnt}/{n16}` episodes replay-verified. "
            f"Because all five ship gates did not pass, `v1.4` remains the sole judged environment in `README.md`, "
            f"and `CANARY_PROVIDER={spec}` stays off by default as a documented ablation (`docs/v16-social-design.md`)."
        )

    out_text = "\n".join(lines) + "\n"
    for bad_dash in FORBIDDEN_DASHES:
        if bad_dash in out_text:
            raise AssertionError(f"forbidden dash character {bad_dash!r} in rendered Markdown")
    return out_text


def build_report(
    *,
    v16_json_path: Path,
    v14_json_path: Path | None = None,
    committed_root: Path = REPO_ROOT / "data/runs/committed",
    v14_seeds_spec: str = "0-9",
    v14_harness: str = "auto",
) -> tuple[str, dict[str, Any]]:
    raw_v16 = json.loads(Path(v16_json_path).read_text(encoding="utf-8"))
    v16 = load_v16_result(raw_v16)

    resolved_harness = v16["harness"] if v14_harness == "auto" else v14_harness
    if v14_json_path is not None:
        v14 = load_v14_from_json(
            Path(v14_json_path),
            tier=v16["tier"],
            harness=resolved_harness,
            model_id=v16["model_id"],
        )
    else:
        v14_seeds = (
            list(v16["seeds"])
            if str(v14_seeds_spec).strip().lower() == "match"
            else parse_seed_spec(v14_seeds_spec)
        )
        v14 = load_committed_v14_baseline(
            Path(committed_root),
            tier=v16["tier"],
            seeds=v14_seeds,
            harness=resolved_harness,
            model_id=v16["model_id"],
        )

    gate_report = evaluate_ship_gates(v16, v14)
    markdown = render_markdown_snippet(v16, v14, gate_report)

    summary: dict[str, Any] = {
        "variant": v16["variant"],
        "provider_spec": v16["provider_spec"],
        "tier": v16["tier"],
        "harness": v16["harness"],
        "model": v16["model"],
        "fake": bool(v16["fake"]),
        "v16_seeds": v16["seeds"],
        "v16_n": v16["n_seeds"],
        "v16_gemini_mean": round(float(v16["gemini_mean"]), 6),
        "v16_solver_mean": round(float(v16["solver_mean"]), 6),
        "v16_ratio": round(float(v16["gemini_vs_solver_ratio"]), 6),
        "v16_ratio_ci_95": [
            round(float(v16["ratio_lo"]), 6) if v16["ratio_lo"] is not None else None,
            round(float(v16["ratio_hi"]), 6) if v16["ratio_hi"] is not None else None,
        ],
        "v16_luck_adj_ratio": (
            round(float(v16["luck_adj_ratio"]), 6) if v16["luck_adj_ratio"] is not None else None
        ),
        "v14_source": v14.get("source"),
        "v14_seeds": v14["seeds"],
        "v14_n": v14["n_seeds"],
        "v14_gemini_mean": round(float(v14["gemini_mean"]), 6),
        "v14_solver_mean": round(float(v14["solver_mean"]), 6),
        "v14_ratio": round(float(v14["gemini_vs_solver_ratio"]), 6),
        "v14_ratio_ci_95": [
            round(float(v14["ratio_lo"]), 6) if v14["ratio_lo"] is not None else None,
            round(float(v14["ratio_hi"]), 6) if v14["ratio_hi"] is not None else None,
        ],
        "v14_luck_adj_ratio": (
            round(float(v14["luck_adj_ratio"]), 6) if v14["luck_adj_ratio"] is not None else None
        ),
        "do_nothing_mean": round(float(v16["do_nothing_mean"]), 6),
        "stop_early_mean": round(float(v16["stop_early_mean"]), 6),
        "solver_calibration_diff": (
            round(float(v16["solver_calibration_diff"]), 6)
            if v16["solver_calibration_diff"] is not None
            else None
        ),
        "replay_verified_count": v16["replay_verified_count"],
        "replay_verified_rate": (
            round(float(v16["replay_verified_rate"]), 6)
            if v16["replay_verified_rate"] is not None
            else None
        ),
        "ship_gates": gate_report,
    }
    _check_hygiene(summary, allow_nan=False)
    return markdown, summary


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Render V1.6 README/HISTORY Markdown snippet from v16_eval_matrix JSON and committed v1.4 baseline."
    )
    ap.add_argument("v16_json_pos", nargs="?", default=None)
    ap.add_argument("--v16-json", dest="v16_json", default=None)
    ap.add_argument("--v14-json", dest="v14_json", default=None)
    ap.add_argument("--committed-root", default=str(REPO_ROOT / "data/runs/committed"))
    ap.add_argument("--v14-seeds", default="0-9")
    ap.add_argument("--v14-harness", choices=("auto", "opencode", "inproc"), default="auto")
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--strict-exit", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    v16_target = args.v16_json or args.v16_json_pos
    if not v16_target:
        raise SystemExit("error: --v16-json <path> is required")

    markdown, summary = build_report(
        v16_json_path=Path(v16_target),
        v14_json_path=Path(args.v14_json) if args.v14_json else None,
        committed_root=Path(args.committed_root),
        v14_seeds_spec=args.v14_seeds,
        v14_harness=args.v14_harness,
    )
    sys.stdout.write(markdown)
    if args.out_md:
        out_md = Path(args.out_md)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(markdown, encoding="utf-8")
    if args.out_json:
        out_js = Path(args.out_json)
        out_js.parent.mkdir(parents=True, exist_ok=True)
        out_js.write_text(
            json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    if args.strict_exit and not summary["ship_gates"]["ship_ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
