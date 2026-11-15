from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole import seed_generalization as SG

SCRIPT_PATH = ROOT / "canary" / "mole" / "seed_generalization.py"
JSON_PATH = ROOT / "results" / "mole_strategies" / "seed_generalization_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_seed_generalization_v14.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
HASH_CHAR = chr(35)
EMP_ID_RE = re.compile(r"\be\d{2,3}\b", re.IGNORECASE)


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
    assert len(raw_bytes) < SG.MAX_JSON_BYTES
    assert len(raw_bytes) < 90_000

    ok, msg = SG.check_seed_generalization_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = SG.main(["--check", "--out", str(JSON_PATH), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out

    raw_json = raw_bytes.decode("utf-8")
    payload = json.loads(raw_json)
    assert payload["study"] == "mole_seed_generalization_v14"
    assert payload["tiers_version"] == "v1.4"
    assert payload["tier"] == "hard"
    assert payload["api_calls"] == 0
    assert payload["baseline_policy"] == "default_v0"
    assert payload["n_blocks"] == 5
    assert payload["n_seeds_total"] == 100
    assert [b["seed_range"] for b in payload["blocks"]] == [
        "15000-15019",
        "25000-25019",
        "45000-45019",
        "65000-65019",
        "85000-85019",
    ]
    assert payload["policy_order"] == list(SG.POLICY_ORDER)
    assert SG.dumps_seed_generalization_json(payload) + "\n" == raw_json

    md_text = MD_PATH.read_text(encoding="utf-8")
    assert SG.format_seed_generalization_markdown(payload) == md_text

    summary_text = SG.format_seed_generalization_summary(payload)
    assert "UNIFORM_DISTANT_PASS=" in summary_text
    for pname in SG.POLICY_ORDER:
        assert pname in summary_text

    sm = payload["summary"]
    assert sm["n_policies"] == 10
    assert sm["all_pooled_passed"] is True
    assert sm["all_zero_baselines_exact"] is True
    assert sm["all_logs_shortcuts_bounded"] is True
    assert sum(sm["counts_by_classification"].values()) == 10
    assert sm["counts_by_classification"]["DISTANT_FAIL"] == 0

    for pname in SG.POLICY_ORDER:
        prow = payload["policies"][pname]
        assert prow["classification"] in SG.CLASSIFICATION_VALUES
        pl = prow["pooled"]
        assert float(pl["solver_acc"]) >= 0.85
        assert float(pl["solver_ratio"]) >= 0.50
        assert float(pl["logs_only_acc"]) <= 0.10
        assert float(pl["accuse_most_logs_acc"]) <= 0.10
        assert float(pl["do_nothing_max_abs"]) == 0.0
        assert float(pl["stop_early_quit_max_abs"]) == 0.0
        assert len(prow["blocks"]) == 5

    all_keys: set[str] = set()
    _collect_keys(payload, all_keys)
    for forbidden in (
        "mole",
        "true_mole",
        "mole_id",
        "canary_ids",
        "secret_mole",
        "decoy_id",
        "decoy",
        "transcript",
        "steps",
        "world_secret",
    ):
        assert forbidden not in all_keys


def test_check_seed_generalization_artifacts_catches_tampering(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ok_missing, msg_missing = SG.check_seed_generalization_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_missing is False
    assert "missing JSON" in msg_missing

    ok_missing_md, msg_missing_md = SG.check_seed_generalization_artifacts(
        json_path=JSON_PATH,
        md_path=tmp_path / "missing.md",
    )
    assert ok_missing_md is False
    assert "missing Markdown" in msg_missing_md

    ok_cap, msg_cap = SG.check_seed_generalization_artifacts(
        json_path=JSON_PATH,
        md_path=MD_PATH,
        max_json_bytes=1024,
    )
    assert ok_cap is False
    assert "exceeds size cap" in msg_cap

    md_text = MD_PATH.read_text(encoding="utf-8")

    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = SG.check_seed_generalization_artifacts(json_path=JSON_PATH, md_path=drifted_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(md_text + "\n" + EM_DASH + "\n", encoding="utf-8")
    ok_dash, msg_dash = SG.check_seed_generalization_artifacts(json_path=JSON_PATH, md_path=dash_md)
    assert ok_dash is False
    assert "dash" in msg_dash

    solver_pct_tag = "% of " + "solver"
    flash_tag = "gemini-3.5-" + "flash"
    coauthor_tag = "co-authored-" + "by"
    emp_tag = "e" + "07"
    fake_api_key = "sk-" + "fakefixtureabcdefghijklmn1234"

    for fname, snippet, expect_sub in (
        ("pct.md", f"50{solver_pct_tag}", solver_pct_tag),
        ("flash.md", flash_tag, "flash"),
        ("co.md", f"{coauthor_tag}: bot", "co-author"),
        ("emp.md", f"suspect {emp_tag} leaked", "employee identifier"),
        ("key.md", fake_api_key, "API key"),
    ):
        bad_md = tmp_path / fname
        bad_md.write_text(md_text + f"\n{snippet}\n", encoding="utf-8")
        ok_m, msg_m = SG.check_seed_generalization_artifacts(json_path=JSON_PATH, md_path=bad_md)
        assert ok_m is False
        assert expect_sub in msg_m

    base = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    leaked = copy.deepcopy(base)
    leaked["policies"]["default_v0"]["true_mole"] = "hidden"
    leaked_json = tmp_path / "leaked.json"
    leaked_json.write_text(SG.dumps_seed_generalization_json(leaked) + "\n", encoding="utf-8")
    ok_leak, msg_leak = SG.check_seed_generalization_artifacts(json_path=leaked_json, md_path=MD_PATH)
    assert ok_leak is False
    assert "forbidden secret key" in msg_leak

    bad_seed = copy.deepcopy(base)
    bad_seed["blocks"][0]["seeds"][0] = 6050
    bad_seed["seeds"][0] = 6050
    bad_seed_json = tmp_path / "bad_seed.json"
    bad_seed_json.write_text(SG.dumps_seed_generalization_json(bad_seed) + "\n", encoding="utf-8")
    ok_seed, msg_seed = SG.check_seed_generalization_artifacts(json_path=bad_seed_json, md_path=MD_PATH)
    assert ok_seed is False
    assert "seed hygiene" in msg_seed

    rc_bad = SG.main(["--check", "--out", str(bad_seed_json), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc_bad == 1
    assert "FAIL:" in captured.err

    bad_pgate = copy.deepcopy(base)
    bad_pgate["policies"]["surgical_trap_shield"]["pooled"]["gates"]["pooled_passed"] = False
    bad_pgate_json = tmp_path / "bad_pgate.json"
    bad_pgate_json.write_text(SG.dumps_seed_generalization_json(bad_pgate) + "\n", encoding="utf-8")
    ok_pgate, msg_pgate = SG.check_seed_generalization_artifacts(json_path=bad_pgate_json, md_path=MD_PATH)
    assert ok_pgate is False
    assert "pooled gate tampering" in msg_pgate

    bad_bgate = copy.deepcopy(base)
    bad_bgate["policies"]["surgical_trap_shield"]["blocks"]["block_15k"]["gates"]["block_passed"] = False
    bad_bgate_json = tmp_path / "bad_bgate.json"
    bad_bgate_json.write_text(SG.dumps_seed_generalization_json(bad_bgate) + "\n", encoding="utf-8")
    ok_bgate, msg_bgate = SG.check_seed_generalization_artifacts(json_path=bad_bgate_json, md_path=MD_PATH)
    assert ok_bgate is False
    assert "block gate tampering" in msg_bgate

    bad_cls = copy.deepcopy(base)
    bad_cls["policies"]["surgical_trap_shield"]["classification"] = "DISTANT_FAIL"
    bad_cls_json = tmp_path / "bad_cls.json"
    bad_cls_json.write_text(SG.dumps_seed_generalization_json(bad_cls) + "\n", encoding="utf-8")
    ok_cls, msg_cls = SG.check_seed_generalization_artifacts(json_path=bad_cls_json, md_path=MD_PATH)
    assert ok_cls is False
    assert "classification mismatch" in msg_cls


@pytest.mark.parametrize(
    "bad_spec",
    [
        "",
        "15000,,15001",
        "-1",
        "0",
        "29",
        "59",
        "0-59",
        "6000",
        "6199",
        "6205",
        "6812",
        "6999",
        "6000-6019",
        "30000",
        "30199",
        "30000-30010",
        "800000",
        "900000",
        "15000,15000",
        "15005-15001",
        "15005:15005",
    ],
)
def test_seed_hygiene_rejects_forbidden_and_malformed_specs(bad_spec: str) -> None:
    with pytest.raises(ValueError):
        SG.validate_distant_seeds(bad_spec, enforce_hygiene=True)


def test_seed_blocks_and_policy_registry_resolution() -> None:
    assert SG.validate_distant_seeds("60") == [60]
    assert SG.validate_distant_seeds("5999,7000,29999,30200,799999") == [5999, 7000, 29999, 30200, 799999]
    with pytest.raises(ValueError):
        SG.validate_distant_seeds([True])
    with pytest.raises(ValueError):
        SG.validate_distant_seeds([])

    blocks = SG.parse_seed_blocks("b1=15000-15001;b2=25000:25002")
    assert [b.name for b in blocks] == ["b1", "b2"]
    assert [list(b.seeds) for b in blocks] == [[15000, 15001], [25000, 25001]]

    with pytest.raises(ValueError):
        SG.parse_seed_blocks("b1=15000-15002;b2=15002-15004")
    with pytest.raises(ValueError):
        SG.parse_seed_blocks("dup=15000;dup=25000")
    with pytest.raises(ValueError):
        SG.parse_seed_blocks("b1=6200-6205")

    names = SG.list_distant_policy_names()
    assert names == list(SG.POLICY_ORDER)
    assert SG.resolve_distant_policy_name("default") == "default_v0"
    assert SG.resolve_distant_policy_name("portfolio") == "regret_portfolio_v14"
    assert SG.resolve_distant_policy_name("hof_r1") == "window_crowd_stale"
    assert SG.resolve_distant_policy_name("hof_r2") == "two_wave_blackout"

    port_spec = SG.get_distant_policy_spec("regret_portfolio_v14")
    port_inst = port_spec.instantiate(15000)
    assert port_inst.selected_name in ("surgical_trap_shield", "gemini_midsize_shield")

    with pytest.raises(KeyError):
        SG.resolve_distant_policy_name("nonexistent_policy_xyz")


def test_gates_classification_and_bootstrap_determinism() -> None:
    assert SG.classify_generalization_status(True, 5, 5) == "UNIFORM_DISTANT_PASS"
    assert SG.classify_generalization_status(True, 4, 5) == "POOLED_DISTANT_PASS"
    assert SG.classify_generalization_status(False, 5, 5) == "DISTANT_FAIL"

    g_ok = SG.evaluate_pooled_gates(
        policy_valid=True,
        solver_acc=0.90,
        solver_score=0.45,
        baseline_solver_score=0.60,
        logs_only_acc=0.05,
        accuse_most_logs_acc=0.10,
        do_nothing_max_abs=0.0,
        stop_early_quit_max_abs=0.0,
    )
    assert g_ok["pooled_passed"] is True
    assert SG.failed_gate_names(g_ok) == []

    g_fail = SG.evaluate_pooled_gates(
        policy_valid=True,
        solver_acc=0.80,
        solver_score=0.20,
        baseline_solver_score=0.60,
        logs_only_acc=0.15,
        accuse_most_logs_acc=0.0,
        do_nothing_max_abs=0.02,
        stop_early_quit_max_abs=0.0,
    )
    assert g_fail["pooled_passed"] is False
    assert set(SG.failed_gate_names(g_fail)) == {
        "solver_acc_ge_min",
        "solver_ratio_ge_min",
        "logs_only_le_max",
        "do_nothing_zero",
    }

    assert SG.paired_bootstrap_ci([]) == {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    assert SG.paired_bootstrap_ci([0.4, 0.4]) == {"mean": 0.4, "ci_low": 0.4, "ci_high": 0.4}
    ci_1 = SG.paired_bootstrap_ci([0.1, 0.3, 0.5, 0.9], n_boot=64, tag="sg")
    ci_2 = SG.paired_bootstrap_ci([0.1, 0.3, 0.5, 0.9], n_boot=64, tag="sg")
    assert ci_1 == ci_2
    assert ci_1["ci_low"] <= ci_1["mean"] <= ci_1["ci_high"]


def test_mini_end_to_end_cli_and_cache_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_path = tmp_path / "mini_cache.jsonl"
    out_json_1 = tmp_path / "mini_1.json"
    out_md_1 = tmp_path / "mini_1.md"
    common_args = [
        "--blocks",
        "b1=15000",
        "--policies",
        "default_v0",
        "--workers",
        "1",
        "--n-boot",
        "16",
        "--cache-jsonl",
        str(cache_path),
    ]
    rc1 = SG.main([*common_args, "--out", str(out_json_1), "--report-md", str(out_md_1)])
    assert rc1 == 0
    assert cache_path.is_file()
    ok1, msg1 = SG.check_seed_generalization_artifacts(json_path=out_json_1, md_path=out_md_1)
    assert ok1 is True, msg1

    def _forbid_worker(_task: Any) -> Any:
        raise AssertionError("expected 100% cache hit on second run")

    monkeypatch.setattr(SG, "_eval_policy_seed_worker", _forbid_worker)
    out_json_2 = tmp_path / "mini_2.json"
    out_md_2 = tmp_path / "mini_2.md"
    rc2 = SG.main([*common_args, "--out", str(out_json_2), "--report-md", str(out_md_2)])
    assert rc2 == 0
    assert out_json_2.read_text(encoding="utf-8") == out_json_1.read_text(encoding="utf-8")
    assert out_md_2.read_text(encoding="utf-8") == out_md_1.read_text(encoding="utf-8")


def test_pr_hygiene_zero_comments_dashes_employee_ids_and_forbidden_claims() -> None:
    coauthor_tag = "co-authored-" + "by"
    flash_35_tag = "gemini-3.5-" + "flash"
    flash_36_tag = "gemini-3.6-" + "flash"
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
        txt = p.read_text(encoding="utf-8")
        low = txt.lower()
        assert flash_35_tag not in low
        assert flash_36_tag not in low
        assert solver_pct_tag not in low
        assert EMP_ID_RE.search(txt) is None, f"employee ID found in {p}"
