from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import world as canary_world
from canary.env import Env
from canary.eval import run_episode
from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS
from canary.solver.policy import SolverPolicy

LABELS = "ABCDEFGH"
TIERS: tuple[str, ...] = ("easy", "medium", "hard")
AGENT_ORDER: tuple[str, ...] = (
    "before_uncalibrated",
    "after_trained",
    "solver_reference",
)
SHIPPED_DEV_SEEDS_BY_TIER: dict[str, tuple[int, ...]] = {
    "hard": (6, 26, 4, 18),
    "medium": (0, 12),
    "easy": (3000,),
}
HELDOUT_PARITY_SEEDS: tuple[int, ...] = (800_000, 800_001, 800_002)
STAGE2_TRAIN_SLICE: tuple[int, int] = (102_000, 102_180)
STAGE3_TRAIN_SLICE: tuple[int, int] = (102_600, 102_780)
SMOKE_TRAIN_SLICE: tuple[int, int] = (102_000, 102_018)
SEED_SPLIT_NOTE = "dev_diagnostic_post_hoc_locked"
HELDOUT_EVAL_TAG = "canary-tiebreak-heldout-v14-eval-01"
EXPECTED_WORLD_SECRET_TAG = "sha256:ebf2f09716cf76d3"
MAX_BUNDLE_BYTES = 250_000

DEFAULT_DATA_JS = ROOT / "docs" / "arena" / "data" / "tiebreak_traces.js"
DEFAULT_SHIM_JS = ROOT / "docs" / "arena" / "tiebreak_traces.js"

DEFAULT_TOPICS: tuple[str, ...] = (
    "recent_documents",
    "contacts_outside",
    "workload",
    "access_needs",
)
ANGER_QUERIES: tuple[str, ...] = (
    "promotion",
    "raise",
    "deserve",
    "goalposts",
    "nobody asks",
    "pay here",
)
EVASIVE_MARKERS: tuple[str, ...] = (
    "offhand",
    "is something missing",
    "keep track",
    "skim most",
    "nothing worth mentioning",
    "depends what you count",
    "personal life",
    "keep a list",
    "i manage",
    "hard to say",
    "some days are late",
    "another time",
    "whatever access",
    "it set it up",
    "problem with my access",
    "evasive",
)

FORBIDDEN_STEP_KEYS: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleId",
        "decoy",
        "true_decoy",
        "decoy_id",
        "decoyId",
        "correct",
        "accused_correct",
        "true_v",
        "true_V",
        "trueV",
        "is_canary",
        "raw_doc_id",
        "raw_title",
        "true_variant",
        "variant_recipients",
        "_world",
        "world_seed",
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
        "is_mole",
        "sealed_verdict",
        "verdict",
        "reveal",
    }
)
FORBIDDEN_ARENA_TOKENS: tuple[str, ...] = (
    "CANARY_" + "WORLD_SECRET",
    "CANARY_" + "LEDGER_TOKEN",
    "CANARY_" + "ADMIN_TOKEN",
    "CANARY_" + "LEDGER_KEY",
    "SA" + "LT",
)
COMMENT_TOKENS: tuple[str, ...] = (
    chr(47) * 2,
    chr(47) + chr(42),
    chr(42) + chr(47),
)
DASH_CHARS: tuple[str, ...] = (
    chr(0x2014),
    chr(0x2013),
    chr(0x2212),
)


@dataclass(frozen=True)
class CompactEmpiricalBayesParams:
    w_canary_hit: float
    w_canary_miss: float
    w_doc_hit: float
    w_after_hours: float
    w_evasive: float
    w_angry_msg: float
    tau_margin: float
    unsurfaced_v_discount: float
    canary_coverage: float
    tiny_pool_size: int
    use_ev_stopping: bool = True
    naive_p_threshold: float = 0.50
    stage: str = "after_trained"

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        for key, val in list(raw.items()):
            if isinstance(val, float):
                raw[key] = round(val, 6)
        return raw


LOCKED_TRAIN_FITTED_PARAMS = CompactEmpiricalBayesParams(
    w_canary_hit=1.316224,
    w_canary_miss=-3.783276,
    w_doc_hit=7.921455,
    w_after_hours=0.122482,
    w_evasive=0.343812,
    w_angry_msg=-2.362232,
    tau_margin=0.50,
    unsurfaced_v_discount=1.00,
    canary_coverage=0.65,
    tiny_pool_size=3,
    use_ev_stopping=True,
    naive_p_threshold=0.50,
    stage="after_trained",
)


def make_uncalibrated_params() -> CompactEmpiricalBayesParams:
    return CompactEmpiricalBayesParams(
        w_canary_hit=1.0,
        w_canary_miss=-0.8,
        w_doc_hit=0.6,
        w_after_hours=0.8,
        w_evasive=0.4,
        w_angry_msg=1.2,
        tau_margin=0.0,
        unsurfaced_v_discount=0.0,
        canary_coverage=0.90,
        tiny_pool_size=0,
        use_ev_stopping=False,
        naive_p_threshold=0.50,
        stage="before_uncalibrated",
    )


def assert_strict_train_seed(seed: int) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"train seed must be int, got {seed!r}")
    if seed in DEV_SEEDS or seed in HELDOUT_SEEDS or seed in JUDGE_SEEDS:
        raise ValueError(f"train seed {seed} overlaps non-train benchmark split")
    if seed not in TRAIN_SEEDS or not (100_000 <= seed < 200_000):
        raise ValueError(f"train seed {seed} outside TRAIN_SEEDS [100000, 200000)")
    return seed


def _parse_instruction_rules(instruction: str) -> dict[str, Any]:
    raw: dict[str, str] = {}
    for line in (instruction or "").splitlines():
        s = line.strip()
        if s.startswith("- ") and ": " in s:
            key, val = s[2:].split(": ", 1)
            if key.replace("_", "").isalnum():
                raw.setdefault(key, val.strip())

    def _f(key: str, default: float) -> float:
        try:
            return float(raw[key])
        except (KeyError, ValueError):
            return default

    def _i(key: str, default: int) -> int:
        try:
            return int(float(raw[key]))
        except (KeyError, ValueError):
            return default

    def _b(key: str, default: bool) -> bool:
        val = raw.get(key, "").lower()
        if val in ("on", "true", "1", "yes"):
            return True
        if val in ("off", "false", "0", "no"):
            return False
        return default

    delays: list[int] = []
    for part in raw.get("delay_choices", "1, 2").split(","):
        part = part.strip()
        if part.isdigit():
            delays.append(int(part))
    if not delays:
        delays = [1, 2]

    low_txt = (instruction or "").lower()
    known_v = (
        "not visible until they surface" in low_txt
        or "undetected damage" in low_txt
        or "known v" in low_txt
    )
    return {
        "n_employees": _i("n_employees", 20),
        "n_days": _i("n_days", 14),
        "p_leak": _f("p_leak", 0.75),
        "delay_choices": tuple(delays),
        "leak_damage": _f("leak_damage", 0.05),
        "canary_cost": _f("canary_cost", 0.01),
        "canaries_per_day": _i("canaries_per_day", 1),
        "max_variants": _i("max_variants", 3),
        "actions_per_day": _i("actions_per_day", 8),
        "tool_call_cap": _i("tool_call_cap", 300),
        "wrong_accusation_score": _f("wrong_accusation_score", -1.0),
        "decoy": _b("decoy", True),
        "known_v": known_v,
    }


def _extract_topics(tools_spec: list[dict[str, Any]]) -> tuple[str, ...]:
    for spec in tools_spec or []:
        if isinstance(spec, dict) and spec.get("name") == "interview":
            props = (spec.get("input_schema") or {}).get("properties") or {}
            enum_vals = (props.get("topic") or {}).get("enum")
            if isinstance(enum_vals, list) and enum_vals:
                return tuple(str(x) for x in enum_vals)
    return DEFAULT_TOPICS


def _is_evasive_answer(text: str) -> bool:
    low = (text or "").lower()
    return any(marker in low for marker in EVASIVE_MARKERS)


def _step_fields(step: Any) -> tuple[int, str, dict[str, Any], dict[str, Any]]:
    if hasattr(step, "tool"):
        day = int(getattr(step, "day", 1))
        tool = str(step.tool)
        args = dict(step.args) if isinstance(step.args, dict) else {}
        res = dict(step.result) if isinstance(step.result, dict) else {}
    else:
        day = int(step.get("day", 1))
        tool = str(step.get("tool", ""))
        args = dict(step.get("args") or {})
        res = dict(step.get("result") or {})
    return day, tool, args, res


