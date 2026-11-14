import pytest

from lab.run import play_day
from sleeper import baselines
from sleeper.models import SEATS

baselines.register()


def test_noop_all_eight():
    bad = [d for d in range(20) if play_day("do_nothing", "do_nothing", None, d, 0)[0]["reward"] != 0]
    assert not bad, bad


@pytest.mark.parametrize("seat", SEATS)
def test_noop_seat_mode(seat):
    bad = [d for d in range(20) if play_day("staff", "do_nothing", seat, d, 0)[0]["reward"] != 0]
    assert not bad, (seat, bad)
