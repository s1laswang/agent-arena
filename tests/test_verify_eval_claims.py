from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary import rules

SCRIPT_PATH = ROOT / "scripts" / "verify_eval_claims.py"
MANIFEST_PATH = ROOT / "results" / "eval_v14" / "claims_manifest.json"
REPORT_PATH = ROOT / "docs" / "reports" / "eval_claims_verification.md"
THIS_TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
H1 = HASH_CHAR + " "
H2 = HASH_CHAR * 2 + " "
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_verifier():
    spec = importlib.util.spec_from_file_location("verify_eval_claims", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verify = _load_verifier()


@pytest.fixture(scope="module")
def real_gates():
    return verify.run_all_gates(ROOT)


def _slice_two_seed_v14_fixture(dst_root: Path) -> Path:
    seeds = {0, 1}
    for rel_dir, _, _ in verify.FRONTIER_V14_RUNS:
        src_ep = ROOT / "data" / "runs" / "committed" / rel_dir / "episodes.jsonl"
        dst_dir = dst_root / "data" / "runs" / "committed" / rel_dir
        dst_dir.mkdir(parents=True, exist_ok=True)
        kept = []
        for ln in src_ep.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            ep = json.loads(ln)
            if int(ep["seed"]) in seeds:
                kept.append(json.dumps(ep))
        (dst_dir / "episodes.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")
        src_meta = ROOT / "data" / "runs" / "committed" / rel_dir / "meta.json"
        if src_meta.is_file():
            shutil.copyfile(src_meta, dst_dir / "meta.json")

    for sol_sub in ("solver-medium-20261114-121126", "solver-hard-20261114-121126"):
        src_ep = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / sol_sub / "episodes.jsonl"
        dst_dir = dst_root / "data" / "runs" / "committed" / "v1.4" / "reference" / sol_sub
        dst_dir.mkdir(parents=True, exist_ok=True)
        kept = []
        for ln in src_ep.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            ep = json.loads(ln)
            if int(ep["seed"]) in seeds:
                kept.append(json.dumps(ep))
        (dst_dir / "episodes.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")

    rows = verify.recompute_paired_v14(dst_root, seeds)
    v14_out = dst_root / "data" / "runs" / "committed" / "v1.4"
    (v14_out / "paired_table_gemini.json").write_text(json.dumps(rows, indent=1) + "\n", encoding="utf-8")

    import paired_gemini

    by_ag: dict[tuple[str, str], dict[str, Any]] = {
        (r["agent"], r["tier"]): r for r in rows if r["label"] != paired_gemini.ALT_LABEL
    }
    oc_h = by_ag[("opencode:google/gemini-4-carbon", "hard")]
    oc_m = by_ag[("opencode:google/gemini-4-carbon", "medium")]
    ip_h = by_ag[("gemini:gemini-4-carbon", "hard")]
    ip_m = by_ag[("gemini:gemini-4-carbon", "medium")]
    fl_h = by_ag[("opencode:google/gemini-3.5-flash", "hard")]
    so_h = by_ag[("solver", "hard")]
    so_m = by_ag[("solver", "medium")]

    oc_h_raw = verify._fmt_pct_ci(oc_h["ratio"], oc_h["ratio_lo"], oc_h["ratio_hi"])
    oc_h_luck = verify._fmt_pct_ci(oc_h["post_expected_ratio"], oc_h["post_expected_lo"], oc_h["post_expected_hi"])
    oc_m_raw = verify._fmt_pct_ci(oc_m["ratio"], oc_m["ratio_lo"], oc_m["ratio_hi"])
    oc_m_luck = verify._fmt_pct_ci(oc_m["post_expected_ratio"], oc_m["post_expected_lo"], oc_m["post_expected_hi"])
    ip_h_raw = verify._fmt_pct_ci(ip_h["ratio"], ip_h["ratio_lo"], ip_h["ratio_hi"])
    ip_h_luck = verify._fmt_pct_ci(ip_h["post_expected_ratio"], ip_h["post_expected_lo"], ip_h["post_expected_hi"])
    ip_m_raw = verify._fmt_pct_ci(ip_m["ratio"], ip_m["ratio_lo"], ip_m["ratio_hi"])
    ip_m_luck = verify._fmt_pct_ci(ip_m["post_expected_ratio"], ip_m["post_expected_lo"], ip_m["post_expected_hi"])

    claim_pct = f"{oc_h['ratio']:.0%}"
    claim_ci = f"{oc_h['ratio_lo']:.0%}".rstrip("%") + "-" + f"{oc_h['ratio_hi']:.0%}"
    oc_h_sc = f"{oc_h['mean']:+.3f} +/- {oc_h['ci']:.3f}"
    so_h_sc = f"{so_h['mean']:+.3f} +/- {so_h['ci']:.3f}"
    fl_h_sc = f"{fl_h['mean']:+.3f} +/- {fl_h['ci']:.3f}"

    readme_lines = [
        H1 + "Canary",
        "",
        f"Claim: in the judges' own harness, gemini-4-carbon earns {claim_pct} of the reference solver's score on Canary's hard tier (95% CI {claim_ci}), while doing nothing scores 0.",
        "",
        H2 + "Result (rules v1.4, hard tier)",
        "",
        "| agent | score +/- 95% CI | % of solver [95% CI] | n |",
        "|---|---:|---:|---:|",
        f"| reference solver | {so_h_sc} | 100% | {so_h['n']} |",
        f"| gemini-4-carbon, OpenCode over MCP | {oc_h_sc} | {oc_h_raw}; luck-adjusted {oc_h_luck} | {oc_h['n']} |",
        "| do_nothing | +0.000 +/- 0.000 | 0% | 40 |",
        "| stop_early | +0.000 +/- 0.000 | 0% | 40 |",
        "",
        f"- Honest reading. The same model run in-process reaches {ip_h_raw} on hard, and OpenCode reaches {oc_m['ratio']:.0%} on medium.",
        f"- What make reproduce does. Gemini row above comes back as {oc_h_sc}.",
    ]
    (dst_root / "README.md").write_text("\n".join(readme_lines) + "\n", encoding="utf-8")

    gap_dir = dst_root / "docs" / "reports"
    gap_dir.mkdir(parents=True, exist_ok=True)
    gap_lines = [
        H1 + "Gap report",
        "",
        H2 + "v1.4 headline",
        "| harness | tier | n | frontier / solver [95% CI] | luck-adjusted / solver [95% CI] |",
        "|---|---|---|---|---|",
        f"| OpenCode over MCP | hard | {oc_h['n']} | {oc_h_raw} | {oc_h_luck} |",
        f"| OpenCode over MCP | medium | {oc_m['n']} | {oc_m_raw} | {oc_m_luck} |",
        f"| in-process | hard | {ip_h['n']} | {ip_h_raw} | {ip_h_luck} |",
        f"| in-process | medium | {ip_m['n']} | {ip_m_raw} | {ip_m_luck} |",
        "",
        f"The solver is paired on all seeds (solver means: hard {so_h['mean']:.3f}, medium {so_m['mean']:.3f}).",
        "Pre-registered extension (f9fb7a4a): seeds 30-59 in opencode-gemini-4-carbon-ext.",
        "Pre-registered second frontier family: gpt-5.5 on v1.4 hard seeds 0-29.",
        "Seed lock (671ed96, post-hoc lock): seeds 0-29 is the PRIMARY result; later reruns are REPLICATION.",
    ]
    (gap_dir / "gap.md").write_text("\n".join(gap_lines) + "\n", encoding="utf-8")

    res_dir = dst_root / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    jt_lines = [
        H1 + "Canary judge table",
        "",
        H2 + "hard (headline)",
        "Reported agent runs: v1.4 (current rules):",
        "| agent | kind | n | invalid | score +/- 95% CI | accuracy | accused | mean accuse day | / solver | pass^k | note |",
        "|---|---|---:|---|---:|---:|---:|---:|---:|---:|---|",
        f"| opencode:google/gemini-3.5-flash | reported | {fl_h['n']} | 0 | {fl_h_sc} | 0.90 | 2/2 | 12.0 | -- | -- | (data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard) |",
    ]
    (res_dir / "judge_table.md").write_text("\n".join(jt_lines) + "\n", encoding="utf-8")
    return dst_root


def test_strict_source_and_artifact_hygiene():
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    test_text = THIS_TEST_PATH.read_text(encoding="utf-8")
    manifest_text = MANIFEST_PATH.read_text(encoding="utf-8")
    report_text = REPORT_PATH.read_text(encoding="utf-8")

    assert HASH_CHAR not in script_text
    assert HASH_CHAR not in test_text
    for blob in (script_text, test_text, manifest_text, report_text):
        assert EM_DASH not in blob
        assert EN_DASH not in blob

    raw_manifest = MANIFEST_PATH.read_bytes()
    assert len(raw_manifest) < verify.MANIFEST_MAX_BYTES
    parsed = json.loads(manifest_text)
    assert parsed["overall_passed"] is True
    assert parsed["tiers_version"] == "v1.4"


def test_real_repo_check_and_json_cli(capsys):
    rc = verify.main(["--check", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["manifest_errors"] == []

    gates = {g["gate"]: g for g in payload["gates"]}
    assert list(gates.keys()) == [
        "gate1_headline_and_gap_table_numbers",
        "gate2_replay_cache_completeness_and_step_consistency",
        "gate3_baselines_and_judge_spread_bands",
        "gate4_version_and_preregistration_hygiene",
        "gate5_protected_paths_and_secret_hygiene",
    ]
    assert all(g["passed"] is True for g in gates.values())

    claims = gates["gate1_headline_and_gap_table_numbers"]["data"]["paired_headline_claims"]
    assert claims["opencode_gemini_4_carbon_hard"]["raw_ratio_ci"] == "65% [24%, 98%]"
    assert claims["opencode_gemini_4_carbon_hard"]["luck_adjusted_ratio_ci"] == "72% [52%, 91%]"
    assert claims["opencode_gemini_4_carbon_medium"]["raw_ratio_ci"] == "111% [99%, 127%]"
    assert claims["opencode_gemini_4_carbon_medium"]["luck_adjusted_ratio_ci"] == "101% [85%, 119%]"
    assert claims["inproc_gemini_4_carbon_hard"]["raw_ratio_ci"] == "95% [62%, 140%]"
    assert claims["inproc_gemini_4_carbon_hard"]["luck_adjusted_ratio_ci"] == "84% [65%, 106%]"
    assert claims["inproc_gemini_4_carbon_medium"]["raw_ratio_ci"] == "82% [56%, 108%]"
    assert claims["inproc_gemini_4_carbon_medium"]["luck_adjusted_ratio_ci"] == "74% [52%, 99%]"
    assert claims["opencode_gemini_3_5_flash_hard"]["raw_ratio_ci"] == "75% [36%, 123%]"
    assert claims["opencode_gemini_3_5_flash_hard"]["luck_adjusted_ratio_ci"] == "22% [-23%, 63%]"
    assert claims["opencode_gpt_5_5_hard"]["raw_ratio_ci"] == "101% [79%, 140%]"
    assert claims["opencode_gpt_5_5_hard"]["luck_adjusted_ratio_ci"] == "84% [67%, 103%]"

    g2 = gates["gate2_replay_cache_completeness_and_step_consistency"]["data"]
    assert sum(r["replay_matched"] for r in g2["frontier_v14_runs"]) == 150
    assert sum(r["replay_matched"] for r in g2["frontier_extension_v14_runs"]) == 32
    assert sum(r["replay_matched"] for r in g2["solver_v14_runs"]) == 90
    sol_by_tier = {r["tier"]: r for r in g2["solver_v14_runs"]}
    assert sol_by_tier["medium"]["n_valid"] == 30
    assert sol_by_tier["hard"]["n_valid"] == 60
    assert g2["ladder_summary"]["native_valid_episodes"] == 550
    assert g2["ladder_summary"]["imported_inproc_valid_episodes"] == 37
    assert g2["ladder_summary"]["total_ladder_episodes"] == 587


def test_approx_equal_and_manifest_float_tolerance(tmp_path, monkeypatch, real_gates):
    assert verify.approx_equal({"v": [0.645958583834]}, {"v": [0.6459585838344]})
    assert not verify.approx_equal({"v": [0.645958583834]}, {"v": [0.645960000000]})
    assert not verify.approx_equal({"flag": True}, {"flag": 1})
    assert not verify.approx_equal({"n": 30}, {"n": 31})

    monkeypatch.setattr(verify, "run_all_gates", lambda *a, **kw: real_gates)
    base_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    within_tol = copy.deepcopy(base_manifest)
    within_tol["paired_headline_claims"]["opencode_gemini_4_carbon_hard"]["ratio"] += 4e-10
    m_ok = tmp_path / "claims_ok.json"
    m_ok.write_text(json.dumps(within_tol), encoding="utf-8")
    assert verify.main(["--check", "--manifest", str(m_ok)]) == 0

    beyond_tol = copy.deepcopy(base_manifest)
    beyond_tol["paired_headline_claims"]["opencode_gemini_4_carbon_hard"]["ratio"] += 1e-5
    m_bad = tmp_path / "claims_bad.json"
    m_bad.write_text(json.dumps(beyond_tol), encoding="utf-8")
    assert verify.main(["--check", "--manifest", str(m_bad)]) == 1


def test_gate1_catches_readme_and_gap_claim_drift(tmp_path):
    syn = _slice_two_seed_v14_fixture(tmp_path / "syn")
    res_ok = verify.gate1_headline_and_gap_table_numbers(syn, expected_seeds=[0, 1])
    assert res_ok.passed is True, res_ok.violations

    orig_readme = (syn / "README.md").read_text(encoding="utf-8")
    (syn / "README.md").write_text(orig_readme.replace("earns ", "earns 999% instead of "), encoding="utf-8")
    res_bad_readme = verify.gate1_headline_and_gap_table_numbers(syn, expected_seeds=[0, 1])
    assert res_bad_readme.passed is False
    assert any("README.md" in v for v in res_bad_readme.violations)
    (syn / "README.md").write_text(orig_readme, encoding="utf-8")

    orig_gap = (syn / "docs" / "reports" / "gap.md").read_text(encoding="utf-8")
    (syn / "docs" / "reports" / "gap.md").write_text(
        orig_gap.replace("| OpenCode over MCP | hard | 2 |", "| OpenCode over MCP | hard | 99 |"),
        encoding="utf-8",
    )
    res_bad_gap = verify.gate1_headline_and_gap_table_numbers(syn, expected_seeds=[0, 1])
    assert res_bad_gap.passed is False
    assert any("gap.md" in v for v in res_bad_gap.violations)


def test_gate2_catches_duplicate_missing_replay_and_timeout(tmp_path, monkeypatch):
    syn = _slice_two_seed_v14_fixture(tmp_path / "syn2")
    res_ok = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_ok.passed is True, res_ok.violations

    ep_file = syn / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    orig_lines = [ln for ln in ep_file.read_text(encoding="utf-8").splitlines() if ln.strip()]

    ep_file.write_text("\n".join([orig_lines[0], orig_lines[0]]) + "\n", encoding="utf-8")
    res_dup = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_dup.passed is False
    assert any("duplicate valid seed" in v for v in res_dup.violations)

    tampered = json.loads(orig_lines[0])
    tampered["score"] = 0.999 if float(tampered["score"]) < 0.9 else 0.111
    tampered["accused"] = "e00"
    tampered["correct"] = True
    ep_file.write_text("\n".join([json.dumps(tampered), orig_lines[1]]) + "\n", encoding="utf-8")
    res_replay = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_replay.passed is False
    assert any("replay mismatch" in v for v in res_replay.violations)

    step_tampered = json.loads(orig_lines[0])
    for st in step_tampered["steps"]:
        if st.get("tool") == "status" and isinstance(st.get("result"), dict):
            st["result"] = {"ok": True, "data": {"tampered": 1}, "error": None}
            break
    ep_file.write_text("\n".join([json.dumps(step_tampered), orig_lines[1]]) + "\n", encoding="utf-8")
    res_step_bad = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_step_bad.passed is False
    assert any("step_mismatches=" in v for v in res_step_bad.violations)

    forged_detail_ep = json.loads(orig_lines[0])
    forged_detail_ep["steps"][3]["result"] = {
        "ok": False,
        "data": {"detail": "forged detail"},
        "error": "invalid arguments",
    }
    ep_file.write_text("\n".join([json.dumps(forged_detail_ep), orig_lines[1]]) + "\n", encoding="utf-8")
    res_forged_detail = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_forged_detail.passed is False
    assert any("step_mismatches=1" in v for v in res_forged_detail.violations)

    timeout_ep = json.loads(orig_lines[0])
    timeout_ep["end_reason"] = "error"
    timeout_ep["meta"] = {"rc": "timeout", "valid": True}
    ep_file.write_text("\n".join([json.dumps(timeout_ep), orig_lines[1]]) + "\n", encoding="utf-8")
    res_timeout = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_timeout.passed is False
    assert any("DATA RULE" in v for v in res_timeout.violations)

    ep_file.write_text("\n".join(orig_lines) + "\n", encoding="utf-8")
    sol_ep_file = (
        syn / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl"
    )
    sol_orig = [ln for ln in sol_ep_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    sol_ep_file.write_text(sol_orig[0] + "\n", encoding="utf-8")
    res_missing_sol = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_missing_sol.passed is False
    assert any("v1.4/reference/solver:hard" in v for v in res_missing_sol.violations)
    sol_ep_file.write_text("\n".join(sol_orig) + "\n", encoding="utf-8")

    monkeypatch.setattr(rules, "TIERS_VERSION", "v1.3")
    res_ver = verify.gate2_replay_cache_completeness_and_step_consistency(syn, expected_seeds=[0, 1])
    assert res_ver.passed is False
    assert any("TIERS_VERSION" in v for v in res_ver.violations)


def test_gate3_catches_baseline_spread_and_oracle_violations(tmp_path):
    res_dir = tmp_path / "results"
    sr_dir = res_dir / "solver_range"
    sr_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / "results" / "judge_episodes.jsonl", res_dir / "judge_episodes.jsonl")
    shutil.copyfile(ROOT / "results" / "judge_table.md", res_dir / "judge_table.md")
    shutil.copyfile(ROOT / "results" / "oracle_range_v1.4.json", res_dir / "oracle_range_v1.4.json")
    shutil.copyfile(ROOT / "README.md", tmp_path / "README.md")
    for p in (ROOT / "results" / "solver_range").glob("*.json"):
        shutil.copyfile(p, sr_dir / p.name)

    assert verify.gate3_baselines_and_judge_spread_bands(tmp_path).passed is True

    je_path = res_dir / "judge_episodes.jsonl"
    orig_je = je_path.read_text(encoding="utf-8")
    bad_line = json.dumps(
        {
            "agent": "do_nothing",
            "tier": "hard",
            "seed": 900099,
            "score": 0.25,
            "accused": "e01",
            "correct": True,
            "end_reason": "accused",
            "final_day": 1,
            "tool_calls": 1,
        }
    )
    je_path.write_text(orig_je + bad_line + "\n", encoding="utf-8")
    res_dn = verify.gate3_baselines_and_judge_spread_bands(tmp_path)
    assert res_dn.passed is False
    assert any("do_nothing" in v for v in res_dn.violations)
    je_path.write_text(orig_je, encoding="utf-8")

    g1_hard = sr_dir / "guess_day1_hard_judge40.json"
    orig_g1 = g1_hard.read_text(encoding="utf-8")
    bad_g1 = json.loads(orig_g1)
    bad_g1["max"] = 0.1
    g1_hard.write_text(json.dumps(bad_g1), encoding="utf-8")
    res_g1 = verify.gate3_baselines_and_judge_spread_bands(tmp_path)
    assert res_g1.passed is False
    assert any("guess_day1_hard_judge40.json" in v for v in res_g1.violations)
    g1_hard.write_text(orig_g1, encoding="utf-8")

    readme = tmp_path / "README.md"
    orig_rm = readme.read_text(encoding="utf-8")
    readme.write_text(orig_rm.replace("+0.39 to +0.68", "+0.10 to +0.99"), encoding="utf-8")
    res_or = verify.gate3_baselines_and_judge_spread_bands(tmp_path)
    assert res_or.passed is False
    assert any("oracle range mismatch" in v for v in res_or.violations)

    assert verify._check_score_invariants({"accused": "e17", "correct": True, "score": 0.0}, "row1", False) == []
    assert verify._check_score_invariants(
        {"accused": "e17", "correct": True, "score": 0.0, "meta": {"rc": 0}}, "row2", False
    ) == []
    assert verify._check_score_invariants(
        {"accused": "e17", "correct": True, "score": 0.0, "meta": {"V": 0.0}}, "row3", False
    ) == []
    err_neg = verify._check_score_invariants({"accused": "e17", "correct": True, "score": -0.2}, "row4", False)
    assert any("score < 0.0" in e for e in err_neg)
    err_vpos = verify._check_score_invariants(
        {"accused": "e17", "correct": True, "score": 0.0, "meta": {"V": 0.45}}, "row5", False
    )
    assert any("contradicts meta V=" in e for e in err_vpos)


def test_gate4_catches_version_mixing_and_stale_claims(tmp_path):
    for rel in verify.ACTIVE_DOCS:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
    v14_dst = tmp_path / "data" / "runs" / "committed" / "v1.4"
    v14_dst.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.json",
        v14_dst / "paired_table_gemini.json",
    )
    shutil.copyfile(
        ROOT / "data" / "runs" / "committed" / "v1.4" / "paired_table_gemini.md",
        v14_dst / "paired_table_gemini.md",
    )
    for mf in (ROOT / "data" / "runs" / "committed" / "v1.4").rglob("meta.json"):
        rel_mf = mf.relative_to(ROOT)
        (tmp_path / rel_mf).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(mf, tmp_path / rel_mf)
    ext_ep_src = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    ext_ep_dst = v14_dst / "opencode-gemini-4-carbon-ext" / "hard" / "episodes.jsonl"
    shutil.copyfile(ext_ep_src, ext_ep_dst)
    gpt_ep_src = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    gpt_ep_dst = v14_dst / "opencode-gpt-5.5" / "hard" / "episodes.jsonl"
    shutil.copyfile(gpt_ep_src, gpt_ep_dst)

    res_init = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_init.passed is True, res_init.violations
    assert res_init.data["posthoc_locked_primary_frontier_cohorts"] == 5
    assert res_init.data["preregistered_extension_frontier_cohorts"] == 2

    ext_mf = v14_dst / "opencode-gemini-4-carbon-ext" / "hard" / "meta.json"
    orig_ext_mf = ext_mf.read_text(encoding="utf-8")
    bad_ext = json.loads(orig_ext_mf)
    bad_ext["seeds"] = [12, 37]
    ext_mf.write_text(json.dumps(bad_ext), encoding="utf-8")
    res_bad_ext = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_bad_ext.passed is False
    assert any("30..59" in v for v in res_bad_ext.violations)
    ext_mf.write_text(orig_ext_mf, encoding="utf-8")

    gpt_dir = v14_dst / "opencode-gpt-5.5" / "hard"
    if gpt_ep_dst.is_file():
        gpt_ep_dst.unlink()
    gpt_dir.mkdir(parents=True, exist_ok=True)
    (gpt_dir / "meta.json").write_text(json.dumps({"tiers_version": "v1.4", "seeds": [0, 1]}), encoding="utf-8")
    assert verify.gate4_version_and_preregistration_hygiene(tmp_path).passed is True
    (gpt_dir / "meta.json").write_text(json.dumps({"tiers_version": "v1.4", "seeds": [35]}), encoding="utf-8")
    res_bad_gpt = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_bad_gpt.passed is False
    assert any("0..29" in v for v in res_bad_gpt.violations)
    shutil.rmtree(v14_dst / "opencode-gpt-5.5")

    gap_p = tmp_path / "docs" / "reports" / "gap.md"
    orig_gap_p = gap_p.read_text(encoding="utf-8")
    gap_p.write_text(orig_gap_p.replace("Seed lock", "Removed rule"), encoding="utf-8")
    res_no_lock = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_no_lock.passed is False
    assert any("Seed lock" in v for v in res_no_lock.violations)
    gap_p.write_text(orig_gap_p, encoding="utf-8")

    pj = v14_dst / "paired_table_gemini.json"
    orig_pj = pj.read_text(encoding="utf-8")
    bad_rows = json.loads(orig_pj)
    bad_rows[0]["group"] = "v1.3/codex-gpt-5.5-full"
    pj.write_text(json.dumps(bad_rows), encoding="utf-8")
    res_mix = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_mix.passed is False
    assert any("v1.3" in v for v in res_mix.violations)
    pj.write_text(orig_pj, encoding="utf-8")

    jt = tmp_path / "results" / "judge_table.md"
    orig_jt = jt.read_text(encoding="utf-8")
    jt.write_text(
        orig_jt.replace(
            "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard",
            "data/runs/committed/superseded/opencode-gemini-4-carbon/hard",
        ),
        encoding="utf-8",
    )
    res_sup = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_sup.passed is False
    assert any("superseded" in v for v in res_sup.violations)
    jt.write_text(orig_jt, encoding="utf-8")

    rm = tmp_path / "README.md"
    orig_rm = rm.read_text(encoding="utf-8")
    rm.write_text(orig_rm + "\nStatus: v1.4 frontier gap: not established.\n", encoding="utf-8")
    res_stale = verify.gate4_version_and_preregistration_hygiene(tmp_path)
    assert res_stale.passed is False
    assert any("frontier_gap_not_established" in v for v in res_stale.violations)


def test_gate5_catches_protected_paths_and_secret_or_mole_leaks(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".github").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / ".github" / "protected-paths.txt", repo / ".github" / "protected-paths.txt")
    (repo / "results" / "eval_v14").mkdir(parents=True, exist_ok=True)
    (repo / "docs" / "reports").mkdir(parents=True, exist_ok=True)
    (repo / "results" / "eval_v14" / "claims_manifest.json").write_text("{}\n", encoding="utf-8")
    (repo / "docs" / "reports" / "eval_claims_verification.md").write_text("clean report\n", encoding="utf-8")
    (repo / "canary").mkdir(parents=True, exist_ok=True)
    (repo / "canary" / "env.py").write_text("x = 1\n", encoding="utf-8")

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "base_branch"], cwd=repo, check=True)

    res_clean = verify.gate5_protected_paths_and_secret_hygiene(repo, base_ref="base_branch")
    assert res_clean.passed is True

    res_override = verify.gate5_protected_paths_and_secret_hygiene(
        repo,
        changed_files_override=["harbor/build.py", "canary/solver/policy.py"],
    )
    assert res_override.passed is False
    assert len(res_override.violations) == 2

    (repo / "canary" / "env.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "canary/env.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "touch protected"], cwd=repo, check=True)
    res_git_prot = verify.gate5_protected_paths_and_secret_hygiene(repo, base_ref="base_branch")
    assert res_git_prot.passed is False
    assert any("canary/env.py" in v for v in res_git_prot.violations)

    subprocess.run(["git", "reset", "--hard", "base_branch"], cwd=repo, check=True)
    fake_key = "AI" + "za" + "SySyntheticTestKey0123456789"
    (repo / "results" / "eval_v14" / "leak.txt").write_text(f"token {fake_key}\n", encoding="utf-8")
    res_key = verify.gate5_protected_paths_and_secret_hygiene(repo, base_ref="base_branch")
    assert res_key.passed is False
    assert any("google_api_key" in v for v in res_key.violations)
    (repo / "results" / "eval_v14" / "leak.txt").unlink()

    mole_json = '{"tier": "hard", "' + "mole" + '": "e07"}'
    (repo / "docs" / "reports" / "leak.md").write_text(mole_json + "\n", encoding="utf-8")
    res_mole = verify.gate5_protected_paths_and_secret_hygiene(repo, base_ref="base_branch")
    assert res_mole.passed is False
    assert any("world_mole_dump" in v for v in res_mole.violations)
    (repo / "docs" / "reports" / "leak.md").unlink()

    demo_placeholder = "dry-run under `CANARY_WORLD_SECRET=canary-demo-live` and \"canary-demo-live\"\n"
    (repo / "docs" / "reports" / "demo_ref.md").write_text(demo_placeholder, encoding="utf-8")
    assert verify.gate5_protected_paths_and_secret_hygiene(repo, base_ref="base_branch").passed is True

    real_world_sec = "CANARY_WORLD_SECRET=" + "canary-demo-live-real-secret\n"
    (repo / "docs" / "reports" / "demo_ref.md").write_text(real_world_sec, encoding="utf-8")
    res_real_sec = verify.gate5_protected_paths_and_secret_hygiene(repo, base_ref="base_branch")
    assert res_real_sec.passed is False
    assert any("secret_env_assignment" in v for v in res_real_sec.violations)
