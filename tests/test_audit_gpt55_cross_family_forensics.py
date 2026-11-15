from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import math
import subprocess
import sys
import time
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DOC_PATH = ROOT / "docs" / "research" / "18_cross_family_gpt55_vs_gemini_forensics.md"
SCRIPT_PATH = ROOT / "scripts" / "audit_gpt55_cross_family_forensics.py"
VERIFY_PATH = ROOT / "scripts" / "verify_research_deception.py"
SELF_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"
CO_TAG = "-".join(("co", "authored", "by:"))


def _load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load_mod("audit_gpt55_cross_family_forensics", SCRIPT_PATH)
V = _load_mod("verify_research_deception_w4", VERIFY_PATH)


@pytest.fixture(scope="module")
def fast_audit_bundle(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("gpt55_forensics")
    out_json = out_dir / "report.json"
    buf = io.StringIO()
    t0 = time.monotonic()
    with contextlib.redirect_stdout(buf):
        rc = S.main(["--fast", "--check", "--json", "--out-json", str(out_json)])
    wall_s = time.monotonic() - t0
    assert rc == 0
    stdout_payload = json.loads(buf.getvalue())
    file_payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert stdout_payload == file_payload
    return {"report": stdout_payload, "wall_s": wall_s}


def test_pure_ascii_zero_comments_zero_hash_zero_dashes() -> None:
    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em-dash found in {py_path}"
        assert EN_DASH not in src, f"en-dash found in {py_path}"
        assert HASH_CH not in src, f"raw hash char found in {py_path}"
        assert CO_TAG not in src.lower(), f"co-author trailer found in {py_path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {py_path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert all(tok.type != tokenize.COMMENT for tok in tokens), f"Python comment found in {py_path}"

    doc_src = DOC_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in doc_src
    assert EN_DASH not in doc_src
    assert CO_TAG not in doc_src.lower()
    assert doc_src.isascii()


def test_v14_frozen_hash_blackwell_and_sub_2s_budget(fast_audit_bundle) -> None:
    from canary import rules

    assert rules.TIERS_VERSION == "v1.4"
    assert S.compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE) == S.EXPECTED_V14_HASH
    assert fast_audit_bundle["wall_s"] < 2.0

    report = fast_audit_bundle["report"]
    assert report["passed"] is True
    assert report["v14_frozen_hash"] == "a8f99c2537c91d72"

    bw = report["blackwell_channel_dominance"]
    assert bw["g_match_rational"] == "224/925"
    assert bw["g_mismatch_rational"] == "184/925"
    assert math.isclose(bw["g_match_evasive"], 224.0 / 925.0, abs_tol=1e-8)
    assert math.isclose(bw["g_mismatch_evasive"], 184.0 / 925.0, abs_tol=1e-8)
    assert bw["max_reconstruction_err"] < 1e-15
    assert math.isclose(bw["canary_mi_nats"], 0.86544, abs_tol=1e-5)
    assert math.isclose(bw["interview_kl_nats"], 0.004774, abs_tol=1e-6)
    assert bw["mi_to_kl_ratio"] == 181.27

    human_txt = S.format_human_report(report)
    assert "[PASS]" in human_txt
    assert "101% [" in human_txt
    assert "84% [" in human_txt


