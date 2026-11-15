"""One-rule-removed agents: the full rule ladder agent (L7) with exactly one rule turned off.

The cumulative ladder (agents/ladder.py) shows what each rule adds on top of the ones before it.
This shows the other direction: does the complete agent still need each rule? If dropping a rule
costs reward with a paired CI that excludes 0, that rule is load-bearing. If not, the task does not
test it on these seeds. Same days, same seat, same scripted team; only the one rule changes.

usage: python -m agents.ladder_drop --days 100 [--jobs 4]  ->  results/ladder_drop.md / .json
"""
import os

os.environ["GEMINI_API_KEY"] = ""
import argparse
import json
import subprocess
from pathlib import Path

from agents import ladder as L
from agents import procedure as P
from agents.staff import SEATS

DROPS = list(range(2, len(L.RULES)))  # L2..L7; L0/L1 are the base, not rules


class DropOne(L.LadderStaff):
    def __init__(self, seat, ev, drop):
        super().__init__(seat, ev, L.TOP)
        self.drop = drop
        gone = set(L.RULES[drop][2] or ())
        self.on = tuple(x for x in self.on if x not in gone)
        if drop == 6:
            self.quarantine = False
            self.audit = lambda *a, **k: None
        if drop == 3:
            self.repair = lambda *a, **k: None
        if drop == 7:
            self.rule = lambda *a, **k: None


def make_team(drop, day=None, trial=0):
    ev = P.Evidence()
    return {s: DropOne(s, ev, drop) for s in SEATS}


def register():
    from lab import run

    L.register()
    for k in DROPS:
        run.FACTORIES["drop%d" % k] = ((lambda d, t, k=k: make_team(k, d, t)), "scripted")


def table(days, start, seat, jobs):
    register()
    from multiprocessing import Pool

    names = ["ladder%d" % L.TOP] + ["drop%d" % k for k in DROPS]
    out = []
    with Pool(jobs, initializer=register) as pool:
        for n in names:
            rows = pool.map(L._one, [(n, seat, d) for d in range(start, start + days)], chunksize=4)
            rw = [r for r, _ in rows]
            m, h = L.ci(rw)
            out.append({"team": n, "rewards": rw, "mean": m, "ci": h, "harm_rate": sum(h for _, h in rows) / len(rows)})
    return out


def render(t, seat, commit, days, start):
    full = t[0]
    lines = [f"seat: {seat or 'all'}, commit {commit}, n={days} days from {start}, command: python -m agents.ladder_drop --days {days}", "",
             "| agent | rule removed | mean | CI95 | harm rate | change vs full agent (paired bootstrap CI95) | load-bearing? |",
             "|---|---|---|---|---|---|---|",
             f"| full (L{L.TOP}) | none | {full['mean']:.3f} | ±{full['ci']:.3f} | {full['harm_rate']:.2f} | | |"]
    for k, r in zip(DROPS, t[1:]):
        d, lo, hi = L.paired(full, r)
        verdict = "yes" if hi < 0 else ("no effect on these seeds" if (lo, hi) == (0.0, 0.0) else "not shown (CI includes 0)")
        lines.append(f"| L{L.TOP} minus L{k} | {L.RULES[k][1]} | {r['mean']:.3f} | ±{r['ci']:.3f} | {r['harm_rate']:.2f} | {d:+.3f} [{lo:+.3f}, {hi:+.3f}] | {verdict} |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=100)
    p.add_argument("--start", type=int, default=1000)
    p.add_argument("--out", default="results")
    p.add_argument("--jobs", type=int, default=4)
    a = p.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    res, md = {}, ""
    for seat in ("finance_ap", None):
        t = table(a.days, a.start, seat, a.jobs)
        res[seat or "all"] = t
        md += render(t, seat, commit, a.days, a.start) + "\n"
    from agents import gemini

    assert gemini.usage()["calls"] == 0, "gemini was called"
    Path(a.out).mkdir(exist_ok=True)
    Path(a.out, "ladder_drop.json").write_text(json.dumps({"commit": commit, "days": a.days, "start": a.start, "tables": res}, indent=1))
    Path(a.out, "ladder_drop.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
