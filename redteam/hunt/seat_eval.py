"""In-process seat-mode eval on Harbor-like day ids (random 62-bit), procedure background.

usage: seat_eval.py N agent1,agent2 [seats]
"""
import collections
import random
import sys

from lab.run import play_day

N = int(sys.argv[1])
agents = sys.argv[2].split(",")
seats = (sys.argv[3] if len(sys.argv) > 3 else "finance_ap,controller,hr,procurement,sales,legal").split(",")
extra = sys.argv[4] if len(sys.argv) > 4 else None
if extra:
    import importlib
    importlib.import_module(extra).register()

rng = random.Random(int(__import__("os").environ.get("RT_SEED", "11")))
ids = [rng.getrandbits(62) for _ in range(N)]
for seat in seats:
    for ag in agents:
        tot = 0
        lost = collections.Counter()
        for d in ids:
            r = play_day("procedure", ag, seat, d, 0)[0]
            tot += r["reward"]
            if not r["reward"]:
                lost[(r.get("strategy"), r.get("sleeper_seat"), tuple(h.split(":")[0] for h in r["harm"][:3]), r["tickets_done"] == r["tickets_total"])] += 1
        print(f"{seat:12s} {ag:22s} {tot}/{N} = {tot / N:.3f}", flush=True)
        for k, v in lost.most_common(6):
            print("      lost", v, k, flush=True)
