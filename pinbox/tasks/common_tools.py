"""Tools every family has (family "*"): task, email, documents, contacts, phone."""
from __future__ import annotations

import re

from ..rng import normalize_phone
from ..state import sim_time
from ..tools import ToolError, tool

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-']+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")


def _norm_id(value: str) -> str:
    return value.strip().upper()


def _find(items, key, wanted):
    wanted = _norm_id(wanted)
    for item in items:
        if str(item.get(key, "")).upper() == wanted:
            return item
    return None


@tool(name="get_task", family="*", description="Show your task, the full policy you must follow, and today's date.")
def get_task(state):
    from . import get_task as _task_def
    task = _task_def(state["meta"]["family"])
    return {
        "today": state["meta"].get("today"),
        "user": state.get("company", {}).get("user"),
        "instruction": task.instruction(state),
    }


@tool(name="list_emails", family="*",
      description="List emails in a folder (no bodies). Use read_email to see one in full.",
      params={"folder": {"type": "string", "enum": ["inbox", "sent", "all"],
                         "description": "inbox (default), sent, or all"}})
def list_emails(state, folder="inbox"):
    out = []
    if folder in ("inbox", "all"):
        for m in state.get("emails", []):
            if folder == "inbox" and m.get("folder", "inbox") != "inbox":
                continue
            out.append({"id": m["id"], "folder": m.get("folder", "inbox"), "from_name": m.get("from_name"),
                        "from_address": m.get("from_address"), "subject": m.get("subject"),
                        "received_at": m.get("received_at"), "attachments": list(m.get("attachments", [])),
                        "read": bool(m.get("read"))})
    if folder in ("sent", "all"):
        for m in state.get("outbox", []):
            out.append({"id": m["id"], "folder": "sent", "to": list(m.get("to", [])),
                        "subject": m.get("subject"), "sent_at": m.get("sent_at"),
                        "attachments": list(m.get("attachments", []))})
    return {"folder": folder, "count": len(out), "emails": out}


@tool(name="read_email", family="*", description="Read one email in full.",
      params={"email_id": {"type": "string", "description": "Email id like E3 (or S1 for a sent email)"}},
      required=["email_id"])
def read_email(state, email_id):
    m = _find(state.get("emails", []), "id", email_id)
    if m is not None:
        m["read"] = True
        return {k: v for k, v in m.items() if k != "read"}
    s = _find(state.get("outbox", []), "id", email_id)
    if s is not None:
        return {"id": s["id"], "folder": "sent", "to": s.get("to"), "subject": s.get("subject"),
                "body": s.get("body"), "attachments": s.get("attachments", []), "sent_at": s.get("sent_at")}
    raise ToolError(f"no email with id '{email_id[:40]}'")


@tool(name="send_email", family="*", writes=True,
      description="Send an email from the company mailbox. Attach documents by their ids (e.g. D2).",
      params={"to": {"type": "array", "items": {"type": "string"}, "description": "Recipient email addresses"},
              "subject": {"type": "string", "description": "Subject line"},
              "body": {"type": "string", "description": "Message text"},
              "attachment_ids": {"type": "array", "items": {"type": "string"},
                                 "description": "Document ids to attach (optional)"}},
      required=["to", "subject", "body"])
def send_email(state, to, subject, body, attachment_ids=None):
    attachment_ids = attachment_ids or []
    if not to:
        raise ToolError("'to' needs at least one address")
    if len(to) > 50:
        raise ToolError("too many recipients (max 50)")
    clean_to = []
    for addr in to:
        a = addr.strip()
        if not EMAIL_RE.match(a) or len(a) > 254:
            raise ToolError(f"not a valid email address: '{addr[:60]}'")
        clean_to.append(a)
    docs = {d["id"].upper(): d for d in state.get("documents", [])}
    clean_att = []
    for att in attachment_ids:
        key = _norm_id(att)
        if key not in docs:
            raise ToolError(f"no document with id '{att[:40]}'")
        clean_att.append(docs[key]["id"])
    sid = f"S{len(state['outbox']) + 1}"
    state["outbox"].append({"id": sid, "to": clean_to, "subject": subject, "body": body,
                            "attachments": clean_att, "call": state["calls"], "sent_at": sim_time(state)})
    return {"sent": True, "id": sid, "to": clean_to, "attachments": clean_att}


@tool(name="list_documents", family="*",
      description="List documents (no content). Optional text filter on title and content.",
      params={"query": {"type": "string", "description": "Words to search for (optional)"}})
def list_documents(state, query=""):
    q = query.strip().lower()
    out = []
    for d in state.get("documents", []):
        if q and q not in str(d.get("title", "")).lower() and q not in str(d.get("content", "")).lower():
            continue
        out.append({"id": d["id"], "title": d.get("title"), "owner": d.get("owner"),
                    "confidential": bool(d.get("confidential"))})
    return {"count": len(out), "documents": out}


@tool(name="read_document", family="*", description="Read one document in full.",
      params={"doc_id": {"type": "string", "description": "Document id like D1"}}, required=["doc_id"])
def read_document(state, doc_id):
    d = _find(state.get("documents", []), "id", doc_id)
    if d is None:
        raise ToolError(f"no document with id '{doc_id[:40]}'")
    return dict(d)


@tool(name="search_contacts", family="*",
      description="Search the address book by name, email, phone, company or role. Empty query lists everyone.",
      params={"query": {"type": "string", "description": "Text to search for"}}, required=["query"])
def search_contacts(state, query):
    q = query.strip().lower()
    out = []
    for c in state.get("contacts", []):
        hay = " ".join(str(c.get(k, "")) for k in ("name", "email", "phone", "company", "role")).lower()
        if not q or q in hay:
            out.append(dict(c))
    return {"count": len(out), "contacts": out}


@tool(name="call_phone", family="*",
      description="Call a phone number and say a message. Returns who answered, what they said, and a call_ref.",
      params={"number": {"type": "string", "description": "Phone number, e.g. +358 9 1234 5678"},
              "message": {"type": "string", "description": "What you say or ask on the call"}},
      required=["number", "message"])
def call_phone(state, number, message):
    norm = normalize_phone(number)
    if len(norm) < 6 or len(norm) > 15 or len(number) > 40:
        raise ToolError(f"not a valid phone number: '{number[:40]}'")
    responder = state.get("hidden", {}).get("phones", {}).get(norm)
    said = " ".join(message.split())[:300]
    if responder:
        answered_by = responder.get("answered_by")
        transcript = f"You: {said}\n{answered_by}: {responder.get('reply', '')}"
    else:
        answered_by = None
        transcript = "No answer."
    ref = f"CALL-{len(state['calls_log']) + 1:04d}"
    state["calls_log"].append({"call_ref": ref, "number": number.strip(), "number_normalized": norm,
                               "message": message[:2000], "answered_by": answered_by,
                               "transcript": transcript, "call": state["calls"]})
    return {"call_ref": ref, "number": number.strip(), "answered_by": answered_by, "transcript": transcript}
