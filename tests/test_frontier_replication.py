"""Tests for scripts/verify_frontier_replication.py, replication_summary.json, and frontier_replication_v14.md."""
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


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def _make_gitless_root(tmp_path: Path, name: str = "gitless_root", gap_md_text: str | None = None) -> Path:
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
    if gap_md_text is None:
        os.symlink(
            ROOT / "docs" / "reports" / "gap.md",
            syn_root / "docs" / "reports" / "gap.md",
        )
    else:
        (syn_root / "docs" / "reports" / "gap.md").write_text(gap_md_text, encoding="utf-8")
    assert not (syn_root / ".git").exists()
    return syn_root


@pytest.fixture(scope="module")
def computed_summary():
    mp = pytest.MonkeyPatch()
    _forbid_subprocess(mp)
    env_before = dict(os.environ)
    try:
        out = vfr.compute_summary(root=ROOT, verify_replays=True)
    finally:
        mp.undo()
    assert dict(os.environ) == env_before
    return out


def test_approx_equal_float_tolerance():
    assert vfr.approx_equal({"x": [0.3223333333333333]}, {"x": [0.3223333333333339]}, tol=1e-9)
    assert not vfr.approx_equal({"x": [0.3223333]}, {"x": [0.3223349]}, tol=1e-9)
    assert not vfr.approx_equal({"flag": True}, {"flag": 1})
    assert not vfr.approx_equal({"v": None}, {"v": 0.0})
    assert vfr.approx_equal({"v": None}, {"v": None})
    assert vfr.approx_equal(float("nan"), float("nan"))


def test_committed_summary_and_report_pass_check(computed_summary, monkeypatch, capsys):
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(vfr, "compute_summary", lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary))
    rc = vfr.main(["--check"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "committed=472/472" in out
    assert "replication=305/305" in out
    assert "union_n=6" in out
    assert "pooled_n36=36" in out
    assert vfr.DEFAULT_JSON.stat().st_size <= vfr.MAX_JSON_BYTES
    assert vfr.DEFAULT_JSON.read_bytes() == vfr.serialize_summary_json(computed_summary).encode("utf-8")
    assert vfr.DEFAULT_MD.read_bytes() == vfr.render_markdown(computed_summary).encode("utf-8")


def test_write_and_check_roundtrip_and_tamper_detection(computed_summary, monkeypatch, tmp_path, capsys):
    _forbid_subprocess(monkeypatch)
    monkeypatch.setattr(vfr, "compute_summary", lambda root=ROOT, verify_replays=True: copy.deepcopy(computed_summary))
    out_json = tmp_path / "replication_summary.json"
    out_md = tmp_path / "frontier_replication_v14.md"

    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md)]) == 0
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--write"]) == 0
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    capsys.readouterr()
    assert vfr.main(["--stdout"]) == 0
    stdout_md = capsys.readouterr().out
    assert stdout_md == out_md.read_text(encoding="utf-8")

    data = json.loads(out_json.read_text(encoding="utf-8"))
    orig_mean = data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"]
    data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"] = orig_mean + 5e-11
    out_json.write_text(vfr.serialize_summary_json(data), encoding="utf-8")
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 0

    data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"] = orig_mean + 1e-5
    out_json.write_text(vfr.serialize_summary_json(data), encoding="utf-8")
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    data["cohort_a_carbon_hard_replication"]["paired_5_seeds_rows"][0]["mean"] = orig_mean
    out_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert out_json.stat().st_size > vfr.MAX_JSON_BYTES
    assert vfr.main(["--out-json", str(out_json), "--out-md", str(out_md), "--check"]) == 1

    out_json.write_text(vfr.serialize_summary_json(data), encoding="utf-8")
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

    paired_v13._P_CACHE.clear()
    pg_rows_60 = paired_gemini.rows_for(ROOT / "data" / "runs" / "committed", "v1.4", "gemini-4-carbon", set(range(60)))
    pg_60_by_label = {(r["label"], r["tier"]): r for r in pg_rows_60}

    ext_label = ("OpenCode + gemini-4-carbon over MCP, extension (seeds 30-59)", "hard")
    pool_label = ("OpenCode + gemini-4-carbon over MCP, pooled (primary + extension)", "hard")
    assert ext_label in pg_60_by_label
    assert pool_label in pg_60_by_label

    our_g1 = computed_summary["g1_committed_ext_hard_n2"]["rows"][0]
    our_pool32 = computed_summary["secondary_pooled_hard_reconciliation"]["n32_primary_plus_g1"]["rows"][0]
    for ours, pgr in ((our_g1, pg_60_by_label[ext_label]), (our_pool32, pg_60_by_label[pool_label])):
        assert ours["seeds"] == pgr["seeds"]
        for fld in numeric_fields:
            pv = pgr[fld]
            ov = ours[fld]
            assert math.isclose(float(ov), float(pv), rel_tol=1e-12, abs_tol=1e-12), f"mismatch on {ours['label']} {fld}"


