"""TextProvider: turns PUBLIC day facts + mechanic signal labels into realistic company text.

Owner: HEAD-ENV (engineer: world-text). Gemini backend wiring: HEAD-AGENTS (llm-providers).

INTEGRITY RULE: providers never receive the mole's identity. Input is a PublicDayFacts object
(employees, roles, published docs, and signal labels chosen by the env from the rules, e.g.
interview_answer="evasive"|"cooperative", decoy_mood="angry"). The env decides signals; the
provider only renders words. That is what makes Gemini text safe to freeze for judging.

    class TextProvider(Protocol):
        name: str                                   # "template" | "gemini:<model>"
        def day_messages(self, facts) -> list[dict] # {id, day, channel, sender, recipients, subject, body}
        def interview_answer(self, facts, employee: str, topic: str, signal: str) -> str

Cache: data/worlds/<tier>/<seed>.text.json; judge seeds committed under data/worlds/judge/.
`make worlds PROVIDER=gemini` regenerates text for judge seeds; mechanics are unchanged.
"""
