import sys
from collections import Counter

import sleeper.goals as g
from agents.procedure import make_procedure_team
from agents.staff import make_team
from tests.test_staff_matrix import fooled_run

SEEDS = range(3)
for label, f in (("staff", make_team), ("procedure", make_procedure_team)):
    harm, runs, fq, per = 0, 0, 0, Counter()
    for sid, st in sorted(g.STRATEGIES.items()):
        for seat in st.seats:
            for seed in SEEDS:
                r, _, _, _ = fooled_run(st, seed, f, seat)
                runs += 1
                harm += bool(r.harm)
                per[sid] += bool(r.harm)
                fq += len(r.false_quarantine)
    print(label, "harm", harm, "of", runs, "false quarantines", fq)
    print({k: v for k, v in per.items() if v})
