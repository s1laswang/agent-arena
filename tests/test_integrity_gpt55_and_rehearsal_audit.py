from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize

import pytest

from scripts import integrity_gpt55_and_rehearsal_audit as audit

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "integrity_gpt55_and_rehearsal_audit.py"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "integrity_gpt55_and_rehearsal_audit.md"
TEST_PATH = Path(__file__).resolve()


@pytest.fixture(scope="module")
def quick_payload(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    out_dir = tmp_path_factory.mktemp("w1b_gpt55_rehearsal")
    out_json = out_dir / "w1b_summary.json"
    rc = audit.main(
        [
            "--quick",
            "--scratch-dir",
            str(out_dir),
            "--out-json",
            str(out_json),
            "--check-report",
            str(REPORT_PATH),
        ]
    )
    assert rc == 0
    return json.loads(out_json.read_text(encoding="utf-8"))


def test_quick_audit_gpt55_replay_and_tables(quick_payload: dict[str, object]) -> None:
    assert quick_payload["ok"] is True
    assert quick_payload["report_check"]["ok"] is True

    hl = quick_payload["headline"]
    assert hl["gpt55_episodes"] == 30
    assert hl["gpt55_valid"] == 30
    assert hl["gpt55_invalid"] == 0
    assert hl["gpt55_stopped_no_accuse"] == 2
    assert hl["gpt55_steps_replayed"] == 2075
    assert hl["gpt55_step_mismatches"] == 0
    assert hl["gpt55_seconds_after_cf394894"] > 0.0
    assert hl["gpt55_ratio_vs_solver"] == "101% [79%, 140%]"
    assert hl["gpt55_luck_adjusted_vs_solver"] == "84% [67%, 103%]"

    rep = quick_payload["gpt55_replay_and_accounting"]
    assert rep["ok"] is True
    assert rep["accused_count"] == 28
    assert rep["correct_count"] == 28
    assert rep["wrong_count"] == 0
    assert rep["stopped_seeds"] == [0, 17]
    assert rep["stopped_env_days"] == {"0": 8, "17": 9}
    assert rep["stopped_verbal_mole_match_count"] == 2
    assert rep["transcript_tool_mismatches"] == 0
    assert rep["transcript_cli_errors"] == 0
    assert rep["secret_or_cheat_hits"] == 0
    assert rep["usage_exact"] is True
    assert rep["lock_ordering"]["ok"] is True
    assert rep["lock_ordering"]["max_concurrent_episodes"] <= 8

    tbl = quick_payload["gpt55_tables_and_docs"]
    assert tbl["ok"] is True
    assert tbl["behaviour_compare_exact_match"] is True
    assert tbl["paired_json_exact_match"] is True
    assert tbl["anticheat_replay_live_ok"] is True


def test_harbor_rehearsal_provenance_and_regeneration(quick_payload: dict[str, object]) -> None:
    reh = quick_payload["harbor_rehearsal"]
    assert reh["ok"] is True
    assert all(reh["provenance_checks"].values())
    assert reh["correction_header_ok"] is True
    assert reh["negative_controls_ok"] is True
    assert reh["oracle_ok"] is True
    assert reh["run_counts_ok"] is True
    assert reh["snapshot_table_exact_match"] is True
    assert reh["final_rehearsal_table_exact_match"] is True
    assert reh["s1_rehearsal_final_git_exact_match"] is True
    assert reh["rehearsal_table_exact_match"] is True
    assert reh["doc_rehearsal_ok"] is True

    m = reh["metrics"]
    assert m["do_nothing_mean"] == 0.0
    assert m["stop_early_mean"] == 0.0
    assert abs(m["oracle_mean"] - 0.506) < 1e-9
    assert abs(m["opencode_1_mean"] - 0.472) < 1e-9
    assert abs(m["opencode_2_mean"] - 0.585) < 1e-9
    assert abs(m["opencode_3_mean"] - 0.625556) < 1e-5
    assert m["opencode_3_ratio_ci"] == "131% [86%, 590%]"
    assert m["opencode_3_valid_count"] == 9
    assert m["opencode_3_infra_count"] == 1
    assert m["opencode_3_unstarted_count"] == 0
    assert m["valid_correct_total"] == 28
    assert m["valid_accused_total"] == 29


def test_positive_controls_and_report_only_issues(quick_payload: dict[str, object]) -> None:
    ctrl = quick_payload["positive_controls"]
    assert ctrl["all_caught"] is True
    assert len(ctrl["controls"]) == 6
    assert all(ctrl["controls"].values())

    iss = quick_payload["report_only_issues"]
    assert iss["issue_count"] == 5
    assert iss["tamper_guard_replay_live_ok"] is True
    assert iss["tamper_guard_flagged_gpt55_seeds"] == []
    got_ids = [item["id"] for item in iss["issues"]]
    assert got_ids == [f"ISSUE-W1B-{i}" for i in range(1, 6)]


def test_report_validator_and_owned_file_hygiene(tmp_path: Path) -> None:
    rep_res = audit.check_report_file(REPORT_PATH)
    assert rep_res["ok"] is True

    em_dash = chr(0x2014)
    banned_kw = "pre-" + "reg"
    bad_md = tmp_path / "bad_report.md"
    bad_md.write_text(
        REPORT_PATH.read_text(encoding="utf-8") + f"\n{banned_kw} {em_dash}\n",
        encoding="utf-8",
    )
    bad_res = audit.check_report_file(bad_md)
    assert bad_res["ok"] is False
    assert em_dash in bad_res["bad_dashes"]
    assert banned_kw in bad_res["banned_prereg"]

    forbidden_dashes = (chr(0x2014), chr(0x2013), chr(0x2212))
    for path in (SCRIPT_PATH, REPORT_PATH, TEST_PATH):
        assert path.is_file()
        assert path.stat().st_size <= 130 * 1024
        content = path.read_text(encoding="utf-8")
        for ch in forbidden_dashes:
            assert ch not in content

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        comments = [
            tok
            for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == []
