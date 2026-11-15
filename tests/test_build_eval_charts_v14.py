"""Tests for deterministic v1.4 paired gap and posterior calibration chart builder."""

from __future__ import annotations

import ast
import copy
import importlib.util
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.analysis.gap import mean_ci
SCRIPT_PATH = ROOT / "scripts" / "build_eval_charts_v14.py"
OUT_DIR = ROOT / "results" / "eval_v14"
HEADLINE_TABLE_JSON = OUT_DIR / "headline_gap_table_v14.json"
PAIRED_DIAG_JSON = OUT_DIR / "paired_seed_diagnostics_v14.json"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"
THIS_TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
CO_AUTHORED = "Co-Authored-" + "By"


def _load_charts_module():
    spec = importlib.util.spec_from_file_location("build_eval_charts_v14", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


charts = _load_charts_module()


def _build_committed_chart_data() -> dict[str, Any]:
    hgt = json.loads(HEADLINE_TABLE_JSON.read_text(encoding="utf-8"))
    psd = json.loads(PAIRED_DIAG_JSON.read_text(encoding="utf-8"))
    sec_a = {
        (row["agent"], row["tier"]): row
        for row in hgt["section_a"]
        if row.get("kind") != "sensitivity"
    }

    psd_hard_ps = psd["tiers"]["hard"]["per_seed"]
    s_hard_raw = [float(x) for x in psd_hard_ps["solver"]["score"]]
    s_hard_la = [float(x) for x in psd_hard_ps["solver"]["la"]]

    forest: dict[str, list[dict[str, Any]]] = {"hard": [], "medium": []}
    for tier in ("hard", "medium"):
        for spec in charts.FOREST_SPECS:
            key = spec["key"]
            if tier not in spec["tiers"]:
                forest[tier].append(
                    {
                        "key": key,
                        "display": spec["display"],
                        "sublabel": spec["sublabel"],
                        "source": spec["source"],
                        "available": False,
                        "tier": tier,
                    }
                )
                continue
            r = sec_a[(spec["agent"], tier)]
            boot_seed = (
                charts.COMMITTED_BOOT_SEED
                if spec["source"] == "committed"
                else charts.BASELINE_BOOT_SEED
            )
            if key == "solver":
                raw_rat, raw_lo, raw_hi = 1.0, 1.0, 1.0
                la_rat, la_lo, la_hi = 1.0, 1.0, 1.0
                raw_lbl, la_lbl = "100% (ref)", "100% (ref)"
            elif key in ("do_nothing", "stop_early"):
                raw_rat, raw_lo, raw_hi = 0.0, 0.0, 0.0
                la_rat, la_lo, la_hi = 0.0, 0.0, 0.0
                raw_lbl, la_lbl = "0% [0%, 0%]", "0% [0%, 0%]"
            elif tier == "hard" and key in psd_hard_ps:
                f_ps = psd_hard_ps[key]
                f_raw = [float(x) for x in f_ps["score"]]
                f_la = [float(x) for x in f_ps["la"]]
                raw_rat = (sum(f_raw) / len(f_raw)) / (sum(s_hard_raw) / len(s_hard_raw))
                la_rat = (sum(f_la) / len(f_la)) / (sum(s_hard_la) / len(s_hard_la))
                raw_lo, raw_hi = charts.fast_boot_ratio(
                    f_raw,
                    s_hard_raw,
                    b_resamples=charts.BOOTSTRAP_RESAMPLES,
                    rng_seed=boot_seed,
                )
                la_lo, la_hi = charts.fast_boot_ratio(
                    f_la,
                    s_hard_la,
                    b_resamples=charts.BOOTSTRAP_RESAMPLES,
                    rng_seed=boot_seed,
                )
                raw_lbl = charts.fmt_pct_ci(raw_rat, raw_lo, raw_hi)
                la_lbl = charts.fmt_pct_ci(la_rat, la_lo, la_hi)
            else:
                raw_rat = float(r["ratio"])
                raw_lo, raw_hi = float(r["ratio_lo"]), float(r["ratio_hi"])
                la_rat = float(r["luck_adj_ratio"])
                la_lo, la_hi = float(r["luck_adj_lo"]), float(r["luck_adj_hi"])
                raw_lbl = charts.fmt_pct_ci(raw_rat, raw_lo, raw_hi)
                la_lbl = charts.fmt_pct_ci(la_rat, la_lo, la_hi)

            forest[tier].append(
                {
                    "key": key,
                    "display": spec["display"],
                    "sublabel": spec["sublabel"],
                    "source": spec["source"],
                    "available": True,
                    "tier": tier,
                    "n": int(r["n"]),
                    "boot_seed": boot_seed,
                    "raw_mean": round(float(r["mean"]), 12),
                    "raw_ci": round(float(r["score_ci"]), 12),
                    "la_mean": round(float(r["luck_adjusted_score"]), 12),
                    "la_ci": round(float(r["score_ci"]), 12),
                    "raw_ratio": round(raw_rat, 12),
                    "raw_lo": round(raw_lo, 12),
                    "raw_hi": round(raw_hi, 12),
                    "la_ratio": round(la_rat, 12),
                    "la_lo": round(la_lo, 12),
                    "la_hi": round(la_hi, 12),
                    "raw_label": raw_lbl,
                    "la_label": la_lbl,
                }
            )

    spec_by_key = {s["key"]: s for s in charts.FOREST_SPECS}
    cal: dict[str, dict[str, Any]] = {}
    for key in charts.CALIBRATION_KEYS:
        ps = psd_hard_ps[key]
        raw_seq = [float(x) for x in ps["score"]]
        ev_seq: list[float] = []
        accusations: list[dict[str, Any]] = []
        abstentions: list[dict[str, Any]] = []
        cum_raw: list[float] = []
        cum_ev: list[float] = []
        run_r = 0.0
        run_e = 0.0
        for s in range(30):
            sc_val = raw_seq[s]
            v_val = float(ps["true_v"][s])
            if ps["accused"][s]:
                p_val = float(ps["p_accused"][s])
                ev_val = p_val * v_val - (1.0 - p_val)
                p_be = 1.0 / (1.0 + v_val)
                accusations.append(
                    {
                        "seed": s,
                        "accused": "emp",
                        "correct": bool(ps["correct"][s]),
                        "v": round(v_val, 12),
                        "p": round(p_val, 12),
                        "p_breakeven": round(p_be, 12),
                        "ev": round(ev_val, 12),
                        "score": round(sc_val, 12),
                        "sub_breakeven": bool(p_val < p_be),
                    }
                )
            else:
                ev_val = 0.0
                abstentions.append({"seed": s, "v": round(v_val, 12)})
            ev_seq.append(ev_val)
            run_r += sc_val
            run_e += ev_val
            cum_raw.append(round(run_r, 12))
            cum_ev.append(round(run_e, 12))

        raw_mean, raw_ci = mean_ci(raw_seq)
        ev_mean, ev_ci = mean_ci(ev_seq)
        sub_be = [a for a in accusations if a["sub_breakeven"]]
        ci_shrink = (1.0 - (ev_ci / raw_ci)) if raw_ci > 0.0 else 0.0
        cal[key] = {
            "key": key,
            "display": spec_by_key[key]["display"],
            "n": 30,
            "n_accused": len(accusations),
            "n_abstained": len(abstentions),
            "n_sub_breakeven": len(sub_be),
            "n_sub_breakeven_lucky": sum(1 for a in sub_be if a["correct"]),
            "n_sub_breakeven_wrong": sum(1 for a in sub_be if not a["correct"]),
            "sub_breakeven_seeds": [a["seed"] for a in sub_be],
            "abstention_seeds": [a["seed"] for a in abstentions],
            "raw_mean": round(raw_mean, 12),
            "raw_ci": round(raw_ci, 12),
            "ev_mean": round(ev_mean, 12),
            "ev_ci": round(ev_ci, 12),
            "raw_sum": round(sum(raw_seq), 12),
            "ev_sum": round(sum(ev_seq), 12),
            "windfall_mean": round(raw_mean - ev_mean, 12),
            "windfall_sum": round(sum(raw_seq) - sum(ev_seq), 12),
            "ci_shrink_fraction": round(ci_shrink, 12),
            "accusations": accusations,
            "abstentions": abstentions,
            "cum_raw": cum_raw,
            "cum_ev": cum_ev,
        }

    return {
        "tiers_version": "v1.4",
        "seeds": list(range(30)),
        "bootstrap_resamples": charts.BOOTSTRAP_RESAMPLES,
        "committed_boot_seed": charts.COMMITTED_BOOT_SEED,
        "baseline_boot_seed": charts.BASELINE_BOOT_SEED,
        "solver_means": {
            "hard": round(float(sec_a[("solver", "hard")]["mean"]), 12),
            "medium": round(float(sec_a[("solver", "medium")]["mean"]), 12),
        },
        "forest": forest,
        "calibration": cal,
    }


@pytest.fixture(scope="module")
def chart_data() -> dict[str, Any]:
    return _build_committed_chart_data()


def test_source_and_protected_path_hygiene() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    test_text = THIS_TEST_PATH.read_text(encoding="utf-8")

    assert HASH_CHAR not in script_text
    assert HASH_CHAR not in test_text
    for blob in (script_text, test_text):
        assert EM_DASH not in blob
        assert EN_DASH not in blob
        assert CO_AUTHORED not in blob
        assert all(ord(ch) < 128 for ch in blob)

    owned_rel_paths = (
        "scripts/build_eval_charts_v14.py",
        "results/eval_v14/headline_gap_paired_v14.png",
        "results/eval_v14/posterior_calibration_v14.png",
        "tests/test_build_eval_charts_v14.py",
    )
    protected_prefixes: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith(HASH_CHAR):
            continue
        protected_prefixes.append(line)

    for rel_path in owned_rel_paths:
        for prefix in protected_prefixes:
            if prefix.endswith("/"):
                assert not rel_path.startswith(prefix)
            else:
                assert rel_path != prefix


def test_compute_chart_data_and_headline_numbers(chart_data: dict[str, Any]) -> None:
    assert chart_data["tiers_version"] == "v1.4"
    assert chart_data["seeds"] == list(range(30))
    assert chart_data["bootstrap_resamples"] == 10000
    assert chart_data["solver_means"]["hard"] == pytest.approx(0.499, abs=1e-9)
    assert chart_data["solver_means"]["medium"] == pytest.approx(0.645, abs=1e-9)

    hard_by_key = {r["key"]: r for r in chart_data["forest"]["hard"]}
    med_by_key = {r["key"]: r for r in chart_data["forest"]["medium"]}

    oc_hard = hard_by_key["opencode_carbon"]
    assert oc_hard["available"] is True
    assert oc_hard["n"] == 30
    assert oc_hard["raw_label"] == "65% [24%, 98%]"
    assert oc_hard["la_label"] == "72% [52%, 91%]"
    assert oc_hard["raw_hi"] < 1.0
    assert oc_hard["la_hi"] < 1.0

    oc_med = med_by_key["opencode_carbon"]
    assert oc_med["available"] is True
    assert oc_med["n"] == 30
    assert oc_med["raw_label"] == "111% [99%, 127%]"
    assert oc_med["la_label"] == "101% [85%, 119%]"

    fl_hard = hard_by_key["opencode_flash"]
    assert fl_hard["available"] is True
    assert fl_hard["n"] == 30
    assert fl_hard["raw_label"] == "75% [36%, 123%]"
    assert fl_hard["la_label"] == "22% [-23%, 63%]"
    assert med_by_key["opencode_flash"]["available"] is False

    ip_hard = hard_by_key["inproc_carbon"]
    assert ip_hard["raw_label"] == "95% [62%, 140%]"
    assert ip_hard["la_label"] == "84% [65%, 106%]"

    ip_med = med_by_key["inproc_carbon"]
    assert ip_med["raw_label"] == "82% [56%, 108%]"
    assert ip_med["la_label"] == "74% [52%, 99%]"

    for by_key in (hard_by_key, med_by_key):
        for zero_key in ("do_nothing", "stop_early"):
            zrow = by_key[zero_key]
            assert zrow["raw_mean"] == 0.0
            assert zrow["la_mean"] == 0.0
            assert zrow["raw_ratio"] == 0.0
            assert zrow["la_ratio"] == 0.0
            assert zrow["raw_label"] == "0% [0%, 0%]"
            assert zrow["la_label"] == "0% [0%, 0%]"

    cal = chart_data["calibration"]
    assert cal["solver"]["n_accused"] == 30
    assert cal["solver"]["n_sub_breakeven"] == 0
    assert cal["opencode_carbon"]["n_accused"] == 29
    assert cal["opencode_carbon"]["abstention_seeds"] == [11]
    assert cal["opencode_carbon"]["sub_breakeven_seeds"] == [5, 18, 23]
    assert cal["inproc_carbon"]["n_accused"] == 29
    assert cal["inproc_carbon"]["abstention_seeds"] == [26]

    fl_cal = cal["opencode_flash"]
    assert fl_cal["n_accused"] == 30
    assert fl_cal["n_sub_breakeven"] == 10
    assert fl_cal["n_sub_breakeven_lucky"] == 7
    assert fl_cal["n_sub_breakeven_wrong"] == 3
    assert fl_cal["raw_mean"] == pytest.approx(0.373, abs=1e-9)
    assert fl_cal["ev_mean"] == pytest.approx(0.1098876667, abs=1e-6)
    assert fl_cal["windfall_mean"] == pytest.approx(0.2631123333, abs=1e-6)
    assert fl_cal["windfall_sum"] == pytest.approx(fl_cal["windfall_mean"] * 30.0, abs=1e-6)

    if HEADLINE_TABLE_JSON.is_file():
        headline_table = json.loads(HEADLINE_TABLE_JSON.read_text(encoding="utf-8"))
        sec_a = {
            (row["agent"], row["tier"]): row
            for row in headline_table["section_a"]
            if row.get("kind") != "sensitivity"
        }
        ht_oc_hard = sec_a[("opencode:google/gemini-4-carbon", "hard")]
        ht_fl_hard = sec_a[("opencode:google/gemini-3.5-flash", "hard")]
        assert oc_hard["raw_ratio"] == pytest.approx(ht_oc_hard["ratio"], abs=1e-8)
        assert oc_hard["la_ratio"] == pytest.approx(ht_oc_hard["luck_adj_ratio"], abs=1e-8)
        assert fl_cal["raw_mean"] == pytest.approx(ht_fl_hard["mean"], abs=1e-8)
        assert fl_cal["ev_mean"] == pytest.approx(ht_fl_hard["luck_adjusted_score"], abs=1e-8)
        assert fl_cal["windfall_mean"] == pytest.approx(
            ht_fl_hard["mean"] - ht_fl_hard["luck_adjusted_score"],
            abs=1e-8,
        )


def test_validate_summary_invariants_detects_tampering(chart_data: dict[str, Any]) -> None:
    assert charts.validate_summary_invariants(chart_data) == []

    bad_carbon = copy.deepcopy(chart_data)
    for row in bad_carbon["forest"]["hard"]:
        if row["key"] == "opencode_carbon":
            row["raw_label"] = "99% [90%, 105%]"
            row["raw_hi"] = 1.05
    errs_carbon = charts.validate_summary_invariants(bad_carbon)
    assert any("opencode_carbon hard labels mismatch" in e for e in errs_carbon)
    assert any("exclude 100% parity" in e for e in errs_carbon)

    bad_zero = copy.deepcopy(chart_data)
    for row in bad_zero["forest"]["medium"]:
        if row["key"] == "do_nothing":
            row["raw_mean"] = 0.05
    errs_zero = charts.validate_summary_invariants(bad_zero)
    assert any("do_nothing on medium must be exact 0%" in e for e in errs_zero)

    bad_flash = copy.deepcopy(chart_data)
    bad_flash["calibration"]["opencode_flash"]["windfall_mean"] = 0.01
    errs_flash = charts.validate_summary_invariants(bad_flash)
    assert any("windfall_mean" in e for e in errs_flash)


def test_committed_png_headers_dimensions_dpi_and_size() -> None:
    expected_dims = {
        charts.HEADLINE_PNG_NAME: (1980, 945),
        charts.CALIBRATION_PNG_NAME: (1980, 930),
    }
    for fname, (exp_w, exp_h) in expected_dims.items():
        fpath = OUT_DIR / fname
        assert fpath.is_file()
        raw = fpath.read_bytes()
        assert raw[:8] == charts.PNG_SIGNATURE
        assert b"IEND" in raw[-32:]
        meta = charts.inspect_png(fpath)
        assert meta["exists"] is True
        assert meta["valid_png"] is True
        assert 1024 < meta["size_bytes"] < charts.MAX_PNG_BYTES
        assert meta["width"] == exp_w
        assert meta["height"] == exp_h
        assert meta["dpi_x"] == charts.TARGET_DPI
        assert meta["dpi_y"] == charts.TARGET_DPI

    assert charts._validate_png_files(OUT_DIR) == []


def test_unmocked_small_slice_replay_and_posterior(chart_data: dict[str, Any]) -> None:
    ep_path = ROOT / "data/runs/committed/v1.4/opencode-gemini-4-carbon/hard/episodes.jsonl"
    oc_s5 = next(
        json.loads(line)
        for line in ep_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line)["seed"] == 5
    )
    charts.paired_v13._P_CACHE.clear()
    try:
        v_s5 = charts._episode_v(oc_s5)
        p_s5 = float(charts.paired_v13.p_acc(oc_s5))
        ev_s5 = float(charts.paired_v13.post_expected(oc_s5))
    finally:
        charts.paired_v13._P_CACHE.clear()

    exp_s5 = next(a for a in chart_data["calibration"]["opencode_carbon"]["accusations"] if a["seed"] == 5)
    assert v_s5 == pytest.approx(exp_s5["v"], abs=1e-9)
    assert p_s5 == pytest.approx(exp_s5["p"], abs=1e-9)
    assert ev_s5 == pytest.approx(exp_s5["ev"], abs=1e-9)
    assert exp_s5["sub_breakeven"] is True

    heur_s0 = charts._replay_baseline_by_tier_seed("heuristic", ("hard",), (0,))[("hard", 0)]
    zero_s0 = charts._replay_baseline_by_tier_seed("do_nothing", ("hard",), (0,))[("hard", 0)]
    assert heur_s0["tier"] == "hard" and heur_s0["seed"] == 0
    assert zero_s0["score"] == 0.0 and zero_s0["accused"] is None


def test_png_generation_into_tmp_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chart_data: dict[str, Any],
) -> None:
    import matplotlib.pyplot as plt
    from PIL import Image

    sm_path = tmp_path / "small_real.png"
    fig_sm, ax_sm = plt.subplots(1, 1, figsize=(2.0, 1.0), dpi=charts.TARGET_DPI)
    ax_sm.plot([0.0, 1.0], [0.2, 0.8])
    charts._save_figure_png(fig_sm, sm_path, dpi=charts.TARGET_DPI)
    plt.close(fig_sm)
    sm_meta = charts.inspect_png(sm_path)
    assert sm_meta["valid_png"] is True
    assert (sm_meta["width"], sm_meta["height"]) == (300, 150)
    assert sm_meta["dpi_x"] == 150 and sm_meta["dpi_y"] == 150

    def _fast_test_png_save(fig: Any, out_path: Path, dpi: int) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        w_in, h_in = fig.get_size_inches()
        w_px, h_px = round(w_in * dpi), round(h_in * dpi)
        img = Image.new("P", (w_px, h_px), 0)
        pal = [252, 252, 250] + [((i * 37) % 251) for i in range(1, 768)]
        img.putpalette(pal[:768])
        for x in range(min(512, w_px)):
            img.putpixel((x, x % h_px), (x % 250) + 1)
        img.save(out_path, format="PNG", compress_level=1, dpi=(dpi, dpi))

    monkeypatch.setattr(charts, "compute_chart_data", lambda *a, **kw: copy.deepcopy(chart_data))
    monkeypatch.setattr(charts, "_save_figure_png", _fast_test_png_save)
    gen_dir = tmp_path / "generated_v14"
    rc = charts.main(["--out-dir", str(gen_dir)])
    assert rc == 0
    assert charts._validate_png_files(gen_dir) == []

    h_meta = charts.inspect_png(gen_dir / charts.HEADLINE_PNG_NAME)
    c_meta = charts.inspect_png(gen_dir / charts.CALIBRATION_PNG_NAME)
    assert (h_meta["width"], h_meta["height"]) == (1980, 945)
    assert (c_meta["width"], c_meta["height"]) == (1980, 930)
    assert h_meta["dpi_x"] == 150 and h_meta["dpi_y"] == 150
    assert c_meta["dpi_x"] == 150 and c_meta["dpi_y"] == 150
    assert h_meta["size_bytes"] < charts.MAX_PNG_BYTES
    assert c_meta["size_bytes"] < charts.MAX_PNG_BYTES


