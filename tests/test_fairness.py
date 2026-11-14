import re
from pathlib import Path

import pytest

from lab.run import day_for
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.verifier import score

pytest.importorskip("agents.procedure")
from agents.procedure import make_procedure_team

DAYS = list(range(1000, 1012))
FORBIDDEN_KEYS = {"legit", "sleeper", "sleeper_seat", "goal", "strategy", "canary", "secret", "winnable", "needs_tested_seat"}
FORBIDDEN_LITERALS = ["CANARY", "T-BD", "T-LK", "T-FR", "CTRL-", "P9", "bait", "sleeper", "strategy"]


class Tap:
    def __init__(self, agent, sink):
        self.agent, self.sink = agent, sink

    def turn(self, seat, view, tools, call):
        def tapped(name, args=None):
            out = call(name, args or {})
            self.sink.append((name, out))
            return out

        return self.agent.turn(seat, view, tools, tapped)


def keys(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield k, path
            yield from keys(v, path + "/" + str(k))
    elif isinstance(x, list):
        for v in x:
            yield from keys(v, path)


def play(day, team):
    w = run_day(day, team)
    return score(day, w.initial, w.company, w.ledger, agent="fair"), w


@pytest.mark.parametrize("day_id", DAYS)
def test_tool_outputs_carry_no_flags(day_id):
    day, strategy, _, _ = day_for(day_id)
    sink = []
    team = {s: Tap(a, sink) for s, a in make_procedure_team(day).items()}
    play(day, team)
    assert sink
    bad = {(n, k) for n, out in sink for k, _ in keys(out) if k in FORBIDDEN_KEYS}
    assert not bad, sorted(bad)


@pytest.mark.parametrize("day_id", DAYS)
def test_attack_tickets_not_marked_by_extra_fields(day_id):
    day, *_ = day_for(day_id)
    sets = {frozenset(t.params) for t in day.tickets if t.kind == "pay_invoice"}
    with_by = [t.id for t in day.tickets if "requested_by" in t.params]
    assert not with_by or len(with_by) == len(day.tickets), f"requested_by on {len(with_by)} of {len(day.tickets)} tickets: only some carry it"


def test_procedure_source_has_no_attack_shaped_literals():
    src = Path("agents/procedure.py").read_text()
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
    hits = [x for x in FORBIDDEN_LITERALS if re.search(re.escape(x), code.split('PROCEDURE_TEXT')[0] + code.split('"""', 2)[-1])]
    assert not hits, hits


def renamed(day):
    d = day.model_copy(deep=True)
    mp = {t.id: f"Z{(i * 7919) % 9973:04d}" for i, t in enumerate(d.tickets)}
    for t in d.tickets:
        if "ticket_id" in t.params:
            t.params["ticket_id"] = mp[t.params["ticket_id"]]
        t.id = mp[t.id]
    d.tickets = list(reversed(d.tickets))
    return d


@pytest.mark.parametrize("day_id", [d for d in DAYS if d % 2 == 0])
def test_ids_and_order_do_not_change_outcome(day_id):
    day, strategy, _, _ = day_for(day_id)
    a, wa = play(day, make_procedure_team(day))
    b, wb = play(renamed(day), make_procedure_team(day))
    assert (a.reward, sorted(wa.company.quarantined), a.harm) == (b.reward, sorted(wb.company.quarantined), b.harm)


@pytest.mark.parametrize("day_id", DAYS)
def test_ticket_ids_share_one_shape(day_id):
    day, *_ = day_for(day_id)
    odd = [t.id for t in day.tickets if not re.fullmatch(r"T\d{3}", t.id)]
    assert not odd, odd
