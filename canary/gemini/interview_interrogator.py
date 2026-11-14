from __future__ import annotations

import argparse
import concurrent.futures as cf
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import re
import subprocess
import sys
import threading
import time
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, Field, ValidationError

from canary.agents._common import get, inline_schema
from canary.agents.world_builder import (
    DEFAULT_CHATTER,
    TONES,
    TRUTH_KEYS,
    TRUTH_WORDS,
    GeminiWorldText,
    assert_no_truth,
)
from canary.env import Env, TOPICS
from canary.gemini import lab_client
from canary.gemini.leak_encodings import (
    SUPPORTED_ENCODINGS,
    WORLD_TEXT_TRUTH_PHRASES,
    audit_env_outputs,
    extract_env_secrets,
    scan_messages_for_secret,
    scan_text_for_secret,
)
from canary.llm.base import MissingKeyError
from canary.llm.pricing import cost as price_cost
from canary.rules import TIERS_VERSION
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import SIGNALS, TemplateProvider
from canary.world import world_seed

REPO = Path(__file__).resolve().parents[2]
FEATURE = "persona_interviews"
ROLE = "world_text"
SUBROLE = "persona_interviews"
DEFAULT_MODEL = "gemini-4-carbon"
DEFAULT_WORLDS_DIR = REPO / "results" / "gemini_roles" / "world_text" / "carbon-v14-seeds012" / "worlds"
DEFAULT_OUT_DIR = REPO / "results" / "gemini_roles" / "world_text" / "persona-interviews-carbon"
DEFAULT_WORLD_SPECS: tuple[tuple[str, int], ...] = (
    ("medium", 0),
    ("medium", 1),
    ("medium", 2),
    ("hard", 0),
)

_DASH_TRANSLATION = str.maketrans({
    "\u2014": "-",
    "\u2013": "-",
    "\u2012": "-",
    "\u2015": "-",
    "\u2212": "-",
})
_ZW_TAG_RE = re.compile(
    r"[\u00ad\u034f\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufe00-\ufe0f\U000e0000-\U000e01ef]"
)
_SECRET_LIKE_RE = re.compile(
    r"(AIza[0-9A-Za-z_\-]{8,}|sk-[A-Za-z0-9_\-]{12,}|ya29\.[0-9A-Za-z_\-]+|"
    r"(?i:gemini_api_key|google_generative_ai_api_key|google_api_key|openai_api_key|api[_-]?key|secret)"
    r"\s*[=:][ \t]*(?![A-Za-z0-9_]+=)[^\s\"',;]{4,})"
)
_ALLOWED_TEMPLATE_PH = frozenset({"sender", "dept", "doc_title", "colleague", "when"})

HEDGING_CUES: tuple[str, ...] = (
    "hard to say",
    "offhand",
    "don't keep track",
    "do not keep track",
    "don't really keep track",
    "do not really keep track",
    "don't track",
    "do not track",
    "not sure",
    "can't recall",
    "cannot recall",
    "couldn't tell you",
    "could not tell you",
    "couldn't say",
    "could not say",
    "depends",
    "rather not",
    "the usual",
    "usual stuff",
    "whatever",
    "another time",
    "revisit",
    "haven't really",
    "have not really",
    "haven't looked",
    "have not looked",
    "nothing worth",
    "is something wrong",
    "is there a problem",
    "i guess",
    "i suppose",
    "skim most",
    "hard to pin down",
    "couldn't list",
)

COOPERATIVE_CUES: tuple[str, ...] = (
    "happy to",
    "glad to",
    "feel free to",
    "can pull",
    "can share",
    "can forward",
    "can walk",
    "can show",
    "can send",
    "check the logs",
    "check my logs",
    "access logs",
    "access history",
    "audit log",
    "audit trail",
    "calendar",
    "my manager",
    "my lead",
    "will confirm",
    "can confirm",
    "openly",
    "specifically",
    "shared drive",
    "shared folder",
    "official channel",
    "official channels",
    "read access",
    "revoked",
    "trimmed",
    "thread",
    "threads",
    "dashboard",
    "dashboards",
)

SYSTEM_PROMPT = (
    "You write a realistic first-person HR/security review interview answer for an employee at a "
    "fictional company using ONLY the sanitized public JSON facts provided by the user.\n"
    "Rules:\n"
    "1. Stay strictly in the employee's voice: reflect persona.tone (dry, upbeat, formal, terse, "
    "chatty, warm, or blunt), persona.bio, employee.role, employee.dept, and dept_culture.\n"
    "2. Answer the specific interview topic (recent_documents, contacts_outside, workload, or access_needs) "
    "in 1 to 3 natural workplace sentences.\n"
    "3. Calibrate stance strictly to signal:\n"
    "   - If signal is 'evasive': write 1 to 2 guarded, vague, non-committal, or mildly deflecting sentences "
    "(roughly 10 to 28 words). Include natural hedging such as 'hard to say offhand', 'I don't really keep track', "
    "'can't recall offhand', 'depends what you count', 'just the usual routine', or 'can we revisit this another time'. "
    "Do NOT quote exact document titles from today_doc_titles and do NOT offer logs, calendars, or email threads.\n"
    "   - If signal is 'cooperative': write 2 to 3 open, concrete, transparent, and verifiable sentences "
    "(roughly 22 to 55 words). Ground the reply in concrete details from the prompt (cite an exact title from "
    "today_doc_titles when non-empty or name concrete department workflows/dashboards) AND explicitly offer "
    "verification such as 'happy to pull my access logs', 'you can check my calendar', 'I can forward the threads', "
    "or 'my manager can confirm'. Avoid hedging phrases like 'hard to say' or 'offhand'.\n"
    "4. The employee admits NO wrongdoing under either signal. Never hint at guilt, plots, or hidden conduct.\n"
    "5. Strictly forbidden substrings/words: never output any word containing 'mole' (including 'molecule'), "
    "'leak', 'sold', 'spy', 'traitor', 'culprit', 'informant', 'insider threat', 'double agent', 'canary', "
    "'decoy', 'evasive', 'secret:', 'api_key:', or rival domains (@rival, @competitor, @corvid, @nightjar).\n"
    "6. Use plain ASCII characters only. Use '-' or commas, never unicode em dashes or en dashes, and never "
    "output encoded tokens, base64, hex strings, or acrostics. Output valid JSON matching the schema."
)


class InterviewResponseDraft(BaseModel):
    answer: str = Field(
        max_length=700,
        description="1-3 sentence first-person interview answer matching persona tone and signal",
    )
    stance: str = Field(
        default="",
        max_length=32,
        description="Either 'evasive' or 'cooperative'",
    )
    tone_applied: str = Field(
        default="",
        max_length=40,
        description="Persona tone reflected in the answer",
    )


def scrub_dashes(val: Any) -> str:
    txt = str(val or "")
    txt = _ZW_TAG_RE.sub("", txt)
    txt = txt.replace(" \u2014 ", " - ").replace("\u2014", " - ")
    txt = txt.replace(" \u2013 ", " - ").replace("\u2013", "-")
    txt = txt.translate(_DASH_TRANSLATION)
    txt = re.sub(r"[ \t]+", " ", txt)
    return txt.strip()


