"""Wording library for attack and noise texts (pinbox/data/payloads.json).

Generators pick a wording with the episode RNG and fill its {placeholders}.

Which wordings can be picked is controlled by the *source mode*:
  - "handwritten" (default): only entries with source == "handwritten". This keeps
    the eval worlds stable when Gemini adds new wordings to the file.
  - "all": every entry.  - "gemini": only entries whose source starts with "gemini".
Set it with the env var PINBOX_PAYLOAD_SOURCES or the `source_mode()` context manager.
Episodes record the mode in state["meta"]["payload_sources"]; the grader uses the same
mode when it regenerates the truth.

`forced(slot, entries)` makes a slot offer only the given entries (used by the Gemini
regret filter to test a candidate wording before it is added to the file).
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import re
from pathlib import Path

PAYLOADS_PATH = Path(__file__).resolve().parent / "data" / "payloads.json"
MODES = ("handwritten", "all", "gemini")
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")

_cache: dict | None = None
_mode_stack: list[str] = []
_forced: dict[str, list[dict]] = {}
_version = 0  # bumps on every (re)load, so caches built from old wordings are not reused


def library(reload: bool = False) -> dict:
    """The parsed payloads.json (cached)."""
    global _cache, _version
    if _cache is None or reload:
        with open(PAYLOADS_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
        _version += 1
    return _cache


def version() -> int:
    library()
    return _version


def forced_snapshot() -> dict:
    """The forced entries now active (stored in episode meta so a re-grade can rebuild the world)."""
    return copy.deepcopy(_forced)


@contextlib.contextmanager
def context_for(meta: dict):
    """Apply the payload mode and any forced wordings recorded in an episode's meta."""
    with contextlib.ExitStack() as stack:
        stack.enter_context(source_mode(meta.get("payload_sources", "handwritten")))
        for slot, entries_ in (meta.get("forced_payloads") or {}).items():
            stack.enter_context(forced(slot, entries_))
        yield


def reload() -> dict:
    return library(reload=True)


def current_mode() -> str:
    if _mode_stack:
        return _mode_stack[-1]
    mode = os.environ.get("PINBOX_PAYLOAD_SOURCES", "handwritten").strip().lower() or "handwritten"
    return mode if mode in MODES else "handwritten"


def forced_active() -> bool:
    return bool(_forced)


def forced_signature() -> str:
    """A stable text key of the forced entries (for caches)."""
    if not _forced:
        return ""
    return json.dumps(_forced, sort_keys=True, ensure_ascii=True)


@contextlib.contextmanager
def source_mode(mode: str | None):
    mode = (mode or "handwritten").lower()
    if mode not in MODES:
        raise ValueError(f"unknown payload source mode {mode!r}; use one of {MODES}")
    _mode_stack.append(mode)
    try:
        yield
    finally:
        _mode_stack.pop()


@contextlib.contextmanager
def forced(slot: str, entries):
    """Within the block, `entries(slot)` returns only these entries."""
    if isinstance(entries, dict):
        entries = [entries]
    old = _forced.get(slot)
    _forced[slot] = [copy.deepcopy(e) for e in entries]
    try:
        yield
    finally:
        if old is None:
            _forced.pop(slot, None)
        else:
            _forced[slot] = old


def _source_ok(entry: dict, mode: str) -> bool:
    src = str(entry.get("source", "handwritten"))
    if mode == "all":
        return True
    if mode == "gemini":
        return src.startswith("gemini")
    return src == "handwritten"


def entries(slot: str, kind: str | None = None) -> list[dict]:
    """Wordings for a slot under the current mode (optionally only one `kind`)."""
    if slot in _forced:
        pool = _forced[slot]
    else:
        pool = library().get("slots", {}).get(slot, [])
        mode = current_mode()
        pool = [e for e in pool if _source_ok(e, mode)]
        if not pool:  # e.g. mode "gemini" but none added yet: fall back to all
            pool = list(library().get("slots", {}).get(slot, []))
    if kind is not None:
        with_kind = [e for e in pool if e.get("kind") == kind]
        if with_kind or slot not in _forced:
            pool = with_kind
    return pool


def pick(rng, slot: str, kind: str | None = None) -> dict:
    pool = entries(slot, kind)
    if not pool:
        raise KeyError(f"no payload wordings for slot {slot!r} kind {kind!r}")
    return copy.deepcopy(rng.choice(pool))


def fill(text: str, values: dict) -> str:
    """Replace {name} with values[name]. Unknown names are left as they are.

    Same effect as str.format_map on a safe dict, but never evaluates attribute or
    index lookups, and stray braces never raise.
    """
    if not isinstance(text, str):
        return ""

    def sub(m):
        key = m.group(1)
        return str(values[key]) if key in values else m.group(0)

    return PLACEHOLDER_RE.sub(sub, text)


def placeholders(text: str) -> list[str]:
    return PLACEHOLDER_RE.findall(text or "")
