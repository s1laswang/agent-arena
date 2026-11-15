"""Lossless working-memory transcript renderer for Canary SFT and HF evaluation.

Pure Python (no torch at import time, zero canary imports). Builds a bounded-length
working-memory prompt from (instruction, tools_spec, steps) using only public tool
inputs and outputs observed by the agent.
"""
from __future__ import annotations

from collections import Counter
import inspect
import json
import re
from typing import Any, Callable

from train.render import KICKOFF, _step_get, assistant_msg, parse_tool_call, to_openai_tools

INVESTIGATIVE_TOOLS: frozenset[str] = frozenset({
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
})

REQUIRED_PARAM_KEYS: tuple[str, ...] = (
    "n_days",
    "leak_damage",
    "canary_cost",
    "canaries_per_day",
    "max_variants",
    "delay_choices",
    "fingerprint_accuracy",
    "actions_per_day",
    "restrict_cost_per_day",
)

_DEFAULT_PARAMS: dict[str, Any] = {
    "n_days": 14,
    "leak_damage": 0.05,
    "canary_cost": 0.01,
    "canaries_per_day": 1,
    "max_variants": 3,
    "delay_choices": [1],
    "fingerprint_accuracy": 1.0,
    "actions_per_day": 8,
    "restrict_cost_per_day": 0.01,
    "wrong_accusation_score": -1.0,
    "tool_call_cap": 300,
}

_LIST_INT_KEYS = frozenset({"delay_choices", "docs_per_day"})
_BOOL_KEYS = frozenset({"decoy", "framing", "careful_mole", "access_constraints"})
_INT_KEYS = frozenset({
    "n_employees",
    "n_days",
    "canaries_per_day",
    "max_variants",
    "actions_per_day",
    "tool_call_cap",
    "leak_window_days",
    "canary_level",
    "search_max_results",
    "low_recipient_threshold",
})
_FLOAT_KEYS = frozenset({
    "p_leak",
    "leak_damage",
    "canary_cost",
    "restrict_cost_per_day",
    "log_rate_benign",
    "log_rate_mole",
    "interview_lr",
    "p_evasive_innocent",
    "p_after_hours_benign",
    "p_after_hours_mole",
    "framing_rate",
    "framing_decoy_share",
    "wrong_accusation_score",
    "p_single_dept_recipients",
    "doc_recipient_share",
    "fingerprint_accuracy",
    "noise",
})

_PARAM_LINE_RE = re.compile(r"^\s*-\s*([a-z][a-z0-9_]*)\s*:\s*(.+?)\s*$")
_N_EMP_RE = re.compile(r"company with (\d+) employees", re.I)
_EMP_NUM_RE = re.compile(r"^e(\d+)$")

_SHORT_TOOL_DESC: dict[str, str] = {
    "status": "Day, V, actions/calls left, restricted.",
    "list_employees": "List staff ids, depts, clearances.",
    "list_documents": "List docs in [day_from, day_to].",
    "read_access_logs": "Access logs for [day_from, day_to].",
    "search_messages": "Substring search messages.",
    "read_message": "Read message by id.",
    "interview": "Interview employee on topic.",
    "plant_canary": "Plant canary mapping emp->variant.",
    "check_leak_feed": "Surfaced leaked docs and variants.",
    "restrict_access": "Restrict employee from new docs.",
    "unrestrict_access": "Lift employee restriction.",
    "advance_day": "Close day and advance.",
    "accuse": "Accuse mole and end episode.",
}

_EVASIVE_CUES: tuple[str, ...] = (
    "couldn't tell you",
    "i guess",
    "is something missing",
    "don't really keep track",
    "skim most",
    "nothing worth mentioning",
    "depends what you count",
    "rather not",
    "keep a list",
    "busy. it's fine",
    "hard to say",
    "it varies",
    "another time",
    "whatever access i need",
    "haven't really looked",
    "is there a problem with",
)

_ANGRY_CUES: tuple[str, ...] = (
    "flat' raise",
    "flat raise",
    "goalposts",
    "burn out",
    "burnout",
    "doesn't deserve me",
    "updating my cv",
    "skipped for promotion",
    "done pretending",
    "nobody asks us",
    "pay here is a joke",
    "joke compared to the market",
    "fed up",
    "frustrated",
)


def _is_evasive(text: str) -> bool:
    low = text.lower()
    return any(cue in low for cue in _EVASIVE_CUES)


def _is_angry(text: str) -> bool:
    low = text.lower()
    return any(cue in low for cue in _ANGRY_CUES)


