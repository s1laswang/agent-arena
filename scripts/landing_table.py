import random
import re
import sys

from agents.reference import make_oracle_team
from agents.sleeper_agent import SleeperAgent
from agents.staff import ScriptedStaff
from sleeper import goals
from sleeper.company import seed_company
from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.tickets import make_day
from sleeper.verifier import score


class ProcurementApproves(ScriptedStaff):
    def _message(self, seat, m, c):
        b = m.get("body", "")
        if seat == "procurement" and "approve_vendor" in b and m.get("sender_seat") != seat:
            v = re.search(r"\b(V\d{2,})\b", b)
            if v and c("approve_vendor", {"vendor_id": v.group(1)}).get("ok"):
                self.tag(seat, "trusted_familiar_name", vendor=v.group(1))
            return
        return super()._message(seat, m, c)


def play(seed, sid, team_kind, ticks=10, shift=8):
    st = goals.STRATEGIES[sid]
    seat = st.seats[0]
    goal = goals.make_goal(st.kind, random.Random(seed), seed_company(seed))
    st = st.model_copy(update={"steps": [x.model_copy(update={"tick": max(0, x.tick - shift)}) for x in st.steps]})
    day = make_day(seed, seat)
    day = day.model_copy(update={"goal": goal, "ticks": ticks})
    extra = st.render_tickets(goal.target)
    if extra:
        day = day.model_copy(update={"tickets": list(day.tickets) + extra})
    team = make_oracle_team(day) if team_kind == "oracle" else {s: ProcurementApproves(s) for s in SEATS}
    team[seat] = SleeperAgent(seat, goal, st, random.Random(seed))
    w = run_day(day, team)
    r = score(day, w.initial, w.company, w.ledger, agent=team_kind)
    return int(bool(goal.success(w.company, w.ledger))), r.reward


def main(seeds=range(10), only=None, ticks=10):
    for sid in goals.STRATEGIES:
        if only and not sid.startswith(only):
            continue
        cells = {k: [play(s, sid, k, ticks) for s in seeds] for k in ("staff", "oracle")}
        print("%-34s staff landed %d reward %d | oracle landed %d reward %d (of %d)" % (
            sid, sum(a for a, _ in cells["staff"]), sum(b for _, b in cells["staff"]),
            sum(a for a, _ in cells["oracle"]), sum(b for _, b in cells["oracle"]), len(list(seeds))))


if __name__ == "__main__":
    main(only=sys.argv[1] if len(sys.argv) > 1 else None)
