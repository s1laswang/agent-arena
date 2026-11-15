"""Distill gemini-4-carbon mole transcripts into catchable MoleStrategy rulesets."""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import random
import subprocess
import time
from typing import Any

from canary import forge_track, rules
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.rl_mole import RLMole, _agent
from canary.mole.dsl import (
    DEFAULT_STRATEGY,
    FEATURES,
    FRAME_SELECTORS,
    LEAK_SELECTORS,
    OPS,
    MoleStrategy,
    MoleView,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BARE_REPO = Path("/home/silas/momin/fleet/repos/agent-arena.git")
DEFAULT_GIT_REFS = (
    "refs/remotes/github/fr8/gemini/mole",
    "refs/heads/fr8/gemini/mole",
    "refs/heads/gemini-track",
)
TRANSCRIPT_PREFIX = "results/gemini_roles/adaptive_mole/"
AGENTS = ("solver", "grok_tactics", "heuristic", "hinted_heuristic")
HEURISTIC_AGENTS = ("grok_tactics", "heuristic", "hinted_heuristic")
TRAIN_SEED_RANGE = range(140_000, 140_040)
HELDOUT_200K_RANGE = range(200_000, 200_050)
HELDOUT_800K_RANGE = range(800_000, 800_050)
DEFAULT_HOF_OUT = ROOT / "data" / "forge" / "hall_of_fame_carbon_distilled.jsonl"
DEFAULT_EVAL_OUT = ROOT / "results" / "moletrain" / "carbon_distilled_dsl_eval.json"
DEFAULT_RL_POLICY = ROOT / "data" / "rl_mole" / "policy_final.json"
MAX_DISTILLED_RULES = 8
HOF_SIZE = 5
MIN_TRAIN_SOLVER_ACC = 0.88
MIN_TRAIN_SOLVER_RATIO = 0.5
CATCHABLE_ACC_FLOOR = 0.85


def shannon_entropy_bits(counts: Counter[Any] | dict[Any, int | float]) -> float:
    vals = [float(v) for v in counts.values() if v > 0]
    tot = sum(vals)
    if tot <= 0:
        return 0.0
    return -sum((v / tot) * math.log2(v / tot) for v in vals)


def map_turn_to_selectors(turn: dict[str, Any]) -> tuple[str, str]:
    mv = turn.get("mole_view") or {}
    docs = list(mv.get("held_docs") or mv.get("docs") or [])
    leak_id = turn.get("leak")
    if not docs or leak_id is None:
        leak_sel = "none"
    else:
        chosen = next((d for d in docs if d.get("doc_id") == leak_id), None)
        if chosen is None:
            leak_sel = "random_seeded"
        else:
            rc_vals = [int(d["recipient_count"]) for d in docs]
            age_vals = [int(d["age_days"]) for d in docs]
            max_rc, min_rc = max(rc_vals), min(rc_vals)
            max_age, min_age = max(age_vals), min(age_vals)
            most_id = min(docs, key=lambda d: -int(d["recipient_count"]))["doc_id"]
            oldest_id = min(docs, key=lambda d: -int(d["age_days"]))["doc_id"]
            newest_id = min(docs, key=lambda d: int(d["age_days"]))["doc_id"]
            fewest_id = min(docs, key=lambda d: int(d["recipient_count"]))["doc_id"]
            if leak_id == most_id and int(chosen["recipient_count"]) == max_rc:
                leak_sel = "most_recipients"
            elif max_age > min_age and leak_id == oldest_id:
                leak_sel = "oldest"
            elif max_age > min_age and leak_id == newest_id:
                leak_sel = "newest"
            elif max_rc > min_rc and leak_id == fewest_id:
                leak_sel = "fewest_recipients"
            else:
                leak_sel = "random_seeded"

    frame_id = turn.get("frame")
    decoy = mv.get("decoy")
    restricted_peers = set(mv.get("restricted_peers") or ())
    peers = set(mv.get("peers") or ())
    if not frame_id:
        frame_sel = "none"
    elif decoy and frame_id == decoy:
        frame_sel = "decoy"
    elif frame_id in restricted_peers:
        frame_sel = "most_restricted_peer"
    elif frame_id in peers:
        frame_sel = "random_peer"
    else:
        frame_sel = "none"
    return leak_sel, frame_sel


def load_carbon_turns(
    jsonl_dir: str | Path | None = None,
    bare_repo: str | Path = DEFAULT_BARE_REPO,
    refs: tuple[str, ...] = DEFAULT_GIT_REFS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if jsonl_dir is not None:
        base = Path(jsonl_dir)
        files = sorted(base.rglob("mole_decisions.jsonl"))
        if not files:
            files = sorted(base.glob("*.jsonl"))
        turns: list[dict[str, Any]] = []
        for fp in files:
            for line in fp.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    turns.append(json.loads(line))
        return turns, {
            "mode": "jsonl_dir",
            "path": str(base),
            "n_files": len(files),
            "files": [str(fp.relative_to(base)) for fp in files],
        }

    local_dir = ROOT / "results" / "gemini_roles" / "adaptive_mole"
    if local_dir.is_dir():
        local_files = sorted(local_dir.glob("*/mole_decisions.jsonl"))
        if local_files:
            turns = []
            for fp in local_files:
                for line in fp.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        turns.append(json.loads(line))
            return turns, {
                "mode": "workspace",
                "path": str(local_dir),
                "n_files": len(local_files),
                "files": [str(fp.relative_to(ROOT)) for fp in local_files],
            }

    repo = Path(bare_repo)
    if repo.exists():
        for ref in refs:
            ls_proc = subprocess.run(
                ["git", f"--git-dir={repo}", "ls-tree", "-r", "--name-only", ref, TRANSCRIPT_PREFIX],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if ls_proc.returncode != 0:
                continue
            rel_files = sorted(
                f for f in ls_proc.stdout.splitlines() if f.endswith("/mole_decisions.jsonl")
            )
            if not rel_files:
                continue
            turns = []
            for rel in rel_files:
                show_proc = subprocess.run(
                    ["git", f"--git-dir={repo}", "show", f"{ref}:{rel}"],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
                for line in show_proc.stdout.splitlines():
                    if line.strip():
                        turns.append(json.loads(line))
            if turns:
                return turns, {
                    "mode": "git_bare_repo",
                    "bare_repo": str(repo),
                    "ref": ref,
                    "n_files": len(rel_files),
                    "files": rel_files,
                }
    raise FileNotFoundError("No gemini-4-carbon mole_decisions.jsonl transcripts found")


def _quantile(vals: list[int | float], q: float, default: int) -> int:
    if not vals:
        return default
    sv = sorted(vals)
    idx = min(len(sv) - 1, max(0, int(q * (len(sv) - 1))))
    return int(round(sv[idx]))


def extract_turn_statistics(turns: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier: Counter[str] = Counter()
    leak_counts: Counter[str] = Counter()
    frame_counts: Counter[str] = Counter()
    pair_counts: Counter[str] = Counter()
    withhold_max_rc: list[int] = []
    leaked_chosen_rc: list[int] = []
    low_rc_withhold = 0
    low_rc_total = 0
    narrow_most_rc = 0
    narrow_total = 0
    restricted_peer_turns = 0

    for t in turns:
        tier = str(t.get("tier") or "unknown")
        by_tier[tier] += 1
        lsel, fsel = map_turn_to_selectors(t)
        leak_counts[lsel] += 1
        frame_counts[fsel] += 1
        pair_counts[f"{lsel}/{fsel}"] += 1
        mv = t.get("mole_view") or {}
        docs = list(mv.get("held_docs") or mv.get("docs") or [])
        if int(mv.get("n_restricted_colleagues") or 0) >= 1:
            restricted_peer_turns += 1
        if docs:
            max_rc = max(int(d["recipient_count"]) for d in docs)
            min_rc = min(int(d["recipient_count"]) for d in docs)
            dsll = int(mv.get("days_since_last_leak", mv.get("day", 1)))
            if max_rc <= 6 and dsll <= 2:
                low_rc_total += 1
                if lsel == "none":
                    low_rc_withhold += 1
            if min_rc <= 2 and max_rc >= 8:
                narrow_total += 1
                if lsel == "most_recipients":
                    narrow_most_rc += 1
            if lsel == "none":
                withhold_max_rc.append(max_rc)
            else:
                ch = next((d for d in docs if d.get("doc_id") == t.get("leak")), None)
                if ch is not None:
                    leaked_chosen_rc.append(int(ch["recipient_count"]))

    p90_withhold = _quantile(withhold_max_rc, 0.90, 6)
    withhold_hi = max(5, min(6, p90_withhold if p90_withhold >= 5 else 6))
    withhold_lo = max(4, withhold_hi - 1)
    p10_leak_rc = _quantile(leaked_chosen_rc, 0.10, 8)
    mid_lo = max(7, min(9, p10_leak_rc - 1 if p10_leak_rc >= 8 else 8))
    p50_leak_rc = _quantile(leaked_chosen_rc, 0.50, 14)
    mid_hi = max(12, min(14, p50_leak_rc - 1))

    return {
        "n_turns": len(turns),
        "by_tier": dict(sorted(by_tier.items())),
        "leak_selector_counts": {k: leak_counts[k] for k in LEAK_SELECTORS if leak_counts[k] > 0},
        "frame_selector_counts": {k: frame_counts[k] for k in FRAME_SELECTORS if frame_counts[k] > 0},
        "top_selector_pairs": dict(pair_counts.most_common(8)),
        "action_entropy_bits": {
            "leak": round(shannon_entropy_bits(leak_counts), 4),
            "frame": round(shannon_entropy_bits(frame_counts), 4),
            "joint": round(shannon_entropy_bits(pair_counts), 4),
        },
        "conditional_rates": {
            "withhold_when_max_rc_le_6_and_dsll_le_2": round(
                low_rc_withhold / max(1, low_rc_total), 4
            ),
            "most_recipients_when_min_rc_le_2_and_max_rc_ge_8": round(
                narrow_most_rc / max(1, narrow_total), 4
            ),
            "restricted_colleagues_turn_share": round(
                restricted_peer_turns / max(1, len(turns)), 4
            ),
        },
        "thresholds": {
            "withhold_max_rc_hi": withhold_hi,
            "withhold_max_rc_lo": withhold_lo,
            "narrow_probe_rc": 2,
            "mid_cover_rc_lo": mid_lo,
            "mid_cover_rc_hi": mid_hi,
            "wide_cover_rc": 35,
        },
    }


def rule_structure_signature(strategy_json: dict[str, Any]) -> tuple[Any, ...]:
    rules_part = tuple(
        (
            tuple((c[0], c[1]) for c in r["if"]),
            r["then"]["leak"],
            r["then"]["frame"],
        )
        for r in strategy_json.get("rules", [])
    )
    d = strategy_json.get("default", {"leak": "random_seeded", "frame": "none"})
    return (rules_part, (d["leak"], d["frame"]))


def distill_candidates(stats: dict[str, Any]) -> list[dict[str, Any]]:
    th = stats.get("thresholds") or {}
    w_hi = int(th.get("withhold_max_rc_hi", 6))
    w_lo = int(th.get("withhold_max_rc_lo", 5))
    narrow = int(th.get("narrow_probe_rc", 2))
    mid_lo = int(th.get("mid_cover_rc_lo", 8))
    mid_hi = int(th.get("mid_cover_rc_hi", 13))
    wide = int(th.get("wide_cover_rc", 35))

    raw = [
        {
            "name": "carbon_distilled_shield_v1",
            "rules": [
                {
                    "if": [["max_recipient_count", "<=", w_hi], ["days_since_last_leak", "<=", 2]],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "if": [["min_recipient_count", "<=", narrow]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
                {
                    "if": [["n_restricted_colleagues", ">=", 1]],
                    "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
                },
                {
                    "if": [["max_recipient_count", ">=", wide]],
                    "then": {"leak": "oldest", "frame": "decoy"},
                },
                {
                    "if": [["min_recipient_count", ">=", mid_lo], ["min_recipient_count", "<=", mid_hi]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
        {
            "name": "carbon_distilled_self_guard_v2",
            "rules": [
                {
                    "if": [["max_recipient_count", "<=", w_lo], ["days_since_last_leak", "<=", 2]],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "if": [["i_am_restricted", "==", 1], ["days_since_last_leak", "<=", 1]],
                    "then": {"leak": "none", "frame": "most_restricted_peer"},
                },
                {
                    "if": [["min_recipient_count", "<=", narrow]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
                {
                    "if": [["n_restricted_colleagues", ">=", 1]],
                    "then": {"leak": "oldest", "frame": "random_peer"},
                },
                {
                    "if": [["min_recipient_count", ">=", mid_lo], ["min_recipient_count", "<=", mid_hi + 1]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
        {
            "name": "carbon_distilled_oldest_deflect_v3",
            "rules": [
                {
                    "if": [["max_recipient_count", "<=", w_hi], ["days_since_last_leak", "<=", 2]],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "if": [["min_recipient_count", "<=", narrow]],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
                {
                    "if": [["n_restricted_colleagues", ">=", 1]],
                    "then": {"leak": "oldest", "frame": "most_restricted_peer"},
                },
                {
                    "if": [["min_recipient_count", ">=", mid_lo], ["min_recipient_count", "<=", mid_hi]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
        {
            "name": "carbon_distilled_decoy_anchor_v4",
            "rules": [
                {
                    "if": [["max_recipient_count", "<=", w_lo], ["days_since_last_leak", "<=", 2]],
                    "then": {"leak": "none", "frame": "random_peer"},
                },
                {
                    "if": [["min_recipient_count", "<=", narrow]],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
                {
                    "if": [["i_am_restricted", "==", 1], ["days_since_last_leak", "<=", 1]],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "if": [["n_restricted_colleagues", ">=", 1]],
                    "then": {"leak": "most_recipients", "frame": "most_restricted_peer"},
                },
                {
                    "if": [
                        ["n_leakable", ">=", 3],
                        ["min_recipient_count", ">=", mid_lo],
                        ["min_recipient_count", "<=", mid_hi],
                    ],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
                {
                    "if": [["max_recipient_count", ">=", wide - 2]],
                    "then": {"leak": "newest", "frame": "decoy"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
        {
            "name": "carbon_distilled_inventory_v5",
            "rules": [
                {
                    "if": [["max_recipient_count", "<=", w_hi], ["days_since_last_leak", "<=", 2]],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "if": [["min_recipient_count", "<=", narrow], ["n_docs_held", ">=", 2]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
                {
                    "if": [["n_restricted_colleagues", ">=", 2]],
                    "then": {"leak": "oldest", "frame": "most_restricted_peer"},
                },
                {
                    "if": [["n_docs_held", ">=", 4], ["max_recipient_count", ">=", 28]],
                    "then": {"leak": "oldest", "frame": "random_peer"},
                },
                {
                    "if": [["min_recipient_count", ">=", mid_lo], ["min_recipient_count", "<=", mid_hi - 1]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "random_peer"},
        },
        {
            "name": "carbon_distilled_day_pivot_v6",
            "rules": [
                {
                    "if": [["max_recipient_count", "<=", w_lo], ["days_since_last_leak", "<=", 1]],
                    "then": {"leak": "none", "frame": "decoy"},
                },
                {
                    "if": [["min_recipient_count", "<=", narrow]],
                    "then": {"leak": "oldest", "frame": "random_peer"},
                },
                {
                    "if": [["n_restricted_colleagues", ">=", 1], ["day", ">=", 4]],
                    "then": {"leak": "most_recipients", "frame": "decoy"},
                },
                {
                    "if": [["newest_doc_age_days", "==", 0], ["min_recipient_count", ">=", mid_lo + 1]],
                    "then": {"leak": "most_recipients", "frame": "random_peer"},
                },
                {
                    "if": [["max_recipient_count", ">=", wide - 1]],
                    "then": {"leak": "newest", "frame": "most_restricted_peer"},
                },
            ],
            "default": {"leak": "random_seeded", "frame": "decoy"},
        },
    ]

    validated: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_sigs: set[tuple[Any, ...]] = set()
    for item in raw:
        st = MoleStrategy.from_json(item)
        if len(st.rules) > MAX_DISTILLED_RULES:
            raise ValueError(f"Strategy {st.name} exceeds {MAX_DISTILLED_RULES} rules")
        sj = st.to_json()
        sig = rule_structure_signature(sj)
        if st.name in seen_names or sig in seen_sigs:
            raise ValueError(f"Duplicate strategy name or structure: {st.name}")
        seen_names.add(st.name)
        seen_sigs.add(sig)
        validated.append(sj)
    return validated


class TracingMoleStrategy:
    def __init__(self, strategy: MoleStrategy, trace: list[tuple[str, str, str, str]]):
        self.strategy = strategy
        self.trace = trace
        self.name = strategy.name

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, Any]:
        leak_sel, frame_sel = self.strategy.default
        for conds, then in self.strategy.rules:
            if all(OPS[op](view.feature(f), n) for f, op, n in conds):
                leak_sel, frame_sel = then
                break
        out = self.strategy.decide(view, rng)
        realized_leak = "leak" if out.get("leak") is not None else "none"
        frame_val = out.get("frame")
        if frame_val is None:
            realized_frame = "none"
        elif view.decoy and frame_val == view.decoy:
            realized_frame = "decoy"
        elif frame_val in view.restricted_peers:
            realized_frame = "restricted_peer"
        else:
            realized_frame = "peer"
        self.trace.append((leak_sel, frame_sel, realized_leak, realized_frame))
        return out


class TracingRLMole:
    def __init__(self, base_policy: RLMole, trace: list[tuple[str, str, str, str]]):
        self.base_policy = base_policy
        self.trace = trace
        self.name = base_policy.name

    def decide(self, view: MoleView, rng: random.Random) -> dict[str, Any]:
        inner_trace: list[Any] = []
        episode_mole = RLMole(
            self.base_policy.p,
            greedy=self.base_policy.greedy,
            trace=inner_trace,
            name=self.base_policy.name,
        )
        out = episode_mole.decide(view, rng)
        _, li, fi = inner_trace[-1]
        leak_sel = LEAK_SELECTORS[li]
        frame_sel = FRAME_SELECTORS[fi]
        realized_leak = "leak" if out.get("leak") is not None else "none"
        frame_val = out.get("frame")
        if frame_val is None:
            realized_frame = "none"
        elif view.decoy and frame_val == view.decoy:
            realized_frame = "decoy"
        elif frame_val in view.restricted_peers:
            realized_frame = "restricted_peer"
        else:
            realized_frame = "peer"
        self.trace.append((leak_sel, frame_sel, realized_leak, realized_frame))
        return out


def _rollout_seed_agents(
    tier: str,
    seed: int,
    mole_key: str,
    mole_builder: Any,
    agents: tuple[str, ...],
    memo: dict[tuple[str, int, str, str], tuple[float, bool, list[tuple[str, str, str, str]]]],
) -> dict[str, tuple[float, bool, list[tuple[str, str, str, str]]]]:
    row: dict[str, tuple[float, bool, list[tuple[str, str, str, str]]]] = {}
    for ag in agents:
        cache_key = (tier, seed, mole_key, ag)
        if cache_key not in memo:
            trace: list[tuple[str, str, str, str]] = []
            mole_obj = mole_builder(trace)
            res = run_episode(Env(tier, seed, mole_strategy=mole_obj), _agent(ag, tier, seed))
            memo[cache_key] = (float(res.score), bool(res.correct), trace)
        row[ag] = memo[cache_key]
    return row


def summarize_entropy(rows: list[dict[str, tuple[float, bool, list[tuple[str, str, str, str]]]]]) -> dict[str, Any]:
    c_lsel: Counter[str] = Counter()
    c_fsel: Counter[str] = Counter()
    c_joint_sel: Counter[str] = Counter()
    c_realized: Counter[str] = Counter()
    for r in rows:
        for lsel, fsel, rleak, rframe in r["solver"][2]:
            c_lsel[lsel] += 1
            c_fsel[fsel] += 1
            c_joint_sel[f"{lsel}/{fsel}"] += 1
            c_realized[f"{rleak}/{rframe}"] += 1
    tot = sum(c_lsel.values()) or 1
    return {
        "n_solver_mole_turns": sum(c_lsel.values()),
        "selector_entropy_bits": {
            "leak": round(shannon_entropy_bits(c_lsel), 4),
            "frame": round(shannon_entropy_bits(c_fsel), 4),
            "joint": round(shannon_entropy_bits(c_joint_sel), 4),
        },
        "realized_action_entropy_bits": round(shannon_entropy_bits(c_realized), 4),
        "selector_profile": {
            "leak": {k: round(v / tot, 4) for k, v in c_lsel.most_common()},
            "frame": {k: round(v / tot, 4) for k, v in c_fsel.most_common()},
        },
    }


def evaluate_train_strategy(
    strategy: MoleStrategy,
    seeds: list[int],
    tier: str,
    default_solver_score: float,
    memo: dict[tuple[str, int, str, str], tuple[float, bool, list[tuple[str, str, str, str]]]],
) -> dict[str, Any]:
    sj = strategy.to_json()
    mkey = json.dumps(sj, sort_keys=True)
    rows = [
        _rollout_seed_agents(
            tier,
            s,
            mkey,
            lambda tr, st=strategy: TracingMoleStrategy(st, tr),
            AGENTS,
            memo,
        )
        for s in seeds
    ]
    n = len(rows)
    solver_score = sum(r["solver"][0] for r in rows) / n
    solver_acc = sum(float(r["solver"][1]) for r in rows) / n
    per_inv: dict[str, dict[str, float]] = {}
    for inv in HEURISTIC_AGENTS:
        inv_score = sum(r[inv][0] for r in rows) / n
        inv_acc = sum(float(r[inv][1]) for r in rows) / n
        per_inv[inv] = {
            "score": round(inv_score, 6),
            "acc": round(inv_acc, 6),
            "regret": round(solver_score - inv_score, 6),
        }
    min_regret = solver_score - max(per_inv[inv]["score"] for inv in HEURISTIC_AGENTS)
    mean_regret = sum(per_inv[inv]["regret"] for inv in HEURISTIC_AGENTS) / len(HEURISTIC_AGENTS)
    feasible = (
        solver_acc >= MIN_TRAIN_SOLVER_ACC
        and solver_score >= MIN_TRAIN_SOLVER_RATIO * default_solver_score
    )
    ent = summarize_entropy(rows)
    return {
        "name": strategy.name,
        "strategy_json": sj,
        "n_rules": len(strategy.rules),
        "fitness": round(min_regret, 6) if feasible else -math.inf,
        "min_regret": round(min_regret, 6),
        "mean_regret": round(mean_regret, 6),
        "solver_score": round(solver_score, 6),
        "solver_acc": round(solver_acc, 6),
        "default_solver_score": round(default_solver_score, 6),
        "feasible": feasible,
        "catchable_85": solver_acc >= CATCHABLE_ACC_FLOOR,
        "per_investigator": per_inv,
        "action_entropy": ent,
    }


def select_and_write_hof(
    candidates: list[dict[str, Any]],
    train_seeds: list[int],
    tier: str,
    hof_out: Path,
    memo: dict[tuple[str, int, str, str], tuple[float, bool, list[tuple[str, str, str, str]]]],
    hof_k: int = HOF_SIZE,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    def_key = json.dumps(DEFAULT_STRATEGY.to_json(), sort_keys=True)
    def_rows = [
        _rollout_seed_agents(
            tier,
            s,
            def_key,
            lambda tr: TracingMoleStrategy(DEFAULT_STRATEGY, tr),
            AGENTS,
            memo,
        )
        for s in train_seeds
    ]
    n_train = len(def_rows)
    def_solver_score = sum(r["solver"][0] for r in def_rows) / n_train
    def_solver_acc = sum(float(r["solver"][1]) for r in def_rows) / n_train
    def_inv = {
        inv: {
            "score": round(sum(r[inv][0] for r in def_rows) / n_train, 6),
            "acc": round(sum(float(r[inv][1]) for r in def_rows) / n_train, 6),
            "regret": round(
                def_solver_score - (sum(r[inv][0] for r in def_rows) / n_train), 6
            ),
        }
        for inv in HEURISTIC_AGENTS
    }
    default_summary = {
        "solver_score": round(def_solver_score, 6),
        "solver_acc": round(def_solver_acc, 6),
        "min_regret": round(
            def_solver_score - max(def_inv[k]["score"] for k in HEURISTIC_AGENTS), 6
        ),
        "mean_regret": round(
            sum(def_inv[k]["regret"] for k in HEURISTIC_AGENTS) / len(HEURISTIC_AGENTS), 6
        ),
        "per_investigator": def_inv,
    }

    evaluated = [
        evaluate_train_strategy(
            MoleStrategy.from_json(c), train_seeds, tier, def_solver_score, memo
        )
        for c in candidates
    ]
    feasible = [e for e in evaluated if e["feasible"] and math.isfinite(e["fitness"])]
    feasible.sort(key=lambda e: (-e["fitness"], -e["mean_regret"], -e["solver_score"], e["name"]))

    selected: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    seen_struct: set[tuple[Any, ...]] = set()
    seen_behav: set[str] = set()
    for e in feasible:
        sig = rule_structure_signature(e["strategy_json"])
        bsig = json.dumps(
            [e["fitness"], e["solver_score"], e["per_investigator"]], sort_keys=True
        )
        if e["name"] in seen_names or sig in seen_struct or bsig in seen_behav:
            continue
        seen_names.add(e["name"])
        seen_struct.add(sig)
        seen_behav.add(bsig)
        selected.append(e)
        if len(selected) == hof_k:
            break

    if len(selected) < hof_k:
        raise RuntimeError(
            f"Only {len(selected)} feasible distinct distilled strategies found; need {hof_k}"
        )

    hof_rows: list[dict[str, Any]] = []
    for idx, e in enumerate(selected, start=1):
        hof_rows.append(
            {
                "rank": idx,
                "name": e["name"],
                "fitness": e["fitness"],
                "mean_regret": e["mean_regret"],
                "solver_score": e["solver_score"],
                "solver_acc": e["solver_acc"],
                "default_solver_score": e["default_solver_score"],
                "train_seeds": f"{train_seeds[0]}-{train_seeds[-1]}",
                "n_train_seeds": len(train_seeds),
                "per_investigator": e["per_investigator"],
                "strategy_json": e["strategy_json"],
            }
        )

    hof_out.parent.mkdir(parents=True, exist_ok=True)
    hof_out.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in hof_rows),
        encoding="utf-8",
    )
    forge_track._cache.pop(str(hof_out.resolve()), None)
    loaded_rows, loaded_strats = forge_track.load(hof_out)
    if len(loaded_rows) != hof_k or len(loaded_strats) != hof_k:
        raise RuntimeError("forge_track.load returned unexpected count")
    if hasattr(forge_track, "validate_hof"):
        forge_track.validate_hof(hof_out)

    return selected, {
        "train_seeds": f"{train_seeds[0]}-{train_seeds[-1]}",
        "n_train": len(train_seeds),
        "default_baseline": default_summary,
        "constraints": {
            "min_solver_acc": MIN_TRAIN_SOLVER_ACC,
            "min_solver_score_ratio": MIN_TRAIN_SOLVER_RATIO,
            "max_rules": MAX_DISTILLED_RULES,
            "hof_size": hof_k,
        },
        "n_candidates_evaluated": len(evaluated),
        "n_candidates_feasible": len(feasible),
        "forge_track_loaded": len(loaded_strats),
        "validate_hof_checked": hasattr(forge_track, "validate_hof"),
    }


def bootstrap_ci(
    values: list[float], resamples: int = 2000, seed: int = 0
) -> dict[str, Any]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95": [0.0, 0.0]}
    rng = random.Random(seed)
    sample_means = sorted(
        sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)
    )
    lo = sample_means[int(0.025 * resamples)]
    hi = sample_means[min(resamples - 1, int(0.975 * resamples))]
    return {
        "mean": round(sum(values) / n, 4),
        "ci95": [round(lo, 4), round(hi, 4)],
    }


def bootstrap_min_regret_diff(
    rows_a: list[dict[str, tuple[float, bool, list[Any]]]],
    rows_b: list[dict[str, tuple[float, bool, list[Any]]]],
    resamples: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    n = len(rows_a)
    if n == 0:
        return {"mean": 0.0, "ci95": [0.0, 0.0]}

    def _min_reg(sub: list[dict[str, tuple[float, bool, list[Any]]]]) -> float:
        sol = sum(x["solver"][0] for x in sub) / len(sub)
        best_inv = max(
            sum(x[inv][0] for x in sub) / len(sub) for inv in HEURISTIC_AGENTS
        )
        return sol - best_inv

    point = _min_reg(rows_a) - _min_reg(rows_b)
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(resamples):
        idxs = [rng.randrange(n) for _ in range(n)]
        sub_a = [rows_a[i] for i in idxs]
        sub_b = [rows_b[i] for i in idxs]
        diffs.append(_min_reg(sub_a) - _min_reg(sub_b))
    diffs.sort()
    return {
        "mean": round(point, 4),
        "ci95": [
            round(diffs[int(0.025 * resamples)], 4),
            round(diffs[min(resamples - 1, int(0.975 * resamples))], 4),
        ],
    }


def summarize_split(
    label: str,
    seeds: list[int],
    arm_rows: dict[str, list[dict[str, tuple[float, bool, list[tuple[str, str, str, str]]]]]],
    resamples: int = 2000,
) -> dict[str, Any]:
    moles_out: dict[str, Any] = {}
    for arm_name, rows in arm_rows.items():
        n = len(rows)
        per_agent = {
            ag: {
                "score": bootstrap_ci([x[ag][0] for x in rows], resamples, seed=11),
                "acc": bootstrap_ci([float(x[ag][1]) for x in rows], resamples, seed=17),
            }
            for ag in AGENTS
        }
        regrets = {
            inv: bootstrap_ci(
                [x["solver"][0] - x[inv][0] for x in rows], resamples, seed=23
            )
            for inv in HEURISTIC_AGENTS
        }
        per_seed_mean_reg = [
            sum(x["solver"][0] - x[inv][0] for inv in HEURISTIC_AGENTS)
            / len(HEURISTIC_AGENTS)
            for x in rows
        ]
        sol_mean = sum(x["solver"][0] for x in rows) / n
        sol_acc = sum(float(x["solver"][1]) for x in rows) / n
        inv_means = {
            inv: sum(x[inv][0] for x in rows) / n for inv in HEURISTIC_AGENTS
        }
        strongest = max(HEURISTIC_AGENTS, key=lambda k: inv_means[k])
        moles_out[arm_name] = {
            "agents": per_agent,
            "regret": regrets,
            "mean_regret": bootstrap_ci(per_seed_mean_reg, resamples, seed=29),
            "min_regret": round(sol_mean - inv_means[strongest], 4),
            "strongest_investigator": strongest,
            "solver_acc": round(sol_acc, 4),
            "catchable_85": sol_acc >= CATCHABLE_ACC_FLOOR,
            "catchable_75": sol_acc >= 0.75,
            "action_entropy": summarize_entropy(rows),
        }

    paired_diffs: dict[str, Any] = {}
    comparisons = (
        ("top_distilled_minus_default", "top_distilled", "default"),
        ("top_distilled_minus_rl_policy_final", "top_distilled", "rl_policy_final"),
        ("hof_rotation_minus_default", "hof_rotation", "default"),
        ("hof_rotation_minus_rl_policy_final", "hof_rotation", "rl_policy_final"),
    )
    for comp_name, lhs, rhs in comparisons:
        ra, rb = arm_rows[lhs], arm_rows[rhs]
        mean_reg_diffs = [
            (
                sum(ya["solver"][0] - ya[inv][0] for inv in HEURISTIC_AGENTS)
                - sum(yb["solver"][0] - yb[inv][0] for inv in HEURISTIC_AGENTS)
            )
            / len(HEURISTIC_AGENTS)
            for ya, yb in zip(ra, rb)
        ]
        paired_diffs[comp_name] = {
            **{
                f"{ag}_score": bootstrap_ci(
                    [ya[ag][0] - yb[ag][0] for ya, yb in zip(ra, rb)], resamples, seed=31
                )
                for ag in AGENTS
            },
            "solver_acc": bootstrap_ci(
                [
                    float(ya["solver"][1]) - float(yb["solver"][1])
                    for ya, yb in zip(ra, rb)
                ],
                resamples,
                seed=37,
            ),
            **{
                f"regret_{inv}": bootstrap_ci(
                    [
                        (ya["solver"][0] - ya[inv][0]) - (yb["solver"][0] - yb[inv][0])
                        for ya, yb in zip(ra, rb)
                    ],
                    resamples,
                    seed=41,
                )
                for inv in HEURISTIC_AGENTS
            },
            "mean_regret": bootstrap_ci(mean_reg_diffs, resamples, seed=43),
            "min_regret": bootstrap_min_regret_diff(ra, rb, resamples, seed=47),
        }

    return {
        "split": label,
        "n": len(seeds),
        "seeds_first": seeds[0] if seeds else None,
        "seeds_last": seeds[-1] if seeds else None,
        "moles": moles_out,
        "paired_diffs": paired_diffs,
    }


def verify_seed_disjointness(
    train_seeds: list[int],
    eval_200k_seeds: list[int],
    eval_800k_seeds: list[int],
) -> dict[str, Any]:
    s_train = set(train_seeds)
    s_200k = set(eval_200k_seeds)
    s_800k = set(eval_800k_seeds)
    s_dev = set(rules.DEV_SEEDS)
    s_heldout = set(rules.HELDOUT_SEEDS)
    s_judge = set(rules.JUDGE_SEEDS)
    s_train_pool = set(rules.TRAIN_SEEDS)

    train_in_pool = s_train.issubset(s_train_pool)
    disjoint_dev = s_train.isdisjoint(s_dev)
    disjoint_200k = s_train.isdisjoint(s_200k)
    disjoint_800k = s_train.isdisjoint(s_800k)
    disjoint_heldout_range = s_train.isdisjoint(s_heldout)
    disjoint_judge = (
        s_train.isdisjoint(s_judge)
        and s_200k.isdisjoint(s_judge)
        and s_800k.isdisjoint(s_judge)
    )
    splits_disjoint = s_200k.isdisjoint(s_800k)
    all_ok = (
        train_in_pool
        and disjoint_dev
        and disjoint_200k
        and disjoint_800k
        and disjoint_heldout_range
        and disjoint_judge
        and splits_disjoint
    )
    if not all_ok:
        raise ValueError("Seed hygiene disjointness check failed")
    return {
        "ok": all_ok,
        "train_subset_of_rules_train_seeds": train_in_pool,
        "train_disjoint_from_dev_seeds": disjoint_dev,
        "train_disjoint_from_eval_200k": disjoint_200k,
        "train_disjoint_from_eval_800k": disjoint_800k,
        "train_disjoint_from_rules_heldout_seeds": disjoint_heldout_range,
        "all_disjoint_from_judge_seeds": disjoint_judge,
        "eval_200k_disjoint_from_eval_800k": splits_disjoint,
    }


def evaluate_heldout_paired(
    hof_strategies: list[MoleStrategy],
    rl_policy: RLMole,
    eval_200k_seeds: list[int],
    eval_800k_seeds: list[int],
    tier: str,
    memo: dict[tuple[str, int, str, str], tuple[float, bool, list[tuple[str, str, str, str]]]],
    resamples: int = 2000,
) -> dict[str, Any]:
    top_st = hof_strategies[0]
    def_key = json.dumps(DEFAULT_STRATEGY.to_json(), sort_keys=True)
    top_key = json.dumps(top_st.to_json(), sort_keys=True)
    hof_keys = [json.dumps(st.to_json(), sort_keys=True) for st in hof_strategies]
    rl_key = f"rl_mole:{rl_policy.name}:greedy={rl_policy.greedy}"

    def _run_seeds(seeds: list[int]) -> dict[str, list[dict[str, tuple[float, bool, list[tuple[str, str, str, str]]]]]]:
        d_rows = [
            _rollout_seed_agents(
                tier,
                s,
                def_key,
                lambda tr: TracingMoleStrategy(DEFAULT_STRATEGY, tr),
                AGENTS,
                memo,
            )
            for s in seeds
        ]
        rl_rows = [
            _rollout_seed_agents(
                tier,
                s,
                rl_key,
                lambda tr: TracingRLMole(rl_policy, tr),
                AGENTS,
                memo,
            )
            for s in seeds
        ]
        top_rows = [
            _rollout_seed_agents(
                tier,
                s,
                top_key,
                lambda tr, st=top_st: TracingMoleStrategy(st, tr),
                AGENTS,
                memo,
            )
            for s in seeds
        ]
        rot_rows = []
        for s in seeds:
            idx = s % len(hof_strategies)
            st_i = hof_strategies[idx]
            key_i = hof_keys[idx]
            rot_rows.append(
                _rollout_seed_agents(
                    tier,
                    s,
                    key_i,
                    lambda tr, st=st_i: TracingMoleStrategy(st, tr),
                    AGENTS,
                    memo,
                )
            )
        return {
            "default": d_rows,
            "rl_policy_final": rl_rows,
            "top_distilled": top_rows,
            "hof_rotation": rot_rows,
        }

    arms_200k = _run_seeds(eval_200k_seeds)
    arms_800k = _run_seeds(eval_800k_seeds)
    arms_combined = {
        k: arms_200k[k] + arms_800k[k] for k in arms_200k
    }
    return {
        "heldout_200k": summarize_split("200000-200049", eval_200k_seeds, arms_200k, resamples),
        "heldout_800k": summarize_split("800000-800049", eval_800k_seeds, arms_800k, resamples),
        "combined_100": summarize_split(
            "200000-200049+800000-800049",
            eval_200k_seeds + eval_800k_seeds,
            arms_combined,
            resamples,
        ),
    }


def run_distillation_pipeline(
    jsonl_dir: str | Path | None = None,
    bare_repo: str | Path = DEFAULT_BARE_REPO,
    train_seeds: list[int] | None = None,
    eval_200k_seeds: list[int] | None = None,
    eval_800k_seeds: list[int] | None = None,
    rl_policy_path: str | Path = DEFAULT_RL_POLICY,
    hof_out: str | Path = DEFAULT_HOF_OUT,
    eval_out: str | Path = DEFAULT_EVAL_OUT,
    tier: str = "hard",
    workers: int = 1,
    bootstrap_resamples: int = 2000,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("distill_dsl enforces --workers 1 for CPU safety")
    t0 = time.monotonic()
    tr_seeds = list(TRAIN_SEED_RANGE) if train_seeds is None else list(train_seeds)
    ev_200k = list(HELDOUT_200K_RANGE) if eval_200k_seeds is None else list(eval_200k_seeds)
    ev_800k = list(HELDOUT_800K_RANGE) if eval_800k_seeds is None else list(eval_800k_seeds)

    hygiene = verify_seed_disjointness(tr_seeds, ev_200k, ev_800k)
    turns, source_meta = load_carbon_turns(jsonl_dir=jsonl_dir, bare_repo=bare_repo)
    stats = extract_turn_statistics(turns)
    candidates = distill_candidates(stats)

    memo: dict[tuple[str, int, str, str], tuple[float, bool, list[tuple[str, str, str, str]]]] = {}
    hof_path = Path(hof_out)
    selected, train_meta = select_and_write_hof(candidates, tr_seeds, tier, hof_path, memo)
    hof_strategies = [MoleStrategy.from_json(e["strategy_json"]) for e in selected]

    rl_path = Path(rl_policy_path)
    rl_policy = RLMole.from_json(json.loads(rl_path.read_text(encoding="utf-8")))
    heldout = evaluate_heldout_paired(
        hof_strategies=hof_strategies,
        rl_policy=rl_policy,
        eval_200k_seeds=ev_200k,
        eval_800k_seeds=ev_800k,
        tier=tier,
        memo=memo,
        resamples=bootstrap_resamples,
    )

    elapsed_s = round(time.monotonic() - t0, 2)
    report = {
        "schema_version": "1.0",
        "tier": tier,
        "tiers_version": rules.TIERS_VERSION,
        "workers": workers,
        "bootstrap_resamples": bootstrap_resamples,
        "elapsed_s": elapsed_s,
        "agents": list(AGENTS),
        "seed_hygiene": {
            **hygiene,
            "train_seeds": f"{tr_seeds[0]}-{tr_seeds[-1]}",
            "n_train": len(tr_seeds),
            "heldout_200k_seeds": f"{ev_200k[0]}-{ev_200k[-1]}",
            "n_heldout_200k": len(ev_200k),
            "heldout_800k_seeds": f"{ev_800k[0]}-{ev_800k[-1]}",
            "n_heldout_800k": len(ev_800k),
        },
        "carbon_transcript_stats": {
            "source": source_meta,
            **stats,
        },
        "train_selection": {
            **train_meta,
            "hof_path": str(hof_path.relative_to(ROOT)) if hof_path.is_relative_to(ROOT) else str(hof_path),
            "selected_hof": [
                {
                    "rank": i + 1,
                    "name": e["name"],
                    "n_rules": e["n_rules"],
                    "fitness": e["fitness"],
                    "mean_regret": e["mean_regret"],
                    "solver_score": e["solver_score"],
                    "solver_acc": e["solver_acc"],
                    "catchable_85": e["catchable_85"],
                    "per_investigator": e["per_investigator"],
                    "selector_entropy_bits": e["action_entropy"]["selector_entropy_bits"],
                }
                for i, e in enumerate(selected)
            ],
        },
        "heldout_eval": heldout,
    }

    eval_path = Path(eval_out)
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, indent=1, sort_keys=True) + "\n"
    if len(serialized.encode("utf-8")) >= 40_000:
        serialized = json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n"
    if len(serialized.encode("utf-8")) >= 40_000:
        raise RuntimeError("Serialized evaluation JSON exceeds 40 KB cap")
    eval_path.write_text(serialized, encoding="utf-8")
    return report


def _validate_ci_bounds(node: Any, path: str = "root") -> int:
    count = 0
    if isinstance(node, dict):
        if "mean" in node and "ci95" in node:
            ci = node["ci95"]
            if not isinstance(ci, list) or len(ci) != 2:
                raise ValueError(f"Invalid ci95 format at {path}")
            lo, hi = float(ci[0]), float(ci[1])
            mean_val = float(node["mean"])
            if not (math.isfinite(lo) and math.isfinite(mean_val) and math.isfinite(hi)):
                raise ValueError(f"Non-finite CI values at {path}")
            if not (lo <= mean_val + 1e-6 and mean_val <= hi + 1e-6 and lo <= hi):
                raise ValueError(f"CI bounds violated at {path}: {lo} <= {mean_val} <= {hi}")
            count += 1
        for k, v in node.items():
            count += _validate_ci_bounds(v, f"{path}.{k}")
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            count += _validate_ci_bounds(item, f"{path}[{idx}]")
    return count


def check_distilled_artifacts(
    hof_path: str | Path = DEFAULT_HOF_OUT,
    eval_path: str | Path = DEFAULT_EVAL_OUT,
) -> dict[str, Any]:
    t0 = time.monotonic()
    hp = Path(hof_path)
    ep = Path(eval_path)
    if not hp.is_file():
        raise FileNotFoundError(f"Missing HoF file: {hp}")
    if not ep.is_file():
        raise FileNotFoundError(f"Missing eval JSON file: {ep}")

    raw_lines = [ln for ln in hp.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(raw_lines) != HOF_SIZE:
        raise ValueError(f"Expected {HOF_SIZE} HoF entries, got {len(raw_lines)}")

    forge_track._cache.pop(str(hp.resolve()), None)
    loaded_rows, loaded_strats = forge_track.load(hp)
    if len(loaded_rows) != HOF_SIZE or len(loaded_strats) != HOF_SIZE:
        raise ValueError("forge_track.load returned unexpected HoF count")

    names: list[str] = []
    seen_sigs: set[tuple[Any, ...]] = set()
    for expected_rank, (row, st) in enumerate(zip(loaded_rows, loaded_strats), start=1):
        if int(row.get("rank", -1)) != expected_rank:
            raise ValueError(f"Expected rank {expected_rank}, got {row.get('rank')}")
        if not isinstance(st, MoleStrategy):
            raise ValueError(f"Expected MoleStrategy entry, got {type(st).__name__}")
        if not (1 <= len(st.rules) <= MAX_DISTILLED_RULES):
            raise ValueError(f"Strategy {st.name} rule count {len(st.rules)} outside 1..{MAX_DISTILLED_RULES}")
        for conds, (lsel, fsel) in st.rules:
            if lsel not in LEAK_SELECTORS or fsel not in FRAME_SELECTORS:
                raise ValueError(f"Invalid rule selectors in {st.name}")
            for feat, op, val in conds:
                if feat not in FEATURES or op not in OPS or not math.isfinite(val):
                    raise ValueError(f"Invalid condition in {st.name}")
        if st.default[0] not in LEAK_SELECTORS or st.default[1] not in FRAME_SELECTORS:
            raise ValueError(f"Invalid default selectors in {st.name}")
        sj = st.to_json()
        sig = rule_structure_signature(sj)
        if st.name in names or sig in seen_sigs:
            raise ValueError(f"Duplicate HoF strategy name or structure: {st.name}")
        if float(row.get("solver_acc", 0.0)) < MIN_TRAIN_SOLVER_ACC:
            raise ValueError(f"HoF entry {st.name} train solver_acc below {MIN_TRAIN_SOLVER_ACC}")
        names.append(st.name)
        seen_sigs.add(sig)

    eval_bytes = ep.read_bytes()
    if len(eval_bytes) >= 40_000:
        raise ValueError(f"Eval JSON exceeds 40 KB cap ({len(eval_bytes)} bytes)")
    rep = json.loads(eval_bytes.decode("utf-8"))
    required_keys = {
        "schema_version",
        "tier",
        "tiers_version",
        "workers",
        "bootstrap_resamples",
        "elapsed_s",
        "agents",
        "seed_hygiene",
        "carbon_transcript_stats",
        "train_selection",
        "heldout_eval",
    }
    missing = required_keys - set(rep.keys())
    if missing:
        raise ValueError(f"Eval JSON missing required top-level keys: {sorted(missing)}")

    sh = rep["seed_hygiene"]
    tr_seeds = parse_seeds(str(sh["train_seeds"]))
    ev_200k = parse_seeds(str(sh["heldout_200k_seeds"]))
    ev_800k = parse_seeds(str(sh["heldout_800k_seeds"]))
    if not all(140_000 <= s < 150_000 for s in tr_seeds):
        raise ValueError("Train seeds must lie in the 140k range")
    if not all(200_000 <= s < 210_000 for s in ev_200k):
        raise ValueError("heldout_200k seeds must lie in the 200k range")
    if not all(800_000 <= s < 810_000 for s in ev_800k):
        raise ValueError("heldout_800k seeds must lie in the 800k range")
    rechecked = verify_seed_disjointness(tr_seeds, ev_200k, ev_800k)
    for k, v in rechecked.items():
        if sh.get(k) is not True or v is not True:
            raise ValueError(f"Seed hygiene flag {k} is not True")

    sel_hof = rep["train_selection"].get("selected_hof") or []
    if [x["name"] for x in sel_hof] != names:
        raise ValueError("train_selection.selected_hof names do not match HoF JSONL")
    if not all(x.get("catchable_85") is True and int(x["n_rules"]) <= MAX_DISTILLED_RULES for x in sel_hof):
        raise ValueError("Selected HoF train entries violate catchable_85 or rule cap")

    expected_splits = {
        "heldout_200k": len(ev_200k),
        "heldout_800k": len(ev_800k),
        "combined_100": len(ev_200k) + len(ev_800k),
    }
    expected_arms = {"default", "rl_policy_final", "top_distilled", "hof_rotation"}
    he = rep["heldout_eval"]
    if set(he.keys()) != set(expected_splits.keys()):
        raise ValueError(f"Unexpected heldout_eval splits: {sorted(he.keys())}")
    for split_name, expected_n in expected_splits.items():
        sp = he[split_name]
        if int(sp.get("n", -1)) != expected_n:
            raise ValueError(f"Split {split_name} expected n={expected_n}, got {sp.get('n')}")
        moles = sp.get("moles") or {}
        if set(moles.keys()) != expected_arms:
            raise ValueError(f"Split {split_name} missing mole arms")
        for arm_name, arm in moles.items():
            acc = float(arm["solver_acc"])
            flag = arm.get("catchable_85")
            if not isinstance(flag, bool) or flag != (acc >= CATCHABLE_ACC_FLOOR):
                raise ValueError(f"Inconsistent catchable_85 on {split_name}.{arm_name}")
        for catchable_arm in ("top_distilled", "hof_rotation"):
            if moles[catchable_arm]["catchable_85"] is not True:
                raise ValueError(f"{catchable_arm} failed catchable_85 on {split_name}")

    n_ci = _validate_ci_bounds(he, "heldout_eval")
    if n_ci == 0:
        raise ValueError("No CI bounds found in heldout_eval")

    return {
        "ok": True,
        "hof_entries": len(names),
        "hof_names": names,
        "eval_bytes": len(eval_bytes),
        "ci_objects_checked": n_ci,
        "elapsed_s": round(time.monotonic() - t0, 4),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.distill_dsl")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--jsonl-dir", default=None)
    ap.add_argument("--bare-repo", default=str(DEFAULT_BARE_REPO))
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--train-seeds", default="140000-140039")
    ap.add_argument("--eval-200k-seeds", default="200000-200049")
    ap.add_argument("--eval-800k-seeds", default="800000-800049")
    ap.add_argument("--rl-policy", default=str(DEFAULT_RL_POLICY))
    ap.add_argument("--hof-out", default=str(DEFAULT_HOF_OUT))
    ap.add_argument("--eval-out", default=str(DEFAULT_EVAL_OUT))
    ap.add_argument("--bootstrap-resamples", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)

    if args.check:
        res = check_distilled_artifacts(hof_path=args.hof_out, eval_path=args.eval_out)
        print(json.dumps(res, indent=2))
        return 0

    rep = run_distillation_pipeline(
        jsonl_dir=args.jsonl_dir,
        bare_repo=args.bare_repo,
        train_seeds=parse_seeds(args.train_seeds),
        eval_200k_seeds=parse_seeds(args.eval_200k_seeds),
        eval_800k_seeds=parse_seeds(args.eval_800k_seeds),
        rl_policy_path=args.rl_policy,
        hof_out=args.hof_out,
        eval_out=args.eval_out,
        tier=args.tier,
        workers=args.workers,
        bootstrap_resamples=args.bootstrap_resamples,
    )
    comb = rep["heldout_eval"]["combined_100"]["moles"]
    summary = {
        "elapsed_s": rep["elapsed_s"],
        "n_turns": rep["carbon_transcript_stats"]["n_turns"],
        "top_hof": rep["train_selection"]["selected_hof"][0]["name"],
        "combined_100": {
            k: {
                "solver_acc": v["solver_acc"],
                "catchable_85": v["catchable_85"],
                "min_regret": v["min_regret"],
                "mean_regret": v["mean_regret"]["mean"],
            }
            for k, v in comb.items()
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
