import pytest

from sleeper.baselines import play
from sleeper.company import World
from sleeper.models import SEATS, Ticket
from sleeper.tickets import make_day

SEEDS = range(20)


def test_hidden_params_not_in_tickets():
    day = make_day(0)
    t = day.tickets[0]
    t.hidden = [next(iter(t.params))]
    w = World(day)
    w.company.tick = t.tick
    key = t.hidden[0]
    mine = [x for x in w.t_my_tickets(t.seat)["tickets"] if x["id"] == t.id]
    assert mine and key not in mine[0]["params"]
    assert all(key not in x["params"] for x in w.t_list_tickets(t.seat)["tickets"] if x["id"] == t.id)


@pytest.mark.parametrize("seat", [None, "controller"])
def test_trust_all_zero_every_day(seat):
    assert [s for s in SEEDS if play("trust_all", s, None, seat, True)["reward"]] == []
