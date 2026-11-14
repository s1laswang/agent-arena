"""Skill-ladder variants run, are deterministic, and the default AblatedSolver == SolverPolicy."""
import importlib.util
from pathlib import Path

import pytest

from canary.env import Env
from canary.solver.ablation import ABLATIONS, AblatedSolver
from canary.solver.bench import _run_local
from canary.solver.policy import SolverPolicy


def _trace(policy, tier, seed):
    env = Env(tier, seed)
    r = _run_local(env, policy)
    return [(s.tool, s.args) for s in env.history], r.score


@pytest.mark.parametrize("tier,seed", [("medium", 7900), ("hard", 7901)])
def test_default_is_reference(tier, seed):
    assert _trace(AblatedSolver(None), tier, seed) == _trace(SolverPolicy(None), tier, seed)


@pytest.mark.parametrize("ab", ABLATIONS)
def test_variant_runs_and_is_deterministic(ab):
    a = _trace(AblatedSolver(None, ablation=ab), "hard", 7902)
    b = _trace(AblatedSolver(None, ablation=ab), "hard", 7902)
    assert a == b
    assert -1.0 <= a[1] <= 1.0


def test_unknown_ablation():
    with pytest.raises(ValueError):
        AblatedSolver(None, ablation="nope")


def test_script_smoke(tmp_path):
    spec = importlib.util.spec_from_file_location("skill_ladder", Path(__file__).parents[1] / "scripts" / "skill_ladder.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [m.run_one(("medium", r, 7903)) for r in ("solver", "solver-accuse_last", "do_nothing")]
    summ = m.summarise(rows, ["medium"], ["solver", "solver-accuse_last", "do_nothing"])
    assert summ[0]["delta"] == 0.0 and summ[2]["mean"] == 0.0
