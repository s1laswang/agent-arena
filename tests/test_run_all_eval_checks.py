"""Fast offline unit tests for scripts/run_all_eval_checks.py and v1.4 suite index/overview."""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts/run_all_eval_checks.py"
INDEX_PATH = ROOT / "results/eval_v14/eval_suite_index.json"
OVERVIEW_PATH = ROOT / "docs/reports/eval_suite_overview.md"
THIS_TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)


def _load_orchestrator():
    spec = importlib.util.spec_from_file_location("run_all_eval_checks", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


suite = _load_orchestrator()


def _write_stub_verifier(script_path: Path, exit_code: int = 0, msg: str = "stub check ok") -> None:
    script_path.parent.mkdir(parents=True, exist_ok=True)
    code = (
        "import sys\n"
        "assert '--check' in sys.argv[1:]\n"
        f"print({msg!r})\n"
        f"raise SystemExit({exit_code})\n"
    )
    script_path.write_text(code, encoding="utf-8")


def _build_synthetic_workspace(dst_root: Path) -> Path:
    for spec in suite.CORE_VERIFIERS:
        _write_stub_verifier(dst_root / spec["script"], exit_code=0, msg=f"{spec['name']} ok")
        src_json = ROOT / spec["json_artifact"]
        dst_json = dst_root / spec["json_artifact"]
        dst_json.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_json, dst_json)

        src_md = ROOT / spec["report_artifact"]
        dst_md = dst_root / spec["report_artifact"]
        dst_md.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_md, dst_md)
    return dst_root


def test_list_mode_and_name_normalization(capsys):
    assert suite.normalize_verifier_name("headline_gap_table") == "headline_gap_table"
    assert suite.normalize_verifier_name("headline_gap_table.py") == "headline_gap_table"
    assert suite.normalize_verifier_name("scripts/headline_gap_table.py") == "headline_gap_table"
    assert suite.normalize_verifier_name("./scripts/headline_gap_table.py") == "headline_gap_table"

    parsed = suite.parse_only_specs(["verify_eval_claims,headline_gap_table.py", "scripts/hint_ablation_audit.py"])
    assert parsed == ["verify_eval_claims", "headline_gap_table", "hint_ablation_audit"]

    rc_txt = suite.main(["--list"])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "[core:present] verify_eval_claims" in out_txt
    assert "[core:present] hint_ablation_audit" in out_txt

    rc_json = suite.main(["--list", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert [c["name"] for c in payload["core_verifiers"]] == [c["name"] for c in suite.CORE_VERIFIERS]
    assert all(c["present"] is True for c in payload["core_verifiers"])
    assert [o["name"] for o in payload["optional_verifiers"]] == list(suite.OPTIONAL_VERIFIER_NAMES)
    assert "version_evolution_v14" in suite.OPTIONAL_VERIFIER_NAMES
    assert "version_evolution_audit" in suite.OPTIONAL_VERIFIER_NAMES
    assert "paired_seed_diagnostics_v14" in suite.OPTIONAL_VERIFIER_NAMES


def test_committed_suite_index_and_overview_invariants():
    assert INDEX_PATH.is_file()
    assert OVERVIEW_PATH.is_file()
    raw_bytes = INDEX_PATH.read_bytes()
    assert len(raw_bytes) < suite.MAX_INDEX_BYTES

    data = json.loads(raw_bytes.decode("utf-8"))
    assert data["schema_version"] == "eval_suite_index_v14.v1"
    assert data["tiers_version"] == "v1.4"
    assert data["primary_seeds"] == "0-29"
    assert data["primary_seeds_lock"].startswith("post-hoc locked paired dev seeds 0-29 (671ed96, 28 s after 8fd4dec")
    assert "pre-registered" not in data["primary_seeds_lock"].lower()
    assert data["n_primary_seeds_per_tier"] == 30
    assert len(data["core_verifiers"]) == 5
    assert all(v["check_passed"] is True for v in data["core_verifiers"])

    raw_index_str = raw_bytes.decode("utf-8")
    for volatile_key in ('"elapsed_s"', '"duration_s"', '"wall_clock"', '"generated_at"', '"head_sha"'):
        assert volatile_key not in raw_index_str

    errs = suite.verify_suite_artifacts(ROOT, INDEX_PATH, OVERVIEW_PATH)
    assert errs == []
    assert suite.main(["--check", "--artifacts-only"]) == 0

    cs = data["core_headline_summary"]
    oc_hard = cs["headline_gap_table"]["cohorts"]["hard_opencode_gemini_4_carbon"]
    assert oc_hard["n"] == 30
    assert oc_hard["ratio"] == pytest.approx(0.6459585838, abs=1e-9)
    assert oc_hard["luck_adj_ratio"] == pytest.approx(0.7201029448, abs=1e-9)

    did_la = cs["harness_and_tier_2x2"]["luck_adjusted_did_hard_minus_medium"]
    assert did_la["point"] == pytest.approx(-0.234127, abs=1e-6)
    assert did_la["boot_ci95"][1] < 0.0

    jrp = cs["judge_rerun_power"]
    assert jrp["opencode_carbon_model_a"]["empirical_paired_var_reduction_factor"] == pytest.approx(
        3.4802717939, abs=1e-6
    )
    assert jrp["pass_k_hard"]["solver"]["pass_3"] > jrp["pass_k_hard"]["opencode-3.5-flash"]["pass_3"]

    ha = cs["hint_ablation"]
    assert ha["ablation_episodes_verified"] == 30
    assert ha["context_episodes_verified"] == 30
    assert ha["total_steps_verified"] == 5986
    assert ha["step_mismatches"] == 0

    rm = cs["repo_milestones"]
    assert rm["seed_lock"]["commit"] == "671ed96"
    assert rm["seed_lock"]["primary_commit"] == "8fd4dec"
    assert rm["seed_lock"]["delay_seconds"] == 28
    assert rm["seed_lock"]["classification"] == "post_hoc_lock_not_preregistered"
    assert rm["replay_panel_fix_d"]["commit"] == "1bc3e281"
    assert rm["replay_panel_fix_d"]["invalid_arguments_detail_compat"] is True
    assert rm["g1_partial_extension"]["prereg_commit"] == "f9fb7a4a"
    assert rm["g1_partial_extension"]["data_commit"] == "364fe657"
    assert rm["g1_partial_extension"]["ext_only"]["seeds"] == [34, 37]
    assert rm["g1_partial_extension"]["pooled_0_59"]["n"] == 32
    assert rm["canonical_gemini_ladder"]["commit"] == "eb363eb9"
    assert rm["canonical_gemini_ladder"]["episodes"] == 587
    assert rm["canonical_gemini_ladder"]["gemma_episodes"] == 5
    assert rm["gpt_5_5_preregistration"]["commit"] == "cf394894"
    assert rm["gpt_5_5_preregistration"]["env_tag"] == "afterquery-final"

    md_text = OVERVIEW_PATH.read_text(encoding="utf-8")
    for expected_snippet in (
        "python scripts/run_all_eval_checks.py --check",
        "post-hoc locked paired dev seeds `0-29` (`671ed96`, 28 s after `8fd4dec`",
        "version_evolution_v14.py",
        "paired_seed_diagnostics_v14.py",
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "eb363eb9",
        "587",
        "364fe657",
        "68% [32%, 100%]",
        "75% [56%, 93%]",
        "1bc3e281",
        "cf394894",
        "fd8c1cb0",
        "-0.333 [-0.659, -0.046]",
        "-0.234 [-0.461, -0.017]",
        "3.48x",
        "4.22x",
        "0.601",
        "All `5/5` deterministic gates PASS",
    ):
        assert expected_snippet in md_text
    assert "pre-registered paired dev seeds" not in md_text.lower()
    assert "section a pre-registered" not in md_text.lower()


def test_only_flag_fast_real_verifier_execution(capsys):
    rc = suite.main(["--check", "--only", "build_eval_dashboard_v14", "--skip-artifact-check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["passed"] is True
    assert len(payload["verifiers_ran"]) == 1
    assert payload["verifiers_ran"][0]["name"] == "build_eval_dashboard_v14"
    assert payload["verifiers_ran"][0]["passed"] is True

    rc_unknown = suite.main(["--check", "--only", "unknown_nonexistent_module", "--json"])
    payload_bad = json.loads(capsys.readouterr().out)
    assert rc_unknown == 1
    assert payload_bad["passed"] is False
    assert any("unknown verifier" in e for e in payload_bad["errors"])


def test_wave2_optional_discovery_and_deterministic_check_resilience(tmp_path: Path, capsys):
    ws = _build_synthetic_workspace(tmp_path / "repo")

    rc_gen = suite.main(["--root", str(ws)])
    capsys.readouterr()
    assert rc_gen == 0

    idx_file = ws / suite.DEFAULT_INDEX_REL
    md_file = ws / suite.DEFAULT_OVERVIEW_REL
    assert idx_file.is_file() and md_file.is_file()
    initial_idx = json.loads(idx_file.read_text(encoding="utf-8"))
    assert initial_idx["present_optional_verifiers"] == []

    _write_stub_verifier(ws / "scripts/ladder_pareto_v14.py", exit_code=0, msg="ladder_pareto ok")
    _write_stub_verifier(ws / "scripts/harbor_luck_adjusted_v14.py", exit_code=0, msg="harbor_la ok")
    _write_stub_verifier(ws / "scripts/version_evolution_v14.py", exit_code=0, msg="version_evo ok")
    (ws / "results/eval_v14/ladder_pareto_v14.json").write_text('{"ok": true}\n', encoding="utf-8")

    rc_check_before_regen = suite.main(["--check", "--jobs", "3", "--root", str(ws), "--json"])
    check_payload = json.loads(capsys.readouterr().out)
    assert rc_check_before_regen == 0
    assert check_payload["passed"] is True
    ran_names = [r["name"] for r in check_payload["verifiers_ran"]]
    assert ran_names[:5] == [c["name"] for c in suite.CORE_VERIFIERS]
    assert "ladder_pareto_v14" in ran_names
    assert "harbor_luck_adjusted_v14" in ran_names
    assert "version_evolution_v14" in ran_names
    assert len(ran_names) == 8
    assert suite.main(["--check", "--jobs", "1", "--root", str(ws)]) == 0
    capsys.readouterr()

    _write_stub_verifier(ws / "scripts/harbor_luck_adjusted_v14.py", exit_code=1, msg="broken optional")
    rc_opt_fail = suite.main(["--check", "--root", str(ws), "--json"])
    fail_payload = json.loads(capsys.readouterr().out)
    assert rc_opt_fail == 1
    assert fail_payload["passed"] is False
    assert any("harbor_luck_adjusted_v14.py" in e for e in fail_payload["errors"])

    _write_stub_verifier(ws / "scripts/harbor_luck_adjusted_v14.py", exit_code=0, msg="harbor_la fixed")
    rc_refresh = suite.main(["--root", str(ws)])
    capsys.readouterr()
    assert rc_refresh == 0
    refreshed_idx = json.loads(idx_file.read_text(encoding="utf-8"))
    assert [o["name"] for o in refreshed_idx["present_optional_verifiers"]] == [
        "harbor_luck_adjusted_v14",
        "ladder_pareto_v14",
        "version_evolution_v14",
    ]
    assert "results/eval_v14/ladder_pareto_v14.json" in refreshed_idx["present_eval_v14_artifacts"]
    assert suite.main(["--check", "--root", str(ws)]) == 0
    capsys.readouterr()


def test_tamper_tolerance_and_missing_core_detection(tmp_path: Path, capsys):
    ws = _build_synthetic_workspace(tmp_path / "tamper_repo")
    assert suite.main(["--root", str(ws)]) == 0
    capsys.readouterr()

    idx_file = ws / suite.DEFAULT_INDEX_REL
    md_file = ws / suite.DEFAULT_OVERVIEW_REL

    tiny_eps: dict[str, Any] = json.loads(idx_file.read_text(encoding="utf-8"))
    tiny_eps["core_headline_summary"]["headline_gap_table"]["cohorts"]["hard_opencode_gemini_4_carbon"]["ratio"] += 1e-12
    idx_file.write_text(json.dumps(tiny_eps, indent=1) + "\n", encoding="utf-8")
    assert suite.main(["--check", "--root", str(ws)]) == 0
    capsys.readouterr()

    bad_idx: dict[str, Any] = json.loads(idx_file.read_text(encoding="utf-8"))
    bad_idx["core_headline_summary"]["headline_gap_table"]["cohorts"]["hard_opencode_gemini_4_carbon"]["ratio"] = 0.99
    idx_file.write_text(json.dumps(bad_idx, indent=1) + "\n", encoding="utf-8")
    rc_bad_idx = suite.main(["--check", "--root", str(ws), "--json"])
    p_bad_idx = json.loads(capsys.readouterr().out)
    assert rc_bad_idx == 1
    assert any("core_headline_summary differs" in e for e in p_bad_idx["errors"])

    assert suite.main(["--root", str(ws)]) == 0
    capsys.readouterr()

    md_file.write_text(md_file.read_text(encoding="utf-8").replace("65% [24%, 98%]", "99% [98%, 100%]"), encoding="utf-8")
    rc_bad_md = suite.main(["--check", "--root", str(ws), "--json"])
    p_bad_md = json.loads(capsys.readouterr().out)
    assert rc_bad_md == 1
    assert any("render_overview_md" in e for e in p_bad_md["errors"])

    assert suite.main(["--root", str(ws)]) == 0
    capsys.readouterr()

    (ws / "scripts/hint_ablation_audit.py").unlink()
    rc_missing = suite.main(["--check", "--root", str(ws), "--json"])
    p_missing = json.loads(capsys.readouterr().out)
    assert rc_missing == 1
    assert any("missing required core verifier script" in e for e in p_missing["errors"])


def test_w5_posthoc_hygiene_and_optional_gpt55_cohorts(tmp_path: Path, capsys):
    ws = _build_synthetic_workspace(tmp_path / "sync_repo")
    cm_path = ws / "results/eval_v14/claims_manifest.json"
    cm = json.loads(cm_path.read_text(encoding="utf-8"))
    cm["version_hygiene"]["posthoc_locked_primary_frontier_cohorts"] = 5
    cm["version_hygiene"]["preregistered_extension_frontier_cohorts"] = 1
    cm["version_hygiene"]["preregistered_frontier_cohorts"] = 1
    cm["version_hygiene"]["seed_lock_rule_verified"] = True
    cm_path.write_text(json.dumps(cm, indent=2) + "\n", encoding="utf-8")

    hgt_path = ws / "results/eval_v14/headline_gap_table_v14.json"
    hgt = json.loads(hgt_path.read_text(encoding="utf-8"))
    base_row = next(
        r for r in hgt["section_a"]
        if r["tier"] == "hard" and r["agent"] == "opencode:google/gemini-4-carbon" and r["kind"] == "frontier"
    )
    gpt55_row = dict(base_row, agent="opencode:openai/gpt-5.5")
    flash_med_row = dict(base_row, tier="medium", agent="opencode:google/gemini-3.5-flash")
    hgt["section_a"].extend([gpt55_row, flash_med_row])
    hgt_path.write_text(json.dumps(hgt, indent=2) + "\n", encoding="utf-8")

    (ws / "data/runs/committed/v1.4/opencode-gpt-5.5").mkdir(parents=True, exist_ok=True)
    _write_stub_verifier(ws / "scripts/paired_seed_diagnostics_v14.py", exit_code=0, msg="paired_diag ok")

    assert suite.main(["--root", str(ws)]) == 0
    capsys.readouterr()

    idx_file = ws / suite.DEFAULT_INDEX_REL
    md_file = ws / suite.DEFAULT_OVERVIEW_REL
    assert idx_file.stat().st_size < suite.MAX_INDEX_BYTES
    idx_data = json.loads(idx_file.read_text(encoding="utf-8"))
    cs = idx_data["core_headline_summary"]
    assert cs["claims_and_hygiene"]["hygiene"]["primary_locked_frontier_cohorts"] == 5
    assert cs["claims_and_hygiene"]["hygiene"]["seed_lock_rule_verified"] is True
    assert "hard_opencode_gpt_5_5" in cs["headline_gap_table"]["cohorts"]
    assert "medium_opencode_gemini_3_5_flash" in cs["headline_gap_table"]["cohorts"]
    assert cs["repo_milestones"]["gpt_5_5_preregistration"]["committed_dir_present"] is True
    assert [o["name"] for o in idx_data["present_optional_verifiers"]] == ["paired_seed_diagnostics_v14"]

    md_txt = md_file.read_text(encoding="utf-8")
    assert "OpenCode + gpt-5.5 (judges' MCP)" in md_txt
    assert "OpenCode + gemini-3.5-flash (judges' MCP)" in md_txt
    assert "committed directory `data/runs/committed/v1.4/opencode-gpt-5.5` present" in md_txt
    assert suite.main(["--check", "--root", str(ws)]) == 0
    capsys.readouterr()


def test_hygiene_zero_comments_zero_unicode_dashes_zero_leaks():
    for py_path in (SCRIPT_PATH, THIS_TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert HASH_CHAR not in src, f"unexpected hash character in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comment_tokens == [], f"tokenize.COMMENT found in {py_path}: {comment_tokens}"

    co_authored_tag = "Co-Authored" + "-By"
    for fpath in (SCRIPT_PATH, INDEX_PATH, OVERVIEW_PATH, THIS_TEST_PATH):
        txt = fpath.read_text(encoding="utf-8")
        assert EN_DASH not in txt and EM_DASH not in txt, f"unicode dash found in {fpath}"
        assert co_authored_tag not in txt
        assert suite._scan_text_hygiene(str(fpath), txt) == []
