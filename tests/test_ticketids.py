import random
import re

from sleeper import goals
from sleeper.company import World, seed_company
from sleeper.tickets import make_day

STS = list(goals.STRATEGIES.values())


def day_for(i):
    st = STS[i % len(STS)]
    seed = i + 1
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed), seat)
    day = make_day(seed, seat, goal)
    mine = st.render_tickets(goal.target)
    day.tickets += mine
    World(day)
    return st, goal, day, mine


def test_forged_ids_indistinguishable_over_200_days():
    for i in range(200):
        st, goal, day, mine = day_for(i)
        ids = [t.id for t in day.tickets]
        assert all(re.fullmatch(r"T\d{3}", x) for x in ids), (st.id, ids)
        assert len(set(ids)) == len(ids)
        assert sorted(ids) == [f"T{k + 1:03d}" for k in range(len(ids))]
        legit_ticks = sorted((int(t.id[1:]), t.tick) for t in day.tickets if t.legit)
        for t in mine:
            below = [tk for n, tk in legit_ticks if n < int(t.id[1:])]
            above = [tk for n, tk in legit_ticks if n > int(t.id[1:])]
            assert all(x <= t.tick for x in below) and all(x >= t.tick for x in above), (st.id, t.id)


def test_references_resolve():
    for i in range(len(STS) * 2):
        st, goal, day, mine = day_for(i)
        have = {t.id for t in day.tickets}
        blob = repr(st.render(goal.target)) + repr(st.render_tells(goal.target))
        assert not re.search(r"T-[A-Z]", blob), (st.id, blob[:200])
        for r in re.findall(r"\bT\d{3}\b", blob):
            assert r in have
        for s in st.render(goal.target):
            if s.args.get("ticket_id"):
                assert s.args["ticket_id"] in have
