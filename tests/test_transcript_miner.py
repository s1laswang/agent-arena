from __future__ import annotations

import json
import tokenize
from pathlib import Path

import pytest

from canary.env import Env
from canary.forge.mutate import validate_strategy
from canary.mole.dsl import FEATURES, FRAME_SELECTORS, LEAK_SELECTORS, MoleStrategy
from canary.mole.transcript_miner import (
    approx_equal,
    main,
    mine_committed_runs,
    render_report,
    reports_agree,
    resolve_committed_root,
)

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def mined_corpus() -> dict:
    return mine_committed_runs(ROOT / "data" / "runs" / "committed")


def test_resolve_committed_root():
    expected = ROOT / "data" / "runs" / "committed"
    assert resolve_committed_root(ROOT) == expected
    assert resolve_committed_root(expected) == expected


def test_mine_committed_runs_real_corpus(mined_corpus: dict):
    cohorts = mined_corpus["cohorts"]
    expected_counts = {
        "v1.4_gemini_opencode": 60,
        "v1.4_gemini_inproc": 60,
        "v1.4_solver": 60,
        "v1.3_codex_gpt55": 22,
        "v1.3_inproc_gpt55": 17,
        "v1.3_solver": 40,
    }
    assert set(cohorts.keys()) == set(expected_counts.keys())
    for cid, exp_n in expected_counts.items():
        assert cid in cohorts
        assert cohorts[cid]["pooled"]["n_episodes"] == exp_n
        assert cohorts[cid]["accuse_md_verified"] is True
        assert cohorts[cid]["invalid_excluded_count"] == 0
        for tier_data in cohorts[cid]["tiers"].values():
            cm = tier_data["canary_metrics"]
            rb = cm["recipient_bins"]
            vc = cm["variant_counts"]
            assert rb["le_3_count"] + rb["4_to_8_count"] + rb["ge_9_count"] == cm["total_planted"]
            assert vc["v1_count"] + vc["v2_count"] + vc["v3_count"] == cm["total_planted"]

    cross = mined_corpus["cross_model_summary"]
    assert cross["frontier_episodes_total"] == 159
    assert cross["frontier_invalid_excluded_total"] == 0
    assert cross["frontier_wrong_accusations_total"] == 10
    assert cross["frontier_horizon_abstentions_total"] == 6
    assert cross["frontier_below_breakeven_gambles_total"] == 22
    assert cross["frontier_horizon_gambles_total"] == 13
    assert cross["frontier_premature_midgame_gambles_total"] == 9
    assert cross["frontier_unlisted_feed_episodes_total"] == 0
    assert cross["frontier_unlisted_feed_items_total"] == 0
    assert cross["frontier_decoy_episodes_total"] == 159
    assert cross["frontier_decoy_detected_in_messages_total"] == 150
    assert cross["frontier_decoy_accused_total"] == 0
    assert cross["frontier_decoy_restricted_total"] == 0
    assert cross["frontier_decoy_dismissal_rate"] == 1.0
    assert cross["frontier_decoy_dismissal_when_detected_rate"] == 1.0
    assert cross["wrong_with_le_1_separating_canary"] == 10
    assert cross["wrong_with_zero_separating_canary"] == 8
    assert cross["wrong_non_decoy_framed_tiebreak"] == 5
    assert cross["wrong_fp95_single_separating_canary"] == 7

    oc_hard = cohorts["v1.4_gemini_opencode"]["tiers"]["hard"]
    sol_hard = cohorts["v1.4_solver"]["tiers"]["hard"]
    cx_med = cohorts["v1.3_codex_gpt55"]["tiers"]["medium"]

    assert oc_hard["tool_budget"]["interview_mean"] > 50.0
    assert sol_hard["tool_budget"]["interview_mean"] == 0.0
    assert oc_hard["canary_metrics"]["per_day_mean"] < 1.0
    assert sol_hard["canary_metrics"]["per_day_mean"] > 1.2
    assert oc_hard["canary_metrics"]["first_canary_day_mean"] > 2.5
    assert sol_hard["canary_metrics"]["first_canary_day_mean"] == 1.0
    assert oc_hard["failure_anatomy"]["accuse_day_lag_vs_solver_mean"] > 2.0
    assert cx_med["canary_metrics"]["recipient_bins"]["le_3_share"] > 0.70
    assert oc_hard["canary_metrics"]["recipient_bins"]["le_3_share"] < 0.02


