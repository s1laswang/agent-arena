"""Shared data contracts. Changing anything here = contract change (see docs/CONTRACT.md)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

ToolName = Literal[
    "status", "list_employees", "list_documents",
    "read_access_logs", "search_messages", "read_message",
    "interview", "plant_canary", "check_leak_feed",
    "restrict_access", "unrestrict_access", "advance_day", "accuse",
]

# Tools that consume one of the per-day action slots.
INVESTIGATIVE_TOOLS: frozenset[str] = frozenset({
    "read_access_logs", "search_messages", "read_message",
    "interview", "plant_canary", "check_leak_feed",
    "restrict_access", "unrestrict_access",
})

InterviewTopic = Literal["recent_documents", "contacts_outside", "workload", "access_needs"]


@dataclass
class ToolResult:
    ok: bool
    data: dict[str, Any]
    error: str | None = None


@dataclass
class Step:
    t: int                      # global tool-call index
    day: int
    tool: str
    args: dict[str, Any]
    result: dict[str, Any]      # exactly what the agent saw (ToolResult as dict)


@dataclass
class LedgerEntry:
    """Server-side only. Never exposed through MCP tools."""
    t: int
    day: int
    event: str                  # "leak", "leak_surfaced", "canary_planted", "restricted", "accused", "episode_end", ...
    detail: dict[str, Any]


@dataclass
class EpisodeResult:
    """One episode = one JSON line in data/runs/<run_id>/episodes.jsonl.

    Shared by eval, regret attribution, failure tagging and SFT export. Do not fork it.
    """
    tier: str
    seed: int
    agent: str                  # "solver", "do_nothing", "stop_early", "random", "openai:<model>", "gemini:<model>", ...
    steps: list[Step]
    score: float                # V at accusation if correct else 0.0
    accused: str | None
    correct: bool
    final_day: int
    end_reason: str             # "accused" | "horizon" | "tool_cap" | "error"
    meta: dict[str, Any] = field(default_factory=dict)


class Policy(Protocol):
    """Anything that plays the investigator through the PUBLIC tool interface only."""
    name: str
    def reset(self, tools_spec: list[dict], instruction: str) -> None: ...
    def act(self, history: list[Step]) -> tuple[str, dict[str, Any]]: ...
