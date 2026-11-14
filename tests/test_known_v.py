import random

import pytest

from canary import rules
from canary.env import Env
from tests.test_env import random_policy


def _expected(env):
    n = sum(1 for f in env._feed if f["surfaced_day"] <= env.day)
    return round(max(0.0, 1.0 - env.p.leak_damage * n - env._costs), 10)


def test_status_shows_known_v_never_unsurfaced():
    hidden_seen = 0
    for seed in range(50):
        env = Env(["easy", "medium", "hard"][seed % 3], seed)
        rng = random.Random(seed)
        while not env.done:
            if rng.random() < 0.3:
                env.call("restrict_access", {"employee": f"e{rng.randrange(env.p.n_employees):02d}"})
            if rng.random() < 0.3:
                env.call("plant_canary", {"doc_title": "x", "assignment": {"e00": "A", "e01": "B"}})
            st = env.call("status", {})
            if not st.ok:
                break
            assert st.data["V"] == _expected(env)
            if any(f["surfaced_day"] > env.day for f in env._feed):
                hidden_seen += 1
                assert st.data["V"] > round(env.V, 10)
            r = env.call("advance_day", {})
            if r.ok and "V" in r.data:
                assert r.data["V"] == _expected(env)
    assert hidden_seen > 0


def test_score_uses_true_v():
    for seed in range(40):
        env = Env("hard", seed)
        while env.day < 6:
            env.call("advance_day", {})
        if any(f["surfaced_day"] > env.day for f in env._feed):
            shown = env.call("status", {}).data["V"]
            env.call("accuse", {"employee": env._world.mole})
            assert env.score() == round(env.V, 10) < shown
            return
    pytest.fail("no seed with an unsurfaced leak")


def test_toggle_restores_true_v(monkeypatch):
    monkeypatch.setattr(rules, "KNOWN_V_MODE", False)
    env = Env("easy", 1)
    for _ in range(5):
        env.call("advance_day", {})
    assert env.call("status", {}).data["V"] == round(env.V, 10)


def test_instruction_mentions_known_v():
    t = Env("medium", 0).instruction()
    assert "damage from leaks that haven't surfaced yet is not visible" in t
    assert "Your score uses the true V" in t