def _make_synthetic_step(t: int, day: int, tool: str, args: dict, data: dict, ok: bool = True) -> dict:
    return {
        "t": t,
        "day": day,
        "tool": tool,
        "args": args,
        "result": {"ok": ok, "data": data if ok else {}, "error": None if ok else "invalid arguments"},
    }


def test_synthetic_transcript_edge_cases_and_json_cli(tmp_path: Path, capsys):
    emps = [{"id": f"e{i:02d}", "name": f"Emp {i}", "dept": "Sales", "role": "analyst", "clearance": 2} for i in range(40)]
    frontier_steps = [
        _make_synthetic_step(0, 1, "list_employees", {}, {"employees": emps}),
        _make_synthetic_step(1, 1, "status", {}, {"day": 1, "V": 1.0, "restricted": []}),
        _make_synthetic_step(2, 1, "plant_canary", {"doc_title": "c1", "assignment": {"e01": "A", "e02": "B", "e03": "C"}}, {"canary_id": "c1"}),
        _make_synthetic_step(3, 1, "plant_canary", {"doc_title": "c1-2", "assignment": {f"e{i:02d}": ("A" if i < 5 else "B") for i in range(1, 8)}}, {"canary_id": "c1-2"}),
        _make_synthetic_step(4, 1, "plant_canary", {"doc_title": "bad", "assignment": {}}, {}, ok=False),
        _make_synthetic_step(5, 1, "advance_day", {}, {"closed_day": 1, "day": 2, "V": 0.98}),
        _make_synthetic_step(6, 2, "plant_canary", {"doc_title": "c2", "assignment": {f"e{i:02d}": "A" for i in range(10)}}, {"canary_id": "c2"}),
        _make_synthetic_step(7, 2, "search_messages", {"query": "promotion"}, {
            "messages": [{"id": "m1-0", "day": 1, "sender": "e09", "subject": "", "snippet": "Skipped for promotion again. I'm done pretending this is fine."}]
        }),
        _make_synthetic_step(8, 2, "read_access_logs", {"day_from": 1, "day_to": 1}, {
            "logs": [
                {"day": 1, "employee": "e09", "doc_id": "d1-1", "after_hours": True},
                {"day": 1, "employee": "e09", "doc_id": "d1-1", "after_hours": True},
                {"day": 1, "employee": "e09", "doc_id": "d1-1", "after_hours": True},
                {"day": 1, "employee": "e01", "doc_id": "d1-1", "after_hours": True},
                {"day": 1, "employee": "e01", "doc_id": "d1-1", "after_hours": True},
                {"day": 1, "employee": "e02", "doc_id": "d1-1", "after_hours": False},
            ]
        }),
        _make_synthetic_step(9, 2, "advance_day", {}, {"closed_day": 2, "day": 3, "V": 0.97}),
        _make_synthetic_step(10, 21, "check_leak_feed", {}, {
            "items": [
                {"surfaced_day": 3, "doc_id": "c1-2", "variant": "A"},
                {"surfaced_day": 15, "doc_id": "d14-2", "variant": None},
            ]
        }),
        _make_synthetic_step(11, 21, "accuse", {"employee": "e01"}, {"accused": "e01", "episode_over": True}),
    ]
    frontier_ep = {
        "tier": "hard",
        "seed": 0,
        "agent": "opencode:google/gemini-4-carbon",
        "steps": frontier_steps,
        "score": -1.0,
        "accused": "e01",
        "correct": False,
        "final_day": 21,
        "end_reason": "accused",
        "meta": {"valid": True},
    }
    older_dup_ep = dict(frontier_ep, score=0.75, accused="e02", correct=True, final_day=9)
    invalid_ep = dict(frontier_ep, seed=1, score=0.0, accused=None, meta={"valid": False})

    solver_steps = [
        _make_synthetic_step(0, 1, "list_employees", {}, {"employees": emps}),
        _make_synthetic_step(1, 1, "status", {}, {"day": 1, "V": 1.0, "restricted": []}),
        _make_synthetic_step(2, 8, "accuse", {"employee": "e02"}, {"accused": "e02", "episode_over": True}),
    ]
    solver_ep = {
        "tier": "hard",
        "seed": 0,
        "agent": "solver",
        "steps": solver_steps,
        "score": 0.68,
        "accused": "e02",
        "correct": True,
        "final_day": 8,
        "end_reason": "accused",
        "meta": {},
    }

    old_dir = tmp_path / "v1.4" / "opencode-gemini-4-carbon" / "hard-older"
    old_dir.mkdir(parents=True)
    (old_dir / "meta.json").write_text(
        json.dumps({"timestamp": "2026-11-14T01:00:00+0200", "tiers_version": "v1.4"}),
        encoding="utf-8",
    )
    (old_dir / "episodes.jsonl").write_text(json.dumps(older_dup_ep) + "\n", encoding="utf-8")

    f_dir = tmp_path / "v1.4" / "opencode-gemini-4-carbon" / "hard"
    f_dir.mkdir(parents=True)
    (f_dir / "meta.json").write_text(
        json.dumps({"timestamp": "2026-11-14T12:00:00+0200", "tiers_version": "v1.4"}),
        encoding="utf-8",
    )
    (f_dir / "episodes.jsonl").write_text(
        json.dumps(frontier_ep) + "\n" + json.dumps(invalid_ep) + "\n",
        encoding="utf-8",
    )

    sup_dir = tmp_path / "v1.4" / "superseded" / "old"
    sup_dir.mkdir(parents=True)
    (sup_dir / "episodes.jsonl").write_text(json.dumps(dict(frontier_ep, seed=2)) + "\n", encoding="utf-8")

    base_dir = tmp_path / "v1.4" / "reference" / "heuristic-hard"
    base_dir.mkdir(parents=True)
    (base_dir / "meta.json").write_text(json.dumps({"agent": "heuristic", "tiers_version": "v1.4"}), encoding="utf-8")
    (base_dir / "episodes.jsonl").write_text(json.dumps(dict(solver_ep, agent="heuristic")) + "\n", encoding="utf-8")

    s_dir = tmp_path / "v1.4" / "reference" / "solver-hard"
    s_dir.mkdir(parents=True)
    (s_dir / "episodes.jsonl").write_text(json.dumps(solver_ep) + "\n", encoding="utf-8")

    out = mine_committed_runs(tmp_path)
    assert out["cohorts"]["v1.4_gemini_opencode"]["invalid_excluded_count"] == 1
    oc = out["cohorts"]["v1.4_gemini_opencode"]["tiers"]["hard"]
    assert oc["n_episodes"] == 1
    assert oc["accuracy"] == 0.0
    assert oc["tool_budget"]["unlisted_feed_episodes"] == 1
    assert oc["tool_budget"]["unlisted_feed_items_total"] == 1
    cm = oc["canary_metrics"]
    assert cm["total_planted"] == 3
    assert cm["attempted_calls"] == 4
    assert cm["recipient_bins"]["le_3_count"] == 1
    assert cm["recipient_bins"]["4_to_8_count"] == 1
    assert cm["recipient_bins"]["ge_9_count"] == 1
    assert cm["variant_counts"]["v1_count"] == 1
    assert cm["variant_counts"]["v2_count"] == 1
    assert cm["variant_counts"]["v3_count"] == 1

    fa = oc["failure_anatomy"]
    assert fa["accuse_day_lag_vs_solver_mean"] == 13.0
    assert fa["decoy_detected_in_messages"] == 1
    assert fa["decoy_max_after_hours_episodes"] == 1
    assert fa["decoy_accused_count"] == 0
    assert fa["decoy_dismissal_rate"] == 1.0
    assert fa["decoy_dismissal_when_detected_rate"] == 1.0
    assert fa["fp95_single_canary_hit_wrong"] == 1
    assert fa["non_decoy_framed_tiebreak_wrong"] == 1
    assert fa["horizon_gambles"] == 1

    rc_json = main(["--runs", str(tmp_path), "--json"])
    assert rc_json == 0
    raw_json_out = capsys.readouterr().out
    parsed = json.loads(raw_json_out)
    assert parsed["cross_model_summary"]["frontier_episodes_total"] == 1
    assert parsed["cross_model_summary"]["frontier_invalid_excluded_total"] == 1

    json_file = tmp_path / "mined.json"
    json_file.write_text(raw_json_out, encoding="utf-8")
    assert main(["--runs", str(tmp_path), "--check", str(json_file)]) == 0
    capsys.readouterr()

    md_file = tmp_path / "mined.md"
    assert main(["--runs", str(tmp_path), "--out", str(md_file)]) == 0
    capsys.readouterr()
    assert main(["--runs", str(tmp_path), "--check", str(md_file)]) == 0
    capsys.readouterr()

    drifted_md = md_file.read_text(encoding="utf-8").replace("13.00d", "14.50d", 1)
    md_file.write_text(drifted_md, encoding="utf-8")
    assert main(["--runs", str(tmp_path), "--check", str(md_file)]) == 1
    capsys.readouterr()


