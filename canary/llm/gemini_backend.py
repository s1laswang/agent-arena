"""Google Gemini backend (google-genai SDK, generateContent with function calling).

Gemini 3+/4 models (thinking models with thought signatures):
- each model turn is returned on LLMResponse.provider_items as the raw `Content` (JSON form, thought
  signatures base64) and replayed verbatim on the next call (assistant messages carrying "provider_items"),
  so the model's reasoning state persists across function-calling turns (stateless multi-turn: the Gemini
  docs require resending the model's content exactly as received);
- temperature is NOT sent (Google's guidance for Gemini 3+: keep the default 1.0; lower values can cause
  looping), mirroring how OpenAIClient drops temperature for gpt-5*;
- thinking: `thinking_level` from CANARY_GEMINI_THINKING_LEVEL (low|medium|high|xhigh); unset = the model's
  default (gemini-4-carbon: medium, per the Gemini API thinking docs), which is also what OpenCode 1.18 sends
  for gemini-4 models (includeThoughts only, no level). include_thoughts=True: thought summaries are kept on
  LLMResponse.thoughts / in the replayed content (they never reach the env).
Gemini 2.5 models keep the legacy thinking_budget (CANARY_GEMINI_THINKING) and the requested temperature.
Function calls without an API id get a local id "gen_<hex>"; such ids are never sent back to the API.
"""
from __future__ import annotations

import json
import os
import re
import uuid

from .base import LLMClient, LLMResponse, ToolCall, require_key
from .pricing import cost

# Strongest Gemini model on the API (checked 2026-11-14): "Gemini 4 Carbon ... Our strongest reasoning model"
# (aistudio.google.com/docs/models). gemini-2.5-flash now returns 404 "no longer available to new users".
DEFAULT_MODEL = "gemini-4-carbon"
_SIGNATURE_MODEL = re.compile(r"^gemini-(?:[3-9]|\d\d)")   # gemini-3*, gemini-3.8-flash, gemini-4-*, ...
THINKING_LEVELS = ("minimal", "low", "medium", "high", "xhigh")
GEN_PREFIX = "gen_"


def is_signature_model(model: str) -> bool:
    return bool(_SIGNATURE_MODEL.match(model or ""))


def _api_id(cid):
    return None if (not cid or str(cid).startswith(GEN_PREFIX)) else cid


