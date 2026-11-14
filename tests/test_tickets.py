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


def test_noop_seat_fails_its_own_tickets():
    from sleeper.day import run_day
    from sleeper.scripted import NoopAgent, OracleAgent, make_team
    from sleeper.tickets import done
    for s in range(3):
        d = make_day(s)
        for seat in SEATS:
            assert sum(t.seat == seat for t in d.tickets) >= 3
            team = make_team(OracleAgent)
            team[seat] = NoopAgent()
            w = run_day(d, team)
            assert any(not done(t, w.company) for t in d.tickets if t.seat == seat), (s, seat)


def test_ceo_board_notice_seeds():
    from sleeper.day import run_day
    from sleeper.scripted import NoopAgent, OracleAgent, make_team
    from sleeper.tickets import done
    for s in range(20):
        d = make_day(s)
        mine = [t for t in d.tickets if t.kind == "board_notice"]
        assert len(mine) == 1
        assert all(done(t, run_day(d, make_team(OracleAgent)).company) for t in mine)
        team = make_team(OracleAgent)
        team["ceo_assistant"] = NoopAgent()
        assert not any(done(t, run_day(d, team).company) for t in mine)
