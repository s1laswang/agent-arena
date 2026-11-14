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
        "accuse_most_logs": _first(["canary.baselines:AccuseMostLogs"]),
        "heuristic": _first(["canary.baselines:Heuristic", "canary.baselines:HeuristicPolicy",
                             "canary.solver.heuristic:HeuristicPolicy",
                             "canary.baselines:ObviousHeuristic"]),
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


def measure(tier: str, seeds: list[int], llm: str | None = None) -> list[tuple]:
    """[(policy, mean, ci95, n)] in skill order, skipping unavailable policies."""
    from canary.env import Env
    rows = []
    for name, factory in policies(llm).items():
        if factory is None:
            print(f"skip {name}: not available")
            continue
        scores = [run_episode(Env(tier=tier, seed=s), _instantiate(factory, s)) for s in seeds]
        m, h = mean_ci(scores)
        rows.append((name, m, h, len(scores)))
        print(f"{tier:6s} {name:18s} {m:+.3f} ± {h:.3f} (n={len(scores)})")
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="medium", help="comma list, e.g. medium,hard")
    ap.add_argument("--seeds", default="0-49")
    ap.add_argument("--llm", default=None, help="e.g. openai:gpt-4o-mini (hinted LLM policy)")
    a = ap.parse_args(argv)
    seeds = parse_seeds(a.seeds)
    tiers = a.tier.split(",")
    OUT.mkdir(exist_ok=True)
    results, monotone = {}, True
    for tier in tiers:
        try:
            rows = measure(tier, seeds, a.llm)
        except NotImplementedError:
            print("canary.env.Env not implemented yet")
            return 2
        if len(rows) < 2:
            print("INSUFFICIENT: fewer than 2 policies available; nothing to compare")
            return 2
        results[tier] = rows
        with (OUT / f"monotonicity-{tier}.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["policy", "mean", "ci95", "n"])
            w.writerows(rows)
        means = [r[1] for r in rows]
        ok = all(x < y for x, y in zip(means, means[1:]))
        monotone &= ok
        print(f"{tier}: " + ("MONOTONE" if ok else "NOT MONOTONE: reward does not rank skill"))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print(f"matplotlib missing: wrote CSVs in {OUT}/ only")
        return 0 if monotone else 1
    fig, axes = plt.subplots(1, len(tiers), figsize=(5.5 * len(tiers), 3.8), squeeze=False)
    for ax, tier in zip(axes[0], tiers):
        rows = results[tier]
        ax.bar([r[0].replace("_", "\n") for r in rows], [r[1] for r in rows],
               yerr=[r[2] for r in rows], color="#4C78A8", capsize=4)
        ax.axhline(0, color="#888", lw=0.8)
        ax.set_title(f"{tier}, n={len(seeds)} dev seeds")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].set_ylabel("mean score (V if correct, -1 if wrong)")
    fig.suptitle("Reward monotonicity: score ranks investigator skill")
    fig.tight_layout()
    fig.savefig(OUT / "monotonicity.png", dpi=150)
    print(f"wrote {OUT}/monotonicity.png")
    return 0 if monotone else 1


if __name__ == "__main__":
    raise SystemExit(main())
