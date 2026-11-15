"""Per-seed winnable and worked predicates ported from Sleeper to Canary Mole strategies."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import copy
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Sequence

import numpy as np

from canary.baselines import DoNothing, GrokTactics, LogsOnly, StopEarlyQuit
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, validate_strategy
from canary.forge.rl_mole import RLMole
from canary.forge_track import _strategy
from canary.mole.counterfactual import (
    DEFAULT_STRATEGY as CF_DEFAULT_STRATEGY,
    coerce_strategy,
    load_v14_frontier_episodes,
    replay_episode_counterfactual,
)
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import STRATEGY_SPECS, list_strategy_names
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params, tiers_version
from canary.solver.policy import SolverPolicy

__all__ = [
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CF_EV_DROP_THRESHOLD",
    "DEFAULT_CF_SEEDS",
    "DEFAULT_CF_SOURCES",
    "DEFAULT_HOF_V14_PATH",
    "DEFAULT_LIVE_SEEDS",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_REGRET_THRESHOLD",
    "DEFAULT_REPORT_MD_PATH",
    "FORBIDDEN_HIGH_SEED_MIN",
    "FORBIDDEN_LOW_SEED_MAX",
    "INVESTIGATOR_LABELS",
    "INVESTIGATOR_ORDER",
    "RESERVED_HELDOUT_SEED_RANGE",
    "CandidateStrategySpec",
    "breakeven_posterior",
    "build_candidate_catalog",
    "check_seed_winnable",
    "check_strategy_worked_counterfactual",
    "check_strategy_worked_live",
    "check_worked_predicate_artifacts",
    "coerce_mole_strategy",
    "dumps_compact_json",
    "evaluate_worked_predicate_study",
    "format_worked_markdown_report",
    "format_worked_summary",
    "load_committed_solver_episodes",
    "main",
    "paired_bootstrap_ci",
    "validate_eval_seeds",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = ROOT / "results" / "mole_strategies" / "worked_predicate_v14.json"
DEFAULT_REPORT_MD_PATH = ROOT / "docs" / "reports" / "mole_worked_predicate_v14.md"
DEFAULT_HOF_V14_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"

DEFAULT_LIVE_SEEDS: tuple[int, ...] = tuple(range(6240, 6280))
DEFAULT_CF_SEEDS: tuple[int, ...] = tuple(range(30))
DEFAULT_CF_SOURCES: tuple[str, ...] = ("opencode", "inproc")

FORBIDDEN_LOW_SEED_MAX = 59
RESERVED_HELDOUT_SEED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

DEFAULT_REGRET_THRESHOLD = 0.25
DEFAULT_CF_EV_DROP_THRESHOLD = 0.20
DEFAULT_MIN_SOLVER_ACC = 0.80
DEFAULT_MIN_SOLVER_RATIO = 0.50
DEFAULT_MAX_LOGS_ONLY_ACC = 0.10
DEFAULT_BOOTSTRAP_SAMPLES = 5000
DEFAULT_BOOTSTRAP_SEED = 20261114
MAX_JSON_BYTES = 95_000
FLOAT_CMP_DECIMALS = 9

INVESTIGATOR_ORDER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
)

FRONTIER_PROXY_ORDER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
)

INVESTIGATOR_LABELS: dict[str, str] = {
    "gemini_carbon_proxy": "GeminiCarbonProxy",
    "codex_horizon_proxy": "CodexHorizonProxy",
    "grok_tactics": "GrokTactics",
    "hinted_heuristic": "HintedHeuristic",
}

INVESTIGATOR_FACTORIES: dict[str, Callable[[int], Any]] = {
    "gemini_carbon_proxy": lambda s: GeminiCarbonProxy(seed=int(s)),
    "GeminiCarbonProxy": lambda s: GeminiCarbonProxy(seed=int(s)),
    "codex_horizon_proxy": lambda s: CodexHorizonProxy(seed=int(s)),
    "CodexHorizonProxy": lambda s: CodexHorizonProxy(seed=int(s)),
    "grok_tactics": lambda s: GrokTactics(seed=int(s)),
    "GrokTactics": lambda s: GrokTactics(seed=int(s)),
    "hinted_heuristic": lambda s: HintedHeuristic(seed=int(s)),
    "HintedHeuristic": lambda s: HintedHeuristic(seed=int(s)),
}

HOF_V14_ALIASES: dict[int, str] = {
    1: "window_crowd_stale",
    2: "two_wave_blackout",
    3: "surgical_trap_shield",
    4: "early_burst_midgame_pace",
}

_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "mole",
    "true_mole",
    "mole_id",
    "secret_mole",
    "canary_ids",
    "world_secret",
    "best_suspect",
    "best_suspect_horizon",
    "recorded_accused",
    "posterior",
})

_EMP_ID_TOKEN_RE = re.compile(r"\be[0-9]{2,3}\b")
_FORBIDDEN_GAP_RE = re.compile(
    r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CandidateStrategySpec:
    name: str
    cohort: str
    origin: str
    hof_rank: int | None
    hof_alias: str | None
    strategy_json: dict[str, Any]

    def to_strategy(self) -> MoleStrategy:
        return MoleStrategy.from_json(self.strategy_json)

    def to_json(self) -> dict[str, Any]:
        return copy.deepcopy(self.strategy_json)


def _canonical_strategy_key(strategy: MoleStrategy | RLMole) -> str:
    sj = strategy.to_json()
    if sj.get("kind") == "rl_mole":
        payload = {k: v for k, v in sj.items() if k != "name"}
    else:
        payload = {"rules": sj["rules"], "default": sj["default"]}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_candidate_catalog(hof_path: str | Path = DEFAULT_HOF_V14_PATH) -> dict[str, CandidateStrategySpec]:
    items: list[CandidateStrategySpec] = []
    default_json = copy.deepcopy(DEFAULT_STRATEGY.to_json())
    default_json["name"] = "default_v0"
    items.append(
        CandidateStrategySpec(
            name="default_v0",
            cohort="baseline",
            origin="canary.mole.dsl.DEFAULT_STRATEGY",
            hof_rank=None,
            hof_alias=None,
            strategy_json=default_json,
        )
    )
    for sname in list_strategy_names(include_default=False):
        spec = STRATEGY_SPECS[sname]
        items.append(
            CandidateStrategySpec(
                name=sname,
                cohort="transcript_grounded",
                origin="canary.mole.strategies",
                hof_rank=None,
                hof_alias=None,
                strategy_json=spec.to_json(),
            )
        )
    resolved_hof = Path(hof_path)
    if not resolved_hof.is_file():
        raise FileNotFoundError(f"hall of fame JSONL not found: {resolved_hof}")
    for idx, raw_line in enumerate(resolved_hof.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        row = json.loads(line)
        rank = int(row.get("rank", idx))
        sj = copy.deepcopy(row.get("strategy_json", row.get("strategy", row)))
        entry_name = f"hof_v14_rank{rank}"
        sj["name"] = entry_name
        items.append(
            CandidateStrategySpec(
                name=entry_name,
                cohort="hof_v14",
                origin="data/forge/hall_of_fame_v1.4.jsonl",
                hof_rank=rank,
                hof_alias=HOF_V14_ALIASES.get(rank),
                strategy_json=sj,
            )
        )
    return {it.name: it for it in items}


def coerce_mole_strategy(
    strategy: MoleStrategy | RLMole | dict[str, Any] | str | None,
    hof_path: str | Path = DEFAULT_HOF_V14_PATH,
) -> MoleStrategy | RLMole:
    if strategy is None:
        return coerce_strategy(CF_DEFAULT_STRATEGY, name="default_v0")
    if isinstance(strategy, str):
        key = strategy.strip()
        if key in ("default", "default_v0", DEFAULT_STRATEGY.name):
            return coerce_strategy(DEFAULT_STRATEGY, name="default_v0")
        if key in STRATEGY_SPECS:
            return STRATEGY_SPECS[key].to_strategy()
        catalog = build_candidate_catalog(hof_path=hof_path)
        if key in catalog:
            return catalog[key].to_strategy()
        for spec in catalog.values():
            if spec.hof_alias == key:
                return spec.to_strategy()
        raise KeyError(f"unknown strategy name {strategy!r}")
    if isinstance(strategy, (MoleStrategy, RLMole)):
        return coerce_strategy(strategy)
    if isinstance(strategy, dict):
        return coerce_strategy(strategy)
    raise TypeError(f"unsupported strategy type: {type(strategy).__name__}")


def _parse_seed_spec_str(spec: str) -> list[int]:
    clean = spec.strip()
    if not clean:
        raise ValueError("seeds must not be empty")
    out: list[int] = []
    for raw_part in clean.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError(f"empty seed token in {spec!r}")
        if ":" in part:
            a_s, b_s = part.split(":", 1)
            a_i, b_i = int(a_s), int(b_s)
            if b_i <= a_i:
                raise ValueError(f"empty or reversed colon seed slice {part!r}")
            out.extend(range(a_i, b_i))
        elif "-" in part and not part.startswith("-"):
            a_s, b_s = part.split("-", 1)
            a_i, b_i = int(a_s), int(b_s)
            if b_i < a_i:
                raise ValueError(f"reversed seed range {part!r}")
            out.extend(range(a_i, b_i + 1))
        else:
            out.append(int(part))
    return out


def validate_eval_seeds(
    seeds: str | Iterable[int],
    enforce_hygiene: bool = True,
) -> list[int]:
    if isinstance(seeds, str):
        parsed = _parse_seed_spec_str(seeds)
    elif isinstance(seeds, Iterable) and not isinstance(seeds, (bytes, dict)):
        parsed = []
        for item in seeds:
            if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
                raise ValueError(f"seed must be an integer, got {item!r}")
            parsed.append(int(item))
    else:
        raise ValueError(f"unsupported seeds specification: {seeds!r}")

    if not parsed:
        raise ValueError("seeds must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ValueError("seeds must not contain duplicate values")

    for s in parsed:
        if s < 0:
            raise ValueError(f"seed {s} must be non-negative")
        if enforce_hygiene:
            if s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(
                    f"seed {s} violates seed hygiene: 0..{FORBIDDEN_LOW_SEED_MAX} reserved for committed frontier runs"
                )
            if s in RESERVED_HELDOUT_SEED_RANGE:
                raise ValueError(
                    f"seed {s} violates seed hygiene: 30000..30199 reserved for held-out evaluation"
                )
            if s >= FORBIDDEN_HIGH_SEED_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
                raise ValueError(
                    f"seed {s} violates seed hygiene: >=800000 held-out and >=900000 judge seeds forbidden"
                )
    return parsed


def _derive_seed(base_seed: int, tag: str) -> int:
    digest = hashlib.sha256(f"{int(base_seed)}:{tag}".encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


def paired_bootstrap_ci(
    values: Sequence[float],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    tag: str = "",
) -> dict[str, float | int]:
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot}")
    if not (0.0 < ci < 1.0):
        raise ValueError(f"ci must be in (0, 1), got {ci}")
    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "ci_half_width": 0.0,
        }
    arr = np.asarray(values, dtype=np.float64)
    mean_val = float(arr.mean())
    if n == 1 or float(arr.min()) == float(arr.max()):
        rounded = round(mean_val, 6)
        return {
            "n": int(n),
            "mean": rounded,
            "ci_low": rounded,
            "ci_high": rounded,
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


def _unfinished_stop_early_score(tier: str, seed: int, strat: MoleStrategy | RLMole) -> float:
    env = Env(tier, int(seed), mole_strategy=strat)
    pol = StopEarlyQuit(seed=int(seed))
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(3):
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    return float(env.score())


def _instantiate_investigator(investigator_fn: Any, seed: int) -> Any:
    if isinstance(investigator_fn, str):
        key = investigator_fn.strip()
        if key not in INVESTIGATOR_FACTORIES:
            raise KeyError(f"unknown investigator {investigator_fn!r}; expected one of {sorted(INVESTIGATOR_FACTORIES)}")
        return INVESTIGATOR_FACTORIES[key](int(seed))
    if not isinstance(investigator_fn, type) and hasattr(investigator_fn, "act") and hasattr(investigator_fn, "reset"):
        return investigator_fn
    if not callable(investigator_fn):
        raise TypeError(f"investigator_fn must be callable, policy instance, or name str; got {type(investigator_fn).__name__}")

    target = investigator_fn.__init__ if isinstance(investigator_fn, type) else investigator_fn
    sig = inspect.signature(target)
    params = list(sig.parameters.values())
    if isinstance(investigator_fn, type) and params and params[0].name == "self":
        params = params[1:]

    if any(p.name == "seed" or p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
        return investigator_fn(seed=int(seed))
    if any(
        p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
        for p in params
    ):
        return investigator_fn(int(seed))
    return investigator_fn()


def check_seed_winnable(
    tier: str,
    seed: int,
    strategy: MoleStrategy | RLMole | dict[str, Any] | str | None,
) -> dict[str, Any]:
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError(f"seed must be an integer, got {seed!r}")
    seed_i = int(seed)
    strat = coerce_mole_strategy(strategy)

    sol_res = run_episode(Env(tier, seed_i, mole_strategy=strat), _make_solver(tier))
    dn_res = run_episode(Env(tier, seed_i, mole_strategy=strat), DoNothing(seed=seed_i))
    seq_res = run_episode(Env(tier, seed_i, mole_strategy=strat), StopEarlyQuit(seed=seed_i))
    seq_unfinished = _unfinished_stop_early_score(tier, seed_i, strat)
    lo_res = run_episode(Env(tier, seed_i, mole_strategy=strat), LogsOnly(seed=seed_i))

    sol_score = float(sol_res.score)
    sol_correct = bool(sol_res.correct)
    sol_accused = bool(sol_res.accused is not None)
    solver_win = bool(sol_correct and sol_accused and sol_score > 0.0)

    dn_score = float(dn_res.score)
    dn_zero = bool(dn_score == 0.0 and not bool(dn_res.correct))

    seq_score = float(seq_res.score)
    seq_zero = bool(seq_score == 0.0 and seq_unfinished == 0.0 and not bool(seq_res.correct))

    lo_score = float(lo_res.score)
    lo_correct = bool(lo_res.correct)
    lo_failed = bool(not lo_correct)

    shortcuts_fail = bool(dn_zero and seq_zero and lo_failed)
    winnable = bool(solver_win and shortcuts_fail)

    reasons: list[str] = []
    if not sol_correct or not sol_accused:
        reasons.append("solver_not_correct")
    elif sol_score <= 0.0:
        reasons.append("solver_nonpositive_score")
    if not dn_zero:
        reasons.append("do_nothing_nonzero")
    if not seq_zero:
        reasons.append("stop_early_quit_nonzero")
    if not lo_failed:
        reasons.append("logs_only_shortcut_correct")

    return {
        "tier": str(tier),
        "seed": seed_i,
        "strategy": str(strat.name),
        "winnable": winnable,
        "solver_win": solver_win,
        "shortcuts_fail": shortcuts_fail,
        "unwinnable_reasons": reasons,
        "solver": {
            "score": round(sol_score, 6),
            "correct": sol_correct,
            "accused": sol_accused,
            "final_day": int(sol_res.final_day),
        },
        "baselines": {
            "do_nothing_score": round(dn_score, 6),
            "do_nothing_zero": dn_zero,
            "stop_early_quit_score": round(seq_score, 6),
            "stop_early_quit_unfinished_score": round(seq_unfinished, 6),
            "stop_early_quit_zero": seq_zero,
            "logs_only_score": round(lo_score, 6),
            "logs_only_correct": lo_correct,
            "logs_only_failed": lo_failed,
        },
    }


def check_strategy_worked_live(
    tier: str,
    seed: int,
    strategy: MoleStrategy | RLMole | dict[str, Any] | str | None,
    investigator_fn: Any,
    regret_threshold: float = DEFAULT_REGRET_THRESHOLD,
    winnable_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if isinstance(seed, bool) or not isinstance(seed, (int, np.integer)):
        raise ValueError(f"seed must be an integer, got {seed!r}")
    seed_i = int(seed)
    strat = coerce_mole_strategy(strategy)
    win_info = copy.deepcopy(winnable_result) if winnable_result is not None else check_seed_winnable(tier, seed_i, strat)

    inv_policy = _instantiate_investigator(investigator_fn, seed_i)
    inv_name = str(getattr(inv_policy, "name", getattr(investigator_fn, "__name__", str(investigator_fn))))
    inv_res = run_episode(Env(tier, seed_i, mole_strategy=strat), inv_policy)

    winnable = bool(win_info["winnable"])
    solver_score = float(win_info["solver"]["score"])
    solver_correct = bool(win_info["solver"]["correct"])

    inv_score = float(inv_res.score)
    inv_correct = bool(inv_res.correct)
    inv_accused = bool(inv_res.accused is not None)
    paired_regret = round(solver_score - inv_score, FLOAT_CMP_DECIMALS)

    inv_failed = bool(not inv_correct)
    regret_exceeded = bool(paired_regret >= round(float(regret_threshold), FLOAT_CMP_DECIMALS))
    raw_beaten = bool(inv_failed or regret_exceeded)
    worked = False if not winnable else bool(raw_beaten)

    if (not winnable) and worked:
        raise AssertionError("anti-unfairness invariant violated: worked must be False when winnable is False")

    return {
        "tier": str(tier),
        "seed": seed_i,
        "strategy": str(strat.name),
        "investigator": inv_name,
        "winnable": winnable,
        "worked": worked,
        "raw_investigator_beaten": raw_beaten,
        "suppressed_unwinnable_credit": bool((not winnable) and raw_beaten),
        "anti_unfairness_invariant_ok": bool((not worked) if (not winnable) else True),
        "investigator_failed": inv_failed,
        "regret_exceeded": regret_exceeded,
        "regret_threshold": float(regret_threshold),
        "paired_regret": round(paired_regret, 6),
        "solver_score": round(solver_score, 6),
        "solver_correct": solver_correct,
        "investigator_score": round(inv_score, 6),
        "investigator_correct": inv_correct,
        "investigator_accused": inv_accused,
        "investigator_final_day": int(inv_res.final_day),
        "unwinnable_reasons": list(win_info.get("unwinnable_reasons", [])),
    }


def breakeven_posterior(known_v: float, wrong_accusation_score: float = -1.0) -> float:
    if wrong_accusation_score >= 0.0:
        raise ValueError(f"wrong_accusation_score must be negative, got {wrong_accusation_score}")
    if known_v < 0.0:
        raise ValueError(f"known_v must be non-negative, got {known_v}")
    return float((-wrong_accusation_score) / (known_v - wrong_accusation_score))


def _resolve_v14_reference_dir(root: str | Path | None = None) -> Path:
    if root is None:
        return ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
    base = Path(root)
    candidates = (
        base / "data" / "runs" / "committed" / "v1.4" / "reference",
        base / "v1.4" / "reference",
        base / "reference",
    )
    for cand in candidates:
        if cand.is_dir():
            return cand
    return candidates[0]


def load_committed_solver_episodes(
    seeds: Iterable[int] = DEFAULT_CF_SEEDS,
    tier: str = "hard",
    root: str | Path | None = None,
) -> dict[int, dict[str, Any]]:
    wanted = [int(s) for s in seeds]
    wanted_set = set(wanted)
    ref_dir = _resolve_v14_reference_dir(root=root)
    if not ref_dir.is_dir():
        raise FileNotFoundError(f"committed v1.4 solver reference directory not found: {ref_dir}")

    max_wanted = max(wanted) if wanted else -1
    by_seed: dict[int, dict[str, Any]] = {}
    with tiers_version("v1.4"):
        for ep_file in sorted(ref_dir.glob(f"solver-{tier}*/episodes.jsonl")):
            low_parts = tuple(p.lower() for p in ep_file.relative_to(ref_dir).parts)
            if any("superseded" in p for p in low_parts):
                continue
            if max_wanted <= 29 and any("seeds30to59" in p for p in low_parts):
                continue
            for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
                if meta.get("valid") is False or raw.get("valid") is False:
                    continue
                if raw.get("agent") != "solver" or str(raw.get("tier") or tier) != tier:
                    continue
                s = int(raw["seed"])
                if s not in wanted_set or s in by_seed:
                    continue
                by_seed[s] = {
                    "seed": s,
                    "correct": bool(raw.get("correct")),
                    "score": round(float(raw.get("score", 0.0)), 6),
                    "final_day": int(raw.get("final_day", 0)),
                    "accused": bool(raw.get("accused") is not None),
                }

    missing = sorted(wanted_set - set(by_seed.keys()))
    if missing:
        raise ValueError(f"missing committed solver-{tier} reference episodes for seeds {missing} in {ref_dir}")
    return {s: dict(by_seed[s]) for s in wanted}


def _evaluate_cf_pair_row(
    source: str,
    seed: int,
    strat_ep: dict[str, Any],
    base_ep: dict[str, Any],
    solver_ep: dict[str, Any],
    ev_drop_threshold: float,
    wrong_score: float,
) -> dict[str, Any]:
    solver_solved = bool(solver_ep["correct"] and float(solver_ep["score"]) > 0.0)

    base_v = float(base_ep["known_V"])
    strat_v = float(strat_ep["known_V"])
    base_be = breakeven_posterior(base_v, wrong_accusation_score=wrong_score)
    strat_be = breakeven_posterior(strat_v, wrong_accusation_score=wrong_score)

    base_p = float(base_ep["p_true_mole"])
    strat_p = float(strat_ep["p_true_mole"])
    base_ev = float(base_ep["optimal_ev"])
    strat_ev = float(strat_ep["optimal_ev"])

    p_drop = round(base_p - strat_p, FLOAT_CMP_DECIMALS)
    ev_drop = round(base_ev - strat_ev, FLOAT_CMP_DECIMALS)

    base_above_be = bool(round(base_p - base_be, FLOAT_CMP_DECIMALS) >= 0.0)
    strat_below_be = bool(round(strat_p - strat_be, FLOAT_CMP_DECIMALS) < 0.0)

    dropped_below_be = bool(base_above_be and strat_below_be)
    dropped_ev_ge_thresh = bool(base_above_be and ev_drop >= round(float(ev_drop_threshold), FLOAT_CMP_DECIMALS))
    raw_cf_degraded = bool(dropped_below_be or dropped_ev_ge_thresh)

    cf_worked = False if not solver_solved else bool(raw_cf_degraded)
    if (not solver_solved) and cf_worked:
        raise AssertionError("counterfactual anti-unfairness invariant violated: cf_worked must be False when solver failed")

    return {
        "source": str(source),
        "seed": int(seed),
        "cf_winnable": solver_solved,
        "cf_worked": cf_worked,
        "raw_cf_degraded": raw_cf_degraded,
        "suppressed_unwinnable_credit": bool((not solver_solved) and raw_cf_degraded),
        "anti_unfairness_invariant_ok": bool((not cf_worked) if (not solver_solved) else True),
        "dropped_below_breakeven": dropped_below_be,
        "dropped_ev_ge_threshold": dropped_ev_ge_thresh,
        "accuse_day": int(strat_ep["accuse_day"]),
        "recorded_correct": bool(strat_ep["recorded_correct"]),
        "recorded_score": round(float(strat_ep["recorded_score"]), 6),
        "solver_correct": bool(solver_ep["correct"]),
        "solver_score": round(float(solver_ep["score"]), 6),
        "base_known_v": round(base_v, 6),
        "base_breakeven_p": round(base_be, 6),
        "base_p_true_mole": round(base_p, 6),
        "base_optimal_ev": round(base_ev, 6),
        "base_above_breakeven": base_above_be,
        "strat_known_v": round(strat_v, 6),
        "strat_breakeven_p": round(strat_be, 6),
        "strat_p_true_mole": round(strat_p, 6),
        "strat_optimal_ev": round(strat_ev, 6),
        "p_true_mole_drop": round(p_drop, 6),
        "optimal_ev_drop": round(ev_drop, 6),
        "surfaced_canaries_base": int(base_ep["surfaced_canaries"]),
        "surfaced_canaries_strat": int(strat_ep["surfaced_canaries"]),
    }


def _summarize_cf_rows(
    strategy_name: str,
    tier: str,
    rows: list[dict[str, Any]],
    sources: Sequence[str],
    ev_drop_threshold: float,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    n_total = len(rows)
    winnable_rows = [r for r in rows if r["cf_winnable"]]
    base_be_winnable_rows = [r for r in winnable_rows if r["base_above_breakeven"]]

    n_winnable = len(winnable_rows)
    n_base_be_win = len(base_be_winnable_rows)
    n_worked = sum(1 for r in rows if r["cf_worked"])
    n_raw = sum(1 for r in rows if r["raw_cf_degraded"])
    n_suppressed = sum(1 for r in rows if r["suppressed_unwinnable_credit"])
    n_drop_be = sum(1 for r in winnable_rows if r["dropped_below_breakeven"])
    n_drop_ev = sum(1 for r in winnable_rows if r["dropped_ev_ge_threshold"])

    invariant_ok = all((not r["cf_worked"]) for r in rows if not r["cf_winnable"])
    if not invariant_ok:
        raise AssertionError("counterfactual anti-unfairness invariant violated in summary")

    cf_worked_vec = [1.0 if r["cf_worked"] else 0.0 for r in rows]
    cf_worked_win_vec = [1.0 if r["cf_worked"] else 0.0 for r in winnable_rows]
    p_drop_vec = [float(r["p_true_mole_drop"]) for r in rows]
    ev_drop_vec = [float(r["optimal_ev_drop"]) for r in rows]

    by_source: dict[str, Any] = {}
    for src in sources:
        s_rows = [r for r in rows if r["source"] == src]
        s_win = [r for r in s_rows if r["cf_winnable"]]
        s_be = [r for r in s_win if r["base_above_breakeven"]]
        s_worked = sum(1 for r in s_rows if r["cf_worked"])
        s_sup = sum(1 for r in s_rows if r["suppressed_unwinnable_credit"])
        by_source[src] = {
            "n_transcripts": len(s_rows),
            "n_solver_winnable": len(s_win),
            "n_base_above_breakeven_winnable": len(s_be),
            "n_cf_worked": s_worked,
            "n_suppressed_unwinnable": s_sup,
            "cf_worked_rate": round(s_worked / len(s_rows), 6) if s_rows else 0.0,
            "cf_worked_rate_given_winnable": round(s_worked / len(s_win), 6) if s_win else 0.0,
            "mean_p_true_mole_drop": round(sum(float(r["p_true_mole_drop"]) for r in s_rows) / len(s_rows), 6) if s_rows else 0.0,
            "mean_optimal_ev_drop": round(sum(float(r["optimal_ev_drop"]) for r in s_rows) / len(s_rows), 6) if s_rows else 0.0,
        }

    return {
        "tier": str(tier),
        "strategy": str(strategy_name),
        "ev_drop_threshold": float(ev_drop_threshold),
        "n_transcripts": n_total,
        "n_solver_winnable": n_winnable,
        "n_base_above_breakeven_winnable": n_base_be_win,
        "n_cf_worked": n_worked,
        "n_raw_cf_degraded": n_raw,
        "n_suppressed_unwinnable": n_suppressed,
        "n_dropped_below_breakeven": n_drop_be,
        "n_dropped_ev_ge_threshold": n_drop_ev,
        "anti_unfairness_invariant_ok": bool(invariant_ok),
        "cf_worked_rate": paired_bootstrap_ci(
            cf_worked_vec,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"cf:{strategy_name}:worked_rate",
        ),
        "cf_worked_rate_given_winnable": paired_bootstrap_ci(
            cf_worked_win_vec,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"cf:{strategy_name}:worked_given_winnable",
        ),
        "cf_worked_rate_given_base_breakeven": round(n_worked / n_base_be_win, 6) if n_base_be_win else 0.0,
        "p_true_mole_drop": paired_bootstrap_ci(
            p_drop_vec,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"cf:{strategy_name}:p_drop",
        ),
        "optimal_ev_drop": paired_bootstrap_ci(
            ev_drop_vec,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"cf:{strategy_name}:ev_drop",
        ),
        "by_source": by_source,
        "cf_worked_keys": [f"{r['source']}:{r['seed']}" for r in rows if r["cf_worked"]],
        "cf_suppressed_keys": [f"{r['source']}:{r['seed']}" for r in rows if r["suppressed_unwinnable_credit"]],
        "transcripts": rows,
    }


def check_strategy_worked_counterfactual(
    strategy: MoleStrategy | RLMole | dict[str, Any] | str | None,
    seeds: Iterable[int] = DEFAULT_CF_SEEDS,
    sources: Sequence[str] = DEFAULT_CF_SOURCES,
    tier: str = "hard",
    root: str | Path | None = None,
    ev_drop_threshold: float = DEFAULT_CF_EV_DROP_THRESHOLD,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    seed_list = [int(s) for s in seeds]
    if not seed_list:
        raise ValueError("counterfactual seeds must not be empty")
    source_tuple = tuple(str(src) for src in sources)
    if not source_tuple:
        raise ValueError("counterfactual sources must not be empty")

    strat = coerce_mole_strategy(strategy)
    loaded_frontier = load_v14_frontier_episodes(
        tier=tier,
        sources=source_tuple,
        seeds=seed_list,
        root=root,
    )
    paired_seeds = sorted(set.intersection(*(set(loaded_frontier[src].keys()) for src in source_tuple)))
    if not paired_seeds:
        raise ValueError(f"no committed v1.4 {tier} frontier episodes found for seeds {seed_list}")

    solver_by_seed = load_committed_solver_episodes(seeds=paired_seeds, tier=tier, root=root)
    wrong_score = float(tier_params(tier).wrong_accusation_score)
    is_default = _canonical_strategy_key(strat) == _canonical_strategy_key(DEFAULT_STRATEGY)

    rows: list[dict[str, Any]] = []
    for src in source_tuple:
        for s in paired_seeds:
            ep = loaded_frontier[src][s]
            base_cf = replay_episode_counterfactual(ep, DEFAULT_STRATEGY)
            strat_cf = base_cf if is_default else replay_episode_counterfactual(ep, strat)
            rows.append(
                _evaluate_cf_pair_row(
                    source=src,
                    seed=s,
                    strat_ep=strat_cf,
                    base_ep=base_cf,
                    solver_ep=solver_by_seed[s],
                    ev_drop_threshold=ev_drop_threshold,
                    wrong_score=wrong_score,
                )
            )

    summary = _summarize_cf_rows(
        strategy_name=str(strat.name),
        tier=tier,
        rows=rows,
        sources=source_tuple,
        ev_drop_threshold=ev_drop_threshold,
        n_boot=n_boot,
        bootstrap_seed=bootstrap_seed,
    )
    bad_key = _find_forbidden_key(summary)
    if bad_key is not None:
        raise AssertionError(f"secret key {bad_key!r} leaked in counterfactual output")
    return summary


def _eval_canonical_seed_worker(
    task: tuple[str, int, dict[str, Any], float],
) -> dict[str, Any]:
    tier, seed, strat_json, regret_threshold = task
    with tiers_version("v1.4"):
        strat = _strategy(strat_json)
        win_info = check_seed_winnable(tier, seed, strat)
        inv_rows: dict[str, dict[str, Any]] = {}
        for inv_key in INVESTIGATOR_ORDER:
            inv_rows[inv_key] = check_strategy_worked_live(
                tier=tier,
                seed=seed,
                strategy=strat,
                investigator_fn=INVESTIGATOR_FACTORIES[inv_key],
                regret_threshold=regret_threshold,
                winnable_result=win_info,
            )
    return {
        "seed": int(seed),
        "winnable_info": win_info,
        "investigators": inv_rows,
    }


def _eval_tagged_seed_worker(
    task: tuple[str, str, int, dict[str, Any], float],
) -> tuple[str, dict[str, Any]]:
    ckey, tier, seed, strat_json, regret_threshold = task
    return ckey, _eval_canonical_seed_worker((tier, seed, strat_json, regret_threshold))


def _validate_strategy_dsl_invariants(sj: dict[str, Any], tier: str) -> tuple[bool, str]:
    parsed = MoleStrategy.from_json(sj)
    round_trip = MoleStrategy.from_json(json.loads(json.dumps(parsed.to_json())))
    if round_trip != parsed or len(parsed.rules) > MAX_RULES:
        return False, ""
    ok, _ = validate_strategy({"rules": sj["rules"], "default": sj["default"]})
    conds_ok = all(is_valid_rule_conds(rule["if"], tier) for rule in sj.get("rules", []))
    canon_str = canonical(parsed.to_json())
    sha16 = hashlib.sha256(canon_str.encode("utf-8")).hexdigest()[:16]
    return bool(ok and conds_ok), sha16


def _summarize_live_strategy(
    spec: CandidateStrategySpec,
    tier: str,
    seed_rows: list[dict[str, Any]],
    default_seed_rows: list[dict[str, Any]],
    regret_threshold: float,
    n_boot: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    n = len(seed_rows)
    winnable_vec = [1.0 if r["winnable_info"]["winnable"] else 0.0 for r in seed_rows]
    n_winnable = sum(1 for r in seed_rows if r["winnable_info"]["winnable"])

    sol_scores = [float(r["winnable_info"]["solver"]["score"]) for r in seed_rows]
    sol_accs = [1.0 if r["winnable_info"]["solver"]["correct"] else 0.0 for r in seed_rows]
    dn_all_zero = all(bool(r["winnable_info"]["baselines"]["do_nothing_zero"]) for r in seed_rows)
    seq_all_zero = all(bool(r["winnable_info"]["baselines"]["stop_early_quit_zero"]) for r in seed_rows)
    lo_correct_seeds = [
        int(r["seed"])
        for r in seed_rows
        if bool(r["winnable_info"]["baselines"]["logs_only_correct"])
    ]
    lo_acc = round(len(lo_correct_seeds) / n, 6) if n else 0.0

    unwinnable_seeds = [
        {
            "seed": int(r["seed"]),
            "reasons": list(r["winnable_info"]["unwinnable_reasons"]),
        }
        for r in seed_rows
        if not r["winnable_info"]["winnable"]
    ]

    inv_summaries: dict[str, Any] = {}
    total_suppressed = 0
    invariant_all_ok = True

    for inv_key in INVESTIGATOR_ORDER:
        cur_inv = [r["investigators"][inv_key] for r in seed_rows]
        def_inv = [r["investigators"][inv_key] for r in default_seed_rows]

        worked_vec = [1.0 if x["worked"] else 0.0 for x in cur_inv]
        def_worked_vec = [1.0 if x["worked"] else 0.0 for x in def_inv]
        worked_win_vec = [
            1.0 if x["worked"] else 0.0
            for x, r in zip(cur_inv, seed_rows)
            if r["winnable_info"]["winnable"]
        ]
        raw_vec = [1.0 if x["raw_investigator_beaten"] else 0.0 for x in cur_inv]

        inv_scores = [float(x["investigator_score"]) for x in cur_inv]
        inv_accs = [1.0 if x["investigator_correct"] else 0.0 for x in cur_inv]
        regrets = [float(x["paired_regret"]) for x in cur_inv]
        def_regrets = [float(x["paired_regret"]) for x in def_inv]
        regrets_win = [
            float(x["paired_regret"])
            for x, r in zip(cur_inv, seed_rows)
            if r["winnable_info"]["winnable"]
        ]

        inv_ok = all((not x["worked"]) for x in cur_inv if not x["winnable"])
        if not inv_ok:
            raise AssertionError(f"anti-unfairness invariant violated on {spec.name}/{inv_key}")
        invariant_all_ok = invariant_all_ok and inv_ok

        suppressed_seeds = [int(x["seed"]) for x in cur_inv if x["suppressed_unwinnable_credit"]]
        worked_seeds = [int(x["seed"]) for x in cur_inv if x["worked"]]
        n_worked = len(worked_seeds)
        n_raw = int(sum(1 for x in cur_inv if x["raw_investigator_beaten"]))
        n_sup = len(suppressed_seeds)
        total_suppressed += n_sup

        n_by_fail = sum(1 for x in cur_inv if x["winnable"] and x["investigator_failed"])
        n_by_reg_only = sum(
            1 for x in cur_inv if x["winnable"] and (not x["investigator_failed"]) and x["regret_exceeded"]
        )

        inv_summaries[inv_key] = {
            "label": INVESTIGATOR_LABELS[inv_key],
            "n_seeds": n,
            "n_worked": n_worked,
            "n_raw_beaten": n_raw,
            "n_suppressed_unwinnable": n_sup,
            "n_worked_by_failure": n_by_fail,
            "n_worked_by_regret_only": n_by_reg_only,
            "anti_unfairness_invariant_ok": bool(inv_ok),
            "worked_rate": paired_bootstrap_ci(
                worked_vec,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:{inv_key}:worked_rate",
            ),
            "worked_rate_given_winnable": paired_bootstrap_ci(
                worked_win_vec,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:{inv_key}:worked_given_winnable",
            ),
            "raw_beaten_rate": round(sum(raw_vec) / n, 6) if n else 0.0,
            "worked_rate_delta_vs_default": paired_bootstrap_ci(
                [a - b for a, b in zip(worked_vec, def_worked_vec)],
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:{inv_key}:worked_delta",
            ),
            "investigator_acc": round(sum(inv_accs) / n, 6) if n else 0.0,
            "investigator_score": paired_bootstrap_ci(
                inv_scores,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:{inv_key}:inv_score",
            ),
            "paired_regret": paired_bootstrap_ci(
                regrets,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:{inv_key}:regret",
            ),
            "paired_regret_given_winnable": round(sum(regrets_win) / len(regrets_win), 6) if regrets_win else 0.0,
            "regret_gain_vs_default": paired_bootstrap_ci(
                [a - b for a, b in zip(regrets, def_regrets)],
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:{inv_key}:regret_gain",
            ),
            "worked_seeds": worked_seeds,
            "suppressed_seeds": suppressed_seeds,
        }

    mean4_vec = [
        0.25 * sum(1.0 if r["investigators"][ik]["worked"] else 0.0 for ik in INVESTIGATOR_ORDER)
        for r in seed_rows
    ]
    def_mean4_vec = [
        0.25 * sum(1.0 if r["investigators"][ik]["worked"] else 0.0 for ik in INVESTIGATOR_ORDER)
        for r in default_seed_rows
    ]
    frontier2_vec = [
        0.5 * sum(1.0 if r["investigators"][ik]["worked"] else 0.0 for ik in FRONTIER_PROXY_ORDER)
        for r in seed_rows
    ]
    def_frontier2_vec = [
        0.5 * sum(1.0 if r["investigators"][ik]["worked"] else 0.0 for ik in FRONTIER_PROXY_ORDER)
        for r in default_seed_rows
    ]
    all4_vec = [
        1.0 if all(r["investigators"][ik]["worked"] for ik in INVESTIGATOR_ORDER) else 0.0
        for r in seed_rows
    ]
    def_all4_vec = [
        1.0 if all(r["investigators"][ik]["worked"] for ik in INVESTIGATOR_ORDER) else 0.0
        for r in default_seed_rows
    ]
    min_worked_rate = min(float(inv_summaries[ik]["worked_rate"]["mean"]) for ik in INVESTIGATOR_ORDER)
    weakest_mole_target = min(
        INVESTIGATOR_ORDER,
        key=lambda ik: float(inv_summaries[ik]["worked_rate"]["mean"]),
    )

    return {
        "n_seeds": n,
        "regret_threshold": float(regret_threshold),
        "winnable": {
            "n_winnable": n_winnable,
            "n_unwinnable": n - n_winnable,
            "winnable_rate": paired_bootstrap_ci(
                winnable_vec,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:winnable_rate",
            ),
            "solver_acc": round(sum(sol_accs) / n, 6) if n else 0.0,
            "solver_score": paired_bootstrap_ci(
                sol_scores,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:solver_score",
            ),
            "do_nothing_all_zero": bool(dn_all_zero),
            "stop_early_quit_all_zero": bool(seq_all_zero),
            "logs_only_acc": lo_acc,
            "logs_only_correct_seeds": lo_correct_seeds,
            "unwinnable_seeds": unwinnable_seeds,
        },
        "composite": {
            "anti_unfairness_invariant_ok": bool(invariant_all_ok),
            "total_suppressed_unwinnable_credits": int(total_suppressed),
            "mean_worked_rate_4inv": paired_bootstrap_ci(
                mean4_vec,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:mean4_worked",
            ),
            "mean_worked_rate_4inv_delta_vs_default": paired_bootstrap_ci(
                [a - b for a, b in zip(mean4_vec, def_mean4_vec)],
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:mean4_worked_delta",
            ),
            "frontier_proxy_worked_rate": paired_bootstrap_ci(
                frontier2_vec,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:frontier2_worked",
            ),
            "frontier_proxy_worked_delta_vs_default": paired_bootstrap_ci(
                [a - b for a, b in zip(frontier2_vec, def_frontier2_vec)],
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:frontier2_worked_delta",
            ),
            "all_4_investigators_worked_rate": paired_bootstrap_ci(
                all4_vec,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:all4_worked",
            ),
            "all_4_investigators_worked_delta_vs_default": paired_bootstrap_ci(
                [a - b for a, b in zip(all4_vec, def_all4_vec)],
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"live:{spec.name}:all4_worked_delta",
            ),
            "minimax_worked_rate_across_4inv": round(min_worked_rate, 6),
            "hardest_investigator_for_mole": weakest_mole_target,
        },
        "per_investigator": inv_summaries,
    }


def evaluate_worked_predicate_study(
    tier: str = "hard",
    seeds: str | Iterable[int] = DEFAULT_LIVE_SEEDS,
    cf_seeds: str | Iterable[int] = DEFAULT_CF_SEEDS,
    cf_sources: Sequence[str] = DEFAULT_CF_SOURCES,
    strategy_names: Sequence[str] | None = None,
    hof_path: str | Path = DEFAULT_HOF_V14_PATH,
    committed_root: str | Path | None = None,
    regret_threshold: float = DEFAULT_REGRET_THRESHOLD,
    cf_ev_drop_threshold: float = DEFAULT_CF_EV_DROP_THRESHOLD,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_only_acc: float = DEFAULT_MAX_LOGS_ONLY_ACC,
    workers: int = 2,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    enforce_seed_hygiene: bool = True,
    progress: bool = False,
    cache_jsonl: str | Path | None = None,
) -> dict[str, Any]:
    live_seed_list = validate_eval_seeds(seeds, enforce_hygiene=enforce_seed_hygiene)
    cf_seed_list = validate_eval_seeds(cf_seeds, enforce_hygiene=False)
    cf_source_tuple = tuple(str(s) for s in cf_sources)
    if not cf_source_tuple:
        raise ValueError("cf_sources must not be empty")

    catalog = build_candidate_catalog(hof_path=hof_path)
    if strategy_names is None:
        selected_names = list(catalog.keys())
    else:
        selected_names = []
        for sname in strategy_names:
            if sname not in catalog:
                raise KeyError(f"unknown candidate strategy {sname!r}; expected one of {sorted(catalog)}")
            if sname not in selected_names:
                selected_names.append(sname)
        if "default_v0" not in selected_names:
            selected_names = ["default_v0", *selected_names]

    canon_to_json: dict[str, dict[str, Any]] = {}
    canon_first_name: dict[str, str] = {}
    name_to_canon: dict[str, str] = {}
    for sname in selected_names:
        st = catalog[sname].to_strategy()
        ckey = _canonical_strategy_key(st)
        name_to_canon[sname] = ckey
        if ckey not in canon_to_json:
            canon_to_json[ckey] = catalog[sname].to_json()
            canon_first_name[ckey] = sname

    live_by_canon: dict[str, dict[int, dict[str, Any]]] = {ckey: {} for ckey in canon_to_json}
    cache_path = Path(cache_jsonl) if cache_jsonl is not None else None
    reg_key = round(float(regret_threshold), FLOAT_CMP_DECIMALS)
    if cache_path is not None and cache_path.is_file():
        for raw_line in cache_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if (
                rec.get("tier") == tier
                and round(float(rec.get("regret_threshold", -1.0)), FLOAT_CMP_DECIMALS) == reg_key
                and rec.get("ckey") in live_by_canon
            ):
                live_by_canon[str(rec["ckey"])][int(rec["seed"])] = rec["payload"]

    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

    all_tasks: list[tuple[str, str, int, dict[str, Any], float]] = []
    for ckey, sj in canon_to_json.items():
        for s in live_seed_list:
            if s not in live_by_canon[ckey]:
                all_tasks.append((ckey, tier, s, sj, float(regret_threshold)))

    if all_tasks:
        total_tasks = len(all_tasks)
        done_count = 0
        cache_fh = cache_path.open("a", encoding="utf-8") if cache_path is not None else None
        try:
            if workers and workers > 1 and total_tasks > 1:
                with ProcessPoolExecutor(max_workers=min(int(workers), total_tasks)) as pool:
                    futures = [pool.submit(_eval_tagged_seed_worker, t) for t in all_tasks]
                    for fut in as_completed(futures):
                        ckey, row = fut.result()
                        live_by_canon[ckey][int(row["seed"])] = row
                        done_count += 1
                        if cache_fh is not None:
                            cache_fh.write(
                                json.dumps(
                                    {
                                        "tier": tier,
                                        "regret_threshold": reg_key,
                                        "ckey": ckey,
                                        "seed": int(row["seed"]),
                                        "payload": row,
                                    },
                                    separators=(",", ":"),
                                )
                                + "\n"
                            )
                            cache_fh.flush()
                        if progress and (done_count % 20 == 0 or done_count == total_tasks):
                            print(
                                f"[{done_count}/{total_tasks}] live episodes completed",
                                file=sys.stderr,
                                flush=True,
                            )
            else:
                for t in all_tasks:
                    ckey, row = _eval_tagged_seed_worker(t)
                    live_by_canon[ckey][int(row["seed"])] = row
                    done_count += 1
                    if cache_fh is not None:
                        cache_fh.write(
                            json.dumps(
                                {
                                    "tier": tier,
                                    "regret_threshold": reg_key,
                                    "ckey": ckey,
                                    "seed": int(row["seed"]),
                                    "payload": row,
                                },
                                separators=(",", ":"),
                            )
                            + "\n"
                        )
                        cache_fh.flush()
                    if progress and (done_count % 20 == 0 or done_count == total_tasks):
                        print(
                            f"[{done_count}/{total_tasks}] live episodes completed",
                            file=sys.stderr,
                            flush=True,
                        )
        finally:
            if cache_fh is not None:
                cache_fh.close()

    loaded_frontier = load_v14_frontier_episodes(
        tier=tier,
        sources=cf_source_tuple,
        seeds=cf_seed_list,
        root=committed_root,
    )
    paired_cf_seeds = sorted(set.intersection(*(set(loaded_frontier[src].keys()) for src in cf_source_tuple)))
    if not paired_cf_seeds:
        raise ValueError(f"no committed v1.4 {tier} frontier episodes found for cf_seeds {cf_seed_list}")
    solver_cf_by_seed = load_committed_solver_episodes(seeds=paired_cf_seeds, tier=tier, root=committed_root)
    wrong_score = float(tier_params(tier).wrong_accusation_score)

    default_ckey = name_to_canon["default_v0"]
    cf_replay_by_canon: dict[str, dict[tuple[str, int], dict[str, Any]]] = {}
    for ckey, sj in canon_to_json.items():
        st = DEFAULT_STRATEGY if ckey == default_ckey else MoleStrategy.from_json(sj)
        cf_replay_by_canon[ckey] = {
            (src, s): replay_episode_counterfactual(loaded_frontier[src][s], st)
            for src in cf_source_tuple
            for s in paired_cf_seeds
        }

    default_live_rows = [live_by_canon[default_ckey][s] for s in live_seed_list]
    base_solver_score = float(
        sum(float(r["winnable_info"]["solver"]["score"]) for r in default_live_rows) / len(default_live_rows)
    )

    strategies_out: dict[str, Any] = {}
    for sname in selected_names:
        spec = catalog[sname]
        ckey = name_to_canon[sname]
        s_rows = [live_by_canon[ckey][s] for s in live_seed_list]
        dsl_ok, canon_sha = _validate_strategy_dsl_invariants(spec.strategy_json, tier)
        b_hash = behavior_hash(spec.strategy_json, tier)
        dup_of = canon_first_name[ckey] if canon_first_name[ckey] != sname else None

        live_summary = _summarize_live_strategy(
            spec=spec,
            tier=tier,
            seed_rows=s_rows,
            default_seed_rows=default_live_rows,
            regret_threshold=regret_threshold,
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
        )

        cf_pair_rows = [
            _evaluate_cf_pair_row(
                source=src,
                seed=s,
                strat_ep=cf_replay_by_canon[ckey][(src, s)],
                base_ep=cf_replay_by_canon[default_ckey][(src, s)],
                solver_ep=solver_cf_by_seed[s],
                ev_drop_threshold=cf_ev_drop_threshold,
                wrong_score=wrong_score,
            )
            for src in cf_source_tuple
            for s in paired_cf_seeds
        ]
        cf_full = _summarize_cf_rows(
            strategy_name=sname,
            tier=tier,
            rows=cf_pair_rows,
            sources=cf_source_tuple,
            ev_drop_threshold=cf_ev_drop_threshold,
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
        )
        cf_compact = {k: v for k, v in cf_full.items() if k != "transcripts"}

        sol_acc = float(live_summary["winnable"]["solver_acc"])
        sol_score = float(live_summary["winnable"]["solver_score"]["mean"])
        lo_acc = float(live_summary["winnable"]["logs_only_acc"])
        dn_ok = bool(live_summary["winnable"]["do_nothing_all_zero"])
        seq_ok = bool(live_summary["winnable"]["stop_early_quit_all_zero"])
        inv_ok = bool(
            live_summary["composite"]["anti_unfairness_invariant_ok"]
            and cf_compact["anti_unfairness_invariant_ok"]
        )
        gates = {
            "dsl_valid": bool(dsl_ok),
            "solver_acc_ok": bool(round(sol_acc - float(min_solver_acc), FLOAT_CMP_DECIMALS) >= 0.0),
            "solver_ratio_ok": bool(
                base_solver_score <= 0.0
                or round(sol_score - float(min_solver_ratio) * base_solver_score, FLOAT_CMP_DECIMALS) >= 0.0
            ),
            "logs_only_acc_ok": bool(round(float(max_logs_only_acc) - lo_acc, FLOAT_CMP_DECIMALS) >= 0.0),
            "do_nothing_zero": dn_ok,
            "stop_early_quit_zero": seq_ok,
            "anti_unfairness_invariant_ok": inv_ok,
        }
        gates["passed_all"] = bool(all(gates.values()))

        strategies_out[sname] = {
            "name": sname,
            "cohort": spec.cohort,
            "origin": spec.origin,
            "hof_rank": spec.hof_rank,
            "hof_alias": spec.hof_alias,
            "canonical_duplicate_of": dup_of,
            "n_rules": len(spec.strategy_json.get("rules", [])),
            "behavior_hash": b_hash,
            "canonical_sha256": canon_sha,
            "strategy_json": spec.to_json(),
            "gates": gates,
            "live": live_summary,
            "counterfactual": cf_compact,
        }

    tg_names = [k for k, v in strategies_out.items() if v["cohort"] == "transcript_grounded"]
    hof_names = [k for k, v in strategies_out.items() if v["cohort"] == "hof_v14"]
    hof_pure_names = [
        k for k in hof_names if strategies_out[k]["canonical_duplicate_of"] is None
    ]

    def _cohort_mean(names: list[str], fn: Callable[[dict[str, Any]], float]) -> float:
        return round(sum(fn(strategies_out[k]) for k in names) / len(names), 6) if names else 0.0

    cohort_comparison = {
        "transcript_grounded_6": {
            "strategies": tg_names,
            "mean_winnable_rate": _cohort_mean(tg_names, lambda s: float(s["live"]["winnable"]["winnable_rate"]["mean"])),
            "mean_live_worked_4inv": _cohort_mean(tg_names, lambda s: float(s["live"]["composite"]["mean_worked_rate_4inv"]["mean"])),
            "mean_live_frontier_worked": _cohort_mean(tg_names, lambda s: float(s["live"]["composite"]["frontier_proxy_worked_rate"]["mean"])),
            "mean_cf_worked_rate": _cohort_mean(tg_names, lambda s: float(s["counterfactual"]["cf_worked_rate"]["mean"])),
            "best_cf_worked_strategy": max(tg_names, key=lambda k: float(strategies_out[k]["counterfactual"]["cf_worked_rate"]["mean"])) if tg_names else None,
        },
        "hof_v14_all_4": {
            "strategies": hof_names,
            "mean_winnable_rate": _cohort_mean(hof_names, lambda s: float(s["live"]["winnable"]["winnable_rate"]["mean"])),
            "mean_live_worked_4inv": _cohort_mean(hof_names, lambda s: float(s["live"]["composite"]["mean_worked_rate_4inv"]["mean"])),
            "mean_live_frontier_worked": _cohort_mean(hof_names, lambda s: float(s["live"]["composite"]["frontier_proxy_worked_rate"]["mean"])),
            "mean_cf_worked_rate": _cohort_mean(hof_names, lambda s: float(s["counterfactual"]["cf_worked_rate"]["mean"])),
        },
        "hof_v14_pure_forge_2": {
            "strategies": hof_pure_names,
            "mean_winnable_rate": _cohort_mean(hof_pure_names, lambda s: float(s["live"]["winnable"]["winnable_rate"]["mean"])),
            "mean_live_worked_4inv": _cohort_mean(hof_pure_names, lambda s: float(s["live"]["composite"]["mean_worked_rate_4inv"]["mean"])),
            "mean_live_frontier_worked": _cohort_mean(hof_pure_names, lambda s: float(s["live"]["composite"]["frontier_proxy_worked_rate"]["mean"])),
            "mean_cf_worked_rate": _cohort_mean(hof_pure_names, lambda s: float(s["counterfactual"]["cf_worked_rate"]["mean"])),
        },
    }

    all_passed = all(v["gates"]["passed_all"] for v in strategies_out.values())
    all_invariants = all(v["gates"]["anti_unfairness_invariant_ok"] for v in strategies_out.values())
    total_live_suppressed = sum(
        int(v["live"]["composite"]["total_suppressed_unwinnable_credits"])
        for v in strategies_out.values()
    )
    total_cf_suppressed = sum(
        int(v["counterfactual"]["n_suppressed_unwinnable"])
        for v in strategies_out.values()
    )
    cf_unwinnable_seeds = sorted(
        s for s, row in solver_cf_by_seed.items() if not (row["correct"] and float(row["score"]) > 0.0)
    )

    seed_range_str = (
        f"{live_seed_list[0]}-{live_seed_list[-1]}"
        if live_seed_list == list(range(live_seed_list[0], live_seed_list[-1] + 1))
        else ",".join(str(s) for s in live_seed_list)
    )

    report = {
        "schema_version": "worked_predicate_v14.1",
        "tiers_version": "v1.4",
        "api_calls": 0,
        "sleeper_port": {
            "winnable_source": "atk-regret-winnable",
            "worked_source": "atk-regret-worked",
            "live_regret_threshold": float(regret_threshold),
            "cf_ev_drop_threshold": float(cf_ev_drop_threshold),
            "min_solver_acc": float(min_solver_acc),
            "min_solver_ratio": float(min_solver_ratio),
            "max_logs_only_acc": float(max_logs_only_acc),
        },
        "tier": str(tier),
        "seed_range": seed_range_str,
        "n_live_seeds": len(live_seed_list),
        "live_seeds": live_seed_list,
        "cf_sources": list(cf_source_tuple),
        "n_cf_seeds_per_source": len(paired_cf_seeds),
        "cf_seeds": paired_cf_seeds,
        "n_cf_transcripts": len(paired_cf_seeds) * len(cf_source_tuple),
        "cf_solver_unwinnable_seeds": cf_unwinnable_seeds,
        "bootstrap": {
            "n_samples": int(n_boot),
            "seed": int(bootstrap_seed),
            "ci": 0.95,
        },
        "investigators": list(INVESTIGATOR_ORDER),
        "strategy_order": selected_names,
        "n_strategies_evaluated": len(selected_names),
        "n_unique_canonical_strategies": len(canon_to_json),
        "summary_gates": {
            "all_strategies_passed": bool(all_passed),
            "anti_unfairness_invariant_all_ok": bool(all_invariants),
            "min_solver_acc_observed": round(
                min(float(v["live"]["winnable"]["solver_acc"]) for v in strategies_out.values()), 6
            ),
            "max_logs_only_acc_observed": round(
                max(float(v["live"]["winnable"]["logs_only_acc"]) for v in strategies_out.values()), 6
            ),
            "total_live_suppressed_unwinnable_credits": int(total_live_suppressed),
            "total_cf_suppressed_unwinnable_credits": int(total_cf_suppressed),
        },
        "cohort_comparison": cohort_comparison,
        "strategies": strategies_out,
    }

    bad_key = _find_forbidden_key(report)
    if bad_key is not None:
        raise AssertionError(f"forbidden secret key {bad_key!r} leaked in study report")
    return report


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


def _contains_employee_id_token(obj: Any) -> str | None:
    if isinstance(obj, str):
        m = _EMP_ID_TOKEN_RE.search(obj)
        return m.group(0) if m is not None else None
    if isinstance(obj, dict):
        for k, v in obj.items():
            hit_k = _contains_employee_id_token(str(k))
            if hit_k is not None:
                return hit_k
            hit_v = _contains_employee_id_token(v)
            if hit_v is not None:
                return hit_v
    elif isinstance(obj, list):
        for item in obj:
            hit = _contains_employee_id_token(item)
            if hit is not None:
                return hit
    return None


def dumps_compact_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _fmt_ci(ci_obj: dict[str, Any], signed: bool = False) -> str:
    m = float(ci_obj["mean"])
    lo = float(ci_obj["ci_low"])
    hi = float(ci_obj["ci_high"])
    if signed:
        return f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]"
    return f"{m:.3f} [{lo:.3f}, {hi:.3f}]"


def format_worked_summary(report: dict[str, Any]) -> str:
    lines = [
        f"Sleeper Worked/Winnable Predicate Study (tier={report['tier']}, live_seeds={report['seed_range']} n={report['n_live_seeds']}, cf_transcripts={report['n_cf_transcripts']})",
        f"Gates: all_passed={report['summary_gates']['all_strategies_passed']}, anti_unfairness_ok={report['summary_gates']['anti_unfairness_invariant_all_ok']}, "
        f"live_suppressed={report['summary_gates']['total_live_suppressed_unwinnable_credits']}, cf_suppressed={report['summary_gates']['total_cf_suppressed_unwinnable_credits']}",
    ]
    for sname in report["strategy_order"]:
        st = report["strategies"][sname]
        win_r = float(st["live"]["winnable"]["winnable_rate"]["mean"])
        m4 = float(st["live"]["composite"]["mean_worked_rate_4inv"]["mean"])
        fp2 = float(st["live"]["composite"]["frontier_proxy_worked_rate"]["mean"])
        cf_r = float(st["counterfactual"]["cf_worked_rate"]["mean"])
        lines.append(
            f"  {sname:28s} cohort={st['cohort']:20s} winnable={win_r:.3f} live_4inv={m4:.3f} live_2proxy={fp2:.3f} cf_worked={cf_r:.3f}"
        )
    return "\n".join(lines)


def format_worked_markdown_report(report: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3

    sg = report["summary_gates"]
    sp = report["sleeper_port"]
    boot = report["bootstrap"]
    strats = report["strategies"]
    order = report["strategy_order"]
    cc = report["cohort_comparison"]

    cf_unwin_seeds = list(report["cf_solver_unwinnable_seeds"])
    cf_unwin = ", ".join(str(s) for s in cf_unwin_seeds) if cf_unwin_seeds else "none"
    cf_seeds_list = list(report["cf_seeds"])
    cf_seed_span = (
        f"{cf_seeds_list[0]}-{cf_seeds_list[-1]}"
        if len(cf_seeds_list) > 1 and cf_seeds_list == list(range(cf_seeds_list[0], cf_seeds_list[-1] + 1))
        else ",".join(str(s) for s in cf_seeds_list)
    )
    n_cf_seeds = int(report["n_cf_seeds_per_source"])
    n_cf_solved_seeds = n_cf_seeds - len(cf_unwin_seeds)
    def_cf = strats[order[0]]["counterfactual"]
    n_cf_total = int(def_cf["n_transcripts"])
    n_cf_win = int(def_cf["n_solver_winnable"])
    n_cf_be = int(def_cf["n_base_above_breakeven_winnable"])
    n_oc = int(def_cf["by_source"].get("opencode", {}).get("n_transcripts", 0))
    n_ip = int(def_cf["by_source"].get("inproc", {}).get("n_transcripts", 0))

    n_tg = len(cc["transcript_grounded_6"]["strategies"])
    n_hof = len(cc["hof_v14_all_4"]["strategies"])
    dup_pairs = [
        f"`{sname}` == `{strats[sname]['canonical_duplicate_of']}`"
        for sname in order
        if strats[sname]["canonical_duplicate_of"] is not None
    ]
    dup_note = f" because {' and '.join(dup_pairs)}" if dup_pairs else ""
    min_sol_acc = float(sp.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC))
    max_lo_acc = float(sp.get("max_logs_only_acc", DEFAULT_MAX_LOGS_ONLY_ACC))
    tier_cap = str(report["tier"]).capitalize()

    lines: list[str] = [
        f"{h1} Sleeper Winnable and Worked Predicate Port for Canary v1.4 Mole Strategies",
        "",
        f"Generated strictly offline (`api_calls={report.get('api_calls', 0)}`) via `python -m canary.mole.worked_predicate --tier {report['tier']} --seeds {report['seed_range']} --workers 2`.",
        "",
        f"{h2} 1. Predicate Definitions and Anti-Unfairness Invariant",
        "",
        f"This report ports Sleeper's per-seed `{sp['winnable_source']}` and `{sp['worked_source']}` predicates to Canary v1.4 `{report['tier']}` "
        "so mole strategy difficulty is never credited on unwinnable or shortcut-solvable seeds:",
        "",
        "- **Live `winnable(tier, seed, strategy)`**: `True` iff `SolverPolicy(tier)` accuses the true mole cleanly (`correct == True` and `score > 0.0`) "
        "AND all three anti-shortcut baselines fail (`DoNothing == 0.0`, `StopEarlyQuit == 0.0` both finished and mid-episode, and `LogsOnly` is incorrect).",
        "- **Live `worked(tier, seed, strategy, investigator)`**: `True` iff `winnable == True` AND the target investigator "
        "(`GeminiCarbonProxy`, `CodexHorizonProxy`, `GrokTactics`, `HintedHeuristic`) either fails (`correct == False`) "
        f"or suffers paired regret `solver_score - inv_score >= {sp['live_regret_threshold']:.2f}`.",
        f"- **Counterfactual `cf_worked(strategy, source, seed)`**: Over the `{n_cf_total}` committed v1.4 `gemini-4-carbon` {tier_cap} transcripts "
        f"(`{', '.join(report['cf_sources'])}` on seeds `{cf_seed_span}`) paired with the `{n_cf_seeds}` committed "
        f"`data/runs/committed/v1.4/reference/solver-{report['tier']}` episodes, `cf_worked == True` iff committed `solver` solved `seed` (`correct == True`, `score > 0`) "
        f"AND replacing `default_v0` with `strategy` drops counterfactual `P(true mole)` at Gemini's accusation day from `>= 1 / (1 + V_accuse)` below break-even "
        f"`1 / (1 + V_accuse)` (or drops `optimal_ev` by `>= {sp['cf_ev_drop_threshold']:.2f}` from a break-even-justified `default_v0` baseline).",
        "- **Hard Anti-Unfairness Invariant**: Whenever `winnable == False` (or `cf_winnable == False`), `worked` (`cf_worked`) is strictly `False`, even if the target investigator failed.",
        "",
        f"{h2} 2. Evaluation Design and Gate Summary",
        "",
        f"- **Disjoint live seed slice**: `{report['tier']}` seeds `{report['seed_range']}` (`n={report['n_live_seeds']}`, strict hygiene guard rejecting `0-59`, `30000-30199`, `800000+`, `900000+`, `{report.get('api_calls', 0)}` live API calls).",
        f"- **Bootstrap protocol**: `{boot['n_samples']}` paired resamples (`seed={boot['seed']}`, `{int(round(100 * boot['ci']))}%` percentile CIs).",
        f"- **Candidate set**: `{report['n_strategies_evaluated']}` entries (`default_v0` + `{n_tg}` transcript-grounded strategies from `canary.mole.strategies` + `{n_hof}` `data/forge/hall_of_fame_v1.4.jsonl` rows; `{report['n_unique_canonical_strategies']}` distinct canonical DSL strategies{dup_note}).",
        f"- **Gates**: `all_strategies_passed={sg['all_strategies_passed']}`, `anti_unfairness_invariant_all_ok={sg['anti_unfairness_invariant_all_ok']}`, "
        f"`min_solver_acc={sg['min_solver_acc_observed']:.3f}` (`>= {min_sol_acc:.3f}`), `max_logs_only_acc={sg['max_logs_only_acc_observed']:.3f}` (`<= {max_lo_acc:.3f}`).",
        f"- **Unwinnable-credit suppression**: `{sg['total_live_suppressed_unwinnable_credits']}` naive investigator-beaten cells suppressed on live seeds `{report['seed_range']}`, "
        f"and `{sg['total_cf_suppressed_unwinnable_credits']}` counterfactual transcript credits suppressed on committed solver-failed seed(s) (`{cf_unwin}`).",
        "",
        f"{h2} 3. Live Winnable and Composite Worked Rates (`n={report['n_live_seeds']}` Disjoint {tier_cap} Seeds)",
        "",
        "| Strategy | Cohort | Winnable Rate [95% CI] | Solver Acc (Mean Score) | LogsOnly Acc | 4-Inv Worked Rate [95% CI] | 4-Inv Worked Delta vs Default [95% CI] | Frontier 2-Proxy Worked [95% CI] | All-4 Worked | Suppressed Credits | Gates |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for sname in order:
        st = strats[sname]
        win = st["live"]["winnable"]
        comp = st["live"]["composite"]
        gate_str = "PASS" if st["gates"]["passed_all"] else "FAIL"
        cohort_label = st["cohort"] if st["canonical_duplicate_of"] is None else f"{st['cohort']} (={st['canonical_duplicate_of']})"
        lines.append(
            f"| `{sname}` | `{cohort_label}` | "
            f"{_fmt_ci(win['winnable_rate'])} | "
            f"{win['solver_acc']:.3f} ({win['solver_score']['mean']:+.3f}) | "
            f"{win['logs_only_acc']:.3f} | "
            f"{_fmt_ci(comp['mean_worked_rate_4inv'])} | "
            f"{_fmt_ci(comp['mean_worked_rate_4inv_delta_vs_default'], signed=True)} | "
            f"{_fmt_ci(comp['frontier_proxy_worked_rate'])} | "
            f"{comp['all_4_investigators_worked_rate']['mean']:.3f} | "
            f"{comp['total_suppressed_unwinnable_credits']} | "
            f"{gate_str} |"
        )

    lines.extend([
        "",
        f"{h2} 4. Per-Investigator Live Worked Rates and Paired Deltas vs `default_v0`",
        "",
        "| Strategy | GeminiCarbonProxy Worked (Delta) | CodexHorizonProxy Worked (Delta) | GrokTactics Worked (Delta) | HintedHeuristic Worked (Delta) | Minimax 4-Inv Worked | Hardest Investigator |",
        "|---|---|---|---|---|---|---|",
    ])

    for sname in order:
        st = strats[sname]
        pinv = st["live"]["per_investigator"]
        comp = st["live"]["composite"]
        cells: list[str] = []
        for ik in INVESTIGATOR_ORDER:
            w_m = float(pinv[ik]["worked_rate"]["mean"])
            d_m = float(pinv[ik]["worked_rate_delta_vs_default"]["mean"])
            cells.append(f"{w_m:.3f} ({d_m:+.3f})")
        lines.append(
            f"| `{sname}` | {cells[0]} | {cells[1]} | {cells[2]} | {cells[3]} | "
            f"{comp['minimax_worked_rate_across_4inv']:.3f} | `{comp['hardest_investigator_for_mole']}` |"
        )

    lines.extend([
        "",
        f"{h3} 4.1 Failure vs Regret-Only Decomposition and Unwinnable Credit Suppression",
        "",
        "Each `worked == True` event decomposes into investigator wrong/abstained accusation (`correct == False`) versus accurate but high-cost catch "
        f"(`correct == True` with `solver_score - inv_score >= {sp['live_regret_threshold']:.2f}`). Naive `raw_beaten - worked` equals suppressed unwinnable credits.",
        "",
        f"| Strategy | Investigator | Raw Beaten | Worked (`winnable & beaten`) | Suppressed (`!winnable & beaten`) | Worked via `correct==False` | Worked via `regret>={sp['live_regret_threshold']:.2f}` Only | Mean Paired Regret [95% CI] |",
        "|---|---|---|---|---|---|---|---|",
    ])

    for sname in order:
        st = strats[sname]
        pinv = st["live"]["per_investigator"]
        for ik in INVESTIGATOR_ORDER:
            row = pinv[ik]
            lines.append(
                f"| `{sname}` | `{row['label']}` | "
                f"{row['n_raw_beaten']}/{row['n_seeds']} ({row['raw_beaten_rate']:.3f}) | "
                f"{row['n_worked']}/{row['n_seeds']} ({row['worked_rate']['mean']:.3f}) | "
                f"{row['n_suppressed_unwinnable']} | "
                f"{row['n_worked_by_failure']} | "
                f"{row['n_worked_by_regret_only']} | "
                f"{_fmt_ci(row['paired_regret'], signed=True)} |"
            )

    lines.extend([
        "",
        f"{h2} 5. Counterfactual Worked Predicate on `{n_cf_total}` Committed v1.4 `gemini-4-carbon` {tier_cap} Transcripts",
        "",
        f"Across the `{n_cf_total}` committed v1.4 {tier_cap} transcripts (`{' + '.join(report['cf_sources'])}` seeds `{cf_seed_span}`), committed `SolverPolicy` solved "
        f"`{n_cf_solved_seeds}/{n_cf_seeds}` seeds (`{n_cf_win}/{n_cf_total}` transcripts `cf_winnable == True`; failed seed(s) `{cf_unwin}` in committed `solver-{report['tier']}` are gated to `cf_worked = False` across harnesses).",
        "",
        f"| Strategy | CF Worked (`n/{n_cf_total}`) [95% CI] | CF Worked Given Winnable (`n/{n_cf_win}`) | CF Worked Given Base >= Break-Even (`n/{n_cf_be}`) | OpenCode (`n/{n_oc}`) | In-Proc (`n/{n_ip}`) | Dropped `< P*(V)` | Dropped `EV >= {sp['cf_ev_drop_threshold']:.2f}` | Suppressed (`!cf_winnable`) | Mean `P(mole)` Drop [95% CI] | Mean `optimal_ev` Drop [95% CI] |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ])

    for sname in order:
        cf = strats[sname]["counterfactual"]
        oc = cf["by_source"].get("opencode", {})
        ip = cf["by_source"].get("inproc", {})
        oc_str = f"{oc.get('n_cf_worked', 0)}/{oc.get('n_transcripts', 0)} ({oc.get('cf_worked_rate', 0.0):.3f})" if oc else "n/a"
        ip_str = f"{ip.get('n_cf_worked', 0)}/{ip.get('n_transcripts', 0)} ({ip.get('cf_worked_rate', 0.0):.3f})" if ip else "n/a"
        lines.append(
            f"| `{sname}` | "
            f"{cf['n_cf_worked']}/{cf['n_transcripts']} {_fmt_ci(cf['cf_worked_rate'])} | "
            f"{cf['n_cf_worked']}/{cf['n_solver_winnable']} ({cf['cf_worked_rate_given_winnable']['mean']:.3f}) | "
            f"{cf['cf_worked_rate_given_base_breakeven']:.3f} | "
            f"{oc_str} | {ip_str} | "
            f"{cf['n_dropped_below_breakeven']} | "
            f"{cf['n_dropped_ev_ge_threshold']} | "
            f"{cf['n_suppressed_unwinnable']} | "
            f"{_fmt_ci(cf['p_true_mole_drop'], signed=True)} | "
            f"{_fmt_ci(cf['optimal_ev_drop'], signed=True)} |"
        )

    tg_c = cc["transcript_grounded_6"]
    hof_all_c = cc["hof_v14_all_4"]
    hof_pure_c = cc["hof_v14_pure_forge_2"]

    lines.extend([
        "",
        f"{h2} 6. Cohort Comparison: Transcript-Grounded vs Forge Hall-of-Fame v1.4",
        "",
        f"| Cohort | Strategies | Mean Live Winnable Rate | Mean 4-Inv Live Worked Rate | Mean Frontier 2-Proxy Live Worked Rate | Mean Counterfactual `cf_worked` Rate (`n={n_cf_total}` Gemini-4-Carbon {tier_cap} Transcripts) |",
        "|---|---|---|---|---|---|",
        f"| `transcript_grounded_6` | `{', '.join(tg_c['strategies']) if tg_c['strategies'] else 'none'}` | {tg_c['mean_winnable_rate']:.3f} | {tg_c['mean_live_worked_4inv']:.3f} | {tg_c['mean_live_frontier_worked']:.3f} | {tg_c['mean_cf_worked_rate']:.3f} |",
        f"| `hof_v14_all_4` | `{', '.join(hof_all_c['strategies']) if hof_all_c['strategies'] else 'none'}` | {hof_all_c['mean_winnable_rate']:.3f} | {hof_all_c['mean_live_worked_4inv']:.3f} | {hof_all_c['mean_live_frontier_worked']:.3f} | {hof_all_c['mean_cf_worked_rate']:.3f} |",
        f"| `hof_v14_pure_forge_2` | `{', '.join(hof_pure_c['strategies']) if hof_pure_c['strategies'] else 'none'}` | {hof_pure_c['mean_winnable_rate']:.3f} | {hof_pure_c['mean_live_worked_4inv']:.3f} | {hof_pure_c['mean_live_frontier_worked']:.3f} | {hof_pure_c['mean_cf_worked_rate']:.3f} |",
        "",
        f"{h2} 7. Provenance Hashes and Unwinnable Seed Audit",
        "",
        f"| Strategy | Rules | Hof Alias | Canonical SHA-256 | Behavior Hash | Live Unwinnable Seeds (`{report['seed_range']}`) |",
        "|---|---|---|---|---|---|",
    ])

    for sname in order:
        st = strats[sname]
        alias_str = f"`{st['hof_alias']}`" if st["hof_alias"] else "none"
        unwin_list = st["live"]["winnable"]["unwinnable_seeds"]
        unwin_str = (
            ", ".join(f"{u['seed']}({'+'.join(u['reasons'])})" for u in unwin_list)
            if unwin_list
            else "none"
        )
        lines.append(
            f"| `{sname}` | {st['n_rules']} | {alias_str} | `{st['canonical_sha256']}` | `{st['behavior_hash']}` | `{unwin_str}` |"
        )

    return "\n".join(lines) + "\n"


def check_worked_predicate_artifacts(
    json_path: Path = DEFAULT_OUTPUT_PATH,
    md_path: Path = DEFAULT_REPORT_MD_PATH,
) -> tuple[bool, str]:
    if not json_path.is_file():
        return False, f"FAIL: missing JSON artifact: {json_path}"
    if not md_path.is_file():
        return False, f"FAIL: missing Markdown report: {md_path}"

    raw_bytes = json_path.read_bytes()
    if len(raw_bytes) >= MAX_JSON_BYTES:
        return False, f"FAIL: JSON size {len(raw_bytes)} bytes exceeds {MAX_JSON_BYTES} byte limit"

    json_text = raw_bytes.decode("utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    coauthor_tag = "co-authored-" + "by"

    for p, txt in ((json_path, json_text), (md_path, md_text)):
        if chr(0x2014) in txt or chr(0x2013) in txt or chr(0x2212) in txt:
            return False, f"FAIL: forbidden em/en dash found in {p}"
        if not txt.isascii():
            return False, f"FAIL: non-ASCII character found in {p}"
        low = txt.lower()
        if flash_tag in low or solver_pct_tag in low or _FORBIDDEN_GAP_RE.search(txt) is not None:
            return False, f"FAIL: forbidden gap ratio claim ({flash_tag} or {solver_pct_tag}) in {p}"
        if coauthor_tag in low:
            return False, f"FAIL: forbidden trailer ({coauthor_tag}) in {p}"

    try:
        report = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return False, f"FAIL: invalid JSON in {json_path}: {exc}"
    if not isinstance(report, dict):
        return False, f"FAIL: expected JSON object in {json_path}"

    if dumps_compact_json(report) + "\n" != json_text:
        return False, f"FAIL: JSON file {json_path} is not in canonical compact format"

    bad_key = _find_forbidden_key(report)
    if bad_key is not None:
        return False, f"FAIL: forbidden secret key {bad_key!r} leaked in {json_path}"

    emp_tok = _contains_employee_id_token(report)
    if emp_tok is not None:
        return False, f"FAIL: potential employee/mole ID token {emp_tok!r} leaked in {json_path}"

    try:
        seeds = validate_eval_seeds(report.get("live_seeds", []), enforce_hygiene=True)
    except ValueError as exc:
        return False, f"FAIL: seed hygiene violation in {json_path}: {exc}"
    if len(seeds) != int(report.get("n_live_seeds", -1)):
        return False, f"FAIL: n_live_seeds mismatch ({len(seeds)} != {report.get('n_live_seeds')})"

    sg = report.get("summary_gates", {})
    if sg.get("all_strategies_passed") is not True:
        return False, "FAIL: summary_gates.all_strategies_passed is not True"
    if sg.get("anti_unfairness_invariant_all_ok") is not True:
        return False, "FAIL: summary_gates.anti_unfairness_invariant_all_ok is not True"

    for sname, st in report.get("strategies", {}).items():
        unwin_set = {int(u["seed"]) for u in st["live"]["winnable"]["unwinnable_seeds"]}
        for ik, irow in st["live"]["per_investigator"].items():
            overlap = unwin_set.intersection(int(s) for s in irow.get("worked_seeds", []))
            if overlap:
                return False, f"FAIL: anti-unfairness invariant violated in {sname}/{ik} on seeds {sorted(overlap)}"
        cf_unwin = set(int(s) for s in report.get("cf_solver_unwinnable_seeds", []))
        for key_str in st["counterfactual"].get("cf_worked_keys", []):
            _, seed_part = str(key_str).split(":", 1)
            if int(seed_part) in cf_unwin:
                return False, f"FAIL: counterfactual anti-unfairness violated in {sname} on {key_str}"

    expected_md = format_worked_markdown_report(report)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {md_path} does not match JSON ledger {json_path}"

    return (
        True,
        f"OK: {json_path.name} ({len(raw_bytes)} bytes < {MAX_JSON_BYTES}, n={len(seeds)} live seeds, "
        f"{report['n_cf_transcripts']} CF transcripts, {report['n_strategies_evaluated']} strategies) matches {md_path.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.worked_predicate")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="6240-6279")
    ap.add_argument("--cf-seeds", default="0-29")
    ap.add_argument("--cf-sources", default="opencode,inproc")
    ap.add_argument("--strategies", default=None)
    ap.add_argument("--hof-path", type=Path, default=DEFAULT_HOF_V14_PATH)
    ap.add_argument("--regret-threshold", type=float, default=DEFAULT_REGRET_THRESHOLD)
    ap.add_argument("--cf-ev-drop-threshold", type=float, default=DEFAULT_CF_EV_DROP_THRESHOLD)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--max-logs-only-acc", type=float, default=DEFAULT_MAX_LOGS_ONLY_ACC)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--n-boot", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    ap.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--cache-jsonl", type=Path, default=None)
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report-md", "--report-out", dest="report_md", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.check:
        j_path = args.out if args.out is not None else DEFAULT_OUTPUT_PATH
        m_path = args.report_md if args.report_md is not None else DEFAULT_REPORT_MD_PATH
        ok, msg = check_worked_predicate_artifacts(json_path=j_path, md_path=m_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    strat_names = [x.strip() for x in args.strategies.split(",") if x.strip()] if args.strategies else None
    cf_sources = tuple(x.strip() for x in args.cf_sources.split(",") if x.strip())

    report = evaluate_worked_predicate_study(
        tier=args.tier,
        seeds=args.seeds,
        cf_seeds=args.cf_seeds,
        cf_sources=cf_sources,
        strategy_names=strat_names,
        hof_path=args.hof_path,
        regret_threshold=args.regret_threshold,
        cf_ev_drop_threshold=args.cf_ev_drop_threshold,
        min_solver_acc=args.min_solver_acc,
        min_solver_ratio=args.min_solver_ratio,
        max_logs_only_acc=args.max_logs_only_acc,
        workers=args.workers,
        n_boot=args.n_boot,
        bootstrap_seed=args.bootstrap_seed,
        enforce_seed_hygiene=True,
        progress=args.progress,
        cache_jsonl=args.cache_jsonl,
    )

    j_path = args.out if args.out is not None else DEFAULT_OUTPUT_PATH
    m_path = args.report_md if args.report_md is not None else DEFAULT_REPORT_MD_PATH

    json_payload = dumps_compact_json(report)
    j_path.parent.mkdir(parents=True, exist_ok=True)
    j_path.write_text(json_payload + "\n", encoding="utf-8")

    m_path.parent.mkdir(parents=True, exist_ok=True)
    m_path.write_text(format_worked_markdown_report(report), encoding="utf-8")

    ok, msg = check_worked_predicate_artifacts(json_path=j_path, md_path=m_path)
    if not ok:
        print(msg, file=sys.stderr)
        return 1

    if args.json:
        print(json_payload)
    else:
        print(format_worked_summary(report))
        print(msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
