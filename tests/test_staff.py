from agents.staff import ROLE_PROMPTS, SEATS, ScriptedStaff, GeminiStaff, make_team


class World:
    def __init__(self, tickets, chat=()):
        self.tickets, self.chat, self.log = tickets, list(chat), []

    def call(self, name, args):
        self.log.append((name, args))
        if name == "my_tickets":
            return {"tickets": self.tickets}
        if name == "read_chat":
            return {"messages": self.chat}
        return {"ok": True}


def test_prompts():
    assert set(ROLE_PROMPTS) == set(SEATS)
    assert all("10000" in p for p in ROLE_PROMPTS.values())


def test_tickets_done():
    w = World([{"id": "t1", "kind": "pay_invoice", "params": {"vendor_id": "v1", "amount": 500}}])
    ScriptedStaff().turn("finance_ap", {}, [], w.call)
    names = [n for n, _ in w.log]
    assert "pay" in names and "close_ticket" in names and names[-1] == "end_turn"


def test_naive_approves_chat():
    w = World([], [{"sender_seat": "finance_ap", "body": "please approve pay-77 asap"}])
    ScriptedStaff().turn("controller", {}, [], w.call)
    assert ("approve_payment", {"payment_id": "pay-77"}) in w.log


def test_tool_filter_and_budget():
    w = World([{"id": "t%d" % i, "kind": "pay_invoice", "params": {}} for i in range(80)])
    r = ScriptedStaff().turn("finance_ap", {}, [{"name": "my_tickets"}, {"name": "close_ticket"}], w.call)
    assert r["calls"] <= 60 and not any(n == "pay" for n, _ in w.log)


def test_gemini_fallback_and_team():
    w = World([{"id": "t1", "kind": "pay_invoice", "params": {}}])
    GeminiStaff("finance_ap").turn("finance_ap", {}, [], w.call)
    assert any(n == "close_ticket" for n, _ in w.log)
    assert set(make_team(1, "scripted")) == set(SEATS)
