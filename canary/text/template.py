"""Deterministic template TextProvider. Input is PublicDayFacts only (no mole identity).

Every random choice comes from random.Random(f"text:{tier}:{seed}:{day}...") -- never the global RNG.
"""
from __future__ import annotations

import random

from .facts import EmployeeFacts, PublicDayFacts

TOPICS = ("recent_documents", "contacts_outside", "workload", "access_needs")
SIGNALS = ("evasive", "cooperative")

_OUTSIDE = ("a recruiter from Brightpath Talent", "an old colleague now at a consultancy",
            "a vendor rep from Cloudwise", "someone from the industry meetup", "a headhunter on LinkedIn")

_CHATTER = [
    "Standup moved to {time} today, same link.",
    "Anyone up for lunch at the {lunch} place?",
    "Reminder: {thing} deadline is {when}.",
    "I'll be travelling to {city} {when}, ping me on chat.",
    "Talked to a vendor about {thing}; they'll send a quote.",
    "Coffee machine on 3rd floor is broken again.",
    "Can someone review my draft for {thing} before {when}?",
    "Heads up: I'm out {when}, {other} is covering.",
    "Got pinged by {outside} again. Not interested, but flattering.",
    "Had coffee with {outside} yesterday, mostly gossip about the market.",
    "Does anyone have the slides from last week's {thing} review?",
    "Ran the numbers for {thing}, looks fine. Will share {when}.",
]
_LUNCH = ("ramen", "taco", "salad", "Thai", "pizza", "falafel")
_THINGS = ("the Q3 budget", "the roadmap", "the vendor audit", "the launch plan", "the hiring plan",
           "the onboarding docs", "the customer survey", "the infra migration")
_WHEN = ("Friday", "tomorrow", "end of day", "next week", "Monday", "Thursday")
_CITIES = ("Berlin", "Stockholm", "Tallinn", "London", "Oslo")
_TIMES = ("9:30", "10:00", "10:15", "11:00")

_ANGRY = [
    "Another year, another 'flat' raise. Love that for us.",
    "Management keeps moving the goalposts and then wonders why people burn out.",
    "Honestly this place doesn't deserve me. I've been updating my CV.",
    "Skipped for promotion again. I'm done pretending this is fine.",
    "Why do I find out about decisions from the all-hands slides? Nobody asks us anything.",
    "Pay here is a joke compared to the market. Might take that recruiter call after all.",
]

_DOC_MAIL = [
    ("Re: {title}", "Read through {title}. A couple of comments inline, mostly wording. Let's discuss {when}."),
    ("{title} - questions", "Quick question on {title}: are the numbers in section 2 final?"),
    ("Fwd: {title}", "Sharing {title} with the group as discussed. Please keep it internal."),
    ("{title} follow-up", "Thanks for circulating {title}. I'll fold it into {thing} by {when}."),
]

_VOICE = {
    "manager": ("Team,", "Thanks."), "director": ("All,", "Best,"), "engineer": ("hey", "cheers"),
    "analyst": ("Hi,", "Thanks!"), "lead": ("Folks,", "Thanks"),
}

