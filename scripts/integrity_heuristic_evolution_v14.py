from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import os

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import random
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.baselines import TOPICS, _params_from_instruction, employee_ids
from canary.eval import make_env, make_policy_factory, run_episode
from canary.mcp_server import seed_allowed
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, tier_params
from canary.types import INVESTIGATIVE_TOOLS, Step
from canary.world import generate_world, set_world_secret

ALL_TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge", "hard_rl")
FAST_SCREEN_TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge")
HARD_TARGETS: tuple[str, ...] = ("hard", "hard_forge", "hard_rl")
EFFORT_TARGETS: tuple[str, ...] = ("hard_forge", "hard_rl")
EFFORT_CUTS: tuple[int, ...] = (10, 25, 50, 75, 90)
HASH_SEEDS: tuple[int, ...] = (0, 1, 42, 2147483647)
PUBLIC_TEST_SECRET: bytes = b"canary-anticheat-public-test-v1"

DEV_TRAIN_SEEDS: tuple[int, ...] = tuple(range(30000, 30100))
DEV_OOS_SEEDS: tuple[int, ...] = tuple(range(30200, 30400))
EFFORT_SEEDS: tuple[int, ...] = tuple(range(30200, 30300))
JUDGE_OOS_SEEDS: tuple[int, ...] = tuple(range(900000, 900040))
JUDGE_PUBLIC_SEEDS: tuple[int, ...] = tuple(range(900000, 900040))
JUDGE_AUTOCORR_SEEDS: tuple[int, ...] = tuple(range(900000, 900200))
HELDOUT_AUTOCORR_SEEDS: tuple[int, ...] = tuple(range(800000, 800200))

CANARY_GROUP_SIZES: tuple[int, ...] = (2, 3, 4, 6, 8, 10, 12, 16, 20)
VARIANT_PARTITIONS: tuple[int, ...] = (2, 3)
DECOY_RULES: tuple[str, ...] = ("none", "unique_cv", "anger_majority", "soft_deprioritize")
AFTER_HOURS_WEIGHTS: tuple[float, ...] = (0.0, 0.5, 1.0, 2.0, 4.0, 8.0)
INTERVIEW_BUDGETS: tuple[int, ...] = (0, 2, 4, 6, 8)
MIN_POOL_SIZES: tuple[int, ...] = (1, 2, 3, 4)
ACCUSE_DAY_THRESHOLDS: tuple[int, ...] = (6, 8, 10, 12, 14, 18, 21, 99)
ELIMINATION_MODES: tuple[str, ...] = ("strict", "min_strikes", "weighted_strikes")
SECOND_CANARY_MODES: tuple[str, ...] = ("offset", "orthogonal", "disjoint_top")

ANGER_QUERIES: tuple[str, ...] = ("CV", "promotion", "raise", "deserve", "unfair")


@dataclass(frozen=True)
class HeuristicConfig:
    first_canary_size: int = 6
    followup_canary_size: int = 6
    variant_partitions: int = 3
    decoy_rule: str = "unique_cv"
    after_hours_weight: float = 0.0
    interview_budget: int = 0
    min_pool_to_accuse: int = 1
    accuse_day_threshold: int = 99
    elimination_mode: str = "strict"
    second_canary_mode: str = "offset"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def short_label(self) -> str:
        return (
            f"g1={self.first_canary_size},g2={self.followup_canary_size},"
            f"vp={self.variant_partitions},dec={self.decoy_rule},"
            f"ah={self.after_hours_weight:g},iv={self.interview_budget},"
            f"mp={self.min_pool_to_accuse},ad={self.accuse_day_threshold},"
            f"el={self.elimination_mode},sc={self.second_canary_mode}"
        )


W2B008_CONFIG = HeuristicConfig()


