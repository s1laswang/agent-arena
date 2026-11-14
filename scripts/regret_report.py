"""Per-decision regret report for recorded runs (offline analysis; reads server-side decoy id).

    uv run --python 3.12 python scripts/regret_report.py data/runs/<run_id>/episodes.jsonl [...]
        [--reference 50]   # also run SolverPolicy + heuristic on the same tiers/seeds as reference rows
        [--out results]

Judge/held-out seeds regenerate the same world only with CANARY_WORLD_SECRET set; without it they
are skipped (their worlds would differ from the recorded run).
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from canary.env import Env  # noqa: E402
from canary.rules import HELDOUT_SEEDS, JUDGE_SEEDS  # noqa: E402
from canary.solver.regret import attribute  # noqa: E402
from canary.types import EpisodeResult, Step  # noqa: E402

TAGS = ["uninformative_canary", "premature_accusation", "decoy_chase", "ignored_delay",
        "over_restriction", "budget_waste", "no_accusation"]


def load(path):
    for line in open(path):
        if not line.strip():
            continue
        d = json.loads(line)
        d["steps"] = [Step(**s) for s in d["steps"]]
        yield EpisodeResult(**d)


def analyse(ep: EpisodeResult):
    env = Env(ep.tier, ep.seed)
    ep.meta = dict(ep.meta or {})
    ep.meta["decoy"] = env._world.decoy  # server-side truth, offline analysis only
    rows = attribute(ep, env.instruction())
    return rows


def summarise(eps_rows):
    """eps_rows: list of (ep, rows) -> per-tier summary dict."""
    out = {}
    by_tier = defaultdict(list)
    for ep, rows in eps_rows:
        by_tier[ep.tier].append((ep, rows))
    for tier, lst in by_tier.items():
        n = len(lst)
        tot = [sum(r["regret"] for r in rows) for _, rows in lst]
        tag_sum, tag_freq = Counter(), Counter()
        p_acc = []
        decisions = []
        for ep, rows in lst:
            for r in rows:
                for t in r["tags"]:
                    tag_sum[t] += r["regret"]
                    tag_freq[t] += 1
                if "p_accused" in r:
                    p_acc.append(r["p_accused"])
                decisions.append(dict(seed=ep.seed, t=r["t"], day=r["day"], action=r["action"],
                                      regret=r["regret"], tags=r["tags"]))
        decisions.sort(key=lambda x: -x["regret"])
        out[tier] = dict(
            n=n, mean_score=statistics.mean(ep.score for ep, _ in lst),
            accuracy=sum(ep.correct for ep, _ in lst) / n,
            mean_total_regret=statistics.mean(tot),
            tags={t: dict(value_lost=round(tag_sum[t], 4), per_episode=round(tag_sum[t] / n, 4),
                          count=tag_freq[t]) for t in TAGS},
            mean_p_correct_at_accusation=(statistics.mean(p_acc) if p_acc else None),
            top5=decisions[:5])
    return out


def reference(agent, tier, seeds):
    from canary.solver.bench import _run_local, make_policy
    for s in seeds:
        yield _run_local(Env(tier, s), make_policy(agent, s))


def to_md(name, summ):
    L = [f"# Regret report: {name}", ""]
    for tier, s in sorted(summ.items()):
        pc = s["mean_p_correct_at_accusation"]
        L += [f"## {tier} (n={s['n']}): score {s['mean_score']:.3f}, accuracy {s['accuracy']:.0%}, "
              f"mean total regret {s['mean_total_regret']:.3f}, mean P(correct) at accusation "
              f"{'n/a' if pc is None else f'{pc:.2f}'}", "",
              "| tag | count | value lost (sum) | per episode |", "|---|---|---|---|"]
        for t, v in s["tags"].items():
            L.append(f"| {t} | {v['count']} | {v['value_lost']:.3f} | {v['per_episode']:.3f} |")
        L += ["", "Top 5 costly decisions:", "", "| seed | t | day | action | regret | tags |", "|---|---|---|---|---|---|"]
        for d in s["top5"]:
            L.append(f"| {d['seed']} | {d['t']} | {d['day']} | {d['action']} | {d['regret']:.3f} | {', '.join(d['tags'])} |")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--out", default="results")
    ap.add_argument("--reference", type=int, default=0, help="also run solver+heuristic on the same tiers/seeds (max n per tier)")
    ap.add_argument("--name", default=None)
    a = ap.parse_args()
    secret = bool(os.environ.get("CANARY_WORLD_SECRET"))
    eps, skipped = [], 0
    for p in a.paths:
        for ep in load(p):
            if (ep.seed in JUDGE_SEEDS or ep.seed in HELDOUT_SEEDS) and not secret:
                skipped += 1
                continue
            eps.append(ep)
    if skipped:
        print(f"skipped {skipped} judge/held-out episodes (set CANARY_WORLD_SECRET to include them)")
    name = a.name or Path(a.paths[0]).parent.name
    report = {"agent": summarise([(ep, analyse(ep)) for ep in eps])}
    if a.reference:
        seeds_by_tier = defaultdict(list)
        for ep in eps:
            seeds_by_tier[ep.tier].append(ep.seed)
        for agent in ("solver", "heuristic"):
            pairs = []
            for tier, seeds in seeds_by_tier.items():
                for ep in reference(agent, tier, sorted(set(seeds))[:a.reference]):
                    pairs.append((ep, analyse(ep)))
            report[agent] = summarise(pairs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"regret_{name}.json").write_text(json.dumps(report, indent=1))
    md = "\n\n".join(to_md(f"{name} [{k}]", v) for k, v in report.items())
    (out / f"regret_{name}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
