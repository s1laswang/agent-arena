"""Unit tests for scripts/harness_and_tier_analysis_v14.py and its v1.4 outputs."""
from __future__ import annotations

import importlib.util
import io
import json
import math
import re
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts/harness_and_tier_analysis_v14.py"
TEST_PATH = ROOT / "tests/test_harness_and_tier_analysis_v14.py"
JSON_PATH = ROOT / "results/eval_v14/harness_and_tier_v14.json"
MD_PATH = ROOT / "docs/reports/medium_vs_hard_and_harness_v14.md"
PAIRED_GEMINI_JSON = ROOT / "data/runs/committed/v1.4/paired_table_gemini.json"


def _load_module():
    spec = importlib.util.spec_from_file_location("harness_and_tier_analysis_v14", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


MOD = _load_module()


@pytest.fixture(scope="module")
def committed_data() -> dict:
    assert JSON_PATH.exists()
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_check_flag_reproduces_committed_outputs():
    rc = MOD.main(["--check"])
    assert rc == 0


def test_check_flag_detects_tampering_and_oversized_json(committed_data: dict, monkeypatch, tmp_path: Path):
    monkeypatch.setattr(MOD, "compute", lambda root=MOD.ROOT: committed_data)
    good_json = tmp_path / "good.json"
    good_md = tmp_path / "good.md"
    assert MOD.main(["--out-json", str(good_json), "--out-md", str(good_md)]) == 0
    assert MOD.main(["--check", "--out-json", str(good_json), "--out-md", str(good_md)]) == 0

    tampered = json.loads(good_json.read_text(encoding="utf-8"))
    tampered["contrasts_2x2"]["raw_score"]["did_hard_minus_medium"]["point"] += 0.01
    bad_json = tmp_path / "bad.json"
    bad_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(bad_json), "--out-md", str(good_md)]) == 1

    bad_md = tmp_path / "bad.md"
    bad_md.write_text(good_md.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(good_json), "--out-md", str(bad_md)]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * 80001, encoding="utf-8")
    assert MOD.main(["--check", "--out-json", str(oversized), "--out-md", str(good_md)]) == 1


def test_2x2_paired_contrasts_and_bootstrap_cis(committed_data: dict):
    ps = committed_data["per_seed"]
    cells = committed_data["cells"]
    ct_raw = committed_data["contrasts_2x2"]["raw_score"]
    ct_la = committed_data["contrasts_2x2"]["luck_adjusted_score"]

    oc_m_raw = ps["medium_opencode"]["score"]
    ip_m_raw = ps["medium_inproc"]["score"]
    oc_h_raw = ps["hard_opencode"]["score"]
    ip_h_raw = ps["hard_inproc"]["score"]

    oc_m_la = ps["medium_opencode"]["luck_adjusted"]
    ip_m_la = ps["medium_inproc"]["luck_adjusted"]
    oc_h_la = ps["hard_opencode"]["luck_adjusted"]
    ip_h_la = ps["hard_inproc"]["luck_adjusted"]

    re_med_raw = MOD.paired_contrast(oc_m_raw, ip_m_raw)
    re_hard_raw = MOD.paired_contrast(oc_h_raw, ip_h_raw)
    re_did_raw = MOD.paired_contrast(
        [a - b for a, b in zip(oc_h_raw, ip_h_raw)],
        [a - b for a, b in zip(oc_m_raw, ip_m_raw)],
    )
    assert MOD.approx_equal(re_med_raw, ct_raw["oc_minus_ip_medium"], tol=1e-6)
    assert MOD.approx_equal(re_hard_raw, ct_raw["oc_minus_ip_hard"], tol=1e-6)
    assert math.isclose(
        ct_raw["did_hard_minus_medium"]["point"],
        ct_raw["oc_minus_ip_hard"]["point"] - ct_raw["oc_minus_ip_medium"]["point"],
        abs_tol=2e-6,
    )
    assert math.isclose(re_did_raw["point"], ct_raw["did_hard_minus_medium"]["point"], abs_tol=1e-6)
    assert re_did_raw["boot_ci95"] == ct_raw["did_hard_minus_medium"]["boot_ci95"]

    assert ct_raw["oc_minus_ip_medium"]["point"] > 0.18
    assert ct_raw["oc_minus_ip_medium"]["boot_ci95"][0] > 0.0
    assert ct_raw["oc_minus_ip_hard"]["point"] < -0.14
    assert ct_raw["did_hard_minus_medium"]["point"] < -0.30
    assert ct_raw["did_hard_minus_medium"]["boot_ci95"][1] < 0.0
    assert ct_raw["did_hard_minus_medium"]["boot_ci95_indep_tiers"][1] < 0.0

    re_med_la = MOD.paired_contrast(oc_m_la, ip_m_la)
    re_hard_la = MOD.paired_contrast(oc_h_la, ip_h_la)
    re_did_la = MOD.paired_contrast(
        [a - b for a, b in zip(oc_h_la, ip_h_la)],
        [a - b for a, b in zip(oc_m_la, ip_m_la)],
    )
    assert MOD.approx_equal(re_med_la, ct_la["oc_minus_ip_medium"], tol=2e-5)
    assert MOD.approx_equal(re_hard_la, ct_la["oc_minus_ip_hard"], tol=2e-5)
    assert math.isclose(
        ct_la["did_hard_minus_medium"]["point"],
        ct_la["oc_minus_ip_hard"]["point"] - ct_la["oc_minus_ip_medium"]["point"],
        abs_tol=2e-5,
    )
    assert MOD.approx_equal(re_did_la["boot_ci95"], ct_la["did_hard_minus_medium"]["boot_ci95"], tol=2e-5)
    assert ct_la["oc_minus_ip_medium"]["point"] > 0.17
    assert ct_la["oc_minus_ip_medium"]["boot_ci95"][0] > 0.0
    assert ct_la["oc_minus_ip_hard"]["point"] < -0.05
    assert ct_la["did_hard_minus_medium"]["point"] < -0.20
    assert ct_la["did_hard_minus_medium"]["boot_ci95"][1] < 0.0
    assert ct_la["did_hard_minus_medium"]["boot_ci95_indep_tiers"][1] < 0.0

    paired_rows = json.loads(PAIRED_GEMINI_JSON.read_text(encoding="utf-8"))
    by_key = {}
    for r in paired_rows:
        if "alternative" in r["label"]:
            continue
        if r["agent"] == "opencode:google/gemini-4-carbon":
            by_key[f"{r['tier']}_opencode"] = r
        elif r["agent"] == "gemini:gemini-4-carbon":
            by_key[f"{r['tier']}_inproc"] = r
        elif r["agent"] == "solver":
            by_key[f"{r['tier']}_solver"] = r

    for key, ref in by_key.items():
        c = cells[key]
        assert math.isclose(c["raw_mean"], ref["mean"], abs_tol=1e-6)
        assert math.isclose(c["luck_adjusted_round3_mean"], ref["post_expected"], abs_tol=1e-6)
        if not key.endswith("_solver"):
            assert math.isclose(c["vs_solver_raw_ratio"], ref["ratio"], abs_tol=1e-6)
            assert math.isclose(c["vs_solver_raw_ratio_boot_ci95"][0], ref["ratio_lo"], abs_tol=1e-6)
            assert math.isclose(c["vs_solver_raw_ratio_boot_ci95"][1], ref["ratio_hi"], abs_tol=1e-6)


def test_six_cell_behavioral_and_crossover_invariants(committed_data: dict):
    cells = committed_data["cells"]
    expected_keys = {
        "medium_opencode",
        "medium_inproc",
        "medium_solver",
        "hard_opencode",
        "hard_inproc",
        "hard_solver",
    }
    assert set(cells.keys()) == expected_keys

    max_bits = math.log2(3.0)
    for key, c in cells.items():
        assert c["n"] == 30
        assert c["accused_count"] + c["abstained_count"] == 30
        assert c["correct_count"] + c["wrong_count"] == c["accused_count"]
        assert 0.0 < c["canary_split_entropy_bits_mean"] <= max_bits + 1e-6
        assert c["canary_group_size_mean"] > 0.0
        assert 1.0 < c["canary_variant_count_mean"] <= 3.0
        assert c["check_leak_feed_calls_mean"] > 0.0
        assert c["read_access_logs_calls_mean"] > 0.0
        assert c["consistent_eq_0_at_accuse"] + c["consistent_eq_1_at_accuse"] + c["consistent_gt_1_at_accuse"] == c["accused_count"]
        if key.startswith("medium_"):
            assert c["days_with_2_canaries_mean"] == 0.0
            assert c["episodes_with_seen_flip_count"] == 0
            assert c["mole_excluded_from_consistent_at_accuse_count"] == 0

    m_oc = cells["medium_opencode"]
    m_ip = cells["medium_inproc"]
    h_oc = cells["hard_opencode"]
    h_ip = cells["hard_inproc"]
    h_sv = cells["hard_solver"]

    assert m_oc["accused_count"] == 30 and m_oc["correct_count"] == 30
    assert m_ip["accused_count"] == 26 and m_ip["abstained_count"] == 4
    assert h_oc["canaries_before_accuse_mean"] < 9.0 < 14.0 < h_sv["canaries_before_accuse_mean"]
    assert h_ip["canaries_before_accuse_mean"] < 9.0 < 14.0 < h_sv["canaries_before_accuse_mean"]
    assert h_oc["days_with_2_canaries_mean"] > 3.0 and h_ip["days_with_2_canaries_mean"] > 3.0
    assert h_oc["interviews_mean"] > 55.0 and h_ip["interviews_mean"] > 55.0 and h_sv["interviews_mean"] == 0.0
    assert h_ip["p_accused_mean"] > h_oc["p_accused_mean"] + 0.04
    assert h_ip["consistent_eq_0_at_accuse"] == 2
    assert h_oc["consistent_eq_0_at_accuse"] == 0


def test_decompositions_and_helper_functions(committed_data: dict):
    for name, dec in committed_data["decompositions"].items():
        t = dec["terms_sum_30_seeds"]
        la_sum = (
            t["posterior_commitment_quality"]
            + t["a_only_accused_gain"]
            + t["a_abstained_loss"]
            + t["leak_timing_value"]
            + t["canary_cost_value"]
            + t["restriction_cost_value"]
        )
        assert math.isclose(dec["luck_adjusted_diff_sum"], la_sum, abs_tol=1e-5), name
        assert math.isclose(dec["raw_diff_sum"], dec["luck_adjusted_diff_sum"] + t["luck_diff"], abs_tol=1e-5), name

    assert math.isclose(MOD.shannon_split_entropy_bits({"e0": "A", "e1": "B", "e2": "C"}), math.log2(3.0), abs_tol=1e-12)
    assert math.isclose(MOD.shannon_split_entropy_bits({"e0": "A", "e1": "A", "e2": "B", "e3": "B"}), 1.0, abs_tol=1e-12)
    assert MOD.shannon_split_entropy_bits({"e0": "A", "e1": "A"}) == 0.0
    assert MOD.approx_equal({"v": [0.1234567890123]}, {"v": [0.1234567890124]})
    assert not MOD.approx_equal({"v": [0.12345]}, {"v": [0.12349]})
    assert not MOD.approx_equal({"b": True}, {"b": 1})


def test_artifact_size_and_strict_hygiene():
    assert JSON_PATH.stat().st_size < 80 * 1024
    assert JSON_PATH.stat().st_size < 80000
    assert MD_PATH.exists() and MD_PATH.stat().st_size > 1000

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"found comment token in {py_path}"
        assert chr(35) not in src, f"found hash char in {py_path}"

    mole_dump_rx = re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = path.read_text(encoding="utf-8")
        assert "\u2013" not in txt and "\u2014" not in txt, f"found em/en dash in {path}"
        assert not mole_dump_rx.search(txt), f"found world_mole_dump pattern in {path}"