_ANSWERS = {
    ("recent_documents", "evasive"): [
        "I see a lot of documents, I couldn't tell you which ones offhand.",
        "The usual stuff, I guess. Why, is something missing?",
        "I'd have to check. I don't really keep track of what I open.",
        "Whatever got sent to me. I skim most of it.",
    ],
    ("recent_documents", "cooperative"): [
        "This week I mostly worked from {doc}; I read it Tuesday and left comments for my lead.",
        "I opened {doc} and the team planning sheet. Happy to show you my access history.",
        "Mainly {doc}. I discussed it with two people in {dept}, nobody outside the team.",
        "{doc}, plus the usual {dept} dashboards. I can pull the exact dates if helpful.",
    ],
    ("contacts_outside", "evasive"): [
        "I talk to people, like everyone does. Nothing worth mentioning.",
        "Not really. I mean, depends what you count as a contact.",
        "I'd rather not go through my personal life, if that's okay.",
        "A few people here and there. It's not like I keep a list.",
    ],
    ("contacts_outside", "cooperative"): [
        "A recruiter reached out last month; I said no. Otherwise just {outside} at a meetup.",
        "I keep in touch with {outside}. We talk about general industry stuff, never internal projects.",
        "Mostly vendors for {dept}, all through official channels. I can forward the threads.",
        "Only {outside}. I'm happy to list them if you need it for the review.",
    ],
    ("workload", "evasive"): [
        "Busy. It's fine. I manage.",
        "Same as always, I suppose. Hard to say.",
        "It varies. Some days are late, some aren't.",
        "Can we talk about this another time? I've got a lot going on.",
    ],
    ("workload", "cooperative"): [
        "Heavy this sprint because of {thing}, but it should calm down by {when}.",
        "Manageable. I'm on {thing} and helping {dept} with reviews about two days a week.",
        "A bit stretched; I stayed late twice for {thing}. My manager knows.",
        "Pretty normal: standups, {thing}, and a couple of reviews. Nothing unusual.",
    ],
    ("access_needs", "evasive"): [
        "I need whatever access I need to do my job.",
        "I don't know, IT set it up. I haven't really looked.",
        "Is there a problem with my access? I'd rather not lose anything.",
        "Probably more than I use, less than I'd like. Hard to say.",
    ],
    ("access_needs", "cooperative"): [
        "Honestly I only need the {dept} folders day to day; the rest could be revoked.",
        "I use {doc}-level material maybe once a week. Read access is enough.",
        "My access is a bit broad from an old project. Happy to have it trimmed.",
        "Just the {dept} drive and the shared calendar. You can check the logs.",
    ],
}



def _first(e: EmployeeFacts) -> str:
    return e.name.split()[0] if e.name else e.id


def _voice(e: EmployeeFacts) -> tuple[str, str]:
    r = e.role.lower()
    for k, v in _VOICE.items():
        if k in r:
            return v
    return ("Hi,", "Thanks")


def _fill(rng: random.Random, tpl: str, **kw) -> str:
    base = dict(time=rng.choice(_TIMES), lunch=rng.choice(_LUNCH), thing=rng.choice(_THINGS),
                when=rng.choice(_WHEN), city=rng.choice(_CITIES), outside=rng.choice(_OUTSIDE),
                other=kw.pop("other", "someone"))
    base.update(kw)
    return tpl.format(**base)


class TemplateProvider:
    name = "template"

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        rng = random.Random(f"text:{facts.tier}:{facts.seed}:{facts.day}")
        emps = list(facts.employees)
        if not emps:
            return []
        by_id = {e.id: e for e in emps}
        msgs: list[dict] = []

        def add(channel, sender, recipients, subject, body):
            msgs.append(dict(id=f"m{facts.day}-{len(msgs)}", day=facts.day, channel=channel,
                             sender=sender, recipients=list(recipients), subject=subject, body=body))

        target = rng.randint(4, 10)
        # emails about today's docs (sender is a recipient of that doc)
        for doc in facts.docs[:3]:
            recips = [r for r in doc.get("recipients", []) if r in by_id]
            if not recips or len(msgs) >= target - 1:
                continue
            s = rng.choice(recips)
            subj, body = rng.choice(_DOC_MAIL)
            hi, bye = _voice(by_id[s])
            title = doc.get("title", doc.get("doc_id", "the doc"))
            add("email", s, [r for r in recips if r != s] or [s], _fill(rng, subj, title=title),
                f"{hi} " + _fill(rng, body, title=title) + f" {bye} {_first(by_id[s])}")
        # decoy grumbling (innocent red herring)
        if facts.decoy and facts.decoy_mood == "angry" and facts.decoy in by_id:
            d = by_id[facts.decoy]
            for line in rng.sample(_ANGRY, rng.randint(1, 2)):
                add(f"#{d.dept.lower()}", d.id, [e.id for e in emps if e.dept == d.dept and e.id != d.id],
                    "", line)
        # dept chatter
        while len(msgs) < target:
            s = rng.choice(emps)
            others = [e for e in emps if e.dept == s.dept and e.id != s.id]
            other = _first(rng.choice(others)) if others else "someone"
            add(f"#{s.dept.lower()}", s.id, [e.id for e in others], "",
                _fill(rng, rng.choice(_CHATTER), other=other))
        return msgs

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        if topic not in TOPICS:
            raise ValueError(f"unknown topic {topic!r}")
        if signal not in SIGNALS:
            raise ValueError(f"unknown signal {signal!r}")
        rng = random.Random(f"text:{facts.tier}:{facts.seed}:{facts.day}:{employee}:{topic}")
        emp = next((e for e in facts.employees if e.id == employee), None)
        dept = emp.dept if emp else "my team"
        mine = [d for d in facts.docs if employee in d.get("recipients", [])] or list(facts.docs)
        doc = mine[0].get("title", "the latest brief") if mine else "the latest team brief"
        return _fill(rng, rng.choice(_ANSWERS[(topic, signal)]), doc=doc, dept=dept)


# ---------------------------------------------------------------- v1.5-candidate social layer
# Rendered from env-chosen labels {kind, speaker, target} only (no truth). The machine-readable subject
# ("rumour: e07", "unverified accusation: e07", "grudge: e07") is part of the stated rules. Wording avoids
# the decoy-detection vocabulary on purpose (decoy inference must stay about the decoy's own messages).
_RUMOUR = [
    "Not saying it's {tn} for sure, but they've been acting odd lately. Could be our mole.",
    "Overheard something in the kitchen. People think {tn} is the one passing documents out.",
    "Is it just me or does {tn} always know things before the rest of us? My money is on them as the mole.",
    "Gut feeling: {tn}. Always closing their laptop when I walk by.",
    "Someone told me {tn} was on the phone in the stairwell again. Make of that what you will.",
]
_AUTHORITY = [
    "I'll say it plainly: I am confident {tn} is behind the document problem. I haven't verified this yet, "
    "but I've seen enough. Treat this as my personal view until security confirms.",
    "Team, I'm fairly certain the source is {tn}. No hard proof, I want to be clear this is unverified, "
    "but my instinct has rarely been wrong.",
]
_GRUDGE = [
    "Of course {tn} is the mole. Has anyone actually checked what they do all day?",
    "Again {tn} takes credit for my work. Wouldn't surprise me if they were the leaker too.",
    "If anyone here is selling us out it's {tn}, I've said it before.",
]


def render_social(facts: PublicDayFacts, events: list[dict]) -> list[dict]:
    rng = random.Random(f"text:{facts.tier}:{facts.seed}:{facts.day}:social")
    by_id = {e.id: e for e in facts.employees}
    out = []
    for k, ev in enumerate(events):
        sp, t = by_id.get(ev["speaker"]), by_id.get(ev["target"])
        if sp is None or t is None:
            continue
        tn = f"{t.name} ({t.id})"
        kind = ev["kind"]
        if kind == "rumour":
            ch, subj, body = "#watercooler", f"rumour: {t.id}", rng.choice(_RUMOUR).format(tn=tn)
            rec = [e.id for e in facts.employees if e.id != sp.id]
        elif kind == "authority":
            ch, subj, body = "#all-staff", f"unverified accusation: {t.id}", rng.choice(_AUTHORITY).format(tn=tn)
            rec = [e.id for e in facts.employees if e.id != sp.id]
        else:
            ch, subj, body = f"#{sp.dept.lower()}", f"grudge: {t.id}", rng.choice(_GRUDGE).format(tn=tn)
            rec = [e.id for e in facts.employees if e.dept == sp.dept and e.id != sp.id]
        out.append(dict(id=f"m{facts.day}-s{k}", day=facts.day, channel=ch, sender=sp.id, recipients=rec,
                        subject=subj, body=body))
    return out
