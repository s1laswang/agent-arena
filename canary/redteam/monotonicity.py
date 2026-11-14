"""Reward-monotonicity check (owner: HEAD-INTEGRITY / props-probe).

A sound reward ranks investigators by skill: random < heuristic < hinted LLM < solver.
Computes mean score ± 95% CI over dev seeds and plots results/monotonicity.png (CSV
fallback when matplotlib is missing). Missing policies are skipped and reported.

    python -m canary.redteam.monotonicity --tier medium --seeds 0-49 [--llm openai:gpt-4o-mini]
"""
from __future__ import annotations

import argparse
import csv
import importlib
import math
from pathlib import Path

from canary.redteam.text_probe import parse_seeds
from canary.rules import TIERS

OUT = Path("results")


def _first(paths: list[str]):
    """Return the first importable 'module:attr' (attr may be dotted)."""
    for p in paths:
        mod, attr = p.split(":")
        try:
            obj = importlib.import_module(mod)
            for a in attr.split("."):
                obj = getattr(obj, a)
            return obj
        except (ImportError, AttributeError):
            continue
    return None


def policies(llm: str | None) -> dict[str, object | None]:
    return {
        "random": _first(["canary.baselines:RandomPolicy"]),
        "heuristic": _first(["canary.baselines:Heuristic", "canary.baselines:HeuristicPolicy",
                             "canary.solver.heuristic:HeuristicPolicy",
                             "canary.baselines:BASELINES.heuristic"]),
        "hinted_llm": (_make_llm(llm) if llm else None),
        "solver": _first(["canary.solver:SolverPolicy", "canary.solver:Solver",
                          "canary.solver.policy:SolverPolicy"]),
    }


def _make_llm(spec: str):
    cls = _first(["canary.agents:LLMPolicy", "canary.agents.llm:LLMPolicy",
                  "canary.llm.policy:LLMPolicy"])
    if cls is None:
        return None
    return lambda seed=0: cls(spec, hinted=True)


def _instantiate(factory, seed: int):
    try:
        return factory(seed=seed)
    except TypeError:
        return factory()


def run_episode(env, policy, max_steps: int = 1000) -> float:
    runner = _first(["canary.eval:run_episode"])
    if runner is not None:
        return runner(env, policy).score
    policy.reset(env.tools_spec(), env.instruction())
    for _ in range(max_steps):
        if env.done:
            break
        tool, args = policy.act(env.history)
        env.call(tool, args)
    return env.score()


def mean_ci(xs: list[float]) -> tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) if n > 1 else 0.0
    return m, 1.96 * sd / math.sqrt(n)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="medium", choices=sorted(TIERS))
    ap.add_argument("--seeds", default="0-49")
    ap.add_argument("--llm", default=None, help="e.g. openai:gpt-4o-mini (hinted LLM policy)")
    a = ap.parse_args(argv)
    from canary.env import Env
    seeds = parse_seeds(a.seeds)
    rows = []
    for name, factory in policies(a.llm).items():
        if factory is None:
            print(f"skip {name}: not available")
            continue
        try:
            scores = [run_episode(Env(tier=a.tier, seed=s), _instantiate(factory, s)) for s in seeds]
        except NotImplementedError:
            print("canary.env.Env not implemented yet")
            return 2
        m, h = mean_ci(scores)
        rows.append((name, m, h, len(scores)))
        print(f"{name:12s} {m:.3f} ± {h:.3f} (n={len(scores)})")
    OUT.mkdir(exist_ok=True)
    with (OUT / f"monotonicity-{a.tier}.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["policy", "mean", "ci95", "n"])
        w.writerows(rows)
    means = [r[1] for r in rows]
    monotone = len(means) >= 2 and all(x < y for x, y in zip(means, means[1:]))
    if len(means) < 2:
        print("INSUFFICIENT: fewer than 2 policies available; nothing to compare")
        return 2
    print("MONOTONE" if monotone else "NOT MONOTONE: reward does not rank skill as expected")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"matplotlib missing: wrote {OUT}/monotonicity-{a.tier}.csv only")
        return 0 if monotone else 1
    fig, ax = plt.subplots(figsize=(6, 3.5))
    ax.bar([r[0] for r in rows], means, yerr=[r[2] for r in rows], color="#4C78A8", capsize=4)
    ax.set_ylabel("mean score (V at correct accusation)")
    ax.set_title(f"Reward monotonicity, {a.tier}, n={len(seeds)} dev seeds")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "monotonicity.png", dpi=150)
    print(f"wrote {OUT}/monotonicity.png")
    return 0 if monotone else 1


if __name__ == "__main__":
    raise SystemExit(main())
