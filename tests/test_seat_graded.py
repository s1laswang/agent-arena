import pytest

from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.scripted import NoopAgent, OracleAgent
from sleeper.tickets import make_day
from sleeper.verifier import score


def test_every_seat_has_three_graded_tickets():
    for seed in range(1, 21):
        seats = [t.seat for t in make_day(seed).tickets if t.legit]
        assert all(seats.count(s) >= 3 for s in SEATS), seed


@pytest.mark.parametrize("seat", SEATS)
def test_noop_seat_scores_zero_and_oracle_scores_one(seat):
    for seed in range(1, 21):
        d = make_day(seed)
        w = run_day(d, {s: (NoopAgent() if s == seat else OracleAgent()) for s in SEATS})
        assert score(d, w.initial, w.company, w.ledger).reward == 0, (seat, seed)
    d = make_day(1)
    w = run_day(d, {s: OracleAgent() for s in SEATS})
    assert score(d, w.initial, w.company, w.ledger).reward == 1
