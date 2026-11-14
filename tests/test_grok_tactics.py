import pytest

from canary.baselines import BASELINES, CALIBRATION_POLICIES, GrokTactics
from canary.env import Env
from canary.eval import run_episode


def test_registered_as_calibration_only():
    assert CALIBRATION_POLICIES["grok_tactics"] is GrokTactics
    assert "grok_tactics" not in BASELINES


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_runs_to_completion(tier):
    for seed in range(10):
        r = run_episode(Env(tier, seed), GrokTactics(seed))
        assert r.end_reason in ("accused", "horizon", "tool_cap"), r.meta


def test_deterministic():
    a = run_episode(Env("medium", 5), GrokTactics(5))
    b = run_episode(Env("medium", 5), GrokTactics(5))
    assert [(s.tool, s.args) for s in a.steps] == [(s.tool, s.args) for s in b.steps]
    assert a.score == b.score
