"""SHA-256-keyed LLM response cache with byte-identical offline replay and provenance labels.

Adapted (with attribution) from Momin's `agents/gemini.py` cache_key/chat and `scripts/gemini_cache.py`
secret check on branch `momin` (lab/frontier_cache.py replay story), so one replay story covers Canary too:

  key  = sha256(json.dumps([model, system, messages, tools, temperature, seed], sort_keys=True))
  file = <cache_dir>/<key>.json = {"text", "tool_calls", "provenance": {"model", "commit", "label": REAL|stub}}

Offline: with CANARY_OFFLINE=1 (or SLEEPER_OFFLINE=1) a cache miss raises OfflineCacheMiss and never calls a client.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

SECRET = re.compile(r"AIza[0-9A-Za-z_\-]{30,}|api[_-]?key", re.I)   # same pattern as momin scripts/gemini_cache.py


class OfflineCacheMiss(RuntimeError):
    pass


def cache_key(model, system, messages, tools=None, temperature=0, seed=None) -> str:
    blob = json.dumps([model, system, messages, tools, temperature, seed], sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parent, timeout=5).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def offline() -> bool:
    return os.environ.get("CANARY_OFFLINE") == "1" or os.environ.get("SLEEPER_OFFLINE") == "1"


def cached_chat(cache_dir, client, model: str, system: str, user: str, response_schema=None, label: str = "REAL") -> dict:
    """Return {"text", "tool_calls", "provenance"}; cache hit = no client call (no key needed)."""
    messages = [{"role": "user", "content": user}]
    key = cache_key(model, system, messages, None, 0, None)
    path = Path(cache_dir) / f"{key}.json"
    if path.is_file():
        return json.loads(path.read_text())
    if offline():
        raise OfflineCacheMiss(f"offline and no cached response ({key[:12]})")
    resp = client().chat([{"role": "system", "content": system}] + messages, temperature=0.0,
                         response_schema=response_schema)
    text = resp["text"] if isinstance(resp, dict) else resp.text
    out = {"text": text, "tool_calls": [], "provenance": {"model": model, "commit": _commit(), "label": label}}
    blob = json.dumps(out, sort_keys=True, indent=1)
    key_env = os.environ.get("GEMINI_API_KEY")
    if SECRET.search(blob) or (key_env and key_env in blob):
        raise ValueError("refusing to cache a response containing a secret pattern")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(blob)
    tmp.replace(path)
    return out
