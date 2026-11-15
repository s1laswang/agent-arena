"""Tests for scripts/frontier_stopping_counterfactual_v14.py and its JSON/Markdown deliverables."""
from __future__ import annotations

import importlib.util
import io
import json
import math
import os
import subprocess
import sys
import tokenize
from pathlib import Path

import pytest

from canary.rules import tier_params_for_episode
from canary.solver.policy import SolverPolicy
from canary.types import Step

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "frontier_stopping_counterfactual_v14.py"
TEST_PATH = Path(__file__).resolve()
JSON_PATH = ROOT / "results" / "frontier_replication" / "v1.4" / "stopping_counterfactual_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "frontier_stopping_counterfactual_v14.md"

MODULE_NAME = "frontier_stopping_counterfactual_v14_mod"

EXPECTED_IDS_GATED = [
    "opencode_gemini_4_carbon_medium",
    "opencode_gemini_4_carbon_hard",
    "opencode_gpt_5_5_hard",
    "inproc_gemini_4_carbon_medium",
    "inproc_gemini_4_carbon_hard",
    "opencode_gemini_3_5_flash_medium",
    "opencode_gemini_4_carbon_hard_30_59_union",
    "solver_medium",
    "solver_hard",
]
EXPECTED_COUNTS_GATED = [30, 30, 30, 30, 30, 30, 6, 30, 30]

EXPECTED_IDS_ALL = [
    "opencode_gemini_4_carbon_medium",
    "opencode_gemini_4_carbon_hard",
    "opencode_gpt_5_5_hard",
    "inproc_gemini_4_carbon_medium",
    "inproc_gemini_4_carbon_hard",
    "opencode_gemini_3_5_flash_medium",
    "opencode_gemini_3_5_flash_hard",
    "opencode_gemini_4_carbon_hard_30_59_union",
    "solver_medium",
    "solver_hard",
]
EXPECTED_COUNTS_ALL = [30, 30, 30, 30, 30, 30, 30, 6, 30, 30]


