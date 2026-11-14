from sleeper.company import World, tools_for
from sleeper.scripted import OracleAgent
from sleeper.tickets import make_day
from scripts.cli_seat import rescore


def test_replay_oracle_seat():
    w = World(make_day(0))
    calls = []

    def call(tool, args):
        calls.append({"tool": tool, "args": args, "result": None})
        return w.call("finance_ap", tool, args)

    OracleAgent().turn("finance_ap", None, tools_for("finance_ap"), call)
    s = rescore({"mcp_calls": calls, "seat": "finance_ap", "seed": 0, "model": "oracle"})
    assert s["tickets_total"] > 0 and "reward" in s
