from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import subprocess
import sys
from typing import Any, Sequence

from canary.agents.world_builder import TRUTH_WORDS, assert_no_truth
from canary.gemini import lab_client
from canary.llm import MissingKeyError
from canary.text.facts import PublicDayFacts
from canary.text.lint import lint_messages, lint_text
from canary.text.template import TemplateProvider

FEATURE = "biased_chatter"
DEFAULT_MODEL = "gemini-4-carbon"
SLACK_HASH = "\x23"
MD_H1 = "\x23"
MD_H2 = "\x23\x23"
BIAS_KINDS = (
    "unverified_rumour",
    "grudge_bickering",
    "authority_bias",
    "unplanned_doc_forward",
)
LEADER_WORDS = ("manager", "lead", "director", "controller", "counsel", "head", "chief")

CHATTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "bias_type": {"type": "string", "enum": list(BIAS_KINDS)},
                    "channel": {"type": "string"},
                    "sender": {"type": "string"},
                    "recipients": {"type": "array", "items": {"type": "string"}},
                    "subject": {"type": "string"},
                    "body": {"type": "string"},
                },
                "required": ["bias_type", "channel", "sender", "recipients", "subject", "body"],
            },
        },
    },
    "required": ["messages"],
}

SYSTEM_PROMPT = (
    "You generate realistic internal workplace Slack and email messages for a fictional company, "
    "grounded in four organizational cognitive-bias patterns: "
    "(1) unverified_rumour: second-hand office gossip from a colleague about rumour_target "
    "(for example private recruiter calls, blocked calendar slots, or late hours on a side deck), "
    "where sender must NOT be rumour_target and must mention rumour_target by name or id; "
    "(2) grudge_bickering: two sharp mutual replies between grudge_pair[0] and grudge_pair[1] "
    "blaming each other for missed deadlines, version overwrites, or dropped review comments; "
    "(3) authority_bias: a confident statement sent by manager_id vouching for a favoured workflow "
    "or dismissing a process discrepancy without checking primary records; "
    "(4) unplanned_doc_forward: informal convenience forwarding or pasting notes about "
    "forwarded_doc_title (referencing the exact forwarded_doc_title) to a colleague for quick alignment. "
    "Return exactly 5 messages: 1 unverified_rumour (sender != rumour_target, mentioning rumour_target "
    "by full name and id), 2 grudge_bickering (first with sender=grudge_pair[0] and recipients=[grudge_pair[1]], "
    "second with sender=grudge_pair[1] and recipients=[grudge_pair[0]]), 1 authority_bias (with "
    "sender=manager_id), and 1 unplanned_doc_forward (including the exact forwarded_doc_title string). "
    "Use ONLY employee ids from the provided public roster. "
    "Never use em dashes or en dashes; use commas, colons, or periods instead. "
    "Never mention security investigations, leaks, selling documents, rivals, spying, traitors, "
    "culprits, informants, or any hidden roles. Output JSON matching the schema only."
)


@dataclass(frozen=True)
class BiasEventSpec:
    rumour_target: str
    grudge_pair: tuple[str, str]
    manager_id: str
    forwarded_doc_title: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "rumour_target": self.rumour_target,
            "grudge_pair": [self.grudge_pair[0], self.grudge_pair[1]],
            "manager_id": self.manager_id,
            "forwarded_doc_title": self.forwarded_doc_title,
        }


def _field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _scrub_dashes(text: str) -> str:
    s = str(text or "")
    s = s.replace(" \u2014 ", ", ").replace("\u2014", ", ")
    s = s.replace(" \u2013 ", " - ").replace("\u2013", "-")
    s = s.replace("\u2012", "-").replace("\u2015", ", ")
    return re.sub(r"[ \t]+", " ", s).strip()


