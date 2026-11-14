"""Timing tell for seats with list_tickets but no audit log (legal).

Honest background staff (agents/procedure.py ProcedureStaff.polls) only touch tickets when tick % 3 == 0
or tick >= 18. The scripted sleeper closes its tickets on every tick. So the first close of a ticket on
a tick outside the poll set is the sleeper. Legal sees the closed flag flip via list_tickets.

usage: legal_study.py N seat
"""
import collections
import random
import sys

from lab.run import play_day

N = int(sys.argv[1])
seat = sys.argv[2] if len(sys.argv) > 2 else "legal"
rng = random.Random(29)
ids = [rng.getrandbits(62) for _ in range(N)]
POLL = lambda t: t % 3 == 0 or t >= 18
c = collections.Counter()
when = []
for d in ids:
    r, ex = play_day("procedure", "reference", seat, d, 0)
    first = {}
    for a in ex["ledger"]:
        if a["tool"] == "close_ticket" and a["ok"] and a["seat"] != seat:
            tid = (a["args"] or {}).get("id")
            first.setdefault(tid, (a["seat"], a["tick"]))
    flagged = {}
    for s, t in first.values():
        if not POLL(t):
            flagged.setdefault(s, t)
            flagged[s] = min(flagged[s], t)
    truth = r["sleeper_seat"]
    if truth is None:
        c["no_sleeper: flagged=%s" % sorted(flagged)] += 1
    else:
        c["sleeper: flagged==truth %s" % (sorted(flagged) == [truth])] += 1
        if truth in flagged:
            when.append(flagged[truth])
print(dict(c))
print("tick of first off-poll close by the sleeper:", sorted(collections.Counter(when).items()))
