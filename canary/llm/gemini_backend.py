"""Google Gemini backend (google-genai SDK)."""
from __future__ import annotations

import json
import os
import uuid

from .base import LLMClient, LLMResponse, ToolCall, require_key
from .pricing import cost

DEFAULT_MODEL = "gemini-2.5-flash"


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
            parts = [types.Part(text=str(content))] if content else []
            for tc in m.get("tool_calls") or []:
                id2name[tc.get("id")] = tc["name"]
                parts.append(types.Part(function_call=types.FunctionCall(
                    id=tc.get("id"), name=tc["name"], args=tc.get("args", {}))))
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
        elif role == "tool":
            name = m.get("name") or id2name.get(m.get("tool_call_id"), "tool")
            try:
                resp = json.loads(content) if isinstance(content, str) else content
            except (json.JSONDecodeError, TypeError):
                resp = content
            if not isinstance(resp, dict):
                resp = {"result": resp}
            part = types.Part(function_response=types.FunctionResponse(
                id=m.get("tool_call_id"), name=name, response=resp))
            # consecutive tool results go in one user turn
            if contents and contents[-1].role == "user" and contents[-1].parts and contents[-1].parts[-1].function_response:
                contents[-1].parts.append(part)
            else:
                contents.append(types.Content(role="user", parts=[part]))
    return ("\n\n".join(system) or None), contents


class GeminiClient(LLMClient):
    provider = "gemini"

    def __init__(self, model: str | None = None, sdk_client=None, **kw):
        super().__init__(model=model or os.environ.get("CANARY_GEMINI_MODEL", DEFAULT_MODEL), **kw)
        if sdk_client is None:
            from google import genai
            sdk_client = genai.Client(api_key=require_key("GEMINI_API_KEY"))
        self.sdk = sdk_client
        self.thinking_budget = int(os.environ.get("CANARY_GEMINI_THINKING", "1024"))

    def build_request(self, messages, tools, temperature, response_schema, max_tokens, seed) -> dict:
        from google.genai import types
        system, contents = to_gemini_contents(messages)
        cfg: dict = {"temperature": temperature}
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
        if self.thinking_budget >= 0 and "2.5" in self.model:
            cfg["thinking_config"] = types.ThinkingConfig(thinking_budget=self.thinking_budget)
        return {"model": self.model, "contents": contents, "config": types.GenerateContentConfig(**cfg)}

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        req = self.build_request(messages, tools, temperature, response_schema, max_tokens, seed)
        r = self.sdk.models.generate_content(**req)
        texts, tcs = [], []
        cands = getattr(r, "candidates", None) or []
        parts = (getattr(cands[0].content, "parts", None) or []) if cands and cands[0].content else []
        for p in parts:
            fc = getattr(p, "function_call", None)
            if fc is not None:
                tcs.append(ToolCall(id=getattr(fc, "id", None) or f"call_{uuid.uuid4().hex[:8]}",
                                    name=fc.name, args=dict(fc.args or {})))
            elif getattr(p, "text", None) and not getattr(p, "thought", False):
                texts.append(p.text)
        um = getattr(r, "usage_metadata", None)
        tin = (getattr(um, "prompt_token_count", 0) or 0) if um else 0
        tout = ((getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0)) if um else 0
        return LLMResponse(text="".join(texts), tool_calls=tcs,
                           usage={"in": tin, "out": tout, **cost(self.model, tin, tout)}, raw=r)
