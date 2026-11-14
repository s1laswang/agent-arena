"""Expected range of the reference solver (= the Harbor oracle) across fresh world secrets, per tier and seed count.

    uv run python scripts/oracle_range.py                  # 200 simulated builds (about 1-2 min)
    uv run python scripts/oracle_range.py 500 --out results/oracle_range_hard_judge10.md

Each `python harbor/build.py` draws a fresh 32-byte world secret, so a judge's oracle run plays 10 worlds
nobody has seen. The Harbor oracle is the reference solver over MCP, and over MCP it scores exactly what the
in-process solver scores on the same secret (harbor/README.md, "Verified on this machine"). So the spread of
the oracle's 10-task mean across builds is the spread of the in-process solver's mean across fresh secrets.
This script draws K fresh secrets, plays the solver on hard 900000-900009 under each, and reports the
distribution of the 10-task mean: the range a judge's single oracle run should land in.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

from canary import world
from canary.eval import make_env, make_policy_factory, run_episode

JUDGE0 = 900000


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    i = (len(s) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("builds", nargs="?", type=int, default=200, help="simulated builds (fresh secrets), default 200")
    ap.add_argument("--tier", default="hard")
    ap.add_argument("--seeds", type=int, default=10,
                    help="first N judge seeds (default 10 = the Harbor judge set; 40 = what make reproduce/accept play)")
    ap.add_argument("--agent", default="solver", help="policy name as in make eval (default solver = the oracle)")
    ap.add_argument("--out", default=None, help="also write the markdown report here (and a .json next to it)")
    a = ap.parse_args(argv)
    if os.environ.get("CANARY_WORLD_SECRET") or (Path(__file__).resolve().parent.parent / "data/worlds/judge/SALT").exists():
        print("oracle_range: the in-process secret takes precedence, but unset CANARY_WORLD_SECRET to avoid confusion",
              file=sys.stderr)

    seeds = list(range(JUDGE0, JUDGE0 + a.seeds))
    factory = make_policy_factory(a.agent)
    means: list[float] = []
    episodes: list[float] = []
    correct = 0
    for k in range(a.builds):
        world.set_world_secret(os.urandom(32))
        scores = []
        for seed in seeds:
            res = run_episode(make_env(a.tier, seed), factory(seed))
            scores.append(float(res.score))
            correct += bool(res.correct)
        means.append(sum(scores) / len(scores))
        episodes.extend(scores)
        if (k + 1) % 50 == 0:
            print(f"{k + 1}/{a.builds} builds", file=sys.stderr)
    world.set_world_secret(None)

    n_ep = len(episodes)
    who = "Reference solver (= Harbor oracle)" if a.agent == "solver" else f"`{a.agent}`"
    lines = [
        f"# {who}: expected range of the {len(seeds)}-task mean, "
        f"{a.tier} x judge seeds {seeds[0]}-{seeds[-1]}",
        "",
        f"`uv run python scripts/oracle_range.py {a.builds} --tier {a.tier} --seeds {a.seeds} --agent {a.agent}`: "
        f"{a.builds} "
        f"simulated builds, each with a fresh 32-byte world secret (as `harbor/build.py` and a keyless "
        f"`make reproduce` draw), `{a.agent}` on the {len(seeds)} tasks of each build.",
        "",
        f"| statistic | {a.agent} {len(seeds)}-task mean |",
        "|---|---:|",
        f"| mean over builds | {statistics.mean(means):+.3f} |",
        f"| standard deviation over builds | {statistics.stdev(means):.3f} |",
        f"| median | {statistics.median(means):+.3f} |",
        f"| **90% range (5th-95th percentile)** | **[{pct(means, 0.05):+.2f}, {pct(means, 0.95):+.2f}]** |",
        f"| 98% range (1st-99th percentile) | [{pct(means, 0.01):+.2f}, {pct(means, 0.99):+.2f}] |",
        f"| 99.8% range (0.1th-99.9th percentile) | [{pct(means, 0.001):+.2f}, {pct(means, 0.999):+.2f}] |",
        f"| min / max over builds | {min(means):+.2f} / {max(means):+.2f} |",
        "",
        f"Per episode ({n_ep} episodes): mean {statistics.mean(episodes):+.3f}, "
        f"correct {correct / n_ep:.1%}, wrong accusations (-1) {sum(1 for s in episodes if s <= -1) / n_ep:.1%}, "
        f"no accusation (0) {sum(1 for s in episodes if s == 0) / n_ep:.1%}.",
        "",
        "do_nothing and stop_early never accuse, so they score exactly 0 on every build.",
    ]
    text = "\n".join(lines) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text)
        summary = {"agent": a.agent, "tier": a.tier, "seeds": [seeds[0], seeds[-1]], "builds": a.builds,
                   "mean": statistics.mean(means), "sd": statistics.stdev(means), "min": min(means), "max": max(means),
                   "p": {str(q): pct(means, q) for q in (0.001, 0.01, 0.05, 0.5, 0.95, 0.99, 0.999)},
                   "build_means": [round(m, 6) for m in means]}
        Path(a.out).with_suffix(".json").write_text(json.dumps(summary, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
