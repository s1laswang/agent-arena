from sleeper import goals
from sleeper.tickets import make_day

KNOWN_MISSING = {"pay_invoice_scan"}


def legit_shapes():
    shapes = {}
    for seed in range(12):
        for t in make_day(seed).tickets:
            if t.legit:
                shapes.setdefault(t.kind, set()).update(set(t.params) - {"requested_by", "ticket_id"})
    return shapes


def attack_tickets():
    for s in goals.STRATEGIES.values():
        for t in s.tickets:
            yield s.id, t


def test_attack_kinds_are_legit_kinds():
    legit = legit_shapes()
    bad = {(sid, t["kind"]) for sid, t in attack_tickets() if t["kind"] not in legit and t["kind"] not in KNOWN_MISSING}
    assert not bad, bad


def test_param_keys_match_legit():
    legit = legit_shapes()
    bad = [(sid, t["kind"], sorted(set(t["params"]) - {"requested_by", "ticket_id", "doc_id"})) for sid, t in attack_tickets()
           if t["kind"] in legit and set(t["params"]) - {"requested_by", "ticket_id"} != legit[t["kind"]]]
    assert not bad, bad
