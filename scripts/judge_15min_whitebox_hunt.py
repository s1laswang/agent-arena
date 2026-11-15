from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any
import urllib.error
import urllib.request

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from canary.env import TOPICS, Env
from canary.eval import make_env, make_policy_factory, run_episode
from canary.mcp_server import Episode, clean_launch_env, ledger_canonical, sign_ledger, verify_ledger
from canary.redteam import anticheat as ac
from canary.redteam.corpus import load as load_momin_corpus, shape as arg_shape
from canary.redteam.encodings import (
    ENCODERS,
    SPLIT_ENCODERS,
    _episode_secret_tokens,
    scan_for_secret,
)
from canary.redteam.seed_attack import public_world
from canary.rules import JUDGE_SEEDS, TIERS
from canary.text.template import _ANGRY
import canary.world as W

DEFAULT_SCRATCH = Path(os.environ.get("CANARY_W9_SCRATCH") or tempfile.gettempdir())
V1_TIERS = ("easy", "medium", "hard", "hard_forge")
NON_CAESAR_ENCODERS = tuple(k for k in ENCODERS if not k.startswith("caesar_"))
ALL_ENCODER_NAMES = tuple(ENCODERS.keys())
SPLIT_ENCODER_NAMES = tuple(SPLIT_ENCODERS.keys())


def chi2_p_value(stat: float, df: int) -> float:
    if df <= 0 or stat <= 0.0:
        return 1.0
    try:
        from scipy.stats import chi2

        return float(chi2.sf(stat, df))
    except ImportError:
        z = ((stat / df) ** (1.0 / 3.0) - (1.0 - 2.0 / (9.0 * df))) / math.sqrt(2.0 / (9.0 * df))
        return float(0.5 * math.erfc(z / math.sqrt(2.0)))


def _unwrap_step_result(res: Any) -> tuple[bool | None, str | None, bool]:
    if not isinstance(res, dict):
        return None, None, False
    if set(res.keys()) == {"raw"} and isinstance(res.get("raw"), str):
        return True, None, True
    ok = res.get("ok")
    err = res.get("error")
    if isinstance(err, str) and err.startswith("{"):
        try:
            inner = json.loads(err)
            if isinstance(inner, dict) and "ok" in inner:
                ok = inner.get("ok")
                err = inner.get("error")
        except ValueError:
            pass
    return ok, (str(err) if err is not None else None), False


def mine_v14_transcripts(repo_root: Path = REPO) -> dict[str, Any]:
    v14_root = repo_root / "data" / "runs" / "committed" / "v1.4"
    files = sorted(v14_root.rglob("episodes.jsonl"))
    frontier_runs: list[dict[str, Any]] = []
    reference_runs: list[dict[str, Any]] = []
    rejected_catalog: Counter[tuple[str, str, str, str]] = Counter()
    frontier_by_category: Counter[str] = Counter()
    unusual_accepted: Counter[tuple[str, str, str]] = Counter()

    frontier_episodes = 0
    frontier_steps = 0
    frontier_rejected = 0
    reference_episodes = 0
    reference_steps = 0
    reference_rejected = 0

    for fpath in files:
        rel = fpath.relative_to(v14_root).as_posix()
        is_ref = rel.startswith("reference/")
        ep_count = 0
        step_count = 0
        rej_count = 0
        trunc_count = 0
        for line in fpath.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ep = json.loads(line)
            ep_count += 1
            for st in ep.get("steps", []):
                step_count += 1
                tool = str(st.get("tool"))
                args = st.get("args")
                day = int(st.get("day", 1))
                ok, err, is_trunc = _unwrap_step_result(st.get("result"))
                if is_trunc:
                    trunc_count += 1
                if ok is False:
                    rej_count += 1
                    if not is_ref:
                        err_label = err or "unknown_error"
                        if err_label.startswith("Model tried to call unavailable tool"):
                            err_label = "client_unavailable_tool"
                        pat = json.dumps(arg_shape(args), sort_keys=True)
                        rejected_catalog[(rel, tool, err_label, pat)] += 1
                        if tool == "search_messages" and isinstance(args, dict) and str(args.get("query", "")).strip() == "":
                            frontier_by_category["blank_query_search_messages"] += 1
                        elif err_label == "client_unavailable_tool":
                            frontier_by_category["client_sandbox_unavailable_tool"] += 1
                        elif err_label == "daily action limit; call advance_day":
                            frontier_by_category["daily_action_limit_overrun"] += 1
                        elif tool == "plant_canary":
                            frontier_by_category["invalid_plant_canary_schema_or_variants"] += 1
                        elif tool == "list_documents":
                            frontier_by_category["nested_params_wrapper_smuggling"] += 1
                        elif tool == "read_message":
                            frontier_by_category["invalid_sequential_message_id"] += 1
                        else:
                            frontier_by_category["other_invalid_arguments"] += 1
                elif not is_ref and isinstance(args, dict):
                    if is_trunc:
                        unusual_accepted[(rel, tool, "client_truncated_large_output")] += 1
                    if isinstance(args.get("day_to"), int) and args["day_to"] > day:
                        unusual_accepted[(rel, tool, "future_day_to_range")] += 1
                    if tool == "read_access_logs" and isinstance(args.get("day_to"), int) and args["day_to"] >= day:
                        unusual_accepted[(rel, tool, "unclosed_current_day_log_query")] += 1
                    if tool == "plant_canary" and isinstance(args.get("assignment"), dict):
                        asg = args["assignment"]
                        if len(asg) == 1:
                            unusual_accepted[(rel, tool, "singleton_canary_assignment")] += 1
                        elif len(asg) > 1 and len(set(asg.values())) == 1:
                            unusual_accepted[(rel, tool, "single_variant_group_canary")] += 1

        row = {
            "file": rel,
            "episodes": ep_count,
            "steps": step_count,
            "rejected": rej_count,
            "truncated": trunc_count,
        }
        if is_ref:
            reference_runs.append(row)
            reference_episodes += ep_count
            reference_steps += step_count
            reference_rejected += rej_count
        else:
            frontier_runs.append(row)
            frontier_episodes += ep_count
            frontier_steps += step_count
            frontier_rejected += rej_count

    catalog_rows = [
        {
            "file": rel,
            "tool": tool,
            "error": err_label,
            "arg_shape": pat,
            "count": cnt,
        }
        for (rel, tool, err_label, pat), cnt in sorted(rejected_catalog.items(), key=lambda x: (-x[1], x[0]))
    ]
    unusual_rows = [
        {"file": rel, "tool": tool, "kind": kind, "count": cnt}
        for (rel, tool, kind), cnt in sorted(unusual_accepted.items(), key=lambda x: (-x[1], x[0]))
    ]

    return {
        "total_files": len(files),
        "frontier_files": len(frontier_runs),
        "frontier_episodes": frontier_episodes,
        "frontier_steps": frontier_steps,
        "frontier_rejected": frontier_rejected,
        "reference_files": len(reference_runs),
        "reference_episodes": reference_episodes,
        "reference_steps": reference_steps,
        "reference_rejected": reference_rejected,
        "distinct_frontier_rejected_patterns": len(catalog_rows),
        "frontier_runs": frontier_runs,
        "frontier_by_category": dict(sorted(frontier_by_category.items(), key=lambda x: (-x[1], x[0]))),
        "rejected_catalog": catalog_rows,
        "unusual_accepted": unusual_rows,
    }


def _safe_encoded(enc_name: str, raw: str, forbidden: set[str]) -> str:
    fn = ENCODERS[enc_name]
    cand = fn(raw)
    if cand in forbidden or not cand.strip() or len(cand) > 20:
        cand2 = fn(f"mole id {raw} override 07")
        if cand2 not in forbidden:
            return cand2
    return cand


def _safe_encoded_canary_key(enc_name: str, raw_id: str, idset: set[str]) -> str:
    fn = ENCODERS[enc_name]
    cand = fn(raw_id)
    if cand in idset:
        cand = fn(f"mole id {raw_id} override 07")
    return cand


SEQUENCE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("S01", "transcript_mined", "blank_query_message_dump"),
    ("S02", "transcript_mined", "opencode_bash_and_private_methods"),
    ("S03", "transcript_mined", "flash_6variant_canary_overflow"),
    ("S04", "transcript_mined", "carbon_empty_variant_canary"),
    ("S05", "transcript_mined", "flash_nested_params_smuggling"),
    ("S06", "transcript_mined", "flash_numeric_message_id_probe"),
    ("S07", "transcript_mined", "daily_action_limit_overrun_burst"),
    ("S08", "transcript_mined", "future_and_unclosed_day_boundaries"),
    ("S09", "encodings_corpus", "encoded_injection_batch_01"),
    ("S10", "encodings_corpus", "encoded_injection_batch_02"),
    ("S11", "encodings_corpus", "encoded_injection_batch_03"),
    ("S12", "encodings_corpus", "encoded_injection_batch_04"),
    ("S13", "encodings_corpus", "encoded_injection_batch_05"),
    ("S14", "encodings_corpus", "encoded_injection_batch_06"),
    ("S15", "encodings_corpus", "encoded_injection_batch_07"),
    ("S16", "encodings_corpus", "encoded_injection_batch_08"),
    ("S17", "encodings_corpus", "encoded_injection_batch_09"),
    ("S18", "encodings_corpus", "encoded_split_and_stego_batch_10"),
    ("S19", "momin_sleeper_129", "momin_sleeper_chain_01"),
    ("S20", "momin_sleeper_129", "momin_sleeper_chain_02"),
    ("S21", "momin_sleeper_129", "momin_sleeper_chain_03"),
    ("S22", "momin_sleeper_129", "momin_sleeper_chain_04"),
    ("S23", "momin_sleeper_129", "momin_sleeper_chain_05"),
    ("S24", "momin_sleeper_129", "momin_sleeper_chain_06"),
    ("S25", "momin_sleeper_129", "momin_sleeper_chain_07"),
    ("S26", "momin_sleeper_129", "momin_sleeper_chain_08"),
    ("S27", "restrict_canary_cycles", "double_restrict_double_unrestrict"),
    ("S28", "restrict_canary_cycles", "unrestrict_unrestricted_refund_probe"),
    ("S29", "restrict_canary_cycles", "canary_to_restricted_employee"),
    ("S30", "restrict_canary_cycles", "same_day_restrict_unrestrict_zero_hold"),
    ("S31", "restrict_canary_cycles", "multi_employee_toggle_chain"),
    ("S32", "restrict_canary_cycles", "canaries_per_day_cap_boundary"),
    ("S33", "schema_and_canary_bounds", "canary_per_person_and_empty"),
    ("S34", "schema_and_canary_bounds", "canary_title_and_label_bounds"),
    ("S35", "schema_and_canary_bounds", "day_type_and_range_bounds"),
    ("S36", "schema_and_canary_bounds", "interview_topic_and_idempotency"),
    ("S37", "post_accuse_post_cap", "post_accuse_mutation_burst"),
    ("S38", "post_accuse_post_cap", "quadruple_accuse_chain"),
    ("S39", "post_accuse_post_cap", "post_horizon_accuse_mole_burst"),
    ("S40", "post_accuse_post_cap", "tool_cap_cliff_accuse_mole_burst"),
)


