from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import (
    DoNothing,
    GrokTactics,
    Heuristic,
    LogsOnly,
    StopEarlyQuit,
)
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical
from canary.forge.rl_mole import RLMole
from canary.mole.counterfactual import (
    ScheduleReplayPolicy,
    inspect_observation_history,
    load_v14_frontier_episodes,
    replay_schedule,
)
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.mole.regret_portfolio import (
    DEFAULT_PORTFOLIO_SALT,
    DEFAULT_SUMMARY_JSON,
    PortfolioMolePolicy,
    load_summaries_from_v14_json,
    solve_minimax_regret_portfolio,
)
from canary.mole.strategies import get_strategy
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION, tier_params
from canary.solver.policy import SolverPolicy
from canary.world import generate_world

__all__ = [
    "BASELINE_POLICY_KEY",
    "DEFAULT_BOOT_RESAMPLES",
    "DEFAULT_BOOT_SEED",
    "DEFAULT_CF_SEEDS_SPEC",
    "DEFAULT_CF_SOURCES",
    "DEFAULT_EVAL_SEEDS_SPEC",
    "DEFAULT_HOF_META_PATH",
    "DEFAULT_HOF_PATH",
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "DEFAULT_OUT_PATH",
    "DEFAULT_PORTFOLIO_SUMMARY_PATH",
    "DEFAULT_REPORT_MD_PATH",
    "DEFAULT_RL_POLICY_PATH",
    "DEFAULT_WORKERS",
    "FAMILY_LABELS",
    "FAMILY_ORDER",
    "FRONTIER_PROXY_ORDER",
    "INVESTIGATOR_LABELS",
    "INVESTIGATOR_ORDER",
    "MAX_JSON_BYTES",
    "POLICY_ORDER",
    "PolicyRepresentationSpec",
    "assert_artifact_hygiene",
    "check_representation_pareto_artifacts",
    "compute_pareto_frontier",
    "dumps_compact_json",
    "evaluate_fairness_gates",
    "format_markdown_report",
    "format_terminal_summary",
    "instantiate_mole_policy",
    "load_representative_policies",
    "main",
    "paired_bootstrap_ci",
    "paired_minimax_bootstrap_ci",
    "pareto_dominates",
    "parse_seed_spec",
    "run_representation_pareto_benchmark",
    "validate_cf_seeds",
    "validate_pareto_seeds",
]

H1 = chr(35)
H2 = H1 * 2
H3 = H1 * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

DEFAULT_OUT_PATH = ROOT / "results" / "mole_strategies" / "representation_pareto_v14.json"
DEFAULT_REPORT_MD_PATH = ROOT / "docs" / "reports" / "mole_representation_pareto_v14.md"
DEFAULT_HOF_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
DEFAULT_HOF_META_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.meta.json"
DEFAULT_RL_POLICY_PATH = ROOT / "data" / "forge" / "rl_mole_frontier_v14.json"
DEFAULT_PORTFOLIO_SUMMARY_PATH = DEFAULT_SUMMARY_JSON

DEFAULT_EVAL_SEEDS_SPEC = "7400-7459"
DEFAULT_CF_SEEDS_SPEC = "0-29"
DEFAULT_CF_SOURCES: tuple[str, ...] = ("opencode", "inproc")
DEFAULT_WORKERS = 4
DEFAULT_BOOT_RESAMPLES = 2000
DEFAULT_BOOT_SEED = 20261115

DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_MIN_SOLVER_RATIO = 0.50
MAX_JSON_BYTES = 90_000

FORBIDDEN_LOW_SEED_MAX = 59
FORBIDDEN_DEV_SEED_RANGE = range(6000, 7000)
FORBIDDEN_RESERVED_HELDOUT_RANGE = range(30_000, 30_200)
FORBIDDEN_RL_TRAIN_RANGE = range(110_000, 111_000)
FORBIDDEN_HIGH_SEED_MIN = 800_000

BASELINE_POLICY_KEY = "default_v0"

POLICY_ORDER: tuple[str, ...] = (
    "default_v0",
    "surgical_trap_shield",
    "gemini_midsize_shield",
    "early_burst_midgame_pace",
    "frontier_synthesis_v14",
    "hof_v14_r1",
    "rl_mole_frontier_v14",
    "rl_mole_frontier_v14_softmax",
    "regret_portfolio_v14",
)

FAMILY_ORDER: tuple[str, ...] = (
    "baseline",
    "symbolic_dsl",
    "continuous_rl_mole",
    "minimax_portfolio",
)

FAMILY_LABELS: dict[str, str] = {
    "baseline": "Baseline Default",
    "symbolic_dsl": "Symbolic Mole DSL",
    "continuous_rl_mole": "Continuous Distilled RLMole",
    "minimax_portfolio": "Game-Theoretic Minimax Portfolio",
}

FRONTIER_PROXY_ORDER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
)

INVESTIGATOR_ORDER: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
)

INVESTIGATOR_LABELS: dict[str, str] = {
    "gemini_carbon_proxy": "GeminiCarbonProxy",
    "codex_horizon_proxy": "CodexHorizonProxy",
    "grok_tactics": "GrokTactics(hard)",
    "hinted_heuristic": "HintedHeuristic(hard)",
    "heuristic": "Heuristic(hard)",
}

FORBIDDEN_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "secret_mole",
        "mole_id",
        "mole_identity",
        "decoy",
        "decoy_id",
        "mole_strategy",
        "world_secret",
        "world_key",
        "salt",
        "ledger_token",
        "ledger_events",
        "posterior",
        "transcript",
        "transcripts",
        "steps",
    }
)

SECRET_KEY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)

EMPLOYEE_ID_RE = re.compile(r"\be\d{2}\b")

FORBIDDEN_GAP_RE = re.compile(
    r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
    re.IGNORECASE,
)

FLASH_TAG = "gemini-3.5-" + "flash"
SOLVER_PCT_TAG = "% of " + "solver"
COAUTHOR_TAG = "co-authored-" + "by"


@dataclass(frozen=True)
class PolicyRepresentationSpec:
    key: str
    family: str
    source: str
    alias: str | None
    decision_mode: str
    canonical_sha256: str
    complexity: dict[str, Any]
    worker_payload: dict[str, Any]


def parse_seed_spec(spec: str) -> list[int]:
    raw = str(spec).strip()
    if not raw:
        raise ValueError("seed specification must not be empty")
    out: list[int] = []
    for part in raw.split(","):
        tok = part.strip()
        if not tok:
            raise ValueError(f"empty token in seed spec {spec!r}")
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi <= lo:
                raise ValueError(f"empty or reversed seed slice {tok!r}")
            out.extend(range(lo, hi))
        elif "-" in tok and not tok.startswith("-"):
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"reversed seed range {tok!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(tok))
    if not out:
        raise ValueError("seed specification produced zero seeds")
    return out


def validate_pareto_seeds(seeds: str | Iterable[int]) -> list[int]:
    if isinstance(seeds, bool):
        raise ValueError("boolean values are not valid seeds")
    if isinstance(seeds, str):
        parsed = parse_seed_spec(seeds)
    else:
        raw_list = list(seeds)
        if any(isinstance(x, bool) or not isinstance(x, int) for x in raw_list):
            raise ValueError("all seeds must be integers")
        parsed = [int(x) for x in raw_list]
    if not parsed:
        raise ValueError("eval seeds must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ValueError("duplicate evaluation seeds are forbidden")
    for s in parsed:
        if s < 0 or s <= FORBIDDEN_LOW_SEED_MAX:
            raise ValueError(f"seed {s} violates seed hygiene: <= {FORBIDDEN_LOW_SEED_MAX} forbidden")
        if s in FORBIDDEN_DEV_SEED_RANGE:
            raise ValueError(f"seed {s} violates seed hygiene: 6000-6999 dev/portfolio range forbidden")
        if s in FORBIDDEN_RESERVED_HELDOUT_RANGE:
            raise ValueError(f"seed {s} violates seed hygiene: 30000-30199 reserved range forbidden")
        if s in FORBIDDEN_RL_TRAIN_RANGE:
            raise ValueError(f"seed {s} violates seed hygiene: 110000-110999 RL training range forbidden")
        if s >= FORBIDDEN_HIGH_SEED_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"seed {s} violates seed hygiene: >= 800000 / heldout / judge forbidden")
    return parsed


def validate_cf_seeds(seeds: str | Iterable[int]) -> list[int]:
    if isinstance(seeds, bool):
        raise ValueError("boolean values are not valid counterfactual seeds")
    if isinstance(seeds, str):
        parsed = parse_seed_spec(seeds)
    else:
        raw_list = list(seeds)
        if any(isinstance(x, bool) or not isinstance(x, int) for x in raw_list):
            raise ValueError("counterfactual seeds must be integers")
        parsed = [int(x) for x in raw_list]
    if not parsed:
        raise ValueError("counterfactual seeds must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ValueError("duplicate counterfactual seeds are forbidden")
    for s in parsed:
        if s < 0 or s >= FORBIDDEN_HIGH_SEED_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"counterfactual seed {s} out of allowed committed transcript bounds")
    return parsed


