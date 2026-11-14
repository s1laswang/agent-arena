from __future__ import annotations

import io
import json
import os
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
from canary.gemini.six_roles_docs import (
    DEFAULT_MATRIX_MD,
    DEFAULT_PITCH_MD,
    DEFAULT_SUBMISSION_MD,
    SUMMARY_MAX_CHARS,
    build_platform_summary,
    build_six_roles_bundle,
    extract_platform_summary,
    main,
    sync_six_roles_docs,
    validate_six_roles_doc_text,
)
from canary.gemini.submission_stats import DEFAULT_OUT_JSON, DEFAULT_OUT_MD

REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


@pytest.fixture()
def synthetic_root(tmp_path: Path) -> Path:
    root = tmp_path / "six_roles_ws"

    _write_json(
        root / "results" / "gemini_roles" / "world_text" / "persona-interviews-carbon" / "meta.json",
        {
            "role": "world_text",
            "subrole": "persona_interviews",
            "model_id": TARGET_MODEL,
            "commit": "1111111abcdef01",
            "n_worlds": 4,
            "n_personas_generated": 80,
            "sample_count": 32,
            "truth_leak_violations": 0,
            "lint_violations": 0,
            "solver_mean_score": 0.645,
            "usage": {"calls": 32, "in": 31496, "out": 2345, "thinking": 6957, "cost_usd": 0.156},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "adaptive_mole" / "mole-forge-carbon-hard" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "mole_forge",
            "model_id": TARGET_MODEL,
            "commit": "2222222abcdef02",
            "sample_count": 24,
            "best_fitness": 0.374,
            "fresh_solver_accuracy": 0.9,
            "n_valid_llm_children": 24,
            "usage": {"calls": 8, "in": 12133, "out": 13031, "thinking": 4958, "cost_usd": 0.2042},
        },
    )

    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "medium-0-1" / "meta.json",
        {
            "role": "investigators",
            "model_id": TARGET_MODEL,
            "commit": "3333333abcdef03",
            "tier": "medium",
            "seeds": [0, 1],
            "usage": {"calls": 163, "in": 465867, "out": 7177, "thinking": 4200, "cached": 425729, "cost_usd": 1.9462},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "medium-0-1" / "episodes.jsonl",
        [
            {"tier": "medium", "seed": 0, "agent": f"gemini:{TARGET_MODEL}", "score": 0.67, "correct": True, "accused": "e05", "final_day": 10, "end_reason": "accused", "meta": {"valid": True}},
            {"tier": "medium", "seed": 1, "agent": f"gemini:{TARGET_MODEL}", "score": 0.73, "correct": True, "accused": "e02", "final_day": 7, "end_reason": "accused", "meta": {"valid": True}},
        ],
    )
    _write_json(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "hard-0" / "meta.json",
        {
            "role": "investigators",
            "model_id": TARGET_MODEL,
            "commit": "4444444abcdef04",
            "tier": "hard",
            "seeds": [0],
            "usage": {"calls": 112, "in": 436242, "out": 4481, "thinking": 0, "cached": 409096, "cost_usd": 1.4001},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "hard-0" / "episodes.jsonl",
        [
            {"tier": "hard", "seed": 0, "agent": f"gemini:{TARGET_MODEL}", "score": 0.53, "correct": True, "accused": "e11", "final_day": 11, "end_reason": "accused", "meta": {"valid": True}},
        ],
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-medium" / "episodes.jsonl",
        [
            {"tier": "medium", "seed": 0, "agent": "solver", "score": 0.74, "correct": True, "accused": "e05", "final_day": 7},
            {"tier": "medium", "seed": 1, "agent": "solver", "score": 0.39, "correct": True, "accused": "e02", "final_day": 14},
        ],
    )
    _write_jsonl(
        root / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard" / "episodes.jsonl",
        [
            {"tier": "hard", "seed": 0, "agent": "solver", "score": 0.64, "correct": True, "accused": "e11", "final_day": 9},
            {"tier": "hard", "seed": 1, "agent": "solver", "score": 0.69, "correct": True, "accused": "e08", "final_day": 7},
        ],
    )

    _write_json(
        root / "results" / "gemini_roles" / "failure_analyst" / "atlas-carbon" / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "failure_atlas_carbon",
            "model_id": TARGET_MODEL,
            "commit": "5555555abcdef05",
            "n_episodes_packed": 101,
            "n_modes": 6,
            "verified_quotes_pct": 100.0,
            "solver_agreement_rate": 0.93,
            "usage": {"calls": 2, "in": 596862, "out": 3191, "thinking": 13356, "cost_usd": 1.3592},
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "exploit_hunter" / "blackbox-swarm-carbon" / "meta.json",
        {
            "role": "exploit_hunter",
            "subrole": "blackbox_mcp_swarm",
            "model_id": TARGET_MODEL,
            "commit": "6666666abcdef06",
            "attempts": 6,
            "mcp_attempts": 2,
            "tool_calls": 363,
            "ledger_verified": 6,
            "exploits": 0,
            "invariant_violations": 0,
            "usage": {"calls": 123, "in": 1233925, "out": 15840, "cached": 961896, "cost_usd": 0.7986},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "exploit_hunter" / "blackbox-swarm-carbon" / "swarm.json",
        {
            "attempts": [
                {"id": "a0", "channel": "inproc", "exploit": False},
                {"id": "a1", "channel": "inproc", "exploit": False},
                {"id": "a2", "channel": "inproc", "exploit": False},
                {"id": "a3", "channel": "inproc", "exploit": False},
                {"id": "a0-mcp", "channel": "mcp", "exploit": False},
                {"id": "a1-mcp", "channel": "mcp", "exploit": False},
            ]
        },
    )

    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "scanned-evidence-ablation-carbon" / "meta.json",
        {
            "role": "multimodal_evidence",
            "subrole": "visual_memo_blind_ablation",
            "model_id": TARGET_MODEL,
            "commit": "7777777abcdef07",
            "tier": "medium",
            "seeds": [0, 1, 2],
            "n_episodes": 3,
            "n_images_read_by_model": 18,
            "variant_vision_accuracy": 1.0,
            "multimodal_mean_score": 0.68,
            "blind_ablation_mean_score": 0.0,
            "oracle_mean_score": 0.68,
            "oracle_score_recovery_ratio": 1.0,
            "usage": {"calls": 18, "in": 35000, "out": 2400, "thinking": 0, "cost_usd": 0.095},
        },
    )
    _write_json(
        root / "results" / "gemini_roles" / "multimodal_evidence" / "scanned-evidence-ablation-carbon" / "comparison.json",
        {
            "tier": "medium",
            "seeds": [0, 1, 2],
            "per_seed": [
                {
                    "seed": s,
                    "tier": "medium",
                    "multimodal_carbon": {"score": 0.68, "correct": True, "n_memos_inspected": 6, "vision_exact_matches": 6},
                    "blind_no_vision": {"score": 0.0, "correct": False},
                    "text_oracle": {"score": 0.68, "correct": True},
                }
                for s in range(3)
            ],
        },
    )

    return root


def test_repo_root_docs_synced_and_verified_keyless(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)

    prov = audit_provenance(REPO_ROOT)
    assert prov["verified"] is True
    assert prov["totals"]["verified_runs"] >= 72

    check_res = sync_six_roles_docs(REPO_ROOT, check=True, strict=True)
    assert check_res["ok"] is True, f"Out of sync or invalid: {check_res}"
    assert check_res["out_of_sync"] == []
    assert check_res["missing_files"] == []
    assert check_res["disk_secret_leaks"] == []
    assert main(["--root", str(REPO_ROOT), "--check", "--strict"]) == 0

    tot = check_res["totals"]
    v14 = check_res["v14_paired"]
    assert tot["n_verified_carbon_runs"] == prov["totals"]["verified_runs"]
    assert tot["tokens_in"] == prov["totals"]["tokens_in"]
    assert tot["tokens_out"] == prov["totals"]["tokens_out"]
    assert tot["cost_usd"] == pytest.approx(prov["totals"]["cost_usd"], abs=1e-5)
    assert v14["overall"]["n"] >= 30

    matrix_txt = (REPO_ROOT / DEFAULT_MATRIX_MD).read_text(encoding="utf-8")
    sub_txt = (REPO_ROOT / DEFAULT_SUBMISSION_MD).read_text(encoding="utf-8")
    pitch_txt = (REPO_ROOT / DEFAULT_PITCH_MD).read_text(encoding="utf-8")
    stats_doc = json.loads((REPO_ROOT / DEFAULT_OUT_JSON).read_text(encoding="utf-8"))

    for run_entry in prov["runs"]:
        if not run_entry["verified"]:
            continue
        assert run_entry["run_dir"] in matrix_txt
        assert run_entry["commit"] in matrix_txt
        assert f"{int(run_entry['tokens_in']):,}" in matrix_txt
        assert f"{int(run_entry['tokens_out']):,}" in matrix_txt

    for doc_txt in (sub_txt, pitch_txt):
        summary = extract_platform_summary(doc_txt)
        assert 100 <= len(summary) <= SUMMARY_MAX_CHARS
        assert f"{tot['n_verified_carbon_runs']:,}" in summary
        assert f"{tot['calls']:,}" in summary
        assert f"${tot['cost_usd']:.2f}" in summary
        assert f"n={v14['overall']['n']}" in summary
        assert "95% CI" in summary

        for role in REQUIRED_ROLES:
            canon = stats_doc["roles"][role]["canonical_run"]
            assert canon is not None
            assert canon["run_folder"] in doc_txt
            assert canon["commit"] in doc_txt
            assert canon["model_id"] in doc_txt

        low = doc_txt.lower()
        assert "in-process" in low and "mcp" in low
        assert "## 4. why gemini is essential" in low
        for pillar in ("thinking_level", "thought_signature", "cache", "1m-token long context", "part.from_bytes"):
            assert pillar in low


def test_cli_script_check_mode_subprocess_keyless() -> None:
    env = {
        **os.environ,
        "GEMINI_API_KEY": "",
        "GOOGLE_GENERATIVE_AI_API_KEY": "",
        "PYTHONPATH": str(REPO_ROOT),
    }
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sync_six_roles_docs.py"),
            "--root",
            str(REPO_ROOT),
            "--check",
            "--strict",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "six_roles_docs check OK:" in proc.stdout


def test_synthetic_sync_idempotence_drift_detection_and_new_v14_pickup(
    synthetic_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)

    pre_check = sync_six_roles_docs(synthetic_root, check=True)
    assert pre_check["ok"] is False
    assert len(pre_check["missing_files"]) == 5
    assert not (synthetic_root / DEFAULT_MATRIX_MD).exists()
    assert main(["--root", str(synthetic_root), "--check"]) == 1

    env = {
        **os.environ,
        "GEMINI_API_KEY": "",
        "GOOGLE_GENERATIVE_AI_API_KEY": "",
        "PYTHONPATH": str(REPO_ROOT),
    }
    run_sync = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "sync_six_roles_docs.py"),
            "--root",
            str(synthetic_root),
            "--strict",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=25,
    )
    assert run_sync.returncode == 0, run_sync.stderr

    tracked_rels = (
        DEFAULT_OUT_JSON,
        DEFAULT_OUT_MD,
        DEFAULT_MATRIX_MD,
        DEFAULT_SUBMISSION_MD,
        DEFAULT_PITCH_MD,
    )
    first_snapshot = {
        rel: (synthetic_root / rel).read_text(encoding="utf-8")
        for rel in tracked_rels
    }

    assert "4 in-process, 2 live MCP" in first_snapshot[DEFAULT_MATRIX_MD]
    assert "4 of 6 ran in-process" in first_snapshot[DEFAULT_SUBMISSION_MD]
    assert "2 of 6 ran over the live HTTP MCP server" in first_snapshot[DEFAULT_SUBMISSION_MD]
    assert "n=3" in extract_platform_summary(first_snapshot[DEFAULT_SUBMISSION_MD])

    sync_six_roles_docs(synthetic_root, check=False, strict=True)
    for rel in tracked_rels:
        assert (synthetic_root / rel).read_text(encoding="utf-8") == first_snapshot[rel]
    assert main(["--root", str(synthetic_root), "--check", "--strict"]) == 0

    stats_path = synthetic_root / DEFAULT_OUT_JSON
    report_path = synthetic_root / DEFAULT_OUT_MD
    stats_obj = json.loads(stats_path.read_text(encoding="utf-8"))
    stats_obj["git_head"] = "abcdef12"
    stats_path.write_text(json.dumps(stats_obj, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace("`unknown`", "`abcdef12`"),
        encoding="utf-8",
    )
    assert sync_six_roles_docs(synthetic_root, check=True, strict=True)["ok"] is True

    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace("`abcdef12`", "`99999999`"),
        encoding="utf-8",
    )
    mismatch_head = sync_six_roles_docs(synthetic_root, check=True, strict=True)
    assert mismatch_head["ok"] is False
    assert DEFAULT_OUT_MD in mismatch_head["out_of_sync"]

    sync_six_roles_docs(synthetic_root, check=False, strict=True)
    sub_path = synthetic_root / DEFAULT_SUBMISSION_MD
    drifted_text = sub_path.read_text(encoding="utf-8") + "\nextra stale line\n"
    sub_path.write_text(drifted_text, encoding="utf-8")
    drift_check = sync_six_roles_docs(synthetic_root, check=True)
    assert drift_check["ok"] is False
    assert drift_check["out_of_sync"] == [DEFAULT_SUBMISSION_MD]
    assert sub_path.read_text(encoding="utf-8") == drifted_text

    _write_json(
        synthetic_root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "hard-1" / "meta.json",
        {
            "role": "investigators",
            "model_id": TARGET_MODEL,
            "commit": "8888888abcdef08",
            "tier": "hard",
            "seeds": [1],
            "usage": {"calls": 117, "in": 429696, "out": 4864, "thinking": 0, "cached": 397176, "cost_usd": 1.534},
            "fake_env": False,
            "smoke": False,
        },
    )
    _write_jsonl(
        synthetic_root / "data" / "runs" / "committed" / "v1.4" / TARGET_MODEL / "hard-1" / "episodes.jsonl",
        [
            {"tier": "hard", "seed": 1, "agent": f"gemini:{TARGET_MODEL}", "score": 0.62, "correct": True, "accused": "e08", "final_day": 13, "end_reason": "accused", "meta": {"valid": True}},
        ],
    )

    stale_after_new_run = sync_six_roles_docs(synthetic_root, check=True)
    assert stale_after_new_run["ok"] is False
    assert set(stale_after_new_run["out_of_sync"]) == set(tracked_rels)

    resynced = sync_six_roles_docs(synthetic_root, check=False, strict=True)
    assert resynced["ok"] is True
    assert resynced["v14_paired"]["overall"]["n"] == 4
    assert sync_six_roles_docs(synthetic_root, check=True, strict=True)["ok"] is True
    new_matrix = (synthetic_root / DEFAULT_MATRIX_MD).read_text(encoding="utf-8")
    assert "data/runs/committed/v1.4/gemini-4-carbon/hard-1" in new_matrix
    assert "8888888abcdef08" in new_matrix
    assert "n=4" in extract_platform_summary((synthetic_root / DEFAULT_SUBMISSION_MD).read_text(encoding="utf-8"))