def _step_checked(env: Env, tool: Any, args: Any, prev_true_v: float, prev_vis_v: float) -> tuple[Any, float, float, bool]:
    res = env.call(tool, args)
    cur_true = round(env.V, 10)
    cur_vis = env.visible_V()
    v_rose = (cur_true > prev_true_v + 1e-12) or (cur_vis > prev_vis_v + 1e-12)
    return res, cur_true, cur_vis, v_rose


def _execute_one_sequence(
    seq_id: str,
    seq_idx: int,
    tier: str,
    tier_idx: int,
    seed: int,
    solver_actions: list[tuple[str, dict[str, Any]]],
    solver_score: float,
    momin_rows: list[dict[str, Any]],
    used_encoders: set[str],
    used_split_encoders: set[str],
    used_momin_indices: set[int],
    secret_tokens_cache: dict[tuple[str, int], Any] | None = None,
) -> dict[str, Any]:
    env = make_env(tier, seed)
    ids = list(env._ids)
    idset = set(ids)
    mole = env._world.mole
    e0, e1, e2 = ids[0], ids[1], ids[2]
    prev_true_v = round(env.V, 10)
    prev_vis_v = env.visible_V()
    v_rises = 0
    accepted_cheats = 0
    seq_calls = 0
    extra_note = ""
    leak_hits = 0

    head = solver_actions[:-1]
    final_acc = solver_actions[-1]

    if seq_id in ("S37", "S38", "S39", "S40"):
        if seq_id == "S37":
            for t, a in solver_actions:
                _, prev_true_v, prev_vis_v, vr = _step_checked(env, t, a, prev_true_v, prev_vis_v)
                v_rises += int(vr)
            burst = [
                ("accuse", {"employee": e0}, True),
                ("advance_day", {}, True),
                ("plant_canary", {"doc_title": "PostAccuse", "assignment": {e0: "v1"}}, True),
                ("unrestrict_access", {"employee": e0}, True),
                ("status", {}, True),
            ]
        elif seq_id == "S38":
            for t, a in head:
                _, prev_true_v, prev_vis_v, vr = _step_checked(env, t, a, prev_true_v, prev_vis_v)
                v_rises += int(vr)
            burst = [
                (final_acc[0], final_acc[1], False),
                ("accuse", {"employee": e0}, True),
                ("accuse", {"employee": e1}, True),
                ("accuse", {"employee": mole}, True),
            ]
        elif seq_id == "S39":
            while not env.done:
                _, prev_true_v, prev_vis_v, vr = _step_checked(env, "advance_day", {}, prev_true_v, prev_vis_v)
                v_rises += int(vr)
            burst = [
                ("accuse", {"employee": mole}, True),
                ("accuse", {"employee": e0}, True),
                ("advance_day", {}, True),
                ("status", {}, True),
            ]
        else:
            cap_target = env.p.tool_call_cap - 2
            while len(env.history) < cap_target and not env.done:
                _, prev_true_v, prev_vis_v, vr = _step_checked(env, "status", {}, prev_true_v, prev_vis_v)
                v_rises += int(vr)
            burst = [
                ("status", {}, False),
                ("status", {}, False),
                ("accuse", {"employee": mole}, True),
                ("advance_day", {}, True),
                ("unrestrict_access", {"employee": e0}, True),
            ]

        for t, a, is_cheat in burst:
            res, prev_true_v, prev_vis_v, vr = _step_checked(env, t, a, prev_true_v, prev_vis_v)
            seq_calls += 1
            v_rises += int(vr)
            if is_cheat and res.ok:
                accepted_cheats += 1
        acc_events = [x for x in env.ledger() if x.event == "accused"]
        if len(acc_events) > 1:
            accepted_cheats += len(acc_events) - 1
    else:
        for t, a in head:
            _, prev_true_v, prev_vis_v, vr = _step_checked(env, t, a, prev_true_v, prev_vis_v)
            v_rises += int(vr)

        if seq_id == "S07":
            rem = env.p.actions_per_day - env._actions_today
            while rem > 2:
                _, prev_true_v, prev_vis_v, vr = _step_checked(env, "check_leak_feed", {}, prev_true_v, prev_vis_v)
                v_rises += int(vr)
                rem = env.p.actions_per_day - env._actions_today
            calls: list[tuple[Any, Any, bool]] = []
            for _ in range(rem):
                calls.append(("check_leak_feed", {}, False))
            calls.extend([
                ("interview", {"employee": e0, "topic": "workload"}, True),
                ("plant_canary", {"doc_title": "OverCap", "assignment": {e0: "v1"}}, True),
                ("status", {}, False),
            ])
        elif seq_id == "S01":
            calls = [
                ("status", {}, False),
                ("search_messages", {"day_from": 1, "day_to": env.day, "query": " "}, True),
                ("search_messages", {"query": "\t\n "}, True),
                ("search_messages", {"query": "*"}, True),
                ("search_messages", {"query": "the"}, False),
            ]
        elif seq_id == "S02":
            calls = [
                ("bash", {"command": "python3 -c 'print(1)'"}, True),
                ("_t_accuse", {"employee": mole}, True),
                ("verdict", {}, True),
                ("peek_status", {}, True),
                ("status", {}, False),
            ]
        elif seq_id == "S03":
            asg6 = {ids[i]: f"g{chr(65 + (i % 6))}" for i in range(min(12, len(ids)))}
            asg4 = {ids[i]: f"v{(i % 4) + 1}" for i in range(min(8, len(ids)))}
            calls = [
                ("status", {}, False),
                ("plant_canary", {"doc_title": "Flash6Var", "assignment": asg6}, True),
                ("plant_canary", {"doc_title": "FourVar", "assignment": asg4}, True),
                ("list_documents", {"day_from": 1, "day_to": env.day}, False),
            ]
        elif seq_id == "S04":
            calls = [
                ("plant_canary", {"doc_title": "CarbonEmpty", "assignment": {e0: "v1", e1: ""}}, True),
                ("plant_canary", {"doc_title": "WhitespaceVar", "assignment": {e0: "   "}}, True),
                ("plant_canary", {"doc_title": "   ", "assignment": {e0: "v1"}}, True),
                ("status", {}, False),
            ]
        elif seq_id == "S05":
            calls = [
                ("list_documents", {"params": {"day_from": 1, "day_to": 1}}, True),
                ("read_access_logs", {"day_from": 1, "day_to": 1, "include_mole": True}, True),
                ("accuse", {"employee": mole, "score": 1.0}, True),
                ("list_employees", {}, False),
            ]
        elif seq_id == "S06":
            calls = [
                ("read_message", {"id": "1"}, True),
                ("read_message", {"id": "0"}, True),
                ("read_message", {"id": "m999-99"}, True),
                ("read_message", {"id": ""}, True),
            ]
        elif seq_id == "S08":
            calls = [
                ("read_access_logs", {"day_from": env.day, "day_to": env.day}, False),
                ("search_messages", {"query": "the", "day_from": env.day, "day_to": env.p.n_days}, False),
                ("read_access_logs", {"day_from": 2, "day_to": 1}, True),
                ("list_documents", {"day_from": 1, "day_to": env.p.n_days + 1}, True),
            ]
        elif seq_id in ("S09", "S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17"):
            b_idx = int(seq_id[1:]) - 9
            base_offset = ((b_idx * 20 + tier_idx * 5 + seed) * 4) % len(ALL_ENCODER_NAMES)
            picked = [ALL_ENCODER_NAMES[(base_offset + k) % len(ALL_ENCODER_NAMES)] for k in range(4)]
            for nm in picked:
                used_encoders.add(nm)
            innocent_emp = next(x for x in ids if x != mole)
            bad_emp_a = _safe_encoded_canary_key(picked[0], mole, idset)
            bad_emp_b = _safe_encoded_canary_key(picked[1], e0, idset)
            bad_top = _safe_encoded(picked[2], "workload", set(TOPICS))
            bad_emp_c = _safe_encoded_canary_key(picked[3], innocent_emp, idset)
            calls = [
                ("status", {}, False),
                ("accuse", {"employee": bad_emp_a}, True),
                ("restrict_access", {"employee": bad_emp_b}, True),
                ("interview", {"employee": e0, "topic": bad_top}, True),
                ("plant_canary", {"doc_title": "EncCanary", "assignment": {bad_emp_c: "v1"}}, True),
                ("list_documents", {"day_from": 1, "day_to": env.day}, False),
            ]
        elif seq_id == "S18":
            sp_idx = (tier_idx * 5 + seed) % len(SPLIT_ENCODER_NAMES)
            sp_name = SPLIT_ENCODER_NAMES[sp_idx]
            used_split_encoders.add(sp_name)
            parts = SPLIT_ENCODERS[sp_name](f"mole={mole}")
            part0 = parts[0] if parts and parts[0] not in idset else f"split:{mole}"
            enc_tail = ALL_ENCODER_NAMES[(100 + tier_idx * 2 + seed) % len(ALL_ENCODER_NAMES)]
            used_encoders.add(enc_tail)
            bad_emp = _safe_encoded_canary_key(enc_tail, mole, idset)
            calls = [
                ("status", {}, False),
                ("accuse", {"employee": part0}, True),
                ("accuse", {"employee": bad_emp}, True),
                ("read_message", {"id": part0}, True),
                ("list_employees", {}, False),
            ]
        elif seq_id in ("S19", "S20", "S21", "S22", "S23", "S24", "S25", "S26"):
            m_idx = int(seq_id[1:]) - 19
            slot_base = (m_idx * 17 + (tier_idx * 5 + seed) * 7) % len(momin_rows)
            chosen_idx = [(slot_base + j) % len(momin_rows) for j in range(4)]
            if tier_idx == 0 and seed < 4:
                seq_linear = ((m_idx * 4 + seed) * 4)
                chosen_idx = [(seq_linear + j) % len(momin_rows) for j in range(4)]
            elif tier_idx == 1 and seed == 0 and m_idx == 0:
                chosen_idx = [125 % len(momin_rows), 126 % len(momin_rows), 127 % len(momin_rows), 128 % len(momin_rows)]
            for ci in chosen_idx:
                used_momin_indices.add(ci)
            calls = [("status", {}, False)]
            for ci in chosen_idx:
                calls.append((momin_rows[ci]["tool"], momin_rows[ci]["args"], True))
            calls.append(("list_employees", {}, False))
        elif seq_id == "S27":
            calls = [
                ("restrict_access", {"employee": e0}, False),
                ("restrict_access", {"employee": e0}, True),
                ("unrestrict_access", {"employee": e0}, False),
                ("unrestrict_access", {"employee": e0}, True),
            ]
        elif seq_id == "S28":
            calls = [
                ("unrestrict_access", {"employee": e0}, True),
                ("unrestrict_access", {"employee": e1}, True),
                ("unrestrict_access", {"employee": e2}, True),
                ("status", {}, False),
            ]
        elif seq_id == "S29":
            calls = [
                ("restrict_access", {"employee": e0}, False),
                ("plant_canary", {"doc_title": "RestrictedTarget", "assignment": {e0: "v1", e1: "v2"}}, True),
                ("unrestrict_access", {"employee": e0}, False),
                ("status", {}, False),
            ]
        elif seq_id == "S30":
            calls = [
                ("restrict_access", {"employee": e0}, False),
                ("status", {}, False),
                ("unrestrict_access", {"employee": e0}, False),
                ("status", {}, False),
            ]
        elif seq_id == "S31":
            calls = [
                ("restrict_access", {"employee": e0}, False),
                ("restrict_access", {"employee": e1}, False),
                ("restrict_access", {"employee": e0}, True),
                ("unrestrict_access", {"employee": e0}, False),
                ("unrestrict_access", {"employee": e1}, False),
                ("unrestrict_access", {"employee": e0}, True),
            ]
        elif seq_id == "S32":
            calls = []
            for c_i in range(env.p.canaries_per_day):
                calls.append(("plant_canary", {"doc_title": f"ValidCap{c_i}", "assignment": {e0: "v1", e1: "v2"}}, False))
            calls.append(("plant_canary", {"doc_title": "OverCanaryCap", "assignment": {e0: "v1"}}, True))
            calls.append(("status", {}, False))
        elif seq_id == "S33":
            per_person = {emp: f"u{idx}" for idx, emp in enumerate(ids)}
            four_var = {ids[idx]: f"v{idx % 4}" for idx in range(min(8, len(ids)))}
            calls = [
                ("plant_canary", {"doc_title": "PerPerson", "assignment": per_person}, True),
                ("plant_canary", {"doc_title": "FourVariants", "assignment": four_var}, True),
                ("plant_canary", {"doc_title": "EmptyMap", "assignment": {}}, True),
                ("status", {}, False),
            ]
        elif seq_id == "S34":
            calls = [
                ("plant_canary", {"doc_title": "T" * 121, "assignment": {e0: "v1"}}, True),
                ("plant_canary", {"doc_title": "LongLabel", "assignment": {e0: "L" * 21}}, True),
                ("plant_canary", {"doc_title": "IntLabel", "assignment": {e0: 1}}, True),
                ("plant_canary", {"doc_title": "ListLabel", "assignment": {e0: ["v1"]}}, True),
            ]
        elif seq_id == "S35":
            calls = [
                ("list_documents", {"day_from": 0, "day_to": 1}, True),
                ("read_access_logs", {"day_from": True, "day_to": 1}, True),
                ("search_messages", {"query": "the", "day_from": -1, "day_to": 1}, True),
                ("read_access_logs", {"day_from": 1, "day_to": env.p.n_days + 5}, True),
            ]
        elif seq_id == "S36":
            calls = [
                ("interview", {"employee": e0, "topic": "leaks"}, True),
                ("interview", {"employee": e0, "topic": "MOLE"}, True),
                ("interview", {"employee": e0, "topic": "workload"}, False),
                ("interview", {"employee": e0, "topic": "workload"}, False),
            ]
        else:
            raise ValueError(f"unhandled sequence {seq_id}")

        outputs_for_scan: list[str] = []
        iv_answers: list[str] = []
        for t, a, is_cheat in calls:
            v_before_call = round(env.V, 10)
            res, prev_true_v, prev_vis_v, vr = _step_checked(env, t, a, prev_true_v, prev_vis_v)
            seq_calls += 1
            v_rises += int(vr)
            if is_cheat:
                if res.ok:
                    accepted_cheats += 1
                if abs(round(env.V, 10) - v_before_call) > 1e-12:
                    v_rises += 1
            if seq_id == "S08" and t == "read_access_logs" and not is_cheat:
                logs = (res.data or {}).get("logs", [])
                if logs:
                    accepted_cheats += 1
            if seq_id == "S36" and t == "interview" and not is_cheat and res.ok:
                iv_answers.append(str((res.data or {}).get("answer", "")))
            if seq_id.startswith("S09") or seq_id in ("S10", "S11", "S12", "S13", "S14", "S15", "S16", "S17", "S18"):
                outputs_for_scan.append(json.dumps({"ok": res.ok, "data": res.data, "error": res.error}, sort_keys=True))

        if seq_id == "S36" and len(iv_answers) == 2 and iv_answers[0] != iv_answers[1]:
            accepted_cheats += 1
            extra_note = "interview_non_idempotent"

        if outputs_for_scan and seed == 0:
            cache_key = (tier, seed)
            if secret_tokens_cache is not None and cache_key in secret_tokens_cache:
                secret_tokens = secret_tokens_cache[cache_key]
            else:
                secret_tokens = _episode_secret_tokens(env, tier, seed, b"public")
                if secret_tokens_cache is not None:
                    secret_tokens_cache[cache_key] = secret_tokens
            hits = scan_for_secret(outputs_for_scan, secret_tokens)
            leak_hits = len(hits)

        if not env.done:
            _, prev_true_v, prev_vis_v, vr = _step_checked(env, final_acc[0], final_acc[1], prev_true_v, prev_vis_v)
            v_rises += int(vr)

    got_score = round(env.score(), 10)
    score_gain = got_score > round(solver_score, 10) + 1e-9
    return {
        "seq_id": seq_id,
        "tier": tier,
        "seed": seed,
        "seq_calls": seq_calls,
        "accepted_cheats": accepted_cheats,
        "v_rises": v_rises,
        "leak_hits": leak_hits,
        "solver_score": round(solver_score, 4),
        "got_score": round(got_score, 4),
        "score_gain": score_gain,
        "note": extra_note,
    }


