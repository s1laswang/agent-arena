from __future__ import annotations

import ast
import io
import json
from pathlib import Path
import re
import shutil
import sys
import time
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import scripts.reproduce_tiebreak_all as rta
import scripts.tiebreak_state_externalization_audit as tsea
import scripts.verify_tiebreak_submission as vts

SCRIPT_PATH = REPO_ROOT / "scripts" / "tiebreak_state_externalization_audit.py"
SUMMARY_PATH = REPO_ROOT / "results" / "tiebreak" / "state_externalization" / "externalization_summary.json"
REPORT_PATH = REPO_ROOT / "docs" / "reports" / "tiebreak_state_externalization.md"
SELF_PATH = Path(__file__).resolve()


def test_check_mode_fast_and_optional_gate_discovered(capsys: pytest.CaptureFixture[str]) -> None:
    t0 = time.perf_counter()
    rc = tsea.main(["--check"])
    elapsed = time.perf_counter() - t0
    out = capsys.readouterr().out
    assert rc == 0
    assert elapsed < 0.5
    assert "state_externalization_ok=True" in out

    verdict = tsea.verify_artifacts(REPO_ROOT)
    assert verdict == {"passed": True, "errors": []}

    discovered, _ = rta.discover_optional_gates(REPO_ROOT)
    disc_ids = [gid for gid, _, _ in discovered]
    assert "tiebreak_state_externalization_audit" in disc_ids

    outcome = rta.execute_single_gate(
        REPO_ROOT,
        "tiebreak_state_externalization_audit",
        "scripts/tiebreak_state_externalization_audit.py",
        "scripts/tiebreak_state_externalization_audit.py --check",
        optional=True,
    )
    assert outcome.passed is True
    assert outcome.errors == []


