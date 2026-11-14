from scripts import gemini_reference_seat as g


def test_scripted_procedure_seat_scores(tmp_path):
    state, st, mcp, agent = g.play("finance_ap", 0, lambda d, s: g.make_procedure_team(d, seed=0)[s], tmp_path)
    r = g.verify(state, "finance_ap")
    assert "reward" in r and st["calls"] > 0 and mcp
