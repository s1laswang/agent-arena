from __future__ import annotations

import copy
import json
from pathlib import Path
import re
import sys
import tokenize

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.mole import discipline_curve as D
from canary.mole.strategies import list_strategy_names
from canary.solver.policy import SolverPolicy

MODULE_PATH = ROOT / "canary" / "mole" / "discipline_curve.py"
JSON_PATH = ROOT / "results" / "mole_strategies" / "discipline_curve_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_discipline_curve_v14.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
HASH_CHAR = chr(35)


def _load_committed_report() -> dict:
    assert JSON_PATH.is_file()
    return json.loads(JSON_PATH.read_text(encoding="utf-8"))


def test_rung_specs_and_policy_construction() -> None:
    names = D.list_rung_names()
    assert names == [
        "undisciplined_gemini_proxy",
        "fix_day1_canary_only",
        "fix_breakeven_abstain_only",
        "fix_gather_hint_both",
        "full_bayesian_solver",
    ]
    for idx, rname in enumerate(names):
        spec = D.get_rung_spec(rname)
        assert spec.index == idx
        assert spec.to_dict()["name"] == rname
        pol_a = D.make_rung_policy(rname, tier="hard", seed=6400)
        pol_b = D.make_rung_policy(rname, tier="hard", seed=6400)
        assert pol_a is not pol_b
        if rname == "full_bayesian_solver":
            assert isinstance(pol_a, SolverPolicy)
        else:
            assert isinstance(pol_a, D.DisciplinedGeminiProxy)
            assert pol_a.fix_day1_canary is spec.fix_day1_canary
            assert pol_a.fix_breakeven_abstain is spec.fix_breakeven_abstain

    proxy = D.DisciplinedGeminiProxy(seed=6400, fix_day1_canary=True, fix_breakeven_abstain=True)
    assert proxy.breakeven_threshold(0.0) == 1.0
    assert proxy.breakeven_threshold(-0.2) == 1.0
    assert proxy.breakeven_threshold(1.0) == pytest.approx(0.5)
    assert proxy.breakeven_threshold(0.6) == pytest.approx(1.0 / 1.6)

    with pytest.raises(KeyError, match="unknown discipline rung"):
        D.get_rung_spec("nonexistent_rung")


@pytest.mark.parametrize(
    "bad_seeds",
    [
        "",
        [],
        [True],
        ["6400"],
        [-1],
        "0",
        "29",
        "30",
        "59",
        "0-59",
        "58-62",
        "30000",
        "30100",
        "30199",
        "30000-30199",
        "6400,30042",
        "800000",
        "800001",
        "900000",
        "6400,6400",
    ],
)
def test_seed_hygiene_rejects_forbidden_seeds(bad_seeds) -> None:
    with pytest.raises(ValueError):
        D.normalize_discipline_seeds(bad_seeds, enforce_hygiene=True)


def test_seed_hygiene_accepts_fresh_disjoint_seeds() -> None:
    assert D.normalize_discipline_seeds("60-60") == [60]
    assert D.normalize_discipline_seeds("6400-6479") == list(D.DEFAULT_DISCIPLINE_SEEDS)
    assert len(D.DEFAULT_DISCIPLINE_SEEDS) == 80
    assert D.normalize_discipline_seeds([60, 29999, 30200, 799999]) == [60, 29999, 30200, 799999]