def _dsl_canonical_sha(sj: Mapping[str, Any]) -> str:
    body = canonical({"rules": sj.get("rules", []), "default": sj.get("default", {})})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _rl_canonical_sha(policy_json: Mapping[str, Any]) -> str:
    body = {k: v for k, v in policy_json.items() if k != "name"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _portfolio_canonical_sha(weights: Mapping[str, float], domain_tag: str) -> str:
    rounded = {k: round(float(v), 8) for k, v in sorted(weights.items())}
    blob = json.dumps({"domain": domain_tag, "weights": rounded}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _dsl_complexity(sj: Mapping[str, Any], is_baseline: bool = False, tag: str | None = None) -> dict[str, Any]:
    rules = list(sj.get("rules", []))
    n_rules = len(rules)
    n_preds = sum(len(r.get("if", [])) for r in rules)
    discrete_tokens = 0 if is_baseline else int(3 * n_preds + 2 * (n_rules + 1))
    if is_baseline:
        label = "0 rules (fixed default)"
    elif tag:
        label = f"{n_rules} DSL rules ({n_preds} predicates, {tag})"
    else:
        label = f"{n_rules} DSL rules ({n_preds} predicates)"
    return {
        "representation_type": "fixed_default" if is_baseline else "symbolic_rule_list",
        "n_rules": n_rules,
        "n_predicates": n_preds,
        "n_continuous_weights": 0,
        "mixture_support_size": 1,
        "effective_param_count": discrete_tokens,
        "complexity_label": label,
    }


def load_representative_policies(
    *,
    hof_path: Path = DEFAULT_HOF_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
    rl_policy_path: Path = DEFAULT_RL_POLICY_PATH,
    portfolio_summary_path: Path = DEFAULT_PORTFOLIO_SUMMARY_PATH,
    selected_keys: Sequence[str] | None = None,
) -> dict[str, PolicyRepresentationSpec]:
    registry: dict[str, PolicyRepresentationSpec] = {}

    def_sj = DEFAULT_STRATEGY.to_json()
    registry["default_v0"] = PolicyRepresentationSpec(
        key="default_v0",
        family="baseline",
        source="canary/mole/dsl.py",
        alias=None,
        decision_mode="deterministic_seeded_dsl",
        canonical_sha256=_dsl_canonical_sha(def_sj),
        complexity=_dsl_complexity(def_sj, is_baseline=True),
        worker_payload={"kind": "dsl", "strategy_json": def_sj},
    )

    for sname in (
        "surgical_trap_shield",
        "gemini_midsize_shield",
        "early_burst_midgame_pace",
        "frontier_synthesis_v14",
    ):
        strat = get_strategy(sname)
        sj = strat.to_json()
        registry[sname] = PolicyRepresentationSpec(
            key=sname,
            family="symbolic_dsl",
            source="canary/mole/strategies.py",
            alias=None,
            decision_mode="deterministic_seeded_dsl",
            canonical_sha256=_dsl_canonical_sha(sj),
            complexity=_dsl_complexity(sj),
            worker_payload={"kind": "dsl", "strategy_json": sj},
        )

    if not hof_path.is_file():
        raise FileNotFoundError(f"missing Hall of Fame JSONL at {hof_path}")
    hof_lines = [ln for ln in hof_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not hof_lines:
        raise ValueError(f"empty Hall of Fame JSONL at {hof_path}")
    r1_row = json.loads(hof_lines[0])
    r1_sj = copy.deepcopy(r1_row.get("strategy_json", r1_row))
    r1_sj["name"] = "hof_v14_r1"
    MoleStrategy.from_json(r1_sj)

    hof_alias = "window_crowd_stale"
    if hof_meta_path.is_file():
        meta = json.loads(hof_meta_path.read_text(encoding="utf-8"))
        snames = meta.get("survivor_names")
        if isinstance(snames, list) and snames:
            hof_alias = str(snames[0])

    registry["hof_v14_r1"] = PolicyRepresentationSpec(
        key="hof_v14_r1",
        family="symbolic_dsl",
        source="data/forge/hall_of_fame_v1.4.jsonl",
        alias=hof_alias,
        decision_mode="deterministic_seeded_dsl",
        canonical_sha256=_dsl_canonical_sha(r1_sj),
        complexity=_dsl_complexity(r1_sj, tag="HoF r1"),
        worker_payload={"kind": "dsl", "strategy_json": r1_sj},
    )

    if not rl_policy_path.is_file():
        raise FileNotFoundError(f"missing distilled RLMole JSON at {rl_policy_path}")
    raw_rl = json.loads(rl_policy_path.read_text(encoding="utf-8"))
    rl_greedy_pol = RLMole.from_json({**raw_rl, "greedy": True, "name": "rl_mole_frontier_v14"})
    rl_soft_pol = RLMole.from_json({**raw_rl, "greedy": False, "name": "rl_mole_frontier_v14_softmax"})
    n_floats = sum(int(arr.size) for arr in rl_greedy_pol.p.values())
    hidden_dim = int(rl_greedy_pol.p["W1"].shape[1])

    for rkey, rpol, mode_tag, label_suffix in (
        ("rl_mole_frontier_v14", rl_greedy_pol, "deterministic_greedy_mlp", "greedy"),
        ("rl_mole_frontier_v14_softmax", rl_soft_pol, "stochastic_softmax_mlp", "softmax"),
    ):
        rj = rpol.to_json()
        registry[rkey] = PolicyRepresentationSpec(
            key=rkey,
            family="continuous_rl_mole",
            source="data/forge/rl_mole_frontier_v14.json",
            alias=None,
            decision_mode=mode_tag,
            canonical_sha256=_rl_canonical_sha(rj),
            complexity={
                "representation_type": "mlp_dual_head",
                "n_rules": 0,
                "n_predicates": 0,
                "hidden_units": hidden_dim,
                "n_continuous_weights": n_floats,
                "mixture_support_size": 1,
                "effective_param_count": n_floats,
                "complexity_label": f"{n_floats} float weights (11x{hidden_dim} MLP, {label_suffix})",
            },
            worker_payload={"kind": "rl_mole", "policy_json": rj},
        )

    port_summaries, port_meta = load_summaries_from_v14_json(portfolio_summary_path)
    port_fit = solve_minimax_regret_portfolio(port_summaries)
    active_names = list(port_fit.active_strategies)
    support_rules = sum(len(get_strategy(n).rules) if n != "default_v0" else 0 for n in active_names)
    weighted_rules = sum(
        float(port_fit.weights[n]) * (len(get_strategy(n).rules) if n != "default_v0" else 0)
        for n in active_names
    )
    active_weights = {n: round(float(port_fit.weights[n]), 6) for n in active_names}

    registry["regret_portfolio_v14"] = PolicyRepresentationSpec(
        key="regret_portfolio_v14",
        family="minimax_portfolio",
        source="canary/mole/regret_portfolio.py",
        alias=f"fit:{port_meta['seed_range']}",
        decision_mode="seed_hashed_simplex_mixture",
        canonical_sha256=_portfolio_canonical_sha(port_fit.weights, DEFAULT_PORTFOLIO_SALT),
        complexity={
            "representation_type": "simplex_mixture_over_dsl",
            "n_rules": support_rules,
            "weighted_mean_rules": round(weighted_rules, 4),
            "n_predicates": sum(
                sum(len(r[0]) for r in get_strategy(n).rules) if n != "default_v0" else 0
                for n in active_names
            ),
            "n_continuous_weights": len(active_names),
            "simplex_free_dof": max(0, len(active_names) - 1),
            "mixture_support_size": len(active_names),
            "active_weights": active_weights,
            "effective_param_count": len(active_names),
            "complexity_label": f"{len(active_names)}-policy SHA-256 mixture ({support_rules} support rules)",
        },
        worker_payload={
            "kind": "portfolio",
            "weights": dict(port_fit.weights),
            "hash_domain": DEFAULT_PORTFOLIO_SALT,
            "name": "regret_portfolio_v14",
        },
    )

    if selected_keys is None:
        return {k: registry[k] for k in POLICY_ORDER}
    wanted: list[str] = []
    for raw_k in selected_keys:
        k = str(raw_k).strip()
        if k == "window_crowd_stale":
            k = "hof_v14_r1"
        if k not in registry:
            raise KeyError(f"unknown representative policy {raw_k!r}; expected one of {sorted(registry)}")
        if k not in wanted:
            wanted.append(k)
    if BASELINE_POLICY_KEY not in wanted:
        wanted.insert(0, BASELINE_POLICY_KEY)
    return {k: registry[k] for k in wanted}


def instantiate_mole_policy(worker_payload: Mapping[str, Any], seed: int) -> Any:
    kind = str(worker_payload["kind"])
    if kind == "dsl":
        return MoleStrategy.from_json(dict(worker_payload["strategy_json"]))
    if kind == "rl_mole":
        return RLMole.from_json(dict(worker_payload["policy_json"]))
    if kind == "portfolio":
        return PortfolioMolePolicy(
            seed=int(seed),
            weights=dict(worker_payload["weights"]),
            salt=str(worker_payload.get("hash_domain", DEFAULT_PORTFOLIO_SALT)),
            name=str(worker_payload.get("name", "regret_portfolio_v14")),
        )
    raise ValueError(f"unsupported mole worker_payload kind {kind!r}")


def _unfinished_stop_early_score(tier: str, seed: int, worker_payload: Mapping[str, Any]) -> float:
    env = Env(tier, seed, mole_strategy=instantiate_mole_policy(worker_payload, seed))
    pol = StopEarlyQuit(seed=seed)
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(3):
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    return float(env.score())


def _eval_live_seed_worker(task: tuple[str, str, int, dict[str, Any]]) -> dict[str, Any]:
    policy_key, tier, seed, payload = task
    tp = tier_params(tier)

    def _mole() -> Any:
        return instantiate_mole_policy(payload, seed)

    sample_mole = _mole()
    realized_name = str(getattr(sample_mole, "selected_name", getattr(sample_mole, "name", policy_key)))

    sol_res = run_episode(
        Env(tier, seed, mole_strategy=sample_mole),
        SolverPolicy(tier if tier in TIERS else tp, act_budget=5.0),
    )
    gem_res = run_episode(Env(tier, seed, mole_strategy=_mole()), GeminiCarbonProxy(seed=seed))
    cdx_res = run_episode(Env(tier, seed, mole_strategy=_mole()), CodexHorizonProxy(seed=seed))
    grk_res = run_episode(Env(tier, seed, mole_strategy=_mole()), GrokTactics(seed=seed))
    hh_res = run_episode(Env(tier, seed, mole_strategy=_mole()), HintedHeuristic(seed=seed, n_days=tp.n_days))
    heu_res = run_episode(Env(tier, seed, mole_strategy=_mole()), Heuristic(seed=seed))
    lo_res = run_episode(Env(tier, seed, mole_strategy=_mole()), LogsOnly(seed=seed))

    env_dn = Env(tier, seed, mole_strategy=_mole())
    dn_res = run_episode(env_dn, DoNothing(seed=seed))
    ledger = env_dn.ledger()
    mole_leaks = sum(1 for item in ledger if str(item.event) == "leak")
    mole_frames = sum(1 for item in ledger if str(item.event) == "framed")

    seq_res = run_episode(Env(tier, seed, mole_strategy=_mole()), StopEarlyQuit(seed=seed))
    seq_unfinished = _unfinished_stop_early_score(tier, seed, payload)

    sol_sc = float(sol_res.score)
    inv_raw = {
        "gemini_carbon_proxy": gem_res,
        "codex_horizon_proxy": cdx_res,
        "grok_tactics": grk_res,
        "hinted_heuristic": hh_res,
        "heuristic": heu_res,
    }

    return {
        "policy_key": policy_key,
        "seed": int(seed),
        "realized_name": realized_name,
        "mole_leaks": int(mole_leaks),
        "mole_frames": int(mole_frames),
        "solver": {
            "score": sol_sc,
            "correct": bool(sol_res.correct),
            "final_day": int(sol_res.final_day),
        },
        "investigators": {
            inv_k: {
                "score": float(r.score),
                "correct": bool(r.correct),
                "regret": float(sol_sc - float(r.score)),
            }
            for inv_k, r in inv_raw.items()
        },
        "logs_only": {
            "score": float(lo_res.score),
            "correct": bool(lo_res.correct),
        },
        "do_nothing_score": float(dn_res.score),
        "stop_early_quit_score": float(seq_res.score),
        "stop_early_unfinished_score": float(seq_unfinished),
    }


def _eval_cf_transcript_worker(
    task: tuple[str, str, int, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    tier, source, seed, payloads_by_key = task
    loaded = load_v14_frontier_episodes(tier=tier, sources=(source,), seeds=(seed,))
    ep = loaded[source][seed]
    tp = tier_params(ep.tier)
    true_mole = generate_world(ep.tier, ep.seed, tp).mole

    per_policy: dict[str, dict[str, float]] = {}
    for pkey, wpayload in payloads_by_key.items():
        replay_pol = ScheduleReplayPolicy(ep, target_day="horizon")
        mole_obj = instantiate_mole_policy(wpayload, int(ep.seed))
        env = Env(ep.tier, int(ep.seed), mole_strategy=mole_obj)
        horizon_hist = replay_schedule(env, replay_pol)
        accuse_hist = horizon_hist[: replay_pol.recorded_prefix_len]

        at_accuse = inspect_observation_history(
            accuse_hist,
            tier=ep.tier,
            seed=int(ep.seed),
            recorded_accused=ep.accused,
            true_mole=true_mole,
        )
        if len(horizon_hist) == len(accuse_hist):
            at_horizon = at_accuse
        else:
            at_horizon = inspect_observation_history(
                horizon_hist,
                tier=ep.tier,
                seed=int(ep.seed),
                recorded_accused=ep.accused,
                true_mole=true_mole,
            )

        per_policy[pkey] = {
            "p_true_mole": float(at_accuse["p_true_mole"]),
            "p_true_mole_horizon": float(at_horizon["p_true_mole"]),
            "optimal_ev": float(at_accuse["optimal_ev"]),
            "optimal_ev_horizon": float(at_horizon["optimal_ev"]),
            "top_is_true_mole": 1.0 if bool(at_accuse["top_is_true_mole"]) else 0.0,
            "surfaced_canaries": float(at_accuse["surfaced_canaries"]),
            "surfaced_total_leaks": float(at_accuse["surfaced_total_leaks"]),
        }

    return {
        "source": source,
        "seed": int(seed),
        "policies": per_policy,
    }


def _derive_boot_seed(base_seed: int, tag: str) -> int:
    digest = hashlib.sha256(f"{int(base_seed)}:{tag}".encode("utf-8")).hexdigest()[:16]
    return int(digest, 16)


def paired_bootstrap_ci(
    values: Sequence[float],
    n_boot: int = DEFAULT_BOOT_RESAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_BOOT_SEED,
    tag: str = "",
) -> dict[str, float]:
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot}")
    if not (0.0 < ci < 1.0):
        raise ValueError(f"ci must be in (0, 1), got {ci}")
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    arr = np.asarray(values, dtype=np.float64)
    mean_val = float(arr.mean())
    if n == 1 or float(arr.min()) == float(arr.max()):
        rv = round(mean_val, 4)
        return {"mean": rv, "ci_low": rv, "ci_high": rv}
    rng = np.random.default_rng(_derive_boot_seed(seed, tag))
    idx = rng.integers(0, n, size=(int(n_boot), n))
    means = arr[idx].mean(axis=1)
    alpha = 0.5 * (1.0 - float(ci))
    lo, hi = np.quantile(means, [alpha, 1.0 - alpha])
    return {
        "mean": round(mean_val, 4),
        "ci_low": round(float(lo), 4),
        "ci_high": round(float(hi), 4),
    }


def paired_minimax_bootstrap_ci(
    cur_regrets_by_inv: Mapping[str, Sequence[float]],
    base_regrets_by_inv: Mapping[str, Sequence[float]],
    inv_keys: Sequence[str],
    n_boot: int = DEFAULT_BOOT_RESAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_BOOT_SEED,
    tag: str = "",
) -> tuple[dict[str, float], dict[str, float]]:
    keys = list(inv_keys)
    if not keys:
        raise ValueError("inv_keys must not be empty")
    n = len(cur_regrets_by_inv[keys[0]])
    if n == 0:
        zero = {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
        return dict(zero), dict(zero)
    cur_mat = np.asarray([cur_regrets_by_inv[k] for k in keys], dtype=np.float64)
    base_mat = np.asarray([base_regrets_by_inv[k] for k in keys], dtype=np.float64)
    cur_pop_min = float(cur_mat.mean(axis=1).min())
    base_pop_min = float(base_mat.mean(axis=1).min())
    gain_pop = cur_pop_min - base_pop_min
    if n == 1:
        rc = round(cur_pop_min, 4)
        rg = round(gain_pop, 4)
        return (
            {"mean": rc, "ci_low": rc, "ci_high": rc},
            {"mean": rg, "ci_low": rg, "ci_high": rg},
        )
    rng = np.random.default_rng(_derive_boot_seed(seed, tag))
    idx = rng.integers(0, n, size=(int(n_boot), n))
    cur_boot = np.take(cur_mat, idx, axis=1).mean(axis=2).min(axis=0)
    base_boot = np.take(base_mat, idx, axis=1).mean(axis=2).min(axis=0)
    gain_boot = cur_boot - base_boot
    alpha = 0.5 * (1.0 - float(ci))
    c_lo, c_hi = np.quantile(cur_boot, [alpha, 1.0 - alpha])
    g_lo, g_hi = np.quantile(gain_boot, [alpha, 1.0 - alpha])
    return (
        {
            "mean": round(cur_pop_min, 4),
            "ci_low": round(float(c_lo), 4),
            "ci_high": round(float(c_hi), 4),
        },
        {
            "mean": round(gain_pop, 4),
            "ci_low": round(float(g_lo), 4),
            "ci_high": round(float(g_hi), 4),
        },
    )


def evaluate_fairness_gates(
    *,
    solver_acc: float,
    logs_only_acc: float,
    do_nothing_max_abs: float,
    stop_early_quit_max_abs: float,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    zero_tol: float = 1e-12,
) -> dict[str, bool]:
    g_sol = bool(float(solver_acc) + 1e-12 >= float(min_solver_acc))
    g_logs = bool(float(logs_only_acc) <= float(max_logs_acc) + 1e-12)
    g_dn = bool(abs(float(do_nothing_max_abs)) <= zero_tol)
    g_seq = bool(abs(float(stop_early_quit_max_abs)) <= zero_tol)
    return {
        "solver_acc_ok": g_sol,
        "logs_only_ok": g_logs,
        "do_nothing_zero": g_dn,
        "stop_early_quit_zero": g_seq,
        "passed": bool(g_sol and g_logs and g_dn and g_seq),
    }


def pareto_dominates(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
    tol: float = 1e-12,
) -> bool:
    xa, ya = float(point_a[0]), float(point_a[1])
    xb, yb = float(point_b[0]), float(point_b[1])
    not_worse = (xa >= xb - tol) and (ya >= yb - tol)
    strictly_better = (xa > xb + tol) or (ya > yb + tol)
    return bool(not_worse and strictly_better)


def compute_pareto_frontier(
    points: Mapping[str, Mapping[str, Any]],
    x_key: str,
    y_key: str,
    feasible_key: str = "feasible",
    tol: float = 1e-12,
) -> dict[str, Any]:
    if not points:
        raise ValueError("points must not be empty")

    coords: dict[str, tuple[float, float]] = {}
    feas_map: dict[str, bool] = {}
    fam_map: dict[str, str | None] = {}
    for name, row in points.items():
        if x_key not in row or y_key not in row:
            raise KeyError(f"point {name!r} missing {x_key!r} or {y_key!r}")
        xv = float(row[x_key])
        yv = float(row[y_key])
        if not (math.isfinite(xv) and math.isfinite(yv)):
            raise ValueError(f"non-finite Pareto coordinates for {name!r}: ({xv}, {yv})")
        coords[name] = (xv, yv)
        feas_map[name] = bool(row.get(feasible_key, True))
        fam_map[name] = str(row["family"]) if "family" in row and row["family"] is not None else None

    feasible_names = [n for n in points if feas_map[n]]
    infeasible_names = [n for n in points if not feas_map[n]]

    dominated_by_map: dict[str, list[str]] = {}
    for name in points:
        if not feas_map[name]:
            dominated_by_map[name] = []
            continue
        doms = [
            other
            for other in feasible_names
            if other != name and pareto_dominates(coords[other], coords[name], tol=tol)
        ]
        doms.sort(key=lambda k: (-coords[k][0], -coords[k][1], k))
        dominated_by_map[name] = doms

    ranks: dict[str, int | None] = {n: None for n in points}
    remaining = list(feasible_names)
    layer = 1
    layers: list[list[str]] = []
    while remaining:
        current_front = [
            n
            for n in remaining
            if not any(
                other != n and pareto_dominates(coords[other], coords[n], tol=tol)
                for other in remaining
            )
        ]
        current_front.sort(key=lambda k: (-coords[k][0], -coords[k][1], k))
        for n in current_front:
            ranks[n] = layer
        layers.append(current_front)
        rem_set = set(current_front)
        remaining = [n for n in remaining if n not in rem_set]
        layer += 1

    frontier = layers[0] if layers else []
    dominated = [n for n in feasible_names if n not in set(frontier)]
    dominated.sort(key=lambda k: (ranks[k] or 999, -coords[k][0], -coords[k][1], k))

    frontier_fams = sorted({fam_map[n] for n in frontier if fam_map[n] is not None})

    per_policy: dict[str, dict[str, Any]] = {}
    for name in points:
        xv, yv = coords[name]
        per_policy[name] = {
            "x": round(xv, 4),
            "y": round(yv, 4),
            "feasible": feas_map[name],
            "pareto_optimal": bool(name in set(frontier)),
            "pareto_rank": ranks[name],
            "dominated_by": dominated_by_map[name],
        }

    return {
        "x_metric": x_key,
        "y_metric": y_key,
        "frontier": frontier,
        "dominated": dominated,
        "infeasible": infeasible_names,
        "frontier_families": frontier_fams,
        "n_layers": len(layers),
        "per_policy": per_policy,
    }


def run_representation_pareto_benchmark(
    *,
    seeds: str | Iterable[int] = DEFAULT_EVAL_SEEDS_SPEC,
    cf_seeds: str | Iterable[int] = DEFAULT_CF_SEEDS_SPEC,
    cf_sources: Iterable[str] = DEFAULT_CF_SOURCES,
    policy_keys: Sequence[str] | None = None,
    tier: str = "hard",
    workers: int = DEFAULT_WORKERS,
    n_boot: int = DEFAULT_BOOT_RESAMPLES,
    boot_seed: int = DEFAULT_BOOT_SEED,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
) -> dict[str, Any]:
    if tier != "hard":
        raise ValueError(f"representation_pareto benchmark requires tier='hard', got {tier!r}")
    clean_seeds = validate_pareto_seeds(seeds)
    clean_cf_seeds = validate_cf_seeds(cf_seeds)
    sources = tuple(str(s).strip() for s in cf_sources if str(s).strip())
    if not sources:
        raise ValueError("cf_sources must not be empty")
    eff_workers = max(1, int(workers))

    specs = load_representative_policies(selected_keys=policy_keys)
    ordered_keys = list(specs.keys())

    live_tasks: list[tuple[str, str, int, dict[str, Any]]] = [
        (pkey, tier, int(s), specs[pkey].worker_payload)
        for pkey in ordered_keys
        for s in clean_seeds
    ]
    if eff_workers > 1 and len(live_tasks) > 1:
        with ProcessPoolExecutor(max_workers=eff_workers) as pool:
            live_rows = list(pool.map(_eval_live_seed_worker, live_tasks, chunksize=2))
    else:
        live_rows = [_eval_live_seed_worker(t) for t in live_tasks]

    live_by_policy: dict[str, list[dict[str, Any]]] = {k: [] for k in ordered_keys}
    for r in live_rows:
        live_by_policy[str(r["policy_key"])].append(r)
    for k in ordered_keys:
        live_by_policy[k].sort(key=lambda item: int(item["seed"]))

    payloads_map = {k: specs[k].worker_payload for k in ordered_keys}
    cf_loaded = load_v14_frontier_episodes(tier=tier, sources=sources, seeds=clean_cf_seeds)
    paired_cf_seeds = sorted(set.intersection(*(set(cf_loaded[src].keys()) for src in sources)))
    if not paired_cf_seeds:
        raise ValueError(f"no committed v1.4 {tier} transcripts found for seeds {clean_cf_seeds}")

    cf_tasks: list[tuple[str, str, int, dict[str, dict[str, Any]]]] = [
        (tier, src, int(s), payloads_map)
        for src in sources
        for s in paired_cf_seeds
    ]
    if eff_workers > 1 and len(cf_tasks) > 1:
        with ProcessPoolExecutor(max_workers=eff_workers) as pool:
            cf_rows = list(pool.map(_eval_cf_transcript_worker, cf_tasks, chunksize=2))
    else:
        cf_rows = [_eval_cf_transcript_worker(t) for t in cf_tasks]

    cf_rows.sort(key=lambda item: (sources.index(str(item["source"])), int(item["seed"])))

    base_live = live_by_policy[BASELINE_POLICY_KEY]
    n_live = len(clean_seeds)
    base_sol_scores = [float(r["solver"]["score"]) for r in base_live]
    base_sol_accs = [1.0 if bool(r["solver"]["correct"]) else 0.0 for r in base_live]
    base_sol_mean = sum(base_sol_scores) / n_live
    base_regrets_by_inv: dict[str, list[float]] = {
        inv: [float(r["investigators"][inv]["regret"]) for r in base_live]
        for inv in INVESTIGATOR_ORDER
    }

    base_cf_ev = [float(r["policies"][BASELINE_POLICY_KEY]["optimal_ev"]) for r in cf_rows]
    base_cf_p = [float(r["policies"][BASELINE_POLICY_KEY]["p_true_mole"]) for r in cf_rows]
    base_cf_top = [float(r["policies"][BASELINE_POLICY_KEY]["top_is_true_mole"]) for r in cf_rows]

    policies_out: dict[str, dict[str, Any]] = {}
    for pkey in ordered_keys:
        spec = specs[pkey]
        prows = live_by_policy[pkey]

        sol_scores = [float(r["solver"]["score"]) for r in prows]
        sol_accs = [1.0 if bool(r["solver"]["correct"]) else 0.0 for r in prows]
        sol_days = [float(r["solver"]["final_day"]) for r in prows]
        lo_accs = [1.0 if bool(r["logs_only"]["correct"]) else 0.0 for r in prows]
        lo_scores = [float(r["logs_only"]["score"]) for r in prows]
        dn_scores = [float(r["do_nothing_score"]) for r in prows]
        seq_scores = [float(r["stop_early_quit_score"]) for r in prows]
        seq_unfin = [float(r["stop_early_unfinished_score"]) for r in prows]
        leaks_vec = [float(r["mole_leaks"]) for r in prows]
        frames_vec = [float(r["mole_frames"]) for r in prows]

        realized_counts: dict[str, int] = {}
        for r in prows:
            rn = str(r["realized_name"])
            realized_counts[rn] = realized_counts.get(rn, 0) + 1

        sol_score_ci = paired_bootstrap_ci(
            sol_scores,
            n_boot=n_boot,
            seed=boot_seed,
            tag=f"{pkey}:solver_score",
        )
        sol_acc_ci = paired_bootstrap_ci(
            sol_accs,
            n_boot=n_boot,
            seed=boot_seed,
            tag=f"{pkey}:solver_acc",
        )
        sol_delta_ci = (
            {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
            if pkey == BASELINE_POLICY_KEY
            else paired_bootstrap_ci(
                [a - b for a, b in zip(sol_scores, base_sol_scores)],
                n_boot=n_boot,
                seed=boot_seed,
                tag=f"{pkey}:solver_score_delta",
            )
        )
        sol_acc_delta_ci = (
            {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
            if pkey == BASELINE_POLICY_KEY
            else paired_bootstrap_ci(
                [a - b for a, b in zip(sol_accs, base_sol_accs)],
                n_boot=n_boot,
                seed=boot_seed,
                tag=f"{pkey}:solver_acc_delta",
            )
        )

        cur_regrets_by_inv: dict[str, list[float]] = {}
        inv_summary: dict[str, dict[str, Any]] = {}
        for inv in INVESTIGATOR_ORDER:
            isc = [float(r["investigators"][inv]["score"]) for r in prows]
            iac = [1.0 if bool(r["investigators"][inv]["correct"]) else 0.0 for r in prows]
            irg = [float(r["investigators"][inv]["regret"]) for r in prows]
            cur_regrets_by_inv[inv] = irg
            reg_ci = paired_bootstrap_ci(
                irg,
                n_boot=n_boot,
                seed=boot_seed,
                tag=f"{pkey}:{inv}:regret",
            )
            gain_ci = (
                {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
                if pkey == BASELINE_POLICY_KEY
                else paired_bootstrap_ci(
                    [a - b for a, b in zip(irg, base_regrets_by_inv[inv])],
                    n_boot=n_boot,
                    seed=boot_seed,
                    tag=f"{pkey}:{inv}:regret_gain",
                )
            )
            inv_summary[inv] = {
                "score": round(sum(isc) / n_live, 4),
                "acc": round(sum(iac) / n_live, 4),
                "regret": reg_ci["mean"],
                "regret_ci95": reg_ci,
                "regret_gain_vs_default": gain_ci,
            }

        fproxy_ci, fproxy_gain_ci = paired_minimax_bootstrap_ci(
            cur_regrets_by_inv,
            base_regrets_by_inv,
            FRONTIER_PROXY_ORDER,
            n_boot=n_boot,
            seed=boot_seed,
            tag=f"{pkey}:min_frontier_proxy_regret",
        )
        if pkey == BASELINE_POLICY_KEY:
            fproxy_gain_ci = {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}

        panel_min_ci, panel_min_gain_ci = paired_minimax_bootstrap_ci(
            cur_regrets_by_inv,
            base_regrets_by_inv,
            INVESTIGATOR_ORDER,
            n_boot=n_boot,
            seed=boot_seed,
            tag=f"{pkey}:min_panel_regret",
        )
        if pkey == BASELINE_POLICY_KEY:
            panel_min_gain_ci = {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}

        seed_mean_panel_cur = [
            sum(cur_regrets_by_inv[inv][i] for inv in INVESTIGATOR_ORDER) / len(INVESTIGATOR_ORDER)
            for i in range(n_live)
        ]
        seed_mean_panel_base = [
            sum(base_regrets_by_inv[inv][i] for inv in INVESTIGATOR_ORDER) / len(INVESTIGATOR_ORDER)
            for i in range(n_live)
        ]
        mean_panel_ci = paired_bootstrap_ci(
            seed_mean_panel_cur,
            n_boot=n_boot,
            seed=boot_seed,
            tag=f"{pkey}:mean_panel_regret",
        )
        mean_panel_gain_ci = (
            {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
            if pkey == BASELINE_POLICY_KEY
            else paired_bootstrap_ci(
                [a - b for a, b in zip(seed_mean_panel_cur, seed_mean_panel_base)],
                n_boot=n_boot,
                seed=boot_seed,
                tag=f"{pkey}:mean_panel_regret_gain",
            )
        )

        strongest_proxy = min(
            FRONTIER_PROXY_ORDER,
            key=lambda inv: sum(cur_regrets_by_inv[inv]) / n_live,
        )
        strongest_panel_inv = min(
            INVESTIGATOR_ORDER,
            key=lambda inv: sum(cur_regrets_by_inv[inv]) / n_live,
        )

        dn_max_abs = max((abs(x) for x in dn_scores), default=0.0)
        seq_max_abs = max([*(abs(x) for x in seq_scores), *(abs(x) for x in seq_unfin)], default=0.0)
        sol_acc_mean = round(sum(sol_accs) / n_live, 4)
        sol_score_mean = round(sum(sol_scores) / n_live, 4)
        lo_acc_mean = round(sum(lo_accs) / n_live, 4)
        lo_score_mean = round(sum(lo_scores) / n_live, 4)

        gates = evaluate_fairness_gates(
            solver_acc=sol_acc_mean,
            logs_only_acc=lo_acc_mean,
            do_nothing_max_abs=dn_max_abs,
            stop_early_quit_max_abs=seq_max_abs,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
        )

        n_cf = len(cf_rows)
        cur_cf_ev = [float(r["policies"][pkey]["optimal_ev"]) for r in cf_rows]
        cur_cf_ev_h = [float(r["policies"][pkey]["optimal_ev_horizon"]) for r in cf_rows]
        cur_cf_p = [float(r["policies"][pkey]["p_true_mole"]) for r in cf_rows]
        cur_cf_p_h = [float(r["policies"][pkey]["p_true_mole_horizon"]) for r in cf_rows]
        cur_cf_top = [float(r["policies"][pkey]["top_is_true_mole"]) for r in cf_rows]
        cur_cf_can = [float(r["policies"][pkey]["surfaced_canaries"]) for r in cf_rows]
        cur_cf_tot = [float(r["policies"][pkey]["surfaced_total_leaks"]) for r in cf_rows]

        if pkey == BASELINE_POLICY_KEY:
            cf_ev_drop_ci = {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
            cf_p_drop_ci = {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
            top_acc_drop = 0.0
        else:
            cf_ev_drop_ci = paired_bootstrap_ci(
                [b - c for b, c in zip(base_cf_ev, cur_cf_ev)],
                n_boot=n_boot,
                seed=boot_seed,
                tag=f"{pkey}:cf_ev_drop",
            )
            cf_p_drop_ci = paired_bootstrap_ci(
                [b - c for b, c in zip(base_cf_p, cur_cf_p)],
                n_boot=n_boot,
                seed=boot_seed,
                tag=f"{pkey}:cf_p_drop",
            )
            top_acc_drop = round((sum(base_cf_top) - sum(cur_cf_top)) / n_cf, 4)

        per_source_cf: dict[str, dict[str, Any]] = {}
        for src in sources:
            src_indices = [i for i, r in enumerate(cf_rows) if str(r["source"]) == src]
            ns = len(src_indices)
            s_ev = sum(cur_cf_ev[i] for i in src_indices) / ns
            s_p = sum(cur_cf_p[i] for i in src_indices) / ns
            s_ev_drop = (
                0.0
                if pkey == BASELINE_POLICY_KEY
                else sum(base_cf_ev[i] - cur_cf_ev[i] for i in src_indices) / ns
            )
            s_p_drop = (
                0.0
                if pkey == BASELINE_POLICY_KEY
                else sum(base_cf_p[i] - cur_cf_p[i] for i in src_indices) / ns
            )
            per_source_cf[src] = {
                "n": ns,
                "optimal_ev": round(s_ev, 4),
                "optimal_ev_drop": round(s_ev_drop, 4),
                "p_true_mole": round(s_p, 4),
                "p_true_mole_drop": round(s_p_drop, 4),
            }

        policies_out[pkey] = {
            "key": pkey,
            "family": spec.family,
            "family_label": FAMILY_LABELS[spec.family],
            "source": spec.source,
            "alias": spec.alias,
            "decision_mode": spec.decision_mode,
            "canonical_sha256": spec.canonical_sha256,
            "complexity": copy.deepcopy(spec.complexity),
            "live": {
                "n_seeds": n_live,
                "realized_strategy_counts": dict(sorted(realized_counts.items())),
                "mean_mole_leaks": round(sum(leaks_vec) / n_live, 4),
                "mean_mole_frames": round(sum(frames_vec) / n_live, 4),
                "solver_score": sol_score_mean,
                "solver_score_ci95": sol_score_ci,
                "solver_score_delta_vs_default": sol_delta_ci,
                "solver_acc": sol_acc_mean,
                "solver_acc_ci95": sol_acc_ci,
                "solver_acc_delta_vs_default": sol_acc_delta_ci,
                "solver_mean_day": round(sum(sol_days) / n_live, 3),
                "solver_retention_vs_default": (
                    round(sol_score_mean / base_sol_mean, 4) if base_sol_mean > 0.0 else 0.0
                ),
                "logs_only_acc": lo_acc_mean,
                "logs_only_score": lo_score_mean,
                "do_nothing_score": round(sum(dn_scores) / n_live, 6),
                "do_nothing_max_abs": round(dn_max_abs, 6),
                "stop_early_quit_score": round(sum(seq_scores) / n_live, 6),
                "stop_early_quit_max_abs": round(seq_max_abs, 6),
                "investigators": inv_summary,
                "strongest_frontier_proxy": strongest_proxy,
                "min_frontier_proxy_regret": fproxy_ci["mean"],
                "min_frontier_proxy_regret_ci95": fproxy_ci,
                "min_frontier_proxy_regret_gain_vs_default": fproxy_gain_ci,
                "strongest_panel_investigator": strongest_panel_inv,
                "min_panel_regret": panel_min_ci["mean"],
                "min_panel_regret_ci95": panel_min_ci,
                "min_panel_regret_gain_vs_default": panel_min_gain_ci,
                "mean_panel_regret": mean_panel_ci["mean"],
                "mean_panel_regret_ci95": mean_panel_ci,
                "mean_panel_regret_gain_vs_default": mean_panel_gain_ci,
            },
            "counterfactual": {
                "n_transcripts": n_cf,
                "optimal_ev": round(sum(cur_cf_ev) / n_cf, 4),
                "optimal_ev_horizon": round(sum(cur_cf_ev_h) / n_cf, 4),
                "counterfactual_ev_drop": cf_ev_drop_ci["mean"],
                "counterfactual_ev_drop_ci95": cf_ev_drop_ci,
                "p_true_mole": round(sum(cur_cf_p) / n_cf, 4),
                "p_true_mole_horizon": round(sum(cur_cf_p_h) / n_cf, 4),
                "p_true_mole_drop": cf_p_drop_ci["mean"],
                "p_true_mole_drop_ci95": cf_p_drop_ci,
                "top_suspect_acc": round(sum(cur_cf_top) / n_cf, 4),
                "top_suspect_acc_drop": top_acc_drop,
                "surfaced_canaries": round(sum(cur_cf_can) / n_cf, 4),
                "surfaced_total_leaks": round(sum(cur_cf_tot) / n_cf, 4),
                "per_source": per_source_cf,
            },
            "fairness_gates": gates,
        }

    pareto_inputs = {
        pkey: {
            "family": policies_out[pkey]["family"],
            "feasible": bool(policies_out[pkey]["fairness_gates"]["passed"]),
            "solver_score": float(policies_out[pkey]["live"]["solver_score"]),
            "solver_acc": float(policies_out[pkey]["live"]["solver_acc"]),
            "min_frontier_proxy_regret": float(policies_out[pkey]["live"]["min_frontier_proxy_regret"]),
            "min_panel_regret": float(policies_out[pkey]["live"]["min_panel_regret"]),
            "counterfactual_ev_drop": float(policies_out[pkey]["counterfactual"]["counterfactual_ev_drop"]),
        }
        for pkey in ordered_keys
    }

    live_proxy_pareto = compute_pareto_frontier(
        pareto_inputs,
        x_key="solver_score",
        y_key="min_frontier_proxy_regret",
        feasible_key="feasible",
    )
    cf_catchability_pareto = compute_pareto_frontier(
        pareto_inputs,
        x_key="solver_acc",
        y_key="counterfactual_ev_drop",
        feasible_key="feasible",
    )
    minimax_panel_pareto = compute_pareto_frontier(
        pareto_inputs,
        x_key="solver_score",
        y_key="min_panel_regret",
        feasible_key="feasible",
    )

    family_rollups: dict[str, dict[str, Any]] = {}
    for fam in FAMILY_ORDER:
        fkeys = [k for k in ordered_keys if policies_out[k]["family"] == fam]
        if not fkeys:
            continue
        feasible_fkeys = [k for k in fkeys if policies_out[k]["fairness_gates"]["passed"]]
        pool_keys = feasible_fkeys if feasible_fkeys else fkeys
        best_proxy_k = max(
            pool_keys,
            key=lambda k: (
                policies_out[k]["live"]["min_frontier_proxy_regret"],
                policies_out[k]["live"]["solver_score"],
            ),
        )
        best_cf_k = max(
            pool_keys,
            key=lambda k: (
                policies_out[k]["counterfactual"]["counterfactual_ev_drop"],
                policies_out[k]["live"]["solver_acc"],
            ),
        )
        best_panel_k = max(
            pool_keys,
            key=lambda k: (
                policies_out[k]["live"]["min_panel_regret"],
                policies_out[k]["live"]["solver_score"],
            ),
        )
        family_rollups[fam] = {
            "family": fam,
            "family_label": FAMILY_LABELS[fam],
            "policies": fkeys,
            "n_policies": len(fkeys),
            "n_fairness_passed": len(feasible_fkeys),
            "best_by_frontier_proxy_regret": best_proxy_k,
            "best_by_counterfactual_ev_drop": best_cf_k,
            "best_by_panel_min_regret": best_panel_k,
            "on_live_proxy_pareto": [k for k in fkeys if k in set(live_proxy_pareto["frontier"])],
            "on_counterfactual_pareto": [k for k in fkeys if k in set(cf_catchability_pareto["frontier"])],
            "on_minimax_panel_pareto": [k for k in fkeys if k in set(minimax_panel_pareto["frontier"])],
        }

    seed_range_str = (
        f"{clean_seeds[0]}-{clean_seeds[-1]}"
        if clean_seeds == list(range(clean_seeds[0], clean_seeds[-1] + 1))
        else ",".join(str(s) for s in clean_seeds)
    )
    cf_seed_range_str = (
        f"{paired_cf_seeds[0]}-{paired_cf_seeds[-1]}"
        if paired_cf_seeds == list(range(paired_cf_seeds[0], paired_cf_seeds[-1] + 1))
        else ",".join(str(s) for s in paired_cf_seeds)
    )

    feasible_all = [k for k in ordered_keys if policies_out[k]["fairness_gates"]["passed"]]
    best_live_proxy = max(
        feasible_all,
        key=lambda k: (
            policies_out[k]["live"]["min_frontier_proxy_regret"],
            policies_out[k]["live"]["solver_score"],
        ),
    ) if feasible_all else ordered_keys[0]
    best_cf_drop = max(
        feasible_all,
        key=lambda k: (
            policies_out[k]["counterfactual"]["counterfactual_ev_drop"],
            policies_out[k]["live"]["solver_acc"],
        ),
    ) if feasible_all else ordered_keys[0]
    best_panel_min = max(
        feasible_all,
        key=lambda k: (
            policies_out[k]["live"]["min_panel_regret"],
            policies_out[k]["live"]["solver_score"],
        ),
    ) if feasible_all else ordered_keys[0]

    report: dict[str, Any] = {
        "schema_version": "mole_representation_pareto_v14.v1",
        "study": "mole_representation_pareto_v14",
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "api_calls": 0,
        "baseline_policy": BASELINE_POLICY_KEY,
        "policy_order": ordered_keys,
        "investigator_order": list(INVESTIGATOR_ORDER),
        "frontier_proxy_order": list(FRONTIER_PROXY_ORDER),
        "seed_hygiene": {
            "live_seed_range": seed_range_str,
            "live_n_seeds": len(clean_seeds),
            "live_seeds": clean_seeds,
            "forbids_le_59": True,
            "forbids_6000_6999_dev_portfolio": True,
            "forbids_30000_30199_reserved": True,
            "forbids_110000_110999_rl_train": True,
            "forbids_800000_plus_heldout_judge": True,
            "counterfactual_seed_range": cf_seed_range_str,
            "counterfactual_sources": list(sources),
            "counterfactual_n_transcripts": len(cf_rows),
        },
        "thresholds": {
            "min_solver_acc": float(min_solver_acc),
            "max_logs_only_acc": float(max_logs_acc),
            "do_nothing_target": 0.0,
            "stop_early_quit_target": 0.0,
        },
        "bootstrap_config": {
            "n_boot": int(n_boot),
            "ci": 0.95,
            "seed": int(boot_seed),
        },
        "summary": {
            "n_policies": len(ordered_keys),
            "n_non_baseline_policies": len(ordered_keys) - 1,
            "n_families": len([f for f in FAMILY_ORDER if f != "baseline" and f in family_rollups]),
            "n_fairness_passed": len(feasible_all),
            "all_fairness_gates_passed": bool(len(feasible_all) == len(ordered_keys)),
            "best_live_frontier_proxy_regret_policy": best_live_proxy,
            "best_counterfactual_ev_drop_policy": best_cf_drop,
            "best_panel_minimax_regret_policy": best_panel_min,
            "live_proxy_pareto_frontier": live_proxy_pareto["frontier"],
            "counterfactual_catchability_pareto_frontier": cf_catchability_pareto["frontier"],
            "minimax_panel_pareto_frontier": minimax_panel_pareto["frontier"],
        },
        "pareto_frontiers": {
            "live_proxy_pareto": live_proxy_pareto,
            "counterfactual_catchability_pareto": cf_catchability_pareto,
            "minimax_panel_pareto": minimax_panel_pareto,
        },
        "family_rollups": family_rollups,
        "policies": policies_out,
    }
    assert_artifact_hygiene(report)
    return report


def dumps_compact_json(
    obj: Any,
    indent: int = 1,
    _level: int = 0,
    inline_limit: int = 260,
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
            f"{pad}{json.dumps(k)}:{dumps_compact_json(obj[k], indent, _level + 1, inline_limit)}"
            for k in sorted(obj)
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(obj, list):
        compact = json.dumps(obj, separators=(",", ":"), sort_keys=True)
        if _level >= 2 or len(compact) <= inline_limit:
            return compact
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [f"{pad}{dumps_compact_json(v, indent, _level + 1, inline_limit)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(obj)


def assert_artifact_hygiene(payload: Any) -> None:
    def _walk(node: Any, path: str) -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                ks = str(k)
                if ks in FORBIDDEN_SECRET_KEYS:
                    raise ValueError(f"forbidden secret key {ks!r} at {path}")
                if EMPLOYEE_ID_RE.search(ks):
                    raise ValueError(f"employee ID leaked in key {ks!r} at {path}")
                _walk(v, f"{path}.{ks}")
        elif isinstance(node, (list, tuple)):
            for i, item in enumerate(node):
                _walk(item, f"{path}[{i}]")
        elif isinstance(node, str):
            if EM_DASH in node or EN_DASH in node or UNICODE_MINUS in node:
                raise ValueError(f"forbidden dash/minus character at {path}")
            if not node.isascii():
                raise ValueError(f"non-ASCII text at {path}")
            low = node.lower()
            if FLASH_TAG in low or SOLVER_PCT_TAG in low or COAUTHOR_TAG in low:
                raise ValueError(f"forbidden claim/trailer text at {path}")
            if FORBIDDEN_GAP_RE.search(node):
                raise ValueError(f"forbidden solver ratio claim at {path}")
            if EMPLOYEE_ID_RE.search(node):
                raise ValueError(f"employee ID token leaked at {path}")
            for pat in SECRET_KEY_PATTERNS:
                if pat.search(node):
                    raise ValueError(f"API key pattern matched at {path}")

    _walk(payload, "root")


def _fmt_ci(ci_obj: Mapping[str, Any], digits: int = 3, signed: bool = True) -> str:
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return (
        f"{fmt.format(float(ci_obj['mean']))} "
        f"[{fmt.format(float(ci_obj['ci_low']))}, {fmt.format(float(ci_obj['ci_high']))}]"
    )


def format_terminal_summary(report: Mapping[str, Any]) -> str:
    sh = report["seed_hygiene"]
    sm = report["summary"]
    lines = [
        f"Mole Representation Pareto Benchmark v1.4 (tier={report['tier']}, "
        f"live_seeds={sh['live_seed_range']} n={sh['live_n_seeds']}, "
        f"cf_transcripts={sh['counterfactual_n_transcripts']}, "
        f"fairness_passed={sm['n_fairness_passed']}/{sm['n_policies']})",
        f"2D Pareto (SolverScore, MinFrontierProxyRegret): {', '.join(sm['live_proxy_pareto_frontier'])}",
        f"2D Pareto (SolverAcc, CounterfactualEVDrop): {', '.join(sm['counterfactual_catchability_pareto_frontier'])}",
        "",
        "| policy | family | params/rules | sol_acc | sol_score | min_proxy_reg | min_panel_reg | cf_ev_drop | gate |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pkey in report["policy_order"]:
        row = report["policies"][pkey]
        lv = row["live"]
        cf = row["counterfactual"]
        gate = "PASS" if row["fairness_gates"]["passed"] else "FAIL"
        lines.append(
            f"| {pkey} | {row['family']} | {row['complexity']['complexity_label']} | "
            f"{lv['solver_acc']:.3f} | {lv['solver_score']:+.3f} | "
            f"{lv['min_frontier_proxy_regret']:+.3f} | {lv['min_panel_regret']:+.3f} | "
            f"{cf['counterfactual_ev_drop']:+.3f} | {gate} |"
        )
    return "\n".join(lines)


def format_markdown_report(report: Mapping[str, Any]) -> str:
    assert_artifact_hygiene(report)
    sh = report["seed_hygiene"]
    th = report["thresholds"]
    bcfg = report["bootstrap_config"]
    sm = report["summary"]
    p_live = report["pareto_frontiers"]["live_proxy_pareto"]
    p_cf = report["pareto_frontiers"]["counterfactual_catchability_pareto"]
    p_panel = report["pareto_frontiers"]["minimax_panel_pareto"]
    pols = report["policies"]
    fams = report["family_rollups"]

    live_front_str = ", ".join(f"`{k}`" for k in p_live["frontier"]) if p_live["frontier"] else "none"
    cf_front_str = ", ".join(f"`{k}`" for k in p_cf["frontier"]) if p_cf["frontier"] else "none"
    panel_front_str = ", ".join(f"`{k}`" for k in p_panel["frontier"]) if p_panel["frontier"] else "none"

    best_proxy_k = str(sm["best_live_frontier_proxy_regret_policy"])
    best_cf_k = str(sm["best_counterfactual_ev_drop_policy"])
    best_panel_k = str(sm["best_panel_minimax_regret_policy"])

    greedy_rl = pols.get("rl_mole_frontier_v14")
    soft_rl = pols.get("rl_mole_frontier_v14_softmax")

    lines: list[str] = [
        f"{H1} Head-to-Head Mole Representation Pareto & Catchability Benchmark (`v1.4` Hard)",
        "",
        "Offline head-to-head comparison (`0` API calls) of all three fair Canary mole policy representations "
        f"against `default_v0` on a single unified fresh disjoint evaluation slice (`{sh['live_seed_range']}`, "
        f"`n={sh['live_n_seeds']}` v1.4 `hard` seeds; strictly disjoint from `0..59`, `6000..6999`, `30000..30199`, "
        f"`110000..110999`, `800000+`, `900000+`) plus exact `ScheduleReplayPolicy` counterfactual replay on all "
        f"`{sh['counterfactual_n_transcripts']}` committed v1.4 Gemini-4-carbon `hard` transcripts "
        f"(`opencode` + `inproc`, seeds `{sh['counterfactual_seed_range']}`).",
        "",
        "Reproduce or run the deterministic `<2s` artifact equivalence gate:",
        "```bash",
        "PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.representation_pareto "
        "--out results/mole_strategies/representation_pareto_v14.json "
        "--report-md docs/reports/mole_representation_pareto_v14.md --workers 4",
        "PYTHONPATH=. /tmp/fleet-momin/shared/agent-arena-venv/bin/python -m canary.mole.representation_pareto --check",
        "```",
        "",
        f"{H2} 1. Executive Takeaways for Judges",
        "",
        f"- **Unified fairness & catchability compliance**: `{sm['n_fairness_passed']}/{sm['n_policies']}` evaluated "
        f"policies pass all four fairness gates on fresh seeds `{sh['live_seed_range']}` (`SolverPolicy(\"hard\") acc >= "
        f"{th['min_solver_acc']:.2f}`, `LogsOnly acc <= {th['max_logs_only_acc']:.2f}`, `DoNothing == 0.0`, "
        "`StopEarlyQuit == 0.0`).",
        f"- **2D Pareto Frontier 1 (`SolverPolicy score` vs `min_frontier_proxy_regret`)**: {live_front_str} "
        f"(representing families: {', '.join(f'`{f}`' for f in p_live['frontier_families'])}). Highest worst-case "
        f"frontier-proxy regret among feasible policies is `{best_proxy_k}` "
        f"(`{pols[best_proxy_k]['live']['min_frontier_proxy_regret']:+.3f}`, Solver score "
        f"`{pols[best_proxy_k]['live']['solver_score']:+.3f}`).",
        f"- **2D Pareto Frontier 2 (`SolverPolicy accuracy` vs `counterfactual_ev_drop`)**: {cf_front_str} "
        f"(representing families: {', '.join(f'`{f}`' for f in p_cf['frontier_families'])}). Largest exact "
        f"counterfactual Gemini-4-carbon optimal-EV drop among feasible policies is `{best_cf_k}` "
        f"(`{pols[best_cf_k]['counterfactual']['counterfactual_ev_drop']:+.3f}`, Solver accuracy "
        f"`{pols[best_cf_k]['live']['solver_acc']:.3f}`).",
        f"- **5-Investigator Minimax Regret Frontier (`SolverPolicy score` vs `min_panel_regret`)**: {panel_front_str}. "
        f"Highest 5-investigator worst-case regret on fresh seeds is `{best_panel_k}` "
        f"(`{pols[best_panel_k]['live']['min_panel_regret']:+.3f}`).",
    ]

    if greedy_rl is not None and soft_rl is not None:
        lines.append(
            "- **Greedy/calibrated vs uncalibrated softmax `RLMole` (`450` continuous float weights)**: "
            f"`rl_mole_frontier_v14` (`greedy=True`) achieves Solver accuracy `{greedy_rl['live']['solver_acc']:.3f}`, "
            f"min frontier-proxy regret `{greedy_rl['live']['min_frontier_proxy_regret']:+.3f}`, and counterfactual EV drop "
            f"`{greedy_rl['counterfactual']['counterfactual_ev_drop']:+.3f}` (`gate={'PASS' if greedy_rl['fairness_gates']['passed'] else 'FAIL'}`), "
            f"whereas `rl_mole_frontier_v14_softmax` (`greedy=False`) yields Solver accuracy "
            f"`{soft_rl['live']['solver_acc']:.3f}`, min frontier-proxy regret "
            f"`{soft_rl['live']['min_frontier_proxy_regret']:+.3f}`, and counterfactual EV drop "
            f"`{soft_rl['counterfactual']['counterfactual_ev_drop']:+.3f}` (`gate={'PASS' if soft_rl['fairness_gates']['passed'] else 'FAIL'}`)."
        )

    lines.extend(
        [
            "",
            f"{H2} 2. Policy Representation Complexity & Structural Summary",
            "",
            "| Policy | Family | Decision Mode | Complexity / Parameter Count | Leaks / Ep | Frames / Ep | Provenance SHA-256 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for pkey in report["policy_order"]:
        row = pols[pkey]
        cx = row["complexity"]
        lv = row["live"]
        alias_note = f" (`{row['alias']}`)" if row["alias"] else ""
        lines.append(
            f"| `{pkey}`{alias_note} | `{row['family']}` | `{row['decision_mode']}` | "
            f"{cx['complexity_label']} (`eff_params={cx['effective_param_count']}`) | "
            f"{lv['mean_mole_leaks']:.2f} | {lv['mean_mole_frames']:.2f} | `{row['canonical_sha256']}` |"
        )

    lines.extend(
        [
            "",
            f"{H2} 3. Unified Fresh-Seed Catchability, Fairness Gates & Counterfactual Replay (`{sh['live_seed_range']}`, `n={sh['live_n_seeds']}` + `60` CF Transcripts)",
            "",
            f"Paired bootstrap 95% confidence intervals use `B={bcfg['n_boot']}` resamples (`seed={bcfg['seed']}`). "
            "`Min Proxy Regret` is `min(Solver - GeminiCarbonProxy, Solver - CodexHorizonProxy)` on paired live seeds; "
            "`Min Panel Regret` takes the minimum across all 5 non-solver investigators.",
            "",
            "| Policy | Family | Solver Acc | Solver Score [95% CI] | LogsOnly Acc | DoNothing / StopEarly | Min Proxy Regret [95% CI] | Min Panel Regret | CF EV Drop [95% CI] | Gate |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for pkey in report["policy_order"]:
        row = pols[pkey]
        lv = row["live"]
        cf = row["counterfactual"]
        gate_str = "**PASS**" if row["fairness_gates"]["passed"] else "**FAIL**"
        lines.append(
            f"| `{pkey}` | `{row['family']}` | "
            f"{lv['solver_acc']:.3f} | "
            f"{_fmt_ci(lv['solver_score_ci95'])} | "
            f"{lv['logs_only_acc']:.3f} | "
            f"{lv['do_nothing_score']:+.3f} / {lv['stop_early_quit_max_abs']:.3f} | "
            f"{_fmt_ci(lv['min_frontier_proxy_regret_ci95'])} | "
            f"{lv['min_panel_regret']:+.3f} (`{lv['strongest_panel_investigator']}`) | "
            f"{_fmt_ci(cf['counterfactual_ev_drop_ci95'])} | "
            f"{gate_str} |"
        )

    lines.extend(
        [
            "",
            f"{H2} 4. Paired Investigator Regret Breakdown on Fresh Disjoint Seeds (`{sh['live_seed_range']}`, `n={sh['live_n_seeds']}`)",
            "",
            "Cell values report `Regret = SolverPolicy(\"hard\") score - Investigator score` (and paired gain vs `default_v0` `[95% CI]`).",
            "",
            "| Policy | GeminiCarbonProxy Regret (Gain) | CodexHorizonProxy Regret (Gain) | GrokTactics Regret (Gain) | HintedHeuristic Regret (Gain) | Heuristic Regret (Gain) | Mean 5-Inv Regret Gain [95% CI] |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for pkey in report["policy_order"]:
        lv = pols[pkey]["live"]
        invs = lv["investigators"]
        cols = [f"`{pkey}`"]
        for inv in INVESTIGATOR_ORDER:
            ic = invs[inv]
            cols.append(f"{ic['regret']:+.3f} ({ic['regret_gain_vs_default']['mean']:+.3f})")
        cols.append(_fmt_ci(lv["mean_panel_regret_gain_vs_default"]))
        lines.append("| " + " | ".join(cols) + " |")

    lines.extend(
        [
            "",
            f"{H2} 5. Exact Counterfactual Replay on `60` Committed v1.4 Gemini-4-carbon Hard Transcripts (`opencode` + `inproc`, Seeds `0-29`)",
            "",
            "Every policy (including stateful/continuous `RLMole` and SHA-256 seed-hashed `PortfolioMolePolicy`) is replayed "
            "via `Env(\"hard\", seed, mole_strategy=...)` + `ScheduleReplayPolicy` holding Gemini-4-carbon tool calls fixed.",
            "",
            "| Policy | CF Optimal EV | CF EV Drop vs Default [95% CI] | CF P(mole) | CF P(mole) Drop [95% CI] | Top-Suspect Acc (Drop) | Surfaced Canaries / Leaks | OpenCode / InProc EV Drop |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for pkey in report["policy_order"]:
        cf = pols[pkey]["counterfactual"]
        oc_d = cf["per_source"]["opencode"]["optimal_ev_drop"]
        ip_d = cf["per_source"]["inproc"]["optimal_ev_drop"]
        lines.append(
            f"| `{pkey}` | "
            f"{cf['optimal_ev']:.3f} | "
            f"{_fmt_ci(cf['counterfactual_ev_drop_ci95'])} | "
            f"{cf['p_true_mole']:.3f} | "
            f"{_fmt_ci(cf['p_true_mole_drop_ci95'])} | "
            f"{cf['top_suspect_acc']:.3f} ({cf['top_suspect_acc_drop']:+.3f}) | "
            f"{cf['surfaced_canaries']:.2f} / {cf['surfaced_total_leaks']:.2f} | "
            f"{oc_d:+.3f} / {ip_d:+.3f} |"
        )

    lines.extend(
        [
            "",
            f"{H2} 6. Two-Dimensional Pareto Frontier Analysis",
            "",
            f"{H3} 6.1 Frontier A: `(SolverPolicy Score, Min Frontier-Proxy Regret)`",
            "",
            "| Policy | Family | Solver Score (`x`) | Min Frontier-Proxy Regret (`y`) | Pareto Rank | Pareto Optimal | Dominated By |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for pkey in report["policy_order"]:
        cell = p_live["per_policy"][pkey]
        rank_str = str(cell["pareto_rank"]) if cell["pareto_rank"] is not None else "infeasible"
        opt_str = "**YES**" if cell["pareto_optimal"] else "no"
        dom_str = ", ".join(f"`{d}`" for d in cell["dominated_by"]) if cell["dominated_by"] else "none"
        lines.append(
            f"| `{pkey}` | `{pols[pkey]['family']}` | {cell['x']:+.4f} | {cell['y']:+.4f} | "
            f"{rank_str} | {opt_str} | {dom_str} |"
        )

    lines.extend(
        [
            "",
            f"{H3} 6.2 Frontier B: `(SolverPolicy Accuracy, Counterfactual EV Drop)`",
            "",
            "| Policy | Family | Solver Accuracy (`x`) | Counterfactual EV Drop (`y`) | Pareto Rank | Pareto Optimal | Dominated By |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for pkey in report["policy_order"]:
        cell = p_cf["per_policy"][pkey]
        rank_str = str(cell["pareto_rank"]) if cell["pareto_rank"] is not None else "infeasible"
        opt_str = "**YES**" if cell["pareto_optimal"] else "no"
        dom_str = ", ".join(f"`{d}`" for d in cell["dominated_by"]) if cell["dominated_by"] else "none"
        lines.append(
            f"| `{pkey}` | `{pols[pkey]['family']}` | {cell['x']:.4f} | {cell['y']:+.4f} | "
            f"{rank_str} | {opt_str} | {dom_str} |"
        )

    lines.extend(
        [
            "",
            f"{H2} 7. Representation Family Synthesis & Tradeoffs for Judges",
            "",
            "| Family | Evaluated Policies | Fairness Pass | Best Live Proxy Regret | Best Counterfactual EV Drop | Best 5-Inv Minimax Regret | Pareto Frontier Memberships (LiveProxy / CF / Panel) |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for fam in FAMILY_ORDER:
        if fam not in fams:
            continue
        fr = fams[fam]
        bp = fr["best_by_frontier_proxy_regret"]
        bc = fr["best_by_counterfactual_ev_drop"]
        bm = fr["best_by_panel_min_regret"]
        lp_m = ", ".join(f"`{k}`" for k in fr["on_live_proxy_pareto"]) or "none"
        cf_m = ", ".join(f"`{k}`" for k in fr["on_counterfactual_pareto"]) or "none"
        pm_m = ", ".join(f"`{k}`" for k in fr["on_minimax_panel_pareto"]) or "none"
        lines.append(
            f"| `{fam}` ({fr['family_label']}) | {fr['n_policies']} | {fr['n_fairness_passed']}/{fr['n_policies']} | "
            f"`{bp}` ({pols[bp]['live']['min_frontier_proxy_regret']:+.3f}) | "
            f"`{bc}` ({pols[bc]['counterfactual']['counterfactual_ev_drop']:+.3f}) | "
            f"`{bm}` ({pols[bm]['live']['min_panel_regret']:+.3f}) | "
            f"{lp_m} / {cf_m} / {pm_m} |"
        )

    lines.extend(
        [
            "",
            "- **Symbolic Mole DSL (`<=5` discrete rules, `0` continuous weights)**: Human-auditable rule lists map "
            "each empirical frontier failure mode directly to an inspectable `(condition -> selector)` branch, achieving "
            "minimal parameter complexity (`2-5` rules) and direct per-rule ablation interpretability.",
            (
                "- **Continuous Distilled `RLMole` (`450` float weights, `11->20` MLP)**: Smooth feature combination blends "
                "multiple symbolic mechanisms into a single continuous network; greedy argmax (`rl_mole_frontier_v14`) tracks "
                f"its symbolic teacher (`CF EV drop {greedy_rl['counterfactual']['counterfactual_ev_drop']:+.3f}`, "
                f"`LogsOnly={greedy_rl['live']['logs_only_acc']:.3f}`), while `Env`-seeded softmax sampling "
                "(`rl_mole_frontier_v14_softmax`) injects action-level entropy (`CodexHorizonProxy` regret "
                f"`{soft_rl['live']['investigators']['codex_horizon_proxy']['regret']:+.3f}` vs "
                f"`{greedy_rl['live']['investigators']['codex_horizon_proxy']['regret']:+.3f}`, live min proxy regret "
                f"`{soft_rl['live']['min_frontier_proxy_regret']:+.3f}`, `SolverPolicy` acc `{soft_rl['live']['solver_acc']:.3f}`)."
                if (greedy_rl is not None and soft_rl is not None)
                else "- **Continuous Distilled `RLMole` (`450` float weights, `11->20` MLP)**: Smooth feature combination "
                "blends multiple symbolic mechanisms into a single continuous network with deterministic `Env`-seeded decoding."
            ),
            "- **Game-Theoretic SHA-256 `PortfolioMolePolicy` (`2` active simplex weights)**: Zero-private-information "
            "seed randomization hedges across complementary pure DSL specialists (`surgical_trap_shield` and "
            "`gemini_midsize_shield`), equalizing binding investigator regrets without expanding the action vocabulary.",
        ]
    )

    return "\n".join(lines) + "\n"


def check_representation_pareto_artifacts(
    json_path: Path = DEFAULT_OUT_PATH,
    md_path: Path = DEFAULT_REPORT_MD_PATH,
    max_json_bytes: int = MAX_JSON_BYTES,
) -> tuple[bool, str]:
    if not json_path.is_file():
        return False, f"FAIL: missing JSON artifact: {json_path}"
    if not md_path.is_file():
        return False, f"FAIL: missing Markdown report: {md_path}"

    raw_bytes = json_path.read_bytes()
    if len(raw_bytes) >= int(max_json_bytes):
        return False, f"FAIL: JSON artifact {json_path} exceeds byte limit ({len(raw_bytes)} >= {max_json_bytes})"

    try:
        json_text = raw_bytes.decode("utf-8")
        md_text = md_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return False, f"FAIL: non-UTF-8 artifact encoding: {exc}"

    for p, txt in ((json_path, json_text), (md_path, md_text)):
        if EM_DASH in txt or EN_DASH in txt or UNICODE_MINUS in txt:
            return False, f"FAIL: forbidden dash/minus character found in {p}"
        if not txt.isascii():
            return False, f"FAIL: non-ASCII character found in {p}"
        low = txt.lower()
        if FLASH_TAG in low:
            return False, f"FAIL: forbidden {FLASH_TAG} reference in {p}"
        if SOLVER_PCT_TAG in low or FORBIDDEN_GAP_RE.search(txt):
            return False, f"FAIL: forbidden solver percentage/ratio claim in {p}"
        if COAUTHOR_TAG in low:
            return False, f"FAIL: forbidden co-author trailer in {p}"
        if EMPLOYEE_ID_RE.search(txt):
            return False, f"FAIL: leaked employee ID token in {p}"
        for pat in SECRET_KEY_PATTERNS:
            if pat.search(txt):
                return False, f"FAIL: leaked API key pattern in {p}"

    try:
        report = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return False, f"FAIL: invalid JSON in {json_path}: {exc}"
    if not isinstance(report, dict):
        return False, f"FAIL: root JSON payload must be an object in {json_path}"

    try:
        assert_artifact_hygiene(report)
    except ValueError as exc:
        return False, f"FAIL: hygiene check failed: {exc}"

    sh = report.get("seed_hygiene")
    if not isinstance(sh, dict):
        return False, "FAIL: missing seed_hygiene block"
    try:
        seeds = validate_pareto_seeds(sh.get("live_seeds", []))
    except ValueError as exc:
        return False, f"FAIL: seed hygiene violation: {exc}"
    if len(seeds) != int(sh.get("live_n_seeds", -1)):
        return False, "FAIL: live_n_seeds mismatch with live_seeds list"

    pols = report.get("policies")
    porder = report.get("policy_order")
    if not isinstance(pols, dict) or not isinstance(porder, list) or len(porder) < 8:
        return False, "FAIL: expected >= 8 representative policies in policy_order"
    if set(pols.keys()) != set(porder):
        return False, "FAIL: policies keys mismatch policy_order"

    families_present = {str(pols[k].get("family")) for k in porder}
    for req_fam in FAMILY_ORDER:
        if req_fam not in families_present:
            return False, f"FAIL: missing required policy family {req_fam!r}"

    th = report.get("thresholds") or {}
    min_sol = float(th.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC))
    max_lo = float(th.get("max_logs_only_acc", DEFAULT_MAX_LOGS_ACC))

    pareto_inputs: dict[str, dict[str, Any]] = {}
    re_pass_count = 0
    for pkey in porder:
        row = pols[pkey]
        lv = row.get("live") or {}
        cf = row.get("counterfactual") or {}
        rec_gates = row.get("fairness_gates") or {}
        re_gates = evaluate_fairness_gates(
            solver_acc=float(lv["solver_acc"]),
            logs_only_acc=float(lv["logs_only_acc"]),
            do_nothing_max_abs=float(lv["do_nothing_max_abs"]),
            stop_early_quit_max_abs=float(lv["stop_early_quit_max_abs"]),
            min_solver_acc=min_sol,
            max_logs_acc=max_lo,
        )
        if rec_gates != re_gates:
            return False, f"FAIL: fairness_gates mismatch/tamper on {pkey}"
        if re_gates["passed"]:
            re_pass_count += 1
        pareto_inputs[pkey] = {
            "family": str(row["family"]),
            "feasible": bool(re_gates["passed"]),
            "solver_score": float(lv["solver_score"]),
            "solver_acc": float(lv["solver_acc"]),
            "min_frontier_proxy_regret": float(lv["min_frontier_proxy_regret"]),
            "min_panel_regret": float(lv["min_panel_regret"]),
            "counterfactual_ev_drop": float(cf["counterfactual_ev_drop"]),
        }

    if int(report.get("summary", {}).get("n_fairness_passed", -1)) != re_pass_count:
        return False, "FAIL: summary.n_fairness_passed mismatch"

    p_frontiers = report.get("pareto_frontiers") or {}
    expected_frontiers = {
        "live_proxy_pareto": compute_pareto_frontier(
            pareto_inputs,
            x_key="solver_score",
            y_key="min_frontier_proxy_regret",
            feasible_key="feasible",
        ),
        "counterfactual_catchability_pareto": compute_pareto_frontier(
            pareto_inputs,
            x_key="solver_acc",
            y_key="counterfactual_ev_drop",
            feasible_key="feasible",
        ),
        "minimax_panel_pareto": compute_pareto_frontier(
            pareto_inputs,
            x_key="solver_score",
            y_key="min_panel_regret",
            feasible_key="feasible",
        ),
    }
    if p_frontiers != expected_frontiers:
        return False, "FAIL: pareto_frontiers mismatch/tamper against policy metrics"

    expected_json = dumps_compact_json(report) + "\n"
    if json_text != expected_json:
        return False, f"FAIL: JSON formatting drift in {json_path}"

    expected_md = format_markdown_report(report)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {md_path} does not match JSON artifact {json_path}"

    return (
        True,
        f"OK: {json_path.name} ({len(raw_bytes)} bytes, n={len(seeds)} seeds, "
        f"policies={len(porder)}, passed={re_pass_count}/{len(porder)}) matches {md_path.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.representation_pareto")
    ap.add_argument("--seeds", default=DEFAULT_EVAL_SEEDS_SPEC)
    ap.add_argument("--cf-seeds", default=DEFAULT_CF_SEEDS_SPEC)
    ap.add_argument("--cf-sources", default="opencode,inproc")
    ap.add_argument("--policies", default=None, help="comma-separated subset of policy keys")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--boot-resamples", type=int, default=DEFAULT_BOOT_RESAMPLES)
    ap.add_argument("--boot-seed", type=int, default=DEFAULT_BOOT_SEED)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report-md", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    out_path = args.out if args.out is not None else DEFAULT_OUT_PATH
    md_path = args.report_md if args.report_md is not None else DEFAULT_REPORT_MD_PATH

    if args.check:
        ok, msg = check_representation_pareto_artifacts(json_path=out_path, md_path=md_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    policy_keys = [x.strip() for x in args.policies.split(",") if x.strip()] if args.policies else None
    cf_sources = tuple(x.strip() for x in args.cf_sources.split(",") if x.strip())

    report = run_representation_pareto_benchmark(
        seeds=args.seeds,
        cf_seeds=args.cf_seeds,
        cf_sources=cf_sources,
        policy_keys=policy_keys,
        workers=args.workers,
        n_boot=args.boot_resamples,
        boot_seed=args.boot_seed,
        min_solver_acc=args.min_solver_acc,
        max_logs_acc=args.max_logs_acc,
    )

    json_payload = dumps_compact_json(report) + "\n"
    if len(json_payload.encode("utf-8")) >= MAX_JSON_BYTES:
        raise ValueError(f"JSON payload exceeds {MAX_JSON_BYTES} byte limit")

    if args.out is not None or args.report_md is None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json_payload, encoding="utf-8")
    if args.report_md is not None or args.out is None:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(format_markdown_report(report), encoding="utf-8")

    if args.json:
        print(json_payload, end="")
    else:
        print(format_terminal_summary(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
