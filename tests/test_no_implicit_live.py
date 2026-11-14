import os

from agents import gemini, staff, sleeper_agent


def test_key_alone_never_goes_live(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.delenv("SLEEPER_LIVE", raising=False)
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    monkeypatch.delenv("SLEEPER_LIVE_SLEEPER", raising=False)
    assert not gemini.enabled()
    assert all(type(a).__name__ == "ScriptedStaff" for a in staff.make_team().values())
    monkeypatch.setenv("SLEEPER_LIVE", "1")
    assert gemini.enabled()
    assert sleeper_agent._gemini() is None


def test_import_does_not_load_env():
    import subprocess, sys
    r = subprocess.run([sys.executable, "-c", "import os, agents.gemini; print(os.environ.get('GEMINI_API_KEY',''))"],
                       env={k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}, capture_output=True, text=True)
    assert r.stdout.strip() == ""
