from collections import defaultdict

from sleeper import goals
from sleeper.company import seed_company
from sleeper.tickets import REQUESTERS, authorised, make_day

import random


def shape(v):
    return "external" if str(v).startswith("external:") else "seat"


def attack_tickets():
    out = []
    for s in goals.STRATEGIES.values():
        g = goals.make_goal(s.kind, random.Random(3), seed_company(3), s.seats[0])
        out += [(s, t) for t in s.render_tickets(g.target)]
    return out


def test_every_legit_ticket_has_requested_by():
    for seed in range(1, 21):
        for t in make_day(seed).tickets:
            assert "requested_by" in t.params, (seed, t.id)


def test_same_key_sets_per_kind():
    legit = defaultdict(set)
    for seed in range(1, 21):
        for t in make_day(seed).tickets:
            legit[t.kind].add(frozenset(t.params))
    for s, t in attack_tickets():
        assert "requested_by" in t.params
        if t.kind in legit:
            ref = {k for ks in legit[t.kind] for k in ks}
            assert set(t.params) <= ref, (s.id, t.kind, set(t.params) - ref)


def test_requested_by_shapes_overlap():
    legit = {shape(t.params["requested_by"]) for seed in range(1, 21) for t in make_day(seed).tickets}
    assert legit == {"seat", "external"}
    assert {shape(t.params["requested_by"]) for _, t in attack_tickets()} <= legit


def test_attack_requesters_are_not_authorised():
    for s, t in attack_tickets():
        if t.kind == "new_account" and "admin" in t.params.get("roles", []):
            continue
        assert not authorised(t.kind, t.params["requested_by"]) or t.kind not in REQUESTERS, (s.id, t.kind, t.params["requested_by"])
