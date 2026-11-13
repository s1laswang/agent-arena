"""Text lint: rendered company text must never confess or name a leak target. Pure, no deps."""
from __future__ import annotations

import re

FORBIDDEN = (
    "i am the mole", "i'm the mole", "the mole is", "leaked it", "i leaked", "we leaked",
    "sold the", "i sold", "i'm leaking", "i am leaking", "sent it to the rival", "mole",
)
RIVAL_ADDR = re.compile(r"[\w.+-]+@[\w-]*(rival|competitor|corvid|nightjar)[\w.-]*", re.I)
EMP_ID = re.compile(r"\be\d\d\b", re.I)


def lint_text(s: str) -> list[str]:
    low = (s or "").lower()
    problems = [f"forbidden phrase: {p!r}" for p in FORBIDDEN if p in low]
    if RIVAL_ADDR.search(s or "") and EMP_ID.search(s or ""):
        problems.append("rival contact address together with an employee id")
    return problems


def lint_messages(msgs: list[dict]) -> list[str]:
    out = []
    for m in msgs:
        for p in lint_text(f"{m.get('subject', '')}\n{m.get('body', '')}"):
            out.append(f"{m.get('id')}: {p}")
    return out
