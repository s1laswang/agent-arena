"""SHA-256-keyed LLM response cache with offline replay and provenance metadata."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_SHARED_CACHE_DIR = (
    "/tmp/fleet-silas/shared/v16_gemini_cache"
    if Path("/tmp/fleet-silas").exists()
    else "/tmp/fleet-momin/shared/v16_gemini_cache"
)
REPO_COMMITTED_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "gemini_cache"
SECRET = re.compile(r"AIza[0-9A-Za-z_\-]{20,}|sk-[0-9A-Za-z_\-]{16,}|api[_-]?key", re.I)


class OfflineCacheMiss(RuntimeError):
    pass


def default_cache_dir(cache_dir: str | Path | None = None) -> Path:
    if cache_dir is not None and str(cache_dir).strip():
        return Path(cache_dir)
    return Path(os.environ.get("CANARY_GEMINI_CACHE_DIR", DEFAULT_SHARED_CACHE_DIR))


def cache_key(model: Any, system: Any, messages: Any, tools: Any = None, temperature: float = 0, seed: Any = None) -> str:
    blob = json.dumps([model, system, messages, tools, temperature, seed], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _commit() -> str:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parent,
            timeout=5,
        )
        return proc.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def offline() -> bool:
    return os.environ.get("CANARY_OFFLINE") == "1" or os.environ.get("SLEEPER_OFFLINE") == "1"


def _resolve_client(client: Any, model: str) -> Any:
    if client is None:
        from canary.llm import get_client
        spec = model if ":" in model else f"gemini:{model}"
        return get_client(spec)
    if hasattr(client, "chat"):
        return client
    if callable(client):
        return client()
    raise TypeError("client must expose chat(...) or be a callable returning a client")


def _serialize_tool_calls(resp: Any) -> list[dict[str, Any]]:
    raw = resp.get("tool_calls") if isinstance(resp, dict) else getattr(resp, "tool_calls", None)
    if not raw:
        return []
    out: list[dict[str, Any]] = []
    for tc in raw:
        if isinstance(tc, dict):
            out.append(dict(tc))
        else:
            out.append({
                "id": getattr(tc, "id", ""),
                "name": getattr(tc, "name", ""),
                "args": dict(getattr(tc, "args", {}) or {}),
            })
    return out


def _assert_no_secrets(blob: str) -> None:
    if SECRET.search(blob):
        raise ValueError("refusing to cache a response containing a secret pattern")
    for env_name in ("GEMINI_API_KEY", "OPENAI_API_KEY"):
        env_val = os.environ.get(env_name)
        if env_val and env_val in blob:
            raise ValueError(f"refusing to cache a response containing {env_name}")


def _entry_label(entry: Any) -> str:
    if isinstance(entry, dict):
        prov = entry.get("provenance")
        if isinstance(prov, dict):
            return str(prov.get("label") or "")
    return ""


def cached_chat(
    cache_dir: str | Path | None,
    client: Any,
    model: str,
    system: str,
    user: str,
    response_schema: dict[str, Any] | None = None,
    label: str = "REAL",
) -> dict[str, Any]:
    resolved_dir = default_cache_dir(cache_dir)
    messages = [{"role": "user", "content": user}]
    key = cache_key(model, system, messages, None, 0, None)
    path = resolved_dir / f"{key}.json"
    default_lookup = (
        not os.environ.get("CANARY_GEMINI_CACHE_DIR")
        and (cache_dir is None or resolved_dir == Path(DEFAULT_SHARED_CACHE_DIR))
    )
    if default_lookup and label == "REAL":
        repo_hit = Path(REPO_COMMITTED_CACHE_DIR) / f"{key}.json"
        if repo_hit.is_file():
            repo_entry = json.loads(repo_hit.read_text(encoding="utf-8"))
            if _entry_label(repo_entry) == "REAL":
                return repo_entry
    if path.is_file():
        local_entry = json.loads(path.read_text(encoding="utf-8"))
        if not (default_lookup and label == "REAL" and _entry_label(local_entry) == "stub"):
            return local_entry
    if default_lookup:
        repo_hit = Path(REPO_COMMITTED_CACHE_DIR) / f"{key}.json"
        if repo_hit.is_file():
            repo_entry = json.loads(repo_hit.read_text(encoding="utf-8"))
            if label != "REAL" or _entry_label(repo_entry) == "REAL":
                return repo_entry
    if offline():
        raise OfflineCacheMiss(f"offline and no cached response ({key[:12]})")
    active_client = _resolve_client(client, model)
    resp = active_client.chat(
        [{"role": "system", "content": system}] + messages,
        temperature=0.0,
        response_schema=response_schema,
    )
    text = resp["text"] if isinstance(resp, dict) else resp.text
    out = {
        "text": text,
        "tool_calls": _serialize_tool_calls(resp),
        "provenance": {
            "model": model,
            "commit": _commit(),
            "label": label,
        },
    }
    blob = json.dumps(out, sort_keys=True, indent=1)
    _assert_no_secrets(blob)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(blob, encoding="utf-8")
    tmp.replace(path)
    return out
