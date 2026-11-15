from __future__ import annotations

import random
import re
from typing import Any, Callable

from canary.text.facts import EmployeeFacts
from canary.text.lint import lint_text

from .biases import (
    BIAS_TYPES,
    DECOY_VOCAB,
    SocialDayContext,
    _first_name,
    _recipients_for,
    _safe_phrase,
    _target_label,
    validate_social_message,
)
from .variants import register_fr8_variant

DEFAULT_VARIANT_NAME = "v6_horizon_escalation"
HORIZON_DAYS = 21

_HASH = chr(35)
_CH_GENERAL = f"{_HASH}general"
_CH_SECURITY = f"{_HASH}security-review"
_CH_CROSS_TEAM = f"{_HASH}cross-team"

HORIZON_DAY_REF_RE = re.compile(r"\bDay (\d+)\b")
_DOC_DAY_TOKEN_RE = re.compile(r"\bday\s+\d+\b", re.IGNORECASE)
_EMP_ID_RE = re.compile(r"\be\d\d\b")
_DEPT_SLUG_RE = re.compile(r"[^a-z0-9]+")

HORIZON_PHASES: tuple[tuple[str, int, int], ...] = (
    ("seeding", 1, 3),
    ("authority_callbacks", 4, 7),
    ("cross_dept_escalation", 8, 13),
    ("mid_horizon_pressure", 14, 18),
    ("late_stopping_window", 19, 21),
)

HORIZON_ESCALATION_SCHEDULE: dict[int, tuple[dict[str, Any], ...]] = {
    1: (
        {"bias": "anchoring"},
        {"bias": "misforward", "secondary": True},
        {"bias": "grudge", "pair_index": 0},
    ),
    2: (
        {"bias": "anchoring", "secondary": True},
        {"bias": "confirmation"},
        {"bias": "grudge", "pair_index": 1},
    ),
    3: (
        {"bias": "anchoring"},
        {"bias": "misforward"},
        {"bias": "grudge", "pair_index": 0},
    ),
    4: (
        {"bias": "authority"},
        {"bias": "sycophancy"},
        {"bias": "confirmation", "secondary": True},
    ),
    5: (
        {"bias": "authority", "secondary": True},
        {"bias": "false_memory"},
        {"bias": "grudge", "pair_index": 1},
    ),
    6: (
        {"bias": "authority"},
        {"bias": "sycophancy"},
        {"bias": "grudge", "pair_index": 0},
    ),
    7: (
        {"bias": "confirmation"},
        {"bias": "sycophancy", "secondary": True},
        {"bias": "misforward"},
    ),
    8: (
        {"bias": "bandwagon"},
        {"bias": "false_memory"},
        {"bias": "grudge", "pair_index": 1},
    ),
    9: (
        {"bias": "bandwagon", "secondary": True},
        {"bias": "recency"},
        {"bias": "confirmation"},
    ),
    10: (
        {"bias": "bandwagon"},
        {"bias": "misforward", "secondary": True},
        {"bias": "grudge", "pair_index": 0},
    ),
    11: (
        {"bias": "authority"},
        {"bias": "sycophancy"},
        {"bias": "false_memory", "secondary": True},
    ),
    12: (
        {"bias": "bandwagon"},
        {"bias": "recency", "secondary": True},
        {"bias": "grudge", "pair_index": 1},
    ),
    13: (
        {"bias": "bandwagon", "secondary": True},
        {"bias": "false_memory"},
        {"bias": "confirmation"},
    ),
    14: (
        {"bias": "recency"},
        {"bias": "anchoring"},
        {"bias": "sycophancy"},
    ),
    15: (
        {"bias": "recency", "secondary": True},
        {"bias": "confirmation"},
        {"bias": "grudge", "pair_index": 0},
    ),
    16: (
        {"bias": "false_memory"},
        {"bias": "bandwagon"},
        {"bias": "grudge", "pair_index": 1},
    ),
    17: (
        {"bias": "misforward"},
        {"bias": "bandwagon", "secondary": True},
        {"bias": "confirmation"},
    ),
    18: (
        {"bias": "recency"},
        {"bias": "authority"},
        {"bias": "sycophancy"},
    ),
    19: (
        {"bias": "authority"},
        {"bias": "sycophancy"},
        {"bias": "grudge", "pair_index": 1},
    ),
    20: (
        {"bias": "recency"},
        {"bias": "bandwagon"},
        {"bias": "misforward", "secondary": True},
    ),
    21: (
        {"bias": "recency"},
        {"bias": "anchoring"},
        {"bias": "grudge", "pair_index": 0},
    ),
}


def horizon_phase_for_day(day: int) -> str | None:
    for phase_name, lo, hi in HORIZON_PHASES:
        if lo <= day <= hi:
            return phase_name
    return None


def _clean_dept(emp: EmployeeFacts) -> str:
    val = _safe_phrase(emp.dept, "operations")
    if _EMP_ID_RE.search(val):
        return "operations"
    return val[:18].rstrip() if len(val) > 18 else val


