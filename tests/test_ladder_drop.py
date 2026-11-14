from agents import ladder as L
from agents import procedure as P
from agents.ladder_drop import DROPS, DropOne, render


def test_drop_one_turns_off_only_that_rule():
    full = L.LadderStaff("finance_ap", P.Evidence(), L.TOP)
    for k in DROPS:
        a = DropOne("finance_ap", P.Evidence(), k)
        assert set(a.on) == set(full.on) - set(L.RULES[k][2] or ()), k
        assert a.level == L.TOP
    assert DropOne("finance_ap", P.Evidence(), 7).rule("pay", {}, None, {}) is None
    assert DropOne("finance_ap", P.Evidence(), 6).quarantine is False
    assert DropOne("finance_ap", P.Evidence(), 5).quarantine is True


def test_render_marks_load_bearing_rules():
    full = {"team": "ladder7", "rewards": [1.0] * 20, "mean": 1.0, "ci": 0.0, "harm_rate": 0.0}
    drops = [{"team": f"drop{k}", "rewards": [0.0 if k == 4 else 1.0] * 20, "mean": 0.0 if k == 4 else 1.0, "ci": 0.0, "harm_rate": 0.0} for k in DROPS]
    md = render([full] + drops, "finance_ap", "abc", 20, 1000)
    assert "| L7 minus L4 |" in md and "| yes |" in md
    assert "no effect on these seeds" in md
