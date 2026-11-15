"""Tests for scripts/verify_frontier_replication.py, replication_summary.json, and frontier_replication_v14.md."""
from __future__ import annotations

import copy
import importlib.util
import json
import math
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vfr = _load_script("verify_frontier_replication", SCRIPTS_DIR / "verify_frontier_replication.py")
paired_gemini = _load_script("paired_gemini", SCRIPTS_DIR / "paired_gemini.py")


@pytest.fixture(scope="module")
def computed_summary():
    return vfr.compute_summary(root=ROOT, verify_replays=True)


def test_approx_equal_float_tolerance():
    assert vfr.approx_equal({"x": [0.3223333333333333]}, {"x": [0.3223333333333339]}, tol=1e-9)
    assert not vfr.approx_equal({"x": [0.3223333]}, {"x": [0.3223349]}, tol=1e-9)
    assert not vfr.approx_equal({"flag": True}, {"flag": 1})
    assert not vfr.approx_equal({"v": None}, {"v": 0.0})
    assert vfr.approx_equal({"v": None}, {"v": None})
    assert vfr.approx_equal(float("nan"), float("nan"))


def test_committed_summary_and_report_pass_check(computed_summary, monkeypatch):
    monkeypatch.setattr(vfr, "compute_summary", lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary))
    rc = vfr.main(["--check"])
    assert rc == 0


def test_write_and_check_roundtrip_and_tamper_detection(computed_summary, monkeypatch, tmp_path):
    monkeypatch.setattr(vfr, "compute_summary", lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary))
    out_json = tmp_path / "replication_summary.json"
    out_md = tmp_path / "frontier_replication_v14.md"

    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data = json.loads(out_json.read_text(encoding="utf-8"))
    orig_mean = data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"]
    data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"] = orig_mean + 5e-11
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"] = orig_mean + 1e-6
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"] = orig_mean
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    md_orig = out_md.read_text(encoding="utf-8")
    out_md.write_text(md_orig + "\nextra tampered line\n", encoding="utf-8")
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1


def test_exact_parity_with_paired_gemini(computed_summary):
    import paired_v13

    paired_v13._P_CACHE.clear()
    pg_rows = paired_gemini.rows_for(ROOT / "data" / "runs" / "committed", "v1.4", "gemini-4-carbon", set(range(30)))
    if not vfr.gap_ships_flash_hard(ROOT):
        pg_rows = [r for r in pg_rows if r["agent"] != "opencode:google/gemini-3.5-flash"]
    our_rows = computed_summary["primary_v14_0_29"]["rows"]

    def _key(r):
        is_alt = "alternative (NOT the headline)" in r["label"]
        return (r["agent"], r["tier"], is_alt)

    our_by_key = {_key(r): r for r in our_rows}
    numeric_fields = (
        "n",
        "mean",
        "ci",
        "accuracy",
        "accused_rate",
        "p_accused",
        "n_p",
        "accuse_day",
        "solver_same_seeds",
        "ratio",
        "ratio_lo",
        "ratio_hi",
        "diff",
        "diff_ci",
        "post_expected",
        "post_expected_ratio",
        "post_expected_lo",
        "post_expected_hi",
        "solver_post_expected",
    )

    assert len(pg_rows) >= 13
    for pgr in pg_rows:
        k = _key(pgr)
        assert k in our_by_key, f"missing primary row {k}"
        ours = our_by_key[k]
        assert ours["label"] == pgr["label"]
        assert ours["seeds"] == pgr["seeds"]
        for fld in numeric_fields:
            pv = pgr[fld]
            ov = ours[fld]
            if isinstance(pv, float) and math.isnan(pv):
                assert ov is None
            else:
                assert math.isclose(float(ov), float(pv), rel_tol=1e-12, abs_tol=1e-12), f"mismatch on {k} {fld}"


