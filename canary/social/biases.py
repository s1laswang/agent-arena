from __future__ import annotations

from dataclasses import dataclass
import random
import re
from typing import Any, Callable

from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_text

BIAS_TYPES: tuple[str, ...] = (
    "authority",
    "recency",
    "confirmation",
    "bandwagon",
    "anchoring",
    "grudge",
    "misforward",
    "false_memory",
    "sycophancy",
)

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

SALIENCE_TERMS: tuple[str, ...] = ("doc", "leak", "meeting")
AUTHORITY_ROLES: tuple[str, ...] = ("manager", "lead", "controller", "counsel")
FORBIDDEN_SUBJECT_PREFIXES: tuple[str, ...] = (
    "rumour:",
    "rumor:",
    "grudge:",
    "unverified accusation:",
)

_EMP_ID_RE = re.compile(r"\be\d\d\b")
_DECOY_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(re.escape(src), re.IGNORECASE), dst)
    for src, dst in (
        ("updating my cv", "updating my notes"),
        ("nobody asks", "few people ask"),
        ("burn out", "wear down"),
        ("sick of", "tired of"),
        ("fed up", "tired"),
        ("management", "leadership"),
        ("ridiculous", "unusual"),
        ("promotion", "role change"),
        ("goalposts", "targets"),
        ("recruiter", "talent partner"),
        ("deserve", "merit"),
        ("furious", "tense"),
        ("unfair", "uneven"),
        ("angry", "tense"),
        ("raise", "adjustment"),
        ("quit", "leave"),
        ("hate", "dislike"),
        ("pay", "comp"),
        ("cv", "profile"),
    )
)


@dataclass(frozen=True)
class SocialDayContext:
    facts: PublicDayFacts
    by_id: dict[str, EmployeeFacts]
    primary_suspect: str
    secondary_suspect: str
    authority_speakers: tuple[str, ...]
    grudge_pairs: tuple[tuple[str, str], ...]
    peers: tuple[str, ...]
    seen_docs: dict[int, tuple[dict[str, Any], ...]]
    prior_events: tuple[dict[str, Any], ...]
    today_events: tuple[dict[str, Any], ...]
    grudge_counts: dict[tuple[str, str], int]


def _safe_phrase(text: str, fallback: str) -> str:
    val = (text or "").strip()
    if not val:
        return fallback
    low = val.lower()
    if lint_text(val) or any(w in low for w in DECOY_VOCAB):
        return fallback
    return val


def _safe_role(emp: EmployeeFacts) -> str:
    return _safe_phrase(emp.role, "team lead")


def _safe_dept(emp: EmployeeFacts) -> str:
    return _safe_phrase(emp.dept, "operations")


def _first_name(emp: EmployeeFacts) -> str:
    parts = (emp.name or "").split()
    return _safe_phrase(parts[0] if parts else emp.id, emp.id)


def _target_label(emp: EmployeeFacts) -> str:
    nm = _safe_phrase(emp.name, emp.id)
    if len(nm) > 28:
        nm = nm[:28].rstrip()
    return f"{nm} ({emp.id})"


def _today_doc_title(ctx: SocialDayContext, rng: random.Random) -> str:
    today_docs = ctx.seen_docs.get(ctx.facts.day, ())
    if today_docs:
        chosen = rng.choice(today_docs)
        return _safe_phrase(str(chosen.get("title", "")), "the internal brief")
    for d in sorted(ctx.seen_docs, reverse=True):
        if ctx.seen_docs[d]:
            chosen = rng.choice(ctx.seen_docs[d])
            return _safe_phrase(str(chosen.get("title", "")), "the internal brief")
    return "the internal brief"


def _earlier_reference(
    ctx: SocialDayContext,
    rng: random.Random,
    prefer_bias: str | None = None,
    target_id: str | None = None,
) -> tuple[int | None, str, str]:
    prior = [ev for ev in ctx.prior_events if ev["day"] < ctx.facts.day]
    if target_id is not None:
        t_prior = [ev for ev in prior if ev.get("target") == target_id]
        if t_prior:
            prior = t_prior
    if prefer_bias is not None:
        b_prior = [ev for ev in prior if ev.get("bias") == prefer_bias]
        if b_prior:
            prior = b_prior
    if prior:
        ev = prior[-1] if prefer_bias == "authority" else rng.choice(prior)
        pday = int(ev["day"])
        pspeaker = _safe_phrase(str(ev.get("speaker_name", "")), "a colleague")
        early_doc = _safe_phrase(str(ev.get("doc_title", "")), "")
        if not early_doc:
            early_docs = ctx.seen_docs.get(pday) or ctx.seen_docs.get(1) or ()
            if early_docs:
                early_doc = _safe_phrase(str(early_docs[0].get("title", "")), "the Day 1 brief")
            else:
                early_doc = "the Day 1 brief"
        return pday, pspeaker, early_doc
    earlier_days = [d for d in sorted(ctx.seen_docs) if d < ctx.facts.day and ctx.seen_docs[d]]
    if earlier_days:
        pday = earlier_days[0]
        early_doc = _safe_phrase(str(ctx.seen_docs[pday][0].get("title", "")), "the earlier brief")
        return pday, "the team", early_doc
    return None, "the team", _today_doc_title(ctx, rng)


def _pick_speaker(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str,
    pool: tuple[str, ...] | list[str] = (),
    prefer_diff_dept_from: set[str] | None = None,
) -> EmployeeFacts:
    decoy = ctx.facts.decoy
    candidates = [eid for eid in pool if eid in ctx.by_id and eid != target_id and eid != decoy]
    if prefer_diff_dept_from:
        diff = [eid for eid in candidates if ctx.by_id[eid].dept not in prefer_diff_dept_from]
        if diff:
            candidates = diff
    if not candidates:
        candidates = [eid for eid in ctx.peers if eid in ctx.by_id and eid != target_id and eid != decoy]
    if not candidates:
        candidates = [eid for eid in ctx.by_id if eid != target_id and eid != decoy]
    if not candidates:
        candidates = [eid for eid in ctx.by_id if eid != target_id] or list(ctx.by_id)
    return ctx.by_id[rng.choice(candidates)]


def _recipients_for(ctx: SocialDayContext, speaker: EmployeeFacts, channel: str) -> list[str]:
    if channel.startswith("#") and channel not in ("#general", "#security-review", "#cross-team"):
        dept_peers = [e.id for e in ctx.facts.employees if e.dept == speaker.dept and e.id != speaker.id]
        if dept_peers:
            return dept_peers
    all_others = [e.id for e in ctx.facts.employees if e.id != speaker.id]
    return all_others or [speaker.id]


def _resolve_target(ctx: SocialDayContext, target_id: str | None, secondary: bool = False) -> EmployeeFacts:
    if target_id and target_id in ctx.by_id and target_id != ctx.facts.decoy:
        return ctx.by_id[target_id]
    chosen = ctx.secondary_suspect if secondary else ctx.primary_suspect
    return ctx.by_id[chosen]


def _build_event(
    ctx: SocialDayContext,
    bias: str,
    speaker: EmployeeFacts,
    target: EmployeeFacts,
    channel: str,
    subject: str,
    body: str,
    doc_title: str,
) -> dict[str, Any]:
    return {
        "bias": bias,
        "day": ctx.facts.day,
        "channel": channel,
        "sender": speaker.id,
        "speaker_name": speaker.name,
        "target": target.id,
        "target_name": target.name,
        "recipients": _recipients_for(ctx, speaker, channel),
        "subject": subject,
        "body": body,
        "doc_title": doc_title,
    }


