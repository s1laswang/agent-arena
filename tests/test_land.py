import random

import pytest

from agents.reference import make_oracle_team
from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent
from sleeper.tickets import make_day
from sleeper.verifier import score

KINDS = ("sabotage", "frame")
IDS = [i for i, s in goals.STRATEGIES.items() if s.kind in KINDS]


def play(seed, sid, team):
    st = goals.STRATEGIES[sid]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed), seat)
    day = make_day(seed, seat, goal)
    day.tickets += st.render_tickets(goal.target)
    if team == "oracle":
        members = make_oracle_team(day)
    elif team == "scripted_oracle":
        members = {s: OracleAgent() for s in SEATS}
    else:
        members = {s: ScriptedStaff(s) for s in SEATS}
    members[seat] = SleeperAgent(seat, goal, st, random.Random(seed))
    w = run_day(day, members)
    return goal.success(w.company, w.ledger), score(day, w.initial, w.company, w.ledger).reward


def table(seeds=range(1, 6)):
    out = []
    for sid in IDS:
        out.append((sid,) + tuple(sum(play(s, sid, t)[0] for s in seeds) for t in ("staff", "scripted_oracle", "oracle")))
    return out


@pytest.mark.parametrize("sid", IDS)
def test_fails_vs_oracle(sid):
    for seed in range(1, 4):
        assert play(seed, sid, "oracle")[0] is False
        assert play(seed, sid, "scripted_oracle")[0] is False


@pytest.mark.xfail(reason="needs ScriptedStaff weaknesses from hn-defender", strict=False)
@pytest.mark.parametrize("sid", IDS)
def test_lands_vs_staff(sid):
    assert sum(play(s, sid, "staff")[0] for s in range(1, 4)) >= 2


if __name__ == "__main__":
    for r in table():
        print("%-34s staff %d/5  scripted_oracle %d/5  oracle %d/5" % r)
