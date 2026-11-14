"""Tiers v1.4 calibration grid (Mac, no LLM calls). Overrides one tier's params in each worker, plays
the solver and the scripted baselines on the same seeds, and prints per-cell paired gaps.

    uv run --python 3.12 python scripts/calib_v14.py --tier hard --seeds 4000-4199 \
        --grid '{"n_days":[21],"canaries_per_day":[2],"max_variants":[3],"leak_damage":[0.05,0.065,0.08],"n_employees":[30,40]}' \
        [--agents solver,grok_tactics,heuristic,logs_only,stop_early,do_nothing] [--solver-kw '{"threshold":0.85}'] [--procs 6] [--out data/calib_v14/x.jsonl]

Every policy reads its numbers from env.instruction() (generated from the overridden params), so the
override is exactly what an agent would see. Deterministic: same (cell, seed, agent) -> same score.
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import math
import statistics
import sys
import time
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_ORIG: dict = {}
DEFAULT_AGENTS = "solver,grok_tactics,heuristic,logs_only,stop_early,do_nothing"


def _one(job):
    tier, over, seed, agent, skw = job
    from canary import rules
    base = _ORIG.setdefault(tier, rules.TIERS[tier])  # always override from the frozen tier, never cumulatively
    rules.TIERS[tier] = dataclasses.replace(base, **{k: (tuple(v) if isinstance(v, list) else v) for k, v in over.items()})
    from canary.env import Env
    from canary.solver.bench import _run_local, make_policy
    t0 = time.perf_counter()
    r = _run_local(Env(tier, seed), make_policy(agent, seed, **(skw if agent == "solver" else {})), max_calls=2000)
    return {"tier": tier, "cell": over, "seed": seed, "agent": agent, "score": r.score, "correct": bool(r.correct),
            "accused": r.end_reason == "accused", "end": r.end_reason,
            "day": r.final_day, "secs": round(time.perf_counter() - t0, 3)}


def _ci(x):
    return 1.96 * statistics.stdev(x) / math.sqrt(len(x)) if len(x) > 1 else 0.0


def summarize(rows, agents):
    by = {}
    for r in rows:
        by.setdefault(json.dumps(r["cell"], sort_keys=True), {}).setdefault(r["agent"], {})[r["seed"]] = r
    out = []
    for cell, d in by.items():
        sol = d.get("solver", {})
        line = {"cell": cell}
        for ag in agents:
            if ag not in d:
                continue
            rs = d[ag]
            sc = [rs[s]["score"] for s in sorted(rs)]
            line[ag] = {"mean": statistics.mean(sc), "ci": _ci(sc), "acc": sum(r["correct"] for r in rs.values()) / len(rs),
                        "noacc": sum(not r["accused"] for r in rs.values()) / len(rs),
                        "day": statistics.mean([r["day"] for r in rs.values() if r["accused"]] or [float("nan")]),
                        "secs": statistics.mean(r["secs"] for r in rs.values())}
            if ag != "solver" and sol:
                common = sorted(set(rs) & set(sol))
                diff = [sol[s]["score"] - rs[s]["score"] for s in common]
                line[ag]["gap"] = statistics.mean(diff)
                line[ag]["gap_ci"] = _ci(diff)
        out.append(line)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", default="4000-4199")
    ap.add_argument("--grid", default="{}", help="JSON: param -> list of values (cartesian product)")
    ap.add_argument("--cells", default=None, help="JSON list of override dicts (instead of --grid)")
    ap.add_argument("--agents", default=DEFAULT_AGENTS)
    ap.add_argument("--solver-kw", default="{}")
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.seeds.split("-"))
    seeds = range(lo, hi + 1)
    if a.cells:
        cells = json.loads(a.cells)
    else:
        g = json.loads(a.grid)
        ks = list(g)
        cells = [dict(zip(ks, v)) for v in itertools.product(*(g[k] for k in ks))] or [{}]
    agents = [x for x in a.agents.split(",") if x]
    skw = json.loads(a.solver_kw)
    jobs = [(a.tier, c, s, ag, skw) for c in cells for ag in agents for s in seeds]
    t0 = time.time()
    with Pool(min(6, a.procs)) as pool:
        rows = pool.map(_one, jobs, chunksize=4)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        with open(a.out, "a") as f:
            for r in rows:
                f.write(json.dumps({**r, "solver_kw": skw}) + "\n")
    print(f"# tier {a.tier}, seeds {lo}-{hi} (n={len(seeds)}), solver_kw={skw}, {time.time() - t0:.0f}s")
    for line in summarize(rows, agents):
        print(line["cell"])
        for ag in agents:
            if ag in line:
                x = line[ag]
                gap = f"  gap {x['gap']:+.3f}±{x['gap_ci']:.3f}" if "gap" in x else ""
                print(f"   {ag:13s} {x['mean']:+.3f}±{x['ci']:.3f} acc {x['acc']:.3f} noacc {x['noacc']:.3f} "
                      f"day {x['day']:.1f} {x['secs']:.2f}s{gap}")


if __name__ == "__main__":
    main()