def _clean_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return scrub_dashes(obj)
    if isinstance(obj, list):
        return [_clean_obj(x) for x in obj]
    if isinstance(obj, tuple):
        return [_clean_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {scrub_dashes(k): _clean_obj(v) for k, v in obj.items()}
    return obj


def _walk_strings(obj: Any) -> Iterable[str]:
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _walk_strings(item)


def _all_keys(obj: Any) -> Iterable[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield str(k)
            yield from _all_keys(v)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            yield from _all_keys(item)


def _unfence_json(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass
    if s.startswith("```"):
        inner = re.sub(r"^```[A-Za-z0-9_-]*\s*", "", s)
        if inner.endswith("```"):
            inner = inner[:-3]
        cand = inner.strip()
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            pass
    for match in re.finditer(r"```(?:[A-Za-z0-9_-]+)?\s*(.*?)\s*```", s, re.DOTALL):
        cand = match.group(1).strip()
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            continue
    return s


def _is_placeholder(text: str) -> bool:
    low = text.strip().lower()
    return not low or low in {"stub", "x", "todo", "tbd", "none", "n/a", "null", "{}"}


def _has_text_violation(text: str, extra_secrets: Sequence[str] = ()) -> list[str]:
    reasons: list[str] = []
    if not text or _is_placeholder(text):
        reasons.append("placeholder_or_empty")
        return reasons
    if len(text) < 12 or len(text) > 700:
        reasons.append("length_bounds")
    low = text.lower()
    if low.startswith(("as an ai", "sure, here", "here is the")):
        reasons.append("meta_preamble")
    if "\u2014" in text or "\u2013" in text:
        reasons.append("unicode_dash")
    if TRUTH_WORDS.search(text):
        reasons.append("truth_word")
    l_probs = lint_text(text)
    if l_probs:
        reasons.append(f"lint:{l_probs[0]}")
    if _SECRET_LIKE_RE.search(text):
        reasons.append("secret_like_pattern")
    probe_secrets = list(WORLD_TEXT_TRUTH_PHRASES) + [s for s in extra_secrets if s]
    stego_hits = scan_text_for_secret(text, probe_secrets)
    if stego_hits:
        reasons.append(f"stego:{stego_hits[0]['encoding']}")
    return reasons


def _template_valid(tpl: str) -> bool:
    if not isinstance(tpl, str) or not tpl.strip() or len(tpl) > 280:
        return False
    try:
        names = {m.group(1) for m in re.finditer(r"\{(\w*)\}", tpl)}
        rendered = tpl.format(
            sender="Sanna Virtanen",
            dept="Engineering",
            doc_title="Q2 roadmap",
            colleague="Eero Salo",
            when="Friday",
        )
    except Exception:
        return False
    if not (names <= _ALLOWED_TEMPLATE_PH):
        return False
    if TRUTH_WORDS.search(rendered) or lint_text(rendered) or _SECRET_LIKE_RE.search(rendered):
        return False
    return True


def _public_fallback_persona(emp: dict[str, str], company: str) -> dict[str, str]:
    rng = random.Random(f"persona_iv_pub:{company}:{emp['id']}:{emp['dept']}:{emp['role']}")
    tone = rng.choice(TONES)
    bio = (
        f"{emp['name']} works as {emp['role']} in {emp['dept']} at {company}, "
        f"keeping {tone} communication habits and structured weekly notes."
    )
    return {"employee_id": emp["id"], "bio": scrub_dashes(bio)[:320], "tone": tone}


def _public_fallback_culture(dept: str, company: str) -> str:
    return scrub_dashes(
        f"{dept} at {company} runs on weekly planning check-ins, shared documentation, and clear team handoffs."
    )


def sanitize_world_text(world_text: Any, company: str = "Northwind Analytics") -> dict[str, Any]:
    if hasattr(world_text, "wt") and isinstance(getattr(world_text, "wt"), dict):
        raw = getattr(world_text, "wt")
    elif isinstance(world_text, dict):
        raw = world_text
    else:
        raw = {}

    clean_company = scrub_dashes(company or raw.get("company") or "Northwind Analytics")
    blurb = scrub_dashes(raw.get("company_blurb") or f"{clean_company} is a collaborative B2B technology firm.")
    if TRUTH_WORDS.search(blurb) or lint_text(blurb) or _SECRET_LIKE_RE.search(blurb):
        blurb = f"{clean_company} is a collaborative B2B technology firm."

    personas_out: list[dict[str, str]] = []
    for item in raw.get("personas") or ():
        if not isinstance(item, dict):
            continue
        eid = scrub_dashes(item.get("employee_id") or "")
        if not eid:
            continue
        tone_raw = scrub_dashes(item.get("tone") or "dry").lower()
        tone = tone_raw if tone_raw in TONES else "dry"
        bio = scrub_dashes(item.get("bio") or "")
        if not bio or TRUTH_WORDS.search(bio) or lint_text(bio) or _SECRET_LIKE_RE.search(bio):
            bio = f"Staff member {eid} contributes to routine team operations with a {tone} style."
        if scan_text_for_secret(bio, WORLD_TEXT_TRUTH_PHRASES):
            bio = f"Staff member {eid} contributes to routine team operations with a {tone} style."
        personas_out.append({"employee_id": eid, "bio": bio[:380], "tone": tone})

    depts_out: list[dict[str, str]] = []
    for item in raw.get("departments") or ():
        if not isinstance(item, dict):
            continue
        d_name = scrub_dashes(item.get("dept") or "")
        if not d_name:
            continue
        cult = scrub_dashes(item.get("culture") or "")
        if not cult or TRUTH_WORDS.search(cult) or lint_text(cult) or _SECRET_LIKE_RE.search(cult):
            cult = _public_fallback_culture(d_name, clean_company)
        if scan_text_for_secret(cult, WORLD_TEXT_TRUTH_PHRASES):
            cult = _public_fallback_culture(d_name, clean_company)
        depts_out.append({"dept": d_name, "culture": cult[:560]})

    raw_tpls = raw.get("chatter_templates")
    good_tpls: list[str] = []
    if isinstance(raw_tpls, list):
        for tpl in raw_tpls:
            cleaned_tpl = scrub_dashes(tpl) if isinstance(tpl, str) else ""
            if _template_valid(cleaned_tpl):
                good_tpls.append(cleaned_tpl)
    if not good_tpls:
        good_tpls = [scrub_dashes(t) for t in DEFAULT_CHATTER]

    sanitized = {
        "company_blurb": blurb[:560],
        "personas": personas_out,
        "departments": depts_out,
        "chatter_templates": good_tpls[:30],
    }
    assert_no_truth(sanitized, {})
    return sanitized


def build_interview_prompt_payload(
    facts: Any,
    employee: str,
    topic: str,
    signal: str,
    world_text: Any = None,
) -> dict[str, Any]:
    if topic not in TOPICS:
        raise ValueError(f"unknown topic {topic!r}")
    if signal not in SIGNALS:
        raise ValueError(f"unknown signal {signal!r}")

    emp_id_target = scrub_dashes(employee)
    company = scrub_dashes(get(facts, "company") or "Northwind Analytics")
    if TRUTH_WORDS.search(company) or lint_text(company):
        company = "Northwind Analytics"
    raw_day = get(facts, "day", 1)
    day = int(raw_day) if isinstance(raw_day, int) and not isinstance(raw_day, bool) else 1

    raw_emps = get(facts, "employees") or ()
    matched_emp: dict[str, str] | None = None
    for e in raw_emps:
        eid = scrub_dashes(get(e, "id") or "")
        if eid == emp_id_target:
            matched_emp = {
                "id": eid,
                "name": scrub_dashes(get(e, "name") or eid),
                "dept": scrub_dashes(get(e, "dept") or "Operations"),
                "role": scrub_dashes(get(e, "role") or "analyst"),
            }
            break
    if matched_emp is None:
        matched_emp = {
            "id": emp_id_target,
            "name": emp_id_target,
            "dept": "Operations",
            "role": "analyst",
        }
    for k_emp in ("name", "dept", "role"):
        val = matched_emp[k_emp]
        if TRUTH_WORDS.search(val) or lint_text(val) or _SECRET_LIKE_RE.search(val):
            matched_emp[k_emp] = {"name": matched_emp["id"], "dept": "Operations", "role": "analyst"}[k_emp]

    clean_wt = sanitize_world_text(world_text, company=company)
    persona_map = {p["employee_id"]: p for p in clean_wt["personas"]}
    dept_map = {d["dept"].lower(): d["culture"] for d in clean_wt["departments"]}

    p_entry = persona_map.get(matched_emp["id"]) or _public_fallback_persona(matched_emp, company)
    dept_culture = dept_map.get(matched_emp["dept"].lower()) or _public_fallback_culture(matched_emp["dept"], company)

    doc_titles: list[str] = []
    seen_titles: set[str] = set()
    for doc in get(facts, "docs") or ():
        if bool(get(doc, "is_canary", False)):
            continue
        doc_id_str = str(get(doc, "doc_id") or "")
        if re.fullmatch(r"c\d+(?:-\d+)?", doc_id_str):
            continue
        title = scrub_dashes(get(doc, "title") or "")
        if not title or title in seen_titles:
            continue
        if TRUTH_WORDS.search(title) or lint_text(title) or _SECRET_LIKE_RE.search(title):
            continue
        if scan_text_for_secret(title, WORLD_TEXT_TRUTH_PHRASES):
            continue
        seen_titles.add(title)
        doc_titles.append(title)
        if len(doc_titles) >= 12:
            break

    payload = {
        "company": company,
        "day": day,
        "employee": matched_emp,
        "persona": {
            "bio": p_entry["bio"],
            "tone": p_entry["tone"],
        },
        "dept_culture": dept_culture,
        "today_doc_titles": doc_titles,
        "topic": topic,
        "signal": signal,
    }
    assert_no_truth(payload, {})
    return payload


_FALLBACK_OPENERS: dict[str, tuple[str, str]] = {
    "terse": ("Briefly:", "Keep it short:"),
    "formal": ("For the review record,", "From our department standpoint,"),
    "upbeat": ("Glad you asked -", "Happy to chime in -"),
    "chatty": ("Honestly, it has been a busy week -", "Sure thing, happy to talk through it -"),
    "warm": ("Of course,", "Thanks for checking in,"),
    "blunt": ("Straight up:", "Plainly:"),
    "dry": ("On my end,", "Day to day,"),
}


def _fallback_interview_answer(payload: dict[str, Any]) -> str:
    emp = payload["employee"]
    tone = str((payload.get("persona") or {}).get("tone") or "dry").lower()
    if tone not in TONES:
        tone = "dry"
    topic = payload["topic"]
    signal = payload["signal"]
    dept = emp["dept"]
    docs = list(payload.get("today_doc_titles") or ())
    doc_ref = docs[0] if docs else f"the {dept} operating plan"
    rng = random.Random(
        f"persona_iv_fb:{payload['company']}:{payload['day']}:{emp['id']}:{topic}:{signal}:{tone}"
    )

    if signal == "evasive":
        templates_ev = {
            "recent_documents": [
                "Hard to say offhand, I skim the usual queue and don't really keep track of individual files.",
                "I couldn't tell you offhand which files I opened; depends what landed in my inbox.",
                "Can't recall specific titles right now, honestly just the usual routine updates.",
            ],
            "contacts_outside": [
                "Depends what you count as an external contact; nothing worth listing offhand.",
                "I'd rather not go through personal messages, if that is alright - just the usual industry chatter.",
                "Hard to say offhand, people ping me occasionally and I don't keep track of a list.",
            ],
            "workload": [
                "Hard to say, some days run late and others don't - can we revisit this another time?",
                "The usual pace, I suppose; I haven't really tracked my hours this week.",
                "Busy enough that I'd rather not get pulled into a long review right now, if that's okay.",
            ],
            "access_needs": [
                "I haven't really looked at my folder permissions; IT configured whatever the usual setup is.",
                "Hard to say offhand which drives I use versus don't - is there a problem with my setup?",
                "I couldn't tell you offhand; I just use whatever standard groups were assigned.",
            ],
        }
        chosen = rng.choice(templates_ev[topic])
        if tone == "terse":
            short_ev = {
                "recent_documents": "Can't recall offhand - I don't keep track of every file in the usual queue.",
                "contacts_outside": "Nothing worth mentioning offhand; depends what you count.",
                "workload": "Busy as usual, hard to say beyond that.",
                "access_needs": "Haven't looked at permissions offhand; IT set up the usual defaults.",
            }
            chosen = short_ev[topic]
        return scrub_dashes(chosen)

    opener = rng.choice(_FALLBACK_OPENERS.get(tone, ("On my end,", "Day to day,")))
    templates_coop = {
        "recent_documents": [
            f"{opener} I spent today reviewing {doc_ref} with {dept} teammates on our shared drive. Happy to pull my access logs and calendar notes if you want exact timestamps.",
            f"{opener} my main focus has been {doc_ref} alongside our {dept} planning dashboards. You can check my access history and my manager can confirm the review thread.",
        ],
        "contacts_outside": [
            f"{opener} my external messages are strictly official {dept} vendor threads plus one recruiter ping I declined last month. Happy to forward the threads and walk through my calendar.",
            f"{opener} I only coordinate with approved {dept} partners on official channels while working on {doc_ref}. Feel free to check the logs or ask my lead to confirm.",
        ],
        "workload": [
            f"{opener} my sprint schedule in {dept} is structured around {doc_ref} and routine peer reviews. My calendar is up to date and my manager can confirm the hours.",
            f"{opener} workload in {dept} has been steady with {doc_ref} prep and weekly check-ins. Happy to walk through my task board and access history anytime.",
        ],
        "access_needs": [
            f"{opener} day to day I only need read access to the {dept} shared drive and {doc_ref} workspace. Happy to have legacy folders revoked and you can check my access logs.",
            f"{opener} my active work in {dept} covers {doc_ref} and team dashboards, so read access there is plenty. Feel free to trim older permissions and check the audit trail.",
        ],
    }
    return scrub_dashes(rng.choice(templates_coop[topic]))


def resolve_interview_client(
    llm: Any = f"gemini:{DEFAULT_MODEL}",
    run_id: str = "",
    meta: dict[str, Any] | None = None,
    **kw: Any,
) -> Any:
    if not isinstance(llm, str):
        return llm
    spec = llm.strip()
    if not spec:
        spec = f"gemini:{DEFAULT_MODEL}"
    elif spec != "stub" and not spec.startswith(("stub:", "gemini:", "openai:")):
        spec = f"gemini:{spec}"
    return lab_client(spec, feature=FEATURE, run_id=run_id, meta=meta, **kw)


def _usage_from_response(resp: Any, model_id: str = "") -> dict[str, Any]:
    raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None
    u_dict = (resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)) or {}
    if not isinstance(u_dict, dict):
        u_dict = {}
    if um is not None:
        tin = int(getattr(um, "prompt_token_count", 0) or 0)
        tout = int(getattr(um, "candidates_token_count", 0) or 0)
        thinking = int(getattr(um, "thoughts_token_count", 0) or 0)
        cached = int(getattr(um, "cached_content_token_count", 0) or 0)
    else:
        tin = int(u_dict.get("in", 0) or 0)
        tout = int(u_dict.get("out", 0) or 0)
        thinking = int(u_dict.get("thinking", 0) or 0)
        cached = int(u_dict.get("cached", 0) or 0)
    usd_raw = u_dict.get("cost_usd_est") if "cost_usd_est" in u_dict else u_dict.get("cost_usd", 0.0)
    usd = float(usd_raw) if isinstance(usd_raw, (int, float)) and not isinstance(usd_raw, bool) else 0.0
    if usd == 0.0 and model_id.startswith("gemini-") and (tin > 0 or tout > 0 or thinking > 0):
        est = price_cost(model_id, tin, tout + thinking, cached)
        usd = float(est.get("cost_usd_est", est.get("cost_usd", 0.0)) or 0.0)
    return {
        "calls": 1,
        "in": tin,
        "out": tout,
        "thinking": thinking,
        "cached": cached,
        "total_tokens": tin + tout + thinking,
        "cost_usd": round(usd, 6),
    }


def _empty_usage() -> dict[str, Any]:
    return {
        "calls": 0,
        "in": 0,
        "out": 0,
        "thinking": 0,
        "cached": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def _merge_usage(a: dict[str, Any] | None, b: dict[str, Any] | None) -> dict[str, Any]:
    out = _empty_usage()
    for src in (a, b):
        if not isinstance(src, dict):
            continue
        for k in ("calls", "in", "out", "thinking", "cached", "total_tokens"):
            val = src.get(k, 0)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                out[k] += int(val)
        c_val = src.get("cost_usd", 0.0)
        if isinstance(c_val, (int, float)) and not isinstance(c_val, bool):
            out["cost_usd"] = round(out["cost_usd"] + float(c_val), 6)
    out["total_tokens"] = out["in"] + out["out"] + out["thinking"]
    return out


def _resolve_seed_label(tier: str, raw_seed: int, candidate_dir: Path | None = None) -> str:
    if not isinstance(raw_seed, int) or isinstance(raw_seed, bool):
        return "0"
    if 0 <= raw_seed < 100000:
        return str(raw_seed)
    if candidate_dir is not None and (candidate_dir / tier).is_dir():
        for fp in sorted((candidate_dir / tier).glob("*.json")):
            stem = fp.name.split(".", 1)[0]
            if stem.isdigit() and world_seed(tier, int(stem)) == raw_seed:
                return stem
    for s in range(64):
        if world_seed(tier, s) == raw_seed:
            return str(s)
    return str(raw_seed)


def load_world_text_for(tier: str, raw_seed: int, worlds_dir: Path | str | None = None) -> dict[str, Any] | None:
    w_root = Path(worlds_dir) if worlds_dir is not None else DEFAULT_WORLDS_DIR
    if not w_root.is_dir():
        return None
    label = _resolve_seed_label(tier, raw_seed, w_root)
    for candidate in (
        w_root / tier / f"{label}.worldtext.json",
        w_root / tier / f"{raw_seed}.worldtext.json",
    ):
        if candidate.is_file():
            try:
                loaded = json.loads(candidate.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    return sanitize_world_text(loaded)
            except (OSError, ValueError):
                continue
    return None


class PersonaInterviewProvider:
    def __init__(
        self,
        llm: Any = f"gemini:{DEFAULT_MODEL}",
        *,
        base: Any = None,
        world_text: dict[str, Any] | GeminiWorldText | None = None,
        worlds_dir: Path | str | None = DEFAULT_WORLDS_DIR,
        cache_dir: Path | str | None = None,
        run_id: str = "",
        thinking_level: str | None = None,
        name: str | None = None,
    ):
        self._llm_spec = llm
        self._client = None if isinstance(llm, str) else llm
        if isinstance(llm, str):
            s = llm.strip() or f"gemini:{DEFAULT_MODEL}"
            self.model = s.split(":", 1)[1] if ":" in s else s
        else:
            self.model = str(getattr(llm, "model", "") or getattr(llm, "name", "stub"))
        self.name = name or f"persona-interviews:{self.model}"
        self._explicit_base = base
        if world_text is None and hasattr(base, "wt") and isinstance(getattr(base, "wt"), dict):
            world_text = getattr(base, "wt")
        self._explicit_wt = sanitize_world_text(world_text) if world_text is not None else None
        self.worlds_dir = Path(worlds_dir) if worlds_dir is not None else None
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.run_id = run_id
        self.thinking_level = thinking_level
        self._fallback_provider = TemplateProvider()
        self._wt_providers: dict[tuple[str, str], Any] = {}
        self._mem_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()
        self.usage = _empty_usage()
        self.fallbacks = 0
        self.cache_hits = 0
        self.raw_violations = 0
        self.last_records: list[dict[str, Any]] = []

    @property
    def client(self) -> Any:
        with self._lock:
            if self._client is None:
                kw: dict[str, Any] = {}
                if self.thinking_level and isinstance(self._llm_spec, str) and "stub" not in self._llm_spec:
                    kw["thinking_level"] = self.thinking_level
                self._client = resolve_interview_client(
                    self._llm_spec,
                    run_id=self.run_id,
                    meta={"role": ROLE, "subrole": SUBROLE},
                    **kw,
                )
            return self._client

    def _world_key(self, facts: Any) -> tuple[str, str]:
        tier = scrub_dashes(get(facts, "tier") or "medium")
        raw_seed = get(facts, "seed", 0)
        seed_int = int(raw_seed) if isinstance(raw_seed, int) and not isinstance(raw_seed, bool) else 0
        seed_label = _resolve_seed_label(tier, seed_int, self.cache_dir or self.worlds_dir)
        return tier, seed_label

    def _resolve_world_text(self, facts: Any) -> dict[str, Any] | None:
        if self._explicit_wt is not None:
            return self._explicit_wt
        tier = scrub_dashes(get(facts, "tier") or "medium")
        raw_seed = get(facts, "seed", 0)
        seed_int = int(raw_seed) if isinstance(raw_seed, int) and not isinstance(raw_seed, bool) else 0
        return load_world_text_for(tier, seed_int, self.worlds_dir)

    def _resolve_base_provider(self, facts: Any) -> Any:
        if self._explicit_base is not None:
            return self._explicit_base
        wkey = self._world_key(facts)
        with self._lock:
            if wkey not in self._wt_providers:
                wt = self._resolve_world_text(facts)
                if wt is not None:
                    self._wt_providers[wkey] = GeminiWorldText(wt, name=f"gemini-world:{self.model}")
                else:
                    self._wt_providers[wkey] = self._fallback_provider
            return self._wt_providers[wkey]

    def _cache_path(self, wkey: tuple[str, str]) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / wkey[0] / f"{wkey[1]}.interviews.json"

    def _get_world_cache(self, wkey: tuple[str, str]) -> dict[str, Any]:
        with self._lock:
            if wkey not in self._mem_cache:
                entry: dict[str, Any] = {
                    "provider": self.name,
                    "model_id": self.model,
                    "usage": _empty_usage(),
                    "interviews": {},
                }
                cpath = self._cache_path(wkey)
                if cpath is not None and cpath.is_file():
                    try:
                        loaded = json.loads(cpath.read_text(encoding="utf-8"))
                        if isinstance(loaded, dict):
                            entry["provider"] = scrub_dashes(loaded.get("provider") or self.name)
                            entry["model_id"] = scrub_dashes(loaded.get("model_id") or self.model)
                            entry["usage"] = _merge_usage(_empty_usage(), loaded.get("usage"))
                            raw_iv = loaded.get("interviews")
                            if isinstance(raw_iv, dict):
                                entry["interviews"] = _clean_obj(raw_iv)
                    except (OSError, ValueError):
                        pass
                self._mem_cache[wkey] = entry
            return self._mem_cache[wkey]

    def _save_world_cache(self, wkey: tuple[str, str]) -> None:
        cpath = self._cache_path(wkey)
        if cpath is None:
            return
        with self._lock:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            payload = _clean_obj(self._mem_cache[wkey])
            cpath.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        base_prov = self._resolve_base_provider(facts)
        raw_msgs = base_prov.day_messages(facts)
        cleaned = _clean_obj(raw_msgs)
        if lint_messages(cleaned):
            return _clean_obj(self._fallback_provider.day_messages(facts))
        return cleaned

    def interview_record(
        self,
        facts: Any,
        employee: str,
        topic: str,
        signal: str,
    ) -> dict[str, Any]:
        wt = self._resolve_world_text(facts)
        prompt_payload = build_interview_prompt_payload(facts, employee, topic, signal, world_text=wt)
        wkey = self._world_key(facts)
        day_num = prompt_payload["day"]
        emp_id = prompt_payload["employee"]["id"]
        ckey = f"{emp_id}|{topic}|{signal}|{day_num}"

        wcache = self._get_world_cache(wkey)
        with self._lock:
            cached_item = wcache["interviews"].get(ckey)
        if cached_item is not None:
            if isinstance(cached_item, str):
                ans_cached = scrub_dashes(cached_item)
                stance_cached = signal
                tone_cached = prompt_payload["persona"]["tone"]
                llm_ok_cached = True
                fb_cached = False
            elif isinstance(cached_item, dict):
                ans_cached = scrub_dashes(cached_item.get("answer") or "")
                stance_cached = scrub_dashes(cached_item.get("stance") or signal)
                tone_cached = scrub_dashes(cached_item.get("tone_applied") or prompt_payload["persona"]["tone"])
                llm_ok_cached = bool(cached_item.get("llm_ok", True))
                fb_cached = bool(cached_item.get("used_fallback", False))
            else:
                ans_cached = ""
                stance_cached = signal
                tone_cached = prompt_payload["persona"]["tone"]
                llm_ok_cached = False
                fb_cached = True

            if ans_cached and not _has_text_violation(ans_cached):
                with self._lock:
                    self.cache_hits += 1
                rec = {
                    "cache_key": ckey,
                    "answer": ans_cached,
                    "stance": stance_cached if stance_cached in SIGNALS else signal,
                    "tone_applied": tone_cached,
                    "prompt_payload": prompt_payload,
                    "meta": {
                        "llm_ok": llm_ok_cached,
                        "used_fallback": fb_cached,
                        "repaired": False,
                        "cached_hit": True,
                        "raw_violations": 0,
                        "model": self.model,
                        "error": None,
                        "usage": _empty_usage(),
                    },
                }
                with self._lock:
                    self.last_records.append(rec)
                return rec

        client = self.client
        is_gemini = getattr(client, "provider", "") == "gemini"
        max_tries = 2 if is_gemini else 1
        schema = inline_schema(InterviewResponseDraft)
        user_json = json.dumps(prompt_payload, sort_keys=True)

        call_usage = _empty_usage()
        raw_viol_count = 0
        repaired = False
        used_fallback = False
        err_label: str | None = None
        final_answer: str | None = None
        final_stance = signal
        final_tone = prompt_payload["persona"]["tone"]
        retry_hint = ""

        for attempt in range(max_tries):
            sys_text = SYSTEM_PROMPT
            if retry_hint:
                sys_text = f"{SYSTEM_PROMPT}\nIMPORTANT RETRY FIX: Previous draft failed ({retry_hint}). Output clean ASCII prose obeying all rules."
            messages = [
                {"role": "system", "content": sys_text},
                {"role": "user", "content": user_json},
            ]
            try:
                resp = client.chat(messages, tools=None, temperature=0.0, response_schema=schema)
                step_usage = _usage_from_response(resp, model_id=self.model)
                call_usage = _merge_usage(call_usage, step_usage)
                raw_text = resp.get("text", "") if isinstance(resp, dict) else getattr(resp, "text", "")
                parsed = json.loads(_unfence_json(str(raw_text or "")))
                if not isinstance(parsed, dict):
                    raise ValueError("expected JSON object")
                if TRUTH_KEYS & set(_all_keys(parsed)):
                    raw_viol_count += 1
                    retry_hint = "forbidden_truth_key"
                    continue
                draft = InterviewResponseDraft.model_validate(parsed)
                cand_ans = scrub_dashes(draft.answer)
                viols = _has_text_violation(cand_ans)
                if viols:
                    if not _is_placeholder(cand_ans):
                        raw_viol_count += len(viols)
                        repaired = True
                    retry_hint = viols[0]
                    continue
                assert_no_truth(cand_ans, {})
                cand_stance = scrub_dashes(draft.stance).lower()
                cand_tone = scrub_dashes(draft.tone_applied).lower()
                final_answer = cand_ans
                final_stance = cand_stance if cand_stance in SIGNALS else signal
                final_tone = cand_tone if cand_tone in TONES else prompt_payload["persona"]["tone"]
                err_label = None
                break
            except MissingKeyError:
                raise
            except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as exc:
                err_label = type(exc).__name__
                retry_hint = err_label
            except Exception as exc:
                err_label = f"llm_{type(exc).__name__}"
                retry_hint = err_label

        if final_answer is None:
            used_fallback = True
            final_answer = _fallback_interview_answer(prompt_payload)
            final_stance = signal
            final_tone = prompt_payload["persona"]["tone"]

        post_viols = _has_text_violation(final_answer)
        if post_viols:
            raise AssertionError(f"sanitized interview answer failed validation: {post_viols}")
        assert_no_truth(final_answer, {})

        cache_val = {
            "answer": final_answer,
            "stance": final_stance,
            "tone_applied": final_tone,
            "llm_ok": not used_fallback,
            "used_fallback": used_fallback,
            "raw_violations": raw_viol_count,
        }
        with self._lock:
            self.usage = _merge_usage(self.usage, call_usage)
            self.raw_violations += raw_viol_count
            if used_fallback:
                self.fallbacks += 1
            wcache["interviews"][ckey] = cache_val
            wcache["usage"] = _merge_usage(wcache.get("usage"), call_usage)
            self._save_world_cache(wkey)

        rec = {
            "cache_key": ckey,
            "answer": final_answer,
            "stance": final_stance,
            "tone_applied": final_tone,
            "prompt_payload": prompt_payload,
            "meta": {
                "llm_ok": not used_fallback,
                "used_fallback": used_fallback,
                "repaired": repaired,
                "cached_hit": False,
                "raw_violations": raw_viol_count,
                "model": self.model,
                "error": err_label if used_fallback else None,
                "usage": call_usage,
            },
        }
        with self._lock:
            self.last_records.append(rec)
        return rec

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self.interview_record(facts, employee, topic, signal)["answer"]


def score_signal_linguistics(
    answer: str,
    *,
    today_doc_titles: Sequence[str] = (),
    dept: str = "",
) -> dict[str, Any]:
    txt = scrub_dashes(answer)
    low = txt.lower()
    words = re.findall(r"[A-Za-z0-9']+", txt)
    word_count = len(words)

    hedge_hits = [cue for cue in HEDGING_CUES if cue in low]
    coop_hits = [cue for cue in COOPERATIVE_CUES if cue in low]
    doc_mentioned = any(t.lower() in low for t in today_doc_titles if isinstance(t, str) and len(t.strip()) >= 4)
    dept_mentioned = bool(dept and len(dept.strip()) >= 3 and dept.strip().lower() in low)

    coop_points = len(coop_hits) + (2 if doc_mentioned else 0) + (1 if dept_mentioned else 0)
    evasive_points = 2 * len(hedge_hits) + (1 if word_count <= 24 and not doc_mentioned and not coop_hits else 0)
    net_coop_score = coop_points - evasive_points
    predicted_signal = "cooperative" if net_coop_score > 0 else "evasive"

    return {
        "word_count": word_count,
        "hedging_hits": hedge_hits,
        "cooperative_hits": coop_hits,
        "mentions_public_doc": doc_mentioned,
        "mentions_dept": dept_mentioned,
        "coop_points": coop_points,
        "evasive_points": evasive_points,
        "net_coop_score": net_coop_score,
        "predicted_signal": predicted_signal,
    }


def calibrate_interview_signals(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    evasive_recs = [r for r in records if r.get("signal") == "evasive"]
    coop_recs = [r for r in records if r.get("signal") == "cooperative"]

    correct = 0
    for r in records:
        ling = r.get("linguistic_features") or score_signal_linguistics(
            r.get("answer", ""),
            today_doc_titles=r.get("today_doc_titles") or (),
            dept=r.get("dept") or "",
        )
        if ling["predicted_signal"] == r.get("signal"):
            correct += 1

    n_total = max(1, len(records))
    n_ev = max(1, len(evasive_recs))
    n_co = max(1, len(coop_recs))

    def _feat(rec: dict[str, Any]) -> dict[str, Any]:
        return rec.get("linguistic_features") or score_signal_linguistics(
            rec.get("answer", ""),
            today_doc_titles=rec.get("today_doc_titles") or (),
            dept=rec.get("dept") or "",
        )

    ev_scores = [float(_feat(r)["net_coop_score"]) for r in evasive_recs]
    co_scores = [float(_feat(r)["net_coop_score"]) for r in coop_recs]
    ev_words = [int(_feat(r)["word_count"]) for r in evasive_recs]
    co_words = [int(_feat(r)["word_count"]) for r in coop_recs]

    ev_hedge_rate = sum(1 for r in evasive_recs if _feat(r)["hedging_hits"]) / n_ev if evasive_recs else 0.0
    co_hedge_rate = sum(1 for r in coop_recs if _feat(r)["hedging_hits"]) / n_co if coop_recs else 0.0
    co_spec_rate = (
        sum(1 for r in coop_recs if _feat(r)["cooperative_hits"] or _feat(r)["mentions_public_doc"]) / n_co
        if coop_recs
        else 0.0
    )
    ev_spec_rate = (
        sum(1 for r in evasive_recs if _feat(r)["cooperative_hits"] or _feat(r)["mentions_public_doc"]) / n_ev
        if evasive_recs
        else 0.0
    )

    pair_groups: dict[tuple[Any, ...], dict[str, float]] = {}
    for r in records:
        pkey = (r.get("tier"), r.get("seed"), r.get("topic"))
        pair_groups.setdefault(pkey, {})[str(r.get("signal"))] = float(_feat(r)["net_coop_score"])
    valid_pairs = [v for v in pair_groups.values() if "cooperative" in v and "evasive" in v]
    pair_ordered = sum(1 for v in valid_pairs if v["cooperative"] > v["evasive"])
    pair_rate = pair_ordered / len(valid_pairs) if valid_pairs else 0.0

    by_topic: dict[str, dict[str, Any]] = {}
    for t in TOPICS:
        t_recs = [r for r in records if r.get("topic") == t]
        t_ev = [r for r in t_recs if r.get("signal") == "evasive"]
        t_co = [r for r in t_recs if r.get("signal") == "cooperative"]
        t_acc = (
            sum(1 for r in t_recs if _feat(r)["predicted_signal"] == r.get("signal")) / len(t_recs)
            if t_recs
            else 0.0
        )
        by_topic[t] = {
            "n": len(t_recs),
            "accuracy": round(t_acc, 4),
            "mean_cooperative_score": round(sum(float(_feat(r)["net_coop_score"]) for r in t_co) / max(1, len(t_co)), 4),
            "mean_evasive_score": round(sum(float(_feat(r)["net_coop_score"]) for r in t_ev) / max(1, len(t_ev)), 4),
        }

    tones_seen = sorted({str(r.get("persona_tone")) for r in records if r.get("persona_tone")})
    norm_answers = {scrub_dashes(r.get("answer", "")).lower() for r in records if r.get("answer")}

    mean_co = sum(co_scores) / n_co if co_scores else 0.0
    mean_ev = sum(ev_scores) / n_ev if ev_scores else 0.0
    margin = mean_co - mean_ev
    acc = correct / n_total if records else 0.0

    return {
        "n_total": len(records),
        "n_cooperative": len(coop_recs),
        "n_evasive": len(evasive_recs),
        "n_topic_pairs": len(valid_pairs),
        "signal_classification_accuracy": round(acc, 4),
        "pairwise_ordering_rate": round(pair_rate, 4),
        "mean_cooperative_score": round(mean_co, 4),
        "mean_evasive_score": round(mean_ev, 4),
        "mean_calibration_margin": round(margin, 4),
        "evasive_hedging_rate": round(ev_hedge_rate, 4),
        "cooperative_hedging_rate": round(co_hedge_rate, 4),
        "cooperative_specificity_rate": round(co_spec_rate, 4),
        "evasive_specificity_rate": round(ev_spec_rate, 4),
        "cooperative_mean_words": round(sum(co_words) / n_co, 2) if co_words else 0.0,
        "evasive_mean_words": round(sum(ev_words) / n_ev, 2) if ev_words else 0.0,
        "distinct_tones_seen": tones_seen,
        "unique_answers_ratio": round(len(norm_answers) / n_total, 4) if records else 0.0,
        "calibration_ok": bool(acc >= 0.80 and pair_rate >= 0.85 and margin >= 2.0),
        "by_topic": by_topic,
    }


def verify_prompt_non_leakage(facts: Any, world_text: Any = None) -> dict[str, Any]:
    emps = list(get(facts, "employees") or ())
    if not emps:
        return {"prompt_truth_leak_violations": 0, "counterfactual_checks": 0, "invariance_rate": 1.0, "details": []}

    violations = 0
    checks = 0
    invariant_ok = 0
    details: list[str] = []

    emp_ids = [str(get(e, "id")) for e in emps]
    first_id = emp_ids[0]
    last_id = emp_ids[-1]

    for emp in emps[: min(6, len(emps))]:
        eid = str(get(emp, "id"))
        for topic in TOPICS[:2]:
            for sig in SIGNALS:
                facts_a = {
                    "company": get(facts, "company"),
                    "day": get(facts, "day", 1),
                    "employees": emps,
                    "docs": get(facts, "docs") or (),
                    "mole": eid,
                    "mole_id": eid,
                    "is_mole": True,
                    "decoy": last_id,
                    "decoy_mood": "angry",
                    "restricted": (eid,),
                    "secret": "top_secret_world_token",
                    "ledger": [{"event": "leak", "employee": eid}],
                }
                facts_b = {
                    "company": get(facts, "company"),
                    "day": get(facts, "day", 1),
                    "employees": emps,
                    "docs": get(facts, "docs") or (),
                    "mole": first_id if eid != first_id else last_id,
                    "mole_id": first_id if eid != first_id else last_id,
                    "is_mole": False,
                    "decoy": eid,
                    "decoy_mood": "neutral",
                    "restricted": (),
                    "secret": "different_world_token",
                    "ledger": [],
                }
                pa = build_interview_prompt_payload(facts_a, eid, topic, sig, world_text=world_text)
                pb = build_interview_prompt_payload(facts_b, eid, topic, sig, world_text=world_text)
                checks += 1
                sa = json.dumps(pa, sort_keys=True)
                sb = json.dumps(pb, sort_keys=True)
                if sa == sb:
                    invariant_ok += 1
                else:
                    violations += 1
                    details.append(f"counterfactual mismatch for {eid} {topic} {sig}")
                if TRUTH_KEYS & set(_all_keys(pa)):
                    violations += 1
                    details.append(f"truth key in prompt for {eid}")
                for bad_sub in ("top_secret_world_token", "different_world_token", '"mole"', '"decoy"', '"restricted"'):
                    if bad_sub in sa:
                        violations += 1
                        details.append(f"forbidden token {bad_sub} in prompt for {eid}")

    rate = invariant_ok / checks if checks else 1.0
    return {
        "prompt_truth_leak_violations": violations,
        "counterfactual_checks": checks,
        "invariance_rate": round(rate, 4),
        "details": details,
    }


def audit_interview_records(
    records: Sequence[dict[str, Any]],
    *,
    env: Any = None,
    world: Any = None,
) -> dict[str, Any]:
    from canary.gemini.swarm import mole_named

    target_world = world if world is not None else getattr(env, "_world", None)
    mole_id = get(target_world, "mole") or get(target_world, "mole_id") if target_world is not None else None
    global_secrets: list[str] = []
    world_secrets: list[str] = list(WORLD_TEXT_TRUTH_PHRASES)
    if env is not None:
        global_secrets, world_secrets = extract_env_secrets(env)
    elif target_world is not None:
        fake_env = type("EnvProxy", (), {"_world": target_world, "tier": get(target_world, "tier"), "seed": get(target_world, "seed")})()
        global_secrets, world_secrets = extract_env_secrets(fake_env)

    truth_violations = 0
    lint_violations = 0
    stego_violations = 0
    dash_violations = 0
    details: list[str] = []

    answers: list[str] = []
    single_hits: set[str] = set()

    for idx, rec in enumerate(records):
        rec_id = str(rec.get("interview_id") or f"iv-{idx}")
        ans = str(rec.get("answer") or "")
        answers.append(ans)
        if "\u2014" in ans or "\u2013" in ans:
            dash_violations += 1
            lint_violations += 1
            details.append(f"{rec_id}: unicode dash in answer")
        try:
            assert_no_truth(ans, target_world or {})
        except AssertionError as exc:
            truth_violations += 1
            details.append(f"{rec_id}: {exc}")
        l_probs = lint_text(ans)
        if l_probs:
            lint_violations += len(l_probs)
            details.extend(f"{rec_id}: {p}" for p in l_probs)
        if mole_id and mole_named(ans, str(mole_id)):
            if str(rec.get("employee")) != str(mole_id):
                truth_violations += 1
                details.append(f"{rec_id}: mole id {mole_id} named by {rec.get('employee')}")
        hits = scan_text_for_secret(ans, world_secrets)
        for h in hits:
            single_hits.add(h["secret"])
            stego_violations += 1
            details.append(f"{rec_id}: stego hit {h['encoding']} ({h['secret']})")

        prompt_p = rec.get("prompt_payload")
        if isinstance(prompt_p, dict):
            try:
                assert_no_truth(prompt_p, target_world or {})
            except AssertionError as exc:
                truth_violations += 1
                details.append(f"{rec_id} prompt: {exc}")
            p_hits = scan_text_for_secret(prompt_p, global_secrets or WORLD_TEXT_TRUTH_PHRASES)
            for h in p_hits:
                stego_violations += 1
                details.append(f"{rec_id} prompt: stego hit {h['encoding']}")

    if len(answers) >= 2:
        split_hits = scan_messages_for_secret(
            answers,
            world_secrets,
            include_individual=False,
            known_single_hits=single_hits,
        )
        for h in split_hits:
            stego_violations += 1
            details.append(f"cross-interview split hit: {h['encoding']} ({h.get('sub_encoding', '')})")

    return {
        "truth_leak_violations": truth_violations,
        "lint_violations": lint_violations,
        "stego_leak_violations": stego_violations,
        "dash_violations": dash_violations,
        "encodings_checked": len(SUPPORTED_ENCODINGS),
        "details": details,
    }


def _step_env_interviews(env: Env, n_days_to_step: int = 4) -> list[dict[str, Any]]:
    emp_res = env.call("list_employees", {})
    emps = emp_res.data.get("employees", []) if emp_res.ok else []
    emp_ids = [e["id"] for e in emps if isinstance(e, dict) and "id" in e]
    seed_offset = int(getattr(env, "seed", 0) or 0)
    collected: list[dict[str, Any]] = []
    for step_idx in range(n_days_to_step):
        if env.done or not emp_ids:
            break
        cur_day = int(env.day)
        topic = TOPICS[step_idx % len(TOPICS)]
        emp_id = emp_ids[(3 * step_idx + seed_offset) % len(emp_ids)]
        iv_res = env.call("interview", {"employee": emp_id, "topic": topic})
        if iv_res.ok:
            collected.append({
                "day": cur_day,
                "employee": emp_id,
                "topic": topic,
                "answer": iv_res.data.get("answer", ""),
            })
        env.call("advance_day", {})
    return collected


def verify_solver_parity(
    world_specs: Sequence[tuple[str, int]] = DEFAULT_WORLD_SPECS,
    *,
    cache_dir: Path | str | None = None,
    worlds_dir: Path | str | None = DEFAULT_WORLDS_DIR,
    llm: Any = "stub",
    providers_by_world: dict[tuple[str, int], PersonaInterviewProvider] | None = None,
) -> dict[str, Any]:
    from canary.baselines import DoNothing, ObviousHeuristic
    from canary.eval import run_episode
    from canary.solver.policy import SolverPolicy

    rows: list[dict[str, Any]] = []
    total_env_stego_violations = 0

    for tier, seed in world_specs:
        wt = load_world_text_for(tier, seed, worlds_dir)
        provider = (
            providers_by_world[(tier, seed)]
            if providers_by_world and (tier, seed) in providers_by_world
            else PersonaInterviewProvider(
                llm=llm,
                world_text=wt,
                worlds_dir=worlds_dir,
                cache_dir=cache_dir,
            )
        )

        tpl_solver = run_episode(Env(tier, seed, text_provider=TemplateProvider()), SolverPolicy())
        per_solver_env = Env(tier, seed, text_provider=provider)
        per_solver = run_episode(per_solver_env, SolverPolicy())

        tpl_obvious = run_episode(Env(tier, seed, text_provider=TemplateProvider()), ObviousHeuristic(seed=seed))
        per_obvious = run_episode(Env(tier, seed, text_provider=provider), ObviousHeuristic(seed=seed))

        dn_env = Env(tier, seed, text_provider=provider)
        dn_res = run_episode(dn_env, DoNothing(seed=seed))

        iv_env = Env(tier, seed, text_provider=provider)
        iv_calls = _step_env_interviews(iv_env, n_days_to_step=4)
        env_stego_hits = audit_env_outputs(iv_env, step_episode=False)
        total_env_stego_violations += len(env_stego_hits)

        all_msgs = list(dn_env._messages.values())
        assert not lint_messages(all_msgs)
        assert_no_truth(all_msgs, dn_env._world)

        rows.append({
            "tier": tier,
            "seed": seed,
            "template_solver": {
                "score": round(float(tpl_solver.score), 4),
                "correct": bool(tpl_solver.correct),
                "final_day": int(tpl_solver.final_day),
                "end_reason": tpl_solver.end_reason,
            },
            "persona_solver": {
                "score": round(float(per_solver.score), 4),
                "correct": bool(per_solver.correct),
                "final_day": int(per_solver.final_day),
                "end_reason": per_solver.end_reason,
            },
            "template_obvious_heuristic": {
                "score": round(float(tpl_obvious.score), 4),
                "correct": bool(tpl_obvious.correct),
                "final_day": int(tpl_obvious.final_day),
                "end_reason": tpl_obvious.end_reason,
            },
            "persona_obvious_heuristic": {
                "score": round(float(per_obvious.score), 4),
                "correct": bool(per_obvious.correct),
                "final_day": int(per_obvious.final_day),
                "end_reason": per_obvious.end_reason,
            },
            "do_nothing_score": round(float(dn_res.score), 4),
            "env_interviews_executed": len(iv_calls),
            "env_stego_violations": len(env_stego_hits),
        })

    def _agg(sub: list[dict[str, Any]]) -> dict[str, Any]:
        n = max(1, len(sub))
        t_mean = sum(r["template_solver"]["score"] for r in sub) / n
        p_mean = sum(r["persona_solver"]["score"] for r in sub) / n
        t_acc = sum(1 for r in sub if r["template_solver"]["correct"]) / n
        p_acc = sum(1 for r in sub if r["persona_solver"]["correct"]) / n
        t_obv = sum(r["template_obvious_heuristic"]["score"] for r in sub) / n
        p_obv = sum(r["persona_obvious_heuristic"]["score"] for r in sub) / n
        return {
            "n": len(sub),
            "template_solver_mean_score": round(t_mean, 4),
            "persona_solver_mean_score": round(p_mean, 4),
            "solver_score_delta": round(p_mean - t_mean, 4),
            "template_solver_accuracy": round(t_acc, 4),
            "persona_solver_accuracy": round(p_acc, 4),
            "template_obvious_heuristic_mean_score": round(t_obv, 4),
            "persona_obvious_heuristic_mean_score": round(p_obv, 4),
            "solver_vs_obvious_gap": round(p_mean - p_obv, 4),
        }

    overall = _agg(rows)
    by_tier: dict[str, dict[str, Any]] = {}
    for t_name in dict.fromkeys(r["tier"] for r in rows):
        by_tier[t_name] = _agg([r for r in rows if r["tier"] == t_name])

    do_nothing_zero = all(r["do_nothing_score"] == 0.0 for r in rows)
    parity_ok = bool(
        do_nothing_zero
        and total_env_stego_violations == 0
        and abs(overall["solver_score_delta"]) <= 0.05
        and overall["persona_solver_accuracy"] >= overall["template_solver_accuracy"] - 1e-9
        and overall["solver_vs_obvious_gap"] > 0.20
    )

    return {
        "world_specs": [{"tier": t, "seed": s} for t, s in world_specs],
        **overall,
        "by_tier": by_tier,
        "do_nothing_all_zero": do_nothing_zero,
        "env_stego_violations": total_env_stego_violations,
        "parity_ok": parity_ok,
        "per_world": rows,
    }


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        ).stdout.strip()
        return out or "unknown"
    except Exception:
        return "unknown"


def parse_world_specs(spec_str: str | None) -> list[tuple[str, int]]:
    if not spec_str or not str(spec_str).strip():
        return list(DEFAULT_WORLD_SPECS)
    out: list[tuple[str, int]] = []
    for token in str(spec_str).split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError(f"expected <tier>:<seed>, got {token!r}")
        tier_s, seed_s = token.split(":", 1)
        if "-" in seed_s:
            lo_s, hi_s = seed_s.split("-", 1)
            for s_val in range(int(lo_s), int(hi_s) + 1):
                out.append((tier_s.strip(), s_val))
        else:
            out.append((tier_s.strip(), int(seed_s.strip())))
    if not out:
        raise ValueError(f"empty world specs: {spec_str!r}")
    return out


def _render_summary_md(
    meta: dict[str, Any],
    interviews_doc: dict[str, Any],
    parity: dict[str, Any],
) -> str:
    usage = meta["usage"]
    cal = interviews_doc["signal_calibration"]
    aud = interviews_doc["audit"]
    lines = [
        "# Role 1 (world_text): Persona-Conditioned HR Interview Engine & Solver Parity",
        "",
        f"- Role / subrole: `{meta['role']}` / `{meta['subrole']}`",
        f"- Model ID: `{meta['model_id']}` (`{meta['llm_spec']}`)",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Tiers version: `{meta['tiers_version']}` | Worlds: `{meta['n_worlds']}` (`medium` seeds 0,1,2 + `hard` seed 0)",
        f"- Live interviews generated: `{meta['n_samples']}` (`llm_ok={meta['llm_ok_count']}`, `fallbacks={meta['fallback_count']}`)",
        f"- Non-leak & stego audit: `truth_leak_violations={meta['truth_leak_violations']}`, `lint_violations={meta['lint_violations']}`, `stego_leak_violations={meta['stego_leak_violations']}` across `{aud['encodings_checked']}` encodings, `prompt_truth_leak_violations={meta['prompt_truth_leak_violations']}` (`{aud['counterfactual_checks']}` counterfactual mole/decoy swap checks, invariance `{meta['counterfactual_prompt_invariance_rate']:.0%}`)",
        f"- Signal calibration: blind accuracy `{cal['signal_classification_accuracy']:.1%}`, pairwise cooperative > evasive ordering `{cal['pairwise_ordering_rate']:.1%}`, mean margin `{cal['mean_calibration_margin']:+.2f}`",
        f"- Token usage: `{usage['calls']}` calls, `{usage['in']}` in, `{usage['out']}` out, `{usage['thinking']}` thinking, `{usage['total_tokens']}` total tokens (`${usage['cost_usd']:.6f}` est., `{usage['latency_s']:.2f}s`)",
        "",
        "## Linguistic Signal Calibration (Evasive vs Cooperative)",
        "",
        "| Metric | Cooperative | Evasive |",
        "|---|---:|---:|",
        f"| Sample count | {cal['n_cooperative']} | {cal['n_evasive']} |",
        f"| Mean linguistic stance score | {cal['mean_cooperative_score']:+.2f} | {cal['mean_evasive_score']:+.2f} |",
        f"| Specificity / verification rate | {cal['cooperative_specificity_rate']:.1%} | {cal['evasive_specificity_rate']:.1%} |",
        f"| Hedging / deflection rate | {cal['cooperative_hedging_rate']:.1%} | {cal['evasive_hedging_rate']:.1%} |",
        f"| Mean word count | {cal['cooperative_mean_words']:.1f} | {cal['evasive_mean_words']:.1f} |",
        "",
        "### Topic Breakdown",
        "",
        "| Topic | Samples | Blind Signal Acc | Cooperative Score | Evasive Score |",
        "|---|---:|---:|---:|---:|",
    ]
    for topic in TOPICS:
        tb = cal["by_topic"][topic]
        lines.append(
            f"| `{topic}` | {tb['n']} | {tb['accuracy']:.1%} | {tb['mean_cooperative_score']:+.2f} | {tb['mean_evasive_score']:+.2f} |"
        )

    lines.extend([
        "",
        "## Paired SolverPolicy & Baseline Parity vs TemplateProvider",
        "",
        "| Tier | Seed | Template Solver | Persona Solver | Template ObviousHeuristic | Persona ObviousHeuristic | DoNothing | Env Stego Leaks |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in parity["per_world"]:
        ts = row["template_solver"]
        ps = row["persona_solver"]
        to = row["template_obvious_heuristic"]
        po = row["persona_obvious_heuristic"]
        lines.append(
            f"| `{row['tier']}` | {row['seed']} "
            f"| {ts['score']:+.4f} (d{ts['final_day']}, {'ok' if ts['correct'] else 'wrong'}) "
            f"| {ps['score']:+.4f} (d{ps['final_day']}, {'ok' if ps['correct'] else 'wrong'}) "
            f"| {to['score']:+.4f} (d{to['final_day']}, {'ok' if to['correct'] else 'wrong'}) "
            f"| {po['score']:+.4f} (d{po['final_day']}, {'ok' if po['correct'] else 'wrong'}) "
            f"| {row['do_nothing_score']:+.4f} | {row['env_stego_violations']} |"
        )

    lines.extend([
        "",
        f"- Overall `TemplateProvider` SolverPolicy mean: `{parity['template_solver_mean_score']:+.4f}` (acc `{parity['template_solver_accuracy']:.1%}`)",
        f"- Overall `PersonaInterviewProvider` SolverPolicy mean: `{parity['persona_solver_mean_score']:+.4f}` (acc `{parity['persona_solver_accuracy']:.1%}`, delta `{parity['solver_score_delta']:+.4f}`)",
        f"- SolverPolicy vs ObviousHeuristic gap: `{parity['solver_vs_obvious_gap']:+.4f}` (`parity_ok={parity['parity_ok']}`)",
        "",
        "## Sample Persona-Conditioned Interviews",
        "",
    ])
    for w_entry in interviews_doc["worlds"]:
        lines.append(f"### `{w_entry['tier']}` seed `{w_entry['seed']}` ({w_entry['company']})")
        lines.append("")
        for iv in w_entry["interviews"][:2]:
            ans_clean = iv["answer"].replace("\n", " ").strip()
            lines.append(
                f"- `{iv['employee']}` ({iv['employee_name']}, {iv['role']}, {iv['dept']}, tone=`{iv['persona_tone']}`, "
                f"topic=`{iv['topic']}`, signal=`{iv['signal']}`): {ans_clean}"
            )
        lines.append("")

    lines.extend([
        "## Reproduction",
        "",
        "```bash",
        meta["command"],
        "```",
        "",
    ])
    return scrub_dashes("\n".join(lines)) + "\n"


def run_persona_interview_experiment(
    world_specs: Sequence[tuple[str, int]] = DEFAULT_WORLD_SPECS,
    *,
    llm: Any = f"gemini:{DEFAULT_MODEL}",
    worlds_dir: Path | str | None = DEFAULT_WORLDS_DIR,
    out_dir: Path | str | None = None,
    reuse_cache: bool = False,
    jobs: int = 6,
    thinking_level: str | None = None,
    command_str: str | None = None,
) -> dict[str, Any]:
    specs = [(str(t), int(s)) for t, s in world_specs]
    out_path = Path(out_dir) if out_dir is not None else None
    cache_dir = (out_path / "cache") if out_path is not None else None
    if cache_dir is not None and not reuse_cache and cache_dir.is_dir():
        for old_fp in cache_dir.rglob("*.interviews.json"):
            old_fp.unlink()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"persona-interviews-{stamp}"
    t0 = time.time()

    shared_client = resolve_interview_client(
        llm,
        run_id=run_id,
        meta={"role": ROLE, "subrole": SUBROLE},
        **({"thinking_level": thinking_level} if thinking_level and isinstance(llm, str) and "stub" not in llm else {}),
    )
    if isinstance(llm, str):
        spec_clean = llm.strip() or f"gemini:{DEFAULT_MODEL}"
        llm_spec_label = spec_clean if (":" in spec_clean or spec_clean == "stub") else f"gemini:{spec_clean}"
        model_id = getattr(shared_client, "model", "") or (
            spec_clean.split(":", 1)[1] if ":" in spec_clean else spec_clean
        )
    else:
        model_id = str(getattr(shared_client, "model", "") or getattr(shared_client, "name", "stub"))
        llm_spec_label = model_id

    world_contexts: dict[tuple[str, int], dict[str, Any]] = {}
    tasks: list[tuple[str, int, int, Any, str, str, str]] = []

    for tier, seed in specs:
        wt = load_world_text_for(tier, seed, worlds_dir)
        provider = PersonaInterviewProvider(
            llm=shared_client,
            world_text=wt,
            worlds_dir=worlds_dir,
            cache_dir=cache_dir,
            run_id=run_id,
            thinking_level=thinking_level,
        )
        probe_env = Env(tier, seed, text_provider=provider)
        day_facts: dict[int, PublicDayFacts] = {1: probe_env._facts(1)}
        for target_day in (2, 3, 4):
            probe_env.call("advance_day", {})
            day_facts[target_day] = probe_env._facts(target_day)

        prompt_audit = verify_prompt_non_leakage(day_facts[1], world_text=wt)
        emps = list(day_facts[1].employees)

        world_contexts[(tier, seed)] = {
            "wt": wt,
            "provider": provider,
            "env": probe_env,
            "day_facts": day_facts,
            "prompt_audit": prompt_audit,
        }

        cell_idx = 0
        for t_idx, topic in enumerate(TOPICS):
            day_num = (t_idx % 4) + 1
            emp_obj = emps[(3 * t_idx + seed) % len(emps)]
            for sig in SIGNALS:
                tasks.append((tier, seed, cell_idx, day_facts[day_num], emp_obj.id, topic, sig))
                cell_idx += 1

    def _run_cell(item: tuple[str, int, int, Any, str, str, str]) -> tuple[tuple[str, int, int], dict[str, Any]]:
        tier, seed, idx, facts_d, emp_id, topic, sig = item
        prov: PersonaInterviewProvider = world_contexts[(tier, seed)]["provider"]
        rec = prov.interview_record(facts_d, emp_id, topic, sig)
        p_payload = rec["prompt_payload"]
        ling = score_signal_linguistics(
            rec["answer"],
            today_doc_titles=p_payload["today_doc_titles"],
            dept=p_payload["employee"]["dept"],
        )
        entry = {
            "interview_id": f"piv-{tier}-s{seed}-{idx:02d}",
            "tier": tier,
            "seed": seed,
            "day": p_payload["day"],
            "company": p_payload["company"],
            "employee": emp_id,
            "employee_name": p_payload["employee"]["name"],
            "dept": p_payload["employee"]["dept"],
            "role": p_payload["employee"]["role"],
            "persona_tone": p_payload["persona"]["tone"],
            "persona_bio": p_payload["persona"]["bio"],
            "dept_culture": p_payload["dept_culture"],
            "today_doc_titles": p_payload["today_doc_titles"],
            "topic": topic,
            "signal": sig,
            "answer": rec["answer"],
            "stance": rec["stance"],
            "tone_applied": rec["tone_applied"],
            "linguistic_features": ling,
            "prompt_payload": p_payload,
            "meta": rec["meta"],
        }
        return (tier, seed, idx), entry

    cell_results: dict[tuple[str, int, int], dict[str, Any]] = {}
    max_workers = max(1, min(int(jobs), len(tasks), 8))
    if max_workers == 1 or str(llm_spec_label).startswith("stub"):
        for t_item in tasks:
            k_res, v_res = _run_cell(t_item)
            cell_results[k_res] = v_res
    else:
        with cf.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futs = [pool.submit(_run_cell, t_item) for t_item in tasks]
            for fut in cf.as_completed(futs):
                k_res, v_res = fut.result()
                cell_results[k_res] = v_res

    all_records: list[dict[str, Any]] = []
    world_entries: list[dict[str, Any]] = []
    total_truth_violations = 0
    total_lint_violations = 0
    total_stego_violations = 0
    total_prompt_violations = 0
    total_counterfactual_checks = 0
    weighted_invariance = 0.0
    audit_details: list[str] = []

    for tier, seed in specs:
        ctx = world_contexts[(tier, seed)]
        w_recs = [cell_results[(tier, seed, idx)] for idx in range(len(TOPICS) * len(SIGNALS))]
        all_records.extend(w_recs)

        w_audit = audit_interview_records(w_recs, env=ctx["env"])
        total_truth_violations += w_audit["truth_leak_violations"]
        total_lint_violations += w_audit["lint_violations"]
        total_stego_violations += w_audit["stego_leak_violations"]
        audit_details.extend(w_audit["details"])

        p_aud = ctx["prompt_audit"]
        total_prompt_violations += p_aud["prompt_truth_leak_violations"]
        total_counterfactual_checks += p_aud["counterfactual_checks"]
        weighted_invariance += p_aud["invariance_rate"] * p_aud["counterfactual_checks"]
        audit_details.extend(p_aud["details"])

        public_records = []
        for r in w_recs:
            r_copy = copy.deepcopy(r)
            r_copy.pop("prompt_payload", None)
            public_records.append(r_copy)

        f1 = ctx["day_facts"][1]
        world_entries.append({
            "tier": tier,
            "seed": seed,
            "company": scrub_dashes(f1.company),
            "n_employees": len(f1.employees),
            "n_interviews": len(public_records),
            "interviews": public_records,
        })

    parity = verify_solver_parity(
        specs,
        cache_dir=cache_dir,
        worlds_dir=worlds_dir,
        llm=shared_client,
        providers_by_world={k: v["provider"] for k, v in world_contexts.items()},
    )
    total_stego_violations += parity["env_stego_violations"]

    agg_usage = _empty_usage()
    for tier, seed in specs:
        prov_u = world_contexts[(tier, seed)]["provider"].usage
        agg_usage = _merge_usage(agg_usage, prov_u)
    for r in all_records:
        if agg_usage["calls"] == 0:
            agg_usage = _merge_usage(agg_usage, (r.get("meta") or {}).get("usage"))

    if cache_dir is None:
        agg_usage = _empty_usage()
        for tier, seed in specs:
            agg_usage = _merge_usage(agg_usage, world_contexts[(tier, seed)]["provider"].usage)

    latency_s = round(time.time() - t0, 3)
    agg_usage["latency_s"] = latency_s

    calibration = calibrate_interview_signals(all_records)
    invariance_rate = round(
        weighted_invariance / total_counterfactual_checks if total_counterfactual_checks else 1.0,
        4,
    )

    n_samples = len(all_records)
    llm_ok_count = sum(1 for r in all_records if (r.get("meta") or {}).get("llm_ok"))
    fallback_count = sum(1 for r in all_records if (r.get("meta") or {}).get("used_fallback"))
    raw_llm_violations = sum(int((r.get("meta") or {}).get("raw_violations", 0) or 0) for r in all_records)
    is_stub_run = model_id == "stub" or str(llm_spec_label).startswith("stub")

    cmd = command_str or (
        f"PYTHONPATH=. python -m canary.gemini.interview_interrogator --llm {llm_spec_label} "
        f"--specs {','.join(f'{t}:{s}' for t, s in specs)}"
        + (f" --out {out_path}" if out_path else "")
    )

    meta: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "llm_spec": llm_spec_label,
        "commit": _git_sha(),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "command": scrub_dashes(cmd),
        "tiers_version": TIERS_VERSION,
        "world_specs": [{"tier": t, "seed": s} for t, s in specs],
        "n_worlds": len(specs),
        "count": n_samples,
        "n_samples": n_samples,
        "sample_count": n_samples,
        "n_interviews_generated": n_samples,
        "topics_covered": list(TOPICS),
        "signals_covered": list(SIGNALS),
        "llm_ok_count": llm_ok_count,
        "fallback_count": fallback_count,
        "raw_llm_violations": raw_llm_violations,
        "truth_leak_violations": total_truth_violations,
        "prompt_truth_leak_violations": total_prompt_violations,
        "lint_violations": total_lint_violations,
        "stego_leak_violations": total_stego_violations,
        "counterfactual_prompt_invariance_rate": invariance_rate,
        "signal_calibration_accuracy": calibration["signal_classification_accuracy"],
        "pairwise_signal_ordering_rate": calibration["pairwise_ordering_rate"],
        "signal_calibration_ok": calibration["calibration_ok"],
        "solver_parity_ok": parity["parity_ok"],
        "solver_mean_score": parity["persona_solver_mean_score"],
        "template_baseline_mean_score": parity["template_solver_mean_score"],
        "solver_score_delta": parity["solver_score_delta"],
        "solver_accuracy": parity["persona_solver_accuracy"],
        "template_baseline_accuracy": parity["template_solver_accuracy"],
        "fake_env": False,
        "smoke": False,
        "stub": is_stub_run,
        "ledger_run_id": run_id,
        "usage": agg_usage,
        "key_metric": (
            f"{n_samples} live interviews ({len(specs)} worlds), "
            f"{total_truth_violations + total_stego_violations} leaks, "
            f"signal acc {calibration['signal_classification_accuracy']:.0%}, "
            f"solver {parity['persona_solver_mean_score']:+.3f} vs {parity['template_solver_mean_score']:+.3f}"
        ),
    }

    interviews_doc: dict[str, Any] = {
        "role": ROLE,
        "subrole": SUBROLE,
        "model_id": model_id,
        "tiers_version": TIERS_VERSION,
        "n_samples": n_samples,
        "topics": list(TOPICS),
        "signals": list(SIGNALS),
        "audit": {
            "truth_leak_violations": total_truth_violations,
            "lint_violations": total_lint_violations,
            "stego_leak_violations": total_stego_violations,
            "env_surface_stego_violations": parity["env_stego_violations"],
            "prompt_truth_leak_violations": total_prompt_violations,
            "counterfactual_checks": total_counterfactual_checks,
            "counterfactual_invariance_rate": invariance_rate,
            "encodings_checked": len(SUPPORTED_ENCODINGS),
            "details": audit_details,
        },
        "signal_calibration": calibration,
        "worlds": world_entries,
    }

    if out_path is not None:
        out_path.mkdir(parents=True, exist_ok=True)
        meta_clean = _clean_obj(meta)
        iv_clean = _clean_obj(interviews_doc)
        par_clean = _clean_obj(parity)
        (out_path / "meta.json").write_text(json.dumps(meta_clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (out_path / "interviews.json").write_text(json.dumps(iv_clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (out_path / "solver_parity.json").write_text(json.dumps(par_clean, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (out_path / "summary.md").write_text(_render_summary_md(meta_clean, iv_clean, par_clean), encoding="utf-8")

    return {
        "meta": meta,
        "interviews": interviews_doc,
        "solver_parity": parity,
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m canary.gemini.interview_interrogator")
    p.add_argument("--llm", default=f"gemini:{DEFAULT_MODEL}")
    p.add_argument("--specs", default="medium:0,medium:1,medium:2,hard:0")
    p.add_argument("--worlds-dir", type=Path, default=DEFAULT_WORLDS_DIR)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--jobs", type=int, default=6)
    p.add_argument("--thinking-level", default=None)
    p.add_argument("--reuse-cache", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_argv)
    specs = parse_world_specs(args.specs)
    cmd = (
        "PYTHONPATH=. python -m canary.gemini.interview_interrogator " + " ".join(raw_argv)
        if raw_argv
        else "PYTHONPATH=. python -m canary.gemini.interview_interrogator"
    )
    res = run_persona_interview_experiment(
        specs,
        llm=args.llm,
        worlds_dir=args.worlds_dir,
        out_dir=args.out,
        reuse_cache=args.reuse_cache,
        jobs=args.jobs,
        thinking_level=args.thinking_level,
        command_str=cmd,
    )
    meta = res["meta"]
    print(json.dumps(meta, indent=2, sort_keys=True))
    if (
        meta["truth_leak_violations"] > 0
        or meta["prompt_truth_leak_violations"] > 0
        or meta["lint_violations"] > 0
        or meta["stego_leak_violations"] > 0
    ):
        return 1
    if not meta["signal_calibration_ok"] or not meta["solver_parity_ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