def to_gemini_contents(messages: list[dict]):
    """Return (system_instruction | None, list[types.Content])."""
    from google.genai import types
    system, contents, id2name = [], [], {}
    for m in messages:
        role, content = m["role"], m.get("content")
        if role == "system":
            system.append(str(content or ""))
        elif role == "user":
            contents.append(types.Content(role="user", parts=[types.Part(text=str(content or ""))]))
        elif role == "assistant":
            for tc in m.get("tool_calls") or []:
                id2name[tc.get("id")] = tc["name"]
            items = m.get("provider_items")
            if items:  # the model's own Content, verbatim (thought signatures included)
                c = items[0] if isinstance(items, list) else items
                contents.append(c if isinstance(c, types.Content) else types.Content.model_validate(c))
                continue
            parts = [types.Part(text=str(content))] if content else []
            for tc in m.get("tool_calls") or []:
                parts.append(types.Part(function_call=types.FunctionCall(
                    id=_api_id(tc.get("id")), name=tc["name"], args=tc.get("args", {}))))
            if parts:  # an empty model turn (no text, no call) is dropped rather than sent as an empty part
                contents.append(types.Content(role="model", parts=parts))
        elif role == "tool":
            name = m.get("name") or id2name.get(m.get("tool_call_id"), "tool")
            try:
                resp = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                resp = content
            if not isinstance(resp, dict):
                resp = {"result": resp}
            part = types.Part(function_response=types.FunctionResponse(
                id=_api_id(m.get("tool_call_id")), name=name, response=resp))
            # consecutive tool results go in one user turn
            if contents and contents[-1].role == "user" and contents[-1].parts and contents[-1].parts[-1].function_response:
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
    return ("\n\n".join(system) or None), contents


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, model: str | None = None, sdk_client=None, thinking_level: str | None = None, **kw):
        super().__init__(model=model or os.environ.get("CANARY_GEMINI_MODEL") or DEFAULT_MODEL, **kw)
        if sdk_client is None:
            from google import genai
            sdk_client = genai.Client(api_key=require_key("GEMINI_API_KEY"))
        self.sdk = sdk_client
        self.thinking_budget = int(os.environ.get("CANARY_GEMINI_THINKING", "1024"))
        level = thinking_level or os.environ.get("CANARY_GEMINI_THINKING_LEVEL") or None
        if level is not None and level.lower() not in THINKING_LEVELS:
            raise ValueError(f"thinking_level must be one of {THINKING_LEVELS}")
        self.thinking_level = level.lower() if level else None
        self.signature_model = is_signature_model(self.model)
        self.supports_temperature = not self.signature_model
        self.finish_reasons: dict[str, int] = {}

    def settings(self) -> dict:
        """What this client sends, for meta.json."""
        if self.signature_model:
            return {"thinking_level": self.thinking_level or "model default (not sent; gemini-4-carbon: medium)",
                    "include_thoughts": True, "temperature": "not sent (API default 1.0)",
                    "thought_signature_replay": True, "api": "generateContent"}
        return {"thinking_budget": self.thinking_budget if "2.5" in self.model else None,
                "temperature": "as requested", "thought_signature_replay": False, "api": "generateContent"}

    def build_request(self, messages, tools, temperature, response_schema, max_tokens, seed) -> dict:
        from google.genai import types
        system, contents = to_gemini_contents(messages)
        cfg: dict = {}
        if self.supports_temperature:
            cfg["temperature"] = temperature
        if system:
            cfg["system_instruction"] = system
        if tools:
            cfg["tools"] = [types.Tool(function_declarations=[types.FunctionDeclaration(
                name=t["name"], description=t["description"], parameters_json_schema=t["schema"])
                for t in tools])]
            cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        if response_schema is not None:
            cfg["response_mime_type"] = "application/json"
            cfg["response_json_schema"] = response_schema
        if max_tokens is not None:
            cfg["max_output_tokens"] = max_tokens
        if seed is not None:
            cfg["seed"] = seed
        if self.signature_model:
            tc: dict = {"include_thoughts": True}
            if self.thinking_level:
                tc["thinking_level"] = self.thinking_level.upper()
            cfg["thinking_config"] = types.ThinkingConfig(**tc)
        elif self.thinking_budget >= 0 and "2.5" in self.model:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=self.thinking_budget)
        return {"model": self.model, "contents": contents, "config": types.GenerateContentConfig(**cfg)}

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        req = self.build_request(messages, tools, temperature, response_schema, max_tokens, seed)
        r = self.sdk.models.generate_content(**req)
        texts, thoughts, tcs = [], [], []
        cands = getattr(r, "candidates", None) or []
        content = cands[0].content if cands and getattr(cands[0], "content", None) else None
        fr = str(getattr(cands[0], "finish_reason", None)) if cands else "no_candidates"
        self.finish_reasons[fr] = self.finish_reasons.get(fr, 0) + 1
        parts = (getattr(content, "parts", None) or []) if content is not None else []
        for p in parts:
            fc = getattr(p, "function_call", None)
            if fc is not None:
                tcs.append(ToolCall(id=getattr(fc, "id", None) or f"{GEN_PREFIX}{uuid.uuid4().hex[:10]}",
                                    name=fc.name, args=dict(fc.args or {})))
            elif getattr(p, "text", None):
                (thoughts if getattr(p, "thought", False) else texts).append(p.text)
        um = getattr(r, "usage_metadata", None)

        def _n(attr):
            v = getattr(um, attr, 0) if um is not None else 0
            return v if isinstance(v, int) else 0
        tin, cached = _n("prompt_token_count"), _n("cached_content_token_count")
        tout = _n("candidates_token_count") + _n("thoughts_token_count")
        resp = LLMResponse(text="".join(texts), tool_calls=tcs,
                           usage={"in": tin, "out": tout, **cost(self.model, tin, tout, cached)}, raw=r)
        if self.signature_model and parts and hasattr(content, "model_dump"):
            resp.provider_items = [content.model_dump(mode="json", exclude_none=True)]
        if thoughts:
            resp.thoughts = "\n".join(thoughts)
        return resp
