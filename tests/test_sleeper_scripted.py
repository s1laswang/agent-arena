import pytest

fr = pytest.importorskip("lab.frontier_rows")


def test_scripted_sleeper_never_live(tmp_path, monkeypatch):
    import agents.sleeper_agent as SA
    from agents import gemini

    monkeypatch.setattr(gemini, "enabled", lambda: True)
    monkeypatch.setattr(SA, "_gemini", SA._gemini)
    for k in ("LAB_GEMINI", "SLEEPER_MODEL_STAFF", "SLEEPER_MAX_CALLS"):
        monkeypatch.setenv(k, "")
    seen = []

    def play(*a, **k):
        seen.append(SA._gemini())
        return {"reward": 0, "harm": [], "tickets_done": 0, "tickets_total": 1, "has_sleeper": True, "goal_kind": None, "strategy": None}, {}

    monkeypatch.setattr(fr.R, "play_day", play)
    fr.run_model("gemini-3.5-flash", 1, 1, 1000, "finance_ap", "seat", str(tmp_path), 350, sleeper="scripted")
    assert seen == [None]