class ParameterizedEliminationPolicy:
    def __init__(self, cfg: HeuristicConfig = W2B008_CONFIG, seed: int = 0, name: str | None = None):
        self.cfg = cfg
        self.seed = seed
        self.name = name or f"elim[{cfg.short_label()}]"
        self.reset([], "")

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        p = _params_from_instruction(instruction)
        env_max_var = int(p.get("max_variants", 3))
        self.max_variants = max(2, min(int(self.cfg.variant_partitions), env_max_var))
        self.cpd = max(1, int(p.get("canaries_per_day", 1)))
        self.n_days = max(1, int(p.get("n_days", 14)))
        self.actions_per_day = max(1, int(p.get("actions_per_day", 8)))
        self.roster: list[str] = []
        self.suspects: set[str] | None = None
        self.strikes: dict[str, int] = {}
        self.leak_hits: dict[str, int] = {}
        self.log_score: dict[str, float] = {}
        self.evasive_hits: dict[str, int] = {}
        self.anger_hits: dict[str, int] = {}
        self.decoy_id: str | None = None
        self.hard_dropped: set[str] = set()
        self.docs: dict[str, dict[str, Any]] = {}
        self.used_leaks: set[str] = set()
        self.done_today: set[tuple[int, str]] = set()
        self.actions_used_by_day: dict[int, int] = {}
        self.decoy_queries_done: set[str] = set()
        self.decoy_checked = False
        self.logs_read_through = 0
        self.interviews_used = 0
        self.interviewed: set[tuple[str, str]] = set()
        self.n_canaries = 0
        self.first_pick_by_day: dict[int, list[str]] = {}
        self._ingested = 0

    def _once(self, day: int, tag: str) -> bool:
        key = (day, tag)
        if key in self.done_today:
            return False
        self.done_today.add(key)
        return True

    def _is_pure_w2b008_ranking(self) -> bool:
        c = self.cfg
        return (
            c.after_hours_weight == 0.0
            and c.interview_budget == 0
            and c.decoy_rule in ("none", "unique_cv")
            and c.elimination_mode == "strict"
        )

    def _ingest_step(self, st: Step) -> None:
        res = st.result or {}
        ok = bool(res.get("ok"))
        data = res.get("data") or {}
        if st.tool in INVESTIGATIVE_TOOLS and ok:
            self.actions_used_by_day[st.day] = self.actions_used_by_day.get(st.day, 0) + 1
        if not ok:
            return
        if st.tool == "list_employees" and self.suspects is None:
            self.roster = employee_ids(res)
            self.suspects = set(self.roster)
            for e in self.roster:
                self.strikes[e] = 0
                self.leak_hits[e] = 0
                self.log_score[e] = 0.0
                self.evasive_hits[e] = 0
                self.anger_hits[e] = 0
        elif st.tool == "list_documents":
            for doc in data.get("documents", []):
                self.docs[doc["doc_id"]] = doc
        elif st.tool == "search_messages":
            msgs = data.get("messages", [])
            if self.cfg.decoy_rule == "unique_cv":
                senders = {m.get("sender") for m in msgs if m.get("sender")}
                if len(senders) == 1 and self.suspects is not None and len(self.suspects) > 1:
                    self.suspects -= senders
                    self.hard_dropped |= senders
            else:
                for m in msgs:
                    snd = m.get("sender")
                    if snd:
                        self.anger_hits[snd] = self.anger_hits.get(snd, 0) + 1
                if self.anger_hits:
                    ordered = sorted(self.anger_hits.items(), key=lambda kv: (-kv[1], kv[0]))
                    top_emp, top_cnt = ordered[0]
                    sec_cnt = ordered[1][1] if len(ordered) > 1 else 0
                    if self.cfg.decoy_rule == "anger_majority":
                        if top_cnt >= 2 and top_cnt >= 2 * max(1, sec_cnt):
                            self.decoy_id = top_emp
                            if self.suspects is not None and len(self.suspects - {top_emp}) >= 1:
                                self.suspects.discard(top_emp)
                            self.hard_dropped.add(top_emp)
                    elif self.cfg.decoy_rule == "soft_deprioritize":
                        if top_cnt >= 1 and top_cnt > sec_cnt:
                            self.decoy_id = top_emp
        elif st.tool == "check_leak_feed":
            for it in data.get("items", []):
                key = f"{it.get('doc_id')}:{it.get('variant')}"
                doc = self.docs.get(it.get("doc_id"))
                if key in self.used_leaks or not doc:
                    continue
                self.used_leaks.add(key)
                is_can = bool(doc.get("is_canary") and it.get("variant") and doc.get("variants"))
                if is_can:
                    grp = set(doc["variants"].get(it["variant"], []))
                else:
                    grp = set(doc.get("recipients", []))
                for e in grp:
                    if e in self.leak_hits:
                        self.leak_hits[e] += 2 if is_can else 1
                miss_penalty = 1
                if self.cfg.elimination_mode == "weighted_strikes":
                    miss_penalty = 2 if is_can else 3
                for e in self.roster:
                    if e not in grp:
                        self.strikes[e] = self.strikes.get(e, 0) + miss_penalty
                if self.suspects is not None and (self.suspects & grp):
                    self.suspects &= grp
        elif st.tool == "read_access_logs":
            w = float(self.cfg.after_hours_weight)
            for entry in data.get("logs", []):
                emp = entry.get("employee")
                if emp in self.log_score:
                    ah = 1.0 if entry.get("after_hours") else 0.0
                    self.log_score[emp] += 1.0 + w * ah
        elif st.tool == "interview":
            emp = st.args.get("employee")
            ans = str(data.get("answer", "")).lower()
            if emp in self.evasive_hits and "evasive" in ans:
                self.evasive_hits[emp] += 1

    def _active_suspects(self) -> set[str]:
        if self.cfg.elimination_mode == "strict":
            return set(self.suspects or self.roster)
        pool = [e for e in self.roster if e not in self.hard_dropped]
        if not pool:
            pool = list(self.roster)
        if not pool:
            return set()
        min_s = min(self.strikes.get(e, 0) for e in pool)
        return {e for e in pool if self.strikes.get(e, 0) == min_s}

    def _rank_suspects(self, active: set[str], day: int, for_accuse: bool = False) -> list[str]:
        if self._is_pure_w2b008_ranking() and not for_accuse:
            return sorted(active)
        denom = float(max(1, day - 1))

        def score_emp(e: str) -> tuple[float, int, str]:
            s = (
                3.0 * float(self.leak_hits.get(e, 0))
                + 4.0 * float(self.evasive_hits.get(e, 0))
                + (self.log_score.get(e, 0.0) / denom)
            )
            if self.decoy_id is not None and e == self.decoy_id:
                s -= 100.0
            return (-s, -self.leak_hits.get(e, 0), e)

        return sorted(active, key=score_emp)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        if len(history) < self._ingested:
            self.reset([], "")
        for st in history[self._ingested :]:
            self._ingest_step(st)
        self._ingested = len(history)

        if self.suspects is None:
            return "list_employees", {}

        day = history[-1].day if history else 1
        if history and history[-1].tool == "advance_day" and history[-1].result.get("ok"):
            day = int(history[-1].result["data"]["day"])

        if self._once(day, "docs"):
            return "list_documents", {}

        used_actions = self.actions_used_by_day.get(day, 0)
        actions_left = self.actions_per_day - used_actions

        if self.cfg.decoy_rule == "unique_cv":
            if day >= 2 and not self.decoy_checked and actions_left > self.cpd + 1:
                self.decoy_checked = True
                return "search_messages", {"query": "CV"}
        elif self.cfg.decoy_rule in ("anger_majority", "soft_deprioritize"):
            max_q = 3 if self.cfg.decoy_rule == "anger_majority" else 2
            if day in (2, 3) and self.decoy_id is None and len(self.decoy_queries_done) < max_q:
                if actions_left > self.cpd + 1:
                    for q in ANGER_QUERIES[:max_q]:
                        if q not in self.decoy_queries_done:
                            self.decoy_queries_done.add(q)
                            return "search_messages", {"query": q}

        if day >= 2 and self._once(day, "feed") and actions_left >= 1:
            return "check_leak_feed", {}

        active = self._active_suspects()
        if len(active) == 1:
            return "accuse", {"employee": next(iter(active))}

        if self.cfg.after_hours_weight > 0.0 and day >= 2 and self.logs_read_through < day - 1:
            if actions_left > self.cpd:
                lo = self.logs_read_through + 1
                hi = day - 1
                self.logs_read_through = hi
                return "read_access_logs", {"day_from": lo, "day_to": hi}

        if self.cfg.interview_budget > 0 and self.interviews_used < self.cfg.interview_budget:
            if day >= 2 and 2 <= len(active) <= 8 and actions_left > self.cpd:
                ranked_iv = self._rank_suspects(active, day, for_accuse=True)
                for emp in ranked_iv:
                    for topic in TOPICS:
                        if (emp, topic) not in self.interviewed:
                            self.interviewed.add((emp, topic))
                            self.interviews_used += 1
                            return "interview", {"employee": emp, "topic": topic}

        if self.cfg.accuse_day_threshold < 99:
            eff_day = min(int(self.cfg.accuse_day_threshold), self.n_days)
            if day >= eff_day and 1 <= len(active) <= int(self.cfg.min_pool_to_accuse):
                best = self._rank_suspects(active, day, for_accuse=True)[0]
                return "accuse", {"employee": best}

        ranked = self._rank_suspects(active, day, for_accuse=False)
        vp = self.max_variants
        for k in range(self.cpd):
            if len(ranked) < 2 or actions_left <= 0:
                break
            if not self._once(day, f"canary{k}"):
                continue
            if len(ranked) <= vp:
                pick = ranked
                if k >= 1 and self.cfg.second_canary_mode != "offset":
                    assign = {e: "ABC"[(i + 1) % vp] for i, e in enumerate(pick)}
                else:
                    assign = {e: "ABC"[i] for i, e in enumerate(pick)}
            else:
                target_sz = self.cfg.first_canary_size if self.n_canaries == 0 else self.cfg.followup_canary_size
                size = max(2, min(len(ranked), int(target_sz)))
                if k == 0 or self.cfg.second_canary_mode == "offset":
                    off = (day * size + k * size) % len(ranked)
                    pick = (ranked[off:] + ranked[:off])[:size]
                    if k == 0:
                        self.first_pick_by_day[day] = list(pick)
                    assign = {e: "ABC"[i % vp] for i, e in enumerate(pick)}
                elif self.cfg.second_canary_mode == "orthogonal":
                    base_pick = [e for e in self.first_pick_by_day.get(day, []) if e in active]
                    if len(base_pick) < 2:
                        off = (day * size) % len(ranked)
                        base_pick = (ranked[off:] + ranked[:off])[:size]
                    pick = base_pick
                    if len(pick) <= vp:
                        assign = {e: "ABC"[(i + 1) % vp] for i, e in enumerate(pick)}
                    else:
                        assign = {e: "ABC"[(i // vp) % vp] for i, e in enumerate(pick)}
                        if len(set(assign.values())) < 2:
                            assign = {e: "ABC"[(i + 1) % vp] for i, e in enumerate(pick)}
                else:
                    used_set = set(self.first_pick_by_day.get(day, []))
                    rest = [e for e in ranked if e not in used_set]
                    if len(rest) >= 2:
                        off = (day * size) % len(rest)
                        pick = (rest[off:] + rest[:off])[: min(len(rest), size)]
                    else:
                        off = (day * size + k * size) % len(ranked)
                        pick = (ranked[off:] + ranked[:off])[:size]
                    assign = {e: "ABC"[i % vp] for i, e in enumerate(pick)}
            self.n_canaries += 1
            return "plant_canary", {"doc_title": f"Targeted Memo {day}-{k}", "assignment": assign}

        return "advance_day", {}


def random_config(rng: random.Random) -> HeuristicConfig:
    return HeuristicConfig(
        first_canary_size=rng.choice(CANARY_GROUP_SIZES),
        followup_canary_size=rng.choice(CANARY_GROUP_SIZES),
        variant_partitions=rng.choice(VARIANT_PARTITIONS),
        decoy_rule=rng.choice(DECOY_RULES),
        after_hours_weight=rng.choice(AFTER_HOURS_WEIGHTS),
        interview_budget=rng.choice(INTERVIEW_BUDGETS),
        min_pool_to_accuse=rng.choice(MIN_POOL_SIZES),
        accuse_day_threshold=rng.choice(ACCUSE_DAY_THRESHOLDS),
        elimination_mode=rng.choice(ELIMINATION_MODES),
        second_canary_mode=rng.choice(SECOND_CANARY_MODES),
    )


def mutate_config(cfg: HeuristicConfig, rng: random.Random, n_genes: int = 2) -> HeuristicConfig:
    d = cfg.to_dict()
    domains: dict[str, tuple[Any, ...]] = {
        "first_canary_size": CANARY_GROUP_SIZES,
        "followup_canary_size": CANARY_GROUP_SIZES,
        "variant_partitions": VARIANT_PARTITIONS,
        "decoy_rule": DECOY_RULES,
        "after_hours_weight": AFTER_HOURS_WEIGHTS,
        "interview_budget": INTERVIEW_BUDGETS,
        "min_pool_to_accuse": MIN_POOL_SIZES,
        "accuse_day_threshold": ACCUSE_DAY_THRESHOLDS,
        "elimination_mode": ELIMINATION_MODES,
        "second_canary_mode": SECOND_CANARY_MODES,
    }
    keys = rng.sample(list(domains.keys()), k=max(1, min(n_genes, len(domains))))
    for k in keys:
        choices = [v for v in domains[k] if v != d[k]]
        if choices:
            d[k] = rng.choice(choices)
    return HeuristicConfig(**d)


def crossover_configs(a: HeuristicConfig, b: HeuristicConfig, rng: random.Random) -> HeuristicConfig:
    da, db = a.to_dict(), b.to_dict()
    merged = {k: (da[k] if rng.random() < 0.5 else db[k]) for k in da}
    return HeuristicConfig(**merged)


def build_structured_grid(n_grid: int, seed: int = 20261115) -> list[HeuristicConfig]:
    rng = random.Random(seed)
    seen: set[HeuristicConfig] = {W2B008_CONFIG}
    ordered: list[HeuristicConfig] = [W2B008_CONFIG]

    anchors: list[HeuristicConfig] = []
    for g1 in (2, 3, 4, 6, 8, 12, 16, 20):
        for vp in (2, 3):
            for el in ELIMINATION_MODES:
                for sc in SECOND_CANARY_MODES:
                    anchors.append(
                        HeuristicConfig(
                            first_canary_size=g1,
                            followup_canary_size=min(20, max(2, g1)),
                            variant_partitions=vp,
                            decoy_rule="unique_cv" if vp == 3 else "anger_majority",
                            after_hours_weight=0.0 if el == "strict" else 2.0,
                            interview_budget=0,
                            min_pool_to_accuse=1 if el == "strict" else 2,
                            accuse_day_threshold=99 if el == "strict" else 21,
                            elimination_mode=el,
                            second_canary_mode=sc,
                        )
                    )
    rng.shuffle(anchors)
    for c in anchors:
        if len(ordered) >= n_grid:
            break
        if c not in seen:
            seen.add(c)
            ordered.append(c)

    while len(ordered) < n_grid:
        c = random_config(rng)
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def regularized_gamma_q(a: float, x: float) -> float:
    if x <= 0.0:
        return 1.0
    if a <= 0.0:
        return 0.0
    eps = 1e-14
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap = a
        term = 1.0 / a
        total = term
        for _ in range(500):
            ap += 1.0
            term *= x / ap
            total += term
            if abs(term) < abs(total) * eps:
                break
        p_val = total * math.exp(-x + a * math.log(x) - gln)
        return max(0.0, min(1.0, 1.0 - p_val))
    b = x + 1.0 - a
    c = 1.0 / 1e-30
    d = 1.0 / b
    h = d
    for i in range(1, 500):
        an = -float(i) * (float(i) - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-30:
            d = 1e-30
        c = b + an / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    q_val = math.exp(-x + a * math.log(x) - gln) * h
    return max(0.0, min(1.0, q_val))


def chi2_sf(x: float, df: int) -> float:
    if df <= 0:
        raise ValueError("df must be positive")
    if x <= 0.0:
        return 1.0
    return regularized_gamma_q(0.5 * float(df), 0.5 * float(x))


def paired_bootstrap_stats(
    policy_scores: list[float],
    solver_scores: list[float],
    n_boot: int = 4000,
    boot_seed: int = 1729,
) -> dict[str, Any]:
    import numpy as np

    if len(policy_scores) != len(solver_scores) or not policy_scores:
        raise ValueError("policy_scores and solver_scores must be equal non-empty length")
    n = len(policy_scores)
    pol_arr = np.asarray(policy_scores, dtype=np.float64)
    sol_arr = np.asarray(solver_scores, dtype=np.float64)
    diffs = pol_arr - sol_arr
    mean_pol = float(pol_arr.mean())
    mean_sol = float(sol_arr.mean())
    mean_diff = float(diffs.mean())
    sd_diff = float(diffs.std(ddof=1)) if n > 1 else 0.0
    rng = np.random.default_rng(boot_seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = diffs[idx].mean(axis=1)
    ci_lo = float(np.percentile(boot_means, 2.5))
    ci_hi = float(np.percentile(boot_means, 97.5))
    one_sided_lower95 = mean_diff - (1.645 * sd_diff / math.sqrt(n) if n > 1 else 0.0)
    wins = int(np.sum(diffs > 1e-9))
    ties = int(np.sum(np.abs(diffs) <= 1e-9))
    losses = int(np.sum(diffs < -1e-9))
    ratio = float(mean_pol / mean_sol) if abs(mean_sol) > 1e-12 else float("nan")
    return {
        "n": n,
        "policy_mean": round(mean_pol, 6),
        "solver_mean": round(mean_sol, 6),
        "paired_mean_diff": round(mean_diff, 6),
        "boot_ci95_lo": round(ci_lo, 6),
        "boot_ci95_hi": round(ci_hi, 6),
        "normal_ci95_half": round(1.96 * sd_diff / math.sqrt(n) if n > 1 else 0.0, 6),
        "one_sided_lower95": round(one_sided_lower95, 6),
        "significantly_above_solver": bool(one_sided_lower95 > 0.0),
        "beats_solver_in_mean": bool(mean_diff > 1e-9),
        "ratio_to_solver": round(ratio, 6) if math.isfinite(ratio) else None,
        "wins": wins,
        "ties": ties,
        "losses": losses,
    }


def eval_policy_on_seeds(
    cfg: HeuristicConfig,
    tier: str,
    seeds: list[int] | tuple[int, ...],
    name: str | None = None,
    ep_cache: dict[tuple[HeuristicConfig, str, int], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    scores: list[float] = []
    corrects: list[bool] = []
    accused_flags: list[bool] = []
    wrong_flags: list[bool] = []
    accuse_days: list[int] = []
    tool_calls = 0
    fresh_episodes = 0
    for s in seeds:
        ck = (cfg, tier, int(s))
        cached = ep_cache.get(ck) if ep_cache is not None else None
        if cached is None:
            env = make_env(tier, s)
            pol = ParameterizedEliminationPolicy(cfg, seed=s, name=name)
            res = run_episode(env, pol)
            cached = {
                "score": float(res.score),
                "correct": bool(res.correct),
                "did_acc": res.accused is not None,
                "acc_day": int(res.final_day) if res.end_reason == "accused" else None,
                "steps": len(res.steps),
            }
            if ep_cache is not None:
                ep_cache[ck] = cached
            tool_calls += cached["steps"]
            fresh_episodes += 1
        scores.append(cached["score"])
        corrects.append(cached["correct"])
        did_acc = cached["did_acc"]
        accused_flags.append(did_acc)
        wrong_flags.append(bool(did_acc and not cached["correct"]))
        if cached["acc_day"] is not None:
            accuse_days.append(cached["acc_day"])
    n = len(scores)
    mean_sc = sum(scores) / n if n else 0.0
    sd_sc = math.sqrt(sum((x - mean_sc) ** 2 for x in scores) / (n - 1)) if n > 1 else 0.0
    return {
        "scores": scores,
        "mean": round(mean_sc, 6),
        "ci95": round(1.96 * sd_sc / math.sqrt(n) if n > 1 else 0.0, 6),
        "accuracy": round(sum(corrects) / n, 6) if n else 0.0,
        "accuse_rate": round(sum(accused_flags) / n, 6) if n else 0.0,
        "wrong_accusations": sum(wrong_flags),
        "mean_accuse_day": round(sum(accuse_days) / len(accuse_days), 4) if accuse_days else None,
        "tool_calls": tool_calls,
        "episodes": fresh_episodes,
        "n_seeds": n,
    }


def run_solver_with_snapshots(tier: str, seed: int, cuts: tuple[int, ...] = ()) -> dict[str, Any]:
    env = make_env(tier, seed)
    pol = make_policy_factory("solver")(seed)
    pol.reset(env.tools_spec(), env.instruction())
    done_at: dict[int, bool] = {}
    score_at: dict[int, float] = {}
    v_at: dict[int, float] = {}
    day_at: dict[int, int] = {}
    while not env.done and len(env.history) < 1000:
        idx = len(env.history)
        done_at[idx] = bool(env.done)
        score_at[idx] = float(env.score())
        v_at[idx] = round(env.V, 10)
        day_at[idx] = int(env.day)
        tool, args = pol.act(list(env.history))
        env.call(tool, args)
    n_calls = len(env.history)
    done_at[n_calls] = bool(env.done)
    score_at[n_calls] = float(env.score())
    v_at[n_calls] = round(env.V, 10)
    day_at[n_calls] = int(env.day)
    res = env.result("solver")
    actions = [(st.tool, st.args) for st in res.steps]
    out: dict[str, Any] = {
        "score": float(res.score),
        "correct": bool(res.correct),
        "accused": res.accused,
        "final_day": int(res.final_day),
        "end_reason": res.end_reason,
        "V": float(env.verdict()["V"]),
        "n_calls": n_calls,
        "actions": actions,
    }
    if cuts:
        true_mole = env._world.mole
        wrong_sc = float(env.p.wrong_accusation_score)
        verdict_final = env.verdict()
        need_idx: set[int] = {0, 1}
        for pct in cuts:
            k = (n_calls * pct) // 100
            need_idx.add(k)
            need_idx.add(max(0, k - 1))
            need_idx.add(min(n_calls, k + 1))
        bpol = make_policy_factory("solver")(seed)
        bpol.reset(env.tools_spec(), env.instruction())
        belief_after_prefix: dict[int, str | None] = {}

        def top_cand() -> str | None:
            p_cur = bpol.belief()
            return max(sorted(p_cur), key=lambda e: p_cur[e]) if p_cur else None

        if 0 in need_idx:
            belief_after_prefix[0] = top_cand()
        for idx, st in enumerate(res.steps, start=1):
            bpol._ingest(st)
            if idx in need_idx or belief_after_prefix.get(idx - 1) is None:
                belief_after_prefix[idx] = top_cand()

        stop_scores: dict[int, float] = {}
        guess_scores: dict[int, float] = {}
        guess_post_ingest_scores: dict[int, float] = {}
        guess_correct: dict[int, bool] = {}
        guess_days: dict[int, int] = {}

        for pct in cuts:
            k = (n_calls * pct) // 100
            stop_scores[pct] = score_at[k]

            if done_at[k]:
                guess_scores[pct] = score_at[k]
                guess_correct[pct] = bool(verdict_final["correct"])
                guess_days[pct] = day_at[k]
            else:
                t_cur = k
                acc_cand: str | None = None
                while not done_at[t_cur] and t_cur <= n_calls:
                    ingested_len = max(0, t_cur - 1)
                    cand = belief_after_prefix.get(ingested_len)
                    if cand is not None:
                        acc_cand = cand
                        break
                    if t_cur < n_calls:
                        t_cur += 1
                    else:
                        break
                if acc_cand is not None and not done_at[t_cur]:
                    is_cor = acc_cand == true_mole
                    guess_scores[pct] = v_at[t_cur] if is_cor else wrong_sc
                    guess_correct[pct] = bool(is_cor)
                    guess_days[pct] = day_at[t_cur]
                else:
                    guess_scores[pct] = score_at[t_cur]
                    guess_correct[pct] = bool(verdict_final["correct"]) if done_at[t_cur] else False
                    guess_days[pct] = day_at[t_cur]

            if done_at[k]:
                guess_post_ingest_scores[pct] = score_at[k]
            else:
                t_post = k
                cand_post = belief_after_prefix.get(k)
                if cand_post is None and n_calls > 0:
                    t_post = 1
                    cand_post = belief_after_prefix.get(1)
                if cand_post is not None and not done_at[t_post]:
                    guess_post_ingest_scores[pct] = v_at[t_post] if cand_post == true_mole else wrong_sc
                else:
                    guess_post_ingest_scores[pct] = score_at[t_post]

        acc_idx = [i for i, (t, _) in enumerate(actions) if t == "accuse"]
        minus_k = acc_idx[-1] if acc_idx else n_calls
        out["effort"] = {
            "stop_scores": stop_scores,
            "minus_accuse_score": score_at[minus_k],
            "guess_scores": guess_scores,
            "guess_post_ingest_scores": guess_post_ingest_scores,
            "guess_correct": guess_correct,
            "guess_days": guess_days,
        }
    return out


def run_evolutionary_search(quick: bool = False, seed: int = 20261115) -> dict[str, Any]:
    rng = random.Random(seed)
    train_seeds = [DEV_TRAIN_SEEDS[0]] if quick else list(DEV_TRAIN_SEEDS)
    oos_dev_seeds = [30201] if quick else list(DEV_OOS_SEEDS)
    judge_seeds = [900004] if quick else list(JUDGE_OOS_SEEDS)

    n_grid = 2 if quick else 560
    n_gens = 1 if quick else 12
    offspring_per_gen = 1 if quick else 40
    rl_promo_count = 1 if quick else 48
    semifinal_count = 1 if quick else 16
    semifinal_seeds_per_tier = 1 if quick else 15
    final_count = 1 if quick else 6

    total_tool_calls = 0
    total_episodes = 0
    policy_eval_records: dict[HeuristicConfig, dict[str, float]] = {}
    train_ep_cache: dict[tuple[HeuristicConfig, str, int], dict[str, Any]] = {}

    grid_configs = build_structured_grid(n_grid, seed=seed)

    def fast_screen(cfg: HeuristicConfig, idx: int) -> dict[str, float]:
        nonlocal total_tool_calls, total_episodes
        if cfg in policy_eval_records:
            return policy_eval_records[cfg]
        by_t: dict[str, float] = {}
        for t_i, t in enumerate(FAST_SCREEN_TARGETS):
            s = train_seeds[(idx + 7 * t_i) % len(train_seeds)]
            r = eval_policy_on_seeds(cfg, t, (s,), ep_cache=train_ep_cache)
            total_tool_calls += int(r["tool_calls"])
            total_episodes += int(r["episodes"])
            by_t[t] = float(r["mean"])
        by_t["hard_rl"] = 0.5 * (by_t["hard"] + by_t["hard_forge"])
        by_t["overall"] = sum(by_t[t] for t in ALL_TARGETS) / len(ALL_TARGETS)
        by_t["hard_trio"] = sum(by_t[t] for t in HARD_TARGETS) / len(HARD_TARGETS)
        by_t["screen_idx"] = float(idx)
        policy_eval_records[cfg] = by_t
        return by_t

    def ensure_rl_screened(cfg: HeuristicConfig) -> None:
        nonlocal total_tool_calls, total_episodes
        rec = policy_eval_records[cfg]
        if rec.get("rl_measured"):
            return
        idx = int(rec.get("screen_idx", 0.0))
        s = train_seeds[(idx + 28) % len(train_seeds)]
        r = eval_policy_on_seeds(cfg, "hard_rl", (s,), ep_cache=train_ep_cache)
        total_tool_calls += int(r["tool_calls"])
        total_episodes += int(r["episodes"])
        rec["hard_rl"] = float(r["mean"])
        rec["overall"] = sum(rec[t] for t in ALL_TARGETS) / len(ALL_TARGETS)
        rec["hard_trio"] = sum(rec[t] for t in HARD_TARGETS) / len(HARD_TARGETS)
        rec["rl_measured"] = 1.0

    for idx, cfg in enumerate(grid_configs):
        fast_screen(cfg, idx)
    ensure_rl_screened(W2B008_CONFIG)

    objectives = ("overall", "hard", "hard_forge", "hard_rl")
    gen_history: list[dict[str, Any]] = []
    eval_counter = len(policy_eval_records)

    for gen in range(n_gens):
        elites_by_obj: dict[str, list[HeuristicConfig]] = {}
        for obj in objectives:
            ranked_cfgs = sorted(
                policy_eval_records.keys(),
                key=lambda c: (policy_eval_records[c][obj], policy_eval_records[c]["hard_trio"]),
                reverse=True,
            )
            top_slice = ranked_cfgs[: max(2, min(12, len(ranked_cfgs)))]
            for ec in top_slice[: (1 if quick else 3)]:
                ensure_rl_screened(ec)
            elites_by_obj[obj] = top_slice

        created = 0
        attempts = 0
        while created < offspring_per_gen and attempts < offspring_per_gen * 25:
            attempts += 1
            obj = objectives[created % len(objectives)]
            pool = elites_by_obj[obj]
            p1 = rng.choice(pool[: max(2, len(pool) // 2)])
            p2 = rng.choice(pool)
            child = crossover_configs(p1, p2, rng) if rng.random() < 0.65 else p1
            child = mutate_config(child, rng, n_genes=1 if rng.random() < 0.55 else 2)
            if child in policy_eval_records:
                continue
            fast_screen(child, eval_counter)
            eval_counter += 1
            created += 1

        gen_history.append(
            {
                "generation": gen + 1,
                "evaluated_policies": len(policy_eval_records),
                "best_screen_overall": round(max(v["overall"] for v in policy_eval_records.values()), 4),
                "best_screen_hard_trio": round(max(v["hard_trio"] for v in policy_eval_records.values()), 4),
            }
        )

    promo_ranked = sorted(
        policy_eval_records.keys(),
        key=lambda c: (policy_eval_records[c]["hard_trio"], policy_eval_records[c]["overall"]),
        reverse=True,
    )
    for cfg in promo_ranked[:rl_promo_count]:
        ensure_rl_screened(cfg)

    semifinalists: list[HeuristicConfig] = [W2B008_CONFIG]
    per_obj_quota = max(1, semifinal_count // len(objectives))
    for obj in objectives:
        ranked_cfgs = sorted(
            policy_eval_records.keys(),
            key=lambda c: (policy_eval_records[c][obj], policy_eval_records[c]["overall"]),
            reverse=True,
        )
        added = 0
        for c in ranked_cfgs:
            if c not in semifinalists:
                semifinalists.append(c)
                added += 1
                if added >= per_obj_quota or len(semifinalists) >= semifinal_count + 1:
                    break

    semi_seeds = train_seeds[: min(len(train_seeds), semifinal_seeds_per_tier)]
    semi_scores: dict[HeuristicConfig, dict[str, float]] = {}
    for cfg in semifinalists:
        row: dict[str, float] = {}
        for t in ALL_TARGETS:
            r = eval_policy_on_seeds(cfg, t, semi_seeds, ep_cache=train_ep_cache)
            total_tool_calls += int(r["tool_calls"])
            total_episodes += int(r["episodes"])
            row[t] = float(r["mean"])
        row["overall"] = sum(row[t] for t in ALL_TARGETS) / len(ALL_TARGETS)
        row["hard_trio"] = sum(row[t] for t in HARD_TARGETS) / len(HARD_TARGETS)
        semi_scores[cfg] = row

    finalists: list[HeuristicConfig] = [W2B008_CONFIG]
    for obj in ("overall", "hard", "hard_forge", "hard_rl", "hard_trio", "medium"):
        ranked_semi = sorted(
            semifinalists,
            key=lambda c: (semi_scores[c][obj], semi_scores[c]["overall"]),
            reverse=True,
        )
        for c in ranked_semi:
            if c not in finalists:
                finalists.append(c)
                break
        if len(finalists) >= final_count + 1:
            break

    train_full_results: dict[HeuristicConfig, dict[str, Any]] = {}
    for cfg in finalists:
        t_res: dict[str, Any] = {}
        for t in ALL_TARGETS:
            r = eval_policy_on_seeds(cfg, t, train_seeds, ep_cache=train_ep_cache)
            total_tool_calls += int(r["tool_calls"])
            total_episodes += int(r["episodes"])
            t_res[t] = r
        t_res["overall_mean"] = sum(t_res[t]["mean"] for t in ALL_TARGETS) / len(ALL_TARGETS)
        t_res["hard_trio_mean"] = sum(t_res[t]["mean"] for t in HARD_TARGETS) / len(HARD_TARGETS)
        train_full_results[cfg] = t_res

    evolved_pool = [c for c in finalists if c != W2B008_CONFIG]
    survivors: list[tuple[str, HeuristicConfig]] = [("swarm_w2b008", W2B008_CONFIG)]
    used_surv: set[HeuristicConfig] = {W2B008_CONFIG}
    selection_specs = (
        ("evo_best_overall", lambda c: train_full_results[c]["overall_mean"]),
        ("evo_best_hard", lambda c: train_full_results[c]["hard"]["mean"]),
        ("evo_best_hard_forge", lambda c: train_full_results[c]["hard_forge"]["mean"]),
        ("evo_best_hard_rl", lambda c: train_full_results[c]["hard_rl"]["mean"]),
        ("evo_best_hard_trio", lambda c: train_full_results[c]["hard_trio_mean"]),
    )
    max_evolved = 1 if quick else 5
    for label, key_fn in selection_specs:
        if len(survivors) >= 1 + max_evolved:
            break
        candidates = sorted(evolved_pool, key=key_fn, reverse=True)
        chosen_cfg = next((c for c in candidates if c not in used_surv), None)
        if chosen_cfg is None and candidates:
            continue
        if chosen_cfg is not None:
            used_surv.add(chosen_cfg)
            survivors.append((label, chosen_cfg))

    effort_seed_set = {30201} if quick else set(EFFORT_SEEDS)
    solver_dev_oos: dict[str, dict[int, dict[str, Any]]] = {t: {} for t in ALL_TARGETS}
    for t in ALL_TARGETS:
        need_cuts = EFFORT_CUTS if t in EFFORT_TARGETS else ()
        for s in oos_dev_seeds:
            cuts_for_seed = need_cuts if s in effort_seed_set else ()
            snap = run_solver_with_snapshots(t, s, cuts=cuts_for_seed)
            total_tool_calls += int(snap["n_calls"])
            total_episodes += 1
            solver_dev_oos[t][s] = snap

    solver_judge_pub: dict[str, dict[int, dict[str, Any]]] = {t: {} for t in ALL_TARGETS}
    set_world_secret(PUBLIC_TEST_SECRET)
    try:
        for t in ALL_TARGETS:
            need_cuts = EFFORT_CUTS if t in EFFORT_TARGETS else ()
            for s in judge_seeds:
                snap = run_solver_with_snapshots(t, s, cuts=need_cuts)
                total_tool_calls += int(snap["n_calls"])
                total_episodes += 1
                solver_judge_pub[t][s] = snap
    finally:
        set_world_secret(None)

    def evaluate_survivors_on_split(
        split_seeds: list[int],
        solver_map: dict[str, dict[int, dict[str, Any]]],
        world_secret: bytes | None,
        boot_base: int,
    ) -> dict[str, Any]:
        nonlocal total_tool_calls, total_episodes
        if world_secret is not None:
            set_world_secret(world_secret)
        try:
            by_policy: dict[str, Any] = {}
            solver_summary: dict[str, Any] = {}
            for t in ALL_TARGETS:
                s_scores = [solver_map[t][s]["score"] for s in split_seeds]
                s_cor = [solver_map[t][s]["correct"] for s in split_seeds]
                s_acc = [solver_map[t][s]["accused"] is not None for s in split_seeds]
                s_wrong = [bool(a and not c) for a, c in zip(s_acc, s_cor)]
                s_days = [solver_map[t][s]["final_day"] for s in split_seeds if solver_map[t][s]["end_reason"] == "accused"]
                m_s = sum(s_scores) / len(s_scores)
                sd_s = math.sqrt(sum((x - m_s) ** 2 for x in s_scores) / (len(s_scores) - 1)) if len(s_scores) > 1 else 0.0
                solver_summary[t] = {
                    "n": len(s_scores),
                    "mean": round(m_s, 6),
                    "ci95": round(1.96 * sd_s / math.sqrt(len(s_scores)) if len(s_scores) > 1 else 0.0, 6),
                    "accuracy": round(sum(s_cor) / len(s_cor), 6),
                    "accuse_rate": round(sum(s_acc) / len(s_acc), 6),
                    "wrong_accusations": sum(s_wrong),
                    "mean_accuse_day": round(sum(s_days) / len(s_days), 4) if s_days else None,
                }

            for p_idx, (label, cfg) in enumerate(survivors):
                tiers_out: dict[str, Any] = {}
                for t_idx, t in enumerate(ALL_TARGETS):
                    r = eval_policy_on_seeds(cfg, t, split_seeds, name=label)
                    total_tool_calls += int(r["tool_calls"])
                    total_episodes += int(r["episodes"])
                    s_scores = [solver_map[t][s]["score"] for s in split_seeds]
                    pstats = paired_bootstrap_stats(
                        r["scores"],
                        s_scores,
                        n_boot=1000 if quick else 4000,
                        boot_seed=boot_base + 100 * p_idx + t_idx,
                    )
                    tiers_out[t] = {
                        "mean": r["mean"],
                        "ci95": r["ci95"],
                        "accuracy": r["accuracy"],
                        "accuse_rate": r["accuse_rate"],
                        "wrong_accusations": r["wrong_accusations"],
                        "mean_accuse_day": r["mean_accuse_day"],
                        "paired_vs_solver": pstats,
                    }
                by_policy[label] = {
                    "config": cfg.to_dict(),
                    "short_label": cfg.short_label(),
                    "tiers": tiers_out,
                }
            return {"n_seeds": len(split_seeds), "solver": solver_summary, "policies": by_policy}
        finally:
            if world_secret is not None:
                set_world_secret(None)

    dev_oos_eval = evaluate_survivors_on_split(oos_dev_seeds, solver_dev_oos, None, boot_base=70000)
    judge_pub_eval = evaluate_survivors_on_split(judge_seeds, solver_judge_pub, PUBLIC_TEST_SECRET, boot_base=90000)

    any_hard_beat_dev = any(
        dev_oos_eval["policies"][lbl]["tiers"][t]["paired_vs_solver"]["beats_solver_in_mean"]
        for lbl in dev_oos_eval["policies"]
        for t in HARD_TARGETS
    )
    any_hard_sig_dev = any(
        dev_oos_eval["policies"][lbl]["tiers"][t]["paired_vs_solver"]["significantly_above_solver"]
        for lbl in dev_oos_eval["policies"]
        for t in HARD_TARGETS
    )
    any_hard_sig_judge = any(
        judge_pub_eval["policies"][lbl]["tiers"][t]["paired_vs_solver"]["significantly_above_solver"]
        for lbl in judge_pub_eval["policies"]
        for t in HARD_TARGETS
    )
    solver_hard_trio_dev = sum(dev_oos_eval["solver"][t]["mean"] for t in HARD_TARGETS) / len(HARD_TARGETS)
    solver_hard_trio_judge = sum(judge_pub_eval["solver"][t]["mean"] for t in HARD_TARGETS) / len(HARD_TARGETS)
    any_hard_trio_beat_dev = any(
        (sum(dev_oos_eval["policies"][lbl]["tiers"][t]["mean"] for t in HARD_TARGETS) / len(HARD_TARGETS))
        > solver_hard_trio_dev + 1e-9
        for lbl in dev_oos_eval["policies"]
    )
    any_hard_trio_beat_judge = any(
        (sum(judge_pub_eval["policies"][lbl]["tiers"][t]["mean"] for t in HARD_TARGETS) / len(HARD_TARGETS))
        > solver_hard_trio_judge + 1e-9
        for lbl in judge_pub_eval["policies"]
    )

    train_summary = {
        lbl: {
            "config": cfg.to_dict(),
            "overall_mean": round(train_full_results[cfg]["overall_mean"], 6),
            "hard_trio_mean": round(train_full_results[cfg]["hard_trio_mean"], 6),
            "tiers": {t: round(train_full_results[cfg][t]["mean"], 6) for t in ALL_TARGETS},
        }
        for lbl, cfg in survivors
    }

    return {
        "search_stats": {
            "distinct_policies_evaluated": len(policy_eval_records),
            "semifinalists_evaluated": len(semifinalists),
            "finalists_evaluated_full_train": len(finalists),
            "survivors_evaluated_oos": len(survivors),
            "total_episodes": total_episodes,
            "total_tool_calls": total_tool_calls,
            "train_seeds_range": f"{train_seeds[0]}-{train_seeds[-1]}",
            "dev_oos_seeds_range": f"{oos_dev_seeds[0]}-{oos_dev_seeds[-1]}",
            "judge_public_seeds_range": f"{judge_seeds[0]}-{judge_seeds[-1]}",
            "generations": gen_history,
        },
        "train_survivors": train_summary,
        "dev_oos": dev_oos_eval,
        "judge_public": judge_pub_eval,
        "verdicts": {
            "any_survivor_beats_solver_mean_on_hard_targets_dev_oos": any_hard_beat_dev,
            "any_survivor_significantly_above_solver_on_hard_targets_dev_oos": any_hard_sig_dev,
            "any_survivor_significantly_above_solver_on_hard_targets_judge": any_hard_sig_judge,
            "any_survivor_beats_solver_hard_trio_dev_oos": any_hard_trio_beat_dev,
            "any_survivor_beats_solver_hard_trio_judge": any_hard_trio_beat_judge,
        },
        "_solver_dev_oos_cache": solver_dev_oos,
        "_solver_judge_pub_cache": solver_judge_pub,
    }


def summarize_effort_ladder(
    solver_cache: dict[str, dict[int, dict[str, Any]]],
    seeds: list[int],
    boot_base: int = 50000,
    n_boot: int = 4000,
) -> dict[str, Any]:
    by_target: dict[str, Any] = {}
    all_stop_zero = True
    all_guess_below_solver = True
    total_probe_episodes = 0

    for t_idx, tier in enumerate(EFFORT_TARGETS):
        full_scores = [solver_cache[tier][s]["score"] for s in seeds]
        full_cor = [solver_cache[tier][s]["correct"] for s in seeds]
        full_calls = [solver_cache[tier][s]["n_calls"] for s in seeds]
        minus_scores = [solver_cache[tier][s]["effort"]["minus_accuse_score"] for s in seeds]
        minus_nonzero = sum(1 for x in minus_scores if abs(x) > 1e-12)
        if minus_nonzero > 0:
            all_stop_zero = False

        cuts_summary: dict[str, Any] = {}
        for c_idx, pct in enumerate(EFFORT_CUTS):
            stop_sc = [solver_cache[tier][s]["effort"]["stop_scores"][pct] for s in seeds]
            guess_sc = [solver_cache[tier][s]["effort"]["guess_scores"][pct] for s in seeds]
            post_sc = [solver_cache[tier][s]["effort"]["guess_post_ingest_scores"][pct] for s in seeds]
            guess_cor = [solver_cache[tier][s]["effort"]["guess_correct"][pct] for s in seeds]
            guess_day = [solver_cache[tier][s]["effort"]["guess_days"][pct] for s in seeds]
            total_probe_episodes += 3 * len(seeds)

            nonzero_stop = sum(1 for x in stop_sc if abs(x) > 1e-12)
            if nonzero_stop > 0:
                all_stop_zero = False

            p_upstream = paired_bootstrap_stats(
                guess_sc,
                full_scores,
                n_boot=n_boot,
                boot_seed=boot_base + 100 * t_idx + c_idx,
            )
            p_postingest = paired_bootstrap_stats(
                post_sc,
                full_scores,
                n_boot=n_boot,
                boot_seed=boot_base + 500 + 100 * t_idx + c_idx,
            )
            strictly_below = bool(p_upstream["paired_mean_diff"] < -1e-9 and p_postingest["paired_mean_diff"] < -1e-9)
            if not strictly_below:
                all_guess_below_solver = False

            cuts_summary[f"{pct}%"] = {
                "pct": pct,
                "n": len(seeds),
                "stop_without_accusing_mean": round(sum(stop_sc) / len(stop_sc), 6),
                "stop_without_accusing_max_abs": round(max(abs(x) for x in stop_sc), 12),
                "stop_without_accusing_nonzero_count": nonzero_stop,
                "cut_guess_mean": p_upstream["policy_mean"],
                "cut_guess_accuracy": round(sum(guess_cor) / len(guess_cor), 6),
                "cut_guess_mean_day": round(sum(guess_day) / len(guess_day), 4),
                "cut_guess_vs_solver": p_upstream,
                "post_ingest_guess_mean": p_postingest["policy_mean"],
                "post_ingest_guess_vs_solver": p_postingest,
                "strictly_below_full_solver": strictly_below,
            }

        full_mean = sum(full_scores) / len(full_scores)
        full_sd = math.sqrt(sum((x - full_mean) ** 2 for x in full_scores) / (len(full_scores) - 1)) if len(full_scores) > 1 else 0.0
        by_target[tier] = {
            "n_seeds": len(seeds),
            "seeds_range": f"{seeds[0]}-{seeds[-1]}",
            "full_solver_mean": round(full_mean, 6),
            "full_solver_ci95": round(1.96 * full_sd / math.sqrt(len(full_scores)) if len(full_scores) > 1 else 0.0, 6),
            "full_solver_accuracy": round(sum(full_cor) / len(full_cor), 6),
            "full_solver_mean_calls": round(sum(full_calls) / len(full_calls), 2),
            "solver_minus_accuse_nonzero_count": minus_nonzero,
            "cuts": cuts_summary,
        }

    return {
        "targets": by_target,
        "total_partial_play_episodes": total_probe_episodes,
        "all_stop_without_accusing_exact_zero": all_stop_zero,
        "all_early_argmax_strictly_below_solver": all_guess_below_solver,
    }


def _hashseed_worker_main(spec_arg: str) -> int:
    if "|" in spec_arg:
        seeds_csv, rollout_csv, world_csv = (spec_arg.split("|") + [""])[:3]
        rollout_tiers = tuple(x for x in rollout_csv.split(",") if x.strip())
        world_tiers = tuple(x for x in world_csv.split(",") if x.strip()) or ALL_TARGETS
    else:
        seeds_csv = spec_arg
        rollout_tiers = ALL_TARGETS
        world_tiers = ALL_TARGETS
    seeds = [int(x) for x in seeds_csv.split(",") if x.strip()]
    set_world_secret(PUBLIC_TEST_SECRET)
    try:
        cells: dict[str, Any] = {}
        for tier in world_tiers:
            p = tier_params(tier)
            for s in seeds:
                w = generate_world(tier, s, p)
                w_dict = {
                    "tier": w.tier,
                    "seed": w.seed,
                    "world_seed": w.world_seed,
                    "company": w.company,
                    "employees": [asdict(e) for e in w.employees],
                    "depts": list(w.depts),
                    "mole": w.mole,
                    "decoy": w.decoy,
                    "planned_docs": w.planned_docs,
                }
                w_sha = hashlib.sha256(json.dumps(w_dict, sort_keys=True).encode("utf-8")).hexdigest()
                if tier in rollout_tiers:
                    env = make_env(tier, s)
                    res = run_episode(env, make_policy_factory("solver")(s))
                    steps_blob = json.dumps([asdict(st) for st in res.steps], sort_keys=True).encode("utf-8")
                    ledger_blob = json.dumps([asdict(le) for le in env.ledger()], sort_keys=True).encode("utf-8")
                    verdict = env.verdict()
                    cells[f"{tier}:{s}"] = {
                        "world_sha256": w_sha,
                        "tool_outputs_sha256": hashlib.sha256(steps_blob).hexdigest(),
                        "ledger_sha256": hashlib.sha256(ledger_blob).hexdigest(),
                        "score": float(res.score),
                        "V": float(verdict["V"]),
                        "accused": res.accused,
                        "correct": bool(res.correct),
                        "final_day": int(res.final_day),
                        "n_steps": len(res.steps),
                    }
                else:
                    cells[f"{tier}:{s}"] = {
                        "world_sha256": w_sha,
                        "n_steps": 0,
                    }
        payload = {
            "pythonhashseed_env": os.environ.get("PYTHONHASHSEED"),
            "probe_str_hash": hash("canary_v14_hashseed_probe_token"),
            "cells": cells,
        }
        print(json.dumps(payload, sort_keys=True))
        return 0
    finally:
        set_world_secret(None)


def run_pythonhashseed_audit(quick: bool = False) -> dict[str, Any]:
    seeds = (30201,) if quick else (30201, 30205, 900000)
    rollout_tiers = ("easy",) if quick else ALL_TARGETS
    world_tiers = ("easy", "medium", "hard") if quick else ALL_TARGETS
    hash_seeds = (0, 2147483647) if quick else HASH_SEEDS
    spec_arg = (
        ",".join(str(s) for s in seeds)
        + "|"
        + ",".join(rollout_tiers)
        + "|"
        + ",".join(world_tiers)
    )
    by_hs: dict[int, dict[str, Any]] = {}
    probe_hashes: dict[str, int] = {}

    for hs in hash_seeds:
        child_env = dict(os.environ)
        child_env["PYTHONHASHSEED"] = str(hs)
        child_env["PYTHONPATH"] = str(REPO_ROOT)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--hashseed-worker", spec_arg],
            cwd=REPO_ROOT,
            env=child_env,
            capture_output=True,
            text=True,
            timeout=180,
            check=True,
        )
        parsed = json.loads(proc.stdout)
        by_hs[hs] = parsed["cells"]
        probe_hashes[str(hs)] = int(parsed["probe_str_hash"])

    ref = by_hs[hash_seeds[0]]
    mismatches: list[str] = []
    for hs in hash_seeds[1:]:
        cur = by_hs[hs]
        for cell_key, ref_val in ref.items():
            if cur.get(cell_key) != ref_val:
                mismatches.append(f"PYTHONHASHSEED={hs} mismatch at {cell_key}")

    total_rollouts = len(hash_seeds) * len(rollout_tiers) * len(seeds)
    total_steps = sum(int(v["n_steps"]) for d in by_hs.values() for v in d.values())
    return {
        "hash_seeds_tested": list(hash_seeds),
        "targets_tested": list(ALL_TARGETS),
        "rollout_targets_tested": list(rollout_tiers),
        "episode_seeds_tested": list(seeds),
        "subprocess_rollouts": total_rollouts,
        "subprocess_tool_calls": total_steps,
        "distinct_builtin_str_hashes": len(set(probe_hashes.values())),
        "builtin_str_hashes": probe_hashes,
        "mismatches": mismatches,
        "bit_identical": len(mismatches) == 0,
        "reference_cells": ref,
    }


def _keyed_hard_mole_index(secret: bytes, seed: int) -> int:
    from canary.world import COMPANIES, DEPTS, FIRST, LAST, ROLES

    p = tier_params("hard")
    ws = int.from_bytes(hmac.new(secret, f"hard:{seed}".encode("utf-8"), hashlib.sha256).digest()[:8], "big")
    rng = random.Random(ws)
    n = p.n_employees
    depts = DEPTS[:5]
    _ = rng.choice(COMPANIES)
    names: set[str] = set()
    for i in range(n):
        while True:
            nm = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if nm not in names:
                names.add(nm)
                break
        dept = depts[i % len(depts)] if i < len(depts) else rng.choice(depts)
        _ = rng.choice(ROLES[dept])
        if p.access_constraints:
            _ = rng.randint(1, 3)
    ids = [f"e{i:02d}" for i in range(n)]
    decoy = rng.choice(ids) if p.decoy else None
    mole = rng.choice([i for i in ids if i != decoy])
    return int(mole[1:])


def sequence_chisq_metrics(
    sequences: list[list[int]],
    n_states: int = 40,
    lags: tuple[int, ...] = (1, 2, 3, 4, 5),
    mc_trials: int = 2000,
    mc_seed: int = 314159,
) -> dict[str, Any]:
    import numpy as np

    flat = [x for seq in sequences for x in seq]
    total_n = len(flat)
    counts = Counter(flat)
    exp_marginal = total_n / float(n_states)
    chi2_marginal = sum(((counts.get(i, 0) - exp_marginal) ** 2) / exp_marginal for i in range(n_states))
    p_marginal = chi2_sf(chi2_marginal, n_states - 1)

    rng = np.random.default_rng(mc_seed)
    seq_lengths = [len(seq) for seq in sequences]

    lag_results: dict[str, Any] = {}
    for lag in lags:
        pairs: list[tuple[int, int]] = []
        for seq in sequences:
            for idx in range(lag, len(seq)):
                pairs.append((seq[idx - lag], seq[idx]))
        n_pairs = len(pairs)
        arr = np.asarray(pairs, dtype=np.int64)
        prev_arr = arr[:, 0]
        curr_arr = arr[:, 1]

        b_prev = prev_arr // 10
        b_curr = curr_arr // 10
        tab4 = np.zeros((4, 4), dtype=np.float64)
        np.add.at(tab4, (b_prev, b_curr), 1.0)
        row4 = tab4.sum(axis=1, keepdims=True)
        col4 = tab4.sum(axis=0, keepdims=True)
        exp4 = (row4 @ col4) / float(n_pairs)
        with np.errstate(divide="ignore", invalid="ignore"):
            chi2_b4 = float(np.nansum(((tab4 - exp4) ** 2) / np.where(exp4 > 0, exp4, np.nan)))
        p_b4 = chi2_sf(chi2_b4, 9)

        m_prev = prev_arr % 5
        m_curr = curr_arr % 5
        tab5 = np.zeros((5, 5), dtype=np.float64)
        np.add.at(tab5, (m_prev, m_curr), 1.0)
        row5 = tab5.sum(axis=1, keepdims=True)
        col5 = tab5.sum(axis=0, keepdims=True)
        exp5 = (row5 @ col5) / float(n_pairs)
        with np.errstate(divide="ignore", invalid="ignore"):
            chi2_m5 = float(np.nansum(((tab5 - exp5) ** 2) / np.where(exp5 > 0, exp5, np.nan)))
        p_m5 = chi2_sf(chi2_m5, 16)

        repeats = int(np.sum(prev_arr == curr_arr))
        exp_rep = n_pairs / float(n_states)
        exp_non = n_pairs - exp_rep
        chi2_rep = ((repeats - exp_rep) ** 2) / exp_rep + (((n_pairs - repeats) - exp_non) ** 2) / exp_non
        p_rep = chi2_sf(chi2_rep, 1)

        tab_full = np.zeros((n_states, n_states), dtype=np.float64)
        np.add.at(tab_full, (prev_arr, curr_arr), 1.0)
        exp_cell = n_pairs / float(n_states * n_states)
        chi2_full_uniform = float(np.sum(((tab_full - exp_cell) ** 2) / exp_cell))

        sim_blocks = [rng.integers(0, n_states, size=(mc_trials, slen)) for slen in seq_lengths]
        sp_mat = np.concatenate([blk[:, :-lag] for blk in sim_blocks], axis=1)
        sc_mat = np.concatenate([blk[:, lag:] for blk in sim_blocks], axis=1)
        flat_mat = sp_mat * n_states + sc_mat
        n_cells = n_states * n_states
        offsets = (np.arange(mc_trials, dtype=np.int64)[:, None]) * n_cells
        all_bins = np.bincount((flat_mat + offsets).ravel(), minlength=mc_trials * n_cells).reshape(mc_trials, n_cells)
        sim_stats = np.sum(((all_bins.astype(np.float64) - exp_cell) ** 2) / exp_cell, axis=1)
        exceed = int(np.sum(sim_stats >= chi2_full_uniform - 1e-12))
        p_full_mc = (exceed + 1.0) / (mc_trials + 1.0)

        p_f = prev_arr.astype(np.float64)
        c_f = curr_arr.astype(np.float64)
        p_cent = p_f - p_f.mean()
        c_cent = c_f - c_f.mean()
        denom = float(np.sqrt(np.sum(p_cent ** 2) * np.sum(c_cent ** 2)))
        r_lag = float(np.sum(p_cent * c_cent) / denom) if denom > 0 else 0.0

        lag_results[f"lag_{lag}"] = {
            "lag": lag,
            "n_transitions": n_pairs,
            "bucket4x4_chi2": round(chi2_b4, 4),
            "bucket4x4_df": 9,
            "bucket4x4_p": round(p_b4, 6),
            "dept_mod5x5_chi2": round(chi2_m5, 4),
            "dept_mod5x5_df": 16,
            "dept_mod5x5_p": round(p_m5, 6),
            "repeat_count": repeats,
            "repeat_expected": round(exp_rep, 3),
            "repeat_chi2": round(chi2_rep, 4),
            "repeat_p": round(p_rep, 6),
            "full40x40_chi2": round(chi2_full_uniform, 4),
            "full40x40_mc_p": round(p_full_mc, 6),
            "autocorr_r": round(r_lag, 6),
        }

    return {
        "n_sequences": len(sequences),
        "total_worlds": total_n,
        "n_states": n_states,
        "marginal_chi2": round(chi2_marginal, 4),
        "marginal_df": n_states - 1,
        "marginal_p": round(p_marginal, 6),
        "min_state_count": min(counts.get(i, 0) for i in range(n_states)),
        "max_state_count": max(counts.get(i, 0) for i in range(n_states)),
        "expected_state_count": round(exp_marginal, 3),
        "lags": lag_results,
    }


def run_seed_autocorrelation_audit(quick: bool = False) -> dict[str, Any]:
    n_secrets = 2 if quick else 5
    mc_trials = 80 if quick else 2000
    live_900k_seeds = tuple(range(900000, 900045)) if quick else JUDGE_AUTOCORR_SEEDS
    live_800k_seeds = tuple(range(800000, 800045)) if quick else HELDOUT_AUTOCORR_SEEDS
    secrets_list = [
        hashlib.sha256(f"canary-c1w2-audit-fresh-secret-{idx}".encode("utf-8")).digest()
        for idx in range(n_secrets)
    ]
    p_hard = tier_params("hard")

    set_world_secret(secrets_list[0])
    try:
        w_sec0 = [generate_world("hard", s, p_hard) for s in live_900k_seeds]
    finally:
        set_world_secret(None)

    set_world_secret(secrets_list[1])
    try:
        w_sec1 = [generate_world("hard", s, p_hard) for s in live_900k_seeds]
    finally:
        set_world_secret(None)

    secret_sensitive_seeds = [
        s for s, w0, w1 in zip(live_900k_seeds, w_sec0, w_sec1) if w0.world_seed != w1.world_seed
    ]
    public_fallback_seeds = [
        s for s, w0, w1 in zip(live_900k_seeds, w_sec0, w_sec1) if w0.world_seed == w1.world_seed
    ]

    old_allow = os.environ.pop("CANARY_ALLOW_DEV", None)
    try:
        mcp_allowed_900000_900039 = sum(1 for s in range(900000, 900040) if seed_allowed(s))
        mcp_allowed_900040_900199 = sum(1 for s in range(900040, 900200) if seed_allowed(s))
    finally:
        if old_allow is not None:
            os.environ["CANARY_ALLOW_DEV"] = old_allow

    helper_matches_live = sum(
        1
        for idx, s in enumerate(JUDGE_PUBLIC_SEEDS)
        if _keyed_hard_mole_index(secrets_list[0], s) == int(w_sec0[idx].mole[1:])
    )

    keyed_900k_seqs = [
        [_keyed_hard_mole_index(sec, s) for s in JUDGE_AUTOCORR_SEEDS]
        for sec in secrets_list
    ]
    single_200_keyed = sequence_chisq_metrics([keyed_900k_seqs[0]], mc_trials=mc_trials, mc_seed=101)
    pooled_keyed_900k = sequence_chisq_metrics(keyed_900k_seqs, mc_trials=mc_trials, mc_seed=202)

    live_900k_seq0 = [int(w.mole[1:]) for w in w_sec0]
    live_200_generate_world = sequence_chisq_metrics([live_900k_seq0], mc_trials=mc_trials, mc_seed=303)

    heldout_seqs: list[list[int]] = []
    for sec in secrets_list:
        set_world_secret(sec)
        try:
            heldout_seqs.append([int(generate_world("hard", s, p_hard).mole[1:]) for s in live_800k_seeds])
        finally:
            set_world_secret(None)
    pooled_heldout_800k = sequence_chisq_metrics(heldout_seqs, mc_trials=mc_trials, mc_seed=404)

    if quick:
        judge40_seqs = [
            [int(w.mole[1:]) for w in w_sec0[:40]],
            [int(w.mole[1:]) for w in w_sec1[:40]],
        ]
    else:
        judge40_secrets = [
            hashlib.sha256(f"canary-c1w2-judge40-batch-{idx}".encode("utf-8")).digest()
            for idx in range(25)
        ]
        judge40_seqs = []
        for sec in judge40_secrets:
            set_world_secret(sec)
            try:
                judge40_seqs.append([int(generate_world("hard", s, p_hard).mole[1:]) for s in JUDGE_PUBLIC_SEEDS])
            finally:
                set_world_secret(None)
    pooled_judge40 = sequence_chisq_metrics(judge40_seqs, mc_trials=mc_trials, mc_seed=505)

    def passes_uniform_and_lags(metrics: dict[str, Any], alpha: float = 0.005) -> bool:
        if metrics["marginal_p"] < alpha:
            return False
        for l_row in metrics["lags"].values():
            if l_row["bucket4x4_p"] < alpha or l_row["full40x40_mc_p"] < alpha:
                return False
        return True

    return {
        "boundary_forensics": {
            "judge_seeds_defined_range": f"{JUDGE_SEEDS.start}-{JUDGE_SEEDS.stop - 1}",
            "heldout_seeds_defined_range": f"{HELDOUT_SEEDS.start}-{HELDOUT_SEEDS.stop - 1}",
            "tested_range": "900000-900199",
            "secret_keyed_count_in_900000_900199": len(secret_sensitive_seeds),
            "public_key_fallback_count_in_900000_900199": len(public_fallback_seeds),
            "mcp_server_allowed_900000_900039": mcp_allowed_900000_900039,
            "mcp_server_allowed_900040_900199": mcp_allowed_900040_900199,
            "keyed_helper_exact_match_on_900000_900039": helper_matches_live,
        },
        "single_secret_keyed_900000_900199": single_200_keyed,
        "pooled_fresh_secrets_keyed_900000_900199": pooled_keyed_900k,
        "live_generate_world_900000_900199_sec0": live_200_generate_world,
        "pooled_live_heldout_800000_800199": pooled_heldout_800k,
        "pooled_live_judge_900000_900039": pooled_judge40,
        "zero_sequential_predictability": bool(
            helper_matches_live == len(JUDGE_PUBLIC_SEEDS)
            and mcp_allowed_900040_900199 == 0
            and passes_uniform_and_lags(single_200_keyed)
            and passes_uniform_and_lags(pooled_keyed_900k)
            and passes_uniform_and_lags(pooled_heldout_800k)
            and passes_uniform_and_lags(pooled_judge40)
        ),
    }


def run_full_audit(quick: bool = False) -> dict[str, Any]:
    t0 = time.monotonic()
    evo = run_evolutionary_search(quick=quick)
    solver_dev_cache = evo.pop("_solver_dev_oos_cache")
    solver_judge_cache = evo.pop("_solver_judge_pub_cache")

    effort_dev_seeds = [30201] if quick else list(EFFORT_SEEDS)
    effort_judge_seeds = [900004] if quick else list(JUDGE_OOS_SEEDS)
    effort_dev = summarize_effort_ladder(
        solver_dev_cache,
        effort_dev_seeds,
        boot_base=50000,
        n_boot=1000 if quick else 4000,
    )
    effort_judge = summarize_effort_ladder(
        solver_judge_cache,
        effort_judge_seeds,
        boot_base=60000,
        n_boot=1000 if quick else 4000,
    )

    hashseed = run_pythonhashseed_audit(quick=quick)
    autocorr = run_seed_autocorrelation_audit(quick=quick)
    elapsed_s = round(time.monotonic() - t0, 3)

    total_tool_calls = int(evo["search_stats"]["total_tool_calls"]) + int(hashseed["subprocess_tool_calls"])
    sample_gates_ok = True
    if not quick:
        sample_gates_ok = bool(
            not evo["verdicts"]["any_survivor_significantly_above_solver_on_hard_targets_dev_oos"]
            and not evo["verdicts"]["any_survivor_significantly_above_solver_on_hard_targets_judge"]
            and not evo["verdicts"]["any_survivor_beats_solver_hard_trio_dev_oos"]
            and not evo["verdicts"]["any_survivor_beats_solver_hard_trio_judge"]
            and effort_dev["all_early_argmax_strictly_below_solver"]
            and effort_judge["all_early_argmax_strictly_below_solver"]
        )
    passed_all = bool(
        sample_gates_ok
        and effort_dev["all_stop_without_accusing_exact_zero"]
        and effort_judge["all_stop_without_accusing_exact_zero"]
        and hashseed["bit_identical"]
        and autocorr["zero_sequential_predictability"]
    )

    return {
        "mode": "quick" if quick else "full",
        "elapsed_s": elapsed_s,
        "workers": 1,
        "live_llm_calls": 0,
        "total_tool_calls": total_tool_calls,
        "passed_all_integrity_gates": passed_all,
        "part_a_evolution": evo,
        "part_b_effort_ladder_dev_oos": effort_dev,
        "part_b_effort_ladder_judge_oos": effort_judge,
        "part_c_pythonhashseed": hashseed,
        "part_c_seed_autocorrelation": autocorr,
    }


def format_console_summary(report: dict[str, Any]) -> str:
    lines: list[str] = []
    st = report["part_a_evolution"]["search_stats"]
    lines.append(
        f"Mode={report['mode']} elapsed={report['elapsed_s']:.2f}s "
        f"policies={st['distinct_policies_evaluated']} tool_calls={report['total_tool_calls']} "
        f"gates_pass={report['passed_all_integrity_gates']}"
    )
    lines.append("Part A (Dev OOS Paired vs SolverPolicy):")
    dev_oos = report["part_a_evolution"]["dev_oos"]
    for lbl, pdata in dev_oos["policies"].items():
        cells = []
        for t in ALL_TARGETS:
            pv = pdata["tiers"][t]["paired_vs_solver"]
            cells.append(
                f"{t}:{pv['policy_mean']:+.3f} vs {pv['solver_mean']:+.3f} "
                f"(diff {pv['paired_mean_diff']:+.3f} [{pv['boot_ci95_lo']:+.3f},{pv['boot_ci95_hi']:+.3f}])"
            )
        lines.append(f"  {lbl}: " + " | ".join(cells))

    lines.append("Part B (Effort Ladder on hard_forge / hard_rl):")
    eb = report["part_b_effort_ladder_dev_oos"]
    for t in EFFORT_TARGETS:
        trow = eb["targets"][t]
        cuts_str = ", ".join(
            f"{k}:stop={v['stop_without_accusing_mean']:.3f}/guess={v['cut_guess_mean']:+.3f}"
            for k, v in trow["cuts"].items()
        )
        lines.append(f"  {t} (solver={trow['full_solver_mean']:+.3f}): {cuts_str}")

    hc = report["part_c_pythonhashseed"]
    ac = report["part_c_seed_autocorrelation"]
    lines.append(
        f"Part C: PYTHONHASHSEED bit_identical={hc['bit_identical']} "
        f"(rollouts={hc['subprocess_rollouts']}, distinct_str_hashes={hc['distinct_builtin_str_hashes']}) | "
        f"seed_autocorr zero_predictability={ac['zero_sequential_predictability']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Evolutionary non-Bayesian heuristic search, hard_forge/hard_rl effort ladder, and determinism audit on Canary v1.4."
    )
    ap.add_argument("--quick", action="store_true", help="Fast smoke sweep (<10s)")
    ap.add_argument("--workers", type=int, default=1, choices=[1], help="Single-CPU worker count (fixed at 1)")
    ap.add_argument("--json-out", type=Path, default=None, help="Optional scratch path for JSON output")
    ap.add_argument("--hashseed-worker", type=str, default=None, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.hashseed_worker is not None:
        return _hashseed_worker_main(args.hashseed_worker)

    report = run_full_audit(quick=args.quick)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(format_console_summary(report))
    return 0 if report["passed_all_integrity_gates"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
