"""Shared pytest setup.

canary.mcp_server serves only judge/held-out seeds unless CANARY_ALLOW_DEV=1 (INTEGRITY #23/#24).
Tests compare the served world with an in-process Env on public dev seeds, so they opt in here.
Tests that check the refusal remove the variable from their subprocess environment explicitly.
"""
import os

os.environ.setdefault("CANARY_ALLOW_DEV", "1")
