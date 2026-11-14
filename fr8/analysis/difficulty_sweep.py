"""Difficulty-curve sweep over ENV's noise scalar: solver vs heuristic.

Cluster/array use (one cell per task), raw per-episode rows:
  python -m fr8.analysis.difficulty_sweep run --tier hard --noise 0.5 --seeds 0:50 --out data/fr8/sweep/hard_0.5.csv
Emit a param list for an array job (one line per task: tier noise seeds):
  python -m fr8.analysis.difficulty_sweep params --tiers easy,medium,hard --grid 0:1:0.1 --seeds 0:50
Aggregate raw CSVs -> summary CSV (noise,tier,agent,mean,ci95,accuracy,n) + PNG:
  python -m fr8.analysis.difficulty_sweep aggregate data/fr8/sweep/*.csv --out fr8/analysis/out/difficulty.csv
(The old flat form `--tier T --noise X --seeds a:b --out CSV` is accepted as `run`.)

Wiring: the noise field is auto-detected on canary.rules.TierParams (first of NOISE_FIELDS);
episodes run through canary.eval.run_episode(Env, policy) with make_policy_factory(agent).
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from ._common import ci_half, group, mean, read_rows, write_rows

NOISE_FIELDS = ("noise", "difficulty", "noise_scale", "noise_level")
DEFAULT_AGENTS = ("solver", "heuristic", "random", "stop_early")


def parse_seeds(s: str) -> list[int]:
    a, b = s.split(":")
    return list(range(int(a), int(b)))


def noise_field() -> str:
    from canary.rules import TierParams
    names = {f.name for f in dataclasses.fields(TierParams)}
    for n in NOISE_FIELDS:
        if n in names:
            return n
    raise RuntimeError(f"no noise scalar on TierParams yet (looked for {NOISE_FIELDS})")


def _episode(tier: str, seed: int, agent: str, params):
    """One episode under `params`: canary.eval.run_episode(Env, policy) with a per-process
    TIERS[tier] swap during Env construction (Env has no params= argument)."""
    from canary import rules
    from canary.env import Env
    from canary.eval import make_policy_factory, run_episode
    old = rules.TIERS[tier]
    rules.TIERS[tier] = params
    try:
        env = Env(tier, seed)
    finally:
        rules.TIERS[tier] = old
    return run_episode(env, make_policy_factory(agent)(seed))


def run_cell(tier: str, noise: float, seeds: list[int], agents=DEFAULT_AGENTS) -> list[dict]:
    from canary.rules import TIERS, apply_noise
    params = apply_noise(TIERS[tier], noise)
    rows = []
    for agent in agents:
        for seed in seeds:
            r = _episode(tier, seed, agent, params)
            rows.append({"noise": noise, "tier": tier, "agent": agent, "seed": seed, "score": r.score,
                         "correct": int(r.correct), "wrong": int(r.accused is not None and not r.correct),
                         "final_day": r.final_day})
    return rows


def aggregate(rows: list[dict]) -> list[dict]:
    out = []
    for (noise, tier, agent), rs in sorted(
            group(rows, lambda r: (float(r["noise"]), r["tier"], r["agent"])).items()):
        sc = [r["score"] for r in rs]
        out.append({"noise": noise, "tier": tier, "agent": agent, "mean_score": mean(sc),
                    "ci95": ci_half(sc), "accuracy": mean([float(r["correct"]) for r in rs]),
                    "wrong_rate": mean([float(r.get("wrong", 0) or 0) for r in rs]),
                    "n": len(rs)})
    return out


def plot(summary: list[dict], png: str | Path) -> bool:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("matplotlib missing: `uv run --with matplotlib ...` for the PNG", file=sys.stderr)
        return False
    tiers = sorted({r["tier"] for r in summary})
    fig, axes = plt.subplots(1, len(tiers), figsize=(4.5 * len(tiers), 3.6), squeeze=False)
    for ax, tier in zip(axes[0], tiers):
        for agent, rs in sorted(group([r for r in summary if r["tier"] == tier],
                                      lambda r: r["agent"]).items()):
            rs.sort(key=lambda r: r["noise"])
            x = [r["noise"] for r in rs]
            y = [r["mean_score"] for r in rs]
            e = [r["ci95"] if r["ci95"] == r["ci95"] else 0 for r in rs]
            ax.plot(x, y, marker="o", label=agent)
            ax.fill_between(x, [a - b for a, b in zip(y, e)], [a + b for a, b in zip(y, e)], alpha=.2)
        ax.set_title(tier); ax.set_xlabel("noise"); ax.set_ylabel("mean score")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0][0].legend(frameon=False)
    fig.tight_layout()
    fig.savefig(png, dpi=130)
    return True


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0].startswith("--"):
        argv = ["run"] + argv
    ap = argparse.ArgumentParser(description="difficulty sweep")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--tier", required=True); r.add_argument("--noise", type=float, required=True)
    r.add_argument("--seeds", default="0:10"); r.add_argument("--out", required=True)
    r.add_argument("--agents", default=",".join(DEFAULT_AGENTS))
    p = sub.add_parser("params")
    p.add_argument("--tiers", default="easy,medium,hard"); p.add_argument("--grid", default="0:1:0.1")
    p.add_argument("--seeds", default="0:50")
    g = sub.add_parser("aggregate")
    g.add_argument("csvs", nargs="+"); g.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        write_rows(a.out, run_cell(a.tier, a.noise, parse_seeds(a.seeds), a.agents.split(",")))
    elif a.cmd == "params":
        lo, hi, step = (float(v) for v in a.grid.split(":"))
        k = 0
        while lo + k * step <= hi + 1e-9:
            for t in a.tiers.split(","):
                print(t, round(lo + k * step, 6), a.seeds)
            k += 1
    else:
        rows = [row for c in a.csvs for row in read_rows(c)]
        summary = aggregate(rows)
        write_rows(a.out, summary)
        plot(summary, Path(a.out).with_suffix(".png"))


if __name__ == "__main__":
    main()
