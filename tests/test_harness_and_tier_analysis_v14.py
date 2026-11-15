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


def test_cross_family_hard_gpt55_and_harbor_harness(committed_data: dict):
    cf = committed_data["cross_family_hard_gpt55"]
    g = cf["summary"]
    bcm = cf["behaviour_compare_metrics"]
    pvc = cf["paired_vs_carbon_opencode"]
    ps_gpt = cf["per_seed"]
    ps_oc = committed_data["per_seed"]["hard_opencode"]

    assert cf["agent"] == "opencode:openai/gpt-5.5"
    assert cf["preregistration_commit"] == "cf394894"
    assert cf["run_commit"] == "ca0a0dc0"
    assert cf["n"] == 30 and cf["infra_failures"] == 0 and cf["replay_mismatches"] == 0
    assert cf["completed_meta_V_final_populated_count"] == 28

    assert g["n"] == 30
    assert g["accused_count"] == 28 and g["correct_count"] == 28 and g["wrong_count"] == 0
    assert g["abstained_count"] == 2 and g["abstained_seeds"] == [0, 17]
    assert math.isclose(g["raw_mean"], 0.503667, abs_tol=1e-6)
    assert math.isclose(g["raw_ci95_norm"], 0.063789, abs_tol=1e-5)
    assert math.isclose(g["vs_solver_raw_ratio"], 1.009352, abs_tol=1e-5)
    assert math.isclose(g["luck_adjusted_mean"], 0.41762, abs_tol=1e-5)
    assert math.isclose(g["vs_solver_luck_adjusted_ratio"], 0.836415, abs_tol=1e-5)
    assert math.isclose(g["accuse_day_accused_mean"], 10.25, abs_tol=1e-6)
    assert math.isclose(bcm["gpt55_plant_canary_calls_mean"], 17.166667, abs_tol=1e-5)
    assert math.isclose(g["canaries_before_accuse_mean"], 17.133333, abs_tol=1e-5)
    assert math.isclose(g["interviews_mean"], 4.166667, abs_tol=1e-5)
    assert math.isclose(bcm["gpt55_interview_call_share"], 0.060241, abs_tol=1e-5)
    assert math.isclose(bcm["carbon_interview_call_share"], 0.531372, abs_tol=1e-5)
    assert g["consistent_eq_0_at_accuse"] == 1
    assert len(cf["flip_episodes"]) == 1 and cf["flip_episodes"][0]["seed"] == 18 and cf["flip_episodes"][0]["correct"] is True

    ab = cf["abstained_prose_only_episodes"]
    assert [r["seed"] for r in ab] == [0, 17]
    assert all(r["accused"] is None and r["score"] == 0.0 and r["meta_V_final"] is None for r in ab)
    assert [r["replayed_day"] for r in ab] == [8, 9]
    assert [r["consistent_size_end"] for r in ab] == [1, 1]
    assert ab[0]["effective_V_final"] > 0.6 and ab[1]["effective_V_final"] > 0.6

    re_raw = MOD.paired_contrast(ps_gpt["score"], ps_oc["score"])
    re_la = MOD.paired_contrast(ps_gpt["luck_adjusted"], ps_oc["luck_adjusted"])
    re_can = MOD.paired_contrast(
        [float(x) for x in ps_gpt["canaries_before"]],
        [float(x) for x in ps_oc["canaries_before"]],
    )
    re_int = MOD.paired_contrast(
        [float(x) for x in ps_gpt["interviews"]],
        [float(x) for x in ps_oc["interviews"]],
    )
    assert MOD.approx_equal(re_raw, pvc["raw_score"], tol=2e-5)
    assert MOD.approx_equal(re_la, pvc["luck_adjusted_score"], tol=2e-5)
    assert MOD.approx_equal(re_can, pvc["canaries_before_accuse"], tol=1e-6)
    assert MOD.approx_equal(re_int, pvc["interviews"], tol=1e-6)
    assert pvc["canaries_before_accuse"]["boot_ci95"][0] > 6.5
    assert pvc["interviews"]["boot_ci95"][1] < -55.0 and pvc["interviews"]["seed_wins_neg"] == 30

    for dec_obj in (pvc["decomposition"], cf["paired_vs_solver"]["decomposition"]):
        t = dec_obj["terms_sum_30_seeds"]
        la_sum = (
            t["posterior_commitment_quality"]
            + t["a_only_accused_gain"]
            + t["a_abstained_loss"]
            + t["leak_timing_value"]
            + t["canary_cost_value"]
            + t["restriction_cost_value"]
        )
        assert math.isclose(dec_obj["luck_adjusted_diff_sum"], la_sum, abs_tol=1e-5)
        assert math.isclose(dec_obj["raw_diff_sum"], dec_obj["luck_adjusted_diff_sum"] + t["luck_diff"], abs_tol=1e-5)

    hb = committed_data["harbor_container_harness"]
    assert hb["tag"] == "afterquery-final"
    assert hb["build_sha_short"] == "1bc3e281"
    assert hb["correction_commits"] == ["aa1c679e", "5f9b3297"]
    assert hb["gap_reproduced_in_harbor"] is False
    hc = hb["harness_matrix"]["harbor_container_opencode_carbon"]
    assert hc["shell_allowed"] is True
    assert hc["shell_used_trials"] == 20 and hc["shell_audited_trials"] == 28
    assert hc["valid_accusations_correct"] == 28 and hc["valid_accusations_total"] == 29
    assert math.isclose(hc["oracle_mean_10_tasks"], 0.506, abs_tol=1e-6)
    assert hc["do_nothing_mean"] == 0.0 and hc["stop_early_mean"] == 0.0
    assert [r["mean"] for r in hc["runs"]] == [0.472, 0.585, 0.626]
    assert [r["ratio_pct"] for r in hc["runs"]] == [93, 116, 131]
    assert hc["runs"][2]["n_valid"] == 9 and math.isclose(hc["runs"][2]["oracle_same_tasks"], 0.477778, abs_tol=1e-5)

    md_txt = MD_PATH.read_text(encoding="utf-8")
    assert "6. Cross-Family Hard Comparison" in md_txt
    assert "7. Harbor Judge-Container Harness vs Local MCP-Only OpenCode" in md_txt
    assert "did not reproduce in the Harbor judge container" in md_txt


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
        assert ("import " + "subprocess") not in src, f"found subprocess import in {py_path}"

    mole_dump_rx = re.compile(r'"(?:mole|mole_id|true_mole)"\s*:\s*"e\d{2}"')
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = path.read_text(encoding="utf-8")
        assert "\u2013" not in txt and "\u2014" not in txt, f"found em/en dash in {path}"
        assert "\u00b1" not in txt, f"found plus-minus symbol in {path}"
        assert not mole_dump_rx.search(txt), f"found world_mole_dump pattern in {path}"
