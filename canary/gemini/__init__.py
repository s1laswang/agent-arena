"""Canary Lab: the Gemini-specific layer on top of Canary (Google DeepMind "Best Use of Gemini API").

Additive package: nothing in the judge path (env, reward, reproduce) imports it.

    from canary.gemini import lab_client, record, ledger_path
    c = lab_client("gemini:gemini-3.8-flash", feature="ladder", thinking_level="low")
    r = c.chat(messages, tools=...)          # same LLMClient interface as canary.llm; every call is ledgered
    record(feature="atlas", model="gemini-4-carbon", kind="cache", usage=resp.usage_metadata, latency_s=1.2)

Modules (owners in docs/gemini/TEAM.md): ledger (this), gateway, ladder, atlas, swarm, dashboard, narrate.
"""
from .ledger import LedgeredClient, lab_client, ledger_path, read_ledger, record

__all__ = ["LedgeredClient", "lab_client", "ledger_path", "read_ledger", "record"]
