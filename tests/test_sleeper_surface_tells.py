from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import sleeper_surface_tells as sst


@pytest.fixture(autouse=True)
def _zero_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_committed_json_and_report_parity() -> None:
    assert sst.DEFAULT_JSON.is_file()
    assert sst.DEFAULT_REPORT.is_file()

    raw_json = sst.DEFAULT_JSON.read_text(encoding="utf-8")
    raw_md = sst.DEFAULT_REPORT.read_text(encoding="utf-8")
    json_bytes = len(raw_json.encode("utf-8"))
    assert json_bytes <= sst.MAX_JSON_BYTES

    report = json.loads(raw_json)
    assert report["passed"] is True
    assert report["config"]["tiers_version"] == "v1.4"
    assert report["config"]["scan_seeds"] == 200
    assert report["config"]["judge_seeds"] == 40
    assert sst.render_json(report) == raw_json
    assert sst.render_markdown(report) == raw_md

    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    script_path = ROOT / "scripts" / "sleeper_surface_tells.py"
    test_path = Path(__file__).resolve()

    for py_path in (script_path, test_path):
        txt = py_path.read_text(encoding="utf-8")
        assert hash_char not in txt
        assert ("canary." + "social") not in txt
        assert ("v1" + ".6") not in txt

    for fpath in (script_path, test_path, sst.DEFAULT_REPORT, sst.DEFAULT_JSON):
        txt = fpath.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        txt.encode("ascii")


def test_h2_template_wording_scanner_clean_and_mole_swap() -> None:
    res = sst.scan_template_wording_tells(scan_seeds=30, tiers=("easy", "medium", "hard"))
    assert res["passed"] is True
    assert res["public_facts_has_mole"] is False
    assert res["mole_swap_diffs"] == 0
    assert res["lint_failures"] == 0
    assert res["world_builder_truth_leaks"] == 0

    for tier in ("easy", "medium", "hard"):
        tr = res["tiers"][tier]
        assert tr["passed"] is True
        assert tr["unmatched_non_decoy"] == 0
        assert tr["angry_from_non_decoy"] == 0
        assert tr["iv_unmatched"] == 0
        assert tr["loso_msg_clf"]["leak_detected"] is False


def test_h3_format_schema_and_v14_multi_canary() -> None:
    res = sst.scan_structural_format_tells(
        scan_seeds=25,
        feed_episodes=8,
        tracks=("easy", "medium", "hard", "hard_forge"),
    )
    assert res["passed"] is True
    for tr_name, tr in res["tracks"].items():
        assert tr["passed"] is True, tr_name
        assert tr["roster_key_mismatches"] == 0
        assert tr["roster_id_mismatches"] == 0
        assert tr["roster_vocab_mismatches"] == 0
        assert tr["doc_schema_mismatches"] == 0
        assert tr["canary_schema_mismatches"] == 0
        assert tr["feed_schema_mismatches"] == 0
        assert tr["feed_unknown_docs"] == 0


def test_h4_canonical_log_sorting_and_known_v() -> None:
    res = sst.scan_actor_and_timing_tells(
        n_episodes=10,
        tracks=("easy", "medium", "hard", "hard_forge"),
    )
    assert res["passed"] is True
    assert res["mole_doc_hides_canary"] is True
    assert res["dsl_numeric_only"] is True
    assert res["known_v_mode"] is True

    for tr_name in ("easy", "medium", "hard", "hard_forge"):
        tr = res["tracks"][tr_name]
        assert tr["passed"] is True
        assert tr["unsorted_days"] == 0
        assert tr["log_key_mismatches"] == 0
        assert tr["intra_pair_ah_inversions"] == 0
        assert tr["known_v_leaks"] == 0
    assert res["tracks"]["medium"]["counterfactual_tail_framed_days"] > 0
    assert res["tracks"]["hard"]["counterfactual_tail_framed_days"] > 0


def test_h5_priors_and_panel_fix_d_error_parity() -> None:
    res = sst.scan_priors_and_error_probes(
        scan_seeds=80,
        judge_seeds=20,
        tracks=("easy", "medium", "hard"),
    )
    assert res["passed"] is True
    for tr_name in ("easy", "medium", "hard"):
        tr = res["tracks"][tr_name]
        assert tr["passed"] is True
        assert tr["decoy_collisions"] == 0
        assert tr["judge_public_matches"] == 0
        assert tr["error_parity_mismatches"] == 0
        assert tr["non_constant_errors"] == 0
        assert tr["mole_id_in_innocent_error"] == 0


def test_surface_tell_policies_blocked_vs_solver() -> None:
    res = sst.benchmark_surface_tell_policies(
        judge_seeds=8,
        train_seeds=25,
        tracks=("easy", "medium", "hard"),
    )
    assert res["passed"] is True
    for tr_name in ("easy", "medium", "hard"):
        rows = res["tracks"][tr_name]
        assert abs(rows["do_nothing"]["mean_score"]) < 1e-12
        solver_mean = rows["solver"]["mean_score"]
        assert solver_mean > 0.2
        for pol in (
            "surface_roster_prior",
            "surface_angry_tell",
            "surface_msg_template_clf",
            "surface_iv_subtemplate",
            "surface_log_tail_probe",
        ):
            assert rows[pol]["blocked"] is True
            assert rows[pol]["mean_score"] < solver_mean


def test_committed_v14_transcripts_and_positive_controls() -> None:
    tr_scan = sst.scan_committed_frontier_transcripts()
    assert tr_scan["passed"] is True
    assert tr_scan["total_episodes"] >= 150
    assert tr_scan["total_day1_accusations"] == 0
    assert tr_scan["total_zero_canary_accusations"] == 0

    ctrls = sst.run_planted_tell_controls()
    assert ctrls["passed"] is True
    for key in (
        "planted_h2_mole_wording_tell",
        "planted_h3_mole_key_order_tell",
        "planted_h4_unsorted_framed_logs",
        "planted_h5_error_parity_leak",
    ):
        assert ctrls["controls"][key]["detected"] is True


def test_cli_write_and_check_roundtrip(tmp_path: Path) -> None:
    out_md = tmp_path / "report.md"
    out_json = tmp_path / "report.json"
    args = [
        "--out",
        str(out_md),
        "--json-out",
        str(out_json),
        "--scan-seeds",
        "60",
        "--judge-seeds",
        "10",
        "--train-seeds",
        "20",
        "--tracks",
        "easy,medium",
    ]
    assert sst.main(args) == 0
    assert out_md.is_file()
    assert out_json.is_file()
    assert out_json.stat().st_size <= sst.MAX_JSON_BYTES
    assert sst.main([*args, "--check"]) == 0

    out_md.write_text("tampered\n", encoding="utf-8")
    assert sst.main([*args, "--check"]) == 1
