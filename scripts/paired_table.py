"""Solver vs other agents, paired by seed, with per-tier paired 95% CIs.

    uv run --python 3.12 python scripts/paired_table.py --seeds 1000:1400 \
        --agents grok_tactics,heuristic,random,stop_early,do_nothing [--mode known|true] [--out results/x.md]
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _init(known, version=None):
    from canary import rules
    rules.KNOWN_V_MODE = known
    if version and version != rules.TIERS_VERSION:  # frozen earlier tiers (rules.TIERS_HISTORY), worker-wide
        rules.TIERS.clear()
        rules.TIERS.update(rules.TIERS_HISTORY[version])
        rules.TIERS_VERSION = version


def _one(job):
    tier, seed, agent = job
    from canary.env import Env
    from canary.solver.bench import _run_local, make_policy
    r = _run_local(Env(tier, seed), make_policy(agent, seed))
    return r.score, r.correct, r.end_reason == "accused", r.final_day


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="1000:1400")
    ap.add_argument("--tiers", default="easy,medium,hard")
    ap.add_argument("--agents", default="grok_tactics,heuristic,random,stop_early,do_nothing")
    ap.add_argument("--mode", choices=["known", "true"], default="known", help="rules.KNOWN_V_MODE")
    ap.add_argument("--procs", type=int, default=6)
    ap.add_argument("--tiers-version", default=None, help="replay an earlier frozen version, e.g. v1.3 (rules.TIERS_HISTORY)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.seeds.split(":"))
    seeds = range(lo, hi)
    agents = ["solver"] + [x for x in a.agents.split(",") if x and x != "solver"]
    from canary import rules
    version = a.tiers_version or rules.TIERS_VERSION
    lines = [f"# Paired table: seeds {lo}-{hi - 1}, V mode = {a.mode}, tiers {version}", "",
             "Diff = agent - solver on the same seed (paired 95% CI). Acc = correct accusations; no-acc = episodes without an accusation.", "",
             "| tier | agent | mean score | ±95% | diff vs solver (paired) | acc | acc when accusing | no-acc | mean accusation day |",
             "|---|---|---|---|---|---|---|---|---|"]
    with Pool(min(6, a.procs), initializer=_init, initargs=(a.mode == "known", a.tiers_version)) as pool:
        for tier in a.tiers.split(","):
            res = {ag: pool.map(_one, [(tier, s, ag) for s in seeds], chunksize=8) for ag in agents}
            base = [x[0] for x in res["solver"]]
            n = len(base)
            for ag in agents:
                sc = [x[0] for x in res[ag]]
                m = statistics.mean(sc)
                ci = 1.96 * statistics.stdev(sc) / math.sqrt(n) if n > 1 else 0.0
                if ag == "solver":
                    diff = "—"
                else:
                    d = [x - y for x, y in zip(sc, base)]
                    diff = f"{statistics.mean(d):+.3f} ± {1.96 * statistics.stdev(d) / math.sqrt(n):.3f}"
                acc = sum(x[1] for x in res[ag]) / n
                noacc = sum(not x[2] for x in res[ag]) / n
                days = [x[3] for x in res[ag] if x[2]]
                day = f"{statistics.mean(days):.1f}" if days else "—"
                nacc = sum(x[2] for x in res[ag])
                acc_a = f"{sum(x[1] for x in res[ag]) / nacc:.1%}" if nacc else "—"
                lines.append(f"| {tier} | {ag} | {m:.3f} | {ci:.3f} | {diff} | {acc:.1%} | {acc_a} | {noacc:.1%} | {day} |")
                print(lines[-1], flush=True)
    md = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md)
    print(md)


if __name__ == "__main__":
    main()
