import random

from agents import gemini
from agents.sleeper_agent import SleeperAgent
from sleeper.day import run_day
from sleeper.models import SEATS
from agents.staff import ScriptedStaff
from tests.test_gemini_team import _fake_generate, _swap_day


def _live(monkeypatch, tmp_path):
    monkeypatch.setattr(gemini, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("GEMINI_API_KEY", "fake")
    monkeypatch.delenv("SLEEPER_OFFLINE", raising=False)
    monkeypatch.setattr(gemini, "_generate", _fake_generate)
    monkeypatch.setattr(gemini, "usage", lambda: {"cost": 9.0})


def _play(model="m"):
    day, st, goal = _swap_day()
    team = {s: ScriptedStaff(s) for s in SEATS}
    ag = SleeperAgent("finance_ap", goal, st, random.Random(1))
    team["finance_ap"] = ag
    return run_day(day, team), ag


def test_cost_cap_aborts_to_script(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    monkeypatch.setenv("SLEEPER_MAX_COST", "1")
    w, _ = _play()
    assert any(a.tool == "update_vendor_bank" for a in w.ledger)
    assert not list((tmp_path / "cache").glob("*.json"))


def test_cache_rerun_zero_calls(monkeypatch, tmp_path):
    _live(monkeypatch, tmp_path)
    monkeypatch.setattr(gemini, "usage", gemini.usage.__wrapped__ if hasattr(gemini.usage, "__wrapped__") else (lambda: {"cost": 0}))
    gemini.reset_usage()
    _play()
    n = gemini._usage["calls"]
    assert n > 0
    gemini.reset_usage()
    monkeypatch.setattr(gemini, "_generate", lambda *a: 1 / 0)
    _play()
    assert gemini._usage["calls"] == 0
