"""Tiny deterministic fallback TextProvider (used only if TemplateProvider is unavailable)."""
from __future__ import annotations

import random

from .facts import PublicDayFacts


class MinimalProvider:
    name = "minimal"

    def day_messages(self, facts: PublicDayFacts) -> list[dict]:
        rng = random.Random(f"{facts.tier}:{facts.seed}:msg:{facts.day}")
        ids = [e.id for e in facts.employees]
        out = []
        for k in range(1, 4):
            s = rng.choice(ids)
            out.append({"id": f"m{facts.day}-{k}", "day": facts.day, "channel": "general", "sender": s,
                        "recipients": ["all"], "subject": f"Day {facts.day} update",
                        "body": f"Status update from {s} at {facts.company}."})
        if facts.decoy and facts.decoy_mood == "angry":
            out.append({"id": f"m{facts.day}-4", "day": facts.day, "channel": "general", "sender": facts.decoy,
                        "recipients": ["all"], "subject": "Frustrated",
                        "body": "I am fed up with how management treats us here."})
        return out

    def interview_answer(self, facts: PublicDayFacts, employee: str, topic: str, signal: str) -> str:
        if signal == "evasive":
            return f"I'd rather not get into {topic.replace('_', ' ')} right now."
        return f"Happy to help. On {topic.replace('_', ' ')}: nothing unusual, ask me anything."
