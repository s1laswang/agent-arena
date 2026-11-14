import pytest

from sleeper.day import run_day
from sleeper.scripted import NoopAgent, OracleAgent, make_team
from sleeper.tickets import done, make_day
from sleeper.verifier import score


class NoRead(OracleAgent):
    def fill(self, t, call):
        return t


def play(seed, cls):
    day = make_day(seed)
    return day, run_day(day, make_team(cls))


def hidden(day):
    return [t for t in day.tickets if t.hidden]


def test_share_hidden():
    n = sum(len(hidden(make_day(s))) for s in range(20))
    tot = sum(len([t for t in make_day(s).tickets if t.legit]) for s in range(20))
    assert 0.1 < n / tot < 0.4


@pytest.mark.parametrize("seed", range(20))
def test_my_tickets_hides_values(seed):
    from sleeper.company import World
    day = make_day(seed)
    w = World(day)
    w.company.tick = day.ticks
    for t in hidden(day):
        got = next(x for x in w.call(t.seat, "my_tickets")["tickets"] if x["id"] == t.id)
        assert not set(t.hidden) & set(got["params"]) and got["hidden"] == t.hidden
        assert all(str(t.params[k]) not in t.request for k in t.hidden)


@pytest.mark.parametrize("seed", range(20))
def test_reader_wins_nonreader_loses(seed):
    day, w = play(seed, OracleAgent)
    assert all(done(t, w.company) for t in hidden(day))
    day, w = play(seed, NoRead)
    assert hidden(day) and not any(done(t, w.company) for t in hidden(day))
    assert score(day, w.initial, w.company, w.ledger).reward == 0
