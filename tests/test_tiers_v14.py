"""Tiers v1.4 (CONTRACT §14): 2 canaries/day and 21 days on hard; v1.3 stays reproducible."""
import json
from pathlib import Path

from canary import rules
from canary.env import Env
from canary.solver import SolverPolicy
from canary.solver.bench import _run_local

ROOT = Path(__file__).resolve().parents[1]


def test_hard_v14_values_in_instruction():
    p = rules.TIERS["hard"]
    assert (p.n_employees, p.n_days, p.canaries_per_day, p.max_variants, p.leak_damage, p.tool_call_cap) == (40, 21, 2, 3, 0.05, 420)
    txt = Env("hard", 0).instruction()
    for s in ("40 employees, with ids e00 to e39", "lasts at most 21 days", "If day 21 ends", "at most 2 per day",
              "at most 3 different labels", "lowers the true V by 0.05", "total limit of 420 calls",
              "- canaries_per_day: 2", "- n_days: 21", "- tool_call_cap: 420", "- max_variants: 3", "- n_employees: 40"):
        assert s in txt, s


def test_two_canaries_per_day_distinct_ids_third_rejected():
    env = Env("hard", 3)
    a = env.call("plant_canary", {"doc_title": "m1", "assignment": {"e00": "A", "e01": "B", "e02": "C"}})
    b = env.call("plant_canary", {"doc_title": "m2", "assignment": {"e03": "A", "e04": "B"}})
    c = env.call("plant_canary", {"doc_title": "m3", "assignment": {"e05": "A"}})
    assert a.ok and b.ok and not c.ok and c.error == "canary limit for today reached"
    assert (a.data["canary_id"], b.data["canary_id"]) == ("c1", "c1-2")
    docs = {d["doc_id"]: d for d in env.call("list_documents", {}).data["documents"]}
    assert docs["c1"]["variants"] == {"A": ["e00"], "B": ["e01"], "C": ["e02"]}
    assert docs["c1-2"]["variants"] == {"A": ["e03"], "B": ["e04"]}
    env.call("advance_day", {})
    assert env.call("plant_canary", {"doc_title": "m4", "assignment": {"e06": "A"}}).data["canary_id"] == "c2"


def test_episode_runs_21_days_and_feed_shows_second_canary():
    seen = False
    for seed in range(30):
        env = Env("hard", seed)
        while not env.done:
            for k in range(2):
                # careful mole: a canary to everyone is never leaked, so each canary goes to a quarter of staff
                asg = {e: "AB"[i % 2] for i, e in enumerate(env._ids[k * 10:(k + 1) * 10])}
                env.call("plant_canary", {"doc_title": f"t{k}", "assignment": asg})
            env.call("advance_day", {})
        assert env.day == 21 and env.score() == 0.0 and env._end_reason == "horizon"
        seen |= any(f["doc_id"].endswith("-2") and "variant" in f for f in env._feed)
    assert seen


def test_solver_plans_at_most_cpd_canaries_and_is_deterministic():
    r1 = _run_local(Env("hard", 11), SolverPolicy(None))
    r2 = _run_local(Env("hard", 11), SolverPolicy(None))
    assert [(s.tool, s.args) for s in r1.steps] == [(s.tool, s.args) for s in r2.steps]
    per_day = {}
    for s in r1.steps:
        if s.tool == "plant_canary":
            assert s.result["ok"], s.result
            per_day[s.day] = per_day.get(s.day, 0) + 1
    assert per_day and max(per_day.values()) <= 2 and 2 in per_day.values()


def test_v13_solver_replays_committed_reference_runs():
    """Committed v1.3 reference episodes (0933805) replay step-for-step under rules.tiers_version('v1.3')."""
    for tier in ("medium", "hard"):
        f = next((ROOT / "data/runs/committed/v1.3/reference").glob(f"solver-{tier}-*/episodes.jsonl"))
        eps = [json.loads(line) for line in f.read_text().splitlines()[:4]]
        with rules.tiers_version("v1.3"):
            for ep in eps:
                r = _run_local(Env(tier, ep["seed"]), SolverPolicy(None))
                assert [(s.tool, s.args) for s in r.steps] == [(s["tool"], s["args"]) for s in ep["steps"]], (tier, ep["seed"])
                assert r.score == ep["score"]


def test_offline_analysis_uses_the_episode_tier_version():
    """accuse/regret audits of committed v1.3 hard runs use the v1.3 hard params (30 staff, 14 days)."""
    from canary.analysis.tags import to_result
    f = next((ROOT / "data/runs/committed/v1.3/reference").glob("solver-hard-*/episodes.jsonl"))
    ep = to_result(json.loads(f.read_text().splitlines()[0]))
    assert rules.tier_params_for_episode("hard", ep.steps) == rules.TIERS_V13["hard"]
    fresh = _run_local(Env("hard", 1), SolverPolicy(None))
    assert rules.tier_params_for_episode("hard", fresh.steps) == rules.TIERS["hard"]
    assert rules.tier_params_for_episode("hard", []) == rules.TIERS["hard"]
