import random

import pytest

from sleeper import goals
from sleeper.company import World, seed_company
from sleeper.daymix import accomplices, sleeper_seats
from sleeper.day import play_round
from sleeper.models import Doc
from sleeper.scripted import NoopAgent
from sleeper.tickets import make_day

SEED = 7


class Steps:
    def __init__(self, steps):
        self.steps = steps

    def turn(self, seat, view, tools, call):
        for st in self.steps:
            if st.tick == view["tick"]:
                call(st.tool, st.args)
        call("end_turn", {})


def run(strat, tested, sleeper, trusts):
    goal = goals.make_goal(strat.kind, random.Random(SEED), seed_company(SEED), sleeper, voter=tested)
    day = make_day(SEED, sleeper, goal)
    day.tickets += strat.render_tickets(goal.target)
    w = World(day)
    for d in strat.render_docs(goal.target):
        doc = Doc(**{k: v for k, v in d.items() if k != "image_lines"})
        w.company.docs[doc.id] = doc
        w.initial.docs[doc.id] = doc.model_copy(deep=True)
    steps = strat.render(goal.target)
    if tested not in {x.seat for x in steps}:
        return None
    team = {s: Steps([x for x in steps if x.seat == s]) for s in accomplices(strat)}
    team[sleeper] = Steps([x for x in steps if not x.seat])
    team[tested] = Steps([x for x in steps if x.seat == tested]) if trusts else NoopAgent()
    while w.tick < max(x.tick for x in steps) + 1:
        play_round(w, team)
    return goal.success(w.company, w.ledger)


CASES = [(s.id, seat) for s in goals.STRATEGIES.values() for seat in sorted(accomplices(s) - {"{voter}"} | ({"controller", "it_admin"} if "{voter}" in accomplices(s) else set())) if sleeper_seats(s, seat)]


@pytest.mark.parametrize("sid,seat", CASES)
def test_judge_seat_decides(sid, seat):
    s = goals.STRATEGIES[sid]
    sl = sleeper_seats(s, seat)[0]
    if run(s, seat, sl, True) is None:
        pytest.skip("seat is not the victim-adjacent voter")
    assert run(s, seat, sl, True), "trust-everything must succeed"
    assert not run(s, seat, sl, False), "refuse-everything must fail"