def parse_instruction_params(instruction: str) -> dict[str, Any]:
    params: dict[str, Any] = dict(_DEFAULT_PARAMS)
    params["delay_choices"] = list(_DEFAULT_PARAMS["delay_choices"])
    for line in instruction.splitlines():
        m = _PARAM_LINE_RE.match(line)
        if not m:
            continue
        key, raw = m.group(1), m.group(2).strip()
        try:
            if key in _LIST_INT_KEYS:
                vals = [int(x.strip()) for x in raw.split(",") if x.strip()]
                if vals:
                    params[key] = vals
            elif key in _BOOL_KEYS:
                params[key] = raw.lower() in {"on", "true", "1", "yes"}
            elif key in _INT_KEYS:
                params[key] = int(float(raw))
            elif key in _FLOAT_KEYS:
                params[key] = float(raw)
            else:
                params[key] = raw
        except ValueError:
            continue
    if "n_employees" not in params:
        m_emp = _N_EMP_RE.search(instruction)
        if m_emp:
            params["n_employees"] = int(m_emp.group(1))
    return params


def extract_public_ledger(instruction: str, steps: list) -> dict[str, Any]:
    params = parse_instruction_params(instruction)
    day = 1
    known_v = 1.0
    actions_today = 0
    employees: list[dict[str, Any]] = []
    restricted_set: set[str] = set()
    docs_by_id: dict[str, dict[str, Any]] = {}
    canaries_by_id: dict[str, dict[str, Any]] = {}
    raw_leaks: dict[tuple[str | None, str | None, int], dict[str, Any]] = {}
    logs_by_day_emp: dict[tuple[int, str], list[dict[str, Any]]] = {}
    interviews_by_key: dict[tuple[int, str, str], str] = {}
    msgs_by_id: dict[str, dict[str, Any]] = {}
    extra_emp_ids: set[str] = set()

    for step_idx, st in enumerate(steps):
        tool = _step_get(st, "tool")
        args = _step_get(st, "args")
        res = _step_get(st, "result")
        if not isinstance(args, dict):
            args = {}
        if not isinstance(res, dict) or not res.get("ok", True):
            continue
        data = res.get("data")
        if not isinstance(data, dict):
            data = {}

        if tool in INVESTIGATIVE_TOOLS:
            actions_today += 1

        if tool == "status":
            if "day" in data:
                day = int(data["day"])
            if "V" in data:
                known_v = float(data["V"])
            if "actions_left_today" in data:
                actions_today = max(0, int(params["actions_per_day"]) - int(data["actions_left_today"]))
            if isinstance(data.get("restricted"), list):
                restricted_set = {str(x) for x in data["restricted"]}
                extra_emp_ids.update(restricted_set)

        elif tool == "advance_day":
            if "day" in data:
                day = int(data["day"])
                actions_today = 0
            elif "closed_day" in data:
                day = int(data["closed_day"])
            if "V" in data:
                known_v = float(data["V"])

        elif tool == "list_employees":
            raw_emps = data.get("employees") or []
            employees = [
                {
                    "id": str(e["id"]),
                    "dept": str(e.get("dept", "")),
                    "clearance": e.get("clearance"),
                }
                for e in raw_emps
                if isinstance(e, dict) and "id" in e
            ]

        elif tool == "plant_canary":
            known_v = round(max(0.0, known_v - float(params["canary_cost"])), 10)
            cid = str(data.get("canary_id") or f"c{day}")
            asg = args.get("assignment") if isinstance(args.get("assignment"), dict) else {}
            variants: dict[str, list[str]] = {}
            for emp_id in sorted(asg):
                vlabel = str(asg[emp_id])
                eid = str(emp_id)
                variants.setdefault(vlabel, []).append(eid)
                extra_emp_ids.add(eid)
            title = str(args.get("doc_title", ""))
            canaries_by_id[cid] = {
                "canary_id": cid,
                "day": day,
                "title": title,
                "variants": variants,
            }
            docs_by_id[cid] = {
                "doc_id": cid,
                "day": day,
                "title": title,
                "is_canary": True,
                "recipients": sorted(str(k) for k in asg),
                "variants": variants,
            }

        elif tool == "list_documents":
            for d in data.get("documents") or []:
                if not isinstance(d, dict) or "doc_id" not in d:
                    continue
                did = str(d["doc_id"])
                recips = sorted(str(r) for r in (d.get("recipients") or []))
                extra_emp_ids.update(recips)
                is_c = bool(d.get("is_canary"))
                vmap: dict[str, list[str]] = {}
                if is_c:
                    for vk, vemps in (d.get("variants") or {}).items():
                        s_emps = sorted(str(x) for x in (vemps or []))
                        vmap[str(vk)] = s_emps
                        extra_emp_ids.update(s_emps)
                    prev_c = canaries_by_id.get(did)
                    canaries_by_id[did] = {
                        "canary_id": did,
                        "day": int(d.get("day", prev_c["day"] if prev_c else day)),
                        "title": str(d.get("title") or (prev_c["title"] if prev_c else "")),
                        "variants": vmap or (prev_c["variants"] if prev_c else {}),
                    }
                docs_by_id[did] = {
                    "doc_id": did,
                    "day": int(d.get("day", day)),
                    "title": str(d.get("title", "")),
                    "is_canary": is_c,
                    "recipients": recips,
                    "variants": vmap,
                }

        elif tool == "check_leak_feed":
            feed_items = data.get("items") if "items" in data else (data.get("leaks") or [])
            for it in feed_items or []:
                if not isinstance(it, dict):
                    continue
                did_raw = it.get("doc_id")
                did_str = str(did_raw) if did_raw is not None else None
                var_raw = it.get("variant")
                var_str = str(var_raw) if var_raw is not None else None
                sday = int(it.get("surfaced_day", day))
                raw_leaks[(did_str, var_str, sday)] = {
                    "doc_id": did_str,
                    "variant": var_str,
                    "surfaced_day": sday,
                }

        elif tool == "read_access_logs":
            rows = data.get("logs") if "logs" in data else (data.get("entries") or [])
            grouped: dict[tuple[int, str], list[dict[str, Any]]] = {}
            for r in rows or []:
                if not isinstance(r, dict) or "employee" not in r:
                    continue
                emp_r = str(r["employee"])
                day_r = int(r.get("day", step_idx + 1))
                extra_emp_ids.add(emp_r)
                grouped.setdefault((day_r, emp_r), []).append(r)
            for k_ge, grp in grouped.items():
                logs_by_day_emp[k_ge] = grp

        elif tool == "interview":
            emp_i = str(data.get("employee") or args.get("employee") or "")
            top_i = str(data.get("topic") or args.get("topic") or "")
            ans_i = str(data.get("answer") or "")
            if emp_i:
                extra_emp_ids.add(emp_i)
                interviews_by_key[(day, emp_i, top_i)] = ans_i

        elif tool == "search_messages":
            for m in data.get("messages") or []:
                if not isinstance(m, dict):
                    continue
                mid = str(m.get("id") or f"m_{step_idx}_{len(msgs_by_id)}")
                sender = str(m.get("sender") or "")
                if sender:
                    extra_emp_ids.add(sender)
                prev_m = msgs_by_id.get(mid, {})
                msgs_by_id[mid] = {**prev_m, **m}

        elif tool == "read_message":
            m = data.get("message")
            if isinstance(m, dict):
                mid = str(m.get("id") or f"m_{step_idx}_{len(msgs_by_id)}")
                sender = str(m.get("sender") or "")
                if sender:
                    extra_emp_ids.add(sender)
                prev_m = msgs_by_id.get(mid, {})
                msgs_by_id[mid] = {**prev_m, **m}

        elif tool == "restrict_access":
            re_emp = str(data.get("restricted") or args.get("employee") or "")
            if re_emp:
                restricted_set.add(re_emp)
                extra_emp_ids.add(re_emp)

        elif tool == "unrestrict_access":
            un_emp = str(data.get("unrestricted") or args.get("employee") or "")
            if un_emp:
                restricted_set.discard(un_emp)
                extra_emp_ids.add(un_emp)

    seen_emp_ids = [e["id"] for e in employees]
    seen_set = set(seen_emp_ids)
    all_emp_ids = seen_emp_ids + sorted(x for x in extra_emp_ids if x not in seen_set)
    all_emp_set = set(all_emp_ids)

    canaries = list(canaries_by_id.values())
    consistency_counts: dict[str, dict[str, Any]] = {
        eid: {
            "canary_hits": 0,
            "canary_misses": 0,
            "leaked_doc_hits": 0,
            "after_hours_logs": 0,
            "total_logs": 0,
            "evasive_interviews": 0,
            "angry_msgs": 0,
            "restricted": eid in restricted_set,
        }
        for eid in all_emp_ids
    }

    leaks: list[dict[str, Any]] = []
    for rl in raw_leaks.values():
        did = rl["doc_id"]
        var = rl["variant"]
        sday = rl["surfaced_day"]
        is_canary_leak = (
            var is not None
            or (did is not None and did in canaries_by_id)
            or bool(did is not None and docs_by_id.get(did, {}).get("is_canary"))
        )
        if did is not None and did in canaries_by_id:
            vmap = canaries_by_id[did]["variants"]
            if var is not None:
                cands = list(vmap.get(var, []))
            else:
                cands = sorted({e for es in vmap.values() for e in es})
        elif did is not None and did in docs_by_id:
            doc = docs_by_id[did]
            if doc.get("is_canary") and var is not None:
                cands = list((doc.get("variants") or {}).get(var, []))
            else:
                cands = list(doc.get("recipients") or [])
        elif did is None and var is not None and var in all_emp_set:
            cands = [var]
        else:
            cands = []

        leaks.append({
            "doc_id": did,
            "variant": var,
            "surfaced_day": sday,
            "candidate_emps": cands,
        })

        if cands:
            cand_set = set(cands)
            if is_canary_leak:
                for eid in all_emp_ids:
                    if eid in cand_set:
                        consistency_counts[eid]["canary_hits"] += 1
                    else:
                        consistency_counts[eid]["canary_misses"] += 1
            else:
                for eid in cands:
                    if eid in consistency_counts:
                        consistency_counts[eid]["leaked_doc_hits"] += 1

    for (_lday, eid), lrows in logs_by_day_emp.items():
        if eid in consistency_counts:
            consistency_counts[eid]["total_logs"] += len(lrows)
            consistency_counts[eid]["after_hours_logs"] += sum(1 for r in lrows if r.get("after_hours"))

    for (_iday, eid, _topic), ans in interviews_by_key.items():
        if eid in consistency_counts and _is_evasive(ans):
            consistency_counts[eid]["evasive_interviews"] += 1

    for m in msgs_by_id.values():
        sender = str(m.get("sender") or "")
        text = f"{m.get('subject') or ''} {m.get('body') or m.get('snippet') or ''}"
        if sender in consistency_counts and _is_angry(text):
            consistency_counts[sender]["angry_msgs"] += 1

    if all_emp_ids:
        min_misses = min(consistency_counts[eid]["canary_misses"] for eid in all_emp_ids)
        target_misses = 0 if min_misses == 0 else min_misses
        pool = [eid for eid in all_emp_ids if consistency_counts[eid]["canary_misses"] == target_misses]
        consistent_suspects = sorted(
            pool,
            key=lambda eid: (
                -consistency_counts[eid]["canary_hits"],
                -consistency_counts[eid]["leaked_doc_hits"],
                consistency_counts[eid]["angry_msgs"],
                -consistency_counts[eid]["after_hours_logs"],
                eid,
            ),
        )
    else:
        consistent_suspects = []

    known_v = round(known_v, 6)
    breakeven_p = round(1.0 / (1.0 + known_v), 4)

    out: dict[str, Any] = {
        "params": params,
        "day": day,
        "known_v": known_v,
        "breakeven_p": breakeven_p,
        "calls_used": len(steps),
        "actions_today": actions_today,
        "employees": employees,
        "canaries": canaries,
        "leaks": leaks,
        "consistency_counts": consistency_counts,
        "consistent_suspects": consistent_suspects,
    }
    for k in REQUIRED_PARAM_KEYS:
        out[k] = params[k]
    return out


