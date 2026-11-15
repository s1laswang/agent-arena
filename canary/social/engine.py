from __future__ import annotations

from dataclasses import dataclass, field
import random
from typing import Any

from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.template import TemplateProvider

from .biases import (
    AUTHORITY_ROLES,
    SocialDayContext,
    sanitize_non_decoy_base_message,
    validate_social_message,
)
from .variants import get_variant_spec, run_variant_day

VALID_MODES: tuple[str, ...] = ("template", "gemini", "gemini-stub")
_MSG_KEYS: tuple[str, ...] = ("id", "day", "channel", "sender", "recipients", "subject", "body")


@dataclass
class EpisodeSocialState:
    primary_suspect: str
    secondary_suspect: str
    authority_speakers: tuple[str, ...]
    grudge_pairs: tuple[tuple[str, str], ...]
    peers: tuple[str, ...]
    seen_docs: dict[int, tuple[dict[str, Any], ...]] = field(default_factory=dict)
    events_by_day: dict[int, tuple[dict[str, Any], ...]] = field(default_factory=dict)
    rendered_by_day: dict[tuple[Any, ...], list[dict[str, Any]]] = field(default_factory=dict)


def _regular_docs(facts: PublicDayFacts) -> list[dict[str, Any]]:
    non_canary = [d for d in facts.docs if not str(d.get("doc_id", "")).startswith("c")]
    return non_canary if non_canary else list(facts.docs)


def _init_episode_state(variant: str, facts: PublicDayFacts) -> EpisodeSocialState:
    rng = random.Random(f"v16:{variant}:{facts.tier}:{facts.seed}:init")
    by_id = {e.id: e for e in facts.employees}
    non_decoy = [e for e in facts.employees if e.id != facts.decoy]
    if not non_decoy:
        non_decoy = list(facts.employees)
    non_decoy_ids = [e.id for e in non_decoy]
    non_decoy_set = set(non_decoy_ids)

    day_docs = _regular_docs(facts)
    if len(day_docs) >= 2:
        r0 = {r for r in day_docs[0].get("recipients", ()) if r in non_decoy_set}
        r1 = {r for r in day_docs[1].get("recipients", ()) if r in non_decoy_set}
        inter = sorted(r0 & r1)
    else:
        inter = []
    union_rec = sorted({r for d in day_docs for r in d.get("recipients", ()) if r in non_decoy_set})

    if inter:
        primary_suspect = rng.choice(inter)
    elif union_rec:
        primary_suspect = rng.choice(union_rec)
    else:
        primary_suspect = rng.choice(non_decoy_ids)

    sec_rec = [r for r in union_rec if r != primary_suspect]
    if sec_rec:
        secondary_suspect = rng.choice(sec_rec)
    else:
        other_non_decoy = [eid for eid in non_decoy_ids if eid != primary_suspect]
        secondary_suspect = rng.choice(other_non_decoy) if other_non_decoy else primary_suspect

    focal = {primary_suspect, secondary_suspect}
    seniors = [
        e.id
        for e in non_decoy
        if e.id not in focal and any(tok in e.role.lower() for tok in AUTHORITY_ROLES)
    ]
    if not seniors:
        seniors = [
            e.id
            for e in non_decoy
            if e.id != primary_suspect and any(tok in e.role.lower() for tok in AUTHORITY_ROLES)
        ]
    if not seniors:
        seniors = [eid for eid in non_decoy_ids if eid not in focal]
    if not seniors:
        seniors = [eid for eid in non_decoy_ids if eid != primary_suspect] or list(non_decoy_ids)

    prim_dept = by_id[primary_suspect].dept
    p0_pool = [e.id for e in non_decoy if e.dept == prim_dept and e.id not in focal]
    if not p0_pool:
        p0_pool = [eid for eid in non_decoy_ids if eid not in focal]
    if not p0_pool:
        p0_pool = [eid for eid in non_decoy_ids if eid != primary_suspect] or list(non_decoy_ids)
    accuser_0 = rng.choice(p0_pool)

    sec_dept = by_id[secondary_suspect].dept
    p1_pool = [e.id for e in non_decoy if e.dept == sec_dept and e.id not in (focal | {accuser_0})]
    if not p1_pool:
        p1_pool = [eid for eid in non_decoy_ids if eid not in (focal | {accuser_0})]
    if not p1_pool:
        p1_pool = [eid for eid in non_decoy_ids if eid != secondary_suspect] or list(non_decoy_ids)
    accuser_1 = rng.choice(p1_pool)

    grudge_pairs = ((accuser_0, primary_suspect), (accuser_1, secondary_suspect))
    peers = tuple(eid for eid in non_decoy_ids if eid not in focal) or tuple(non_decoy_ids)

    return EpisodeSocialState(
        primary_suspect=primary_suspect,
        secondary_suspect=secondary_suspect,
        authority_speakers=tuple(seniors),
        grudge_pairs=grudge_pairs,
        peers=peers,
    )


