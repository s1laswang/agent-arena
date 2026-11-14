from __future__ import annotations

import copy
import importlib.util
import json
import os
import sys
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


def test_real_repo_manifest_and_check_flag():
    rc = preflight.main(["--check"])
    assert rc == 0
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["tiers_version"] == "v1.4"
    assert manifest["summary"]["passed"] is True
    assert manifest["preflight"]["passed"] is True
    assert manifest["preflight"]["zero_live_llm_calls"] is True
    assert manifest["summary"]["replication_total_episodes"] == 304
    assert manifest["summary"]["replication_replay_verified_episodes"] == 304

    by_id = {c["cohort_id"]: c for c in manifest["cohorts"]}
    c_carbon = by_id["opencode-gemini-4-carbon-hard-30-59"]
    assert c_carbon["landed_seeds"] == [30, 34, 42, 45, 57]
    assert c_carbon["landed_count"] == 5
    assert c_carbon["missing_count"] == 25
    assert c_carbon["missing_seeds"] == [
        31, 32, 33, 35, 36, 37, 38, 39, 40, 41,
        43, 44, 46, 47, 48, 49, 50, 51, 52, 53,
        54, 55, 56, 58, 59,
    ]

    c_flash_med = by_id["opencode-gemini-3.5-flash-medium-0-29"]
    assert c_flash_med["landed_seeds"] == [s for s in range(30) if s != 28]
    assert c_flash_med["landed_count"] == 29
    assert c_flash_med["missing_count"] == 1
    assert c_flash_med["missing_seeds"] == [28]

    c_flash_hard = by_id["opencode-gemini-3.5-flash-hard-30-59"]
    assert c_flash_hard["landed_seeds"] == []
    assert c_flash_hard["landed_count"] == 0
    assert c_flash_hard["missing_count"] == 30
    assert c_flash_hard["missing_seeds"] == list(range(30, 60))

    waves = manifest["waves"]
    assert len(waves) == 20
    assert all(1 <= w["worker_count"] <= 3 and w["ram_safe"] is True for w in waves)

    queued_by_cohort: dict[str, list[int]] = {}
    for w in waves:
        assert [j["seed"] for j in w["jobs"]] == w["seeds"]
        queued_by_cohort.setdefault(w["cohort_id"], []).extend(w["seeds"])

    for cid, c in by_id.items():
        q = queued_by_cohort.get(cid, [])
        assert q == c["missing_seeds"]
        assert set(q).isdisjoint(set(c["landed_seeds"]))
        lo, hi = c["seed_range"]
        assert sorted(q + c["landed_seeds"]) == list(range(lo, hi + 1))


def test_cli_commands_and_validator_rejects_bad_waves():
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    val = preflight.validate_wave_commands(manifest["waves"])
    assert val["passed"] is True
    assert val["commands_validated"] == 56

    bad_workers = copy.deepcopy(manifest["waves"][:1])
    bad_workers[0]["worker_count"] = 4
    assert preflight.validate_wave_commands(bad_workers)["passed"] is False

    bad_flag = copy.deepcopy(manifest["waves"][:1])
    bad_flag[0]["jobs"][0]["command"] += " --workers 2"
    res_flag = preflight.validate_wave_commands(bad_flag)
    assert res_flag["passed"] is False
    assert any("invalid flags" in e for e in res_flag["errors"])

    bad_path = copy.deepcopy(manifest["waves"][:1])
    bad_path[0]["jobs"][0]["command"] = bad_path[0]["jobs"][0]["command"].replace(
        "PATH=/home/silas/momin/bin:$PATH ", ""
    )
    assert preflight.validate_wave_commands(bad_path)["passed"] is False

    bad_timeout = copy.deepcopy(manifest["waves"][:1])
    bad_timeout[0]["jobs"][0]["command"] = bad_timeout[0]["jobs"][0]["command"].replace(
        "--timeout 3600", "--timeout 2400"
    )
    assert preflight.validate_wave_commands(bad_timeout)["passed"] is False

    with pytest.raises(ValueError):
        preflight.partition_into_waves(manifest["cohorts"], max_workers_per_wave=4)


def test_security_and_isolation_preflight_controls(monkeypatch):
    env_before = dict(os.environ)
    assert preflight.check_tiers_gate()["passed"] is True
    assert preflight.check_opencode_config_isolation()["passed"] is True
    assert preflight.check_child_env_stripping()["passed"] is True
    assert dict(os.environ) == env_before
    assert preflight.check_workdir_isolation(ROOT)["passed"] is True

    monkeypatch.setattr(opencode_run, "PERMISSION", {"*": "allow"})
    res_perm = preflight.check_opencode_config_isolation()
    assert res_perm["passed"] is False
    monkeypatch.undo()

    monkeypatch.setattr(common, "child_env", lambda: {"GEMINI_API_KEY": "leaked", "PWD": ""})
    res_env = preflight.check_child_env_stripping()
    assert res_env["passed"] is False


def test_carbon_step_reconstruction_and_transcript_negative_controls(tmp_path):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    tr_check = manifest["preflight"]["checks"]["transcript_redaction_infra_and_steps"]
    assert tr_check["passed"] is True
    assert tr_check["real_transcripts_checked"] == 34
    assert tr_check["carbon_hard_step_counts"] == {
        "30": 112,
        "34": 83,
        "42": 74,
        "45": 156,
        "57": 76,
    }

    src_dir = ROOT / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon" / "hard-s30"
    ep = json.loads((src_dir / "episodes.jsonl").read_text(encoding="utf-8").splitlines()[0])
    tr_txt = (src_dir / "transcripts" / "30.txt").read_text(encoding="utf-8")

    fake_root = tmp_path / "repo"
    shard = fake_root / "results" / "frontier_replication" / "v1.4" / "opencode-gemini-4-carbon" / "hard-s30"
    (shard / "transcripts").mkdir(parents=True)
    (shard / "episodes.jsonl").write_text(json.dumps(ep) + "\n", encoding="utf-8")
    unredacted_txt = tr_txt.replace("<2068 chars>", "Z" * 120, 1)
    (shard / "transcripts" / "30.txt").write_text(unredacted_txt, encoding="utf-8")

    scan = preflight.scan_replication_tree(fake_root, enforce_expected_baseline=False)
    assert not scan["errors"]
    chk_unredacted = preflight.check_transcript_redaction_and_infra(
        fake_root,
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
