"""Bench the solver vs baselines on dev seeds.

    uv run python -m canary.solver.bench --seeds 200 [--tiers easy,medium,hard] [--sim]
"""
from __future__ import annotations

import argparse
import math
import random
import statistics
import time

from ..rules import TIERS


def _make_env(tier, seed, sim):
    if not sim:
        try:
            from ..env import Env
            return Env(tier, seed)
        except NotImplementedError:
            pass
    from ._sim import SimEnv
    return SimEnv(tier, seed)


def _run_local(env, policy, max_calls=400):
    """Private runner (canary.eval.run_episode is HARNESS's)."""
    policy.reset(env.tools_spec(), env.instruction())
    n = 0
    while not env.done and n < max_calls:
        tool, args = policy.act(env.history)
        env.call(tool, args)
        n += 1
    return env.result(policy.name)


class _Scripted:
    """do_nothing / stop_early / random baselines expressed as policies."""
    def __init__(self, kind, seed):
        self.name, self.kind, self.rng = kind, kind, random.Random(f"base:{kind}:{seed}")

    def reset(self, spec, instr):
        self.emps, self.day_acc = None, None

    def act(self, history):
        if self.emps is None:
            if not history or history[-1].tool != "list_employees":
                return "list_employees", {}
            from .policy import _items
            self.emps = [e["id"] for e in _items(history[-1].result["data"], "employees")]
            self.day_acc = {"do_nothing": 10**9, "stop_early": 1}.get(self.kind) or self.rng.randint(1, 14)
        day = history[-1].day if history else 1
        if day >= self.day_acc:
            return "accuse", {"employee": self.rng.choice(self.emps)}
        return "advance_day", {}


def stats(rs):
    sc = [r.score for r in rs]
    m = statistics.mean(sc)
    ci = 1.96 * statistics.pstdev(sc) / math.sqrt(len(sc)) if len(sc) > 1 else 0.0
    acc = sum(r.correct for r in rs) / len(rs)
    days = [r.final_day for r in rs if r.end_reason == "accused"]
    return m, ci, acc, (statistics.mean(days) if days else float("nan"))


def main(argv=None):
    from .policy import SolverPolicy
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--sim", action="store_true", help="force the private SimEnv")
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--btemper", type=float, default=0.3)
    ap.add_argument("--no-none-group", action="store_true")
    a = ap.parse_args(argv)
    print(f"{'tier':7s} {'agent':11s} {'acc':>6s} {'score':>7s} {'±95%':>6s} {'day':>5s}")
    for tier in a.tiers.split(","):
        t0 = time.time()
        rows = {}
        rows["solver"] = [_run_local(_make_env(tier, s, a.sim),
                                     SolverPolicy(None, threshold=a.threshold, behaviour_temper=a.btemper,
                                                  none_group=not a.no_none_group))
                          for s in range(a.seeds)]
        for k in ("do_nothing", "stop_early", "random"):
            rows[k] = [_run_local(_make_env(tier, s, a.sim), _Scripted(k, s)) for s in range(a.seeds)]
        for k, rs in rows.items():
            m, ci, acc, d = stats(rs)
            print(f"{tier:7s} {k:11s} {acc:6.1%} {m:7.3f} {ci:6.3f} {d:5.1f}")
        print(f"# {tier}: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
