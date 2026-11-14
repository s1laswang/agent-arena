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

# v0.3 regrid (ENV request 02:10). Names = canary.rules.TierParams fields.
# p_single_dept_recipients: 1.0 = department-wide groups, 0.0 = union of two depts (~40-50% of staff).
# log_rate_mole is set as ratio x log_rate_benign (benign stays 1.0): 1.0, 1.15, 1.3.
_COMMON = {
    "p_single_dept_recipients": [1.0, 0.6, 0.0],
    "log_rate_mole": [1.0, 1.15, 1.3],
    "p_after_hours_mole": [0.15, 0.30],
}
TIER_GRID = {  # medium + hard first (priority), 144 cells each; easy 18
    "medium": {**_COMMON, "delay_choices": [(1, 2), (1, 2, 3)], "careful_mole": [False, True], "framing_rate": [0.5, 1.5]},
    "hard": {**_COMMON, "delay_choices": [(1, 2, 3), (2, 3)], "careful_mole": [False, True], "framing_rate": [0.5, 1.5]},
    "easy": dict(_COMMON),
}
GRID = list(dict.fromkeys(k for g in TIER_GRID.values() for k in g))  # CSV param columns
AGENTS = ["solver", "heuristic", "logs_only", "stop_early", "random"]


def cells():
    for tier, g in TIER_GRID.items():
        keys = list(g)
        for vals in itertools.product(*(g[k] for k in keys)):
            yield tier, dict(zip(keys, vals))


def load_policy(name: str, seed: int):
    """solver -> canary.solver.policy.SolverPolicy; heuristic -> baselines 'obvious_heuristic'; else BASELINES[name]."""
    if name == "solver":
        return importlib.import_module("canary.solver.policy").SolverPolicy()
    from canary.baselines import BASELINES, CALIBRATION_POLICIES
    return {**BASELINES, **CALIBRATION_POLICIES}[name](seed=seed)


def run(env, policy, agent):
    try:
        from canary.eval import run_episode
    except ImportError:  # eval not merged yet: baselines.play drives the same public tool loop
        from canary.baselines import play
        play(env, policy)
        return env.result(agent)
    return run_episode(env, policy)


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
    cols = ["cell", "tier", "n_employees", *GRID, "agent", "seed", "score", "correct", "wrong", "accused", "final_day", "end_reason", "secs"]
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, cols); w.writeheader()
        if a.dry:
            print(f"DRY cell {a.task}/{len(all_cells)} tier={tier} {params} -> {path}"); return
        from canary.env import Env
        for agent in a.agents.split(","):
            for s in seeds:
                t0 = time.time()
                r = run(Env(tier=tier, seed=s), load_policy(agent, s), agent)
                w.writerow({"cell": a.task, "tier": tier, "n_employees": base.n_employees, **{k: json.dumps(v) if isinstance(v, tuple) else v for k, v in ((k, params.get(k, getattr(base, k))) for k in GRID)},
                            "agent": agent, "seed": s, "score": r.score, "correct": int(r.correct), "wrong": int(r.accused is not None and not r.correct), "accused": r.accused or "",
                            "final_day": r.final_day, "end_reason": r.end_reason, "secs": round(time.time() - t0, 3)})
            fh.flush()
    print(f"done cell {a.task} -> {path}")


if __name__ == "__main__":
    main()
