"""Tests for scripts/frontier_transcript_forensics.py, transcript_forensics.json, and frontier_transcript_forensics_v14.md."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
SCRIPT_PATH = SCRIPTS_DIR / "frontier_transcript_forensics.py"
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "transcript_forensics.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_transcript_forensics_v14.md"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_module():
    spec = importlib.util.spec_from_file_location("frontier_transcript_forensics", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ftf = _load_module()


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _make_gitless_root(tmp_path: Path, name: str = "gitless_root", link_gap_md: bool = True) -> Path:
    syn_root = tmp_path / name
    (syn_root / "data" / "runs" / "committed").mkdir(parents=True)
    (syn_root / "results" / "frontier_replication").mkdir(parents=True)
    (syn_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(
        ROOT / "data" / "runs" / "committed" / "v1.4",
        syn_root / "data" / "runs" / "committed" / "v1.4",
    )
    os.symlink(
        ROOT / "results" / "frontier_replication" / "v1.4",
        syn_root / "results" / "frontier_replication" / "v1.4",
    )
    if link_gap_md:
        os.symlink(
            ROOT / "docs" / "reports" / "gap.md",
            syn_root / "docs" / "reports" / "gap.md",
        )
    assert not (syn_root / ".git").exists()
    return syn_root


@pytest.fixture(scope="module")
def computed_summary():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    env_before = dict(os.environ)
    try:
        out = ftf.compute_summary(root=ROOT, verify_replays=True)
    finally:
        mp.undo()
    assert dict(os.environ) == env_before
    return out


def test_check_cli_zero_subprocess_and_size_cap(computed_summary, monkeypatch, capsys):
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(
        ftf,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary),
    )
    assert ftf.main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "OK transcript_forensics=PASS committed_replays=472 replication_replays=305 active_transcripts=97" in out
    assert ftf.MAX_JSON_BYTES == 45_000
    assert JSON_PATH.stat().st_size < 45_000
    assert JSON_PATH.stat().st_size <= ftf.MAX_JSON_BYTES
    assert JSON_PATH.read_bytes() == ftf.serialize_summary_json(computed_summary).encode("utf-8")
    assert MD_PATH.read_bytes() == ftf.render_markdown(computed_summary).encode("utf-8")


def test_gitless_root_write_check_roundtrip(computed_summary, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    no_git_root = _make_gitless_root(tmp_path, name="zip_export_tree", link_gap_md=True)
    out_json = tmp_path / "out" / "transcript_forensics.json"
    out_md = tmp_path / "out" / "frontier_transcript_forensics_v14.md"

    monkeypatch.setattr(
        ftf,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: ftf.compute_summary.__wrapped__(root)
        if hasattr(ftf.compute_summary, "__wrapped__")
        else copy.deepcopy(computed_summary),
    )
    assert ftf.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert ftf.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert out_json.is_file() and out_md.is_file()
    assert out_json.stat().st_size < 45_000
    assert out_json.read_bytes() == JSON_PATH.read_bytes()
    assert out_md.read_bytes() == MD_PATH.read_bytes()
    assert ftf.main(["--root", str(no_git_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0


def test_provenance_honesty_raw_before_la_and_replay_invariants(computed_summary):
    assert computed_summary["schema_version"] == "v1.4-frontier-transcript-forensics-1"
    assert computed_summary["tiers_version"] == "v1.4"
    assert computed_summary["pure_cpu_zero_api_calls"] is True
    assert computed_summary["zero_git_runtime_dependency"] is True

    prov = computed_summary["provenance_and_locks"]
    p0 = prov["primary_0_29_lock"]
    assert p0["classification"] == "post_hoc_lock_not_preregistered"
    assert p0["episodes_commit"] == "8fd4dec"
    assert p0["seed_lock_commit"] == "671ed96"
    assert p0["lock_delay_seconds"] == 28
    assert "post-hoc lock" in p0["note"].lower()
    assert "not a pre-registration" in p0["note"].lower()

    g1 = prov["g1_hard_30_59_extension"]
    assert g1["classification"] == "pre_registered"
    assert g1["prereg_commit"] == "f9fb7a4a"
    assert g1["completed_seeds"] == [34, 37]
    assert g1["completed_n"] == 2

    gpt = prov["gpt_5_5_second_family"]
    assert gpt["classification"] == "pre_registered"
    assert gpt["prereg_commit"] == "cf394894"
    assert gpt["timeout_s"] == 7200
    assert gpt["max_spend_usd"] == 200.0
    assert gpt["committed_v14_episodes"] == 30

    ph = computed_summary["paired_hard_headline_0_29"]
    assert round(ph["carbon_mean_score"], 3) == 0.322
    assert round(ph["solver_mean_score"], 3) == 0.499
    assert round(ph["carbon_mean_post_expected"], 3) == 0.360
    assert round(ph["raw_ratio_vs_solver"] * 100) == 65
    assert round(ph["luck_adjusted_ratio_vs_solver"] * 100) == 72

    rv = computed_summary["replay_and_transcript_verification"]
    assert rv["committed_v14"]["total"] == 472
    assert rv["committed_v14"]["verified"] == 472
    assert rv["committed_v14"]["mismatches"] == 0
    assert rv["committed_v14"]["step_mismatches"] == 0
    assert rv["committed_v14"]["unwrapped_mcp_error_steps"] == 84
    assert rv["committed_v14"]["pre_1bc3e281_detail_normalized_steps"] == 321
    assert rv["replication_v14"]["total"] == 305
    assert rv["replication_v14"]["verified"] == 305
    assert rv["replication_v14"]["mismatches"] == 0
    assert rv["replication_v14"]["step_mismatches"] == 0
    assert rv["replication_v14"]["unwrapped_mcp_error_steps"] == 24
    assert rv["replication_v14"]["pre_1bc3e281_detail_normalized_steps"] == 156
    assert rv["combined_verified_episodes"] == 777
    assert rv["active_opencode_cohorts_count"] == 5
    assert rv["active_transcripts_verified"] == 97
    assert rv["step_sequence_mismatches"] == 0
    assert rv["unredacted_thought_signatures"] == 0
    assert rv["secret_key_leaks"] == 0

    md = MD_PATH.read_text(encoding="utf-8")
    for token in (
        "post-hoc lock",
        "not a pre-registration",
        "671ed96",
        "28 s",
        "8fd4dec",
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "f9fb7a4a",
        "cf394894",
        "1bc3e281",
    ):
        assert token in md
    assert md.index("65% [24%, 98%]") < md.index("72% [52%, 91%]")


def test_forensic_cohorts_bookkeeping_and_cases(computed_summary):
    by_id = {c["cohort_id"]: c for c in computed_summary["cohorts"]}
    assert set(by_id) == {
        "opencode_gemini_4_carbon_medium",
        "opencode_gemini_4_carbon_hard",
        "opencode_gemini_4_carbon_hard_ext",
        "opencode_gemini_4_carbon_hard_rep",
        "opencode_gemini_3_5_flash_medium",
    }

    for c in by_id.values():
        assert c["rule_awareness"]["careful_mole"]["count"] == 0

    c_hard = by_id["opencode_gemini_4_carbon_hard"]
    assert c_hard["n"] == 30
    assert c_hard["accused_count"] == 29
    assert c_hard["abstained_seeds"] == [11]
    assert c_hard["wrong_accusation_seeds"] == [1, 15, 18, 26]
    assert c_hard["certainty_calibration"]["decisive_count"] == 29
    assert c_hard["certainty_calibration"]["decisive_wrong_seeds"] == [1, 15, 18, 26]
    assert c_hard["certainty_calibration"]["sub_breakeven_seeds"] == [5, 18, 23]
    assert math.isclose(c_hard["observed_actions"]["mean_interviews"], 68.03333333333333, abs_tol=1e-6)

    pmb = computed_summary["paired_medium_bookkeeping_0_29"]
    assert pmb["carbon_medium"]["structured_count"] == 30
    assert pmb["flash_medium"]["structured_count"] == 20
    assert len(pmb["flash_medium"]["unstructured_seeds"]) == 10
    assert pmb["correlations_structured_bookkeeping"]["pooled_medium_n60"]["r_post_expected"] > 0.3
    assert pmb["correlations_structured_bookkeeping"]["within_flash_medium_n30"]["r_post_expected"] > 0.3

    cases = {c["case_id"]: c for c in computed_summary["annotated_cases"]}
    assert cases["hard_seed26_s1_noise_trap"]["accused"] == "e04"
    assert cases["hard_seed26_s1_noise_trap"]["correct"] is False
    assert cases["hard_seed11_day21_rational_abstention"]["accused"] is None
    assert cases["hard_seed18_sub_breakeven_wrong"]["sub_breakeven_accusation"] is True

    s34 = computed_summary["seed34_cross_run_convergence"]
    assert s34["converged_accused"] is True
    assert s34["g1_committed_ext"]["accused"] == "e29"
    assert s34["fr8_replication"]["accused"] == "e29"


def test_gap_ships_flash_hard_gate_false_and_true(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    syn_root = _make_gitless_root(tmp_path, name="flash_gate_root", link_gap_md=False)
    gap_file = syn_root / "docs" / "reports" / "gap.md"
    assert ftf.gap_ships_flash_hard(syn_root) is False

    gap_file.write_text("Primary headline: gemini-4-carbon hard 65% [24%, 98%]\n", encoding="utf-8")
    assert ftf.gap_ships_flash_hard(syn_root) is False
    sum_false = ftf.compute_summary(root=syn_root, verify_replays=False)
    assert sum_false["provenance_and_locks"]["flash_hard_gate"]["gap_ships_flash_hard"] is False
    assert sum_false["replay_and_transcript_verification"]["active_opencode_cohorts_count"] == 5
    assert sum_false["replay_and_transcript_verification"]["active_transcripts_verified"] == 97
    assert "OpenCode gemini-3.5-flash hard (0-29)" not in ftf.render_markdown(sum_false)

    gap_file.write_text(
        "Primary headline: gemini-4-carbon and opencode:google/gemini-3.5-flash hard (0-29)\n",
        encoding="utf-8",
    )
    assert ftf.gap_ships_flash_hard(syn_root) is True
    sum_true = ftf.compute_summary(root=syn_root, verify_replays=False)
    assert sum_true["provenance_and_locks"]["flash_hard_gate"]["gap_ships_flash_hard"] is True
    assert sum_true["replay_and_transcript_verification"]["active_opencode_cohorts_count"] == 6
    assert sum_true["replay_and_transcript_verification"]["active_transcripts_verified"] == 127
    json_true_bytes = len(ftf.serialize_summary_json(sum_true).encode("utf-8"))
    assert json_true_bytes < 45_000
    assert json_true_bytes <= ftf.MAX_JSON_BYTES
    assert "OpenCode gemini-3.5-flash hard (0-29)" in ftf.render_markdown(sum_true)


def test_parsers_compat_and_tamper_guards(computed_summary, monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)

    wrapped_err = {
        "ok": False,
        "error": json.dumps({"ok": False, "data": {}, "error": "bad variant map"}),
    }
    live_err = {"ok": False, "data": {"detail": "employee e99 unknown"}, "error": "bad variant map"}
    ok_match, flags = ftf.step_result_matches(wrapped_err, live_err)
    assert ok_match is True
    assert flags == {
        "unwrapped_mcp_error": True,
        "detail_normalized": True,
        "truncated_checked": False,
    }

    fake_google = "AI" + "za" + "SySyntheticKey" + ("X" * 22)
    fake_sk = "s" + "k-proj-" + ("Y" * 24)
    assert len(ftf.scan_secret_tokens(f"k1={fake_google} k2={fake_sk}")) == 2

    with pytest.raises(ValueError, match="unredacted thoughtSignature"):
        ftf.parse_opencode_transcript('{"thoughtSignature": "' + ("A" * 80) + '"}')

    with pytest.raises(ValueError, match="raw API key pattern"):
        ftf.parse_opencode_transcript(f"--- stdout\n{fake_google}\n")

    assert ftf.extract_verbalized_posterior("Bayesian posterior certainty is ~96.5% on e29.") == 0.965
    assert ftf.point_biserial([True, True, False, False], [1.0, 1.0, 0.0, 0.0]) == 1.0

    syn_root = _make_gitless_root(tmp_path, name="tamper_root", link_gap_md=True)
    out_json = tmp_path / "tamper_out" / "transcript_forensics.json"
    out_md = tmp_path / "tamper_out" / "frontier_transcript_forensics_v14.md"
    monkeypatch.setattr(
        ftf,
        "compute_summary",
        lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary),
    )

    assert ftf.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert ftf.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["paired_hard_headline_0_29"]["carbon_mean_score"] += 0.05
    out_json.write_text(ftf.serialize_summary_json(tampered), encoding="utf-8")
    assert ftf.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    out_json.write_text(ftf.serialize_summary_json(computed_summary), encoding="utf-8")
    orig_md = out_md.read_text(encoding="utf-8")
    out_md.write_text(orig_md + "\ntampered\n", encoding="utf-8")
    assert ftf.main(["--root", str(syn_root), "--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    sample_path = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
    first_ep = json.loads(sample_path.read_text(encoding="utf-8").splitlines()[0])
    assert ftf.verify_episode_pool([first_ep], "unit_ok")["verified"] == 1
    with pytest.raises(ValueError, match="replay mismatches"):
        ftf.verify_episode_pool([dict(first_ep, score=float(first_ep["score"]) + 0.25)], "unit_bad_score")
    with pytest.raises(ValueError, match="duplicate episodes"):
        ftf.verify_episode_pool([first_ep, dict(first_ep)], "unit_dup")


def test_strict_hygiene_no_hash_in_py_and_no_em_en_dashes():
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    this_test = Path(__file__).resolve()
    py_files = [SCRIPT_PATH, this_test]
    owned_files = [SCRIPT_PATH, JSON_PATH, MD_PATH, this_test]

    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
        src = pf.read_text(encoding="utf-8")
        assert hash_char not in src, f"found {hash_char!r} character in {pf}"

    for f in owned_files:
        txt = f.read_text(encoding="utf-8")
        assert em_dash not in txt, f"found em dash in {f}"
        assert en_dash not in txt, f"found en dash in {f}"

    assert JSON_PATH.stat().st_size < 45_000
    assert JSON_PATH.stat().st_size <= ftf.MAX_JSON_BYTES
