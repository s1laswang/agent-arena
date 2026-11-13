import random

import pytest

from agents.reference import make_oracle_team
from agents.sleeper_agent import SleeperAgent
from scripts.landing_table import ProcurementApproves
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.tickets import make_day
from sleeper.verifier import score

TICKS = 10
SHIFT = 8


def sleeper_day(seed, sid):
    st = goals.STRATEGIES[sid]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    st = st.model_copy(update={"steps": [x.model_copy(update={"tick": max(0, x.tick - SHIFT)}) for x in st.steps]})
    day = make_day(seed, seat).model_copy(update={"goal": goal, "ticks": TICKS})
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
        return {s: ProcurementApproves(s) for s in SEATS}
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
    print(format_matrix(matrix(), 10))
