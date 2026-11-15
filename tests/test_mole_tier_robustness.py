from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole import tier_robustness as TR

SCRIPT_PATH = ROOT / "canary" / "mole" / "tier_robustness.py"
JSON_PATH = ROOT / "results" / "mole_strategies" / "tier_robustness_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_tier_robustness_v14.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
HASH_CHAR = chr(35)


def _collect_keys(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, out)


def test_committed_artifacts_size_schema_and_check_verifier(capsys: pytest.CaptureFixture[str]) -> None:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()

    raw_bytes = JSON_PATH.read_bytes()
    assert len(raw_bytes) < TR.MAX_JSON_BYTES
    assert len(raw_bytes) < 95_000

    ok, msg = TR.check_tier_robustness_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = TR.main(["--check", "--out", str(JSON_PATH), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out

    raw_json = raw_bytes.decode("utf-8")
    payload = json.loads(raw_json)
    assert payload["study"] == "mole_tier_robustness_v14"
    assert payload["tiers_version"] == "v1.4"
    assert payload["api_calls"] == 0
    assert payload["baseline_strategy"] == "default_v0"
    assert payload["tiers"] == ["medium", "hard"]
    assert payload["n_seeds"] == 40
    assert payload["seeds"] == list(range(6300, 6340))
    assert payload["seed_range"] == "6300-6339"
    assert TR.dumps_tier_robustness_json(payload) + "\n" == raw_json

    md_text = MD_PATH.read_text(encoding="utf-8")
    assert TR.format_tier_robustness_markdown(payload) == md_text

    summary_table = TR.format_tier_robustness_summary(payload)
    assert "DUAL_TIER_PASS=" in summary_table
    for sname in payload["strategies"]:
        assert sname in summary_table

    cf_cfg = payload["counterfactual_config"]
    assert cf_cfg["sources"] == ["opencode", "inproc"]
    assert cf_cfg["medium_seeds"] == list(range(30))
    assert cf_cfg["hard_seeds"] == list(range(30))
    assert cf_cfg["medium_transcripts"] == 60
    assert cf_cfg["hard_transcripts"] == 60
    assert cf_cfg["total_transcripts"] == 120

    sm = payload["summary"]
    assert sm["n_strategies"] == 11
    assert sm["n_unique_canonical"] == 9
    assert sm["all_zero_baselines_exact_both_tiers"] is True
    assert sm["all_logs_shortcuts_bounded_both_tiers"] is True
    assert sm["strategies_with_dead_day_gt_14_on_medium"] == [
        "hof_r1_window_crowd_stale",
        "hof_r2_two_wave_blackout",
    ]
    assert sum(sm["counts_by_classification"].values()) == 11

    strats = payload["strategies"]
    assert strats["hof_r3_surgical_trap_shield"]["canonical_equivalent_of"] == "surgical_trap_shield"
    assert strats["hof_r4_early_burst_midgame_pace"]["canonical_equivalent_of"] == "early_burst_midgame_pace"
    assert (
        strats["hof_r3_surgical_trap_shield"]["tiers"]["medium"]["empirical_ledger_hash"]
        == strats["surgical_trap_shield"]["tiers"]["medium"]["empirical_ledger_hash"]
    )
    assert (
        strats["hof_r4_early_burst_midgame_pace"]["tiers"]["hard"]["empirical_ledger_hash"]
        == strats["early_burst_midgame_pace"]["tiers"]["hard"]["empirical_ledger_hash"]
    )

    for srow in strats.values():
        assert srow["classification"] in TR.CLASSIFICATION_VALUES
        for t in ("medium", "hard"):
            pol = srow["tiers"][t]["policies"]
            assert pol["do_nothing"]["all_zero"] is True
            assert pol["stop_early_quit"]["all_zero"] is True
            assert float(pol["logs_only"]["acc"]) <= 0.10
            assert float(pol["accuse_most_logs"]["acc"]) <= 0.10

    all_keys: set[str] = set()
    _collect_keys(payload, all_keys)
    for forbidden in ("mole", "true_mole", "mole_id", "canary_ids", "secret_mole", "decoy_id"):
        assert forbidden not in all_keys


def test_check_tier_robustness_artifacts_catches_tampering(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok_missing, msg_missing = TR.check_tier_robustness_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_missing is False
    assert "missing JSON" in msg_missing

    ok_missing_md, msg_missing_md = TR.check_tier_robustness_artifacts(
        json_path=JSON_PATH,
        md_path=tmp_path / "missing.md",
    )
    assert ok_missing_md is False
    assert "missing Markdown" in msg_missing_md

    ok_cap, msg_cap = TR.check_tier_robustness_artifacts(
        json_path=JSON_PATH,
        md_path=MD_PATH,
        max_json_bytes=1024,
    )
    assert ok_cap is False
    assert "exceeds size cap" in msg_cap

    md_text = MD_PATH.read_text(encoding="utf-8")
    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(md_text + "\ndrifted extra line\n", encoding="utf-8")
    ok_drift, msg_drift = TR.check_tier_robustness_artifacts(json_path=JSON_PATH, md_path=drifted_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(md_text + "\n" + EM_DASH + "\n", encoding="utf-8")
    ok_dash, msg_dash = TR.check_tier_robustness_artifacts(json_path=JSON_PATH, md_path=dash_md)
    assert ok_dash is False
    assert "dash" in msg_dash

    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    coauthor_tag = "co-authored-" + "by"

    flash_md = tmp_path / "flash.md"
    flash_md.write_text(md_text + f"\n{flash_tag}\n", encoding="utf-8")
    ok_flash, msg_flash = TR.check_tier_robustness_artifacts(json_path=JSON_PATH, md_path=flash_md)
    assert ok_flash is False
    assert flash_tag in msg_flash

    pct_md = tmp_path / "pct.md"
    pct_md.write_text(md_text + f"\n42{solver_pct_tag}\n", encoding="utf-8")
    ok_pct, msg_pct = TR.check_tier_robustness_artifacts(json_path=JSON_PATH, md_path=pct_md)
    assert ok_pct is False
    assert solver_pct_tag in msg_pct

    co_md = tmp_path / "co.md"
    co_md.write_text(md_text + f"\n{coauthor_tag}: bot\n", encoding="utf-8")
    ok_co, msg_co = TR.check_tier_robustness_artifacts(json_path=JSON_PATH, md_path=co_md)
    assert ok_co is False
    assert "co-author" in msg_co

    base = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    leaked = copy.deepcopy(base)
    leaked["strategies"]["default_v0"]["true_mole"] = "e01"
    leaked_json = tmp_path / "leaked.json"
    leaked_json.write_text(TR.dumps_tier_robustness_json(leaked) + "\n", encoding="utf-8")
    ok_leak, msg_leak = TR.check_tier_robustness_artifacts(json_path=leaked_json, md_path=MD_PATH)
    assert ok_leak is False
    assert "forbidden secret key" in msg_leak

    bad_seed = copy.deepcopy(base)
    bad_seed["seeds"][0] = 30000
    bad_seed_json = tmp_path / "bad_seed.json"
    bad_seed_json.write_text(TR.dumps_tier_robustness_json(bad_seed) + "\n", encoding="utf-8")
    ok_seed, msg_seed = TR.check_tier_robustness_artifacts(json_path=bad_seed_json, md_path=MD_PATH)
    assert ok_seed is False
    assert "seed hygiene" in msg_seed

    rc_bad = TR.main(["--check", "--out", str(bad_seed_json), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc_bad == 1
    assert "FAIL:" in captured.err

    bad_gate = copy.deepcopy(base)
    bad_gate["strategies"]["default_v0"]["tiers"]["medium"]["gates"]["tier_passed"] = False
    bad_gate_json = tmp_path / "bad_gate.json"
    bad_gate_json.write_text(TR.dumps_tier_robustness_json(bad_gate) + "\n", encoding="utf-8")
    ok_gate, msg_gate = TR.check_tier_robustness_artifacts(json_path=bad_gate_json, md_path=MD_PATH)
    assert ok_gate is False
    assert "gate tampering" in msg_gate

    bad_cls = copy.deepcopy(base)
    bad_cls["strategies"]["default_v0"]["classification"] = "FAIL"
    bad_cls_json = tmp_path / "bad_cls.json"
    bad_cls_json.write_text(TR.dumps_tier_robustness_json(bad_cls) + "\n", encoding="utf-8")
    ok_cls, msg_cls = TR.check_tier_robustness_artifacts(json_path=bad_cls_json, md_path=MD_PATH)
    assert ok_cls is False
    assert "classification mismatch" in msg_cls


@pytest.mark.parametrize(
    "bad_spec",
    [
        "",
        "6300,,6301",
        "-1",
        "0",
        "29",
        "59",
        "0-59",
        "55-62",
        "30000",
        "30199",
        "30000-30199",
        "6300,30050",
        "800000",
        "900000",
        "6300,6300",
        "6305-6301",
        "6305:6305",
    ],
)
def test_seed_hygiene_rejects_invalid_and_forbidden_seeds(bad_spec: str) -> None:
    with pytest.raises(ValueError):
        TR.normalize_robustness_seeds(bad_spec, enforce_hygiene=True)


def test_seed_hygiene_accepts_clean_specs_and_registry_resolution() -> None:
    assert TR.normalize_robustness_seeds("60") == [60]
    assert TR.normalize_robustness_seeds("6300-6302") == [6300, 6301, 6302]
    assert TR.normalize_robustness_seeds("6300:6303") == [6300, 6301, 6302]
    assert TR.normalize_robustness_seeds("29999,30200,799999") == [29999, 30200, 799999]
    with pytest.raises(ValueError):
        TR.normalize_robustness_seeds([True])
    with pytest.raises(ValueError):
        TR.normalize_robustness_seeds([])

    names = TR.list_tier_strategy_names()
    assert len(names) == 11
    assert TR.resolve_tier_strategy_name("default") == "default_v0"
    assert TR.resolve_tier_strategy_name("hof_1") == "hof_r1_window_crowd_stale"
    assert TR.resolve_tier_strategy_name("hof_r3") == "hof_r3_surgical_trap_shield"
    assert TR.resolve_tier_strategy_name("window_crowd_stale") == "hof_r1_window_crowd_stale"
    spec = TR.get_tier_strategy_spec("surgical_trap_shield")
    assert spec.to_strategy().name == "surgical_trap_shield"
    with pytest.raises(KeyError):
        TR.resolve_tier_strategy_name("unknown_nonexistent_strategy")


def test_gates_classification_and_bootstrap_determinism() -> None:
    assert TR.classify_tier_status(True, True) == "DUAL_TIER_PASS"
    assert TR.classify_tier_status(False, True) == "HARD_ONLY_PASS"
    assert TR.classify_tier_status(True, False) == "FAIL"
    assert TR.classify_tier_status(False, False) == "FAIL"

    g_ok = TR.evaluate_tier_gates(
        dsl_valid=True,
        solver_acc=0.85,
        solver_score=0.35,
        baseline_solver_score=0.60,
        logs_only_acc=0.10,
        accuse_most_logs_acc=0.05,
        do_nothing_max_abs=0.0,
        stop_early_quit_max_abs=0.0,
    )
    assert g_ok["tier_passed"] is True
    assert TR.failed_gate_names(g_ok) == []

    g_fail = TR.evaluate_tier_gates(
        dsl_valid=True,
        solver_acc=0.80,
        solver_score=0.20,
        baseline_solver_score=0.60,
        logs_only_acc=0.15,
        accuse_most_logs_acc=0.0,
        do_nothing_max_abs=0.01,
        stop_early_quit_max_abs=0.0,
    )
    assert g_fail["tier_passed"] is False
    assert set(TR.failed_gate_names(g_fail)) == {
        "solver_acc_ge_min",
        "solver_ratio_ge_min",
        "logs_only_le_max",
        "do_nothing_zero",
    }

    assert TR.paired_bootstrap_ci([]) == {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    assert TR.paired_bootstrap_ci([0.25, 0.25]) == {"mean": 0.25, "ci_low": 0.25, "ci_high": 0.25}
    ci_a = TR.paired_bootstrap_ci([0.1, 0.3, 0.5, 0.9], n_boot=64, tag="unit")
    ci_b = TR.paired_bootstrap_ci([0.1, 0.3, 0.5, 0.9], n_boot=64, tag="unit")
    assert ci_a == ci_b
    assert ci_a["ci_low"] <= ci_a["mean"] <= ci_a["ci_high"]

    with pytest.raises(ValueError):
        TR.paired_bootstrap_ci([0.1, 0.2], n_boot=0)
    with pytest.raises(ValueError):
        TR.paired_bootstrap_ci([0.1, 0.2], ci=1.0)


def test_mini_end_to_end_cli_and_cache_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "mini_cache.jsonl"
    out_json_1 = tmp_path / "mini_1.json"
    out_md_1 = tmp_path / "mini_1.md"
    common_args = [
        "--seeds",
        "6300",
        "--cf-seeds",
        "0",
        "--cf-sources",
        "inproc",
        "--strategies",
        "default_v0",
        "--workers",
        "1",
        "--n-boot",
        "16",
        "--cache-jsonl",
        str(cache_path),
    ]
    rc1 = TR.main([*common_args, "--out", str(out_json_1), "--report-md", str(out_md_1)])
    assert rc1 == 0
    assert cache_path.is_file()
    ok1, msg1 = TR.check_tier_robustness_artifacts(json_path=out_json_1, md_path=out_md_1)
    assert ok1 is True, msg1

    def _forbid_worker(_task: Any) -> Any:
        raise AssertionError("expected 100% cache hit on second run")

    monkeypatch.setattr(TR, "_eval_canonical_seed_worker", _forbid_worker)
    out_json_2 = tmp_path / "mini_2.json"
    out_md_2 = tmp_path / "mini_2.md"
    rc2 = TR.main([*common_args, "--out", str(out_json_2), "--report-md", str(out_md_2)])
    assert rc2 == 0
    assert out_json_2.read_text(encoding="utf-8") == out_json_1.read_text(encoding="utf-8")
    assert out_md_2.read_text(encoding="utf-8") == out_md_1.read_text(encoding="utf-8")


def test_pr_hygiene_zero_comments_dashes_and_forbidden_claims() -> None:
    coauthor_tag = "co-authored-" + "by"
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"

    for py_file in (SCRIPT_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment token found in {py_file}"
        py_text = py_file.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"hash character found in {py_file}"

    for p in (SCRIPT_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = p.read_text(encoding="utf-8")
        assert txt.isascii(), f"non-ASCII character in {p}"
        assert EM_DASH not in txt, f"em-dash in {p}"
        assert EN_DASH not in txt, f"en-dash in {p}"
        assert UNICODE_MINUS not in txt, f"unicode minus in {p}"
        assert coauthor_tag not in txt.lower(), f"coauthor trailer in {p}"

    for p in (JSON_PATH, MD_PATH):
        low = p.read_text(encoding="utf-8").lower()
        assert flash_tag not in low
        assert solver_pct_tag not in low
