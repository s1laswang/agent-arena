import random

from sleeper.goals import STRATEGIES, get

KINDS = ("fraud", "leak", "backdoor", "sabotage", "frame")
NEVER_SLEEPER = {"controller"}


def accomplices(s):
    return {x.seat for x in s.steps if x.seat and x.seat != "{victim}"}


def sleeper_seats(s, seat_under_test=None):
    return sorted(set(s.seats) - NEVER_SLEEPER - {seat_under_test})


def gated(seat):
    return sorted((s for s in STRATEGIES.values() if (seat in accomplices(s) or "{voter}" in accomplices(s)) and sleeper_seats(s, seat)), key=lambda s: s.id)


def no_sleeper(day_id):
    return {"day_id": day_id, "seed": day_id, "sleeper_seat": None, "goal": None, "strategy": None, "needs_tested_seat": False}


def entry(day_id, seat_under_test=None):
    if day_id % 5 == 4:
        return no_sleeper(day_id)
    k = day_id // 5 * 4 + day_id % 5
    if seat_under_test:
        kinds = [x for x in KINDS if any(s.kind == x for s in gated(seat_under_test))]
        if not kinds:
            return no_sleeper(day_id)
        kind = kinds[k % len(kinds)]
        pick = [s for s in gated(seat_under_test) if s.kind == kind]
        s = pick[k // len(kinds) % len(pick)]
    else:
        kind = KINDS[k % len(KINDS)]
        pick = [s for s in sorted(get(kind), key=lambda s: s.id) if sleeper_seats(s)]
        s = pick[k // len(KINDS) % len(pick)]
    seat = random.Random(f"mix-{day_id}").choice(sleeper_seats(s, seat_under_test))
    return {"day_id": day_id, "seed": day_id, "sleeper_seat": seat, "goal": kind, "strategy": s.id, "needs_tested_seat": bool(seat_under_test)}


def mix(n, seat_under_test=None):
    return [entry(i, seat_under_test) for i in range(n)]


def day_spec(day_id, seat_under_test=None):
    from sleeper.company import seed_company
    from sleeper.goals import make_goal
    e = entry(day_id, seat_under_test)
    if e["sleeper_seat"] is None:
        return {**e, "goal": None, "strategy": None, "tickets": [], "winnable": True}
    s = STRATEGIES[e["strategy"]]
    goal = make_goal(s.kind, random.Random(e["seed"]), seed_company(e["seed"]), sleeper_seat=e["sleeper_seat"], voter=seat_under_test)
    return {**e, "goal": goal, "strategy": s, "tickets": s.render_tickets(goal.target), "winnable": True}
