"""Unit and reproducibility tests for scripts/counterfactual_decomposition_v14.py."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import math
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

SCRIPT_PATH = ROOT / "scripts/counterfactual_decomposition_v14.py"
TEST_PATH = Path(__file__).resolve()
JSON_PATH = ROOT / "results/eval_v14/counterfactual_decomposition_v14.json"
MD_PATH = ROOT / "docs/reports/counterfactual_decomposition_v14.md"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


CFD = _load_module("counterfactual_decomposition_v14", SCRIPT_PATH)


@pytest.fixture(scope="module")
def committed_payload() -> dict[str, Any]:
    assert JSON_PATH.is_file(), f"missing {JSON_PATH}"
    assert MD_PATH.is_file(), f"missing {MD_PATH}"
    assert JSON_PATH.stat().st_size <= CFD.MAX_JSON_BYTES
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_cli_check_exit_code_zero(
    committed_payload: dict[str, Any],
    capsys,
    monkeypatch,
):
    assert CFD.render_markdown_report(committed_payload) == MD_PATH.read_text(encoding="utf-8")
    assert CFD.approx_equal(json.loads(CFD.serialize_json(committed_payload)), committed_payload)

    slice_seeds = {18, 26}
    oc_slice = CFD.load_episodes_by_seed(
        ROOT,
        ("data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl",),
        "hard",
        slice_seeds,
    )
    sol_slice = CFD.load_episodes_by_seed(
        ROOT,
        CFD.SOLVER_REF_PATHS["hard"],
        "hard",
        slice_seeds,
    )
    committed_recs = {
        (r["cohort"], r["seed"]): r
        for r in committed_payload["hard_seed_forensics"]["records"]
    }
    for sd in sorted(slice_seeds):
        dec = CFD.decompose_seed_pair(oc_slice[sd], sol_slice[sd], "hard")
        exp = committed_recs[("opencode-gemini-4-carbon", sd)]
        assert dec["regime"] == exp["regime"]
        assert math.isclose(float(oc_slice[sd]["p_solver"]), float(exp["p_solver"]), abs_tol=1e-6)
        assert math.isclose(float(oc_slice[sd]["ev_threshold"]), float(exp["ev_threshold"]), abs_tol=1e-6)
        assert math.isclose(float(oc_slice[sd]["entropy_bits"]), float(exp["entropy_bits"]), abs_tol=1e-6)
        assert math.isclose(float(dec["ev_abstain_rescue"]), float(exp["ev_abstain_rescue"]), abs_tol=1e-6)
        assert math.isclose(
            float(dec["calibrated_wrong_accuse_residual"]),
            float(exp["calibrated_wrong_accuse_residual"]),
            abs_tol=1e-6,
        )
        assert oc_slice[sd]["flips"] == exp["surfaced_flips"]

    monkeypatch.setattr(CFD, "compute_all", lambda _root=CFD.ROOT: copy.deepcopy(committed_payload))
    rc = CFD.main(["--check"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK: counterfactual_decomposition_v14 verified" in out


def test_all_nine_seed_decomposition_regimes_zero_residual():
    base_ag = {
        "seed": 3,
        "score": 0.0,
        "accused": None,
        "correct": False,
        "ev_threshold": 0.60,
        "p_solver": None,
        "blind_cf_score": 0.0,
        "n_leaks": 2,
        "n_canaries": 4,
        "restriction_cost": 0.0,
    }
    base_sol = {
        "seed": 3,
        "score": 0.65,
        "correct": True,
        "n_leaks": 1,
        "n_canaries": 6,
        "restriction_cost": 0.0,
    }

    cases = [
        (
            {
                **base_ag,
                "score": 0.86,
                "accused": "e01",
                "correct": True,
                "p_solver": 0.98,
                "blind_cf_score": 0.86,
                "n_leaks": 2,
                "n_canaries": 4,
                "restriction_cost": 0.0,
            },
            {
                **base_sol,
                "score": 0.89,
                "correct": True,
                "n_leaks": 1,
                "n_canaries": 6,
                "restriction_cost": 0.0,
            },
            "both_caught",
            "timing_and_cost_bleed_gap",
        ),
        (
            {
                **base_ag,
                "score": -1.0,
                "accused": "e04",
                "correct": False,
                "p_solver": 0.95,
                "blind_cf_score": -1.0,
            },
            {**base_sol, "score": 0.69, "correct": True},
            "calibrated_wrong_accuse",
            "calibrated_wrong_accuse_residual",
        ),
        (
            {
                **base_ag,
                "score": -1.0,
                "accused": "e29",
                "correct": False,
                "p_solver": 0.40,
                "blind_cf_score": 0.0,
            },
            {**base_sol, "score": 0.52, "correct": True},
            "rescued_wrong_accuse_solver_caught",
            "ev_abstain_rescue",
        ),
        (
            {
                **base_ag,
                "score": -1.0,
                "accused": "e29",
                "correct": False,
                "p_solver": 0.40,
                "blind_cf_score": 0.0,
            },
            {**base_sol, "score": 0.0, "correct": False},
            "rescued_wrong_accuse_solver_abstained",
            "ev_abstain_rescue",
        ),
        (
            {
                **base_ag,
                "score": -1.0,
                "accused": "e29",
                "correct": False,
                "p_solver": 0.40,
                "blind_cf_score": 0.0,
            },
            {**base_sol, "score": -1.0, "correct": False},
            "rescued_wrong_accuse_solver_wrong",
            "ev_abstain_rescue",
        ),
        (
            {**base_ag, "score": 0.0, "accused": None, "correct": False},
            {**base_sol, "score": 0.62, "correct": True},
            "frontier_abstained_solver_caught",
            "missed_catch_information_gap",
        ),
        (
            {**base_ag, "score": 0.0, "accused": None, "correct": False},
            {**base_sol, "score": 0.0, "correct": False},
            "both_abstained",
            None,
        ),
        (
            {**base_ag, "score": 0.0, "accused": None, "correct": False},
            {**base_sol, "score": -1.0, "correct": False},
            "frontier_abstained_solver_wrong",
            "solver_miss_frontier_catch_offset",
        ),
        (
            {
                **base_ag,
                "score": 0.57,
                "accused": "e10",
                "correct": True,
                "p_solver": 0.99,
                "blind_cf_score": 0.57,
            },
            {**base_sol, "score": -1.0, "correct": False},
            "frontier_caught_solver_missed",
            "solver_miss_frontier_catch_offset",
        ),
    ]

    seen_regimes: set[str] = set()
    for ag, sol, exp_regime, must_key in cases:
        out = CFD.decompose_seed_pair(ag, sol, "hard")
        assert out["regime"] == exp_regime
        seen_regimes.add(out["regime"])
        comp_sum = sum(float(out[k]) for k in CFD.COMPONENT_KEYS)
        assert math.isclose(comp_sum, float(out["delta"]), abs_tol=1e-12)
        assert out["abs_residual"] <= 1e-12
        if must_key is not None:
            assert abs(float(out[must_key])) > 0.0

    assert seen_regimes == set(CFD.REGIME_SHORT_CODES.keys())


def test_committed_frontier_cohorts_identities_and_headline_parity(committed_payload: dict[str, Any]):
    assert committed_payload["schema_version"] == CFD.SCHEMA_VERSION
    assert committed_payload["tiers_version"] == "v1.4"
    assert committed_payload["primary_seeds"] == "0-29"
    assert committed_payload["n_seeds_per_cohort"] == 30
    assert "671ed96" in committed_payload["primary_seed_lock_note"]

    vt = committed_payload["verification_totals"]
    assert vt["frontier_cohorts_count"] == 7
    assert vt["baseline_cohorts_count"] == 2
    assert vt["frontier_episodes_replayed"] == 210
    assert vt["solver_reference_episodes_replayed"] == 60
    assert vt["all_identities_within_1e_12"] is True

    by_ct = {(c["cohort"], c["tier"]): c for c in committed_payload["frontier_cohorts"]}
    assert ("opencode-gemini-4-carbon", "hard") in by_ct
    assert ("inproc-gemini-4-carbon", "hard") in by_ct
    assert ("opencode-gemini-3.5-flash", "hard") in by_ct
    assert ("opencode-gpt-5.5", "hard") in by_ct
    assert ("opencode-gemini-4-carbon", "medium") in by_ct
    assert ("inproc-gemini-4-carbon", "medium") in by_ct
    assert ("opencode-gemini-3.5-flash", "medium") in by_ct

    for c in committed_payload["frontier_cohorts"] + committed_payload["baseline_reference_cohorts"]:
        assert c["n"] == 30
        assert c["seeds"] == [0, 29]
        sp = c["scores_and_posteriors"]
        cm = c["components"]
        ic = c["identity_check"]
        tc = c["timing_and_cost_subcomponents"]
        bl = c["blind_ev_stopping_counterfactual"]

        comp_sum = sum(float(cm[k]["mean"]) for k in CFD.COMPONENT_KEYS)
        assert math.isclose(comp_sum, float(sp["total_gap_delta"]), abs_tol=1e-7)
        assert ic["within_1e_12"] is True
        assert float(ic["mean_abs_residual"]) <= 1e-12
        assert float(ic["per_seed_max_abs_residual"]) <= 1e-12
        assert float(ic["bootstrap_max_abs_residual"]) <= 1e-12

        bleed_sum = (
            float(tc["leak_bleed_diff_mean"])
            + float(tc["canary_cost_diff_mean"])
            + float(tc["restriction_cost_diff_mean"])
        )
        assert math.isclose(bleed_sum, float(cm["timing_and_cost_bleed_gap"]["mean"]), abs_tol=1e-7)

        blind_sum = float(bl["rescued_wrong_gain"]) + float(bl["forfeited_lucky_catch_loss"])
        assert math.isclose(blind_sum, float(bl["blind_cf_gain_over_agent"]), abs_tol=1e-7)

    oc_h = by_ct[("opencode-gemini-4-carbon", "hard")]
    assert math.isclose(oc_h["scores_and_posteriors"]["agent_mean"], 0.32233333, abs_tol=1e-6)
    assert math.isclose(oc_h["scores_and_posteriors"]["solver_mean"], 0.499, abs_tol=1e-6)
    assert math.isclose(oc_h["scores_and_posteriors"]["total_gap_delta"], 0.17666667, abs_tol=1e-6)
    assert oc_h["components"]["ev_abstain_rescue"]["active_seeds"] == [18]
    assert oc_h["components"]["calibrated_wrong_accuse_residual"]["active_seeds"] == [1, 26]

    gpt_h = by_ct[("opencode-gpt-5.5", "hard")]
    assert gpt_h["scores_and_posteriors"]["accused_count"] == 28
    assert gpt_h["scores_and_posteriors"]["wrong_count"] == 0
    assert gpt_h["scores_and_posteriors"]["abstain_count"] == 2
    assert gpt_h["scores_and_posteriors"]["sub_threshold_gamble_count"] == 0
    assert gpt_h["components"]["ev_abstain_rescue"]["mean"] == 0.0
    assert gpt_h["components"]["calibrated_wrong_accuse_residual"]["mean"] == 0.0
    assert gpt_h["components"]["missed_catch_information_gap"]["active_seeds"] == [0, 17]


def test_forensics_regret_and_panel_fix_a_sync(committed_payload: dict[str, Any]):
    pf = committed_payload["panel_fix_a_and_headline"]
    assert pf["primary_hard_raw_ratio_headline"] == "65% [24%, 98%]"
    assert pf["primary_hard_luck_adjusted_ratio_headline"] == "72% [52%, 91%]"
    assert pf["opencode_gpt55_hard_raw_ratio"] == "101% [79%, 140%]"
    assert pf["harbor_rehearsal_3run_ratios"] == [
        "93% [20%, 371%]",
        "116% [78%, 363%]",
        "131% [86%, 590%]",
    ]
    assert pf["headline_gap_table_crosschecked"] is True

    recs = {(r["cohort"], r["seed"]): r for r in committed_payload["hard_seed_forensics"]["records"]}
    assert recs[("opencode-gemini-4-carbon", 6)]["regime"] == "both_caught"
    assert recs[("opencode-gemini-4-carbon", 18)]["regime"] == "rescued_wrong_accuse_solver_caught"
    assert recs[("opencode-gemini-4-carbon", 26)]["regime"] == "calibrated_wrong_accuse"
    assert recs[("inproc-gemini-4-carbon", 26)]["regime"] == "frontier_abstained_solver_caught"
    assert recs[("opencode-gpt-5.5", 18)]["regime"] == "both_caught"

    rc = committed_payload["regret_crosschecks"]
    for cohort_name in ("opencode-gemini-4-carbon", "inproc-gemini-4-carbon"):
        for tier in ("hard", "medium"):
            assert rc[cohort_name]["tiers"][tier]["all_matched"] is True

    md_txt = MD_PATH.read_text(encoding="utf-8")
    for token in (
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "101% [79%, 140%]",
        "131% [86%, 590%]",
        "aa1c679e",
        "671ed96",
        "opencode-gpt-5.5",
    ):
        assert token in md_txt


def test_cli_write_and_check_tamper_detection(
    committed_payload: dict[str, Any],
    tmp_path: Path,
    monkeypatch,
):
    assert CFD.approx_equal({"x": [1.0, 2.0]}, {"x": [1.0, 2.0 + 1e-12]})
    assert not CFD.approx_equal({"x": [1.0]}, {"x": [1.001]})
    assert not CFD.approx_equal({"flag": True}, {"flag": 1})

    monkeypatch.setattr(CFD, "compute_all", lambda root=CFD.ROOT: copy.deepcopy(committed_payload))
    out_json = tmp_path / "out.json"
    out_md = tmp_path / "out.md"

    assert CFD.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    assert CFD.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["frontier_cohorts"][0]["scores_and_posteriors"]["agent_mean"] += 0.05
    out_json.write_text(json.dumps(tampered), encoding="utf-8")
    assert CFD.main(["--check", "--out-json", str(out_json), "--out-md", str(out_md)]) == 1

    assert CFD.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    bad_md = tmp_path / "bad.md"
    bad_md.write_text(out_md.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
    assert CFD.main(["--check", "--out-json", str(out_json), "--out-md", str(bad_md)]) == 1

    oversized = tmp_path / "oversized.json"
    oversized.write_text(" " * (CFD.MAX_JSON_BYTES + 10), encoding="utf-8")
    assert CFD.main(["--check", "--out-json", str(oversized), "--out-md", str(out_md)]) == 1


def test_strict_hygiene_and_artifact_limits():
    assert JSON_PATH.stat().st_size <= CFD.MAX_JSON_BYTES
    assert MD_PATH.stat().st_size > 1000

    for py_path in (SCRIPT_PATH, TEST_PATH):
        src = py_path.read_text(encoding="utf-8")
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"found comment token in {py_path}"
        assert chr(35) not in src, f"found hash char in {py_path}"

    forbidden_chars = (chr(0x2013), chr(0x2014), chr(0x2212), chr(0x00B1))
    co_author_tag = "Co-Authored-" + "By"

    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = path.read_text(encoding="utf-8")
        for ch in forbidden_chars:
            assert ch not in txt, f"found forbidden char {hex(ord(ch))} in {path}"
        assert co_author_tag not in txt, f"found co-author tag in {path}"
        assert CFD.check_text_hygiene(str(path), txt) == []
