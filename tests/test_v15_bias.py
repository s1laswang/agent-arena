"""Tests for V1.6 social layer (social-v2 / v16:*): off by default, zero mole/decoy leak, exact solver calibration, cached offline replay."""
from __future__ import annotations

from dataclasses import replace
import json
import re

import pytest

from canary.baselines import BASELINES, BIAS_BASELINES
from canary.env import Env
from canary.eval import run_episode
from canary.redteam.fuzz import _mole_named
from canary.rules import TIERS, TIERS_VERSION
from canary.social import (
    ANGER_WORDS,
    BIASES,
    DECOY_VOCAB,
    SocialV2Provider,
    build_cast,
    generate_social_events,
    parse_variant_biases,
    social_message_ok,
)
from canary.solver.policy import SolverPolicy
from canary.text.gemini import GeminiSocialProvider, get_provider
from canary.text.lint import lint_messages


def _play(tier: str, seed: int, days: int = 6, provider=None):
    e = Env(tier, seed, text_provider=provider)
    for _ in range(days):
        e.call("advance_day", {})
    return e


def _trace(e):
    return json.dumps(
        {
            "docs": e.docs,
            "logs": e._logs,
            "feed": e._feed,
            "msgs": [e._messages[m] for m in e._msg_order],
            "V": e.V,
        },
        sort_keys=True,
        default=list,
    )


def test_social_off_by_default_and_v14_unchanged():
    assert TIERS_VERSION == "v1.4"
    for name in ("easy", "medium", "hard"):
        e = _play(name, 7001, days=5)
        assert e.provider.name == "template"
        assert not any("-s" in mid for mid in e._msg_order)


def test_get_provider_variants():
    assert get_provider("social-v2").name == "social-v2"
    assert get_provider("social-v2:gemini-4-carbon").name == "social-v2"
    assert get_provider("social-v2:authority").name == "social-v2:authority"
    assert get_provider("v16").name == "v16:all"
    assert get_provider("v16:all").name == "v16:all"
    assert get_provider("v16-template:v1").name == "v16:v1"
    assert get_provider("v16-stub:recency").name == "v16:recency"
    for b in BIASES:
        p = get_provider(f"v16-template:{b}")
        assert p.biases == (b,)
    comb = parse_variant_biases("authority+recency+bandwagon")
    assert comb == ("authority", "recency", "bandwagon")
    with pytest.raises(ValueError):
        parse_variant_biases("nonexistent_bias")


def test_social_determinism_and_stream_isolation():
    p1 = get_provider("v16-template:all")
    p2 = get_provider("v16-template:all")
    a = _play("hard", 7002, days=8, provider=None)
    b1 = _play("hard", 7002, days=8, provider=p1)
    b2 = _play("hard", 7002, days=8, provider=p2)
    assert _trace(b1) == _trace(b2)
    assert a.docs == b1.docs and a._logs == b1._logs and a._feed == b1._feed and a.V == b1.V
    assert any("-s" in mid for mid in b1._msg_order)
    base_ids = [mid for mid in b1._msg_order if "-s" not in mid]
    assert [a._messages[m] for m in a._msg_order] == [b1._messages[m] for m in base_ids]


def test_zero_decoy_and_mole_dependence_and_multiday_memory():
    e = Env("hard", 12)
    f1 = e._facts(4)
    f2 = replace(f1, decoy="e00" if f1.decoy != "e00" else "e01", decoy_mood="neutral")
    assert build_cast(f1) == build_cast(f2)
    assert generate_social_events(f1, "all") == generate_social_events(f2, "all")
    prov = SocialV2Provider(variant="all", template_only=True)
    assert prov.social_only_messages(f1) == prov.social_only_messages(f2)
    msgs_d4 = prov.social_only_messages(f1)
    assert msgs_d4
    assert any("Day " in m["body"] for m in msgs_d4)


def test_anger_words_scrubbed_decoy_intact_and_no_truth_leak():
    assert tuple(SolverPolicy.ANGER_WORDS) == ANGER_WORDS
    prov = get_provider("v16-template:all")
    decoy_angry_hits = 0
    for seed in range(25):
        e = _play("hard", seed, days=10, provider=prov)
        social_msgs = [e._messages[m] for m in e._msg_order if "-s" in m]
        assert social_msgs
        assert not lint_messages(social_msgs)
        for m in social_msgs:
            assert social_message_ok(m)
            blob = f"{m['subject']}\n{m['body']}".lower()
            for w in SolverPolicy.ANGER_WORDS:
                assert w not in blob
            for w in DECOY_VOCAB:
                assert w not in blob
            assert not _mole_named(json.dumps(m), e._world.mole)
        for w in SolverPolicy.ANGER_WORDS:
            hits = e.call("search_messages", {"query": w}).data["messages"]
            for h in hits:
                assert "-s" not in h["id"]
                if h["sender"] == e._world.decoy:
                    decoy_angry_hits += 1
    assert decoy_angry_hits > 0


