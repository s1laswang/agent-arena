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
EN_DASH = "\u2013"


def _load_preflight():
    spec = importlib.util.spec_from_file_location("frontier_queue_preflight", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


preflight = _load_preflight()


@pytest.fixture(scope="module")
def repo_manifest() -> dict:
    assert preflight.main(["--check", "--validate-template-waves"]) == 0
    assert MANIFEST_PATH.stat().st_size <= 50 * 1024
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_real_repo_manifest_reconciliation_and_provenance(repo_manifest):
    manifest = repo_manifest
    assert manifest["schema_version"] == 1
    assert manifest["tiers_version"] == "v1.4"
    assert manifest["upstream_reconciled_commit"] == "5f9b3297"

    s = manifest["summary"]
    assert s["passed"] is True
    assert s["pure_cpu_mode"] is True
    assert manifest["preflight"]["passed"] is True
    assert manifest["preflight"]["zero_live_llm_calls"] is True
    assert s["committed_v14_total_episodes"] == 472
    assert s["committed_v14_replay_verified_episodes"] == 472
    assert s["replication_total_episodes"] == 305
    assert s["replication_replay_verified_episodes"] == 305
    assert s["combined_v14_total_episodes"] == 777
    assert s["combined_v14_replay_verified_episodes"] == 777
    assert s["target_frontier_episodes"] == 90
    assert s["landed_frontier_episodes"] == 35
    assert s["missing_frontier_episodes"] == 55
    assert s["g1_committed_ext_episodes"] == 2
    assert s["g1_committed_ext_provider_quota_excluded"] == 31
    assert s["g1_fr8_replication_episodes"] == 5
    assert s["g1_combined_distinct_hard_ext_episodes"] == 6
    assert s["g1_combined_remaining_hard_ext_episodes"] == 24
    assert s["gpt55_committed_hard_episodes"] == 30
    assert s["fr8_dispatch_active_episodes"] == 0
    assert s["wave_count"] == 0
    assert s["max_workers_in_any_wave"] == 0
    assert s["template_wave_count"] == 19
    assert s["template_commands_validated"] == 55
    assert s["cross_family_template_wave_count"] == 20
    assert s["cross_family_template_commands_validated"] == 60
    assert s["gpt55_synthetic_template_commands_validated"] == 30
    assert manifest["waves"] == []

    rec = manifest["corpus_reconciliation"]
    assert rec["committed_v14"]["total_episodes"] == 472
    assert rec["committed_v14"]["replay_verified_episodes"] == 472
    assert rec["fr8_replication_v14"]["total_episodes"] == 305
    assert rec["fr8_replication_v14"]["replay_verified_episodes"] == 305
    assert rec["combined_v14_total_episodes"] == 777
    assert rec["combined_v14_replay_verified_episodes"] == 777
    assert rec["gpt55_hard_0_29_committed"] == {
        "run_dir": "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
        "seed_range": [0, 29],
        "target_count": 30,
        "landed_count": 30,
        "remaining_count": 0,
        "clean_unended_rc0_seeds": [0, 17],
        "infra_excluded": 0,
        "pre_registered_commit": "cf394894",
        "committed_commit": "ca0a0dc0",
    }

    ext = rec["carbon_hard_30_59_extension"]
    assert ext["committed_g1_partial"] == {
        "run_dir": "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
        "landed_seeds": [34, 37],
        "n": 2,
        "provider_quota_excluded": 31,
    }
    assert ext["fr8_replication"]["landed_seeds"] == [30, 34, 42, 45, 57]
    assert ext["fr8_replication"]["n"] == 5
    assert ext["combined_distinct_landed_seeds"] == [30, 34, 37, 42, 45, 57]
    assert ext["combined_distinct_count"] == 6
    assert ext["shared_overlap_seeds"] == [34]
    assert ext["combined_remaining_count"] == 24

    prov = manifest["provenance_honesty"]
    assert prov["panel_doc"] == "docs/agents/PANEL-0500.md"
    assert prov["panel_status_commit"] == "8b9afa61"
    assert prov["panel_fix_a_commit"] == "92708834"
    assert prov["panel_fix_d_commit"] == "1bc3e281"
    p_cohorts = prov["cohorts"]
    assert p_cohorts["primary_carbon_0_29"]["classification"] == "post_hoc_lock"
    assert p_cohorts["primary_carbon_0_29"]["episodes_commit"] == "8fd4dec"
    assert p_cohorts["primary_carbon_0_29"]["lock_commit"] == "671ed96"
    assert p_cohorts["primary_carbon_0_29"]["lock_delay_s"] == 28
    assert p_cohorts["g1_carbon_hard_30_59"]["classification"] == "pre_registered"
    assert p_cohorts["g1_carbon_hard_30_59"]["pre_registered_commit"] == "f9fb7a4a"
    assert p_cohorts["g2_argon_hydrogen_hard_0_29"]["classification"] == "pre_registered"
    assert p_cohorts["g2_argon_hydrogen_hard_0_29"]["pre_registered_commit"] == "f9fb7a4a"
    assert p_cohorts["gpt_5_5_hard_0_29"]["classification"] == "pre_registered"
    assert p_cohorts["gpt_5_5_hard_0_29"]["pre_registered_commit"] == "cf394894"
    assert p_cohorts["gpt_5_5_hard_0_29"]["committed_commit"] == "ca0a0dc0"
    assert p_cohorts["gpt_5_5_hard_0_29"]["committed_dir"] == "data/runs/committed/v1.4/opencode-gpt-5.5/hard"
    assert p_cohorts["gpt_5_5_hard_0_29"]["committed_n"] == 30
    assert p_cohorts["gpt_5_5_hard_0_29"]["committed_infra_excluded"] == 0
    assert p_cohorts["gpt_5_5_hard_0_29"]["clean_unended_rc0_seeds"] == [0, 17]

    sessions = manifest["gemini_sessions"]
    assert sessions["source_doc"] == "docs/agents/GEMINI-SESSIONS.md"
    assert sessions["source_commit"] == "f9fb7a4a"
    assert sessions["pure_cpu_mode"] is True
    assert sessions["fr8_live_gemini_dispatch_enabled"] is False
    assert sessions["g1_carbon_hard_ext60"]["fr8_landed_seeds"] == [30, 34, 42, 45, 57]
    assert sessions["g1_carbon_hard_ext60"]["committed_landed_seeds"] == [34, 37]
    assert sessions["g1_carbon_hard_ext60"]["committed_provider_quota_excluded"] == 31
    assert sessions["g1_carbon_hard_ext60"]["combined_distinct_landed_seeds"] == [30, 34, 37, 42, 45, 57]
    assert sessions["g1_carbon_hard_ext60"]["remaining_count"] == 25
    assert sessions["g1_carbon_hard_ext60"]["combined_remaining_count"] == 24
    assert sessions["g2_frontier_families_hard_0_29"]["models"] == [
        "google/gemini-4-argon",
        "google/gemini-4-hydrogen",
    ]
    assert sessions["gpt55_hard_0_29"]["committed_landed_count"] == 30
    assert sessions["gpt55_hard_0_29"]["remaining_count"] == 0
    assert sessions["gpt55_hard_0_29"]["clean_unended_rc0_seeds"] == [0, 17]

    by_id = {c["cohort_id"]: c for c in manifest["cohorts"]}
    c_carbon = by_id["opencode-gemini-4-carbon-hard-30-59"]
    assert c_carbon["landed_seeds"] == [30, 34, 42, 45, 57]
    assert c_carbon["landed_count"] == 5
    assert c_carbon["missing_count"] == 25
    assert c_carbon["fr8_dispatch_enabled"] is False

    c_flash_med = by_id["opencode-gemini-3.5-flash-medium-0-29"]
    assert c_flash_med["landed_seeds"] == list(range(30))
    assert c_flash_med["landed_count"] == 30
    assert c_flash_med["missing_count"] == 0
    assert c_flash_med["fr8_dispatch_enabled"] is False

    c_flash_hard = by_id["opencode-gemini-3.5-flash-hard-30-59"]
    assert c_flash_hard["landed_count"] == 0
    assert c_flash_hard["missing_count"] == 30
    assert c_flash_hard["fr8_dispatch_enabled"] is False

    tmpl_by_id = {c["cohort_id"]: c for c in manifest["template_cohorts"]}
    assert set(tmpl_by_id.keys()) == {
        "opencode-gemini-4-argon-hard-0-29",
        "opencode-gemini-4-hydrogen-hard-0-29",
        "opencode-openai-gpt-5.5-hard-0-29",
    }
    gpt55 = tmpl_by_id["opencode-openai-gpt-5.5-hard-0-29"]
    assert gpt55["agent"] == "opencode:openai/gpt-5.5"
    assert gpt55["model"] == "openai/gpt-5.5"
    assert gpt55["tier"] == "hard"
    assert gpt55["seed_range"] == [0, 29]
    assert gpt55["target_count"] == 30
    assert gpt55["landed_count"] == 30
    assert gpt55["missing_count"] == 0
    assert gpt55["timeout_s"] == 7200
    assert gpt55["max_spend_usd"] == 200.0
    assert gpt55["stop_launch_at"] == "08:15"
    assert gpt55["hard_drop_at"] == "08:45"
    assert gpt55["pre_registered_commit"] == "cf394894"
    assert gpt55["committed_commit"] == "ca0a0dc0"
    assert gpt55["committed_dir"] == "data/runs/committed/v1.4/opencode-gpt-5.5/hard"
    assert gpt55["execution_owner"] == "silas_ca0a0dc0_committed_complete"
    assert gpt55["fr8_dispatch_enabled"] is False


def test_template_wave_validation_and_dispatch_gating(repo_manifest):
    manifest = repo_manifest
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

    gpt55_reconciled_waves = preflight.build_gpt55_template_waves()
    assert gpt55_reconciled_waves == []
    assert preflight.validate_wave_commands(gpt55_reconciled_waves)["commands_validated"] == 0

    gpt55_waves = preflight.build_gpt55_template_waves(include_committed=True)
    assert len(gpt55_waves) == 10
    val_gpt55 = preflight.validate_wave_commands(gpt55_waves)
    assert val_gpt55["passed"] is True
    assert val_gpt55["commands_validated"] == 30
    for w in gpt55_waves:
        assert w["cohort_id"] == "opencode-openai-gpt-5.5-hard-0-29"
        assert w["timeout_s"] == 7200
        assert w["fr8_dispatch_enabled"] is False
        for j in w["jobs"]:
            assert "--model openai/gpt-5.5" in j["command"]
            assert "--timeout 7200" in j["command"]

    cross_waves = preflight.build_cross_family_template_waves()
    assert len(cross_waves) == 20
    assert preflight.validate_wave_commands(cross_waves)["commands_validated"] == 60
    assert all(w["cohort_id"] != "opencode-openai-gpt-5.5-hard-0-29" for w in cross_waves)

    cross_syn_waves = preflight.build_cross_family_template_waves(include_committed=True)
    assert len(cross_syn_waves) == 30
    assert preflight.validate_wave_commands(cross_syn_waves)["commands_validated"] == 90

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


def test_opencode_run_and_gemini_runner_cf394894_parity(tmp_path, monkeypatch):
    gr_check = preflight.check_gemini_runner_controls()
    assert gr_check["passed"] is True
    assert gr_check["zero_live_subprocesses"] is True

    monkeypatch.setenv("CANARY_ALLOW_DEV", "1")
    monkeypatch.delenv("GOOGLE_GENERATIVE_AI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "synthetic-google-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-anthropic-key")

    seen_envs: dict[str, dict[str, str]] = {}

    class FakeServer:
        def __init__(self, tier: str, seed: int):
            self.tier = tier
            self.seed = seed
            self.token = "SYNTHETICLEDGERTOKEN"
            self.url = "http://127.0.0.1:19999/mcp"

        def start(self, **kwargs):
            return self

        def ledger(self):
            return {
                "score": 0.75,
                "done": True,
                "end_reason": "accused",
                "accused": "e01",
                "accused_correct": True,
                "tier": self.tier,
                "final_day": 6,
                "V": 0.75,
                "ledger": [],
            }

        def stop(self):
            pass

    event_stream = json.dumps(
        {
            "type": "step_finish",
            "part": {
                "type": "step-finish",
                "reason": "stop",
                "tokens": {"input": 100, "output": 10, "reasoning": 0, "cache": {"read": 0, "write": 0}},
                "cost": 0.01,
            },
        }
    )

    for label, model_id in (("google", "google/gemini-4-carbon"), ("openai", "openai/gpt-5.5")):
        def fake_runner(argv, cwd, env, _label=label, **kwargs):
            seen_envs[_label] = dict(env)
            return type("Proc", (), {"returncode": 0, "stdout": event_stream, "stderr": ""})()

        spec = common.RunSpec(
            f"opencode:{model_id}",
            "hard",
            [0],
            tmp_path / label,
            timeout_s=7200 if label == "openai" else 3600,
            child_env_extra=opencode_run.child_env_extra(model_id),
        )
        res = common.run_seeds(
            spec,
            lambda wd, prompt, url, _m=model_id: opencode_run.build_cmd(wd, prompt, _m, url),
            opencode_run.FILES,
            runner=fake_runner,
            server_factory=FakeServer,
        )
        assert res[0].score == 0.75

    g_env = seen_envs["google"]
    assert g_env["GOOGLE_GENERATIVE_AI_API_KEY"] == "synthetic-gemini-key"
    for k in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        assert k not in g_env

    o_env = seen_envs["openai"]
    assert o_env["OPENAI_API_KEY"] == "synthetic-openai-key"
    for k in ("GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        assert k not in o_env


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

    inside_end = preflight.check_carbon_quota_blackout("2026-11-15T06:14:59Z")
    assert inside_end["allowed"] is False
    assert inside_end["in_blackout_window"] is True

    after = preflight.check_carbon_quota_blackout("2026-11-15T06:15:00Z")
    assert after["allowed"] is True
    assert after["in_blackout_window"] is False

    epoch_start = int(datetime(2026, 11, 15, 4, 30, 0, tzinfo=timezone.utc).timestamp())
    epoch_after = int(datetime(2026, 11, 15, 6, 15, 0, tzinfo=timezone.utc).timestamp())
    assert preflight.check_carbon_quota_blackout(epoch_start)["allowed"] is False
    assert preflight.check_carbon_quota_blackout(epoch_after)["allowed"] is True

    for exempt_model in (
        "gemini-4-argon",
        "google/gemini-4-argon",
        "gemini-4-hydrogen",
        "google/gemini-4-hydrogen",
        "gpt-5.5",
        "openai/gpt-5.5",
        "opencode:openai/gpt-5.5",
    ):
        allowed_res = preflight.check_carbon_quota_blackout("2026-11-15T05:30:00Z", model=exempt_model)
        assert allowed_res["allowed"] is True
        assert allowed_res["in_blackout_window"] is True
        assert allowed_res["is_carbon_model"] is False
        if "gpt-5.5" in exempt_model:
            assert allowed_res["model"] == "openai/gpt-5.5"

    assert preflight.main(["--check-blackout", "2026-11-15T05:30:00Z"]) == 1
    assert preflight.main(["--check-blackout", "2026-11-15T05:30:00Z", "--model", "openai/gpt-5.5"]) == 0
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


def test_all_transcripts_g1_ext_and_zip_export_safety(repo_manifest, tmp_path):
    manifest = repo_manifest
    tr_check = manifest["preflight"]["checks"]["transcript_redaction_infra_and_steps"]
    assert tr_check["passed"] is True
    assert tr_check["real_transcripts_checked"] == 35
    assert tr_check["committed_g1_ext_transcripts_checked"] == 2
    assert tr_check["committed_gpt55_transcripts_checked"] == 30
    assert tr_check["committed_gpt55_total_steps"] > 0
    assert tr_check["committed_g1_ext_step_counts"] == {"34": 51, "37": 64}
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

    out_manifest = tmp_path / "queue_manifest.json"
    assert preflight.main(["--root", str(fake_root), "--manifest", str(out_manifest), "--check"]) == 1
    assert preflight.main(["--root", str(fake_root), "--manifest", str(out_manifest), "--write"]) == 0
    assert preflight.main(["--root", str(fake_root), "--manifest", str(out_manifest), "--check"]) == 0

    data = json.loads(out_manifest.read_text(encoding="utf-8"))
    data["summary"]["missing_frontier_episodes"] = 0
    out_manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    assert preflight.main(["--root", str(fake_root), "--manifest", str(out_manifest), "--check"]) == 1

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


def test_gpt55_clean_unended_replay_verification():
    gpt55_ep_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    eps = [json.loads(line) for line in gpt55_ep_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(eps) == 30
    by_seed = {int(e["seed"]): e for e in eps}
    for s in (0, 17):
        ep = by_seed[s]
        assert ep["accused"] is None
        assert float(ep["score"]) == 0.0
        assert int(ep["final_day"]) == 0
        assert ep["meta"]["rc"] == 0
        assert preflight.verify_episode_replay(ep) is True

        bad_timeout = copy.deepcopy(ep)
        bad_timeout["meta"]["rc"] = "timeout"
        assert preflight.verify_episode_replay(bad_timeout) is False

        bad_rc = copy.deepcopy(ep)
        bad_rc["meta"]["rc"] = 1
        assert preflight.verify_episode_replay(bad_rc) is False

        bad_bool = copy.deepcopy(ep)
        bad_bool["meta"]["rc"] = False
        assert preflight.verify_episode_replay(bad_bool) is False

        bad_day = copy.deepcopy(ep)
        bad_day["final_day"] = 1
        assert preflight.verify_episode_replay(bad_day) is False

        bad_score = copy.deepcopy(ep)
        bad_score["score"] = 0.25
        assert preflight.verify_episode_replay(bad_score) is False


def test_task_w3_files_have_zero_comments_zero_em_dashes_and_size_cap():
    assert MANIFEST_PATH.stat().st_size <= 50 * 1024
    for path in (SCRIPT_PATH, Path(__file__).resolve(), MANIFEST_PATH):
        txt = path.read_text(encoding="utf-8")
        assert HASH_CHAR not in txt, f"found hash comment char in {path}"
        assert EM_DASH not in txt, f"found em dash in {path}"
        assert EN_DASH not in txt, f"found en dash in {path}"
