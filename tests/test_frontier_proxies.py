from __future__ import annotations

from pathlib import Path
import pickle
import random
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from canary.baselines import play
from canary.env import Env
from canary.eval import run_episode
from canary.forge.fitness import ClassFactory, default_solver_factory, evaluate, solver_baseline
from canary.forge.frontier_proxies import (
    CodexHorizonProxy,
    CodexProxy,
    GeminiCarbonProxy,
    frontier_proxy_investigators,
)
from canary.forge.mutate import default_strategy_json, validate_strategy
from canary.mole.dsl import MoleStrategy
from canary.types import Step


def _step(t: int, day: int, tool: str, args: dict, data: dict, ok: bool = True) -> Step:
    return Step(t=t, day=day, tool=tool, args=args, result={"ok": ok, "data": data, "error": None if ok else "err"})


def test_hygiene_no_comments_or_em_dashes():
    root = Path(__file__).resolve().parents[1]
    hash_ch = chr(35)
    em_dash = "\u2014"
    for rel in ("canary/forge/frontier_proxies.py", "tests/test_frontier_proxies.py"):
        txt = (root / rel).read_text(encoding="utf-8")
        assert hash_ch not in txt, rel
        assert em_dash not in txt, rel


def test_policy_names_and_picklable_factories():
    assert GeminiCarbonProxy.name == "gemini_carbon_proxy"
    assert CodexHorizonProxy.name == "codex_horizon_proxy"
    assert CodexProxy is CodexHorizonProxy
    assert CodexProxy.name == "codex_horizon_proxy"

    only_proxies = frontier_proxy_investigators(include_defaults=False)
    assert set(only_proxies) == {"gemini_carbon_proxy", "codex_horizon_proxy"}

    with_defaults = frontier_proxy_investigators(include_defaults=True)
    assert {"heuristic", "hinted_heuristic", "gemini_carbon_proxy", "codex_horizon_proxy"} <= set(with_defaults)

    for name, fac in with_defaults.items():
        assert isinstance(fac, ClassFactory), name
        restored = pickle.loads(pickle.dumps(fac))
        pol = restored(7)
        assert getattr(pol, "seed", None) == 7


@pytest.mark.parametrize("cls", [GeminiCarbonProxy, CodexHorizonProxy])
@pytest.mark.parametrize("tier,seed", [("medium", 5), ("hard", 6)])
def test_deterministic_and_isolated_from_global_rng(cls, tier, seed):
    random.seed(111)
    pol = cls(seed=seed)
    a = run_episode(Env(tier, seed), pol)
    random.seed(999999)
    b = run_episode(Env(tier, seed), cls(seed=seed))
    assert [(s.tool, s.args) for s in a.steps] == [(s.tool, s.args) for s in b.steps]
    assert a.accused == b.accused
    assert a.score == b.score

    c = run_episode(Env(tier, seed), pol)
    assert [(s.tool, s.args) for s in a.steps] == [(s.tool, s.args) for s in c.steps]


@pytest.mark.parametrize("cls", [GeminiCarbonProxy, CodexHorizonProxy])
@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
def test_public_tools_only_completion_across_tiers(cls, tier):
    for seed in range(2):
        env = Env(tier, seed)
        allowed = {spec["name"] for spec in env.tools_spec()}
        pol = cls(seed=seed)
        res = run_episode(env, pol)
        assert res.end_reason in ("accused", "horizon")
        assert len(res.steps) < env.p.tool_call_cap
        for st in res.steps:
            assert st.tool in allowed
            assert st.result.get("error") != "invalid arguments"


