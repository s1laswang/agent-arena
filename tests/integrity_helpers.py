"""Shared helpers for tests/test_integrity*.py (owner: HEAD-INTEGRITY).

Integrity tests are written against the CONTRACT before Env exists. `make_env` skips the
test while canary.env.Env is still the NotImplementedError stub, so tests switch on
automatically the moment HEAD-ENV merges the real engine.
"""
from __future__ import annotations

import pytest


def make_env(tier: str = "easy", seed: int = 0, **kw):
    from canary.env import Env
    try:
        return Env(tier=tier, seed=seed, **kw)
    except NotImplementedError:
        pytest.skip("canary.env.Env not implemented yet (HEAD-ENV)")


def true_mole(env) -> str:
    """Server-side truth for tests only. Tries the ledger/world without assuming one layout."""
    for attr in ("world", "_world"):
        w = getattr(env, attr, None)
        if w is not None:
            for name in ("mole", "mole_id"):
                if hasattr(w, name):
                    return getattr(w, name)
    raise AssertionError("cannot find mole on env.world; ask HEAD-ENV for env.world.mole")