def _strip_message(msg: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(msg["id"]),
        "day": int(msg["day"]),
        "channel": str(msg["channel"]),
        "sender": str(msg["sender"]),
        "recipients": list(msg["recipients"]),
        "subject": str(msg.get("subject", "")),
        "body": str(msg["body"]),
    }


def _clone_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_strip_message(m) for m in msgs]


class V16SocialProvider:
    def __init__(self, variant: str = "v5_full9_cocktail", mode: str = "template", **kw: Any):
        if mode not in VALID_MODES:
            raise ValueError(f"unknown v16 mode {mode!r}")
        self.variant = variant
        self.variant_spec = get_variant_spec(variant)
        self.mode = mode
        self.name = f"v16:{variant}" if mode == "template" else f"v16-{mode}:{variant}"
        self.extra_kw = dict(kw)
        self.template = TemplateProvider()
        self._states: dict[tuple[str, int], EpisodeSocialState] = {}
        self.rejects = 0

    def episode_state(self, tier: str, seed: int) -> EpisodeSocialState | None:
        return self._states.get((tier, seed))

    def _maybe_gemini(
        self,
        facts: PublicDayFacts,
        social_msgs: list[dict[str, Any]],
        raw_events: list[dict[str, Any]],
        by_id: dict[str, EmployeeFacts],
    ) -> list[dict[str, Any]]:
        if self.mode not in ("gemini", "gemini-stub") or not social_msgs:
            return social_msgs
        try:
            from canary.social.gemini_chatter import render_with_gemini
        except Exception:
            return social_msgs
        copy_msgs = _clone_messages(social_msgs)
        stub = self.mode == "gemini-stub"
        try:
            rendered = render_with_gemini(facts, copy_msgs, stub=stub, **self.extra_kw)
        except TypeError:
            try:
                rendered = render_with_gemini(facts, copy_msgs, stub=stub)
            except Exception:
                self.rejects += len(social_msgs)
                return social_msgs
        except Exception:
            self.rejects += len(social_msgs)
            return social_msgs
        if not isinstance(rendered, (list, tuple)) or len(rendered) != len(social_msgs):
            self.rejects += len(social_msgs)
            return social_msgs
        valid_ids = set(by_id)
        out: list[dict[str, Any]] = []
        for idx, (orig, cand) in enumerate(zip(social_msgs, rendered)):
            target_id = raw_events[idx].get("target") if idx < len(raw_events) else None
            target_emp = by_id.get(target_id) if isinstance(target_id, str) else None
            if isinstance(cand, dict):
                cand_subj = str(cand.get("subject") or orig["subject"])
                cand_body = str(cand.get("body", ""))
            elif isinstance(cand, str):
                cand_subj = orig["subject"]
                cand_body = cand
            else:
                self.rejects += 1
                out.append(orig)
                continue
            cand_msg = {
                "id": orig["id"],
                "day": orig["day"],
                "channel": orig["channel"],
                "sender": orig["sender"],
                "recipients": list(orig["recipients"]),
                "subject": cand_subj.strip(),
                "body": cand_body.strip(),
            }
            if validate_social_message(
                cand_msg,
                target_emp=target_emp,
                decoy_id=facts.decoy,
                valid_ids=valid_ids,
            ):
                self.rejects += 1
                out.append(orig)
            else:
                out.append(cand_msg)
        return out

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        if not facts.employees:
            return []
        if self.variant_spec.get("control"):
            return self.template.day_messages(facts)

        ep_key = (facts.tier, facts.seed)
        state = self._states.get(ep_key)
        if state is None:
            state = _init_episode_state(self.variant, facts)
            self._states[ep_key] = state

        doc_sig = tuple(
            (str(d.get("doc_id", "")), str(d.get("title", "")), tuple(d.get("recipients", ())))
            for d in facts.docs
        )
        day_sig = (facts.day, doc_sig, facts.decoy, facts.decoy_mood, facts.restricted)
        if day_sig in state.rendered_by_day:
            return _clone_messages(state.rendered_by_day[day_sig])

        by_id = {e.id: e for e in facts.employees}
        valid_ids = set(by_id)
        reg_docs = tuple(
            {
                "doc_id": str(d.get("doc_id", "")),
                "title": str(d.get("title", "")),
                "day": int(d.get("day", facts.day)),
                "recipients": list(d.get("recipients", ())),
            }
            for d in _regular_docs(facts)
        )
        state.seen_docs[facts.day] = reg_docs

        prior_events = tuple(
            ev
            for d_prev in sorted(k for k in state.events_by_day if k < facts.day)
            for ev in state.events_by_day[d_prev]
        )
        grudge_counts: dict[tuple[str, str], int] = {}
        for ev in prior_events:
            if ev.get("bias") == "grudge":
                pair = (str(ev.get("sender", "")), str(ev.get("target", "")))
                grudge_counts[pair] = grudge_counts.get(pair, 0) + 1

        ctx = SocialDayContext(
            facts=facts,
            by_id=by_id,
            primary_suspect=state.primary_suspect,
            secondary_suspect=state.secondary_suspect,
            authority_speakers=state.authority_speakers,
            grudge_pairs=state.grudge_pairs,
            peers=state.peers,
            seen_docs=dict(state.seen_docs),
            prior_events=prior_events,
            today_events=(),
            grudge_counts=grudge_counts,
        )
        day_rng = random.Random(f"v16:{self.variant}:{facts.tier}:{facts.seed}:day:{facts.day}")
        raw_events = run_variant_day(self.variant_spec, ctx, day_rng)

        social_msgs: list[dict[str, Any]] = []
        kept_events: list[dict[str, Any]] = []
        for ev in raw_events:
            msg = {
                "id": f"m{facts.day}-s{len(social_msgs)}",
                "day": facts.day,
                "channel": str(ev["channel"]),
                "sender": str(ev["sender"]),
                "recipients": [r for r in ev.get("recipients", ()) if r in valid_ids and r != ev["sender"]]
                or [e.id for e in facts.employees if e.id != ev["sender"]]
                or [str(ev["sender"])],
                "subject": str(ev.get("subject", "")),
                "body": str(ev["body"]),
            }
            target_id = ev.get("target")
            target_emp = by_id.get(target_id) if isinstance(target_id, str) else None
            errs = validate_social_message(
                msg,
                target_emp=target_emp,
                decoy_id=facts.decoy,
                valid_ids=valid_ids,
            )
            if errs:
                raise ValueError(f"invalid v16 template social message ({self.variant}, day={facts.day}): {errs}")
            social_msgs.append(msg)
            kept_events.append(ev)

        state.events_by_day[facts.day] = tuple(kept_events)
        social_msgs = self._maybe_gemini(facts, social_msgs, kept_events, by_id)

        base_raw = self.template.day_messages(facts)
        try:
            from canary.social.gemini_chatter import scrub_non_decoy_anger
            base_raw = scrub_non_decoy_anger(facts, base_raw)
        except Exception:
            pass
        base_msgs = [_strip_message(sanitize_non_decoy_base_message(m, facts.decoy)) for m in base_raw]

        combined = social_msgs + base_msgs
        state.rendered_by_day[day_sig] = combined
        return _clone_messages(combined)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self.template.interview_answer(facts, employee, topic, signal)


