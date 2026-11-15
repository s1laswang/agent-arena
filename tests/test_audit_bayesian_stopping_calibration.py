from __future__ import annotations

import functools
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import sys
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = ROOT / "docs" / "research" / "09_bayesian_stopping_and_calibration.md"
SCRIPT_PATH = ROOT / "scripts" / "audit_bayesian_stopping_calibration.py"
VERIFY_PATH = ROOT / "scripts" / "verify_research_deception.py"
SELF_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"
CO_TAG = "-".join(("co", "authored", "by"))


def _load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


A = _load_mod("audit_bayesian_stopping_calibration", SCRIPT_PATH)
V = _load_mod("verify_research_deception_for_m09", VERIFY_PATH)


@functools.lru_cache(maxsize=1)
def _cached_audit() -> dict:
    return A.run_audit(root=ROOT, p9_1_seeds=20, include_gpt55=True)


def test_pure_ascii_zero_comments_zero_hash_zero_dashes() -> None:
    assert DOC_PATH.is_file(), f"missing monograph {DOC_PATH}"
    doc_src = DOC_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in doc_src
    assert EN_DASH not in doc_src
    assert CO_TAG not in doc_src.lower()
    assert doc_src.isascii()

    script_src = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "subprocess" not in script_src

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em-dash found in {py_path}"
        assert EN_DASH not in src, f"en-dash found in {py_path}"
        assert HASH_CH not in src, f"raw hash char found in {py_path}"
        assert CO_TAG not in src.lower(), f"co-author trailer found in {py_path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert all(tok.type != tokenize.COMMENT for tok in tokens), f"Python comment found in {py_path}"

    hyg = V.check_hygiene(ROOT, [DOC_PATH], extra_py_files=[SCRIPT_PATH, SELF_PATH])
    assert hyg.status == "PASS", hyg.details


def test_stopping_math_and_brier_identities() -> None:
    assert math.isclose(A.breakeven_threshold(1.0, -1.0), 0.5, abs_tol=1e-12)
    assert math.isclose(A.breakeven_threshold(0.46, -1.0), 1.0 / 1.46, abs_tol=1e-12)
    assert math.isclose(A.breakeven_threshold(0.16, -1.0), 1.0 / 1.16, abs_tol=1e-12)
    assert math.isclose(A.decision_ev(1.0 / 1.46, 0.46, -1.0), 0.0, abs_tol=1e-12)

    assert math.isclose(A.sunk_cost_threshold(0.21, 0.0, -1.0), A.breakeven_threshold(0.21, -1.0), abs_tol=1e-12)
    for v_val in (0.16, 0.21, 0.28, 0.51, 0.80):
        assert math.isclose(A.sunk_cost_threshold(v_val, 0.5, -1.0), 0.5, abs_tol=1e-12)
    assert A.sunk_cost_threshold(0.21, 0.35, -1.0) < A.breakeven_threshold(0.21, -1.0)

    with pytest.raises(ValueError):
        A.breakeven_threshold(0.5, 0.0)
    with pytest.raises(ValueError):
        A.breakeven_threshold(-0.1, -1.0)
    with pytest.raises(ValueError):
        A.sunk_cost_threshold(0.5, -0.1, -1.0)

    ps, pt = 0.89, 0.6272478445
    exp_b = pt * A.brier_loss(ps, 1) + (1.0 - pt) * A.brier_loss(ps, 0)
    assert math.isclose(A.expected_bayes_brier(ps, pt), exp_b, abs_tol=1e-12)


