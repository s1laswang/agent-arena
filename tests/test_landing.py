import pytest

from scripts.landing_table import play


@pytest.mark.parametrize("day_id", range(10))
def test_oracle_wins_every_day(day_id):
    r, _ = play(day_id, "oracle")
    assert r["reward"] == 1


@pytest.mark.parametrize("day_id", [0, 2, 3, 7])
def test_sleeper_lands_on_staff(day_id):
    r, _ = play(day_id, "staff")
    assert r["landed"] == 1 and r["reward"] == 0


def test_base64_leak_is_harm():
    r, _ = play(1, "staff")
    assert r["landed"] == 1 and r["reward"] == 0
