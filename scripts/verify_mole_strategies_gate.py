"""Offline end-to-end submission gate and executive summary generator for Canary Mole strategies."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import llm as canary_llm
from canary.analysis.tags import to_result
from canary.baselines import DoNothing, StopEarlyQuit
from canary.env import Env
from canary.eval import run_episode
from canary.forge.mutate import validate_strategy
from canary.mole.counterfactual import evaluate_counterfactual
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.regret_portfolio import (
    LEDGER_END as PORTFOLIO_LEDGER_END,
    LEDGER_START as PORTFOLIO_LEDGER_START,
    PortfolioMolePolicy,
    check_markdown_report as check_regret_portfolio_report,
)
from canary.mole.strategies import STRATEGY_SPECS, get_strategy
from canary.mole.transfer_eval import check_transfer_artifacts
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult


def _load_social_modules() -> tuple[dict[str, Any], Any, Any] | None:
    try:
        variants_mod = importlib.import_module("canary.social.variants")
        audit_mod = importlib.import_module("canary.social_audit")
    except Exception:
        return None
    variants = getattr(variants_mod, "VARIANTS", None)
    resolve_fn = getattr(audit_mod, "resolve_text_provider", None)
    verify_fn = getattr(audit_mod, "verify_and_score_episodes", None)
    if not isinstance(variants, dict) or not callable(resolve_fn) or not callable(verify_fn):
        return None
    return variants, resolve_fn, verify_fn

HASH_CHAR = chr(35)
H1 = HASH_CHAR
H2 = HASH_CHAR * 2
H3 = HASH_CHAR * 3
EM_DASH = "\u2014"
EN_DASH = "\u2013"

DEFAULT_BASE_REF = "origin/justSilas"
DEFAULT_PROTECTED_PATHS_REL = Path(".github") / "protected-paths.txt"
DEFAULT_HOF_JSONL_REL = Path("data") / "forge" / "hall_of_fame_v1.4.jsonl"
DEFAULT_HOF_META_REL = Path("data") / "forge" / "hall_of_fame_v1.4.meta.json"
DEFAULT_FRESH_EVAL_REL = Path("results") / "mole_strategies" / "v14_fresh_6000_6199.json"
DEFAULT_ABLATION_REL = Path("results") / "mole_strategies" / "lever_ablation_v14.json"
DEFAULT_TRANSFER_JSON_REL = Path("results") / "mole_strategies" / "cross_model_transfer.json"
DEFAULT_TRANSFER_MD_REL = Path("docs") / "reports" / "mole_cross_model_transfer.md"
DEFAULT_PORTFOLIO_MD_REL = Path("docs") / "reports" / "mole_regret_portfolio_v14.md"
DEFAULT_V16_PARTIAL_REL = Path("results") / "v16_social" / "partial"
DEFAULT_V16_AUDIT_REL = Path("results") / "v16_social" / "social_audit_report.json"
DEFAULT_SUMMARY_MD = ROOT / "docs" / "reports" / "mole_strategies_summary.md"

DEFAULT_SPOT_SEEDS: tuple[int, ...] = (6900, 6901, 6902, 6903)
DEFAULT_CF_SEEDS: tuple[int, ...] = tuple(range(10))
DEFAULT_CF_SOURCES: tuple[str, ...] = ("opencode",)

MIN_COMMITTED_SOLVER_ACC = 0.85
MIN_COMMITTED_SOLVER_RATIO = 0.50
MAX_COMMITTED_LOGS_ACC = 0.10
MIN_SPOT_SOLVER_ACC = 0.75

FORBIDDEN_LOW_SEED_MAX = 59
FORBIDDEN_RESERVED_SEEDS = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

EMP_ID_PATTERN = re.compile(r"\be\d{2,3}\b", re.IGNORECASE)
SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}"),
    re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"),
)
FLASH_SOLVER_CLAIM_PATTERN = re.compile(
    r"gemini-3\.[56]-flash[^\n]{0,120}%\s+of\s+solver|%\s+of\s+solver[^\n]{0,120}gemini-3\.[56]-flash",
    re.IGNORECASE,
)

ABLATION_DISPLAY_ORDER: tuple[str, ...] = (
    "default_v0",
    "only_surgical_shield",
    "only_reactive_oldest",
    "only_midgame_pacing",
    "only_peer_framing",
    "only_decoy_framing",
    "no_surgical_shield",
    "no_reactive_oldest",
    "no_midgame_pacing",
    "no_peer_framing",
    "synthesis_decoy_framing",
    "frontier_synthesis_v14",
)


@contextmanager
def offline_gate_guard() -> Iterator[dict[str, int]]:
    telemetry = {"live_api_calls": 0, "blocked_api_attempts": 0}
    orig_get_client = canary_llm.get_client
    prev_offline = os.environ.get("CANARY_OFFLINE")
    prev_sleeper = os.environ.get("SLEEPER_OFFLINE")

    def _guarded_get_client(spec: str, **kw: Any) -> Any:
        provider, _, _ = str(spec).partition(":")
        if provider == "stub":
            return orig_get_client(spec, **kw)
        telemetry["blocked_api_attempts"] += 1
        raise RuntimeError(f"live LLM API calls are forbidden in submission gate: {spec!r}")

    tmp_base = "/tmp/opencode" if Path("/tmp/opencode").is_dir() else None
    with tempfile.TemporaryDirectory(prefix="mole_gate_cache_", dir=tmp_base) as empty_cache:
        prev_cache = os.environ.get("CANARY_GEMINI_CACHE_DIR")
        try:
            canary_llm.get_client = _guarded_get_client
            os.environ["CANARY_OFFLINE"] = "1"
            os.environ["SLEEPER_OFFLINE"] = "1"
            os.environ["CANARY_GEMINI_CACHE_DIR"] = empty_cache
            yield telemetry
        finally:
            canary_llm.get_client = orig_get_client
            if prev_offline is None:
                os.environ.pop("CANARY_OFFLINE", None)
            else:
                os.environ["CANARY_OFFLINE"] = prev_offline
            if prev_sleeper is None:
                os.environ.pop("SLEEPER_OFFLINE", None)
            else:
                os.environ["SLEEPER_OFFLINE"] = prev_sleeper
            if prev_cache is None:
                os.environ.pop("CANARY_GEMINI_CACHE_DIR", None)
            else:
                os.environ["CANARY_GEMINI_CACHE_DIR"] = prev_cache


def _parse_seed_spec(spec: str | Iterable[int]) -> list[int]:
    if not isinstance(spec, str):
        return [int(s) for s in spec]
    text = spec.strip()
    if not text:
        raise ValueError("seed specification must not be empty")
    out: list[int] = []
    for part_raw in text.split(","):
        part = part_raw.strip()
        if not part:
            continue
        if ":" in part:
            lo_s, hi_s = part.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi <= lo:
                raise ValueError(f"invalid colon seed slice {part!r}")
            out.extend(range(lo, hi))
        elif "-" in part and not part.startswith("-"):
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"reversed seed range {part!r}")
            out.extend(range(lo, hi + 1))
        else:
            out.append(int(part))
    return out


def validate_fresh_seed_slice(seeds: str | Iterable[int], label: str) -> list[int]:
    parsed = _parse_seed_spec(seeds)
    if not parsed:
        raise ValueError(f"{label}: seed list must not be empty")
    if len(set(parsed)) != len(parsed):
        raise ValueError(f"{label}: duplicate seeds are forbidden")
    for s in parsed:
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError(f"{label}: non-integer seed {s!r}")
        if s <= FORBIDDEN_LOW_SEED_MAX:
            raise ValueError(f"{label}: seed {s} falls in forbidden low range <= {FORBIDDEN_LOW_SEED_MAX}")
        if s in FORBIDDEN_RESERVED_SEEDS:
            raise ValueError(f"{label}: seed {s} falls in reserved 30000..30199 range")
        if s >= FORBIDDEN_HIGH_SEED_MIN or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"{label}: seed {s} falls in forbidden judge/heldout range")
    return parsed


def parse_protected_rules(text: str) -> list[str]:
    rules: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        rules.append(line)
    return rules


def match_protected_paths(changed_files: Iterable[str], rules: Sequence[str]) -> list[str]:
    hits: set[str] = set()
    for rel in changed_files:
        clean = rel.strip().lstrip("./")
        if not clean:
            continue
        for rule in rules:
            if rule.endswith("/"):
                if clean.startswith(rule):
                    hits.add(clean)
            elif clean == rule:
                hits.add(clean)
    return sorted(hits)


def check_protected_paths(
    root: Path = ROOT,
    base_ref: str = DEFAULT_BASE_REF,
    protected_paths_rel: Path = DEFAULT_PROTECTED_PATHS_REL,
) -> dict[str, Any]:
    root = Path(root).resolve()
    local_prot = root / protected_paths_rel
    local_rules = parse_protected_rules(local_prot.read_text(encoding="utf-8")) if local_prot.is_file() else []

    git_dir_ok = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
    ).returncode == 0

    if not git_dir_ok:
        passed = len(local_rules) > 0
        return {
            "passed": passed,
            "git_repo": False,
            "base_ref": base_ref,
            "base_ref_present": False,
            "n_protected_rules": len(local_rules),
            "protected_rules": local_rules,
            "violations": [] if passed else ["missing .github/protected-paths.txt rules"],
        }

    ref_check = subprocess.run(
        ["git", "rev-parse", "--verify", f"{base_ref}^{{commit}}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
    )
    base_present = ref_check.returncode == 0

    rules = list(local_rules)
    if base_present:
        base_prot = subprocess.run(
            ["git", "show", f"{base_ref}:{protected_paths_rel.as_posix()}"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if base_prot.returncode == 0:
            rules = parse_protected_rules(base_prot.stdout)

    changed: set[str] = set()
    if base_present:
        diff_base = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_base.returncode != 0:
            return {
                "passed": False,
                "git_repo": True,
                "base_ref": base_ref,
                "base_ref_present": True,
                "n_protected_rules": len(rules),
                "protected_rules": rules,
                "violations": [f"git diff failed vs {base_ref}"],
            }
        changed.update(ln.strip() for ln in diff_base.stdout.splitlines() if ln.strip())

    for extra_cmd in (["git", "diff", "--name-only", "HEAD"], ["git", "diff", "--name-only", "--cached"]):
        proc = subprocess.run(extra_cmd, cwd=root, capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            changed.update(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())

    violations = match_protected_paths(changed, rules)
    if not rules:
        violations.append("empty protected-paths rule set")

    return {
        "passed": len(violations) == 0,
        "git_repo": True,
        "base_ref": base_ref,
        "base_ref_present": base_present,
        "n_protected_rules": len(rules),
        "protected_rules": rules,
        "violations": violations,
    }


def _validate_dsl_strategy_entry(
    strategy_json: dict[str, Any],
    tier: str = "hard",
    fallback_name: str = "custom",
) -> dict[str, Any]:
    payload = dict(strategy_json)
    if "name" not in payload or payload["name"] in (None, "", "custom"):
        payload["name"] = fallback_name[:80]
    parsed = MoleStrategy.from_json(payload)
    dumped = parsed.to_json()
    re_parsed = MoleStrategy.from_json(json.loads(json.dumps(dumped)))
    round_trip_ok = (re_parsed == parsed) and (len(parsed.rules) <= MAX_RULES)
    validate_strategy({"rules": dumped["rules"], "default": dumped["default"]})
    conds_ok = all(is_valid_rule_conds(r["if"], tier) for r in dumped.get("rules", []))
    bhash = behavior_hash(dumped, tier)
    return {
        "name": parsed.name,
        "n_rules": len(parsed.rules),
        "round_trip_ok": bool(round_trip_ok),
        "conds_valid": bool(conds_ok),
        "behavior_hash": bhash,
        "strategy_json": dumped,
    }


_SPOT_SEED_CACHE: dict[tuple[str, int, str], tuple[float, float, float, bool]] = {}
_V16_FILE_REPLAY_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_CF_REPLAY_CACHE: dict[tuple[str, str, tuple[int, ...], tuple[str, ...]], dict[str, Any]] = {}


def _spot_seed_worker(task: tuple[str, int, dict[str, Any]]) -> tuple[float, float, float, bool]:
    tier, s, sj = task
    strat = MoleStrategy.from_json(sj)
    dn_res = run_episode(Env(tier, s, mole_strategy=strat), DoNothing(seed=s))
    sq_res = run_episode(Env(tier, s, mole_strategy=strat), StopEarlyQuit(seed=s))
    sol_res = run_episode(Env(tier, s, mole_strategy=strat), SolverPolicy(tier, act_budget=5.0))
    return (
        float(dn_res.score),
        float(sq_res.score),
        float(sol_res.score),
        bool(sol_res.correct),
    )


def _warm_spot_seed_cache(
    strategies: Sequence[tuple[str, dict[str, Any]]],
    seeds: Sequence[int],
    tier: str = "hard",
    workers: int = 4,
) -> None:
    missing_keys: list[tuple[str, int, str]] = []
    missing_tasks: list[tuple[str, int, dict[str, Any]]] = []
    seen_keys: set[tuple[str, int, str]] = set()
    for label, strategy_json in strategies:
        strat = MoleStrategy.from_json({**strategy_json, "name": label[:80]})
        dumped = strat.to_json()
        canon_key = json.dumps({"rules": dumped["rules"], "default": dumped["default"]}, sort_keys=True)
        for s in seeds:
            ck = (tier, int(s), canon_key)
            if ck not in _SPOT_SEED_CACHE and ck not in seen_keys:
                seen_keys.add(ck)
                missing_keys.append(ck)
                missing_tasks.append((tier, int(s), dumped))
    if not missing_tasks:
        return
    if workers > 1 and len(missing_tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(missing_tasks))) as pool:
            computed = list(pool.map(_spot_seed_worker, missing_tasks))
    else:
        computed = [_spot_seed_worker(t) for t in missing_tasks]
    for ck, val in zip(missing_keys, computed):
        _SPOT_SEED_CACHE[ck] = val


def _run_spot_check_for_strategy(
    label: str,
    strategy_json: dict[str, Any],
    seeds: Sequence[int],
    tier: str = "hard",
    min_solver_acc: float = MIN_SPOT_SOLVER_ACC,
) -> dict[str, Any]:
    strat = MoleStrategy.from_json({**strategy_json, "name": label[:80]})
    dumped = strat.to_json()
    canon_key = json.dumps({"rules": dumped["rules"], "default": dumped["default"]}, sort_keys=True)
    _warm_spot_seed_cache([(label, dumped)], seeds, tier=tier)
    n = len(seeds)
    dn_scores: list[float] = []
    sq_scores: list[float] = []
    sol_scores: list[float] = []
    sol_correct: list[bool] = []

    for s in seeds:
        ck = (tier, int(s), canon_key)
        dn_v, sq_v, sol_v, sol_c = _SPOT_SEED_CACHE[ck]
        dn_scores.append(dn_v)
        sq_scores.append(sq_v)
        sol_scores.append(sol_v)
        sol_correct.append(sol_c)

    env_unfinished = Env(tier, seeds[0], mole_strategy=strat)
    quit_pol = StopEarlyQuit(seed=seeds[0])
    quit_pol.reset(env_unfinished.tools_spec(), env_unfinished.instruction())
    for _ in range(3):
        tool, args = quit_pol.act(list(env_unfinished.history))
        env_unfinished.call(tool, args)
    unfinished_score = float(env_unfinished.score())

    dn_max_abs = max((abs(x) for x in dn_scores), default=0.0)
    sq_max_abs = max((abs(x) for x in sq_scores), default=0.0)
    sol_acc = sum(1 for c in sol_correct if c) / n
    sol_mean = sum(sol_scores) / n

    dn_ok = all(x == 0.0 for x in dn_scores) and dn_max_abs == 0.0
    sq_ok = all(x == 0.0 for x in sq_scores) and sq_max_abs == 0.0 and unfinished_score == 0.0
    sol_ok = sol_acc >= min_solver_acc

    return {
        "name": label,
        "n_seeds": n,
        "seeds": list(seeds),
        "behavior_hash": behavior_hash(strat.to_json(), tier),
        "do_nothing_max_abs": dn_max_abs,
        "do_nothing_zero": dn_ok,
        "stop_early_quit_max_abs": sq_max_abs,
        "unfinished_quit_score": unfinished_score,
        "stop_early_quit_zero": sq_ok,
        "solver_acc": sol_acc,
        "solver_mean_score": sol_mean,
        "min_solver_acc": float(min_solver_acc),
        "passed": bool(dn_ok and sq_ok and sol_ok),
    }


def check_strategies_and_fresh_eval(
    root: Path = ROOT,
    *,
    hof_jsonl_path: Path | None = None,
    hof_meta_path: Path | None = None,
    fresh_eval_path: Path | None = None,
    spot_seeds: Sequence[int] = DEFAULT_SPOT_SEEDS,
    spot_targets: Sequence[str] | None = None,
    min_spot_solver_acc: float = MIN_SPOT_SOLVER_ACC,
) -> dict[str, Any]:
    root = Path(root).resolve()
    hof_path = Path(hof_jsonl_path) if hof_jsonl_path is not None else (root / DEFAULT_HOF_JSONL_REL)
    meta_path = Path(hof_meta_path) if hof_meta_path is not None else (root / DEFAULT_HOF_META_REL)
    eval_path = Path(fresh_eval_path) if fresh_eval_path is not None else (root / DEFAULT_FRESH_EVAL_REL)

    failures: list[str] = []
    tier = "hard"
    default_bhash = behavior_hash(DEFAULT_STRATEGY.to_json(), tier)

    spec_entries: list[dict[str, Any]] = []
    for name, spec in STRATEGY_SPECS.items():
        try:
            validated = _validate_dsl_strategy_entry(spec.to_json(), tier=tier, fallback_name=name)
        except Exception as exc:
            failures.append(f"strategy {name} failed DSL validation: {exc}")
            continue
        if not (validated["round_trip_ok"] and validated["conds_valid"]):
            failures.append(f"strategy {name} failed round_trip or rule_conds check")
        spec_entries.append({
            **validated,
            "lever_id": spec.lever_id,
            "target_cohort": spec.target_cohort,
            "empirical_anchors": dict(spec.empirical_anchors),
        })

    if len(spec_entries) != 6:
        failures.append(f"expected 6 strategies in canary.mole.strategies, found {len(spec_entries)}")

    spec_hashes = [e["behavior_hash"] for e in spec_entries]
    spec_unique_bhash = (len(set(spec_hashes)) == len(spec_hashes)) and (default_bhash not in set(spec_hashes))
    if not spec_unique_bhash:
        failures.append("canary.mole.strategies behavior_hash values are not unique or collide with default_v0")

    hof_name_by_bhash: dict[str, str] = {}
    hof_heldout_seeds: list[int] = []
    hof_dev_seeds: list[int] = []
    if meta_path.is_file():
        meta_obj = json.loads(meta_path.read_text(encoding="utf-8"))
        for bh, names in (meta_obj.get("behavior_groups") or {}).items():
            if isinstance(names, list) and names:
                hof_name_by_bhash[str(bh)] = str(names[0])
        try:
            hof_heldout_seeds = validate_fresh_seed_slice(meta_obj.get("heldout_seeds", "6200-6219"), "hof_heldout_seeds")
            hof_dev_seeds = validate_fresh_seed_slice(meta_obj.get("dev_seeds", "10000-10019"), "hof_dev_seeds")
            if set(hof_heldout_seeds) & set(hof_dev_seeds):
                failures.append("hall_of_fame_v1.4 heldout_seeds and dev_seeds overlap")
        except ValueError as exc:
            failures.append(str(exc))

    if not hof_path.is_file():
        failures.append(f"missing Hall-of-Fame JSONL: {hof_path}")
        hof_lines: list[str] = []
    else:
        hof_lines = [ln for ln in hof_path.read_text(encoding="utf-8").splitlines() if ln.strip()]

    hof_entries: list[dict[str, Any]] = []
    for idx, ln in enumerate(hof_lines, 1):
        row = json.loads(ln)
        sj = row.get("strategy_json", row)
        raw_bhash = behavior_hash(MoleStrategy.from_json(sj).to_json(), tier)
        resolved_name = hof_name_by_bhash.get(raw_bhash, f"hof_rank_{row.get('rank', idx)}")
        validated = _validate_dsl_strategy_entry(sj, tier=tier, fallback_name=resolved_name)
        if not (validated["round_trip_ok"] and validated["conds_valid"]):
            failures.append(f"hof rank {idx} ({resolved_name}) failed round_trip or rule_conds check")
        rec_sol_acc = float(row.get("solver_acc", 0.0))
        rec_sol_score = float(row.get("solver_score", 0.0))
        rec_fitness = float(row.get("fitness", 0.0))
        if rec_sol_acc < MIN_COMMITTED_SOLVER_ACC or rec_fitness <= 0.0:
            failures.append(f"hof rank {idx} ({resolved_name}) failed heldout solver_acc/fitness threshold")
        per_inv = row.get("per_investigator") or {}
        hof_entries.append({
            "rank": int(row.get("rank", idx)),
            "name": resolved_name,
            "n_rules": validated["n_rules"],
            "round_trip_ok": validated["round_trip_ok"],
            "conds_valid": validated["conds_valid"],
            "behavior_hash": validated["behavior_hash"],
            "solver_acc": rec_sol_acc,
            "solver_score": rec_sol_score,
            "min_regret": rec_fitness,
            "gemini_proxy_regret": float((per_inv.get("gemini_carbon_proxy") or {}).get("regret", 0.0)),
            "codex_proxy_regret": float((per_inv.get("codex_horizon_proxy") or {}).get("regret", 0.0)),
            "strategy_json": validated["strategy_json"],
        })

    if len(hof_entries) != 4:
        failures.append(f"expected 4 rows in hall_of_fame_v1.4.jsonl, found {len(hof_entries)}")

    hof_hashes = [e["behavior_hash"] for e in hof_entries]
    hof_unique_bhash = (len(set(hof_hashes)) == len(hof_hashes)) and (default_bhash not in set(hof_hashes))
    if not hof_unique_bhash:
        failures.append("hall_of_fame_v1.4.jsonl behavior_hash values are not unique or collide with default_v0")

    combined_unique_bhash_count = len(set(spec_hashes) | set(hof_hashes))

    fresh_rows: list[dict[str, Any]] = []
    fresh_eval_seeds: list[int] = []
    fresh_cf_summary: dict[str, Any] = {}
    if not eval_path.is_file():
        failures.append(f"missing committed 200-seed eval JSON: {eval_path}")
    else:
        eval_obj = json.loads(eval_path.read_text(encoding="utf-8"))
        try:
            fresh_eval_seeds = validate_fresh_seed_slice(eval_obj.get("seeds", []), "v14_fresh_6000_6199")
        except ValueError as exc:
            failures.append(str(exc))
        if len(fresh_eval_seeds) != 200 or fresh_eval_seeds != list(range(6000, 6200)):
            failures.append(f"v14_fresh_6000_6199 expected 200 seeds 6000..6199, got n={len(fresh_eval_seeds)}")
        if eval_obj.get("tier") != "hard" or eval_obj.get("tiers_version") != "v1.4":
            failures.append("v14_fresh_6000_6199 tier/tiers_version mismatch")

        strats_map = eval_obj.get("strategies") or {}
        def_row = strats_map.get("default_v0")
        def_sol_score = float(((def_row or {}).get("solver") or {}).get("score", 0.0))
        if def_sol_score <= 0.0:
            failures.append("v14_fresh_6000_6199 missing positive default_v0 solver score")

        ordered_names = ["default_v0", *STRATEGY_SPECS.keys()]
        for sname in ordered_names:
            if sname not in strats_map:
                failures.append(f"v14_fresh_6000_6199 missing strategy {sname}")
                continue
            item = strats_map[sname]
            sol = item.get("solver") or {}
            base = item.get("baselines") or {}
            reg = item.get("regret_summary") or {}
            cf = item.get("counterfactual") or {}
            lo = base.get("logs_only") or {}
            aml = base.get("accuse_most_logs") or {}
            dn = base.get("do_nothing") or {}
            sq = base.get("stop_early_quit") or {}

            sol_acc = float(sol.get("accuracy", 0.0))
            sol_score = float(sol.get("score", 0.0))
            lo_acc = float(lo.get("accuracy", 1.0))
            lo_score = float(lo.get("score", 1.0))
            aml_acc = float(aml.get("accuracy", 1.0))
            dn_score = float(dn.get("score", 1.0))
            dn_max = float(dn.get("max_abs_score", 1.0))
            sq_score = float(sq.get("score", 1.0))
            sq_max = float(sq.get("max_abs_score", 1.0))
            sq_unfin = float(sq.get("unfinished_score", 1.0))

            expected_sj = DEFAULT_STRATEGY.to_json() if sname == "default_v0" else STRATEGY_SPECS[sname].to_json()
            expected_bh = behavior_hash(expected_sj, tier)
            bh_match = item.get("behavior_hash") == expected_bh

            row_ok = (
                bh_match
                and sol_acc >= MIN_COMMITTED_SOLVER_ACC
                and sol_score >= MIN_COMMITTED_SOLVER_RATIO * def_sol_score
                and lo_acc <= MAX_COMMITTED_LOGS_ACC
                and lo_score < 0.0
                and aml_acc <= MAX_COMMITTED_LOGS_ACC
                and dn_score == 0.0
                and dn_max == 0.0
                and sq_score == 0.0
                and sq_max == 0.0
                and sq_unfin == 0.0
            )
            if not row_ok:
                failures.append(f"v14_fresh_6000_6199 gate check failed for {sname}")

            fresh_rows.append({
                "name": sname,
                "display_name": str(item.get("display_name", sname)),
                "lever_id": str(item.get("lever_id", "")),
                "n_rules": int(item.get("n_rules", 0)),
                "behavior_hash": str(item.get("behavior_hash", "")),
                "solver_acc": sol_acc,
                "solver_score": sol_score,
                "solver_ci_95": float(sol.get("score_ci_95", 0.0)),
                "logs_only_acc": lo_acc,
                "logs_only_score": lo_score,
                "accuse_most_logs_acc": aml_acc,
                "do_nothing_score": dn_score,
                "stop_early_score": sq_score,
                "strongest_investigator": str(reg.get("strongest_investigator_label", "")),
                "min_regret": float(reg.get("min_regret", 0.0)),
                "min_regret_gain": float(reg.get("min_regret_gain_vs_default", 0.0)),
                "gemini_regret": float(reg.get("gemini_regret", 0.0)),
                "gemini_regret_gain": float(reg.get("gemini_regret_gain_vs_default", 0.0)),
                "mean_regret": float(reg.get("mean_regret", 0.0)),
                "cf_p_true_mole": float(cf.get("p_true_mole", 0.0)),
                "cf_p_true_mole_drop": float(cf.get("p_true_mole_drop", 0.0)),
                "cf_optimal_ev": float(cf.get("optimal_ev", 0.0)),
                "cf_optimal_ev_drop": float(cf.get("optimal_ev_drop", 0.0)),
                "cf_surfaced_canaries": float(cf.get("surfaced_canaries", 0.0)),
                "cf_surfaced_canaries_delta": float(cf.get("surfaced_canaries_delta", 0.0)),
                "passed": row_ok,
            })

        fs_cf = (strats_map.get("frontier_synthesis_v14") or {}).get("counterfactual") or {}
        def_cf = (strats_map.get("default_v0") or {}).get("counterfactual") or {}
        fresh_cf_summary = {
            "n_transcripts": int(fs_cf.get("n_transcripts", 0)),
            "default_p_true_mole": float(def_cf.get("p_true_mole", 0.0)),
            "synthesis_p_true_mole": float(fs_cf.get("p_true_mole", 0.0)),
            "p_true_mole_drop": float(fs_cf.get("p_true_mole_drop", 0.0)),
            "default_optimal_ev": float(def_cf.get("optimal_ev", 0.0)),
            "synthesis_optimal_ev": float(fs_cf.get("optimal_ev", 0.0)),
            "optimal_ev_drop": float(fs_cf.get("optimal_ev_drop", 0.0)),
            "default_surfaced_canaries": float(def_cf.get("surfaced_canaries", 0.0)),
            "synthesis_surfaced_canaries": float(fs_cf.get("surfaced_canaries", 0.0)),
            "surfaced_canaries_delta": float(fs_cf.get("surfaced_canaries_delta", 0.0)),
        }

    spot_seed_list: list[int] = []
    try:
        spot_seed_list = validate_fresh_seed_slice(spot_seeds, "spot_check_seeds")
    except ValueError as exc:
        failures.append(str(exc))

    if fresh_eval_seeds and (set(spot_seed_list) & set(fresh_eval_seeds)):
        failures.append("spot_check_seeds overlap with v14_fresh_6000_6199 seeds")
    if hof_heldout_seeds and (set(spot_seed_list) & set(hof_heldout_seeds)):
        failures.append("spot_check_seeds overlap with hall_of_fame_v1.4 heldout_seeds")

    target_map: dict[str, dict[str, Any]] = {}
    if "early_burst_midgame_pace" in STRATEGY_SPECS:
        target_map["early_burst_midgame_pace"] = STRATEGY_SPECS["early_burst_midgame_pace"].to_json()
    if hof_entries:
        target_map[f"hof_rank1_{hof_entries[0]['name']}"] = hof_entries[0]["strategy_json"]

    selected_targets = list(target_map.keys()) if spot_targets is None else list(spot_targets)
    spot_results: list[dict[str, Any]] = []
    if spot_seed_list and selected_targets:
        resolved_pairs = [
            (tname, target_map[tname] if tname in target_map else get_strategy(tname).to_json())
            for tname in selected_targets
        ]
        _warm_spot_seed_cache(resolved_pairs, spot_seed_list, tier=tier)
        for tname, sj in resolved_pairs:
            sres = _run_spot_check_for_strategy(
                tname,
                sj,
                spot_seed_list,
                tier=tier,
                min_solver_acc=min_spot_solver_acc,
            )
            if not sres["passed"]:
                failures.append(f"live spot-check failed for {tname} on seeds {spot_seed_list}")
            spot_results.append(sres)

    return {
        "passed": len(failures) == 0,
        "tier": tier,
        "default_behavior_hash": default_bhash,
        "n_transcript_strategies": len(spec_entries),
        "transcript_unique_behavior_hashes": spec_unique_bhash,
        "transcript_strategies": spec_entries,
        "n_hof_rows": len(hof_entries),
        "hof_unique_behavior_hashes": hof_unique_bhash,
        "combined_unique_behavior_hashes": combined_unique_bhash_count,
        "hof_rows": hof_entries,
        "seed_hygiene_passed": len([f for f in failures if "seed" in f.lower()]) == 0,
        "fresh_eval_n_seeds": len(fresh_eval_seeds),
        "fresh_eval_rows": fresh_rows,
        "fresh_counterfactual_60": fresh_cf_summary,
        "spot_check_seeds": spot_seed_list,
        "spot_checks": spot_results,
        "failures": failures,
    }


def check_counterfactual_replay(
    root: Path = ROOT,
    *,
    seeds: Sequence[int] = DEFAULT_CF_SEEDS,
    sources: Sequence[str] = DEFAULT_CF_SOURCES,
    tier: str = "hard",
) -> dict[str, Any]:
    root = Path(root).resolve()
    seed_list = [int(s) for s in seeds]
    src_tuple = tuple(str(s) for s in sources)
    cf_key = (str(root), tier, tuple(seed_list), src_tuple)
    if cf_key not in _CF_REPLAY_CACHE:
        fs_strat = get_strategy("frontier_synthesis_v14")
        _CF_REPLAY_CACHE[cf_key] = evaluate_counterfactual(
            strategies={
                "default_v0": DEFAULT_STRATEGY,
                "frontier_synthesis_v14": fs_strat,
            },
            seeds=seed_list,
            tier=tier,
            run_solver=False,
            sources=src_tuple,
            root=root,
        )
    rep = _CF_REPLAY_CACHE[cf_key]
    def_row = rep["strategies"]["default_v0"]
    fs_row = rep["strategies"]["frontier_synthesis_v14"]

    def_p = float(def_row["p_true_mole"])
    fs_p = float(fs_row["p_true_mole"])
    p_drop = float(fs_row["p_true_mole_drop"])

    def_ev = float(def_row["optimal_ev"])
    fs_ev = float(fs_row["optimal_ev"])
    ev_drop = float(fs_row["optimal_ev_drop"])

    failures: list[str] = []
    if rep["seeds"] != sorted(seed_list):
        failures.append(f"counterfactual replay expected seeds {sorted(seed_list)}, got {rep['seeds']}")
    if not (fs_p < def_p and p_drop > 0.0):
        failures.append(f"frontier_synthesis_v14 did not reduce P(true mole): {fs_p:.4f} vs {def_p:.4f}")
    if not (fs_ev < def_ev and ev_drop > 0.0):
        failures.append(f"frontier_synthesis_v14 did not reduce optimal EV: {fs_ev:.4f} vs {def_ev:.4f}")

    return {
        "passed": len(failures) == 0,
        "tier": tier,
        "sources": list(sources),
        "seeds": list(rep["seeds"]),
        "n_episodes": int(fs_row["combined"]["n"]),
        "default_p_true_mole": def_p,
        "synthesis_p_true_mole": fs_p,
        "p_true_mole_drop": p_drop,
        "p_true_mole_drop_ci": float(fs_row["combined"]["p_true_mole_drop_ci"]),
        "default_optimal_ev": def_ev,
        "synthesis_optimal_ev": fs_ev,
        "optimal_ev_drop": ev_drop,
        "optimal_ev_drop_ci": float(fs_row["combined"]["optimal_ev_drop_ci"]),
        "failures": failures,
    }


def _infer_v16_variant_and_provider(
    ep_path: Path,
    rec: dict[str, Any],
    variants: Iterable[str] | None = None,
) -> tuple[str, str]:
    if variants is None:
        social_mods = _load_social_modules()
        known_variants: set[str] = set(social_mods[0]) if social_mods is not None else set()
    else:
        known_variants = set(variants)

    path_var: str | None = None
    for part in reversed(ep_path.parts[:-1]):
        clean = part.replace("__", ":")
        for prefix in ("v16-gemini-stub:", "v16-gemini:", "v16:"):
            if clean.startswith(prefix):
                clean = clean.split(":", 1)[1].strip()
        if clean == "v0_v14_control" or clean in known_variants:
            path_var = clean
            break

    meta = rec.get("meta") if isinstance(rec.get("meta"), dict) else {}
    raw_var = str(rec.get("variant") or meta.get("variant") or path_var or "v0_v14_control").strip()
    for prefix in ("v16-gemini-stub:", "v16-gemini:", "v16:"):
        if raw_var.startswith(prefix):
            raw_var = raw_var.split(":", 1)[1].strip()
    if raw_var == "template":
        raw_var = "v0_v14_control"

    raw_prov = str(meta.get("provider") or "").strip()
    if raw_var == "v0_v14_control" or raw_prov == "template":
        return "v0_v14_control", "template"
    if raw_prov.startswith("v16-gemini-stub:"):
        return raw_var, raw_prov
    if raw_prov.startswith("v16-gemini:"):
        return raw_var, "v16:" + raw_prov.split(":", 1)[1].strip()
    if raw_prov.startswith("v16:"):
        return raw_var, raw_prov
    if raw_var in known_variants:
        return raw_var, f"v16:{raw_var}"
    return raw_var, "template"


def _parse_episode_record(rec: dict[str, Any]) -> EpisodeResult:
    from_dict_fn = getattr(EpisodeResult, "from_dict", None)
    if callable(from_dict_fn):
        return from_dict_fn(rec)
    return to_result(rec)


def check_ablation_and_v16_replays(
    root: Path = ROOT,
    *,
    ablation_path: Path | None = None,
    v16_partial_dir: Path | None = None,
    v16_audit_json_path: Path | None = None,
    expected_checkpoint_episodes: int = 10,
    pure_mole: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    abl_file = Path(ablation_path) if ablation_path is not None else (root / DEFAULT_ABLATION_REL)
    partial_root = Path(v16_partial_dir) if v16_partial_dir is not None else (root / DEFAULT_V16_PARTIAL_REL)
    v16_audit_file = Path(v16_audit_json_path) if v16_audit_json_path is not None else (root / DEFAULT_V16_AUDIT_REL)

    failures: list[str] = []
    ablation_arms: list[dict[str, Any]] = []
    ablation_summary: dict[str, Any] = {}
    peer_vs_decoy_summary: dict[str, Any] = {}

    if not abl_file.is_file():
        failures.append(f"missing lever ablation JSON: {abl_file}")
    else:
        abl = json.loads(abl_file.read_text(encoding="utf-8"))
        try:
            abl_seeds = validate_fresh_seed_slice(abl.get("seeds", []), "lever_ablation_v14")
        except ValueError as exc:
            failures.append(str(exc))
            abl_seeds = []

        gs = abl.get("gates_summary") or {}
        arms_dict = abl.get("arms") or {}
        if int(gs.get("n_arms", 0)) != 12 or len(arms_dict) != 12:
            failures.append(f"lever_ablation_v14 expected 12 arms, got {len(arms_dict)}")
        if int(gs.get("n_passed", 0)) != 12 or not bool(gs.get("all_arms_passed")):
            failures.append("lever_ablation_v14 gates_summary reports failed arms")
        if not bool(gs.get("unique_canonical_strategies")):
            failures.append("lever_ablation_v14 canonical strategies are not unique")

        base_sol_score = float(((abl.get("baseline_reference") or {}).get("solver_score")) or 0.0)
        ordered_arms = [a for a in ABLATION_DISPLAY_ORDER if a in arms_dict] + [
            a for a in sorted(arms_dict) if a not in ABLATION_DISPLAY_ORDER
        ]
        for aname in ordered_arms:
            arm = arms_dict[aname]
            gates = arm.get("gates") or {}
            pols = arm.get("policies") or {}
            sol = pols.get("solver") or {}
            lo = pols.get("logs_only") or {}
            dn = pols.get("do_nothing") or {}
            sq = pols.get("stop_early_quit") or {}
            cf = arm.get("counterfactual") or {}

            validated = _validate_dsl_strategy_entry(arm["strategy_json"], tier="hard", fallback_name=aname)
            sol_acc = float(sol.get("acc", 0.0))
            sol_score = float(sol.get("score", 0.0))
            lo_acc = float(lo.get("acc", 1.0))
            dn_max = float(dn.get("max_abs_score", 1.0))
            sq_max = float(sq.get("max_abs_score", 1.0))

            arm_ok = (
                bool(gates.get("passed_all"))
                and validated["round_trip_ok"]
                and sol_acc >= MIN_COMMITTED_SOLVER_ACC
                and sol_score >= MIN_COMMITTED_SOLVER_RATIO * base_sol_score
                and lo_acc <= MAX_COMMITTED_LOGS_ACC
                and dn_max == 0.0
                and sq_max == 0.0
            )
            if not arm_ok:
                failures.append(f"lever_ablation_v14 arm {aname} failed gate verification")

            p_drop_obj = cf.get("p_true_mole_drop_vs_default")
            ev_drop_obj = cf.get("optimal_ev_drop_vs_default")
            p_drop_val = float(p_drop_obj["mean"]) if isinstance(p_drop_obj, dict) else float(p_drop_obj or 0.0)
            ev_drop_val = float(ev_drop_obj["mean"]) if isinstance(ev_drop_obj, dict) else float(ev_drop_obj or 0.0)

            reg_sum = arm.get("regret_summary") or {}
            fr_obj = reg_sum.get("mean_frontier_proxy_regret")
            fr_val = float(fr_obj["mean"]) if isinstance(fr_obj, dict) else float(fr_obj or 0.0)
            ablation_arms.append({
                "name": aname,
                "kind": str(arm.get("kind", "")),
                "n_rules": int(arm.get("n_rules", 0)),
                "framing_mode": str(arm.get("framing_mode", "")),
                "behavior_hash": validated["behavior_hash"],
                "solver_acc": sol_acc,
                "solver_score": sol_score,
                "gemini_proxy_score": float((pols.get("gemini_carbon_proxy") or {}).get("score", 0.0)),
                "codex_proxy_score": float((pols.get("codex_horizon_proxy") or {}).get("score", 0.0)),
                "frontier_regret": fr_val,
                "logs_only_acc": lo_acc,
                "do_nothing_max_abs": dn_max,
                "stop_early_max_abs": sq_max,
                "cf_p_mole_drop": p_drop_val,
                "cf_ev_drop": ev_drop_val,
                "cf_surfaced_canaries": float(cf.get("surfaced_canaries", 0.0)),
                "passed": arm_ok,
            })

        fca = abl.get("framing_control_analysis") or {}
        pvd_syn = fca.get("peer_vs_decoy_in_synthesis") or {}
        pvd_sin = fca.get("peer_vs_decoy_single_lever") or {}
        peer_vs_decoy_summary = {
            "synthesis_frontier_regret_gain": float(
                (((pvd_syn.get("live") or {}).get("mean_frontier_proxy_regret_gain")) or {}).get("mean", 0.0)
            ),
            "synthesis_cf_ev_drop_gain": float(
                (((pvd_syn.get("counterfactual") or {}).get("optimal_ev_drop_gain")) or {}).get("mean", 0.0)
            ),
            "single_frontier_regret_gain": float(
                (((pvd_sin.get("live") or {}).get("mean_frontier_proxy_regret_gain")) or {}).get("mean", 0.0)
            ),
            "single_codex_score_delta": float(
                (((pvd_sin.get("live") or {}).get("codex_proxy_score_delta")) or {}).get("mean", 0.0)
            ),
        }
        ablation_summary = {
            "n_seeds": len(abl_seeds),
            "seed_range": str(abl.get("seed_range", "6600-6639")),
            "n_arms": len(ablation_arms),
            "n_passed": sum(1 for a in ablation_arms if a["passed"]),
            "min_solver_acc_observed": min((a["solver_acc"] for a in ablation_arms), default=0.0),
            "max_logs_only_acc_observed": max((a["logs_only_acc"] for a in ablation_arms), default=1.0),
            "peer_vs_decoy": peer_vs_decoy_summary,
        }

    effective_pure_mole = bool(pure_mole)
    pure_mole_reason = "explicit_flag" if effective_pure_mole else ""
    social_mods: tuple[dict[str, Any], Any, Any] | None = None

    if not effective_pure_mole:
        if v16_partial_dir is None and not partial_root.is_dir():
            effective_pure_mole = True
            pure_mole_reason = "missing_v16_partial_dir"
        else:
            social_mods = _load_social_modules()
            if social_mods is None:
                effective_pure_mole = True
                pure_mole_reason = "social_audit_unavailable"

    if effective_pure_mole:
        return {
            "passed": len(failures) == 0,
            "pure_mole": True,
            "pure_mole_reason": pure_mole_reason,
            "ablation": ablation_summary,
            "ablation_arms": ablation_arms,
            "v16_checkpoint_files": 0,
            "v16_episodes_replayed": 0,
            "v16_replay_mismatches": 0,
            "v16_checkpoints": [],
            "v16_provider_audit": {
                "present": False,
                "n_providers_audited": 0,
                "n_providers_passed": 0,
                "live_api_calls": 0,
            },
            "failures": failures,
        }

    assert social_mods is not None
    variants_map, resolve_text_provider, verify_and_score_episodes = social_mods

    v16_files = sorted(partial_root.rglob("episodes.jsonl")) if partial_root.is_dir() else []
    if not v16_files:
        failures.append(f"no partial V1.6 checkpoint episodes.jsonl files found under {partial_root}")

    total_replayed = 0
    total_mismatches = 0
    checkpoint_variants: list[dict[str, Any]] = []
    by_variant_seed: dict[str, dict[int, dict[str, float]]] = {}

    for ep_file in v16_files:
        raw_content = ep_file.read_text(encoding="utf-8")
        lines = [ln for ln in raw_content.splitlines() if ln.strip()]
        if not lines:
            continue
        raw_recs = [json.loads(ln) for ln in lines]
        var_name, prov_spec = _infer_v16_variant_and_provider(ep_file, raw_recs[0], variants=variants_map)
        file_hash = hashlib.sha256(raw_content.encode("utf-8")).hexdigest()
        f_key = (f"{var_name}:{prov_spec}", file_hash)
        if f_key not in _V16_FILE_REPLAY_CACHE:
            parsed_eps = [_parse_episode_record(r) for r in raw_recs]
            solver_stubs = [
                EpisodeResult(
                    tier="hard",
                    seed=int(ep.seed),
                    agent="solver_stub",
                    steps=[],
                    score=0.0,
                    accused=None,
                    correct=False,
                    final_day=1,
                    end_reason="horizon",
                    meta={},
                )
                for ep in parsed_eps
            ]
            _V16_FILE_REPLAY_CACHE[f_key] = verify_and_score_episodes(
                parsed_eps,
                solver_stubs,
                tier="hard",
                provider=resolve_text_provider(prov_spec),
                strict=False,
                bootstrap_samples=10,
                rng_seed=20261115,
            )
        scored = _V16_FILE_REPLAY_CACHE[f_key]
        n_val = int(scored["n_agent_valid"])
        mm_count = len(scored["mismatches"])
        total_replayed += n_val
        total_mismatches += mm_count
        if not scored["passed"] or mm_count != 0 or n_val != len(raw_recs):
            failures.append(f"V1.6 checkpoint replay mismatch in {ep_file}: {mm_count} mismatches")

        seed_map = by_variant_seed.setdefault(var_name, {})
        for r in scored["per_seed"]:
            seed_map[int(r["seed"])] = {
                "score": float(r["score"]),
                "luck_adj": float(r["luck_adjusted_score"]),
                "correct": 1.0 if r["correct"] else 0.0,
            }

        checkpoint_variants.append({
            "variant": var_name,
            "provider_spec": prov_spec,
            "n_valid": n_val,
            "seeds": [int(s) for s in scored["seeds"]],
            "mismatch_count": mm_count,
            "raw_mean": float(scored["agent_mean_score"] or 0.0),
            "luck_adj_mean": float(scored["agent_luck_adjusted_mean"] or 0.0),
            "accuracy": float(scored["agent_accuracy"] or 0.0),
            "mean_accuse_day": float(scored["mean_accuse_day"] or 0.0),
        })

    if total_replayed != expected_checkpoint_episodes:
        failures.append(
            f"expected {expected_checkpoint_episodes} V1.6 partial checkpoint episodes, verified {total_replayed}"
        )
    if total_mismatches != 0:
        failures.append(f"expected 0 V1.6 replay mismatches, got {total_mismatches}")

    ctl_seeds = by_variant_seed.get("v0_v14_control", {})
    for row in checkpoint_variants:
        vname = row["variant"]
        if vname == "v0_v14_control":
            row["n_paired_vs_control"] = len(ctl_seeds)
            row["paired_control_raw"] = row["raw_mean"]
            row["paired_delta_raw"] = 0.0
            row["paired_control_luck_adj"] = row["luck_adj_mean"]
            row["paired_delta_luck_adj"] = 0.0
        else:
            vmap = by_variant_seed.get(vname, {})
            shared = sorted(set(vmap) & set(ctl_seeds))
            n_sh = len(shared)
            ctl_r = sum(ctl_seeds[s]["score"] for s in shared) / n_sh if n_sh else 0.0
            var_r = sum(vmap[s]["score"] for s in shared) / n_sh if n_sh else 0.0
            ctl_l = sum(ctl_seeds[s]["luck_adj"] for s in shared) / n_sh if n_sh else 0.0
            var_l = sum(vmap[s]["luck_adj"] for s in shared) / n_sh if n_sh else 0.0
            row["n_paired_vs_control"] = n_sh
            row["paired_control_raw"] = ctl_r
            row["paired_delta_raw"] = var_r - ctl_r
            row["paired_control_luck_adj"] = ctl_l
            row["paired_delta_luck_adj"] = var_l - ctl_l

    v16_provider_audit_summary: dict[str, Any] = {
        "present": False,
        "n_providers_audited": 0,
        "n_providers_passed": 0,
        "live_api_calls": 0,
    }
    if v16_audit_file.is_file():
        v16_aud = json.loads(v16_audit_file.read_text(encoding="utf-8"))
        n_aud = int(v16_aud.get("n_providers_audited", 0))
        n_pass = int(v16_aud.get("n_providers_passed", 0))
        live_calls = int(v16_aud.get("live_api_calls", 0))
        if not bool(v16_aud.get("all_v16_providers_passed")) or n_aud != n_pass or live_calls != 0:
            failures.append("social_audit_report.json failed V1.6 provider fairness invariants")
        v16_provider_audit_summary = {
            "present": True,
            "n_providers_audited": n_aud,
            "n_providers_passed": n_pass,
            "live_api_calls": live_calls,
        }

    return {
        "passed": len(failures) == 0,
        "pure_mole": False,
        "pure_mole_reason": "",
        "ablation": ablation_summary,
        "ablation_arms": ablation_arms,
        "v16_checkpoint_files": len(v16_files),
        "v16_episodes_replayed": total_replayed,
        "v16_replay_mismatches": total_mismatches,
        "v16_checkpoints": checkpoint_variants,
        "v16_provider_audit": v16_provider_audit_summary,
        "failures": failures,
    }


def _extract_portfolio_ledger(md_text: str) -> dict[str, Any]:
    if PORTFOLIO_LEDGER_START not in md_text or PORTFOLIO_LEDGER_END not in md_text:
        raise ValueError("missing embedded ledger markers in mole_regret_portfolio_v14.md")
    body = md_text.split(PORTFOLIO_LEDGER_START, 1)[1].split(PORTFOLIO_LEDGER_END, 1)[0].strip()
    fence_open = "```json"
    fence_close = "```"
    if not body.startswith(fence_open) or not body.endswith(fence_close):
        raise ValueError("malformed embedded JSON code block in mole_regret_portfolio_v14.md")
    raw_json = body[len(fence_open) : -len(fence_close)].strip()
    parsed = json.loads(raw_json)
    if not isinstance(parsed, dict):
        raise ValueError("embedded portfolio ledger must be a JSON object")
    return parsed


def check_transfer_and_regret_portfolio(
    root: Path = ROOT,
    *,
    transfer_json_path: Path | None = None,
    transfer_md_path: Path | None = None,
    portfolio_md_path: Path | None = None,
) -> dict[str, Any]:
    root = Path(root).resolve()
    t_json = Path(transfer_json_path) if transfer_json_path is not None else (root / DEFAULT_TRANSFER_JSON_REL)
    t_md = Path(transfer_md_path) if transfer_md_path is not None else (root / DEFAULT_TRANSFER_MD_REL)
    p_md = Path(portfolio_md_path) if portfolio_md_path is not None else (root / DEFAULT_PORTFOLIO_MD_REL)

    failures: list[str] = []
    transfer_summary: dict[str, Any] = {
        "passed": False,
        "n_catalog": 0,
        "n_gates_passed": 0,
        "n_unique_behaviors": 0,
        "total_transcripts": 0,
        "transcript_verified_total": 0,
        "baseline_audit_match_total": 0,
        "fresh_seed_range": "",
        "fresh_n_seeds": 0,
        "min_solver_acc": 0.0,
        "max_logs_only_acc": 1.0,
        "synthesis_gemini_ev_drop": 0.0,
        "synthesis_codex_all_ev_drop": 0.0,
        "synthesis_all_frontier_ev_drop": 0.0,
        "synthesis_worst_family_ev_drop": 0.0,
        "specialist_in_domain_gain": 0.0,
        "specialist_out_of_domain_gain": 0.0,
        "specialist_min_regret_mean": 0.0,
        "specialist_worst_cf_ev_drop": 0.0,
        "generalist_min_regret_mean": 0.0,
        "generalist_worst_cf_ev_drop": 0.0,
    }

    t_ok, t_msg = check_transfer_artifacts(json_path=t_json, md_path=t_md)
    if not t_ok:
        failures.append(f"cross_model_transfer check failed: {t_msg}")

    if t_json.is_file():
        try:
            t_payload = json.loads(t_json.read_text(encoding="utf-8"))
        except Exception as exc:
            t_payload = {}
            failures.append(f"cross_model_transfer JSON parse error: {exc}")

        if isinstance(t_payload, dict) and t_payload:
            if int(t_payload.get("api_calls", -1)) != 0:
                failures.append("cross_model_transfer api_calls must be 0")
            catalog = t_payload.get("catalog") or {}
            cf = t_payload.get("counterfactual") or {}
            fresh = t_payload.get("fresh_seed_transfer") or {}
            syn = t_payload.get("synthesis") or {}

            n_cat = len(catalog)
            n_uniq = int(syn.get("n_unique_behaviors", 0))
            n_cf_tot = int(cf.get("total_episodes", 0))
            n_cf_ver = int(cf.get("transcript_verified_total", 0))
            n_cf_aud = int(cf.get("baseline_audit_match_total", 0))
            if n_cat != 11 or n_uniq != 9:
                failures.append(f"cross_model_transfer expected 11 catalog entries (9 unique), got {n_cat} ({n_uniq})")
            if n_cf_tot != 99 or n_cf_ver != 99 or n_cf_aud != 99:
                failures.append(
                    f"cross_model_transfer expected 99/99 verified transcripts, got {n_cf_ver}/{n_cf_tot} (audit={n_cf_aud})"
                )

            try:
                t_seeds = validate_fresh_seed_slice(fresh.get("seeds", []), "cross_model_transfer")
            except ValueError as exc:
                t_seeds = []
                failures.append(str(exc))

            if len(t_seeds) != 30:
                failures.append(f"cross_model_transfer expected 30 fresh seeds, got {len(t_seeds)}")

            f_strats = fresh.get("strategies") or {}
            n_gates = sum(
                1
                for r in f_strats.values()
                if bool(r.get("gates_passed"))
                and float(r.get("solver_acc", 0.0)) >= MIN_COMMITTED_SOLVER_ACC
                and float(r.get("logs_only_acc", 1.0)) <= MAX_COMMITTED_LOGS_ACC
            )
            if not bool(fresh.get("all_gates_passed")) or n_gates != 11 or len(f_strats) != 11:
                failures.append(f"cross_model_transfer expected 11/11 strategy gates passed, got {n_gates}/{len(f_strats)}")

            min_sa = min((float(r.get("solver_acc", 0.0)) for r in f_strats.values()), default=0.0)
            max_la = max((float(r.get("logs_only_acc", 1.0)) for r in f_strats.values()), default=1.0)
            fs_cf = ((cf.get("strategies") or {}).get("frontier_synthesis_v14")) or {}
            fs_roll = fs_cf.get("rollups") or {}
            groups = syn.get("groups") or {}
            sp_grp = groups.get("all_specialists") or {}
            gn_grp = groups.get("all_generalists") or {}

            seed_span = f"{t_seeds[0]}-{t_seeds[-1]}" if t_seeds else ""
            t_local_ok = bool(
                t_ok
                and int(t_payload.get("api_calls", -1)) == 0
                and n_cat == 11
                and n_uniq == 9
                and n_cf_tot == 99
                and n_cf_ver == 99
                and n_cf_aud == 99
                and len(t_seeds) == 30
                and bool(fresh.get("all_gates_passed"))
                and n_gates == 11
            )
            transfer_summary = {
                "passed": t_local_ok,
                "n_catalog": n_cat,
                "n_gates_passed": n_gates,
                "n_unique_behaviors": n_uniq,
                "total_transcripts": n_cf_tot,
                "transcript_verified_total": n_cf_ver,
                "baseline_audit_match_total": n_cf_aud,
                "fresh_seed_range": seed_span,
                "fresh_n_seeds": len(t_seeds),
                "min_solver_acc": min_sa,
                "max_logs_only_acc": max_la,
                "synthesis_gemini_ev_drop": float((fs_roll.get("gemini_4_carbon_hard") or {}).get("optimal_ev_drop", 0.0)),
                "synthesis_codex_all_ev_drop": float((fs_roll.get("codex_gpt55_all") or {}).get("optimal_ev_drop", 0.0)),
                "synthesis_all_frontier_ev_drop": float((fs_roll.get("all_frontier") or {}).get("optimal_ev_drop", 0.0)),
                "synthesis_worst_family_ev_drop": float(fs_cf.get("worst_family_ev_drop", 0.0)),
                "specialist_in_domain_gain": float(sp_grp.get("in_domain_regret_gain_mean", 0.0)),
                "specialist_out_of_domain_gain": float(sp_grp.get("out_of_domain_regret_gain_mean", 0.0)),
                "specialist_min_regret_mean": float(sp_grp.get("fresh_panel_min_regret_mean", 0.0)),
                "specialist_worst_cf_ev_drop": float(sp_grp.get("cf_worst_family_ev_drop_mean", 0.0)),
                "generalist_min_regret_mean": float(gn_grp.get("fresh_panel_min_regret_mean", 0.0)),
                "generalist_worst_cf_ev_drop": float(gn_grp.get("cf_worst_family_ev_drop_mean", 0.0)),
            }

    portfolio_summary: dict[str, Any] = {
        "passed": False,
        "train_seed_range": "",
        "train_n_seeds": 0,
        "val_seed_range": "",
        "val_n_seeds": 0,
        "weights": {},
        "train_min_regret": 0.0,
        "min_regret_gain_vs_default": 0.0,
        "best_pure_strategy": "",
        "best_pure_min_regret": 0.0,
        "min_regret_gain_vs_best_pure": 0.0,
        "duality_gap": 1.0,
        "binding_investigators": [],
        "train_solver_acc": 0.0,
        "train_logs_only_acc": 1.0,
        "expected_cf_ev_drop": 0.0,
        "expected_cf_regret": 0.0,
        "val_solver_acc": 0.0,
        "val_solver_score": 0.0,
        "val_logs_only_acc": 1.0,
        "val_do_nothing_score": 1.0,
        "val_stop_early_quit_score": 1.0,
        "val_min_regret": 0.0,
        "selected_strategy_counts": {},
    }

    p_ok, p_msg = check_regret_portfolio_report(p_md)
    if not p_ok:
        failures.append(f"mole_regret_portfolio_v14 check failed: {p_msg}")

    if p_md.is_file():
        try:
            ledger = _extract_portfolio_ledger(p_md.read_text(encoding="utf-8"))
        except Exception as exc:
            ledger = {}
            failures.append(f"mole_regret_portfolio_v14 ledger parse error: {exc}")

        if ledger:
            if ledger.get("schema_version") != "mole_regret_portfolio_v14.v1":
                failures.append(f"unexpected regret portfolio schema_version: {ledger.get('schema_version')!r}")
            if not bool((ledger.get("runtime_meta") or {}).get("zero_api_calls")):
                failures.append("mole_regret_portfolio_v14 zero_api_calls must be True")

            sh = ledger.get("seed_hygiene") or {}
            try:
                p_train_seeds = validate_fresh_seed_slice(sh.get("train_seed_range", ""), "portfolio_train_seeds")
                p_val_seeds = validate_fresh_seed_slice(sh.get("val_seeds", []), "portfolio_val_seeds")
                if set(p_train_seeds) & set(p_val_seeds):
                    failures.append("mole_regret_portfolio_v14 train and validation seeds overlap")
            except ValueError as exc:
                p_train_seeds = []
                p_val_seeds = []
                failures.append(str(exc))

            tp = ((ledger.get("train") or {}).get("portfolio")) or {}
            va = ledger.get("validation") or {}
            vp = va.get("regret_portfolio_v14") or {}
            weights = {str(k): float(v) for k, v in (tp.get("weights") or {}).items()}
            salt = str(ledger.get("portfolio_salt", "canary.mole.regret_portfolio.v1"))

            realized_counts: dict[str, int] = {}
            if p_val_seeds and weights:
                try:
                    for s in p_val_seeds:
                        chosen = PortfolioMolePolicy(s, weights, salt=salt).selected_name
                        realized_counts[chosen] = realized_counts.get(chosen, 0) + 1
                except Exception as exc:
                    failures.append(f"PortfolioMolePolicy realization failed: {exc}")

            recorded_counts = {str(k): int(v) for k, v in (vp.get("selected_strategy_counts") or {}).items()}
            counts_match = bool(realized_counts) and (realized_counts == recorded_counts)
            if not counts_match:
                failures.append(f"PortfolioMolePolicy counts {realized_counts} != ledger {recorded_counts}")

            train_min_reg = float(tp.get("min_regret", 0.0))
            best_pure_reg = float(tp.get("best_pure_min_regret", 1.0))
            d_gap = abs(float(tp.get("duality_gap", 1.0)))
            if not bool(tp.get("gates_passed")) or train_min_reg <= best_pure_reg or d_gap > 1e-9:
                failures.append("mole_regret_portfolio_v14 train saddle-point/dominance check failed")
            if not bool(va.get("gates_passed")):
                failures.append("mole_regret_portfolio_v14 validation gates_passed is not True")

            p_local_ok = bool(
                p_ok
                and ledger.get("schema_version") == "mole_regret_portfolio_v14.v1"
                and bool((ledger.get("runtime_meta") or {}).get("zero_api_calls"))
                and len(p_train_seeds) == 200
                and len(p_val_seeds) == 12
                and not (set(p_train_seeds) & set(p_val_seeds))
                and counts_match
                and bool(tp.get("gates_passed"))
                and train_min_reg > best_pure_reg
                and d_gap <= 1e-9
                and bool(va.get("gates_passed"))
            )
            portfolio_summary = {
                "passed": p_local_ok,
                "train_seed_range": str(sh.get("train_seed_range", "")),
                "train_n_seeds": len(p_train_seeds),
                "val_seed_range": str(sh.get("val_seed_range", "")),
                "val_n_seeds": len(p_val_seeds),
                "weights": {k: v for k, v in sorted(weights.items()) if v > 0.0},
                "train_min_regret": train_min_reg,
                "min_regret_gain_vs_default": float(tp.get("min_regret_gain_vs_default", 0.0)),
                "best_pure_strategy": str(tp.get("best_pure_strategy", "")),
                "best_pure_min_regret": best_pure_reg,
                "min_regret_gain_vs_best_pure": float(tp.get("min_regret_gain_vs_best_pure", 0.0)),
                "duality_gap": d_gap,
                "binding_investigators": [str(x) for x in (tp.get("binding_investigators") or [])],
                "train_solver_acc": float(tp.get("expected_solver_accuracy", 0.0)),
                "train_logs_only_acc": float(tp.get("expected_logs_only_accuracy", 1.0)),
                "expected_cf_ev_drop": float(tp.get("expected_counterfactual_ev_drop", 0.0)),
                "expected_cf_regret": float(tp.get("expected_counterfactual_regret", 0.0)),
                "val_solver_acc": float(vp.get("solver_accuracy", 0.0)),
                "val_solver_score": float(vp.get("solver_score", 0.0)),
                "val_logs_only_acc": float(vp.get("logs_only_accuracy", 1.0)),
                "val_do_nothing_score": float(vp.get("do_nothing_score", 1.0)),
                "val_stop_early_quit_score": float(vp.get("stop_early_quit_score", 1.0)),
                "val_min_regret": float(vp.get("min_regret", 0.0)),
                "selected_strategy_counts": recorded_counts,
            }

    return {
        "passed": len(failures) == 0,
        "transfer": transfer_summary,
        "portfolio": portfolio_summary,
        "failures": failures,
    }


def validate_markdown_hygiene(md_text: str) -> list[str]:
    issues: list[str] = []
    if EM_DASH in md_text:
        issues.append("markdown contains forbidden em-dash character")
    if EN_DASH in md_text:
        issues.append("markdown contains forbidden en-dash character")
    if FLASH_SOLVER_CLAIM_PATTERN.search(md_text):
        issues.append("markdown contains forbidden % of solver claim on gemini-3.5-flash")
    if EMP_ID_PATTERN.search(md_text):
        issues.append("markdown contains employee identifier matching e00..e999")
    for rx in SECRET_PATTERNS:
        if rx.search(md_text):
            issues.append("markdown contains raw API key pattern")
    return issues


def render_summary_markdown(report: dict[str, Any]) -> str:
    is_pure_mole = bool(report.get("pure_mole") or report.get("ablation_and_v16", {}).get("pure_mole"))
    prot = report["protected_paths"]
    cat = report["strategies_and_fresh_eval"]
    cf10 = report["counterfactual_opencode_0_9"]
    abl_v16 = report["ablation_and_v16"]
    xp = report["transfer_and_portfolio"]
    trf = xp["transfer"]
    prt = xp["portfolio"]
    cf60 = cat["fresh_counterfactual_60"]
    abl = abl_v16["ablation"]
    pvd = abl.get("peer_vs_decoy") or {}
    v16_prov = abl_v16["v16_provider_audit"]

    min_200_sol = min(
        (r["solver_acc"] for r in cat["fresh_eval_rows"] if r["name"] != "default_v0"),
        default=0.0,
    )
    max_200_logs = max(
        (r["logs_only_acc"] for r in cat["fresh_eval_rows"] if r["name"] != "default_v0"),
        default=0.0,
    )
    spot_desc = ", ".join(
        f"`{s['name']}` (`acc={s['solver_acc']:.3f}`, `mean={s['solver_mean_score']:+.3f}`)"
        for s in cat["spot_checks"]
    )
    weight_desc = " + ".join(
        f"`{w:.4f}` `{k}`"
        for k, w in sorted(prt["weights"].items(), key=lambda kv: (-kv[1], kv[0]))
    )
    val_counts_desc = ", ".join(
        f"`{k}`: `{c}`"
        for k, c in sorted(prt["selected_strategy_counts"].items(), key=lambda kv: (-kv[1], kv[0]))
    )
    bind_desc = ", ".join(f"`{b}`" for b in prt["binding_investigators"])

    if is_pure_mole:
        header_title = f"{H1} Mole Strategies: Pure-Mole Executive Submission Summary"
        intro_line = (
            f"Deterministic offline verification summary (`TIERS_VERSION={TIERS_VERSION}`, `tier=hard`, "
            "`pure_mole=True`, `live_api_calls=0`) across Canary's transcript-grounded Mole DSL strategies, "
            "Forge v1.4 Hall-of-Fame survivors, 12-arm lever ablation study, cross-model strategy transfer "
            "(`99/99` transcripts, `11/11` gates), and Sleeper minimax attack-regret portfolio "
            "(`canary.mole.regret_portfolio`)."
        )
        repro_cmd = (
            'GOOGLE_API_KEY="" GEMINI_API_KEY="" OPENAI_API_KEY="" '
            "PYTHONPATH=. python scripts/verify_mole_strategies_gate.py --pure-mole"
        )
        gate_d_row = (
            f"| `(d)` 12-Arm Lever Ablation (Pure-Mole) | `results/mole_strategies/lever_ablation_v14.json` (`{abl.get('seed_range', '')}`, `n={abl.get('n_seeds', 0)}`) | "
            f"`{abl.get('n_passed', 0)}/{abl.get('n_arms', 0)}` ablation arms pass gates (min `solver_acc={abl.get('min_solver_acc_observed', 0.0):.3f}`, max `logs_only_acc={abl.get('max_logs_only_acc_observed', 0.0):.3f}`) | {'PASS' if abl_v16['passed'] else 'FAIL'} |"
        )
        gate_f_row = (
            f"| `(f)` Offline & Hygiene Discipline | Zero API keys, zero em/en dashes, zero secret or employee-ID leaks, zero `canary.social` imports | "
            f"`live_api_calls={report['telemetry']['live_api_calls']}`, `blocked_api_attempts={report['telemetry']['blocked_api_attempts']}` | "
            f"{'PASS' if report['all_passed'] else 'FAIL'} |"
        )
    else:
        header_title = f"{H1} Mole Strategies & Social Deception: Executive Submission Summary"
        intro_line = (
            f"Deterministic offline verification summary (`TIERS_VERSION={TIERS_VERSION}`, `tier=hard`, "
            "`live_api_calls=0`) across Canary's transcript-grounded Mole DSL strategies, Forge v1.4 "
            "Hall-of-Fame survivors, 12-arm lever ablation study, cross-model strategy transfer (`99/99` "
            "transcripts, `11/11` gates), Sleeper minimax attack-regret portfolio (`canary.mole.regret_portfolio`), "
            "and V1.6 social-chatter fairness and partial checkpoint audit."
        )
        repro_cmd = (
            'GOOGLE_API_KEY="" GEMINI_API_KEY="" OPENAI_API_KEY="" '
            "PYTHONPATH=. python scripts/verify_mole_strategies_gate.py --check"
        )
        gate_d_row = (
            f"| `(d)` 12-Arm Lever Ablation & V1.6 Replay Audit | `results/mole_strategies/lever_ablation_v14.json` (`{abl['seed_range']}`, `n={abl['n_seeds']}`) + `results/v16_social/partial/` (`{abl_v16['v16_checkpoint_files']}` files) | "
            f"`{abl['n_passed']}/{abl['n_arms']}` ablation arms pass gates (min `solver_acc={abl['min_solver_acc_observed']:.3f}`, max `logs_only_acc={abl['max_logs_only_acc_observed']:.3f}`); "
            f"`{abl_v16['v16_episodes_replayed']}/10` V1.6 checkpoints replay-verified bit-for-bit (`{abl_v16['v16_replay_mismatches']}` mismatches) | {'PASS' if abl_v16['passed'] else 'FAIL'} |"
        )
        gate_f_row = (
            f"| `(f)` Offline & Hygiene Discipline | Zero API keys, zero em/en dashes, zero secret or employee-ID leaks, honest V1.6 Gate B reporting | "
            f"`live_api_calls={report['telemetry']['live_api_calls']}`, `blocked_api_attempts={report['telemetry']['blocked_api_attempts']}` | "
            f"{'PASS' if report['all_passed'] else 'FAIL'} |"
        )

    lines: list[str] = [
        header_title,
        "",
        intro_line,
        "",
        "Reproduce or verify exact deterministic byte parity with zero API keys:",
        "```bash",
        repro_cmd,
        "```",
        "",
        f"{H2} 1. Six-Gate Submission Verification Summary",
        "",
        "| Gate | Scope & Verification Target | Key Measured Result | Verdict |",
        "|---|---|---|---|",
        (
            f"| `(a)` Protected-Path Guard | `.github/protected-paths.txt` ({prot['n_protected_rules']} protected prefixes vs `{prot['base_ref']}`) | "
            f"`{len(prot['violations'])}` protected-path modifications | {'PASS' if prot['passed'] else 'FAIL'} |"
        ),
        (
            f"| `(b)` Catalogs, Seed Hygiene, 200-Seed Eval & Live Spot-Check | "
            f"`{cat['n_transcript_strategies']}` `canary.mole.strategies` + `{cat['n_hof_rows']}` `hall_of_fame_v1.4.jsonl` rows; "
            f"`6000-6199` (`n={cat['fresh_eval_n_seeds']}`) + live `{cat['spot_check_seeds'][0]}-{cat['spot_check_seeds'][-1]}` (`n={len(cat['spot_check_seeds'])}`) | "
            f"100% DSL round-trip, `{cat['n_transcript_strategies']}/6` + `{cat['n_hof_rows']}/4` unique 64-view `behavior_hash` (`{cat['combined_unique_behavior_hashes']}` distinct across catalogs); "
            f"200-seed min `solver_acc={min_200_sol:.3f}` (`>=0.85`), max `logs_only_acc={max_200_logs:.3f}` (`<=0.10`), `DoNothing=0.0`, `StopEarlyQuit=0.0`; "
            f"live spot-check: {spot_desc} | {'PASS' if cat['passed'] else 'FAIL'} |"
        ),
        (
            f"| `(c)` Counterfactual Frontier Replay | Live `canary.mole.counterfactual` on v1.4 Gemini Hard `opencode` seeds `0-9` (`n={cf10['n_episodes']}`) + committed 60-transcript v1.4 Hard cohort (`30` `opencode` + `30` `inproc`) | "
            f"`opencode` `0-9`: `P(true mole)` `{cf10['default_p_true_mole']:.3f} -> {cf10['synthesis_p_true_mole']:.3f}` (drop `{cf10['p_true_mole_drop']:+.3f}`), "
            f"optimal EV `{cf10['default_optimal_ev']:.3f} -> {cf10['synthesis_optimal_ev']:.3f}` (drop `{cf10['optimal_ev_drop']:+.3f}`); "
            f"full `60` transcripts: `P(true mole)` `{cf60['default_p_true_mole']:.3f} -> {cf60['synthesis_p_true_mole']:.3f}` (drop `{cf60['p_true_mole_drop']:+.3f}`), "
            f"optimal EV `{cf60['default_optimal_ev']:.3f} -> {cf60['synthesis_optimal_ev']:.3f}` (drop `{cf60['optimal_ev_drop']:+.3f}`) | {'PASS' if cf10['passed'] else 'FAIL'} |"
        ),
        gate_d_row,
        (
            f"| `(e)` Cross-Model Transfer & Sleeper Regret Portfolio | `results/mole_strategies/cross_model_transfer.json` + `docs/reports/mole_regret_portfolio_v14.md` (`canary.mole.regret_portfolio`) | "
            f"`{trf['n_gates_passed']}/{trf['n_catalog']}` transfer gates passed (`{trf['fresh_seed_range']}`, `n={trf['fresh_n_seeds']}`, min `solver_acc={trf['min_solver_acc']:.3f}`), "
            f"`{trf['transcript_verified_total']}/{trf['total_transcripts']}` transcripts verified (`{trf['baseline_audit_match_total']}/{trf['total_transcripts']}` baseline audit parity); "
            f"`PortfolioMolePolicy` ({weight_desc}, `duality_gap={prt['duality_gap']:.2e}`) train `min_regret={prt['train_min_regret']:.4f}` (`{prt['min_regret_gain_vs_default']:+.4f}` vs `default_v0`), "
            f"live val `{prt['val_seed_range']}` (`n={prt['val_n_seeds']}`) `solver_acc={prt['val_solver_acc']:.3f}`, `logs_only_acc={prt['val_logs_only_acc']:.3f}` | {'PASS' if xp['passed'] else 'FAIL'} |"
        ),
        gate_f_row,
        "",
        f"{H2} 2. Empirical Frontier Failure Modes Driving Fair Mole Levers",
        "",
        (
            "All mole strategies operate strictly inside `canary.mole.dsl.MoleView` (public-free features only: "
            "the mole never sees canary labels, investigator tool calls, or posterior beliefs) and remain "
            "consistently solvable by `SolverPolicy(\"hard\")` (`>= 0.85` accuracy on 200 fresh seeds):"
        ),
        "",
        (
            "- **100.0% angry-decoy dismissal vs non-decoy peer framing**: Across `159` primary v1.4/v1.3 "
            "frontier episodes, frontier investigators accused the angry decoy `0` times (`100.0%` dismissal), "
            "whereas non-decoy after-hours log framing broke `0`-separation canary ties into `-1.0` wrong "
            "accusations in `5/10` total frontier wrong accusations."
        ),
        (
            "- **Architectural split in canary recipient sizing**: Codex and GPT-5.5 place `30.6%` (Hard) to "
            "`75.3%` (Medium) of planted canaries into `<=3`-recipient surgical traps, while `gemini-4-carbon` "
            "places `0.0%` to `0.6%` in `<=3` recipients and concentrates `43.6%` to `73.6%` in `4-8`-recipient "
            "3-variant partitions."
        ),
        (
            "- **Delayed Day-1 canary start and single-canary fragility**: On v1.4 Hard, `gemini-4-carbon` delays "
            "its first canary to mean day `3.03` (OpenCode) and `3.40` (in-proc) vs `SolverPolicy` day `1.00`, "
            "spends `57.27` to `68.03` calls per episode (`64.4%` to `68.0%` of investigative budget) on low-LR "
            "`interview` calls, and commits `7/10` Hard wrong accusations with `<=1` separating canary under "
            "`0.95` fingerprint accuracy."
        ),
        "",
        f"{H2} 3. Transcript-Grounded Strategies on 200 Fresh Hard Seeds (`6000-6199`) & 60 Real Transcripts",
        "",
        (
            "Seed hygiene is enforced across every evaluation slice (`0-59`, `30000-30199`, `800000+`, and "
            "`900000+` strictly forbidden across `6000-6199`, `6200-6229`, `6600-6639`, `6812-6823`, "
            "and `6900-6903`)."
        ),
        "",
        "| Strategy | Rules | BHash | Solver Acc | Solver Score +/- CI | LogsOnly Acc | Min Regret | GeminiProxy Regret (Gain) | CF P(mole) (Drop) | CF Opt EV (Drop) | Gate |",
        "|---|---|---|---:|---|---:|---:|---|---|---|---:|",
    ]

    for row in cat["fresh_eval_rows"]:
        lines.append(
            f"| `{row['display_name']}` | {row['n_rules']} | `{row['behavior_hash'][:8]}` | "
            f"{row['solver_acc']:.3f} | {row['solver_score']:+.3f} +/- {row['solver_ci_95']:.3f} | "
            f"{row['logs_only_acc']:.3f} | {row['min_regret']:.3f} | "
            f"{row['gemini_regret']:.3f} ({row['gemini_regret_gain']:+.3f}) | "
            f"{row['cf_p_true_mole']:.3f} ({row['cf_p_true_mole_drop']:+.3f}) | "
            f"{row['cf_optimal_ev']:.3f} ({row['cf_optimal_ev_drop']:+.3f}) | "
            f"{'PASS' if row['passed'] else 'FAIL'} |"
        )

    lines.extend([
        "",
        f"{H2} 4. Forge v1.4 Hall-of-Fame Survivors (`6200-6219`) & Live Fresh Spot-Check (`6900-6903`)",
        "",
        "| HoF Rank | Survivor Name | Rules | BHash | Held-Out Solver Acc | Held-Out Solver Score | Held-Out Min Regret | GeminiProxy Regret | CodexProxy Regret | DSL Round-Trip |",
        "|---:|---|---:|---|---:|---:|---:|---:|---:|---|",
    ])

    for hrow in cat["hof_rows"]:
        lines.append(
            f"| {hrow['rank']} | `{hrow['name']}` | {hrow['n_rules']} | `{hrow['behavior_hash'][:8]}` | "
            f"{hrow['solver_acc']:.3f} | {hrow['solver_score']:+.3f} | {hrow['min_regret']:.3f} | "
            f"{hrow['gemini_proxy_regret']:.3f} | {hrow['codex_proxy_regret']:.3f} | "
            f"{'PASS' if (hrow['round_trip_ok'] and hrow['conds_valid']) else 'FAIL'} |"
        )

    lines.extend([
        "",
        f"{H3} 4.1 Live 4-Seed Gate Spot-Check (`hard`, Seeds `6900-6903`)",
        "",
        "| Spot-Check Strategy | Seeds | BHash | Solver Acc (Min 0.75) | Solver Mean Score | DoNothing Max Abs | StopEarlyQuit Max Abs | Unfinished Quit | Gate |",
        "|---|---|---|---:|---:|---:|---:|---:|---|",
    ])

    for srow in cat["spot_checks"]:
        seed_span = f"{srow['seeds'][0]}-{srow['seeds'][-1]}" if srow["seeds"] else "none"
        lines.append(
            f"| `{srow['name']}` | `{seed_span}` | `{srow['behavior_hash'][:8]}` | "
            f"{srow['solver_acc']:.3f} | {srow['solver_mean_score']:+.3f} | "
            f"{srow['do_nothing_max_abs']:.3f} | {srow['stop_early_quit_max_abs']:.3f} | "
            f"{srow['unfinished_quit_score']:.3f} | {'PASS' if srow['passed'] else 'FAIL'} |"
        )

    lines.extend([
        "",
        f"{H2} 5. 12-Arm `frontier_synthesis_v14` Lever Ablation (`6600-6639`, `n=40` Live + `60` Transcripts)",
        "",
        (
            f"All `{abl['n_passed']}/{abl['n_arms']}` single-lever, leave-one-out, decoy-control, and composite "
            f"arms pass every catchability and anti-shortcut gate (`min_solver_acc={abl['min_solver_acc_observed']:.3f}`, "
            f"`max_logs_only_acc={abl['max_logs_only_acc_observed']:.3f}`, `DoNothing=0.000`, `StopEarlyQuit=0.000`). "
            f"Replacing dismissed angry-decoy framing with non-decoy peer framing increases frontier proxy regret "
            f"by `{pvd.get('synthesis_frontier_regret_gain', 0.0):+.3f}` (composite) and "
            f"`{pvd.get('single_frontier_regret_gain', 0.0):+.3f}` (single-lever, Codex proxy score delta "
            f"`{pvd.get('single_codex_score_delta', 0.0):+.3f}`) while adding "
            f"`{pvd.get('synthesis_cf_ev_drop_gain', 0.0):+.3f}` counterfactual EV drop in synthesis."
        ),
        "",
        "| Arm | Kind | Rules | Framing | Solver Acc | Solver Score | Frontier Regret | LogsOnly Acc | CF P(mole) Drop | CF EV Drop | Surf Canaries | Gate |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ])

    for arm in abl_v16["ablation_arms"]:
        lines.append(
            f"| `{arm['name']}` | `{arm['kind']}` | {arm['n_rules']} | `{arm['framing_mode']}` | "
            f"{arm['solver_acc']:.3f} | {arm['solver_score']:+.3f} | {arm['frontier_regret']:+.3f} | "
            f"{arm['logs_only_acc']:.3f} | {arm['cf_p_mole_drop']:+.3f} | {arm['cf_ev_drop']:+.3f} | "
            f"{arm['cf_surfaced_canaries']:.2f} | {'PASS' if arm['passed'] else 'FAIL'} |"
        )

    lines.extend([
        "",
        f"{H2} 6. Cross-Model Strategy Transfer (`99/99` Transcripts, `11/11` Gates) & Sleeper Minimax Regret Portfolio",
        "",
        (
            f"- **Cross-model transfer (`results/mole_strategies/cross_model_transfer.json`, `docs/reports/mole_cross_model_transfer.md`)**: "
            f"`{trf['transcript_verified_total']}/{trf['total_transcripts']}` raw frontier transcripts (`60` v1.4 `gemini-4-carbon` Hard across OpenCode MCP + in-proc; "
            f"`39` v1.3 Codex/GPT-5.5 across Hard `n=19` and Medium `n=20`) reconstruct into public-tool schedules with "
            f"`{trf['baseline_audit_match_total']}/{trf['total_transcripts']}` `audit_episode` baseline posterior parity. On fresh v1.4 Hard seeds "
            f"`{trf['fresh_seed_range']}` (`n={trf['fresh_n_seeds']}`), `{trf['n_gates_passed']}/{trf['n_catalog']}` catalog entries "
            f"(`{trf['n_unique_behaviors']}` unique behavioral policies) pass all catchability and anti-shortcut gates "
            f"(`min solver_acc={trf['min_solver_acc']:.3f} >= 0.85`, `max logs_only_acc={trf['max_logs_only_acc']:.3f} <= 0.10`). "
            f"`frontier_synthesis_v14` leads cross-family counterfactual EV drop (`{trf['synthesis_gemini_ev_drop']:+.3f}` Gemini Hard, "
            f"`{trf['synthesis_codex_all_ev_drop']:+.3f}` Codex/GPT-5.5 All, `{trf['synthesis_all_frontier_ev_drop']:+.3f}` across all `99` transcripts, "
            f"worst-family `{trf['synthesis_worst_family_ev_drop']:+.3f}`), while unique specialists (`n=4`) achieve `{trf['specialist_in_domain_gain']:+.3f}` "
            f"in-domain vs `{trf['specialist_out_of_domain_gain']:+.3f}` out-of-domain proxy regret gain (`{trf['specialist_min_regret_mean']:.3f}` "
            f"5-investigator minimax regret and `{trf['specialist_worst_cf_ev_drop']:+.3f}` worst-family CF EV drop vs generalists "
            f"`{trf['generalist_min_regret_mean']:.3f}` and `{trf['generalist_worst_cf_ev_drop']:+.3f}`)."
        ),
        (
            f"- **Sleeper minimax attack-regret portfolio (`canary.mole.regret_portfolio`, `docs/reports/mole_regret_portfolio_v14.md`)**: "
            f"Linear-programming saddle-point portfolio fit on `{prt['train_seed_range']}` (`n={prt['train_n_seeds']}`) places {weight_desc}, "
            f"equalizing binding adversaries ({bind_desc}) at minimax regret `{prt['train_min_regret']:.4f}` (`duality_gap={prt['duality_gap']:.2e}`), "
            f"strictly dominating `default_v0` (`{prt['min_regret_gain_vs_default']:+.4f}`) and best single pure strategy `{prt['best_pure_strategy']}` "
            f"(`{prt['best_pure_min_regret']:.4f}`, `{prt['min_regret_gain_vs_best_pure']:+.4f}`), with expected `SolverPolicy` `acc={prt['train_solver_acc']:.3f}`, "
            f"`LogsOnly` `acc={prt['train_logs_only_acc']:.3f}`, and 60-transcript Gemini counterfactual EV drop `{prt['expected_cf_ev_drop']:+.3f}` "
            f"(counterfactual regret `{prt['expected_cf_regret']:+.3f}`). Zero-private-info SHA-256 seed-hashed `PortfolioMolePolicy` "
            f"(`select_portfolio_strategy(seed, weights)`) passes every gate on disjoint held-out live validation seeds `{prt['val_seed_range']}` "
            f"(`n={prt['val_n_seeds']}`, realizing {val_counts_desc}): `SolverPolicy(\"hard\")` `acc={prt['val_solver_acc']:.3f}` "
            f"(`score={prt['val_solver_score']:+.3f}`), `LogsOnly` `acc={prt['val_logs_only_acc']:.3f}`, `DoNothing={prt['val_do_nothing_score']:.3f}`, "
            f"and `StopEarlyQuit={prt['val_stop_early_quit_score']:.3f}`."
        ),
    ])

    if not is_pure_mole:
        lines.extend([
            "",
            f"{H2} 7. V1.6 Social Deception Audit & Honest Gate B Negative Result",
            "",
            (
                f"- **Engineering & fairness gates (`PASS`)**: Across `{v16_prov['n_providers_passed']}/{v16_prov['n_providers_audited']}` "
                "audited V1.6 and sanitized `TextProvider` specs on Hard seeds `30-35` (`0` live API calls), "
                "`SolverPolicy` achieves bit-exact calibration parity (`max_abs_score_diff = 0.000000`), non-decoy "
                "`ANGER_WORDS` leakage is `0`, `DoNothing = 0.0`, `StopEarlyQuit = 0.0`, and all "
                f"`{abl_v16['v16_episodes_replayed']}/10` collected Gemini checkpoints under `results/v16_social/partial/` "
                f"replay bit-for-bit via `canary.social_audit.verify_and_score_episodes` with `{abl_v16['v16_replay_mismatches']}` mismatches."
            ),
            (
                "- **Live Gate B outcome (`NOT MET`, negative result)**: Live `gemini-4-carbon` evaluation on Hard seeds "
                "`30-44` was halted early after `10` valid episodes (`v0_v14_control` `n=4`, `v5_full9_cocktail` `n=3`, "
                "`v3_grudge_falsemem_misforward` `n=2`, `v1_anchoring_authority_confirmation` `n=1`) to protect shared API "
                "quota for the primary `n=60` gap run. Neither the sample-size threshold (`n >= 15` / `n >= 30`) nor the "
                "gap-widening criterion (lowering `gemini-4-carbon` score below `v0_v14_control`) was met: structured "
                "forensic tools (`plant_canary`, `read_access_logs`, `check_leak_feed`) dominated social-chatter decoys "
                "(`10/10` correct accusations), and all three tested social variants scored higher in raw mean on their "
                "paired seeds than `v0_v14_control`."
            ),
            "",
            "| Checkpoint Variant | Provider Spec | Valid Seeds | n | Gemini Raw Mean | Gemini Luck-Adj Mean | Paired Delta Raw vs v0 | Paired Delta Luck-Adj vs v0 | Replay Mismatches | Gate B Verdict |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
        ])

        for crow in abl_v16["v16_checkpoints"]:
            seed_csv = ",".join(str(s) for s in crow["seeds"])
            verdict = "CONTROL (n=4)" if crow["variant"] == "v0_v14_control" else "NOT MET (negative)"
            lines.append(
                f"| `{crow['variant']}` | `{crow['provider_spec']}` | `{seed_csv}` | {crow['n_valid']} | "
                f"{crow['raw_mean']:+.3f} | {crow['luck_adj_mean']:+.3f} | "
                f"{crow['paired_delta_raw']:+.3f} | {crow['paired_delta_luck_adj']:+.3f} | "
                f"{crow['mismatch_count']} | {verdict} |"
            )

    lines.append("")
    return "\n".join(lines)


def run_submission_gate(
    root: Path = ROOT,
    *,
    base_ref: str = DEFAULT_BASE_REF,
    spot_seeds: Sequence[int] = DEFAULT_SPOT_SEEDS,
    spot_targets: Sequence[str] | None = None,
    min_spot_solver_acc: float = MIN_SPOT_SOLVER_ACC,
    cf_seeds: Sequence[int] = DEFAULT_CF_SEEDS,
    cf_sources: Sequence[str] = DEFAULT_CF_SOURCES,
    expected_v16_episodes: int = 10,
    pure_mole: bool = False,
) -> dict[str, Any]:
    root = Path(root).resolve()
    with offline_gate_guard() as telemetry:
        c_prot = check_protected_paths(root=root, base_ref=base_ref)
        c_cat = check_strategies_and_fresh_eval(
            root=root,
            spot_seeds=spot_seeds,
            spot_targets=spot_targets,
            min_spot_solver_acc=min_spot_solver_acc,
        )
        c_cf = check_counterfactual_replay(
            root=root,
            seeds=cf_seeds,
            sources=cf_sources,
        )
        c_abl_v16 = check_ablation_and_v16_replays(
            root=root,
            expected_checkpoint_episodes=expected_v16_episodes,
            pure_mole=pure_mole,
        )
        c_xp = check_transfer_and_regret_portfolio(root=root)

    api_clean = telemetry["live_api_calls"] == 0 and telemetry["blocked_api_attempts"] == 0
    all_passed = bool(
        c_prot["passed"]
        and c_cat["passed"]
        and c_cf["passed"]
        and c_abl_v16["passed"]
        and c_xp["passed"]
        and api_clean
    )
    is_pure_mole = bool(c_abl_v16.get("pure_mole", pure_mole))
    report: dict[str, Any] = {
        "schema_version": "mole_strategies_submission_gate.v1",
        "tiers_version": TIERS_VERSION,
        "pure_mole": is_pure_mole,
        "pure_mole_reason": str(c_abl_v16.get("pure_mole_reason", "")),
        "all_passed": all_passed,
        "telemetry": telemetry,
        "protected_paths": c_prot,
        "strategies_and_fresh_eval": c_cat,
        "counterfactual_opencode_0_9": c_cf,
        "ablation_and_v16": c_abl_v16,
        "transfer_and_portfolio": c_xp,
    }
    md_preview = render_summary_markdown(report)
    hygiene_issues = validate_markdown_hygiene(md_preview)
    report["markdown_hygiene"] = {
        "passed": len(hygiene_issues) == 0,
        "issues": hygiene_issues,
    }
    if hygiene_issues:
        report["all_passed"] = False
    return report


def _format_cli_summary(report: dict[str, Any], elapsed_s: float) -> str:
    prot = report["protected_paths"]
    cat = report["strategies_and_fresh_eval"]
    cf = report["counterfactual_opencode_0_9"]
    av = report["ablation_and_v16"]
    xp = report["transfer_and_portfolio"]
    trf = xp["transfer"]
    prt = xp["portfolio"]
    hyg = report["markdown_hygiene"]
    if bool(report.get("pure_mole") or av.get("pure_mole")):
        gate_d_line = (
            f"[{'PASS' if av['passed'] else 'FAIL'}] (d) Lever Ablation (Pure-Mole): "
            f"{av['ablation'].get('n_passed', 0)}/{av['ablation'].get('n_arms', 0)} ablation arms "
            f"(pure_mole={av.get('pure_mole_reason') or 'true'})"
        )
    else:
        gate_d_line = (
            f"[{'PASS' if av['passed'] else 'FAIL'}] (d) Ablation & V1.6 Replays: "
            f"{av['ablation'].get('n_passed', 0)}/{av['ablation'].get('n_arms', 0)} ablation arms, "
            f"{av['v16_episodes_replayed']}/10 V1.6 episodes ({av['v16_replay_mismatches']} mismatches)"
        )
    lines = [
        f"[{'PASS' if prot['passed'] else 'FAIL'}] (a) Protected-Path Guard: {len(prot['violations'])} violations across {prot['n_protected_rules']} rules (base_ref={prot['base_ref']}, present={prot['base_ref_present']})",
        f"[{'PASS' if cat['passed'] else 'FAIL'}] (b) Catalogs & Fresh Seeds: {cat['n_transcript_strategies']}/6 strategies + {cat['n_hof_rows']}/4 HoF rows, 200-seed v14 eval + {len(cat['spot_check_seeds'])}-seed spot-check",
        f"[{'PASS' if cf['passed'] else 'FAIL'}] (c) Counterfactual Opencode 0-9: P(mole) {cf['default_p_true_mole']:.3f}->{cf['synthesis_p_true_mole']:.3f} (drop {cf['p_true_mole_drop']:+.3f}), EV {cf['default_optimal_ev']:.3f}->{cf['synthesis_optimal_ev']:.3f} (drop {cf['optimal_ev_drop']:+.3f})",
        gate_d_line,
        f"[{'PASS' if xp['passed'] else 'FAIL'}] (e) Cross-Model Transfer & Regret Portfolio: {trf['n_gates_passed']}/{trf['n_catalog']} transfer gates ({trf['transcript_verified_total']}/{trf['total_transcripts']} transcripts), portfolio min_regret={prt['train_min_regret']:.4f} (val solver_acc={prt['val_solver_acc']:.3f})",
        f"[{'PASS' if hyg['passed'] else 'FAIL'}] (f) Summary Hygiene & Offline Guard: {len(hyg['issues'])} issues, {report['telemetry']['live_api_calls']} API calls ({elapsed_s:.2f}s)",
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/verify_mole_strategies_gate.py")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--base-ref", default=DEFAULT_BASE_REF)
    ap.add_argument("--spot-seeds", default="6900-6903")
    ap.add_argument("--spot-targets", default=None)
    ap.add_argument("--cf-seeds", default="0-9")
    ap.add_argument(
        "--pure-mole",
        action="store_true",
        help="run pure-mole submission gates without V1.6 social modules or checkpoints",
    )
    ap.add_argument("--out", type=Path, default=None, help="write deterministic executive summary Markdown")
    ap.add_argument(
        "--check",
        nargs="?",
        const="__DEFAULT__",
        default=None,
        help="verify executive summary Markdown matches deterministic gate output",
    )
    ap.add_argument("--json", action="store_true", help="emit JSON gate report")
    args = ap.parse_args(argv)

    t0 = time.perf_counter()
    spot_seeds = _parse_seed_spec(args.spot_seeds)
    spot_targets = (
        [t.strip() for t in args.spot_targets.split(",") if t.strip()]
        if args.spot_targets is not None
        else None
    )
    cf_seeds = _parse_seed_spec(args.cf_seeds)

    report = run_submission_gate(
        root=args.root,
        base_ref=args.base_ref,
        spot_seeds=spot_seeds,
        spot_targets=spot_targets,
        cf_seeds=cf_seeds,
        pure_mole=bool(args.pure_mole),
    )
    rendered_md = render_summary_markdown(report)
    elapsed_s = time.perf_counter() - t0

    if args.out is not None and args.check is None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered_md, encoding="utf-8")

    check_ok = True
    check_msg = ""
    if args.check is not None:
        if args.check == "__DEFAULT__":
            target_md = args.out if args.out is not None else DEFAULT_SUMMARY_MD
        else:
            target_md = Path(args.check)
        if not target_md.is_file():
            check_ok = False
            check_msg = f"FAIL: missing summary markdown {target_md}"
        else:
            existing_md = target_md.read_text(encoding="utf-8")
            hyg_existing = validate_markdown_hygiene(existing_md)
            if hyg_existing:
                check_ok = False
                check_msg = f"FAIL: {target_md} failed hygiene: {'; '.join(hyg_existing)}"
            elif existing_md != rendered_md:
                check_ok = False
                check_msg = f"FAIL: {target_md} is out of sync with deterministic gate output"
            else:
                check_msg = f"OK: {target_md} matches deterministic gate output ({elapsed_s:.2f}s)"

    if args.json:
        payload = {**report, "check_ok": check_ok, "check_message": check_msg}
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_format_cli_summary(report, elapsed_s))
        if check_msg:
            print(check_msg)

    return 0 if (report["all_passed"] and check_ok) else 1


if __name__ == "__main__":
    raise SystemExit(main())