def _shorten_desc(desc: str) -> str:
    s = " ".join((desc or "").split())
    if not s:
        return ""
    dot = s.find(".")
    if 0 < dot <= 60:
        return s[:dot + 1]
    return s[:60].rstrip()


def compact_tools_spec(tools_spec: list[dict]) -> list[dict]:
    norm = to_openai_tools(tools_spec)
    out: list[dict] = []
    for item in norm:
        fn = item["function"]
        name = fn["name"]
        desc = _SHORT_TOOL_DESC.get(name) or _shorten_desc(fn.get("description", ""))
        raw_params = fn.get("parameters") or {"type": "object", "properties": {}}
        raw_props = raw_params.get("properties") or {}
        props: dict[str, dict[str, Any]] = {}
        for pname, pschema in raw_props.items():
            if isinstance(pschema, dict):
                entry: dict[str, Any] = {"type": pschema.get("type", "string")}
                if "enum" in pschema:
                    entry["enum"] = list(pschema["enum"])
                props[pname] = entry
            else:
                props[pname] = {"type": "string"}
        cparams: dict[str, Any] = {"type": "object", "properties": props}
        req = raw_params.get("required")
        if req:
            cparams["required"] = list(req)
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": desc,
                "parameters": cparams,
            },
        })
    return out


