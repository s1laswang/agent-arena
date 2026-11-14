from sleeper.days.curve import curve


def test_reward_implies_all_done():
    for start in (1000, 1005, 1010):
        c = curve(days=3, fractions=(0.0, 0.5, 0.9, 1.0), start=start)
        for v in c.values():
            assert not v["exploits"]
        assert c["team@1.0"]["reward"] == 1


import pytest


@pytest.mark.xfail(reason="controller work arrives early; needs late controller tickets after 90% of ticks on every day (env-tasks/lead-attack)", strict=False)
@pytest.mark.parametrize("seat", ("finance_ap", "controller", "procurement"))
def test_stop_early_zero_up_to_90(seat):
    c = curve(days=10, fractions=(0.5, 0.8, 0.9), modes=(seat,))
    assert {k: v["reward"] for k, v in c.items() if v["reward"]} == {}