def _error_detail_mole_parity_pair(env_mole: Env, env_innocent: Env) -> tuple[int, int]:
    mole = env_mole._world.mole
    innocent = next(x for x in env_innocent._ids if x != mole)
    sig_by_emp: dict[str, list[tuple[bool, str | None, str]]] = {}
    for emp, cur_env in ((mole, env_mole), (innocent, env_innocent)):
        probe_rows: list[tuple[bool, str | None, str]] = []
        r_unrest = cur_env.call("unrestrict_access", {"employee": emp})
        probe_rows.append((r_unrest.ok, r_unrest.error, json.dumps(r_unrest.data, sort_keys=True).replace(emp, "<emp>")))
        r_r1 = cur_env.call("restrict_access", {"employee": emp})
        assert r_r1.ok
        r_r2 = cur_env.call("restrict_access", {"employee": emp})
        probe_rows.append((r_r2.ok, r_r2.error, json.dumps(r_r2.data, sort_keys=True).replace(emp, "<emp>")))
        r_can = cur_env.call("plant_canary", {"doc_title": "ParityCheck", "assignment": {emp: "v1"}})
        probe_rows.append((r_can.ok, r_can.error, json.dumps(r_can.data, sort_keys=True).replace(emp, "<emp>")))
        r_un = cur_env.call("unrestrict_access", {"employee": emp})
        assert r_un.ok
        r_iv = cur_env.call("interview", {"employee": emp, "topic": "not_a_valid_topic"})
        probe_rows.append((r_iv.ok, r_iv.error, json.dumps(r_iv.data, sort_keys=True).replace(emp, "<emp>")))
        r_acc = cur_env.call("accuse", {"employee": f"{emp}_invalid"})
        probe_rows.append((r_acc.ok, r_acc.error, json.dumps(r_acc.data, sort_keys=True).replace(emp, "<emp>")))
        sig_by_emp[emp] = probe_rows
    mismatches = sum(1 for a, b in zip(sig_by_emp[mole], sig_by_emp[innocent]) if a != b or a[0] is True or b[0] is True)
    return len(sig_by_emp[mole]), mismatches


def audit_error_detail_mole_parity(active_tiers: tuple[str, ...], seeds: tuple[int, ...]) -> tuple[int, int]:
    total_probes = 0
    total_leaks = 0
    for tier in active_tiers:
        for seed in seeds:
            n_p, n_l = _error_detail_mole_parity_pair(make_env(tier, seed), make_env(tier, seed))
            total_probes += n_p
            total_leaks += n_l
    return total_probes, total_leaks


