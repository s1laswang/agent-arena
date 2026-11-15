from __future__ import annotations

import importlib.util
import json
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import world

SCRIPT_PATH = ROOT / "scripts" / "integrity_final_make_hunt_v14.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_final_make_hunt_v14.md"
TEST_PATH = Path(__file__).resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("integrity_final_make_hunt_v14", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


sweep_mod = _load_module()


@pytest.fixture(scope="module")
def quick_run(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("w2_final_make_hunt_quick")
    before_secret = world._SET_SECRET
    rc = sweep_mod.main([
        "--quick",
        "--out-dir",
        str(out_dir),
        "--check-report",
        str(REPORT_PATH),
    ])
    after_secret = world._SET_SECRET
    summary_path = out_dir / "final_make_hunt_v14_summary.json"
    assert summary_path.is_file()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    return {
        "rc": rc,
        "before_secret": before_secret,
        "after_secret": after_secret,
        "summary": summary,
    }


def test_quick_sweep_end_to_end_and_secret_restoration(quick_run):
    assert quick_run["rc"] == 0
    assert quick_run["before_secret"] == quick_run["after_secret"]
    s = quick_run["summary"]
    assert s["all_passed"] is True
    assert s["tiers_version"] == "v1.4"
    assert s["known_v_mode"] is True
    assert s["v14_tier_hash"] == "a8f99c2537c91d72"
    assert s["v13_tier_hash"] == "8df71cf570bb48bc"
    assert s["quick"] is True
    assert s["jobs"] == 1
    assert s["total_cells"] == 6
    assert s["tracks_make_hunt"] == ["easy", "medium", "hard", "hard_forge"]
    assert s["tracks_heldout"] == ["hard", "hard_forge"]
    assert s["modes"] == ["random", "malformed", "evolve", "parallel_accuse"]
    assert s["total_genomes_evaluated"] == 18
    assert s["total_parallel_races"] == 6
    assert s["best_non_solver_score"] == 0.0
    assert s["total_invariant_violations"] == 0
    assert s["total_strict_v14_violations"] == 0
    assert s["full_seed_parity_audit"]["track_seed_pairs_probed"] == 6
    assert s["full_seed_parity_audit"]["violations_count"] == 0
    assert s["full_seed_parity_audit"]["strict_v14_violations_count"] == 0
    assert s["report_check"]["ok"] is True


def test_anticheat_roundtrip_and_committed_artifact_invariants(quick_run):
    ac = quick_run["summary"]["anticheat_verification"]
    assert ac["verified_ok"] is True
    assert ac["committed_rows"] == 99
    assert ac["committed_n_seeds"] == 40
    assert ac["committed_seed_range"] == [900000, 900039]
    assert ac["committed_tiers"] == ["easy", "medium", "hard"]
    assert ac["all_blocked"] is True
    assert ac["replay_all_consistent"] is True
    assert ac["replay_counts"]["replayed"] == 1051
    assert ac["replay_counts"]["consistent"] == 1051
    assert ac["replay_counts"]["step_mismatches"] == 0
    assert ac["harbor_all_consistent"] is True
    assert ac["harbor_trials_consistent"] == 80
    assert ac["harbor_jobs_consistent"] == 18
    assert ac["verify_rc"] == 0
    assert ac["differences"] == 0
    assert ac["tamper_positive_control_rc"] == 1
    assert ac["tamper_positive_control_diffs"] >= 1
    assert ac["live_replay_sampled"] is True
    assert ac["live_replay_replayed"] >= 2
    assert ac["live_replay_consistent"] == ac["live_replay_replayed"]
    assert ac["live_replay_step_mismatches"] == 0
    assert ac["live_replay_ok"] is True
    assert ac["synthetic_replay_tamper_caught"] is True


def test_shallow_detached_head_fallback_without_origin_justsilas(tmp_path):
    import subprocess

    shallow_repo = tmp_path / "shallow_ci_repo"
    shallow_repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "sh",
            "-e",
            "-c",
            "git init -q && git -c user.email=ci@example.com -c user.name=CI commit --allow-empty -qm init "
            "&& git checkout -q --detach HEAD",
        ],
        cwd=shallow_repo,
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )

    prov = sweep_mod.resolve_git_provenance(root=shallow_repo, base_ref="origin/justSilas")
    assert prov["ok"] is True
    assert prov["shallow_ci_fallback"] is True
    assert prov["detached_head"] is True
    assert prov["resolved_base_ref"] == "HEAD"
    assert prov["pinned_justsilas_sha"] == "5f9b3297"
    assert prov["protected_touched"] == []

    no_git_dir = tmp_path / "no_git_archive"
    no_git_dir.mkdir(parents=True, exist_ok=True)
    prov_nogit = sweep_mod.resolve_git_provenance(root=no_git_dir, base_ref="origin/justSilas")
    assert prov_nogit["ok"] is True
    assert prov_nogit["shallow_ci_fallback"] is True
    assert prov_nogit["resolved_base_ref"] is None
    assert prov_nogit["resolved_base_sha"] == "5f9b3297"


def test_fake_env_positive_controls_and_strict_v14_oracle(quick_run):
    fc = quick_run["summary"]["fake_env_positive_controls"]
    assert fc["clean_control"]["clean"] is True
    assert fc["bugs_tested"] == 6
    assert fc["bugs_caught"] == 6
    assert fc["all_caught"] is True
    for bug_name in (
        "accuse_twice",
        "truth_leak",
        "parity_leak",
        "unhandled_exception",
        "wrong_accusation_positive",
        "parallel_accuse_race",
    ):
        assert fc["per_bug"][bug_name]["caught"] is True
    v0 = fc["v0_zero_wrong_audit"]
    assert v0["fuzz_score_invariants_caught"] is False
    assert v0["strict_v14_oracle_caught"] is True
    assert v0["strict_v14_violations_count"] >= 1


def test_report_only_issues_and_text_hygiene(quick_run):
    issues = quick_run["summary"]["report_only_issues"]
    assert [i["id"] for i in issues] == [
        "ISSUE-W2-FUZZ-ALL-BUDGET-TRUNCATION-AND-SHARED-RNG",
        "ISSUE-W2-FUZZ-LEGACY-V0-ZERO-SCORE-INVARIANT-GAP",
        "ISSUE-W2-MAKE-HUNT-DEFAULT-OUT-DIR-ACCUMULATION",
    ]
    assert issues[0]["evidence"]["makefile_requested_budget"] == 80000
    assert issues[0]["evidence"]["makefile_actual_genomes"] == 79992
    assert issues[0]["evidence"]["makefile_dropped_genomes_modulo_3"] == 8
    assert issues[0]["evidence"]["shared_rng_warmup_identical"] is True

    rep_chk = sweep_mod.check_report_hygiene(
        REPORT_PATH,
        expected_tokens=(
            "5f9b3297",
            "8302df7a",
            "65% [24%, 98%]",
            "72% [52%, 91%]",
            "post-hoc lock",
            "never binds",
            "11,988",
            "352,000",
            "363,233",
            "ISSUE-W2-FUZZ-ALL-BUDGET-TRUNCATION-AND-SHARED-RNG",
            "ISSUE-W2-FUZZ-LEGACY-V0-ZERO-SCORE-INVARIANT-GAP",
            "ISSUE-W2-MAKE-HUNT-DEFAULT-OUT-DIR-ACCUMULATION",
        ),
    )
    assert rep_chk["ok"] is True, rep_chk["problems"]

    for py_path in (SCRIPT_PATH, TEST_PATH):
        with py_path.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"comments found in {py_path}"
