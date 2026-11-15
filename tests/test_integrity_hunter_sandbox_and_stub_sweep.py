from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tokenize

from scripts import integrity_hunter_sandbox_and_stub_sweep as sweep
from scripts import verify_integrity_branch as vib

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_hunter_sandbox_and_stub_sweep.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_hunter_sandbox_and_stub_sweep.md"
TEST_PATH = ROOT / "tests" / "test_integrity_hunter_sandbox_and_stub_sweep.py"


def test_unit_fast_cli_sweep_and_positive_controls_pass(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    out_json = tmp_path / "hunter_sweep_summary.json"
    rc = sweep.main([
        "--unit-fast",
        "--scratch-dir",
        str(scratch),
        "--json-out",
        str(out_json),
        "--check-report",
        str(REPORT_PATH),
    ])
    assert rc == 0
    assert out_json.is_file()
    if scratch.exists():
        assert list(scratch.iterdir()) == []

    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["all_passed"] is True
    assert summary["mode"] == "quick"
    assert summary["unit_fast"] is True
    assert summary["live_llm_calls"] == 0
    assert summary["report_check"]["passed"] is True
    assert summary["report_check"]["issues"] == []

    sb = summary["sandbox_audit"]
    assert sb["passed"] is True
    assert sb["results_in_secret_excludes"] is False
    assert sb["ledger_key_in_secret_excludes"] is False
    assert sb["salt_in_secret_excludes"] is False
    assert sb["api_keys_in_pass_keys"] == ["GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"]
    assert sb["prompts_verified"] is True
    assert sb["whitebox_has_env_py"] is True
    assert sb["whitebox_excludes_hunter_py"] is True

    bb_scan = sb["blackbox_sandbox"]
    assert bb_scan["clean"] is True
    assert bb_scan["file_count"] == 0
    assert bb_scan["total_bytes"] == 0

    wb_scan = sb["whitebox_sandbox"]
    assert wb_scan["clean"] is True
    assert wb_scan["file_count"] >= 288
    assert wb_scan["salt_files"] == 0
    assert wb_scan["dotenv_files"] == 0
    assert wb_scan["data_runs_files"] == 0
    assert wb_scan["judge_files"] == 0
    assert wb_scan["redteam_files"] == 0
    assert wb_scan["exploits_md_files"] == 0
    assert wb_scan["reports_files"] == 0
    assert wb_scan["ledger_key_files"] == 0
    assert wb_scan["top_level_results_files"] == 0
    assert len(wb_scan["nested_results_files"]) >= 4
    assert wb_scan["docs_file_count"] >= 70
    assert wb_scan["media_file_count"] >= 20
    assert wb_scan["integrity_test_file_count"] >= 30

    env_audit = sb["attacker_env_audit"]
    assert env_audit["clean"] is True
    assert env_audit["unexpected_keys"] == []

    se = sb["seed_env_audit"]
    assert se["clean"] is True
    assert se["judge_seeds_checked"] == 40
    assert se["heldout_seeds_checked"] == 200
    assert se["dev_seeds_checked"] == 10000
    assert se["train_seeds_checked"] == 1000
    assert se["total_seeds_checked"] == 11240
    assert se["fake_toy_hard_forge_raises_keyerror"] is True
    assert se["fake_toy_wrong_accuse_score"] == 0.0
    assert se["fake_toy_ledger_exposes_mole"] is True

    inv = sb["repo_results_inventory"]
    assert inv["total_files"] >= 2000
    assert inv["harbor_files"] >= 1000
    assert inv["retired_harbor_ledger_keys"] >= 8
    assert [a["id"] for a in sb["advisories"]] == [
        "ISS-HUNTER-01",
        "ISS-HUNTER-02",
        "ISS-HUNTER-03",
        "ISS-HUNTER-04",
    ]

    st = summary["stub_sweep"]
    assert st["passed"] is True
    assert st["cell_runs"] == 5
    assert st["cli_entrypoint_runs"] == 1
    assert st["total_stub_runs"] == 6
    assert set(st["server_kinds_covered"]) == {"envshim", "fake"}
    assert set(st["tiers_covered"]) == {"easy", "medium", "hard", "hard_forge"}
    assert set(st["modes_covered"]) == {"blackbox", "whitebox"}
    assert st["exploits"] == 0
    assert st["leaked_orphan_server_count"] == 0
    assert st["probe_no_token_all_held"] is True
    assert st["single_accusation_enforced_runs"] == 5
    assert st["quick_contract"]["passed"] is True
    assert st["quick_contract"]["modes_0600_ok"] is True

    pc = summary["positive_controls"]
    assert pc["passed"] is True
    assert pc["clean_baseline_false_positive"] is False
    assert pc["controls_total"] == 6
    assert pc["controls_caught"] == 6
    assert pc["recall"] == "6/6"
    assert tuple(c["id"] for c in pc["controls"]) == sweep.POSITIVE_CONTROL_IDS


def test_sandbox_env_secret_and_verdict_detectors_synthetic(tmp_path: Path) -> None:
    clean_sb = tmp_path / "clean_sb"
    (clean_sb / "src").mkdir(parents=True)
    (clean_sb / "src" / ".env.example").write_text("GEMINI_API_KEY=\n", encoding="utf-8")
    assert sweep.scan_sandbox_directory(clean_sb)["clean"] is True

    dirty_sb = tmp_path / "dirty_sb"
    for rel in (
        "src/.env.local",
        "src/data/runs/ep.jsonl",
        "src/docs/EXPLOITS.md",
        "src/docs/reports/r.md",
        "src/results/table.json",
        "src/canary/redteam/hunter.py",
    ):
        fp = dirty_sb / rel
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("x\n", encoding="utf-8")
    dirty_res = sweep.scan_sandbox_directory(dirty_sb)
    assert dirty_res["clean"] is False
    joined_v = " ".join(dirty_res["violations"])
    for tag in ("dotenv_leak", "data_runs_leak", "exploits_md_leak", "reports_leak", "top_level_results_leak", "redteam_leak"):
        assert tag in joined_v

    saved_env = dict(os.environ)
    try:
        for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
            os.environ.pop(k, None)
        cleaned_keyless = sweep.hunter.clean_env()
        assert sweep.scan_attacker_env(cleaned_keyless)["clean"] is True
    finally:
        os.environ.clear()
        os.environ.update(saved_env)

    bad_env = sweep.scan_attacker_env(
        {"PATH": "/usr/bin", "PYTHONPATH": ".", "VIRTUAL_ENV": "/v", "EXTRA_SECRET": "tok-77"},
        ("tok-77",),
    )
    assert bad_env["clean"] is False
    assert len(bad_env["violations"]) >= 3

    sec_bad = sweep.audit_secret_consumption_and_proc_env(
        [],
        "PATH=/usr/bin\x00CANARY_WORLD_SECRET=raw\x00",
        ("raw",),
        expect_bootstrapped=True,
    )
    assert sec_bad["clean"] is False
    assert "missing_canary_bootstrapped_marker" in sec_bad["violations"]
    assert "proc_environ_secret_value_leak" in sec_bad["violations"]

    probe_ok = {"admin_reset_get": 405, "none": 403, "empty": 403, "wrong": 403, "prefix": 403}
    led_zero_wrong = {"done": True, "score": 0.0, "accused": "e01", "accused_correct": False, "ledger": []}
    an_wrong = {"score": 0.0, "correct": False, "n_accusations": 1, "exploit": False, "flags": []}
    assert sweep.audit_probe_and_ledger_verdict(probe_ok, 403, 200, led_zero_wrong, an_wrong, False, "real")["clean"] is False
    assert sweep.audit_probe_and_ledger_verdict(probe_ok, 404, 200, led_zero_wrong, an_wrong, False, "fake")["clean"] is True

    bad_md = tmp_path / "bad_report.md"
    bad_md.write_text("Luck-adjusted 72% [52%, 91%] before 65% [24%, 98%], pre-registered\u2014bad.\n", encoding="utf-8")
    md_issues = sweep.check_report_text(bad_md)
    assert any("em/en dash" in x for x in md_issues)
    assert any("pre-reg" in x for x in md_issues)
    assert any("before luck-adjusted" in x for x in md_issues)


def test_w9c_files_strict_hygiene() -> None:
    for p, rel in (
        (SCRIPT_PATH, "scripts/integrity_hunter_sandbox_and_stub_sweep.py"),
        (REPORT_PATH, "docs/reports/integrity_hunter_sandbox_and_stub_sweep.md"),
        (TEST_PATH, "tests/test_integrity_hunter_sandbox_and_stub_sweep.py"),
    ):
        assert p.is_file(), f"missing {rel}"
        assert p.stat().st_size <= 130 * 1024
        txt = p.read_text(encoding="utf-8")
        assert vib.scan_text_hygiene(txt, rel) == []
        if rel.endswith(".py"):
            assert chr(35) not in txt
            comments = [
                tok for tok in tokenize.generate_tokens(io.StringIO(txt).readline) if tok.type == tokenize.COMMENT
            ]
            assert comments == []
            assert vib.scan_ast_zero_api(txt, rel) == []
        else:
            assert vib.scan_markdown_honesty(txt, rel) == []
            assert sweep.check_report_text(p) == []