def test_cli_check_on_real_dir_and_failure_modes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    chart_data: dict[str, Any],
) -> None:
    from PIL import Image

    monkeypatch.setattr(charts, "compute_chart_data", lambda *a, **kw: copy.deepcopy(chart_data))

    rc_real = charts.main(["--check"])
    captured_real = capsys.readouterr()
    assert rc_real == 0
    assert "PASS:" in captured_real.out
    assert "65% [24%, 98%]" in captured_real.out
    assert "72% [52%, 91%]" in captured_real.out
    assert "+0.263 V" in captured_real.out

    missing_dir = tmp_path / "missing_png"
    missing_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT_DIR / charts.HEADLINE_PNG_NAME, missing_dir / charts.HEADLINE_PNG_NAME)
    rc_missing = charts.main(["--check", "--out-dir", str(missing_dir)])
    captured_missing = capsys.readouterr()
    assert rc_missing == 1
    assert "missing PNG file" in captured_missing.err

    corrupt_dir = tmp_path / "corrupt_png"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT_DIR / charts.HEADLINE_PNG_NAME, corrupt_dir / charts.HEADLINE_PNG_NAME)
    (corrupt_dir / charts.CALIBRATION_PNG_NAME).write_bytes(b"CORRUPTED_NON_PNG_PAYLOAD_0123456789ABCDEF")
    rc_corrupt = charts.main(["--check", "--out-dir", str(corrupt_dir)])
    captured_corrupt = capsys.readouterr()
    assert rc_corrupt == 1
    assert "invalid PNG header" in captured_corrupt.err

    oversize_dir = tmp_path / "oversize_png"
    oversize_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT_DIR / charts.HEADLINE_PNG_NAME, oversize_dir / charts.HEADLINE_PNG_NAME)
    valid_bytes = (OUT_DIR / charts.CALIBRATION_PNG_NAME).read_bytes()
    (oversize_dir / charts.CALIBRATION_PNG_NAME).write_bytes(valid_bytes + (b"\x00" * charts.MAX_PNG_BYTES))
    rc_oversize = charts.main(["--check", "--out-dir", str(oversize_dir)])
    captured_oversize = capsys.readouterr()
    assert rc_oversize == 1
    assert "exceeds 200 KB cap" in captured_oversize.err

    wrong_dpi_dir = tmp_path / "wrong_dpi"
    wrong_dpi_dir.mkdir(parents=True, exist_ok=True)
    dpi96_img = Image.new("RGB", (64, 32), (252, 252, 250))
    dpi96_img.save(wrong_dpi_dir / charts.HEADLINE_PNG_NAME, format="PNG", compress_level=0, dpi=(96, 96))
    shutil.copyfile(OUT_DIR / charts.CALIBRATION_PNG_NAME, wrong_dpi_dir / charts.CALIBRATION_PNG_NAME)
    rc_dpi = charts.main(["--check", "--out-dir", str(wrong_dpi_dir)])
    captured_dpi = capsys.readouterr()
    assert rc_dpi == 1
    assert "PNG DPI mismatch" in captured_dpi.err


def test_fast_sha256_check_timing_lazy_imports_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    chart_data: dict[str, Any],
) -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    top_roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_roots.add(node.module.split(".")[0])
    for forbidden in ("matplotlib", "numpy", "PIL", "canary", "paired_v13"):
        assert forbidden not in top_roots, f"top-level heavy import {forbidden} in {SCRIPT_PATH}"

    calls = {"n": 0}

    def _fake_compute(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        calls["n"] += 1
        return copy.deepcopy(chart_data)

    monkeypatch.setattr(charts, "compute_chart_data", _fake_compute)
    t0 = time.perf_counter()
    assert charts.main(["--check"]) == 0
    elapsed = time.perf_counter() - t0
    assert calls["n"] == 0
    assert elapsed < 1.5, f"fast --check took {elapsed:.2f}s >= 1.5s"
    assert "PASS:" in capsys.readouterr().out

    assert charts.main(["--check", "--full-check"]) == 0
    assert calls["n"] == 1
    assert "PASS:" in capsys.readouterr().out

    monkeypatch.setattr(charts, "EXPECTED_INPUTS_SHA256", "0" * 64)
    assert charts.main(["--check"]) == 0
    assert calls["n"] == 2
    assert "PASS:" in capsys.readouterr().out

    tampered = copy.deepcopy(chart_data)
    for row in tampered["forest"]["hard"]:
        if row["key"] == "opencode_carbon":
            row["raw_label"] = "99% [90%, 105%]"
            row["raw_hi"] = 1.05
    monkeypatch.setattr(charts, "compute_chart_data", lambda *_a, **_kw: copy.deepcopy(tampered))
    assert charts.main(["--check"]) == 1
    assert "FAIL:" in capsys.readouterr().err
