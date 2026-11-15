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


def test_committed_suite_index_and_overview_invariants():
    assert INDEX_PATH.is_file()
    assert OVERVIEW_PATH.is_file()
    raw_bytes = INDEX_PATH.read_bytes()
    assert len(raw_bytes) < suite.MAX_INDEX_BYTES

    data = json.loads(raw_bytes.decode("utf-8"))
    assert data["schema_version"] == "eval_suite_index_v14.v1"
    assert data["tiers_version"] == "v1.4"
    assert data["primary_seeds"] == "0-29"
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

    md_text = OVERVIEW_PATH.read_text(encoding="utf-8")
    for expected_snippet in (
        "python scripts/run_all_eval_checks.py --check",
        "version_evolution_v14.py",
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "-0.333 [-0.659, -0.046]",
        "-0.234 [-0.461, -0.017]",
        "3.48x",
        "4.22x",
        "0.601",
        "All `5/5` deterministic gates PASS",
    ):
        assert expected_snippet in md_text


def test_only_flag_fast_real_verifier_execution(capsys):
    rc = suite.main(["--check", "--only", "harness_and_tier_analysis_v14", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["passed"] is True
    assert len(payload["verifiers_ran"]) == 1
    assert payload["verifiers_ran"][0]["name"] == "harness_and_tier_analysis_v14"
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

    rc_check_before_regen = suite.main(["--check", "--root", str(ws), "--json"])
    check_payload = json.loads(capsys.readouterr().out)
    assert rc_check_before_regen == 0
    assert check_payload["passed"] is True
    ran_names = [r["name"] for r in check_payload["verifiers_ran"]]
    assert "ladder_pareto_v14" in ran_names
    assert "harbor_luck_adjusted_v14" in ran_names
    assert "version_evolution_v14" in ran_names
    assert len(ran_names) == 8

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