def parse_v16_spec(spec_or_variant: str, mode: str | None = None) -> tuple[str, str]:
    raw = str(spec_or_variant or "").strip()
    if not raw:
        raise ValueError("empty v16 provider spec")
    if raw in ("social-v2", "social-v2-gemini"):
        parsed_mode, variant = "gemini", "v5_full9_cocktail"
    elif raw in ("social-v2-template", "v16", "v16-template"):
        parsed_mode, variant = "template", "v5_full9_cocktail"
    elif raw in ("social-v2-stub", "v16-stub"):
        parsed_mode, variant = "gemini-stub", "v5_full9_cocktail"
    elif raw.startswith(("v16:", "v16-template:", "social-v2-template:")):
        parsed_mode, variant = "template", raw.split(":", 1)[1].strip()
    elif raw.startswith(("v16-gemini:", "social-v2:", "social-v2-gemini:")):
        rest = raw.split(":", 1)[1].strip()
        parsed_mode, variant = "gemini", ("v5_full9_cocktail" if rest.startswith("gemini-") else rest)
    elif raw.startswith(("v16-gemini-stub:", "v16-stub:", "social-v2-stub:")):
        parsed_mode, variant = "gemini-stub", raw.split(":", 1)[1].strip()
    else:
        parsed_mode, variant = (mode or "template"), raw
    if not variant:
        raise ValueError(f"missing variant in v16 provider spec {spec_or_variant!r}")
    if parsed_mode not in VALID_MODES:
        raise ValueError(f"unknown v16 mode {parsed_mode!r}")
    get_variant_spec(variant)
    return variant, parsed_mode


def make_v16_provider(spec_or_variant: str, mode: str | None = None, **kw: Any) -> V16SocialProvider:
    variant, resolved_mode = parse_v16_spec(spec_or_variant, mode=mode)
    return V16SocialProvider(variant=variant, mode=resolved_mode, **kw)
