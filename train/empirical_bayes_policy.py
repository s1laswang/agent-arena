from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

LABELS = "ABCDEFGH"
TIERS: tuple[str, ...] = ("easy", "medium", "hard")
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

STAGE2_TRAIN_RANGE: tuple[int, int] = (102_000, 102_600)
STAGE3_TRAIN_RANGE: tuple[int, int] = (102_600, 103_200)
HELDOUT_EVAL_RANGE: tuple[int, int] = (800_000, 800_060)
HELDOUT_N90_SUBSET_COUNT: int = 30
DEV_HARD_EVAL_RANGE: tuple[int, int] = (0, 30)
HELDOUT_SECRET_TAG = "canary-tiebreak-heldout-v14-eval-01"
DEFAULT_CHECKPOINT_DIR = "/tmp/fleet-silas/shared/tiebreak/empirical_bayes"
DEFAULT_RESULTS_DIR = "results/tiebreak/empirical_bayes"

ABLATION_VARIANTS: tuple[str, ...] = (
    "eb_naive_prior",
    "eb_likelihood_only",
    "eb_ev_stop_only",
    "eb_no_canary_planting",
    "eb_experience_opt",
)

ABLATION_MECHANISM_NOTES: dict[str, dict[str, Any]] = {
    "eb_naive_prior": {
        "mechanism": "Untrained prior + uncalibrated p>=0.50 stopping + default 0.90 splits",
        "learned_likelihoods": False,
        "ev_stopping": False,
        "active_canary_planting": True,
        "learned_split_and_margin": False,
        "negative_ablation": True,
    },
    "eb_likelihood_only": {
        "mechanism": "Learned log-likelihoods on TRAIN_SEEDS, no EV-stopping, default 0.90 splits",
        "learned_likelihoods": True,
        "ev_stopping": False,
        "active_canary_planting": True,
        "learned_split_and_margin": False,
        "negative_ablation": False,
    },
    "eb_ev_stop_only": {
        "mechanism": "Naive prior + 1/(1+V) EV-stopping without learned likelihoods (negative ablation)",
        "learned_likelihoods": False,
        "ev_stopping": True,
        "active_canary_planting": True,
        "learned_split_and_margin": False,
        "negative_ablation": True,
    },
    "eb_no_canary_planting": {
        "mechanism": "Learned likelihoods + EV-stopping, canary_cov=0.0 passive logs/messages/docs only (negative ablation)",
        "learned_likelihoods": True,
        "ev_stopping": True,
        "active_canary_planting": False,
        "learned_split_and_margin": False,
        "negative_ablation": True,
    },
    "eb_experience_opt": {
        "mechanism": "Full learned likelihoods + learned canary-split sizing + learned tau_margin EV-stopping",
        "learned_likelihoods": True,
        "ev_stopping": True,
        "active_canary_planting": True,
        "learned_split_and_margin": True,
        "negative_ablation": False,
    },
}


@dataclass(frozen=True)
class EmpiricalBayesParams:
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
    stage: str = "eb_experience_opt"

    def theta_dict(self) -> dict[str, float]:
        return {
            "w_canary_hit": round(float(self.w_canary_hit), 6),
            "w_canary_miss": round(float(self.w_canary_miss), 6),
            "w_doc_hit": round(float(self.w_doc_hit), 6),
            "w_after_hours": round(float(self.w_after_hours), 6),
            "w_evasive": round(float(self.w_evasive), 6),
            "w_angry_msg": round(float(self.w_angry_msg), 6),
        }

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, float):
                d[k] = round(v, 6)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> EmpiricalBayesParams:
        return cls(
            w_canary_hit=float(d["w_canary_hit"]),
            w_canary_miss=float(d["w_canary_miss"]),
            w_doc_hit=float(d["w_doc_hit"]),
            w_after_hours=float(d["w_after_hours"]),
            w_evasive=float(d["w_evasive"]),
            w_angry_msg=float(d["w_angry_msg"]),
            tau_margin=float(d["tau_margin"]),
            unsurfaced_v_discount=float(d["unsurfaced_v_discount"]),
            canary_coverage=float(d["canary_coverage"]),
            tiny_pool_size=int(d["tiny_pool_size"]),
            use_ev_stopping=bool(d.get("use_ev_stopping", True)),
            naive_p_threshold=float(d.get("naive_p_threshold", 0.50)),
            stage=str(d.get("stage", "eb_experience_opt")),
        )


def make_naive_prior_params() -> EmpiricalBayesParams:
    return EmpiricalBayesParams(
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
        stage="eb_naive_prior",
    )


def make_ev_stop_only_params() -> EmpiricalBayesParams:
    naive = make_naive_prior_params()
    return EmpiricalBayesParams(
        w_canary_hit=naive.w_canary_hit,
        w_canary_miss=naive.w_canary_miss,
        w_doc_hit=naive.w_doc_hit,
        w_after_hours=naive.w_after_hours,
        w_evasive=naive.w_evasive,
        w_angry_msg=naive.w_angry_msg,
        tau_margin=0.0,
        unsurfaced_v_discount=0.0,
        canary_coverage=0.90,
        tiny_pool_size=0,
        use_ev_stopping=True,
        naive_p_threshold=0.50,
        stage="eb_ev_stop_only",
    )


def make_no_canary_planting_params(
    likelihood_params: EmpiricalBayesParams,
    opt_params: EmpiricalBayesParams,
) -> EmpiricalBayesParams:
    return EmpiricalBayesParams(
        w_canary_hit=likelihood_params.w_canary_hit,
        w_canary_miss=likelihood_params.w_canary_miss,
        w_doc_hit=likelihood_params.w_doc_hit,
        w_after_hours=likelihood_params.w_after_hours,
        w_evasive=likelihood_params.w_evasive,
        w_angry_msg=likelihood_params.w_angry_msg,
        tau_margin=opt_params.tau_margin,
        unsurfaced_v_discount=opt_params.unsurfaced_v_discount,
        canary_coverage=0.0,
        tiny_pool_size=0,
        use_ev_stopping=True,
        naive_p_threshold=0.50,
        stage="eb_no_canary_planting",
    )


def build_ablation_variant_params(
    stage1_params: EmpiricalBayesParams,
    stage2_params: EmpiricalBayesParams,
    stage3_params: EmpiricalBayesParams,
) -> dict[str, EmpiricalBayesParams]:
    likelihood_only = EmpiricalBayesParams(
        w_canary_hit=stage2_params.w_canary_hit,
        w_canary_miss=stage2_params.w_canary_miss,
        w_doc_hit=stage2_params.w_doc_hit,
        w_after_hours=stage2_params.w_after_hours,
        w_evasive=stage2_params.w_evasive,
        w_angry_msg=stage2_params.w_angry_msg,
        tau_margin=0.0,
        unsurfaced_v_discount=0.0,
        canary_coverage=0.90,
        tiny_pool_size=0,
        use_ev_stopping=False,
        naive_p_threshold=0.50,
        stage="eb_likelihood_only",
    )
    return {
        "eb_naive_prior": stage1_params,
        "eb_likelihood_only": likelihood_only,
        "eb_ev_stop_only": make_ev_stop_only_params(),
        "eb_no_canary_planting": make_no_canary_planting_params(likelihood_only, stage3_params),
        "eb_experience_opt": stage3_params,
    }


def _parse_instruction_rules(instruction: str) -> dict[str, Any]:
    raw: dict[str, str] = {}
    for line in (instruction or "").splitlines():
        s = line.strip()
        if s.startswith("- ") and ": " in s:
            k, v = s[2:].split(": ", 1)
            if k.replace("_", "").isalnum():
                raw.setdefault(k, v.strip())

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

    delays_str = raw.get("delay_choices", "1, 2")
    delays_parsed: list[int] = []
    for part in delays_str.split(","):
        part = part.strip()
        if part.isdigit():
            delays_parsed.append(int(part))
    if not delays_parsed:
        delays_parsed = [1, 2]

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
        "delay_choices": tuple(delays_parsed),
        "leak_damage": _f("leak_damage", 0.05),
        "canary_cost": _f("canary_cost", 0.01),
        "canaries_per_day": _i("canaries_per_day", 1),
        "max_variants": _i("max_variants", 3),
        "actions_per_day": _i("actions_per_day", 8),
        "tool_call_cap": _i("tool_call_cap", 300),
        "wrong_accusation_score": _f("wrong_accusation_score", -1.0),
        "leak_window_days": _i("leak_window_days", 3),
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


