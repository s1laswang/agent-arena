"""Loader for the failure research dataset (data/failures)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "data" / "failures"


def cases() -> dict[str, dict]:
    out = {}
    for p in sorted(ROOT.glob("cases_*.json")):
        for c in json.loads(p.read_text(encoding="utf-8")):
            out[c["id"]] = c
    return out


def patterns() -> list[dict]:
    return json.loads((ROOT / "patterns.json").read_text(encoding="utf-8"))["patterns"]


def pattern_for_family(family: str) -> dict | None:
    return next((p for p in patterns() if p.get("family") == family), None)
