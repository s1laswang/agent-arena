from __future__ import annotations

import io
import json
from pathlib import Path
import re
import tokenize

import pytest

from canary.baselines import DoNothing, ObviousHeuristic
from canary.env import Env
from canary.eval import run_episode
from canary.rules import TIERS
from canary.solver.policy import SolverPolicy, accuse_value
from canary.types import Step
from scripts import skill_ladder

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = "\u2014"


def test_rung_registry_and_subclasses_match_spec() -> None:
    expected = (
        "full_solver",
        "no_ev_commit",
        "single_canary_per_day",
        "binary_canary_only",
        "no_log_interview_updates",
        "heuristic_bisection",
        "do_nothing",
    )
    assert skill_ladder.RUNG_ORDER == expected
    for name in expected[:5]:
        pol = skill_ladder.make_rung(name, seed=7)
        assert isinstance(pol, SolverPolicy)
        assert pol.name == name
    hb = skill_ladder.make_rung("heuristic_bisection", seed=7)
    assert isinstance(hb, ObviousHeuristic)
    assert hb.name == "heuristic_bisection"
    dn = skill_ladder.make_rung("do_nothing", seed=7)
    assert isinstance(dn, DoNothing)
    assert dn.name == "do_nothing"
    with pytest.raises(ValueError):
        skill_ladder.make_rung("unknown_rung")


def test_full_solver_matches_reference_solver_step_for_step() -> None:
    for tier in ("medium", "hard"):
        ref = run_episode(Env(tier, 5000), SolverPolicy())
        rung = run_episode(Env(tier, 5000), skill_ladder.make_rung("full_solver", seed=5000))
        assert [(s.tool, s.args) for s in rung.steps] == [(s.tool, s.args) for s in ref.steps]
        assert rung.score == ref.score
        assert rung.correct == ref.correct


def test_no_ev_commit_accuses_above_035_with_negative_ev_and_on_final_day() -> None:
    p_mid = {"e00": 0.36, "e01": 0.32, "e02": 0.32}
    assert accuse_value(0.36, 0.90, TIERS["medium"]) < 0.0

    ref = SolverPolicy(params="medium")
    ref.obs.employees = ["e00", "e01", "e02"]
    ref.obs.today = 4
    ref.V = 0.90
    ref.V_pre = 0.90
    ref.phase = "decide"
    ref.belief = lambda: dict(p_mid)
    ref._plan()
    assert ref.queue[0][0] != "accuse"

    abl = skill_ladder.NoEvCommitSolver(params="medium")
    abl.obs.employees = ["e00", "e01", "e02"]
    abl.obs.today = 4
    abl.V = 0.90
    abl.V_pre = 0.90
    abl.phase = "decide"
    abl.belief = lambda: dict(p_mid)
    abl._plan()
    assert abl.queue == [("accuse", {"employee": "e00"})]

    p_low = {"e00": 0.22, "e01": 0.20, "e02": 0.20, "e03": 0.19, "e04": 0.19}
    abl_last = skill_ladder.NoEvCommitSolver(params="medium")
    abl_last.obs.employees = list(p_low)
    abl_last.obs.today = TIERS["medium"].n_days
    abl_last.V = 0.50
    abl_last.V_pre = 0.50
    abl_last.phase = "decide"
    abl_last.belief = lambda: dict(p_low)
    abl_last._plan()
    assert abl_last.queue == [("accuse", {"employee": "e00"})]


def test_single_canary_per_day_caps_hard_at_one_and_matches_medium() -> None:
    ref_med = run_episode(Env("medium", 5001), skill_ladder.make_rung("full_solver", seed=5001))
    one_med = run_episode(Env("medium", 5001), skill_ladder.make_rung("single_canary_per_day", seed=5001))
    assert [(s.tool, s.args) for s in one_med.steps] == [(s.tool, s.args) for s in ref_med.steps]

    ref_hard = run_episode(Env("hard", 11), skill_ladder.make_rung("full_solver", seed=11))
    one_hard = run_episode(Env("hard", 11), skill_ladder.make_rung("single_canary_per_day", seed=11))
    ref_counts: dict[int, int] = {}
    for s in ref_hard.steps:
        if s.tool == "plant_canary" and s.result["ok"]:
            ref_counts[s.day] = ref_counts.get(s.day, 0) + 1
    one_counts: dict[int, int] = {}
    for s in one_hard.steps:
        if s.tool == "plant_canary" and s.result["ok"]:
            one_counts[s.day] = one_counts.get(s.day, 0) + 1
    assert max(ref_counts.values()) == 2
    assert one_counts and max(one_counts.values()) == 1