def _step_fields(step: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if hasattr(step, "tool"):
        tool = str(step.tool)
        args = dict(step.args) if isinstance(step.args, dict) else {}
        res = dict(step.result) if isinstance(step.result, dict) else {}
    else:
        tool = str(step.get("tool", ""))
        args = dict(step.get("args") or {})
        res = dict(step.get("result") or {})
    return tool, args, res


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
        tool, args, res = _step_fields(step)
        if not res.get("ok"):
            return
        data = res.get("data") or {}
        if not isinstance(data, dict):
            return
        step_day = int(getattr(step, "day", step.get("day", self.today) if isinstance(step, dict) else self.today))
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
            for d in data.get("documents") or []:
                if not isinstance(d, dict) or "doc_id" not in d:
                    continue
                did = str(d["doc_id"])
                var_raw = d.get("variants")
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
                    "day": int(d.get("day", self.today)),
                    "recipients": frozenset(str(x) for x in (d.get("recipients") or [])),
                    "is_canary": bool(d.get("is_canary", False)),
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
            emp_filter = args.get("employee")
            if emp_filter is None:
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
        surfaced_list = sorted(self.feed_items.values(), key=lambda x: (x["surfaced_day"], x["doc_id"]))
        for emp in self.employees:
            c_hit = 0
            c_miss = 0
            d_hit = 0
            for item in surfaced_list:
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
            ah = self.after_hours.get(emp, 0)
            ev = self.interviews_evasive.get(emp, 0)
            ang = self.angry_msgs.get(emp, 0)
            feats[emp] = (c_hit, c_miss, d_hit, ah, ev, ang)
        return feats


class EmpiricalBayesPolicy:
    name = "empirical_bayes"

    def __init__(
        self,
        params: EmpiricalBayesParams | None = None,
        seed: int = 0,
        name: str | None = None,
    ) -> None:
        self.params = params if params is not None else make_naive_prior_params()
        self.seed = int(seed)
        self.name = str(name if name is not None else self.params.stage)
        self.rules: dict[str, Any] = _parse_instruction_rules("")
        self.topics: tuple[str, ...] = DEFAULT_TOPICS
        self.tracker = _PublicHistoryTracker()
        self.queue: list[tuple[str, dict[str, Any]]] = []
        self.planned_day: int = 0
        self.last_decision_meta: dict[str, Any] = {}

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.rules = _parse_instruction_rules(instruction)
        self.topics = _extract_topics(tools_spec)
        self.tracker = _PublicHistoryTracker()
        self.queue = []
        self.planned_day = 0
        self.last_decision_meta = {}

    def posterior(self) -> dict[str, float]:
        emps = self.tracker.employees
        if not emps:
            n = max(1, int(self.rules.get("n_employees", 20)))
            return {f"e{i:02d}": 1.0 / n for i in range(n)}
        feats = self.tracker.extract_features()
        p = self.params
        weights = np.array(
            [
                p.w_canary_hit,
                p.w_canary_miss,
                p.w_doc_hit,
                p.w_after_hours,
                p.w_evasive,
                p.w_angry_msg,
            ],
            dtype=np.float64,
        )
        mat = np.array([feats[e] for e in emps], dtype=np.float64)
        logits = mat @ weights
        max_l = float(np.max(logits))
        probs = np.exp(logits - max_l)
        probs /= float(np.sum(probs))
        return {emp: float(probs[i]) for i, emp in enumerate(emps)}

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
        est = vis_v - disc * float(self.rules["leak_damage"]) * pending
        return max(0.0, est)

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
            "visible_v": self.tracker.visible_v,
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
                max_count = n_total if cov >= 0.999 else max(k, min(n_total - 1, int(round(cov * n_total))))
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
                g = min(range(ng), key=lambda idx: (grp_mass[idx], len(groups[idx])))
                groups[g].append(e)
                grp_mass[g] += post[e]
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
            nxt_tool, nxt_args = self.queue.pop(0)
            return (nxt_tool, nxt_args)

        return ("advance_day", {})

    def _decide_step(self) -> tuple[str, dict[str, Any]]:
        dm = self.decision_metrics()
        self.last_decision_meta = {
            "day": dm["day"],
            "top_emp": dm["top_emp"],
            "top_p": round(float(dm["top_p"]), 6),
            "v_hat": round(float(dm["v_hat"]), 6),
            "breakeven_p": round(float(dm["breakeven_p"]), 6),
            "ev_accuse": round(float(dm["ev_accuse"]), 6),
        }
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


class _ExplorationRolloutPolicy:
    name = "eb_explorer"

    def __init__(self, seed: int) -> None:
        self.seed = int(seed)
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
            t, a = self.queue.pop(0)
            if t == "__explore_decide__":
                return self._explore_decide()
            return (t, a)
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
                pending_q = [w for w in ANGER_QUERIES if w not in self.tracker.queries_done][:3]
                for w in pending_q:
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
                angry_cands = [e for e in emps if feats[e][5] > 0]
                if angry_cands:
                    target = max(angry_cands, key=lambda e: (feats[e][5], feats[e][3], e))
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


def assert_strict_train_seed(seed: int, lo: int = 102_000, hi: int = 103_200) -> int:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ValueError(f"seed must be int, got {seed!r}")
    if seed in DEV_SEEDS or 0 <= seed < 10_000:
        raise ValueError(f"seed {seed} overlaps DEV_SEEDS")
    if 10_000 <= seed < 100_000:
        raise ValueError(f"seed {seed} overlaps reserved/dev range [10000, 100000)")
    if seed in HELDOUT_SEEDS or 800_000 <= seed < 900_000:
        raise ValueError(f"seed {seed} overlaps HELDOUT_SEEDS")
    if seed in JUDGE_SEEDS or seed >= 900_000:
        raise ValueError(f"seed {seed} overlaps JUDGE_SEEDS")
    if seed not in TRAIN_SEEDS:
        raise ValueError(f"seed {seed} is outside TRAIN_SEEDS")
    if not (lo <= seed < hi):
        raise ValueError(f"seed {seed} is outside allowed stage slice [{lo}, {hi})")
    return seed


def validate_seed_partition(
    stage2_seeds: list[int],
    stage3_seeds: list[int],
    heldout_seeds: list[int],
    dev_seeds: list[int],
) -> None:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS

    for s in stage2_seeds:
        assert_strict_train_seed(s, STAGE2_TRAIN_RANGE[0], STAGE2_TRAIN_RANGE[1])
    for s in stage3_seeds:
        assert_strict_train_seed(s, STAGE3_TRAIN_RANGE[0], STAGE3_TRAIN_RANGE[1])

    s2 = set(stage2_seeds)
    s3 = set(stage3_seeds)
    sh = set(heldout_seeds)
    sd = set(dev_seeds)
    sj = set(JUDGE_SEEDS)

    if s2 & s3:
        raise ValueError("stage2 and stage3 training seeds must be strictly disjoint")
    if (s2 | s3) & (sh | sd | sj | set(DEV_SEEDS) | set(HELDOUT_SEEDS)):
        raise ValueError("training seeds overlap eval/dev/heldout/judge seeds")
    if not all(s in HELDOUT_SEEDS for s in sh):
        raise ValueError("heldout_seeds must lie strictly inside HELDOUT_SEEDS")
    if not all(s in DEV_SEEDS for s in sd):
        raise ValueError("dev_seeds must lie strictly inside DEV_SEEDS")


def fit_empirical_likelihoods(
    seeds: list[int],
    laplace_alpha: float = 1.0,
) -> tuple[EmpiricalBayesParams, dict[str, Any]]:
    from canary.env import Env
    from canary.eval import run_episode

    for s in seeds:
        assert_strict_train_seed(s, STAGE2_TRAIN_RANGE[0], STAGE2_TRAIN_RANGE[1])

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

    n_identified_episodes = 0
    n_decoy_accused = 0
    n_decoy_correct = 0
    naive_scores: list[float] = []

    naive_params = make_naive_prior_params()

    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        naive_ep = run_episode(Env(tier, seed), EmpiricalBayesPolicy(naive_params, seed=seed))
        naive_scores.append(float(naive_ep.score))

        env = Env(tier, seed)
        explorer = _ExplorationRolloutPolicy(seed=seed)
        ep = run_episode(env, explorer)
        tr = explorer.tracker
        tr.ingest_steps(list(ep.steps))
        feats = tr.extract_features()

        if ep.accused and feats.get(ep.accused, (0, 0, 0, 0, 0, 0))[5] > 0:
            n_decoy_accused += 1
            if ep.correct:
                n_decoy_correct += 1

        if not (ep.accused and ep.correct):
            continue

        n_identified_episodes += 1
        mole_id = str(ep.accused)
        surfaced_list = list(tr.feed_items.values())
        n_surfaced = len(surfaced_list)
        n_log_days = len(tr.logged_days)
        did_msg_search = bool(tr.queries_done)

        for emp in tr.employees:
            y = 1 if emp == mole_id else 0
            c_h, c_m, d_h, ah, ev, ang = feats[emp]
            c_held = c_h + c_m
            can_exp[y] += c_held
            can_hit[y] += c_h
            can_miss[y] += c_m
            doc_exp[y] += n_surfaced
            doc_hit[y] += d_h
            ah_days[y] += n_log_days
            ah_cnt[y] += ah
            if y == 0 and n_log_days > 0:
                inn_ah_obs.append((ah, n_log_days))
            iv_tot = tr.interviews_total.get(emp, 0)
            iv_exp[y] += iv_tot
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

    p_doc_1 = (doc_hit[1] + a) / max(2.0 * a, doc_exp[1] + 2.0 * a)
    p_doc_0 = (doc_hit[0] + a) / max(2.0 * a, doc_exp[0] + 2.0 * a)
    p_doc_1 = min(1.0 - 1e-6, max(1e-6, p_doc_1))
    p_doc_0 = min(1.0 - 1e-6, max(1e-6, p_doc_0))
    w_doc_hit = math.log((p_doc_1 * (1.0 - p_doc_0)) / ((1.0 - p_doc_1) * p_doc_0))

    r_ah_1 = (ah_cnt[1] + a) / max(a, ah_days[1] + a)
    r_ah_0 = (ah_cnt[0] + a) / max(a, ah_days[0] + a)
    if inn_ah_obs:
        pearson_sq = [
            ((k_ah - r_ah_0 * d_obs) ** 2) / max(1e-6, r_ah_0 * d_obs)
            for k_ah, d_obs in inn_ah_obs
        ]
        fano_inn_ah = max(1.0, float(np.mean(pearson_sq)))
    else:
        fano_inn_ah = 1.0
    w_after_hours = math.log(r_ah_1 / r_ah_0) / fano_inn_ah

    p_ev_1 = (iv_ev[1] + a) / max(2.0 * a, iv_exp[1] + 2.0 * a)
    p_ev_0 = (iv_ev[0] + a) / max(2.0 * a, iv_exp[0] + 2.0 * a)
    w_evasive = math.log(p_ev_1 / p_ev_0)

    r_ang_1 = (ang_cnt[1] + a) / max(2.0 * a, ang_eps[1] + 2.0 * a)
    r_ang_0 = (ang_cnt[0] + a) / max(2.0 * a, ang_eps[0] + 2.0 * a)
    w_angry_msg = math.log(r_ang_1 / r_ang_0)

    stage2_params = EmpiricalBayesParams(
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
        stage="eb_likelihood_only",
    )

    stage2_train_scores: list[float] = []
    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        ep2 = run_episode(Env(tier, seed), EmpiricalBayesPolicy(stage2_params, seed=seed))
        stage2_train_scores.append(float(ep2.score))

    stats = {
        "seed_range": f"{seeds[0]}..{seeds[-1]}",
        "n_episodes": len(seeds),
        "n_identified_episodes": n_identified_episodes,
        "decoy_exploration_probes": n_decoy_accused,
        "decoy_exploration_mole_hits": n_decoy_correct,
        "laplace_alpha": laplace_alpha,
        "empirical_rates": {
            "p_canary_hit_mole": round(p_chit_1, 6),
            "p_canary_hit_innocent": round(p_chit_0, 6),
            "p_canary_miss_mole": round(p_cmiss_1, 6),
            "p_canary_miss_innocent": round(p_cmiss_0, 6),
            "p_doc_hit_mole": round(p_doc_1, 6),
            "p_doc_hit_innocent": round(p_doc_0, 6),
            "rate_after_hours_mole": round(r_ah_1, 6),
            "rate_after_hours_innocent": round(r_ah_0, 6),
            "fano_dispersion_after_hours_innocent": round(fano_inn_ah, 6),
            "p_evasive_mole": round(p_ev_1, 6),
            "p_evasive_innocent": round(p_ev_0, 6),
            "rate_angry_msg_mole": round(r_ang_1, 6),
            "rate_angry_msg_innocent": round(r_ang_0, 6),
        },
        "raw_counts": {
            "canary_held_mole_inn": [can_exp[1], can_exp[0]],
            "canary_hit_mole_inn": [can_hit[1], can_hit[0]],
            "canary_miss_mole_inn": [can_miss[1], can_miss[0]],
            "doc_exp_mole_inn": [doc_exp[1], doc_exp[0]],
            "doc_hit_mole_inn": [doc_hit[1], doc_hit[0]],
            "after_hours_days_mole_inn": [ah_days[1], ah_days[0]],
            "after_hours_cnt_mole_inn": [ah_cnt[1], ah_cnt[0]],
            "interview_exp_mole_inn": [iv_exp[1], iv_exp[0]],
            "interview_evasive_mole_inn": [iv_ev[1], iv_ev[0]],
            "angry_episodes_mole_inn": [ang_eps[1], ang_eps[0]],
            "angry_cnt_mole_inn": [ang_cnt[1], ang_cnt[0]],
        },
        "train_mean_score_eb_naive_prior": round(float(np.mean(naive_scores)), 6),
        "train_mean_score_eb_likelihood_only": round(float(np.mean(stage2_train_scores)), 6),
        "train_mean_score_eb_likelihood_learned": round(float(np.mean(stage2_train_scores)), 6),
    }
    return stage2_params, stats


def _eval_params_on_train_slice(
    params: EmpiricalBayesParams,
    seeds: list[int],
) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode

    scores: list[float] = []
    correct_cnt = 0
    wrong_cnt = 0
    abstain_cnt = 0
    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        ep = run_episode(Env(tier, seed), EmpiricalBayesPolicy(params, seed=seed))
        scores.append(float(ep.score))
        if ep.accused is None:
            abstain_cnt += 1
        elif ep.correct:
            correct_cnt += 1
        else:
            wrong_cnt += 1
    n = max(1, len(seeds))
    return {
        "mean_score": round(float(np.mean(scores)), 6),
        "accuracy": round(correct_cnt / n, 6),
        "wrong_accuse_rate": round(wrong_cnt / n, 6),
        "abstain_rate": round(abstain_cnt / n, 6),
    }


def optimize_stopping_and_splits(
    stage2_params: EmpiricalBayesParams,
    seeds: list[int],
) -> tuple[EmpiricalBayesParams, dict[str, Any]]:
    for s in seeds:
        assert_strict_train_seed(s, STAGE3_TRAIN_RANGE[0], STAGE3_TRAIN_RANGE[1])

    half = max(3, len(seeds) // 2)
    split_a = seeds[:half]
    split_b = seeds[half:] if len(seeds) > half else seeds

    ledger: list[dict[str, Any]] = []

    baseline_stage2_eval = _eval_params_on_train_slice(stage2_params, seeds)
    ledger.append(
        {
            "phase": "stage2_uncalibrated_baseline_all",
            "canary_coverage": stage2_params.canary_coverage,
            "tiny_pool_size": stage2_params.tiny_pool_size,
            "tau_margin": stage2_params.tau_margin,
            "unsurfaced_v_discount": stage2_params.unsurfaced_v_discount,
            "use_ev_stopping": False,
            **baseline_stage2_eval,
        }
    )

    split_candidates: list[tuple[float, int]] = [
        (0.90, 0),
        (0.65, 3),
        (0.55, 4),
        (0.45, 6),
        (0.35, 6),
    ]
    best_cov, best_tiny = 0.55, 4
    best_split_key = (-1e9, -1e9)
    for cov, tiny_sz in split_candidates:
        cand = EmpiricalBayesParams(
            w_canary_hit=stage2_params.w_canary_hit,
            w_canary_miss=stage2_params.w_canary_miss,
            w_doc_hit=stage2_params.w_doc_hit,
            w_after_hours=stage2_params.w_after_hours,
            w_evasive=stage2_params.w_evasive,
            w_angry_msg=stage2_params.w_angry_msg,
            tau_margin=0.65,
            unsurfaced_v_discount=1.0,
            canary_coverage=cov,
            tiny_pool_size=tiny_sz,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="eb_experience_opt_search",
        )
        res = _eval_params_on_train_slice(cand, split_a)
        ledger.append(
            {
                "phase": "canary_split_search",
                "canary_coverage": cov,
                "tiny_pool_size": tiny_sz,
                "tau_margin": 0.65,
                "unsurfaced_v_discount": 1.0,
                "use_ev_stopping": True,
                **res,
            }
        )
        cand_key = (res["mean_score"], -res["wrong_accuse_rate"])
        if cand_key > best_split_key:
            best_split_key = cand_key
            best_cov, best_tiny = cov, tiny_sz

    tau_candidates = (0.0, 0.30, 0.50, 0.65, 0.75, 0.85)
    best_tau = 0.65
    best_tau_key = (-1e9, -1e9)
    for tau in tau_candidates:
        cand = EmpiricalBayesParams(
            w_canary_hit=stage2_params.w_canary_hit,
            w_canary_miss=stage2_params.w_canary_miss,
            w_doc_hit=stage2_params.w_doc_hit,
            w_after_hours=stage2_params.w_after_hours,
            w_evasive=stage2_params.w_evasive,
            w_angry_msg=stage2_params.w_angry_msg,
            tau_margin=tau,
            unsurfaced_v_discount=1.0,
            canary_coverage=best_cov,
            tiny_pool_size=best_tiny,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="eb_experience_opt_search",
        )
        res = _eval_params_on_train_slice(cand, split_b)
        ledger.append(
            {
                "phase": "tau_margin_search",
                "canary_coverage": best_cov,
                "tiny_pool_size": best_tiny,
                "tau_margin": tau,
                "unsurfaced_v_discount": 1.0,
                "use_ev_stopping": True,
                **res,
            }
        )
        cand_key = (res["mean_score"], -res["wrong_accuse_rate"])
        if cand_key > best_tau_key:
            best_tau_key = cand_key
            best_tau = tau

    disc_candidates = (0.0, 0.50, 1.00, 1.25)
    best_disc = 1.00
    best_disc_key = (-1e9, -1e9, -1e9)
    for disc in disc_candidates:
        cand = EmpiricalBayesParams(
            w_canary_hit=stage2_params.w_canary_hit,
            w_canary_miss=stage2_params.w_canary_miss,
            w_doc_hit=stage2_params.w_doc_hit,
            w_after_hours=stage2_params.w_after_hours,
            w_evasive=stage2_params.w_evasive,
            w_angry_msg=stage2_params.w_angry_msg,
            tau_margin=best_tau,
            unsurfaced_v_discount=disc,
            canary_coverage=best_cov,
            tiny_pool_size=best_tiny,
            use_ev_stopping=True,
            naive_p_threshold=0.50,
            stage="eb_experience_opt_search",
        )
        res = _eval_params_on_train_slice(cand, split_b)
        ledger.append(
            {
                "phase": "unsurfaced_v_discount_search",
                "canary_coverage": best_cov,
                "tiny_pool_size": best_tiny,
                "tau_margin": best_tau,
                "unsurfaced_v_discount": disc,
                "use_ev_stopping": True,
                **res,
            }
        )
        cand_key = (res["mean_score"], -res["wrong_accuse_rate"], -abs(disc - 1.0))
        if cand_key > best_disc_key:
            best_disc_key = cand_key
            best_disc = disc

    stage3_params = EmpiricalBayesParams(
        w_canary_hit=stage2_params.w_canary_hit,
        w_canary_miss=stage2_params.w_canary_miss,
        w_doc_hit=stage2_params.w_doc_hit,
        w_after_hours=stage2_params.w_after_hours,
        w_evasive=stage2_params.w_evasive,
        w_angry_msg=stage2_params.w_angry_msg,
        tau_margin=best_tau,
        unsurfaced_v_discount=best_disc,
        canary_coverage=best_cov,
        tiny_pool_size=best_tiny,
        use_ev_stopping=True,
        naive_p_threshold=0.50,
        stage="eb_experience_opt",
    )
    final_train_eval = _eval_params_on_train_slice(stage3_params, seeds)
    ledger.append(
        {
            "phase": "stage3_selected_all",
            "canary_coverage": best_cov,
            "tiny_pool_size": best_tiny,
            "tau_margin": best_tau,
            "unsurfaced_v_discount": best_disc,
            "use_ev_stopping": True,
            **final_train_eval,
        }
    )
    return stage3_params, {
        "seed_range": f"{seeds[0]}..{seeds[-1]}",
        "n_episodes": len(seeds),
        "selected": {
            "canary_coverage": best_cov,
            "tiny_pool_size": best_tiny,
            "tau_margin": best_tau,
            "unsurfaced_v_discount": best_disc,
        },
        "train_stage2_uncalibrated": baseline_stage2_eval,
        "train_stage3_selected": final_train_eval,
        "search_ledger": ledger,
    }


def replay_verify_episode(ep: Any) -> bool:
    from canary.env import Env

    env = Env(ep.tier, ep.seed)
    for st in ep.steps:
        if env.done:
            break
        tool, args, recorded_res = _step_fields(st)
        live_res = env.call(tool, args)
        if recorded_res and "ok" in recorded_res and bool(live_res.ok) != bool(recorded_res["ok"]):
            raise AssertionError(
                f"step ok mismatch on {ep.agent} {ep.tier} seed={ep.seed} step={tool}"
            )
    replayed = env.result("replay")
    if abs(float(replayed.score) - float(ep.score)) > 1e-9:
        raise AssertionError(
            f"replay score mismatch on {ep.agent} {ep.tier} seed={ep.seed}: {replayed.score} != {ep.score}"
        )
    if replayed.accused != ep.accused:
        raise AssertionError(
            f"replay accused mismatch on {ep.agent} {ep.tier} seed={ep.seed}: {replayed.accused} != {ep.accused}"
        )
    if bool(replayed.correct) != bool(ep.correct):
        raise AssertionError(
            f"replay correct mismatch on {ep.agent} {ep.tier} seed={ep.seed}"
        )
    if int(replayed.final_day) != int(ep.final_day):
        raise AssertionError(
            f"replay final_day mismatch on {ep.agent} {ep.tier} seed={ep.seed}"
        )
    return True


def luck_adjusted_ev(ep: Any) -> float:
    from canary.analysis.accuse import audit_episode

    if not ep.accused:
        return 0.0
    aud = audit_episode(ep)
    p_acc = aud.get("p_accused")
    true_v = (ep.meta or {}).get("V")
    if p_acc is None or true_v is None:
        return float(ep.score)
    return float(p_acc) * float(true_v) - (1.0 - float(p_acc))


def bootstrap_ci(
    values: list[float],
    n_boot: int = 10_000,
    rng_seed: int = 20261115,
) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_halfwidth": 0.0}
    mean_val = float(np.mean(arr))
    if n < 2:
        return {
            "mean": round(mean_val, 6),
            "ci95_low": round(mean_val, 6),
            "ci95_high": round(mean_val, 6),
            "ci95_halfwidth": 0.0,
        }
    rng = np.random.default_rng(rng_seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = np.mean(arr[idx], axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    lo_f, hi_f = float(lo), float(hi)
    return {
        "mean": round(mean_val, 6),
        "ci95_low": round(lo_f, 6),
        "ci95_high": round(hi_f, 6),
        "ci95_halfwidth": round(0.5 * (hi_f - lo_f), 6),
    }


def paired_bootstrap_delta(
    after: list[float],
    before: list[float],
    n_boot: int = 10_000,
    rng_seed: int = 20261115,
) -> dict[str, float]:
    if len(after) != len(before):
        raise ValueError("paired arrays must have identical length")
    diffs = [float(a) - float(b) for a, b in zip(after, before)]
    return bootstrap_ci(diffs, n_boot=n_boot, rng_seed=rng_seed)


def _valid_call_rate(eps: list[Any]) -> float:
    total_steps = 0
    ok_steps = 0
    for ep in eps:
        for st in ep.steps:
            total_steps += 1
            _, _, res = _step_fields(st)
            if res.get("ok"):
                ok_steps += 1
    return round(ok_steps / max(1, total_steps), 6)


def _invalid_episode_count(eps: list[Any]) -> int:
    bad = 0
    for ep in eps:
        er = getattr(ep, "end_reason", None)
        meta = getattr(ep, "meta", None) or {}
        if er in ("error", "invalid") or meta.get("valid") is False:
            bad += 1
    return bad


def _planted_canary_count(ep: Any) -> int:
    cnt = 0
    for st in ep.steps:
        tool, _, res = _step_fields(st)
        if tool == "plant_canary" and res.get("ok"):
            cnt += 1
    return cnt


def summarize_episodes(eps: list[Any], luck_vals: list[float]) -> dict[str, Any]:
    n = max(1, len(eps))
    scores = [float(e.score) for e in eps]
    score_ci = bootstrap_ci(scores)
    luck_ci = bootstrap_ci(luck_vals)
    acc_days = [int(e.final_day) for e in eps if e.accused is not None]
    can_counts = [_planted_canary_count(e) for e in eps]
    n_correct = sum(1 for e in eps if e.accused is not None and bool(e.correct))
    n_wrong = sum(1 for e in eps if e.accused is not None and not bool(e.correct))
    n_abstain = sum(1 for e in eps if e.accused is None)
    return {
        "n": len(eps),
        "score": score_ci,
        "luck_adjusted_ev": luck_ci,
        "accuracy": round(n_correct / n, 6),
        "wrong_accuse_rate": round(n_wrong / n, 6),
        "abstain_rate": round(n_abstain / n, 6),
        "accused_rate": round((n_correct + n_wrong) / n, 6),
        "mean_accuse_day": round(float(np.mean(acc_days)), 4) if acc_days else None,
        "mean_canaries_planted": round(float(np.mean(can_counts)), 4) if can_counts else 0.0,
        "total_canaries_planted": int(sum(can_counts)),
        "correct_count": n_correct,
        "wrong_count": n_wrong,
        "abstain_count": n_abstain,
    }


def _load_committed_dev_hard(repo_root: Path, subdir: str, expected_seeds: list[int]) -> list[Any]:
    from canary.eval import episode_from_dict

    ep_file = repo_root / "data" / "runs" / "committed" / "v1.4" / subdir / "hard" / "episodes.jsonl"
    if not ep_file.exists():
        raise FileNotFoundError(f"missing committed frontier file: {ep_file}")
    by_seed: dict[int, Any] = {}
    for line in ep_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if (raw.get("meta") or {}).get("valid") is False:
            continue
        ep = episode_from_dict(raw)
        by_seed[int(ep.seed)] = ep
    missing = [s for s in expected_seeds if s not in by_seed]
    if missing:
        raise ValueError(f"committed {subdir} missing dev hard seeds: {missing}")
    return [by_seed[s] for s in expected_seeds]


HELDOUT_DELTA_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("eb_likelihood_only_minus_eb_naive_prior", "eb_likelihood_only", "eb_naive_prior"),
    ("eb_ev_stop_only_minus_eb_naive_prior", "eb_ev_stop_only", "eb_naive_prior"),
    ("eb_no_canary_planting_minus_eb_naive_prior", "eb_no_canary_planting", "eb_naive_prior"),
    ("eb_experience_opt_minus_eb_no_canary_planting", "eb_experience_opt", "eb_no_canary_planting"),
    ("eb_experience_opt_minus_eb_ev_stop_only", "eb_experience_opt", "eb_ev_stop_only"),
    ("eb_experience_opt_minus_eb_likelihood_only", "eb_experience_opt", "eb_likelihood_only"),
    ("eb_experience_opt_minus_eb_naive_prior", "eb_experience_opt", "eb_naive_prior"),
    ("eb_experience_opt_minus_heuristic", "eb_experience_opt", "heuristic"),
    ("eb_experience_opt_minus_solver", "eb_experience_opt", "solver"),
)


def _summarize_heldout_prefix(
    heldout_eps: dict[str, dict[str, list[Any]]],
    heldout_luck: dict[str, dict[str, list[float]]],
    agent_names: list[str],
    seeds_prefix: list[int],
    heldout_secret: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    k = len(seeds_prefix)
    by_tier: dict[str, Any] = {}
    overall: dict[str, Any] = {}
    paired_deltas: dict[str, Any] = {"by_tier": {}, "overall": {}}

    for tier in TIERS:
        by_tier[tier] = {
            name: summarize_episodes(heldout_eps[name][tier][:k], heldout_luck[name][tier][:k])
            for name in agent_names
        }
    for name in agent_names:
        pooled_eps = [ep for t in TIERS for ep in heldout_eps[name][t][:k]]
        pooled_luck = [lv for t in TIERS for lv in heldout_luck[name][t][:k]]
        overall[name] = summarize_episodes(pooled_eps, pooled_luck)

    for tier in TIERS:
        paired_deltas["by_tier"][tier] = {}
        for key, a_name, b_name in HELDOUT_DELTA_PAIRS:
            a_sc = [float(e.score) for e in heldout_eps[a_name][tier][:k]]
            b_sc = [float(e.score) for e in heldout_eps[b_name][tier][:k]]
            a_lu = heldout_luck[a_name][tier][:k]
            b_lu = heldout_luck[b_name][tier][:k]
            paired_deltas["by_tier"][tier][key] = {
                "score_delta": paired_bootstrap_delta(a_sc, b_sc),
                "luck_adjusted_delta": paired_bootstrap_delta(a_lu, b_lu),
            }

    for key, a_name, b_name in HELDOUT_DELTA_PAIRS:
        a_sc = [float(e.score) for t in TIERS for e in heldout_eps[a_name][t][:k]]
        b_sc = [float(e.score) for t in TIERS for e in heldout_eps[b_name][t][:k]]
        a_lu = [lv for t in TIERS for lv in heldout_luck[a_name][t][:k]]
        b_lu = [lv for t in TIERS for lv in heldout_luck[b_name][t][:k]]
        paired_deltas["overall"][key] = {
            "score_delta": paired_bootstrap_delta(a_sc, b_sc),
            "luck_adjusted_delta": paired_bootstrap_delta(a_lu, b_lu),
        }

    pooled_before_eps = [ep for t in TIERS for ep in heldout_eps["eb_naive_prior"][t][:k]]
    pooled_after_eps = [ep for t in TIERS for ep in heldout_eps["eb_experience_opt"][t][:k]]
    paired_episode_deltas = [
        round(float(a.score) - float(b.score), 6)
        for a, b in zip(pooled_after_eps, pooled_before_eps)
    ]
    headline_delta = paired_deltas["overall"]["eb_experience_opt_minus_eb_naive_prior"]["score_delta"]
    gate_metrics = {
        "n": len(pooled_after_eps),
        "before_mean_score": overall["eb_naive_prior"]["score"]["mean"],
        "after_mean_score": overall["eb_experience_opt"]["score"]["mean"],
        "before_valid_call_rate": _valid_call_rate(pooled_before_eps),
        "after_valid_call_rate": _valid_call_rate(pooled_after_eps),
        "before_invalid_episodes": _invalid_episode_count(pooled_before_eps),
        "after_invalid_episodes": _invalid_episode_count(pooled_after_eps),
        "paired_mean_delta": headline_delta["mean"],
        "paired_ci95_low": headline_delta["ci95_low"],
        "paired_ci95_high": headline_delta["ci95_high"],
        "paired_episode_deltas": paired_episode_deltas,
    }

    secret_fp = hashlib.sha256(heldout_secret.encode("utf-8")).hexdigest()[:12]
    block = {
        "world_secret_tag": heldout_secret,
        "world_secret_sha256_12": secret_fp,
        "eval_seed_range": f"{seeds_prefix[0]}..{seeds_prefix[-1]}",
        "eval_seeds": {"start": seeds_prefix[0], "stop": seeds_prefix[-1] + 1},
        "tiers": list(TIERS),
        "n_per_tier": k,
        "n_total_per_agent": k * len(TIERS),
        "episodes_replayed": k * len(TIERS) * len(agent_names),
        "replay_verified": True,
        "by_tier": by_tier,
        "overall": overall,
        "paired_deltas": paired_deltas,
    }
    return block, gate_metrics


def evaluate_heldout_and_dev(
    stage1_params: EmpiricalBayesParams,
    stage2_params: EmpiricalBayesParams,
    stage3_params: EmpiricalBayesParams,
    heldout_seeds: list[int],
    dev_seeds: list[int],
    repo_root: Path,
    heldout_secret: str = HELDOUT_SECRET_TAG,
) -> dict[str, Any]:
    from canary import world as canary_world
    from canary.env import Env
    from canary.eval import make_policy_factory, run_episode

    solver_factory = make_policy_factory("solver")
    heuristic_factory = make_policy_factory("heuristic")
    variant_params = build_ablation_variant_params(stage1_params, stage2_params, stage3_params)

    agent_specs: list[tuple[str, Any]] = [
        (
            v_name,
            (lambda vp, vn: lambda s: EmpiricalBayesPolicy(vp, seed=s, name=vn))(
                variant_params[v_name], v_name
            ),
        )
        for v_name in ABLATION_VARIANTS
    ] + [
        ("heuristic", heuristic_factory),
        ("solver", solver_factory),
    ]
    agent_names = [name for name, _ in agent_specs]

    prev_secret = os.environ.get("CANARY_WORLD_SECRET")
    prev_set_secret = getattr(canary_world, "_SET_SECRET", None)
    heldout_eps: dict[str, dict[str, list[Any]]] = {name: {} for name in agent_names}
    heldout_luck: dict[str, dict[str, list[float]]] = {name: {} for name in agent_names}
    n_replayed_heldout = 0

    try:
        canary_world.set_world_secret(None)
        os.environ["CANARY_WORLD_SECRET"] = heldout_secret
        for tier in TIERS:
            for name, factory in agent_specs:
                eps_t: list[Any] = []
                luck_t: list[float] = []
                for seed in heldout_seeds:
                    ep = run_episode(Env(tier, seed), factory(seed))
                    replay_verify_episode(ep)
                    n_replayed_heldout += 1
                    eps_t.append(ep)
                    luck_t.append(luck_adjusted_ev(ep))
                heldout_eps[name][tier] = eps_t
                heldout_luck[name][tier] = luck_t
    finally:
        canary_world.set_world_secret(prev_set_secret)
        if prev_secret is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_secret

    heldout_full_block, gate_metrics = _summarize_heldout_prefix(
        heldout_eps=heldout_eps,
        heldout_luck=heldout_luck,
        agent_names=agent_names,
        seeds_prefix=heldout_seeds,
        heldout_secret=heldout_secret,
    )
    heldout_full_block["episodes_replayed"] = n_replayed_heldout

    n90_k = min(HELDOUT_N90_SUBSET_COUNT, len(heldout_seeds))
    heldout_n90_block, gate_metrics_n90 = _summarize_heldout_prefix(
        heldout_eps=heldout_eps,
        heldout_luck=heldout_luck,
        agent_names=agent_names,
        seeds_prefix=heldout_seeds[:n90_k],
        heldout_secret=heldout_secret,
    )
    heldout_n90_block["before_after_gate"] = gate_metrics_n90

    ablation_rows: list[dict[str, Any]] = []
    zero_delta = {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_halfwidth": 0.0}
    for v_name in ABLATION_VARIANTS:
        meta_info = ABLATION_MECHANISM_NOTES[v_name]
        v_sc_full = [float(e.score) for t in TIERS for e in heldout_eps[v_name][t]]
        n_sc_full = [float(e.score) for t in TIERS for e in heldout_eps["eb_naive_prior"][t]]
        o_sc_full = [float(e.score) for t in TIERS for e in heldout_eps["eb_experience_opt"][t]]
        v_lu_full = [lv for t in TIERS for lv in heldout_luck[v_name][t]]
        n_lu_full = [lv for t in TIERS for lv in heldout_luck["eb_naive_prior"][t]]
        o_lu_full = [lv for t in TIERS for lv in heldout_luck["eb_experience_opt"][t]]

        delta_vs_naive = (
            zero_delta
            if v_name == "eb_naive_prior"
            else paired_bootstrap_delta(v_sc_full, n_sc_full)
        )
        luck_delta_vs_naive = (
            zero_delta
            if v_name == "eb_naive_prior"
            else paired_bootstrap_delta(v_lu_full, n_lu_full)
        )
        delta_vs_opt = (
            zero_delta
            if v_name == "eb_experience_opt"
            else paired_bootstrap_delta(v_sc_full, o_sc_full)
        )
        ablation_rows.append(
            {
                "variant": v_name,
                **meta_info,
                "parameters": variant_params[v_name].to_dict(),
                "n180_overall": heldout_full_block["overall"][v_name],
                "n180_by_tier": {t: heldout_full_block["by_tier"][t][v_name] for t in TIERS},
                "n90_overall": heldout_n90_block["overall"][v_name],
                "paired_score_delta_vs_naive_prior": delta_vs_naive,
                "paired_luck_delta_vs_naive_prior": luck_delta_vs_naive,
                "paired_score_delta_vs_experience_opt": delta_vs_opt,
            }
        )

    component_ablation_matrix = {
        "eval_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
        "n_per_tier": len(heldout_seeds),
        "n_total_per_variant": len(heldout_seeds) * len(TIERS),
        "world_secret_tag": heldout_secret,
        "world_secret_sha256_12": heldout_full_block["world_secret_sha256_12"],
        "replay_verified": True,
        "episodes_replayed": len(ABLATION_VARIANTS) * len(heldout_seeds) * len(TIERS),
        "variants": ablation_rows,
    }

    prev_dev_secret = os.environ.pop("CANARY_WORLD_SECRET", None)
    prev_dev_set_secret = getattr(canary_world, "_SET_SECRET", None)
    dev_eps: dict[str, list[Any]] = {}
    dev_luck: dict[str, list[float]] = {}
    n_replayed_dev = 0
    try:
        canary_world.set_world_secret(None)
        for name, factory in agent_specs:
            eps_d: list[Any] = []
            luck_d: list[float] = []
            for seed in dev_seeds:
                ep = run_episode(Env("hard", seed), factory(seed))
                replay_verify_episode(ep)
                n_replayed_dev += 1
                eps_d.append(ep)
                luck_d.append(luck_adjusted_ev(ep))
            dev_eps[name] = eps_d
            dev_luck[name] = luck_d

        for frontier_key, subdir in (
            ("opencode:google/gemini-4-carbon", "opencode-gemini-4-carbon"),
            ("gemini:gemini-4-carbon", "inproc-gemini-4-carbon"),
        ):
            c_eps = _load_committed_dev_hard(repo_root, subdir, dev_seeds)
            c_luck: list[float] = []
            for ep in c_eps:
                replay_verify_episode(ep)
                n_replayed_dev += 1
                c_luck.append(luck_adjusted_ev(ep))
            dev_eps[frontier_key] = c_eps
            dev_luck[frontier_key] = c_luck
    finally:
        canary_world.set_world_secret(prev_dev_set_secret)
        if prev_dev_secret is not None:
            os.environ["CANARY_WORLD_SECRET"] = prev_dev_secret

    dev_agents_order = list(ABLATION_VARIANTS) + [
        "heuristic",
        "opencode:google/gemini-4-carbon",
        "gemini:gemini-4-carbon",
        "solver",
    ]
    dev_delta_pairs = list(HELDOUT_DELTA_PAIRS) + [
        (
            "eb_experience_opt_minus_opencode_gemini_4_carbon",
            "eb_experience_opt",
            "opencode:google/gemini-4-carbon",
        ),
        (
            "eb_experience_opt_minus_inproc_gemini_4_carbon",
            "eb_experience_opt",
            "gemini:gemini-4-carbon",
        ),
    ]
    dev_range_str = f"{dev_seeds[0]}..{dev_seeds[-1]}"
    dev_summary: dict[str, Any] = {
        "protocol_label": f"post-hoc locked dev hard {dev_range_str}",
        "tier": "hard",
        "world_key": "public",
        "eval_seed_range": dev_range_str,
        "n_seeds": len(dev_seeds),
        "agents": {
            name: summarize_episodes(dev_eps[name], dev_luck[name])
            for name in dev_agents_order
        },
        "paired_deltas": {
            key: {
                "score_delta": paired_bootstrap_delta(
                    [float(e.score) for e in dev_eps[a_name]],
                    [float(e.score) for e in dev_eps[b_name]],
                ),
                "luck_adjusted_delta": paired_bootstrap_delta(
                    dev_luck[a_name],
                    dev_luck[b_name],
                ),
            }
            for key, a_name, b_name in dev_delta_pairs
        },
    }

    return {
        "variant_params": variant_params,
        "gate_metrics": gate_metrics,
        "heldout": heldout_full_block,
        "heldout_n90": heldout_n90_block,
        "component_ablation_matrix": component_ablation_matrix,
        "dev_hard": {
            "episodes_replayed": n_replayed_dev,
            **dev_summary,
        },
        "total_episodes_replayed": n_replayed_heldout + n_replayed_dev,
    }


def _fmt_ci(d: dict[str, float], signed: bool = True) -> str:
    m = d["mean"]
    lo = d["ci95_low"]
    hi = d["ci95_high"]
    if signed:
        return f"{m:+.3f} [{lo:+.3f}, {hi:+.3f}]"
    return f"{m:.3f} [{lo:.3f}, {hi:.3f}]"


def format_markdown_report(summary: dict[str, Any]) -> str:
    ho = summary["heldout"]
    ho90 = summary["heldout_n90"]
    dh = summary["dev_hard"]
    ab_map = {row["variant"]: row for row in summary["component_ablation_matrix"]["variants"]}
    all_eval_agents = list(ABLATION_VARIANTS) + ["heuristic", "solver"]

    lines: list[str] = []
    lines.append("EmpiricalBayesPolicy Tiebreaker and Component Ablation Report (Canary v1.4)")
    lines.append("===========================================================================")
    lines.append("")
    lines.append(
        f"- Train seed range: `{summary['train_seed_range']}` "
        f"(Stage 2 likelihoods `{summary['stage2_seed_range']}`, Stage 3 stopping/splits `{summary['stage3_seed_range']}`)"
    )
    lines.append(
        f"- Primary held-out eval seed range: `{ho['eval_seed_range']}` across `easy, medium, hard` "
        f"(`n={ho['n_per_tier']}/tier`, `{ho['n_total_per_agent']}` episodes/variant, matching `v3-4k-s0` `n=180` scale)"
    )
    lines.append(
        f"- Retained held-out subset seed range: `{ho90['eval_seed_range']}` across `easy, medium, hard` "
        f"(`n={ho90['n_per_tier']}/tier`, `{ho90['n_total_per_agent']}` episodes/variant for exact `n=90` cross-comparisons)"
    )
    lines.append(
        f"- Held-out world secret tag: `{summary['world_secret_tag']}` "
        f"(sha256 prefix `{ho['world_secret_sha256_12']}`, shared across all paired held-out variants)"
    )
    lines.append(
        f"- Keyless reference benchmark: `{dh['protocol_label']}` "
        f"(`b\"public\"`, `n={dh['n_seeds']}`, paired vs `solver` and committed `gemini-4-carbon`)"
    )
    lines.append(
        f"- Tool-by-tool Env replay verified: `{summary['replay_verified']}` "
        f"(`{summary['total_episodes_replayed']}` episodes replayed with zero mismatches)"
    )

    lines.append("")
    sec1 = "1. Learned Parameter and Component Ablation Configurations (TRAIN_SEEDS 102000..102779)"
    lines.append(sec1)
    lines.append("-" * len(sec1))
    lines.append("")
    lines.append(
        "| Variant | w_canary_hit | w_canary_miss | w_doc_hit | w_after_hours | w_evasive | w_angry_msg | tau_margin | unsurfaced_v_disc | canary_cov | tiny_pool | ev_stop |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for st_name in ABLATION_VARIANTS:
        p = summary["parameters"][st_name]
        lines.append(
            f"| {st_name} | {p['w_canary_hit']:+.3f} | {p['w_canary_miss']:+.3f} | {p['w_doc_hit']:+.3f} | "
            f"{p['w_after_hours']:+.3f} | {p['w_evasive']:+.3f} | {p['w_angry_msg']:+.3f} | "
            f"{p['tau_margin']:.2f} | {p['unsurfaced_v_discount']:.2f} | {p['canary_coverage']:.2f} | "
            f"{p['tiny_pool_size']} | {p['use_ev_stopping']} |"
        )

    lines.append("")
    sec2 = (
        f"2. Component Ablation Matrix and Held-Out Overall Progression "
        f"(Seeds {ho['eval_seed_range']}, n={ho['n_total_per_agent']}, Plus Exact Seeds {ho90['eval_seed_range']}, n={ho90['n_total_per_agent']})"
    )
    lines.append(sec2)
    lines.append("-" * len(sec2))
    lines.append("")
    lines.append(
        f"Primary held-out evaluation on `{ho['eval_seed_range']}` (`n={ho['n_per_tier']}/tier = {ho['n_total_per_agent']}` episodes, shared secret `{summary['world_secret_tag']}`, 100% Env replay-verified):"
    )
    lines.append("")
    lines.append(
        "| Agent / Variant | Mechanism Isolated | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for ag in all_eval_agents:
        r = ho["overall"][ag]
        mech = (
            ab_map[ag]["mechanism"]
            if ag in ab_map
            else ("Scripted heuristic baseline" if ag == "heuristic" else "Exact Bayesian reference solver")
        )
        day_s = f"{r['mean_accuse_day']:.1f}" if r["mean_accuse_day"] is not None else "-"
        lines.append(
            f"| {ag} | {mech} | {r['n']} | {r['mean_canaries_planted']:.2f} | {_fmt_ci(r['score'])} | "
            f"{_fmt_ci(r['luck_adjusted_ev'])} | {r['accuracy']:.3f} | {r['wrong_accuse_rate']:.3f} | "
            f"{r['abstain_rate']:.3f} | {day_s} |"
        )

    lines.append("")
    lines.append(
        f"Retained exact `n={ho90['n_total_per_agent']}` subset on `{ho90['eval_seed_range']}` (`n={ho90['n_per_tier']}/tier`, shared secret `{summary['world_secret_tag']}`):"
    )
    lines.append("")
    lines.append(
        "| Agent / Variant | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for ag in all_eval_agents:
        r90 = ho90["overall"][ag]
        day_s = f"{r90['mean_accuse_day']:.1f}" if r90["mean_accuse_day"] is not None else "-"
        lines.append(
            f"| {ag} | {r90['n']} | {r90['mean_canaries_planted']:.2f} | {_fmt_ci(r90['score'])} | "
            f"{_fmt_ci(r90['luck_adjusted_ev'])} | {r90['accuracy']:.3f} | {r90['wrong_accuse_rate']:.3f} | "
            f"{r90['abstain_rate']:.3f} | {day_s} |"
        )

    lines.append("")
    sec3 = (
        f"3. Held-Out Per-Tier Results (Seeds {ho['eval_seed_range']}, n={ho['n_per_tier']}/tier, "
        f"and Seeds {ho90['eval_seed_range']}, n={ho90['n_per_tier']}/tier)"
    )
    lines.append(sec3)
    lines.append("-" * len(sec3))
    lines.append("")
    lines.append(f"Full held-out per-tier breakdown (`{ho['eval_seed_range']}`, `n={ho['n_per_tier']}/tier`):")
    lines.append("")
    lines.append(
        "| Tier | Agent / Variant | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for tier in TIERS:
        for ag in all_eval_agents:
            r = ho["by_tier"][tier][ag]
            day_s = f"{r['mean_accuse_day']:.1f}" if r["mean_accuse_day"] is not None else "-"
            lines.append(
                f"| {tier} | {ag} | {r['n']} | {r['mean_canaries_planted']:.2f} | {_fmt_ci(r['score'])} | "
                f"{_fmt_ci(r['luck_adjusted_ev'])} | {r['accuracy']:.3f} | {r['wrong_accuse_rate']:.3f} | "
                f"{r['abstain_rate']:.3f} | {day_s} |"
            )

    lines.append("")
    lines.append(f"Retained `n={ho90['n_per_tier']}/tier` per-tier breakdown (`{ho90['eval_seed_range']}`):")
    lines.append("")
    lines.append(
        "| Tier | Agent / Variant | n | Canaries/Ep | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for tier in TIERS:
        for ag in all_eval_agents:
            r90 = ho90["by_tier"][tier][ag]
            day_s = f"{r90['mean_accuse_day']:.1f}" if r90["mean_accuse_day"] is not None else "-"
            lines.append(
                f"| {tier} | {ag} | {r90['n']} | {r90['mean_canaries_planted']:.2f} | {_fmt_ci(r90['score'])} | "
                f"{_fmt_ci(r90['luck_adjusted_ev'])} | {r90['accuracy']:.3f} | {r90['wrong_accuse_rate']:.3f} | "
                f"{r90['abstain_rate']:.3f} | {day_s} |"
            )

    lines.append("")
    sec4 = "4. Paired Held-Out Ablation and Before/After Deltas (95% Paired Bootstrap CI)"
    lines.append(sec4)
    lines.append("-" * len(sec4))
    lines.append("")
    lines.append("| Scope | Comparison (After - Before) | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |")
    lines.append("|---|---|---:|---:|")
    delta_labels = [
        ("eb_likelihood_only_minus_eb_naive_prior", "eb_likelihood_only - eb_naive_prior"),
        ("eb_ev_stop_only_minus_eb_naive_prior", "eb_ev_stop_only - eb_naive_prior"),
        ("eb_no_canary_planting_minus_eb_naive_prior", "eb_no_canary_planting - eb_naive_prior"),
        ("eb_experience_opt_minus_eb_no_canary_planting", "eb_experience_opt - eb_no_canary_planting"),
        ("eb_experience_opt_minus_eb_ev_stop_only", "eb_experience_opt - eb_ev_stop_only"),
        ("eb_experience_opt_minus_eb_likelihood_only", "eb_experience_opt - eb_likelihood_only"),
        ("eb_experience_opt_minus_eb_naive_prior", "eb_experience_opt - eb_naive_prior"),
        ("eb_experience_opt_minus_heuristic", "eb_experience_opt - heuristic"),
        ("eb_experience_opt_minus_solver", "eb_experience_opt - solver"),
    ]
    for key, label in delta_labels:
        d_ov = ho["paired_deltas"]["overall"][key]
        lines.append(
            f"| overall {ho['eval_seed_range']} (n={ho['n_total_per_agent']}) | {label} | {_fmt_ci(d_ov['score_delta'])} | {_fmt_ci(d_ov['luck_adjusted_delta'])} |"
        )
    for key, label in delta_labels:
        d_ov90 = ho90["paired_deltas"]["overall"][key]
        lines.append(
            f"| subset {ho90['eval_seed_range']} (n={ho90['n_total_per_agent']}) | {label} | {_fmt_ci(d_ov90['score_delta'])} | {_fmt_ci(d_ov90['luck_adjusted_delta'])} |"
        )
    tier_delta_subset = [
        ("eb_likelihood_only_minus_eb_naive_prior", "eb_likelihood_only - eb_naive_prior"),
        ("eb_ev_stop_only_minus_eb_naive_prior", "eb_ev_stop_only - eb_naive_prior"),
        ("eb_experience_opt_minus_eb_no_canary_planting", "eb_experience_opt - eb_no_canary_planting"),
        ("eb_experience_opt_minus_eb_likelihood_only", "eb_experience_opt - eb_likelihood_only"),
        ("eb_experience_opt_minus_eb_naive_prior", "eb_experience_opt - eb_naive_prior"),
        ("eb_experience_opt_minus_heuristic", "eb_experience_opt - heuristic"),
    ]
    for tier in TIERS:
        for key, label in tier_delta_subset:
            d_tr = ho["paired_deltas"]["by_tier"][tier][key]
            lines.append(
                f"| {tier} {ho['eval_seed_range']} (n={ho['n_per_tier']}) | {label} | {_fmt_ci(d_tr['score_delta'])} | {_fmt_ci(d_tr['luck_adjusted_delta'])} |"
            )

    lines.append("")
    sec5 = (
        f"5. Keyless Reference Comparison on Post-Hoc Locked Dev Hard {dh['eval_seed_range']} "
        f"vs Solver and Committed gemini-4-carbon (n={dh['n_seeds']})"
    )
    lines.append(sec5)
    lines.append("-" * len(sec5))
    lines.append("")
    lines.append(
        f"- Seed protocol: `{dh['protocol_label']}` keyless public worlds (`b\"public\"`, locked after primary commitment to prevent cherry-picking; evaluated with zero LLM API calls against committed `gemini-4-carbon` episodes and in-process `solver`)."
    )
    lines.append("")
    lines.append(
        "| Agent / Variant | n | Score [95% Bootstrap CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Mean Accuse Day |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for ag in list(ABLATION_VARIANTS) + [
        "heuristic",
        "opencode:google/gemini-4-carbon",
        "gemini:gemini-4-carbon",
        "solver",
    ]:
        r = dh["agents"][ag]
        day_s = f"{r['mean_accuse_day']:.1f}" if r["mean_accuse_day"] is not None else "-"
        lines.append(
            f"| {ag} | {r['n']} | {_fmt_ci(r['score'])} | {_fmt_ci(r['luck_adjusted_ev'])} | "
            f"{r['accuracy']:.3f} | {r['wrong_accuse_rate']:.3f} | {r['abstain_rate']:.3f} | {day_s} |"
        )

    lines.append("")
    lines.append(
        f"| Post-Hoc Locked Dev Hard {dh['eval_seed_range']} Paired Comparison | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |"
    )
    lines.append("|---|---:|---:|")
    for key, label in [
        ("eb_experience_opt_minus_eb_naive_prior", "eb_experience_opt - eb_naive_prior"),
        ("eb_experience_opt_minus_eb_ev_stop_only", "eb_experience_opt - eb_ev_stop_only"),
        ("eb_experience_opt_minus_eb_no_canary_planting", "eb_experience_opt - eb_no_canary_planting"),
        ("eb_experience_opt_minus_eb_likelihood_only", "eb_experience_opt - eb_likelihood_only"),
        ("eb_experience_opt_minus_heuristic", "eb_experience_opt - heuristic"),
        ("eb_experience_opt_minus_opencode_gemini_4_carbon", "eb_experience_opt - opencode:google/gemini-4-carbon"),
        ("eb_experience_opt_minus_inproc_gemini_4_carbon", "eb_experience_opt - gemini:gemini-4-carbon"),
        ("eb_experience_opt_minus_solver", "eb_experience_opt - solver"),
    ]:
        d_dev = dh["paired_deltas"][key]
        lines.append(f"| {label} | {_fmt_ci(d_dev['score_delta'])} | {_fmt_ci(d_dev['luck_adjusted_delta'])} |")

    lines.append("")
    sec6 = f"6. Stage 3 Training Search Ledger (TRAIN_SEEDS {summary['stage3_seed_range']}, Including Suboptimal Configs)"
    lines.append(sec6)
    lines.append("-" * len(sec6))
    lines.append("")
    lines.append("| Phase | canary_cov | tiny_pool | tau_margin | unsurfaced_v_disc | ev_stop | Train Mean Score | Accuracy | Wrong | Abstain |")
    lines.append("|---|---:|---:|---:|---:|---|---:|---:|---:|---:|")
    for row in summary["training"]["stage3"]["search_ledger"]:
        lines.append(
            f"| {row['phase']} | {row['canary_coverage']:.2f} | {row['tiny_pool_size']} | "
            f"{row['tau_margin']:.2f} | {row['unsurfaced_v_discount']:.2f} | {row['use_ev_stopping']} | "
            f"{row['mean_score']:+.3f} | {row['accuracy']:.3f} | {row['wrong_accuse_rate']:.3f} | {row['abstain_rate']:.3f} |"
        )

    return "\n".join(lines) + "\n"


def run_full_pipeline(
    stage2_count: int = 180,
    stage3_count: int = 180,
    heldout_count: int = 60,
    dev_count: int = 30,
    checkpoint_dir: str = DEFAULT_CHECKPOINT_DIR,
    results_dir: str = DEFAULT_RESULTS_DIR,
    heldout_secret: str = HELDOUT_SECRET_TAG,
    workers: int = 1,
) -> dict[str, Any]:
    if workers != 1:
        raise ValueError("EmpiricalBayesPolicy pipeline enforces --workers 1 for shared CPU hygiene")
    t0 = time.time()
    repo_root = Path(__file__).resolve().parents[1]

    stage2_seeds = list(range(STAGE2_TRAIN_RANGE[0], STAGE2_TRAIN_RANGE[0] + stage2_count))
    stage3_seeds = list(range(STAGE3_TRAIN_RANGE[0], STAGE3_TRAIN_RANGE[0] + stage3_count))
    heldout_seeds = list(range(HELDOUT_EVAL_RANGE[0], HELDOUT_EVAL_RANGE[0] + heldout_count))
    dev_seeds = list(range(DEV_HARD_EVAL_RANGE[0], DEV_HARD_EVAL_RANGE[0] + dev_count))

    validate_seed_partition(stage2_seeds, stage3_seeds, heldout_seeds, dev_seeds)

    stage1_params = make_naive_prior_params()
    stage2_params, stage2_stats = fit_empirical_likelihoods(stage2_seeds, laplace_alpha=1.0)
    stage3_params, stage3_stats = optimize_stopping_and_splits(stage2_params, stage3_seeds)
    variant_params = build_ablation_variant_params(stage1_params, stage2_params, stage3_params)

    ckpt_path = Path(checkpoint_dir)
    ckpt_path.mkdir(parents=True, exist_ok=True)
    checkpoints_payload = {
        "train_seed_range": f"{stage2_seeds[0]}..{stage3_seeds[-1]}",
        "stage2_seed_range": f"{stage2_seeds[0]}..{stage2_seeds[-1]}",
        "stage3_seed_range": f"{stage3_seeds[0]}..{stage3_seeds[-1]}",
        **{v_name: variant_params[v_name].to_dict() for v_name in ABLATION_VARIANTS},
        "eb_likelihood_learned": variant_params["eb_likelihood_only"].to_dict(),
    }
    (ckpt_path / "checkpoints.json").write_text(
        json.dumps(checkpoints_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    eval_out = evaluate_heldout_and_dev(
        stage1_params=stage1_params,
        stage2_params=stage2_params,
        stage3_params=stage3_params,
        heldout_seeds=heldout_seeds,
        dev_seeds=dev_seeds,
        repo_root=repo_root,
        heldout_secret=heldout_secret,
    )

    elapsed = round(time.time() - t0, 2)
    gm = eval_out["gate_metrics"]
    if gm["before_invalid_episodes"] != 0 or gm["after_invalid_episodes"] != 0:
        raise AssertionError("EmpiricalBayesPolicy produced invalid or error episodes")
    secret_sha256_tag = "sha256:" + hashlib.sha256(heldout_secret.encode("utf-8")).hexdigest()[:16]
    headline_delta = eval_out["heldout"]["paired_deltas"]["overall"]["eb_experience_opt_minus_eb_naive_prior"]["score_delta"]
    headline_luck_delta = eval_out["heldout"]["paired_deltas"]["overall"]["eb_experience_opt_minus_eb_naive_prior"]["luck_adjusted_delta"]
    headline_n90_delta = eval_out["heldout_n90"]["paired_deltas"]["overall"]["eb_experience_opt_minus_eb_naive_prior"]["score_delta"]
    summary: dict[str, Any] = {
        "run_id": "empirical-bayes-v14",
        "model": "EmpiricalBayesPolicy (likelihood + optimal stopping learned on TRAIN_SEEDS)",
        "tiers_version": "v1.4",
        "tiers": list(TIERS),
        "n": gm["n"],
        "train_seeds": {"start": stage2_seeds[0], "stop": stage3_seeds[-1] + 1},
        "eval_seeds": {"start": heldout_seeds[0], "stop": heldout_seeds[-1] + 1},
        "replay_verified": True,
        "invalid_episodes": 0,
        "before": {
            "n": gm["n"],
            "mean_score": gm["before_mean_score"],
            "valid_call_rate": gm["before_valid_call_rate"],
            "world_secret_tag": secret_sha256_tag,
            "replay_verified": True,
            "invalid_episodes": gm["before_invalid_episodes"],
        },
        "after": {
            "n": gm["n"],
            "mean_score": gm["after_mean_score"],
            "valid_call_rate": gm["after_valid_call_rate"],
            "world_secret_tag": secret_sha256_tag,
            "replay_verified": True,
            "invalid_episodes": gm["after_invalid_episodes"],
        },
        "paired": {
            "mean_delta": headline_delta["mean"],
            "ci95_low": headline_delta["ci95_low"],
            "ci95_high": headline_delta["ci95_high"],
            "deltas": gm["paired_episode_deltas"],
        },
        "notes": (
            f"Learned log-likelihood ratios ({stage2_count} eps) + optimal stopping/splits ({stage3_count} eps) "
            f"strictly on TRAIN_SEEDS; paired held-out n={gm['n']} (800000..{heldout_seeds[-1]}) "
            f"luck-adjusted EV delta {headline_luck_delta['mean']:+.3f} "
            f"(n={eval_out['heldout_n90']['n_total_per_agent']} subset score delta {headline_n90_delta['mean']:+.3f})."
        ),
        "world_secret_tag": heldout_secret,
        "train_seed_range": f"{stage2_seeds[0]}..{stage3_seeds[-1]}",
        "stage2_seed_range": f"{stage2_seeds[0]}..{stage2_seeds[-1]}",
        "stage3_seed_range": f"{stage3_seeds[0]}..{stage3_seeds[-1]}",
        "eval_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
        "eval_n90_seed_range": eval_out["heldout_n90"]["eval_seed_range"],
        "dev_eval_seed_range": f"{dev_seeds[0]}..{dev_seeds[-1]}",
        "dev_protocol_label": eval_out["dev_hard"]["protocol_label"],
        "total_episodes_replayed": eval_out["total_episodes_replayed"],
        "workers": workers,
        "elapsed_seconds": elapsed,
        "parameters": {
            **{v_name: variant_params[v_name].to_dict() for v_name in ABLATION_VARIANTS},
            "eb_likelihood_learned": variant_params["eb_likelihood_only"].to_dict(),
        },
        "learned_theta": {
            **{v_name: variant_params[v_name].theta_dict() for v_name in ABLATION_VARIANTS},
            "eb_likelihood_learned": variant_params["eb_likelihood_only"].theta_dict(),
        },
        "headline_heldout_improvement": headline_delta,
        "headline_heldout_n90_improvement": headline_n90_delta,
        "component_ablation_matrix": eval_out["component_ablation_matrix"],
        "training": {
            "stage2": stage2_stats,
            "stage3": stage3_stats,
        },
        "heldout": eval_out["heldout"],
        "heldout_n90": eval_out["heldout_n90"],
        "dev_hard": eval_out["dev_hard"],
    }

    res_path = Path(results_dir)
    if not res_path.is_absolute():
        res_path = repo_root / res_path
    res_path.mkdir(parents=True, exist_ok=True)
    (res_path / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    md_text = format_markdown_report(summary)
    (res_path / "table.md").write_text(md_text, encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage2-n", type=int, default=180)
    ap.add_argument("--stage3-n", type=int, default=180)
    ap.add_argument("--heldout-n", type=int, default=60)
    ap.add_argument("--dev-n", type=int, default=30)
    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR)
    ap.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    ap.add_argument("--heldout-secret", default=HELDOUT_SECRET_TAG)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args(argv)
    summary = run_full_pipeline(
        stage2_count=args.stage2_n,
        stage3_count=args.stage3_n,
        heldout_count=args.heldout_n,
        dev_count=args.dev_n,
        checkpoint_dir=args.checkpoint_dir,
        results_dir=args.results_dir,
        heldout_secret=args.heldout_secret,
        workers=args.workers,
    )
    print(
        json.dumps(
            {
                "replay_verified": summary["replay_verified"],
                "elapsed_seconds": summary["elapsed_seconds"],
                "n": summary["n"],
                "total_episodes_replayed": summary["total_episodes_replayed"],
                "headline_heldout_n180_improvement": summary["headline_heldout_improvement"],
                "headline_heldout_n90_improvement": summary["headline_heldout_n90_improvement"],
                "heldout_n180_eb_naive_prior": summary["heldout"]["overall"]["eb_naive_prior"]["score"],
                "heldout_n180_eb_likelihood_only": summary["heldout"]["overall"]["eb_likelihood_only"]["score"],
                "heldout_n180_eb_ev_stop_only": summary["heldout"]["overall"]["eb_ev_stop_only"]["score"],
                "heldout_n180_eb_no_canary_planting": summary["heldout"]["overall"]["eb_no_canary_planting"]["score"],
                "heldout_n180_eb_experience_opt": summary["heldout"]["overall"]["eb_experience_opt"]["score"],
                "heldout_n180_solver": summary["heldout"]["overall"]["solver"]["score"],
                "heldout_n90_eb_experience_opt": summary["heldout_n90"]["overall"]["eb_experience_opt"]["score"],
                "dev_hard_protocol": summary["dev_hard"]["protocol_label"],
                "dev_hard_eb_experience_opt": summary["dev_hard"]["agents"]["eb_experience_opt"]["score"],
                "dev_hard_opencode_carbon": summary["dev_hard"]["agents"]["opencode:google/gemini-4-carbon"]["score"],
                "dev_hard_solver": summary["dev_hard"]["agents"]["solver"]["score"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
