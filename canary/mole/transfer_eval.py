from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
import sys
from typing import Any, Iterable, Sequence

from canary.analysis.accuse import audit_episode
from canary.analysis.tags import to_result
from canary.baselines import GrokTactics, Heuristic, LogsOnly
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import CodexHorizonProxy, GeminiCarbonProxy
from canary.forge.investigators import HintedHeuristic
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.counterfactual import REPLAY_TOOLS, inspect_observation_history
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import STRATEGY_SPECS
from canary.rules import (
    HELDOUT_SEEDS,
    JUDGE_SEEDS,
    TIERS,
    tier_params,
    tier_params_for_episode,
    tiers_version,
)
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step
from canary.world import generate_world

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMMITTED_ROOT = ROOT / "data" / "runs" / "committed"
DEFAULT_HOF_V14_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
DEFAULT_HOF_V14_META_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.meta.json"
DEFAULT_JSON_OUT = ROOT / "results" / "mole_strategies" / "cross_model_transfer.json"
DEFAULT_REPORT_OUT = ROOT / "docs" / "reports" / "mole_cross_model_transfer.md"

DEFAULT_FRESH_SEEDS = range(6200, 6230)
DEFAULT_MIN_SOLVER_ACC = 0.85
DEFAULT_MAX_LOGS_ACC = 0.10
DEFAULT_MIN_SOLVER_RATIO = 0.50
DEFAULT_BOOTSTRAP_SAMPLES = 1000
DEFAULT_WORKERS = max(1, min(4, os.cpu_count() or 1))

PRIMARY_COHORT_SEED_MAX = 29
FORBIDDEN_LOW_SEED_MAX = 59
RESERVED_HELDOUT_SEEDS = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

TRANSFER_INVESTIGATORS: tuple[str, ...] = (
    "solver",
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
    "logs_only",
)
NON_TRIVIAL_INVESTIGATORS: tuple[str, ...] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
    "grok_tactics",
    "hinted_heuristic",
    "heuristic",
)
FRONTIER_PROXY_PAIR: tuple[str, str] = (
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
)


@dataclass(frozen=True)
class FrontierCohortSpec:
    cohort_id: str
    version: str
    rel_dir: str
    tier: str
    family: str
    harness: str
    label: str


FRONTIER_COHORTS: tuple[FrontierCohortSpec, ...] = (
    FrontierCohortSpec(
        cohort_id="v14_gemini_opencode_hard",
        version="v1.4",
        rel_dir="v1.4/opencode-gemini-4-carbon/hard",
        tier="hard",
        family="gemini_4_carbon",
        harness="opencode_mcp",
        label="v1.4 Gemini-4-carbon Hard (OpenCode MCP)",
    ),
    FrontierCohortSpec(
        cohort_id="v14_gemini_inproc_hard",
        version="v1.4",
        rel_dir="v1.4/inproc-gemini-4-carbon/hard",
        tier="hard",
        family="gemini_4_carbon",
        harness="gemini_inproc",
        label="v1.4 Gemini-4-carbon Hard (In-Proc)",
    ),
    FrontierCohortSpec(
        cohort_id="v13_codex_hard",
        version="v1.3",
        rel_dir="v1.3/codex-gpt-5.5-full/hard",
        tier="hard",
        family="codex_gpt55",
        harness="codex_mcp",
        label="v1.3 Codex GPT-5.5 Hard (Codex CLI MCP)",
    ),
    FrontierCohortSpec(
        cohort_id="v13_gpt55_hard",
        version="v1.3",
        rel_dir="v1.3/gpt-5.5-full/hard",
        tier="hard",
        family="codex_gpt55",
        harness="openai_inproc",
        label="v1.3 GPT-5.5 Hard (In-Proc Responses)",
    ),
    FrontierCohortSpec(
        cohort_id="v13_codex_medium",
        version="v1.3",
        rel_dir="v1.3/codex-gpt-5.5-full/medium",
        tier="medium",
        family="codex_gpt55",
        harness="codex_mcp",
        label="v1.3 Codex GPT-5.5 Medium (Codex CLI MCP)",
    ),
    FrontierCohortSpec(
        cohort_id="v13_gpt55_medium",
        version="v1.3",
        rel_dir="v1.3/gpt-5.5-full/medium",
        tier="medium",
        family="codex_gpt55",
        harness="openai_inproc",
        label="v1.3 GPT-5.5 Medium (In-Proc Responses)",
    ),
)

FRONTIER_COHORT_MAP: dict[str, FrontierCohortSpec] = {c.cohort_id: c for c in FRONTIER_COHORTS}

COUNTERFACTUAL_ROLLUPS: dict[str, tuple[str, ...]] = {
    "gemini_4_carbon_hard": (
        "v14_gemini_opencode_hard",
        "v14_gemini_inproc_hard",
    ),
    "codex_gpt55_hard": (
        "v13_codex_hard",
        "v13_gpt55_hard",
    ),
    "codex_gpt55_medium": (
        "v13_codex_medium",
        "v13_gpt55_medium",
    ),
    "codex_gpt55_all": (
        "v13_codex_hard",
        "v13_gpt55_hard",
        "v13_codex_medium",
        "v13_gpt55_medium",
    ),
    "all_frontier": tuple(c.cohort_id for c in FRONTIER_COHORTS),
}


@dataclass(frozen=True)
class CatalogStrategyEntry:
    key: str
    source: str
    role: str
    target_family: str
    hof_rank: int | None
    hof_survivor_name: str | None
    alias_of: str | None
    behavior_hash: str
    canonical_key: str
    n_rules: int
    strategy: MoleStrategy
    strategy_json: dict[str, Any]


_FRESH_EPISODE_CACHE: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}
_CF_REPLAY_CACHE: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}


def parse_seed_spec(spec: str | int | Iterable[int]) -> list[int]:
    if isinstance(spec, bool):
        raise ValueError("boolean is not a valid seed specification")
    if isinstance(spec, int):
        if spec <= 0:
            raise ValueError("integer seed count must be positive")
        return list(range(6200, 6200 + int(spec)))
    if not isinstance(spec, str):
        out = []
        for item in spec:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(f"non-integer seed: {item!r}")
            out.append(int(item))
        if not out:
            raise ValueError("seed sequence must not be empty")
        return out

    out_list: list[int] = []
    for part in spec.split(","):
        tok = part.strip()
        if not tok:
            continue
        if ":" in tok:
            lo_s, hi_s = tok.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi <= lo:
                raise ValueError(f"empty or reversed seed slice: {tok!r}")
            out_list.extend(range(lo, hi))
        elif "-" in tok and not tok.startswith("-"):
            lo_s, hi_s = tok.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if hi < lo:
                raise ValueError(f"reversed seed range: {tok!r}")
            out_list.extend(range(lo, hi + 1))
        else:
            out_list.append(int(tok))
    if not out_list:
        raise ValueError(f"no seeds parsed from {spec!r}")
    return out_list


def validate_transfer_seeds(seeds: Sequence[int]) -> list[int]:
    if not seeds:
        raise ValueError("fresh transfer seeds must not be empty")
    clean: list[int] = []
    seen: set[int] = set()
    for raw in seeds:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(f"fresh transfer seeds contain non-integer value: {raw!r}")
        s = int(raw)
        if s < 0 or s <= FORBIDDEN_LOW_SEED_MAX:
            raise ValueError(
                f"seed {s} violates transfer seed hygiene (negatives and 0..{FORBIDDEN_LOW_SEED_MAX} blocked)"
            )
        if s in RESERVED_HELDOUT_SEEDS:
            raise ValueError(f"seed {s} falls in blocked reserved range 30000..30199")
        if s >= FORBIDDEN_HIGH_SEED_MIN or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
            raise ValueError(f"seed {s} falls in blocked heldout/judge range 800000+")
        if s in seen:
            raise ValueError(f"duplicate seed {s} in fresh transfer seed list")
        seen.add(s)
        clean.append(s)
    return clean


def _canonical_strategy_key(sj: dict[str, Any]) -> str:
    norm = validate_strategy({"rules": sj.get("rules", []), "default": sj["default"]})
    return canonical(norm)


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _round_floats(obj: Any, nd: int = 4) -> Any:
    if isinstance(obj, bool) or obj is None:
        return obj
    if isinstance(obj, float):
        return round(obj, nd) if math.isfinite(obj) else obj
    if isinstance(obj, dict):
        return {k: _round_floats(v, nd=nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_floats(v, nd=nd) for v in obj]
    if isinstance(obj, tuple):
        return [_round_floats(v, nd=nd) for v in obj]
    return obj


def bootstrap_ci(
    xs: Sequence[float],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed_tag: str = "0",
) -> dict[str, float]:
    vals = [float(x) for x in xs]
    n = len(vals)
    if n == 0:
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0, "ci95_half": 0.0}
    m = _mean(vals)
    if n == 1 or n_boot <= 0:
        return {"mean": m, "ci95_lo": m, "ci95_hi": m, "ci95_half": 0.0}
    if all(v == vals[0] for v in vals):
        return {"mean": m, "ci95_lo": m, "ci95_hi": m, "ci95_half": 0.0}
    rng = random.Random(f"transfer-boot:{seed_tag}:{n}:{n_boot}")
    inv_n = 1.0 / n
    draws = [sum(rng.choices(vals, k=n)) * inv_n for _ in range(n_boot)]
    draws.sort()
    lo = draws[int(0.025 * n_boot)]
    hi = draws[min(n_boot - 1, int(0.975 * n_boot))]
    return {
        "mean": m,
        "ci95_lo": lo,
        "ci95_hi": hi,
        "ci95_half": 0.5 * (hi - lo),
    }


def paired_bootstrap_ci(
    xs: Sequence[float],
    ys: Sequence[float],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed_tag: str = "paired",
) -> dict[str, float]:
    if len(xs) != len(ys):
        raise ValueError(f"paired sequences must have equal length: {len(xs)} != {len(ys)}")
    diffs = [float(x) - float(y) for x, y in zip(xs, ys)]
    return bootstrap_ci(diffs, n_boot=n_boot, seed_tag=seed_tag)


def paired_minimax_gain_bootstrap_ci(
    strat_matrix: dict[str, Sequence[float]],
    base_matrix: dict[str, Sequence[float]],
    keys: Sequence[str],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    seed_tag: str = "minimax",
) -> dict[str, float]:
    key_list = list(keys)
    if not key_list:
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0, "ci95_half": 0.0}
    n = len(strat_matrix[key_list[0]])
    for k in key_list:
        if len(strat_matrix[k]) != n or len(base_matrix[k]) != n:
            raise ValueError(f"unequal vector length for {k}")
    if n == 0:
        return {"mean": 0.0, "ci95_lo": 0.0, "ci95_hi": 0.0, "ci95_half": 0.0}
    strat_min = min(_mean(strat_matrix[k]) for k in key_list)
    base_min = min(_mean(base_matrix[k]) for k in key_list)
    point = strat_min - base_min
    if n == 1 or n_boot <= 0:
        return {"mean": point, "ci95_lo": point, "ci95_hi": point, "ci95_half": 0.0}
    rng = random.Random(f"transfer-minimax:{seed_tag}:{n}:{n_boot}")
    m_keys = len(key_list)
    s_rows = [tuple(float(strat_matrix[k][i]) for k in key_list) for i in range(n)]
    b_rows = [tuple(float(base_matrix[k][i]) for k in key_list) for i in range(n)]
    paired_rows = list(zip(s_rows, b_rows))
    inv_n = 1.0 / n
    draws: list[float] = []
    for _ in range(n_boot):
        picked = rng.choices(paired_rows, k=n)
        s_min = min(sum(sr[j] for sr, _ in picked) * inv_n for j in range(m_keys))
        b_min = min(sum(br[j] for _, br in picked) * inv_n for j in range(m_keys))
        draws.append(s_min - b_min)
    draws.sort()
    lo = draws[int(0.025 * n_boot)]
    hi = draws[min(n_boot - 1, int(0.975 * n_boot))]
    return {
        "mean": point,
        "ci95_lo": lo,
        "ci95_hi": hi,
        "ci95_half": 0.5 * (hi - lo),
    }


def _load_hof_survivor_map(hof_path: Path) -> dict[str, str]:
    meta_path = hof_path.with_suffix(".meta.json")
    if not meta_path.is_file() and hof_path.resolve() == DEFAULT_HOF_V14_PATH.resolve():
        meta_path = DEFAULT_HOF_V14_META_PATH
    if not meta_path.is_file():
        return {}
    raw = json.loads(meta_path.read_text(encoding="utf-8"))
    by_bhash: dict[str, str] = {}
    for sname, bhash in (raw.get("survivor_behavior_hashes") or {}).items():
        by_bhash[str(bhash)] = str(sname)
    return by_bhash


def load_transfer_catalog(
    hof_path: str | Path = DEFAULT_HOF_V14_PATH,
    tier: str = "hard",
    selected_names: Sequence[str] | None = None,
) -> dict[str, CatalogStrategyEntry]:
    with tiers_version("v1.4"):
        entries: dict[str, CatalogStrategyEntry] = {}
        by_canon: dict[str, CatalogStrategyEntry] = {}

        def_sj = DEFAULT_STRATEGY.to_json()
        def_ck = _canonical_strategy_key(def_sj)
        def_bh = behavior_hash(def_sj, tier)
        def_entry = CatalogStrategyEntry(
            key="default",
            source="baseline",
            role="baseline",
            target_family="none",
            hof_rank=None,
            hof_survivor_name=None,
            alias_of=None,
            behavior_hash=def_bh,
            canonical_key=def_ck,
            n_rules=len(DEFAULT_STRATEGY.rules),
            strategy=DEFAULT_STRATEGY,
            strategy_json=copy.deepcopy(def_sj),
        )
        entries["default"] = def_entry
        by_canon[def_ck] = def_entry

        for name, spec in STRATEGY_SPECS.items():
            sj = spec.to_json()
            strat = MoleStrategy.from_json(sj)
            if len(strat.rules) > MAX_RULES:
                raise ValueError(f"strategy {name!r} exceeds MAX_RULES")
            if not all(is_valid_rule_conds(r["if"], tier) for r in sj.get("rules", [])):
                raise ValueError(f"strategy {name!r} has invalid rule conditions on {tier}")
            ck = _canonical_strategy_key(sj)
            bh = behavior_hash(sj, tier)
            role = "generalist" if spec.target_cohort == "frontier_all" else "specialist"
            ent = CatalogStrategyEntry(
                key=name,
                source="transcript_strategies",
                role=role,
                target_family=spec.target_cohort,
                hof_rank=None,
                hof_survivor_name=None,
                alias_of=by_canon[ck].key if ck in by_canon else None,
                behavior_hash=bh,
                canonical_key=ck,
                n_rules=len(strat.rules),
                strategy=strat,
                strategy_json=sj,
            )
            entries[name] = ent
            by_canon.setdefault(ck, ent)

        resolved_hof = Path(hof_path)
        if not resolved_hof.is_file():
            raise FileNotFoundError(f"hall of fame JSONL not found: {resolved_hof}")
        survivor_by_bhash = _load_hof_survivor_map(resolved_hof)
        lines = [ln for ln in resolved_hof.read_text(encoding="utf-8").splitlines() if ln.strip()]
        for idx, ln in enumerate(lines):
            row = json.loads(ln)
            rank = int(row.get("rank", idx + 1))
            key = f"hof_v14_r{rank}"
            raw_sj = dict(row.get("strategy_json", row.get("strategy", row)))
            raw_sj["name"] = key
            strat = MoleStrategy.from_json(raw_sj)
            if len(strat.rules) > MAX_RULES:
                raise ValueError(f"HOF strategy {key!r} exceeds MAX_RULES")
            if not all(is_valid_rule_conds(r["if"], tier) for r in raw_sj.get("rules", [])):
                raise ValueError(f"HOF strategy {key!r} has invalid rule conditions on {tier}")
            ck = _canonical_strategy_key(raw_sj)
            bh = behavior_hash(raw_sj, tier)
            alias_entry = by_canon.get(ck)
            surv_name = row.get("name") or survivor_by_bhash.get(bh)
            if alias_entry is not None:
                role = alias_entry.role
                target_family = alias_entry.target_family
                alias_of = alias_entry.key
            else:
                role = "generalist"
                target_family = "frontier_all"
                alias_of = None
            ent = CatalogStrategyEntry(
                key=key,
                source="hall_of_fame_v1.4",
                role=role,
                target_family=target_family,
                hof_rank=rank,
                hof_survivor_name=str(surv_name) if surv_name else None,
                alias_of=alias_of,
                behavior_hash=bh,
                canonical_key=ck,
                n_rules=len(strat.rules),
                strategy=strat,
                strategy_json=strat.to_json(),
            )
            entries[key] = ent
            by_canon.setdefault(ck, ent)

    if selected_names is None:
        return entries

    wanted: list[str] = []
    for raw_name in selected_names:
        nm = raw_name.strip()
        if not nm:
            continue
        if nm in ("default_v0", DEFAULT_STRATEGY.name):
            nm = "default"
        if nm not in entries:
            raise KeyError(f"unknown strategy {raw_name!r}; expected one of {sorted(entries)}")
        if nm not in wanted:
            wanted.append(nm)
    if not wanted:
        raise ValueError("selected_names must not be empty")
    return {nm: entries[nm] for nm in wanted}


