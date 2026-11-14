from agents.staff import ScriptedStaff
import random

import pytest

from agents.reference import make_oracle_team
from agents.sleeper_agent import SleeperAgent
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.tickets import make_day
from sleeper.verifier import score

TICKS = None
SHIFT = 0


def sleeper_day(seed, sid):
    st = goals.STRATEGIES[sid]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    st = st.model_copy(update={"steps": [x.model_copy(update={"tick": max(0, x.tick - SHIFT)}) for x in st.steps]})
    day = make_day(seed, seat).model_copy(update={"goal": goal, **({"ticks": TICKS} if TICKS else {})})
    extra = st.render_tickets(goal.target)
    if extra:
        day = day.model_copy(update={"tickets": list(day.tickets) + extra})
    return day, st, goal, seat


def scrub(day):
    return day.model_copy(update={"sleeper_seat": None, "goal": None, "events": [],
                                  "tickets": [t.model_copy(update={"legit": True}) for t in day.tickets]})


def team_for(kind, day, seed=0):
    if kind == "oracle":
        return make_oracle_team(day)
    if kind == "staff":
        return {s: ScriptedStaff(s) for s in SEATS}
    from agents.procedure import make_procedure_team
    return make_procedure_team(day, seed=seed)


def play(seed, sid, kind, scrubbed=False):
    day, st, goal, seat = sleeper_day(seed, sid)
    team = team_for(kind, scrub(day) if scrubbed else day, seed)
    team[seat] = SleeperAgent(seat, goal, st, random.Random(seed))
    w = run_day(day, team)
    r = score(day, w.initial, w.company, w.ledger, agent=kind)
    log = [(a.tick, a.seat, a.tool, repr(sorted(a.args.items())), a.ok) for a in w.ledger]
    return {"reward": r.reward, "harm": len(r.harm), "caught": r.sleeper_caught, "landed": bool(goal.success(w.company, w.ledger)),
            "fq": r.false_quarantine, "log": log}


def test_procedure_ignores_hidden_info():
    pytest.importorskip("agents.procedure")
    for sid in ("fraud.bank_swap", "leak.share_doc_external", "backdoor.newhire_piggyback", "frame.false_whisper"):
        for seed in (1, 2):
            a, b = play(seed, sid, "procedure"), play(seed, sid, "procedure", scrubbed=True)
            assert a["log"] == b["log"], (sid, seed)


def test_no_sleeper_days_no_quarantine():
    pytest.importorskip("agents.procedure")
    from agents.procedure import make_procedure_team
    for seed in range(20):
        day = make_day(seed)
        w = run_day(day, make_procedure_team(day, seed=seed))
        assert w.company.quarantined == [], seed


TESTED = ("controller", "legal", "it_admin", "finance_ap")


def seat_strategies(tested):
    return [s for s in sorted(goals.STRATEGIES.values(), key=lambda x: x.id) if tested in s.needs_seats and set(s.seats) - {tested}]


def play_seat(seed, sid, tested, kind):
    from agents.reference import make_oracle_seat
    from agents.staff import make_team as staff_team
    st = goals.STRATEGIES[sid]
    seat = sorted(set(st.seats) - {tested})[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    st = st.model_copy(update={"steps": [x.model_copy(update={"tick": max(0, x.tick - SHIFT)}) for x in st.steps]})
    day = make_day(seed, seat).model_copy(update={"goal": goal, **({"ticks": TICKS} if TICKS else {})})
    extra = st.render_tickets(goal.target)
    if extra:
        day = day.model_copy(update={"tickets": list(day.tickets) + extra})
    team = staff_team(day, seed, kind="scripted")
    if kind == "oracle":
        team[tested] = make_oracle_seat(day, tested)
    elif kind == "procedure":
        from agents.procedure import make_procedure_team
        team[tested] = make_procedure_team(scrub(day), seed=seed, quarantine=False)[tested]
    team[seat] = SleeperAgent(seat, goal, st, random.Random(seed))
    w = run_day(day, team)
    r = score(day, w.initial, w.company, w.ledger, agent=kind, seat_under_test=tested)
    return {"reward": r.reward, "harm": len(r.harm), "fq": len(r.false_quarantine), "caught": r.sleeper_caught}


def seat_matrix(kinds, seeds=range(5), seats=TESTED):
    lines = []
    for tested in seats:
        for st in seat_strategies(tested):
            cells = []
            for k in kinds:
                rs = [play_seat(sd, st.id, tested, k) for sd in seeds]
                cells.append("%s r%d h%d fq%d" % (k[:4], sum(r["reward"] for r in rs), sum(r["harm"] > 0 for r in rs), sum(r["fq"] > 0 for r in rs)))
            lines.append("%-11s %-34s " % (tested, st.id) + " | ".join(cells) + " (of %d)" % len(list(seeds)))
    return "\n".join(lines)


def test_seat_matrix_runs():
    kinds = ["staff", "oracle"]
    try:
        import agents.procedure
        kinds.insert(1, "procedure")
    except ImportError:
        pass
    out = seat_matrix(kinds, range(2))
    assert out
    print(out)


def matrix(kinds=("staff", "procedure", "oracle"), seeds=range(10)):
    rows = []
    for sid in goals.STRATEGIES:
        cells = {}
        for k in kinds:
            rs = [play(s, sid, k) for s in seeds]
            cells[k] = (sum(r["reward"] for r in rs), sum(r["harm"] > 0 for r in rs), sum(r["caught"] for r in rs), sum(bool(r["fq"]) for r in rs))
        rows.append((sid, cells))
    return rows


def format_matrix(rows, n):
    out = []
    for sid, cells in rows:
        out.append("%-34s " % sid + " | ".join("%s r%d h%d c%d fq%d" % ((k[:4],) + v) for k, v in cells.items()) + " (of %d)" % n)
    return "\n".join(out)


def test_matrix_runs():
    kinds = ["staff", "oracle"]
    try:
        import agents.procedure
        kinds.insert(1, "procedure")
    except ImportError:
        pass
    rows = matrix(kinds, range(3))
    assert len(rows) == len(goals.STRATEGIES)
    print(format_matrix(rows, 3))


if __name__ == "__main__":
    import sys
    if "seat" in sys.argv:
        print(seat_matrix(["staff", "procedure", "oracle"] if __import__("importlib").util.find_spec("agents.procedure") else ["staff", "oracle"]))
    else:
        print(format_matrix(matrix(), 10))
