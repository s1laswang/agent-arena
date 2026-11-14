"""Control: burning the call budget with harmless reads BEFORE the solver acts must not change its reward,
and one call past the budget must zero it. The existing anticheat control pads only after the episode
ended (every call returns 'episode over'), so it never touches the cap boundary. Offline."""
import os

os.environ["GEMINI_API_KEY"] = ""

import pytest

from canary.eval import make_env
import functools

from canary.redteam.anticheat import replay_actions, solver_actions as _sa
from canary.rules import TIERS

solver_actions = functools.lru_cache(None)(_sa)
CASES = [(t, s) for t in sorted(TIERS) for s in (0, 1)]
READS = ("status", "list_employees")  # check_leak_feed is investigative: it spends the daily action budget and changes what the solver can do


def padded(tier, seed, actions, pad):
    env = make_env(tier, seed)
    for i in range(pad):
        env.call(READS[i % len(READS)], {})
    for tool, args in actions:
        env.call(tool, args)
    return env


@pytest.mark.parametrize("tier,seed", CASES)
def test_pad_to_budget_minus_one_keeps_solver_reward(tier, seed):
    actions, want = solver_actions(tier, seed)
    cap = TIERS[tier].tool_call_cap
    env = padded(tier, seed, actions, cap - 1 - len(actions))
    assert len(env.history) == cap - 1
    assert env.score() == pytest.approx(want), (tier, seed, want, env.score())
    assert env.result("pad").end_reason == "accused"


@pytest.mark.parametrize("tier,seed", CASES[:3])
def test_cap_boundary_budget_th_call_ok_next_zeroes(tier, seed):
    actions, want = solver_actions(tier, seed)
    cap = TIERS[tier].tool_call_cap
    assert padded(tier, seed, actions, cap - len(actions)).score() == pytest.approx(want), "the cap-th call still executes"
    env = padded(tier, seed, actions, cap - len(actions) + 1)
    assert env.done and env.score() == 0.0 and env.result("pad").end_reason == "tool_cap"
    assert want > 0


@pytest.mark.parametrize("tier,seed", CASES[:3])
def test_solver_replay_alone_matches(tier, seed):
    actions, want = solver_actions(tier, seed)
    assert replay_actions(tier, seed, actions).score() == pytest.approx(want)