def test_binary_canary_only_uses_at_most_two_variants() -> None:
    saw_three_in_ref = False
    for tier, seed in (("medium", 5000), ("medium", 5002), ("hard", 5000), ("hard", 5002)):
        ref = run_episode(Env(tier, seed), skill_ladder.make_rung("full_solver", seed=seed))
        for s in ref.steps:
            if s.tool == "plant_canary" and s.result["ok"]:
                if len(set(s.args["assignment"].values())) == 3:
                    saw_three_in_ref = True
        abl = run_episode(Env(tier, seed), skill_ladder.make_rung("binary_canary_only", seed=seed))
        for s in abl.steps:
            if s.tool == "plant_canary" and s.result["ok"]:
                n_vars = len(set(s.args["assignment"].values()))
                assert 1 <= n_vars <= 2
    assert saw_three_in_ref


def test_no_log_interview_updates_ignores_logs_messages_and_interviews() -> None:
    ep = run_episode(Env("medium", 5000), skill_ladder.make_rung("no_log_interview_updates", seed=5000))
    assert all(s.tool not in ("read_access_logs", "search_messages", "interview") for s in ep.steps)

    emps = [{"id": f"e{i:02d}"} for i in range(6)]
    base_steps = [
        Step(0, 1, "list_employees", {}, {"ok": True, "data": {"employees": emps}}),
        Step(1, 1, "status", {}, {"ok": True, "data": {"day": 1, "V": 1.0, "restricted": []}}),
        Step(2, 1, "plant_canary", {"doc_title": "c", "assignment": {"e00": "A", "e01": "A", "e02": "B"}},
             {"ok": True, "data": {"canary_id": "c1"}}),
        Step(3, 1, "advance_day", {}, {"ok": True, "data": {"closed_day": 1, "day": 2, "V": 0.99}}),
        Step(4, 2, "check_leak_feed", {}, {"ok": True, "data": {"items": [{"surfaced_day": 2, "doc_id": "c1", "variant": "A"}]}}),
    ]
    extra_steps = [
        Step(5, 2, "read_access_logs", {"day_from": 1, "day_to": 1}, {
            "ok": True,
            "data": {"entries": [{"employee": "e00", "after_hours": True} for _ in range(8)]},
        }),
        Step(6, 2, "search_messages", {"query": "promotion"}, {
            "ok": True,
            "data": {"messages": [{"id": f"m{i}", "sender": "e01", "body": "promotion"} for i in range(5)]},
        }),
        Step(7, 2, "interview", {"employee": "e00", "topic": "workload"}, {
            "ok": True,
            "data": {"signal": "evasive"},
        }),
    ]

    p_clean = skill_ladder.NoLogInterviewUpdatesSolver(params="medium")
    for s in base_steps:
        p_clean._ingest(s)
    b_clean = p_clean.belief()

    p_noisy = skill_ladder.NoLogInterviewUpdatesSolver(params="medium")
    for s in base_steps + extra_steps:
        p_noisy._ingest(s)
    b_noisy = p_noisy.belief()

    for e in b_clean:
        assert abs(b_clean[e] - b_noisy[e]) < 1e-12

    p_full = skill_ladder.FullSolver(params="medium")
    for s in base_steps + extra_steps:
        p_full._ingest(s)
    b_full = p_full.belief()
    assert b_full["e01"] == 0.0
    assert b_noisy["e01"] > 0.4


