from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

from canary.env import Env

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "judge_15min_whitebox_hunt.py"
REPORT_PATH = ROOT / "docs" / "reports" / "judge_15min_hunt.md"


def _load_hunt_module():
    spec = importlib.util.spec_from_file_location("judge_15min_whitebox_hunt", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


hunt = _load_hunt_module()


def test_quick_cli_all_five_vectors_pass(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    out_json = tmp_path / "quick_summary.json"
    t0 = time.perf_counter()
    rc = hunt.main([
        "--quick",
        "--workers",
        "1",
        "--scratch-dir",
        str(scratch),
        "--json-out",
        str(out_json),
    ])
    elapsed = time.perf_counter() - t0
    assert rc == 0
    assert elapsed < 14.5
    assert out_json.is_file()
    if scratch.exists():
        assert list(scratch.iterdir()) == []

    summary = json.loads(out_json.read_text(encoding="utf-8"))
    assert summary["ok"] is True
    assert summary["mode"] == "quick"
    assert summary["workers"] == 1
    assert set(summary["vectors"].keys()) == {"V1", "V2", "V3", "V4", "V5"}

    v1 = summary["vectors"]["V1"]
    assert v1["ok"] is True
    assert v1["n_sequences"] == 40
    assert v1["total_episode_runs"] == 80
    assert v1["accepted_cheats"] == 0
    assert v1["v_rises"] == 0
    assert v1["score_gains_over_solver"] == 0
    assert v1["encoded_leak_hits"] == 0
    assert v1["encoders_available"] >= 107
    assert v1["non_caesar_base_encoders"] >= 79
    assert v1["momin_corpus_rows"] == 129
    assert v1["transcript_miner"]["frontier_files"] == 5
    assert v1["transcript_miner"]["frontier_episodes"] == 150
    assert v1["transcript_miner"]["frontier_rejected"] == 138
    assert all(row["held"] is True for row in v1["sequences"])

    v2 = summary["vectors"]["V2"]
    assert v2["ok"] is True
    assert v2["n_secrets"] == 60
    assert v2["total_employee_rows"] == 2400
    assert v2["loo_joint_metadata_oracle_ev"] < -0.50
    assert v2["insample_overfit_joint_oracle_ev"] < -0.50
    for feat in ("clearance", "dept", "role", "doc_count"):
        assert v2["features"][feat]["mole_p"] > 0.01

    v3 = summary["vectors"]["V3"]
    assert v3["ok"] is True
    assert v3["n_vectors"] == 16
    assert v3["failed_closed_count"] == 16
    assert v3["controls_ok"] is True
    by_id = {r["id"]: r for r in v3["vectors"]}
    assert set(by_id.keys()) == {f"F{i:02d}" for i in range(1, 17)}
    assert by_id["F16"]["child_killed"] is True

    v4 = summary["vectors"]["V4"]
    assert v4["ok"] is True
    assert v4["salt_file_present"] is False
    assert v4["live_urandom_unique_secrets"] == 20
    assert v4["live_public_roster_matches"] == 0
    assert v4["public_key_roster_matches"] == 0
    assert v4["cross_reset_unique_episode_tokens"] == 20

    v5 = summary["vectors"]["V5"]
    assert v5["ok"] is True
    assert v5["rehearsal_dry_jobs"] == 5
    assert v5["rehearsal_dry_trials"] == 43
    assert v5["same_build_ledger_key_across_rehearsal_dry"] is True
    assert v5["isolation_checks_passed"] == "36/36"
    assert v5["infra_rerun_exact_match"] is True
    assert v5["oracle_valid_mean"] == 0.467
    assert v5["opencode_valid_mean"] == 0.398
    assert v5["negative_controls"]["forged_unscored_infra_exclusion_caught"] is True
    assert v5["negative_controls"]["forged_cheat_probe_hole_caught"] is True


def test_workers_guard_and_unknown_vector(tmp_path: Path) -> None:
    assert hunt.main(["--workers", "2", "--quick", "--scratch-dir", str(tmp_path)]) == 2
    with pytest.raises(ValueError):
        hunt.run_all(repo_root=ROOT, scratch_dir=tmp_path, quick=True, vectors=("V99",))


def test_positive_exploit_and_contingency_detectors() -> None:
    ok_trunc, err_trunc, is_trunc = hunt._unwrap_step_result({"raw": "truncated blob"})
    assert (ok_trunc, err_trunc, is_trunc) == (True, None, True)

    ok_nested, err_nested, is_nested = hunt._unwrap_step_result(
        {"ok": True, "error": json.dumps({"ok": False, "error": "invalid arguments"})}
    )
    assert (ok_nested, err_nested, is_nested) == (False, "invalid arguments", False)

    biased = {
        "leak_bucket": [100, 95, 0],
        "normal_bucket": [3900, 5, 100],
    }
    stats = hunt._contingency_stats(biased)
    assert stats["mole_p"] < 1e-6
    assert stats["mole_mi_bits"] > 0.1

    env = Env("easy", 0)
    _, cur_true, cur_vis, rose_clean = hunt._step_checked(env, "status", {}, round(env.V, 10), env.visible_V())
    assert rose_clean is False
    _, _, _, rose_planted = hunt._step_checked(env, "status", {}, cur_true - 0.05, cur_vis)
    assert rose_planted is True


def test_report_and_source_hygiene() -> None:
    test_path = ROOT / "tests" / "test_judge_15min_whitebox_hunt.py"
    assert SCRIPT_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert test_path.is_file()

    for p in (SCRIPT_PATH, test_path, REPORT_PATH):
        txt = p.read_text(encoding="utf-8")
        assert "\u2014" not in txt
        assert "\u2013" not in txt

    for py_path in (SCRIPT_PATH, test_path):
        assert chr(35) not in py_path.read_text(encoding="utf-8")

    report_txt = REPORT_PATH.read_text(encoding="utf-8")
    for expected in (
        "38.339s",
        "27.001s",
        "1.749s",
        "7.796s",
        "1.034s",
        "0.752s",
        "4,030",
        "12,000",
        "-0.9933",
        "16/16",
        "36/36",
        "0.467",
        "0.398",
        "e0a919a36451fdda",
        "f713536597d716b4",
    ):
        assert expected in report_txt

    for fid in range(1, 17):
        assert f"`F{fid:02d}`" in report_txt
