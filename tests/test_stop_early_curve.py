from sleeper.days.curve import curve


def test_reward_implies_all_done():
    for start in (1000, 1005, 1010):
        c = curve(days=3, fractions=(0.0, 0.5, 0.9, 1.0), start=start)
        for v in c.values():
            assert not v["exploits"]
            if v["fraction"] < 1 and v["mode"] == "team":
                assert v["reward"] == 0
