from __future__ import annotations

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
SCRIPT_PATH = ROOT / "scripts" / "audit_transcript_biases.py"
VERIFIER_PATH = ROOT / "scripts" / "verify_research_deception.py"
MONOGRAPH_PATH = ROOT / "docs" / "research" / "11_empirical_transcript_bias_forensics.md"
SELF_PATH = Path(__file__).resolve()

H = chr(35)
EM = chr(0x2014)
EN = chr(0x2013)
CO_TAG = "-".join(("Co", "Authored", "By"))


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


AUDIT_MOD = _load_module("audit_transcript_biases", SCRIPT_PATH)
VERIFIER_MOD = _load_module("verify_research_deception", VERIFIER_PATH)


@pytest.fixture(scope="module")
def cli_audit_run(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("transcript_bias_audit")
    out_json = out_dir / "audit.json"
    out_md = out_dir / "audit.md"
    t0 = time.monotonic()
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--root",
            str(ROOT),
            "--json",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    wall_s = time.monotonic() - t0
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    return {
        "wall_s": wall_s,
        "payload": payload,
        "file_json": json.loads(out_json.read_text(encoding="utf-8")),
        "md_text": out_md.read_text(encoding="utf-8"),
    }


def test_py_files_zero_comments_zero_dashes_pure_ascii():
    for path in (SCRIPT_PATH, SELF_PATH):
        src = path.read_text(encoding="utf-8")
        assert EM not in src, f"em-dash found in {path}"
        assert EN not in src, f"en-dash found in {path}"
        assert H not in src, f"raw hash char found in {path}"
        assert CO_TAG not in src, f"trailer tag found in {path}"
        assert all(ord(ch) < 128 for ch in src), f"non-ASCII char found in {path}"
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert not comment_tokens, f"Python comment found in {path}: {comment_tokens}"

    hygiene = VERIFIER_MOD.check_hygiene(ROOT, [], extra_py_files=[SCRIPT_PATH, SELF_PATH])
    assert hygiene.status == "PASS", hygiene.details


def test_cli_json_outputs_and_v14_frozen_hash(cli_audit_run):
    assert cli_audit_run["wall_s"] < 60.0
    payload = cli_audit_run["payload"]
    assert payload == cli_audit_run["file_json"]
    assert payload["elapsed_s"] < 60.0
    assert payload["tiers_version"] == "v1.4"
    assert payload["v14_frozen_hash"] == "a8f99c2537c91d72"
    assert payload["known_v_mode"] is True

    cv = payload["cross_verification"]
    assert cv["passed"] is True, cv["mismatches"]
    assert cv["checks_run"] >= 100
    assert cv["mismatches"] == []

    md_text = cli_audit_run["md_text"]
    assert "a8f99c2537c91d72" in md_text
    assert "68.03" in md_text
    assert "242 / 303" in md_text
    assert EM not in md_text
    assert EN not in md_text


def test_signature_1_demeanor_crowding_and_inproc_moderation(cli_audit_run):
    payload = cli_audit_run["payload"]
    fa = json.loads((ROOT / "results" / "failure_analysis_v1.4.json").read_text(encoding="utf-8"))
    fa_oc = fa["summary"]["opencode"]
    fa_ip = fa["summary"]["inproc"]
    fa_sv = fa["summary"]["solver"]

    s1 = payload["signatures"]["demeanor_interview_crowding"]
    assert math.isclose(s1["opencode_interviews_per_ep"], 2041 / 30, abs_tol=1e-4)
    assert round(s1["opencode_interviews_per_ep"], 2) == 68.03
    assert math.isclose(s1["inproc_interviews_per_ep"], fa_ip["interviews"], abs_tol=1e-4)
    assert s1["solver_interviews_per_ep"] == 0.0

    assert s1["opencode_days_played"] == 403
    assert s1["opencode_days_lt2_canaries"] == 303
    assert s1["opencode_days_lt2_full_budget"] == 242
    assert s1["opencode_interviews_on_lt2_full"] == 1503
    assert s1["inproc_days_lt2_canaries"] == 292
    assert s1["inproc_days_lt2_full_budget"] == 205
    assert s1["inproc_interviews_on_lt2_full"] == 1253

    assert round(s1["opencode_first_canary_day"], 1) == 3.0
    assert round(s1["inproc_first_canary_day"], 1) == 3.4
    assert s1["solver_first_canary_day"] == 1.0

    assert round(s1["opencode_canaries_before_accuse"], 1) == 8.5
    assert s1["opencode_plant_canary_calls_per_ep"] == 8.5
    assert round(s1["inproc_canaries_before_accuse"], 1) == 8.6
    assert round(s1["solver_canaries_before_accuse"], 1) == 14.1

    assert round(100.0 * s1["opencode_capacity_used"], 1) == 31.5
    assert round(100.0 * s1["inproc_capacity_used"], 1) == 33.0
    assert round(100.0 * s1["solver_capacity_used"], 1) == 66.7
    assert math.isclose(s1["opencode_capacity_used"], fa_oc["capacity_used"], abs_tol=1e-6)
    assert math.isclose(s1["solver_capacity_used"], fa_sv["capacity_used"], abs_tol=1e-6)

    assert s1["opencode_day1_2_interviews_total"] == 300
    assert s1["opencode_repeat_interviews_total"] == 1471
    assert round(100.0 * s1["opencode_repeat_interviews_share"], 1) == 72.1
    assert s1["opencode_interview_targets"] == {"mole": 503, "decoy": 0, "plain_innocent": 1536}
    assert round(s1["interview_kl_hard_nats"], 5) == 0.00477
    assert round(s1["canary_mi_hard_nats"], 5) == 0.86544

    evasive = payload["cohorts"]["opencode_hard_n30"]["interview_evasive_observed"]
    assert evasive == {"mole": 112, "innocent_or_decoy": 309}


def test_signature_2_cheap_talk_logs_and_restrictions(cli_audit_run):
    payload = cli_audit_run["payload"]
    s2 = payload["signatures"]["cheap_talk_and_log_distraction"]

    assert round(s2["opencode_read_access_logs_per_ep"], 2) == 12.27
    assert round(s2["inproc_read_access_logs_per_ep"], 2) == 11.80
    assert round(s2["solver_read_access_logs_per_ep"], 2) == 9.60

    rates = s2["theoretical_after_hours_rates_per_day"]
    assert math.isclose(rates["mole"], 0.30, abs_tol=1e-6)
    assert math.isclose(rates["decoy"], 1.10, abs_tol=1e-6)
    assert math.isclose(rates["company_total"], 6.20, abs_tol=1e-6)
    assert round(100.0 * rates["ppv_all"], 2) == 4.84
    assert round(100.0 * rates["ppv_ex_decoy"], 2) == 5.88

    obs_ah = s2["opencode_observed_after_hours"]
    assert obs_ah["mole"] == 95
    assert obs_ah["decoy"] == 390
    assert obs_ah["plain_innocent"] == 1690
    assert obs_ah["total"] == 2175
    assert round(100.0 * obs_ah["empirical_ppv_all"], 2) == 4.37
    assert round(100.0 * obs_ah["empirical_ppv_ex_decoy"], 2) == 5.32

    assert round(s2["opencode_search_messages_per_ep"], 2) == 4.23
    assert round(s2["opencode_read_message_per_ep"], 2) == 0.17
    assert math.isclose(s2["opencode_message_calls_per_ep"], 4.40, abs_tol=1e-4)
    assert s2["opencode_message_calls_after_decoy_seen"] == 24
    assert s2["opencode_message_snippets_returned"]["decoy"] == 88
    assert s2["opencode_message_snippets_returned"]["non_decoy"] == 301
    assert s2["opencode_read_message_targets"] == {"decoy": 2, "non_decoy": 3}
    assert s2["solver_message_snippets_returned"]["decoy"] == 106
    assert s2["solver_message_snippets_returned"]["non_decoy"] == 5

    assert s2["opencode_restrict_calls_total"] == 3
    assert s2["opencode_restrict_targets"] == {"mole": 2, "decoy": 0, "innocent": 1}
    assert s2["inproc_restrict_calls_total"] == 8
    assert s2["inproc_restrict_targets"] == {"mole": 1, "decoy": 0, "innocent": 7}
    assert s2["solver_restrict_calls_total"] == 0
    assert math.isclose(s2["restriction_v_cost_gap_30_seeds"], 0.12, abs_tol=1e-6)


def test_signature_3_thin_commitment_wrong_decomp_and_pooled_n32(cli_audit_run):
    payload = cli_audit_run["payload"]
    s3 = payload["signatures"]["loss_gambling_and_thin_commitment"]

    assert s3["opencode_accused_count"] == 29
    assert s3["opencode_horizon_abstain_count"] == 1
    assert s3["opencode_horizon_abstain_seeds"] == [11]
    assert s3["opencode_voluntary_abstain_among_29_accused"] == 0
    assert s3["opencode_voluntary_abstain_on_ev_negative"] == 0
    assert s3["opencode_ev_negative_seeds"] == [5, 18, 23]
    assert round(s3["opencode_ev_negative_v_lost"], 2) == 1.64

    assert s3["opencode_not_isolated_count"] == 9
    assert s3["opencode_not_isolated_seeds"] == [3, 5, 7, 8, 14, 15, 18, 20, 23]
    assert s3["inproc_not_isolated_count"] == 6
    assert s3["solver_not_isolated_count"] == 3
    assert round(s3["opencode_consistent_set_mean"], 2) == 1.83
    assert round(s3["inproc_consistent_set_mean"], 2) == 1.21
    assert round(s3["solver_consistent_set_mean"], 2) == 1.07

    assert round(s3["thin_commitment_v_lost_net"], 2) == 3.39
    assert round(s3["thin_commitment_v_lost_on_unresolved"], 2) == 3.50
    assert round(s3["abstention_seed11_v_lost"], 2) == 0.62
    assert round(s3["extra_leak_damage_v_lost"], 2) == 1.75
    assert round(s3["canary_cost_saved_v"], 2) == -1.69
    assert round(s3["raw_gap_v_sum"], 2) == 5.30
    assert round(s3["luck_adjusted_gap_v_sum"], 2) == 4.19

    wrong = s3["wrong_accusations"]
    assert wrong["counts"] == {
        "disclosed_fingerprint_flip": 2,
        "unresolved_pair_bet": 1,
        "negative_ev_gamble": 1,
    }
    by_seed = {e["seed"]: e for e in wrong["episodes"]}
    assert set(by_seed) == {1, 15, 18, 26}
    assert by_seed[1]["category"] == "disclosed_fingerprint_flip"
    assert by_seed[26]["category"] == "disclosed_fingerprint_flip"
    assert by_seed[15]["category"] == "unresolved_pair_bet"
    assert round(by_seed[15]["p_accused"], 2) == 0.80
    assert by_seed[18]["category"] == "negative_ev_gamble"
    assert by_seed[18]["p_accused"] < by_seed[18]["breakeven_p"]
    assert by_seed[18]["ev_accused"] < 0.0

    hl = s3["headline_primary_n30"]
    assert "post-hoc lock" in hl["seed_lock_note"]
    assert round(hl["opencode_score"], 3) == 0.322
    assert round(hl["opencode_ci95"], 3) == 0.199
    assert round(hl["solver_score"], 3) == 0.499
    assert round(hl["solver_ci95"], 3) == 0.119
    assert round(100.0 * hl["raw_ratio"]) == 65
    assert round(100.0 * hl["raw_ratio_lo"]) == 24
    assert round(100.0 * hl["raw_ratio_hi"]) == 98
    assert round(100.0 * hl["luck_adjusted_ratio"]) == 72
    assert round(100.0 * hl["luck_adjusted_ratio_lo"]) == 52
    assert round(100.0 * hl["luck_adjusted_ratio_hi"]) == 91

    pl = s3["extension_and_pooled"]
    assert pl["ext_seeds"] == [34, 37]
    assert pl["pooled_n"] == 32
    assert round(pl["pooled_score"], 3) == 0.349
    assert round(pl["pooled_ci95"], 3) == 0.190
    assert round(100.0 * pl["pooled_luck_adjusted_ratio"]) == 75
    assert round(100.0 * pl["pooled_luck_adjusted_ratio_lo"]) == 56
    assert round(100.0 * pl["pooled_luck_adjusted_ratio_hi"]) == 93


def test_signature_4_seed_forensics_overprecision_and_grok_contrast(cli_audit_run):
    payload = cli_audit_run["payload"]
    s4 = payload["signatures"]["seed_forensics_and_grok_contrast"]

    assert len(s4["per_seed"]) == 30
    assert len(s4["unresolved_commitment_seeds"]) == 9
    assert s4["unresolved_overprecision_pp_mean"] > 20.0

    per_seed = {r["seed"]: r for r in s4["per_seed"]}
    assert per_seed[18]["claimed_posterior_pct"] == 89.0
    assert round(per_seed[18]["p_accused"], 2) == 0.63
    assert per_seed[23]["claimed_posterior_pct"] == 82.0
    assert round(per_seed[23]["p_accused"], 2) == 0.45

    oc_tel = payload["cohorts"]["opencode_hard_n30"]["transcript_telemetry"]
    ip_tel = payload["cohorts"]["inproc_hard_n30"]["transcript_telemetry"]
    assert oc_tel["files_audited"] == 30
    assert oc_tel["rationales_present"] == 30
    assert ip_tel["files_audited"] == 30
    assert ip_tel["episodes_mentioning_breakeven_ev"] == 25

    grok = s4["grok_contrast"]
    assert grok["hard"]["n"] == 5
    assert grok["medium"]["n"] == 5
    assert math.isclose(grok["hard"]["interviews_per_ep"], 0.6, abs_tol=1e-6)
    assert grok["hard"]["accused_count"] == 4
    assert grok["hard"]["deliberate_abstentions"] == 1
    abstain_case = grok["hard_900000_abstention_case"]
    assert abstain_case is not None
    assert abstain_case["abstained"] is True
    assert abstain_case["mentions_breakeven_formula"] is True
    assert "53%" in abstain_case["rationale"]


def test_signature_5_unisolated_argmax_v13_codex_and_bias_tags(cli_audit_run):
    payload = cli_audit_run["payload"]
    assert payload["v13_frozen_hash"] == "8df71cf570bb48bc"

    tb = payload["signatures"]["cheap_talk_and_log_distraction"]["opencode_unisolated_after_hours_tiebreak"]
    assert tb["unisolated_count"] == 9
    assert tb["strict_argmax_count"] == 9
    assert tb["strict_argmax_share"] == 1.0
    tb_by_seed = {r["seed"]: r for r in tb["episodes"]}
    assert tb_by_seed[15]["consistent_after_hours"] == {"e34": 3, "e37": 1}
    assert tb_by_seed[18]["consistent_after_hours"] == {"e09": 1, "e27": 2, "e29": 6, "e37": 2}

    s4 = payload["signatures"]["seed_forensics_and_grok_contrast"]
    v13 = s4["v13_codex_historical"]
    assert v13["codex_mcp_medium_n11"]["n"] == 11
    assert v13["codex_mcp_medium_n11"]["wrong_seeds"] == [0, 4]
    assert v13["codex_mcp_medium_n11"]["abstain_seeds"] == []
    assert v13["codex_mcp_hard_n11"]["n"] == 11
    assert v13["codex_mcp_hard_n11"]["abstain_seeds"] == []
    assert v13["inproc_gpt55_hard_n8"]["n"] == 8
    assert math.isclose(v13["inproc_gpt55_hard_n8"]["log_reads_per_ep"], 33.75, abs_tol=1e-4)

    tags = s4["cognitive_bias_tag_rates"]
    assert tags["opencode_hard_n30"]["demeanor_interview_crowding"]["episodes_with"] == 30
    assert tags["opencode_hard_n30"]["cheap_talk_distraction"]["episodes_with"] == 30
    assert tags["opencode_hard_n30"]["unisolated_log_tiebreak"]["episodes_with"] == 9
    assert tags["opencode_hard_n30"]["below_breakeven_gamble"]["seeds"] == [5, 18, 23]
    assert tags["opencode_hard_n30"]["overprecision_inflation"]["episodes_with"] == 6
    assert tags["solver_hard_n30"]["demeanor_interview_crowding"]["episodes_with"] == 0
    assert tags["solver_hard_n30"]["cheap_talk_distraction"]["episodes_with"] == 0
    assert tags["solver_hard_n30"]["below_breakeven_gamble"]["episodes_with"] == 0


def test_monograph_11_gates_and_mole_strategy_schema():
    from canary.mole.dsl import MoleStrategy

    assert MONOGRAPH_PATH.is_file()
    results, meta = VERIFIER_MOD.verify_research_repo(
        root=ROOT,
        explicit_docs=[MONOGRAPH_PATH],
        check_http=False,
        require_flagship=False,
    )
    assert all(r.status == "PASS" for r in results), [(r.name, r.status, r.details) for r in results]
    assert meta["unique_url_count"] >= 8
    assert meta["verbatim_quote_count"] >= 8
    assert "P11.1" in meta["proposal_ids"]
    assert "P11.2" in meta["proposal_ids"]

    _, fences, unclosed = VERIFIER_MOD._parse_markdown_fences(MONOGRAPH_PATH.read_text(encoding="utf-8"))
    assert unclosed is None
    json_fences = [json.loads(f.content) for f in fences if f.lang.lower() == "json"]
    assert len(json_fences) >= 1
    parsed_strategies = [MoleStrategy.from_json(obj) for obj in json_fences if "rules" in obj]
    assert len(parsed_strategies) >= 1
    assert parsed_strategies[0].name == "echo_framing_careful_v14"
