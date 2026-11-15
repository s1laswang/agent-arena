from __future__ import annotations

import dataclasses
import json
import random
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.accuse import audit_episode
from canary.baselines import DoNothing, Heuristic
from canary.env import Env
from canary.eval import run_episode
from canary.solver.policy import SolverPolicy
from scripts import v16_compare_30_44 as CMP


def _make_episode_record(
    seed: int,
    variant: str,
    *,
    mode: str = "heuristic",
    accused_emp: str = "e00",
    advance_days: int = 2,
    valid_top: bool | None = True,
    valid_meta: bool | None = True,
    fake: bool = False,
) -> dict[str, Any]:
    prov = CMP.resolve_offline_provider(variant)
    env = Env("hard", seed, text_provider=prov)
    if mode == "solver":
        ep = run_episode(env, SolverPolicy("hard"))
    elif mode == "heuristic":
        ep = run_episode(env, Heuristic(seed=seed))
    elif mode == "abstain":
        ep = run_episode(env, DoNothing(seed=seed))
    elif mode == "scripted_accuse":
        env.call("list_employees", {})
        env.call("status", {})
        for d in range(advance_days):
            env.call("plant_canary", {"doc_title": f"Trap {seed} {d}", "assignment": {"e00": "A", "e01": "B"}})
            env.call("advance_day", {})
        env.call("accuse", {"employee": accused_emp})
        ep = env.result("gemini:gemini-4-carbon")
    else:
        raise ValueError(f"unknown mode {mode!r}")

    rec = dataclasses.asdict(ep)
    meta = dict(rec.get("meta") or {})
    meta["variant"] = variant
    meta["fake"] = bool(fake)
    if valid_meta is not None:
        meta["valid"] = bool(valid_meta)
    rec["meta"] = meta
    if valid_top is not None:
        rec["valid"] = bool(valid_top)
    return rec


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(r, sort_keys=True) for r in records) + "\n",
        encoding="utf-8",
    )
    return path


