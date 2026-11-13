import random

import pytest

from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent
from sleeper.tickets import make_day


def play(seed, strategy_id, team_cls):
    st = goals.STRATEGIES[strategy_id]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    day = make_day(seed, seat)
    object.__setattr__(day, "goal", goal)
    team = {s: team_cls(s) if team_cls is ScriptedStaff else team_cls() for s in SEATS}
    team[seat] = SleeperAgent(seat, goal, st, random.Random(seed))
    w = run_day(day, team)
    return goal.success(w.company, w.ledger)


def table(seeds=range(1, 6)):
    rows = []
    for sid in goals.STRATEGIES:
        rows.append((sid, sum(play(s, sid, ScriptedStaff) for s in seeds), sum(play(s, sid, OracleAgent) for s in seeds)))
    return rows


@pytest.mark.parametrize("sid", list(goals.STRATEGIES))
def test_runs(sid):
    play(1, sid, ScriptedStaff)


if __name__ == "__main__":
    for r in table():
        print("%-36s staff %d/5  oracle %d/5" % r)
