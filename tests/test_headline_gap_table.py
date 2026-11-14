"""Fast (<10s) unit tests for scripts/headline_gap_table.py and committed v1.4 headline artifacts."""
from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import headline_gap_table as hgt
from canary.gemini import dashboard as gemini_dashboard


def test_wilson_ci_bounds_and_symmetry():
    lo0, hi0 = hgt.wilson_ci(0.0, 30)
    lo1, hi1 = hgt.wilson_ci(1.0, 30)
    assert lo0 == 0.0
    assert hi1 == 1.0
    assert math.isclose(hi0, 1.0 - lo1, abs_tol=1e-12)
    assert 0.10 < hi0 < 0.13

    lom, him = hgt.wilson_ci(0.80, 30)
    assert 0.62 < lom < 0.64
    assert 0.90 < him < 0.91

    lon, hin = hgt.wilson_ci(0.5, 0)
    assert math.isnan(lon) and math.isnan(hin)


def test_boot_ratio_deterministic_and_edge_cases():
    f = [0.6, 0.8, -1.0, 0.7, 0.5, 0.9, 0.65, 0.75, 0.8, 0.7]
    s = [0.8, 0.8, 0.7, 0.8, 0.6, 0.9, 0.7, 0.8, 0.8, 0.8]
    lo_a, hi_a = hgt.boot_ratio(f, s, B=2000, rng_seed=0)
    lo_b, hi_b = hgt.boot_ratio(f, s, B=2000, rng_seed=0)
    assert lo_a == lo_b and hi_a == hi_b
    point = (sum(f) / len(f)) / (sum(s) / len(s))
    assert lo_a < point < hi_a

    lo_ident, hi_ident = hgt.boot_ratio(s, s, B=1000, rng_seed=0)
    assert math.isclose(lo_ident, 1.0, abs_tol=1e-12)
    assert math.isclose(hi_ident, 1.0, abs_tol=1e-12)

    lo_one, hi_one = hgt.boot_ratio([0.5], [0.6])
    assert math.isnan(lo_one) and math.isnan(hi_one)

    lo_neg, hi_neg = hgt.boot_ratio([0.1, 0.2, 0.3], [-1.0, -0.5, 0.0], B=500, rng_seed=0)
    assert math.isnan(lo_neg) and math.isnan(hi_neg)


def test_paired_wilcoxon_and_sign_test():
    assert math.isclose(hgt.wilcoxon_pvalue([1.0, 2.0, 3.0, 4.0, 5.0]), 0.0625, abs_tol=1e-12)
    assert math.isclose(hgt.sign_test_pvalue([1.0, 2.0, 3.0, 4.0, 5.0]), 0.0625, abs_tol=1e-12)
    assert math.isclose(hgt.wilcoxon_pvalue([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), 0.03125, abs_tol=1e-12)
    assert math.isclose(hgt.sign_test_pvalue([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]), 0.03125, abs_tol=1e-12)
    assert hgt.wilcoxon_pvalue([0.0, 0.0, 0.0]) == 1.0
    assert hgt.sign_test_pvalue([0.0, 0.0, 0.0]) == 1.0
    assert math.isclose(hgt.wilcoxon_pvalue([-2.0, -1.0, 1.0, 2.0]), 1.0, abs_tol=1e-12)
    p_ties = hgt.wilcoxon_pvalue([0.5, 0.5, 0.5, 0.5, -0.1])
    assert 0.0 < p_ties < 0.25


def test_luck_adjusted_ev_and_posterior_pass3():
    assert hgt.luck_adjusted_ev(None, None, 0.85) == 0.0
    assert hgt.luck_adjusted_ev(None, 0.9, 0.85) == 0.0
    assert hgt.luck_adjusted_ev("e01", None, 0.85) is None
    assert math.isclose(hgt.luck_adjusted_ev("e01", 1.0, 0.72), 0.72, abs_tol=1e-12)
    assert math.isclose(hgt.luck_adjusted_ev("e01", 0.0, 0.72), -1.0, abs_tol=1e-12)
    assert math.isclose(hgt.luck_adjusted_ev("e01", 0.5, 0.80), -0.10, abs_tol=1e-12)

    p3 = hgt.posterior_pass_k([1.0, 0.5, 0.0], k=3)
    assert math.isclose(p3, (1.0 + 0.125 + 0.0) / 3.0, abs_tol=1e-12)


def test_winnable_world_filter():
    f_scores = [0.6, -1.0, 0.8, 0.5, 0.7]
    s_scores = [0.8, 0.0, 0.8, -1.0, 0.7]
    seeds = [0, 1, 2, 3, 4]
    w = hgt.winnable_filter(f_scores, s_scores, seeds, B=1000, rng_seed=0)
    assert w["winnable_n"] == 3
    assert w["excluded_n"] == 2
    assert w["excluded_seeds"] == [1, 3]
    expected_ratio = ((0.6 + 0.8 + 0.7) / 3.0) / ((0.8 + 0.8 + 0.7) / 3.0)
    assert math.isclose(w["winnable_ratio"], expected_ratio, abs_tol=1e-12)
    assert w["winnable_ratio_lo"] <= w["winnable_ratio"] <= w["winnable_ratio_hi"]


def test_committed_artifacts_section_a_invariants_and_headline_numbers():
    assert hgt.OUT_JSON.exists()
    assert hgt.OUT_MD.exists()
    raw_bytes = hgt.OUT_JSON.read_bytes()
    assert len(raw_bytes) < 100_000

    data = json.loads(raw_bytes.decode("utf-8"))
    sec_a = data["section_a"]
    sec_b = data["section_b"]
    hgt.check_section_a_invariants(sec_a, root=ROOT)
    assert all(r["n"] >= 30 for r in sec_a)
    assert len(sec_a) == 23
    assert len(sec_b) == 32
    assert data["verification"]["ladder_cached_episodes_replayed"] == 320
    assert data["verification"]["ladder_total_reported_episodes"] == 357
    assert all(r["n"] < 30 and r["small_n_directional"] is True for r in sec_b)

    bad_n = copy.deepcopy(sec_a)
    bad_n[0]["n"] = 29
    with pytest.raises(ValueError, match="n=29 < 30"):
        hgt.check_section_a_invariants(bad_n, root=ROOT)

    bad_cache = copy.deepcopy(sec_a)
    bad_cache[0]["cache_path"] = "data/runs/committed/v1.4/nonexistent/episodes.jsonl"
    with pytest.raises(ValueError, match="Missing committed cache path"):
        hgt.check_section_a_invariants(bad_cache, root=ROOT)

    flash = next(r for r in sec_a if r["agent"] == "opencode:google/gemini-3.5-flash" and r["tier"] == "hard")
    assert flash["n"] == 30
    assert round(flash["mean"], 3) == 0.373
    assert round(flash["score_ci"], 3) == 0.177
    assert round(flash["ratio"] * 100) == 75
    assert round(flash["ratio_lo"] * 100) == 36
    assert round(flash["ratio_hi"] * 100) == 123
    assert round(flash["mean_p_accused"], 2) == 0.71
    assert round(flash["luck_adjusted_score"], 3) == 0.110
    assert round(flash["luck_adj_ratio"] * 100) == 22
    assert round(flash["luck_adj_lo"] * 100) == -23
    assert round(flash["luck_adj_hi"] * 100) == 63

    oc_hard = next(
        r for r in sec_a if r["agent"] == "opencode:google/gemini-4-carbon" and r["tier"] == "hard" and r["kind"] == "frontier"
    )
    assert round(oc_hard["ratio"] * 100) == 65
    assert round(oc_hard["luck_adj_ratio"] * 100) == 72

    assert hgt.render_md(data) + "\n" == hgt.OUT_MD.read_text(encoding="utf-8")


def test_leaderboard_v14_hard_schema_and_dashboard_compat():
    assert hgt.OUT_LEADERBOARD.exists()
    lb = json.loads(hgt.OUT_LEADERBOARD.read_text(encoding="utf-8"))
    assert lb["tier"] == "hard"
    assert lb["tiers_version"] == "v1.4"
    assert lb["seeds"] == "0-29"
    hgt.check_leaderboard_v14_hard(lb)

    rows = lb["rows"]
    assert len(rows) == 11
    by_name = {r["name"]: r for r in rows}
    for req in hgt.LEADERBOARD_REQUIRED_NAMES:
        assert req in by_name
        assert by_name[req]["n"] == 30
        assert tuple(by_name[req].keys()) == hgt.LEADERBOARD_KEYS

    oc_carbon = by_name["opencode:google/gemini-4-carbon"]
    assert round(oc_carbon["score"], 3) == 0.322
    assert round(oc_carbon["pct_solver"] * 100) == 65
    assert [round(x * 100) for x in oc_carbon["pct_solver_ci"]] == [24, 98]
    assert round(oc_carbon["luck_adjusted_score"], 3) == 0.360
    assert round(oc_carbon["luck_adjusted_pct_solver"] * 100) == 72
    assert [round(x * 100) for x in oc_carbon["luck_adjusted_pct_solver_ci"]] == [52, 91]

    oc_flash = by_name["opencode:google/gemini-3.5-flash"]
    assert round(oc_flash["score"], 3) == 0.373
    assert round(oc_flash["pct_solver"] * 100) == 75
    assert round(oc_flash["luck_adjusted_pct_solver"] * 100) == 22

    inproc_carbon = by_name["gemini:gemini-4-carbon"]
    assert round(inproc_carbon["score"], 3) == 0.473
    assert round(inproc_carbon["pct_solver"] * 100) == 95
    assert round(inproc_carbon["luck_adjusted_pct_solver"] * 100) == 84

    sol = by_name["reference solver"]
    assert round(sol["score"], 3) == 0.499
    assert sol["pct_solver"] == 1.0
    assert sol["pct_solver_ci"] is None
    assert sol["luck_adjusted_pct_solver"] == 1.0
    assert sol["luck_adjusted_pct_solver_ci"] is None

    slim = gemini_dashboard.slim_leaderboard(
        {
            "kind": "leaderboard",
            "source": "results/leaderboard_v14_hard.json",
            "source_sha": "deadbeef",
            "source_json": lb,
        }
    )
    assert slim["rows"] == rows

    bad_nested = copy.deepcopy(lb)
    bad_nested["rows"][0]["compute"] = {"gpu": 0}
    with pytest.raises(ValueError, match="not scalar or \\[lo, hi\\]"):
        hgt.check_leaderboard_v14_hard(bad_nested)

    bad_missing = copy.deepcopy(lb)
    bad_missing["rows"] = [r for r in bad_missing["rows"] if r["name"] != "grok_tactics"]
    with pytest.raises(ValueError, match="missing required hard n=30 cohorts"):
        hgt.check_leaderboard_v14_hard(bad_missing)


def test_env_replay_truncated_and_tamper_detection():
    ep_path = ROOT / "data/runs/committed/v1.4/opencode-gemini-3.5-flash/hard/episodes.jsonl"
    seed2 = next(
        json.loads(line)
        for line in ep_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["seed"] == 2
    )
    rec = hgt.replay_verify_episode(seed2)
    assert rec["steps_truncated_checked"] == 1
    assert rec["steps_client_only"] == 1
    assert math.isclose(rec["score"], float(seed2["score"]), abs_tol=1e-9)

    tampered = copy.deepcopy(seed2)
    tampered["score"] = float(seed2["score"]) + 0.25
    with pytest.raises(ValueError, match="Env replay mismatch"):
        hgt.replay_verify_episode(tampered)


def test_check_flag_mode_and_float_tolerance(tmp_path, monkeypatch):
    stored = json.loads(hgt.OUT_JSON.read_text(encoding="utf-8"))
    monkeypatch.setattr(hgt, "compute", lambda _root=ROOT: copy.deepcopy(stored))

    assert hgt.main(["--check"]) == 0

    j_path = tmp_path / "table.json"
    m_path = tmp_path / "table.md"
    lb_path = tmp_path / "leaderboard_v14_hard.json"
    out_flags = ["--out-json", str(j_path), "--out-md", str(m_path), "--out-leaderboard", str(lb_path)]
    assert hgt.main(out_flags) == 0
    assert hgt.main(["--check", *out_flags]) == 0

    jittered = json.loads(j_path.read_text(encoding="utf-8"))
    jittered["section_a"][0]["mean"] += 1e-12
    j_path.write_text(json.dumps(jittered), encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 0

    drifted = json.loads(j_path.read_text(encoding="utf-8"))
    drifted["section_a"][0]["mean"] += 1e-4
    j_path.write_text(json.dumps(drifted), encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 1

    j_path.write_text(hgt.OUT_JSON.read_text(encoding="utf-8"), encoding="utf-8")
    drifted_lb = json.loads(lb_path.read_text(encoding="utf-8"))
    drifted_lb["rows"][0]["score"] += 1e-4
    lb_path.write_text(json.dumps(drifted_lb), encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 1

    lb_path.write_text(hgt.OUT_LEADERBOARD.read_text(encoding="utf-8"), encoding="utf-8")
    m_path.write_text(m_path.read_text(encoding="utf-8") + "tamper\n", encoding="utf-8")
    assert hgt.main(["--check", *out_flags]) == 1

    assert hgt.main(["--check", "--out-json", str(tmp_path / "missing.json"), "--out-md", str(m_path), "--out-leaderboard", str(lb_path)]) == 1
    assert hgt.main(["--check", "--out-json", str(j_path), "--out-md", str(m_path), "--out-leaderboard", str(tmp_path / "missing_lb.json")]) == 1
