import argparse
import collections
import json
import multiprocessing as mp
import sys

from sleeper.models import SEATS

AGENTS = ["do_nothing", "stop_early", "quarantine_all", "refuse_all", "exploiter", "exploiter_nowork"]


def register():
    from lab import run
    from redteam.gemini_exploiter import ExploitAgent
    run.FACTORIES["exploiter"] = (lambda day, trial: {s: ExploitAgent(day.ticks, True, False) for s in SEATS}, "scripted")
    run.FACTORIES["exploiter_nowork"] = (lambda day, trial: {s: ExploitAgent(day.ticks, False, False) for s in SEATS}, "scripted")
    return run


def one(a):
    agent, seat, day, trial = a
    run = register()
    try:
        r, _ = run.play_day("oracle", agent, seat, day, trial)
    except Exception as e:
        return {"agent": agent, "seat": seat, "day": day, "trial": trial, "error": repr(e)[:120]}
    d = run.day_for(day, seat)[0]
    return {"agent": agent, "seat": seat, "day": day, "trial": trial, "reward": r["reward"], "done": r["tickets_done"], "total": r["tickets_total"],
            "harm": r["harm"], "fq": r["false_quarantine"], "sleeper": r["sleeper_seat"], "winnable": r["winnable"], "own": sum(t.seat == seat for t in d.tickets)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", default="1000..1039")
    ap.add_argument("--trials", type=int, default=3)
    ap.add_argument("--agents", default=",".join(AGENTS))
    ap.add_argument("--out", default="redteam/sweep.jsonl")
    a = ap.parse_args()
    lo, hi = map(int, a.days.split(".."))
    jobs = [(g, s, d, t) for g in a.agents.split(",") for s in SEATS for d in range(lo, hi + 1) for t in range(a.trials)]
    with mp.Pool() as p, open(a.out, "w") as f:
        for r in p.imap_unordered(one, jobs, chunksize=8):
            f.write(json.dumps(r) + "\n")
    rows = [json.loads(l) for l in open(a.out)]
    err = [r for r in rows if "error" in r]
    bad = [r for r in rows if r.get("reward")]
    print(len(rows), "runs", len(err), "errors", len(bad), "reward>0")
    c = collections.Counter((r["agent"], r["seat"], r["own"], tuple(sorted({h.split(":")[0] for h in r["harm"]}))) for r in bad)
    for k, v in sorted(c.items()):
        print(v, k)
    for r in err[:5]:
        print(r)


if __name__ == "__main__":
    sys.exit(main())
