"""Bench the solver vs baselines on dev seeds (real canary.env.Env).

    uv run python -m canary.solver.bench --seeds 200 [--tiers easy,medium,hard] [--procs 6]
          [--agents solver,heuristic,...] [--random-moles]   # random DSL mole per seed
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import time
from multiprocessing import Pool

DEFAULT_AGENTS = "solver,heuristic,obvious_heuristic,logs_only,random,stop_early,do_nothing"


def _run_local(env, policy, max_calls=400):
    """Private runner (canary.eval.run_episode is HARNESS's)."""
    policy.reset(env.tools_spec(), env.instruction())
    n = 0
    while not env.done and n < max_calls:
        tool, args = policy.act(list(env.history))
        env.call(tool, args)
        n += 1
    return env.result(policy.name)


def make_policy(agent: str, seed: int, **kw):
    from .policy import SolverPolicy
    if agent == "solver":
        return SolverPolicy(None, **kw)
    from ..baselines import BASELINES, CALIBRATION_POLICIES
    cls = BASELINES.get(agent) or CALIBRATION_POLICIES[agent]
    return cls(seed=seed)


def make_env(tier, seed, random_mole=False):
    from ..env import Env
    strat = None
    if random_mole:
        from ..mole.dsl import random_strategy
        strat = random_strategy(random.Random(f"bench-mole:{seed}"))
    return Env(tier, seed, mole_strategy=strat)


def _one(job):
    tier, agent, seed, random_mole, kw = job
    r = _run_local(make_env(tier, seed, random_mole), make_policy(agent, seed, **kw))
    return (tier, agent, r.score, r.correct, r.final_day if r.end_reason == "accused" else None)


def summarize(rows):
    sc = [x[2] for x in rows]
    m = statistics.mean(sc)
    ci = 1.96 * statistics.pstdev(sc) / math.sqrt(len(sc)) if len(sc) > 1 else 0.0
    acc = sum(x[3] for x in rows) / len(rows)
    days = [x[4] for x in rows if x[4] is not None]
    return m, ci, acc, (statistics.mean(days) if days else float("nan")), len(days) / len(rows)


def run(tiers, agents, seeds, procs=6, random_mole=False, **kw):
    jobs = [(t, a, s, random_mole, kw) for t in tiers for a in agents for s in seeds]
    with Pool(procs) as pool:
        res = pool.map(_one, jobs, chunksize=8)
    out = {}
    for r in res:
        out.setdefault((r[0], r[1]), []).append(r)
    return {k: summarize(v) for k, v in out.items()}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--agents", default=DEFAULT_AGENTS)
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--random-moles", action="store_true")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--btemper", type=float, default=None)
    ap.add_argument("--ctemper", type=float, default=None)
    a = ap.parse_args(argv)
    kw = {k: v for k, v in dict(threshold=a.threshold, behaviour_temper=a.btemper,
                                choice_temper=a.ctemper).items() if v is not None}
    t0 = time.time()
    tiers, agents = a.tiers.split(","), a.agents.split(",")
    res = run(tiers, agents, range(a.seeds), a.procs, a.random_moles, **kw)
    print("| tier | agent | acc | accused | score | ±95% | day |\n|---|---|---|---|---|---|---|")
    for t in tiers:
        for ag in agents:
            m, ci, acc, d, fa = res[(t, ag)]
            print(f"| {t} | {ag} | {acc:.1%} | {fa:.0%} | {m:.3f} | {ci:.3f} | {d:.1f} |")
    print(f"# {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
