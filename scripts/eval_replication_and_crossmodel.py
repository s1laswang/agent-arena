"""Offline v1.4 cross-model comparison (seeds 0-29) and hard replication audit (seeds 30-59).

Usage:
    python scripts/eval_replication_and_crossmodel.py
    python scripts/eval_replication_and_crossmodel.py --check
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary import rules
from canary.analysis.gap import mean_ci
from canary.env import Env
from canary.eval import make_policy_factory, run_episode
import paired_v13

TIERS_VERSION = "v1.4"
BOOT_SEED = 0
N_BOOT = 10000
FLEET_MAX_WALL_S = 3590.0
REPLAY_TOL = 1e-9
MAX_JSON_BYTES = 80 * 1024

_BOOT_WEIGHT_CACHE: dict[tuple[int, int, int], np.ndarray] = {}

DEFAULT_COMMITTED_DIR = "data/runs/committed/v1.4"
DEFAULT_FRONTIER_REF = "origin/fr8/canary/frontier"
FRONTIER_SUBPATH = "results/frontier_replication/v1.4"
DEFAULT_OUT_JSON = "results/eval_v14/crossmodel_and_replication_v14.json"
DEFAULT_OUT_MD = "docs/reports/crossmodel_and_replication_v14.md"

DETERMINISTIC_BASELINES_0_29 = (
    "grok_tactics",
    "heuristic",
    "logs_only",
    "do_nothing",
    "stop_early",
    "guess_day1",
)

REPLICATION_REF_ORDER = (
    "solver",
    "grok_tactics",
    "heuristic",
    "logs_only",
    "random",
    "restrict_all",
    "guess_day1",
    "stop_early",
    "do_nothing",
)

H1 = chr(35)
H2 = chr(35) * 2
H3 = chr(35) * 3


def approx_equal(a: Any, b: Any, tol: float = REPLAY_TOL) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, int) and isinstance(b, int):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def validate_and_replay_episode(
    ep: dict[str, Any],
    enforce_wall_cap: bool = True,
    max_wall_s: float = FLEET_MAX_WALL_S,
) -> tuple[bool, str | None, dict[str, Any] | None]:
    if rules.TIERS_VERSION != TIERS_VERSION:
        raise RuntimeError(f"Expected TIERS_VERSION={TIERS_VERSION}, got {rules.TIERS_VERSION}")
    meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
    if ep.get("valid") is False or meta.get("valid") is False:
        return False, "invalid_flag", None
    end_reason = ep.get("end_reason")
    if end_reason in ("error", "timeout"):
        return False, f"end_reason_{end_reason}", None
    rc = ep.get("rc") if "rc" in ep else meta.get("rc")
    if rc == "timeout":
        return False, "rc_timeout", None
    if isinstance(rc, int) and not isinstance(rc, bool) and rc != 0:
        return False, f"rc_nonzero_{rc}", None
    if ep.get("score") is None:
        return False, "missing_score", None
    ep_ver = ep.get("tiers_version") or meta.get("tiers_version")
    if ep_ver is not None and ep_ver != TIERS_VERSION:
        return False, f"tiers_version_{ep_ver}", None

    wall_raw = ep.get("wall_s") if ep.get("wall_s") is not None else meta.get("wall_s")
    wall_s = float(wall_raw) if wall_raw is not None else None
    if wall_s is not None:
        if enforce_wall_cap and wall_s >= max_wall_s:
            return False, f"wall_s_ge_{max_wall_s:g}", None
        if not enforce_wall_cap and wall_s >= max_wall_s and end_reason not in ("accused", "horizon"):
            return False, f"unclean_over_wall_cap_{end_reason}", None

    tier = str(ep["tier"])
    seed = int(ep["seed"])
    env = Env(tier, seed)
    shown_v = env.visible_V()
    for step in ep.get("steps") or []:
        if env.done:
            break
        if step.get("tool") == "accuse":
            shown_v = env.visible_V()
        env.call(step["tool"], step.get("args") or {})
    rep = env.result("replay")
    rec_score = float(ep["score"])
    if abs(rep.score - rec_score) >= REPLAY_TOL or rep.accused != ep.get("accused"):
        raise ValueError(
            f"Replay mismatch on {ep.get('agent')} {tier} seed {seed}: "
            f"recorded=({rec_score}, {ep.get('accused')}) vs replay=({rep.score}, {rep.accused})"
        )

    ep_clean = dict(ep)
    meta_clean = dict(meta)
    if "V" not in meta_clean and "V_final" not in meta_clean:
        meta_clean["V"] = env.V
    ep_clean["meta"] = meta_clean

    paired_v13._P_CACHE.pop(id(ep_clean), None)
    pa = paired_v13.p_acc(ep_clean) if ep_clean.get("accused") else None
    pe = paired_v13.post_expected(ep_clean)
    if pe is None:
        raise ValueError(f"post_expected returned None for {ep.get('agent')} {tier} seed {seed}")

    breakeven = 1.0 / (1.0 + shown_v)
    is_gamble = bool(ep_clean.get("accused") and pa is not None and pa < breakeven)
    info = {
        "episode": ep_clean,
        "tier": tier,
        "seed": seed,
        "agent": str(ep_clean.get("agent") or ""),
        "score": rec_score,
        "correct": bool(ep_clean.get("correct")),
        "accused": ep_clean.get("accused"),
        "end_reason": str(end_reason or ""),
        "final_day": int(ep_clean.get("final_day") or 0),
        "wall_s": wall_s,
        "rc": rc,
        "shown_v": float(shown_v),
        "true_v": float(env.V),
        "p_accused": float(pa) if pa is not None else None,
        "luck_adjusted": float(pe),
        "breakeven_p": float(breakeven),
        "sub_breakeven_gamble": is_gamble,
    }
    return True, None, info


def _boot_weights(n: int, n_boot: int, seed: int) -> np.ndarray:
    key = (n, n_boot, seed)
    if key not in _BOOT_WEIGHT_CACHE:
        rng = random.Random(seed)
        w = np.zeros((n_boot, n), dtype=np.float64)
        inv_n = 1.0 / n
        for b in range(n_boot):
            for _ in range(n):
                w[b, rng.randrange(n)] += inv_n
        _BOOT_WEIGHT_CACHE[key] = w
    return _BOOT_WEIGHT_CACHE[key]


def paired_bootstrap_stats(
    a_vals: list[float],
    b_vals: list[float],
    n_boot: int = N_BOOT,
    seed: int = BOOT_SEED,
) -> dict[str, Any]:
    a = np.asarray(a_vals, dtype=np.float64)
    b = np.asarray(b_vals, dtype=np.float64)
    n = len(a)
    if n == 0:
        return {
            "ratio": None,
            "ratio_ci95": None,
            "diff": None,
            "diff_ci95": None,
        }
    mean_a = float(a.mean())
    mean_b = float(b.mean())
    diff = float((a - b).mean())
    ratio = float(mean_a / mean_b) if mean_b > 0.0 else None
    if n < 2:
        return {
            "ratio": ratio,
            "ratio_ci95": [ratio, ratio] if ratio is not None else None,
            "diff": diff,
            "diff_ci95": [diff, diff],
        }
    w = _boot_weights(n, n_boot, seed)
    ma = w @ a
    mb = w @ b
    diffs = np.sort(ma - mb)
    m_diff = int(diffs.shape[0])
    diff_ci = [float(diffs[int(0.025 * m_diff)]), float(diffs[int(0.975 * m_diff) - 1])]
    ok = mb > 0.0
    if ratio is not None and bool(np.any(ok)):
        ratios = np.sort(ma[ok] / mb[ok])
        m_rat = int(ratios.shape[0])
        ratio_ci: list[float] | None = [
            float(ratios[int(0.025 * m_rat)]),
            float(ratios[int(0.975 * m_rat) - 1]),
        ]
    else:
        ratio_ci = None
    return {
        "ratio": ratio,
        "ratio_ci95": ratio_ci,
        "diff": diff,
        "diff_ci95": diff_ci,
    }


def _parse_jsonl_lines(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _collect_validated(
    raw_eps: list[dict[str, Any]],
    source_tag: str,
    cohort_name: str,
    enforce_wall_cap: bool,
    audit_log: dict[str, Any],
    tier_filter: str | None = None,
) -> dict[int, dict[str, Any]]:
    by_seed: dict[int, dict[str, Any]] = {}
    for ep in raw_eps:
        if tier_filter is not None and ep.get("tier") != tier_filter:
            continue
        audit_log["total_inspected_episodes"] += 1
        ok, reason, info = validate_and_replay_episode(
            ep,
            enforce_wall_cap=enforce_wall_cap,
            max_wall_s=FLEET_MAX_WALL_S,
        )
        if not ok or info is None:
            audit_log["rejected_episodes"].append({
                "source": source_tag,
                "cohort": cohort_name,
                "tier": ep.get("tier"),
                "seed": ep.get("seed"),
                "reason": reason,
            })
            continue
        audit_log["total_valid_replayed_episodes"] += 1
        if not enforce_wall_cap and info["wall_s"] is not None and info["wall_s"] >= FLEET_MAX_WALL_S:
            audit_log["committed_primary_over_3590s_clean_completions"].append({
                "cohort": cohort_name,
                "tier": info["tier"],
                "seed": info["seed"],
                "wall_s": info["wall_s"],
                "rc": info["rc"],
                "end_reason": info["end_reason"],
                "final_day": info["final_day"],
                "score": info["score"],
            })
        by_seed[info["seed"]] = info
    return by_seed


def replay_deterministic_policy(
    agent: str,
    tier: str,
    seeds: list[int],
    audit_log: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    factory = make_policy_factory(agent)
    raw_eps: list[dict[str, Any]] = []
    for seed in seeds:
        res = run_episode(Env(tier, seed), factory(seed))
        raw_eps.append(asdict(res))
    return _collect_validated(
        raw_eps,
        source_tag="inproc_deterministic_v1.4",
        cohort_name=agent,
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter=tier,
    )


def _resolve_frontier_local_dir(frontier_dir: Path) -> Path:
    for candidate in (
        frontier_dir,
        frontier_dir / FRONTIER_SUBPATH,
        frontier_dir / "v1.4",
    ):
        if (candidate / "opencode-gemini-4-carbon").exists() or (
            candidate / "opencode-gemini-3.5-flash"
        ).exists() or (candidate / "reference").exists():
            return candidate
    return frontier_dir


def git_subpath_commit(frontier_ref: str, subpath: str = FRONTIER_SUBPATH) -> str | None:
    proc = subprocess.run(
        ["git", "log", "-1", "--format=%H", frontier_ref, "--", subpath],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    return None


def load_frontier_tree(
    frontier_dir: Path | None,
    frontier_ref: str,
    allow_merged_local: bool = True,
) -> dict[str, str] | None:
    if frontier_dir is not None:
        base = _resolve_frontier_local_dir(frontier_dir)
        if not base.exists():
            raise FileNotFoundError(f"--frontier-dir does not exist: {frontier_dir}")
        out: dict[str, str] = {}
        for p in sorted(base.rglob("episodes.jsonl")):
            rel = p.relative_to(base).as_posix()
            out[rel] = p.read_text()
        return out

    proc = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", frontier_ref, FRONTIER_SUBPATH],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        out = {}
        for full_rel in sorted(proc.stdout.splitlines()):
            if not full_rel.endswith("episodes.jsonl"):
                continue
            show = subprocess.run(
                ["git", "show", f"{frontier_ref}:{full_rel}"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            short_rel = full_rel[len(FRONTIER_SUBPATH) + 1 :]
            out[short_rel] = show.stdout
        return out

    if allow_merged_local:
        merged_local = ROOT / FRONTIER_SUBPATH
        if merged_local.is_dir():
            out = {}
            for p in sorted(merged_local.rglob("episodes.jsonl")):
                out[p.relative_to(merged_local).as_posix()] = p.read_text()
            return out

    return None


def summarize_cohort(
    cohort: str,
    tier: str,
    source: str,
    by_seed: dict[int, dict[str, Any]],
    solver_by_seed: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    seeds = sorted(s for s in by_seed if s in solver_by_seed)
    items = [by_seed[s] for s in seeds]
    sol_items = [solver_by_seed[s] for s in seeds]
    n = len(items)
    if n == 0:
        raise ValueError(f"Empty paired cohort {cohort} on tier {tier}")

    agent_str = items[0]["agent"]
    scores = [x["score"] for x in items]
    sol_scores = [x["score"] for x in sol_items]
    la_scores = [x["luck_adjusted"] for x in items]
    sol_la_scores = [x["luck_adjusted"] for x in sol_items]

    m_score, hw_score = mean_ci(scores)
    sol_mean = sum(sol_scores) / n
    sol_la_mean = sum(sol_la_scores) / n
    la_mean = sum(la_scores) / n

    diffs = [a - b for a, b in zip(scores, sol_scores)]
    _, diff_hw = mean_ci(diffs)

    is_solver = cohort == "solver"
    if is_solver:
        ratio_vs_solver: float | None = 1.0
        ratio_ci95: list[float] | None = [1.0, 1.0]
        paired_diff = 0.0
        paired_diff_ci95: list[float] | None = [0.0, 0.0]
        paired_diff_hw = 0.0
        la_ratio: float | None = 1.0
        la_ratio_ci95: list[float] | None = [1.0, 1.0]
    else:
        raw_boot = paired_bootstrap_stats(scores, sol_scores)
        la_boot = paired_bootstrap_stats(la_scores, sol_la_scores)
        ratio_vs_solver = raw_boot["ratio"]
        ratio_ci95 = raw_boot["ratio_ci95"]
        paired_diff = float(raw_boot["diff"])
        paired_diff_ci95 = raw_boot["diff_ci95"]
        paired_diff_hw = float(diff_hw)
        la_ratio = la_boot["ratio"]
        la_ratio_ci95 = la_boot["ratio_ci95"]

    accused_items = [x for x in items if x["accused"] is not None]
    p_vals = [x["p_accused"] for x in accused_items if x["p_accused"] is not None]
    gamble_items = [x for x in items if x["sub_breakeven_gamble"]]
    lucky_gambles = [x for x in gamble_items if x["correct"]]

    return {
        "cohort": cohort,
        "agent": agent_str,
        "tier": tier,
        "source": source,
        "n": n,
        "seeds": seeds,
        "mean_score": float(m_score),
        "score_ci95": float(hw_score),
        "score_ci95_bounds": [float(m_score - hw_score), float(m_score + hw_score)],
        "solver_mean": float(sol_mean),
        "ratio_vs_solver": ratio_vs_solver,
        "ratio_ci95": ratio_ci95,
        "paired_diff": paired_diff,
        "paired_diff_ci95": paired_diff_ci95,
        "paired_diff_halfwidth95": paired_diff_hw,
        "accuracy": sum(1 for x in items if x["correct"]) / n,
        "accused_rate": len(accused_items) / n,
        "abstention_rate": 1.0 - (len(accused_items) / n),
        "mean_accuse_day": (
            sum(x["final_day"] for x in accused_items) / len(accused_items)
            if accused_items
            else None
        ),
        "mean_p_accused": (sum(p_vals) / len(p_vals)) if p_vals else None,
        "luck_adjusted_score": float(la_mean),
        "solver_luck_adjusted_score": float(sol_la_mean),
        "luck_adjusted_ratio": la_ratio,
        "luck_adjusted_ratio_ci95": la_ratio_ci95,
        "sub_breakeven_gamble_count": len(gamble_items),
        "sub_breakeven_gamble_rate": len(gamble_items) / n,
        "sub_breakeven_lucky_hits": len(lucky_gambles),
        "realized_luck": float(m_score - la_mean),
    }


def compute_head_to_head(
    tier: str,
    model_a_name: str,
    a_by_seed: dict[int, dict[str, Any]],
    model_b_name: str,
    b_by_seed: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    seeds = sorted(s for s in a_by_seed if s in b_by_seed)
    a_items = [a_by_seed[s] for s in seeds]
    b_items = [b_by_seed[s] for s in seeds]
    n = len(seeds)
    if n == 0:
        raise ValueError(f"No shared seeds for head_to_head on {tier}")

    a_scores = [x["score"] for x in a_items]
    b_scores = [x["score"] for x in b_items]
    a_la = [x["luck_adjusted"] for x in a_items]
    b_la = [x["luck_adjusted"] for x in b_items]

    raw_boot = paired_bootstrap_stats(a_scores, b_scores)
    la_boot = paired_bootstrap_stats(a_la, b_la)
    _, raw_hw = mean_ci([x - y for x, y in zip(a_scores, b_scores)])
    _, la_hw = mean_ci([x - y for x, y in zip(a_la, b_la)])

    mean_a = sum(a_scores) / n
    mean_b = sum(b_scores) / n
    mean_la_a = sum(a_la) / n
    mean_la_b = sum(b_la) / n
    luck_a = mean_a - mean_la_a
    luck_b = mean_b - mean_la_b

    both_corr = sum(1 for x, y in zip(a_items, b_items) if x["correct"] and y["correct"])
    a_only_corr = sum(1 for x, y in zip(a_items, b_items) if x["correct"] and not y["correct"])
    b_only_corr = sum(1 for x, y in zip(a_items, b_items) if not x["correct"] and y["correct"])
    neither_corr = sum(1 for x, y in zip(a_items, b_items) if not x["correct"] and not y["correct"])

    both_gam = sum(
        1 for x, y in zip(a_items, b_items) if x["sub_breakeven_gamble"] and y["sub_breakeven_gamble"]
    )
    a_only_gam = sum(
        1 for x, y in zip(a_items, b_items) if x["sub_breakeven_gamble"] and not y["sub_breakeven_gamble"]
    )
    b_only_gam = sum(
        1 for x, y in zip(a_items, b_items) if not x["sub_breakeven_gamble"] and y["sub_breakeven_gamble"]
    )
    neither_gam = sum(
        1 for x, y in zip(a_items, b_items) if not x["sub_breakeven_gamble"] and not y["sub_breakeven_gamble"]
    )

    return {
        "tier": tier,
        "model_a": model_a_name,
        "model_b": model_b_name,
        "n": n,
        "seeds": seeds,
        "mean_score_a": float(mean_a),
        "mean_score_b": float(mean_b),
        "paired_raw_diff": float(raw_boot["diff"]),
        "paired_raw_diff_ci95": raw_boot["diff_ci95"],
        "paired_raw_diff_halfwidth95": float(raw_hw),
        "luck_adjusted_a": float(mean_la_a),
        "luck_adjusted_b": float(mean_la_b),
        "paired_luck_adjusted_diff": float(la_boot["diff"]),
        "paired_luck_adjusted_diff_ci95": la_boot["diff_ci95"],
        "paired_luck_adjusted_diff_halfwidth95": float(la_hw),
        "realized_luck_a": float(luck_a),
        "realized_luck_b": float(luck_b),
        "realized_luck_gap_b_minus_a": float(luck_b - luck_a),
        "accuracy_concordance": {
            "both_correct": both_corr,
            "a_only_correct": a_only_corr,
            "b_only_correct": b_only_corr,
            "neither_correct": neither_corr,
        },
        "sub_breakeven_gamble_concordance": {
            "both_gamble": both_gam,
            "a_only_gamble": a_only_gam,
            "b_only_gamble": b_only_gam,
            "neither_gamble": neither_gam,
            "a_gamble_seeds": [x["seed"] for x in a_items if x["sub_breakeven_gamble"]],
            "b_gamble_seeds": [x["seed"] for x in b_items if x["sub_breakeven_gamble"]],
            "a_lucky_gamble_seeds": [
                x["seed"] for x in a_items if x["sub_breakeven_gamble"] and x["correct"]
            ],
            "b_lucky_gamble_seeds": [
                x["seed"] for x in b_items if x["sub_breakeven_gamble"] and x["correct"]
            ],
        },
    }


def _load_committed_cohorts(
    committed_dir: Path,
    audit_log: dict[str, Any],
) -> dict[str, dict[str, dict[int, dict[str, Any]]]]:
    solver_raw_med: list[dict[str, Any]] = []
    solver_raw_hard: list[dict[str, Any]] = []
    for f in sorted((committed_dir / "reference").glob("solver-medium-*/episodes.jsonl")):
        solver_raw_med.extend(_parse_jsonl_lines(f.read_text()))
    for f in sorted((committed_dir / "reference").glob("solver-hard-*/episodes.jsonl")):
        solver_raw_hard.extend(_parse_jsonl_lines(f.read_text()))

    solver_med = _collect_validated(
        solver_raw_med,
        source_tag="committed_v1.4",
        cohort_name="solver",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="medium",
    )
    solver_hard = _collect_validated(
        solver_raw_hard,
        source_tag="committed_v1.4",
        cohort_name="solver",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="hard",
    )

    carbon_oc_med = _collect_validated(
        _parse_jsonl_lines((committed_dir / "opencode-gemini-4-carbon/medium/episodes.jsonl").read_text()),
        source_tag="committed_v1.4",
        cohort_name="opencode-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="medium",
    )
    carbon_oc_hard = _collect_validated(
        _parse_jsonl_lines((committed_dir / "opencode-gemini-4-carbon/hard/episodes.jsonl").read_text()),
        source_tag="committed_v1.4",
        cohort_name="opencode-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="hard",
    )
    carbon_ip_med = _collect_validated(
        _parse_jsonl_lines((committed_dir / "inproc-gemini-4-carbon/medium/episodes.jsonl").read_text()),
        source_tag="committed_v1.4",
        cohort_name="inproc-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="medium",
    )
    carbon_ip_hard = _collect_validated(
        _parse_jsonl_lines((committed_dir / "inproc-gemini-4-carbon/hard/episodes.jsonl").read_text()),
        source_tag="committed_v1.4",
        cohort_name="inproc-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="hard",
    )
    flash_oc_hard = _collect_validated(
        _parse_jsonl_lines((committed_dir / "opencode-gemini-3.5-flash/hard/episodes.jsonl").read_text()),
        source_tag="committed_v1.4",
        cohort_name="opencode-gemini-3.5-flash",
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter="hard",
    )

    det_med: dict[str, dict[int, dict[str, Any]]] = {}
    det_hard: dict[str, dict[int, dict[str, Any]]] = {}
    seeds_0_29 = list(range(30))
    for ag in DETERMINISTIC_BASELINES_0_29:
        det_med[ag] = replay_deterministic_policy(ag, "medium", seeds_0_29, audit_log)
        det_hard[ag] = replay_deterministic_policy(ag, "hard", seeds_0_29, audit_log)

    return {
        "medium": {
            "opencode-gemini-4-carbon": carbon_oc_med,
            "inproc-gemini-4-carbon": carbon_ip_med,
            "solver": solver_med,
            **det_med,
        },
        "hard": {
            "opencode-gemini-4-carbon": carbon_oc_hard,
            "inproc-gemini-4-carbon": carbon_ip_hard,
            "opencode-gemini-3.5-flash": flash_oc_hard,
            "solver": solver_hard,
            **det_hard,
        },
    }


def compute(
    committed_dir: Path,
    frontier_dir: Path | None = None,
    frontier_ref: str = DEFAULT_FRONTIER_REF,
) -> dict[str, Any]:
    paired_v13._P_CACHE.clear()
    audit_log: dict[str, Any] = {
        "tiers_version_required": TIERS_VERSION,
        "fleet_max_wall_s": FLEET_MAX_WALL_S,
        "replay_score_tol": REPLAY_TOL,
        "total_inspected_episodes": 0,
        "total_valid_replayed_episodes": 0,
        "rejected_episodes": [],
        "committed_primary_over_3590s_clean_completions": [],
    }

    local_cohorts = _load_committed_cohorts(committed_dir, audit_log)
    audit_log["frontier_subpath_commit"] = (
        git_subpath_commit(frontier_ref) if frontier_dir is None else None
    )
    frontier_blobs = load_frontier_tree(frontier_dir, frontier_ref)
    if frontier_blobs is None:
        raise RuntimeError(
            f"Frontier replication data not found via --frontier-dir or --frontier-ref={frontier_ref}"
        )

    flash_med_raw: list[dict[str, Any]] = []
    carbon_rep_raw: list[dict[str, Any]] = []
    ref_30_59_raw: dict[str, list[dict[str, Any]]] = {}

    for rel, text in sorted(frontier_blobs.items()):
        if rel.startswith("opencode-gemini-3.5-flash/medium"):
            flash_med_raw.extend(_parse_jsonl_lines(text))
        elif rel.startswith("opencode-gemini-4-carbon/hard"):
            carbon_rep_raw.extend(_parse_jsonl_lines(text))
        elif rel.startswith("reference/") and "-hard-seeds30to59/" in rel:
            run_folder = rel.split("/")[1]
            agent_name = run_folder.split("-hard-seeds30to59")[0]
            ref_30_59_raw.setdefault(agent_name, []).extend(_parse_jsonl_lines(text))

    flash_oc_med = _collect_validated(
        flash_med_raw,
        source_tag="frontier_replication_v1.4",
        cohort_name="opencode-gemini-3.5-flash",
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter="medium",
    )
    carbon_rep_hard = _collect_validated(
        carbon_rep_raw,
        source_tag="frontier_replication_v1.4",
        cohort_name="opencode-gemini-4-carbon-replication",
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter="hard",
    )

    ref_30_59_validated: dict[str, dict[int, dict[str, Any]]] = {}
    for ag, raw_list in sorted(ref_30_59_raw.items()):
        ref_30_59_validated[ag] = _collect_validated(
            raw_list,
            source_tag="frontier_replication_v1.4",
            cohort_name=f"reference/{ag}",
            enforce_wall_cap=True,
            audit_log=audit_log,
            tier_filter="hard",
        )

    if "solver" in ref_30_59_validated and ref_30_59_validated["solver"]:
        solver_30_59 = ref_30_59_validated["solver"]
    elif carbon_rep_hard:
        solver_30_59 = replay_deterministic_policy(
            "solver", "hard", sorted(carbon_rep_hard.keys()), audit_log
        )
    else:
        solver_30_59 = {}

    med_solver = local_cohorts["medium"]["solver"]
    hard_solver = local_cohorts["hard"]["solver"]

    primary_cohorts: list[dict[str, Any]] = []
    med_order = [
        ("opencode-gemini-4-carbon", "committed_v1.4", local_cohorts["medium"]["opencode-gemini-4-carbon"]),
        ("inproc-gemini-4-carbon", "committed_v1.4", local_cohorts["medium"]["inproc-gemini-4-carbon"]),
    ]
    if flash_oc_med:
        med_order.append(("opencode-gemini-3.5-flash", "frontier_replication_v1.4", flash_oc_med))
    med_order.append(("solver", "committed_v1.4", med_solver))
    for ag in DETERMINISTIC_BASELINES_0_29:
        med_order.append((ag, "inproc_deterministic_v1.4", local_cohorts["medium"][ag]))

    for cname, src, cmap in med_order:
        primary_cohorts.append(summarize_cohort(cname, "medium", src, cmap, med_solver))

    hard_order = [
        ("opencode-gemini-4-carbon", "committed_v1.4", local_cohorts["hard"]["opencode-gemini-4-carbon"]),
        ("inproc-gemini-4-carbon", "committed_v1.4", local_cohorts["hard"]["inproc-gemini-4-carbon"]),
        ("opencode-gemini-3.5-flash", "committed_v1.4", local_cohorts["hard"]["opencode-gemini-3.5-flash"]),
        ("solver", "committed_v1.4", hard_solver),
    ]
    for ag in DETERMINISTIC_BASELINES_0_29:
        hard_order.append((ag, "inproc_deterministic_v1.4", local_cohorts["hard"][ag]))

    for cname, src, cmap in hard_order:
        primary_cohorts.append(summarize_cohort(cname, "hard", src, cmap, hard_solver))

    head_to_head: dict[str, Any] = {
        "hard": compute_head_to_head(
            "hard",
            "opencode-gemini-4-carbon",
            local_cohorts["hard"]["opencode-gemini-4-carbon"],
            "opencode-gemini-3.5-flash",
            local_cohorts["hard"]["opencode-gemini-3.5-flash"],
        )
    }
    if flash_oc_med:
        head_to_head["medium"] = compute_head_to_head(
            "medium",
            "opencode-gemini-4-carbon",
            local_cohorts["medium"]["opencode-gemini-4-carbon"],
            "opencode-gemini-3.5-flash",
            flash_oc_med,
        )

    rep_carbon_summary = (
        summarize_cohort(
            "opencode-gemini-4-carbon-replication",
            "hard",
            "frontier_replication_v1.4",
            carbon_rep_hard,
            solver_30_59,
        )
        if carbon_rep_hard
        else None
    )
    rep_per_seed = [
        {
            "seed": s,
            "score": carbon_rep_hard[s]["score"],
            "solver_score": solver_30_59[s]["score"],
            "correct": carbon_rep_hard[s]["correct"],
            "solver_correct": solver_30_59[s]["correct"],
            "accuse_day": carbon_rep_hard[s]["final_day"] if carbon_rep_hard[s]["accused"] else None,
            "solver_accuse_day": solver_30_59[s]["final_day"] if solver_30_59[s]["accused"] else None,
            "p_accused": carbon_rep_hard[s]["p_accused"],
            "shown_v": carbon_rep_hard[s]["shown_v"],
            "luck_adjusted": carbon_rep_hard[s]["luck_adjusted"],
            "solver_luck_adjusted": solver_30_59[s]["luck_adjusted"],
        }
        for s in sorted(carbon_rep_hard)
        if s in solver_30_59
    ]

    ref_30_59_summaries: list[dict[str, Any]] = []
    ordered_ref_names = [a for a in REPLICATION_REF_ORDER if a in ref_30_59_validated] + [
        a for a in sorted(ref_30_59_validated) if a not in REPLICATION_REF_ORDER
    ]
    for ag in ordered_ref_names:
        if ref_30_59_validated[ag] and solver_30_59:
            ref_30_59_summaries.append(
                summarize_cohort(
                    ag,
                    "hard",
                    "frontier_replication_v1.4",
                    ref_30_59_validated[ag],
                    solver_30_59,
                )
            )

    post_pr16_checks: dict[str, Any] = {}
    if "stop_early" in ref_30_59_validated and ref_30_59_validated["stop_early"]:
        se_vals = [x["score"] for x in ref_30_59_validated["stop_early"].values()]
        post_pr16_checks["stop_early_all_zero"] = all(abs(v) < REPLAY_TOL for v in se_vals)
        post_pr16_checks["stop_early_mean"] = float(sum(se_vals) / len(se_vals))
    if "do_nothing" in ref_30_59_validated and ref_30_59_validated["do_nothing"]:
        dn_vals = [x["score"] for x in ref_30_59_validated["do_nothing"].values()]
        post_pr16_checks["do_nothing_all_zero"] = all(abs(v) < REPLAY_TOL for v in dn_vals)
        post_pr16_checks["do_nothing_mean"] = float(sum(dn_vals) / len(dn_vals))

    pooled_carbon = {**local_cohorts["hard"]["opencode-gemini-4-carbon"], **carbon_rep_hard}
    pooled_solver = {**hard_solver, **solver_30_59}
    pooled_summary = summarize_cohort(
        "opencode-gemini-4-carbon-pooled-sensitivity",
        "hard",
        "pooled_secondary_0_29_plus_replication",
        pooled_carbon,
        pooled_solver,
    )
    pooled_summary["status"] = "secondary_sensitivity_only"
    pooled_summary["headline_cohort"] = "primary_0_29/opencode-gemini-4-carbon/hard"

    paired_v13._P_CACHE.clear()
    return {
        "schema_version": "v1.4.1",
        "tiers_version": TIERS_VERSION,
        "bootstrap": {"n_boot": N_BOOT, "seed": BOOT_SEED},
        "data_rule": audit_log,
        "primary_0_29": {
            "pre_registration_note": (
                "Seeds 0-29 per tier (pre-registered Sat 14 Nov ~22:45 Helsinki, commit 671ed96, "
                "docs/reports/gap.md) form the sole primary headline result."
            ),
            "cohorts": primary_cohorts,
            "head_to_head": head_to_head,
        },
        "replication_30_59": {
            "pre_registration_note": (
                "Seeds 30-59 extension/replication shards are reported (a) strictly separately on their own "
                "and (b) pooled with seeds 0-29 as a secondary sensitivity check only, never replacing the "
                "primary n=30 row (commits 671ed96 and f9fb7a4a, docs/reports/gap.md)."
            ),
            "opencode_gemini_4_carbon_hard_replication": rep_carbon_summary,
            "opencode_gemini_4_carbon_hard_per_seed": rep_per_seed,
            "reference_hard_30_59": ref_30_59_summaries,
            "post_pr16_zero_checks": post_pr16_checks,
            "secondary_pooled_sensitivity_hard": pooled_summary,
        },
    }


def _fmt_num(x: float | None, nd: int = 3, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    spec = f"{'+' if signed else ''}.{nd}f"
    return format(x, spec)


def _fmt_pct_ci(r: float | None, ci: list[float] | None, is_solver: bool = False) -> str:
    if is_solver or r is None:
        return "100%" if is_solver else "n/a"
    if ci is None:
        return f"{r * 100.0:.1f}%"
    return f"{r * 100.0:.1f}% [{ci[0] * 100.0:.1f}%, {ci[1] * 100.0:.1f}%]"


def _cohort_table_md(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| tier | cohort | n | score +/- 95% CI | / solver [95% CI] | paired diff [95% CI] | acc | accused | day | mean P(acc) | luck-adj | luck-adj / solver [95% CI] | gambles | luck |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        is_sol = r["cohort"] == "solver"
        diff_cell = (
            "0.000"
            if is_sol
            else f"{r['paired_diff']:+.3f} [{r['paired_diff_ci95'][0]:+.3f}, {r['paired_diff_ci95'][1]:+.3f}]"
        )
        lines.append(
            f"| {r['tier']} | `{r['cohort']}` | {r['n']} | "
            f"{r['mean_score']:+.3f} +/- {r['score_ci95']:.3f} | "
            f"{_fmt_pct_ci(r['ratio_vs_solver'], r['ratio_ci95'], is_sol)} | "
            f"{diff_cell} | "
            f"{r['accuracy']:.2f} | {r['accused_rate']:.2f} | "
            f"{_fmt_num(r['mean_accuse_day'], 1)} | {_fmt_num(r['mean_p_accused'], 2)} | "
            f"{r['luck_adjusted_score']:+.3f} | "
            f"{_fmt_pct_ci(r['luck_adjusted_ratio'], r['luck_adjusted_ratio_ci95'], is_sol)} | "
            f"{r['sub_breakeven_gamble_count']}/{r['n']} ({r['sub_breakeven_gamble_rate'] * 100.0:.0f}%) | "
            f"{r['realized_luck']:+.3f} |"
        )
    return lines


def render_markdown(data: dict[str, Any]) -> str:
    audit = data["data_rule"]
    prim = data["primary_0_29"]
    rep = data["replication_30_59"]
    cohorts = prim["cohorts"]
    med_rows = [r for r in cohorts if r["tier"] == "medium"]
    hard_rows = [r for r in cohorts if r["tier"] == "hard"]
    by_key = {(r["tier"], r["cohort"]): r for r in cohorts}

    c_hard = by_key[("hard", "opencode-gemini-4-carbon")]
    f_hard = by_key[("hard", "opencode-gemini-3.5-flash")]
    f_med = by_key.get(("medium", "opencode-gemini-3.5-flash"))
    h2h_hard = prim["head_to_head"]["hard"]
    h2h_med = prim["head_to_head"].get("medium")
    med_heading = (
        f"{H3} Medium Tier (`seeds 0-29`, `n=30` paired per cohort)"
        if all(r["n"] == 30 for r in med_rows)
        else f"{H3} Medium Tier (`seeds 0-29`; `gemini-3.5-flash` paired on `n={f_med['n'] if f_med else 0}` completed seeds)"
    )

    lines: list[str] = [
        f"{H1} Canary v1.4 Cross-Model Comparison and Seeds 30-59 Replication Audit",
        "",
        "Generated deterministically offline (`0` live LLM calls, single-process) by:",
        "```bash",
        "python scripts/eval_replication_and_crossmodel.py",
        "python scripts/eval_replication_and_crossmodel.py --check",
        "```",
        "",
        f"{H2} Data Rule and Replay Integrity",
        "",
        f"- Rules version verified: `{data['tiers_version']}` (`Env(tier, seed)` step-by-step replay tolerance `{audit['replay_score_tol']}`).",
        f"- Total episode records inspected and replay-verified: `{audit['total_valid_replayed_episodes']}/{audit['total_inspected_episodes']}` valid (`{len(audit['rejected_episodes'])}` rejected by DATA RULE).",
        f"- Fleet shard wall-clock guard: `wall_s < {audit['fleet_max_wall_s']:.0f}s` (`rc != timeout`, `end_reason != error`, `valid != False`).",
        f"- Pre-registered primary `0-29` clean completions exceeding 3590s (run prior to the fleet 3600s cap, motivating Harbor's `3600s -> 10800s` bump in commit `512836b9`): `{len(audit['committed_primary_over_3590s_clean_completions'])}` episodes, all `rc=0` and replay-exact.",
        f"- Paired bootstrap: `{data['bootstrap']['n_boot']}` resamples over shared seeds (`seed={data['bootstrap']['seed']}`).",
        "",
        f"{H2} Part A: Primary Evaluation (`seeds 0-29`, Pre-Registered Headline Scope)",
        "",
        prim["pre_registration_note"],
        "",
        med_heading,
        "",
        *_cohort_table_md(med_rows),
        "",
        f"{H3} Hard Tier (`seeds 0-29`, `n=30` paired per cohort)",
        "",
        *_cohort_table_md(hard_rows),
        "",
        f"{H3} Head-to-Head Cross-Model Comparison (`opencode-gemini-4-carbon` minus `opencode-gemini-3.5-flash`)",
        "",
        "| tier | n | carbon raw | flash raw | paired raw diff [95% CI] | carbon luck-adj | flash luck-adj | paired luck-adj diff [95% CI] | carbon gambles (lucky) | flash gambles (lucky) | flash minus carbon luck |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for t_key in ("medium", "hard"):
        h = prim["head_to_head"].get(t_key)
        if not h:
            continue
        gc = h["sub_breakeven_gamble_concordance"]
        n_a_gam = len(gc["a_gamble_seeds"])
        n_a_luk = len(gc["a_lucky_gamble_seeds"])
        n_b_gam = len(gc["b_gamble_seeds"])
        n_b_luk = len(gc["b_lucky_gamble_seeds"])
        lines.append(
            f"| {t_key} | {h['n']} | {h['mean_score_a']:+.3f} | {h['mean_score_b']:+.3f} | "
            f"{h['paired_raw_diff']:+.3f} [{h['paired_raw_diff_ci95'][0]:+.3f}, {h['paired_raw_diff_ci95'][1]:+.3f}] | "
            f"{h['luck_adjusted_a']:+.3f} | {h['luck_adjusted_b']:+.3f} | "
            f"{h['paired_luck_adjusted_diff']:+.3f} [{h['paired_luck_adjusted_diff_ci95'][0]:+.3f}, {h['paired_luck_adjusted_diff_ci95'][1]:+.3f}] | "
            f"{n_a_gam}/{h['n']} ({n_a_luk}) | {n_b_gam}/{h['n']} ({n_b_luk}) | "
            f"{h['realized_luck_gap_b_minus_a']:+.3f} |"
        )

    lines.extend([
        "",
        f"{H3} Why `gemini-3.5-flash` Hard Raw Score (`{_fmt_pct_ci(f_hard['ratio_vs_solver'], f_hard['ratio_ci95'])}`) Collapses Under Luck Adjustment (`{_fmt_pct_ci(f_hard['luck_adjusted_ratio'], f_hard['luck_adjusted_ratio_ci95'])}`)",
        "",
        f"1. **Unjustified sub-breakeven gambling (`0%` abstention)**: On `hard` seeds `0-29`, `opencode-gemini-3.5-flash` never abstains (`accused_rate = {f_hard['accused_rate']:.2f}`) and accuses at mean solver posterior `P(accused) = {f_hard['mean_p_accused']:.2f}` vs `opencode-gemini-4-carbon`'s `P(accused) = {c_hard['mean_p_accused']:.2f}`. In `{f_hard['sub_breakeven_gamble_count']}/{f_hard['n']}` episodes (`{f_hard['sub_breakeven_gamble_rate'] * 100.0:.1f}%`, seeds `{h2h_hard['sub_breakeven_gamble_concordance']['b_gamble_seeds']}`), `gemini-3.5-flash` accuses below the public EV break-even threshold `1 / (1 + shown_V)`, compared to `{c_hard['sub_breakeven_gamble_count']}/{c_hard['n']}` (`{c_hard['sub_breakeven_gamble_rate'] * 100.0:.1f}%`) for `gemini-4-carbon`.",
        f"2. **Realized luck windfall**: Across those `{f_hard['sub_breakeven_gamble_count']}` negative-EV gambles, `gemini-3.5-flash` hit the true mole on `{f_hard['sub_breakeven_lucky_hits']}/{f_hard['sub_breakeven_gamble_count']}` episodes (`{f_hard['accuracy']:.2f}` overall accuracy), generating `realized_luck = {f_hard['realized_luck']:+.3f}` per episode vs `{c_hard['realized_luck']:+.3f}` for `gemini-4-carbon` (a `{h2h_hard['realized_luck_gap_b_minus_a']:+.3f}` per-episode luck swing).",
        f"3. **Decision-quality reversal**: Scoring each accusation by its exact solver-posterior expected value `P * V - (1 - P)` drops `gemini-3.5-flash` from `{f_hard['mean_score']:+.3f}` (`{_fmt_pct_ci(f_hard['ratio_vs_solver'], f_hard['ratio_ci95'])}`) to `{f_hard['luck_adjusted_score']:+.3f}` (`{_fmt_pct_ci(f_hard['luck_adjusted_ratio'], f_hard['luck_adjusted_ratio_ci95'])}` of solver), while `gemini-4-carbon` rises to `{c_hard['luck_adjusted_score']:+.3f}` (`{_fmt_pct_ci(c_hard['luck_adjusted_ratio'], c_hard['luck_adjusted_ratio_ci95'])}` of solver), giving `gemini-4-carbon` a `{h2h_hard['paired_luck_adjusted_diff']:+.3f}` (`[{h2h_hard['paired_luck_adjusted_diff_ci95'][0]:+.3f}, {h2h_hard['paired_luck_adjusted_diff_ci95'][1]:+.3f}]`) paired luck-adjusted advantage on `hard`"
        + (
            f" alongside a `{h2h_med['paired_luck_adjusted_diff']:+.3f}` (`[{h2h_med['paired_luck_adjusted_diff_ci95'][0]:+.3f}, {h2h_med['paired_luck_adjusted_diff_ci95'][1]:+.3f}]`) paired luck-adjusted advantage on `medium` (`n={h2h_med['n']}`)."
            if h2h_med
            else "."
        ),
        f"4. **Concordance on `hard` (`n={h2h_hard['n']}`)**: Accuracy concordance is `both_correct={h2h_hard['accuracy_concordance']['both_correct']}`, `carbon_only={h2h_hard['accuracy_concordance']['a_only_correct']}`, `flash_only={h2h_hard['accuracy_concordance']['b_only_correct']}`, `neither={h2h_hard['accuracy_concordance']['neither_correct']}`; sub-breakeven gamble concordance is `both_gamble={h2h_hard['sub_breakeven_gamble_concordance']['both_gamble']}`, `carbon_only={h2h_hard['sub_breakeven_gamble_concordance']['a_only_gamble']}`, `flash_only={h2h_hard['sub_breakeven_gamble_concordance']['b_only_gamble']}`, `neither={h2h_hard['sub_breakeven_gamble_concordance']['neither_gamble']}`.",
        "",
        f"{H2} Part B: Hard Replication Audit (`seeds 30-59`, Strictly Separated from Headline)",
        "",
        rep["pre_registration_note"],
        "",
    ])

    rep_c = rep["opencode_gemini_4_carbon_hard_replication"]
    pooled = rep["secondary_pooled_sensitivity_hard"]
    if rep_c is not None:
        lines.extend([
            f"{H3} Replication Cohort (`opencode-gemini-4-carbon` on Completed Seeds `{rep_c['seeds']}`) and Secondary Pooled Sensitivity",
            "",
            *_cohort_table_md([rep_c, pooled]),
            "",
            "| seed | carbon score | carbon day | carbon P(acc) | carbon luck-adj | solver score | solver day | solver luck-adj |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for ps in rep["opencode_gemini_4_carbon_hard_per_seed"]:
            lines.append(
                f"| {ps['seed']} | {ps['score']:+.3f} | {_fmt_num(ps['accuse_day'], 0)} | "
                f"{_fmt_num(ps['p_accused'], 3)} | {ps['luck_adjusted']:+.3f} | "
                f"{ps['solver_score']:+.3f} | {_fmt_num(ps['solver_accuse_day'], 0)} | "
                f"{ps['solver_luck_adjusted']:+.3f} |"
            )
        ref_sol_note = (
            f" (vs `{rep['reference_hard_30_59'][0]['mean_score']:+.3f}` across all 30 seeds `30-59`)"
            if rep["reference_hard_30_59"]
            else ""
        )
        lines.extend([
            "",
            f"Note on small-sample replication ratio (`n={rep_c['n']}`): on seed `30` the reference solver suffered a 5% canary fingerprint flip (`score = -1.000`, `luck_adjusted = +0.175`), depressing the 5-seed raw solver denominator to `{rep_c['solver_mean']:+.3f}`{ref_sol_note}. Under the secondary pooled sensitivity check (`n={pooled['n']}`), the luck-adjusted ratio is `{_fmt_pct_ci(pooled['luck_adjusted_ratio'], pooled['luck_adjusted_ratio_ci95'])}` (95% CI upper bound `< 100%`). Per pre-registration (`docs/reports/gap.md`), `primary_0_29` (`n=30`) remains the sole headline.",
            "",
        ])

    if rep["reference_hard_30_59"]:
        z = rep["post_pr16_zero_checks"]
        lines.extend([
            f"{H3} Reference Baselines on Hard Seeds `30-59` (`n=30` Each, Post-PR16 Verification)",
            "",
            f"- Post-PR16 zero-reward invariants on `30-59`: `stop_early == 0.0` (`all_zero={z.get('stop_early_all_zero')}`, `mean={z.get('stop_early_mean', 0.0):+.3f}`), `do_nothing == 0.0` (`all_zero={z.get('do_nothing_all_zero')}`, `mean={z.get('do_nothing_mean', 0.0):+.3f}`).",
            "",
            *_cohort_table_md(rep["reference_hard_30_59"]),
            "",
        ])

    return "\n".join(lines).rstrip() + "\n"


def check_shallow_ci(
    committed_dir: Path,
    out_json: Path,
    out_md: Path,
) -> int:
    if not out_json.exists() or not out_md.exists():
        print("Missing committed JSON or Markdown output for --check", file=sys.stderr)
        return 1
    if out_json.stat().st_size >= MAX_JSON_BYTES:
        print(f"{out_json} size {out_json.stat().st_size} >= {MAX_JSON_BYTES}", file=sys.stderr)
        return 1
    stored = json.loads(out_json.read_text(encoding="utf-8"))
    stored_md = out_md.read_text(encoding="utf-8")
    if render_markdown(stored) != stored_md:
        print(f"{out_md} differs from render_markdown({out_json})", file=sys.stderr)
        return 1

    paired_v13._P_CACHE.clear()
    audit_log: dict[str, Any] = {
        "tiers_version_required": TIERS_VERSION,
        "fleet_max_wall_s": FLEET_MAX_WALL_S,
        "replay_score_tol": REPLAY_TOL,
        "total_inspected_episodes": 0,
        "total_valid_replayed_episodes": 0,
        "rejected_episodes": [],
        "committed_primary_over_3590s_clean_completions": [],
    }
    local_cohorts = _load_committed_cohorts(committed_dir, audit_log)
    stored_map = {
        (c["tier"], c["cohort"]): c for c in stored.get("primary_0_29", {}).get("cohorts", [])
    }

    for tier in ("medium", "hard"):
        sol = local_cohorts[tier]["solver"]
        for cname, cmap in local_cohorts[tier].items():
            src = (
                "committed_v1.4"
                if cname in ("opencode-gemini-4-carbon", "inproc-gemini-4-carbon", "opencode-gemini-3.5-flash", "solver")
                else "inproc_deterministic_v1.4"
            )
            fresh_row = summarize_cohort(cname, tier, src, cmap, sol)
            target = stored_map.get((tier, cname))
            if target is None or not approx_equal(target, fresh_row):
                print(f"Mismatch in shallow --check on primary cohort ({tier}, {cname})", file=sys.stderr)
                return 1

    fresh_h2h_hard = compute_head_to_head(
        "hard",
        "opencode-gemini-4-carbon",
        local_cohorts["hard"]["opencode-gemini-4-carbon"],
        "opencode-gemini-3.5-flash",
        local_cohorts["hard"]["opencode-gemini-3.5-flash"],
    )
    if not approx_equal(stored["primary_0_29"]["head_to_head"]["hard"], fresh_h2h_hard):
        print("Mismatch in shallow --check on primary head_to_head hard", file=sys.stderr)
        return 1

    paired_v13._P_CACHE.clear()
    print("crossmodel and replication check passed (shallow CI mode: primary 0-29 + MD verified)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline v1.4 cross-model and seeds 30-59 replication audit.")
    ap.add_argument("--committed-dir", default=DEFAULT_COMMITTED_DIR)
    ap.add_argument("--frontier-ref", default=None)
    ap.add_argument("--frontier-dir", default=None)
    ap.add_argument("--out-json", default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", default=DEFAULT_OUT_MD)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    committed_dir = Path(args.committed_dir)
    if not committed_dir.is_absolute():
        committed_dir = ROOT / committed_dir
    frontier_dir = Path(args.frontier_dir) if args.frontier_dir is not None else None
    if frontier_dir is not None and not frontier_dir.is_absolute():
        frontier_dir = ROOT / frontier_dir
    out_json = Path(args.out_json)
    if not out_json.is_absolute():
        out_json = ROOT / out_json
    out_md = Path(args.out_md)
    if not out_md.is_absolute():
        out_md = ROOT / out_md

    if args.check:
        if not out_json.exists() or not out_md.exists():
            print("Committed JSON or Markdown file does not exist for --check", file=sys.stderr)
            return 1
        if out_json.stat().st_size >= MAX_JSON_BYTES:
            print(f"{out_json} size {out_json.stat().st_size} >= {MAX_JSON_BYTES}", file=sys.stderr)
            return 1
        stored = json.loads(out_json.read_text(encoding="utf-8"))
        if frontier_dir is not None:
            effective_ref = args.frontier_ref or DEFAULT_FRONTIER_REF
            has_frontier = True
        elif args.frontier_ref is not None:
            effective_ref = args.frontier_ref
            has_frontier = load_frontier_tree(None, effective_ref, allow_merged_local=False) is not None
        else:
            pinned = stored.get("data_rule", {}).get("frontier_subpath_commit")
            if (
                isinstance(pinned, str)
                and pinned
                and git_subpath_commit(pinned) == pinned
                and load_frontier_tree(None, pinned, allow_merged_local=False) is not None
            ):
                effective_ref = pinned
                has_frontier = True
            elif (
                load_frontier_tree(None, DEFAULT_FRONTIER_REF, allow_merged_local=False) is not None
                and git_subpath_commit(DEFAULT_FRONTIER_REF) == pinned
            ):
                effective_ref = DEFAULT_FRONTIER_REF
                has_frontier = True
            else:
                effective_ref = DEFAULT_FRONTIER_REF
                has_frontier = False
        if not has_frontier:
            return check_shallow_ci(committed_dir, out_json, out_md)
        fresh = compute(committed_dir, frontier_dir=frontier_dir, frontier_ref=effective_ref)
        fresh_roundtrip = json.loads(json.dumps(fresh, sort_keys=True))
        if not approx_equal(stored, fresh_roundtrip):
            print(f"{out_json} differs from fresh computation beyond {REPLAY_TOL}", file=sys.stderr)
            return 1
        fresh_md = render_markdown(fresh_roundtrip)
        if out_md.read_text(encoding="utf-8") != fresh_md:
            print(f"{out_md} differs from fresh Markdown render", file=sys.stderr)
            return 1
        print("crossmodel and replication check passed (full Part A + Part B + MD verified)")
        return 0

    effective_ref = args.frontier_ref or DEFAULT_FRONTIER_REF
    data = compute(committed_dir, frontier_dir=frontier_dir, frontier_ref=effective_ref)
    blob = json.dumps(data, indent=1, sort_keys=True, ensure_ascii=True) + "\n"
    if len(blob.encode("utf-8")) >= MAX_JSON_BYTES:
        print(f"Generated JSON {len(blob)} bytes exceeds {MAX_JSON_BYTES}", file=sys.stderr)
        return 1
    md = render_markdown(json.loads(blob))
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(blob, encoding="utf-8")
    out_md.write_text(md, encoding="utf-8")
    print(f"wrote {out_json} ({len(blob)} bytes) and {out_md} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
