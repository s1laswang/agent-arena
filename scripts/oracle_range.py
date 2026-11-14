"""Expected oracle score range for a judge's Harbor rerun (fresh build secret = new worlds).

harbor/build.py bakes one random 32-byte world secret per build; the sidecar's canary.world derives each
world as HMAC(secret, "<tier>:<seed>"). Here we draw --builds synthetic secrets (deterministic from
--rng-seed, never a real SALT), set them in-process with canary.world.set_world_secret, play each agent on
the judge seeds, and report the distribution of the k-task mean for k = 2, 10, 20.

    uv run --python 3.12 --extra dev python scripts/oracle_range.py --builds 200 --tiers hard,medium \
        --agents solver,do_nothing,stop_early --procs 2
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SEEDS20 = list(range(900000, 900020))


def build_secret(rng_seed: int, b: int) -> bytes:
    return hashlib.sha256(f"oracle-range:{rng_seed}:{b}".encode()).digest()


def _job(job):
    agent, tier, rng_seed, b = job
    from canary import world
    from canary.eval import make_env, run_episode
    sys.path.insert(0, str(ROOT / "scripts"))
    from gap_vs_reference import _policy
    world.set_world_secret(build_secret(rng_seed, b))
    out = []
    for s in SEEDS20:
        t0 = time.perf_counter()
        r = run_episode(make_env(tier, s), _policy(agent, s))
        out.append((r.score, time.perf_counter() - t0))
    world.set_world_secret(None)
    return agent, tier, b, out


def summarize(m):
    m = np.asarray(m)
    return {"mean": float(m.mean()), "sd": float(m.std(ddof=1)),
            "p5": float(np.quantile(m, .05)), "p50": float(np.quantile(m, .5)), "p95": float(np.quantile(m, .95)),
            "p_lt0": float((m < 0).mean()), "p_le_-0.43": float((m <= -0.43).mean())}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--builds", type=int, default=200)
    ap.add_argument("--tiers", default="hard,medium")
    ap.add_argument("--agents", default="solver,do_nothing,stop_early")
    ap.add_argument("--rng-seed", type=int, default=1)
    ap.add_argument("--procs", type=int, default=2)
    ap.add_argument("--out", default=str(ROOT / "results/oracle_range_v1.4"))
    a = ap.parse_args(argv)
    jobs = [(ag, t, a.rng_seed, b) for ag in a.agents.split(",") for t in a.tiers.split(",") for b in range(a.builds)]
    t0 = time.time()
    with Pool(max(1, min(a.procs, 2))) as p:
        res = p.map(_job, jobs, chunksize=4)
    wall = time.time() - t0
    S = {}
    for ag, t, b, out in res:
        S.setdefault((ag, t), {})[b] = out
    rows = []
    for (ag, t), d in sorted(S.items()):
        sc = np.array([[x[0] for x in d[b]] for b in sorted(d)])   # builds x 20 seeds
        rt = np.array([[x[1] for x in d[b]] for b in sorted(d)])
        row = {"agent": ag, "tier": t, "builds": len(d), "sec_per_task": float(rt.mean()),
               "per_task_sd": float(sc[:, :10].std(ddof=1))}
        for k in (2, 10, 20):
            row[f"k{k}"] = summarize(sc[:, :k].mean(1))
        rows.append(row)
    out = {"command": "uv run --python 3.12 --extra dev python " + " ".join(sys.argv), "wall_s": round(wall, 1),
           "secrets": f"sha256('oracle-range:{a.rng_seed}:<b>') for b < {a.builds} (synthetic, not a build SALT)",
           "rows": rows}
    Path(a.out + ".json").write_text(json.dumps(out, indent=1))
    L = [f"builds={a.builds}, wall {wall:.0f} s, procs {a.procs}", "",
         "| agent | tier | k tasks | mean | sd | p5 | p50 | p95 | P(mean<0) | P(mean≤−0.43) | s/task (in-process) |",
         "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        for k in (2, 10, 20):
            s = r[f"k{k}"]
            L.append(f"| {r['agent']} | {r['tier']} | {k} | {s['mean']:+.3f} | {s['sd']:.3f} | {s['p5']:+.3f} | "
                     f"{s['p50']:+.3f} | {s['p95']:+.3f} | {s['p_lt0']:.1%} | {s['p_le_-0.43']:.1%} | {r['sec_per_task']:.3f} |")
    Path(a.out + ".md").write_text("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
