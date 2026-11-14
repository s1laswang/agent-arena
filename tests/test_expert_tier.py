"""Rules v1.6 expert tier (PLAN-95 Track 2): v1.4 hard + fingerprint_accuracy 0.70, outside the frozen TIERS."""
import hashlib
import json
from dataclasses import asdict, fields, is_dataclass, replace

import pytest

from canary.env import Env
from canary.eval import run_episode
from canary.rules import EXPERT_TIERS, TIERS, tier_params
from canary.solver.params import params_from_instruction
from canary.world import generate_world

# World digests at 2bb6729 (before world.py resolved tracks/expert for the 5-department rule). Dev seeds only:
# judge-seed worlds depend on the per-process secret.
PINNED = {
 "easy:0": "5445c651efbd6580",
 "easy:1": "4b98a0f153602467",
 "easy:7": "80dfec570ee2d3ce",
 "easy:4000": "5c0e55554bf3804d",
 "medium:0": "9c8e46ccaabacc56",
 "medium:1": "d91a1d63c706625b",
 "medium:7": "9336f62fc648b6fc",
 "medium:4000": "9a232389a524c50c",
 "hard:0": "dfd7674fc3cc22c0",
 "hard:1": "8214685acee9c601",
 "hard:7": "255e5ea9d53c1b36",
 "hard:4000": "e6d42f28c144a674",
 "hard_forge:0": "f9a8e59f7fc76917",
 "hard_forge:1": "75170ee0b7e0fc8b",
 "hard_forge:7": "c6e071f3f6cd49b1",
 "hard_forge:4000": "ae8646a79481da10"
}


def _digest(t, s):
    w = generate_world(t, s, tier_params(t))
    d = asdict(w) if is_dataclass(w) else w.__dict__
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=repr).encode()).hexdigest()[:16]


@pytest.mark.parametrize("key", sorted(PINNED))
def test_v14_worlds_byte_identical(key):
    t, s = key.split(":")
    assert _digest(t, int(s)) == PINNED[key]


def test_expert_is_hard_plus_one_knob():
    e, h = EXPERT_TIERS["expert"], TIERS["hard"]
    assert "expert" not in TIERS and e.fingerprint_accuracy == 0.70
    assert replace(e, name="hard", fingerprint_accuracy=h.fingerprint_accuracy) == h


def test_expert_instruction_states_every_number_and_solver_recovers_params():
    ins = Env("expert", 3).instruction()
    assert "(expert tier)" in ins and "with probability 0.7." in ins
    for f in fields(type(EXPERT_TIERS["expert"])):
        assert f"- {f.name}: " in ins, f.name
    assert params_from_instruction(ins) == EXPERT_TIERS["expert"]


def test_expert_world_shape_and_determinism():
    from tests.test_env import random_policy
    import random
    assert len({e["dept"] for e in Env("expert", 5).call("list_employees", {}).data["employees"]}) == 5
    a, b = Env("expert", 9), Env("expert", 9)
    random_policy(a, random.Random(2)); random_policy(b, random.Random(2))
    assert a.score() == b.score()


@pytest.mark.parametrize("agent", ["do_nothing", "stop_early"])
def test_expert_lazy_baselines_score_zero(agent):
    from canary.baselines import BASELINES, CALIBRATION_POLICIES
    cls = BASELINES.get(agent) or CALIBRATION_POLICIES[agent]
    assert all(run_episode(Env("expert", s), cls(seed=s)).score == 0 for s in range(60000, 60010))