def test_cross_scale_synthesis_numbers_match_committed_artifacts() -> None:
    assert SUMMARY_PATH.is_file()
    assert REPORT_PATH.is_file()
    assert SUMMARY_PATH.stat().st_size < 300 * 1024
    assert not (SUMMARY_PATH.parent / "summary.json").exists()
    assert not (SUMMARY_PATH.parent / "table.md").exists()

    data = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert data["schema"] == tsea.SCHEMA_ID
    assert data["dev_eval_seed_range"] == "0..29"
    assert data["dev_protocol_status"] == "post-hoc locked"
    assert data["heldout_seed_range"] == "800000..800059"

    qwen = data["regime_a_raw_in_context"]["open_weight_qwen25_15b"]
    assert qwen["is_open_weight_llm"] is True
    assert qwen["historical_runs_total"] == 19
    assert qwen["historical_runs_beating_base_zero"] == 0
    assert qwen["prompt_header_tax"]["slurm_44410_header_tokens"] == 2842
    assert qwen["prompt_header_tax"]["window_4k_tokens"] == 4096
    assert qwen["prompt_header_tax"]["header_share_of_4k_pct"] == pytest.approx(69.4, abs=0.1)
    assert qwen["canary_variant_map_eviction"]["evicted_4k_headline_band"] == "92-98%"
    assert qwen["canary_variant_map_eviction"]["evicted_8k_headline_band"] == "56-85%"
    assert 92.0 <= qwen["canary_variant_map_eviction"]["evicted_4k_range_pct"][0] <= 93.0
    assert 97.5 <= qwen["canary_variant_map_eviction"]["evicted_4k_range_pct"][1] <= 98.5
    assert 56.0 <= qwen["canary_variant_map_eviction"]["evicted_8k_range_pct"][0] <= 57.5
    assert 84.0 <= qwen["canary_variant_map_eviction"]["evicted_8k_range_pct"][1] <= 85.5

    qruns = qwen["representative_runs"]
    assert qruns["v2_sft_4k"]["mean_score"] == pytest.approx(-0.457, abs=1e-3)
    assert qruns["v3_4k_s0_grpo"]["mean_score"] == pytest.approx(-0.147, abs=1e-3)
    assert qruns["v3_8k_abstain_mode_s0"]["mean_score"] == pytest.approx(-0.060, abs=1e-3)
    assert qruns["v3_8k_abstain_mode_s2"]["mean_score"] == pytest.approx(-0.050, abs=1e-3)
    assert qruns["v3_8k_reckless_mode_s1"]["mean_score"] == pytest.approx(-0.777, abs=1e-3)
    assert qruns["v3_8k_reckless_mode_s3"]["mean_score"] == pytest.approx(-0.788, abs=1e-3)
    assert qruns["dagger_r1_8k_verda_x2"]["mean_score"] == pytest.approx(-0.542, abs=1e-3)
    assert qruns["dagger_r1_4k_verda_x2"]["mean_score"] == pytest.approx(-0.101, abs=1e-3)

    fmcp = data["regime_a_raw_in_context"]["frontier_mcp_only"]
    g_mcp = fmcp["gemini_4_carbon_opencode_mcp_hard"]
    assert g_mcp["mean_score"] == pytest.approx(0.322, abs=1e-3)
    assert g_mcp["ci95"] == pytest.approx(0.199, abs=1e-3)
    assert g_mcp["solver_same_seeds"] == pytest.approx(0.499, abs=1e-3)
    assert g_mcp["ratio_vs_solver_display"] == "65% [24%, 98%]"
    assert g_mcp["luck_ratio_vs_solver_pct"] == 72
    assert g_mcp["canaries_planted_per_ep"] == pytest.approx(8.5, abs=0.1)
    assert g_mcp["interviews_per_ep"] == pytest.approx(68.0, abs=0.1)
    assert g_mcp["wrong_count"] == 4

    gpt_mcp = fmcp["gpt_5_5_opencode_mcp_hard"]
    assert gpt_mcp["mean_score"] == pytest.approx(0.504, abs=1e-3)
    assert gpt_mcp["ci95"] == pytest.approx(0.064, abs=1e-3)
    assert gpt_mcp["ratio_vs_solver_display"] == "101% [79%, 140%]"
    assert gpt_mcp["canaries_planted_per_ep"] == pytest.approx(17.2, abs=0.1)
    assert gpt_mcp["interviews_per_ep"] == pytest.approx(4.2, abs=0.25)
    assert gpt_mcp["wrong_count"] == 0
    assert gpt_mcp["text_only_non_accusations"] == 2

    harbor = data["regime_b_externalized_state"]["frontier_harbor_judge_path"]
    assert harbor["shell_used_trials"] == 20
    assert harbor["shell_audited_trials"] == 28
    assert harbor["oracle_mean_all_10"] == pytest.approx(0.506, abs=1e-3)
    assert harbor["valid_accusations_correct"] == 28
    assert harbor["valid_accusations_total"] == 29
    h_means = [r["mean_score"] for r in harbor["runs"]]
    h_pcts = [r["ratio_vs_oracle_pct"] for r in harbor["runs"]]
    assert h_means == [pytest.approx(0.472), pytest.approx(0.585), pytest.approx(0.626)]
    assert h_pcts == [93, 116, 131]

    comp = data["regime_b_externalized_state"]["tiebreak_compact_policies"]
    assert comp["panel_fix_e_strict_separation"] is True
    assert comp["all_policies_is_open_weight_llm"] is False
    assert comp["externalized_ledger_properties"]["max_state_token_budget"] == 900
    assert comp["externalized_ledger_properties"]["dense_feature_dim"] == 28
    assert comp["externalized_ledger_properties"]["canary_map_eviction_pct"] == 0.0
    assert comp["ratio_vs_solver_n90_headline_band"] == "89-92%"
    assert comp["policies_passing_all_5_panel_fix_e_gates"] == 4

    by_cls = {p["policy_class"]: p for p in comp["policies"]}
    assert by_cls["EmpiricalBayesPolicy"]["param_count"] == 11
    assert by_cls["EmpiricalBayesPolicy"]["after_mean_score_3d"] == pytest.approx(0.607, abs=1e-3)
    assert by_cls["ScalingLogisticPolicy"]["param_count"] == 82
    assert by_cls["ScalingLogisticPolicy"]["after_mean_score_3d"] == pytest.approx(0.611, abs=1e-3)
    assert by_cls["CompactLinearDAggerPolicy"]["param_count"] == 785
    assert by_cls["CompactLinearDAggerPolicy"]["after_mean_score_3d"] == pytest.approx(0.627, abs=1e-3)
    assert by_cls["TinyMLPPolicy"]["param_count"] == 12293
    assert by_cls["TinyMLPPolicy"]["after_mean_score_3d"] == pytest.approx(0.614, abs=1e-3)
    assert all(
        p["is_open_weight_llm"] is False and p["panel_fix_e_gates_passed"] == 5
        for p in comp["policies"]
    )


def test_partial_root_without_git_or_external_tables_passes(tmp_path: Path) -> None:
    partial = tmp_path / "shallow_no_git_export"
    (partial / "scripts").mkdir(parents=True, exist_ok=True)
    (partial / "results" / "tiebreak" / "state_externalization").mkdir(parents=True, exist_ok=True)
    (partial / "docs" / "reports").mkdir(parents=True, exist_ok=True)

    shutil.copy2(SCRIPT_PATH, partial / "scripts" / "tiebreak_state_externalization_audit.py")
    shutil.copy2(SUMMARY_PATH, partial / tsea.DEFAULT_OUT_JSON)
    shutil.copy2(REPORT_PATH, partial / tsea.DEFAULT_OUT_MD)

    assert not (partial / ".git").exists()
    assert not (partial / tsea.HARBOR_REHEARSAL_TABLE_REL).exists()
    assert not (partial / tsea.PAIRED_TABLE_GEMINI_REL).exists()
    assert not (partial / tsea.BEHAVIOUR_COMPARE_REL).exists()

    full_summary, full_errs = tsea.build_externalization_summary(REPO_ROOT)
    part_summary, part_errs = tsea.build_externalization_summary(partial)
    assert full_errs == []
    assert part_errs == []
    assert full_summary == json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    assert part_summary == full_summary

    assert tsea.main(["--check", "--root", str(partial)]) == 0

    rep = rta.run_all_gates(root=partial, allow_partial_root=True, workers=1)
    assert rep["passed"] is True
    assert rep["optional_discovered"] == ["tiebreak_state_externalization_audit"]


def test_tamper_and_guard_rejections(tmp_path: Path) -> None:
    work = tmp_path / "tamper_case"
    (work / "results" / "tiebreak" / "state_externalization").mkdir(parents=True, exist_ok=True)
    (work / "docs" / "reports").mkdir(parents=True, exist_ok=True)
    j_path = work / tsea.DEFAULT_OUT_JSON
    m_path = work / tsea.DEFAULT_OUT_MD
    shutil.copy2(SUMMARY_PATH, j_path)
    shutil.copy2(REPORT_PATH, m_path)

    assert tsea.verify_committed_artifacts(j_path, m_path, repo_root=work) == []

    bad_judge = json.loads(SUMMARY_PATH.read_text(encoding="utf-8"))
    bad_judge["forbidden_seed_note"] = "900000..900009"
    j_path.write_text(json.dumps(bad_judge, indent=2) + "\n", encoding="utf-8")
    errs_judge = tsea.verify_committed_artifacts(j_path, m_path, repo_root=work)
    assert any("JUDGE_SEEDS leak" in e for e in errs_judge)
    shutil.copy2(SUMMARY_PATH, j_path)

    m_path.write_text(REPORT_PATH.read_text(encoding="utf-8") + "\nPre-registered seeds 0..29\n", encoding="utf-8")
    errs_pfa = tsea.verify_committed_artifacts(j_path, m_path, repo_root=work)
    assert any("0..29" in e for e in errs_pfa)
    shutil.copy2(REPORT_PATH, m_path)

    collide = j_path.parent / "summary.json"
    collide.write_text("{}\n", encoding="utf-8")
    errs_col = tsea.verify_committed_artifacts(j_path, m_path, repo_root=work)
    assert any("summary.json name collision" in e for e in errs_col)
    collide.unlink()


def test_hygiene_zero_judge_seeds_and_submission_provenance() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]
        assert hash_char not in src
        assert em_dash not in src
        assert en_dash not in src
        assert src.isascii()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    raw_json = SUMMARY_PATH.read_text(encoding="utf-8")
    raw_md = REPORT_PATH.read_text(encoding="utf-8")
    for txt in (raw_json, raw_md):
        assert em_dash not in txt
        assert en_dash not in txt
        assert txt.isascii()

    for m in re.finditer(r"\b\d+\b", raw_json):
        assert int(m.group(0)) < 900_000

    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules

    seed_chk = vts.check_seed_and_secret_provenance(root=REPO_ROOT, strict=True)
    assert seed_chk.passed is True, seed_chk.errors
