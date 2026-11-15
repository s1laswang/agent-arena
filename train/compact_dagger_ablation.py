from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import time
from typing import Any

os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import numpy as np

from train.compact_render import (
    INVESTIGATIVE_TOOLS,
    _is_angry,
    _is_evasive,
    parse_instruction_params,
)

LABELS = "ABCDEFGH"
TIERS: tuple[str, ...] = ("easy", "medium", "hard")

ACTION_NAMES: tuple[str, ...] = (
    "list_employees",
    "status",
    "list_documents",
    "check_leak_feed",
    "search_messages",
    "read_access_logs",
    "plant_canary",
    "advance_day",
    "accuse",
)
ACTION_TO_IDX: dict[str, int] = {name: idx for idx, name in enumerate(ACTION_NAMES)}

SPLIT_MODES: tuple[str, ...] = (
    "tiny_1x3",
    "tiny_2x3",
    "focused_cov35",
    "balanced_cov60",
    "broad_cov85",
    "full_cov100",
)
SPLIT_TO_IDX: dict[str, int] = {name: idx for idx, name in enumerate(SPLIT_MODES)}

ANGER_WORDS: tuple[str, ...] = (
    "promotion",
    "raise",
    "deserve",
    "burn out",
    "recruiter",
    "goalposts",
    "nobody asks",
    "updating my cv",
)

STAGE_NAMES: tuple[str, ...] = (
    "stage0_untrained",
    "stage1_survivorship_sft",
    "stage2_calibrated_bc",
    "stage3_onpolicy_dagger_r2",
)

ALL_ABLATION_STAGES: tuple[str, ...] = (
    "stage0_untrained",
    "stage1_survivorship_sft",
    "stage2_calibrated_bc",
    "stage3a_onpolicy_dagger_r1",
    "stage3_onpolicy_dagger_r2",
)

TRAIN_SEED_START = 109_000
TRAIN_SEED_STOP = 109_510
OFFLINE_SEED_RANGE: tuple[int, int] = (109_000, 109_150)
DAGGER_R1_SEED_RANGE: tuple[int, int] = (109_150, 109_300)
DAGGER_R2_SEED_RANGE: tuple[int, int] = (109_300, 109_450)
VAL_SEED_RANGE: tuple[int, int] = (109_450, 109_510)
HELDOUT_SEED_RANGE: tuple[int, int] = (800_000, 800_060)
DEV_HARD_SEED_RANGE: tuple[int, int] = (0, 30)

HELDOUT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"
RUN_ID = "compact-linear-dagger-v14"
MODEL_LABEL = "CompactLinearDAggerPolicy (4-stage SFT vs BC vs On-Policy DAgger)"
INFERENCE_MODULE_REL = "train/compact_dagger_ablation.py"
DEFAULT_SUMMARY_PATH = "results/tiebreak/dagger_ablation/summary.json"
DEFAULT_TABLE_PATH = "results/tiebreak/dagger_ablation/table.md"
DEFAULT_CKPT_PATH = "/tmp/fleet-silas/shared/tiebreak-v100/dagger_ablation_ckpt.json"

D_EMP = 28
D_ACT = 62
D_SPLIT = 26
N_ACT = len(ACTION_NAMES)
N_SPLIT = len(SPLIT_MODES)


def _step_parts(st: Any) -> tuple[str, dict[str, Any], dict[str, Any]]:
    if isinstance(st, dict):
        tool = str(st.get("tool", ""))
        args = st.get("args")
        res = st.get("result")
    else:
        tool = str(getattr(st, "tool", ""))
        args = getattr(st, "args", None)
        res = getattr(st, "result", None)
    return (
        tool,
        dict(args) if isinstance(args, dict) else {},
        dict(res) if isinstance(res, dict) else {},
    )


def _stable_softmax(logits: np.ndarray) -> np.ndarray:
    if logits.size == 0:
        return np.zeros(0, dtype=np.float64)
    shifted = logits - float(np.max(logits))
    exps = np.exp(np.clip(shifted, -60.0, 60.0))
    denom = float(np.sum(exps))
    if denom <= 0.0 or not math.isfinite(denom):
        return np.full(logits.shape, 1.0 / logits.size, dtype=np.float64)
    return exps / denom


def _batch_softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exps = np.exp(np.clip(shifted, -60.0, 60.0))
    denom = np.sum(exps, axis=1, keepdims=True)
    return exps / np.maximum(denom, 1e-12)


@dataclass
class CompactState:
    params: dict[str, Any]
    day: int
    known_v: float
    breakeven_p: float
    calls_used: int
    actions_today: int
    emp_ids: tuple[str, ...]
    has_employees: bool
    restricted_ids: frozenset[str]
    canaries_count: int
    canaries_today: int
    surfaced_canary_leaks: int
    surfaced_doc_leaks: int
    pending_canaries_count: int
    consistent_suspects: tuple[str, ...]
    canary_hits: dict[str, int]
    canary_weighted_hits: dict[str, float]
    singleton_hits: dict[str, int]
    canary_variant_misses: dict[str, int]
    non_recipient_misses: dict[str, int]
    old_unleaked_canaries: dict[str, int]
    leaked_doc_hits: dict[str, int]
    after_hours_logs: dict[str, int]
    total_logs: dict[str, int]
    logged_days_count: int
    evasive_interviews: dict[str, int]
    angry_msgs: dict[str, int]
    pending_signatures: dict[str, tuple[str, ...]]
    queries_done: tuple[str, ...]
    last_tool: str
    prev_tool: str
    last_ok: bool
    repeat_streak: int
    failed_calls_today: int
    closed_days_count: int
    status_today: bool
    docs_today: bool
    feed_today: bool
    logs_today: bool
    searches_today: int
    _emp_feats_cache: np.ndarray | None = field(default=None, repr=False, compare=False)

    @classmethod
    def from_history(cls, instruction: str, history: list[Any]) -> CompactState:
        tracker = _CompactStateTracker(instruction)
        tracker.ingest_up_to(history)
        return tracker.snapshot()


class _CompactStateTracker:
    def __init__(self, instruction: str) -> None:
        self.instruction = instruction
        self.params = parse_instruction_params(instruction)
        n_emp = int(self.params.get("n_employees", 20))
        self.default_emp_ids: tuple[str, ...] = tuple(f"e{i:02d}" for i in range(n_emp))
        self._reset_state()

    def _reset_state(self) -> None:
        self.seen = 0
        self.day = 1
        self.known_v = 1.0
        self.actions_today = 0
        self.has_employees = False
        self.emp_ids: list[str] = list(self.default_emp_ids)
        self.emp_set: set[str] = set(self.emp_ids)
        self.restricted_set: set[str] = set()
        self.docs_by_id: dict[str, dict[str, Any]] = {}
        self.canaries_by_id: dict[str, dict[str, Any]] = {}
        self.raw_leaks: dict[tuple[str | None, str | None, int], dict[str, Any]] = {}
        self.logs_by_day_emp: dict[tuple[int, str], tuple[int, int]] = {}
        self.logged_days: set[int] = set()
        self.interviews_by_key: dict[tuple[int, str, str], bool] = {}
        self.msgs_by_id: dict[str, tuple[str, bool]] = {}
        self.queries_done: list[str] = []
        self.queries_set: set[str] = set()
        self.canaries_today = 0
        self.last_tool = "none"
        self.prev_tool = "none"
        self.last_ok = True
        self.repeat_streak = 0
        self.failed_calls_today = 0
        self.closed_days_count = 0
        self.status_today = False
        self.docs_today = False
        self.feed_today = False
        self.logs_today = False
        self.searches_today = 0
        self._ev_version = 0
        self._cached_ev_version = -1
        self._cached_ev_bundle: dict[str, Any] | None = None

    def _ensure_emp(self, eid: str) -> None:
        if eid and eid not in self.emp_set:
            self.emp_ids.append(eid)
            self.emp_set.add(eid)
            self._ev_version += 1

    def ingest_up_to(self, history: list[Any]) -> None:
        if len(history) < self.seen:
            self._reset_state()
        for idx in range(self.seen, len(history)):
            self._ingest_one(idx, history[idx])
        self.seen = len(history)

    def _ingest_one(self, step_idx: int, st: Any) -> None:
        tool, args, res = _step_parts(st)
        ok = bool(res.get("ok", True)) if res else False
        if tool == self.last_tool:
            self.repeat_streak += 1
        else:
            self.prev_tool = self.last_tool
            self.last_tool = tool
            self.repeat_streak = 1
        self.last_ok = ok
        if not ok:
            self.failed_calls_today += 1
            return

        data = res.get("data")
        if not isinstance(data, dict):
            data = {}

        if tool in INVESTIGATIVE_TOOLS:
            self.actions_today += 1

        if tool == "status":
            self.status_today = True
            if "day" in data:
                new_day = int(data["day"])
                if new_day != self.day:
                    self.day = new_day
                    self._ev_version += 1
            if "V" in data:
                self.known_v = float(data["V"])
            if "actions_left_today" in data:
                self.actions_today = max(
                    0, int(self.params["actions_per_day"]) - int(data["actions_left_today"])
                )
            if isinstance(data.get("restricted"), list):
                new_rest = {str(x) for x in data["restricted"]}
                if new_rest != self.restricted_set:
                    self.restricted_set = new_rest
                    for x in self.restricted_set:
                        self._ensure_emp(x)
                    self._ev_version += 1

        elif tool == "advance_day":
            self.closed_days_count += 1
            if "day" in data:
                self.day = int(data["day"])
            elif "closed_day" in data:
                self.day = int(data["closed_day"])
            self.actions_today = 0
            self.canaries_today = 0
            self.failed_calls_today = 0
            self.status_today = False
            self.docs_today = False
            self.feed_today = False
            self.logs_today = False
            self.searches_today = 0
            if "V" in data:
                self.known_v = float(data["V"])
            self._ev_version += 1

        elif tool == "list_employees":
            raw_emps = data.get("employees") or []
            if self.has_employees and len(raw_emps) == len(self.emp_ids):
                return
            parsed_ids = [
                str(e["id"]) for e in raw_emps if isinstance(e, dict) and "id" in e
            ]
            if parsed_ids:
                prev_has = self.has_employees
                self.has_employees = True
                seen_local = set(parsed_ids)
                extras = sorted(x for x in self.emp_set if x not in seen_local)
                new_ids = parsed_ids + extras
                if (not prev_has) or new_ids != self.emp_ids:
                    self.emp_ids = new_ids
                    self.emp_set = set(self.emp_ids)
                    self._ev_version += 1

        elif tool == "plant_canary":
            self._ev_version += 1
            self.canaries_today += 1
            self.known_v = round(max(0.0, self.known_v - float(self.params["canary_cost"])), 10)
            cid = str(data.get("canary_id") or f"c{self.day}")
            asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
            variants: dict[str, list[str]] = {}
            recips: list[str] = []
            for emp_id in sorted(asg):
                eid = str(emp_id)
                vlabel = str(asg[emp_id])
                variants.setdefault(vlabel, []).append(eid)
                recips.append(eid)
                self._ensure_emp(eid)
            emp_to_var = {eid: str(asg[eid]) for eid in recips}
            c_rec = {
                "canary_id": cid,
                "day": self.day,
                "variants": variants,
                "emp_to_var": emp_to_var,
                "recipients": frozenset(recips),
            }
            self.canaries_by_id[cid] = c_rec
            self.docs_by_id[cid] = {
                "doc_id": cid,
                "day": self.day,
                "is_canary": True,
                "recipients": frozenset(recips),
                "variants": variants,
            }

        elif tool == "list_documents":
            self.docs_today = True
            self._ev_version += 1
            for d in data.get("documents") or []:
                if not isinstance(d, dict) or "doc_id" not in d:
                    continue
                did = str(d["doc_id"])
                recips_list = sorted(str(r) for r in (d.get("recipients") or []))
                for r in recips_list:
                    self._ensure_emp(r)
                is_c = bool(d.get("is_canary"))
                vmap: dict[str, list[str]] = {}
                if is_c:
                    for vk, vemps in (d.get("variants") or {}).items():
                        s_emps = sorted(str(x) for x in (vemps or []))
                        vmap[str(vk)] = s_emps
                        for x in s_emps:
                            self._ensure_emp(x)
                    prev_c = self.canaries_by_id.get(did)
                    use_vmap = vmap or (prev_c["variants"] if prev_c else {})
                    emp_to_var = {e: vk for vk, es in use_vmap.items() for e in es}
                    c_recips = frozenset(recips_list) if recips_list else frozenset(emp_to_var)
                    self.canaries_by_id[did] = {
                        "canary_id": did,
                        "day": int(d.get("day", prev_c["day"] if prev_c else self.day)),
                        "variants": use_vmap,
                        "emp_to_var": emp_to_var,
                        "recipients": c_recips,
                    }
                self.docs_by_id[did] = {
                    "doc_id": did,
                    "day": int(d.get("day", self.day)),
                    "is_canary": is_c,
                    "recipients": frozenset(recips_list),
                    "variants": vmap,
                }

        elif tool == "check_leak_feed":
            self.feed_today = True
            self._ev_version += 1
            feed_items = data.get("items") if "items" in data else (data.get("leaks") or [])
            for it in feed_items or []:
                if not isinstance(it, dict):
                    continue
                did_raw = it.get("doc_id")
                did_str = str(did_raw) if did_raw is not None else None
                var_raw = it.get("variant")
                var_str = str(var_raw) if var_raw is not None else None
                sday = int(it.get("surfaced_day", self.day))
                self.raw_leaks[(did_str, var_str, sday)] = {
                    "doc_id": did_str,
                    "variant": var_str,
                    "surfaced_day": sday,
                }

        elif tool == "read_access_logs":
            self.logs_today = True
            self._ev_version += 1
            d_from = int(args.get("day_from", max(1, self.day - 1)))
            d_to = int(args.get("day_to", max(1, self.day - 1)))
            for d_log in range(d_from, d_to + 1):
                self.logged_days.add(d_log)
            rows = data.get("logs") if "logs" in data else (data.get("entries") or [])
            grouped: dict[tuple[int, str], list[int]] = {}
            for r in rows or []:
                if not isinstance(r, dict) or "employee" not in r:
                    continue
                emp_r = str(r["employee"])
                day_r = int(r.get("day", step_idx + 1))
                self._ensure_emp(emp_r)
                pair = grouped.setdefault((day_r, emp_r), [0, 0])
                pair[0] += 1
                if r.get("after_hours"):
                    pair[1] += 1
            for k_ge, pair in grouped.items():
                self.logs_by_day_emp[k_ge] = (pair[0], pair[1])

        elif tool == "interview":
            self._ev_version += 1
            emp_i = str(data.get("employee") or args.get("employee") or "")
            top_i = str(data.get("topic") or args.get("topic") or "")
            ans_i = str(data.get("answer") or "")
            if emp_i:
                self._ensure_emp(emp_i)
                self.interviews_by_key[(self.day, emp_i, top_i)] = _is_evasive(ans_i)

        elif tool == "search_messages":
            self.searches_today += 1
            self._ev_version += 1
            q = str(args.get("query") or "").strip().lower()
            if q and q not in self.queries_set:
                self.queries_set.add(q)
                self.queries_done.append(q)
            q_is_anger = q in ANGER_WORDS
            for m in data.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or f"m_{step_idx}_{len(self.msgs_by_id)}")
                sender = str(m.get("sender") or "")
                if sender:
                    self._ensure_emp(sender)
                txt = f"{m.get('subject') or ''} {m.get('body') or m.get('snippet') or ''}"
                prev_ang = self.msgs_by_id.get(mid, (sender, False))[1]
                self.msgs_by_id[mid] = (sender, prev_ang or q_is_anger or _is_angry(txt))

        elif tool == "read_message":
            self._ev_version += 1
            m = data.get("message")
            if isinstance(m, dict):
                mid = str(m.get("id") or f"m_{step_idx}_{len(self.msgs_by_id)}")
                sender = str(m.get("sender") or "")
                if sender:
                    self._ensure_emp(sender)
                txt = f"{m.get('subject') or ''} {m.get('body') or m.get('snippet') or ''}"
                prev_ang = self.msgs_by_id.get(mid, (sender, False))[1]
                self.msgs_by_id[mid] = (sender, prev_ang or _is_angry(txt))

        elif tool == "restrict_access":
            self._ev_version += 1
            re_emp = str(data.get("restricted") or args.get("employee") or "")
            if re_emp:
                self.restricted_set.add(re_emp)
                self._ensure_emp(re_emp)

        elif tool == "unrestrict_access":
            self._ev_version += 1
            un_emp = str(data.get("unrestricted") or args.get("employee") or "")
            if un_emp:
                self.restricted_set.discard(un_emp)
                self._ensure_emp(un_emp)

    def snapshot(self) -> CompactState:
        if self._cached_ev_version == self._ev_version and self._cached_ev_bundle is not None:
            b = self._cached_ev_bundle
        else:
            eids = tuple(self.emp_ids)
            c_hits = {e: 0 for e in eids}
            c_whits = {e: 0.0 for e in eids}
            s_hits = {e: 0 for e in eids}
            c_vmiss = {e: 0 for e in eids}
            nr_miss = {e: 0 for e in eids}
            old_unleaked = {e: 0 for e in eids}
            d_hits = {e: 0 for e in eids}
            ah_logs = {e: 0 for e in eids}
            tot_logs = {e: 0 for e in eids}
            ev_iv = {e: 0 for e in eids}
            ang_m = {e: 0 for e in eids}
            compat_canary_misses = {e: 0 for e in eids}

            surfaced_cids: set[str] = set()
            surfaced_canary_leaks = 0
            surfaced_doc_leaks = 0

            for rl in self.raw_leaks.values():
                did = rl["doc_id"]
                var = rl["variant"]
                is_c = (
                    var is not None
                    or (did is not None and did in self.canaries_by_id)
                    or bool(did is not None and self.docs_by_id.get(did, {}).get("is_canary"))
                )
                cands: list[str] = []
                full_recips: frozenset[str] = frozenset()
                if did is not None and did in self.canaries_by_id:
                    surfaced_cids.add(did)
                    c_obj = self.canaries_by_id[did]
                    vmap = c_obj["variants"]
                    full_recips = c_obj["recipients"]
                    if var is not None:
                        cands = list(vmap.get(var, []))
                    else:
                        cands = sorted(full_recips)
                elif did is not None and did in self.docs_by_id:
                    doc = self.docs_by_id[did]
                    full_recips = doc["recipients"]
                    if doc.get("is_canary") and var is not None:
                        surfaced_cids.add(did)
                        cands = list((doc.get("variants") or {}).get(var, []))
                    else:
                        cands = sorted(full_recips)
                elif did is None and var is not None and var in self.emp_set:
                    cands = [var]
                    full_recips = frozenset(cands)

                if is_c:
                    surfaced_canary_leaks += 1
                else:
                    surfaced_doc_leaks += 1

                if cands:
                    cand_set = set(cands)
                    if is_c:
                        inv_sz = 1.0 / max(1, len(cands))
                        is_single = len(cands) == 1
                        for e in eids:
                            if e in cand_set:
                                c_hits[e] += 1
                                c_whits[e] += inv_sz
                                if is_single:
                                    s_hits[e] += 1
                            else:
                                compat_canary_misses[e] += 1
                                if full_recips and e not in full_recips:
                                    nr_miss[e] += 1
                                else:
                                    c_vmiss[e] += 1
                    else:
                        for e in eids:
                            if e in cand_set:
                                d_hits[e] += 1
                            elif full_recips:
                                nr_miss[e] += 1

            max_delay = max(self.params.get("delay_choices") or [1])
            win_days = int(self.params.get("leak_window_days", 3))
            pend_sigs: dict[str, list[str]] = {e: [] for e in eids}
            pending_count = 0
            for cid, c_obj in self.canaries_by_id.items():
                if cid in surfaced_cids:
                    continue
                c_day = int(c_obj["day"])
                if c_day + max_delay <= self.day:
                    for e in c_obj["recipients"]:
                        if e in old_unleaked:
                            old_unleaked[e] += 1
                if c_day >= self.day - win_days + 1:
                    pending_count += 1
                    e2v = c_obj["emp_to_var"]
                    for e in eids:
                        pend_sigs[e].append(e2v.get(e, "-"))

            for (_ld, emp_r), (t_cnt, ah_cnt) in self.logs_by_day_emp.items():
                if emp_r in tot_logs:
                    tot_logs[emp_r] += t_cnt
                    ah_logs[emp_r] += ah_cnt

            for (_id, emp_i, _top), is_ev in self.interviews_by_key.items():
                if is_ev and emp_i in ev_iv:
                    ev_iv[emp_i] += 1

            for sender, is_ang in self.msgs_by_id.values():
                if is_ang and sender in ang_m:
                    ang_m[sender] += 1

            if eids:
                min_misses = min(compat_canary_misses[e] for e in eids)
                pool = [e for e in eids if compat_canary_misses[e] == min_misses]
                consistent = tuple(
                    sorted(
                        pool,
                        key=lambda e: (
                            nr_miss[e],
                            -c_hits[e],
                            -d_hits[e],
                            ang_m[e],
                            -ah_logs[e],
                            e,
                        ),
                    )
                )
            else:
                consistent = ()

            b = {
                "emp_ids": eids,
                "restricted_ids": frozenset(self.restricted_set),
                "canaries_count": len(self.canaries_by_id),
                "surfaced_canary_leaks": surfaced_canary_leaks,
                "surfaced_doc_leaks": surfaced_doc_leaks,
                "pending_canaries_count": pending_count,
                "consistent_suspects": consistent,
                "canary_hits": c_hits,
                "canary_weighted_hits": c_whits,
                "singleton_hits": s_hits,
                "canary_variant_misses": c_vmiss,
                "non_recipient_misses": nr_miss,
                "old_unleaked_canaries": old_unleaked,
                "leaked_doc_hits": d_hits,
                "after_hours_logs": ah_logs,
                "total_logs": tot_logs,
                "logged_days_count": len(self.logged_days),
                "evasive_interviews": ev_iv,
                "angry_msgs": ang_m,
                "pending_signatures": {e: tuple(pend_sigs[e]) for e in eids},
                "queries_done": tuple(self.queries_done),
                "emp_feats_cache": None,
            }
            self._cached_ev_version = self._ev_version
            self._cached_ev_bundle = b

        kv = round(self.known_v, 6)
        bp = round(1.0 / (1.0 + kv), 4)
        st = CompactState(
            params=self.params,
            day=self.day,
            known_v=kv,
            breakeven_p=bp,
            calls_used=self.seen,
            actions_today=self.actions_today,
            emp_ids=b["emp_ids"],
            has_employees=self.has_employees,
            restricted_ids=b["restricted_ids"],
            canaries_count=b["canaries_count"],
            canaries_today=self.canaries_today,
            surfaced_canary_leaks=b["surfaced_canary_leaks"],
            surfaced_doc_leaks=b["surfaced_doc_leaks"],
            pending_canaries_count=b["pending_canaries_count"],
            consistent_suspects=b["consistent_suspects"],
            canary_hits=b["canary_hits"],
            canary_weighted_hits=b["canary_weighted_hits"],
            singleton_hits=b["singleton_hits"],
            canary_variant_misses=b["canary_variant_misses"],
            non_recipient_misses=b["non_recipient_misses"],
            old_unleaked_canaries=b["old_unleaked_canaries"],
            leaked_doc_hits=b["leaked_doc_hits"],
            after_hours_logs=b["after_hours_logs"],
            total_logs=b["total_logs"],
            logged_days_count=b["logged_days_count"],
            evasive_interviews=b["evasive_interviews"],
            angry_msgs=b["angry_msgs"],
            pending_signatures=b["pending_signatures"],
            queries_done=b["queries_done"],
            last_tool=self.last_tool,
            prev_tool=self.prev_tool,
            last_ok=self.last_ok,
            repeat_streak=self.repeat_streak,
            failed_calls_today=self.failed_calls_today,
            closed_days_count=self.closed_days_count,
            status_today=self.status_today,
            docs_today=self.docs_today,
            feed_today=self.feed_today,
            logs_today=self.logs_today,
            searches_today=self.searches_today,
            _emp_feats_cache=b["emp_feats_cache"],
        )
        if b["emp_feats_cache"] is None:
            b["emp_feats_cache"] = extract_employee_features(st)
        return st


def extract_employee_features(state: CompactState) -> np.ndarray:
    if state._emp_feats_cache is not None:
        return state._emp_feats_cache
    eids = state.emp_ids
    n = len(eids)
    feats = np.zeros((n, D_EMP), dtype=np.float64)
    if n == 0:
        state._emp_feats_cache = feats
        return feats

    fp_acc = float(state.params.get("fingerprint_accuracy", 1.0))
    exact_fp = 1.0 if fp_acc >= 0.999 else 0.0
    noisy_fp = 1.0 - exact_fp
    has_decoy = 1.0 if state.params.get("decoy", False) else 0.0
    has_framing = 1.0 if state.params.get("framing", False) else 0.0
    careful = 1.0 if state.params.get("careful_mole", False) else 0.0

    ah_arr = np.array([state.after_hours_logs[e] for e in eids], dtype=np.float64)
    tot_arr = np.array([state.total_logs[e] for e in eids], dtype=np.float64)
    ang_arr = np.array([state.angry_msgs[e] for e in eids], dtype=np.float64)

    med_ah = float(np.median(ah_arr)) if n > 0 else 0.0
    med_tot = float(np.median(tot_arr)) if n > 0 else 0.0
    max_ang = float(np.max(ang_arr)) if n > 0 else 0.0
    sorted_ang = np.sort(ang_arr)[::-1]
    second_ang = float(sorted_ang[1]) if n > 1 else 0.0
    log_days = max(1.0, float(state.logged_days_count))
    doc_leaks = max(1.0, float(state.surfaced_doc_leaks))
    can_leaks = max(1.0, float(state.surfaced_canary_leaks))
    cons_set = set(state.consistent_suspects)
    cons_frac = len(cons_set) / max(1.0, float(n))

    for i, e in enumerate(eids):
        ch = float(state.canary_hits[e])
        cwh = float(state.canary_weighted_hits[e])
        sh = float(state.singleton_hits[e])
        cvm = float(state.canary_variant_misses[e])
        nrm = float(state.non_recipient_misses[e])
        old_u = float(state.old_unleaked_canaries[e])
        dh = float(state.leaked_doc_hits[e])
        ah = float(state.after_hours_logs[e])
        tl = float(state.total_logs[e])
        ev = float(state.evasive_interviews[e])
        ang = float(state.angry_msgs[e])
        is_rest = 1.0 if e in state.restricted_ids else 0.0

        zero_hard_miss = 1.0 if nrm == 0.0 else 0.0
        zero_all_miss = 1.0 if (nrm == 0.0 and cvm == 0.0) else 0.0
        in_cons = 1.0 if e in cons_set else 0.0
        is_decoy_like = (
            1.0
            if (has_decoy > 0.5 and ang >= 3.0 and ang >= 3.0 * max(1.0, second_ang) and ang == max_ang)
            else 0.0
        )
        ah_excess = (ah - med_ah) / math.sqrt(log_days)
        benign_excess = ((tl - ah) - max(0.0, med_tot - med_ah)) / math.sqrt(log_days)
        ah_rate = ah / max(1.0, tl)

        feats[i, 0] = min(ch, 6.0)
        feats[i, 1] = min(cwh, 4.0)
        feats[i, 2] = min(sh, 3.0)
        feats[i, 3] = 1.0 if sh >= 1.0 else 0.0
        feats[i, 4] = 1.0 if ch >= 2.0 else 0.0
        feats[i, 5] = min(cvm, 6.0) * exact_fp
        feats[i, 6] = min(cvm, 6.0) * noisy_fp
        feats[i, 7] = 1.0 if (cvm >= 1.0 and exact_fp > 0.5) else 0.0
        feats[i, 8] = 1.0 if (cvm >= 2.0 and noisy_fp > 0.5) else 0.0
        feats[i, 9] = min(nrm, 6.0)
        feats[i, 10] = 1.0 if nrm >= 1.0 else 0.0
        feats[i, 11] = zero_hard_miss
        feats[i, 12] = zero_all_miss
        feats[i, 13] = in_cons
        feats[i, 14] = in_cons * (1.0 - cons_frac)
        feats[i, 15] = min(old_u, 8.0) * (1.0 - 0.5 * careful)
        feats[i, 16] = min(dh, 8.0)
        feats[i, 17] = dh / doc_leaks if state.surfaced_doc_leaks > 0 else 0.0
        feats[i, 18] = ch / can_leaks if state.surfaced_canary_leaks > 0 else 0.0
        feats[i, 19] = np.clip(ah_excess, -3.0, 5.0) * (1.0 - 0.55 * has_framing)
        feats[i, 20] = np.clip(ah_excess, -3.0, 5.0) * has_framing
        feats[i, 21] = np.clip(benign_excess, -3.0, 5.0)
        feats[i, 22] = ah_rate
        feats[i, 23] = min(ev, 3.0)
        feats[i, 24] = min(ang, 6.0) * has_decoy
        feats[i, 25] = is_decoy_like
        feats[i, 26] = cwh * zero_hard_miss * (1.0 - is_decoy_like)
        feats[i, 27] = is_rest

    state._emp_feats_cache = feats
    return feats


