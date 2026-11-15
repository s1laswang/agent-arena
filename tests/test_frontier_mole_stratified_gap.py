"""Tests for scripts/frontier_mole_stratified_gap.py, mole_stratified_gap.json, and frontier_mole_stratified_gap_v14.md."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "frontier_mole_stratified_gap.py"
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "mole_stratified_gap.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_mole_stratified_gap_v14.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("frontier_mole_stratified_gap", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


fms = _load_module()


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _make_gitless_root(tmp_path: Path, name: str = "gitless_root", link_gap_md: bool = True) -> Path:
    syn_root = tmp_path / name
    (syn_root / "data" / "runs" / "committed").mkdir(parents=True)
    (syn_root / "results" / "frontier_replication").mkdir(parents=True)
    (syn_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        syn_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "frontier_replication" / "v1.4",
        syn_root / "results" / "frontier_replication" / "v1.4",
    )
    if link_gap_md:
        os.symlink(
            ROOT / "docs" / "reports" / "gap.md",
            syn_root / "docs" / "reports" / "gap.md",
        )
    assert not (syn_root / ".git").exists()
    return syn_root


@pytest.fixture(scope="module")
def computed_audit():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    env_before = dict(os.environ)
    try:
        out = fms.compute_audit(root=ROOT, verify_replays=True, enforce_expected_counts=True)
    finally:
        mp.undo()
    assert dict(os.environ) == env_before
    return out


def test_check_cli_offline_zero_subprocess_and_size_cap(computed_audit, monkeypatch, capsys):
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(
        fms,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: copy.deepcopy(computed_audit),
    )
    assert fms.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert (
        "OK mole_stratified_gap=PASS worlds=90 committed_replays=472 "
        "replication_replays=305 combined_replays=777"
    ) in out
    assert fms.MAX_JSON_BYTES == 45_000
    assert JSON_PATH.stat().st_size < 45_000
    assert JSON_PATH.stat().st_size <= fms.MAX_JSON_BYTES
    assert JSON_PATH.read_bytes() == fms.serialize_audit_json(computed_audit).encode("utf-8")
    assert MD_PATH.read_bytes() == fms.render_markdown(computed_audit).encode("utf-8")


def test_gitless_root_write_check_roundtrip_and_byte_identity(computed_audit, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    no_git_root = _make_gitless_root(tmp_path, name="zip_export_tree", link_gap_md=True)
    out_json = tmp_path / "out" / "mole_stratified_gap.json"
    out_md = tmp_path / "out" / "frontier_mole_stratified_gap_v14.md"

    monkeypatch.setattr(
        fms,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: fms.compute_audit.__wrapped__(root)
        if hasattr(fms.compute_audit, "__wrapped__")
        else copy.deepcopy(computed_audit),
    )
    assert fms.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert fms.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert out_json.is_file() and out_md.is_file()
    assert out_json.stat().st_size < 45_000
    assert out_json.read_bytes() == JSON_PATH.read_bytes()
    assert out_md.read_bytes() == MD_PATH.read_bytes()
    assert fms.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0


def test_gitless_real_compute_without_git_dir(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    syn_root = tmp_path / "mini_gitless"
    rel_dirs = (
        ("data/runs/committed/v1.4/reference", {"solver"}, {0, 1, 2, 5}),
        ("data/runs/committed/v1.4/reference/solver-hard-seeds30to59", {"solver"}, {30, 34}),
        (
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
            {"opencode:google/gemini-4-carbon"},
            {0, 1, 2, 5},
        ),
        (
            "data/runs/committed/v1.4/inproc-gemini-4-carbon/hard",
            {"gemini:gemini-4-carbon"},
            {0, 1, 2, 5},
        ),
        (
            "data/runs/committed/v1.4/opencode-gpt-5.5/hard",
            {"opencode:openai/gpt-5.5"},
            {0, 1, 2, 5},
        ),
        (
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium",
            {"opencode:google/gemini-4-carbon"},
            {0, 1, 2, 5},
        ),
        (
            "data/runs/committed/v1.4/inproc-gemini-4-carbon/medium",
            {"gemini:gemini-4-carbon"},
            {0, 1, 2, 5},
        ),
        (
            "data/runs/committed/v1.4/opencode-gemini-4-carbon-ext/hard",
            {"opencode:google/gemini-4-carbon"},
            {34},
        ),
        (
            "results/frontier_replication/v1.4/opencode-gemini-3.5-flash",
            {"opencode:google/gemini-3.5-flash"},
            {0, 1, 2, 5},
        ),
        (
            "results/frontier_replication/v1.4/reference/grok_tactics-hard-seeds30to59",
            {"grok_tactics"},
            {30, 34},
        ),
        (
            "results/frontier_replication/v1.4/reference/heuristic-hard-seeds30to59",
            {"heuristic"},
            {30, 34},
        ),
        (
            "results/frontier_replication/v1.4/opencode-gemini-4-carbon",
            {"opencode:google/gemini-4-carbon"},
            {30, 34},
        ),
    )
    for rel_dir, allowed_agents, allowed_seeds in rel_dirs:
        dst = syn_root / rel_dir
        dst.mkdir(parents=True, exist_ok=True)
        picked: list[str] = []
        for ep_file in sorted((ROOT / rel_dir).rglob("episodes.jsonl")):
            if "solver-hard-seeds30to59" in str(ep_file) and "solver-hard-seeds30to59" not in rel_dir:
                continue
            for line in ep_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                ep = json.loads(line)
                if (
                    ep.get("agent") in allowed_agents
                    and int(ep["seed"]) in allowed_seeds
                    and (ep.get("meta") or {}).get("valid") is not False
                ):
                    picked.append(line)
        (dst / "episodes.jsonl").write_text("\n".join(picked) + "\n", encoding="utf-8")

    assert not (syn_root / ".git").exists()
    audit_no_git = fms.compute_audit(root=syn_root, verify_replays=True, enforce_expected_counts=False)
    assert audit_no_git["zero_git_dependency"] is True
    assert audit_no_git["zero_live_api_calls"] is True
    assert audit_no_git["summary"]["worlds_extracted"] == 10
    assert audit_no_git["replay_verification"]["committed_v14"]["mismatches"] == 0
    assert audit_no_git["replay_verification"]["committed_v14"]["clean_rc0_non_accuse_zero_day_seeds"] == [0]
    assert audit_no_git["replay_verification"]["replication_v14"]["mismatches"] == 0
    assert len(fms.serialize_audit_json(audit_no_git).encode("utf-8")) < 45_000
    assert "Canary v1.4 Mole-Archetype" in fms.render_markdown(audit_no_git)


def test_provenance_honesty_and_replay_invariants(computed_audit):
    assert computed_audit["schema_version"] == "v1.4-frontier-mole-stratified-gap-1"
    assert computed_audit["tiers_version"] == "v1.4"
    assert computed_audit["zero_live_api_calls"] is True
    assert computed_audit["zero_git_dependency"] is True
    assert computed_audit["stratum_metric_columns"] == list(fms.STRATUM_METRIC_COLUMNS)

    prov = computed_audit["provenance_and_locks"]
    assert prov["primary_0_29_lock"]["classification"] == "post_hoc_lock"
    assert prov["primary_0_29_lock"]["episodes_commit"] == "8fd4dec"
    assert prov["primary_0_29_lock"]["lock_commit"] == "671ed96"
    assert prov["primary_0_29_lock"]["lock_delay_s"] == 28
    assert "post-hoc lock" in prov["primary_0_29_lock"]["note"].lower()

    assert prov["g1_hard_30_59_extension"]["classification"] == "pre_registered"
    assert prov["g1_hard_30_59_extension"]["prereg_commit"] == "f9fb7a4a"
    assert prov["g1_hard_30_59_extension"]["completed_seeds"] == [34, 37]
    assert prov["g1_hard_30_59_extension"]["n"] == 2

    assert prov["gpt_5_5_hard_0_29"]["classification"] == "pre_registered"
    assert prov["gpt_5_5_hard_0_29"]["prereg_commit"] == "cf394894"
    assert prov["gpt_5_5_hard_0_29"]["results_commit"] == "ca0a0dc0"
    assert prov["gpt_5_5_hard_0_29"]["upstream_sync_commit"] == "5f9b3297"
    assert prov["gpt_5_5_hard_0_29"]["timeout_cap_s"] == 7200
    assert prov["gpt_5_5_hard_0_29"]["spend_cap_usd"] == 200
    assert prov["gpt_5_5_hard_0_29"]["committed_v14_episodes"] == 30
    assert prov["gpt_5_5_hard_0_29"]["clean_rc0_non_accuse_zero_day_seeds"] == [0, 17]
    assert prov["step_error_detail_compat"]["commit"] == "1bc3e281"

    rv = computed_audit["replay_verification"]
    assert rv["committed_v14"]["total"] == 472
    assert rv["committed_v14"]["verified"] == 472
    assert rv["committed_v14"]["mismatches"] == 0
    assert rv["committed_v14"]["step_mismatches"] == 0
    assert rv["committed_v14"]["duplicates"] == 0
    assert rv["committed_v14"]["pre_1bc3e281_detail_normalized_steps"] == 321
    assert rv["committed_v14"]["unwrapped_mcp_error_steps"] == 84
    assert rv["committed_v14"]["clean_rc0_non_accuse_zero_day_seeds"] == [0, 17]

    assert rv["replication_v14"]["total"] == 305
    assert rv["replication_v14"]["verified"] == 305
    assert rv["replication_v14"]["mismatches"] == 0
    assert rv["replication_v14"]["step_mismatches"] == 0
    assert rv["replication_v14"]["duplicates"] == 0
    assert rv["replication_v14"]["pre_1bc3e281_detail_normalized_steps"] == 156
    assert rv["replication_v14"]["unwrapped_mcp_error_steps"] == 24
    assert rv["replication_v14"]["clean_rc0_non_accuse_zero_day_seeds"] == []

    summ = computed_audit["summary"]
    assert summ["worlds_extracted"] == 90
    assert summ["committed_v14_total"] == 472
    assert summ["committed_v14_verified"] == 472
    assert summ["total_pool_episodes_replay_verified"] == 777

    md = MD_PATH.read_text(encoding="utf-8")
    for required in (
        "post-hoc lock",
        "671ed96",
        "8fd4dec",
        "f9fb7a4a",
        "cf394894",
        "ca0a0dc0",
        "5f9b3297",
        "7200 s",
        "1bc3e281",
        "472/472",
        "777/777",
    ):
        assert required in md


def test_seed_profiles_solvability_and_stratified_gap_drivers(computed_audit):
    sp = computed_audit["seed_profiles"]
    for key, s_lo, s_hi in (("medium_0_29", 0, 29), ("hard_0_29", 0, 29), ("hard_30_59", 30, 59)):
        blk = sp[key]
        assert blk["n_seeds"] == 30
        assert blk["mole_policy"] == "default_v0"
        assert sum(blk["mole_archetype_counts"].values()) == 30
        assert sum(blk["dept_stratum_counts"].values()) == 30
        assert sum(blk["solver_difficulty_counts"].values()) == 30
        unpacked = fms.unpack_seed_profiles(blk)
        assert [p["seed"] for p in unpacked] == list(range(s_lo, s_hi + 1))
        for p in unpacked:
            assert p["mole_archetype"] in fms.MOLE_ARCHETYPES
            assert p["dept_stratum"] in fms.DEPT_STRATA
            assert p["solver_difficulty_stratum"] in fms.SOLVER_DIFFICULTY_STRATA

    solv = computed_audit["solver_solvability"]
    assert solv["medium_0_29_overall"]["precision_when_accusing"] == 1.0
    assert solv["medium_0_29_overall"]["wrong_accusations"] == 0
    assert solv["medium_0_29_overall"]["abstentions"] == 3

    hp = solv["hard_0_59_pooled"]
    assert hp["n"] == 60
    assert hp["all_mole_archetypes_positive_luck_adj"] is True
    assert hp["all_dept_strata_positive_luck_adj"] is True
    assert hp["by_mole_archetype"]["deep_crowd_camouflage"]["n"] == 13
    assert hp["by_mole_archetype"]["deep_crowd_camouflage"]["acc"] == 1.0
    assert hp["by_dept_stratum"]["crowded_dept"]["n"] == 11
    assert hp["by_dept_stratum"]["crowded_dept"]["acc"] == 1.0

    h0 = {c["cohort_id"]: c for c in computed_audit["blocks"]["primary_hard_0_29"]}
    oc_c = h0["opencode_carbon_hard_0_29"]
    assert round(oc_c["overall"]["raw"], 3) == 0.322
    assert round(oc_c["overall"]["luck"], 3) == 0.360
    assert round(oc_c["overall"]["l_gap"], 3) == 0.140
    assert round(oc_c["overall"]["ratio"] * 100) == 72

    for ax_key, expected_keys in (
        ("by_mole_archetype", fms.MOLE_ARCHETYPES),
        ("by_dept_stratum", fms.DEPT_STRATA),
        ("by_solver_difficulty", fms.SOLVER_DIFFICULTY_STRATA),
    ):
        total_n = sum(fms.unpack_stratum_metrics(oc_c[ax_key][k])["n"] for k in expected_keys)
        assert total_n == 30

    oc_gpt = h0["opencode_gpt55_hard_0_29"]
    assert round(oc_gpt["overall"]["raw"], 3) == 0.504
    assert round(oc_gpt["overall"]["luck"], 3) == 0.418
    assert round(oc_gpt["overall"]["acc"], 3) == 0.933
    assert round(oc_gpt["overall"]["ratio"] * 100) == 84
    assert fms.unpack_stratum_metrics(oc_gpt["by_mole_archetype"]["deep_crowd_camouflage"])["acc"] == 1.0
    assert fms.unpack_stratum_metrics(oc_gpt["by_dept_stratum"]["crowded_dept"])["acc"] == 1.0
    assert round(fms.unpack_stratum_metrics(oc_gpt["by_mole_archetype"]["low_tempo_stealth"])["abst"], 3) == 0.200

    drv = computed_audit["gap_drivers"]
    assert [r["stratum"] for r in drv["primary_carbon_hard_by_mole_archetype"][:2]] == [
        "deep_crowd_camouflage",
        "low_tempo_stealth",
    ]
    assert round(drv["primary_carbon_hard_by_mole_archetype"][0]["luck_adj_gap"], 3) == 0.209
    assert round(drv["primary_carbon_hard_by_mole_archetype"][1]["luck_adj_gap"], 3) == 0.208
    assert drv["primary_carbon_hard_by_dept_stratum"][0]["stratum"] == "crowded_dept"
    assert round(drv["primary_carbon_hard_by_dept_stratum"][0]["luck_adj_gap"], 3) == 0.253

    u6 = drv["extension_6_seed_union_selection_profile"]
    assert u6["union_seeds"] == [30, 34, 37, 42, 45, 57]
    assert u6["overlap_seeds_committed_precedence"] == [34]
    assert u6["seed_34_selected_source"] == "committed_g1_f9fb7a4a"
    assert math.isclose(u6["seed_34_g1_score"], 0.79, abs_tol=1e-9)
    assert math.isclose(u6["seed_34_fr8_score"], 0.82, abs_tol=1e-9)
    assert u6["deep_crowd_camouflage_count_in_union_6"] == 0
    assert u6["crowded_dept_count_in_union_6"] == 0
    assert u6["mean_mole_dept_size_union_6"] < u6["mean_mole_dept_size_hard_30_59"]
    assert u6["mean_mole_dept_size_union_6"] < u6["mean_mole_dept_size_hard_0_29"]


def test_gap_ships_flash_hard_false_and_true(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    syn_root = _make_gitless_root(tmp_path, name="flash_gate_root", link_gap_md=False)
    gap_file = syn_root / "docs" / "reports" / "gap.md"
    assert fms.gap_ships_flash_hard(syn_root) is False

    gap_file.write_text("Primary headline: gemini-4-carbon hard 65% [24%, 98%]\n", encoding="utf-8")
    assert fms.gap_ships_flash_hard(syn_root) is False
    audit_false = fms.compute_audit(root=syn_root, verify_replays=False, enforce_expected_counts=True)
    assert audit_false["flash_hard_shipped_in_gap_md"] is False
    assert audit_false["summary"]["flash_hard_held_pending_gap_md"] is True
    assert audit_false["summary"]["cohort_count"] == 14
    assert len(audit_false["blocks"]["primary_hard_0_29"]) == 4
    assert audit_false["blocks"]["primary_hard_0_29"][3]["cohort_id"] == "opencode_gpt55_hard_0_29"
    assert "primary_flash_hard_by_mole_archetype" not in audit_false["gap_drivers"]
    assert "primary_gpt55_hard_by_mole_archetype" in audit_false["gap_drivers"]
    md_false = fms.render_markdown(audit_false)
    assert "gated out of primary hard tables" in md_false
    assert "OpenCode gemini-3.5-flash hard (0-29)" not in md_false
    assert len(fms.serialize_audit_json(audit_false).encode("utf-8")) < 45_000

    gap_file.write_text(
        "Primary headline: gemini-4-carbon and opencode:google/gemini-3.5-flash hard (0-29)\n",
        encoding="utf-8",
    )
    assert fms.gap_ships_flash_hard(syn_root) is True
    audit_true = fms.compute_audit(root=syn_root, verify_replays=False, enforce_expected_counts=True)
    assert audit_true["flash_hard_shipped_in_gap_md"] is True
    assert audit_true["summary"]["flash_hard_held_pending_gap_md"] is False
    assert audit_true["summary"]["cohort_count"] == 15
    assert len(audit_true["blocks"]["primary_hard_0_29"]) == 5
    assert audit_true["blocks"]["primary_hard_0_29"][4]["cohort_id"] == "opencode_flash_hard_0_29"
    assert "primary_flash_hard_by_mole_archetype" in audit_true["gap_drivers"]
    json_true_bytes = len(fms.serialize_audit_json(audit_true).encode("utf-8"))
    assert json_true_bytes < 45_000
    assert json_true_bytes <= fms.MAX_JSON_BYTES
    md_true = fms.render_markdown(audit_true)
    assert "OpenCode gemini-3.5-flash hard (0-29)" in md_true


def test_step_compat_classifiers_and_tamper_detection(computed_audit, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)

    wrapped_err = {
        "ok": False,
        "error": json.dumps({"ok": False, "data": {}, "error": "bad variant map"}),
    }
    live_err = {"ok": False, "data": {"detail": "employee e99 unknown"}, "error": "bad variant map"}
    ok_match, flags = fms.step_result_matches(wrapped_err, live_err)
    assert ok_match is True
    assert flags == {
        "unwrapped_mcp_error": True,
        "detail_normalized": True,
        "truncated_checked": False,
    }

    live_big = {"ok": True, "data": {"items": [1, 2, 3]}, "error": None}
    nbytes = len(json.dumps(live_big).encode("utf-8"))
    trunc_rec = {
        "raw": f"...{nbytes} bytes truncated... The tool call succeeded but the output was truncated. Full output saved to: /tmp/x"
    }
    ok_trunc, flags_trunc = fms.step_result_matches(trunc_rec, live_big)
    assert ok_trunc is True
    assert flags_trunc["truncated_checked"] is True

    assert fms.is_client_only_step(
        {
            "tool": "bash",
            "result": {"ok": False, "error": "Model tried to call unavailable tool 'bash'"},
        }
    )
    assert fms.classify_mole_archetype("hard", True, 6, 8) == "decoy_entangled"
    assert fms.classify_mole_archetype("hard", False, 10, 8) == "deep_crowd_camouflage"
    assert fms.classify_mole_archetype("hard", False, 8, 13) == "low_tempo_stealth"
    assert fms.classify_mole_archetype("hard", False, 8, 14) == "high_tempo_exposed"
    assert fms.classify_dept_stratum("medium", 4) == "compact_dept"
    assert fms.classify_dept_stratum("medium", 6) == "standard_dept"
    assert fms.classify_dept_stratum("medium", 7) == "crowded_dept"
    assert fms.classify_solver_difficulty("hard", 8) == "fast_isolation"
    assert fms.classify_solver_difficulty("hard", 12) == "mid_horizon_isolation"
    assert fms.classify_solver_difficulty("hard", 13) == "late_or_stalled_isolation"

    syn_root = _make_gitless_root(tmp_path, name="tamper_root", link_gap_md=True)
    out_json = tmp_path / "tamper_out" / "mole_stratified_gap.json"
    out_md = tmp_path / "tamper_out" / "frontier_mole_stratified_gap_v14.md"
    monkeypatch.setattr(
        fms,
        "compute_audit",
        lambda root=ROOT, verify_replays=True, enforce_expected_counts=True: copy.deepcopy(computed_audit),
    )

    with pytest.raises(SystemExit):
        fms.main(["--write", "--check"])

    assert fms.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert fms.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data = json.loads(out_json.read_text(encoding="utf-8"))
    orig_luck = data["blocks"]["primary_hard_0_29"][1]["overall"]["luck"]

    data["blocks"]["primary_hard_0_29"][1]["overall"]["luck"] = orig_luck + 1e-10
    out_json.write_text(fms.serialize_audit_json(data), encoding="utf-8")
    assert fms.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data["blocks"]["primary_hard_0_29"][1]["overall"]["luck"] = orig_luck + 1e-3
    out_json.write_text(fms.serialize_audit_json(data), encoding="utf-8")
    assert fms.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    data["blocks"]["primary_hard_0_29"][1]["overall"]["luck"] = orig_luck
    oversized = fms.serialize_audit_json(data).rstrip("\n") + (" " * 8_000) + "\n"
    assert len(oversized.encode("utf-8")) > fms.MAX_JSON_BYTES
    out_json.write_text(oversized, encoding="utf-8")
    assert fms.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    out_json.write_text(fms.serialize_audit_json(data), encoding="utf-8")
    orig_md = out_md.read_text(encoding="utf-8")
    out_md.write_text(orig_md + "\ntampered\n", encoding="utf-8")
    assert fms.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    sample_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    first_ep = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])
    assert fms.verify_episode_pool([first_ep], "unit_ok")["verified"] == 1
    with pytest.raises(ValueError, match="replay mismatches"):
        fms.verify_episode_pool([dict(first_ep, score=float(first_ep["score"]) + 0.25)], "unit_bad_score")
    with pytest.raises(ValueError, match="replay mismatches"):
        fms.verify_episode_pool([dict(first_ep, final_day=0)], "unit_tampered_done_zero_day")
    with pytest.raises(ValueError, match="duplicate episodes"):
        fms.verify_episode_pool([first_ep, dict(first_ep)], "unit_dup")

    gpt55_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    gpt55_s0 = json.loads(gpt55_path.read_text(encoding="utf-8").splitlines()[0])
    assert int(gpt55_s0["seed"]) == 0
    assert fms.is_clean_non_accuse_rc0_exit(gpt55_s0, env_done=False) is True
    assert fms.is_clean_non_accuse_rc0_exit(gpt55_s0, env_done=True) is False
    assert fms.verify_episode_pool([gpt55_s0], "unit_gpt55_clean_rc0")[
        "clean_rc0_non_accuse_zero_day_seeds"
    ] == [0]

    for bad_variant in (
        {**gpt55_s0, "meta": {**gpt55_s0["meta"], "rc": 124}},
        {**gpt55_s0, "meta": {**gpt55_s0["meta"], "rc": False}},
        {**gpt55_s0, "meta": {**gpt55_s0["meta"], "valid": False}},
        {**gpt55_s0, "meta": {**gpt55_s0["meta"], "error": "timeout"}},
        {**gpt55_s0, "end_reason": "timeout"},
        {**gpt55_s0, "score": 0.25},
        {**gpt55_s0, "accused": "e00"},
        {**gpt55_s0, "final_day": 3},
    ):
        with pytest.raises(ValueError, match="replay mismatches"):
            fms.verify_episode_pool([bad_variant], "unit_gpt55_tampered")


def test_strict_hygiene_no_hash_in_py_and_no_em_en_dashes():
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    this_test = Path(__file__).resolve()
    py_files = [SCRIPT_PATH, this_test]
    owned_files = [SCRIPT_PATH, JSON_PATH, MD_PATH, this_test]

    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
        src = pf.read_text(encoding="utf-8")
        assert hash_char not in src, f"found {hash_char!r} character in {pf}"

    for f in owned_files:
        txt = f.read_text(encoding="utf-8")
        assert em_dash not in txt, f"found em dash in {f}"
        assert en_dash not in txt, f"found en dash in {f}"

    assert JSON_PATH.stat().st_size < 45_000
    assert JSON_PATH.stat().st_size <= fms.MAX_JSON_BYTES