def test_gemini_proxy_signature_behaviors():
    for seed in range(2):
        env = Env("hard", seed)
        pol = GeminiCarbonProxy(seed=seed)
        res = run_episode(env, pol)

        assert any(st.day == 1 and st.tool == "search_messages" for st in res.steps)
        assert pol.decoy == env._world.decoy
        assert res.accused != env._world.decoy

        by_day_canaries: dict[int, int] = {}
        for st in res.steps:
            if st.tool == "plant_canary" and st.result.get("ok"):
                by_day_canaries[st.day] = by_day_canaries.get(st.day, 0) + 1
                asg = st.args["assignment"]
                assert 2 <= len(asg) <= 6
                assert 1 <= len(set(asg.values())) <= 3
        assert all(cnt <= 1 for cnt in by_day_canaries.values())
        assert sum(by_day_canaries.values()) < res.final_day

        log_calls = [st for st in res.steps if st.tool == "read_access_logs" and st.result.get("ok")]
        assert 1 <= len(log_calls) < res.final_day

    ins = (
        "You are the security lead of a company with 8 employees, with ids e00 to e07.\n"
        "- n_days: 21\n- max_variants: 3\n- canaries_per_day: 2\n- actions_per_day: 8\n"
        "- decoy: on\n- fingerprint_accuracy: 0.95\n- wrong_accusation_score: -1\n"
    )
    pol = GeminiCarbonProxy(seed=0)
    pol.reset([], ins)
    emps = [{"id": f"e0{i}"} for i in range(8)]
    hist = [
        _step(0, 1, "list_employees", {}, {"employees": emps}),
        _step(1, 1, "search_messages", {"query": "unfair"}, {
            "messages": [{"id": "m1", "day": 1, "sender": "e00", "subject": "", "snippet": "This is unfair"}],
        }),
        _step(2, 4, "advance_day", {}, {"day": 4, "V": 0.90}),
        _step(3, 4, "status", {}, {"day": 4, "V": 0.90, "actions_left_today": 8, "restricted": []}),
        _step(4, 4, "list_documents", {"day_from": 2, "day_to": 4}, {
            "documents": [{
                "doc_id": "c2",
                "day": 2,
                "recipients": ["e01", "e02", "e03", "e04", "e05", "e06"],
                "is_canary": True,
                "variants": {"v1": ["e01"], "v2": ["e02", "e03", "e04"], "v3": ["e05", "e06"]},
            }],
        }),
        _step(5, 4, "check_leak_feed", {}, {"items": [{"surfaced_day": 4, "doc_id": "c2", "variant": "v1"}]}),
    ]
    tool, args = pol.act(hist)
    assert (tool, args) == ("accuse", {"employee": "e01"})

    tie_pol = GeminiCarbonProxy(seed=0)
    tie_pol.reset([], ins)
    tie_hist = [
        _step(0, 1, "list_employees", {}, {"employees": emps}),
        _step(1, 1, "search_messages", {"query": "unfair"}, {
            "messages": [{"id": "m1", "day": 1, "sender": "e00", "subject": "", "snippet": "unfair"}],
        }),
        _step(2, 21, "advance_day", {}, {"day": 21, "V": 0.50}),
        _step(3, 21, "status", {}, {"day": 21, "V": 0.50, "actions_left_today": 8, "restricted": []}),
        _step(4, 21, "list_documents", {"day_from": 1, "day_to": 21}, {
            "documents": [{"doc_id": "d1", "day": 1, "recipients": ["e00", "e01", "e02"], "is_canary": False}],
        }),
        _step(5, 21, "check_leak_feed", {}, {"items": [{"surfaced_day": 3, "doc_id": "d1"}]}),
        _step(6, 21, "read_access_logs", {"day_from": 1, "day_to": 20}, {
            "logs": [
                {"day": 2, "employee": "e00", "doc_id": "d1", "after_hours": True},
                {"day": 3, "employee": "e00", "doc_id": "d1", "after_hours": True},
                {"day": 4, "employee": "e00", "doc_id": "d1", "after_hours": True},
                {"day": 2, "employee": "e02", "doc_id": "d1", "after_hours": True},
                {"day": 3, "employee": "e02", "doc_id": "d1", "after_hours": True},
            ],
        }),
    ]
    tool, args = tie_pol.act(tie_hist)
    assert (tool, args) == ("accuse", {"employee": "e02"})