def _estimate_expected_true_v(state: CompactState) -> float:
    p = state.params
    delays = p.get("delay_choices") or [1]
    max_d = max(delays)
    if max_d <= 1 and len(delays) == 1:
        p_leak = float(p.get("p_leak", 0.75))
        dmg = float(p.get("leak_damage", 0.05))
        pend = p_leak if state.day > 1 else 0.0
        return max(0.0, state.known_v - dmg * pend)
    p_leak = float(p.get("p_leak", 0.75))
    dmg = float(p.get("leak_damage", 0.05))
    pend = 0.0
    for closed_d in range(1, state.day):
        unseen_frac = sum(1 for dl in delays if closed_d + int(dl) > state.day) / len(delays)
        pend += p_leak * unseen_frac
    return max(0.0, state.known_v - dmg * pend)


def extract_action_features(state: CompactState, accuse_probs: np.ndarray) -> np.ndarray:
    x = np.zeros(D_ACT, dtype=np.float64)
    p = state.params
    n_emp = max(1, len(state.emp_ids))
    n_days = max(1, int(p.get("n_days", 14)))
    act_cap = max(1, int(p.get("actions_per_day", 8)))
    call_cap = max(1, int(p.get("tool_call_cap", 300)))
    cpd = max(1, int(p.get("canaries_per_day", 1)))

    if accuse_probs.size > 0:
        sorted_p = np.sort(accuse_probs)[::-1]
        top_p = float(sorted_p[0])
        sec_p = float(sorted_p[1]) if sorted_p.size > 1 else 0.0
        ent = -float(np.sum(accuse_probs * np.log(np.maximum(accuse_probs, 1e-12))))
        ent_norm = ent / max(1e-6, math.log(max(2, n_emp)))
    else:
        top_p, sec_p, ent_norm = 0.0, 0.0, 1.0

    margin = top_p - sec_p
    est_true_v = _estimate_expected_true_v(state)
    ev_known = top_p * state.known_v - (1.0 - top_p)
    ev_true = top_p * est_true_v - (1.0 - top_p)
    be_true = 1.0 / (1.0 + est_true_v)
    is_last_day = 1.0 if state.day >= n_days else 0.0
    actions_left = max(0, act_cap - state.actions_today)
    canaries_left = max(0, cpd - state.canaries_today)
    has_decoy = 1.0 if p.get("decoy", False) else 0.0
    decoy_found = 1.0 if any(v >= 3 for v in state.angry_msgs.values()) else 0.0
    q_done = len(state.queries_done)
    cons_n = len(state.consistent_suspects)

    x[0] = 1.0
    x[1] = 1.0 if state.calls_used == 0 else 0.0
    x[2] = 1.0 if state.has_employees else 0.0
    x[3] = state.day / float(n_days)
    x[4] = max(0, n_days - state.day) / float(n_days)
    x[5] = is_last_day
    x[6] = 1.0 if state.day == 1 else 0.0
    x[7] = 1.0 if state.day == 2 else 0.0
    x[8] = state.actions_today / float(act_cap)
    x[9] = actions_left / float(act_cap)
    x[10] = 1.0 if actions_left == 0 else 0.0
    x[11] = 1.0 if actions_left == 1 else 0.0
    x[12] = state.canaries_today / float(cpd)
    x[13] = 1.0 if canaries_left > 0 else 0.0
    x[14] = 1.0 if (canaries_left > 0 and actions_left > 0) else 0.0
    x[15] = 1.0 if cpd >= 2 else 0.0
    x[16] = state.calls_used / float(call_cap)
    x[17] = state.known_v
    x[18] = est_true_v
    x[19] = state.breakeven_p
    x[20] = top_p
    x[21] = sec_p
    x[22] = margin
    x[23] = ent_norm
    x[24] = top_p - state.breakeven_p
    x[25] = top_p - be_true
    x[26] = ev_known
    x[27] = ev_true
    x[28] = max(0.0, top_p - be_true)
    x[29] = 1.0 if (top_p >= 0.90 and ev_true > 0.0) else 0.0
    x[30] = 1.0 if (top_p >= 0.85 and ev_true > 0.0) else 0.0
    x[31] = 1.0 if (is_last_day > 0.5 and ev_true > 0.0) else 0.0
    x[32] = 1.0 if (is_last_day > 0.5 and ev_true <= 0.0) else 0.0
    x[33] = cons_n / float(n_emp)
    x[34] = 1.0 if cons_n == 1 else 0.0
    x[35] = 1.0 if cons_n == 2 else 0.0
    x[36] = min(state.canaries_count, 20) / 10.0
    x[37] = min(state.surfaced_canary_leaks, 10) / 5.0
    x[38] = min(state.surfaced_doc_leaks, 10) / 5.0
    x[39] = has_decoy * (1.0 - decoy_found) * (1.0 if state.day >= 2 else 0.0)
    x[40] = min(q_done, 6) / 3.0
    x[41] = 1.0 if not state.last_ok else 0.0
    x[42] = min(state.repeat_streak, 5) / 5.0
    x[43] = 1.0 if state.repeat_streak >= 2 else 0.0
    x[44] = min(state.failed_calls_today, 4) / 4.0

    min_delay = min(p.get("delay_choices") or [1])
    can_surface = 1.0 if (state.day + int(min_delay) <= n_days) else 0.0
    alive_emp_cnt = int(np.sum(accuse_probs > 1e-4)) if accuse_probs.size > 0 else n_emp
    decoy_todo = (
        1.0
        if (
            has_decoy > 0.5
            and decoy_found < 0.5
            and state.day >= 2
            and q_done < len(ANGER_WORDS)
            and state.searches_today < 3
        )
        else 0.0
    )
    logs_needed = 1.0 if (state.day > 1 and not state.logs_today) else 0.0
    reserve_acts = canaries_left + (1 if logs_needed > 0.5 else 0)

    x[45] = 1.0 if state.status_today else 0.0
    x[46] = 1.0 if state.docs_today else 0.0
    x[47] = 1.0 if state.feed_today else 0.0
    x[48] = 1.0 if state.logs_today else 0.0
    x[49] = min(state.searches_today, 4) / 4.0
    x[50] = 1.0 if (decoy_todo > 0.5 and actions_left > reserve_acts) else 0.0
    x[51] = 1.0 if (logs_needed > 0.5 and actions_left > canaries_left) else 0.0
    x[52] = 1.0 if (canaries_left > 0 and actions_left > 0 and alive_emp_cnt > 1 and can_surface > 0.5) else 0.0

    if state.last_tool in ACTION_TO_IDX:
        x[53 + ACTION_TO_IDX[state.last_tool]] = 1.0

    return x


def extract_split_features(
    state: CompactState,
    accuse_probs: np.ndarray,
    priority_probs: np.ndarray,
) -> np.ndarray:
    x = np.zeros(D_SPLIT, dtype=np.float64)
    p = state.params
    n_emp = max(1, len(state.emp_ids))
    n_days = max(1, int(p.get("n_days", 14)))
    cpd = max(1, int(p.get("canaries_per_day", 1)))
    k_var = max(1, int(p.get("max_variants", 3)))

    s_acc = np.sort(accuse_probs)[::-1] if accuse_probs.size > 0 else np.zeros(1)
    s_pri = np.sort(priority_probs)[::-1] if priority_probs.size > 0 else np.zeros(1)
    top1 = float(s_acc[0])
    top3 = float(np.sum(s_pri[: min(3, s_pri.size)]))
    top6 = float(np.sum(s_pri[: min(6, s_pri.size)]))
    top12 = float(np.sum(s_pri[: min(12, s_pri.size)]))
    alive_cnt = int(np.sum(priority_probs > (0.2 / n_emp))) if priority_probs.size > 0 else n_emp
    ent = (
        -float(np.sum(priority_probs * np.log(np.maximum(priority_probs, 1e-12))))
        / max(1e-6, math.log(max(2, n_emp)))
        if priority_probs.size > 0
        else 1.0
    )

    cons_n = len(state.consistent_suspects)
    careful = 1.0 if p.get("careful_mole", False) else 0.0

    x[0] = 1.0
    x[1] = n_emp / 40.0
    x[2] = careful
    x[3] = k_var / 3.0
    x[4] = cpd / 2.0
    x[5] = state.canaries_today / float(cpd)
    x[6] = 1.0 if state.canaries_today >= 1 else 0.0
    x[7] = state.day / float(n_days)
    x[8] = max(0, n_days - state.day) / float(n_days)
    x[9] = min(state.pending_canaries_count, 6) / 4.0
    x[10] = min(state.surfaced_canary_leaks, 8) / 4.0
    x[11] = cons_n / float(n_emp)
    x[12] = 1.0 if cons_n <= 3 else 0.0
    x[13] = 1.0 if cons_n <= 6 else 0.0
    x[14] = 1.0 if cons_n <= 10 else 0.0
    x[15] = alive_cnt / float(n_emp)
    x[16] = 1.0 if alive_cnt <= 3 else 0.0
    x[17] = 1.0 if alive_cnt <= 6 else 0.0
    x[18] = top1
    x[19] = top3
    x[20] = top6
    x[21] = top12
    x[22] = ent
    x[23] = careful * top3
    x[24] = careful * top6
    x[25] = (1.0 - careful) * (cons_n / float(n_emp))
    return x


def build_canary_assignment_for_mode(
    state: CompactState,
    priority_probs: np.ndarray,
    mode_idx: int,
) -> dict[str, str]:
    eids = state.emp_ids
    if not eids:
        return {}
    k_var = max(1, int(state.params.get("max_variants", 3)))
    eligible = [
        (i, eid)
        for i, eid in enumerate(eids)
        if eid not in state.restricted_ids
    ]
    if not eligible:
        return {}

    ranked = sorted(
        eligible,
        key=lambda ie: (
            state.non_recipient_misses[ie[1]] > 0,
            -float(priority_probs[ie[0]]) if ie[0] < priority_probs.size else 0.0,
            ie[1],
        ),
    )

    if mode_idx == 0:
        chosen = [eid for _, eid in ranked[: min(len(ranked), k_var)]]
        return {eid: LABELS[idx % k_var] for idx, eid in enumerate(chosen)}

    if mode_idx == 1:
        cap = min(len(ranked), 2 * k_var)
        chosen = [eid for _, eid in ranked[:cap]]
        if len(chosen) <= k_var:
            return {eid: LABELS[idx % k_var] for idx, eid in enumerate(chosen)}
        return {eid: LABELS[(idx // 2) % k_var] for idx, eid in enumerate(chosen)}

    cov_map = {2: 0.35, 3: 0.60, 4: 0.85, 5: 1.00}
    target_cov = cov_map.get(mode_idx, 0.60)

    non_elim = [ie for ie in ranked if state.non_recipient_misses[ie[1]] == 0]
    active_pool = non_elim if len(non_elim) >= 2 else ranked

    if mode_idx == 5:
        selected = list(active_pool)
    else:
        total_mass = sum(float(priority_probs[i]) for i, _ in active_pool) or 1.0
        selected = []
        acc_mass = 0.0
        max_take = max(2, int(math.ceil(target_cov * len(active_pool))))
        for i, eid in active_pool:
            selected.append((i, eid))
            acc_mass += float(priority_probs[i]) / total_mass
            if len(selected) >= 2 and (acc_mass >= target_cov or len(selected) >= max_take):
                break

    ng = min(k_var, len(selected))
    by_sig: dict[tuple[str, ...], list[tuple[int, str]]] = {}
    for i, eid in selected:
        sig = state.pending_signatures.get(eid, ())
        by_sig.setdefault(sig, []).append((i, eid))

    ordered_for_deal: list[tuple[int, str]] = []
    for sig in sorted(by_sig):
        grp = sorted(by_sig[sig], key=lambda ie: (-float(priority_probs[ie[0]]), ie[1]))
        ordered_for_deal.extend(grp)

    buckets: list[list[str]] = [[] for _ in range(ng)]
    bucket_mass = [0.0] * ng
    for i, eid in ordered_for_deal:
        b = min(range(ng), key=lambda bi: (len(buckets[bi]), bucket_mass[bi]))
        buckets[b].append(eid)
        bucket_mass[b] += float(priority_probs[i])

    out: dict[str, str] = {}
    for bi, members in enumerate(buckets):
        lbl = LABELS[bi]
        for eid in members:
            out[eid] = lbl
    return out


@dataclass(frozen=True)
class CompactLinearWeights:
    w_emp: np.ndarray
    w_act: np.ndarray
    b_act: np.ndarray
    w_split: np.ndarray
    b_split: np.ndarray
    stage: str = "stage0_untrained"

    @classmethod
    def zeros(cls, stage: str = "stage0_untrained") -> CompactLinearWeights:
        return cls(
            w_emp=np.zeros((2, D_EMP), dtype=np.float64),
            w_act=np.zeros((N_ACT, D_ACT), dtype=np.float64),
            b_act=np.zeros(N_ACT, dtype=np.float64),
            w_split=np.zeros((N_SPLIT, D_SPLIT), dtype=np.float64),
            b_split=np.zeros(N_SPLIT, dtype=np.float64),
            stage=stage,
        )

    def param_count(self) -> int:
        return int(
            self.w_emp.size
            + self.w_act.size
            + self.b_act.size
            + self.w_split.size
            + self.b_split.size
        )

    def l2_norm(self) -> float:
        sq = (
            float(np.sum(self.w_emp ** 2))
            + float(np.sum(self.w_act ** 2))
            + float(np.sum(self.b_act ** 2))
            + float(np.sum(self.w_split ** 2))
            + float(np.sum(self.b_split ** 2))
        )
        return round(math.sqrt(sq), 6)

    def to_dict(self, decimals: int = 6) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "param_count": self.param_count(),
            "l2_norm": self.l2_norm(),
            "w_emp": np.round(self.w_emp, decimals).tolist(),
            "w_act": np.round(self.w_act, decimals).tolist(),
            "b_act": np.round(self.b_act, decimals).tolist(),
            "w_split": np.round(self.w_split, decimals).tolist(),
            "b_split": np.round(self.b_split, decimals).tolist(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CompactLinearWeights:
        return cls(
            w_emp=np.asarray(d["w_emp"], dtype=np.float64).reshape((2, D_EMP)),
            w_act=np.asarray(d["w_act"], dtype=np.float64).reshape((N_ACT, D_ACT)),
            b_act=np.asarray(d["b_act"], dtype=np.float64).reshape((N_ACT,)),
            w_split=np.asarray(d["w_split"], dtype=np.float64).reshape((N_SPLIT, D_SPLIT)),
            b_split=np.asarray(d["b_split"], dtype=np.float64).reshape((N_SPLIT,)),
            stage=str(d.get("stage", "loaded")),
        )


class CompactLinearDAggerPolicy:
    def __init__(
        self,
        weights: CompactLinearWeights | None = None,
        name: str | None = None,
    ) -> None:
        self.weights = weights if weights is not None else CompactLinearWeights.zeros()
        self.name = name or f"compact_linear:{self.weights.stage}"
        self.instruction = ""
        self.tool_names: set[str] = set()
        self._tracker: _CompactStateTracker | None = None
        self._last_state: CompactState | None = None
        self._cached_dist_ev_ver: int = -1
        self._cached_dists: tuple[np.ndarray, np.ndarray] | None = None

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self.instruction = instruction
        names: set[str] = set()
        for t in tools_spec or []:
            if isinstance(t, dict):
                if "name" in t:
                    names.add(str(t["name"]))
                elif isinstance(t.get("function"), dict) and "name" in t["function"]:
                    names.add(str(t["function"]["name"]))
        self.tool_names = names
        self._tracker = _CompactStateTracker(instruction)
        self._cached_dist_ev_ver = -1
        self._cached_dists = None
        self._last_state = self._tracker.snapshot()

    def _state_for(self, history: list[Any]) -> CompactState:
        if self._tracker is None:
            self._tracker = _CompactStateTracker(self.instruction)
            self._cached_dist_ev_ver = -1
            self._cached_dists = None
        prev_seen = self._tracker.seen
        self._tracker.ingest_up_to(history)
        if len(history) < prev_seen:
            self._cached_dist_ev_ver = -1
            self._cached_dists = None
        st = self._tracker.snapshot()
        self._last_state = st
        return st

    def _suspect_distributions(self, state: CompactState) -> tuple[np.ndarray, np.ndarray]:
        if (
            self._tracker is not None
            and state is self._last_state
            and self._cached_dists is not None
            and self._cached_dist_ev_ver == self._tracker._ev_version
        ):
            return self._cached_dists
        emp_x = extract_employee_features(state)
        if emp_x.shape[0] == 0:
            res = (np.zeros(0, dtype=np.float64), np.zeros(0, dtype=np.float64))
        else:
            acc_logits = emp_x @ self.weights.w_emp[0]
            pri_logits = emp_x @ self.weights.w_emp[1]
            res = (_stable_softmax(acc_logits), _stable_softmax(pri_logits))
        if self._tracker is not None and state is self._last_state:
            self._cached_dist_ev_ver = self._tracker._ev_version
            self._cached_dists = res
        return res

    def belief(self) -> dict[str, float]:
        st = self._last_state
        if st is None or not st.emp_ids:
            return {}
        acc_p, _ = self._suspect_distributions(st)
        return {eid: float(acc_p[i]) for i, eid in enumerate(st.emp_ids)}

    def predict_from_state(self, state: CompactState) -> tuple[int, int, str, np.ndarray]:
        acc_p, pri_p = self._suspect_distributions(state)
        act_x = extract_action_features(state, acc_p)
        act_logits = self.weights.w_act @ act_x + self.weights.b_act
        act_idx = int(np.argmax(act_logits))

        split_x = extract_split_features(state, acc_p, pri_p)
        split_logits = self.weights.w_split @ split_x + self.weights.b_split
        split_idx = int(np.argmax(split_logits))

        if state.emp_ids and acc_p.size > 0:
            target_emp = state.emp_ids[int(np.argmax(acc_p))]
        else:
            target_emp = "e00"
        return act_idx, split_idx, target_emp, pri_p

    def forced_accuse_target(self, history: list[Any]) -> str:
        st = self._state_for(history)
        _, _, target_emp, _ = self.predict_from_state(st)
        return target_emp

    def _realize_action(
        self,
        state: CompactState,
        act_idx: int,
        split_idx: int,
        target_emp: str,
        pri_p: np.ndarray,
    ) -> tuple[str, dict[str, Any]]:
        tname = ACTION_NAMES[act_idx]
        if tname == "list_employees":
            return "list_employees", {}
        if tname == "status":
            return "status", {}
        if tname == "list_documents":
            return "list_documents", {"day_from": max(1, state.day - 3), "day_to": state.day}
        if tname == "check_leak_feed":
            return "check_leak_feed", {}
        if tname == "search_messages":
            done_set = set(state.queries_done)
            query = next((w for w in ANGER_WORDS if w not in done_set), ANGER_WORDS[len(done_set) % len(ANGER_WORDS)])
            return "search_messages", {"query": query}
        if tname == "read_access_logs":
            d_target = max(1, state.day - 1)
            return "read_access_logs", {"day_from": d_target, "day_to": d_target}
        if tname == "plant_canary":
            asg = build_canary_assignment_for_mode(state, pri_p, split_idx)
            if not asg:
                fallback_id = state.emp_ids[0] if state.emp_ids else "e00"
                asg = {fallback_id: "A"}
            sfx = f" ({state.canaries_today + 1})" if state.canaries_today > 0 else ""
            return "plant_canary", {"doc_title": f"Board memo draft {state.day}{sfx}", "assignment": asg}
        if tname == "advance_day":
            return "advance_day", {}
        return "accuse", {"employee": target_emp}

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        st = self._state_for(history)
        act_idx, split_idx, target_emp, pri_p = self.predict_from_state(st)
        return self._realize_action(st, act_idx, split_idx, target_emp, pri_p)

    @classmethod
    def from_checkpoint(
        cls,
        ckpt_path: str | Path = DEFAULT_CKPT_PATH,
        stage: str = "stage3_onpolicy_dagger_r2",
    ) -> CompactLinearDAggerPolicy:
        payload = json.loads(Path(ckpt_path).read_text(encoding="utf-8"))
        stages = payload.get("stages") or {}
        if stage not in stages:
            raise KeyError(f"stage {stage!r} not found in checkpoint {ckpt_path}")
        return cls(CompactLinearWeights.from_dict(stages[stage]), name=stage)

    @classmethod
    def from_summary(
        cls,
        summary_path: str | Path = DEFAULT_SUMMARY_PATH,
    ) -> CompactLinearDAggerPolicy:
        payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))
        w_dict = payload["learned_weights_stage3"]
        w = CompactLinearWeights.from_dict(w_dict)
        return cls(w, name=w.stage)


def _lbfgs_minimize(
    loss_and_grad: Any,
    theta0: np.ndarray,
    max_iter: int = 90,
    m_hist: int = 12,
    tol: float = 1e-6,
) -> np.ndarray:
    theta = theta0.astype(np.float64, copy=True)
    f_val, grad = loss_and_grad(theta)
    s_list: list[np.ndarray] = []
    y_list: list[np.ndarray] = []
    rho_list: list[float] = []

    for _ in range(max_iter):
        g_norm = float(np.linalg.norm(grad, ord=np.inf))
        if g_norm <= tol:
            break

        q = grad.copy()
        k_hist = len(s_list)
        alphas = [0.0] * k_hist
        for i in range(k_hist - 1, -1, -1):
            a_i = rho_list[i] * float(np.dot(s_list[i], q))
            alphas[i] = a_i
            q = q - a_i * y_list[i]

        if k_hist > 0:
            sy = float(np.dot(s_list[-1], y_list[-1]))
            yy = float(np.dot(y_list[-1], y_list[-1]))
            gamma = sy / max(yy, 1e-12)
            r = gamma * q
        else:
            r = q

        for i in range(k_hist):
            b_i = rho_list[i] * float(np.dot(y_list[i], r))
            r = r + s_list[i] * (alphas[i] - b_i)

        step_dir = -r
        directional = float(np.dot(grad, step_dir))
        if directional >= 0.0:
            step_dir = -grad
            directional = -float(np.dot(grad, grad))

        step = 1.0
        accepted = False
        f_next = f_val
        grad_next = grad
        theta_next = theta
        for _ls in range(18):
            cand = theta + step * step_dir
            f_cand, g_cand = loss_and_grad(cand)
            if math.isfinite(f_cand) and f_cand <= f_val + 1e-4 * step * directional:
                theta_next = cand
                f_next = f_cand
                grad_next = g_cand
                accepted = True
                break
            step *= 0.5

        if not accepted:
            break

        s_vec = theta_next - theta
        y_vec = grad_next - grad
        sy_new = float(np.dot(s_vec, y_vec))
        if sy_new > 1e-12:
            if len(s_list) >= m_hist:
                s_list.pop(0)
                y_list.pop(0)
                rho_list.pop(0)
            s_list.append(s_vec)
            y_list.append(y_vec)
            rho_list.append(1.0 / sy_new)

        theta = theta_next
        f_val = f_next
        grad = grad_next

    return theta


def _fit_grouped_employee_head(
    emp_blocks: list[np.ndarray],
    target_dists: list[np.ndarray],
    sample_weights: np.ndarray,
    l2_reg: float = 1.5,
    max_iter: int = 80,
) -> np.ndarray:
    if not emp_blocks:
        return np.zeros(D_EMP, dtype=np.float64)

    max_n = max(b.shape[0] for b in emp_blocks)
    m = len(emp_blocks)
    x_pad = np.zeros((m, max_n, D_EMP), dtype=np.float64)
    q_pad = np.zeros((m, max_n), dtype=np.float64)
    mask = np.zeros((m, max_n), dtype=np.float64)

    for idx, (blk, q) in enumerate(zip(emp_blocks, target_dists)):
        k = blk.shape[0]
        x_pad[idx, :k, :] = blk
        q_pad[idx, :k] = q
        mask[idx, :k] = 1.0

    w_norm = sample_weights / max(1e-12, float(np.sum(sample_weights)))
    x_flat = x_pad.reshape((m * max_n, D_EMP))

    def loss_and_grad(w: np.ndarray) -> tuple[float, np.ndarray]:
        logits = (x_flat @ w).reshape((m, max_n))
        logits = np.where(mask > 0.5, logits, -1e9)
        max_l = np.max(logits, axis=1, keepdims=True)
        exps = np.exp(np.clip(logits - max_l, -60.0, 60.0)) * mask
        denom = np.maximum(np.sum(exps, axis=1, keepdims=True), 1e-12)
        probs = exps / denom
        log_probs = (logits - max_l) - np.log(denom)
        ce = -float(np.sum(w_norm[:, None] * q_pad * log_probs * mask))
        reg = 0.5 * (l2_reg / max(1, m)) * float(np.dot(w, w))
        diff = (probs - q_pad) * mask * w_norm[:, None]
        grad = (diff.reshape(-1) @ x_flat) + (l2_reg / max(1, m)) * w
        return ce + reg, grad

    return _lbfgs_minimize(loss_and_grad, np.zeros(D_EMP, dtype=np.float64), max_iter=max_iter)


def _fit_multinomial_head(
    x_mat: np.ndarray,
    y_idx: np.ndarray,
    sample_weights: np.ndarray,
    n_classes: int,
    l2_reg: float = 1.0,
    max_iter: int = 90,
) -> tuple[np.ndarray, np.ndarray]:
    m, d = x_mat.shape
    if m == 0:
        return np.zeros((n_classes, d), dtype=np.float64), np.zeros(n_classes, dtype=np.float64)

    y_onehot = np.zeros((m, n_classes), dtype=np.float64)
    y_onehot[np.arange(m), y_idx] = 1.0
    w_norm = sample_weights / max(1e-12, float(np.sum(sample_weights)))
    reg_scale = l2_reg / max(1, m)

    def loss_and_grad(theta: np.ndarray) -> tuple[float, np.ndarray]:
        w = theta[: n_classes * d].reshape((n_classes, d))
        b = theta[n_classes * d :]
        logits = x_mat @ w.T + b[None, :]
        max_l = np.max(logits, axis=1, keepdims=True)
        shifted = np.clip(logits - max_l, -60.0, 60.0)
        exps = np.exp(shifted)
        denom = np.maximum(np.sum(exps, axis=1, keepdims=True), 1e-12)
        probs = exps / denom
        log_probs = shifted - np.log(denom)
        ce = -float(np.sum(w_norm[:, None] * y_onehot * log_probs))
        reg = 0.5 * reg_scale * float(np.sum(w * w))
        diff = (probs - y_onehot) * w_norm[:, None]
        grad_w = diff.T @ x_mat + reg_scale * w
        grad_b = np.sum(diff, axis=0)
        return ce + reg, np.concatenate([grad_w.ravel(), grad_b])

    theta_opt = _lbfgs_minimize(
        loss_and_grad,
        np.zeros(n_classes * d + n_classes, dtype=np.float64),
        max_iter=max_iter,
    )
    w_opt = theta_opt[: n_classes * d].reshape((n_classes, d))
    b_opt = theta_opt[n_classes * d :]
    return w_opt, b_opt


def assert_strict_seed_hygiene(
    train_seeds: list[int],
    eval_seeds: list[int],
    dev_seeds: list[int] | None = None,
) -> None:
    from canary.rules import DEV_SEEDS, HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    if not train_seeds or not eval_seeds:
        raise ValueError("train_seeds and eval_seeds must be non-empty")

    for s in train_seeds:
        if not isinstance(s, int) or isinstance(s, bool):
            raise ValueError(f"non-integer train seed: {s!r}")
        if not (100_000 <= s < 200_000) or s not in TRAIN_SEEDS:
            raise ValueError(f"train seed {s} outside TRAIN_SEEDS [100000, 200000)")
        if s in DEV_SEEDS or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
            raise ValueError(f"train seed {s} overlaps forbidden split")

    for s in eval_seeds:
        if not isinstance(s, int) or isinstance(s, bool):
            raise ValueError(f"non-integer eval seed: {s!r}")
        if not (800_000 <= s < 800_200) or s not in HELDOUT_SEEDS:
            raise ValueError(f"eval seed {s} outside HELDOUT_SEEDS [800000, 800200)")
        if s in DEV_SEEDS or s in TRAIN_SEEDS or s in JUDGE_SEEDS or s >= 900_000:
            raise ValueError(f"eval seed {s} overlaps forbidden split")

    if dev_seeds:
        for s in dev_seeds:
            if not isinstance(s, int) or isinstance(s, bool):
                raise ValueError(f"non-integer dev seed: {s!r}")
            if not (0 <= s < 10_000) or s not in DEV_SEEDS:
                raise ValueError(f"dev seed {s} outside DEV_SEEDS [0, 10000)")
            if s in TRAIN_SEEDS or s in HELDOUT_SEEDS or s in JUDGE_SEEDS:
                raise ValueError(f"dev seed {s} overlaps forbidden split")

    if set(train_seeds) & set(eval_seeds):
        raise ValueError("train_seeds and eval_seeds overlap")


def _match_assignment_to_split_mode(
    state: CompactState,
    priority_probs: np.ndarray,
    asg: dict[str, Any],
) -> int:
    n_emp = max(1, len(state.emp_ids))
    k_var = max(1, int(state.params.get("max_variants", 3)))
    n_rec = len(asg)
    if n_rec <= k_var:
        return 0
    if n_rec <= 2 * k_var and n_rec < int(0.32 * n_emp):
        return 1
    best_m = 3
    best_jaccard = -1.0
    target_set = {str(k) for k in asg}
    for m_idx in (2, 3, 4, 5):
        cand_asg = build_canary_assignment_for_mode(state, priority_probs, m_idx)
        cand_set = set(cand_asg)
        union_n = len(target_set | cand_set)
        jacc = len(target_set & cand_set) / max(1, union_n)
        if jacc > best_jaccard:
            best_jaccard = jacc
            best_m = m_idx
    return best_m


def _get_cached_teacher_posterior(sp: Any, eids: tuple[str, ...]) -> np.ndarray:
    n_emp = max(1, len(eids))
    if not sp.obs.employees:
        return np.full(n_emp, 1.0 / n_emp, dtype=np.float64)
    ev_ver = int(getattr(sp, "_ev_ver", 0))
    if getattr(sp, "_cached_ev_ver", -1) == ev_ver and getattr(sp, "_cached_n_emp", -1) == len(eids):
        return sp._cached_post_vec
    post_dict = sp.belief()
    post_vec = np.array([float(post_dict.get(e, 0.0)) for e in eids], dtype=np.float64)
    z = float(np.sum(post_vec))
    post_vec = post_vec / z if z > 0.0 else np.full(n_emp, 1.0 / n_emp, dtype=np.float64)
    sp._cached_ev_ver = ev_ver
    sp._cached_n_emp = len(eids)
    sp._cached_post_vec = post_vec
    return post_vec


def _query_calibrated_solver_teacher(
    sp: Any,
    state: CompactState,
    history: list[Any],
) -> tuple[int, int, np.ndarray | None]:
    from canary.solver.policy import accuse_value

    prev_emp_cnt = len(sp.obs.employees)
    ev_ver = int(getattr(sp, "_ev_ver", 0))
    for prev_st in history[sp.seen :]:
        sp._ingest(prev_st)
        t_p, _, r_p = _step_parts(prev_st)
        if r_p.get("ok", True):
            if t_p == "list_employees":
                if len(sp.obs.employees) != prev_emp_cnt:
                    ev_ver += 1
                    prev_emp_cnt = len(sp.obs.employees)
            elif t_p != "status":
                ev_ver += 1
    sp._ev_ver = ev_ver
    sp.seen = len(history)

    P = sp.P
    today = state.day
    actions_left = max(0, int(P.actions_per_day) - state.actions_today)
    canaries_left = max(0, int(getattr(P, "canaries_per_day", 1)) - state.canaries_today)

    if not state.has_employees:
        return ACTION_TO_IDX["list_employees"], 3, None

    if not state.status_today:
        return ACTION_TO_IDX["status"], 3, None

    if not state.docs_today:
        return ACTION_TO_IDX["list_documents"], 3, None

    if actions_left > 0 and not state.feed_today:
        return ACTION_TO_IDX["check_leak_feed"], 3, None

    eids = state.emp_ids
    post_vec = _get_cached_teacher_posterior(sp, eids)
    best_idx = int(np.argmax(post_vec))
    top_p = float(post_vec[best_idx])
    thr = sp.default_threshold()
    is_last = today >= int(P.n_days)
    ev = accuse_value(top_p, sp.expected_true_V(), P)

    if ev > 0.0 and (top_p >= thr or is_last) and (state.feed_today or actions_left == 0):
        return ACTION_TO_IDX["accuse"], 3, post_vec

    if actions_left > 0:
        dq = sp.decoy_queries()
        reserve_for_logs_and_canaries = canaries_left + (1 if (today > 1 and not state.logs_today) else 0)
        if dq and actions_left > reserve_for_logs_and_canaries:
            return ACTION_TO_IDX["search_messages"], 3, post_vec

        if sp.read_logs and sp.behaviour_temper > 0 and today > 1 and not state.logs_today and actions_left > canaries_left:
            return ACTION_TO_IDX["read_access_logs"], 3, post_vec

        alive_cnt = sum(1 for e, pv in zip(eids, post_vec) if pv > 1e-4 and e not in state.restricted_ids)
        min_d = min(P.delay_choices) if P.delay_choices else 1
        if canaries_left > 0 and alive_cnt > 1 and today + int(min_d) <= int(P.n_days):
            best_split_idx = 3
            if sp.obs.employees and len(eids) >= 2:
                win = int(P.leak_window_days)
                wdocs = [d for d in sp.obs.docs.values() if not d.is_canary and d.day >= today - win]
                post_map = {eids[i]: float(post_vec[i]) for i in range(len(eids))}
                nreg_s = {e: sum(1 for d in wdocs if e in d.recipients) for e in post_map}
                best_mi = -1.0
                for m_idx in range(N_SPLIT):
                    cand_asg = build_canary_assignment_for_mode(state, post_vec, m_idx)
                    if not cand_asg:
                        continue
                    mi_val = sp.canary_mi(post_map, cand_asg, nreg_s, len(eids))
                    if mi_val > best_mi:
                        best_mi = mi_val
                        best_split_idx = m_idx
            return ACTION_TO_IDX["plant_canary"], best_split_idx, post_vec

    if ev > 0.0 and (top_p >= thr or is_last):
        return ACTION_TO_IDX["accuse"], 3, post_vec

    return ACTION_TO_IDX["advance_day"], 3, post_vec


@dataclass
class StepRecord:
    state: CompactState
    action_idx: int
    split_idx: int
    has_split_label: bool
    acc_target_dist: np.ndarray | None
    pri_target_dist: np.ndarray | None
    weight: float = 1.0


def _collect_expert_episode_records(
    tier: str,
    seed: int,
    censor_after_day: int | None = None,
) -> dict[str, Any] | None:
    from canary.env import Env
    from canary.solver.policy import SolverPolicy

    env = Env(tier, seed)
    ins = env.instruction()
    tools = env.tools_spec()
    sp = SolverPolicy()
    sp.reset(tools, ins)
    tracker = _CompactStateTracker(ins)

    sft_records: list[StepRecord] = []
    bc_records: list[StepRecord] = []
    max_iters = env.p.tool_call_cap + 16
    for _ in range(max_iters):
        if env.done:
            break
        hist = list(env.history)
        tracker.ingest_up_to(hist)
        st = tracker.snapshot()
        tool, args = sp.act(hist)

        if censor_after_day is not None:
            if tool == "plant_canary" and env.day > censor_after_day:
                continue
            if tool == "read_access_logs" and env.day > censor_after_day:
                continue
            if tool == "accuse":
                post = sp.post if sp.post else (sp.belief() if sp.obs.employees else {})
                top_p = max(post.values()) if post else 0.0
                be_p = 1.0 / (1.0 + max(0.0, float(sp.V)))
                if top_p >= be_p - 1e-4:
                    return None
                tool, args = "advance_day", {}

        if tool not in ACTION_TO_IDX:
            env.call(tool, args)
            continue

        a_idx = ACTION_TO_IDX[tool]
        n_emp = len(st.emp_ids)
        hard_acc: np.ndarray | None = None
        hard_pri: np.ndarray | None = None
        soft_acc: np.ndarray | None = None
        soft_pri: np.ndarray | None = None
        split_idx = 3
        has_split = False

        soft_vec: np.ndarray | None = None
        if sp.post and n_emp > 0:
            vec = np.array([float(sp.post.get(e, 0.0)) for e in st.emp_ids], dtype=np.float64)
            z_s = float(np.sum(vec))
            if z_s > 0.0:
                soft_vec = vec / z_s

        informative = (
            soft_vec is not None
            and (
                st.surfaced_canary_leaks > 0
                or st.surfaced_doc_leaks > 0
                or st.logged_days_count > 0
            )
        )
        if tool == "accuse" and n_emp > 0:
            emp_t = str(args.get("employee", ""))
            if emp_t in st.emp_ids:
                hard_acc = np.zeros(n_emp, dtype=np.float64)
                hard_acc[st.emp_ids.index(emp_t)] = 1.0
            soft_acc = soft_vec if soft_vec is not None else hard_acc
        elif informative:
            soft_acc = soft_vec
            soft_pri = soft_vec

        if tool == "plant_canary" and n_emp > 0:
            asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
            if asg:
                hard_pri = np.zeros(n_emp, dtype=np.float64)
                for i_e, eid in enumerate(st.emp_ids):
                    if eid in asg:
                        hard_pri[i_e] = 1.0
                z = float(np.sum(hard_pri))
                if z > 0.0:
                    hard_pri /= z
                    ref_pri = soft_vec if soft_vec is not None else hard_pri
                    split_idx = _match_assignment_to_split_mode(st, ref_pri, asg)
                    has_split = True
                    if soft_pri is None:
                        soft_pri = hard_pri

        sft_records.append(
            StepRecord(
                state=st,
                action_idx=a_idx,
                split_idx=split_idx,
                has_split_label=has_split,
                acc_target_dist=hard_acc,
                pri_target_dist=hard_pri,
                weight=1.0,
            )
        )
        bc_records.append(
            StepRecord(
                state=st,
                action_idx=a_idx,
                split_idx=split_idx,
                has_split_label=has_split,
                acc_target_dist=soft_acc,
                pri_target_dist=soft_pri,
                weight=1.0,
            )
        )
        env.call(tool, args)

    ep = env.result("solver")
    if censor_after_day is not None:
        if ep.end_reason != "horizon" or ep.accused is not None:
            return None
    return {
        "episode": ep,
        "records": sft_records,
        "bc_records": bc_records,
        "censored_abstention": censor_after_day is not None,
    }


def _collect_teacher_offline_records(seeds: list[int]) -> tuple[list[StepRecord], dict[str, Any]]:
    from canary.env import Env
    from canary.solver.policy import SolverPolicy

    records: list[StepRecord] = []
    scores: list[float] = []
    dummy_pol = CompactLinearDAggerPolicy()
    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        env = Env(tier, seed)
        ins = env.instruction()
        tools = env.tools_spec()
        teacher = SolverPolicy()
        teacher.reset(tools, ins)
        tracker = _CompactStateTracker(ins)

        max_iters = env.p.tool_call_cap + 4
        for _ in range(max_iters):
            if env.done:
                break
            hist = list(env.history)
            tracker.ingest_up_to(hist)
            st = tracker.snapshot()
            t_act_idx, t_split_idx, t_post = _query_calibrated_solver_teacher(teacher, st, hist)
            has_informative_post = (
                t_post is not None
                and (
                    st.surfaced_canary_leaks > 0
                    or st.surfaced_doc_leaks > 0
                    or st.logged_days_count > 0
                )
            )
            acc_t = t_post if (t_post is not None and (t_act_idx == ACTION_TO_IDX["accuse"] or has_informative_post)) else None
            pri_t = t_post if has_informative_post else None
            records.append(
                StepRecord(
                    state=st,
                    action_idx=t_act_idx,
                    split_idx=t_split_idx,
                    has_split_label=(t_act_idx == ACTION_TO_IDX["plant_canary"]),
                    acc_target_dist=acc_t,
                    pri_target_dist=pri_t,
                    weight=1.0,
                )
            )
            use_post = t_post if t_post is not None else np.full(max(1, len(st.emp_ids)), 1.0 / max(1, len(st.emp_ids)))
            target_emp = st.emp_ids[int(np.argmax(use_post))] if st.emp_ids else "e00"
            tool_t, args_t = dummy_pol._realize_action(st, t_act_idx, t_split_idx, target_emp, use_post)
            env.call(tool_t, args_t)

        ep = env.result("calibrated_teacher")
        scores.append(float(ep.score))

    return records, {
        "n_episodes": len(seeds),
        "n_states": len(records),
        "teacher_mean_score": round(float(np.mean(scores)) if scores else 0.0, 6),
    }


def collect_offline_sft_and_bc_datasets(
    seeds: list[int],
) -> tuple[list[StepRecord], list[StepRecord], dict[str, Any]]:
    sft_records: list[StepRecord] = []
    bc_records: list[StepRecord] = []

    n_natural = 0
    n_correct = 0
    n_nat_abstain = 0
    n_rejected_wrong = 0
    n_aug_abstain = 0

    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        n_natural += 1

        raw = _collect_expert_episode_records(tier, seed, censor_after_day=None)
        if raw is None:
            continue

        ep = raw["episode"]
        if ep.accused is not None and bool(ep.correct):
            n_correct += 1
            sft_records.extend(raw["records"])
            bc_records.extend(raw["bc_records"])
        elif ep.accused is None:
            n_nat_abstain += 1
            bc_records.extend(raw["bc_records"])
        else:
            n_rejected_wrong += 1

        if idx % 3 == 0:
            censor_day = {"easy": 1, "medium": 2, "hard": 3}[tier]
            cen_bc = _collect_expert_episode_records(
                tier,
                seed,
                censor_after_day=censor_day,
            )
            if cen_bc is not None:
                n_aug_abstain += 1
                bc_records.extend(cen_bc["bc_records"])

    stats = {
        "n_episodes": n_natural,
        "correct_accusations": n_correct,
        "natural_abstentions": n_nat_abstain,
        "rejected_wrong_accusations": n_rejected_wrong,
        "augmented_censored_abstentions": n_aug_abstain,
        "stage1_sft_states": len(sft_records),
        "stage2_bc_states": len(bc_records),
    }
    return sft_records, bc_records, stats


def fit_policy_from_records(
    records: list[StepRecord],
    stage_name: str,
    l2_emp: float = 1.5,
    l2_act: float = 1.0,
    l2_split: float = 1.0,
) -> CompactLinearWeights:
    acc_blocks: list[np.ndarray] = []
    acc_dists: list[np.ndarray] = []
    acc_weights: list[float] = []

    pri_blocks: list[np.ndarray] = []
    pri_dists: list[np.ndarray] = []
    pri_weights: list[float] = []

    for r in records:
        if r.acc_target_dist is not None or r.pri_target_dist is not None:
            ef = extract_employee_features(r.state)
            if r.acc_target_dist is not None and ef.shape[0] == r.acc_target_dist.size:
                acc_blocks.append(ef)
                acc_dists.append(r.acc_target_dist)
                acc_weights.append(r.weight)
            if r.pri_target_dist is not None and ef.shape[0] == r.pri_target_dist.size:
                pri_blocks.append(ef)
                pri_dists.append(r.pri_target_dist)
                pri_weights.append(r.weight)

    w_emp_acc = _fit_grouped_employee_head(
        acc_blocks,
        acc_dists,
        np.asarray(acc_weights, dtype=np.float64) if acc_weights else np.zeros(0),
        l2_reg=l2_emp,
    )
    if pri_blocks:
        w_emp_pri = _fit_grouped_employee_head(
            pri_blocks,
            pri_dists,
            np.asarray(pri_weights, dtype=np.float64),
            l2_reg=l2_emp,
        )
    else:
        w_emp_pri = w_emp_acc.copy()

    w_emp = np.vstack([w_emp_acc, w_emp_pri])

    m_tot = len(records)
    x_act = np.zeros((m_tot, D_ACT), dtype=np.float64)
    y_act = np.zeros(m_tot, dtype=np.int64)
    w_act_s = np.zeros(m_tot, dtype=np.float64)

    x_split_list: list[np.ndarray] = []
    y_split_list: list[int] = []
    w_split_list: list[float] = []

    for idx, r in enumerate(records):
        ef = extract_employee_features(r.state)
        acc_p = _stable_softmax(ef @ w_emp[0])
        pri_p = _stable_softmax(ef @ w_emp[1])
        x_act[idx] = extract_action_features(r.state, acc_p)
        y_act[idx] = r.action_idx
        w_act_s[idx] = r.weight
        if r.has_split_label:
            x_split_list.append(extract_split_features(r.state, acc_p, pri_p))
            y_split_list.append(r.split_idx)
            w_split_list.append(r.weight)

    w_act_m, b_act_v = _fit_multinomial_head(
        x_act, y_act, w_act_s, N_ACT, l2_reg=l2_act
    )
    if x_split_list:
        w_split_m, b_split_v = _fit_multinomial_head(
            np.vstack(x_split_list),
            np.asarray(y_split_list, dtype=np.int64),
            np.asarray(w_split_list, dtype=np.float64),
            N_SPLIT,
            l2_reg=l2_split,
        )
    else:
        w_split_m = np.zeros((N_SPLIT, D_SPLIT), dtype=np.float64)
        b_split_v = np.zeros(N_SPLIT, dtype=np.float64)

    return CompactLinearWeights(
        w_emp=w_emp,
        w_act=w_act_m,
        b_act=b_act_v,
        w_split=w_split_m,
        b_split=b_split_v,
        stage=stage_name,
    )


def collect_dagger_round(
    student_weights: CompactLinearWeights,
    seeds: list[int],
    step_weight: float = 1.5,
) -> tuple[list[StepRecord], dict[str, Any]]:
    from canary.env import Env
    from canary.solver.policy import SolverPolicy

    out_records: list[StepRecord] = []
    scores: list[float] = []
    agreements = 0
    total_steps = 0
    ok_steps = 0
    oos_steps = 0
    cap_stalls = 0

    for idx, seed in enumerate(seeds):
        tier = TIERS[idx % len(TIERS)]
        env = Env(tier, seed)
        ins = env.instruction()
        tools = env.tools_spec()

        student = CompactLinearDAggerPolicy(student_weights, name=student_weights.stage)
        student.reset(tools, ins)

        teacher = SolverPolicy()
        teacher.reset(tools, ins)

        max_iters = env.p.tool_call_cap + 4
        for _ in range(max_iters):
            if env.done:
                break
            hist = list(env.history)
            st = student._state_for(hist)
            s_act_idx, s_split_idx, s_target_emp, s_pri_p = student.predict_from_state(st)
            t_act_idx, t_split_idx, t_post = _query_calibrated_solver_teacher(teacher, st, hist)

            if s_act_idx == t_act_idx:
                agreements += 1
            total_steps += 1
            if not st.last_ok or st.repeat_streak >= 3:
                oos_steps += 1

            has_informative_post = (
                st.surfaced_canary_leaks > 0
                or st.surfaced_doc_leaks > 0
                or st.logged_days_count > 0
            )
            acc_t = t_post if (t_act_idx == ACTION_TO_IDX["accuse"] or has_informative_post) else None
            pri_t = t_post if has_informative_post else None
            eff_w = step_weight / math.sqrt(max(1, st.repeat_streak))

            out_records.append(
                StepRecord(
                    state=st,
                    action_idx=t_act_idx,
                    split_idx=t_split_idx,
                    has_split_label=(t_act_idx == ACTION_TO_IDX["plant_canary"]),
                    acc_target_dist=acc_t,
                    pri_target_dist=pri_t,
                    weight=eff_w,
                )
            )

            tool_s, args_s = student._realize_action(st, s_act_idx, s_split_idx, s_target_emp, s_pri_p)
            res = env.call(tool_s, args_s)
            if res.ok:
                ok_steps += 1

        ep = env.result(student.name)
        scores.append(float(ep.score))
        if ep.end_reason == "cap":
            cap_stalls += 1

    stats = {
        "n_episodes": len(seeds),
        "n_states_collected": len(out_records),
        "student_rollout_mean_score": round(float(np.mean(scores)) if scores else 0.0, 6),
        "teacher_action_agreement_on_student_states": round(agreements / max(1, total_steps), 6),
        "student_valid_call_rate": round(ok_steps / max(1, total_steps), 6),
        "out_of_support_state_rate": round(oos_steps / max(1, total_steps), 6),
        "cap_stall_rate": round(cap_stalls / max(1, len(seeds)), 6),
    }
    return out_records, stats


def measure_covariate_shift_on_train_val(
    stage_weights: dict[str, CompactLinearWeights],
    val_seeds: list[int],
) -> dict[str, dict[str, Any]]:
    from canary.env import Env
    from canary.solver.policy import SolverPolicy

    expert_states: list[tuple[CompactState, int]] = []
    dummy_pol = CompactLinearDAggerPolicy()
    for idx, seed in enumerate(val_seeds):
        tier = TIERS[idx % len(TIERS)]
        env = Env(tier, seed)
        ins = env.instruction()
        tools = env.tools_spec()
        teacher = SolverPolicy()
        teacher.reset(tools, ins)
        tracker = _CompactStateTracker(ins)
        for _ in range(env.p.tool_call_cap + 4):
            if env.done:
                break
            hist = list(env.history)
            tracker.ingest_up_to(hist)
            st = tracker.snapshot()
            t_act_idx, t_split_idx, t_post = _query_calibrated_solver_teacher(teacher, st, hist)
            expert_states.append((st, t_act_idx))
            use_post = (
                t_post
                if t_post is not None
                else np.full(max(1, len(st.emp_ids)), 1.0 / max(1, len(st.emp_ids)))
            )
            target_emp = st.emp_ids[int(np.argmax(use_post))] if st.emp_ids else "e00"
            tool_t, args_t = dummy_pol._realize_action(st, t_act_idx, t_split_idx, target_emp, use_post)
            env.call(tool_t, args_t)

    diagnostics: dict[str, dict[str, Any]] = {}
    for s_name, w in stage_weights.items():
        pol_exp = CompactLinearDAggerPolicy(w, name=s_name)
        exp_agree = 0
        for st, t_act in expert_states:
            pred_act, _, _, _ = pol_exp.predict_from_state(st)
            if pred_act == t_act:
                exp_agree += 1
        p_exp_agree = exp_agree / max(1, len(expert_states))

        _, roll_stats = collect_dagger_round(w, val_seeds, step_weight=1.0)
        p_stu_agree = float(roll_stats["teacher_action_agreement_on_student_states"])
        diagnostics[s_name] = {
            "n_episodes": len(val_seeds),
            "agreement_on_expert_states": round(p_exp_agree, 6),
            "agreement_on_student_states": round(p_stu_agree, 6),
            "covariate_shift_agreement_drop": round(p_exp_agree - p_stu_agree, 6),
            "out_of_support_state_rate": roll_stats["out_of_support_state_rate"],
            "student_valid_call_rate": roll_stats["student_valid_call_rate"],
            "cap_stall_rate": roll_stats["cap_stall_rate"],
            "val_mean_score": roll_stats["student_rollout_mean_score"],
        }
    return diagnostics


def replay_verify_episode(ep: Any) -> bool:
    from canary.env import Env

    env = Env(ep.tier, ep.seed)
    for st in ep.steps:
        if env.done:
            break
        tool, args, recorded_res = _step_parts(st)
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


def normal_ci95_stats(values: list[float]) -> dict[str, float]:
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    m = sum(values) / n
    if n < 2:
        return {
            "mean": round(m, 6),
            "ci95_low": round(m, 6),
            "ci95_high": round(m, 6),
            "ci95_half_width": 0.0,
        }
    var = sum((x - m) ** 2 for x in values) / (n - 1)
    hw = 1.96 * math.sqrt(max(0.0, var)) / math.sqrt(n)
    return {
        "mean": round(m, 6),
        "ci95_low": round(m - hw, 6),
        "ci95_high": round(m + hw, 6),
        "ci95_half_width": round(hw, 6),
    }


def bootstrap_ci95_stats(
    values: list[float],
    n_boot: int = 5_000,
    rng_seed: int = 20261115,
) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n == 0:
        return {"mean": 0.0, "ci95_low": 0.0, "ci95_high": 0.0, "ci95_half_width": 0.0}
    m = float(np.mean(arr))
    if n < 2:
        return {
            "mean": round(m, 6),
            "ci95_low": round(m, 6),
            "ci95_high": round(m, 6),
            "ci95_half_width": 0.0,
        }
    rng = np.random.default_rng(rng_seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    means = np.mean(arr[idx], axis=1)
    lo, hi = np.quantile(means, [0.025, 0.975])
    lo_f, hi_f = float(lo), float(hi)
    return {
        "mean": round(m, 6),
        "ci95_low": round(lo_f, 6),
        "ci95_high": round(hi_f, 6),
        "ci95_half_width": round(0.5 * (hi_f - lo_f), 6),
    }


def _valid_call_rate(eps: list[Any]) -> float:
    tot = 0
    ok_cnt = 0
    for ep in eps:
        for st in ep.steps:
            tot += 1
            _, _, res = _step_parts(st)
            if res.get("ok"):
                ok_cnt += 1
    return round(ok_cnt / max(1, tot), 6)


def _invalid_episode_count(eps: list[Any]) -> int:
    bad = 0
    for ep in eps:
        er = getattr(ep, "end_reason", None)
        meta = getattr(ep, "meta", None) or {}
        if er in ("error", "invalid") or meta.get("valid") is False:
            bad += 1
    return bad


def _planted_canaries(ep: Any) -> int:
    cnt = 0
    for st in ep.steps:
        t, _, r = _step_parts(st)
        if t == "plant_canary" and r.get("ok"):
            cnt += 1
    return cnt


def summarize_episodes(eps: list[Any], luck_vals: list[float]) -> dict[str, Any]:
    n = max(1, len(eps))
    scores = [float(e.score) for e in eps]
    sc_ci = bootstrap_ci95_stats(scores)
    lu_ci = bootstrap_ci95_stats(luck_vals)
    acc_days = [int(e.final_day) for e in eps if e.accused is not None]
    can_cnts = [_planted_canaries(e) for e in eps]
    n_corr = sum(1 for e in eps if e.accused is not None and bool(e.correct))
    n_wrong = sum(1 for e in eps if e.accused is not None and not bool(e.correct))
    n_abst = sum(1 for e in eps if e.accused is None)
    n_cap = sum(1 for e in eps if getattr(ep_e := e, "end_reason", None) == "cap")
    return {
        "n": len(eps),
        "mean_score": sc_ci["mean"],
        "score_ci95_low": sc_ci["ci95_low"],
        "score_ci95_high": sc_ci["ci95_high"],
        "luck_adjusted_ev": lu_ci["mean"],
        "luck_ci95_low": lu_ci["ci95_low"],
        "luck_ci95_high": lu_ci["ci95_high"],
        "accuracy": round(n_corr / n, 6),
        "wrong_accuse_rate": round(n_wrong / n, 6),
        "abstain_rate": round(n_abst / n, 6),
        "cap_stall_rate": round(n_cap / n, 6),
        "valid_call_rate": _valid_call_rate(eps),
        "mean_accuse_day": round(float(np.mean(acc_days)), 4) if acc_days else None,
        "mean_canaries_planted": round(float(np.mean(can_cnts)), 4) if can_cnts else 0.0,
        "correct_count": n_corr,
        "wrong_count": n_wrong,
        "abstain_count": n_abst,
        "cap_stall_count": n_cap,
        "invalid_episodes": _invalid_episode_count(eps),
    }


def _paired_comparison(
    after_eps: list[Any],
    before_eps: list[Any],
    after_luck: list[float],
    before_luck: list[float],
) -> dict[str, Any]:
    s_diffs = [round(float(a.score) - float(b.score), 6) for a, b in zip(after_eps, before_eps)]
    l_diffs = [float(a) - float(b) for a, b in zip(after_luck, before_luck)]
    norm_s = normal_ci95_stats(s_diffs)
    boot_s = bootstrap_ci95_stats(s_diffs)
    boot_l = bootstrap_ci95_stats(l_diffs)
    return {
        "n": len(s_diffs),
        "mean_delta": norm_s["mean"],
        "ci95_low": norm_s["ci95_low"],
        "ci95_high": norm_s["ci95_high"],
        "ci95_half_width": norm_s["ci95_half_width"],
        "bootstrap_ci95_low": boot_s["ci95_low"],
        "bootstrap_ci95_high": boot_s["ci95_high"],
        "luck_adjusted_mean_delta": boot_l["mean"],
        "luck_adjusted_ci95_low": boot_l["ci95_low"],
        "luck_adjusted_ci95_high": boot_l["ci95_high"],
        "deltas": s_diffs,
    }


def _load_committed_dev_hard(repo_root: Path, subdir: str, expected_seeds: list[int]) -> list[Any]:
    from canary.eval import episode_from_dict

    ep_file = repo_root / "data" / "runs" / "committed" / "v1.4" / subdir / "hard" / "episodes.jsonl"
    if not ep_file.is_file():
        return []
    by_seed: dict[int, Any] = {}
    for line in ep_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if (raw.get("meta") or {}).get("valid") is False:
            continue
        ep = episode_from_dict(raw)
        by_seed[int(ep.seed)] = ep
    if any(s not in by_seed for s in expected_seeds):
        return []
    return [by_seed[s] for s in expected_seeds]


def evaluate_heldout_and_dev(
    stage_weights: dict[str, CompactLinearWeights],
    heldout_seeds: list[int],
    dev_seeds: list[int],
    repo_root: Path,
    heldout_secret: str = HELDOUT_WORLD_SECRET,
) -> dict[str, Any]:
    from canary import world as canary_world
    from canary.env import Env
    from canary.eval import make_policy_factory, run_episode

    solver_factory = make_policy_factory("solver")
    heuristic_factory = make_policy_factory("heuristic")

    agent_specs: list[tuple[str, Any]] = [
        (
            st_name,
            (lambda w, sn: lambda _s: CompactLinearDAggerPolicy(w, name=sn))(
                stage_weights[st_name], st_name
            ),
        )
        for st_name in ALL_ABLATION_STAGES
    ] + [
        ("heuristic", heuristic_factory),
        ("solver", solver_factory),
    ]
    agent_names = [name for name, _ in agent_specs]

    prev_env_sec = os.environ.get("CANARY_WORLD_SECRET")
    prev_set_sec = getattr(canary_world, "_SET_SECRET", None)
    heldout_eps: dict[str, dict[str, list[Any]]] = {name: {} for name in agent_names}
    heldout_luck: dict[str, dict[str, list[float]]] = {name: {} for name in agent_names}
    replayed_heldout = 0

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
                    replayed_heldout += 1
                    eps_t.append(ep)
                    luck_t.append(luck_adjusted_ev(ep))
                heldout_eps[name][tier] = eps_t
                heldout_luck[name][tier] = luck_t
    finally:
        canary_world.set_world_secret(prev_set_sec)
        if prev_env_sec is None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        else:
            os.environ["CANARY_WORLD_SECRET"] = prev_env_sec

    overall_summary: dict[str, Any] = {}
    by_tier_summary: dict[str, dict[str, Any]] = {t: {} for t in TIERS}
    for name in agent_names:
        pooled_e = [ep for t in TIERS for ep in heldout_eps[name][t]]
        pooled_l = [lv for t in TIERS for lv in heldout_luck[name][t]]
        overall_summary[name] = summarize_episodes(pooled_e, pooled_l)
        for t in TIERS:
            by_tier_summary[t][name] = summarize_episodes(heldout_eps[name][t], heldout_luck[name][t])

    delta_pairs: tuple[tuple[str, str, str], ...] = (
        ("stage1_minus_stage0", "stage1_survivorship_sft", "stage0_untrained"),
        ("stage2_minus_stage1", "stage2_calibrated_bc", "stage1_survivorship_sft"),
        ("stage2_minus_stage0", "stage2_calibrated_bc", "stage0_untrained"),
        ("stage3a_r1_minus_stage2", "stage3a_onpolicy_dagger_r1", "stage2_calibrated_bc"),
        ("stage3_r2_minus_stage3a_r1", "stage3_onpolicy_dagger_r2", "stage3a_onpolicy_dagger_r1"),
        ("stage3_r2_minus_stage2", "stage3_onpolicy_dagger_r2", "stage2_calibrated_bc"),
        ("stage3_r2_minus_stage1", "stage3_onpolicy_dagger_r2", "stage1_survivorship_sft"),
        ("stage3_r2_minus_stage0", "stage3_onpolicy_dagger_r2", "stage0_untrained"),
        ("stage3_r2_minus_heuristic", "stage3_onpolicy_dagger_r2", "heuristic"),
        ("stage3_r2_minus_solver", "stage3_onpolicy_dagger_r2", "solver"),
    )

    paired_overall: dict[str, Any] = {}
    for d_key, a_name, b_name in delta_pairs:
        a_eps = [ep for t in TIERS for ep in heldout_eps[a_name][t]]
        b_eps = [ep for t in TIERS for ep in heldout_eps[b_name][t]]
        a_lu = [lv for t in TIERS for lv in heldout_luck[a_name][t]]
        b_lu = [lv for t in TIERS for lv in heldout_luck[b_name][t]]
        cmp_obj = _paired_comparison(a_eps, b_eps, a_lu, b_lu)
        if d_key != "stage3_r2_minus_stage0":
            cmp_obj = {k: v for k, v in cmp_obj.items() if k != "deltas"}
        paired_overall[d_key] = cmp_obj

    n90_k = min(30, len(heldout_seeds))
    n90_overall: dict[str, Any] = {}
    for name in agent_names:
        pe90 = [ep for t in TIERS for ep in heldout_eps[name][t][:n90_k]]
        pl90 = [lv for t in TIERS for lv in heldout_luck[name][t][:n90_k]]
        n90_overall[name] = summarize_episodes(pe90, pl90)

    dev_block: dict[str, Any] = {}
    replayed_dev = 0
    if dev_seeds:
        prev_dev_env = os.environ.pop("CANARY_WORLD_SECRET", None)
        prev_dev_set = getattr(canary_world, "_SET_SECRET", None)
        dev_eps: dict[str, list[Any]] = {}
        dev_luck: dict[str, list[float]] = {}
        try:
            canary_world.set_world_secret(None)
            for name, factory in agent_specs:
                d_e: list[Any] = []
                d_l: list[float] = []
                for seed in dev_seeds:
                    ep = run_episode(Env("hard", seed), factory(seed))
                    replay_verify_episode(ep)
                    replayed_dev += 1
                    d_e.append(ep)
                    d_l.append(luck_adjusted_ev(ep))
                dev_eps[name] = d_e
                dev_luck[name] = d_l

            for f_key, subdir in (
                ("opencode:google/gemini-4-carbon", "opencode-gemini-4-carbon"),
                ("gemini:gemini-4-carbon", "inproc-gemini-4-carbon"),
            ):
                c_eps = _load_committed_dev_hard(repo_root, subdir, dev_seeds)
                if c_eps:
                    c_lu: list[float] = []
                    for ep in c_eps:
                        replay_verify_episode(ep)
                        replayed_dev += 1
                        c_lu.append(luck_adjusted_ev(ep))
                    dev_eps[f_key] = c_eps
                    dev_luck[f_key] = c_lu
        finally:
            canary_world.set_world_secret(prev_dev_set)
            if prev_dev_env is not None:
                os.environ["CANARY_WORLD_SECRET"] = prev_dev_env

        dev_agents_summary = {
            k_ag: summarize_episodes(dev_eps[k_ag], dev_luck[k_ag]) for k_ag in dev_eps
        }
        dev_block = {
            "protocol_label": f"post-hoc locked dev hard {dev_seeds[0]}..{dev_seeds[-1]}",
            "tier": "hard",
            "world_key": "public",
            "dev_eval_seed_range": f"{dev_seeds[0]}..{dev_seeds[-1]}",
            "n_seeds": len(dev_seeds),
            "episodes_replayed": replayed_dev,
            "agents": dev_agents_summary,
        }

    return {
        "overall": overall_summary,
        "by_tier": by_tier_summary,
        "paired_overall": paired_overall,
        "n90_subset_overall": n90_overall,
        "n90_eval_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[n90_k - 1]}",
        "dev_hard": dev_block,
        "episodes_replayed_heldout": replayed_heldout,
        "episodes_replayed_total": replayed_heldout + replayed_dev,
    }


def format_markdown_table(summary: dict[str, Any]) -> str:
    ho = summary["heldout_ablation"]
    ov = ho["overall"]
    bt = ho["by_tier"]
    pd = ho["paired_deltas"]
    cs = summary["covariate_shift_diagnostics"]
    bef = summary["before"]
    aft = summary["after"]
    pair = summary["paired"]

    lines: list[str] = []
    title = "CompactLinearDAggerPolicy Covariate-Shift and 4-Stage DAgger Ablation (Canary v1.4)"
    lines.append(title)
    lines.append("=" * len(title))
    lines.append("")
    lines.append(f"- Run ID: `{summary['run_id']}`")
    lines.append(f"- Model: `{summary['model']}` (`{summary['policy_architecture']['param_count']}` linear parameters, 0 LLM calls)")
    lines.append(f"- Inference module: `{summary['inference_module']}` (AST-verified zero `canary.solver` / `canary.world` imports in inference path)")
    lines.append(
        f"- Train seed range: `{summary['train_seed_range']}` strictly inside `TRAIN_SEEDS [100000, 200000)` "
        f"(Offline SFT/BC `{summary['offline_seed_range']}`, DAgger R1 `{summary['dagger_r1_seed_range']}`, "
        f"DAgger R2 `{summary['dagger_r2_seed_range']}`, Covariate-Shift Val `{summary['val_seed_range']}`)"
    )
    lines.append(
        f"- Primary held-out eval seed range: `{summary['eval_seed_range']}` across `easy, medium, hard` "
        f"(`n=60/tier`, `n={summary['n']}` paired episodes, world secret `{summary['world_secret_tag']}`)"
    )
    lines.append(
        f"- Headline Before -> After (`stage0_untrained` -> `stage3_onpolicy_dagger_r2`, `n={summary['n']}`): "
        f"mean score `{bef['mean_score']:+.4f}` -> `{aft['mean_score']:+.4f}`, "
        f"paired mean delta `{pair['mean_delta']:+.4f}` "
        f"(95% CI `[{pair['ci95_low']:+.4f}, {pair['ci95_high']:+.4f}]`), "
        f"luck-adjusted EV delta `{pair['luck_adjusted_mean_delta']:+.4f}` "
        f"(`[{pair['luck_adjusted_ci95_low']:+.4f}, {pair['luck_adjusted_ci95_high']:+.4f}]`), "
        f"replay verified `{summary['replay_verified']}` (`{summary['total_episodes_replayed']}` episodes, `{summary['invalid_episodes']}` invalid)"
    )

    lines.append("")
    s1 = f"1. Held-Out 4-Stage Progression and Reference Baselines (Seeds {summary['eval_seed_range']}, n={summary['n']})"
    lines.append(s1)
    lines.append("-" * len(s1))
    lines.append("")
    lines.append(
        "| Stage / Policy | n | Mean Score [95% CI] | Luck-Adjusted EV [95% CI] | Accuracy | Wrong Accuse | Abstain | Cap Stall | Valid Call Rate | Canaries/Ep |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    row_order = list(ALL_ABLATION_STAGES) + ["heuristic", "solver"]
    for ag in row_order:
        m = ov[ag]
        lines.append(
            f"| {ag} | {m['n']} | {m['mean_score']:+.4f} [{m['score_ci95_low']:+.4f}, {m['score_ci95_high']:+.4f}] | "
            f"{m['luck_adjusted_ev']:+.4f} [{m['luck_ci95_low']:+.4f}, {m['luck_ci95_high']:+.4f}] | "
            f"{m['accuracy']:.3f} | {m['wrong_accuse_rate']:.3f} | {m['abstain_rate']:.3f} | "
            f"{m['cap_stall_rate']:.3f} | {m['valid_call_rate']:.4f} | {m['mean_canaries_planted']:.2f} |"
        )

    lines.append("")
    s2 = f"2. Paired Step-by-Step Ablation Deltas on Held-Out Seeds {summary['eval_seed_range']} (n={summary['n']})"
    lines.append(s2)
    lines.append("-" * len(s2))
    lines.append("")
    lines.append(
        "| Ablation Comparison (After - Before) | Mechanism Isolated | Score Delta [95% CI] | Luck-Adjusted EV Delta [95% CI] |"
    )
    lines.append("|---|---|---:|---:|")
    mech_labels = (
        ("stage1_minus_stage0", "stage1_survivorship_sft - stage0_untrained", "Offline SFT on winning rollouts only (survivorship bias + covariate shift)"),
        ("stage2_minus_stage1", "stage2_calibrated_bc - stage1_survivorship_sft", "Adding censored horizon abstentions + soft Bayesian posteriors (still off-policy)"),
        ("stage3a_r1_minus_stage2", "stage3a_onpolicy_dagger_r1 - stage2_calibrated_bc", "On-policy DAgger Round 1 state recovery on student rollouts"),
        ("stage3_r2_minus_stage3a_r1", "stage3_onpolicy_dagger_r2 - stage3a_onpolicy_dagger_r1", "On-policy DAgger Round 2 refinement on student rollouts"),
        ("stage3_r2_minus_stage2", "stage3_onpolicy_dagger_r2 - stage2_calibrated_bc", "Total on-policy DAgger gain over calibrated offline BC (pure covariate-shift fix)"),
        ("stage3_r2_minus_stage1", "stage3_onpolicy_dagger_r2 - stage1_survivorship_sft", "Calibrated posteriors + abstentions + on-policy DAgger over survivorship SFT"),
        ("stage3_r2_minus_stage0", "stage3_onpolicy_dagger_r2 - stage0_untrained", "Headline Before -> After improvement from Canary experience"),
        ("stage3_r2_minus_heuristic", "stage3_onpolicy_dagger_r2 - heuristic", "Compact 785-param linear DAgger policy vs scripted heuristic baseline"),
        ("stage3_r2_minus_solver", "stage3_onpolicy_dagger_r2 - solver", "Compact 785-param linear DAgger policy vs exact nonlinear Bayesian solver"),
    )
    for d_key, label_cmp, mech in mech_labels:
        d = pd[d_key]
        lines.append(
            f"| {label_cmp} | {mech} | "
            f"{d['mean_delta']:+.4f} [{d['ci95_low']:+.4f}, {d['ci95_high']:+.4f}] | "
            f"{d['luck_adjusted_mean_delta']:+.4f} [{d['luck_adjusted_ci95_low']:+.4f}, {d['luck_adjusted_ci95_high']:+.4f}] |"
        )

    lines.append("")
    val_n = cs["stage0_untrained"]["n_episodes"]
    s3 = f"3. Direct Covariate-Shift Diagnostics on Disjoint Train-Val Slice ({summary['val_seed_range']}, n={val_n})"
    lines.append(s3)
    lines.append("-" * len(s3))
    lines.append("")
    lines.append(
        "| Stage | Expert-State Agreement P_expert | Student-State Agreement P_student | Covariate-Shift Drop | Out-of-Support State Rate | Valid Call Rate | Cap Stall Rate | Train-Val Score |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for st_name in ALL_ABLATION_STAGES:
        c = cs[st_name]
        lines.append(
            f"| {st_name} | {c['agreement_on_expert_states']:.4f} | {c['agreement_on_student_states']:.4f} | "
            f"{c['covariate_shift_agreement_drop']:+.4f} | {c['out_of_support_state_rate']:.4f} | "
            f"{c['student_valid_call_rate']:.4f} | {c['cap_stall_rate']:.4f} | {c['val_mean_score']:+.4f} |"
        )

    lines.append("")
    s4 = f"4. Held-Out Per-Tier Breakdown (Seeds {summary['eval_seed_range']}, n={ho['n_per_tier']}/tier)"
    lines.append(s4)
    lines.append("-" * len(s4))
    lines.append("")
    lines.append(
        "| Tier | Stage / Policy | n | Mean Score [95% CI] | Luck-Adjusted EV | Accuracy | Wrong Accuse | Abstain | Cap Stall |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for tier in TIERS:
        for ag in (
            "stage0_untrained",
            "stage1_survivorship_sft",
            "stage2_calibrated_bc",
            "stage3_onpolicy_dagger_r2",
            "heuristic",
            "solver",
        ):
            m = bt[tier][ag]
            lines.append(
                f"| {tier} | {ag} | {m['n']} | {m['mean_score']:+.4f} [{m['score_ci95_low']:+.4f}, {m['score_ci95_high']:+.4f}] | "
                f"{m['luck_adjusted_ev']:+.4f} | {m['accuracy']:.3f} | {m['wrong_accuse_rate']:.3f} | "
                f"{m['abstain_rate']:.3f} | {m['cap_stall_rate']:.3f} |"
            )

    dev_hard = ho.get("dev_hard") or {}
    if dev_hard and dev_hard.get("agents"):
        lines.append("")
        s5 = f"5. Keyless Reference Comparison on {dev_hard['protocol_label']} (Public Worlds, n={dev_hard['n_seeds']})"
        lines.append(s5)
        lines.append("-" * len(s5))
        lines.append("")
        lines.append(
            f"- Protocol: `{dev_hard['protocol_label']}` (`b\"public\"`, locked post-hoc for zero-API cross-comparison against committed frontier runs)."
        )
        lines.append("")
        lines.append("| Policy / Agent | n | Mean Score [95% CI] | Luck-Adjusted EV | Accuracy | Wrong Accuse | Abstain |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for ag_k, m in dev_hard["agents"].items():
            lines.append(
                f"| {ag_k} | {m['n']} | {m['mean_score']:+.4f} [{m['score_ci95_low']:+.4f}, {m['score_ci95_high']:+.4f}] | "
                f"{m['luck_adjusted_ev']:+.4f} | {m['accuracy']:.3f} | {m['wrong_accuse_rate']:.3f} | {m['abstain_rate']:.3f} |"
            )

    return "\n".join(lines) + "\n"


def run_ablation_pipeline(
    offline_count: int = 150,
    dagger_r1_count: int = 150,
    dagger_r2_count: int = 150,
    val_count: int = 60,
    heldout_count: int = 60,
    dev_count: int = 30,
    summary_out: str | Path = DEFAULT_SUMMARY_PATH,
    table_out: str | Path = DEFAULT_TABLE_PATH,
    ckpt_out: str | Path = DEFAULT_CKPT_PATH,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    root = repo_root if repo_root is not None else Path(__file__).resolve().parents[1]

    offline_seeds = list(range(OFFLINE_SEED_RANGE[0], OFFLINE_SEED_RANGE[0] + offline_count))
    r1_seeds = list(range(DAGGER_R1_SEED_RANGE[0], DAGGER_R1_SEED_RANGE[0] + dagger_r1_count))
    r2_seeds = list(range(DAGGER_R2_SEED_RANGE[0], DAGGER_R2_SEED_RANGE[0] + dagger_r2_count))
    val_seeds = list(range(VAL_SEED_RANGE[0], VAL_SEED_RANGE[0] + val_count))
    if len(offline_seeds) + len(r1_seeds) + len(r2_seeds) + len(val_seeds) != len(
        set(offline_seeds) | set(r1_seeds) | set(r2_seeds) | set(val_seeds)
    ):
        raise ValueError("offline, dagger_r1, dagger_r2, and val seed slices must be mutually disjoint")
    all_train_seeds = sorted(set(offline_seeds + r1_seeds + r2_seeds + val_seeds))
    heldout_seeds = list(range(HELDOUT_SEED_RANGE[0], HELDOUT_SEED_RANGE[0] + heldout_count))
    dev_seeds = list(range(DEV_HARD_SEED_RANGE[0], DEV_HARD_SEED_RANGE[0] + dev_count)) if dev_count > 0 else []

    assert_strict_seed_hygiene(all_train_seeds, heldout_seeds, dev_seeds=dev_seeds)

    w_stage0 = CompactLinearWeights.zeros("stage0_untrained")

    sft_records, bc_records, offline_stats = collect_offline_sft_and_bc_datasets(offline_seeds)
    w_stage1 = fit_policy_from_records(sft_records, "stage1_survivorship_sft")
    w_stage2 = fit_policy_from_records(bc_records, "stage2_calibrated_bc")

    teacher_base_records, teacher_base_stats = _collect_teacher_offline_records(offline_seeds)
    r1_records, r1_stats = collect_dagger_round(w_stage2, r1_seeds, step_weight=1.5)
    w_stage3a = fit_policy_from_records(
        teacher_base_records + r1_records,
        "stage3a_onpolicy_dagger_r1",
    )

    r2_records, r2_stats = collect_dagger_round(w_stage3a, r2_seeds, step_weight=1.75)
    w_stage3 = fit_policy_from_records(
        teacher_base_records + r1_records + r2_records,
        "stage3_onpolicy_dagger_r2",
    )

    stage_weights: dict[str, CompactLinearWeights] = {
        "stage0_untrained": w_stage0,
        "stage1_survivorship_sft": w_stage1,
        "stage2_calibrated_bc": w_stage2,
        "stage3a_onpolicy_dagger_r1": w_stage3a,
        "stage3_onpolicy_dagger_r2": w_stage3,
    }

    cov_shift_diag = measure_covariate_shift_on_train_val(stage_weights, val_seeds)
    eval_res = evaluate_heldout_and_dev(
        stage_weights=stage_weights,
        heldout_seeds=heldout_seeds,
        dev_seeds=dev_seeds,
        repo_root=root,
        heldout_secret=HELDOUT_WORLD_SECRET,
    )

    secret_sha16 = hashlib.sha256(HELDOUT_WORLD_SECRET.encode("utf-8")).hexdigest()[:16]
    secret_tag = f"sha256:{secret_sha16}"

    bef_m = eval_res["overall"]["stage0_untrained"]
    aft_m = eval_res["overall"]["stage3_onpolicy_dagger_r2"]
    headline_paired = eval_res["paired_overall"]["stage3_r2_minus_stage0"]
    n_total = int(aft_m["n"])

    before_block = {
        "stage": "stage0_untrained",
        "n": n_total,
        "mean_score": bef_m["mean_score"],
        "ci95_low": bef_m["score_ci95_low"],
        "ci95_high": bef_m["score_ci95_high"],
        "luck_adjusted_ev": bef_m["luck_adjusted_ev"],
        "accuracy": bef_m["accuracy"],
        "wrong_accuse_rate": bef_m["wrong_accuse_rate"],
        "abstain_rate": bef_m["abstain_rate"],
        "cap_stall_rate": bef_m["cap_stall_rate"],
        "valid_call_rate": bef_m["valid_call_rate"],
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "invalid_episodes": int(bef_m["invalid_episodes"]),
    }
    after_block = {
        "stage": "stage3_onpolicy_dagger_r2",
        "n": n_total,
        "mean_score": aft_m["mean_score"],
        "ci95_low": aft_m["score_ci95_low"],
        "ci95_high": aft_m["score_ci95_high"],
        "luck_adjusted_ev": aft_m["luck_adjusted_ev"],
        "accuracy": aft_m["accuracy"],
        "wrong_accuse_rate": aft_m["wrong_accuse_rate"],
        "abstain_rate": aft_m["abstain_rate"],
        "cap_stall_rate": aft_m["cap_stall_rate"],
        "valid_call_rate": aft_m["valid_call_rate"],
        "world_secret_tag": secret_tag,
        "replay_verified": True,
        "invalid_episodes": int(aft_m["invalid_episodes"]),
    }

    elapsed_s = round(time.perf_counter() - t0, 2)
    summary: dict[str, Any] = {
        "run_id": RUN_ID,
        "model": MODEL_LABEL,
        "inference_module": INFERENCE_MODULE_REL,
        "tiers_version": "v1.4",
        "tiers": list(TIERS),
        "n": n_total,
        "train_seeds": {"start": min(all_train_seeds), "stop": max(all_train_seeds) + 1},
        "eval_seeds": {"start": heldout_seeds[0], "stop": heldout_seeds[-1] + 1},
        "train_seed_range": f"{min(all_train_seeds)}..{max(all_train_seeds)}",
        "offline_seed_range": f"{offline_seeds[0]}..{offline_seeds[-1]}",
        "dagger_r1_seed_range": f"{r1_seeds[0]}..{r1_seeds[-1]}",
        "dagger_r2_seed_range": f"{r2_seeds[0]}..{r2_seeds[-1]}",
        "val_seed_range": f"{val_seeds[0]}..{val_seeds[-1]}",
        "eval_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
        "replay_verified": True,
        "invalid_episodes": int(bef_m["invalid_episodes"]) + int(aft_m["invalid_episodes"]),
        "world_secret_tag": secret_tag,
        "before": before_block,
        "after": after_block,
        "paired": headline_paired,
        "notes": (
            f"4-stage covariate-shift ablation strictly on TRAIN_SEEDS ({min(all_train_seeds)}..{max(all_train_seeds)}); "
            f"held-out n={n_total} ({heldout_seeds[0]}..{heldout_seeds[-1]}) score "
            f"{bef_m['mean_score']:+.3f} -> {aft_m['mean_score']:+.3f} "
            f"(DAgger vs calibrated BC +{eval_res['paired_overall']['stage3_r2_minus_stage2']['mean_delta']:.3f}, "
            f"DAgger vs survivorship SFT +{eval_res['paired_overall']['stage3_r2_minus_stage1']['mean_delta']:.3f})."
        ),
        "policy_architecture": {
            "class_name": "CompactLinearDAggerPolicy",
            "param_count": w_stage3.param_count(),
            "d_emp": D_EMP,
            "d_act": D_ACT,
            "d_split": D_SPLIT,
            "n_actions": N_ACT,
            "n_split_modes": N_SPLIT,
            "stage_l2_norms": {k: v.l2_norm() for k, v in stage_weights.items()},
        },
        "training_stages": {
            "offline_collection": offline_stats,
            "teacher_offline_base": teacher_base_stats,
            "dagger_round_1": r1_stats,
            "dagger_round_2": r2_stats,
        },
        "covariate_shift_diagnostics": cov_shift_diag,
        "heldout_ablation": {
            "eval_seed_range": f"{heldout_seeds[0]}..{heldout_seeds[-1]}",
            "n_per_tier": len(heldout_seeds),
            "n_total_per_policy": n_total,
            "world_secret_tag": secret_tag,
            "overall": eval_res["overall"],
            "by_tier": eval_res["by_tier"],
            "paired_deltas": {
                k: ({kk: vv for kk, vv in v.items() if kk != "deltas"} if isinstance(v, dict) else v)
                for k, v in eval_res["paired_overall"].items()
            },
            "n90_subset_eval_seed_range": eval_res["n90_eval_seed_range"],
            "n90_subset_overall": eval_res["n90_subset_overall"],
            "dev_hard": eval_res["dev_hard"],
        },
        "learned_weights_stage3": w_stage3.to_dict(decimals=5),
        "total_episodes_replayed": eval_res["episodes_replayed_total"],
        "elapsed_seconds": elapsed_s,
    }

    ckpt_path = Path(ckpt_out)
    ckpt_path.parent.mkdir(parents=True, exist_ok=True)
    ckpt_payload = {
        "run_id": RUN_ID,
        "stages": {k: v.to_dict(decimals=6) for k, v in stage_weights.items()},
    }
    ckpt_path.write_text(json.dumps(ckpt_payload, indent=2) + "\n", encoding="utf-8")

    sum_path = Path(summary_out)
    if not sum_path.is_absolute():
        sum_path = root / sum_path
    sum_path.parent.mkdir(parents=True, exist_ok=True)
    sum_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    tbl_path = Path(table_out)
    if not tbl_path.is_absolute():
        tbl_path = root / tbl_path
    tbl_path.parent.mkdir(parents=True, exist_ok=True)
    tbl_md = format_markdown_table(summary)
    tbl_path.write_text(tbl_md, encoding="utf-8")

    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Train and evaluate 4-stage CompactLinearDAggerPolicy covariate-shift ablation."
    )
    ap.add_argument("--offline-count", type=int, default=150)
    ap.add_argument("--dagger-r1-count", type=int, default=150)
    ap.add_argument("--dagger-r2-count", type=int, default=150)
    ap.add_argument("--val-count", type=int, default=60)
    ap.add_argument("--heldout-count", type=int, default=60)
    ap.add_argument("--dev-count", type=int, default=30)
    ap.add_argument("--summary-out", type=str, default=DEFAULT_SUMMARY_PATH)
    ap.add_argument("--table-out", type=str, default=DEFAULT_TABLE_PATH)
    ap.add_argument("--ckpt-out", type=str, default=DEFAULT_CKPT_PATH)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = run_ablation_pipeline(
        offline_count=args.offline_count,
        dagger_r1_count=args.dagger_r1_count,
        dagger_r2_count=args.dagger_r2_count,
        val_count=args.val_count,
        heldout_count=args.heldout_count,
        dev_count=args.dev_count,
        summary_out=args.summary_out,
        table_out=args.table_out,
        ckpt_out=args.ckpt_out,
    )
    bef = summary["before"]["mean_score"]
    aft = summary["after"]["mean_score"]
    d_mean = summary["paired"]["mean_delta"]
    d_lo = summary["paired"]["ci95_low"]
    d_hi = summary["paired"]["ci95_high"]
    print(
        f"[{summary['run_id']}] n={summary['n']} before={bef:+.4f} after={aft:+.4f} "
        f"delta={d_mean:+.4f} [{d_lo:+.4f}, {d_hi:+.4f}] in {summary['elapsed_seconds']:.2f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
