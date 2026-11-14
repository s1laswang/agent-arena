"""Spread of `make reproduce` across fresh judge-world secrets (the README's "Expected numbers" table).

    uv run python scripts/repro_spread.py            # 30 keyless runs, all judge seeds (about 5 min)
    uv run python scripts/repro_spread.py 5 --seeds 5   # quick look

Each run is one keyless `make reproduce`: one fresh random secret shared by every agent in that run
(paired). For every (tier, agent) we print the mean of the K run means and their [min, max] range,
which is exactly how the README table is built. CANARY_WORLD_SECRET must be unset, because with a fixed
secret every run is identical and the spread is zero.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from collections import defaultdict

from canary import reproduce as R


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="?", type=int, default=30, help="number of fresh-secret runs (default 30)")
    ap.add_argument("--seeds", type=int, default=None, help="judge seeds per tier (default: all)")
    a = ap.parse_args(argv)
    if os.environ.get("CANARY_WORLD_SECRET"):
        print("repro_spread: unset CANARY_WORLD_SECRET; with a fixed secret every run is identical", file=sys.stderr)
        return 2

    means: dict[tuple[str, str], list[float]] = defaultdict(list)
    for i in range(a.runs):
        with tempfile.TemporaryDirectory() as d:
            out = R.reproduce(a.seeds, d, quiet=True)
        for r in out["rows"]:
            if not r.pending and r.kind != "reported":  # paired rows only (replayed agent runs share agent names)
                means[(r.tier, r.agent)].append(R.mean(r.scores))
        print(f"run {i + 1}/{a.runs} done", file=sys.stderr)

    tiers = [t for t in R.TIER_ORDER if any(k[0] == t for k in means)]
    agents = [ag for ag in R.REPRO_AGENTS if any(k[1] == ag for k in means)]
    print(f"| agent | {' | '.join(tiers)} |")
    print("|---|" + "---:|" * len(tiers))
    for ag in agents:
        cells = []
        for t in tiers:
            ms = means.get((t, ag), [])
            cells.append(f"{sum(ms) / len(ms):+.2f} [{min(ms):+.2f}, {max(ms):+.2f}]" if ms else "–")
        print(f"| {ag} | {' | '.join(cells)} |")
    print(f"\n{a.runs} runs, {a.seeds or 'all'} judge seeds per tier, a fresh secret per run.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
