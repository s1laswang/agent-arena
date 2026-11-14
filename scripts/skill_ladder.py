"""Skill ladder: each rung removes ONE component of the reference solver; paired deltas vs full solver.

    uv run --python 3.12 --extra dev --extra llm --extra plot python scripts/skill_ladder.py \
        --tiers medium,hard --seed0 7000 --n 400 --procs 2

Writes results/skill_ladder_v1.4.{md,png,csv}. Rules frozen at v1.4; fresh dev seeds only.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from canary.solver.ablation import ABLATIONS  # noqa: E402

BASELINES = ("heuristic", "grok_tactics", "do_nothing")
RUNGS = ("solver",) + tuple(f"solver-{a}" for a in ABLATIONS) + BASELINES
DESC = {
    "solver": "full reference solver",
    "solver-accuse_last": "no EV rule: accuse argmax on last day",
    "solver-accuse_p50": "no EV rule: accuse when P>=0.5",
    "solver-no_careful": "belief ignores careful mole",
    "solver-no_delay": "belief assumes min delay",
    "solver-single_canary": "1 canary/day (multi=off)",
    "solver-no_decoy": "no decoy search/marginalisation",
    "solver-no_framing": "belief ignores framing",
    "heuristic": "baseline: heuristic",
    "grok_tactics": "baseline: grok_tactics",
    "do_nothing": "baseline: do-nothing",
}


def make_policy(agent: str, seed: int):
    if agent.startswith("solver"):
        from canary.solver.ablation import AblatedSolver
        return AblatedSolver(None, ablation=agent.split("-", 1)[1] if "-" in agent else None)
    from canary.solver.bench import make_policy as mp
    return mp(agent, seed)


def run_one(job):
    tier, agent, seed = job
    from canary.solver.bench import _run_local, make_env
    r = _run_local(make_env(tier, seed), make_policy(agent, seed))
    acc = r.end_reason == "accused"
    return {"tier": tier, "agent": agent, "seed": seed, "score": float(r.score),
            "correct": int(bool(r.correct)), "accused": int(acc), "final_day": r.final_day}


def ci95(xs):
    return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def summarise(rows, tiers, rungs):
    by = {(r["tier"], r["agent"], r["seed"]): r for r in rows}
    out = []
    for t in tiers:
        seeds = sorted({r["seed"] for r in rows if r["tier"] == t})
        ref = [by[(t, "solver", s)]["score"] for s in seeds]
        for a in rungs:
            rs = [by[(t, a, s)] for s in seeds]
            sc = [r["score"] for r in rs]
            accd = [r for r in rs if r["accused"]]
            d = [x - y for x, y in zip(sc, ref)]
            out.append(dict(tier=t, agent=a, n=len(rs), mean=statistics.mean(sc), ci=ci95(sc),
                            acc=(sum(r["correct"] for r in accd) / len(accd)) if accd else float("nan"),
                            abstain=1 - len(accd) / len(rs), delta=statistics.mean(d), dci=ci95(d)))
    return out


def write_md(path, summ, args, cmd, secs):
    L = ["# Skill ladder (rules v1.4)", "",
         "Each `solver-*` rung removes exactly ONE component of the reference `SolverPolicy`",
         "(`canary/solver/ablation.py`; the reference class itself is untouched). Delta = paired mean",
         "difference vs the full solver on the SAME seeds, with a paired 95% CI (1.96·sd/√n).", "",
         f"- Seeds: fresh dev seeds {args.seed0}–{args.seed0 + args.n - 1} (n={args.n} per tier), "
         "default env mole, no judge seeds.",
         f"- Command: `{cmd}`", f"- Runtime: {secs/60:.1f} min on {args.procs} processes.",
         "- Accuracy = correct / accused episodes. Abstain = episodes ending without an accusation (score 0 + damage-free).", ""]
    for t in sorted({s["tier"] for s in summ}, key=["easy", "medium", "hard"].index):
        L += [f"## {t}", "", "| rung | what is removed | mean score | ±95% | Δ vs full | Δ ±95% | acc (accused) | abstain |",
              "|---|---|---|---|---|---|---|---|"]
        for s in summ:
            if s["tier"] != t:
                continue
            flag = ""
            if s["agent"] != "solver" and s["delta"] + s["dci"] >= 0:
                flag = " ⚑"
            L.append(f"| {s['agent']}{flag} | {DESC[s['agent']]} | {s['mean']:.3f} | {s['ci']:.3f} | "
                     f"{s['delta']:+.3f} | {s['dci']:.3f} | {s['acc']:.1%} | {s['abstain']:.1%} |")
        L.append("")
    L += ["⚑ = paired 95% CI of the delta includes 0 or is positive (rung not shown to cost score).", ""]
    Path(path).write_text("\n".join(L))


def plot(path, summ):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    tiers = sorted({s["tier"] for s in summ}, key=["easy", "medium", "hard"].index)
    fig, axes = plt.subplots(1, len(tiers), figsize=(6 * len(tiers), 5.5), squeeze=False)
    for ax, t in zip(axes[0], tiers):
        ss = [s for s in summ if s["tier"] == t]
        names = [s["agent"].replace("solver-", "−") for s in ss]
        cols = ["#2b6cb0" if s["agent"] == "solver" else "#e07b39" if s["agent"].startswith("solver") else "#888"
                for s in ss]
        ax.barh(range(len(ss)), [s["mean"] for s in ss], xerr=[s["ci"] for s in ss], color=cols, capsize=3)
        ax.set_yticks(range(len(ss)), names)
        ax.invert_yaxis()
        ax.axvline(0, color="k", lw=0.8)
        ax.set_title(f"{t} (n={ss[0]['n']})")
        ax.set_xlabel("mean score ±95% CI")
    fig.suptitle("Canary v1.4 skill ladder: remove one solver component at a time")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--tiers", default="medium,hard")
    ap.add_argument("--seed0", type=int, default=7000)
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--rungs", default=",".join(RUNGS))
    ap.add_argument("--out", default=str(ROOT / "results" / "skill_ladder_v1.4"))
    a = ap.parse_args(argv)
    if a.seed0 + a.n > 900000:
        raise SystemExit("judge seeds (900000+) are off limits")
    tiers, rungs = a.tiers.split(","), a.rungs.split(",")
    if "solver" not in rungs:
        rungs = ["solver"] + rungs
    jobs = [(t, r, s) for t in tiers for s in range(a.seed0, a.seed0 + a.n) for r in rungs]
    t0 = time.time()
    with Pool(a.procs) as pool:
        rows = pool.map(run_one, jobs, chunksize=4)
    secs = time.time() - t0
    with open(a.out + ".csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summ = summarise(rows, tiers, rungs)
    cmd = ("uv run --python 3.12 --extra dev --extra llm --extra plot python scripts/skill_ladder.py "
           f"--tiers {a.tiers} --seed0 {a.seed0} --n {a.n} --procs {a.procs}")
    write_md(a.out + ".md", summ, a, cmd, secs)
    plot(a.out + ".png", summ)
    print(Path(a.out + ".md").read_text())


if __name__ == "__main__":
    main()
