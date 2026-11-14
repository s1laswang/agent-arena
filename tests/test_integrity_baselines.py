"""Baselines must be ≪ solver; do-nothing == 0; score>0 ⇒ exactly one correct accusation."""
import statistics

import pytest

from canary.baselines import BASELINES, play
from canary.redteam.fuzz import _accusations, score_invariants
from tests.integrity_helpers import make_env, true_mole

SEEDS = range(30)


def _run(name, tier="easy", seeds=SEEDS):
    out = []
    for s in seeds:
        env = make_env(tier, s)
        sc = play(env, BASELINES[name](seed=s))
        acc = _accusations(env.ledger(), set())
        assert score_invariants(sc, acc, true_mole(env)) == [], (name, tier, s, sc, acc)
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


# Calibrated on Env v0 (d3ba858), 30 seeds, 2026-11-14. Observed means:
#            easy   medium  hard
# stop_early 0.100  0.033   0.033   random 0.029 0.015 0.026   restrict_all 0.089 0 0
# probe_all  0      0       0       accuse_decoy 0.087 0.029 0.032
# accuse_most_logs 0.542 0.265 0.151   logs_minus_decoy 0.515 0.233 0.182
# obvious_heuristic 0.387 0.148 0.139
CHANCE_LEVEL = {"stop_early", "random", "restrict_all", "probe_all", "accuse_decoy"}
CHANCE_BOUND = {"easy": 0.25, "medium": 0.15, "hard": 0.15}   # ≈ 2-3x V/N + noise margin
# Log-based baselines currently beat chance by a lot (EXPLOITS #4). These bounds only stop it
# getting worse; the real bar is test_log_signal_alone_near_chance (strict since ENV tiers v1).
LOG_BOUND = {"easy": 0.7, "medium": 0.4, "hard": 0.35}


@pytest.mark.parametrize("name", sorted(set(BASELINES) - {"do_nothing"}))
@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_baseline_far_below_solver(name, tier):
    m = statistics.mean(_run(name, tier))
    sol = _solver_mean(tier)
    if sol is not None:
        assert m < 0.9 * sol, (name, tier, m, sol)
    bound = CHANCE_BOUND[tier] if name in CHANCE_LEVEL else LOG_BOUND[tier]
    assert m < bound, (name, tier, m)


@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_accuse_decoy_near_chance(tier):
    from canary.rules import TIERS
    acc = sum(x > 0 for x in _run("accuse_decoy", tier)) / 30
    assert acc <= 2.0 / TIERS[tier].n_employees, (tier, acc)


@pytest.mark.parametrize("name", ["accuse_most_logs"])
@pytest.mark.parametrize("tier", ["medium", "hard"])
def test_most_logs_near_chance(name, tier):
    from canary.rules import TIERS
    scores = _run(name, tier, range(100))  # 100 seeds: 30 is too noisy at a 2x-chance bound
    acc = sum(x > 0 for x in scores) / len(scores)
    assert acc <= 2.0 / TIERS[tier].n_employees, (name, tier, acc)


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_log_signal_alone_near_chance(tier):
    """Repro: wait 5 days, read_access_logs(1..day), drop angriest sender, accuse argmax(3*AH+total).
    Never plants a canary. Should be ≪ the canary heuristic and near chance."""
    logs = statistics.mean(_run("logs_minus_decoy", tier))
    canary = statistics.mean(_run("obvious_heuristic", tier))
    assert logs < 0.5 * canary, (tier, logs, canary)


def wrong_accusation_penalty() -> float:
    """Probe episode: accuse an innocent on easy/0 and return the score (v0: 0.0, v0.3: -1.0)."""
    env = make_env("easy", 0)
    mole = true_mole(env)
    from canary.baselines import employee_ids
    emps = employee_ids({"ok": True, "data": env.call("list_employees", {}).data})
    env.call("accuse", {"employee": next(e for e in emps if e != mole)})
    return env.score()


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_stop_early_negative(tier):
    if wrong_accusation_penalty() != -1.0:
        pytest.xfail("v0 stop-early lottery (EXPLOITS #1)")
    m = statistics.mean(_run("stop_early", tier, range(50)))
    assert m < 0, (tier, m)


LOGS_ONLY_MAX_ACC = {"easy": 0.40, "medium": 2.0 / 20, "hard": 2.0 / 30}  # CEO decision 03:00


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_logs_only_bound(tier):
    """logs_only (no canaries, wait 9 days) accuracy over 100 dev seeds stays under the CEO bound."""
    scores = _run("logs_only", tier, range(100))
    acc = sum(x > 0 for x in scores) / len(scores)
    assert acc <= LOGS_ONLY_MAX_ACC[tier], (tier, acc)


@pytest.mark.parametrize("tier", ["easy", "medium", "hard", "hard_forge"])
def test_calibration_policies_below_solver(tier):
    """Scripted calibration investigators (heuristic, grok_tactics) are public-interface only and must
    not beat the reference solver (v1.3, 40 seeds)."""
    from canary.baselines import CALIBRATION_POLICIES
    from canary.solver import SolverPolicy
    seeds = range(40)
    solver = statistics.mean(play(make_env(tier, s), SolverPolicy()) for s in seeds)
    for name, cls in CALIBRATION_POLICIES.items():
        m = statistics.mean(play(make_env(tier, s), cls(seed=s)) for s in seeds)
        assert m < solver, (tier, name, m, solver)
