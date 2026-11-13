from sleeper.regret import evaluate, filter_candidates

C = {"seed": 1, "sleeper_seat": "hr", "goal": "fraud", "strategy": "s1"}


def fake(table):
    def run_day(seed, team, seat, goal, strategy, run=0):
        return table[team] if not callable(table[team]) else table[team](run)
    return run_day


def test_unbeatable_dropped():
    e = evaluate(C, fake({"oracle": 0, "reference": 1, "staff": 0}))
    assert e["reason"] == "unbeatable"


def test_no_gap_flagged():
    e = evaluate(C, fake({"oracle": 1, "reference": 1, "staff": 1}))
    assert e["reason"] == "no_gap"


def test_good_kept():
    kept, dropped = filter_candidates([C], fake({"oracle": 1, "reference": 1, "staff": lambda r: r % 2}))
    assert len(kept) == 1 and not dropped
    assert kept[0]["regret"] > 0 and kept[0]["staff_fails"] == 2


def test_deterministic():
    f = fake({"oracle": 1, "reference": 1, "staff": 0})
    assert evaluate(C, f) == evaluate(C, f)
