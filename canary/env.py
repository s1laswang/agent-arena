"""Env: the one public entrypoint for every investigator (solver, baselines, LLM agents, MCP).

Owner: HEAD-ENV (engineer: sim-engine). Contract (do not change signatures without CONTRACT.md):

    env = Env(tier="medium", seed=42, text_provider=None)   # None -> TemplateProvider
    env.tools_spec() -> list[dict]          # JSON-schema tool specs (MCP server mirrors these 1:1)
    env.instruction() -> str                # rules in plain words (same text as instruction.md)
    env.call(tool, args) -> ToolResult      # validates args, enforces per-day + global caps, accuse lock
    env.done -> bool
    env.score() -> float                    # 0.0 until a correct accusation; server-side
    env.ledger() -> list[LedgerEntry]       # server-side truth log; NEVER exposed to agents
    env.history -> list[Step]               # what the agent saw
    env.result(agent_name) -> EpisodeResult

Integrity rules (INTEGRITY head will attack these):
  * the mole id lives only in the private World object; no tool result may contain it
  * accuse() works exactly once; any call after done returns ok=False and changes nothing
  * strict arg validation: unknown ids, lists, wildcards -> ok=False (still counts toward the cap)
  * determinism: same (tier, seed, action sequence) -> identical results and ledger
"""
from __future__ import annotations

from .types import EpisodeResult, LedgerEntry, Step, ToolResult


class Env:
    def __init__(self, tier: str, seed: int, text_provider=None):
        raise NotImplementedError("HEAD-ENV / sim-engine")

    def tools_spec(self) -> list[dict]: ...
    def instruction(self) -> str: ...
    def call(self, tool: str, args: dict) -> ToolResult: ...
    @property
    def done(self) -> bool: ...
    def score(self) -> float: ...
    def ledger(self) -> list[LedgerEntry]: ...
    @property
    def history(self) -> list[Step]: ...
    def result(self, agent_name: str) -> EpisodeResult: ...