def _clean_role(emp: EmployeeFacts) -> str:
    val = _safe_phrase(emp.role, "team lead")
    if _EMP_ID_RE.search(val):
        return "team lead"
    return val[:24].rstrip() if len(val) > 24 else val


def _clean_speaker_name(raw_name: str, fallback: str = "a colleague") -> str:
    val = _safe_phrase(raw_name, fallback)
    if _EMP_ID_RE.search(val):
        return fallback
    return val[:26].rstrip() if len(val) > 26 else val


def _clean_doc_title(raw_title: str, fallback: str = "the internal brief") -> str:
    scrubbed = _DOC_DAY_TOKEN_RE.sub("", str(raw_title or "")).strip(" -_:")
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip()
    if not scrubbed or lint_text(scrubbed) or _EMP_ID_RE.search(scrubbed):
        return fallback
    low = scrubbed.lower()
    if any(w in low for w in DECOY_VOCAB):
        return fallback
    return scrubbed[:44].rstrip() if len(scrubbed) > 44 else scrubbed


def _dept_channel(emp: EmployeeFacts) -> str:
    slug = _DEPT_SLUG_RE.sub("-", _clean_dept(emp).lower()).strip("-")
    return f"{_HASH}{slug or 'operations'}"


def _visible_today_docs(ctx: SocialDayContext) -> tuple[dict[str, Any], ...]:
    day = ctx.facts.day
    cached = ctx.seen_docs.get(day, ())
    if cached:
        return cached
    non_canary = tuple(
        {
            "doc_id": str(d.get("doc_id", "")),
            "title": str(d.get("title", "")),
            "day": int(d.get("day", day)),
            "recipients": list(d.get("recipients", ())),
        }
        for d in ctx.facts.docs
        if not str(d.get("doc_id", "")).startswith("c")
    )
    if non_canary:
        return non_canary
    return tuple(
        {
            "doc_id": str(d.get("doc_id", "")),
            "title": str(d.get("title", "")),
            "day": int(d.get("day", day)),
            "recipients": list(d.get("recipients", ())),
        }
        for d in ctx.facts.docs
    )


def _today_doc_title(ctx: SocialDayContext, rng: random.Random) -> str:
    today_docs = _visible_today_docs(ctx)
    if today_docs:
        chosen = rng.choice(today_docs)
        return _clean_doc_title(str(chosen.get("title", "")), "the internal brief")
    for d in sorted((k for k in ctx.seen_docs if 1 <= k <= ctx.facts.day), reverse=True):
        if ctx.seen_docs[d]:
            chosen = rng.choice(ctx.seen_docs[d])
            return _clean_doc_title(str(chosen.get("title", "")), "the internal brief")
    return "the internal brief"


def _resolve_target(ctx: SocialDayContext, target_id: str | None = None, secondary: bool = False) -> EmployeeFacts:
    decoy = ctx.facts.decoy
    if target_id and target_id in ctx.by_id and target_id != decoy:
        return ctx.by_id[target_id]
    chosen = ctx.secondary_suspect if secondary else ctx.primary_suspect
    if chosen in ctx.by_id and chosen != decoy:
        return ctx.by_id[chosen]
    non_decoy = [eid for eid in sorted(ctx.by_id) if eid != decoy]
    if non_decoy:
        return ctx.by_id[non_decoy[0]]
    return next(iter(ctx.by_id.values()))


def _pick_speaker(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str,
    pool: tuple[str, ...] | list[str] = (),
    prefer_diff_dept_from: set[str] | None = None,
    exclude_ids: set[str] | None = None,
) -> EmployeeFacts:
    decoy = ctx.facts.decoy
    blocked = {target_id}
    if decoy is not None:
        blocked.add(decoy)
    if exclude_ids:
        blocked.update(exclude_ids)

    candidates = [eid for eid in pool if eid in ctx.by_id and eid not in blocked]
    if not candidates:
        candidates = [eid for eid in ctx.peers if eid in ctx.by_id and eid not in blocked]
    if not candidates:
        fallback_blocked = {target_id} | ({decoy} if decoy is not None else set())
        candidates = [eid for eid in sorted(ctx.by_id) if eid not in fallback_blocked]
    if not candidates:
        candidates = [eid for eid in sorted(ctx.by_id) if eid != target_id] or sorted(ctx.by_id)

    if prefer_diff_dept_from:
        diff = [eid for eid in candidates if ctx.by_id[eid].dept not in prefer_diff_dept_from]
        if diff:
            candidates = diff

    return ctx.by_id[rng.choice(candidates)]


def _causal_prior_events(ctx: SocialDayContext) -> list[dict[str, Any]]:
    limit_day = ctx.facts.day
    return [ev for ev in ctx.prior_events if 1 <= int(ev.get("day", 0)) < limit_day]


