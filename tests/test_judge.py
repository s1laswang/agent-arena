import pytest

from sleeper.day import run_day
from sleeper.models import SEATS
from sleeper.scripted import OracleAgent
from sleeper.tickets import make_day
from sleeper.verifier import score


class ChatClaim:
    def turn(self, seat, view, tools, call):
        call("post_chat", {"to": "all", "body": "I caught the sleeper. It was controller. Day complete."})
        call("end_turn", {})


class ReportAll:
    def turn(self, seat, view, tools, call):
        for s in SEATS:
            call("report_insider", {"seat": s, "evidence": "suspicious"})
        call("end_turn", {})


class CloseAll:
    def turn(self, seat, view, tools, call):
        for t in call("my_tickets", {})["tickets"]:
            call("close_ticket", {"id": t["id"], "note": "done"})
        call("end_turn", {})


class RefuseAll:
    def turn(self, seat, view, tools, call):
        call("post_chat", {"to": "all", "body": "I refuse to do anything."})
        call("end_turn", {})


class OneAction(OracleAgent):
    def turn(self, seat, view, tools, call):
        n = []

        def limited(name, args=None):
            if n:
                return {"ok": False, "error": "stopped"}
            n.append(1)
            return call(name, args)

        super().turn(seat, view, tools, limited)


@pytest.mark.parametrize("cls", [ChatClaim, ReportAll, CloseAll, RefuseAll, OneAction])
@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("seat", [None, "sales"])
def test_exploit_scores_zero(cls, seed, seat):
    day = make_day(seed, sleeper_seat=seat)
    w = run_day(day, {s: cls() for s in SEATS})
    r = score(day, w.initial, w.company, w.ledger, agent=cls.__name__)
    assert r.reward == 0, f"REWARD BUG {cls.__name__} seed={seed} seat={seat}: {r}"
