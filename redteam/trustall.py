import collections
import json
import multiprocessing as mp
import sys

from sleeper.models import SEATS


def one(a):
    day_id, seat, trial = a
    from lab import run
    d, strat, _, _m = run.day_for(day_id, seat)
    if seat == d.sleeper_seat:
        return None
    r, x = run.play_day("oracle", "trust_all", seat, day_id, trial)
    ev = sorted({(e.get("channel", "?"), e.get("kind", "?")) if isinstance(e, dict) else "?" for e in d.events})
    tk = sorted({t.kind for t in d.tickets if not t.legit})
    return {"day": day_id, "seat": seat, "trial": trial, "reward": r["reward"], "sleeper": r["sleeper_seat"], "goal": r["goal_kind"],
            "strategy": getattr(strat, "id", None), "harm": r["harm"], "harmful": x["harmful"], "done": r["tickets_done"], "total": r["tickets_total"],
            "events": [list(e) for e in ev], "bad_tickets": tk, "n_events": len(d.events)}


def main():
    lo, hi = 1000, 1049
    jobs = [(d, s, t) for d in range(lo, hi + 1) for s in SEATS for t in range(3)]
    with mp.Pool() as p:
        rows = [r for r in p.imap_unordered(one, jobs, chunksize=4) if r]
    json.dump(rows, open("redteam/trustall.json", "w"))
    byday = collections.defaultdict(list)
    for r in rows:
        byday[r["day"]].append(r)
    cls = collections.Counter()
    for d in sorted(byday):
        rs = byday[d]
        w = [r for r in rs if r["reward"] == 1]
        r0 = rs[0]
        if not r0["sleeper"]:
            c = "c nosleeper"
        elif not w:
            c = "lost"
        elif any(r["harmful"] for r in w):
            c = "b landed-no-harm"
        else:
            c = "a goal-not-landed"
        cls[c] += 1
        print(d, c, f"win {len(w)}/{len(rs)}", r0["goal"], r0["strategy"], "events", r0["events"], "bad_tickets", r0["bad_tickets"])
    print(cls)


if __name__ == "__main__":
    main()
