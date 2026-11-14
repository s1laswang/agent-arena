"""LLM provider layer. Owner: HEAD-AGENTS (engineer: llm-providers).

    client = get_client("stub" | "stub:<script>" | "openai:<model>" | "gemini[:<model>]")
    resp = client.chat(messages, tools=None, temperature=0.0, response_schema=None,
                       max_tokens=None, seed=None) -> LLMResponse
    LLMResponse: text: str, tool_calls: list[ToolCall(id, name, args)],
                 usage: {in, out, cost_usd[, cost_unknown]}, raw
    client.total_usage: cumulative {in, out, cost_usd, calls}

Messages: {"role": system|user|assistant|tool, "content", "tool_calls"?: [{id,name,args}],
"tool_call_id"?, "name"?}. Tools: {"name","description","input_schema"|"parameters"}.
Keys come from .env (GEMINI_API_KEY, OPENAI_API_KEY) via python-dotenv. Never log keys.
Missing key -> MissingKeyError naming the variable. `stub` always works (deterministic).
Retries (max 5, exponential backoff) on 429/5xx/timeouts; pass sleep= to override.
"""
from __future__ import annotations

from .base import LLMClient, LLMError, LLMResponse, MissingKeyError, ToolCall
from .stub import SCRIPTS, StubClient, register_script, schema_example

__all__ = ["get_client", "LLMClient", "LLMResponse", "ToolCall", "LLMError", "MissingKeyError",
           "StubClient", "register_script", "schema_example", "SCRIPTS"]


def get_client(spec: str, **kw) -> LLMClient:
    provider, _, model = spec.partition(":")
    if provider == "stub":
        return StubClient(script=model or None, **kw)
    if provider == "openai":
        from .openai_backend import OpenAIClient
        return OpenAIClient(model=model or default_openai_model(), **kw)
    if provider == "gemini":
        from .gemini_backend import GeminiClient
        return GeminiClient(model=model or None, **kw)
    raise LLMError(f"unknown LLM spec {spec!r}; use stub, stub:<script>, openai:<model> or gemini[:<model>]")


FRONTIER_OPENAI_DEFAULT = "gpt-5.5"  # strongest chat-completions model on our key (checked 02:20)


def default_openai_model() -> str:
    """The frontier model under test: $CANARY_OPENAI_MODEL, else gpt-5.5. Small models = smoke tests only."""
    import os
    return os.environ.get("CANARY_OPENAI_MODEL") or FRONTIER_OPENAI_DEFAULT


def default_gemini_model() -> str:
    """The Gemini model under test: $CANARY_GEMINI_MODEL, else gemini-4-carbon (strongest on the API, 2026-11-14)."""
    import os
    from .gemini_backend import DEFAULT_MODEL
    return os.environ.get("CANARY_GEMINI_MODEL") or DEFAULT_MODEL
