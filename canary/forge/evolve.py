"""Mole Forge evolution loop (CONTRACT §7).

python -m canary.forge.evolve --mutator stub|gemini:<model> --tier hard --pop 16 --gens 50 \
    --seeds 0-19 --workers 8 --out data/forge/<run>/ [--fake] [--seed 0] [--hof 20]

Writes <out>/log.jsonl (one line per generation, incl. the full population so the run is resumable)
and <out>/hall_of_fame.jsonl (top-k unique feasible strategies). Re-running with the same --out resumes.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from pathlib import Path

from .fitness import (default_investigators, default_solver_factory, evaluate, fake_factory, fake_runner,
                      real_runner, solver_baseline, tier_defaults)
from .mutate import canonical, default_strategy_json, get_mutator, validate_strategy


def parse_seeds(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def _fin(x):
    return x if x is not None and math.isfinite(x) else None


def _tournament(rng, pop, k=3):
    cand = rng.sample(pop, min(k, len(pop)))
    return max(cand, key=lambda p: (p["fitness"], -len(p["strategy_json"].get("rules", []))))


def run(mutator_spec="stub", tier="hard", pop_size=16, gens=50, seeds=range(20), workers=1, out="data/forge/run",
        fake=False, seed=0, elite=2, hof_k=20, investigators=None, solver_factory=None, runner=None,
        log=print, fitness_mode: str | None = None, min_solver_acc: float | None = None) -> dict:
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    seeds = list(seeds)
    if fake:
        runner = runner or fake_runner
        investigators = investigators or {"heuristic": fake_factory, "hinted_heuristic": fake_factory}
        solver_factory = solver_factory or fake_factory
    else:
        runner = runner or real_runner
        investigators = investigators or default_investigators()
        solver_factory = solver_factory or default_solver_factory()
    td = tier_defaults(tier)
    fitness_mode = fitness_mode or td["fitness_mode"]
    min_solver_acc = td["min_solver_acc"] if min_solver_acc is None else min_solver_acc
    mutator = get_mutator(mutator_spec, seed=seed)
    baseline = solver_baseline(solver_factory, seeds, tier, runner, workers)
    cache: dict[str, dict] = {}

    def ev(s):
        k = canonical(s)
        if k not in cache:
            cache[k] = evaluate(s, investigators, solver_factory, seeds, tier, runner, workers, baseline,
                                fitness_mode=fitness_mode, min_solver_acc=min_solver_acc)
        return cache[k]

    def member(s):
        e = ev(s)
        return {"strategy_json": s, "fitness": e["fitness"], "eval": e}

    log_path, start_gen, pop = out / "log.jsonl", 0, None
    if log_path.exists():
        lines = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
        for line in lines:
            for p in line["population"]:
                p["fitness"] = -math.inf if p["fitness"] is None else p["fitness"]
                cache[canonical(p["strategy_json"])] = {**p["eval"], "fitness": p["fitness"]}
        if lines:
            start_gen = lines[-1]["gen"] + 1
            pop = lines[-1]["population"]
            log(f"resuming {out} at gen {start_gen}")
    if pop is None:
        base = validate_strategy(default_strategy_json())
        if hasattr(mutator, "reseed"):
            mutator.reseed(-1)
        init = [base] + mutator.propose([{"strategy_json": base, "fitness": None, "beaten_tags": []}], pop_size - 1)
        pop = [member(s) for s in init]
        start_gen = 0

    for gen in range(start_gen, gens):
        t0 = time.time()
        rng = random.Random(f"forge-evolve:{seed}:{gen}")
        if hasattr(mutator, "reseed"):
            mutator.reseed(gen)
        if gen > 0:
            ranked = sorted(pop, key=lambda p: p["fitness"], reverse=True)
            elites = ranked[:elite]
            parents = []
            for _ in range(max(2, min(4, pop_size // 4))):
                p = _tournament(rng, ranked)
                parents.append({"strategy_json": p["strategy_json"], "fitness": _fin(p["fitness"]),
                                "beaten_tags": p["eval"].get("beaten", [])})
            children = mutator.propose(parents, pop_size - len(elites))
            pop = elites + [member(c) for c in children]
        _write_gen(log_path, gen, pop, baseline, mutator, t0)
        best = max(pop, key=lambda p: p["fitness"])
        log(f"gen {gen}: best={best['fitness']:.4f} feasible={sum(math.isfinite(p['fitness']) for p in pop)}/{len(pop)}")
        _write_hof(out / "hall_of_fame.jsonl", cache, hof_k)
    return {"out": str(out), "baseline": baseline, "hof": _write_hof(out / "hall_of_fame.jsonl", cache, hof_k)}


def _write_gen(path, gen, pop, baseline, mutator, t0):
    fits = [p["fitness"] for p in pop]
    feas = [f for f in fits if math.isfinite(f)]
    best = max(pop, key=lambda p: p["fitness"])
    line = {"gen": gen, "best_fitness": _fin(best["fitness"]),
            "mean_fitness": sum(feas) / len(feas) if feas else None,
            "feasible_share": len(feas) / len(pop), "best_strategy": best["strategy_json"],
            "best_eval": {k: v for k, v in best["eval"].items() if k != "fitness"},
            "baseline_solver_score": baseline["score"], "mutator": getattr(mutator, "name", "?"),
            "mutator_stats": mutator.stats() if hasattr(mutator, "stats") else None,
            "seconds": round(time.time() - t0, 3),
            "population": [{"strategy_json": p["strategy_json"], "fitness": _fin(p["fitness"]),
                            "eval": {k: v for k, v in p["eval"].items() if k != "fitness"}} for p in pop]}
    with open(path, "a") as f:
        f.write(json.dumps(line) + "\n")


def _write_hof(path, cache, k):
    rows = [(key, e) for key, e in cache.items() if e.get("feasible") and math.isfinite(e["fitness"])]
    rows.sort(key=lambda r: (-r[1]["fitness"], r[0]))
    hof = [{"rank": i + 1, "fitness": e["fitness"], "solver_score": e["solver_score"], "solver_acc": e["solver_acc"],
            "per_investigator": e["per_investigator"], "strategy_json": json.loads(key)}
           for i, (key, e) in enumerate(rows[:k])]
    path.write_text("".join(json.dumps(h) + "\n" for h in hof))
    return hof


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mutator", default="stub")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--pop", type=int, default=16)
    ap.add_argument("--gens", type=int, default=50)
    ap.add_argument("--seeds", default="0-19")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--elite", type=int, default=2)
    ap.add_argument("--hof", type=int, default=20)
    ap.add_argument("--fitness", choices=["min", "mean"], default=None,
                    help="min = regret vs strongest investigator (default on hard), mean = mean regret")
    ap.add_argument("--min-solver-acc", type=float, default=None, help="feasibility floor (hard 0.75, else 0.85)")
    ap.add_argument("--fake", action="store_true", help="test doubles instead of Env/solver/heuristics")
    a = ap.parse_args(argv)
    res = run(a.mutator, a.tier, a.pop, a.gens, parse_seeds(a.seeds), a.workers, a.out, a.fake, a.seed,
              a.elite, a.hof, fitness_mode=a.fitness, min_solver_acc=a.min_solver_acc)
    print(json.dumps({"out": res["out"], "baseline": res["baseline"], "hof_size": len(res["hof"]),
                      "best": res["hof"][0]["fitness"] if res["hof"] else None}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
