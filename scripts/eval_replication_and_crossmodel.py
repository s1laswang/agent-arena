"""Offline v1.4 cross-model comparison (seeds 0-29) and hard extension audit (seeds 30-59).

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
from canary.redteam.anticheat import _canon, _client_only_step, _client_truncated_bytes, _norm_result
import paired_v13

SCHEMA_VERSION = "v1.4.2"
TIERS_VERSION = "v1.4"
BOOT_SEED = 0
N_BOOT = 10000
FLEET_MAX_WALL_S = 3590.0
REPLAY_TOL = 1e-9
MAX_JSON_BYTES = 50 * 1024
JSON_FLOAT_DIGITS = 12

PRIMARY_SEEDS: tuple[int, ...] = tuple(range(30))
EXTENSION_SEEDS: tuple[int, ...] = tuple(range(30, 60))

_BOOT_WEIGHT_CACHE: dict[tuple[int, int, int], np.ndarray] = {}

DEFAULT_COMMITTED_DIR = "data/runs/committed/v1.4"
DEFAULT_FRONTIER_DIR = "results/frontier_replication/v1.4"
DEFAULT_OUT_JSON = "results/eval_v14/crossmodel_and_replication_v14.json"
DEFAULT_OUT_MD = "docs/reports/crossmodel_and_replication_v14.md"

DETERMINISTIC_BASELINES_0_29: tuple[str, ...] = (
    "grok_tactics",
    "heuristic",
    "logs_only",
    "do_nothing",
    "stop_early",
    "guess_day1",
)

REPLICATION_REF_ORDER: tuple[str, ...] = (
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
        fa, fb = float(a), float(b)
        if not (math.isfinite(fa) and math.isfinite(fb)):
            return False
        return math.isclose(fa, fb, rel_tol=tol, abs_tol=tol)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(approx_equal(a[k], b[k], tol) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(approx_equal(x, y, tol) for x, y in zip(a, b))
    return a == b


def _round_floats(obj: Any, ndigits: int = JSON_FLOAT_DIGITS) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, (int, str)):
        return obj
    if isinstance(obj, float):
        if not math.isfinite(obj):
            return None
        val = round(obj, ndigits)
        return 0.0 if val == 0.0 else val
    if isinstance(obj, dict):
        return {str(k): _round_floats(obj[k], ndigits) for k in sorted(obj)}
    if isinstance(obj, (list, tuple)):
        return [_round_floats(v, ndigits) for v in obj]
    return obj


def _is_scalar_list(val: Any) -> bool:
    return isinstance(val, list) and all(
        v is None or isinstance(v, (bool, int, float, str)) for v in val
    )


def format_compact_json(obj: Any, indent: int = 0) -> str:
    pad = " " * indent
    next_pad = " " * (indent + 1)
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        items: list[str] = []
        for k in sorted(obj):
            k_str = json.dumps(str(k), ensure_ascii=True)
            v_str = format_compact_json(obj[k], indent + 1)
            items.append(f"{next_pad}{k_str}: {v_str}")
        return "{\n" + ",\n".join(items) + "\n" + pad + "}"
    if isinstance(obj, list):
        if not obj:
            return "[]"
        if _is_scalar_list(obj):
            return "[" + ", ".join(json.dumps(v, ensure_ascii=True) for v in obj) + "]"
        items = [f"{next_pad}{format_compact_json(v, indent + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + pad + "]"
    return json.dumps(obj, ensure_ascii=True)


def serialize_payload(data: dict[str, Any]) -> str:
    cleaned = _round_floats(data)
    return format_compact_json(cleaned) + "\n"


def _step_payload_matches(r_ok: bool, r_data: Any, r_error: str | None, rec: Any) -> tuple[bool, bool]:
    if rec is None:
        return True, False
    want = _norm_result(rec)
    got_payload: dict[str, Any] = {"ok": r_ok, "data": r_data, "error": r_error}
    has_recorded_detail = (
        isinstance(want, dict)
        and isinstance(want.get("data"), dict)
        and "detail" in want["data"]
    )
    if not r_ok and isinstance(r_data, dict) and set(r_data) == {"detail"} and not has_recorded_detail:
        got_payload = {"ok": r_ok, "data": {}, "error": r_error}
    trunc = _client_truncated_bytes(rec)
    if trunc is not None:
        return len(json.dumps(got_payload).encode("utf-8")) == trunc, True
    if want is None or got_payload == want:
        return True, False
    return _canon(got_payload) == _canon(want), False


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
    rc = ep.get("rc") if "rc" in ep else meta.get("rc")
    agent_stopped = (
        rc == 0
        and ep.get("accused") is None
        and float(ep.get("score") or 0.0) == 0.0
        and str(meta.get("note") or "").startswith("agent stopped without ending the episode")
    )
    if end_reason == "timeout" or (end_reason == "error" and not agent_stopped):
        return False, f"end_reason_{end_reason}", None
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
    steps_verified = 0
    steps_truncated_checked = 0
    steps_client_only = 0
    for step_idx, step in enumerate(ep.get("steps") or []):
        if _client_only_step(step):
            steps_client_only += 1
            continue
        if step.get("tool") == "accuse" and not env.done:
            shown_v = env.visible_V()
        r = env.call(step["tool"], step.get("args") or {})
        matched, was_trunc = _step_payload_matches(r.ok, r.data, r.error, step.get("result"))
        if not matched:
            raise ValueError(
                f"Step replay mismatch on {ep.get('agent')} {tier} seed {seed} at step {step_idx}"
            )
        steps_verified += 1
        if was_trunc:
            steps_truncated_checked += 1

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
        "steps_verified": steps_verified,
        "steps_truncated_checked": steps_truncated_checked,
        "steps_client_only": steps_client_only,
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


def _new_audit_log() -> dict[str, Any]:
    return {
        "tiers_version_required": TIERS_VERSION,
        "fleet_max_wall_s": FLEET_MAX_WALL_S,
        "replay_score_tol": REPLAY_TOL,
        "step_error_detail_compat": "1bc3e281",
        "step_error_detail_rule": (
            "Step-level Env tool-output replay strips data.detail on not-ok single-key detail "
            "responses when replaying pre-1bc3e281 recorded steps that lack detail, while "
            "verifying exact detail strings on post-1bc3e281 steps (Panel Fix D, commit 1bc3e281)."
        ),
        "primary_seed_lock_rule": (
            "Primary seeds 0-29 per tier are a post-hoc lock (commit 671ed96, committed 28 s after "
            "8fd4dec against later reruns and cherry-picking, not pre-registered); true pre-registrations "
            "before any episode are G1 hard seeds 30-59 (f9fb7a4a), causal --hint gather (fd8c1cb0), "
            "and OpenCode 1.19.5 gpt-5.5 hard seeds 0-29 (cf394894, tag afterquery-final, stop 08:15 / $200 cap)."
        ),
        "solver_reference_layout_note": (
            "Primary seeds 0-29 filter strictly to 0..29 across the 20+10 solver reference dirs "
            "(solver-{medium,hard}-20261114-121126 for 0-19 plus solver-{medium,hard}-seeds20to29 for 20-29), "
            "never mixing committed solver-hard-seeds30to59 (seeds 30-59, n=30), which pairs 30-59 directly."
        ),
        "hard_access_constraints_note": (
            "On v1.4 hard, access_constraints never binds because canary_level=1 while every employee "
            "clearance is 1-3 (docs/DIFFICULTY.md W4 / Panel Fix A 92708834)."
        ),
        "working_tree_only": True,
        "total_inspected_episodes": 0,
        "total_valid_replayed_episodes": 0,
        "total_steps_verified": 0,
        "total_steps_truncated_checked": 0,
        "total_steps_client_only": 0,
        "rejected_episodes": [],
        "committed_primary_over_3590s_clean_completions": [],
    }


def _collect_validated(
    raw_eps: list[dict[str, Any]],
    source_tag: str,
    cohort_name: str,
    enforce_wall_cap: bool,
    audit_log: dict[str, Any],
    tier_filter: str | None = None,
    allowed_seeds: set[int] | None = None,
) -> dict[int, dict[str, Any]]:
    by_seed: dict[int, dict[str, Any]] = {}
    for ep in raw_eps:
        if tier_filter is not None and ep.get("tier") != tier_filter:
            continue
        if allowed_seeds is not None and int(ep.get("seed", -1)) not in allowed_seeds:
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
        audit_log["total_steps_verified"] += int(info["steps_verified"])
        audit_log["total_steps_truncated_checked"] += int(info["steps_truncated_checked"])
        audit_log["total_steps_client_only"] += int(info["steps_client_only"])
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
        frontier_dir / DEFAULT_FRONTIER_DIR,
        frontier_dir / "v1.4",
    ):
        if (
            (candidate / "opencode-gemini-3.5-flash").exists()
            or (candidate / "opencode-gemini-4-carbon").exists()
            or (candidate / "reference").exists()
        ):
            return candidate
    return frontier_dir


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


def _load_committed_primary_cohorts(
    committed_dir: Path,
    audit_log: dict[str, Any],
) -> tuple[dict[str, dict[str, dict[int, dict[str, Any]]]], dict[str, list[dict[str, Any]]]]:
    primary_seed_set = set(PRIMARY_SEEDS)
    solver_raw_med: list[dict[str, Any]] = []
    solver_raw_hard: list[dict[str, Any]] = []
    solver_ref_dirs: dict[str, list[dict[str, Any]]] = {"medium": [], "hard": []}

    for tier, target_list in (("medium", solver_raw_med), ("hard", solver_raw_hard)):
        for f in sorted((committed_dir / "reference").glob(f"solver-{tier}-*/episodes.jsonl")):
            rows = [
                ep
                for ep in _parse_jsonl_lines(f.read_text(encoding="utf-8"))
                if ep.get("tier") == tier and int(ep.get("seed", -1)) in primary_seed_set
            ]
            if not rows:
                continue
            target_list.extend(rows)
            seeds_in_dir = sorted(int(r["seed"]) for r in rows)
            solver_ref_dirs[tier].append({
                "dir": f.parent.name,
                "n": len(seeds_in_dir),
                "seed_min": seeds_in_dir[0],
                "seed_max": seeds_in_dir[-1],
            })

    solver_med = _collect_validated(
        solver_raw_med,
        source_tag="committed_v1.4",
        cohort_name="solver",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="medium",
        allowed_seeds=primary_seed_set,
    )
    solver_hard = _collect_validated(
        solver_raw_hard,
        source_tag="committed_v1.4",
        cohort_name="solver",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="hard",
        allowed_seeds=primary_seed_set,
    )

    carbon_oc_med = _collect_validated(
        _parse_jsonl_lines((committed_dir / "opencode-gemini-4-carbon/medium/episodes.jsonl").read_text(encoding="utf-8")),
        source_tag="committed_v1.4",
        cohort_name="opencode-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="medium",
        allowed_seeds=primary_seed_set,
    )
    carbon_oc_hard = _collect_validated(
        _parse_jsonl_lines((committed_dir / "opencode-gemini-4-carbon/hard/episodes.jsonl").read_text(encoding="utf-8")),
        source_tag="committed_v1.4",
        cohort_name="opencode-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="hard",
        allowed_seeds=primary_seed_set,
    )
    carbon_ip_med = _collect_validated(
        _parse_jsonl_lines((committed_dir / "inproc-gemini-4-carbon/medium/episodes.jsonl").read_text(encoding="utf-8")),
        source_tag="committed_v1.4",
        cohort_name="inproc-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="medium",
        allowed_seeds=primary_seed_set,
    )
    carbon_ip_hard = _collect_validated(
        _parse_jsonl_lines((committed_dir / "inproc-gemini-4-carbon/hard/episodes.jsonl").read_text(encoding="utf-8")),
        source_tag="committed_v1.4",
        cohort_name="inproc-gemini-4-carbon",
        enforce_wall_cap=False,
        audit_log=audit_log,
        tier_filter="hard",
        allowed_seeds=primary_seed_set,
    )
    flash_oc_hard = _collect_validated(
        _parse_jsonl_lines((committed_dir / "opencode-gemini-3.5-flash/hard/episodes.jsonl").read_text(encoding="utf-8")),
        source_tag="committed_v1.4",
        cohort_name="opencode-gemini-3.5-flash",
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter="hard",
        allowed_seeds=primary_seed_set,
    )

    gpt55_cohorts: dict[str, dict[int, dict[str, Any]]] = {}
    gpt55_root = committed_dir / "opencode-gpt-5.5"
    if gpt55_root.is_dir():
        for tier in ("medium", "hard"):
            gpt55_files = sorted(gpt55_root.glob(f"{tier}*/episodes.jsonl"))
            top_ep = gpt55_root / "episodes.jsonl"
            if not gpt55_files and top_ep.is_file():
                gpt55_files = [top_ep]
            raw_gpt55: list[dict[str, Any]] = []
            for gf in gpt55_files:
                raw_gpt55.extend(_parse_jsonl_lines(gf.read_text(encoding="utf-8")))
            if raw_gpt55:
                validated_gpt55 = _collect_validated(
                    raw_gpt55,
                    source_tag="committed_v1.4",
                    cohort_name="opencode-gpt-5.5",
                    enforce_wall_cap=False,
                    audit_log=audit_log,
                    tier_filter=tier,
                    allowed_seeds=primary_seed_set,
                )
                if validated_gpt55:
                    gpt55_cohorts[tier] = validated_gpt55

    det_med: dict[str, dict[int, dict[str, Any]]] = {}
    det_hard: dict[str, dict[int, dict[str, Any]]] = {}
    seeds_0_29 = sorted(solver_med) if solver_med else list(PRIMARY_SEEDS)
    seeds_0_29_hard = sorted(solver_hard) if solver_hard else list(PRIMARY_SEEDS)
    for ag in DETERMINISTIC_BASELINES_0_29:
        det_med[ag] = replay_deterministic_policy(ag, "medium", seeds_0_29, audit_log)
        det_hard[ag] = replay_deterministic_policy(ag, "hard", seeds_0_29_hard, audit_log)

    med_map: dict[str, dict[int, dict[str, Any]]] = {
        "opencode-gemini-4-carbon": carbon_oc_med,
        "inproc-gemini-4-carbon": carbon_ip_med,
    }
    if "medium" in gpt55_cohorts:
        med_map["opencode-gpt-5.5"] = gpt55_cohorts["medium"]
    med_map["solver"] = solver_med
    med_map.update(det_med)

    hard_map: dict[str, dict[int, dict[str, Any]]] = {
        "opencode-gemini-4-carbon": carbon_oc_hard,
        "inproc-gemini-4-carbon": carbon_ip_hard,
        "opencode-gemini-3.5-flash": flash_oc_hard,
    }
    if "hard" in gpt55_cohorts:
        hard_map["opencode-gpt-5.5"] = gpt55_cohorts["hard"]
    hard_map["solver"] = solver_hard
    hard_map.update(det_hard)

    return {"medium": med_map, "hard": hard_map}, solver_ref_dirs


def _load_flash_medium_from_working_tree(
    frontier_base: Path,
    audit_log: dict[str, Any],
) -> tuple[dict[int, dict[str, Any]], dict[str, Any]]:
    flash_root = frontier_base / "opencode-gemini-3.5-flash"
    raw_eps: list[dict[str, Any]] = []
    shards_meta: list[dict[str, Any]] = []
    if flash_root.is_dir():
        for ep_file in sorted(flash_root.glob("medium*/episodes.jsonl")):
            shard_dir = ep_file.parent
            lines = _parse_jsonl_lines(ep_file.read_text(encoding="utf-8"))
            raw_eps.extend(lines)
            meta_file = shard_dir / "meta.json"
            m_obj = json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.is_file() else {}
            shard_seeds = sorted(int(r["seed"]) for r in lines)
            shards_meta.append({
                "shard": shard_dir.name,
                "git_sha": str(m_obj.get("git_sha") or "")[:8] or None,
                "n": len(shard_seeds),
                "seed_min": shard_seeds[0] if shard_seeds else None,
                "seed_max": shard_seeds[-1] if shard_seeds else None,
                "status": m_obj.get("status"),
            })
    validated = _collect_validated(
        raw_eps,
        source_tag="frontier_replication_v1.4",
        cohort_name="opencode-gemini-3.5-flash",
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter="medium",
        allowed_seeds=set(PRIMARY_SEEDS),
    )
    provenance = {
        "commit_brought": "d4bc4f3d",
        "directory": "results/frontier_replication/v1.4/opencode-gemini-3.5-flash",
        "shards": shards_meta,
        "caveat": (
            "Brought from PR 51 in commit d4bc4f3d across three shards at three git SHAs "
            "(medium-00-14 @ c01f371a, medium-15-29 @ 55d9781c, medium-s28 @ a5d12c7e). "
            "Seed 28 failed in medium-15-29 (meta.json status INCOMPLETE: seed [28] pending rerun) "
            "and was re-run alone as medium-s28; its first attempt is not in the committed data."
        ),
    }
    return validated, provenance


def _verify_paired_table_row(summary: dict[str, Any], ref_row: dict[str, Any], label: str) -> None:
    checks: list[tuple[str, Any, Any]] = [
        ("n", summary["n"], ref_row["n"]),
        ("seeds", summary["seeds"], ref_row["seeds"]),
        ("mean_score", summary["mean_score"], ref_row["mean"]),
        ("score_ci95", summary["score_ci95"], ref_row["ci"]),
        ("accuracy", summary["accuracy"], ref_row["accuracy"]),
        ("accused_rate", summary["accused_rate"], ref_row["accused_rate"]),
        ("mean_p_accused", summary["mean_p_accused"], ref_row["p_accused"]),
        ("mean_accuse_day", summary["mean_accuse_day"], ref_row["accuse_day"]),
        ("solver_mean", summary["solver_mean"], ref_row["solver_same_seeds"]),
        ("luck_adjusted_score", summary["luck_adjusted_score"], ref_row["post_expected"]),
        (
            "solver_luck_adjusted_score",
            summary["solver_luck_adjusted_score"],
            ref_row["solver_post_expected"],
        ),
    ]
    if summary["cohort"] != "solver":
        checks.extend([
            ("ratio_vs_solver", summary["ratio_vs_solver"], ref_row["ratio"]),
            ("ratio_ci95_lo", summary["ratio_ci95"][0], ref_row["ratio_lo"]),
            ("ratio_ci95_hi", summary["ratio_ci95"][1], ref_row["ratio_hi"]),
            ("paired_diff", summary["paired_diff"], ref_row["diff"]),
            ("paired_diff_halfwidth95", summary["paired_diff_halfwidth95"], ref_row["diff_ci"]),
            ("luck_adjusted_ratio", summary["luck_adjusted_ratio"], ref_row["post_expected_ratio"]),
            (
                "luck_adjusted_ratio_ci95_lo",
                summary["luck_adjusted_ratio_ci95"][0],
                ref_row["post_expected_lo"],
            ),
            (
                "luck_adjusted_ratio_ci95_hi",
                summary["luck_adjusted_ratio_ci95"][1],
                ref_row["post_expected_hi"],
            ),
        ])
    for field_name, got_val, exp_val in checks:
        if not approx_equal(got_val, exp_val, REPLAY_TOL):
            raise ValueError(
                f"Paired table cross-check mismatch for {label}.{field_name}: "
                f"got={got_val!r} vs committed={exp_val!r}"
            )


def _crosscheck_committed_ext_tables(
    committed_dir: Path,
    ext_summary: dict[str, Any] | None,
    pooled_summary: dict[str, Any],
    solver_30_59_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    ext_json = committed_dir / "opencode-gemini-4-carbon-ext/paired_table_ext30to59.json"
    pooled_json = committed_dir / "opencode-gemini-4-carbon-ext/paired_table_pooled0to59.json"
    if not (ext_json.is_file() and pooled_json.is_file() and ext_summary is not None):
        return {
            "checked": False,
            "ext30to59_match": None,
            "pooled0to59_match": None,
            "solver30to59_match": None,
        }

    ext_rows = json.loads(ext_json.read_text(encoding="utf-8"))
    ext_carbon_ref = next(
        r for r in ext_rows if r.get("group") == "v1.4/opencode-gemini-4-carbon-ext"
    )
    _verify_paired_table_row(ext_summary, ext_carbon_ref, "paired_table_ext30to59.extension")

    solver_match = False
    if solver_30_59_summary is not None:
        ext_solver_ref = next(r for r in ext_rows if r.get("agent") == "solver")
        _verify_paired_table_row(solver_30_59_summary, ext_solver_ref, "paired_table_ext30to59.solver")
        solver_match = True

    pooled_rows = json.loads(pooled_json.read_text(encoding="utf-8"))
    pooled_ref = next(
        r
        for r in pooled_rows
        if r.get("tier") == "hard"
        and "v1.4/opencode-gemini-4-carbon-ext" in str(r.get("group"))
        and "v1.4/opencode-gemini-4-carbon+" in str(r.get("group"))
    )
    _verify_paired_table_row(pooled_summary, pooled_ref, "paired_table_pooled0to59.pooled_hard")

    return {
        "checked": True,
        "ext30to59_match": True,
        "pooled0to59_match": True,
        "solver30to59_match": solver_match,
    }


def compute(
    committed_dir: Path,
    frontier_dir: Path | None = None,
    frontier_ref: str | None = None,
) -> dict[str, Any]:
    _ = frontier_ref
    paired_v13._P_CACHE.clear()
    audit_log = _new_audit_log()

    local_cohorts, solver_ref_dirs = _load_committed_primary_cohorts(committed_dir, audit_log)
    effective_frontier_dir = (
        _resolve_frontier_local_dir(frontier_dir)
        if frontier_dir is not None
        else _resolve_frontier_local_dir(ROOT / DEFAULT_FRONTIER_DIR)
    )
    flash_oc_med, flash_med_prov = _load_flash_medium_from_working_tree(
        effective_frontier_dir, audit_log
    )

    med_solver = local_cohorts["medium"]["solver"]
    hard_solver = local_cohorts["hard"]["solver"]

    primary_cohorts: list[dict[str, Any]] = []
    med_order: list[tuple[str, str, dict[int, dict[str, Any]]]] = [
        ("opencode-gemini-4-carbon", "committed_v1.4", local_cohorts["medium"]["opencode-gemini-4-carbon"]),
        ("inproc-gemini-4-carbon", "committed_v1.4", local_cohorts["medium"]["inproc-gemini-4-carbon"]),
    ]
    if flash_oc_med:
        med_order.append(("opencode-gemini-3.5-flash", "frontier_replication_v1.4", flash_oc_med))
    if "opencode-gpt-5.5" in local_cohorts["medium"]:
        med_order.append(("opencode-gpt-5.5", "committed_v1.4", local_cohorts["medium"]["opencode-gpt-5.5"]))
    med_order.append(("solver", "committed_v1.4", med_solver))
    for ag in DETERMINISTIC_BASELINES_0_29:
        med_order.append((ag, "inproc_deterministic_v1.4", local_cohorts["medium"][ag]))

    for cname, src, cmap in med_order:
        primary_cohorts.append(summarize_cohort(cname, "medium", src, cmap, med_solver))

    hard_order: list[tuple[str, str, dict[int, dict[str, Any]]]] = [
        ("opencode-gemini-4-carbon", "committed_v1.4", local_cohorts["hard"]["opencode-gemini-4-carbon"]),
        ("inproc-gemini-4-carbon", "committed_v1.4", local_cohorts["hard"]["inproc-gemini-4-carbon"]),
        ("opencode-gemini-3.5-flash", "committed_v1.4", local_cohorts["hard"]["opencode-gemini-3.5-flash"]),
    ]
    if "opencode-gpt-5.5" in local_cohorts["hard"]:
        hard_order.append(("opencode-gpt-5.5", "committed_v1.4", local_cohorts["hard"]["opencode-gpt-5.5"]))
    hard_order.append(("solver", "committed_v1.4", hard_solver))
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
    if "opencode-gpt-5.5" in local_cohorts["hard"]:
        head_to_head["hard_carbon_vs_gpt55"] = compute_head_to_head(
            "hard",
            "opencode-gemini-4-carbon",
            local_cohorts["hard"]["opencode-gemini-4-carbon"],
            "opencode-gpt-5.5",
            local_cohorts["hard"]["opencode-gpt-5.5"],
        )

    ext_seed_set = set(EXTENSION_SEEDS)
    ext_ep_path = committed_dir / "opencode-gemini-4-carbon-ext/hard/episodes.jsonl"
    ext_meta_path = committed_dir / "opencode-gemini-4-carbon-ext/hard/meta.json"
    ext_source_tag = "committed_v1.4"
    ext_raw_eps: list[dict[str, Any]] = []
    if ext_ep_path.is_file():
        ext_raw_eps = _parse_jsonl_lines(ext_ep_path.read_text(encoding="utf-8"))
    elif (effective_frontier_dir / "opencode-gemini-4-carbon").is_dir():
        ext_source_tag = "frontier_replication_v1.4"
        for p in sorted((effective_frontier_dir / "opencode-gemini-4-carbon").glob("hard*/episodes.jsonl")):
            ext_raw_eps.extend(_parse_jsonl_lines(p.read_text(encoding="utf-8")))

    carbon_ext_hard = _collect_validated(
        ext_raw_eps,
        source_tag=ext_source_tag,
        cohort_name="opencode-gemini-4-carbon-ext",
        enforce_wall_cap=True,
        audit_log=audit_log,
        tier_filter="hard",
        allowed_seeds=ext_seed_set,
    )

    ext_meta = (
        json.loads(ext_meta_path.read_text(encoding="utf-8"))
        if ext_meta_path.is_file()
        else {}
    )
    excluded_attempts = ext_meta.get("infra_invalid_attempts_excluded") or []
    quota_attempts = [x for x in excluded_attempts if "infra:provider_quota" in str(x)]
    g1_ext_provenance = {
        "pre_registered_commit": "f9fb7a4a",
        "directory": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
        "git_sha": str(ext_meta.get("git_sha") or "")[:8] or None,
        "opencode_version": ext_meta.get("opencode_version"),
        "planned_seeds_count": len(ext_meta.get("planned_seeds") or EXTENSION_SEEDS),
        "completed_valid_seeds": sorted(carbon_ext_hard),
        "infra_invalid_attempts_excluded_count": len(excluded_attempts),
        "infra_provider_quota_attempts_count": len(quota_attempts),
        "status": ext_meta.get("status"),
        "pr51_overlap_note": (
            "Per commit d4bc4f3d, PR 51's 5-seed opencode-gemini-4-carbon hard shard on "
            "origin/fr8/canary/frontier was intentionally not brought into justSilas because it "
            "overlapped this pre-registered G1 seeds 30-59 extension."
        ),
    }

    solver_30_59_file = committed_dir / "reference/solver-hard-seeds30to59/episodes.jsonl"
    frontier_solver_30_59 = effective_frontier_dir / "reference/solver-hard-seeds30to59/episodes.jsonl"
    ref_30_59_validated: dict[str, tuple[str, dict[int, dict[str, Any]]]] = {}

    if solver_30_59_file.is_file():
        sol_map = _collect_validated(
            _parse_jsonl_lines(solver_30_59_file.read_text(encoding="utf-8")),
            source_tag="committed_v1.4",
            cohort_name="solver",
            enforce_wall_cap=True,
            audit_log=audit_log,
            tier_filter="hard",
            allowed_seeds=ext_seed_set,
        )
        ref_30_59_validated["solver"] = ("committed_v1.4", sol_map)
    elif frontier_solver_30_59.is_file():
        sol_map = _collect_validated(
            _parse_jsonl_lines(frontier_solver_30_59.read_text(encoding="utf-8")),
            source_tag="frontier_replication_v1.4",
            cohort_name="solver",
            enforce_wall_cap=True,
            audit_log=audit_log,
            tier_filter="hard",
            allowed_seeds=ext_seed_set,
        )
        ref_30_59_validated["solver"] = ("frontier_replication_v1.4", sol_map)
    else:
        sol_map = replay_deterministic_policy("solver", "hard", list(EXTENSION_SEEDS), audit_log)
        ref_30_59_validated["solver"] = ("inproc_deterministic_v1.4", sol_map)

    solver_30_59 = ref_30_59_validated["solver"][1]
    target_30_59_seeds = sorted(solver_30_59) if solver_30_59 else list(EXTENSION_SEEDS)

    for ag in REPLICATION_REF_ORDER:
        if ag == "solver":
            continue
        comm_ag_file = committed_dir / f"reference/{ag}-hard-seeds30to59/episodes.jsonl"
        front_ag_file = effective_frontier_dir / f"reference/{ag}-hard-seeds30to59/episodes.jsonl"
        if comm_ag_file.is_file():
            ag_map = _collect_validated(
                _parse_jsonl_lines(comm_ag_file.read_text(encoding="utf-8")),
                source_tag="committed_v1.4",
                cohort_name=ag,
                enforce_wall_cap=True,
                audit_log=audit_log,
                tier_filter="hard",
                allowed_seeds=ext_seed_set,
            )
            ref_30_59_validated[ag] = ("committed_v1.4", ag_map)
        elif front_ag_file.is_file():
            ag_map = _collect_validated(
                _parse_jsonl_lines(front_ag_file.read_text(encoding="utf-8")),
                source_tag="frontier_replication_v1.4",
                cohort_name=ag,
                enforce_wall_cap=True,
                audit_log=audit_log,
                tier_filter="hard",
                allowed_seeds=ext_seed_set,
            )
            ref_30_59_validated[ag] = ("frontier_replication_v1.4", ag_map)
        else:
            ag_map = replay_deterministic_policy(ag, "hard", target_30_59_seeds, audit_log)
            ref_30_59_validated[ag] = ("inproc_deterministic_v1.4", ag_map)

    ext_carbon_summary = (
        summarize_cohort(
            "opencode-gemini-4-carbon-ext",
            "hard",
            ext_source_tag,
            carbon_ext_hard,
            solver_30_59,
        )
        if carbon_ext_hard
        else None
    )
    ext_per_seed = [
        {
            "seed": s,
            "score": carbon_ext_hard[s]["score"],
            "solver_score": solver_30_59[s]["score"],
            "correct": carbon_ext_hard[s]["correct"],
            "solver_correct": solver_30_59[s]["correct"],
            "accuse_day": carbon_ext_hard[s]["final_day"] if carbon_ext_hard[s]["accused"] else None,
            "solver_accuse_day": solver_30_59[s]["final_day"] if solver_30_59[s]["accused"] else None,
            "p_accused": carbon_ext_hard[s]["p_accused"],
            "shown_v": carbon_ext_hard[s]["shown_v"],
            "luck_adjusted": carbon_ext_hard[s]["luck_adjusted"],
            "solver_luck_adjusted": solver_30_59[s]["luck_adjusted"],
        }
        for s in sorted(carbon_ext_hard)
        if s in solver_30_59
    ]

    ref_30_59_summaries: list[dict[str, Any]] = []
    for ag in REPLICATION_REF_ORDER:
        if ag in ref_30_59_validated and ref_30_59_validated[ag][1] and solver_30_59:
            src_tag, ag_map = ref_30_59_validated[ag]
            ref_30_59_summaries.append(
                summarize_cohort(ag, "hard", src_tag, ag_map, solver_30_59)
            )

    post_pr16_checks: dict[str, Any] = {}
    if "stop_early" in ref_30_59_validated and ref_30_59_validated["stop_early"][1]:
        se_vals = [x["score"] for x in ref_30_59_validated["stop_early"][1].values()]
        post_pr16_checks["stop_early_all_zero"] = all(abs(v) < REPLAY_TOL for v in se_vals)
        post_pr16_checks["stop_early_mean"] = float(sum(se_vals) / len(se_vals))
    if "do_nothing" in ref_30_59_validated and ref_30_59_validated["do_nothing"][1]:
        dn_vals = [x["score"] for x in ref_30_59_validated["do_nothing"][1].values()]
        post_pr16_checks["do_nothing_all_zero"] = all(abs(v) < REPLAY_TOL for v in dn_vals)
        post_pr16_checks["do_nothing_mean"] = float(sum(dn_vals) / len(dn_vals))

    pooled_carbon = {**local_cohorts["hard"]["opencode-gemini-4-carbon"], **carbon_ext_hard}
    pooled_solver = {**hard_solver, **solver_30_59}
    pooled_summary = summarize_cohort(
        "opencode-gemini-4-carbon-pooled-sensitivity",
        "hard",
        "pooled_secondary_0_29_plus_g1_ext",
        pooled_carbon,
        pooled_solver,
    )
    pooled_summary["status"] = "secondary_sensitivity_only"
    pooled_summary["headline_cohort"] = "primary_0_29/opencode-gemini-4-carbon/hard"

    solver_30_59_summary = next(
        (r for r in ref_30_59_summaries if r["cohort"] == "solver"), None
    )
    crosscheck = _crosscheck_committed_ext_tables(
        committed_dir,
        ext_carbon_summary,
        pooled_summary,
        solver_30_59_summary,
    )

    gpt55_prereg = {
        "pre_registered_commit": "cf394894",
        "model": "gpt-5.5",
        "agent": "opencode:openai/gpt-5.5",
        "opencode_version": "1.19.5",
        "tier": "hard",
        "planned_seeds": "0-29",
        "env_tag": "afterquery-final",
        "stop_time_helsinki": "08:15",
        "spend_cap_usd": 200,
        "committed_dir": "data/runs/committed/v1.4/opencode-gpt-5.5",
        "committed_present": (committed_dir / "opencode-gpt-5.5").is_dir(),
        "completed_n_by_tier": {
            t: len(local_cohorts[t]["opencode-gpt-5.5"])
            for t in ("medium", "hard")
            if "opencode-gpt-5.5" in local_cohorts[t]
        },
    }

    paired_v13._P_CACHE.clear()
    return {
        "schema_version": SCHEMA_VERSION,
        "tiers_version": TIERS_VERSION,
        "authoritative_headline_sources": [
            "docs/reports/gap.md",
            "data/runs/committed/v1.4/paired_table_gemini.md",
        ],
        "bootstrap": {"n_boot": N_BOOT, "seed": BOOT_SEED},
        "data_rule": audit_log,
        "primary_0_29": {
            "seed_lock_note": (
                "Seeds 0-29 per tier were post-hoc locked in commit 671ed96 (28 s after 8fd4dec), "
                "not pre-registered: a post-hoc lock against later reruns and cherry-picking. "
                "docs/reports/gap.md and data/runs/committed/v1.4/paired_table_gemini.md form the "
                "authoritative headline table of record (hard OpenCode gemini-4-carbon n=30: "
                "raw 65% [24%, 98%] first, luck-adjusted 72% [52%, 91%] second; on hard, "
                "access_constraints never binds per docs/DIFFICULTY.md W4). Separately, "
                "the hard seeds 30-59 extension was pre-registered before any episode in f9fb7a4a, "
                "and the gpt-5.5 OpenCode 1.19.5 v1.4 hard run (seeds 0-29, stop 08:15 / $200, tag "
                "afterquery-final) was pre-registered before any episode in cf394894."
            ),
            "solver_reference_dirs": solver_ref_dirs,
            "flash_medium_provenance": flash_med_prov,
            "gpt_5_5_preregistration": gpt55_prereg,
            "cohorts": primary_cohorts,
            "head_to_head": head_to_head,
        },
        "replication_30_59": {
            "extension_pre_registration_note": (
                "Hard seeds 30-59 extension (opencode-gemini-4-carbon-ext) was pre-registered before "
                "any episode in commit f9fb7a4a (docs/reports/gap.md) to be reported (a) strictly "
                "separately on its own and (b) pooled with post-hoc locked primary seeds 0-29 "
                "(671ed96, 28 s after 8fd4dec) as a secondary sensitivity check only, never replacing "
                "the primary n=30 headline row."
            ),
            "solver_reference_dir": "data/runs/committed/v1.4/reference/solver-hard-seeds30to59",
            "g1_extension_provenance": g1_ext_provenance,
            "opencode_gemini_4_carbon_hard_extension": ext_carbon_summary,
            "opencode_gemini_4_carbon_hard_per_seed": ext_per_seed,
            "secondary_pooled_sensitivity_hard": pooled_summary,
            "paired_table_crosscheck": crosscheck,
            "reference_hard_30_59": ref_30_59_summaries,
            "post_pr16_zero_checks": post_pr16_checks,
        },
    }


def _fmt_num(x: float | None, nd: int = 3, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    spec = f"{'+' if signed else ''}.{nd}f"
    return format(x, spec)


def _fmt_pct_ci(r: float | None, ci: list[float] | None, is_solver: bool = False, nd: int = 1) -> str:
    if is_solver or r is None:
        return "100%" if is_solver else "n/a"
    if ci is None:
        return f"{r * 100.0:.{nd}f}%"
    return f"{r * 100.0:.{nd}f}% [{ci[0] * 100.0:.{nd}f}%, {ci[1] * 100.0:.{nd}f}%]"


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
    s_hard = by_key[("hard", "solver")]
    h2h_hard = prim["head_to_head"]["hard"]
    h2h_med = prim["head_to_head"].get("medium")
    h2h_gpt55 = prim["head_to_head"].get("hard_carbon_vs_gpt55")

    gpt55_hard = by_key.get(("hard", "opencode-gpt-5.5"))
    gpt55_pre = prim.get("gpt_5_5_preregistration") or {}
    gpt55_status_note = (
        f"committed (`n={gpt55_hard['n']}` on `hard`)"
        if gpt55_hard is not None
        else "auto-included from `data/runs/committed/v1.4/opencode-gpt-5.5` if committed"
    )

    med_heading = (
        f"{H3} Medium Tier (`seeds 0-29`, `n=30` paired per cohort)"
        if all(r["n"] == 30 for r in med_rows)
        else f"{H3} Medium Tier (`seeds 0-29`; `gemini-3.5-flash` paired on `n={f_med['n'] if f_med else 0}` completed seeds)"
    )
    hard_heading = (
        f"{H3} Hard Tier (`seeds 0-29`, `n=30` paired per cohort)"
        if all(r["n"] == 30 for r in hard_rows)
        else f"{H3} Hard Tier (`seeds 0-29`; `opencode-gpt-5.5` paired on `n={gpt55_hard['n'] if gpt55_hard else 0}` completed seeds)"
    )

    sol_dirs = prim.get("solver_reference_dirs") or {}
    med_dir_desc = ", ".join(
        f"`{d['dir']}` (`{d['seed_min']}-{d['seed_max']}`, `n={d['n']}`)"
        for d in sol_dirs.get("medium") or []
    )
    hard_dir_desc = ", ".join(
        f"`{d['dir']}` (`{d['seed_min']}-{d['seed_max']}`, `n={d['n']}`)"
        for d in sol_dirs.get("hard") or []
    )

    lines: list[str] = [
        f"{H1} Canary v1.4 Cross-Model Comparison and Seeds 30-59 Extension Audit",
        "",
        "Generated deterministically offline from committed working-tree caches (`0` live LLM calls, single-process) by:",
        "```bash",
        "python scripts/eval_replication_and_crossmodel.py",
        "python scripts/eval_replication_and_crossmodel.py --check",
        "```",
        "",
        f"{H2} Headline Anchor and Provenance Discipline",
        "",
        "- **Authoritative headline table of record:** `docs/reports/gap.md` and `data/runs/committed/v1.4/paired_table_gemini.md`.",
        f"- **Primary `hard` headline (`opencode-gemini-4-carbon`, `n={c_hard['n']}`, `seeds 0-29`):** raw **`{_fmt_pct_ci(c_hard['ratio_vs_solver'], c_hard['ratio_ci95'], nd=0)}`** (`{_fmt_pct_ci(c_hard['ratio_vs_solver'], c_hard['ratio_ci95'])}`, `{c_hard['mean_score']:+.3f} +/- {c_hard['score_ci95']:.3f}` vs solver `{s_hard['mean_score']:+.3f} +/- {s_hard['score_ci95']:.3f}`, paired diff `{c_hard['paired_diff']:+.3f} +/- {c_hard['paired_diff_halfwidth95']:.3f}`, bootstrap 95% CI `[{c_hard['paired_diff_ci95'][0]:+.3f}, {c_hard['paired_diff_ci95'][1]:+.3f}]`) first; luck-adjusted **`{_fmt_pct_ci(c_hard['luck_adjusted_ratio'], c_hard['luck_adjusted_ratio_ci95'], nd=0)}`** (`{_fmt_pct_ci(c_hard['luck_adjusted_ratio'], c_hard['luck_adjusted_ratio_ci95'])}`, `{c_hard['luck_adjusted_score']:+.3f}` vs solver `{s_hard['luck_adjusted_score']:+.3f}`) second.",
        f"- **Post-hoc seed lock vs true pre-registrations (Panel Fix A, commits `92708834` and `dcd8c372`):** Primary `seeds 0-29` were **post-hoc locked in `671ed96` (28 s after `8fd4dec`), not pre-registered** (a lock against later reruns and cherry-picking). By contrast, the `seeds 30-59` hard extension (`f9fb7a4a`), the `--hint gather` causal test (`fd8c1cb0`), and the second frontier family `gpt-5.5` OpenCode `{gpt55_pre.get('opencode_version', '1.19.5')}` `v1.4` hard run (`{gpt55_pre.get('pre_registered_commit', 'cf394894')}`, `seeds {gpt55_pre.get('planned_seeds', '0-29')}`, stop `{gpt55_pre.get('stop_time_helsinki', '08:15')}` Helsinki / `${gpt55_pre.get('spend_cap_usd', 200)}` cap, tag `{gpt55_pre.get('env_tag', 'afterquery-final')}`; {gpt55_status_note}) were pre-registered before any episode.",
        "",
        f"{H2} Data Rule and Step-Level Replay Integrity",
        "",
        f"- Rules version verified: `{data['tiers_version']}` (`Env(tier, seed)` step-by-step tool replay + final score tolerance `{audit['replay_score_tol']}`; backward-compatible with Panel Fix D commit `{audit['step_error_detail_compat']}` `invalid arguments` `data.detail` payloads).",
        f"- Working-tree self-contained: `{audit['working_tree_only']}` (zero reliance on unmerged or moving remote git refs).",
        f"- Total episode records inspected and replay-verified: `{audit['total_valid_replayed_episodes']}/{audit['total_inspected_episodes']}` valid (`{audit['total_steps_verified']}` MCP/Env steps verified, `{audit['total_steps_truncated_checked']}` client-truncated byte lengths verified, `{audit['total_steps_client_only']}` client-only unavailable-tool steps skipped, `{len(audit['rejected_episodes'])}` rejected by DATA RULE).",
        f"- Fleet shard wall-clock guard: `wall_s < {audit['fleet_max_wall_s']:.0f}s` (`rc != timeout`, `end_reason != error`, `valid != False`).",
        f"- Primary `0-29` clean completions exceeding 3590s (post-hoc locked in `671ed96`, run prior to the fleet 3600s cap, motivating Harbor's `3600s -> 10800s` bump in commit `512836b9`): `{len(audit['committed_primary_over_3590s_clean_completions'])}` episodes, all `rc=0` and replay-exact.",
        f"- Reference solver `0-29` split (`20 + 10` dirs, strictly filtered to `seeds 0-29` and never mixing committed `solver-hard-seeds30to59` `30-59` `n=30`): medium {med_dir_desc}; hard {hard_dir_desc}; `30-59` extension/replication paired directly against `{rep.get('solver_reference_dir', 'data/runs/committed/v1.4/reference/solver-hard-seeds30to59')}`.",
        "- Hard clearance disclosure (`docs/DIFFICULTY.md` W4 / `92708834`): `access_constraints` on `hard` never binds because `canary_level = 1` while every employee's clearance is `1-3`.",
        f"- Paired bootstrap: `{data['bootstrap']['n_boot']}` resamples over shared seeds (`seed={data['bootstrap']['seed']}`).",
        "",
        f"{H2} Part A: Primary Evaluation (`seeds 0-29`, Post-Hoc Seed Lock `671ed96`)",
        "",
        prim["seed_lock_note"],
        "",
        med_heading,
        "",
        *_cohort_table_md(med_rows),
        "",
    ]

    f_prov = prim.get("flash_medium_provenance") or {}
    if f_med is not None and f_prov.get("shards"):
        shard_bits = ", ".join(
            f"`{s['shard']}` @ `{s['git_sha']}` (`n={s['n']}`"
            + (f", status `{s['status']}`" if s.get("status") else "")
            + ")"
            for s in f_prov["shards"]
        )
        lines.extend([
            f"**Provenance caveat on `opencode-gemini-3.5-flash` medium (`d4bc4f3d`, `{f_med['mean_score']:+.3f} +/- {f_med['score_ci95']:.3f}`, raw `{_fmt_pct_ci(f_med['ratio_vs_solver'], f_med['ratio_ci95'])}`, luck-adjusted `{_fmt_pct_ci(f_med['luck_adjusted_ratio'], f_med['luck_adjusted_ratio_ci95'])}`):** {f_prov['caveat']} Verified working-tree shards: {shard_bits}.",
            "",
        ])

    lines.extend([
        hard_heading,
        "",
        *_cohort_table_md(hard_rows),
        "",
        f"{H3} Head-to-Head Cross-Model Comparison (`opencode-gemini-4-carbon` minus `opencode-gemini-3.5-flash`)",
        "",
        "| tier | n | carbon raw | flash raw | paired raw diff [95% CI] | carbon luck-adj | flash luck-adj | paired luck-adj diff [95% CI] | carbon gambles (lucky) | flash gambles (lucky) | flash minus carbon luck |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])

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

    if h2h_gpt55 is not None:
        lines.extend([
            "",
            f"- **Second frontier family (`opencode-gpt-5.5` on `hard`, `n={h2h_gpt55['n']}`):** carbon minus `gpt-5.5` paired raw diff `{h2h_gpt55['paired_raw_diff']:+.3f}` (`[{h2h_gpt55['paired_raw_diff_ci95'][0]:+.3f}, {h2h_gpt55['paired_raw_diff_ci95'][1]:+.3f}]`), paired luck-adjusted diff `{h2h_gpt55['paired_luck_adjusted_diff']:+.3f}` (`[{h2h_gpt55['paired_luck_adjusted_diff_ci95'][0]:+.3f}, {h2h_gpt55['paired_luck_adjusted_diff_ci95'][1]:+.3f}]`).",
        ])

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
        f"{H2} Part B: Pre-Registered Hard Extension Audit (`seeds 30-59`, Strictly Separated from Headline)",
        "",
        rep["extension_pre_registration_note"],
        "",
    ])

    ext_c = rep["opencode_gemini_4_carbon_hard_extension"]
    pooled = rep["secondary_pooled_sensitivity_hard"]
    g1_prov = rep["g1_extension_provenance"]
    xchk = rep["paired_table_crosscheck"]
    if ext_c is not None:
        lines.extend([
            f"{H3} Committed G1 Extension (`opencode-gemini-4-carbon-ext` on Valid Seeds `{ext_c['seeds']}`) and Secondary Pooled Sensitivity (`n={pooled['n']}`)",
            "",
            *_cohort_table_md([ext_c, pooled]),
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
            f" (vs `{rep['reference_hard_30_59'][0]['mean_score']:+.3f} +/- {rep['reference_hard_30_59'][0]['score_ci95']:.3f}` across all 30 seeds `30-59`)"
            if rep["reference_hard_30_59"]
            else ""
        )
        lines.extend([
            "",
            f"- **G1 extension provenance (`f9fb7a4a` / PR 60):** `{ext_c['n']}` valid episodes completed (`seeds={ext_c['seeds']}`, raw `{_fmt_pct_ci(ext_c['ratio_vs_solver'], ext_c['ratio_ci95'], nd=0)}` / `{_fmt_pct_ci(ext_c['ratio_vs_solver'], ext_c['ratio_ci95'])}`, luck-adjusted `{_fmt_pct_ci(ext_c['luck_adjusted_ratio'], ext_c['luck_adjusted_ratio_ci95'], nd=0)}` / `{_fmt_pct_ci(ext_c['luck_adjusted_ratio'], ext_c['luck_adjusted_ratio_ci95'])}`) before early stop at `03:22` Helsinki to preserve shared carbon quota for the judge rehearsal; `{g1_prov['infra_provider_quota_attempts_count']}`/`{g1_prov['infra_invalid_attempts_excluded_count']}` excluded attempts hit `infra:provider_quota` (`meta.json` git SHA `{g1_prov['git_sha']}`). {g1_prov['pr51_overlap_note']}",
            f"- **Secondary pooled sensitivity (`n={pooled['n']}`, `seeds 0-29 + {ext_c['seeds']}`):** `{pooled['mean_score']:+.3f} +/- {pooled['score_ci95']:.3f}` vs solver `{pooled['solver_mean']:+.3f}`{ref_sol_note}, raw `{_fmt_pct_ci(pooled['ratio_vs_solver'], pooled['ratio_ci95'], nd=0)}` (`{_fmt_pct_ci(pooled['ratio_vs_solver'], pooled['ratio_ci95'])}`), paired diff `{pooled['paired_diff']:+.3f} +/- {pooled['paired_diff_halfwidth95']:.3f}` (bootstrap 95% CI `[{pooled['paired_diff_ci95'][0]:+.3f}, {pooled['paired_diff_ci95'][1]:+.3f}]`), luck-adjusted `{_fmt_pct_ci(pooled['luck_adjusted_ratio'], pooled['luck_adjusted_ratio_ci95'], nd=0)}` (`{_fmt_pct_ci(pooled['luck_adjusted_ratio'], pooled['luck_adjusted_ratio_ci95'])}`). Cross-check against `paired_table_{{ext30to59,pooled0to59}}.json`: `checked={xchk['checked']}`, `ext_match={xchk['ext30to59_match']}`, `pooled_match={xchk['pooled0to59_match']}`, `solver30to59_match={xchk['solver30to59_match']}`. Per the post-hoc seed lock (`671ed96`) and pre-registered extension rule (`f9fb7a4a`), `primary_0_29` (`n=30`) remains the sole headline.",
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline v1.4 cross-model and seeds 30-59 extension audit.")
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
        fresh = compute(committed_dir, frontier_dir=frontier_dir, frontier_ref=args.frontier_ref)
        fresh_roundtrip = json.loads(serialize_payload(fresh))
        if not approx_equal(stored, fresh_roundtrip):
            print(f"{out_json} differs from fresh computation beyond {REPLAY_TOL}", file=sys.stderr)
            return 1
        fresh_md = render_markdown(fresh_roundtrip)
        if out_md.read_text(encoding="utf-8") != fresh_md:
            print(f"{out_md} differs from fresh Markdown render", file=sys.stderr)
            return 1
        print("crossmodel and replication check passed (working-tree Part A + Part B + MD verified)")
        return 0

    data = compute(committed_dir, frontier_dir=frontier_dir, frontier_ref=args.frontier_ref)
    blob = serialize_payload(data)
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
