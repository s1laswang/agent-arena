from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tokenize
from typing import Any

import pytest

from canary import rules
from canary.gemini import carbon_roles as cr

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES_CARBON_DIR = REPO_ROOT / "results" / "gemini" / "roles_carbon"
ROLES_MD_PATH = REPO_ROOT / "docs" / "gemini" / "ROLES_CARBON.md"
SUBMISSION_MD_PATH = REPO_ROOT / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md"
PITCH_MD_PATH = REPO_ROOT / "pitch" / "GEMINI_SIX_ROLES.md"
VALIDATION_MD_PATH = REPO_ROOT / "docs" / "gemini" / "validation.md"
CARBON_ROLES_PY_PATH = REPO_ROOT / "canary" / "gemini" / "carbon_roles.py"
SELF_TEST_PY_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"

PROTECTED_PATHS: tuple[str, ...] = (
    "docs/gemini/validation.md",
    "canary/rules.py",
    "canary/env.py",
    "canary/scoring.py",
    "harbor",
    "data/worlds",
    "data/runs/committed",
    "results/judge_table.md",
    "results/judge_episodes.jsonl",
)

EXPECTED_17_MM_RUNS = frozenset({
    "access-heatmap-carbon",
    "access-heatmap-hard-carbon",
    "access-heatmap-v14-high-s8to11-carbon",
    "access-heatmap-v14-low-s8to11-carbon",
    "access-heatmap-v14-sweep-carbon",
    "belief-chart-forensics-carbon",
    "carbon-trajectory-forensics",
    "carbon-trajectory-forensics-v14-expanded",
    "memo-watermark-ablation-carbon",
    "memo-watermark-hard-ablation-carbon",
    "memo-watermark-hard-seeds10to14-carbon",
    "memo-watermark-hard-seeds5to9-carbon",
    "memo-watermark-med-seeds6to11-carbon",
    "multi-image-dossier-carbon",
    "multi-image-dossier-med6to8-hard5to7-carbon",
    "multi-image-dossier-v14-expanded-carbon",
    "scanned-evidence-ablation-carbon",
})

EXPECTED_2_EH_RUNS = frozenset({
    "blackbox-swarm-carbon",
    "whitebox-swarm-carbon",
})

API_KEY_ENV_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _keyless_and_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in API_KEY_ENV_VARS:
        monkeypatch.setenv(var, "")

    def _blocked_connect(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Network access blocked in keyless carbon_roles test suite")

    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket, "create_connection", _blocked_connect)