def test_paired_bootstrap_ci_and_regret_decomposition_identity() -> None:
    c1 = D.paired_bootstrap_ci([0.1, 0.3, 0.5, 0.7], n_boot=256, seed=42, tag="t1")
    c2 = D.paired_bootstrap_ci([0.1, 0.3, 0.5, 0.7], n_boot=256, seed=42, tag="t1")
    assert c1 == c2
    assert c1["ci_low"] <= c1["mean"] <= c1["ci_high"]

    empty_ci = D.paired_bootstrap_ci([], n_boot=64, seed=42)
    assert empty_ci["n"] == 0
    assert empty_ci["mean"] == 0.0

    const_ci = D.paired_bootstrap_ci([0.4, 0.4, 0.4], n_boot=64, seed=42, tag="const")
    assert const_ci["mean"] == pytest.approx(0.4)
    assert const_ci["ci_half_width"] == 0.0

    with pytest.raises(ValueError, match="n_boot"):
        D.paired_bootstrap_ci([0.1, 0.2], n_boot=0)
    with pytest.raises(ValueError, match="ci"):
        D.paired_bootstrap_ci([0.1, 0.2], ci=1.0)

    scores = {
        "undisciplined_gemini_proxy": [-1.0, 0.20, 0.40, 0.00],
        "fix_day1_canary_only": [0.30, 0.20, -1.00, 0.50],
        "fix_breakeven_abstain_only": [0.00, 0.20, 0.40, 0.00],
        "fix_gather_hint_both": [0.30, 0.20, 0.00, 0.50],
        "full_bayesian_solver": [0.70, 0.60, 0.50, 0.80],
    }
    dec = D.decompose_strategy_regret("unit_strat", scores, n_boot=128, bootstrap_seed=7)
    assert dec["identity_abs_error"] == 0.0
    assert (
        dec["delayed_canary_regret"]["mean"]
        + dec["gamble_discipline_regret"]["mean"]
        + dec["residual_evasion_framing_regret"]["mean"]
    ) == pytest.approx(dec["total_regret"]["mean"], abs=1e-6)
    assert dec["canary_abstain_interaction"]["mean"] == pytest.approx(
        dec["gamble_discipline_regret"]["mean"] - dec["standalone_abstain_regret"]["mean"],
        abs=1e-6,
    )

    missing = dict(scores)
    missing.pop("fix_gather_hint_both")
    with pytest.raises(ValueError, match="missing rungs"):
        D.decompose_strategy_regret("unit_strat", missing, n_boot=32)

    unequal = dict(scores)
    unequal["full_bayesian_solver"] = [0.70, 0.60]
    with pytest.raises(ValueError, match="identical length"):
        D.decompose_strategy_regret("unit_strat", unequal, n_boot=32)


