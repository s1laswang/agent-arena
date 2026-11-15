from __future__ import annotations

import copy
import importlib.util
import io
import json
import math
import sys
import time
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "audit_seed6_seed26_forensics.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_research_deception.py"
DOC_PATH = ROOT / "docs" / "research" / "12_seed6_caught_vs_seed26_fooled_forensics.md"
SELF_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


AUDIT = _load_module("audit_seed6_seed26_forensics", SCRIPT_PATH)
VERIFIER = _load_module("verify_research_deception_for_seed6_26", VERIFIER_PATH)


def test_cli_check_and_json_parity_under_runtime_budget(capsys):
    t0 = time.monotonic()
    rc = AUDIT.main(["--root", str(ROOT), "--check", "--json"])
    elapsed = time.monotonic() - t0
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert rc == 0
    assert elapsed < 5.0
    assert payload["check_passed"] is True
    assert payload["check_errors"] == []
    assert payload["tiers_version"] == "v1.4"
    assert payload["v14_hash"] == "a8f99c2537c91d72"
    assert payload["seeds"] == [6, 26]
    assert payload["total_replay_discrepancies"] == 0
    assert payload["failure_analysis_parity_errors"] == []

    rc_human = AUDIT.main(["--root", str(ROOT), "--check"])
    human_out = capsys.readouterr().out
    assert rc_human == 0
    assert "CHECK STATUS: PASS" in human_out
    assert "a8f99c2537c91d72" in human_out


def test_seed6_caught_vs_seed26_fooled_exact_forensics():
    payload = AUDIT.run_forensic_audit(ROOT)
    assert AUDIT.validate_audit_payload(payload) == []

    s6_g = payload["episodes"]["seed_6"]["opencode_gemini_4_carbon"]
    s6_s = payload["episodes"]["seed_6"]["reference_solver"]
    s26_g = payload["episodes"]["seed_26"]["opencode_gemini_4_carbon"]
    s26_s = payload["episodes"]["seed_26"]["reference_solver"]

    assert s6_g["mole_id"] == s6_s["mole_id"] == "e34"
    assert s6_g["decoy_id"] == s6_s["decoy_id"] == "e20"
    assert s6_g["outcome_label"] == "caught"
    assert s6_g["correct"] is True
    assert s6_g["accused_id"] == "e34"
    assert s6_g["accuse_day"] == 6
    assert math.isclose(s6_g["replay_score"], 0.73, abs_tol=1e-9)
    assert s6_g["canary_summary"]["planted_count"] == 7
    assert s6_g["canary_summary"]["first_canary_day"] == 1
    assert s6_g["canary_summary"]["tiny_confirmation_count"] == 0
    assert s6_g["tool_counts"]["interview"] == 25
    assert s6_g["tool_counts"]["read_access_logs"] == 5
    assert s6_g["canary_summary"]["ground_truth_flips"] == []
    assert math.isclose(s6_g["commitment"]["p_mole"], 0.9981352492512117, abs_tol=1e-9)
    assert math.isclose(s6_g["commitment"]["p_accused"], 0.9981352492512117, abs_tol=1e-9)
    assert s6_g["commitment"]["p_accused"] > s6_g["commitment"]["p_breakeven_expected_V"]

    assert s6_s["correct"] is True
    assert s6_s["accused_id"] == "e34"
    assert s6_s["accuse_day"] == 6
    assert math.isclose(s6_s["replay_score"], 0.71, abs_tol=1e-9)
    assert s6_s["canary_summary"]["planted_count"] == 9
    assert s6_s["canary_summary"]["tiny_confirmation_count"] == 2
    assert s6_s["tool_counts"].get("interview", 0) == 0
    assert math.isclose(s6_s["commitment"]["p_mole"], 0.9994827308069345, abs_tol=1e-9)

    assert s26_g["mole_id"] == s26_s["mole_id"] == "e08"
    assert s26_g["decoy_id"] == s26_s["decoy_id"] == "e38"
    assert s26_g["outcome_label"] == "fooled"
    assert s26_g["correct"] is False
    assert s26_g["accused_id"] == "e04"
    assert s26_g["accuse_day"] == 10
    assert math.isclose(s26_g["replay_score"], -1.0, abs_tol=1e-9)
    assert s26_g["canary_summary"]["planted_count"] == 8
    assert s26_g["canary_summary"]["first_canary_day"] == 4
    assert s26_g["tool_counts"]["interview"] == 43
    assert s26_g["tool_counts"]["read_access_logs"] == 9

    for d_idx in range(3):
        assert s26_g["daily_trace"][d_idx]["canaries_planted"] == []

    day8_row = s26_g["daily_trace"][7]
    assert day8_row["day"] == 8
    assert day8_row["n_consistent"] == 3
    assert day8_row["top_suspect"] == "e04"
    assert day8_row["cum_after_hours"]["accused"] == 3
    assert day8_row["cum_after_hours"]["mole"] == 1

    day9_row = s26_g["daily_trace"][8]
    assert day9_row["day"] == 9
    assert day9_row["top_suspect"] == "e08"
    assert day9_row["top_is_mole"] is True
    assert day9_row["p_mole"] > day9_row["p_accused"]
    assert day9_row["cum_after_hours"]["mole"] == 4
    assert day9_row["cum_after_hours"]["accused"] == 3

    flips_26 = s26_g["canary_summary"]["ground_truth_flips"]
    assert len(flips_26) == 1
    assert flips_26[0] == {
        "doc_id": "c6-2",
        "planted_day": 6,
        "surfaced_day": 10,
        "shown_variant": "S1",
        "true_variant": "S3",
    }
    assert s26_g["commitment"]["consistent_suspects"] == ["e04"]
    assert math.isclose(s26_g["commitment"]["p_accused"], 0.9504440769307383, abs_tol=1e-9)
    assert math.isclose(s26_g["commitment"]["p_mole"], 0.02673505539968284, abs_tol=1e-9)
    assert s26_g["commitment"]["p_accused"] > s26_g["commitment"]["p_breakeven_expected_V"]

    assert s26_s["correct"] is True
    assert s26_s["accused_id"] == "e08"
    assert s26_s["accuse_day"] == 7
    assert math.isclose(s26_s["replay_score"], 0.69, abs_tol=1e-9)
    assert s26_s["canary_summary"]["planted_count"] == 11
    assert s26_s["canary_summary"]["first_canary_day"] == 1
    assert s26_s["canary_summary"]["tiny_confirmation_count"] == 1
    assert s26_s["tool_counts"].get("interview", 0) == 0
    assert s26_s["canary_summary"]["ground_truth_flips"] == []
    assert math.isclose(
        payload["paired_comparison"]["26"]["raw_score_gap_solver_minus_gemini"],
        1.69,
        abs_tol=1e-9,
    )