def test_codex_horizon_proxy_signature_behaviors():
    for seed in range(2):
        env = Env("hard", seed)
        pol = CodexHorizonProxy(seed=seed)
        res = run_episode(env, pol)

        assert pol.decoy == env._world.decoy
        assert res.accused != env._world.decoy
        assert any(st.tool == "interview" and st.result.get("ok") for st in res.steps)
        assert any(st.tool == "read_access_logs" and st.result.get("ok") for st in res.steps)

        for st in res.steps:
            if st.tool == "plant_canary" and st.result.get("ok"):
                asg = st.args["assignment"]
                counts: dict[str, int] = {}
                for lab in asg.values():
                    counts[lab] = counts.get(lab, 0) + 1
                assert all(c in (1, 2) for c in counts.values())
                if st.day >= env.p.n_days // 2:
                    assert all(c == 1 for c in counts.values())

    ins = (
        "You are the security lead of a company with 8 employees, with ids e00 to e07.\n"
        "- n_days: 14\n- max_variants: 3\n- canaries_per_day: 1\n- actions_per_day: 8\n"
        "- decoy: on\n- fingerprint_accuracy: 0.95\n- wrong_accusation_score: -1\n"
    )
    emps = [{"id": f"e0{i}"} for i in range(8)]
    pol = CodexHorizonProxy(seed=0)
    pol.reset([], ins)
    spike_hist = [
        _step(0, 1, "list_employees", {}, {"employees": emps}),
        _step(1, 1, "search_messages", {"query": "angry"}, {
            "messages": [{"id": "m1", "day": 1, "sender": "e00", "subject": "", "snippet": "angry"}],
        }),
        _step(2, 5, "advance_day", {}, {"day": 5, "V": 0.70}),
        _step(3, 5, "status", {}, {"day": 5, "V": 0.70, "actions_left_today": 8, "restricted": []}),
        _step(4, 5, "list_documents", {"day_from": 1, "day_to": 5}, {
            "documents": [{"doc_id": "d1", "day": 1, "recipients": ["e00", "e01", "e02", "e03"], "is_canary": False}],
        }),
        _step(5, 5, "check_leak_feed", {}, {"items": [{"surfaced_day": 3, "doc_id": "d1"}]}),
        _step(6, 5, "read_access_logs", {"day_from": 1, "day_to": 4}, {
            "logs": [
                {"day": 2, "employee": "e00", "doc_id": "d1", "after_hours": True},
                {"day": 3, "employee": "e00", "doc_id": "d1", "after_hours": True},
                {"day": 4, "employee": "e00", "doc_id": "d1", "after_hours": True},
                {"day": 2, "employee": "e03", "doc_id": "d1", "after_hours": True},
                {"day": 3, "employee": "e03", "doc_id": "d1", "after_hours": True},
                {"day": 4, "employee": "e03", "doc_id": "d1", "after_hours": True},
                {"day": 2, "employee": "e01", "doc_id": "d1", "after_hours": True},
            ],
        }),
    ]
    tool, args = pol.act(spike_hist)
    pool = pol._suspect_pool()
    true_post = pol._posterior(pool, pol.fingerprint_accuracy)
    assert true_post["e03"] < 1.0 / (1.0 + pol.V)
    assert (tool, args) == ("accuse", {"employee": "e03"})

    hor_pol = CodexHorizonProxy(seed=0)
    hor_pol.reset([], ins)
    hor_hist = [
        _step(0, 1, "list_employees", {}, {"employees": emps}),
        _step(1, 1, "search_messages", {"query": "angry"}, {
            "messages": [{"id": "m1", "day": 1, "sender": "e00", "subject": "", "snippet": "angry"}],
        }),
        _step(2, 14, "advance_day", {}, {"day": 14, "V": 0.40}),
        _step(3, 14, "status", {}, {"day": 14, "V": 0.40, "actions_left_today": 8, "restricted": []}),
        _step(4, 14, "list_documents", {"day_from": 12, "day_to": 14}, {"documents": []}),
        _step(5, 14, "check_leak_feed", {}, {"items": []}),
        _step(6, 14, "read_access_logs", {"day_from": 1, "day_to": 13}, {
            "logs": [{"day": 10, "employee": "e05", "doc_id": "d1", "after_hours": True}],
        }),
    ]
    tool, args = hor_pol.act(hor_hist)
    assert tool == "accuse" and args["employee"] == "e05"


def test_forge_evaluate_compatibility_and_v14_calibration():
    seeds = (6, 17)
    sol_factory = default_solver_factory()
    base_hard = solver_baseline(sol_factory, seeds, "hard", workers=1)

    ev = evaluate(
        default_strategy_json(),
        frontier_proxy_investigators(include_defaults=True),
        sol_factory,
        seeds,
        "hard",
        workers=1,
        baseline=base_hard,
        fitness_mode="min",
        min_solver_acc=0.85,
    )
    assert ev["feasible"]
    solver_hard = ev["solver_score"]
    for name in ("gemini_carbon_proxy", "codex_horizon_proxy"):
        proxy_score = ev["per_investigator"][name]["score"]
        assert 0.0 < proxy_score < solver_hard, (name, proxy_score, solver_hard)
        assert ev["per_investigator"][name]["regret"] > 0.0
        assert name in ev["beaten"]

    gem_can_per_day: list[float] = []
    for s in seeds:
        env_g = Env("hard", s)
        pol_g = GeminiCarbonProxy(seed=s)
        res_g = run_episode(env_g, pol_g)
        assert pol_g.decoy == env_g._world.decoy
        assert res_g.accused != env_g._world.decoy
        nc = sum(1 for st in res_g.steps if st.tool == "plant_canary" and st.result.get("ok"))
        gem_can_per_day.append(nc / max(1, res_g.final_day))
    mean_gem_cpd = sum(gem_can_per_day) / len(gem_can_per_day)
    assert 0.40 <= mean_gem_cpd <= 0.50, mean_gem_cpd

    dev_seeds = (10008,)
    for tier in ("easy", "medium"):
        sol_mean = sum(play(Env(tier, s), sol_factory(s)) for s in dev_seeds) / len(dev_seeds)
        for cls in (GeminiCarbonProxy, CodexHorizonProxy):
            proxy_mean = sum(play(Env(tier, s), cls(seed=s)) for s in dev_seeds) / len(dev_seeds)
            assert 0.0 < proxy_mean < sol_mean, (tier, cls.name, proxy_mean, sol_mean)

    anti_frontier = MoleStrategy.from_json(validate_strategy({
        "rules": [{"if": [["recent_low_recipient_docs", ">=", 1]], "then": {"leak": "most_recipients", "frame": "random_peer"}}],
        "default": {"leak": "most_recipients", "frame": "random_peer"},
    }))
    for cls in (GeminiCarbonProxy, CodexHorizonProxy):
        default_sc = sum(play(Env("hard", s), cls(seed=s)) for s in dev_seeds) / len(dev_seeds)
        anti_sc = sum(play(Env("hard", s, mole_strategy=anti_frontier), cls(seed=s)) for s in dev_seeds) / len(dev_seeds)
        assert anti_sc < default_sc, (cls.name, anti_sc, default_sc)
