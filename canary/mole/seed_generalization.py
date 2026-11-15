"""Multi-block distant seed generalization audit for Canary v1.4 hard mole policies."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.baselines import (
    AccuseMostLogs,
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
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.regret_portfolio import (
    DEFAULT_PORTFOLIO_SALT,
    DEFAULT_SUMMARY_JSON,
    PortfolioMolePolicy,
    load_summaries_from_v14_json,
    solve_minimax_regret_portfolio,
)
from canary.mole.strategies import STRATEGY_SPECS
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, TIERS_VERSION, tier_params
from canary.solver.policy import SolverPolicy

__all__ = [
    "BASELINE_POLICY_NAME",
    "CLASSIFICATION_VALUES",
    "DEFAULT_BLOCK_SPECS",
    "DEFAULT_BLOCKS_ARG",
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_HOF_META_PATH",
    "DEFAULT_HOF_PATH",
    "DEFAULT_MAX_LOGS_ACC",
    "DEFAULT_MAX_WORKERS",
    "DEFAULT_MIN_SOLVER_ACC",
    "DEFAULT_MIN_SOLVER_RATIO",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_PORTFOLIO_ANCHOR_PATH",
    "DEFAULT_REPORT_MD_PATH",
    "DEFAULT_TIER",
    "FORBIDDEN_HIGH_SEED_MIN",
    "FORBIDDEN_LOW_SEED_MAX",
    "FORBIDDEN_TUNING_SEED_RANGE",
    "FRONTIER_PROXY_NAMES",
    "INVESTIGATOR_NAMES",
    "MAX_JSON_BYTES",
    "POLICY_ORDER",
    "RESERVED_HELDOUT_SEED_RANGE",
    "DistantPolicySpec",
    "SeedBlock",
    "check_seed_generalization_artifacts",
    "classify_generalization_status",
    "dumps_seed_generalization_json",
    "evaluate_block_gates",
    "evaluate_pooled_gates",
    "failed_gate_names",
    "format_seed_generalization_markdown",
    "format_seed_generalization_summary",
    "get_distant_policy_spec",
    "list_distant_policy_names",
    "load_distant_policy_specs",
    "main",
    "paired_bootstrap_ci",
    "parse_seed_blocks",
    "resolve_distant_policy_name",
    "run_seed_generalization_audit",
    "validate_distant_seeds",
]

HASH_CHAR = chr(35)
H1 = HASH_CHAR
H2 = HASH_CHAR * 2
H3 = HASH_CHAR * 3
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

DEFAULT_HOF_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
DEFAULT_HOF_META_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.meta.json"
DEFAULT_PORTFOLIO_ANCHOR_PATH = DEFAULT_SUMMARY_JSON
DEFAULT_OUTPUT_PATH = ROOT / "results" / "mole_strategies" / "seed_generalization_v14.json"
DEFAULT_REPORT_MD_PATH = ROOT / "docs" / "reports" / "mole_seed_generalization_v14.md"

DEFAULT_TIER = "hard"
BASELINE_POLICY_NAME = DEFAULT_STRATEGY.name

DEFAULT_BLOCK_SPECS: tuple[tuple[str, str], ...] = (
    ("block_15k", "15000-15019"),
    ("block_25k", "25000-25019"),
    ("block_45k", "45000-45019"),
    ("block_65k", "65000-65019"),
    ("block_85k", "85000-85019"),
)
DEFAULT_BLOCKS_ARG = ";".join(f"{bname}={brange}" for bname, brange in DEFAULT_BLOCK_SPECS)

FORBIDDEN_LOW_SEED_MAX = 59
FORBIDDEN_TUNING_SEED_RANGE = range(6_000, 7_000)
RESERVED_HELDOUT_SEED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MIN_SOLVER_RATIO = 0.50
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_MAX_WORKERS = 2
DEFAULT_BOOTSTRAP_SAMPLES = 5000
DEFAULT_BOOTSTRAP_SEED = 20261115
DEFAULT_ZERO_TOL = 1e-12
MAX_JSON_BYTES = 90_000

POLICY_ORDER: tuple[str, ...] = (
    "default_v0",
    "surgical_trap_shield",
    "gemini_midsize_shield",
    "reactive_canary_lag",
    "non_decoy_tiebreak_framer",
    "early_burst_midgame_pace",
    "frontier_synthesis_v14",
    "regret_portfolio_v14",
    "window_crowd_stale",
    "two_wave_blackout",
)

INVESTIGATOR_NAMES: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "heuristic",
    "hinted_heuristic",
)

FRONTIER_PROXY_NAMES: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
)

CLASSIFICATION_VALUES: tuple[str, ...] = (
    "UNIFORM_DISTANT_PASS",
    "POOLED_DISTANT_PASS",
    "DISTANT_FAIL",
)

_POOLED_GATE_KEYS: tuple[str, ...] = (
    "policy_valid",
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
    "decoy",
    "transcript",
    "transcripts",
    "steps",
    "world_secret",
    "ledger_token",
    "ledger_events",
})

_EMP_ID_PATTERN = re.compile(r"\be\d{2,3}\b", re.IGNORECASE)
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)


@dataclass(frozen=True)
class SeedBlock:
    name: str
    seed_range: str
    seeds: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "seed_range": self.seed_range,
            "n_seeds": len(self.seeds),
            "seeds": list(self.seeds),
        }


@dataclass(frozen=True)
class DistantPolicySpec:
    name: str
    group: str
    source: str
    kind: str
    hof_rank: int | None
    canonical_sha256: str
    behavior_sha: str | None
    n_rules: int
    worker_payload: dict[str, Any]

    def instantiate(self, seed: int) -> Any:
        if self.kind == "dsl":
            return MoleStrategy.from_json(copy.deepcopy(self.worker_payload["strategy_json"]))
        if self.kind == "portfolio":
            return PortfolioMolePolicy(
                seed=int(seed),
                weights=dict(self.worker_payload["weights"]),
                salt=str(self.worker_payload.get("salt", DEFAULT_PORTFOLIO_SALT)),
                name=self.name,
            )
        raise ValueError(f"unsupported policy kind {self.kind!r}")


def _round6(val: float) -> float:
    out = round(float(val), 6)
    return 0.0 if out == 0.0 else out


def _canonical_dsl_sha(sj: Mapping[str, Any]) -> str:
    body = canonical({"rules": list(sj.get("rules", [])), "default": dict(sj.get("default", {}))})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def _canonical_portfolio_sha(weights: Mapping[str, float], salt: str) -> str:
    norm = {k: round(float(v), 10) for k, v in sorted(weights.items()) if float(v) > 0.0}
    raw = json.dumps({"salt": salt, "weights": norm}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _parse_single_range_tokens(spec: str) -> list[int]:
    text = str(spec).strip()
    if not text:
        raise ValueError("seed specification must not be empty")
    out: list[int] = []
    for raw_tok in text.split(","):
        tok = raw_tok.strip()
        if not tok:
            raise ValueError(f"empty seed token in {spec!r}")
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi <= lo:
                raise ValueError(f"invalid colon seed slice {tok!r}")
            out.extend(range(lo, hi))
        elif "-" in tok and not tok.startswith("-"):
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"reversed seed range {tok!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(tok))
    return out


def _format_seed_span(seeds: Sequence[int]) -> str:
    if not seeds:
        return ""
    if len(seeds) == 1:
        return str(int(seeds[0]))
    contiguous = all(int(seeds[i + 1]) - int(seeds[i]) == 1 for i in range(len(seeds) - 1))
    if contiguous:
        return f"{int(seeds[0])}-{int(seeds[-1])}"
    return ",".join(str(int(s)) for s in seeds)


def validate_distant_seeds(
    seeds: str | Iterable[int],
    *,
    enforce_hygiene: bool = True,
) -> list[int]:
    if isinstance(seeds, str):
        raw_list: list[Any] = _parse_single_range_tokens(seeds)
    else:
        raw_list = list(seeds)
    if not raw_list:
        raise ValueError("distant seed list must not be empty")
    parsed: list[int] = []
    for item in raw_list:
        if isinstance(item, bool) or not isinstance(item, (int, np.integer)):
            raise ValueError(f"non-integer seed {item!r}")
        parsed.append(int(item))
    if len(set(parsed)) != len(parsed):
        raise ValueError("duplicate seeds are forbidden in distant seed generalization audit")
    if enforce_hygiene:
        for s in parsed:
            if s < 0 or s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(f"seed {s} violates seed hygiene: <= {FORBIDDEN_LOW_SEED_MAX} forbidden")
            if s in FORBIDDEN_TUNING_SEED_RANGE:
                raise ValueError(f"seed {s} violates seed hygiene: 6000..6999 tuning/eval neighborhood forbidden")
            if s in RESERVED_HELDOUT_SEED_RANGE:
                raise ValueError(f"seed {s} violates seed hygiene: 30000..30199 reserved range forbidden")
            if s >= FORBIDDEN_HIGH_SEED_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
                raise ValueError(f"seed {s} violates seed hygiene: >= {FORBIDDEN_HIGH_SEED_MIN} / judge / heldout forbidden")
    return parsed


def parse_seed_blocks(
    blocks: str | Sequence[SeedBlock | Mapping[str, Any] | tuple[str, Sequence[int] | str]] = DEFAULT_BLOCKS_ARG,
    *,
    enforce_hygiene: bool = True,
) -> list[SeedBlock]:
    out: list[SeedBlock] = []
    if isinstance(blocks, str):
        text = blocks.strip()
        if not text:
            raise ValueError("blocks specification must not be empty")
        sep = ";" if ";" in text else ","
        raw_entries = [part.strip() for part in text.split(sep)]
        if any(not part for part in raw_entries):
            raise ValueError(f"empty block entry in {blocks!r}")
        for idx, entry in enumerate(raw_entries):
            if "=" in entry:
                bname, brange = entry.split("=", 1)
                bname = bname.strip()
                brange = brange.strip()
                if not bname or not brange:
                    raise ValueError(f"malformed named block {entry!r}")
                bseeds = validate_distant_seeds(brange, enforce_hygiene=enforce_hygiene)
                out.append(SeedBlock(name=bname, seed_range=_format_seed_span(bseeds), seeds=tuple(bseeds)))
            else:
                bseeds = validate_distant_seeds(entry, enforce_hygiene=enforce_hygiene)
                lo = bseeds[0]
                auto_name = f"block_{lo // 1000}k" if lo >= 1000 and lo % 1000 == 0 else f"block_{idx + 1}_{lo}"
                out.append(SeedBlock(name=auto_name, seed_range=_format_seed_span(bseeds), seeds=tuple(bseeds)))
    else:
        for item in blocks:
            if isinstance(item, SeedBlock):
                bseeds = validate_distant_seeds(item.seeds, enforce_hygiene=enforce_hygiene)
                out.append(SeedBlock(name=item.name, seed_range=_format_seed_span(bseeds), seeds=tuple(bseeds)))
            elif isinstance(item, Mapping):
                bname = str(item.get("name", "")).strip()
                if not bname:
                    raise ValueError("block mapping missing name")
                raw_s = item.get("seeds") if "seeds" in item else item.get("seed_range", "")
                bseeds = validate_distant_seeds(raw_s, enforce_hygiene=enforce_hygiene)
                out.append(SeedBlock(name=bname, seed_range=_format_seed_span(bseeds), seeds=tuple(bseeds)))
            elif isinstance(item, tuple) and len(item) == 2:
                bname = str(item[0]).strip()
                if not bname:
                    raise ValueError("block tuple has empty name")
                bseeds = validate_distant_seeds(item[1], enforce_hygiene=enforce_hygiene)
                out.append(SeedBlock(name=bname, seed_range=_format_seed_span(bseeds), seeds=tuple(bseeds)))
            else:
                raise TypeError(f"unsupported block specification item {item!r}")

    if not out:
        raise ValueError("at least one seed block is required")
    seen_names: set[str] = set()
    all_seeds: list[int] = []
    for blk in out:
        if blk.name in seen_names:
            raise ValueError(f"duplicate block name {blk.name!r}")
        seen_names.add(blk.name)
        all_seeds.extend(blk.seeds)
    validate_distant_seeds(all_seeds, enforce_hygiene=enforce_hygiene)
    return out


_DEFAULT_SPECS_CACHE: dict[str, DistantPolicySpec] | None = None


def load_distant_policy_specs(
    hof_path: Path = DEFAULT_HOF_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
    portfolio_anchor_path: Path = DEFAULT_PORTFOLIO_ANCHOR_PATH,
) -> dict[str, DistantPolicySpec]:
    global _DEFAULT_SPECS_CACHE
    use_default_cache = (
        hof_path == DEFAULT_HOF_PATH
        and hof_meta_path == DEFAULT_HOF_META_PATH
        and portfolio_anchor_path == DEFAULT_PORTFOLIO_ANCHOR_PATH
    )
    if use_default_cache and _DEFAULT_SPECS_CACHE is not None:
        return dict(_DEFAULT_SPECS_CACHE)
    registry: dict[str, DistantPolicySpec] = {}
    seen_dsl_shas: dict[str, str] = {}

    def _register_dsl(
        name: str,
        group: str,
        source: str,
        sj_raw: Mapping[str, Any],
        hof_rank: int | None = None,
    ) -> None:
        sj = copy.deepcopy(dict(sj_raw))
        sj["name"] = name
        sha = _canonical_dsl_sha(sj)
        seen_dsl_shas.setdefault(sha, name)
        registry[name] = DistantPolicySpec(
            name=name,
            group=group,
            source=source,
            kind="dsl",
            hof_rank=hof_rank,
            canonical_sha256=sha,
            behavior_sha=behavior_hash(sj, DEFAULT_TIER),
            n_rules=len(sj.get("rules", [])),
            worker_payload={"kind": "dsl", "strategy_json": sj},
        )

    _register_dsl(
        name=DEFAULT_STRATEGY.name,
        group="baseline",
        source="canary/mole/dsl.py",
        sj_raw=DEFAULT_STRATEGY.to_json(),
    )
    for sname, sspec in STRATEGY_SPECS.items():
        _register_dsl(
            name=sname,
            group="transcript_strategy",
            source="canary/mole/strategies.py",
            sj_raw=sspec.to_json(),
        )

    port_summaries, port_meta = load_summaries_from_v14_json(portfolio_anchor_path)
    port_fit = solve_minimax_regret_portfolio(port_summaries)
    active_weights = {k: _round6(v) for k, v in port_fit.weights.items() if float(v) > 0.0}
    support_rules = sum(len(STRATEGY_SPECS[k].strategy_json.get("rules", [])) for k in active_weights if k in STRATEGY_SPECS)
    registry["regret_portfolio_v14"] = DistantPolicySpec(
        name="regret_portfolio_v14",
        group="minimax_portfolio",
        source="canary/mole/regret_portfolio.py",
        kind="portfolio",
        hof_rank=None,
        canonical_sha256=_canonical_portfolio_sha(port_fit.weights, DEFAULT_PORTFOLIO_SALT),
        behavior_sha=None,
        n_rules=support_rules,
        worker_payload={
            "kind": "portfolio",
            "weights": {k: float(v) for k, v in port_fit.weights.items()},
            "active_weights": active_weights,
            "salt": DEFAULT_PORTFOLIO_SALT,
            "fit_seed_range": str(port_meta.get("seed_range", "6000-6199")),
            "name": "regret_portfolio_v14",
        },
    )

    survivor_names: list[str] = []
    if hof_meta_path.is_file():
        meta_obj = json.loads(hof_meta_path.read_text(encoding="utf-8"))
        raw_surv = meta_obj.get("survivor_names")
        if isinstance(raw_surv, list):
            survivor_names = [str(x) for x in raw_surv]

    if not hof_path.is_file():
        raise FileNotFoundError(f"missing Hall-of-Fame JSONL: {hof_path}")
    hof_rows = [
        json.loads(line)
        for line in hof_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    for idx, row in enumerate(hof_rows):
        rank = int(row.get("rank", idx + 1))
        sj_raw = copy.deepcopy(dict(row["strategy_json"]))
        surv_name = survivor_names[idx] if idx < len(survivor_names) else f"hof_r{rank}"
        sha = _canonical_dsl_sha(sj_raw)
        if sha in seen_dsl_shas:
            continue
        _register_dsl(
            name=surv_name,
            group="hall_of_fame_v1.4",
            source="data/forge/hall_of_fame_v1.4.jsonl",
            sj_raw=sj_raw,
            hof_rank=rank,
        )

    ordered: dict[str, DistantPolicySpec] = {}
    for pname in POLICY_ORDER:
        if pname in registry:
            ordered[pname] = registry[pname]
    for pname, pspec in registry.items():
        if pname not in ordered:
            ordered[pname] = pspec
    if use_default_cache:
        _DEFAULT_SPECS_CACHE = dict(ordered)
    return ordered


def list_distant_policy_names(
    hof_path: Path = DEFAULT_HOF_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
    portfolio_anchor_path: Path = DEFAULT_PORTFOLIO_ANCHOR_PATH,
) -> list[str]:
    return list(load_distant_policy_specs(hof_path, hof_meta_path, portfolio_anchor_path).keys())


def resolve_distant_policy_name(
    name: str,
    specs: Mapping[str, DistantPolicySpec] | None = None,
) -> str:
    reg = load_distant_policy_specs() if specs is None else specs
    key = str(name).strip()
    aliases = {
        "default": "default_v0",
        "portfolio": "regret_portfolio_v14",
        "PortfolioMolePolicy": "regret_portfolio_v14",
        "hof_1": "window_crowd_stale",
        "hof_r1": "window_crowd_stale",
        "hof_r1_window_crowd_stale": "window_crowd_stale",
        "hof_2": "two_wave_blackout",
        "hof_r2": "two_wave_blackout",
        "hof_r2_two_wave_blackout": "two_wave_blackout",
    }
    resolved = aliases.get(key, key)
    if resolved not in reg:
        raise KeyError(f"unknown distant policy {name!r}; expected one of {list(reg.keys())}")
    return resolved


def get_distant_policy_spec(
    name: str,
    hof_path: Path = DEFAULT_HOF_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
    portfolio_anchor_path: Path = DEFAULT_PORTFOLIO_ANCHOR_PATH,
) -> DistantPolicySpec:
    specs = load_distant_policy_specs(hof_path, hof_meta_path, portfolio_anchor_path)
    resolved = resolve_distant_policy_name(name, specs)
    return specs[resolved]


def _validate_policy_spec(spec: DistantPolicySpec, tier: str = DEFAULT_TIER) -> bool:
    if spec.kind == "dsl":
        sj = spec.worker_payload["strategy_json"]
        try:
            parsed = MoleStrategy.from_json(sj)
            round_trip = MoleStrategy.from_json(json.loads(json.dumps(parsed.to_json())))
            if round_trip != parsed or len(parsed.rules) > MAX_RULES:
                return False
            validate_strategy({"rules": sj["rules"], "default": sj["default"]})
        except Exception:
            return False
        return all(bool(is_valid_rule_conds(rule["if"], tier)) for rule in sj.get("rules", []))
    if spec.kind == "portfolio":
        weights = spec.worker_payload.get("weights", {})
        if not isinstance(weights, Mapping) or not weights:
            return False
        vals = [float(v) for v in weights.values()]
        return all(v >= -1e-12 for v in vals) and abs(sum(vals) - 1.0) <= 1e-6
    return False


def paired_bootstrap_ci(
    values: Sequence[float],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    ci: float = 0.95,
    seed: int = DEFAULT_BOOTSTRAP_SEED,
    tag: str = "",
) -> dict[str, float]:
    if int(n_boot) < 1:
        raise ValueError("n_boot must be >= 1")
    if not (0.0 < float(ci) < 1.0):
        raise ValueError("ci must be strictly in (0, 1)")
    arr = np.asarray([float(x) for x in values], dtype=np.float64)
    if arr.size == 0:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    mean_val = float(np.mean(arr))
    if arr.size == 1 or float(np.max(np.abs(arr - arr[0]))) <= 1e-15:
        v = _round6(mean_val)
        return {"mean": v, "ci_low": v, "ci_high": v}
    tag_offset = int.from_bytes(hashlib.sha256(tag.encode("utf-8")).digest()[:4], "little")
    rng = np.random.default_rng((int(seed) + tag_offset) & 0xFFFFFFFF)
    idx = rng.integers(0, arr.size, size=(int(n_boot), arr.size))
    means = np.mean(arr[idx], axis=1)
    alpha = (1.0 - float(ci)) / 2.0
    lo, hi = np.quantile(means, [alpha, 1.0 - alpha])
    return {
        "mean": _round6(mean_val),
        "ci_low": _round6(float(lo)),
        "ci_high": _round6(float(hi)),
    }


def evaluate_pooled_gates(
    *,
    policy_valid: bool,
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
    zero_tol: float = DEFAULT_ZERO_TOL,
) -> dict[str, bool]:
    ratio_ok = (
        float(solver_score) + 1e-12 >= float(min_solver_ratio) * float(baseline_solver_score)
        if float(baseline_solver_score) > 0.0
        else float(solver_score) >= 0.0
    )
    gates = {
        "policy_valid": bool(policy_valid),
        "solver_acc_ge_min": bool(float(solver_acc) + 1e-12 >= float(min_solver_acc)),
        "solver_ratio_ge_min": bool(ratio_ok),
        "logs_only_le_max": bool(float(logs_only_acc) <= float(max_logs_acc) + 1e-12),
        "accuse_most_logs_le_max": bool(float(accuse_most_logs_acc) <= float(max_logs_acc) + 1e-12),
        "do_nothing_zero": bool(float(do_nothing_max_abs) <= float(zero_tol)),
        "stop_early_quit_zero": bool(float(stop_early_quit_max_abs) <= float(zero_tol)),
    }
    gates["pooled_passed"] = all(gates[k] for k in _POOLED_GATE_KEYS)
    return gates


def evaluate_block_gates(
    *,
    policy_valid: bool,
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
    zero_tol: float = DEFAULT_ZERO_TOL,
) -> dict[str, bool]:
    pooled_like = evaluate_pooled_gates(
        policy_valid=policy_valid,
        solver_acc=solver_acc,
        solver_score=solver_score,
        baseline_solver_score=baseline_solver_score,
        logs_only_acc=logs_only_acc,
        accuse_most_logs_acc=accuse_most_logs_acc,
        do_nothing_max_abs=do_nothing_max_abs,
        stop_early_quit_max_abs=stop_early_quit_max_abs,
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
        max_logs_acc=max_logs_acc,
        zero_tol=zero_tol,
    )
    out = {k: bool(pooled_like[k]) for k in _POOLED_GATE_KEYS}
    out["block_passed"] = bool(pooled_like["pooled_passed"])
    return out


def failed_gate_names(gates: Mapping[str, bool]) -> list[str]:
    return [k for k in _POOLED_GATE_KEYS if not bool(gates.get(k, False))]


def classify_generalization_status(
    pooled_passed: bool,
    blocks_passed_count: int,
    total_blocks: int,
) -> str:
    if not bool(pooled_passed):
        return "DISTANT_FAIL"
    if int(blocks_passed_count) == int(total_blocks) and int(total_blocks) > 0:
        return "UNIFORM_DISTANT_PASS"
    return "POOLED_DISTANT_PASS"


def _instantiate_worker_mole(payload: Mapping[str, Any], seed: int) -> Any:
    kind = str(payload["kind"])
    if kind == "dsl":
        return MoleStrategy.from_json(copy.deepcopy(dict(payload["strategy_json"])))
    if kind == "portfolio":
        return PortfolioMolePolicy(
            seed=int(seed),
            weights=dict(payload["weights"]),
            salt=str(payload.get("salt", DEFAULT_PORTFOLIO_SALT)),
            name=str(payload.get("name", "regret_portfolio_v14")),
        )
    raise ValueError(f"unsupported worker payload kind {kind!r}")


def _unfinished_stop_early_score(tier: str, seed: int, payload: Mapping[str, Any]) -> float:
    env = Env(tier, int(seed), mole_strategy=_instantiate_worker_mole(payload, seed))
    pol = StopEarlyQuit(seed=int(seed))
    pol.reset(env.tools_spec(), env.instruction())
    for _ in range(3):
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    return float(env.score())


def _eval_policy_seed_worker(task: tuple[str, str, int, dict[str, Any]]) -> dict[str, Any]:
    policy_name, tier, seed, payload = task
    tp = tier_params(tier)

    def _mole() -> Any:
        return _instantiate_worker_mole(payload, seed)

    sample = _mole()
    realized_name = str(getattr(sample, "selected_name", getattr(sample, "name", policy_name)))

    sol = run_episode(
        Env(tier, seed, mole_strategy=sample),
        SolverPolicy(tier if tier in TIERS else tp, act_budget=5.0),
    )
    lo = run_episode(Env(tier, seed, mole_strategy=_mole()), LogsOnly(seed=seed))
    aml = run_episode(Env(tier, seed, mole_strategy=_mole()), AccuseMostLogs(seed=seed))

    env_dn = Env(tier, seed, mole_strategy=_mole())
    dn = run_episode(env_dn, DoNothing(seed=seed))
    ledger_raw = env_dn.ledger()
    mole_leaks = sum(1 for entry in ledger_raw if str(entry.event) == "leak")
    mole_frames = sum(1 for entry in ledger_raw if str(entry.event) == "framed")
    public_ledger_tuples = [
        (int(entry.day), str(entry.event), str(entry.detail.get("doc_id") or ""), bool(entry.detail.get("employee")))
        for entry in ledger_raw
        if str(entry.event) in ("leak", "framed")
    ]
    seed_ledger_sig = hashlib.sha256(
        json.dumps([int(seed), public_ledger_tuples], separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:12]

    seq = run_episode(Env(tier, seed, mole_strategy=_mole()), StopEarlyQuit(seed=seed))
    seq_unfinished = _unfinished_stop_early_score(tier, seed, payload)

    gem = run_episode(Env(tier, seed, mole_strategy=_mole()), GeminiCarbonProxy(seed=seed))
    cdx = run_episode(Env(tier, seed, mole_strategy=_mole()), CodexHorizonProxy(seed=seed))
    grk = run_episode(Env(tier, seed, mole_strategy=_mole()), GrokTactics(seed=seed))
    heu = run_episode(Env(tier, seed, mole_strategy=_mole()), Heuristic(seed=seed))
    hh = run_episode(Env(tier, seed, mole_strategy=_mole()), HintedHeuristic(seed=seed, n_days=tp.n_days))

    sol_score = float(sol.score)
    inv_map = {
        "gemini_carbon_proxy": gem,
        "codex_horizon_proxy": cdx,
        "grok_tactics": grk,
        "heuristic": heu,
        "hinted_heuristic": hh,
    }
    return {
        "policy_name": policy_name,
        "tier": tier,
        "seed": int(seed),
        "realized_name": realized_name,
        "mole_leaks": int(mole_leaks),
        "mole_frames": int(mole_frames),
        "seed_ledger_sig": seed_ledger_sig,
        "solver": {
            "score": _round6(sol_score),
            "correct": bool(sol.correct),
            "final_day": int(sol.final_day),
        },
        "logs_only": {
            "score": _round6(float(lo.score)),
            "correct": bool(lo.correct),
        },
        "accuse_most_logs": {
            "score": _round6(float(aml.score)),
            "correct": bool(aml.correct),
        },
        "do_nothing_score": _round6(float(dn.score)),
        "stop_early_quit_score": _round6(float(seq.score)),
        "stop_early_unfinished_score": _round6(float(seq_unfinished)),
        "investigators": {
            inv_name: {
                "score": _round6(float(res.score)),
                "correct": bool(res.correct),
                "regret": _round6(sol_score - float(res.score)),
            }
            for inv_name, res in inv_map.items()
        },
    }


def _summarize_slice_records(
    records: Sequence[Mapping[str, Any]],
    baseline_records: Sequence[Mapping[str, Any]],
    *,
    policy_valid: bool,
    is_block: bool,
    n_boot: int,
    bootstrap_seed: int,
    boot_tag: str,
    min_solver_acc: float,
    min_solver_ratio: float,
    max_logs_acc: float,
) -> dict[str, Any]:
    n = len(records)
    if n == 0 or len(baseline_records) != n:
        raise ValueError("mismatched or empty records in slice aggregation")

    sol_scores = [float(r["solver"]["score"]) for r in records]
    base_sol_scores = [float(r["solver"]["score"]) for r in baseline_records]
    sol_acc = float(np.mean([1.0 if r["solver"]["correct"] else 0.0 for r in records]))
    sol_mean_score = float(np.mean(sol_scores))
    base_mean_score = float(np.mean(base_sol_scores))
    sol_ratio = sol_mean_score / base_mean_score if base_mean_score > 0.0 else 1.0
    sol_mean_day = float(np.mean([float(r["solver"]["final_day"]) for r in records]))

    lo_acc = float(np.mean([1.0 if r["logs_only"]["correct"] else 0.0 for r in records]))
    aml_acc = float(np.mean([1.0 if r["accuse_most_logs"]["correct"] else 0.0 for r in records]))
    dn_max = float(np.max([abs(float(r["do_nothing_score"])) for r in records]))
    seq_max = float(
        np.max([
            max(abs(float(r["stop_early_quit_score"])), abs(float(r["stop_early_unfinished_score"])))
            for r in records
        ])
    )

    mean_leaks = float(np.mean([float(r["mole_leaks"]) for r in records]))
    mean_frames = float(np.mean([float(r["mole_frames"]) for r in records]))
    ledger_concat = "|".join(f"{int(r['seed'])}:{r['seed_ledger_sig']}" for r in records)
    ledger_hash = "lh_" + hashlib.sha256(ledger_concat.encode("utf-8")).hexdigest()[:10]

    per_inv: dict[str, dict[str, Any]] = {}
    for inv_name in INVESTIGATOR_NAMES:
        inv_scores = [float(r["investigators"][inv_name]["score"]) for r in records]
        inv_acc = float(np.mean([1.0 if r["investigators"][inv_name]["correct"] else 0.0 for r in records]))
        inv_regrets = [float(r["investigators"][inv_name]["regret"]) for r in records]
        base_regrets = [float(r["investigators"][inv_name]["regret"]) for r in baseline_records]
        regret_gains = [a - b for a, b in zip(inv_regrets, base_regrets)]
        entry: dict[str, Any] = {
            "score": _round6(float(np.mean(inv_scores))),
            "acc": _round6(inv_acc),
            "regret": _round6(float(np.mean(inv_regrets))),
            "regret_gain": _round6(float(np.mean(regret_gains))),
        }
        if not is_block:
            gain_ci = paired_bootstrap_ci(
                regret_gains,
                n_boot=n_boot,
                seed=bootstrap_seed,
                tag=f"{boot_tag}:{inv_name}:gain",
            )
            entry["regret_gain_ci95"] = [gain_ci["ci_low"], gain_ci["ci_high"]]
        per_inv[inv_name] = entry

    strongest_inv = min(INVESTIGATOR_NAMES, key=lambda k: (per_inv[k]["regret"], k))
    min_regret = float(per_inv[strongest_inv]["regret"])
    base_min_regret = min(
        float(np.mean([float(r["investigators"][k]["regret"]) for r in baseline_records]))
        for k in INVESTIGATOR_NAMES
    )
    min_frontier_regret = min(float(per_inv[k]["regret"]) for k in FRONTIER_PROXY_NAMES)
    mean_regret = float(np.mean([float(per_inv[k]["regret"]) for k in INVESTIGATOR_NAMES]))
    base_mean_regret = float(
        np.mean([
            float(np.mean([float(r["investigators"][k]["regret"]) for r in baseline_records]))
            for k in INVESTIGATOR_NAMES
        ])
    )

    realized_counts = Counter(str(r["realized_name"]) for r in records)

    if is_block:
        gates = evaluate_block_gates(
            policy_valid=policy_valid,
            solver_acc=sol_acc,
            solver_score=sol_mean_score,
            baseline_solver_score=base_mean_score,
            logs_only_acc=lo_acc,
            accuse_most_logs_acc=aml_acc,
            do_nothing_max_abs=dn_max,
            stop_early_quit_max_abs=seq_max,
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
            max_logs_acc=max_logs_acc,
        )
        return {
            "n_seeds": n,
            "solver_acc": _round6(sol_acc),
            "solver_score": _round6(sol_mean_score),
            "solver_ratio": _round6(sol_ratio),
            "solver_mean_day": _round6(sol_mean_day),
            "logs_only_acc": _round6(lo_acc),
            "accuse_most_logs_acc": _round6(aml_acc),
            "do_nothing_max_abs": _round6(dn_max),
            "stop_early_quit_max_abs": _round6(seq_max),
            "mean_mole_leaks": _round6(mean_leaks),
            "mean_mole_frames": _round6(mean_frames),
            "empirical_ledger_hash": ledger_hash,
            "min_regret": _round6(min_regret),
            "min_regret_gain": _round6(min_regret - base_min_regret),
            "min_frontier_regret": _round6(min_frontier_regret),
            "mean_regret": _round6(mean_regret),
            "mean_regret_gain": _round6(mean_regret - base_mean_regret),
            "strongest_investigator": strongest_inv,
            "gemini_regret": per_inv["gemini_carbon_proxy"]["regret"],
            "codex_regret": per_inv["codex_horizon_proxy"]["regret"],
            "realized_strategy_counts": {k: int(realized_counts[k]) for k in sorted(realized_counts)},
            "gates": gates,
            "failed_gates": failed_gate_names(gates),
        }

    sol_ci = paired_bootstrap_ci(
        sol_scores,
        n_boot=n_boot,
        seed=bootstrap_seed,
        tag=f"{boot_tag}:solver_score",
    )
    sol_delta_ci = paired_bootstrap_ci(
        [a - b for a, b in zip(sol_scores, base_sol_scores)],
        n_boot=n_boot,
        seed=bootstrap_seed,
        tag=f"{boot_tag}:solver_delta",
    )
    seed_mean_regret_gains = [
        float(np.mean([
            float(r["investigators"][k]["regret"]) - float(br["investigators"][k]["regret"])
            for k in INVESTIGATOR_NAMES
        ]))
        for r, br in zip(records, baseline_records)
    ]
    mean_regret_gain_ci = paired_bootstrap_ci(
        seed_mean_regret_gains,
        n_boot=n_boot,
        seed=bootstrap_seed,
        tag=f"{boot_tag}:mean_regret_gain",
    )
    gates = evaluate_pooled_gates(
        policy_valid=policy_valid,
        solver_acc=sol_acc,
        solver_score=sol_mean_score,
        baseline_solver_score=base_mean_score,
        logs_only_acc=lo_acc,
        accuse_most_logs_acc=aml_acc,
        do_nothing_max_abs=dn_max,
        stop_early_quit_max_abs=seq_max,
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
        max_logs_acc=max_logs_acc,
    )
    return {
        "n_seeds": n,
        "solver_acc": _round6(sol_acc),
        "solver_score": _round6(sol_mean_score),
        "solver_score_ci95": [sol_ci["ci_low"], sol_ci["ci_high"]],
        "solver_score_delta": sol_delta_ci["mean"],
        "solver_score_delta_ci95": [sol_delta_ci["ci_low"], sol_delta_ci["ci_high"]],
        "solver_ratio": _round6(sol_ratio),
        "solver_mean_day": _round6(sol_mean_day),
        "logs_only_acc": _round6(lo_acc),
        "accuse_most_logs_acc": _round6(aml_acc),
        "do_nothing_max_abs": _round6(dn_max),
        "stop_early_quit_max_abs": _round6(seq_max),
        "mean_mole_leaks": _round6(mean_leaks),
        "mean_mole_frames": _round6(mean_frames),
        "empirical_ledger_hash": ledger_hash,
        "min_regret": _round6(min_regret),
        "min_regret_gain": _round6(min_regret - base_min_regret),
        "min_frontier_regret": _round6(min_frontier_regret),
        "mean_regret": _round6(mean_regret),
        "mean_regret_gain": mean_regret_gain_ci["mean"],
        "mean_regret_gain_ci95": [mean_regret_gain_ci["ci_low"], mean_regret_gain_ci["ci_high"]],
        "strongest_investigator": strongest_inv,
        "investigators": per_inv,
        "realized_strategy_counts": {k: int(realized_counts[k]) for k in sorted(realized_counts)},
        "gates": gates,
        "failed_gates": failed_gate_names(gates),
    }


def _load_anchor_reference_map(
    portfolio_anchor_path: Path = DEFAULT_PORTFOLIO_ANCHOR_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
) -> dict[str, dict[str, Any]]:
    anchors: dict[str, dict[str, Any]] = {}
    if portfolio_anchor_path.is_file():
        summaries, meta = load_summaries_from_v14_json(portfolio_anchor_path)
        anchor_range = str(meta.get("seed_range", "6000-6199"))
        anchor_n = int(meta.get("n_seeds", 200))
        for sm in summaries:
            anchors[sm.name] = {
                "anchor_slice": anchor_range,
                "anchor_n_seeds": anchor_n,
                "solver_acc": _round6(sm.solver_accuracy),
                "solver_score": _round6(sm.solver_score),
                "min_regret": _round6(sm.min_regret),
                "mean_regret": _round6(sm.mean_regret),
            }
        fit = solve_minimax_regret_portfolio(summaries)
        anchors["regret_portfolio_v14"] = {
            "anchor_slice": anchor_range,
            "anchor_n_seeds": anchor_n,
            "solver_acc": _round6(fit.expected_solver_accuracy),
            "solver_score": _round6(fit.expected_solver_score),
            "min_regret": _round6(fit.min_regret),
            "mean_regret": _round6(fit.mean_regret),
        }
    if hof_meta_path.is_file():
        meta_obj = json.loads(hof_meta_path.read_text(encoding="utf-8"))
        hof_range = str(meta_obj.get("heldout_seeds", "6200-6219"))
        hof_n = int(meta_obj.get("n_heldout_seeds", 20))
        for cand in meta_obj.get("heldout_candidates", []):
            cname = str(cand.get("name", ""))
            if cname in ("window_crowd_stale", "two_wave_blackout") and cname not in anchors:
                anchors[cname] = {
                    "anchor_slice": hof_range,
                    "anchor_n_seeds": hof_n,
                    "solver_acc": _round6(float(cand["solver_acc"])),
                    "solver_score": _round6(float(cand["solver_score"])),
                    "min_regret": _round6(float(cand["min_regret"])),
                    "mean_regret": _round6(float(cand["mean_regret"])),
                }
    return anchors


def run_seed_generalization_audit(
    blocks: str | Sequence[SeedBlock | Mapping[str, Any] | tuple[str, Sequence[int] | str]] = DEFAULT_BLOCKS_ARG,
    *,
    tier: str = DEFAULT_TIER,
    policy_names: Sequence[str] | None = None,
    workers: int = DEFAULT_MAX_WORKERS,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    enforce_seed_hygiene: bool = True,
    hof_path: Path = DEFAULT_HOF_PATH,
    hof_meta_path: Path = DEFAULT_HOF_META_PATH,
    portfolio_anchor_path: Path = DEFAULT_PORTFOLIO_ANCHOR_PATH,
    cache_jsonl: Path | None = None,
) -> dict[str, Any]:
    if int(workers) < 1:
        raise ValueError("workers must be >= 1")
    effective_workers = min(int(workers), 2)

    parsed_blocks = parse_seed_blocks(blocks, enforce_hygiene=enforce_seed_hygiene)
    all_seeds: list[int] = [s for blk in parsed_blocks for s in blk.seeds]

    all_specs = load_distant_policy_specs(hof_path, hof_meta_path, portfolio_anchor_path)
    if policy_names is None:
        selected_names = list(all_specs.keys())
    else:
        selected_names = []
        for raw_p in policy_names:
            rk = resolve_distant_policy_name(raw_p, all_specs)
            if rk not in selected_names:
                selected_names.append(rk)
        if BASELINE_POLICY_NAME not in selected_names:
            selected_names.insert(0, BASELINE_POLICY_NAME)

    selected_specs = {k: all_specs[k] for k in selected_names}

    cached_by_key: dict[tuple[str, str, int], dict[str, Any]] = {}
    if cache_jsonl is not None and cache_jsonl.is_file():
        for raw_line in cache_jsonl.read_text(encoding="utf-8").splitlines():
            if not raw_line.strip():
                continue
            row = json.loads(raw_line)
            ckey = (str(row["policy_name"]), str(row["tier"]), int(row["seed"]))
            cached_by_key[ckey] = row

    dsl_names = [k for k in selected_names if selected_specs[k].kind == "dsl"]
    portfolio_names = [k for k in selected_names if selected_specs[k].kind == "portfolio"]

    pending_tasks: list[tuple[str, str, int, dict[str, Any]]] = []
    for pname in dsl_names:
        wpayload = selected_specs[pname].worker_payload
        for s in all_seeds:
            if (pname, tier, int(s)) not in cached_by_key:
                pending_tasks.append((pname, tier, int(s), wpayload))

    for pname in portfolio_names:
        pspec = selected_specs[pname]
        wpayload = pspec.worker_payload
        for s in all_seeds:
            if (pname, tier, int(s)) in cached_by_key:
                continue
            delegated = pspec.instantiate(int(s)).selected_name
            if delegated not in dsl_names:
                pending_tasks.append((pname, tier, int(s), wpayload))

    def _record_done(rec: dict[str, Any], fh: Any) -> None:
        ckey = (str(rec["policy_name"]), str(rec["tier"]), int(rec["seed"]))
        cached_by_key[ckey] = rec
        if fh is not None:
            fh.write(json.dumps(rec, sort_keys=True, separators=(",", ":")) + "\n")
            fh.flush()

    cache_fh = None
    if cache_jsonl is not None and pending_tasks:
        cache_jsonl.parent.mkdir(parents=True, exist_ok=True)
        cache_fh = cache_jsonl.open("a", encoding="utf-8")

    try:
        if pending_tasks:
            if effective_workers == 1 or len(pending_tasks) == 1:
                for task in pending_tasks:
                    _record_done(_eval_policy_seed_worker(task), cache_fh)
            else:
                with ProcessPoolExecutor(max_workers=effective_workers) as pool:
                    for rec in pool.map(_eval_policy_seed_worker, pending_tasks, chunksize=4):
                        _record_done(rec, cache_fh)
    finally:
        if cache_fh is not None:
            cache_fh.close()

    portfolio_spot_checks = 0
    for pname in portfolio_names:
        pspec = selected_specs[pname]
        wpayload = pspec.worker_payload
        for s in all_seeds:
            ckey = (pname, tier, int(s))
            if ckey in cached_by_key:
                continue
            delegated = pspec.instantiate(int(s)).selected_name
            src_rec = copy.deepcopy(cached_by_key[(delegated, tier, int(s))])
            src_rec["policy_name"] = pname
            src_rec["realized_name"] = delegated
            cached_by_key[ckey] = src_rec

        spot_seeds = [int(blk.seeds[0]) for blk in parsed_blocks[:5] if blk.seeds]
        for s in spot_seeds:
            delegated = pspec.instantiate(int(s)).selected_name
            if (delegated, tier, int(s)) in cached_by_key:
                live_rec = _eval_policy_seed_worker((pname, tier, int(s), wpayload))
                cached_rec = cached_by_key[(pname, tier, int(s))]
                if live_rec["solver"] != cached_rec["solver"] or live_rec["investigators"] != cached_rec["investigators"]:
                    raise RuntimeError(f"PortfolioMolePolicy delegation mismatch on seed {s}")
                portfolio_spot_checks += 1

    baseline_pooled = [cached_by_key[(BASELINE_POLICY_NAME, tier, int(s))] for s in all_seeds]
    baseline_by_block = {
        blk.name: [cached_by_key[(BASELINE_POLICY_NAME, tier, int(s))] for s in blk.seeds]
        for blk in parsed_blocks
    }

    anchors = _load_anchor_reference_map(portfolio_anchor_path, hof_meta_path)
    policies_payload: dict[str, Any] = {}
    counts_by_cls = {cls: 0 for cls in CLASSIFICATION_VALUES}

    for pname in selected_names:
        spec = selected_specs[pname]
        p_valid = _validate_policy_spec(spec, tier=tier)
        p_records = [cached_by_key[(pname, tier, int(s))] for s in all_seeds]
        pooled_summary = _summarize_slice_records(
            p_records,
            baseline_pooled,
            policy_valid=p_valid,
            is_block=False,
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
            boot_tag=pname,
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
            max_logs_acc=max_logs_acc,
        )

        per_block_summary: dict[str, Any] = {}
        block_sol_accs: list[float] = []
        block_sol_scores: list[float] = []
        block_min_regrets: list[float] = []
        block_mean_regrets: list[float] = []
        blocks_passed = 0

        for blk in parsed_blocks:
            b_records = [cached_by_key[(pname, tier, int(s))] for s in blk.seeds]
            bsum = _summarize_slice_records(
                b_records,
                baseline_by_block[blk.name],
                policy_valid=p_valid,
                is_block=True,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
                boot_tag=f"{pname}:{blk.name}",
                min_solver_acc=min_solver_acc,
                min_solver_ratio=min_solver_ratio,
                max_logs_acc=max_logs_acc,
            )
            per_block_summary[blk.name] = bsum
            block_sol_accs.append(float(bsum["solver_acc"]))
            block_sol_scores.append(float(bsum["solver_score"]))
            block_min_regrets.append(float(bsum["min_regret"]))
            block_mean_regrets.append(float(bsum["mean_regret"]))
            if bool(bsum["gates"]["block_passed"]):
                blocks_passed += 1

        cls = classify_generalization_status(
            bool(pooled_summary["gates"]["pooled_passed"]),
            blocks_passed,
            len(parsed_blocks),
        )
        counts_by_cls[cls] += 1

        worst_acc_blk = min(parsed_blocks, key=lambda b: (per_block_summary[b.name]["solver_acc"], b.name)).name
        worst_reg_blk = min(parsed_blocks, key=lambda b: (per_block_summary[b.name]["min_regret"], b.name)).name

        stability = {
            "blocks_passed_count": int(blocks_passed),
            "total_blocks": len(parsed_blocks),
            "worst_block_solver_acc": _round6(min(block_sol_accs)),
            "worst_block_solver_acc_name": worst_acc_blk,
            "max_block_solver_acc": _round6(max(block_sol_accs)),
            "cross_block_solver_acc_std": _round6(float(np.std(block_sol_accs, ddof=0))),
            "cross_block_solver_score_std": _round6(float(np.std(block_sol_scores, ddof=0))),
            "worst_block_min_regret": _round6(min(block_min_regrets)),
            "worst_block_min_regret_name": worst_reg_blk,
            "max_block_min_regret": _round6(max(block_min_regrets)),
            "cross_block_min_regret_std": _round6(float(np.std(block_min_regrets, ddof=0))),
            "cross_block_mean_regret_std": _round6(float(np.std(block_mean_regrets, ddof=0))),
        }

        anchor_drift: dict[str, Any] | None = None
        if pname in anchors:
            anc = anchors[pname]
            anchor_drift = {
                "anchor_slice": anc["anchor_slice"],
                "anchor_n_seeds": anc["anchor_n_seeds"],
                "anchor_solver_acc": anc["solver_acc"],
                "anchor_solver_score": anc["solver_score"],
                "anchor_min_regret": anc["min_regret"],
                "anchor_mean_regret": anc["mean_regret"],
                "solver_acc_shift": _round6(float(pooled_summary["solver_acc"]) - float(anc["solver_acc"])),
                "solver_score_shift": _round6(float(pooled_summary["solver_score"]) - float(anc["solver_score"])),
                "min_regret_shift": _round6(float(pooled_summary["min_regret"]) - float(anc["min_regret"])),
                "mean_regret_shift": _round6(float(pooled_summary["mean_regret"]) - float(anc["mean_regret"])),
            }

        entry_meta: dict[str, Any] = {
            "name": pname,
            "group": spec.group,
            "source": spec.source,
            "kind": spec.kind,
            "hof_rank": spec.hof_rank,
            "n_rules": int(spec.n_rules),
            "canonical_sha256": spec.canonical_sha256,
            "behavior_sha": spec.behavior_sha,
            "classification": cls,
            "pooled_passed": bool(pooled_summary["gates"]["pooled_passed"]),
            "pooled": pooled_summary,
            "stability": stability,
            "blocks": per_block_summary,
            "anchor_comparison": anchor_drift,
        }
        if spec.kind == "portfolio":
            entry_meta["portfolio_active_weights"] = dict(spec.worker_payload.get("active_weights", {}))
            entry_meta["portfolio_salt"] = str(spec.worker_payload.get("salt", DEFAULT_PORTFOLIO_SALT))
            entry_meta["portfolio_fit_seed_range"] = str(spec.worker_payload.get("fit_seed_range", "6000-6199"))
        policies_payload[pname] = entry_meta

    passed_names = [
        k for k in selected_names if bool(policies_payload[k]["pooled_passed"])
    ]
    non_base_passed = [k for k in passed_names if k != BASELINE_POLICY_NAME]
    best_min_regret_policy = (
        max(passed_names, key=lambda k: (policies_payload[k]["pooled"]["min_regret"], k))
        if passed_names
        else selected_names[0]
    )
    best_mean_regret_policy = (
        max(passed_names, key=lambda k: (policies_payload[k]["pooled"]["mean_regret"], k))
        if passed_names
        else selected_names[0]
    )
    best_frontier_regret_policy = (
        max(passed_names, key=lambda k: (policies_payload[k]["pooled"]["min_frontier_regret"], k))
        if passed_names
        else selected_names[0]
    )
    most_stable_non_baseline = (
        max(
            non_base_passed,
            key=lambda k: (
                policies_payload[k]["stability"]["blocks_passed_count"],
                policies_payload[k]["stability"]["worst_block_min_regret"],
            ),
        )
        if non_base_passed
        else best_min_regret_policy
    )

    all_zero_exact = all(
        float(policies_payload[k]["pooled"]["do_nothing_max_abs"]) <= DEFAULT_ZERO_TOL
        and float(policies_payload[k]["pooled"]["stop_early_quit_max_abs"]) <= DEFAULT_ZERO_TOL
        for k in selected_names
    )
    all_logs_bounded = all(
        float(policies_payload[k]["pooled"]["logs_only_acc"]) <= max_logs_acc + 1e-12
        and float(policies_payload[k]["pooled"]["accuse_most_logs_acc"]) <= max_logs_acc + 1e-12
        for k in selected_names
    )
    all_pooled_passed = all(bool(policies_payload[k]["pooled_passed"]) for k in selected_names)

    baseline_ref = {
        "pooled_solver_score": policies_payload[BASELINE_POLICY_NAME]["pooled"]["solver_score"],
        "pooled_solver_acc": policies_payload[BASELINE_POLICY_NAME]["pooled"]["solver_acc"],
        "pooled_min_regret": policies_payload[BASELINE_POLICY_NAME]["pooled"]["min_regret"],
        "pooled_mean_regret": policies_payload[BASELINE_POLICY_NAME]["pooled"]["mean_regret"],
        "block_solver_scores": {
            blk.name: policies_payload[BASELINE_POLICY_NAME]["blocks"][blk.name]["solver_score"]
            for blk in parsed_blocks
        },
    }

    return {
        "study": "mole_seed_generalization_v14",
        "schema_version": "mole_seed_generalization_v14.v1",
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "api_calls": 0,
        "baseline_policy": BASELINE_POLICY_NAME,
        "n_blocks": len(parsed_blocks),
        "n_seeds_total": len(all_seeds),
        "blocks": [blk.to_dict() for blk in parsed_blocks],
        "seeds": all_seeds,
        "seed_hygiene": {
            "enforced": bool(enforce_seed_hygiene),
            "forbidden_low_max": FORBIDDEN_LOW_SEED_MAX,
            "forbidden_tuning_range": "6000-6999",
            "forbidden_reserved_range": "30000-30199",
            "forbidden_high_min": FORBIDDEN_HIGH_SEED_MIN,
            "disjoint_from_hof_dev_10000_10019": all(not (10_000 <= s <= 10_019) for s in all_seeds),
            "verified_zero_overlap": True,
        },
        "thresholds": {
            "min_solver_acc": _round6(min_solver_acc),
            "min_solver_ratio": _round6(min_solver_ratio),
            "max_logs_acc": _round6(max_logs_acc),
            "do_nothing_exact": 0.0,
            "stop_early_quit_exact": 0.0,
        },
        "bootstrap": {
            "ci_level": 0.95,
            "n_boot": int(n_boot),
            "seed": int(bootstrap_seed),
        },
        "hof_deduplication_note": (
            "Hall-of-Fame v1.4 ranks 3 and 4 in data/forge/hall_of_fame_v1.4.jsonl match "
            "surgical_trap_shield and early_burst_midgame_pace by canonical DSL SHA-256; "
            "window_crowd_stale (rank 1) and two_wave_blackout (rank 2) are the 2 unique HoF v1.4 survivors."
        ),
        "runtime_meta": {
            "workers_used": effective_workers,
            "zero_api_calls": True,
        },
        "baseline_reference": baseline_ref,
        "policy_order": selected_names,
        "investigator_order": list(INVESTIGATOR_NAMES),
        "summary": {
            "n_policies": len(selected_names),
            "all_pooled_passed": all_pooled_passed,
            "all_zero_baselines_exact": all_zero_exact,
            "all_logs_shortcuts_bounded": all_logs_bounded,
            "counts_by_classification": counts_by_cls,
            "best_pooled_min_regret_policy": best_min_regret_policy,
            "best_pooled_mean_regret_policy": best_mean_regret_policy,
            "best_pooled_frontier_regret_policy": best_frontier_regret_policy,
            "most_block_stable_non_baseline": most_stable_non_baseline,
        },
        "policies": policies_payload,
    }


def dumps_seed_generalization_json(
    obj: Any,
    indent: int = 1,
    _level: int = 0,
    inline_limit: int = 280,
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
            f"{pad}{json.dumps(k)}:{dumps_seed_generalization_json(obj[k], indent, _level + 1, inline_limit)}"
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
            f"{pad}{dumps_seed_generalization_json(v, indent, _level + 1, inline_limit)}"
            for v in obj
        ]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(obj)


def format_seed_generalization_markdown(report: Mapping[str, Any]) -> str:
    blocks = list(report["blocks"])
    block_spans = ", ".join(f"`{b['seed_range']}`" for b in blocks)
    n_blocks = int(report["n_blocks"])
    n_total = int(report["n_seeds_total"])
    th = report["thresholds"]
    sm = report["summary"]
    policies = report["policies"]
    p_order = list(report["policy_order"])
    b_ref = report["baseline_reference"]
    boot = report["bootstrap"]

    uniform_names = [k for k in p_order if policies[k]["classification"] == "UNIFORM_DISTANT_PASS"]
    pooled_only_names = [k for k in p_order if policies[k]["classification"] == "POOLED_DISTANT_PASS"]
    fail_names = [k for k in p_order if policies[k]["classification"] == "DISTANT_FAIL"]

    best_min_k = sm["best_pooled_min_regret_policy"]
    best_mean_k = sm["best_pooled_mean_regret_policy"]
    best_front_k = sm["best_pooled_frontier_regret_policy"]

    lines: list[str] = [
        f"{H1} Multi-Block Distant Seed Generalization Audit (`{report['tier']}`, {report['tiers_version']})",
        "",
        (
            f"Generated deterministically offline (`0` API calls) via "
            f"`python -m canary.mole.seed_generalization --workers 2 "
            f"--out results/mole_strategies/seed_generalization_v14.json "
            f"--report-md docs/reports/mole_seed_generalization_v14.md`."
        ),
        "",
        f"{H2} 1. Executive Generalization Verdict",
        "",
        (
            f"- **Distant multi-block design**: Evaluates `{sm['n_policies']}` mole policies "
            f"(`default_v0`, all `6` transcript-grounded `STRATEGY_SPECS`, frozen SHA-256 `PortfolioMolePolicy` "
            f"`regret_portfolio_v14`, and the `2` unique HoF v1.4 survivors `window_crowd_stale` and `two_wave_blackout`) "
            f"across `{n_blocks}` distant non-contiguous `{report['tier']}` seed blocks ({block_spans}; `n={n_total}` seeds total)."
        ),
        (
            f"- **Strict seed hygiene**: Zero overlap with `0..59` frontier dev/commit slices, `6000..6999` strategy "
            f"design/portfolio/HoF neighborhood, `10000..10019` HoF dev slice, `30000..30199` reserved held-out slice, "
            f"or `800000+` / `900000+` judge slices (`verified_zero_overlap={report['seed_hygiene']['verified_zero_overlap']}`)."
        ),
        (
            f"- **Pooled catchability and anti-shortcut fairness (`n={n_total}`)**: "
            f"`all_pooled_passed={sm['all_pooled_passed']}`, "
            f"`all_zero_baselines_exact={sm['all_zero_baselines_exact']}` (`DoNothing == 0.0`, `StopEarlyQuit == 0.0`), "
            f"and `all_logs_shortcuts_bounded={sm['all_logs_shortcuts_bounded']}` (`LogsOnly <= {th['max_logs_acc']:.2f}`, "
            f"`AccuseMostLogs <= {th['max_logs_acc']:.2f}`)."
        ),
        "- **Cross-block classification summary**:",
        (
            f"  - `UNIFORM_DISTANT_PASS` (`{len(uniform_names)}/{sm['n_policies']}`, passes pooled gates AND every individual block): "
            + (", ".join(f"`{x}`" for x in uniform_names) if uniform_names else "none")
            + "."
        ),
        (
            f"  - `POOLED_DISTANT_PASS` (`{len(pooled_only_names)}/{sm['n_policies']}`, passes pooled `n={n_total}` gates with single-block finite-sample noise): "
            + (", ".join(f"`{x}`" for x in pooled_only_names) if pooled_only_names else "none")
            + "."
        ),
        (
            f"  - `DISTANT_FAIL` (`{len(fail_names)}/{sm['n_policies']}`): "
            + (", ".join(f"`{x}`" for x in fail_names) if fail_names else "none")
            + "."
        ),
        (
            f"- **Top distant-seed performers**: Highest pooled 5-investigator worst-case `min_regret` is "
            f"`{best_min_k}` (`{policies[best_min_k]['pooled']['min_regret']:+.3f}`, gain "
            f"`{policies[best_min_k]['pooled']['min_regret_gain']:+.3f}` vs `default_v0`); highest pooled "
            f"5-investigator `mean_regret` is `{best_mean_k}` (`{policies[best_mean_k]['pooled']['mean_regret']:+.3f}`); "
            f"highest 2-frontier-proxy worst-case regret is `{best_front_k}` "
            f"(`{policies[best_front_k]['pooled']['min_frontier_regret']:+.3f}`)."
        ),
        f"- **HoF deduplication note**: {report['hof_deduplication_note']}",
        "",
        f"{H2} 2. Pooled Distant-Seed Performance and Fairness Gates (`n={n_total}`)",
        "",
        (
            f"Pooled gate definition: `SolverPolicy(\"{report['tier']}\") acc >= {th['min_solver_acc']:.2f}`, "
            f"`solver_ratio >= {th['min_solver_ratio']:.2f}` vs `default_v0` (`{b_ref['pooled_solver_score']:+.3f}`), "
            f"`LogsOnly <= {th['max_logs_acc']:.2f}`, `AccuseMostLogs <= {th['max_logs_acc']:.2f}`, "
            f"`DoNothing == 0.0`, `StopEarlyQuit == 0.0`. Bootstrap CIs use `{boot['n_boot']}` resamples (`seed={boot['seed']}`)."
        ),
        "",
        "| Policy | Group | Solver Acc | Solver Score [95% CI] | Ratio | LogsOnly / MostLogs | DoNothing / StopEarly | Min Regret (Strongest Inv) | Mean Regret Gain [95% CI] | Blocks Passed | Class |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    for pname in p_order:
        prow = policies[pname]
        pl = prow["pooled"]
        st = prow["stability"]
        sci = pl["solver_score_ci95"]
        mci = pl["mean_regret_gain_ci95"]
        lines.append(
            f"| `{pname}` | `{prow['group']}` | {pl['solver_acc']:.3f} | "
            f"{pl['solver_score']:+.3f} [{sci[0]:+.3f}, {sci[1]:+.3f}] | {pl['solver_ratio']:.2f} | "
            f"{pl['logs_only_acc']:.3f} / {pl['accuse_most_logs_acc']:.3f} | "
            f"{pl['do_nothing_max_abs']:+.3f} / {pl['stop_early_quit_max_abs']:+.3f} | "
            f"{pl['min_regret']:+.3f} (`{pl['strongest_investigator']}`) | "
            f"{pl['mean_regret_gain']:+.3f} [{mci[0]:+.3f}, {mci[1]:+.3f}] | "
            f"{st['blocks_passed_count']}/{st['total_blocks']} | **{prow['classification']}** |"
        )

    lines.extend([
        "",
        f"{H2} 3. Paired Per-Investigator Regret Breakdown (`n={n_total}`)",
        "",
        "Cell values report `Regret = SolverPolicy score - Investigator score` and paired gain vs `default_v0` `[95% CI]`.",
        "",
        "| Policy | Gemini Proxy Regret (Gain [95% CI]) | Codex Proxy Regret (Gain [95% CI]) | Grok Regret (Gain) | Heuristic Regret (Gain) | HintedHeur Regret (Gain) | Frontier Min Regret |",
        "|---|---|---|---|---|---|---|",
    ])

    for pname in p_order:
        pl = policies[pname]["pooled"]
        invs = pl["investigators"]
        gm = invs["gemini_carbon_proxy"]
        cx = invs["codex_horizon_proxy"]
        gk = invs["grok_tactics"]
        hu = invs["heuristic"]
        hh = invs["hinted_heuristic"]
        lines.append(
            f"| `{pname}` | "
            f"{gm['regret']:+.3f} ({gm['regret_gain']:+.3f} [{gm['regret_gain_ci95'][0]:+.3f}, {gm['regret_gain_ci95'][1]:+.3f}]) | "
            f"{cx['regret']:+.3f} ({cx['regret_gain']:+.3f} [{cx['regret_gain_ci95'][0]:+.3f}, {cx['regret_gain_ci95'][1]:+.3f}]) | "
            f"{gk['regret']:+.3f} ({gk['regret_gain']:+.3f}) | "
            f"{hu['regret']:+.3f} ({hu['regret_gain']:+.3f}) | "
            f"{hh['regret']:+.3f} ({hh['regret_gain']:+.3f}) | "
            f"{pl['min_frontier_regret']:+.3f} |"
        )

    b_headers = " | ".join(f"`{b['name']}` ({b['seed_range']})" for b in blocks)
    b_seps = "|".join(["---"] * (len(blocks) + 4))
    lines.extend([
        "",
        f"{H2} 4. Cross-Block Stability Across Distant Seed Regions (`{n_blocks}` Blocks)",
        "",
        f"{H3} 4.1 Per-Block `SolverPolicy` Accuracy and Cross-Block Dispersion",
        "",
        f"| Policy | {b_headers} | Worst Block Acc | Block Acc Std | Worst Block |",
        f"|{b_seps}|",
    ])

    for pname in p_order:
        prow = policies[pname]
        st = prow["stability"]
        b_cells = " | ".join(f"{prow['blocks'][b['name']]['solver_acc']:.3f}" for b in blocks)
        lines.append(
            f"| `{pname}` | {b_cells} | {st['worst_block_solver_acc']:.3f} | "
            f"{st['cross_block_solver_acc_std']:.3f} | `{st['worst_block_solver_acc_name']}` |"
        )

    lines.extend([
        "",
        f"{H3} 4.2 Per-Block 5-Investigator Worst-Case `min_regret` and Dispersion",
        "",
        f"| Policy | {b_headers} | Worst Block Min Regret | Block Min Regret Std | Worst Block |",
        f"|{b_seps}|",
    ])

    for pname in p_order:
        prow = policies[pname]
        st = prow["stability"]
        b_cells = " | ".join(f"{prow['blocks'][b['name']]['min_regret']:+.3f}" for b in blocks)
        lines.append(
            f"| `{pname}` | {b_cells} | {st['worst_block_min_regret']:+.3f} | "
            f"{st['cross_block_min_regret_std']:.3f} | `{st['worst_block_min_regret_name']}` |"
        )

    if "regret_portfolio_v14" in policies:
        pport = policies["regret_portfolio_v14"]
        active_w = pport.get("portfolio_active_weights", {})
        w_str = ", ".join(f"`{k}={v:.6f}`" for k, v in sorted(active_w.items()))
        realized_pooled = pport["pooled"]["realized_strategy_counts"]
        rp_str = ", ".join(f"`{k}`: `{v}`" for k, v in sorted(realized_pooled.items()))
        lines.extend([
            "",
            f"{H2} 5. Frozen `PortfolioMolePolicy` Zero-Private-Info SHA-256 Realization Audit",
            "",
            (
                f"Frozen weights fit on `{pport.get('portfolio_fit_seed_range', '6000-6199')}` ({w_str}; "
                f"`salt={pport.get('portfolio_salt', DEFAULT_PORTFOLIO_SALT)}`) select a pure strategy per seed "
                f"using only `(seed, weights)` with zero private world access. Pooled distant-seed realizations: {rp_str}."
            ),
            "",
            "| Block | Seed Range | n | Realized Pure Strategy Counts | Block Solver Acc | Block Min Regret | Block Mean Regret |",
            "|---|---|---|---|---|---|---|",
        ])
        for b in blocks:
            bname = b["name"]
            bsum = pport["blocks"][bname]
            rc_str = ", ".join(f"`{k}`:{v}" for k, v in sorted(bsum["realized_strategy_counts"].items()))
            lines.append(
                f"| `{bname}` | `{b['seed_range']}` | {bsum['n_seeds']} | {rc_str} | "
                f"{bsum['solver_acc']:.3f} | {bsum['min_regret']:+.3f} | {bsum['mean_regret']:+.3f} |"
            )

    has_anchors = any(policies[k].get("anchor_comparison") is not None for k in p_order)
    if has_anchors:
        lines.extend([
            "",
            f"{H2} 6. Out-of-Neighborhood Generalization Shift vs `6000-6999` Selection Anchors",
            "",
            "Compares pooled distant-seed metrics against each policy's original `6000-6199` (`n=200`) or `6200-6219` (`n=20` HoF held-out) anchor.",
            "",
            "| Policy | Anchor Slice (`n`) | Anchor Solver Acc -> Distant | Acc Shift | Anchor Min Regret -> Distant | Min Regret Shift | Anchor Mean Regret -> Distant | Mean Regret Shift |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for pname in p_order:
            anc = policies[pname].get("anchor_comparison")
            if anc is None:
                continue
            pl = policies[pname]["pooled"]
            lines.append(
                f"| `{pname}` | `{anc['anchor_slice']}` (`{anc['anchor_n_seeds']}`) | "
                f"{anc['anchor_solver_acc']:.3f} -> {pl['solver_acc']:.3f} | {anc['solver_acc_shift']:+.3f} | "
                f"{anc['anchor_min_regret']:+.3f} -> {pl['min_regret']:+.3f} | {anc['min_regret_shift']:+.3f} | "
                f"{anc['anchor_mean_regret']:+.3f} -> {pl['mean_regret']:+.3f} | {anc['mean_regret_shift']:+.3f} |"
            )

    lines.extend([
        "",
        f"{H2} 7. Provenance Hashes and Mole Activity Diagnostics",
        "",
        "| Policy | Rules | Mean Leaks | Mean Frames | Canon SHA-256 | Behavior SHA | Pooled Ledger Hash |",
        "|---|---|---|---|---|---|---|",
    ])
    for pname in p_order:
        prow = policies[pname]
        pl = prow["pooled"]
        bsha = f"`{prow['behavior_sha'][:12]}`" if prow["behavior_sha"] else "`seed_mixture`"
        lines.append(
            f"| `{pname}` | {prow['n_rules']} | {pl['mean_mole_leaks']:.2f} | {pl['mean_mole_frames']:.2f} | "
            f"`{prow['canonical_sha256']}` | {bsha} | `{pl['empirical_ledger_hash']}` |"
        )

    return "\n".join(lines) + "\n"


def format_seed_generalization_summary(report: Mapping[str, Any]) -> str:
    sm = report["summary"]
    cls_counts = sm["counts_by_classification"]
    header = (
        f"Distant Seed Generalization ({report['tier']} {report['tiers_version']}, "
        f"blocks={report['n_blocks']}, n={report['n_seeds_total']}): "
        f"UNIFORM_DISTANT_PASS={cls_counts['UNIFORM_DISTANT_PASS']}, "
        f"POOLED_DISTANT_PASS={cls_counts['POOLED_DISTANT_PASS']}, "
        f"DISTANT_FAIL={cls_counts['DISTANT_FAIL']}"
    )
    rows = [header]
    for pname in report["policy_order"]:
        prow = report["policies"][pname]
        pl = prow["pooled"]
        st = prow["stability"]
        rows.append(
            f"  {pname:26s} acc={pl['solver_acc']:.3f} score={pl['solver_score']:+.3f} "
            f"min_reg={pl['min_regret']:+.3f} mean_reg={pl['mean_regret']:+.3f} "
            f"blocks={st['blocks_passed_count']}/{st['total_blocks']} [{prow['classification']}]"
        )
    return "\n".join(rows)


def _find_forbidden_key(obj: Any) -> str | None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in _FORBIDDEN_PAYLOAD_KEYS:
                return ks
            nested = _find_forbidden_key(v)
            if nested is not None:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _find_forbidden_key(item)
            if nested is not None:
                return nested
    return None


def check_seed_generalization_artifacts(
    json_path: Path = DEFAULT_OUTPUT_PATH,
    md_path: Path = DEFAULT_REPORT_MD_PATH,
    max_json_bytes: int = MAX_JSON_BYTES,
) -> tuple[bool, str]:
    if not json_path.is_file():
        return False, f"FAIL: missing JSON artifact: {json_path}"
    if not md_path.is_file():
        return False, f"FAIL: missing Markdown report: {md_path}"

    raw_bytes = json_path.read_bytes()
    if len(raw_bytes) >= int(max_json_bytes):
        return False, f"FAIL: JSON artifact {json_path} exceeds size cap ({len(raw_bytes)} >= {max_json_bytes})"

    json_text = raw_bytes.decode("utf-8")
    md_text = md_path.read_text(encoding="utf-8")

    flash_35_tag = "gemini-3.5-" + "flash"
    flash_36_tag = "gemini-3.6-" + "flash"
    solver_pct_tag = "% of " + "solver"
    coauthor_tag = "co-authored-" + "by"

    for p, txt in ((json_path, json_text), (md_path, md_text)):
        if not txt.isascii():
            return False, f"FAIL: non-ASCII characters found in {p}"
        if EM_DASH in txt or EN_DASH in txt or UNICODE_MINUS in txt:
            return False, f"FAIL: forbidden dash or unicode minus found in {p}"
        low = txt.lower()
        if flash_35_tag in low or flash_36_tag in low:
            return False, f"FAIL: forbidden flash model claim in {p}"
        if solver_pct_tag in low:
            return False, f"FAIL: forbidden {solver_pct_tag} claim in {p}"
        if coauthor_tag in low:
            return False, f"FAIL: forbidden co-author trailer found in {p}"
        emp_match = _EMP_ID_PATTERN.search(txt)
        if emp_match is not None:
            return False, f"FAIL: forbidden employee identifier {emp_match.group(0)!r} found in {p}"
        for rx in _SECRET_PATTERNS:
            if rx.search(txt) is not None:
                return False, f"FAIL: forbidden raw API key pattern found in {p}"

    try:
        report = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return False, f"FAIL: invalid JSON in {json_path}: {exc}"
    if not isinstance(report, dict):
        return False, f"FAIL: expected top-level JSON object in {json_path}"

    bad_key = _find_forbidden_key(report)
    if bad_key is not None:
        return False, f"FAIL: forbidden secret key {bad_key!r} leaked in {json_path}"

    if report.get("study") != "mole_seed_generalization_v14":
        return False, f"FAIL: unexpected study name {report.get('study')!r}"
    if int(report.get("api_calls", -1)) != 0:
        return False, "FAIL: api_calls must be 0"

    try:
        parsed_blocks = parse_seed_blocks(report.get("blocks", []), enforce_hygiene=True)
        flat_seeds = validate_distant_seeds(report.get("seeds", []), enforce_hygiene=True)
    except (TypeError, ValueError) as exc:
        return False, f"FAIL: seed hygiene violation: {exc}"

    block_flat = [s for blk in parsed_blocks for s in blk.seeds]
    if flat_seeds != block_flat:
        return False, "FAIL: top-level seeds list does not match concatenated block seeds"
    if len(flat_seeds) != int(report.get("n_seeds_total", -1)):
        return False, "FAIL: n_seeds_total mismatch"
    if len(parsed_blocks) != int(report.get("n_blocks", -1)):
        return False, "FAIL: n_blocks mismatch"

    th = report.get("thresholds", {})
    b_ref = report.get("baseline_reference", {})
    policies = report.get("policies", {})
    p_order = report.get("policy_order", [])
    if (
        not isinstance(policies, dict)
        or not policies
        or not isinstance(p_order, list)
        or len(p_order) != len(policies)
        or set(policies.keys()) != set(p_order)
    ):
        return False, "FAIL: policies dictionary missing or inconsistent with policy_order"

    recomputed_counts = {cls: 0 for cls in CLASSIFICATION_VALUES}
    for pname in p_order:
        prow = policies[pname]
        if prow.get("classification") not in CLASSIFICATION_VALUES:
            return False, f"FAIL: invalid classification on {pname}: {prow.get('classification')!r}"
        pl = prow.get("pooled") or {}
        rec_pgates = pl.get("gates") or {}
        re_pgates = evaluate_pooled_gates(
            policy_valid=bool(rec_pgates.get("policy_valid", False)),
            solver_acc=float(pl["solver_acc"]),
            solver_score=float(pl["solver_score"]),
            baseline_solver_score=float(b_ref["pooled_solver_score"]),
            logs_only_acc=float(pl["logs_only_acc"]),
            accuse_most_logs_acc=float(pl["accuse_most_logs_acc"]),
            do_nothing_max_abs=float(pl["do_nothing_max_abs"]),
            stop_early_quit_max_abs=float(pl["stop_early_quit_max_abs"]),
            min_solver_acc=float(th.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC)),
            min_solver_ratio=float(th.get("min_solver_ratio", DEFAULT_MIN_SOLVER_RATIO)),
            max_logs_acc=float(th.get("max_logs_acc", DEFAULT_MAX_LOGS_ACC)),
        )
        if rec_pgates != re_pgates:
            return False, f"FAIL: pooled gate tampering on {pname}"
        if bool(prow.get("pooled_passed")) != bool(re_pgates["pooled_passed"]):
            return False, f"FAIL: pooled_passed boolean mismatch on {pname}"

        pblocks = prow.get("blocks") or {}
        b_passed_count = 0
        for blk in parsed_blocks:
            bcell = pblocks.get(blk.name)
            if not isinstance(bcell, dict):
                return False, f"FAIL: missing block {blk.name} on {pname}"
            rec_bgates = bcell.get("gates") or {}
            re_bgates = evaluate_block_gates(
                policy_valid=bool(rec_bgates.get("policy_valid", False)),
                solver_acc=float(bcell["solver_acc"]),
                solver_score=float(bcell["solver_score"]),
                baseline_solver_score=float(b_ref["block_solver_scores"][blk.name]),
                logs_only_acc=float(bcell["logs_only_acc"]),
                accuse_most_logs_acc=float(bcell["accuse_most_logs_acc"]),
                do_nothing_max_abs=float(bcell["do_nothing_max_abs"]),
                stop_early_quit_max_abs=float(bcell["stop_early_quit_max_abs"]),
                min_solver_acc=float(th.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC)),
                min_solver_ratio=float(th.get("min_solver_ratio", DEFAULT_MIN_SOLVER_RATIO)),
                max_logs_acc=float(th.get("max_logs_acc", DEFAULT_MAX_LOGS_ACC)),
            )
            if rec_bgates != re_bgates:
                return False, f"FAIL: block gate tampering on {pname} ({blk.name})"
            if bool(re_bgates["block_passed"]):
                b_passed_count += 1

        st = prow.get("stability") or {}
        if int(st.get("blocks_passed_count", -1)) != b_passed_count:
            return False, f"FAIL: blocks_passed_count mismatch on {pname}"

        exp_cls = classify_generalization_status(
            bool(re_pgates["pooled_passed"]),
            b_passed_count,
            len(parsed_blocks),
        )
        if prow.get("classification") != exp_cls:
            return (
                False,
                f"FAIL: classification mismatch on {pname}: got {prow.get('classification')!r}, expected {exp_cls!r}",
            )
        recomputed_counts[exp_cls] += 1

    sm = report.get("summary") or {}
    if sm.get("counts_by_classification") != recomputed_counts:
        return False, "FAIL: summary.counts_by_classification mismatch"

    expected_json = dumps_seed_generalization_json(report) + "\n"
    if json_text != expected_json:
        return False, f"FAIL: JSON formatting drift in {json_path}"

    expected_md = format_seed_generalization_markdown(report)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {md_path} does not match JSON ledger {json_path}"

    return (
        True,
        f"OK: {json_path.name} ({len(raw_bytes)} bytes, blocks={len(parsed_blocks)}, n={len(flat_seeds)}, "
        f"UNIFORM_DISTANT_PASS={recomputed_counts['UNIFORM_DISTANT_PASS']}, "
        f"POOLED_DISTANT_PASS={recomputed_counts['POOLED_DISTANT_PASS']}, "
        f"DISTANT_FAIL={recomputed_counts['DISTANT_FAIL']}) matches {md_path.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.seed_generalization")
    ap.add_argument("--blocks", default=DEFAULT_BLOCKS_ARG)
    ap.add_argument("--tier", default=DEFAULT_TIER)
    ap.add_argument("--policies", default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_MAX_WORKERS)
    ap.add_argument("--n-boot", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    ap.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--cache-jsonl", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report-md", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.check:
        j_path = args.out if args.out is not None else DEFAULT_OUTPUT_PATH
        m_path = args.report_md if args.report_md is not None else DEFAULT_REPORT_MD_PATH
        ok, msg = check_seed_generalization_artifacts(json_path=j_path, md_path=m_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    pol_list = [x.strip() for x in args.policies.split(",") if x.strip()] if args.policies else None
    report = run_seed_generalization_audit(
        blocks=args.blocks,
        tier=args.tier,
        policy_names=pol_list,
        workers=args.workers,
        n_boot=args.n_boot,
        bootstrap_seed=args.bootstrap_seed,
        min_solver_acc=args.min_solver_acc,
        min_solver_ratio=args.min_solver_ratio,
        max_logs_acc=args.max_logs_acc,
        enforce_seed_hygiene=True,
        cache_jsonl=args.cache_jsonl,
    )

    json_payload = dumps_seed_generalization_json(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json_payload + "\n", encoding="utf-8")

    if args.report_md is not None:
        args.report_md.parent.mkdir(parents=True, exist_ok=True)
        args.report_md.write_text(format_seed_generalization_markdown(report), encoding="utf-8")

    if args.json:
        print(json_payload)
    else:
        print(format_seed_generalization_summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