def _fmt_emp_ids(ids: list[str], compress_ranges: bool = False) -> str:
    if not ids:
        return ""
    if not compress_ranges or len(ids) < 4:
        return ",".join(ids)
    nums: list[tuple[int, int, str]] = []
    for eid in ids:
        m = _EMP_NUM_RE.match(eid)
        if not m:
            return ",".join(ids)
        s_num = m.group(1)
        nums.append((int(s_num), len(s_num), eid))
    parts: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1][0] == nums[j][0] + 1:
            j += 1
        if j - i >= 2:
            parts.append(f"{nums[i][2]}..{nums[j][2]}")
        else:
            for k in range(i, j + 1):
                parts.append(nums[k][2])
        i = j + 1
    return ",".join(parts)


def compact_system_text(instruction: str, ledger: dict[str, Any] | None = None) -> str:
    p = (ledger or {}).get("params") or parse_instruction_params(instruction)
    delays = ",".join(str(x) for x in p.get("delay_choices", [1]))
    flags = []
    for fk in ("decoy", "framing", "careful_mole", "access_constraints"):
        if fk in p:
            flags.append(f"{fk}={'on' if p[fk] else 'off'}")
    flag_str = (", " + ", ".join(flags)) if flags else ""
    return (
        "Canary investigator: identify and accuse the single mole leaking sensitive documents.\n"
        f"Params: n_days={p['n_days']}, actions_per_day={p['actions_per_day']}, "
        f"cap={p.get('tool_call_cap', 300)}, leak_damage={p['leak_damage']:g}, "
        f"delay_choices=[{delays}], canary_cost={p['canary_cost']:g}, "
        f"canaries_per_day={p['canaries_per_day']}, max_variants={p['max_variants']}, "
        f"fingerprint_accuracy={p['fingerprint_accuracy']:g}, "
        f"restrict_cost_per_day={p['restrict_cost_per_day']:g}{flag_str}.\n"
        "Rules: status, list_employees, list_documents, advance_day, accuse are free; "
        "other tools use 1 daily action. Only the mole leaks held docs; decoy writes angry "
        "messages but is innocent; framing injects fake after-hours logs on others.\n"
        "Decision rule: Wrong accusation scores -1.0; abstaining to horizon scores 0.0; "
        "only accuse when suspect confidence exceeds break-even 1/(1+V).\n"
        "Protocol: Make exactly one tool call per turn as JSON: "
        "{\"name\": \"<tool>\", \"arguments\": {...}}."
    )