def test_partial_seed_overlap_and_empty_intersection(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    v1 = "v1_anchoring_authority_confirmation"
    v2 = "v2_recency_bandwagon_sycophancy"

    ctl_records = [
        _make_episode_record(30, CMP.CONTROL_VARIANT, mode="heuristic"),
        _make_episode_record(31, CMP.CONTROL_VARIANT, mode="heuristic"),
        _make_episode_record(32, CMP.CONTROL_VARIANT, mode="heuristic"),
        _make_episode_record(33, CMP.CONTROL_VARIANT, mode="heuristic"),
    ]
    v1_records = [
        _make_episode_record(31, v1, mode="scripted_accuse", accused_emp="e00"),
        _make_episode_record(33, v1, mode="abstain"),
        _make_episode_record(34, v1, mode="heuristic"),
    ]
    v2_records = [
        _make_episode_record(35, v2, mode="heuristic"),
    ]

    _write_jsonl(runs_root / "inproc" / CMP.CONTROL_VARIANT / "hard" / "episodes.jsonl", ctl_records)
    _write_jsonl(runs_root / "w1_real" / "inproc" / v1 / "hard" / "episodes.jsonl", v1_records)
    _write_jsonl(runs_root / "w2_real" / "inproc" / v2 / "hard" / "episodes.jsonl", v2_records)

    payload = CMP.compare_v16_checkpoints(runs_root=runs_root)
    assert payload["gates"]["all_passed"] is True
    assert payload["control"]["valid_seeds"] == [30, 31, 32, 33]

    rep_v1 = payload["variants"][v1]
    assert rep_v1["variant_valid_seeds"] == [31, 33, 34]
    assert rep_v1["paired_seeds"] == [31, 33]
    assert rep_v1["n_paired"] == 2
    assert rep_v1["control_only_seeds"] == [30, 32]
    assert rep_v1["variant_only_seeds"] == [34]
    assert [r["seed"] for r in rep_v1["per_seed"]] == [31, 33]
    assert rep_v1["do_nothing_mean"] == 0.0
    assert rep_v1["stop_early_mean"] == 0.0
    assert rep_v1["variant_replay_verified_count"] == 2
    assert rep_v1["control_replay_verified_count"] == 2

    rep_v2 = payload["variants"][v2]
    assert rep_v2["variant_valid_seeds"] == [35]
    assert rep_v2["paired_seeds"] == []
    assert rep_v2["n_paired"] == 0
    assert rep_v2["variant_raw_mean"] is None
    assert rep_v2["paired_delta_raw_mean"] is None
    assert rep_v2["gates"]["all_passed"] is True


def test_valid_false_error_zero_steps_and_fake_exclusion(tmp_path: Path) -> None:
    v3 = "v3_grudge_falsemem_misforward"
    ctl_path = tmp_path / "control.jsonl"
    var_path = tmp_path / "v3.jsonl"

    ctl_31_good = _make_episode_record(31, CMP.CONTROL_VARIANT, mode="heuristic")
    ctl_32_bad_meta = _make_episode_record(32, CMP.CONTROL_VARIANT, mode="heuristic", valid_top=None, valid_meta=False)
    ctl_32_bad_meta["meta"]["error"] = "429 RESOURCE_EXHAUSTED"
    ctl_33_good = _make_episode_record(33, CMP.CONTROL_VARIANT, mode="heuristic")

    var_31_fail_first = {
        "tier": "hard",
        "seed": 31,
        "agent": "gemini:gemini-4-carbon",
        "steps": [],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 0,
        "end_reason": "error",
        "valid": False,
        "meta": {"variant": v3, "valid": False, "rc": "timeout"},
    }
    var_31_retry_ok = _make_episode_record(31, v3, mode="heuristic")
    var_33_top_invalid = _make_episode_record(33, v3, mode="heuristic", valid_top=False, valid_meta=True)
    var_34_zero_steps = {
        "tier": "hard",
        "seed": 34,
        "agent": "gemini:gemini-4-carbon",
        "steps": [],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 1,
        "end_reason": "horizon",
        "meta": {"variant": v3},
    }
    var_35_fake = _make_episode_record(35, v3, mode="heuristic", fake=True)

    _write_jsonl(ctl_path, [ctl_31_good, ctl_32_bad_meta, ctl_33_good])
    _write_jsonl(var_path, [var_31_fail_first, var_31_retry_ok, var_33_top_invalid, var_34_zero_steps, var_35_fake])

    payload = CMP.compare_v16_checkpoints(
        runs_root=None,
        control_jsonl=ctl_path,
        variant_jsonl=f"{v3}={var_path}",
    )
    assert payload["control"]["valid_seeds"] == [31, 33]
    assert payload["control"]["excluded_invalid_seeds"] == [32]

    rep = payload["variants"][v3]
    assert rep["variant_valid_seeds"] == [31]
    assert rep["paired_seeds"] == [31]
    assert rep["excluded_invalid_seeds"] == [33, 34]
    assert rep["invalid_attempt_count"] == 3
    assert rep["gates"]["all_passed"] is True


def test_seed_ge_45_and_lt_30_rejection(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside allowed hard window"):
        CMP.parse_seeds_30_44("30-45")
    with pytest.raises(ValueError, match="outside allowed hard window"):
        CMP.parse_seeds_30_44("45")
    with pytest.raises(ValueError, match="outside allowed hard window"):
        CMP.parse_seeds_30_44("29,30")
    assert CMP.parse_seeds_30_44("30-32,44") == [30, 31, 32, 44]

    v5 = "v5_full9_cocktail"
    ctl_path = tmp_path / "ctl_range.jsonl"
    var_path = tmp_path / "v5_range.jsonl"

    seeds_mixed = [29, 31, 44, 45, 46, 49]
    _write_jsonl(ctl_path, [_make_episode_record(s, CMP.CONTROL_VARIANT, mode="abstain") for s in seeds_mixed])
    _write_jsonl(var_path, [_make_episode_record(s, v5, mode="abstain") for s in seeds_mixed])

    payload = CMP.compare_v16_checkpoints(
        runs_root=None,
        control_jsonl=ctl_path,
        variant_jsonl=var_path,
    )
    assert payload["control"]["valid_seeds"] == [31, 44]
    assert payload["control"]["rejected_out_of_range_seeds"] == [29, 45, 46, 49]
    rep = payload["variants"][v5]
    assert rep["variant_valid_seeds"] == [31, 44]
    assert rep["paired_seeds"] == [31, 44]
    assert rep["rejected_out_of_range_seeds"] == [29, 45, 46, 49]
    assert payload["reference_seeds_rejected_out_of_range"] == [45, 46, 47, 48, 49]
    assert payload["reference_seeds_loaded"] == list(range(30, 45))

    with pytest.raises(ValueError, match="outside allowed hard window"):
        CMP.compare_v16_checkpoints(
            runs_root=None,
            control_jsonl=ctl_path,
            variant_jsonl=var_path,
            strict_seeds=True,
        )

    rc_strict = CMP.main([
        "--control-jsonl",
        str(ctl_path),
        "--variant-jsonl",
        str(var_path),
        "--strict-seeds",
    ])
    assert rc_strict == 2


def test_luck_adjusted_math_and_replay_tamper_detection(tmp_path: Path) -> None:
    assert CMP.compute_luck_adjusted_score(None, 0.9, 0.8) == 0.0
    assert CMP.compute_luck_adjusted_score("e01", None, 0.8) == 0.0
    assert CMP.compute_luck_adjusted_score("e01", 0.8, 0.5) == pytest.approx(0.8 * 0.5 - 0.2)
    assert CMP.compute_luck_adjusted_score("e01", 1.0, 0.64) == pytest.approx(0.64)
    assert CMP.compute_luck_adjusted_score("e01", 0.0, 0.9) == pytest.approx(-1.0)

    abstain_rec = _make_episode_record(31, CMP.CONTROL_VARIANT, mode="abstain")
    abstain_ep = CMP.to_result({k: v for k, v in abstain_rec.items() if k != "valid"})
    p_abs, v_abs, la_abs = CMP.episode_posterior_and_luck(abstain_ep)
    assert p_abs is None
    assert v_abs is None
    assert la_abs == 0.0

    heur_rec = _make_episode_record(31, CMP.CONTROL_VARIANT, mode="heuristic")
    heur_ep = CMP.to_result({k: v for k, v in heur_rec.items() if k != "valid"})
    aud_heur = audit_episode(heur_ep)
    p_h, v_h, la_h = CMP.episode_posterior_and_luck(heur_ep)
    assert p_h == pytest.approx(aud_heur["p_accused"])
    assert v_h == pytest.approx(heur_ep.meta["V"])
    assert la_h == pytest.approx(float(aud_heur["p_accused"]) * float(heur_ep.meta["V"]) - (1.0 - float(aud_heur["p_accused"])))

    wrong_rec = _make_episode_record(31, "v1_anchoring_authority_confirmation", mode="scripted_accuse", accused_emp="e00", advance_days=2)
    if wrong_rec["correct"]:
        wrong_rec = _make_episode_record(31, "v1_anchoring_authority_confirmation", mode="scripted_accuse", accused_emp="e01", advance_days=2)
    assert wrong_rec["correct"] is False
    assert wrong_rec["score"] == -1.0
    true_v = float(wrong_rec["meta"]["V"])
    assert 0.0 < true_v < 1.0
    stripped_wrong = dict(wrong_rec)
    stripped_wrong["meta"] = {"variant": "v1_anchoring_authority_confirmation"}
    stored_wrong = CMP.StoredEpisode(
        seed=31,
        variant="v1_anchoring_authority_confirmation",
        score=-1.0,
        correct=False,
        accused=wrong_rec["accused"],
        final_day=wrong_rec["final_day"],
        end_reason=wrong_rec["end_reason"],
        episode=CMP.to_result({k: v for k, v in stripped_wrong.items() if k != "valid"}),
    )
    aud_wrong = CMP.audit_and_verify_episode(stored_wrong, "v1_anchoring_authority_confirmation")
    assert aud_wrong.replay_verified is True
    assert aud_wrong.v_accuse == pytest.approx(true_v)
    assert aud_wrong.p_accused is not None
    expected_wrong_luck = aud_wrong.p_accused * true_v - (1.0 - aud_wrong.p_accused)
    assert aud_wrong.luck_adj == pytest.approx(expected_wrong_luck)

    tampered = dict(heur_rec)
    tampered["score"] = 0.999999
    ctl_path = _write_jsonl(tmp_path / "ctl_ok.jsonl", [heur_rec])
    bad_path = _write_jsonl(tmp_path / "var_tampered.jsonl", [tampered])
    rc_bad = CMP.main([
        "--control-jsonl",
        str(ctl_path),
        "--variant-jsonl",
        f"v1_anchoring_authority_confirmation={bad_path}",
    ])
    assert rc_bad == 1


def test_deterministic_bootstrap_ci_ratios_and_deltas(tmp_path: Path) -> None:
    v5 = "v5_full9_cocktail"
    seeds = [31, 33, 34]
    ctl_recs = [_make_episode_record(s, CMP.CONTROL_VARIANT, mode="heuristic") for s in seeds]
    var_recs = [
        _make_episode_record(31, v5, mode="solver"),
        _make_episode_record(33, v5, mode="abstain"),
        _make_episode_record(34, v5, mode="heuristic"),
    ]
    ctl_path = _write_jsonl(tmp_path / "ctl_ci.jsonl", ctl_recs)
    var_path = _write_jsonl(tmp_path / "v5_ci.jsonl", var_recs)

    random.seed(98765)
    expected_next_global = random.Random(98765).random()

    p1 = CMP.compare_v16_checkpoints(
        runs_root=None,
        control_jsonl=ctl_path,
        variant_jsonl=var_path,
    )
    actual_next_global = random.random()
    assert actual_next_global == expected_next_global

    p2 = CMP.compare_v16_checkpoints(
        runs_root=None,
        control_jsonl=ctl_path,
        variant_jsonl=var_path,
    )
    assert p1 == p2
    assert p1["n_boot"] == 2000

    r = p1["variants"][v5]
    assert r["paired_seeds"] == [31, 33, 34]
    assert r["solver_raw_mean"] > 0.0
    assert r["solver_luck_adj_mean"] > 0.0

    assert r["variant_vs_solver_raw_ratio"] == pytest.approx(r["variant_raw_mean"] / r["solver_raw_mean"], abs=1e-5)
    assert r["control_vs_solver_raw_ratio"] == pytest.approx(r["control_raw_mean"] / r["solver_raw_mean"], abs=1e-5)
    assert r["variant_vs_solver_luck_adj_ratio"] == pytest.approx(
        r["variant_luck_adj_mean"] / r["solver_luck_adj_mean"],
        abs=1e-5,
    )
    assert r["control_vs_solver_luck_adj_ratio"] == pytest.approx(
        r["control_luck_adj_mean"] / r["solver_luck_adj_mean"],
        abs=1e-5,
    )
    assert r["paired_delta_raw_mean"] == pytest.approx(r["variant_raw_mean"] - r["control_raw_mean"], abs=1e-5)
    assert r["paired_delta_luck_adj_mean"] == pytest.approx(
        r["variant_luck_adj_mean"] - r["control_luck_adj_mean"],
        abs=1e-5,
    )

    for ci_key, pt_key in (
        ("paired_delta_raw_ci_95", "paired_delta_raw_mean"),
        ("paired_delta_luck_adj_ci_95", "paired_delta_luck_adj_mean"),
        ("variant_vs_solver_raw_ratio_ci_95", "variant_vs_solver_raw_ratio"),
        ("control_vs_solver_raw_ratio_ci_95", "control_vs_solver_raw_ratio"),
        ("variant_vs_solver_luck_adj_ratio_ci_95", "variant_vs_solver_luck_adj_ratio"),
        ("control_vs_solver_luck_adj_ratio_ci_95", "control_vs_solver_luck_adj_ratio"),
    ):
        lo, hi = r[ci_key]
        pt = r[pt_key]
        assert lo is not None and hi is not None and pt is not None
        assert lo <= pt <= hi

    assert r["do_nothing_mean"] == 0.0
    assert r["stop_early_mean"] == 0.0
    assert r["solver_calibration_diff"] == 0.0
    assert r["gates"]["all_passed"] is True


def test_cli_outputs_exported_json_discovery_and_hygiene(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    runs_root = tmp_path / "runs_export"
    v4 = "v4_triad_authority_recency_grudge"

    ctl_rec = _make_episode_record(31, CMP.CONTROL_VARIANT, mode="heuristic")
    _write_jsonl(runs_root / "inproc" / CMP.CONTROL_VARIANT / "hard" / "episodes.jsonl", [ctl_rec])

    exported_summary = {
        "variant": v4,
        "tier": "hard",
        "fake": False,
        "per_seed": [
            {
                "seed": 31,
                "gemini_score": 0.45,
                "gemini_correct": True,
                "gemini_accused": "e03",
                "gemini_final_day": 12,
                "gemini_end_reason": "accused",
                "gemini_v_accuse": 0.45,
                "gemini_p_accused": 0.9,
                "gemini_luck_adjusted": round(0.9 * 0.45 - 0.1, 6),
                "replay_verified": True,
            },
            {
                "seed": 47,
                "gemini_score": 0.6,
                "gemini_correct": True,
                "gemini_accused": "e02",
                "gemini_final_day": 10,
                "gemini_end_reason": "accused",
                "gemini_v_accuse": 0.6,
                "gemini_p_accused": 1.0,
                "gemini_luck_adjusted": 0.6,
                "replay_verified": True,
            },
        ],
    }
    exp_file = runs_root / "exported_v4.json"
    exp_file.write_text(json.dumps(exported_summary), encoding="utf-8")

    out_json = tmp_path / "out" / "report.json"
    out_md = tmp_path / "out" / "report.md"
    rc = CMP.main([
        "--runs-root",
        str(runs_root),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ])
    stdout = capsys.readouterr().out
    assert rc == 0
    assert out_json.is_file()
    assert out_md.is_file()
    assert v4 in stdout

    raw_json = out_json.read_text(encoding="utf-8")
    raw_md = out_md.read_text(encoding="utf-8")
    data = json.loads(raw_json)
    assert data["variants"][v4]["paired_seeds"] == [31]
    assert data["variants"][v4]["rejected_out_of_range_seeds"] == [47]

    for forbidden in ('"mole"', '"decoy"', '"steps"', '"transcript"', "\u2014", "\u2013"):
        assert forbidden not in raw_json
        assert forbidden not in raw_md
    assert CMP.EMP_ID_PATTERN.search(raw_md) is None


def test_live_shared_v16_runs_checkpoints(tmp_path: Path) -> None:
    live_root = Path("/tmp/fleet-momin/shared/v16_runs")
    if not live_root.is_dir():
        pytest.skip("shared v16_runs directory not present on this host")

    out_json = tmp_path / "live_compare.json"
    out_md = tmp_path / "live_compare.md"
    rc = CMP.main([
        "--runs-root",
        str(live_root),
        "--out-json",
        str(out_json),
        "--out-md",
        str(out_md),
    ])
    assert rc == 0
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["gates"]["all_passed"] is True
    assert all(30 <= s <= 44 for s in data["control"]["valid_seeds"])
    for rep in data["variants"].values():
        assert all(30 <= s <= 44 for s in rep["paired_seeds"])
        assert rep["do_nothing_mean"] == 0.0
        assert rep["stop_early_mean"] == 0.0


def test_committed_partial_v16_artifacts(tmp_path: Path) -> None:
    partial_root = ROOT / "results" / "v16_social" / "partial"
    summary_path = ROOT / "results" / "v16_social" / "partial_summary.json"
    report_path = ROOT / "docs" / "reports" / "v16_social_eval.md"

    assert partial_root.is_dir()
    assert summary_path.is_file()
    assert report_path.is_file()

    raw_summary = summary_path.read_text(encoding="utf-8")
    raw_report = report_path.read_text(encoding="utf-8")
    for forbidden in ("\u2014", "\u2013"):
        assert forbidden not in raw_summary
        assert forbidden not in raw_report
    assert CMP.EMP_ID_PATTERN.search(raw_report) is None
    for rx in CMP.KEY_PATTERNS:
        assert rx.search(raw_report) is None

    summary = json.loads(raw_summary)
    CMP.assert_clean_output(summary)
    assert summary["gap_widening_gate_met"] is False
    assert summary["sample_size_gate_met"] is False
    assert summary["control"]["valid_seeds"] == [30, 31, 32, 33]
    assert summary["variants"]["v5_full9_cocktail"]["paired_seeds"] == [30, 31, 32]
    assert (
        summary["variants"]["v5_full9_cocktail"]["variant_raw_mean"]
        > summary["variants"]["v5_full9_cocktail"]["control_raw_mean"]
    )
    assert "HIGHER" in raw_report
    assert "NOT met" in raw_report

    out_json = tmp_path / "partial_recheck.json"
    rc = CMP.main([
        "--runs-root",
        str(partial_root),
        "--n-boot",
        "200",
        "--out-json",
        str(out_json),
    ])
    assert rc == 0
    recheck = json.loads(out_json.read_text(encoding="utf-8"))
    assert recheck["gates"]["all_passed"] is True
    assert len(summary["per_variant_seed_table"]) == 10

