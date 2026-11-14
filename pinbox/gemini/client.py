"""Thin wrapper over google-genai, plus FakeGemini for tests.

    from pinbox.gemini.client import GeminiClient
    g = GeminiClient()                       # model from PINBOX_GEMINI_MODEL, key from GEMINI_API_KEY
    data = g.generate_json(prompt, schema)   # dict/list checked against the schema
    text = g.generate_text(prompt)
    chat = g.start_chat(system, tool_specs)  # manual function calling (used by the defender agent)
    turn = chat.send()                       # -> ModelTurn(text, calls, finish_reason, ...)

`google-genai` is imported lazily, inside methods. So `import pinbox.gemini.client` works on a
bare Python, and FakeGemini never needs the SDK.

Retries: we retry 408/429/5xx, time-outs and connection errors with exponential backoff
(and honour the server's `retryDelay` hint). 400/403/404 are never retried. The SDK's own
retry is left off so the two loops do not multiply.
"""
from __future__ import annotations

import copy
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("pinbox.gemini")

DEFAULT_MODEL = "gemini-4-hydrogen"
MODEL_ENV = "PINBOX_GEMINI_MODEL"
KEY_ENVS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
THINKING_ENV = "PINBOX_GEMINI_THINKING"          # optional: low | medium | high | ...
API_VERSION_ENV = "PINBOX_GEMINI_API_VERSION"    # optional: v1 | v1beta
TRIES_ENV = "PINBOX_GEMINI_TRIES"                # optional: attempts per request (default 6)
RETRY_CODES = {408, 429, 500, 502, 503, 504}
RETRY_STATUSES = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED", "INTERNAL"}
_NET_ERROR_NAMES = ("Timeout", "ConnectError", "RemoteProtocolError", "ReadError", "WriteError",
                    "PoolTimeout", "NetworkError")
_UNKNOWN_FIELD_HINTS = ("unknown name", "invalid json payload", "cannot find field")


class GeminiError(RuntimeError):
    """A Gemini call failed (after retries) or returned unusable output."""


class GeminiUnavailable(GeminiError):
    """No API key, or google-genai is not installed."""


# ---------------------------------------------------------------- config helpers

def resolve_model(model: str | None = None) -> str:
    return (model or os.environ.get(MODEL_ENV, "").strip() or DEFAULT_MODEL)


def api_key_from_env() -> str | None:
    for name in KEY_ENVS:
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return None


def sdk_available() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("google.genai") is not None
    except (ImportError, ValueError):
        return False


def available(api_key: str | None = None) -> bool:
    """True when a real Gemini call could be made (key present and SDK installed)."""
    return bool(api_key or api_key_from_env()) and sdk_available()


# ---------------------------------------------------------------- retry / backoff

def is_retryable(exc: BaseException) -> bool:
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in RETRY_CODES:
        return True
    status = getattr(exc, "status", None)
    if isinstance(status, str) and status.upper() in RETRY_STATUSES:
        return True
    name = type(exc).__name__
    return any(part in name for part in _NET_ERROR_NAMES)


def retry_delay_hint(exc: BaseException) -> float | None:
    """Seconds from a google.rpc.RetryInfo `retryDelay` ("37s") in the error, if any."""
    blob = getattr(exc, "details", None)
    try:
        text = json.dumps(blob) if blob is not None else str(exc)
    except (TypeError, ValueError):
        text = str(exc)
    m = re.search(r'retryDelay"?\s*[:=]\s*"?(\d+(?:\.\d+)?)s', text)
    return float(m.group(1)) if m else None


def call_with_backoff(fn: Callable[[], Any], *, tries: int = 6, base: float = 2.0, max_delay: float = 60.0,
                      sleep: Callable[[float], None] = time.sleep, rng: random.Random | None = None,
                      what: str = "gemini call"):
    """Run fn(); on a retryable error wait (exponential + jitter, or the server hint) and try again."""
    rng = rng or random.Random("pinbox-gemini-backoff")
    tries = max(1, int(tries))
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - we re-raise anything we do not retry
            if not is_retryable(e) or i == tries - 1:
                raise
            delay = min(max_delay, base ** i) + rng.random()
            hint = retry_delay_hint(e)
            if hint is not None:
                delay = max(delay, min(hint + rng.random(), max_delay * 2))
            log.warning("%s failed (%s: %s); retry %d/%d in %.1fs", what, type(e).__name__,
                        str(e)[:160], i + 1, tries - 1, delay)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


# ---------------------------------------------------------------- tiny JSON-schema check