def compact_user_text(ledger: dict[str, Any]) -> str:
    p = ledger["params"]
    restricted_ids = sorted(
        eid for eid, c in ledger["consistency_counts"].items() if c.get("restricted")
    )
    lines = [
        KICKOFF,
        (
            f"STATE: day={ledger['day']}/{p['n_days']} known_v={ledger['known_v']:g} "
            f"breakeven_p={ledger['breakeven_p']:.4f} "
            f"calls={ledger['calls_used']}/{p.get('tool_call_cap', 300)} "
            f"actions_today={ledger['actions_today']}/{p['actions_per_day']} "
            f"restricted=[{','.join(restricted_ids)}]"
        ),
    ]

    emps = ledger["employees"]
    if emps:
        if len(emps) <= 20:
            emp_tokens = []
            for e in emps:
                tok = e["id"]
                if e.get("dept"):
                    tok += ":" + e["dept"][:3]
                if e.get("clearance") is not None:
                    tok += ":" + str(e["clearance"])
                emp_tokens.append(tok)
            lines.append(f"EMPLOYEES({len(emps)}): " + " ".join(emp_tokens))
        else:
            groups: dict[str, list[str]] = {}
            for e in emps:
                tag = (e["dept"][:3] if e.get("dept") else "Emp") + (
                    str(e["clearance"]) if e.get("clearance") is not None else ""
                )
                groups.setdefault(tag, []).append(e["id"])
            g_parts = [
                f"{tag}[{_fmt_emp_ids(eids, True)}]"
                for tag, eids in sorted(groups.items())
            ]
            lines.append(f"EMPLOYEES({len(emps)}): " + " ".join(g_parts))
    else:
        lines.append("EMPLOYEES(0): none")

    canaries = ledger["canaries"]
    if canaries:
        max_full = 2 if len(emps) > 20 else 3
        while max_full > 1 and sum(
            len(ve) for c in canaries[-max_full:] for ve in c["variants"].values()
        ) > 36:
            max_full -= 1
        older_n = max(0, len(canaries) - max_full)
        shown = canaries[-max_full:]
        c_parts = [f"+{older_n}older"] if older_n > 0 else []
        for c in shown:
            v_parts = [
                f"{vk}:{_fmt_emp_ids(vemps, True)}"
                for vk, vemps in sorted(c["variants"].items())
            ]
            c_parts.append(f"{c['canary_id']}@d{c['day']}{{{';'.join(v_parts)}}}")
        lines.append(f"CANARIES({len(canaries)}): " + " ".join(c_parts))
    else:
        lines.append("CANARIES(0): none")

    leaks = ledger["leaks"]
    if leaks:
        reg_indices = [i for i, lk in enumerate(leaks) if lk["variant"] is None]
        keep_full_reg = set(reg_indices[-1:] if len(reg_indices) > 2 else reg_indices)
        l_parts = []
        for idx, lk in enumerate(leaks):
            did = lk["doc_id"] if lk["doc_id"] is not None else "feed"
            if lk["variant"] is not None:
                cstr = _fmt_emp_ids(lk["candidate_emps"], True)
                l_parts.append(f"{did}@d{lk['surfaced_day']}:{lk['variant']}->[{cstr}]")
            elif idx in keep_full_reg and len(lk["candidate_emps"]) <= 14:
                cstr = _fmt_emp_ids(lk["candidate_emps"], True)
                l_parts.append(f"{did}@d{lk['surfaced_day']}:doc->[{cstr}]")
            else:
                l_parts.append(f"{did}@d{lk['surfaced_day']}:doc({len(lk['candidate_emps'])})")
        lines.append(f"LEAKS({len(leaks)}): " + " ".join(l_parts))
    else:
        lines.append("LEAKS(0): none")

    suspects = ledger["consistent_suspects"]
    counts = ledger["consistency_counts"]
    max_susp = 10 if len(emps) > 20 else 14
    if len(suspects) <= max_susp:
        susp_str = ",".join(suspects)
    else:
        susp_str = ",".join(suspects[:max_susp]) + f",+{len(suspects) - max_susp}more"
    lines.append(f"CONSISTENT_SUSPECTS({len(suspects)}): [{susp_str}]")
    if suspects:
        top_k = 4 if len(emps) > 20 else 5
        top_parts = []
        for eid in suspects[:top_k]:
            c = counts[eid]
            top_parts.append(
                f"{eid}(ch={c['canary_hits']},cm={c['canary_misses']},"
                f"dh={c['leaked_doc_hits']},ah={c['after_hours_logs']}/{c['total_logs']},"
                f"ev={c['evasive_interviews']},ang={c['angry_msgs']},"
                f"r={1 if c['restricted'] else 0})"
            )
        lines.append("SUSPECT_COUNTS: " + " ".join(top_parts))

    angry = [
        f"{eid}:{c['angry_msgs']}"
        for eid, c in sorted(counts.items())
        if c["angry_msgs"] > 0
    ]
    if angry:
        lines.append("ANGRY_SENDERS: " + ",".join(angry))

    return "\n".join(lines)


