from sleeper.models import SEATS
from sleeper.tickets import make_day


def test_deterministic():
    assert make_day(3).model_dump() == make_day(3).model_dump()
    assert make_day(3).model_dump() != make_day(4).model_dump()


def test_size_and_seats():
    for s in range(30):
        d = make_day(s)
        assert 40 <= len(d.tickets) <= 60
        assert {t.seat for t in d.tickets} == set(SEATS)
        assert all(0 <= t.tick <= 20 for t in d.tickets)
        assert len({t.id for t in d.tickets}) == len(d.tickets)
