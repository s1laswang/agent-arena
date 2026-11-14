import os

os.environ["GEMINI_API_KEY"] = ""

from agents import procedure
from lab import run


def test_procedure_finishes_hidden_param_tickets():
    run.FACTORIES["proc"] = ((lambda d, t: procedure.make_procedure_team(d, t)), "scripted")
    r, _ = run.play_day("oracle", "proc", "finance_ap", 1000, 0)
    assert r["tickets_done"] == r["tickets_total"]