_PY_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "integer": int, "number": (int, float), "null": type(None),
}


def schema_errors(value, schema: dict, path: str = "$") -> list[str]:
    """Check the subset of JSON Schema we use (type, required, properties, items, enum, minItems,
    maxItems). Gemini guarantees valid JSON, not correct values, so we check in code."""
    errs: list[str] = []
    if not isinstance(schema, dict):
        return errs
    types = schema.get("type")
    if types is not None:
        tlist = types if isinstance(types, list) else [types]
        ok = False
        for t in tlist:
            py = _PY_TYPES.get(t)
            if py is None:
                ok = True
                break
            if isinstance(value, bool) and t in ("integer", "number"):
                continue
            if isinstance(value, py):
                ok = True
                break
        if not ok:
            return [f"{path}: expected {types}, got {type(value).__name__}"]
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} not in enum")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errs.append(f"{path}: missing '{req}'")
        props = schema.get("properties", {})
        for k, v in value.items():
            if k in props:
                errs.extend(schema_errors(v, props[k], f"{path}.{k}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errs.append(f"{path}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errs.append(f"{path}: more than {schema['maxItems']} items")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errs.extend(schema_errors(item, schema["items"], f"{path}[{i}]"))
    return errs


# ---------------------------------------------------------------- turns (SDK-free)

@dataclass
class FunctionCall:
    name: str
    args: dict = field(default_factory=dict)
    id: str | None = None


@dataclass
class ModelTurn:
    """One model reply, without SDK types: text, function calls and why it stopped."""
    text: str = ""
    calls: list = field(default_factory=list)          # list[FunctionCall]
    finish_reason: str = "STOP"
    blocked: str | None = None                          # prompt block reason, if any
    usage: dict = field(default_factory=dict)

    @classmethod
    def coerce(cls, obj, counter: int = 0) -> "ModelTurn":
        if isinstance(obj, ModelTurn):
            return obj
        if isinstance(obj, str):
            return cls(text=obj)
        if not isinstance(obj, dict):
            raise TypeError(f"cannot turn {type(obj).__name__} into a ModelTurn")
        calls = []
        for j, c in enumerate(obj.get("calls") or []):
            if isinstance(c, FunctionCall):
                calls.append(c)
            else:
                calls.append(FunctionCall(name=c["name"], args=dict(c.get("args") or {}),
                                          id=c.get("id") or f"fake_{counter}_{j}"))
        return cls(text=obj.get("text", "") or "", calls=calls,
                   finish_reason=obj.get("finish_reason", "STOP"), blocked=obj.get("blocked"),
                   usage=dict(obj.get("usage") or {}))


def _add_usage(total: dict, usage: dict) -> None:
    for k, v in (usage or {}).items():
        if isinstance(v, (int, float)):
            total[k] = total.get(k, 0) + v


# ---------------------------------------------------------------- real client

class GeminiClient:
    """google-genai wrapper. Nothing is imported or built until the first call."""

    def __init__(self, model: str | None = None, api_key: str | None = None, *,
                 thinking_level: str | None = None, max_output_tokens: int = 32768,
                 timeout_ms: int = 600_000, tries: int | None = None, api_version: str | None = None,
                 genai_client=None, http_client=None, sleep: Callable[[float], None] = time.sleep):
        self.model = resolve_model(model)
        self.api_key = api_key or api_key_from_env()
        self.thinking_level = thinking_level or (os.environ.get(THINKING_ENV, "").strip() or None)
        self.max_output_tokens = int(max_output_tokens)
        self.timeout_ms = int(timeout_ms)
        if tries is None:
            try:
                tries = int(os.environ.get(TRIES_ENV, "") or 6)
            except ValueError:
                tries = 6
        self.tries = max(1, int(tries))
        self.api_version = api_version or (os.environ.get(API_VERSION_ENV, "").strip() or None)
        self._client = genai_client
        self._http_client = http_client          # tests: an httpx2.Client with a MockTransport
        self._sleep = sleep
        self._rng = random.Random(f"pinbox-gemini-backoff:{self.model}")
        self._switched_version = False
        self._genai = self._types = None
        self.usage: dict = {}
        self.requests = 0

    @property
    def name(self) -> str:
        return self.model

    # -- lazy SDK -------------------------------------------------------
    def _sdk(self):
        if self._types is None:
            try:
                from google import genai  # noqa: WPS433 - lazy on purpose
                from google.genai import types
            except ImportError as e:
                raise GeminiUnavailable(
                    "google-genai is not installed (pip install google-genai)") from e
            self._genai, self._types = genai, types
        return self._genai, self._types

    def _build_client(self):
        genai, types = self._sdk()
        if not self.api_key:
            raise GeminiUnavailable("no Gemini API key: set GEMINI_API_KEY")
        opts = {"timeout": self.timeout_ms}
        if self.api_version:
            opts["api_version"] = self.api_version
        if self._http_client is not None:
            opts["httpx_client"] = self._http_client
        return genai.Client(api_key=self.api_key, http_options=types.HttpOptions(**opts))

    @property
    def types(self):
        return self._sdk()[1]

    @property
    def raw(self):
        """The underlying genai.Client (built on first use)."""
        if self._client is None:
            self._client = self._build_client()
        return self._client

    # -- config + one request --------------------------------------------
    def make_config(self, *, system: str | None = None, thinking_level: str | None = None,
                    json_schema: dict | None = None, tools: list | None = None):
        types = self.types
        kw: dict[str, Any] = {"max_output_tokens": self.max_output_tokens}
        if system:
            kw["system_instruction"] = system
        level = thinking_level or self.thinking_level
        if level:
            kw["thinking_config"] = types.ThinkingConfig(thinking_level=level)
        if json_schema is not None:
            kw["response_mime_type"] = "application/json"
            kw["response_json_schema"] = json_schema
        if tools is not None:
            kw["tools"] = tools
            kw["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
            kw["tool_config"] = types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO"))
        return types.GenerateContentConfig(**kw)

    def _is_unknown_field(self, e: BaseException) -> bool:
        if getattr(e, "code", None) != 400:
            return False
        msg = (str(getattr(e, "message", "")) + " " + str(e)).lower()
        return any(h in msg for h in _UNKNOWN_FIELD_HINTS)

    def generate(self, contents, config):
        """One generate_content call with backoff. Returns the SDK response."""
        def once():
            return self.raw.models.generate_content(model=self.model, contents=contents, config=config)

        try:
            resp = call_with_backoff(once, tries=self.tries, sleep=self._sleep, rng=self._rng,
                                     what=f"{self.model} generate_content")
        except Exception as e:  # noqa: BLE001
            if self._is_unknown_field(e) and not self._switched_version and self._http_client is None:
                # The v1 endpoint may not know newer fields (JSON schema, thinking_level); try the other one.
                self._switched_version = True
                self.api_version = "v1" if self.api_version == "v1beta" else "v1beta"
                log.warning("Gemini rejected a field (%s); retrying on api_version=%s", str(e)[:120],
                            self.api_version)
                self._client = self._build_client()
                return self.generate(contents, config)
            if isinstance(e, GeminiError):
                raise
            raise GeminiError(f"{type(e).__name__}: {str(e)[:500]}") from e
        self.requests += 1
        _add_usage(self.usage, usage_dict(resp))
        return resp

    # -- public helpers ----------------------------------------------------
    def generate_json(self, prompt: str, schema: dict, *, system: str | None = None,
                      thinking_level: str | None = None, attempts: int = 2):
        config = self.make_config(system=system, thinking_level=thinking_level, json_schema=schema)
        last = ""
        for _ in range(max(1, attempts)):
            resp = self.generate(prompt, config)
            data = getattr(resp, "parsed", None)
            if data is None:
                text = response_text(resp)
                try:
                    data = json.loads(text) if text else None
                except ValueError:
                    data = None
            if data is None:
                last = f"no valid JSON (finish={finish_reason(resp)})"
                continue
            errs = schema_errors(data, schema)
            if errs:
                last = "; ".join(errs[:5])
                continue
            return data
        raise GeminiError(f"generate_json failed: {last}")

    def generate_text(self, prompt: str, *, system: str | None = None, thinking_level: str | None = None) -> str:
        config = self.make_config(system=system, thinking_level=thinking_level)
        return response_text(self.generate(prompt, config))

    def count_tokens(self, text: str) -> int:
        try:
            return int(self.raw.models.count_tokens(model=self.model, contents=text).total_tokens)
        except Exception:  # noqa: BLE001 - an estimate is fine for budgeting
            return estimate_tokens(text)

    def start_chat(self, system: str, tool_specs: list, *, first_message: str = "Start the task now.",
                   thinking_level: str | None = None) -> "GeminiChat":
        types = self.types
        config = self.make_config(system=system, thinking_level=thinking_level,
                                  tools=to_gemini_tools(tool_specs, types))
        contents = [types.Content(role="user", parts=[types.Part.from_text(text=first_message)])]
        return GeminiChat(self, config, contents)


class GeminiChat:
    """A manual function-calling conversation. The model turn is kept unchanged (thought signatures)."""

    def __init__(self, gclient: GeminiClient, config, contents):
        self.g = gclient
        self.config = config
        self.contents = contents
        self._pending_first = True

    def send(self, responses: list | None = None, text: str | None = None) -> ModelTurn:
        """Send function results (list of (FunctionCall, dict)) and/or a user text, get the next turn."""
        types = self.g.types
        parts = []
        for call, out in responses or []:
            parts.append(types.Part(function_response=types.FunctionResponse(
                id=call.id, name=call.name, response=_as_response_dict(out))))
        if text:
            parts.append(types.Part.from_text(text=text))
        if parts:
            self.contents.append(types.Content(role="user", parts=parts))
        elif not self._pending_first:
            raise GeminiError("send() needs function responses or text after the first turn")
        self._pending_first = False
        resp = self.g.generate(self.contents, self.config)
        return self._turn(resp)

    def _turn(self, resp) -> ModelTurn:
        usage = usage_dict(resp)
        cands = getattr(resp, "candidates", None) or []
        if not cands:
            fb = getattr(resp, "prompt_feedback", None)
            reason = str(getattr(fb, "block_reason", None) or "NO_CANDIDATES")
            return ModelTurn(text="", calls=[], finish_reason="BLOCKED", blocked=reason, usage=usage)
        cand = cands[0]
        if getattr(cand, "content", None) is not None and getattr(cand.content, "parts", None):
            self.contents.append(cand.content)        # unchanged: keeps thought signatures
        calls = []
        for j, fc in enumerate(getattr(resp, "function_calls", None) or []):
            calls.append(FunctionCall(name=fc.name or "", args=dict(fc.args or {}),
                                      id=fc.id or None))
        return ModelTurn(text=response_text(resp), calls=calls, finish_reason=finish_reason(resp),
                         usage=usage)

    def transcript(self) -> list:
        out = []
        for c in self.contents:
            try:
                out.append(c.model_dump(mode="json", exclude_none=True))
            except Exception:  # noqa: BLE001
                out.append({"repr": repr(c)[:2000]})
        return out


# ---------------------------------------------------------------- SDK response helpers (duck-typed)

def response_text(resp) -> str:
    """Text parts of the first candidate, skipping thought parts (no SDK warning)."""
    try:
        parts = resp.candidates[0].content.parts or []
    except (AttributeError, IndexError, TypeError):
        return ""
    return "".join(p.text for p in parts if getattr(p, "text", None) and not getattr(p, "thought", False))


def finish_reason(resp) -> str:
    try:
        fr = resp.candidates[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return "NO_CANDIDATES"
    return getattr(fr, "name", None) or str(fr or "UNKNOWN")


def usage_dict(resp) -> dict:
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return {}
    out = {}
    for k in ("prompt_token_count", "candidates_token_count", "thoughts_token_count",
              "total_token_count", "cached_content_token_count"):
        v = getattr(u, k, None)
        if isinstance(v, int):
            out[k] = v
    return out


def _as_response_dict(out) -> dict:
    """FunctionResponse.response must be a dict; our dispatch dict already is."""
    if isinstance(out, dict):
        return json.loads(json.dumps(out, ensure_ascii=False, default=str))
    return {"result": json.loads(json.dumps(out, ensure_ascii=False, default=str))}


# ---------------------------------------------------------------- tool specs -> Gemini

_SCHEMA_KEYS = {"type", "title", "description", "properties", "required", "additionalProperties", "enum",
                "format", "minimum", "maximum", "items", "prefixItems", "minItems", "maxItems", "anyOf",
                "$ref", "$defs", "nullable"}


def clean_schema(schema):
    """Keep only JSON-Schema keywords Gemini documents; move `default` into the description."""
    if isinstance(schema, list):
        return [clean_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k in ("properties", "$defs") and isinstance(v, dict):
            out[k] = {pk: clean_schema(pv) for pk, pv in v.items()}
        elif k in ("items", "anyOf", "prefixItems", "additionalProperties"):
            out[k] = clean_schema(v)
        elif k in _SCHEMA_KEYS:
            out[k] = copy.deepcopy(v)
    if "default" in schema and not isinstance(schema.get("default"), (dict, list)):
        desc = out.get("description", "")
        out["description"] = (desc + " " if desc else "") + f"Default: {json.dumps(schema['default'])}."
    return out


def function_declarations(tool_specs: list) -> list[dict]:
    """Plain dicts {name, description, parameters?} (SDK-free; easy to test)."""
    decls = []
    for s in tool_specs:
        d = {"name": s["name"], "description": s.get("description", "")}
        params = s.get("parameters") or {}
        if params.get("properties"):           # no schema for no-arg tools (safer with the API)
            d["parameters"] = clean_schema(params)
        decls.append(d)
    return decls


def to_gemini_tools(tool_specs: list, types) -> list:
    decls = []
    for d in function_declarations(tool_specs):
        kw = {"name": d["name"], "description": d["description"]}
        if "parameters" in d:
            kw["parameters_json_schema"] = d["parameters"]
        decls.append(types.FunctionDeclaration(**kw))
    return [types.Tool(function_declarations=decls)]


def estimate_tokens(text: str) -> int:
    """Rough token count (about 4 characters per token)."""
    return (len(text or "") + 3) // 4


# ---------------------------------------------------------------- fake (tests, demos, no network)

class FakeGemini:
    """Same methods as GeminiClient, but every answer is scripted.

    json_replies / text_replies: lists consumed in order. An item may be a value, an Exception
    (raised), or a callable(prompt, schema) -> value. chat_turns: list of ModelTurn / dict
    {"text", "calls": [{"name", "args", "id"?}]} / callable(history) -> one of those.
    """

    def __init__(self, json_replies=None, text_replies=None, chat_turns=None, model: str = "fake-gemini",
                 default_json=None):
        self.model = model
        self.json_replies = list(json_replies or [])
        self.text_replies = list(text_replies or [])
        self.chat_turns = list(chat_turns or [])
        self.default_json = default_json
        self.prompts: list[tuple] = []
        self.chats: list[FakeChat] = []
        self.usage: dict = {}
        self.requests = 0

    @property
    def name(self) -> str:
        return self.model

    def _next(self, queue: list, prompt, schema, kind: str):
        self.prompts.append((kind, prompt, schema))
        self.requests += 1
        if queue:
            item = queue.pop(0)
        elif kind == "json" and self.default_json is not None:
            item = self.default_json
        else:
            raise GeminiError(f"FakeGemini: no scripted {kind} reply left")
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(prompt, schema)
        return copy.deepcopy(item)

    def generate_json(self, prompt: str, schema: dict, **_kw):
        data = self._next(self.json_replies, prompt, schema, "json")
        errs = schema_errors(data, schema)
        if errs:
            raise GeminiError("generate_json failed: " + "; ".join(errs[:5]))
        return data

    def generate_text(self, prompt: str, **_kw) -> str:
        return str(self._next(self.text_replies, prompt, None, "text"))

    def count_tokens(self, text: str) -> int:
        return estimate_tokens(text)

    def start_chat(self, system: str, tool_specs: list, *, first_message: str = "Start the task now.",
                   **_kw) -> "FakeChat":
        chat = FakeChat(self, system, tool_specs, first_message)
        self.chats.append(chat)
        return chat


class FakeChat:
    def __init__(self, fake: FakeGemini, system: str, tool_specs: list, first_message: str):
        self.fake = fake
        self.system = system
        self.tool_specs = tool_specs
        self.declarations = function_declarations(tool_specs)
        self.history: list[dict] = [{"role": "user", "text": first_message}]
        self.sent: list = []          # what the agent sent back each turn

    def send(self, responses: list | None = None, text: str | None = None) -> ModelTurn:
        if responses or text:
            entry = {"role": "user", "function_responses": [
                {"id": c.id, "name": c.name, "response": _as_response_dict(o)} for c, o in (responses or [])]}
            if text:
                entry["text"] = text
            self.history.append(entry)
            self.sent.append(entry)
        self.fake.requests += 1
        if not self.fake.chat_turns:
            raise GeminiError("FakeGemini: no scripted chat turn left")
        item = self.fake.chat_turns.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(self.history)
        turn = ModelTurn.coerce(copy.deepcopy(item), counter=len(self.history))
        self.history.append({"role": "model", "text": turn.text,
                             "calls": [{"id": c.id, "name": c.name, "args": c.args} for c in turn.calls]})
        _add_usage(self.fake.usage, turn.usage)
        return turn

    def transcript(self) -> list:
        return copy.deepcopy(self.history)


def make_gemini(model: str | None = None, *, fake: bool = False, **kw):
    """A GeminiClient, or a FakeGemini when fake=True."""
    if fake:
        return FakeGemini(model=f"fake:{resolve_model(model)}", **kw)
    return GeminiClient(model=model, **kw)
