from __future__ import annotations

import argparse
import copy
import gzip
import itertools
import json
import logging
import math
import os
import random
import re
import sys
import threading
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules, world
from canary.baselines import employee_ids
from canary.env import ERRORS, TOPICS, _SPECS, Env
from canary.eval import run_episode
from canary.redteam import anticheat as ac
from canary.redteam import corpus as rt_corpus
from canary.redteam import fuzz
from canary.solver.policy import SolverPolicy
from canary.types import INVESTIGATIVE_TOOLS, LedgerEntry, ToolResult

TARGETS: tuple[str, ...] = ("easy", "medium", "hard", "hard_forge", "hard_rl")
PHASES: tuple[str, ...] = ("day1_start", "pre_canary", "midpoint", "pre_accuse", "post_end")
FUZZ_MODES: tuple[str, ...] = ("random", "malformed", "evolve", "parallel_accuse")
STATEFUL_FAMILIES: tuple[str, ...] = (
    "restrict_toggle_leak_delay",
    "dual_canary_partitions",
    "tool_call_cap_cliff",
    "out_of_order_day_windows",
    "barrier_race_16t_accuse_advance",
)

DETERMINISTIC_SWEEP_SECRET = b"canary-w4-megahunt-deterministic-key-v14"
DEFAULT_SCRATCH_DIR = Path("/tmp/opencode/w4")

FULL_SEED_BANDS: tuple[tuple[str, list[int]], ...] = (
    ("900000-900039", list(range(900000, 900040))),
    ("800000-800099", list(range(800000, 800100))),
)
QUICK_SEED_BANDS: tuple[tuple[str, list[int]], ...] = (
    ("900000", [900000]),
    ("800000", [800000]),
)

FULL_FUZZ_BUDGETS: dict[str, tuple[int, int]] = {
    "easy": (900, 1500),
    "medium": (900, 1500),
    "hard": (900, 1500),
    "hard_forge": (900, 1500),
    "hard_rl": (900, 1500),
}
QUICK_FUZZ_BUDGETS: dict[str, tuple[int, int]] = {
    "easy": (3, 3),
    "medium": (3, 3),
    "hard": (3, 3),
    "hard_forge": (3, 3),
    "hard_rl": (3, 3),
}

EMP_ID_RE = re.compile(r"^e\d{2,}$")
_STANDARD_STATUS_KEYS = frozenset({"day", "V", "actions_left_today", "tool_calls_left", "restricted", "canaries_planted"})


def _default_env_factory(tier: str, seed: int) -> Any:
    return Env(tier=tier, seed=seed)


def _counting_factory(
    base_factory: Callable[[str, int], Any],
) -> tuple[Callable[[str, int], Any], Callable[[], tuple[int, int]]]:
    ep_counter = itertools.count(0)
    call_counter = itertools.count(0)

    def factory(tier: str, seed: int) -> Any:
        env = base_factory(tier, seed)
        next(ep_counter)
        orig_call = env.call

        def wrapped_call(tool: str, args: Any) -> ToolResult:
            next(call_counter)
            return orig_call(tool, args)

        env.call = wrapped_call
        return env

    def read_counts() -> tuple[int, int]:
        return next(ep_counter), next(call_counter)

    return factory, read_counts


def _expected_known_v(env: Any) -> float:
    if not rules.KNOWN_V_MODE:
        return round(float(env.V), 10)
    surfaced = sum(1 for f in env._feed if f["surfaced_day"] <= env.day)
    return round(max(0.0, 1.0 - env.p.leak_damage * surfaced - env._costs), 10)


class AuditedEnvRunner:
    def __init__(self, env: Any, family: str, check_internals: bool = True):
        self.env = env
        self.family = family
        self.check_internals = check_internals
        self.mole = fuzz.true_mole(env)
        self.violations: list[dict[str, Any]] = []
        self.calls = 0
        self.error_detail_checked = 0
        self.prev_true_v = float(getattr(env, "V", 1.0))
        self.prev_vis_v = float(env.visible_V()) if hasattr(env, "visible_V") else self.prev_true_v

    def call(self, tool: Any, args: Any) -> ToolResult:
        env = self.env
        before_done = bool(env.done)
        before_score = float(env.score())
        before_ledger_len = len(env.ledger())
        before_v = float(getattr(env, "V", 0.0))
        before_vis_v = float(env.visible_V()) if hasattr(env, "visible_V") else before_v
        before_costs = float(getattr(env, "_costs", 0.0))
        before_actions = int(getattr(env, "_actions_today", 0))
        before_canaries = int(getattr(env, "_canaries_today", 0))
        before_restricted = set(getattr(env, "_restricted", set()))
        before_docs_len = len(getattr(env, "docs", ()))

        try:
            res = env.call(tool, args)
        except Exception as ex:
            self.violations.append({
                "kind": "exception",
                "family": self.family,
                "t": self.calls,
                "tool": repr(tool),
                "error": f"{type(ex).__name__}: {ex}",
                "tb": traceback.format_exc(limit=3),
            })
            return ToolResult(False, {}, "exception")

        self.calls += 1
        if not (
            tool == "status"
            and res.ok
            and res.error is None
            and isinstance(res.data, dict)
            and set(res.data) == _STANDARD_STATUS_KEYS
        ):
            out_text = fuzz._jsonable(res.data) + fuzz._jsonable(res.error)
            low_text = out_text.lower()
            if ("mole" in low_text or "correct" in low_text or "culprit" in low_text) and fuzz._mole_named(out_text, self.mole):
                self.violations.append({
                    "kind": "truth_leak",
                    "family": self.family,
                    "t": self.calls,
                    "tool": repr(tool),
                    "out": out_text[:300],
                })

        if not res.ok and res.error not in ERRORS:
            self.violations.append({
                "kind": "unexpected_error_string",
                "family": self.family,
                "t": self.calls,
                "tool": repr(tool),
                "error": res.error,
            })

        if not before_done and not res.ok and res.error == "invalid arguments" and self.check_internals and hasattr(env, "_feed"):
            det = res.data.get("detail") if isinstance(res.data, dict) else None
            if not (isinstance(res.data, dict) and set(res.data) == {"detail"} and isinstance(det, str) and bool(det.strip())):
                self.violations.append({
                    "kind": "missing_or_malformed_error_detail",
                    "family": self.family,
                    "t": self.calls,
                    "tool": repr(tool),
                })
            else:
                self.error_detail_checked += 1
                if fuzz._mole_named(det, self.mole) and not fuzz._mole_named(fuzz._jsonable(args), self.mole):
                    self.violations.append({
                        "kind": "error_detail_unprompted_mole_id",
                        "family": self.family,
                        "t": self.calls,
                        "tool": repr(tool),
                        "detail": det[:200],
                    })
                if hasattr(env, "_world") and hasattr(env._world, "world_seed") and str(env._world.world_seed) in det:
                    self.violations.append({
                        "kind": "error_detail_world_seed_leak",
                        "family": self.family,
                        "t": self.calls,
                        "tool": repr(tool),
                    })

        after_v = float(getattr(env, "V", 0.0))
        if after_v < -1e-12 or after_v > 1.0 + 1e-12 or after_v > self.prev_true_v + 1e-12:
            self.violations.append({
                "kind": "true_v_monotonicity",
                "family": self.family,
                "t": self.calls,
                "prev_v": self.prev_true_v,
                "after_v": after_v,
            })
        self.prev_true_v = after_v

        if self.check_internals and hasattr(env, "visible_V") and hasattr(env, "_feed"):
            after_vis_v = float(env.visible_V())
            if after_vis_v < -1e-12 or after_vis_v > 1.0 + 1e-12 or after_vis_v > self.prev_vis_v + 1e-12:
                self.violations.append({
                    "kind": "visible_v_monotonicity",
                    "family": self.family,
                    "t": self.calls,
                    "prev_vis_v": self.prev_vis_v,
                    "after_vis_v": after_vis_v,
                })
            self.prev_vis_v = after_vis_v
            exp_kv = _expected_known_v(env)
            if abs(after_vis_v - exp_kv) > 1e-9:
                self.violations.append({
                    "kind": "known_v_formula_mismatch",
                    "family": self.family,
                    "t": self.calls,
                    "got": after_vis_v,
                    "expected": exp_kv,
                })
            if rules.KNOWN_V_MODE and any(f["surfaced_day"] > env.day for f in env._feed):
                if not (after_vis_v > round(after_v, 10) or after_vis_v == 0.0):
                    self.violations.append({
                        "kind": "unsurfaced_leak_exposed",
                        "family": self.family,
                        "t": self.calls,
                        "visible_v": after_vis_v,
                        "true_v": after_v,
                    })

        if before_done:
            if res.ok or res.error != "episode over" or float(env.score()) != before_score or len(env.ledger()) != before_ledger_len or after_v != before_v:
                self.violations.append({
                    "kind": "post_end_effect",
                    "family": self.family,
                    "t": self.calls,
                    "tool": repr(tool),
                })
        elif not res.ok and self.check_internals and hasattr(env, "_actions_today"):
            if (
                after_v != before_v
                or after_vis_v != before_vis_v
                or float(env._costs) != before_costs
                or int(env._actions_today) != before_actions
                or int(env._canaries_today) != before_canaries
                or set(env._restricted) != before_restricted
                or len(env.docs) != before_docs_len
            ):
                self.violations.append({
                    "kind": "failed_call_state_mutation",
                    "family": self.family,
                    "t": self.calls,
                    "tool": repr(tool),
                })

        return res

    def finalize(self, emps: set[str]) -> list[dict[str, Any]]:
        acc = fuzz._accusations(self.env.ledger(), emps | {self.mole})
        for sv in fuzz.score_invariants(float(self.env.score()), acc, self.mole):
            self.violations.append({**sv, "family": self.family})
        return self.violations


def _run_restrict_toggle_leak_delay(
    tier: str,
    seed: int,
    rng: random.Random,
    factory: Callable[[str, int], Any],
    max_days: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    env = factory(tier, seed)
    aud = AuditedEnvRunner(env, "restrict_toggle_leak_delay", check_internals=hasattr(env, "_feed"))
    le = aud.call("list_employees", {})
    emps = employee_ids({"ok": True, "data": le.data}) if le.ok else [f"e{i:02d}" for i in range(12)]
    p = getattr(env, "p", rules.tier_params(tier))
    horizon = p.n_days if max_days is None else min(p.n_days, max_days)

    for d in range(1, horizon + 1):
        if env.done:
            break
        picks = rng.sample(emps, min(4, len(emps)))
        asg = {picks[0]: "A", picks[1]: "B", picks[2]: "C"}
        c_res = aud.call("plant_canary", {"doc_title": f"DelayProbe-{d}", "assignment": asg})
        if c_res.ok:
            r1 = aud.call("restrict_access", {"employee": picks[0]})
            if r1.ok:
                r_dup = aud.call("restrict_access", {"employee": picks[0]})
                if r_dup.ok:
                    aud.violations.append({"kind": "double_restrict_accepted", "family": aud.family, "day": d})
                bad_c = aud.call("plant_canary", {"doc_title": f"RestrictedCanary-{d}", "assignment": {picks[0]: "A", picks[3]: "B"}})
                if bad_c.ok:
                    aud.violations.append({"kind": "restricted_recipient_canary_accepted", "family": aud.family, "day": d})

        aud.call("status", {})
        aud.call("check_leak_feed", {})
        aud.call("list_documents", {"day_from": 1, "day_to": d})

        if d % 2 == 0:
            st = aud.call("status", {})
            cur_rest = list((st.data or {}).get("restricted") or []) if st.ok else []
            if cur_rest:
                target_u = cur_rest[0]
                u1 = aud.call("unrestrict_access", {"employee": target_u})
                if u1.ok:
                    u_dup = aud.call("unrestrict_access", {"employee": target_u})
                    if u_dup.ok:
                        aud.violations.append({"kind": "double_unrestrict_accepted", "family": aud.family, "day": d})
            else:
                u_bad = aud.call("unrestrict_access", {"employee": picks[-1]})
                if u_bad.ok:
                    aud.violations.append({"kind": "unrestrict_unrestricted_accepted", "family": aud.family, "day": d})

        if d == horizon and (seed % 2 == 0 or max_days is not None) and not env.done:
            aud.call("accuse", {"employee": rng.choice(emps)})
        elif not env.done:
            aud.call("advance_day", {})

    aud.call("status", {})
    aud.call("accuse", {"employee": emps[0]})
    return aud.calls, aud.finalize(set(emps))


def _run_dual_canary_partitions(
    tier: str,
    seed: int,
    rng: random.Random,
    factory: Callable[[str, int], Any],
    max_days: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    env = factory(tier, seed)
    aud = AuditedEnvRunner(env, "dual_canary_partitions", check_internals=hasattr(env, "_feed"))
    le = aud.call("list_employees", {})
    emps = employee_ids({"ok": True, "data": le.data}) if le.ok else [f"e{i:02d}" for i in range(12)]
    p = getattr(env, "p", rules.tier_params(tier))
    horizon = p.n_days if max_days is None else min(p.n_days, max_days)

    for d in range(1, horizon + 1):
        if env.done:
            break
        picks = rng.sample(emps, min(6, len(emps)))
        singleton_asg = {picks[0]: "S1"}
        c1 = aud.call("plant_canary", {"doc_title": f"Singleton-{d}", "assignment": singleton_asg})
        if not c1.ok and hasattr(env, "_feed"):
            aud.violations.append({"kind": "valid_singleton_canary_rejected", "family": aud.family, "day": d})

        overlap_asg = {picks[0]: "V1", picks[1]: "V2", picks[2]: "V3", picks[3]: "V1"}
        c2 = aud.call("plant_canary", {"doc_title": f"Overlap-{d}", "assignment": overlap_asg})
        if p.canaries_per_day >= 2:
            if not c2.ok and hasattr(env, "_feed"):
                aud.violations.append({"kind": "second_canary_wrongly_rejected", "family": aud.family, "day": d})
            c3 = aud.call("plant_canary", {"doc_title": f"OverCap-{d}", "assignment": {picks[4]: "A"}})
            if c3.ok:
                aud.violations.append({"kind": "third_canary_accepted", "family": aud.family, "day": d})
        else:
            if c2.ok:
                aud.violations.append({"kind": "second_canary_accepted_on_single_cap_tier", "family": aud.family, "day": d})

        four_var = {picks[0]: "A", picks[1]: "B", picks[2]: "C", picks[3]: "D"}
        c4 = aud.call("plant_canary", {"doc_title": f"FourVar-{d}", "assignment": four_var})
        if c4.ok:
            aud.violations.append({"kind": "exceeds_max_variants_accepted", "family": aud.family, "day": d})

        ld = aud.call("list_documents", {"day_from": d, "day_to": d})
        feed = aud.call("check_leak_feed", {})
        if ld.ok and feed.ok and hasattr(env, "_doc_by_id"):
            for item in (feed.data or {}).get("items") or ():
                did = item.get("doc_id")
                doc = env._doc_by_id.get(did)
                if doc and doc.get("is_canary"):
                    var = item.get("variant")
                    if var not in (doc.get("variants") or {}):
                        aud.violations.append({"kind": "invalid_leaked_canary_variant", "family": aud.family, "doc_id": did, "variant": var})

        if d == horizon and (seed % 2 == 1 or max_days is not None) and not env.done:
            aud.call("accuse", {"employee": rng.choice(emps)})
        elif not env.done:
            aud.call("advance_day", {})

    aud.call("plant_canary", {"doc_title": "PostEnd", "assignment": {emps[0]: "A"}})
    return aud.calls, aud.finalize(set(emps))


def _run_tool_call_cap_cliff(
    tier: str,
    seed: int,
    rng: random.Random,
    factory: Callable[[str, int], Any],
    quick: bool = False,
) -> tuple[int, int, list[dict[str, Any]]]:
    total_calls = 0
    ep_count = 0
    all_viol: list[dict[str, Any]] = []
    p = rules.tier_params(tier)
    cap = p.tool_call_cap

    env_a = factory(tier, seed)
    ep_count += 1
    aud_a = AuditedEnvRunner(env_a, "tool_call_cap_cliff_accuse", check_internals=hasattr(env_a, "_feed"))
    le_a = aud_a.call("list_employees", {})
    emps_a = employee_ids({"ok": True, "data": le_a.data}) if le_a.ok else [f"e{i:02d}" for i in range(p.n_employees)]
    while aud_a.calls < cap - 1 and not env_a.done:
        rem = (cap - 1) - aud_a.calls
        if rem > 2 and env_a.day < p.n_days and aud_a.calls % 19 == 0:
            aud_a.call("advance_day", {})
        elif aud_a.calls % 5 == 0:
            aud_a.call("list_documents", {"day_from": 1, "day_to": env_a.day})
        elif aud_a.calls % 7 == 0 and getattr(env_a, "_actions_today", 0) < p.actions_per_day:
            aud_a.call("check_leak_feed", {})
        else:
            aud_a.call("status", {})

    if hasattr(env_a, "_feed") and not env_a.done and aud_a.calls == cap - 1:
        acc_target = emps_a[seed % len(emps_a)]
        r_acc = aud_a.call("accuse", {"employee": acc_target})
        if not r_acc.ok or not env_a.done:
            aud_a.violations.append({"kind": "cliff_accuse_failed_at_cap", "family": aud_a.family, "seed": seed})
        if hasattr(env_a, "verdict") and env_a.verdict().get("end_reason") != "accused":
            aud_a.violations.append({
                "kind": "cliff_accuse_overwritten_by_tool_cap",
                "family": aud_a.family,
                "end_reason": env_a.verdict().get("end_reason"),
            })
        r_post = aud_a.call("status", {})
        if r_post.ok:
            aud_a.violations.append({"kind": "post_cliff_call_succeeded", "family": aud_a.family})
    total_calls += aud_a.calls
    all_viol.extend(aud_a.finalize(set(emps_a)))

    if quick:
        return ep_count, total_calls, all_viol

    env_b = factory(tier, seed)
    ep_count += 1
    aud_b = AuditedEnvRunner(env_b, "tool_call_cap_cliff_exhaust", check_internals=hasattr(env_b, "_feed"))
    le_b = aud_b.call("list_employees", {})
    emps_b = employee_ids({"ok": True, "data": le_b.data}) if le_b.ok else emps_a
    while aud_b.calls < cap and not env_b.done:
        if env_b.day < p.n_days and aud_b.calls % 23 == 0:
            aud_b.call("advance_day", {})
        elif aud_b.calls % 3 == 0:
            aud_b.call("list_documents", {})
        else:
            aud_b.call("status", {})

    if hasattr(env_b, "_feed"):
        if not env_b.done or env_b.score() != 0.0:
            aud_b.violations.append({
                "kind": "cap_exhaust_not_zero_done",
                "family": aud_b.family,
                "done": env_b.done,
                "score": env_b.score(),
            })
        if hasattr(env_b, "verdict") and env_b.verdict().get("end_reason") != "tool_cap":
            aud_b.violations.append({
                "kind": "cap_exhaust_wrong_end_reason",
                "family": aud_b.family,
                "end_reason": env_b.verdict().get("end_reason"),
            })
        r_late = aud_b.call("accuse", {"employee": aud_b.mole})
        if r_late.ok or env_b.score() != 0.0:
            aud_b.violations.append({"kind": "post_cap_mole_accuse_scored", "family": aud_b.family, "score": env_b.score()})
    total_calls += aud_b.calls
    all_viol.extend(aud_b.finalize(set(emps_b)))

    env_c = factory(tier, seed)
    ep_count += 1
    aud_c = AuditedEnvRunner(env_c, "tool_call_cap_invalid_burn", check_internals=hasattr(env_c, "_feed"))
    bad_cycle = (
        ("unknown_foreign_tool", {"x": 1}),
        ("search_messages", {"query": "   "}),
        ("read_access_logs", {"day_from": 5, "day_to": 2}),
        ("plant_canary", {"doc_title": "", "assignment": {}}),
        ("accuse", {"employee": "*"}),
        ("interview", {"employee": "e00", "topic": "invalid_topic"}),
    )
    while aud_c.calls < cap and not env_c.done:
        bt, ba = bad_cycle[aud_c.calls % len(bad_cycle)]
        r_bad = aud_c.call(bt, ba)
        if r_bad.ok:
            aud_c.violations.append({"kind": "invalid_burn_call_accepted", "family": aud_c.family, "tool": bt})
    if hasattr(env_c, "_feed"):
        if not env_c.done or env_c.score() != 0.0:
            aud_c.violations.append({
                "kind": "invalid_burn_did_not_enforce_cap",
                "family": aud_c.family,
                "done": env_c.done,
                "score": env_c.score(),
            })
        aud_c.call("accuse", {"employee": aud_c.mole})
    total_calls += aud_c.calls
    all_viol.extend(aud_c.finalize(set(emps_a)))

    env_d = factory(tier, seed)
    ep_count += 1
    aud_d = AuditedEnvRunner(env_d, "tool_call_cap_countdown_zero", check_internals=hasattr(env_d, "_feed"))
    le_d = aud_d.call("list_employees", {})
    emps_d = employee_ids({"ok": True, "data": le_d.data}) if le_d.ok else emps_a
    while aud_d.calls < cap - 2 and not env_d.done:
        if env_d.day < p.n_days and aud_d.calls % 21 == 0:
            aud_d.call("advance_day", {})
        elif aud_d.calls % 11 == 0 and getattr(env_d, "_actions_today", 0) < p.actions_per_day:
            aud_d.call("interview", {"employee": emps_d[aud_d.calls % len(emps_d)], "topic": "workload"})
        else:
            aud_d.call("status", {})

    if hasattr(env_d, "_feed") and not env_d.done and aud_d.calls == cap - 2:
        st_penult = aud_d.call("status", {})
        if not st_penult.ok or (st_penult.data or {}).get("tool_calls_left") != 1 or env_d.done:
            aud_d.violations.append({
                "kind": "penultimate_tool_calls_left_mismatch",
                "family": aud_d.family,
                "got": (st_penult.data or {}).get("tool_calls_left"),
            })
        st_final = aud_d.call("status", {})
        if not st_final.ok or (st_final.data or {}).get("tool_calls_left") != 0 or not env_d.done:
            aud_d.violations.append({
                "kind": "final_tool_calls_left_mismatch",
                "family": aud_d.family,
                "got": (st_final.data or {}).get("tool_calls_left"),
                "done": env_d.done,
            })
        aud_d.call("status", {})
    total_calls += aud_d.calls
    all_viol.extend(aud_d.finalize(set(emps_d)))

    return ep_count, total_calls, all_viol


def _run_out_of_order_day_windows(
    tier: str,
    seed: int,
    rng: random.Random,
    factory: Callable[[str, int], Any],
    max_days: int | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    env = factory(tier, seed)
    aud = AuditedEnvRunner(env, "out_of_order_day_windows", check_internals=hasattr(env, "_feed"))
    le = aud.call("list_employees", {})
    emps = employee_ids({"ok": True, "data": le.data}) if le.ok else [f"e{i:02d}" for i in range(12)]
    p = getattr(env, "p", rules.tier_params(tier))
    horizon = p.n_days if max_days is None else min(p.n_days, max_days)

    for d in range(1, horizon + 1):
        if env.done:
            break
        inv_hi = min(p.n_days, d + 2)
        inv_lo = max(1, d - 1)
        if inv_hi > inv_lo:
            for tname, extra in (
                ("list_documents", {}),
                ("read_access_logs", {}),
                ("search_messages", {"query": "project"}),
            ):
                r_inv = aud.call(tname, {"day_from": inv_hi, "day_to": inv_lo, **extra})
                if r_inv.ok:
                    aud.violations.append({"kind": "inverted_day_window_accepted", "family": aud.family, "tool": tname, "day": d})

        for bad_day in (0, -1, p.n_days + 1, True):
            r_oob = aud.call("read_access_logs", {"day_from": bad_day, "day_to": d})
            if r_oob.ok:
                aud.violations.append({"kind": "oob_day_accepted", "family": aud.family, "bad_day": repr(bad_day)})

        if d < p.n_days and hasattr(env, "_feed"):
            r_fdoc = aud.call("list_documents", {"day_from": d + 1, "day_to": p.n_days})
            if r_fdoc.ok and (r_fdoc.data or {}).get("documents"):
                aud.violations.append({"kind": "future_documents_leaked", "family": aud.family, "day": d})

            r_flog = aud.call("read_access_logs", {"day_from": d, "day_to": p.n_days})
            if r_flog.ok and (r_flog.data or {}).get("logs"):
                aud.violations.append({"kind": "unclosed_day_logs_leaked", "family": aud.family, "day": d})

            r_fmsg = aud.call("search_messages", {"query": "a", "day_from": d, "day_to": p.n_days})
            if r_fmsg.ok and (r_fmsg.data or {}).get("messages"):
                aud.violations.append({"kind": "unclosed_day_messages_leaked", "family": aud.family, "day": d})

        if d > 1:
            aud.call("read_access_logs", {"day_from": 1, "day_to": d - 1, "employee": emps[d % len(emps)]})
            aud.call("search_messages", {"query": "memo", "day_from": 1, "day_to": d - 1})

        if d < horizon:
            aud.call("advance_day", {})
        else:
            aud.call("accuse", {"employee": emps[seed % len(emps)]})

    return aud.calls, aud.finalize(set(emps))


def _run_barrier_race_16t_accuse_advance(
    tier: str,
    seed: int,
    factory: Callable[[str, int], Any],
) -> tuple[int, list[dict[str, Any]]]:
    total_calls = 0
    viol: list[dict[str, Any]] = []
    p = rules.tier_params(tier)

    for race_tag, target_day in (("mid_horizon", min(3, p.n_days)), ("final_horizon", p.n_days)):
        env = factory(tier, seed)
        mole = fuzz.true_mole(env)
        le = env.call("list_employees", {})
        total_calls += 1
        emps = employee_ids({"ok": True, "data": le.data}) if le.ok else [f"e{i:02d}" for i in range(12)]
        while env.day < target_day and not env.done:
            env.call("advance_day", {})
            total_calls += 1

        n_threads = 16
        barrier = threading.Barrier(n_threads)
        lock = threading.Lock()
        acc_oks: list[bool] = []
        adv_oks: list[bool] = []
        race_excs: list[str] = []

        def worker_fn(idx: int) -> None:
            try:
                barrier.wait(timeout=10.0)
                if idx < 8:
                    emp = emps[idx % len(emps)]
                    r = env.call("accuse", {"employee": emp})
                    with lock:
                        acc_oks.append(bool(r.ok))
                else:
                    r = env.call("advance_day", {})
                    with lock:
                        adv_oks.append(bool(r.ok))
            except Exception as ex:
                with lock:
                    race_excs.append(f"{type(ex).__name__}: {ex}")

        threads = [threading.Thread(target=worker_fn, args=(i,)) for i in range(n_threads)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        total_calls += n_threads

        if race_excs:
            viol.append({"kind": "barrier_16t_exception", "race": race_tag, "seed": seed, "errors": race_excs[:3]})
        acc_led = fuzz._accusations(env.ledger(), set(emps) | {mole})
        if len(acc_led) > 1 or sum(acc_oks) > 1 or sum(acc_oks) != len(acc_led):
            viol.append({
                "kind": "barrier_16t_accuse_race",
                "race": race_tag,
                "seed": seed,
                "acc_ok_count": sum(acc_oks),
                "ledger_accusations": acc_led,
            })
        if hasattr(env, "verdict") and env.done:
            verd = env.verdict()
            if len(acc_led) == 1 and verd.get("end_reason") != "accused":
                viol.append({
                    "kind": "barrier_16t_end_reason_mismatch",
                    "race": race_tag,
                    "seed": seed,
                    "acc": acc_led,
                    "end_reason": verd.get("end_reason"),
                })
            if len(acc_led) == 0 and verd.get("end_reason") == "accused":
                viol.append({"kind": "barrier_16t_accused_without_ledger", "race": race_tag, "seed": seed})
        for sv in fuzz.score_invariants(float(env.score()), acc_led, mole):
            viol.append({**sv, "race": race_tag, "seed": seed})

    return total_calls, viol


@dataclass
class _MockWorld:
    mole: str


class PlantedBugEnv:
    def __init__(self, tier: str, seed: int):
        self._emps = [f"e{i:02d}" for i in range(12)]
        self._world = _MockWorld(mole=self._emps[seed % len(self._emps)])
        self.p = rules.tier_params(tier if tier in rules.TIERS or tier in rules.TRACKS else "hard")
        self.day = 1
        self.V = 1.0
        self._done = False
        self._score = 0.0
        self._ledger: list[LedgerEntry] = []

    @property
    def done(self) -> bool:
        return self._done

    def score(self) -> float:
        return self._score

    def visible_V(self) -> float:
        return self.V

    def ledger(self) -> list[LedgerEntry]:
        return list(self._ledger)

    def verdict(self) -> dict[str, Any]:
        acc = [e.detail.get("employee") for e in self._ledger if e.event == "accused"]
        return {
            "done": self._done,
            "end_reason": "accused" if acc else ("horizon" if self._done else None),
            "accused": acc[-1] if acc else None,
            "correct": bool(acc and acc[-1] == self._world.mole),
            "final_day": self.day,
            "V": self.V,
            "score": self._score,
        }

    def call(self, tool: str, args: Any) -> ToolResult:
        if not isinstance(args, dict):
            return ToolResult(False, {}, "invalid arguments")
        if tool == "list_employees":
            return ToolResult(True, {"employees": [{"id": e} for e in self._emps]})
        if tool == "status":
            self.V = min(1.05, self.V + 0.02)
            return ToolResult(True, {"day": self.day, "V": self.V, "mole": self._world.mole})
        if tool == "advance_day":
            self.day += 1
            if self.day > self.p.n_days:
                self._done = True
            return ToolResult(True, {"day": self.day})
        if tool == "accuse":
            emp = args.get("employee")
            if emp not in self._emps:
                return ToolResult(False, {}, "invalid arguments")
            time.sleep(0.0005)
            self._ledger.append(LedgerEntry(len(self._ledger), self.day, "accused", {"employee": emp}))
            self._done = True
            self._score = 1.0
            return ToolResult(True, {"accused": emp, "episode_over": True})
        return ToolResult(False, {}, "unknown tool")


def run_planted_bug_positive_control() -> dict[str, Any]:
    fuzz_res = fuzz.hunt(
        tier="hard",
        seeds=[900000, 900001],
        budget=18,
        seed=0,
        mode="all",
        workers=1,
        factory=PlantedBugEnv,
    )
    rng = random.Random(7)
    _, s_viol = _run_restrict_toggle_leak_delay("hard", 900000, rng, PlantedBugEnv)
    _, r_viol = _run_barrier_race_16t_accuse_advance("hard", 900000, PlantedBugEnv)
    kinds = sorted({v["kind"] for v in fuzz_res["invariant_violations"]} | {v["kind"] for v in s_viol} | {v["kind"] for v in r_viol})
    detected = bool(
        {"truth_leak", "true_v_monotonicity", "post_end_effect"} <= set(kinds)
        and ({"parallel_accuse_race", "barrier_16t_accuse_race"} & set(kinds))
    )
    return {
        "detected": detected,
        "fuzz_violations": len(fuzz_res["invariant_violations"]),
        "stateful_violations": len(s_viol),
        "race_16t_violations": len(r_viol),
        "violation_kinds": kinds,
    }


def run_megahunt(
    quick: bool = False,
    rng_seed: int = 0,
    targets: tuple[str, ...] = TARGETS,
    fuzz_budget_overrides: dict[str, tuple[int, int]] | None = None,
    factory: Callable[[str, int], Any] = _default_env_factory,
) -> dict[str, Any]:
    t0 = time.time()
    seed_bands = QUICK_SEED_BANDS if quick else FULL_SEED_BANDS
    base_budgets = QUICK_FUZZ_BUDGETS if quick else FULL_FUZZ_BUDGETS
    overrides = fuzz_budget_overrides or {}

    per_target: dict[str, Any] = {}
    total_episodes = 0
    total_env_calls = 0
    total_fuzz_calls = 0
    total_stateful_calls = 0
    total_violations = 0
    all_violation_kinds: set[str] = set()
    overall_best_non_solver = 0.0
    overall_best_spc = 0.0

    for idx_t, target in enumerate(targets):
        tt0 = time.time()
        band_budgets = overrides.get(target, base_budgets[target])
        target_eps = 0
        target_fuzz_calls = 0
        target_stateful_calls = 0
        target_violations: list[dict[str, Any]] = []
        target_best_non_solver = 0.0
        target_best_spc = 0.0
        per_band: dict[str, Any] = {}
        mode_totals: dict[str, dict[str, Any]] = {
            m: {"budget": 0, "races": 0, "best_non_solver_score": 0.0, "best_score_per_call": 0.0, "n_violations": 0}
            for m in FUZZ_MODES
        }
        family_totals: dict[str, dict[str, int]] = {
            fam: {"episodes": 0, "env_calls": 0, "violations": 0}
            for fam in STATEFUL_FAMILIES
        }

        for idx_b, ((band_label, band_seeds), b_budget) in enumerate(zip(seed_bands, band_budgets)):
            run_rng = rng_seed + idx_t * 100 + idx_b
            if quick and idx_b == 1:
                f_eps, f_calls, f_viol = 0, 0, []
            else:
                cfac, read_counts = _counting_factory(factory)
                f_res = fuzz.hunt(
                    tier=target,
                    seeds=band_seeds,
                    budget=b_budget,
                    seed=run_rng,
                    mode="all",
                    workers=1,
                    factory=cfac,
                )
                f_eps, f_calls = read_counts()
                f_viol = list(f_res["invariant_violations"])
                target_eps += f_eps
                target_fuzz_calls += f_calls
                target_violations.extend(f_viol)
                target_best_non_solver = max(target_best_non_solver, float(f_res["best_non_solver_score"]))
                target_best_spc = max(target_best_spc, float(f_res["best_score_per_call"]))

                for m_name, m_data in f_res["per_mode"].items():
                    mt = mode_totals[m_name]
                    mt["budget"] += int(m_data.get("budget", 0))
                    mt["races"] += int(m_data.get("races", 0))
                    mt["best_non_solver_score"] = max(mt["best_non_solver_score"], float(m_data["best_non_solver_score"]))
                    mt["best_score_per_call"] = max(mt["best_score_per_call"], float(m_data["best_score_per_call"]))
                    mt["n_violations"] += int(m_data["n_violations"])

            band_stateful_eps = 0
            band_stateful_calls = 0
            band_stateful_viol = 0
            rng = random.Random(run_rng ^ 0xA5A5)

            q_days = 4 if quick else None
            for s in band_seeds:
                if quick and idx_b == 1:
                    c1, v1 = _run_restrict_toggle_leak_delay(target, s, rng, factory, max_days=q_days)
                    family_totals["restrict_toggle_leak_delay"]["episodes"] += 1
                    family_totals["restrict_toggle_leak_delay"]["env_calls"] += c1
                    family_totals["restrict_toggle_leak_delay"]["violations"] += len(v1)
                    band_stateful_eps += 1
                    band_stateful_calls += c1
                    band_stateful_viol += len(v1)
                    target_violations.extend(v1)
                    continue

                c1, v1 = _run_restrict_toggle_leak_delay(target, s, rng, factory, max_days=q_days)
                family_totals["restrict_toggle_leak_delay"]["episodes"] += 1
                family_totals["restrict_toggle_leak_delay"]["env_calls"] += c1
                family_totals["restrict_toggle_leak_delay"]["violations"] += len(v1)

                c2, v2 = _run_dual_canary_partitions(target, s, rng, factory, max_days=q_days)
                family_totals["dual_canary_partitions"]["episodes"] += 1
                family_totals["dual_canary_partitions"]["env_calls"] += c2
                family_totals["dual_canary_partitions"]["violations"] += len(v2)

                ep3, c3, v3 = _run_tool_call_cap_cliff(target, s, rng, factory, quick=quick)
                family_totals["tool_call_cap_cliff"]["episodes"] += ep3
                family_totals["tool_call_cap_cliff"]["env_calls"] += c3
                family_totals["tool_call_cap_cliff"]["violations"] += len(v3)

                c4, v4 = _run_out_of_order_day_windows(target, s, rng, factory, max_days=q_days)
                family_totals["out_of_order_day_windows"]["episodes"] += 1
                family_totals["out_of_order_day_windows"]["env_calls"] += c4
                family_totals["out_of_order_day_windows"]["violations"] += len(v4)

                c5, v5 = _run_barrier_race_16t_accuse_advance(target, s, factory)
                family_totals["barrier_race_16t_accuse_advance"]["episodes"] += 2
                family_totals["barrier_race_16t_accuse_advance"]["env_calls"] += c5
                family_totals["barrier_race_16t_accuse_advance"]["violations"] += len(v5)

                s_calls = c1 + c2 + c3 + c4 + c5
                s_viols = v1 + v2 + v3 + v4 + v5
                band_stateful_eps += 5 + ep3
                band_stateful_calls += s_calls
                band_stateful_viol += len(s_viols)
                target_violations.extend(s_viols)

            target_eps += band_stateful_eps
            target_stateful_calls += band_stateful_calls
            per_band[band_label] = {
                "n_seeds": len(band_seeds),
                "fuzz_budget": b_budget,
                "fuzz_episodes": f_eps,
                "fuzz_env_calls": f_calls,
                "stateful_episodes": band_stateful_eps,
                "stateful_env_calls": band_stateful_calls,
                "total_episodes": f_eps + band_stateful_eps,
                "total_env_calls": f_calls + band_stateful_calls,
                "violations": len(f_viol) + band_stateful_viol,
            }

        v_kinds = sorted({v["kind"] for v in target_violations})
        all_violation_kinds.update(v_kinds)
        t_calls = target_fuzz_calls + target_stateful_calls
        p = rules.tier_params(target)
        per_target[target] = {
            "tier": target,
            "params": {
                "n_employees": p.n_employees,
                "n_days": p.n_days,
                "canaries_per_day": p.canaries_per_day,
                "max_variants": p.max_variants,
                "tool_call_cap": p.tool_call_cap,
                "fingerprint_accuracy": p.fingerprint_accuracy,
            },
            "episodes": target_eps,
            "fuzz_env_calls": target_fuzz_calls,
            "stateful_env_calls": target_stateful_calls,
            "total_env_calls": t_calls,
            "best_non_solver_score": target_best_non_solver,
            "best_score_per_call": round(target_best_spc, 6),
            "violations_count": len(target_violations),
            "violation_kinds": v_kinds,
            "per_mode": mode_totals,
            "per_stateful_family": family_totals,
            "per_band": per_band,
            "elapsed_s": round(time.time() - tt0, 2),
        }
        total_episodes += target_eps
        total_fuzz_calls += target_fuzz_calls
        total_stateful_calls += target_stateful_calls
        total_env_calls += t_calls
        total_violations += len(target_violations)
        overall_best_non_solver = max(overall_best_non_solver, target_best_non_solver)
        overall_best_spc = max(overall_best_spc, target_best_spc)

    positive_control = run_planted_bug_positive_control()
    return {
        "quick": quick,
        "seed_bands": [lbl for lbl, _ in seed_bands],
        "targets": list(targets),
        "total_episodes": total_episodes,
        "fuzz_env_calls": total_fuzz_calls,
        "stateful_env_calls": total_stateful_calls,
        "total_env_calls": total_env_calls,
        "best_non_solver_score": overall_best_non_solver,
        "best_score_per_call": round(overall_best_spc, 6),
        "total_violations": total_violations,
        "violation_kinds": sorted(all_violation_kinds),
        "positive_control": positive_control,
        "per_target": per_target,
        "elapsed_s": round(time.time() - t0, 2),
    }


def classify_unconditional_invalid(tool: Any, args: Any) -> tuple[bool, str]:
    if not isinstance(tool, str) or tool not in _SPECS:
        return True, "foreign_or_unknown_tool"
    if not isinstance(args, dict):
        return True, "non_dict_args"
    _, props, req = _SPECS[tool]
    if any(k not in props for k in args) or any(k not in args for k in req):
        return True, "schema_keys"
    for k, v in args.items():
        typ = props[k].get("type")
        if typ == "integer" and (not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > 21):
            return True, "int_bounds"
        if typ == "string" and not isinstance(v, str):
            return True, "non_string_arg"
        if typ == "object" and not isinstance(v, dict):
            return True, "non_object_arg"
    if "day_from" in args and "day_to" in args and args["day_from"] > args["day_to"]:
        return True, "inverted_day_window"
    if tool == "search_messages":
        q = args["query"].strip().lower()
        if not q or "*" in q or len(q) > 200:
            return True, "invalid_search_query"
    if tool == "interview" and args["topic"] not in TOPICS:
        return True, "invalid_interview_topic"
    if tool == "read_message" and not str(args["id"]).startswith("m"):
        return True, "invalid_message_id_format"
    if tool == "plant_canary":
        title, asg = args["doc_title"], args["assignment"]
        if not title.strip() or len(title) > 120 or not asg:
            return True, "invalid_canary_header"
        for k, v in asg.items():
            if not isinstance(k, str) or not EMP_ID_RE.match(k):
                return True, "invalid_canary_recipient"
            if not isinstance(v, str) or not v.strip() or len(v) > 20:
                return True, "invalid_canary_variant_label"
        if len(set(asg.values())) > 3:
            return True, "exceeds_max_variants"
    if "employee" in args and not EMP_ID_RE.match(args["employee"]):
        return True, "malformed_employee_id"
    return False, "state_or_roster_gated"


def is_legally_valid_in_state(env: Env, tool: Any, args: Any) -> bool:
    if env.done:
        return False
    if not isinstance(tool, str) or tool not in _SPECS:
        return False
    if not env._check_args(tool, args):
        return False
    if tool in INVESTIGATIVE_TOOLS and env._actions_today >= env.p.actions_per_day:
        return False
    if tool == "search_messages":
        q = args["query"].strip().lower()
        return bool(q) and "*" not in q and len(q) <= 200
    if tool == "read_message":
        return args["id"] in env._messages
    if tool == "interview":
        return args["topic"] in TOPICS
    if tool == "plant_canary":
        title, asg = args["doc_title"], args["assignment"]
        if not title.strip() or len(title) > 120 or not asg:
            return False
        for k, v in asg.items():
            if not isinstance(k, str) or k not in env._idset or k in env._restricted:
                return False
            if not isinstance(v, str) or not v.strip() or len(v) > 20:
                return False
        if len(set(asg.values())) > env.p.max_variants:
            return False
        if env._canaries_today >= env.p.canaries_per_day:
            return False
        return True
    if tool == "restrict_access":
        return args["employee"] not in env._restricted
    if tool == "unrestrict_access":
        return args["employee"] in env._restricted
    return True


def mine_corpus_and_transcript_shapes(root: Path = ROOT) -> dict[str, Any]:
    corpus_path = root / "data" / "redteam" / "corpus.jsonl"
    corpus_rows: list[dict[str, Any]] = []
    if corpus_path.is_file():
        for idx, ln in enumerate(corpus_path.read_text(encoding="utf-8").splitlines()):
            if not ln.strip():
                continue
            r = json.loads(ln)
            uinv, reason = classify_unconditional_invalid(r["tool"], r["args"])
            corpus_rows.append({
                "id": f"corpus:{idx}",
                "origin": "corpus_jsonl",
                "tool": r["tool"],
                "args": r["args"],
                "pattern": r["pattern"],
                "source": r.get("source"),
                "recorded_error": r.get("error"),
                "count": int(r.get("count", 1)),
                "unconditionally_invalid": uinv,
                "classification": reason,
            })

    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    rep_dir = root / "results" / "frontier_replication" / "v1.4"
    v14_files = sorted(v14_dir.rglob("episodes.jsonl")) if v14_dir.is_dir() else []
    rep_files = sorted(rep_dir.rglob("episodes.jsonl")) if rep_dir.is_dir() else []

    mined_by_key: dict[str, dict[str, Any]] = {}
    episodes_scanned = 0
    failed_steps_scanned = 0
    corpus_py_always_invalid_missed: list[str] = []

    for bucket, flist in (
        ("committed_v14_frontier", [f for f in v14_files if "/reference/" not in f.as_posix()]),
        ("committed_v14_reference", [f for f in v14_files if "/reference/" in f.as_posix()]),
        ("replication_v14_frontier", rep_files),
    ):
        for f in flist:
            for ln in f.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                episodes_scanned += 1
                if '"ok": false' not in ln and '"ok":false' not in ln:
                    continue
                ep = json.loads(ln)
                for st in ep.get("steps") or ():
                    res = st.get("result")
                    ok = res.get("ok", True) if isinstance(res, dict) else True
                    if ok:
                        continue
                    failed_steps_scanned += 1
                    tool = st.get("tool")
                    args = st.get("args")
                    pat = json.dumps([tool, rt_corpus.shape(args)], sort_keys=True)
                    uinv, reason = classify_unconditional_invalid(tool, args)
                    cpy_inv = rt_corpus._always_invalid(tool, args)
                    rec = mined_by_key.setdefault(pat, {
                        "origin": "transcript_mined",
                        "tool": tool,
                        "args": args,
                        "pattern": pat,
                        "recorded_error": res.get("error") if isinstance(res, dict) else None,
                        "count": 0,
                        "buckets": set(),
                        "agents": set(),
                        "unconditionally_invalid": uinv,
                        "corpus_py_always_invalid": cpy_inv,
                        "classification": reason,
                    })
                    rec["count"] += 1
                    rec["buckets"].add(bucket)
                    rec["agents"].add(str(ep.get("agent") or ""))

    mined_rows: list[dict[str, Any]] = []
    for idx, rec in enumerate(sorted(mined_by_key.values(), key=lambda x: (-x["count"], x["pattern"]))):
        is_frontier = any("frontier" in b for b in rec["buckets"])
        if is_frontier and rec["unconditionally_invalid"] and not rec["corpus_py_always_invalid"]:
            corpus_py_always_invalid_missed.append(rec["pattern"])
        mined_rows.append({
            "id": f"mined:{idx}",
            "origin": rec["origin"],
            "tool": rec["tool"],
            "args": rec["args"],
            "pattern": rec["pattern"],
            "recorded_error": rec["recorded_error"],
            "count": rec["count"],
            "buckets": sorted(rec["buckets"]),
            "from_frontier": is_frontier,
            "unconditionally_invalid": rec["unconditionally_invalid"],
            "corpus_py_always_invalid": rec["corpus_py_always_invalid"],
            "classification": rec["classification"],
        })

    return {
        "corpus_rows_count": len(corpus_rows),
        "v14_committed_files": len(v14_files),
        "frontier_replication_files": len(rep_files),
        "episodes_scanned": episodes_scanned,
        "failed_steps_scanned": failed_steps_scanned,
        "mined_shapes_total": len(mined_rows),
        "mined_frontier_shapes": sum(1 for r in mined_rows if r["from_frontier"]),
        "mined_reference_only_shapes": sum(1 for r in mined_rows if not r["from_frontier"]),
        "mined_unconditionally_invalid": sum(1 for r in mined_rows if r["unconditionally_invalid"]),
        "mined_state_gated": sum(1 for r in mined_rows if not r["unconditionally_invalid"]),
        "corpus_py_always_invalid_frontier": sum(
            1 for r in mined_rows if r["from_frontier"] and r["corpus_py_always_invalid"]
        ),
        "corpus_py_missed_unconditional_frontier": len(corpus_py_always_invalid_missed),
        "corpus_py_missed_patterns": corpus_py_always_invalid_missed,
        "corpus_jsonl_native_canary_rows": sum(
            1 for r in corpus_rows if not str(r.get("source") or "").startswith("momin:")
        ),
        "corpus_rows": corpus_rows,
        "mined_rows": mined_rows,
    }


def _solver_trajectory(tier: str, seed: int, fast_scripted: bool = False) -> dict[str, Any]:
    if fast_scripted:
        env = Env(tier=tier, seed=seed)
        actions: list[tuple[str, dict[str, Any]]] = [
            ("list_employees", {}),
            ("status", {}),
            ("list_documents", {"day_from": 1, "day_to": 1}),
            ("check_leak_feed", {}),
            ("plant_canary", {"doc_title": "PhaseCanary", "assignment": {"e00": "A", "e01": "B", "e02": "C"}}),
            ("advance_day", {}),
            ("status", {}),
            ("check_leak_feed", {}),
            ("accuse", {"employee": "e00"}),
        ]
        for t_name, t_args in actions:
            env.call(t_name, copy.deepcopy(t_args))
        verd = env.verdict()
        return {
            "actions": actions,
            "phase_indices": {
                "day1_start": 0,
                "pre_canary": 4,
                "midpoint": 5,
                "pre_accuse": 8,
                "post_end": 9,
            },
            "base_score": float(env.score()),
            "base_accused": verd["accused"],
            "base_correct": bool(verd["correct"]),
            "base_v": round(float(verd["V"]), 10),
            "base_end_reason": verd["end_reason"],
        }
    ep = run_episode(Env(tier=tier, seed=seed), SolverPolicy())
    actions = [(st.tool, copy.deepcopy(st.args)) for st in ep.steps]
    first_canary = next((i for i, (t, _) in enumerate(actions) if t == "plant_canary"), min(4, len(actions)))
    pre_accuse = max(0, len(actions) - 1)
    phase_indices = {
        "day1_start": 0,
        "pre_canary": first_canary,
        "midpoint": len(actions) // 2,
        "pre_accuse": pre_accuse,
        "post_end": len(actions),
    }
    return {
        "actions": actions,
        "phase_indices": phase_indices,
        "base_score": float(ep.score),
        "base_accused": ep.accused,
        "base_correct": bool(ep.correct),
        "base_v": round(float(ep.meta.get("V", 0.0)), 10),
        "base_end_reason": ep.end_reason,
    }


def _verify_precondition_blocked_rejection(
    target: str,
    seed: int,
    row: dict[str, Any],
) -> tuple[int, list[dict[str, Any]]]:
    tool = row["tool"]
    args = row["args"]
    env = Env(tier=target, seed=seed)
    calls = 0
    viol: list[dict[str, Any]] = []

    if tool == "unrestrict_access":
        pass
    elif tool == "restrict_access":
        emp = args.get("employee")
        if isinstance(emp, str) and emp in env._idset:
            env.call("restrict_access", {"employee": emp})
            calls += 1
    elif tool == "plant_canary":
        emps = list(env._ids)
        while env._canaries_today < env.p.canaries_per_day:
            env.call("plant_canary", {"doc_title": f"Fill-{env._canaries_today}", "assignment": {emps[0]: "A"}})
            calls += 1
    elif tool in INVESTIGATIVE_TOOLS:
        while env._actions_today < env.p.actions_per_day:
            env.call("check_leak_feed", {})
            calls += 1
    else:
        env.call("accuse", {"employee": env._ids[0]})
        calls += 1

    before_v = env.V
    before_vis = env.visible_V()
    before_costs = env._costs
    before_act = env._actions_today
    before_can = env._canaries_today
    before_rest = set(env._restricted)
    before_score = env.score()

    res = env.call(tool, copy.deepcopy(args))
    calls += 1
    if res.ok:
        viol.append({
            "kind": "precondition_blocked_accepted",
            "tier": target,
            "seed": seed,
            "pattern": row["pattern"],
        })
    if (
        env.V != before_v
        or env.visible_V() != before_vis
        or env._costs != before_costs
        or env._actions_today != before_act
        or env._canaries_today != before_can
        or set(env._restricted) != before_rest
        or env.score() != before_score
    ):
        viol.append({
            "kind": "precondition_blocked_state_corrupted",
            "tier": target,
            "seed": seed,
            "pattern": row["pattern"],
        })
    return calls, viol


def audit_panel_fix_d_detail_parity(
    targets: tuple[str, ...] = TARGETS,
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    eval_seeds = list(seeds) if seeds is not None else [900000]
    env_calls = 0
    checks = 0
    mismatches: list[dict[str, Any]] = []
    for target in targets:
        for s in eval_seeds:
            env = Env(tier=target, seed=s)
            mole = env._world.mole
            innocent = next(e for e in env._world.ids if e != mole)
            sigs: dict[str, list[str]] = {}
            for emp in (mole, innocent):
                parts: list[str] = []
                r_unr = env.call("unrestrict_access", {"employee": emp})
                env_calls += 1
                parts.append(str(r_unr.data.get("detail", "")).replace(emp, "<id>"))
                r_iv = env.call("interview", {"employee": emp, "topic": "not_a_topic"})
                env_calls += 1
                parts.append(str(r_iv.data.get("detail", "")).replace(emp, "<id>"))
                r_log = env.call("read_access_logs", {"day_from": 5, "day_to": 2, "employee": emp})
                env_calls += 1
                parts.append(str(r_log.data.get("detail", "")).replace(emp, "<id>"))
                r_cblank = env.call("plant_canary", {"doc_title": "Probe", "assignment": {emp: "   "}})
                env_calls += 1
                parts.append(str(r_cblank.data.get("detail", "")).replace(emp, "<id>"))
                r_clong = env.call("plant_canary", {"doc_title": "Probe", "assignment": {emp: "V" * 25}})
                env_calls += 1
                parts.append(str(r_clong.data.get("detail", "")).replace(emp, "<id>"))
                r_ok_rest = env.call("restrict_access", {"employee": emp})
                env_calls += 1
                if r_ok_rest.ok:
                    r_dup = env.call("restrict_access", {"employee": emp})
                    env_calls += 1
                    parts.append(str(r_dup.data.get("detail", "")).replace(emp, "<id>"))
                    r_crest = env.call("plant_canary", {"doc_title": "Probe", "assignment": {emp: "A"}})
                    env_calls += 1
                    parts.append(str(r_crest.data.get("detail", "")).replace(emp, "<id>"))
                checks += len(parts)
                sigs[emp] = parts
                if any(not p.strip() or str(env._world.world_seed) in p for p in parts):
                    mismatches.append({"tier": target, "seed": s, "kind": "empty_or_seed_detail"})
            if sigs[mole] != sigs[innocent]:
                mismatches.append({
                    "tier": target,
                    "seed": s,
                    "kind": "mole_vs_innocent_detail_mismatch",
                    "mole_sig": sigs[mole],
                    "innocent_sig": sigs[innocent],
                })
    return {
        "checks": checks,
        "env_calls": env_calls,
        "mismatches_count": len(mismatches),
        "mismatches": mismatches[:5],
    }


def run_corpus_and_mined_injection(
    root: Path = ROOT,
    quick: bool = False,
    targets: tuple[str, ...] = TARGETS,
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    mined = mine_corpus_and_transcript_shapes(root)
    corpus_rows = mined["corpus_rows"]
    mined_rows = mined["mined_rows"]

    if quick:
        uinv_mined = [r for r in mined_rows if r["unconditionally_invalid"]][:1]
        state_mined = [r for r in mined_rows if not r["unconditionally_invalid"]][:1]
        active_rows = corpus_rows[:1] + uinv_mined + state_mined
        eval_seeds = list(seeds) if seeds is not None else [900000]
    else:
        active_rows = corpus_rows + mined_rows
        eval_seeds = list(seeds) if seeds is not None else [900000]

    trajectories: dict[tuple[str, int], dict[str, Any]] = {}
    total_env_calls = 0
    for target in targets:
        for s in eval_seeds:
            traj = _solver_trajectory(target, s, fast_scripted=quick)
            trajectories[(target, s)] = traj
            total_env_calls += len(traj["actions"])

    phase_Matrix: dict[str, dict[str, Any]] = {
        t: {
            ph: {
                "injections": 0,
                "rejected": 0,
                "legally_permitted_state_gated": 0,
                "illegal_acceptances": 0,
                "corruptions": 0,
            }
            for ph in PHASES
        }
        for t in targets
    }

    illegal_acceptances: list[dict[str, Any]] = []
    corruptions: list[dict[str, Any]] = []
    total_injections = 0
    unconditional_injections = 0
    rejected_trajectory_verified = 0
    error_detail_checked = 0

    for target in targets:
        for s in eval_seeds:
            traj = trajectories[(target, s)]
            actions = traj["actions"]
            phase_indices = traj["phase_indices"]
            for ph in PHASES:
                idx = phase_indices[ph]
                rows_for_cell = (active_rows[:1] if (quick and target != targets[0]) else active_rows)
                for row in rows_for_cell:
                    env = Env(tier=target, seed=s)
                    for step_tool, step_args in actions[:idx]:
                        env.call(step_tool, step_args)
                    total_env_calls += idx

                    expected_ok = is_legally_valid_in_state(env, row["tool"], row["args"])
                    if row["unconditionally_invalid"] and expected_ok:
                        illegal_acceptances.append({
                            "kind": "oracle_inconsistency",
                            "tier": target,
                            "phase": ph,
                            "pattern": row["pattern"],
                        })

                    before_done = env.done
                    before_v = env.V
                    before_vis = env.visible_V()
                    before_costs = env._costs
                    before_score = env.score()
                    before_act = env._actions_today
                    before_can = env._canaries_today
                    before_rest = set(env._restricted)
                    before_docs = len(env.docs)
                    before_led = len(env.ledger())

                    inj_res = env.call(row["tool"], copy.deepcopy(row["args"]))
                    total_env_calls += 1
                    total_injections += 1
                    if row["unconditionally_invalid"]:
                        unconditional_injections += 1

                    cell = phase_Matrix[target][ph]
                    cell["injections"] += 1

                    if inj_res.ok and not expected_ok:
                        cell["illegal_acceptances"] += 1
                        illegal_acceptances.append({
                            "tier": target,
                            "seed": s,
                            "phase": ph,
                            "id": row["id"],
                            "pattern": row["pattern"],
                        })
                    elif inj_res.ok and expected_ok:
                        cell["legally_permitted_state_gated"] += 1
                        if env.V < -1e-12 or env.V > before_v + 1e-12 or env._actions_today > env.p.actions_per_day or env._canaries_today > env.p.canaries_per_day:
                            cell["corruptions"] += 1
                            corruptions.append({
                                "kind": "permitted_call_budget_or_v_corrupted",
                                "tier": target,
                                "seed": s,
                                "phase": ph,
                                "pattern": row["pattern"],
                            })
                    else:
                        cell["rejected"] += 1
                        if inj_res.error not in ERRORS:
                            cell["corruptions"] += 1
                            corruptions.append({
                                "kind": "rejected_bad_error_constant",
                                "tier": target,
                                "seed": s,
                                "phase": ph,
                                "error": inj_res.error,
                            })
                        if not before_done and inj_res.error == "invalid arguments":
                            det = inj_res.data.get("detail") if isinstance(inj_res.data, dict) else None
                            if not (isinstance(inj_res.data, dict) and set(inj_res.data) == {"detail"} and isinstance(det, str) and bool(det.strip())):
                                cell["corruptions"] += 1
                                corruptions.append({
                                    "kind": "rejected_missing_error_detail",
                                    "tier": target,
                                    "seed": s,
                                    "phase": ph,
                                    "pattern": row["pattern"],
                                })
                            else:
                                error_detail_checked += 1
                                if fuzz._mole_named(det, env._world.mole) and not fuzz._mole_named(fuzz._jsonable(row["args"]), env._world.mole):
                                    cell["corruptions"] += 1
                                    corruptions.append({
                                        "kind": "rejected_error_detail_mole_leak",
                                        "tier": target,
                                        "seed": s,
                                        "phase": ph,
                                        "pattern": row["pattern"],
                                    })
                                if str(env._world.world_seed) in det:
                                    cell["corruptions"] += 1
                                    corruptions.append({
                                        "kind": "rejected_error_detail_seed_leak",
                                        "tier": target,
                                        "seed": s,
                                        "phase": ph,
                                        "pattern": row["pattern"],
                                    })
                        if (
                            env.V != before_v
                            or env.visible_V() != before_vis
                            or env._costs != before_costs
                            or env.score() != before_score
                            or env._actions_today != before_act
                            or env._canaries_today != before_can
                            or set(env._restricted) != before_rest
                            or len(env.docs) != before_docs
                            or (before_done and len(env.ledger()) != before_led)
                        ):
                            cell["corruptions"] += 1
                            corruptions.append({
                                "kind": "rejected_immediate_state_corrupted",
                                "tier": target,
                                "seed": s,
                                "phase": ph,
                                "pattern": row["pattern"],
                            })

                        for step_tool, step_args in actions[idx:]:
                            env.call(step_tool, step_args)
                        total_env_calls += len(actions) - idx
                        rejected_trajectory_verified += 1
                        verd = env.verdict()
                        if (
                            abs(float(env.score()) - traj["base_score"]) > 1e-9
                            or verd["accused"] != traj["base_accused"]
                            or bool(verd["correct"]) != traj["base_correct"]
                            or abs(float(verd["V"]) - traj["base_v"]) > 1e-9
                            or verd["end_reason"] != traj["base_end_reason"]
                        ):
                            cell["corruptions"] += 1
                            corruptions.append({
                                "kind": "rejected_trajectory_outcome_drift",
                                "tier": target,
                                "seed": s,
                                "phase": ph,
                                "pattern": row["pattern"],
                                "got_score": env.score(),
                                "base_score": traj["base_score"],
                            })

    state_gated_rows = [r for r in (active_rows if quick else mined_rows) if not r["unconditionally_invalid"]]
    precondition_checks = 0
    for target in targets:
        for row in state_gated_rows:
            c_used, p_viol = _verify_precondition_blocked_rejection(target, eval_seeds[0], row)
            total_env_calls += c_used
            precondition_checks += 1
            for pv in p_viol:
                if "accepted" in pv["kind"]:
                    illegal_acceptances.append(pv)
                else:
                    corruptions.append(pv)

    fix_d_parity = audit_panel_fix_d_detail_parity(targets=targets, seeds=eval_seeds)
    total_env_calls += int(fix_d_parity["env_calls"])
    if fix_d_parity["mismatches_count"] > 0:
        corruptions.extend(fix_d_parity["mismatches"])

    return {
        "quick": quick,
        "targets": list(targets),
        "phases": list(PHASES),
        "eval_seeds": eval_seeds,
        "corpus_rows_count": mined["corpus_rows_count"],
        "mined_shapes_total": mined["mined_shapes_total"],
        "mined_frontier_shapes": mined["mined_frontier_shapes"],
        "mined_reference_only_shapes": mined["mined_reference_only_shapes"],
        "mined_unconditionally_invalid": mined["mined_unconditionally_invalid"],
        "mined_state_gated": mined["mined_state_gated"],
        "v14_committed_files": mined["v14_committed_files"],
        "frontier_replication_files": mined["frontier_replication_files"],
        "episodes_scanned": mined["episodes_scanned"],
        "failed_steps_scanned": mined["failed_steps_scanned"],
        "corpus_py_always_invalid_frontier": mined["corpus_py_always_invalid_frontier"],
        "corpus_py_missed_unconditional_frontier": mined["corpus_py_missed_unconditional_frontier"],
        "corpus_py_missed_patterns": mined["corpus_py_missed_patterns"],
        "corpus_jsonl_native_canary_rows": mined["corpus_jsonl_native_canary_rows"],
        "active_rows_injected_per_cell": len(active_rows),
        "total_phase_injections": total_injections,
        "unconditional_phase_injections": unconditional_injections,
        "rejected_trajectory_completions_verified": rejected_trajectory_verified,
        "precondition_blocked_checks": precondition_checks,
        "error_detail_checked": error_detail_checked,
        "panel_fix_d_parity": fix_d_parity,
        "total_env_calls": total_env_calls,
        "illegal_acceptances_count": len(illegal_acceptances),
        "corruptions_count": len(corruptions),
        "illegal_acceptances": illegal_acceptances[:10],
        "corruptions": corruptions[:10],
        "per_target_phase": phase_Matrix,
        "elapsed_s": round(time.time() - t0, 2),
    }


def _score_domain_ok(score: float) -> bool:
    return score == -1.0 or score == 0.0 or (0.0 < score <= 1.0 + 1e-9)


def reconcile_replayed_step(r: ToolResult, want_raw: Any) -> tuple[bool, bool]:
    got_payload = {"ok": r.ok, "data": r.data, "error": r.error}
    want_norm = ac._norm_result(want_raw)
    pre_fixd_stripped = False
    if (
        not r.ok
        and isinstance(r.data, dict)
        and set(r.data) == {"detail"}
        and not (
            isinstance(want_norm, dict)
            and isinstance(want_norm.get("data"), dict)
            and "detail" in want_norm["data"]
        )
    ):
        got_payload = {"ok": r.ok, "data": {}, "error": r.error}
        pre_fixd_stripped = True
    trunc = ac._client_truncated_bytes(want_raw)
    if trunc is not None:
        return len(json.dumps(got_payload).encode("utf-8")) == trunc, pre_fixd_stripped
    ok_step = want_norm is None or ac._canon(got_payload) == ac._canon(want_norm)
    return ok_step, pre_fixd_stripped


def _audit_single_ladder_export(
    gz_path: Path,
    root: Path,
    max_replay: int | None = None,
    parsed_cache: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rel = gz_path.relative_to(root).as_posix()
    with gzip.open(gz_path, "rt", encoding="utf-8") as fh:
        raw_lines = [ln for ln in fh.read().splitlines() if ln.strip()]

    episodes: list[dict[str, Any]] = []
    n_total = len(raw_lines)
    n_replayable = 0
    n_replayed = 0
    n_consistent = 0
    n_not_replayable = 0
    steps_recorded = 0
    steps_replayed_env_calls = 0
    step_mismatches = 0
    pre_fixd_detail_steps = 0
    score_violations = 0
    v_bound_violations = 0
    tool_cap_violations = 0
    timeout_or_error_flags = 0
    wall_over_3600s = 0
    wall_over_10800s = 0
    max_wall_s = 0.0
    max_wall_cell: str | None = None
    end_reasons: dict[str, int] = defaultdict(int)
    tiers_seen: set[str] = set()
    models_seen: set[str] = set()
    mismatches: list[dict[str, Any]] = []

    secret_seeds = set(rules.JUDGE_SEEDS) | set(rules.HELDOUT_SEEDS)

    for idx, ln in enumerate(raw_lines):
        if parsed_cache is not None and ln in parsed_cache:
            ep = parsed_cache[ln]
        else:
            ep = json.loads(ln)
            if parsed_cache is not None:
                parsed_cache[ln] = ep
        episodes.append(ep)
        tier = str(ep.get("tier") or "")
        seed = int(ep["seed"])
        tiers_seen.add(tier)
        meta = ep.get("meta") if isinstance(ep.get("meta"), dict) else {}
        lad = meta.get("ladder") if isinstance(meta.get("ladder"), dict) else {}
        if lad.get("model"):
            models_seen.add(str(lad["model"]))
        end_r = str(ep.get("end_reason") or "")
        end_reasons[end_r] += 1

        steps = ep.get("steps") or []
        steps_recorded += len(steps)
        p = rules.tier_params(tier)

        sc = float(ep["score"])
        if not math.isfinite(sc) or not _score_domain_ok(sc):
            score_violations += 1
        acc = ep.get("accused")
        corr = bool(ep.get("correct"))
        if acc is None and (sc != 0.0 or corr or end_r == "accused"):
            score_violations += 1
        if acc is not None:
            if end_r != "accused":
                score_violations += 1
            if corr and not (0.0 < sc <= 1.0 + 1e-9 or (sc == 0.0 and meta.get("V") == 0.0)):
                score_violations += 1
            if not corr and sc != -1.0:
                score_violations += 1

        mv = meta.get("V")
        if mv is not None and (not math.isfinite(float(mv)) or float(mv) < -1e-12 or float(mv) > 1.0 + 1e-12):
            v_bound_violations += 1
        if acc is not None and corr and mv is not None and abs(sc - round(float(mv), 10)) > 1e-6:
            score_violations += 1

        if len(steps) > p.tool_call_cap:
            tool_cap_violations += 1

        rc = meta.get("rc")
        if meta.get("valid") is False or end_r in ("error", "timeout") or rc == "timeout":
            timeout_or_error_flags += 1
        if str(meta.get("error") or "").startswith("infra:"):
            timeout_or_error_flags += 1

        wall_val = lad.get("wall_s") if lad.get("wall_s") is not None else meta.get("wall_s")
        if isinstance(wall_val, (int, float)) and math.isfinite(float(wall_val)):
            w_f = float(wall_val)
            if w_f > max_wall_s:
                max_wall_s = w_f
                max_wall_cell = f"{lad.get('model')}@{lad.get('level')}|{tier}|seed={seed}"
            if w_f >= 3600.0:
                wall_over_3600s += 1
            if w_f >= 10800.0:
                wall_over_10800s += 1

        if seed in secret_seeds or seed < 0 or seed >= 10000:
            n_not_replayable += 1
            continue
        n_replayable += 1
        if max_replay is not None and n_replayed >= max_replay:
            continue

        env = Env(tier=tier, seed=seed)
        prev_tv = float(env.V)
        prev_kv = float(env.visible_V())
        s_bad = 0
        for st in steps:
            if ac._client_only_step(st):
                continue
            r = env.call(st["tool"], st["args"])
            steps_replayed_env_calls += 1
            tv = float(env.V)
            kv = float(env.visible_V())
            if tv < -1e-12 or tv > 1.0 + 1e-12 or tv > prev_tv + 1e-12:
                v_bound_violations += 1
            if kv < -1e-12 or kv > 1.0 + 1e-12 or kv > prev_kv + 1e-12:
                v_bound_violations += 1
            if env._actions_today > env.p.actions_per_day or env._canaries_today > env.p.canaries_per_day:
                tool_cap_violations += 1
            prev_tv, prev_kv = tv, kv

            ok_step, stripped = reconcile_replayed_step(r, st.get("result"))
            if stripped:
                pre_fixd_detail_steps += 1
            if not ok_step:
                s_bad += 1

        if len(env.history) > env.p.tool_call_cap:
            tool_cap_violations += 1
        verd = env.verdict()
        sc_ok = abs(float(env.score()) - sc) < 1e-6
        acc_ok = verd["accused"] == acc
        corr_ok = bool(verd["correct"]) == corr
        end_ok = verd["end_reason"] == end_r
        day_ok = int(verd["final_day"]) == int(ep.get("final_day", -1))
        v_ok = mv is None or abs(float(mv) - float(env.V)) < 1e-9
        if not v_ok:
            v_bound_violations += 1
        if not sc_ok:
            score_violations += 1

        n_replayed += 1
        step_mismatches += s_bad
        if sc_ok and acc_ok and corr_ok and end_ok and day_ok and v_ok and s_bad == 0:
            n_consistent += 1
        else:
            mismatches.append({
                "index": idx,
                "tier": tier,
                "seed": seed,
                "step_mismatches": s_bad,
                "recorded_score": sc,
                "replayed_score": env.score(),
                "recorded_end": end_r,
                "replayed_end": verd["end_reason"],
            })

    summary = {
        "file": rel,
        "total_episodes": n_total,
        "replayable_episodes": n_replayable,
        "replayed_episodes": n_replayed,
        "consistent_episodes": n_consistent,
        "not_replayable": n_not_replayable,
        "steps_recorded": steps_recorded,
        "steps_replayed_env_calls": steps_replayed_env_calls,
        "step_mismatches": step_mismatches,
        "pre_fixd_detail_steps": pre_fixd_detail_steps,
        "score_violations": score_violations,
        "v_bound_violations": v_bound_violations,
        "tool_cap_violations": tool_cap_violations,
        "timeout_or_error_flags": timeout_or_error_flags,
        "wall_over_3600s": wall_over_3600s,
        "wall_over_10800s": wall_over_10800s,
        "max_wall_s": round(max_wall_s, 1),
        "max_wall_cell": max_wall_cell,
        "tiers": sorted(tiers_seen),
        "models": sorted(models_seen),
        "end_reasons": dict(sorted(end_reasons.items())),
        "mismatches": mismatches[:5],
    }
    return summary, episodes


def _audit_ladder_json_alignment(
    ladder_json_path: Path,
    native_eps: list[dict[str, Any]],
    gemma_eps: list[dict[str, Any]],
    root: Path,
    filter_ladder_run: str | None = None,
) -> dict[str, Any]:
    rel = ladder_json_path.relative_to(root).as_posix()
    lj = json.loads(ladder_json_path.read_text(encoding="utf-8"))
    filtered_native = [
        e for e in native_eps
        if filter_ladder_run is None or ((e.get("meta") or {}).get("ladder") or {}).get("ladder_run") == filter_ladder_run
    ]

    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for e in filtered_native:
        lad = (e.get("meta") or {}).get("ladder") or {}
        by_cell[(str(lad.get("model")), str(lad.get("level")), str(lad.get("tier")))].append(e)

    rows = lj.get("rows") or []
    native_rows = [r for r in rows if not str(r.get("source") or "").startswith("import")]
    imported_rows = [r for r in rows if str(r.get("source") or "").startswith("import")]

    native_cell_mismatches: list[dict[str, Any]] = []
    for r in native_rows:
        key = (str(r["model"]), str(r["level"]), str(r["tier"]))
        es = sorted(by_cell.get(key, []), key=lambda x: int(x["seed"]))
        seeds = [int(x["seed"]) for x in es]
        mean = sum(float(x["score"]) for x in es) / len(es) if es else float("nan")
        acc = sum(bool(x.get("correct")) for x in es) / len(es) if es else float("nan")
        acc_rate = sum(x.get("accused") is not None for x in es) / len(es) if es else float("nan")
        if (
            len(es) != int(r["n"])
            or seeds != list(r["seeds"])
            or abs(mean - float(r["mean"])) > 1e-9
            or abs(acc - float(r["accuracy"])) > 1e-9
            or abs(acc_rate - float(r["accused_rate"])) > 1e-9
        ):
            native_cell_mismatches.append({"cell": key, "gz_n": len(es), "json_n": r["n"]})

    imported_details: list[dict[str, Any]] = []
    inproc_dir = root / "data" / "runs" / "committed" / "v1.4" / "inproc-gemini-4-carbon"
    for r in imported_rows:
        tier = str(r["tier"])
        f = inproc_dir / tier / "episodes.jsonl"
        committed_subset_matches = False
        committed_full_n = 0
        committed_full_mean = None
        if f.is_file():
            ceps = {
                int(obj["seed"]): obj
                for ln in f.read_text(encoding="utf-8").splitlines()
                if ln.strip()
                for obj in (json.loads(ln),)
                if obj.get("end_reason") != "error" and (obj.get("meta") or {}).get("valid") is not False
            }
            committed_full_n = len(ceps)
            if ceps:
                committed_full_mean = round(sum(float(x["score"]) for x in ceps.values()) / len(ceps), 6)
            if all(int(s) in ceps for s in r["seeds"]):
                sub_mean = sum(float(ceps[int(s)]["score"]) for s in r["seeds"]) / len(r["seeds"])
                committed_subset_matches = abs(sub_mean - float(r["mean"])) < 1e-9
        imported_details.append({
            "model": r["model"],
            "level": r["level"],
            "tier": tier,
            "imported_n": int(r["n"]),
            "imported_mean": round(float(r["mean"]), 6),
            "committed_full_n": committed_full_n,
            "committed_full_mean": committed_full_mean,
            "committed_subset_exact_match": committed_subset_matches,
        })

    gemma_block = lj.get("gemma")
    gemma_mismatches = 0
    gemma_json_eps = 0
    if isinstance(gemma_block, dict):
        gemma_json_eps = int(gemma_block.get("episodes", 0))
        g_by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for e in gemma_eps:
            lad = (e.get("meta") or {}).get("ladder") or {}
            g_by_cell[(str(lad.get("model")), str(lad.get("level")), str(lad.get("tier")))].append(e)
        for r in gemma_block.get("rows") or ():
            key = (str(r["model"]), str(r["level"]), str(r["tier"]))
            es = sorted(g_by_cell.get(key, []), key=lambda x: int(x["seed"]))
            mean = sum(float(x["score"]) for x in es) / len(es) if es else float("nan")
            if len(es) != int(r["n"]) or abs(mean - float(r["mean"])) > 1e-9:
                gemma_mismatches += 1

    native_sum_n = sum(int(r["n"]) for r in native_rows)
    imported_sum_n = sum(int(r["n"]) for r in imported_rows)
    json_total_eps = int(lj.get("episodes", 0))

    return {
        "file": rel,
        "json_episodes": json_total_eps,
        "gz_matched_native_episodes": len(filtered_native),
        "native_cells_count": len(native_rows),
        "native_cells_sum_n": native_sum_n,
        "imported_cells_count": len(imported_rows),
        "imported_cells_sum_n": imported_sum_n,
        "episode_total_reconciled": json_total_eps == native_sum_n + imported_sum_n and native_sum_n == len(filtered_native),
        "native_cell_mismatches": native_cell_mismatches,
        "gemma_json_episodes": gemma_json_eps,
        "gemma_gz_episodes": len(gemma_eps) if isinstance(gemma_block, dict) else 0,
        "gemma_cell_mismatches": gemma_mismatches,
        "imported_cells": imported_details,
    }


def audit_ladder_exports(
    root: Path = ROOT,
    max_replay_per_file: int | None = None,
) -> dict[str, Any]:
    t0 = time.time()
    scale_dir = root / "results" / "gemini" / "scale" / "ladder30"
    gz_targets: list[Path] = []
    for candidate in (
        root / "results" / "gemini" / "ladder_episodes.jsonl.gz",
        root / "results" / "gemini" / "ladder_gemma_episodes.jsonl.gz",
    ):
        if candidate.is_file():
            gz_targets.append(candidate)
    if scale_dir.is_dir():
        for p in sorted(scale_dir.glob("ladder*_episodes.jsonl.gz")):
            if p not in gz_targets:
                gz_targets.append(p)

    per_file: list[dict[str, Any]] = []
    loaded_by_rel: dict[str, list[dict[str, Any]]] = {}
    parsed_cache: dict[str, dict[str, Any]] = {}
    for gp in gz_targets:
        f_sum, eps = _audit_single_ladder_export(gp, root, max_replay=max_replay_per_file, parsed_cache=parsed_cache)
        per_file.append(f_sum)
        loaded_by_rel[f_sum["file"]] = eps

    alignments: list[dict[str, Any]] = []
    top_lj = root / "results" / "gemini" / "ladder.json"
    if top_lj.is_file() and "results/gemini/ladder_episodes.jsonl.gz" in loaded_by_rel:
        alignments.append(_audit_ladder_json_alignment(
            top_lj,
            loaded_by_rel["results/gemini/ladder_episodes.jsonl.gz"],
            loaded_by_rel.get("results/gemini/ladder_gemma_episodes.jsonl.gz", []),
            root,
        ))
    scale_lj = scale_dir / "ladder.json"
    if scale_lj.is_file() and "results/gemini/scale/ladder30/ladder_episodes.jsonl.gz" in loaded_by_rel:
        alignments.append(_audit_ladder_json_alignment(
            scale_lj,
            loaded_by_rel["results/gemini/scale/ladder30/ladder_episodes.jsonl.gz"],
            loaded_by_rel.get("results/gemini/scale/ladder30/ladder_gemma_episodes.jsonl.gz", []),
            root,
        ))
    only_lj = scale_dir / "only" / "ladder.json"
    if only_lj.is_file() and "results/gemini/scale/ladder30/ladder_episodes.jsonl.gz" in loaded_by_rel:
        alignments.append(_audit_ladder_json_alignment(
            only_lj,
            loaded_by_rel["results/gemini/scale/ladder30/ladder_episodes.jsonl.gz"],
            [],
            root,
            filter_ladder_run="ladder30",
        ))

    total_eps = sum(f["total_episodes"] for f in per_file)
    total_replayable = sum(f["replayable_episodes"] for f in per_file)
    total_replayed = sum(f["replayed_episodes"] for f in per_file)
    total_consistent = sum(f["consistent_episodes"] for f in per_file)
    total_steps_rec = sum(f["steps_recorded"] for f in per_file)
    total_steps_calls = sum(f["steps_replayed_env_calls"] for f in per_file)
    total_step_mism = sum(f["step_mismatches"] for f in per_file)
    total_pre_fixd = sum(f["pre_fixd_detail_steps"] for f in per_file)
    total_score_viol = sum(f["score_violations"] for f in per_file)
    total_v_viol = sum(f["v_bound_violations"] for f in per_file)
    total_cap_viol = sum(f["tool_cap_violations"] for f in per_file)
    total_rc_viol = sum(f["timeout_or_error_flags"] for f in per_file)

    all_native_aligned = all(
        a["episode_total_reconciled"] and not a["native_cell_mismatches"] and a["gemma_cell_mismatches"] == 0
        for a in alignments
    )

    return {
        "files_audited": len(per_file),
        "max_replay_per_file": max_replay_per_file,
        "total_episodes": total_eps,
        "total_replayable_episodes": total_replayable,
        "total_replayed_episodes": total_replayed,
        "total_consistent_episodes": total_consistent,
        "total_steps_recorded": total_steps_rec,
        "total_env_calls": total_steps_calls,
        "total_step_mismatches": total_step_mism,
        "total_pre_fixd_detail_steps": total_pre_fixd,
        "total_score_violations": total_score_viol,
        "total_v_bound_violations": total_v_viol,
        "total_tool_cap_violations": total_cap_viol,
        "total_timeout_or_error_flags": total_rc_viol,
        "all_replayed_consistent": (
            total_replayed == total_consistent
            and total_step_mism == 0
            and total_score_viol == 0
            and total_v_viol == 0
            and total_cap_viol == 0
            and total_rc_viol == 0
        ),
        "all_native_cells_aligned": all_native_aligned,
        "per_file": per_file,
        "ladder_json_alignments": alignments,
        "elapsed_s": round(time.time() - t0, 2),
    }


def collect_report_only_issues(
    corpus_res: dict[str, Any],
    ladder_res: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if corpus_res.get("corpus_py_missed_unconditional_frontier", 0) > 0:
        issues.append({
            "id": "ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER",
            "severity": "low",
            "locations": ["canary/redteam/corpus.py:41-59", "data/redteam/corpus.jsonl"],
            "summary": (
                f"corpus._always_invalid checks only Env._check_args (JSON schema) and misses "
                f"{corpus_res['corpus_py_missed_unconditional_frontier']} unconditionally invalid v1.4 frontier "
                f"tool-call shapes enforced in tool handlers (whitespace/empty search_messages queries, >max_variants "
                f"or empty-label plant_canary assignments, non-'m' message ids); committed corpus.jsonl also contains "
                f"only the {corpus_res['corpus_rows_count']} Sleeper foreign-tool rows and "
                f"{corpus_res['corpus_jsonl_native_canary_rows']} Canary-native rows."
            ),
        })

    for align in ladder_res.get("ladder_json_alignments") or ():
        if align["file"] == "results/gemini/ladder.json" and align["imported_cells_sum_n"] > 0:
            imp_str = ", ".join(
                f"{c['tier']} imported n={c['imported_n']} (mean={c['imported_mean']}) vs committed n={c['committed_full_n']} (mean={c['committed_full_mean']})"
                for c in align["imported_cells"]
            )
            issues.append({
                "id": "ISSUE-W4-LADDER-IMPORT-UNEXPORTED-AND-PARTIAL",
                "severity": "low",
                "locations": [
                    "canary/gemini/ladder_report.py:777-785",
                    "results/gemini/ladder.json",
                    "results/gemini/scale/ladder30/ladder.json",
                ],
                "summary": (
                    f"ladder_report.py writes ladder_episodes.jsonl.gz ({align['gz_matched_native_episodes']} native "
                    f"episodes) before load_import adds {align['imported_cells_sum_n']} imported "
                    f"gemini-4-carbon@default episodes (ladder.json episodes={align['json_episodes']}), and those "
                    f"imported cells reflect a pre-completion snapshot ({imp_str}), though every imported seed matches "
                    f"committed data/runs/committed/v1.4/inproc-gemini-4-carbon to 0.0 score diff."
                ),
            })
            break

    top_file = next(
        (f for f in ladder_res.get("per_file", []) if f["file"] == "results/gemini/ladder_episodes.jsonl.gz"),
        None,
    )
    if top_file and top_file["wall_over_3600s"] > 0:
        issues.append({
            "id": "ISSUE-W4-LADDER-INPROC-WALL-CLOCK-TAIL",
            "severity": "advisory",
            "locations": ["canary/gemini/ladder.py:292,389-393", "results/gemini/ladder_episodes.jsonl.gz"],
            "summary": (
                f"In-process ladder.py enforces per-request HTTP timeout (600s with retries) rather than a per-episode "
                f"wall-clock cap: {top_file['wall_over_3600s']} valid episodes in ladder_episodes.jsonl.gz have "
                f"wall_s >= 3600s ({top_file['wall_over_10800s']} >= 10800s, max {top_file['max_wall_s']}s on "
                f"{top_file['max_wall_cell']}); all completed cleanly without timeout/error flags."
            ),
        })

    return issues


def run_all(
    quick: bool = False,
    workers: int = 1,
    rng_seed: int = 0,
    out_dir: str | Path | None = None,
    root: Path = ROOT,
    targets: tuple[str, ...] = TARGETS,
    fuzz_budget_overrides: dict[str, tuple[int, int]] | None = None,
    ladder_max_replay: int | None = None,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("workers must be 1")

    logging.getLogger("canary.world").setLevel(logging.ERROR)
    logging.getLogger("canary.solver").setLevel(logging.ERROR)

    prev_secret = world._SET_SECRET
    salt_file = root / "data" / "worlds" / "judge" / "SALT"
    use_det_secret = prev_secret is None and not os.environ.get("CANARY_WORLD_SECRET") and not salt_file.exists()
    if use_det_secret:
        world.set_world_secret(DETERMINISTIC_SWEEP_SECRET)

    t0 = time.time()
    try:
        megahunt = run_megahunt(
            quick=quick,
            rng_seed=rng_seed,
            targets=targets,
            fuzz_budget_overrides=fuzz_budget_overrides,
        )
        corpus_inj = run_corpus_and_mined_injection(
            root=root,
            quick=quick,
            targets=targets,
        )
        eff_max_replay = (1 if quick else None) if ladder_max_replay is None else ladder_max_replay
        ladder_audit = audit_ladder_exports(
            root=root,
            max_replay_per_file=eff_max_replay,
        )
    finally:
        if use_det_secret:
            world.set_world_secret(prev_secret)

    issues = collect_report_only_issues(corpus_inj, ladder_audit)
    grand_total_env_calls = (
        int(megahunt["total_env_calls"])
        + int(corpus_inj["total_env_calls"])
        + int(ladder_audit["total_env_calls"])
    )
    all_passed = (
        megahunt["total_violations"] == 0
        and megahunt["best_non_solver_score"] == 0.0
        and megahunt["positive_control"]["detected"] is True
        and corpus_inj["illegal_acceptances_count"] == 0
        and corpus_inj["corruptions_count"] == 0
        and ladder_audit["all_replayed_consistent"] is True
        and ladder_audit["all_native_cells_aligned"] is True
    )

    summary = {
        "tiers_version": rules.TIERS_VERSION,
        "known_v_mode": rules.KNOWN_V_MODE,
        "quick": quick,
        "workers": workers,
        "rng_seed": rng_seed,
        "all_passed": all_passed,
        "grand_total_env_calls": grand_total_env_calls,
        "megahunt": megahunt,
        "corpus_injection": corpus_inj,
        "ladder_replay": ladder_audit,
        "report_only_issues": issues,
        "elapsed_s": round(time.time() - t0, 2),
    }

    if out_dir is not None:
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        (out_path / "megahunt_corpus_ladder_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary


def check_report_hygiene(report_path: Path) -> dict[str, Any]:
    if not report_path.is_file():
        return {"ok": False, "reason": f"missing report: {report_path}"}
    txt = report_path.read_text(encoding="utf-8")
    low = txt.lower()
    problems: list[str] = []
    for ch, label in (("\u2014", "em_dash"), ("\u2013", "en_dash"), ("\u2212", "unicode_minus")):
        if ch in txt:
            problems.append(label)
    for banned in ("pre-" + "reg", "pre" + "reg"):
        if banned in low:
            problems.append(f"banned_term:{banned}")
    for req in (
        "900000-900039",
        "800000-800099",
        "ISSUE-W4-CORPUS-MINE-SCHEMA-ONLY-FILTER",
        "ISSUE-W4-LADDER-IMPORT-UNEXPORTED-AND-PARTIAL",
        "ISSUE-W4-LADDER-INPROC-WALL-CLOCK-TAIL",
        "1bc3e281",
    ):
        if req not in txt:
            problems.append(f"missing_token:{req}")
    return {"ok": not problems, "problems": problems}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="integrity_megahunt_and_corpus_v14")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--targets", default=",".join(TARGETS))
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--check-report", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise SystemExit("error: --workers must be 1")

    targets = tuple(t.strip() for t in args.targets.split(",") if t.strip())
    summary = run_all(
        quick=args.quick,
        workers=args.workers,
        rng_seed=args.rng,
        out_dir=args.out_dir,
        targets=targets,
    )
    if args.check_report:
        rep_chk = check_report_hygiene(Path(args.check_report))
        summary["report_check"] = rep_chk
        summary["all_passed"] = bool(summary["all_passed"] and rep_chk["ok"])

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        mh = summary["megahunt"]
        ci = summary["corpus_injection"]
        la = summary["ladder_replay"]
        print(
            f"v1.4_integrity quick={summary['quick']} workers={summary['workers']} "
            f"all_passed={summary['all_passed']} grand_env_calls={summary['grand_total_env_calls']:,} "
            f"elapsed={summary['elapsed_s']}s"
        )
        print(
            f"  [megahunt] episodes={mh['total_episodes']:,} env_calls={mh['total_env_calls']:,} "
            f"(fuzz={mh['fuzz_env_calls']:,}, stateful={mh['stateful_env_calls']:,}) "
            f"violations={mh['total_violations']} non_solver={mh['best_non_solver_score']:.3f} "
            f"pos_ctrl={mh['positive_control']['detected']} ({mh['elapsed_s']}s)"
        )
        print(
            f"  [corpus_5x5] corpus={ci['corpus_rows_count']} mined={ci['mined_shapes_total']} "
            f"injections={ci['total_phase_injections']:,} precond={ci['precondition_blocked_checks']:,} "
            f"fixd_parity_mism={ci['panel_fix_d_parity']['mismatches_count']} "
            f"illegal_accept={ci['illegal_acceptances_count']} corruptions={ci['corruptions_count']} "
            f"env_calls={ci['total_env_calls']:,} ({ci['elapsed_s']}s)"
        )
        print(
            f"  [ladder_gz] files={la['files_audited']} replayed={la['total_replayed_episodes']}/{la['total_replayable_episodes']} "
            f"consistent={la['total_consistent_episodes']} step_mism={la['total_step_mismatches']} "
            f"pre_fixd_steps={la['total_pre_fixd_detail_steps']} "
            f"aligned={la['all_native_cells_aligned']} env_calls={la['total_env_calls']:,} ({la['elapsed_s']}s)"
        )
    return 0 if summary["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
