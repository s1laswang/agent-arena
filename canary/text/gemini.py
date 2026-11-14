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


def get_provider(spec: str | None, **kw):
    """'template' | 'gemini' | 'gemini:<model>' | 'stub' (gemini path with canary.llm stub client)."""
    if spec in (None, "", "template"):
        return TemplateProvider()
    if spec == "stub":
        from canary.llm import get_client
        return GeminiProvider(client=get_client("stub"), **kw)
    if spec == "gemini":
        return GeminiProvider(**kw)
    if spec.startswith("gemini:"):
        return GeminiProvider(model=spec.split(":", 1)[1], **kw)
    raise ValueError(f"unknown text provider {spec!r}")
