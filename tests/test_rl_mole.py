"""WS3: RL mole policy, its training step, the hard_rl track and the GRPO mole reward."""
import json
import random

import numpy as np
import pytest

from canary import forge_track
from canary.env import Env
from canary.eval import run_episode
from canary.forge import rl_mole
from canary.forge.rl_mole import RLMole, default_like_params, init_params
from canary.solver.policy import SolverPolicy
from tests.test_env import random_policy
from train import grpo_mole


def _ep(params, seed, agent="solver"):
    r = run_episode(Env("hard", seed, mole_strategy=RLMole(params)), rl_mole._agent(agent, "hard", seed))
    return r.score, r.correct


def test_policy_roundtrip_and_determinism():
    p = init_params(seed=3)
    pol = RLMole.from_json(json.loads(json.dumps(RLMole(p).to_json())))
    for k in p:
        assert np.allclose(pol.p[k], p[k])
    assert _ep(p, 11) == _ep(pol.p, 11)
    with pytest.raises(ValueError):
        RLMole.from_json({"kind": "rl_mole", "leak_selectors": ["x"], "frame_selectors": [], "params": {}})


def test_default_like_policy_mostly_plays_default_selectors():
    tr = []
    run_episode(Env("hard", 5, mole_strategy=RLMole(default_like_params(), trace=tr)), SolverPolicy("hard"))
    assert tr
    li = [t[1] for t in tr]
    assert li.count(rl_mole.LEAK_SELECTORS.index("random_seeded")) / len(li) > 0.5


def test_train_step_updates_params_and_writes_curve(tmp_path):
    res = rl_mole.train(iters=1, batch=2, workers=1, out=tmp_path, log=lambda s: None)
    row = json.loads((tmp_path / "curve.jsonl").read_text().splitlines()[0])
    assert {"min_regret", "solver_acc", "lam"} <= set(row)
    assert (tmp_path / "policy_final.json").exists()
    assert not np.allclose(res["params"]["bl"], default_like_params()["bl"])


def test_hard_rl_track(tmp_path, monkeypatch):
    hof = tmp_path / "hof.jsonl"
    hof.write_text("".join(json.dumps({"strategy_json": RLMole(init_params(seed=s)).to_json()}) + "\n" for s in range(2)))
    monkeypatch.setenv("CANARY_RL_HOF", str(hof))
    forge_track._cache.clear()
    env = Env("hard_rl", 4)
    assert env.p.name == "hard" and isinstance(env._world.mole_strategy, RLMole)
    assert "reinforcement learning" in env.instruction() and "params" not in env.instruction()
    a, b = Env("hard_rl", 9), Env("hard_rl", 9)
    random_policy(a, random.Random(1)); random_policy(b, random.Random(1))
    assert a.score() == b.score()


def test_grpo_parse_and_reward():
    assert grpo_mole.parse_action('ok {"leak": "oldest", "frame": "decoy"}') == ("oldest", "decoy")
    assert grpo_mole.parse_action('{"leak": "everything"}') is None
    assert grpo_mole.parse_action("no json") is None
    row = grpo_mole.collect_prompts(1)[0]
    assert "Day" in row["prompt"] and "mole" not in row["prompt"].lower()
    assert grpo_mole.episode_reward((row, "garbage"))["reward"] == grpo_mole.INVALID_REWARD
    t = '{"leak": "fewest_recipients", "frame": "none"}'
    r1, r2 = grpo_mole.episode_reward((row, t)), grpo_mole.episode_reward((row, t))
    assert r1 == r2 and r1["valid"]