def test_gpt55_vs_gemini_vs_solver_cohort_forensics(fast_audit_bundle) -> None:
    report = fast_audit_bundle["report"]
    parity = report["committed_table_parity"]
    assert parity["all_parity_checks_passed"] is True
    assert all(parity["checks"].values())
    assert parity["gpt55_prereg_git_sha"].startswith("cf394894")
    assert math.isclose(parity["gpt55_reported_cost_usd"], 38.908, abs_tol=1e-3)

    f400 = parity["fresh_400_seeds_context"]
    assert f400["n_seeds"] == 400
    assert f400["gpt55_habit_reparam_solver_mean"] == 0.496
    assert f400["unchanged_solver_mean"] == 0.561

    g = report["cohorts"]["gpt55"]
    assert g["n"] == 30
    assert round(g["score_mean"], 3) == 0.504
    assert round(g["score_ci95"], 3) == 0.064
    assert round(100.0 * g["raw_ratio_to_solver"]) == 101
    assert 0.75 <= g["raw_ratio_boot95"][0] <= 0.83
    assert 1.30 <= g["raw_ratio_boot95"][1] <= 1.45
    assert round(100.0 * g["luck_adjusted_ratio_to_solver"]) == 84
    assert 0.64 <= g["luck_adjusted_boot95"][0] <= 0.70
    assert 1.00 <= g["luck_adjusted_boot95"][1] <= 1.06
    assert g["total_canaries"] == 515
    assert g["accepted_ok_canaries"] == 514
    assert round(g["canaries_per_ep"], 2) == 17.17
    assert round(g["accepted_ok_canaries_per_ep"], 2) == 17.13
    assert g["total_interviews"] == 125
    assert g["accepted_ok_interviews"] == 124
    assert round(g["interviews_per_ep"], 2) == 4.17
    assert round(100.0 * g["interview_share_of_calls"]) == 6
    assert g["correct_count"] == 28
    assert g["wrong_count"] == 0
    assert g["no_accusation_count"] == 2
    assert g["accusation_precision"] == 1.0
    assert g["accuse_day_1dp_str"] == "10.2"
    assert g["day1_canary_start_count"] == 30
    assert g["below_060_posterior_count"] == 0
    assert g["cadence_days"]["pre_terminal_two_canary_days"] == 257
    assert g["cadence_days"]["pre_terminal_days"] == 274

    slips = g["prose_action_slips"]
    assert [sl["seed"] for sl in slips] == [0, 17]
    assert slips[0]["prose_accused"] == "e38"
    assert slips[0]["true_mole_matched"] is True
    assert slips[0]["consistent_set_is_singleton_target"] is True
    assert slips[0]["solver_posterior_p_prose"] == 0.949
    assert slips[0]["counterfactual_score_if_accused"] == 0.66
    assert slips[1]["prose_accused"] == "e28"
    assert slips[1]["true_mole_matched"] is True
    assert slips[1]["consistent_set_is_singleton_target"] is True
    assert slips[1]["solver_posterior_p_prose"] == 0.963
    assert slips[1]["counterfactual_score_if_accused"] == 0.64

    m = report["cohorts"]["gemini"]
    assert round(m["score_mean"], 3) == 0.322
    assert round(m["score_ci95"], 3) == 0.199
    assert m["total_canaries"] == 255
    assert m["accepted_ok_canaries"] == 254
    assert round(m["accepted_ok_canaries_per_ep"], 2) == 8.47
    assert m["total_interviews"] == 2041
    assert m["correct_count"] == 25
    assert m["wrong_count"] == 4
    assert m["no_accusation_count"] == 1
    assert m["cadence_days"]["under_planted_full_budget_days"] == 242
    assert m["cadence_days"]["under_planted_days"] == 303
    assert m["prose_action_slips"] == []

    sol = report["cohorts"]["solver"]
    assert sol["score_mean"] == 0.499
    assert sol["total_canaries"] == 424
    assert sol["total_interviews"] == 0
    assert (sol["correct_count"], sol["wrong_count"], sol["no_accusation_count"]) == (29, 1, 0)


