from sleeper.days.curve import curve


def test_curve_zero_below_full():
    for start in (0, 20, 40):
        c = curve(days=3, fractions=(0.0, 0.5, 0.9, 1.0), start=start)
        for v in c.values():
            assert not v["exploits"]
            if v["fraction"] < 1:
                assert v["reward"] == 0
