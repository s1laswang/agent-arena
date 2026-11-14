from canary.env import Env
from canary.baselines import BASELINES


def _run(tier, seed, name):
    env = Env(tier, seed)
    cls = BASELINES[name]
    p = cls() if name == "do_nothing" else cls(seed=seed)
    p.reset(env.tools_spec(), env.instruction())
    while not env.done:
        env.call(*p.act(env.history))
    return env.score()


def test_do_nothing_zero_and_stop_early_low():
    for tier in ("easy", "medium", "hard"):
        assert all(_run(tier, s, "do_nothing") == 0 for s in range(20))
        assert sum(_run(tier, s, "stop_early") for s in range(40)) / 40 < 0.25
