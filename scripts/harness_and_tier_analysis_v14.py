"""2x2 Harness x Tier crossover and set-elimination vs noisy-Bayes analysis on committed v1.4 runs.

Usage:
    /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/harness_and_tier_analysis_v14.py
    /tmp/fleet-silas/shared/agent-arena-venv/bin/python scripts/harness_and_tier_analysis_v14.py --check
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import json
import math
import os
import random
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault("CANARY_ALLOW_DEV", "1")

from canary.env import Env
from canary.rules import TIERS, tier_params_for_episode
from canary.solver.policy import SolverPolicy, accuse_value
from canary.types import INVESTIGATIVE_TOOLS, Step

V14 = ROOT / "data/runs/committed/v1.4"
SEEDS = list(range(30))
BOOT_RESAMPLES = 10000
BOOT_SEED = 0
MAX_JSON_BYTES = 80000

DEFAULT_OUT_JSON = ROOT / "results/eval_v14/harness_and_tier_v14.json"
DEFAULT_OUT_MD = ROOT / "docs/reports/medium_vs_hard_and_harness_v14.md"

CELL_SOURCES: dict[tuple[str, str], tuple[str, list[str]]] = {
    ("medium", "opencode"): (
        "opencode:google/gemini-4-carbon",
        ["data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl"],
    ),
    ("medium", "inproc"): (
        "gemini:gemini-4-carbon",
        ["data/runs/committed/v1.4/inproc-gemini-4-carbon/medium/episodes.jsonl"],
    ),
    ("medium", "solver"): (
        "solver",
        [
            "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
            "data/runs/committed/v1.4/reference/solver-medium-seeds20to29/episodes.jsonl",
        ],
    ),
    ("hard", "opencode"): (
        "opencode:google/gemini-4-carbon",
        ["data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"],
    ),
    ("hard", "inproc"): (
        "gemini:gemini-4-carbon",
        ["data/runs/committed/v1.4/inproc-gemini-4-carbon/hard/episodes.jsonl"],
    ),
    ("hard", "solver"): (
        "solver",
        [
            "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
            "data/runs/committed/v1.4/reference/solver-hard-seeds20to29/episodes.jsonl",
        ],
    ),
}

GPT55_HARD_SOURCE: tuple[str, list[str]] = (
    "opencode:openai/gpt-5.5",
    ["data/runs/committed/v1.4/opencode-gpt-5.5/hard/episodes.jsonl"],
)
HARBOR_REHEARSAL_DIR = "results/harbor/rehearsal"

MD_H1 = "\x23 "
MD_H2 = "\x23\x23 "
MD_H3 = "\x23\x23\x23 "


def step_ok(s: Step) -> bool:
    return bool((s.result or {}).get("ok"))


def steps_of(ep: dict) -> list[Step]:
    return [Step(**{k: s.get(k) for k in ("t", "day", "tool", "args", "result")}) for s in (ep.get("steps") or [])]


def load_cell(tier: str, agent: str, rel_paths: list[str], root: Path = ROOT) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for rel in rel_paths:
        path = root / rel
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            if ep.get("tier") != tier or ep.get("agent") != agent:
                continue
            if (ep.get("meta") or {}).get("valid") is False:
                continue
            out[int(ep["seed"])] = ep
    return out


def replay_env(tier: str, seed: int, steps: list[Step]) -> Env:
    env = Env(tier, seed)
    for s in steps:
        if env.done:
            break
        env.call(s.tool, s.args or {})
    return env


def shannon_split_entropy_bits(assignment: dict[str, str]) -> float:
    m = len(assignment)
    if m <= 1:
        return 0.0
    counts: dict[str, int] = {}
    for label in assignment.values():
        counts[label] = counts.get(label, 0) + 1
    return -sum((c / m) * math.log2(c / m) for c in counts.values() if c > 0)


def canary_assignments(steps: list[Step], upto: int) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for s in steps[:upto]:
        if s.tool == "plant_canary" and step_ok(s):
            cid = ((s.result or {}).get("data") or {}).get("canary_id")
            if cid:
                out[str(cid)] = dict((s.args or {}).get("assignment") or {})
    return out


def last_leak_feed(steps: list[Step], upto: int) -> list[dict]:
    feed: list[dict] = []
    for s in steps[:upto]:
        if s.tool == "check_leak_feed" and step_ok(s):
            feed = list(((s.result or {}).get("data") or {}).get("items") or [])
    return feed


def strict_consistent_set(env: Env, steps: list[Step], upto: int) -> list[str]:
    asg = canary_assignments(steps, upto)
    docs = env._doc_by_id
    cand = set(env._ids)
    for it in last_leak_feed(steps, upto):
        did = it.get("doc_id")
        if it.get("variant") is not None and did in asg:
            cand &= {emp for emp, lab in asg[did].items() if lab == it["variant"]}
        elif did in docs:
            cand &= set(docs[did].get("recipients") or [])
    return sorted(cand)


def first_isolated_day(env: Env, steps: list[Step], upto: int) -> int | None:
    asg = canary_assignments(steps, upto)
    docs = env._doc_by_id
    for s in steps[:upto]:
        if s.tool == "check_leak_feed" and step_ok(s):
            items = list(((s.result or {}).get("data") or {}).get("items") or [])
            cand = set(env._ids)
            for it in items:
                did = it.get("doc_id")
                if it.get("variant") is not None and did in asg:
                    cand &= {emp for emp, lab in asg[did].items() if lab == it["variant"]}
                elif did in docs:
                    cand &= set(docs[did].get("recipients") or [])
            if len(cand) == 1:
                return int(s.day)
    return None


def world_flips(env: Env) -> list[dict]:
    out: list[dict] = []
    docs = env._doc_by_id
    mole = env._world.mole
    for it in env._feed:
        d = docs.get(it["doc_id"])
        if d and d.get("is_canary") and "variant" in it:
            true_v = next(k for k, v in d["variants"].items() if mole in v)
            if it["variant"] != true_v:
                out.append({
                    "doc_id": it["doc_id"],
                    "shown": it["variant"],
                    "true": true_v,
                    "surfaced_day": int(it["surfaced_day"]),
                })
    return out


def analyze_episode(tier: str, harness: str, ep: dict) -> dict:
    seed = int(ep["seed"])
    steps = steps_of(ep)
    env = replay_env(tier, seed, steps)
    if abs(env.score() - float(ep["score"])) > 1e-9 or env._accused != ep.get("accused"):
        raise SystemExit(f"replay mismatch: {tier}/{harness} seed {seed}: {env.score()} vs {ep['score']}")

    params = TIERS[tier]
    acc_idx = next((i for i, s in enumerate(steps) if s.tool == "accuse" and step_ok(s)), None)
    upto = acc_idx if acc_idx is not None else len(steps)
    accused = ep.get("accused")
    mole = env._world.mole
    correct = bool(ep.get("correct"))
    accuse_day = int(steps[acc_idx].day) if acc_idx is not None else None
    raw_final_day = int(ep["final_day"])
    final_day = raw_final_day if raw_final_day > 0 else int(env.day)
    played_days = accuse_day if accuse_day is not None else final_day

    cans_all = [s for s in steps if s.tool == "plant_canary" and step_ok(s)]
    cans_before = [s for s in steps[:upto] if s.tool == "plant_canary" and step_ok(s)]

    by_day_can: dict[int, int] = {}
    by_day_act: dict[int, int] = {}
    by_day_int: dict[int, int] = {}
    tool_counts: dict[str, int] = {}
    ok_tool_counts: dict[str, int] = {}
    for idx, s in enumerate(steps):
        tool_counts[s.tool] = tool_counts.get(s.tool, 0) + 1
        if step_ok(s):
            ok_tool_counts[s.tool] = ok_tool_counts.get(s.tool, 0) + 1
            if idx < upto:
                if s.tool == "plant_canary":
                    by_day_can[s.day] = by_day_can.get(s.day, 0) + 1
                if s.tool in INVESTIGATIVE_TOOLS:
                    by_day_act[s.day] = by_day_act.get(s.day, 0) + 1
                if s.tool == "interview":
                    by_day_int[s.day] = by_day_int.get(s.day, 0) + 1

    days_ge1_can = sum(1 for d in range(1, played_days + 1) if by_day_can.get(d, 0) >= 1)
    days_2_can = sum(1 for d in range(1, played_days + 1) if by_day_can.get(d, 0) >= 2)
    days_lt_cap = sum(1 for d in range(1, played_days + 1) if by_day_can.get(d, 0) < params.canaries_per_day)
    days_lt_cap_full = sum(
        1
        for d in range(1, played_days + 1)
        if by_day_can.get(d, 0) < params.canaries_per_day and by_day_act.get(d, 0) >= params.actions_per_day
    )
    interviews_on_lt_cap_full = sum(
        by_day_int.get(d, 0)
        for d in range(1, played_days + 1)
        if by_day_can.get(d, 0) < params.canaries_per_day and by_day_act.get(d, 0) >= params.actions_per_day
    )

    group_sizes = [len(s.args["assignment"]) for s in cans_before]
    variant_counts = [len(set(s.args["assignment"].values())) for s in cans_before]
    entropies_bits = [shannon_split_entropy_bits(s.args["assignment"]) for s in cans_before]
    covered = set().union(*[set(s.args["assignment"]) for s in cans_before]) if cans_before else set()
    first_can_day = min((int(s.day) for s in cans_before), default=None)

    cset = strict_consistent_set(env, steps, upto)
    first_c1 = first_isolated_day(env, steps, upto)
    feed_items = last_leak_feed(steps, upto)
    asg = canary_assignments(steps, upto)
    seen_canary_leaks = sum(1 for it in feed_items if it.get("variant") is not None and it.get("doc_id") in asg)
    seen_flips = []
    for it in feed_items:
        did = it.get("doc_id")
        if it.get("variant") is not None and did in asg:
            mv = asg[did].get(mole)
            if mv is not None and mv != it["variant"]:
                seen_flips.append({
                    "doc_id": did,
                    "surfaced_day": int(it["surfaced_day"]),
                    "shown": it["variant"],
                    "true": mv,
                })

    t_cut = steps[acc_idx].t if acc_idx is not None else 10**9
    leaks_before = sum(1 for x in env.ledger() if x.event == "leak" and x.t <= t_cut)

    sp = SolverPolicy(tier_params_for_episode(tier, steps))
    for prev in steps[:upto]:
        sp._ingest(prev)
    post = sp.belief() if sp.obs.employees else {}
    top_emp = max(post, key=post.get) if post else None
    p_top = float(post[top_emp]) if top_emp is not None else None
    exp_v = float(sp.expected_true_V()) if post else float(env.V)

    if acc_idx is not None and accused is not None:
        p_acc = float(post.get(accused, 0.0))
        p_acc_round3 = round(p_acc, 3)
        ev_acc = float(accuse_value(p_acc, exp_v, sp.P))
        luck_adj = float(p_acc * env.V - (1.0 - p_acc))
        luck_adj_round3 = float(p_acc_round3 * env.V - (1.0 - p_acc_round3))
    else:
        p_acc = None
        p_acc_round3 = None
        ev_acc = None
        luck_adj = 0.0
        luck_adj_round3 = 0.0

    ev_top = float(accuse_value(p_top, exp_v, sp.P)) if p_top is not None else None

    return {
        "tier": tier,
        "harness": harness,
        "seed": seed,
        "score": float(ep["score"]),
        "luck_adjusted": luck_adj,
        "luck_adjusted_round3": luck_adj_round3,
        "true_V_end": float(env.V),
        "meta_V_final": (ep.get("meta") or {}).get("V_final"),
        "accused": accused,
        "mole": mole,
        "decoy": env._world.decoy,
        "correct": correct,
        "end_reason": str(ep["end_reason"]),
        "accuse_day": accuse_day,
        "recorded_final_day": raw_final_day,
        "final_day": final_day,
        "played_days": played_days,
        "leaks_before": leaks_before,
        "canaries_before": len(cans_before),
        "canaries_total": len(cans_all),
        "plant_canary_calls": tool_counts.get("plant_canary", 0),
        "days_ge1_canary": days_ge1_can,
        "days_2_canaries": days_2_can,
        "days_lt_cap": days_lt_cap,
        "days_lt_cap_full": days_lt_cap_full,
        "interviews_on_lt_cap_full": interviews_on_lt_cap_full,
        "first_canary_day": first_can_day,
        "group_sizes": group_sizes,
        "variant_counts": variant_counts,
        "entropies_bits": entropies_bits,
        "staff_covered": len(covered),
        "interviews": tool_counts.get("interview", 0),
        "feed_calls": ok_tool_counts.get("check_leak_feed", 0),
        "log_calls": ok_tool_counts.get("read_access_logs", 0) + ok_tool_counts.get("get_access_logs", 0),
        "doc_calls": ok_tool_counts.get("list_documents", 0),
        "msg_search_calls": ok_tool_counts.get("search_messages", 0),
        "restrict_calls": ok_tool_counts.get("restrict_access", 0),
        "total_calls": len(steps),
        "invalid_calls": sum(1 for s in steps if not step_ok(s)),
        "consistent_set": cset,
        "consistent_size": len(cset),
        "mole_in_consistent": mole in cset,
        "first_c1_day": first_c1,
        "seen_canary_leaks": seen_canary_leaks,
        "seen_flips": seen_flips,
        "world_flips": world_flips(env),
        "p_accused": p_acc,
        "ev_accused": ev_acc,
        "top_emp": top_emp,
        "p_top": p_top,
        "ev_top": ev_top,
    }


def mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else float("nan")


def median(xs: list[float]) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    m = len(s) // 2
    return float(s[m]) if len(s) % 2 == 1 else float(0.5 * (s[m - 1] + s[m]))


def norm_ci95(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    var = sum((x - m) ** 2 for x in xs) / (n - 1)
    return 1.96 * math.sqrt(var / n)


@lru_cache(maxsize=16)
def _boot_indices(n: int, b_resamples: int, rng_seed: int) -> np.ndarray:
    rng = random.Random(rng_seed)
    rows = [[rng.randrange(n) for _ in range(n)] for _ in range(b_resamples)]
    return np.asarray(rows, dtype=np.int64)


@lru_cache(maxsize=16)
def _indep_boot_indices(nh: int, nm: int, b_resamples: int, rng_seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(rng_seed)
    return rng.integers(0, nh, size=(b_resamples, nh)), rng.integers(0, nm, size=(b_resamples, nm))


def boot_mean_ci(xs: list[float], b_resamples: int = BOOT_RESAMPLES, rng_seed: int = BOOT_SEED) -> tuple[float, float]:
    n = len(xs)
    idx = _boot_indices(n, b_resamples, rng_seed)
    arr = np.asarray(xs, dtype=np.float64)
    vals = np.sort(arr[idx].mean(axis=1))
    return float(vals[int(0.025 * len(vals))]), float(vals[int(0.975 * len(vals)) - 1])


def boot_ratio_ci(
    num: list[float],
    den: list[float],
    b_resamples: int = BOOT_RESAMPLES,
    rng_seed: int = BOOT_SEED,
) -> tuple[float, float]:
    n = len(num)
    idx = _boot_indices(n, b_resamples, rng_seed)
    num_m = np.asarray(num, dtype=np.float64)[idx].mean(axis=1)
    den_m = np.asarray(den, dtype=np.float64)[idx].mean(axis=1)
    valid = num_m[den_m > 0.0] / den_m[den_m > 0.0]
    vals = np.sort(valid)
    return float(vals[int(0.025 * len(vals))]), float(vals[int(0.975 * len(vals)) - 1])


def paired_contrast(
    a_vals: list[float],
    b_vals: list[float],
    b_resamples: int = BOOT_RESAMPLES,
    rng_seed: int = BOOT_SEED,
) -> dict:
    if len(a_vals) != len(b_vals):
        raise ValueError("paired vectors must have equal length")
    diffs = [float(a - b) for a, b in zip(a_vals, b_vals)]
    n = len(diffs)
    pt = sum(diffs) / n
    sd = math.sqrt(sum((d - pt) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 0 else 0.0
    idx = _boot_indices(n, b_resamples, rng_seed)
    boots = np.sort(np.asarray(diffs, dtype=np.float64)[idx].mean(axis=1))
    lo = float(boots[int(0.025 * len(boots))])
    hi = float(boots[int(0.975 * len(boots)) - 1])
    le_zero = float(np.mean(boots <= 0.0))
    ge_zero = float(np.mean(boots >= 0.0))
    p_two = min(1.0, 2.0 * min(le_zero, ge_zero))
    return {
        "n": n,
        "point": round(pt, 6),
        "sum_30_seeds": round(sum(diffs), 6),
        "se": round(se, 6),
        "norm_ci95_halfwidth": round(1.96 * se, 6),
        "boot_ci95": [round(lo, 6), round(hi, 6)],
        "p_boot_two_sided": round(p_two, 6),
        "seed_wins_pos": sum(1 for d in diffs if d > 1e-12),
        "seed_wins_neg": sum(1 for d in diffs if d < -1e-12),
        "seed_ties": sum(1 for d in diffs if abs(d) <= 1e-12),
    }


def indep_tier_did_boot_ci(
    hard_diffs: list[float],
    med_diffs: list[float],
    b_resamples: int = BOOT_RESAMPLES,
    rng_seed: int = BOOT_SEED,
) -> list[float]:
    nh, nm = len(hard_diffs), len(med_diffs)
    ih, im = _indep_boot_indices(nh, nm, b_resamples, rng_seed)
    hm = np.asarray(hard_diffs, dtype=np.float64)[ih].mean(axis=1)
    mm = np.asarray(med_diffs, dtype=np.float64)[im].mean(axis=1)
    boots = np.sort(hm - mm)
    return [round(float(boots[int(0.025 * len(boots))]), 6), round(float(boots[int(0.975 * len(boots)) - 1]), 6)]


def summarize_cell(tier: str, harness: str, eps: list[dict], solver_eps: list[dict]) -> dict:
    params = TIERS[tier]
    n = len(eps)
    raw = [r["score"] for r in eps]
    la = [r["luck_adjusted"] for r in eps]
    la_r3 = [r["luck_adjusted_round3"] for r in eps]
    s_raw = [r["score"] for r in solver_eps]
    s_la = [r["luck_adjusted"] for r in solver_eps]

    acc = [r for r in eps if r["accused"] is not None]
    abstained = [r for r in eps if r["accused"] is None]
    wrong = [r for r in acc if not r["correct"]]

    can_before = [float(r["canaries_before"]) for r in eps]
    played = [r["played_days"] for r in eps]
    tot_played = sum(played)

    ep_grp_means = [mean([ float(x) for x in r["group_sizes"] ]) for r in eps if r["group_sizes"]]
    ep_var_means = [mean([ float(x) for x in r["variant_counts"] ]) for r in eps if r["variant_counts"]]
    ep_ent_bits = [mean(r["entropies_bits"]) for r in eps if r["entropies_bits"]]

    all_grps = [float(x) for r in eps for x in r["group_sizes"]]
    all_vars = [float(x) for r in eps for x in r["variant_counts"]]
    all_ents = [float(x) for r in eps for x in r["entropies_bits"]]

    ps = [r["p_accused"] for r in acc if r["p_accused"] is not None]
    evs = [r["ev_accused"] for r in acc if r["ev_accused"] is not None]
    waits = [
        float(r["accuse_day"] - r["first_c1_day"])
        for r in acc
        if r["first_c1_day"] is not None and r["accuse_day"] is not None
    ]

    is_solver = harness == "solver"
    raw_ratio = (sum(raw) / sum(s_raw)) if sum(s_raw) > 0 else float("nan")
    la_ratio = (sum(la) / sum(s_la)) if sum(s_la) > 0 else float("nan")
    raw_r_lo, raw_r_hi = (1.0, 1.0) if is_solver else boot_ratio_ci(raw, s_raw)
    la_r_lo, la_r_hi = (1.0, 1.0) if is_solver else boot_ratio_ci(la, s_la)
    vs_s_raw = paired_contrast(raw, s_raw)
    vs_s_la = paired_contrast(la, s_la)
    raw_b_lo, raw_b_hi = boot_mean_ci(raw)
    la_b_lo, la_b_hi = boot_mean_ci(la)

    ln2 = math.log(2.0)
    return {
        "tier": tier,
        "harness": harness,
        "n": n,
        "raw_mean": round(mean(raw), 6),
        "raw_ci95_norm": round(norm_ci95(raw), 6),
        "raw_boot_ci95": [round(raw_b_lo, 6), round(raw_b_hi, 6)],
        "luck_adjusted_mean": round(mean(la), 6),
        "luck_adjusted_round3_mean": round(mean(la_r3), 6),
        "luck_adjusted_ci95_norm": round(norm_ci95(la), 6),
        "luck_adjusted_boot_ci95": [round(la_b_lo, 6), round(la_b_hi, 6)],
        "luck_realization_mean": round(mean([a - b for a, b in zip(raw, la)]), 6),
        "luck_realization_sum": round(sum(a - b for a, b in zip(raw, la)), 6),
        "vs_solver_raw_ratio": round(raw_ratio, 6),
        "vs_solver_raw_ratio_boot_ci95": [round(raw_r_lo, 6), round(raw_r_hi, 6)],
        "vs_solver_raw_diff": vs_s_raw,
        "vs_solver_luck_adjusted_ratio": round(la_ratio, 6),
        "vs_solver_luck_adjusted_ratio_boot_ci95": [round(la_r_lo, 6), round(la_r_hi, 6)],
        "vs_solver_luck_adjusted_diff": vs_s_la,
        "accused_count": len(acc),
        "correct_count": sum(1 for r in eps if r["correct"]),
        "wrong_count": len(wrong),
        "abstained_count": len(abstained),
        "accused_rate": round(len(acc) / n, 6),
        "abstention_rate": round(len(abstained) / n, 6),
        "accuracy": round(sum(1 for r in eps if r["correct"]) / n, 6),
        "conditional_accuracy": round((len(acc) - len(wrong)) / len(acc), 6) if acc else 0.0,
        "abstained_seeds": [r["seed"] for r in abstained],
        "wrong_seeds": [r["seed"] for r in wrong],
        "accuse_day_accused_mean": round(mean([float(r["accuse_day"]) for r in acc]), 6) if acc else None,
        "accuse_day_with_horizon_mean": round(mean([float(x) for x in played]), 6),
        "canaries_before_accuse_mean": round(mean(can_before), 6),
        "canaries_before_accuse_ci95": round(norm_ci95(can_before), 6),
        "canaries_total_mean": round(mean([float(r["canaries_total"]) for r in eps]), 6),
        "days_with_ge1_canary_mean": round(mean([float(r["days_ge1_canary"]) for r in eps]), 6),
        "days_with_ge1_canary_share": round(sum(r["days_ge1_canary"] for r in eps) / tot_played, 6),
        "days_with_2_canaries_mean": round(mean([float(r["days_2_canaries"]) for r in eps]), 6),
        "days_with_2_canaries_share": round(sum(r["days_2_canaries"] for r in eps) / tot_played, 6),
        "canary_capacity_used_share": round(
            sum(r["canaries_before"] for r in eps) / (params.canaries_per_day * tot_played), 6
        ),
        "first_canary_day_mean": round(
            mean([float(r["first_canary_day"]) for r in eps if r["first_canary_day"] is not None]), 6
        ),
        "canary_group_size_mean": round(mean(ep_grp_means), 6) if ep_grp_means else 0.0,
        "canary_group_size_pooled_mean": round(mean(all_grps), 6) if all_grps else 0.0,
        "canary_group_recipient_share_mean": round(mean(ep_grp_means) / params.n_employees, 6) if ep_grp_means else 0.0,
        "canary_variant_count_mean": round(mean(ep_var_means), 6) if ep_var_means else 0.0,
        "canary_variant_count_pooled_mean": round(mean(all_vars), 6) if all_vars else 0.0,
        "canary_split_entropy_bits_mean": round(mean(ep_ent_bits), 6) if ep_ent_bits else 0.0,
        "canary_split_entropy_nats_mean": round(mean(ep_ent_bits) * ln2, 6) if ep_ent_bits else 0.0,
        "canary_split_entropy_pooled_bits_mean": round(mean(all_ents), 6) if all_ents else 0.0,
        "staff_covered_mean": round(mean([float(r["staff_covered"]) for r in eps]), 6),
        "staff_covered_share": round(mean([float(r["staff_covered"]) for r in eps]) / params.n_employees, 6),
        "interviews_mean": round(mean([float(r["interviews"]) for r in eps]), 6),
        "check_leak_feed_calls_mean": round(mean([float(r["feed_calls"]) for r in eps]), 6),
        "read_access_logs_calls_mean": round(mean([float(r["log_calls"]) for r in eps]), 6),
        "list_documents_calls_mean": round(mean([float(r["doc_calls"]) for r in eps]), 6),
        "search_messages_calls_mean": round(mean([float(r["msg_search_calls"]) for r in eps]), 6),
        "restrict_access_calls_mean": round(mean([float(r["restrict_calls"]) for r in eps]), 6),
        "total_tool_calls_mean": round(mean([float(r["total_calls"]) for r in eps]), 6),
        "invalid_tool_calls_mean": round(mean([float(r["invalid_calls"]) for r in eps]), 6),
        "total_active_days": tot_played,
        "days_lt_cap_count": sum(r["days_lt_cap"] for r in eps),
        "days_lt_cap_full_budget_count": sum(r["days_lt_cap_full"] for r in eps),
        "interviews_on_lt_cap_full_days": sum(r["interviews_on_lt_cap_full"] for r in eps),
        "leaks_before_accuse_mean": round(mean([float(r["leaks_before"]) for r in acc]), 6) if acc else 0.0,
        "seen_canary_leaks_mean": round(mean([float(r["seen_canary_leaks"]) for r in eps]), 6),
        "consistent_size_at_accuse_mean": round(mean([float(r["consistent_size"]) for r in acc]), 6) if acc else None,
        "consistent_size_at_accuse_median": median([float(r["consistent_size"]) for r in acc]),
        "consistent_eq_0_at_accuse": sum(1 for r in acc if r["consistent_size"] == 0),
        "consistent_eq_1_at_accuse": sum(1 for r in acc if r["consistent_size"] == 1),
        "consistent_eq_1_share_of_accused": round(
            sum(1 for r in acc if r["consistent_size"] == 1) / len(acc), 6
        ) if acc else 0.0,
        "consistent_gt_1_at_accuse": sum(1 for r in acc if r["consistent_size"] > 1),
        "mole_in_consistent_at_accuse_count": sum(1 for r in acc if r["mole_in_consistent"]),
        "mole_excluded_from_consistent_at_accuse_count": sum(1 for r in acc if not r["mole_in_consistent"]),
        "episodes_with_seen_flip_count": sum(1 for r in eps if r["seen_flips"]),
        "episodes_with_seen_flip_seeds": [r["seed"] for r in eps if r["seen_flips"]],
        "wait_days_after_first_c1_mean": round(mean(waits), 6) if waits else 0.0,
        "hesitated_after_c1_count": sum(1 for w in waits if w > 0),
        "p_accused_mean": round(mean(ps), 6) if ps else None,
        "p_accused_median": round(median(ps), 6) if ps else None,
        "p_accused_buckets": {
            "ge_0.95": sum(1 for p in ps if p >= 0.95),
            "0.85_to_0.95": sum(1 for p in ps if 0.85 <= p < 0.95),
            "0.60_to_0.85": sum(1 for p in ps if 0.60 <= p < 0.85),
            "lt_0.60": sum(1 for p in ps if p < 0.60),
        },
        "p_accused_ge_0.85_count": sum(1 for p in ps if p >= 0.85),
        "p_accused_lt_0.85_count": sum(1 for p in ps if p < 0.85),
        "ev_accused_mean": round(mean(evs), 6) if evs else None,
        "ev_negative_accuse_count": sum(1 for r in acc if r["ev_accused"] is not None and r["ev_accused"] < 0),
        "ev_negative_accuse_seeds": [r["seed"] for r in acc if r["ev_accused"] is not None and r["ev_accused"] < 0],
        "expected_wrong_from_posteriors": round(sum(1.0 - p for p in ps), 6),
        "abstained_p_top_end_mean": round(
            mean([r["p_top"] for r in abstained if r["p_top"] is not None]), 6
        ) if abstained else None,
        "abstained_consistent_size_end_mean": round(
            mean([float(r["consistent_size"]) for r in abstained]), 6
        ) if abstained else None,
    }


def decompose_pair(tier: str, a_eps: list[dict], b_eps: list[dict]) -> dict:
    params = TIERS[tier]
    leak_dmg = params.leak_damage
    can_cost = params.canary_cost
    leak_term = 0.0
    canary_term = 0.0
    restrict_term = 0.0
    penalty_term = 0.0
    a_only_accused = 0.0
    a_abstained = 0.0
    both_accused = 0
    both_abstained = 0
    a_only_seeds: list[int] = []
    a_abstained_seeds: list[int] = []

    for ra, rb in zip(a_eps, b_eps):
        a_acc = ra["accused"] is not None
        b_acc = rb["accused"] is not None
        if a_acc and b_acc:
            both_accused += 1
            va, la_cnt, ca_cnt, pa = ra["true_V_end"], ra["leaks_before"], ra["canaries_before"], ra["p_accused"]
            vb, lb_cnt, cb_cnt, pb = rb["true_V_end"], rb["leaks_before"], rb["canaries_before"], rb["p_accused"]
            ra_rest = 1.0 - va - leak_dmg * la_cnt - can_cost * ca_cnt
            rb_rest = 1.0 - vb - leak_dmg * lb_cnt - can_cost * cb_cnt
            pen_a = (1.0 - pa) * (1.0 + va)
            pen_b = (1.0 - pb) * (1.0 + vb)
            leak_term += -leak_dmg * (la_cnt - lb_cnt)
            canary_term += -can_cost * (ca_cnt - cb_cnt)
            restrict_term += -(ra_rest - rb_rest)
            penalty_term += -(pen_a - pen_b)
        elif a_acc and not b_acc:
            a_only_accused += ra["luck_adjusted"]
            a_only_seeds.append(ra["seed"])
        elif not a_acc and b_acc:
            a_abstained += -rb["luck_adjusted"]
            a_abstained_seeds.append(ra["seed"])
        else:
            both_abstained += 1

    la_diff_sum = sum(ra["luck_adjusted"] - rb["luck_adjusted"] for ra, rb in zip(a_eps, b_eps))
    raw_diff_sum = sum(ra["score"] - rb["score"] for ra, rb in zip(a_eps, b_eps))
    luck_a = sum(ra["score"] - ra["luck_adjusted"] for ra in a_eps)
    luck_b = sum(rb["score"] - rb["luck_adjusted"] for rb in b_eps)
    luck_diff = luck_a - luck_b
    reconstructed = leak_term + canary_term + restrict_term + penalty_term + a_only_accused + a_abstained
    if abs(la_diff_sum - reconstructed) > 1e-9:
        raise SystemExit(f"decomposition mismatch on {tier}: {la_diff_sum} vs {reconstructed}")
    if abs(raw_diff_sum - (la_diff_sum + luck_diff)) > 1e-9:
        raise SystemExit(f"raw/luck mismatch on {tier}: {raw_diff_sum} vs {la_diff_sum + luck_diff}")

    n = len(a_eps)
    return {
        "n": n,
        "raw_diff_sum": round(raw_diff_sum, 6),
        "raw_diff_per_ep": round(raw_diff_sum / n, 6),
        "luck_adjusted_diff_sum": round(la_diff_sum, 6),
        "luck_adjusted_diff_per_ep": round(la_diff_sum / n, 6),
        "both_accused_count": both_accused,
        "both_abstained_count": both_abstained,
        "a_only_accused_seeds": a_only_seeds,
        "a_abstained_seeds": a_abstained_seeds,
        "terms_sum_30_seeds": {
            "posterior_commitment_quality": round(penalty_term, 6),
            "a_only_accused_gain": round(a_only_accused, 6),
            "a_abstained_loss": round(a_abstained, 6),
            "leak_timing_value": round(leak_term, 6),
            "canary_cost_value": round(canary_term, 6),
            "restriction_cost_value": round(restrict_term, 6),
            "luck_diff": round(luck_diff, 6),
            "luck_a": round(luck_a, 6),
            "luck_b": round(luck_b, 6),
        },
    }


def tier_mechanics_meta(tier: str) -> dict:
    p = TIERS[tier]
    pe = p.p_evasive_innocent
    pm = pe * p.interview_lr
    kl_int = pm * math.log(pm / pe) + (1.0 - pm) * math.log((1.0 - pm) / (1.0 - pe))
    lr_var = (
        float("inf")
        if p.fingerprint_accuracy >= 1.0
        else p.fingerprint_accuracy / ((1.0 - p.fingerprint_accuracy) / (p.max_variants - 1))
    )
    return {
        "n_employees": p.n_employees,
        "n_days": p.n_days,
        "p_leak": p.p_leak,
        "delay_choices": list(p.delay_choices),
        "leak_damage": p.leak_damage,
        "canary_cost": p.canary_cost,
        "canaries_per_day": p.canaries_per_day,
        "max_variants": p.max_variants,
        "actions_per_day": p.actions_per_day,
        "fingerprint_accuracy": p.fingerprint_accuracy,
        "access_constraints": p.access_constraints,
        "interview_lr": p.interview_lr,
        "interview_kl_nats": round(kl_int, 6),
        "max_canary_split_bits": round(math.log2(p.max_variants), 6),
        "max_canary_split_nats": round(math.log(p.max_variants), 6),
        "canary_variant_match_lr": None if math.isinf(lr_var) else round(lr_var, 6),
    }


def compact_per_seed(eps: list[dict]) -> dict:
    return {
        "seed": [r["seed"] for r in eps],
        "score": [round(r["score"], 6) for r in eps],
        "luck_adjusted": [round(r["luck_adjusted"], 6) for r in eps],
        "accused": [r["accused"] for r in eps],
        "correct": [r["correct"] for r in eps],
        "accuse_day": [r["accuse_day"] for r in eps],
        "final_day": [r["final_day"] for r in eps],
        "canaries_before": [r["canaries_before"] for r in eps],
        "days_2_canaries": [r["days_2_canaries"] for r in eps],
        "interviews": [r["interviews"] for r in eps],
        "feed_calls": [r["feed_calls"] for r in eps],
        "log_calls": [r["log_calls"] for r in eps],
        "consistent_size": [r["consistent_size"] for r in eps],
        "mole_in_consistent": [r["mole_in_consistent"] for r in eps],
        "seen_flip": [bool(r["seen_flips"]) for r in eps],
        "p_accused": [round(r["p_accused"], 6) if r["p_accused"] is not None else None for r in eps],
        "ev_accused": [round(r["ev_accused"], 6) if r["ev_accused"] is not None else None for r in eps],
        "p_top_end": [round(r["p_top"], 6) if r["p_top"] is not None else None for r in eps],
    }


def flip_outcomes_summary(eps: list[dict]) -> list[dict]:
    out = []
    for r in eps:
        if not r["seen_flips"]:
            continue
        out.append({
            "seed": r["seed"],
            "score": round(r["score"], 4),
            "accused": r["accused"],
            "correct": r["correct"],
            "abstained": r["accused"] is None,
            "accuse_day": r["accuse_day"],
            "final_day": r["final_day"],
            "consistent_size": r["consistent_size"],
            "consistent_set": r["consistent_set"],
            "mole_in_consistent": r["mole_in_consistent"],
            "p_accused": round(r["p_accused"], 4) if r["p_accused"] is not None else None,
            "p_top_end": round(r["p_top"], 4) if r["p_top"] is not None else None,
            "flips": r["seen_flips"],
        })
    return out


def build_cross_family_hard_gpt55(root: Path, oc_h: list[dict], sv_h: list[dict]) -> dict:
    agent, rel_paths = GPT55_HARD_SOURCE
    gpt_loaded = load_cell("hard", agent, rel_paths, root=root)
    missing = [s for s in SEEDS if s not in gpt_loaded]
    if missing:
        raise SystemExit(f"hard/opencode_gpt55 missing seeds: {missing}")

    gpt_h = [analyze_episode("hard", "opencode_gpt55", gpt_loaded[s]) for s in SEEDS]
    for r in gpt_h:
        vf = r["meta_V_final"]
        if r["accused"] is not None:
            if vf is None or abs(float(vf) - r["true_V_end"]) > 1e-6:
                raise SystemExit(f"gpt55 V_final mismatch on seed {r['seed']}: {vf} vs {r['true_V_end']}")
        elif vf is not None and abs(float(vf) - r["true_V_end"]) > 1e-6:
            raise SystemExit(f"gpt55 abstained V_final mismatch on seed {r['seed']}: {vf} vs {r['true_V_end']}")

    gpt_sum = summarize_cell("hard", "opencode_gpt55", gpt_h, sv_h)
    gpt_raw = [r["score"] for r in gpt_h]
    gpt_la = [r["luck_adjusted"] for r in gpt_h]
    oc_raw = [r["score"] for r in oc_h]
    oc_la = [r["luck_adjusted"] for r in oc_h]

    cost_total = sum(
        float(((gpt_loaded[s].get("meta") or {}).get("usage") or {}).get("opencode_reported_cost_usd", 0.0))
        for s in SEEDS
    )
    gpt_int_share = sum(r["interviews"] for r in gpt_h) / sum(r["total_calls"] for r in gpt_h)
    oc_int_share = sum(r["interviews"] for r in oc_h) / sum(r["total_calls"] for r in oc_h)

    abstained_rows = []
    for r in gpt_h:
        if r["accused"] is not None:
            continue
        ep_meta = gpt_loaded[r["seed"]].get("meta") or {}
        vf = ep_meta.get("V_final")
        abstained_rows.append({
            "seed": r["seed"],
            "accused": r["accused"],
            "score": round(r["score"], 4),
            "recorded_final_day": r["recorded_final_day"],
            "replayed_day": r["final_day"],
            "meta_V_final": round(float(vf), 6) if vf is not None else None,
            "effective_V_final": round(float(vf if vf is not None else r["true_V_end"]), 6),
            "canaries_before": r["canaries_before"],
            "interviews": r["interviews"],
            "consistent_size_end": r["consistent_size"],
            "mole_in_consistent_end": r["mole_in_consistent"],
            "p_top_end": round(r["p_top"], 6) if r["p_top"] is not None else None,
            "note": str(ep_meta.get("note") or ""),
        })

    return {
        "agent": agent,
        "model": "gpt-5.5",
        "opencode_version": "1.19.5",
        "tier": "hard",
        "preregistration_commit": "cf394894",
        "run_commit": "ca0a0dc0",
        "env_tag": "afterquery-final",
        "env_commit": "1bc3e281",
        "source": rel_paths[0],
        "n": len(gpt_h),
        "infra_failures": 0,
        "replay_mismatches": 0,
        "completed_meta_V_final_populated_count": sum(1 for r in gpt_h if r["meta_V_final"] is not None),
        "opencode_reported_cost_usd_total": round(cost_total, 4),
        "summary": gpt_sum,
        "behaviour_compare_metrics": {
            "gpt55_plant_canary_calls_mean": round(mean([float(r["plant_canary_calls"]) for r in gpt_h]), 6),
            "gpt55_interview_call_share": round(gpt_int_share, 6),
            "carbon_plant_canary_calls_mean": round(mean([float(r["plant_canary_calls"]) for r in oc_h]), 6),
            "carbon_interview_call_share": round(oc_int_share, 6),
            "solver_plant_canary_calls_mean": round(mean([float(r["plant_canary_calls"]) for r in sv_h]), 6),
            "solver_interview_call_share": 0.0,
            "gpt55_c1_isolated_any_seed_count": sum(1 for r in gpt_h if r["consistent_size"] == 1),
        },
        "paired_vs_carbon_opencode": {
            "raw_score": paired_contrast(gpt_raw, oc_raw),
            "luck_adjusted_score": paired_contrast(gpt_la, oc_la),
            "canaries_before_accuse": paired_contrast(
                [float(r["canaries_before"]) for r in gpt_h],
                [float(r["canaries_before"]) for r in oc_h],
            ),
            "interviews": paired_contrast(
                [float(r["interviews"]) for r in gpt_h],
                [float(r["interviews"]) for r in oc_h],
            ),
            "total_tool_calls": paired_contrast(
                [float(r["total_calls"]) for r in gpt_h],
                [float(r["total_calls"]) for r in oc_h],
            ),
            "decomposition": decompose_pair("hard", gpt_h, oc_h),
        },
        "paired_vs_solver": {
            "decomposition": decompose_pair("hard", gpt_h, sv_h),
        },
        "abstained_prose_only_episodes": abstained_rows,
        "flip_episodes": flip_outcomes_summary(gpt_h),
        "per_seed": {
            "seed": [r["seed"] for r in gpt_h],
            "score": [round(r["score"], 6) for r in gpt_h],
            "luck_adjusted": [round(r["luck_adjusted"], 6) for r in gpt_h],
            "accused": [r["accused"] for r in gpt_h],
            "correct": [r["correct"] for r in gpt_h],
            "accuse_day": [r["accuse_day"] for r in gpt_h],
            "canaries_before": [r["canaries_before"] for r in gpt_h],
            "interviews": [r["interviews"] for r in gpt_h],
            "consistent_size": [r["consistent_size"] for r in gpt_h],
            "p_accused": [round(r["p_accused"], 6) if r["p_accused"] is not None else None for r in gpt_h],
        },
    }


def _parse_signed_score(cell: str) -> float | None:
    m = re.search(r"([+-]\d+\.\d+)", cell)
    return float(m.group(1)) if m else None


def build_harbor_container_harness(
    root: Path,
    h_oc_summary: dict,
    h_ip_summary: dict,
    gpt55_summary: dict,
) -> dict:
    reh_dir = root / HARBOR_REHEARSAL_DIR
    build_txt = (reh_dir / "BUILD.txt").read_text(encoding="utf-8")
    table_md = (reh_dir / "TABLE.md").read_text(encoding="utf-8")

    sha_m = re.search(r"^sha:\s*([0-9a-f]+)", build_txt, flags=re.M)
    desc_m = re.search(r"^describe:\s*(\S+)", build_txt, flags=re.M)
    harbor_m = re.search(r"^harbor:\s*(\S+)", build_txt, flags=re.M)
    if not (sha_m and desc_m and harbor_m):
        raise SystemExit("failed to parse results/harbor/rehearsal/BUILD.txt")
    build_sha = sha_m.group(1)
    build_tag = desc_m.group(1)
    harbor_ver = harbor_m.group(1)

    task_rows = re.findall(
        r"^\|\s*(hard-\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|",
        table_md,
        flags=re.M,
    )
    if len(task_rows) != 10:
        raise SystemExit(f"expected 10 judge task rows in TABLE.md, found {len(task_rows)}")

    oracle_scores = [float(_parse_signed_score(r[1])) for r in task_rows]
    oc1_scores = [float(_parse_signed_score(r[2])) for r in task_rows]
    oc2_scores = [float(_parse_signed_score(r[3])) for r in task_rows]
    dn_scores = [float(_parse_signed_score(r[5])) for r in task_rows]
    se_scores = [float(_parse_signed_score(r[6])) for r in task_rows]

    oracle_mean_10 = round(mean(oracle_scores), 6)
    oc1_mean = round(mean(oc1_scores), 6)
    oc2_mean = round(mean(oc2_scores), 6)
    if abs(oracle_mean_10 - 0.506) > 1e-6 or abs(oc1_mean - 0.472) > 1e-6 or abs(oc2_mean - 0.585) > 1e-6:
        raise SystemExit(f"Harbor TABLE.md mean mismatch: {oracle_mean_10}, {oc1_mean}, {oc2_mean}")
    if any(abs(x) > 1e-9 for x in dn_scores + se_scores):
        raise SystemExit("Harbor zero baselines nonzero in TABLE.md")

    infra_idx = next(i for i, r in enumerate(task_rows) if "infra" in r[4].lower())
    oracle_9_opencode3 = round(mean([s for i, s in enumerate(oracle_scores) if i != infra_idx]), 6)
    oc3_snap7_scores = [_parse_signed_score(r[4]) for r in task_rows]
    oc3_snap7_valid = [x for x in oc3_snap7_scores if x is not None]
    oracle_snap7 = [oracle_scores[i] for i, x in enumerate(oc3_snap7_scores) if x is not None]

    oc3_final_mean = 0.626
    final_run_means = [oc1_mean, oc2_mean, oc3_final_mean]
    final_mom = mean(final_run_means)
    final_sd = math.sqrt(sum((x - final_mom) ** 2 for x in final_run_means) / (len(final_run_means) - 1))

    return {
        "harbor_version": harbor_ver,
        "tag": build_tag,
        "build_sha": build_sha,
        "build_sha_short": build_sha[:8],
        "correction_commits": ["aa1c679e", "5f9b3297"],
        "final_trials_branch_commit": "d0ead011",
        "sources": [
            f"{HARBOR_REHEARSAL_DIR}/README.md",
            f"{HARBOR_REHEARSAL_DIR}/BUILD.txt",
            f"{HARBOR_REHEARSAL_DIR}/TABLE.md",
        ],
        "judge_seeds": "900000-900009",
        "n_tasks": 10,
        "gap_reproduced_in_harbor": False,
        "harness_matrix": {
            "opencode_mcp_only_carbon": {
                "shell_allowed": False,
                "shell_used_trials": 0,
                "n_valid": h_oc_summary["n"],
                "raw_mean": h_oc_summary["raw_mean"],
                "vs_solver_raw_ratio": h_oc_summary["vs_solver_raw_ratio"],
                "vs_solver_raw_boot_ci95": h_oc_summary["vs_solver_raw_ratio_boot_ci95"],
                "valid_accusations_correct": h_oc_summary["correct_count"],
                "valid_accusations_total": h_oc_summary["accused_count"],
            },
            "inproc_thought_sig_carbon": {
                "shell_allowed": False,
                "shell_used_trials": 0,
                "n_valid": h_ip_summary["n"],
                "raw_mean": h_ip_summary["raw_mean"],
                "vs_solver_raw_ratio": h_ip_summary["vs_solver_raw_ratio"],
                "vs_solver_raw_boot_ci95": h_ip_summary["vs_solver_raw_ratio_boot_ci95"],
                "valid_accusations_correct": h_ip_summary["correct_count"],
                "valid_accusations_total": h_ip_summary["accused_count"],
            },
            "opencode_mcp_only_gpt55": {
                "shell_allowed": False,
                "shell_used_trials": 0,
                "n_valid": gpt55_summary["n"],
                "raw_mean": gpt55_summary["raw_mean"],
                "vs_solver_raw_ratio": gpt55_summary["vs_solver_raw_ratio"],
                "vs_solver_raw_boot_ci95": gpt55_summary["vs_solver_raw_ratio_boot_ci95"],
                "valid_accusations_correct": gpt55_summary["correct_count"],
                "valid_accusations_total": gpt55_summary["accused_count"],
            },
            "harbor_container_opencode_carbon": {
                "environment": "Harbor 0.26.0 container + OpenCode + gemini-4-carbon (afterquery-final 1bc3e281)",
                "shell_allowed": True,
                "shell_tools": ["bash", "python3"],
                "shell_used_trials": 20,
                "shell_audited_trials": 28,
                "shell_used_share": round(20.0 / 28.0, 6),
                "seeds": "900000-900009",
                "n_runs": 3,
                "n_valid_total": 29,
                "n_infra_excluded_total": 1,
                "valid_accusations_correct": 28,
                "valid_accusations_total": 29,
                "valid_accusation_accuracy": round(28.0 / 29.0, 6),
                "oracle_mean_10_tasks": oracle_mean_10,
                "oracle_correct_10_tasks": sum(1 for s in oracle_scores if s > 0.0),
                "oracle_same_9_tasks_opencode3": oracle_9_opencode3,
                "do_nothing_mean": 0.0,
                "stop_early_mean": 0.0,
                "runs": [
                    {
                        "run": "opencode-1",
                        "n_valid": 10,
                        "n_infra_excluded": 0,
                        "correct": 9,
                        "accused": 10,
                        "mean": oc1_mean,
                        "oracle_same_tasks": oracle_mean_10,
                        "ratio_pct": 93,
                        "ratio_boot_ci95_pct": [20, 371],
                        "diff_vs_oracle": round(oc1_mean - oracle_mean_10, 6),
                    },
                    {
                        "run": "opencode-2",
                        "n_valid": 10,
                        "n_infra_excluded": 0,
                        "correct": 10,
                        "accused": 10,
                        "mean": oc2_mean,
                        "oracle_same_tasks": oracle_mean_10,
                        "ratio_pct": 116,
                        "ratio_boot_ci95_pct": [78, 363],
                        "diff_vs_oracle": round(oc2_mean - oracle_mean_10, 6),
                    },
                    {
                        "run": "opencode-3",
                        "n_valid": 9,
                        "n_infra_excluded": 1,
                        "infra_excluded_task": task_rows[infra_idx][0],
                        "finished_after_0830_cutoff": 5,
                        "correct": 9,
                        "accused": 9,
                        "mean": oc3_final_mean,
                        "oracle_same_tasks": oracle_9_opencode3,
                        "ratio_pct": 131,
                        "ratio_boot_ci95_pct": [86, 590],
                        "diff_vs_oracle": round(oc3_final_mean - oracle_9_opencode3, 6),
                        "snapshot_0852_n7": {
                            "n_valid": len(oc3_snap7_valid),
                            "mean": round(mean(oc3_snap7_valid), 6),
                            "oracle_same_tasks": round(mean(oracle_snap7), 6),
                            "ratio_pct": 153,
                            "ratio_boot_ci95_pct": [89, 411],
                        },
                    },
                ],
                "three_run_mean_of_means_final": round(final_mom, 6),
                "three_run_sd_final": round(final_sd, 6),
                "three_run_range_final": round(max(final_run_means) - min(final_run_means), 6),
            },
        },
        "disclosed_differences_vs_mcp_dev": [
            "Harbor container provides bash and python3 alongside MCP tools (used in 20/28 audited trials vs 0/30 in MCP-only dev where * = deny)",
            "Tag afterquery-final (1bc3e281) includes public-only data.detail strings on invalid arguments and the reworded careful-mole W1 sentence",
            "Judge rehearsal ran on 10 held-out hard judge seeds (900000-900009) rather than the 30 dev seeds (0-29)",
        ],
        "honest_disclosure": (
            "The 65% [24%, 98%] MCP-only Hard gap for gemini-4-carbon did not reproduce in the Harbor "
            "judge container: across three runs on tag afterquery-final (1bc3e281, corrected in aa1c679e/5f9b3297), "
            "gemini-4-carbon scored +0.472 (93%), +0.585 (116%), and +0.626 (131% on n=9 valid) against the +0.506 "
            "same-build oracle, getting 28/29 valid accusations right while using bash/python3 in 20/28 audited trials."
        ),
    }


def compute(root: Path = ROOT) -> dict:
    raw_loaded: dict[tuple[str, str], dict[int, dict]] = {}
    for (tier, harness), (agent, rel_paths) in CELL_SOURCES.items():
        loaded = load_cell(tier, agent, rel_paths, root=root)
        missing = [s for s in SEEDS if s not in loaded]
        if missing:
            raise SystemExit(f"{tier}/{harness} missing seeds: {missing}")
        raw_loaded[(tier, harness)] = loaded

    analyzed: dict[tuple[str, str], list[dict]] = {}
    for (tier, harness), by_seed in raw_loaded.items():
        analyzed[(tier, harness)] = [analyze_episode(tier, harness, by_seed[s]) for s in SEEDS]

    cells_summary: dict[str, dict] = {}
    per_seed_out: dict[str, dict] = {}
    for tier in ("medium", "hard"):
        s_eps = analyzed[(tier, "solver")]
        for harness in ("opencode", "inproc", "solver"):
            key = f"{tier}_{harness}"
            eps = analyzed[(tier, harness)]
            cells_summary[key] = summarize_cell(tier, harness, eps, s_eps)
            per_seed_out[key] = compact_per_seed(eps)

    oc_m = analyzed[("medium", "opencode")]
    ip_m = analyzed[("medium", "inproc")]
    sv_m = analyzed[("medium", "solver")]
    oc_h = analyzed[("hard", "opencode")]
    ip_h = analyzed[("hard", "inproc")]
    sv_h = analyzed[("hard", "solver")]

    oc_m_raw = [r["score"] for r in oc_m]
    ip_m_raw = [r["score"] for r in ip_m]
    sv_m_raw = [r["score"] for r in sv_m]
    oc_h_raw = [r["score"] for r in oc_h]
    ip_h_raw = [r["score"] for r in ip_h]
    sv_h_raw = [r["score"] for r in sv_h]

    oc_m_la = [r["luck_adjusted"] for r in oc_m]
    ip_m_la = [r["luck_adjusted"] for r in ip_m]
    sv_m_la = [r["luck_adjusted"] for r in sv_m]
    oc_h_la = [r["luck_adjusted"] for r in oc_h]
    ip_h_la = [r["luck_adjusted"] for r in ip_h]
    sv_h_la = [r["luck_adjusted"] for r in sv_h]

    hard_diff_raw = [a - b for a, b in zip(oc_h_raw, ip_h_raw)]
    med_diff_raw = [a - b for a, b in zip(oc_m_raw, ip_m_raw)]
    did_raw = paired_contrast(hard_diff_raw, med_diff_raw)
    did_raw["boot_ci95_indep_tiers"] = indep_tier_did_boot_ci(hard_diff_raw, med_diff_raw)

    hard_diff_la = [a - b for a, b in zip(oc_h_la, ip_h_la)]
    med_diff_la = [a - b for a, b in zip(oc_m_la, ip_m_la)]
    did_la = paired_contrast(hard_diff_la, med_diff_la)
    did_la["boot_ci95_indep_tiers"] = indep_tier_did_boot_ci(hard_diff_la, med_diff_la)

    contrasts_2x2 = {
        "raw_score": {
            "oc_minus_ip_medium": paired_contrast(oc_m_raw, ip_m_raw),
            "oc_minus_ip_hard": paired_contrast(oc_h_raw, ip_h_raw),
            "did_hard_minus_medium": did_raw,
            "tier_drop_oc_hard_minus_med": paired_contrast(oc_h_raw, oc_m_raw),
            "tier_drop_ip_hard_minus_med": paired_contrast(ip_h_raw, ip_m_raw),
            "tier_drop_solver_hard_minus_med": paired_contrast(sv_h_raw, sv_m_raw),
            "solver_adj_tier_drop_oc": paired_contrast(
                [a - b for a, b in zip(oc_h_raw, sv_h_raw)],
                [a - b for a, b in zip(oc_m_raw, sv_m_raw)],
            ),
            "solver_adj_tier_drop_ip": paired_contrast(
                [a - b for a, b in zip(ip_h_raw, sv_h_raw)],
                [a - b for a, b in zip(ip_m_raw, sv_m_raw)],
            ),
        },
        "luck_adjusted_score": {
            "oc_minus_ip_medium": paired_contrast(oc_m_la, ip_m_la),
            "oc_minus_ip_hard": paired_contrast(oc_h_la, ip_h_la),
            "did_hard_minus_medium": did_la,
            "tier_drop_oc_hard_minus_med": paired_contrast(oc_h_la, oc_m_la),
            "tier_drop_ip_hard_minus_med": paired_contrast(ip_h_la, ip_m_la),
            "tier_drop_solver_hard_minus_med": paired_contrast(sv_h_la, sv_m_la),
            "solver_adj_tier_drop_oc": paired_contrast(
                [a - b for a, b in zip(oc_h_la, sv_h_la)],
                [a - b for a, b in zip(oc_m_la, sv_m_la)],
            ),
            "solver_adj_tier_drop_ip": paired_contrast(
                [a - b for a, b in zip(ip_h_la, sv_h_la)],
                [a - b for a, b in zip(ip_m_la, sv_m_la)],
            ),
        },
        "behavioral_contrasts": {
            "canaries_oc_minus_ip_medium": paired_contrast(
                [float(r["canaries_before"]) for r in oc_m],
                [float(r["canaries_before"]) for r in ip_m],
            ),
            "canaries_oc_minus_ip_hard": paired_contrast(
                [float(r["canaries_before"]) for r in oc_h],
                [float(r["canaries_before"]) for r in ip_h],
            ),
            "canaries_oc_minus_solver_hard": paired_contrast(
                [float(r["canaries_before"]) for r in oc_h],
                [float(r["canaries_before"]) for r in sv_h],
            ),
            "canaries_ip_minus_solver_hard": paired_contrast(
                [float(r["canaries_before"]) for r in ip_h],
                [float(r["canaries_before"]) for r in sv_h],
            ),
            "interviews_oc_minus_ip_medium": paired_contrast(
                [float(r["interviews"]) for r in oc_m],
                [float(r["interviews"]) for r in ip_m],
            ),
            "interviews_oc_minus_ip_hard": paired_contrast(
                [float(r["interviews"]) for r in oc_h],
                [float(r["interviews"]) for r in ip_h],
            ),
        },
    }

    decompositions = {
        "oc_minus_ip_medium": decompose_pair("medium", oc_m, ip_m),
        "oc_minus_ip_hard": decompose_pair("hard", oc_h, ip_h),
        "oc_minus_solver_medium": decompose_pair("medium", oc_m, sv_m),
        "ip_minus_solver_medium": decompose_pair("medium", ip_m, sv_m),
        "oc_minus_solver_hard": decompose_pair("hard", oc_h, sv_h),
        "ip_minus_solver_hard": decompose_pair("hard", ip_h, sv_h),
    }

    med_ip_failures = []
    for s in SEEDS:
        ri = ip_m[s]
        ro = oc_m[s]
        rs = sv_m[s]
        if not ri["correct"]:
            med_ip_failures.append({
                "seed": s,
                "ip_outcome": "abstained" if ri["accused"] is None else "wrong",
                "ip_score": round(ri["score"], 4),
                "ip_canaries": ri["canaries_before"],
                "ip_interviews": ri["interviews"],
                "ip_first_canary_day": ri["first_canary_day"],
                "ip_c_size_end": ri["consistent_size"],
                "ip_c_set_end": ri["consistent_set"],
                "ip_p_end": round(ri["p_accused"] if ri["accused"] else ri["p_top"], 4),
                "oc_score": round(ro["score"], 4),
                "oc_accuse_day": ro["accuse_day"],
                "oc_canaries": ro["canaries_before"],
                "oc_c_size": ro["consistent_size"],
                "oc_p_accused": round(ro["p_accused"], 4),
                "solver_score": round(rs["score"], 4),
                "solver_accuse_day": rs["accuse_day"],
            })

    hard_outcome_divergences = []
    for s in SEEDS:
        ro = oc_h[s]
        ri = ip_h[s]
        rs = sv_h[s]
        if ro["correct"] != ri["correct"] or (ro["accused"] is None) != (ri["accused"] is None):
            hard_outcome_divergences.append({
                "seed": s,
                "oc_score": round(ro["score"], 4),
                "oc_accused": ro["accused"],
                "oc_correct": ro["correct"],
                "oc_day": ro["accuse_day"],
                "oc_c_size": ro["consistent_size"],
                "oc_seen_flip": bool(ro["seen_flips"]),
                "oc_p": round(ro["p_accused"], 4) if ro["p_accused"] is not None else None,
                "ip_score": round(ri["score"], 4),
                "ip_accused": ri["accused"],
                "ip_correct": ri["correct"],
                "ip_day": ri["accuse_day"],
                "ip_c_size": ri["consistent_size"],
                "ip_seen_flip": bool(ri["seen_flips"]),
                "ip_p": round(ri["p_accused"], 4) if ri["p_accused"] is not None else None,
                "solver_score": round(rs["score"], 4),
                "solver_day": rs["accuse_day"],
            })

    mechanisms = {
        "medium_noiseless_set_elimination": {
            "opencode_c1_isolations": cells_summary["medium_opencode"]["consistent_eq_1_at_accuse"],
            "opencode_c2_lucky_commitments": [
                {
                    "seed": r["seed"],
                    "score": round(r["score"], 4),
                    "p_accused": round(r["p_accused"], 4),
                    "consistent_set": r["consistent_set"],
                }
                for r in oc_m
                if r["consistent_size"] > 1
            ],
            "inproc_non_correct_episodes": med_ip_failures,
        },
        "hard_noisy_bayes_and_flips": {
            "opencode_flip_episodes": flip_outcomes_summary(oc_h),
            "inproc_flip_episodes": flip_outcomes_summary(ip_h),
            "solver_flip_episodes": flip_outcomes_summary(sv_h),
            "hard_outcome_divergences": hard_outcome_divergences,
        },
    }

    cross_family_gpt55 = build_cross_family_hard_gpt55(root, oc_h, sv_h)
    harbor_container = build_harbor_container_harness(
        root,
        cells_summary["hard_opencode"],
        cells_summary["hard_inproc"],
        cross_family_gpt55["summary"],
    )

    return {
        "meta": {
            "tiers_version": "v1.4",
            "model": "gemini-4-carbon",
            "seeds": SEEDS,
            "n_seeds": len(SEEDS),
            "n_episodes_frontier": 120,
            "n_episodes_solver": 60,
            "n_episodes_total": 180,
            "bootstrap_resamples": BOOT_RESAMPLES,
            "bootstrap_rng_seed": BOOT_SEED,
            "access_log_tool_name_in_env": "read_access_logs",
            "sources": {f"{t}_{h}": paths for (t, h), (_, paths) in CELL_SOURCES.items()},
            "tier_mechanics": {
                "medium": tier_mechanics_meta("medium"),
                "hard": tier_mechanics_meta("hard"),
            },
        },
        "cells": cells_summary,
        "contrasts_2x2": contrasts_2x2,
        "decompositions": decompositions,
        "mechanisms": mechanisms,
        "per_seed": per_seed_out,
        "cross_family_hard_gpt55": cross_family_gpt55,
        "harbor_container_harness": harbor_container,
    }


def f3(x: float | None, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "--"
    return f"{x:+.3f}" if sign else f"{x:.3f}"


def f2(x: float | None, sign: bool = False) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "--"
    return f"{x:+.2f}" if sign else f"{x:.2f}"


def pct(x: float) -> str:
    return f"{100.0 * x:.0f}%"


def render_markdown(data: dict) -> str:
    c = data["cells"]
    m_oc, m_ip, m_sv = c["medium_opencode"], c["medium_inproc"], c["medium_solver"]
    h_oc, h_ip, h_sv = c["hard_opencode"], c["hard_inproc"], c["hard_solver"]
    ct_raw = data["contrasts_2x2"]["raw_score"]
    ct_la = data["contrasts_2x2"]["luck_adjusted_score"]
    dec = data["decompositions"]
    mech = data["mechanisms"]
    tm = data["meta"]["tier_mechanics"]
    cf = data["cross_family_hard_gpt55"]
    g_oc = cf["summary"]
    hb = data["harbor_container_harness"]

    assert m_oc["correct_count"] == 30 and m_oc["accused_count"] == 30 and m_oc["abstained_count"] == 0
    assert m_ip["accused_count"] == 26 and m_ip["abstained_count"] == 4 and m_ip["wrong_count"] == 1
    assert m_oc["mole_excluded_from_consistent_at_accuse_count"] == 0
    assert m_ip["mole_excluded_from_consistent_at_accuse_count"] == 0
    assert m_oc["wait_days_after_first_c1_mean"] == 0.0 and m_ip["wait_days_after_first_c1_mean"] == 0.0
    assert ct_raw["oc_minus_ip_medium"]["point"] > 0 and ct_raw["oc_minus_ip_hard"]["point"] < 0
    assert ct_raw["did_hard_minus_medium"]["boot_ci95"][1] < 0
    assert ct_la["did_hard_minus_medium"]["boot_ci95"][1] < 0
    assert h_ip["p_accused_mean"] > h_oc["p_accused_mean"]
    assert h_oc["canaries_before_accuse_mean"] < 10.0 < h_sv["canaries_before_accuse_mean"]
    assert h_ip["canaries_before_accuse_mean"] < 10.0 < h_sv["canaries_before_accuse_mean"]
    assert h_ip["consistent_eq_0_at_accuse"] == 2 and h_oc["consistent_eq_0_at_accuse"] == 0
    assert g_oc["accused_count"] == 28 and g_oc["correct_count"] == 28 and g_oc["wrong_count"] == 0
    assert g_oc["abstained_seeds"] == [0, 17] and g_oc["consistent_eq_0_at_accuse"] == 1
    assert hb["gap_reproduced_in_harbor"] is False

    raw_med = ct_raw["oc_minus_ip_medium"]
    raw_hard = ct_raw["oc_minus_ip_hard"]
    raw_did = ct_raw["did_hard_minus_medium"]
    la_med = ct_la["oc_minus_ip_medium"]
    la_hard = ct_la["oc_minus_ip_hard"]
    la_did = ct_la["did_hard_minus_medium"]

    lines: list[str] = []
    a = lines.append

    a(MD_H1 + "Medium vs Hard and the 2x2 Harness Crossover (Rules v1.4, Paired Seeds 0-29)")
    a("")
    a("**Scope.** Exact replay-verified analysis of all **210 committed v1.4 episodes** on paired dev seeds `0-29` "
      "(`180` primary `2x2` `gemini-4-carbon` factorial `{OpenCode over MCP, In-Process} x {Medium, Hard}` + `SolverPolicy` "
      "episodes in Sections 1-5, plus `30` pre-registered `opencode:openai/gpt-5.5` Hard episodes in Section 6) and the "
      "Harbor `0.26.0` judge-container rehearsal (`afterquery-final` `1bc3e281`, `aa1c679e`/`5f9b3297`, Section 7). "
      "Every committed episode is replayed in a fresh `Env` and verified against the recorded score and accusation; "
      "all confidence intervals use 10,000-resample paired bootstraps (`rng_seed = 0`). Reproduce with one command "
      "(no API keys, ~3 s): `python scripts/harness_and_tier_analysis_v14.py` (`--check` verifies exact reproduction).")
    a("")
    a(MD_H2 + "Executive Summary: Two Headline Patterns, One Mechanistic Explanation")
    a("")
    a("Judges reading `docs/reports/gap.md` observe two immediate patterns across the 120 `gemini-4-carbon` episodes:")
    a(f"1. **Tier separation in the judges' harness (OpenCode over MCP):** Medium is at solver parity "
      f"(**{pct(m_oc['vs_solver_raw_ratio'])}** `[{pct(m_oc['vs_solver_raw_ratio_boot_ci95'][0])}, "
      f"{pct(m_oc['vs_solver_raw_ratio_boot_ci95'][1])}]` raw; "
      f"**{pct(m_oc['vs_solver_luck_adjusted_ratio'])}** `[{pct(m_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][0])}, "
      f"{pct(m_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][1])}]` luck-adjusted), while Hard opens a clear gap "
      f"(**{pct(h_oc['vs_solver_raw_ratio'])}** `[{pct(h_oc['vs_solver_raw_ratio_boot_ci95'][0])}, "
      f"{pct(h_oc['vs_solver_raw_ratio_boot_ci95'][1])}]` raw; "
      f"**{pct(h_oc['vs_solver_luck_adjusted_ratio'])}** `[{pct(h_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][0])}, "
      f"{pct(h_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][1])}]` luck-adjusted).")
    a(f"2. **2x2 Harness x Tier crossover:** OpenCode beats In-Process on Medium "
      f"(`{f3(m_oc['raw_mean'], True)}` vs `{f3(m_ip['raw_mean'], True)}`, paired diff "
      f"`{f3(raw_med['point'], True)}` `[{f3(raw_med['boot_ci95'][0], True)}, {f3(raw_med['boot_ci95'][1], True)}]`; "
      f"luck-adjusted `{f3(m_oc['luck_adjusted_mean'])}` vs `{f3(m_ip['luck_adjusted_mean'])}`, diff "
      f"`{f3(la_med['point'], True)}` `[{f3(la_med['boot_ci95'][0], True)}, {f3(la_med['boot_ci95'][1], True)}]`), "
      f"whereas In-Process beats OpenCode on Hard "
      f"(`{f3(h_ip['raw_mean'], True)}` vs `{f3(h_oc['raw_mean'], True)}`, `OC - IP = {f3(raw_hard['point'], True)}` "
      f"`[{f3(raw_hard['boot_ci95'][0], True)}, {f3(raw_hard['boot_ci95'][1], True)}]`; "
      f"luck-adjusted `{f3(h_ip['luck_adjusted_mean'])}` vs `{f3(h_oc['luck_adjusted_mean'])}`, "
      f"`OC - IP = {f3(la_hard['point'], True)}` `[{f3(la_hard['boot_ci95'][0], True)}, {f3(la_hard['boot_ci95'][1], True)}]`). "
      f"The **Difference-in-Differences** `(OC_hard - IP_hard) - (OC_med - IP_med)` is "
      f"**`{f3(raw_did['point'], True)}`** `[{f3(raw_did['boot_ci95'][0], True)}, {f3(raw_did['boot_ci95'][1], True)}]` "
      f"on raw score (`p = {raw_did['p_boot_two_sided']:.4f}`) and "
      f"**`{f3(la_did['point'], True)}`** `[{f3(la_did['boot_ci95'][0], True)}, {f3(la_did['boot_ci95'][1], True)}]` "
      f"on luck-adjusted score (`p = {la_did['p_boot_two_sided']:.4f}`), excluding zero on both metrics.")
    a("")
    a("**Why the crossover happens (mechanistic proof):**")
    a(f"- **On Medium (`N = {tm['medium']['n_employees']}`, `100%` fingerprint accuracy, 1 canary/day, no clearance constraints), "
      f"noiseless set elimination suffices.** Every leaked regular document and canary variant is a deterministic 0/1 "
      f"filter (`mole in C` in `30/30` episodes for every agent). OpenCode starts planting canaries slightly earlier "
      f"(day `{m_oc['first_canary_day_mean']:.2f}` vs `{m_ip['first_canary_day_mean']:.2f}`), wastes fewer full-budget days "
      f"on zero-canary interview sprees (`{m_oc['days_lt_cap_full_budget_count']}` vs `{m_ip['days_lt_cap_full_budget_count']}` "
      f"days), isolates `|C| = 1` on `{m_oc['consistent_eq_1_at_accuse']}/30` seeds, and commits decisively on all `30/30` "
      f"episodes (`30/30` correct; `{30 - m_oc['consistent_eq_1_at_accuse']}` unresolved `|C| = 2` bets all landed, "
      f"adding `{m_oc['luck_realization_mean']:+.3f}` V/ep of positive luck that explains `111%` raw vs `101%` luck-adjusted). "
      f"In-Process reaches day 14 with `|C| >= 2` on 5 episodes and abstains on `{m_ip['abstained_count']}/30` "
      f"(seeds `{', '.join(map(str, m_ip['abstained_seeds']))}`, `{m_ip['accused_count']}/30` accused) plus 1 horizon miss (seed 18).")
    a(f"- **On Hard (`N = {tm['hard']['n_employees']}`, `95%` fingerprint accuracy = 5% variant flip, 2 canaries/day, "
      f"2-3 day delay, clearance constraints), BOTH harnesses severely under-explore AND OpenCode's strict-elimination "
      f"commitment breaks under noise.** Both OpenCode and In-Process plant only `{h_oc['canaries_before_accuse_mean']:.1f}` "
      f"and `{h_ip['canaries_before_accuse_mean']:.1f}` canaries vs Solver's `{h_sv['canaries_before_accuse_mean']:.1f}` "
      f"(`{pct(h_oc['canary_capacity_used_share'])}` and `{pct(h_ip['canary_capacity_used_share'])}` of the 2/day capacity "
      f"vs Solver's `{pct(h_sv['canary_capacity_used_share'])}`) while spending `{h_oc['interviews_mean']:.1f}` and "
      f"`{h_ip['interviews_mean']:.1f}` calls on near-zero-information interviews (`<= {tm['hard']['interview_kl_nats']:.4f}` "
      f"nats each vs `{tm['hard']['max_canary_split_nats']:.3f}` nats per 3-way canary; Solver runs `0` interviews). "
      f"Crucially, `95%` fingerprint accuracy turns a canary variant mismatch from hard exclusion into a `1:38` "
      f"likelihood ratio. OpenCode's aggressive commitment suffers `2/2` wrong accusations on false `|C| = 1` flip traps "
      f"(seeds `1, 26`) plus `9/29` under-isolated (`|C| >= 2`) accusations (`P(accused) = {h_oc['p_accused_mean']:.2f}`, "
      f"`{h_oc['p_accused_lt_0.85_count']}/29` below `0.85`). In-Process's `generateContent` loop with persisted "
      f"`thought_signature_replay` tracks noisy likelihoods more conservatively (`P(accused) = {h_ip['p_accused_mean']:.2f}`, "
      f"only `{h_ip['p_accused_lt_0.85_count']}/29` below `0.85`), **recovering to accuse the true mole on `2` flip "
      f"episodes (seeds `3, 5`) even after subsequent leaks drove the strict noiseless consistent set to `|C| = 0` (empty)** "
      f"and rationally abstaining on flip seed `26` (`1` wrong total vs OpenCode's `4`).")
    a("")

    a(MD_H2 + "1. Full 2x2 Factorial Scoreboard and Paired Bootstrap Contrasts")
    a("")
    a(MD_H3 + "1.1 Six-Cell Headline Table (Paired Seeds 0-29)")
    a("")
    a("| Tier | Harness | n | Raw Score +/- CI | Raw / Solver [95% Boot CI] | Luck-Adj Score +/- CI | Luck-Adj / Solver [95% Boot CI] | Accused | Accuracy | Mean P(accused) |")
    a("|---|---|---:|---|---|---|---|---|---|---|")
    for cell in (m_oc, m_ip, m_sv, h_oc, h_ip, h_sv):
        is_sv = cell["harness"] == "solver"
        label = {
            "opencode": "OpenCode over MCP",
            "inproc": "In-Process (thought-sig)",
            "solver": "SolverPolicy (reference)",
        }[cell["harness"]]
        r_rat = "--" if is_sv else (
            f"{pct(cell['vs_solver_raw_ratio'])} "
            f"[{pct(cell['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(cell['vs_solver_raw_ratio_boot_ci95'][1])}]"
        )
        la_rat = "--" if is_sv else (
            f"{pct(cell['vs_solver_luck_adjusted_ratio'])} "
            f"[{pct(cell['vs_solver_luck_adjusted_ratio_boot_ci95'][0])}, {pct(cell['vs_solver_luck_adjusted_ratio_boot_ci95'][1])}]"
        )
        a(f"| {cell['tier']} | {label} | {cell['n']} | "
          f"{f3(cell['raw_mean'], True)} +/- {f3(cell['raw_ci95_norm'])} | {r_rat} | "
          f"{f3(cell['luck_adjusted_mean'], True)} +/- {f3(cell['luck_adjusted_ci95_norm'])} | {la_rat} | "
          f"{cell['accused_count']}/{cell['n']} ({pct(cell['accused_rate'])}) | "
          f"{cell['correct_count']}/{cell['n']} ({pct(cell['accuracy'])}) | "
          f"{f3(cell['p_accused_mean'])} |")
    a("")
    a("Note: `luck_adjusted_round3_mean` (rounding `P(accused)` to 3 decimals as in `scripts/paired_v13.py`) gives "
      f"Medium `{m_oc['luck_adjusted_round3_mean']:.3f} / {m_ip['luck_adjusted_round3_mean']:.3f} / {m_sv['luck_adjusted_round3_mean']:.3f}` "
      f"and Hard `{h_oc['luck_adjusted_round3_mean']:.3f} / {h_ip['luck_adjusted_round3_mean']:.3f} / {h_sv['luck_adjusted_round3_mean']:.3f}`, "
      "matching `docs/reports/gap.md` to every printed digit.")
    a("")

    a(MD_H3 + "1.2 Exact Paired 2x2 Contrasts (10,000-Resample Paired Bootstrap 95% CIs)")
    a("")
    a("| Contrast (n = 30 paired seeds) | Metric | Mean Diff (per ep) | Sum (30 seeds) | 95% Paired Boot CI | Indep-Tier Boot CI | Boot 2-Sided p | Seed Wins (+ / - / tie) |")
    a("|---|---|---:|---:|---|---|---:|---|")
    contrast_rows = [
        ("OpenCode - In-Process (Medium)", "Raw score", raw_med, "--"),
        ("OpenCode - In-Process (Hard)", "Raw score", raw_hard, "--"),
        ("DiD: (OC_hard - IP_hard) - (OC_med - IP_med)", "Raw score", raw_did,
         f"[{f3(raw_did['boot_ci95_indep_tiers'][0], True)}, {f3(raw_did['boot_ci95_indep_tiers'][1], True)}]"),
        ("OpenCode - In-Process (Medium)", "Luck-adjusted", la_med, "--"),
        ("OpenCode - In-Process (Hard)", "Luck-adjusted", la_hard, "--"),
        ("DiD: (OC_hard - IP_hard) - (OC_med - IP_med)", "Luck-adjusted", la_la := la_did,
         f"[{f3(la_did['boot_ci95_indep_tiers'][0], True)}, {f3(la_did['boot_ci95_indep_tiers'][1], True)}]"),
        ("Tier drop: OpenCode (Hard - Medium)", "Raw score", ct_raw["tier_drop_oc_hard_minus_med"], "--"),
        ("Tier drop: In-Process (Hard - Medium)", "Raw score", ct_raw["tier_drop_ip_hard_minus_med"], "--"),
        ("Tier drop: Solver (Hard - Medium)", "Raw score", ct_raw["tier_drop_solver_hard_minus_med"], "--"),
        ("Solver-adj tier drop: (OC_h - S_h) - (OC_m - S_m)", "Luck-adjusted", ct_la["solver_adj_tier_drop_oc"], "--"),
        ("Solver-adj tier drop: (IP_h - S_h) - (IP_m - S_m)", "Luck-adjusted", ct_la["solver_adj_tier_drop_ip"], "--"),
    ]
    for title, metric, obj, indep_txt in contrast_rows:
        _ = la_la
        wins = f"{obj['seed_wins_pos']} / {obj['seed_wins_neg']} / {obj['seed_ties']}"
        a(f"| {title} | {metric} | **{f3(obj['point'], True)}** | {f2(obj['sum_30_seeds'], True)} V | "
          f"[{f3(obj['boot_ci95'][0], True)}, {f3(obj['boot_ci95'][1], True)}] | {indep_txt} | "
          f"{obj['p_boot_two_sided']:.4f} | {wins} |")
    a("")

    a(MD_H2 + "2. Six-Cell Mechanistic Behavioral and Posterior Metrics")
    a("")
    a("| Metric | Med OC | Med IP | Med Solver | Hard OC | Hard IP | Hard Solver |")
    a("|---|---:|---:|---:|---:|---:|---:|")
    cells6 = (m_oc, m_ip, m_sv, h_oc, h_ip, h_sv)
    mech_rows = [
        ("Canaries planted before accusation", lambda x: f"{x['canaries_before_accuse_mean']:.2f}"),
        ("Days with >=1 canary (mean / share of days)", lambda x: f"{x['days_with_ge1_canary_mean']:.2f} ({pct(x['days_with_ge1_canary_share'])})"),
        ("Days with 2 canaries (mean / share of days)", lambda x: f"{x['days_with_2_canaries_mean']:.2f} ({pct(x['days_with_2_canaries_share'])})"),
        ("Canary capacity used (1/day Med, 2/day Hard)", lambda x: pct(x["canary_capacity_used_share"])),
        ("First canary planted (day)", lambda x: f"{x['first_canary_day_mean']:.2f}"),
        ("Mean canary group size (staff share)", lambda x: f"{x['canary_group_size_mean']:.2f} ({pct(x['canary_group_recipient_share_mean'])})"),
        ("Mean canary variant count (max 3)", lambda x: f"{x['canary_variant_count_mean']:.2f}"),
        ("Canary Shannon split entropy (bits, max 1.585)", lambda x: f"{x['canary_split_entropy_bits_mean']:.3f}"),
        ("Canary Shannon split entropy (nats, max 1.099)", lambda x: f"{x['canary_split_entropy_nats_mean']:.3f}"),
        ("Unique staff ever covered by a canary", lambda x: f"{x['staff_covered_mean']:.1f} ({pct(x['staff_covered_share'])})"),
        ("Interviews called per episode", lambda x: f"{x['interviews_mean']:.1f}"),
        ("Full-budget days (<max canaries, 8/8 actions)", lambda x: f"{x['days_lt_cap_full_budget_count']} / {x['total_active_days']}"),
        ("Interviews on under-canaried full-budget days", lambda x: f"{x['interviews_on_lt_cap_full_days']}"),
        ("`check_leak_feed` calls per episode", lambda x: f"{x['check_leak_feed_calls_mean']:.1f}"),
        ("`read_access_logs` calls per episode", lambda x: f"{x['read_access_logs_calls_mean']:.1f}"),
        ("Total tool calls per episode", lambda x: f"{x['total_tool_calls_mean']:.1f}"),
        ("Accusation day (accused episodes)", lambda x: f"{x['accuse_day_accused_mean']:.2f}"),
        ("Decision day (abstentions at horizon 14/21)", lambda x: f"{x['accuse_day_with_horizon_mean']:.2f}"),
        ("Abstention rate (count / 30)", lambda x: f"{pct(x['abstention_rate'])} ({x['abstained_count']}/30)"),
        ("Wrong accusations (expected from posteriors)", lambda x: f"{x['wrong_count']} ({x['expected_wrong_from_posteriors']:.1f})"),
        ("Strict consistent-set size `|C|` at accusation (mean)", lambda x: f"{x['consistent_size_at_accuse_mean']:.2f}"),
        ("Accusations at `|C| = 0` / `|C| = 1` / `|C| > 1`",
         lambda x: f"{x['consistent_eq_0_at_accuse']} / {x['consistent_eq_1_at_accuse']} / {x['consistent_gt_1_at_accuse']}"),
        ("Mole excluded from strict `C` at accusation", lambda x: f"{x['mole_excluded_from_consistent_at_accuse_count']}/{x['accused_count']}"),
        ("Episodes with >=1 surfaced 5% variant flip", lambda x: f"{x['episodes_with_seen_flip_count']}/30"),
        ("Wait days after first `|C| = 1` (hesitation)", lambda x: f"{x['wait_days_after_first_c1_mean']:.2f} ({x['hesitated_after_c1_count']} eps)"),
        ("Solver posterior `P(accused)` mean / median", lambda x: f"{x['p_accused_mean']:.3f} / {x['p_accused_median']:.3f}"),
        ("Accusations at P >=0.95 / 0.85-0.95 / 0.60-0.85 / <0.60",
         lambda x: (f"{x['p_accused_buckets']['ge_0.95']} / {x['p_accused_buckets']['0.85_to_0.95']} / "
                    f"{x['p_accused_buckets']['0.60_to_0.85']} / {x['p_accused_buckets']['lt_0.60']}")),
        ("Negative-EV accusations (`EV < 0` under Solver)", lambda x: f"{x['ev_negative_accuse_count']}"),
    ]
    for label, fn in mech_rows:
        a(f"| {label} | " + " | ".join(fn(x) for x in cells6) + " |")
    a("")
    a("(In `canary/env.py`, the access-log tool is named `read_access_logs`; zero `get_access_logs` aliases exist.)")
    a("")

    a(MD_H2 + "3. Exact Additive V Decompositions Across 30 Paired Seeds")
    a("")
    a("For every episode where an agent accuses, `true_V = 1 - leak_damage * L - canary_cost * C - R` and "
      "`luck_adjusted = true_V - (1 - P) * (1 + true_V)`. Across 30 paired seeds, the difference `A - B` "
      "decomposes with zero residual into commitment posterior quality `-(pen_A - pen_B)` on jointly accused seeds, "
      "asymmetric accusation/abstention terms (`A`-only accused vs `A`-abstained), leak timing, canary cost, "
      "restriction cost, and luck (`realized - luck_adjusted`).")
    a("")
    a("| Paired Comparison (30 seeds, V units) | Luck-Adj Diff | Commitment Quality | A-Only Accused | A-Abstained | Leak Timing | Canary Cost | Restrict | Luck Diff | Raw Diff |")
    a("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    dec_rows = [
        ("Medium: OpenCode - In-Process", dec["oc_minus_ip_medium"]),
        ("Hard: OpenCode - In-Process", dec["oc_minus_ip_hard"]),
        ("Medium: OpenCode - Solver", dec["oc_minus_solver_medium"]),
        ("Medium: In-Process - Solver", dec["ip_minus_solver_medium"]),
        ("Hard: OpenCode - Solver", dec["oc_minus_solver_hard"]),
        ("Hard: In-Process - Solver", dec["ip_minus_solver_hard"]),
    ]
    for label, d in dec_rows:
        t = d["terms_sum_30_seeds"]
        a(f"| {label} | **{f2(d['luck_adjusted_diff_sum'], True)}** | "
          f"{f2(t['posterior_commitment_quality'], True)} | {f2(t['a_only_accused_gain'], True)} | "
          f"{f2(t['a_abstained_loss'], True)} | {f2(t['leak_timing_value'], True)} | "
          f"{f2(t['canary_cost_value'], True)} | {f2(t['restriction_cost_value'], True)} | "
          f"{f2(t['luck_diff'], True)} | **{f2(d['raw_diff_sum'], True)}** |")
    a("")

    a(MD_H2 + "4. Proof Part I: Why OpenCode Hits Parity and Beats In-Process on Medium")
    a("")
    d_med = dec["oc_minus_ip_medium"]["terms_sum_30_seeds"]
    d_oc_sv_m = dec["oc_minus_solver_medium"]["terms_sum_30_seeds"]
    a(f"1. **Noiseless set elimination is exact on Medium.** With `N = 20`, `fingerprint_accuracy = 1.00`, and no "
      f"clearance constraints, every leaked canary variant and regular document is a 0/1 set intersection with zero "
      f"false exclusions (`mole in C` in `30/30` OpenCode and `26/26` In-Process accusations). Whenever `|C| = 1` "
      f"surfaces in `check_leak_feed`, **both harnesses accuse on that exact day** (`0.00` wait days after first `|C| = 1` "
      f"across `27/27` OpenCode and `22/22` In-Process isolated episodes).")
    a(f"2. **Why OpenCode beats In-Process (`+5.48 V` raw = `+0.183/ep`, `+5.18 V` luck-adjusted = `+0.173/ep`):** "
      f"In-Process starts its first canary later (`day {m_ip['first_canary_day_mean']:.2f}` vs `{m_oc['first_canary_day_mean']:.2f}`) "
      f"and burns `{m_ip['days_lt_cap_full_budget_count']}` active days exhausting all 8 actions on interviews with 0 canaries "
      f"(vs `{m_oc['days_lt_cap_full_budget_count']}` for OpenCode; `{m_ip['interviews_mean']:.1f}` vs `{m_oc['interviews_mean']:.1f}` "
      f"interviews/episode). Consequently, In-Process reaches the day-14 horizon with `|C| >= 2` on **5 seeds (`3, 7, 8, 12, 18`)**: "
      f"it abstains on 4 (`seeds 3, 7, 8, 12`, losing `{d_med['a_only_accused_gain']:+.2f} V` of luck-adjusted value that OpenCode "
      f"captured on those exact 4 seeds) and guesses wrong on seed 18 (`-1.00`, `|C| = 2`, `P = 0.554`).")
    a(f"3. **Why Medium OpenCode is `111%` raw yet `101%` luck-adjusted vs Solver:** On `27/30` seeds OpenCode isolated "
      f"`|C| = 1` (`P = 1.00`). On the remaining 3 seeds (`7, 23, 29`), `|C| = 2` remained (`P = 0.627, 0.660, 0.558`), "
      f"and OpenCode committed anyway -- winning all 3 coin-tilted bets for `{d_oc_sv_m['luck_a']:+.2f} V` (`+{m_oc['luck_realization_mean']:.3f}/ep`) "
      f"of positive luck, while `SolverPolicy` rationally abstained on 3 unresolved horizon seeds (`20, 21, 29`). Removing luck "
      f"puts OpenCode (`{m_oc['luck_adjusted_mean']:.3f}`) and Solver (`{m_sv['luck_adjusted_mean']:.3f}`) at exact parity (`101.1%`).")
    a("")
    a("| Seed | IP Outcome | IP Score | IP 1st Canary | IP Canaries / Interviews | IP End `|C|` (`P_top`) | OC Score (Day) | OC Canaries | OC `|C|` (`P_acc`) | Solver Score (Day) |")
    a("|---:|---|---:|---:|---|---:|---|---:|---|---:|")
    for row in mech["medium_noiseless_set_elimination"]["inproc_non_correct_episodes"]:
        a(f"| {row['seed']} | {row['ip_outcome']} | {row['ip_score']:+.2f} | day {row['ip_first_canary_day']} | "
          f"{row['ip_canaries']} / {row['ip_interviews']} | {row['ip_c_size_end']} ({row['ip_p_end']:.2f}) | "
          f"{row['oc_score']:+.2f} (d{row['oc_accuse_day']}) | {row['oc_canaries']} | "
          f"{row['oc_c_size']} ({row['oc_p_accused']:.2f}) | "
          f"{row['solver_score']:+.2f} ({'d' + str(row['solver_accuse_day']) if row['solver_accuse_day'] else 'abstain'}) |")
    a("")

    a(MD_H2 + "5. Proof Part II: Why Hard Opens a Real Gap and Reverses the Harness Ranking")
    a("")
    a(f"1. **Shared model-level bottleneck -- severe canary under-exploration:** On Hard (`N = 40`, 21 days, 2 canaries/day, "
      f"2-3 day delay, clearance constraints), individual canaries planted by both harnesses are well-structured "
      f"(mean group size `{h_oc['canary_group_size_mean']:.1f}` and `{h_ip['canary_group_size_mean']:.1f}` = ~25% of staff, "
      f"3.00 variants, split entropy `{h_oc['canary_split_entropy_bits_mean']:.3f}` and `{h_ip['canary_split_entropy_bits_mean']:.3f}` "
      f"bits vs Solver's `{h_sv['canary_split_entropy_bits_mean']:.3f}` bits out of `1.585` max). The failure is **rate and "
      f"budget allocation**: OpenCode and In-Process plant only `{h_oc['canaries_before_accuse_mean']:.2f}` and "
      f"`{h_ip['canaries_before_accuse_mean']:.2f}` canaries before accusing (vs Solver's `{h_sv['canaries_before_accuse_mean']:.2f}`), "
      f"using `{pct(h_oc['canary_capacity_used_share'])}` and `{pct(h_ip['canary_capacity_used_share'])}` of the 2-canary/day "
      f"pipeline (vs Solver's `{pct(h_sv['canary_capacity_used_share'])}`) while spending `{h_oc['interviews_mean']:.1f}` and "
      f"`{h_ip['interviews_mean']:.1f}` calls on interviews (`<= 0.005` nats each).")
    a(f"2. **Why In-Process beats OpenCode on Hard (`+0.151/ep` raw, `+0.061/ep` luck-adjusted):** Under `fingerprint_accuracy = 0.95`, "
      f"a leaked canary showing variant `X` gives a `38:1` likelihood ratio (`0.95` vs `0.025`) among recipients of that canary, "
      f"**not** a noiseless exclusion. Strict set elimination fails whenever the 5% variant flip occurs:")
    a(f"   - **OpenCode (`opencode-cli+mcp_server`)** encountered 2 episodes with a surfaced 5% flip (`seeds 1, 26`); on **both**, "
      f"strict elimination collapsed to a false singleton `|C| = 1` excluding the true mole, and OpenCode accused the innocent "
      f"singleton (`-1.00` each). In addition, OpenCode's aggressive commitment habit produced `{h_oc['consistent_gt_1_at_accuse']}/29` "
      f"accusations with `|C| >= 2` (`{h_oc['p_accused_lt_0.85_count']}/29` at `P < 0.85`, mean `P(accused) = {h_oc['p_accused_mean']:.3f}`, "
      f"expected wrong `{h_oc['expected_wrong_from_posteriors']:.1f}`, actual wrong `{h_oc['wrong_count']}`).")
    a(f"   - **In-Process (`generateContent` with `thought_signature_replay = true`)** encountered **4 episodes** with a surfaced "
      f"5% variant flip (`seeds 3, 5, 6, 26`). On **seeds 3 and 5**, subsequent leaks contradicted the flipped canary and drove the "
      f"strict consistent set to **empty (`|C| = 0`)** -- a total breakdown for noiseless set elimination -- yet In-Process weighed "
      f"the 5% noise model across turns and **accused the true mole on both** (`P = 0.985` on seed 3, `+0.59`; `P = 0.901` on seed 5, "
      f"`+0.10`). On **seed 26**, a flip left `|C| = 3` (`P_top = 0.379`) and In-Process **rationally abstained (`0.00` vs OpenCode's `-1.00`)**. "
      f"Overall, In-Process achieved `P(accused) = {h_ip['p_accused_mean']:.3f}` (`{h_ip['p_accused_ge_0.85_count']}/29` at `P >= 0.85`, "
      f"expected wrong `{h_ip['expected_wrong_from_posteriors']:.1f}`, actual wrong `{h_ip['wrong_count']}`).")
    a("")

    a(MD_H3 + "5.1 All Surfaced 5% Fingerprint-Flip Episodes Across Harnesses on Hard")
    a("")
    a("| Harness | Seed | Flipped Canary (Day: Shown vs Mole's) | Strict `|C|` at Decision | Mole in `C`? | Agent Decision | Solver `P` | Score |")
    a("|---|---:|---|---:|---|---|---:|---:|")
    for h_label, key in (
        ("OpenCode", "opencode_flip_episodes"),
        ("In-Process", "inproc_flip_episodes"),
        ("SolverPolicy", "solver_flip_episodes"),
    ):
        for row in mech["hard_noisy_bayes_and_flips"][key]:
            fl_txt = ", ".join(f"{f['doc_id']} (d{f['surfaced_day']}: {f['shown']}!={f['true']})" for f in row["flips"])
            dec_txt = "abstain (d21)" if row["abstained"] else (
                f"accuse {row['accused']} d{row['accuse_day']} ({'OK' if row['correct'] else 'WRONG'})"
            )
            p_val = row["p_top_end"] if row["abstained"] else row["p_accused"]
            a(f"| {h_label} | {row['seed']} | {fl_txt} | {row['consistent_size']} | "
              f"{'yes' if row['mole_in_consistent'] else 'NO'} | {dec_txt} | {p_val:.3f} | {row['score']:+.2f} |")
    a("")

    a(MD_H3 + "5.2 Paired Outcome Divergences on Hard (Seeds Where OpenCode and In-Process Differ in Outcome)")
    a("")
    a("| Seed | OC Outcome (Day, `|C|`, Flip?, `P`) | OC Score | IP Outcome (Day, `|C|`, Flip?, `P`) | IP Score | Solver Score |")
    a("|---:|---|---:|---|---:|---:|")
    for row in mech["hard_noisy_bayes_and_flips"]["hard_outcome_divergences"]:
        oc_txt = (
            "abstain (d21)"
            if row["oc_accused"] is None
            else (
                f"{row['oc_accused']} {'OK' if row['oc_correct'] else 'WRONG'} "
                f"(d{row['oc_day']}, |C|={row['oc_c_size']}, flip={'Y' if row['oc_seen_flip'] else 'N'}, P={row['oc_p']:.2f})"
            )
        )
        ip_txt = (
            "abstain (d21)"
            if row["ip_accused"] is None
            else (
                f"{row['ip_accused']} {'OK' if row['ip_correct'] else 'WRONG'} "
                f"(d{row['ip_day']}, |C|={row['ip_c_size']}, flip={'Y' if row['ip_seen_flip'] else 'N'}, P={row['ip_p']:.2f})"
            )
        )
        a(f"| {row['seed']} | {oc_txt} | {row['oc_score']:+.2f} | {ip_txt} | {row['ip_score']:+.2f} | {row['solver_score']:+.2f} |")
    a("")

    bcm = cf["behaviour_compare_metrics"]
    pvc = cf["paired_vs_carbon_opencode"]
    d_gc = pvc["decomposition"]
    d_gs = cf["paired_vs_solver"]["decomposition"]
    a(MD_H2 + "6. Cross-Family Hard Comparison: `gpt-5.5` vs `gemini-4-carbon` vs `SolverPolicy` (OpenCode over MCP, Seeds 0-29)")
    a("")
    a(f"Pre-registered in `{cf['preregistration_commit']}` prior to execution (`{cf['run_commit']}`, `{cf['source']}`), "
      f"`{cf['agent']}` ran on Hard dev seeds `0-29` (`n = {cf['n']}`, `{cf['infra_failures']}` infra failures, "
      f"`${cf['opencode_reported_cost_usd_total']:.2f}` OpenCode-reported spend) under OpenCode `{cf['opencode_version']}` "
      f"with identical MCP-only permissions (`* = deny`, `canary_* = allow`, environment tag `{cf['env_tag']}` `{cf['env_commit']}`). "
      f"All `{cf['n']}` episodes replay in `Env('hard', seed)` with `{cf['replay_mismatches']}` mismatches.")
    a("")
    a("| Agent (Hard, Seeds 0-29) | n | Raw Score +/- CI | Raw / Solver [95% Boot CI] | Luck-Adj Score +/- CI | Luck-Adj / Solver [95% Boot CI] | Canaries (calls / ok) | Interviews (share) | Calls | Accuse Day | Correct / Wrong / Abstain | Mean P(accused) |")
    a("|---|---:|---|---|---|---|---|---|---:|---:|---|---|")
    a(f"| SolverPolicy (reference) | 30 | {f3(h_sv['raw_mean'], True)} +/- {f3(h_sv['raw_ci95_norm'])} | -- | "
      f"{f3(h_sv['luck_adjusted_mean'], True)} +/- {f3(h_sv['luck_adjusted_ci95_norm'])} | -- | "
      f"{bcm['solver_plant_canary_calls_mean']:.1f} / {h_sv['canaries_before_accuse_mean']:.2f} | "
      f"{h_sv['interviews_mean']:.1f} ({pct(bcm['solver_interview_call_share'])}) | "
      f"{h_sv['total_tool_calls_mean']:.1f} | {h_sv['accuse_day_accused_mean']:.1f} | "
      f"{h_sv['correct_count']} / {h_sv['wrong_count']} / {h_sv['abstained_count']} | {f3(h_sv['p_accused_mean'])} |")
    a(f"| gpt-5.5, OpenCode over MCP | 30 | {f3(g_oc['raw_mean'], True)} +/- {f3(g_oc['raw_ci95_norm'])} | "
      f"{pct(g_oc['vs_solver_raw_ratio'])} [{pct(g_oc['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(g_oc['vs_solver_raw_ratio_boot_ci95'][1])}] | "
      f"{f3(g_oc['luck_adjusted_mean'], True)} +/- {f3(g_oc['luck_adjusted_ci95_norm'])} | "
      f"{pct(g_oc['vs_solver_luck_adjusted_ratio'])} [{pct(g_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][0])}, {pct(g_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][1])}] | "
      f"{bcm['gpt55_plant_canary_calls_mean']:.1f} / {g_oc['canaries_before_accuse_mean']:.2f} | "
      f"{g_oc['interviews_mean']:.1f} ({pct(bcm['gpt55_interview_call_share'])}) | "
      f"{g_oc['total_tool_calls_mean']:.1f} | {g_oc['accuse_day_accused_mean']:.1f} | "
      f"{g_oc['correct_count']} / {g_oc['wrong_count']} / {g_oc['abstained_count']} | {f3(g_oc['p_accused_mean'])} |")
    a(f"| gemini-4-carbon, OpenCode over MCP | 30 | {f3(h_oc['raw_mean'], True)} +/- {f3(h_oc['raw_ci95_norm'])} | "
      f"{pct(h_oc['vs_solver_raw_ratio'])} [{pct(h_oc['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(h_oc['vs_solver_raw_ratio_boot_ci95'][1])}] | "
      f"{f3(h_oc['luck_adjusted_mean'], True)} +/- {f3(h_oc['luck_adjusted_ci95_norm'])} | "
      f"{pct(h_oc['vs_solver_luck_adjusted_ratio'])} [{pct(h_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][0])}, {pct(h_oc['vs_solver_luck_adjusted_ratio_boot_ci95'][1])}] | "
      f"{bcm['carbon_plant_canary_calls_mean']:.1f} / {h_oc['canaries_before_accuse_mean']:.2f} | "
      f"{h_oc['interviews_mean']:.1f} ({pct(bcm['carbon_interview_call_share'])}) | "
      f"{h_oc['total_tool_calls_mean']:.1f} | {h_oc['accuse_day_accused_mean']:.1f} | "
      f"{h_oc['correct_count']} / {h_oc['wrong_count']} / {h_oc['abstained_count']} | {f3(h_oc['p_accused_mean'])} |")
    a("")
    a(MD_H3 + "6.1 Paired `n = 30` Bootstrap Contrasts (`gpt-5.5` vs `gemini-4-carbon` and `SolverPolicy`)")
    a("")
    a("| Paired Contrast (Hard, Seeds 0-29) | Metric | Mean Diff (per ep) | Sum (30 seeds) | 95% Paired Boot CI | Boot 2-Sided p | Seed Wins (+ / - / tie) |")
    a("|---|---|---:|---:|---|---:|---|")
    cf_rows = [
        ("gpt-5.5 - gemini-4-carbon (OpenCode MCP)", "Raw score", pvc["raw_score"], "V"),
        ("gpt-5.5 - gemini-4-carbon (OpenCode MCP)", "Luck-adjusted", pvc["luck_adjusted_score"], "V"),
        ("gpt-5.5 - SolverPolicy (Hard)", "Raw score", g_oc["vs_solver_raw_diff"], "V"),
        ("gpt-5.5 - SolverPolicy (Hard)", "Luck-adjusted", g_oc["vs_solver_luck_adjusted_diff"], "V"),
        ("gpt-5.5 - gemini-4-carbon (OpenCode MCP)", "Canaries before accuse", pvc["canaries_before_accuse"], "can"),
        ("gpt-5.5 - gemini-4-carbon (OpenCode MCP)", "Interviews called", pvc["interviews"], "int"),
        ("gpt-5.5 - gemini-4-carbon (OpenCode MCP)", "Total tool calls", pvc["total_tool_calls"], "calls"),
    ]
    for title, metric, obj, unit in cf_rows:
        wins = f"{obj['seed_wins_pos']} / {obj['seed_wins_neg']} / {obj['seed_ties']}"
        a(f"| {title} | {metric} | **{f3(obj['point'], True)}** | {f2(obj['sum_30_seeds'], True)} {unit} | "
          f"[{f3(obj['boot_ci95'][0], True)}, {f3(obj['boot_ci95'][1], True)}] | {obj['p_boot_two_sided']:.4f} | {wins} |")
    a("")
    t_gc = d_gc["terms_sum_30_seeds"]
    t_gs = d_gs["terms_sum_30_seeds"]
    fl18 = cf["flip_episodes"][0]
    ab0, ab17 = cf["abstained_prose_only_episodes"]
    a(f"- **Decision mechanism (`results/behaviour_compare_v1.4.md` + `SolverPolicy` posterior pipeline):** With the exact same "
      f"13 MCP tools, `gpt-5.5` plants `{bcm['gpt55_plant_canary_calls_mean']:.1f}` `plant_canary` calls (`{g_oc['canaries_before_accuse_mean']:.2f}` "
      f"accepted = `{pct(g_oc['canary_capacity_used_share'])}` of 2/day capacity, starting day `{g_oc['first_canary_day_mean']:.2f}` on all 30 seeds "
      f"and covering `{g_oc['staff_covered_mean']:.1f}/40` = `{pct(g_oc['staff_covered_share'])}` of staff) while spending only "
      f"`{g_oc['interviews_mean']:.1f}` calls (`{pct(bcm['gpt55_interview_call_share'])}`) on LR-1.2 interviews, vs `gemini-4-carbon`'s "
      f"`{h_oc['canaries_before_accuse_mean']:.2f}` canaries (`{pct(h_oc['canary_capacity_used_share'])}` capacity) and "
      f"`{h_oc['interviews_mean']:.1f}` interviews (`{pct(bcm['carbon_interview_call_share'])}` of `{h_oc['total_tool_calls_mean']:.1f}` calls). "
      f"`gpt-5.5` isolates `|C| = 1` on `{bcm['gpt55_c1_isolated_any_seed_count']}/30` seeds, accuses `{h_oc['accuse_day_accused_mean'] - g_oc['accuse_day_accused_mean']:.1f}` "
      f"days earlier (`day {g_oc['accuse_day_accused_mean']:.2f}` vs `{h_oc['accuse_day_accused_mean']:.2f}`), and achieves `{g_oc['correct_count']}/{g_oc['accused_count']}` "
      f"(`0` wrong accusations, `{g_oc['ev_negative_accuse_count']}` negative-EV accusation vs `{h_oc['ev_negative_accuse_count']}`, mean `P(accused) = {g_oc['p_accused_mean']:.3f}`). "
      f"On its sole surfaced 5% variant flip (seed `{fl18['seed']}`, `{fl18['flips'][0]['doc_id']}` d`{fl18['flips'][0]['surfaced_day']}` "
      f"`{fl18['flips'][0]['shown']}!={fl18['flips'][0]['true']}`), subsequent leaks drove strict noiseless `|C| = {fl18['consistent_size']}`, "
      f"yet `gpt-5.5` integrated noisy likelihoods and accused `{fl18['accused']}` correctly on day `{fl18['accuse_day']}` (`P = {fl18['p_accused']:.3f}`, `{fl18['score']:+.2f}`).")
    a(f"- **Prose-only non-tool abstentions on seeds `{cf['summary']['abstained_seeds']}` and `meta['V_final']` accounting:** "
      f"On all `{cf['completed_meta_V_final_populated_count']}` completed accusations, `ep['meta']['V_final']` equals replayed `env.V`; "
      f"on seeds `{ab0['seed']}` and `{ab17['seed']}`, `accused is None` because `gpt-5.5` isolated `|C| = {ab0['consistent_size_end']}` "
      f"(`P_top = {ab0['p_top_end']:.3f}`, effective `V_final = {ab0['effective_V_final']:.2f}` at replayed day `{ab0['replayed_day']}` on seed `{ab0['seed']}`; "
      f"`|C| = {ab17['consistent_size_end']}`, `P_top = {ab17['p_top_end']:.3f}`, effective `V_final = {ab17['effective_V_final']:.2f}` at replayed day `{ab17['replayed_day']}` on seed `{ab17['seed']}`, "
      f"with `ep['meta']['V_final'] = None` and `recorded_final_day = 0` when the OpenCode transcript ended without calling `accuse`) and named the culprit in final prose only, "
      f"scoring `0.000` under the pre-registered rule. Across 30 seeds, `gpt-5.5 - gemini-4-carbon` (`{d_gc['raw_diff_sum']:+.2f} V` raw, `{d_gc['luck_adjusted_diff_sum']:+.2f} V` LA) "
      f"decomposes into `{t_gc['posterior_commitment_quality']:+.2f} V` commitment quality, `{t_gc['leak_timing_value']:+.2f} V` earlier leak containment, "
      f"`{t_gc['canary_cost_value']:+.2f} V` extra canary investment, `{t_gc['restriction_cost_value']:+.2f} V` restriction, `{t_gc['a_only_accused_gain']:+.2f} V` seed-11 catch, "
      f"`{t_gc['a_abstained_loss']:+.2f} V` prose-abstention loss on seeds `[0, 17]`, and `{t_gc['luck_diff']:+.2f} V` luck (`gpt-5.5 - Solver`: `{d_gs['raw_diff_sum']:+.2f} V` raw, "
      f"`{d_gs['luck_adjusted_diff_sum']:+.2f} V` LA = `{t_gs['posterior_commitment_quality']:+.2f} V` commitment + `{t_gs['a_abstained_loss']:+.2f} V` seeds `[0, 17]` "
      f"+ `{t_gs['leak_timing_value']:+.2f} V` leak timing + `{t_gs['canary_cost_value']:+.2f} V` canary cost + `{t_gs['luck_diff']:+.2f} V` luck).")
    a("")

    hm = hb["harness_matrix"]
    hc = hm["harbor_container_opencode_carbon"]
    r1, r2, r3 = hc["runs"]
    a(MD_H2 + "7. Harbor Judge-Container Harness vs Local MCP-Only OpenCode (`afterquery-final` `1bc3e281`, `aa1c679e`/`5f9b3297`)")
    a("")
    a(f"Comparing all Hard execution harnesses side-by-side connects the local `2x2` crossover (Sections 1-5) and cross-family "
      f"parity (Section 6) to the pre-registered **Harbor `{hb['harbor_version']}` judge-container rehearsal** "
      f"(`results/harbor/rehearsal/TABLE.md`, `BUILD.txt`, tag `{hb['tag']}` `{hb['build_sha_short']}`, updated with the final "
      f"`opencode-3` completion in `{hb['correction_commits'][0]}`/`{hb['correction_commits'][1]}`, full trial dirs on "
      f"`s1-rehearsal-final` `{hb['final_trials_branch_commit']}`):")
    a("")
    a("| Hard Harness & Agent | Seeds (`n` valid) | Shell (`bash`/`python3`) | Valid Accusations Right | Mean Score | Same-Seed Reference / Oracle | Ratio [95% Boot CI] |")
    a("|---|---|---|---:|---:|---:|---|")
    a(f"| Local OpenCode MCP-only (`gemini-4-carbon`) | dev `0-29` (`30`) | denied (`* = deny`, `0/30`) | "
      f"{h_oc['correct_count']}/{h_oc['accused_count']} ({pct(h_oc['conditional_accuracy'])}) | {f3(h_oc['raw_mean'], True)} | "
      f"{f3(h_sv['raw_mean'], True)} (`SolverPolicy`) | {pct(h_oc['vs_solver_raw_ratio'])} [{pct(h_oc['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(h_oc['vs_solver_raw_ratio_boot_ci95'][1])}] |")
    a(f"| Local In-Process `thought_signature` (`gemini-4-carbon`) | dev `0-29` (`30`) | none (`0/30`) | "
      f"{h_ip['correct_count']}/{h_ip['accused_count']} ({pct(h_ip['conditional_accuracy'])}) | {f3(h_ip['raw_mean'], True)} | "
      f"{f3(h_sv['raw_mean'], True)} (`SolverPolicy`) | {pct(h_ip['vs_solver_raw_ratio'])} [{pct(h_ip['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(h_ip['vs_solver_raw_ratio_boot_ci95'][1])}] |")
    a(f"| Local OpenCode MCP-only (`gpt-5.5`, `{cf['preregistration_commit']}`) | dev `0-29` (`30`) | denied (`* = deny`, `0/30`) | "
      f"{g_oc['correct_count']}/{g_oc['accused_count']} ({pct(g_oc['conditional_accuracy'])}) | {f3(g_oc['raw_mean'], True)} | "
      f"{f3(h_sv['raw_mean'], True)} (`SolverPolicy`) | {pct(g_oc['vs_solver_raw_ratio'])} [{pct(g_oc['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(g_oc['vs_solver_raw_ratio_boot_ci95'][1])}] |")
    a(f"| Harbor `opencode-1` (`gemini-4-carbon`, `{hb['build_sha_short']}`) | judge `{hb['judge_seeds']}` (`{r1['n_valid']}`) | "
      f"allowed (`{hc['shell_used_trials']}/{hc['shell_audited_trials']}` pooled) | {r1['correct']}/{r1['accused']} (90%) | "
      f"{f3(r1['mean'], True)} | {f3(r1['oracle_same_tasks'], True)} (`oracle`) | {r1['ratio_pct']}% [{r1['ratio_boot_ci95_pct'][0]}%, {r1['ratio_boot_ci95_pct'][1]}%] |")
    a(f"| Harbor `opencode-2` (`gemini-4-carbon`, `{hb['build_sha_short']}`) | judge `{hb['judge_seeds']}` (`{r2['n_valid']}`) | "
      f"allowed (`{hc['shell_used_trials']}/{hc['shell_audited_trials']}` pooled) | {r2['correct']}/{r2['accused']} (100%) | "
      f"{f3(r2['mean'], True)} | {f3(r2['oracle_same_tasks'], True)} (`oracle`) | {r2['ratio_pct']}% [{r2['ratio_boot_ci95_pct'][0]}%, {r2['ratio_boot_ci95_pct'][1]}%] |")
    a(f"| Harbor `opencode-3` final (`gemini-4-carbon`, `{hb['correction_commits'][0]}`/`{hb['correction_commits'][1]}`) | "
      f"judge `{hb['judge_seeds']}` (`{r3['n_valid']}` valid, `1` infra) | allowed (`{hc['shell_used_trials']}/{hc['shell_audited_trials']}` pooled) | "
      f"{r3['correct']}/{r3['accused']} (100%) | {f3(r3['mean'], True)} | {f3(r3['oracle_same_tasks'], True)} (same 9 tasks) | "
      f"{r3['ratio_pct']}% [{r3['ratio_boot_ci95_pct'][0]}%, {r3['ratio_boot_ci95_pct'][1]}%] |")
    a(f"| Harbor `do_nothing` / `stop_early` baselines | judge `{hb['judge_seeds']}` (`10 / 10`) | container baseline | "
      f"0/0 | +0.000 / +0.000 | {f3(hc['oracle_mean_10_tasks'], True)} (`oracle`) | 0% [0%, 0%] |")
    a("")
    snap = r3["snapshot_0852_n7"]
    a(f"- **Honest disclosure -- the MCP-only Hard gap did not reproduce in the Harbor judge container:** Across the three "
      f"Harbor runs on `{hb['judge_seeds']}`, `gemini-4-carbon` scored **`{f3(r1['mean'], True)}` (`{r1['ratio_pct']}%`)**, "
      f"**`{f3(r2['mean'], True)}` (`{r2['ratio_pct']}%`)**, and **`{f3(r3['mean'], True)}` (`{r3['ratio_pct']}%` on `n = {r3['n_valid']}` valid; "
      f"`1` provider rate-limit infra-excluded on `{r3['infra_excluded_task']}`, `{r3['finished_after_0830_cutoff']}` trials finished after the `08:30` "
      f"cut-off; `08:52` partial `n = {snap['n_valid']}` snapshot in `TABLE.md` was `{f3(snap['mean'], True)}` = `{snap['ratio_pct']}%` vs `{f3(snap['oracle_same_tasks'], True)}`)** "
      f"against the `{f3(hc['oracle_mean_10_tasks'], True)}` 10-task oracle (`{hc['oracle_correct_10_tasks']}/10` correct), with final 3-run mean of means "
      f"`{f3(hc['three_run_mean_of_means_final'], True)}` (`SD = {hc['three_run_sd_final']:.3f}`, range `{hc['three_run_range_final']:.3f}`) and "
      f"**`{hc['valid_accusations_correct']}/{hc['valid_accusations_total']}` (`{ 100.0 * hc['valid_accusation_accuracy']:.1f}%`) valid accusations correct**.")
    a(f"- **Mechanistic synthesis across harnesses:** Unlike local OpenCode MCP-only (`bash`/`python3` denied -> `{pct(h_oc['vs_solver_raw_ratio'])}` "
      f"`[{pct(h_oc['vs_solver_raw_ratio_boot_ci95'][0])}, {pct(h_oc['vs_solver_raw_ratio_boot_ci95'][1])}]`, `4/29` wrong accusations), the Harbor "
      f"container provides a shell that `gemini-4-carbon` used in **`{hc['shell_used_trials']}/{hc['shell_audited_trials']}` (`{100.0 * hc['shell_used_share']:.1f}%`)** "
      f"audited trials alongside the two disclosed 15 Nov tag updates (`1bc3e281`). While `n = 10` judge tasks cannot statistically separate shell "
      f"access from the 15 Nov tag updates and seed variance, combining Sections 5, 6, and 7 establishes a single consistent finding: on `v1.4` Hard, "
      f"frontier agents reach reference parity whenever noisy-Bayes state tracking is supported -- via model-internal discipline (`gpt-5.5` MCP-only `101%`), "
      f"persisted `thought_signature` state (`gemini-4-carbon` In-Process `95%`), or container shell access (`gemini-4-carbon` Harbor `93% / 116% / 131%`) -- "
      f"and the `65%` shortfall is specific to `gemini-4-carbon` in the shell-denied MCP-only harness.")
    a("")

    return "\n".join(lines) + "\n"


def approx_equal(a, b, tol: float = 1e-9) -> bool:
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


_LEAF_LIST_RE = re.compile(r"\[\n(?:\s*(?:null|true|false|-?\d+(?:\.\d+)?|\"[^\"\n\\]*\"),?\n)+\s*\]")


def compact_json_dumps(data: dict) -> str:
    raw = json.dumps(data, indent=1, sort_keys=True)
    collapsed = _LEAF_LIST_RE.sub(lambda m: re.sub(r"\s*\n\s*", " ", m.group(0)).replace("[ ", "[").replace(" ]", "]"), raw)
    return collapsed + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--out-json", type=Path, default=DEFAULT_OUT_JSON)
    ap.add_argument("--out-md", type=Path, default=DEFAULT_OUT_MD)
    args = ap.parse_args(argv)

    data = compute(ROOT)
    blob = compact_json_dumps(data)
    blob_bytes = len(blob.encode("utf-8"))
    if blob_bytes >= MAX_JSON_BYTES:
        print(f"JSON payload too large: {blob_bytes} bytes >= {MAX_JSON_BYTES} bytes", file=sys.stderr)
        return 1
    fresh = json.loads(blob)
    md = render_markdown(fresh)

    if args.check:
        if not args.out_json.exists():
            print(f"missing {args.out_json}", file=sys.stderr)
            return 1
        if args.out_json.stat().st_size >= MAX_JSON_BYTES:
            print(f"{args.out_json} exceeds {MAX_JSON_BYTES} bytes", file=sys.stderr)
            return 1
        committed_json = json.loads(args.out_json.read_text(encoding="utf-8"))
        if not approx_equal(committed_json, fresh):
            print(f"{args.out_json} differs from fresh computation", file=sys.stderr)
            return 1
        if not args.json_only:
            if not args.out_md.exists():
                print(f"missing {args.out_md}", file=sys.stderr)
                return 1
            committed_md = args.out_md.read_text(encoding="utf-8")
            if committed_md != md:
                print(f"{args.out_md} differs from fresh render", file=sys.stderr)
                return 1
        print(f"2x2 harness and tier analysis reproduces ({blob_bytes} bytes)")
        return 0

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(blob, encoding="utf-8")
    print(f"wrote {args.out_json} ({blob_bytes} bytes)")
    if not args.json_only:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
        print(f"wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
