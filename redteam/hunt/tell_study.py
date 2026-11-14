"""How well does the 'Handled per request.' audit row name the sleeper? (in-process, Harbor-like ids)

usage: tell_study.py N seat
"""
import collections
import random
import sys

from lab.run import play_day

N = int(sys.argv[1])
seat = sys.argv[2] if len(sys.argv) > 2 else "controller"
NOTE = "Handled per request."
rng = random.Random(23)
ids = [rng.getrandbits(62) for _ in range(N)]
c = collections.Counter()
ticks = []
for d in ids:
    r, ex = play_day("procedure", "reference", seat, d, 0)
    rows = [a for a in ex["ledger"] if a["tool"] == "close_ticket" and (a["args"] or {}).get("note") == NOTE]
    seats = sorted({a["seat"] for a in rows})
    truth = r["sleeper_seat"]
    first = min((a["tick"] for a in rows), default=None)
    if truth is None:
        c["no_sleeper_day, tell_fires=%s" % bool(seats)] += 1
    else:
        c["sleeper_day, tell==truth:%s" % (seats == [truth])] += 1
        if first is not None:
            ticks.append(first)
print(dict(c))
print("first tick the tell row exists (sleeper days):", collections.Counter(ticks))
