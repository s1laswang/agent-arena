import json
import random
from dataclasses import asdict
from pathlib import Path

import pytest

from canary import forge_track
from canary.env import Env
from canary.forge_track import strategy_for, strategy_index, validate
from tests.test_env import random_policy

FIX = Path(__file__).parent / "fixtures" / "hof_small.jsonl"


@pytest.fixture(autouse=True)
def _hof(monkeypatch):
    monkeypatch.setenv("CANARY_FORGE_HOF", str(FIX))


def test_uses_hard_params_and_a_hof_strategy():
    _, strats = forge_track.load(FIX)
    env = Env("hard_forge", 5)
    assert env.p.name == "hard" and env._world.mole_strategy in strats
    assert "hard_forge track" in env.instruction() and "evolved Mole DSL strategy" in env.instruction()
    assert "rank" not in env.instruction()


def test_selection_stable_and_spread():
    idx = [strategy_index("hard_forge", s, 3) for s in range(60)]
    assert idx == [strategy_index("hard_forge", s, 3) for s in range(60)]
    assert set(idx) == {0, 1, 2}
    assert strategy_for("hard_forge", 7) == strategy_for("hard_forge", 7)


def test_determinism_and_no_strategy_leak():
    for seed in range(10):
        a, b = Env("hard_forge", seed), Env("hard_forge", seed)
        random_policy(a, random.Random(seed))
        random_policy(b, random.Random(seed))
        assert [asdict(x) for x in a.ledger()] == [asdict(x) for x in b.ledger()]
        assert [s.result for s in a.history] == [s.result for s in b.history]
        for s in a.history:
            blob = json.dumps(s.result)
            assert "strategy_json" not in blob and "\"rules\"" not in blob and "most_recipients" not in blob


def test_missing_file_clear_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CANARY_FORGE_HOF", str(tmp_path / "nope.jsonl"))
    with pytest.raises(FileNotFoundError, match="hall of fame"):
        Env("hard_forge", 1)
    Env("hard", 1)  # plain tiers never need the file


def test_validate_writes_accepted(tmp_path):
    out = tmp_path / "hof.jsonl"
    keep = validate(FIX, 3, out=out, min_acc=0.0)
    assert len(keep) == 3 and len(out.read_text().splitlines()) == 3
    assert all("track_validation" in r for r in keep)
    assert validate(FIX, 2, out=tmp_path / "none.jsonl", min_acc=1.01) == []


def test_eval_accepts_track():
    from canary.eval import make_env, run_episode
    from canary.solver.policy import SolverPolicy
    r = run_episode(make_env("hard_forge", 3), SolverPolicy())
    assert r.tier == "hard_forge" and r.end_reason in ("accused", "horizon", "tool_cap")
