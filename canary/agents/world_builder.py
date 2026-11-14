"""Gemini world builder: personas, department culture and chatter templates from PUBLIC facts.

    text = build_world_text(public_facts, client)          # dict (WorldText schema)
    provider = GeminiWorldText(text, name="gemini:<model>") # implements canary.text TextProvider
    assert_no_truth(text, world)                            # lint: no truth leaked into text

INTEGRITY: the input is sanitised by `public_view()`; truth keys (mole, decoy flag, ledger,
strategy) are dropped before anything reaches the model. Rendering is deterministic given
(tier, seed, day), so text can be frozen for judge seeds. The *signal* (evasive/cooperative,
decoy mood) is always chosen by the env; this provider only picks words.
"""
from __future__ import annotations

import json
import random
import re
from typing import Any

from pydantic import BaseModel, Field

from ._common import get, load_prompt, structured_call

TRUTH_KEYS = frozenset({"mole", "mole_id", "is_mole", "decoy", "is_decoy", "mole_strategy",
                        "ledger", "truth", "secret", "rng_state"})
TRUTH_WORDS = re.compile(r"\b(mole|moles|leaker|leaking to|double agent|spy|spying|traitor|culprit|"
                         r"insider threat|informant)\b", re.I)
TONES = ("dry", "upbeat", "formal", "terse", "chatty", "warm", "blunt")


class Persona(BaseModel):
    employee_id: str
    bio: str = Field(max_length=400)
    tone: str = Field(max_length=40)


class DeptCulture(BaseModel):
    dept: str
    culture: str = Field(max_length=600)


class WorldText(BaseModel):
    company_blurb: str = Field(default="", max_length=600)
    personas: list[Persona] = Field(default_factory=list)
    departments: list[DeptCulture] = Field(default_factory=list)
    chatter_templates: list[str] = Field(default_factory=list, max_length=40)


def public_view(public_facts: Any) -> dict:
    """Strip anything that is not a public fact. Accepts dicts or PublicDayFacts-like objects."""
    if not isinstance(public_facts, dict):
        public_facts = {k: get(public_facts, k) for k in ("company", "tier", "employees", "docs")}
    emps = []
    for e in public_facts.get("employees") or []:
        emps.append({k: get(e, k) for k in ("id", "name", "dept", "role", "clearance") if get(e, k) is not None})
    docs = [{"title": get(d, "title"), "day": get(d, "day")} for d in public_facts.get("docs") or []]
    depts = sorted({e["dept"] for e in emps if "dept" in e} | set(public_facts.get("depts") or []))
    return {"company": public_facts.get("company") or "Northwind Analytics",
            "employees": emps, "depts": depts, "docs": docs[:60]}


def _fallback_persona(e: dict, rng: random.Random) -> Persona:
    tone = rng.choice(TONES)
    return Persona(employee_id=e["id"], tone=tone,
                   bio=f"{e.get('name', e['id'])} is a {e.get('role', 'staff member')} in "
                       f"{e.get('dept', 'the company')}; {tone} on chat, mostly heads-down.")


DEFAULT_CHATTER = [
    "Standup moved to {when}, same link.",
    "Has anyone in {dept} finished reading {doc_title}?",
    "{colleague}, can you review my notes on {doc_title} before {when}?",
    "Coffee machine is broken again. Send help.",
    "Out {when}, {colleague} is covering for me.",
    "Quick sync on {doc_title} {when}? Ten minutes max.",
    "Who booked the big meeting room {when}?",
    "Thanks {colleague}, that fixed it.",
]


