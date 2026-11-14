import random

import pytest

from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent as _O
from sleeper.tickets import make_day


class OracleAgent(_O):
    def work(self, t, call):
        if t["kind"] in ("pay_invoice", "update_employee", "new_account", "share_contract"):
            super().work(t, call)


def play(seed, strategy_id, team_cls):
    st = goals.STRATEGIES[strategy_id]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    day = make_day(seed, seat)
    object.__setattr__(day, "goal", goal)
    day.tickets.extend(st.render_tickets(goal.target))
    team = {s: team_cls(s) if team_cls is ScriptedStaff else team_cls() for s in SEATS}
    team[seat] = SleeperAgent(seat, goal, st, random.Random(seed), ticks=day.ticks)
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


CONTROLLER_IDS = ["fraud.over10k_release", "leak.controller_audit_request", "backdoor.controller_cosign", "sabotage.controller_cosign"]


def play_ctrl(seed, sid, controller):
    st = goals.STRATEGIES[sid]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    day = make_day(seed, seat)
    object.__setattr__(day, "goal", goal)
    day.tickets.extend(st.render_tickets(goal.target))
    team = {s: ScriptedStaff(s) for s in SEATS}
    team[seat] = SleeperAgent(seat, goal, st, random.Random(seed), ticks=day.ticks)
    team["controller"] = controller
    w = run_day(day, team)
    return goal.success(w.company, w.ledger)


@pytest.mark.parametrize("sid", CONTROLLER_IDS)
def test_controller_is_the_gate(sid):
    from sleeper.scripted import NoopAgent

    assert all(play_ctrl(s, sid, ScriptedStaff("controller")) for s in (1, 2, 3))
    assert not any(play_ctrl(s, sid, NoopAgent()) for s in (1, 2, 3))