def test_pre_registered_separation_g1_fr8_n6_union_and_n36_pool(computed_summary):
    assert computed_summary["schema_version"] == "v1.4-frontier-replication-2"
    assert computed_summary["zero_live_api_calls"] is True
    assert computed_summary["zero_git_dependency"] is True

    rule = computed_summary["pre_registered_rule"]
    assert rule["enforced"] is True
    assert rule["primary_seeds"] == list(range(30))
    assert rule["primary_lock_classification"] == "post_hoc_lock"
    assert rule["primary_episodes_commit"] == "8fd4dec"
    assert rule["primary_lock_commit"] == "671ed96"
    assert rule["primary_lock_delay_s"] == 28
    assert rule["g1_extension_classification"] == "pre_registered"
    assert rule["g1_prereg_commit"] == "f9fb7a4a"
    assert rule["g1_carbon_ext_hard_seeds"] == [34, 37]
    assert rule["gpt_5_5_classification"] == "pre_registered"
    assert rule["gpt_5_5_prereg_commit"] == "cf394894"
    assert rule["replication_carbon_hard_seeds"] == [30, 34, 42, 45, 57]
    assert rule["union_dedup_hard_seeds"] == [30, 34, 37, 42, 45, 57]
    assert rule["shared_extension_seeds"] == [34]
    assert rule["primary_and_replication_disjoint"] is True
    assert rule["pooled_n32_classification"] == "secondary_sensitivity_only"
    assert rule["pooled_n35_classification"] == "secondary_sensitivity_only"
    assert rule["pooled_n36_classification"] == "secondary_sensitivity_only"

    rv = computed_summary["replay_verification"]
    assert rv["step_error_detail_1bc3e281_compat"] is True
    assert rv["committed_v14"]["verified"] == 472
    assert rv["committed_v14"]["verified"] == rv["committed_v14"]["total"]
    assert rv["committed_v14"]["mismatches"] == 0
    assert rv["committed_v14"]["duplicates"] == 0
    assert rv["committed_v14"]["pre_1bc3e281_error_steps"] == 521
    assert rv["replication_v14"]["verified"] == 305
    assert rv["replication_v14"]["verified"] == rv["replication_v14"]["total"]
    assert rv["replication_v14"]["mismatches"] == 0
    assert rv["replication_v14"]["duplicates"] == 0
    assert rv["replication_v14"]["pre_1bc3e281_error_steps"] == 348

    sp = computed_summary["solver_30_59_parity"]
    assert sp["exact_parity"] is True
    assert sp["n"] == 30
    assert sp["matched"] == 30
    assert sp["mismatches"] == 0

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

    g1 = computed_summary["g1_committed_ext_hard_n2"]
    assert g1["seeds"] == [34, 37]
    assert len(g1["pending_seeds_in_30_59"]) == 28
    g1_c = g1["rows"][0]
    assert g1_c["n"] == 2
    assert f"{g1_c['ratio']:.0%} [{g1_c['ratio_lo']:.0%}, {g1_c['ratio_hi']:.0%}]" == "101% [91%, 113%]"
    assert f"{g1_c['post_expected_ratio']:.0%} [{g1_c['post_expected_lo']:.0%}, {g1_c['post_expected_hi']:.0%}]" == "109% [105%, 114%]"

    ca = computed_summary["cohort_a_carbon_hard_replication"]
    assert ca["seeds"] == [30, 34, 42, 45, 57]
    agents_5 = [r["agent"] for r in ca["paired_5_seeds_rows"]]
    assert agents_5[0] == "opencode:google/gemini-4-carbon"
    assert agents_5[1] == "solver"
    assert set(agents_5[2:]) == set(vfr.NON_SOLVER_BASELINES_30_59)
    assert len(ca["reference_30_59_rows"]) == 9
    assert all(r["n"] == 30 for r in ca["reference_30_59_rows"])

    u6 = computed_summary["union_dedup_hard_n6"]
    assert u6["seeds"] == [30, 34, 37, 42, 45, 57]
    assert u6["g1_only_seeds"] == [37]
    assert u6["fr8_only_seeds"] == [30, 42, 45, 57]
    assert u6["shared_seeds"] == [34]
    assert u6["dropped_duplicate_episodes"] == 1
    assert len(u6["pending_seeds_in_30_59"]) == 24
    s34 = u6["shared_seed_comparisons"][0]
    assert s34["seed"] == 34
    assert s34["selected_source"] == "committed_g1"
    assert s34["committed_g1"]["score"] == 0.79
    assert s34["fr8_replication"]["score"] == 0.82
    assert s34["solver"]["score"] == 0.70
    assert s34["committed_g1"]["accused"] == s34["fr8_replication"]["accused"] == s34["solver"]["accused"] == "e29"
    assert u6["rows"][0]["n"] == 6
    assert u6["rows"][1]["n"] == 6
    assert u6["rows"][0]["post_expected"] > u6["rows"][1]["post_expected"]

    cb = computed_summary["cohort_b_secondary_pooled_hard_n35"]
    assert cb["classification"] == "secondary_sensitivity_only"
    assert cb["rows"][0]["n"] == 35
    assert cb["rows"][0]["post_expected_hi"] < 1.0

    sp_rec = computed_summary["secondary_pooled_hard_reconciliation"]
    assert sp_rec["classification"] == "secondary_sensitivity_only"
    assert sp_rec["primary_headline_n"] == 30
    assert sp_rec["no_duplicate_seeds_verified"] is True
    assert sp_rec["all_luck_adjusted_95ci_exclude_parity"] is True

    p32 = sp_rec["n32_primary_plus_g1"]
    assert p32["seeds"] == list(range(30)) + [34, 37]
    assert len(p32["seeds"]) == len(set(p32["seeds"])) == 32
    assert f"{p32['rows'][0]['ratio']:.0%} [{p32['rows'][0]['ratio_lo']:.0%}, {p32['rows'][0]['ratio_hi']:.0%}]" == "68% [32%, 100%]"
    assert f"{p32['rows'][0]['post_expected_ratio']:.0%} [{p32['rows'][0]['post_expected_lo']:.0%}, {p32['rows'][0]['post_expected_hi']:.0%}]" == "75% [56%, 93%]"
    assert p32["rows"][0]["post_expected_hi"] < 1.0

    p36 = sp_rec["n36_primary_plus_union6"]
    assert p36["seeds"] == list(range(30)) + [30, 34, 37, 42, 45, 57]
    assert len(p36["seeds"]) == len(set(p36["seeds"])) == 36
    assert p36["rows"][0]["n"] == 36
    assert "SECONDARY" in p36["rows"][0]["label"]
    assert f"{p36['rows'][0]['post_expected_ratio']:.0%} [{p36['rows'][0]['post_expected_lo']:.0%}, {p36['rows'][0]['post_expected_hi']:.0%}]" == "81% [62%, 99%]"
    assert p36["rows"][0]["post_expected_hi"] < 1.0
    assert p36["rows"][1]["n"] == 36
    assert p36["rows"][1]["post_expected_hi"] < 1.0

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
    assert "30, 34, 37, 42, 45, 57" in md
    assert "81% [62%, 99%]" in md

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