class _PublicHistoryTracker:
    def __init__(self) -> None:
        self.employees: list[str] = []
        self.today: int = 1
        self.visible_v: float = 1.0
        self.actions_left: int = 8
        self.calls_left: int = 300
        self.restricted: set[str] = set()
        self.docs: dict[str, dict[str, Any]] = {}
        self.feed_items: dict[str, dict[str, Any]] = {}
        self.logged_days: set[int] = set()
        self.after_hours: dict[str, int] = {}
        self.seen_msg_ids: set[str] = set()
        self.angry_msgs: dict[str, int] = {}
        self.queries_done: set[str] = set()
        self.seen_interviews: set[tuple[int, str, str]] = set()
        self.interviews_total: dict[str, int] = {}
        self.interviews_evasive: dict[str, int] = {}
        self.seen_steps: int = 0

    def ingest_steps(self, history: list[Any]) -> None:
        if len(history) < self.seen_steps:
            self.__init__()
        for idx in range(self.seen_steps, len(history)):
            self._ingest_one(history[idx])
        self.seen_steps = len(history)

    def _ingest_one(self, step: Any) -> None:
        step_day, tool, args, res = _step_fields(step)
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        if not isinstance(data, dict):
            return
        if tool == "list_employees":
            emps = data.get("employees") or []
            self.employees = [
                str(e["id"]) if isinstance(e, dict) else str(e)
                for e in emps
                if (isinstance(e, dict) and "id" in e) or isinstance(e, str)
            ]
            for emp in self.employees:
                self.after_hours.setdefault(emp, 0)
                self.angry_msgs.setdefault(emp, 0)
                self.interviews_total.setdefault(emp, 0)
                self.interviews_evasive.setdefault(emp, 0)
        elif tool == "status":
            self.today = int(data.get("day", self.today))
            self.visible_v = float(data.get("V", self.visible_v))
            self.actions_left = int(data.get("actions_left_today", self.actions_left))
            self.calls_left = int(data.get("tool_calls_left", self.calls_left))
            self.restricted = set(str(x) for x in (data.get("restricted") or []))
        elif tool == "list_documents":
            for doc in data.get("documents") or []:
                if not isinstance(doc, dict) or "doc_id" not in doc:
                    continue
                did = str(doc["doc_id"])
                var_raw = doc.get("variants")
                emp_to_var: dict[str, str] = {}
                if isinstance(var_raw, dict):
                    for k, v in var_raw.items():
                        if isinstance(v, list):
                            for emp in v:
                                emp_to_var[str(emp)] = str(k)
                        elif isinstance(v, str):
                            emp_to_var[str(k)] = v
                if not emp_to_var and did in self.docs:
                    emp_to_var = dict(self.docs[did].get("variants") or {})
                self.docs[did] = {
                    "doc_id": did,
                    "day": int(doc.get("day", self.today)),
                    "recipients": frozenset(str(x) for x in (doc.get("recipients") or [])),
                    "is_canary": bool(doc.get("is_canary", False)),
                    "variants": emp_to_var,
                }
        elif tool == "plant_canary":
            cid = str(data.get("canary_id") or "")
            asg = args.get("assignment") or {}
            if cid and isinstance(asg, dict):
                emp_map = {str(e): str(v) for e, v in asg.items()}
                self.docs[cid] = {
                    "doc_id": cid,
                    "day": step_day,
                    "recipients": frozenset(emp_map.keys()),
                    "is_canary": True,
                    "variants": emp_map,
                }
        elif tool == "check_leak_feed":
            for it in data.get("items") or []:
                if not isinstance(it, dict) or "doc_id" not in it:
                    continue
                did = str(it["doc_id"])
                self.feed_items[did] = {
                    "doc_id": did,
                    "surfaced_day": int(it.get("surfaced_day", self.today)),
                    "variant": str(it["variant"]) if it.get("variant") is not None else None,
                }
        elif tool == "read_access_logs":
            d_from = int(args.get("day_from", 1))
            d_to = int(args.get("day_to", d_from))
            if args.get("employee") is None:
                new_days = set(range(d_from, d_to + 1)) - self.logged_days
                for entry in data.get("logs") or []:
                    if not isinstance(entry, dict):
                        continue
                    ed = int(entry.get("day", 0))
                    emp = str(entry.get("employee", ""))
                    if ed in new_days and entry.get("after_hours") and emp:
                        self.after_hours[emp] = self.after_hours.get(emp, 0) + 1
                self.logged_days.update(new_days)
        elif tool == "search_messages":
            q = str(args.get("query", "")).strip().lower()
            if q:
                self.queries_done.add(q)
            if any(aq in q or q in aq for aq in ANGER_QUERIES):
                for msg in data.get("messages") or []:
                    if not isinstance(msg, dict):
                        continue
                    mid = str(msg.get("id", ""))
                    snd = str(msg.get("sender", ""))
                    if mid and mid not in self.seen_msg_ids and snd:
                        self.seen_msg_ids.add(mid)
                        self.angry_msgs[snd] = self.angry_msgs.get(snd, 0) + 1
        elif tool == "interview":
            emp = str(args.get("employee", data.get("employee", "")))
            topic = str(args.get("topic", data.get("topic", "")))
            key = (step_day, emp, topic)
            if emp and key not in self.seen_interviews:
                self.seen_interviews.add(key)
                self.interviews_total[emp] = self.interviews_total.get(emp, 0) + 1
                if _is_evasive_answer(str(data.get("answer", ""))):
                    self.interviews_evasive[emp] = self.interviews_evasive.get(emp, 0) + 1
        elif tool == "restrict_access":
            emp = str(args.get("employee", ""))
            if emp:
                self.restricted.add(emp)
        elif tool == "unrestrict_access":
            emp = str(args.get("employee", ""))
            if emp:
                self.restricted.discard(emp)
        elif tool == "advance_day":
            if "day" in data:
                self.today = int(data["day"])
            if "V" in data:
                self.visible_v = float(data["V"])

    def extract_features(self) -> dict[str, tuple[int, int, int, int, int, int]]:
        feats: dict[str, tuple[int, int, int, int, int, int]] = {}
        surfaced = sorted(self.feed_items.values(), key=lambda x: (x["surfaced_day"], x["doc_id"]))
        for emp in self.employees:
            c_hit = 0
            c_miss = 0
            d_hit = 0
            for item in surfaced:
                doc = self.docs.get(item["doc_id"])
                if doc is None:
                    continue
                if emp in doc["recipients"]:
                    d_hit += 1
                    if doc["is_canary"] and item["variant"] is not None and doc["variants"]:
                        if doc["variants"].get(emp) == item["variant"]:
                            c_hit += 1
                        else:
                            c_miss += 1
            feats[emp] = (
                c_hit,
                c_miss,
                d_hit,
                self.after_hours.get(emp, 0),
                self.interviews_evasive.get(emp, 0),
                self.angry_msgs.get(emp, 0),
            )
        return feats


class CompactEmpiricalBayesPolicy:
    def __init__(
        self,
        params: CompactEmpiricalBayesParams | None = None,
        seed: int = 0,
        name: str | None = None,
    ) -> None:
        self.params = params if params is not None else make_uncalibrated_params()
        self.seed = int(seed)
        self.name = str(name if name is not None else self.params.stage)
        self.rules: dict[str, Any] = _parse_instruction_rules("")
        self.topics: tuple[str, ...] = DEFAULT_TOPICS
        self.tracker = _PublicHistoryTracker()
        self.queue: list[tuple[str, dict[str, Any]]] = []
        self.planned_day: int = 0

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.rules = _parse_instruction_rules(instruction)
        self.topics = _extract_topics(tools_spec)
        self.tracker = _PublicHistoryTracker()
        self.queue = []
        self.planned_day = 0

    def posterior(self) -> dict[str, float]:
        emps = self.tracker.employees
        if not emps:
            n = max(1, int(self.rules.get("n_employees", 20)))
            return {f"e{i + 1:02d}": 1.0 / n for i in range(n)}
        feats = self.tracker.extract_features()
        p = self.params
        w = (
            p.w_canary_hit,
            p.w_canary_miss,
            p.w_doc_hit,
            p.w_after_hours,
            p.w_evasive,
            p.w_angry_msg,
        )
        logits: list[float] = []
        for emp in emps:
            f_emp = feats[emp]
            logits.append(sum(float(f_emp[i]) * float(w[i]) for i in range(6)))
        max_l = max(logits)
        exps = [math.exp(val - max_l) for val in logits]
        denom = sum(exps)
        return {emp: exps[idx] / denom for idx, emp in enumerate(emps)}

    def estimated_true_v(self) -> float:
        vis_v = float(self.tracker.visible_v)
        disc = float(self.params.unsurfaced_v_discount)
        if disc <= 0.0 or not self.rules.get("known_v", True):
            return max(0.0, vis_v)
        today = self.tracker.today
        p_leak = float(self.rules["p_leak"])
        delays = self.rules["delay_choices"]
        n_del = max(1, len(delays))
        pending = 0.0
        for d in range(1, today):
            frac_unsurfaced = sum(1 for dl in delays if d + dl > today) / n_del
            pending += p_leak * frac_unsurfaced
        return max(0.0, vis_v - disc * float(self.rules["leak_damage"]) * pending)

    def decision_metrics(self) -> dict[str, Any]:
        post = self.posterior()
        ranked = sorted(post.items(), key=lambda kv: (-kv[1], kv[0]))
        top_emp, top_p = ranked[0]
        v_hat = self.estimated_true_v()
        w_wrong = float(self.rules["wrong_accusation_score"])
        denom = v_hat - w_wrong
        breakeven_p = (-w_wrong / denom) if denom > 1e-9 else 1.0
        ev_accuse = top_p * v_hat + (1.0 - top_p) * w_wrong
        return {
            "day": self.tracker.today,
            "top_emp": top_emp,
            "top_p": top_p,
            "v_hat": v_hat,
            "breakeven_p": breakeven_p,
            "ev_accuse": ev_accuse,
            "post": post,
        }

    def _should_accuse(self, dm: dict[str, Any]) -> bool:
        top_p = float(dm["top_p"])
        v_hat = float(dm["v_hat"])
        ev_acc = float(dm["ev_accuse"])
        n_days = int(self.rules["n_days"])
        today = int(dm["day"])
        if not self.params.use_ev_stopping:
            return top_p >= float(self.params.naive_p_threshold)
        if today >= n_days:
            return ev_acc > 0.0
        required_ev = float(self.params.tau_margin) * v_hat
        return ev_acc > 0.0 and ev_acc >= required_ev

    def _plan_canaries(self, post: dict[str, float]) -> list[dict[str, str]]:
        today = self.tracker.today
        n_days = int(self.rules["n_days"])
        min_delay = min(self.rules["delay_choices"])
        if self.params.use_ev_stopping and today + min_delay > n_days:
            return []
        alive = [
            e
            for e in self.tracker.employees
            if post.get(e, 0.0) > 1e-4 and e not in self.tracker.restricted
        ]
        if len(alive) <= 1:
            return []
        cpd = max(1, int(self.rules["canaries_per_day"]))
        k = max(2, int(self.rules["max_variants"]))
        n_total = max(1, len(self.tracker.employees))
        cov = float(self.params.canary_coverage)
        if cov <= 0.0:
            return []
        tiny_sz = int(self.params.tiny_pool_size)

        chosen: list[dict[str, str]] = []
        used_today: set[str] = set()
        for ci in range(cpd):
            rng = random.Random(f"eb_canary:{self.seed}:{today}:{ci}:{len(self.tracker.feed_items)}")
            tie = {e: rng.random() for e in alive}
            ranked = sorted(alive, key=lambda e: (-round(post[e], 5), tie[e]))

            cum = 0.0
            core90: list[str] = []
            for e in ranked:
                core90.append(e)
                cum += post[e]
                if cum >= 0.90:
                    break

            if tiny_sz > 0 and len(core90) <= tiny_sz:
                if ci == 0:
                    if len(core90) <= k:
                        need = max(2, len(core90))
                        pool = ranked[: min(len(ranked), min(k, need))]
                    elif cpd >= 2:
                        pool = core90[:k]
                    else:
                        pool = list(core90)
                else:
                    rest = [e for e in ranked if e not in used_today and post[e] >= 0.01]
                    if len(rest) >= 2:
                        pool = rest[:k]
                    else:
                        need = max(2, min(k, len(core90)))
                        pool = ranked[: min(len(ranked), need)]
                        ng = min(k, len(pool))
                        asg_shift = {e: LABELS[(idx + ci) % ng] for idx, e in enumerate(pool)}
                        if len(set(asg_shift.values())) >= 2:
                            chosen.append(asg_shift)
                            used_today.update(asg_shift.keys())
                        continue
            else:
                untested = [e for e in ranked if e not in used_today]
                tested = [e for e in ranked if e in used_today]
                priority = untested + tested
                max_count = (
                    n_total
                    if cov >= 0.999
                    else max(k, min(n_total - 1, int(round(cov * n_total))))
                )
                pool = []
                mass_acc = 0.0
                for e in priority:
                    if len(pool) >= max_count:
                        break
                    if len(pool) >= min(k, len(priority)) and mass_acc >= cov - 1e-9:
                        break
                    pool.append(e)
                    mass_acc += post[e]
                if len(pool) < 2:
                    pool = priority[: min(2, len(priority))]

            ng = min(k, len(pool))
            if ng < 2:
                continue
            grp_mass = [0.0] * ng
            groups: list[list[str]] = [[] for _ in range(ng)]
            for e in pool:
                g_idx = min(range(ng), key=lambda idx: (grp_mass[idx], len(groups[idx])))
                groups[g_idx].append(e)
                grp_mass[g_idx] += post[e]
            asg = {e: LABELS[g_idx] for g_idx, grp in enumerate(groups) for e in grp}
            if asg:
                chosen.append(asg)
                used_today.update(asg.keys())
        return chosen

    def _pick_interview(self, post: dict[str, float]) -> tuple[str, dict[str, Any]] | None:
        emps = self.tracker.employees
        if not emps:
            return None
        today = self.tracker.today
        ranked = sorted(emps, key=lambda e: (-post.get(e, 0.0), e))
        for emp in ranked[:6]:
            for topic in self.topics:
                if (today, emp, topic) not in self.tracker.seen_interviews:
                    return ("interview", {"employee": emp, "topic": topic})
        return None

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        self.tracker.ingest_steps(history)
        if not self.tracker.employees:
            return ("list_employees", {})
        if self.queue:
            nxt_tool, nxt_args = self.queue.pop(0)
            if nxt_tool == "__decide__":
                return self._decide_step()
            return (nxt_tool, nxt_args)

        today = self.tracker.today
        if self.planned_day != today:
            self.planned_day = today
            q: list[tuple[str, dict[str, Any]]] = [
                ("status", {}),
                ("list_documents", {}),
                ("check_leak_feed", {}),
            ]
            prev_day = today - 1
            if prev_day >= 1 and prev_day not in self.tracker.logged_days:
                q.append(("read_access_logs", {"day_from": prev_day, "day_to": prev_day}))
            if self.rules.get("decoy", True) and today >= 2:
                pending_q = [w for w in ANGER_QUERIES if w not in self.tracker.queries_done][:3]
                for w in pending_q:
                    q.append(("search_messages", {"query": w}))
            q.append(("__decide__", {}))
            self.queue = q
            return self.queue.pop(0)

        return ("advance_day", {})

    def _decide_step(self) -> tuple[str, dict[str, Any]]:
        dm = self.decision_metrics()
        if self._should_accuse(dm):
            self.queue = []
            return ("accuse", {"employee": str(dm["top_emp"])})

        post = dm["post"]
        actions_used_est = 1
        if self.tracker.today >= 2:
            actions_used_est += 1
        if self.rules.get("decoy", True) and self.tracker.today in (2, 3):
            actions_used_est += 3

        canaries = self._plan_canaries(post)
        q: list[tuple[str, dict[str, Any]]] = []
        for idx, asg in enumerate(canaries):
            if actions_used_est < int(self.rules["actions_per_day"]):
                suffix = f" ({idx + 1})" if idx > 0 else ""
                q.append(
                    (
                        "plant_canary",
                        {
                            "doc_title": f"Audit brief day {self.tracker.today}{suffix}",
                            "assignment": asg,
                        },
                    )
                )
                actions_used_est += 1

        if actions_used_est < int(self.rules["actions_per_day"]) and self.tracker.today not in (2, 3):
            iv = self._pick_interview(post)
            if iv is not None:
                q.append(iv)
                actions_used_est += 1

        q.append(("advance_day", {}))
        self.queue = q
        return self.queue.pop(0)


