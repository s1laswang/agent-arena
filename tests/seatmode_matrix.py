import sys
from collections import Counter

import sleeper.goals as g
from agents.procedure import make_procedure_team
from agents.staff import SEATS, make_team
from tests.test_staff_matrix import fooled_run

SEEDS = range(3)


def run(label, factory, seat_filter=None):
    harm, runs, fq = 0, 0, 0
    for sid, st in sorted(g.STRATEGIES.items()):
        for seat in st.seats:
            for seed in SEEDS:
                r, _, _, _ = fooled_run(st, seed, factory, seat)
                runs += 1
                harm += bool(r.harm)
                fq += len(r.false_quarantine)
    print(f"{label}: harm {harm} of {runs}, false quarantines {fq}")


def mixed(S, quarantine):
    def f(day, seed):
        t = make_team(day, seed)
        t[S] = make_procedure_team(day, seed, quarantine)[S]
        return t
    return f


if __name__ == "__main__":
    run("all staff", make_team)
    run("all procedure", make_procedure_team)
    for S in SEATS:
        run(f"procedure in {S}, staff elsewhere", mixed(S, False))
