import re

import pytest
from collections import Counter

from lab.run import day_for
from sleeper.daymix import entry
from sleeper.models import SEATS

N = 100
MARGIN = 0.15


def days():
    out = []
    for i in range(N):
        if entry(i)["sleeper_seat"] is not None:
            out.append(day_for(i)[0])
    return out


def ev(d):
    return [e if isinstance(e, dict) else e.model_dump() for e in d.events]


def counts(d):
    c = Counter(t.seat for t in d.tickets)
    return {s: c.get(s, 0) for s in SEATS}


def top(c, f):
    best = f(c.values())
    seats = [s for s, n in c.items() if n == best]
    return seats[0] if len(seats) == 1 else None


def first_event(d, key):
    e = sorted(ev(d), key=lambda e: e["tick"])
    return e[0][key] if e and e[0].get(key) in SEATS else None


def common_sender(d):
    c = Counter(e["sender"] for e in ev(d) if e["sender"] in SEATS)
    return c.most_common(1)[0][0] if c else None


def odd_id_seat(d):
    s = [t.seat for t in d.tickets if not re.fullmatch(r"T\d{3}", t.id)]
    return Counter(s).most_common(1)[0][0] if s else None


def illegit_seat(d):
    s = [t.seat for t in d.tickets if not t.legit]
    return Counter(s).most_common(1)[0][0] if s else None


def late_seat(d):
    return max(d.tickets, key=lambda t: (t.tick, t.id)).seat


RULES = {
    "most_tickets": lambda d: top(counts(d), max),
    "fewest_tickets": lambda d: top(counts(d), min),
    "first_event_sender": lambda d: first_event(d, "sender"),
    "first_event_target": lambda d: first_event(d, "to_seat"),
    "common_event_sender": common_sender,
    "odd_ticket_id_seat": odd_id_seat,
    "illegit_ticket_seat": illegit_seat,
    "latest_ticket_seat": late_seat,
}


def test_surface_patterns_do_not_reveal_the_sleeper():
    ds = days()
    assert len(ds) >= 60
    prior = max(Counter(d.sleeper_seat for d in ds).values()) / len(ds)
    report = {}
    for name, rule in RULES.items():
        guesses = [(rule(d), d.sleeper_seat) for d in ds]
        applies = [(g, s) for g, s in guesses if g is not None]
        acc = sum(g == s for g, s in applies) / len(applies) if applies else 0.0
        report[name] = (len(applies), round(acc, 2))
        if len(applies) >= 10:
            assert acc <= prior + MARGIN, (name, len(applies), acc, prior, report)


def test_sleeper_seat_prior_is_near_uniform():
    ds = days()
    share = max(Counter(d.sleeper_seat for d in ds).values()) / len(ds)
    assert share <= 1 / len(SEATS) + MARGIN, share