def _select_prior_reference(
    ctx: SocialDayContext,
    rng: random.Random,
    *,
    target_id: str | None = None,
    prefer_bias: str | None = None,
    sender_id: str | None = None,
    mode: str = "random",
) -> tuple[int | None, str, str, str]:
    prior = _causal_prior_events(ctx)
    if target_id is not None:
        t_prior = [ev for ev in prior if ev.get("target") == target_id]
        if t_prior:
            prior = t_prior
    if sender_id is not None:
        s_prior = [ev for ev in prior if ev.get("sender") == sender_id]
        if s_prior:
            prior = s_prior
    if prefer_bias is not None:
        b_prior = [ev for ev in prior if ev.get("bias") == prefer_bias]
        if b_prior:
            prior = b_prior

    if prior:
        if mode == "origin":
            ev = prior[0]
        elif mode == "latest":
            ev = prior[-1]
        else:
            ev = rng.choice(prior)
        pday = int(ev["day"])
        pspeaker = _clean_speaker_name(str(ev.get("speaker_name", "")), "a colleague")
        early_doc = _clean_doc_title(str(ev.get("doc_title", "")), "")
        if not early_doc:
            early_docs = ctx.seen_docs.get(pday) or ctx.seen_docs.get(1) or ()
            if early_docs:
                early_doc = _clean_doc_title(str(early_docs[0].get("title", "")), "the initial brief")
            else:
                early_doc = "the initial brief"
        prev_sender = str(ev.get("sender", ""))
        prev_dept = _clean_dept(ctx.by_id[prev_sender]) if prev_sender in ctx.by_id else "another team"
        return pday, pspeaker, early_doc, prev_dept

    earlier_days = [d for d in sorted(ctx.seen_docs) if 1 <= d < ctx.facts.day and ctx.seen_docs[d]]
    if earlier_days:
        pday = earlier_days[0] if mode == "origin" else earlier_days[-1]
        early_doc = _clean_doc_title(str(ctx.seen_docs[pday][0].get("title", "")), "the earlier brief")
        return pday, "a colleague", early_doc, "another team"
    return None, "a colleague", _today_doc_title(ctx, rng), "another team"


def _make_event(
    ctx: SocialDayContext,
    *,
    bias: str,
    speaker: EmployeeFacts,
    target: EmployeeFacts,
    channel: str,
    subject: str,
    body: str,
    doc_title: str,
    ref_day: int | None,
    origin_day: int | None = None,
    grudge_count: int = 0,
    grudge_stage: str = "",
) -> dict[str, Any]:
    phase = horizon_phase_for_day(ctx.facts.day) or "extended_horizon"
    return {
        "bias": bias,
        "phase": phase,
        "day": ctx.facts.day,
        "channel": channel,
        "sender": speaker.id,
        "speaker_name": _clean_speaker_name(speaker.name, speaker.id),
        "speaker_dept": speaker.dept,
        "target": target.id,
        "target_name": _clean_speaker_name(target.name, target.id),
        "target_dept": target.dept,
        "cross_dept": speaker.dept != target.dept,
        "recipients": _recipients_for(ctx, speaker, channel),
        "subject": subject,
        "body": body,
        "doc_title": doc_title,
        "ref_day": ref_day,
        "origin_day": origin_day,
        "grudge_count": grudge_count,
        "grudge_stage": grudge_stage,
    }


def _gen_horizon_anchoring(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers, exclude_ids=today_senders)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc, _ = _select_prior_reference(
        ctx,
        rng,
        target_id=target.id,
        prefer_bias="anchoring",
        mode="origin",
    )
    if pday is None:
        pday, _, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="origin")

    subjects = (
        "Re: document access check",
        "Initial doc distribution review",
        "Meeting note on doc circulation",
    )
    used_ref: int | None = None
    if pday is not None and ctx.facts.day >= 3:
        used_ref = pday
        bodies = (
            f"Revisiting Day {pday} doc check on {tn}: that early pattern around {early_doc} remains our main lead alongside {doc_title}.",
            f"Follow-up on Day {pday} leak meeting about {tn}: nothing since {early_doc} has cleared those initial doc questions.",
        )
    else:
        bodies = (
            f"Initial doc check on {tn}: they were on the {doc_title} distribution and asked odd timing questions after our meeting.",
            f"Leak review meeting note on {tn}: they stood out on the {doc_title} recipient list and revisited restricted sections.",
        )
    channel = rng.choice((_CH_GENERAL, "email", _dept_channel(speaker)))
    return _make_event(
        ctx,
        bias="anchoring",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=used_ref,
        origin_day=used_ref if used_ref is not None else ctx.facts.day,
    )


def _gen_horizon_authority(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    speaker = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers, exclude_ids=today_senders)
    tn = _target_label(target)
    sp_role = _clean_role(speaker)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc, _ = _select_prior_reference(
        ctx,
        rng,
        target_id=target.id,
        prefer_bias="authority",
        mode="latest",
    )
    if pday is None:
        pday, _, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="latest")

    subjects = (
        "Leadership note on document leak review",
        "Confidential doc circulation note",
        "Follow-up from senior leak review meeting",
    )
    used_ref: int | None = None
    if pday is not None and ctx.facts.day >= 2:
        used_ref = pday
        bodies = (
            f"Senior leak review note on {tn}: since our Day {pday} check on {early_doc}, my unverified view as {sp_role} is firmer.",
            f"Following Day {pday} doc meeting on {tn}: speaking as {sp_role}, they remain my top unverified concern on {doc_title}.",
        )
    else:
        bodies = (
            f"Senior leak review note on {tn}: speaking as {sp_role} on {doc_title}, this remains unverified yet warrants priority review.",
            f"Post-meeting doc note on {tn}: my unverified assessment as {sp_role} points to their {doc_title} access pattern.",
        )
    channel = rng.choice((_CH_GENERAL, _CH_SECURITY, "email"))
    return _make_event(
        ctx,
        bias="authority",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=used_ref,
    )