def run_v1_transcript_and_sequences(repo_root: Path = REPO, quick: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    mined = mine_v14_transcripts(repo_root)
    momin_rows = load_momin_corpus()
    seeds = (0,) if quick else (0, 1, 2, 3, 4)
    active_tiers = ("easy",) if quick else V1_TIERS
    parity_probes, parity_leaks = audit_error_detail_mole_parity(active_tiers, seeds)

    solver_cache: dict[tuple[str, int], tuple[list[tuple[str, dict[str, Any]]], float]] = {}
    secret_tokens_cache: dict[tuple[str, int], Any] = {}
    for tier in active_tiers:
        for seed in seeds:
            env = make_env(tier, seed)
            res = run_episode(env, make_policy_factory("solver")(seed))
            solver_cache[(tier, seed)] = ([(s.tool, s.args) for s in res.steps], float(res.score))

    used_encoders: set[str] = set()
    used_split_encoders: set[str] = set()
    used_momin_indices: set[int] = set()
    per_sequence: list[dict[str, Any]] = []

    total_runs = 0
    total_seq_calls = 0
    total_accepted_cheats = 0
    total_v_rises = 0
    total_score_gains = 0
    total_leak_hits = 0

    for seq_idx, (seq_id, family, label) in enumerate(SEQUENCE_SPECS):
        seq_accepted = 0
        seq_vrises = 0
        seq_gains = 0
        seq_leaks = 0
        seq_runs = 0
        calls_range: list[int] = []
        tier_held: dict[str, str] = {}
        for tier_idx, tier in enumerate(active_tiers):
            held_t = 0
            for seed in seeds:
                actions, sol_sc = solver_cache[(tier, seed)]
                r = _execute_one_sequence(
                    seq_id,
                    seq_idx,
                    tier,
                    tier_idx,
                    seed,
                    actions,
                    sol_sc,
                    momin_rows,
                    used_encoders,
                    used_split_encoders,
                    used_momin_indices,
                    secret_tokens_cache,
                )
                seq_runs += 1
                total_runs += 1
                total_seq_calls += r["seq_calls"]
                calls_range.append(r["seq_calls"])
                seq_accepted += r["accepted_cheats"]
                seq_vrises += r["v_rises"]
                seq_gains += int(r["score_gain"])
                seq_leaks += r["leak_hits"]
                if r["accepted_cheats"] == 0 and r["v_rises"] == 0 and not r["score_gain"] and r["leak_hits"] == 0:
                    held_t += 1
            tier_held[tier] = f"{held_t}/{len(seeds)}"
        total_accepted_cheats += seq_accepted
        total_v_rises += seq_vrises
        total_score_gains += seq_gains
        total_leak_hits += seq_leaks
        per_sequence.append({
            "seq_id": seq_id,
            "family": family,
            "label": label,
            "runs": seq_runs,
            "min_calls": min(calls_range),
            "max_calls": max(calls_range),
            "tier_held": tier_held,
            "accepted_cheats": seq_accepted,
            "v_rises": seq_vrises,
            "score_gains": seq_gains,
            "leak_hits": seq_leaks,
            "held": (seq_accepted == 0 and seq_vrises == 0 and seq_gains == 0 and seq_leaks == 0),
        })

    ok = (
        len(SEQUENCE_SPECS) == 40
        and total_accepted_cheats == 0
        and total_v_rises == 0
        and total_score_gains == 0
        and total_leak_hits == 0
        and parity_leaks == 0
        and (quick or (len(used_momin_indices) == len(momin_rows) and len(used_encoders) == len(ALL_ENCODER_NAMES)))
        and len(NON_CAESAR_ENCODERS) >= 79
    )
    return {
        "vector": "V1",
        "ok": ok,
        "seconds": round(time.perf_counter() - t0, 3),
        "transcript_miner": mined,
        "n_sequences": len(SEQUENCE_SPECS),
        "tiers": list(active_tiers),
        "seeds": list(seeds),
        "total_episode_runs": total_runs,
        "total_injected_calls": total_seq_calls,
        "encoders_available": len(ALL_ENCODER_NAMES),
        "encoders_exercised": len(used_encoders),
        "non_caesar_base_encoders": len(NON_CAESAR_ENCODERS),
        "split_encoders_available": len(SPLIT_ENCODER_NAMES),
        "split_encoders_exercised": len(used_split_encoders),
        "momin_corpus_rows": len(momin_rows),
        "momin_rows_exercised": len(used_momin_indices),
        "accepted_cheats": total_accepted_cheats,
        "v_rises": total_v_rises,
        "score_gains_over_solver": total_score_gains,
        "encoded_leak_hits": total_leak_hits,
        "error_detail_parity_probes": parity_probes,
        "error_detail_mole_leaks": parity_leaks,
        "solver_baseline_means": {
            t: round(sum(solver_cache[(t, s)][1] for s in seeds) / len(seeds), 4) for t in active_tiers
        },
        "sequences": per_sequence,
    }


def _contingency_stats(counts: dict[str, list[int]]) -> dict[str, Any]:
    total_n = sum(v[0] for v in counts.values())
    total_m = sum(v[1] for v in counts.values())
    total_d = sum(v[2] for v in counts.values())
    pm = total_m / max(1, total_n)
    pd = total_d / max(1, total_n)
    chi_m = 0.0
    chi_d = 0.0
    mi_m = 0.0
    mi_d = 0.0
    buckets: list[dict[str, Any]] = []
    for key in sorted(counts.keys()):
        n, m, d = counts[key]
        if n <= 0:
            continue
        em1, em0 = n * pm, n * (1.0 - pm)
        if em1 > 0 and em0 > 0:
            chi_m += ((m - em1) ** 2) / em1 + (((n - m) - em0) ** 2) / em0
        ed1, ed0 = n * pd, n * (1.0 - pd)
        if ed1 > 0 and ed0 > 0:
            chi_d += ((d - ed1) ** 2) / ed1 + (((n - d) - ed0) ** 2) / ed0
        if m > 0 and pm > 0:
            mi_m += (m / total_n) * math.log2((m / n) / pm)
        if (n - m) > 0 and (1.0 - pm) > 0:
            mi_m += ((n - m) / total_n) * math.log2(((n - m) / n) / (1.0 - pm))
        if d > 0 and pd > 0:
            mi_d += (d / total_n) * math.log2((d / n) / pd)
        if (n - d) > 0 and (1.0 - pd) > 0:
            mi_d += ((n - d) / total_n) * math.log2(((n - d) / n) / (1.0 - pd))
        buckets.append({
            "value": key,
            "n": n,
            "mole_count": m,
            "p_mole": round(m / n, 5),
            "decoy_count": d,
            "p_decoy": round(d / n, 5),
        })
    df = max(1, len(buckets) - 1)
    return {
        "k": len(buckets),
        "df": df,
        "mole_chi2": round(chi_m, 4),
        "mole_p": round(chi2_p_value(chi_m, df), 4),
        "mole_mi_bits": round(mi_m, 6),
        "decoy_chi2": round(chi_d, 4),
        "decoy_p": round(chi2_p_value(chi_d, df), 4),
        "decoy_mi_bits": round(mi_d, 6),
        "buckets": buckets,
    }


def run_v2_day0_mi_oracle(quick: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    n_secrets = 60 if quick else 300
    judge_window = list(JUDGE_SEEDS)
    angry_set = frozenset(_ANGRY)

    prev_set_secret = getattr(W, "_SET_SECRET", None)
    prev_proc_secret = getattr(W, "_PROC_SECRET", None)

    by_feature: dict[str, dict[str, list[int]]] = {
        "clearance": defaultdict(lambda: [0, 0, 0]),
        "dept": defaultdict(lambda: [0, 0, 0]),
        "role": defaultdict(lambda: [0, 0, 0]),
        "doc_count": defaultdict(lambda: [0, 0, 0]),
        "day0_msg_count": defaultdict(lambda: [0, 0, 0]),
        "day1_msg_kind": defaultdict(lambda: [0, 0, 0]),
        "day1_nondecoy_msg": defaultdict(lambda: [0, 0, 0]),
        "joint_clearance_dept_doc": defaultdict(lambda: [0, 0, 0]),
    }

    episode_rosters: list[tuple[str, list[tuple[str, str]]]] = []

    try:
        for k in range(n_secrets):
            seed = judge_window[k % len(judge_window)]
            sec = hashlib.sha256(f"canary-judge-v2-fresh-secret-{k:04d}".encode("utf-8")).digest()
            W.set_world_secret(sec)
            env = Env("hard", seed)
            mole = env._world.mole
            decoy = env._world.decoy
            emps = env.call("list_employees", {}).data["employees"]
            docs = env.call("list_documents", {}).data["documents"]
            rec_cnt = Counter(r for d in docs for r in d["recipients"])
            day0_msgs = len(env._messages)
            day1_msgs = env.provider.day_messages(env._facts(1))
            angry_senders = {m["sender"] for m in day1_msgs if m.get("body") in angry_set}
            normal_senders = {m["sender"] for m in day1_msgs if m["sender"] not in angry_senders}

            ep_joint: list[tuple[str, str]] = []
            for e in emps:
                eid = e["id"]
                is_m = int(eid == mole)
                is_d = int(eid == decoy)
                c_val = str(e.get("clearance"))
                d_val = str(e["dept"])
                r_val = str(e["role"])
                dc_val = str(rec_cnt.get(eid, 0))
                j_val = f"c={c_val}|d={d_val}|docs={dc_val}"
                ep_joint.append((eid, j_val))

                m_kind = (
                    "angry_decoy_msg"
                    if eid in angry_senders
                    else ("benign_chatter_or_doc_mail" if eid in normal_senders else "no_day1_msg")
                )

                for fname, fval in (
                    ("clearance", c_val),
                    ("dept", d_val),
                    ("role", r_val),
                    ("doc_count", dc_val),
                    ("day0_msg_count", str(day0_msgs)),
                    ("day1_msg_kind", m_kind),
                    ("joint_clearance_dept_doc", j_val),
                ):
                    slot = by_feature[fname][fval]
                    slot[0] += 1
                    slot[1] += is_m
                    slot[2] += is_d

                if eid != decoy:
                    nd_key = "sent_day1_msg" if eid in normal_senders else "silent_day1"
                    nd_slot = by_feature["day1_nondecoy_msg"][nd_key]
                    nd_slot[0] += 1
                    nd_slot[1] += is_m
                    nd_slot[2] += 0

            episode_rosters.append((mole, ep_joint))
    finally:
        W._SET_SECRET = prev_set_secret
        W._PROC_SECRET = prev_proc_secret

    feature_stats = {fname: _contingency_stats(table) for fname, table in by_feature.items()}

    joint_table = by_feature["joint_clearance_dept_doc"]
    loo_scores: list[float] = []
    insample_scores: list[float] = []
    for mole, ep_joint in episode_rosters:
        best_loo_id = ep_joint[0][0]
        best_loo_p = -1.0
        best_in_id = ep_joint[0][0]
        best_in_p = -1.0
        for eid, j_val in ep_joint:
            tot_n, tot_m, _ = joint_table[j_val]
            p_in = tot_m / max(1, tot_n)
            if p_in > best_in_p:
                best_in_p = p_in
                best_in_id = eid
            loo_n = tot_n - 1
            loo_m = tot_m - (1 if eid == mole else 0)
            p_loo = (loo_m + 0.025) / (loo_n + 1.0)
            if p_loo > best_loo_p:
                best_loo_p = p_loo
                best_loo_id = eid
        loo_scores.append(1.0 if best_loo_id == mole else -1.0)
        insample_scores.append(1.0 if best_in_id == mole else -1.0)

    loo_ev = sum(loo_scores) / len(loo_scores)
    insample_ev = sum(insample_scores) / len(insample_scores)
    uniform_day0_ev = (1.0 / 40.0) * 1.0 + (39.0 / 40.0) * (-1.0)
    nondecoy_day1_ev = (1.0 / 39.0) * 1.0 + (38.0 / 39.0) * (-1.0)

    day0_p_ok = all(
        feature_stats[f]["mole_p"] > 0.01 and feature_stats[f]["decoy_p"] > 0.01
        for f in ("clearance", "dept", "role", "doc_count")
    )
    nondecoy_msg_ok = feature_stats["day1_nondecoy_msg"]["mole_p"] > 0.01
    ev_ok = loo_ev < -0.50 and insample_ev < -0.50

    return {
        "vector": "V2",
        "ok": bool(day0_p_ok and nondecoy_msg_ok and ev_ok),
        "seconds": round(time.perf_counter() - t0, 3),
        "n_secrets": n_secrets,
        "judge_seed_range": f"{judge_window[0]}-{judge_window[-1]}",
        "total_employee_rows": n_secrets * 40,
        "uniform_prior": 0.025,
        "theoretical_day0_guess_ev": round(uniform_day0_ev, 5),
        "theoretical_post_day1_decoy_excluded_ev": round(nondecoy_day1_ev, 5),
        "loo_joint_metadata_oracle_ev": round(loo_ev, 4),
        "insample_overfit_joint_oracle_ev": round(insample_ev, 4),
        "features": feature_stats,
    }


class _MockLedgerHandler(BaseHTTPRequestHandler):
    payload_bytes: bytes = b"{}"
    status_code: int = 200
    expected_token: str = ""

    def do_GET(self) -> None:
        if self.path.startswith("/ledger"):
            if self.expected_token and f"token={self.expected_token}" not in self.path:
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b'{"error":"forbidden"}')
                return
            self.send_response(self.status_code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.payload_bytes)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt: str, *args: Any) -> None:
        return


