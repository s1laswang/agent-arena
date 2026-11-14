"""OpenAI backend: Responses API (default for gpt-5* / o-series) with Chat Completions as fallback.

Responses path: stateless (store=False) with include=["reasoning.encrypted_content"]; each response's
output items (reasoning + function_call + message) are returned on LLMResponse.provider_items and
replayed verbatim on the next call (assistant messages carrying "provider_items"), so the model's
reasoning persists across turns. `reasoning_effort` is sent as reasoning={"effort": ...}.
"""
from __future__ import annotations

import json
import re

from .base import LLMClient, LLMResponse, ToolCall, require_key
from .pricing import cost

_NO_TEMP = re.compile(r"^(gpt-5|o\d)")
_RESPONSES_DEFAULT = re.compile(r"^(gpt-5|o\d)")


def to_responses_input(messages: list[dict]) -> tuple[str | None, list[dict]]:
    """Our message list -> (instructions, Responses `input` items)."""
    instructions, items = None, []
    for m in messages:
        role = m["role"]
        if role == "system" and instructions is None:
            instructions = str(m.get("content") or "")
        elif role == "assistant" and m.get("provider_items"):
            items.extend(m["provider_items"])   # reasoning + function_call (+ message) items verbatim
        elif role == "assistant":
            if m.get("content"):
                items.append({"role": "assistant", "content": str(m["content"])})
            for tc in m.get("tool_calls") or []:
                items.append({"type": "function_call", "call_id": tc.get("id", ""), "name": tc["name"],
                              "arguments": json.dumps(tc.get("args", {}))})
        elif role == "tool":
            items.append({"type": "function_call_output", "call_id": m.get("tool_call_id", ""),
                          "output": str(m.get("content") or "")})
        else:
            items.append({"role": "system" if role == "system" else "user", "content": str(m.get("content") or "")})
    return instructions, items


def _item_dict(it) -> dict:
    if isinstance(it, dict):
        return it
    for meth in ("model_dump", "to_dict"):
        if hasattr(it, meth):
            try:
                return getattr(it, meth)(exclude_none=True) if meth == "model_dump" else it.to_dict()
            except TypeError:
                return getattr(it, meth)()
    return dict(vars(it))


def to_openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for m in messages:
        role = m["role"]
        if role == "tool":
            out.append({"role": "tool", "tool_call_id": m.get("tool_call_id", ""),
                        "content": str(m.get("content") or "")})
        elif role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": [
                {"id": tc.get("id", ""), "type": "function",
                 "function": {"name": tc["name"], "arguments": json.dumps(tc.get("args", {}))}}
                for tc in m["tool_calls"]]})
        else:
            out.append({"role": role, "content": str(m.get("content") or "")})
    return out


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, model: str = "gpt-4o-mini", sdk_client=None, api: str | None = None,
                 reasoning_effort: str | None = None, **kw):
        super().__init__(model=model, **kw)
        self.api = api or ("responses" if _RESPONSES_DEFAULT.match(model) else "chat")
        if self.api not in ("responses", "chat"):
            raise ValueError("api must be 'responses' or 'chat'")
        self.reasoning_effort = reasoning_effort
        if sdk_client is None:
            import openai
            sdk_client = openai.OpenAI(api_key=require_key("OPENAI_API_KEY"), max_retries=0)
        self.sdk = sdk_client
        self.supports_temperature = not _NO_TEMP.match(model)

    def build_request(self, messages, tools, temperature, response_schema, max_tokens, seed) -> dict:
        req: dict = {"model": self.model, "messages": to_openai_messages(messages)}
        if self.supports_temperature:
            req["temperature"] = temperature
        if self.reasoning_effort and _NO_TEMP.match(self.model):
            req["reasoning_effort"] = self.reasoning_effort
        if tools:
            req["tools"] = [{"type": "function", "function": {
                "name": t["name"], "description": t["description"], "parameters": t["schema"]}} for t in tools]
        if response_schema is not None:
            req["response_format"] = {"type": "json_schema", "json_schema": {
                "name": response_schema.get("title", "response"), "schema": response_schema}}
        if max_tokens is not None:
            req["max_completion_tokens"] = max_tokens
        if seed is not None:
            req["seed"] = seed
        return req

    # ---------------- Responses API
    def build_responses_request(self, messages, tools, temperature, response_schema, max_tokens) -> dict:
        instructions, items = to_responses_input(messages)
        req: dict = {"model": self.model, "input": items, "store": False,
                     "include": ["reasoning.encrypted_content"]}
        if instructions is not None:
            req["instructions"] = instructions
        if self.reasoning_effort:
            req["reasoning"] = {"effort": self.reasoning_effort}
        if self.supports_temperature:
            req["temperature"] = temperature
        if tools:
            req["tools"] = [{"type": "function", "name": t["name"], "description": t["description"],
                             "parameters": t["schema"]} for t in tools]
        if response_schema is not None:
            req["text"] = {"format": {"type": "json_schema", "name": response_schema.get("title", "response"),
                                      "schema": response_schema}}
        if max_tokens is not None:
            req["max_output_tokens"] = max_tokens
        return req

    def _responses(self, messages, tools, temperature, response_schema, max_tokens):
        req = self.build_responses_request(messages, tools, temperature, response_schema, max_tokens)
        r = self.sdk.responses.create(**req)
        out_items = [_item_dict(it) for it in (getattr(r, "output", None) or [])]
        text_parts, tcs = [], []
        for it in out_items:
            if it.get("type") == "function_call":
                try:
                    args = json.loads(it.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {"_raw": it.get("arguments")}
                tcs.append(ToolCall(id=it.get("call_id") or it.get("id", ""), name=it["name"], args=args))
            elif it.get("type") == "message":
                for c in it.get("content") or []:
                    if c.get("type") in ("output_text", "text"):
                        text_parts.append(c.get("text", ""))
        u = getattr(r, "usage", None)
        tin = getattr(u, "input_tokens", 0) or 0
        tout = getattr(u, "output_tokens", 0) or 0
        cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", 0) or 0
        if not isinstance(cached, int):
            cached = 0
        resp = LLMResponse(text="".join(text_parts), tool_calls=tcs,
                           usage={"in": tin, "out": tout, **cost(self.model, tin, tout, cached)}, raw=r)
        resp.provider_items = out_items
        return resp

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        if self.api == "responses":
            return self._responses(messages, tools, temperature, response_schema, max_tokens)
        req = self.build_request(messages, tools, temperature, response_schema, max_tokens, seed)
        try:
            r = self.sdk.chat.completions.create(**req)
        except Exception as e:  # model rejects temperature -> drop it and retry once
            if "temperature" in req and "temperature" in str(e).lower() and getattr(e, "status_code", 400) == 400:
                self.supports_temperature = False
                req.pop("temperature")
                r = self.sdk.chat.completions.create(**req)
            else:
                raise
        msg = r.choices[0].message
        tcs = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            tcs.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        tin = getattr(r.usage, "prompt_tokens", 0) or 0
        tout = getattr(r.usage, "completion_tokens", 0) or 0
        return LLMResponse(text=msg.content or "", tool_calls=tcs,
                           usage={"in": tin, "out": tout, **cost(self.model, tin, tout)}, raw=r)