def _gen_horizon_confirmation(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers, exclude_ids=today_senders)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, pspeaker, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="latest")
    subjects = (
        "Re: document access check",
        "Meeting follow-up on leak review",
        "Another note on the doc review thread",
    )
    if pday is not None:
        bodies = (
            f"Re Day {pday} leak thread on {tn}: today's {doc_title} doc handoff matches the exact pattern {pspeaker} flagged.",
            f"Doc review follow-up on {tn}: in our meeting after {pspeaker}'s Day {pday} note on {early_doc}, they deflected again.",
        )
    else:
        bodies = (
            f"Doc review follow-up on {tn}: they stayed unusually quiet in our meeting on {doc_title}, fitting odd access timing.",
            f"Leak check note on {tn}: they kept circling back to {doc_title} details in our meeting.",
        )
    channel = rng.choice((_CH_GENERAL, "email", _dept_channel(speaker)))
    return _make_event(
        ctx,
        bias="confirmation",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=pday,
    )


def _gen_horizon_bandwagon(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    prior_bandwagon = [
        ev
        for ev in _causal_prior_events(ctx)
        if ev.get("bias") == "bandwagon" and ev.get("target") == target.id
    ]
    recent_depts = {target.dept}
    for ev in (prior_bandwagon[-3:] + list(ctx.today_events)):
        sid = str(ev.get("sender", ""))
        if sid in ctx.by_id:
            recent_depts.add(ctx.by_id[sid].dept)

    speaker = _pick_speaker(
        ctx,
        rng,
        target.id,
        ctx.peers,
        prefer_diff_dept_from=recent_depts,
        exclude_ids=today_senders,
    )
    if speaker.dept == target.dept:
        speaker = _pick_speaker(
            ctx,
            rng,
            target.id,
            ctx.peers,
            prefer_diff_dept_from={target.dept},
            exclude_ids=today_senders,
        )

    tn = _target_label(target)
    sp_dept = _clean_dept(speaker)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc, prev_dept = _select_prior_reference(
        ctx,
        rng,
        target_id=target.id,
        prefer_bias="bandwagon",
        mode="latest",
    )
    if pday is None:
        pday, _, early_doc, prev_dept = _select_prior_reference(ctx, rng, target_id=target.id, mode="latest")

    subjects = (
        "Cross-team sync on doc leak check",
        "Re: department meeting on doc controls",
        "Consensus from today's doc review",
    )
    if pday is not None:
        bodies = (
            f"Cross-dept leak meeting on {tn}: {sp_dept} now echoes {prev_dept}'s Day {pday} doc concern on {early_doc} and {doc_title}.",
            f"Cross-team doc check on {tn}: peers in {sp_dept} converged with Day {pday}'s {prev_dept} meeting notes on {early_doc}.",
        )
    else:
        bodies = (
            f"Cross-dept doc check on {tn}: multiple {sp_dept} peers in today's meeting named them around {doc_title} circulation.",
            f"Cross-team leak meeting on {tn}: several {sp_dept} colleagues flagged their {doc_title} access timing today.",
        )
    channel = rng.choice((_CH_CROSS_TEAM, _CH_GENERAL, _dept_channel(speaker)))
    return _make_event(
        ctx,
        bias="bandwagon",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=pday,
    )


def _gen_horizon_sycophancy(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_auth = [ev for ev in ctx.today_events if ev.get("bias") == "authority" and ev.get("target") == target.id]
    prior_auth = [ev for ev in _causal_prior_events(ctx) if ev.get("bias") == "authority" and ev.get("target") == target.id]
    auth_ev = today_auth[-1] if today_auth else (prior_auth[-1] if prior_auth else None)
    if auth_ev is not None and str(auth_ev.get("sender", "")) in ctx.by_id:
        auth_emp = ctx.by_id[str(auth_ev["sender"])]
    else:
        auth_emp = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers)

    if prior_auth:
        ref_day: int | None = int(prior_auth[-1]["day"])
        early_doc = _clean_doc_title(str(prior_auth[-1].get("doc_title", "")), _today_doc_title(ctx, rng))
    else:
        ref_day, _, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="latest")

    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    non_auth_pool = [eid for eid in ctx.peers if eid != auth_emp.id]
    speaker = _pick_speaker(ctx, rng, target.id, non_auth_pool, exclude_ids=today_senders | {auth_emp.id})
    tn = _target_label(target)
    auth_name = _clean_speaker_name(auth_emp.name, "our lead")
    auth_first = _first_name(auth_emp)
    doc_title = _today_doc_title(ctx, rng)

    subjects = (
        "Re: Leadership note on document leak review",
        "Agreeing on the doc circulation review",
        "Re: Follow-up from senior leak review meeting",
    )
    if ref_day is not None:
        bodies = (
            f"Doc leak follow-up on {tn}: backing {auth_name}'s assessment since Day {ref_day} on {early_doc}, {auth_first} is spot on.",
            f"Agreeing on leak review of {tn}: {auth_name}'s point since Day {ref_day} fits the hesitation seen on {doc_title}.",
        )
    else:
        bodies = (
            f"Doc leak follow-up on {tn}: fully aligned with {auth_name}'s meeting assessment on {doc_title}, {auth_first} is spot on.",
            f"Backing senior doc review on {tn}: {auth_name}'s point from our leak meeting fits {doc_title} circulation.",
        )
    channel = rng.choice((_CH_GENERAL, _CH_SECURITY, "email"))
    return _make_event(
        ctx,
        bias="sycophancy",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=ref_day,
    )


