"""Shared plumbing for the Gemini roles: client resolution, structured calls, config loading.

Every role calls the LLM with `response_schema` (structured output), validates with pydantic,
and falls back deterministically on anything invalid. No role ever raises because of model output.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

M = TypeVar("M", bound=BaseModel)
CONFIG_DIR = Path(__file__).resolve().parents[2] / "configs" / "agents"


def resolve_client(spec_or_client: Any):
    """Accept a client object or a spec string ("stub" | "gemini:<model>")."""
    if not isinstance(spec_or_client, str):
        return spec_or_client
    try:
        from canary.llm import get_client  # type: ignore[attr-defined]
    except ImportError:
        get_client = None
    if get_client is None:
        if spec_or_client == "stub":
            return _MiniStub()
        raise RuntimeError(
            f"canary.llm.get_client is not available on this branch; cannot build {spec_or_client!r}. "
            "Merge the llm-providers work (justSilas-agents-llm) or use --llm stub.")
    return get_client(spec_or_client)


class _Resp:
    def __init__(self, text: str):
        self.text, self.tool_calls, self.usage, self.raw = text, [], {"in": 0, "out": 0}, None


class _MiniStub:
    """Fallback used only when canary.llm has no get_client yet. Returns '{}' (forces role fallbacks)."""
    name = "stub"

    def chat(self, messages, tools=None, temperature=0.0, response_schema=None):
        return _Resp("{}")


def inline_schema(model: type[BaseModel]) -> dict:
    """pydantic JSON schema with $refs inlined (Gemini structured output dislikes $defs)."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                return walk(dict(defs[node["$ref"].split("/")[-1]]))
            return {k: walk(v) for k, v in node.items() if k not in ("title", "default")}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node
    return walk(schema)


def structured_call(client, system: str, user: str, model: type[M],
                    temperature: float = 0.0) -> tuple[M | None, str | None]:
    """One structured LLM call. Returns (parsed, None) or (None, error_string)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        resp = client.chat(messages, tools=None, temperature=temperature,
                           response_schema=inline_schema(model))
        text = getattr(resp, "text", None)
        if text is None and isinstance(resp, dict):
            text = resp.get("text")
        return model.model_validate(json.loads(text or "")), None
    except (ValidationError, json.JSONDecodeError, TypeError, ValueError) as e:
        return None, f"{type(e).__name__}: {str(e)[:200]}"
    except Exception as e:  # transport errors etc.: still never crash a role
        return None, f"llm_error {type(e).__name__}: {str(e)[:200]}"


def load_prompt(role: str) -> dict[str, Any]:
    """Load configs/agents/<role>.yaml (tiny YAML subset: `key: |` blocks and `key: value`)."""
    path = CONFIG_DIR / f"{role}.yaml"
    if not path.exists():
        return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(path.read_text()) or {}
    except ImportError:
        return _mini_yaml(path.read_text())


def _mini_yaml(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    key, buf = None, []
    for line in text.splitlines():
        if key and (line.startswith("  ") or not line.strip()):
            buf.append(line[2:])
            continue
        if key:
            out[key], key, buf = "\n".join(buf).strip() + "\n", None, []
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v == "|":
            key = k.strip()
        else:
            out[k.strip()] = v.strip('"')
    if key:
        out[key] = "\n".join(buf).strip() + "\n"
    return out


def get(obj: Any, name: str, default: Any = None) -> Any:
    """Read a field from a dataclass/object or a dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


Fallback = Callable[[], Any]
