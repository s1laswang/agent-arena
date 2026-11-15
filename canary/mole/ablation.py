"""Deterministic single-lever, leave-one-lever-out, and decoy-framing ablation study for frontier_synthesis_v14."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any, Iterable, Sequence

import numpy as np

from canary.baselines import DoNothing, GrokTactics, LogsOnly, StopEarlyQuit
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.counterfactual import evaluate_counterfactual
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import get_strategy
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params
from canary.solver.policy import SolverPolicy

__all__ = [
    "ABLATION_ARM_SPECS",
    "DEFAULT_ABLATION_SEEDS",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CF_SEEDS",
    "DEFAULT_CF_SOURCES",
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_REPORT_MD_PATH",
    "FORBIDDEN_ABLATION_SEED_MAX",
    "FORBIDDEN_HIGH_SEED_MIN",
    "LEVER_IDS",
    "LEVER_SPECS",
    "POLICY_NAMES",
    "RESERVED_HELDOUT_SEED_RANGE",
    "AblationArmSpec",
    "LeverSpec",
    "ablation_strategies",
    "build_ablation_arm_json",
    "check_ablation_artifacts",
    "dumps_ablation_json",
    "format_ablation_markdown_report",
    "format_ablation_summary",
    "get_ablation_arm_spec",
    "list_ablation_arm_names",
    "main",
    "normalize_ablation_seeds",
    "paired_bootstrap_ci",
    "run_ablation_study",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = ROOT / "results" / "mole_strategies" / "lever_ablation_v14.json"
DEFAULT_REPORT_MD_PATH = ROOT / "docs" / "reports" / "mole_lever_ablation_v14.md"

DEFAULT_ABLATION_SEEDS: tuple[int, ...] = tuple(range(6600, 6640))
DEFAULT_CF_SEEDS: tuple[int, ...] = tuple(range(30))
DEFAULT_CF_SOURCES: tuple[str, ...] = ("opencode", "inproc")

FORBIDDEN_ABLATION_SEED_MAX = 59
RESERVED_HELDOUT_SEED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MIN_SOLVER_RATIO = 0.50
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_BOOTSTRAP_SAMPLES = 5000
DEFAULT_BOOTSTRAP_SEED = 20261114

LEVER_IDS: tuple[str, ...] = (
    "surgical_low_recipient_shield",
    "reactive_age0_canary_oldest",
    "midgame_quiet_pacing",
    "non_decoy_peer_framing",
)

POLICY_NAMES: tuple[str, ...] = (
    "solver",
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "logs_only",
    "do_nothing",
    "stop_early_quit",
)

_LEAK_LEVER_RULES: dict[str, tuple[list[list[Any]], str]] = {
    "surgical_low_recipient_shield": (
        [["day", "<=", 6], ["recent_low_recipient_docs", ">=", 2]],
        "most_recipients",
    ),
    "reactive_age0_canary_oldest": (
        [["day", "<=", 7], ["newest_doc_age_days", "==", 0], ["n_leakable", ">=", 2]],
        "oldest",
    ),
    "midgame_quiet_pacing": (
        [["day", ">=", 5], ["day", "<=", 8], ["days_since_last_leak", "<", 2]],
        "none",
    ),
}

_LEAK_LEVER_ORDER: tuple[str, ...] = (
    "surgical_low_recipient_shield",
    "reactive_age0_canary_oldest",
    "midgame_quiet_pacing",
)


@dataclass(frozen=True)
class LeverSpec:
    lever_id: str
    short_code: str
    label: str
    single_arm: str
    leave_one_out_arm: str
    mechanism: str


@dataclass(frozen=True)
class AblationArmSpec:
    name: str
    kind: str
    leak_levers: tuple[str, ...]
    framing_mode: str
    focus_lever: str | None
    description: str

    @property
    def active_levers(self) -> tuple[str, ...]:
        if self.framing_mode == "peer":
            return (*self.leak_levers, "non_decoy_peer_framing")
        return self.leak_levers

    def to_json(self) -> dict[str, Any]:
        return build_ablation_arm_json(self.name, self.leak_levers, self.framing_mode)

    def to_strategy(self) -> MoleStrategy:
        return MoleStrategy.from_json(self.to_json())


def build_ablation_arm_json(
    name: str,
    leak_levers: Sequence[str],
    framing_mode: str,
) -> dict[str, Any]:
    if framing_mode not in ("none", "peer", "decoy"):
        raise ValueError(f"unknown framing_mode {framing_mode!r}; expected 'none', 'peer', or 'decoy'")
    unknown = set(leak_levers) - set(_LEAK_LEVER_ORDER)
    if unknown:
        raise ValueError(f"unknown leak_levers {sorted(unknown)}")

    base_frame = {"none": "none", "peer": "random_peer", "decoy": "decoy"}[framing_mode]
    rules: list[dict[str, Any]] = []
    active_set = set(leak_levers)
    for lid in _LEAK_LEVER_ORDER:
        if lid in active_set:
            conds, leak_sel = _LEAK_LEVER_RULES[lid]
            rules.append({
                "if": copy.deepcopy(conds),
                "then": {"leak": leak_sel, "frame": base_frame},
            })
    if framing_mode == "peer":
        rules.append({
            "if": [["n_restricted_colleagues", ">=", 1]],
            "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
        })
    return {
        "name": name,
        "rules": rules,
        "default": {"leak": "random_seeded", "frame": base_frame},
    }


LEVER_SPECS: dict[str, LeverSpec] = {
    "surgical_low_recipient_shield": LeverSpec(
        lever_id="surgical_low_recipient_shield",
        short_code="a",
        label="Surgical low-recipient shield",
        single_arm="only_surgical_shield",
        leave_one_out_arm="no_surgical_shield",
        mechanism="Days 1..6 when >=2 leakable docs have <=3 recipients, leak most_recipients instead of surgical traps.",
    ),
    "reactive_age0_canary_oldest": LeverSpec(
        lever_id="reactive_age0_canary_oldest",
        short_code="b",
        label="Reactive age-0 canary evasion -> oldest",
        single_arm="only_reactive_oldest",
        leave_one_out_arm="no_reactive_oldest",
        mechanism="Days 1..7 when newest_doc_age_days == 0 and n_leakable >= 2, leak oldest doc to evade reactive day-d canaries.",
    ),
    "midgame_quiet_pacing": LeverSpec(
        lever_id="midgame_quiet_pacing",
        short_code="c",
        label="Midgame quiet pacing days 5..8",
        single_arm="only_midgame_pacing",
        leave_one_out_arm="no_midgame_pacing",
        mechanism="Days 5..8 when days_since_last_leak < 2, throttle back-to-back leaks via leak='none'.",
    ),
    "non_decoy_peer_framing": LeverSpec(
        lever_id="non_decoy_peer_framing",
        short_code="d",
        label="Non-decoy peer framing vs decoy framing",
        single_arm="only_peer_framing",
        leave_one_out_arm="no_peer_framing",
        mechanism="Frame most_restricted_peer when colleagues are restricted and random_peer otherwise, avoiding dismissed angry decoy.",
    ),
}


def _build_arm_specs() -> dict[str, AblationArmSpec]:
    all_three = _LEAK_LEVER_ORDER
    items = (
        AblationArmSpec(
            name="default_v0",
            kind="baseline",
            leak_levers=(),
            framing_mode="none",
            focus_lever=None,
            description="DEFAULT_STRATEGY baseline (random_seeded leak, no extra framing).",
        ),
        AblationArmSpec(
            name="only_surgical_shield",
            kind="single_lever",
            leak_levers=("surgical_low_recipient_shield",),
            framing_mode="none",
            focus_lever="surgical_low_recipient_shield",
            description="Single-lever (a): surgical low-recipient shield on days 1..6 only.",
        ),
        AblationArmSpec(
            name="only_reactive_oldest",
            kind="single_lever",
            leak_levers=("reactive_age0_canary_oldest",),
            framing_mode="none",
            focus_lever="reactive_age0_canary_oldest",
            description="Single-lever (b): reactive age-0 canary evasion -> oldest on days 1..7 only.",
        ),
        AblationArmSpec(
            name="only_midgame_pacing",
            kind="single_lever",
            leak_levers=("midgame_quiet_pacing",),
            framing_mode="none",
            focus_lever="midgame_quiet_pacing",
            description="Single-lever (c): midgame quiet pacing on days 5..8 only.",
        ),
        AblationArmSpec(
            name="only_peer_framing",
            kind="single_lever",
            leak_levers=(),
            framing_mode="peer",
            focus_lever="non_decoy_peer_framing",
            description="Single-lever (d): non-decoy peer framing (most_restricted_peer / random_peer) only.",
        ),
        AblationArmSpec(
            name="only_decoy_framing",
            kind="decoy_control",
            leak_levers=(),
            framing_mode="decoy",
            focus_lever="non_decoy_peer_framing",
            description="Single-lever angry-decoy framing control (random_seeded leak with frame='decoy').",
        ),
        AblationArmSpec(
            name="no_surgical_shield",
            kind="leave_one_out",
            leak_levers=("reactive_age0_canary_oldest", "midgame_quiet_pacing"),
            framing_mode="peer",
            focus_lever="surgical_low_recipient_shield",
            description="Leave-one-out (-a): frontier_synthesis_v14 without surgical low-recipient shield.",
        ),
        AblationArmSpec(
            name="no_reactive_oldest",
            kind="leave_one_out",
            leak_levers=("surgical_low_recipient_shield", "midgame_quiet_pacing"),
            framing_mode="peer",
            focus_lever="reactive_age0_canary_oldest",
            description="Leave-one-out (-b): frontier_synthesis_v14 without reactive age-0 canary evasion.",
        ),
        AblationArmSpec(
            name="no_midgame_pacing",
            kind="leave_one_out",
            leak_levers=("surgical_low_recipient_shield", "reactive_age0_canary_oldest"),
            framing_mode="peer",
            focus_lever="midgame_quiet_pacing",
            description="Leave-one-out (-c): frontier_synthesis_v14 without midgame quiet pacing.",
        ),
        AblationArmSpec(
            name="no_peer_framing",
            kind="leave_one_out",
            leak_levers=all_three,
            framing_mode="none",
            focus_lever="non_decoy_peer_framing",
            description="Leave-one-out (-d): frontier_synthesis_v14 leak levers (a+b+c) with frame='none'.",
        ),
        AblationArmSpec(
            name="synthesis_decoy_framing",
            kind="decoy_control",
            leak_levers=all_three,
            framing_mode="decoy",
            focus_lever="non_decoy_peer_framing",
            description="Composite angry-decoy framing control: frontier_synthesis_v14 leak levers (a+b+c) with frame='decoy'.",
        ),
        AblationArmSpec(
            name="frontier_synthesis_v14",
            kind="composite",
            leak_levers=all_three,
            framing_mode="peer",
            focus_lever=None,
            description="Full 4-lever composite frontier_synthesis_v14 (a+b+c+d).",
        ),
    )
    out = {spec.name: spec for spec in items}
    if out["default_v0"].to_strategy() != DEFAULT_STRATEGY:
        raise AssertionError("default_v0 ablation arm diverged from DEFAULT_STRATEGY")
    if out["frontier_synthesis_v14"].to_strategy() != get_strategy("frontier_synthesis_v14"):
        raise AssertionError("frontier_synthesis_v14 ablation arm diverged from canary.mole.strategies")
    return out


ABLATION_ARM_SPECS: dict[str, AblationArmSpec] = _build_arm_specs()


def list_ablation_arm_names() -> list[str]:
    return list(ABLATION_ARM_SPECS.keys())


def get_ablation_arm_spec(name: str) -> AblationArmSpec:
    if name not in ABLATION_ARM_SPECS:
        raise KeyError(f"unknown ablation arm {name!r}; expected one of {sorted(ABLATION_ARM_SPECS)}")
    return ABLATION_ARM_SPECS[name]


def ablation_strategies(names: Sequence[str] | None = None) -> dict[str, MoleStrategy]:
    selected = list_ablation_arm_names() if names is None else list(names)
    return {name: get_ablation_arm_spec(name).to_strategy() for name in selected}


def normalize_ablation_seeds(
    seeds: str | Iterable[int] = DEFAULT_ABLATION_SEEDS,
    enforce_hygiene: bool = True,
) -> list[int]:
    if isinstance(seeds, str):
        seed_list = parse_seeds(seeds)
    else:
        raw_items = list(seeds)
        seed_list = []
        for item in raw_items:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(f"ablation seed must be int, got {item!r}")
            seed_list.append(int(item))
    if not seed_list:
        raise ValueError("ablation seeds must not be empty")
    if len(set(seed_list)) != len(seed_list):
        raise ValueError("ablation seeds must not contain duplicates")
    if enforce_hygiene:
        for s in seed_list:
            if s < 0 or s <= FORBIDDEN_ABLATION_SEED_MAX:
                raise ValueError(
                    f"seed {s} violates ablation seed hygiene (0..{FORBIDDEN_ABLATION_SEED_MAX} and negatives forbidden)"
                )
            if s in RESERVED_HELDOUT_SEED_RANGE:
                raise ValueError(f"seed {s} falls in reserved held-out range 30000..30199")
            if s >= FORBIDDEN_HIGH_SEED_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
                raise ValueError(f"seed {s} violates heldout/judge seed hygiene (800000+ and 900000+ forbidden)")
    return seed_list


def _derive_seed(base_seed: int, tag: str) -> int:
    if not tag:
        return int(base_seed)
    digest = hashlib.sha256(f"{int(base_seed)}:{tag}".encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


def paired_bootstrap_ci(
    diffs: Sequence[float],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    tag: str = "",
) -> dict[str, float | int]:
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot}")
    if not (0.0 < ci < 1.0):
        raise ValueError(f"ci must be in (0, 1), got {ci}")
    n = len(diffs)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "ci_half_width": 0.0,
        }
    arr = np.asarray(diffs, dtype=np.float64)
    mean_val = float(arr.mean())
    if n == 1 or float(arr.min()) == float(arr.max()):
        return {
            "n": int(n),
            "mean": round(mean_val, 6),
            "ci_low": round(mean_val, 6),
            "ci_high": round(mean_val, 6),
            "ci_half_width": 0.0,
        }
    rng = np.random.default_rng(_derive_seed(seed, tag))
    idx = rng.integers(0, n, size=(int(n_boot), n))
    boot_means = arr[idx].mean(axis=1)
    alpha = 0.5 * (1.0 - float(ci))
    lo, hi = np.quantile(boot_means, [alpha, 1.0 - alpha])
    ci_low = float(lo)
    ci_high = float(hi)
    return {
        "n": int(n),
        "mean": round(mean_val, 6),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "ci_half_width": round(0.5 * (ci_high - ci_low), 6),
    }


def _make_solver(tier: str) -> SolverPolicy:
    return SolverPolicy(tier if tier in TIERS else tier_params(tier), act_budget=5.0)


def _unfinished_stop_early_score(tier: str, seed: int, strat: MoleStrategy) -> float:
    env = Env(tier, seed, mole_strategy=strat)
    pol = StopEarlyQuit(seed=seed)
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(3):
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    return float(env.score())


def _eval_arm_seed_worker(task: tuple[str, str, int, dict[str, Any]]) -> dict[str, Any]:
    arm_name, tier, seed, sj = task
    strat = MoleStrategy.from_json(sj)

    sol = run_episode(Env(tier, seed, mole_strategy=strat), _make_solver(tier))
    gem = run_episode(Env(tier, seed, mole_strategy=strat), GeminiCarbonProxy(seed=seed))
    cdx = run_episode(Env(tier, seed, mole_strategy=strat), CodexHorizonProxy(seed=seed))
    grk = run_episode(Env(tier, seed, mole_strategy=strat), GrokTactics(seed=seed))
    lo = run_episode(Env(tier, seed, mole_strategy=strat), LogsOnly(seed=seed))

    env_dn = Env(tier, seed, mole_strategy=strat)
    dn = run_episode(env_dn, DoNothing(seed=seed))
    ledger_events = [
        (int(entry.day), str(entry.event), entry.detail.get("doc_id"), entry.detail.get("employee"))
        for entry in env_dn.ledger()
    ]

    seq = run_episode(Env(tier, seed, mole_strategy=strat), StopEarlyQuit(seed=seed))
    seq_unfinished = _unfinished_stop_early_score(tier, seed, strat)

    def _pack(res: Any) -> dict[str, Any]:
        return {
            "score": float(res.score),
            "correct": bool(res.correct),
            "final_day": int(res.final_day),
            "accused": res.accused is not None,
        }

    return {
        "arm": arm_name,
        "seed": int(seed),
        "policies": {
            "solver": _pack(sol),
            "gemini_carbon_proxy": _pack(gem),
            "codex_horizon_proxy": _pack(cdx),
            "grok_tactics": _pack(grk),
            "logs_only": _pack(lo),
            "do_nothing": _pack(dn),
            "stop_early_quit": {
                **_pack(seq),
                "unfinished_score": seq_unfinished,
            },
        },
        "ledger_events": ledger_events,
    }


def _cf_batch_worker(
    task: tuple[str, list[int], tuple[str, ...], dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    tier, cf_seeds, cf_sources, strat_jsons = task
    return evaluate_counterfactual(
        strategies=strat_jsons,
        seeds=cf_seeds,
        tier=tier,
        run_solver=False,
        sources=cf_sources,
        workers=1,
    )


def _validate_arm_dsl(sj: dict[str, Any], tier: str) -> tuple[bool, str]:
    parsed = MoleStrategy.from_json(sj)
    round_trip = MoleStrategy.from_json(json.loads(json.dumps(parsed.to_json())))
    if round_trip != parsed or len(parsed.rules) > MAX_RULES:
        return False, ""
    validate_strategy({"rules": sj["rules"], "default": sj["default"]})
    conds_ok = all(is_valid_rule_conds(rule["if"], tier) for rule in sj.get("rules", []))
    c_str = canonical(parsed.to_json())
    sha = hashlib.sha256(c_str.encode("utf-8")).hexdigest()[:16]
    return bool(conds_ok), sha


def _summarize_policy_runs(
    arm_name: str,
    policy_name: str,
    seed_rows: list[dict[str, Any]],
    solver_scores: list[float],
    n_boot: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    n = len(seed_rows)
    p_rows = [r["policies"][policy_name] for r in seed_rows]
    scores = [float(p["score"]) for p in p_rows]
    accs = [1.0 if p["correct"] else 0.0 for p in p_rows]
    accused_days = [float(p["final_day"]) for p in p_rows if p["accused"]]
    score_ci = paired_bootstrap_ci(
        scores,
        n_boot=n_boot,
        seed=bootstrap_seed,
        tag=f"arm:{arm_name}:{policy_name}:score",
    )
    out: dict[str, Any] = {
        "n": n,
        "score": score_ci["mean"],
        "ci_low": score_ci["ci_low"],
        "ci_high": score_ci["ci_high"],
        "ci_half_width": score_ci["ci_half_width"],
        "acc": round(sum(accs) / n, 6),
        "accused_rate": round(len(accused_days) / n, 6),
        "mean_accuse_day": round(sum(accused_days) / len(accused_days), 4) if accused_days else None,
    }
    if policy_name in ("gemini_carbon_proxy", "codex_horizon_proxy", "grok_tactics", "logs_only"):
        regrets = [sol_s - sc for sol_s, sc in zip(solver_scores, scores)]
        reg_ci = paired_bootstrap_ci(
            regrets,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"arm:{arm_name}:{policy_name}:regret",
        )
        out["regret_vs_solver"] = reg_ci
    if policy_name == "do_nothing":
        max_abs = max((abs(s) for s in scores), default=0.0)
        out["max_abs_score"] = round(max_abs, 6)
        out["all_zero"] = bool(all(s == 0.0 for s in scores))
    if policy_name == "stop_early_quit":
        unfin = [float(p["unfinished_score"]) for p in p_rows]
        max_abs = max([*(abs(s) for s in scores), *(abs(u) for u in unfin)], default=0.0)
        out["max_abs_score"] = round(max_abs, 6)
        out["unfinished_max_abs_score"] = round(max((abs(u) for u in unfin), default=0.0), 6)
        out["all_zero"] = bool(all(s == 0.0 for s in scores) and all(u == 0.0 for u in unfin))
    return out


def _compute_contrast(
    contrast_id: str,
    treatment_name: str,
    reference_name: str,
    live_by_arm: dict[str, list[dict[str, Any]]],
    cf_eps_by_arm: dict[str, dict[tuple[str, int], dict[str, Any]]],
    cf_sources: Sequence[str],
    n_boot: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    rows_a = live_by_arm[treatment_name]
    rows_b = live_by_arm[reference_name]
    if [r["seed"] for r in rows_a] != [r["seed"] for r in rows_b]:
        raise AssertionError(f"seed alignment mismatch between {treatment_name} and {reference_name}")

    def _sc(rows: list[dict[str, Any]], pol: str) -> list[float]:
        return [float(r["policies"][pol]["score"]) for r in rows]

    def _ac(rows: list[dict[str, Any]], pol: str) -> list[float]:
        return [1.0 if r["policies"][pol]["correct"] else 0.0 for r in rows]

    sol_a, sol_b = _sc(rows_a, "solver"), _sc(rows_b, "solver")
    sol_acc_a, sol_acc_b = _ac(rows_a, "solver"), _ac(rows_b, "solver")
    gem_a, gem_b = _sc(rows_a, "gemini_carbon_proxy"), _sc(rows_b, "gemini_carbon_proxy")
    cdx_a, cdx_b = _sc(rows_a, "codex_horizon_proxy"), _sc(rows_b, "codex_horizon_proxy")
    grk_a, grk_b = _sc(rows_a, "grok_tactics"), _sc(rows_b, "grok_tactics")
    lo_acc_a, lo_acc_b = _ac(rows_a, "logs_only"), _ac(rows_b, "logs_only")

    gem_reg_a = [s - g for s, g in zip(sol_a, gem_a)]
    gem_reg_b = [s - g for s, g in zip(sol_b, gem_b)]
    cdx_reg_a = [s - c for s, c in zip(sol_a, cdx_a)]
    cdx_reg_b = [s - c for s, c in zip(sol_b, cdx_b)]
    grk_reg_a = [s - g for s, g in zip(sol_a, grk_a)]
    grk_reg_b = [s - g for s, g in zip(sol_b, grk_b)]

    fmean_a = [0.5 * (g + c) for g, c in zip(gem_a, cdx_a)]
    fmean_b = [0.5 * (g + c) for g, c in zip(gem_b, cdx_b)]
    freg_a = [s - fm for s, fm in zip(sol_a, fmean_a)]
    freg_b = [s - fm for s, fm in zip(sol_b, fmean_b)]

    min_reg_a = [s - max(g, c, k) for s, g, c, k in zip(sol_a, gem_a, cdx_a, grk_a)]
    min_reg_b = [s - max(g, c, k) for s, g, c, k in zip(sol_b, gem_b, cdx_b, grk_b)]

    def _bci(diffs: list[float], metric: str) -> dict[str, float | int]:
        return paired_bootstrap_ci(
            diffs,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"contrast:{contrast_id}:{metric}",
        )

    live_deltas = {
        "solver_score_delta": _bci([a - b for a, b in zip(sol_a, sol_b)], "solver_score_delta"),
        "solver_acc_delta": _bci([a - b for a, b in zip(sol_acc_a, sol_acc_b)], "solver_acc_delta"),
        "gemini_proxy_score_delta": _bci([a - b for a, b in zip(gem_a, gem_b)], "gemini_proxy_score_delta"),
        "gemini_proxy_regret_gain": _bci([a - b for a, b in zip(gem_reg_a, gem_reg_b)], "gemini_proxy_regret_gain"),
        "codex_proxy_score_delta": _bci([a - b for a, b in zip(cdx_a, cdx_b)], "codex_proxy_score_delta"),
        "codex_proxy_regret_gain": _bci([a - b for a, b in zip(cdx_reg_a, cdx_reg_b)], "codex_proxy_regret_gain"),
        "grok_tactics_score_delta": _bci([a - b for a, b in zip(grk_a, grk_b)], "grok_tactics_score_delta"),
        "grok_tactics_regret_gain": _bci([a - b for a, b in zip(grk_reg_a, grk_reg_b)], "grok_tactics_regret_gain"),
        "mean_frontier_proxy_score_delta": _bci(
            [a - b for a, b in zip(fmean_a, fmean_b)], "mean_frontier_proxy_score_delta"
        ),
        "mean_frontier_proxy_regret_gain": _bci(
            [a - b for a, b in zip(freg_a, freg_b)], "mean_frontier_proxy_regret_gain"
        ),
        "min_proxy_regret_gain": _bci(
            [a - b for a, b in zip(min_reg_a, min_reg_b)], "min_proxy_regret_gain"
        ),
        "logs_only_acc_delta": _bci([a - b for a, b in zip(lo_acc_a, lo_acc_b)], "logs_only_acc_delta"),
    }

    cf_a = cf_eps_by_arm[treatment_name]
    cf_b = cf_eps_by_arm[reference_name]
    keys = sorted(set(cf_a.keys()) & set(cf_b.keys()))
    p_drop_gain = [float(cf_b[k]["p_true_mole"] - cf_a[k]["p_true_mole"]) for k in keys]
    ev_drop_gain = [float(cf_b[k]["optimal_ev"] - cf_a[k]["optimal_ev"]) for k in keys]
    ph_drop_gain = [float(cf_b[k]["p_true_mole_horizon"] - cf_a[k]["p_true_mole_horizon"]) for k in keys]
    evh_drop_gain = [float(cf_b[k]["optimal_ev_horizon"] - cf_a[k]["optimal_ev_horizon"]) for k in keys]
    can_delta = [float(cf_a[k]["surfaced_canaries"] - cf_b[k]["surfaced_canaries"]) for k in keys]

    cf_deltas: dict[str, Any] = {
        "p_true_mole_drop_gain": _bci(p_drop_gain, "cf_p_true_mole_drop_gain"),
        "optimal_ev_drop_gain": _bci(ev_drop_gain, "cf_optimal_ev_drop_gain"),
        "p_true_mole_horizon_drop_gain": _bci(ph_drop_gain, "cf_p_true_mole_horizon_drop_gain"),
        "optimal_ev_horizon_drop_gain": _bci(evh_drop_gain, "cf_optimal_ev_horizon_drop_gain"),
        "surfaced_canaries_delta": _bci(can_delta, "cf_surfaced_canaries_delta"),
        "by_source": {},
    }
    for src in cf_sources:
        src_keys = [k for k in keys if k[0] == src]
        cf_deltas["by_source"][src] = {
            "p_true_mole_drop_gain": _bci(
                [float(cf_b[k]["p_true_mole"] - cf_a[k]["p_true_mole"]) for k in src_keys],
                f"cf_{src}_p_true_mole_drop_gain",
            ),
            "optimal_ev_drop_gain": _bci(
                [float(cf_b[k]["optimal_ev"] - cf_a[k]["optimal_ev"]) for k in src_keys],
                f"cf_{src}_optimal_ev_drop_gain",
            ),
        }

    return {
        "contrast_id": contrast_id,
        "treatment_arm": treatment_name,
        "reference_arm": reference_name,
        "live": live_deltas,
        "counterfactual": cf_deltas,
    }


def run_ablation_study(
    tier: str = "hard",
    seeds: str | Iterable[int] = DEFAULT_ABLATION_SEEDS,
    cf_seeds: str | Iterable[int] = DEFAULT_CF_SEEDS,
    cf_sources: Iterable[str] = DEFAULT_CF_SOURCES,
    arm_names: Sequence[str] | None = None,
    workers: int = 1,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    enforce_seed_hygiene: bool = True,
    progress: bool = False,
    cache_jsonl: str | Path | None = None,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    seed_list = normalize_ablation_seeds(seeds, enforce_hygiene=enforce_seed_hygiene)
    cf_seed_list = parse_seeds(cf_seeds) if isinstance(cf_seeds, str) else [int(s) for s in cf_seeds]
    if not cf_seed_list:
        raise ValueError("cf_seeds must not be empty")
    source_tuple = tuple(str(s).strip() for s in cf_sources if str(s).strip())
    if not source_tuple:
        raise ValueError("cf_sources must not be empty")

    selected_names = list_ablation_arm_names() if arm_names is None else [str(a) for a in arm_names]
    if not selected_names:
        raise ValueError("arm_names must not be empty")
    selected_specs = [get_ablation_arm_spec(name) for name in selected_names]

    eval_specs_by_name = {spec.name: spec for spec in selected_specs}
    if "default_v0" not in eval_specs_by_name:
        eval_specs_by_name["default_v0"] = ABLATION_ARM_SPECS["default_v0"]
    eval_names = list(eval_specs_by_name.keys())

    t0 = time.monotonic()
    arm_jsons_all: dict[str, dict[str, Any]] = {
        name: eval_specs_by_name[name].to_json() for name in eval_names
    }
    live_by_arm: dict[str, list[dict[str, Any]]] = {name: [] for name in eval_names}
    cached_pairs: set[tuple[str, int]] = set()
    cache_path = Path(cache_jsonl) if cache_jsonl is not None else None
    if cache_path is not None and cache_path.is_file():
        want_seeds = set(seed_list)
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("tier") == tier and row.get("arm") in live_by_arm and int(row["seed"]) in want_seeds:
                key = (str(row["arm"]), int(row["seed"]))
                if key not in cached_pairs:
                    cached_pairs.add(key)
                    live_by_arm[str(row["arm"])].append(row)

    live_tasks: list[tuple[str, str, int, dict[str, Any]]] = []
    for name in eval_names:
        sj = arm_jsons_all[name]
        for s in seed_list:
            if (name, s) not in cached_pairs:
                live_tasks.append((name, tier, s, sj))

    eff_workers = max(1, int(workers))
    cache_fh = None
    if cache_path is not None and live_tasks:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_fh = cache_path.open("a", encoding="utf-8")

    try:
        if eff_workers > 1 and (len(live_tasks) > 1 or len(eval_names) > 2):
            with ProcessPoolExecutor(max_workers=eff_workers) as pool:
                if live_tasks:
                    done_count = len(cached_pairs)
                    total_tasks = len(cached_pairs) + len(live_tasks)
                    for row in pool.map(_eval_arm_seed_worker, live_tasks, chunksize=4):
                        row["tier"] = tier
                        live_by_arm[row["arm"]].append(row)
                        if cache_fh is not None:
                            cache_fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                            cache_fh.flush()
                        done_count += 1
                        if progress and (done_count % 100 == 0 or done_count == total_tasks):
                            print(
                                f"[ablation] live episodes {done_count}/{total_tasks} ({time.monotonic() - t0:.1f}s)",
                                file=sys.stderr,
                                flush=True,
                            )

                non_def = [n for n in eval_names if n != "default_v0"]
                if len(non_def) > 1:
                    n_chunks = min(eff_workers, len(non_def))
                    cf_tasks = []
                    for idx in range(n_chunks):
                        chunk_names = non_def[idx::n_chunks]
                        payload = {"default_v0": arm_jsons_all["default_v0"]}
                        for cn in chunk_names:
                            payload[cn] = arm_jsons_all[cn]
                        cf_tasks.append((tier, cf_seed_list, source_tuple, payload))
                    cf_reports = list(pool.map(_cf_batch_worker, cf_tasks))
                    merged_cf_strats: dict[str, Any] = {}
                    for rep in cf_reports:
                        merged_cf_strats.update(rep["strategies"])
                    cf_report = {
                        "tier": tier,
                        "seeds": cf_reports[0]["seeds"],
                        "sources": cf_reports[0]["sources"],
                        "strategies": merged_cf_strats,
                    }
                else:
                    cf_report = _cf_batch_worker((tier, cf_seed_list, source_tuple, arm_jsons_all))
        else:
            total_tasks = len(cached_pairs) + len(live_tasks)
            for offset, task in enumerate(live_tasks, 1):
                row = _eval_arm_seed_worker(task)
                row["tier"] = tier
                live_by_arm[row["arm"]].append(row)
                if cache_fh is not None:
                    cache_fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                    cache_fh.flush()
                done_count = len(cached_pairs) + offset
                if progress and (done_count % 50 == 0 or done_count == total_tasks):
                    print(
                        f"[ablation] live episodes {done_count}/{total_tasks} ({time.monotonic() - t0:.1f}s)",
                        file=sys.stderr,
                        flush=True,
                    )
            cf_report = _cf_batch_worker((tier, cf_seed_list, source_tuple, arm_jsons_all))
    finally:
        if cache_fh is not None:
            cache_fh.close()

    if progress:
        print(f"[ablation] counterfactual replay complete ({time.monotonic() - t0:.1f}s)", file=sys.stderr, flush=True)

    for name in eval_names:
        live_by_arm[name].sort(key=lambda r: int(r["seed"]))

    cf_eps_by_arm: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    for name in eval_names:
        srow = cf_report["strategies"][name]
        by_key: dict[tuple[str, int], dict[str, Any]] = {}
        for src in source_tuple:
            for ep in srow["per_source"][src]["episodes"]:
                by_key[(src, int(ep["seed"]))] = ep
        cf_eps_by_arm[name] = by_key

    base_solver_scores = [float(r["policies"]["solver"]["score"]) for r in live_by_arm["default_v0"]]
    baseline_solver_score = sum(base_solver_scores) / len(base_solver_scores)
    baseline_solver_acc = (
        sum(1.0 if r["policies"]["solver"]["correct"] else 0.0 for r in live_by_arm["default_v0"])
        / len(live_by_arm["default_v0"])
    )

    base_cf_eps = cf_eps_by_arm["default_v0"]
    cf_keys = sorted(base_cf_eps.keys())

    arms_out: dict[str, dict[str, Any]] = {}
    for spec in selected_specs:
        name = spec.name
        sj = arm_jsons_all[name]
        dsl_ok, c_sha = _validate_arm_dsl(sj, tier)
        rows = live_by_arm[name]
        sol_scores = [float(r["policies"]["solver"]["score"]) for r in rows]

        ledger_blob = json.dumps([r["ledger_events"] for r in rows], separators=(",", ":")).encode("utf-8")
        emp_ledger_hash = hashlib.sha256(ledger_blob).hexdigest()[:16]

        policies_summary = {
            pname: _summarize_policy_runs(
                arm_name=name,
                policy_name=pname,
                seed_rows=rows,
                solver_scores=sol_scores,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
            )
            for pname in POLICY_NAMES
        }

        gem_scores = [float(r["policies"]["gemini_carbon_proxy"]["score"]) for r in rows]
        cdx_scores = [float(r["policies"]["codex_horizon_proxy"]["score"]) for r in rows]
        grk_scores = [float(r["policies"]["grok_tactics"]["score"]) for r in rows]
        mean_frontier_reg = [s - 0.5 * (g + c) for s, g, c in zip(sol_scores, gem_scores, cdx_scores)]
        min_proxy_reg = [s - max(g, c, k) for s, g, c, k in zip(sol_scores, gem_scores, cdx_scores, grk_scores)]

        cf_row = cf_report["strategies"][name]
        comb = cf_row["combined"]
        cur_cf_eps = cf_eps_by_arm[name]
        p_drops = [float(base_cf_eps[k]["p_true_mole"] - cur_cf_eps[k]["p_true_mole"]) for k in cf_keys]
        ev_drops = [float(base_cf_eps[k]["optimal_ev"] - cur_cf_eps[k]["optimal_ev"]) for k in cf_keys]

        cf_summary = {
            "n_transcripts": int(comb["n"]),
            "seeds": list(comb["seeds"]),
            "p_true_mole": round(float(comb["p_true_mole"]), 6),
            "p_true_mole_horizon": round(float(comb["p_true_mole_horizon"]), 6),
            "optimal_ev": round(float(comb["optimal_ev"]), 6),
            "optimal_ev_horizon": round(float(comb["optimal_ev_horizon"]), 6),
            "top_suspect_accuracy": round(float(comb["top_suspect_accuracy"]), 6),
            "top_suspect_accuracy_horizon": round(float(comb["top_suspect_accuracy_horizon"]), 6),
            "surfaced_canaries": round(float(comb["surfaced_canaries"]), 6),
            "surfaced_total_leaks": round(float(comb["surfaced_total_leaks"]), 6),
            "surfaced_canaries_delta": round(float(comb["surfaced_canaries_delta"]), 6),
            "surfaced_total_leaks_delta": round(float(comb["surfaced_total_leaks_delta"]), 6),
            "p_true_mole_drop_vs_default": paired_bootstrap_ci(
                p_drops,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"arm:{name}:cf_p_drop",
            ),
            "optimal_ev_drop_vs_default": paired_bootstrap_ci(
                ev_drops,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"arm:{name}:cf_ev_drop",
            ),
            "per_source": {
                src: {
                    "n": int(cf_row["per_source"][src]["n"]),
                    "p_true_mole": round(float(cf_row["per_source"][src]["p_true_mole"]), 6),
                    "p_true_mole_drop": round(float(cf_row["per_source"][src]["p_true_mole_drop"]), 6),
                    "optimal_ev": round(float(cf_row["per_source"][src]["optimal_ev"]), 6),
                    "optimal_ev_drop": round(float(cf_row["per_source"][src]["optimal_ev_drop"]), 6),
                    "surfaced_canaries": round(float(cf_row["per_source"][src]["surfaced_canaries"]), 6),
                }
                for src in source_tuple
            },
        }

        sol_acc = float(policies_summary["solver"]["acc"])
        sol_score = float(policies_summary["solver"]["score"])
        dn_zero = bool(policies_summary["do_nothing"]["all_zero"])
        seq_zero = bool(policies_summary["stop_early_quit"]["all_zero"])
        lo_acc = float(policies_summary["logs_only"]["acc"])
        lo_score = float(policies_summary["logs_only"]["score"])

        gates = {
            "dsl_valid": bool(dsl_ok),
            "solver_acc_ge_min": bool(sol_acc >= float(min_solver_acc)),
            "solver_ratio_ge_min": bool(sol_score >= float(min_solver_ratio) * baseline_solver_score),
            "do_nothing_zero": dn_zero,
            "stop_early_quit_zero": seq_zero,
            "logs_only_bounded": bool(lo_acc <= float(max_logs_acc) and lo_score < 0.0),
        }
        gates["passed_all"] = bool(all(gates.values()))

        arms_out[name] = {
            "name": name,
            "kind": spec.kind,
            "description": spec.description,
            "active_levers": list(spec.active_levers),
            "focus_lever": spec.focus_lever,
            "framing_mode": spec.framing_mode,
            "n_rules": len(sj["rules"]),
            "behavior_hash": behavior_hash(sj, tier),
            "canonical_sha256": c_sha,
            "empirical_ledger_hash": emp_ledger_hash,
            "strategy_json": sj,
            "policies": policies_summary,
            "regret_summary": {
                "mean_frontier_proxy_regret": paired_bootstrap_ci(
                    mean_frontier_reg,
                    n_boot=n_boot,
                    seed=bootstrap_seed,
                    tag=f"arm:{name}:mean_frontier_proxy_regret",
                ),
                "min_proxy_regret": paired_bootstrap_ci(
                    min_proxy_reg,
                    n_boot=n_boot,
                    seed=bootstrap_seed,
                    tag=f"arm:{name}:min_proxy_regret",
                ),
            },
            "counterfactual": cf_summary,
            "gates": gates,
        }

    def _maybe_contrast(cid: str, arm_a: str, arm_b: str) -> dict[str, Any] | None:
        if arm_a in arms_out and arm_b in live_by_arm and arm_a in live_by_arm:
            return _compute_contrast(
                contrast_id=cid,
                treatment_name=arm_a,
                reference_name=arm_b,
                live_by_arm=live_by_arm,
                cf_eps_by_arm=cf_eps_by_arm,
                cf_sources=source_tuple,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
            )
        return None

    lever_contributions: dict[str, dict[str, Any]] = {}
    for lid in LEVER_IDS:
        lspec = LEVER_SPECS[lid]
        entry: dict[str, Any] = {
            "lever_id": lid,
            "short_code": lspec.short_code,
            "label": lspec.label,
            "mechanism": lspec.mechanism,
            "single_arm": lspec.single_arm,
            "leave_one_out_arm": lspec.leave_one_out_arm,
            "single_lever_vs_default": _maybe_contrast(f"single:{lid}", lspec.single_arm, "default_v0"),
            "leave_one_out_in_synthesis": _maybe_contrast(
                f"loo:{lid}", "frontier_synthesis_v14", lspec.leave_one_out_arm
            ),
        }
        if lid == "non_decoy_peer_framing":
            entry["peer_vs_decoy_in_synthesis"] = _maybe_contrast(
                "peer_vs_decoy:synthesis", "frontier_synthesis_v14", "synthesis_decoy_framing"
            )
            entry["peer_vs_decoy_single_lever"] = _maybe_contrast(
                "peer_vs_decoy:single", "only_peer_framing", "only_decoy_framing"
            )
        lever_contributions[lid] = entry

    framing_control_analysis = {
        "peer_vs_decoy_in_synthesis": _maybe_contrast(
            "peer_vs_decoy:synthesis", "frontier_synthesis_v14", "synthesis_decoy_framing"
        ),
        "peer_vs_decoy_single_lever": _maybe_contrast(
            "peer_vs_decoy:single", "only_peer_framing", "only_decoy_framing"
        ),
        "decoy_vs_none_in_synthesis": _maybe_contrast(
            "decoy_vs_none:synthesis", "synthesis_decoy_framing", "no_peer_framing"
        ),
        "decoy_vs_default_single_lever": _maybe_contrast(
            "decoy_vs_default:single", "only_decoy_framing", "default_v0"
        ),
    }

    composite_vs_default = _maybe_contrast(
        "composite:frontier_synthesis_v14_vs_default_v0",
        "frontier_synthesis_v14",
        "default_v0",
    )

    canonical_hashes = [arms_out[n]["canonical_sha256"] for n in selected_names]
    ledger_hashes = [arms_out[n]["empirical_ledger_hash"] for n in selected_names]

    gates_summary = {
        "n_arms": len(selected_names),
        "n_passed": sum(1 for n in selected_names if arms_out[n]["gates"]["passed_all"]),
        "all_arms_passed": all(arms_out[n]["gates"]["passed_all"] for n in selected_names),
        "min_solver_acc_threshold": float(min_solver_acc),
        "min_solver_ratio_threshold": float(min_solver_ratio),
        "max_logs_acc_threshold": float(max_logs_acc),
        "min_solver_acc_observed": round(
            min(float(arms_out[n]["policies"]["solver"]["acc"]) for n in selected_names), 6
        ),
        "max_do_nothing_abs_score": round(
            max(float(arms_out[n]["policies"]["do_nothing"]["max_abs_score"]) for n in selected_names), 6
        ),
        "max_stop_early_quit_abs_score": round(
            max(float(arms_out[n]["policies"]["stop_early_quit"]["max_abs_score"]) for n in selected_names), 6
        ),
        "max_logs_only_acc_observed": round(
            max(float(arms_out[n]["policies"]["logs_only"]["acc"]) for n in selected_names), 6
        ),
        "unique_canonical_strategies": len(set(canonical_hashes)) == len(canonical_hashes),
        "unique_empirical_ledgers": len(set(ledger_hashes)) == len(ledger_hashes),
    }

    return {
        "study": "mole_lever_ablation_v14",
        "anchor_strategy": "frontier_synthesis_v14",
        "baseline_strategy": "default_v0",
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "seed_range": f"{seed_list[0]}-{seed_list[-1]}",
        "counterfactual_config": {
            "n_seeds_per_source": len(cf_report["seeds"]),
            "seeds": list(cf_report["seeds"]),
            "sources": list(source_tuple),
            "n_transcripts_total": len(cf_keys),
        },
        "bootstrap_config": {
            "n_boot": int(n_boot),
            "ci": 0.95,
            "seed": int(bootstrap_seed),
        },
        "baseline_reference": {
            "solver_score": round(baseline_solver_score, 6),
            "solver_acc": round(baseline_solver_acc, 6),
        },
        "gates_summary": gates_summary,
        "arms": arms_out,
        "composite_vs_default": composite_vs_default,
        "lever_contributions": lever_contributions,
        "framing_control_analysis": framing_control_analysis,
    }


def _ordered_arm_items(arms: dict[str, Any]) -> list[tuple[str, Any]]:
    ordered = [name for name in ABLATION_ARM_SPECS if name in arms]
    ordered.extend(name for name in arms if name not in ABLATION_ARM_SPECS)
    return [(name, arms[name]) for name in ordered]


def format_ablation_summary(report: dict[str, Any]) -> str:
    gs = report["gates_summary"]
    cf_cfg = report["counterfactual_config"]
    lines = [
        f"Mole Lever Ablation Study (tier={report['tier']}, seeds={report['seed_range']} n={report['n_seeds']}, "
        f"cf_transcripts={cf_cfg['n_transcripts_total']}, passed={gs['n_passed']}/{gs['n_arms']})",
        "",
        "| arm | kind | solver_acc | solver | gemini_proxy | codex_proxy | grok | logs_acc | dn | cf_P_drop | cf_EV_drop | gates |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, arm in _ordered_arm_items(report["arms"]):
        pol = arm["policies"]
        cf = arm["counterfactual"]
        status = "PASS" if arm["gates"]["passed_all"] else "FAIL"
        lines.append(
            f"| {name} | {arm['kind']} | "
            f"{pol['solver']['acc']:.2f} | {pol['solver']['score']:+.3f} | "
            f"{pol['gemini_carbon_proxy']['score']:+.3f} | {pol['codex_horizon_proxy']['score']:+.3f} | "
            f"{pol['grok_tactics']['score']:+.3f} | {pol['logs_only']['acc']:.2f} | "
            f"{pol['do_nothing']['score']:.2f} | "
            f"{cf['p_true_mole_drop_vs_default']['mean']:+.3f} | "
            f"{cf['optimal_ev_drop_vs_default']['mean']:+.3f} | {status} |"
        )

    lines.extend([
        "",
        "Marginal Lever Contributions (paired bootstrap 95% CI):",
        "| lever | mode | frontier_regret_gain [95% CI] | cf_EV_drop_gain [95% CI] | cf_P_drop_gain [95% CI] |",
        "|---|---|---|---|---|",
    ])
    for lid in LEVER_IDS:
        item = report["lever_contributions"].get(lid)
        if not item:
            continue
        for mode_label, key in (
            ("single_vs_default", "single_lever_vs_default"),
            ("loo_in_synthesis", "leave_one_out_in_synthesis"),
            ("peer_vs_decoy_synth", "peer_vs_decoy_in_synthesis"),
            ("peer_vs_decoy_single", "peer_vs_decoy_single_lever"),
        ):
            con = item.get(key)
            if not con:
                continue
            fr = con["live"]["mean_frontier_proxy_regret_gain"]
            ev = con["counterfactual"]["optimal_ev_drop_gain"]
            pd = con["counterfactual"]["p_true_mole_drop_gain"]
            lines.append(
                f"| ({item['short_code']}) {lid} | {mode_label} | "
                f"{fr['mean']:+.3f} [{fr['ci_low']:+.3f}, {fr['ci_high']:+.3f}] | "
                f"{ev['mean']:+.3f} [{ev['ci_low']:+.3f}, {ev['ci_high']:+.3f}] | "
                f"{pd['mean']:+.3f} [{pd['ci_low']:+.3f}, {pd['ci_high']:+.3f}] |"
            )
    return "\n".join(lines)


def _fmt_ci(ci_obj: dict[str, Any], digits: int = 3, signed: bool = True) -> str:
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return (
        f"{fmt.format(float(ci_obj['mean']))} "
        f"[{fmt.format(float(ci_obj['ci_low']))}, {fmt.format(float(ci_obj['ci_high']))}]"
    )


def format_ablation_markdown_report(report: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3

    gs = report["gates_summary"]
    cf_cfg = report["counterfactual_config"]
    b_cfg = report["bootstrap_config"]
    arms = report["arms"]
    comp = report.get("composite_vs_default")

    src_str = ",".join(cf_cfg["sources"])
    cf_seeds = cf_cfg["seeds"]
    cf_seed_range = f"{cf_seeds[0]}-{cf_seeds[-1]}" if cf_seeds else "n/a"

    lines: list[str] = [
        f"{h1} Mole Lever Ablation Study: `frontier_synthesis_v14` (`{report['tier']}` Tier)",
        "",
        "Generated deterministically offline (0 API calls) via "
        f"`python -m canary.mole.ablation --tier {report['tier']} --seeds {report['seed_range']} "
        f"--cf-seeds {cf_seed_range} --cf-sources {src_str} "
        "--out results/mole_strategies/lever_ablation_v14.json "
        "--report-md docs/reports/mole_lever_ablation_v14.md`.",
        "",
        f"{h2} 1. Executive Summary and Catchability / Anti-Cheese Gates",
        "",
        f"- **Live paired evaluation slice**: `n={report['n_seeds']}` fresh `{report['tier']}` seeds "
        f"(`{report['seed_range']}`), strictly disjoint from committed run seeds (`0..59`), reserved held-out "
        "evaluation seeds (`30000..30199`), and held-out/judge seeds (`800000+`, `900000+`).",
        f"- **Counterfactual frontier replay slice**: `n={cf_cfg['n_transcripts_total']}` committed v1.4 "
        f"Gemini-4-carbon `{report['tier']}` transcripts (`{src_str}`, seeds `{cf_seed_range}`) replayed under "
        "`canary.mole.counterfactual.ScheduleReplayPolicy` and scored with exact `SolverPolicy` posteriors.",
        f"- **Paired bootstrap uncertainty**: `{b_cfg['n_boot']}` paired resamples (`ci={b_cfg['ci']:.2f}`, "
        f"`seed={b_cfg['seed']}`).",
        f"- **Fairness and catchability gate summary**: **{gs['n_passed']}/{gs['n_arms']}** arms passed every gate "
        f"(`SolverPolicy` catchability `>= {gs['min_solver_acc_threshold']:.2f}`, observed minimum "
        f"`{gs['min_solver_acc_observed']:.3f}`; `SolverPolicy` score ratio `>= {gs['min_solver_ratio_threshold']:.2f}` "
        f"of `default_v0` baseline `{report['baseline_reference']['solver_score']:+.3f}`; "
        f"`LogsOnly` accuracy `<= {gs['max_logs_acc_threshold']:.2f}`, observed maximum "
        f"`{gs['max_logs_only_acc_observed']:.3f}`; `DoNothing` max `|score| == {gs['max_do_nothing_abs_score']:.3f}`; "
        f"`StopEarlyQuit` max `|score| == {gs['max_stop_early_quit_abs_score']:.3f}`).",
        f"- **Distinctness**: `unique_canonical_strategies={gs['unique_canonical_strategies']}`, "
        f"`unique_empirical_ledgers={gs['unique_empirical_ledgers']}`.",
    ]

    if comp is not None:
        c_live = comp["live"]
        c_cf = comp["counterfactual"]
        lines.append(
            f"- **Full composite (`frontier_synthesis_v14` vs `default_v0`)**: "
            f"mean frontier proxy regret gain `{_fmt_ci(c_live['mean_frontier_proxy_regret_gain'])}`, "
            f"Gemini proxy score delta `{_fmt_ci(c_live['gemini_proxy_score_delta'])}`, "
            f"Codex proxy score delta `{_fmt_ci(c_live['codex_proxy_score_delta'])}`, "
            f"counterfactual `P(true mole)` drop `{_fmt_ci(c_cf['p_true_mole_drop_gain'])}`, "
            f"counterfactual `optimal_ev` drop `{_fmt_ci(c_cf['optimal_ev_drop_gain'])}`, "
            f"while `SolverPolicy` score delta is `{_fmt_ci(c_live['solver_score_delta'])}`."
        )

    lines.extend([
        "",
        f"{h2} 2. Lever Specifications and Experimental Design",
        "",
        "Every lever uses only public-free, non-omniscient `MoleView` features from `canary.mole.dsl` "
        "(no canary labels, no investigator belief state) and <=4 total DSL rules.",
        "",
        "| Code | Lever ID | Single-Lever Arm | Leave-One-Out Arm | Mechanism |",
        "|---|---|---|---|---|",
    ])
    for lid in LEVER_IDS:
        lspec = LEVER_SPECS[lid]
        lines.append(
            f"| `({lspec.short_code})` | `{lid}` | `{lspec.single_arm}` | `{lspec.leave_one_out_arm}` | {lspec.mechanism} |"
        )

    lines.extend([
        "",
        f"{h2} 3. Paired 12-Arm Live and Counterfactual Results",
        "",
        "| Arm | Kind | Solver Acc | Solver Score | Gemini Proxy | Codex Proxy | Grok | Frontier Regret | LogsOnly Acc (Score) | DoNothing | StopEarly | CF P(mole) Drop | CF EV Drop | Surf Canaries | Gates |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ])
    for name, arm in _ordered_arm_items(arms):
        pol = arm["policies"]
        cf = arm["counterfactual"]
        reg = arm["regret_summary"]["mean_frontier_proxy_regret"]
        status = "PASS" if arm["gates"]["passed_all"] else "FAIL"
        lines.append(
            f"| `{name}` | `{arm['kind']}` | "
            f"{pol['solver']['acc']:.3f} | {pol['solver']['score']:+.3f} +/- {pol['solver']['ci_half_width']:.3f} | "
            f"{pol['gemini_carbon_proxy']['score']:+.3f} | {pol['codex_horizon_proxy']['score']:+.3f} | "
            f"{pol['grok_tactics']['score']:+.3f} | {reg['mean']:+.3f} | "
            f"{pol['logs_only']['acc']:.3f} ({pol['logs_only']['score']:+.3f}) | "
            f"{pol['do_nothing']['score']:+.3f} | {pol['stop_early_quit']['score']:+.3f} | "
            f"{cf['p_true_mole_drop_vs_default']['mean']:+.3f} | "
            f"{cf['optimal_ev_drop_vs_default']['mean']:+.3f} | "
            f"{cf['surfaced_canaries']:.2f} | {status} |"
        )

    lines.extend([
        "",
        f"{h2} 4. Marginal Lever Contributions (Single-Lever Additions and Leave-One-Lever-Out)",
        "",
        "Positive regret gain and positive counterfactual `P(true mole)` / `optimal_ev` drop indicate the lever "
        "increases investigator difficulty relative to the reference arm (`single_lever` vs `default_v0`, or full "
        "`frontier_synthesis_v14` vs `leave_one_out`).",
        "",
        "| Lever | Contrast | Solver Score Delta [95% CI] | Gemini Regret Gain [95% CI] | Codex Regret Gain [95% CI] | Frontier Regret Gain [95% CI] | CF P(mole) Drop Gain [95% CI] | CF EV Drop Gain [95% CI] | CF Canaries Delta [95% CI] |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for lid in LEVER_IDS:
        item = report["lever_contributions"].get(lid)
        if not item:
            continue
        for mode_label, key in (
            (f"`{item['single_arm']}` vs `default_v0`", "single_lever_vs_default"),
            (f"`frontier_synthesis_v14` vs `{item['leave_one_out_arm']}`", "leave_one_out_in_synthesis"),
        ):
            con = item.get(key)
            if not con:
                continue
            lv = con["live"]
            cf = con["counterfactual"]
            lines.append(
                f"| `({item['short_code']}) {lid}` | {mode_label} | "
                f"{_fmt_ci(lv['solver_score_delta'])} | "
                f"{_fmt_ci(lv['gemini_proxy_regret_gain'])} | "
                f"{_fmt_ci(lv['codex_proxy_regret_gain'])} | "
                f"{_fmt_ci(lv['mean_frontier_proxy_regret_gain'])} | "
                f"{_fmt_ci(cf['p_true_mole_drop_gain'])} | "
                f"{_fmt_ci(cf['optimal_ev_drop_gain'])} | "
                f"{_fmt_ci(cf['surfaced_canaries_delta'])} |"
            )

    lines.extend([
        "",
        f"{h3} 4.1 Counterfactual Drop Split by Frontier Harness (`opencode` vs `inproc`)",
        "",
        "| Lever | Contrast | OpenCode CF P(mole) Drop Gain [95% CI] | OpenCode CF EV Drop Gain [95% CI] | In-Proc CF P(mole) Drop Gain [95% CI] | In-Proc CF EV Drop Gain [95% CI] |",
        "|---|---|---|---|---|---|",
    ])
    for lid in LEVER_IDS:
        item = report["lever_contributions"].get(lid)
        if not item:
            continue
        for mode_label, key in (
            ("single_vs_default", "single_lever_vs_default"),
            ("loo_in_synthesis", "leave_one_out_in_synthesis"),
        ):
            con = item.get(key)
            if not con:
                continue
            by_src = con["counterfactual"].get("by_source", {})
            oc = by_src.get("opencode")
            ip = by_src.get("inproc")
            if not oc or not ip:
                continue
            lines.append(
                f"| `({item['short_code']}) {lid}` | `{mode_label}` | "
                f"{_fmt_ci(oc['p_true_mole_drop_gain'])} | {_fmt_ci(oc['optimal_ev_drop_gain'])} | "
                f"{_fmt_ci(ip['p_true_mole_drop_gain'])} | {_fmt_ci(ip['optimal_ev_drop_gain'])} |"
            )

    lines.extend([
        "",
        f"{h2} 5. Non-Decoy Peer Framing vs Angry-Decoy Framing Controls",
        "",
        "Committed frontier transcripts showed 100% dismissal of the angry decoy (`0` accusations and `0` restrictions "
        "across 159 decoy-enabled episodes), whereas non-decoy peer after-hours log framing broke 0-separation ties "
        "into wrong accusations. The two decoy control arms (`only_decoy_framing` and `synthesis_decoy_framing`) isolate "
        "framing choice while holding leak selection identical.",
        "",
        "| Framing Contrast | Treatment vs Reference | Frontier Regret Gain [95% CI] | Gemini Score Delta [95% CI] | Codex Score Delta [95% CI] | CF P(mole) Drop Gain [95% CI] | CF EV Drop Gain [95% CI] |",
        "|---|---|---|---|---|---|---|",
    ])
    fc = report.get("framing_control_analysis", {})
    for label, key in (
        ("Peer vs Decoy (composite)", "peer_vs_decoy_in_synthesis"),
        ("Peer vs Decoy (single-lever)", "peer_vs_decoy_single_lever"),
        ("Decoy vs None (composite)", "decoy_vs_none_in_synthesis"),
        ("Decoy vs Default (single-lever)", "decoy_vs_default_single_lever"),
    ):
        con = fc.get(key)
        if not con:
            continue
        lv = con["live"]
        cf = con["counterfactual"]
        lines.append(
            f"| {label} | `{con['treatment_arm']}` vs `{con['reference_arm']}` | "
            f"{_fmt_ci(lv['mean_frontier_proxy_regret_gain'])} | "
            f"{_fmt_ci(lv['gemini_proxy_score_delta'])} | "
            f"{_fmt_ci(lv['codex_proxy_score_delta'])} | "
            f"{_fmt_ci(cf['p_true_mole_drop_gain'])} | "
            f"{_fmt_ci(cf['optimal_ev_drop_gain'])} |"
        )

    lines.extend([
        "",
        f"{h2} 6. Determinism and Strategy Provenance Hashes",
        "",
        "| Arm | Rules | Framing Mode | Active Levers | Behavior Hash | Canonical SHA-256 | Empirical Ledger Hash |",
        "|---|---|---|---|---|---|---|",
    ])
    for name, arm in _ordered_arm_items(arms):
        levs = ", ".join(arm["active_levers"]) if arm["active_levers"] else "none"
        lines.append(
            f"| `{name}` | {arm['n_rules']} | `{arm['framing_mode']}` | `{levs}` | "
            f"`{arm['behavior_hash']}` | `{arm['canonical_sha256']}` | `{arm['empirical_ledger_hash']}` |"
        )

    return "\n".join(lines) + "\n"


_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "true_mole",
    "mole_id",
    "canary_ids",
    "secret_mole",
})


def _find_forbidden_key(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in _FORBIDDEN_PAYLOAD_KEYS:
                return str(k)
            hit = _find_forbidden_key(v)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for item in obj:
            hit = _find_forbidden_key(item)
            if hit is not None:
                return hit
    return None


def dumps_ablation_json(obj: Any, indent: int = 1, _level: int = 0) -> str:
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        if all(not isinstance(v, (dict, list)) for v in obj.values()):
            return json.dumps(obj, separators=(",", ":"), sort_keys=True)
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [
            f"{pad}{json.dumps(k)}:{dumps_ablation_json(obj[k], indent, _level + 1)}"
            for k in sorted(obj)
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(obj, list):
        if not obj or all(not isinstance(v, (dict, list)) for v in obj):
            return json.dumps(obj, separators=(",", ":"))
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [f"{pad}{dumps_ablation_json(v, indent, _level + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(obj)


def check_ablation_artifacts(
    json_path: Path = DEFAULT_OUTPUT_PATH,
    md_path: Path = DEFAULT_REPORT_MD_PATH,
) -> tuple[bool, str]:
    if not json_path.is_file():
        return False, f"FAIL: missing JSON artifact: {json_path}"
    if not md_path.is_file():
        return False, f"FAIL: missing Markdown report: {md_path}"

    json_text = json_path.read_text(encoding="utf-8")
    md_text = md_path.read_text(encoding="utf-8")
    for p, txt in ((json_path, json_text), (md_path, md_text)):
        if chr(0x2014) in txt or chr(0x2013) in txt:
            return False, f"FAIL: forbidden em/en dash found in {p}"

    md_lower = md_text.lower()
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    if flash_tag in md_lower and solver_pct_tag in md_lower:
        return False, f"FAIL: forbidden {flash_tag} {solver_pct_tag} ratio in {md_path}"

    try:
        report = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return False, f"FAIL: invalid JSON in {json_path}: {exc}"
    if not isinstance(report, dict):
        return False, f"FAIL: expected JSON object in {json_path}"

    bad_key = _find_forbidden_key(report)
    if bad_key is not None:
        return False, f"FAIL: forbidden secret key {bad_key!r} leaked in {json_path}"

    try:
        seeds = normalize_ablation_seeds(report.get("seeds", []), enforce_hygiene=True)
    except ValueError as exc:
        return False, f"FAIL: seed hygiene violation: {exc}"
    if len(seeds) != int(report.get("n_seeds", -1)):
        return False, f"FAIL: n_seeds mismatch ({len(seeds)} != {report.get('n_seeds')})"

    gs = report.get("gates_summary", {})
    if gs.get("all_arms_passed") is not True:
        return False, "FAIL: gates_summary.all_arms_passed is not True"
    if float(gs.get("min_solver_acc_observed", 0.0)) < float(gs.get("min_solver_acc_threshold", DEFAULT_MIN_SOLVER_ACC)):
        return False, "FAIL: solver accuracy below threshold"
    if float(gs.get("max_logs_only_acc_observed", 1.0)) > float(gs.get("max_logs_acc_threshold", DEFAULT_MAX_LOGS_ACC)):
        return False, "FAIL: logs_only accuracy above threshold"
    if float(gs.get("max_do_nothing_abs_score", 1.0)) != 0.0:
        return False, "FAIL: DoNothing score is non-zero"
    if float(gs.get("max_stop_early_quit_abs_score", 1.0)) != 0.0:
        return False, "FAIL: StopEarlyQuit score is non-zero"
    if gs.get("unique_canonical_strategies") is not True:
        return False, "FAIL: canonical strategies are not unique across arms"

    expected_md = format_ablation_markdown_report(report)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {md_path} does not match JSON ledger {json_path}"

    return (
        True,
        f"OK: {json_path.name} ({len(json_text)} bytes, n={len(seeds)} seeds, "
        f"{gs['n_passed']}/{gs['n_arms']} arms passed) matches {md_path.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.ablation")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="6600-6639")
    ap.add_argument("--cf-seeds", default="0-29")
    ap.add_argument("--cf-sources", default="opencode,inproc")
    ap.add_argument("--arms", default=None, help="comma-separated subset of ablation arm names")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--n-boot", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    ap.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--cache-jsonl", type=Path, default=None)
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report-md", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.check:
        j_path = args.out if args.out is not None else DEFAULT_OUTPUT_PATH
        m_path = args.report_md if args.report_md is not None else DEFAULT_REPORT_MD_PATH
        ok, msg = check_ablation_artifacts(json_path=j_path, md_path=m_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    arm_names = [x.strip() for x in args.arms.split(",") if x.strip()] if args.arms else None
    cf_sources = tuple(x.strip() for x in args.cf_sources.split(",") if x.strip())

    report = run_ablation_study(
        tier=args.tier,
        seeds=args.seeds,
        cf_seeds=args.cf_seeds,
        cf_sources=cf_sources,
        arm_names=arm_names,
        workers=args.workers,
        n_boot=args.n_boot,
        bootstrap_seed=args.bootstrap_seed,
        min_solver_acc=args.min_solver_acc,
        min_solver_ratio=args.min_solver_ratio,
        max_logs_acc=args.max_logs_acc,
        enforce_seed_hygiene=True,
        progress=args.progress,
        cache_jsonl=args.cache_jsonl,
    )

    json_payload = dumps_ablation_json(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json_payload + "\n", encoding="utf-8")

    if args.report_md is not None:
        args.report_md.parent.mkdir(parents=True, exist_ok=True)
        args.report_md.write_text(format_ablation_markdown_report(report), encoding="utf-8")

    if args.json:
        print(json_payload)
    else:
        print(format_ablation_summary(report))
    return 0 if report["gates_summary"]["all_arms_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