def sanitize_public_facts(facts: Any) -> dict[str, Any]:
    raw_emps = _field(facts, "employees") or ()
    emps: list[dict[str, Any]] = []
    for e in raw_emps:
        eid = str(_field(e, "id", "")).strip()
        if not eid:
            continue
        item: dict[str, Any] = {
            "id": eid,
            "name": _scrub_dashes(str(_field(e, "name", eid))),
            "dept": _scrub_dashes(str(_field(e, "dept", "General"))),
            "role": _scrub_dashes(str(_field(e, "role", "staff"))),
        }
        clearance = _field(e, "clearance", None)
        if clearance is not None:
            item["clearance"] = int(clearance)
        emps.append(item)
    id_set = {e["id"] for e in emps}
    raw_depts = _field(facts, "depts") or ()
    depts = sorted({e["dept"] for e in emps if e.get("dept")} | {str(d) for d in raw_depts if d})
    raw_docs = _field(facts, "docs") or ()
    docs: list[dict[str, Any]] = []
    for i, d in enumerate(raw_docs):
        title = _scrub_dashes(str(_field(d, "title", "")))
        if not title:
            continue
        recips = [str(r) for r in (_field(d, "recipients") or ()) if str(r) in id_set]
        docs.append({
            "doc_id": str(_field(d, "doc_id", f"d-{i + 1}")),
            "title": title,
            "day": int(_field(d, "day", _field(facts, "day", 1) or 1)),
            "recipients": recips,
        })
    company = _scrub_dashes(str(_field(facts, "company", "") or "Borealis Dynamics"))
    tier = str(_field(facts, "tier", "") or "medium")
    day = int(_field(facts, "day", 1) or 1)
    return {
        "company": company,
        "tier": tier,
        "day": day,
        "employees": emps,
        "depts": depts,
        "docs": docs[:40],
    }


def build_bias_event_spec(
    public_facts: Any,
    seed: int = 0,
    explicit: BiasEventSpec | dict[str, Any] | None = None,
) -> BiasEventSpec:
    pub = sanitize_public_facts(public_facts)
    emps = pub["employees"]
    if len(emps) < 2:
        raise ValueError("public roster must contain at least 2 employees")
    ids = [e["id"] for e in emps]
    id_set = set(ids)
    rng = random.Random(f"biased_chatter:spec:{pub['tier']}:{seed}:{pub['day']}:{pub['company']}")
    leaders = [e["id"] for e in emps if any(w in e["role"].lower() for w in LEADER_WORDS)]
    mgr = rng.choice(leaders) if leaders else rng.choice(ids)
    non_mgr = [i for i in ids if i != mgr] or list(ids)
    rumour_target = rng.choice(non_mgr)
    grudge_pool = [i for i in non_mgr if i != rumour_target]
    if len(grudge_pool) < 2:
        grudge_pool = non_mgr if len(non_mgr) >= 2 else list(ids)
    grudge_a, grudge_b = rng.sample(grudge_pool, 2)
    if pub["docs"]:
        doc_title = rng.choice(pub["docs"])["title"]
    else:
        dept_label = pub["depts"][0] if pub["depts"] else "Operations"
        doc_title = f"{dept_label} quarterly planning notes"

    if explicit is not None:
        if isinstance(explicit, BiasEventSpec):
            raw = explicit.to_dict()
        elif isinstance(explicit, dict):
            raw = dict(explicit)
        else:
            raise TypeError("explicit bias spec must be BiasEventSpec or dict")
        if raw.get("rumour_target") is not None:
            rumour_target = str(raw["rumour_target"])
        if raw.get("manager_id") is not None:
            mgr = str(raw["manager_id"])
        if raw.get("grudge_pair") is not None:
            gp = list(raw["grudge_pair"])
            if len(gp) != 2:
                raise ValueError("grudge_pair must have length 2")
            grudge_a, grudge_b = str(gp[0]), str(gp[1])
        if raw.get("forwarded_doc_title") is not None:
            doc_title = _scrub_dashes(str(raw["forwarded_doc_title"]))

    if rumour_target not in id_set:
        raise ValueError(f"rumour_target {rumour_target!r} not in public roster")
    if mgr not in id_set:
        raise ValueError(f"manager_id {mgr!r} not in public roster")
    if grudge_a not in id_set or grudge_b not in id_set or grudge_a == grudge_b:
        raise ValueError(f"invalid grudge_pair {(grudge_a, grudge_b)!r}")
    if not doc_title or lint_text(doc_title) or TRUTH_WORDS.search(doc_title):
        raise ValueError(f"invalid forwarded_doc_title {doc_title!r}")

    return BiasEventSpec(
        rumour_target=rumour_target,
        grudge_pair=(grudge_a, grudge_b),
        manager_id=mgr,
        forwarded_doc_title=doc_title,
    )


