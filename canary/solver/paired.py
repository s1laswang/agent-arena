"""Paired comparison of two solver-family agents on the same seeds (real canary.env.Env).

    uv run python -m canary.solver.paired --tiers medium,hard --seed0 9000 --seeds 400 [--a solver --b solver_v2]
"""
from __future__ import annotations

import argparse
import math
import statistics as st
from multiprocessing import Pool

from .bench import _run_local, make_env, make_policy


def _one(job):
    tier, agent, seed = job
    r = _run_local(make_env(tier, seed), make_policy(agent, seed))
    return r.score, bool(r.correct), r.end_reason == "accused"


def _ci(x):
    return 1.96 * st.pstdev(x) / math.sqrt(len(x))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="medium,hard")
    ap.add_argument("--seed0", type=int, default=9000)
    ap.add_argument("--seeds", type=int, default=400)
    ap.add_argument("--a", default="solver")
    ap.add_argument("--b", default="solver_v2")
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args(argv)
    seeds = range(a.seed0, a.seed0 + a.seeds)
    print(f"seeds {a.seed0}-{a.seed0 + a.seeds - 1} (n={a.seeds})")
    print("| tier | agent | mean ± 95% CI | acc when accusing | abstain | paired Δ (b−a) ± 95% CI |\n|---|---|---|---|---|---|")
    with Pool(a.procs) as pool:
        for t in a.tiers.split(","):
            res = {ag: pool.map(_one, [(t, ag, s) for s in seeds], chunksize=8) for ag in (a.a, a.b)}
            d = [y[0] - x[0] for x, y in zip(res[a.a], res[a.b])]
            for ag in (a.a, a.b):
                R = res[ag]
                sc = [r[0] for r in R]
                nacc = sum(r[2] for r in R)
                acc = sum(r[1] for r in R) / max(1, nacc)
                delta = f"{st.mean(d):+.3f} ± {_ci(d):.3f}" if ag == a.b else ""
                print(f"| {t} | {ag} | {st.mean(sc):.3f} ± {_ci(sc):.3f} | {acc:.1%} | {1 - nacc / len(R):.1%} | {delta} |",
                      flush=True)


if __name__ == "__main__":
    main()