def test_committed_artifacts_consistency_and_gates(capsys: pytest.CaptureFixture[str]) -> None:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    raw_size = JSON_PATH.stat().st_size
    assert raw_size < 100_000
    assert raw_size < D.MAX_JSON_BYTES

    ok, msg = D.check_discipline_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = D.main(["--check", "--out", str(JSON_PATH), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out

    raw_json = JSON_PATH.read_text(encoding="utf-8")
    md_text = MD_PATH.read_text(encoding="utf-8")
    report = _load_committed_report()
    assert D.dumps_discipline_json(report) + "\n" == raw_json
    assert D.format_discipline_markdown_report(report) == md_text

    assert report["study"] == "mole_discipline_curve_v14"
    assert report["tier"] == "hard"
    assert report["n_seeds"] == 80
    assert report["seed_range"] == "6400-6479"
    assert report["seeds"] == list(range(6400, 6480))
    assert report["rung_names"] == list(D.RUNG_NAMES)
    assert set(report["strategies"].keys()) == set(list_strategy_names(include_default=True))
    assert report["gates_summary"]["all_strategies_passed"] is True
    assert report["gates_summary"]["n_passed"] == 7

    for sname, st in report["strategies"].items():
        assert st["gates"]["passed_all"] is True, sname
        assert float(st["rungs"]["full_bayesian_solver"]["acc"]) >= 0.85
        assert float(st["gates"]["logs_only_acc"]) <= 0.10
        assert float(st["gates"]["do_nothing_max_abs_score"]) == 0.0
        assert float(st["gates"]["solver_score_ratio"]) >= 0.50
        assert st["regret_decomposition"]["identity_abs_error"] == 0.0
        for rname in ("fix_day1_canary_only", "fix_gather_hint_both", "full_bayesian_solver"):
            assert float(st["rungs"][rname]["day1_canary_rate"]) == 1.0
        for rname in ("fix_breakeven_abstain_only", "fix_gather_hint_both", "full_bayesian_solver"):
            assert float(st["rungs"][rname]["below_breakeven_gamble_rate"]) == 0.0

    pool = report["transcript_strategy_mean"]
    assert pool["n_strategies"] == 6
    assert pool["regret_decomposition"]["identity_abs_error"] == 0.0


def test_check_discipline_artifacts_catches_tampering(tmp_path: Path) -> None:
    ok_missing, msg_missing = D.check_discipline_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_missing is False
    assert "missing JSON" in msg_missing

    ok_oversize, msg_oversize = D.check_discipline_artifacts(
        json_path=JSON_PATH,
        md_path=MD_PATH,
        max_json_bytes=1024,
    )
    assert ok_oversize is False
    assert "bytes" in msg_oversize

    md_text = MD_PATH.read_text(encoding="utf-8")
    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = D.check_discipline_artifacts(json_path=JSON_PATH, md_path=drifted_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    dash_md = tmp_path / "dash.md"
    dash_md.write_text(md_text + "\n" + EM_DASH + "\n", encoding="utf-8")
    ok_dash, msg_dash = D.check_discipline_artifacts(json_path=JSON_PATH, md_path=dash_md)
    assert ok_dash is False
    assert "dash" in msg_dash

    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    flash_md = tmp_path / "flash.md"
    flash_md.write_text(md_text + f"\n{flash_tag}\n", encoding="utf-8")
    ok_flash, msg_flash = D.check_discipline_artifacts(json_path=JSON_PATH, md_path=flash_md)
    assert ok_flash is False
    assert flash_tag in msg_flash

    pct_md = tmp_path / "pct.md"
    pct_md.write_text(md_text + f"\n40{solver_pct_tag}\n", encoding="utf-8")
    ok_pct, msg_pct = D.check_discipline_artifacts(json_path=JSON_PATH, md_path=pct_md)
    assert ok_pct is False
    assert "solver" in msg_pct.lower()

    base = _load_committed_report()
    leaked = copy.deepcopy(base)
    leaked["strategies"]["default_v0"]["true_mole"] = "e01"
    leaked_json = tmp_path / "leaked.json"
    leaked_json.write_text(D.dumps_discipline_json(leaked) + "\n", encoding="utf-8")
    ok_leak, msg_leak = D.check_discipline_artifacts(json_path=leaked_json, md_path=MD_PATH)
    assert ok_leak is False
    assert "forbidden secret key" in msg_leak

    bad_seed = copy.deepcopy(base)
    bad_seed["seeds"][0] = 30000
    bad_seed_json = tmp_path / "bad_seed.json"
    bad_seed_json.write_text(D.dumps_discipline_json(bad_seed) + "\n", encoding="utf-8")
    ok_seed, msg_seed = D.check_discipline_artifacts(json_path=bad_seed_json, md_path=MD_PATH)
    assert ok_seed is False
    assert "seed hygiene" in msg_seed

    bad_decomp = copy.deepcopy(base)
    bad_decomp["strategies"]["default_v0"]["regret_decomposition"]["total_regret"]["mean"] = 0.999
    bad_decomp_json = tmp_path / "bad_decomp.json"
    bad_decomp_json.write_text(D.dumps_discipline_json(bad_decomp) + "\n", encoding="utf-8")
    ok_dec, msg_dec = D.check_discipline_artifacts(json_path=bad_decomp_json, md_path=MD_PATH)
    assert ok_dec is False
    assert "decomposition sum mismatch" in msg_dec


def test_single_seed_cli_end_to_end_smoke(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_json = tmp_path / "smoke.json"
    out_md = tmp_path / "smoke.md"
    rc = D.main([
        "--tier",
        "hard",
        "--seeds",
        "6400",
        "--strategies",
        "default_v0,frontier_synthesis_v14",
        "--workers",
        "1",
        "--n-boot",
        "32",
        "--out",
        str(out_json),
        "--report-md",
        str(out_md),
    ])
    summary_out = capsys.readouterr().out
    assert rc == 0
    assert "frontier_synthesis_v14" in summary_out

    ok, msg = D.check_discipline_artifacts(json_path=out_json, md_path=out_md)
    assert ok is True, msg


def test_pr_hygiene_zero_comments_dashes_and_forbidden_claims() -> None:
    coauthor_tag = "co-authored-" + "by"
    flash_tag = "gemini-3.5-" + "flash"
    solver_pct_tag = "% of " + "solver"
    forbidden_gap_re = re.compile(
        r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
        re.IGNORECASE,
    )

    for py_file in (MODULE_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected comment token in {py_file}"
        py_text = py_file.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"unexpected raw hash character in {py_file}"

    for p in (MODULE_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        text = p.read_text(encoding="utf-8")
        assert EM_DASH not in text, f"em-dash found in {p}"
        assert EN_DASH not in text, f"en-dash found in {p}"
        assert UNICODE_MINUS not in text, f"unicode minus found in {p}"
        assert text.isascii(), f"non-ASCII character found in {p}"
        assert coauthor_tag not in text.lower(), f"coauthor trailer found in {p}"

    for p in (JSON_PATH, MD_PATH):
        text = p.read_text(encoding="utf-8")
        low = text.lower()
        assert flash_tag not in low
        assert solver_pct_tag not in low
        assert forbidden_gap_re.search(text) is None
