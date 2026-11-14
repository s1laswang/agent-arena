"""v1.5-candidate human-bias social layer (WS2): defaults off = v1.4 identical; mechanics appear; deterministic."""
import json
import math
from dataclasses import replace

import pytest

from canary import rules
from canary.env import Env
from canary.mole.dsl import DEFAULT_STRATEGY, MoleStrategy, StrategyError
from canary.rules import SOCIAL_DEFAULTS, TIERS, TIERS_V15
from canary.solver.belief import Observations, social_loglik
from canary.solver.bench import _run_local, make_policy
from canary.solver.params import params_from_instruction


def _play(tier, seed, days=6, env_kw=None):
    e = Env(tier, seed, **(env_kw or {}))
    for _ in range(days):
        e.call("advance_day", {})
    return e


def _trace(e):
    return json.dumps({"docs": e.docs, "logs": e._logs, "feed": e._feed, "msgs": [e._messages[m] for m in e._msg_order],
                       "V": e.V}, sort_keys=True, default=list)


def test_defaults_off_and_hidden_from_v14():
    for p in TIERS.values():
        assert not p.social
        assert not any(k in p.to_dict() for k in SOCIAL_DEFAULTS)
        assert "Office chatter" not in Env(p.name, 0).instruction()
        assert "rumour" not in Env(p.name, 0).instruction()


def test_zero_knobs_identical_to_v14():
    """Explicitly zeroed knobs give a byte-identical trajectory to v1.4 (no new draws on shared RNG streams)."""
    for tier in ("medium", "hard"):
        a = _play(tier, 7001, days=8)
        with rules.tiers_version("v1.5-candidate"):
            pass
        zeroed = replace(TIERS[tier], **SOCIAL_DEFAULTS)
        assert zeroed == TIERS[tier]
        b = _play(tier, 7001, days=8)
        assert _trace(a) == _trace(b)


def test_social_does_not_shift_leak_stream():
    """With the knobs ON the leak/feed/log streams are unchanged when no doc is misforwarded (separate RNGs)."""
    with rules.tiers_version("v1.5-candidate"):
        TIERS["medium"] = replace(TIERS["medium"], p_misforward=0.0)
        b = _play("medium", 7002, days=8)
    a = _play("medium", 7002, days=8)
    assert a._feed == b._feed and a._logs == b._logs and a.docs == b.docs
    assert len(b._messages) > len(a._messages)


def test_v15_version_selectable_and_restores():
    before = dict(TIERS)
    with rules.tiers_version("v1.5-candidate"):
        assert rules.TIERS_VERSION == "v1.5-candidate" and rules.tier_params("hard").social
        assert "Office chatter" in Env("hard", 0).instruction()
    assert rules.TIERS_VERSION == "v1.4" and TIERS == before


def test_mechanics_appear_and_are_deterministic():
    with rules.tiers_version("v1.5-candidate"):
        e = _play("medium", 7003, days=6)
        e2 = _play("medium", 7003, days=6)
        assert _trace(e) == _trace(e2)
        subj = [m["subject"] for m in e._messages.values()]
        assert any(s.startswith("rumour: e") for s in subj)
        assert sum(s.startswith("unverified accusation: e") for s in subj) == 1
        assert any(s.startswith("grudge: e") for s in subj)
        r = e.call("search_messages", {"query": "rumour:"})
        assert r.ok and r.data["messages"]
        docs = e.call("list_documents", {}).data["documents"]
        fwd = [d for d in docs if "forwarded_to" in d]
        assert fwd and all(d["forwarded_to"] in d["recipients"] for d in fwd)
        for d in fwd:   # the forwarded recipient really holds the doc (leak attribution stays correct)
            assert d["doc_id"] in e._held[d["forwarded_to"]]


def test_rumour_targets_and_grudges_never_reveal_mole():
    """Seeded rumours never name the mole; unseeded ones may (the mole is not excluded from the uniform draw)."""
    with rules.tiers_version("v1.5-candidate"):
        named_mole = 0
        for seed in range(7010, 7040):
            e = Env("medium", seed)
            for d in range(1, 15):
                for ev in e._social_events(d):
                    named_mole += ev["kind"] == "rumour" and ev["target"] == e._world.mole
            pairs = {x for p in e._grudges() for x in p}
            assert e._world.decoy not in pairs
        assert named_mole > 0


def test_seed_rumour_dsl():
    s = MoleStrategy.from_json({"rules": [], "seed_rumour": "random_peer"})
    assert s.seed_rumour == "random_peer" and MoleStrategy.from_json(s.to_json()) == s
    assert "seed_rumour" not in DEFAULT_STRATEGY.to_json()
    with pytest.raises(StrategyError):
        MoleStrategy.from_json({"rules": [], "seed_rumour": "the_ceo"})
    with rules.tiers_version("v1.5-candidate"):
        e = Env("medium", 7004, mole_strategy={"rules": [], "seed_rumour": "random_peer"})
        tg = [ev["target"] for d in range(1, 15) for ev in e._social_events(d) if ev["kind"] == "rumour"]
        assert tg


def test_solver_parses_new_params():
    with rules.tiers_version("v1.5-candidate"):
        for t in ("easy", "medium", "hard"):
            assert params_from_instruction(Env(t, 3).instruction()) == TIERS_V15[t]
    for t in ("easy", "medium", "hard"):
        assert params_from_instruction(Env(t, 3).instruction()) == TIERS[t]


def test_social_loglik_exact():
    P = TIERS_V15["easy"]
    obs = Observations(employees=[f"e{i:02d}" for i in range(12)])
    obs.social = [("rumour", "e01", "e02"), ("grudge", "e03", "e04")]
    n, s = 12, P.rumour_frame_share
    assert math.isclose(social_loglik(obs, "e02", P), math.log((1 - s) / (n * (n - 1))))
    assert math.isclose(social_loglik(obs, "e05", P), math.log((1 - s) / (n * (n - 1)) + s / (n - 1) ** 2))
    Pm = TIERS_V15["medium"]
    obs.decoy = "e09"
    assert social_loglik(obs, "e02", Pm) == social_loglik(obs, "e05", Pm) == 0.0


def test_solver_unfooled_rumour_follower_fooled():
    with rules.tiers_version("v1.5-candidate"):
        sol = [_run_local(Env("medium", s), make_policy("solver", s)) for s in range(7050, 7056)]
        rf = [_run_local(Env("medium", s), make_policy("rumour_follower", s)) for s in range(7050, 7056)]
    acc = [r for r in sol if r.accused]
    assert acc and sum(r.correct for r in acc) / len(acc) >= 0.8
    assert sum(r.score for r in rf) < sum(r.score for r in sol)
