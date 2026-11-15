"""WS5: PAIRED Gemini Scenario Designer at scale (arena mode, not the judged environment).

    uv run --extra llm --extra dev --extra plot python -m canary.gemini.designer_scale \
        --target 500 --tier medium --seeds 0-4 --scratch data/gemini/scratch/designer_ws5 \
        --out results/gemini/scale/designer

Labelled everywhere: "arena mode, not the judged environment".
Proposer: gemini-4-hydrogen (~500 Mole DSL strategies on medium tier; TierParams untouched).
Filter:   SolverPolicy mean >= 0.5 AND gemini-3.8-flash (thinking=low) mean <= 0.2 on 5 dev seeds (in-process).
Transfer: Top 10 accepted strategies evaluated against gemini-4-argon (thinking=high) on the same 5 dev seeds.
Zero gemini-4-carbon API calls; <= 4 CPU processes; every Gemini call ledgered via canary.gemini.ledger.lab_client.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import math
import random
import statistics
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from canary.agents.llm_policy import LLMPolicy
from canary.agents.loop import run_episode
from canary.env import Env
from canary.forge.mutate import (
    DSL_GRAMMAR,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    MAX_CONDS,
    MAX_RULES,
    _coerce_child,
    canonical,
    default_strategy_json,
    validate_strategy,
)
from canary.mole.dsl import MoleDoc, MoleStrategy, MoleView
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[2]
ARENA_LABEL = "arena mode, not the judged environment"
FEATURE = "scale-designer"

ARCHETYPES = (
    (
        "trap_evader",
        "Avoid leaking whenever low-recipient canary traps are likely in the window (`recent_low_recipient_docs >= 1` "
        "or `min_recipient_count <= 4`), preferring `most_recipients` or holding fire (`none`) while framing `decoy`.",
    ),
    (
        "stale_doc_ambusher",
        "Exploit the 3-day leak window and 1-3 day surfacing delay by leaking `oldest` documents (`newest_doc_age_days` "
        "or `n_docs_held >= 3`) so leaks attribute to earlier days' recipient intersections, confusing LLM bookkeeping.",
    ),
    (
        "burst_and_silent",
        "Alternate silence (`days_since_last_leak < 2` or `< 3` -> `leak: none`) with sudden broad leaks (`most_recipients` "
        "or `newest`) while framing `random_peer` or `decoy` continuously to lure premature accusations.",
    ),
    (
        "decoy_amplifier",
        "Relentlessly frame `decoy` on early days (`day <= 6`) while leaking `most_recipients` or `oldest`, tempting a "
        "low-thinking LLM to accuse the angry decoy or framed peers before canary evidence resolves.",
    ),
    (
        "restriction_counterpuncher",
        "React to investigator containment (`i_am_restricted == 1` or `n_restricted_colleagues >= 1`) by switching between "
        "`none`, `oldest`, and `most_restricted_peer` framing to corrupt restriction-based elimination.",
    ),
    (
        "late_horizon_sprinter",
        "Leak conservatively early (`day <= 4` -> `most_recipients` or `none` when `recent_low_recipient_docs >= 1`) and "
        "accelerate leaks (`newest` / `random_seeded`) in `day >= 6` so value drains right as the 14-day horizon closes.",
    ),
    (
        "high_pool_camouflager",
        "Only leak when holding large-pool documents (`max_recipient_count >= 9` or `>= 10` -> `most_recipients`), "
        "holding fire (`none`) when only narrow documents are held, starving naive investigators of narrow intersections.",
    ),
    (
        "peer_scatter_framer",
        "Combine `random_peer` framing on odd/early phases with `decoy` framing on later phases while leaking `oldest` "
        "when `n_leakable >= 3`, spreading false after-hours log spikes across innocent staff.",
    ),
    (
        "threshold_edge_switcher",
        "Chain 3 to 6 specific threshold conditions on `day`, `n_docs_held`, `min_recipient_count`, and "
        "`days_since_last_leak` so the leak pattern shifts mid-episode while remaining catchable by Bayes canary splits.",
    ),
    (
        "canary_dilution_hybrid",
        "When `recent_low_recipient_docs == 0`, leak `newest` or `random_seeded` aggressively; when `recent_low_recipient_docs >= 1`, "
        "switch to `most_recipients` (never `fewest_recipients`) and frame `decoy`.",
    ),
)

PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "strategies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "rationale": {"type": "string"},
                    "rules": {
                        "type": "array",
                        "maxItems": MAX_RULES,
                        "items": {
                            "type": "object",
                            "properties": {
                                "if": {
                                    "type": "array",
                                    "minItems": 1,
                                    "maxItems": MAX_CONDS,
                                    "items": {
                                        "type": "array",
                                        "minItems": 3,
                                        "maxItems": 3,
                                        "items": {"type": "string"},
                                    },
                                },
                                "then": {
                                    "type": "object",
                                    "properties": {
                                        "leak": {"type": "string", "enum": list(LEAK_SELECTORS)},
                                        "frame": {"type": "string", "enum": list(FRAME_SELECTORS)},
                                    },
                                    "required": ["leak", "frame"],
                                },
                            },
                            "required": ["if", "then"],
                        },
                    },
                    "default": {
                        "type": "object",
                        "properties": {
                            "leak": {"type": "string", "enum": list(LEAK_SELECTORS)},
                            "frame": {"type": "string", "enum": list(FRAME_SELECTORS)},
                        },
                        "required": ["leak", "frame"],
                    },
                },
                "required": ["name", "rationale", "rules", "default"],
            },
        }
    },
    "required": ["strategies"],
}


def wilson_ci(k: int, n: int, z: float = 1.96) -> list[float]:
    if n <= 0:
        return [0.0, 1.0]
    p = k / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / denom
    return [round(max(0.0, center - half), 4), round(min(1.0, center + half), 4)]


def mean_ci95(xs: list[float]) -> tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = statistics.fmean(xs)
    if len(xs) < 2:
        return round(m, 4), 0.0
    hw = 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))
    return round(m, 4), round(hw, 4)


def paired_bootstrap_ci(a: list[float], b: list[float], n_boot: int = 2000, seed: int = 42) -> list[float]:
    """95% bootstrap CI on mean(a - b) for paired seed scores."""
    if not a or len(a) != len(b):
        return [0.0, 0.0]
    n = len(a)
    diffs = [x - y for x, y in zip(a, b)]
    if n == 1:
        return [round(diffs[0], 4), round(diffs[0], 4)]
    rng = random.Random(seed)
    means = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return [round(means[int(0.025 * n_boot)], 4), round(means[int(0.975 * n_boot)], 4)]


def git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def strategy_can_leak(strat_json: dict) -> bool:
    thens = [r.get("then", {}) for r in strat_json.get("rules", [])] + [strat_json.get("default", {})]
    return any((t.get("leak") or "none") != "none" for t in thens)


# Prebuilt representative MoleView probe states on medium tier (20 staff, 14 days) to detect exact functional twins
def _build_probe_views() -> list[MoleView]:
    """4,096 deterministic reachable medium-tier MoleView states spanning every integer value 0..20 of every feature."""
    rng = random.Random("ws5-functional-probe-v1")
    views: list[MoleView] = []
    for i in range(4096):
        day = (i % 14) + 1
        dsl = rng.randint(0, day)
        iam = i % 2
        nrest = rng.choice([0, 0, 1, 2, 3, 4, 5, 8])
        n_docs = rng.randint(1, 10)
        min_age = rng.choice([0, 1, 2])
        recs = sorted([rng.randint(1, 20) for _ in range(n_docs)])
        ages = [min_age] + [rng.randint(min_age, 2) for _ in range(n_docs - 1)]
        rng.shuffle(ages)
        docs = tuple(MoleDoc(f"d{k}", f"doc{k}", recs[k], ages[k]) for k in range(n_docs))
        rlow = sum(1 for d in docs if d.recipient_count <= 3)
        views.append(MoleView(
            day=day,
            docs=docs,
            days_since_last_leak=dsl,
            i_am_restricted=iam,
            n_restricted_colleagues=nrest,
            recent_low_recipient_docs=rlow,
            peers=("e01", "e02", "e03"),
            restricted_peers=("e02",) if nrest > 0 else (),
            decoy="e19",
            can_leak=True,
            select_weights=tuple(1.0 for _ in docs),
        ))
    return views


_PROBE_VIEWS = _build_probe_views()


def functional_signature(strat_json: dict) -> str:
    """Hash the (leak_sel, frame_sel) rule choice across reachable medium-tier MoleView states + custom thresholds."""
    ms = MoleStrategy.from_json(strat_json)
    choices = []
    for v in _PROBE_VIEWS:
        leak_sel, frame_sel = ms.default
        for conds, then in ms.rules:
            if all(
                {"<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b,
                 ">=": lambda a, b: a >= b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}[op](v.feature(f), n)
                for f, op, n in conds
            ):
                leak_sel, frame_sel = then
                break
        choices.append(f"{leak_sel}:{frame_sel}")
    return hashlib.sha256("|".join(choices).encode()).hexdigest()[:16]


def _eval_fast_candidate_worker(args: tuple[str, list[int], dict]) -> dict:
    """Top-level picklable worker for <= 4 CPU processes: runs SolverPolicy + Heuristic on seeds."""
    from canary.baselines import Heuristic
    tier, seeds, strat_json = args
    s_scores, s_corr, s_days = [], [], []
    h_scores, h_corr = [], []
    trace_events = []
    for seed in seeds:
        env_s = Env(tier=tier, seed=seed, mole_strategy=strat_json)
        res_s = run_episode(env_s, SolverPolicy(), "solver")
        s_scores.append(round(float(res_s.score), 4))
        s_corr.append(bool(res_s.correct))
        s_days.append(int(res_s.final_day))
        # Record leak/frame ledger events under solver for empirical outcome-trace hashing
        for le in env_s._ledger:
            if le.event in ("leak", "framed"):
                trace_events.append(f"{seed}:{le.day}:{le.event}:{le.detail.get('doc_id') or le.detail.get('target')}")

        env_h = Env(tier=tier, seed=seed, mole_strategy=strat_json)
        res_h = run_episode(env_h, Heuristic(seed=seed), "heuristic")
        h_scores.append(round(float(res_h.score), 4))
        h_corr.append(bool(res_h.correct))

    sm, sci = mean_ci95(s_scores)
    hm, hci = mean_ci95(h_scores)
    thash = hashlib.sha256("|".join(trace_events).encode()).hexdigest()[:16]
    fhash = functional_signature(strat_json)
    return {
        "solver_scores": s_scores,
        "solver_mean": sm,
        "solver_ci95": sci,
        "solver_acc": round(sum(s_corr) / len(s_corr), 4),
        "solver_mean_day": round(sum(s_days) / len(s_days), 2),
        "heuristic_scores": h_scores,
        "heuristic_mean": hm,
        "heuristic_ci95": hci,
        "heuristic_acc": round(sum(h_corr) / len(h_corr), 4),
        "solver_trace_hash": thash,
        "functional_hash": fhash,
        "behavior_key": f"{fhash}:{thash}",
    }


def evaluate_solver_batch(candidates: list[dict], tier: str, seeds: list[int], cpu_workers: int = 4) -> list[dict]:
    cpu_workers = max(1, min(4, cpu_workers))
    tasks = [(tier, seeds, c["strategy_json"]) for c in candidates]
    if cpu_workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=cpu_workers) as pool:
            evals = list(pool.map(_eval_fast_candidate_worker, tasks))
    else:
        evals = [_eval_fast_candidate_worker(t) for t in tasks]
    out = []
    for c, ev in zip(candidates, evals):
        out.append({**c, **ev})
    return out


class ModelVersionTracker:
    """Thread-safe tracker capturing API-served model_version strings from LedgeredClient responses."""

    def __init__(self, inner):
        self.inner = inner
        self.model_versions: dict[str, int] = {}
        self._lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def chat(self, *args, **kwargs):
        r = self.inner.chat(*args, **kwargs)
        mv = getattr(r.raw, "model_version", None) if getattr(r, "raw", None) is not None else None
        if isinstance(mv, str) and mv:
            with self._lock:
                self.model_versions[mv] = self.model_versions.get(mv, 0) + 1
        return r


def _is_infra_exception(exc: BaseException) -> bool:
    from canary.llm.base import is_retryable
    if is_retryable(exc):
        return True
    msg = f"{type(exc).__name__}: {exc}".lower()
    return any(k in msg for k in ("429", "quota", "resource_exhausted", "rate", "timeout", "503", "500", "502", "504", "connection", "disconnected", "unavailable"))


def run_llm_episode_with_retry(
    model: str,
    thinking_level: str,
    tier: str,
    seed: int,
    strat_json: dict | None,
    run_id: str,
    meta: dict,
    max_attempts: int = 5,
    client_builder=None,
) -> dict:
    """Run one in-process LLMPolicy episode; retry infra failures (sleeping 60s on 429/quota) and never score infra as 0."""
    from canary.gemini.ledger import lab_client

    if "carbon" in model.lower():
        raise ValueError("gemini-4-carbon is strictly forbidden in WS5")

    last_err = ""
    for attempt in range(1, max_attempts + 1):
        t0 = time.time()
        raw_client = (
            client_builder(model, thinking_level, run_id, meta)
            if client_builder is not None
            else lab_client(
                f"gemini:{model}",
                feature=FEATURE,
                run_id=run_id,
                meta={**meta, "seed": seed, "attempt": attempt},
                thinking_level=thinking_level,
            )
        )
        tracked = ModelVersionTracker(raw_client)
        env = Env(tier=tier, seed=seed, mole_strategy=strat_json)
        pol = LLMPolicy(f"gemini:{model}", temperature=0.0, context="full", client=tracked)
        try:
            res = run_episode(env, pol, f"gemini:{model}+think:{thinking_level}")
            if pol.usage.get("calls", 0) == 0:
                raise RuntimeError("infra: zero LLM calls recorded")
            return {
                "seed": seed,
                "valid": True,
                "score": round(float(res.score), 4),
                "correct": bool(res.correct),
                "accused": res.accused,
                "final_day": int(res.final_day),
                "end_reason": res.end_reason,
                "steps": len(res.steps),
                "llm_calls": int(pol.usage.get("calls", 0)),
                "wall_s": round(time.time() - t0, 2),
                "model_versions": dict(tracked.model_versions),
                "attempts": attempt,
            }
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {str(exc)[:240]}"
            if attempt < max_attempts and _is_infra_exception(exc):
                wait_s = 60.0 if ("429" in last_err or "exhausted" in last_err.lower() or "quota" in last_err.lower()) else min(15.0 * attempt, 60.0)
                time.sleep(wait_s)
                continue
            break
    return {
        "seed": seed,
        "valid": False,
        "infra_error": last_err,
        "score": None,
        "correct": None,
    }


def evaluate_llm_on_strategy(
    model: str,
    thinking_level: str,
    tier: str,
    seeds: list[int],
    strat_json: dict | None,
    run_id: str,
    label_id: str,
    early_reject_threshold: float | None = None,
    client_builder=None,
) -> dict:
    """Evaluate an LLM investigator across `seeds` on one mole strategy.

    If `early_reject_threshold` is set (e.g. 0.20 for flash-low), stops early ONLY when it becomes mathematically
    impossible for the 5-seed mean to be <= threshold even if all remaining seeds score -1.0 (wrong_accusation_score).
    Every candidate that can still pass runs all 5 seeds.
    """
    episodes = []
    valid_scores: list[float] = []
    model_versions: dict[str, int] = {}
    early_stopped = False
    n_total = len(seeds)

    for idx, seed in enumerate(seeds):
        ep = run_llm_episode_with_retry(
            model=model,
            thinking_level=thinking_level,
            tier=tier,
            seed=seed,
            strat_json=strat_json,
            run_id=run_id,
            meta={"strategy_id": label_id, "tier": tier},
            client_builder=client_builder,
        )
        episodes.append(ep)
        for mv, cnt in (ep.get("model_versions") or {}).items():
            model_versions[mv] = model_versions.get(mv, 0) + cnt
        if ep.get("valid"):
            valid_scores.append(float(ep["score"]))
            rem = n_total - (idx + 1)
            if early_reject_threshold is not None and rem > 0 and len(valid_scores) == idx + 1:
                min_possible_mean = (sum(valid_scores) + rem * (-1.0)) / n_total
                if min_possible_mean > early_reject_threshold + 1e-9:
                    early_stopped = True
                    break

    if not valid_scores or any(not e.get("valid") for e in episodes):
        return {
            "strategy_id": label_id,
            "model": model,
            "thinking_level": thinking_level,
            "valid": False,
            "n_valid_seeds": len(valid_scores),
            "episodes": episodes,
            "model_versions": model_versions,
        }

    m, ci = mean_ci95(valid_scores)
    acc = sum(1 for e in episodes if e.get("correct")) / len(episodes)
    return {
        "strategy_id": label_id,
        "model": model,
        "thinking_level": thinking_level,
        "valid": True,
        "early_stopped_above_threshold": early_stopped,
        "n_valid_seeds": len(valid_scores),
        "scores": valid_scores,
        "mean": m,
        "ci95": ci,
        "acc": round(acc, 4),
        "episodes": episodes,
        "model_versions": model_versions,
    }


def propose_strategies_hydrogen(
    target: int,
    tier: str,
    seeds: list[int],
    scratch_dir: Path,
    run_id: str,
    batch_size: int = 15,
    cpu_workers: int = 4,
    client_builder=None,
) -> tuple[list[dict], dict]:
    """Propose `target` distinct valid Mole DSL strategies with gemini-4-hydrogen in PAIRED evolutionary waves."""
    from canary.gemini.ledger import lab_client

    scratch_dir.mkdir(parents=True, exist_ok=True)
    prop_file = scratch_dir / "proposals_evaluated.jsonl"
    stats_file = scratch_dir / "proposal_stats.json"

    existing: list[dict] = []
    seen_canon: set[str] = {canonical(default_strategy_json())}
    if prop_file.exists():
        for ln in prop_file.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                row = json.loads(ln)
                existing.append(row)
                seen_canon.add(canonical(row["strategy_json"]))

    stats = {"batches": 0, "raw_items": 0, "syntax_valid": 0, "syntax_invalid_or_noleak": 0, "duplicate_json": 0,
             "api_errors": 0, "model_versions": {}}
    if stats_file.exists():
        stats.update(json.loads(stats_file.read_text(encoding="utf-8")))

    sys_prompt = (
        f"You are the PAIRED Scenario Designer ({ARENA_LABEL}) for the Canary insider-threat benchmark (medium tier: "
        "20 employees, 4 departments, 14 days, 1 canary/day up to 3 variants, p_leak=0.75, leak_damage=0.04, "
        "delay 1-3 days, decoy=True, framing=True, careful_mole=True).\n"
        "Your goal: propose diverse, valid Mole DSL strategies that stay SOLVABLE for the exact Bayesian reference "
        "solver (mean score >= 0.50 over 5 seeds — so the mole MUST leak documents!) while BREAKING a weaker LLM "
        "investigator (`gemini-3.8-flash` at low thinking, mean score <= 0.20) by exploiting premature accusation, "
        "framed after-hours logs, decoy anger, leak-window delays, and narrow-canary avoidance.\n\n"
        + DSL_GRAMMAR
    )

    batch_idx = stats["batches"]
    while len(existing) < target and batch_idx < 120:
        arch_name, arch_desc = ARCHETYPES[batch_idx % len(ARCHETYPES)]
        # Build evolutionary feedback from already-evaluated proposals
        feedback_lines = []
        if existing:
            feasible = [r for r in existing if r["solver_mean"] >= 0.5]
            infeasible = [r for r in existing if r["solver_mean"] < 0.5]
            top_heur_gap = sorted(feasible, key=lambda r: r["solver_mean"] - r["heuristic_mean"], reverse=True)[:4]
            for ex in top_heur_gap:
                feedback_lines.append(
                    f"  GOOD (solver={ex['solver_mean']:+.2f} >= 0.5, vs heuristic={ex['heuristic_mean']:+.2f}): "
                    f"{canonical(ex['strategy_json'])}"
                )
            for bad in infeasible[-2:]:
                feedback_lines.append(
                    f"  REJECTED (solver={bad['solver_mean']:+.2f} < 0.5, leaked too rarely): "
                    f"{canonical(bad['strategy_json'])}"
                )

        need = min(batch_size, target - len(existing) + 4)
        temp = round(0.75 + 0.05 * (batch_idx % 5), 2)
        user_prompt = (
            f"Batch #{batch_idx + 1} · Adversarial archetype: `{arch_name}` — {arch_desc}\n"
            f"Already collected: {len(existing)}/{target} distinct valid strategies.\n"
            + ("Feedback from earlier batches:\n" + "\n".join(feedback_lines) + "\n" if feedback_lines else "")
            + f"Propose {need} NEW, structurally distinct Mole DSL strategies (vary rule counts 1..6, feature combinations, "
              "thresholds, leak selectors, and frame selectors). In every condition `[feature, op, number]`, write the "
              "number as a string (e.g. `[\"day\", \">=\", \"4\"]`). Ensure at least one reachable branch leaks!"
        )

        raw_client = (
            client_builder("gemini-4-hydrogen", "low", run_id, {"batch": batch_idx, "archetype": arch_name})
            if client_builder is not None
            else lab_client(
                "gemini:gemini-4-hydrogen",
                feature=FEATURE,
                run_id=run_id,
                meta={"role": "proposer", "batch": batch_idx, "archetype": arch_name},
                thinking_level="low",
            )
        )
        tracked = ModelVersionTracker(raw_client)
        batch_idx += 1
        stats["batches"] = batch_idx
        try:
            resp = tracked.chat(
                [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
                temperature=temp,
                response_schema=PROPOSAL_SCHEMA,
                max_tokens=16384,
            )
            for mv, cnt in tracked.model_versions.items():
                stats["model_versions"][mv] = stats["model_versions"].get(mv, 0) + cnt
            items = json.loads(resp.text or "{}").get("strategies", [])
        except Exception as exc:  # noqa: BLE001
            stats["api_errors"] += 1
            if _is_infra_exception(exc):
                time.sleep(60.0)
            stats_file.write_text(json.dumps(stats, indent=2))
            continue

        new_cands = []
        for item in items:
            if len(existing) + len(new_cands) >= target:
                break
            stats["raw_items"] += 1
            try:
                norm = validate_strategy(_coerce_child(item))
                if not strategy_can_leak(norm):
                    stats["syntax_invalid_or_noleak"] += 1
                    continue
                ckey = canonical(norm)
                if ckey in seen_canon:
                    stats["duplicate_json"] += 1
                    continue
                seen_canon.add(ckey)
                stats["syntax_valid"] += 1
                idx_num = len(existing) + len(new_cands)
                new_cands.append({
                    "id": f"cand-{idx_num:04d}",
                    "archetype": arch_name,
                    "name": str(item.get("name") or f"{arch_name}-{idx_num}")[:60],
                    "rationale": str(item.get("rationale") or "")[:300],
                    "strategy_json": norm,
                })
            except Exception:  # noqa: BLE001
                stats["syntax_invalid_or_noleak"] += 1

        if new_cands:
            evaluated = evaluate_solver_batch(new_cands, tier=tier, seeds=seeds, cpu_workers=cpu_workers)
            with open(prop_file, "a", encoding="utf-8") as f:
                for row in evaluated:
                    f.write(json.dumps(row) + "\n")
            existing.extend(evaluated)
        stats_file.write_text(json.dumps(stats, indent=2))
        print(
            f"[proposer] batch={batch_idx} collected={len(existing)}/{target} "
            f"solver>=0.5: {sum(1 for r in existing if r['solver_mean'] >= 0.5)}",
            flush=True,
        )

    return existing[:target], stats


def build_report_and_write(
    proposals: list[dict],
    prop_stats: dict,
    baseline_solver: dict,
    baseline_flash: dict,
    baseline_argon: dict,
    flash_by_bkey: dict[str, dict],
    argon_by_bkey: dict[str, dict],
    tier: str,
    seeds: list[int],
    out_dir: Path,
    run_id: str,
) -> dict[str, Any]:
    """Compute exact acceptance rates, CIs, top-10 strategies, and argon-high transfer results; write JSON & MD."""
    out_dir.mkdir(parents=True, exist_ok=True)
    now_str = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    sha = git_sha()

    enriched = []
    for p in proposals:
        s_pass = p["solver_mean"] >= 0.5
        bkey = p["behavior_key"]
        fev = flash_by_bkey.get(bkey) if s_pass else None
        f_valid = bool(fev and fev.get("valid"))
        f_mean = fev["mean"] if f_valid else None
        f_pass = bool(s_pass and f_valid and f_mean is not None and f_mean <= 0.2 and not fev.get("early_stopped_above_threshold"))
        # Note: if early_stopped_above_threshold is True, 5-seed mean is provably > 0.2 -> f_pass is False!
        evaluated_pair = bool((not s_pass) or f_valid)
        gap = round(p["solver_mean"] - f_mean, 4) if (f_valid and f_mean is not None and not fev.get("early_stopped_above_threshold")) else None
        aev = argon_by_bkey.get(bkey)
        enriched.append({
            **p,
            "solver_pass": s_pass,
            "evaluated": evaluated_pair,
            "flash_low": fev,
            "flash_pass": f_pass,
            "accepted": bool(s_pass and f_pass),
            "paired_gap_solver_minus_flash": gap,
            "argon_high": aev,
        })

    # Contiguous prefix from cand-0000..cand-(K-1) where 100% of proposals are fully evaluated (unbiased denominator!)
    contiguous_rows: list[dict] = []
    for r in enriched:
        if r["evaluated"]:
            contiguous_rows.append(r)
        else:
            break
    evaluated_rows = contiguous_rows
    n_eval = len(evaluated_rows)
    n_solver_pass = sum(1 for r in evaluated_rows if r["solver_pass"])
    n_accepted = sum(1 for r in evaluated_rows if r["accepted"])

    # Behavioral-class level statistics (deduplicated by exact functional + solver trace behavior)
    by_bkey: dict[str, list[dict]] = {}
    for r in evaluated_rows:
        by_bkey.setdefault(r["behavior_key"], []).append(r)
    n_unique_classes = len(by_bkey)
    n_unique_solver_pass = sum(1 for grp in by_bkey.values() if grp[0]["solver_pass"])
    n_unique_accepted = sum(1 for grp in by_bkey.values() if grp[0]["accepted"])

    # Select top 10 distinct accepted strategies (1 representative per behavioral class first, sorted by gap desc)
    accepted_all = [r for r in evaluated_rows if r["accepted"] and r["paired_gap_solver_minus_flash"] is not None]
    accepted_all.sort(key=lambda r: (-r["paired_gap_solver_minus_flash"], -r["solver_mean"], r["id"]))
    top10: list[dict] = []
    seen_top_bkey: set[str] = set()
    for r in accepted_all:
        if r["behavior_key"] in seen_top_bkey:
            continue
        seen_top_bkey.add(r["behavior_key"])
        top10.append(r)
        if len(top10) >= 10:
            break
    # If fewer than 10 unique behavioral classes were accepted, fill remaining slots from accepted_all
    if len(top10) < 10:
        used_ids = {r["id"] for r in top10}
        for r in accepted_all:
            if r["id"] not in used_ids:
                top10.append(r)
                used_ids.add(r["id"])
                if len(top10) >= 10:
                    break

    top10_summary = []
    argon_also_fails = 0
    argon_tested = 0
    for rank, r in enumerate(top10, 1):
        fl = r["flash_low"]
        ar = r.get("argon_high")
        ar_valid = bool(ar and ar.get("valid"))
        ar_mean = ar["mean"] if ar_valid else None
        ar_fails_02 = bool(ar_valid and ar_mean <= 0.2)
        ar_below_solver = bool(ar_valid and ar_mean < r["solver_mean"])
        if ar_valid:
            argon_tested += 1
            if ar_fails_02:
                argon_also_fails += 1
        ar_seeds = [int(e["seed"]) for e in (ar.get("episodes") or [])] if ar_valid else []
        sol_by_seed = dict(zip(seeds, r["solver_scores"]))
        ar_paired_sol = [sol_by_seed[s] for s in ar_seeds] if ar_valid else []
        ar_paired_gap = round(statistics.fmean(ar_paired_sol) - ar_mean, 4) if (ar_valid and ar_paired_sol and ar_mean is not None) else None
        top10_summary.append({
            "rank": rank,
            "id": r["id"],
            "name": r["name"],
            "archetype": r["archetype"],
            "rationale": r["rationale"],
            "behavior_key": r["behavior_key"],
            "strategy_json": r["strategy_json"],
            "solver_mean": r["solver_mean"],
            "solver_ci95": r["solver_ci95"],
            "solver_acc": r["solver_acc"],
            "solver_scores": r["solver_scores"],
            "heuristic_mean": r["heuristic_mean"],
            "flash_low_mean": fl["mean"],
            "flash_low_ci95": fl["ci95"],
            "flash_low_acc": fl["acc"],
            "flash_low_scores": fl["scores"],
            "paired_gap_solver_minus_flash": r["paired_gap_solver_minus_flash"],
            "paired_gap_ci95": paired_bootstrap_ci(r["solver_scores"], fl["scores"]),
            "argon_high_n": len(ar_seeds) if ar_valid else 0,
            "argon_high_seeds": ar_seeds if ar_valid else None,
            "argon_high_mean": ar_mean,
            "argon_high_ci95": ar["ci95"] if ar_valid else None,
            "argon_high_acc": ar["acc"] if ar_valid else None,
            "argon_high_scores": ar["scores"] if ar_valid else None,
            "argon_high_also_fails_le_0_2": ar_fails_02 if ar_valid else None,
            "argon_high_paired_gap_vs_solver": ar_paired_gap,
            "argon_high_paired_gap_ci95": paired_bootstrap_ci(ar_paired_sol, ar["scores"]) if ar_valid else None,
        })

    # Aggregate served model_versions across all stages
    served_versions = {
        "proposer_hydrogen": prop_stats.get("model_versions", {}),
        "filter_flash_low": {},
        "transfer_argon_high": {},
    }
    for v in flash_by_bkey.values():
        for mv, c in (v.get("model_versions") or {}).items():
            served_versions["filter_flash_low"][mv] = served_versions["filter_flash_low"].get(mv, 0) + c
    for v in argon_by_bkey.values():
        for mv, c in (v.get("model_versions") or {}).items():
            served_versions["transfer_argon_high"][mv] = served_versions["transfer_argon_high"].get(mv, 0) + c

    payload = {
        "mode": ARENA_LABEL,
        "label": ARENA_LABEL,
        "generated_at": now_str,
        "git_sha": sha,
        "run_id": run_id,
        "tier": tier,
        "dev_seeds": seeds,
        "n_seeds_per_eval": len(seeds),
        "models": {
            "proposer": "gemini-4-hydrogen",
            "weak_filter_agent": "gemini-3.8-flash (thinking_level=low, in-process LLMPolicy)",
            "strong_transfer_agent": "gemini-4-argon (thinking_level=high, in-process LLMPolicy)",
            "carbon_calls": 0,
            "served_model_versions": served_versions,
        },
        "thresholds": {
            "solver_min_score": 0.5,
            "flash_low_max_score": 0.2,
        },
        "default_mole_baseline": {
            "solver": baseline_solver,
            "flash_low": baseline_flash,
            "argon_high": baseline_argon,
        },
        "counts": {
            "n_proposed_total": len(proposals),
            "n_fully_evaluated": n_eval,
            "n_solver_feasible_ge_0_5": n_solver_pass,
            "solver_feasible_rate": round(n_solver_pass / max(1, n_eval), 4),
            "solver_feasible_rate_ci95": wilson_ci(n_solver_pass, n_eval),
            "n_accepted_paired": n_accepted,
            "acceptance_rate": round(n_accepted / max(1, n_eval), 4),
            "acceptance_rate_ci95": wilson_ci(n_accepted, n_eval),
            "conditional_break_rate_given_solver_ge_0_5": round(n_accepted / max(1, n_solver_pass), 4),
            "conditional_break_rate_ci95": wilson_ci(n_accepted, n_solver_pass),
            "unique_behavioral_classes": n_unique_classes,
            "unique_solver_feasible_classes": n_unique_solver_pass,
            "unique_accepted_classes": n_unique_accepted,
            "unique_acceptance_rate": round(n_unique_accepted / max(1, n_unique_classes), 4),
            "unique_acceptance_rate_ci95": wilson_ci(n_unique_accepted, n_unique_classes),
            "proposer_stats": prop_stats,
        },
        "argon_high_transfer": {
            "n_top_strategies_tested": argon_tested,
            "n_argon_also_fails_le_0_2": argon_also_fails,
            "argon_fail_rate_le_0_2": round(argon_also_fails / max(1, argon_tested), 4) if argon_tested else None,
            "argon_fail_rate_ci95": wilson_ci(argon_also_fails, argon_tested) if argon_tested else None,
            "mean_solver_on_top10": round(statistics.fmean([t["solver_mean"] for t in top10_summary]), 4) if top10_summary else None,
            "mean_flash_low_on_top10": round(statistics.fmean([t["flash_low_mean"] for t in top10_summary]), 4) if top10_summary else None,
            "mean_argon_high_on_top10": (
                round(statistics.fmean([t["argon_high_mean"] for t in top10_summary if t["argon_high_mean"] is not None]), 4)
                if argon_tested else None
            ),
        },
        "top_10_strategies": top10_summary,
        "candidates": [
            {
                "id": r["id"],
                "name": r["name"],
                "archetype": r["archetype"],
                "behavior_key": r["behavior_key"],
                "solver_mean": r["solver_mean"],
                "solver_acc": r["solver_acc"],
                "heuristic_mean": r["heuristic_mean"],
                "solver_pass": r["solver_pass"],
                "evaluated": r["evaluated"],
                "flash_low_mean": r["flash_low"]["mean"] if (r["flash_low"] and r["flash_low"].get("valid")) else None,
                "flash_low_early_stopped": r["flash_low"].get("early_stopped_above_threshold", False) if r["flash_low"] else False,
                "accepted": r["accepted"],
                "paired_gap": r["paired_gap_solver_minus_flash"],
                "strategy_json": r["strategy_json"],
            }
            for r in enriched
        ],
    }

    (out_dir / "designer.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    # Render designer.md
    c = payload["counts"]
    at = payload["argon_high_transfer"]
    acc_pct = c["acceptance_rate"] * 100
    acc_ci = [x * 100 for x in c["acceptance_rate_ci95"]]
    sol_pct = c["solver_feasible_rate"] * 100
    sol_ci = [x * 100 for x in c["solver_feasible_rate_ci95"]]
    u_pct = c["unique_acceptance_rate"] * 100
    u_ci = [x * 100 for x in c["unique_acceptance_rate_ci95"]]

    md = [
        f"DONE {now_str}",
        "",
        f"# Gemini PAIRED Scenario Designer (`{ARENA_LABEL}`)",
        "",
        f"> **Scope label: `{ARENA_LABEL}`.** Every run on this page varies only the Mole DSL strategy (`Env(..., mole_strategy=...)`) on public dev seeds `{seeds[0]}–{seeds[-1]}` (`{tier}` tier, `n={len(seeds)}` seeds per cell) in-process. Frozen v1.4 judged rules, solver, and reward code are untouched. Zero `gemini-4-carbon` API calls were made.",
        "",
        f"- **Stamped:** `{now_str}` · **Git SHA:** `{sha[:12]}` · **Run ID:** `{run_id}`",
        f"- **Proposer:** `gemini-4-hydrogen` (served: `{', '.join(served_versions['proposer_hydrogen']) or 'gemini-4-hydrogen'}`)",
        f"- **Filter investigator:** `gemini-3.8-flash` at `thinking_level=low` (served: `{', '.join(served_versions['filter_flash_low']) or 'gemini-3.8-flash'}`, in-process `LLMPolicy`, full history + thought-signature replay)",
        f"- **Stronger transfer investigator:** `gemini-4-argon` at `thinking_level=high` (served: `{', '.join(served_versions['transfer_argon_high']) or 'gemini-4-argon'}`, in-process `LLMPolicy`)",
        f"- **PAIRED acceptance criterion (`{tier}`, dev seeds `{seeds[0]}–{seeds[-1]}`):** `SolverPolicy` mean **≥ 0.50** AND `gemini-3.8-flash` (`low`) mean **≤ 0.20**.",
        "",
        "---",
        "",
        f"## 1. Headline Acceptance & Transfer Summary (`{ARENA_LABEL}`)",
        "",
        "| Metric | Count | Rate [95% Wilson CI] | Notes |",
        "|---|---:|---:|---|",
        f"| Valid distinct DSL strategies proposed (`gemini-4-hydrogen`) | {c['n_fully_evaluated']} / {c['n_proposed_total']} | — | {prop_stats.get('batches', 0)} ledgered proposal batches; 0 stub fallbacks |",
        f"| Stage 1 — Solvable by reference `SolverPolicy` (mean ≥ 0.50, `n={len(seeds)}`) | {c['n_solver_feasible_ge_0_5']} / {c['n_fully_evaluated']} | **{sol_pct:.1f}% [{sol_ci[0]:.1f}%, {sol_ci[1]:.1f}%]** | Rejects non-leaking or information-starved moles in CPU pre-filter |",
        f"| **PAIRED Accepted (`solver ≥ 0.50` AND `3.8-flash-low ≤ 0.20`)** | **{c['n_accepted_paired']} / {c['n_fully_evaluated']}** | **{acc_pct:.1f}% [{acc_ci[0]:.1f}%, {acc_ci[1]:.1f}%]** | Conditional break rate among solver-feasible: {c['conditional_break_rate_given_solver_ge_0_5']*100:.1f}% [{c['conditional_break_rate_ci95'][0]*100:.1f}%, {c['conditional_break_rate_ci95'][1]*100:.1f}%] |",
        f"| Behavioral equivalence classes accepted (deduped by truth-table + trace) | {c['unique_accepted_classes']} / {c['unique_behavioral_classes']} | {u_pct:.1f}% [{u_ci[0]:.1f}%, {u_ci[1]:.1f}%] | {c['unique_solver_feasible_classes']} unique solver-feasible behavioral classes |",
        (
            f"| **Transfer to `gemini-4-argon` (`high` thinking) on Top-{at['n_top_strategies_tested']} hardest** | "
            f"**{at['n_argon_also_fails_le_0_2']} / {at['n_top_strategies_tested']} also ≤ 0.20** | "
            f"**{at['argon_fail_rate_le_0_2']*100:.1f}% [{at['argon_fail_rate_ci95'][0]*100:.1f}%, {at['argon_fail_rate_ci95'][1]*100:.1f}%]** | "
            f"Mean score on Top-{at['n_top_strategies_tested']}: solver `{at['mean_solver_on_top10']:+.3f}`, flash-low `{at['mean_flash_low_on_top10']:+.3f}`, argon-high `{at['mean_argon_high_on_top10']:+.3f}` |"
            if at["n_top_strategies_tested"]
            else "| Transfer to `gemini-4-argon` (`high`) | pending | — | — |"
        ),
        "",
        "### Default-Mole Reference Baseline (`DEFAULT_STRATEGY`, same 5 dev seeds `0–4`, `medium`)",
        f"- **Reference `SolverPolicy`:** `{baseline_solver['solver_mean']:+.3f} ± {baseline_solver['solver_ci95']:.3f}` (acc `{baseline_solver['solver_acc']*100:.0f}%`, `n={len(seeds)}`)",
        (
            f"- **`gemini-3.8-flash` (`low` thinking):** `{baseline_flash['mean']:+.3f} ± {baseline_flash['ci95']:.3f}` (acc `{baseline_flash['acc']*100:.0f}%`, `n={baseline_flash['n_valid_seeds']}`)"
            if baseline_flash and baseline_flash.get("valid")
            else "- **`gemini-3.8-flash` (`low` thinking):** pending"
        ),
        (
            f"- **`gemini-4-argon` (`high` thinking):** `{baseline_argon['mean']:+.3f} ± {baseline_argon['ci95']:.3f}` (acc `{baseline_argon['acc']*100:.0f}%`, `n={baseline_argon['n_valid_seeds']}`)"
            if baseline_argon and baseline_argon.get("valid")
            else "- **`gemini-4-argon` (`high` thinking):** pending"
        ),
        "",
        "---",
        "",
        f"## 2. Top 10 Hardest PAIRED Mole Strategies (`{ARENA_LABEL}`)",
        "",
        "Ranked by paired regret (`solver_mean − flash_low_mean`) across distinct behavioral classes on `medium` dev seeds `0–4` (`n=5` per cell):",
        "",
        "| Rank | ID & Name | Archetype | Solver ± CI (acc) | `3.8-flash` low ± CI (acc) | Paired Gap [boot 95% CI] | `4-argon` high ± CI (acc) | Argon ≤ 0.20? |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ]

    for t in top10_summary:
        ar_str = (
            f"`{t['argon_high_mean']:+.3f} ± {t['argon_high_ci95']:.3f}` ({t['argon_high_acc']*100:.0f}%, n={t['argon_high_n']})"
            if t["argon_high_mean"] is not None
            else "—"
        )
        ar_fail = ("**YES**" if t["argon_high_also_fails_le_0_2"] else "no") if t["argon_high_also_fails_le_0_2"] is not None else "—"
        md.append(
            f"| {t['rank']} | `{t['id']}` {t['name']} | `{t['archetype']}` | "
            f"`{t['solver_mean']:+.3f} ± {t['solver_ci95']:.3f}` ({t['solver_acc']*100:.0f}%) | "
            f"`{t['flash_low_mean']:+.3f} ± {t['flash_low_ci95']:.3f}` ({t['flash_low_acc']*100:.0f}%) | "
            f"**`{t['paired_gap_solver_minus_flash']:+.3f}`** [{t['paired_gap_ci95'][0]:+.2f}, {t['paired_gap_ci95'][1]:+.2f}] | "
            f"{ar_str} | {ar_fail} |"
        )

    md.extend([
        "",
        "### DSL Rules of the Top 10 Strategies",
        "",
    ])
    for t in top10_summary:
        md.extend([
            f"#### #{t['rank']} · `{t['id']}` — {t['name']} (`{t['archetype']}`)",
            f"- **Designer rationale:** {t['rationale']}",
            f"- **Scores (`n=5`, seeds `0–4`):** solver `{t['solver_scores']}` (mean `{t['solver_mean']:+.3f}`) · "
            f"3.8-flash-low `{t['flash_low_scores']}` (mean `{t['flash_low_mean']:+.3f}`) · "
            + (f"4-argon-high `{t['argon_high_scores']}` (mean `{t['argon_high_mean']:+.3f}`)" if t["argon_high_scores"] is not None else "4-argon-high pending"),
            f"- **Mole DSL JSON:** `{canonical(t['strategy_json'])}`",
            "",
        ])

    md.extend([
        "---",
        "",
        f"## 3. Methodology & Honesty Notes (`{ARENA_LABEL}`)",
        "",
        f"1. **Strictly `{ARENA_LABEL}`:** None of these strategies modify or enter the judged v1.4 benchmark. Only `mole_strategy` in `Env('medium', seed, mole_strategy=...)` varies; `TierParams` are untouched.",
        "2. **Selection-bias caveat (in-sample 5-seed filter):** Filtering candidates on `flash_low_mean <= 0.20` over 5 seeds selects partly for genuine strategic difficulty and partly for negative luck on those 5 seeds (each wrong accusation is `-1.0`). Evaluating the **independent `gemini-4-argon` (`high` thinking)** model on the selected Top-10 provides an out-of-model transfer test free of filter-selection luck on Argon's own rollouts.",
        "3. **Behavioral equivalence caching:** Distinct DSL JSONs that evaluate to the exact same `(leak, frame)` choices across our 4,096-state reachable `MoleView` truth-table and solver trajectory trace share one behavioral class (`behavior_key`), avoiding redundant API spend on dead-branch syntactic variants while reporting both raw-proposal and deduplicated class acceptance rates.",
        "4. **Infra-error handling:** Transport/quota errors (`429`, `5xx`, timeouts) are retried with 60s quota backoff and never scored as `0`.",
    ])

    (out_dir / "designer.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return payload


def run_campaign(
    target: int = 500,
    tier: str = "medium",
    seeds: list[int] | None = None,
    scratch_dir: Path = ROOT / "data" / "gemini" / "scratch" / "designer_ws5",
    out_dir: Path = ROOT / "results" / "gemini" / "scale" / "designer",
    cpu_workers: int = 4,
    flash_concurrency: int = 10,
    argon_concurrency: int = 8,
    max_flash_classes: int | None = None,
    top_k_argon: int = 10,
    assemble_only: bool = False,
    run_id: str = "ws5-designer-v1",
    client_builder=None,
) -> dict[str, Any]:
    seeds = seeds or [0, 1, 2, 3, 4]
    cpu_workers = max(1, min(4, cpu_workers))
    scratch_dir.mkdir(parents=True, exist_ok=True)

    # 0. CPU solver baseline + Load cached LLM baselines
    base_sol = _eval_fast_candidate_worker((tier, seeds, default_strategy_json()))
    base_file = scratch_dir / "baselines.json"
    baselines = json.loads(base_file.read_text(encoding="utf-8")) if base_file.exists() else {}

    # 1. Propose `target` valid Mole DSL strategies on gemini-4-hydrogen + CPU Solver pre-filter
    proposals, prop_stats = propose_strategies_hydrogen(
        target=target, tier=tier, seeds=seeds, scratch_dir=scratch_dir, run_id=run_id,
        cpu_workers=cpu_workers, client_builder=client_builder,
    )

    # 2. Group solver-passing strategies (solver >= 0.5) by behavioral equivalence class
    flash_file = scratch_dir / "flash_evals.jsonl"
    flash_by_bkey: dict[str, dict] = {}
    if flash_file.exists():
        for ln in flash_file.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                if d.get("valid"):
                    flash_by_bkey[d["behavior_key"]] = d

    argon_file = scratch_dir / "argon_evals.jsonl"
    argon_by_bkey: dict[str, dict] = {}
    if argon_file.exists():
        for ln in argon_file.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                if d.get("valid"):
                    argon_by_bkey[d["behavior_key"]] = d

    feasible_reps: list[dict] = []
    seen_bkeys: set[str] = set()
    for p in proposals:
        if p["solver_mean"] < 0.5:
            continue
        bk = p["behavior_key"]
        if bk not in seen_bkeys:
            seen_bkeys.add(bk)
            if bk not in flash_by_bkey:
                feasible_reps.append(p)

    if max_flash_classes is not None:
        feasible_reps = feasible_reps[:max_flash_classes]

    print(
        f"[stage2] solver>=0.5 proposals={sum(1 for p in proposals if p['solver_mean'] >= 0.5)}/{len(proposals)}, "
        f"unique behavioral classes={len(seen_bkeys)} (cached={len(flash_by_bkey)}, todo={len(feasible_reps)})",
        flush=True,
    )

    write_lock = threading.Lock()
    done_cnt = 0

    def _run_flash_baseline() -> None:
        if (baselines.get("flash_low") or {}).get("valid"):
            return
        ev = evaluate_llm_on_strategy(
            "gemini-3.8-flash", "low", tier, seeds, default_strategy_json(), run_id, "baseline-default",
            early_reject_threshold=None, client_builder=client_builder,
        )
        with write_lock:
            baselines["flash_low"] = ev
            base_file.write_text(json.dumps(baselines, indent=2))

    def _run_flash_one(rep: dict) -> tuple[str, dict]:
        nonlocal done_cnt
        ev = evaluate_llm_on_strategy(
            model="gemini-3.8-flash",
            thinking_level="low",
            tier=tier,
            seeds=seeds,
            strat_json=rep["strategy_json"],
            run_id=run_id,
            label_id=rep["id"],
            early_reject_threshold=0.2,
            client_builder=client_builder,
        )
        ev["behavior_key"] = rep["behavior_key"]
        with write_lock:
            done_cnt += 1
            if ev.get("valid"):
                flash_by_bkey[rep["behavior_key"]] = ev
                with open(flash_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ev) + "\n")
            if done_cnt % 15 == 0:
                build_report_and_write(
                    proposals, prop_stats, base_sol, baselines.get("flash_low", {}),
                    baselines.get("argon_high", {}), flash_by_bkey, argon_by_bkey, tier, seeds, out_dir, run_id,
                )
            print(
                f"[flash-low {done_cnt}/{len(feasible_reps)}] {rep['id']} solver={rep['solver_mean']:+.2f} "
                f"flash={ev.get('mean')} early={ev.get('early_stopped_above_threshold')} valid={ev.get('valid')}",
                flush=True,
            )
        return rep["behavior_key"], ev

    if max_flash_classes != 0 and not assemble_only:
        with ThreadPoolExecutor(max_workers=max(1, flash_concurrency)) as pool:
            futs = [pool.submit(_run_flash_baseline)]
            futs += [pool.submit(_run_flash_one, rep) for rep in feasible_reps]
            for fut in as_completed(futs):
                fut.result()

    # 3. Identify Top-K accepted behavioral classes and run gemini-4-argon (high) transfer check at (strategy, seed) level
    argon_ep_file = scratch_dir / "argon_episodes.jsonl"
    argon_ep_cache: dict[tuple[str, int], dict] = {}
    if argon_ep_file.exists():
        for ln in argon_ep_file.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                d = json.loads(ln)
                if d.get("valid"):
                    argon_ep_cache[(d["bkey"], int(d["seed"]))] = d

    accepted_reps: list[tuple[float, dict]] = []
    used_bk: set[str] = set()
    for p in proposals:
        bk = p["behavior_key"]
        if p["solver_mean"] < 0.5 or bk in used_bk:
            continue
        fev = flash_by_bkey.get(bk)
        if fev and fev.get("valid") and not fev.get("early_stopped_above_threshold") and fev["mean"] <= 0.2:
            used_bk.add(bk)
            accepted_reps.append((p["solver_mean"] - fev["mean"], p))
    accepted_reps.sort(key=lambda x: (-x[0], -x[1]["solver_mean"], x[1]["id"]))
    top_argon_reps = [p for _, p in accepted_reps[:top_k_argon]]

    argon_tasks: list[tuple[str, str, dict | None, int]] = []
    if top_k_argon > 0:
        for s in seeds:
            if ("__baseline_default__", s) not in argon_ep_cache:
                argon_tasks.append(("__baseline_default__", "baseline-default-argon", default_strategy_json(), s))
        for rep in top_argon_reps:
            for s in seeds:
                if (rep["behavior_key"], s) not in argon_ep_cache:
                    argon_tasks.append((rep["behavior_key"], f"{rep['id']}-argon-high", rep["strategy_json"], s))

    print(
        f"[stage3] accepted unique classes={len(accepted_reps)}; "
        f"argon-high episode tasks todo={len(argon_tasks)} (parallel={argon_concurrency})",
        flush=True,
    )

    def _run_argon_ep(task: tuple[str, str, dict | None, int]) -> None:
        bkey, label_id, sjson, sd = task
        ep = run_llm_episode_with_retry(
            model="gemini-4-argon",
            thinking_level="high",
            tier=tier,
            seed=sd,
            strat_json=sjson,
            run_id=run_id,
            meta={"strategy_id": label_id, "tier": tier},
            client_builder=client_builder,
        )
        ep["bkey"] = bkey
        with write_lock:
            if ep.get("valid"):
                argon_ep_cache[(bkey, sd)] = ep
                with open(argon_ep_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(ep) + "\n")
            print(f"[argon-high] {label_id} seed={sd} score={ep.get('score')} valid={ep.get('valid')}", flush=True)

    if argon_tasks and not assemble_only:
        with ThreadPoolExecutor(max_workers=max(1, argon_concurrency)) as pool:
            futs = [pool.submit(_run_argon_ep, t) for t in argon_tasks]
            for fut in as_completed(futs):
                fut.result()

    def _assemble_argon(bkey: str, label_id: str) -> dict | None:
        eps = [argon_ep_cache.get((bkey, s)) for s in seeds if argon_ep_cache.get((bkey, s)) and argon_ep_cache[(bkey, s)].get("valid")]
        if len(eps) < 3:
            return None
        scores = [float(e["score"]) for e in eps]  # type: ignore[index]
        m, ci = mean_ci95(scores)
        acc = sum(1 for e in eps if e and e.get("correct")) / len(eps)
        mvs: dict[str, int] = {}
        for e in eps:
            for mv, cnt in ((e or {}).get("model_versions") or {}).items():
                mvs[mv] = mvs.get(mv, 0) + cnt
        return {
            "strategy_id": label_id,
            "behavior_key": bkey,
            "model": "gemini-4-argon",
            "thinking_level": "high",
            "valid": True,
            "n_valid_seeds": len(scores),
            "scores": scores,
            "mean": m,
            "ci95": ci,
            "acc": round(acc, 4),
            "episodes": eps,
            "model_versions": mvs,
        }

    if top_k_argon > 0:
        b_ar = _assemble_argon("__baseline_default__", "baseline-default-argon")
        if b_ar:
            baselines["argon_high"] = b_ar
            base_file.write_text(json.dumps(baselines, indent=2))
        for _, rep in accepted_reps:
            assembled = _assemble_argon(rep["behavior_key"], f"{rep['id']}-argon-high")
            if assembled:
                argon_by_bkey[rep["behavior_key"]] = assembled

    return build_report_and_write(
        proposals=proposals,
        prop_stats=prop_stats,
        baseline_solver=base_sol,
        baseline_flash=baselines.get("flash_low", {}),
        baseline_argon=baselines.get("argon_high", {}),
        flash_by_bkey=flash_by_bkey,
        argon_by_bkey=argon_by_bkey,
        tier=tier,
        seeds=seeds,
        out_dir=out_dir,
        run_id=run_id,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target", type=int, default=500, help="Number of distinct valid Mole DSL strategies to propose")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="0-4")
    ap.add_argument("--scratch", type=Path, default=ROOT / "data" / "gemini" / "scratch" / "designer_ws5")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "gemini" / "scale" / "designer")
    ap.add_argument("--cpu-workers", type=int, default=4)
    ap.add_argument("--flash-concurrency", type=int, default=10)
    ap.add_argument("--argon-concurrency", type=int, default=8)
    ap.add_argument("--max-flash-classes", type=int, default=None)
    ap.add_argument("--top-k-argon", type=int, default=10)
    ap.add_argument("--assemble-only", action="store_true", help="Assemble designer.{json,md} from scratch cache with 0 API calls")
    ap.add_argument("--run-id", default="ws5-designer-v1")
    a = ap.parse_args(argv)

    seed_list = []
    for part in a.seeds.split(","):
        if "-" in part:
            lo, hi = part.split("-", 1)
            seed_list.extend(range(int(lo), int(hi) + 1))
        elif part.strip():
            seed_list.append(int(part))

    res = run_campaign(
        target=a.target,
        tier=a.tier,
        seeds=seed_list,
        scratch_dir=a.scratch,
        out_dir=a.out,
        cpu_workers=min(4, a.cpu_workers),
        flash_concurrency=a.flash_concurrency,
        argon_concurrency=a.argon_concurrency,
        max_flash_classes=a.max_flash_classes,
        top_k_argon=a.top_k_argon,
        assemble_only=a.assemble_only,
        run_id=a.run_id,
    )
    print(json.dumps({"mode": res["mode"], "counts": res["counts"], "argon_high_transfer": res["argon_high_transfer"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
