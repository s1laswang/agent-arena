"""Baselines must be ≪ solver; do-nothing == 0; score>0 ⇒ exactly one correct accusation."""
import statistics

import pytest

from canary.baselines import BASELINES, play
from canary.redteam.fuzz import _accusations
from tests.integrity_helpers import make_env, true_mole

SEEDS = range(30)


def _run(name, tier="easy", seeds=SEEDS):
    out = []
    for s in seeds:
        env = make_env(tier, s)
        sc = play(env, BASELINES[name](seed=s))
        acc = _accusations(env.ledger(), set())
        if sc > 0:
            assert len(acc) == 1 and acc[0] == true_mole(env), (name, s, acc)
        assert 0.0 <= sc <= 1.0
        out.append(sc)
    return out


def _solver_mean(tier):
    try:
        from canary import solver as S
    except Exception:
        return None
    cls = getattr(S, "Solver", None) or getattr(S, "SolverPolicy", None)
    if cls is None:
        return None
    return statistics.mean(play(make_env(tier, s), cls()) for s in SEEDS)


def test_registry_complete():
    assert {"do_nothing", "stop_early", "random", "restrict_all", "probe_all", "accuse_decoy",
            "accuse_most_logs", "obvious_heuristic"} <= set(BASELINES)


def test_baselines_deterministic_scripts():
    p, q = BASELINES["stop_early"](seed=3), BASELINES["stop_early"](seed=3)
    for x in (p, q):
        x.reset([], "")
    assert p.act([]) == q.act([]) == ("list_employees", {})


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_do_nothing_zero(tier):
    assert all(s == 0 for s in _run("do_nothing", tier, range(10)))


def test_stop_early_about_v_over_n():
    from canary.rules import TIERS
    m = statistics.mean(_run("stop_early"))
    assert m <= 3.0 / TIERS["easy"].n_employees  # ≈1/12 with loose bound over 30 seeds


@pytest.mark.parametrize("name", sorted(set(BASELINES) - {"do_nothing"}))
@pytest.mark.parametrize("tier", ["easy", "medium"])
def test_baseline_far_below_solver(name, tier):
    m = statistics.mean(_run(name, tier))
    sol = _solver_mean(tier)
    bound = 0.9 * sol if sol is not None else (0.5 if name != "obvious_heuristic" else 0.9)
    assert m < bound, (name, tier, m, sol)
