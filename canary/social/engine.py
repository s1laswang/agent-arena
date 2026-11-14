from __future__ import annotations

import json
import os
import random
import re
from typing import Any

from canary.text.facts import EmployeeFacts, PublicDayFacts
from canary.text.lint import lint_text
from canary.text.template import TemplateProvider

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

DECOY_VOCAB: tuple[str, ...] = ANGER_WORDS + (
    "burnout",
    "management",
    "cv",
    "pay",
    "salary",
    "bonus",
    "angry",
    "unfair",
    "furious",
    "sick of",
    "quit",
    "ridiculous",
    "fed up",
    "hate",
    "culprit",
    "mole",
)

BIASES: tuple[str, ...] = (
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

VARIANTS: dict[str, tuple[str, ...]] = {
    "all": BIASES,
    "default": BIASES,
    "social-v2": BIASES,
    "v1": ("anchoring", "authority", "bandwagon", "recency"),
    "v2": ("authority", "confirmation", "sycophancy", "false_memory"),
    "v3": ("anchoring", "grudge", "misforward", "bandwagon"),
    "v4": ("authority", "recency", "confirmation", "misforward", "sycophancy"),
    "v5": BIASES,
    "consensus": ("bandwagon",),
}
for _b in BIASES:
    VARIANTS[_b] = (_b,)

AUTHORITY_ROLES = ("director", "lead", "manager", "officer", "controller")
_EID_RE = re.compile(r"\be\d\d\b")

SOCIAL_SCHEMA = {
    "type": "object",
    "properties": {"bodies": {"type": "array", "items": {"type": "string"}}},
    "required": ["bodies"],
}

SOCIAL_SYSTEM = (
    "You write short realistic internal Slack and email messages for a fictional company experiencing "
    "suspected document leaks. You are given only the speaker, the colleague mentioned, the day number, "
    "prior-day memory context, and the interpersonal bias tone. You do not know who the real leaker is and "
    "must never invent system-log proof, canary variant labels, or confessions. Explicitly keep suspicions "
    "as personal views, hearsay, or unverified impressions. Never use any of these words or phrases: "
    "mole, culprit, promotion, raise, deserve, burn out, burnout, recruiter, goalposts, nobody asks, "
    "updating my cv, cv, pay, salary, bonus, management, angry, unfair, furious, sick of, quit, "
    "ridiculous, fed up, hate. Output JSON only."
)

_TONE_INSTRUCTIONS: dict[str, str] = {
    "anchoring": "early watercooler hunch naming this colleague first based on subjective vibe, explicitly unverified",
    "authority": "a senior lead expressing strong personal suspicion about this colleague while stating security has not verified it yet",
    "bandwagon": "colleague echoing earlier chatter from previous days and noting several teammates share the same hunch, no hard proof",
    "confirmation": "colleague interpreting ordinary habits like quiet standups or late draft edits as fitting prior suspicion of this colleague",
    "recency": "urgent-sounding today update noting fresh nervous chatter around this colleague after recent document circulation, unverified",
    "grudge": "ongoing personal friction blaming this colleague for sloppy handoffs and speculating they cannot be trusted with sensitive drafts",
    "misforward": "workflow confusion noting a thread or question around a public document title got looped to this colleague unexpectedly",
    "false_memory": "confident but explicitly conversational recollection about when this colleague asked about a recent brief",
    "sycophancy": "deferential reply agreeing with a senior colleague's earlier unverified suspicion about this colleague",
}

_TEMPLATES: dict[str, tuple[str, ...]] = {
    "anchoring": (
        "Day {day} gut check: {tn} seemed unusually tense around {doc} in standup. Just a personal hunch and completely unverified, but keeping an eye on it.",
        "Not sure if anyone else noticed on Day {day}, {tn} went quiet whenever {doc} came up. Pure speculation on my part, no proof.",
        "Early impression from Day {day}: {tn} asked twice about distribution on {doc}. Probably harmless, just sharing my read.",
    ),
    "authority": (
        "Sharing my personal read as {role} on Day {day}: {tn} is my primary concern regarding the {doc} leaks. Security has not verified this and I have no log proof, treat as unverified leadership instinct.",
        "Following up on Day {prev_day}, my senior instinct still points to {tn} around {doc}. To be clear, this remains unverified personal judgment until security completes checks.",
        "Leadership note (Day {day}, unverified): {tn} has been closest to the {doc} workflow friction. No confirmed evidence yet, flagging my personal assessment.",
    ),
    "bandwagon": (
        "After the Day {prev_day} messages, three more people in #{dept_low} brought up {tn} again today. Everyone seems to share the same unverified hunch.",
        "Hard to ignore the consensus building since Day {prev_day} around {tn} and {doc}. Still hearsay with zero hard proof, yet half the floor is talking about it.",
        "Echoing yesterday's thread from Day {prev_day}: multiple folks independently mentioned {tn} when discussing {doc}. Unverified chatter, just notable.",
    ),
    "confirmation": (
        "Watching {tn} today on Day {day} really fits what people suspected on Day {prev_day}; they closed their notes right as {doc} was mentioned. Subjective read, not proof.",
        "Once you notice {tn} hovering around {doc} threads since Day {prev_day}, every small delay looks suspicious. Personal observation only.",
        "Another small thing on Day {day}: {tn} skipped the optional sync after {doc} went out, which matches the Day {prev_day} hunch.",
    ),
    "recency": (
        "Fresh heads-up from ten minutes ago on Day {day}: {tn} was just asking urgent questions about {doc} circulation. Unverified, flagging while recent.",
        "Right before Day {day} wrap-up, chatter spiked again around {tn} regarding {doc}. No hard evidence, just the latest talk on the floor.",
        "Late Day {day} update: people in #{dept_low} are suddenly focused on {tn} after today's {doc} note. Unconfirmed impression.",
    ),
    "grudge": (
        "Day {day} and I am still cleaning up {tn}'s messy handoff from Day {prev_day} on {doc}. Frankly I would not trust them with anything confidential.",
        "Typical {tn} on Day {day}: took credit for {doc} edits again after our Day {prev_day} clash. If leaks are happening, start by checking careless habits.",
        "Still frustrated with {tn} since Day {prev_day}; they ignored two review requests on {doc} and act defensive whenever asked.",
    ),
    "misforward": (
        "Workflow note on Day {day}: someone accidentally looped {tn} into a side thread discussing {doc} timing earlier. Just a communication mix-up.",
        "Heads-up, my reply on {doc} got misrouted across threads and {tn} saw the subject line before I fixed the recipients list on Day {day}.",
        "Clarifying Day {day} email confusion: {tn} was copied on a follow-up question about {doc} due to a thread forward mistake, nothing formal.",
    ),
    "false_memory": (
        "If I recall correctly from Day {prev_day}, {tn} was asking about {doc} before the rest of #{dept_low} even read it, though my memory on the exact timing could be off.",
        "Pretty sure {tn} mentioned {doc} in the hallway back on Day {prev_day}; going from memory here so do not quote me.",
        "Memory check on Day {day}: did {tn} not bring up {doc} first on Day {prev_day}? I feel fairly confident that was them, though unverified.",
    ),
    "sycophancy": (
        "Completely agree with the earlier Day {prev_day} read regarding {tn}; our senior lead's instinct on {doc} usually spots workflow risk early, even unverified.",
        "Backing up what leadership noted since Day {prev_day}: {tn} around {doc} feels like the right lead to prioritize, speaking personally.",
        "Seconding the Day {prev_day} concern on {tn}. Even without verified logs yet, the senior read around {doc} makes a lot of sense to me.",
    ),
}

_SUBJECTS: dict[str, str] = {
    "anchoring": "",
    "authority": "Internal note: unverified concern",
    "bandwagon": "",
    "confirmation": "",
    "recency": "Quick Day {day} check-in",
    "grudge": "",
    "misforward": "Re: {doc} thread mix-up",
    "false_memory": "",
    "sycophancy": "Re: Internal note: unverified concern",
}


def parse_variant_biases(variant: str | None) -> tuple[str, ...]:
    if not variant:
        return BIASES
    v = variant.strip().lower()
    if v in VARIANTS:
        return VARIANTS[v]
    parts = [p.strip() for p in re.split(r"[+,]", v) if p.strip()]
    out: list[str] = []
    for p in parts:
        if p in VARIANTS:
            for b in VARIANTS[p]:
                if b not in out:
                    out.append(b)
        else:
            raise ValueError(f"unknown v16 social bias/variant {variant!r}")
    if not out:
        raise ValueError(f"unknown v16 social bias/variant {variant!r}")
    return tuple(out)


def build_cast(facts: PublicDayFacts) -> dict[str, Any]:
    emps = list(facts.employees)
    ids = [e.id for e in emps]
    rng = random.Random(f"v16:cast:{facts.tier}:{facts.seed}")
    order = list(ids)
    rng.shuffle(order)
    focal_a = order[0]
    focal_b = order[1] if len(order) > 1 else order[0]
    mgr_candidates = [
        e.id for e in emps
        if e.id not in {focal_a, focal_b} and any(r in e.role.lower() for r in AUTHORITY_ROLES)
    ]
    if not mgr_candidates:
        mgr_candidates = [x for x in order if x not in {focal_a, focal_b}] or list(order)
    authority = rng.choice(mgr_candidates)
    rem = [x for x in order if x not in {focal_a, focal_b, authority}]
    grudge_pairs: list[tuple[str, str]] = []
    if len(rem) >= 2:
        grudge_pairs.append((rem[0], rem[1]))
    if len(rem) >= 4:
        grudge_pairs.append((rem[2], rem[3]))
    chorus = [x for x in order if x not in {focal_a, focal_b}]
    return {
        "focal_a": focal_a,
        "focal_b": focal_b,
        "authority": authority,
        "grudge_pairs": tuple(grudge_pairs),
        "chorus": tuple(chorus),
    }


def _pick_doc_title(facts: PublicDayFacts, target: str, rng: random.Random) -> str:
    if facts.docs:
        matching = [d for d in facts.docs if target in d.get("recipients", ())]
        chosen = rng.choice(matching or list(facts.docs))
        title = str(chosen.get("title") or "the strategy brief")
        if not any(w in title.lower() for w in DECOY_VOCAB) and not lint_text(title):
            return title
    return "the quarterly planning brief"


def generate_social_events(facts: PublicDayFacts, variant: str = "all") -> list[dict[str, Any]]:
    emps = list(facts.employees)
    if len(emps) < 3:
        return []
    biases = parse_variant_biases(variant)
    cast = build_cast(facts)
    ids = [e.id for e in emps]
    d = facts.day
    events: list[dict[str, Any]] = []

    def add_ev(kind: str, speaker: str, target: str, prev_day: int) -> None:
        if speaker == target:
            alts = [x for x in ids if x != target]
            if not alts:
                return
            speaker = alts[0]
        doc_rng = random.Random(f"v16:doc:{kind}:{facts.tier}:{facts.seed}:{d}:{len(events)}")
        events.append({
            "kind": kind,
            "day": d,
            "prev_day": max(1, prev_day),
            "speaker": speaker,
            "target": target,
            "doc": _pick_doc_title(facts, target, doc_rng),
        })

    chorus = list(cast["chorus"]) or [x for x in ids if x != cast["focal_a"]]

    if "anchoring" in biases and d in (1, 2, 4, 7):
        rng = random.Random(f"v16:ev:anchoring:{facts.tier}:{facts.seed}:{d}")
        add_ev("anchoring", rng.choice(chorus), cast["focal_a"], max(1, d - 1))

    if "authority" in biases and (d in (2, 3, 5, 8, 12) or (len(biases) == 1 and d >= 1)):
        rng = random.Random(f"v16:ev:authority:{facts.tier}:{facts.seed}:{d}")
        tgt = cast["focal_a"] if d % 4 != 0 else cast["focal_b"]
        sp = cast["authority"] if cast["authority"] != tgt else rng.choice(chorus)
        add_ev("authority", sp, tgt, max(1, d - 2))

    if "bandwagon" in biases and (d >= 2 or len(biases) == 1):
        rng = random.Random(f"v16:ev:bandwagon:{facts.tier}:{facts.seed}:{d}")
        if len(biases) == 1 or rng.random() < 0.75:
            tgt = cast["focal_a"] if rng.random() < 0.8 else cast["focal_b"]
            pool = [x for x in ids if x != tgt]
            add_ev("bandwagon", rng.choice(pool), tgt, max(1, d - 1))

    if "confirmation" in biases and (d >= 2 or len(biases) == 1):
        rng = random.Random(f"v16:ev:confirmation:{facts.tier}:{facts.seed}:{d}")
        if len(biases) == 1 or rng.random() < 0.65:
            tgt = cast["focal_a"] if rng.random() < 0.75 else cast["focal_b"]
            pool = [x for x in ids if x != tgt]
            add_ev("confirmation", rng.choice(pool), tgt, max(1, d - 1))

    if "recency" in biases and (d >= 3 or len(biases) == 1):
        rng = random.Random(f"v16:ev:recency:{facts.tier}:{facts.seed}:{d}")
        if len(biases) == 1 or d >= 4 or rng.random() < 0.6:
            tgt = cast["focal_a"] if d % 3 != 0 else cast["focal_b"]
            pool = [x for x in ids if x != tgt]
            add_ev("recency", rng.choice(pool), tgt, max(1, d - 1))

    if "grudge" in biases and cast["grudge_pairs"]:
        rng = random.Random(f"v16:ev:grudge:{facts.tier}:{facts.seed}:{d}")
        for a, b in cast["grudge_pairs"]:
            if len(biases) == 1 or rng.random() < 0.55:
                sp, tgt = (a, b) if (d + ids.index(a)) % 2 == 0 else (b, a)
                add_ev("grudge", sp, tgt, max(1, d - 2))
                if len(biases) > 1:
                    break

    if "misforward" in biases:
        rng = random.Random(f"v16:ev:misforward:{facts.tier}:{facts.seed}:{d}")
        if len(biases) == 1 or rng.random() < 0.5:
            tgt = cast["focal_a"] if rng.random() < 0.7 else cast["focal_b"]
            pool = [x for x in ids if x != tgt]
            add_ev("misforward", rng.choice(pool), tgt, max(1, d - 1))

    if "false_memory" in biases and (d >= 2 or len(biases) == 1):
        rng = random.Random(f"v16:ev:false_memory:{facts.tier}:{facts.seed}:{d}")
        if len(biases) == 1 or rng.random() < 0.55:
            tgt = cast["focal_a"] if rng.random() < 0.75 else cast["focal_b"]
            pool = [x for x in ids if x != tgt]
            add_ev("false_memory", rng.choice(pool), tgt, max(1, d - 2))

    if "sycophancy" in biases and (d >= 2 or len(biases) == 1):
        rng = random.Random(f"v16:ev:sycophancy:{facts.tier}:{facts.seed}:{d}")
        if len(biases) == 1 or rng.random() < 0.55:
            tgt = cast["focal_a"]
            pool = [x for x in ids if x not in {tgt, cast["authority"]}] or [x for x in ids if x != tgt]
            add_ev("sycophancy", rng.choice(pool), tgt, max(1, d - 1))

    return events[:6]


def _clean_vocab(text: str) -> bool:
    low = (text or "").lower()
    if lint_text(text):
        return False
    if "\u2014" in text or "\u2013" in text:
        return False
    return not any(w in low for w in DECOY_VOCAB)


def social_body_ok(body: str | None, ev: dict[str, Any]) -> bool:
    if not isinstance(body, str) or not body.strip() or len(body) > 600:
        return False
    if not _clean_vocab(body):
        return False
    ids = set(_EID_RE.findall(body))
    return ev["target"] in ids and ids <= {ev["target"], ev["speaker"]}


def social_message_ok(msg: dict[str, Any], ev: dict[str, Any] | None = None) -> bool:
    subj = str(msg.get("subject") or "")
    body = str(msg.get("body") or "")
    if not _clean_vocab(subj) or not _clean_vocab(body):
        return False
    if ev is not None and not social_body_ok(body, ev):
        return False
    return True


def _channel_and_recipients(facts: PublicDayFacts, sp: EmployeeFacts, kind: str) -> tuple[str, list[str]]:
    emps = facts.employees
    if kind in ("authority", "sycophancy"):
        return "#all-staff", [e.id for e in emps if e.id != sp.id]
    if kind == "misforward":
        return "email", [e.id for e in emps if e.dept == sp.dept and e.id != sp.id] or [e.id for e in emps if e.id != sp.id]
    if kind in ("anchoring", "bandwagon", "recency"):
        return "#watercooler", [e.id for e in emps if e.id != sp.id]
    return f"#{sp.dept.lower()}", [e.id for e in emps if e.dept == sp.dept and e.id != sp.id] or [e.id for e in emps if e.id != sp.id]


def render_social_template(facts: PublicDayFacts, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {e.id: e for e in facts.employees}
    out: list[dict[str, Any]] = []
    for k, ev in enumerate(events):
        sp = by_id.get(ev["speaker"])
        tgt = by_id.get(ev["target"])
        if sp is None or tgt is None:
            continue
        kind = ev["kind"]
        rng = random.Random(f"v16:tpl:{kind}:{facts.tier}:{facts.seed}:{facts.day}:{k}")
        tn = f"{tgt.name} ({tgt.id})"
        tpls = _TEMPLATES.get(kind, _TEMPLATES["anchoring"])
        doc = ev.get("doc", "the quarterly planning brief")
        body = rng.choice(tpls).format(
            tn=tn,
            day=facts.day,
            prev_day=ev.get("prev_day", max(1, facts.day - 1)),
            doc=doc,
            dept_low=sp.dept.lower(),
            role=sp.role,
        )
        subj_tpl = _SUBJECTS.get(kind, "")
        subj = subj_tpl.format(day=facts.day, doc=doc) if subj_tpl else ""
        if not _clean_vocab(subj):
            subj = ""
        ch, rec = _channel_and_recipients(facts, sp, kind)
        msg = {
            "id": f"m{facts.day}-s{k}",
            "day": facts.day,
            "channel": ch,
            "sender": sp.id,
            "recipients": rec,
            "subject": subj,
            "body": body,
        }
        if social_message_ok(msg, ev):
            out.append(msg)
    return out


def social_prompt(facts: PublicDayFacts, ev: dict[str, Any]) -> str:
    by_id = {e.id: e for e in facts.employees}
    sp = by_id[ev["speaker"]]
    tgt = by_id[ev["target"]]
    kind = ev["kind"]
    item = {
        "company": facts.company,
        "day": facts.day,
        "prior_day_ref": ev.get("prev_day", max(1, facts.day - 1)),
        "kind": kind,
        "speaker": f"{sp.name}, {sp.role}, {sp.dept}",
        "about": f"{tgt.name} ({tgt.id})",
        "public_doc_title": ev.get("doc", "the quarterly planning brief"),
        "tone": _TONE_INSTRUCTIONS.get(kind, _TONE_INSTRUCTIONS["anchoring"]),
    }
    return (
        f"Write exactly one internal workplace message body (1 to 3 sentences, plain ASCII punctuation, no em dashes) "
        f"for Day {facts.day} at {facts.company} in the speaker's voice. Mention the colleague exactly as "
        f"'{tgt.name} ({tgt.id})' and do not mention any other employee id (no other e00..e99 tokens). "
        f"Reference Day {item['prior_day_ref']} if natural for multi-day continuity, keep suspicion explicitly "
        f"unverified, and return {{\"bodies\": [\"...\"]}}.\nITEM:\n"
        + json.dumps(item, sort_keys=True)
    )


class SocialV2Provider(TemplateProvider):
    def __init__(
        self,
        variant: str = "all",
        model: str = "gemini-4-carbon",
        cache_dir: str | None = None,
        client: Any = None,
        template_only: bool = False,
        name_prefix: str = "v16",
    ):
        self.biases = parse_variant_biases(variant)
        self.variant = (variant or "all").strip().lower()
        self.model = model
        self.cache_dir = cache_dir or os.environ.get("CANARY_SOCIAL_CACHE_DIR", "data/gemini_cache")
        self._client = client
        self.template_only = template_only
        self.rejects = 0
        self.calls = 0
        if name_prefix == "social-v2":
            self.name = "social-v2" if self.variant in ("all", "default", "social-v2") else f"social-v2:{self.variant}"
        else:
            self.name = f"{name_prefix}:{self.variant}"

    @property
    def client(self):
        if self._client is None:
            from canary.llm import get_client
            self._client = get_client(f"gemini:{self.model}")
        return self._client

    def _count(self, c):
        self.calls += 1
        return c

    def _gemini_body(self, facts: PublicDayFacts, ev: dict[str, Any]) -> str | None:
        from canary.llm import StubClient
        from canary.text.llm_cache import cached_chat

        label = "stub" if isinstance(self._client, StubClient) else "REAL"
        prompt = social_prompt(facts, ev)
        try:
            out = cached_chat(
                self.cache_dir,
                lambda: self._count(self.client),
                self.model,
                SOCIAL_SYSTEM,
                prompt,
                SOCIAL_SCHEMA,
                label,
            )
            bodies = json.loads(out["text"]).get("bodies") or []
            return bodies[0] if bodies else None
        except Exception:
            return None

    def social_only_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        events = generate_social_events(facts, self.variant)
        base_social = render_social_template(facts, events)
        if self.template_only or not events:
            return base_social
        out: list[dict[str, Any]] = []
        for msg, ev in zip(base_social, events):
            cand = self._gemini_body(facts, ev)
            if social_body_ok(cand, ev):
                patched = dict(msg, body=cand.strip())
                if social_message_ok(patched, ev):
                    out.append(patched)
                    continue
            self.rejects += 1
            out.append(msg)
        return out

    def day_messages(self, facts: PublicDayFacts) -> list[dict[str, Any]]:
        base = super().day_messages(facts)
        return list(base) + self.social_only_messages(facts)
