"""Calibration sweep (HEAD-ENV / bayes-solver). uv run python -m canary.solver.sweep [--seeds 200]"""
from __future__ import annotations

import argparse
import json

from .bench import run

AGENTS = ["solver", "heuristic", "obvious_heuristic", "logs_only", "random", "stop_early"]


def evaluate(tier, ov, seeds, procs):
    res = run([tier], AGENTS, range(seeds), procs, overrides={tier: ov})
    return {a: dict(score=round(res[(tier, a)][0], 3), acc=round(res[(tier, a)][2], 3)) for a in AGENTS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--tier", default="medium")
    ap.add_argument("--grid", required=True, help="JSON list of override dicts")
    a = ap.parse_args()
    for ov in json.loads(a.grid):
        r = evaluate(a.tier, {k: tuple(v) if isinstance(v, list) else v for k, v in ov.items()}, a.seeds, a.procs)
        s = r["solver"]["score"]
        print(json.dumps(ov), "|", " ".join(f"{k}={v['score']:.3f}/{v['acc']:.0%}" for k, v in r.items()),
              f"| heur/solver={r['heuristic']['score'] / s if s else float('nan'):.2f}", flush=True)


if __name__ == "__main__":
    main()
