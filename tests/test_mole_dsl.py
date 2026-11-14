import json
import random
from dataclasses import asdict

import pytest

from canary.env import Env
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy, StrategyError, random_strategy
from tests.test_env import random_policy

TIERS = ["easy", "medium", "hard"]


def _run(tier, seed, strat):
    env = Env(tier, seed, mole_strategy=strat)
    random_policy(env, random.Random(seed))
    return env


def test_default_equals_none():
    for seed in range(200):
        t = TIERS[seed % 3]
        a, b = _run(t, seed, None), _run(t, seed, DEFAULT_STRATEGY)
        assert [asdict(x) for x in a.ledger()] == [asdict(x) for x in b.ledger()]
        assert [s.result for s in a.history] == [s.result for s in b.history]


@pytest.mark.parametrize("bad", [
    None, [], {"rules": "x"}, {"rules": [], "extra": 1},
    {"rules": [{"if": [], "then": {"leak": "newest"}}] * 13},
    {"rules": [{"if": [["mole_id", "==", 1]], "then": {}}]},
    {"rules": [{"if": [["day", "!=", 1]], "then": {}}]},
    {"rules": [{"if": [["day", ">", "1"]], "then": {}}]},
    {"rules": [{"if": [["day", ">", True]], "then": {}}]},
    {"rules": [{"if": ["__import__('os') > 1"], "then": {}}]},
    {"rules": [{"if": [], "then": {"leak": "all"}}]},
    {"rules": [{"if": [], "then": {"frame": "e01"}}]},
    {"rules": [{"if": [], "then": {"leak": "newest", "code": "x"}}]},
    {"rules": [{"if": [], "then": {}, "else": {}}]},
    {"default": {"leak": "everything"}},
])
def test_reject(bad):
    with pytest.raises(StrategyError):
        MoleStrategy.from_json(bad)


def test_roundtrip_and_string_conditions():
    s = MoleStrategy.from_json({"rules": [{"if": ["days_since_last_leak >= 2", ["i_am_restricted", "==", 0]],
                                           "then": {"leak": "oldest", "frame": "decoy"}}]})
    assert MoleStrategy.from_json(json.loads(json.dumps(s.to_json()))) == s


def test_frame_adds_access_and_never_leaks_restricted_choice():
    strat = {"rules": [], "default": {"leak": "none", "frame": "decoy"}}
    env = Env("medium", 3, mole_strategy=strat)
    for _ in range(5):
        env.call("advance_day", {})
    led = env.ledger()
    assert not any(x.event == "leak" for x in led)
    framed = [x for x in led if x.event == "framed"]
    assert framed and all(x.detail["employee"] == env._world.decoy for x in framed)


def test_fewest_recipients_selector():
    env = Env("easy", 8, mole_strategy={"rules": [], "default": {"leak": "fewest_recipients", "frame": "none"}})
    for _ in range(6):
        env.call("advance_day", {})
    leaks = [x.detail["doc_id"] for x in env.ledger() if x.event == "leak"]
    assert leaks


def test_random_strategies_run_deterministically():
    for i in range(60):
        strat = random_strategy(random.Random(i))
        t = TIERS[i % 3]
        a, b = _run(t, i, strat), _run(t, i, strat)
        assert [asdict(x) for x in a.ledger()] == [asdict(x) for x in b.ledger()]
        for s in a.history:
            assert '"mole' not in json.dumps(s.result).lower()
