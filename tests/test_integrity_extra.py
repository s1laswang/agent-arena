"""Regression tests for EXPLOITS rows that were previously script/manual-only (#9 text leak, #40 evolved moles)."""
from __future__ import annotations

import json
import statistics
from pathlib import Path

import pytest

from tests.integrity_helpers import make_env

ROOT = Path(__file__).resolve().parent.parent


def test_09_text_probe_not_above_fair_bar():
    """#9: a text-only investigator (stub, messages + interviews, no canaries) is not significantly
    above the Bayes bar implied by the documented interview signal (medium, 100 seeds)."""
    from canary.redteam import text_probe as tp
    make_env("medium", 0)
    seeds = range(100)
    correct = 0
    for s in seeds:
        obs = tp.collect("medium", s)
        env = make_env("medium", s)
        correct += tp.stub_guess(obs) == env._world.mole
    bar = tp.fair_bar("medium", 2)
    assert tp.p_value_above(correct, len(seeds), bar) > 0.01, (correct, bar)


def _hof_files():
    return sorted((ROOT / "data" / "forge").glob("hall_of_fame_v*.jsonl"))


@pytest.mark.parametrize("path", _hof_files(), ids=lambda p: p.name)
def test_40_evolved_moles_catchable_and_unexploitable(path):
    """#40: every hall-of-fame evolved mole stays catchable by the solver, do_nothing = 0,
    guess_day1 < 0 (the day-1 accusation), and the fuzzer finds no invariant violation (hard, 20 seeds)."""
    from canary.baselines import BASELINES, play
    from canary.env import Env
    from canary.mole.dsl import MoleStrategy
    from canary.redteam import fuzz
    from canary.solver import SolverPolicy
    rows = [json.loads(l) for l in path.read_text().splitlines() if '"strategy_json"' in l]
    if not rows:
        pytest.skip("no strategies in file")
    make_env("hard", 6000)
    seeds = range(6000, 6020)
    for row in rows:
        st = MoleStrategy.from_json(row["strategy_json"])
        mk = lambda s: Env("hard", s, mole_strategy=st)
        assert statistics.mean(play(mk(s), SolverPolicy()) for s in seeds) > 0.3
        assert all(play(mk(s), BASELINES["do_nothing"](seed=s)) == 0 for s in seeds)
        assert statistics.mean(play(mk(s), BASELINES["guess_day1"](seed=s)) for s in seeds) < 0
        r = fuzz.hunt("hard", seeds, 2000, 0, mode="all", factory=lambda t, s: Env(t, s, mole_strategy=st))
        assert r["best_non_solver_score"] <= 0 and not r["invariant_violations"]
