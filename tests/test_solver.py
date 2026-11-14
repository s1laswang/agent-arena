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
