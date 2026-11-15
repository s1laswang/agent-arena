from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from canary.agents.frontier import common, opencode_run

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "frontier_queue_preflight.py"
MANIFEST_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "queue_manifest.json"
HASH_CHAR = chr(35)
EM_DASH = "\u2014"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("frontier_queue_preflight", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


preflight = _load_preflight()


def test_real_repo_manifest_ownership_and_pure_cpu_waves():
    assert preflight.main(["--check"]) == 0
    assert preflight.main(["--validate-template-waves"]) == 0
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["tiers_version"] == "v1.4"
    assert manifest["summary"]["passed"] is True
    assert manifest["summary"]["pure_cpu_mode"] is True
    assert manifest["preflight"]["passed"] is True
    assert manifest["preflight"]["zero_live_llm_calls"] is True
    assert manifest["summary"]["replication_total_episodes"] >= 305
    assert (
        manifest["summary"]["replication_replay_verified_episodes"]
        == manifest["summary"]["replication_total_episodes"]
    )
    assert manifest["summary"]["target_frontier_episodes"] == 90
    assert manifest["summary"]["landed_frontier_episodes"] == 35
    assert manifest["summary"]["missing_frontier_episodes"] == 55
    assert manifest["summary"]["fr8_dispatch_active_episodes"] == 0
    assert manifest["summary"]["wave_count"] == 0
    assert manifest["summary"]["max_workers_in_any_wave"] == 0
    assert manifest["summary"]["template_wave_count"] == 19
    assert manifest["summary"]["template_commands_validated"] == 55
    assert manifest["waves"] == []

    sessions = manifest["gemini_sessions"]
    assert sessions["source_doc"] == "docs/agents/GEMINI-SESSIONS.md"
    assert sessions["source_commit"] == "f9fb7a4a"
    assert sessions["pure_cpu_mode"] is True
    assert sessions["fr8_live_gemini_dispatch_enabled"] is False
    assert sessions["g1_carbon_hard_ext60"]["execution_owner"] == "silas_g1_ext60"
    assert sessions["g1_carbon_hard_ext60"]["fr8_dispatch_enabled"] is False
    assert sessions["g1_carbon_hard_ext60"]["fr8_landed_seeds"] == [30, 34, 42, 45, 57]
    assert sessions["g1_carbon_hard_ext60"]["remaining_count"] == 25
    assert sessions["g2_frontier_families_hard_0_29"]["execution_owner"] == "silas_g2_families"
    assert sessions["g2_frontier_families_hard_0_29"]["models"] == [
        "google/gemini-4-argon",
        "google/gemini-4-hydrogen",
    ]
    assert sessions["g2_frontier_families_hard_0_29"]["allowed_during_carbon_blackout"] is True

    by_id = {c["cohort_id"]: c for c in manifest["cohorts"]}
    c_carbon = by_id["opencode-gemini-4-carbon-hard-30-59"]
    assert c_carbon["landed_seeds"] == [30, 34, 42, 45, 57]
    assert c_carbon["landed_count"] == 5
    assert c_carbon["missing_count"] == 25
    assert c_carbon["execution_owner"] == "silas_g1_ext60"
    assert c_carbon["fr8_dispatch_enabled"] is False
    assert sorted(c_carbon["landed_seeds"] + c_carbon["missing_seeds"]) == list(range(30, 60))

    c_flash_med = by_id["opencode-gemini-3.5-flash-medium-0-29"]
    assert c_flash_med["landed_seeds"] == list(range(30))
    assert 28 in c_flash_med["landed_seeds"]
    assert c_flash_med["landed_count"] == 30
    assert c_flash_med["missing_count"] == 0
    assert c_flash_med["missing_seeds"] == []
    assert c_flash_med["execution_owner"] == "fr8_frontier_complete"
    assert c_flash_med["fr8_dispatch_enabled"] is False

    c_flash_hard = by_id["opencode-gemini-3.5-flash-hard-30-59"]
    assert c_flash_hard["landed_count"] == 0
    assert c_flash_hard["missing_count"] == 30
    assert c_flash_hard["missing_seeds"] == list(range(30, 60))
    assert c_flash_hard["execution_owner"] == "fr8_frontier_paused_pure_cpu"
    assert c_flash_hard["fr8_dispatch_enabled"] is False


def test_template_wave_validation_and_dispatch_gating():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert preflight.partition_into_waves(manifest["cohorts"]) == []
    assert preflight.validate_wave_commands(manifest["waves"])["commands_validated"] == 0

    template_waves = preflight.build_template_waves(manifest["cohorts"])
    assert len(template_waves) == 19
    assert all(1 <= w["worker_count"] <= 3 and w["ram_safe"] is True for w in template_waves)

    by_id = {c["cohort_id"]: c for c in manifest["cohorts"]}
    queued_by_cohort: dict[str, list[int]] = {}
    for w in template_waves:
        assert [j["seed"] for j in w["jobs"]] == w["seeds"]
        queued_by_cohort.setdefault(w["cohort_id"], []).extend(w["seeds"])
    for cid, c in by_id.items():
        q = queued_by_cohort.get(cid, [])
        assert q == c["missing_seeds"]
        assert set(q).isdisjoint(set(c["landed_seeds"]))
        lo, hi = c["seed_range"]
        assert sorted(q + c["landed_seeds"]) == list(range(lo, hi + 1))

    val = preflight.validate_wave_commands(template_waves)
    assert val["passed"] is True
    assert val["commands_validated"] == 55

    g2_waves = preflight.build_g2_template_waves()
    assert len(g2_waves) == 20
    val_g2 = preflight.validate_wave_commands(g2_waves)
    assert val_g2["passed"] is True
    assert val_g2["commands_validated"] == 60

    enabled_copy = copy.deepcopy(manifest["cohorts"])
    for c in enabled_copy:
        if c["cohort_id"] == "opencode-gemini-3.5-flash-hard-30-59":
            c["fr8_dispatch_enabled"] = True
    flash_waves = preflight.partition_into_waves(enabled_copy)
    assert len(flash_waves) == 10
    assert all(w["cohort_id"] == "opencode-gemini-3.5-flash-hard-30-59" for w in flash_waves)

    bad_workers = copy.deepcopy(template_waves[:1])
    bad_workers[0]["worker_count"] = 4
    assert preflight.validate_wave_commands(bad_workers)["passed"] is False

    bad_flag = copy.deepcopy(template_waves[:1])
    bad_flag[0]["jobs"][0]["command"] += " --workers 2"
    res_flag = preflight.validate_wave_commands(bad_flag)
    assert res_flag["passed"] is False
    assert any("invalid flags" in e for e in res_flag["errors"])

    bad_path = copy.deepcopy(template_waves[:1])
    bad_path[0]["jobs"][0]["command"] = bad_path[0]["jobs"][0]["command"].replace(
        "PATH=/home/silas/momin/bin:$PATH ", ""
    )
    assert preflight.validate_wave_commands(bad_path)["passed"] is False

    bad_timeout = copy.deepcopy(template_waves[:1])
    bad_timeout[0]["jobs"][0]["command"] = bad_timeout[0]["jobs"][0]["command"].replace(
        "--timeout 3600", "--timeout 2400"
    )
    assert preflight.validate_wave_commands(bad_timeout)["passed"] is False

    with pytest.raises(ValueError):
        preflight.partition_into_waves(manifest["cohorts"], max_workers_per_wave=4)


def test_carbon_quota_blackout_boundaries_and_exempt_families():
    before = preflight.check_carbon_quota_blackout("2026-11-15T04:29:59Z")
    assert before["allowed"] is True
    assert before["in_blackout_window"] is False
    assert before["reason"] == "outside_carbon_blackout_window"

    inside_start = preflight.check_carbon_quota_blackout("2026-11-15T04:30:00Z")
    assert inside_start["allowed"] is False
    assert inside_start["in_blackout_window"] is True
    assert inside_start["reason"] == "rehearsal_carbon_blackout_0630_0815_eet"

    inside_mid = preflight.check_carbon_quota_blackout("2026-11-15T05:30:00Z")
    assert inside_mid["allowed"] is False
    assert inside_mid["in_blackout_window"] is True
    assert inside_mid["reason"] == "rehearsal_carbon_blackout_0630_0815_eet"

    inside_end = preflight.check_carbon_quota_blackout("2026-11-15T06:14:59Z")
    assert inside_end["allowed"] is False
    assert inside_end["in_blackout_window"] is True
    assert inside_end["reason"] == "rehearsal_carbon_blackout_0630_0815_eet"

    after = preflight.check_carbon_quota_blackout("2026-11-15T06:15:00Z")
    assert after["allowed"] is True
    assert after["in_blackout_window"] is False
    assert after["reason"] == "outside_carbon_blackout_window"

    epoch_before = int(datetime(2026, 11, 15, 4, 29, 59, tzinfo=timezone.utc).timestamp())
    epoch_start = int(datetime(2026, 11, 15, 4, 30, 0, tzinfo=timezone.utc).timestamp())
    epoch_mid = int(datetime(2026, 11, 15, 5, 30, 0, tzinfo=timezone.utc).timestamp())
    epoch_end_minus_1 = int(datetime(2026, 11, 15, 6, 14, 59, tzinfo=timezone.utc).timestamp())
    epoch_after = int(datetime(2026, 11, 15, 6, 15, 0, tzinfo=timezone.utc).timestamp())

    assert preflight.check_carbon_quota_blackout(epoch_before)["allowed"] is True
    assert preflight.check_carbon_quota_blackout(epoch_start)["allowed"] is False
    assert preflight.check_carbon_quota_blackout(float(epoch_mid))["allowed"] is False
    assert preflight.check_carbon_quota_blackout(str(epoch_end_minus_1))["allowed"] is False
    assert preflight.check_carbon_quota_blackout(epoch_after)["allowed"] is True

    assert preflight.check_carbon_quota_blackout("2026-11-15T06:29:59+02:00")["allowed"] is True
    assert preflight.check_carbon_quota_blackout("2026-11-15T06:30:00+02:00")["allowed"] is False
    assert preflight.check_carbon_quota_blackout("2026-11-15T08:14:59+02:00")["allowed"] is False
    assert preflight.check_carbon_quota_blackout("2026-11-15T08:15:00+02:00")["allowed"] is True

    for carbon_alias in ("gemini-4-carbon", "google/gemini-4-carbon", "opencode:google/gemini-4-carbon"):
        blocked = preflight.check_carbon_quota_blackout("2026-11-15T05:30:00Z", model=carbon_alias)
        assert blocked["allowed"] is False
        assert blocked["reason"] == "rehearsal_carbon_blackout_0630_0815_eet"

    for exempt_model in (
        "gemini-4-argon",
        "google/gemini-4-argon",
        "gemini-4-hydrogen",
        "google/gemini-4-hydrogen",
    ):
        allowed_res = preflight.check_carbon_quota_blackout("2026-11-15T05:30:00Z", model=exempt_model)
        assert allowed_res["allowed"] is True
        assert allowed_res["in_blackout_window"] is True
        assert allowed_res["is_carbon_model"] is False

    assert preflight.main(["--check-blackout", "2026-11-15T05:30:00Z"]) == 1
    assert preflight.main(["--check-blackout", "2026-11-15T04:29:59Z"]) == 0
    assert preflight.main(["--check-blackout", "2026-11-15T06:15:00Z"]) == 0
    assert preflight.main(["--check-blackout", "2026-11-15T05:30:00Z", "--model", "gemini-4-argon"]) == 0

    with pytest.raises(ValueError):
        preflight.check_carbon_quota_blackout(True)
    with pytest.raises(ValueError):
        preflight.check_carbon_quota_blackout("")
    with pytest.raises(ValueError):
        preflight.check_carbon_quota_blackout("not-a-timestamp")
    with pytest.raises(ValueError):
        preflight.check_carbon_quota_blackout(float("nan"))


def test_security_and_isolation_preflight_controls(monkeypatch):
    env_before = dict(os.environ)
    assert preflight.check_tiers_gate()["passed"] is True
    assert preflight.check_opencode_config_isolation()["passed"] is True
    assert preflight.check_child_env_stripping()["passed"] is True
    assert dict(os.environ) == env_before
    assert preflight.check_workdir_isolation(ROOT)["passed"] is True
    assert preflight.check_carbon_quota_blackout_guard()["passed"] is True

    monkeypatch.setattr(opencode_run, "PERMISSION", {"*": "allow"})
    res_perm = preflight.check_opencode_config_isolation()
    assert res_perm["passed"] is False
    monkeypatch.undo()

    monkeypatch.setattr(common, "child_env", lambda: {"GEMINI_API_KEY": "leaked", "PWD": ""})
    res_env = preflight.check_child_env_stripping()
    assert res_env["passed"] is False


def test_all_35_transcripts_including_s28_and_zip_export_safety(tmp_path):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tr_check = manifest["preflight"]["checks"]["transcript_redaction_infra_and_steps"]
    assert tr_check["passed"] is True
    assert tr_check["real_transcripts_checked"] == 35
    assert tr_check["real_transcripts_checked"] == manifest["summary"]["landed_frontier_episodes"]
    assert isinstance(tr_check["flash_medium_s28_steps"], int) and tr_check["flash_medium_s28_steps"] > 0
    for k, v in {"30": 112, "34": 83, "42": 74, "45": 156, "57": 76}.items():
        assert tr_check["carbon_hard_step_counts"][k] == v

    src_dir = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon" / "hard-s30"
    ep = json.loads((src_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines()[0])
    tr_txt = (src_dir / "transcripts" / "30.txt").read_text(encoding="utf-8")

    zip_export_root = tmp_path / "zip_exported_repo"
    shard = zip_export_root / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon" / "hard-s30"
    (shard / "transcripts").mkdir(parents=True)
    (shard / "episodes.jsonl").write_text(json.dumps(ep) + "\n", encoding="utf-8")
    (shard / "transcripts" / "30.txt").write_text(tr_txt, encoding="utf-8")
    assert not (zip_export_root / ".git").exists()

    zip_manifest = preflight.build_manifest(root=zip_export_root, enforce_expected_baseline=False)
    assert zip_manifest["summary"]["passed"] is True
    assert zip_manifest["waves"] == []

    unredacted_txt = tr_txt.replace("<2068 chars>", "Z" * 120, 1)
    (shard / "transcripts" / "30.txt").write_text(unredacted_txt, encoding="utf-8")
    scan = preflight.scan_replication_tree(zip_export_root, enforce_expected_baseline=False)
    assert not scan["errors"]
    chk_unredacted = preflight.check_transcript_redaction_and_infra(
        zip_export_root,
        scan["records_by_agent_tier"],
        enforce_expected_baseline=False,
    )
    assert chk_unredacted["passed"] is False
    assert any("unredacted thoughtSignature" in e for e in chk_unredacted["errors"])


def test_write_check_roundtrip_and_replay_filtering(tmp_path):
    out_manifest = tmp_path / "queue_manifest.json"
    assert preflight.main(["--manifest", str(out_manifest), "--check"]) == 1
    assert preflight.main(["--manifest", str(out_manifest), "--write"]) == 0
    assert preflight.main(["--manifest", str(out_manifest), "--check"]) == 0

    data = json.loads(out_manifest.read_text(encoding="utf-8"))
    data["summary"]["missing_frontier_episodes"] = 0
    out_manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert preflight.main(["--manifest", str(out_manifest), "--check"]) == 1

    src_ep_file = (
        ROOT
        / "results"
        / "frontier_replication"
        / "v1.4"
        / "opencode-gemini-4-carbon"
        / "hard-s30"
        / "episodes.jsonl"
    )
    ep_valid = json.loads(src_ep_file.read_text(encoding="utf-8").splitlines()[0])
    ep_invalid = {
        "tier": "hard",
        "seed": 31,
        "agent": "opencode:google/gemini-4-carbon",
        "steps": [],
        "score": 0.0,
        "accused": None,
        "correct": False,
        "final_day": 0,
        "end_reason": "error",
        "meta": {"valid": False, "error": "infra:provider_unavailable"},
    }
    fake_root = tmp_path / "synthetic_repo"
    shard = fake_root / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon" / "hard-s30"
    (shard / "transcripts").mkdir(parents=True)
    src_tr = src_ep_file.parent / "transcripts" / "30.txt"
    (shard / "transcripts" / "30.txt").write_text(src_tr.read_text(encoding="utf-8"), encoding="utf-8")
    (shard / "episodes.jsonl").write_text(
        json.dumps(ep_valid) + "\n" + json.dumps(ep_invalid) + "\n",
        encoding="utf-8",
    )

    scan = preflight.scan_replication_tree(fake_root, enforce_expected_baseline=False)
    assert not scan["errors"]
    c0 = next(c for c in scan["cohorts"] if c["cohort_id"] == "opencode-gemini-4-carbon-hard-30-59")
    assert c0["landed_seeds"] == [30]
    assert 31 in c0["missing_seeds"]
    assert c0["invalid_seeds"] == [31]

    tampered = dict(ep_valid, score=0.999999)
    (shard / "episodes.jsonl").write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    scan_bad = preflight.scan_replication_tree(fake_root, enforce_expected_baseline=False)
    assert any("replay mismatch" in e for e in scan_bad["errors"])


def test_task_w3_files_have_zero_comments_and_zero_em_dashes():
    for path in (SCRIPT_PATH, Path(__file__).resolve(), MANIFEST_PATH):
        txt = path.read_text(encoding="utf-8")
        assert HASH_CHAR not in txt, f"found hash comment char in {path}"
        assert EM_DASH not in txt, f"found em dash in {path}"
