"""Confirm a co-tune cell on fresh dev seeds: solver on medium + hard, paired medium-hard CI.

  python fr8/confirm_cell.py --hard-fp 1.0 --hard-framing 3.0 --bw 0.6 --seeds 200-999
"""
import argparse, dataclasses, math, os
from multiprocessing import Pool
def run(args):
    tier, s = args
    from canary import rules
    from canary.env import Env
    from canary.solver.policy import SolverPolicy
    from fr8.j1_grid import run as r1
    if tier == "hard":
        rules.TIERS["hard"] = dataclasses.replace(rules.TIERS["hard"], fingerprint_accuracy=float(os.environ["CC_FP"]), framing_rate=float(os.environ["CC_FR"]))
    r = r1(Env(tier=tier, seed=s), SolverPolicy(behaviour_weight=float(os.environ["CC_BW"])), "solver")
    return tier, s, r.score, int(r.correct), int(r.accused is None)
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--hard-fp", default="1.0"); ap.add_argument("--hard-framing", default="3.0")
    ap.add_argument("--bw", default="0.6"); ap.add_argument("--seeds", default="200-999")
    a = ap.parse_args()
    os.environ.update(CC_FP=a.hard_fp, CC_FR=a.hard_framing, CC_BW=a.bw)
    lo, hi = map(int, a.seeds.split("-")); seeds = range(lo, hi + 1)
    with Pool(3) as p:
        out = p.map(run, [(t, s) for t in ("medium", "hard") for s in seeds], chunksize=20)
    d = {t: {s: (sc, c, n) for tt, s, sc, c, n in out if tt == t} for t in ("medium", "hard")}
    for t in d:
        v = list(d[t].values()); n = len(v)
        acc = sum(x[1] for x in v) / n; m = sum(x[0] for x in v) / n
        sd = math.sqrt(sum((x[0] - m) ** 2 for x in v) / (n - 1))
        print(t, "n", n, "mean %.3f ± %.3f" % (m, 1.96 * sd / n**.5), "acc %.3f ± %.3f" % (acc, 1.96 * math.sqrt(acc * (1 - acc) / n)), "none %.3f" % (sum(x[2] for x in v) / n))
    diff = [d["medium"][s][0] - d["hard"][s][0] for s in seeds]; m = sum(diff) / len(diff)
    sd = math.sqrt(sum((x - m) ** 2 for x in diff) / (len(diff) - 1))
    print("medium-hard paired %.3f ± %.3f" % (m, 1.96 * sd / len(diff) ** .5))