def test_full_bayesian_stopping_and_calibration_audit_and_5f9b3297_sync() -> None:
    payload = _cached_audit()
    assert payload["passed"] is True
    assert payload["validation_errors"] == []
    assert payload["meta"]["tiers_version"] == "v1.4"
    assert payload["meta"]["v14_frozen_hash"] == "a8f99c2537c91d72"
    assert payload["meta"]["n_seeds"] == 30

    oc = payload["summary"]["opencode_gemini_4_carbon"]
    sv = payload["summary"]["solver_reference"]
    gpt55 = payload["summary"]["opencode_gpt_5_5"]
    hb = payload["summary"]["harbor_rehearsal_5f9b3297"]
    gap = payload["summary"]["paired_gap"]
    cal = payload["summary"]["calibration_and_overprecision"]
    cf = payload["summary"]["counterfactual_exact_stopping_on_known_V"]

    assert oc["accused"] == 29 and oc["abstained"] == 1 and oc["correct"] == 25 and oc["wrong"] == 4
    assert math.isclose(oc["raw_mean"], 9.67 / 30.0, abs_tol=1e-9)
    assert math.isclose(oc["luck_adjusted_mean"], 0.3596419056, abs_tol=1e-6)
    assert oc["below_breakeven_known_V_seeds"] == [5, 18, 23]
    assert oc["below_breakeven_exp_V_seeds"] == [5, 18, 23]
    assert oc["below_breakeven_true_V_seeds"] == [5, 18, 23]

    assert sv["accused"] == 30 and sv["wrong"] == 1
    assert math.isclose(sv["raw_mean"], 0.499, abs_tol=1e-9)
    assert sv["below_breakeven_known_V_seeds"] == []
    assert sv["below_breakeven_exp_V_seeds"] == []
    assert sv["min_margin_exp_V"] > 0.11
    assert sv["ece_30_acc"] < 0.005

    assert gpt55 is not None
    assert gpt55["accused"] == 28 and gpt55["abstained"] == 2 and gpt55["wrong"] == 0
    assert gpt55["abstained_seeds"] == [0, 17]
    assert gpt55["below_breakeven_known_V_seeds"] == []
    assert gpt55["below_breakeven_exp_V_seeds"] == [5]

    assert hb["synced_5f9b3297"] is True
    assert hb["run_means"] == [0.472, 0.585, 0.626]
    assert hb["run_valid_ns"] == [10, 10, 9]
    assert hb["run_ratios_pct"] == [93.3, 115.6, 131.0]
    assert hb["valid_accusations_correct"] == 28 and hb["valid_accusations_total"] == 29

    assert math.isclose(gap["raw_gap_sum"], 5.30, abs_tol=1e-9)
    assert math.isclose(gap["luck_adjusted_gap_sum"], 4.18968395, abs_tol=1e-6)

    assert cal["n_verbalized_total"] == 29
    assert cal["n_verbalized_accusations"] == 28
    assert cal["unquantified_seeds"] == [26]
    assert cal["n_overconfident_seeds_all_29"] == 25
    assert math.isclose(cal["mean_p_stated_acc_28"], 0.9660408163, abs_tol=1e-6)
    assert math.isclose(cal["mean_p_true_acc_28"], 0.8794422293, abs_tol=1e-6)
    assert math.isclose(cal["mean_overprecision_unisolated_acc"], 0.2319785545, abs_tol=1e-6)
    assert math.isclose(cal["mean_overprecision_unisolated_7_pct_4dp"], 0.2293571429, abs_tol=1e-6)
    assert cal["mean_overprecision_below_be_3"] > 0.33

    assert cf["abstain_seeds"] == [5, 18, 23]
    assert cf["same_seeds_under_exp_and_true_V"] is True
    assert math.isclose(cf["luck_adjusted_gain_sum_V"], 0.9367505628, abs_tol=1e-6)
    assert math.isclose(cf["raw_gain_sum_V"], 0.61, abs_tol=1e-9)
    assert math.isclose(cf["luck_adjusted_gap_reduction_share"], 0.2235850182, abs_tol=1e-6)

    sp5 = payload["spotlight"]["5"]
    sp11 = payload["spotlight"]["11"]
    sp18 = payload["spotlight"]["18"]
    sp23 = payload["spotlight"]["23"]
    assert sp5["stated_kind"] == "odds_ratio" and sp5["p_true_accused"] < sp5["p_star_exp_V"]
    assert sp11["accused"] is None and math.isclose(sp11["p_stated"], 0.429, abs_tol=1e-9)
    assert sp18["accuse_day"] == 18 and sp18["days_remaining"] == 3 and sp18["correct"] is False
    assert sp23["consistent"] == ["e15", "e29", "e38"] and sp23["p_true_accused"] < 0.50


