from __future__ import annotations

import argparse
import copy
import json
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pydantic import BaseModel, Field, ValidationError

from canary.agents._common import get, inline_schema
from canary.agents.world_builder import TRUTH_KEYS, TRUTH_WORDS, assert_no_truth
from canary.gemini import lab_client
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import TemplateProvider

REPO = Path(__file__).resolve().parents[2]
FEATURE = "live_events"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_DAYS = (3, 6, 10)
EVENT_CATEGORIES = (
    "compliance_audit",
    "vendor_offboarding",
    "access_reorganization",
    "press_rumor",
)
_DECOY_NOISE = (
    "promotion",
    "raise",
    "deserve",
    "burn out",
    "recruiter",
    "goalposts",
    "nobody asks",
    "updating my cv",
    "angry",
    "unfair",
    "furious",
    "sick of",
    "quit",
    "ridiculous",
    "fed up",
    "hate",
)
_PREFERRED_ROLES = (
    "compliance officer",
    "counsel",
    "controller",
    "tech lead",
    "sales manager",
    "research lead",
    "director",
    "manager",
    "lead",
)

SYSTEM_PROMPT = (
    "You generate realistic mid-episode corporate incident updates ('new information arrives') "
    "for a workplace simulation using ONLY the public company, department, employee, and document "
    "facts provided in the user JSON.\n"
    "Valid category values: compliance_audit, vendor_offboarding, access_reorganization, press_rumor. "
    "Prefer suggested_category when given.\n"
    "Rules:\n"
    "1. bulletin.sender and every reactions[i].sender MUST be an exact employee id from employees.\n"
    "2. bulletin.channel MUST be 'email' or '#announcements'.\n"
    "3. Provide 3 reactions using exact channel names from department_channels and distinct employee ids.\n"
    "4. Each reaction body MUST be a complete, natural 1-2 sentence workplace Slack reply.\n"
    "5. affected_departments MUST list 1 to 3 exact names from departments.\n"
    "6. referenced_documents MUST list 0 to 3 exact document title strings from documents_up_to_day.\n"
    "7. Never mention moles, spies, traitors, culprits, informants, double agents, insider threats, "
    "leaking, selling documents, or confessions.\n"
    "8. Keep tone operational and professional. Do not write disgruntled rants or use the words "
    "promotion, raise, deserve, burn out, recruiter, goalposts, nobody asks, updating my cv, "
    "angry, unfair, furious, sick of, quit, ridiculous, fed up, or hate (say 'open a ticket' instead of 'raise a ticket').\n"
    "9. Use plain ASCII hyphens ('-'), never em dashes or en dashes. Output valid JSON only."
)


class ReactionDraft(BaseModel):
    sender: str = Field(description="Exact employee id from employees, e.g. e04")
    channel: str = Field(description="Exact Slack channel from department_channels, e.g. #engineering")
    body: str = Field(max_length=500, description="Complete 1-2 sentence operational Slack reaction")


class BulletinDraft(BaseModel):
    sender: str = Field(description="Exact employee id from employees, e.g. e03")
    channel: str = Field(description="Either 'email' or '#announcements'")
    subject: str = Field(max_length=200, description="Concise corporate incident subject line")
    body: str = Field(max_length=1000, description="2-4 sentence internal corporate incident bulletin")


class IncidentEventDraft(BaseModel):
    category: str = Field(description="One of compliance_audit, vendor_offboarding, access_reorganization, press_rumor")
    headline: str = Field(max_length=240, description="Concise corporate incident headline")
    summary: str = Field(max_length=600, description="1-2 sentence factual summary of the incident")
    affected_departments: list[str] = Field(description="1 to 3 exact department names from departments")
    referenced_documents: list[str] = Field(description="0 to 3 exact document title strings from documents_up_to_day")
    bulletin: BulletinDraft
    reactions: list[ReactionDraft] = Field(description="3 workplace Slack reactions from distinct employee ids")


def _clean_text(s: Any) -> str:
    txt = str(s or "").replace("\u2014", " - ").replace("\u2013", " - ")
    return re.sub(r"[ \t]+", " ", txt).strip()


def _is_placeholder(s: str) -> bool:
    low = s.strip().lower()
    return not low or low in {"stub", "x", "todo", "tbd", "none", "n/a"}


def _is_bad_prose(s: str) -> bool:
    if _is_placeholder(s):
        return True
    low = s.strip().lower()
    if len(low) < 10 or low == "wait" or low.startswith(("wait,", "wait -", "wait ")):
        return True
    return "#<" in low or "channel must be" in low


def _has_truth_or_lint_issue(s: str) -> bool:
    if not s:
        return False
    return bool(TRUTH_WORDS.search(s) or lint_text(s))


def _has_decoy_noise(s: str) -> bool:
    low = s.lower()
    return any(tok in low for tok in _DECOY_NOISE)


def _walk_strings(obj: Any):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_strings(item)