def _sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _stage_minimal_four_other_roles(roles_root: Path) -> None:
    _write_json(
        roles_root / "world_text" / "persona-interviews-carbon" / "meta.json",
        {
            "role": "world_text",
            "subrole": "live_persona_interviews",
            "model_id": "gemini-4-carbon",
            "commit": "1111111111111111111111111111111111111111",
            "n_worlds": 6,
            "truth_leak_violations": 0,
            "fake_env": False,
            "smoke": False,
            "usage": {
                "calls": 24,
                "in": 92000,
                "out": 8400,
                "thinking": 6200,
                "cached": 48000,
                "cost_usd": 0.2415,
            },
        },
    )
    (roles_root / "world_text" / "worldtext-carbon-suite").mkdir(parents=True, exist_ok=True)
    _write_json(
        roles_root / "world_text" / "worldtext-carbon-suite" / "summary.json",
        {"consolidated": True},
    )

    _write_json(
        roles_root / "adaptive_mole" / "paired-skill-designer-carbon-hard" / "meta.json",
        {
            "role": "adaptive_mole",
            "subrole": "paired_skill_designer",
            "model_id": "gemini-4-carbon",
            "commit": "2222222222222222222222222222222222222222",
            "n_kept": 5,
            "n_llm_valid": 6,
            "eval_full_solver_mean": 0.612,
            "fake_env": False,
            "smoke": False,
            "usage": {
                "calls": 18,
                "in": 74000,
                "out": 9100,
                "thinking": 11200,
                "cached": 30000,
                "cost_usd": 0.318,
            },
        },
    )
    (roles_root / "adaptive_mole" / "carbon-vs-carbon-suite").mkdir(parents=True, exist_ok=True)
    _write_json(
        roles_root / "adaptive_mole" / "carbon-vs-carbon-suite" / "suite.json",
        {"consolidated": True},
    )

    inv_ep_dir = roles_root / "investigators" / "medium-0-1"
    _write_json(
        inv_ep_dir / "meta.json",
        {
            "role": "investigators",
            "subrole": "v14_frontier_investigator",
            "model_id": "gemini-4-carbon",
            "commit": "3333333333333333333333333333333333333333",
            "tier": "medium",
            "seeds": [0, 1],
            "mean_score": 0.665,
            "accuracy": 1.0,
            "fake_env": False,
            "smoke": False,
            "usage": {
                "calls": 42,
                "in": 310000,
                "out": 14500,
                "thinking": 28400,
                "cached": 240000,
                "cost_usd": 0.712,
            },
        },
    )
    inv_episodes = [
        {"tier": "medium", "seed": 0, "score": 0.68, "accused": "e01", "correct": True, "final_day": 8},
        {"tier": "medium", "seed": 1, "score": 0.65, "accused": "e02", "correct": True, "final_day": 9},
    ]
    (inv_ep_dir / "episodes.jsonl").write_text(
        "\n".join(json.dumps(row) for row in inv_episodes) + "\n",
        encoding="utf-8",
    )

    _write_json(
        roles_root / "investigators" / "thinking-ladder-carbon-hard0" / "meta.json",
        {
            "role": "investigators",
            "subrole": "thinking_level_ablation",
            "model_id": "gemini-4-carbon",
            "commit": "3333333333333333333333333333333333333333",
            "episode_count": 2,
            "levels_summary": {
                "low": {"mean_score": 0.41},
                "high": {"mean_score": 0.69},
            },
            "solver_baseline": {"mean_score": 0.72},
            "fake_env": False,
            "smoke": False,
            "usage": {
                "calls": 36,
                "in": 265000,
                "out": 12200,
                "thinking": 54000,
                "cached": 195000,
                "cost_usd": 0.945,
            },
        },
    )

    _write_json(
        roles_root / "failure_analyst" / "atlas-carbon" / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "long_context_failure_atlas",
            "model_id": "gemini-4-carbon",
            "commit": "4444444444444444444444444444444444444444",
            "n_episodes_packed": 48,
            "n_clusters": 5,
            "verified_quotes_pct": 100.0,
            "agreement_rate": 0.916,
            "fake_env": False,
            "smoke": False,
            "usage": {
                "calls": 4,
                "in": 420000,
                "out": 11800,
                "thinking": 19500,
                "cached": 210000,
                "cost_usd": 0.884,
            },
        },
    )
    _write_json(
        roles_root / "failure_analyst" / "index.json",
        {"note": "role index metadata file skipped by run scanner"},
    )


