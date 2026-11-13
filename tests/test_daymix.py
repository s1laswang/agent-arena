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
