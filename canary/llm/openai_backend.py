"""OpenAI Chat Completions backend."""
from __future__ import annotations

import json
import re

from .base import LLMClient, LLMResponse, ToolCall, require_key
from .pricing import cost

_NO_TEMP = re.compile(r"^(gpt-5|o\d)")


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

    def __init__(self, model: str = "gpt-4o-mini", sdk_client=None, **kw):
        super().__init__(model=model, **kw)
        if sdk_client is None:
            import openai
            sdk_client = openai.OpenAI(api_key=require_key("OPENAI_API_KEY"), max_retries=0)
        self.sdk = sdk_client
        self.supports_temperature = not _NO_TEMP.match(model)

    def build_request(self, messages, tools, temperature, response_schema, max_tokens, seed) -> dict:
        req: dict = {"model": self.model, "messages": to_openai_messages(messages)}
        if self.supports_temperature:
            req["temperature"] = temperature
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

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
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