def _all_keys(obj: Any):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _all_keys(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _all_keys(item)


def _seed_hint(env_or_public_facts: Any) -> int:
    if isinstance(env_or_public_facts, dict):
        if env_or_public_facts and all(isinstance(k, int) for k in env_or_public_facts):
            first = next(iter(env_or_public_facts.values()))
            return _seed_hint(first)
        val = env_or_public_facts.get("seed", 0)
        return int(val) if isinstance(val, int) else 0
    if isinstance(env_or_public_facts, (list, tuple)) and env_or_public_facts:
        return _seed_hint(env_or_public_facts[0])
    val = getattr(env_or_public_facts, "seed", 0)
    return int(val) if isinstance(val, int) else 0


def _extract_employees(raw_emps: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for emp in raw_emps or ():
        eid = get(emp, "id")
        if not isinstance(eid, str) or not eid or eid in seen:
            continue
        seen.add(eid)
        entry: dict[str, Any] = {
            "id": eid,
            "name": _clean_text(get(emp, "name") or eid),
            "dept": _clean_text(get(emp, "dept") or "Operations"),
            "role": _clean_text(get(emp, "role") or "analyst"),
        }
        clearance = get(emp, "clearance")
        if isinstance(clearance, int) and not isinstance(clearance, bool):
            entry["clearance"] = clearance
        out.append(entry)
    return out


def _extract_docs_up_to_day(raw_docs: Any, day: int, emp_ids: set[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, doc in enumerate(raw_docs or ()):
        if bool(get(doc, "is_canary", False)):
            continue
        doc_day_raw = get(doc, "day", 1)
        doc_day = int(doc_day_raw) if isinstance(doc_day_raw, int) else 1
        if doc_day > day:
            continue
        title = _clean_text(get(doc, "title") or "")
        if not title or _has_truth_or_lint_issue(title):
            continue
        doc_id = _clean_text(get(doc, "doc_id") or f"d{doc_day}-{idx + 1}")
        key = f"{doc_id}:{title}:{doc_day}"
        if key in seen:
            continue
        seen.add(key)
        recips = [r for r in (get(doc, "recipients") or ()) if isinstance(r, str) and (not emp_ids or r in emp_ids)]
        out.append({"doc_id": doc_id, "title": title, "day": doc_day, "recipients": recips})
    return out[:48]


def public_day_facts_view(env_or_public_facts: Any, day: int) -> dict[str, Any]:
    day = int(day)
    if isinstance(env_or_public_facts, dict) and env_or_public_facts and all(isinstance(k, int) for k in env_or_public_facts):
        chosen = env_or_public_facts.get(day)
        if chosen is None:
            earlier = [k for k in sorted(env_or_public_facts) if k <= day]
            chosen = env_or_public_facts[earlier[-1] if earlier else sorted(env_or_public_facts)[0]]
        return public_day_facts_view(chosen, day)

    if isinstance(env_or_public_facts, (list, tuple)):
        if not env_or_public_facts:
            raise ValueError("empty public facts sequence")
        exact = next((x for x in env_or_public_facts if get(x, "day") == day), None)
        base = exact if exact is not None else env_or_public_facts[0]
        emps = _extract_employees(get(base, "employees"))
        emp_ids = {e["id"] for e in emps}
        merged_docs: list[Any] = []
        for item in env_or_public_facts:
            merged_docs.extend(get(item, "docs") or ())
        docs = _extract_docs_up_to_day(merged_docs, day, emp_ids)
        depts = sorted({e["dept"] for e in emps if e.get("dept")} | set(get(base, "depts") or ()))
        return {
            "company": _clean_text(get(base, "company") or "Northwind Analytics"),
            "tier": _clean_text(get(base, "tier") or "medium"),
            "day": day,
            "departments": depts or ["Operations"],
            "employees": emps,
            "documents_up_to_day": docs,
        }

    world_obj = getattr(env_or_public_facts, "_world", None)
    if world_obj is not None:
        emps = _extract_employees(getattr(world_obj, "employees", ()))
        emp_ids = {e["id"] for e in emps}
        raw_docs: list[Any] = list(getattr(env_or_public_facts, "docs", ()) or ())
        planned = getattr(world_obj, "planned_docs", None) or {}
        for d_key in sorted(planned):
            if int(d_key) <= day:
                raw_docs.extend(planned[d_key])
        docs = _extract_docs_up_to_day(raw_docs, day, emp_ids)
        depts = sorted({e["dept"] for e in emps if e.get("dept")})
        return {
            "company": _clean_text(getattr(world_obj, "company", None) or "Northwind Analytics"),
            "tier": _clean_text(getattr(env_or_public_facts, "tier", None) or "medium"),
            "day": day,
            "departments": depts or ["Operations"],
            "employees": emps,
            "documents_up_to_day": docs,
        }

    call_fn = getattr(env_or_public_facts, "call", None)
    if callable(call_fn) and get(env_or_public_facts, "employees") is None:
        emp_res = call_fn("list_employees", {})
        emp_data = get(emp_res, "data") or {}
        emps = _extract_employees(get(emp_data, "employees"))
        emp_ids = {e["id"] for e in emps}
        doc_res = call_fn("list_documents", {"day_from": 1, "day_to": day})
        doc_data = get(doc_res, "data") or {}
        docs = _extract_docs_up_to_day(get(doc_data, "documents"), day, emp_ids)
        depts = sorted({e["dept"] for e in emps if e.get("dept")})
        return {
            "company": _clean_text(get(env_or_public_facts, "company") or "Northwind Analytics"),
            "tier": _clean_text(get(env_or_public_facts, "tier") or "medium"),
            "day": day,
            "departments": depts or ["Operations"],
            "employees": emps,
            "documents_up_to_day": docs,
        }

    emps = _extract_employees(get(env_or_public_facts, "employees"))
    emp_ids = {e["id"] for e in emps}
    raw_docs = get(env_or_public_facts, "docs") or get(env_or_public_facts, "documents_up_to_day") or ()
    docs = _extract_docs_up_to_day(raw_docs, day, emp_ids)
    raw_depts = get(env_or_public_facts, "departments") or get(env_or_public_facts, "depts") or ()
    depts = sorted({e["dept"] for e in emps if e.get("dept")} | {_clean_text(d) for d in raw_depts if _clean_text(d)})
    return {
        "company": _clean_text(get(env_or_public_facts, "company") or "Northwind Analytics"),
        "tier": _clean_text(get(env_or_public_facts, "tier") or "medium"),
        "day": day,
        "departments": depts or ["Operations"],
        "employees": emps,
        "documents_up_to_day": docs,
    }


def resolve_live_events_client(llm: Any = f"gemini:{DEFAULT_MODEL}", run_id: str = "", **kw):
    if not isinstance(llm, str):
        return llm
    spec = llm.strip()
    if not spec:
        spec = f"gemini:{DEFAULT_MODEL}"
    elif spec != "stub" and not spec.startswith(("stub:", "gemini:", "openai:")):
        spec = f"gemini:{spec}"
    return lab_client(spec, feature=FEATURE, run_id=run_id, **kw)


def _first_name(emp: dict[str, Any]) -> str:
    name = emp.get("name") or emp["id"]
    return str(name).split()[0]


def _pick_bulletin_sender(employees: list[dict[str, Any]], rng: random.Random) -> dict[str, Any]:
    for role_kw in _PREFERRED_ROLES:
        matches = [e for e in employees if role_kw in e.get("role", "").lower()]
        if matches:
            return rng.choice(matches)
    return rng.choice(employees)


def _fallback_components(pub: dict[str, Any], category: str, rng: random.Random) -> dict[str, Any]:
    emps = pub["employees"]
    depts = pub["departments"]
    docs = pub["documents_up_to_day"]
    day = int(pub["day"])
    company = pub["company"]

    dept1 = rng.choice(depts)
    other_depts = [d for d in depts if d != dept1]
    dept2 = rng.choice(other_depts) if other_depts else dept1
    affected = [dept1] if dept2 == dept1 else [dept1, dept2]

    chosen_doc = rng.choice(docs) if docs else None
    doc_title = chosen_doc["title"] if chosen_doc else f"the {dept1} quarterly operating plan"
    ref_docs = [chosen_doc["title"]] if chosen_doc else []

    lead_emp = _pick_bulletin_sender(emps, rng)
    lead_first = _first_name(lead_emp)
    pool = [e for e in emps if e["id"] != lead_emp["id"]] or list(emps)
    dept_pool = [e for e in pool if e["dept"] in affected] or pool
    reactors = rng.sample(dept_pool, k=min(3, len(dept_pool)))
    if len(reactors) < 2 and len(pool) >= 2:
        extra = [e for e in pool if e["id"] not in {r["id"] for r in reactors}]
        reactors.extend(extra[: 2 - len(reactors)])
    peer_first = _first_name(reactors[-1]) if reactors else lead_first

    if category == "compliance_audit":
        headline = f"Day {day} compliance record audit for {dept1}"
        summary = f"{company} opened a scheduled compliance verification covering {dept1} retention tags and folder checklists."
        b_chan = "#announcements"
        b_subj = f"[Compliance] Day {day} retention verification for {dept1}"
        b_body = (
            f"All {dept1} and {dept2} contributors: external compliance reviewers requested retention tag "
            f"confirmation on {doc_title} by end of Day {day + 1}. Please update the checklist in the shared "
            f"audit folder and open an IT ticket for archived copies."
        )
        r_bodies = [
            f"Checked our {dept1} folder metadata on {doc_title}; retention labels match the checklist.",
            f"Thanks {lead_first}, syncing with {peer_first} so {dept2} sign-off finishes before tomorrow's cutoff.",
            f"Audit tracker row for {doc_title} is marked verified on our side.",
        ]
    elif category == "vendor_offboarding":
        headline = f"Vendor offboarding notice affecting {dept1} integrations"
        summary = f"{company} concluded a third-party contractor engagement on Day {day} and rotated shared integration tokens."
        b_chan = "email"
        b_subj = f"[Ops Notice] Contractor offboarding and token rotation for {dept1}"
        b_body = (
            f"Operations update for {dept1}: our external contractor engagement concluded today. Shared service "
            f"credentials tied to {doc_title} workflows were rotated at noon; move active exports to internal drives."
        )
        r_bodies = [
            f"Switched our {dept1} sync job to the rotated internal credential; {doc_title} pipeline ran cleanly.",
            f"Confirmed no external contractor webhooks remain enabled in the {dept2} workspace.",
            f"Thanks {lead_first}, archived the vendor handoff checklist in the {dept1} folder.",
        ]
    elif category == "access_reorganization":
        headline = f"Workspace permission alignment across {dept1} and {dept2}"
        summary = f"{company} reorganized shared project folder boundaries between {dept1} and {dept2} on Day {day}."
        b_chan = "#announcements"
        b_subj = f"[IT Update] {dept1} and {dept2} workspace alignment"
        b_body = (
            f"Starting Day {day}, shared folders supporting {doc_title} are consolidated under the aligned "
            f"{dept1}-{dept2} workspace. Standard role groups carry over automatically; open a helpdesk ticket if "
            f"any bookmark needs remapping."
        )
        r_bodies = [
            f"Located {doc_title} under the updated {dept1} workspace path and refreshed team bookmarks.",
            f"{peer_first} and I verified read permissions for {dept2} reviewers on the consolidated folder.",
            f"Migration looks clean from {dept1}, folder sync finished in two minutes.",
        ]
    else:
        headline = f"Trade-press report on rival product bundling near {dept1}"
        summary = f"Industry press published Day {day} speculation on market bundling shifts, prompting a calm internal review at {company}."
        b_chan = "email"
        b_subj = f"[Comms Brief] Industry press rumor and {dept1} talking points"
        b_body = (
            f"Team note: trade media ran an unconfirmed article today regarding competing enterprise bundles. "
            f"Route external media questions to comms and keep {doc_title} delivery assumptions unchanged pending review."
        )
        r_bodies = [
            f"Noted for {dept1} customer briefings today; sticking strictly to our published product sheet.",
            f"Reviewed {doc_title} timeline with {peer_first}, no schedule adjustments needed from that article.",
            f"Forwarded one inbound analyst question to the comms alias per protocol.",
        ]

    reactions_out = []
    for idx, emp in enumerate(reactors):
        reactions_out.append({
            "sender": emp["id"],
            "channel": f"#{emp['dept'].lower()}",
            "body": r_bodies[idx % len(r_bodies)],
        })

    return {
        "category": category,
        "headline": headline,
        "summary": summary,
        "affected_departments": affected,
        "referenced_documents": ref_docs,
        "bulletin": {
            "sender": lead_emp["id"],
            "channel": b_chan,
            "subject": b_subj,
            "body": b_body,
        },
        "reactions": reactions_out,
    }


def _usage_from_response(resp: Any) -> dict[str, Any]:
    raw = getattr(resp, "raw", None) if not isinstance(resp, dict) else resp.get("raw")
    um = getattr(raw, "usage_metadata", None) if raw is not None else None
    usage_dict = getattr(resp, "usage", None) if not isinstance(resp, dict) else resp.get("usage")
    usage_dict = usage_dict if isinstance(usage_dict, dict) else {}
    if um is not None:
        tin = int(getattr(um, "prompt_token_count", 0) or 0)
        cand_out = int(getattr(um, "candidates_token_count", 0) or 0)
        thinking = int(getattr(um, "thoughts_token_count", 0) or 0)
        cached = int(getattr(um, "cached_content_token_count", 0) or 0)
    else:
        tin = int(usage_dict.get("in", 0) or 0)
        cand_out = int(usage_dict.get("out", 0) or 0)
        thinking = int(usage_dict.get("thinking", 0) or 0)
        cached = int(usage_dict.get("cached", 0) or 0)
    cost_usd = float(usage_dict.get("cost_usd", 0.0) or 0.0)
    return {
        "in": tin,
        "out": cand_out,
        "thinking": thinking,
        "cached": cached,
        "total_tokens": tin + cand_out + thinking,
        "cost_usd": round(cost_usd, 6),
    }


def _build_canonical_messages(
    day: int,
    employees: list[dict[str, Any]],
    bulletin_spec: dict[str, str],
    reaction_specs: list[dict[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    emp_by_id = {e["id"]: e for e in employees}
    all_ids = [e["id"] for e in employees]

    b_sender = bulletin_spec["sender"]
    b_recipients = [eid for eid in all_ids if eid != b_sender] or [b_sender]
    bulletin_msg = {
        "id": f"ev{day}-0",
        "day": day,
        "channel": bulletin_spec["channel"],
        "sender": b_sender,
        "recipients": b_recipients,
        "subject": bulletin_spec["subject"],
        "body": bulletin_spec["body"],
    }

    reaction_msgs: list[dict[str, Any]] = []
    for idx, r_spec in enumerate(reaction_specs, start=1):
        r_sender = r_spec["sender"]
        r_chan = r_spec["channel"]
        dept_low = r_chan.lstrip("#").lower()
        dept_peers = [e["id"] for e in employees if e["dept"].lower() == dept_low and e["id"] != r_sender]
        if not dept_peers:
            sender_dept = emp_by_id[r_sender]["dept"].lower()
            dept_peers = [e["id"] for e in employees if e["dept"].lower() == sender_dept and e["id"] != r_sender]
        r_recipients = dept_peers or ([eid for eid in all_ids if eid != r_sender] or [r_sender])
        reaction_msgs.append({
            "id": f"ev{day}-{idx}",
            "day": day,
            "channel": r_chan,
            "sender": r_sender,
            "recipients": r_recipients,
            "subject": "",
            "body": r_spec["body"],
        })
    return bulletin_msg, reaction_msgs


def _validate_and_finalize_bundle(
    draft: IncidentEventDraft | None,
    pub: dict[str, Any],
    suggested_category: str,
    seed_val: int,
    model_label: str,
    err_label: str | None,
    call_usage: dict[str, Any],
) -> dict[str, Any]:
    day = int(pub["day"])
    rng = random.Random(f"live_events:{pub['tier']}:{seed_val}:{day}:{pub['company']}")
    emps = pub["employees"]
    if not emps:
        emps = [{"id": "e00", "name": "Alex Rivera", "dept": "Operations", "role": "manager"}]
        pub = {**pub, "employees": emps, "departments": ["Operations"]}

    emp_ids = {e["id"] for e in emps}
    emp_by_id = {e["id"]: e for e in emps}
    dept_set = set(pub["departments"])
    dept_by_low = {d.lower(): d for d in pub["departments"]}
    doc_titles = {d["title"] for d in pub["documents_up_to_day"]}

    raw_truth_violations = 0
    if draft is not None:
        raw_dump = draft.model_dump()
        if TRUTH_KEYS & set(_all_keys(raw_dump)):
            raw_truth_violations += 1
        for s in _walk_strings(raw_dump):
            if _has_truth_or_lint_issue(s):
                raw_truth_violations += 1

    cat = _clean_text(draft.category).lower() if draft is not None else ""
    repaired = False
    used_fallback = draft is None
    if cat not in EVENT_CATEGORIES:
        if draft is not None and not _is_placeholder(cat):
            repaired = True
        cat = suggested_category

    fb = _fallback_components(pub, cat, rng)

    if draft is None:
        comp = fb
    else:
        headline = _clean_text(draft.headline)
        if _is_bad_prose(headline) or _has_truth_or_lint_issue(headline) or _has_decoy_noise(headline):
            if not _is_placeholder(headline):
                repaired = True
            else:
                used_fallback = True
            headline = fb["headline"]

        summary = _clean_text(draft.summary)
        if _is_bad_prose(summary) or _has_truth_or_lint_issue(summary) or _has_decoy_noise(summary):
            if not _is_placeholder(summary):
                repaired = True
            summary = fb["summary"]

        aff = []
        for d_name in draft.affected_departments:
            cleaned = _clean_text(d_name)
            matched = cleaned if cleaned in dept_set else dept_by_low.get(cleaned.lower())
            if matched and matched not in aff:
                aff.append(matched)
            elif cleaned and not _is_placeholder(cleaned):
                repaired = True
        if not aff:
            aff = fb["affected_departments"]

        refs = []
        for t_name in draft.referenced_documents:
            cleaned = _clean_text(t_name)
            if cleaned in doc_titles and cleaned not in refs:
                refs.append(cleaned)
            elif cleaned and not _is_placeholder(cleaned):
                repaired = True

        b_sender = _clean_text(draft.bulletin.sender)
        if b_sender not in emp_ids:
            if not _is_placeholder(b_sender):
                repaired = True
            b_sender = fb["bulletin"]["sender"]

        b_chan = _clean_text(draft.bulletin.channel).lower()
        if b_chan not in {"email", "#announcements"}:
            b_chan = fb["bulletin"]["channel"]

        b_subj = _clean_text(draft.bulletin.subject)
        if _is_bad_prose(b_subj) or _has_truth_or_lint_issue(b_subj) or _has_decoy_noise(b_subj):
            if not _is_placeholder(b_subj):
                repaired = True
            b_subj = fb["bulletin"]["subject"]

        b_body = _clean_text(draft.bulletin.body)
        if _is_bad_prose(b_body) or _has_truth_or_lint_issue(b_body) or _has_decoy_noise(b_body):
            if not _is_placeholder(b_body):
                repaired = True
            used_fallback = used_fallback or _is_placeholder(_clean_text(draft.bulletin.body))
            b_body = fb["bulletin"]["body"]

        valid_reactions: list[dict[str, str]] = []
        used_senders = {b_sender}
        for r_draft in draft.reactions[:4]:
            r_sender = _clean_text(r_draft.sender)
            r_body = _clean_text(r_draft.body)
            if r_sender not in emp_ids:
                if not _is_placeholder(r_sender):
                    repaired = True
                continue
            if len(emp_ids) > 2 and r_sender in used_senders:
                continue
            if _is_bad_prose(r_body) or _has_truth_or_lint_issue(r_body) or _has_decoy_noise(r_body):
                if not _is_placeholder(r_body):
                    repaired = True
                continue
            raw_chan = _clean_text(r_draft.channel).lower()
            if not raw_chan.startswith("#"):
                raw_chan = f"#{raw_chan}" if raw_chan else ""
            dept_key = raw_chan.lstrip("#")
            if dept_key not in dept_by_low:
                raw_chan = f"#{emp_by_id[r_sender]['dept'].lower()}"
            valid_reactions.append({"sender": r_sender, "channel": raw_chan, "body": r_body})
            used_senders.add(r_sender)

        if len(valid_reactions) < 2:
            if draft.reactions:
                repaired = True
            else:
                used_fallback = True
            for fb_r in fb["reactions"]:
                if len(valid_reactions) >= 2:
                    break
                if len(emp_ids) > 2 and fb_r["sender"] in used_senders:
                    alt = next((e for e in emps if e["id"] not in used_senders), None)
                    if alt is not None:
                        fb_r = {
                            "sender": alt["id"],
                            "channel": f"#{alt['dept'].lower()}",
                            "body": fb_r["body"],
                        }
                valid_reactions.append(fb_r)
                used_senders.add(fb_r["sender"])

        comp = {
            "category": cat,
            "headline": headline,
            "summary": summary,
            "affected_departments": aff,
            "referenced_documents": refs,
            "bulletin": {
                "sender": b_sender,
                "channel": b_chan,
                "subject": b_subj,
                "body": b_body,
            },
            "reactions": valid_reactions,
        }

    bulletin_msg, reaction_msgs = _build_canonical_messages(
        day=day,
        employees=emps,
        bulletin_spec=comp["bulletin"],
        reaction_specs=comp["reactions"],
    )
    all_msgs = [bulletin_msg, *reaction_msgs]
    if lint_messages(all_msgs):
        repaired = True
        used_fallback = True
        bulletin_msg, reaction_msgs = _build_canonical_messages(
            day=day,
            employees=emps,
            bulletin_spec=fb["bulletin"],
            reaction_specs=fb["reactions"],
        )
        all_msgs = [bulletin_msg, *reaction_msgs]
        comp = fb

    safe_err = None
    if err_label:
        safe_err = _clean_text(err_label.split(":", 1)[0])[:80]
        if _has_truth_or_lint_issue(safe_err):
            safe_err = "validation_error"

    bundle = {
        "event_id": f"ev-s{seed_val}-d{day}",
        "day": day,
        "company": pub["company"],
        "tier": pub["tier"],
        "category": comp["category"],
        "headline": comp["headline"],
        "summary": comp["summary"],
        "affected_departments": comp["affected_departments"],
        "referenced_documents": comp["referenced_documents"],
        "bulletin": bulletin_msg,
        "reactions": reaction_msgs,
        "messages": all_msgs,
        "meta": {
            "llm_ok": draft is not None and not used_fallback,
            "used_fallback": used_fallback,
            "repaired": repaired,
            "raw_violations": raw_truth_violations,
            "model": _clean_text(model_label or "stub"),
            "error": safe_err,
            "usage": call_usage,
        },
    }
    assert_no_truth(bundle, {})
    probs = lint_messages(bundle["messages"])
    if probs:
        raise AssertionError(f"live_events lint failure after sanitization: {probs}")
    return bundle


def generate_mid_episode_events(
    env_or_public_facts: Any,
    days: Iterable[int] = DEFAULT_DAYS,
    llm: Any = f"gemini:{DEFAULT_MODEL}",
    *,
    run_id: str = "",
    seed: int | None = None,
) -> list[dict[str, Any]]:
    client = resolve_live_events_client(llm, run_id=run_id)
    seed_val = _seed_hint(env_or_public_facts) if seed is None else int(seed)
    model_label = getattr(client, "model", None) or getattr(client, "name", "stub")
    schema = inline_schema(IncidentEventDraft)

    bundles: list[dict[str, Any]] = []
    prior_headlines: list[str] = []

    for idx, raw_day in enumerate(days):
        day = int(raw_day)
        pub = public_day_facts_view(env_or_public_facts, day)
        suggested_category = EVENT_CATEGORIES[(seed_val + idx) % len(EVENT_CATEGORIES)]
        prompt_payload = {
            "company": pub["company"],
            "tier": pub["tier"],
            "day": day,
            "suggested_category": suggested_category,
            "prior_headlines": list(prior_headlines),
            "departments": pub["departments"],
            "department_channels": [f"#{d.lower()}" for d in pub["departments"]],
            "employees": pub["employees"],
            "documents_up_to_day": pub["documents_up_to_day"],
        }
        assert_no_truth(prompt_payload, {})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt_payload, sort_keys=True)},
        ]
        draft: IncidentEventDraft | None = None
        err_label: str | None = None
        call_usage = {"in": 0, "out": 0, "thinking": 0, "cached": 0, "total_tokens": 0, "cost_usd": 0.0}
        try:
            resp = client.chat(messages, tools=None, temperature=0.0, response_schema=schema)
            call_usage = _usage_from_response(resp)
            raw_text = resp.get("text", "") if isinstance(resp, dict) else getattr(resp, "text", "")
            txt = re.sub(r"^```(?:json)?|```$", "", str(raw_text or "").strip()).strip()
            draft = IncidentEventDraft.model_validate(json.loads(txt))
        except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
            err_label = type(exc).__name__
        except Exception as exc:
            from canary.llm.base import MissingKeyError
            if isinstance(exc, MissingKeyError):
                raise
            err_label = f"llm_{type(exc).__name__}"

        bundle = _validate_and_finalize_bundle(
            draft=draft,
            pub=pub,
            suggested_category=suggested_category,
            seed_val=seed_val,
            model_label=str(model_label),
            err_label=err_label,
            call_usage=call_usage,
        )
        prior_headlines.append(bundle["headline"])
        bundles.append(bundle)

    return bundles


def audit_event_bundles(events: Iterable[dict[str, Any]], world: Any = None) -> dict[str, Any]:
    from canary.gemini.swarm import mole_named

    truth_violations = 0
    raw_llm_violations = 0
    lint_violations = 0
    details: list[str] = []
    mole_id = get(world, "mole") or get(world, "mole_id") if world is not None else None
    emp_ids = {get(e, "id") for e in (get(world, "employees") or ()) if get(e, "id")} if world is not None else set()

    for bundle in events:
        ev_id = bundle.get("event_id", f"day-{bundle.get('day')}")
        try:
            assert_no_truth(bundle, world or {})
        except AssertionError as exc:
            truth_violations += 1
            details.append(f"{ev_id}: {exc}")
        raw_v = int((bundle.get("meta") or {}).get("raw_violations", 0) or 0)
        raw_llm_violations += raw_v
        msgs = bundle.get("messages") or []
        m_probs = lint_messages(msgs)
        if m_probs:
            lint_violations += len(m_probs)
            details.extend(f"{ev_id}: {p}" for p in m_probs)
        for msg in msgs:
            if emp_ids and msg.get("sender") not in emp_ids:
                lint_violations += 1
                details.append(f"{ev_id}: unknown sender {msg.get('sender')!r}")
            if emp_ids and any(r not in emp_ids for r in (msg.get("recipients") or ())):
                lint_violations += 1
                details.append(f"{ev_id}: unknown recipient in {msg.get('id')!r}")
        if mole_id:
            for s in _walk_strings(bundle):
                if mole_named(s, str(mole_id)):
                    truth_violations += 1
                    details.append(f"{ev_id}: mole named in {s[:80]!r}")

    return {
        "truth_leak_violations": truth_violations,
        "raw_llm_violations": raw_llm_violations,
        "lint_violations": lint_violations,
        "details": details,
    }


class LiveEventsTextProvider:
    def __init__(
        self,
        events: Iterable[dict[str, Any]] | dict[int, list[dict[str, Any]]],
        base: Any = None,
        name: str = "gemini-live-events",
    ):
        self.name = name
        self.base = base if base is not None else TemplateProvider()
        self.by_day: dict[int, list[dict[str, Any]]] = {}
        if isinstance(events, dict):
            for d_key, msgs in events.items():
                self.by_day[int(d_key)] = [copy.deepcopy(m) for m in msgs]
        else:
            for bundle in events:
                day = int(bundle["day"])
                self.by_day.setdefault(day, []).extend(copy.deepcopy(m) for m in bundle.get("messages", ()))

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        out = [copy.deepcopy(m) for m in self.base.day_messages(facts)]
        emp_ids = {e.id for e in facts.employees}
        seen_ids = {m["id"] for m in out}
        for msg in self.by_day.get(int(facts.day), ()):
            m = copy.deepcopy(msg)
            if emp_ids and m.get("sender") not in emp_ids:
                continue
            if emp_ids:
                recips = [r for r in m.get("recipients", ()) if r in emp_ids]
                m["recipients"] = recips or [sorted(emp_ids)[0]]
            if m["id"] in seen_ids:
                m["id"] = f"{m['id']}-{len(out)}"
            m["day"] = int(facts.day)
            seen_ids.add(m["id"])
            out.append(m)
        return out

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self.base.interview_answer(facts, employee, topic, signal)


def verify_solver_parity(
    tier: str,
    seeds: Iterable[int],
    events_by_seed: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    from canary.baselines import DoNothing, ObviousHeuristic
    from canary.env import Env
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    seed_list = [int(s) for s in seeds]
    rows: list[dict[str, Any]] = []
    for seed in seed_list:
        bundles = events_by_seed[seed]
        live_provider = LiveEventsTextProvider(bundles, base=TemplateProvider(), name="gemini-live-events")

        base_solver = run_episode(Env(tier, seed, text_provider=TemplateProvider()), SolverPolicy())
        live_solver = run_episode(Env(tier, seed, text_provider=live_provider), SolverPolicy())

        base_obvious = run_episode(Env(tier, seed, text_provider=TemplateProvider()), ObviousHeuristic(seed=seed))
        live_obvious = run_episode(Env(tier, seed, text_provider=live_provider), ObviousHeuristic(seed=seed))

        horizon_env = Env(tier, seed, text_provider=live_provider)
        do_nothing_res = run_episode(horizon_env, DoNothing(seed=seed))
        all_env_msgs = list(horizon_env._messages.values())
        ev_msgs = [m for m in all_env_msgs if str(m.get("id", "")).startswith("ev")]
        assert not lint_messages(all_env_msgs)
        for m in ev_msgs:
            assert_no_truth(m, horizon_env._world)

        rows.append({
            "seed": seed,
            "baseline_solver": {
                "score": round(float(base_solver.score), 4),
                "correct": bool(base_solver.correct),
                "final_day": int(base_solver.final_day),
                "end_reason": base_solver.end_reason,
            },
            "live_events_solver": {
                "score": round(float(live_solver.score), 4),
                "correct": bool(live_solver.correct),
                "final_day": int(live_solver.final_day),
                "end_reason": live_solver.end_reason,
            },
            "baseline_obvious_heuristic": {
                "score": round(float(base_obvious.score), 4),
                "correct": bool(base_obvious.correct),
                "final_day": int(base_obvious.final_day),
                "end_reason": base_obvious.end_reason,
            },
            "live_events_obvious_heuristic": {
                "score": round(float(live_obvious.score), 4),
                "correct": bool(live_obvious.correct),
                "final_day": int(live_obvious.final_day),
                "end_reason": live_obvious.end_reason,
            },
            "live_events_do_nothing_score": round(float(do_nothing_res.score), 4),
            "event_messages_delivered": len(ev_msgs),
            "total_horizon_messages": len(all_env_msgs),
        })

    n = max(1, len(rows))
    b_s_mean = sum(r["baseline_solver"]["score"] for r in rows) / n
    l_s_mean = sum(r["live_events_solver"]["score"] for r in rows) / n
    b_o_mean = sum(r["baseline_obvious_heuristic"]["score"] for r in rows) / n
    l_o_mean = sum(r["live_events_obvious_heuristic"]["score"] for r in rows) / n
    b_s_acc = sum(1 for r in rows if r["baseline_solver"]["correct"]) / n
    l_s_acc = sum(1 for r in rows if r["live_events_solver"]["correct"]) / n
    l_o_acc = sum(1 for r in rows if r["live_events_obvious_heuristic"]["correct"]) / n
    do_nothing_zero = all(r["live_events_do_nothing_score"] == 0.0 for r in rows)
    score_delta = l_s_mean - b_s_mean
    solver_gap = l_s_mean - l_o_mean
    parity_ok = bool(
        do_nothing_zero
        and abs(score_delta) <= 0.05
        and l_s_acc >= b_s_acc - 1e-9
        and solver_gap > 0.20
    )

    return {
        "tier": tier,
        "seeds": seed_list,
        "baseline_solver_mean_score": round(b_s_mean, 4),
        "live_events_solver_mean_score": round(l_s_mean, 4),
        "solver_score_delta": round(score_delta, 4),
        "baseline_solver_accuracy": round(b_s_acc, 4),
        "live_events_solver_accuracy": round(l_s_acc, 4),
        "baseline_obvious_heuristic_mean_score": round(b_o_mean, 4),
        "live_events_obvious_heuristic_mean_score": round(l_o_mean, 4),
        "live_events_obvious_heuristic_accuracy": round(l_o_acc, 4),
        "solver_vs_obvious_gap": round(solver_gap, 4),
        "do_nothing_all_zero": do_nothing_zero,
        "parity_ok": parity_ok,
        "per_seed": rows,
    }


def _git_sha() -> str:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=REPO,
                timeout=10,
            ).stdout.strip()
            or "unknown"
        )
    except Exception:
        return "unknown"


def _parse_int_csv(spec: str) -> list[int]:
    out = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            out.extend(range(int(lo_s), int(hi_s) + 1))
        else:
            out.append(int(part))
    if not out:
        raise ValueError(f"empty integer list: {spec!r}")
    return out


def _strip_usage_meta(bundle: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(bundle)
    return out


def _render_summary_md(meta: dict[str, Any], events_doc: dict[str, Any], parity: dict[str, Any]) -> str:
    usage = meta["usage"]
    lines = [
        "# Role 1 (world_text): Dynamic Mid-Episode Corporate Incident Events",
        "",
        f"- Model: `{meta['model_id']}`",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Tier / version: `{meta['tier']}` (`{meta['tiers_version']}`)",
        f"- Seeds: `{meta['seeds']}` | Arrival days: `{meta['days']}`",
        f"- Events generated: `{meta['n_events_generated']}` | Truth leak violations: `{meta['truth_leak_violations']}` | Lint violations: `{meta['lint_violations']}`",
        f"- Token usage: `{usage['calls']}` calls, `{usage['in']}` input, `{usage['out']}` output, `{usage['thinking']}` thinking, `{usage['total_tokens']}` total tokens (`${usage['cost_usd']:.6f}` est., `{usage['latency_s']:.2f}s`)",
        "",
        "## Generated Mid-Episode Event Bundles",
        "",
        "| Seed | Day | Company | Category | Headline | Reactions | LLM OK |",
        "|---:|---:|---|---|---|---:|---|",
    ]
    for seed_entry in events_doc["seeds"]:
        s_val = seed_entry["seed"]
        for ev in seed_entry["events"]:
            llm_ok = "yes" if ev["meta"]["llm_ok"] else "fallback"
            headline = ev["headline"].replace("|", "/")
            lines.append(
                f"| {s_val} | {ev['day']} | {ev['company']} | `{ev['category']}` | {headline} | {len(ev['reactions'])} | {llm_ok} |"
            )

    lines.extend([
        "",
        "## SolverPolicy vs ObviousHeuristic Catchability Parity",
        "",
        "| Seed | Baseline Solver | Live-Events Solver | Baseline ObviousHeuristic | Live-Events ObviousHeuristic | DoNothing | Event Msgs Delivered |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in parity["per_seed"]:
        bs = row["baseline_solver"]
        ls = row["live_events_solver"]
        bo = row["baseline_obvious_heuristic"]
        lo = row["live_events_obvious_heuristic"]
        lines.append(
            f"| {row['seed']} | {bs['score']:+.4f} (d{bs['final_day']}, {'ok' if bs['correct'] else 'wrong'}) "
            f"| {ls['score']:+.4f} (d{ls['final_day']}, {'ok' if ls['correct'] else 'wrong'}) "
            f"| {bo['score']:+.4f} (d{bo['final_day']}, {'ok' if bo['correct'] else 'wrong'}) "
            f"| {lo['score']:+.4f} (d{lo['final_day']}, {'ok' if lo['correct'] else 'wrong'}) "
            f"| {row['live_events_do_nothing_score']:+.4f} | {row['event_messages_delivered']} |"
        )

    lines.extend([
        "",
        f"- Baseline `SolverPolicy` mean score: `{parity['baseline_solver_mean_score']:+.4f}` (accuracy `{parity['baseline_solver_accuracy']:.2f}`)",
        f"- Live-events `SolverPolicy` mean score: `{parity['live_events_solver_mean_score']:+.4f}` (accuracy `{parity['live_events_solver_accuracy']:.2f}`, delta `{parity['solver_score_delta']:+.4f}`)",
        f"- Live-events `ObviousHeuristic` mean score: `{parity['live_events_obvious_heuristic_mean_score']:+.4f}` (accuracy `{parity['live_events_obvious_heuristic_accuracy']:.2f}`)",
        f"- `SolverPolicy` vs `ObviousHeuristic` gap on dynamic-event worlds: `{parity['solver_vs_obvious_gap']:+.4f}` (`parity_ok={parity['parity_ok']}`)",
        "",
        "## Reproduction",
        "",
        "```bash",
        meta["command"],
        "```",
    ])
    return "\n".join(lines) + "\n"


def run_live_events_experiment(
    tier: str = "medium",
    seeds: Iterable[int] = (3, 4, 5),
    days: Iterable[int] = DEFAULT_DAYS,
    llm: str = f"gemini:{DEFAULT_MODEL}",
    out_dir: Path | None = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    from canary.env import Env
    from canary.rules import TIERS_VERSION

    seed_list = [int(s) for s in seeds]
    day_list = [int(d) for d in days]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"live-events-{tier}-{stamp}"
    t0 = time.time()

    client = resolve_live_events_client(llm, run_id=run_id)
    model_id = getattr(client, "model", "") or (llm.split(":", 1)[1] if ":" in llm else llm)

    events_by_seed: dict[int, list[dict[str, Any]]] = {}
    total_truth_violations = 0
    total_raw_violations = 0
    total_lint_violations = 0
    audit_details: list[str] = []
    agg_usage = {"calls": 0, "in": 0, "out": 0, "thinking": 0, "cached": 0, "total_tokens": 0, "cost_usd": 0.0}

    seed_entries: list[dict[str, Any]] = []
    for seed in seed_list:
        env = Env(tier, seed)
        bundles = generate_mid_episode_events(env, days=day_list, llm=client, run_id=run_id, seed=seed)
        audit = audit_event_bundles(bundles, world=env._world)
        total_truth_violations += audit["truth_leak_violations"]
        total_raw_violations += audit["raw_llm_violations"]
        total_lint_violations += audit["lint_violations"]
        audit_details.extend(audit["details"])
        for b in bundles:
            u = (b.get("meta") or {}).get("usage") or {}
            agg_usage["calls"] += 1
            for k in ("in", "out", "thinking", "cached", "total_tokens"):
                agg_usage[k] += int(u.get(k, 0) or 0)
            agg_usage["cost_usd"] = round(agg_usage["cost_usd"] + float(u.get("cost_usd", 0.0) or 0.0), 6)
        events_by_seed[seed] = bundles
        seed_entries.append({
            "seed": seed,
            "tier": tier,
            "company": bundles[0]["company"] if bundles else env._world.company,
            "events": [_strip_usage_meta(b) for b in bundles],
        })

    latency_s = round(time.time() - t0, 3)
    agg_usage["latency_s"] = latency_s
    parity = verify_solver_parity(tier=tier, seeds=seed_list, events_by_seed=events_by_seed)

    n_events = sum(len(v) for v in events_by_seed.values())
    cmd = command_str or (
        f"PYTHONPATH=. python -m canary.gemini.live_events --llm {llm} "
        f"--tier {tier} --seeds {','.join(map(str, seed_list))} --days {','.join(map(str, day_list))}"
        + (f" --out {out_dir}" if out_dir else "")
    )
    meta = {
        "role": "world_text",
        "subrole": "dynamic_mid_episode_events",
        "model_id": model_id,
        "commit": _git_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": _clean_text(cmd),
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "seeds": seed_list,
        "days": day_list,
        "ledger_run_id": run_id,
        "usage": agg_usage,
        "truth_leak_violations": total_truth_violations,
        "raw_llm_violations": total_raw_violations,
        "lint_violations": total_lint_violations,
        "n_events_generated": n_events,
        "solver_parity_ok": parity["parity_ok"],
        "key_metric": (
            f"{n_events} events ({len(seed_list)} seeds), {total_truth_violations} truth leaks, "
            f"solver {parity['live_events_solver_mean_score']:+.3f} vs base {parity['baseline_solver_mean_score']:+.3f}"
        ),
    }
    events_doc = {
        "role": "world_text",
        "subrole": "dynamic_mid_episode_events",
        "model_id": model_id,
        "tier": tier,
        "tiers_version": TIERS_VERSION,
        "days": day_list,
        "n_events_generated": n_events,
        "seeds": seed_entries,
    }

    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        (out_dir / "events.json").write_text(json.dumps(events_doc, indent=2, sort_keys=True) + "\n")
        (out_dir / "solver_parity.json").write_text(json.dumps(parity, indent=2, sort_keys=True) + "\n")
        (out_dir / "summary.md").write_text(_render_summary_md(meta, events_doc, parity))

    return {
        "meta": meta,
        "events": events_doc,
        "solver_parity": parity,
        "audit_details": audit_details,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.live_events")
    p.add_argument("--llm", default=f"gemini:{DEFAULT_MODEL}")
    p.add_argument("--tier", default="medium")
    p.add_argument("--seeds", default="3,4,5")
    p.add_argument("--days", default="3,6,10")
    p.add_argument("--out", type=Path, default=None)
    return p


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    seeds = _parse_int_csv(args.seeds)
    days = _parse_int_csv(args.days)
    cmd = "PYTHONPATH=. python -m canary.gemini.live_events " + " ".join(raw_argv) if raw_argv else (
        "PYTHONPATH=. python -m canary.gemini.live_events"
    )
    res = run_live_events_experiment(
        tier=args.tier,
        seeds=seeds,
        days=days,
        llm=args.llm,
        out_dir=args.out,
        command_str=cmd,
    )
    print(json.dumps(res["meta"], indent=2, sort_keys=True))
    if res["meta"]["truth_leak_violations"] > 0 or res["meta"]["lint_violations"] > 0:
        return 1
    if not res["solver_parity"]["parity_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