def _load_mod():
    spec = importlib.util.spec_from_file_location(MODULE_NAME, SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = mod
    spec.loader.exec_module(mod)
    return mod


fsc = _load_mod()


def _forbid_subprocess(mp: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess forbidden: {args}")

    mp.setattr(subprocess, "run", _fail)
    mp.setattr(subprocess, "Popen", _fail)
    mp.setattr(subprocess, "check_call", _fail)
    mp.setattr(subprocess, "check_output", _fail)


def _strip_keys(mp: pytest.MonkeyPatch) -> None:
    for var in (
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CANARY_WORLD_SECRET",
    ):
        mp.delenv(var, raising=False)


@pytest.fixture(scope="module")
def audit_data():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    _strip_keys(mp)
    env_before = dict(os.environ)
    try:
        out = fsc.compute_audit(root=ROOT, enforce_expected_counts=True)
        assert dict(os.environ) == env_before
    finally:
        mp.undo()
    return out


def test_hygiene_ascii_no_dashes_no_hash_comments():
    assert MODULE_NAME in sys.modules
    for path in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        raw = path.read_bytes()
        text = raw.decode("ascii")
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text
    assert JSON_PATH.stat().st_size <= 35_000
    for py_path in (SCRIPT_PATH, TEST_PATH):
        py_bytes = py_path.read_bytes()
        assert 35 not in py_bytes
        toks = list(tokenize.tokenize(io.BytesIO(py_bytes).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT]


def test_provenance_counts_and_stopping_metrics(audit_data, monkeypatch):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    monkeypatch.setattr(fsc, "compute_audit", lambda root=ROOT, enforce_expected_counts=True: audit_data)
    assert fsc.main(["--check"]) == 0
    assert JSON_PATH.read_text(encoding="utf-8") == fsc.serialize_json(audit_data)
    assert MD_PATH.read_text(encoding="utf-8") == fsc.render_markdown(audit_data)

    assert audit_data["tiers_version"] == "v1.4"
    assert audit_data["upstream_justsilas_sync_commit"] == "5f9b3297"
    assert audit_data["zero_live_api_calls"] is True
    assert audit_data["zero_subprocesses"] is True
    assert audit_data["zero_git_dependency"] is True
    assert audit_data["taus"] == [0.60, 0.70, 0.80, 0.85, 0.90, 0.95]

    prov = audit_data["provenance"]
    assert prov["upstream_head_commit"] == "5f9b3297"
    assert prov["committed_v14_episodes"] == 472
    assert prov["replication_v14_episodes"] == 305
    assert prov["combined_v14_episodes"] == 777
    assert prov["primary_0_29_lock_commit"] == "671ed96"
    assert prov["primary_0_29_episodes_commit"] == "8fd4dec"
    assert prov["gpt_5_5_prereg_commit"] == "cf394894"
    assert prov["gpt_5_5_results_commit"] == "ca0a0dc0"
    assert prov["gpt_5_5_clean_rc0_non_accuse_seeds"] == [0, 17]
    assert prov["g1_ext_prereg_commit"] == "f9fb7a4a"
    assert prov["g1_seeds"] == [34, 37]
    assert prov["fr8_rep_seeds"] == [30, 34, 42, 45, 57]
    assert prov["carbon_hard_30_59_dedup_union_seeds"] == [30, 34, 37, 42, 45, 57]
    assert prov["carbon_hard_30_59_source_by_seed"]["34"] == "committed_g1"
    assert prov["harbor_rehearsal_final_commit"] == "d0ead011"
    assert prov["harbor_rehearsal_ratios_pct"] == [93, 116, 131]

    ships_flash = fsc.gap_ships_flash_hard(ROOT)
    exp_ids = EXPECTED_IDS_ALL if ships_flash else EXPECTED_IDS_GATED
    exp_counts = EXPECTED_COUNTS_ALL if ships_flash else EXPECTED_COUNTS_GATED
    cohorts = audit_data["cohorts"]
    assert [c["cohort_id"] for c in cohorts] == exp_ids
    assert [c["n"] for c in cohorts] == exp_counts

    by_id = {c["cohort_id"]: c for c in cohorts}
    ch = by_id["opencode_gemini_4_carbon_hard"]
    assert ch["breakeven_counterfactual"]["sub_breakeven_seeds"] == [5, 18, 23]
    assert math.isclose(ch["raw_mean"], 0.322333, abs_tol=1e-5)
    assert math.isclose(ch["breakeven_counterfactual"]["cf_raw_mean"], 0.342667, abs_tol=1e-5)
    assert math.isclose(ch["luck_mean"], 0.35954, abs_tol=1e-5)
    assert math.isclose(ch["breakeven_counterfactual"]["cf_luck_mean"], 0.390773, abs_tol=1e-5)
    assert ch["gap_decomposition"]["luck"]["evidence_share_of_gap"] > 0.75

    fl = by_id["opencode_gemini_3_5_flash_medium"]
    assert fl["breakeven_counterfactual"]["sub_breakeven_seeds"] == [8, 11, 13, 22, 26, 29]
    assert fl["gap_decomposition"]["luck"]["stopping_share_of_gap"] > 0.55

    gp = by_id["opencode_gpt_5_5_hard"]
    assert gp["non_accuse_seeds"] == [0, 17]
    assert gp["breakeven_counterfactual"]["sub_breakeven_known_v_count"] == 0
    assert gp["breakeven_counterfactual"]["sub_breakeven_seeds"] == [5]
    assert gp["gap_decomposition"]["luck"]["positive_ev_abstention_seeds"] == [0, 17]
    assert gp["gap_decomposition"]["luck"]["positive_ev_abstention_loss"] > 0.04
    assert gp["gap_decomposition"]["luck"]["non_map_accusation_seeds"] == []
    assert by_id["opencode_gemini_4_carbon_hard"]["gap_decomposition"]["luck"]["non_map_accusation_seeds"] == []
    assert by_id["inproc_gemini_4_carbon_medium"]["gap_decomposition"]["luck"]["non_map_accusation_seeds"] == [11]
    gnf = audit_data["gpt_5_5_non_accuse_forensics"]
    assert gnf["seeds"] == [0, 17]
    assert all(ep["clean_rc0_zero_day"] is True and ep["p_top"] > 0.94 for ep in gnf["episodes"])

    u6 = by_id["opencode_gemini_4_carbon_hard_30_59_union"]
    assert u6["seeds"] == [30, 34, 37, 42, 45, 57]
    assert u6["breakeven_counterfactual"]["sub_breakeven_count"] == 0

    assert by_id["solver_medium"]["breakeven_counterfactual"]["sub_breakeven_count"] == 0
    assert by_id["solver_hard"]["breakeven_counterfactual"]["sub_breakeven_count"] == 0
    assert by_id["solver_medium"]["non_accuse_seeds"] == [20, 21, 29]

    for c in cohorts:
        bc = c["breakeven_counterfactual"]
        assert bc["cf_luck_delta"] >= -1e-9
        assert bc["kept_accusations"] == c["accused_count"] - bc["sub_breakeven_count"]
        sweeps = c["threshold_sweep"]
        assert [s["tau"] for s in sweeps] == [0.60, 0.70, 0.80, 0.85, 0.90, 0.95]
        kept_seq = [s["kept_accusations"] for s in sweeps]
        assert kept_seq == sorted(kept_seq, reverse=True)
        for s in sweeps:
            assert s["abstained_count"] == c["n"] - s["kept_accusations"]
        gl = c["gap_decomposition"]["luck"]
        assert gl["map_choice_ev_loss"] >= -1e-9
        assert gl["positive_ev_abstention_loss"] >= -1e-9
        assert math.isclose(
            gl["map_choice_ev_loss"] + gl["positive_ev_abstention_loss"] + gl["pure_information_gathering_deficit"],
            gl["evidence_collection_deficit"],
            abs_tol=1e-5,
        )
        for kind in ("luck", "raw"):
            gd = c["gap_decomposition"][kind]
            assert math.isclose(
                gd["sub_breakeven_stopping_loss"] + gd["evidence_collection_deficit"],
                gd["total_gap"],
                abs_tol=1e-5,
            )
            if gd["stopping_share_of_gap"] is not None:
                assert math.isclose(
                    gd["stopping_share_of_gap"] + gd["evidence_share_of_gap"],
                    1.0,
                    abs_tol=1e-5,
                )


def test_fast_belief_exact_parity_with_solver_policy():
    ep_file = ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon/medium/episodes.jsonl"
    with ep_file.open(encoding="utf-8") as fh:
        lines = [json.loads(fh.readline()) for _ in range(3)]
    for ep in lines:
        steps_raw = ep.get("steps") or []
        acc_idx = next((i for i, s in enumerate(steps_raw) if s.get("tool") == "accuse"), len(steps_raw))
        steps_pre = [Step(s.get("t", 0), s.get("day", 0), s.get("tool", ""), s.get("args") or {}, s.get("result")) for s in steps_raw[:acc_idx]]
        sp = SolverPolicy(tier_params_for_episode(str(ep["tier"]), steps_pre))
        for st in steps_pre:
            sp._ingest(st)
        sp.seen = acc_idx
        p_ref = sp.belief()
        p_fast = fsc._fast_belief(sp)
        assert p_ref.keys() == p_fast.keys()
        for emp in p_ref:
            assert math.isclose(p_ref[emp], p_fast[emp], rel_tol=1e-12, abs_tol=1e-12)


def test_gap_flash_hard_gate_and_cli_roundtrip(monkeypatch, tmp_path, capsys):
    _forbid_subprocess(monkeypatch)
    _strip_keys(monkeypatch)
    mock_root = tmp_path / "ws"
    (mock_root / "data" / "runs" / "committed").mkdir(parents=True)
    (mock_root / "results" / "frontier_replication").mkdir(parents=True)
    (mock_root / "docs" / "reports").mkdir(parents=True)
    os.symlink(ROOT / "data/runs/committed/v1.4", mock_root / "data/runs/committed/v1.4")
    os.symlink(ROOT / "results/frontier_replication/v1.4", mock_root / "results/frontier_replication/v1.4")
    gap_file = mock_root / "docs/reports/gap.md"
    out_j = tmp_path / "out.json"
    out_m = tmp_path / "out.md"

    gap_file.write_text("Primary headline: gemini-4-carbon hard 65%\n", encoding="utf-8")
    assert fsc.gap_ships_flash_hard(mock_root) is False
    rc = fsc.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--write", "--check", "--stdout"])
    assert rc == 0
    captured = capsys.readouterr().out
    assert "Canary v1.4 Bayes Stopping-Rule Counterfactual" in captured
    assert "gemini-3.5-flash hard" not in captured
    assert "0.373" not in captured

    orig_md = out_m.read_text(encoding="utf-8")
    out_m.write_text(orig_md + "\ntampered\n", encoding="utf-8")
    assert fsc.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--check"]) == 1
    out_m.write_text(orig_md, encoding="utf-8")

    tampered_json = json.loads(out_j.read_text(encoding="utf-8"))
    tampered_json["cohorts"][0]["raw_mean"] = 0.999
    out_j.write_text(json.dumps(tampered_json), encoding="utf-8")
    assert fsc.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--check"]) == 1
    assert fsc.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--write", "--check"]) == 0

    gap_file.write_text("Includes gemini-3.5-flash hard 0-29\n", encoding="utf-8")
    assert fsc.gap_ships_flash_hard(mock_root) is True
    audit_true = fsc.compute_audit(root=mock_root, enforce_expected_counts=True)
    assert [c["cohort_id"] for c in audit_true["cohorts"]] == EXPECTED_IDS_ALL
    by_id = {c["cohort_id"]: c for c in audit_true["cohorts"]}
    assert by_id["opencode_gemini_3_5_flash_hard"]["breakeven_counterfactual"]["sub_breakeven_count"] == 10
    assert by_id["opencode_gemini_3_5_flash_hard"]["gap_decomposition"]["luck"]["non_map_accusation_seeds"] == [10]
    assert fsc.main(["--root", str(mock_root), "--out-json", str(out_j), "--out-md", str(out_m), "--check"]) == 1
