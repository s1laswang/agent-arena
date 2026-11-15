from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import copy
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable, Iterable, Sequence

from canary.baselines import TOPICS
from canary.env import Env
from canary.eval import parse_seeds, run_episode
from canary.forge.fitness import ClassFactory, SOLVER_NAME
from canary.forge.frontier_proxies import (
    CodexHorizonProxy,
    GEMINI_LABELS,
    GeminiCarbonProxy,
    LABELS,
    _FrontierProxyBase,
)
from canary.forge.mutate import canonical, validate_strategy
from canary.forge.rl_mole import RLMole
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy
from canary.mole.evolve_v14 import (
    FORBIDDEN_LOW_SEED_MAX,
    RESERVED_HELDOUT_EVAL_SEEDS,
    V14Mutator,
    _strategy_profile,
    behavior_hash,
)
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TIERS_VERSION
from canary.solver.policy import SolverPolicy

__all__ = [
    "FRONTIER_PROXY_NAMES",
    "BASELINE_INVESTIGATOR_NAMES",
    "CURATED_TRANSCRIPT_STRATEGIES",
    "TRANSCRIPT_ENSEMBLE_STRATEGY",
    "GeminiCarbonOpenCodeProxy",
    "GeminiCarbonInProcProxy",
    "CodexGPT55Proxy",
    "MultiModelProxySuite",
    "frontier_ensemble_investigators",
    "validate_ensemble_seeds",
    "curated_transcript_strategies",
    "evaluate_proxy_ensemble",
    "search_ensemble_strategies",
    "main",
]

FRONTIER_PROXY_NAMES: tuple[str, ...] = (
    "gemini_opencode_proxy",
    "gemini_inproc_proxy",
    "codex_gpt55_proxy",
    "gemini_carbon_proxy",
    "codex_horizon_proxy",
)

BASELINE_INVESTIGATOR_NAMES: tuple[str, ...] = (
    "heuristic",
    "hinted_heuristic",
    "grok_tactics",
)