def compact_tool_content(tool: str, result: dict, max_chars: int = 220) -> str:
    if not isinstance(result, dict):
        return "{}"
    if not result.get("ok", True):
        return json.dumps({"error": result.get("error") or "error"}, separators=(",", ":"))
    data = result.get("data")
    if not isinstance(data, dict):
        data = {}

    if tool == "status":
        cp = data.get("canaries_planted") or []
        body: Any = {
            "V": data.get("V"),
            "actions_left_today": data.get("actions_left_today"),
            "day": data.get("day"),
            "n_canaries": len(cp),
            "restricted": data.get("restricted") or [],
            "tool_calls_left": data.get("tool_calls_left"),
        }
    elif tool == "list_employees":
        emps = data.get("employees") or []
        body = {"n_employees": len(emps)}
    elif tool == "list_documents":
        docs = data.get("documents") or []
        body = {
            "n_docs": len(docs),
            "doc_ids": [d.get("doc_id") for d in docs[-8:] if isinstance(d, dict)],
        }
    elif tool == "read_access_logs":
        logs = data.get("logs") if "logs" in data else (data.get("entries") or [])
        ah = Counter(
            str(r["employee"])
            for r in (logs or [])
            if isinstance(r, dict) and r.get("employee") and r.get("after_hours")
        )
        body = {"n_logs": len(logs or []), "after_hours_top": dict(ah.most_common(6))}
    elif tool == "check_leak_feed":
        items = data.get("items") if "items" in data else (data.get("leaks") or [])
        body = {
            "leaks": [
                {
                    "doc_id": x.get("doc_id"),
                    "variant": x.get("variant"),
                    "surfaced_day": x.get("surfaced_day"),
                }
                for x in (items or [])[-5:]
                if isinstance(x, dict)
            ]
        }
    elif tool == "search_messages":
        msgs = data.get("messages") or []
        body = {
            "n_msgs": len(msgs),
            "hits": [
                {"id": m.get("id"), "sender": m.get("sender")}
                for m in msgs[:6]
                if isinstance(m, dict)
            ],
        }
    else:
        body = data

    s = json.dumps(body, separators=(",", ":"), sort_keys=True, default=str)
    if len(s) > max_chars:
        s = s[:max_chars] + "...[truncated]"
    return s


_SPECIAL_TAG_RE = re.compile(r"<\|im_start\|>|<\|im_end\|>")
_TOK_UNIT_RE = re.compile(r"[A-Za-z]+|\d|[^\sA-Za-z\d]{1,2}")


def estimate_compact_tokens(text: str) -> int:
    specials = len(_SPECIAL_TAG_RE.findall(text))
    rem = _SPECIAL_TAG_RE.sub(" ", text)
    return specials + int(0.93 * len(_TOK_UNIT_RE.findall(rem)))


def _build_tail_messages(steps: list, tail_turns: int) -> list[dict]:
    tail = steps[-tail_turns:] if tail_turns > 0 else []
    out: list[dict] = []
    for st in tail:
        tname = _step_get(st, "tool")
        targs = _step_get(st, "args")
        tres = _step_get(st, "result")
        out.append(assistant_msg(tname, targs if isinstance(targs, dict) else {}))
        out.append({
            "role": "tool",
            "name": tname,
            "content": compact_tool_content(tname, tres),
        })
    return out


def render_compact_messages(instruction: str, steps: list, tail_turns: int = 6) -> list[dict]:
    ledger = extract_public_ledger(instruction, steps)
    base: list[dict] = [
        {"role": "system", "content": compact_system_text(instruction, ledger)},
        {"role": "user", "content": compact_user_text(ledger)},
    ]
    return base + _build_tail_messages(steps, tail_turns)


render_compact_step_prompt = render_compact_messages


def render_compact_turn(
    instruction: str,
    tools_spec: list[dict],
    history_prefix: list,
    target_step=None,
    tail_turns: int = 4,
    max_prompt_chars: int = 7000,
    max_prompt_tokens: int = 1680,
) -> dict[str, Any]:
    ctools = compact_tools_spec(tools_spec)
    ledger = extract_public_ledger(instruction, history_prefix)
    base: list[dict] = [
        {"role": "system", "content": compact_system_text(instruction, ledger)},
        {"role": "user", "content": compact_user_text(ledger)},
    ]
    target_msgs: list[dict] = []
    if target_step is not None:
        tname = _step_get(target_step, "tool")
        targs = _step_get(target_step, "args")
        target_msgs.append(assistant_msg(tname, targs if isinstance(targs, dict) else {}))

    t_turns = tail_turns
    while True:
        msgs = base + _build_tail_messages(history_prefix, t_turns) + target_msgs
        rec = {"messages": msgs, "tools": ctools}
        if t_turns <= 0:
            return rec
        txt = render_compact_prompt_text(rec, add_generation_prompt=(target_step is None))
        if len(txt) <= max_prompt_chars and estimate_compact_tokens(txt) <= max_prompt_tokens:
            return rec
        t_turns -= 1


def render_compact_episode_turns(
    ep,
    instruction: str,
    tools_spec: list[dict],
    tail_turns: int = 4,
) -> list[dict[str, Any]]:
    g = (lambda k: ep[k]) if isinstance(ep, dict) else (lambda k: getattr(ep, k))
    steps = list(g("steps"))
    ctools = compact_tools_spec(tools_spec)
    out: list[dict[str, Any]] = []
    for idx, st in enumerate(steps):
        turn = render_compact_turn(
            instruction,
            ctools,
            steps[:idx],
            target_step=st,
            tail_turns=tail_turns,
        )
        out.append({
            "tier": g("tier"),
            "seed": g("seed"),
            "agent": g("agent"),
            "score": g("score"),
            "correct": g("correct"),
            "final_day": g("final_day"),
            "end_reason": g("end_reason"),
            "step_index": idx,
            "target_tool": _step_get(st, "tool"),
            "tools": ctools,
            "messages": turn["messages"],
        })
    return out


def render_compact_prompt_text(turn: dict[str, Any], add_generation_prompt: bool = False) -> str:
    tools = turn.get("tools") or []
    msgs = turn.get("messages") or []
    parts: list[str] = []
    if tools:
        sys_content = msgs[0]["content"] if msgs and msgs[0]["role"] == "system" else ""
        t_lines = "\n".join(json.dumps(t, separators=(",", ":")) for t in tools)
        parts.append(
            "<|im_start|>system\n"
            + sys_content
            + "\n\nTools:\n<tools>\n"
            + t_lines
            + "\n</tools><|im_end|>\n"
        )
        start_idx = 1 if msgs and msgs[0]["role"] == "system" else 0
    else:
        start_idx = 0

    for m in msgs[start_idx:]:
        role = m["role"]
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function", tc)
                payload = json.dumps(
                    {"name": fn["name"], "arguments": fn.get("arguments", {})},
                    separators=(",", ":"),
                )
                calls.append(f"<tool_call>\n{payload}\n</tool_call>")
            parts.append("<|im_start|>assistant\n" + "\n".join(calls) + "<|im_end|>\n")
        elif role == "tool":
            parts.append(
                f"<|im_start|>user\n<tool_response>\n{m.get('content', '')}\n</tool_response><|im_end|>\n"
            )
        else:
            parts.append(f"<|im_start|>{role}\n{m.get('content', '')}<|im_end|>\n")

    if add_generation_prompt:
        parts.append("<|im_start|>assistant\n")
    return "".join(parts)


def compact_turn_window(
    rec: dict[str, Any],
    tokenizer,
    max_len: int = 2048,
) -> list[tuple[list[int], list[int], list[bool]]]:
    msgs = rec["messages"]
    if not msgs or msgs[-1].get("role") != "assistant":
        return []
    tools = rec.get("tools")
    full = tokenizer.apply_chat_template(
        msgs, tools=tools, tokenize=False, add_generation_prompt=False
    )
    prefix = tokenizer.apply_chat_template(
        msgs[:-1], tools=tools, tokenize=False, add_generation_prompt=True
    )
    enc = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    ids = list(enc["input_ids"])
    if len(ids) > max_len:
        return []
    offsets = [tuple(o) for o in enc["offset_mapping"]]
    body_start = len(prefix)
    lo, hi = 0, len(offsets)
    while lo < hi:
        mid = (lo + hi) // 2
        if offsets[mid][0] < body_start:
            lo = mid + 1
        else:
            hi = mid
    if lo >= len(ids):
        return []
    labels = [-100] * lo + ids[lo:]
    is_acc = any(
        c.get("function", {}).get("name") == "accuse"
        for c in (msgs[-1].get("tool_calls") or [])
    )
    acc_mask = [False] * lo + ([is_acc] * (len(ids) - lo))
    return [(ids, labels, acc_mask)]


def _common_prefix(a: list[int], b: list[int]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


class CompactHFPolicy:
    def __init__(
        self,
        model=None,
        tokenizer=None,
        name: str = "compact_hf",
        max_ctx: int = 2048,
        max_new: int = 96,
        tail_turns: int = 4,
        kv_reuse: bool = True,
        generator: Callable | None = None,
    ):
        if generator is None and callable(model) and tokenizer is None:
            generator = model
            model = None
        self.model = model
        self.tok = tokenizer
        self.name = name
        self.max_ctx = max_ctx
        self.max_new = max_new
        self.tail_turns = tail_turns
        self.kv_reuse = kv_reuse
        self.generator = generator
        self.raw_tools_spec: list[dict] = []
        self.tools: list[dict] = []
        self.tool_names: set[str] = set()
        self.instruction = ""
        self.invalid = 0
        self.calls = 0
        self.cache = None
        self.cache_ids: list[int] = []
        self.encoded = 0
        self.reused = 0

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self.raw_tools_spec = list(tools_spec)
        self.tools = compact_tools_spec(tools_spec)
        self.tool_names = {t["function"]["name"] for t in self.tools}
        self.instruction = instruction
        self.invalid = 0
        self.calls = 0
        self.cache = None
        self.cache_ids = []
        self.encoded = 0
        self.reused = 0

    def _ids(self, msgs: list[dict]) -> list[int]:
        ids = self.tok.apply_chat_template(
            msgs,
            tools=self.tools,
            tokenize=True,
            add_generation_prompt=True,
        )
        if hasattr(ids, "keys"):
            ids = ids["input_ids"]
        return list(ids)

    def _prompt_ids(self, history: list) -> list[int]:
        t_turns = self.tail_turns
        while True:
            msgs = render_compact_messages(self.instruction, history, tail_turns=t_turns)
            ids = self._ids(msgs)
            if len(ids) <= self.max_ctx - self.max_new or t_turns <= 0:
                return ids
            t_turns -= 1

    def _invoke_generator(self, turn: dict[str, Any], history: list) -> str:
        assert self.generator is not None
        try:
            sig = inspect.signature(self.generator)
            pos = [
                p
                for p in sig.parameters.values()
                if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]
            has_var = any(
                p.kind == inspect.Parameter.VAR_POSITIONAL
                for p in sig.parameters.values()
            )
            if has_var and len(pos) <= 1:
                return str(self.generator(turn))
            if len(pos) == 0:
                return str(self.generator())
            if len(pos) == 1:
                return str(self.generator(turn))
            if len(pos) == 2:
                return str(self.generator(turn["messages"], turn["tools"]))
            return str(self.generator(turn["messages"], turn["tools"], history))
        except (TypeError, ValueError):
            return str(self.generator(turn))

    def generate_text(self, history: list) -> str:
        if self.generator is not None:
            turn = render_compact_turn(
                self.instruction,
                self.tools,
                history,
                target_step=None,
                tail_turns=self.tail_turns,
            )
            return self._invoke_generator(turn, history)

        import torch

        ids = self._prompt_ids(history)
        keep = _common_prefix(self.cache_ids, ids) if (self.kv_reuse and self.cache is not None) else 0
        keep = min(keep, max(len(ids) - 1, 0))
        if keep > 0:
            self.cache.crop(keep)
        else:
            from transformers import DynamicCache

            self.cache = DynamicCache() if self.kv_reuse else None
        self.reused += keep
        self.encoded += len(ids) - keep
        x = torch.tensor([ids], device=self.model.device)
        with torch.no_grad():
            out = self.model.generate(
                input_ids=x,
                attention_mask=torch.ones_like(x),
                past_key_values=self.cache,
                use_cache=True,
                max_new_tokens=self.max_new,
                do_sample=False,
                pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id,
            )
        seq = out[0].tolist()
        if self.kv_reuse and self.cache is not None:
            self.cache_ids = seq[:self.cache.get_seq_length()]
        return self.tok.decode(seq[len(ids):], skip_special_tokens=False)

    def act(self, history: list) -> tuple[str, dict[str, Any]]:
        self.calls += 1
        call = parse_tool_call(self.generate_text(history), self.tool_names)
        if call is None:
            self.invalid += 1
            return "status", {}
        return call