def test_primary_v14_loader_ignores_hint_gpt55_and_ext_dirs(tmp_path: Path):
    emps = [{"id": f"e{i:02d}", "name": f"Emp {i}", "dept": "Sales", "role": "analyst", "clearance": 2} for i in range(40)]
    base_steps = [
        _make_synthetic_step(0, 1, "list_employees", {}, {"employees": emps}),
        _make_synthetic_step(1, 1, "status", {}, {"day": 1, "V": 1.0, "restricted": []}),
        _make_synthetic_step(2, 8, "accuse", {"employee": "e01"}, {"accused": "e01", "episode_over": True}),
    ]
    primary_ep = {
        "tier": "hard",
        "seed": 0,
        "agent": "opencode:google/gemini-4-carbon",
        "steps": base_steps,
        "score": 0.42,
        "accused": "e01",
        "correct": True,
        "final_day": 8,
        "end_reason": "accused",
        "meta": {"valid": True},
    }
    seed30_ep = dict(primary_ep, seed=30, score=0.91)
    solver_ep = dict(primary_ep, agent="solver", score=0.68)

    primary_dir = tmp_path / "v1.4" / "opencode-gemini-4-carbon" / "hard"
    primary_dir.mkdir(parents=True)
    (primary_dir / "meta.json").write_text(
        json.dumps({"timestamp": "2026-11-14T10:00:00+0200", "tiers_version": "v1.4"}),
        encoding="utf-8",
    )
    (primary_dir / "episodes.jsonl").write_text(
        json.dumps(primary_ep) + "\n" + json.dumps(seed30_ep) + "\n",
        encoding="utf-8",
    )

    ref_dir = tmp_path / "v1.4" / "reference" / "solver-hard"
    ref_dir.mkdir(parents=True)
    (ref_dir / "episodes.jsonl").write_text(json.dumps(solver_ep) + "\n", encoding="utf-8")

    ref_ext_dir = tmp_path / "v1.4" / "reference" / "solver-hard-seeds30to59"
    ref_ext_dir.mkdir(parents=True)
    (ref_ext_dir / "episodes.jsonl").write_text(json.dumps(dict(solver_ep, seed=34)) + "\n", encoding="utf-8")

    hint_dir = tmp_path / "v1.4" / "opencode-gemini-4-carbon-hint-gather" / "hard"
    hint_dir.mkdir(parents=True)
    (hint_dir / "meta.json").write_text(
        json.dumps({"timestamp": "2026-11-15T04:00:00+0200", "tiers_version": "v1.4"}),
        encoding="utf-8",
    )
    (hint_dir / "episodes.jsonl").write_text(
        json.dumps(dict(primary_ep, seed=0, score=0.95)) + "\n"
        + json.dumps(dict(primary_ep, seed=1, score=0.88)) + "\n",
        encoding="utf-8",
    )

    gpt55_dir = tmp_path / "v1.4" / "opencode-gpt-5.5" / "hard"
    gpt55_dir.mkdir(parents=True)
    (gpt55_dir / "meta.json").write_text(
        json.dumps({"timestamp": "2026-11-15T05:00:00+0200", "tiers_version": "v1.4"}),
        encoding="utf-8",
    )
    (gpt55_dir / "episodes.jsonl").write_text(
        json.dumps(dict(primary_ep, seed=2, agent="opencode:openai/gpt-5.5", score=0.77)) + "\n"
        + json.dumps(dict(primary_ep, seed=3, score=0.79)) + "\n",
        encoding="utf-8",
    )

    ext_dir = tmp_path / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard"
    ext_dir.mkdir(parents=True)
    (ext_dir / "meta.json").write_text(
        json.dumps({"timestamp": "2026-11-15T03:00:00+0200", "tiers_version": "v1.4"}),
        encoding="utf-8",
    )
    (ext_dir / "episodes.jsonl").write_text(
        json.dumps(dict(primary_ep, seed=4, score=0.71)) + "\n"
        + json.dumps(dict(primary_ep, seed=34, score=0.79)) + "\n",
        encoding="utf-8",
    )

    v13_dir = tmp_path / "v1.3" / "codex-gpt-5.5-full" / "hard"
    v13_dir.mkdir(parents=True)
    (v13_dir / "episodes.jsonl").write_text(
        json.dumps(dict(primary_ep, seed=0, agent="codex:gpt-5.5", score=0.61)) + "\n"
        + json.dumps(dict(primary_ep, seed=20, agent="codex:gpt-5.5", score=0.66)) + "\n",
        encoding="utf-8",
    )
    v13_hint = tmp_path / "v1.3" / "codex-gpt-5.5-hint" / "hard"
    v13_hint.mkdir(parents=True)
    (v13_hint / "episodes.jsonl").write_text(
        json.dumps(dict(primary_ep, seed=1, agent="codex:gpt-5.5", score=0.80)) + "\n",
        encoding="utf-8",
    )

    out = mine_committed_runs(tmp_path)
    oc_hard = out["cohorts"]["v1.4_gemini_opencode"]["tiers"]["hard"]
    assert oc_hard["n_episodes"] == 1
    assert oc_hard["seeds"] == [0]
    assert oc_hard["score_mean"] == 0.42

    sol_hard = out["cohorts"]["v1.4_solver"]["tiers"]["hard"]
    assert sol_hard["n_episodes"] == 1
    assert sol_hard["seeds"] == [0]

    cx_hard = out["cohorts"]["v1.3_codex_gpt55"]["tiers"]["hard"]
    assert cx_hard["n_episodes"] == 1
    assert cx_hard["seeds"] == [0]
    assert out["cross_model_summary"]["frontier_episodes_total"] == 2