class _TrainExplorationPolicy:
    name = "eb_explorer"

    def __init__(self, seed: int) -> None:
        self.seed = assert_strict_train_seed(seed)
        self.rules: dict[str, Any] = _parse_instruction_rules("")
        self.topics: tuple[str, ...] = DEFAULT_TOPICS
        self.tracker = _PublicHistoryTracker()
        self.queue: list[tuple[str, dict[str, Any]]] = []
        self.planned_day: int = 0
        self.iv_cursor: int = 0

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.rules = _parse_instruction_rules(instruction)
        self.topics = _extract_topics(tools_spec)
        self.tracker = _PublicHistoryTracker()
        self.queue = []
        self.planned_day = 0
        self.iv_cursor = 0

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        self.tracker.ingest_steps(history)
        if not self.tracker.employees:
            return ("list_employees", {})
        if self.queue:
            tool, args = self.queue.pop(0)
            if tool == "__explore_decide__":
                return self._explore_decide()
            return (tool, args)
        today = self.tracker.today
        if self.planned_day != today:
            self.planned_day = today
            q: list[tuple[str, dict[str, Any]]] = [
                ("status", {}),
                ("list_documents", {}),
                ("check_leak_feed", {}),
            ]
            if today >= 2 and (today - 1) not in self.tracker.logged_days:
                q.append(("read_access_logs", {"day_from": today - 1, "day_to": today - 1}))
            if today >= 2:
                for w in [w for w in ANGER_QUERIES if w not in self.tracker.queries_done][:3]:
                    q.append(("search_messages", {"query": w}))
            q.append(("__explore_decide__", {}))
            self.queue = q
            return self.queue.pop(0)
        return ("advance_day", {})

    def _explore_decide(self) -> tuple[str, dict[str, Any]]:
        today = self.tracker.today
        n_days = int(self.rules["n_days"])
        emps = self.tracker.employees
        feats = self.tracker.extract_features()
        if today >= n_days:
            if self.seed % 10 == 0:
                angry = [e for e in emps if feats[e][5] > 0]
                if angry:
                    target = max(angry, key=lambda e: (feats[e][5], feats[e][3], e))
                else:
                    target = max(emps, key=lambda e: (feats[e][3], e))
            else:
                target = max(
                    emps,
                    key=lambda e: (
                        feats[e][2] * 3 + feats[e][0] * 2 - feats[e][1] * 2 - feats[e][5] * 4,
                        -emps.index(e),
                    ),
                )
            return ("accuse", {"employee": target})

        cpd = max(1, int(self.rules["canaries_per_day"]))
        k = max(2, int(self.rules["max_variants"]))
        q: list[tuple[str, dict[str, Any]]] = []
        used_actions = 1 + (1 if today >= 2 else 0) + (3 if today in (2, 3) else 0)
        used_today: set[str] = set()
        for ci in range(cpd):
            if used_actions >= int(self.rules["actions_per_day"]):
                break
            rng = random.Random(f"eb_exp:{self.seed}:{today}:{ci}")
            if today <= n_days // 2:
                order = [e for e in emps if e not in used_today]
                rng.shuffle(order)
                take = max(k, int(round(0.45 * len(emps))))
                pool = order[: min(len(order), take)]
            else:
                scored = sorted(
                    emps,
                    key=lambda e: (
                        -(feats[e][2] * 3 + feats[e][0] * 2 - feats[e][1] * 2),
                        e in used_today,
                        rng.random(),
                    ),
                )
                take = max(2, min(k * 2, len(emps) // 3))
                pool = scored[:take]
            ng = min(k, len(pool))
            if ng >= 2:
                asg = {e: LABELS[idx % ng] for idx, e in enumerate(pool)}
                suffix = f" ({ci + 1})" if ci > 0 else ""
                q.append(("plant_canary", {"doc_title": f"Review packet {today}{suffix}", "assignment": asg}))
                used_today.update(pool)
                used_actions += 1

        while used_actions < min(int(self.rules["actions_per_day"]), 7):
            emp = emps[self.iv_cursor % len(emps)]
            topic = self.topics[(self.iv_cursor // max(1, len(emps))) % len(self.topics)]
            self.iv_cursor += 1
            if (today, emp, topic) not in self.tracker.seen_interviews:
                q.append(("interview", {"employee": emp, "topic": topic}))
                used_actions += 1
            if self.iv_cursor > len(emps) * len(self.topics) * 2:
                break

        q.append(("advance_day", {}))
        self.queue = q
        return self.queue.pop(0)


def fit_likelihood_weights_on_train_seeds(
    seeds: list[int],
    laplace_alpha: float = 1.0,
) -> CompactEmpiricalBayesParams:
    for s in seeds:
        assert_strict_train_seed(s)

    can_exp = [0, 0]
    can_hit = [0, 0]
    can_miss = [0, 0]
    doc_exp = [0, 0]
    doc_hit = [0, 0]
    ah_days = [0, 0]
    ah_cnt = [0, 0]
    inn_ah_obs: list[tuple[int, int]] = []
    iv_exp = [0, 0]
    iv_ev = [0, 0]
    ang_eps = [0, 0]
    ang_cnt = [0, 0]

    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        explorer = _TrainExplorationPolicy(seed=seed)
        ep = run_episode(Env(tier, seed), explorer)
        tr = explorer.tracker
        tr.ingest_steps(list(ep.steps))
        feats = tr.extract_features()
        if not (ep.accused and ep.correct):
            continue
        chosen_id = str(ep.accused)
        n_surfaced = len(tr.feed_items)
        n_log_days = len(tr.logged_days)
        did_msg_search = bool(tr.queries_done)
        for emp in tr.employees:
            y = 1 if emp == chosen_id else 0
            c_h, c_m, d_h, ah, ev, ang = feats[emp]
            can_exp[y] += c_h + c_m
            can_hit[y] += c_h
            can_miss[y] += c_m
            doc_exp[y] += n_surfaced
            doc_hit[y] += d_h
            ah_days[y] += n_log_days
            ah_cnt[y] += ah
            if y == 0 and n_log_days > 0:
                inn_ah_obs.append((ah, n_log_days))
            iv_exp[y] += tr.interviews_total.get(emp, 0)
            iv_ev[y] += ev
            if did_msg_search:
                ang_eps[y] += 1
                ang_cnt[y] += ang

    a = float(laplace_alpha)
    p_chit_1 = (can_hit[1] + a) / max(2.0 * a, can_exp[1] + 2.0 * a)
    p_chit_0 = (can_hit[0] + a) / max(2.0 * a, can_exp[0] + 2.0 * a)
    p_cmiss_1 = (can_miss[1] + a) / max(2.0 * a, can_exp[1] + 2.0 * a)
    p_cmiss_0 = (can_miss[0] + a) / max(2.0 * a, can_exp[0] + 2.0 * a)
    w_canary_hit = math.log(p_chit_1 / p_chit_0)
    w_canary_miss = math.log(p_cmiss_1 / p_cmiss_0)

    p_doc_1 = min(1.0 - 1e-6, max(1e-6, (doc_hit[1] + a) / max(2.0 * a, doc_exp[1] + 2.0 * a)))
    p_doc_0 = min(1.0 - 1e-6, max(1e-6, (doc_hit[0] + a) / max(2.0 * a, doc_exp[0] + 2.0 * a)))
    w_doc_hit = math.log((p_doc_1 * (1.0 - p_doc_0)) / ((1.0 - p_doc_1) * p_doc_0))

    r_ah_1 = (ah_cnt[1] + a) / max(a, ah_days[1] + a)
    r_ah_0 = (ah_cnt[0] + a) / max(a, ah_days[0] + a)
    if inn_ah_obs:
        pearson_sq = [
            ((k_ah - r_ah_0 * d_obs) ** 2) / max(1e-6, r_ah_0 * d_obs)
            for k_ah, d_obs in inn_ah_obs
        ]
        fano_inn_ah = max(1.0, sum(pearson_sq) / len(pearson_sq))
    else:
        fano_inn_ah = 1.0
    w_after_hours = math.log(r_ah_1 / r_ah_0) / fano_inn_ah

    p_ev_1 = (iv_ev[1] + a) / max(2.0 * a, iv_exp[1] + 2.0 * a)
    p_ev_0 = (iv_ev[0] + a) / max(2.0 * a, iv_exp[0] + 2.0 * a)
    w_evasive = math.log(p_ev_1 / p_ev_0)

    r_ang_1 = (ang_cnt[1] + a) / max(2.0 * a, ang_eps[1] + 2.0 * a)
    r_ang_0 = (ang_cnt[0] + a) / max(2.0 * a, ang_eps[0] + 2.0 * a)
    w_angry_msg = math.log(r_ang_1 / r_ang_0)

    return CompactEmpiricalBayesParams(
        w_canary_hit=w_canary_hit,
        w_canary_miss=w_canary_miss,
        w_doc_hit=w_doc_hit,
        w_after_hours=w_after_hours,
        w_evasive=w_evasive,
        w_angry_msg=w_angry_msg,
        tau_margin=0.0,
        unsurfaced_v_discount=0.0,
        canary_coverage=0.90,
        tiny_pool_size=0,
        use_ev_stopping=False,
        naive_p_threshold=0.50,
        stage="stage2_likelihood_only",
    )


def _eval_on_train_slice(params: CompactEmpiricalBayesParams, seeds: list[int]) -> tuple[float, float]:
    total_score = 0.0
    wrong_cnt = 0
    for idx, seed in enumerate(seeds):
        assert_strict_train_seed(seed)
        tier = TIERS[idx % len(TIERS)]
        ep = run_episode(Env(tier, seed), CompactEmpiricalBayesPolicy(params, seed=seed))
        total_score += float(ep.score)
        if ep.accused is not None and not ep.correct:
            wrong_cnt += 1
    n = max(1, len(seeds))
    return round(total_score / n, 6), round(wrong_cnt / n, 6)


def fit_compact_empirical_bayes_from_train_seeds(
    stage2_seeds: list[int] | None = None,
    stage3_seeds: list[int] | None = None,
) -> CompactEmpiricalBayesParams:
    s2 = stage2_seeds if stage2_seeds is not None else list(range(*STAGE2_TRAIN_SLICE))
    s3 = stage3_seeds if stage3_seeds is not None else list(range(*STAGE3_TRAIN_SLICE))
    if set(s2) & set(s3):
        raise ValueError("stage2 and stage3 train slices must be disjoint")
    like_params = fit_likelihood_weights_on_train_seeds(s2, laplace_alpha=1.0)
    half = max(3, len(s3) // 2)
    split_a = s3[:half]
    split_b = s3[half:] if len(s3) > half else s3

    best_cov, best_tiny = 0.55, 4
    best_split_key = (-1e9, -1e9)
    for cov, tiny_sz in ((0.90, 0), (0.65, 3), (0.55, 4), (0.45, 6), (0.35, 6)):
        cand = CompactEmpiricalBayesParams(
            w_canary_hit=like_params.w_canary_hit,
            w_canary_miss=like_params.w_canary_miss,
            w_doc_hit=like_params.w_doc_hit,
            w_after_hours=like_params.w_after_hours,
            w_evasive=like_params.w_evasive,
            w_angry_msg=like_params.w_angry_msg,
            tau_margin=0.65,
            unsurfaced_v_discount=1.0,
            canary_coverage=cov,
            tiny_pool_size=tiny_sz,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="search",
        )
        mean_sc, wrong_rate = _eval_on_train_slice(cand, split_a)
        key = (mean_sc, -wrong_rate)
        if key > best_split_key:
            best_split_key = key
            best_cov, best_tiny = cov, tiny_sz

    best_tau = 0.65
    best_tau_key = (-1e9, -1e9)
    for tau in (0.0, 0.30, 0.50, 0.65, 0.75, 0.85):
        cand = CompactEmpiricalBayesParams(
            w_canary_hit=like_params.w_canary_hit,
            w_canary_miss=like_params.w_canary_miss,
            w_doc_hit=like_params.w_doc_hit,
            w_after_hours=like_params.w_after_hours,
            w_evasive=like_params.w_evasive,
            w_angry_msg=like_params.w_angry_msg,
            tau_margin=tau,
            unsurfaced_v_discount=1.0,
            canary_coverage=best_cov,
            tiny_pool_size=best_tiny,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="search",
        )
        mean_sc, wrong_rate = _eval_on_train_slice(cand, split_b)
        key = (mean_sc, -wrong_rate)
        if key > best_tau_key:
            best_tau_key = key
            best_tau = tau

    best_disc = 1.00
    best_disc_key = (-1e9, -1e9, -1e9)
    for disc in (0.0, 0.50, 1.00, 1.25):
        cand = CompactEmpiricalBayesParams(
            w_canary_hit=like_params.w_canary_hit,
            w_canary_miss=like_params.w_canary_miss,
            w_doc_hit=like_params.w_doc_hit,
            w_after_hours=like_params.w_after_hours,
            w_evasive=like_params.w_evasive,
            w_angry_msg=like_params.w_angry_msg,
            tau_margin=best_tau,
            unsurfaced_v_discount=disc,
            canary_coverage=best_cov,
            tiny_pool_size=best_tiny,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="search",
        )
        mean_sc, wrong_rate = _eval_on_train_slice(cand, split_b)
        key = (mean_sc, -wrong_rate, -abs(disc - 1.0))
        if key > best_disc_key:
            best_disc_key = key
            best_disc = disc

    return CompactEmpiricalBayesParams(
        w_canary_hit=like_params.w_canary_hit,
        w_canary_miss=like_params.w_canary_miss,
        w_doc_hit=like_params.w_doc_hit,
        w_after_hours=like_params.w_after_hours,
        w_evasive=like_params.w_evasive,
        w_angry_msg=like_params.w_angry_msg,
        tau_margin=best_tau,
        unsurfaced_v_discount=best_disc,
        canary_coverage=best_cov,
        tiny_pool_size=best_tiny,
        use_ev_stopping=True,
        naive_p_threshold=0.50,
        stage="after_trained",
    )


def _format_step_summary(tool: str, args: dict[str, Any], ok: bool, data: dict[str, Any], vis_v: float, step_day: int, env_day: int) -> str:
    if tool == "accuse":
        return "accuse([SEALED])"
    if not ok:
        return f"{tool} err"
    if tool == "list_employees":
        emps = data.get("employees") or []
        return f"staff ({len(emps)})"
    if tool == "status":
        al = data.get("actions_left_today", 0)
        return f"d{step_day} V={vis_v:.2f} left={al}"
    if tool == "list_documents":
        docs = data.get("documents") or []
        return f"docs ({len(docs)})"
    if tool == "check_leak_feed":
        items = data.get("items") or []
        if not items:
            return "feed: 0"
        parts = [
            f"{it['doc_id']}[{it['variant']}]" if it.get("variant") else str(it.get("doc_id", "doc"))
            for it in items[-2:]
            if isinstance(it, dict)
        ]
        return f"feed: {len(items)} ({','.join(parts)})"
    if tool == "read_access_logs":
        logs = data.get("logs") or []
        ah = sum(1 for row in logs if isinstance(row, dict) and row.get("after_hours"))
        d_from = args.get("day_from", step_day)
        d_to = args.get("day_to", d_from)
        span = f"d{d_from}" if d_from == d_to else f"d{d_from}..d{d_to}"
        return f"logs {span}: {len(logs)} ({ah} AH)"
    if tool == "search_messages":
        msgs = data.get("messages") or []
        q = str(args.get("query", ""))
        return f"msg '{q}': {len(msgs)}"
    if tool == "read_message":
        return f"msg {args.get('message_id', '')}"
    if tool == "plant_canary":
        cid = str(data.get("canary_id") or data.get("doc_id") or "canary")
        asg = args.get("assignment") or {}
        n_vars = len(set(asg.values())) if isinstance(asg, dict) else 0
        n_rec = len(asg) if isinstance(asg, dict) else 0
        return f"canary {cid} ({n_rec}r, {n_vars}v)"
    if tool == "interview":
        emp = str(args.get("employee", ""))
        tag = "evasive" if _is_evasive_answer(str(data.get("answer", ""))) else "direct"
        return f"iv {emp}: {tag}"
    if tool == "restrict_access":
        return f"restrict {args.get('employee', '')}"
    if tool == "unrestrict_access":
        return f"unrestrict {args.get('employee', '')}"
    if tool == "advance_day":
        next_day = data.get("day", env_day)
        return f"d{next_day} V={vis_v:.2f}"
    return tool


def _solver_step_metrics(observer: SolverPolicy, env: Env) -> tuple[float, float]:
    observer._ingest(env.history[-1])
    observer.seen = len(env.history)
    if observer.obs.employees:
        post = observer.belief()
        top_p = max(post.values()) if post else (1.0 / max(1, env.p.n_employees))
        v_hat = observer.expected_true_V()
    else:
        top_p = 1.0 / max(1, env.p.n_employees)
        v_hat = env.visible_V()
    w_wrong = float(env.p.wrong_accusation_score)
    denom = v_hat - w_wrong
    breakeven_p = (-w_wrong / denom) if denom > 1e-9 else 1.0
    return round(float(top_p), 3), round(float(breakeven_p), 3)


def _eb_step_metrics(observer: CompactEmpiricalBayesPolicy, env: Env) -> tuple[float, float]:
    observer.tracker.ingest_steps(list(env.history))
    dm = observer.decision_metrics()
    return round(float(dm["top_p"]), 3), round(float(dm["breakeven_p"]), 3)


def run_and_build_verified_trace(
    tier: str,
    seed: int,
    agent_name: str,
    trained_params: CompactEmpiricalBayesParams,
    seed_split_note: str,
) -> dict[str, Any]:
    if agent_name == "before_uncalibrated":
        uncal = make_uncalibrated_params()
        policy: Any = CompactEmpiricalBayesPolicy(uncal, seed=seed, name=agent_name)
    elif agent_name == "after_trained":
        policy = CompactEmpiricalBayesPolicy(trained_params, seed=seed, name=agent_name)
    elif agent_name == "solver_reference":
        policy = SolverPolicy()
    else:
        raise ValueError(f"unsupported agent_name: {agent_name}")

    ep = run_episode(Env(tier, seed), policy)

    replay_env = Env(tier, seed)
    if agent_name == "solver_reference":
        sol_obs = SolverPolicy()
        sol_obs.reset(replay_env.tools_spec(), replay_env.instruction())
        eb_obs = None
    else:
        sol_obs = None
        obs_params = make_uncalibrated_params() if agent_name == "before_uncalibrated" else trained_params
        eb_obs = CompactEmpiricalBayesPolicy(obs_params, seed=seed, name=agent_name)
        eb_obs.reset(replay_env.tools_spec(), replay_env.instruction())

    trace_steps: list[dict[str, Any]] = []
    for call_idx, st in enumerate(ep.steps):
        if int(st.t) != call_idx:
            raise AssertionError(f"step call_idx mismatch at {tier}:{seed}:{agent_name}: {st.t} != {call_idx}")
        step_day = replay_env.day
        if int(st.day) != step_day:
            raise AssertionError(f"step day mismatch at {tier}:{seed}:{agent_name}: {st.day} != {step_day}")
        tool = str(st.tool)
        raw_args = dict(st.args) if isinstance(st.args, dict) else {}
        live_res = replay_env.call(tool, raw_args)
        rec_ok = bool((st.result or {}).get("ok"))
        if bool(live_res.ok) != rec_ok:
            raise AssertionError(f"replay ok mismatch at {tier}:{seed}:{agent_name} step {call_idx} ({tool})")

        vis_v = replay_env.visible_V()
        if sol_obs is not None:
            top_p, breakeven_p = _solver_step_metrics(sol_obs, replay_env)
        else:
            assert eb_obs is not None
            top_p, breakeven_p = _eb_step_metrics(eb_obs, replay_env)

        args_out = {"employee_id": "[SEALED]"} if tool == "accuse" else raw_args
        data_dict = live_res.data if isinstance(live_res.data, dict) else {}
        summary = _format_step_summary(
            tool=tool,
            args=raw_args,
            ok=bool(live_res.ok),
            data=data_dict,
            vis_v=vis_v,
            step_day=step_day,
            env_day=replay_env.day,
        )
        trace_steps.append(
            {
                "day": int(step_day),
                "call_idx": int(call_idx),
                "tool": tool,
                "args": args_out,
                "ok": bool(live_res.ok),
                "summary": summary,
                "V": vis_v,
                "top_p": top_p,
                "breakeven_p": breakeven_p,
            }
        )

    replayed = replay_env.result(agent_name)
    if abs(float(replayed.score) - float(ep.score)) > 1e-9:
        raise AssertionError(f"replay terminal score mismatch at {tier}:{seed}:{agent_name}")
    if replayed.accused != ep.accused or bool(replayed.correct) != bool(ep.correct):
        raise AssertionError(f"replay terminal verdict mismatch at {tier}:{seed}:{agent_name}")
    if int(replayed.final_day) != int(ep.final_day) or str(replayed.end_reason) != str(ep.end_reason):
        raise AssertionError(f"replay terminal day/reason mismatch at {tier}:{seed}:{agent_name}")

    return {
        "seed": int(seed),
        "tier": str(tier),
        "agent": str(agent_name),
        "seed_split_note": str(seed_split_note),
        "steps": trace_steps,
        "final": {
            "accused": ep.accused,
            "correct": bool(ep.correct),
            "final_day": int(ep.final_day),
            "tool_calls": len(trace_steps),
            "score": round(float(ep.score), 4),
            "end_reason": str(ep.end_reason),
        },
    }


@contextlib.contextmanager
def _heldout_secret_scope() -> Iterator[str]:
    secret_bytes = HELDOUT_EVAL_TAG.encode("utf-8")
    tag = "sha256:" + hashlib.sha256(secret_bytes).hexdigest()[:16]
    if tag != EXPECTED_WORLD_SECRET_TAG:
        raise AssertionError(f"unexpected heldout world_secret_tag {tag}")
    prev = canary_world._SET_SECRET
    canary_world.set_world_secret(secret_bytes)
    try:
        yield tag
    finally:
        canary_world.set_world_secret(prev)


def verify_in_memory_heldout_parity(trained_params: CompactEmpiricalBayesParams) -> dict[str, Any]:
    with _heldout_secret_scope() as secret_tag:
        before_scores: list[float] = []
        after_scores: list[float] = []
        solver_scores: list[float] = []
        episodes_checked = 0
        for tier in TIERS:
            for seed in HELDOUT_PARITY_SEEDS:
                if seed not in HELDOUT_SEEDS:
                    raise AssertionError(f"parity seed {seed} outside HELDOUT_SEEDS")
                for agent_name in AGENT_ORDER:
                    tr = run_and_build_verified_trace(
                        tier=tier,
                        seed=seed,
                        agent_name=agent_name,
                        trained_params=trained_params,
                        seed_split_note="in_memory_heldout_parity_only",
                    )
                    episodes_checked += 1
                    sc = float(tr["final"]["score"])
                    if agent_name == "before_uncalibrated":
                        before_scores.append(sc)
                    elif agent_name == "after_trained":
                        after_scores.append(sc)
                    else:
                        solver_scores.append(sc)
        n = len(before_scores)
        return {
            "world_secret_tag": secret_tag,
            "seeds_verified": list(HELDOUT_PARITY_SEEDS),
            "tiers_verified": list(TIERS),
            "episodes_verified": episodes_checked,
            "before_mean_score": round(sum(before_scores) / n, 4),
            "after_mean_score": round(sum(after_scores) / n, 4),
            "solver_mean_score": round(sum(solver_scores) / n, 4),
            "paired_mean_delta": round(sum(a - b for a, b in zip(after_scores, before_scores)) / n, 4),
        }


def build_ledger_summary_payload() -> dict[str, Any]:
    open_weight_runs: list[dict[str, Any]] = [
        {
            "run_id": "J4-pilot-44200",
            "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (pilot)",
            "method": "SFT prefix 4k pilot tokenization on 20k J3 episodes",
            "tiers_version": "v1.0",
            "context_len": 4096,
            "heldout_n": 0,
            "before_mean_score": None,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": None,
            "after_valid_call_rate": None,
            "status": "FAILED_OOM",
            "bar_passed": False,
            "summary": "28 GB Slurm cgroup OOM while tokenizing 20k prefix-window episodes before training started",
        },
        {
            "run_id": "J4-v1-44397",
            "model": "Qwen2.5-1.5B-Instruct LoRA r=16",
            "method": "SFT prefix 4k windows (450 steps, 14.3M tokens on J3v2 v1.3)",
            "tiers_version": "v1.3",
            "context_len": 4096,
            "heldout_n": 12,
            "before_mean_score": 0.0,
            "after_mean_score": -0.25,
            "paired_mean_delta": -0.25,
            "before_valid_call_rate": 0.08,
            "after_valid_call_rate": 0.99,
            "status": "NEGATIVE_REWARD_PROTOCOL_GAIN",
            "bar_passed": False,
            "summary": "Valid call rate rose 0.08 to 0.99, but 4k prefix truncation missed culprit identity (-0.250 vs 0.000)",
        },
        {
            "run_id": "WS4-base-44411",
            "model": "Qwen2.5-1.5B-Instruct (base)",
            "method": "Zero-shot base evaluation at 4k context (max_calls=120)",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 16,
            "before_mean_score": 0.0,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": None,
            "status": "BASELINE_CAVEATED",
            "bar_passed": False,
            "summary": "Untrained base reference (valid call rate 0.03, 16 of 16 hit eval_cap=120 on Day 1 for 0.000)",
        },
        {
            "run_id": "WS4-base-pooled",
            "model": "Qwen2.5-1.5B-Instruct (base, pooled)",
            "method": "Zero-shot base evaluation at 4k context (jobs 44411 n=16 + 44584 n=20)",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 36,
            "before_mean_score": 0.0,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": None,
            "status": "BASELINE_CAVEATED",
            "bar_passed": False,
            "summary": "Pooled untrained base reference n=36 scored 0.000 (0.03 valid call rate, Day 1 cap exhaustion)",
        },
        {
            "run_id": "WS4-v2-44412",
            "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (dense v2)",
            "method": "SFT dense 4k windows + oversample-endings 3 (887 steps on J3v14)",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 82,
            "before_mean_score": 0.0,
            "after_mean_score": -0.395,
            "paired_mean_delta": -0.395,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.92,
            "status": "NEGATIVE_BLIND_ACCUSE",
            "bar_passed": False,
            "summary": "Accuse-only SFT with 3x ending oversampling triggered blind early accusations (-0.395, 0 of 27 hard)",
        },
        {
            "run_id": "WS4-v2-off30-68bb",
            "model": "Qwen2.5-1.5B-Instruct LoRA r=16 (dense v2, off30)",
            "method": "SFT dense 4k + oversample-endings 3 extra shard on Verda A100 68bbe201",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": -0.514,
            "paired_mean_delta": -0.514,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.92,
            "status": "NEGATIVE_BLIND_ACCUSE",
            "bar_passed": False,
            "summary": "Confirmed v2 blind-accuse regression (-0.514 on off30 n=90; pooled v2 n=172 is -0.457, precision 0.09)",
        },
        {
            "run_id": "WS4-v3-44548-44550",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3 GRPO init from 44410)",
            "method": "Decision-point GRPO on 2,000 TRAIN states",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 0,
            "before_mean_score": None,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": None,
            "after_valid_call_rate": None,
            "status": "FAILED_CUDA_OOM",
            "bar_passed": False,
            "summary": "CUDA OOM on V100 32 GB during unchunked group prefill and full-logit sampling at step 0",
        },
        {
            "run_id": "WS4-v3-44553",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3 GRPO unguided)",
            "method": "Decision-point GRPO with gradient checkpointing, unguided sampling",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 0,
            "before_mean_score": None,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": None,
            "after_valid_call_rate": None,
            "status": "FAILED_ZERO_VARIANCE",
            "bar_passed": False,
            "summary": "8 of 10 GRPO groups collapsed to continue_frac=1.0 zero reward variance before guided exploration",
        },
        {
            "run_id": "WS4-v3-4k-s1-714d-spot",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s1 spot replicate)",
            "method": "Guided decision-point GRPO at 4k context on Verda A100 spot 714d8144",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 0,
            "before_mean_score": None,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": None,
            "after_valid_call_rate": None,
            "status": "FAILED_SPOT_PREEMPTED",
            "bar_passed": False,
            "summary": "Verda A100 spot instance preempted ~30 minutes into 4k GRPO replicate s1 with 0 eval episodes",
        },
        {
            "run_id": "WS4-v3-4k-s1-44572",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s1, 192 GRPO steps partial)",
            "method": "Guided decision-point GRPO on V100 job 44572 (4.0h, 192 steps, partial eval 44573)",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 25,
            "before_mean_score": 0.0,
            "after_mean_score": -0.24,
            "paired_mean_delta": -0.24,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.97,
            "status": "NEGATIVE_FLAT_PARTIAL",
            "bar_passed": False,
            "summary": "Partial V100 4k GRPO replicate had flat whom-accuracy (0.22 to 0.27) and scored -0.240 on n=25",
        },
        {
            "run_id": "WS4-v3-verda-s0-eval",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s0, 609 GRPO steps, pooled n=180)",
            "method": "Guided decision-point GRPO on Verda H100 3bb74f5a (609 steps, max_ctx=4096, s0 + off30)",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 180,
            "before_mean_score": 0.0,
            "after_mean_score": -0.147,
            "paired_mean_delta": -0.147,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 1.0,
            "status": "NEGATIVE_4K_TRUNCATION_PERSISTS",
            "bar_passed": False,
            "summary": "Improved +0.310 over v2 via abstention (accused 0.21, valid 1.00) but remained -0.147 vs 0.000 base",
        },
        {
            "run_id": "WS4-v3-4k-s0-ctx8k",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-4k s0 evaluated at max_ctx=8192)",
            "method": "Same 609-step 4k GRPO adapter (3d0cd43b8037) evaluated at 8k context (shared tag 1ca0c2a64d)",
            "tiers_version": "v1.4",
            "context_len": 8192,
            "heldout_n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": -0.716,
            "paired_mean_delta": -0.716,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.99,
            "status": "NEGATIVE_INFERENCE_CTX_CONFOUND",
            "bar_passed": False,
            "summary": "Inference-length confound: raising eval max_ctx 4k to 8k flipped medium/hard accusations to 0.80/0.90 (-0.716)",
        },
        {
            "run_id": "WS4-v3-8k-s1-ac58",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s1, 371 GRPO steps)",
            "method": "Guided decision-point GRPO at 8k context on Verda A100 spot ac58df04 (371 steps)",
            "tiers_version": "v1.4",
            "context_len": 8192,
            "heldout_n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": -0.777,
            "paired_mean_delta": -0.777,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.92,
            "status": "NEGATIVE_OFFPOLICY_OVERACCUSE",
            "bar_passed": False,
            "summary": "Off-policy solver-state GRPO at 8k over-accused on own rollouts (-0.777, accused 0.94, precision 0.09)",
        },
        {
            "run_id": "WS4-v3-8k-s2-dbd0",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s2, 693 GRPO steps)",
            "method": "Guided decision-point GRPO at 8k context on Verda H100 spot dbd083ca (693 steps)",
            "tiers_version": "v1.4",
            "context_len": 8192,
            "heldout_n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": -0.05,
            "paired_mean_delta": -0.05,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.96,
            "status": "NEGATIVE_ABSTAIN_COLLAPSE",
            "bar_passed": False,
            "summary": "693-step 8k GRPO collapsed to 93% abstention (-0.050 +/- 0.049, 6 accused, 1 hit across n=90)",
        },
        {
            "run_id": "WS4-v3-8k-s3-f437",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s3, 344 GRPO steps, shared tag 1ca0c2a64d)",
            "method": "Guided decision-point GRPO at 8k context on Verda A100 f4378173 paired vs v3-4k-s0 at 8k",
            "tiers_version": "v1.4",
            "context_len": 8192,
            "heldout_n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": -0.788,
            "paired_mean_delta": -0.073,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": 0.94,
            "status": "NEGATIVE_PAIRED_8K_NULL",
            "bar_passed": False,
            "summary": "Truly paired 8k vs 4k-at-8k under shared tag 1ca0c2a64d gave -0.073 +/- 0.173 (-0.788 overall)",
        },
        {
            "run_id": "WS4-v3-8k-s0-3bb7",
            "model": "Qwen2.5-1.5B-Instruct LoRA (v3-8k s0, 637 GRPO steps, shared tag 1ca0c2a64d)",
            "method": "Guided decision-point GRPO at 8k context on Verda H100 3bb74f5a (637 steps, shared secret)",
            "tiers_version": "v1.4",
            "context_len": 8192,
            "heldout_n": 90,
            "before_mean_score": 0.0,
            "after_mean_score": -0.06,
            "paired_mean_delta": -0.06,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": None,
            "status": "NEGATIVE_ABSTAIN_COLLAPSE",
            "bar_passed": False,
            "summary": "637-step H100 8k GRPO abstained 0.92 (-0.060 +/- 0.054, n=90; paired +0.728 +/- 0.134 vs s3)",
        },
        {
            "run_id": "WS4-base-backup-18ac",
            "model": "Qwen2.5-1.5B-Instruct (base backup eval)",
            "method": "Backup zero-shot base evaluation on Verda A100 18acfa5d",
            "tiers_version": "v1.4",
            "context_len": 4096,
            "heldout_n": 0,
            "before_mean_score": None,
            "after_mean_score": None,
            "paired_mean_delta": None,
            "before_valid_call_rate": None,
            "after_valid_call_rate": None,
            "status": "FAILED_REAPER_LOST",
            "bar_passed": False,
            "summary": "On-instance reaper deleted Verda A100 18acfa5d at 07:30 before backup base eval artifacts were pulled",
        },
        {
            "run_id": "X2-dagger-r1-e9ea",
            "model": "Qwen2.5-1.5B-Instruct LoRA (DAgger round 1 from v3-4k s0)",
            "method": "250-step SFT on 4,000 solver-relabelled own-policy states on Verda A100-40 e9ea8b2e",
            "tiers_version": "v1.4",
            "context_len": 8192,
            "heldout_n": 50,
            "before_mean_score": 0.0,
            "after_mean_score": -0.542,
            "paired_mean_delta": -0.542,
            "before_valid_call_rate": 0.03,
            "after_valid_call_rate": None,
            "status": "NEGATIVE_DAGGER_NULL",
            "bar_passed": False,
            "summary": "Honest null at deadline: -0.542 +/- 0.214 at 8k context (n=50 partial) and level with v3-4k at 4k context",
        },
    ]
    compact_non_llm_run = {
        "run_id": "empirical-bayes-v14",
        "category": "non_llm_compact_empirical_bayes",
        "strictly_separated_from_open_weight_llm": True,
        "model": "CompactEmpiricalBayesPolicy (6 log-likelihood weights + 4 EV-stopping/split scalars fitted on TRAIN_SEEDS)",
        "tiers_version": "v1.4",
        "tiers": ["easy", "medium", "hard"],
        "n": 180,
        "n_per_tier": 60,
        "train_seed_window": "TRAIN_SEEDS_102000_to_102779",
        "eval_split_label": "heldout_60_seeds_per_tier",
        "before_mean_score": -0.421,
        "before_mean_score_exact": -0.4209,
        "after_mean_score": 0.607,
        "after_mean_score_exact": 0.6073,
        "paired_mean_delta": 1.028,
        "paired_mean_delta_exact": 1.0282,
        "paired_ci95": [0.915, 1.141],
        "paired_ci95_exact": [0.9152, 1.1411],
        "paired_summary": "+1.028 [+0.915, +1.141]",
        "before_valid_call_rate": 1.0,
        "after_valid_call_rate": 1.0,
        "world_secret_tag": EXPECTED_WORLD_SECRET_TAG,
        "replay_verified": True,
        "invalid_episodes": 0,
        "status": "VERIFIED_IMPROVEMENT",
    }
    n_open = len(open_weight_runs)
    return {
        "schema_version": "canary_tiebreak_ledger_v1",
        "tiers_version": "v1.4",
        "total_runs_logged": n_open + 1,
        "open_weight_llm_summary": {
            "model_family": "Qwen2.5-1.5B-Instruct LoRA (SFT + Guided Decision-Point GRPO + DAgger)",
            "total_runs": n_open,
            "verified_improvements": 0,
            "bar_ratio": f"0/{n_open}",
            "bar_met": False,
            "honest_readout": (
                f"Open-weight 1.5B SFT/GRPO/DAgger learned tool JSON syntax (valid calls 0.03 to 0.92..1.00) and "
                f"shifted accusation timing (v2 -0.457 to v3-4k -0.147, v3-8k-s0 -0.060, v3-8k-s2 -0.050), "
                f"but 0/{n_open} runs beat the 0.000 untrained base on held-out seeds; all OOMs, spot preemptions, "
                f"reaper-deleted boxes, 8k context confounds, and DAgger round 1 null are logged in full."
            ),
            "runs": open_weight_runs,
        },
        "compact_non_llm_empirical_bayes": compact_non_llm_run,
        "separation_note": (
            f"Open-weight neural LLM runs (0/{n_open} bar met) and the non-LLM 10-scalar CompactEmpiricalBayesPolicy "
            "(+0.607 vs -0.421, paired +1.028 [+0.915, +1.141], n=180) are reported in separate tracks and "
            "never conflated."
        ),
    }


def build_traces_payload(trained_params: CompactEmpiricalBayesParams) -> dict[str, Any]:
    traces: list[dict[str, Any]] = []
    for tier in ("hard", "medium", "easy"):
        for seed in SHIPPED_DEV_SEEDS_BY_TIER[tier]:
            if seed not in DEV_SEEDS or seed in HELDOUT_SEEDS or seed in JUDGE_SEEDS:
                raise ValueError(f"shipped arena trace seed {seed} must be strictly in DEV_SEEDS")
            for agent_name in AGENT_ORDER:
                traces.append(
                    run_and_build_verified_trace(
                        tier=tier,
                        seed=seed,
                        agent_name=agent_name,
                        trained_params=trained_params,
                        seed_split_note=SEED_SPLIT_NOTE,
                    )
                )
    return {
        "schema_version": "canary_tiebreak_arena_v1",
        "rules_version": "v1.4",
        "seed_split_note": SEED_SPLIT_NOTE,
        "seed_split_disclosure": (
            "Shipped Arena traces use DEV_SEEDS only; seeds 0-29 are a post-hoc lock "
            "(671ed96 landed 28 s after 8fd4dec), not pre-registered, and zero HELDOUT_SEEDS "
            "or JUDGE_SEEDS worlds are shipped in docs/arena."
        ),
        "agents": list(AGENT_ORDER),
        "default_seeds": list(SHIPPED_DEV_SEEDS_BY_TIER["hard"]),
        "seeds_by_tier": {t: list(s) for t, s in SHIPPED_DEV_SEEDS_BY_TIER.items()},
        "train_fit_provenance": {
            "train_seed_domain": [100_000, 200_000],
            "stage2_likelihood_seeds": [STAGE2_TRAIN_SLICE[0], STAGE2_TRAIN_SLICE[1] - 1],
            "stage3_stopping_seeds": [STAGE3_TRAIN_SLICE[0], STAGE3_TRAIN_SLICE[1] - 1],
            "before_uncalibrated_params": make_uncalibrated_params().to_dict(),
            "after_trained_params": trained_params.to_dict(),
        },
        "traces": traces,
    }


def render_data_js(traces_payload: dict[str, Any], ledger_payload: dict[str, Any]) -> str:
    traces_json = json.dumps(traces_payload, separators=(",", ":"), ensure_ascii=True)
    ledger_json = json.dumps(ledger_payload, separators=(",", ":"), ensure_ascii=True)
    lines = [
        f"const TIEBREAK_TRACES_PAYLOAD = {traces_json};",
        f"const TIEBREAK_LEDGER_SUMMARY_PAYLOAD = {ledger_json};",
        "const _BuiltCanaryTiebreakApi = (function buildCanaryTiebreakApi() {",
        "  const byCase = {};",
        "  for (const tr of TIEBREAK_TRACES_PAYLOAD.traces) {",
        '    const key = tr.tier + ":" + String(tr.seed);',
        "    if (!byCase[key]) {",
        "      byCase[key] = {",
        "        seed: tr.seed,",
        "        tier: tr.tier,",
        "        seed_split_note: tr.seed_split_note,",
        "        agents: {}",
        "      };",
        "    }",
        "    byCase[key].agents[tr.agent] = tr;",
        "    byCase[key][tr.agent] = tr;",
        "  }",
        "  function gateStep(st, unlock) {",
        '    const isAccuse = st.tool === "accuse";',
        "    if (unlock && isAccuse) {",
        "      return {",
        "        day: st.day,",
        "        call_idx: st.call_idx,",
        "        tool: st.tool,",
        "        args: st.args,",
        "        ok: st.ok,",
        "        summary: st.summary,",
        "        V: st.V,",
        "        top_p: st.top_p,",
        "        breakeven_p: st.breakeven_p,",
        "        sealed: false",
        "      };",
        "    }",
        "    return {",
        "        day: st.day,",
        "        call_idx: st.call_idx,",
        "        tool: st.tool,",
        '        args: isAccuse ? { employee_id: "[SEALED]" } : st.args,',
        "        ok: st.ok,",
        '        summary: isAccuse ? "accuse([SEALED])" : st.summary,',
        "        V: st.V,",
        "        top_p: st.top_p,",
        "        breakeven_p: st.breakeven_p,",
        "        sealed: isAccuse",
        "    };",
        "  }",
        "  function getTrace(tier, seed, agent) {",
        '    const key = String(tier || "hard") + ":" + String(seed);',
        "    const entry = byCase[key];",
        "    if (!entry) return null;",
        '    return entry.agents[String(agent || "after_trained")] || null;',
        "  }",
        "  function getTiebreakDuelView(seed, day, done, tier, agent) {",
        '    const resolvedTier = tier ? String(tier) : Number(seed) >= 3000 ? "easy" : "hard";',
        '    const entry = byCase[resolvedTier + ":" + String(seed)] || byCase["hard:" + String(seed)] || byCase["medium:" + String(seed)] || byCase["easy:" + String(seed)] || null;',
        '    const resolvedAgent = String(agent || "after_trained");',
        "    if (!entry || !entry.agents[resolvedAgent]) {",
        "      return {",
        "        available: false,",
        "        seed: Number(seed),",
        "        tier: resolvedTier,",
        "        agent: resolvedAgent,",
        '        seed_split_note: "dev_diagnostic_post_hoc_locked",',
        "        steps: [],",
        '        status: "unavailable",',
        "        sealed_day: null,",
        "        final: null",
        "      };",
        "    }",
        "    const tr = entry.agents[resolvedAgent];",
        "    const humanDone = done === true;",
        "    const dayCap = Math.max(1, Number(day) || 1);",
        "    if (humanDone) {",
        "      const accId = tr.final && tr.final.accused ? tr.final.accused : null;",
        "      const stepsUnlocked = tr.steps.map((st) => {",
        "        const copy = gateStep(st, true);",
        '        if (st.tool === "accuse" && accId) {',
        "          copy.args = { employee: accId };",
        '          copy.summary = "accuse(" + accId + ")";',
        "        }",
        "        return copy;",
        "      });",
        "      return {",
        "        available: true,",
        "        seed: tr.seed,",
        "        tier: tr.tier,",
        "        agent: tr.agent,",
        "        seed_split_note: tr.seed_split_note,",
        "        steps: stepsUnlocked,",
        '        status: "unlocked",',
        "        sealed_day: null,",
        "        final: Object.assign({}, tr.final)",
        "      };",
        "    }",
        "    const stepsLocked = [];",
        "    let sealedDay = null;",
        '    let status = "hunting";',
        "    for (const st of tr.steps) {",
        "      if (st.day <= dayCap) {",
        "        const clean = gateStep(st, false);",
        "        if (clean.sealed) {",
        '          status = "sealed_accusation";',
        "          if (sealedDay === null || st.day < sealedDay) {",
        "            sealedDay = st.day;",
        "          }",
        "        }",
        "        stepsLocked.push(clean);",
        "      }",
        "    }",
        "    return {",
        "      available: true,",
        "      seed: tr.seed,",
        "      tier: tr.tier,",
        "      agent: tr.agent,",
        "      seed_split_note: tr.seed_split_note,",
        "      steps: stepsLocked,",
        "      status: status,",
        "      sealed_day: sealedDay,",
        "      final: null",
        "    };",
        "  }",
        "  function getCaseComparison(seed, day, done, tier) {",
        '    const resolvedTier = tier ? String(tier) : Number(seed) >= 3000 ? "easy" : "hard";',
        "    const views = {};",
        "    for (const ag of TIEBREAK_TRACES_PAYLOAD.agents) {",
        "      views[ag] = getTiebreakDuelView(seed, day, done, resolvedTier, ag);",
        "    }",
        "    return {",
        "      available: Boolean(views.after_trained && views.after_trained.available),",
        "      seed: Number(seed),",
        "      tier: resolvedTier,",
        "      day: Math.max(1, Number(day) || 1),",
        "      done: done === true,",
        '      seed_split_note: "dev_diagnostic_post_hoc_locked",',
        "      agents: views",
        "    };",
        "  }",
        "  function listSeeds(tier) {",
        "    if (tier && TIEBREAK_TRACES_PAYLOAD.seeds_by_tier[tier]) {",
        "      return TIEBREAK_TRACES_PAYLOAD.seeds_by_tier[tier].slice();",
        "    }",
        "    return TIEBREAK_TRACES_PAYLOAD.default_seeds.slice();",
        "  }",
        "  const api = Object.assign({}, TIEBREAK_TRACES_PAYLOAD, {",
        "    by_case: byCase,",
        "    episodes: byCase,",
        "    ledger_summary: TIEBREAK_LEDGER_SUMMARY_PAYLOAD,",
        "    getTrace: getTrace,",
        "    getTiebreakDuelView: getTiebreakDuelView,",
        "    getDuelView: getTiebreakDuelView,",
        "    getCaseComparison: getCaseComparison,",
        "    listSeeds: listSeeds",
        "  });",
        "  return api;",
        "})();",
        "export const CANARY_TIEBREAK_TRACES = _BuiltCanaryTiebreakApi;",
        "export const tiebreakTraces = CANARY_TIEBREAK_TRACES;",
        "export const CANARY_TIEBREAK_LEDGER_SUMMARY = TIEBREAK_LEDGER_SUMMARY_PAYLOAD;",
        "export default CANARY_TIEBREAK_TRACES;",
        'if (typeof globalThis !== "undefined") {',
        "  globalThis.CANARY_TIEBREAK_TRACES = CANARY_TIEBREAK_TRACES;",
        "  globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY = CANARY_TIEBREAK_LEDGER_SUMMARY;",
        "}",
        'if (typeof window !== "undefined") {',
        "  window.CANARY_TIEBREAK_TRACES = CANARY_TIEBREAK_TRACES;",
        "  window.CANARY_TIEBREAK_LEDGER_SUMMARY = CANARY_TIEBREAK_LEDGER_SUMMARY;",
        "}",
        "",
    ]
    return "\n".join(lines)


def render_shim_js() -> str:
    return (
        "import {\n"
        "  CANARY_TIEBREAK_TRACES as _CANARY_TIEBREAK_TRACES,\n"
        "  CANARY_TIEBREAK_LEDGER_SUMMARY as _CANARY_TIEBREAK_LEDGER_SUMMARY\n"
        '} from "./data/tiebreak_traces.js";\n'
        "export const CANARY_TIEBREAK_TRACES = _CANARY_TIEBREAK_TRACES;\n"
        "export const tiebreakTraces = _CANARY_TIEBREAK_TRACES;\n"
        "export const CANARY_TIEBREAK_LEDGER_SUMMARY = _CANARY_TIEBREAK_LEDGER_SUMMARY;\n"
        "export default _CANARY_TIEBREAK_TRACES;\n"
        'if (typeof globalThis !== "undefined") {\n'
        "  globalThis.CANARY_TIEBREAK_TRACES = _CANARY_TIEBREAK_TRACES;\n"
        "  globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY = _CANARY_TIEBREAK_LEDGER_SUMMARY;\n"
        "}\n"
        'if (typeof window !== "undefined") {\n'
        "  window.CANARY_TIEBREAK_TRACES = _CANARY_TIEBREAK_TRACES;\n"
        "  window.CANARY_TIEBREAK_LEDGER_SUMMARY = _CANARY_TIEBREAK_LEDGER_SUMMARY;\n"
        "}\n"
    )