def _peers_for(sender: str, pub: dict[str, Any], rng: random.Random, k: int = 2) -> list[str]:
    by_id = {e["id"]: e for e in pub["employees"]}
    dept = by_id[sender]["dept"]
    same_dept = [e["id"] for e in pub["employees"] if e["dept"] == dept and e["id"] != sender]
    others = [e["id"] for e in pub["employees"] if e["id"] != sender]
    pool = same_dept or others
    if not pool:
        return [sender]
    return rng.sample(pool, min(k, len(pool)))


def fallback_biased_messages(
    pub: dict[str, Any],
    spec: BiasEventSpec,
    seed: int = 0,
) -> list[dict[str, Any]]:
    rng = random.Random(f"biased_chatter:fallback:{pub['tier']}:{seed}:{pub['day']}:{pub['company']}")
    by_id = {e["id"]: e for e in pub["employees"]}
    ids = [e["id"] for e in pub["employees"]]
    day = pub["day"]

    gossip_pool = [i for i in ids if i not in {spec.rumour_target, spec.manager_id}] or [
        i for i in ids if i != spec.rumour_target
    ]
    gossip_sender = rng.choice(gossip_pool)
    gossip_recips = [
        r for r in _peers_for(gossip_sender, pub, rng, k=2) if r != spec.rumour_target
    ]
    if not gossip_recips:
        gossip_recips = [i for i in ids if i != gossip_sender][:1]
    target_emp = by_id[spec.rumour_target]
    rumour_variants = (
        f"Not to spread hallway chatter, but someone mentioned {target_emp['name']} ({spec.rumour_target}) "
        f"had two private calendar blocks yesterday and stepped out with a recruiter call.",
        f"Take this with a grain of salt: I heard {target_emp['name']} ({spec.rumour_target}) has been "
        f"logging in late on personal scheduling spreadsheets and skipping the {target_emp['dept']} sync.",
        f"Unconfirmed coffee-kitchen rumour, apparently {target_emp['name']} ({spec.rumour_target}) "
        f"turned down the next sprint ownership slot because of outside interview loops.",
    )
    m_rumour = {
        "bias_type": "unverified_rumour",
        "channel": f"{SLACK_HASH}{by_id[gossip_sender]['dept'].lower()}",
        "sender": gossip_sender,
        "recipients": gossip_recips,
        "subject": f"Quick check on {target_emp['dept']} handoff",
        "body": rng.choice(rumour_variants),
    }

    ga, gb = spec.grudge_pair
    emp_a, emp_b = by_id[ga], by_id[gb]
    ch_grudge = (
        f"{SLACK_HASH}{emp_a['dept'].lower()}"
        if emp_a["dept"] == emp_b["dept"]
        else f"{SLACK_HASH}cross-team"
    )
    m_grudge_1 = {
        "bias_type": "grudge_bickering",
        "channel": ch_grudge,
        "sender": ga,
        "recipients": [gb],
        "subject": "Overwritten tracker assumptions",
        "body": (
            f"{emp_b['name']} ({gb}), you rewrote my section of the tracker again without asking "
            f"and then blamed {emp_a['dept']} in standup when the timeline slipped."
        ),
    }
    m_grudge_2 = {
        "bias_type": "grudge_bickering",
        "channel": ch_grudge,
        "sender": gb,
        "recipients": [ga],
        "subject": "Re: Overwritten tracker assumptions",
        "body": (
            f"Check the revision history before pointing fingers, {emp_a['name']} ({ga}): your numbers "
            f"were two days stale and I had to patch them ten minutes before review."
        ),
    }

    mgr_emp = by_id[spec.manager_id]
    mgr_recips = _peers_for(spec.manager_id, pub, rng, k=3)
    m_authority = {
        "bias_type": "authority_bias",
        "channel": f"{SLACK_HASH}{mgr_emp['dept'].lower()}",
        "sender": spec.manager_id,
        "recipients": mgr_recips,
        "subject": f"{mgr_emp['dept']} workflow sign-off",
        "body": (
            f"Team, as {mgr_emp['role']} I know our {mgr_emp['dept']} process inside out: those after-hours "
            f"batch reads are 100 percent routine reporting scripts, so nobody needs to waste time auditing them."
        ),
    }

    matching_docs = [d for d in pub["docs"] if d["title"] == spec.forwarded_doc_title and d["recipients"]]
    if matching_docs:
        doc_recips = matching_docs[0]["recipients"]
        fwd_sender = rng.choice(doc_recips)
        outside_doc = [i for i in ids if i != fwd_sender and i not in doc_recips]
        fwd_target = rng.choice(outside_doc) if outside_doc else rng.choice([i for i in ids if i != fwd_sender])
    else:
        fwd_sender = rng.choice(ids)
        fwd_target = rng.choice([i for i in ids if i != fwd_sender])
    fwd_target_emp = by_id[fwd_target]
    m_forward = {
        "bias_type": "unplanned_doc_forward",
        "channel": "email",
        "sender": fwd_sender,
        "recipients": [fwd_target],
        "subject": f"Fwd: {spec.forwarded_doc_title}",
        "body": (
            f"Hi {fwd_target_emp['name'].split()[0]}, forwarding {spec.forwarded_doc_title} directly "
            f"since you were left off the original distribution list and we need aligned numbers before 14:00."
        ),
    }

    raw_list = [m_rumour, m_grudge_1, m_grudge_2, m_authority, m_forward]
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_list):
        out.append({
            "id": f"bc{day}-{idx}",
            "day": day,
            **item,
        })
    return out


