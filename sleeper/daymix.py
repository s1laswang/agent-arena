import random

from sleeper.goals import get

KINDS = ("fraud", "leak", "backdoor", "sabotage", "frame")


def entry(day_id, seat_under_test=None):
    if day_id % 5 == 4:
        return {"day_id": day_id, "seed": day_id, "sleeper_seat": None, "goal": None, "strategy": None}
    rng = random.Random(f"mix-{day_id}")
    kind = KINDS[(day_id // 5 * 4 + day_id % 5) % len(KINDS)]
    pool = sorted(get(kind), key=lambda s: s.id)
    if seat_under_test:
        pool = [s for s in pool if seat_under_test in s.needs_seats and set(s.seats) - {seat_under_test}] or pool
    s = rng.choice(pool)
    seat = rng.choice(sorted(set(s.seats) - {seat_under_test}))
    return {"day_id": day_id, "seed": day_id, "sleeper_seat": seat, "goal": kind, "strategy": s.id}


def mix(n, seat_under_test=None):
    return [entry(i, seat_under_test) for i in range(n)]


def day_spec(day_id, seat_under_test=None):
    from sleeper.company import seed_company
    from sleeper.goals import STRATEGIES, make_goal
    e = entry(day_id, seat_under_test)
    if e["sleeper_seat"] is None:
        return {**e, "goal": None, "strategy": None, "tickets": [], "winnable": True}
    s = STRATEGIES[e["strategy"]]
    goal = make_goal(s.kind, random.Random(e["seed"]), seed_company(e["seed"]))
    return {**e, "goal": goal, "strategy": s, "tickets": s.render_tickets(goal.target), "winnable": True}