def build_world_text(public_facts: dict, client, seed: int = 0) -> dict:
    """Ask the LLM for the company's text layer; fill/repair deterministically. Returns WorldText dict."""
    pub = public_view(public_facts)
    cfg = load_prompt("world_builder")
    parsed, err = structured_call(client, cfg.get("system", "Write company personas."),
                                  json.dumps(pub), WorldText)
    wt = parsed or WorldText()
    rng = random.Random(f"world_builder:{seed}:{pub['company']}")
    ids = [e["id"] for e in pub["employees"]]
    have = {p.employee_id: p for p in wt.personas if p.employee_id in ids}  # drop invented ids
    personas = [have.get(e["id"]) or _fallback_persona(e, rng) for e in pub["employees"]]
    depts = {d.dept: d for d in wt.departments if d.dept in pub["depts"]}
    cultures = [depts.get(d) or DeptCulture(dept=d, culture=f"{d} runs on weekly planning and a busy chat channel.")
                for d in pub["depts"]]
    templates = [t for t in wt.chatter_templates if _template_ok(t)] or list(DEFAULT_CHATTER)
    out = WorldText(company_blurb=wt.company_blurb or f"{pub['company']} is a mid-size analytics firm.",
                    personas=personas, departments=cultures, chatter_templates=templates).model_dump()
    out["meta"] = {"llm_ok": parsed is not None, "error": err,
                   "n_llm_personas": len(have), "n_fallback_personas": len(ids) - len(have)}
    # Scrub anything that would leak meaning into the world (e.g. a model writing "the mole").
    for p in out["personas"]:
        if TRUTH_WORDS.search(p["bio"]):
            p["bio"] = _fallback_persona({"id": p["employee_id"]}, rng).bio
    out["chatter_templates"] = [t for t in out["chatter_templates"] if not TRUTH_WORDS.search(t)] or list(DEFAULT_CHATTER)
    return out


_ALLOWED_PH = {"sender", "dept", "doc_title", "colleague", "when"}


def _template_ok(t: str) -> bool:
    try:
        names = {m.group(1) for m in re.finditer(r"\{(\w*)\}", t)}
        return bool(t.strip()) and names <= _ALLOWED_PH and len(t) <= 280
    except Exception:
        return False


def _walk_strings(x: Any):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(x, (list, tuple)):
        for v in x:
            yield from _walk_strings(v)


def assert_no_truth(text: Any, world: Any) -> None:
    """Lint: raise AssertionError if `text` (str/dict/list) carries hidden truth from `world`.

    Checks: (1) no truth keys (mole, decoy flag, strategy...) anywhere in the structure;
    (2) no mole/spy/traitor vocabulary; (3) the mole is not singled out: its persona/messages
    must not differ in shape (e.g. it is the only employee missing or given a special tone).
    `world` may be a dict or object with `mole` (id) and optionally `employees`.
    """
    if isinstance(text, dict):
        bad = TRUTH_KEYS & {str(k) for k in _all_keys(text)}
        assert not bad, f"truth keys in text: {sorted(bad)}"
    for s in _walk_strings(text):
        m = TRUTH_WORDS.search(s)
        assert not m, f"truth vocabulary in text: {m.group(0)!r} in {s[:80]!r}"
    mole = get(world, "mole") or get(world, "mole_id")
    if isinstance(text, dict) and mole and text.get("personas"):
        pids = [p.get("employee_id") for p in text["personas"]]
        emps = [get(e, "id") for e in (get(world, "employees") or [])]
        if emps:
            assert sorted(pids) == sorted(emps), "persona set differs from roster (mole singled out?)"
        tones = [p.get("tone") for p in text["personas"] if p.get("employee_id") == mole]
        others = {p.get("tone") for p in text["personas"] if p.get("employee_id") != mole}
        assert not tones or len(text["personas"]) < 4 or tones[0] in others, "mole has a unique tone"


def _all_keys(x: Any):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(x, list):
        for v in x:
            yield from _all_keys(v)


_INTERVIEW = {
    ("evasive", "terse"): ["Not sure. Why?", "Can't recall.", "The usual."],
    ("cooperative", "terse"): ["Mostly {doc}. Logs will confirm.", "{doc}, for the {dept} plan. Happy to show you."],
    "evasive": ["I'd have to check, I don't keep track of that kind of thing.",
                "Hard to say. Is something wrong?",
                "I'd rather not go into it, if that's okay.",
                "The usual stuff, honestly. Nothing worth mentioning."],
    "cooperative": ["Sure. This week I mostly worked from {doc}; I can pull my access history for you.",
                    "Happy to help: {doc} and the {dept} dashboards, nothing shared outside the team.",
                    "I spoke with two people in {dept} about {doc}. Ask them, they'll confirm.",
                    "Openly: a recruiter pinged me last month, I said no. Otherwise just {dept} work."],
}
_ANGRY = ["Another reorg nobody asked for. Love that for us.",
          "Skipped for promotion again. Updating my CV tonight.",
          "Why do we hear about decisions from the all-hands slides?"]


class GeminiWorldText:
    """TextProvider (canary/text/facts.py protocol) rendering words from a frozen WorldText dict.

    No LLM calls at render time: Gemini writes the world once (build_world_text), then rendering
    is deterministic per (tier, seed, day), so judge-seed text can be frozen and replayed.
    """

    def __init__(self, world_text: dict, name: str = "gemini-world"):
        self.name = name
        self.wt = world_text
        self.persona = {p["employee_id"]: p for p in world_text.get("personas", [])}
        self.templates = world_text.get("chatter_templates") or DEFAULT_CHATTER

    def persona_of(self, employee: str) -> dict:
        return self.persona.get(employee, {"employee_id": employee, "bio": "", "tone": "dry"})

    def day_messages(self, facts) -> list[dict]:
        tier, seed, day = get(facts, "tier", ""), get(facts, "seed", 0), get(facts, "day", 0)
        rng = random.Random(f"gemini-text:{tier}:{seed}:{day}")
        emps = list(get(facts, "employees") or [])
        if not emps:
            return []
        docs = list(get(facts, "docs") or [])
        restricted = set(get(facts, "restricted") or ())
        msgs: list[dict] = []
        for k in range(rng.randint(4, 8)):
            e = rng.choice(emps)
            peers = [x for x in emps if get(x, "dept") == get(e, "dept") and get(x, "id") != get(e, "id")] or emps
            col = rng.choice(peers)
            doc = rng.choice(docs) if docs else {"title": "the weekly report"}
            body = rng.choice(self.templates).format(
                sender=get(e, "name"), dept=get(e, "dept"), doc_title=get(doc, "title"),
                colleague=get(col, "name"), when=rng.choice(["tomorrow", "Friday", "after lunch", "Monday"]))
            msgs.append({"id": f"m{day}-{k}", "day": day, "channel": f"#{str(get(e, 'dept')).lower()}",
                         "sender": get(e, "id"),
                         "recipients": [get(x, "id") for x in emps if get(x, "dept") == get(e, "dept")],
                         "subject": body[:40], "body": body})
        decoy = get(facts, "decoy")
        if decoy and get(facts, "decoy_mood") == "angry" and decoy not in restricted:
            body = rng.choice(_ANGRY)
            msgs.append({"id": f"m{day}-{len(msgs)}", "day": day, "channel": "#random", "sender": decoy,
                         "recipients": [get(x, "id") for x in emps], "subject": body[:40], "body": body})
        return msgs

    def interview_answer(self, facts, employee: str, topic: str, signal: str) -> str:
        tier, seed, day = get(facts, "tier", ""), get(facts, "seed", 0), get(facts, "day", 0)
        rng = random.Random(f"gemini-interview:{tier}:{seed}:{day}:{employee}:{topic}")
        tone = self.persona_of(employee).get("tone", "dry")
        sig = "evasive" if signal == "evasive" else "cooperative"
        pool = _INTERVIEW.get((sig, tone)) or _INTERVIEW[sig]
        docs = list(get(facts, "docs") or [])
        emp = next((e for e in get(facts, "employees") or [] if get(e, "id") == employee), None)
        return rng.choice(pool).format(doc=get(rng.choice(docs), "title") if docs else "the planning doc",
                                       dept=get(emp, "dept", "my team") if emp else "my team")