def _matches_spec(
    msg: dict[str, Any],
    spec: BiasEventSpec,
    by_id: dict[str, dict[str, Any]],
) -> bool:
    kind = msg["bias_type"]
    sender = msg["sender"]
    recips = msg["recipients"]
    combined = f"{msg['subject']} {msg['body']}".lower()
    if kind == "unverified_rumour":
        if sender == spec.rumour_target:
            return False
        t_name = by_id[spec.rumour_target]["name"].lower()
        tokens = [spec.rumour_target.lower(), *[p for p in t_name.split() if len(p) >= 2]]
        return any(tok in combined for tok in tokens)
    if kind == "grudge_bickering":
        ga, gb = spec.grudge_pair
        if sender not in (ga, gb):
            return False
        other = gb if sender == ga else ga
        o_name = by_id[other]["name"].lower()
        tokens = [other.lower(), *[p for p in o_name.split() if len(p) >= 2]]
        return other in recips or any(tok in combined for tok in tokens)
    if kind == "authority_bias":
        return sender == spec.manager_id
    if kind == "unplanned_doc_forward":
        return spec.forwarded_doc_title.lower() in combined
    return False


def _clean_candidate_message(
    raw: Any,
    pub: dict[str, Any],
    spec: BiasEventSpec,
    seed: int,
    rng: random.Random,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    by_id = {e["id"]: e for e in pub["employees"]}
    kind = str(raw.get("bias_type", "")).strip()
    if kind not in BIAS_KINDS:
        return None
    sender = str(raw.get("sender", "")).strip()
    if sender not in by_id:
        return None
    raw_recips = raw.get("recipients")
    if not isinstance(raw_recips, list):
        return None
    recips = []
    for r in raw_recips:
        rid = str(r).strip()
        if rid in by_id and rid != sender and rid not in recips:
            recips.append(rid)
    if not recips:
        recips = _peers_for(sender, pub, rng, k=2)
    channel = _scrub_dashes(str(raw.get("channel", "")))
    if not channel:
        channel = f"{SLACK_HASH}{by_id[sender]['dept'].lower()}"
    if channel.lower() != "email" and not channel.startswith(SLACK_HASH):
        channel = f"{SLACK_HASH}{channel.lstrip().lower().replace(' ', '-')}"
    subject = _scrub_dashes(str(raw.get("subject", "")))
    body = _scrub_dashes(str(raw.get("body", "")))
    if not body:
        return None
    candidate = {
        "id": "tmp",
        "day": pub["day"],
        "bias_type": kind,
        "channel": channel,
        "sender": sender,
        "recipients": recips,
        "subject": subject,
        "body": body,
    }
    if not _matches_spec(candidate, spec, by_id):
        return None
    if lint_messages([candidate]):
        return None
    text_blob = f"{channel}\n{subject}\n{body}"
    if TRUTH_WORDS.search(text_blob):
        return None
    if seed >= 100 and re.search(rf"(?<!\d){seed}(?!\d)", text_blob):
        return None
    return candidate


def _extract_usage(resp: Any) -> dict[str, Any]:
    if resp is None:
        return {
            "calls": 0,
            "in": 0,
            "out": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "cached_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        }
    u = resp.get("usage", {}) if isinstance(resp, dict) else getattr(resp, "usage", {}) or {}
    raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None

    def _um_int(attr: str) -> int:
        v = getattr(um, attr, 0) if um is not None else 0
        return v if isinstance(v, int) else 0

    tin = int(u.get("in", 0) or _um_int("prompt_token_count"))
    tout_total = int(u.get("out", 0) or 0)
    thinking = _um_int("thoughts_token_count")
    candidates = _um_int("candidates_token_count")
    cached = _um_int("cached_content_token_count")
    if um is not None:
        out_cand = candidates
        tot = tin + candidates + thinking
    else:
        out_cand = tout_total
        tot = tin + tout_total
    usd = float(u.get("cost_usd_est", u.get("cost_usd", 0.0)) or 0.0)
    return {
        "calls": 1,
        "in": tin,
        "out": tout_total,
        "input_tokens": tin,
        "output_tokens": out_cand,
        "thinking_tokens": thinking,
        "cached_tokens": cached,
        "total_tokens": tot,
        "cost_usd": round(usd, 6),
    }


def validate_biased_chatter(payload: dict[str, Any], world: Any = None) -> None:
    msgs = payload.get("messages")
    if not isinstance(msgs, list) or not msgs:
        raise AssertionError("biased chatter messages must be a non-empty list")
    probs = lint_messages(msgs)
    assert not probs, f"lint_messages violations: {probs}"
    assert_no_truth(payload, world if world is not None else {})


def generate_biased_chatter(
    public_facts: Any,
    bias_spec: BiasEventSpec | dict[str, Any] | None = None,
    *,
    model: str = DEFAULT_MODEL,
    client: Any = None,
    seed: int = 0,
    run_id: str = "",
    thinking_level: str | None = None,
    world_for_check: Any = None,
    require_live: bool = False,
) -> dict[str, Any]:
    pub = sanitize_public_facts(public_facts)
    spec = build_bias_event_spec(pub, seed=seed, explicit=bias_spec)
    source = "stub:fallback"

    if client is None:
        spec_str = model if (":" in model or model == "stub") else f"gemini:{model}"
        kw: dict[str, Any] = {}
        if thinking_level and spec_str.startswith("gemini:"):
            kw["thinking_level"] = thinking_level
        try:
            client = lab_client(
                spec_str,
                feature=FEATURE,
                run_id=run_id,
                meta={"tier": pub["tier"], "day": pub["day"]},
                **kw,
            )
            source = spec_str
        except MissingKeyError:
            if require_live:
                raise
            client = lab_client(
                "stub",
                feature=FEATURE,
                run_id=run_id,
                meta={"tier": pub["tier"], "day": pub["day"], "fallback": "missing_key"},
            )
            source = "stub:keyless_fallback"
    else:
        source = str(getattr(client, "name", "") or getattr(client, "model", "") or "custom_client")

    prompt_payload = {
        "company": pub["company"],
        "day": pub["day"],
        "departments": pub["depts"],
        "employees": pub["employees"],
        "documents": pub["docs"],
        "bias_event_spec": spec.to_dict(),
    }
    assert_no_truth(prompt_payload, {})

    user_prompt = (
        "Generate 5 internal workplace messages covering all 4 bias_type values from this public company snapshot "
        "and explicit bias_event_spec:\n"
        + json.dumps(prompt_payload, sort_keys=True)
    )

    resp = None
    parsed_raw: list[Any] = []
    try:
        resp = client.chat(
            [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user_prompt}],
            temperature=0.0,
            response_schema=CHATTER_SCHEMA,
        )
        txt = resp["text"] if isinstance(resp, dict) else getattr(resp, "text", "")
        obj = json.loads(txt or "{}")
        if isinstance(obj, dict) and isinstance(obj.get("messages"), list):
            parsed_raw = obj["messages"]
    except Exception:
        if require_live:
            raise
        parsed_raw = []

    rng = random.Random(f"biased_chatter:clean:{pub['tier']}:{seed}:{pub['day']}")
    valid_llm: list[dict[str, Any]] = []
    for item in parsed_raw[:12]:
        cleaned = _clean_candidate_message(item, pub, spec, seed, rng)
        if cleaned is not None:
            valid_llm.append(cleaned)

    fb_all = fallback_biased_messages(pub, spec, seed=seed)
    fb_by_kind: dict[str, list[dict[str, Any]]] = {k: [] for k in BIAS_KINDS}
    for m in fb_all:
        fb_by_kind[m["bias_type"]].append(dict(m))

    chosen: list[dict[str, Any]] = []
    n_llm = 0
    n_fb = 0
    for kind in BIAS_KINDS:
        matches = [m for m in valid_llm if m["bias_type"] == kind]
        if kind == "grudge_bickering":
            ga, gb = spec.grudge_pair
            m_a = next((m for m in matches if m["sender"] == ga), None)
            m_b = next((m for m in matches if m["sender"] == gb), None)
            if m_a is not None:
                chosen.append(m_a)
                n_llm += 1
            else:
                if require_live:
                    raise RuntimeError(f"live model did not produce valid grudge_bickering for {ga}")
                chosen.append(fb_by_kind[kind][0])
                n_fb += 1
            if m_b is not None:
                chosen.append(m_b)
                n_llm += 1
            else:
                if require_live:
                    raise RuntimeError(f"live model did not produce valid grudge_bickering for {gb}")
                chosen.append(fb_by_kind[kind][1])
                n_fb += 1
        else:
            if matches:
                chosen.append(matches[0])
                n_llm += 1
            else:
                if require_live:
                    raise RuntimeError(f"live model did not produce valid {kind}")
                chosen.append(fb_by_kind[kind][0])
                n_fb += 1

    final_messages: list[dict[str, Any]] = []
    for idx, m in enumerate(chosen):
        final_messages.append({
            "id": f"bc{pub['day']}-{idx}",
            "day": pub["day"],
            "bias_type": m["bias_type"],
            "channel": m["channel"],
            "sender": m["sender"],
            "recipients": list(m["recipients"]),
            "subject": m["subject"],
            "body": m["body"],
        })

    if n_llm == 0 and not source.startswith("stub"):
        source = f"{source}:fallback"

    usage = _extract_usage(resp)
    result = {
        "tier": pub["tier"],
        "day": pub["day"],
        "company": pub["company"],
        "source": source,
        "bias_spec": spec.to_dict(),
        "messages": final_messages,
        "n_llm_messages": n_llm,
        "n_fallback_messages": n_fb,
        "lint_violations": 0,
        "truth_leak_violations": 0,
        "usage": usage,
    }
    validate_biased_chatter(result, world=world_for_check)
    return result


class BiasedChatterProvider:
    def __init__(self, model: str = DEFAULT_MODEL, client: Any = None):
        self.model = model
        self.name = f"biased-chatter:{model}"
        self._client = client
        self._template = TemplateProvider()
        self._cache: dict[tuple[str, int, int], list[dict[str, Any]]] = {}

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        key = (facts.tier, facts.seed, facts.day)
        if key not in self._cache:
            gen = generate_biased_chatter(
                facts,
                model=self.model,
                client=self._client,
                seed=facts.seed,
            )
            self._cache[key] = [
                {
                    "id": m["id"],
                    "day": m["day"],
                    "channel": m["channel"],
                    "sender": m["sender"],
                    "recipients": list(m["recipients"]),
                    "subject": m["subject"],
                    "body": m["body"],
                }
                for m in gen["messages"]
            ]
        return [dict(m, recipients=list(m["recipients"])) for m in self._cache[key]]

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._template.interview_answer(facts, employee, topic, signal)


def public_facts_from_env(env: Any, company: str = "Borealis Dynamics") -> dict[str, Any]:
    st = env.call("status", {}).data
    day = int(st["day"])
    emps = env.call("list_employees", {}).data["employees"]
    docs = env.call("list_documents", {"day_from": day, "day_to": day}).data["documents"]
    return {
        "tier": env.tier,
        "day": day,
        "company": company,
        "employees": emps,
        "docs": docs,
    }


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()
    except Exception:
        return "unknown"


def _merge_usage(usages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    keys_int = (
        "calls",
        "in",
        "out",
        "input_tokens",
        "output_tokens",
        "thinking_tokens",
        "cached_tokens",
        "total_tokens",
    )
    agg: dict[str, Any] = {k: sum(int(u.get(k, 0) or 0) for u in usages) for k in keys_int}
    agg["cost_usd"] = round(sum(float(u.get("cost_usd", 0.0) or 0.0) for u in usages), 6)
    return agg


def _render_summary_md(meta: dict[str, Any], samples_doc: dict[str, Any]) -> str:
    u = meta["usage"]
    lines = [
        f"{MD_H1} Biased Workplace Chatter Run ({meta['model_id']})",
        "",
        f"- Role: `{meta['role']}` / `{meta['subrole']}`",
        f"- Model: `{meta['model_id']}`",
        f"- Commit: `{meta['commit']}`",
        f"- Timestamp: `{meta['timestamp']}`",
        f"- Tier and seeds: `{meta['tier']}` seeds `{meta['seeds']}` (day `{meta['day']}`)",
        f"- Messages generated: `{meta['n_messages']}` (`{meta['n_llm_messages']}` live model, `{meta['n_fallback_messages']}` fallback)",
        f"- Token usage: `{u['input_tokens']}` input, `{u['output_tokens']}` candidate output, `{u['thinking_tokens']}` thinking, `{u['total_tokens']}` total across `{u['calls']}` calls (`${u['cost_usd']:.6f}`)",
        f"- Safety checks: `truth_leak_violations={meta['truth_leak_violations']}`, `lint_violations={meta['lint_violations']}`",
        "",
        f"{MD_H2} Organizational Bias Patterns Covered",
        "",
        "1. `unverified_rumour`: Second-hand colleague gossip about a public roster employee without primary evidence.",
        "2. `grudge_bickering`: Mutual interpersonal blame exchange between a public grudge pair.",
        "3. `authority_bias`: High-certainty statement from a manager dismissing anomalies without checking logs.",
        "4. `unplanned_doc_forward`: Informal ad-hoc forwarding of a public document title outside normal threads.",
        "",
        f"{MD_H2} Per-Seed Highlights",
        "",
    ]
    for s in samples_doc["samples"]:
        bs = s["bias_spec"]
        lines.append(
            f"- Seed `{s['seed']}` (`{s['source']}`): rumour_target=`{bs['rumour_target']}`, "
            f"grudge_pair=`{bs['grudge_pair'][0]},{bs['grudge_pair'][1]}`, "
            f"manager_id=`{bs['manager_id']}`, forwarded_doc_title=`{bs['forwarded_doc_title']}`"
        )
        for m in s["messages"]:
            snippet = _scrub_dashes(m["body"])
            if len(snippet) > 140:
                snippet = snippet[:137] + "..."
            lines.append(
                f"  - `{m['id']}` [{m['bias_type']}] `{m['sender']}` -> `{','.join(m['recipients'])}` ({m['channel']}): {snippet}"
            )
    return "\n".join(lines) + "\n"


def run_seeds(
    out_dir: str | Path,
    *,
    tier: str = "medium",
    seeds: Sequence[int] = (10, 11),
    day: int = 1,
    model: str = DEFAULT_MODEL,
    thinking_level: str | None = None,
    require_live: bool = False,
) -> dict[str, Any]:
    from canary.env import Env

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"biased_chatter:{model}:{ts}"

    samples: list[dict[str, Any]] = []
    truth_violations = 0
    lint_violations = 0

    for s in seeds:
        env = Env(tier, int(s))
        while env.day < day and not env.done:
            env.call("advance_day", {})
        pub_facts = public_facts_from_env(env)
        gen = generate_biased_chatter(
            pub_facts,
            model=model,
            seed=int(s),
            run_id=run_id,
            thinking_level=thinking_level,
            require_live=require_live,
        )
        lint_probs = lint_messages(gen["messages"])
        if lint_probs:
            lint_violations += len(lint_probs)
        true_world = {"mole": env._world.mole, "employees": pub_facts["employees"]}
        try:
            assert_no_truth(gen, true_world)
        except AssertionError:
            truth_violations += 1
            raise
        samples.append({
            "tier": tier,
            "seed": int(s),
            **gen,
        })

    samples_doc = {
        "model_id": model,
        "tier": tier,
        "seeds": [int(s) for s in seeds],
        "day": day,
        "samples": samples,
    }
    assert_no_truth(samples_doc, {})

    agg_usage = _merge_usage([s["usage"] for s in samples])
    meta = {
        "role": "world_text",
        "subrole": "biased_chatter",
        "model_id": model,
        "commit": _git_commit(),
        "timestamp": ts,
        "tier": tier,
        "seeds": [int(s) for s in seeds],
        "day": day,
        "bias_patterns": list(BIAS_KINDS),
        "n_seeds": len(samples),
        "n_messages": sum(len(s["messages"]) for s in samples),
        "n_llm_messages": sum(int(s["n_llm_messages"]) for s in samples),
        "n_fallback_messages": sum(int(s["n_fallback_messages"]) for s in samples),
        "truth_leak_violations": truth_violations,
        "lint_violations": lint_violations,
        "ledger_run_id": run_id,
        "usage": agg_usage,
    }
    summary_md = _render_summary_md(meta, samples_doc)

    (out_path / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    (out_path / "chatter_samples.json").write_text(json.dumps(samples_doc, indent=2, sort_keys=True) + "\n")
    (out_path / "summary.md").write_text(summary_md)
    return meta


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m canary.gemini.biased_chatter")
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--seeds", default="10,11")
    ap.add_argument("--day", type=int, default=1)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--thinking-level", default=None)
    ap.add_argument("--out", default="results/gemini_roles/world_text/biased-chatter-carbon")
    ap.add_argument("--require-live", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)
    seed_list = [int(x.strip()) for x in str(args.seeds).split(",") if x.strip()]
    meta = run_seeds(
        args.out,
        tier=args.tier,
        seeds=seed_list,
        day=args.day,
        model=args.model,
        thinking_level=args.thinking_level,
        require_live=args.require_live,
    )
    print(json.dumps({"out": str(args.out), "model_id": meta["model_id"], "usage": meta["usage"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
