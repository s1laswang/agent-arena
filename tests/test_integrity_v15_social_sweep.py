from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import scripts.integrity_v15_social_sweep as sweep


@pytest.fixture(scope="module")
def clean_factory():
    return sweep.make_synthetic_v15_factory(plant_leak=False)


@pytest.fixture(scope="module")
def hard_conditionals(clean_factory):
    return sweep.audit_social_conditionals(clean_factory, "hard", list(range(7500, 7512)))


def test_seed_spec_and_statistical_helpers() -> None:
    assert sweep.parse_seed_spec("7500:7504") == [7500, 7501, 7502, 7503]
    assert sweep.parse_seed_spec("1, 3-5, 9") == [1, 3, 4, 5, 9]
    assert sweep.ci95([1.0]) == 0.0
    assert sweep.ci95([0.0, 1.0, 0.0, 1.0]) > 0.0

    zero = sweep.rate_summary(0, 0)
    assert zero == {"hits": 0, "total": 0, "rate": 0.0, "ci95": 0.0}
    half = sweep.rate_summary(50, 100)
    assert half["rate"] == pytest.approx(0.5)
    assert half["ci95"] == pytest.approx(0.098, abs=1e-3)

    assert sweep.mole_named_leak("e07 is the mole", "e07") is True
    assert sweep.mole_named_leak('{"true_culprit": "e07"}', "e07") is True
    assert sweep.mole_named_leak("Gut feeling: Pat (e07). Always closing their laptop.", "e07") is False


