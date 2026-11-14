from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from canary.gemini.provenance import (
    REQUIRED_ROLES,
    TARGET_MODEL,
    audit_provenance,
    scan_file_secrets,
)
from canary.gemini.submission_stats import (
    assert_valid_report_text,
    build_submission_stats,
    extract_cited_run_folders,
    main,
    render_submission_report_md,
    render_submission_stats_json,
    validate_report_text,
    write_submission_outputs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_RUN_KEYS = frozenset({
    "role",
    "subrole",
    "run_folder",
    "model_id",
    "commit",
    "count",
    "calls",
    "tokens_in",
    "tokens_out",
    "thinking_tokens",
    "cached_tokens",
    "cost_usd",
    "headline_metric",
})


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture()
def synthetic_six_role_root(tmp_path: Path) -> Path:
    root = tmp_path / "arena_root"

    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "biased-chatter-small" / "meta.json",
        {
            "role": "world_text",
            "subrole": "biased_chatter",
            "model_id": TARGET_MODEL,
            "commit": "1111111abcdef0",
            "n_messages": 10,
            "n_seeds": 2,
            "seeds": [10, 11],
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "usage": {"calls": 2, "in": 3400, "out": 2700, "thinking_tokens": 1700, "cost_usd": 0.034},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "carbon-v14-worlds" / "meta.json",
        {
            "role": "world_text",
            "subrole": "company_personas_chatter",
            "model_id": TARGET_MODEL,
            "commit": "2222222abcdef0",
            "n_worlds": 6,
            "n_personas_generated": 160,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "solver_mean_score": 0.654,
            "solver_episodes_verified": 6,
            "usage": {"calls": 30, "in": 40000, "out": 15000, "thinking": 20000, "cost_usd": 0.48},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "adaptive_mole" / "arena-live-carbon-med" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "live_arena_mole",
            "model_id": TARGET_MODEL,
            "commit": "3333333abcdef0",
            "seeds": [0, 1, 2],
            "mole_decisions_count": 77,
            "solver_mean": 0.4233,
            "solver_accuracy": 0.6667,
            "baseline_default_mole": {"solver_mean": 0.7333},
            "usage": {"calls": 77, "in": 61000, "out": 4900, "thinking": 5500, "cost_usd": 0.228},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "adaptive_mole" / "mole-forge-carbon" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "model_id": TARGET_MODEL,
            "commit": "4444444abcdef0",
            "n_samples": 6,
            "best_fitness": 0.37,
            "fresh_solver_accuracy": 0.95,
            "usage": {"calls": 12, "in": 2600, "out": 1100, "thinking": 1200, "cost_usd": 0.028},
        },
    )

    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "medium-0-1" / "meta.json",
        {
            "role": "investigators",
            "model_id": TARGET_MODEL,
            "commit": "5555555abcdef0",
            "tier": "medium",
            "seeds": [0, 1],
            "usage": {"calls": 160, "in": 450000, "out": 7000, "thinking": 12000, "cached_in": 400000, "cost_usd_est": 1.25},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "medium-0-1" / "episodes.jsonl",
        [
            {"tier": "medium", "seed": 0, "agent": f"gemini:{TARGET_MODEL}", "score": 0.70, "correct": True, "accused": "e05", "final_day": 8, "end_reason": "accused", "meta": {"valid": True}},
            {"tier": "medium", "seed": 1, "agent": f"gemini:{TARGET_MODEL}", "score": 0.44, "correct": True, "accused": "e02", "final_day": 13, "end_reason": "accused", "meta": {"valid": True}},
        ],
    )
    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "hard-0" / "meta.json",
        {
            "role": "investigators",
            "model_id": TARGET_MODEL,
            "commit": "6666666abcdef0",
            "tier": "hard",
            "seeds": [0],
            "usage": {"calls": 90, "in": 300000, "out": 5000, "thinking": 9000, "cached_in": 250000, "cost_usd_est": 0.85},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "hard-0" / "episodes.jsonl",
        [
            {"tier": "hard", "seed": 0, "agent": f"gemini:{TARGET_MODEL}", "score": 0.52, "correct": True, "accused": "e11", "final_day": 10, "end_reason": "accused", "meta": {"valid": True}},
        ],
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-medium" / "episodes.jsonl",
        [
            {"tier": "medium", "seed": 0, "agent": "solver", "score": 0.74, "correct": True, "accused": "e05", "final_day": 7},
            {"tier": "medium", "seed": 1, "agent": "solver", "score": 0.40, "correct": True, "accused": "e02", "final_day": 14},
        ],
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard" / "episodes.jsonl",
        [
            {"tier": "hard", "seed": 0, "agent": "solver", "score": 0.65, "correct": True, "accused": "e11", "final_day": 9},
        ],
    )

    _write_json(
        root / "results" / "gemini_roles" / "failure_analyst" / "carbon-longctx-corpus" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": TARGET_MODEL,
            "commit": "7777777abcdef0",
            "n_episodes_packed": 101,
            "source": "llm",
            "verified_quotes_pct": 100.0,
            "usage": {"calls": 2, "prompt_tokens": 237000, "out_tokens": 16000, "thinking_tokens": 14000, "cost_usd": 0.639},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "failure_analyst" / "carbon-longctx-corpus" / "report.json",
        {"clusters": [{"name": f"c{i}"} for i in range(6)]},
    )
    _write_json(
        root / "results" / "gemini_roles" / "failure_analyst" / "calibration-ev-carbon" / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "bayesian_calibration_analyst",
            "model_id": TARGET_MODEL,
            "commit": "8888888abcdef0",
            "n_episodes": 20,
            "n_calibrated_episodes": 101,
            "ece": 0.0807,
            "verified_quotes_pct": 100.0,
            "usage": {"calls": 1, "in": 83000, "out": 6600, "thinking": 10700, "cost_usd": 0.341},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "exploit_hunter" / "blackbox-swarm-carbon" / "meta.json",
        {
            "role": "exploit_hunter",
            "subrole": "blackbox_mcp_swarm",
            "model_id": TARGET_MODEL,
            "commit": "9999999abcdef0",
            "n_episodes": 6,
            "attempts": 6,
            "ledger_verified": 6,
            "exploits": 0,
            "invariant_violations": 0,
            "usage": {"calls": 123, "in": 1230000, "out": 15800, "cached": 960000, "cost_usd": 0.799},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "belief-chart-forensics-carbon" / "meta.json",
        {
            "role": "multimodal_evidence",
            "subrole": "belief_chart_forensics",
            "model_id": TARGET_MODEL,
            "commit": "aaaaaaaabcdef0",
            "n_charts_analyzed": 6,
            "visual_threshold_accuracy": 1.0,
            "usage": {"calls": 6, "in": 10800, "out": 1300, "thinking": 2000, "cost_usd": 0.055},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "access-heatmap-hard-carbon" / "meta.json",
        {
            "role": "multimodal_evidence",
            "subrole": "soc_access_vision_hard",
            "model_id": TARGET_MODEL,
            "commit": "bbbbbbbabcdef0",
            "tier": "hard",
            "n_images_read_by_model": 3,
            "usage": {"calls": 3, "in": 6450, "out": 1500, "thinking": 6200, "cost_usd": 0.09},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "access-heatmap-hard-carbon" / "results.json",
        {
            "tier": "hard",
            "n_images_read_by_model": 3,
            "metrics": {
                "top1_mole_accuracy": 1.0,
                "top1_decoy_accuracy": 1.0,
                "naive_after_hours_baseline_mole_accuracy": 0.0,
            },
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "memo-watermark-ablation-carbon" / "meta.json",
        {
            "role": "multimodal_evidence",
            "subrole": "visual_memo_blind_ablation",
            "model_id": TARGET_MODEL,
            "commit": "cccccccabcdef0",
            "tier": "medium",
            "seeds": [3, 4, 5],
            "n_episodes": 3,
            "n_images_read_by_model": 16,
            "n_canary_memos_read_by_model": 4,
            "variant_vision_accuracy": 1.0,
            "canary_variant_vision_accuracy": 1.0,
            "multimodal_mean_score": 0.6933,
            "blind_mean_score": 0.0,
            "blind_ablation_mean_score": 0.0,
            "oracle_mean_score": 0.6933,
            "multimodal_accuracy": 1.0,
            "blind_accuracy": 0.0,
            "oracle_accuracy": 1.0,
            "oracle_score_recovery_ratio": 1.0,
            "usage": {"calls": 16, "in": 30464, "out": 2085, "thinking": 1367, "cached": 0, "cost_usd": 0.095448},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "memo-watermark-ablation-carbon" / "comparison.json",
        {
            "tier": "medium",
            "seeds": [3, 4, 5],
            "n_episodes": 3,
            "n_images_read_by_model": 16,
            "summary": {
                "multimodal_carbon": {"n": 3, "mean_score": 0.6933, "accuracy": 1.0},
                "blind_no_vision": {"n": 3, "mean_score": 0.0, "accuracy": 0.0},
                "text_oracle": {"n": 3, "mean_score": 0.6933, "accuracy": 1.0},
                "multimodal_minus_blind": 0.6933,
                "oracle_score_recovery_ratio": 1.0,
                "variant_vision_accuracy": 1.0,
                "canary_variant_vision_accuracy": 1.0,
            },
            "per_seed": [
                {
                    "seed": 3,
                    "tier": "medium",
                    "multimodal_carbon": {"score": 0.60, "correct": True, "n_memos_inspected": 8, "vision_exact_matches": 8},
                    "blind_no_vision": {"score": 0.0, "correct": False},
                    "text_oracle": {"score": 0.60, "correct": True},
                },
                {
                    "seed": 4,
                    "tier": "medium",
                    "multimodal_carbon": {"score": 0.69, "correct": True, "n_memos_inspected": 5, "vision_exact_matches": 5},
                    "blind_no_vision": {"score": 0.0, "correct": False},
                    "text_oracle": {"score": 0.69, "correct": True},
                },
                {
                    "seed": 5,
                    "tier": "medium",
                    "multimodal_carbon": {"score": 0.79, "correct": True, "n_memos_inspected": 3, "vision_exact_matches": 3},
                    "blind_no_vision": {"score": 0.0, "correct": False},
                    "text_oracle": {"score": 0.79, "correct": True},
                },
            ],
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "flash-non-carbon" / "meta.json",
        {
            "role": "world_text",
            "subrole": "flash_run",
            "model_id": "gemini-3.8-flash",
            "commit": "dddddddabcdef0",
            "n_worlds": 99,
            "usage": {"calls": 10, "in": 5000, "out": 1000, "cost_usd": 0.01},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "exploit_hunter" / "smoke-ignored" / "meta.json",
        {
            "role": "exploit_hunter",
            "subrole": "smoke_swarm",
            "model_id": TARGET_MODEL,
            "commit": "eeeeeeeabcdef0",
            "attempts": 50,
            "smoke": True,
            "usage": {"calls": 5, "in": 1000, "out": 200, "cost_usd": 0.01},
        },
    )

    return root


def test_six_role_canonical_picker_supporting_runs_and_determinism(
    synthetic_six_role_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)

    stats = build_submission_stats(synthetic_six_role_root)
    stats_again = build_submission_stats(synthetic_six_role_root)
    assert stats == stats_again

    tot = stats["totals"]
    assert tot["all_roles_verified"] is True
    assert tot["n_roles_verified"] == 6
    assert tuple(tot["verified_roles"]) == REQUIRED_ROLES
    assert tot["missing_roles"] == []
    assert tot["n_verified_carbon_runs"] == 12
    assert tot["n_canonical_runs"] == 6
    assert tot["n_supporting_runs"] == 6

    roles = stats["roles"]
    assert roles["world_text"]["canonical_run"]["run_folder"] == "results/gemini_roles/world_text/carbon-v14-worlds"
    assert len(roles["world_text"]["supporting_runs"]) == 1
    assert roles["world_text"]["supporting_runs"][0]["run_folder"] == "results/gemini_roles/world_text/biased-chatter-small"

    assert roles["adaptive_mole"]["canonical_run"]["run_folder"] == "results/gemini_roles/adaptive_mole/mole-forge-carbon"
    assert [r["run_folder"] for r in roles["adaptive_mole"]["supporting_runs"]] == [
        "results/gemini_roles/adaptive_mole/arena-live-carbon-med"
    ]

    assert roles["investigators"]["canonical_run"]["run_folder"] == "data/runs/committed/v1.4/gemini-4-carbon/medium-0-1"
    assert [r["run_folder"] for r in roles["investigators"]["supporting_runs"]] == [
        "data/runs/committed/v1.4/gemini-4-carbon/hard-0"
    ]

    assert roles["failure_analyst"]["canonical_run"]["run_folder"] == "results/gemini_roles/failure_analyst/carbon-longctx-corpus"
    assert [r["run_folder"] for r in roles["failure_analyst"]["supporting_runs"]] == [
        "results/gemini_roles/failure_analyst/calibration-ev-carbon"
    ]

    assert roles["exploit_hunter"]["canonical_run"]["run_folder"] == "results/gemini_roles/exploit_hunter/blackbox-swarm-carbon"
    assert roles["exploit_hunter"]["supporting_runs"] == []

    assert (
        roles["multimodal_evidence"]["canonical_run"]["run_folder"]
        == "results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon"
    )
    assert [r["run_folder"] for r in roles["multimodal_evidence"]["supporting_runs"]] == [
        "results/gemini_roles/multimodal_evidence/belief-chart-forensics-carbon",
        "results/gemini_roles/multimodal_evidence/access-heatmap-hard-carbon",
    ]

    for role in REQUIRED_ROLES:
        canon = roles[role]["canonical_run"]
        assert canon is not None
        assert set(canon.keys()) == EXPECTED_RUN_KEYS
        assert canon["model_id"] == TARGET_MODEL
        for sr in roles[role]["supporting_runs"]:
            assert set(sr.keys()) == EXPECTED_RUN_KEYS
            assert sr["model_id"] == TARGET_MODEL

    paired = stats["paired_solver_comparison"]
    tiers = {t["tier"]: t for t in paired["tiers"]}
    assert set(tiers.keys()) == {"medium", "hard"}
    assert tiers["medium"]["n"] == 2
    assert tiers["medium"]["carbon_mean"] == pytest.approx(0.57, abs=1e-4)
    assert tiers["medium"]["solver_mean"] == pytest.approx(0.57, abs=1e-4)
    assert tiers["hard"]["n"] == 1
    assert tiers["hard"]["carbon_mean"] == pytest.approx(0.52, abs=1e-4)
    assert tiers["hard"]["solver_mean"] == pytest.approx(0.65, abs=1e-4)
    assert paired["overall"]["n"] == 3

    mm = stats["multimodal_ablation"]
    assert mm["available"] is True
    assert len(mm["runs"]) == 1
    assert mm["canonical_ablation_run"]["vision_gain"] == pytest.approx(0.6933, abs=1e-4)
    assert mm["canonical_ablation_run"]["oracle_recovery_ratio"] == pytest.approx(1.0, abs=1e-4)
    assert mm["pooled_unique_seeds"]["n_episodes"] == 3
    assert mm["pooled_unique_seeds"]["n_images_read"] == 16
    assert len(mm["soc_raster_runs"]) == 1
    assert mm["soc_raster_runs"][0]["top1_mole_accuracy"] == pytest.approx(1.0)

    md_text = render_submission_report_md(stats)
    assert md_text == render_submission_report_md(stats_again)
    assert validate_report_text(md_text, synthetic_six_role_root) == []
    assert_valid_report_text(md_text, synthetic_six_role_root)


def test_larger_multimodal_ablation_supersedes_smaller_and_deduplicates_pooled_seeds(
    synthetic_six_role_root: Path,
) -> None:
    _write_json(
        synthetic_six_role_root / "results" / "gemini_roles" / "multimodal_evidence" / "scanned-evidence-ablation-6seed" / "meta.json",
        {
            "role": "multimodal_evidence",
            "subrole": "visual_memo_blind_ablation_6seed",
            "model_id": TARGET_MODEL,
            "commit": "fffffffabcdef0",
            "tier": "medium",
            "seeds": [0, 1, 2, 3, 4, 5],
            "n_episodes": 6,
            "n_images_read_by_model": 30,
            "variant_vision_accuracy": 1.0,
            "multimodal_mean_score": 0.71,
            "blind_ablation_mean_score": 0.0,
            "oracle_mean_score": 0.71,
            "oracle_score_recovery_ratio": 1.0,
            "usage": {"calls": 30, "in": 60000, "out": 4200, "thinking": 2800, "cost_usd": 0.19},
        },
    )
    _write_json(
        synthetic_six_role_root / "results" / "gemini_roles" / "multimodal_evidence" / "scanned-evidence-ablation-6seed" / "comparison.json",
        {
            "tier": "medium",
            "seeds": [0, 1, 2, 3, 4, 5],
            "per_seed": [
                {
                    "seed": s,
                    "tier": "medium",
                    "multimodal_carbon": {"score": 0.71, "correct": True, "n_memos_inspected": 5, "vision_exact_matches": 5},
                    "blind_no_vision": {"score": 0.0, "correct": False},
                    "text_oracle": {"score": 0.71, "correct": True},
                }
                for s in range(6)
            ],
        },
    )

    stats = build_submission_stats(synthetic_six_role_root)
    mm_role = stats["roles"]["multimodal_evidence"]
    assert (
        mm_role["canonical_run"]["run_folder"]
        == "results/gemini_roles/multimodal_evidence/scanned-evidence-ablation-6seed"
    )
    assert mm_role["supporting_runs"][0]["run_folder"] == "results/gemini_roles/multimodal_evidence/memo-watermark-ablation-carbon"
    assert stats["multimodal_ablation"]["pooled_unique_seeds"]["n_episodes"] == 6


def test_cli_strict_mode_provenance_and_meta_json_guard(synthetic_six_role_root: Path) -> None:
    rc = main([
        "--root",
        str(synthetic_six_role_root),
        "--out-md",
        "docs/gemini/ROLES_REPORT.md",
        "--out-json",
        "results/gemini_roles/submission_stats.json",
        "--strict",
    ])
    assert rc == 0

    md_file = synthetic_six_role_root / "docs" / "gemini" / "ROLES_REPORT.md"
    json_file = synthetic_six_role_root / "results" / "gemini_roles" / "submission_stats.json"
    assert md_file.is_file()
    assert json_file.is_file()
    assert validate_report_text(md_file.read_text(encoding="utf-8"), synthetic_six_role_root) == []

    prov_after = audit_provenance(synthetic_six_role_root)
    assert prov_after["secret_leaks"] == []
    assert len(prov_after["verified_roles"]) == 6

    bad_rc = main([
        "--root",
        str(synthetic_six_role_root),
        "--out-json",
        "results/gemini_roles/meta.json",
    ])
    assert bad_rc == 1
    assert not (synthetic_six_role_root / "results" / "gemini_roles" / "meta.json").exists()

    with pytest.raises(ValueError, match="meta.json"):
        write_submission_outputs(synthetic_six_role_root, out_json="results/gemini_roles/meta.json")

    shutil.rmtree(synthetic_six_role_root / "results" / "gemini_roles" / "exploit_hunter")
    assert main(["--root", str(synthetic_six_role_root), "--strict"]) == 1
    assert main(["--root", str(synthetic_six_role_root)]) == 0
    assert validate_report_text(md_file.read_text(encoding="utf-8"), synthetic_six_role_root) == []


def test_script_entrypoint_keyless(synthetic_six_role_root: Path) -> None:
    env = {
        **os.environ,
        "GEMINI_API_KEY": "",
        "GOOGLE_GENERATIVE_AI_API_KEY": "",
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "build_gemini_submission_stats.py"),
            "--root",
            str(synthetic_six_role_root),
            "--strict",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert "6/6 roles verified" in proc.stdout


@pytest.mark.parametrize(
    ("bad_snippet", "expected_code"),
    [
        ("Total episodes: \u27e8N\u27e9 across tiers.", "angle_bracket_placeholder"),
        ("Metric is \u27e8pending", "angle_bracket_placeholder"),
        ("Closing bracket only \u27e9 here", "angle_bracket_placeholder"),
        ("Score: TODO fill before freeze", "todo_or_tbd_placeholder"),
        ("Cost is tbd right now", "todo_or_tbd_placeholder"),
        ("Range 300\u2013400 steps", "en_dash"),
        ("Gemini \u2014 Bayes comparison", "em_dash"),
        ("Key " + "AIza" + "SyDummyKey000000000001", "secret_leak:google_api_key"),
        ("Token " + "sk-" + "proj-DummySecret000000001", "secret_leak:sk_api_key"),
        ("OAuth " + "ya29." + "DummyOAuthToken0000001", "secret_leak:oauth_token"),
        ("GEMINI_API" + "_KEY=" + "leaked_live_secret_value", "secret_leak:env_api_key"),
        ("Run `results/gemini_roles/world_text/nonexistent-folder`", "missing_run_folder:results/gemini_roles/world_text/nonexistent-folder"),
        ("Run `data/runs/committed/v1.4/gemini-4-carbon/missing-tier`", "missing_run_folder:data/runs/committed/v1.4/gemini-4-carbon/missing-tier"),
        ("| Role | Run Folder |\n| --- | --- |\n| world_text | `custom/missing/folder` |", "missing_run_folder:custom/missing/folder"),
    ],
)
def test_validate_report_text_catches_all_violations(
    tmp_path: Path,
    bad_snippet: str,
    expected_code: str,
) -> None:
    errs = validate_report_text(bad_snippet, tmp_path)
    assert expected_code in errs
    with pytest.raises(ValueError):
        assert_valid_report_text(bad_snippet, tmp_path)


def test_validate_report_text_allows_existing_folders_and_empty_env_vars(tmp_path: Path) -> None:
    valid_dir = tmp_path / "results" / "gemini_roles" / "world_text" / "real-run"
    valid_dir.mkdir(parents=True)
    text = (
        "# Clean Report\n\n"
        "| Role | Run Folder |\n"
        "| --- | --- |\n"
        "| `world_text` | `results/gemini_roles/world_text/real-run` |\n\n"
        "```bash\n"
        "GEMINI_API_KEY= GOOGLE_GENERATIVE_AI_API_KEY= PYTHONPATH=. python scripts/build_gemini_submission_stats.py --out-json results/gemini_roles/submission_stats.json\n"
        "```\n"
    )
    assert extract_cited_run_folders(text) == ["results/gemini_roles/world_text/real-run"]
    assert validate_report_text(text, tmp_path) == []


def test_repo_root_consistency_and_committed_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)

    prov = audit_provenance(REPO_ROOT)
    stats = build_submission_stats(REPO_ROOT, provenance_report=prov)

    assert stats["provenance"]["secret_leaks_count"] == 0
    assert set(stats["totals"]["verified_roles"]) == set(prov["verified_roles"])
    assert set(stats["totals"]["missing_roles"]) == set(prov["missing_roles"])
    assert stats["totals"]["tokens_in"] == prov["totals"]["tokens_in"]
    assert stats["totals"]["tokens_out"] == prov["totals"]["tokens_out"]
    assert stats["totals"]["count"] == prov["totals"]["count"]
    assert stats["totals"]["cost_usd"] == pytest.approx(prov["totals"]["cost_usd"], abs=1e-5)

    md_text = render_submission_report_md(stats)
    json_text = render_submission_stats_json(stats)
    assert validate_report_text(md_text, REPO_ROOT) == []
    assert validate_report_text(json_text, REPO_ROOT) == []

    committed_md = REPO_ROOT / "docs" / "gemini" / "ROLES_REPORT.md"
    committed_json = REPO_ROOT / "results" / "gemini_roles" / "submission_stats.json"
    if committed_md.is_file():
        assert validate_report_text(committed_md.read_text(encoding="utf-8"), REPO_ROOT) == []
    if committed_json.is_file():
        parsed = json.loads(committed_json.read_text(encoding="utf-8"))
        assert set(parsed["roles"].keys()) == set(REQUIRED_ROLES)


def test_owned_files_have_zero_comments_dashes_or_secrets() -> None:
    targets = [
        REPO_ROOT / "canary" / "gemini" / "submission_stats.py",
        REPO_ROOT / "scripts" / "build_gemini_submission_stats.py",
        REPO_ROOT / "tests" / "test_submission_stats.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []
