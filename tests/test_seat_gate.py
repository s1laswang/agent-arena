from lab.run import play_day
from sleeper.company import SEATS


def test_do_nothing_zero_every_seat():
    for s in SEATS:
        for d in range(1000, 1020):
            r, _ = play_day("oracle", "do_nothing", s, d, 0)
            assert r["reward"] == 0, (s, d, r["harm"])


def test_seat_is_sleeper_zero():
    for d in range(1000, 1040):
        r, _ = play_day("oracle", "do_nothing", None, d, 0)
        s = r["sleeper_seat"]
        if s:
            r, _ = play_day("oracle", "do_nothing", s, d, 0)
            assert r["reward"] == 0, (s, d)
            return


def test_baselines_zero_every_seat_20_days():
    from sleeper.baselines import register

    register()
    for name in ("stop_early", "refuse_all", "claim_only", "quarantine_all"):
        for s in SEATS:
            for d in range(1000, 1020):
                r, _ = play_day("oracle", name, s, d, 0)
                assert r["reward"] == 0, (name, s, d)
