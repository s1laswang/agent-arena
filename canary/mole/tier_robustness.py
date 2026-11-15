"""Cross-tier catchability, anti-shortcut fairness, and investigator regret evaluation across medium and hard tiers."""
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

from canary.baselines import (
    AccuseMostLogs,
    DoNothing,
    GrokTactics,
    LogsOnly,
    StopEarlyQuit,
)
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.counterfactual import evaluate_counterfactual
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import STRATEGY_SPECS
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params
from canary.solver.policy import SolverPolicy

__all__ = [
    "CLASSIFICATION_VALUES",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_CF_SEEDS",
    "DEFAULT_CF_SOURCES",
    "DEFAULT_HOF_META_PATH",
    "DEFAULT_HOF_PATH",
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_REPORT_MD_PATH",
    "DEFAULT_ROBUSTNESS_SEEDS",
    "DEFAULT_TIERS",
    "FORBIDDEN_HIGH_SEED_MIN",
    "FORBIDDEN_LOW_SEED_MAX",
    "FRONTIER_PROXY_NAMES",
    "INVESTIGATOR_NAMES",
    "MAX_JSON_BYTES",
    "POLICY_NAMES",
    "RESERVED_HELDOUT_SEED_RANGE",
    "TierStrategySpec",
    "check_tier_robustness_artifacts",
    "classify_tier_status",
    "dumps_tier_robustness_json",
    "evaluate_tier_gates",
    "failed_gate_names",
    "format_tier_robustness_markdown",
    "format_tier_robustness_summary",
    "get_tier_strategy_spec",
    "list_tier_strategy_names",
    "load_tier_strategy_specs",
    "main",
    "normalize_robustness_seeds",
    "paired_bootstrap_ci",
    "resolve_tier_strategy_name",
    "run_tier_robustness_study",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HOF_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
DEFAULT_HOF_META_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.meta.json"
DEFAULT_OUTPUT_PATH = ROOT / "results" / "mole_strategies" / "tier_robustness_v14.json"
DEFAULT_REPORT_MD_PATH = ROOT / "docs" / "reports" / "mole_tier_robustness_v14.md"

DEFAULT_ROBUSTNESS_SEEDS: tuple[int, ...] = tuple(range(6300, 6340))
DEFAULT_TIERS: tuple[str, ...] = ("medium", "hard")
DEFAULT_CF_SEEDS: tuple[int, ...] = tuple(range(30))
DEFAULT_CF_SOURCES: tuple[str, ...] = ("opencode", "inproc")

FORBIDDEN_LOW_SEED_MAX = 59
RESERVED_HELDOUT_SEED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MIN_SOLVER_RATIO = 0.50
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_BOOTSTRAP_SAMPLES = 5000
DEFAULT_BOOTSTRAP_SEED = 20261114
MAX_JSON_BYTES = 95_000

CLASSIFICATION_VALUES: tuple[str, ...] = (
    "DUAL_TIER_PASS",
    "HARD_ONLY_PASS",
    "FAIL",
)

POLICY_NAMES: tuple[str, ...] = (
    "solver",
    "logs_only",
    "accuse_most_logs",
    "do_nothing",
    "stop_early_quit",
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
)

INVESTIGATOR_NAMES: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
)

FRONTIER_PROXY_NAMES: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
)

_GATE_KEYS: tuple[str, ...] = (
    "dsl_valid",
    "solver_acc_ge_min",
    "solver_ratio_ge_min",
    "logs_only_le_max",
    "accuse_most_logs_le_max",
    "do_nothing_zero",
    "stop_early_quit_zero",
)

_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "mole",
    "true_mole",
    "mole_id",
    "canary_ids",
    "secret_mole",
    "decoy_id",
})


@dataclass(frozen=True)
class TierStrategySpec:
    name: str
    source: str
    group: str
    hof_rank: int | None
    hof_survivor_name: str | None
    canonical_equivalent_of: str | None
    canonical_sha256: str
    strategy_json: dict[str, Any]

    def to_strategy(self) -> MoleStrategy:
        return MoleStrategy.from_json(self.strategy_json)

    def to_json(self) -> dict[str, Any]:
        return copy.deepcopy(self.strategy_json)


def _canonical_body_sha(sj: dict[str, Any]) -> str:
    c_str = canonical({"rules": sj.get("rules", []), "default": sj.get("default", {})})
    return hashlib.sha256(c_str.encode("utf-8")).hexdigest()[:16]


def _inspect_rule_mechanics(sj: dict[str, Any]) -> dict[str, Any]:
    rules = sj.get("rules", [])
    max_day = 0
    uses_d5_d8_pacing = False
    uses_age0_oldest = False
    for rule in rules:
        conds = rule.get("if", [])
        then = rule.get("then", {})
        day_vals = [int(round(float(c[2]))) for c in conds if len(c) == 3 and c[0] == "day"]
        if day_vals:
            max_day = max(max_day, max(day_vals))
        has_dsll = any(len(c) == 3 and c[0] == "days_since_last_leak" for c in conds)
        has_mid_day = any(5 <= v <= 8 for v in day_vals)
        if then.get("leak") == "none" and has_dsll and has_mid_day:
            uses_d5_d8_pacing = True
        has_age0 = any(
            len(c) == 3 and c[0] == "newest_doc_age_days" and c[1] == "==" and float(c[2]) == 0.0
            for c in conds
        )
        if has_age0 and then.get("leak") == "oldest":
            uses_age0_oldest = True
    default_leak_none = sj.get("default", {}).get("leak") == "none"
    return {
        "n_rules": len(rules),
        "max_day_threshold": max_day,
        "has_day_gt_medium_horizon": bool(max_day > 14),
        "uses_d5_d8_quiet_pacing": uses_d5_d8_pacing,
        "uses_age0_oldest_evasion": uses_age0_oldest,
        "uses_default_leak_none": bool(default_leak_none),
    }


def load_tier_strategy_specs(
    hof_path: Path = DEFAULT_HOF_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
) -> dict[str, TierStrategySpec]:
    specs: list[TierStrategySpec] = []
    seen_by_sha: dict[str, str] = {}

    def _register(
        name: str,
        source: str,
        group: str,
        sj_raw: dict[str, Any],
        hof_rank: int | None = None,
        hof_survivor_name: str | None = None,
    ) -> None:
        sj = copy.deepcopy(sj_raw)
        sj["name"] = name
        sha = _canonical_body_sha(sj)
        equiv = seen_by_sha.get(sha)
        if equiv is None:
            seen_by_sha[sha] = name
        specs.append(
            TierStrategySpec(
                name=name,
                source=source,
                group=group,
                hof_rank=hof_rank,
                hof_survivor_name=hof_survivor_name,
                canonical_equivalent_of=equiv,
                canonical_sha256=sha,
                strategy_json=sj,
            )
        )

    _register(
        name=DEFAULT_STRATEGY.name,
        source="canary/mole/strategies.py",
        group="baseline",
        sj_raw=DEFAULT_STRATEGY.to_json(),
    )
    for tname, tspec in STRATEGY_SPECS.items():
        _register(
            name=tname,
            source="canary/mole/strategies.py",
            group="transcript_strategy",
            sj_raw=tspec.to_json(),
        )

    if not hof_path.is_file():
        raise FileNotFoundError(f"missing Hall of Fame file: {hof_path}")
    hof_lines = [ln for ln in hof_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    survivor_names: list[str] = []
    if hof_meta_path.is_file():
        meta = json.loads(hof_meta_path.read_text(encoding="utf-8"))
        raw_names = meta.get("survivor_names")
        if isinstance(raw_names, list):
            survivor_names = [str(x) for x in raw_names]

    for idx, line in enumerate(hof_lines):
        row = json.loads(line)
        rank = int(row.get("rank", idx + 1))
        sj_row = row.get("strategy_json", row.get("strategy", row))
        surv = survivor_names[idx] if idx < len(survivor_names) else f"survivor_{rank}"
        hname = f"hof_r{rank}_{surv}"
        _register(
            name=hname,
            source="data/forge/hall_of_fame_v1.4.jsonl",
            group="hall_of_fame_v1.4",
            sj_raw=sj_row,
            hof_rank=rank,
            hof_survivor_name=surv,
        )

    return {s.name: s for s in specs}


_STRATEGY_REGISTRY: dict[str, TierStrategySpec] | None = None


def _registry() -> dict[str, TierStrategySpec]:
    global _STRATEGY_REGISTRY
    if _STRATEGY_REGISTRY is None:
        _STRATEGY_REGISTRY = load_tier_strategy_specs()
    return _STRATEGY_REGISTRY


def list_tier_strategy_names() -> list[str]:
    return list(_registry().keys())


def resolve_tier_strategy_name(name: str) -> str:
    reg = _registry()
    clean = str(name).strip()
    if clean in reg:
        return clean
    if clean == "default":
        return DEFAULT_STRATEGY.name
    for spec in reg.values():
        if spec.hof_rank is not None:
            if clean in (f"hof_{spec.hof_rank}", f"hof_r{spec.hof_rank}"):
                return spec.name
            if spec.hof_survivor_name == clean and clean not in reg:
                return spec.name
    raise KeyError(f"unknown strategy {name!r}; expected one of {sorted(reg)}")


def get_tier_strategy_spec(name: str) -> TierStrategySpec:
    reg = _registry()
    resolved = resolve_tier_strategy_name(name)
    return reg[resolved]


def _parse_explicit_seed_spec(spec: str) -> list[int]:
    raw = str(spec).strip()
    if not raw:
        raise ValueError("seeds must not be empty")
    out: list[int] = []
    for part in raw.split(","):
        tok = part.strip()
        if not tok:
            raise ValueError(f"empty token in seed spec {spec!r}")
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi <= lo:
                raise ValueError(f"empty or reversed seed slice: {tok!r}")
            out.extend(range(lo, hi))
        elif "-" in tok and not tok.startswith("-"):
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"reversed seed range: {tok!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(tok))
    if not out:
        raise ValueError("seeds must not be empty")
    return out


def normalize_robustness_seeds(
    seeds: str | Iterable[int] = DEFAULT_ROBUSTNESS_SEEDS,
    enforce_hygiene: bool = True,
) -> list[int]:
    if isinstance(seeds, str):
        seed_list = _parse_explicit_seed_spec(seeds)
    else:
        raw_items = list(seeds)
        seed_list = []
        for item in raw_items:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(f"robustness seed must be int, got {item!r}")
            seed_list.append(int(item))
    if not seed_list:
        raise ValueError("robustness seeds must not be empty")
    if len(set(seed_list)) != len(seed_list):
        raise ValueError("robustness seeds must not contain duplicates")
    if enforce_hygiene:
        for s in seed_list:
            if s < 0 or s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(
                    f"seed {s} violates seed hygiene (0..{FORBIDDEN_LOW_SEED_MAX} and negatives forbidden)"
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
) -> dict[str, float]:
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot}")
    if not (0.0 < ci < 1.0):
        raise ValueError(f"ci must be in (0, 1), got {ci}")
    n = len(diffs)
    if n == 0:
        return {
            "mean": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
        }
    arr = np.asarray(diffs, dtype=np.float64)
    mean_val = float(arr.mean())
    if n == 1 or float(arr.min()) == float(arr.max()):
        r_val = round(mean_val, 4)
        return {
            "mean": r_val,
            "ci_low": r_val,
            "ci_high": r_val,
        }
    rng = np.random.default_rng(_derive_seed(seed, tag))
    idx = rng.integers(0, n, size=(int(n_boot), n))
    boot_means = arr[idx].mean(axis=1)
    alpha = 0.5 * (1.0 - float(ci))
    lo, hi = np.quantile(boot_means, [alpha, 1.0 - alpha])
    ci_low = float(lo)
    ci_high = float(hi)
    return {
        "mean": round(mean_val, 4),
        "ci_low": round(ci_low, 4),
        "ci_high": round(ci_high, 4),
    }


def evaluate_tier_gates(
    *,
    dsl_valid: bool,
    solver_acc: float,
    solver_score: float,
    baseline_solver_score: float,
    logs_only_acc: float,
    accuse_most_logs_acc: float,
    do_nothing_max_abs: float,
    stop_early_quit_max_abs: float,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
) -> dict[str, bool]:
    gates = {
        "dsl_valid": bool(dsl_valid),
        "solver_acc_ge_min": bool(float(solver_acc) + 1e-12 >= float(min_solver_acc)),
        "solver_ratio_ge_min": bool(
            float(solver_score) + 1e-12 >= float(min_solver_ratio) * float(baseline_solver_score)
        ),
        "logs_only_le_max": bool(float(logs_only_acc) <= float(max_logs_acc) + 1e-12),
        "accuse_most_logs_le_max": bool(float(accuse_most_logs_acc) <= float(max_logs_acc) + 1e-12),
        "do_nothing_zero": bool(abs(float(do_nothing_max_abs)) == 0.0),
        "stop_early_quit_zero": bool(abs(float(stop_early_quit_max_abs)) == 0.0),
    }
    gates["tier_passed"] = bool(all(gates[k] for k in _GATE_KEYS))
    return gates


def failed_gate_names(gates: dict[str, bool]) -> list[str]:
    return [k for k in _GATE_KEYS if not bool(gates.get(k, False))]


def classify_tier_status(medium_passed: bool, hard_passed: bool) -> str:
    if bool(medium_passed) and bool(hard_passed):
        return "DUAL_TIER_PASS"
    if bool(hard_passed) and not bool(medium_passed):
        return "HARD_ONLY_PASS"
    return "FAIL"


def _make_solver(tier: str) -> SolverPolicy:
    return SolverPolicy(tier if tier in TIERS else tier_params(tier), act_budget=5.0)


def _make_grok_tactics(tier: str, seed: int) -> GrokTactics:
    _ = tier_params(tier)
    return GrokTactics(seed=seed)


def _make_hinted_heuristic(tier: str, seed: int) -> HintedHeuristic:
    return HintedHeuristic(seed=seed, n_days=tier_params(tier).n_days)


def _unfinished_stop_early_score(tier: str, seed: int, strat: MoleStrategy) -> float:
    env = Env(tier, seed, mole_strategy=strat)
    pol = StopEarlyQuit(seed=seed)
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(3):
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    return float(env.score())


def _eval_canonical_seed_worker(task: tuple[str, str, int, dict[str, Any]]) -> dict[str, Any]:
    canon_sha, tier, seed, sj = task
    strat = MoleStrategy.from_json(sj)

    sol = run_episode(Env(tier, seed, mole_strategy=strat), _make_solver(tier))
    lo = run_episode(Env(tier, seed, mole_strategy=strat), LogsOnly(seed=seed))
    aml = run_episode(Env(tier, seed, mole_strategy=strat), AccuseMostLogs(seed=seed))

    env_dn = Env(tier, seed, mole_strategy=strat)
    dn = run_episode(env_dn, DoNothing(seed=seed))
    ledger_raw = env_dn.ledger()
    mole_leaks = sum(1 for entry in ledger_raw if str(entry.event) == "leak")
    mole_frames = sum(1 for entry in ledger_raw if str(entry.event) == "framed")
    ledger_events = [
        (int(entry.day), str(entry.event), entry.detail.get("doc_id"), entry.detail.get("employee"))
        for entry in ledger_raw
        if str(entry.event) in ("leak", "framed")
    ]

    seq = run_episode(Env(tier, seed, mole_strategy=strat), StopEarlyQuit(seed=seed))
    seq_unfinished = _unfinished_stop_early_score(tier, seed, strat)

    gem = run_episode(Env(tier, seed, mole_strategy=strat), GeminiCarbonProxy(seed=seed))
    cdx = run_episode(Env(tier, seed, mole_strategy=strat), CodexHorizonProxy(seed=seed))
    grk = run_episode(Env(tier, seed, mole_strategy=strat), _make_grok_tactics(tier, seed))
    hh = run_episode(Env(tier, seed, mole_strategy=strat), _make_hinted_heuristic(tier, seed))

    def _pack(res: Any) -> dict[str, Any]:
        return {
            "score": float(res.score),
            "correct": bool(res.correct),
            "final_day": int(res.final_day),
            "accused": res.accused is not None,
        }

    return {
        "canon_sha": canon_sha,
        "tier": tier,
        "seed": int(seed),
        "mole_leaks": int(mole_leaks),
        "mole_frames": int(mole_frames),
        "ledger_events": ledger_events,
        "policies": {
            "solver": _pack(sol),
            "logs_only": _pack(lo),
            "accuse_most_logs": _pack(aml),
            "do_nothing": _pack(dn),
            "stop_early_quit": {
                **_pack(seq),
                "unfinished_score": seq_unfinished,
            },
            "gemini_carbon_proxy": _pack(gem),
            "codex_horizon_proxy": _pack(cdx),
            "grok_tactics": _pack(grk),
            "hinted_heuristic": _pack(hh),
        },
    }


def _validate_dsl_for_tier(sj: dict[str, Any], tier: str) -> tuple[bool, bool]:
    try:
        parsed = MoleStrategy.from_json(sj)
        round_trip = MoleStrategy.from_json(json.loads(json.dumps(parsed.to_json())))
        if round_trip != parsed or len(parsed.rules) > MAX_RULES:
            return False, False
        validate_strategy({"rules": sj["rules"], "default": sj["default"]})
    except Exception:
        return False, False
    conds_in_range = all(is_valid_rule_conds(rule["if"], tier) for rule in sj.get("rules", []))
    return True, bool(conds_in_range)


