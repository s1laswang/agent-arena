"""Difficulty curve: solver vs heuristic as evidence noise varies around the medium tier.

    uv run python scripts/difficulty_curve.py [--seeds 2000-2199] [--workers 6] [--extra-runs data/runs/<id>/episodes.jsonl]

Params = canary.rules.apply_noise(TIERS["medium"], noise), installed with `env.p = params` before
the first call (world generation only reads structural fields, which apply_noise does not change).
Writes results/difficulty_curve.csv and results/difficulty_curve.png.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics as st
from multiprocessing import Pool

from canary.baselines import CALIBRATION_POLICIES
from canary.env import Env
from canary.eval import run_episode
from canary.rules import TIERS, apply_noise
from canary.solver.policy import SolverPolicy

NOISES = [0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0]
AGENTS = ("solver", "heuristic")


def one(job):
    noise, agent, seed = job
    params = apply_noise(TIERS["medium"], noise)
    env = Env("medium", seed)
    env.p = params
    pol = SolverPolicy(params=params) if agent == "solver" else CALIBRATION_POLICIES["heuristic"](seed)
    r = run_episode(env, pol)
    return noise, agent, seed, r.score, r.correct, r.accused is not None


def summarize(rows):
    s = [r[0] for r in rows]
    m = st.mean(s)
    ci = 1.96 * st.stdev(s) / math.sqrt(len(s)) if len(s) > 1 else 0.0
    return dict(mean=round(m, 4), ci95=round(ci, 4), acc=round(st.mean(r[1] for r in rows), 4),
                accused=round(st.mean(r[2] for r in rows), 4), n=len(s))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="2000-2199")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--extra-runs", action="append", default=[], help="episodes.jsonl plotted at noise=1")
    ap.add_argument("--out", default="results/difficulty_curve")
    a = ap.parse_args(argv)
    lo, hi = map(int, a.seeds.split("-"))
    jobs = [(n, ag, s) for n in NOISES for ag in AGENTS for s in range(lo, hi + 1)]
    with Pool(a.workers) as pool:
        res = pool.map(one, jobs, chunksize=8)
    groups: dict = {}
    for n, ag, _, sc, ok, acc in res:
        groups.setdefault((n, ag), []).append((sc, ok, acc))
    table = [dict(noise=n, agent=ag, **summarize(groups[(n, ag)])) for n in NOISES for ag in AGENTS]
    for path in a.extra_runs:
        by: dict = {}
        with open(path) as fh:
            for line in fh:
                d = json.loads(line)
                if d.get("tier", "medium") == "medium":
                    by.setdefault(d["agent"], []).append((d["score"], d["correct"], d.get("accused") is not None))
        table += [dict(noise=1.0, agent=ag, **summarize(v)) for ag, v in by.items()]
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out + ".csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["noise", "agent", "mean", "ci95", "acc", "accused", "n"])
        w.writeheader()
        w.writerows(table)
    for r in table:
        print(r)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing; skipped PNG (uv sync --extra plot)")
        return
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for ag in AGENTS:
        rs = [r for r in table if r["agent"] == ag and r["noise"] in NOISES]
        x = [r["noise"] for r in rs]; y = [r["mean"] for r in rs]; c = [r["ci95"] for r in rs]
        ax.plot(x, y, marker="o", label=ag)
        ax.fill_between(x, [u - v for u, v in zip(y, c)], [u + v for u, v in zip(y, c)], alpha=0.2)
    for r in table[len(NOISES) * len(AGENTS):]:
        ax.errorbar([1.0], [r["mean"]], yerr=[r["ci95"]], fmt="s", capsize=4, label=f"{r['agent']} (n={r['n']})")
    ax.axhline(0, color="gray", ls="--", lw=1, label="do-nothing (0)")
    ax.axvline(1.0, color="gray", ls=":", lw=0.8)
    ax.set_xlabel("evidence noise (1 = medium tier)")
    ax.set_ylabel("mean score (95% CI)")
    ax.set_title(f"Canary difficulty curve, medium tier, seeds {a.seeds}")
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(a.out + ".png", dpi=130)


if __name__ == "__main__":
    main()