def test_reports_agree_and_approx_equal():
    base = "Metric `alpha=0.500000000000` across 30 episodes (+2.52d).\n"
    within = "Metric `alpha=0.5000000000004` across 30 episodes (+2.52d).\n"
    beyond = "Metric `alpha=0.5001` across 30 episodes (+2.52d).\n"
    int_diff = "Metric `alpha=0.500000000000` across 31 episodes (+2.52d).\n"

    assert reports_agree(base, base)[0] is True
    assert reports_agree(within, base, tol=1e-9)[0] is True
    assert reports_agree(beyond, base, tol=1e-9)[0] is False
    assert reports_agree(int_diff, base, tol=1e-2)[0] is False

    assert approx_equal({"x": [1, 2.0], "ok": True}, {"x": (1, 2.0 + 1e-12), "ok": True}, tol=1e-9)
    assert not approx_equal({"ok": True}, {"ok": 1}, tol=1e-9)


def test_strategy_levers_valid_dsl_and_runnable(mined_corpus: dict):
    levers = mined_corpus["strategy_levers"]
    assert len(levers) == 5

    seen_features = set()
    seen_leaks = set()
    seen_frames = set()
    for lv in levers:
        for feat in lv["mole_view_features"]:
            assert feat in FEATURES
            seen_features.add(feat)
        sel = lv["mole_strategy_selectors"]
        assert sel["leak"] in LEAK_SELECTORS
        assert sel["frame"] in FRAME_SELECTORS
        seen_leaks.add(sel["leak"])
        seen_frames.add(sel["frame"])

        strat = MoleStrategy.from_json(lv["dsl_snippet"])
        norm = validate_strategy(lv["dsl_snippet"])
        assert isinstance(norm["rules"], list)

        env = Env("medium", 0, mole_strategy=strat)
        for _ in range(4):
            env.call("advance_day", {})
        assert env.day == 5

    assert "recent_low_recipient_docs" in seen_features
    assert {"most_recipients", "oldest", "none"} <= seen_leaks
    assert {"random_peer", "most_restricted_peer"} <= seen_frames