def test_cli_check_determinism_and_committed_inventory(tmp_path: Path) -> None:
    assert len(EXPECTED_17_MM_RUNS) == 17
    assert len(EXPECTED_2_EH_RUNS) == 2

    report_1 = cr.audit_carbon_roles(REPO_ROOT)
    report_2 = cr.audit_carbon_roles(REPO_ROOT)
    assert report_1 == report_2
    assert report_1["ok"] is True
    assert report_1["invalid_runs"] == []
    assert report_1["secret_leaks"] == []
    assert report_1["totals"]["verified_runs"] >= 19
    assert report_1["totals"]["invalid_runs"] == 0
    assert report_1["totals"]["secret_leaks_count"] == 0

    mm_runs = {r["run_name"] for r in report_1["roles"]["multimodal_evidence"]["runs"]}
    eh_runs = {r["run_name"] for r in report_1["roles"]["exploit_hunter"]["runs"]}
    assert EXPECTED_17_MM_RUNS.issubset(mm_runs)
    assert EXPECTED_2_EH_RUNS.issubset(eh_runs)

    rendered_roles_1 = cr.render_roles_carbon_md(report_1)
    rendered_roles_2 = cr.render_roles_carbon_md(report_2)
    rendered_sub_1 = cr.render_six_roles_submission_md(report_1)
    rendered_sub_2 = cr.render_six_roles_submission_md(report_2)
    rendered_pitch_1 = cr.render_pitch_six_roles_md(report_1)
    rendered_pitch_2 = cr.render_pitch_six_roles_md(report_2)
    assert rendered_roles_1 == rendered_roles_2
    assert rendered_sub_1 == rendered_sub_2
    assert rendered_pitch_1 == rendered_pitch_2

    assert ROLES_MD_PATH.read_text(encoding="utf-8") == rendered_roles_1
    assert SUBMISSION_MD_PATH.read_text(encoding="utf-8") == rendered_sub_1
    assert PITCH_MD_PATH.read_text(encoding="utf-8") == rendered_pitch_1
    assert cr.STALE_ROLES_PREFIX not in rendered_pitch_1
    assert "docs/gemini/SUBMISSION.md" in rendered_pitch_1
    assert "docs/gemini/SIX_ROLES_SUBMISSION.md" in rendered_pitch_1
    assert "docs/gemini/ROLES_CARBON.md" in rendered_pitch_1

    for run in report_1["runs"]:
        assert run["verified"] is True
        assert run["model_id"] == "gemini-4-carbon"
        assert run["commit"] and cr.COMMIT_RE.fullmatch(run["commit"]) is not None
        assert run["calls"] > 0
        assert run["tokens_in"] > 0
        assert run["tokens_out"] > 0
        assert run["cost_usd"] > 0.0
        assert run["run_folder"] in rendered_roles_1

    assert cr.main(["--root", str(REPO_ROOT), "--check"]) == 0

    env = dict(os.environ)
    for var in API_KEY_ENV_VARS:
        env[var] = ""
    env["PYTHONPATH"] = str(REPO_ROOT)
    proc = subprocess.run(
        [sys.executable, "-m", "canary.gemini.carbon_roles", "--root", str(REPO_ROOT), "--check"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok=True" in proc.stdout

    drifted_roles = tmp_path / "ROLES_CARBON_drifted.md"
    drifted_roles.write_text(rendered_roles_1 + "\ndrift\n", encoding="utf-8")
    rc_drift = cr.main(
        [
            "--root",
            str(REPO_ROOT),
            "--roles-md",
            str(drifted_roles),
            "--submission-md",
            str(SUBMISSION_MD_PATH),
            "--check",
        ]
    )
    assert rc_drift == 1

    missing_sub = tmp_path / "MISSING_SUBMISSION.md"
    rc_missing = cr.main(
        [
            "--root",
            str(REPO_ROOT),
            "--roles-md",
            str(ROLES_MD_PATH),
            "--submission-md",
            str(missing_sub),
            "--pitch-md",
            str(PITCH_MD_PATH),
            "--check",
        ]
    )
    assert rc_missing == 1

    drifted_pitch = tmp_path / "PITCH_drifted.md"
    drifted_pitch.write_text(rendered_pitch_1 + "\ndrift\n", encoding="utf-8")
    rc_pitch_drift = cr.main(
        [
            "--root",
            str(REPO_ROOT),
            "--roles-md",
            str(ROLES_MD_PATH),
            "--submission-md",
            str(SUBMISSION_MD_PATH),
            "--pitch-md",
            str(drifted_pitch),
            "--check",
        ]
    )
    assert rc_pitch_drift == 1

    missing_pitch = tmp_path / "MISSING_PITCH.md"
    rc_pitch_missing = cr.main(
        [
            "--root",
            str(REPO_ROOT),
            "--roles-md",
            str(ROLES_MD_PATH),
            "--submission-md",
            str(SUBMISSION_MD_PATH),
            "--pitch-md",
            str(missing_pitch),
            "--check",
        ]
    )
    assert rc_pitch_missing == 1


def test_six_role_strict_staged_and_hostile_rejection(tmp_path: Path) -> None:
    stage_root = tmp_path / "strict_stage"
    stage_roles = stage_root / "results" / "gemini" / "roles_carbon"
    stage_roles.mkdir(parents=True)
    (stage_root / "data").symlink_to(REPO_ROOT / "data", target_is_directory=True)

    for eh_name in EXPECTED_2_EH_RUNS:
        shutil.copytree(
            ROLES_CARBON_DIR / "exploit_hunter" / eh_name,
            stage_roles / "exploit_hunter" / eh_name,
        )
    for mm_name in (
        "scanned-evidence-ablation-carbon",
        "memo-watermark-hard-seeds10to14-carbon",
        "access-heatmap-v14-low-s8to11-carbon",
        "access-heatmap-v14-high-s8to11-carbon",
    ):
        shutil.copytree(
            ROLES_CARBON_DIR / "multimodal_evidence" / mm_name,
            stage_roles / "multimodal_evidence" / mm_name,
        )

    assert cr.main(["--root", str(stage_root), "--strict", "--audit-only"]) == 1
    assert cr.main(["--root", str(stage_root), "--audit-only"]) == 0

    _stage_minimal_four_other_roles(stage_roles)
    (stage_roles / "multimodal_evidence" / "multimodal-carbon-suite").mkdir(parents=True, exist_ok=True)
    _write_json(
        stage_roles / "multimodal_evidence" / "multimodal-carbon-suite" / "summary.json",
        {"consolidated": True},
    )

    manifest_out = stage_root / "results" / "gemini" / "roles_carbon_manifest.json"
    rc_write = cr.main(
        [
            "--root",
            str(stage_root),
            "--out-json",
            str(manifest_out),
            "--strict",
        ]
    )
    assert rc_write == 0
    assert manifest_out.is_file()

    rc_check = cr.main(["--root", str(stage_root), "--strict", "--check"])
    assert rc_check == 0

    staged_roles_md = (stage_root / "docs" / "gemini" / "ROLES_CARBON.md").read_text(encoding="utf-8")
    staged_sub_md = (stage_root / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md").read_text(encoding="utf-8")
    staged_pitch_md = (stage_root / "pitch" / "GEMINI_SIX_ROLES.md").read_text(encoding="utf-8")
    staged_manifest = json.loads(manifest_out.read_text(encoding="utf-8"))

    assert staged_manifest["strict_ok"] is True
    assert staged_manifest["verified_roles_count"] == 6
    assert staged_manifest["missing_roles"] == []
    assert set(staged_manifest["verified_roles"]) == set(cr.REQUIRED_ROLES)
    assert "STRICT 6/6 VERIFIED" in staged_roles_md
    assert "not populated on this branch" not in staged_roles_md
    assert "not populated on this branch" not in staged_sub_md
    assert "not populated on this branch" not in staged_pitch_md
    assert "Paired `gemini-4-carbon` vs `SolverPolicy` Benchmark (`v1.4`)" in staged_roles_md
    assert "thinking-ladder-carbon-hard0" in staged_sub_md
    assert "thinking-ladder-carbon-hard0" in staged_pitch_md

    for role in cr.REQUIRED_ROLES:
        _write_json(
            stage_roles / role / "index.json",
            {
                "role": role,
                "target_model": "gemini-4-carbon",
                "verified": True,
                "secret_hygiene_clean": True,
            },
        )
    idx_rep = cr.audit_carbon_roles(stage_root)
    assert idx_rep["strict_ok"] is True
    assert idx_rep["invalid_runs"] == []
    assert idx_rep["secret_leaks"] == []
    expected_skipped_idx = {f"results/gemini/roles_carbon/{r}/index.json" for r in cr.REQUIRED_ROLES}
    assert expected_skipped_idx.issubset(set(idx_rep["skipped_non_dirs"]))
    assert cr.main(["--root", str(stage_root), "--strict", "--check"]) == 0

    leaked_idx = stage_roles / "multimodal_evidence" / "index.json"
    leaked_idx.write_text(json.dumps({"leak": "AI" + "za" + "SyLeakedIndexToken1234567890"}) + "\n", encoding="utf-8")
    leak_rep = cr.audit_carbon_roles(stage_root)
    assert leak_rep["ok"] is False
    assert leak_rep["strict_ok"] is False
    assert any(lk["kind"] == "google_api_key" for lk in leak_rep["secret_leaks"])
    leaked_idx.unlink()
    assert cr.main(["--root", str(stage_root), "--strict", "--check"]) == 0

    with pytest.raises(ValueError, match="meta.json"):
        cr.sync_carbon_roles_docs(stage_root, out_json="results/gemini/meta.json")

    bad_root = tmp_path / "hostile_stage"
    bad_roles = bad_root / "results" / "gemini" / "roles_carbon"
    _write_json(
        bad_roles / "world_text" / "flash-run" / "meta.json",
        {
            "role": "world_text",
            "model_id": "gemini-3.5-flash",
            "commit": "abcdef1234567",
            "usage": {"calls": 3, "in": 1000, "out": 200, "cost_usd": 0.01},
        },
    )
    _write_json(
        bad_roles / "adaptive_mole" / "smoke-run" / "meta.json",
        {
            "role": "adaptive_mole",
            "model_id": "gemini-4-carbon",
            "commit": "abcdef1234567",
            "smoke": True,
            "fake_env": True,
            "usage": {"calls": 3, "in": 1000, "out": 200, "cost_usd": 0.01},
        },
    )
    _write_json(
        bad_roles / "investigators" / "zero-usage" / "meta.json",
        {
            "role": "investigators",
            "model_id": "gemini-4-carbon",
            "commit": "not-a-hex-sha!",
            "provider": "stub",
            "usage": {"calls": 0, "in": 0, "out": 0, "cost_usd": 0.0},
        },
    )
    bad_rep = cr.audit_carbon_roles(bad_root)
    assert bad_rep["ok"] is False
    assert bad_rep["strict_ok"] is False
    assert len(bad_rep["invalid_runs"]) == 3
    err_sets = {r["run_name"]: set(r["errors"]) for r in bad_rep["invalid_runs"]}
    assert "wrong_model:gemini-3.5-flash" in err_sets["flash-run"]
    assert {"smoke_flag", "fake_env_flag"}.issubset(err_sets["smoke-run"])
    assert {"stub_run", "zero_or_invalid_usage"}.issubset(err_sets["zero-usage"])
    assert cr.main(["--root", str(bad_root), "--audit-only"]) == 1


def test_platform_summary_within_600_chars_with_n_and_cis(tmp_path: Path) -> None:
    committed_sub_md = SUBMISSION_MD_PATH.read_text(encoding="utf-8")
    committed_pitch_md = PITCH_MD_PATH.read_text(encoding="utf-8")
    summary = cr.extract_platform_summary(committed_sub_md)
    pitch_summary = cr.extract_platform_summary(committed_pitch_md)
    assert summary == pitch_summary
    assert 100 <= len(summary) <= 600
    assert re.search(r"\bn=[1-9]\d*\b", summary) is not None
    assert "95% CI" in summary
    assert "+/-" in summary
    assert "gemini-4-carbon" in summary
    assert "Part.from_bytes" in summary
    assert HASH_CHAR not in summary
    for dash in cr.FORBIDDEN_DASHES:
        assert dash not in summary

    report = cr.audit_carbon_roles(REPO_ROOT)
    assert summary == report["platform_summary"]
    assert f"{report['totals']['calls']:,}" in summary

    large_summary = cr.build_platform_summary(
        totals={
            "verified_runs": 128,
            "verified_roles_count": 6,
            "required_roles_count": 6,
            "calls": 11180,
            "cost_usd": 88.72,
        },
        v14_paired={
            "overall": {
                "n": 70,
                "paired_diff": -0.0842,
                "diff_ci": 0.0615,
                "ratio": 0.8712,
            }
        },
        mm_summary={"pooled_ablation": None},
    )
    assert 100 <= len(large_summary) <= 600
    assert "n=70" in large_summary
    assert "95% CI" in large_summary
    assert "+/-" in large_summary
    assert "six essential roles" in large_summary
    assert tmp_path.is_dir()


def test_explicit_8_of_11_inproc_vs_3_of_11_mcp_disclosure(tmp_path: Path) -> None:
    bb_swarm = json.loads((ROLES_CARBON_DIR / "exploit_hunter" / "blackbox-swarm-carbon" / "swarm.json").read_text(encoding="utf-8"))
    wb_swarm = json.loads((ROLES_CARBON_DIR / "exploit_hunter" / "whitebox-swarm-carbon" / "swarm.json").read_text(encoding="utf-8"))
    assert len(bb_swarm["attempts"]) == 6
    assert len(wb_swarm["attempts"]) == 5

    stage_eh_root = tmp_path / "eh_pair"
    for name in ("blackbox-swarm-carbon", "whitebox-swarm-carbon"):
        shutil.copytree(
            ROLES_CARBON_DIR / "exploit_hunter" / name,
            stage_eh_root / "results" / "gemini" / "roles_carbon" / "exploit_hunter" / name,
        )
    pair_rep = cr.audit_carbon_roles(stage_eh_root)
    eh_pair = pair_rep["exploit_summary"]
    assert eh_pair["total_attempts"] == 11
    assert eh_pair["inproc_attempts"] == 8
    assert eh_pair["mcp_attempts"] == 3
    assert eh_pair["ledger_verified"] == 11
    assert eh_pair["tool_calls"] == 655
    assert eh_pair["max_pack_files"] == 104
    assert eh_pair["max_pack_tokens"] == 203463

    pair_roles_md = cr.render_roles_carbon_md(pair_rep)
    pair_sub_md = cr.render_six_roles_submission_md(pair_rep)
    pair_pitch_md = cr.render_pitch_six_roles_md(pair_rep)
    for doc_txt in (pair_roles_md, pair_sub_md, pair_pitch_md):
        assert "**8 of 11**" in doc_txt
        assert "**3 of 11**" in doc_txt
        assert "in-process against `canary.env.Env`" in doc_txt
        assert "executed over live HTTP MCP" in doc_txt
        assert "11/11 server-ledger verified" in doc_txt
        assert "dev seeds" in doc_txt

    assert "suite channels: 8/11 in-process, 3/11 live HTTP MCP" in pair_sub_md
    assert "suite channels: 8/11 in-process, 3/11 live HTTP MCP" in pair_pitch_md

    repo_rep = cr.audit_carbon_roles(REPO_ROOT)
    eh_repo = repo_rep["exploit_summary"]
    assert eh_repo["inproc_attempts"] + eh_repo["mcp_attempts"] == eh_repo["total_attempts"]
    assert eh_repo["total_attempts"] >= 11
    expected_inproc_phrase = f"**{eh_repo['inproc_attempts']} of {eh_repo['total_attempts']}**"
    expected_mcp_phrase = f"**{eh_repo['mcp_attempts']} of {eh_repo['total_attempts']}**"
    expected_channel_ratio = (
        f"suite channels: {eh_repo['inproc_attempts']}/{eh_repo['total_attempts']} in-process, "
        f"{eh_repo['mcp_attempts']}/{eh_repo['total_attempts']} live HTTP MCP"
    )
    committed_roles_md = ROLES_MD_PATH.read_text(encoding="utf-8")
    committed_sub_md = SUBMISSION_MD_PATH.read_text(encoding="utf-8")
    committed_pitch_md = PITCH_MD_PATH.read_text(encoding="utf-8")
    for doc_txt in (committed_roles_md, committed_sub_md, committed_pitch_md):
        assert expected_inproc_phrase in doc_txt
        assert expected_mcp_phrase in doc_txt
        assert "dev seeds" in doc_txt
    assert expected_channel_ratio in committed_sub_md
    assert expected_channel_ratio in committed_pitch_md


def test_validation_md_untouched_and_zero_protected_paths_touches(tmp_path: Path) -> None:
    assert VALIDATION_MD_PATH.is_file()
    val_before = VALIDATION_MD_PATH.read_bytes()
    val_sha_before = _sha256_bytes(VALIDATION_MD_PATH)
    val_text = val_before.decode("utf-8")
    assert "human labeller: Ivar" in val_text
    for row_idx in range(1, 31):
        assert f"| {row_idx} |" in val_text

    assert rules.TIERS_VERSION == "v1.4"
    v14_obj = {"tiers": {k: v.to_dict() for k, v in rules.TIERS.items()}, "known_v_mode": rules.KNOWN_V_MODE}
    v13_obj = {"tiers": {k: v.to_dict() for k, v in rules.TIERS_V13.items()}, "known_v_mode": rules.KNOWN_V_MODE}
    v14_hash = hashlib.sha256(json.dumps(v14_obj, sort_keys=True, default=list).encode()).hexdigest()[:16]
    v13_hash = hashlib.sha256(json.dumps(v13_obj, sort_keys=True, default=list).encode()).hexdigest()[:16]
    assert v14_hash == EXPECTED_V14_HASH
    assert v13_hash == EXPECTED_V13_HASH

    existing_protected = [REPO_ROOT / rel for rel in PROTECTED_PATHS if (REPO_ROOT / rel).is_file()]
    digests_before = {p: _sha256_bytes(p) for p in existing_protected}

    res = cr.sync_carbon_roles_docs(REPO_ROOT, check=True)
    assert res["ok"] is True

    out_roles = tmp_path / "ROLES_CARBON.md"
    out_sub = tmp_path / "SIX_ROLES_SUBMISSION.md"
    out_pitch = tmp_path / "GEMINI_SIX_ROLES.md"
    write_res = cr.sync_carbon_roles_docs(
        REPO_ROOT,
        roles_md=out_roles,
        submission_md=out_sub,
        pitch_md=out_pitch,
        check=False,
    )
    assert write_res["ok"] is True
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "GEMINI_SIX_ROLES.md",
        "ROLES_CARBON.md",
        "SIX_ROLES_SUBMISSION.md",
    ]

    assert _sha256_bytes(VALIDATION_MD_PATH) == val_sha_before
    for p, expected_sha in digests_before.items():
        assert _sha256_bytes(p) == expected_sha, p

    if (REPO_ROOT / ".git").exists():
        proc = subprocess.run(
            ["git", "status", "--porcelain", "--", *PROTECTED_PATHS],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        assert proc.stdout.strip() == ""

    for doc_path in (ROLES_MD_PATH, SUBMISSION_MD_PATH, PITCH_MD_PATH):
        txt = doc_path.read_text(encoding="utf-8")
        assert "docs/gemini/validation.md" in txt
        assert "Ivar" in txt


def test_zero_hash_comments_zero_unicode_dashes_and_zero_secret_leaks(tmp_path: Path) -> None:
    py_targets = (CARBON_ROLES_PY_PATH, SELF_TEST_PY_PATH)
    for py_path in py_targets:
        assert py_path.is_file(), py_path
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"literal hash char found in {py_path}"
        for dash in cr.FORBIDDEN_DASHES:
            assert dash not in src, f"forbidden unicode dash U+{ord(dash):04X} in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"comment tokens in {py_path}: {comment_tokens}"
        assert cr.scan_file_hygiene(py_path, REPO_ROOT) == []

    doc_targets = (ROLES_MD_PATH, SUBMISSION_MD_PATH, PITCH_MD_PATH)
    for doc_path in doc_targets:
        txt = doc_path.read_text(encoding="utf-8")
        assert EM_DASH not in txt, doc_path
        assert EN_DASH not in txt, doc_path
        assert cr.STALE_ROLES_PREFIX not in txt, doc_path
        for dash in cr.FORBIDDEN_DASHES:
            assert dash not in txt, doc_path
        assert cr.scan_file_hygiene(doc_path, REPO_ROOT) == []

    for fp in sorted(p for p in ROLES_CARBON_DIR.rglob("*") if p.is_file()):
        rel_parts = fp.relative_to(ROLES_CARBON_DIR).parts
        if any(part in cr.SKIP_DIRS for part in rel_parts):
            continue
        assert cr.scan_file_hygiene(fp, REPO_ROOT) == [], fp
        raw = fp.read_bytes()
        if b"\x00" not in raw:
            txt = raw.decode("utf-8", errors="replace")
            assert EM_DASH not in txt, fp
            assert EN_DASH not in txt, fp

    assert cr.sanitize_text(f"alpha{EM_DASH}beta{EN_DASH}gamma") == "alpha-beta-gamma"
    fake_gkey = "AI" + "za" + "SySyntheticLeakToken1234567890"
    fake_skey = "s" + "k-proj-" + ("Z" * 24)
    fake_oauth = "ya" + "29." + ("Q" * 24)
    assert "[redacted]" in cr.sanitize_text(fake_gkey)
    assert fake_gkey not in cr.sanitize_text(fake_gkey)

    leak_dir = tmp_path / "hygiene_cases"
    leak_dir.mkdir()
    key_file = leak_dir / "leaked.txt"
    key_file.write_text(
        f"{fake_gkey}\n{fake_skey}\n{fake_oauth}\nGEMINI_API_KEY='real_secret_token'\n",
        encoding="utf-8",
    )
    kinds = {item["kind"] for item in cr.scan_file_hygiene(key_file, leak_dir)}
    assert {"google_api_key", "sk_api_key", "oauth_token", "env_api_key"} == kinds

    env_file = leak_dir / ".env"
    env_file.write_text("X=1\n", encoding="utf-8")
    assert {i["kind"] for i in cr.scan_file_hygiene(env_file, leak_dir)} == {"tracked_env_file"}

    salt_file = leak_dir / "SALT"
    salt_file.write_bytes(b"0" * 32)
    assert {i["kind"] for i in cr.scan_file_hygiene(salt_file, leak_dir)} == {"tracked_salt_file"}

    world_file = leak_dir / "900000.world.json"
    world_file.write_text(json.dumps({"tier": "medium", "mole": "e03"}), encoding="utf-8")
    assert {i["kind"] for i in cr.scan_file_hygiene(world_file, leak_dir)} == {"world_mole_answer_key"}


def test_role_schema_fallbacks_for_worldtext_mole_investigators_and_analyst(tmp_path: Path) -> None:
    roles_root = tmp_path / "results" / "gemini" / "roles_carbon"
    _write_json(
        roles_root / "world_text" / "events-run" / "meta.json",
        {
            "role": "world_text",
            "model_id": "gemini-4-carbon",
            "commit": "aaaaaaa",
            "n_events_generated": 15,
            "truth_leak_violations": 0,
            "usage": {"calls": 15, "in": 20000, "out": 1500, "cost_usd": 0.12},
        },
    )
    _write_json(
        roles_root / "adaptive_mole" / "forge-run" / "meta.json",
        {
            "role": "adaptive_mole",
            "model_id": "gemini-4-carbon",
            "commit": "bbbbbbb",
            "n_valid_llm_children": 25,
            "best_fitness": 0.561,
            "usage": {"calls": 34, "in": 45000, "out": 3100, "cost_usd": 0.0913},
        },
    )
    _write_json(
        roles_root / "investigators" / "ladder-run" / "meta.json",
        {
            "role": "investigators",
            "model_id": "gemini-4-carbon",
            "commit": "ccccccc",
            "episode_count": 2,
            "low_score": 0.78,
            "high_score": 0.36,
            "solver_score": 0.64,
            "usage": {"calls": 163, "in": 6499263, "out": 5422, "thinking": 52968, "cached": 6200000, "cost_usd": 1.9892},
        },
    )
    _write_json(
        roles_root / "failure_analyst" / "claims-run" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": "gemini-4-carbon",
            "commit": "ddddddd",
            "n_claims": 30,
            "verified_quotes_pct": 100.0,
            "usage": {"calls": 4, "in": 110000, "out": 4200, "cost_usd": 0.4017},
        },
    )

    rep = cr.audit_carbon_roles(tmp_path)
    assert rep["ok"] is True
    assert rep["invalid_runs"] == []
    by_role = {r["role"]: r for r in rep["runs"]}
    assert by_role["world_text"]["count"] == 15
    assert "15 events, 0 truth leaks" in by_role["world_text"]["headline_metric"]
    assert by_role["adaptive_mole"]["count"] == 25
    assert "25 valid DSL children" in by_role["adaptive_mole"]["headline_metric"]
    assert "low +0.780 -> high +0.360 vs solver +0.640" in by_role["investigators"]["headline_metric"]
    assert by_role["failure_analyst"]["count"] == 30
    assert "30 claims audited, 100% verified quotes" in by_role["failure_analyst"]["headline_metric"]
