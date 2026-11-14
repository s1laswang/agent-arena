"""Frozen-tier table on FRESH dev seeds (not used for tuning). Usage: python scripts/fresh_table.py 1000 1400"""
import statistics, sys
from multiprocessing import Pool
from canary.env import Env
from canary.solver.policy import SolverPolicy
from canary.baselines import BASELINES, CALIBRATION_POLICIES

AGENTS = {"solver": lambda s: SolverPolicy(), **{k: (lambda c: lambda s: c(seed=s))(v) for k, v in
          {**CALIBRATION_POLICIES, **{k: BASELINES[k] for k in ("obvious_heuristic", "random", "stop_early", "do_nothing") if k in BASELINES}}.items()}}
def run(job):
    tier, name, s = job
    env = Env(tier, s); p = AGENTS[name](s); p.reset(env.tools_spec(), env.instruction())
    while not env.done:
        env.call(*p.act(env.history))
    r = env.result(name)
    return tier, name, r.score, r.correct, r.accused is not None
if __name__ == "__main__":
    a, b = int(sys.argv[1]), int(sys.argv[2])
    jobs = [(t, n, s) for t in ("easy", "medium", "hard") for n in AGENTS for s in range(a, b)]
    with Pool(6) as pool:
        res = pool.map(run, jobs, chunksize=20)
    print(f"seeds {a}-{b-1} (n={b-a})\n| tier | agent | score ±95% | acc | accused |\n|---|---|---|---|---|")
    for t in ("easy", "medium", "hard"):
        for n in AGENTS:
            r = [x for x in res if x[0] == t and x[1] == n]
            sc = [x[2] for x in r]; ci = 1.96 * statistics.pstdev(sc) / len(sc) ** 0.5
            print(f"| {t} | {n} | {statistics.mean(sc):.3f} ± {ci:.3f} | {sum(x[3] for x in r)/len(r):.1%} | {sum(x[4] for x in r)/len(r):.1%} |")
