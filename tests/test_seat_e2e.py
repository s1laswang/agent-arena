import pytest
from tests.seat_e2e import run

EXPECT = {"oracle": 1, "nop": 0, "stop_early": 0}


@pytest.mark.parametrize("seat", ["finance_ap", "controller"])
@pytest.mark.parametrize("kind", list(EXPECT))
def test_sidecar_reward(seat, kind, tmp_path):
    r = run(seat, kind, team="oracle", out=str(tmp_path / "s.json"))
    assert r["reward"] == EXPECT[kind] and r["seat_under_test"] == seat


def test_staff_in_seat_below_oracle(tmp_path):
    assert run("finance_ap", "staff", seed=5, out=str(tmp_path / "s.json"))["reward"] == 0