def test_pre_registered_separation_and_cohorts(computed_summary):
    rule = computed_summary["pre_registered_rule"]
    assert rule["enforced"] is True
    assert rule["primary_seeds"] == list(range(30))
    assert {30, 34, 42, 45, 57}.issubset(set(rule["replication_carbon_hard_seeds"]))
    assert rule["primary_and_replication_disjoint"] is True
    assert rule["pooled_n35_classification"] == "secondary_sensitivity_only"

    rv = computed_summary["replay_verification"]
    assert rv["committed_v14"]["verified"] == 442
    assert rv["committed_v14"]["verified"] == rv["committed_v14"]["total"]
    assert rv["committed_v14"]["mismatches"] == 0
    assert rv["replication_v14"]["verified"] >= 305
    assert rv["replication_v14"]["verified"] == rv["replication_v14"]["total"]
    assert rv["replication_v14"]["mismatches"] == 0

    prim_rows = computed_summary["primary_v14_0_29"]["rows"]
    c_hard = next(
        r for r in prim_rows
        if r["agent"] == "opencode:google/gemini-4-carbon"
        and r["tier"] == "hard"
        and "alternative" not in r["label"]
    )
    assert c_hard["n"] == 30
    assert f"{c_hard['ratio']:.0%} [{c_hard['ratio_lo']:.0%}, {c_hard['ratio_hi']:.0%}]" == "65% [24%, 98%]"
    assert (
        f"{c_hard['post_expected_ratio']:.0%} [{c_hard['post_expected_lo']:.0%}, {c_hard['post_expected_hi']:.0%}]"
        == "72% [52%, 91%]"
    )

    ca = computed_summary["cohort_a_carbon_hard_replication"]
    assert {30, 34, 42, 45, 57}.issubset(set(ca["seeds"]))
    agents_5 = [r["agent"] for r in ca["paired_5_seeds_rows"]]
    assert agents_5[0] == "opencode:google/gemini-4-carbon"
    assert agents_5[1] == "solver"
    assert set(agents_5[2:]) == set(vfr.NON_SOLVER_BASELINES_30_59)
    assert len(ca["reference_30_59_rows"]) == 9
    assert all(r["n"] == 30 for r in ca["reference_30_59_rows"])

    cb = computed_summary["cohort_b_secondary_pooled_hard_n35"]
    assert cb["classification"] == "secondary_sensitivity_only"
    pooled_row = cb["rows"][0]
    assert pooled_row["n"] == 30 + len(ca["seeds"])
    assert "SECONDARY" in pooled_row["label"]
    assert pooled_row["post_expected_hi"] < 1.0

    cc = computed_summary["cohort_c_flash_and_cross_model"]
    flash_med = cc["flash_medium_n29_row"]
    assert flash_med["n"] == 30
    assert cc["flash_medium_missing_seeds_in_0_29"] == []
    assert cc["head_to_head_carbon_vs_flash"]["medium_n29"]["raw_diff"] > 0.0

    md = (ROOT / "docs" / "reports" / "frontier_replication_v14.md").read_text(encoding="utf-8")
    assert "SECONDARY SENSITIVITY ONLY" in md
    assert "post-hoc lock" in md
    assert "65% [24%, 98%]" in md
    assert "72% [52%, 91%]" in md

    if vfr.gap_ships_flash_hard(ROOT):
        assert cc["flash_hard_held_pending_gap_md"] is False
        assert cc["flash_hard_n30_row"]["n"] == 30
        assert cc["head_to_head_carbon_vs_flash"]["hard_n30"]["luck_adjusted_diff"] > 0.0
    else:
        assert cc["flash_hard_held_pending_gap_md"] is True
        assert cc["flash_hard_n30_row"] is None
        assert "hard_n30" not in cc["head_to_head_carbon_vs_flash"]
        for unapproved_tok in ("75% [36%, 123%]", "22% [-23%, 63%]", "0.373"):
            assert unapproved_tok not in md, f"unapproved flash hard token {unapproved_tok} in report before gap.md"


def test_file_hygiene_no_comments_or_em_dashes():
    py_files = [
        ROOT / "scripts" / "verify_frontier_replication.py",
        ROOT / "tests" / "test_frontier_replication.py",
    ]
    all_files = py_files + [
        ROOT / "docs" / "reports" / "frontier_replication_v14.md",
        ROOT / "results" / "frontier_replication" / "v1.4" / "replication_summary.json",
    ]
    for pf in py_files:
        with pf.open("rb") as fh:
            tokens = list(tokenize.tokenize(fh.readline))
        comments = [t for t in tokens if t.type == tokenize.COMMENT]
        assert not comments, f"found comments in {pf}: {comments}"
    for f in all_files:
        txt = f.read_text(encoding="utf-8")
        assert "\u2014" not in txt, f"found em dash in {f}"
        assert "\u2013" not in txt, f"found en dash in {f}"