CURATED_TRANSCRIPT_STRATEGIES: dict[str, dict[str, Any]] = {
    "surgical_trap_shield": {
        "name": "surgical_trap_shield",
        "rules": [
            {
                "if": [["recent_low_recipient_docs", ">=", 1]],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "wide_crowd_preference": {
        "name": "wide_crowd_preference",
        "rules": [
            {
                "if": [
                    ["day", "<=", 6],
                    ["min_recipient_count", "<=", 8],
                    ["max_recipient_count", ">=", 12],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "reactive_canary_lag": {
        "name": "reactive_canary_lag",
        "rules": [
            {
                "if": [
                    ["day", "<=", 8],
                    ["newest_doc_age_days", "==", 0],
                    ["n_leakable", ">=", 2],
                ],
                "then": {"leak": "oldest", "frame": "random_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "non_decoy_tiebreak_framing": {
        "name": "non_decoy_tiebreak_framing",
        "rules": [
            {
                "if": [["n_restricted_colleagues", ">=", 1]],
                "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            }
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "early_burst_then_paced": {
        "name": "early_burst_then_paced",
        "rules": [
            {
                "if": [["day", "<=", 3]],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", ">=", 4],
                    ["day", "<=", 6],
                    ["days_since_last_leak", "<", 2],
                ],
                "then": {"leak": "none", "frame": "random_peer"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
    "ensemble_multicohort_v14": {
        "name": "ensemble_multicohort_v14",
        "rules": [
            {
                "if": [
                    ["day", "<=", 9],
                    ["recent_low_recipient_docs", ">=", 1],
                    ["max_recipient_count", ">=", 8],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", "<=", 6],
                    ["min_recipient_count", "<=", 8],
                    ["max_recipient_count", ">=", 12],
                ],
                "then": {"leak": "most_recipients", "frame": "random_peer"},
            },
            {
                "if": [
                    ["day", "<=", 5],
                    ["newest_doc_age_days", "==", 0],
                    ["n_leakable", ">=", 3],
                ],
                "then": {"leak": "oldest", "frame": "random_peer"},
            },
            {
                "if": [["n_restricted_colleagues", ">=", 1]],
                "then": {"leak": "random_seeded", "frame": "most_restricted_peer"},
            },
        ],
        "default": {"leak": "random_seeded", "frame": "random_peer"},
    },
}

TRANSCRIPT_ENSEMBLE_STRATEGY = MoleStrategy.from_json(
    CURATED_TRANSCRIPT_STRATEGIES["ensemble_multicohort_v14"]
)

_MSG_QUERIES: tuple[str, ...] = ("unfair", "angry", "promotion", "joke", "goalposts")
_EPISODE_CACHE: dict[tuple[str, str, int, str, str], dict[str, Any]] = {}


def _sync_instruction_fields(proxy: _FrontierProxyBase, instruction: str) -> None:
    text = instruction or ""
    m_can = re.search(r"plant at most (\d+) per day", text)
    if m_can:
        proxy.canaries_per_day = max(1, int(m_can.group(1)))

    m_act = re.search(r"one of your (\d+) actions per day", text)
    if m_act:
        proxy.actions_per_day = max(1, int(m_act.group(1)))
        proxy.actions_left = proxy.actions_per_day

    m_cap = re.search(r"total limit of (\d+) calls", text)
    if m_cap:
        proxy.tool_call_cap = max(20, int(m_cap.group(1)))

    m_emp = re.search(r"company with (\d+) employees", text)
    proxy.n_employees_hint = int(m_emp.group(1)) if m_emp else 0

    m_wrong = re.search(r"accuse an innocent employee, your score is (-?[0-9]+(?:\.[0-9]+)?)", text)
    if m_wrong:
        proxy.wrong_accusation_score = float(m_wrong.group(1))


class GeminiCarbonOpenCodeProxy(GeminiCarbonProxy):
    name = "gemini_opencode_proxy"

    def __init__(
        self,
        seed: int = 0,
        flip_underweight: float = 0.02,
        accuse_p: float = 0.76,
        daily_interview_cap: int = 6,
        d1_canary_share: float = 0.35,
        wide_canary_share: float = 0.50,
        midgame_spike_p: float = 0.24,
        midgame_spike_gap: int = 1,
        midgame_min_ah: int = 3,
        horizon_min_p: float = 0.20,
    ):
        self.daily_interview_cap = daily_interview_cap
        self.d1_canary_share = d1_canary_share
        self.wide_canary_share = wide_canary_share
        self.midgame_spike_p = midgame_spike_p
        self.midgame_spike_gap = midgame_spike_gap
        self.midgame_min_ah = midgame_min_ah
        self.horizon_min_p = horizon_min_p
        self.n_employees_hint = 0
        self.first_canary_day = 3
        super().__init__(seed=seed, flip_underweight=flip_underweight, accuse_p=accuse_p)

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        super().reset(tools_spec, instruction)
        _sync_instruction_fields(self, instruction)
        is_hard_like = self.n_days >= 18 or self.canaries_per_day >= 2 or self.n_employees_hint >= 30
        u = self.rng.random()
        if is_hard_like:
            if (self.seed % 10) in (1, 4, 7) and u < min(0.95, self.d1_canary_share * 2.2):
                self.first_canary_day = 1
            else:
                self.first_canary_day = 4 if u < 0.68 else 3
        else:
            self.first_canary_day = 1 if u < 0.90 else 2

    def _build_day_queue(self) -> list[tuple[str, dict[str, Any]]]:
        q: list[tuple[str, dict[str, Any]]] = [("status", {})]
        d_from = 1 if self.day == 1 else max(1, self.day - 2)
        q.append(("list_documents", {"day_from": d_from, "day_to": self.day}))
        if self.has_decoy and self.day <= 4 and (self.day == 1 or self.decoy is None or self.day in (2, 4)):
            q_word = _MSG_QUERIES[(self.day - 1) % len(_MSG_QUERIES)]
            q.append(("search_messages", {"query": q_word}))
        if self.day >= 2 and (self.day % 2 == 0 or self.day >= self.n_days - 3 or self.canaries_planted_total > 0 and self.day % 3 == 0):
            q.append(("check_leak_feed", {}))
        if self.day > 1 and self.last_log_day < self.day - 1:
            if self.day % 2 == 0 or self.day >= self.n_days - 4:
                q.append(("read_access_logs", {"day_from": self.last_log_day + 1, "day_to": self.day - 1}))
        q.append(("__decide__", {}))
        return q

    def _behav_tie(self, emp: str) -> tuple[float, int, int]:
        if self.has_decoy and emp == self.decoy:
            return (-100.0, -1, -1)
        ah = self.after_hours[emp]
        ev = self.evasive_counts[emp]
        coop = self.coop_counts[emp]
        tot = self.total_logs[emp]
        score = 1.6 * ah + 1.1 * ev - 0.25 * coop + 0.08 * tot
        return (round(score, 4), ah, tot)

    def _canary_subset(self, live: list[str], subj_post: dict[str, float], plant_idx: int) -> list[str]:
        unrestricted_live = [e for e in live if e not in self.restricted and not (self.has_decoy and e == self.decoy)]
        unrestricted_all = [e for e in self.emps if e not in self.restricted and not (self.has_decoy and e == self.decoy)]
        if not unrestricted_all:
            unrestricted_all = [e for e in self.emps if e not in self.restricted]
        if len(unrestricted_all) < 2:
            return []

        unrestricted_live.sort(
            key=lambda e: (
                -round(subj_post.get(e, 0.0), 5),
                -self._non_decoy_ah(e)[0],
                self.canary_exposures[e] // 3,
                -self.tie_order[e],
            )
        )
        want_wide = ((self.day + plant_idx + (self.seed % 3)) % 2 == 0) if abs(self.wide_canary_share - 0.5) < 0.05 else (self.rng.random() < self.wide_canary_share)
        if want_wide and len(unrestricted_all) >= 9:
            target_n = 12 if (len(unrestricted_live) >= 12 and self.day <= 8) else 9
        else:
            target_n = 6 if len(unrestricted_all) >= 6 else max(4, len(unrestricted_all))
        target_n = min(len(unrestricted_all), max(4, target_n)) if len(unrestricted_all) >= 4 else len(unrestricted_all)

        chosen = list(unrestricted_live[:target_n])
        if len(chosen) < target_n:
            chosen_set = set(chosen)
            extras = [e for e in unrestricted_all if e not in chosen_set]
            extras.sort(key=lambda e: (self.canary_exposures[e], -self._non_decoy_ah(e)[0], -self.tie_order[e]))
            chosen.extend(extras[: target_n - len(chosen)])
        return chosen

    def _plan_canaries_today(self, live: list[str]) -> int:
        if self.day < self.first_canary_day or self.canaries_per_day < 1 or len(live) < 2:
            return 0
        roll = (self.day * 7 + self.seed * 3) % 10
        if roll in (0, 5) and self.day > self.first_canary_day:
            return 0
        if self.canaries_per_day >= 2 and roll in (2, 6, 9):
            return 2
        return 1

    def _select_midgame_accuse(self, live: list[str], subj_post: dict[str, float]) -> str | None:
        best = max(live, key=lambda e: (round(subj_post[e], 6), self._behav_tie(e), self.tie_order[e]))
        pb = subj_post[best]
        ev = pb * self.V + (1.0 - pb) * self.wrong_accusation_score
        if pb >= self.accuse_p and ev > 0.0:
            return best

        non_decoy_live = [e for e in live if not (self.has_decoy and e == self.decoy)]
        if len(non_decoy_live) >= 2 and self.day >= max(7, self.n_days // 3):
            by_ah = sorted(
                non_decoy_live,
                key=lambda e: (self.after_hours[e], self._behav_tie(e)[0], subj_post[e], self.tie_order[e]),
                reverse=True,
            )
            leader = by_ah[0]
            runner_up = by_ah[1]
            ah_gap = self.after_hours[leader] - self.after_hours[runner_up]
            if (
                self.after_hours[leader] >= self.midgame_min_ah
                and ah_gap >= self.midgame_spike_gap
                and subj_post[leader] >= self.midgame_spike_p
            ):
                return leader
        return None

    def _handle_marker(self, marker: str) -> None:
        if marker != "__decide__":
            return
        pool = self._suspect_pool()
        subj_post = self._posterior(pool, self._subjective_q())
        live = sorted([e for e in pool if subj_post[e] > 1e-4]) or sorted(pool)

        accuse_target = self._select_midgame_accuse(live, subj_post)
        if accuse_target is not None:
            self.queue = [("accuse", {"employee": accuse_target})]
            return

        if self.day >= self.n_days:
            top_p = max(subj_post[e] for e in live)
            band = [e for e in live if subj_post[e] >= top_p - 0.14]
            winner = max(band, key=lambda e: (self._behav_tie(e), round(subj_post[e], 6), self.tie_order[e]))
            max_ah = max((self._non_decoy_ah(e)[0] for e in band), default=0)
            if top_p >= self.horizon_min_p or (top_p >= 0.14 and max_ah >= 4):
                self.queue = [("accuse", {"employee": winner})]
            else:
                self.queue = [("advance_day", {})]
            return

        n_canaries = min(self._plan_canaries_today(live), self.actions_left)
        iv_slots = min(self.daily_interview_cap, max(0, self.actions_left - n_canaries))

        nxt: list[tuple[str, dict[str, Any]]] = []
        iv_pool = [e for e in live if not (self.has_decoy and e == self.decoy)] or list(live)
        iv_pool.sort(
            key=lambda e: (
                self.evasive_counts[e] + self.coop_counts[e],
                -round(subj_post.get(e, 0.0), 5),
                -self._non_decoy_ah(e)[0],
                -self.tie_order[e],
            )
        )
        for idx in range(iv_slots):
            emp = iv_pool[idx % len(iv_pool)]
            topic = TOPICS[(self.interview_cursor + idx) % len(TOPICS)]
            nxt.append(("interview", {"employee": emp, "topic": topic}))
        self.interview_cursor += iv_slots

        for c_idx in range(n_canaries):
            subset = self._canary_subset(live, subj_post, c_idx)
            if len(subset) < 2:
                break
            k_var = min(self.max_variants, 3, len(subset))
            labels = GEMINI_LABELS[:k_var]
            asg = {emp: labels[i % k_var] for i, emp in enumerate(subset)}
            nxt.append(("plant_canary", {"doc_title": f"Security review brief d{self.day}.{c_idx + 1}", "assignment": asg}))

        nxt.append(("advance_day", {}))
        self.queue = nxt


class GeminiCarbonInProcProxy(GeminiCarbonOpenCodeProxy):
    name = "gemini_inproc_proxy"

    def __init__(
        self,
        seed: int = 0,
        flip_underweight: float = 0.28,
        accuse_p: float = 0.90,
        daily_interview_cap: int = 4,
        d1_canary_share: float = 0.30,
        wide_canary_share: float = 0.56,
        midgame_spike_p: float = 0.58,
        midgame_spike_gap: int = 3,
        midgame_min_ah: int = 5,
        horizon_min_p: float = 0.44,
    ):
        super().__init__(
            seed=seed,
            flip_underweight=flip_underweight,
            accuse_p=accuse_p,
            daily_interview_cap=daily_interview_cap,
            d1_canary_share=d1_canary_share,
            wide_canary_share=wide_canary_share,
            midgame_spike_p=midgame_spike_p,
            midgame_spike_gap=midgame_spike_gap,
            midgame_min_ah=midgame_min_ah,
            horizon_min_p=horizon_min_p,
        )

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        super().reset(tools_spec, instruction)
        is_hard_like = self.n_days >= 18 or self.canaries_per_day >= 2 or self.n_employees_hint >= 30
        u = self.rng.random()
        if is_hard_like:
            if (self.seed % 10) in (1, 5, 8) and u < 0.95:
                self.first_canary_day = 1
            else:
                self.first_canary_day = 5 if u < 0.38 else 4
        else:
            self.first_canary_day = 1 if u < 0.80 else 3

    def _handle_marker(self, marker: str) -> None:
        if marker != "__decide__":
            return
        pool = self._suspect_pool()
        subj_post = self._posterior(pool, self._subjective_q())
        live = sorted([e for e in pool if subj_post[e] > 1e-4]) or sorted(pool)

        accuse_target = self._select_midgame_accuse(live, subj_post)
        if accuse_target is not None:
            self.queue = [("accuse", {"employee": accuse_target})]
            return

        if self.day >= self.n_days:
            top_p = max(subj_post[e] for e in live)
            band = [e for e in live if subj_post[e] >= top_p - 0.08]
            winner = max(band, key=lambda e: (round(subj_post[e], 6), self._behav_tie(e), self.tie_order[e]))
            if top_p >= self.horizon_min_p:
                self.queue = [("accuse", {"employee": winner})]
            else:
                self.queue = [("advance_day", {})]
            return

        super()._handle_marker(marker)


class CodexGPT55Proxy(CodexHorizonProxy):
    name = "codex_gpt55_proxy"

    def __init__(
        self,
        seed: int = 0,
        accuse_p: float = 0.86,
        spike_min_ah: int = 3,
        spike_gap: int = 2,
        log_weight: float = 2.8,
    ):
        self.log_weight = log_weight
        self.n_employees_hint = 0
        super().__init__(seed=seed, accuse_p=accuse_p, spike_min_ah=spike_min_ah, spike_gap=spike_gap)

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        super().reset(tools_spec, instruction)
        _sync_instruction_fields(self, instruction)

    def _build_day_queue(self) -> list[tuple[str, dict[str, Any]]]:
        q: list[tuple[str, dict[str, Any]]] = [("status", {})]
        d_from = 1 if self.day == 1 else max(1, self.day - 2)
        q.append(("list_documents", {"day_from": d_from, "day_to": self.day}))
        if self.has_decoy and (self.day <= 3 or (self.decoy is None and self.day <= 6) or self.day % 3 == 0):
            q_word = _MSG_QUERIES[(self.day - 1) % len(_MSG_QUERIES)]
            q.append(("search_messages", {"query": q_word}))
        q.append(("check_leak_feed", {}))
        if self.day > 1 and self.last_log_day < self.day - 1:
            q.append(("read_access_logs", {"day_from": self.last_log_day + 1, "day_to": self.day - 1}))
        q.append(("__post_obs__", {}))
        return q

    def _behav_score(self, emp: str) -> float:
        if self.has_decoy and emp == self.decoy:
            return -20.0
        return (
            self.log_weight * self.after_hours[emp]
            + 0.25 * self.total_logs[emp]
            + 1.6 * self.evasive_counts[emp]
            - 0.20 * self.coop_counts[emp]
        )

    def _preferred_variants(self) -> int:
        n_staff = len(self.emps) or self.n_employees_hint
        if n_staff >= 30:
            return min(2, self.max_variants)
        return min(3, self.max_variants)

    def _check_accuse(self, live: list[str], true_post: dict[str, float]) -> str | None:
        best = max(live, key=lambda e: (round(true_post[e], 6), self._behav_score(e), self.tie_order[e]))
        threshold = 1.0 / (1.0 + max(self.V, 1e-6))
        if len(live) == 1:
            return live[0]
        if true_post[best] >= self.accuse_p and true_post[best] > threshold:
            return best

        non_decoy_live = [e for e in live if not (self.has_decoy and e == self.decoy)]
        if len(non_decoy_live) >= 2 and self.day >= 6 and len(live) <= 6:
            by_ah = sorted(
                non_decoy_live,
                key=lambda e: (
                    self.after_hours[e],
                    self._behav_score(e),
                    true_post[e],
                    self.tie_order[e],
                ),
                reverse=True,
            )
            top_e, sec_e = by_ah[0], by_ah[1]
            if (
                self.after_hours[top_e] >= self.spike_min_ah
                and self.after_hours[top_e] - self.after_hours[sec_e] >= self.spike_gap
                and true_post[top_e] >= 0.20
            ):
                return top_e

        if self.day >= self.n_days:
            return max(
                live,
                key=lambda e: (
                    round(true_post[e], 3) + 0.08 * self._behav_score(e),
                    self._behav_score(e),
                    self.tie_order[e],
                ),
            )
        return None

    def _handle_marker(self, marker: str) -> None:
        pool = self._suspect_pool()
        true_post = self._posterior(pool, self.fingerprint_accuracy)
        live = sorted([e for e in pool if true_post[e] > 1e-4]) or sorted(pool)

        if marker == "__post_obs__":
            target = self._check_accuse(live, true_post)
            if target is not None:
                self.queue = [("accuse", {"employee": target})]
                return

            reserve = 1 if (self.canaries_per_day >= 1 and len(live) >= 2) else 0
            want_iv = 1 if (self.day % 2 == 1 or len(live) <= 5) else 0
            iv_budget = min(want_iv, max(0, self.actions_left - reserve))
            iv_cands = sorted(
                [e for e in live if e not in self.interviewed_today and not (self.has_decoy and e == self.decoy)],
                key=lambda e: (
                    -round(true_post[e], 4),
                    -self._behav_score(e),
                    self.evasive_counts[e] + self.coop_counts[e],
                    -self.tie_order[e],
                ),
            )
            nxt: list[tuple[str, dict[str, Any]]] = []
            for emp in iv_cands[:iv_budget]:
                topic = TOPICS[self.interview_cursor % len(TOPICS)]
                self.interview_cursor += 1
                nxt.append(("interview", {"employee": emp, "topic": topic}))
            nxt.append(("__plant__", {}))
            self.queue = nxt
            return

        if marker == "__plant__":
            target = self._check_accuse(live, true_post)
            if target is not None:
                self.queue = [("accuse", {"employee": target})]
                return

            cand = [e for e in live if e not in self.restricted and not (self.has_decoy and e == self.decoy)]
            if len(cand) < 2:
                cand = [e for e in live if e not in self.restricted]
            if self.canaries_per_day >= 1 and self.actions_left >= 1 and len(cand) >= 2:
                cand.sort(
                    key=lambda e: (
                        -round(true_post[e], 4),
                        -self._behav_score(e),
                        self.canary_exposures[e],
                        -self.tie_order[e],
                    )
                )
                n_staff = len(self.emps) or self.n_employees_hint
                k_var = min(self._preferred_variants(), len(cand))
                is_medium_like = n_staff < 30
                if is_medium_like:
                    surgical = (self.day == 1) or ((self.day % 3) != 0) or len(cand) <= 3
                else:
                    surgical = (self.day in (1, 2)) or ((self.day % 2) == 1 and self.day <= 11) or len(cand) <= 3

                if surgical:
                    target_recips = min(len(cand), 3 if is_medium_like else max(2, k_var))
                    target_recips = min(3, max(2, target_recips))
                elif not is_medium_like and (self.day % 4 == 0) and len(cand) >= 10:
                    target_recips = min(len(cand), 10)
                else:
                    target_recips = min(len(cand), max(4, 2 * k_var))

                chosen = cand[:target_recips]
                use_vars = min(k_var, len(chosen))
                labels = LABELS[:use_vars]
                asg = {emp: labels[i % use_vars] for i, emp in enumerate(chosen)}
                self.queue = [
                    ("plant_canary", {"doc_title": f"Codex audit brief d{self.day}", "assignment": asg}),
                    ("advance_day", {}),
                ]
                return

            self.queue = [("advance_day", {})]


def frontier_ensemble_investigators(include_baselines: bool = True) -> dict[str, Callable]:
    inv: dict[str, Callable] = {
        "gemini_opencode_proxy": ClassFactory("canary.forge.proxy_ensemble", "GeminiCarbonOpenCodeProxy"),
        "gemini_inproc_proxy": ClassFactory("canary.forge.proxy_ensemble", "GeminiCarbonInProcProxy"),
        "codex_gpt55_proxy": ClassFactory("canary.forge.proxy_ensemble", "CodexGPT55Proxy"),
        "gemini_carbon_proxy": ClassFactory("canary.forge.frontier_proxies", "GeminiCarbonProxy"),
        "codex_horizon_proxy": ClassFactory("canary.forge.frontier_proxies", "CodexHorizonProxy"),
    }
    if include_baselines:
        inv["heuristic"] = ClassFactory("canary.baselines", "Heuristic")
        inv["hinted_heuristic"] = ClassFactory("canary.forge.investigators", "HintedHeuristic")
        inv["grok_tactics"] = ClassFactory("canary.baselines", "GrokTactics")
    return inv


class MultiModelProxySuite(dict):
    def __init__(self, include_baselines: bool = True):
        super().__init__(frontier_ensemble_investigators(include_baselines=include_baselines))
        self.include_baselines = include_baselines

    @property
    def proxy_names(self) -> tuple[str, ...]:
        return FRONTIER_PROXY_NAMES

    def frontier_factories(self) -> dict[str, Callable]:
        return frontier_ensemble_investigators(include_baselines=False)

    def investigators(self, include_baselines: bool | None = None) -> dict[str, Callable]:
        flag = self.include_baselines if include_baselines is None else include_baselines
        return frontier_ensemble_investigators(include_baselines=flag)

    def evaluate(
        self,
        strategy_obj: Any,
        tier: str = "hard",
        seeds: Iterable[int] = range(6400, 6420),
        min_solver_acc: float = 0.85,
        min_solver_ratio: float = 0.50,
    ) -> dict[str, Any]:
        return evaluate_proxy_ensemble(
            strategy_obj,
            tier=tier,
            seeds=seeds,
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
        )


def validate_ensemble_seeds(
    seeds: Iterable[int],
    *,
    label: str = "seeds",
    forbid_reserved_train: bool = False,
) -> list[int]:
    out = list(seeds)
    if not out:
        raise ValueError(f"{label} must not be empty")
    for s in out:
        if isinstance(s, bool) or not isinstance(s, int):
            raise ValueError(f"{label} contains non-integer seed: {s!r}")
        if s <= FORBIDDEN_LOW_SEED_MAX:
            raise ValueError(f"{label} contains forbidden low seed {s}; seeds < 30 are prohibited")
        if s >= 800_000 or s in JUDGE_SEEDS or s in HELDOUT_SEEDS:
            raise ValueError(f"{label} contains forbidden heldout/judge seed {s}; seeds >= 800000 are prohibited")
        if forbid_reserved_train and s in RESERVED_HELDOUT_EVAL_SEEDS:
            raise ValueError(f"{label} contains reserved heldout seed {s} in 30000..30199")
    return out


def curated_transcript_strategies() -> list[MoleStrategy]:
    return [MoleStrategy.from_json(spec) for spec in CURATED_TRANSCRIPT_STRATEGIES.values()]


def _coerce_strategy(strategy_obj: Any) -> MoleStrategy | RLMole:
    if strategy_obj is None:
        return DEFAULT_STRATEGY
    if isinstance(strategy_obj, MoleStrategy):
        return strategy_obj
    if isinstance(strategy_obj, RLMole):
        return RLMole.from_json(strategy_obj.to_json())
    if isinstance(strategy_obj, str):
        stripped = strategy_obj.strip()
        if stripped in ("default", "default_v0"):
            return DEFAULT_STRATEGY
        if stripped in CURATED_TRANSCRIPT_STRATEGIES:
            return MoleStrategy.from_json(CURATED_TRANSCRIPT_STRATEGIES[stripped])
        p = Path(stripped)
        if p.is_file():
            raw_txt = p.read_text(encoding="utf-8").strip()
            first_line = next((ln for ln in raw_txt.splitlines() if ln.strip()), "")
            return _coerce_strategy(json.loads(first_line if p.suffix == ".jsonl" else raw_txt))
        return _coerce_strategy(json.loads(stripped))
    if isinstance(strategy_obj, dict):
        payload = dict(strategy_obj.get("strategy_json", strategy_obj.get("strategy", strategy_obj)))
        if payload.get("kind") == "rl_mole":
            return RLMole.from_json(payload)
        return MoleStrategy.from_json(payload)
    raise TypeError(f"unsupported strategy object type: {type(strategy_obj).__name__}")


def _strategy_key_and_payload(strat: MoleStrategy | RLMole) -> tuple[str, dict[str, Any]]:
    sj = strat.to_json()
    if isinstance(strat, MoleStrategy):
        key_payload = {"rules": sj.get("rules", []), "default": sj.get("default", {})}
        return canonical(key_payload), sj
    return json.dumps(sj, sort_keys=True, separators=(",", ":")), sj


def _instantiate_strategy(sj: dict[str, Any]) -> MoleStrategy | RLMole:
    if sj.get("kind") == "rl_mole":
        return RLMole.from_json(sj)
    return MoleStrategy.from_json(sj)


def _run_single_agent_episode(
    tier: str,
    seed: int,
    strategy_json: dict[str, Any],
    agent_name: str,
) -> dict[str, Any]:
    strat = _instantiate_strategy(strategy_json)
    env = Env(tier=tier, seed=seed, mole_strategy=strat)
    if agent_name == SOLVER_NAME:
        policy = SolverPolicy(tier)
    else:
        factories = frontier_ensemble_investigators(include_baselines=True)
        policy = factories[agent_name](seed)
    ep = run_episode(env, policy)
    return {
        "score": float(ep.score),
        "correct": bool(ep.correct),
        "wrong": bool(ep.accused is not None and not ep.correct),
        "abstain": bool(ep.accused is None),
        "final_day": int(ep.final_day),
    }


def _seed_bundle_worker(
    args: tuple[str, int, str, dict[str, Any], tuple[str, ...]],
) -> tuple[tuple[str, int, str], dict[str, dict[str, Any]]]:
    tier, seed, skey, strategy_json, agent_names = args
    out: dict[str, dict[str, Any]] = {}
    for agent_name in agent_names:
        out[agent_name] = _run_single_agent_episode(tier, seed, strategy_json, agent_name)
    return (tier, seed, skey), out


def _ensure_cached_runs(
    tier: str,
    seeds: Sequence[int],
    strategies: Sequence[tuple[str, dict[str, Any]]],
    agent_names: Sequence[str],
    workers: int | None = None,
) -> None:
    ver = TIERS_VERSION
    missing: list[tuple[str, int, str, dict[str, Any], tuple[str, ...]]] = []
    seen_req: set[tuple[str, int, str, tuple[str, ...]]] = set()

    for skey, sjson in strategies:
        for seed in seeds:
            needed = tuple(a for a in agent_names if (ver, tier, seed, skey, a) not in _EPISODE_CACHE)
            if not needed:
                continue
            req_id = (tier, seed, skey, needed)
            if req_id in seen_req:
                continue
            seen_req.add(req_id)
            missing.append((tier, seed, skey, sjson, needed))

    if not missing:
        return

    if workers is None:
        max_w = 1
    else:
        max_w = max(1, min(int(workers), len(missing)))

    if max_w > 1:
        with ProcessPoolExecutor(max_workers=max_w) as ex:
            results = list(ex.map(_seed_bundle_worker, missing))
    else:
        results = [_seed_bundle_worker(item) for item in missing]

    for (t_name, s_val, skey), agent_map in results:
        for agent_name, metrics in agent_map.items():
            _EPISODE_CACHE[(ver, t_name, s_val, skey, agent_name)] = metrics


def _summarize_cached(
    tier: str,
    seeds: Sequence[int],
    skey: str,
    solver_rows: Sequence[dict[str, Any]],
    proxy_names: Sequence[str],
) -> dict[str, dict[str, float]]:
    ver = TIERS_VERSION
    n = len(seeds)
    per_proxy: dict[str, dict[str, float]] = {}
    for pname in proxy_names:
        prows = [_EPISODE_CACHE[(ver, tier, s, skey, pname)] for s in seeds]
        mean_score = sum(r["score"] for r in prows) / n
        mean_acc = sum(1.0 if r["correct"] else 0.0 for r in prows) / n
        wrong_rate = sum(1.0 if r["wrong"] else 0.0 for r in prows) / n
        abstain_rate = sum(1.0 if r["abstain"] else 0.0 for r in prows) / n
        mean_day = sum(r["final_day"] for r in prows) / n
        paired_regret = sum(sr["score"] - pr["score"] for sr, pr in zip(solver_rows, prows)) / n
        per_proxy[pname] = {
            "score": mean_score,
            "acc": mean_acc,
            "wrong_rate": wrong_rate,
            "abstain_rate": abstain_rate,
            "mean_final_day": mean_day,
            "paired_regret_vs_solver": paired_regret,
        }
    return per_proxy


def evaluate_proxy_ensemble(
    strategy_obj: Any,
    tier: str = "hard",
    seeds: Iterable[int] = range(6400, 6420),
    min_solver_acc: float = 0.85,
    min_solver_ratio: float = 0.50,
    *,
    include_baselines: bool = False,
    workers: int | None = None,
) -> dict[str, Any]:
    seed_list = validate_ensemble_seeds(seeds, label="seeds")
    strat = _coerce_strategy(strategy_obj)
    skey, sjson = _strategy_key_and_payload(strat)
    def_key, def_json = _strategy_key_and_payload(DEFAULT_STRATEGY)

    agent_names: tuple[str, ...] = (SOLVER_NAME, *FRONTIER_PROXY_NAMES)
    if include_baselines:
        agent_names = (*agent_names, *BASELINE_INVESTIGATOR_NAMES)

    strat_pairs: list[tuple[str, dict[str, Any]]] = [(def_key, def_json)]
    if skey != def_key:
        strat_pairs.append((skey, sjson))

    _ensure_cached_runs(tier, seed_list, strat_pairs, agent_names, workers=workers)

    ver = TIERS_VERSION
    n = len(seed_list)
    def_solver_rows = [_EPISODE_CACHE[(ver, tier, s, def_key, SOLVER_NAME)] for s in seed_list]
    baseline_solver_score = sum(r["score"] for r in def_solver_rows) / n
    baseline_solver_acc = sum(1.0 if r["correct"] else 0.0 for r in def_solver_rows) / n
    def_per_proxy = _summarize_cached(tier, seed_list, def_key, def_solver_rows, FRONTIER_PROXY_NAMES)
    default_worst_regret = min(v["paired_regret_vs_solver"] for v in def_per_proxy.values())
    default_mean_regret = sum(v["paired_regret_vs_solver"] for v in def_per_proxy.values()) / len(def_per_proxy)

    solver_rows = [_EPISODE_CACHE[(ver, tier, s, skey, SOLVER_NAME)] for s in seed_list]
    solver_score = sum(r["score"] for r in solver_rows) / n
    solver_acc = sum(1.0 if r["correct"] else 0.0 for r in solver_rows) / n
    solver_mean_day = sum(r["final_day"] for r in solver_rows) / n

    per_proxy = _summarize_cached(tier, seed_list, skey, solver_rows, FRONTIER_PROXY_NAMES)
    for pname, pmetrics in per_proxy.items():
        pmetrics["default_score"] = def_per_proxy[pname]["score"]
        pmetrics["default_paired_regret_vs_solver"] = def_per_proxy[pname]["paired_regret_vs_solver"]

    worst_proxy_name = min(per_proxy, key=lambda k: per_proxy[k]["paired_regret_vs_solver"])
    worst_case_proxy_regret = per_proxy[worst_proxy_name]["paired_regret_vs_solver"]
    mean_proxy_regret = sum(v["paired_regret_vs_solver"] for v in per_proxy.values()) / len(per_proxy)

    feasible = bool(
        solver_acc >= min_solver_acc
        and solver_score >= min_solver_ratio * baseline_solver_score
    )
    pareto_dominates_default = bool(
        feasible and (worst_case_proxy_regret > default_worst_regret + 1e-9)
    )

    out: dict[str, Any] = {
        "strategy_name": strat.name,
        "strategy_json": sjson,
        "tier": tier,
        "seeds": seed_list,
        "n_seeds": n,
        "min_solver_acc": float(min_solver_acc),
        "min_solver_ratio": float(min_solver_ratio),
        "solver_score": solver_score,
        "solver_acc": solver_acc,
        "solver_mean_final_day": solver_mean_day,
        "baseline_solver_score": baseline_solver_score,
        "baseline_solver_acc": baseline_solver_acc,
        "feasible": feasible,
        "per_proxy": per_proxy,
        "worst_case_proxy": worst_proxy_name,
        "worst_case_proxy_regret": worst_case_proxy_regret,
        "mean_proxy_regret": mean_proxy_regret,
        "default_worst_case_proxy_regret": default_worst_regret,
        "default_mean_proxy_regret": default_mean_regret,
        "pareto_dominates_default": pareto_dominates_default,
    }
    if include_baselines:
        out["per_baseline"] = _summarize_cached(
            tier, seed_list, skey, solver_rows, BASELINE_INVESTIGATOR_NAMES
        )
    return out


def search_ensemble_strategies(
    candidates: Sequence[Any] | None = None,
    n_mutations: int = 12,
    seed: int = 0,
    tier: str = "hard",
    train_seeds: Iterable[int] = range(6400, 6416),
    holdout_seeds: Iterable[int] = range(6420, 6436),
    min_solver_acc: float = 0.85,
    *,
    min_solver_ratio: float = 0.50,
    workers: int | None = None,
) -> dict[str, Any]:
    train_list = validate_ensemble_seeds(
        train_seeds, label="train_seeds", forbid_reserved_train=True
    )
    holdout_list = validate_ensemble_seeds(holdout_seeds, label="holdout_seeds")
    overlap = sorted(set(train_list) & set(holdout_list))
    if overlap:
        raise ValueError(f"train_seeds and holdout_seeds must be disjoint; overlap={overlap[:10]}")

    seed_pool: list[MoleStrategy] = []
    if candidates is None:
        seed_pool.append(DEFAULT_STRATEGY)
        seed_pool.extend(curated_transcript_strategies())
    else:
        for item in candidates:
            coerced = _coerce_strategy(item)
            if isinstance(coerced, MoleStrategy):
                seed_pool.append(coerced)
        if not seed_pool:
            seed_pool.append(DEFAULT_STRATEGY)
            seed_pool.extend(curated_transcript_strategies())

    unique_by_bhash: dict[str, MoleStrategy] = {}
    for st in seed_pool:
        bh = behavior_hash(st.to_json(), tier)
        unique_by_bhash.setdefault(bh, st)

    mutator = V14Mutator(seed=seed, tier=tier)
    parent_specs = [
        {
            "strategy_json": validate_strategy(
                {"rules": st.to_json()["rules"], "default": st.to_json()["default"]}
            ),
            "fitness": None,
            "beaten_tags": [],
        }
        for st in unique_by_bhash.values()
    ]
    if n_mutations > 0:
        proposed = mutator.propose(parent_specs, int(n_mutations))
        for idx, raw_sj in enumerate(proposed):
            named = copy.deepcopy(raw_sj)
            named["name"] = f"v14_mut_{seed}_{idx:02d}"
            st = MoleStrategy.from_json(named)
            bh = behavior_hash(st.to_json(), tier)
            if bh not in unique_by_bhash:
                unique_by_bhash[bh] = st

    min_leak_rate = 0.45 if min_solver_acc >= 0.75 else 0.15
    active_candidates = [
        (bh, st)
        for bh, st in unique_by_bhash.items()
        if _strategy_profile(st, tier)["leak_rate"] >= min_leak_rate
    ]
    if not active_candidates:
        active_candidates = list(unique_by_bhash.items())

    def_key, def_json = _strategy_key_and_payload(DEFAULT_STRATEGY)
    proxy_pairs = [(_strategy_key_and_payload(st)) for _, st in active_candidates]
    _ensure_cached_runs(
        tier,
        train_list,
        [(def_key, def_json), *proxy_pairs],
        FRONTIER_PROXY_NAMES,
        workers=1,
    )

    ver = TIERS_VERSION
    scored_proxy_screen: list[tuple[float, float, str, MoleStrategy]] = []
    for bh, st in active_candidates:
        skey, _ = _strategy_key_and_payload(st)
        p_means = [
            sum(_EPISODE_CACHE[(ver, tier, s, skey, p)]["score"] for s in train_list) / len(train_list)
            for p in FRONTIER_PROXY_NAMES
        ]
        scored_proxy_screen.append((max(p_means), sum(p_means) / len(p_means), bh, st))
    scored_proxy_screen.sort(key=lambda row: (row[0], row[1], len(row[3].rules)))

    shortlist_limit = min(len(scored_proxy_screen), max(4, 3 + max(0, int(n_mutations)) // 3))
    train_shortlist = [(bh, st) for _, _, bh, st in scored_proxy_screen[:shortlist_limit]]
    shortlist_bhashes = {bh for bh, _ in train_shortlist}
    anchor_names = {DEFAULT_STRATEGY.name, TRANSCRIPT_ENSEMBLE_STRATEGY.name}
    for bh, st in active_candidates:
        if st.name in anchor_names and bh not in shortlist_bhashes:
            train_shortlist.append((bh, st))
            shortlist_bhashes.add(bh)
    solver_pairs = [(def_key, def_json)] + [_strategy_key_and_payload(st) for _, st in train_shortlist]
    _ensure_cached_runs(tier, train_list, solver_pairs, (SOLVER_NAME,), workers=workers)

    default_train = evaluate_proxy_ensemble(
        DEFAULT_STRATEGY,
        tier=tier,
        seeds=train_list,
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
        workers=workers,
    )

    train_leaderboard: list[dict[str, Any]] = []
    for bh, st in train_shortlist:
        ev = evaluate_proxy_ensemble(
            st,
            tier=tier,
            seeds=train_list,
            min_solver_acc=min_solver_acc,
            min_solver_ratio=min_solver_ratio,
            workers=workers,
        )
        train_leaderboard.append(
            {
                "behavior_hash": bh,
                "strategy_name": st.name,
                "strategy_json": st.to_json(),
                "feasible": ev["feasible"],
                "worst_case_proxy_regret": ev["worst_case_proxy_regret"],
                "mean_proxy_regret": ev["mean_proxy_regret"],
                "solver_score": ev["solver_score"],
                "solver_acc": ev["solver_acc"],
                "pareto_dominates_default": ev["pareto_dominates_default"],
                "eval": ev,
            }
        )

    train_leaderboard.sort(
        key=lambda row: (
            1 if row["feasible"] else 0,
            row["worst_case_proxy_regret"],
            row["mean_proxy_regret"],
            row["solver_score"],
            -len(row["strategy_json"].get("rules", [])),
        ),
        reverse=True,
    )

    feasible_train = [row for row in train_leaderboard if row["feasible"]]
    holdout_cap = 3 if int(n_mutations) <= 4 else 5
    holdout_pool = feasible_train[:holdout_cap] if feasible_train else train_leaderboard[:2]
    remaining_feasible = feasible_train[holdout_cap:]

    def _collect_holdout_rows(pool_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        if not pool_rows:
            return []
        pool_pairs = [(def_key, def_json)] + [
            _strategy_key_and_payload(_instantiate_strategy(r["strategy_json"]))
            for r in pool_rows
        ]
        _ensure_cached_runs(
            tier,
            holdout_list,
            pool_pairs,
            (SOLVER_NAME, *FRONTIER_PROXY_NAMES),
            workers=workers,
        )
        collected: list[dict[str, Any]] = []
        for r in pool_rows:
            st_obj = _instantiate_strategy(r["strategy_json"])
            hev = evaluate_proxy_ensemble(
                st_obj,
                tier=tier,
                seeds=holdout_list,
                min_solver_acc=min_solver_acc,
                min_solver_ratio=min_solver_ratio,
                workers=workers,
            )
            if not hev["feasible"]:
                continue
            collected.append(
                {
                    "behavior_hash": r["behavior_hash"],
                    "strategy_name": st_obj.name,
                    "strategy_json": st_obj.to_json(),
                    "feasible": True,
                    "train_worst_case_proxy_regret": r["worst_case_proxy_regret"],
                    "holdout_worst_case_proxy_regret": hev["worst_case_proxy_regret"],
                    "worst_case_proxy_regret": hev["worst_case_proxy_regret"],
                    "mean_proxy_regret": hev["mean_proxy_regret"],
                    "worst_case_proxy": hev["worst_case_proxy"],
                    "solver_score": hev["solver_score"],
                    "solver_acc": hev["solver_acc"],
                    "baseline_solver_score": hev["baseline_solver_score"],
                    "pareto_dominates_default": hev["pareto_dominates_default"],
                    "per_proxy": hev["per_proxy"],
                    "train_eval": r["eval"],
                    "holdout_eval": hev,
                }
            )
        return collected

    _ensure_cached_runs(
        tier,
        holdout_list,
        [(def_key, def_json)],
        (SOLVER_NAME, *FRONTIER_PROXY_NAMES),
        workers=workers,
    )
    default_holdout = evaluate_proxy_ensemble(
        DEFAULT_STRATEGY,
        tier=tier,
        seeds=holdout_list,
        min_solver_acc=min_solver_acc,
        min_solver_ratio=min_solver_ratio,
        workers=workers,
    )

    holdout_rows = _collect_holdout_rows(holdout_pool)
    if not holdout_rows and remaining_feasible:
        holdout_rows = _collect_holdout_rows(remaining_feasible)

    holdout_rows.sort(
        key=lambda row: (
            row["worst_case_proxy_regret"],
            row["mean_proxy_regret"],
            row["solver_score"],
            -len(row["strategy_json"].get("rules", [])),
        ),
        reverse=True,
    )
    ranked: list[dict[str, Any]] = [
        {"rank": idx + 1, **row} for idx, row in enumerate(holdout_rows)
    ]
    best = ranked[0] if ranked else None

    return {
        "tier": tier,
        "seed": int(seed),
        "n_mutations": int(n_mutations),
        "min_solver_acc": float(min_solver_acc),
        "min_solver_ratio": float(min_solver_ratio),
        "train_seeds": train_list,
        "holdout_seeds": holdout_list,
        "n_candidates_evaluated": len(train_leaderboard),
        "default_train": default_train,
        "default_holdout": default_holdout,
        "train_leaderboard": train_leaderboard,
        "holdout_leaderboard": ranked,
        "ranked": ranked,
        "hof": ranked,
        "best_holdout": best,
        "best_strategy": best["strategy_json"] if best is not None else None,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Evaluate or search Mole strategies against the multi-cohort frontier proxy ensemble."
    )
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="6400-6419")
    ap.add_argument("--min-solver-acc", type=float, default=0.85)
    ap.add_argument("--min-solver-ratio", type=float, default=0.50)
    ap.add_argument("--strategy", default="ensemble_multicohort_v14")
    ap.add_argument("--search", action="store_true")
    ap.add_argument("--n-mutations", type=int, default=12)
    ap.add_argument("--holdout-seeds", default="6420-6435")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=None)
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    seed_list = parse_seeds(args.seeds)
    if args.search:
        holdout_list = parse_seeds(args.holdout_seeds)
        report = search_ensemble_strategies(
            n_mutations=args.n_mutations,
            seed=args.seed,
            tier=args.tier,
            train_seeds=seed_list,
            holdout_seeds=holdout_list,
            min_solver_acc=args.min_solver_acc,
            min_solver_ratio=args.min_solver_ratio,
            workers=args.workers,
        )
    else:
        report = evaluate_proxy_ensemble(
            args.strategy,
            tier=args.tier,
            seeds=seed_list,
            min_solver_acc=args.min_solver_acc,
            min_solver_ratio=args.min_solver_ratio,
            workers=args.workers,
        )

    serialized = json.dumps(report, indent=2, sort_keys=True)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(serialized + "\n", encoding="utf-8")

    if args.as_json or not args.out:
        print(serialized)
    else:
        print(
            json.dumps(
                {
                    "out": str(args.out),
                    "tier": args.tier,
                    "n_seeds": len(seed_list),
                }
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
