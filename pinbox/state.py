"""Episode state helpers. The state is one JSON-serialisable dict (SPEC section 4)."""
from __future__ import annotations

import copy
import json
import os
import time
from pathlib import Path

from .rng import TODAY, date_plus_minutes

COMPANY = {
    "name": "Northwind Bakery Oy",
    "domain": "northwind.fi",
    "user": {"name": "Mia Koskinen", "email": "mia@northwind.fi", "role": "Office manager"},
}
DAY_START = "08:00"  # simulated clock starts at 08:00 on `today`; +1 minute per tool call

# Keys that tools must never return.
SECRET_KEYS = ("hidden", "events")


def episode_id(family: str, seed: int, difficulty: int) -> str:
    return f"{family}-s{seed}-d{difficulty}"


def new_state(family: str, seed: int, difficulty: int, budget: int, today: str = TODAY,
              payload_sources: str = "handwritten") -> dict:
    """The common skeleton every family fills in."""
    return {
        "meta": {
            "family": family,
            "seed": int(seed),
            "difficulty": int(difficulty),
            "episode_id": episode_id(family, seed, difficulty),
            "today": today,
            "budget": int(budget),
            "payload_sources": payload_sources,
        },
        "calls": 0,
        "clock": 0,
        "tool_counts": {},
        "company": copy.deepcopy(COMPANY),
        "emails": [],
        "outbox": [],
        "documents": [],
        "contacts": [],
        "calls_log": [],
        "events": {"pending": [], "fired": []},
        "hidden": {"phones": {}},
    }


def sim_time(state: dict) -> str:
    """Simulated wall time, e.g. '2026-11-16T08:17' after 17 tool calls."""
    meta = state.get("meta", {})
    return date_plus_minutes(meta.get("today", TODAY), DAY_START, int(state.get("clock", 0)))


def public_view(state: dict) -> dict:
    """Deep copy without the secret parts (hidden data and future events)."""
    return {k: copy.deepcopy(v) for k, v in state.items() if k not in SECRET_KEYS}


def dumps(obj, indent: int | None = 1) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=False)


def canonical_json(obj) -> str:
    """Byte-stable text used to compare worlds."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_copy(obj):
    """Deep copy through JSON (also proves the object is JSON-able)."""
    return json.loads(json.dumps(obj, ensure_ascii=False))


def write_text(path, text: str) -> None:
    """Write UTF-8 text atomically, with retries (OneDrive can lock files briefly)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    last = None
    for attempt in range(6):
        try:
            with open(tmp, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp, path)
            return
        except PermissionError as e:  # pragma: no cover - Windows file locks
            last = e
            time.sleep(0.05 * (attempt + 1))
    raise last  # pragma: no cover


def save_json(path, obj) -> None:
    write_text(path, dumps(obj) + "\n")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_path(state: dict, dotted: str):
    cur = state
    for part in dotted.split("."):
        cur = cur[part]
    return cur


def set_path(state: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = state
    for part in parts[:-1]:
        cur = cur[part]
    cur[parts[-1]] = value