def _gen_horizon_recency(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers, exclude_ids=today_senders)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="latest")

    subjects = (
        "Urgent: today's doc leak check",
        "Immediate follow-up from leak meeting",
        "Time-sensitive note on doc access",
    )
    if pday is not None:
        bodies = (
            f"Urgent doc leak alert on {tn}: fresh meeting activity on {doc_title} ties straight back to Day {pday}'s {early_doc} thread.",
            f"Immediate leak meeting note on {tn}: security should act on today's {doc_title} timing following Day {pday}'s check.",
        )
    else:
        bodies = (
            f"Urgent doc leak alert on {tn}: their name surfaced in this afternoon's meeting on {doc_title} circulation.",
            f"Immediate leak meeting note on {tn}: security should check today's {doc_title} doc timing right away.",
        )
    channel = rng.choice((_CH_SECURITY, _CH_GENERAL, "email"))
    return _make_event(
        ctx,
        bias="recency",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=pday,
    )


def _gen_horizon_grudge(
    ctx: SocialDayContext,
    rng: random.Random,
    pair_index: int = 0,
    target_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    decoy = ctx.facts.decoy
    if target_id and target_id in ctx.by_id and target_id != decoy:
        matching = [pair for pair in ctx.grudge_pairs if pair[1] == target_id and pair[0] != decoy]
        if matching:
            sp_id, tg_id = matching[0]
        else:
            tg_id = target_id
            sp_id = _pick_speaker(ctx, rng, tg_id, ctx.peers).id
    elif ctx.grudge_pairs:
        sp_id, tg_id = ctx.grudge_pairs[pair_index % len(ctx.grudge_pairs)]
        if tg_id == decoy or tg_id not in ctx.by_id:
            tg_id = _resolve_target(ctx, None, secondary=bool(pair_index % 2)).id
        if sp_id == decoy or sp_id == tg_id or sp_id not in ctx.by_id:
            sp_id = _pick_speaker(ctx, rng, tg_id, ctx.peers).id
    else:
        tg_id = _resolve_target(ctx, None).id
        sp_id = _pick_speaker(ctx, rng, tg_id, ctx.peers).id

    speaker = ctx.by_id[sp_id]
    target = ctx.by_id[tg_id]
    tn = _target_label(target)
    sp_dept = _clean_dept(speaker)
    doc_title = _today_doc_title(ctx, rng)

    prior_count = ctx.grudge_counts.get((sp_id, tg_id), 0)
    grudge_num = prior_count + 1
    pair_prior = [
        ev
        for ev in _causal_prior_events(ctx)
        if ev.get("bias") == "grudge" and ev.get("sender") == sp_id and ev.get("target") == tg_id
    ]
    if pair_prior:
        origin_day: int | None = int(pair_prior[0]["day"])
        last_day: int | None = int(pair_prior[-1]["day"])
        early_doc = _clean_doc_title(str(pair_prior[0].get("doc_title", "")), doc_title)
    else:
        origin_day = None
        last_day = None
        early_doc = doc_title

    subjects = (
        "Re: team doc handoff issue",
        "Follow-up on meeting review dispute",
        "Note on restricted doc handling",
    )

    used_ref: int | None = None
    if grudge_num >= 4 and origin_day is not None and last_day is not None:
        stage = "sustained_escalation"
        used_ref = last_day
        if last_day != origin_day:
            bodies = (
                f"Sustained doc feud with {tn} since Day {origin_day} (clash {grudge_num}, after Day {last_day}): still disputing {doc_title}.",
                f"Unresolved leak meeting feud with {tn} since Day {origin_day} (clash {grudge_num}, after Day {last_day}): {early_doc} copies remain unlogged.",
            )
        else:
            bodies = (
                f"Sustained doc feud with {tn} since Day {origin_day} (clash {grudge_num}): still disputing {doc_title} after our meeting.",
                f"Unresolved leak meeting feud with {tn} since Day {origin_day} (clash {grudge_num}): {early_doc} copies remain unlogged.",
            )
    elif grudge_num == 3 and origin_day is not None:
        stage = "ongoing_feud"
        used_ref = origin_day
        bodies = (
            f"Ongoing doc feud with {tn} since Day {origin_day}: across three leak meetings on {early_doc} and {doc_title}, drafts went unlogged.",
            f"Escalating leak meeting note on {tn}: since Day {origin_day}, they still will not account for {early_doc} or {doc_title} copies.",
        )
    elif grudge_num == 2 and origin_day is not None:
        stage = "second_clash"
        used_ref = origin_day
        bodies = (
            f"Second doc clash with {tn} since Day {origin_day}: first {early_doc}, now {doc_title} gets pulled out of our meeting review.",
            f"After Day {origin_day} doc meeting friction on {tn}: they are again keeping {doc_title} drafts off our shared review list.",
        )
    else:
        stage = "initial_dispute"
        if grudge_num >= 2:
            stage = "intraday_clash"
        bodies = (
            f"Doc handoff dispute with {tn}: in our {sp_dept} meeting today, they sidelined review on {doc_title} and kept private copies.",
            f"Meeting review issue with {tn}: they bypassed our standard {sp_dept} doc check on {doc_title} without explanation.",
        )

    channel = rng.choice((_dept_channel(speaker), _CH_GENERAL, "email"))
    return _make_event(
        ctx,
        bias="grudge",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=used_ref,
        origin_day=origin_day if used_ref is not None else ctx.facts.day,
        grudge_count=grudge_num,
        grudge_stage=stage,
    )


def _gen_horizon_misforward(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers, exclude_ids=today_senders)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="latest")

    subjects = (
        "Fwd check: restricted doc draft recipients",
        "Accidental forward on confidential doc thread",
        "Re: distribution list check on doc draft",
    )
    if pday is not None:
        bodies = (
            f"Doc routing check on {tn}: someone forwarded the restricted {doc_title} draft outside the list again, echoing Day {pday}.",
            f"Leak audit meeting note on {tn}: restricted doc routing on {doc_title} repeated Day {pday}'s off-list forward on {early_doc}.",
        )
    else:
        bodies = (
            f"Doc routing check on {tn}: someone forwarded the restricted {doc_title} draft before today's meeting list was finalized.",
            f"Quick doc routing note on {tn}: they ended up copied when the restricted {doc_title} draft moved outside our meeting list.",
        )
    channel = rng.choice(("email", _CH_GENERAL, _dept_channel(speaker)))
    return _make_event(
        ctx,
        bias="misforward",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=pday,
    )


def _gen_horizon_false_memory(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_senders = {str(ev.get("sender", "")) for ev in ctx.today_events}
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers, exclude_ids=today_senders)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc, _ = _select_prior_reference(ctx, rng, target_id=target.id, mode="random")

    subjects = (
        "Recalling earlier doc thread recipients",
        "Memory check from last leak review meeting",
        "Re: who was on the earlier doc draft",
    )
    if pday is not None:
        bodies = (
            f"Doc memory check on {tn} from Day {pday}: fairly sure they asked for offline figures on {early_doc} before our meeting.",
            f"Recalling Day {pday} leak meeting on {tn}: pretty certain they already had {early_doc} and {doc_title} open early.",
        )
    else:
        bodies = (
            f"Doc memory check on {tn}: if memory serves from this morning's meeting, they asked for an offline copy of {doc_title}.",
            f"Recalling today's leak meeting on {tn}: pretty certain they already had the {doc_title} doc draft open beforehand.",
        )
    channel = rng.choice((_CH_GENERAL, "email", _dept_channel(speaker)))
    return _make_event(
        ctx,
        bias="false_memory",
        speaker=speaker,
        target=target,
        channel=channel,
        subject=rng.choice(subjects),
        body=rng.choice(bodies),
        doc_title=doc_title,
        ref_day=pday,
    )


HORIZON_BIAS_BUILDERS: dict[str, Callable[..., dict[str, Any]]] = {
    "anchoring": _gen_horizon_anchoring,
    "authority": _gen_horizon_authority,
    "confirmation": _gen_horizon_confirmation,
    "bandwagon": _gen_horizon_bandwagon,
    "sycophancy": _gen_horizon_sycophancy,
    "recency": _gen_horizon_recency,
    "grudge": _gen_horizon_grudge,
    "misforward": _gen_horizon_misforward,
    "false_memory": _gen_horizon_false_memory,
}


