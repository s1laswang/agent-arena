"""J1 calibration: one array task = one (tier, param-cell). Writes one CSV row per (cell, agent, seed).

  python fr8/j1_grid.py --list                       # print the grid (n cells)
  python fr8/j1_grid.py --task 0 --seeds 500 --out DIR   # run cell 0
  python fr8/j1_grid.py --task 0 --dry               # no Env: check grid/imports/CSV path only

Params are overridden by swapping canary.rules.TIERS[tier] with dataclasses.replace(...)
before each Env(tier, seed) is built. Seeds: dev 0..9999, deterministic (seed_offset + i).
"""
from __future__ import annotations

import argparse, csv, dataclasses, importlib, itertools, json, os, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from canary import rules  # noqa: E402

GRID = {  # names must match canary.rules.TierParams fields
    "p_leak": [0.6, 0.75, 0.9],
    "delay_choices": [(1,), (1, 2), (1, 2, 3)],
    "log_rate_mole": [1.2, 1.4, 1.7],
    "interview_lr": [1.2, 1.5],
    "leak_damage": [0.035, 0.05],
}
AGENTS = ["solver", "heuristic", "do_nothing", "stop_early", "random", "restrict_all"]


def cells():
    keys = list(GRID)
    for tier in rules.TIERS:
        for vals in itertools.product(*(GRID[k] for k in keys)):
            yield tier, dict(zip(keys, vals))


def load_policy(name: str, seed: int):
    """Resolve a policy factory. Tries the module layout from docs/agents/ENV.md."""
    if name == "solver":
        return importlib.import_module("canary.solver.policy").SolverPolicy()
    b = importlib.import_module("canary.baselines")
    for attr in (f"make_{name}", "make", "get_policy"):
        f = getattr(b, attr, None)
        if f is not None:
            try:
                return f(seed=seed) if attr.startswith("make_") else f(name, seed=seed)
            except TypeError:
                return f() if attr.startswith("make_") else f(name)
    cls = "".join(p.capitalize() for p in name.split("_")) + "Policy"
    C = getattr(b, cls)
    try:
        return C(seed=seed)
    except TypeError:
        return C()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--task", type=int, default=int(os.environ.get("SLURM_ARRAY_TASK_ID", 0)))
    ap.add_argument("--seeds", type=int, default=500)
    ap.add_argument("--seed-offset", type=int, default=0)
    ap.add_argument("--agents", default=",".join(AGENTS))
    ap.add_argument("--out", default=os.path.expanduser("~/agent-arena-data/j1"))
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    all_cells = list(cells())
    if a.list:
        print(len(all_cells)); return
    tier, params = all_cells[a.task]
    assert set(params) <= {f.name for f in dataclasses.fields(rules.TierParams)}, params
    seeds = range(a.seed_offset, a.seed_offset + a.seeds)
    assert seeds.start >= 0 and seeds.stop <= 10_000, "J1 tunes on DEV seeds only"
    out = Path(a.out) / "parts"; out.mkdir(parents=True, exist_ok=True)
    path = out / f"cell{a.task:04d}.csv"
    base = rules.TIERS[tier]
    rules.TIERS[tier] = dataclasses.replace(base, **params)
    cols = ["cell", "tier", *GRID, "agent", "seed", "score", "correct", "final_day", "end_reason", "secs"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, cols); w.writeheader()
        if a.dry:
            print(f"DRY cell {a.task}/{len(all_cells)} tier={tier} {params} -> {path}"); return
        from canary.env import Env
        from canary.eval import run_episode
        for agent in a.agents.split(","):
            for s in seeds:
                t0 = time.time()
                r = run_episode(Env(tier=tier, seed=s), load_policy(agent, s))
                w.writerow({"cell": a.task, "tier": tier, **{k: json.dumps(v) if isinstance(v, tuple) else v for k, v in params.items()},
                            "agent": agent, "seed": s, "score": r.score, "correct": int(r.correct),
                            "final_day": r.final_day, "end_reason": r.end_reason, "secs": round(time.time() - t0, 3)})
            fh.flush()
    print(f"done cell {a.task} -> {path}")


if __name__ == "__main__":
    main()
