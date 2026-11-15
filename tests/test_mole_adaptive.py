from __future__ import annotations

import ast
import random
from pathlib import Path

import pytest

from canary.baselines import DoNothing
from canary.env import Env
from canary.eval import run_episode
from canary.forge.frontier_proxies import GeminiCarbonProxy
from canary.mole.adaptive import (
    ADAPTIVE_CLASSES,
    CounterFrontierMole,
    CrowdShieldMole,
    DISTILLED_DSL_JSON,
    DISTILLED_DSL_STRATEGIES,
    HorizonSqueezeMole,
    ReactiveLagMole,
    adaptive_from_json,
    list_adaptive_strategy_names,
    make_mole_strategy,
)
from canary.mole.dsl import DEFAULT_STRATEGY, MoleDoc, MoleStrategy, MoleView
from canary.solver.policy import SolverPolicy

ROOT = Path(__file__).resolve().parents[1]


def test_hygiene_and_zero_social_imports():
    hash_ch = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_ref = "solver_" + "v2"
    for rel in ("canary/mole/adaptive.py", "tests/test_mole_adaptive.py"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert hash_ch not in txt, rel
        assert em_dash not in txt, rel
        assert en_dash not in txt, rel
        assert forbidden_ref not in txt, rel

    tree = ast.parse((ROOT / "canary/mole/adaptive.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "social" not in node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "social" not in alias.name


def test_serialization_factory_and_invalid_inputs():
    names_all = list_adaptive_strategy_names(include_dsl=True, include_default=True)
    assert names_all[0] == "default_v0"
    for k in DISTILLED_DSL_STRATEGIES:
        assert k in names_all
    for k in ADAPTIVE_CLASSES:
        assert k in names_all

    names_adaptive_only = list_adaptive_strategy_names(include_dsl=False, include_default=False)
    assert names_adaptive_only == tuple(ADAPTIVE_CLASSES.keys())

    assert make_mole_strategy("default") is DEFAULT_STRATEGY
    assert make_mole_strategy("default_v0") is DEFAULT_STRATEGY

    for dsl_name, dsl_json in DISTILLED_DSL_JSON.items():
        s_by_name = make_mole_strategy(dsl_name)
        s_by_dict = make_mole_strategy(dsl_json)
        assert isinstance(s_by_name, MoleStrategy)
        assert s_by_name.to_json() == s_by_dict.to_json()

    custom_instances = [
        CrowdShieldMole(scapegoat_ring_size=5, wide_frac=0.30),
        ReactiveLagMole(scapegoat_ring_size=2, early_burst_days=4),
        HorizonSqueezeMole(scapegoat_ring_size=4, burst_target=2, lull_start=4, lull_end=9),
        CounterFrontierMole(scapegoat_ring_size=3, wide_frac=0.28, pause_narrow_until_day=14),
    ]
    for inst in custom_instances:
        payload = inst.to_json()
        rebuilt = adaptive_from_json(payload)
        cloned = inst.clone()
        via_factory = make_mole_strategy(payload)
        via_obj = make_mole_strategy(inst)
        assert rebuilt.to_json() == payload
        assert cloned.to_json() == payload
        assert via_factory.to_json() == payload
        assert via_obj.to_json() == payload
        assert via_obj is not inst

    with pytest.raises(ValueError):
        adaptive_from_json({"kind": "not_adaptive", "strategy": "adaptive_crowd_shield"})
    with pytest.raises(ValueError):
        adaptive_from_json({"kind": "adaptive_mole", "strategy": "nonexistent"})
    with pytest.raises(ValueError):
        make_mole_strategy("unknown_strategy_name")


def test_episode_reset_scapegoats_and_gate_respect():
    peers = ("emp_01", "emp_02", "emp_03", "emp_04", "emp_05")
    docs = (
        MoleDoc("doc_narrow", "Narrow", 3, 0),
        MoleDoc("doc_wide_new", "WideNew", 12, 0),
        MoleDoc("doc_wide_aged", "WideAged", 12, 2),
    )
    mole = CounterFrontierMole(scapegoat_ring_size=3)

    v_blocked = MoleView(
        day=1,
        docs=docs,
        days_since_last_leak=1,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=1,
        peers=peers,
        restricted_peers=(),
        decoy="emp_01",
        can_leak=False,
    )
    dec_blocked = mole.decide(v_blocked, random.Random(0))
    assert dec_blocked["leak"] is None
    assert dec_blocked["frame"] in peers
    assert dec_blocked["frame"] != "emp_01"

    v_open = MoleView(
        day=4,
        docs=docs,
        days_since_last_leak=4,
        i_am_restricted=0,
        n_restricted_colleagues=2,
        recent_low_recipient_docs=1,
        peers=peers,
        restricted_peers=("emp_01", "emp_04"),
        decoy="emp_01",
        can_leak=True,
    )
    dec_open = mole.decide(v_open, random.Random(0))
    assert dec_open["leak"] == "doc_wide_aged"
    assert dec_open["frame"] == "emp_04"

    v_next_ep = MoleView(
        day=1,
        docs=docs,
        days_since_last_leak=1,
        i_am_restricted=0,
        n_restricted_colleagues=0,
        recent_low_recipient_docs=1,
        peers=peers,
        restricted_peers=(),
        decoy="emp_02",
        can_leak=True,
    )
    fresh = CounterFrontierMole(scapegoat_ring_size=3)
    assert mole.decide(v_next_ep, random.Random(7)) == fresh.decide(v_next_ep, random.Random(7))


def test_env_determinism_zero_baseline_and_solver_beatability():
    seeds = range(6000, 6020)
    all_names = list_adaptive_strategy_names(include_dsl=True, include_default=False)

    for name in all_names:
        r1 = run_episode(Env("hard", 6000, mole_strategy=make_mole_strategy(name)), SolverPolicy("hard"))
        r2 = run_episode(Env("hard", 6000, mole_strategy=make_mole_strategy(name)), SolverPolicy("hard"))
        assert [(s.tool, s.args) for s in r1.steps] == [(s.tool, s.args) for s in r2.steps]
        assert r1.score == r2.score
        assert r1.accused == r2.accused

        dn = run_episode(Env("hard", 6000, mole_strategy=make_mole_strategy(name)), DoNothing(seed=6000))
        assert dn.score == 0.0

        solver_runs = [
            run_episode(Env("hard", s, mole_strategy=make_mole_strategy(name)), SolverPolicy("hard"))
            for s in seeds
        ]
        proxy_runs = [
            run_episode(Env("hard", s, mole_strategy=make_mole_strategy(name)), GeminiCarbonProxy(seed=s))
            for s in seeds
        ]
        acc = sum(1 for r in solver_runs if r.correct) / len(solver_runs)
        mean_score = sum(r.score for r in solver_runs) / len(solver_runs)
        proxy_mean = sum(r.score for r in proxy_runs) / len(proxy_runs)
        paired_regret = mean_score - proxy_mean
        assert acc >= 0.85, (name, acc)
        assert mean_score >= 0.25, (name, mean_score)
        assert paired_regret > 0.0, (name, mean_score, proxy_mean)