def test_validator_rejects_corrupted_hash_discrepancy_and_flip():
    base = AUDIT.run_forensic_audit(ROOT)

    bad_hash = copy.deepcopy(base)
    bad_hash["v14_hash"] = "0000000000000000"
    assert any("v14_hash" in e for e in AUDIT.validate_audit_payload(bad_hash))

    bad_disc = copy.deepcopy(base)
    bad_disc["total_replay_discrepancies"] = 1
    assert any("total_replay_discrepancies" in e for e in AUDIT.validate_audit_payload(bad_disc))

    bad_flip = copy.deepcopy(base)
    bad_flip["episodes"]["seed_26"]["opencode_gemini_4_carbon"]["canary_summary"]["ground_truth_flips"] = []
    assert any("c6-2" in e for e in AUDIT.validate_audit_payload(bad_flip))

    bad_post = copy.deepcopy(base)
    bad_post["episodes"]["seed_6"]["opencode_gemini_4_carbon"]["daily_trace"][0]["posterior_sum"] = 0.5
    assert any("posterior sum" in e for e in AUDIT.validate_audit_payload(bad_post))


def test_monograph_12_strict_research_verifier_and_dsl_parity(capsys):
    from canary.mole.dsl import MoleStrategy

    assert DOC_PATH.is_file(), f"missing monograph: {DOC_PATH}"
    rc = VERIFIER.main(["--root", str(ROOT), "--docs", str(DOC_PATH), "--strict"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "0 WARN, 0 FAIL" in out

    results, meta = VERIFIER.verify_research_repo(root=ROOT, explicit_docs=[DOC_PATH])
    assert all(r.status == "PASS" for r in results), [(r.name, r.status, r.details) for r in results]
    assert set(meta["proposal_ids"]) >= {"P12.1", "P12.2"}
    assert meta["unique_url_count"] >= 8
    assert meta["verbatim_quote_count"] >= 8

    doc_text = DOC_PATH.read_text(encoding="utf-8")
    for token in (
        "a8f99c2537c91d72",
        "post-hoc locked",
        "gen_single_hit_closure_lure",
        "n_confirming_canaries_on_top_suspect",
        "S3 -> S1",
        "1.69 V",
        "93%",
        "116%",
        "131%",
    ):
        assert token in doc_text, f"missing expected forensic token {token!r} in {DOC_PATH}"

    _, fences, unclosed = VERIFIER._parse_markdown_fences(doc_text)
    assert unclosed is None
    parsed_strategies = []
    for fence in fences:
        if fence.lang.lower() == "json":
            obj = json.loads(fence.content)
            if isinstance(obj, dict) and {"name", "rules", "default"} <= set(obj.keys()):
                ms = MoleStrategy.from_json(obj)
                parsed_strategies.append(ms.name)
    assert "burnashev_confirmation_evader_v14" in parsed_strategies


def test_zero_comments_zero_dashes_pure_ascii_hygiene():
    doc_src = DOC_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in doc_src
    assert EN_DASH not in doc_src

    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em-dash found in {path}"
        assert EN_DASH not in src, f"en-dash found in {path}"
        assert HASH_CHAR not in src, f"raw hash char found in {path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comments, f"Python comment found in {path}: {comments}"

    hygiene = VERIFIER.check_hygiene(ROOT, [DOC_PATH], extra_py_files=[SCRIPT_PATH, SELF_PATH])
    assert hygiene.status == "PASS", hygiene.details