def test_fuzz_summary_and_deterministic_call_accounting(tmp_path: Path) -> None:
    tiers = ("easy", "medium", "hard", "hard_forge")
    for idx, tier in enumerate(tiers):
        sub = tmp_path / f"redteam-fuzz-20261114-22415{idx}-{tier}-all"
        sub.mkdir()
        summary = {
            "tier": tier,
            "seeds": [7500, 7509],
            "budget": 300,
            "mode": "all",
            "best_non_solver_score": 0.0,
            "best_score_per_call": 1.0,
            "violation_kinds": [],
            "per_mode": {
                "random": {"budget": 100, "best_score_per_call": 0.25, "n_violations": 0},
                "malformed": {"budget": 100, "best_score_per_call": 0.0, "n_violations": 0},
                "evolve": {"budget": 100, "best_score_per_call": 1.0, "n_violations": 0},
                "parallel_accuse": {
                    "budget": 0,
                    "races": 10,
                    "threads_per_race": 8,
                    "best_score_per_call": 0.0,
                    "n_violations": 0,
                },
            },
            "n_findings": 0,
            "seconds": 1.5,
        }
        (sub / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        (sub / "findings.jsonl").write_text("", encoding="utf-8")

    agg = sweep.summarize_fuzz_dir(tmp_path)
    assert agg["present"] is True
    assert [t["tier"] for t in agg["tiers"]] == list(tiers)
    totals = agg["totals"]
    assert totals["total_budget"] == 1200
    assert totals["total_parallel_races"] == 40
    assert totals["total_parallel_threads"] == 320
    assert totals["total_parity_episodes"] == 360
    assert totals["total_episodes"] == 1600
    assert totals["total_malformed_calls"] == 12000
    assert totals["total_parallel_accuse_calls"] == 360
    assert totals["total_parity_calls"] == 1020
    assert totals["total_setup_calls"] == 120
    assert totals["total_deterministic_non_evolve_calls"] > totals["total_malformed_calls"]
    assert totals["min_total_calls"] == totals["total_deterministic_non_evolve_calls"] + 400
    assert totals["max_best_non_solver_score"] == 0.0
    assert totals["total_invariant_violations"] == 0


def test_word_and_token_leak_detector_clean_vs_planted(clean_factory) -> None:
    leaky_factory = sweep.make_synthetic_v15_factory(plant_leak=True)

    clean_res = sweep.audit_word_and_token_leaks(clean_factory, "medium", [7500, 7501, 7502])
    assert clean_res["clean"] is True
    assert clean_res["social_messages_scanned"] > 0
    assert clean_res["mole_word_leaks"] == 0
    assert clean_res["truth_pattern_leaks"] == 0
    assert clean_res["seed_or_secret_token_leaks"] == 0

    leak_res = sweep.audit_word_and_token_leaks(leaky_factory, "medium", [7500, 7501])
    assert leak_res["clean"] is False
    assert leak_res["mole_word_leaks"] >= 1
    assert leak_res["truth_pattern_leaks"] >= 1
    assert leak_res["seed_or_secret_token_leaks"] >= 1


def test_anti_inversion_grudge_exclusion_and_misforward_detectors(clean_factory, hard_conditionals) -> None:
    prior = hard_conditionals["prior_mole"]
    assert prior == pytest.approx(0.025)
    assert hard_conditionals["rumour_event"]["p_mole_given_rumoured"]["rate"] < prior
    assert hard_conditionals["rumour_event"]["p_decoy_given_rumoured"]["rate"] > 0.30
    assert hard_conditionals["employee_rumour"]["p_mole_given_top_rumoured"]["rate"] == 0.0
    assert hard_conditionals["employee_rumour"]["p_decoy_given_top_rumoured"]["rate"] == 1.0

    grudge = hard_conditionals["grudge"]
    assert grudge["p_decoy_given_grudge_target_ge1"]["rate"] == 0.0
    assert grudge["p_decoy_given_grudge_participant"]["rate"] == 0.0
    assert grudge["p_decoy_given_grudge_pair_member"]["rate"] == 0.0

    misfwd = hard_conditionals["misforward"]
    assert misfwd["regular_docs_published"] > 0
    assert misfwd["misforwarded_doc_rate"]["rate"] > 0.05
    assert misfwd["mean_effective_recipients"] > misfwd["mean_base_recipients"]
    assert misfwd["mean_leaked_effective_intersection_size"] >= misfwd["mean_leaked_base_intersection_size"]

    excl = sweep.audit_exclusion_by_day(clean_factory, "hard", list(range(7500, 7506)), checkpoints=(6, 21))
    assert excl["checkpoints"]["day_21"]["safe_exclusion_not_mole"]["rate"] == 1.0
    assert excl["checkpoints"]["day_21"]["exact_decoy_match"]["rate"] == 1.0

    peer_cond = sweep.audit_social_conditionals(
        clean_factory, "hard", list(range(7500, 7512)), seed_rumour="random_peer"
    )
    assert peer_cond["rumour_event"]["p_mole_given_rumoured"]["rate"] < prior
    assert peer_cond["grudge"]["p_decoy_given_grudge_participant"]["rate"] == 0.0


def test_invariants_and_adversarial_social_policies(clean_factory) -> None:
    inv = sweep.audit_invariants(clean_factory, "medium", [7500, 7501, 7502])
    assert inv["all_invariants_hold"] is True
    assert inv["known_v_reveals"] == 0
    assert inv["v_monotone_violations"] == 0

    pol = sweep.audit_policies(clean_factory, "medium", [7500, 7501], include_log_probes=True)
    assert pol["solver"]["mean_social_ingested"] == 0.0
    assert pol["anti_rumour_solver"]["mean_social_ingested"] > 0.0
    assert pol["rumour_follower"]["mean_score"] < 0.0
    assert "logs_anti_rumour" in pol


def test_cli_synthetic_audit_smoke(tmp_path: Path) -> None:
    out_json = tmp_path / "audit.json"
    rc = sweep.main([
        "--synthetic",
        "--seeds",
        "7500:7504",
        "--solver-seeds",
        "7500:7502",
        "--tiers",
        "medium",
        "--workers",
        "1",
        "--json-out",
        str(out_json),
    ])
    assert rc == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["source"] == "synthetic-v1.5"
    assert payload["llm_calls"] == 0
    assert payload["word_and_token_leaks"]["medium"]["clean"] is True
    assert payload["invariants"]["medium"]["all_invariants_hold"] is True


def test_report_and_source_hygiene_integrity() -> None:
    report_path = REPO / "docs" / "reports" / "integrity_v15_social_sweep.md"
    script_path = REPO / "scripts" / "integrity_v15_social_sweep.py"
    test_path = Path(__file__).resolve()

    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")

    for dash in ("\u2014", "\u2013"):
        assert dash not in report
        assert dash not in script_path.read_text(encoding="utf-8")
        assert dash not in test_path.read_text(encoding="utf-8")

    hash_char = chr(35)
    assert hash_char not in script_path.read_text(encoding="utf-8")
    assert hash_char not in test_path.read_text(encoding="utf-8")

    required_tokens = (
        "origin/justSilas-v15",
        "de9cc50e",
        "v1.5-candidate",
        "321,360",
        "6,577,180",
        "easy",
        "medium",
        "hard",
        "hard_forge",
        "0.420984",
        "0.016995",
        "0/800",
        "ISS-V15-01",
        "ISS-V15-02",
        "ISS-V15-03",
        "ISS-V15-04",
        "ISS-V15-05",
    )
    for tok in required_tokens:
        assert tok in report, f"missing expected report token: {tok}"