def _extract_const_payload(js_text: str, const_name: str) -> dict[str, Any]:
    prefix = f"const {const_name} = "
    for line in js_text.splitlines():
        if line.startswith(prefix) and line.endswith(";"):
            return json.loads(line[len(prefix) : -1])
    raise ValueError(f"missing {const_name} JSON assignment")


def _scan_recursive_invariants(node: Any, path_label: str, in_steps: bool = False) -> list[str]:
    errors: list[str] = []
    if isinstance(node, int) and not isinstance(node, bool):
        if node in HELDOUT_SEEDS or node in JUDGE_SEEDS:
            errors.append(f"{path_label}: forbidden benchmark seed integer {node}")
    elif isinstance(node, str):
        if node.isdigit() and (int(node) in HELDOUT_SEEDS or int(node) in JUDGE_SEEDS):
            errors.append(f"{path_label}: forbidden benchmark seed string {node}")
    elif isinstance(node, list):
        for idx, item in enumerate(node):
            errors.extend(_scan_recursive_invariants(item, f"{path_label}[{idx}]", in_steps=in_steps))
    elif isinstance(node, dict):
        for k, v in node.items():
            ks = str(k)
            if ks.isdigit() and (int(ks) in HELDOUT_SEEDS or int(ks) in JUDGE_SEEDS):
                errors.append(f"{path_label}.{ks}: forbidden benchmark seed key")
            if in_steps and ks in FORBIDDEN_STEP_KEYS:
                errors.append(f"{path_label}.{ks}: forbidden pre-end truth key in steps")
            child_in_steps = in_steps or ks == "steps"
            errors.extend(_scan_recursive_invariants(v, f"{path_label}.{ks}", in_steps=child_in_steps))
    return errors


