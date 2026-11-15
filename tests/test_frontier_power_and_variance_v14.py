"""Tests for scripts/frontier_power_and_variance_v14.py and its JSON/Markdown deliverables."""
from __future__ import annotations

import importlib.util
import io
import json
import math
import os
import random
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import Step

SCRIPT_PATH = SCRIPTS_DIR / "frontier_power_and_variance_v14.py"
TEST_PATH = Path(__file__).resolve()
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "power_and_variance_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_power_and_variance_v14.md"

MODULE_NAME = "frontier_power_and_variance_v14_mod"
INITIAL_ALLOW_DEV = os.environ.get("CANARY_ALLOW_DEV")

EXPECTED_IDS_GATED = [
    "opencode_gemini_4_carbon_hard",
    "opencode_gemini_4_carbon_medium",
    "inproc_gemini_4_carbon_hard",
    "inproc_gemini_4_carbon_medium",
    "opencode_gpt_5_5_hard",
    "opencode_gemini_3_5_flash_medium",
    "g2_opencode_gemini_4_argon_hard",
    "g2_opencode_gemini_4_hydrogen_hard",
]

EXPECTED_IDS_ALL = EXPECTED_IDS_GATED + ["opencode_gemini_3_5_flash_hard"]


def _load_mod():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


fpv = _load_mod()


def _forbid_subprocess(mp: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess forbidden: {args}")

    mp.setattr(subprocess, "run", _fail)
    mp.setattr(subprocess, "Popen", _fail)
    mp.setattr(subprocess, "check_call", _fail)
    mp.setattr(subprocess, "check_output", _fail)


def _strip_keys(mp: pytest.MonkeyPatch) -> None:
    for var in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
        mp.setenv(var, "")
    for var in ("GOOGLE_GENERATIVE_AI_API_KEY", "ANTHROPIC_API_KEY", "CANARY_WORLD_SECRET"):
        mp.delenv(var, raising=False)


@pytest.fixture(scope="module")
def audit_data():
    env_outer = dict(os.environ)
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    _strip_keys(mp)
    env_inner = dict(os.environ)
    try:
        out = fpv.compute_audit(root=ROOT, enforce_expected_counts=True)
        assert dict(os.environ) == env_inner
    finally:
        mp.undo()
    assert dict(os.environ) == env_outer
    assert os.environ.get("CANARY_ALLOW_DEV") == INITIAL_ALLOW_DEV
    return out


def test_hygiene_ascii_no_dashes_no_hash_comments_no_secrets():
    assert MODULE_NAME in sys.modules
    assert os.environ.get("CANARY_ALLOW_DEV") == INITIAL_ALLOW_DEV
    forbidden_prefixes = ("AI" + "za", "s" + "k-proj-", "gh" + "p_", "BEGIN " + "PRIVATE KEY")
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        raw = path.read_bytes()
        text = raw.decode("ascii")
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text
        for pref in forbidden_prefixes:
            assert pref not in text
    assert 0 < JSON_PATH.stat().st_size <= 38_000
    for py_path in (SCRIPT_PATH, TEST_PATH):
        py_bytes = py_path.read_bytes()
        assert 35 not in py_bytes
        toks = list(tokenize.tokenize(io.BytesIO(py_bytes).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]


def test_variance_reduction_and_bootstrap_ci_spans(audit_data, monkeypatch):
    env_before = dict(os.environ)
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    monkeypatch.setattr(fpv, "compute_audit", lambda root=ROOT, enforce_expected_counts=True: audit_data)
    assert fpv.main(["--check"]) == 0
    assert JSON_PATH.read_text(encoding="utf-8") == fpv.serialize_json(audit_data)
    assert MD_PATH.read_text(encoding="utf-8") == fpv.render_markdown(audit_data)

    assert audit_data["tiers_version"] == "v1.4"
    assert audit_data["upstream_justsilas_sync_commit"] == "5f9b3297"
    assert audit_data["zero_live_api_calls"] is True
    assert audit_data["zero_subprocesses"] is True
    assert audit_data["zero_git_dependency"] is True

    prov = audit_data["provenance"]
    assert prov["upstream_head_commit"] == "5f9b3297"
    assert prov["committed_v14_episodes"] == 472
    assert prov["replication_v14_episodes"] == 305
    assert prov["combined_v14_episodes"] == 777
    assert prov["replay_mismatches"] == 0
    assert prov["valid_jsonl_timeout_error_episodes"] == 0
    assert prov["g2_hard_0_29_episodes"] == 60
    assert prov["primary_0_29_lock_classification"] == "post_hoc_lock"
    assert prov["primary_0_29_lock_commit"] == "671ed96"
    assert prov["primary_0_29_episodes_commit"] == "8fd4dec"
    assert prov["primary_0_29_lock_delay_s"] == 28
    assert prov["gpt_5_5_clean_rc0_non_accuse_seeds"] == [0, 17]
    assert prov["g1_seeds"] == [34, 37]
    assert prov["fr8_rep_seeds"] == [30, 34, 42, 45, 57]
    assert prov["carbon_hard_30_59_dedup_union_seeds"] == [30, 34, 37, 42, 45, 57]
    assert prov["harbor_rehearsal_final_commit"] == "d0ead011"
    assert prov["harbor_rehearsal_ratios_pct"] == [93, 116, 131]
    assert prov["harbor_rehearsal_valid_trials"] == [10, 10, 9]

    ships_flash = fpv.gap_ships_flash_hard(ROOT)
    exp_ids = EXPECTED_IDS_ALL if ships_flash else EXPECTED_IDS_GATED
    cohorts = audit_data["cohorts"]
    assert [c["cohort_id"] for c in cohorts] == exp_ids
    assert all(c["n"] == 30 for c in cohorts)

    by_id = {c["cohort_id"]: c for c in cohorts}
    ch = by_id["opencode_gemini_4_carbon_hard"]
    assert ch["wrong_cliff_seeds"] == [1, 15, 18, 26]
    assert ch["solver_wrong_cliff_seeds"] == [15]
    assert ch["raw"]["ratio_ci_rounded_pct"] == [24, 98]
    assert ch["raw"]["ratio_ci_rounded_span_pp"] == 74
    assert ch["luck_adjusted"]["ratio_ci_rounded_pct"] == [52, 91]
    assert ch["luck_adjusted"]["ratio_ci_rounded_span_pp"] == 39
    assert math.isclose(ch["variance_reduction"]["vrf_paired_diff"], 3.47872, abs_tol=1e-4)
    assert math.isclose(ch["variance_reduction"]["n_eff_at_30"], 104.36156, abs_tol=1e-3)
    assert ch["variance_reduction"]["wrong_cliff_share_of_raw_ss"] > 0.78

    gp = by_id["opencode_gpt_5_5_hard"]
    assert gp["wrong_cliff_count"] == 0
    assert gp["abstain_seeds"] == [0, 17]
    assert round(gp["raw"]["ratio_vs_solver"] * 100) == 101
    assert round(gp["luck_adjusted"]["ratio_vs_solver"] * 100) == 84
    assert gp["variance_reduction"]["vrf_paired_diff"] > 2.0

    ar = by_id["g2_opencode_gemini_4_argon_hard"]
    hy = by_id["g2_opencode_gemini_4_hydrogen_hard"]
    assert round(ar["raw"]["ratio_vs_solver"] * 100) == 103
    assert round(ar["luck_adjusted"]["ratio_vs_solver"] * 100) == 60
    assert round(hy["raw"]["ratio_vs_solver"] * 100) == 115
    assert round(hy["luck_adjusted"]["ratio_vs_solver"] * 100) == 97

    for c in cohorts:
        vr = c["variance_reduction"]
        rw, la = c["raw"], c["luck_adjusted"]
        assert math.isclose(rw["paired_diff_var"] / la["paired_diff_var"], vr["vrf_paired_diff"], rel_tol=1e-4, abs_tol=1e-4)
        assert math.isclose(30.0 * vr["vrf_paired_diff"], vr["n_eff_at_30"], rel_tol=1e-4, abs_tol=1e-4)
        if c["tier"] == "hard":
            assert vr["vrf_paired_diff"] > 1.3
            assert rw["ratio_ci_span_pp"] > la["ratio_ci_span_pp"]

    monkeypatch.undo()
    assert dict(os.environ) == env_before


def test_mde_curves_boot_and_belief_parity(audit_data):
    assert audit_data["parameters"]["sample_sizes"] == [6, 9, 10, 20, 30, 32, 35, 36, 60]
    for row in audit_data["mde_critical_constants"]:
        df = row["df"]
        assert math.isclose(fpv.two_sided_t_power(0.0, df), 0.05, abs_tol=1e-5)
        assert math.isclose(fpv.two_sided_t_power(row["delta_mde_t_80"], df), 0.80, abs_tol=1e-4)
        assert row["delta_mde_t_80"] > row["delta_mde_z_80"]

    by_id = {c["cohort_id"]: c for c in audit_data["cohorts"]}
    ch = by_id["opencode_gemini_4_carbon_hard"]
    srq = ch["sample_size_requirements_80pct_power"]
    assert srq["la_n_req_t_obs_gap"] == 36
    assert srq["la_n_req_z_obs_gap"] == 34
    assert srq["raw_n_req_t_obs_gap"] == 76
    assert srq["raw_n_req_z_obs_gap"] == 74
    assert srq["raw_n_req_t_15pct_solver"] > 3 * srq["la_n_req_t_15pct_solver"]

    for c in audit_data["cohorts"]:
        for metric in ("raw", "post_expected"):
            rows = [dict(zip(audit_data["mde_curve_columns"], r)) for r in c["mde_curve"][metric]]
            assert [r["n"] for r in rows] == [6, 9, 10, 20, 30, 32, 35, 36, 60]
            mde_t_seq = [r["mde_t_score"] for r in rows]
            mde_z_seq = [r["mde_z_score"] for r in rows]
            pow_seq = [r["power_t_at_obs_gap"] for r in rows]
            assert mde_t_seq == sorted(mde_t_seq, reverse=True)
            assert mde_z_seq == sorted(mde_z_seq, reverse=True)
            assert pow_seq == sorted(pow_seq)
            assert all(r["mde_t_score"] > r["mde_z_score"] for r in rows)

    rng = random.Random(7)
    f_vec = [0.1 * ((i % 7) - 2) for i in range(30)]
    s_vec = [0.4 + 0.02 * (i % 5) for i in range(30)]
    ref_vals = []
    for _ in range(500):
        idx = [rng.randrange(30) for _ in range(30)]
        ms = sum(s_vec[i] for i in idx) / 30.0
        if ms > 0.0:
            ref_vals.append(sum(f_vec[i] for i in idx) / 30.0 / ms)
    ref_vals.sort()
    r_lo, r_hi = ref_vals[int(0.025 * len(ref_vals))], ref_vals[int(0.975 * len(ref_vals)) - 1]
    f_lo, f_hi = fpv.fast_boot_ratio(f_vec, s_vec, resamples=500, seed=7)
    assert math.isclose(r_lo, f_lo, abs_tol=1e-12)
    assert math.isclose(r_hi, f_hi, abs_tol=1e-12)

    for rel in (
        "data/runs/committed/v1.4/reference/solver-medium-20261114-121126/episodes.jsonl",
        "data/runs/committed/v1.4/reference/solver-hard-20261114-121126/episodes.jsonl",
    ):
        with (ROOT / rel).open(encoding="utf-8") as fh:
            ep = json.loads(fh.readline())
        steps_raw = ep.get("steps") or []
        acc_idx = next((i for i, s in enumerate(steps_raw) if s.get("tool") == "accuse"), len(steps_raw))
        steps_pre = [Step(s.get("t", 0), s.get("day", 0), s.get("tool", ""), s.get("args") or {}, s.get("result")) for s in steps_raw[:acc_idx]]
        sp = SolverPolicy(tier_params_for_episode(str(ep["tier"]), steps_pre))
        for st in steps_pre:
            sp._ingest(st)
        sp.seen = acc_idx
        p_ref = sp.belief()
        p_fast = fpv._fast_belief(sp)
        assert p_ref.keys() == p_fast.keys()
        for emp in p_ref:
            assert math.isclose(p_ref[emp], p_fast[emp], rel_tol=1e-12, abs_tol=1e-12)


def test_harbor_n10_exact_combinatorial_and_gitless_cli_roundtrip(audit_data, monkeypatch, tmp_path, capsys):
    env_before = dict(os.environ)
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    hr = audit_data["harbor_n10_subsample_reconciliation"]
    hm = hr["headline_n10_exact_metrics"]
    ex10 = hr["exact_combinatorial"]["n_10"]
    ex9 = hr["exact_combinatorial"]["n_9"]

    assert math.isclose(sum(ex10["hypergeometric_pmf"].values()), 1.0, abs_tol=1e-6)
    assert math.isclose(sum(ex9["hypergeometric_pmf"].values()), 1.0, abs_tol=1e-6)
    assert math.isclose(hm["p_zero_wrong_wor_hypergeom"], math.comb(26, 10) / math.comb(30, 10), abs_tol=1e-5)
    assert math.isclose(hm["p_le_one_wrong_wor_hypergeom"], (math.comb(26, 10) + 4 * math.comb(26, 9)) / math.comb(30, 10), abs_tol=1e-5)
    assert math.isclose(hm["p_zero_wrong_wr_binomial"], (26.0 / 30.0) ** 10, abs_tol=1e-5)
    assert ex10["exact_wor_ratio_tails"]["ge_0.93"]["favorable_subsets"] == 5_359_872
    assert ex10["exact_wor_ratio_tails"]["ge_1.00"]["favorable_subsets"] == 3_460_206
    assert ex10["exact_wor_ratio_tails"]["ge_0.93"]["total_subsets"] == 30_045_015

    mc_wor = hr["monte_carlo_10k"]["n10_without_replacement"]
    assert abs(mc_wor["empirical_p_zero_wrong"] - hm["p_zero_wrong_wor_hypergeom"]) < 0.015
    assert abs(mc_wor["tail_probs_raw_ratio"]["ge_0.93"] - hm["p_ratio_ge_0_93_wor_exact"]) < 0.015
    assert abs(mc_wor["tail_probs_raw_ratio"]["ge_1.00"] - hm["p_ratio_ge_1_00_wor_exact"]) < 0.015

    toy_f = [100] * 12 + [0] * 18
    toy_s = [100] * 30
    t10, t9 = fpv._exact_wor_ratio_tails_pair(toy_f, toy_s, thresholds=((100, 100),))
    assert t10["ge_1.00"]["favorable_subsets"] == math.comb(12, 10)
    assert t9["ge_1.00"]["favorable_subsets"] == math.comb(12, 9)

    mock_root = tmp_path / "gitless_ws"
    (mock_root / "data" / "runs" / "committed").mkdir(parents=True)
    (mock_root / "results" / "frontier_replication").mkdir(parents=True)
    (mock_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(ROOT / "data/runs/committed/v1.4", mock_root / "data/runs/committed/v1.4")
    os.symlink(ROOT / "results/frontier_replication/v1.4", mock_root / "results/frontier_replication/v1.4")
    assert not (mock_root / ".git").exists()
    gap_file = mock_root / "docs/reports/gap.md"
    out_j = tmp_path / "out.json"
    out_m = tmp_path / "out.md"

    gap_file.write_text("Primary headline: gemini-4-carbon hard 65%\n", encoding="utf-8")
    assert fpv.gap_ships_flash_hard(mock_root) is False

    real_compute = fpv.compute_audit
    monkeypatch.setattr(fpv, "compute_audit", lambda root=ROOT, enforce_expected_counts=True: audit_data)
    assert fpv.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--write", "--check", "--stdout"]) == 0
    captured = capsys.readouterr().out
    assert "Canary v1.4 Statistical Power" in captured
    assert "gemini-3.5-flash hard" not in captured

    orig_md = out_m.read_text(encoding="utf-8")
    out_m.write_text(orig_md + "\ntampered\n", encoding="utf-8")
    assert fpv.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--check"]) == 1
    out_m.write_text(orig_md + chr(0x2014) + "\n", encoding="utf-8")
    assert fpv.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--check"]) == 1
    out_m.write_text(orig_md, encoding="utf-8")

    tampered_json = json.loads(out_j.read_text(encoding="utf-8"))
    tampered_json["cohorts"][0]["raw"]["mean"] = 0.999
    out_j.write_text(json.dumps(tampered_json), encoding="utf-8")
    assert fpv.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--check"]) == 1

    gap_file.write_text("Includes gemini-3.5-flash hard 0-29\n", encoding="utf-8")
    assert fpv.gap_ships_flash_hard(mock_root) is True
    real_eval = fpv._eval_episode

    def _fast_flash_eval(ep):
        if ep.get("agent") == "opencode:google/gemini-3.5-flash" and ep.get("tier") == "hard":
            sc = float(ep["score"])
            return {
                "seed": int(ep["seed"]),
                "accused": ep.get("accused"),
                "correct": bool(ep.get("correct")),
                "raw": sc,
                "v_true": max(0.0, sc),
                "p_accused": 0.8 if ep.get("accused") else None,
                "luck": 0.8 * max(0.0, sc) - 0.2 if ep.get("accused") else 0.0,
            }
        return real_eval(ep)

    monkeypatch.setattr(fpv, "compute_audit", real_compute)
    monkeypatch.setattr(fpv, "_eval_episode", _fast_flash_eval)
    audit_true = fpv.compute_audit(root=mock_root, enforce_expected_counts=True)
    assert [c["cohort_id"] for c in audit_true["cohorts"]] == EXPECTED_IDS_ALL
    assert len(fpv.serialize_json(audit_true).encode("utf-8")) <= 38_000

    monkeypatch.undo()
    assert dict(os.environ) == env_before
    assert os.environ.get("CANARY_ALLOW_DEV") == INITIAL_ALLOW_DEV
