import random

from sleeper.goals import STRATEGIES, get

KINDS = ("fraud", "leak", "backdoor", "sabotage", "frame")
NEVER_SLEEPER = {"controller"}


def accomplices(s):
    return {x.seat for x in s.steps if x.seat and x.seat != "{victim}"}


def sleeper_seats(s, seat_under_test=None):
    return sorted(set(s.seats) - NEVER_SLEEPER - {seat_under_test})


NOT_DECISIVE = {
    ("controller", "fraud.bank_swap"),
    ("controller", "fraud.over10k_release"),
    ("controller", "fraud.forged_scanned_invoice"),
    ("controller", "fraud.ticket_vendor_pay"),
    ("controller", "fraud.split_under_limit"),
    ("finance_ap", "fraud.urgent_ceo_request"),
}


def gated(seat):
    return sorted((s for s in STRATEGIES.values() if (seat, s.id) not in NOT_DECISIVE and (seat in accomplices(s) or "{voter}" in accomplices(s)) and sleeper_seats(s, seat)), key=lambda s: s.id)


def no_sleeper(day_id):
    return {"day_id": day_id, "seed": day_id, "sleeper_seat": None, "goal": None, "strategy": None, "needs_tested_seat": False}


def entry(day_id, seat_under_test=None):
    if day_id % 5 == 4:
        return no_sleeper(day_id)
    k = day_id // 5 * 4 + day_id % 5
    pool = gated(seat_under_test) if seat_under_test else sorted(STRATEGIES.values(), key=lambda s: s.id)
    seats = sorted({x for s in pool for x in sleeper_seats(s, seat_under_test)})
    if not seats:
        return no_sleeper(day_id)
    seat = seats[k % len(seats)]
    cand = [s for s in pool if seat in sleeper_seats(s, seat_under_test)]
    support = {x: len({y for s in pool if s.kind == x for y in sleeper_seats(s, seat_under_test)}) for x in KINDS}
    seen = {}
    key = {}
    for x in sorted(cand, key=lambda x: x.id):
        key[x.id] = seen.get(x.kind, 0)
        seen[x.kind] = key[x.id] + 1
    cand.sort(key=lambda x: (key[x.id], support[x.kind], x.kind, x.id))
    s = cand[k // len(seats) % len(cand)]
    kind = s.kind
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