def _audit_js_text_hygiene(js_text: str, label: str, max_bytes: int | None = None) -> list[str]:
    errors: list[str] = []
    raw_bytes = js_text.encode("utf-8")
    if max_bytes is not None and len(raw_bytes) > max_bytes:
        errors.append(f"{label}: size {len(raw_bytes)} exceeds cap {max_bytes}")
    if not js_text.isascii():
        errors.append(f"{label}: contains non-ASCII characters")
    for dch in DASH_CHARS:
        if dch in js_text:
            errors.append(f"{label}: contains unicode dash {ord(dch):04x}")
    if " -- " in js_text:
        errors.append(f"{label}: contains prose double-hyphen")
    for tok in COMMENT_TOKENS:
        if tok in js_text:
            errors.append(f"{label}: contains JS comment token {tok!r}")
    for sec in FORBIDDEN_ARENA_TOKENS:
        if sec in js_text:
            errors.append(f"{label}: contains forbidden secret token {sec}")
    for match in re.finditer(r"\b(800[01]\d\d|9000[0-3]\d)\b", js_text):
        errors.append(f"{label}: contains forbidden benchmark seed literal {match.group(1)}")
    return errors


def verify_shipped_arena_traces(
    data_js_path: Path = DEFAULT_DATA_JS,
    shim_js_path: Path = DEFAULT_SHIM_JS,
    full_fit: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    if not data_js_path.is_file():
        raise FileNotFoundError(f"missing {data_js_path}")
    if not shim_js_path.is_file():
        raise FileNotFoundError(f"missing {shim_js_path}")

    if full_fit:
        fitted = fit_compact_empirical_bayes_from_train_seeds()
        if fitted.to_dict() != LOCKED_TRAIN_FITTED_PARAMS.to_dict():
            raise AssertionError("full TRAIN_SEEDS fit drifted from locked parameters")
        trained_params = fitted
    else:
        smoke_seeds = list(range(*SMOKE_TRAIN_SLICE))
        smoke_a = fit_likelihood_weights_on_train_seeds(smoke_seeds)
        smoke_b = fit_likelihood_weights_on_train_seeds(smoke_seeds)
        if smoke_a.to_dict() != smoke_b.to_dict():
            raise AssertionError("TRAIN_SEEDS likelihood fit is non-deterministic")
        trained_params = LOCKED_TRAIN_FITTED_PARAMS

    data_txt = data_js_path.read_text(encoding="utf-8")
    shim_txt = shim_js_path.read_text(encoding="utf-8")

    hygiene_errors = _audit_js_text_hygiene(data_txt, "docs/arena/data/tiebreak_traces.js", MAX_BUNDLE_BYTES)
    hygiene_errors.extend(_audit_js_text_hygiene(shim_txt, "docs/arena/tiebreak_traces.js", 4096))
    for label, txt in (
        ("docs/arena/data/tiebreak_traces.js", data_txt),
        ("docs/arena/tiebreak_traces.js", shim_txt),
    ):
        for req_tok in (
            "export const CANARY_TIEBREAK_TRACES =",
            "export const tiebreakTraces =",
            "export const CANARY_TIEBREAK_LEDGER_SUMMARY =",
            "export default ",
            "globalThis.CANARY_TIEBREAK_TRACES =",
            "globalThis.CANARY_TIEBREAK_LEDGER_SUMMARY =",
        ):
            if req_tok not in txt:
                hygiene_errors.append(f"{label}: missing required module/global contract token {req_tok!r}")
    if shim_txt != render_shim_js():
        hygiene_errors.append("docs/arena/tiebreak_traces.js does not match canonical shim")
    if hygiene_errors:
        raise AssertionError("; ".join(hygiene_errors))

    shipped_traces_obj = _extract_const_payload(data_txt, "TIEBREAK_TRACES_PAYLOAD")
    shipped_ledger_obj = _extract_const_payload(data_txt, "TIEBREAK_LEDGER_SUMMARY_PAYLOAD")

    inv_errors = _scan_recursive_invariants(shipped_traces_obj, "TIEBREAK_TRACES_PAYLOAD")
    inv_errors.extend(_scan_recursive_invariants(shipped_ledger_obj, "TIEBREAK_LEDGER_SUMMARY_PAYLOAD"))
    if inv_errors:
        raise AssertionError("; ".join(inv_errors))

    expected_traces_obj = build_traces_payload(trained_params)
    expected_ledger_obj = build_ledger_summary_payload()
    if shipped_traces_obj != expected_traces_obj:
        raise AssertionError("shipped TIEBREAK_TRACES_PAYLOAD differs from deterministic Env regeneration")
    if shipped_ledger_obj != expected_ledger_obj:
        raise AssertionError("shipped TIEBREAK_LEDGER_SUMMARY_PAYLOAD differs from canonical readout")
    if data_txt != render_data_js(expected_traces_obj, expected_ledger_obj):
        raise AssertionError("docs/arena/data/tiebreak_traces.js differs from canonical render")

    for tr in shipped_traces_obj["traces"]:
        tier = tr["tier"]
        seed = tr["seed"]
        shadow = Env(tier, seed)
        steps = tr["steps"]
        for idx, st in enumerate(steps):
            if st["call_idx"] != idx:
                raise AssertionError(f"call_idx mismatch on {tier}:{seed}:{tr['agent']}")
            if st["tool"] == "accuse":
                if st["args"] != {"employee_id": "[SEALED]"} or st["summary"] != "accuse([SEALED])":
                    raise AssertionError(f"unsealed accuse step on {tier}:{seed}:{tr['agent']}")
                real_emp = tr["final"]["accused"]
                if not isinstance(real_emp, str) or not real_emp:
                    raise AssertionError(f"missing final.accused on {tier}:{seed}:{tr['agent']}")
                shadow.call("accuse", {"employee": real_emp})
            else:
                if "[SEALED]" in json.dumps(st["args"]):
                    raise AssertionError(f"unexpected sealed non-accuse step on {tier}:{seed}")
                res = shadow.call(st["tool"], st["args"])
                if bool(res.ok) != bool(st["ok"]):
                    raise AssertionError(f"shadow ok mismatch on {tier}:{seed}")
            if abs(float(st["V"]) - shadow.visible_V()) > 1e-9:
                raise AssertionError(f"pre-end V != visible_V on {tier}:{seed} step {idx}")
        verdict = shadow.result(tr["agent"])
        if abs(round(float(verdict.score), 4) - float(tr["final"]["score"])) > 1e-9:
            raise AssertionError(f"shadow terminal score mismatch on {tier}:{seed}:{tr['agent']}")
        if verdict.accused != tr["final"]["accused"] or bool(verdict.correct) != bool(tr["final"]["correct"]):
            raise AssertionError(f"shadow terminal verdict mismatch on {tier}:{seed}:{tr['agent']}")
        if int(verdict.final_day) != int(tr["final"]["final_day"]):
            raise AssertionError(f"shadow final_day mismatch on {tier}:{seed}:{tr['agent']}")

    heldout_parity = verify_in_memory_heldout_parity(trained_params)
    elapsed = round(time.perf_counter() - t0, 3)
    return {
        "passed": True,
        "data_js_bytes": len(data_txt.encode("utf-8")),
        "shim_js_lines": len(shim_txt.splitlines()),
        "shipped_traces_count": len(shipped_traces_obj["traces"]),
        "ledger_total_runs": shipped_ledger_obj["total_runs_logged"],
        "open_weight_bar": shipped_ledger_obj["open_weight_llm_summary"]["bar_ratio"],
        "heldout_parity": heldout_parity,
        "elapsed_s": elapsed,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build and verify Canary Arena tiebreaker traces.")
    ap.add_argument("--check", action="store_true", help="Verify shipped JS bundle and held-out parity without writing")
    ap.add_argument("--full-fit", action="store_true", help="Run full 360-episode TRAIN_SEEDS fit")
    ap.add_argument("--data-out", type=Path, default=DEFAULT_DATA_JS)
    ap.add_argument("--shim-out", type=Path, default=DEFAULT_SHIM_JS)
    args = ap.parse_args(argv)

    if args.check:
        report = verify_shipped_arena_traces(
            data_js_path=args.data_out,
            shim_js_path=args.shim_out,
            full_fit=args.full_fit,
        )
        print(json.dumps(report, indent=2))
        return 0

    if args.full_fit:
        fitted_params = fit_compact_empirical_bayes_from_train_seeds()
        if fitted_params.to_dict() != LOCKED_TRAIN_FITTED_PARAMS.to_dict():
            raise AssertionError(
                f"TRAIN_SEEDS fit mismatch: got {fitted_params.to_dict()}, expected {LOCKED_TRAIN_FITTED_PARAMS.to_dict()}"
            )
    else:
        fitted_params = LOCKED_TRAIN_FITTED_PARAMS
    traces_payload = build_traces_payload(fitted_params)
    ledger_payload = build_ledger_summary_payload()
    data_txt = render_data_js(traces_payload, ledger_payload)
    shim_txt = render_shim_js()

    args.data_out.parent.mkdir(parents=True, exist_ok=True)
    args.shim_out.parent.mkdir(parents=True, exist_ok=True)
    args.data_out.write_text(data_txt, encoding="utf-8")
    args.shim_out.write_text(shim_txt, encoding="utf-8")

    report = verify_shipped_arena_traces(
        data_js_path=args.data_out,
        shim_js_path=args.shim_out,
        full_fit=False,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
