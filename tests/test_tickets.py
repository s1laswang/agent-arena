from sleeper.models import SEATS
from sleeper.tickets import make_day


def test_deterministic():
    assert make_day(3).model_dump() == make_day(3).model_dump()
    assert make_day(3).model_dump() != make_day(4).model_dump()


def test_size_and_seats():
    for s in range(30):
        d = make_day(s)
        assert 40 <= len(d.tickets) <= 60
        assert {t.seat for t in d.tickets} == set(SEATS)
        assert all(0 <= t.tick <= 20 for t in d.tickets)
        assert len({t.id for t in d.tickets}) == len(d.tickets)


def test_oracle_solves_every_ticket():
    from sleeper.day import run_day
    from sleeper.scripted import OracleAgent, make_team
    from sleeper.tickets import done
    for s in range(20):
        d = make_day(s)
        w = run_day(d, make_team(OracleAgent))
        bad = [t.id + t.kind for t in d.tickets if not done(t, w.company)]
        assert not bad, (s, bad)


def test_do_nothing_fails():
    from sleeper.day import run_day
    from sleeper.scripted import NoopAgent, make_team
    from sleeper.tickets import done
    d = make_day(0)
    w = run_day(d, make_team(NoopAgent))
    assert not any(done(t, w.company) for t in d.tickets)


def test_day_list():
    from sleeper.tickets import day_list
    d = day_list(20)
    assert d == day_list(20)
    none = [x for x in d if x[1] is None]
    assert 3 <= len(none) <= 9
    assert len({x[1] for x in d if x[1]}) >= 6
    assert len({x[2] for x in d if x[2]}) == 5


def test_goal_day_builds():
    from sleeper.tickets import day_list
    for seed, seat, kind in day_list(20):
        d = make_day(seed, seat, kind)
        assert (d.goal is None) == (kind is None)
        assert make_day(seed, seat, kind).model_dump(exclude={"goal"}) == d.model_dump(exclude={"goal"})