def test_parse_seeds_hygiene_and_end_to_end_cli(tmp_path: Path) -> None:
    assert skill_ladder.parse_seeds("5000..5002") == [5000, 5001, 5002]
    assert skill_ladder.parse_seeds("5000-5002") == [5000, 5001, 5002]
    assert skill_ladder.parse_seeds("5000:5003") == [5000, 5001, 5002]
    for bad in ("900000", "800001", "-1", "5005-5002"):
        with pytest.raises(ValueError):
            skill_ladder.parse_seeds(bad)

    prefix = tmp_path / "skill_ladder_v1.4"
    rc = skill_ladder.main([
        "--seeds", "5000-5001",
        "--tiers", "medium,hard",
        "--workers", "1",
        "--out-prefix", str(prefix),
    ])
    assert rc == 0
    md_path = Path(f"{prefix}.md")
    json_path = Path(f"{prefix}.json")
    png_path = Path(f"{prefix}.png")
    assert md_path.exists() and json_path.exists() and png_path.exists()
    assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")

    md_text = md_path.read_text()
    json_text = json_path.read_text()
    assert EM_DASH not in md_text
    assert EM_DASH not in json_text

    doc = json.loads(json_text)
    assert doc["tiers_version"] == "v1.4"
    assert doc["n_per_tier"] == 2
    assert len(doc["rows"]) == 2 * len(skill_ladder.RUNG_ORDER)
    for r in doc["rows"]:
        if r["rung"] == "do_nothing":
            assert r["mean_score"] == 0.0
            assert r["accused_rate"] == 0.0


def test_no_code_comments_or_em_dashes_and_committed_results() -> None:
    for rel in ("scripts/skill_ladder.py", "tests/test_skill_ladder.py"):
        src = (ROOT / rel).read_text()
        assert EM_DASH not in src, rel
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [t for t in toks if t.type == tokenize.COMMENT]
        assert not comments, f"unexpected comment in {rel}: {comments[0]}"

    json_file = ROOT / "results" / "skill_ladder_v1.4.json"
    md_file = ROOT / "results" / "skill_ladder_v1.4.md"
    png_file = ROOT / "results" / "skill_ladder_v1.4.png"
    if json_file.exists():
        assert md_file.exists() and png_file.exists()
        assert png_file.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        md_txt = md_file.read_text()
        js_txt = json_file.read_text()
        assert EM_DASH not in md_txt
        assert EM_DASH not in js_txt
        doc = json.loads(js_txt)
        assert doc["tiers_version"] == "v1.4"
        assert doc["seed_start"] == 5000 and doc["seed_end"] == 5099 and doc["n_per_tier"] == 100
        assert doc["tiers"] == ["medium", "hard"]
        assert re.fullmatch(r"[0-9a-f]{40}", doc["git_sha"])
        assert doc["git_sha"][:10] in md_txt
        by_key = {(r["tier"], r["rung"]): r for r in doc["rows"]}
        assert len(by_key) == 14
        assert by_key[("medium", "no_ev_commit")]["paired_diff"] < 0
        assert by_key[("hard", "no_ev_commit")]["paired_diff"] < 0
        assert by_key[("medium", "binary_canary_only")]["paired_diff"] < 0
        assert by_key[("medium", "no_log_interview_updates")]["paired_diff"] < 0
        assert by_key[("hard", "no_log_interview_updates")]["paired_diff"] < 0
        assert by_key[("hard", "single_canary_per_day")]["max_canaries_in_a_day"] <= 1
        assert by_key[("hard", "full_solver")]["max_canaries_in_a_day"] == 2
        assert by_key[("hard", "binary_canary_only")]["max_variants_used"] <= 2
        assert by_key[("hard", "full_solver")]["max_variants_used"] == 3
        for tier in ("medium", "hard"):
            for rung in ("no_ev_commit", "binary_canary_only", "no_log_interview_updates", "heuristic_bisection", "do_nothing"):
                assert by_key[(tier, rung)]["luck_adjusted_diff"] < 0
        assert by_key[("hard", "single_canary_per_day")]["luck_adjusted_diff"] < 0
