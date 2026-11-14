"""Re-validate a Mole Forge hall of fame on the current tiers (CONTRACT §7 feasibility).

  python -m fr8.analysis.forge_validate <run_dir> --tier hard --seeds 2000:2200 --workers 2 \
      --out fr8/analysis/out/forge_v12_validation

For every hall-of-fame strategy (plus the default mole) on FRESH seeds: solver score/accuracy/none-rate,
heuristic score/accuracy, regret = solver - heuristic. Feasible iff solver score >= 0.5 x solver score on
the default mole AND solver accuracy >= 0.85 (constants from canary.forge.fitness). Reuses
canary.forge.fitness.make_env + default factories; this module only adds the none-rate bookkeeping.
Judge-set candidates: feasible AND regret CI lower bound > 0.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from ._common import ci_half, mean, write_rows


def _episode(tier, seed, strat, factory, name):
    from canary.forge.fitness import make_env
    env = make_env(tier, seed, strat)
    pol = factory(seed)
    pol.reset(env.tools_spec(), env.instruction())
    while not env.done:
        tool, args = pol.act(env.history)
        env.call(tool, args)
    r = env.result(name)
    return float(env.score()), bool(r.correct), r.accused in (None, "")


def eval_strategy(args) -> dict:
    sid, strat, tier, seeds = args
    from canary.forge.fitness import default_investigators, default_solver_factory
    sf, hf = default_solver_factory(), default_investigators()["heuristic"]
    S = [_episode(tier, s, strat, sf, "solver") for s in seeds]
    H = [_episode(tier, s, strat, hf, "heuristic") for s in seeds]
    reg = [a[0] - b[0] for a, b in zip(S, H)]
    return {"strategy": sid, "n": len(seeds),
            "solver_score": mean([x[0] for x in S]), "solver_ci": ci_half([x[0] for x in S]),
            "solver_acc": mean([float(x[1]) for x in S]), "solver_none": mean([float(x[2]) for x in S]),
            "heur_score": mean([x[0] for x in H]), "heur_acc": mean([float(x[1]) for x in H]),
            "regret": mean(reg), "regret_ci": ci_half(reg)}


def validate(hof: list[dict], tier: str, seeds: list[int], workers: int = 2) -> list[dict]:
    from canary.forge.fitness import FEASIBLE_SOLVER_ACC, FEASIBLE_SOLVER_RATIO
    from canary.forge.mutate import default_strategy_json
    tasks = [("default", default_strategy_json(), tier, seeds)]
    tasks += [(f"hof#{h.get('rank', i + 1)}", h["strategy_json"], tier, seeds) for i, h in enumerate(hof)]
    if workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows = list(ex.map(eval_strategy, tasks))
    else:
        rows = [eval_strategy(t) for t in tasks]
    base = rows[0]["solver_score"]
    for r, h in zip(rows, [None] + hof):
        r["ratio_vs_default"] = r["solver_score"] / base if base else float("nan")
        r["feasible"] = (r["solver_score"] >= FEASIBLE_SOLVER_RATIO * base) and r["solver_acc"] >= FEASIBLE_SOLVER_ACC
        r["judge_candidate"] = r["strategy"] != "default" and r["feasible"] and r["regret"] - r["regret_ci"] > 0
        r["v1_fitness"] = h.get("fitness") if h else None
    return rows


def to_markdown(rows, run, tier, seeds, tier_params: dict) -> str:
    f = lambda v: f"{v:.3f}" if isinstance(v, float) else str(v)
    cols = ["strategy", "n", "solver_score", "solver_ci", "solver_acc", "solver_none", "heur_score", "heur_acc",
            "regret", "regret_ci", "ratio_vs_default", "feasible", "judge_candidate", "v1_fitness"]
    cand = [r["strategy"] for r in rows if r["judge_candidate"]]
    out = [f"# Forge hall-of-fame re-validation", "",
           f"- run: `{run}`", f"- tier: {tier}, fresh seeds {seeds[0]}–{seeds[-1]} (n={len(seeds)})",
           f"- tier params: " + ", ".join(f"{k}={tier_params[k]}" for k in
                                          ("fingerprint_accuracy", "framing_rate", "n_employees", "delay_choices")
                                          if k in tier_params),
           "- feasible: solver score ≥ 0.5 × default-mole score AND solver acc ≥ 0.85 (CONTRACT §7); "
           "judge candidate: feasible AND regret 95% CI lower bound > 0",
           f"- feasible: {sum(r['feasible'] for r in rows if r['strategy'] != 'default')}/{len(rows) - 1}; "
           f"judge candidates: {', '.join(cand) or 'none'}", "",
           "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(f(r[c]) for c in cols) + " |" for r in rows]
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="forge HoF re-validation")
    ap.add_argument("run"); ap.add_argument("--tier", default="hard"); ap.add_argument("--seeds", default="2000:2200")
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int)
    a = ap.parse_args(argv)
    from canary.rules import TIERS
    lo, hi = (int(x) for x in a.seeds.split(":"))
    seeds = list(range(lo, hi))
    hof = [json.loads(l) for l in (Path(a.run) / "hall_of_fame.jsonl").read_text().splitlines() if l.strip()]
    hof = hof[: a.limit] if a.limit else hof
    rows = validate(hof, a.tier, seeds, a.workers)
    write_rows(a.out + ".csv", rows)
    md = to_markdown(rows, a.run, a.tier, seeds, dataclasses.asdict(TIERS[a.tier]))
    Path(a.out + ".md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
