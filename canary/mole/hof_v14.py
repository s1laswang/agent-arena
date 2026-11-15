"""v1.4 Hall-of-Fame evolution, diversity selection, and track validation utilities."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
import random
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from canary import forge_track
from canary.env import Env
from canary.eval import make_policy_factory, parse_seeds, run_episode
from canary.forge.fitness import default_solver_factory, real_runner, solver_baseline
from canary.forge.frontier_proxies import frontier_proxy_investigators
from canary.forge.mutate import canonical, default_strategy_json, validate_strategy
from canary.mole.dsl import MoleStrategy
from canary.mole.evolve_v14 import (
    V14Mutator,
    _strategy_profile,
    behavior_hash,
    evaluate_v14,
    generation_seed_batch,
    is_valid_rule_conds,
    representative_views,
    v14_investigators,
    validate_seed_hygiene,
)
from canary.mole.fairness_audit import audit_strategy
from canary.mole.strategies import STRATEGY_SPECS
from canary.redteam import fuzz
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION

ROOT = Path(__file__).resolve().parent.parent.parent
HOF_V14_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.jsonl"
HOF_V14_META_PATH = ROOT / "data" / "forge" / "hall_of_fame_v1.4.meta.json"

HOF_KEYS: tuple[str, ...] = (
    "rank",
    "fitness",
    "solver_score",
    "solver_acc",
    "per_investigator",
    "strategy_json",
)

MIN_SOLVER_ACC = 0.85
MIN_SOLVER_RATIO = 0.50
MIN_VIEW_DISAGREEMENT = 0.15
DEFAULT_MAX_SURVIVORS = 5
DEFAULT_TRAIN_SEEDS = range(200, 600)
DEFAULT_HOLDOUT_SEEDS = range(6200, 6230)
DEFAULT_AUDIT_SEEDS = range(6000, 6010)
OUTCOME_EVENTS: tuple[str, ...] = ("leak", "framed")
OUTCOME_AGENTS: tuple[str, ...] = ("do_nothing", "solver")


def load_hof_v14(path: str | Path | None = None) -> tuple[list[dict[str, Any]], list[MoleStrategy]]:
    target = Path(path) if path is not None else HOF_V14_PATH
    return forge_track.load(target)


def load_hof_v14_meta(meta_path: str | Path | None = None) -> dict[str, Any]:
    target = Path(meta_path) if meta_path is not None else HOF_V14_META_PATH
    return json.loads(target.read_text(encoding="utf-8"))


def strategy_for_v14(
    seed: int,
    track: str = "hard_forge",
    path: str | Path | None = None,
) -> MoleStrategy:
    target = Path(path) if path is not None else HOF_V14_PATH
    return forge_track.strategy_for(track, seed, target)


def v14_hof_investigators(include_frontier_proxies: bool = True) -> dict[str, Callable]:
    inv = dict(v14_investigators())
    if include_frontier_proxies:
        inv.update(frontier_proxy_investigators(include_defaults=False))
    return inv


def empirical_archetypes(tier: str = "hard") -> list[tuple[str, dict[str, Any]]]:
    raw_specs: list[tuple[str, dict[str, Any]]] = [
        (name, spec.to_json()) for name, spec in STRATEGY_SPECS.items()
    ]
    extra_specs: list[tuple[str, dict[str, Any]]] = [
        (
            "wide_crowd_partition_evader",
            {
                "rules": [
                    {
                        "if": [["min_recipient_count", "<=", 4], ["max_recipient_count", ">=", 12]],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [["day", "<=", 4], ["n_docs_held", ">=", 3]],
                        "then": {"leak": "newest", "frame": "decoy"},
                    },
                ],
                "default": {"leak": "most_recipients", "frame": "random_peer"},
            },
        ),
        (
            "restricted_peer_cascade",
            {
                "rules": [
                    {
                        "if": [["i_am_restricted", "==", 1]],
                        "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
                    },
                    {
                        "if": [["n_restricted_colleagues", ">=", 2]],
                        "then": {"leak": "oldest", "frame": "most_restricted_peer"},
                    },
                    {
                        "if": [["recent_low_recipient_docs", ">=", 1], ["day", "<=", 10]],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            },
        ),
        (
            "decoy_pivot_non_decoy_frame",
            {
                "rules": [
                    {
                        "if": [["day", "<=", 2]],
                        "then": {"leak": "newest", "frame": "decoy"},
                    },
                    {
                        "if": [["days_since_last_leak", ">=", 3], ["n_leakable", ">=", 2]],
                        "then": {"leak": "most_recipients", "frame": "random_peer"},
                    },
                    {
                        "if": [
                            ["day", ">=", 6],
                            ["day", "<=", 11],
                            ["days_since_last_leak", "==", 1],
                            ["recent_low_recipient_docs", ">=", 1],
                        ],
                        "then": {"leak": "none", "frame": "random_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
        (
            "late_horizon_stall_hybrid",
            {
                "rules": [
                    {
                        "if": [["day", "<=", 3]],
                        "then": {"leak": "random_seeded", "frame": "random_peer"},
                    },
                    {
                        "if": [
                            ["day", ">=", 13],
                            ["recent_low_recipient_docs", ">=", 1],
                            ["days_since_last_leak", "<=", 2],
                        ],
                        "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
                    },
                    {
                        "if": [["n_docs_held", ">=", 6], ["newest_doc_age_days", "==", 0]],
                        "then": {"leak": "oldest", "frame": "random_peer"},
                    },
                ],
                "default": {"leak": "random_seeded", "frame": "random_peer"},
            },
        ),
    ]
    raw_specs.extend(extra_specs)
    validated: list[tuple[str, dict[str, Any]]] = []
    for label, spec in raw_specs:
        clean_spec = {k: v for k, v in spec.items() if k in ("rules", "default", "name")}
        norm = validate_strategy(clean_spec)
        for rule in norm.get("rules", []):
            if not is_valid_rule_conds(rule["if"], tier):
                raise ValueError(f"invalid rule condition in archetype {label}: {rule['if']}")
        validated.append((label, norm))
    return validated


def decision_vector(
    strategy_obj: dict[str, Any] | MoleStrategy,
    tier: str = "hard",
) -> tuple[tuple[str | None, str | None], ...]:
    strat = strategy_obj if isinstance(strategy_obj, MoleStrategy) else MoleStrategy.from_json(strategy_obj)
    views = representative_views(tier)
    out: list[tuple[str | None, str | None]] = []
    for idx, view in enumerate(views):
        dec = strat.decide(view, random.Random(f"v14-bhash:{tier}:{idx}"))
        out.append((dec.get("leak"), dec.get("frame")))
    return tuple(out)


def pairwise_view_disagreement(
    strat_a: dict[str, Any] | MoleStrategy,
    strat_b: dict[str, Any] | MoleStrategy,
    tier: str = "hard",
) -> float:
    va = decision_vector(strat_a, tier)
    vb = decision_vector(strat_b, tier)
    diffs = sum(1 for a, b in zip(va, vb) if a != b)
    return diffs / max(1, len(va))


def _extract_strategy_json(entry: dict[str, Any] | MoleStrategy) -> dict[str, Any]:
    if isinstance(entry, MoleStrategy):
        raw = entry.to_json()
    elif "strategy_json" in entry:
        raw = entry["strategy_json"]
    elif "strategy" in entry and isinstance(entry["strategy"], dict):
        raw = entry["strategy"]
    else:
        raw = entry
    clean = {k: v for k, v in raw.items() if k in ("rules", "default", "name")}
    return validate_strategy(clean)


def behavioral_diversity_report(
    entries: Sequence[dict[str, Any] | MoleStrategy],
    tier: str = "hard",
    outcome_hashes_by_rank: dict[int, str] | None = None,
) -> dict[str, Any]:
    n = len(entries)
    if n == 0:
        return {
            "n_strategies": 0,
            "unique_behavior_hashes": 0,
            "unique_outcome_hashes": 0,
            "all_behavior_hashes_unique": False,
            "all_outcome_hashes_unique": False,
            "min_pairwise_view_disagreement": 0.0,
            "mean_pairwise_view_disagreement": 0.0,
            "leak_rate_span": 0.0,
            "frame_rate_span": 0.0,
            "high_rc_share_span": 0.0,
            "distinct_leak_selectors": [],
            "distinct_frame_selectors": [],
        }

    sjs = [_extract_strategy_json(e) for e in entries]
    profiles = [_strategy_profile(sj, tier) for sj in sjs]
    bhashes = [p["behavior_hash"] for p in profiles]

    ohashes: list[str] = []
    for idx, e in enumerate(entries):
        rank_key = idx + 1
        if outcome_hashes_by_rank and rank_key in outcome_hashes_by_rank:
            ohashes.append(outcome_hashes_by_rank[rank_key])
        elif isinstance(e, dict) and isinstance(e.get("outcome_hash"), str):
            ohashes.append(e["outcome_hash"])

    disagreements: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            disagreements.append(pairwise_view_disagreement(sjs[i], sjs[j], tier))

    leak_sels: set[str] = set()
    frame_sels: set[str] = set()
    for sj in sjs:
        branches = [r["then"] for r in sj.get("rules", [])] + [sj["default"]]
        for br in branches:
            lk = br.get("leak") or "none"
            fr = br.get("frame") or "none"
            leak_sels.add(lk)
            frame_sels.add(fr)

    leak_rates = [float(p["leak_rate"]) for p in profiles]
    frame_rates = [float(p["frame_rate"]) for p in profiles]
    high_rc = [float(p["high_rc_share"]) for p in profiles]

    return {
        "n_strategies": n,
        "unique_behavior_hashes": len(set(bhashes)),
        "unique_outcome_hashes": len(set(ohashes)) if ohashes else 0,
        "all_behavior_hashes_unique": len(set(bhashes)) == n,
        "all_outcome_hashes_unique": (len(set(ohashes)) == n) if len(ohashes) == n else False,
        "min_pairwise_view_disagreement": round(min(disagreements), 4) if disagreements else 0.0,
        "mean_pairwise_view_disagreement": round(sum(disagreements) / len(disagreements), 4) if disagreements else 0.0,
        "leak_rate_span": round(max(leak_rates) - min(leak_rates), 4),
        "frame_rate_span": round(max(frame_rates) - min(frame_rates), 4),
        "high_rc_share_span": round(max(high_rc) - min(high_rc), 4),
        "distinct_leak_selectors": sorted(leak_sels),
        "distinct_frame_selectors": sorted(frame_sels),
    }


def outcome_trace_v14(
    strategy_json: dict[str, Any],
    tier: str = "hard",
    seeds: Iterable[int] = DEFAULT_AUDIT_SEEDS,
    agents: Sequence[str] = OUTCOME_AGENTS,
) -> list[tuple[Any, ...]]:
    ms = MoleStrategy.from_json(strategy_json)
    seed_list = [int(s) for s in seeds]
    _validate_extra_seed_slice("outcome_seeds", seed_list, set())
    trace: list[tuple[Any, ...]] = []
    for ag in agents:
        fac = make_policy_factory(ag)
        for s in seed_list:
            env = Env(tier, s, mole_strategy=ms)
            run_episode(env, fac(s))
            for ev in env.ledger():
                if ev.event in OUTCOME_EVENTS:
                    target = ev.detail.get("doc_id") or ev.detail.get("employee")
                    trace.append((ag, s, int(ev.day), ev.event, target))
    return trace


def outcome_hash_v14(
    strategy_json: dict[str, Any],
    tier: str = "hard",
    seeds: Iterable[int] = DEFAULT_AUDIT_SEEDS,
    agents: Sequence[str] = OUTCOME_AGENTS,
) -> str:
    tr = outcome_trace_v14(strategy_json, tier=tier, seeds=seeds, agents=agents)
    payload = json.dumps(tr, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def select_diverse_survivors(
    candidates: Sequence[dict[str, Any]],
    max_survivors: int = DEFAULT_MAX_SURVIVORS,
    tier: str = "hard",
    min_view_disagreement: float = MIN_VIEW_DISAGREEMENT,
) -> list[dict[str, Any]]:
    by_bhash: dict[str, dict[str, Any]] = {}
    for cand in candidates:
        sj = _extract_strategy_json(cand)
        bh = cand.get("behavior_hash") or behavior_hash(sj, tier)
        score_key = (
            float(cand.get("fitness", -math.inf)),
            float(cand.get("solver_acc", 0.0)),
            float(cand.get("solver_score", 0.0)),
            -len(sj.get("rules", [])),
            canonical(sj),
        )
        prev = by_bhash.get(bh)
        if prev is None or score_key > prev["_sort_key"]:
            by_bhash[bh] = {**cand, "strategy_json": sj, "behavior_hash": bh, "_sort_key": score_key}

    by_outcome: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(by_bhash.values()):
        oh = item.get("outcome_hash") or f"unique_{idx}_{item['behavior_hash']}"
        prev = by_outcome.get(oh)
        if prev is None or item["_sort_key"] > prev["_sort_key"]:
            by_outcome[oh] = item

    ordered = sorted(by_outcome.values(), key=lambda x: x["_sort_key"], reverse=True)
    chosen: list[dict[str, Any]] = []
    for item in ordered:
        if len(chosen) >= max_survivors:
            break
        if all(
            pairwise_view_disagreement(item["strategy_json"], prev["strategy_json"], tier) >= min_view_disagreement
            for prev in chosen
        ):
            cleaned = {k: v for k, v in item.items() if k != "_sort_key"}
            chosen.append(cleaned)
    return chosen


def _quick_solver_acc(
    strategy_json: dict[str, Any],
    solver_fac: Callable,
    seeds: Sequence[int],
    tier: str = "hard",
) -> float:
    probe = list(seeds)[:4]
    if not probe:
        return 1.0
    hits = 0
    for s in probe:
        _, ok = real_runner(tier, int(s), strategy_json, "solver", solver_fac)
        hits += int(bool(ok))
    return hits / len(probe)


def _screen_investigators_only(
    strategy_json: dict[str, Any],
    investigators: dict[str, Callable],
    seeds: Sequence[int],
    tier: str = "hard",
    workers: int = 1,
) -> dict[str, float]:
    totals: dict[str, float] = {name: 0.0 for name in investigators}
    for name, fac in sorted(investigators.items()):
        for s in seeds:
            sc, _ = real_runner(tier, int(s), strategy_json, name, fac)
            totals[name] += float(sc)
    per_inv_scores = {name: totals[name] / max(1, len(seeds)) for name in sorted(investigators)}
    max_inv = max(per_inv_scores.values()) if per_inv_scores else 0.0
    mean_inv = sum(per_inv_scores.values()) / max(1, len(per_inv_scores))
    return {"max_inv_score": max_inv, "mean_inv_score": mean_inv, **per_inv_scores}


def _validate_extra_seed_slice(label: str, seeds: Sequence[int], forbidden_overlap: set[int]) -> None:
    if not seeds:
        raise ValueError(f"{label} must not be empty")
    for s in seeds:
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError(f"{label} contains non-int seed: {s!r}")
        if s <= 29 or s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS or s in range(30_000, 30_200):
            raise ValueError(f"{label} contains prohibited seed {s}")
        if s in forbidden_overlap:
            raise ValueError(f"{label} overlaps train/holdout seed {s}")


def _git_short_sha() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() or "unknown"


def build_hof_v14(
    out_jsonl: str | Path = HOF_V14_PATH,
    out_meta: str | Path = HOF_V14_META_PATH,
    tier: str = "hard",
    train_seeds: Iterable[int] = DEFAULT_TRAIN_SEEDS,
    holdout_seeds: Iterable[int] = DEFAULT_HOLDOUT_SEEDS,
    audit_seeds: Iterable[int] = DEFAULT_AUDIT_SEEDS,
    batch_size: int = 8,
    workers: int = 2,
    seed: int = 14,
    max_survivors: int = DEFAULT_MAX_SURVIVORS,
    min_solver_acc: float = MIN_SOLVER_ACC,
    min_solver_ratio: float = MIN_SOLVER_RATIO,
    min_view_disagreement: float = MIN_VIEW_DISAGREEMENT,
    n_gen0: int = 6,
    n_gen1: int = 6,
    fuzz_calls: int = 400,
    log: Callable[[str], None] = lambda msg: print(msg, flush=True),
) -> dict[str, Any]:
    train_list = [int(s) for s in train_seeds]
    holdout_list = [int(s) for s in holdout_seeds]
    audit_list = [int(s) for s in audit_seeds]
    validate_seed_hygiene(train_list, holdout_list)
    _validate_extra_seed_slice("audit_seeds", audit_list, set(train_list) | set(holdout_list))

    invs = v14_hof_investigators(include_frontier_proxies=True)
    solver_fac = default_solver_factory()
    mutator = V14Mutator(seed=seed, tier=tier)

    archetypes = empirical_archetypes(tier)
    candidate_pool: dict[str, dict[str, Any]] = {}
    for name, sj in archetypes:
        bh = behavior_hash(sj, tier)
        candidate_pool[bh] = {"label": name, "origin": "empirical_archetype", "strategy_json": sj}

    mutator.reseed(0)
    parent_records = [{"strategy_json": sj, "fitness": None, "beaten_tags": []} for _, sj in archetypes]
    parent_records.append({"strategy_json": validate_strategy(default_strategy_json()), "fitness": None, "beaten_tags": []})
    gen0_children = mutator.propose(parent_records, n_gen0)
    for idx, child in enumerate(gen0_children):
        bh = behavior_hash(child, tier)
        if bh not in candidate_pool:
            candidate_pool[bh] = {
                "label": f"j5c_gen0_{idx:02d}",
                "origin": "v14_mutator_gen0",
                "strategy_json": child,
            }

    batch0 = generation_seed_batch(train_list, batch_size, seed=seed, gen=0)
    log(f"screening {len(candidate_pool)} candidates on train batch0 (n={len(batch0)})")
    screened_gen0: list[dict[str, Any]] = []
    for bh, info in candidate_pool.items():
        prof = _strategy_profile(info["strategy_json"], tier)
        if prof["leak_rate"] < 0.45:
            continue
        qacc = _quick_solver_acc(info["strategy_json"], solver_fac, batch0, tier=tier)
        if qacc < 0.75:
            continue
        inv_stats = _screen_investigators_only(info["strategy_json"], invs, batch0, tier=tier, workers=workers)
        screened_gen0.append(
            {
                **info,
                "behavior_hash": bh,
                "screen_score": -inv_stats["max_inv_score"] - 0.35 * inv_stats["mean_inv_score"] + 0.10 * qacc,
                "max_inv_score": inv_stats["max_inv_score"],
            }
        )
    screened_gen0.sort(key=lambda x: x["screen_score"], reverse=True)

    mutator.reseed(1)
    top_parents = [
        {"strategy_json": x["strategy_json"], "fitness": x["screen_score"], "beaten_tags": []}
        for x in screened_gen0[:8]
    ]
    gen1_children = mutator.propose(top_parents, n_gen1)
    batch1 = generation_seed_batch(train_list, batch_size, seed=seed, gen=1)
    log(f"screening {len(gen1_children)} gen1 children on train batch1 (n={len(batch1)})")
    for idx, child in enumerate(gen1_children):
        bh = behavior_hash(child, tier)
        if bh in candidate_pool:
            continue
        prof = _strategy_profile(child, tier)
        if prof["leak_rate"] < 0.45:
            continue
        qacc = _quick_solver_acc(child, solver_fac, batch1, tier=tier)
        if qacc < 0.75:
            continue
        inv_stats = _screen_investigators_only(child, invs, batch1, tier=tier, workers=workers)
        entry = {
            "label": f"j5c_gen1_{idx:02d}",
            "origin": "v14_mutator_gen1",
            "strategy_json": child,
            "behavior_hash": bh,
            "screen_score": -inv_stats["max_inv_score"] - 0.35 * inv_stats["mean_inv_score"] + 0.10 * qacc,
            "max_inv_score": inv_stats["max_inv_score"],
        }
        candidate_pool[bh] = entry
        screened_gen0.append(entry)

    diverse_pre = select_diverse_survivors(
        [
            {
                **x,
                "fitness": x["screen_score"],
                "solver_acc": 1.0,
                "solver_score": 1.0,
            }
            for x in screened_gen0
        ],
        max_survivors=max(10, max_survivors + 5),
        tier=tier,
        min_view_disagreement=min_view_disagreement,
    )

    batch2 = generation_seed_batch(train_list, min(10, len(train_list)), seed=seed, gen=2)
    train_base = solver_baseline(solver_fac, batch2, tier, real_runner, workers)
    log(f"evaluating {len(diverse_pre)} diverse candidates with SolverPolicy on train batch2 (n={len(batch2)})")
    train_raw_feasible: list[dict[str, Any]] = []
    for item in diverse_pre:
        ev = evaluate_v14(
            item["strategy_json"],
            invs,
            solver_fac,
            batch2,
            tier=tier,
            runner=real_runner,
            workers=workers,
            baseline=train_base,
            fitness_mode="min",
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
        )
        log(
            f"  train {item['label']}: solver_acc={ev['solver_acc']:.3f} "
            f"solver_score={ev['solver_score']:.3f} min_regret={ev['min_regret']:.3f}"
        )
        if ev["feasible"] and ev["min_regret"] > 0.0:
            train_raw_feasible.append(
                {
                    **item,
                    "fitness": float(ev["min_regret"]),
                    "solver_acc": float(ev["solver_acc"]),
                    "solver_score": float(ev["solver_score"]),
                    "train_eval": ev,
                }
            )
    train_feasible = select_diverse_survivors(
        train_raw_feasible,
        max_survivors=max_survivors + 1,
        tier=tier,
        min_view_disagreement=min_view_disagreement,
    )

    log(f"evaluating default baseline + {len(train_feasible)} train-feasible candidates on holdout (n={len(holdout_list)})")
    holdout_base = solver_baseline(solver_fac, holdout_list, tier, real_runner, workers)
    default_holdout = evaluate_v14(
        validate_strategy(default_strategy_json()),
        invs,
        solver_fac,
        holdout_list,
        tier=tier,
        runner=real_runner,
        workers=workers,
        baseline=holdout_base,
        fitness_mode="min",
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
    )

    holdout_passed: list[dict[str, Any]] = []
    outcome_groups: dict[str, list[str]] = {}
    source_strategies: list[str] = []
    for idx, item in enumerate(train_feasible):
        cid = f"cand_{idx + 1:02d}_{item['label']}"
        source_strategies.append(cid)
        sj = item["strategy_json"]
        ev = evaluate_v14(
            sj,
            invs,
            solver_fac,
            holdout_list,
            tier=tier,
            runner=real_runner,
            workers=workers,
            baseline=holdout_base,
            fitness_mode="min",
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
        )
        gain_min = float(ev["min_regret"]) - float(default_holdout["min_regret"])
        gain_mean = float(ev["regret"]) - float(default_holdout["regret"])
        if not ev["feasible"] or float(ev["min_regret"]) <= 0.0:
            log(
                f"  holdout {cid}: acc={ev['solver_acc']:.3f} score={ev['solver_score']:.3f} "
                f"min_regret={ev['min_regret']:.3f} gain={gain_min:+.3f} skipped"
            )
            continue
        oh = outcome_hash_v14(sj, tier=tier, seeds=audit_list)
        outcome_groups.setdefault(oh, []).append(cid)
        log(
            f"  holdout {cid}: acc={ev['solver_acc']:.3f} score={ev['solver_score']:.3f} "
            f"min_regret={ev['min_regret']:.3f} gain={gain_min:+.3f} outcome={oh[:10]}"
        )
        holdout_passed.append(
            {
                "candidate_id": cid,
                "label": item["label"],
                "origin": item["origin"],
                "strategy_json": sj,
                "behavior_hash": item["behavior_hash"],
                "behavior_profile": _strategy_profile(sj, tier),
                "outcome_hash": oh,
                "fitness": float(ev["min_regret"]),
                "min_regret": float(ev["min_regret"]),
                "mean_regret": float(ev["regret"]),
                "min_regret_gain_vs_default": gain_min,
                "mean_regret_gain_vs_default": gain_mean,
                "solver_score": float(ev["solver_score"]),
                "solver_acc": float(ev["solver_acc"]),
                "per_investigator": ev["per_investigator"],
            }
        )

    shortlist = select_diverse_survivors(
        holdout_passed,
        max_survivors=max_survivors + 2,
        tier=tier,
        min_view_disagreement=min_view_disagreement,
    )

    verified_survivors: list[dict[str, Any]] = []
    for item in shortlist:
        if len(verified_survivors) >= max_survivors:
            break
        sj = item["strategy_json"]
        audit_rep = audit_strategy(
            sj,
            tier=tier,
            seeds=audit_list,
            min_solver_acc=min_solver_acc,
            min_solver_score=0.25,
            max_logs_acc=0.20,
        )
        ms = MoleStrategy.from_json(sj)
        fuzz_rep = fuzz.hunt(
            tier,
            audit_list,
            fuzz_calls,
            0,
            mode="all",
            factory=lambda t, s, m=ms: Env(t, s, mole_strategy=m),
        )
        fuzz_ok = bool(fuzz_rep["best_non_solver_score"] <= 0 and not fuzz_rep["invariant_violations"])
        log(
            f"  audit {item['candidate_id']}: fairness_all={audit_rep['all_passed']} "
            f"audit_solver_acc={audit_rep['checks']['solver_beatable']['solver_acc']:.3f} fuzz_ok={fuzz_ok}"
        )
        if audit_rep["all_passed"] and fuzz_ok:
            verified_survivors.append(
                {
                    **item,
                    "audit_solver_acc": float(audit_rep["checks"]["solver_beatable"]["solver_acc"]),
                    "audit_solver_score": float(audit_rep["checks"]["solver_beatable"]["solver_mean_score"]),
                    "audit_regret_gain": float(audit_rep["checks"]["regret_gain"]["regret_gain"]),
                    "fuzz_best_non_solver_score": float(fuzz_rep["best_non_solver_score"]),
                }
            )

    if len(verified_survivors) < 3:
        raise RuntimeError(f"expected at least 3 verified diverse v1.4 HoF survivors, got {len(verified_survivors)}")

    hof_rows: list[dict[str, Any]] = []
    survivor_details: list[dict[str, Any]] = []
    outcome_by_rank: dict[int, str] = {}
    for rank_idx, item in enumerate(verified_survivors, start=1):
        row = {
            "rank": rank_idx,
            "fitness": round(float(item["fitness"]), 6),
            "solver_score": round(float(item["solver_score"]), 6),
            "solver_acc": round(float(item["solver_acc"]), 6),
            "per_investigator": {
                inv_name: {
                    "score": round(float(vals["score"]), 6),
                    "acc": round(float(vals["acc"]), 6),
                    "regret": round(float(vals["regret"]), 6),
                }
                for inv_name, vals in sorted(item["per_investigator"].items())
            },
            "strategy_json": item["strategy_json"],
        }
        hof_rows.append(row)
        outcome_by_rank[rank_idx] = item["outcome_hash"]
        survivor_details.append(
            {
                "rank": rank_idx,
                "candidate_id": item["candidate_id"],
                "label": item["label"],
                "origin": item["origin"],
                "behavior_hash": item["behavior_hash"],
                "outcome_hash": item["outcome_hash"],
                "behavior_profile": {
                    k: round(float(v), 4) if isinstance(v, float) else v
                    for k, v in item["behavior_profile"].items()
                },
                "holdout_solver_acc": round(float(item["solver_acc"]), 6),
                "holdout_solver_score": round(float(item["solver_score"]), 6),
                "holdout_min_regret": round(float(item["min_regret"]), 6),
                "holdout_mean_regret": round(float(item["mean_regret"]), 6),
                "min_regret_gain_vs_default": round(float(item["min_regret_gain_vs_default"]), 6),
                "mean_regret_gain_vs_default": round(float(item["mean_regret_gain_vs_default"]), 6),
                "audit_solver_acc": round(float(item["audit_solver_acc"]), 6),
                "audit_solver_score": round(float(item["audit_solver_score"]), 6),
                "audit_regret_gain": round(float(item["audit_regret_gain"]), 6),
                "fuzz_best_non_solver_score": round(float(item["fuzz_best_non_solver_score"]), 6),
            }
        )

    diversity = behavioral_diversity_report(hof_rows, tier=tier, outcome_hashes_by_rank=outcome_by_rank)
    named_outcome_groups = {
        members[0]: members for members in outcome_groups.values()
    }
    group_sizes = {grp: len(members) for grp, members in named_outcome_groups.items()}

    meta = {
        "code_sha": _git_short_sha(),
        "tiers_version": TIERS_VERSION,
        "tier": tier,
        "train_seeds": f"{train_list[0]}:{train_list[-1] + 1}",
        "seeds": f"{holdout_list[0]}:{holdout_list[-1] + 1}",
        "n_seeds": len(holdout_list),
        "outcome_seeds": f"{audit_list[0]}:{audit_list[-1] + 1}",
        "min_solver_acc": min_solver_acc,
        "min_solver_ratio": min_solver_ratio,
        "min_view_disagreement": min_view_disagreement,
        "feasibility": (
            "solver_score >= 0.5 x default-mole solver score AND solver_acc >= 0.85 on fresh v1.4 hard seeds "
            "AND min_regret > 0 across heuristic, hinted_heuristic, grok_tactics, gemini_carbon_proxy, codex_horizon_proxy "
            "AND all 7 fairness_audit checks + fuzz hunt passed on audit seeds"
        ),
        "dedupe_method": (
            "two-stage behavioural + outcome diversity: unique 64-view MoleView decision hash, unique world-level "
            "(agent, seed, day, event, doc_id|frame_target) outcome hash under do_nothing and solver on hard seeds "
            f"{audit_list[0]}:{audit_list[-1] + 1}, and pairwise representative-view disagreement >= {min_view_disagreement:.2f}"
        ),
        "n_candidates_screened": len(candidate_pool),
        "n_train_feasible": len(train_feasible),
        "n_survivors": len(hof_rows),
        "source_strategies": source_strategies,
        "outcome_groups": named_outcome_groups,
        "group_sizes": group_sizes,
        "baseline_default_mole": {
            "solver_score": round(float(default_holdout["solver_score"]), 6),
            "solver_acc": round(float(default_holdout["solver_acc"]), 6),
            "min_regret": round(float(default_holdout["min_regret"]), 6),
            "mean_regret": round(float(default_holdout["regret"]), 6),
            "per_investigator": {
                k: {kk: round(float(vv), 6) for kk, vv in v.items()}
                for k, v in sorted(default_holdout["per_investigator"].items())
            },
        },
        "behavioral_diversity": diversity,
        "survivors": survivor_details,
        "write_command": (
            f"python -m canary.mole.hof_v14 build --tier {tier} "
            f"--train-seeds {train_list[0]}-{train_list[-1]} "
            f"--holdout-seeds {holdout_list[0]}-{holdout_list[-1]} "
            f"--audit-seeds {audit_list[0]}-{audit_list[-1]}"
        ),
    }

    out_jsonl_p = Path(out_jsonl)
    out_meta_p = Path(out_meta)
    out_jsonl_p.parent.mkdir(parents=True, exist_ok=True)
    out_meta_p.parent.mkdir(parents=True, exist_ok=True)
    out_jsonl_p.write_text("".join(json.dumps(r) + "\n" for r in hof_rows), encoding="utf-8")
    out_meta_p.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    forge_track._cache.pop(str(out_jsonl_p.resolve()), None)
    return {"hof": hof_rows, "meta": meta}


def verify_hof_v14_artifacts(
    hof_path: str | Path = HOF_V14_PATH,
    meta_path: str | Path = HOF_V14_META_PATH,
    min_solver_acc: float = MIN_SOLVER_ACC,
    min_view_disagreement: float = MIN_VIEW_DISAGREEMENT,
    live_seeds: Sequence[int] | None = None,
) -> dict[str, Any]:
    hp = Path(hof_path)
    mp = Path(meta_path)
    rows, strats = load_hof_v14(hp)
    meta = load_hof_v14_meta(mp)

    if len(rows) < 3:
        raise ValueError(f"expected >= 3 diverse v1.4 HoF strategies, got {len(rows)}")
    if meta.get("tiers_version") != "v1.4" or meta.get("tier") != "hard":
        raise ValueError(f"unexpected meta tier/version: {meta.get('tier')}/{meta.get('tiers_version')}")
    if meta.get("n_survivors") != len(rows):
        raise ValueError("meta n_survivors mismatch")

    survivor_meta = meta.get("survivors") or []
    outcome_map = {int(s["rank"]): str(s["outcome_hash"]) for s in survivor_meta if "rank" in s and "outcome_hash" in s}

    for idx, (row, strat) in enumerate(zip(rows, strats), start=1):
        if tuple(row.keys()) != HOF_KEYS:
            raise ValueError(f"row {idx} keys {tuple(row.keys())} != {HOF_KEYS}")
        if row["rank"] != idx:
            raise ValueError(f"row {idx} rank mismatch: {row['rank']}")
        if float(row["solver_acc"]) < min_solver_acc:
            raise ValueError(f"row {idx} solver_acc {row['solver_acc']} < {min_solver_acc}")
        if float(row["fitness"]) <= 0.0:
            raise ValueError(f"row {idx} non-positive fitness: {row['fitness']}")
        norm = validate_strategy(row["strategy_json"])
        if norm != row["strategy_json"]:
            raise ValueError(f"row {idx} strategy_json is not in canonical form")
        if MoleStrategy.from_json(norm) != strat:
            raise ValueError(f"row {idx} MoleStrategy round-trip mismatch")
        for rule in norm.get("rules", []):
            if not is_valid_rule_conds(rule["if"], "hard"):
                raise ValueError(f"row {idx} rule condition failed tier range check: {rule['if']}")

    div = behavioral_diversity_report(rows, tier="hard", outcome_hashes_by_rank=outcome_map)
    if not div["all_behavior_hashes_unique"]:
        raise ValueError("duplicate behavior_hash detected in v1.4 HoF")
    if outcome_map and not div["all_outcome_hashes_unique"]:
        raise ValueError("duplicate outcome_hash detected in v1.4 HoF")
    if float(div["min_pairwise_view_disagreement"]) < min_view_disagreement:
        raise ValueError(
            f"pairwise view disagreement {div['min_pairwise_view_disagreement']} < {min_view_disagreement}"
        )

    live_check: list[dict[str, Any]] | None = None
    if live_seeds is not None:
        _validate_extra_seed_slice("live_seeds", list(live_seeds), set())
        accepted = forge_track.validate(hp, list(live_seeds), out=None, min_acc=min_solver_acc, tier="hard")
        if len(accepted) != len(rows):
            raise ValueError(
                f"live catchability check accepted {len(accepted)}/{len(rows)} strategies at min_acc={min_solver_acc}"
            )
        live_check = [r["track_validation"] for r in accepted]

    return {
        "ok": True,
        "n_strategies": len(rows),
        "min_recorded_solver_acc": min(float(r["solver_acc"]) for r in rows),
        "diversity": div,
        "live_check": live_check,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.hof_v14")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--out", default=str(HOF_V14_PATH))
    b.add_argument("--meta-out", default=str(HOF_V14_META_PATH))
    b.add_argument("--tier", default="hard")
    b.add_argument("--train-seeds", default="200-599")
    b.add_argument("--holdout-seeds", default="6200-6229")
    b.add_argument("--audit-seeds", default="6000-6009")
    b.add_argument("--batch-size", type=int, default=8)
    b.add_argument("--workers", type=int, default=2)
    b.add_argument("--seed", type=int, default=14)
    b.add_argument("--max-survivors", type=int, default=DEFAULT_MAX_SURVIVORS)
    b.add_argument("--min-solver-acc", type=float, default=MIN_SOLVER_ACC)
    b.add_argument("--min-solver-ratio", type=float, default=MIN_SOLVER_RATIO)
    b.add_argument("--min-view-disagreement", type=float, default=MIN_VIEW_DISAGREEMENT)

    v = sub.add_parser("verify")
    v.add_argument("--hof", default=str(HOF_V14_PATH))
    v.add_argument("--meta", default=str(HOF_V14_META_PATH))
    v.add_argument("--min-solver-acc", type=float, default=MIN_SOLVER_ACC)
    v.add_argument("--min-view-disagreement", type=float, default=MIN_VIEW_DISAGREEMENT)
    v.add_argument("--live-seeds", default=None)

    args = ap.parse_args(argv)
    if args.cmd == "build":
        res = build_hof_v14(
            out_jsonl=args.out,
            out_meta=args.meta_out,
            tier=args.tier,
            train_seeds=parse_seeds(args.train_seeds),
            holdout_seeds=parse_seeds(args.holdout_seeds),
            audit_seeds=parse_seeds(args.audit_seeds),
            batch_size=args.batch_size,
            workers=args.workers,
            seed=args.seed,
            max_survivors=args.max_survivors,
            min_solver_acc=args.min_solver_acc,
            min_solver_ratio=args.min_solver_ratio,
            min_view_disagreement=args.min_view_disagreement,
        )
        print(
            json.dumps(
                {
                    "n_survivors": len(res["hof"]),
                    "ranks": [r["rank"] for r in res["hof"]],
                    "solver_accs": [r["solver_acc"] for r in res["hof"]],
                    "fitnesses": [r["fitness"] for r in res["hof"]],
                    "diversity": res["meta"]["behavioral_diversity"],
                },
                indent=2,
            )
        )
        return 0

    live = parse_seeds(args.live_seeds) if args.live_seeds else None
    rep = verify_hof_v14_artifacts(
        hof_path=args.hof,
        meta_path=args.meta,
        min_solver_acc=args.min_solver_acc,
        min_view_disagreement=args.min_view_disagreement,
        live_seeds=live,
    )
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
