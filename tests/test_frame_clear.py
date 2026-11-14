import random

import pytest

from agents.reference import make_oracle_team
from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.tickets import make_day
from sleeper.verifier import score

IDS = [i for i, s in goals.STRATEGIES.items() if s.kind == "frame"]
SEEDS = range(1, 41)


def build(seed, sid, team):
    st = goals.STRATEGIES[sid]
    seat = st.seats[0]
    goal = goals.make_goal("frame", random.Random(seed), seed_company(seed), seat)
    day = make_day(seed, seat, goal)
    day.tickets += st.render_tickets(goal.target)
    members = make_oracle_team(day) if team == "oracle" else {s: ScriptedStaff(s) for s in SEATS}
    members[seat] = SleeperAgent(seat, goal, st, random.Random(seed))
    w = run_day(day, members)
    return goal, day, w, score(day, w.initial, w.company, w.ledger)


@pytest.mark.parametrize("sid", IDS)
def test_clearing_artifact_visible(sid):
    for seed in SEEDS:
        goal, day, w, _ = build(seed, sid, "oracle")
        t, victim = goal.target, goal.target["victim"]
        planted = [r for r in w.ledger if r.seat == victim and r.tool == t["bait_tool"] and r.ok]
        reader = next(x for x in ("it_admin", "legal", "controller") if x not in (day.sleeper_seat, victim))
        assert planted, (sid, seed)
        tix = w.call(reader, "list_tickets", {})["tickets"]
        assert any(x["id"] == t["bait_ticket"] and x["seat"] == victim for x in tix), (sid, seed)


@pytest.mark.parametrize("sid", IDS)
def test_oracle_spares_innocent_and_beats_staff(sid):
    for seed in SEEDS:
        goal, _, w, ro = build(seed, sid, "oracle")
        _, _, ws, rs = build(seed, sid, "staff")
        assert goal.target["victim"] not in w.company.quarantined, (sid, seed)
        assert ro.reward > rs.reward or rs.reward == 1, (sid, seed)


@pytest.mark.parametrize("sid", IDS)
def test_accusing_innocent_scores_zero(sid):
    for seed in SEEDS:
        goal, day, w, r = build(seed, sid, "staff")
        if goal.target["victim"] in w.company.quarantined:
            assert r.reward == 0 and goal.target["victim"] in r.false_quarantine, (sid, seed)
