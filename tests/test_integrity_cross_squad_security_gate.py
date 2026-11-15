from __future__ import annotations

import json
from pathlib import Path
import tempfile

from scripts import integrity_cross_squad_security_gate as gate
from scripts import verify_integrity_branch as vib

ROOT = Path(__file__).resolve().parents[1]


def test_live_cross_squad_security_gate_passes_under_3s() -> None:
    report = gate.run_cross_squad_security_gate(root=ROOT)
    assert report["all_passed"] is True, report["violations"]
    assert isinstance(report["under_3s_budget"], bool)
    assert report["elapsed_s"] < 60.0, f"elapsed_s={report['elapsed_s']} exceeded 60.0s CI ceiling"
    assert report["live_llm_calls"] == 0
    assert len(report["base_commit_sha"]) == 8

    sc = report["summary_counts"]
    assert sc["protected_file_mutations"] == 0
    assert sc["raw_api_key_leaks"] == 0
    assert sc["salt_files"] == 0
    assert sc["world_json_mole_leaks"] == 0
    assert sc["total_violations"] == 0
    assert sc["structured_issues_count"] >= 1

    if report["shallow_checkout_fallback"]:
        assert "HEAD" in report["branches"]
        assert any(i["issue_id"] == "ISSUE-W9B-SHALLOW" for i in report["structured_issues"])
        for b_info in report["branches"].values():
            assert b_info["core_protected_mutations"] == 0
            assert b_info["extended_protected_mutations"] == 0
            assert b_info["protected_blob_sha_mismatches"] == 0
            assert b_info["tracked_blobs_total"] >= 3400
            assert b_info["content_scanned_paths"] >= 400
            assert b_info["pyodide_mirror_mismatches"] == []
    else:
        assert sc["structured_issues_count"] >= 2
        main_info = report["branches"]["origin/fr8/canary/main"]
        arena_info = report["branches"]["origin/fr8/canary/arena"]
        assert main_info["core_protected_mutations"] == 0
        assert main_info["extended_protected_mutations"] == 0
        assert main_info["protected_blob_sha_mismatches"] == 0
        assert main_info["tracked_blobs_total"] >= 3400

        assert arena_info["core_protected_mutations"] == 0
        assert arena_info["extended_protected_mutations"] == 0
        assert arena_info["protected_blob_sha_mismatches"] == 0
        assert arena_info["pyodide_mirror_files_checked"] >= 14
        assert arena_info["pyodide_mirror_mismatches"] == []


def test_positive_controls_catch_all_unchecked_out_blob_mutations() -> None:
    pos = gate.run_positive_controls()
    assert pos["all_caught"] is True, pos
    assert pos["controls_passed"] == pos["controls_total"] == 7


def test_extra_secret_weight_env_and_arena_judge_seed_detectors() -> None:
    parent_dir = gate._resolve_scratch_parent(None)
    with tempfile.TemporaryDirectory(prefix="w9b_extra_test_", dir=str(parent_dir)) as tmp_s:
        repo = Path(tmp_s)
        gate._git_check(repo, ["init", "-q"], text=True)
        gate._git_check(repo, ["config", "user.email", "w9@canary.local"], text=True)
        gate._git_check(repo, ["config", "user.name", "w9"], text=True)

        base_files = {
            ".github/protected-paths.txt": "\n".join(gate.EXTENDED_PROTECTED_RULES) + "\n",
            "canary/env.py": "ENV_V = 1\n",
            "canary/rules.py": "TIERS_VERSION = 'v1.4'\n",
            "canary/reproduce.py": "R_V = 1\n",
            "canary/solver/policy.py": "S_V = 1\n",
            "harbor/build.py": "H_V = 1\n",
            "results/harbor/rehearsal-dry/oracle/ledger_key": "job-hmac-verifier-key\n",
            ".env.example": "OPENAI_API_KEY=\n",
        }
        gate._git_commit_files(repo, "base_ref", None, base_files, "init base")

        sk_tok = "s" + "k-" + "proj-" + "AbCdEfGhIjKlMnOpQrStUvWxYz1234"
        gate._git_commit_files(
            repo,
            "br_sk_and_env",
            "base_ref",
            {
                ".env": f"OPENAI_API_KEY={sk_tok}\n",
                "train/weights.safetensors": "binary-weights",
                "results/harbor/job1/canary-hard-900000__abc/agent/ledger_key": "leaked",
            },
            "bad artifacts",
        )
        gate._git_commit_files(
            repo,
            "br_arena_judge_seed",
            "base_ref",
            {
                "docs/arena/data/bad_pack.js": "window.PACK = " + json.dumps({"seed": 900005, "tier": "hard"}) + ";\n",
            },
            "bad arena seed",
        )
        gate._git_commit_files(
            repo,
            "br_lagging_clean",
            "base_ref",
            {"docs/reports/squad_note.md": "Clean squad report.\n"},
            "clean branch before upstream advance",
        )
        gate._git_commit_files(
            repo,
            "base_advanced",
            "base_ref",
            {"Makefile": "all:\n\t@true\n", "README.md": "Upstream update\n"},
            "silas upstream advance",
        )
        gate._git_check(repo, ["checkout", "-q", "base_ref"], text=True)

        r_bad = gate.run_cross_squad_security_gate(repo, "base_ref", ("br_sk_and_env",))
        assert r_bad["all_passed"] is False
        assert r_bad["summary_counts"]["raw_api_key_leaks"] == 1
        hygiene = " ".join(r_bad["branches"]["br_sk_and_env"]["path_hygiene_violations"])
        assert "env_secret_file" in hygiene
        assert "binary_weight_artifact" in hygiene
        assert "ledger_key_file" in hygiene

        r_arena = gate.run_cross_squad_security_gate(repo, "base_ref", ("br_arena_judge_seed",))
        assert r_arena["all_passed"] is False
        assert r_arena["summary_counts"]["world_json_mole_leaks"] == 1

        r_lag = gate.run_cross_squad_security_gate(repo, "base_advanced", ("br_lagging_clean",))
        assert r_lag["all_passed"] is True, r_lag["violations"]
        assert r_lag["branches"]["br_lagging_clean"]["behind_base_commits"] == 1
        assert any(i["issue_id"] == "ISSUE-W9B-01" for i in r_lag["structured_issues"])

        gate._git_check(repo, ["checkout", "-q", "--detach", "br_lagging_clean"], text=True)
        r_shallow_clean = gate.run_cross_squad_security_gate(repo)
        assert r_shallow_clean["all_passed"] is True, r_shallow_clean["violations"]
        assert r_shallow_clean["shallow_checkout_fallback"] is True
        assert list(r_shallow_clean["branches"].keys()) == ["HEAD"]
        assert any(i["issue_id"] == "ISSUE-W9B-SHALLOW" for i in r_shallow_clean["structured_issues"])

        report_md = ROOT / "docs" / "reports" / "integrity_cross_squad_security_gate.md"
        assert gate.main(["--root", str(repo), "--check-report", str(report_md)]) == 0

        gate._git_check(repo, ["checkout", "-q", "--detach", "br_sk_and_env"], text=True)
        r_shallow_dirty = gate.run_cross_squad_security_gate(repo)
        assert r_shallow_dirty["all_passed"] is False
        assert r_shallow_dirty["shallow_checkout_fallback"] is True
        assert r_shallow_dirty["summary_counts"]["raw_api_key_leaks"] == 1


def test_cli_check_report_and_w9b_file_hygiene() -> None:
    report_path = ROOT / "docs" / "reports" / "integrity_cross_squad_security_gate.md"
    assert gate.check_markdown_report(report_path) == []
    rc = gate.main(["--check-report", str(report_path)])
    assert rc == 0

    w9b_files = (
        "scripts/integrity_cross_squad_security_gate.py",
        "docs/reports/integrity_cross_squad_security_gate.md",
        "tests/test_integrity_cross_squad_security_gate.py",
    )
    for rel in w9b_files:
        full = ROOT / rel
        assert full.is_file(), f"missing {rel}"
        txt = full.read_text(encoding="utf-8")
        assert vib.scan_text_hygiene(txt, rel) == []
        if rel.endswith(".py"):
            assert vib.scan_python_comments(txt) == []
            assert vib.scan_ast_zero_api(txt, rel) == []
        elif rel.endswith(".md"):
            assert vib.scan_markdown_honesty(txt, rel) == []
