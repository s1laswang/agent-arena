"""Mechanistic 5-rung investigator discipline curve and regret decomposition for Canary mole strategies."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
import sys
from typing import Any, Iterable, Sequence

import numpy as np

from canary.baselines import DoNothing, LogsOnly, TOPICS
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.frontier_proxies import GEMINI_LABELS, GeminiCarbonProxy
from canary.forge.mutate import canonical, validate_strategy
from canary.mole.dsl import DEFAULT_STRATEGY, MAX_RULES, MoleStrategy
from canary.mole.evolve_v14 import behavior_hash, is_valid_rule_conds
from canary.mole.strategies import (
    DEFAULT_MAX_LOGS_ACC,
    DEFAULT_MIN_SOLVER_ACC,
    DEFAULT_MIN_SOLVER_RATIO,
    STRATEGY_SPECS,
    get_strategy,
    list_strategy_names,
)
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS, tier_params
from canary.solver.params import params_from_instruction
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult, Step

__all__ = [
    "DEFAULT_BOOTSTRAP_SAMPLES",
    "DEFAULT_BOOTSTRAP_SEED",
    "DEFAULT_DISCIPLINE_SEEDS",
    "DEFAULT_OUTPUT_PATH",
    "DEFAULT_REPORT_MD_PATH",
    "FORBIDDEN_HIGH_SEED_MIN",
    "FORBIDDEN_LOW_SEED_MAX",
    "MAX_JSON_BYTES",
    "RESERVED_HELDOUT_SEED_RANGE",
    "RUNG_NAMES",
    "RUNG_SPECS",
    "DisciplinedGeminiProxy",
    "RungSpec",
    "check_discipline_artifacts",
    "decompose_strategy_regret",
    "dumps_discipline_json",
    "format_discipline_markdown_report",
    "format_discipline_summary",
    "get_rung_spec",
    "list_rung_names",
    "main",
    "make_rung_policy",
    "normalize_discipline_seeds",
    "paired_bootstrap_ci",
    "run_discipline_curve",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_PATH = ROOT / "results" / "mole_strategies" / "discipline_curve_v14.json"
DEFAULT_REPORT_MD_PATH = ROOT / "docs" / "reports" / "mole_discipline_curve_v14.md"

DEFAULT_DISCIPLINE_SEEDS: tuple[int, ...] = tuple(range(6400, 6480))
FORBIDDEN_LOW_SEED_MAX = 59
RESERVED_HELDOUT_SEED_RANGE = range(30_000, 30_200)
FORBIDDEN_HIGH_SEED_MIN = 800_000

DEFAULT_BOOTSTRAP_SAMPLES = 5000
DEFAULT_BOOTSTRAP_SEED = 20261114
MAX_JSON_BYTES = 95_000

RUNG_NAMES: tuple[str, ...] = (
    "undisciplined_gemini_proxy",
    "fix_day1_canary_only",
    "fix_breakeven_abstain_only",
    "fix_gather_hint_both",
    "full_bayesian_solver",
)


@dataclass(frozen=True)
class RungSpec:
    name: str
    index: int
    kind: str
    fix_day1_canary: bool
    fix_breakeven_abstain: bool
    uses_bayesian_solver: bool
    canary_geometry: str
    framing_handling: str
    stopping_rule: str
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "index": int(self.index),
            "kind": self.kind,
            "fix_day1_canary": bool(self.fix_day1_canary),
            "fix_breakeven_abstain": bool(self.fix_breakeven_abstain),
            "uses_bayesian_solver": bool(self.uses_bayesian_solver),
            "canary_geometry": self.canary_geometry,
            "framing_handling": self.framing_handling,
            "stopping_rule": self.stopping_rule,
            "description": self.description,
        }


def _build_rung_specs() -> dict[str, RungSpec]:
    items = (
        RungSpec(
            name="undisciplined_gemini_proxy",
            index=0,
            kind="proxy_baseline",
            fix_day1_canary=False,
            fix_breakeven_abstain=False,
            uses_bayesian_solver=False,
            canary_geometry="midsize_4_8_3var",
            framing_handling="non_bayesian_after_hours_tiebreak",
            stopping_rule="below_breakeven_gambling",
            description=(
                "Full GeminiCarbonProxy defects: delayed Day-2/3 canary start (1 canary on planting days), "
                "midsize 4-6 recipient 3-variant cells, noisy non-decoy after-hours log tiebreak, and "
                "below-breakeven midgame/horizon gambling."
            ),
        ),
        RungSpec(
            name="fix_day1_canary_only",
            index=1,
            kind="single_defect_repair",
            fix_day1_canary=True,
            fix_breakeven_abstain=False,
            uses_bayesian_solver=False,
            canary_geometry="midsize_4_8_3var",
            framing_handling="non_bayesian_after_hours_tiebreak",
            stopping_rule="below_breakeven_gambling",
            description=(
                "Repairs delayed canary start by planting up to 2 canaries/day from Day 1 (pipelined up to "
                "max_pending=4), while keeping midsize 3-variant cells, non-decoy after-hours log tiebreak, "
                "and below-breakeven gambling."
            ),
        ),
        RungSpec(
            name="fix_breakeven_abstain_only",
            index=2,
            kind="single_defect_repair",
            fix_day1_canary=False,
            fix_breakeven_abstain=True,
            uses_bayesian_solver=False,
            canary_geometry="midsize_4_8_3var",
            framing_handling="non_bayesian_after_hours_tiebreak",
            stopping_rule="calibrated_breakeven_abstain",
            description=(
                "Repairs premature and horizon gambles by enforcing calibrated P >= 1 / (1 + E[V]) under "
                "fingerprint_accuracy=0.95 and expected unsurfaced leak drain, while keeping delayed Day-2/3 "
                "canary start and midsize cells."
            ),
        ),
        RungSpec(
            name="fix_gather_hint_both",
            index=3,
            kind="gather_hint_twin",
            fix_day1_canary=True,
            fix_breakeven_abstain=True,
            uses_bayesian_solver=False,
            canary_geometry="midsize_4_8_3var",
            framing_handling="non_bayesian_after_hours_tiebreak",
            stopping_rule="calibrated_breakeven_abstain",
            description=(
                "Mechanistic offline twin of --hint gather: combines Day-1 2-canary/day planting and "
                "calibrated P >= 1 / (1 + E[V]) abstain gate while retaining midsize canary geometry and "
                "non-Bayesian after-hours framing sensitivity."
            ),
        ),
        RungSpec(
            name="full_bayesian_solver",
            index=4,
            kind="reference_ceiling",
            fix_day1_canary=True,
            fix_breakeven_abstain=True,
            uses_bayesian_solver=True,
            canary_geometry="wide_balanced_joint_mi",
            framing_handling="bayesian_poisson_marginalized",
            stopping_rule="calibrated_bayesian_ev",
            description=(
                "Reference SolverPolicy('hard'): wide balanced partitions with joint multi-canary MI "
                "pipelining, Bayesian Poisson framing marginalization (behaviour_temper=0.6), and "
                "calibrated EV stopping."
            ),
        ),
    )
    return {spec.name: spec for spec in items}


RUNG_SPECS: dict[str, RungSpec] = _build_rung_specs()


def list_rung_names() -> list[str]:
    return list(RUNG_NAMES)


def get_rung_spec(name: str) -> RungSpec:
    if name not in RUNG_SPECS:
        raise KeyError(f"unknown discipline rung {name!r}; expected one of {list(RUNG_NAMES)}")
    return RUNG_SPECS[name]


class DisciplinedGeminiProxy(GeminiCarbonProxy):
    def __init__(
        self,
        seed: int = 0,
        rung_name: str = "undisciplined_gemini_proxy",
        fix_day1_canary: bool = False,
        fix_breakeven_abstain: bool = False,
        max_pending: int = 4,
        min_plant_v: float = 0.12,
        flip_underweight: float = 0.05,
        accuse_p: float = 0.88,
    ):
        self.rung_name = str(rung_name)
        self.fix_day1_canary = bool(fix_day1_canary)
        self.fix_breakeven_abstain = bool(fix_breakeven_abstain)
        self.max_pending = int(max_pending)
        self.min_plant_v = float(min_plant_v)
        self._tier_params = None
        self.last_accuse_cal_p: float | None = None
        self.last_accuse_breakeven_p: float | None = None
        super().__init__(seed=seed, flip_underweight=flip_underweight, accuse_p=accuse_p)

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        super().reset(tools_spec, instruction)
        self.rng = random.Random(f"gemini_carbon_proxy:{self.seed}")
        self._tier_params = params_from_instruction(self.instruction) if self.instruction else None
        self.last_accuse_cal_p = None
        self.last_accuse_breakeven_p = None

    def expected_true_v(self) -> float:
        if self._tier_params is None:
            return max(0.0, float(self.V))
        p = self._tier_params
        if not p.delay_choices:
            return max(0.0, float(self.V))
        pend = 0.0
        n_delays = len(p.delay_choices)
        for closed_day in range(1, self.day):
            unseen = sum(1 for dl in p.delay_choices if closed_day + dl > self.day)
            pend += p.p_leak * unseen / n_delays
        return max(0.0, float(self.V) - p.leak_damage * pend)

    def breakeven_threshold(self, exp_v: float | None = None) -> float:
        ev_val = self.expected_true_v() if exp_v is None else float(exp_v)
        if ev_val <= 0.0:
            return 1.0
        w_cost = abs(float(self.wrong_accusation_score)) if self.wrong_accusation_score < 0.0 else 1.0
        return w_cost / (w_cost + ev_val)

    def _record_accuse_diagnostics(self, pool: set[str], target: str) -> None:
        cal_post = self._posterior(pool, self.fingerprint_accuracy)
        exp_v = self.expected_true_v()
        self.last_accuse_cal_p = float(cal_post.get(target, 0.0))
        self.last_accuse_breakeven_p = float(self.breakeven_threshold(exp_v))

    def _handle_marker(self, marker: str) -> None:
        if marker != "__decide__":
            return

        if not self.fix_day1_canary and not self.fix_breakeven_abstain:
            super()._handle_marker(marker)
            if self.queue and self.queue[0][0] == "accuse":
                target = str(self.queue[0][1].get("employee", ""))
                self._record_accuse_diagnostics(self._suspect_pool(), target)
            return

        pool = self._suspect_pool()
        subj_post = self._posterior(pool, self._subjective_q())
        live = sorted([e for e in pool if subj_post[e] > 1e-4]) or sorted(pool)

        if self.fix_breakeven_abstain:
            cal_post = self._posterior(pool, self.fingerprint_accuracy)
            best_cal = max(
                live,
                key=lambda e: (round(cal_post[e], 6), self._non_decoy_ah(e), self.tie_order[e]),
            )
            p_cal = float(cal_post[best_cal])
            exp_v = self.expected_true_v()
            breakeven = self.breakeven_threshold(exp_v)
            if exp_v > 0.0 and p_cal >= breakeven and (p_cal >= self.accuse_p or self.day >= self.n_days):
                self.last_accuse_cal_p = p_cal
                self.last_accuse_breakeven_p = float(breakeven)
                self.queue = [("accuse", {"employee": best_cal})]
                return
            if self.day >= self.n_days:
                self.queue = [("advance_day", {})]
                return
        else:
            best = max(
                live,
                key=lambda e: (round(subj_post[e], 6), self._non_decoy_ah(e), self.tie_order[e]),
            )
            pb = float(subj_post[best])
            ev = pb * self.V + (1.0 - pb) * self.wrong_accusation_score
            if pb >= self.accuse_p and ev > 0.0:
                self._record_accuse_diagnostics(pool, best)
                self.queue = [("accuse", {"employee": best})]
                return
            if self.day >= self.n_days:
                top_p = max(subj_post[e] for e in live)
                tied = [e for e in live if subj_post[e] >= top_p - 0.10]
                winner = max(
                    tied,
                    key=lambda e: (self._non_decoy_ah(e), round(subj_post[e], 6), self.tie_order[e]),
                )
                if top_p >= 0.25 or len(live) <= 4:
                    self._record_accuse_diagnostics(pool, winner)
                    self.queue = [("accuse", {"employee": winner})]
                else:
                    self.queue = [("advance_day", {})]
                return

        cand = [e for e in live if e not in self.restricted]
        nxt: list[tuple[str, dict[str, Any]]] = []
        if self.actions_left >= 3 and len(live) >= 2:
            iv_cands = [e for e in live if e not in self.interviewed_today]
            if iv_cands:
                e0 = iv_cands[(self.day + self.seed) % len(iv_cands)]
                topic = TOPICS[self.interview_cursor % len(TOPICS)]
                self.interview_cursor += 1
                nxt.append(("interview", {"employee": e0, "topic": topic}))

        if not self.fix_day1_canary:
            should_plant = self.day >= 2 and ((self.day + (self.seed % 2)) % 2 == 0 or self.day == 3)
            if should_plant and self.canaries_per_day >= 1 and self.actions_left - len(nxt) >= 1 and len(cand) >= 2:
                cand.sort(
                    key=lambda e: (
                        -round(subj_post[e], 5),
                        -self._non_decoy_ah(e)[0],
                        self.canary_exposures[e] // 4,
                        -self.tie_order[e],
                    )
                )
                subset = cand if len(cand) <= 6 else cand[: self.rng.randint(4, 6)]
                k_var = min(self.max_variants, 3, len(subset))
                labels = GEMINI_LABELS[:k_var]
                asg = {emp: labels[i % k_var] for i, emp in enumerate(subset)}
                nxt.append(("plant_canary", {"doc_title": f"Security review brief d{self.day}", "assignment": asg}))
        else:
            win_days = self._tier_params.leak_window_days if self._tier_params is not None else 3
            surfaced_ids = {str(did) for did, _, _ in self.feed_seen}
            pending = sum(
                1
                for did, doc in self.docs.items()
                if doc.get("is_canary")
                and str(did) not in surfaced_ids
                and int(doc.get("day", 0)) >= self.day - win_days + 1
            )
            max_today = min(
                self.canaries_per_day - self.canaries_today,
                self.actions_left - len(nxt),
                max(0, self.max_pending - pending),
            )
            if len(cand) <= 3:
                max_today = min(max_today, 1)
            n_slots = max_today if (self.canaries_per_day >= 1 and len(cand) >= 2 and self.V > self.min_plant_v) else 0
            planned_exp: Counter[str] = Counter(self.canary_exposures)
            for slot in range(max(0, n_slots)):
                cand_sorted = sorted(
                    cand,
                    key=lambda e: (
                        -round(subj_post[e], 5),
                        -self._non_decoy_ah(e)[0],
                        planned_exp[e],
                        -self.tie_order[e],
                    ),
                )
                subset = cand_sorted if len(cand_sorted) <= 6 else cand_sorted[: self.rng.randint(4, 6)]
                k_var = min(self.max_variants, 3, len(subset))
                labels = GEMINI_LABELS[:k_var]
                if slot == 0 or len(subset) < k_var:
                    asg = {emp: labels[i % k_var] for i, emp in enumerate(subset)}
                else:
                    asg = {
                        emp: labels[min(k_var - 1, (i * k_var) // len(subset))]
                        for i, emp in enumerate(subset)
                    }
                title = (
                    f"Security review brief d{self.day}"
                    if slot == 0
                    else f"Security review brief d{self.day} ({slot + 1})"
                )
                nxt.append(("plant_canary", {"doc_title": title, "assignment": asg}))
                for emp in subset:
                    planned_exp[emp] += 1

        nxt.append(("advance_day", {}))
        self.queue = nxt


def make_rung_policy(rung_name: str, tier: str = "hard", seed: int = 0) -> DisciplinedGeminiProxy | SolverPolicy:
    spec = get_rung_spec(rung_name)
    if spec.uses_bayesian_solver:
        return SolverPolicy(tier if tier in TIERS else tier_params(tier), act_budget=5.0)
    return DisciplinedGeminiProxy(
        seed=seed,
        rung_name=spec.name,
        fix_day1_canary=spec.fix_day1_canary,
        fix_breakeven_abstain=spec.fix_breakeven_abstain,
    )


def normalize_discipline_seeds(
    seeds: str | Iterable[int],
    enforce_hygiene: bool = True,
) -> list[int]:
    if isinstance(seeds, str):
        seed_list = parse_seeds(seeds)
    else:
        raw_items = list(seeds)
        seed_list = []
        for item in raw_items:
            if isinstance(item, bool) or not isinstance(item, int):
                raise ValueError(f"discipline seed must be int, got {item!r}")
            seed_list.append(int(item))
    if not seed_list:
        raise ValueError("discipline seeds must not be empty")
    if len(set(seed_list)) != len(seed_list):
        raise ValueError("discipline seeds must not contain duplicates")
    if enforce_hygiene:
        for s in seed_list:
            if s < 0 or s <= FORBIDDEN_LOW_SEED_MAX:
                raise ValueError(
                    f"seed {s} violates discipline seed hygiene (0..{FORBIDDEN_LOW_SEED_MAX} and negatives forbidden)"
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
) -> dict[str, float | int]:
    if n_boot <= 0:
        raise ValueError(f"n_boot must be positive, got {n_boot}")
    if not (0.0 < ci < 1.0):
        raise ValueError(f"ci must be in (0, 1), got {ci}")
    n = len(diffs)
    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "ci_half_width": 0.0,
        }
    arr = np.asarray(diffs, dtype=np.float64)
    mean_val = float(arr.mean())
    if n == 1 or float(arr.min()) == float(arr.max()):
        return {
            "n": int(n),
            "mean": round(mean_val, 6),
            "ci_low": round(mean_val, 6),
            "ci_high": round(mean_val, 6),
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


def _extract_step_telemetry(steps: Sequence[Step]) -> dict[str, Any]:
    canary_days: list[int] = []
    canary_sizes: list[int] = []
    surfaced_canary_ids: set[str] = set()
    day1_canaries = 0
    for st in steps:
        res = st.result or {}
        if not res.get("ok"):
            continue
        if st.tool == "plant_canary":
            d = int(st.day)
            canary_days.append(d)
            if d == 1:
                day1_canaries += 1
            asg = (st.args or {}).get("assignment")
            if isinstance(asg, dict):
                canary_sizes.append(len(asg))
        elif st.tool == "check_leak_feed":
            data = res.get("data")
            if isinstance(data, dict):
                for it in data.get("items") or []:
                    if isinstance(it, dict) and it.get("variant") is not None and it.get("doc_id"):
                        surfaced_canary_ids.add(str(it["doc_id"]))
    return {
        "canaries_planted": len(canary_days),
        "first_canary_day": min(canary_days) if canary_days else None,
        "day1_canaries": day1_canaries,
        "mean_canary_recipients": (sum(canary_sizes) / len(canary_sizes)) if canary_sizes else 0.0,
        "surfaced_canaries": len(surfaced_canary_ids),
    }


def _pack_rung_episode(
    res: EpisodeResult,
    pol: DisciplinedGeminiProxy | SolverPolicy,
) -> dict[str, Any]:
    telem = _extract_step_telemetry(res.steps)
    accused = res.accused is not None
    gamble = False
    if accused:
        if isinstance(pol, DisciplinedGeminiProxy):
            if pol.last_accuse_cal_p is not None and pol.last_accuse_breakeven_p is not None:
                gamble = bool(pol.last_accuse_cal_p + 1e-9 < pol.last_accuse_breakeven_p)
        elif isinstance(pol, SolverPolicy):
            p_acc = float(pol.post.get(str(res.accused), 1.0))
            exp_v = float(pol.expected_true_V())
            w_cost = abs(float(pol.P.wrong_accusation_score)) if pol.P and pol.P.wrong_accusation_score < 0 else 1.0
            be = 1.0 if exp_v <= 0.0 else w_cost / (w_cost + exp_v)
            gamble = bool(p_acc + 1e-9 < be)
    return {
        "score": float(res.score),
        "correct": bool(res.correct),
        "accused": bool(accused),
        "wrong_accused": bool(accused and not res.correct),
        "abstained": bool(not accused),
        "final_day": int(res.final_day),
        "below_breakeven_gamble": gamble,
        **telem,
    }


def _eval_strategy_seed_worker(
    task: tuple[str, str, int, dict[str, Any], tuple[str, ...]],
) -> dict[str, Any]:
    strat_name, tier, seed, sj, rung_names = task
    strat = MoleStrategy.from_json(sj)
    rungs_out: dict[str, dict[str, Any]] = {}
    for rname in rung_names:
        pol = make_rung_policy(rname, tier=tier, seed=seed)
        ep = run_episode(Env(tier, seed, mole_strategy=strat), pol)
        rungs_out[rname] = _pack_rung_episode(ep, pol)

    lo_ep = run_episode(Env(tier, seed, mole_strategy=strat), LogsOnly(seed=seed))
    dn_ep = run_episode(Env(tier, seed, mole_strategy=strat), DoNothing(seed=seed))
    return {
        "strategy": strat_name,
        "seed": int(seed),
        "rungs": rungs_out,
        "baselines": {
            "logs_only": {"score": float(lo_ep.score), "correct": bool(lo_ep.correct)},
            "do_nothing": {"score": float(dn_ep.score), "correct": bool(dn_ep.correct)},
        },
    }


def _validate_strategy_dsl(sj: dict[str, Any], tier: str) -> tuple[bool, str]:
    parsed = MoleStrategy.from_json(sj)
    round_trip = MoleStrategy.from_json(json.loads(json.dumps(parsed.to_json())))
    if round_trip != parsed or len(parsed.rules) > MAX_RULES:
        return False, ""
    ok, _ = validate_strategy({"rules": sj.get("rules", []), "default": sj.get("default", {"leak": "random_seeded", "frame": "none"})})
    conds_ok = all(is_valid_rule_conds(rule["if"], tier) for rule in sj.get("rules", []))
    c_str = canonical(parsed.to_json())
    sha = hashlib.sha256(c_str.encode("utf-8")).hexdigest()[:16]
    return bool(ok and conds_ok), sha


def _summarize_rung_episodes(
    strat_name: str,
    rung_name: str,
    rows: Sequence[dict[str, Any]],
    n_boot: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    n = len(rows)
    ep_rows = [r["rungs"][rung_name] for r in rows]
    scores = [float(x["score"]) for x in ep_rows]
    score_ci = paired_bootstrap_ci(
        scores,
        n_boot=n_boot,
        seed=bootstrap_seed,
        tag=f"cell:{strat_name}:{rung_name}:score",
    )
    first_days = [float(x["first_canary_day"]) for x in ep_rows if x["first_canary_day"] is not None]
    canary_sizes = [float(x["mean_canary_recipients"]) for x in ep_rows if x["canaries_planted"] > 0]
    accused_days = [float(x["final_day"]) for x in ep_rows if x["accused"]]
    return {
        "n": n,
        "score": score_ci["mean"],
        "ci_low": score_ci["ci_low"],
        "ci_high": score_ci["ci_high"],
        "ci_half_width": score_ci["ci_half_width"],
        "acc": round(sum(1.0 if x["correct"] else 0.0 for x in ep_rows) / n, 6),
        "wrong_rate": round(sum(1.0 if x["wrong_accused"] else 0.0 for x in ep_rows) / n, 6),
        "abstain_rate": round(sum(1.0 if x["abstained"] else 0.0 for x in ep_rows) / n, 6),
        "below_breakeven_gamble_rate": round(
            sum(1.0 if x["below_breakeven_gamble"] else 0.0 for x in ep_rows) / n, 6
        ),
        "mean_final_day": round(sum(float(x["final_day"]) for x in ep_rows) / n, 4),
        "mean_accuse_day": round(sum(accused_days) / len(accused_days), 4) if accused_days else None,
        "mean_canaries_planted": round(sum(float(x["canaries_planted"]) for x in ep_rows) / n, 4),
        "mean_surfaced_canaries": round(sum(float(x["surfaced_canaries"]) for x in ep_rows) / n, 4),
        "day1_canary_rate": round(sum(1.0 if x["day1_canaries"] >= 1 else 0.0 for x in ep_rows) / n, 6),
        "day1_two_canary_rate": round(sum(1.0 if x["day1_canaries"] >= 2 else 0.0 for x in ep_rows) / n, 6),
        "mean_first_canary_day": round(sum(first_days) / len(first_days), 4) if first_days else None,
        "mean_canary_recipients": round(sum(canary_sizes) / len(canary_sizes), 4) if canary_sizes else 0.0,
        "scores": [round(s, 4) for s in scores],
    }


def decompose_strategy_regret(
    strat_name: str,
    scores_by_rung: dict[str, Sequence[float]],
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    missing = [r for r in RUNG_NAMES if r not in scores_by_rung]
    if missing:
        raise ValueError(f"cannot decompose regret; missing rungs {missing}")
    s0 = [float(x) for x in scores_by_rung["undisciplined_gemini_proxy"]]
    s1 = [float(x) for x in scores_by_rung["fix_day1_canary_only"]]
    s2 = [float(x) for x in scores_by_rung["fix_breakeven_abstain_only"]]
    s3 = [float(x) for x in scores_by_rung["fix_gather_hint_both"]]
    s4 = [float(x) for x in scores_by_rung["full_bayesian_solver"]]
    if not (len(s0) == len(s1) == len(s2) == len(s3) == len(s4)):
        raise ValueError("rung score vectors must have identical length")

    d_delayed = [b - a for a, b in zip(s0, s1)]
    d_gamble = [b - a for a, b in zip(s1, s3)]
    d_residual = [b - a for a, b in zip(s3, s4)]
    d_total = [b - a for a, b in zip(s0, s4)]
    d_gather = [b - a for a, b in zip(s0, s3)]
    d_abstain_only = [b - a for a, b in zip(s0, s2)]
    d_interaction = [g - ao for g, ao in zip(d_gamble, d_abstain_only)]

    max_per_seed_err = max(
        (abs((a + b + c) - t) for a, b, c, t in zip(d_delayed, d_gamble, d_residual, d_total)),
        default=0.0,
    )

    def _ci(vec: list[float], metric: str) -> dict[str, float | int]:
        return paired_bootstrap_ci(
            vec,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"decomp:{strat_name}:{metric}",
        )

    ci_delayed = _ci(d_delayed, "delayed_canary_regret")
    ci_gamble = _ci(d_gamble, "gamble_discipline_regret")
    ci_residual = _ci(d_residual, "residual_evasion_framing_regret")
    ci_total = _ci(d_total, "total_regret")
    ci_gather = _ci(d_gather, "gather_hint_repair_total")
    ci_abstain_only = _ci(d_abstain_only, "standalone_abstain_regret")
    ci_interaction = _ci(d_interaction, "canary_abstain_interaction")

    exact_mean_delayed = sum(d_delayed) / len(d_delayed) if d_delayed else 0.0
    exact_mean_gamble = sum(d_gamble) / len(d_gamble) if d_gamble else 0.0
    exact_mean_residual = sum(d_residual) / len(d_residual) if d_residual else 0.0
    exact_mean_total = sum(d_total) / len(d_total) if d_total else 0.0
    mean_err = abs((exact_mean_delayed + exact_mean_gamble + exact_mean_residual) - exact_mean_total)

    residual_fraction = (
        round(exact_mean_residual / exact_mean_total, 6)
        if abs(exact_mean_total) > 1e-9
        else None
    )

    return {
        "total_regret": ci_total,
        "delayed_canary_regret": ci_delayed,
        "gamble_discipline_regret": ci_gamble,
        "residual_evasion_framing_regret": ci_residual,
        "gather_hint_repair_total": ci_gather,
        "standalone_abstain_regret": ci_abstain_only,
        "canary_abstain_interaction": ci_interaction,
        "decomposition_sum": round(
            float(ci_delayed["mean"]) + float(ci_gamble["mean"]) + float(ci_residual["mean"]),
            6,
        ),
        "identity_abs_error": round(max(mean_err, max_per_seed_err), 12),
        "residual_regret_fraction": residual_fraction,
    }


def _compute_vs_default_contrast(
    strat_name: str,
    strat_scores: dict[str, Sequence[float]],
    default_scores: dict[str, Sequence[float]],
    n_boot: int,
    bootstrap_seed: int,
) -> dict[str, Any]:
    s0, d0 = [float(x) for x in strat_scores["undisciplined_gemini_proxy"]], [float(x) for x in default_scores["undisciplined_gemini_proxy"]]
    s1, d1 = [float(x) for x in strat_scores["fix_day1_canary_only"]], [float(x) for x in default_scores["fix_day1_canary_only"]]
    s3, d3 = [float(x) for x in strat_scores["fix_gather_hint_both"]], [float(x) for x in default_scores["fix_gather_hint_both"]]
    s4, d4 = [float(x) for x in strat_scores["full_bayesian_solver"]], [float(x) for x in default_scores["full_bayesian_solver"]]

    def _ci(vec: list[float], metric: str) -> dict[str, float | int]:
        return paired_bootstrap_ci(
            vec,
            n_boot=n_boot,
            seed=bootstrap_seed,
            tag=f"vs_default:{strat_name}:{metric}",
        )

    return {
        "rung0_score_delta": _ci([a - b for a, b in zip(s0, d0)], "rung0_score_delta"),
        "rung3_score_delta": _ci([a - b for a, b in zip(s3, d3)], "rung3_score_delta"),
        "rung4_score_delta": _ci([a - b for a, b in zip(s4, d4)], "rung4_score_delta"),
        "total_regret_gain": _ci([(a4 - a0) - (b4 - b0) for a4, a0, b4, b0 in zip(s4, s0, d4, d0)], "total_regret_gain"),
        "delayed_canary_regret_gain": _ci([(a1 - a0) - (b1 - b0) for a1, a0, b1, b0 in zip(s1, s0, d1, d0)], "delayed_canary_regret_gain"),
        "gamble_discipline_regret_gain": _ci([(a3 - a1) - (b3 - b1) for a3, a1, b3, b1 in zip(s3, s1, d3, d1)], "gamble_discipline_regret_gain"),
        "residual_regret_gain": _ci([(a4 - a3) - (b4 - b3) for a4, a3, b4, b3 in zip(s4, s3, d4, d3)], "residual_regret_gain"),
    }


def run_discipline_curve(
    tier: str = "hard",
    seeds: str | Iterable[int] = DEFAULT_DISCIPLINE_SEEDS,
    strategy_names: Sequence[str] | None = None,
    rung_names: Sequence[str] | None = None,
    workers: int = 1,
    n_boot: int = DEFAULT_BOOTSTRAP_SAMPLES,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    min_solver_acc: float = DEFAULT_MIN_SOLVER_ACC,
    min_solver_ratio: float = DEFAULT_MIN_SOLVER_RATIO,
    max_logs_acc: float = DEFAULT_MAX_LOGS_ACC,
    enforce_seed_hygiene: bool = True,
) -> dict[str, Any]:
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}; expected one of {sorted(TIERS)}")
    seed_list = normalize_discipline_seeds(seeds, enforce_hygiene=enforce_seed_hygiene)
    selected_strats = list(list_strategy_names(include_default=True) if strategy_names is None else strategy_names)
    if not selected_strats:
        raise ValueError("strategy_names must not be empty")
    selected_rungs = tuple(RUNG_NAMES if rung_names is None else rung_names)
    if not selected_rungs:
        raise ValueError("rung_names must not be empty")
    for rname in selected_rungs:
        get_rung_spec(rname)

    strat_jsons: dict[str, dict[str, Any]] = {}
    for sname in selected_strats:
        parsed = get_strategy(sname)
        sj = parsed.to_json()
        sj["name"] = parsed.name
        strat_jsons[parsed.name] = sj
    canonical_strat_names = list(strat_jsons.keys())

    eval_names = list(canonical_strat_names)
    if DEFAULT_STRATEGY.name not in eval_names and "full_bayesian_solver" in selected_rungs:
        def_sj = DEFAULT_STRATEGY.to_json()
        def_sj["name"] = DEFAULT_STRATEGY.name
        strat_jsons[DEFAULT_STRATEGY.name] = def_sj
        eval_names = [DEFAULT_STRATEGY.name, *eval_names]

    tasks: list[tuple[str, str, int, dict[str, Any], tuple[str, ...]]] = [
        (sname, tier, s, strat_jsons[sname], selected_rungs)
        for sname in eval_names
        for s in seed_list
    ]
    if workers > 1 and len(tasks) > 1:
        with ProcessPoolExecutor(max_workers=min(int(workers), len(tasks))) as pool:
            raw_rows = list(pool.map(_eval_strategy_seed_worker, tasks))
    else:
        raw_rows = [_eval_strategy_seed_worker(t) for t in tasks]

    by_strat: dict[str, list[dict[str, Any]]] = {sname: [] for sname in eval_names}
    for row in raw_rows:
        by_strat[str(row["strategy"])].append(row)
    for sname in eval_names:
        by_strat[sname].sort(key=lambda r: int(r["seed"]))

    has_full_ladder = set(selected_rungs) == set(RUNG_NAMES)
    baseline_solver_score = 0.0
    baseline_solver_acc = 0.0
    default_rung_scores: dict[str, list[float]] | None = None
    if DEFAULT_STRATEGY.name in by_strat:
        def_rows = by_strat[DEFAULT_STRATEGY.name]
        if "full_bayesian_solver" in selected_rungs:
            def_sol = [float(r["rungs"]["full_bayesian_solver"]["score"]) for r in def_rows]
            def_sol_ok = [1.0 if r["rungs"]["full_bayesian_solver"]["correct"] else 0.0 for r in def_rows]
            baseline_solver_score = sum(def_sol) / len(def_sol)
            baseline_solver_acc = sum(def_sol_ok) / len(def_sol_ok)
        if has_full_ladder:
            default_rung_scores = {
                rname: [float(r["rungs"][rname]["score"]) for r in def_rows]
                for rname in RUNG_NAMES
            }

    strategies_out: dict[str, Any] = {}
    for sname in canonical_strat_names:
        rows = by_strat[sname]
        sj = strat_jsons[sname]
        dsl_ok, canon_sha = _validate_strategy_dsl(sj, tier)
        b_hash = behavior_hash(sj, tier)
        spec_meta = STRATEGY_SPECS.get(sname)

        rungs_summary: dict[str, Any] = {}
        scores_by_rung: dict[str, list[float]] = {}
        for rname in selected_rungs:
            summary = _summarize_rung_episodes(
                strat_name=sname,
                rung_name=rname,
                rows=rows,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
            )
            rungs_summary[rname] = summary
            scores_by_rung[rname] = [float(r["rungs"][rname]["score"]) for r in rows]

        lo_accs = [1.0 if r["baselines"]["logs_only"]["correct"] else 0.0 for r in rows]
        lo_scores = [float(r["baselines"]["logs_only"]["score"]) for r in rows]
        dn_scores = [float(r["baselines"]["do_nothing"]["score"]) for r in rows]
        lo_acc = round(sum(lo_accs) / len(lo_accs), 6)
        lo_score = round(sum(lo_scores) / len(lo_scores), 6)
        dn_max_abs = round(max((abs(x) for x in dn_scores), default=0.0), 6)

        if "full_bayesian_solver" in rungs_summary:
            sol_acc = float(rungs_summary["full_bayesian_solver"]["acc"])
            sol_score = float(rungs_summary["full_bayesian_solver"]["score"])
            sol_ratio = (
                round(sol_score / baseline_solver_score, 6)
                if baseline_solver_score > 1e-9
                else 1.0
            )
            passed_solver_acc = sol_acc >= float(min_solver_acc)
            passed_solver_ratio = sol_ratio >= float(min_solver_ratio)
        else:
            sol_ratio = None
            passed_solver_acc = True
            passed_solver_ratio = True

        passed_logs = lo_acc <= float(max_logs_acc)
        passed_dn = dn_max_abs == 0.0
        gates = {
            "dsl_valid": bool(dsl_ok),
            "solver_acc_ok": bool(passed_solver_acc),
            "solver_ratio_ok": bool(passed_solver_ratio),
            "solver_score_ratio": sol_ratio,
            "logs_only_acc": lo_acc,
            "logs_only_score": lo_score,
            "logs_only_ok": bool(passed_logs),
            "do_nothing_max_abs_score": dn_max_abs,
            "do_nothing_ok": bool(passed_dn),
            "passed_all": bool(dsl_ok and passed_solver_acc and passed_solver_ratio and passed_logs and passed_dn),
        }

        decomp = (
            decompose_strategy_regret(
                strat_name=sname,
                scores_by_rung=scores_by_rung,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
            )
            if has_full_ladder
            else None
        )
        vs_default = (
            _compute_vs_default_contrast(
                strat_name=sname,
                strat_scores=scores_by_rung,
                default_scores=default_rung_scores,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
            )
            if (has_full_ladder and default_rung_scores is not None and sname != DEFAULT_STRATEGY.name)
            else None
        )

        strategies_out[sname] = {
            "name": sname,
            "lever_id": spec_meta.lever_id if spec_meta is not None else "baseline_random_seeded",
            "target_cohort": spec_meta.target_cohort if spec_meta is not None else "baseline",
            "n_rules": len(sj.get("rules", [])),
            "behavior_hash": b_hash,
            "canonical_sha256": canon_sha,
            "gates": gates,
            "rungs": rungs_summary,
            "regret_decomposition": decomp,
            "vs_default": vs_default,
        }

    transcript_names = [n for n in canonical_strat_names if n != DEFAULT_STRATEGY.name]
    transcript_pool_summary: dict[str, Any] | None = None
    if has_full_ladder and transcript_names:
        n_s = len(seed_list)
        pooled_by_rung: dict[str, list[float]] = {}
        for rname in RUNG_NAMES:
            pooled_by_rung[rname] = [
                sum(float(by_strat[sn][idx]["rungs"][rname]["score"]) for sn in transcript_names) / len(transcript_names)
                for idx in range(n_s)
            ]
        pooled_decomp = decompose_strategy_regret(
            strat_name="mean_transcript_strategies",
            scores_by_rung=pooled_by_rung,
            n_boot=n_boot,
            bootstrap_seed=bootstrap_seed,
        )
        pooled_vs_default = (
            _compute_vs_default_contrast(
                strat_name="mean_transcript_strategies",
                strat_scores=pooled_by_rung,
                default_scores=default_rung_scores,
                n_boot=n_boot,
                bootstrap_seed=bootstrap_seed,
            )
            if default_rung_scores is not None
            else None
        )
        transcript_pool_summary = {
            "strategy_names": transcript_names,
            "n_strategies": len(transcript_names),
            "mean_scores_by_rung": {
                rname: round(sum(pooled_by_rung[rname]) / n_s, 6)
                for rname in RUNG_NAMES
            },
            "regret_decomposition": pooled_decomp,
            "vs_default": pooled_vs_default,
        }

    canon_hashes = [strategies_out[n]["canonical_sha256"] for n in canonical_strat_names]
    solver_accs = [
        float(strategies_out[n]["rungs"]["full_bayesian_solver"]["acc"])
        for n in canonical_strat_names
        if "full_bayesian_solver" in strategies_out[n]["rungs"]
    ]
    gates_summary = {
        "n_strategies": len(canonical_strat_names),
        "n_passed": sum(1 for n in canonical_strat_names if strategies_out[n]["gates"]["passed_all"]),
        "all_strategies_passed": all(strategies_out[n]["gates"]["passed_all"] for n in canonical_strat_names),
        "min_solver_acc_threshold": float(min_solver_acc),
        "min_solver_ratio_threshold": float(min_solver_ratio),
        "max_logs_acc_threshold": float(max_logs_acc),
        "min_solver_acc_observed": round(min(solver_accs), 6) if solver_accs else None,
        "max_logs_only_acc_observed": round(
            max(float(strategies_out[n]["gates"]["logs_only_acc"]) for n in canonical_strat_names), 6
        ),
        "max_do_nothing_abs_score": round(
            max(float(strategies_out[n]["gates"]["do_nothing_max_abs_score"]) for n in canonical_strat_names), 6
        ),
        "unique_canonical_strategies": len(set(canon_hashes)) == len(canon_hashes),
    }

    return {
        "study": "mole_discipline_curve_v14",
        "tier": tier,
        "n_seeds": len(seed_list),
        "seeds": seed_list,
        "seed_range": f"{seed_list[0]}-{seed_list[-1]}",
        "rung_names": list(selected_rungs),
        "rung_specs": {rname: get_rung_spec(rname).to_dict() for rname in selected_rungs},
        "bootstrap_config": {
            "n_boot": int(n_boot),
            "ci": 0.95,
            "seed": int(bootstrap_seed),
        },
        "baseline_reference": {
            "strategy": DEFAULT_STRATEGY.name,
            "solver_score": round(baseline_solver_score, 6),
            "solver_acc": round(baseline_solver_acc, 6),
        },
        "gates_summary": gates_summary,
        "strategies": strategies_out,
        "transcript_strategy_mean": transcript_pool_summary,
    }


def _ordered_strategy_names(strategies: dict[str, Any]) -> list[str]:
    canonical_order = list_strategy_names(include_default=True)
    out = [n for n in canonical_order if n in strategies]
    out.extend(n for n in strategies if n not in out)
    return out


def _fmt_ci(ci_obj: dict[str, Any], digits: int = 3, signed: bool = True) -> str:
    fmt = f"{{:+.{digits}f}}" if signed else f"{{:.{digits}f}}"
    return (
        f"{fmt.format(float(ci_obj['mean']))} "
        f"[{fmt.format(float(ci_obj['ci_low']))}, {fmt.format(float(ci_obj['ci_high']))}]"
    )


def format_discipline_summary(report: dict[str, Any]) -> str:
    gs = report["gates_summary"]
    lines = [
        f"Mole Investigator Discipline Curve (tier={report['tier']}, seeds={report['seed_range']} n={report['n_seeds']}, "
        f"passed={gs['n_passed']}/{gs['n_strategies']})",
        "",
        "| strategy | R0_undisc | R1_day1 | R2_abstain | R3_gather | R4_solver | delayed(R1-R0) | gamble(R3-R1) | residual(R4-R3) | total(R4-R0) | gates |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for sname in _ordered_strategy_names(report["strategies"]):
        st = report["strategies"][sname]
        r = st["rungs"]
        dec = st.get("regret_decomposition")
        status = "PASS" if st["gates"]["passed_all"] else "FAIL"
        if dec is not None:
            lines.append(
                f"| {sname} | "
                f"{r['undisciplined_gemini_proxy']['score']:+.3f} | "
                f"{r['fix_day1_canary_only']['score']:+.3f} | "
                f"{r['fix_breakeven_abstain_only']['score']:+.3f} | "
                f"{r['fix_gather_hint_both']['score']:+.3f} | "
                f"{r['full_bayesian_solver']['score']:+.3f} | "
                f"{dec['delayed_canary_regret']['mean']:+.3f} | "
                f"{dec['gamble_discipline_regret']['mean']:+.3f} | "
                f"{dec['residual_evasion_framing_regret']['mean']:+.3f} | "
                f"{dec['total_regret']['mean']:+.3f} | {status} |"
            )
        else:
            cols = " | ".join(f"{r[rn]['score']:+.3f}" for rn in report["rung_names"])
            lines.append(f"| {sname} | {cols} | {status} |")
    return "\n".join(lines)


def format_discipline_markdown_report(report: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3

    gs = report["gates_summary"]
    b_cfg = report["bootstrap_config"]
    strats = report["strategies"]
    ordered_names = _ordered_strategy_names(strats)
    has_full_ladder = set(report["rung_names"]) == set(RUNG_NAMES)
    pool_summary = report.get("transcript_strategy_mean")

    lines: list[str] = [
        f"{h1} Mechanistic Investigator Discipline Curve and Regret Decomposition (`{report['tier']}` Tier)",
        "",
        "Generated deterministically offline (0 API calls) via "
        f"`python -m canary.mole.discipline_curve --tier {report['tier']} --seeds {report['seed_range']} --workers 1 "
        "--out results/mole_strategies/discipline_curve_v14.json "
        "--report-md docs/reports/mole_discipline_curve_v14.md`.",
        "",
        f"{h2} 1. Executive Summary and Causal Hypothesis (`--hint gather` Twin)",
        "",
        f"- **Fresh disjoint evaluation slice**: `n={report['n_seeds']}` paired `{report['tier']}` seeds "
        f"(`{report['seed_range']}`), strictly disjoint from committed run seeds (`0..59`), reserved held-out "
        "evaluation seeds (`30000..30199`), and held-out/judge seeds (`800000+`, `900000+`).",
        f"- **Paired bootstrap uncertainty**: `{b_cfg['n_boot']}` paired resamples (`ci={b_cfg['ci']:.2f}`, "
        f"`seed={b_cfg['seed']}`).",
        f"- **Catchability and anti-shortcut gates**: **{gs['n_passed']}/{gs['n_strategies']}** strategies passed "
        f"every gate (`SolverPolicy` catchability `>= {gs['min_solver_acc_threshold']:.2f}`, observed minimum "
        f"`{gs['min_solver_acc_observed']:.3f}`"
        if gs.get("min_solver_acc_observed") is not None
        else f"- **Catchability and anti-shortcut gates**: **{gs['n_passed']}/{gs['n_strategies']}** strategies passed every gate",
    ]
    if gs.get("min_solver_acc_observed") is not None:
        lines[-1] += (
            f"; `SolverPolicy` score ratio `>= {gs['min_solver_ratio_threshold']:.2f}` of `default_v0` baseline "
            f"`{report['baseline_reference']['solver_score']:+.3f}`; `LogsOnly` accuracy "
            f"`<= {gs['max_logs_acc_threshold']:.2f}`, observed maximum `{gs['max_logs_only_acc_observed']:.3f}`; "
            f"`DoNothing` max `|score| == {gs['max_do_nothing_abs_score']:.3f}`)."
        )

    if has_full_ladder and pool_summary is not None:
        n_tr = int(pool_summary.get("n_strategies", 6))
        pd = pool_summary["regret_decomposition"]
        pvd = pool_summary.get("vs_default")
        lines.append(
            f"- **Pooled {n_tr}-strategy transcript mean regret decomposition**: "
            f"total regret `R4 - R0 = {_fmt_ci(pd['total_regret'])}` decomposes exactly into "
            f"(a) delayed-canary regret `R1 - R0 = {_fmt_ci(pd['delayed_canary_regret'])}`, "
            f"(b) gamble-discipline regret `R3 - R1 = {_fmt_ci(pd['gamble_discipline_regret'])}`, and "
            f"(c) residual strategic evasion/framing regret `R4 - R3 = {_fmt_ci(pd['residual_evasion_framing_regret'])}` "
            f"(persisting even against the `--hint gather` twin; residual share of total regret "
            f"`{pd['residual_regret_fraction']:.3f}`)."
            if pd.get("residual_regret_fraction") is not None
            else f"- **Pooled {n_tr}-strategy transcript mean regret decomposition**: exact telescoping sum verified."
        )
        if pvd is not None:
            lines.append(
                f"- **Gain over `default_v0` across the {n_tr} transcript strategies**: "
                f"total regret gain `{_fmt_ci(pvd['total_regret_gain'])}`, "
                f"`Rung 0` proxy score delta `{_fmt_ci(pvd['rung0_score_delta'])}`, "
                f"`Rung 3` (`--hint gather` twin) score delta `{_fmt_ci(pvd['rung3_score_delta'])}`, and "
                f"residual `R4 - R3` regret gain `{_fmt_ci(pvd['residual_regret_gain'])}` while `Rung 4` (`SolverPolicy`) "
                f"score delta is `{_fmt_ci(pvd['rung4_score_delta'])}`."
            )

    lines.extend([
        "",
        f"{h2} 2. Five-Rung Deterministic Investigator Ladder",
        "",
        "Each rung wraps public `GeminiCarbonProxy` / `SolverPolicy` components with zero protected-path edits and "
        "uses only public tool calls and instruction parameters.",
        "",
        "| Rung | Name | Day-1 2-Canary/Day | Calibrated `P >= 1/(1+E[V])` | Canary Geometry | Framing Handling | Role |",
        "|---|---|---|---|---|---|---|",
    ])
    for rname in report["rung_names"]:
        rspec = report["rung_specs"][rname]
        lines.append(
            f"| `Rung {rspec['index']}` | `{rname}` | "
            f"`{rspec['fix_day1_canary']}` | `{rspec['fix_breakeven_abstain']}` | "
            f"`{rspec['canary_geometry']}` | `{rspec['framing_handling']}` | {rspec['description']} |"
        )

    if has_full_ladder:
        lines.extend([
            "",
            f"{h2} 3. Paired 5-Rung Score and Accuracy Curve Across All Strategies (`n={report['n_seeds']}`)",
            "",
            "| Strategy | Rung 0 Score (Acc) | Rung 1 Score (Acc) | Rung 2 Score (Acc) | Rung 3 `--hint gather` Score (Acc) | Rung 4 `SolverPolicy` Score (Acc) | Gates |",
            "|---|---|---|---|---|---|---|",
        ])
        for sname in ordered_names:
            st = strats[sname]
            r = st["rungs"]
            status = "PASS" if st["gates"]["passed_all"] else "FAIL"
            lines.append(
                f"| `{sname}` | "
                f"{r['undisciplined_gemini_proxy']['score']:+.3f} ({r['undisciplined_gemini_proxy']['acc']:.3f}) | "
                f"{r['fix_day1_canary_only']['score']:+.3f} ({r['fix_day1_canary_only']['acc']:.3f}) | "
                f"{r['fix_breakeven_abstain_only']['score']:+.3f} ({r['fix_breakeven_abstain_only']['acc']:.3f}) | "
                f"{r['fix_gather_hint_both']['score']:+.3f} ({r['fix_gather_hint_both']['acc']:.3f}) | "
                f"{r['full_bayesian_solver']['score']:+.3f} ({r['full_bayesian_solver']['acc']:.3f}) | {status} |"
            )

        lines.extend([
            "",
            f"{h2} 4. Exact Three-Term Regret Decomposition (`(R1 - R0) + (R3 - R1) + (R4 - R3) == R4 - R0`)",
            "",
            "Total investigator regret `Rung 4 - Rung 0` telescopes into: "
            "(a) **delayed-canary regret** (`Rung 1 - Rung 0`), "
            "(b) **gamble-discipline regret** (`Rung 3 - Rung 1`, enforcing calibrated `P >= 1 / (1 + E[V])` on top of Day-1 canaries), and "
            "(c) **residual strategic evasion/framing regret** (`Rung 4 - Rung 3`, which persists even against the `--hint gather` twin). "
            "Standalone abstain repair without Day-1 canaries (`Rung 2 - Rung 0`) is also reported for completeness.",
            "",
            "| Strategy | Total Regret `R4 - R0` [95% CI] | (a) Delayed-Canary `R1 - R0` [95% CI] | (b) Gamble-Discipline `R3 - R1` [95% CI] | (c) Residual Evasion/Framing `R4 - R3` [95% CI] | Standalone Abstain `R2 - R0` [95% CI] | Residual Share | Sum Err |",
            "|---|---|---|---|---|---|---|---|",
        ])
        for sname in ordered_names:
            dec = strats[sname]["regret_decomposition"]
            rf = f"{dec['residual_regret_fraction']:.3f}" if dec["residual_regret_fraction"] is not None else "n/a"
            lines.append(
                f"| `{sname}` | "
                f"{_fmt_ci(dec['total_regret'])} | "
                f"{_fmt_ci(dec['delayed_canary_regret'])} | "
                f"{_fmt_ci(dec['gamble_discipline_regret'])} | "
                f"{_fmt_ci(dec['residual_evasion_framing_regret'])} | "
                f"{_fmt_ci(dec['standalone_abstain_regret'])} | "
                f"{rf} | {dec['identity_abs_error']:.1e} |"
            )
        if pool_summary is not None:
            n_tr = int(pool_summary.get("n_strategies", 6))
            pdec = pool_summary["regret_decomposition"]
            prf = f"{pdec['residual_regret_fraction']:.3f}" if pdec["residual_regret_fraction"] is not None else "n/a"
            lines.append(
                f"| **`mean_transcript_strategies` ({n_tr})** | "
                f"{_fmt_ci(pdec['total_regret'])} | "
                f"{_fmt_ci(pdec['delayed_canary_regret'])} | "
                f"{_fmt_ci(pdec['gamble_discipline_regret'])} | "
                f"{_fmt_ci(pdec['residual_evasion_framing_regret'])} | "
                f"{_fmt_ci(pdec['standalone_abstain_regret'])} | "
                f"{prf} | {pdec['identity_abs_error']:.1e} |"
            )

        has_vs_default = any(strats[n].get("vs_default") is not None for n in ordered_names)
        if has_vs_default:
            lines.extend([
                "",
                f"{h2} 5. Paired Regret Gains Relative to `default_v0`",
                "",
                "Positive regret gains and negative Rung 0 / Rung 3 score deltas show how each transcript-grounded "
                "mole strategy increases investigator difficulty beyond `DEFAULT_STRATEGY` both before (`Rung 0`) and "
                "after (`Rung 3`) `--hint gather` discipline repairs, without degrading `SolverPolicy` (`Rung 4`).",
                "",
                "| Strategy | Rung 0 Delta vs Default | Rung 3 `--hint gather` Delta | Rung 4 Solver Delta | Total Regret Gain [95% CI] | Delayed-Canary Gain [95% CI] | Gamble-Discipline Gain [95% CI] | Residual `R4 - R3` Gain [95% CI] |",
                "|---|---|---|---|---|---|---|---|",
            ])
            for sname in ordered_names:
                vd = strats[sname].get("vs_default")
                if vd is None:
                    continue
                lines.append(
                    f"| `{sname}` | "
                    f"{_fmt_ci(vd['rung0_score_delta'])} | "
                    f"{_fmt_ci(vd['rung3_score_delta'])} | "
                    f"{_fmt_ci(vd['rung4_score_delta'])} | "
                    f"{_fmt_ci(vd['total_regret_gain'])} | "
                    f"{_fmt_ci(vd['delayed_canary_regret_gain'])} | "
                    f"{_fmt_ci(vd['gamble_discipline_regret_gain'])} | "
                    f"{_fmt_ci(vd['residual_regret_gain'])} |"
                )
            if pool_summary is not None and pool_summary.get("vs_default") is not None:
                n_tr = int(pool_summary.get("n_strategies", 6))
                pvd = pool_summary["vs_default"]
                lines.append(
                    f"| **`mean_transcript_strategies` ({n_tr})** | "
                    f"{_fmt_ci(pvd['rung0_score_delta'])} | "
                    f"{_fmt_ci(pvd['rung3_score_delta'])} | "
                    f"{_fmt_ci(pvd['rung4_score_delta'])} | "
                    f"{_fmt_ci(pvd['total_regret_gain'])} | "
                    f"{_fmt_ci(pvd['delayed_canary_regret_gain'])} | "
                    f"{_fmt_ci(pvd['gamble_discipline_regret_gain'])} | "
                    f"{_fmt_ci(pvd['residual_regret_gain'])} |"
                )

        lines.extend([
            "",
            f"{h2} 6. Mechanistic Telemetry Verification Across Rungs",
            "",
            "| Strategy | R0 1st-Can Day / Canaries / Gamble / Wrong / Abst | R1 1st-Can Day / Canaries / Gamble / Wrong / Abst | R2 1st-Can Day / Canaries / Gamble / Wrong / Abst | R3 1st-Can Day / Canaries / Gamble / Wrong / Abst | R4 1st-Can Day / Canaries / Recips / Wrong / Abst |",
            "|---|---|---|---|---|---|",
        ])
        for sname in ordered_names:
            r = strats[sname]["rungs"]

            def _cell_proxy(rn: str) -> str:
                c = r[rn]
                fd = f"{c['mean_first_canary_day']:.2f}" if c["mean_first_canary_day"] is not None else "n/a"
                return (
                    f"{fd}d / {c['mean_canaries_planted']:.1f} / "
                    f"{c['below_breakeven_gamble_rate']:.3f} / "
                    f"{c['wrong_rate']:.3f} / {c['abstain_rate']:.3f}"
                )

            c4 = r["full_bayesian_solver"]
            fd4 = f"{c4['mean_first_canary_day']:.2f}" if c4["mean_first_canary_day"] is not None else "n/a"
            cell4 = (
                f"{fd4}d / {c4['mean_canaries_planted']:.1f} / "
                f"{c4['mean_canary_recipients']:.1f} / "
                f"{c4['wrong_rate']:.3f} / {c4['abstain_rate']:.3f}"
            )
            lines.append(
                f"| `{sname}` | "
                f"{_cell_proxy('undisciplined_gemini_proxy')} | "
                f"{_cell_proxy('fix_day1_canary_only')} | "
                f"{_cell_proxy('fix_breakeven_abstain_only')} | "
                f"{_cell_proxy('fix_gather_hint_both')} | "
                f"{cell4} |"
            )

    lines.extend([
        "",
        f"{h3} 6.1 Strategy Provenance and Anti-Shortcut Gate Ledger",
        "",
        "| Strategy | Lever ID | Cohort | Rules | Behavior Hash | Canonical SHA-256 | LogsOnly Acc (Score) | DoNothing Max Abs | Gates |",
        "|---|---|---|---|---|---|---|---|---|",
    ])
    for sname in ordered_names:
        st = strats[sname]
        g = st["gates"]
        status = "PASS" if g["passed_all"] else "FAIL"
        lines.append(
            f"| `{sname}` | `{st['lever_id']}` | `{st['target_cohort']}` | {st['n_rules']} | "
            f"`{st['behavior_hash']}` | `{st['canonical_sha256']}` | "
            f"{g['logs_only_acc']:.3f} ({g['logs_only_score']:+.3f}) | "
            f"{g['do_nothing_max_abs_score']:.3f} | {status} |"
        )

    return "\n".join(lines) + "\n"


_FORBIDDEN_PAYLOAD_KEYS: frozenset[str] = frozenset({
    "true_mole",
    "mole_id",
    "canary_ids",
    "secret_mole",
})


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


def dumps_discipline_json(obj: Any, indent: int = 1, _level: int = 0) -> str:
    if isinstance(obj, dict):
        if not obj:
            return "{}"
        if all(not isinstance(v, (dict, list)) for v in obj.values()):
            return json.dumps(obj, separators=(",", ":"), sort_keys=True)
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [
            f"{pad}{json.dumps(k)}:{dumps_discipline_json(obj[k], indent, _level + 1)}"
            for k in sorted(obj)
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(obj, list):
        if not obj or all(not isinstance(v, (dict, list)) for v in obj):
            return json.dumps(obj, separators=(",", ":"))
        pad = " " * (indent * (_level + 1))
        end = " " * (indent * _level)
        items = [f"{pad}{dumps_discipline_json(v, indent, _level + 1)}" for v in obj]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(obj)


_FORBIDDEN_GAP_RE = re.compile(
    r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
    re.IGNORECASE,
)


def check_discipline_artifacts(
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
        return False, f"FAIL: JSON artifact {json_path} is {len(raw_bytes)} bytes (>= {max_json_bytes})"

    json_text = raw_bytes.decode("utf-8")
    md_text = md_path.read_text(encoding="utf-8")
    for p, txt in ((json_path, json_text), (md_path, md_text)):
        if chr(0x2014) in txt or chr(0x2013) in txt:
            return False, f"FAIL: forbidden em/en dash found in {p}"
        if not txt.isascii():
            return False, f"FAIL: non-ASCII character found in {p}"
        if _FORBIDDEN_GAP_RE.search(txt) is not None:
            return False, f"FAIL: forbidden unapproved solver-ratio gap claim in {p}"

    md_lower = md_text.lower()
    json_lower = json_text.lower()
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    coauthor_tag = "co-authored-" + "by"
    if flash_tag in md_lower or flash_tag in json_lower:
        return False, f"FAIL: forbidden {flash_tag} claim found"
    if solver_pct_tag in md_lower or solver_pct_tag in json_lower:
        return False, f"FAIL: forbidden unapproved {solver_pct_tag} claim found"
    if coauthor_tag in md_lower or coauthor_tag in json_lower:
        return False, f"FAIL: forbidden {coauthor_tag} trailer found"

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
        seeds = normalize_discipline_seeds(report.get("seeds", []), enforce_hygiene=True)
    except ValueError as exc:
        return False, f"FAIL: seed hygiene violation: {exc}"
    if len(seeds) != int(report.get("n_seeds", -1)):
        return False, f"FAIL: n_seeds mismatch ({len(seeds)} != {report.get('n_seeds')})"

    rungs = report.get("rung_names", [])
    if list(rungs) != list(RUNG_NAMES):
        return False, f"FAIL: rung_names {rungs!r} does not match canonical 5-rung order {list(RUNG_NAMES)}"

    gs = report.get("gates_summary", {})
    min_sol_thresh = float(gs.get("min_solver_acc_threshold", DEFAULT_MIN_SOLVER_ACC))
    max_logs_thresh = float(gs.get("max_logs_acc_threshold", DEFAULT_MAX_LOGS_ACC))
    if gs.get("all_strategies_passed") is not True:
        return False, "FAIL: gates_summary.all_strategies_passed is not True"
    if float(gs.get("min_solver_acc_observed", 0.0)) < min_sol_thresh:
        return False, "FAIL: solver accuracy below threshold"
    if float(gs.get("max_logs_only_acc_observed", 1.0)) > max_logs_thresh:
        return False, "FAIL: logs_only accuracy above threshold"
    if float(gs.get("max_do_nothing_abs_score", 1.0)) != 0.0:
        return False, "FAIL: DoNothing score is non-zero"
    if gs.get("unique_canonical_strategies") is not True:
        return False, "FAIL: canonical strategies are not unique"

    strats = report.get("strategies", {})
    if not isinstance(strats, dict) or not strats:
        return False, "FAIL: missing strategies block"

    for sname, st in strats.items():
        st_gates = st.get("gates", {})
        if st_gates.get("passed_all") is not True:
            return False, f"FAIL: strategy {sname} gates.passed_all is not True"
        if float(st_gates.get("logs_only_acc", 1.0)) > max_logs_thresh:
            return False, f"FAIL: strategy {sname} logs_only_acc above threshold"
        if float(st_gates.get("do_nothing_max_abs_score", 1.0)) != 0.0:
            return False, f"FAIL: strategy {sname} do_nothing_max_abs_score is non-zero"

        dec = st.get("regret_decomposition")
        if not isinstance(dec, dict):
            return False, f"FAIL: missing regret_decomposition for {sname}"
        m_a = float(dec["delayed_canary_regret"]["mean"])
        m_b = float(dec["gamble_discipline_regret"]["mean"])
        m_c = float(dec["residual_evasion_framing_regret"]["mean"])
        m_tot = float(dec["total_regret"]["mean"])
        if not math.isclose(m_a + m_b + m_c, m_tot, abs_tol=2e-6):
            return False, f"FAIL: decomposition sum mismatch on {sname}: {m_a + m_b + m_c} != {m_tot}"

        r_block = st.get("rungs", {})
        if float(r_block["full_bayesian_solver"]["acc"]) < min_sol_thresh:
            return False, f"FAIL: strategy {sname} solver accuracy below threshold"

        for rname in RUNG_NAMES:
            rb = r_block.get(rname, {})
            sc_vec = rb.get("scores", [])
            if len(sc_vec) != len(seeds):
                return False, f"FAIL: score vector length mismatch on {sname} {rname}"
            mean_sc = sum(float(v) for v in sc_vec) / len(sc_vec)
            if not math.isclose(mean_sc, float(rb["score"]), abs_tol=2e-6):
                return False, f"FAIL: mean(scores) mismatch on {sname} {rname}"

        s0 = r_block["undisciplined_gemini_proxy"]["scores"]
        s1 = r_block["fix_day1_canary_only"]["scores"]
        s3 = r_block["fix_gather_hint_both"]["scores"]
        s4 = r_block["full_bayesian_solver"]["scores"]
        for idx in range(len(seeds)):
            lhs = (float(s1[idx]) - float(s0[idx])) + (float(s3[idx]) - float(s1[idx])) + (float(s4[idx]) - float(s3[idx]))
            rhs = float(s4[idx]) - float(s0[idx])
            if not math.isclose(lhs, rhs, abs_tol=1e-9):
                return False, f"FAIL: per-seed decomposition mismatch on {sname} index {idx}"

        for zero_gamble_rung in ("fix_breakeven_abstain_only", "fix_gather_hint_both", "full_bayesian_solver"):
            if float(r_block[zero_gamble_rung]["below_breakeven_gamble_rate"]) != 0.0:
                return False, f"FAIL: non-zero gamble rate on {sname} {zero_gamble_rung}"
        for day1_rung in ("fix_day1_canary_only", "fix_gather_hint_both", "full_bayesian_solver"):
            if float(r_block[day1_rung]["day1_canary_rate"]) < 1.0:
                return False, f"FAIL: day1_canary_rate < 1.0 on {sname} {day1_rung}"

    expected_md = format_discipline_markdown_report(report)
    if md_text != expected_md:
        return False, f"FAIL: Markdown report {md_path} does not match JSON ledger {json_path}"

    return (
        True,
        f"OK: {json_path.name} ({len(raw_bytes)} bytes, n={len(seeds)} seeds, "
        f"{gs['n_passed']}/{gs['n_strategies']} strategies passed) matches {md_path.name}",
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.mole.discipline_curve")
    ap.add_argument("--tier", default="hard", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="6400-6479")
    ap.add_argument("--strategies", default=None, help="comma-separated subset of mole strategy names")
    ap.add_argument("--rungs", default=None, help="comma-separated subset of discipline rung names")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--n-boot", type=int, default=DEFAULT_BOOTSTRAP_SAMPLES)
    ap.add_argument("--bootstrap-seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    ap.add_argument("--min-solver-acc", type=float, default=DEFAULT_MIN_SOLVER_ACC)
    ap.add_argument("--min-solver-ratio", type=float, default=DEFAULT_MIN_SOLVER_RATIO)
    ap.add_argument("--max-logs-acc", type=float, default=DEFAULT_MAX_LOGS_ACC)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--report-md", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.check:
        j_path = args.out if args.out is not None else DEFAULT_OUTPUT_PATH
        m_path = args.report_md if args.report_md is not None else DEFAULT_REPORT_MD_PATH
        ok, msg = check_discipline_artifacts(json_path=j_path, md_path=m_path)
        print(msg, file=sys.stdout if ok else sys.stderr)
        return 0 if ok else 1

    strat_names = [x.strip() for x in args.strategies.split(",") if x.strip()] if args.strategies else None
    rung_names = [x.strip() for x in args.rungs.split(",") if x.strip()] if args.rungs else None

    report = run_discipline_curve(
        tier=args.tier,
        seeds=args.seeds,
        strategy_names=strat_names,
        rung_names=rung_names,
        workers=args.workers,
        n_boot=args.n_boot,
        bootstrap_seed=args.bootstrap_seed,
        min_solver_acc=args.min_solver_acc,
        min_solver_ratio=args.min_solver_ratio,
        max_logs_acc=args.max_logs_acc,
        enforce_seed_hygiene=True,
    )

    json_payload = dumps_discipline_json(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json_payload + "\n", encoding="utf-8")

    if args.report_md is not None:
        args.report_md.parent.mkdir(parents=True, exist_ok=True)
        args.report_md.write_text(format_discipline_markdown_report(report), encoding="utf-8")

    if args.json:
        print(json_payload)
    else:
        print(format_discipline_summary(report))
    return 0 if report["gates_summary"]["all_strategies_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