def test_cli_writes_deterministic_ascii_report_and_hygiene(tmp_path: Path, mined_corpus: dict, capsys):
    report_path = ROOT / "docs" / "reports" / "mole_transcript_mining.md"
    rendered = render_report(mined_corpus)
    committed = report_path.read_text(encoding="utf-8")
    assert rendered == committed
    assert "gemini-3.5-flash" not in rendered.lower()
    assert "gemini_35_flash" not in rendered.lower()
    assert all(ord(ch) < 128 for ch in rendered)
    for bad in ("\u2014", "\u2013", "\u2212"):
        assert bad not in rendered

    out_md = tmp_path / "mole_transcript_mining.md"
    rc = main(["--runs", str(ROOT / "data" / "runs" / "committed"), "--out", str(out_md)])
    assert rc == 0
    capsys.readouterr()
    assert out_md.read_text(encoding="utf-8") == committed

    rc_check = main(["--runs", str(ROOT / "data" / "runs" / "committed"), "--check", str(report_path)])
    assert rc_check == 0
    capsys.readouterr()

    for py_path in (ROOT / "canary" / "mole" / "transcript_miner.py", Path(__file__).resolve()):
        src = py_path.read_text(encoding="utf-8")
        for bad in ("\u2014", "\u2013", "\u2212"):
            assert bad not in src
        with py_path.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == []
