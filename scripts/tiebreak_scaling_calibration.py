"""Experience sample-efficiency scaling law and cross-model calibration/failure classifier.

Part A trains a compact pure-NumPy linear/logistic-softmax investigator policy across
training budgets N_train in [0, 15, 60, 240, 900] strictly from TRAIN_SEEDS (107000..108999)
with zero solver/world imports at inference, then evaluates every checkpoint on paired
HELDOUT_SEEDS 800000..800029 (n=30/tier, 90 episodes/budget) with replay verification.

Part B provides classify_episodes(episodes_path, world_secret=None), replaying any Canary
episodes.jsonl alongside evaluation-only SolverPolicy belief inspection into 8 mutually
exclusive calibration and failure categories.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

for _blas_env in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_blas_env, "1")

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TIERS: tuple[str, ...] = ("easy", "medium", "hard")
TRAIN_BUDGETS: tuple[int, ...] = (0, 15, 60, 240, 900)
TRAIN_SEED_MIN = 107_000
TRAIN_SEED_MAX = 108_999
TIER_TRAIN_OFFSETS: dict[str, int] = {"easy": 107_000, "medium": 107_600, "hard": 108_200}
HELDOUT_EVAL_SEEDS: tuple[int, ...] = tuple(range(800_000, 800_030))
DEFAULT_WORLD_SECRET = "canary-tiebreak-heldout-v14-eval-01"

OUT_DIR_DEFAULT = ROOT / "results" / "tiebreak" / "scaling"
SUMMARY_JSON_DEFAULT = OUT_DIR_DEFAULT / "scaling_summary.json"
TABLE_MD_DEFAULT = OUT_DIR_DEFAULT / "table.md"

CATEGORIES: tuple[str, ...] = (
    "calibrated_win",
    "lucky_win",
    "unlucky_noise_loss",
    "premature_gamble_loss",
    "horizon_gamble_loss",
    "calibrated_abstain",
    "missed_commit_abstain",
    "protocol_or_cap_stall",
)

DISGRUNTLED_QUERIES: tuple[str, ...] = (
    "promotion",
    "raise",
    "deserve",
    "burn out",
    "recruiter",
    "goalposts",
)
INTERVIEW_TOPICS: tuple[str, ...] = (
    "recent_documents",
    "contacts_outside",
    "workload",
    "access_needs",
)
CANARY_LABELS = "ABCDEFGH"
TOOL_ACTIONS: tuple[str, ...] = (
    "check_leak_feed",
    "search_messages",
    "read_access_logs",
    "plant_canary",
    "interview",
    "finish_day",
)

D_SUSPECT = 14
D_COMMIT = 10
D_WAIT = 6
D_TOOL = 8
D_CANARY = 4


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - float(np.max(logits))
    exps = np.exp(np.clip(shifted, -60.0, 60.0))
    total = float(np.sum(exps))
    if total <= 0.0 or not math.isfinite(total):
        return np.full_like(logits, 1.0 / max(1, len(logits)), dtype=np.float64)
    return exps / total


def _sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    clipped = np.clip(x, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def _logit(p: float) -> float:
    q = min(1.0 - 1e-6, max(1e-6, float(p)))
    return math.log(q / (1.0 - q))


def parse_public_instruction(instruction: str) -> dict[str, Any]:
    params: dict[str, Any] = {
        "n_employees": 20,
        "n_days": 14,
        "p_leak": 0.75,
        "delay_choices": (1, 2),
        "leak_damage": 0.05,
        "canary_cost": 0.01,
        "canaries_per_day": 1,
        "max_variants": 3,
        "restrict_cost_per_day": 0.01,
        "actions_per_day": 8,
        "tool_call_cap": 300,
        "leak_window_days": 3,
        "wrong_accusation_score": -1.0,
        "fingerprint_accuracy": 1.0,
        "decoy": False,
        "framing": False,
        "careful_mole": False,
        "known_v": ("not visible until they surface" in (instruction or "").lower()),
    }
    text = instruction or ""
    idx = text.find("Exact parameters")
    if idx >= 0:
        kv = dict(re.findall(r"^- (\w+): (.+)$", text[idx:], flags=re.M))
        int_keys = (
            "n_employees",
            "n_days",
            "canaries_per_day",
            "max_variants",
            "actions_per_day",
            "tool_call_cap",
            "leak_window_days",
        )
        float_keys = (
            "p_leak",
            "leak_damage",
            "canary_cost",
            "restrict_cost_per_day",
            "wrong_accusation_score",
            "fingerprint_accuracy",
        )
        bool_keys = ("decoy", "framing", "careful_mole")
        for k in int_keys:
            if k in kv:
                try:
                    params[k] = int(float(kv[k].strip()))
                except ValueError:
                    pass
        for k in float_keys:
            if k in kv:
                try:
                    params[k] = float(kv[k].strip())
                except ValueError:
                    pass
        for k in bool_keys:
            if k in kv:
                params[k] = kv[k].strip().lower() in ("on", "true", "1", "yes")
        if "delay_choices" in kv:
            try:
                vals = tuple(int(x.strip()) for x in kv["delay_choices"].split(",") if x.strip())
                if vals:
                    params["delay_choices"] = vals
            except ValueError:
                pass
    return params


@dataclass
class PublicObsState:
    params: dict[str, Any]
    employees: list[str] = field(default_factory=list)
    today: int = 1
    visible_v: float = 1.0
    actions_used_today: int = 0
    canaries_today: int = 0
    restricted: set[str] = field(default_factory=set)
    docs: dict[str, dict[str, Any]] = field(default_factory=dict)
    feed: dict[str, dict[str, Any]] = field(default_factory=dict)
    access_reg: dict[str, int] = field(default_factory=dict)
    access_ah: dict[str, int] = field(default_factory=dict)
    logged_days: set[int] = field(default_factory=set)
    angry_counts: dict[str, int] = field(default_factory=dict)
    seen_msg_ids: set[str] = field(default_factory=set)
    queries_done: set[str] = field(default_factory=set)
    iv_evasive: dict[str, int] = field(default_factory=dict)
    iv_coop: dict[str, int] = field(default_factory=dict)
    interviewed_today: set[str] = field(default_factory=set)
    feed_checked_today: bool = False
    docs_listed_today: bool = False
    status_checked_today: bool = False
    total_calls: int = 0


def _step_fields(st: Any) -> tuple[str, dict[str, Any], dict[str, Any], int]:
    if hasattr(st, "tool"):
        return (
            str(st.tool),
            dict(st.args or {}),
            dict(st.result or {}),
            int(getattr(st, "day", 1)),
        )
    return (
        str(st.get("tool", "")),
        dict(st.get("args") or {}),
        dict(st.get("result") or {}),
        int(st.get("day", 1)),
    )


def ingest_step_into_state(state: PublicObsState, st: Any) -> None:
    tool, args, res, step_day = _step_fields(st)
    state.total_calls += 1
    if not res.get("ok"):
        err_txt = str(res.get("error") or "")
        if "daily action limit" in err_txt:
            state.actions_used_today = int(state.params.get("actions_per_day", 8))
        elif "canary limit" in err_txt:
            state.canaries_today = int(state.params.get("canaries_per_day", 1))
        return
    data = res.get("data") or {}
    investigative = {
        "read_access_logs",
        "search_messages",
        "read_message",
        "interview",
        "plant_canary",
        "check_leak_feed",
        "restrict_access",
        "unrestrict_access",
    }
    if tool in investigative:
        state.actions_used_today += 1
    if tool == "list_employees":
        emps = data.get("employees") or []
        state.employees = [e["id"] if isinstance(e, dict) else str(e) for e in emps]
        if state.employees:
            state.params["n_employees"] = len(state.employees)
    elif tool == "status":
        d = int(data.get("day", state.today))
        if d != state.today:
            state.today = d
            state.actions_used_today = 0
            state.canaries_today = 0
            state.interviewed_today.clear()
            state.feed_checked_today = False
            state.docs_listed_today = False
        state.visible_v = float(data.get("V", state.visible_v))
        state.restricted = set(data.get("restricted") or [])
        left = data.get("actions_left_today")
        if isinstance(left, int):
            state.actions_used_today = max(0, int(state.params["actions_per_day"]) - left)
        state.status_checked_today = True
    elif tool == "list_documents":
        for d in data.get("documents") or []:
            did = str(d["doc_id"])
            raw_var = d.get("variants")
            emp_to_var: dict[str, str] = {}
            if isinstance(raw_var, dict):
                for k, v in raw_var.items():
                    if isinstance(v, list):
                        for emp in v:
                            emp_to_var[str(emp)] = str(k)
                    elif isinstance(v, str):
                        emp_to_var[str(k)] = v
            prev = state.docs.get(did, {})
            state.docs[did] = {
                "doc_id": did,
                "day": int(d.get("day", step_day)),
                "recipients": set(d.get("recipients") or prev.get("recipients") or ()),
                "is_canary": bool(d.get("is_canary", prev.get("is_canary", False))),
                "variants": emp_to_var or dict(prev.get("variants") or {}),
            }
        state.docs_listed_today = True
    elif tool == "plant_canary":
        cid = str(data.get("canary_id") or data.get("doc_id") or f"c{state.today}")
        asg = {str(k): str(v) for k, v in (args.get("assignment") or {}).items()}
        state.docs[cid] = {
            "doc_id": cid,
            "day": state.today,
            "recipients": set(asg.keys()),
            "is_canary": True,
            "variants": asg,
        }
        state.canaries_today += 1
        state.visible_v = max(0.0, state.visible_v - float(state.params["canary_cost"]))
    elif tool == "check_leak_feed":
        for it in data.get("items") or []:
            did = str(it["doc_id"])
            state.feed[did] = {
                "doc_id": did,
                "surfaced_day": int(it.get("surfaced_day", state.today)),
                "variant": it.get("variant"),
            }
        state.feed_checked_today = True
    elif tool == "read_access_logs":
        d_from = int(args.get("day_from", 1))
        d_to = int(args.get("day_to", max(1, state.today - 1)))
        new_days = [d for d in range(d_from, d_to + 1) if d < state.today and d not in state.logged_days]
        if new_days and args.get("employee") is None:
            new_set = set(new_days)
            state.logged_days.update(new_set)
            for entry in data.get("logs") or []:
                if int(entry.get("day", 0)) in new_set:
                    emp = str(entry["employee"])
                    if entry.get("after_hours"):
                        state.access_ah[emp] = state.access_ah.get(emp, 0) + 1
                    else:
                        state.access_reg[emp] = state.access_reg.get(emp, 0) + 1
    elif tool == "search_messages":
        q = str(args.get("query", ""))
        state.queries_done.add(q)
        for m in data.get("messages") or []:
            mid = str(m.get("id", ""))
            if mid and mid not in state.seen_msg_ids:
                state.seen_msg_ids.add(mid)
                snd = str(m.get("sender", ""))
                if snd:
                    state.angry_counts[snd] = state.angry_counts.get(snd, 0) + 1
    elif tool == "interview":
        emp = str(args.get("employee", ""))
        ans = str(data.get("answer", data.get("signal", ""))).lower()
        state.interviewed_today.add(emp)
        evasive_markers = ("evasive", "deflect", "vague", "hesitat", "uncomfortable", "decline", "change the subject")
        is_ev = any(tok in ans for tok in evasive_markers)
        if is_ev:
            state.iv_evasive[emp] = state.iv_evasive.get(emp, 0) + 1
        else:
            state.iv_coop[emp] = state.iv_coop.get(emp, 0) + 1
    elif tool == "restrict_access":
        emp = str(args.get("employee", ""))
        if emp:
            state.restricted.add(emp)
    elif tool == "unrestrict_access":
        emp = str(args.get("employee", ""))
        state.restricted.discard(emp)
    elif tool == "advance_day":
        if "day" in data:
            state.today = int(data["day"])
        else:
            state.today += 1
        if "V" in data:
            state.visible_v = float(data["V"])
        state.actions_used_today = 0
        state.canaries_today = 0
        state.interviewed_today.clear()
        state.feed_checked_today = False
        state.docs_listed_today = False
        state.status_checked_today = True


def expected_true_v_public(state: PublicObsState) -> float:
    p = state.params
    if not p.get("known_v", True):
        return float(state.visible_v)
    delays = p.get("delay_choices") or (1, 2)
    p_leak = float(p.get("p_leak", 0.75))
    dmg = float(p.get("leak_damage", 0.05))
    pending = 0.0
    for d in range(1, state.today):
        frac_unseen = sum(1 for dl in delays if d + dl > state.today) / max(1, len(delays))
        pending += p_leak * frac_unseen
    return max(0.0, float(state.visible_v) - dmg * pending)


def inferred_decoy_id(state: PublicObsState) -> str | None:
    if not state.params.get("decoy") or not state.angry_counts:
        return None
    ranked = sorted(state.angry_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top_emp, n1 = ranked[0]
    n2 = ranked[1][1] if len(ranked) > 1 else 0
    if n1 >= 3 and n1 >= 3 * max(1, n2):
        return top_emp
    return None


def compute_suspect_features(state: PublicObsState) -> np.ndarray:
    emps = state.employees or [f"e{i:02d}" for i in range(int(state.params["n_employees"]))]
    m = len(emps)
    feats = np.zeros((m, D_SUSPECT), dtype=np.float64)
    p = state.params
    fp_acc = float(p.get("fingerprint_accuracy", 1.0))
    exact_fp = 1.0 if fp_acc >= 0.999 else 0.0
    noisy_fp = 1.0 - exact_fp
    delays = p.get("delay_choices") or (1, 2)
    max_delay = max(delays)
    p_leak = float(p.get("p_leak", 0.75))
    careful = bool(p.get("careful_mole", False))
    decoy_emp = inferred_decoy_id(state)
    decoy_on = 1.0 if p.get("decoy") else 0.0

    reg_prepared: list[tuple[set[str], float]] = []
    can_prepared: list[tuple[set[str], dict[str, str], Any, bool, float]] = []
    for did, item in state.feed.items():
        doc = state.docs.get(did)
        if not doc:
            continue
        recs = doc["recipients"]
        if doc["is_canary"]:
            shown = item.get("variant")
            variants = doc["variants"]
            has_var = (shown is not None) and bool(variants)
            if has_var:
                grp_sz = sum(1 for v in variants.values() if v == shown)
                hit_info = math.log(max(1.05, m / max(1, grp_sz)))
            else:
                hit_info = 0.0
            can_prepared.append((recs, variants, shown, has_var, hit_info))
        else:
            reg_info = math.log(max(1.05, m / max(1, len(recs))))
            reg_prepared.append((recs, reg_info))

    unleaked_prepared: list[tuple[set[str], float]] = []
    cutoff_day = state.today - max_delay
    inv_m = 1.0 / max(1, m)
    for did, doc in state.docs.items():
        if doc["is_canary"] and did not in state.feed and doc["day"] <= cutoff_day:
            recs = doc["recipients"]
            w = (1.0 - len(recs) * inv_m) if careful else 1.0
            unleaked_prepared.append((recs, p_leak * max(0.05, w)))

    n_log_days = len(state.logged_days)
    if n_log_days > 0 and m > 0:
        reg_vals = [float(state.access_reg.get(e, 0)) for e in emps]
        ah_vals = [float(state.access_ah.get(e, 0)) for e in emps]
        reg_mean = sum(reg_vals) * inv_m
        reg_inv_std = 1.0 / (math.sqrt(sum((v - reg_mean) ** 2 for v in reg_vals) * inv_m) + 1.0)
        ah_mean = sum(ah_vals) * inv_m
        ah_inv_std = 1.0 / (math.sqrt(sum((v - ah_mean) ** 2 for v in ah_vals) * inv_m) + 1.0)
    else:
        reg_vals = []
        ah_vals = []
        reg_mean = 0.0
        reg_inv_std = 1.0
        ah_mean = 0.0
        ah_inv_std = 1.0

    angry_get = state.angry_counts.get
    ev_get = state.iv_evasive.get
    coop_get = state.iv_coop.get

    for idx, emp in enumerate(emps):
        reg_in_info = 0.0
        reg_miss = 0.0
        for recs, r_info in reg_prepared:
            if emp in recs:
                reg_in_info += r_info
            else:
                reg_miss += 1.0

        can_hit_info = 0.0
        can_hit_cnt = 0.0
        can_var_mismatch = 0.0
        can_non_rec = 0.0
        for recs, variants, shown, has_var, hit_info in can_prepared:
            if emp not in recs:
                can_non_rec += 1.0
            elif has_var:
                if variants.get(emp) == shown:
                    can_hit_info += hit_info
                    can_hit_cnt += 1.0
                else:
                    can_var_mismatch += 1.0

        unleaked_exp = 0.0
        for recs, inc in unleaked_prepared:
            if emp in recs:
                unleaked_exp += inc

        is_decoy = 1.0 if (decoy_emp is not None and emp == decoy_emp) else 0.0
        angry_cnt = angry_get(emp, 0)
        angry_raw = (3.0 if angry_cnt >= 3 else float(angry_cnt)) / 3.0
        reg_z = (reg_vals[idx] - reg_mean) * reg_inv_std if n_log_days > 0 else 0.0
        ah_z = (ah_vals[idx] - ah_mean) * ah_inv_std if n_log_days > 0 else 0.0
        iv_net = float(ev_get(emp, 0)) - 0.25 * float(coop_get(emp, 0))
        consistent_all = 1.0 if (reg_miss == 0.0 and can_non_rec == 0.0 and can_var_mismatch == 0.0) else 0.0

        feats[idx, 0] = reg_in_info
        feats[idx, 1] = reg_miss
        feats[idx, 2] = can_hit_info
        feats[idx, 3] = can_hit_cnt
        feats[idx, 4] = can_var_mismatch * exact_fp
        feats[idx, 5] = can_var_mismatch * noisy_fp
        feats[idx, 6] = can_non_rec
        feats[idx, 7] = unleaked_exp
        feats[idx, 8] = reg_z
        feats[idx, 9] = ah_z * (1.0 - is_decoy)
        feats[idx, 10] = is_decoy
        feats[idx, 11] = angry_raw * decoy_on
        feats[idx, 12] = iv_net
        feats[idx, 13] = consistent_all
    return feats


def compute_commit_features(state: PublicObsState, probs: np.ndarray, suspect_feats: np.ndarray) -> np.ndarray:
    m = max(2, len(probs))
    order = np.argsort(-probs)
    top_idx = int(order[0])
    second_idx = int(order[1]) if len(order) > 1 else top_idx
    p_top = float(probs[top_idx])
    p_sec = float(probs[second_idx]) if second_idx != top_idx else 0.0
    ent = -float(np.sum(probs * np.log(np.clip(probs, 1e-12, 1.0)))) / math.log(m)
    consistent_cnt = float(np.sum(suspect_feats[:, 13] > 0.5))
    isolated = 1.0 if (consistent_cnt == 1.0 and suspect_feats[top_idx, 13] > 0.5) else 0.0
    n_days = max(1, int(state.params["n_days"]))
    fp_noisy = 1.0 if float(state.params.get("fingerprint_accuracy", 1.0)) < 0.999 else 0.0
    z = np.zeros(D_COMMIT, dtype=np.float64)
    z[0] = 1.0
    z[1] = _logit(p_top)
    z[2] = p_top - p_sec
    z[3] = 1.0 - ent
    z[4] = min(3.0, float(suspect_feats[top_idx, 3]))
    z[5] = min(4.0, float(suspect_feats[top_idx, 2])) / 3.0
    z[6] = min(4.0, float(suspect_feats[top_idx, 0])) / 3.0
    z[7] = isolated
    z[8] = fp_noisy
    z[9] = float(state.today) / float(n_days)
    return z


def compute_wait_features(state: PublicObsState, p_commit: float, ev_now: float) -> np.ndarray:
    n_days = max(1, int(state.params["n_days"]))
    rem_frac = max(0.0, float(n_days - state.today)) / float(n_days)
    surfaced = set(state.feed.keys())
    win = int(state.params.get("leak_window_days", 3))
    pending_cans = sum(
        1 for did, doc in state.docs.items()
        if doc["is_canary"] and did not in surfaced and doc["day"] >= state.today - win
    )
    z = np.zeros(D_WAIT, dtype=np.float64)
    z[0] = 1.0
    z[1] = rem_frac
    z[2] = float(p_commit)
    z[3] = float(ev_now)
    z[4] = min(4.0, float(pending_cans)) / 4.0
    z[5] = 1.0 if float(state.params.get("fingerprint_accuracy", 1.0)) < 0.999 else 0.0
    return z


def available_tool_features(state: PublicObsState, probs: np.ndarray) -> tuple[list[int], np.ndarray]:
    m = max(2, len(probs))
    ent_norm = -float(np.sum(probs * np.log(np.clip(probs, 1e-12, 1.0)))) / math.log(m)
    p = state.params
    can_cap = int(p.get("canaries_per_day", 1))
    rem_actions = max(0, int(p.get("actions_per_day", 8)) - state.actions_used_today)
    if rem_actions <= 0:
        return [5], np.zeros((1, D_TOOL), dtype=np.float64)

    need_feed = (state.today >= 2) and (not state.feed_checked_today)
    need_decoy = (
        bool(p.get("decoy"))
        and state.today >= 2
        and inferred_decoy_id(state) is None
        and len(state.queries_done) < 3
    )
    need_logs = (state.today >= 2) and ((state.today - 1) not in state.logged_days)
    alive_cnt = int(np.sum(probs > 1e-3))
    can_plant = (state.canaries_today < can_cap) and (alive_cnt > 1) and (state.today < int(p.get("n_days", 14)))
    can_iv = len(state.interviewed_today) < len(state.employees)

    avail: list[int] = []
    rows: list[np.ndarray] = []
    flags = [need_feed, need_decoy, need_logs, can_plant, can_iv, True]
    for act_idx, ok_flag in enumerate(flags):
        if not ok_flag:
            continue
        row = np.zeros(D_TOOL, dtype=np.float64)
        row[0] = 1.0
        row[1] = ent_norm
        row[2] = 1.0 if need_feed else 0.0
        row[3] = 1.0 if need_decoy else 0.0
        row[4] = 1.0 if need_logs else 0.0
        row[5] = float(can_cap - state.canaries_today) / max(1.0, float(can_cap))
        row[6] = float(rem_actions) / max(1.0, float(p.get("actions_per_day", 8)))
        row[7] = float(state.today) / max(1.0, float(p.get("n_days", 14)))
        avail.append(act_idx)
        rows.append(row)
    return avail, np.vstack(rows)


def candidate_canary_assignments(
    state: PublicObsState,
    probs: np.ndarray,
) -> list[tuple[dict[str, str], np.ndarray]]:
    emps = state.employees
    if not emps:
        return []
    m = len(emps)
    p = state.params
    k_var = max(2, int(p.get("max_variants", 3)))
    careful = 1.0 if p.get("careful_mole") else 0.0
    win = int(p.get("leak_window_days", 3))
    surfaced = set(state.feed.keys())
    pending = [
        doc for did, doc in sorted(state.docs.items())
        if doc["is_canary"] and doc.get("variants") and did not in surfaced and doc["day"] >= state.today - win + 1
    ]
    prob_map = {emps[i]: float(probs[i]) for i in range(m)}
    elig = [e for e in emps if e not in state.restricted]
    if not elig:
        return []
    elig_sorted = sorted(elig, key=lambda e: (-prob_map[e], e))

    sig_to_cid: dict[tuple[str, ...], int] = {}
    emp_cid: dict[str, int] = {}
    old_cells: dict[int, float] = {}
    for e in emps:
        sig = tuple(doc["variants"].get(e, "-") for doc in pending)
        cid = sig_to_cid.get(sig)
        if cid is None:
            cid = len(sig_to_cid)
            sig_to_cid[sig] = cid
        emp_cid[e] = cid
        old_cells[cid] = old_cells.get(cid, 0.0) + prob_map[e]
    gini_old = 1.0 - sum(v * v for v in old_cells.values())

    coverages = (0.18, 0.30, 0.48, 0.72, 1.00)
    candidates: list[tuple[dict[str, str], np.ndarray]] = []
    seen_keys: set[tuple[tuple[str, str], ...]] = set()
    labels = CANARY_LABELS[:k_var]
    log_k = math.log(k_var)
    inv_m = 1.0 / max(1.0, float(m))

    for cov in coverages:
        cnt = max(min(len(elig_sorted), k_var), min(len(elig_sorted), int(round(cov * m))))
        chosen = elig_sorted[:cnt]
        by_cell: dict[int, list[str]] = {}
        for e in chosen:
            by_cell.setdefault(emp_cid[e], []).append(e)

        asg: dict[str, str] = {}
        label_mass = {lab: 0.0 for lab in labels}
        for _, grp in sorted(by_cell.items(), key=lambda kv: (-sum(prob_map[x] for x in kv[1]), kv[0])):
            cell_mass = {lab: 0.0 for lab in labels}
            for e in grp:
                best_lab = min(labels, key=lambda lab: (cell_mass[lab], label_mass[lab], lab))
                asg[e] = best_lab
                cell_mass[best_lab] += prob_map[e]
                label_mass[best_lab] += prob_map[e]

        key = tuple(sorted(asg.items()))
        if key in seen_keys:
            continue
        seen_keys.add(key)

        mass_cov = sum(prob_map[e] for e in asg)
        leak_factor = (1.0 - len(asg) * inv_m) if careful > 0.5 else 1.0
        eff_leak = mass_cov * max(0.05, leak_factor)

        tot_m = max(1e-12, mass_cov)
        norm_masses = [label_mass[lab] / tot_m for lab in labels if label_mass[lab] > 0.0]
        bal_ent = -sum(q * math.log(q) for q in norm_masses) / log_k

        new_cells: dict[tuple[int, str], float] = {}
        asg_get = asg.get
        for e in emps:
            nsig = (emp_cid[e], asg_get(e, "-"))
            new_cells[nsig] = new_cells.get(nsig, 0.0) + prob_map[e]
        gini_gain = max(0.0, (1.0 - sum(v * v for v in new_cells.values())) - gini_old)

        psi = np.array([mass_cov, eff_leak, bal_ent, eff_leak * gini_gain], dtype=np.float64)
        candidates.append((asg, psi))
    return candidates


@dataclass
class LinearPolicyWeights:
    w_suspect: np.ndarray
    w_commit: np.ndarray
    w_wait: np.ndarray
    w_tool: np.ndarray
    w_canary: np.ndarray
    n_train: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_train": int(self.n_train),
            "n_parameters": int(self.num_parameters()),
            "w_suspect": [round(float(x), 6) for x in self.w_suspect.tolist()],
            "w_commit": [round(float(x), 6) for x in self.w_commit.tolist()],
            "w_wait": [round(float(x), 6) for x in self.w_wait.tolist()],
            "w_tool": [[round(float(v), 6) for v in row] for row in self.w_tool.tolist()],
            "w_canary": [round(float(x), 6) for x in self.w_canary.tolist()],
        }

    def num_parameters(self) -> int:
        return int(
            self.w_suspect.size
            + self.w_commit.size
            + self.w_wait.size
            + self.w_tool.size
            + self.w_canary.size
        )


def make_prior_weights(seed: int = 20261114) -> LinearPolicyWeights:
    rng = np.random.default_rng(seed)
    w_suspect = rng.normal(0.0, 0.12, size=D_SUSPECT)
    w_commit = np.zeros(D_COMMIT, dtype=np.float64)
    w_commit[0] = 0.35
    w_commit[1] = 0.08
    w_wait = np.zeros(D_WAIT, dtype=np.float64)
    w_wait[0] = -1.6
    w_tool = rng.normal(0.0, 0.08, size=(len(TOOL_ACTIONS), D_TOOL))
    w_canary = np.array([0.10, 0.0, 0.05, 0.0], dtype=np.float64)
    return LinearPolicyWeights(
        w_suspect=w_suspect,
        w_commit=w_commit,
        w_wait=w_wait,
        w_tool=w_tool,
        w_canary=w_canary,
        n_train=0,
    )


class CompactLinearPolicy:
    """Pure-NumPy linear/logistic-softmax investigator policy (zero solver/world imports)."""

    def __init__(
        self,
        weights: LinearPolicyWeights,
        name: str | None = None,
        explore_eps: float = 0.0,
        rng_seed: int = 0,
    ) -> None:
        self.weights = weights
        self.name = name or f"tiebreak_linear_n{weights.n_train}"
        self.explore_eps = float(explore_eps)
        self.rng_seed = int(rng_seed)
        self.rng = np.random.default_rng(self.rng_seed)
        self.state = PublicObsState(params=parse_public_instruction(""))
        self.seen = 0
        self.last_commit_prob: float | None = None
        self.last_suspect_probs: dict[str, float] = {}
        self._last_step_suspect_feats: np.ndarray | None = None
        self._last_step_tool_choice: tuple[list[int], np.ndarray, int, int] | None = None
        self._last_step_canary_psi: np.ndarray | None = None

    def reset(self, tools_spec: list[dict[str, Any]], instruction: str) -> None:
        self.rng = np.random.default_rng(self.rng_seed)
        self.state = PublicObsState(params=parse_public_instruction(instruction))
        self.seen = 0
        self.last_commit_prob = None
        self.last_suspect_probs = {}
        self._last_step_suspect_feats = None
        self._last_step_tool_choice = None
        self._last_step_canary_psi = None

    def _sync(self, history: list[Any]) -> None:
        if len(history) < self.seen:
            params = dict(self.state.params)
            self.state = PublicObsState(params=params)
            self.seen = 0
        for st in history[self.seen:]:
            ingest_step_into_state(self.state, st)
        self.seen = len(history)

    def current_belief_and_commit(self) -> tuple[list[str], np.ndarray, str, float, float]:
        emps = self.state.employees or [f"e{i:02d}" for i in range(int(self.state.params["n_employees"]))]
        s_feats = compute_suspect_features(self.state)
        self._last_step_suspect_feats = s_feats
        probs = _softmax(s_feats @ self.weights.w_suspect)
        top_idx = int(np.argmax(probs))
        top_emp = emps[top_idx]
        c_feats = compute_commit_features(self.state, probs, s_feats)
        p_commit = float(_sigmoid(float(c_feats @ self.weights.w_commit)))
        v_est = expected_true_v_public(self.state)
        ws = float(self.state.params.get("wrong_accusation_score", -1.0))
        ev_now = p_commit * v_est + (1.0 - p_commit) * ws
        return emps, probs, top_emp, p_commit, ev_now

    def act(self, history: list[Any]) -> tuple[str, dict[str, Any]]:
        self._last_step_suspect_feats = None
        self._last_step_tool_choice = None
        self._last_step_canary_psi = None
        self._sync(history)
        s = self.state
        p = s.params
        cap = int(p.get("tool_call_cap", 300))
        if cap - s.total_calls <= 2:
            emps, probs, top_emp, p_commit, ev_now = self.current_belief_and_commit()
            self.last_suspect_probs = {emps[i]: float(probs[i]) for i in range(len(emps))}
            if ev_now > 0.0:
                self.last_commit_prob = p_commit
                return "accuse", {"employee": top_emp}
            return "advance_day", {}

        if not s.employees:
            return "list_employees", {}
        if not s.status_checked_today:
            return "status", {}
        if not s.docs_listed_today:
            return "list_documents", {"day_from": max(1, s.today - 3), "day_to": s.today}

        emps, probs, top_emp, p_commit, ev_now = self.current_belief_and_commit()
        self.last_suspect_probs = {emps[i]: float(probs[i]) for i in range(len(emps))}

        n_days = int(p.get("n_days", 14))
        if s.today >= 2 and s.feed_checked_today:
            if s.today >= n_days:
                if ev_now > 0.0:
                    self.last_commit_prob = p_commit
                    return "accuse", {"employee": top_emp}
            else:
                w_feats = compute_wait_features(s, p_commit, ev_now)
                req_margin = float(_sigmoid(float(w_feats @ self.weights.w_wait))) * max(0.1, expected_true_v_public(s))
                if ev_now > req_margin and p_commit >= 0.55:
                    self.last_commit_prob = p_commit
                    return "accuse", {"employee": top_emp}

        avail_idxs, tool_x = available_tool_features(s, probs)
        scores = np.array([float(tool_x[k] @ self.weights.w_tool[act_i]) for k, act_i in enumerate(avail_idxs)])
        if self.explore_eps > 0.0 and float(self.rng.random()) < self.explore_eps:
            chosen_pos = int(self.rng.integers(0, len(avail_idxs)))
        else:
            chosen_pos = int(np.argmax(scores))
        chosen_global_idx = avail_idxs[chosen_pos]
        self._last_step_tool_choice = (avail_idxs, tool_x, chosen_pos, chosen_global_idx)
        chosen_act = TOOL_ACTIONS[chosen_global_idx]

        if chosen_act == "check_leak_feed":
            return "check_leak_feed", {}
        if chosen_act == "search_messages":
            q = next((w for w in DISGRUNTLED_QUERIES if w not in s.queries_done), DISGRUNTLED_QUERIES[0])
            return "search_messages", {"query": q}
        if chosen_act == "read_access_logs":
            d_prev = max(1, s.today - 1)
            return "read_access_logs", {"day_from": d_prev, "day_to": d_prev}
        if chosen_act == "plant_canary":
            cands = candidate_canary_assignments(s, probs)
            if cands:
                if self.explore_eps > 0.0 and float(self.rng.random()) < self.explore_eps:
                    c_idx = int(self.rng.integers(0, len(cands)))
                else:
                    c_scores = np.array([float(psi @ self.weights.w_canary) for _, psi in cands])
                    c_idx = int(np.argmax(c_scores))
                asg, psi_used = cands[c_idx]
                self._last_step_canary_psi = psi_used
                suffix = f" ({s.canaries_today + 1})" if s.canaries_today > 0 else ""
                return "plant_canary", {"doc_title": f"Audit brief day {s.today}{suffix}", "assignment": asg}
        if chosen_act == "interview":
            unasked = [e for e in sorted(emps, key=lambda x: (-self.last_suspect_probs[x], x)) if e not in s.interviewed_today]
            if unasked:
                topic = INTERVIEW_TOPICS[(s.today + len(s.interviewed_today)) % len(INTERVIEW_TOPICS)]
                return "interview", {"employee": unasked[0], "topic": topic}

        if s.today >= n_days and ev_now > 0.0:
            self.last_commit_prob = p_commit
            return "accuse", {"employee": top_emp}
        return "advance_day", {}


def assert_train_seed_hygiene(seeds: Iterable[int]) -> list[int]:
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    out = [int(s) for s in seeds]
    for s in out:
        assert TRAIN_SEED_MIN <= s <= TRAIN_SEED_MAX, (
            f"seed {s} outside permitted tiebreak scaling range [{TRAIN_SEED_MIN}, {TRAIN_SEED_MAX}]"
        )
        assert s in TRAIN_SEEDS, f"seed {s} is not in canary.rules.TRAIN_SEEDS"
        assert s not in HELDOUT_SEEDS, f"seed {s} leaked into HELDOUT_SEEDS"
        assert s not in JUDGE_SEEDS, f"seed {s} leaked into JUDGE_SEEDS"
    return out


def assert_heldout_seed_hygiene(eval_seeds: Iterable[int], train_seeds_used: Iterable[int], require_heldout: bool = True) -> list[int]:
    from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS, TRAIN_SEEDS

    ev = [int(s) for s in eval_seeds]
    tr_set = {int(s) for s in train_seeds_used}
    for s in ev:
        assert s not in tr_set, f"eval seed {s} overlaps training seeds"
        assert s not in TRAIN_SEEDS, f"eval seed {s} is inside TRAIN_SEEDS"
        assert s not in JUDGE_SEEDS, f"eval seed {s} is inside JUDGE_SEEDS"
        if require_heldout:
            assert s in HELDOUT_SEEDS, f"eval seed {s} is not in HELDOUT_SEEDS"
    return ev


def select_train_seeds(n_train: int) -> dict[str, list[int]]:
    if n_train < 0 or n_train % len(TIERS) != 0:
        raise ValueError(f"n_train={n_train} must be non-negative and divisible by {len(TIERS)}")
    per_tier = n_train // len(TIERS)
    by_tier: dict[str, list[int]] = {}
    all_seeds: list[int] = []
    for tier in TIERS:
        base = TIER_TRAIN_OFFSETS[tier]
        t_seeds = list(range(base, base + per_tier))
        assert_train_seed_hygiene(t_seeds)
        by_tier[tier] = t_seeds
        all_seeds.extend(t_seeds)
    assert len(all_seeds) == n_train
    assert len(set(all_seeds)) == n_train
    return by_tier


def _fit_suspect_softmax(
    episodes_snapshots: list[list[np.ndarray]],
    mole_indices: list[int],
    w_prior: np.ndarray,
    lam: float = 8.0,
    max_iter: int = 90,
    w_init: np.ndarray | None = None,
) -> np.ndarray:
    w = (w_prior if w_init is None else w_init).astype(np.float64).copy()
    if not episodes_snapshots:
        return w

    grouped_x: dict[int, list[np.ndarray]] = {}
    grouped_y: dict[int, list[int]] = {}
    grouped_wt: dict[int, list[float]] = {}
    for snaps, target in zip(episodes_snapshots, mole_indices):
        if not snaps:
            continue
        inv_t = 1.0 / len(snaps)
        m_sz = int(snaps[0].shape[0])
        xs = grouped_x.setdefault(m_sz, [])
        ys = grouped_y.setdefault(m_sz, [])
        ws = grouped_wt.setdefault(m_sz, [])
        for x_mat in snaps:
            xs.append(x_mat)
            ys.append(int(target))
            ws.append(inv_t)

    packed: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for m_sz, xs in grouped_x.items():
        x_arr = np.stack(xs, axis=0)
        y_arr = np.array(grouped_y[m_sz], dtype=np.int64)
        wt_arr = np.array(grouped_wt[m_sz], dtype=np.float64)
        idx_arr = np.arange(len(y_arr), dtype=np.int64)
        packed.append((x_arr, y_arr, wt_arr, idx_arr))

    if not packed:
        return w

    eye_d = np.eye(len(w), dtype=np.float64)

    def obj_grad_hess(vec: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
        diff = vec - w_prior
        val = -0.5 * lam * float(diff @ diff)
        grad = -lam * diff
        hess = lam * eye_d.copy()
        for x_arr, y_arr, wt_arr, idx_arr in packed:
            logits = x_arr @ vec
            shifted = logits - np.max(logits, axis=1, keepdims=True)
            exps = np.exp(np.clip(shifted, -60.0, 60.0))
            probs = exps / np.maximum(1e-15, np.sum(exps, axis=1, keepdims=True))
            val += float(np.sum(wt_arr * np.log(np.maximum(1e-15, probs[idx_arr, y_arr]))))
            target_x = x_arr[idx_arr, y_arr]
            exp_x = np.einsum("nm,nmd->nd", probs, x_arr)
            grad = grad + np.sum(wt_arr[:, None] * (target_x - exp_x), axis=0)
            wx = probs * wt_arr[:, None]
            h_pos = np.einsum("nm,nmi,nmj->ij", wx, x_arr, x_arr)
            h_neg = (exp_x * wt_arr[:, None]).T @ exp_x
            hess = hess + (h_pos - h_neg)
        return val, grad, hess

    def obj_only(vec: np.ndarray) -> float:
        diff = vec - w_prior
        val = -0.5 * lam * float(diff @ diff)
        for x_arr, y_arr, wt_arr, idx_arr in packed:
            logits = x_arr @ vec
            shifted = logits - np.max(logits, axis=1, keepdims=True)
            exps = np.exp(np.clip(shifted, -60.0, 60.0))
            probs = exps / np.maximum(1e-15, np.sum(exps, axis=1, keepdims=True))
            val += float(np.sum(wt_arr * np.log(np.maximum(1e-15, probs[idx_arr, y_arr]))))
        return val

    for _ in range(min(max_iter, 25)):
        val, grad, hess = obj_grad_hess(w)
        gnorm = float(np.linalg.norm(grad))
        if gnorm < 1e-7:
            break
        try:
            direction = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            direction = grad / max(1.0, lam)
        slope = float(grad @ direction)
        if slope <= 0.0:
            direction = grad
            slope = gnorm * gnorm
        step = 1.0
        accepted = False
        for _ in range(16):
            cand = w + step * direction
            if obj_only(cand) >= val + 1e-4 * step * slope:
                w = cand
                accepted = True
                break
            step *= 0.5
        if not accepted or float(np.linalg.norm(step * direction)) < 1e-7:
            break
    return w


def _fit_binary_logistic(
    x_mat: np.ndarray,
    y_vec: np.ndarray,
    sample_weights: np.ndarray,
    w_prior: np.ndarray,
    lam: float = 6.0,
    max_iter: int = 35,
) -> np.ndarray:
    w = w_prior.astype(np.float64).copy()
    if x_mat.shape[0] == 0:
        return w
    for _ in range(max_iter):
        p = _sigmoid(x_mat @ w)
        grad = (x_mat.T @ (sample_weights * (y_vec - p))) - lam * (w - w_prior)
        if float(np.linalg.norm(grad)) < 1e-7:
            break
        r = sample_weights * p * (1.0 - p)
        hess = (x_mat.T * r) @ x_mat + lam * np.eye(len(w), dtype=np.float64)
        try:
            delta = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            delta = grad / (lam + 1.0)
        w = w + delta
        if float(np.linalg.norm(delta)) < 1e-7:
            break
    return w


def _fit_tool_softmax(
    samples: list[tuple[list[int], np.ndarray, int, float]],
    w_prior: np.ndarray,
    lam: float = 6.0,
    max_iter: int = 60,
) -> np.ndarray:
    w = w_prior.astype(np.float64).copy()
    if not samples:
        return w

    n_s = len(samples)
    k_actions = len(TOOL_ACTIONS)
    x_ctx = np.zeros((n_s, D_TOOL), dtype=np.float64)
    mask = np.zeros((n_s, k_actions), dtype=bool)
    y_act = np.zeros(n_s, dtype=np.int64)
    wt_arr = np.zeros(n_s, dtype=np.float64)
    idx_arr = np.arange(n_s, dtype=np.int64)

    for i, (avail_idxs, tool_x, target_pos, wt) in enumerate(samples):
        x_ctx[i] = tool_x[0]
        for a_idx in avail_idxs:
            mask[i, a_idx] = True
        y_act[i] = avail_idxs[target_pos]
        wt_arr[i] = wt

    def obj_and_grad(mat: np.ndarray) -> tuple[float, np.ndarray]:
        diff = mat - w_prior
        val = -0.5 * lam * float(np.sum(diff * diff))
        logits = x_ctx @ mat.T
        masked_logits = np.where(mask, logits, -1e9)
        shifted = masked_logits - np.max(masked_logits, axis=1, keepdims=True)
        exps = np.where(mask, np.exp(np.clip(shifted, -60.0, 60.0)), 0.0)
        probs = exps / np.maximum(1e-15, np.sum(exps, axis=1, keepdims=True))
        val += float(np.sum(wt_arr * np.log(np.maximum(1e-15, probs[idx_arr, y_act]))))
        delta_p = -probs
        delta_p[idx_arr, y_act] += 1.0
        grad = ((delta_p * wt_arr[:, None]).T @ x_ctx) - lam * diff
        return val, grad

    val, grad = obj_and_grad(w)
    step = min(0.2, 2.0 / max(1.0, float(np.sum(wt_arr)) + lam))
    for _ in range(max_iter):
        gnorm = float(np.linalg.norm(grad))
        if gnorm < 1e-6:
            break
        accepted = False
        for _ in range(16):
            cand = w + step * grad
            c_val, c_grad = obj_and_grad(cand)
            if c_val >= val + 1e-4 * step * (gnorm * gnorm):
                w, val, grad = cand, c_val, c_grad
                step = min(0.8, step * 1.25)
                accepted = True
                break
            step *= 0.5
        if not accepted:
            break
    return w


def _fit_canary_ridge(
    psi_rows: list[np.ndarray],
    gains: list[float],
    w_prior: np.ndarray,
    lam: float = 8.0,
) -> np.ndarray:
    if not psi_rows:
        return w_prior.astype(np.float64).copy()
    x_mat = np.vstack(psi_rows)
    y_vec = np.array(gains, dtype=np.float64)
    a_mat = x_mat.T @ x_mat + lam * np.eye(len(w_prior), dtype=np.float64)
    b_vec = x_mat.T @ y_vec + lam * w_prior
    try:
        return np.linalg.solve(a_mat, b_vec)
    except np.linalg.LinAlgError:
        return w_prior.astype(np.float64).copy()


@dataclass
class TrainingTrajectory:
    tier: str
    seed: int
    mole_idx: int
    day_suspect_mats: list[np.ndarray]
    day_states_meta: list[dict[str, Any]]
    tool_Choices: list[tuple[list[int], np.ndarray, int, float]]
    canary_outcomes: list[tuple[np.ndarray, float]]


def _collect_one_training_trajectory(
    tier: str,
    seed: int,
    behavior_weights: LinearPolicyWeights,
    explore_eps: float,
) -> TrainingTrajectory:
    from canary.env import Env

    assert_train_seed_hygiene([seed])
    env = Env(tier, seed)
    pol = CompactLinearPolicy(
        weights=behavior_weights,
        name="collector",
        explore_eps=explore_eps,
        rng_seed=seed,
    )
    pol.reset(env.tools_spec(), env.instruction())

    mole_id = env._world.mole
    emps = [e.id for e in env._world.employees]
    mole_idx = emps.index(mole_id)

    day_suspect_mats: list[np.ndarray] = []
    day_states_meta: list[dict[str, Any]] = []
    planted_records: list[tuple[str, np.ndarray, int]] = []
    tool_records: list[tuple[list[int], np.ndarray, int, int, float]] = []

    max_steps = env.p.tool_call_cap
    for _ in range(max_steps):
        if env.done:
            break
        tool, args = pol.act(env.history)
        s = pol.state

        if tool == "advance_day" or tool == "accuse":
            if s.employees:
                snap_mat = pol._last_step_suspect_feats
                if snap_mat is None:
                    snap_mat = compute_suspect_features(s)
                day_suspect_mats.append(snap_mat)
                win = int(s.params.get("leak_window_days", 3))
                day_states_meta.append({
                    "today": int(s.today),
                    "n_days": int(s.params["n_days"]),
                    "true_v": float(env.V),
                    "expected_v": float(expected_true_v_public(s)),
                    "wrong_score": float(s.params.get("wrong_accusation_score", -1.0)),
                    "fp_acc": float(s.params.get("fingerprint_accuracy", 1.0)),
                    "leak_window_days": win,
                    "pending_cans": sum(
                        1 for did, doc in s.docs.items()
                        if doc["is_canary"] and did not in s.feed and doc["day"] >= s.today - win
                    ),
                })

        if pol._last_step_tool_choice is not None:
            avail_idxs, tool_x, chosen_pos, chosen_global_idx = pol._last_step_tool_choice
            act_label = tool if tool in TOOL_ACTIONS else "finish_day"
            if act_label in TOOL_ACTIONS:
                act_global_idx = TOOL_ACTIONS.index(act_label)
                if act_global_idx in avail_idxs:
                    pos = chosen_pos if act_global_idx == chosen_global_idx else avail_idxs.index(act_global_idx)
                    tool_records.append((avail_idxs, tool_x, pos, act_global_idx, 0.0))
        elif s.employees and s.status_checked_today and s.docs_listed_today:
            s_mat = pol._last_step_suspect_feats
            if s_mat is not None:
                probs = _softmax(s_mat @ behavior_weights.w_suspect)
                avail_idxs, tool_x = available_tool_features(s, probs)
                act_label = tool if tool in TOOL_ACTIONS else "finish_day"
                if act_label in TOOL_ACTIONS:
                    act_global_idx = TOOL_ACTIONS.index(act_label)
                    if act_global_idx in avail_idxs:
                        pos = avail_idxs.index(act_global_idx)
                        tool_records.append((avail_idxs, tool_x, pos, act_global_idx, 0.0))

        cand_psi_used = pol._last_step_canary_psi if tool == "plant_canary" else None
        res = env.call(tool, args)
        if tool == "plant_canary" and res.ok and cand_psi_used is not None:
            cid = str((res.data or {}).get("canary_id", ""))
            if cid:
                planted_records.append((cid, cand_psi_used, int(s.today)))

    pol._sync(env.history)
    final_s = pol.state
    if not day_suspect_mats and final_s.employees:
        day_suspect_mats.append(compute_suspect_features(final_s))
        day_states_meta.append({
            "today": int(final_s.today),
            "n_days": int(final_s.params["n_days"]),
            "true_v": float(env.V),
            "expected_v": float(expected_true_v_public(final_s)),
            "wrong_score": float(final_s.params.get("wrong_accusation_score", -1.0)),
            "fp_acc": float(final_s.params.get("fingerprint_accuracy", 1.0)),
            "leak_window_days": int(final_s.params.get("leak_window_days", 3)),
            "pending_cans": 0,
        })

    canary_outcomes: list[tuple[np.ndarray, float]] = []
    for cid, psi_vec, planted_day in planted_records:
        feed_item = final_s.feed.get(cid)
        doc_info = final_s.docs.get(cid)
        if feed_item is not None and doc_info is not None:
            shown = feed_item.get("variant")
            variants = doc_info.get("variants") or {}
            grp = max(1, sum(1 for v in variants.values() if v == shown))
            gain = math.log(max(1.05, len(emps) / grp))
            canary_outcomes.append((psi_vec, gain))
        elif final_s.today - planted_day >= max(final_s.params.get("delay_choices") or (1, 2)):
            canary_outcomes.append((psi_vec, 0.0))

    emp_tool_choices: list[tuple[list[int], np.ndarray, int, float]] = []
    surfaced_any = len(final_s.feed) > 0
    decoy_found = inferred_decoy_id(final_s) is not None
    for avail_idxs, tool_x, chosen_pos, act_global_idx, _ in tool_records:
        act_scores = np.zeros(len(avail_idxs), dtype=np.float64)
        for k, a_i in enumerate(avail_idxs):
            aname = TOOL_ACTIONS[a_i]
            if aname == "check_leak_feed":
                act_scores[k] = 2.4 if surfaced_any else 1.5
            elif aname == "plant_canary":
                act_scores[k] = 2.2
            elif aname == "search_messages":
                act_scores[k] = 1.8 if decoy_found else 0.8
            elif aname == "read_access_logs":
                act_scores[k] = 1.1
            elif aname == "finish_day":
                act_scores[k] = 0.9
            elif aname == "interview":
                act_scores[k] = 0.05
        best_k = int(np.argmax(act_scores))
        wt = 1.0 / max(1, len(tool_records))
        emp_tool_choices.append((avail_idxs, tool_x, best_k, wt))
        if chosen_pos == best_k and env.score() > 0:
            emp_tool_choices.append((avail_idxs, tool_x, chosen_pos, 0.5 * wt * float(env.score())))

    return TrainingTrajectory(
        tier=tier,
        seed=seed,
        mole_idx=mole_idx,
        day_suspect_mats=day_suspect_mats,
        day_states_meta=day_states_meta,
        tool_Choices=emp_tool_choices,
        canary_outcomes=canary_outcomes,
    )


def fit_weights_from_trajectories(
    trajs: list[TrainingTrajectory],
    prior: LinearPolicyWeights,
) -> LinearPolicyWeights:
    n_train = len(trajs)
    if n_train == 0:
        return LinearPolicyWeights(
            w_suspect=prior.w_suspect.copy(),
            w_commit=prior.w_commit.copy(),
            w_wait=prior.w_wait.copy(),
            w_tool=prior.w_tool.copy(),
            w_canary=prior.w_canary.copy(),
            n_train=0,
        )

    snaps_all = [t.day_suspect_mats for t in trajs]
    moles_all = [t.mole_idx for t in trajs]
    w_suspect = _fit_suspect_softmax(snaps_all, moles_all, prior.w_suspect, lam=14.0)

    n_folds = min(5, n_train)
    oof_w_suspect: list[np.ndarray] = []
    for f in range(n_folds):
        tr_snaps = [snaps_all[i] for i in range(n_train) if i % n_folds != f]
        tr_moles = [moles_all[i] for i in range(n_train) if i % n_folds != f]
        if tr_snaps:
            oof_w_suspect.append(
                _fit_suspect_softmax(tr_snaps, tr_moles, prior.w_suspect, lam=14.0, w_init=w_suspect)
            )
        else:
            oof_w_suspect.append(w_suspect)

    commit_rows: list[np.ndarray] = []
    commit_y: list[float] = []
    commit_sw: list[float] = []
    for idx, t in enumerate(trajs):
        w_oof = oof_w_suspect[idx % n_folds]
        inv_d = 1.0 / max(1, len(t.day_suspect_mats))
        for s_mat, meta in zip(t.day_suspect_mats, t.day_states_meta):
            probs = _softmax(s_mat @ w_oof)
            top_idx = int(np.argmax(probs))
            dummy_state = PublicObsState(
                params={
                    "n_employees": s_mat.shape[0],
                    "n_days": meta["n_days"],
                    "fingerprint_accuracy": meta["fp_acc"],
                },
                today=meta["today"],
            )
            c_feat = compute_commit_features(dummy_state, probs, s_mat)
            commit_rows.append(c_feat)
            commit_y.append(1.0 if top_idx == t.mole_idx else 0.0)
            commit_sw.append(inv_d)

    x_commit = np.vstack(commit_rows) if commit_rows else np.zeros((0, D_COMMIT), dtype=np.float64)
    y_commit = np.array(commit_y, dtype=np.float64)
    sw_commit = np.array(commit_sw, dtype=np.float64)
    w_commit = _fit_binary_logistic(x_commit, y_commit, sw_commit, prior.w_commit, lam=10.0)

    wait_rows: list[np.ndarray] = []
    wait_y: list[float] = []
    wait_sw: list[float] = []
    for idx, t in enumerate(trajs):
        w_oof = oof_w_suspect[idx % n_folds]
        d_len = len(t.day_suspect_mats)
        if d_len < 2:
            continue
        day_top_ok: list[bool] = []
        day_pcoms: list[float] = []
        day_evs: list[float] = []
        for s_mat, meta in zip(t.day_suspect_mats, t.day_states_meta):
            probs = _softmax(s_mat @ w_oof)
            top_idx = int(np.argmax(probs))
            dummy_state = PublicObsState(
                params={
                    "n_employees": s_mat.shape[0],
                    "n_days": meta["n_days"],
                    "fingerprint_accuracy": meta["fp_acc"],
                },
                today=meta["today"],
            )
            c_feat = compute_commit_features(dummy_state, probs, s_mat)
            p_com = float(_sigmoid(float(c_feat @ w_commit)))
            ev_now = p_com * meta["expected_v"] + (1.0 - p_com) * meta["wrong_score"]
            day_top_ok.append(top_idx == t.mole_idx)
            day_pcoms.append(p_com)
            day_evs.append(ev_now)

        inv_d = 1.0 / max(1, d_len - 1)
        for j in range(d_len - 1):
            meta = t.day_states_meta[j]
            if meta["today"] >= meta["n_days"]:
                continue
            best_future_ev = max(0.0, max(day_evs[j + 1:]))
            should_wait = 1.0 if ((not day_top_ok[j]) or (best_future_ev > day_evs[j] + 0.015)) else 0.0
            rem_frac = max(0.0, float(meta["n_days"] - meta["today"])) / float(meta["n_days"])
            w_feat = np.array([
                1.0,
                rem_frac,
                day_pcoms[j],
                day_evs[j],
                min(4.0, float(meta["pending_cans"])) / 4.0,
                1.0 if meta["fp_acc"] < 0.999 else 0.0,
            ], dtype=np.float64)
            wait_rows.append(w_feat)
            wait_y.append(should_wait)
            wait_sw.append(inv_d)

    x_wait = np.vstack(wait_rows) if wait_rows else np.zeros((0, D_WAIT), dtype=np.float64)
    y_wait = np.array(wait_y, dtype=np.float64)
    sw_wait = np.array(wait_sw, dtype=np.float64)
    w_wait = _fit_binary_logistic(x_wait, y_wait, sw_wait, prior.w_wait, lam=8.0)

    tool_samples = [item for t in trajs for item in t.tool_Choices]
    w_tool = _fit_tool_softmax(tool_samples, prior.w_tool, lam=12.0)

    can_psis = [psi for t in trajs for psi, _ in t.canary_outcomes]
    can_gains = [g for t in trajs for _, g in t.canary_outcomes]
    w_canary = _fit_canary_ridge(can_psis, can_gains, prior.w_canary, lam=12.0)

    return LinearPolicyWeights(
        w_suspect=w_suspect,
        w_commit=w_commit,
        w_wait=w_wait,
        w_tool=w_tool,
        w_canary=w_canary,
        n_train=n_train,
    )


def train_scaling_checkpoints(
    budgets: Iterable[int] = TRAIN_BUDGETS,
    prior_seed: int = 20261114,
) -> tuple[dict[int, LinearPolicyWeights], dict[int, dict[str, list[int]]]]:
    sorted_budgets = sorted(int(b) for b in budgets)
    prior = make_prior_weights(prior_seed)
    collected_by_tier: dict[str, dict[int, TrainingTrajectory]] = {t: {} for t in TIERS}
    checkpoints: dict[int, LinearPolicyWeights] = {}
    seeds_manifest: dict[int, dict[str, list[int]]] = {}
    current_weights = prior

    for budget in sorted_budgets:
        tier_seeds = select_train_seeds(budget)
        seeds_manifest[budget] = tier_seeds
        if budget == 0:
            checkpoints[0] = fit_weights_from_trajectories([], prior)
            current_weights = checkpoints[0]
            continue

        eps_explore = 0.35 if current_weights.n_train == 0 else (0.20 if current_weights.n_train < 100 else 0.10)
        ordered_trajs: list[TrainingTrajectory] = []
        for tier in TIERS:
            for s in tier_seeds[tier]:
                if s not in collected_by_tier[tier]:
                    collected_by_tier[tier][s] = _collect_one_training_trajectory(
                        tier=tier,
                        seed=s,
                        behavior_weights=current_weights,
                        explore_eps=eps_explore,
                    )
                ordered_trajs.append(collected_by_tier[tier][s])

        assert len(ordered_trajs) == budget
        checkpoints[budget] = fit_weights_from_trajectories(ordered_trajs, prior)
        current_weights = checkpoints[budget]

    return checkpoints, seeds_manifest


def _install_world_secret(world_secret: str | bytes | None) -> tuple[Any, str | None]:
    from canary import world

    prev_set = getattr(world, "_SET_SECRET", None)
    prev_env = os.environ.get("CANARY_WORLD_SECRET")
    if world_secret is not None:
        sec_bytes = world_secret.encode("utf-8") if isinstance(world_secret, str) else bytes(world_secret)
        sec_str = world_secret if isinstance(world_secret, str) else sec_bytes.decode("utf-8", errors="replace")
        os.environ["CANARY_WORLD_SECRET"] = sec_str
        if len(sec_bytes) >= 16:
            world.set_world_secret(sec_bytes)
        else:
            world.set_world_secret(None)
    return prev_set, prev_env


def _restore_world_secret(prev_set: Any, prev_env: str | None) -> None:
    from canary import world

    world.set_world_secret(prev_set)
    if prev_env is None:
        os.environ.pop("CANARY_WORLD_SECRET", None)
    else:
        os.environ["CANARY_WORLD_SECRET"] = prev_env


def _is_client_only_step(st: dict[str, Any], env_specs: dict[str, Any]) -> bool:
    res = st.get("result")
    return (
        st.get("tool") not in env_specs
        and isinstance(res, dict)
        and res.get("ok") is False
        and isinstance(res.get("error"), str)
        and res["error"].startswith("Model tried to call unavailable tool")
    )


def _episode_to_shallow_dict(ep: Any) -> dict[str, Any]:
    return {
        "tier": ep.tier,
        "seed": ep.seed,
        "agent": ep.agent,
        "score": ep.score,
        "accused": ep.accused,
        "correct": ep.correct,
        "final_day": ep.final_day,
        "end_reason": ep.end_reason,
        "steps": [
            {"t": st.t, "day": st.day, "tool": st.tool, "args": st.args, "result": st.result}
            for st in ep.steps
        ],
        "meta": dict(ep.meta or {}),
    }


def _load_episode_dicts(episodes_source: str | Path | Iterable[Any]) -> list[dict[str, Any]]:
    if isinstance(episodes_source, (str, Path)):
        path = Path(episodes_source)
        if path.is_dir():
            path = path / "episodes.jsonl"
        rows: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                if (obj.get("meta") or {}).get("valid") is False:
                    continue
                rows.append(obj)
        return rows
    out: list[dict[str, Any]] = []
    for item in episodes_source:
        if dataclasses.is_dataclass(item):
            d = _episode_to_shallow_dict(item)
        else:
            d = dict(item)
        if (d.get("meta") or {}).get("valid") is False:
            continue
        out.append(d)
    return out


def mean_ci95(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    m = sum(xs) / n
    if n < 2:
        return m, 0.0
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    return m, 1.96 * sd / math.sqrt(n)


def compute_ece_and_brier(probs: list[float], outcomes: list[int], n_bins: int = 10) -> tuple[float | None, float | None]:
    if not probs:
        return None, None
    p_arr = np.clip(np.array(probs, dtype=np.float64), 0.0, 1.0)
    y_arr = np.array(outcomes, dtype=np.float64)
    brier = float(np.mean((p_arr - y_arr) ** 2))
    ece = 0.0
    n = len(probs)
    for b in range(n_bins):
        lo = b / n_bins
        hi = (b + 1) / n_bins
        if b == n_bins - 1:
            mask = (p_arr >= lo) & (p_arr <= hi)
        else:
            mask = (p_arr >= lo) & (p_arr < hi)
        cnt = int(np.sum(mask))
        if cnt > 0:
            ece += (cnt / n) * abs(float(np.mean(p_arr[mask])) - float(np.mean(y_arr[mask])))
    return float(ece), brier


def _summarize_classified_rows(classified_rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {cat: 0 for cat in CATEGORIES}
    for r in classified_rows:
        counts[r["category"]] += 1
    n_total = len(classified_rows)
    assert sum(counts.values()) == n_total
    rates = {cat: (counts[cat] / n_total if n_total > 0 else 0.0) for cat in CATEGORIES}

    scores = [r["score"] for r in classified_rows]
    m_score, ci_score = mean_ci95(scores)
    acc_rows = [r for r in classified_rows if r["accused"] is not None]
    solver_probs = [r["p_solver"] for r in acc_rows]
    acc_outcomes = [1 if r["correct"] else 0 for r in acc_rows]
    s_ece, s_brier = compute_ece_and_brier(solver_probs, acc_outcomes)

    model_rows = [r for r in acc_rows if r["p_model_commit"] is not None]
    if model_rows:
        m_ece, m_brier = compute_ece_and_brier(
            [float(r["p_model_commit"]) for r in model_rows],
            [1 if r["correct"] else 0 for r in model_rows],
        )
    else:
        m_ece, m_brier = s_ece, s_brier

    metrics = {
        "n": n_total,
        "mean_score": round(m_score, 6),
        "ci95": round(ci_score, 6),
        "accuracy": round(sum(1 for r in classified_rows if r["correct"]) / max(1, n_total), 6),
        "wrong_accusation_rate": round(
            sum(1 for r in classified_rows if r["accused"] is not None and not r["correct"]) / max(1, n_total),
            6,
        ),
        "abstention_rate": round(
            sum(1 for r in classified_rows if r["accused"] is None) / max(1, n_total),
            6,
        ),
        "calibrated_abstention_rate": round(counts["calibrated_abstain"] / max(1, n_total), 6),
        "commit_count": len(acc_rows),
        "ece_at_commit": round(m_ece, 6) if m_ece is not None else None,
        "brier_at_commit": round(m_brier, 6) if m_brier is not None else None,
        "solver_ece_at_commit": round(s_ece, 6) if s_ece is not None else None,
        "solver_brier_at_commit": round(s_brier, 6) if s_brier is not None else None,
        "luck_adjusted_ev": round(
            sum(r["luck_adjusted_ev"] for r in classified_rows) / max(1, n_total),
            6,
        ),
    }

    return {
        "n": n_total,
        "replay_verified": n_total,
        "all_replay_verified": True,
        "counts": counts,
        "rates": {k: round(v, 6) for k, v in rates.items()},
        "metrics": metrics,
        "episodes": classified_rows,
    }


def classify_episodes(
    episodes_path: str | Path | Iterable[Any],
    world_secret: str | bytes | None = None,
) -> dict[str, Any]:
    """Replay Canary episodes and classify each using evaluation-only SolverPolicy belief inspection."""
    from canary import rules
    from canary.env import Env, _SPECS
    from canary.solver.policy import SolverPolicy

    prev_set, prev_env = _install_world_secret(world_secret)
    try:
        raw_eps = _load_episode_dicts(episodes_path)
        counts: dict[str, int] = {cat: 0 for cat in CATEGORIES}
        classified_rows: list[dict[str, Any]] = []

        for e in raw_eps:
            tier = str(e["tier"])
            seed = int(e["seed"])
            raw_steps = list(e.get("steps") or [])
            p_ep = rules.tier_params_for_episode(tier, raw_steps)

            ver_ctx = rules.TIERS_VERSION
            if p_ep.n_employees != rules.tier_params(tier).n_employees:
                for cand_v, hist in rules.TIERS_HISTORY.items():
                    base_t = rules.TRACKS.get(tier, tier)
                    if base_t in hist and hist[base_t].n_employees == p_ep.n_employees:
                        ver_ctx = cand_v
                        break

            with rules.tiers_version(ver_ctx):
                env = Env(tier, seed)
                for st in raw_steps:
                    if _is_client_only_step(st, _SPECS):
                        continue
                    if env.done:
                        break
                    env.call(st["tool"], st.get("args") or {})

                verdict = env.verdict()
                rec_score = float(e["score"])
                rec_accused = e.get("accused")
                rec_end = str(e.get("end_reason") or "")

                if abs(env.score() - rec_score) > 1e-6 or verdict["accused"] != rec_accused:
                    raise ValueError(
                        f"replay mismatch on tier={tier} seed={seed}: "
                        f"env=({env.score()}, {verdict['accused']}) vs recorded=({rec_score}, {rec_accused})"
                    )
                if rec_end == "eval_cap":
                    if env.done:
                        raise ValueError(f"eval_cap episode unexpectedly finished in Env on tier={tier} seed={seed}")
                elif rec_end in ("accused", "horizon", "tool_cap"):
                    if not env.done or verdict["end_reason"] != rec_end:
                        raise ValueError(
                            f"end_reason mismatch on tier={tier} seed={seed}: {verdict['end_reason']} vs {rec_end}"
                        )

                replayed_steps = list(env.history)
                sp = SolverPolicy(p_ep)
                sp.instruction = env.instruction()

                acc_step_idx: int | None = None
                for i, st_obj in enumerate(replayed_steps):
                    if st_obj.tool == "accuse" and bool((st_obj.result or {}).get("ok")):
                        acc_step_idx = i
                        break

                upto = acc_step_idx if acc_step_idx is not None else len(replayed_steps)
                for st_obj in replayed_steps[:upto]:
                    sp._ingest(st_obj)
                sp.seen = upto

                if not sp.obs.employees:
                    sp.obs.employees = list(env._ids)
                post = sp.belief()
                p_top = max(post.values()) if post else (1.0 / max(1, p_ep.n_employees))
                exp_v = float(sp.expected_true_V())
                ws = float(p_ep.wrong_accusation_score)
                denom = exp_v - ws
                breakeven = (-ws) / denom if denom > 1e-9 else 1.0
                breakeven = min(1.0, max(0.0, breakeven))

                n_days = int(p_ep.n_days)
                correct = bool(verdict["correct"])
                accused = verdict["accused"]
                true_v = float(env.V)

                if rec_end in ("eval_cap", "tool_cap") or (accused is None and rec_end not in ("horizon", "accused")):
                    p_solver = float(p_top)
                    commit_day = int(e.get("final_day", env.day))
                    category = "protocol_or_cap_stall"
                    luck_adj = 0.0
                elif accused is None:
                    p_solver = float(p_top)
                    commit_day = int(e.get("final_day", env.day))
                    category = "calibrated_abstain" if p_solver < breakeven else "missed_commit_abstain"
                    luck_adj = 0.0
                else:
                    p_solver = float(post.get(accused, 0.0))
                    commit_day = int(replayed_steps[acc_step_idx].day) if acc_step_idx is not None else int(env.day)
                    luck_adj = p_solver * true_v + (1.0 - p_solver) * ws
                    if correct:
                        category = "calibrated_win" if p_solver >= breakeven else "lucky_win"
                    else:
                        if p_solver >= 0.85:
                            category = "unlucky_noise_loss"
                        elif commit_day < n_days:
                            category = "premature_gamble_loss"
                        else:
                            category = "horizon_gamble_loss"

                counts[category] += 1
                meta_dict = e.get("meta") or {}
                p_model = meta_dict.get("p_commit")
                classified_rows.append({
                    "tier": tier,
                    "seed": seed,
                    "agent": str(e.get("agent", "")),
                    "score": rec_score,
                    "accused": accused,
                    "correct": correct,
                    "mole": env._world.mole,
                    "day": commit_day,
                    "n_days": n_days,
                    "end_reason": rec_end,
                    "p_solver": round(p_solver, 6),
                    "p_top": round(float(p_top), 6),
                    "p_model_commit": round(float(p_model), 6) if p_model is not None else None,
                    "breakeven": round(breakeven, 6),
                    "expected_true_V": round(exp_v, 6),
                    "true_V": round(true_v, 6),
                    "luck_adjusted_ev": round(luck_adj, 6),
                    "category": category,
                    "replay_verified": True,
                })

        return _summarize_classified_rows(classified_rows)
    finally:
        _restore_world_secret(prev_set, prev_env)


def evaluate_policy_checkpoint(
    weights: LinearPolicyWeights,
    eval_seeds: Iterable[int],
    world_secret: str | bytes | None = DEFAULT_WORLD_SECRET,
    tiers: Iterable[str] = TIERS,
) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode

    seeds_list = [int(s) for s in eval_seeds]
    tiers_list = list(tiers)
    prev_set, prev_env = _install_world_secret(world_secret)
    try:
        ep_dicts: list[dict[str, Any]] = []
        for tier in tiers_list:
            for seed in seeds_list:
                env = Env(tier, seed)
                pol = CompactLinearPolicy(
                    weights=weights,
                    name=f"tiebreak_linear_n{weights.n_train}",
                    explore_eps=0.0,
                    rng_seed=seed,
                )
                ep = run_episode(env, pol)
                d = _episode_to_shallow_dict(ep)
                if pol.last_commit_prob is not None and ep.accused is not None:
                    d.setdefault("meta", {})["p_commit"] = float(pol.last_commit_prob)
                ep_dicts.append(d)
    finally:
        _restore_world_secret(prev_set, prev_env)

    overall = classify_episodes(ep_dicts, world_secret=world_secret)
    by_tier: dict[str, Any] = {}
    for tier in tiers_list:
        sub_cls = _summarize_classified_rows([r for r in overall["episodes"] if r["tier"] == tier])
        by_tier[tier] = {
            "metrics": sub_cls["metrics"],
            "counts": sub_cls["counts"],
            "rates": sub_cls["rates"],
        }

    return {
        "n_train": int(weights.n_train),
        "n_parameters": int(weights.num_parameters()),
        "metrics": overall["metrics"],
        "counts": overall["counts"],
        "rates": overall["rates"],
        "by_tier": by_tier,
        "replay_verified": overall["replay_verified"],
        "all_replay_verified": overall["all_replay_verified"],
        "weights": weights.to_dict(),
    }


def evaluate_solver_reference(
    eval_seeds: Iterable[int],
    world_secret: str | bytes | None = DEFAULT_WORLD_SECRET,
    tiers: Iterable[str] = TIERS,
) -> dict[str, Any]:
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    seeds_list = [int(s) for s in eval_seeds]
    tiers_list = list(tiers)
    prev_set, prev_env = _install_world_secret(world_secret)
    try:
        ep_dicts: list[dict[str, Any]] = []
        for tier in tiers_list:
            for seed in seeds_list:
                env = Env(tier, seed)
                sp = SolverPolicy()
                ep = run_episode(env, sp)
                d = _episode_to_shallow_dict(ep)
                ep_dicts.append(d)
    finally:
        _restore_world_secret(prev_set, prev_env)

    overall = classify_episodes(ep_dicts, world_secret=world_secret)
    by_tier: dict[str, Any] = {}
    for tier in tiers_list:
        sub_cls = _summarize_classified_rows([r for r in overall["episodes"] if r["tier"] == tier])
        by_tier[tier] = {
            "metrics": sub_cls["metrics"],
            "counts": sub_cls["counts"],
            "rates": sub_cls["rates"],
        }
    return {
        "agent": "solver",
        "metrics": overall["metrics"],
        "counts": overall["counts"],
        "rates": overall["rates"],
        "by_tier": by_tier,
        "replay_verified": overall["replay_verified"],
        "all_replay_verified": overall["all_replay_verified"],
    }


def classify_committed_v14_runs(root: Path = ROOT) -> list[dict[str, Any]]:
    v14_dir = root / "data" / "runs" / "committed" / "v1.4"
    targets: list[tuple[str, str, list[Path]]] = [
        ("opencode-gemini-4-carbon", "hard", [v14_dir / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"]),
        ("opencode-gemini-4-carbon", "medium", [v14_dir / "opencode-gemini-4-carbon" / "medium" / "episodes.jsonl"]),
        ("inproc-gemini-4-carbon", "hard", [v14_dir / "inproc-gemini-4-carbon" / "hard" / "episodes.jsonl"]),
        ("inproc-gemini-4-carbon", "medium", [v14_dir / "inproc-gemini-4-carbon" / "medium" / "episodes.jsonl"]),
        (
            "solver",
            "hard",
            [
                v14_dir / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl",
                v14_dir / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl",
            ],
        ),
        (
            "solver",
            "medium",
            [
                v14_dir / "reference" / "solver-medium-20261114-121126" / "episodes.jsonl",
                v14_dir / "reference" / "solver-medium-seeds20to29" / "episodes.jsonl",
            ],
        ),
        ("heuristic", "hard", [v14_dir / "reference" / "heuristic-hard-20261114-121126" / "episodes.jsonl"]),
        ("heuristic", "medium", [v14_dir / "reference" / "heuristic-medium-20261114-121126" / "episodes.jsonl"]),
    ]
    rows: list[dict[str, Any]] = []
    for label, tier, paths in targets:
        if not all(p.exists() for p in paths):
            continue
        merged: list[dict[str, Any]] = []
        for p in paths:
            merged.extend(_load_episode_dicts(p))
        cls = classify_episodes(merged, world_secret=None)
        rows.append({
            "agent": label,
            "tier": tier,
            "n": cls["n"],
            "replay_verified": cls["replay_verified"],
            "metrics": cls["metrics"],
            "counts": cls["counts"],
            "rates": cls["rates"],
        })
    return rows


def run_scaling_experiment(
    budgets: Iterable[int] = TRAIN_BUDGETS,
    eval_seeds: Iterable[int] = HELDOUT_EVAL_SEEDS,
    world_secret: str = DEFAULT_WORLD_SECRET,
    require_heldout: bool = True,
    include_cross_model: bool = True,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    budgets_list = [int(b) for b in budgets]
    eval_seeds_list = [int(s) for s in eval_seeds]

    checkpoints, seeds_manifest = train_scaling_checkpoints(budgets=budgets_list)
    all_train_seeds = [
        s
        for b_map in seeds_manifest.values()
        for t_seeds in b_map.values()
        for s in t_seeds
    ]
    assert_train_seed_hygiene(all_train_seeds)
    assert_heldout_seed_hygiene(eval_seeds_list, all_train_seeds, require_heldout=require_heldout)

    curve: list[dict[str, Any]] = []
    for b in budgets_list:
        res_b = evaluate_policy_checkpoint(
            weights=checkpoints[b],
            eval_seeds=eval_seeds_list,
            world_secret=world_secret if require_heldout else None,
            tiers=TIERS,
        )
        curve.append(res_b)

    solver_ref = evaluate_solver_reference(
        eval_seeds=eval_seeds_list,
        world_secret=world_secret if require_heldout else None,
        tiers=TIERS,
    )

    cross_model = classify_committed_v14_runs(ROOT) if include_cross_model else []
    sec_fp = hashlib.sha256(world_secret.encode("utf-8")).hexdigest()[:12] if require_heldout else "public"

    scores_by_b = [row["metrics"]["mean_score"] for row in curve]
    la_by_b = [row["metrics"]["luck_adjusted_ev"] for row in curve]

    return {
        "schema": "canary.tiebreak.scaling_calibration.v1",
        "tiers_version": "v1.4",
        "tiers": list(TIERS),
        "train_budgets": budgets_list,
        "train_seed_range": [TRAIN_SEED_MIN, TRAIN_SEED_MAX],
        "train_seeds_unique_count": len(set(all_train_seeds)),
        "eval_seeds": [eval_seeds_list[0], eval_seeds_list[-1]],
        "eval_seeds_per_tier": len(eval_seeds_list),
        "eval_episodes_per_budget": len(eval_seeds_list) * len(TIERS),
        "world_secret_sha256_12": sec_fp,
        "policy_architecture": {
            "type": "compact_linear_logistic_softmax",
            "pure_numpy": True,
            "zero_solver_or_world_imports_at_inference": True,
            "n_parameters": curve[0]["n_parameters"] if curve else 0,
        },
        "monotonic_mean_score": all(
            scores_by_b[i] <= scores_by_b[i + 1] + 1e-9 for i in range(len(scores_by_b) - 1)
        ),
        "monotonic_luck_adjusted_ev": all(
            la_by_b[i] <= la_by_b[i + 1] + 1e-9 for i in range(len(la_by_b) - 1)
        ),
        "delta_n0_to_max": {
            "score_gain": round(scores_by_b[-1] - scores_by_b[0], 6) if len(scores_by_b) >= 2 else 0.0,
            "luck_adjusted_gain": round(la_by_b[-1] - la_by_b[0], 6) if len(la_by_b) >= 2 else 0.0,
            "accuracy_gain": round(
                curve[-1]["metrics"]["accuracy"] - curve[0]["metrics"]["accuracy"], 6
            ) if len(curve) >= 2 else 0.0,
        },
        "scaling_curve": curve,
        "solver_reference": solver_ref,
        "categories": list(CATEGORIES),
        "cross_model_v14": cross_model,
        "runtime_seconds": round(time.perf_counter() - t0, 2),
    }


def _fmt_num(val: float | None, digits: int = 3, signed: bool = False) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "n/a"
    return f"{val:+.{digits}f}" if signed else f"{val:.{digits}f}"


def render_markdown_report(summary: dict[str, Any]) -> str:
    h1 = chr(35)
    h2 = chr(35) * 2
    seed_pool_label = "DEV_SEEDS" if summary["world_secret_sha256_12"] == "public" else "HELDOUT_SEEDS"
    lines: list[str] = [
        f"{h1} Tiebreak Experience Sample-Efficiency Scaling Law & Calibration Taxonomy",
        "",
        f"- Rules version: `{summary['tiers_version']}` (`easy`, `medium`, `hard`)",
        f"- Training seeds: strictly from `TRAIN_SEEDS` (`{summary['train_seed_range'][0]}..{summary['train_seed_range'][1]}`), asserted disjoint from held-out and judge seeds",
        f"- Held-out evaluation: paired `{seed_pool_label}` `{summary['eval_seeds'][0]}..{summary['eval_seeds'][1]}` (`n={summary['eval_seeds_per_tier']}/tier` = `{summary['eval_episodes_per_budget']}` episodes/budget, secret sha256 prefix `{summary['world_secret_sha256_12']}`)",
        f"- Policy: pure-NumPy linear/logistic-softmax investigator (`{summary['policy_architecture']['n_parameters']}` parameters, zero solver/world imports at inference, 100% replay-verified)",
        "",
        f"{h2} Part A: Experience Sample-Efficiency Curve (All Tiers Pooled, n={summary['eval_episodes_per_budget']}/budget)",
        "",
        "| N_train | n_eval | score +/- 95% CI | luck-adj EV | accuracy | wrong-acc rate | cal-abstain rate | ECE @ commit | Brier @ commit | % of solver | replay ok |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    sol_m = summary["solver_reference"]["metrics"]
    sol_score = max(1e-9, float(sol_m["mean_score"]))

    for row in summary["scaling_curve"]:
        m = row["metrics"]
        pct_sol = 100.0 * float(m["mean_score"]) / sol_score
        lines.append(
            f"| {row['n_train']} | {m['n']} | {_fmt_num(m['mean_score'], 3, True)} +/- {_fmt_num(m['ci95'], 3)} | "
            f"{_fmt_num(m['luck_adjusted_ev'], 3, True)} | {_fmt_num(m['accuracy'], 3)} | "
            f"{_fmt_num(m['wrong_accusation_rate'], 3)} | {_fmt_num(m['calibrated_abstention_rate'], 3)} | "
            f"{_fmt_num(m['ece_at_commit'], 3)} | {_fmt_num(m['brier_at_commit'], 3)} | "
            f"{pct_sol:.1f}% | {row['replay_verified']}/{m['n']} |"
        )

    lines.append(
        f"| solver (ref) | {sol_m['n']} | {_fmt_num(sol_m['mean_score'], 3, True)} +/- {_fmt_num(sol_m['ci95'], 3)} | "
        f"{_fmt_num(sol_m['luck_adjusted_ev'], 3, True)} | {_fmt_num(sol_m['accuracy'], 3)} | "
        f"{_fmt_num(sol_m['wrong_accusation_rate'], 3)} | {_fmt_num(sol_m['calibrated_abstention_rate'], 3)} | "
        f"{_fmt_num(sol_m['ece_at_commit'], 3)} | {_fmt_num(sol_m['brier_at_commit'], 3)} | "
        f"100.0% | {summary['solver_reference']['replay_verified']}/{sol_m['n']} |"
    )

    lines += [
        "",
        f"{h2} Part A Per-Tier Breakdown (n={summary['eval_seeds_per_tier']}/tier per budget)",
        "",
        "| N_train | easy score +/- CI | medium score +/- CI | hard score +/- CI | easy acc | medium acc | hard acc | hard luck-adj EV |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["scaling_curve"]:
        bt = row["by_tier"]
        e_m, m_m, h_m = bt["easy"]["metrics"], bt["medium"]["metrics"], bt["hard"]["metrics"]
        lines.append(
            f"| {row['n_train']} | {_fmt_num(e_m['mean_score'], 3, True)} +/- {_fmt_num(e_m['ci95'], 3)} | "
            f"{_fmt_num(m_m['mean_score'], 3, True)} +/- {_fmt_num(m_m['ci95'], 3)} | "
            f"{_fmt_num(h_m['mean_score'], 3, True)} +/- {_fmt_num(h_m['ci95'], 3)} | "
            f"{_fmt_num(e_m['accuracy'], 2)} | {_fmt_num(m_m['accuracy'], 2)} | {_fmt_num(h_m['accuracy'], 2)} | "
            f"{_fmt_num(h_m['luck_adjusted_ev'], 3, True)} |"
        )
    s_bt = summary["solver_reference"]["by_tier"]
    lines.append(
        f"| solver (ref) | {_fmt_num(s_bt['easy']['metrics']['mean_score'], 3, True)} +/- {_fmt_num(s_bt['easy']['metrics']['ci95'], 3)} | "
        f"{_fmt_num(s_bt['medium']['metrics']['mean_score'], 3, True)} +/- {_fmt_num(s_bt['medium']['metrics']['ci95'], 3)} | "
        f"{_fmt_num(s_bt['hard']['metrics']['mean_score'], 3, True)} +/- {_fmt_num(s_bt['hard']['metrics']['ci95'], 3)} | "
        f"{_fmt_num(s_bt['easy']['metrics']['accuracy'], 2)} | {_fmt_num(s_bt['medium']['metrics']['accuracy'], 2)} | "
        f"{_fmt_num(s_bt['hard']['metrics']['accuracy'], 2)} | {_fmt_num(s_bt['hard']['metrics']['luck_adjusted_ev'], 3, True)} |"
    )

    lines += [
        "",
        f"{h2} Part B: Scaling Checkpoints Episode Outcome & Calibration Taxonomy (Counts out of {summary['eval_episodes_per_budget']})",
        "",
        "| N_train | cal_win | lucky_win | unlucky_noise_loss | premature_gamble | horizon_gamble | cal_abstain | missed_commit | cap_stall |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["scaling_curve"]:
        c = row["counts"]
        lines.append(
            f"| {row['n_train']} | {c['calibrated_win']} | {c['lucky_win']} | {c['unlucky_noise_loss']} | "
            f"{c['premature_gamble_loss']} | {c['horizon_gamble_loss']} | {c['calibrated_abstain']} | "
            f"{c['missed_commit_abstain']} | {c['protocol_or_cap_stall']} |"
        )
    sc = summary["solver_reference"]["counts"]
    lines.append(
        f"| solver (ref) | {sc['calibrated_win']} | {sc['lucky_win']} | {sc['unlucky_noise_loss']} | "
        f"{sc['premature_gamble_loss']} | {sc['horizon_gamble_loss']} | {sc['calibrated_abstain']} | "
        f"{sc['missed_commit_abstain']} | {sc['protocol_or_cap_stall']} |"
    )

    if summary.get("cross_model_v14"):
        lines += [
            "",
            f"{h2} Part B: Cross-Model Committed v1.4 Failure-Mode & Calibration Classification",
            "",
            "| agent | tier | n | score +/- CI | luck-adj EV | cal_win | lucky_win | unlucky_noise | premature_gamble | horizon_gamble | cal_abstain | missed_commit | cap_stall |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for row in summary["cross_model_v14"]:
            m = row["metrics"]
            c = row["counts"]
            lines.append(
                f"| {row['agent']} | {row['tier']} | {row['n']} | "
                f"{_fmt_num(m['mean_score'], 3, True)} +/- {_fmt_num(m['ci95'], 3)} | "
                f"{_fmt_num(m['luck_adjusted_ev'], 3, True)} | {c['calibrated_win']} | {c['lucky_win']} | "
                f"{c['unlucky_noise_loss']} | {c['premature_gamble_loss']} | {c['horizon_gamble_loss']} | "
                f"{c['calibrated_abstain']} | {c['missed_commit_abstain']} | {c['protocol_or_cap_stall']} |"
            )

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Tiebreak scaling law and episode calibration classifier")
    ap.add_argument("--out-json", type=Path, default=SUMMARY_JSON_DEFAULT)
    ap.add_argument("--out-md", type=Path, default=TABLE_MD_DEFAULT)
    ap.add_argument("--world-secret", type=str, default=DEFAULT_WORLD_SECRET)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--dev-smoke", action="store_true", help="Run on DEV_SEEDS 500..529 without touching HELDOUT_SEEDS")
    ap.add_argument("--classify", type=Path, default=None, help="Classify a single episodes.jsonl file and print JSON")
    args = ap.parse_args(argv)

    if args.workers != 1:
        raise ValueError("Memory hygiene rule requires --workers 1")

    if args.classify is not None:
        secret = args.world_secret if args.world_secret else None
        out = classify_episodes(args.classify, world_secret=secret)
        print(json.dumps({k: v for k, v in out.items() if k != "episodes"}, indent=2, sort_keys=True))
        return 0

    if args.dev_smoke:
        summary = run_scaling_experiment(
            budgets=TRAIN_BUDGETS,
            eval_seeds=range(500, 530),
            world_secret="",
            require_heldout=False,
            include_cross_model=True,
        )
        print(render_markdown_report(summary))
        print(f"dev_smoke runtime_seconds={summary['runtime_seconds']}")
        return 0

    summary = run_scaling_experiment(
        budgets=TRAIN_BUDGETS,
        eval_seeds=HELDOUT_EVAL_SEEDS,
        world_secret=args.world_secret,
        require_heldout=True,
        include_cross_model=True,
    )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown_report(summary), encoding="utf-8")
    print(f"wrote {args.out_json}")
    print(f"wrote {args.out_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
