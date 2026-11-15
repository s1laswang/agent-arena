from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_audit_replays_and_harbor.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("integrity_audit_replays_and_harbor", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit_mod = _load_module()


@pytest.fixture(scope="module")
def full_report(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("lane_c1_audit")
    return audit_mod.run_full_audit(root=ROOT, tmp_base=tmp_dir)


def test_committed_runs_and_judge_episodes_pass_data_rules(full_report):
    da = full_report["data_rule_audit"]
    assert da["passed"] is True, da["violations"]
    assert da["violations"] == []
    assert da["active_files"] >= 61
    assert da["active_episodes"] >= 999
    assert da["active_valid"] >= 991
    assert da["active_invalid"] >= 8
    assert da["superseded"]["n_files"] >= 13
    assert da["superseded"]["n_episodes"] >= 58
    assert da["superseded"]["violations"] == []
    assert da["judge_episodes_total"] >= 840
    assert len(da["judge_cohorts"]) >= 21
    for c in da["cohorts"]:
        assert c["dup_in_file"] == 0, c
        assert c["dup_in_cohort"] == 0, c
        assert c["end_error_valid"] == 0, c
        assert c["rc_timeout_valid"] == 0, c
        assert c["wall_ge_cap_no_accuse"] == 0, c
        assert c["score_domain_bad"] == 0, c
        assert c["score_v_mismatch"] == 0, c
        assert c["n_total"] == c["n_distinct_seeds"], c
    for jc in da["judge_cohorts"]:
        assert jc["dup_in_cohort"] == 0, jc
        assert jc["violations"] == 0, jc
        assert jc["n_total"] == 40 and jc["n_distinct_seeds"] == 40, jc


def test_live_tamper_guard_and_rehearsal_dry_pass(full_report):
    lt = full_report["live_tamper_guard"]
    assert lt["replay_all_consistent"] is True
    assert lt["replay_counts"]["replayed"] >= 989
    assert lt["replay_counts"]["step_mismatches"] == 0
    assert lt["harbor_all_consistent"] is True
    assert lt["harbor_jobs"] >= 18
    assert lt["harbor_trials"] >= 80
    assert lt["harbor_retired_key_resign_notices"] >= 57

    rd = full_report["rehearsal_dry_audit"]
    assert rd["passed"] is True, rd["problems"]
    assert rd["n_jobs"] == 5
    assert rd["n_trials"] == 43
    assert rd["n_hmac_verified"] == 43
    assert rd["n_trajectory_checked"] == 13
    assert rd["n_retired_key_resign_notices"] == 43
    assert rd["shared_retired_key_count"] == 1
    assert rd["table_md_matches"] is True


@pytest.mark.parametrize(
    "bad_ep,expected_substr",
    [
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": 0.0,
                "accused": None,
                "correct": False,
                "end_reason": "error",
                "meta": {"valid": True},
            },
            "end_reason == 'error'",
        ),
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": 0.0,
                "accused": None,
                "correct": False,
                "end_reason": "horizon",
                "meta": {"rc": "timeout", "valid": True},
            },
            "timeout",
        ),
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": 0.0,
                "accused": None,
                "correct": False,
                "end_reason": "horizon",
                "meta": {"wall_s": 10800.0, "valid": True},
            },
            "wall_s=",
        ),
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": -0.5,
                "accused": "e01",
                "correct": False,
                "final_day": 5,
                "end_reason": "accused",
                "meta": {},
            },
            "outside {-1.0, 0.0}",
        ),
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": 0.72,
                "accused": "e01",
                "correct": True,
                "final_day": 5,
                "end_reason": "accused",
                "meta": {"V_final": 0.60},
            },
            "meta.V_final",
        ),
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": 0.0,
                "accused": "e01",
                "correct": True,
                "final_day": 5,
                "end_reason": "accused",
                "meta": {},
            },
            "without V==0.0",
        ),
        (
            {
                "tier": "hard",
                "seed": 1,
                "agent": "a",
                "score": -1.0,
                "accused": "e01",
                "correct": False,
                "final_day": 5,
                "end_reason": "accused",
                "meta": {"valid": False, "error": "infra:provider_quota"},
            },
            "invalid episode",
        ),
    ],
)
def test_data_rule_auditor_catches_planted_violations(tmp_path, bad_ep, expected_substr):
    run_dir = tmp_path / "data/runs/committed/v1.4/bad_agent/hard"
    run_dir.mkdir(parents=True)
    (run_dir / "episodes.jsonl").write_text(json.dumps(bad_ep) + "\n", encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps({"tiers_version": "v1.4", "timeout_s": 10800.0}), encoding="utf-8"
    )
    res = audit_mod.audit_data_rules(tmp_path)
    assert res["passed"] is False
    assert any(expected_substr in v for v in res["violations"]), res["violations"]


