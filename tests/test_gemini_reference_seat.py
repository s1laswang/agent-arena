from scripts import gemini_reference_seat as g


def test_scripted_procedure_seat_scores(tmp_path):
    state, st, mcp, agent = g.play("finance_ap", 0, lambda d, s: g.make_procedure_team(d, seed=0)[s], tmp_path)
    r = g.verify(state, "finance_ap")
    assert "reward" in r and st["calls"] > 0 and mcp


def test_build_day_has_sleeper():
    from scripts.frontier_day import build_day

    world, team, strategy = build_day("finance_ap", 0)
    assert world.day.sleeper_seat and strategy