def _summarize_policy_cell(
    canon_sha: str,
    tier: str,
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
    out: dict[str, Any] = {
        "score": round(sum(scores) / n, 4),
        "acc": round(sum(accs) / n, 4),
        "accused_rate": round(len(accused_days) / n, 4),
        "mean_accuse_day": round(sum(accused_days) / len(accused_days), 3) if accused_days else None,
    }
    if policy_name == "solver" or policy_name in INVESTIGATOR_NAMES:
        score_ci = paired_bootstrap_ci(
            scores,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"pol:{tier}:{canon_sha}:{policy_name}:score",
        )
        out["ci_low"] = score_ci["ci_low"]
        out["ci_high"] = score_ci["ci_high"]
    if policy_name in INVESTIGATOR_NAMES:
        regrets = [sol_s - sc for sol_s, sc in zip(solver_scores, scores)]
        out["regret_vs_solver"] = paired_bootstrap_ci(
            regrets,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"pol:{tier}:{canon_sha}:{policy_name}:regret",
        )
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


def _build_tier_cell(
    spec: TierStrategySpec,
    tier: str,
    rows: list[dict[str, Any]],
    base_rows: list[dict[str, Any]],
    cf_strat_row: dict[str, Any],
    cf_eps_cur: dict[tuple[str, int], dict[str, Any]],
    cf_eps_base: dict[tuple[str, int], dict[str, Any]],
    cf_sources: Sequence[str],
    n_boot: int,
    bootstrap_seed: int,
    min_solver_acc: float,
    min_solver_ratio: float,
    max_logs_acc: float,
) -> dict[str, Any]:
    sj = spec.strategy_json
    canon_sha = spec.canonical_sha256
    dsl_ok, conds_in_range = _validate_dsl_for_tier(sj, tier)

    sol_scores = [float(r["policies"]["solver"]["score"]) for r in rows]
    base_sol_scores = [float(r["policies"]["solver"]["score"]) for r in base_rows]
    sol_accs = [1.0 if r["policies"]["solver"]["correct"] else 0.0 for r in rows]
    base_sol_accs = [1.0 if r["policies"]["solver"]["correct"] else 0.0 for r in base_rows]

    baseline_solver_score = sum(base_sol_scores) / len(base_sol_scores)

    ledger_blob = json.dumps([r["ledger_events"] for r in rows], separators=(",", ":")).encode("utf-8")
    emp_ledger_hash = hashlib.sha256(ledger_blob).hexdigest()[:16]
    mean_mole_leaks = round(sum(float(r["mole_leaks"]) for r in rows) / len(rows), 4)
    mean_mole_frames = round(sum(float(r["mole_frames"]) for r in rows) / len(rows), 4)

    policies_summary = {
        pname: _summarize_policy_cell(
            canon_sha=canon_sha,
            tier=tier,
            policy_name=pname,
            seed_rows=rows,
            solver_scores=sol_scores,
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
        )
        for pname in POLICY_NAMES
    }

    def _inv_scores(rlist: list[dict[str, Any]], pname: str) -> list[float]:
        return [float(r["policies"][pname]["score"]) for r in rlist]

    gem_cur, gem_base = _inv_scores(rows, "gemini_carbon_proxy"), _inv_scores(base_rows, "gemini_carbon_proxy")
    cdx_cur, cdx_base = _inv_scores(rows, "codex_horizon_proxy"), _inv_scores(base_rows, "codex_horizon_proxy")
    grk_cur, grk_base = _inv_scores(rows, "grok_tactics"), _inv_scores(base_rows, "grok_tactics")
    hh_cur, hh_base = _inv_scores(rows, "hinted_heuristic"), _inv_scores(base_rows, "hinted_heuristic")

    freg_cur = [s - 0.5 * (g + c) for s, g, c in zip(sol_scores, gem_cur, cdx_cur)]
    freg_base = [s - 0.5 * (g + c) for s, g, c in zip(base_sol_scores, gem_base, cdx_base)]
    reg4_cur = [
        s - 0.25 * (g + c + k + h)
        for s, g, c, k, h in zip(sol_scores, gem_cur, cdx_cur, grk_cur, hh_cur)
    ]
    reg4_base = [
        s - 0.25 * (g + c + k + h)
        for s, g, c, k, h in zip(base_sol_scores, gem_base, cdx_base, grk_base, hh_base)
    ]
    min4_seed_cur = [
        s - max(g, c, k, h)
        for s, g, c, k, h in zip(sol_scores, gem_cur, cdx_cur, grk_cur, hh_cur)
    ]

    def _bci(diffs: list[float], metric: str) -> dict[str, float | int]:
        return paired_bootstrap_ci(
            diffs,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"vsdef:{tier}:{canon_sha}:{metric}",
        )

    mean_inv_regrets = {
        pname: float(policies_summary[pname]["regret_vs_solver"]["mean"])
        for pname in INVESTIGATOR_NAMES
    }
    strongest_inv = min(INVESTIGATOR_NAMES, key=lambda pname: mean_inv_regrets[pname])

    vs_default = {
        "solver_acc_delta": _bci([a - b for a, b in zip(sol_accs, base_sol_accs)], "solver_acc_delta"),
        "solver_score_delta": _bci([a - b for a, b in zip(sol_scores, base_sol_scores)], "solver_score_delta"),
        "gemini_regret_gain": _bci(
            [(sa - ga) - (sb - gb) for sa, ga, sb, gb in zip(sol_scores, gem_cur, base_sol_scores, gem_base)],
            "gemini_regret_gain",
        ),
        "codex_regret_gain": _bci(
            [(sa - ca) - (sb - cb) for sa, ca, sb, cb in zip(sol_scores, cdx_cur, base_sol_scores, cdx_base)],
            "codex_regret_gain",
        ),
        "grok_regret_gain": _bci(
            [(sa - ka) - (sb - kb) for sa, ka, sb, kb in zip(sol_scores, grk_cur, base_sol_scores, grk_base)],
            "grok_regret_gain",
        ),
        "hinted_regret_gain": _bci(
            [(sa - ha) - (sb - hb) for sa, ha, sb, hb in zip(sol_scores, hh_cur, base_sol_scores, hh_base)],
            "hinted_regret_gain",
        ),
        "mean_frontier_regret": _bci(freg_cur, "mean_frontier_regret"),
        "mean_frontier_regret_gain": _bci([a - b for a, b in zip(freg_cur, freg_base)], "mean_frontier_regret_gain"),
        "mean_4inv_regret": _bci(reg4_cur, "mean_4inv_regret"),
        "mean_4inv_regret_gain": _bci([a - b for a, b in zip(reg4_cur, reg4_base)], "mean_4inv_regret_gain"),
        "seedwise_min_4inv_regret": _bci(min4_seed_cur, "seedwise_min_4inv_regret"),
        "population_min_4inv_regret": round(mean_inv_regrets[strongest_inv], 5),
        "strongest_investigator": strongest_inv,
    }

    comb = cf_strat_row["combined"]
    cf_keys = sorted(set(cf_eps_cur.keys()) & set(cf_eps_base.keys()))
    p_drops = [float(cf_eps_base[k]["p_true_mole"] - cf_eps_cur[k]["p_true_mole"]) for k in cf_keys]
    ev_drops = [float(cf_eps_base[k]["optimal_ev"] - cf_eps_cur[k]["optimal_ev"]) for k in cf_keys]

    cf_summary = {
        "n_transcripts": int(comb["n"]),
        "p_true_mole": round(float(comb["p_true_mole"]), 5),
        "p_true_mole_horizon": round(float(comb["p_true_mole_horizon"]), 5),
        "optimal_ev": round(float(comb["optimal_ev"]), 5),
        "optimal_ev_horizon": round(float(comb["optimal_ev_horizon"]), 5),
        "top_suspect_accuracy": round(float(comb["top_suspect_accuracy"]), 5),
        "surfaced_canaries": round(float(comb["surfaced_canaries"]), 4),
        "surfaced_total_leaks": round(float(comb["surfaced_total_leaks"]), 4),
        "p_true_mole_drop_vs_default": paired_bootstrap_ci(
            p_drops,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"cf:{tier}:{canon_sha}:p_drop",
        ),
        "optimal_ev_drop_vs_default": paired_bootstrap_ci(
            ev_drops,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"cf:{tier}:{canon_sha}:ev_drop",
        ),
        "per_source": {
            src: {
                "n": int(cf_strat_row["per_source"][src]["n"]),
                "p_true_mole": round(float(cf_strat_row["per_source"][src]["p_true_mole"]), 5),
                "p_true_mole_drop": round(float(cf_strat_row["per_source"][src]["p_true_mole_drop"]), 5),
                "optimal_ev": round(float(cf_strat_row["per_source"][src]["optimal_ev"]), 5),
                "optimal_ev_drop": round(float(cf_strat_row["per_source"][src]["optimal_ev_drop"]), 5),
                "surfaced_canaries": round(float(cf_strat_row["per_source"][src]["surfaced_canaries"]), 4),
            }
            for src in cf_sources
        },
    }

    sol_acc_val = float(policies_summary["solver"]["acc"])
    sol_score_val = float(policies_summary["solver"]["score"])
    solver_ratio = round(sol_score_val / baseline_solver_score, 5) if baseline_solver_score > 0.0 else 0.0

    gates = evaluate_tier_gates(
        dsl_valid=dsl_ok,
        solver_acc=sol_acc_val,
        solver_score=sol_score_val,
        baseline_solver_score=baseline_solver_score,
        logs_only_acc=float(policies_summary["logs_only"]["acc"]),
        accuse_most_logs_acc=float(policies_summary["accuse_most_logs"]["acc"]),
        do_nothing_max_abs=float(policies_summary["do_nothing"]["max_abs_score"]),
        stop_early_quit_max_abs=float(policies_summary["stop_early_quit"]["max_abs_score"]),
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
        max_logs_acc=max_logs_acc,
    )

    return {
        "tier": tier,
        "behavior_hash": behavior_hash(sj, tier),
        "empirical_ledger_hash": emp_ledger_hash,
        "tier_conds_in_range": conds_in_range,
        "mean_mole_leaks": mean_mole_leaks,
        "mean_mole_frames": mean_mole_frames,
        "solver_ratio_vs_default": solver_ratio,
        "gates": gates,
        "failed_gates": failed_gate_names(gates),
        "policies": policies_summary,
        "vs_default": vs_default,
        "counterfactual": cf_summary,
    }


def _compute_cross_tier_deltas(
    canon_sha: str,
    med_rows: list[dict[str, Any]],
    hard_rows: list[dict[str, Any]],
    cf_med_cur: dict[tuple[str, int], dict[str, Any]],
    cf_med_base: dict[tuple[str, int], dict[str, Any]],
    cf_hard_cur: dict[tuple[str, int], dict[str, Any]],
    cf_hard_base: dict[tuple[str, int], dict[str, Any]],
    n_boot: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    if [r["seed"] for r in med_rows] != [r["seed"] for r in hard_rows]:
        raise AssertionError("medium and hard seed alignment mismatch")

    acc_diff = [
        (1.0 if m["policies"]["solver"]["correct"] else 0.0)
        - (1.0 if h["policies"]["solver"]["correct"] else 0.0)
        for m, h in zip(med_rows, hard_rows)
    ]
    sc_diff = [
        float(m["policies"]["solver"]["score"]) - float(h["policies"]["solver"]["score"])
        for m, h in zip(med_rows, hard_rows)
    ]
    freg_diff = [
        (
            float(m["policies"]["solver"]["score"])
            - 0.5
            * (
                float(m["policies"]["gemini_carbon_proxy"]["score"])
                + float(m["policies"]["codex_horizon_proxy"]["score"])
            )
        )
        - (
            float(h["policies"]["solver"]["score"])
            - 0.5
            * (
                float(h["policies"]["gemini_carbon_proxy"]["score"])
                + float(h["policies"]["codex_horizon_proxy"]["score"])
            )
        )
        for m, h in zip(med_rows, hard_rows)
    ]
    leak_diff = [float(m["mole_leaks"] - h["mole_leaks"]) for m, h in zip(med_rows, hard_rows)]

    cf_keys = sorted(
        set(cf_med_cur.keys())
        & set(cf_med_base.keys())
        & set(cf_hard_cur.keys())
        & set(cf_hard_base.keys())
    )
    cf_ev_drop_diff = [
        float(cf_med_base[k]["optimal_ev"] - cf_med_cur[k]["optimal_ev"])
        - float(cf_hard_base[k]["optimal_ev"] - cf_hard_cur[k]["optimal_ev"])
        for k in cf_keys
    ]
    cf_p_drop_diff = [
        float(cf_med_base[k]["p_true_mole"] - cf_med_cur[k]["p_true_mole"])
        - float(cf_hard_base[k]["p_true_mole"] - cf_hard_cur[k]["p_true_mole"])
        for k in cf_keys
    ]

    def _xci(diffs: list[float], metric: str) -> dict[str, float | int]:
        return paired_bootstrap_ci(
            diffs,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"xtier:{canon_sha}:{metric}",
        )

    return {
        "medium_minus_hard_solver_acc": _xci(acc_diff, "solver_acc"),
        "medium_minus_hard_solver_score": _xci(sc_diff, "solver_score"),
        "medium_minus_hard_frontier_regret": _xci(freg_diff, "frontier_regret"),
        "medium_minus_hard_mole_leaks": _xci(leak_diff, "mole_leaks"),
        "medium_minus_hard_cf_ev_drop": _xci(cf_ev_drop_diff, "cf_ev_drop"),
        "medium_minus_hard_cf_p_drop": _xci(cf_p_drop_diff, "cf_p_drop"),
    }


def run_tier_robustness_study(
    tiers: Sequence[str] = DEFAULT_TIERS,
    seeds: str | Iterable[int] = DEFAULT_ROBUSTNESS_SEEDS,
    cf_seeds: str | Iterable[int] = DEFAULT_CF_SEEDS,
    cf_sources: Iterable[str] = DEFAULT_CF_SOURCES,
    strategy_names: Sequence[str] | None = None,
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
    tier_tuple = tuple(str(t).strip() for t in tiers if str(t).strip())
    if tuple(tier_tuple) != ("medium", "hard"):
        raise ValueError(f"tiers must be ('medium', 'hard'), got {tier_tuple!r}")

    seed_list = normalize_robustness_seeds(seeds, enforce_hygiene=enforce_seed_hygiene)
    cf_seed_list = _parse_explicit_seed_spec(cf_seeds) if isinstance(cf_seeds, str) else [int(s) for s in cf_seeds]
    if not cf_seed_list:
        raise ValueError("cf_seeds must not be empty")
    source_tuple = tuple(str(s).strip() for s in cf_sources if str(s).strip())
    if not source_tuple:
        raise ValueError("cf_sources must not be empty")

    reg = _registry()
    if strategy_names is None:
        selected_names = list(reg.keys())
    else:
        selected_names = []
        for raw_name in strategy_names:
            rname = resolve_tier_strategy_name(raw_name)
            if rname not in selected_names:
                selected_names.append(rname)
    if not selected_names:
        raise ValueError("strategy_names must not be empty")

    selected_specs = [reg[n] for n in selected_names]
    default_spec = reg[DEFAULT_STRATEGY.name]

    canon_to_sj: dict[str, dict[str, Any]] = {
        default_spec.canonical_sha256: default_spec.to_json()
    }
    for spec in selected_specs:
        if spec.canonical_sha256 not in canon_to_sj:
            canon_to_sj[spec.canonical_sha256] = spec.to_json()
    canon_order = list(canon_to_sj.keys())

    live_by_tier_canon: dict[tuple[str, str], list[dict[str, Any]]] = {
        (t, csha): [] for t in tier_tuple for csha in canon_order
    }
    cached_keys: set[tuple[str, str, int]] = set()
    cache_path = Path(cache_jsonl) if cache_jsonl is not None else None
    if cache_path is not None and cache_path.is_file():
        want_seeds = set(seed_list)
        want_tiers = set(tier_tuple)
        want_canons = set(canon_order)
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            rt = str(row.get("tier", ""))
            rc = str(row.get("canon_sha", ""))
            rs = int(row.get("seed", -1))
            if rt in want_tiers and rc in want_canons and rs in want_seeds:
                ck = (rt, rc, rs)
                if ck not in cached_keys:
                    cached_keys.add(ck)
                    live_by_tier_canon[(rt, rc)].append(row)

    tasks: list[tuple[str, str, int, dict[str, Any]]] = []
    for t in tier_tuple:
        for csha in canon_order:
            sj = canon_to_sj[csha]
            for s in seed_list:
                if (t, csha, s) not in cached_keys:
                    tasks.append((csha, t, s, sj))

    t0 = time.monotonic()
    eff_workers = max(1, int(workers))
    cache_fh = None
    if cache_path is not None and tasks:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_fh = cache_path.open("a", encoding="utf-8")

    try:
        total_cells = len(cached_keys) + len(tasks)
        if eff_workers > 1 and len(tasks) > 1:
            with ProcessPoolExecutor(max_workers=eff_workers) as pool:
                done_count = len(cached_keys)
                for row in pool.map(_eval_canonical_seed_worker, tasks, chunksize=2):
                    live_by_tier_canon[(str(row["tier"]), str(row["canon_sha"]))].append(row)
                    if cache_fh is not None:
                        cache_fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                        cache_fh.flush()
                    done_count += 1
                    if progress and (done_count % 50 == 0 or done_count == total_cells):
                        print(
                            f"[tier_robustness] live cells {done_count}/{total_cells} ({time.monotonic() - t0:.1f}s)",
                            file=sys.stderr,
                            flush=True,
                        )
        else:
            for offset, task in enumerate(tasks, 1):
                row = _eval_canonical_seed_worker(task)
                live_by_tier_canon[(str(row["tier"]), str(row["canon_sha"]))].append(row)
                if cache_fh is not None:
                    cache_fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                    cache_fh.flush()
                done_count = len(cached_keys) + offset
                if progress and (done_count % 40 == 0 or done_count == total_cells):
                    print(
                        f"[tier_robustness] live cells {done_count}/{total_cells} ({time.monotonic() - t0:.1f}s)",
                        file=sys.stderr,
                        flush=True,
                    )
    finally:
        if cache_fh is not None:
            cache_fh.close()

    for key in live_by_tier_canon:
        live_by_tier_canon[key].sort(key=lambda r: int(r["seed"]))

    cf_by_tier: dict[str, dict[str, Any]] = {}
    cf_eps_by_tier_canon: dict[tuple[str, str], dict[tuple[str, int], dict[str, Any]]] = {}
    cf_payload: dict[str, dict[str, Any]] = {}
    for csha, sj in canon_to_sj.items():
        sj_named = copy.deepcopy(sj)
        sj_named["name"] = DEFAULT_STRATEGY.name if csha == default_spec.canonical_sha256 else csha
        cf_payload[csha] = sj_named

    for t in tier_tuple:
        cf_rep = evaluate_counterfactual(
            strategies=cf_payload,
            seeds=cf_seed_list,
            tier=t,
            run_solver=False,
            sources=source_tuple,
            workers=1,
        )
        cf_by_tier[t] = cf_rep
        for csha in canon_order:
            srow = cf_rep["strategies"][csha]
            by_ep: dict[tuple[str, int], dict[str, Any]] = {}
            for src in source_tuple:
                for ep in srow["per_source"][src]["episodes"]:
                    by_ep[(src, int(ep["seed"]))] = ep
            cf_eps_by_tier_canon[(t, csha)] = by_ep
        if progress:
            print(
                f"[tier_robustness] counterfactual {t} complete ({time.monotonic() - t0:.1f}s)",
                file=sys.stderr,
                flush=True,
            )

    def_sha = default_spec.canonical_sha256
    baseline_reference: dict[str, dict[str, float]] = {}
    for t in tier_tuple:
        b_rows = live_by_tier_canon[(t, def_sha)]
        baseline_reference[t] = {
            "solver_score": round(
                sum(float(r["policies"]["solver"]["score"]) for r in b_rows) / len(b_rows), 5
            ),
            "solver_acc": round(
                sum(1.0 if r["policies"]["solver"]["correct"] else 0.0 for r in b_rows) / len(b_rows), 5
            ),
            "mean_mole_leaks": round(sum(float(r["mole_leaks"]) for r in b_rows) / len(b_rows), 4),
        }

    strategies_out: dict[str, dict[str, Any]] = {}
    for spec in selected_specs:
        csha = spec.canonical_sha256
        mech = _inspect_rule_mechanics(spec.strategy_json)
        tier_cells: dict[str, dict[str, Any]] = {}
        for t in tier_tuple:
            tier_cells[t] = _build_tier_cell(
                spec=spec,
                tier=t,
                rows=live_by_tier_canon[(t, csha)],
                base_rows=live_by_tier_canon[(t, def_sha)],
                cf_strat_row=cf_by_tier[t]["strategies"][csha],
                cf_eps_cur=cf_eps_by_tier_canon[(t, csha)],
                cf_eps_base=cf_eps_by_tier_canon[(t, def_sha)],
                cf_sources=source_tuple,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
                min_solver_acc=min_solver_acc,
                min_solver_ratio=min_solver_ratio,
                max_logs_acc=max_logs_acc,
            )

        med_passed = bool(tier_cells["medium"]["gates"]["tier_passed"])
        hard_passed = bool(tier_cells["hard"]["gates"]["tier_passed"])
        classification = classify_tier_status(med_passed, hard_passed)

        xtier = _compute_cross_tier_deltas(
            canon_sha=csha,
            med_rows=live_by_tier_canon[("medium", csha)],
            hard_rows=live_by_tier_canon[("hard", csha)],
            cf_med_cur=cf_eps_by_tier_canon[("medium", csha)],
            cf_med_base=cf_eps_by_tier_canon[("medium", def_sha)],
            cf_hard_cur=cf_eps_by_tier_canon[("hard", csha)],
            cf_hard_base=cf_eps_by_tier_canon[("hard", def_sha)],
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
        )

        strategies_out[spec.name] = {
            "name": spec.name,
            "source": spec.source,
            "group": spec.group,
            "hof_rank": spec.hof_rank,
            "hof_survivor_name": spec.hof_survivor_name,
            "canonical_equivalent_of": spec.canonical_equivalent_of,
            "canonical_sha256": csha,
            **mech,
            "classification": classification,
            "medium_passed": med_passed,
            "hard_passed": hard_passed,
            "strategy_json": spec.to_json(),
            "cross_tier_deltas": xtier,
            "tiers": tier_cells,
        }

    counts_by_class = {
        cls: sum(1 for s in strategies_out.values() if s["classification"] == cls)
        for cls in CLASSIFICATION_VALUES
    }
    names_by_class = {
        cls: [name for name, s in strategies_out.items() if s["classification"] == cls]
        for cls in CLASSIFICATION_VALUES
    }

    pacing_names = [
        name for name, s in strategies_out.items() if s["uses_d5_d8_quiet_pacing"]
    ]
    horizon_gt14_names = [
        name for name, s in strategies_out.items() if s["has_day_gt_medium_horizon"]
    ]

    tier_specs_meta: dict[str, dict[str, Any]] = {}
    for t in tier_tuple:
        tp = tier_params(t)
        tier_specs_meta[t] = {
            "n_days": int(tp.n_days),
            "n_employees": int(tp.n_employees),
            "fingerprint_accuracy": float(tp.fingerprint_accuracy),
            "canaries_per_day": int(tp.canaries_per_day),
            "max_variants": int(tp.max_variants),
            "p_leak": float(tp.p_leak),
            "delay_choices": list(tp.delay_choices),
            "leak_damage": float(tp.leak_damage),
            "framing_rate": float(tp.framing_rate),
        }

    cf_med_seeds = list(cf_by_tier["medium"]["seeds"])
    cf_hard_seeds = list(cf_by_tier["hard"]["seeds"])

    summary = {
        "n_strategies": len(strategies_out),
        "n_unique_canonical": len({s["canonical_sha256"] for s in strategies_out.values()}),
        "counts_by_classification": counts_by_class,
        "strategies_by_classification": names_by_class,
        "d5_d8_pacing_strategies": pacing_names,
        "d5_d8_pacing_all_stay_ge_085_on_medium": bool(
            all(
                float(strategies_out[n]["tiers"]["medium"]["policies"]["solver"]["acc"]) >= float(min_solver_acc)
                for n in pacing_names
            )
        )
        if pacing_names
        else True,
        "strategies_with_dead_day_gt_14_on_medium": horizon_gt14_names,
        "all_zero_baselines_exact_both_tiers": bool(
            all(
                s["tiers"][t]["gates"]["do_nothing_zero"]
                and s["tiers"][t]["gates"]["stop_early_quit_zero"]
                for s in strategies_out.values()
                for t in tier_tuple
            )
        ),
        "all_logs_shortcuts_bounded_both_tiers": bool(
            all(
                s["tiers"][t]["gates"]["logs_only_le_max"]
                and s["tiers"][t]["gates"]["accuse_most_logs_le_max"]
                for s in strategies_out.values()
                for t in tier_tuple
            )
        ),
    }

    seed_range_str = f"{seed_list[0]}-{seed_list[-1]}" if len(seed_list) > 1 else str(seed_list[0])
    return {
        "study": "mole_tier_robustness_v14",
        "tiers_version": "v1.4",
        "api_calls": 0,
        "baseline_strategy": DEFAULT_STRATEGY.name,
        "tiers": list(tier_tuple),
        "tier_params": tier_specs_meta,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "seed_range": seed_range_str,
        "thresholds": {
            "min_solver_acc": float(min_solver_acc),
            "min_solver_ratio": float(min_solver_ratio),
            "max_logs_acc": float(max_logs_acc),
            "do_nothing_target": 0.0,
            "stop_early_quit_target": 0.0,
        },
        "bootstrap_config": {
            "n_boot": int(n_boot),
            "ci": 0.95,
            "seed": int(bootstrap_seed),
        },
        "counterfactual_config": {
            "sources": list(source_tuple),
            "medium_seeds": cf_med_seeds,
            "hard_seeds": cf_hard_seeds,
            "medium_transcripts": len(cf_med_seeds) * len(source_tuple),
            "hard_transcripts": len(cf_hard_seeds) * len(source_tuple),
            "total_transcripts": (len(cf_med_seeds) + len(cf_hard_seeds)) * len(source_tuple),
        },
        "baseline_reference": baseline_reference,
        "summary": summary,
        "strategies": strategies_out,
    }


def _ordered_strategy_items(strategies: dict[str, Any]) -> list[tuple[str, Any]]:
    known = list_tier_strategy_names()
    ordered = [n for n in known if n in strategies]
    ordered.extend(n for n in strategies if n not in known)
    return [(n, strategies[n]) for n in ordered]


def _fmt_ci(ci_obj: dict[str, Any], digits: int = 3, signed: bool = True) -> str:
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return (
        f"{fmt.format(float(ci_obj['mean']))} "
        f"[{fmt.format(float(ci_obj['ci_low']))}, {fmt.format(float(ci_obj['ci_high']))}]"
    )


def format_tier_robustness_summary(report: dict[str, Any]) -> str:
    sm = report["summary"]
    cnt = sm["counts_by_classification"]
    cf_cfg = report["counterfactual_config"]
    lines = [
        f"Mole Cross-Tier Robustness v1.4 (seeds={report['seed_range']} n={report['n_seeds']}/tier, "
        f"cf_transcripts={cf_cfg['total_transcripts']}, "
        f"DUAL_TIER_PASS={cnt['DUAL_TIER_PASS']}, HARD_ONLY_PASS={cnt['HARD_ONLY_PASS']}, FAIL={cnt['FAIL']})",
        "",
        "| strategy | group | med_sol_acc | med_sol_sc | hard_sol_acc | hard_sol_sc | med-hard_acc | med_freg | hard_freg | class |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, s in _ordered_strategy_items(report["strategies"]):
        med = s["tiers"]["medium"]
        hrd = s["tiers"]["hard"]
        d_acc = s["cross_tier_deltas"]["medium_minus_hard_solver_acc"]
        lines.append(
            f"| {name} | {s['group']} | "
            f"{med['policies']['solver']['acc']:.3f} | {med['policies']['solver']['score']:+.3f} | "
            f"{hrd['policies']['solver']['acc']:.3f} | {hrd['policies']['solver']['score']:+.3f} | "
            f"{d_acc['mean']:+.3f} | "
            f"{med['vs_default']['mean_frontier_regret']['mean']:+.3f} | "
            f"{hrd['vs_default']['mean_frontier_regret']['mean']:+.3f} | "
            f"{s['classification']} |"
        )
    return "\n".join(lines)


def format_tier_robustness_markdown(report: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3

    sm = report["summary"]
    cnt = sm["counts_by_classification"]
    by_cls = sm["strategies_by_classification"]
    th = report["thresholds"]
    b_cfg = report["bootstrap_config"]
    cf_cfg = report["counterfactual_config"]
    tp_med = report["tier_params"]["medium"]
    tp_hrd = report["tier_params"]["hard"]
    b_ref = report["baseline_reference"]

    src_str = ",".join(cf_cfg["sources"])
    med_cf_seeds = cf_cfg["medium_seeds"]
    cf_seed_range = (
        f"{med_cf_seeds[0]}-{med_cf_seeds[-1]}"
        if len(med_cf_seeds) > 1
        else (str(med_cf_seeds[0]) if med_cf_seeds else "n/a")
    )
    per_src_str = " + ".join(f"`{len(med_cf_seeds)}` `{src}`" for src in cf_cfg["sources"])

    dual_list = ", ".join(f"`{x}`" for x in by_cls["DUAL_TIER_PASS"]) if by_cls["DUAL_TIER_PASS"] else "none"
    hard_only_list = ", ".join(f"`{x}`" for x in by_cls["HARD_ONLY_PASS"]) if by_cls["HARD_ONLY_PASS"] else "none"
    fail_list = ", ".join(f"`{x}`" for x in by_cls["FAIL"]) if by_cls["FAIL"] else "none"

    pacing_rows = [report["strategies"][n] for n in sm["d5_d8_pacing_strategies"] if n in report["strategies"]]
    pacing_summary_parts = [
        f"`{r['name']}` (`medium` acc `{r['tiers']['medium']['policies']['solver']['acc']:.3f}` vs "
        f"`hard` acc `{r['tiers']['hard']['policies']['solver']['acc']:.3f}`, "
        f"`{r['classification']}`)"
        for r in pacing_rows
    ]
    pacing_answer = (
        f"Yes, every days 5..8 midgame-pacing strategy stays >= {th['min_solver_acc']:.2f} catchable on 14-day `medium`: "
        + "; ".join(pacing_summary_parts)
        if sm["d5_d8_pacing_all_stay_ge_085_on_medium"]
        else f"No, days 5..8 midgame quiet-pacing rules tuned on 21-day `hard` do NOT uniformly stay >= {th['min_solver_acc']:.2f} "
        "`SolverPolicy(\"medium\")` catchable on 14-day `medium`: " + "; ".join(pacing_summary_parts)
    )

    lines: list[str] = [
        f"{h1} Cross-Tier Mole Strategy Robustness Study (`medium` vs `hard`, v1.4)",
        "",
        "Generated deterministically offline (0 API calls) via "
        f"`python -m canary.mole.tier_robustness --seeds {report['seed_range']} "
        f"--cf-seeds {cf_seed_range} --cf-sources {src_str} --workers 2 "
        "--out results/mole_strategies/tier_robustness_v14.json "
        "--report-md docs/reports/mole_tier_robustness_v14.md`.",
        "",
        f"{h2} 1. Executive Answer for Silas (`medium` 14d vs `hard` 21d)",
        "",
        f"- **Tier parameter contrast**: `medium` runs `{tp_med['n_days']}` days, `{tp_med['n_employees']}` employees, "
        f"`canaries_per_day={tp_med['canaries_per_day']}`, `delay_choices={tuple(tp_med['delay_choices'])}`, "
        f"`p_leak={tp_med['p_leak']:.2f}`, `fingerprint_accuracy={tp_med['fingerprint_accuracy']:.2f}`; "
        f"`hard` runs `{tp_hrd['n_days']}` days, `{tp_hrd['n_employees']}` employees, "
        f"`canaries_per_day={tp_hrd['canaries_per_day']}`, `delay_choices={tuple(tp_hrd['delay_choices'])}`, "
        f"`p_leak={tp_hrd['p_leak']:.2f}`, `fingerprint_accuracy={tp_hrd['fingerprint_accuracy']:.2f}`.",
        f"- **Paired offline evaluation slice**: `n={report['n_seeds']}` fresh disjoint seeds (`{report['seed_range']}`) "
        "on BOTH `medium` and `hard` (zero overlap with `0..59`, `30000..30199`, `800000+`, `900000+`), "
        f"plus `{cf_cfg['total_transcripts']}` committed v1.4 Gemini-4-carbon transcripts "
        f"(`{cf_cfg['medium_transcripts']}` `medium` + `{cf_cfg['hard_transcripts']}` `hard`, seeds `{cf_seed_range}`, "
        f"`{src_str}`) and `{b_cfg['n_boot']}` paired bootstrap resamples (`seed={b_cfg['seed']}`).",
        f"- **Critical question on 21-day `hard` pacing vs 14-day `medium` catchability**: {pacing_answer}.",
        f"- **Classification breakdown across all `{sm['n_strategies']}` strategies "
        f"(`{sm['n_unique_canonical']}` unique canonical DSL bodies)**:",
        f"  - `DUAL_TIER_PASS` (`{cnt['DUAL_TIER_PASS']}/{sm['n_strategies']}`): {dual_list}.",
        f"  - `HARD_ONLY_PASS` (`{cnt['HARD_ONLY_PASS']}/{sm['n_strategies']}`): {hard_only_list}.",
        f"  - `FAIL` (`{cnt['FAIL']}/{sm['n_strategies']}`): {fail_list}.",
        f"- **Anti-shortcut fairness invariants**: `DoNothing == 0.0` and `StopEarlyQuit == 0.0` hold exactly on "
        f"both tiers (`all_zero_baselines_exact_both_tiers={sm['all_zero_baselines_exact_both_tiers']}`), and "
        f"`LogsOnly <= {th['max_logs_acc']:.2f}` plus `AccuseMostLogs <= {th['max_logs_acc']:.2f}` hold across "
        f"checked cells (`all_logs_shortcuts_bounded_both_tiers={sm['all_logs_shortcuts_bounded_both_tiers']}`).",
        f"- **Horizon-rule diagnostic**: strategies with explicit `day > 14` conditions that become unreachable dead "
        f"branches on 14-day `medium`: "
        + (
            ", ".join(f"`{x}`" for x in sm["strategies_with_dead_day_gt_14_on_medium"])
            if sm["strategies_with_dead_day_gt_14_on_medium"]
            else "none"
        )
        + ".",
        "",
        f"{h2} 2. Cross-Tier Classification and Catchability Summary",
        "",
        f"Gate definition per tier: `SolverPolicy >= {th['min_solver_acc']:.2f}`, "
        f"`solver_ratio >= {th['min_solver_ratio']:.2f}` vs `default_v0` (`medium` `{b_ref['medium']['solver_score']:+.3f}`, "
        f"`hard` `{b_ref['hard']['solver_score']:+.3f}`), `LogsOnly <= {th['max_logs_acc']:.2f}`, "
        f"`AccuseMostLogs <= {th['max_logs_acc']:.2f}`, `DoNothing == 0.0`, `StopEarlyQuit == 0.0`.",
        "",
        "| Strategy | Source Group | Med Solver Acc | Med Ratio | Hard Solver Acc | Hard Ratio | Med - Hard Acc [95% CI] | Med/Hard Leaks | Failed Gates (Med / Hard) | Class |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for name, s in _ordered_strategy_items(report["strategies"]):
        med = s["tiers"]["medium"]
        hrd = s["tiers"]["hard"]
        d_acc = s["cross_tier_deltas"]["medium_minus_hard_solver_acc"]
        fg_med = ",".join(med["failed_gates"]) if med["failed_gates"] else "none"
        fg_hrd = ",".join(hrd["failed_gates"]) if hrd["failed_gates"] else "none"
        lines.append(
            f"| `{name}` | `{s['group']}` | "
            f"{med['policies']['solver']['acc']:.3f} | {med['solver_ratio_vs_default']:.2f} | "
            f"{hrd['policies']['solver']['acc']:.3f} | {hrd['solver_ratio_vs_default']:.2f} | "
            f"{_fmt_ci(d_acc)} | "
            f"{med['mean_mole_leaks']:.2f} / {hrd['mean_mole_leaks']:.2f} | "
            f"`{fg_med}` / `{fg_hrd}` | **{s['classification']}** |"
        )

    for tier_label, tier_key, tp_cur in (
        ("3. Medium Tier (`14d / 20 emp / fp=1.0`)", "medium", tp_med),
        ("4. Hard Tier (`21d / 40 emp / fp=0.95`)", "hard", tp_hrd),
    ):
        lines.extend([
            "",
            f"{h2} {tier_label} Paired Live (`n={report['n_seeds']}`) and Counterfactual (`n={cf_cfg[tier_key + '_transcripts']}`) Results",
            "",
            f"Tier baseline (`default_v0`): `SolverPolicy` acc `{b_ref[tier_key]['solver_acc']:.3f}`, "
            f"score `{b_ref[tier_key]['solver_score']:+.3f}`, mean mole leaks `{b_ref[tier_key]['mean_mole_leaks']:.2f}` "
            f"over `{tp_cur['n_days']}` days.",
            "",
            "| Strategy | Solver Acc (Score) | LogsOnly Acc | AccuseMostLogs Acc | DoNothing / StopEarly | Gemini Proxy | Codex Proxy | Grok | HintedHeur | Frontier Regret | CF EV Drop | Gate |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ])
        for name, s in _ordered_strategy_items(report["strategies"]):
            tc = s["tiers"][tier_key]
            pol = tc["policies"]
            freg = tc["vs_default"]["mean_frontier_regret"]
            cf = tc["counterfactual"]
            gate_str = "PASS" if tc["gates"]["tier_passed"] else "FAIL"
            lines.append(
                f"| `{name}` | "
                f"{pol['solver']['acc']:.3f} ({pol['solver']['score']:+.3f}) | "
                f"{pol['logs_only']['acc']:.3f} | "
                f"{pol['accuse_most_logs']['acc']:.3f} | "
                f"{pol['do_nothing']['score']:+.3f} / {pol['stop_early_quit']['score']:+.3f} | "
                f"{pol['gemini_carbon_proxy']['score']:+.3f} | "
                f"{pol['codex_horizon_proxy']['score']:+.3f} | "
                f"{pol['grok_tactics']['score']:+.3f} | "
                f"{pol['hinted_heuristic']['score']:+.3f} | "
                f"{freg['mean']:+.3f} | "
                f"{cf['optimal_ev_drop_vs_default']['mean']:+.3f} | "
                f"{gate_str} |"
            )

    lines.extend([
        "",
        f"{h2} 5. Investigator Regret Gains vs `default_v0` (Paired Bootstrap 95% CIs)",
        "",
        "Regret is `SolverPolicy(tier) score - investigator score` on paired seeds; positive regret gain means the "
        "mole strategy widens the Solver-to-investigator gap relative to `default_v0`.",
        "",
        f"{h3} 5.1 `medium` Tier Regret Gains vs `default_v0`",
        "",
        "| Strategy | Solver Score Delta [95% CI] | Gemini Regret Gain [95% CI] | Codex Regret Gain [95% CI] | Grok Regret Gain [95% CI] | Hinted Regret Gain [95% CI] | 4-Inv Mean Regret Gain [95% CI] | Strongest Inv (Min Regret) |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for name, s in _ordered_strategy_items(report["strategies"]):
        vd = s["tiers"]["medium"]["vs_default"]
        lines.append(
            f"| `{name}` | "
            f"{_fmt_ci(vd['solver_score_delta'])} | "
            f"{_fmt_ci(vd['gemini_regret_gain'])} | "
            f"{_fmt_ci(vd['codex_regret_gain'])} | "
            f"{_fmt_ci(vd['grok_regret_gain'])} | "
            f"{_fmt_ci(vd['hinted_regret_gain'])} | "
            f"{_fmt_ci(vd['mean_4inv_regret_gain'])} | "
            f"`{vd['strongest_investigator']}` ({vd['population_min_4inv_regret']:+.3f}) |"
        )

    lines.extend([
        "",
        f"{h3} 5.2 `hard` Tier Regret Gains vs `default_v0`",
        "",
        "| Strategy | Solver Score Delta [95% CI] | Gemini Regret Gain [95% CI] | Codex Regret Gain [95% CI] | Grok Regret Gain [95% CI] | Hinted Regret Gain [95% CI] | 4-Inv Mean Regret Gain [95% CI] | Strongest Inv (Min Regret) |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for name, s in _ordered_strategy_items(report["strategies"]):
        vd = s["tiers"]["hard"]["vs_default"]
        lines.append(
            f"| `{name}` | "
            f"{_fmt_ci(vd['solver_score_delta'])} | "
            f"{_fmt_ci(vd['gemini_regret_gain'])} | "
            f"{_fmt_ci(vd['codex_regret_gain'])} | "
            f"{_fmt_ci(vd['grok_regret_gain'])} | "
            f"{_fmt_ci(vd['hinted_regret_gain'])} | "
            f"{_fmt_ci(vd['mean_4inv_regret_gain'])} | "
            f"`{vd['strongest_investigator']}` ({vd['population_min_4inv_regret']:+.3f}) |"
        )

    lines.extend([
        "",
        f"{h2} 6. Counterfactual Replay on Committed v1.4 Gemini-4-carbon Transcripts (`{cf_cfg['medium_transcripts']}` `medium` + `{cf_cfg['hard_transcripts']}` `hard`)",
        "",
        f"Schedule replay holds Gemini-4-carbon tool calls fixed on seeds `{cf_seed_range}` ({per_src_str} per tier) "
        "and measures exact Bayesian `P(true mole)` and `optimal_ev` drops relative to `default_v0`.",
        "",
        "| Strategy | Med CF P(mole) Drop [95% CI] | Med CF EV Drop [95% CI] | Med Surf Canaries | Hard CF P(mole) Drop [95% CI] | Hard CF EV Drop [95% CI] | Hard Surf Canaries | OpenCode Med/Hard EV Drop | InProc Med/Hard EV Drop |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for name, s in _ordered_strategy_items(report["strategies"]):
        cm = s["tiers"]["medium"]["counterfactual"]
        ch = s["tiers"]["hard"]["counterfactual"]
        oc_m = cm["per_source"].get("opencode", {}).get("optimal_ev_drop", 0.0)
        oc_h = ch["per_source"].get("opencode", {}).get("optimal_ev_drop", 0.0)
        ip_m = cm["per_source"].get("inproc", {}).get("optimal_ev_drop", 0.0)
        ip_h = ch["per_source"].get("inproc", {}).get("optimal_ev_drop", 0.0)
        lines.append(
            f"| `{name}` | "
            f"{_fmt_ci(cm['p_true_mole_drop_vs_default'])} | "
            f"{_fmt_ci(cm['optimal_ev_drop_vs_default'])} | "
            f"{cm['surfaced_canaries']:.2f} | "
            f"{_fmt_ci(ch['p_true_mole_drop_vs_default'])} | "
            f"{_fmt_ci(ch['optimal_ev_drop_vs_default'])} | "
            f"{ch['surfaced_canaries']:.2f} | "
            f"{oc_m:+.3f} / {oc_h:+.3f} | "
            f"{ip_m:+.3f} / {ip_h:+.3f} |"
        )

    lines.extend([
        "",
        f"{h2} 7. Rule Structure Diagnostics and Provenance Hashes",
        "",
        "| Strategy | Rules | Max Day | d5..8 Pacing | Age0->Oldest | Default Leak=None | Med Conds In-Range | Canon Equiv | Canon SHA-256 | Med / Hard Ledger Hashes |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ])
    for name, s in _ordered_strategy_items(report["strategies"]):
        med = s["tiers"]["medium"]
        hrd = s["tiers"]["hard"]
        eq = f"`{s['canonical_equivalent_of']}`" if s["canonical_equivalent_of"] else "unique"
        lines.append(
            f"| `{name}` | {s['n_rules']} | {s['max_day_threshold']} | "
            f"`{s['uses_d5_d8_quiet_pacing']}` | `{s['uses_age0_oldest_evasion']}` | "
            f"`{s['uses_default_leak_none']}` | `{med['tier_conds_in_range']}` | "
            f"{eq} | `{s['canonical_sha256']}` | "
            f"`{med['empirical_ledger_hash'][:10]}` / `{hrd['empirical_ledger_hash'][:10]}` |"
        )

    return "\n".join(lines) + "\n"


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


def dumps_tier_robustness_json(
    obj: Any,
    indent: int = 1,
    _level: int = 0,
    inline_limit: int = 320,
) -> str:
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        compact = json.dumps(obj, separators=(",", ":"), sort_keys=True)
        if _level >= 2 or len(compact) <= inline_limit:
            return compact
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [
            f"{pad}{json.dumps(k)}:{dumps_tier_robustness_json(obj[k], indent, _level + 1, inline_limit)}"
            for k in sorted(obj)
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(obj, list):
        compact = json.dumps(obj, separators=(",", ":"), sort_keys=True)
        if _level >= 2 or len(compact) <= inline_limit:
            return compact
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [
            f"{pad}{dumps_tier_robustness_json(v, indent, _level + 1, inline_limit)}"
            for v in obj
        ]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(obj)


def check_tier_robustness_artifacts(
    json_path: Path = DEFAULT_OUTPUT_PATH,
    md_path: Path = DEFAULT_REPORT_MD_PATH,
    max_json_bytes: int = MAX_JSON_BYTES,
) -> tuple[bool, str]:
    if not json_path.is_file():
        return False, f"FAIL: missing JSON artifact: {json_path}"
    if not md_path.is_file():
        return False, f"FAIL: missing Markdown report: {md_path}"

    raw_json_bytes = json_path.read_bytes()
    if len(raw_json_bytes) >= int(max_json_bytes):
        return False, f"FAIL: JSON artifact {json_path} exceeds size cap ({len(raw_json_bytes)} >= {max_json_bytes})"

    json_text = raw_json_bytes.decode("utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    for p, txt in ((json_path, json_text), (md_path, md_text)):
        if chr(0x2014) in txt or chr(0x2013) in txt:
            return False, f"FAIL: forbidden em/en dash found in {p}"
        if not txt.isascii():
            return False, f"FAIL: non-ASCII characters found in {p}"

    md_lower = md_text.lower()
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    coauthor_tag = "co-authored-" + "by"
    if flash_tag in md_lower:
        return False, f"FAIL: forbidden {flash_tag} reference in {md_path}"
    if solver_pct_tag in md_lower:
        return False, f"FAIL: forbidden unapproved {solver_pct_tag} claim in {md_path}"
    if coauthor_tag in md_lower or coauthor_tag in json_text.lower():
        return False, "FAIL: forbidden co-author trailer found"

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
        seeds = normalize_robustness_seeds(report.get("seeds", []), enforce_hygiene=True)
    except ValueError as exc:
        return False, f"FAIL: seed hygiene violation: {exc}"
    if len(seeds) != int(report.get("n_seeds", -1)):
        return False, f"FAIL: n_seeds mismatch ({len(seeds)} != {report.get('n_seeds')})"

    if report.get("tiers") != ["medium", "hard"]:
        return False, f"FAIL: expected tiers ['medium', 'hard'], got {report.get('tiers')!r}"

    th = report.get("thresholds", {})
    b_ref = report.get("baseline_reference", {})
    strategies = report.get("strategies", {})
    if not isinstance(strategies, dict) or not strategies:
        return False, "FAIL: missing strategies dictionary"

    recomputed_counts = {cls: 0 for cls in CLASSIFICATION_VALUES}
    for sname, srow in strategies.items():
        if srow.get("classification") not in CLASSIFICATION_VALUES:
            return False, f"FAIL: invalid classification on {sname}: {srow.get('classification')!r}"
        tier_pass_map: dict[str, bool] = {}
        for t in ("medium", "hard"):
            tcell = (srow.get("tiers") or {}).get(t)
            if not isinstance(tcell, dict):
                return False, f"FAIL: missing tier cell {t} on {sname}"
            pol = tcell.get("policies") or {}
            rec_gates = tcell.get("gates") or {}
            re_gates = evaluate_tier_gates(
                dsl_valid=bool(rec_gates.get("dsl_valid", False)),
                solver_acc=float(pol["solver"]["acc"]),
                solver_score=float(pol["solver"]["score"]),
                baseline_solver_score=float(b_ref[t]["solver_score"]),
                logs_only_acc=float(pol["logs_only"]["acc"]),
                accuse_most_logs_acc=float(pol["accuse_most_logs"]["acc"]),
                do_nothing_max_abs=float(pol["do_nothing"]["max_abs_score"]),
                stop_early_quit_max_abs=float(pol["stop_early_quit"]["max_abs_score"]),
                min_solver_acc=float(th.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC)),
                min_solver_ratio=float(th.get("min_solver_ratio", DEFAULT_MIN_SOLVER_RATIO)),
                max_logs_acc=float(th.get("max_logs_acc", DEFAULT_MAX_LOGS_ACC)),
            )
            if rec_gates != re_gates:
                return False, f"FAIL: gate tampering or mismatch on {sname} ({t})"
            tier_pass_map[t] = bool(re_gates["tier_passed"])

        exp_cls = classify_tier_status(tier_pass_map["medium"], tier_pass_map["hard"])
        if srow.get("classification") != exp_cls:
            return (
                False,
                f"FAIL: classification mismatch on {sname}: got {srow.get('classification')!r}, expected {exp_cls!r}",
            )
        if bool(srow.get("medium_passed")) != tier_pass_map["medium"] or bool(srow.get("hard_passed")) != tier_pass_map["hard"]:
            return False, f"FAIL: tier pass boolean mismatch on {sname}"
        recomputed_counts[exp_cls] += 1

    sm = report.get("summary", {})
    if sm.get("counts_by_classification") != recomputed_counts:
        return False, "FAIL: summary.counts_by_classification mismatch"

    expected_md = format_tier_robustness_markdown(report)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {md_path} does not match JSON ledger {json_path}"

    return (
        True,
        f"OK: {json_path.name} ({len(raw_json_bytes)} bytes, n={len(seeds)} seeds/tier, "
        f"DUAL_TIER_PASS={recomputed_counts['DUAL_TIER_PASS']}, "
        f"HARD_ONLY_PASS={recomputed_counts['HARD_ONLY_PASS']}, "
        f"FAIL={recomputed_counts['FAIL']}) matches {md_path.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.tier_robustness")
    ap.add_argument("--seeds", default="6300-6339")
    ap.add_argument("--cf-seeds", default="0-29")
    ap.add_argument("--cf-sources", default="opencode,inproc")
    ap.add_argument("--strategies", default=None, help="comma-separated subset of strategy names")
    ap.add_argument("--workers", type=int, default=2)
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
        ok, msg = check_tier_robustness_artifacts(json_path=j_path, md_path=m_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    strat_names = [x.strip() for x in args.strategies.split(",") if x.strip()] if args.strategies else None
    cf_sources = tuple(x.strip() for x in args.cf_sources.split(",") if x.strip())

    report = run_tier_robustness_study(
        seeds=args.seeds,
        cf_seeds=args.cf_seeds,
        cf_sources=cf_sources,
        strategy_names=strat_names,
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

    json_payload = dumps_tier_robustness_json(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json_payload + "\n", encoding="utf-8")

    if args.report_md is not None:
        args.report_md.parent.mkdir(parents=True, exist_ok=True)
        args.report_md.write_text(format_tier_robustness_markdown(report), encoding="utf-8")

    if args.json:
        print(json_payload)
    else:
        print(format_tier_robustness_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