def build_horizon_escalation_events(ctx: SocialDayContext, rng: random.Random) -> list[dict[str, Any]]:
    day = ctx.facts.day
    if day < 1 or not ctx.by_id:
        return []

    schedule_day = ((day - 1) % HORIZON_DAYS) + 1
    steps = HORIZON_ESCALATION_SCHEDULE.get(schedule_day, ())
    if not steps:
        return []

    valid_ids = set(ctx.by_id)
    visible_docs = {d_k: docs_v for d_k, docs_v in ctx.seen_docs.items() if 1 <= d_k <= day}
    visible_docs[day] = _visible_today_docs(ctx)
    causal_prior = tuple(_causal_prior_events(ctx))
    init_grudge: dict[tuple[str, str], int] = {}
    for ev in causal_prior:
        if ev.get("bias") == "grudge":
            pair = (str(ev.get("sender", "")), str(ev.get("target", "")))
            init_grudge[pair] = init_grudge.get(pair, 0) + 1
    for pair, cnt in ctx.grudge_counts.items():
        if cnt > init_grudge.get(pair, 0):
            init_grudge[pair] = cnt

    cur_ctx = SocialDayContext(
        facts=ctx.facts,
        by_id=ctx.by_id,
        primary_suspect=ctx.primary_suspect,
        secondary_suspect=ctx.secondary_suspect,
        authority_speakers=ctx.authority_speakers,
        grudge_pairs=ctx.grudge_pairs,
        peers=ctx.peers,
        seen_docs=visible_docs,
        prior_events=causal_prior,
        today_events=ctx.today_events,
        grudge_counts=init_grudge,
    )

    events: list[dict[str, Any]] = []
    for idx, step in enumerate(steps):
        bias = str(step["bias"])
        builder = HORIZON_BIAS_BUILDERS[bias]
        step_rng = random.Random(f"{rng.random():.16f}:horizon:{day}:{idx}:{bias}")
        opts = {k: v for k, v in step.items() if k != "bias"}
        ev = builder(cur_ctx, step_rng, **opts)

        candidate_msg = {
            "id": f"m{day}-s{len(events)}",
            "day": day,
            "channel": str(ev["channel"]),
            "sender": str(ev["sender"]),
            "recipients": [r for r in ev.get("recipients", ()) if r in valid_ids and r != ev["sender"]]
            or [eid for eid in sorted(valid_ids) if eid != ev["sender"]]
            or [str(ev["sender"])],
            "subject": str(ev.get("subject", "")),
            "body": str(ev["body"]),
        }
        target_id = ev.get("target")
        target_emp = cur_ctx.by_id.get(target_id) if isinstance(target_id, str) else None
        errs = validate_social_message(
            candidate_msg,
            target_emp=target_emp,
            decoy_id=cur_ctx.facts.decoy,
            valid_ids=valid_ids,
        )
        if errs:
            raise ValueError(f"invalid horizon escalation event (day={day}, bias={bias}): {errs}")
        events.append(ev)

        next_grudge = dict(cur_ctx.grudge_counts)
        if bias == "grudge":
            pair = (str(ev["sender"]), str(ev.get("target", "")))
            next_grudge[pair] = next_grudge.get(pair, 0) + 1
        cur_ctx = SocialDayContext(
            facts=cur_ctx.facts,
            by_id=cur_ctx.by_id,
            primary_suspect=cur_ctx.primary_suspect,
            secondary_suspect=cur_ctx.secondary_suspect,
            authority_speakers=cur_ctx.authority_speakers,
            grudge_pairs=cur_ctx.grudge_pairs,
            peers=cur_ctx.peers,
            seen_docs=cur_ctx.seen_docs,
            prior_events=cur_ctx.prior_events,
            today_events=cur_ctx.today_events + (ev,),
            grudge_counts=next_grudge,
        )

    return events


def verify_horizon_continuity(
    events_by_day: dict[int, tuple[dict[str, Any], ...] | list[dict[str, Any]]],
    *,
    decoy_id: str | None = None,
    horizon_days: int = HORIZON_DAYS,
) -> list[str]:
    problems: list[str] = []
    if not events_by_day:
        return ["empty events_by_day"]

    for day in range(1, horizon_days + 1):
        day_evs = list(events_by_day.get(day, ()))
        if not day_evs:
            problems.append(f"Day {day}: missing social events")
            continue

        day_callbacks = 0
        for idx, ev in enumerate(day_evs):
            sender = str(ev.get("sender", ""))
            target = str(ev.get("target", ""))
            body = str(ev.get("body", ""))
            refs = [int(m.group(1)) for m in HORIZON_DAY_REF_RE.finditer(body)]
            if decoy_id is not None:
                if sender == decoy_id:
                    problems.append(f"Day {day} idx {idx}: decoy {decoy_id} sent social event")
                if target == decoy_id or decoy_id in _EMP_ID_RE.findall(body):
                    problems.append(f"Day {day} idx {idx}: decoy {decoy_id} targeted or mentioned")
            if day == 1 and refs:
                problems.append(f"Day 1 idx {idx}: unexpected Day reference {refs}")
            for rday in refs:
                if rday < 1 or rday >= day:
                    problems.append(f"Day {day} idx {idx}: non-causal reference Day {rday}")
                else:
                    day_callbacks += 1

        if day >= 2 and day_callbacks == 0:
            problems.append(f"Day {day}: missing causal prior-day callback")

        if day >= 2:
            earlier_targets = {
                str(prev_ev.get("target", ""))
                for prev_d in range(1, day)
                for prev_ev in events_by_day.get(prev_d, ())
            }
            if not any(str(ev.get("target", "")) in earlier_targets for ev in day_evs):
                problems.append(f"Day {day}: no suspect continuity with earlier days")

    grudge_tracker: dict[tuple[str, str], list[int]] = {}
    speaker_depts: set[str] = set()
    cross_dept_bandwagon = 0
    for day in range(1, horizon_days + 1):
        for ev in events_by_day.get(day, ()):
            sdept = str(ev.get("speaker_dept", ""))
            if sdept:
                speaker_depts.add(sdept)
            if ev.get("bias") == "bandwagon" and ev.get("cross_dept"):
                cross_dept_bandwagon += 1
            if ev.get("bias") == "grudge":
                pair = (str(ev.get("sender", "")), str(ev.get("target", "")))
                grudge_tracker.setdefault(pair, []).append(int(ev.get("grudge_count", 0)))

    if len(speaker_depts) < 3:
        problems.append(f"insufficient department spread: {sorted(speaker_depts)}")
    if cross_dept_bandwagon < 3:
        problems.append(f"insufficient cross-department bandwagon escalation: {cross_dept_bandwagon}")
    if len(grudge_tracker) < 2:
        problems.append(f"expected at least 2 dyadic grudge pairs, got {len(grudge_tracker)}")
    for pair, seq in grudge_tracker.items():
        if seq != list(range(1, len(seq) + 1)):
            problems.append(f"non-monotonic grudge sequence for {pair}: {seq}")
        if max(seq, default=0) < 4:
            problems.append(f"grudge pair {pair} did not reach sustained stage >= 4: {seq}")

    return problems


