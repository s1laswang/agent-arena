"""Sleeper seat / strategy prior per judged seat, from the public daymix only (Harbor-like 62-bit ids)."""
import collections
import random

from sleeper.daymix import entry

SEATS = "finance_ap controller hr procurement sales legal".split()
rng = random.Random(5)
ids = [rng.getrandbits(62) for _ in range(20000)]
for seat in SEATS:
    sl = collections.Counter()
    st = collections.Counter()
    for d in ids:
        e = entry(d, seat)
        sl[e["sleeper_seat"]] += 1
        st[e["strategy"]] += 1
    n_sl = sum(v for k, v in sl.items() if k)
    top, topn = max(((k, v) for k, v in sl.items() if k), key=lambda x: x[1])
    print(f"{seat:12s} sleeper days {n_sl / len(ids):.3f}  best constant guess {top} right on {topn / n_sl:.3f} of sleeper days")
    print("     sleeper dist:", {k: round(v / len(ids), 3) for k, v in sl.most_common()})
    print("     strategies  :", len([k for k in st if k]), {k: round(v / len(ids), 3) for k, v in st.most_common()})
