from __future__ import annotations

import gzip
import importlib.util
import json
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_game_and_gateway_audit.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_game_and_gateway_audit.md"


def _load_module():
    spec = importlib.util.spec_from_file_location("integrity_game_and_gateway_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit_mod = _load_module()


@pytest.fixture(scope="module")
def game_play_result(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("w2_game_play")
    return audit_mod.audit_game_and_play_boundaries(scratch_root=scratch, quick=False)


@pytest.fixture(scope="module")
def gateway_wire_result(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("w2_gateway_wire")
    return audit_mod.audit_gateway_and_offline_replay(scratch_root=scratch, quick=True, wire_only=True)


@pytest.fixture(scope="module")
def artifacts_result():
    return audit_mod.audit_swarm_ladder_atlas_artifacts()


def test_play_cli_seed_spoofing_and_parser_boundaries(game_play_result):
    assert game_play_result["ok"] is True
    cli = game_play_result["play_cli"]
    assert cli["ok"] is True
    assert cli["judge_seeds_probed"] == 40
    assert cli["judge_seeds_refused_exit2"] == 40
    assert cli["cross_tier_judge_probed"] == 4
    assert cli["cross_tier_judge_refused_exit2"] == 4
    assert cli["heldout_seeds_probed"] == 30
    assert cli["heldout_seeds_refused_exit2"] == 30
    assert cli["low_dev_seeds_probed"] == 7
    assert cli["low_dev_seeds_refused_exit2"] == 7
    assert cli["high_int_seeds_probed"] == 8
    assert cli["high_int_seeds_refused_exit2"] == 8
    assert cli["arabic_judge_rc"] == 2
    assert cli["superscript_digit_rc"] == 1
    assert cli["superscript_digit_exc"] == "ValueError"
    assert cli["non_digit_probed"] == 9
    assert cli["non_digit_dev_fallback"] == 9
    assert cli["bad_arg_probed"] == 9
    assert cli["bad_arg_refused_exit2"] == 9
    assert cli["subproc_spoof_probed"] == 10
    assert cli["subproc_spoof_refused_exit2"] == 10
    assert cli["subproc_secret_leaks"] == 0
    assert cli["neg_sub_safe"] is True
    assert cli["valid_play_isolated"] is True
    assert cli["parser_adversarial_probed"] == 14
    assert cli["parser_adversarial_rejected"] == 14


def test_pyodide_game_build_and_ephemeral_secret_isolation(game_play_result):
    pg = game_play_result["pyodide_game"]
    assert pg["ok"] is True
    assert pg["site_total_files"] == 19
    assert pg["site_python_files"] == 15
    assert pg["manifest_matches_disk"] is True
    assert pg["forbidden_files_shipped"] == 0
    assert pg["secret_pattern_hits"] == 0
    assert pg["game_wrapper_allowed"] == "3/3"
    assert pg["game_wrapper_blocked"] == "15/15"
    assert pg["raw_env_tiers_allowed"] == 3
    assert pg["raw_env_tracks_blocked"] == 3
    assert pg["ephemeral_judge_secret_verified"] is True


def test_local_replay_gateway_wire_vectors_and_offline_manifests(gateway_wire_result):
    assert gateway_wire_result["ok"] is True
    assert gateway_wire_result["upstream_outbound_calls"] == 0
    assert gateway_wire_result["vectors_total"] == 10
    assert gateway_wire_result["vectors_held"] == 10
    assert gateway_wire_result["replay_cache_files_total"] == 614
    by_id = {v["id"]: v for v in gateway_wire_result["vectors"]}
    assert set(by_id) == {f"G{i:02d}" for i in range(1, 11)}
    for vid, row in by_id.items():
        assert row["held"] is True, (vid, row)
        assert "upstream=0" in row["detail"], (vid, row)

    rg = ROOT / "results" / "gemini"
    showcase = json.loads((rg / "replay" / "showcase.json").read_text(encoding="utf-8"))
    assert len(showcase["steps"]) == 5
    man_lad = json.loads((rg / "replay-ladder" / "manifest.json").read_text(encoding="utf-8"))
    man_show = json.loads((rg / "replay-ladder-showcase" / "manifest.json").read_text(encoding="utf-8"))
    assert sum(len(v) for v in man_lad["episodes"].values()) == 4
    assert sum(len(v) for v in man_show["episodes"].values()) == 6


def test_swarm_ladder_and_atlas_artifact_accounting(artifacts_result):
    assert artifacts_result["ok"] is True
    sc = artifacts_result["secret_scan"]
    assert sc["files_scanned"] == 818
    assert sc["gz_files_decompressed"] == 739
    assert sc["parse_errors"] == 0
    assert sc["credential_hits"] == 0

    swc = artifacts_result["swarm_counts"]
    assert swc["planned_primary"] == 96
    assert swc["lost_infra_invalid"] == 5
    assert swc["finished_primary"] == 91
    assert swc["whitebox_primary"] == 75
    assert swc["blackbox_primary"] == 16
    assert swc["mcp_reruns"] == 9
    assert swc["total_attempts"] == 100
    assert swc["per_tier"] == {"hard": 50, "medium": 50}
    assert swc["mcp_channel_attempts"] == 19
    assert swc["tool_calls"] == 4325
    assert swc["verified_exploits"] == 0
    assert swc["invariant_violations"] == 0
    assert swc["positive_control_exploits"] == "4/4"
    assert swc["counts_match_markdown"] is True

    pe = artifacts_result["positive_episodes"]
    assert pe["swarm_positive_total"] == 16
    assert pe["swarm_unaccounted"] == 0
    assert pe["review_w2b008_positive_justified"] == 1
    assert pe["positive_control_dev_seed_wins"] == 4
    assert pe["score_sign_invariant_ok"] is True
    assert len(pe["episodes"]) == 16
    assert all(ep["category"] and ep["evidence"] for ep in pe["episodes"])

    la = artifacts_result["ladder_and_atlas"]
    assert la["ladder_ok"] is True
    assert la["ladder_episodes"] == 357
    assert la["ladder_cells"] == 34
    assert la["ladder_ledger_calls"] == 19016
    assert la["ladder_run_ids"] == 320
    assert la["atlas_ok"] is True
    assert la["atlas_v2_episodes"] == 111
    assert la["atlas_v2_cohorts"] == 24
    assert la["atlas_v2_quotes_verified"] == "383/395"
    assert la["atlas_v2_step_verified"] == "369/395"
    assert la["atlas_v2_localisation"] == "8/8"


def test_secret_and_parse_scanner_catches_planted_violations(tmp_path):
    fake_google_key = "AIza" + "B" * 35
    with gzip.open(tmp_path / "leaked.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"leaked": fake_google_key}, fh)
    (tmp_path / "header_leak.json").write_text(
        '{"headers": {"x-goog-api-key": "gateway-token-secret-value"}}\n',
        encoding="utf-8",
    )
    with gzip.open(tmp_path / "broken.json.gz", "wt", encoding="utf-8") as fh:
        fh.write("{broken_json")
    (tmp_path / "secret_bytes.txt").write_bytes(b"prefix-SUPER_SECRET_SALT_VALUE_1234-suffix")

    res = audit_mod.scan_gemini_tree(tmp_path, repo_secrets=[b"SUPER_SECRET_SALT_VALUE_1234"])
    kinds = {(h["file"], h["kind"]) for h in res["secret_hits"]}
    assert ("leaked.json.gz", "google_api_key") in kinds
    assert ("header_leak.json", "gateway_header_leak") in kinds
    assert ("secret_bytes.txt", "repo_secret_value") in kinds
    assert len(res["parse_errors"]) == 1
    assert res["parse_errors"][0].startswith("broken.json.gz:")


def test_report_and_owned_files_integrity(game_play_result, gateway_wire_result, artifacts_result):
    synth_full = {
        "ok": True,
        "git_sha": "62d258cd",
        "quick": False,
        "scratch_root": "/localscratch/job_44578/w2",
        "elapsed_s": 10.0,
        "live_llm_calls": 0,
        "part_a_game_and_play": game_play_result,
        "part_b_gateway_and_replay": {
            **gateway_wire_result,
            "vectors_total": 12,
            "vectors_held": 12,
            "replayed_episodes_verified": 11,
        },
        "part_c_artifacts": artifacts_result,
    }
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_model = "-".join(("gemini", "3.5", "flash"))

    rendered = audit_mod.render_markdown_report(synth_full)
    assert "Surface A (`canary/play.py` + `game/build.py`):" in rendered
    assert em_dash not in rendered and en_dash not in rendered
    assert forbidden_model not in rendered.lower()

    assert REPORT_PATH.is_file()
    report_txt = REPORT_PATH.read_text(encoding="utf-8")
    for expected in (
        "40/40",
        "30/30",
        "10/10",
        "12/12",
        "614",
        "818",
        "739",
        "16/16",
        "357",
        "111",
        "w2b-008-reward_hacker",
    ):
        assert expected in report_txt, expected

    for p in (SCRIPT_PATH, REPORT_PATH, Path(__file__).resolve()):
        txt = p.read_text(encoding="utf-8")
        assert em_dash not in txt and en_dash not in txt, p
        assert forbidden_model not in txt.lower(), p

    for py_path in (SCRIPT_PATH, Path(__file__).resolve()):
        with open(py_path, "rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], (py_path, comments)