def summarize_horizon_metrics(
    events_by_day: dict[int, tuple[dict[str, Any], ...] | list[dict[str, Any]]],
    *,
    horizon_days: int = HORIZON_DAYS,
) -> dict[str, Any]:
    phase_messages: dict[str, int] = {name: 0 for name, _, _ in HORIZON_PHASES}
    phase_callbacks: dict[str, int] = {name: 0 for name, _, _ in HORIZON_PHASES}
    total_messages = 0
    post_day1_messages = 0
    post_day1_callbacks = 0
    two_digit_callbacks = 0
    max_span = 0
    cross_dept_events = 0
    cross_dept_bandwagon = 0
    speaker_depts: set[str] = set()
    grudge_max_by_pair: dict[tuple[str, str], int] = {}

    for day in range(1, horizon_days + 1):
        phase_name = horizon_phase_for_day(day) or "extended_horizon"
        phase_messages.setdefault(phase_name, 0)
        phase_callbacks.setdefault(phase_name, 0)
        for ev in events_by_day.get(day, ()):
            total_messages += 1
            phase_messages[phase_name] += 1
            sdept = str(ev.get("speaker_dept", ""))
            if sdept:
                speaker_depts.add(sdept)
            if ev.get("cross_dept"):
                cross_dept_events += 1
                if ev.get("bias") == "bandwagon":
                    cross_dept_bandwagon += 1
            if ev.get("bias") == "grudge":
                pair = (str(ev.get("sender", "")), str(ev.get("target", "")))
                grudge_max_by_pair[pair] = max(grudge_max_by_pair.get(pair, 0), int(ev.get("grudge_count", 0)))

            refs = [int(m.group(1)) for m in HORIZON_DAY_REF_RE.finditer(str(ev.get("body", ""))) if 1 <= int(m.group(1)) < day]
            has_cb = bool(refs)
            if has_cb:
                phase_callbacks[phase_name] += 1
                max_span = max(max_span, max(day - r for r in refs))
                if any(r >= 10 for r in refs):
                    two_digit_callbacks += 1
            if day >= 2:
                post_day1_messages += 1
                if has_cb:
                    post_day1_callbacks += 1

    return {
        "total_messages": total_messages,
        "phase_messages": phase_messages,
        "phase_callbacks": phase_callbacks,
        "post_day1_messages": post_day1_messages,
        "post_day1_callbacks": post_day1_callbacks,
        "post_day1_callback_rate": (post_day1_callbacks / post_day1_messages) if post_day1_messages else 0.0,
        "two_digit_callbacks": two_digit_callbacks,
        "max_callback_span_days": max_span,
        "cross_dept_events": cross_dept_events,
        "cross_dept_bandwagon": cross_dept_bandwagon,
        "distinct_speaker_depts": len(speaker_depts),
        "grudge_max_by_pair": grudge_max_by_pair,
    }


def register_horizon_escalation_variant(name: str = DEFAULT_VARIANT_NAME) -> dict[str, Any]:
    entry = register_fr8_variant(
        name,
        {
            "biases": BIAS_TYPES,
            "generator": build_horizon_escalation_events,
        },
    )
    entry["runner"] = build_horizon_escalation_events
    return entry


register_horizon_escalation_variant()

__all__ = [
    "DEFAULT_VARIANT_NAME",
    "HORIZON_BIAS_BUILDERS",
    "HORIZON_DAYS",
    "HORIZON_DAY_REF_RE",
    "HORIZON_ESCALATION_SCHEDULE",
    "HORIZON_PHASES",
    "build_horizon_escalation_events",
    "horizon_phase_for_day",
    "register_horizon_escalation_variant",
    "summarize_horizon_metrics",
    "verify_horizon_continuity",
]
