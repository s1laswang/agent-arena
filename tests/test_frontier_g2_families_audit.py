"""Tests for scripts/frontier_g2_families_audit.py, g2_families_audit.json, and frontier_g2_families_v14.md."""
from __future__ import annotations

import importlib.util
import io
import json
import shutil
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


g2_mod = _load_script("frontier_g2_families_audit", SCRIPTS_DIR / "frontier_g2_families_audit.py")


def _forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError(f"subprocess call forbidden at runtime: {args}")

    monkeypatch.setattr(subprocess, "run", _fail)
    monkeypatch.setattr(subprocess, "Popen", _fail)
    monkeypatch.setattr(subprocess, "check_call", _fail)
    monkeypatch.setattr(subprocess, "check_output", _fail)


def test_g2_families_audit_hygiene_and_size() -> None:
    py_files = (
        ROOT / "scripts" / "frontier_g2_families_audit.py",
        ROOT / "tests" / "test_frontier_g2_families_audit.py",
    )
    all_files = py_files + (
        g2_mod.default_json_path(ROOT),
        g2_mod.default_md_path(ROOT),
    )

    for fp in all_files:
        assert fp.is_file(), f"missing file: {fp}"
        raw = fp.read_bytes()
        text = raw.decode("ascii")
        assert chr(0x2014) not in text
        assert chr(0x2013) not in text
        assert g2_mod.scan_meta_secrets(text) == []

    for py_fp in py_files:
        py_txt = py_fp.read_text(encoding="utf-8")
        assert chr(35) not in py_txt, f"hash character found in {py_fp}"
        tokens = list(tokenize.generate_tokens(io.StringIO(py_txt).readline))
        assert not any(tok.type == tokenize.COMMENT for tok in tokens)

    json_bytes = g2_mod.default_json_path(ROOT).read_bytes()
    assert len(json_bytes) < g2_mod.MAX_JSON_BYTES


def test_g2_families_audit_check_no_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    _forbid_subprocess(monkeypatch)
    rc = g2_mod.main(["--root", str(ROOT), "--check"])
    assert rc == 0


def test_g2_families_audit_gitless_shallow_export_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_subprocess(monkeypatch)
    syn_root = tmp_path / "shallow_zip_export"
    (syn_root / "data" / "runs" / "committed").mkdir(parents=True)
    os_symlink_src = ROOT / "data" / "runs" / "committed" / "v1.4"
    (syn_root / "data" / "runs" / "committed" / "v1.4").symlink_to(os_symlink_src)

    out_json = g2_mod.default_json_path(syn_root)
    out_md = g2_mod.default_md_path(syn_root)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(g2_mod.default_json_path(ROOT), out_json)
    shutil.copy2(g2_mod.default_md_path(ROOT), out_md)

    assert not (syn_root / ".git").exists()
    assert g2_mod.g2_presence_state(syn_root / "data" / "runs" / "committed" / "v1.4") == "both_absent"
    assert g2_mod.main(["--root", str(syn_root), "--check"]) == 0

    tampered = json.loads(out_json.read_text(encoding="utf-8"))
    tampered["families"]["argon"]["paired_vs_solver"]["mean_score"] = 0.123
    out_json.write_text(g2_mod.serialize_audit_json(tampered), encoding="utf-8")
    assert g2_mod.main(["--root", str(syn_root), "--check"]) == 1


def _rewrite_synthetic_g2_cohort(src_hard: Path, dst_hard: Path, target_agent: str) -> None:
    dst_hard.mkdir(parents=True, exist_ok=True)
    meta = json.loads((src_hard / "meta.json").read_text(encoding="utf-8"))
    meta["agent"] = target_agent
    meta["status"] = "complete"
    meta["smoke"] = False
    meta["hint"] = None
    meta["seeds"] = list(range(30))
    meta["planned_seeds"] = list(range(30))
    meta["invalid_episodes"] = []
    (dst_hard / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    out_lines: list[str] = []
    for ln in (src_hard / "episodes.jsonl").read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        ep = json.loads(ln)
        ep["agent"] = target_agent
        out_lines.append(json.dumps(ep))
    (dst_hard / "episodes.jsonl").write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    (dst_hard / "transcripts").symlink_to(src_hard / "transcripts")


def test_g2_families_audit_synthetic_live_g2_write_and_clean_rc0_zero_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _forbid_subprocess(monkeypatch)
    syn_g2 = tmp_path / "syn_g2_v14"
    carbon_src = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard"
    gpt55_src = ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gpt-5.5" / "hard"

    _rewrite_synthetic_g2_cohort(
        carbon_src,
        syn_g2 / "opencode-gemini-4-argon" / "hard",
        "opencode:google/gemini-4-argon",
    )
    assert g2_mod.g2_presence_state(syn_g2) == "partial"
    out_json = tmp_path / "out" / "g2_families_audit.json"
    out_md = tmp_path / "out" / "frontier_g2_families_v14.md"
    assert (
        g2_mod.main(
            [
                "--root",
                str(ROOT),
                "--g2-dir",
                str(syn_g2),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
                "--write",
            ]
        )
        == 1
    )

    _rewrite_synthetic_g2_cohort(
        gpt55_src,
        syn_g2 / "opencode-gemini-4-hydrogen" / "hard",
        "opencode:google/gemini-4-hydrogen",
    )
    assert g2_mod.g2_presence_state(syn_g2) == "both_present"

    rc_write = g2_mod.main(
        [
            "--root",
            str(ROOT),
            "--g2-dir",
            str(syn_g2),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--write",
        ]
    )
    assert rc_write == 0
    assert out_json.is_file() and out_md.is_file()
    syn_obj = json.loads(out_json.read_text(encoding="utf-8"))
    assert syn_obj["families"]["hydrogen"]["calibration_and_behavior"]["abstained_seeds"] == [0, 17]

    rc_check_live = g2_mod.main(
        [
            "--root",
            str(ROOT),
            "--g2-dir",
            str(syn_g2),
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
            "--check",
        ]
    )
    assert rc_check_live == 0


def test_g2_families_audit_numbers_match_ceo_and_gap_citations() -> None:
    obj = json.loads(g2_mod.default_json_path(ROOT).read_text(encoding="utf-8"))
    vt = obj["verification_totals"]
    assert vt["g2_episodes_total"] == 60
    assert vt["g2_episodes_replay_verified"] == 60
    assert vt["g2_transcripts_verified"] == 60
    assert vt["combined_hard_0_29_episodes_verified"] == 120
    assert vt["committed_v14_episodes_verified"] == 472
    assert vt["committed_plus_g2_v14_episodes_verified"] == 532
    assert vt["clean_rc0_non_accuse_zero_day_episodes"] == 2
    assert vt["all_mismatches"] == 0
    assert vt["all_timeouts_or_errors_in_valid_jsonl"] == 0
    assert vt["all_secret_or_signature_leaks"] == 0
    assert vt["argon_exceeding_900s_count"] == 30
    assert vt["argon_exceeding_3600s_count"] == 0
    assert vt["hydrogen_exceeding_900s_count"] == 0
    assert vt["hydrogen_exceeding_3600s_count"] == 0

    carb = obj["families"]["carbon"]["paired_vs_solver"]
    arg = obj["families"]["argon"]["paired_vs_solver"]
    hyd = obj["families"]["hydrogen"]["paired_vs_solver"]
    gpt = obj["committed_v14_and_gpt55_comparison"]["gpt_5_5_hard_0_29"]["paired_vs_solver"]

    assert g2_mod._ratio_ci_str(carb["raw_ratio_vs_solver"], carb["raw_ratio_ci"]) == "65% [24%, 98%]"
    assert (
        g2_mod._ratio_ci_str(carb["luck_adjusted_ratio_vs_solver"], carb["luck_adjusted_ratio_ci"])
        == "72% [52%, 91%]"
    )
    assert g2_mod._ratio_ci_str(arg["raw_ratio_vs_solver"], arg["raw_ratio_ci"]) == "103% [71%, 144%]"
    assert (
        g2_mod._ratio_ci_str(arg["luck_adjusted_ratio_vs_solver"], arg["luck_adjusted_ratio_ci"])
        == "60% [33%, 85%]"
    )
    assert g2_mod._ratio_ci_str(hyd["raw_ratio_vs_solver"], hyd["raw_ratio_ci"]) == "115% [92%, 157%]"
    assert (
        g2_mod._ratio_ci_str(hyd["luck_adjusted_ratio_vs_solver"], hyd["luck_adjusted_ratio_ci"])
        == "97% [75%, 119%]"
    )
    assert g2_mod._ratio_ci_str(gpt["raw_ratio_vs_solver"], gpt["raw_ratio_ci"]) == "101% [79%, 140%]"
    assert (
        g2_mod._ratio_ci_str(gpt["luck_adjusted_ratio_vs_solver"], gpt["luck_adjusted_ratio_ci"])
        == "84% [67%, 103%]"
    )
