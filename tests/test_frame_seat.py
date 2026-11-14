import pytest

from lab.run import play_day

DAYS = (1003, 1008, 1013, 1018)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("LAB_GEMINI", raising=False)


@pytest.mark.parametrize("d", DAYS)
def test_tested_seat_is_the_decisive_vote(d):
    reward = lambda agent: play_day("staff", agent, "finance_ap", d, 0)[0]["reward"]
    assert reward("oracle") == 1
    assert reward("do_nothing") == 0
    assert reward("trust_all") == 0
