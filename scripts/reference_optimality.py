"""Reference (solver) optimality analysis on v1.4: calibration, loss decomposition, stopping-rule sweep,
information-rate numbers. DIAGNOSIS ONLY: reads env internals (mole, true V) offline to grade; the solver itself
is run unchanged. Tuning/dev seeds only.

    uv run --python 3.12 --extra dev python scripts/reference_optimality.py --tier hard --seed0 8000 --seeds 400
"""
from __future__ import annotations

import argparse
import collections
import statistics as st
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _traj(job):
    """Solver with stopping disabled (threshold > 1; the canary plan does not depend on the threshold, so any
    stopping rule can be replayed offline). Per decide point: (day, pmax, argmax==mole, true V, canaries so far,
    leaks so far, regular docs the mole could leak today)."""
    from canary.solver.bench import make_env
    from canary.solver.policy import SolverPolicy
    tier, s = job
    env = make_env(tier, s)
    p = SolverPolicy(None, threshold=1.01)
    p.reset(env.tools_spec(), env.instruction())
    mole, rows, n = env._world.mole, [], 0
    while not env.done and n < 1000:
        tool, args = p.act(list(env.history))
        if p.trace and (not rows or rows[-1][0] != p.trace[-1]["day"]):
            post = p.trace[-1]["post"]
            b = max(post, key=post.get)
            d = p.trace[-1]["day"]
            nc = sum(1 for x in env.history if x.tool == "plant_canary" and (x.result or {}).get("ok", True))
            reg = sum(1 for doc in p.obs.docs.values() if not doc.is_canary and mole in doc.recipients
                      and d - env.p.leak_window_days + 1 <= doc.day <= d)
            pend_c = sum(1 for doc in p.obs.docs.values() if doc.is_canary and mole in doc.recipients
                         and d - env.p.leak_window_days + 1 <= doc.day <= d)
            rows.append((d, post[b], b == mole, env.V, nc, reg, pend_c))
        if tool == "accuse":
            break
        env.call(tool, args)
        n += 1
    return rows


def replay(R, rule, W=-1.0):
    out = []
    for rows in R:
        res = ("abstain", 0.0, None, None)
        for i, (d, p, c, V, nc, reg, pc) in enumerate(rows):
            if rule(d, p, V, i == len(rows) - 1) and p * V + (1 - p) * W > 0:
                res = ("correct" if c else "wrong", V if c else W, p, nc)
                break
        out.append(res)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seed0", type=int, default=8000)
    ap.add_argument("--seeds", type=int, default=400)
    ap.add_argument("--procs", type=int, default=2)
    a = ap.parse_args(argv)
    from canary.rules import TIERS
    P = TIERS[a.tier]
    thr = {"hard": 0.85}.get(a.tier, 0.9)
    with Pool(a.procs) as pool:
        R = pool.map(_traj, [(a.tier, s) for s in range(a.seed0, a.seed0 + a.seeds)])
    n = len(R)
    base = replay(R, lambda d, p, V, last: p >= thr or last)
    sc = [x[1] for x in base]
    print(f"## {a.tier}: seeds {a.seed0}-{a.seed0 + n - 1}, n={n}, solver default threshold {thr}\n")
    print(f"mean score {st.mean(sc):.3f}")
    # 1. calibration at accusation
    bins = collections.defaultdict(list)
    for kind, s, p, _ in base:
        if p is not None:
            bins[min(0.95, int(p * 20) / 20)].append(kind == "correct")
    print("\n### Calibration at accusation\n\n| posterior bin | n | empirical accuracy |\n|---|---|---|")
    for k in sorted(bins):
        print(f"| {k:.2f}-{k + 0.05:.2f} | {len(bins[k])} | {st.mean(bins[k]):.3f} |")
    allb = collections.defaultdict(list)
    for rows in R:
        for (d, p, c, *_r) in rows:
            allb[min(0.9, int(p * 10) / 10)].append(c)
    print("\n### Calibration over all decision days (top suspect)\n\n| bin | n | P(top = mole) |\n|---|---|---|")
    for k in sorted(allb):
        print(f"| {k:.1f}-{k + 0.1:.1f} | {len(allb[k])} | {st.mean(allb[k]):.3f} |")
    # 2. loss decomposition (1.0 - mean score)
    can = st.mean([x[3] * P.canary_cost if x[3] is not None else 0 for x in base])
    wrong = [x for x in base if x[0] == "wrong"]
    abst = [x for x in base if x[0] == "abstain"]
    wrong_loss = sum(1.0 - x[1] for x in wrong) / n          # vs V=1: gives up V and pays the penalty
    abst_loss = len(abst) / n
    cor = [x for x in base if x[0] == "correct"]
    leak = sum(1.0 - x[1] - x[3] * P.canary_cost for x in cor) / n
    print(f"\n### Loss decomposition (1 - mean score = {1 - st.mean(sc):.3f})\n")
    print("| bucket | loss | note |\n|---|---|---|")
    print(f"| canary cost (correct accusations) | {sum(x[3] * P.canary_cost for x in cor) / n:.3f} | mean canaries {st.mean(x[3] for x in cor):.1f} |")
    print(f"| leak damage (+ restrictions) before a correct accusation | {leak:.3f} | |")
    print(f"| wrong accusations | {wrong_loss:.3f} | {len(wrong)}/{n} episodes, each 1 - ({P.wrong_accusation_score:g}) = full loss |")
    print(f"| abstains (score 0) | {abst_loss:.3f} | {len(abst)}/{n} episodes |")
    print(f"| canary cost, all episodes (for reference) | {can:.3f} | |")
    # 3. stopping sweep
    print("\n### Stopping-rule sweep (same trajectories)\n\n| rule | mean | Δ vs default |\n|---|---|---|")
    m0 = st.mean(sc)
    for t in (0.6, 0.7, 0.8, 0.85, 0.9, 0.95):
        m = st.mean(x[1] for x in replay(R, lambda d, p, V, l, t=t: p >= t or l))
        print(f"| p ≥ {t} | {m:.3f} | {m - m0:+.3f} |")
    best = max(((st.mean(x[1] for x in replay(R, lambda d, p, V, l, a_=a_, b_=b_: p >= a_ + b_ * V or l))), a_, b_)
               for a_ in [x / 100 for x in range(50, 100, 5)] for b_ in [x / 100 for x in range(-40, 41, 10)])
    print(f"| best p ≥ a + b·V (grid a 0.50..0.95, b -0.4..0.4) a={best[1]} b={best[2]} | {best[0]:.3f} | {best[0] - m0:+.3f} |")
    orc = st.mean(max([r[3] for r in rows if r[2]] + [0.0]) for rows in R)
    print(f"| oracle stop (knows the mole; upper bound, not achievable) | {orc:.3f} | {orc - m0:+.3f} |")
    # 4. information rate
    regs = [r[5] for rows in R for r in rows if r[0] >= 3]
    pcs = [r[6] for rows in R for r in rows if r[0] >= 3]
    print("\n### Information rate (days ≥ 3, all decision days)\n")
    print(f"- regular docs the mole can leak on a given day: mean {st.mean(regs):.2f}")
    print(f"- our canaries the mole holds in its leak window: mean {st.mean(pcs):.2f}")
    print(f"- p_leak {P.p_leak}, canaries/day {P.canaries_per_day}, variants {P.max_variants}, delays {P.delay_choices}, "
          f"careful mole {P.careful_mole}")


if __name__ == "__main__":
    main()
