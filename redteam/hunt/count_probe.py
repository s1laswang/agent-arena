"""Does the number of tickets in the day (learnable at tick 0 by probing close_ticket on T050..T053:
'not your ticket' = exists, 'bad arguments' = does not) tell sleeper days apart?"""
import collections
import random

from lab.run import day_for
from sleeper.company import World

rng = random.Random(3)
ids = [rng.getrandbits(62) for _ in range(400)]
for seat in "finance_ap controller hr procurement sales legal".split():
    c = collections.Counter()
    for d in ids:
        day = day_for(d, seat)[0]
        c[(len(day.tickets), day.sleeper_seat is not None)] += 1
    print(seat, sorted(c.items()))

# show the probe answers on one day through the real World.call
day = day_for(ids[0], "finance_ap")[0]
w = World(day)
print("n tickets", len(day.tickets), "sleeper day", day.sleeper_seat is not None)
for i in (49, 50, 51, 52, 53):
    print(f"T{i:03d}", w.call("finance_ap", "close_ticket", {"id": f"T{i:03d}", "note": "x"}))
