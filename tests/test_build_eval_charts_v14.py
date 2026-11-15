"""Tests for deterministic v1.4 paired gap and posterior calibration chart builder."""

from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "build_eval_charts_v14.py"
OUT_DIR = ROOT / "results" / "eval_v14"
HEADLINE_TABLE_JSON = OUT_DIR / "headline_gap_table_v14.json"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"
THIS_TEST_PATH = Path(__file__).resolve()

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)


def _load_charts_module():
    spec = importlib.util.spec_from_file_location("build_eval_charts_v14", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


charts = _load_charts_module()


@pytest.fixture(scope="module")
def chart_data() -> dict[str, Any]:
    return charts.compute_chart_data(root=ROOT)


def test_source_and_protected_path_hygiene() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    test_text = THIS_TEST_PATH.read_text(encoding="utf-8")

    assert HASH_CHAR not in script_text
    assert HASH_CHAR not in test_text
    for blob in (script_text, test_text):
        assert EM_DASH not in blob
        assert EN_DASH not in blob

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


def test_png_generation_into_tmp_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    chart_data: dict[str, Any],
) -> None:
    monkeypatch.setattr(charts, "compute_chart_data", lambda *a, **kw: chart_data)
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
    rc_real = charts.main(["--check"])
    captured_real = capsys.readouterr()
    assert rc_real == 0
    assert "PASS:" in captured_real.out
    assert "65% [24%, 98%]" in captured_real.out
    assert "72% [52%, 91%]" in captured_real.out
    assert "+0.263 V" in captured_real.out

    monkeypatch.setattr(charts, "compute_chart_data", lambda *a, **kw: chart_data)

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
    charts.render_headline_gap_chart(chart_data, wrong_dpi_dir / charts.HEADLINE_PNG_NAME, dpi=96)
    shutil.copyfile(OUT_DIR / charts.CALIBRATION_PNG_NAME, wrong_dpi_dir / charts.CALIBRATION_PNG_NAME)
    rc_dpi = charts.main(["--check", "--out-dir", str(wrong_dpi_dir)])
    captured_dpi = capsys.readouterr()
    assert rc_dpi == 1
    assert "PNG DPI mismatch" in captured_dpi.err