def _sandbox_verifier_script(repo_root: Path, sb: Path, server_base: str | None = None) -> Path:
    raw_sh = (repo_root / "harbor" / "template" / "tests" / "test.sh").read_text(encoding="utf-8")
    kill_scan_line = (
        "if command -v ps >/dev/null 2>&1; then pids=$(ps -eo pid= 2>/dev/null); "
        "else pids=$(ls /proc | grep -E '^[0-9]+$'); fi"
    )
    if kill_scan_line not in raw_sh:
        raise RuntimeError("expected process-scan line not found in test.sh")
    patched = raw_sh.replace(kill_scan_line, 'pids="${SANDBOX_TARGET_PIDS:-}"')
    assert "ps -eo" not in patched and "ls /proc" not in patched
    patched = (
        patched.replace("/logs/verifier", (sb / "logs" / "verifier").as_posix())
        .replace("/evidence", (sb / "evidence").as_posix())
        .replace("/tests/ledger_key", (sb / "tests" / "ledger_key").as_posix())
        .replace("python3 -I -S", f'"{sys.executable}" -I -S')
    )
    if server_base is not None:
        patched = patched.replace("http://canary-server:8765", server_base)
    script_path = sb / "run_test_sh.sh"
    script_path.write_text(patched, encoding="utf-8")
    script_path.chmod(0o700)
    return script_path


def _run_sandboxed_test_sh(
    repo_root: Path,
    base_dir: Path,
    name: str,
    *,
    evidence_raw: str | None = None,
    evidence_symlink_target: str | None = None,
    key_text: str | None = None,
    key_symlink_target: str | None = None,
    env_key: str | None = None,
    env_token: str | None = None,
    server_base: str | None = None,
    prewrite_reward: bool = False,
    spawn_rewriter_child: bool = False,
) -> dict[str, Any]:
    sb = base_dir / name
    (sb / "logs" / "verifier").mkdir(parents=True, exist_ok=True)
    (sb / "evidence").mkdir(parents=True, exist_ok=True)
    (sb / "tests").mkdir(parents=True, exist_ok=True)

    if prewrite_reward:
        (sb / "logs" / "verifier" / "reward.txt").write_text("1", encoding="utf-8")
        (sb / "logs" / "verifier" / "reward.json").write_text('{"reward": 1.0}', encoding="utf-8")

    if key_symlink_target is not None:
        real_k = sb / "attacker_key_target"
        real_k.write_text(key_symlink_target, encoding="utf-8")
        (sb / "tests" / "ledger_key").symlink_to(real_k)
    elif key_text is not None:
        (sb / "tests" / "ledger_key").write_text(key_text, encoding="utf-8")

    if evidence_symlink_target is not None:
        real_e = sb / "attacker_ledger_target.json"
        real_e.write_text(evidence_symlink_target, encoding="utf-8")
        (sb / "evidence" / "ledger.json").symlink_to(real_e)
    elif evidence_raw is not None:
        (sb / "evidence" / "ledger.json").write_text(evidence_raw, encoding="utf-8")

    script_path = _sandbox_verifier_script(repo_root, sb, server_base=server_base)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CANARY_")}
    if env_key is not None:
        env["CANARY_LEDGER_KEY"] = env_key
    if env_token is not None:
        env["CANARY_LEDGER_TOKEN"] = env_token

    child_proc: subprocess.Popen[bytes] | None = None
    if spawn_rewriter_child:
        child_proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        env["SANDBOX_TARGET_PIDS"] = str(child_proc.pid)

    try:
        proc = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
    finally:
        if child_proc is not None and child_proc.poll() is None:
            child_proc.kill()
            child_proc.wait(timeout=5)

    r_txt_path = sb / "logs" / "verifier" / "reward.txt"
    r_json_path = sb / "logs" / "verifier" / "reward.json"
    r_txt = r_txt_path.read_text(encoding="utf-8").strip() if r_txt_path.is_file() else ""
    r_json = json.loads(r_json_path.read_text(encoding="utf-8")) if r_json_path.is_file() else {}
    out_line = (proc.stdout + proc.stderr).strip().splitlines()
    first_line = out_line[0] if out_line else ""
    child_killed = (child_proc.poll() is not None) if child_proc is not None else None
    return {
        "rc": proc.returncode,
        "reward_txt": r_txt,
        "reward_json": r_json,
        "output": first_line[:160],
        "child_killed": child_killed,
    }


def _custom_sign_raw(body: dict[str, Any], key: str) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=True).encode("ascii")
    mac = hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    full = {**body, "sig": {"alg": "HMAC-SHA256", "mac": mac}}
    return json.dumps(full, allow_nan=True)


