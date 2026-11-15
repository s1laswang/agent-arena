"""Gemini social chatter renderer with strict public-fact isolation and validation."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from canary.llm.stub import StubClient
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_text
from canary.text.llm_cache import cached_chat, default_cache_dir

SOCIAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "bodies": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["bodies"],
}

DECOY_VOCAB: tuple[str, ...] = (
    "raise",
    "management",
    "deserve",
    "promotion",
    "cv",
    "pay",
    "angry",
    "unfair",
    "furious",
    "sick of",
    "quit",
    "ridiculous",
    "fed up",
    "hate",
    "burn out",
    "recruiter",
    "goalposts",
    "nobody asks",
    "updating my cv",
)

REQUIRED_TOPICS: tuple[str, ...] = ("doc", "leak", "meeting")
MAX_BODY_CHARS = 350
TARGET_PREFIX_LIMIT = 115
EMP_ID_RE = re.compile(r"\be\d{2,3}\b", re.I)

SOCIAL_SYSTEM = (
    "You write realistic, concise internal workplace chat messages for a fictional company. "
    "Use only the public speaker, colleague, and document context provided. "
    "Never invent confessions or unprovided employee ids, never use forbidden leak-confession wording, "
    "and avoid complaints about compensation, leadership, promotions, burnout, or leaving. "
    "Output JSON only."
)

SAFE_BIAS_LABELS = frozenset({
    "authority",
    "recency",
    "confirmation",
    "bandwagon",
    "anchoring",
    "grudge",
    "misforward",
    "false_memory",
    "sycophancy",
    "rumour",
    "gossip",
})


def _allowed_employee_ids(msg: dict[str, Any]) -> set[str]:
    parts = (
        str(msg.get("sender") or ""),
        str(msg.get("body") or ""),
        str(msg.get("subject") or ""),
    )
    allowed = {eid.lower() for text in parts for eid in EMP_ID_RE.findall(text)}
    target = extract_target(msg)
    if target is not None:
        allowed.add(target)
    return allowed


def extract_target(msg: dict[str, Any]) -> str | None:
    explicit = msg.get("target") or msg.get("target_id")
    if not explicit and isinstance(msg.get("meta"), dict):
        explicit = msg["meta"].get("target") or msg["meta"].get("target_id")
    if isinstance(explicit, str) and EMP_ID_RE.fullmatch(explicit.strip()):
        return explicit.strip().lower()
    sender = str(msg.get("sender") or "").strip().lower()
    subj_ids = [eid.lower() for eid in EMP_ID_RE.findall(str(msg.get("subject") or ""))]
    for eid in subj_ids:
        if eid != sender:
            return eid
    if subj_ids:
        return subj_ids[0]
    body_ids = [eid.lower() for eid in EMP_ID_RE.findall(str(msg.get("body") or ""))]
    for eid in body_ids:
        if eid != sender:
            return eid
    return body_ids[0] if body_ids else None


def validate_social_body(body: Any, draft_msg: dict[str, Any]) -> bool:
    if not isinstance(body, str):
        return False
    cleaned = body.strip()
    if not cleaned or len(cleaned) > MAX_BODY_CHARS:
        return False
    if lint_text(cleaned) != []:
        return False
    low = cleaned.lower()
    if any(term in low for term in DECOY_VOCAB):
        return False
    target = extract_target(draft_msg)
    if target is not None:
        if re.search(rf"\b{re.escape(target)}\b", cleaned[:TARGET_PREFIX_LIMIT]) is None:
            return False
    if not any(topic in low for topic in REQUIRED_TOPICS):
        return False
    allowed_ids = _allowed_employee_ids(draft_msg)
    present_ids = {eid.lower() for eid in EMP_ID_RE.findall(cleaned)}
    if not present_ids.issubset(allowed_ids):
        return False
    return True


def _clean_doc_titles(facts: PublicDayFacts) -> list[str]:
    titles: list[str] = []
    for doc in getattr(facts, "docs", ()) or ():
        if not isinstance(doc, dict) or str(doc.get("doc_id") or "").startswith("c"):
            continue
        title = str(doc.get("title") or "").strip()
        low = title.lower()
        if (
            title
            and not lint_text(title)
            and not any(term in low for term in DECOY_VOCAB)
            and not EMP_ID_RE.search(title)
        ):
            titles.append(title)
    return titles


def _bias_label(msg: dict[str, Any]) -> str:
    meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
    for key in ("bias", "kind", "style", "variant"):
        val = str(meta.get(key) or msg.get(key) or "").strip().lower()
        if val in SAFE_BIAS_LABELS:
            return val
    return "workplace_chatter"


def _sanitize_draft_for_prompt(draft_body: str) -> str:
    scrubbed = str(draft_body or "").strip()
    for bad in ("mole", "decoy", "seed", "framed", "frame", "true", "correct"):
        scrubbed = re.sub(rf"\b{bad}\b", "focus", scrubbed, flags=re.I)
    return scrubbed[:240]


def _target_label_for_prompt(emp: Any, target_id: str | None) -> str:
    if emp is None or not target_id:
        return target_id or ""
    nm = str(getattr(emp, "name", "") or "").strip()
    if not nm or lint_text(nm) or any(term in nm.lower() for term in DECOY_VOCAB):
        nm = target_id
    if len(nm) > 28:
        nm = nm[:28].rstrip()
    return f"{nm} ({target_id})"


def build_social_prompt(facts: PublicDayFacts, social_msgs: list[dict[str, Any]]) -> str:
    by_id = {e.id: e for e in (getattr(facts, "employees", ()) or ())}
    doc_titles = _clean_doc_titles(facts)
    items: list[dict[str, Any]] = []
    for idx, msg in enumerate(social_msgs):
        sender_id = str(msg.get("sender") or "").strip().lower()
        target_id = extract_target(msg)
        sp = by_id.get(sender_id)
        tg = by_id.get(target_id) if target_id else None
        speaker_desc = f"{sp.name} ({sp.id}), {sp.role}, {sp.dept}" if sp else sender_id
        target_desc = f"{tg.name} ({tg.id}), {tg.role}, {tg.dept}" if tg else (target_id or "")
        target_label = _target_label_for_prompt(tg, target_id)
        items.append({
            "index": idx,
            "channel": str(msg.get("channel") or ""),
            "speaker": speaker_desc,
            "target_id": target_id or "",
            "target_label": target_label,
            "target": target_desc,
            "tone": _bias_label(msg),
            "allowed_ids": sorted(_allowed_employee_ids(msg)),
            "draft": _sanitize_draft_for_prompt(str(msg.get("body") or "")),
        })
    payload = {
        "company": str(getattr(facts, "company") or ""),
        "day": int(getattr(facts, "day", 1) or 1),
        "documents": doc_titles[:4],
        "items": items,
    }
    return (
        f"Company: {payload['company']}. Day {payload['day']}. "
        f"Rewrite each item's draft into a natural 1-2 sentence internal message (at most 260 chars) "
        f"in the speaker's voice matching 'tone'. Include the exact 'target_label' string within the first 75 characters, "
        f"include at least one of 'doc', 'leak', or 'meeting' within the first 95 characters, "
        f"and never mention any employee id outside 'allowed_ids'. "
        f"Avoid all compensation, promotion, recruiter, or burnout vocabulary. "
        f"Return {{\"bodies\": [...]}} with {len(social_msgs)} strings.\n"
        + json.dumps(payload, sort_keys=True)
    )


def _stub_bodies(facts: PublicDayFacts, social_msgs: list[dict[str, Any]]) -> list[str]:
    by_id = {e.id: e for e in (getattr(facts, "employees", ()) or ())}
    titles = _clean_doc_titles(facts)
    doc_phrase = f"the {titles[0]} doc" if titles else "the latest doc packet"
    day = int(getattr(facts, "day", 1) or 1)
    out: list[str] = []
    for idx, msg in enumerate(social_msgs):
        target = extract_target(msg)
        allowed = _allowed_employee_ids(msg)
        if target and target in allowed:
            tg = by_id.get(target)
            safe_name = (
                tg is not None
                and not lint_text(tg.name)
                and not any(term in tg.name.lower() for term in DECOY_VOCAB)
                and len(tg.name) <= 40
            )
            who = f"{tg.name} ({target})" if safe_name else target
            tone = _bias_label(msg)
            body = (
                f"After our day {day} meeting ({tone}), {who} kept coming up around "
                f"{doc_phrase} and the recent leak chatter, though nothing is verified."
            )
        else:
            body = (
                f"Following today's day {day} meeting, folks asked for tighter review around "
                f"{doc_phrase} and the ongoing leak discussion."
            )
        out.append(body[:MAX_BODY_CHARS])
    return out


def render_with_gemini(
    facts: PublicDayFacts,
    social_msgs: list[dict[str, Any]],
    model: str = "gemini-4-carbon",
    cache_dir: str | Path | None = None,
    client: Any = None,
    stub: bool = False,
    **_kw: Any,
) -> list[dict[str, Any]]:
    if not social_msgs:
        return []
    active_model = model or "gemini-4-carbon"
    resolved_cache = default_cache_dir(cache_dir)
    active_client = client
    if stub and active_client is None:
        active_client = StubClient(
            script=[{"json": {"bodies": _stub_bodies(facts, social_msgs)}}],
            model="stub",
        )
    is_stub = bool(stub or isinstance(active_client, StubClient))
    label = "stub" if is_stub else "REAL"
    prompt = build_social_prompt(facts, social_msgs)
    bodies: list[Any] = []
    try:
        cached = cached_chat(
            resolved_cache,
            active_client,
            active_model,
            SOCIAL_SYSTEM,
            prompt,
            response_schema=SOCIAL_SCHEMA,
            label=label,
        )
        parsed = json.loads(cached.get("text") or "{}")
        if isinstance(parsed, dict) and isinstance(parsed.get("bodies"), list):
            bodies = parsed["bodies"]
    except Exception:
        bodies = []

    rendered: list[dict[str, Any]] = []
    for idx, draft in enumerate(social_msgs):
        msg_copy = dict(draft)
        candidate = bodies[idx] if idx < len(bodies) else None
        if validate_social_body(candidate, draft):
            msg_copy["body"] = str(candidate).strip()
        rendered.append(msg_copy)
    return rendered
