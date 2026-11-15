"""Tests for scripts/verify_frontier_suite.py, suite_manifest_v14.json, and frontier_master_index_v14.md."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

SCRIPT_PATH = SCRIPTS_DIR / "verify_frontier_suite.py"
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "suite_manifest_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_master_index_v14.md"

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_frontier_suite", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vfs = _load_module()


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _strip_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CANARY_WORLD_SECRET",
    ):
        monkeypatch.delenv(var, raising=False)


def _make_lightweight_root(tmp_path: Path, name: str = "light_root") -> Path:
    syn_root = tmp_path / name
    rep_v14 = syn_root / "results" / "frontier_replication" / "v1.4"
    comm_v14 = syn_root / "data" / "runs" / "committed" / "v1.4"
    harbor_dir = syn_root / "results" / "harbor" / "rehearsal"
    reports_dir = syn_root / "docs" / "reports"
    rep_v14.mkdir(parents=True)
    comm_v14.mkdir(parents=True)
    harbor_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)

    for spec in vfs.UPSTREAM_JSON_SPECS:
        src = ROOT / spec["json_rel"]
        dst = syn_root / spec["json_rel"]
        shutil.copyfile(src, dst)

    shutil.copyfile(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json",
        comm_v14 / "paired_table_gemini.json",
    )
    shutil.copyfile(
        ROOT / "results" / "harbor" / "rehearsal" / "TABLE.md",
        harbor_dir / "TABLE.md",
    )
    assert not (syn_root / ".git").exists()
    return syn_root


def _make_full_gitless_root(tmp_path: Path, name: str = "gitless_full") -> Path:
    syn_root = tmp_path / name
    (syn_root / "data" / "runs" / "committed").mkdir(parents=True)
    rep_v14 = syn_root / "results" / "frontier_replication" / "v1.4"
    rep_v14.mkdir(parents=True)
    (syn_root / "results" / "harbor").mkdir(parents=True)
    (syn_root / "docs" / "reports").mkdir(parents=True)

    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        syn_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "harbor" / "rehearsal",
        syn_root / "results" / "harbor" / "rehearsal",
    )
    os.symlink(ROOT / "scripts", syn_root / "scripts")
    os.symlink(ROOT / "tests", syn_root / "tests")

    for subdir in ("opencode-gemini-3.5-flash", "opencode-gemini-4-carbon", "reference"):
        os.symlink(
            ROOT / "results" / "frontier_replication" / "v1.4" / subdir,
            rep_v14 / subdir,
        )
    for spec in vfs.UPSTREAM_JSON_SPECS:
        shutil.copyfile(ROOT / spec["json_rel"], syn_root / spec["json_rel"])
        if spec["report_rel"] is not None:
            os.symlink(ROOT / spec["report_rel"], syn_root / spec["report_rel"])

    assert not (syn_root / ".git").exists()
    return syn_root


def test_check_cli_speed_offline_keyless_and_byte_identity(monkeypatch, capsys):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    t0 = time.perf_counter()
    rc = vfs.main(["--check"])
    elapsed_s = time.perf_counter() - t0
    assert rc == 0
    assert elapsed_s < 1.5, f"--check took {elapsed_s:.3f}s, exceeding 1.5s budget"
    out = capsys.readouterr().out
    assert "OK frontier_suite=PASS" in out
    assert "episodes=472+305=777" in out
    assert "carbon_hard=65%/72%" in out
    assert "gpt55_hard=101%/84%" in out
    assert "harbor=93%,116%,131%" in out

    assert JSON_PATH.is_file() and MD_PATH.is_file()
    assert JSON_PATH.stat().st_size <= vfs.MAX_JSON_BYTES
    assert vfs.MAX_JSON_BYTES == 25_000
    parsed = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    assert JSON_PATH.read_bytes() == vfs.serialize_manifest_json(parsed).encode("utf-8")
    assert MD_PATH.read_bytes() == vfs.render_markdown(parsed).encode("utf-8")


def test_gitless_root_write_check_roundtrip(monkeypatch, tmp_path, capsys):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    syn_root = _make_full_gitless_root(tmp_path)
    light_root = _make_lightweight_root(tmp_path, name="stdout_root")
    out_json = syn_root / "results" / "frontier_replication" / "v1.4" / "suite_manifest_v14.json"
    out_md = syn_root / "docs" / "reports" / "frontier_master_index_v14.md"

    assert vfs.main(["--root", str(syn_root), "--check"]) == 1
    assert vfs.main(["--root", str(syn_root), "--write"]) == 0
    assert out_json.is_file() and out_md.is_file()
    assert out_json.read_bytes() == JSON_PATH.read_bytes()
    assert out_md.read_bytes() == MD_PATH.read_bytes()
    assert vfs.main(["--root", str(syn_root), "--check"]) == 0

    capsys.readouterr()
    assert vfs.main(["--root", str(light_root), "--stdout"]) == 0
    assert capsys.readouterr().out == MD_PATH.read_text(encoding="utf-8")

    with pytest.raises(SystemExit):
        vfs.main(["--write", "--check"])


def test_cross_artifact_numerical_and_provenance_invariants(monkeypatch):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    m = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    md = MD_PATH.read_text(encoding="utf-8")

    assert m["schema_version"] == "v1.4-frontier-suite-manifest-1"
    assert m["tiers_version"] == "v1.4"
    assert m["pure_cpu_zero_api_calls"] is True
    assert m["zero_subprocesses"] is True
    assert m["zero_git_history_calls"] is True
    assert m["upstream_justsilas_sync_commit"] == "5f9b3297"

    ct = m["corpus_totals"]
    assert ct["committed_v14_episodes"] == 472
    assert ct["replication_v14_episodes"] == 305
    assert ct["combined_v14_episodes"] == 777
    assert ct["g2_cross_family_hard_episodes"] == 60
    assert ct["committed_plus_g2_episodes"] == 532
    assert ct["replay_mismatches"] == 0
    assert ct["duplicate_episodes"] == 0

    pl = m["provenance_locks"]
    assert pl == {
        "primary_0_29_classification": "post_hoc_lock",
        "primary_episodes_commit": "8fd4dec",
        "primary_lock_commit": "671ed96",
        "primary_lock_delay_s": 28,
        "g1_and_g2_prereg_commit": "f9fb7a4a",
        "gpt_5_5_prereg_commit": "cf394894",
        "gpt_5_5_results_commit": "ca0a0dc0",
        "step_error_detail_compat_commit": "1bc3e281",
        "shared_seed_dedup_rule_commit": "eb9dee54",
    }

    hc = m["headline_and_cross_model"]
    ch = hc["primary_carbon_hard_0_29"]
    assert ch["n"] == 30
    assert round(ch["mean_score"], 3) == 0.322
    assert ch["solver_mean_score"] == 0.499
    assert ch["raw_ratio_pct"] == 65
    assert ch["raw_ratio_ci_pct"] == [24, 98]
    assert round(ch["post_expected"], 3) == 0.360
    assert ch["luck_adjusted_ratio_pct"] == 72
    assert ch["luck_adjusted_ratio_ci_pct"] == [52, 91]

    gp = hc["gpt_5_5_hard_0_29"]
    assert gp["n"] == 30
    assert gp["accused_count"] == 28
    assert gp["correct_count"] == 28
    assert gp["clean_rc0_non_accuse_seeds"] == [0, 17]
    assert gp["infra_excluded_attempts"] == 0
    assert round(gp["mean_score"], 3) == 0.504
    assert gp["solver_mean_score"] == 0.499
    assert gp["raw_ratio_pct"] == 101
    assert gp["raw_ratio_ci_pct"] == [79, 140]
    assert round(gp["post_expected"], 3) == 0.418
    assert gp["luck_adjusted_ratio_pct"] == 84
    assert gp["luck_adjusted_ratio_ci_pct"] == [67, 103]

    ext = m["carbon_hard_30_59_reconciliation"]
    assert ext["g1_committed_ext"]["n"] == 2
    assert ext["g1_committed_ext"]["seeds"] == [34, 37]
    assert ext["g1_committed_ext"]["provider_quota_excluded"] == 31
    assert ext["fr8_replication"]["n"] == 5
    assert ext["fr8_replication"]["seeds"] == [30, 34, 42, 45, 57]
    assert ext["dedup_union_n6"]["n"] == 6
    assert ext["dedup_union_n6"]["seeds"] == [30, 34, 37, 42, 45, 57]
    assert ext["dedup_union_n6"]["shared_seeds"] == [34]
    assert ext["dedup_union_n6"]["remaining_unplayed_seeds_count"] == 24
    assert ext["secondary_pooled_sensitivity"]["all_la_95ci_exclude_parity"] is True
    assert ext["secondary_pooled_sensitivity"]["n32_la_ratio_pct"] == 75
    assert ext["secondary_pooled_sensitivity"]["n35_la_ratio_pct"] == 77
    assert ext["secondary_pooled_sensitivity"]["n36_la_ratio_pct"] == 81

    hr = m["harbor_rehearsal"]
    assert hr["final_ratios_pct"] == [93, 116, 131]
    assert hr["total_valid_opencode_trials"] == 29
    assert [r["n_valid"] for r in hr["runs"]] == [10, 10, 9]
    assert hr["do_nothing_ratio_pct"] == 0
    assert hr["stop_early_ratio_pct"] == 0

    assert len(m["deliverables"]) == 8
    for d in m["deliverables"]:
        assert d["script_rel"] in md
        assert d["json_rel"] in md
        assert d["verify_cmd"] in md
        if d["report_rel"] is not None:
            assert d["report_rel"] in md


def test_tamper_detection_across_json_harbor_caps_secrets_and_dashes(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    syn = _make_lightweight_root(tmp_path)
    assert vfs.main(["--root", str(syn), "--write"]) == 0
    assert vfs.main(["--root", str(syn), "--check"]) == 0

    que_path = syn / "results" / "frontier_replication" / "v1.4" / "queue_manifest.json"
    que_orig = que_path.read_text(encoding="utf-8")
    que_bad = json.loads(que_orig)
    que_bad["summary"]["committed_v14_replay_verified_episodes"] = 471
    que_path.write_text(json.dumps(que_bad), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    que_path.write_text(que_orig, encoding="utf-8")

    inf_path = syn / "results" / "frontier_replication" / "v1.4" / "infra_sensitivity.json"
    inf_orig = inf_path.read_text(encoding="utf-8")
    inf_bad = json.loads(inf_orig)
    inf_bad["imputation_sensitivity_0_29"]["hard_0_29_regimes"][0]["mean"] = 0.400
    inf_path.write_text(json.dumps(inf_bad), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    inf_path.write_text(inf_orig, encoding="utf-8")

    g2_path = syn / "results" / "frontier_replication" / "v1.4" / "g2_families_audit.json"
    g2_orig = g2_path.read_text(encoding="utf-8")
    g2_bad = json.loads(g2_orig)
    g2_bad["committed_v14_and_gpt55_comparison"]["gpt_5_5_hard_0_29"]["clean_rc0_non_accuse_zero_day_seeds"] = [0, 18]
    g2_path.write_text(json.dumps(g2_bad), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    g2_path.write_text(g2_orig, encoding="utf-8")

    trj_path = syn / "results" / "frontier_replication" / "v1.4" / "trajectory_audit.json"
    trj_orig = trj_path.read_text(encoding="utf-8")
    trj_bad = json.loads(trj_orig)
    for c in trj_bad["cohorts"]:
        if c["cohort_id"] == "opencode_gemini_4_carbon_hard_ext":
            c["seeds"] = [34, 38]
    trj_path.write_text(json.dumps(trj_bad), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    trj_path.write_text(trj_orig, encoding="utf-8")

    fsc_path = syn / "results" / "frontier_replication" / "v1.4" / "transcript_forensics.json"
    fsc_orig = fsc_path.read_text(encoding="utf-8")
    fsc_bad = json.loads(fsc_orig)
    for c in fsc_bad["cohorts"]:
        if c["cohort_id"] == "opencode_gemini_4_carbon_hard_rep":
            c["seeds"] = [30, 34, 42, 45, 58]
    fsc_path.write_text(json.dumps(fsc_bad), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    fsc_path.write_text(fsc_orig, encoding="utf-8")

    mol_path = syn / "results" / "frontier_replication" / "v1.4" / "mole_stratified_gap.json"
    mol_orig = mol_path.read_text(encoding="utf-8")
    mol_bad = json.loads(mol_orig)
    mol_bad["gap_drivers"]["extension_6_seed_union_selection_profile"]["union_seeds"] = [30, 34, 37, 42, 45]
    mol_path.write_text(json.dumps(mol_bad), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    mol_path.write_text(mol_orig, encoding="utf-8")

    harbor_path = syn / "results" / "harbor" / "rehearsal" / "TABLE.md"
    harbor_orig = harbor_path.read_text(encoding="utf-8")
    harbor_path.write_text(harbor_orig.replace("131% [86%, 590%]", "132% [86%, 590%]"), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    harbor_path.write_text(harbor_orig, encoding="utf-8")

    rep_path = syn / "results" / "frontier_replication" / "v1.4" / "replication_summary.json"
    rep_orig = rep_path.read_text(encoding="utf-8")
    rep_path.write_text(rep_orig.rstrip("\n") + (" " * 10_000) + "\n", encoding="utf-8")
    assert rep_path.stat().st_size > 48_000
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    rep_path.write_text(rep_orig, encoding="utf-8")

    fake_google_key = "AI" + "za" + ("B" * 24)
    fake_sk_key = "s" + "k-" + ("C" * 24)
    fake_sig = '"thoughtSignature":"' + ("D" * 80) + '"'
    for leak in (fake_google_key, fake_sk_key, fake_sig):
        assert vfs.scan_secrets_bytes(leak.encode("utf-8"), "unit") != []
    que_leak = json.loads(que_orig)
    que_leak["replication_root"] = fake_google_key
    que_path.write_text(json.dumps(que_leak), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    que_path.write_text(que_orig, encoding="utf-8")

    que_dash = json.loads(que_orig)
    que_dash["replication_root"] = "bad" + EM_DASH + "dash"
    que_path.write_text(json.dumps(que_dash, ensure_ascii=False), encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    que_path.write_text(que_orig, encoding="utf-8")

    out_json = syn / "results" / "frontier_replication" / "v1.4" / "suite_manifest_v14.json"
    out_md = syn / "docs" / "reports" / "frontier_master_index_v14.md"
    assert vfs.main(["--root", str(syn), "--check"]) == 0

    json_orig = out_json.read_text(encoding="utf-8")
    out_json.write_text(json_orig.rstrip("\n") + (" " * 20_000) + "\n", encoding="utf-8")
    assert out_json.stat().st_size > vfs.MAX_JSON_BYTES
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    out_json.write_text(json_orig, encoding="utf-8")

    md_orig = out_md.read_text(encoding="utf-8")
    out_md.write_text(md_orig + "\nextra drifted line\n", encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 1
    out_md.write_text(md_orig, encoding="utf-8")
    assert vfs.main(["--root", str(syn), "--check"]) == 0


def test_strict_hygiene_owned_files_zero_comments_zero_dashes_ascii():
    this_test = Path(__file__).resolve()
    py_files = [SCRIPT_PATH, this_test]
    owned_files = [SCRIPT_PATH, JSON_PATH, MD_PATH, this_test]

    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
        src = pf.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"found {HASH_CHAR!r} character in {pf}"

    for f in owned_files:
        raw = f.read_bytes()
        assert vfs.scan_secrets_bytes(raw, str(f)) == []
        txt = raw.decode("utf-8")
        assert EM_DASH not in txt, f"found em dash in {f}"
        assert EN_DASH not in txt, f"found en dash in {f}"
        assert txt.isascii(), f"found non-ASCII characters in {f}"

    assert JSON_PATH.stat().st_size <= vfs.MAX_JSON_BYTES