def test_solver_exact_calibration_and_zero_baselines():
    for tier in ("medium", "hard"):
        for seed in range(8):
            r_base = run_episode(Env(tier, seed), SolverPolicy())
            r_soc = run_episode(Env(tier, seed, text_provider=get_provider("v16-template:all")), SolverPolicy())
            assert r_soc.score == r_base.score
            assert r_soc.accused == r_base.accused
            assert r_soc.final_day == r_base.final_day
            dn = run_episode(Env(tier, seed, text_provider=get_provider("v16-template:all")), BASELINES["do_nothing"](seed=seed))
            se = run_episode(Env(tier, seed, text_provider=get_provider("v16-template:all")), BASELINES["stop_early"](seed=seed))
            assert dn.score == 0.0
            assert se.score == 0.0


def test_rumour_follower_fooled_by_zero_info_chatter():
    rf_cls = BIAS_BASELINES["rumour_follower"]
    scores = [
        run_episode(Env("hard", seed, text_provider=get_provider("v16-template:all")), rf_cls(seed=seed)).score
        for seed in range(20)
    ]
    sol_scores = [run_episode(Env("hard", seed), SolverPolicy()).score for seed in range(20)]
    assert sum(scores) / len(scores) < 0.0
    assert sum(scores) < sum(sol_scores)


class _FakeGeminiClient:
    def __init__(self, fn):
        self.fn = fn
        self.calls = 0
        self.prompts: list[str] = []

    def chat(self, messages, **kw):
        self.calls += 1
        user_prompt = messages[-1]["content"]
        self.prompts.append(user_prompt)
        return {"text": json.dumps({"bodies": self.fn(user_prompt)})}


def test_gemini_cache_offline_replay_and_anger_scrub(tmp_path, monkeypatch):
    def good_fn(prompt: str):
        abouts = re.findall(r'"about": "([^"]+)"', prompt)
        return [f"Day check: personal unverified hunch around {x}, zero hard proof yet." for x in abouts]

    fc = _FakeGeminiClient(good_fn)
    p1 = SocialV2Provider(variant="v1", cache_dir=str(tmp_path), client=fc, name_prefix="social-v2")
    e1 = _play("medium", 7003, days=4, provider=p1)
    assert fc.calls > 0
    for pr in fc.prompts:
        low = pr.lower()
        for bad in ("mole", "decoy", str(e1._world.world_seed), "framed"):
            assert bad not in low

    cache_files = list(tmp_path.glob("*.json"))
    assert cache_files
    prov_meta = json.loads(cache_files[0].read_text())["provenance"]
    assert set(prov_meta) == {"model", "commit", "label"} and prov_meta["model"] == "gemini-4-carbon"

    monkeypatch.setenv("CANARY_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    class _NoNet:
        def chat(self, *a, **kw):
            raise AssertionError("network called on cache hit")

    p2 = SocialV2Provider(variant="v1", cache_dir=str(tmp_path), client=_NoNet(), name_prefix="social-v2")
    e2 = _play("medium", 7003, days=4, provider=p2)
    assert [e1._messages[m] for m in e1._msg_order] == [e2._messages[m] for m in e2._msg_order]

    bad_fc = _FakeGeminiClient(lambda p: ["Skipped for promotion again and e00 might take that recruiter call."])
    monkeypatch.delenv("CANARY_OFFLINE", raising=False)
    p_bad = SocialV2Provider(variant="authority", cache_dir=str(tmp_path / "bad"), client=bad_fc)
    e_bad = _play("medium", 7004, days=3, provider=p_bad)
    assert p_bad.rejects > 0
    for mid in e_bad._msg_order:
        if "-s" in mid:
            low = e_bad._messages[mid]["body"].lower()
            assert "promotion" not in low and "recruiter" not in low


def test_legacy_gemini_social_provider_and_committed_cache(monkeypatch):
    monkeypatch.setenv("CANARY_OFFLINE", "1")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    e = Env("medium", 7000)
    facts = e._facts(1)
    p = GeminiSocialProvider()
    events = [{"kind": "rumour", "speaker": "e01", "target": "e02"}]
    rendered = p.social_messages(facts, events)
    assert len(rendered) == 1 and rendered[0]["sender"] == "e01"