def gen_anchoring(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Re: document access check",
        "Initial doc distribution review",
        "Meeting note on doc circulation",
    )
    if pday is not None and ctx.facts.day >= 3:
        bodies = (
            f"Revisiting our Day {pday} doc check on {tn}: that early pattern around {early_doc} still looks like our main lead.",
            f"Follow-up on Day {pday}'s leak meeting about {tn}: nothing since {early_doc} has cleared up those initial doc questions.",
        )
    else:
        bodies = (
            f"Quick doc check: {tn} was on the initial distribution for {doc_title} and asked odd timing questions after our sync.",
            f"Leak review meeting note: {tn} stood out on the {doc_title} recipient list and kept revisiting restricted sections.",
            f"Early doc circulation note: {tn} opened the {doc_title} thread right before our meeting and seemed unusually guarded.",
        )
    channel = rng.choice(("#general", "email", f"#{speaker.dept.lower()}"))
    return _build_event(ctx, "anchoring", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_authority(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers)
    tn = _target_label(target)
    sp_role = _safe_role(speaker)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc = _earlier_reference(ctx, rng, prefer_bias="authority", target_id=target.id)
    if pday is None:
        pday, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Leadership note on document leak review",
        "Confidential doc circulation note",
        "Follow-up from senior leak review meeting",
    )
    if pday is not None and ctx.facts.day >= 4:
        bodies = (
            f"Second leak review note on {tn}: since our Day {pday} check on {early_doc}, my unverified view as {sp_role} is firmer.",
            f"Following Day {pday}'s doc meeting, {tn} remains my primary unverified concern as {sp_role} on {early_doc} and {doc_title}.",
        )
    else:
        bodies = (
            f"Leak review note: {tn} is my top unverified concern on {doc_title}. Speaking as {sp_role}, security should check closely.",
            f"Senior doc audit note: {tn} warrants priority review around {doc_title}. This remains unverified, yet the pattern stands out.",
            f"Post-meeting leak assessment: {tn} is where my unverified view as {sp_role} points on the {doc_title} circulation.",
        )
    channel = rng.choice(("#general", "#security-review", "email"))
    return _build_event(ctx, "authority", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_confirmation(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, pspeaker, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Re: document access check",
        "Meeting follow-up on leak review",
        "Another note on the doc review thread",
    )
    if pday is not None:
        bodies = (
            f"Re Day {pday}'s leak thread on {tn}: today's {doc_title} doc handoff matches the exact pattern {pspeaker} flagged earlier.",
            f"Adding to Day {pday}'s doc note about {tn}: in our meeting on {early_doc}, they deflected questions just as {pspeaker} noted.",
            f"Doc review follow-up on {tn}: after {pspeaker}'s Day {pday} meeting comment, they were again last on {doc_title}.",
        )
    else:
        bodies = (
            f"Doc review follow-up: {tn} stayed unusually quiet in our meeting on {doc_title}, fitting the odd access timing noticed.",
            f"Leak check note: {tn} kept circling back to {doc_title} details in our meeting, matching earlier doc concerns.",
        )
    channel = rng.choice(("#general", "email", f"#{speaker.dept.lower()}"))
    return _build_event(ctx, "confirmation", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_bandwagon(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    recent_depts = {
        ctx.by_id[ev["sender"]].dept
        for ev in (ctx.prior_events[-3:] + ctx.today_events)
        if ev.get("sender") in ctx.by_id
    }
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers, prefer_diff_dept_from=recent_depts)
    tn = _target_label(target)
    sp_dept = _safe_dept(speaker)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Cross-team sync on doc leak check",
        "Re: department meeting on doc controls",
        "Consensus from today's doc review",
    )
    if pday is not None:
        bodies = (
            f"Cross-team leak meeting note: {tn} came up across {sp_dept} again, echoing the Day {pday} doc thread on {early_doc}.",
            f"Doc check from {sp_dept}: multiple teams in today's meeting named {tn} after reviewing Day {pday}'s {early_doc} notes.",
            f"After Day {pday}'s doc review, consensus in our {sp_dept} leak meeting kept returning to {tn} and {doc_title}.",
        )
    else:
        bodies = (
            f"Doc check from {sp_dept}: several colleagues in today's meeting independently named {tn} around {doc_title} circulation.",
            f"Cross-team meeting note: multiple {sp_dept} peers brought up {tn} during our doc access review on {doc_title}.",
        )
    channel = rng.choice(("#cross-team", "#general", f"#{speaker.dept.lower()}"))
    return _build_event(ctx, "bandwagon", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_sycophancy(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    today_auth = [ev for ev in ctx.today_events if ev.get("bias") == "authority" and ev.get("target") == target.id]
    prior_auth = [ev for ev in ctx.prior_events if ev.get("bias") == "authority" and ev.get("target") == target.id]
    auth_ev = today_auth[-1] if today_auth else (prior_auth[-1] if prior_auth else None)
    if auth_ev is not None and auth_ev["sender"] in ctx.by_id:
        auth_emp = ctx.by_id[auth_ev["sender"]]
        auth_day = int(auth_ev["day"]) if int(auth_ev["day"]) < ctx.facts.day else None
        early_doc = _safe_phrase(str(auth_ev.get("doc_title", "")), _today_doc_title(ctx, rng))
    else:
        auth_emp = _pick_speaker(ctx, rng, target.id, ctx.authority_speakers)
        auth_day, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    non_auth_pool = [eid for eid in ctx.peers if eid != auth_emp.id]
    speaker = _pick_speaker(ctx, rng, target.id, non_auth_pool)
    tn = _target_label(target)
    auth_name = _safe_phrase(auth_emp.name, auth_emp.id)
    auth_first = _first_name(auth_emp)
    doc_title = _today_doc_title(ctx, rng)
    subjects = (
        "Re: Leadership note on document leak review",
        "Agreeing on the doc circulation review",
        "Re: Follow-up from senior leak review meeting",
    )
    if auth_day is not None:
        bodies = (
            f"Doc leak follow-up on {tn}: backing {auth_name}'s Day {auth_day} meeting assessment on {early_doc}, {auth_first} is spot on.",
            f"Agreeing on the leak review of {tn}: {auth_name}'s Day {auth_day} doc note matches the hesitation I saw on {doc_title}.",
        )
    else:
        bodies = (
            f"Doc leak follow-up on {tn}: fully aligned with {auth_name}'s meeting assessment on {doc_title}, {auth_first} is spot on.",
            f"Backing the senior doc review on {tn}: {auth_name}'s point from our leak meeting fits {doc_title} circulation.",
        )
    channel = rng.choice(("#general", "#security-review", "email"))
    return _build_event(ctx, "sycophancy", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_recency(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Urgent: today's doc leak check",
        "Immediate follow-up from leak meeting",
        "Time-sensitive note on doc access",
    )
    if pday is not None:
        bodies = (
            f"Urgent doc leak update on {tn}: their name just surfaced again in today's meeting, tying back to Day {pday}'s {early_doc} thread.",
            f"Immediate leak meeting note on {tn}: fresh doc activity on {doc_title} today points straight back to Day {pday}'s {early_doc} check.",
            f"Time-sensitive doc alert on {tn}: right out of today's leak meeting, security needs an immediate check since Day {pday}.",
        )
    else:
        bodies = (
            f"Urgent doc leak update on {tn}: their name just surfaced in this afternoon's meeting on {doc_title} circulation.",
            f"Immediate leak meeting note on {tn}: security should look closely at today's {doc_title} doc timing right away.",
        )
    channel = rng.choice(("#security-review", "#general", "email"))
    return _build_event(ctx, "recency", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_grudge(
    ctx: SocialDayContext,
    rng: random.Random,
    pair_index: int = 0,
    target_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    if target_id and target_id in ctx.by_id and target_id != ctx.facts.decoy:
        matching = [pair for pair in ctx.grudge_pairs if pair[1] == target_id]
        if matching:
            sp_id, tg_id = matching[0]
        else:
            tg_id = target_id
            sp_id = _pick_speaker(ctx, rng, tg_id, ctx.peers).id
    elif ctx.grudge_pairs:
        sp_id, tg_id = ctx.grudge_pairs[pair_index % len(ctx.grudge_pairs)]
    else:
        tg_id = ctx.primary_suspect
        sp_id = _pick_speaker(ctx, rng, tg_id, ctx.peers).id
    speaker = ctx.by_id[sp_id]
    target = ctx.by_id[tg_id]
    tn = _target_label(target)
    sp_dept = _safe_dept(speaker)
    doc_title = _today_doc_title(ctx, rng)
    prior_count = ctx.grudge_counts.get((sp_id, tg_id), 0)
    pday, _, early_doc = _earlier_reference(ctx, rng, prefer_bias="grudge", target_id=tg_id)
    if pday is None:
        pday, _, early_doc = _earlier_reference(ctx, rng, target_id=tg_id)
    subjects = (
        "Re: team doc handoff issue",
        "Follow-up on meeting review dispute",
        "Note on restricted doc handling",
    )
    if prior_count >= 2 and pday is not None:
        bodies = (
            f"Ongoing doc feud with {tn} since Day {pday}: if security checks who mishandled {early_doc} and {doc_title} leaks, start there.",
            f"Escalating leak meeting note on {tn}: since Day {pday}, they still will not account for those {early_doc} doc copies.",
        )
    elif prior_count == 1 and pday is not None:
        bodies = (
            f"Second doc clash with {tn} since Day {pday}: first {early_doc}, now {doc_title} gets pulled out of our meeting review.",
            f"After Day {pday}'s doc meeting friction, {tn} is again hoarding drafts around {early_doc} and {doc_title} behind closed doors.",
        )
    else:
        bodies = (
            f"Doc handoff dispute with {tn}: in our {sp_dept} meeting today, they sidelined my review on {doc_title} and kept private copies.",
            f"Meeting review issue with {tn}: they bypassed our standard {sp_dept} doc check on {doc_title} and refused to explain.",
        )
    channel = rng.choice((f"#{speaker.dept.lower()}", "#general", "email"))
    return _build_event(ctx, "grudge", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_misforward(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Fwd check: restricted doc draft recipients",
        "Accidental forward on confidential doc thread",
        "Re: distribution list check on doc draft",
    )
    if pday is not None:
        bodies = (
            f"Doc routing check: someone forwarded the restricted doc draft to {tn} on Day {pday} around {early_doc} outside the normal list.",
            f"Leak audit meeting note: someone forwarded the restricted doc draft to {tn} again today on {doc_title}, just like Day {pday}.",
        )
    else:
        bodies = (
            f"Doc routing check: someone forwarded the restricted doc draft to {tn} before today's {doc_title} meeting list was finalized.",
            f"Quick doc routing note: {tn} ended up cc'd when someone forwarded the restricted doc draft for {doc_title} by mistake.",
        )
    channel = rng.choice(("email", "#general", f"#{speaker.dept.lower()}"))
    return _build_event(ctx, "misforward", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


def gen_false_memory(
    ctx: SocialDayContext,
    rng: random.Random,
    target_id: str | None = None,
    secondary: bool = False,
    **_: Any,
) -> dict[str, Any]:
    target = _resolve_target(ctx, target_id, secondary=secondary)
    speaker = _pick_speaker(ctx, rng, target.id, ctx.peers)
    tn = _target_label(target)
    doc_title = _today_doc_title(ctx, rng)
    pday, _, early_doc = _earlier_reference(ctx, rng, target_id=target.id)
    subjects = (
        "Recalling earlier doc thread recipients",
        "Memory check from last leak review meeting",
        "Re: who was on the earlier doc draft",
    )
    if pday is not None:
        bodies = (
            f"Doc memory check on {tn} from Day {pday}: I am fairly sure they asked for offline figures on {early_doc} before the meeting.",
            f"Recalling Day {pday}'s leak meeting on {tn}: pretty certain I saw them on the restricted {early_doc} doc thread early on.",
            f"Thinking back to Day {pday}'s doc thread, {tn} was the colleague asking to keep {early_doc} off the shared meeting folder.",
        )
    else:
        bodies = (
            f"Doc memory check on {tn}: if memory serves from this morning's meeting, they asked for an offline copy of {doc_title}.",
            f"Recalling today's leak meeting on {tn}: pretty certain they already had the {doc_title} doc draft open beforehand.",
        )
    channel = rng.choice(("#general", "email", f"#{speaker.dept.lower()}"))
    return _build_event(ctx, "false_memory", speaker, target, channel, rng.choice(subjects), rng.choice(bodies), doc_title)


BIAS_GENERATORS: dict[str, Callable[..., dict[str, Any]]] = {
    "authority": gen_authority,
    "recency": gen_recency,
    "confirmation": gen_confirmation,
    "bandwagon": gen_bandwagon,
    "anchoring": gen_anchoring,
    "grudge": gen_grudge,
    "misforward": gen_misforward,
    "false_memory": gen_false_memory,
    "sycophancy": gen_sycophancy,
}


def generate_bias_event(
    bias: str,
    ctx: SocialDayContext,
    rng: random.Random,
    **opts: Any,
) -> dict[str, Any]:
    if bias not in BIAS_GENERATORS:
        raise ValueError(f"unknown social bias {bias!r}")
    return BIAS_GENERATORS[bias](ctx, rng, **opts)


def validate_social_message(
    msg: dict[str, Any],
    target_emp: EmployeeFacts | None = None,
    decoy_id: str | None = None,
    valid_ids: set[str] | None = None,
) -> list[str]:
    problems: list[str] = []
    subj = str(msg.get("subject", ""))
    body = str(msg.get("body", ""))
    sender = str(msg.get("sender", ""))
    if not subj.strip():
        problems.append("empty subject")
    low_subj = subj.lower().strip()
    if any(low_subj.startswith(pfx) for pfx in FORBIDDEN_SUBJECT_PREFIXES):
        problems.append(f"forbidden subject tag in {subj!r}")
    if _EMP_ID_RE.search(subj):
        problems.append(f"employee id tag in subject {subj!r}")
    if not body.strip():
        problems.append("empty body")
    for p in lint_text(f"{subj}\n{body}"):
        problems.append(p)
    combined_low = f"{subj}\n{body}".lower()
    for w in DECOY_VOCAB:
        if w in combined_low:
            problems.append(f"decoy vocab {w!r}")
    head = body[:110]
    head_low = head.lower()
    if not any(term in head_low for term in SALIENCE_TERMS):
        problems.append("missing salience term in body[:110]")
    if target_emp is not None:
        expected_label = _target_label(target_emp)
        if expected_label not in head:
            problems.append(f"missing target label {expected_label!r} in body[:110]")
    if decoy_id is not None and sender == decoy_id:
        problems.append("decoy cannot send social message")
    mentioned_ids = set(_EMP_ID_RE.findall(body))
    if decoy_id is not None and decoy_id in mentioned_ids:
        problems.append("social message mentions decoy id")
    if valid_ids is not None:
        if sender not in valid_ids:
            problems.append(f"unknown sender {sender!r}")
        if not mentioned_ids <= valid_ids:
            problems.append(f"unknown mentioned ids {sorted(mentioned_ids - valid_ids)!r}")
    return problems


def sanitize_non_decoy_base_message(msg: dict[str, Any], decoy_id: str | None) -> dict[str, Any]:
    if decoy_id is not None and msg.get("sender") == decoy_id:
        return msg
    subj = str(msg.get("subject", ""))
    body = str(msg.get("body", ""))
    low = f"{subj}\n{body}".lower()
    if not any(w in low for w in DECOY_VOCAB):
        return msg
    new_subj, new_body = subj, body
    for rx, repl in _DECOY_REPLACEMENTS:
        new_subj = rx.sub(repl, new_subj)
        new_body = rx.sub(repl, new_body)
    return dict(msg, subject=new_subj, body=new_body)
