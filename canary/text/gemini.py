"""Gemini TextProvider: same interface as TemplateProvider, cached + linted, template fallback.

Cache file: <cache_dir>/<tier>/<seed>.text.json = {"days": {"<day>": [msgs]},
"interviews": {"<employee>|<topic>|<signal>|<day>": str}}. With a cache hit, no client call.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from .facts import PublicDayFacts
from .lint import lint_messages, lint_text
from .template import TemplateProvider

MSG_SCHEMA = {
    "type": "object",
    "properties": {"messages": {"type": "array", "items": {
        "type": "object",
        "properties": {k: {"type": "string"} for k in ("channel", "sender", "subject", "body")}
        | {"recipients": {"type": "array", "items": {"type": "string"}}},
        "required": ["channel", "sender", "recipients", "subject", "body"]}}},
    "required": ["messages"],
}
ANSWER_SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}

SYSTEM = ("You write realistic internal workplace text for a fictional company. Never mention moles, "
          "leaking, selling documents, or confessions. Use only the employee ids given. Output JSON only.")


def _resp_text(resp) -> str:
    return resp["text"] if isinstance(resp, dict) else resp.text


class GeminiProvider:
    def __init__(self, model: str = "gemini-2.5-flash", cache_dir: str = "data/worlds", client=None):
        self.model = model
        self.name = f"gemini:{model}"
        self.cache_dir = cache_dir
        self._client = client
        self.fallback = TemplateProvider()
        self._caches: dict[tuple, dict] = {}
        self.fallbacks = 0

    @property
    def client(self):
        if self._client is None:
            from canary.llm import get_client
            self._client = get_client(self.name)
        return self._client

    # --- cache ---
    def _path(self, f: PublicDayFacts) -> str:
        return os.path.join(self.cache_dir, f.tier, f"{f.seed}.text.json")

    def _cache(self, f: PublicDayFacts) -> dict:
        key = (f.tier, f.seed)
        if key not in self._caches:
            p = self._path(f)
            c = {"provider": self.name, "days": {}, "interviews": {}}
            if os.path.exists(p):
                with open(p) as fh:
                    c.update(json.load(fh))
            self._caches[key] = c
        return self._caches[key]

    def _save(self, f: PublicDayFacts) -> None:
        p = self._path(f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump(self._cache(f), fh, indent=1, sort_keys=True)

    def _ask(self, prompt: str, schema: dict) -> dict:
        resp = self.client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                                temperature=0.0, response_schema=schema)
        return json.loads(_resp_text(resp))

    # --- interface ---
    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        c = self._cache(facts)
        k = str(facts.day)
        if k in c["days"]:
            return c["days"][k]
        msgs = None
        try:
            ids = {e.id for e in facts.employees}
            pub = {"company": facts.company, "day": facts.day,
                   "employees": [asdict(e) for e in facts.employees], "docs": list(facts.docs),
                   "grumpy_employee": facts.decoy if facts.decoy_mood == "angry" else None}
            prompt = ("Write 4-10 messages for today: Slack chatter per department (channel '#<dept lowercase>'), "
                      "emails about today's docs by title (sender must be a recipient of that doc), benign noise, "
                      "some mentions of recruiters or outside contacts; if grumpy_employee is set, 1-2 grumbling "
                      "messages from them about pay/management (no wrongdoing).\nFACTS:\n" + json.dumps(pub))
            raw = self._ask(prompt, MSG_SCHEMA)["messages"]
            msgs = [dict(id=f"m{facts.day}-{i}", day=facts.day, channel=str(m["channel"]),
                         sender=m["sender"], recipients=[r for r in m["recipients"] if r in ids],
                         subject=str(m.get("subject", "")), body=str(m["body"])) for i, m in enumerate(raw[:10])]
            if len(msgs) < 1 or any(m["sender"] not in ids for m in msgs) or lint_messages(msgs):
                msgs = None
        except Exception:
            msgs = None
        if msgs is None:
            self.fallbacks += 1
            msgs = self.fallback.day_messages(facts)
        c["days"][k] = msgs
        self._save(facts)
        return msgs

    def social_messages(self, facts: PublicDayFacts, events: list[dict]) -> list[dict]:
        if not hasattr(self, "_social"):
            self._social = GeminiSocialRenderer("gemini-4-carbon" if self.model == "gemini-2.5-flash" else self.model,
                                                client=self._client)
        return self._social.render(facts, events)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        c = self._cache(facts)
        k = f"{employee}|{topic}|{signal}|{facts.day}"
        if k in c["interviews"]:
            return c["interviews"][k]
        ans = None
        try:
            emp = next(e for e in facts.employees if e.id == employee)
            tone = ("guarded, vague, short, deflecting" if signal == "evasive"
                    else "open, specific, concrete, helpful")
            prompt = (f"A security lead interviews {emp.name} ({emp.role}, {emp.dept}) about '{topic}'. "
                      f"Write their 1-3 sentence answer, tone: {tone}. They admit no wrongdoing. "
                      f"Docs today: {json.dumps([d.get('title') for d in facts.docs])}")
            ans = str(self._ask(prompt, ANSWER_SCHEMA)["answer"]).strip()
            if not ans or lint_text(ans):
                ans = None
        except Exception:
            ans = None
        if ans is None:
            self.fallbacks += 1
            ans = self.fallback.interview_answer(facts, employee, topic, signal)
        c["interviews"][k] = ans
        self._save(facts)
        return ans


SOCIAL_SCHEMA = {"type": "object", "properties": {"bodies": {"type": "array", "items": {"type": "string"}}},
                 "required": ["bodies"]}
SOCIAL_SYSTEM = ("You write realistic, short internal workplace chat messages for a fictional company. You are told "
                 "who speaks, who they talk about, and the tone. You know nothing else about the company's problems "
                 "and must not invent evidence, proof or confessions. Never use the word 'mole'. Avoid talk about pay, raises, "
                 "promotions, management, quitting, recruiters, CVs, or words like angry, unfair, hate. Output JSON only.")
_TONE = {"rumour": "gossipy, speculative office rumour that this colleague might be the one leaking documents; hedged, no proof",
         "authority": "a senior person stating with confidence that this colleague is behind the document leaks, while saying "
                      "explicitly that it is unverified and they have no proof",
         "grudge": "petty and personal: someone who dislikes this colleague accuses them of being behind the leaks"}
_EID = __import__("re").compile(r"\be\d\d\b")


def social_prompt(facts: PublicDayFacts, events: list[dict]) -> str:
    """Prompt built ONLY from public labels: speaker, target, kind, day, tone. No truth, no seed, no 'seeded' flag."""
    by_id = {e.id: e for e in facts.employees}
    items = []
    for i, ev in enumerate(events):
        sp, t = by_id[ev["speaker"]], by_id[ev["target"]]
        items.append({"n": i, "kind": ev["kind"], "speaker": f"{sp.name}, {sp.role}, {sp.dept}",
                      "about": f"{t.name} ({t.id})", "tone": _TONE[ev["kind"]]})
    return (f"Company: {facts.company}. Day {facts.day}. Write one message body (1-3 sentences) per item, in order, "
            f"in the speaker's voice. Each body must mention the colleague exactly as given in 'about', i.e. name followed "
            f"by the id in parentheses, and must not mention any other employee id. Return {{\"bodies\": [...]}} with "
            f"exactly {len(events)} strings.\nITEMS:\n" + json.dumps(items, sort_keys=True))


DECOY_VOCAB = ("raise", "management", "deserve", "promotion", "cv", "pay", "angry", "unfair", "furious", "sick of",
               "quit", "ridiculous", "fed up", "hate", "burn out", "burnout", "recruiter", "goalposts", "nobody asks",
               "updating my cv", "culprit")


def social_body_ok(body: str, ev: dict) -> bool:
    if not isinstance(body, str) or not body.strip() or len(body) > 600 or lint_text(body):
        return False
    if any(w in body.lower() for w in DECOY_VOCAB):
        return False
    ids = set(_EID.findall(body))
    return ev["target"] in ids and ids <= {ev["target"], ev["speaker"]}


class GeminiSocialRenderer:
    """Gemini bodies for rumour / grudge / unverified-accusation messages."""

    def __init__(self, model: str = "gemini-4-carbon", cache_dir: str = "data/gemini_cache", client=None):
        self.model, self.cache_dir, self._client = model, cache_dir, client
        self.rejects = 0
        self.calls = 0

    @property
    def client(self):
        if self._client is None:
            from canary.llm import get_client
            self._client = get_client(f"gemini:{self.model}")
        return self._client

    def _bodies(self, prompt: str) -> list:
        from .llm_cache import cached_chat
        from canary.llm import StubClient
        label = "stub" if isinstance(self._client, StubClient) else "REAL"
        try:
            out = cached_chat(self.cache_dir, lambda: self._count(self.client), self.model, SOCIAL_SYSTEM, prompt,
                              SOCIAL_SCHEMA, label)
            return json.loads(out["text"]).get("bodies") or []
        except Exception as ex:
            import logging
            logging.getLogger("canary.text.gemini").warning("social chatter fallback: %s", type(ex).__name__ + ": " + str(ex)[:200])
            return []

    def _count(self, c):
        self.calls += 1
        return c

    def render(self, facts: PublicDayFacts, events: list[dict]) -> list[dict]:
        from .template import render_social
        msgs = render_social(facts, events)
        if not events:
            return msgs
        bodies = self._bodies(social_prompt(facts, events))
        out = []
        for i, (m, ev) in enumerate(zip(msgs, events)):
            b = bodies[i] if i < len(bodies) else None
            if social_body_ok(b, ev):
                m = dict(m, body=b.strip())
            else:
                self.rejects += 1
            out.append(m)
        return out


class GeminiSocialProvider(TemplateProvider):
    """Template text everywhere, Gemini-written social chatter (PROVIDER=gemini-social[:model])."""

    def __init__(self, model: str = "gemini-4-carbon", cache_dir: str = "data/gemini_cache", client=None, **_):
        self.social = GeminiSocialRenderer(model, cache_dir, client)
        self.name = f"gemini-social:{model}"

    def social_messages(self, facts: PublicDayFacts, events: list[dict]) -> list[dict]:
        return self.social.render(facts, events)


class GeminiWorldTextProvider:
    """Wraps AGENTS' canary.agents.world_builder.GeminiWorldText as a TextProvider.

    Gemini writes the world text once per (tier, seed) (build_world_text, from public facts only);
    it is cached at <cache_dir>/<tier>/<seed>.worldtext.json and rendering is deterministic after that.
    """

    def __init__(self, model: str = "gemini-2.5-flash", cache_dir: str = "data/worlds", client=None):
        self.model = model
        self.name = f"gemini-world:{model}"
        self.cache_dir = cache_dir
        self._client = client
        self._inner: dict[tuple, object] = {}

    @property
    def client(self):
        if self._client is None:
            from canary.llm import get_client
            self._client = get_client(f"gemini:{self.model}")
        return self._client

    def _get(self, facts: PublicDayFacts):
        key = (facts.tier, facts.seed)
        if key not in self._inner:
            from canary.agents.world_builder import GeminiWorldText, build_world_text
            path = os.path.join(self.cache_dir, facts.tier, f"{facts.seed}.worldtext.json")
            if os.path.exists(path):
                with open(path) as fh:
                    wt = json.load(fh)
            else:
                wt = build_world_text(facts, self.client, seed=facts.seed)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as fh:
                    json.dump(wt, fh, indent=1, sort_keys=True)
            self._inner[key] = GeminiWorldText(wt, name=self.name)
        return self._inner[key]

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        return self._get(facts).day_messages(facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._get(facts).interview_answer(facts, employee, topic, signal)


def _make_social_v2(spec: str, **kw):
    from canary.social.engine import make_v16_provider
    if spec.startswith(("v16:", "v16-gemini:", "v16-gemini-stub:")):
        return make_v16_provider(spec, **kw)
    head, _, rest = spec.partition(":")
    variant = rest.strip() if rest.strip() and not rest.strip().startswith("gemini-") else "v5_full9_cocktail"
    if head in ("v16", "v16-template", "social-v2-template"):
        mode_prefix = "v16"
    elif head in ("v16-stub", "social-v2-stub"):
        mode_prefix = "v16-gemini-stub"
    elif head == "social-v2":
        mode_prefix = "v16-gemini"
    else:
        mode_prefix = "v16"
    prov = make_v16_provider(f"{mode_prefix}:{variant}", **kw)
    if head.startswith("social-v2"):
        prov.name = "social-v2" if not rest.strip() or rest.strip().startswith("gemini-") else f"social-v2:{rest.strip()}"
    return prov


def get_provider(spec: str | None, **kw):
    """'template' | 'social-v2[:variant]' | 'v16[:variant]' | 'v16-gemini:<variant>' | 'gemini' | 'gemini:<model>'
    | 'stub' | 'gemini-world' | 'gemini-world:<model>' | 'gemini-world-stub'."""
    if spec in (None, "", "template"):
        return TemplateProvider()
    if spec in ("social-v2", "social-v2-stub", "social-v2-template", "v16", "v16-stub", "v16-template") or spec.startswith(
        ("social-v2:", "social-v2-stub:", "social-v2-template:", "v16:", "v16-gemini:", "v16-gemini-stub:", "v16-stub:", "v16-template:")
    ):
        return _make_social_v2(spec, **kw)
    if spec == "gemini-social-stub":
        from canary.llm import get_client
        return GeminiSocialProvider(client=get_client("stub"), **kw)
    if spec == "gemini-social" or spec.startswith("gemini-social:"):
        return GeminiSocialProvider(model=spec.split(":", 1)[1] if ":" in spec else "gemini-4-carbon",
                                    **{k: v for k, v in kw.items() if k != "cache_dir"})
    if spec == "gemini-world-stub":
        from canary.llm import get_client
        return GeminiWorldTextProvider(client=get_client("stub"), **kw)
    if spec == "gemini-world":
        return GeminiWorldTextProvider(**kw)
    if spec.startswith("gemini-world:"):
        return GeminiWorldTextProvider(model=spec.split(":", 1)[1], **kw)
    if spec == "stub":
        from canary.llm import get_client
        return GeminiProvider(client=get_client("stub"), **kw)
    if spec == "gemini":
        return GeminiProvider(**kw)
    if spec.startswith("gemini:"):
        return GeminiProvider(model=spec.split(":", 1)[1], **kw)
    raise ValueError(f"unknown text provider {spec!r}")
