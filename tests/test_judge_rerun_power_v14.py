"""Fast unit and reproducibility tests for scripts/judge_rerun_power_v14.py."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import judge_rerun_power_v14 as JRP


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


def test_exact_committed_v14_hard_means(committed_payload: dict):
    agents = committed_payload["agents"]
    expected = {
        "opencode-carbon": (0.322, 0.360),
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


def test_pass_k_monotonicity_and_flash_collapse(committed_payload: dict):
    pk = committed_payload["pass_k_reliability"]
    for name in JRP.AGENT_ORDER:
        row = pk[name]
        assert 1.0 >= row["pass_1"] >= row["pass_2"] >= row["pass_3"] >= 0.0
        assert math.isclose(row["expected_all3_wins_per_10tasks"], 10.0 * row["pass_3"], rel_tol=1e-12)

    assert pk["solver"]["pass_3"] > pk["inproc-carbon"]["pass_3"]
    assert pk["inproc-carbon"]["pass_3"] > pk["opencode-carbon"]["pass_3"]
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
    assert ma["inproc-carbon"]["empirical_paired_var_reduction_factor"] > 2.0
    assert mb["inproc-carbon"]["analytical_decomposition"]["la_var_reduction_vs_raw_r1"] > 2.0


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
