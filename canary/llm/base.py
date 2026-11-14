"""Shared types, retry logic and helpers for all LLM backends."""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class LLMError(RuntimeError):
    pass


class MissingKeyError(LLMError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=lambda: {"in": 0, "out": 0, "cost_usd": 0.0})
    raw: Any = None


def load_env() -> None:
    """Load .env from cwd or any parent (repo root). Never prints values."""
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:  # pragma: no cover
        return
    path = find_dotenv(usecwd=True)
    if not path:
        here = Path(__file__).resolve().parents[2] / ".env"
        path = str(here) if here.exists() else ""
    if path:
        load_dotenv(path, override=False)


def require_key(var: str) -> str:
    load_env()
    key = os.environ.get(var, "").strip()
    if not key:
        raise MissingKeyError(f"{var} is not set (add it to .env or the environment)")
    return key


def normalize_tools(tools: list[dict] | None) -> list[dict]:
    out = []
    for t in tools or []:
        schema = t.get("input_schema") or t.get("parameters") or {"type": "object", "properties": {}}
        out.append({"name": t["name"], "description": t.get("description", ""), "schema": schema})
    return out


def is_retryable(exc: BaseException) -> bool:
    for attr in ("status_code", "code", "status"):
        v = getattr(exc, attr, None)
        if isinstance(v, int) and (v == 429 or v == 408 or 500 <= v < 600):
            return True
    name = type(exc).__name__.lower()
    return any(k in name for k in ("ratelimit", "timeout", "connection", "unavailable",
                                   "internalserver", "resourceexhausted", "servererror"))


class LLMClient:
    """Base client: subclasses implement _chat(). chat() adds retries and usage accounting."""

    provider = "base"

    def __init__(self, model: str = "", max_retries: int | None = None, base_delay: float = 1.0,
                 sleep: Callable[[float], None] = time.sleep, seed: int | None = None):
        self.model = model
        # transport retries only (never changes what the model sees); CANARY_LLM_MAX_RETRIES rides out network blips
        self.max_retries = int(os.environ.get("CANARY_LLM_MAX_RETRIES", "5")) if max_retries is None else max_retries
        self.base_delay = base_delay
        self.sleep = sleep
        self.seed = seed
        self.total_usage: dict[str, Any] = {"in": 0, "out": 0, "cost_usd": 0.0, "calls": 0}

    @property
    def name(self) -> str:
        return f"{self.provider}:{self.model}" if self.model else self.provider

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.0, response_schema: dict | None = None,
             max_tokens: int | None = None, seed: int | None = None) -> LLMResponse:
        seed = self.seed if seed is None else seed
        attempt = 0
        while True:
            try:
                resp = self._chat(messages, normalize_tools(tools), temperature,
                                  response_schema, max_tokens, seed)
                break
            except Exception as e:  # noqa: BLE001
                if attempt >= self.max_retries or not is_retryable(e):
                    raise
                delay = min(self.base_delay * (2 ** attempt), 60.0) * (1 + 0.1 * random.random())
                attempt += 1
                self.sleep(delay)
        for k in ("in", "out", "cost_usd"):
            self.total_usage[k] += resp.usage.get(k, 0) or 0
        self.total_usage["calls"] += 1
        return resp

    def _chat(self, messages, tools, temperature, response_schema, max_tokens, seed) -> LLMResponse:
        raise NotImplementedError
