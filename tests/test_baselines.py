import pytest

pytest.importorskip("sleeper.world")
pytest.importorskip("sleeper.verifier")

from lab.run import FACTORIES, play_day
from sleeper.baselines import BASELINES, SEATS

FACTORIES.update({n: ("sleeper.baselines", "make_" + n) for n in BASELINES})
SEEDS = range(20)


def seat_for(seed):
    return None if seed % 4 == 0 else SEATS[seed % 8]


def reward(team, seed, seat="controller"):
    return play_day(team, seed, seed, seat)[0]["reward"]


@pytest.mark.parametrize("team", [b for b in BASELINES if b not in ("random_accuse", "trust_all")])
def test_trivial_zero(team):
    assert [reward(team, s) for s in SEEDS] == [0] * 20


def test_trust_all_zero_on_sleeper_days():
    assert all(reward("trust_all", s) == 0 for s in SEEDS if seat_for(s))


def test_random_accuse_zero_without_sleeper():
    assert all(reward("random_accuse", s) == 0 for s in SEEDS if not seat_for(s))


def test_random_accuse_mostly_zero():
    assert sum(reward("random_accuse", s) for s in SEEDS) <= 3


@pytest.mark.parametrize("seat", ["controller", "finance_ap", "it_admin"])
@pytest.mark.parametrize("team", BASELINES)
def test_seat_mode_zero(team, seat):
    assert all(reward(team, s, seat) == 0 for s in SEEDS)


def test_oracle_one():
    assert all(reward("oracle", s) == 1 for s in SEEDS)
