"""Gemini TextProvider: same interface as TemplateProvider, cached + linted, template fallback.

Cache file: <cache_dir>/<tier>/<seed>.text.json = {"model_id": str, "usage": {...},
"days": {"<day>": [msgs]}, "interviews": {"<employee>|<topic>|<signal>|<day>": str}}.
With a cache hit, no client call.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from types import SimpleNamespace

from .facts import PublicDayFacts
from .lint import lint_messages, lint_text
from .template import TemplateProvider

DEFAULT_MODEL = "gemini-4-carbon"

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


def _empty_usage() -> dict:
    return {"in": 0, "out": 0, "thinking": 0, "cached": 0, "calls": 0, "cost_usd": 0.0}


def _resp_text(resp) -> str:
    if isinstance(resp, dict):
        return str(resp.get("text") or "")
    return str(getattr(resp, "text", "") or "")


def _unfence_json(text: str) -> str:
    s = (text or "").strip()
    try:
        json.loads(s)
        return s
    except json.JSONDecodeError:
        pass
    if s.startswith("```"):
        inner = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s)
        if inner.endswith("```"):
            inner = inner[:-3]
        cand = inner.strip()
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            pass
    m = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*)\s*```", s, re.DOTALL)
    if m:
        cand = m.group(1).strip()
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            pass
    for m_iter in re.finditer(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```", s, re.DOTALL):
        cand = m_iter.group(1).strip()
        try:
            json.loads(cand)
            return cand
        except json.JSONDecodeError:
            pass
    return s


def _loads_json(text: str):
    return json.loads(_unfence_json(text))


def _resp_usage(resp) -> dict:
    u = (resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)) or {}
    if not isinstance(u, dict):
        u = {}
    raw = resp.get("raw") if isinstance(resp, dict) else getattr(resp, "raw", None)
    um = getattr(raw, "usage_metadata", None) if raw is not None else None

    def _um_int(attr: str) -> int:
        v = getattr(um, attr, 0) if um is not None else 0
        return v if isinstance(v, int) and not isinstance(v, bool) else 0

    def _u_int(*keys: str) -> int:
        for k in keys:
            v = u.get(k)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                return int(v)
        return 0

    tin = _u_int("in", "input_tokens", "prompt_tokens", "prompt_token_count") or _um_int("prompt_token_count")
    tout = _u_int("out", "output_tokens", "out_tokens", "completion_tokens", "candidates_token_count")
    thinking = _u_int("thinking", "thinking_tokens", "thoughts_token_count") or _um_int("thoughts_token_count")
    if not tout and um is not None:
        tout = _um_int("candidates_token_count") + thinking
    cached = _u_int("cached", "cached_in", "cached_tokens", "cached_content_token_count") or _um_int("cached_content_token_count")
    calls = _u_int("calls") or 1
    raw_cost = u.get("cost_usd_est") if "cost_usd_est" in u else u.get("cost_usd", 0.0)
    usd = float(raw_cost) if isinstance(raw_cost, (int, float)) and not isinstance(raw_cost, bool) else 0.0
    return {
        "in": tin,
        "out": tout,
        "thinking": thinking,
        "cached": cached,
        "calls": calls,
        "cost_usd": round(usd, 6),
    }


def _merge_usage(base: dict | None, delta: dict | None = None) -> dict:
    out = _empty_usage()
    for src in (base, delta):
        if not isinstance(src, dict):
            continue
        for k in ("in", "out", "thinking", "cached", "calls"):
            v = src.get(k, 0)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] += int(v)
        v_cost = src.get("cost_usd", 0.0)
        if isinstance(v_cost, (int, float)) and not isinstance(v_cost, bool):
            out["cost_usd"] = round(out["cost_usd"] + float(v_cost), 6)
    return out


class _WorldClientAdapter:
    def __init__(self, inner):
        self.inner = inner
        self.usage = _empty_usage()

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None, **kw):
        if kw:
            resp = self.inner.chat(messages, tools=tools, temperature=temperature, response_schema=response_schema, **kw)
        else:
            resp = self.inner.chat(messages, tools=tools, temperature=temperature, response_schema=response_schema)
        self.usage = _merge_usage(self.usage, _resp_usage(resp))
        clean_text = _unfence_json(_resp_text(resp))
        if isinstance(resp, dict):
            return {**resp, "text": clean_text}
        return SimpleNamespace(
            text=clean_text,
            tool_calls=getattr(resp, "tool_calls", []),
            usage=getattr(resp, "usage", {}),
            raw=getattr(resp, "raw", None),
        )


class GeminiProvider:
    def __init__(self, model: str = DEFAULT_MODEL, cache_dir: str = "data/worlds", client=None):
        self.model = model or DEFAULT_MODEL
        self.name = f"gemini:{self.model}"
        self.cache_dir = cache_dir
        self._client = client
        self.fallback = TemplateProvider()
        self._caches: dict[tuple, dict] = {}
        self.fallbacks = 0
        self.usage = _empty_usage()

    @property
    def client(self):
        if self._client is None:
            from canary.llm import get_client
            self._client = get_client(self.name)
        return self._client

    def _path(self, f: PublicDayFacts) -> str:
        return os.path.join(self.cache_dir, f.tier, f"{f.seed}.text.json")

    def _cache(self, f: PublicDayFacts) -> dict:
        key = (f.tier, f.seed)
        if key not in self._caches:
            p = self._path(f)
            c = {
                "provider": self.name,
                "model_id": self.model,
                "usage": _empty_usage(),
                "days": {},
                "interviews": {},
            }
            if os.path.exists(p):
                with open(p) as fh:
                    loaded = json.load(fh)
                c.update(loaded)
                c["model_id"] = loaded.get("model_id") or self.model
                c["usage"] = _merge_usage(loaded.get("usage"))
            self._caches[key] = c
        return self._caches[key]

    def _save(self, f: PublicDayFacts) -> None:
        p = self._path(f)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as fh:
            json.dump(self._cache(f), fh, indent=1, sort_keys=True)

    def _ask(self, prompt: str, schema: dict, facts: PublicDayFacts | None = None) -> dict:
        resp = self.client.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                                temperature=0.0, response_schema=schema)
        delta = _resp_usage(resp)
        self.usage = _merge_usage(self.usage, delta)
        if facts is not None:
            c = self._cache(facts)
            c["usage"] = _merge_usage(c.get("usage"), delta)
        data = _loads_json(_resp_text(resp))
        if not isinstance(data, dict):
            raise ValueError("expected JSON object")
        return data

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
            raw = self._ask(prompt, MSG_SCHEMA, facts)["messages"]
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
            ans = str(self._ask(prompt, ANSWER_SCHEMA, facts)["answer"]).strip()
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


class GeminiWorldTextProvider:
    """Wraps AGENTS' canary.agents.world_builder.GeminiWorldText as a TextProvider.

    Gemini writes the world text once per (tier, seed) (build_world_text, from public facts only);
    it is cached at <cache_dir>/<tier>/<seed>.worldtext.json and rendering is deterministic after that.
    """

    def __init__(self, model: str = DEFAULT_MODEL, cache_dir: str = "data/worlds", client=None):
        self.model = model or DEFAULT_MODEL
        self.name = f"gemini-world:{self.model}"
        self.cache_dir = cache_dir
        self._client = client
        self._inner: dict[tuple, object] = {}
        self.usage = _empty_usage()

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
                adapter = _WorldClientAdapter(self.client)
                wt = build_world_text(facts, adapter, seed=facts.seed)
                self.usage = _merge_usage(self.usage, adapter.usage)
                wt["provider"] = self.name
                wt["model_id"] = self.model
                wt["usage"] = adapter.usage
                if isinstance(wt.get("meta"), dict):
                    wt["meta"]["model_id"] = self.model
                    wt["meta"]["usage"] = dict(adapter.usage)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w") as fh:
                    json.dump(wt, fh, indent=1, sort_keys=True)
            self._inner[key] = GeminiWorldText(wt, name=self.name)
        return self._inner[key]

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        return self._get(facts).day_messages(facts)

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        return self._get(facts).interview_answer(facts, employee, topic, signal)


def get_provider(spec: str | None, **kw):
    """'template' | 'gemini' | 'gemini:<model>' | 'stub' (gemini path with canary.llm stub client)
    | 'gemini-world' | 'gemini-world:<model>' | 'gemini-world-stub' (AGENTS' GeminiWorldText)."""
    if spec in (None, "", "template"):
        return TemplateProvider()
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