def parse_raw_transcript_calls(transcript_path: str | Path) -> list[tuple[str, dict[str, Any]]]:
    fp = Path(transcript_path)
    if not fp.is_file():
        raise FileNotFoundError(f"transcript file not found: {fp}")
    text = fp.read_text(encoding="utf-8")
    if fp.suffix == ".json":
        messages = json.loads(text)
        if not isinstance(messages, list):
            raise ValueError(f"expected JSON message list in {fp}")
        calls: list[tuple[str, dict[str, Any]]] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            for tc in msg.get("tool_calls") or []:
                if isinstance(tc, dict) and isinstance(tc.get("name"), str):
                    raw_args = tc.get("args")
                    calls.append((tc["name"], dict(raw_args) if isinstance(raw_args, dict) else {}))
        return calls

    calls_txt: list[tuple[str, dict[str, Any]]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        ev_type = obj.get("type")
        if ev_type == "item.completed":
            item = obj.get("item")
            if (
                isinstance(item, dict)
                and item.get("type") == "mcp_tool_call"
                and item.get("server") in ("canary", None)
                and isinstance(item.get("tool"), str)
            ):
                raw_args = item.get("arguments")
                calls_txt.append((item["tool"], dict(raw_args) if isinstance(raw_args, dict) else {}))
        elif ev_type == "tool_use":
            part = obj.get("part")
            if isinstance(part, dict) and part.get("type") == "tool" and isinstance(part.get("tool"), str):
                tname = part["tool"]
                if tname.startswith("canary_"):
                    tname = tname[len("canary_") :]
                state = part.get("state")
                inp = state.get("input") if isinstance(state, dict) else None
                calls_txt.append((tname, dict(inp) if isinstance(inp, dict) else {}))
    return calls_txt


def _infer_episode_version(ep: EpisodeResult, explicit_version: str | None = None) -> str:
    if explicit_version is not None:
        return explicit_version
    meta_ver = (ep.meta or {}).get("tiers_version")
    if isinstance(meta_ver, str) and meta_ver in ("v1.3", "v1.4"):
        return meta_ver
    p = tier_params_for_episode(ep.tier, ep.steps)
    if ep.tier == "hard" and p.n_employees == 30:
        return "v1.3"
    return "v1.4"


def reconstruct_public_trajectory(
    episode: EpisodeResult | dict[str, Any],
    transcript_path: str | Path | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    ep = to_result(episode) if isinstance(episode, dict) else episode
    ver = _infer_episode_version(ep, explicit_version=version)

    recorded_calls = [(st.tool, dict(st.args or {})) for st in ep.steps]
    recorded_public_calls = [
        (st.tool, dict(st.args or {}))
        for st in ep.steps
        if st.tool in REPLAY_TOOLS or st.tool == "accuse"
    ]
    transcript_verified = False
    if transcript_path is not None:
        tp = Path(transcript_path)
        if tp.is_file():
            raw_calls = parse_raw_transcript_calls(tp)
            raw_public_calls = [
                (tname, targs)
                for tname, targs in raw_calls
                if tname in REPLAY_TOOLS or tname == "accuse"
            ]
            if raw_public_calls != recorded_public_calls:
                raise ValueError(
                    f"transcript tool mismatch for {ep.agent} {ep.tier} seed={ep.seed}: "
                    f"transcript={len(raw_public_calls)} vs episode={len(recorded_public_calls)}"
                )
            transcript_verified = True

    with tiers_version(ver):
        params = tier_params(ep.tier)
        horizon_day = int(params.n_days)
        true_mole = generate_world(ep.tier, int(ep.seed), params).mole
        rec_audit = audit_episode(ep)

    accuse_day = int(ep.final_day)
    for st in ep.steps:
        if st.tool == "accuse":
            accuse_day = int(st.day)
            break
    target_accuse_day = max(1, min(accuse_day, horizon_day))

    actions: list[tuple[str, dict[str, Any]]] = []
    sim_day = 1
    saw_employees = False
    for st in ep.steps:
        if st.tool == "accuse":
            break
        if st.day > target_accuse_day:
            break
        if st.day == target_accuse_day and st.tool == "advance_day":
            break
        if st.tool not in REPLAY_TOOLS:
            if isinstance(st.result, dict) and st.result.get("ok") is False:
                continue
            raise ValueError(f"non-public tool {st.tool!r} encountered in {ep.agent} seed={ep.seed}")
        actions.append((st.tool, dict(st.args or {})))
        if st.tool == "list_employees" and bool((st.result or {}).get("ok", True)):
            saw_employees = True
        elif st.tool == "advance_day" and bool((st.result or {}).get("ok", True)):
            sim_day += 1

    accuse_prefix_len = len(actions)
    horizon_actions = list(actions)
    if sim_day < horizon_day:
        while sim_day < horizon_day:
            horizon_actions.append(("advance_day", {}))
            sim_day += 1
        if not saw_employees:
            horizon_actions.append(("list_employees", {}))
        horizon_actions.append(("status", {}))
        horizon_actions.append(("list_documents", {"day_from": 1, "day_to": horizon_day}))
        horizon_actions.append(("check_leak_feed", {}))

    return {
        "version": ver,
        "tier": ep.tier,
        "seed": int(ep.seed),
        "agent": ep.agent,
        "true_mole": true_mole,
        "accuse_day": target_accuse_day,
        "horizon_day": horizon_day,
        "recorded_accused": ep.accused,
        "recorded_correct": bool(ep.correct),
        "recorded_score": float(ep.score),
        "recorded_p_accused": rec_audit["p_accused"],
        "recorded_p_top": rec_audit["p_top"],
        "recorded_verdict": rec_audit["verdict"],
        "accuse_prefix_len": accuse_prefix_len,
        "schedule": horizon_actions,
        "raw_call_count": len(recorded_calls),
        "transcript_verified": transcript_verified,
    }


def _find_transcript_file(cohort_dir: Path, seed: int) -> Path | None:
    tx_dir = cohort_dir / "transcripts"
    if not tx_dir.is_dir():
        return None
    for ext in (".txt", ".json"):
        cand = tx_dir / f"{seed}{ext}"
        if cand.is_file():
            return cand
    return None


def is_excluded_committed_path(rel_parts: Sequence[str]) -> bool:
    if "superseded" in rel_parts or "reference" in rel_parts:
        return True
    return any(
        part.endswith(("-smoke", "-ext")) or "seeds30to59" in part
        for part in rel_parts
    )


def discover_primary_frontier_episode_files(
    committed_root: str | Path = DEFAULT_COMMITTED_ROOT,
    versions: Sequence[str] = ("v1.4", "v1.3"),
) -> list[Path]:
    base = Path(committed_root)
    if (base / "data" / "runs" / "committed").is_dir():
        base = base / "data" / "runs" / "committed"
    found: list[Path] = []
    for ver in versions:
        ver_dir = base / ver
        if not ver_dir.is_dir():
            continue
        for fpath in sorted(ver_dir.rglob("episodes.jsonl")):
            rel_parts = fpath.relative_to(ver_dir).parts
            if is_excluded_committed_path(rel_parts):
                continue
            found.append(fpath)
    return found


def load_cohort_trajectories(
    spec: FrontierCohortSpec,
    committed_root: str | Path = DEFAULT_COMMITTED_ROOT,
    seeds: Iterable[int] | None = None,
    allow_extended: bool = False,
) -> list[dict[str, Any]]:
    rel_parts = Path(spec.rel_dir).parts
    if not allow_extended and is_excluded_committed_path(rel_parts):
        raise ValueError(f"excluded non-primary committed cohort path: {spec.rel_dir}")
    base = Path(committed_root)
    if (base / "data" / "runs" / "committed").is_dir():
        base = base / "data" / "runs" / "committed"
    cohort_dir = base / spec.rel_dir
    ep_path = cohort_dir / "episodes.jsonl"
    if not ep_path.is_file():
        raise FileNotFoundError(f"committed episodes file not found: {ep_path}")

    wanted = {int(s) for s in seeds} if seeds is not None else None
    by_seed: dict[int, dict[str, Any]] = {}
    for raw_line in ep_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        raw = json.loads(line)
        if (raw.get("meta") or {}).get("valid") is False:
            continue
        s = int(raw["seed"])
        if wanted is not None:
            if s not in wanted:
                continue
        elif not allow_extended and (s < 0 or s > PRIMARY_COHORT_SEED_MAX):
            continue
        tx_file = _find_transcript_file(cohort_dir, s)
        rec = reconstruct_public_trajectory(raw, transcript_path=tx_file, version=spec.version)
        rec["cohort_id"] = spec.cohort_id
        rec["family"] = spec.family
        rec["harness"] = spec.harness
        by_seed[s] = rec
    return [by_seed[s] for s in sorted(by_seed)]


def replay_trajectory_counterfactual(
    trajectory: dict[str, Any],
    strategy: MoleStrategy,
    canonical_key: str | None = None,
    include_horizon: bool = False,
) -> dict[str, Any]:
    ver = str(trajectory["version"])
    tier = str(trajectory["tier"])
    seed = int(trajectory["seed"])
    cohort_id = str(trajectory.get("cohort_id") or trajectory["agent"])
    ckey = canonical_key or _canonical_strategy_key(strategy.to_json())
    cache_key = (cohort_id, ver, seed, tier, f"{ckey}:h={int(include_horizon)}")
    if cache_key in _CF_REPLAY_CACHE:
        cached = dict(_CF_REPLAY_CACHE[cache_key])
        cached["strategy"] = strategy.name
        return cached

    prefix_len = int(trajectory["accuse_prefix_len"])
    run_sched = trajectory["schedule"] if include_horizon else trajectory["schedule"][:prefix_len]

    with tiers_version(ver):
        env = Env(tier, seed, mole_strategy=strategy)
        for tool, args in run_sched:
            if env.done:
                raise RuntimeError(
                    f"counterfactual schedule ended prematurely on {cohort_id} {tier} seed={seed}"
                )
            env.call(tool, dict(args))
        full_hist: list[Step] = list(env.history)
        accuse_hist = full_hist[:prefix_len]
        at_accuse = inspect_observation_history(
            accuse_hist,
            tier=tier,
            seed=seed,
            recorded_accused=trajectory["recorded_accused"],
            true_mole=trajectory["true_mole"],
        )
        if not include_horizon or len(full_hist) == len(accuse_hist):
            at_horizon = at_accuse
        else:
            at_horizon = inspect_observation_history(
                full_hist,
                tier=tier,
                seed=seed,
                recorded_accused=trajectory["recorded_accused"],
                true_mole=trajectory["true_mole"],
            )

    baseline_audit_match = True
    if ckey == _canonical_strategy_key(DEFAULT_STRATEGY.to_json()) and trajectory["recorded_accused"] is not None:
        p_top_match = round(float(at_accuse["max_posterior"]), 3) == trajectory["recorded_p_top"]
        p_acc_match = round(float(at_accuse["p_recorded_accused"] or 0.0), 3) == (
            trajectory["recorded_p_accused"] or 0.0
        )
        baseline_audit_match = bool(p_top_match and p_acc_match)

    result = {
        "cohort_id": cohort_id,
        "family": trajectory.get("family"),
        "harness": trajectory.get("harness"),
        "version": ver,
        "tier": tier,
        "seed": seed,
        "agent": trajectory["agent"],
        "strategy": strategy.name,
        "accuse_day": int(trajectory["accuse_day"]),
        "horizon_day": int(trajectory["horizon_day"]),
        "recorded_accused": trajectory["recorded_accused"],
        "recorded_correct": bool(trajectory["recorded_correct"]),
        "recorded_score": float(trajectory["recorded_score"]),
        "transcript_verified": bool(trajectory["transcript_verified"]),
        "baseline_audit_match": baseline_audit_match,
        "known_V": float(at_accuse["known_V"]),
        "known_V_horizon": float(at_horizon["known_V"]),
        "p_true_mole": float(at_accuse["p_true_mole"]),
        "p_true_mole_horizon": float(at_horizon["p_true_mole"]),
        "max_posterior": float(at_accuse["max_posterior"]),
        "max_posterior_horizon": float(at_horizon["max_posterior"]),
        "optimal_ev": float(at_accuse["optimal_ev"]),
        "optimal_ev_horizon": float(at_horizon["optimal_ev"]),
        "top_is_true_mole": bool(at_accuse["top_is_true_mole"]),
        "top_is_true_mole_horizon": bool(at_horizon["top_is_true_mole"]),
        "surfaced_canaries": int(at_accuse["surfaced_canaries"]),
        "surfaced_canaries_horizon": int(at_horizon["surfaced_canaries"]),
        "surfaced_total_leaks": int(at_accuse["surfaced_total_leaks"]),
        "surfaced_total_leaks_horizon": int(at_horizon["surfaced_total_leaks"]),
        "planted_canaries": int(at_accuse["planted_canaries"]),
    }
    _CF_REPLAY_CACHE[cache_key] = dict(result)
    return result


def _eval_cf_strategy_task(
    task: tuple[str, dict[str, Any], dict[str, list[dict[str, Any]]]],
) -> tuple[str, dict[str, list[dict[str, Any]]]]:
    ckey, strat_json, trajectories_by_cohort = task
    strat = MoleStrategy.from_json(strat_json)
    rows_by_cohort = {
        cid: [
            replay_trajectory_counterfactual(tr, strat, canonical_key=ckey)
            for tr in tr_list
        ]
        for cid, tr_list in trajectories_by_cohort.items()
    }
    return ckey, rows_by_cohort


def _summarize_cf_pair(
    strat_rows: Sequence[dict[str, Any]],
    base_rows: Sequence[dict[str, Any]],
    n_boot: int,
    seed_tag: str,
    compact: bool = False,
) -> dict[str, Any]:
    base_map = {(r["cohort_id"], r["seed"]): r for r in base_rows}
    pairs = [
        (s_row, base_map[(s_row["cohort_id"], s_row["seed"])])
        for s_row in strat_rows
        if (s_row["cohort_id"], s_row["seed"]) in base_map
    ]
    n = len(pairs)
    if n == 0:
        return {"n": 0}

    s_p = [e["p_true_mole"] for e, _ in pairs]
    b_p = [b["p_true_mole"] for _, b in pairs]
    s_ev = [e["optimal_ev"] for e, _ in pairs]
    b_ev = [b["optimal_ev"] for _, b in pairs]
    s_top = [1.0 if e["top_is_true_mole"] else 0.0 for e, _ in pairs]
    b_top = [1.0 if b["top_is_true_mole"] else 0.0 for _, b in pairs]
    s_can = [float(e["surfaced_canaries"]) for e, _ in pairs]
    b_can = [float(b["surfaced_canaries"]) for _, b in pairs]
    s_tot = [float(e["surfaced_total_leaks"]) for e, _ in pairs]
    b_tot = [float(b["surfaced_total_leaks"]) for _, b in pairs]

    ev_drop_ci = paired_bootstrap_ci(b_ev, s_ev, n_boot=n_boot, seed_tag=f"{seed_tag}:evdrop")
    top_drop_mean = _mean([b - a for a, b in zip(s_top, b_top)])
    can_delta = _mean([a - b for a, b in zip(s_can, b_can)])
    tot_delta = _mean([a - b for a, b in zip(s_tot, b_tot)])

    if compact:
        return {
            "n": n,
            "p_true_mole_drop": _mean([b - a for a, b in zip(s_p, b_p)]),
            "optimal_ev_drop": ev_drop_ci["mean"],
            "top_suspect_acc_drop": top_drop_mean,
            "surfaced_canaries_delta": can_delta,
        }

    p_drop_ci = paired_bootstrap_ci(b_p, s_p, n_boot=n_boot, seed_tag=f"{seed_tag}:pdrop")
    return {
        "n": n,
        "p_true_mole": _mean(s_p),
        "optimal_ev": _mean(s_ev),
        "top_suspect_acc": _mean(s_top),
        "surfaced_canaries": _mean(s_can),
        "surfaced_total_leaks": _mean(s_tot),
        "surfaced_canaries_delta": can_delta,
        "surfaced_total_leaks_delta": tot_delta,
        "p_true_mole_drop": p_drop_ci["mean"],
        "p_true_mole_drop_ci95": p_drop_ci,
        "optimal_ev_drop": ev_drop_ci["mean"],
        "optimal_ev_drop_ci95": ev_drop_ci,
        "top_suspect_acc_drop": top_drop_mean,
    }


def evaluate_cross_family_counterfactual(
    catalog: dict[str, CatalogStrategyEntry],
    committed_root: str | Path = DEFAULT_COMMITTED_ROOT,
    cohort_ids: Sequence[str] | None = None,
    seeds: Iterable[int] | None = None,
    workers: int = DEFAULT_WORKERS,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
) -> dict[str, Any]:
    if int(workers) < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    selected_cohorts = (
        [FRONTIER_COHORT_MAP[cid] for cid in cohort_ids]
        if cohort_ids is not None
        else list(FRONTIER_COHORTS)
    )
    if not selected_cohorts:
        raise ValueError("selected_cohorts must not be empty")

    trajectories_by_cohort: dict[str, list[dict[str, Any]]] = {
        spec.cohort_id: load_cohort_trajectories(spec, committed_root=committed_root, seeds=seeds)
        for spec in selected_cohorts
    }
    total_eps = sum(len(v) for v in trajectories_by_cohort.values())
    if total_eps == 0:
        raise ValueError("no committed frontier episodes loaded for counterfactual replay")

    def_ckey = _canonical_strategy_key(DEFAULT_STRATEGY.to_json())
    unique_strats: dict[str, MoleStrategy] = {def_ckey: DEFAULT_STRATEGY}
    for ent in catalog.values():
        unique_strats.setdefault(ent.canonical_key, ent.strategy)

    missing_ckeys = [
        ckey
        for ckey in unique_strats
        if any(
            (spec.cohort_id, str(tr["version"]), int(tr["seed"]), str(tr["tier"]), f"{ckey}:h=0") not in _CF_REPLAY_CACHE
            for spec in selected_cohorts
            for tr in trajectories_by_cohort[spec.cohort_id]
        )
    ]
    if missing_ckeys and int(workers) > 1 and len(missing_ckeys) > 1:
        cf_tasks = [
            (ckey, unique_strats[ckey].to_json(), trajectories_by_cohort)
            for ckey in missing_ckeys
        ]
        with ProcessPoolExecutor(max_workers=min(int(workers), len(cf_tasks))) as pool:
            for ckey, rows_map in pool.map(_eval_cf_strategy_task, cf_tasks):
                for cid, row_list in rows_map.items():
                    for r in row_list:
                        _CF_REPLAY_CACHE[(cid, str(r["version"]), int(r["seed"]), str(r["tier"]), f"{ckey}:h=0")] = dict(r)

    base_rows_by_cohort: dict[str, list[dict[str, Any]]] = {
        spec.cohort_id: [
            replay_trajectory_counterfactual(tr, DEFAULT_STRATEGY, canonical_key=def_ckey)
            for tr in trajectories_by_cohort[spec.cohort_id]
        ]
        for spec in selected_cohorts
    }
    for cid, rows in base_rows_by_cohort.items():
        bad = [r["seed"] for r in rows if not r["baseline_audit_match"]]
        if bad:
            raise ValueError(f"baseline counterfactual replay failed audit parity on {cid} seeds={bad}")

    cohort_meta = {
        spec.cohort_id: {
            "cohort_id": spec.cohort_id,
            "version": spec.version,
            "tier": spec.tier,
            "family": spec.family,
            "harness": spec.harness,
            "label": spec.label,
            "n_episodes": len(trajectories_by_cohort[spec.cohort_id]),
            "seeds": [int(t["seed"]) for t in trajectories_by_cohort[spec.cohort_id]],
            "transcript_verified_count": sum(
                1 for t in trajectories_by_cohort[spec.cohort_id] if t["transcript_verified"]
            ),
            "baseline_audit_match_count": sum(
                1 for r in base_rows_by_cohort[spec.cohort_id] if r["baseline_audit_match"]
            ),
        }
        for spec in selected_cohorts
    }

    active_cids = {spec.cohort_id for spec in selected_cohorts}
    active_rollups: dict[str, list[str]] = {
        rname: [cid for cid in cids if cid in active_cids]
        for rname, cids in COUNTERFACTUAL_ROLLUPS.items()
    }
    active_rollups = {k: v for k, v in active_rollups.items() if v}

    cf_summary_by_ckey: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    out_strategies: dict[str, dict[str, Any]] = {}
    for skey, entry in catalog.items():
        if entry.canonical_key in cf_summary_by_ckey:
            per_cohort, rollups = copy.deepcopy(cf_summary_by_ckey[entry.canonical_key])
        else:
            rows_by_cohort: dict[str, list[dict[str, Any]]] = {
                spec.cohort_id: [
                    replay_trajectory_counterfactual(
                        tr,
                        entry.strategy,
                        canonical_key=entry.canonical_key,
                    )
                    for tr in trajectories_by_cohort[spec.cohort_id]
                ]
                for spec in selected_cohorts
            }
            per_cohort = {
                spec.cohort_id: _summarize_cf_pair(
                    rows_by_cohort[spec.cohort_id],
                    base_rows_by_cohort[spec.cohort_id],
                    n_boot=n_boot,
                    seed_tag=f"cf:{entry.canonical_key[:10]}:{spec.cohort_id}",
                    compact=True,
                )
                for spec in selected_cohorts
            }
            rollups = {}
            for rname, cids in active_rollups.items():
                s_comb = [r for cid in cids for r in rows_by_cohort[cid]]
                b_comb = [r for cid in cids for r in base_rows_by_cohort[cid]]
                rollups[rname] = _summarize_cf_pair(
                    s_comb,
                    b_comb,
                    n_boot=n_boot,
                    seed_tag=f"cf:{entry.canonical_key[:10]}:{rname}",
                    compact=False,
                )
            cf_summary_by_ckey[entry.canonical_key] = (copy.deepcopy(per_cohort), copy.deepcopy(rollups))

        gem_ev_drop = rollups.get("gemini_4_carbon_hard", {}).get("optimal_ev_drop")
        cdx_all_ev_drop = rollups.get("codex_gpt55_all", {}).get("optimal_ev_drop")
        cdx_hard_ev_drop = rollups.get("codex_gpt55_hard", {}).get("optimal_ev_drop")
        worst_family_ev_drop = (
            min(float(gem_ev_drop), float(cdx_all_ev_drop))
            if gem_ev_drop is not None and cdx_all_ev_drop is not None
            else None
        )
        hard_worst_family_ev_drop = (
            min(float(gem_ev_drop), float(cdx_hard_ev_drop))
            if gem_ev_drop is not None and cdx_hard_ev_drop is not None
            else None
        )
        mean_family_ev_drop = (
            0.5 * (float(gem_ev_drop) + float(cdx_all_ev_drop))
            if gem_ev_drop is not None and cdx_all_ev_drop is not None
            else None
        )

        in_dom_cf: float | None = None
        out_dom_cf: float | None = None
        cf_transfer_ratio: float | None = None
        if entry.role == "specialist" and gem_ev_drop is not None and cdx_all_ev_drop is not None:
            if entry.target_family == "gemini_4_carbon":
                in_dom_cf = float(gem_ev_drop)
                out_dom_cf = float(cdx_all_ev_drop)
            elif entry.target_family == "codex_gpt55":
                in_dom_cf = float(cdx_all_ev_drop)
                out_dom_cf = float(gem_ev_drop)
            if in_dom_cf is not None and out_dom_cf is not None and in_dom_cf > 1e-6:
                cf_transfer_ratio = out_dom_cf / in_dom_cf

        out_strategies[skey] = {
            "key": skey,
            "per_cohort": per_cohort,
            "rollups": rollups,
            "gemini_hard_ev_drop": gem_ev_drop,
            "codex_hard_ev_drop": cdx_hard_ev_drop,
            "codex_all_ev_drop": cdx_all_ev_drop,
            "worst_family_ev_drop": worst_family_ev_drop,
            "hard_worst_family_ev_drop": hard_worst_family_ev_drop,
            "mean_family_ev_drop": mean_family_ev_drop,
            "in_domain_cf_ev_drop": in_dom_cf,
            "out_of_domain_cf_ev_drop": out_dom_cf,
            "cf_transfer_ratio": cf_transfer_ratio,
        }

    return {
        "total_episodes": total_eps,
        "transcript_verified_total": sum(m["transcript_verified_count"] for m in cohort_meta.values()),
        "baseline_audit_match_total": sum(m["baseline_audit_match_count"] for m in cohort_meta.values()),
        "cohorts": cohort_meta,
        "rollup_definitions": active_rollups,
        "strategies": out_strategies,
    }


def _make_investigator(inv_name: str, tier: str, seed: int) -> Any:
    if inv_name == "solver":
        return SolverPolicy(tier if tier in TIERS else tier_params(tier), act_budget=5.0)
    if inv_name == "gemini_carbon_proxy":
        return GeminiCarbonProxy(seed=seed)
    if inv_name == "codex_horizon_proxy":
        return CodexHorizonProxy(seed=seed)
    if inv_name == "grok_tactics":
        return GrokTactics(seed=seed)
    if inv_name == "hinted_heuristic":
        return HintedHeuristic(seed=seed)
    if inv_name == "heuristic":
        return Heuristic(seed=seed)
    if inv_name == "logs_only":
        return LogsOnly(seed=seed)
    raise ValueError(f"unknown investigator {inv_name!r}")


def _eval_fresh_seed_batch_task(
    task: tuple[str, int, str, tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...]],
) -> tuple[int, dict[str, dict[str, dict[str, Any]]]]:
    tier, seed, ver, strat_specs = task
    out_by_ckey: dict[str, dict[str, dict[str, Any]]] = {}
    with tiers_version(ver):
        for ckey, strat_json, inv_names in strat_specs:
            strat = MoleStrategy.from_json(strat_json)
            per_inv: dict[str, dict[str, Any]] = {}
            for inv_name in inv_names:
                pol = _make_investigator(inv_name, tier=tier, seed=seed)
                res = run_episode(Env(tier, seed, mole_strategy=strat), pol)
                per_inv[inv_name] = {
                    "score": float(res.score),
                    "correct": bool(res.correct),
                    "final_day": int(res.final_day),
                    "end_reason": str(res.end_reason),
                }
            out_by_ckey[ckey] = per_inv
    return int(seed), out_by_ckey


def _populate_fresh_episode_cache(
    tier: str,
    seeds: Sequence[int],
    strategies_by_ckey: dict[str, MoleStrategy],
    investigators: Sequence[str],
    workers: int = 1,
    version: str = "v1.4",
) -> None:
    inv_tuple = tuple(investigators)
    sj_by_ckey = {ck: st.to_json() for ck, st in strategies_by_ckey.items()}
    batch_tasks: list[tuple[str, int, str, tuple[tuple[str, dict[str, Any], tuple[str, ...]], ...]]] = []
    for raw_s in seeds:
        s = int(raw_s)
        per_seed_specs: list[tuple[str, dict[str, Any], tuple[str, ...]]] = []
        for ckey, sj in sj_by_ckey.items():
            miss_invs = tuple(
                inv for inv in inv_tuple if (version, tier, s, ckey, inv) not in _FRESH_EPISODE_CACHE
            )
            if miss_invs:
                per_seed_specs.append((ckey, sj, miss_invs))
        if per_seed_specs:
            batch_tasks.append((tier, s, version, tuple(per_seed_specs)))

    if not batch_tasks:
        return
    if workers > 1 and len(batch_tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(workers, len(batch_tasks))) as pool:
            computed = list(pool.map(_eval_fresh_seed_batch_task, batch_tasks))
    else:
        computed = [_eval_fresh_seed_batch_task(t) for t in batch_tasks]

    for seed_val, by_ckey in computed:
        for ckey, per_inv in by_ckey.items():
            for inv_name, outcome in per_inv.items():
                _FRESH_EPISODE_CACHE[(version, tier, seed_val, ckey, inv_name)] = outcome


def _run_fresh_strategy_panel(
    tier: str,
    seeds: Sequence[int],
    strategy: MoleStrategy,
    canonical_key: str,
    investigators: Sequence[str],
    workers: int = 1,
    version: str = "v1.4",
) -> dict[int, dict[str, dict[str, Any]]]:
    inv_tuple = tuple(investigators)
    _populate_fresh_episode_cache(
        tier=tier,
        seeds=seeds,
        strategies_by_ckey={canonical_key: strategy},
        investigators=inv_tuple,
        workers=workers,
        version=version,
    )
    return {
        int(s): {
            inv: dict(_FRESH_EPISODE_CACHE[(version, tier, int(s), canonical_key, inv)])
            for inv in inv_tuple
        }
        for s in seeds
    }


def evaluate_fresh_seed_transfer(
    catalog: dict[str, CatalogStrategyEntry],
    seeds: str | int | Iterable[int] = DEFAULT_FRESH_SEEDS,
    tier: str = "hard",
    workers: int = DEFAULT_WORKERS,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    investigators: Sequence[str] = TRANSFER_INVESTIGATORS,
) -> dict[str, Any]:
    if int(workers) < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    seed_list = validate_transfer_seeds(parse_seed_spec(seeds))
    inv_list = tuple(investigators)
    if "solver" not in inv_list or "logs_only" not in inv_list:
        raise ValueError("investigators must include 'solver' and 'logs_only'")

    def_ckey = _canonical_strategy_key(DEFAULT_STRATEGY.to_json())
    all_unique_strats: dict[str, MoleStrategy] = {def_ckey: DEFAULT_STRATEGY}
    for ent in catalog.values():
        all_unique_strats.setdefault(ent.canonical_key, ent.strategy)
    _populate_fresh_episode_cache(
        tier=tier,
        seeds=seed_list,
        strategies_by_ckey=all_unique_strats,
        investigators=inv_list,
        workers=int(workers),
        version="v1.4",
    )
    base_seed_map = _run_fresh_strategy_panel(
        tier=tier,
        seeds=seed_list,
        strategy=DEFAULT_STRATEGY,
        canonical_key=def_ckey,
        investigators=inv_list,
        workers=1,
        version="v1.4",
    )

    base_sol_scores = [base_seed_map[s]["solver"]["score"] for s in seed_list]
    base_sol_accs = [1.0 if base_seed_map[s]["solver"]["correct"] else 0.0 for s in seed_list]
    base_sol_mean = _mean(base_sol_scores)
    base_sol_acc = _mean(base_sol_accs)

    non_trivial = [inv for inv in NON_TRIVIAL_INVESTIGATORS if inv in inv_list]
    base_regret_vectors: dict[str, list[float]] = {
        inv: [base_seed_map[s]["solver"]["score"] - base_seed_map[s][inv]["score"] for s in seed_list]
        for inv in non_trivial
    }
    has_proxy_pair = all(p in base_regret_vectors for p in FRONTIER_PROXY_PAIR)
    base_proxy_min_regret = (
        min(_mean(base_regret_vectors[p]) for p in FRONTIER_PROXY_PAIR) if has_proxy_pair else None
    )
    base_panel_min_regret = (
        min(_mean(base_regret_vectors[inv]) for inv in non_trivial) if non_trivial else None
    )
    base_panel_mean_regret = (
        _mean([_mean(base_regret_vectors[inv]) for inv in non_trivial]) if non_trivial else None
    )

    out_strategies: dict[str, dict[str, Any]] = {}
    for skey, entry in catalog.items():
        seed_map = _run_fresh_strategy_panel(
            tier=tier,
            seeds=seed_list,
            strategy=entry.strategy,
            canonical_key=entry.canonical_key,
            investigators=inv_list,
            workers=int(workers),
            version="v1.4",
        )
        sol_scores = [seed_map[s]["solver"]["score"] for s in seed_list]
        sol_accs = [1.0 if seed_map[s]["solver"]["correct"] else 0.0 for s in seed_list]
        sol_days = [float(seed_map[s]["solver"]["final_day"]) for s in seed_list]
        sol_score_ci = bootstrap_ci(sol_scores, n_boot=n_boot, seed_tag=f"fresh:{entry.canonical_key[:10]}:sol_s")
        sol_acc_ci = bootstrap_ci(sol_accs, n_boot=n_boot, seed_tag=f"fresh:{entry.canonical_key[:10]}:sol_a")
        sol_delta_ci = paired_bootstrap_ci(
            sol_scores,
            base_sol_scores,
            n_boot=n_boot,
            seed_tag=f"fresh:{entry.canonical_key[:10]}:sol_d",
        )

        lo_scores = [seed_map[s]["logs_only"]["score"] for s in seed_list]
        lo_accs = [1.0 if seed_map[s]["logs_only"]["correct"] else 0.0 for s in seed_list]
        lo_score_ci = bootstrap_ci(lo_scores, n_boot=n_boot, seed_tag=f"fresh:{entry.canonical_key[:10]}:lo_s")
        lo_acc_ci = bootstrap_ci(lo_accs, n_boot=n_boot, seed_tag=f"fresh:{entry.canonical_key[:10]}:lo_a")

        solver_acc_val = sol_acc_ci["mean"]
        solver_score_val = sol_score_ci["mean"]
        logs_only_acc_val = lo_acc_ci["mean"]
        logs_only_score_val = lo_score_ci["mean"]

        solver_passed = bool(
            solver_acc_val >= float(min_solver_acc)
            and solver_score_val >= float(min_solver_ratio) * base_sol_mean
        )
        logs_only_passed = bool(logs_only_acc_val <= float(max_logs_acc) and logs_only_score_val < 0.0)
        gates_passed = bool(solver_passed and logs_only_passed)

        per_inv_summary: dict[str, dict[str, Any]] = {}
        regret_vectors: dict[str, list[float]] = {}
        regret_gain_vectors: dict[str, list[float]] = {}

        for inv in inv_list:
            inv_scores = [seed_map[s][inv]["score"] for s in seed_list]
            inv_accs = [1.0 if seed_map[s][inv]["correct"] else 0.0 for s in seed_list]
            inv_days = [float(seed_map[s][inv]["final_day"]) for s in seed_list]
            base_inv_scores = [base_seed_map[s][inv]["score"] for s in seed_list]
            base_inv_accs = [1.0 if base_seed_map[s][inv]["correct"] else 0.0 for s in seed_list]

            sc_mean = _mean(inv_scores)
            ac_mean = _mean(inv_accs)
            drop_ci = paired_bootstrap_ci(
                base_inv_scores,
                inv_scores,
                n_boot=n_boot,
                seed_tag=f"fresh:{entry.canonical_key[:10]}:{inv}:drop",
            )
            acc_drop_mean = _mean([b - a for a, b in zip(inv_accs, base_inv_accs)])

            inv_entry: dict[str, Any] = {
                "score": sc_mean,
                "acc": ac_mean,
                "mean_day": _mean(inv_days),
                "score_drop_vs_default": drop_ci["mean"],
                "score_drop_ci95": drop_ci,
                "acc_drop_vs_default": acc_drop_mean,
            }
            if inv != "solver":
                reg_vec = [sol_scores[i] - inv_scores[i] for i in range(len(seed_list))]
                base_reg_vec = [base_sol_scores[i] - base_inv_scores[i] for i in range(len(seed_list))]
                reg_gain_ci = paired_bootstrap_ci(
                    reg_vec,
                    base_reg_vec,
                    n_boot=n_boot,
                    seed_tag=f"fresh:{entry.canonical_key[:10]}:{inv}:rgain",
                )
                inv_entry["regret"] = _mean(reg_vec)
                inv_entry["regret_gain_vs_default"] = reg_gain_ci["mean"]
                inv_entry["regret_gain_ci95"] = reg_gain_ci
                if inv in non_trivial:
                    regret_vectors[inv] = reg_vec
                    regret_gain_vectors[inv] = [reg_vec[i] - base_reg_vec[i] for i in range(len(seed_list))]

            per_inv_summary[inv] = inv_entry

        proxy_min_regret: float | None = None
        proxy_min_gain_ci: dict[str, float] | None = None
        proxy_asym_ci: dict[str, float] | None = None
        if has_proxy_pair:
            proxy_min_regret = min(per_inv_summary[p]["regret"] for p in FRONTIER_PROXY_PAIR)
            proxy_min_gain_ci = paired_minimax_gain_bootstrap_ci(
                regret_vectors,
                base_regret_vectors,
                FRONTIER_PROXY_PAIR,
                n_boot=n_boot,
                seed_tag=f"fresh:{entry.canonical_key[:10]}:proxy_min",
            )
            proxy_asym_ci = paired_bootstrap_ci(
                regret_gain_vectors["gemini_carbon_proxy"],
                regret_gain_vectors["codex_horizon_proxy"],
                n_boot=n_boot,
                seed_tag=f"fresh:{entry.canonical_key[:10]}:proxy_asym",
            )

        panel_min_regret: float | None = None
        panel_min_gain_ci: dict[str, float] | None = None
        panel_mean_regret: float | None = None
        panel_mean_gain_ci: dict[str, float] | None = None
        strongest_inv: str | None = None
        if non_trivial:
            strongest_inv = min(sorted(non_trivial), key=lambda k: per_inv_summary[k]["regret"])
            panel_min_regret = float(per_inv_summary[strongest_inv]["regret"])
            panel_min_gain_ci = paired_minimax_gain_bootstrap_ci(
                regret_vectors,
                base_regret_vectors,
                non_trivial,
                n_boot=n_boot,
                seed_tag=f"fresh:{entry.canonical_key[:10]}:panel_min",
            )
            per_seed_mean_reg = [
                sum(regret_vectors[inv][i] for inv in non_trivial) / len(non_trivial)
                for i in range(len(seed_list))
            ]
            base_per_seed_mean_reg = [
                sum(base_regret_vectors[inv][i] for inv in non_trivial) / len(non_trivial)
                for i in range(len(seed_list))
            ]
            panel_mean_regret = _mean(per_seed_mean_reg)
            panel_mean_gain_ci = paired_bootstrap_ci(
                per_seed_mean_reg,
                base_per_seed_mean_reg,
                n_boot=n_boot,
                seed_tag=f"fresh:{entry.canonical_key[:10]}:panel_mean",
            )

        specialist_transfer: dict[str, Any] | None = None
        if entry.role == "specialist" and has_proxy_pair:
            if entry.target_family == "gemini_4_carbon":
                in_p, out_p = "gemini_carbon_proxy", "codex_horizon_proxy"
            else:
                in_p, out_p = "codex_horizon_proxy", "gemini_carbon_proxy"
            in_gain_ci = per_inv_summary[in_p]["regret_gain_ci95"]
            out_gain_ci = per_inv_summary[out_p]["regret_gain_ci95"]
            in_minus_out_ci = paired_bootstrap_ci(
                regret_gain_vectors[in_p],
                regret_gain_vectors[out_p],
                n_boot=n_boot,
                seed_tag=f"fresh:{entry.canonical_key[:10]}:spec_gap",
            )
            in_drop_ci = per_inv_summary[in_p]["score_drop_ci95"]
            out_drop_ci = per_inv_summary[out_p]["score_drop_ci95"]
            ratio = (
                out_gain_ci["mean"] / in_gain_ci["mean"]
                if in_gain_ci["mean"] > 1e-6
                else None
            )
            specialist_transfer = {
                "in_domain_proxy": in_p,
                "out_of_domain_proxy": out_p,
                "in_domain_regret_gain": in_gain_ci["mean"],
                "in_domain_regret_gain_ci95": in_gain_ci,
                "out_of_domain_regret_gain": out_gain_ci["mean"],
                "out_of_domain_regret_gain_ci95": out_gain_ci,
                "in_minus_out_regret_gain": in_minus_out_ci["mean"],
                "in_minus_out_regret_gain_ci95": in_minus_out_ci,
                "in_domain_score_drop": in_drop_ci["mean"],
                "out_of_domain_score_drop": out_drop_ci["mean"],
                "proxy_transfer_ratio": ratio,
            }

        out_strategies[skey] = {
            "key": skey,
            "solver_acc": solver_acc_val,
            "solver_score": solver_score_val,
            "solver_score_ci95": sol_score_ci,
            "solver_mean_day": _mean(sol_days),
            "solver_score_delta_vs_default": sol_delta_ci["mean"],
            "solver_score_delta_ci95": sol_delta_ci,
            "solver_ratio_vs_default": solver_score_val / base_sol_mean if base_sol_mean > 0 else 0.0,
            "logs_only_acc": logs_only_acc_val,
            "logs_only_score": logs_only_score_val,
            "solver_passed": solver_passed,
            "logs_only_passed": logs_only_passed,
            "gates_passed": gates_passed,
            "strongest_investigator": strongest_inv,
            "frontier_proxy_min_regret": proxy_min_regret,
            "frontier_proxy_min_regret_gain": proxy_min_gain_ci["mean"] if proxy_min_gain_ci else None,
            "frontier_proxy_min_regret_gain_ci95": proxy_min_gain_ci,
            "proxy_regret_gain_gem_minus_cdx": proxy_asym_ci["mean"] if proxy_asym_ci else None,
            "panel_min_regret": panel_min_regret,
            "panel_min_regret_gain": panel_min_gain_ci["mean"] if panel_min_gain_ci else None,
            "panel_min_regret_gain_ci95": panel_min_gain_ci,
            "panel_mean_regret": panel_mean_regret,
            "panel_mean_regret_gain": panel_mean_gain_ci["mean"] if panel_mean_gain_ci else None,
            "specialist_transfer": specialist_transfer,
            "per_investigator": per_inv_summary,
        }

    all_gates_passed = all(r["gates_passed"] for r in out_strategies.values())
    return {
        "tiers_version": "v1.4",
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "workers": int(workers),
        "investigators": list(inv_list),
        "non_trivial_investigators": non_trivial,
        "min_solver_acc": float(min_solver_acc),
        "max_logs_acc": float(max_logs_acc),
        "min_solver_ratio": float(min_solver_ratio),
        "baseline_solver_score": base_sol_mean,
        "baseline_solver_acc": base_sol_acc,
        "baseline_frontier_proxy_min_regret": base_proxy_min_regret,
        "baseline_panel_min_regret": base_panel_min_regret,
        "baseline_panel_mean_regret": base_panel_mean_regret,
        "all_gates_passed": all_gates_passed,
        "strategies": out_strategies,
    }


def build_specialist_vs_generalist_synthesis(
    catalog: dict[str, CatalogStrategyEntry],
    counterfactual: dict[str, Any] | None,
    fresh_matrix: dict[str, Any] | None,
) -> dict[str, Any]:
    unique_non_default = [
        e for e in catalog.values() if e.role != "baseline" and e.alias_of is None
    ]
    specialists = [e for e in unique_non_default if e.role == "specialist"]
    generalists = [e for e in unique_non_default if e.role == "generalist"]
    gem_specs = [e for e in specialists if e.target_family == "gemini_4_carbon"]
    cdx_specs = [e for e in specialists if e.target_family == "codex_gpt55"]
    tx_gens = [e for e in generalists if e.source == "transcript_strategies"]
    hof_gens = [e for e in generalists if e.source == "hall_of_fame_v1.4"]

    def _summarize_group(entries: Sequence[CatalogStrategyEntry]) -> dict[str, Any]:
        keys = [e.key for e in entries]
        out: dict[str, Any] = {"n_unique_strategies": len(keys), "strategies": keys}
        if counterfactual is not None:
            cf_strats = counterfactual["strategies"]
            gem_drops = [
                cf_strats[k]["gemini_hard_ev_drop"]
                for k in keys
                if k in cf_strats and cf_strats[k]["gemini_hard_ev_drop"] is not None
            ]
            cdx_drops = [
                cf_strats[k]["codex_all_ev_drop"]
                for k in keys
                if k in cf_strats and cf_strats[k]["codex_all_ev_drop"] is not None
            ]
            worst_drops = [
                cf_strats[k]["worst_family_ev_drop"]
                for k in keys
                if k in cf_strats and cf_strats[k]["worst_family_ev_drop"] is not None
            ]
            out["cf_gemini_hard_ev_drop_mean"] = _mean(gem_drops) if gem_drops else None
            out["cf_codex_all_ev_drop_mean"] = _mean(cdx_drops) if cdx_drops else None
            out["cf_worst_family_ev_drop_mean"] = _mean(worst_drops) if worst_drops else None

        if fresh_matrix is not None:
            fm_strats = fresh_matrix["strategies"]
            f_keys = [k for k in keys if k in fm_strats]
            if f_keys:
                out["fresh_solver_acc_mean"] = _mean([fm_strats[k]["solver_acc"] for k in f_keys])
                out["fresh_solver_score_mean"] = _mean([fm_strats[k]["solver_score"] for k in f_keys])
                p_mins = [
                    fm_strats[k]["frontier_proxy_min_regret"]
                    for k in f_keys
                    if fm_strats[k]["frontier_proxy_min_regret"] is not None
                ]
                p_gains = [
                    fm_strats[k]["frontier_proxy_min_regret_gain"]
                    for k in f_keys
                    if fm_strats[k]["frontier_proxy_min_regret_gain"] is not None
                ]
                pan_mins = [
                    fm_strats[k]["panel_min_regret"]
                    for k in f_keys
                    if fm_strats[k]["panel_min_regret"] is not None
                ]
                pan_means = [
                    fm_strats[k]["panel_mean_regret"]
                    for k in f_keys
                    if fm_strats[k]["panel_mean_regret"] is not None
                ]
                gem_rgains = [
                    fm_strats[k]["per_investigator"]["gemini_carbon_proxy"]["regret_gain_vs_default"]
                    for k in f_keys
                    if "gemini_carbon_proxy" in fm_strats[k]["per_investigator"]
                ]
                cdx_rgains = [
                    fm_strats[k]["per_investigator"]["codex_horizon_proxy"]["regret_gain_vs_default"]
                    for k in f_keys
                    if "codex_horizon_proxy" in fm_strats[k]["per_investigator"]
                ]
                out["fresh_frontier_proxy_min_regret_mean"] = _mean(p_mins) if p_mins else None
                out["fresh_frontier_proxy_min_regret_gain_mean"] = _mean(p_gains) if p_gains else None
                out["fresh_panel_min_regret_mean"] = _mean(pan_mins) if pan_mins else None
                out["fresh_panel_mean_regret_mean"] = _mean(pan_means) if pan_means else None
                out["fresh_gemini_proxy_regret_gain_mean"] = _mean(gem_rgains) if gem_rgains else None
                out["fresh_codex_proxy_regret_gain_mean"] = _mean(cdx_rgains) if cdx_rgains else None

                spec_items = [
                    fm_strats[k]["specialist_transfer"]
                    for k in f_keys
                    if fm_strats[k]["specialist_transfer"] is not None
                ]
                if spec_items:
                    out["in_domain_regret_gain_mean"] = _mean([x["in_domain_regret_gain"] for x in spec_items])
                    out["out_of_domain_regret_gain_mean"] = _mean([x["out_of_domain_regret_gain"] for x in spec_items])
                    ratios = [x["proxy_transfer_ratio"] for x in spec_items if x["proxy_transfer_ratio"] is not None]
                    out["proxy_transfer_ratio_mean"] = _mean(ratios) if ratios else None
        return out

    rankings: dict[str, list[str]] = {}
    if counterfactual is not None:
        cf_s = counterfactual["strategies"]
        rankings["by_cf_worst_family_ev_drop"] = [
            e.key
            for e in sorted(
                (ent for ent in unique_non_default if ent.key in cf_s),
                key=lambda ent: float(cf_s[ent.key]["worst_family_ev_drop"] or -999.0),
                reverse=True,
            )
        ]
    if fresh_matrix is not None:
        fm_s = fresh_matrix["strategies"]
        rankings["by_fresh_panel_min_regret"] = [
            e.key
            for e in sorted(
                (ent for ent in unique_non_default if ent.key in fm_s),
                key=lambda ent: float(fm_s[ent.key]["panel_min_regret"] or -999.0),
                reverse=True,
            )
        ]
        rankings["by_fresh_frontier_proxy_min_regret"] = [
            e.key
            for e in sorted(
                (ent for ent in unique_non_default if ent.key in fm_s),
                key=lambda ent: float(fm_s[ent.key]["frontier_proxy_min_regret"] or -999.0),
                reverse=True,
            )
        ]

    return {
        "n_catalog_entries": len(catalog),
        "n_unique_behaviors": len({e.behavior_hash for e in catalog.values()}),
        "behavioral_aliases": {
            e.key: e.alias_of for e in catalog.values() if e.alias_of is not None
        },
        "groups": {
            "all_specialists": _summarize_group(specialists),
            "all_generalists": _summarize_group(generalists),
            "specialist_gemini": _summarize_group(gem_specs),
            "specialist_codex": _summarize_group(cdx_specs),
            "generalist_transcript": _summarize_group(tx_gens),
            "generalist_hof": _summarize_group(hof_gens),
        },
        "rankings_unique_non_default": rankings,
    }


def evaluate_cross_model_transfer(
    committed_root: str | Path = DEFAULT_COMMITTED_ROOT,
    hof_path: str | Path = DEFAULT_HOF_V14_PATH,
    fresh_seeds: str | int | Iterable[int] = DEFAULT_FRESH_SEEDS,
    tier: str = "hard",
    selected_strategies: Sequence[str] | None = None,
    cohort_ids: Sequence[str] | None = None,
    cf_seeds: Iterable[int] | None = None,
    workers: int = DEFAULT_WORKERS,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    run_counterfactual: bool = True,
    run_fresh: bool = True,
) -> dict[str, Any]:
    if int(workers) < 1:
        raise ValueError(f"workers must be >= 1, got {workers}")
    catalog = load_transfer_catalog(hof_path=hof_path, tier=tier, selected_names=selected_strategies)

    cf_res = (
        evaluate_cross_family_counterfactual(
            catalog=catalog,
            committed_root=committed_root,
            cohort_ids=cohort_ids,
            seeds=cf_seeds,
            workers=int(workers),
            n_boot=n_boot,
        )
        if run_counterfactual
        else None
    )
    fresh_res = (
        evaluate_fresh_seed_transfer(
            catalog=catalog,
            seeds=fresh_seeds,
            tier=tier,
            workers=int(workers),
            n_boot=n_boot,
            min_solver_acc=min_solver_acc,
            max_logs_acc=max_logs_acc,
            min_solver_ratio=min_solver_ratio,
        )
        if run_fresh
        else None
    )

    catalog_meta = {
        key: {
            "key": ent.key,
            "source": ent.source,
            "role": ent.role,
            "target_family": ent.target_family,
            "hof_rank": ent.hof_rank,
            "hof_survivor_name": ent.hof_survivor_name,
            "alias_of": ent.alias_of,
            "behavior_hash": ent.behavior_hash,
            "n_rules": ent.n_rules,
            "strategy_json": ent.strategy_json,
        }
        for key, ent in catalog.items()
    }

    synthesis = build_specialist_vs_generalist_synthesis(catalog, cf_res, fresh_res)

    return _round_floats(
        {
            "schema_version": "1.0",
            "api_calls": 0,
            "workers": int(workers),
            "n_bootstrap_samples": int(n_boot),
            "catalog": catalog_meta,
            "counterfactual": cf_res,
            "fresh_seed_transfer": fresh_res,
            "synthesis": synthesis,
        },
        nd=4,
    )


def _fmt_f(val: float | None, nd: int = 3, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:+.{nd}f}" if signed else f"{val:.{nd}f}"


def _fmt_ci(ci_obj: dict[str, float] | None, nd: int = 3, signed: bool = True) -> str:
    if not ci_obj:
        return "n/a"
    m = _fmt_f(ci_obj["mean"], nd=nd, signed=signed)
    lo = _fmt_f(ci_obj["ci95_lo"], nd=nd, signed=signed)
    hi = _fmt_f(ci_obj["ci95_hi"], nd=nd, signed=signed)
    return f"{m} [{lo}, {hi}]"


def render_transfer_report(payload: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = h1 * 2
    h3 = h1 * 3
    cat = payload["catalog"]
    cf = payload.get("counterfactual")
    fm = payload.get("fresh_seed_transfer")
    syn = payload["synthesis"]

    lines: list[str] = [
        f"{h1} Cross-Model Mole Strategy Transfer Evaluation (Gemini-4-Carbon vs Codex/GPT-5.5)",
        "",
        "Generated strictly offline (`api_calls=0`) via "
        "`python -m canary.mole.transfer_eval "
        "--out results/mole_strategies/cross_model_transfer.json "
        "--report-out docs/reports/mole_cross_model_transfer.md`.",
        "",
        f"{h2} 1. Executive Summary and Verification Gates",
        "",
        f"- **Catalog evaluated**: {syn['n_catalog_entries']} strategy entries "
        f"(1 `DEFAULT_STRATEGY` baseline + 6 transcript-grounded strategies from `canary/mole/strategies.py` + "
        f"4 entries from `data/forge/hall_of_fame_v1.4.jsonl`), spanning **{syn['n_unique_behaviors']}** distinct "
        f"behavioral policies (`hof_v14_r3` is an exact behavioral alias of `surgical_trap_shield`; "
        f"`hof_v14_r4` is an exact behavioral alias of `early_burst_midgame_pace`).",
    ]

    if cf is not None:
        n_gem = cf["strategies"]["default"]["rollups"].get("gemini_4_carbon_hard", {}).get("n", 0)
        n_cdx = cf["strategies"]["default"]["rollups"].get("codex_gpt55_all", {}).get("n", 0)
        lines.append(
            f"- **Read-only counterfactual transcript replay (`n={cf['total_episodes']}`)**: "
            f"`{cf['transcript_verified_total']}/{cf['total_episodes']}` raw frontier transcripts "
            f"(`{n_gem}` v1.4 Gemini-4-carbon Hard across OpenCode MCP + In-Proc; "
            f"`{n_cdx}` v1.3 Codex/GPT-5.5 across Hard `n=19` and Medium `n=20`) reconstructed cleanly into "
            f"public-tool schedules and matched `100%` of committed `audit_episode` posteriors under `DEFAULT_STRATEGY`."
        )

    if fm is not None:
        s_lo, s_hi = fm["seeds"][0], fm["seeds"][-1]
        min_sa = min(r["solver_acc"] for r in fm["strategies"].values())
        max_la = max(r["logs_only_acc"] for r in fm["strategies"].values())
        lines.append(
            f"- **Fresh-seed v1.4 Hard transfer matrix (`seeds {s_lo}-{s_hi}`, `n={fm['n_seeds']}`, `--workers {fm['workers']}`)**: "
            f"All `{len(fm['strategies'])}/{len(fm['strategies'])}` strategy entries pass catchability and fairness gates "
            f"(`all_gates_passed={fm['all_gates_passed']}`, minimum `solver_acc={min_sa:.3f} >= {fm['min_solver_acc']:.2f}`, "
            f"maximum `logs_only_acc={max_la:.3f} <= {fm['max_logs_acc']:.2f}`, seed hygiene blocking `0-59`, `30000-30199`, `800000+`)."
        )

    grp = syn["groups"]
    sp_grp = grp["all_specialists"]
    gn_grp = grp["all_generalists"]
    if sp_grp.get("fresh_panel_min_regret_mean") is not None and gn_grp.get("fresh_panel_min_regret_mean") is not None:
        lines.append(
            f"- **Specialist vs Generalist transfer**: Unique specialists (`n={sp_grp['n_unique_strategies']}`) achieve "
            f"mean in-domain proxy regret gain `{_fmt_f(sp_grp.get('in_domain_regret_gain_mean'), signed=True)}` vs "
            f"out-of-domain `{_fmt_f(sp_grp.get('out_of_domain_regret_gain_mean'), signed=True)}` "
            f"(mean 5-investigator minimax regret `{_fmt_f(sp_grp.get('fresh_panel_min_regret_mean'))}`), whereas "
            f"unique generalists (`n={gn_grp['n_unique_strategies']}`) achieve mean 5-investigator minimax regret "
            f"`{_fmt_f(gn_grp.get('fresh_panel_min_regret_mean'))}` and mean worst-family counterfactual EV drop "
            f"`{_fmt_f(gn_grp.get('cf_worst_family_ev_drop_mean'), signed=True)}` vs specialists "
            f"`{_fmt_f(sp_grp.get('cf_worst_family_ev_drop_mean'), signed=True)}`."
        )

    lines += [
        "",
        f"{h2} 2. Strategy Catalog and Behavioral Deduplication",
        "",
        "| Strategy Key | Source | Role | Target Family | Rules | Behavior Hash (v1.4 Hard) | HOF Survivor / Alias |",
        "|---|---|---|---|---|---|---|",
    ]
    for key, meta in cat.items():
        note_parts: list[str] = []
        if meta["hof_survivor_name"]:
            note_parts.append(f"survivor={meta['hof_survivor_name']}")
        if meta["alias_of"]:
            note_parts.append(f"alias_of={meta['alias_of']}")
        note = ", ".join(note_parts) if note_parts else "canonical"
        lines.append(
            f"| `{key}` | `{meta['source']}` | `{meta['role']}` | `{meta['target_family']}` | "
            f"{meta['n_rules']} | `{meta['behavior_hash'][:12]}` | {note} |"
        )

    if cf is not None:
        lines += [
            "",
            f"{h2} 3. Part (a): Read-Only Counterfactual Replay Across Model Families",
            "",
            f"{h3} 3.1 Reconstructed Frontier Transcript Cohorts",
            "",
            "| Cohort ID | Ruleset | Tier | Family | Harness | Episodes | Seeds | Raw Transcript Verified | Baseline Audit Parity |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for cid, cm in cf["cohorts"].items():
            s_str = f"{cm['seeds'][0]}..{cm['seeds'][-1]}" if cm["seeds"] else "none"
            lines.append(
                f"| `{cid}` | `{cm['version']}` | `{cm['tier']}` | `{cm['family']}` | `{cm['harness']}` | "
                f"{cm['n_episodes']} | `{s_str}` | {cm['transcript_verified_count']}/{cm['n_episodes']} | "
                f"{cm['baseline_audit_match_count']}/{cm['n_episodes']} |"
            )

        lines += [
            "",
            f"{h3} 3.2 Cross-Family Counterfactual Optimal-EV Drop vs `DEFAULT_STRATEGY` (Paired Bootstrap 95% CI)",
            "",
            "| Strategy | Role (Target) | v1.4 Gemini Hard EV Drop (n=60) | v1.3 Codex/GPT-5.5 Hard EV Drop (n=19) | v1.3 Codex/GPT-5.5 Med EV Drop (n=20) | v1.3 Codex/GPT-5.5 All EV Drop (n=39) | Worst-Family EV Drop |",
            "|---|---|---|---|---|---|---|",
        ]
        for key, row in cf["strategies"].items():
            meta = cat[key]
            rl = row["rollups"]
            gem_ci = rl.get("gemini_4_carbon_hard", {}).get("optimal_ev_drop_ci95")
            ch_ci = rl.get("codex_gpt55_hard", {}).get("optimal_ev_drop_ci95")
            cm_ci = rl.get("codex_gpt55_medium", {}).get("optimal_ev_drop_ci95")
            ca_ci = rl.get("codex_gpt55_all", {}).get("optimal_ev_drop_ci95")
            lines.append(
                f"| `{key}` | `{meta['role']}` (`{meta['target_family']}`) | "
                f"{_fmt_ci(gem_ci)} | {_fmt_ci(ch_ci)} | {_fmt_ci(cm_ci)} | {_fmt_ci(ca_ci)} | "
                f"{_fmt_f(row['worst_family_ev_drop'], signed=True)} |"
            )

        lines += [
            "",
            f"{h3} 3.3 Counterfactual Posterior `P(true mole)` Drop and Surfaced Canary Delta",
            "",
            "| Strategy | Gemini Hard `P(mole)` Drop (n=60) | Gemini Surfaced Canaries (Delta) | Codex/GPT-5.5 All `P(mole)` Drop (n=39) | Codex/GPT-5.5 Surfaced Canaries (Delta) | All-Frontier EV Drop (n=99) |",
            "|---|---|---|---|---|---|",
        ]
        for key, row in cf["strategies"].items():
            rl = row["rollups"]
            g = rl.get("gemini_4_carbon_hard", {})
            c = rl.get("codex_gpt55_all", {})
            a = rl.get("all_frontier", {})
            lines.append(
                f"| `{key}` | {_fmt_ci(g.get('p_true_mole_drop_ci95'))} | "
                f"{_fmt_f(g.get('surfaced_canaries'), 2)} ({_fmt_f(g.get('surfaced_canaries_delta'), 2, signed=True)}) | "
                f"{_fmt_ci(c.get('p_true_mole_drop_ci95'))} | "
                f"{_fmt_f(c.get('surfaced_canaries'), 2)} ({_fmt_f(c.get('surfaced_canaries_delta'), 2, signed=True)}) | "
                f"{_fmt_ci(a.get('optimal_ev_drop_ci95'))} |"
            )

    if fm is not None:
        s_lo, s_hi = fm["seeds"][0], fm["seeds"][-1]
        lines += [
            "",
            f"{h2} 4. Part (b): Fresh-Seed Offline Transfer Matrix (v1.4 Hard Seeds {s_lo}-{s_hi}, n={fm['n_seeds']})",
            "",
            f"{h3} 4.1 Catchability Gates and Investigator Score / Accuracy Matrix",
            "",
            "| Strategy | Solver Score (Acc) | GeminiProxy Score (Acc) | CodexProxy Score (Acc) | GrokTactics Score (Acc) | HintedHeur Score (Acc) | Heuristic Score (Acc) | LogsOnly Score (Acc) | Gates |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for key, row in fm["strategies"].items():
            pi = row["per_investigator"]

            def _cell(inv: str) -> str:
                d = pi[inv]
                return f"{d['score']:+.3f} ({100.0 * d['acc']:.1f}%)"

            gate_str = "PASS" if row["gates_passed"] else "FAIL"
            lines.append(
                f"| `{key}` | {_cell('solver')} | {_cell('gemini_carbon_proxy')} | "
                f"{_cell('codex_horizon_proxy')} | {_cell('grok_tactics')} | "
                f"{_cell('hinted_heuristic')} | {_cell('heuristic')} | {_cell('logs_only')} | **{gate_str}** |"
            )

        lines += [
            "",
            f"{h3} 4.2 Paired Regret Gain vs `DEFAULT_STRATEGY` (Paired Bootstrap 95% CI, B={payload['n_bootstrap_samples']})",
            "",
            "| Strategy | GeminiProxy Regret Gain | CodexProxy Regret Gain | Proxy Min-Regret Gain | Panel Min-Regret (Strongest) | Panel Min-Regret Gain |",
            "|---|---|---|---|---|---|",
        ]
        for key, row in fm["strategies"].items():
            pi = row["per_investigator"]
            gem_rg = pi["gemini_carbon_proxy"]["regret_gain_ci95"]
            cdx_rg = pi["codex_horizon_proxy"]["regret_gain_ci95"]
            pmin_rg = row["frontier_proxy_min_regret_gain_ci95"]
            pan_rg = row["panel_min_regret_gain_ci95"]
            lines.append(
                f"| `{key}` | {_fmt_ci(gem_rg)} | {_fmt_ci(cdx_rg)} | {_fmt_ci(pmin_rg)} | "
                f"{_fmt_f(row['panel_min_regret'])} (`{row['strongest_investigator']}`) | {_fmt_ci(pan_rg)} |"
            )

    lines += [
        "",
        f"{h2} 5. Specialist vs Generalist Cross-Model Transfer Analysis",
        "",
        f"{h3} 5.1 Specialist In-Domain vs Out-of-Domain Transfer",
        "",
        "| Specialist Strategy | Target Family | In-Domain Proxy Regret Gain | Out-of-Domain Proxy Regret Gain | In-Minus-Out Gap (95% CI) | Proxy Transfer Ratio | In-Domain CF EV Drop | Out-of-Domain CF EV Drop |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key, meta in cat.items():
        if meta["role"] != "specialist" or meta["alias_of"] is not None:
            continue
        st_fm = fm["strategies"][key]["specialist_transfer"] if fm is not None else None
        st_cf = cf["strategies"][key] if cf is not None else None
        lines.append(
            f"| `{key}` | `{meta['target_family']}` | "
            f"{_fmt_ci(st_fm['in_domain_regret_gain_ci95']) if st_fm else 'n/a'} | "
            f"{_fmt_ci(st_fm['out_of_domain_regret_gain_ci95']) if st_fm else 'n/a'} | "
            f"{_fmt_ci(st_fm['in_minus_out_regret_gain_ci95']) if st_fm else 'n/a'} | "
            f"{_fmt_f(st_fm['proxy_transfer_ratio'], 2) if st_fm else 'n/a'} | "
            f"{_fmt_f(st_cf['in_domain_cf_ev_drop'], signed=True) if st_cf else 'n/a'} | "
            f"{_fmt_f(st_cf['out_of_domain_cf_ev_drop'], signed=True) if st_cf else 'n/a'} |"
        )

    lines += [
        "",
        f"{h3} 5.2 Cohort-Group Synthesis (Unique Non-Default Strategies)",
        "",
        "| Strategy Group | Count | Mean Solver Acc | Mean GeminiProxy Regret Gain | Mean CodexProxy Regret Gain | Mean Proxy Min-Regret | Mean 5-Inv Min-Regret | Mean CF Worst-Family EV Drop |",
        "|---|---|---|---|---|---|---|---|",
    ]
    group_labels = (
        ("specialist_gemini", "Gemini Specialists (`gemini_4_carbon`)"),
        ("specialist_codex", "Codex Specialists (`codex_gpt55`)"),
        ("all_specialists", "All Unique Specialists"),
        ("generalist_transcript", "Transcript Generalists (`frontier_all`)"),
        ("generalist_hof", "HOF v1.4 Minimax Generalists"),
        ("all_generalists", "All Unique Generalists"),
    )
    for gkey, glabel in group_labels:
        gd = syn["groups"][gkey]
        lines.append(
            f"| {glabel} | {gd['n_unique_strategies']} | "
            f"{_fmt_f(gd.get('fresh_solver_acc_mean'))} | "
            f"{_fmt_f(gd.get('fresh_gemini_proxy_regret_gain_mean'), signed=True)} | "
            f"{_fmt_f(gd.get('fresh_codex_proxy_regret_gain_mean'), signed=True)} | "
            f"{_fmt_f(gd.get('fresh_frontier_proxy_min_regret_mean'))} | "
            f"{_fmt_f(gd.get('fresh_panel_min_regret_mean'))} | "
            f"{_fmt_f(gd.get('cf_worst_family_ev_drop_mean'), signed=True)} |"
        )

    rk = syn["rankings_unique_non_default"]
    lines += [
        "",
        f"{h3} 5.3 Cross-Evaluation Rankings (Unique Non-Default Policies)",
        "",
    ]
    if "by_cf_worst_family_ev_drop" in rk:
        lines.append(
            "- **By worst-family counterfactual EV drop (Gemini Hard & Codex/GPT-5.5 All)**: "
            + " > ".join(f"`{k}`" for k in rk["by_cf_worst_family_ev_drop"])
        )
    if "by_fresh_frontier_proxy_min_regret" in rk:
        lines.append(
            "- **By fresh-seed worst frontier-proxy regret (`min(GeminiProxy, CodexProxy)`)**: "
            + " > ".join(f"`{k}`" for k in rk["by_fresh_frontier_proxy_min_regret"])
        )
    if "by_fresh_panel_min_regret" in rk:
        lines.append(
            "- **By fresh-seed 5-investigator minimax regret**: "
            + " > ".join(f"`{k}`" for k in rk["by_fresh_panel_min_regret"])
        )

    return "\n".join(lines) + "\n"


def format_compact_json(obj: Any, depth: int = 0) -> str:
    if isinstance(obj, dict):
        if not obj or depth >= 3 or all(not isinstance(v, (dict, list)) for v in obj.values()):
            return json.dumps(obj, separators=(",", ":"))
        pad = " " * (depth + 1)
        items = [f"{pad}{json.dumps(k)}:{format_compact_json(v, depth + 1)}" for k, v in obj.items()]
        return "{\n" + ",\n".join(items) + "\n" + (" " * depth) + "}"
    if isinstance(obj, list):
        if not obj or depth >= 3 or all(not isinstance(v, (dict, list)) for v in obj):
            return json.dumps(obj, separators=(",", ":"))
        pad = " " * (depth + 1)
        items = [f"{pad}{format_compact_json(v, depth + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + (" " * depth) + "]"
    return json.dumps(obj)


def _find_forbidden_secret_key(obj: Any) -> str | None:
    forbidden = ("true_mole", "mole_id", "secret_mole")
    if isinstance(obj, dict):
        for k, v in obj.items():
            ks = str(k)
            if ks in forbidden:
                return ks
            hit = _find_forbidden_secret_key(v)
            if hit is not None:
                return hit
    elif isinstance(obj, list):
        for item in obj:
            hit = _find_forbidden_secret_key(item)
            if hit is not None:
                return hit
    return None


def check_transfer_artifacts(
    json_path: str | Path = DEFAULT_JSON_OUT,
    md_path: str | Path = DEFAULT_REPORT_OUT,
    max_json_bytes: int = 150 * 1024,
) -> tuple[bool, str]:
    jp = Path(json_path)
    mp = Path(md_path)
    if not jp.is_file():
        return False, f"FAIL: missing JSON artifact: {jp}"
    if not mp.is_file():
        return False, f"FAIL: missing Markdown report: {mp}"

    json_text = jp.read_text(encoding="utf-8")
    md_text = mp.read_text(encoding="utf-8")
    byte_len = len(json_text.encode("utf-8"))
    if byte_len >= int(max_json_bytes):
        return False, f"FAIL: JSON size {byte_len} bytes exceeds {max_json_bytes} limit"

    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    coauthor_tag = "co-authored-" + "by"

    for p, txt in ((jp, json_text), (mp, md_text)):
        if em_dash in txt or en_dash in txt:
            return False, f"FAIL: forbidden em/en dash found in {p}"
        low = txt.lower()
        if flash_tag in low or solver_pct_tag in low:
            return False, f"FAIL: forbidden {flash_tag} or {solver_pct_tag} claim in {p}"
        if coauthor_tag in low:
            return False, f"FAIL: forbidden {coauthor_tag} line in {p}"

    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return False, f"FAIL: invalid JSON in {jp}: {exc}"
    if not isinstance(payload, dict):
        return False, f"FAIL: expected JSON object in {jp}"
    if payload.get("schema_version") != "1.0":
        return False, f"FAIL: unexpected schema_version {payload.get('schema_version')!r}"
    if payload.get("api_calls") != 0:
        return False, f"FAIL: expected api_calls == 0, got {payload.get('api_calls')!r}"

    bad_key = _find_forbidden_secret_key(payload)
    if bad_key is not None:
        return False, f"FAIL: forbidden secret key {bad_key!r} leaked in {jp}"

    n_cf = 0
    cf = payload.get("counterfactual")
    if cf is not None:
        n_cf = int(cf.get("total_episodes", 0))
        if n_cf <= 0:
            return False, "FAIL: counterfactual.total_episodes must be positive"
        if int(cf.get("transcript_verified_total", -1)) != n_cf:
            return False, "FAIL: counterfactual transcript verification mismatch"
        if int(cf.get("baseline_audit_match_total", -1)) != n_cf:
            return False, "FAIL: counterfactual baseline audit parity mismatch"

    n_fresh = 0
    n_strats = len(payload.get("catalog", {}))
    fm = payload.get("fresh_seed_transfer")
    if fm is not None:
        try:
            seeds = validate_transfer_seeds(fm.get("seeds", []))
        except ValueError as exc:
            return False, f"FAIL: seed hygiene violation: {exc}"
        n_fresh = len(seeds)
        if n_fresh != int(fm.get("n_seeds", -1)):
            return False, f"FAIL: n_seeds mismatch ({n_fresh} != {fm.get('n_seeds')})"
        if fm.get("all_gates_passed") is not True:
            return False, "FAIL: fresh_seed_transfer.all_gates_passed is not True"
        min_sa = float(fm.get("min_solver_acc", DEFAULT_MIN_SOLVER_ACC))
        max_la = float(fm.get("max_logs_acc", DEFAULT_MAX_LOGS_ACC))
        for skey, row in (fm.get("strategies") or {}).items():
            if row.get("gates_passed") is not True:
                return False, f"FAIL: strategy {skey!r} failed catchability gates"
            if float(row.get("solver_acc", 0.0)) < min_sa:
                return False, f"FAIL: strategy {skey!r} solver_acc below {min_sa}"
            if float(row.get("logs_only_acc", 1.0)) > max_la:
                return False, f"FAIL: strategy {skey!r} logs_only_acc above {max_la}"

    if format_compact_json(payload) + "\n" != json_text:
        return False, f"FAIL: non-canonical compact JSON formatting in {jp}"

    expected_md = render_transfer_report(payload)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {mp} does not match JSON ledger {jp}"

    return (
        True,
        f"OK: {jp.name} ({byte_len} bytes, cf={n_cf} eps, fresh={n_fresh} seeds, "
        f"{n_strats}/{n_strats} strategies verified) matches {mp.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.transfer_eval")
    ap.add_argument("--committed-root", type=Path, default=DEFAULT_COMMITTED_ROOT)
    ap.add_argument("--hof-path", type=Path, default=DEFAULT_HOF_V14_PATH)
    ap.add_argument("--fresh-seeds", default="6200-6229")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--strategies", default=None)
    ap.add_argument("--cohorts", default=None)
    ap.add_argument("--cf-seeds", default=None)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--n-boot", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--skip-counterfactual", action="store_true")
    ap.add_argument("--skip-fresh", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report-out", type=Path, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.check:
        j_path = args.out if args.out is not None else DEFAULT_JSON_OUT
        m_path = args.report_out if args.report_out is not None else DEFAULT_REPORT_OUT
        ok, msg = check_transfer_artifacts(json_path=j_path, md_path=m_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    selected_strats = (
        [s.strip() for s in args.strategies.split(",") if s.strip()]
        if args.strategies
        else None
    )
    selected_cohorts = (
        [c.strip() for c in args.cohorts.split(",") if c.strip()]
        if args.cohorts
        else None
    )
    cf_seed_list = parse_seed_spec(args.cf_seeds) if args.cf_seeds is not None else None

    payload = evaluate_cross_model_transfer(
        committed_root=args.committed_root,
        hof_path=args.hof_path,
        fresh_seeds=args.fresh_seeds,
        tier=args.tier,
        selected_strategies=selected_strats,
        cohort_ids=selected_cohorts,
        cf_seeds=cf_seed_list,
        workers=args.workers,
        n_boot=args.n_boot,
        min_solver_acc=args.min_solver_acc,
        max_logs_acc=args.max_logs_acc,
        min_solver_ratio=args.min_solver_ratio,
        run_counterfactual=not args.skip_counterfactual,
        run_fresh=not args.skip_fresh,
    )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(format_compact_json(payload) + "\n", encoding="utf-8")

    report_md = render_transfer_report(payload)
    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report_md, encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(report_md, end="")

    if payload["fresh_seed_transfer"] is not None and not payload["fresh_seed_transfer"]["all_gates_passed"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
