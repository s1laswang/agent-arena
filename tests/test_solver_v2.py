"""solver_v2: deterministic, runs on every tier within the caps, and leaves `solver` byte-identical."""
from __future__ import annotations

import hashlib
import json

import pytest

from canary.env import Env
from canary.rules import TIERS
from canary.solver import SolverPolicy
from canary.solver.bench import _run_local, make_policy
from canary.solver.policy_v2 import SolverV2Policy


def _trace_hash(env) -> str:
    return hashlib.sha256(json.dumps([(s.tool, s.args) for s in env.history], sort_keys=True).encode()).hexdigest()[:16]


# Tool-trace hashes of `solver` computed on the parent branch (justSilas-solver2) before solver_v2 existed.
SOLVER_TRACES = {("easy", 3): "fd369f8dfb7bd5a9", ("medium", 5): "4f484656218d6cd5",
                 ("hard", 7): "5ba4d28b6a08948e", ("hard", 11): "68231b4f64939acf"}


@pytest.mark.parametrize("tier,seed", sorted(SOLVER_TRACES))
def test_solver_unchanged(tier, seed):
    env = Env(tier, seed)
    _run_local(env, SolverPolicy(None))
    assert _trace_hash(env) == SOLVER_TRACES[(tier, seed)]


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_v2_deterministic_and_within_caps(tier):
    for seed in (1, 2):
        hs = []
        for _ in range(2):
            env = Env(tier, seed)
            r = _run_local(env, SolverV2Policy(None))
            hs.append(_trace_hash(env))
            assert len(env.history) <= TIERS[tier].tool_call_cap
            assert r.end_reason != "tool_cap"
            per_day = {}
            for s in env.history:
                if s.tool == "plant_canary" and (s.result or {}).get("ok", True):
                    per_day[s.day] = per_day.get(s.day, 0) + 1
                    assert len(set(s.args["assignment"].values())) <= TIERS[tier].max_variants
            assert all(v <= TIERS[tier].canaries_per_day for v in per_day.values())
            assert all((s.result or {}).get("ok", True) for s in env.history), "v2 made an invalid call"
        assert hs[0] == hs[1]


def test_v2_registered():
    from canary.eval import make_policy_factory
    assert make_policy_factory("solver_v2")(0).name == "solver_v2"
    assert make_policy(agent="solver_v2", seed=0).name == "solver_v2"


def test_v2_accuracy_smoke():
    rs = [_run_local(Env("hard", s), SolverV2Policy(None)) for s in range(12)]
    assert sum(r.correct for r in rs) >= 10
