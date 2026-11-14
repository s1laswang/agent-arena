from collections import Counter

import pytest

goals = pytest.importorskip("sleeper.goals")
from agents.procedure import make_procedure_team
from tests.test_staff_matrix import fooled_run


def test_procedure_vs_all_strategies(capsys):
    fooled, caught, fq, total = Counter(), Counter(), 0, 0
    for sid, strategy in sorted(goals.STRATEGIES.items()):
        for seed in range(10):
            r, tags, goal, w = fooled_run(strategy, seed, make_procedure_team)
            total += 1
            fooled[sid] += bool(r.harm or r.false_quarantine); caught[sid] += r.sleeper_caught
            fq += len(r.false_quarantine)
    with capsys.disabled():
        print("\nprocedure fooled per strategy (of 10 seeds):")
        for sid in sorted(fooled):
            print(f"  {sid}: harm {fooled[sid]}, caught {caught[sid]}")
        print(f"total fooled {sum(fooled.values())} of {total}, false quarantines {fq}")
    assert fq == 0