def test_data_rule_auditor_catches_duplicate_seeds_in_run(tmp_path):
    run_dir = tmp_path / "data/runs/committed/v1.4/dup_agent/medium"
    run_dir.mkdir(parents=True)
    ep_a = {
        "tier": "medium",
        "seed": 7,
        "agent": "dup_agent",
        "score": 0.8,
        "accused": "e01",
        "correct": True,
        "final_day": 5,
        "end_reason": "accused",
        "meta": {"V_final": 0.8},
    }
    ep_b = {
        "tier": "medium",
        "seed": 7,
        "agent": "dup_agent",
        "score": -1.0,
        "accused": "e02",
        "correct": False,
        "final_day": 6,
        "end_reason": "accused",
        "meta": {"V_final": 0.8},
    }
    (run_dir / "episodes.jsonl").write_text(
        json.dumps(ep_a) + "\n" + json.dumps(ep_b) + "\n", encoding="utf-8"
    )
    (run_dir / "meta.json").write_text(json.dumps({"tiers_version": "v1.4"}), encoding="utf-8")
    res = audit_mod.audit_data_rules(tmp_path)
    assert res["passed"] is False
    assert any("duplicate seed 7" in v for v in res["violations"]), res["violations"]


def test_replay_mutation_matrix_completeness_and_verdicts(full_report):
    rows = full_report["replay_mutations"]
    assert len(rows) == 17
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {f"R{i:02d}" for i in range(1, 18)}

    must_block = (
        "R01",
        "R02",
        "R03",
        "R04",
        "R05",
        "R06",
        "R07",
        "R08",
        "R09",
        "R12",
        "R13",
        "R14",
        "R15",
        "R16",
        "R17",
    )
    for mid in must_block:
        assert by_id[mid]["tamper_guard_caught"] is True, by_id[mid]
        assert by_id[mid]["anticheat_caught"] is True, by_id[mid]
        assert by_id[mid]["bypass"] is False, by_id[mid]
        assert by_id[mid]["location"], by_id[mid]

    assert by_id["R11"]["tamper_guard_caught"] is False
    assert by_id["R11"]["bypass"] is False

    assert by_id["R10"]["tamper_guard_caught"] is False
    assert by_id["R10"]["bypass"] is True

    assert by_id["R12"]["audit_submission_caught"] is True
    assert by_id["R13"]["audit_submission_caught"] is True


def test_harbor_mutation_matrix_completeness_and_verdicts(full_report):
    rows = full_report["harbor_mutations"]
    assert len(rows) == 14
    by_id = {r["id"]: r for r in rows}
    assert set(by_id) == {f"H{i:02d}" for i in range(1, 15)}

    must_block = (
        "H01",
        "H02",
        "H03",
        "H05",
        "H06",
        "H07",
        "H08",
        "H09",
        "H10",
        "H11",
        "H12",
        "H13",
        "H14",
    )
    for mid in must_block:
        assert by_id[mid]["tamper_guard_caught"] is True, by_id[mid]
        assert by_id[mid]["anticheat_caught"] is True, by_id[mid]
        assert by_id[mid]["bypass"] is False, by_id[mid]
        assert by_id[mid]["location"], by_id[mid]

    assert by_id["H01"]["verifier_caught"] is True
    assert by_id["H03"]["verifier_caught"] is True
    assert by_id["H02"]["verifier_caught"] is False
    assert by_id["H05"]["verifier_caught"] is False
    assert by_id["H04"]["verifier_caught"] is False
    assert by_id["H04"]["tamper_guard_caught"] is False
    assert by_id["H04"]["bypass"] is False


def test_cli_json_output_is_strict_rfc8259_json(monkeypatch, capsys, full_report):
    monkeypatch.setattr(audit_mod, "run_full_audit", lambda root=ROOT, tmp_base=None: full_report)
    rc = audit_mod.main(["--root", str(ROOT), "--json"])
    out = capsys.readouterr().out
    parsed = json.loads(
        out,
        parse_constant=lambda c: (_ for _ in ()).throw(ValueError(f"non-standard JSON constant {c}")),
    )
    assert rc == 0
    assert parsed["summary"]["total_mutations"] == 31
    assert parsed["data_rule_audit"]["passed"] is True
    assert parsed["rehearsal_dry_audit"]["passed"] is True
