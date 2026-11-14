from sleeper.daymix import KINDS, mix
from sleeper.goals import STRATEGIES


def test_mix():
    m = mix(20)
    assert m == mix(20)
    assert sum(e["sleeper_seat"] is None for e in m) == 4
    assert {e["goal"] for e in m if e["goal"]} == set(KINDS)
    for e in m:
        if e["strategy"]:
            s = STRATEGIES[e["strategy"]]
            assert s.kind == e["goal"] and e["sleeper_seat"] in s.seats


def test_seat_mode():
    for e in mix(40, "controller"):
        assert e["sleeper_seat"] != "controller"


def test_never_controller_sleeper():
    assert all(e["sleeper_seat"] != "controller" for e in mix(60))


def test_day_spec():
    from sleeper.daymix import day_spec
    for i in range(10):
        d = day_spec(i)
        assert (d["goal"] is None) == (d["sleeper_seat"] is None) and d["winnable"]
        if d["goal"]:
            assert d["goal"].kind == d["strategy"].kind


def test_covers_every_strategy():
    used = {e["strategy"] for e in mix(5 * 4 * 8)}
    assert used >= set(STRATEGIES) - {s for s in STRATEGIES if not set(STRATEGIES[s].seats) - {"controller"}}


def test_seat_mode_is_gated():
    from sleeper.daymix import accomplices
    from sleeper.models import SEATS
    for seat in SEATS:
        for e in mix(20, seat):
            if e["strategy"]:
                assert seat in accomplices(STRATEGIES[e["strategy"]]) and e["sleeper_seat"] != seat
