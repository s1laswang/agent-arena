import pytest
from tests.seat_e2e import run

EXPECT = {"oracle": 1, "nop": 0, "stop_early": 0}


@pytest.mark.parametrize("seat", ["finance_ap", "controller"])
@pytest.mark.parametrize("kind", list(EXPECT))
def test_sidecar_reward(seat, kind, tmp_path):
    r = run(seat, kind, team="oracle", out=str(tmp_path / "s.json"))
    assert r["reward"] == EXPECT[kind] and r["seat_under_test"] == seat


def test_staff_in_seat_below_oracle(tmp_path):
    from sleeper.daymix import entry

    days = [d for d in range(40) if entry(d, "finance_ap")["strategy"]][:8]
    rewards = [run("finance_ap", "staff", seed=d, out=str(tmp_path / "s.json"))["reward"] for d in days]
    assert 0 in rewards, (days, rewards)
