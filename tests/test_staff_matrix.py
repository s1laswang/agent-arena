import random
from collections import Counter

import pytest

goals = pytest.importorskip("sleeper.goals")
from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff, make_team
from sleeper.company import World, seed_company
from sleeper.day import run_day
from sleeper.tickets import make_day
from sleeper.verifier import score


def fooled_run(strategy, seed, factory=make_team, seat=None):
    seat = seat or strategy.seats[0]
    base = make_day(seed)
    company = seed_company(seed)
    goal = goals.make_goal(strategy.kind, random.Random(f"g{seed}"), company, seat) if strategy.kind in ("backdoor",) or True else None
    rendered = strategy.model_copy(update={"steps": strategy.render(goal.target)})
    day = base.model_copy(update={"sleeper_seat": seat, "goal": goal, "tickets": base.tickets + strategy.render_tickets(goal.target)})
    team = factory(day, seed)
    team[seat] = SleeperAgent(seat, goal, rendered)
    staff = [a for s, a in team.items() if s != seat and hasattr(a, 'log')]
    w = run_day(day, team)
    r = score(day, w.initial, w.company, w.ledger)
    tags = {x["weakness"] for a in staff for x in a.log}
    return r, tags, goal, w


def test_staff_vs_all_strategies(capsys):
    fooled, tags_n, total = Counter(), Counter(), 0
    for sid, strategy in sorted(goals.STRATEGIES.items()):
        for seed in range(10):
            r, tags, goal, w = fooled_run(strategy, seed)
            total += 1
            succ = goal.success(w.company, w.ledger)
            fooled[sid] += succ
            if succ:
                tags_n.update(tags)
    with capsys.disabled():
        print("\nstaff fooled per strategy (of 10 seeds):")
        for sid in sorted(fooled):
            print(f"  {sid}: {fooled[sid]}")
        print("weakness tags on fooled days:", dict(tags_n))
        print(f"total fooled {sum(fooled.values())} of {total}")
