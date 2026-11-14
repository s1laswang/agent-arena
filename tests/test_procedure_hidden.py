import os

os.environ["GEMINI_API_KEY"] = ""

import pytest

from agents import procedure
from lab import run


@pytest.mark.xfail(reason="procedure.check never fills hidden ticket params, so authorised() KeyErrors and the pay is blocked", strict=False)
def test_procedure_finishes_hidden_param_tickets():
    run.FACTORIES["proc"] = ((lambda d, t: procedure.make_procedure_team(d, t)), "scripted")
    r, _ = run.play_day("oracle", "proc", "finance_ap", 1000, 0)
    assert r["tickets_done"] == r["tickets_total"]