def test_platform_summary_char_bound_and_validator_guards(synthetic_root: Path) -> None:
    huge_summary = build_platform_summary(
        {"n_verified_carbon_runs": 9999, "calls": 9999999, "cost_usd": 99999.99},
        {"overall": {"n": 9999, "ratio": 1.0234, "paired_diff": -0.1234, "diff_ci": 0.2345}},
    )
    assert 100 <= len(huge_summary) <= SUMMARY_MAX_CHARS

    bundle = build_six_roles_bundle(synthetic_root)
    good_sub = bundle["rendered"][DEFAULT_SUBMISSION_MD]
    assert validate_six_roles_doc_text(good_sub, synthetic_root, kind="submission", prov=bundle["provenance"]) == []

    bad_sub = good_sub + "\nPlaceholder <insert_metric> and \u2014 dash\n"
    errs = validate_six_roles_doc_text(bad_sub, synthetic_root, kind="submission", prov=bundle["provenance"])
    assert "ascii_angle_placeholder_found" in errs
    assert "em_dash" in errs


def test_owned_source_files_have_zero_comments_dashes_angles_or_secrets() -> None:
    targets = [
        REPO_ROOT / "canary" / "gemini" / "six_roles_docs.py",
        REPO_ROOT / "scripts" / "sync_six_roles_docs.py",
        REPO_ROOT / "tests" / "test_six_roles_docs_sync.py",
    ]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        assert "\u2014" not in text
        assert "\u2013" not in text
        assert "\u27e8" not in text
        assert "\u27e9" not in text
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"Found Python comments in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []
