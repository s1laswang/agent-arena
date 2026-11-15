"""Fast unit and reproducibility tests for scripts/judge_rerun_power_v14.py."""
from __future__ import annotations

import json
import math
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import judge_rerun_power_v14 as JRP

FORBIDDEN_UNICODE = (chr(0x2013), chr(0x2014), chr(0x2212), chr(0x00B1))


@pytest.fixture(scope="module")
def committed_payload() -> dict:
    assert JRP.OUT_JSON.exists(), f"missing {JRP.OUT_JSON}"
    assert JRP.OUT_MD.exists(), f"missing {JRP.OUT_MD}"
    assert JRP.OUT_JSON.stat().st_size < 80 * 1024
    return json.loads(JRP.OUT_JSON.read_text(encoding="utf-8"))


def test_check_reproduces_committed_artifacts(capsys):
    rc = JRP.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "check passed" in out


def test_exact_committed_v14_hard_means_and_gpt55(committed_payload: dict):
    agents = committed_payload["agents"]
    expected = {
        "opencode-carbon": (0.322, 0.360),
        "opencode-gpt-5.5": (0.504, 0.418),
        "opencode-3.5-flash": (0.373, 0.110),
        "inproc-carbon": (0.473, 0.421),
        "solver": (0.499, 0.499),
    }
    for name, (exp_raw, exp_la) in expected.items():
        ag = agents[name]
        assert ag["n_seeds"] == 30
        assert round(ag["raw_mean"], 3) == exp_raw
        assert round(ag["luck_adjusted_mean"], 3) == exp_la
        assert 0.14 < ag["mean_wrong_accuse_swing_10task"] < 0.17

    gpt = agents["opencode-gpt-5.5"]
    assert gpt["prereg_commit"] == "cf394894"
    assert gpt["data_commit"] == "ca0a0dc0"
    assert gpt["n_accused"] == 28
    assert gpt["n_correct_accused"] == 28
    assert gpt["n_wrong"] == 0
    assert gpt["n_abstain"] == 2
    assert gpt["abstain_seeds"] == [0, 17]
    pvs = gpt["paired_vs_solver"]
    assert pvs["raw_ratio_pct"] == 101
    assert pvs["raw_ratio_ci95_pct"] == [79, 140]
    assert pvs["luck_adjusted_ratio_pct"] == 84
    assert pvs["luck_adjusted_ratio_ci95_pct"] == [67, 103]

    oc_pvs = agents["opencode-carbon"]["paired_vs_solver"]
    assert oc_pvs["raw_ratio_pct"] == 65
    assert oc_pvs["raw_ratio_ci95_pct"] == [24, 98]
    assert oc_pvs["luck_adjusted_ratio_pct"] == 72
    assert oc_pvs["luck_adjusted_ratio_ci95_pct"] == [52, 91]


def test_harbor_rehearsal_realisation(committed_payload: dict):
    hr = committed_payload["harbor_rehearsal_realisation"]
    assert hr is not None
    assert hr["env_tag"] == "afterquery-final"
    assert hr["build_sha"] == "1bc3e281"
    assert hr["correction_commits"] == ["aa1c679e", "5f9b3297"]
    assert hr["final_trials_branch_commit"] == "d0ead011"
    assert hr["shell_in_container"] is True
    assert hr["shell_used_trials"] == [20, 28]
    assert hr["mcp_only_gap_reproduced_in_harbor"] is False

    ora = hr["oracle_10task"]
    assert ora["n_valid"] == 10
    assert ora["n_correct"] == 9
    assert math.isclose(ora["mean"], 0.506, abs_tol=1e-6)

    runs = hr["runs_final"]
    assert runs["opencode-1"]["n_valid"] == 10
    assert math.isclose(runs["opencode-1"]["mean"], 0.472, abs_tol=1e-6)
    assert runs["opencode-1"]["ratio_pct"] == 93
    assert runs["opencode-1"]["ratio_ci95_pct"] == [20, 371]

    assert runs["opencode-2"]["n_valid"] == 10
    assert math.isclose(runs["opencode-2"]["mean"], 0.585, abs_tol=1e-6)
    assert runs["opencode-2"]["ratio_pct"] == 116
    assert runs["opencode-2"]["ratio_ci95_pct"] == [78, 363]

    assert runs["opencode-3"]["n_valid"] == 9
    assert runs["opencode-3"]["n_infra_excluded"] == 1
    assert runs["opencode-3"]["n_correct"] == 9
    assert math.isclose(runs["opencode-3"]["mean"], 0.626, abs_tol=1e-6)
    assert runs["opencode-3"]["ratio_pct"] == 131
    assert runs["opencode-3"]["ratio_ci95_pct"] == [86, 590]

    sp = hr["three_run_spread_final"]
    assert sp["run_means"] == [0.472, 0.585, 0.626]
    assert sp["total_valid_trials"] == 29
    assert sp["total_valid_correct"] == 28


def test_pass_k_monotonicity_and_flash_collapse(committed_payload: dict):
    pk = committed_payload["pass_k_reliability"]
    for name in JRP.AGENT_ORDER:
        row = pk[name]
        assert 1.0 >= row["pass_1"] >= row["pass_2"] >= row["pass_3"] >= 0.0
        assert math.isclose(row["expected_all3_wins_per_10tasks"], 10.0 * row["pass_3"], rel_tol=1e-12)

    assert round(pk["opencode-gpt-5.5"]["pass_3_audit_3dp"], 3) == 0.793
    assert round(pk["opencode-gpt-5.5"]["pass_3"], 3) == 0.792
    assert pk["solver"]["pass_3"] > pk["inproc-carbon"]["pass_3"]
    assert pk["inproc-carbon"]["pass_3"] > pk["opencode-gpt-5.5"]["pass_3"]
    assert pk["opencode-gpt-5.5"]["pass_3"] > pk["opencode-carbon"]["pass_3"]
    assert pk["opencode-carbon"]["pass_3"] > pk["opencode-3.5-flash"]["pass_3"]
    assert pk["opencode-3.5-flash"]["homogeneous_mean_p_cubed"] < 0.40
    assert pk["solver"]["homogeneous_mean_p_cubed"] > 0.88
    assert pk["opencode-3.5-flash"]["gamble_pass_3"] < 0.05


def test_variance_reduction_and_power_across_r(committed_payload: dict):
    ma = committed_payload["model_a_empirical_paired_resampling"]
    mb = committed_payload["model_b_posterior_repeated_runs"]

    for fname in JRP.FRONTIER_ORDER:
        for kind in ("raw", "luck_adjusted"):
            runs_a = ma[fname][kind]["runs"]
            sd1_a = runs_a["R1"]["diff"]["sd"]
            sd3_a = runs_a["R3"]["diff"]["sd"]
            sd5_a = runs_a["R5"]["diff"]["sd"]
            assert sd5_a < sd3_a < sd1_a
            assert math.isclose(sd1_a / sd3_a, math.sqrt(3.0), rel_tol=0.03)
            if ma[fname][kind]["paired_30seed_diff_mean"] < 0.0:
                assert runs_a["R3"]["p_frontier_lt_oracle"] >= runs_a["R1"]["p_frontier_lt_oracle"]

        runs_b = mb[fname]["runs"]
        sd1_b = runs_b["R1"]["diff"]["sd"]
        sd3_b = runs_b["R3"]["diff"]["sd"]
        sd5_b = runs_b["R5"]["diff"]["sd"]
        assert sd5_b < sd3_b < sd1_b
        assert runs_b["R3"]["p_frontier_lt_oracle"] > runs_b["R1"]["p_frontier_lt_oracle"]

        dec = mb[fname]["analytical_decomposition"]
        assert math.isclose(dec["luck_noise_sd_reduction_r1_to_r3"], math.sqrt(3.0), rel_tol=1e-9)
        assert math.isclose(
            runs_b["R3"]["within_build_run_sd_rms"],
            dec["exact_within_build_1run_sd"],
            rel_tol=0.02,
        )

    assert ma["opencode-carbon"]["empirical_paired_var_reduction_factor"] > 2.0
    assert mb["opencode-carbon"]["analytical_decomposition"]["la_var_reduction_vs_raw_r1"] > 2.0
    assert ma["opencode-gpt-5.5"]["empirical_paired_var_reduction_factor"] > 2.0
    assert mb["opencode-gpt-5.5"]["analytical_decomposition"]["la_var_reduction_vs_raw_r1"] > 2.0
    assert ma["inproc-carbon"]["empirical_paired_var_reduction_factor"] > 2.0
    assert mb["inproc-carbon"]["analytical_decomposition"]["la_var_reduction_vs_raw_r1"] > 2.0


def test_report_hygiene_and_no_comments():
    md_text = JRP.OUT_MD.read_text(encoding="utf-8")
    json_text = JRP.OUT_JSON.read_text(encoding="utf-8")
    for ch in FORBIDDEN_UNICODE:
        assert ch not in md_text
        assert ch not in json_text
    for token in (
        "101% [79%, 140%]",
        "84% [67%, 103%]",
        "0.793",
        "cf394894",
        "ca0a0dc0",
        "aa1c679e",
        "5f9b3297",
        "93%",
        "116%",
        "131%",
        "+0.506",
        "shell",
    ):
        assert token in md_text

    for py_path in (ROOT / "scripts/judge_rerun_power_v14.py", Path(__file__).resolve()):
        with py_path.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comments in {py_path}"


def test_check_detects_tampering_and_approx_equal(committed_payload: dict, tmp_path: Path, monkeypatch):
    assert JRP.approx_equal({"a": [1.0, 2.0]}, {"a": [1.0, 2.0 + 1e-12]})
    assert not JRP.approx_equal({"a": [1.0]}, {"a": [1.001]})
    assert not JRP.approx_equal({"flag": True}, {"flag": 1})

    monkeypatch.setattr(JRP, "compute", lambda **kwargs: committed_payload)
    tmp_json = tmp_path / "out.json"
    tmp_md = tmp_path / "out.md"
    assert JRP.main(["--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 0
    assert JRP.main(["--check", "--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 0

    tampered = json.loads(tmp_json.read_text(encoding="utf-8"))
    tampered["agents"]["solver"]["raw_mean"] = 0.999
    tmp_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert JRP.main(["--check", "--out-json", str(tmp_json), "--out-md", str(tmp_md)]) == 1
