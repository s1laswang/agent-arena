"""Track 2 (PLAN-95 reopen): sweep candidate EXPERT tiers = v1.4 hard + overrides of existing, documented knobs.

Each config is registered IN MEMORY as TIERS["expert"] inside each worker (rules.py on disk / the v1.4 hash are
untouched). The solver reads the exact parameter block from the instruction, so it models every knob exactly.

Rungs (paired on the same seeds):
  solver                 full reference solver
  solver-accuse_p50      no EV rule: accuse when P >= 0.5               (canary.solver.ablation)
  solver-accuse_last     no EV rule: accuse argmax on the last day      (canary.solver.ablation)
  never_abstain          full solver, but where it would abstain it accuses its argmax instead
                         (closest proxy for the measured Gemini behaviour: accuses at high P, almost never abstains)
  grok_tactics, heuristic, do_nothing, stop_early   baselines

    uv run python scripts/expert_sweep.py --grid coarse --n 100 --procs 3 --out results/expert_sweep_coarse
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import statistics
import sys
import time
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RUNGS = ("solver", "solver-accuse_p50", "solver-accuse_last", "never_abstain",
         "grok_tactics", "heuristic", "do_nothing", "stop_early")
SEED0 = 60_000  # fresh dev seeds; never judge seeds


def grid(name: str) -> list[dict]:
    if name == "coarse":
        out = []
        for fa, cpd, nd, ld in itertools.product((0.95, 0.8, 0.7), (2, 1), (21, 14), (0.05, 0.07)):
            out.append({"fingerprint_accuracy": fa, "canaries_per_day": cpd, "n_days": nd, "leak_damage": ld})
        return out
    return [json.loads(x) for x in name.split(";")]  # explicit: '{"n_days": 14}; {...}'


def register(ov: dict):
    from canary import rules
    hard = rules.TIERS["hard"]
    ov = {k: (tuple(v) if isinstance(v, list) else v) for k, v in ov.items()}
    rules.TIERS["expert"] = replace(hard, name="expert", **ov)
    return rules.TIERS["expert"]


class NeverAbstain:
    """Full solver; if its action would end the episode without an accusation, accuse its current argmax instead."""
    name = "never_abstain"

    def __init__(self):
        from canary.solver.policy import SolverPolicy
        self.s = SolverPolicy(None)

    def reset(self, tools_spec, instruction):
        self.s.reset(tools_spec, instruction)

    def act(self, history):
        tool, args = self.s.act(history)
        P = self.s.P
        day = history[-1].day if history else 1
        if history and history[-1].tool == "advance_day" and history[-1].result.get("ok"):
            day = history[-1].result["data"].get("day", day)
        last_day = P is not None and day >= P.n_days
        near_cap = P is not None and len(history) >= P.tool_call_cap - 2
        if tool in ("advance_day",) and (last_day or near_cap) or (near_cap and tool != "accuse"):
            post = self.s.post or (self.s.belief() if hasattr(self.s, "belief") else {})
            if post:
                return "accuse", {"employee": max(sorted(post), key=post.get)}
        return tool, args


def make_policy(agent: str, seed: int):
    if agent == "never_abstain":
        return NeverAbstain()
    if agent.startswith("solver"):
        from canary.solver.ablation import AblatedSolver
        return AblatedSolver(None, ablation=agent.split("-", 1)[1] if "-" in agent else None)
    from canary.solver.bench import make_policy as mp
    return mp(agent, seed)


def run_one(job):
    ci, ov, agent, seed = job
    import logging
    logging.getLogger("canary.solver").setLevel(logging.ERROR)
    register(ov)
    from canary.env import Env
    from canary.solver.bench import _run_local
    r = _run_local(Env("expert", seed), make_policy(agent, seed))
    return {"cfg": ci, "agent": agent, "seed": seed, "score": float(r.score), "correct": int(bool(r.correct)),
            "accused": int(r.end_reason == "accused"), "final_day": r.final_day}


def ci95(xs):
    return 1.96 * statistics.stdev(xs) / math.sqrt(len(xs)) if len(xs) > 1 else 0.0


def summarise(rows, cfgs):
    by = {(r["cfg"], r["agent"], r["seed"]): r for r in rows}
    out = []
    for ci, ov in enumerate(cfgs):
        seeds = sorted({r["seed"] for r in rows if r["cfg"] == ci})
        ref = [by[(ci, "solver", s)]["score"] for s in seeds]
        row = {"cfg": ci, "overrides": ov, "n": len(seeds)}
        for a in RUNGS:
            rs = [by[(ci, a, s)] for s in seeds if (ci, a, s) in by]
            if not rs:
                continue
            sc = [r["score"] for r in rs]
            accd = [r for r in rs if r["accused"]]
            d = [x - y for x, y in zip(sc, ref)]
            row[a] = {"mean": round(statistics.mean(sc), 3), "ci": round(ci95(sc), 3),
                      "acc_among_accused": round(sum(r["correct"] for r in accd) / len(accd), 3) if accd else None,
                      "abstain": round(1 - len(accd) / len(rs), 3),
                      "delta": round(statistics.mean(d), 3), "dci": round(ci95(d), 3)}
        s = row["solver"]
        row["pass"] = {
            "solver_mean>=0.4": s["mean"] >= 0.4,
            "solver_acc>=0.85": (s["acc_among_accused"] or 0) >= 0.85,
            "no_EV_rule_costs>=0.3": max(-row["solver-accuse_p50"]["delta"], -row["solver-accuse_last"]["delta"]) >= 0.3,
            "do_nothing=0": row["do_nothing"]["mean"] == 0 and row["do_nothing"]["ci"] == 0,
            "stop_early=0": row["stop_early"]["mean"] == 0 and row["stop_early"]["ci"] == 0,
        }
        row["never_abstain_cost"] = -row["never_abstain"]["delta"]
        out.append(row)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="coarse")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed0", type=int, default=SEED0)
    ap.add_argument("--procs", type=int, default=3)
    ap.add_argument("--rungs", default=",".join(RUNGS))
    ap.add_argument("--out", default="results/expert_sweep")
    a = ap.parse_args(argv)
    if a.seed0 + a.n > 900000:
        raise SystemExit("judge seeds are off limits")
    cfgs = grid(a.grid)
    rungs = [r for r in a.rungs.split(",")]
    jobs = [(ci, ov, r, s) for ci, ov in enumerate(cfgs) for s in range(a.seed0, a.seed0 + a.n) for r in rungs]
    t0 = time.time()
    with Pool(a.procs) as pool:
        rows = pool.map(run_one, jobs, chunksize=8)
    summ = summarise(rows, cfgs)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out + ".jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    Path(a.out + ".json").write_text(json.dumps({"n": a.n, "seed0": a.seed0, "secs": round(time.time() - t0),
                                                 "configs": summ}, indent=1))
    hdr = f"{'cfg':>3} {'overrides':60} {'solver':>7} {'acc':>5} {'abst':>5} {'p50Δ':>6} {'lastΔ':>6} {'nevAbΔ':>7} {'grok':>6} {'heur':>6} pass"
    print(hdr)
    for r in summ:
        print(f"{r['cfg']:>3} {json.dumps(r['overrides']):60} {r['solver']['mean']:>7.3f} "
              f"{r['solver']['acc_among_accused'] or 0:>5.2f} {r['solver']['abstain']:>5.2f} "
              f"{r['solver-accuse_p50']['delta']:>6.3f} {r['solver-accuse_last']['delta']:>6.3f} "
              f"{r['never_abstain']['delta']:>7.3f} {r['grok_tactics']['mean']:>6.3f} {r['heuristic']['mean']:>6.3f} "
              f"{sum(r['pass'].values())}/5")
    print(f"{time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