def test_proposals_p18_1_and_p18_2_and_zero_leakage(fast_audit_bundle) -> None:
    from canary.mole.dsl import MoleStrategy
    from canary.types import Step

    report = fast_audit_bundle["report"]
    p1 = report["proposal_p18_1_cadence_evader_sleeper"]
    assert p1["proposal_id"] == "P18.1"
    assert p1["catchability_passed"] is True
    assert p1["cadence_evader_sleeper_v14"]["solver_acc"] >= 0.85
    assert p1["gpt55_proxy_score_drop"] > 0.12

    parsed_strat = MoleStrategy.from_json(S.CADENCE_EVADER_SLEEPER_V14)
    assert parsed_strat.name == "cadence_evader_sleeper_v14"
    _, fences, unclosed = V._parse_markdown_fences(DOC_PATH.read_text(encoding="utf-8"))
    assert unclosed is None
    strat_fences = [
        json.loads(f.content)
        for f in fences
        if f.lang.lower() == "json" and "rules" in f.content
    ]
    assert len(strat_fences) == 1
    assert MoleStrategy.from_json(strat_fences[0]).to_json() == parsed_strat.to_json()

    p2 = report["proposal_p18_2_action_slip_vs_bias"] if "proposal_p18_2_action_slip_vs_bias" in report else report["proposal_p18_2_action_slip_vs_epistemic_bias"]
    assert p2["proposal_id"] == "P18.2"
    assert p2["zero_mole_leakage_invariant"] == "I(Social; Mole | PublicDayFacts) = 0"
    assert p2["public_day_facts_zero_mole_leakage"] is True
    assert p2["public_consistent_set_exact_parity"] == "60/60"
    assert p2["public_consistent_set_all_matched"] is True

    gpt_dec = p2["decompositions"]["gpt55"]
    gem_dec = p2["decompositions"]["gemini"]
    assert math.isclose(gpt_dec["total_paired_luck_adjusted_deficit_v"], 2.44628, abs_tol=1e-5)
    assert gpt_dec["buckets"]["protocol_action_slip"]["seeds"] == [0, 17]
    assert math.isclose(gpt_dec["buckets"]["protocol_action_slip"]["paired_luck_adjusted_loss_v"], 1.25202, abs_tol=1e-5)
    assert round(gpt_dec["slip_repaired_counterfactual"]["raw_mean"], 3) == 0.547
    assert gem_dec["buckets"]["protocol_action_slip"]["episode_count"] == 0
    assert gem_dec["buckets"]["horizon_starvation"]["seeds"] == [11]
    assert len(gem_dec["buckets"]["unisolated_epistemic_tiebreak"]["seeds"]) == 9
    assert math.isclose(gem_dec["total_paired_raw_deficit_v"], 5.30, abs_tol=1e-6)

    synthetic_steps = [
        Step(t=1, day=1, tool="list_employees", args={}, result={"ok": True, "data": {"employees": ["e00", "e01"]}}),
        Step(t=2, day=1, tool="plant_canary", args={"assignment": {"e00": "A", "e01": "B"}}, result={"ok": True, "data": {"canary_id": "c1"}}),
        Step(t=3, day=2, tool="check_leak_feed", args={}, result={"ok": True, "data": {"items": [{"doc_id": "c1", "variant": "A"}]}}),
    ]
    cls_slip = S.classify_episode_public_forensics(synthetic_steps, "Accusing e00 from canary c1.")
    assert cls_slip["bucket"] == "protocol_action_slip"
    assert cls_slip["public_consistent_set"] == ["e00"]
    cls_starve = S.classify_episode_public_forensics(synthetic_steps, "Time expired without accusing.")
    assert cls_starve["bucket"] == "horizon_starvation"


def test_shallow_ci_depth1_no_tags_and_verifier_6_of_6(monkeypatch, tmp_path: Path, fast_audit_bundle) -> None:
    real_run = subprocess.run

    def forbid_git_subprocess(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]) == "git":
            raise AssertionError(f"audit script must not shell out to git in shallow CI: {cmd}")
        return real_run(cmd, *args, **kwargs)

    cohorts = fast_audit_bundle["report"]["cohorts"]
    monkeypatch.setattr(subprocess, "run", forbid_git_subprocess)
    parity = S.verify_committed_tables_parity(ROOT, cohorts)
    assert parity["all_parity_checks_passed"] is True
    monkeypatch.setattr(subprocess, "run", real_run)

    hyg = V.check_hygiene(ROOT, [DOC_PATH], extra_py_files=[SCRIPT_PATH, SELF_PATH])
    assert hyg.status == "PASS", hyg.details

    results, meta = V.verify_research_repo(
        root=ROOT,
        explicit_docs=[DOC_PATH],
        check_http=False,
        strict_http=False,
        base_ref="origin/nonexistent-ref-simulating-shallow-depth1-ci",
    )
    assert len(results) == 6
    assert all(r.status == "PASS" for r in results), [(r.name, r.status, r.details) for r in results]
    assert meta["unique_url_count"] >= 15
    assert meta["verbatim_quote_count"] >= 8
    assert {"P18.1", "P18.2"} <= set(meta["proposal_ids"])

    shallow_guard = tmp_path / "shallow_no_git"
    (shallow_guard / ".github").mkdir(parents=True)
    (shallow_guard / ".github" / "protected-paths.txt").write_text("canary/env.py\ncanary/rules.py\nharbor/\n", encoding="utf-8")
    prot_res = V.check_protected_paths(shallow_guard, base_ref="origin/justSilas")
    assert prot_res.status in {"PASS", "WARN"}
