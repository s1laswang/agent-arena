import math

from canary.rules import TIERS
from canary.solver.belief import Doc, FeedItem, Observations, posterior, leak_loglik
from canary.solver.bench import _run_local
from canary.solver._sim import SimEnv
from canary.solver import SolverPolicy


def _obs():
    o = Observations(employees=["e00", "e01", "e02", "e03"], today=3)
    o.docs["d0"] = Doc("d0", 1, frozenset({"e00", "e01"}))
    o.docs["c1"] = Doc("c1", 1, frozenset({"e00", "e01", "e02"}), True, {"e00": "A", "e01": "B", "e02": "A"})
    o.closed_days = {1, 2}
    return o


def test_leaked_variant_excludes_other_groups():
    o = _obs()
    o.leak_days = {1}
    o.feed = [FeedItem(2, "c1", "A")]
    p = posterior(o, TIERS["easy"], behaviour_temper=0)
    assert p["e01"] == 0 and p["e03"] == 0
    assert abs(p["e00"] + p["e02"] - 1) < 1e-9


def test_delay_marginalisation_pending_leak():
    o = _obs()
    o.leak_days = {2}          # leaked on day 2, not surfaced yet (delay 1..3 in hard)
    o.today = 3
    P = TIERS["hard"]
    # e03 holds nothing: cannot have leaked
    assert leak_loglik(o, "e03", P) == -math.inf
    assert leak_loglik(o, "e00", P) > -math.inf


def test_regular_leak_holder_only():
    o = _obs()
    o.leak_days = {1}
    o.feed = [FeedItem(2, "d0")]
    p = posterior(o, TIERS["easy"], behaviour_temper=0)
    assert p["e02"] == 0 and p["e03"] == 0


def test_solver_accuracy_sim_smoke():
    for tier in ("easy", "medium", "hard"):
        rs = [_run_local(SimEnv(tier, s), SolverPolicy(tier)) for s in range(15)]
        assert sum(r.correct for r in rs) >= 13, tier


def test_params_from_instruction_roundtrip():
    from canary.env import Env
    from canary.solver.params import params_from_instruction
    for t in ("easy", "medium", "hard"):
        assert params_from_instruction(Env(t, 0).instruction()) == TIERS[t]


def test_regret_tags_and_solver_low_regret():
    from canary.env import Env
    from canary.baselines import StopEarly, DoNothing
    from canary.solver.regret import attribute
    tot_solver, tot_early = 0.0, 0.0
    for s in range(10):
        r = attribute(_run_local(Env("medium", s), SolverPolicy(None)))
        tot_solver += sum(x["regret"] for x in r)
        e = attribute(_run_local(Env("medium", s), StopEarly(seed=s)))
        assert "premature_accusation" in e[-1]["tags"]
        tot_early += sum(x["regret"] for x in e)
        n = attribute(_run_local(Env("medium", s), DoNothing(seed=s)))
        assert "no_accusation" in n[-1]["tags"]
    assert tot_solver < tot_early


def test_solver_robust_to_random_dsl_moles():
    """CONTRACT §7: canary-first inference; 20 random strategies on medium (episodes where the
    mole never leaks are unsolvable by evidence and excluded)."""
    import random
    from canary.env import Env
    from canary.mole.dsl import random_strategy
    ok = n = 0
    for s in range(20):
        env = Env("medium", s, mole_strategy=random_strategy(random.Random(f"bench-mole:{s}")))
        r = _run_local(env, SolverPolicy(None))
        if not any(e.event == "leak" for e in env.ledger()):
            continue
        n += 1
        ok += r.correct
    assert n >= 15 and ok / n >= 0.85, (ok, n)
