"""Repro for EXPLOIT H7/H8 (found by codex whitebox hunt, seed 300): rebuild the world from public code.

The attacker calls list_employees, then runs generate_world over candidate seeds with the PUBLIC key
until the roster (names, depts, roles) matches, and reads world.mole. Works for every non-judge seed,
and for judge/held-out seeds whenever the server runs without CANARY_WORLD_SECRET / SALT (fail-open).

    python -m canary.redteam.seed_attack --tier easy --seed 300        # serve-side seed, prints recovered mole
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import random

from canary.rules import TIERS
from canary.world import generate_world
import canary.world as W


def roster(tier: str, seed: int) -> list[tuple]:
    from canary.env import Env
    data = Env(tier=tier, seed=seed).call("list_employees", {}).data
    rows = data["employees"] if isinstance(data, dict) else data
    return [(r["id"], r["name"], r["dept"], r["role"]) for r in rows]


def public_world(tier: str, seed: int):
    """generate_world with the key forced to b'public' (what an attacker can compute)."""
    orig = W.world_seed
    W.world_seed = lambda t, s: int.from_bytes(hmac.new(b"public", f"{t}:{s}".encode(), hashlib.sha256).digest()[:8], "big")
    try:
        return generate_world(tier, seed, TIERS[tier])
    finally:
        W.world_seed = orig


def recover_mole(tier: str, observed: list[tuple], seeds) -> tuple[int, str] | None:
    for s in seeds:
        w = public_world(tier, s)
        if [(e.id, e.name, e.dept, e.role) for e in w.employees] == observed:
            return s, w.mole
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="easy")
    ap.add_argument("--seed", type=int, default=300)
    a = ap.parse_args()
    obs = roster(a.tier, a.seed)
    cands = [a.seed] + list(range(0, 10_000)) + list(range(900_000, 900_030)) + list(range(800_000, 800_200))
    print(recover_mole(a.tier, obs, cands))


if __name__ == "__main__":
    random.seed(0)
    main()
