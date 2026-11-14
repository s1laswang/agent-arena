"""canary.eval: run_episode + CLI artifacts (HARNESS)."""
from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from canary.baselines import DoNothing, StopEarly
from canary.env import Env
from canary.eval import (AgentUnavailable, episode_from_dict, main, make_policy_factory, parse_seeds,
                         run_episode)
from canary.types import EpisodeResult


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_do_nothing_scores_zero(tier):
    res = run_episode(Env(tier, 3), DoNothing(seed=3))
    assert res.score == 0.0
    assert res.end_reason == "horizon"
    assert res.accused is None and not res.correct
    assert res.agent == "do_nothing"


def test_stop_early_accuses_and_score_is_v_or_minus_one():
    for seed in range(5):
        res = run_episode(Env("easy", seed), StopEarly(seed=seed))
        assert res.end_reason == "accused" and res.accused is not None
        assert res.score == (res.meta["V"] if res.correct else -1.0)


def test_determinism():
    a = run_episode(Env("medium", 11), StopEarly(seed=11))
    b = run_episode(Env("medium", 11), StopEarly(seed=11))
    assert asdict(a) == asdict(b)


def test_iteration_cap_marks_error():
    class Spinner:
        name = "spinner"
        def reset(self, tools_spec, instruction): pass
        def act(self, history): return ("status", {})

    env = Env("easy", 0)
    res = run_episode(env, Spinner(), max_iters=10)
    assert res.end_reason == "error" and res.score == 0.0 and len(res.steps) == 10


def test_crashing_policy_is_contained():
    class Crash:
        name = "crash"
        def reset(self, tools_spec, instruction): pass
        def act(self, history): raise ValueError("boom")

    res = run_episode(Env("easy", 0), Crash())
    assert res.end_reason == "error" and "boom" in res.meta["error"]


def test_jsonl_round_trip():
    res = run_episode(Env("easy", 2), StopEarly(seed=2))
    line = json.dumps(asdict(res), sort_keys=True)
    back = episode_from_dict(json.loads(line))
    assert isinstance(back, EpisodeResult)
    assert asdict(back) == json.loads(line)


def test_cli_writes_artifacts(tmp_path, capsys):
    rc = main(["--agent", "stop_early", "--tier", "easy", "--seeds", "3", "--out", str(tmp_path)])
    assert rc == 0
    (run,) = list(tmp_path.iterdir())
    lines = (run / "episodes.jsonl").read_text().splitlines()
    assert len(lines) == 3
    eps = [episode_from_dict(json.loads(x)) for x in lines]
    assert [e.seed for e in eps] == [0, 1, 2] and all(e.tier == "easy" for e in eps)
    meta = json.loads((run / "meta.json").read_text())
    for k in ("agent", "tier", "seeds", "git_sha", "timestamp", "provider"):
        assert k in meta
    assert meta["agent"] == "stop_early" and meta["seeds"] == [0, 1, 2]
    out = capsys.readouterr().out
    assert "score ± 95% CI" in out and "stop_early" in out


def test_cli_unknown_agent(capsys, tmp_path):
    assert main(["--agent", "nope", "--tier", "easy", "--seeds", "1", "--out", str(tmp_path)]) == 2
    assert "unknown agent" in capsys.readouterr().err


def test_llm_agent_not_available():
    with pytest.raises(AgentUnavailable):
        make_policy_factory("openai:gpt-x")


def test_parse_seeds():
    assert parse_seeds("dev20") == list(range(20))
    assert parse_seeds("3") == [0, 1, 2]
    assert parse_seeds("5-7,9") == [5, 6, 7, 9]
    assert parse_seeds("judge")[0] == 900_000


def test_parse_seeds_bare_large_int_is_one_seed():
    """A bare judge seed must not expand to range(900003) (the '4-min solver blow-up')."""
    assert parse_seeds("900003") == [900003]
    assert parse_seeds("20") == list(range(20))
    assert parse_seeds("1000") == list(range(1000))
    assert parse_seeds("1001") == [1001]
    assert parse_seeds("n:5") == [0, 1, 2, 3, 4]
    assert parse_seeds("900000-900002,900007") == [900000, 900001, 900002, 900007]


@pytest.mark.parametrize("spec", ["0-20000", "n:10001", "900000-999999", "1-5,0-9999", "abc", "9-3", ""])
def test_parse_seeds_rejects_huge_or_bad(spec):
    with pytest.raises(ValueError, match="--seeds"):
        parse_seeds(spec)


def test_cli_rejects_over_10k_episodes(capsys):
    assert main(["--agent", "do_nothing", "--tier", "all", "--seeds", "n:4000"]) == 2
    assert "limit" in capsys.readouterr().err
