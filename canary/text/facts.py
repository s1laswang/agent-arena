"""Public inputs to every TextProvider. NEVER put the mole id or any truth in here.

Owner: HEAD-ENV. The env builds one PublicDayFacts per day from public state only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EmployeeFacts:
    id: str
    name: str
    dept: str
    role: str
    clearance: int | None = None


@dataclass(frozen=True)
class PublicDayFacts:
    tier: str
    seed: int                                   # world seed (public); providers use it for deterministic variety
    day: int
    company: str
    employees: tuple[EmployeeFacts, ...]
    docs: tuple[dict[str, Any], ...]            # today's published docs: {doc_id, title, day, recipients}
    decoy: str | None = None                    # innocent disgruntled employee (public persona fact, not truth)
    decoy_mood: str = "neutral"                 # "angry" | "neutral"
    restricted: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)


class TextProvider(Protocol):
    name: str
    def day_messages(self, facts: PublicDayFacts) -> list[dict]: ...
        # -> [{id, day, channel, sender, recipients, subject, body}]; ids unique per world, e.g. "m<day>-<k>"
    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str: ...
        # signal in {"evasive", "cooperative"}
