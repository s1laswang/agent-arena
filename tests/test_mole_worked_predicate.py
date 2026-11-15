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

from canary.baselines import DoNothing
from canary.mole import worked_predicate as WP

MODULE_PATH = ROOT / "canary" / "mole" / "worked_predicate.py"
JSON_PATH = ROOT / "results" / "mole_strategies" / "worked_predicate_v14.json"
MD_PATH = ROOT / "docs" / "reports" / "mole_worked_predicate_v14.md"
TEST_PATH = Path(__file__).resolve()

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
HASH_CHAR = chr(35)
COAUTHOR_TAG = "co-authored-" + "by"
FLASH_TAG = "gemini-3.5-" + "flash"
SOLVER_PCT_TAG = "% of " + "solver"
FORBIDDEN_GAP_RE = re.compile(
    r"(?:%\s+of\s+(?:the\s+)?solver|(?:score|frontier|luck-adj\.?)\s*/\s*solver)",
    re.IGNORECASE,
)


def _collect_keys(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _collect_keys(v, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_keys(item, out)


def test_committed_artifacts_size_schema_and_report_parity(capsys: pytest.CaptureFixture[str]) -> None:
    assert JSON_PATH.is_file()
    assert MD_PATH.is_file()
    assert JSON_PATH.stat().st_size < 95_000

    ok, msg = WP.check_worked_predicate_artifacts(json_path=JSON_PATH, md_path=MD_PATH)
    assert ok is True, msg
    assert "OK:" in msg

    rc = WP.main(["--check", "--out", str(JSON_PATH), "--report-md", str(MD_PATH)])
    captured = capsys.readouterr()
    assert rc == 0
    assert "OK:" in captured.out

    raw_json = JSON_PATH.read_text(encoding="utf-8")
    payload = json.loads(raw_json)
    assert WP.dumps_compact_json(payload) + "\n" == raw_json
    assert WP.format_worked_markdown_report(payload) == MD_PATH.read_text(encoding="utf-8")

    assert payload["schema_version"] == "worked_predicate_v14.1"
    assert payload["tiers_version"] == "v1.4"
    assert payload["api_calls"] == 0
    assert payload["tier"] == "hard"
    assert payload["seed_range"] == "6240-6279"
    assert payload["n_live_seeds"] == 40
    assert payload["live_seeds"] == list(range(6240, 6280))
    assert payload["n_cf_transcripts"] == 60
    assert payload["n_cf_seeds_per_source"] == 30
    assert payload["cf_sources"] == ["opencode", "inproc"]
    assert payload["cf_solver_unwinnable_seeds"] == [15]
    assert payload["n_strategies_evaluated"] == 11
    assert payload["n_unique_canonical_strategies"] == 9

    sg = payload["summary_gates"]
    assert sg["all_strategies_passed"] is True
    assert sg["anti_unfairness_invariant_all_ok"] is True
    assert float(sg["min_solver_acc_observed"]) >= 0.80
    assert float(sg["max_logs_only_acc_observed"]) <= 0.10
    assert int(sg["total_live_suppressed_unwinnable_credits"]) > 0
    assert int(sg["total_cf_suppressed_unwinnable_credits"]) > 0

    strats = payload["strategies"]
    assert strats["default_v0"]["counterfactual"]["cf_worked_rate"]["mean"] == 0.0
    assert strats["hof_v14_rank3"]["canonical_duplicate_of"] == "surgical_trap_shield"
    assert strats["hof_v14_rank4"]["canonical_duplicate_of"] == "early_burst_midgame_pace"
    for sname, st in strats.items():
        assert st["gates"]["passed_all"] is True, sname
        assert st["gates"]["anti_unfairness_invariant_ok"] is True, sname
        unwin = {int(u["seed"]) for u in st["live"]["winnable"]["unwinnable_seeds"]}
        for ik, irow in st["live"]["per_investigator"].items():
            assert unwin.isdisjoint(int(s) for s in irow["worked_seeds"]), f"{sname}/{ik}"
        for cf_key in st["counterfactual"]["cf_worked_keys"]:
            assert not str(cf_key).endswith(":15"), f"{sname}:{cf_key}"

    all_keys: set[str] = set()
    _collect_keys(payload, all_keys)
    for bad in ("mole", "true_mole", "mole_id", "secret_mole", "canary_ids", "posterior"):
        assert bad not in all_keys


def test_check_artifacts_catches_tampering_and_invariant_violations(tmp_path: Path) -> None:
    ok_miss_j, msg_miss_j = WP.check_worked_predicate_artifacts(
        json_path=tmp_path / "missing.json",
        md_path=MD_PATH,
    )
    assert ok_miss_j is False
    assert "missing JSON" in msg_miss_j

    ok_miss_m, msg_miss_m = WP.check_worked_predicate_artifacts(
        json_path=JSON_PATH,
        md_path=tmp_path / "missing.md",
    )
    assert ok_miss_m is False
    assert "missing Markdown" in msg_miss_m

    md_text = MD_PATH.read_text(encoding="utf-8")
    drifted_md = tmp_path / "drifted.md"
    drifted_md.write_text(md_text + "\nextra drifted line\n", encoding="utf-8")
    ok_drift, msg_drift = WP.check_worked_predicate_artifacts(json_path=JSON_PATH, md_path=drifted_md)
    assert ok_drift is False
    assert "does not match" in msg_drift

    for idx, bad_fragment in enumerate(
        (
            EM_DASH,
            EN_DASH,
            UNICODE_MINUS,
            FLASH_TAG,
            f"42{SOLVER_PCT_TAG}",
            "score / solver",
            f"{COAUTHOR_TAG}: Someone",
        )
    ):
        bad_md = tmp_path / f"bad_{idx}.md"
        bad_md.write_text(md_text + f"\n{bad_fragment}\n", encoding="utf-8")
        ok_bad, _ = WP.check_worked_predicate_artifacts(json_path=JSON_PATH, md_path=bad_md)
        assert ok_bad is False

    base = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    leaked_key = copy.deepcopy(base)
    leaked_key["strategies"]["default_v0"]["true_mole"] = "alice"
    leaked_key_p = tmp_path / "leaked_key.json"
    leaked_key_p.write_text(WP.dumps_compact_json(leaked_key) + "\n", encoding="utf-8")
    ok_lk, msg_lk = WP.check_worked_predicate_artifacts(json_path=leaked_key_p, md_path=MD_PATH)
    assert ok_lk is False
    assert "forbidden secret key" in msg_lk

    leaked_emp = copy.deepcopy(base)
    leaked_emp["note"] = "suspect e04"
    leaked_emp_p = tmp_path / "leaked_emp.json"
    leaked_emp_p.write_text(WP.dumps_compact_json(leaked_emp) + "\n", encoding="utf-8")
    ok_le, msg_le = WP.check_worked_predicate_artifacts(json_path=leaked_emp_p, md_path=MD_PATH)
    assert ok_le is False
    assert "employee/mole ID" in msg_le

    bad_seed = copy.deepcopy(base)
    bad_seed["live_seeds"][0] = 30000
    bad_seed_p = tmp_path / "bad_seed.json"
    bad_seed_p.write_text(WP.dumps_compact_json(bad_seed) + "\n", encoding="utf-8")
    ok_bs, msg_bs = WP.check_worked_predicate_artifacts(json_path=bad_seed_p, md_path=MD_PATH)
    assert ok_bs is False
    assert "seed hygiene" in msg_bs

    bad_live_inv = copy.deepcopy(base)
    unwin_seed = int(bad_live_inv["strategies"]["default_v0"]["live"]["winnable"]["unwinnable_seeds"][0]["seed"])
    bad_live_inv["strategies"]["default_v0"]["live"]["per_investigator"]["gemini_carbon_proxy"]["worked_seeds"].append(
        unwin_seed
    )
    bad_live_p = tmp_path / "bad_live_inv.json"
    bad_live_p.write_text(WP.dumps_compact_json(bad_live_inv) + "\n", encoding="utf-8")
    ok_li, msg_li = WP.check_worked_predicate_artifacts(json_path=bad_live_p, md_path=MD_PATH)
    assert ok_li is False
    assert "anti-unfairness invariant violated" in msg_li

    bad_cf_inv = copy.deepcopy(base)
    bad_cf_inv["strategies"]["surgical_trap_shield"]["counterfactual"]["cf_worked_keys"].append("opencode:15")
    bad_cf_p = tmp_path / "bad_cf_inv.json"
    bad_cf_p.write_text(WP.dumps_compact_json(bad_cf_inv) + "\n", encoding="utf-8")
    ok_ci, msg_ci = WP.check_worked_predicate_artifacts(json_path=bad_cf_p, md_path=MD_PATH)
    assert ok_ci is False
    assert "counterfactual anti-unfairness violated" in msg_ci


@pytest.mark.parametrize(
    "bad_seeds",
    [
        "",
        "6240,",
        "-1",
        "0",
        "15",
        "59",
        "0-59",
        "55-62",
        "30000",
        "30199",
        "30000-30199",
        "800000",
        "900000",
        "6240,6240",
        "6245-6241",
        "6245:6245",
    ],
)
def test_seed_hygiene_rejects_invalid_and_reserved_seeds(bad_seeds: str) -> None:
    with pytest.raises(ValueError):
        WP.validate_eval_seeds(bad_seeds, enforce_hygiene=True)


def test_seed_hygiene_accepts_clean_ranges_and_breakeven_math() -> None:
    assert WP.validate_eval_seeds("60,29999,30200,799999") == [60, 29999, 30200, 799999]
    assert WP.validate_eval_seeds("6240:6243") == [6240, 6241, 6242]
    assert WP.validate_eval_seeds("0-2", enforce_hygiene=False) == [0, 1, 2]
    with pytest.raises(ValueError):
        WP.validate_eval_seeds([True])

    assert WP.breakeven_posterior(1.0) == pytest.approx(0.5)
    assert WP.breakeven_posterior(0.0) == pytest.approx(1.0)
    assert WP.breakeven_posterior(0.6) == pytest.approx(1.0 / 1.6)
    with pytest.raises(ValueError):
        WP.breakeven_posterior(0.5, wrong_accusation_score=0.0)
    with pytest.raises(ValueError):
        WP.breakeven_posterior(-0.1)

    c1 = WP.paired_bootstrap_ci([0.2, 0.4, 0.8], n_boot=64, tag="det")
    c2 = WP.paired_bootstrap_ci([0.2, 0.4, 0.8], n_boot=64, tag="det")
    assert c1 == c2
    assert c1["ci_low"] <= c1["mean"] <= c1["ci_high"]
    assert WP.paired_bootstrap_ci([], n_boot=16)["n"] == 0
    assert WP.paired_bootstrap_ci([0.5, 0.5], n_boot=16)["ci_half_width"] == 0.0
    with pytest.raises(ValueError):
        WP.paired_bootstrap_ci([0.5], n_boot=0)
    with pytest.raises(ValueError):
        WP.paired_bootstrap_ci([0.5], ci=1.0)


def test_catalog_coercion_and_live_anti_unfairness_invariant() -> None:
    cat = WP.build_candidate_catalog()
    assert len(cat) == 11
    assert cat["hof_v14_rank3"].hof_alias == "surgical_trap_shield"
    assert cat["hof_v14_rank4"].hof_alias == "early_burst_midgame_pace"

    assert WP.coerce_mole_strategy(None).name == "default_v0"
    assert WP.coerce_mole_strategy("window_crowd_stale").name == "hof_v14_rank1"
    assert WP.coerce_mole_strategy("surgical_trap_shield").name == "surgical_trap_shield"
    with pytest.raises(KeyError):
        WP.coerce_mole_strategy("nonexistent_mole_strategy")
    with pytest.raises(TypeError):
        WP.coerce_mole_strategy(12345)

    win_res = WP.check_seed_winnable("medium", 6240, "surgical_trap_shield")
    assert win_res["winnable"] is True
    assert win_res["solver_win"] is True
    assert win_res["shortcuts_fail"] is True

    worked_live = WP.check_strategy_worked_live(
        tier="medium",
        seed=6240,
        strategy="surgical_trap_shield",
        investigator_fn=DoNothing,
        winnable_result=win_res,
    )
    assert worked_live["winnable"] is True
    assert worked_live["raw_investigator_beaten"] is True
    assert worked_live["worked"] is True
    assert worked_live["suppressed_unwinnable_credit"] is False
    assert worked_live["anti_unfairness_invariant_ok"] is True

    unwin_override = copy.deepcopy(win_res)
    unwin_override["winnable"] = False
    unwin_override["unwinnable_reasons"] = ["solver_not_correct"]
    suppressed_live = WP.check_strategy_worked_live(
        tier="medium",
        seed=6240,
        strategy="surgical_trap_shield",
        investigator_fn=DoNothing,
        winnable_result=unwin_override,
    )
    assert suppressed_live["winnable"] is False
    assert suppressed_live["raw_investigator_beaten"] is True
    assert suppressed_live["worked"] is False
    assert suppressed_live["suppressed_unwinnable_credit"] is True
    assert suppressed_live["anti_unfairness_invariant_ok"] is True


def test_counterfactual_anti_unfairness_and_mini_cli_end_to_end(tmp_path: Path) -> None:
    base_ep = {"known_V": 0.6, "p_true_mole": 0.90, "optimal_ev": 0.44, "accuse_day": 10, "recorded_correct": True, "recorded_score": 0.6, "surfaced_canaries": 2}
    degraded_ep = {"known_V": 0.6, "p_true_mole": 0.30, "optimal_ev": -0.52, "accuse_day": 10, "recorded_correct": True, "recorded_score": 0.6, "surfaced_canaries": 0}

    row_win = WP._evaluate_cf_pair_row(
        source="opencode",
        seed=0,
        strat_ep=degraded_ep,
        base_ep=base_ep,
        solver_ep={"correct": True, "score": 0.72},
        ev_drop_threshold=0.20,
        wrong_score=-1.0,
    )
    assert row_win["cf_winnable"] is True
    assert row_win["raw_cf_degraded"] is True
    assert row_win["cf_worked"] is True
    assert row_win["dropped_below_breakeven"] is True
    assert row_win["suppressed_unwinnable_credit"] is False

    row_unwin = WP._evaluate_cf_pair_row(
        source="opencode",
        seed=15,
        strat_ep=degraded_ep,
        base_ep=base_ep,
        solver_ep={"correct": False, "score": -1.0},
        ev_drop_threshold=0.20,
        wrong_score=-1.0,
    )
    assert row_unwin["cf_winnable"] is False
    assert row_unwin["raw_cf_degraded"] is True
    assert row_unwin["cf_worked"] is False
    assert row_unwin["suppressed_unwinnable_credit"] is True
    assert row_unwin["anti_unfairness_invariant_ok"] is True

    out_json = tmp_path / "mini_worked.json"
    out_md = tmp_path / "mini_worked.md"
    rc = WP.main(
        [
            "--tier",
            "medium",
            "--seeds",
            "6240",
            "--cf-seeds",
            "0",
            "--cf-sources",
            "opencode",
            "--strategies",
            "default_v0,surgical_trap_shield",
            "--workers",
            "1",
            "--n-boot",
            "16",
            "--min-solver-acc",
            "0.0",
            "--min-solver-ratio",
            "0.0",
            "--out",
            str(out_json),
            "--report-md",
            str(out_md),
        ]
    )
    assert rc == 0
    ok_mini, msg_mini = WP.check_worked_predicate_artifacts(json_path=out_json, md_path=out_md)
    assert ok_mini is True, msg_mini


def test_pr42_hygiene_zero_comments_dashes_and_forbidden_claims() -> None:
    for py_file in (MODULE_PATH, TEST_PATH):
        with py_file.open("rb") as fh:
            comments = [tok for tok in tokenize.tokenize(fh.readline) if tok.type == tokenize.COMMENT]
        assert comments == [], f"comment token found in {py_file}"
        py_text = py_file.read_text(encoding="utf-8")
        assert HASH_CHAR not in py_text, f"raw hash character found in {py_file}"

    for p in (MODULE_PATH, TEST_PATH, JSON_PATH, MD_PATH):
        txt = p.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em-dash in {p}"
        assert EN_DASH not in txt, f"en-dash in {p}"
        assert UNICODE_MINUS not in txt, f"unicode-minus in {p}"
        assert txt.isascii(), f"non-ASCII character in {p}"
        assert COAUTHOR_TAG not in txt.lower(), f"coauthor trailer in {p}"

    for p in (JSON_PATH, MD_PATH):
        txt = p.read_text(encoding="utf-8")
        low = txt.lower()
        assert FLASH_TAG not in low
        assert SOLVER_PCT_TAG not in low
        assert FORBIDDEN_GAP_RE.search(txt) is None
