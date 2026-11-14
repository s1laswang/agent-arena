from agents import staff
from lab import hint


def test_ablate_scripted(tmp_path):
    saved = dict(staff.ROLE_PROMPTS)
    try:
        hint.apply("verify_bank")
        assert all("Hint: " + hint.HINTS["verify_bank"][1] in p for p in staff.ROLE_PROMPTS.values())
        hint.apply("verify_bank")
        assert all(p.count("Hint:") == 1 for p in staff.ROLE_PROMPTS.values())
    finally:
        staff.ROLE_PROMPTS.update(saved)
    r = hint.ablate("verify_bank", days=2, trials=1, seat="finance_ap", day_start=1000, out=str(tmp_path))
    assert r["seeds"] == 2 and r["verdict"] == "no change" and r["rate_base"] == r["rate_hint"]
    assert "verify_bank" in hint.table([r])
