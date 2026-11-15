from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import textwrap
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ARENA_DIR = ROOT / "docs" / "arena"
GAME_DIR = ROOT / "game"
for p in (str(ARENA_DIR), str(GAME_DIR), str(ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

import scoring_parity as sp
import canary_game
from canary.baselines import BASELINES, CALIBRATION_POLICIES
from canary.env import Env
from canary.eval import episode_from_dict, make_env, make_policy_factory, run_episode
from canary.rules import TIERS
from canary.solver.policy import SolverPolicy
from canary.types import EpisodeResult

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
OWNED_FILES = (
    "docs/arena/scoring_parity.py",
    "tests/test_arena_investigator_parity.py",
)
NAMED_BASELINES = (
    "heuristic",
    "grok_tactics",
    "logs_only",
    "random",
    "do_nothing",
    "stop_early",
    "guess_day1",
)
ALL_SCRIPTED_AGENTS = tuple(sorted(set(BASELINES) | set(CALIBRATION_POLICIES)))


@lru_cache(maxsize=None)
def _load_committed_gemini_episode(tier: str, seed: int) -> dict:
    ep_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / tier / "episodes.jsonl"
    for line in ep_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if int(row["seed"]) == seed:
            return row
    raise LookupError(f"missing committed episode for {tier} seed {seed}")


def test_hygiene_protected_paths_and_stdlib_only():
    protected_file = ROOT / ".github" / "protected-paths.txt"
    protected_prefixes: list[str] = []
    for raw in protected_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        protected_prefixes.append(line)

    for rel in OWNED_FILES:
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert src.isascii(), f"non-ASCII char found in {rel}"
        assert HASH_CHAR not in src, f"comment char found in {rel}"
        assert EM_DASH not in src, f"em dash found in {rel}"
        assert EN_DASH not in src, f"en dash found in {rel}"
        for prefix in protected_prefixes:
            if prefix.endswith("/"):
                assert not rel.startswith(prefix), f"{rel} touches protected dir {prefix}"
            else:
                assert rel != prefix, f"{rel} touches protected file {prefix}"

    probe_code = textwrap.dedent(
        """
        import json, sys
        sys.path.insert(0, sys.argv[1])
        import scoring_parity as sp
        rep = sp.verify_action_list_parity("easy", 6, [["advance_day", {}] for _ in range(14)])
        s = sp.duel_end_screen_summary(
            "easy", 6,
            {"score": 0.0, "correct": False, "accused": None, "end_reason": "horizon", "final_day": 14, "tool_calls": 14},
            {"score": -1.0, "correct": False, "accused": "e00", "end_reason": "accused", "final_day": 2, "tool_calls": 4},
            {"score": 0.88, "correct": True, "accused": "e01", "end_reason": "accused", "final_day": 3, "tool_calls": 19},
        )
        stdlib = set(sys.stdlib_module_names) | {"builtins", "__main__", "_frozen_importlib", "_frozen_importlib_external"}
        non_stdlib = sorted(
            name for name in sys.modules
            if name.split(".")[0] not in stdlib
            and name.split(".")[0] not in {"canary", "canary_game", "scoring_parity"}
        )
        print(json.dumps({"ok": rep["ok"], "non_stdlib": non_stdlib, "share": s["share_line"]}))
        """
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe_code, str(ARENA_DIR)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["ok"] is True
    assert payload["non_stdlib"] == []
    assert EM_DASH not in payload["share"]


@lru_cache(maxsize=None)
def _cached_solver_run(tier: str, seed: int) -> tuple[EpisodeResult, list[list]]:
    return sp.record_policy_actions(tier, seed, SolverPolicy())


@pytest.mark.parametrize("tier", ["easy", "medium", "hard"])
@pytest.mark.parametrize("seed", [3000, 3001, 3002, 3003, 6, 26])
def test_solver_policy_parity_across_tiers_and_seeds(tier: str, seed: int):
    solver_ep, actions = _cached_solver_run(tier, seed)
    replayed_ep = run_episode(make_env(tier, seed, "template"), sp.RecordedActionsPolicy(actions))
    assert replayed_ep.score == solver_ep.score
    assert replayed_ep.correct == solver_ep.correct
    assert replayed_ep.accused == solver_ep.accused
    assert replayed_ep.end_reason == solver_ep.end_reason
    assert replayed_ep.final_day == solver_ep.final_day
    assert replayed_ep.steps == solver_ep.steps

    report = sp.verify_action_list_parity(tier, seed, actions)
    assert json.loads(json.dumps(report)) == report
    assert report["ok"] is True
    assert report["done"] is True
    assert report["score"] == solver_ep.score
    assert report["correct"] == solver_ep.correct
    assert report["accused"] == solver_ep.accused
    assert report["end_reason"] == solver_ep.end_reason
    assert report["final_day"] == solver_ep.final_day
    assert report["tool_calls"] == len(solver_ep.steps)
    assert report["final"] == {
        "accused": solver_ep.accused,
        "correct": solver_ep.correct,
        "final_day": solver_ep.final_day,
        "tool_calls": len(solver_ep.steps),
        "score": solver_ep.score,
    }
    assert set(report["final"].keys()) == set(sp.CRAFT_FINAL_VERDICT_KEYS)
    assert report["pre_done_steps_checked"] == len(solver_ep.steps) - 1
    assert report["canary_game_checked"] is (tier == "medium" and 3000 <= seed <= 9999)
    assert report["reveal_refusals_checked"] == len(solver_ep.steps)


def test_named_baselines_subset_of_all_scripted():
    assert set(NAMED_BASELINES) <= set(ALL_SCRIPTED_AGENTS)


@pytest.mark.parametrize("agent_name", ALL_SCRIPTED_AGENTS)
def test_all_scripted_baselines_parity(agent_name: str):
    factory = make_policy_factory(agent_name)
    cases = (("easy", 6), ("medium", 3000), ("hard", 26))
    for tier, seed in cases:
        ep, actions = sp.record_policy_actions(tier, seed, factory(seed))
        rep = sp.verify_action_list_parity(tier, seed, actions)
        assert rep["score"] == ep.score
        assert rep["correct"] == ep.correct
        assert rep["accused"] == ep.accused
        assert rep["end_reason"] == ep.end_reason
        assert rep["final_day"] == ep.final_day
        assert rep["tool_calls"] == len(ep.steps)
        if tier == "medium" and seed == 3000:
            assert rep["canary_game_checked"] is True


def test_malformed_json_args_do_not_count_or_shift_episode():
    bad_payloads = ("{not json", "[1, 2", "{employee: e00}", "{,", "tru")
    for tier, seed in (("easy", 6), ("medium", 3000), ("hard", 26)):
        session = sp.ArenaSession(tier, seed)
        for raw_bad in bad_payloads:
            out = json.loads(session.call_json("interview", raw_bad))
            assert out == {
                "ok": False,
                "data": {},
                "error": "arguments are not valid JSON",
                "done": False,
            }
        assert session.env.history == []
        assert session.actions == []

    cg = canary_game.Game(3000)
    session = sp.ArenaSession("medium", 3000)
    cap = TIERS["medium"].tool_call_cap

    s1 = json.loads(session.call_json("status", "{}"))
    c1 = json.loads(cg.call_json("status", "{}"))
    assert s1 == c1 and s1["data"]["tool_calls_left"] == cap - 1

    for raw_bad in bad_payloads:
        sb = json.loads(session.call_json("accuse", raw_bad))
        cb = json.loads(cg.call_json("accuse", raw_bad))
        assert sb == cb and sb["ok"] is False and sb["done"] is False
    assert len(session.actions) == 1 and len(cg.actions) == 1

    s2 = json.loads(session.call_json("status", ""))
    c2 = json.loads(cg.call_json("status", ""))
    assert s2 == c2 and s2["data"]["tool_calls_left"] == cap - 2

    for _ in range(TIERS["medium"].n_days):
        session.call_json("advance_day", "{}")
        cg.call_json("advance_day", "{}")

    assert session.env.done and cg.env.done
    rep = sp.verify_action_list_parity("medium", 3000, session.actions)
    assert rep["tool_calls"] == 2 + TIERS["medium"].n_days
    assert rep["score"] == 0.0
    assert rep["end_reason"] == "horizon"


def test_1bc3e281_invalid_arguments_data_detail_parity():
    invalid_calls: list[tuple[list, str]] = [
        (["accuse", ["e00"]], "arguments must be a JSON object"),
        (["status", 7], "arguments must be a JSON object"),
        (["interview", "e00"], "arguments must be a JSON object"),
        (["status", {"extra": 1}], "unknown argument(s)"),
        (["interview", {"employee": "e00"}], "missing required argument(s)"),
        (["read_access_logs", {"day_from": True, "day_to": 1}], "must be an integer"),
        (["read_access_logs", {"day_from": 0, "day_to": 1}], "must be between 1 and"),
        (["read_access_logs", {"day_from": 3, "day_to": 1}], "day_from must not be after day_to"),
        (["accuse", {"employee": "e99"}], "employee must be an id returned by list_employees"),
        (["interview", {"employee": "e00", "topic": "rumors"}], "topic must be one of"),
        (["search_messages", {"query": "*"}], "must not contain *"),
        (["read_message", {"id": "msg_missing"}], "unknown message id"),
        (
            ["plant_canary", {"doc_title": "Trap", "assignment": {"e00": "A", "e01": "B", "e02": "C", "e03": "D"}}],
            "distinct variant labels",
        ),
        (["unrestrict_access", {"employee": "e00"}], "is not restricted"),
    ]

    actions = [pair for pair, _ in invalid_calls]
    actions.append(["restrict_access", {"employee": "e00"}])
    actions.append(["restrict_access", {"employee": "e00"}])
    actions.extend(["advance_day", {}] for _ in range(TIERS["medium"].n_days))

    session = sp.ArenaSession("medium", 3000)
    for idx, (call_pair, expected_substr) in enumerate(invalid_calls):
        tool, args = call_pair
        res = json.loads(session.call_json(tool, json.dumps(args)))
        assert res["ok"] is False, f"step {idx} unexpectedly succeeded"
        assert res["error"] == "invalid arguments"
        assert set(res["data"]) == {"detail"}
        assert expected_substr in res["data"]["detail"]
        assert res["done"] is False

    r_ok = json.loads(session.call_json("restrict_access", json.dumps({"employee": "e00"})))
    assert r_ok["ok"] is True
    r_dup = json.loads(session.call_json("restrict_access", json.dumps({"employee": "e00"})))
    assert r_dup["ok"] is False and r_dup["error"] == "invalid arguments"
    assert "already restricted" in r_dup["data"]["detail"]

    rep = sp.verify_action_list_parity("medium", 3000, actions)
    assert rep["detail_error_steps"] == len(invalid_calls) + 1
    assert rep["canary_game_checked"] is True
    assert rep["tool_calls"] == len(actions)
    assert rep["score"] == 0.0
    assert rep["end_reason"] == "horizon"


def test_horizon_abstention_and_unfinished_stop_early_zero_score():
    for tier, seed in (("easy", 6), ("medium", 3000), ("hard", 26)):
        n_days = TIERS[tier].n_days
        actions = [["advance_day", {}] for _ in range(n_days)]
        rep = sp.verify_action_list_parity(tier, seed, actions)
        assert rep["done"] is True
        assert rep["end_reason"] == "horizon"
        assert rep["accused"] is None
        assert rep["correct"] is False
        assert rep["score"] == 0.0
        assert rep["final_day"] == n_days
        assert rep["tool_calls"] == n_days

    partial_actions = [
        ["list_employees", {}],
        ["status", {}],
        ["read_access_logs", {"day_from": 1, "day_to": 1}],
    ]
    partial_rep = sp.verify_action_list_parity("medium", 3000, partial_actions)
    assert partial_rep["done"] is False
    assert partial_rep["end_reason"] == "error"
    assert partial_rep["accused"] is None
    assert partial_rep["correct"] is False
    assert partial_rep["score"] == 0.0
    assert partial_rep["tool_calls"] == 3
    assert partial_rep["canary_game_checked"] is True


def test_tool_cap_zero_score_and_post_done_calls_rejected():
    for tier, seed in (("easy", 6), ("medium", 3000), ("hard", 26)):
        cap = TIERS[tier].tool_call_cap
        actions = [["status", {}] for _ in range(cap)]
        rep = sp.verify_action_list_parity(tier, seed, actions)
        assert rep["done"] is True
        assert rep["end_reason"] == "tool_cap"
        assert rep["accused"] is None
        assert rep["correct"] is False
        assert rep["score"] == 0.0
        assert rep["final_day"] == 1
        assert rep["tool_calls"] == cap

    session = sp.ArenaSession("medium", 3000)
    mole = session.env._world.mole
    for _ in range(TIERS["medium"].tool_call_cap):
        session.call_json("status", "{}")
    assert session.env.done is True
    late = json.loads(session.call_json("accuse", json.dumps({"employee": mole})))
    assert late == {"ok": False, "data": {}, "error": "episode over", "done": True}
    rev = json.loads(session.reveal_json())
    assert rev["you"]["score"] == 0.0
    assert rev["you"]["accused"] is None
    assert rev["you"]["end_reason"] == "tool_cap"


def test_wrong_accusation_minus_one_across_tiers():
    for tier, seed in (("easy", 6), ("medium", 3000), ("hard", 26)):
        probe_env = Env(tier, seed)
        mole = probe_env._world.mole
        innocent = next(emp.id for emp in probe_env._world.employees if emp.id != mole)
        actions = [
            ["list_employees", {}],
            ["status", {}],
            ["accuse", {"employee": innocent}],
        ]
        rep = sp.verify_action_list_parity(tier, seed, actions)
        assert rep["done"] is True
        assert rep["end_reason"] == "accused"
        assert rep["accused"] == innocent
        assert rep["correct"] is False
        assert rep["score"] == -1.0
        assert rep["tool_calls"] == 3


def test_correct_accusation_when_true_v_is_zero_scores_zero():
    probe_env = Env("medium", 3000)
    mole = probe_env._world.mole
    emps = [e.id for e in probe_env._world.employees]
    actions: list[list] = []
    for emp_id in emps[:8]:
        actions.append(["restrict_access", {"employee": emp_id}])
    actions.append(["advance_day", {}])
    for emp_id in emps[8:16]:
        actions.append(["restrict_access", {"employee": emp_id}])
    actions.append(["advance_day", {}])
    for emp_id in emps[16:19]:
        actions.append(["restrict_access", {"employee": emp_id}])
    for _ in range(5):
        actions.append(["advance_day", {}])
    actions.append(["status", {}])
    actions.append(["accuse", {"employee": mole}])

    rep = sp.verify_action_list_parity("medium", 3000, actions)
    assert rep["done"] is True
    assert rep["canary_game_checked"] is True
    assert rep["end_reason"] == "accused"
    assert rep["accused"] == mole
    assert rep["correct"] is True
    assert rep["true_v"] == 0.0
    assert rep["visible_v"] == 0.0
    assert rep["score"] == 0.0

    sim = Env("hard", 6)
    sim_actions: list[list] = []
    emps_h = [e.id for e in sim._world.employees]
    for eid in emps_h[:8]:
        sim.call("restrict_access", {"employee": eid})
        sim_actions.append(["restrict_access", {"employee": eid}])
    sim.call("advance_day", {})
    sim_actions.append(["advance_day", {}])
    for eid in emps_h[8:16]:
        sim.call("restrict_access", {"employee": eid})
        sim_actions.append(["restrict_access", {"employee": eid}])
    for _ in range(4):
        sim.call("advance_day", {})
        sim_actions.append(["advance_day", {}])
    for eid in sorted(list(sim._restricted)):
        if sim._actions_today >= sim.p.actions_per_day:
            sim.call("advance_day", {})
            sim_actions.append(["advance_day", {}])
        sim.call("unrestrict_access", {"employee": eid})
        sim_actions.append(["unrestrict_access", {"employee": eid}])
    found_hidden_zero = False
    while not sim.done and sim.day < sim.p.n_days:
        if any(f["surfaced_day"] > sim.day for f in sim._feed) and sim.visible_V() > 0:
            while sim.visible_V() > 0.04 and sim._canaries_today < sim.p.canaries_per_day and sim._actions_today < sim.p.actions_per_day:
                sim.call("plant_canary", {"doc_title": f"Drain {sim.day}", "assignment": {"e00": "A", "e01": "B"}})
                sim_actions.append(["plant_canary", {"doc_title": f"Drain {sim.day}", "assignment": {"e00": "A", "e01": "B"}}])
            if round(sim.V, 10) == 0.0 and sim.visible_V() > 0.0:
                sim.call("status", {})
                sim_actions.append(["status", {}])
                sim.call("accuse", {"employee": sim._world.mole})
                sim_actions.append(["accuse", {"employee": sim._world.mole}])
                rep_h = sp.verify_action_list_parity("hard", 6, sim_actions)
                assert rep_h["correct"] is True
                assert rep_h["visible_v"] > 0.0
                assert rep_h["true_v"] == 0.0
                assert rep_h["score"] == 0.0
                found_hidden_zero = True
                break
        sim.call("advance_day", {})
        sim_actions.append(["advance_day", {}])
    assert found_hidden_zero, "expected hard seed 6 to reach visible_V > 0 while true_V == 0"


def test_premature_reveal_refusal_and_known_v_vs_true_v_gap():
    chosen_seed = None
    chosen_actions: list[list] = []
    for seed in range(3000, 3030):
        sim = Env("medium", seed)
        acts: list[list] = []
        while sim.day < 8 and not sim.done:
            sim.call("advance_day", {})
            acts.append(["advance_day", {}])
            if any(f["surfaced_day"] > sim.day for f in sim._feed):
                sim.call("status", {})
                acts.append(["status", {}])
                acts.append(["accuse", {"employee": "not_an_employee"}])
                sim.call("accuse", {"employee": "not_an_employee"})
                acts.append(["accuse", {"employee": sim._world.mole}])
                sim.call("accuse", {"employee": sim._world.mole})
                chosen_seed = seed
                chosen_actions = acts
                break
        if chosen_seed is not None:
            break

    assert chosen_seed is not None
    session = sp.ArenaSession("medium", chosen_seed)
    assert json.loads(session.reveal_json()) == {"error": "the episode is not over yet"}
    for tool, args in chosen_actions[:-1]:
        out = json.loads(session.call_json(tool, json.dumps(args)))
        assert out["done"] is False
        assert json.loads(session.reveal_json()) == {"error": "the episode is not over yet"}
        if tool == "status":
            shown_v = out["data"]["V"]
    final_out = json.loads(session.call_json(*[chosen_actions[-1][0], json.dumps(chosen_actions[-1][1])]))
    assert final_out["done"] is True
    rev = json.loads(session.reveal_json())
    assert rev["you"]["correct"] is True
    assert rev["you"]["score"] == rev["you"]["true_V"] < rev["you"]["visible_V"] == shown_v

    rep = sp.verify_action_list_parity("medium", chosen_seed, chosen_actions)
    assert rep["canary_game_checked"] is True
    assert rep["unsurfaced_leak_steps"] >= 1
    assert rep["true_v"] < rep["visible_v"]
    assert rep["score"] == rep["true_v"]


def test_duel_end_screen_summary_tiebreaks_and_committed_gemini_replays():
    s_day = sp.duel_end_screen_summary(
        "medium",
        3000,
        {"score": 0.72, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 4, "tool_calls": 25},
        {"score": 0.90, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 10},
        {"score": 0.85, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 6, "tool_calls": 12},
    )
    assert s_day["caught_first"] == "human"
    assert s_day["score_winner"] == "gemini"
    assert s_day["ranking"] == ["human", "gemini", "solver"]

    s_calls = sp.duel_end_screen_summary(
        "medium",
        3000,
        {"score": 0.85, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 22},
        {"score": 0.80, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 18},
        {"score": 0.82, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 20},
    )
    assert s_calls["caught_first"] == "gemini"
    assert s_calls["ranking"] == ["gemini", "solver", "human"]

    s_score = sp.duel_end_screen_summary(
        "medium",
        3000,
        {"score": 0.81, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 20},
        {"score": 0.83, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 20},
        {"score": 0.88, "correct": True, "accused": "e04", "end_reason": "accused", "final_day": 5, "tool_calls": 20},
    )
    assert s_score["caught_first"] == "solver"
    assert s_score["ranking"] == ["solver", "gemini", "human"]

    s_none = sp.duel_end_screen_summary(
        "hard",
        26,
        {"score": -0.0, "correct": False, "accused": None, "end_reason": "horizon", "final_day": 21, "tool_calls": 21},
        {"score": -1.0, "correct": False, "accused": "e04", "end_reason": "accused", "final_day": 10, "tool_calls": 91},
        {"score": 0.0, "correct": False, "accused": None, "end_reason": "tool_cap", "final_day": 12, "tool_calls": 420},
    )
    assert s_none["any_caught"] is False
    assert "Caught first: none" in s_none["share_line"]
    assert "-0.000" not in s_none["share_line"]
    assert EM_DASH not in s_none["share_line"] and EN_DASH not in s_none["share_line"]

    for tier, seed in (("medium", 6), ("medium", 26), ("hard", 6), ("hard", 26)):
        gem_dict = _load_committed_gemini_episode(tier, seed)
        gem_ep = episode_from_dict(gem_dict)
        gem_actions = sp.actions_from_episode(gem_ep)
        gem_rep = sp.verify_action_list_parity(tier, seed, gem_actions)
        assert gem_rep["score"] == gem_ep.score
        assert gem_rep["accused"] == gem_ep.accused
        assert gem_rep["correct"] == gem_ep.correct

        sol_ep, _ = _cached_solver_run(tier, seed)
        hum_ep = run_episode(make_env(tier, seed, "template"), make_policy_factory("heuristic")(seed))
        duel = sp.duel_end_screen_summary(tier, seed, hum_ep, gem_ep, sol_ep)
        duel_from_dicts = sp.duel_end_screen_summary(tier, seed, asdict(hum_ep), gem_dict, asdict(sol_ep))
        assert duel == duel_from_dicts
        assert duel["share_line"].isascii()
        assert EM_DASH not in duel["share_line"] and HASH_CHAR not in duel["share_line"]

        if (tier, seed) == ("hard", 6):
            assert duel["gemini"]["correct"] is True and duel["solver"]["correct"] is True
            assert duel["gemini"]["final_day"] == 6 and duel["solver"]["final_day"] == 6
            assert duel["solver"]["tool_calls"] < duel["gemini"]["tool_calls"]
            assert duel["caught_first"] in ("human", "solver")
            assert duel["ranking"].index("solver") < duel["ranking"].index("gemini")
        if (tier, seed) == ("hard", 26):
            assert duel["gemini"]["score"] == -1.0 and duel["gemini"]["correct"] is False
            assert duel["solver"]["correct"] is True


def test_arena_game_auto_discovery_absent_present_and_tamper_detection(tmp_path: Path):
    assert sp.discover_arena_game_module() is None
    base_actions = [["advance_day", {}] for _ in range(TIERS["hard"].n_days)]
    rep_absent = sp.verify_action_list_parity("hard", 6, base_actions)
    assert rep_absent["arena_game"] == {
        "present": False,
        "checked": False,
        "game_checked": False,
        "replay_checked": False,
    }

    multi_dir = tmp_path / "multi"
    multi_dir.mkdir()
    (multi_dir / "arena_game.py").write_text(
        textwrap.dedent(
            """
            import json
            from canary.env import Env

            class Game:
                def __init__(self, tier: str, seed: int):
                    self.tier = tier
                    self.seed = int(seed)
                    self.env = Env(tier, self.seed)
                    self.actions = []

                def call_json(self, tool: str, args_json: str) -> str:
                    args = json.loads(args_json) if args_json else {}
                    res = self.env.call(tool, args)
                    self.actions.append([tool, args])
                    return json.dumps({"ok": res.ok, "data": res.data, "error": res.error, "done": self.env.done})

                def reveal_json(self) -> str:
                    if not self.env.done:
                        return json.dumps({"error": "the episode is not over yet"})
                    v = self.env.verdict()
                    return json.dumps({
                        "mole": self.env._world.mole,
                        "you": {
                            "score": v["score"],
                            "correct": v["correct"],
                            "accused": v["accused"],
                            "end_reason": v["end_reason"],
                            "final_day": v["final_day"],
                            "tool_calls": len(self.actions),
                        },
                    })

            def replay(tier: str, seed: int, actions: list) -> dict:
                g = Game(tier, seed)
                for t, a in actions:
                    g.call_json(t, json.dumps(a))
                return g.env.verdict()
            """
        ),
        encoding="utf-8",
    )
    rep_multi = sp.verify_action_list_parity("hard", 6, base_actions, arena_dir=multi_dir)
    assert rep_multi["arena_game"]["present"] is True
    assert rep_multi["arena_game"]["checked"] is True
    assert rep_multi["arena_game"]["game_checked"] is True
    assert rep_multi["arena_game"]["replay_checked"] is True

    med_dir = tmp_path / "med_only"
    med_dir.mkdir()
    (med_dir / "arena_game.py").write_text((GAME_DIR / "canary_game.py").read_text(encoding="utf-8"), encoding="utf-8")
    med_actions = [["advance_day", {}] for _ in range(TIERS["medium"].n_days)]
    rep_med = sp.verify_action_list_parity("medium", 3000, med_actions, arena_dir=med_dir)
    assert rep_med["arena_game"]["game_checked"] is True
    assert rep_med["arena_game"]["replay_checked"] is True

    rep_med_skip = sp.verify_action_list_parity("hard", 6, base_actions, arena_dir=med_dir)
    assert rep_med_skip["arena_game"]["present"] is True
    assert rep_med_skip["arena_game"]["checked"] is False
    assert len(rep_med_skip["arena_game"]["skipped_reasons"]) == 2

    tamper_dir = tmp_path / "tamper"
    tamper_dir.mkdir()
    (tamper_dir / "arena_game.py").write_text(
        textwrap.dedent(
            """
            from canary.env import Env

            def replay(tier: str, seed: int, actions: list) -> dict:
                env = Env(tier, int(seed))
                for t, a in actions:
                    env.call(t, a)
                v = env.verdict()
                v["score"] = round(v["score"] + 0.05, 10)
                return v
            """
        ),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError):
        sp.verify_action_list_parity("hard", 6, base_actions, arena_dir=tamper_dir)


def test_craft_final_verdict_shape_verbatim_and_tamper_guards(tmp_path: Path):
    expected_keys = {"accused", "correct", "final_day", "tool_calls", "score"}
    assert set(sp.CRAFT_FINAL_VERDICT_KEYS) == expected_keys

    for tier, seed in (("easy", 6), ("medium", 3000), ("hard", 6), ("hard", 26)):
        sol_ep, sol_actions = _cached_solver_run(tier, seed)
        env = Env(tier, seed)
        for tool, args in sol_actions:
            env.call(tool, args)
        verdict = env.verdict()
        from_env = sp.craft_final_verdict_from_env(env)
        from_ep = sp.craft_final_verdict_from_episode(sol_ep)
        assert set(from_env.keys()) == expected_keys
        assert from_env == from_ep == {
            "accused": verdict["accused"],
            "correct": verdict["correct"],
            "final_day": verdict["final_day"],
            "tool_calls": len(sol_actions),
            "score": verdict["score"],
        }
        assert sp.validate_craft_final_verdict(from_env, env=env, episode=sol_ep, tool_calls=len(sol_actions)) == from_env

        sess = sp.ArenaSession(tier, seed)
        assert json.loads(sess.final_json()) == {"error": "the episode is not over yet"}
        for tool, args in sol_actions[:-1]:
            sess.call_json(tool, json.dumps(args))
            assert json.loads(sess.final_json()) == {"error": "the episode is not over yet"}
        sess.call_json(sol_actions[-1][0], json.dumps(sol_actions[-1][1]))
        fin_json = json.loads(sess.final_json())
        rev_json = json.loads(sess.reveal_json())
        assert set(fin_json.keys()) == expected_keys
        assert set(rev_json["final"].keys()) == expected_keys
        assert fin_json == rev_json["final"] == from_env

    probe_env = Env("medium", 3000)
    innocent = next(e.id for e in probe_env._world.employees if e.id != probe_env._world.mole)
    terminal_cases = [
        [["accuse", {"employee": innocent}]],
        [["advance_day", {}] for _ in range(TIERS["medium"].n_days)],
        [["status", {}] for _ in range(TIERS["medium"].tool_call_cap)],
    ]
    for acts in terminal_cases:
        rep = sp.verify_action_list_parity("medium", 3000, acts)
        assert set(rep["final"].keys()) == expected_keys
        assert sp.validate_craft_final_verdict(rep["final"], tool_calls=len(acts)) == rep["final"]

    for tier, seed in (("medium", 6), ("medium", 26), ("hard", 6), ("hard", 26)):
        gem_dict = _load_committed_gemini_episode(tier, seed)
        gem_ep = episode_from_dict(gem_dict)
        gem_final = sp.craft_final_verdict_from_episode(gem_ep)
        gem_dict_final = sp.craft_final_verdict_from_episode(gem_dict)
        assert gem_final == gem_dict_final
        assert set(gem_final.keys()) == expected_keys

        sol_ep, _ = _cached_solver_run(tier, seed)
        hum_ep = run_episode(make_env(tier, seed, "template"), make_policy_factory("heuristic")(seed))
        duel_direct = sp.duel_end_screen_summary(tier, seed, hum_ep, gem_ep, sol_ep)
        duel_craft_final = sp.duel_end_screen_summary(
            tier,
            seed,
            sp.craft_final_verdict_from_episode(hum_ep),
            {"status": "unlocked", "final": sp.craft_final_verdict_from_episode(gem_ep)},
            {"status": "unlocked", "final": sp.craft_final_verdict_from_episode(sol_ep)},
        )
        assert duel_direct["scores"] == duel_craft_final["scores"]
        assert duel_direct["ranking"] == duel_craft_final["ranking"]
        assert duel_direct["caught_first"] == duel_craft_final["caught_first"]
        for role in ("human", "gemini", "solver"):
            assert set(duel_direct[role]["final"].keys()) == expected_keys
            assert duel_direct[role]["final"] == duel_craft_final[role]["final"]

    craft_dir = tmp_path / "craft_final_arena"
    craft_dir.mkdir()
    (craft_dir / "arena_game.py").write_text(
        textwrap.dedent(
            """
            import json
            from canary.env import Env

            class Game:
                def __init__(self, tier: str, seed: int):
                    self.env = Env(tier, int(seed))
                    self.actions = []

                def call_json(self, tool: str, args_json: str) -> str:
                    args = json.loads(args_json) if args_json else {}
                    res = self.env.call(tool, args)
                    self.actions.append([tool, args])
                    return json.dumps({"ok": res.ok, "data": res.data, "error": res.error, "done": self.env.done})

                def final_json(self) -> str:
                    if not self.env.done:
                        return json.dumps({"error": "the episode is not over yet"})
                    v = self.env.verdict()
                    return json.dumps({
                        "accused": v["accused"],
                        "correct": v["correct"],
                        "final_day": v["final_day"],
                        "tool_calls": len(self.actions),
                        "score": v["score"],
                    })

                def reveal_json(self) -> str:
                    if not self.env.done:
                        return json.dumps({"error": "the episode is not over yet"})
                    v = self.env.verdict()
                    return json.dumps({
                        "mole": self.env._world.mole,
                        "final": json.loads(self.final_json()),
                    })

            def replay(tier: str, seed: int, actions: list) -> dict:
                g = Game(tier, seed)
                for t, a in actions:
                    g.call_json(t, json.dumps(a))
                return json.loads(g.final_json())
            """
        ),
        encoding="utf-8",
    )
    sol_ep_h6, sol_acts_h6 = _cached_solver_run("hard", 6)
    rep_craft = sp.verify_action_list_parity("hard", 6, sol_acts_h6, arena_dir=craft_dir)
    assert rep_craft["arena_game"]["game_checked"] is True
    assert rep_craft["arena_game"]["replay_checked"] is True
    assert rep_craft["final"] == sp.craft_final_verdict_from_episode(sol_ep_h6)

    invalid_finals = [
        {"accused": "e01", "correct": True, "final_day": 3, "tool_calls": 10},
        {"accused": "e01", "correct": True, "final_day": 3, "tool_calls": 10, "score": 0.9, "mole": "e01"},
        {"accused": "e01", "correct": True, "final_day": 3, "tool_calls": 10, "score": 0.9, "end_reason": "accused"},
        {"accused": "e01", "correct": 1, "final_day": 3, "tool_calls": 10, "score": 0.9},
        {"accused": "e01", "correct": True, "final_day": True, "tool_calls": 10, "score": 0.9},
        {"accused": "e01", "correct": True, "final_day": 3, "tool_calls": False, "score": 0.9},
        {"accused": "e01", "correct": True, "final_day": 3, "tool_calls": 10, "score": True},
        {"accused": None, "correct": True, "final_day": 14, "tool_calls": 14, "score": 0.0},
        {"accused": None, "correct": False, "final_day": 14, "tool_calls": 14, "score": 0.25},
    ]
    for bad_payload in invalid_finals:
        with pytest.raises(AssertionError):
            sp.validate_craft_final_verdict(bad_payload)

    with pytest.raises(AssertionError):
        sp.validate_craft_final_verdict(
            {
                "accused": sol_ep_h6.accused,
                "correct": sol_ep_h6.correct,
                "final_day": sol_ep_h6.final_day,
                "tool_calls": len(sol_ep_h6.steps) + 1,
                "score": sol_ep_h6.score,
            },
            episode=sol_ep_h6,
        )


def test_zero_hidden_truth_keys_in_pre_done_step_payloads(tmp_path: Path):
    assert set(sp.HIDDEN_TRUTH_KEYS) == {"mole", "_world", "true_mole"}

    for tier, seed in (("easy", 6), ("medium", 3000), ("hard", 26)):
        sess = sp.ArenaSession(tier, seed)
        emp_res = json.loads(sess.call_json("list_employees", "{}"))
        assert sp.assert_zero_hidden_truth_pre_done(emp_res, step_index=0) is True
        first_emp = emp_res["data"]["employees"][0]["id"]
        second_emp = emp_res["data"]["employees"][1]["id"]

        msg_search = json.loads(sess.call_json("search_messages", json.dumps({"query": "a"})))
        assert sp.assert_zero_hidden_truth_pre_done(msg_search, step_index=1) is True
        msg_id = msg_search["data"]["messages"][0]["id"] if msg_search["data"]["messages"] else "msg_none"

        tool_calls = [
            ("status", {}),
            ("list_documents", {"day_from": 1, "day_to": 1}),
            ("interview", {"employee": first_emp, "topic": "workload"}),
            ("plant_canary", {"doc_title": "Audit Canary", "assignment": {first_emp: "A", second_emp: "B"}}),
            ("restrict_access", {"employee": first_emp}),
            ("unrestrict_access", {"employee": first_emp}),
            ("check_leak_feed", {}),
            ("advance_day", {}),
            ("read_access_logs", {"day_from": 1, "day_to": 1}),
            ("search_messages", {"query": "e"}),
            ("read_message", {"id": msg_id}),
            ("unknown_tool_probe", {}),
            ("interview", {"employee": "not_valid"}),
        ]
        collected_steps = [emp_res, msg_search]
        for idx, (tool_name, tool_args) in enumerate(tool_calls, start=2):
            step_out = json.loads(sess.call_json(tool_name, json.dumps(tool_args)))
            assert step_out["done"] is False
            assert sp.assert_zero_hidden_truth_pre_done(step_out, step_index=idx) is True
            collected_steps.append(step_out)

        bad_json_step = json.loads(sess.call_json("status", "{bad"))
        assert bad_json_step["done"] is False
        assert sp.assert_zero_hidden_truth_pre_done(bad_json_step) is True
        collected_steps.append(bad_json_step)

        terminal_step = json.loads(sess.call_json("accuse", json.dumps({"employee": first_emp})))
        assert terminal_step["done"] is True
        assert sp.find_hidden_truth_keys(terminal_step) == []
        collected_steps.append(terminal_step)

        scan = sp.verify_pre_done_steps_zero_hidden_truth(collected_steps)
        assert scan["pre_done_steps_checked"] == len(collected_steps) - 1
        assert scan["done_steps_skipped"] == 1

    for tier, seed in (("medium", 6), ("medium", 26), ("hard", 6), ("hard", 26)):
        gem_dict = _load_committed_gemini_episode(tier, seed)
        gem_ep = episode_from_dict(gem_dict)
        scan_ep = sp.verify_pre_done_steps_zero_hidden_truth(gem_ep.steps)
        assert scan_ep["total_steps"] == len(gem_ep.steps)
        assert scan_ep["pre_done_steps_checked"] >= len(gem_ep.steps) - 1

    leaked_pre_done_cases = [
        {"ok": True, "data": {"mole": "e04"}, "error": None, "done": False},
        {"ok": True, "data": {"nested": {"_world": {"seed": 1}}}, "error": None, "done": False},
        {"ok": True, "data": {"employees": [{"id": "e01", "true_mole": True}]}, "error": None, "done": False},
        {"day": 2, "tool": "status", "ok": True, "mole": "e04"},
        {"ok": True, "data": {"mole": "e04"}, "error": None, "done": 1},
        {"ok": True, "data": {"_world": {}}, "error": None, "done": "true"},
        {"ok": True, "data": {"true_mole": "e04"}, "error": None, "done": None},
    ]
    for leaked in leaked_pre_done_cases:
        assert len(sp.find_hidden_truth_keys(leaked)) >= 1
        with pytest.raises(AssertionError):
            sp.assert_zero_hidden_truth_pre_done(leaked)
        with pytest.raises(AssertionError):
            sp.verify_pre_done_steps_zero_hidden_truth([leaked])

    post_done_reveal = {"done": True, "mole": "e04", "true_mole": "e04", "_world": {"mole": "e04"}}
    assert sp.assert_zero_hidden_truth_pre_done(post_done_reveal) is False
    assert sp.verify_pre_done_steps_zero_hidden_truth([post_done_reveal])["done_steps_skipped"] == 1

    for leaked_key in ("mole", "_world", "true_mole"):
        leak_dir = tmp_path / f"leak_{leaked_key}"
        leak_dir.mkdir()
        (leak_dir / "arena_game.py").write_text(
            textwrap.dedent(
                f"""
                import json
                from canary.env import Env

                class Game:
                    def __init__(self, tier: str, seed: int):
                        self.env = Env(tier, int(seed))
                        self.actions = []

                    def call_json(self, tool: str, args_json: str) -> str:
                        args = json.loads(args_json) if args_json else {{}}
                        res = self.env.call(tool, args)
                        self.actions.append([tool, args])
                        payload = {{"ok": res.ok, "data": dict(res.data), "error": res.error, "done": self.env.done}}
                        if not self.env.done:
                            payload["data"][{leaked_key!r}] = "leaked_secret"
                        return json.dumps(payload)
                """
            ),
            encoding="utf-8",
        )
        with pytest.raises(AssertionError):
            sp.verify_action_list_parity("medium", 3000, [["status", {}], ["advance_day", {}]], arena_dir=leak_dir)
