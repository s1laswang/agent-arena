"""Deterministic offline backend with scripted responses."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .base import LLMClient, LLMError, LLMResponse, ToolCall

SCRIPTS: dict[str, list[dict]] = {}


def register_script(name: str, script: list[dict]) -> None:
    SCRIPTS[name] = list(script)


def schema_example(schema: dict | None) -> Any:
    """Minimal valid, deterministic instance of a JSON schema."""
    s = schema or {}
    if "enum" in s:
        return s["enum"][0]
    if "const" in s:
        return s["const"]
    for k in ("anyOf", "oneOf", "allOf"):
        if s.get(k):
            return schema_example(s[k][0])
    t = s.get("type", "object" if "properties" in s else "string")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if t == "object":
        props = s.get("properties", {})
        return {k: schema_example(v) for k, v in props.items()}
    if t == "array":
        n = s.get("minItems", 0)
        return [schema_example(s.get("items", {})) for _ in range(n)]
    if t == "integer":
        return int(s.get("minimum", 0))
    if t == "number":
        return float(s.get("minimum", 0.0))
    if t == "boolean":
        return False
    if t == "null":
        return None
    return "x" * int(s.get("minLength", 0)) if s.get("minLength") else "stub"


class StubClient(LLMClient):
    provider = "stub"

    def __init__(self, script: list[dict] | str | None = None, **kw):
        super().__init__(model=kw.pop("model", ""), **kw)
        if isinstance(script, str):
            if script not in SCRIPTS:
                raise LLMError(f"unknown stub script {script!r}; registered: {sorted(SCRIPTS)}")
            self.model = script
            script = SCRIPTS[script]
        self.script: list[dict] = list(script or [])
        self.calls: list[dict] = []

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools,
                           "temperature": temperature, "response_schema": response_schema,
                           "max_tokens": max_tokens, "seed": seed})
        n = len(self.calls)
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, BaseException):
                raise item
            tcs = [ToolCall(id=tc.get("id", f"call_{n}_{i}"), name=tc["name"], args=dict(tc.get("args", {})))
                   for i, tc in enumerate(item.get("tool_calls", []))]
            text = item.get("text", "")
            if "json" in item:
                text = json.dumps(item["json"])
        elif response_schema is not None:
            text, tcs = json.dumps(schema_example(response_schema)), []
        else:
            last = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"), "")
            h = hashlib.sha256(str(last).encode()).hexdigest()[:8]
            text, tcs = f"stub reply {h}", []
        tin = sum(len(str(m.get("content") or "")) for m in messages) // 4
        return LLMResponse(text=text, tool_calls=tcs,
                           usage={"in": tin, "out": len(text) // 4, "cost_usd": 0.0}, raw=None)