def test_proposals_p9_1_and_p9_2_and_transcript_parser() -> None:
    payload = _cached_audit()
    p1 = payload["proposals"]["P9_1_sunk_cost_urgency_anchor"]
    p2 = payload["proposals"]["P9_2_brier_calibrated_stopping_gate"]

    assert p1["proposal_id"] == "P9.1"
    assert p1["total_events"] == 60
    assert p1["valid_events"] == 60
    assert p1["valid_rate"] == 1.0
    assert p1["conditional_mi_nats"] == 0.0
    assert p1["exact_llr_nats"] == 0.0
    assert p1["solver_policy_loss_V"] == 0.0

    assert p2["proposal_id"] == "P9.2"
    assert p2["n_stated_accusations"] == 28
    assert math.isclose(p2["fitted_temperature"], 1.4, abs_tol=1e-6)
    assert math.isclose(p2["fitted_entropy_penalty"], 1.0, abs_tol=1e-6)
    assert p2["loo_soft_brier_mse"] < 0.005
    assert p2["loo_soft_brier_reduction_ratio"] > 4.4
    assert p2["loo_expected_brier"] < p2["uncalibrated_expected_brier"]
    assert p2["loo_empirical_brier"] < p2["uncalibrated_empirical_brier"]
    assert p2["loo_gated_abstain_seeds"] == [5, 18, 23]
    assert p2["loo_false_blocks_on_positive_ev"] == []
    assert math.isclose(p2["loo_luck_adjusted_gain_V"], 0.9367505628, abs_tol=1e-6)
    assert math.isclose(p2["loo_raw_gain_V"], 0.61, abs_tol=1e-9)

    full_11, final_11 = A.extract_commitment_transcript(11)
    assert len(full_11) >= len(final_11) > 20
    assert final_11 == A._extract_final_commitment_message(11)

    emp_a = A.EmployeeFacts("e01", "Alice Park", "Finance", "Controller", 2)
    emp_b = A.EmployeeFacts("e02", "Bob Kim", "Legal", "Counsel", 2)
    emp_d = A.EmployeeFacts("e03", "Dan Decoy", "Sales", "Rep", 1)
    facts = A.PublicDayFacts("hard", 42, 15, "Acme", (emp_a, emp_b, emp_d), (), decoy="e03")
    ctx = A.SunkCostAnchorContext(
        facts=facts,
        by_id={"e01": emp_a, "e02": emp_b, "e03": emp_d},
        consistent_non_decoy=("e01", "e02"),
        authority_speakers=("e01",),
        surfaced_regular_leaks=6,
        doc_titles=("Q3 Board Brief",),
    )
    msg = A.gen_sunk_cost_urgency_anchor(ctx, random.Random(7), target_id="e02")
    assert A.validate_p9_social_message(msg, emp_b, "e03", {"e01", "e02", "e03"}) == []

    bad_msg = dict(msg, subject="Rumour: e02 leaked", body="Angry about management pay for e03")
    errs = A.validate_p9_social_message(bad_msg, emp_b, "e03", {"e01", "e02", "e03"})
    assert len(errs) >= 3

    with pytest.raises(ValueError):
        A.BrierCalibratedStoppingGate(temperature=0.0)


def test_cli_validator_monograph_09_verifier_and_shallow_ci(tmp_path: Path, monkeypatch, capsys) -> None:
    payload = _cached_audit()
    txt_report = A.format_text_report(payload)
    assert "P9.1 gen_sunk_cost_urgency_anchor: 60/60 valid" in txt_report
    assert "P9.2 BrierCalibratedStoppingGate:" in txt_report

    slim = {k: v for k, v in payload.items() if k != "episodes"}
    monkeypatch.setattr(A, "run_audit", lambda **kwargs: slim)
    out_json = tmp_path / "m09_audit.json"
    rc = A.main(["--check", "--json", "--out-json", str(out_json)])
    out_str = capsys.readouterr().out
    assert rc == 0
    assert json.loads(out_str)["passed"] is True
    assert json.loads(out_json.read_text(encoding="utf-8"))["passed"] is True

    corrupted = dict(slim, meta=dict(payload["meta"], v14_frozen_hash="0000000000000000"), passed=False)
    assert any("v14_frozen_hash" in e for e in A.validate_audit_payload(corrupted))
    monkeypatch.setattr(A, "run_audit", lambda **kwargs: corrupted)
    assert A.main(["--check"]) == 1
    capsys.readouterr()

    docs = [DOC_PATH]
    results = [
        V.check_doc_structure(ROOT, docs, explicit_mode=True),
        V.check_hygiene(ROOT, docs, extra_py_files=[SCRIPT_PATH, SELF_PATH]),
        V.check_citations_and_quotes(ROOT, docs, check_http=False),
        V.check_repo_numbers(ROOT, docs),
        V.check_proposals(ROOT, docs),
        V.check_protected_paths(ROOT, base_ref="origin/justSilas"),
    ]
    assert len(results) == 6
    assert all(r.status == "PASS" for r in results), [(r.name, r.status, r.details) for r in results]
    url_map, quote_count = V.extract_urls_and_quotes(ROOT, docs)
    pids = sorted(set(V.PROPOSAL_ID_RX.findall(DOC_PATH.read_text(encoding="utf-8"))))
    assert pids == ["P9.1", "P9.2"]
    assert len(url_map) >= 10
    assert quote_count >= 8

    shallow_prot = V.check_protected_paths(
        ROOT,
        base_ref="refs/remotes/origin/nonexistent_shallow_base_ref",
    )
    assert shallow_prot.status == "PASS"
    no_git_prot = V.check_protected_paths(tmp_path, base_ref="origin/justSilas")
    assert no_git_prot.status in {"PASS", "WARN"}
