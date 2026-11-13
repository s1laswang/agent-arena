import asyncio
import json
from sleeper.mcp_server import ARGS, build_server

SHARED = ["read_chat", "post_chat", "end_turn", "my_tickets"]
TOOLS = {"controller": SHARED + ["approve_payment", "edit_contract"], "finance_ap": SHARED + ["pay"]}


class FakeWorld:
    def __init__(self):
        self.tick = 0
        self.last_tick = 2
        self.company = {"tick": 0}
        self.ledger = [{"seq": 0}]
        self.calls = []

    def tools(self, seat):
        return TOOLS[seat]

    def call(self, seat, tool, args):
        self.calls.append((seat, tool, args))
        if tool == "end_turn":
            self.tick += 1
        return {"ok": True, "tool": tool}


def run(coro):
    return asyncio.run(coro)


def test_tools_per_seat():
    names = lambda s: sorted(t.name for t in run(build_server(FakeWorld(), s).list_tools()))
    assert names("controller") == sorted(TOOLS["controller"])
    assert names("finance_ap") == sorted(TOOLS["finance_ap"])
    assert "read_ledger" not in ARGS


def test_call_and_seat_mode(tmp_path):
    w = FakeWorld()
    stepped = []
    out = tmp_path / "s.json"
    srv = build_server(w, "finance_ap", step_others=lambda w, s: stepped.append(s), out=str(out))
    r = run(srv.call_tool("pay", {"vendor_id": "v1", "amount": 5.0, "reference": "r"}))
    assert w.calls[0] == ("finance_ap", "pay", {"vendor_id": "v1", "amount": 5.0, "reference": "r"})
    assert stepped == ["finance_ap"]
    run(srv.call_tool("end_turn", {}))
    assert not out.exists()
    run(srv.call_tool("end_turn", {}))
    assert json.loads(out.read_text())["ledger"] == [{"seq": 0}]


def test_budget(tmp_path):
    w = FakeWorld()
    out = tmp_path / "b.json"
    srv = build_server(w, "controller", step_others=lambda *a: None, out=str(out))
    for _ in range(60):
        run(srv.call_tool("read_chat", {}))
    assert out.exists()
    n = len(w.calls)
    run(srv.call_tool("read_chat", {}))
    assert len(w.calls) == n