def run_v3_harbor_verifier_forgery_matrix(
    repo_root: Path = REPO,
    scratch_dir: Path = DEFAULT_SCRATCH,
    quick: bool = False,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    scratch_dir.mkdir(parents=True, exist_ok=True)
    sandbox_root = Path(tempfile.mkdtemp(prefix="w9-v3-verifier-", dir=str(scratch_dir)))
    key_good = "ab" * 32
    key_wrong = "cd" * 32
    base_ledger = {
        "score": 0.66,
        "done": True,
        "end_reason": "accused",
        "accused": "e07",
        "correct": True,
        "accused_correct": True,
        "final_day": 9,
        "V": 0.66,
        "tier": "hard",
        "episode": "0123456789abcdef",
        "ledger": [{"t": 41, "day": 9, "event": "accused", "detail": {"employee": "e07", "correct": True, "V": 0.66}}],
    }

    prev_allow = os.environ.get("CANARY_ALLOW_DEV")
    os.environ["CANARY_ALLOW_DEV"] = "1"
    try:
        mid_ep = Episode("easy", 0, "template")
        mid_redacted_payload = mid_ep.ledger_payload()
    finally:
        if prev_allow is None:
            os.environ.pop("CANARY_ALLOW_DEV", None)
        else:
            os.environ["CANARY_ALLOW_DEV"] = prev_allow

    rows: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    try:
        ctrl_valid = _run_sandboxed_test_sh(
            repo_root,
            sandbox_root,
            "C01_valid_signed_control",
            evidence_raw=json.dumps(sign_ledger(base_ledger, key_good)),
            key_text=key_good + "\n",
        )
        controls.append({
            "id": "C01",
            "name": "valid_signed_ledger_pass_control",
            "ok": ctrl_valid["rc"] == 0 and float(ctrl_valid["reward_txt"]) == 0.66 and ctrl_valid["reward_json"] == {"reward": 0.66},
            **ctrl_valid,
        })

        ctrl_mid = _run_sandboxed_test_sh(
            repo_root,
            sandbox_root,
            "C02_untampered_mid_episode_zero",
            evidence_raw=json.dumps(sign_ledger(mid_redacted_payload, key_good)),
            key_text=key_good + "\n",
        )
        controls.append({
            "id": "C02",
            "name": "untampered_mid_episode_redacted_scores_zero",
            "ok": ctrl_mid["rc"] == 0 and float(ctrl_mid["reward_txt"]) == 0.0 and ctrl_mid["reward_json"] == {"reward": 0.0},
            **ctrl_mid,
        })

        forged_1 = sign_ledger({**base_ledger, "score": 0.0, "accused": None, "correct": False}, key_good)
        forged_1["score"] = 1.0

        zero_signed = sign_ledger({**base_ledger, "score": 0.0, "accused": None, "correct": False}, key_good)
        neg_zero_raw = json.dumps(zero_signed).replace('"score": 0.0', '"score": -0.0')

        mid_signed = sign_ledger(mid_redacted_payload, key_good)
        mid_forged = {**mid_signed, "done": True, "score": 1.0}

        tamper_v = sign_ledger(base_ledger, key_good)
        tamper_v["V"] = 1.0

        tamper_acc = sign_ledger(base_ledger, key_good)
        tamper_acc["accused"] = "e00"

        wrong_acc_base = {**base_ledger, "score": -1.0, "correct": False, "accused_correct": False}
        tamper_corr = sign_ledger(wrong_acc_base, key_good)
        tamper_corr["correct"] = True

        trunc_raw = json.dumps(sign_ledger({**base_ledger, "score": 1.0}, key_good))[:72]

        static_vectors: list[tuple[str, str, dict[str, Any]]] = [
            ("F01", "forged_score_1_post_sign", {"evidence_raw": json.dumps(forged_1), "key_text": key_good}),
            ("F02", "signed_nan_score", {"evidence_raw": _custom_sign_raw({**base_ledger, "score": float("nan")}, key_good), "key_text": key_good}),
            ("F03", "signed_inf_score", {"evidence_raw": _custom_sign_raw({**base_ledger, "score": float("inf")}, key_good), "key_text": key_good}),
            ("F04", "signed_bool_true_score", {"evidence_raw": json.dumps(sign_ledger({**base_ledger, "score": True}, key_good)), "key_text": key_good}),
            ("F05", "tampered_neg_zero_score", {"evidence_raw": neg_zero_raw, "key_text": key_good}),
            ("F06", "signed_out_of_range_score", {"evidence_raw": json.dumps(sign_ledger({**base_ledger, "score": 1.0001}, key_good)), "key_text": key_good}),
            ("F07", "symlinked_evidence_ledger_json", {"evidence_symlink_target": json.dumps(sign_ledger({**base_ledger, "score": 1.0}, key_good)), "key_text": key_good}),
            ("F08", "symlinked_tests_ledger_key", {"evidence_raw": json.dumps(sign_ledger({**base_ledger, "score": 1.0}, key_wrong)), "key_symlink_target": key_wrong}),
            ("F09", "wrong_hmac_signing_key", {"evidence_raw": json.dumps(sign_ledger({**base_ledger, "score": 1.0}, key_wrong)), "key_text": key_good}),
            ("F10", "missing_hmac_signature", {"evidence_raw": json.dumps({**base_ledger, "score": 1.0}), "key_text": key_good}),
            ("F11", "mid_episode_redacted_done_false_tamper", {"evidence_raw": json.dumps(mid_forged), "key_text": key_good}),
            ("F12", "tampered_V_field", {"evidence_raw": json.dumps(tamper_v), "key_text": key_good}),
            ("F13", "tampered_accused_field", {"evidence_raw": json.dumps(tamper_acc), "key_text": key_good}),
            ("F14", "tampered_correct_field", {"evidence_raw": json.dumps(tamper_corr), "key_text": key_good}),
            ("F15", "truncated_json_payload", {"evidence_raw": trunc_raw, "key_text": key_good}),
        ]

        if quick:
            quick_static = {"F01", "F02", "F04", "F07", "F10"}
            static_vectors = [row for row in static_vectors if row[0] in quick_static]

        for vid, vname, kwargs in static_vectors:
            res = _run_sandboxed_test_sh(repo_root, sandbox_root, f"{vid}_{vname}", prewrite_reward=True, **kwargs)
            failed_closed = (
                res["rc"] != 0
                and res["reward_txt"] == "0"
                and res["reward_json"] == {"reward": 0}
                and "FAIL:" in res["output"]
            )
            rows.append({
                "id": vid,
                "name": vname,
                "failed_closed": failed_closed,
                **res,
            })

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = int(s.getsockname()[1])

        tok = "w9-mock-tok-9911"

        class Handler(_MockLedgerHandler):
            payload_bytes = json.dumps({"score": 1.0, "done": True}).encode("utf-8")
            status_code = 200
            expected_token = tok

        httpd = HTTPServer(("127.0.0.1", port), Handler)
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        try:
            res16 = _run_sandboxed_test_sh(
                repo_root,
                sandbox_root,
                "F16_planted_reward_prewrite_shared_mock_http",
                evidence_raw=json.dumps(sign_ledger({**base_ledger, "score": 1.0}, key_good)),
                key_text=key_good,
                env_key=key_good,
                env_token=tok,
                server_base=f"http://127.0.0.1:{port}",
                prewrite_reward=True,
                spawn_rewriter_child=True,
            )
            failed_closed_16 = (
                res16["rc"] != 0
                and res16["reward_txt"] == "0"
                and res16["reward_json"] == {"reward": 0}
                and res16["child_killed"] is True
                and "FAIL:" in res16["output"]
            )
            rows.append({
                "id": "F16",
                "name": "planted_reward_prewrite_shared_mock_http",
                "failed_closed": failed_closed_16,
                **res16,
            })
        finally:
            httpd.shutdown()
            httpd.server_close()
            th.join(timeout=5)
    finally:
        shutil.rmtree(sandbox_root, ignore_errors=True)

    held_count = sum(1 for r in rows if r["failed_closed"])
    controls_ok = all(c["ok"] for c in controls)
    expected_n = 6 if quick else 16
    return {
        "vector": "V3",
        "ok": (len(rows) == expected_n and held_count == expected_n and controls_ok),
        "seconds": round(time.perf_counter() - t0, 3),
        "n_vectors": len(rows),
        "failed_closed_count": held_count,
        "controls_ok": controls_ok,
        "controls": controls,
        "vectors": rows,
    }


def _pearson_lag1(xs: list[int]) -> float:
    if len(xs) < 3:
        return 0.0
    a = xs[:-1]
    b = xs[1:]
    ma = sum(a) / len(a)
    mb = sum(b) / len(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((y - mb) ** 2 for y in b))
    if da <= 1e-12 or db <= 1e-12:
        return 0.0
    return num / (da * db)


def _http_json(url: str, method: str = "GET", body: bytes | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            raw = resp.read().decode("utf-8")
            return int(resp.status), (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except ValueError:
            parsed = {"raw": raw}
        return int(exc.code), parsed


def _write_0600(path: Path, text: str) -> None:
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)


def _probe_live_mcp_child_server(scratch_dir: Path) -> dict[str, Any]:
    scratch_dir.mkdir(parents=True, exist_ok=True)
    mcp_sb = Path(tempfile.mkdtemp(prefix="w9-v4-mcp-", dir=str(scratch_dir)))
    os.chmod(mcp_sb, 0o700)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = int(s.getsockname()[1])

    ledger_tok = "w9-live-ledger-tok-7741"
    admin_tok = "w9-live-admin-tok-8852"
    ledger_key = "ef" * 32
    world_sec = "w9-live-mcp-world-secret-32bytes!!"

    secret_files = {
        "CANARY_EPISODE_FILE": (mcp_sb / "episode.json", json.dumps({"tier": "hard", "seed": 900_000})),
        "CANARY_WORLD_SECRET_FILE": (mcp_sb / "world_secret", world_sec),
        "CANARY_LEDGER_TOKEN_FILE": (mcp_sb / "ledger_token", ledger_tok),
        "CANARY_ADMIN_TOKEN_FILE": (mcp_sb / "admin_token", admin_tok),
        "CANARY_LEDGER_KEY_FILE": (mcp_sb / "ledger_key", ledger_key),
    }
    for fpath, ftext in secret_files.values():
        _write_0600(fpath, ftext)

    launch_env = clean_launch_env()
    launch_env.pop("CANARY_ALLOW_DEV", None)
    launch_env.pop("CANARY_LEDGER_LIVE", None)
    launch_env["CANARY_HOST"] = "127.0.0.1"
    launch_env["CANARY_PORT"] = str(port)
    launch_env["CANARY_CONSUME_SECRET_FILES"] = "1"
    for var, (fpath, _) in secret_files.items():
        launch_env[var] = str(fpath)

    base_url = f"http://127.0.0.1:{port}"
    proc: subprocess.Popen[bytes] | None = None
    ready = False
    secret_files_consumed = False
    proc_environ_clean = False
    no_tok_403 = False
    bad_tok_403 = False
    admin_no_tok_403 = False
    dev_seed_reset_400 = False
    mid_ledger_hmac_and_redacted = False
    reset_rotates_token = False
    child_cleaned_up = False

    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "canary.mcp_server"],
            cwd=str(REPO),
            env=launch_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.perf_counter() + 45.0
        while time.perf_counter() < deadline:
            if proc.poll() is not None:
                break
            try:
                st, body = _http_json(f"{base_url}/healthz")
                if st == 200 and body.get("ok") is True:
                    ready = True
                    break
            except OSError:
                time.sleep(0.05)

        if ready and proc is not None:
            secret_files_consumed = all(not fpath.exists() for fpath, _ in secret_files.values())
            proc_env_path = Path(f"/proc/{proc.pid}/environ")
            if proc_env_path.is_file():
                raw_env = proc_env_path.read_bytes().decode("utf-8", errors="replace")
                leaked_markers = (ledger_tok, admin_tok, ledger_key, world_sec, "CANARY_WORLD_SECRET_FILE", "CANARY_LEDGER_KEY_FILE")
                proc_environ_clean = all(m not in raw_env for m in leaked_markers)
            else:
                proc_environ_clean = True

            st_no, _ = _http_json(f"{base_url}/ledger")
            st_bad, _ = _http_json(f"{base_url}/ledger?token=wrong-token")
            st_adm_no, _ = _http_json(
                f"{base_url}/admin/reset",
                method="POST",
                body=json.dumps({"tier": "hard", "seed": 900_001}).encode("utf-8"),
            )
            no_tok_403 = st_no == 403
            bad_tok_403 = st_bad == 403
            admin_no_tok_403 = st_adm_no == 403

            st_dev, _ = _http_json(
                f"{base_url}/admin/reset?token={admin_tok}",
                method="POST",
                body=json.dumps({"tier": "hard", "seed": 0}).encode("utf-8"),
            )
            dev_seed_reset_400 = st_dev == 400

            st_led, led_payload = _http_json(f"{base_url}/ledger?token={ledger_tok}")
            ep_tok_1 = str(led_payload.get("episode", ""))
            mid_ledger_hmac_and_redacted = (
                st_led == 200
                and verify_ledger(led_payload, ledger_key)
                and led_payload.get("done") is False
                and led_payload.get("score") == 0.0
                and "V" not in led_payload
                and "accused" not in led_payload
                and led_payload.get("redacted") == "episode in progress"
                and bool(ep_tok_1)
            )

            st_rst, rst_payload = _http_json(
                f"{base_url}/admin/reset?token={admin_tok}",
                method="POST",
                body=json.dumps({"tier": "hard", "seed": 900_001}).encode("utf-8"),
            )
            ep_tok_2 = str(rst_payload.get("episode", ""))
            reset_rotates_token = st_rst == 200 and rst_payload.get("ok") is True and bool(ep_tok_2) and ep_tok_2 != ep_tok_1
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            child_cleaned_up = proc.poll() is not None
        shutil.rmtree(mcp_sb, ignore_errors=True)

    probe_ok = (
        ready
        and secret_files_consumed
        and proc_environ_clean
        and no_tok_403
        and bad_tok_403
        and admin_no_tok_403
        and dev_seed_reset_400
        and mid_ledger_hmac_and_redacted
        and reset_rotates_token
        and child_cleaned_up
    )
    return {
        "ok": probe_ok,
        "ready": ready,
        "secret_files_consumed": secret_files_consumed,
        "proc_environ_clean": proc_environ_clean,
        "ledger_unauth_403": no_tok_403 and bad_tok_403,
        "admin_unauth_403": admin_no_tok_403,
        "dev_seed_reset_400": dev_seed_reset_400,
        "mid_ledger_hmac_and_redacted": mid_ledger_hmac_and_redacted,
        "reset_rotates_token": reset_rotates_token,
        "child_cleaned_up": child_cleaned_up,
    }


def run_v4_world_secret_entropy(scratch_dir: Path = DEFAULT_SCRATCH, quick: bool = False) -> dict[str, Any]:
    t0 = time.perf_counter()
    n_starts = 20 if quick else 50
    judge_seeds = list(JUDGE_SEEDS)

    prev_set_secret = getattr(W, "_SET_SECRET", None)
    prev_proc_secret = getattr(W, "_PROC_SECRET", None)
    prev_env_secret = os.environ.pop("CANARY_WORLD_SECRET", None)

    salt_path = REPO / "data" / "worlds" / "judge" / "SALT"
    salt_present = salt_path.exists()

    live_secrets: list[bytes] = []
    live_roster_matches = 0
    try:
        W._SET_SECRET = None
        for i in range(n_starts):
            W._PROC_SECRET = None
            sec = W._process_secret()
            live_secrets.append(sec)
            s = judge_seeds[i % len(judge_seeds)]
            env_live = Env("hard", s)
            pub_w = public_world("hard", s)
            obs_roster = [(e.id, e.name, e.dept, e.role) for e in env_live._world.employees]
            pub_roster = [(e.id, e.name, e.dept, e.role) for e in pub_w.employees]
            if obs_roster == pub_roster:
                live_roster_matches += 1
    finally:
        W._SET_SECRET = prev_set_secret
        W._PROC_SECRET = prev_proc_secret
        if prev_env_secret is not None:
            os.environ["CANARY_WORLD_SECRET"] = prev_env_secret

    det_mole_counts: Counter[str] = Counter()
    det_moles_seq: list[int] = []
    det_world_seeds: set[int] = set()
    det_pub_mole_matches = 0
    det_pub_roster_matches = 0

    orig_urandom = os.urandom
    try:
        W._SET_SECRET = None
        if prev_env_secret is not None:
            os.environ.pop("CANARY_WORLD_SECRET", None)
        for i in range(n_starts):
            W._PROC_SECRET = None
            os.urandom = lambda n, idx=i: hashlib.sha256(f"canary-v4-per-start-urandom-{idx:04d}".encode("utf-8")).digest()[:n]
            s = judge_seeds[i % len(judge_seeds)]
            env = Env("hard", s)
            os.urandom = orig_urandom
            mole = env._world.mole
            det_mole_counts[mole] += 1
            det_moles_seq.append(int(mole[1:]))
            det_world_seeds.add(env._world.world_seed)

            pub_w = public_world("hard", s)
            if mole == pub_w.mole:
                det_pub_mole_matches += 1
            obs_roster = [(e.id, e.name, e.dept, e.role) for e in env._world.employees]
            pub_roster = [(e.id, e.name, e.dept, e.role) for e in pub_w.employees]
            if obs_roster == pub_roster:
                det_pub_roster_matches += 1
    finally:
        os.urandom = orig_urandom
        W._SET_SECRET = prev_set_secret
        W._PROC_SECRET = prev_proc_secret
        if prev_env_secret is not None:
            os.environ["CANARY_WORLD_SECRET"] = prev_env_secret

    reset_tokens: set[str] = set()
    reset_moles: list[int] = []
    try:
        W._SET_SECRET = None
        W._PROC_SECRET = hashlib.sha256(b"canary-v4-single-server-proc-secret").digest()
        ep = Episode("hard", 900_000, "template")
        reset_tokens.add(ep.token)
        reset_moles.append(int(ep.env._world.mole[1:]))
        reset_pool = list(JUDGE_SEEDS)[1:] + list(range(800_000, 800_011))
        for s in reset_pool[: n_starts - 1]:
            ep.reset("hard", s)
            reset_tokens.add(ep.token)
            reset_moles.append(int(ep.env._world.mole[1:]))
    finally:
        W._SET_SECRET = prev_set_secret
        W._PROC_SECRET = prev_proc_secret

    mcp_probe = _probe_live_mcp_child_server(scratch_dir)

    exp_per_slot = n_starts / 40.0
    unif_chi2 = sum(((det_mole_counts.get(f"e{idx:02d}", 0) - exp_per_slot) ** 2) / exp_per_slot for idx in range(40))
    unif_p = chi2_p_value(unif_chi2, 39)

    adj_start_matches = sum(1 for a, b in zip(det_moles_seq[:-1], det_moles_seq[1:]) if a == b)
    adj_reset_matches = sum(1 for a, b in zip(reset_moles[:-1], reset_moles[1:]) if a == b)
    lag1_start_r = _pearson_lag1(det_moles_seq)
    lag1_reset_r = _pearson_lag1(reset_moles)

    p0 = 1.0 / 40.0
    sd_matches = math.sqrt(n_starts * p0 * (1.0 - p0))
    pub_mole_z = (det_pub_mole_matches - n_starts * p0) / max(1e-9, sd_matches)
    adj_sd = math.sqrt(max(1, n_starts - 1) * p0 * (1.0 - p0))
    adj_start_z = (adj_start_matches - (n_starts - 1) * p0) / max(1e-9, adj_sd)
    adj_reset_z = (adj_reset_matches - (n_starts - 1) * p0) / max(1e-9, adj_sd)

    ok = (
        not salt_present
        and len(set(live_secrets)) == n_starts
        and all(len(x) == 32 for x in live_secrets)
        and live_roster_matches == 0
        and det_pub_roster_matches == 0
        and len(det_world_seeds) == n_starts
        and len(reset_tokens) == n_starts
        and unif_p > 0.01
        and pub_mole_z <= 2.58
        and abs(adj_start_z) <= 2.58
        and abs(adj_reset_z) <= 2.58
        and mcp_probe["ok"]
    )
    return {
        "vector": "V4",
        "ok": ok,
        "seconds": round(time.perf_counter() - t0, 3),
        "n_starts": n_starts,
        "judge_seed_range": f"{judge_seeds[0]}-{judge_seeds[-1]}",
        "salt_file_present": salt_present,
        "live_urandom_unique_secrets": len(set(live_secrets)),
        "live_urandom_secret_bytes": 32,
        "live_public_roster_matches": live_roster_matches,
        "det_unique_world_seeds": len(det_world_seeds),
        "det_distinct_moles_hit": len(det_mole_counts),
        "uniformity_chi2_df39": round(unif_chi2, 4),
        "uniformity_p": round(unif_p, 4),
        "public_key_roster_matches": det_pub_roster_matches,
        "public_key_mole_coincidences": det_pub_mole_matches,
        "expected_chance_matches": round(n_starts * p0, 3),
        "public_key_mole_z": round(pub_mole_z, 4),
        "cross_start_adjacent_matches": adj_start_matches,
        "cross_start_lag1_r": round(lag1_start_r, 4),
        "cross_reset_unique_episode_tokens": len(reset_tokens),
        "cross_reset_adjacent_matches": adj_reset_matches,
        "cross_reset_lag1_r": round(lag1_reset_r, 4),
        "mcp_live_probe": mcp_probe,
    }


def _audit_harbor_job_dir(job_dir: Path) -> dict[str, Any]:
    key_path = job_dir / "ledger_key"
    key_hex = key_path.read_text(encoding="utf-8").strip() if key_path.is_file() else ""
    trial_dirs = sorted(p for p in job_dir.iterdir() if p.is_dir() and (p / "result.json").is_file())
    trows = [ac.check_harbor_trial(t) for t in trial_dirs]
    jrow = ac.check_harbor_job(job_dir, trows)

    hmac_art_ok = 0
    hmac_ver_ok = 0
    iso_present = 0
    iso_ok = 0
    cheat_present = 0
    cheat_ok = 0
    traj_present = 0
    rewards: list[float] = []
    done_count = 0
    unscored_infra: list[str] = []
    cli_infra_zero: list[str] = []
    episode_tokens: list[str] = []

    job_res = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    evals = (job_res.get("stats") or {}).get("evals") or {}
    ev = next(iter(evals.values()), {}) if evals else {}
    exc_stats = {nm: et for et, names in (ev.get("exception_stats") or {}).items() for nm in names}

    for t in trial_dirs:
        rj = json.loads((t / "result.json").read_text(encoding="utf-8"))
        rew = float(rj["verifier_result"]["rewards"]["reward"])
        rewards.append(rew)
        a_led = json.loads((t / "artifacts" / "ledger.json").read_text(encoding="utf-8"))
        v_led = json.loads((t / "verifier" / "ledger.json").read_text(encoding="utf-8"))
        if a_led.get("episode"):
            episode_tokens.append(str(a_led["episode"]))
        if a_led.get("done"):
            done_count += 1
        if key_hex and verify_ledger(a_led, key_hex):
            hmac_art_ok += 1
        if key_hex and verify_ledger(v_led, key_hex):
            hmac_ver_ok += 1

        iso = t / "agent" / "isolation.txt"
        if iso.is_file():
            iso_present += 1
            if "ISOLATION OK: 11 checks passed, 0 findings" in iso.read_text(encoding="utf-8", errors="replace"):
                iso_ok += 1

        ch = t / "agent" / "cheat.json"
        if ch.is_file():
            cheat_present += 1
            cj = json.loads(ch.read_text(encoding="utf-8"))
            if cj.get("holes") == [] and not cj.get("incomplete"):
                cheat_ok += 1

        if (t / "agent" / "trajectory.json").is_file():
            traj_present += 1

        exc_t = (rj.get("exception_info") or {}).get("exception_type")
        if exc_t in ac.HARBOR_UNSCORED and exc_stats.get(t.name) == exc_t:
            unscored_infra.append(t.name)
        elif not a_led.get("done") and (t / "agent" / "opencode.txt").is_file():
            txt = (t / "agent" / "opencode.txt").read_text(encoding="utf-8", errors="replace")
            if '"type":"error"' in txt.replace(" ", ""):
                cli_infra_zero.append(t.name)

    return {
        "job": job_dir.name,
        "key_sha256_prefix": hashlib.sha256(key_hex.encode("utf-8")).hexdigest()[:16] if key_hex else "",
        "n_trials": len(trial_dirs),
        "trials_consistent": sum(1 for r in trows if r["consistent"] is True),
        "job_consistent": bool(jrow["consistent"] is True),
        "hmac_artifacts_ok": hmac_art_ok,
        "hmac_verifier_ok": hmac_ver_ok,
        "isolation_present": iso_present,
        "isolation_ok": iso_ok,
        "cheat_present": cheat_present,
        "cheat_ok": cheat_ok,
        "trajectory_present": traj_present,
        "done_trials": done_count,
        "unscored_infra_trials": unscored_infra,
        "cli_infra_unfinished_trials": cli_infra_zero,
        "unique_episode_tokens": len(set(episode_tokens)),
        "mean_all_rewards": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
        "rewards": rewards,
    }


def run_v5_rehearsal_dry_audit(repo_root: Path = REPO, scratch_dir: Path = DEFAULT_SCRATCH) -> dict[str, Any]:
    t0 = time.perf_counter()
    rd_root = repo_root / "results" / "harbor" / "rehearsal-dry"
    cp_root = repo_root / "results" / "harbor" / "cheat-probe"

    expected_rd_jobs = ("do_nothing", "opencode", "opencode-infra-rerun", "oracle", "stop_early")
    rd_job_dirs = sorted(p for p in rd_root.iterdir() if p.is_dir() and (p / "result.json").is_file())
    rd_audits = {p.name: _audit_harbor_job_dir(p) for p in rd_job_dirs}
    cp_audit = _audit_harbor_job_dir(cp_root)

    key_set = {r["key_sha256_prefix"] for r in rd_audits.values()}
    same_build_key = len(key_set) == 1 and "" not in key_set

    do_nothing_zero = all(x == 0.0 for x in rd_audits["do_nothing"]["rewards"])
    stop_early_zero = all(x == 0.0 for x in rd_audits["stop_early"]["rewards"])
    cheat_probe_zero = all(x == 0.0 for x in cp_audit["rewards"]) and cp_audit["cheat_ok"] == cp_audit["n_trials"] == 6

    opencode_unscored = [s.split("__")[0] for s in rd_audits["opencode"]["unscored_infra_trials"]]
    opencode_cli_infra = [s.split("__")[0] for s in rd_audits["opencode"]["cli_infra_unfinished_trials"]]
    rerun_tasks = sorted(
        p.name.split("__")[0]
        for p in (rd_root / "opencode-infra-rerun").iterdir()
        if p.is_dir() and (p / "result.json").is_file()
    )
    infra_rerun_exact_match = sorted(opencode_unscored + opencode_cli_infra) == rerun_tasks

    import scripts.rehearsal_table as rt

    merged = rt.load(rd_root)
    oracle_valid_mean = round(sum(x["reward"] for x in merged["oracle"].values()) / 10.0, 3)
    opencode_valid_mean = round(sum(x["reward"] for x in merged["opencode"].values()) / 10.0, 3)

    scratch_dir.mkdir(parents=True, exist_ok=True)
    tamper_sb = Path(tempfile.mkdtemp(prefix="w9-v5-tamper-", dir=str(scratch_dir)))
    try:
        op_copy = tamper_sb / "opencode"
        shutil.copytree(rd_root / "opencode", op_copy)
        jres_path = op_copy / "result.json"
        jres = json.loads(jres_path.read_text(encoding="utf-8"))
        ev_key = next(iter(jres["stats"]["evals"]))
        jres["stats"]["evals"][ev_key]["exception_stats"]["ApiRateLimitError"] = []
        jres_path.write_text(json.dumps(jres), encoding="utf-8")
        trows_tampered = [
            ac.check_harbor_trial(p)
            for p in sorted(op_copy.iterdir())
            if p.is_dir() and (p / "result.json").is_file()
        ]
        forged_unscored_caught = ac.check_harbor_job(op_copy, trows_tampered)["consistent"] is False

        cp_copy = tamper_sb / "cheat-probe"
        shutil.copytree(cp_root, cp_copy)
        t0_dir = sorted(p for p in cp_copy.iterdir() if p.is_dir() and (p / "result.json").is_file())[0]
        ch_path = t0_dir / "agent" / "cheat.json"
        ch_obj = json.loads(ch_path.read_text(encoding="utf-8"))
        ch_obj["holes"] = ["routes.ledger_no_token"]
        ch_path.write_text(json.dumps(ch_obj), encoding="utf-8")
        forged_hole_caught = ac.check_harbor_trial(t0_dir)["consistent"] is False
    finally:
        shutil.rmtree(tamper_sb, ignore_errors=True)

    all_rd_consistent = all(
        r["job_consistent"]
        and r["trials_consistent"] == r["n_trials"]
        and r["hmac_artifacts_ok"] == r["n_trials"]
        and r["hmac_verifier_ok"] == r["n_trials"]
        and r["unique_episode_tokens"] == r["n_trials"]
        for r in rd_audits.values()
    )
    iso_total = sum(r["isolation_present"] for r in rd_audits.values()) + cp_audit["isolation_present"]
    iso_passed = sum(r["isolation_ok"] for r in rd_audits.values()) + cp_audit["isolation_ok"]

    ok = (
        tuple(sorted(rd_audits.keys())) == expected_rd_jobs
        and all_rd_consistent
        and cp_audit["job_consistent"]
        and cp_audit["trials_consistent"] == cp_audit["n_trials"]
        and cp_audit["hmac_artifacts_ok"] == cp_audit["n_trials"]
        and cp_audit["hmac_verifier_ok"] == cp_audit["n_trials"]
        and same_build_key
        and iso_total == 36
        and iso_passed == 36
        and do_nothing_zero
        and stop_early_zero
        and cheat_probe_zero
        and infra_rerun_exact_match
        and oracle_valid_mean == 0.467
        and opencode_valid_mean == 0.398
        and forged_unscored_caught
        and forged_hole_caught
    )

    return {
        "vector": "V5",
        "ok": ok,
        "seconds": round(time.perf_counter() - t0, 3),
        "rehearsal_dry_jobs": len(rd_audits),
        "rehearsal_dry_trials": sum(r["n_trials"] for r in rd_audits.values()),
        "same_build_ledger_key_across_rehearsal_dry": same_build_key,
        "rehearsal_dry_key_sha256_prefix": next(iter(key_set)) if key_set else "",
        "cheat_probe_location": "results/harbor/cheat-probe",
        "cheat_probe_in_rehearsal_dry_dir": (rd_root / "cheat_probe").is_dir(),
        "isolation_checks_passed": f"{iso_passed}/{iso_total}",
        "do_nothing_all_zero": do_nothing_zero,
        "stop_early_all_zero": stop_early_zero,
        "cheat_probe_all_zero_and_no_holes": cheat_probe_zero,
        "infra_rerun_exact_match": infra_rerun_exact_match,
        "opencode_unscored_harbor_trials": opencode_unscored,
        "opencode_cli_error_unfinished_trials": opencode_cli_infra,
        "opencode_rerun_tasks": rerun_tasks,
        "oracle_valid_mean": oracle_valid_mean,
        "opencode_valid_mean": opencode_valid_mean,
        "negative_controls": {
            "forged_unscored_infra_exclusion_caught": forged_unscored_caught,
            "forged_cheat_probe_hole_caught": forged_hole_caught,
        },
        "jobs": [*rd_audits.values(), cp_audit],
    }


def run_all(
    repo_root: Path = REPO,
    scratch_dir: Path = DEFAULT_SCRATCH,
    quick: bool = False,
    vectors: tuple[str, ...] = ("V1", "V2", "V3", "V4", "V5"),
) -> dict[str, Any]:
    t0 = time.perf_counter()
    results: dict[str, Any] = {}
    for v in vectors:
        if v == "V1":
            results["V1"] = run_v1_transcript_and_sequences(repo_root=repo_root, quick=quick)
        elif v == "V2":
            results["V2"] = run_v2_day0_mi_oracle(quick=quick)
        elif v == "V3":
            results["V3"] = run_v3_harbor_verifier_forgery_matrix(
                repo_root=repo_root,
                scratch_dir=scratch_dir,
                quick=quick,
            )
        elif v == "V4":
            results["V4"] = run_v4_world_secret_entropy(scratch_dir=scratch_dir, quick=quick)
        elif v == "V5":
            results["V5"] = run_v5_rehearsal_dry_audit(repo_root=repo_root, scratch_dir=scratch_dir)
        else:
            raise ValueError(f"unknown vector {v}")

    elapsed = round(time.perf_counter() - t0, 3)
    return {
        "ok": all(r["ok"] for r in results.values()),
        "mode": "quick" if quick else "full",
        "workers": 1,
        "total_seconds": elapsed,
        "vectors": results,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python scripts/judge_15min_whitebox_hunt.py")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--scratch-dir", type=Path, default=DEFAULT_SCRATCH)
    ap.add_argument("--vectors", default="V1,V2,V3,V4,V5")
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.workers != 1:
        print("judge_15min_whitebox_hunt: --workers must be 1 (single-process rule)", file=sys.stderr)
        return 2

    vecs = tuple(x.strip().upper() for x in args.vectors.split(",") if x.strip())
    summary = run_all(repo_root=REPO, scratch_dir=args.scratch_dir, quick=args.quick, vectors=vecs)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for vname, vres in summary["vectors"].items():
        print(f"[{vname}] ok={vres['ok']} seconds={vres['seconds']:.3f}")
    print(f"TOTAL ok={summary['ok']} mode={summary['mode']} workers={summary['workers']} seconds={summary['total_seconds']:.3f}")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