def test_duplicate_seed_guards_and_gitless_flash_gate_toggle(monkeypatch, tmp_path):
    _forbid_subprocess(monkeypatch)
    ep34 = {"tier": "hard", "seed": 34, "agent": "opencode:google/gemini-4-carbon", "score": 0.79, "correct": True, "accused": "e29", "final_day": 5, "steps": []}
    with pytest.raises(ValueError, match="overlapping seeds"):
        vfr.pool_disjoint_episodes([dict(ep34, seed=5), ep34], [ep34], "bad_pool")
    with pytest.raises(ValueError, match="duplicate seeds inside G1"):
        vfr.dedup_extension_union([ep34, ep34], [], {})

    gitless_shipped = _make_gitless_root(
        tmp_path,
        name="gitless_flash_shipped",
        gap_md_text="gemini-3.5-flash shipped on hard\n",
    )
    assert vfr.gap_ships_flash_hard(gitless_shipped) is True
    shipped_summary = vfr.compute_summary(root=gitless_shipped, verify_replays=False)
    assert shipped_summary["cohort_c_flash_and_cross_model"]["flash_hard_held_pending_gap_md"] is False
    assert shipped_summary["cohort_c_flash_and_cross_model"]["flash_hard_n30_row"]["n"] == 30
    assert "hard_n30" in shipped_summary["cohort_c_flash_and_cross_model"]["head_to_head_carbon_vs_flash"]
    shipped_md = vfr.render_markdown(shipped_summary)
    assert "75% [36%, 123%]" in shipped_md
    assert len(vfr.serialize_summary_json(shipped_summary).encode("utf-8")) <= vfr.MAX_JSON_BYTES


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
