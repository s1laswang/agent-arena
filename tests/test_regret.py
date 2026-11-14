from sleeper.regret import evaluate, filter_candidates

C = {"seed": 1, "sleeper_seat": "hr", "goal": "fraud", "strategy": "s1"}


def fake(table):
    def run_day(seed, team, seat, goal, strategy, run=0):
        v = table.get(team, 0)
        return v if not callable(v) else v(run)
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


def test_no_sleeper_and_summary():
    from sleeper.regret import summary
    n = {"seed": 1, "sleeper_seat": None, "goal": None, "strategy": None}
    e = evaluate(n, fake({"oracle": 1}))
    assert e["type"] == "no_sleeper" and e["verdict"] == "kept"
    kept, dropped = filter_candidates([C, n], fake({"oracle": 1, "reference": 1, "staff": 0}))
    s = summary(kept, dropped)
    assert s["no_sleeper"]["kept"] == 1 and s["sleeper"]["fraud"]["mean_regret"] == 1.0


def test_object_strategy_and_mutate():
    from pydantic import BaseModel
    from sleeper.regret import mutate_round, cid

    class S(BaseModel):
        id: str
        t: int

    c = {"seed": 1, "sleeper_seat": "hr", "goal": "fraud", "strategy": S(id="a", t=0)}
    kept, _ = filter_candidates([c], fake({"oracle": 1, "reference": 1, "staff": 0}))
    mk, md = mutate_round(kept, fake({"oracle": 1, "reference": 1, "staff": 0}), lambda s, seed: S(id=s.id, t=seed + 5))
    assert len(mk) == 1 and cid(mk[0]) != kept[0]["id"]


def test_blind_diligence_dropped():
    from sleeper.regret import evaluate
    c = {"seed": 1, "sleeper_seat": "finance_ap", "goal": "fraud", "strategy": "s"}
    e = evaluate(c, fake({"oracle": 1, "reference": 1, "staff": 0, "trust_all": 1}), 3)
    assert e["verdict"] == "dropped" and e["reason"] == "blind_diligence_wins"
