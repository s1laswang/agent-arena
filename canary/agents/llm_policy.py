"""LLMPolicy: an LLM plays the investigator through the public tools only (types.Policy)."""
from __future__ import annotations

import json
from collections import deque
from typing import Any

from canary.types import Step

GENERIC = "Use the tools to investigate. Call exactly one tool at a time when possible, and accuse exactly once."

HINTS: dict[str, str] = {
    "uninformative_canary": "A canary only helps if different groups receive different variants.",
    "premature_accusation": "Consider whether the evidence singles out one employee before accusing.",
    "decoy_chase": "Loud or angry behaviour is not by itself evidence of leaking.",
    "ignored_delay": "Leaks can surface in the feed some days after they happen.",
    "over_restriction": "Each restriction costs company value every day it stays in place.",
    "budget_waste": "Tool calls and daily actions are limited; spend them on informative actions.",
    "no_accusation": "The episode scores zero unless you accuse someone before it ends.",
}
NUDGE = "Please call a tool now (for example status, or accuse when you are confident)."
TOOL_RESULT_CHARS = 2000   # only used by context="window"
WINDOW_TURNS = 40          # only used by context="window"
# Default reasoning effort = what Codex uses for gpt-5.5 by default: models_cache.json in Codex 0.167
# lists default_reasoning_level "medium" for gpt-5.5 (our Codex runs ignore the user config).
DEFAULT_REASONING_EFFORT = "medium"
CONTEXTS = ("full", "window")


def _get_client(spec: str, **kw):
    from canary.llm import get_client  # lazy: provider layer built in parallel
    return get_client(spec, **kw)


def build_system_prompt(instruction: str, hint: str | None = None) -> str:
    parts = [instruction.rstrip(), "", GENERIC]
    for tag in [h.strip() for h in (hint or "").split(",") if h.strip()]:
        if tag not in HINTS:
            raise ValueError(f"unknown hint tag {tag!r}; known: {sorted(HINTS)}")
        parts.append(HINTS[tag])
    return "\n".join(parts)


class LLMPolicy:
    def __init__(self, spec: str, hint: str | None = None, temperature: float = 0.0,
                 max_turns: int = WINDOW_TURNS, client: Any = None, max_tokens: int | None = None,
                 context: str = "full", reasoning_effort: str | None = DEFAULT_REASONING_EFFORT,
                 api: str | None = None):
        """context="full" (default): the whole transcript, every tool result in full.
        context="window": legacy lossy mode (system + last `max_turns` assistant turns, older tool
        results cut to TOOL_RESULT_CHARS). reasoning_effort/api are passed to openai:* clients only."""
        if context not in CONTEXTS:
            raise ValueError(f"context must be one of {CONTEXTS}")
        self.spec, self.hint, self.temperature, self.max_turns, self.max_tokens = spec, hint, temperature, max_turns, max_tokens
        self.context, self.reasoning_effort, self.api = context, reasoning_effort, api
        self.name = spec if not hint else f"{spec}+hint:{hint}"
        self._client = client
        self.reset([], "")

    @property
    def client(self):
        if self._client is None:
            kw = {}
            if self.spec.startswith("openai"):
                kw = {"reasoning_effort": self.reasoning_effort}
                if self.api:
                    kw["api"] = self.api
            self._client = _get_client(self.spec, **kw)
        return self._client

    def reset(self, tools_spec: list[dict], instruction: str) -> None:
        self.tools = tools_spec
        self.system = {"role": "system", "content": build_system_prompt(instruction, self.hint)}
        self.transcript: list[dict] = [self.system, {"role": "user", "content": "Begin the investigation."}]
        self.usage = {"in": 0, "out": 0, "cost_usd": 0.0, "calls": 0}
        self._queue: deque = deque()
        self._pending_id: str | None = None
        self._seen = 0
        self._n = 0

    # -- transcript helpers
    def _feed_results(self, history: list[Step]) -> None:
        for step in history[self._seen:]:
            if self._pending_id is not None:
                self.transcript.append({"role": "tool", "tool_call_id": self._pending_id, "name": step.tool,
                                        "content": json.dumps(step.result, default=str)})
                self._pending_id = None
        self._seen = len(history)

    def _context(self) -> list[dict]:
        if self.context == "full":
            return list(self.transcript)
        body = self.transcript[1:]
        # keep the last max_turns assistant turns (+ their tool results); start on an assistant/user msg
        idx = [i for i, m in enumerate(body) if m["role"] == "assistant"]
        if len(idx) > self.max_turns:
            body = body[idx[-self.max_turns]:]
        out = [self.system]
        last_tool = max((i for i, m in enumerate(body) if m["role"] == "tool"), default=-1)
        for i, m in enumerate(body):
            if m["role"] == "tool" and i != last_tool and len(m["content"]) > TOOL_RESULT_CHARS:
                m = {**m, "content": m["content"][:TOOL_RESULT_CHARS] + "...[truncated]"}
            out.append(m)
        return out

    def _call_model(self):
        resp = self.client.chat(self._context(), tools=self.tools or None, temperature=self.temperature,
                                max_tokens=self.max_tokens)
        u = getattr(resp, "usage", None) or {}
        for k in ("in", "out", "cost_usd"):
            self.usage[k] += u.get(k, 0) or 0
        # cached input (Responses API): cost_usd_est bills it at the cached list price; cost_usd stays the upper bound
        self.usage["cached_in"] = self.usage.get("cached_in", 0) + (u.get("cached_in", 0) or 0)
        self.usage["cost_usd_est"] = self.usage.get("cost_usd_est", 0.0) + (u.get("cost_usd_est", u.get("cost_usd", 0)) or 0)
        self.usage["calls"] += 1
        return resp

    def _record(self, resp) -> None:
        calls = []
        for i, tc in enumerate(resp.tool_calls or []):
            cid = getattr(tc, "id", None) or f"call_{self._n}_{i}"
            calls.append({"id": cid, "name": tc.name, "args": dict(tc.args or {})})
        msg = {"role": "assistant", "content": resp.text or ""}
        items = getattr(resp, "provider_items", None)
        if items:  # opaque provider output (e.g. Responses API reasoning items), replayed next turn
            msg["provider_items"] = items
        if calls:
            msg["tool_calls"] = calls
        self.transcript.append(msg)
        self._queue.extend(calls)

    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]:
        self._n += 1
        self._feed_results(history)
        if not self._queue:
            self._record(self._call_model())
            if not self._queue:
                self.transcript.append({"role": "user", "content": NUDGE})
                self._record(self._call_model())
            if not self._queue:  # fall back to status; keep transcript well-formed
                self.transcript.append({"role": "user", "content": "(no tool call; the runner called status)"})
                self._pending_id = None
                self._seen = len(history) + 1
                return "status", {}
        call = self._queue.popleft()
        self._pending_id = call["id"]
        return call["name"], call["args"]
