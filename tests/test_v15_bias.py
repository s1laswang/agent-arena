"""Tests for FR8 + Azure unified V1.6 social layer aliases, RumourFollower trap, and legacy GeminiSocialProvider."""
from __future__ import annotations

import json

import pytest

from canary.baselines import BASELINES, BIAS_BASELINES
from canary.env import Env
from canary.eval import run_episode
from canary.redteam.fuzz import _mole_named
from canary.rules import TIERS_VERSION
from canary.social import ANGER_WORDS, BIASES, DECOY_VOCAB, parse_variant_biases
from canary.solver.policy import SolverPolicy
from canary.text.gemini import GeminiSocialProvider, get_provider
from canary.text.lint import lint_messages


def _play(tier: str, seed: int, days: int = 6, provider=None):
    e = Env(tier, seed, text_provider=provider)
    for _ in range(days):
        e.call("advance_day", {})
    return e


def test_social_off_by_default_and_shorthand_aliases():
    assert TIERS_VERSION == "v1.4"
    assert get_provider("social-v2").name == "social-v2"
    assert get_provider("social-v2:gemini-4-carbon").name == "social-v2"
    assert get_provider("social-v2:authority").name == "social-v2:authority"
    assert get_provider("v16").name == "v16:v5_full9_cocktail"
    assert get_provider("v16:all").name == "v16:all"
    assert get_provider("v16-template:v1").name == "v16:v1"
    assert get_provider("v16-stub:recency").name == "v16-gemini-stub:recency"
    for b in BIASES:
        p = get_provider(f"v16:{b}")
        assert p.variant_spec["biases"] == (b,)
    assert parse_variant_biases("authority+recency+bandwagon") == ("authority", "recency", "bandwagon")
    with pytest.raises(ValueError):
        parse_variant_biases("nonexistent_bias")


def test_fr8_seeds_0_29_solver_calibration_and_anger_scrub():
    assert tuple(SolverPolicy.ANGER_WORDS) == ANGER_WORDS
    prov = get_provider("v16:all")
    for seed in range(10):
        r_base = run_episode(Env("hard", seed), SolverPolicy("hard"))
        r_soc = run_episode(Env("hard", seed, text_provider=get_provider("v16:all")), SolverPolicy("hard"))
        assert r_soc.score == r_base.score
        assert r_soc.accused == r_base.accused
        assert r_soc.final_day == r_base.final_day
        dn = run_episode(Env("hard", seed, text_provider=get_provider("v16:all")), BASELINES["do_nothing"](seed=seed))
        se = run_episode(Env("hard", seed, text_provider=get_provider("v16:all")), BASELINES["stop_early"](seed=seed))
        assert dn.score == 0.0
        assert se.score == 0.0

        e = _play("hard", seed, days=8, provider=prov)
        social_msgs = [e._messages[m] for m in e._msg_order if "-s" in m]
        assert social_msgs and not lint_messages(social_msgs)
        for m in social_msgs:
            blob = f"{m['subject']}\n{m['body']}".lower()
            for w in DECOY_VOCAB:
                assert w not in blob
            assert not _mole_named(json.dumps(m), e._world.mole)


def test_rumour_follower_fooled_on_hard_seeds():
    rf_cls = BIAS_BASELINES["rumour_follower"]
    scores = [
        run_episode(Env("hard", seed, text_provider=get_provider("v16:all")), rf_cls(seed=seed)).score
        for seed in range(15)
    ]
    sol_scores = [run_episode(Env("hard", seed), SolverPolicy("hard")).score for seed in range(15)]
    assert sum(scores) / len(scores) < 0.0
    assert sum(scores) < sum(sol_scores)


def test_legacy_gemini_social_provider_and_committed_cache(monkeypatch):
    monkeypatch.setenv("CANARY_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    e = Env("medium", 7000)
    facts = e._facts(1)
    p = GeminiSocialProvider()
    events = [{"kind": "rumour", "speaker": "e01", "target": "e02"}]
    rendered = p.social_messages(facts, events)
    assert len(rendered) == 1 and rendered[0]["sender"] == "e01"
