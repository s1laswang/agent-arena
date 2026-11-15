from __future__ import annotations

import ast
import io
import json
import sys
import tokenize
from pathlib import Path

import pytest

import scripts.reproduce_tiebreak_all as rta

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = REPO_ROOT / "scripts" / "reproduce_tiebreak_all.py"
INDEX_PATH = REPO_ROOT / "docs" / "reports" / "TIEBREAK_INDEX.md"
SELF_PATH = Path(__file__).resolve()


def test_live_run_and_json_cli(capsys: pytest.CaptureFixture[str]) -> None:
    rc = rta.main(["--check", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    payload = json.loads(captured.out)
    assert payload["schema"] == rta.SCHEMA_ID
    assert payload["passed"] is True
    assert payload["check_mode"] is True
    assert payload["gates_passed"] == payload["gates_total"]
    assert payload["gates_total"] >= len(rta.CORE_GATE_SPECS)
    assert payload["wall_clock_ms"] > 0.0

    by_id = {g["gate_id"]: g for g in payload["gates"]}
    for gid, _, expected_cmd in rta.CORE_GATE_SPECS:
        assert gid in by_id
        gate = by_id[gid]
        assert gate["passed"] is True
        assert gate["command"] == expected_cmd
        assert gate["wall_clock_ms"] >= 0.0
        assert gate["summary"]
        assert gate["errors"] == []

    human_text = rta.format_human_report(payload)
    assert "TIEBREAK UNIFIED REPRO VERIFIER: PASS" in human_text
    for _, _, expected_cmd in rta.CORE_GATE_SPECS:
        assert f"[PASS] {expected_cmd}" in human_text
        assert "ms)" in human_text

    rc_single = rta.main(["--only", "neural_mlp_tiebreak"])
    out_single = capsys.readouterr().out
    assert rc_single == 0
    assert "[PASS] python -m train.neural_mlp_tiebreak --check" in out_single
    assert "ms)" in out_single


def test_full_flag_invokes_frontier_builder(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import scripts.tiebreak_vs_frontier_comparison as tvfc

    called = {"count": 0}
    cached = json.loads(
        (REPO_ROOT / "results" / "tiebreak" / "frontier_comparison" / "comparison_summary.json").read_text(
            encoding="utf-8"
        )
    )

    def fake_build(repo_root: Path = REPO_ROOT, workers: int = 12) -> dict:
        called["count"] += 1
        return cached

    monkeypatch.setattr(tvfc, "build_comparison_summary", fake_build)
    rc = rta.main(["--full", "--only", "tiebreak_vs_frontier_comparison", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert called["count"] == 1
    assert payload["full_mode"] is True
    assert "live 990-trajectory" in payload["gates"][0]["summary"]


def test_optional_module_handling_and_failure_exit(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    found_empty, absent_empty = rta.discover_optional_gates(tmp_path)
    assert found_empty == []
    assert absent_empty == list(rta.OPTIONAL_FILENAMES)

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    lc_script = scripts_dir / "tiebreak_learning_curve.py"
    vw_script = scripts_dir / "build_tiebreak_viewer.py"

    lc_script.write_text(
        "\n".join(
            [
                "import argparse",
                "def build_arg_parser():",
                "    ap = argparse.ArgumentParser()",
                "    ap.add_argument('--check', action='store_true')",
                "    ap.add_argument('--root', default='')",
                "    return ap",
                "def main(argv=None):",
                "    args = build_arg_parser().parse_args(argv)",
                "    print('curve_ok=' + str(bool(args.check)))",
                "    return 0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    vw_script.write_text(
        "\n".join(
            [
                "def verify_artifacts():",
                "    return {'passed': True, 'errors': []}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rc_ok = rta.main(["--root", str(tmp_path), "--allow-partial-root", "--json"])
    payload_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert payload_ok["passed"] is True
    assert payload_ok["optional_discovered"] == ["tiebreak_learning_curve", "build_tiebreak_viewer"]
    assert payload_ok["optional_absent"] == []
    assert payload_ok["gates_passed"] == 2
    assert payload_ok["gates_total"] == 2
    assert all(g["optional"] is True and g["passed"] is True for g in payload_ok["gates"])

    vw_script.write_text(
        "\n".join(
            [
                "def main(argv=None):",
                "    print('viewer artifact mismatch')",
                "    return 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rc_fail = rta.main(["--root", str(tmp_path), "--allow-partial-root"])
    out_fail = capsys.readouterr().out
    assert rc_fail == 1
    assert "TIEBREAK UNIFIED REPRO VERIFIER: FAIL (1/2 gates" in out_fail
    assert "[FAIL] scripts/build_tiebreak_viewer.py --check [optional]" in out_fail
    assert "viewer artifact mismatch" in out_fail

    rc_missing_core = rta.main(["--root", str(tmp_path), "--only", "neural_mlp_tiebreak"])
    out_missing_core = capsys.readouterr().out
    assert rc_missing_core == 1
    assert "missing required gate script" in out_missing_core


def test_tiebreak_index_verified_against_committed_jsons(tmp_path: Path) -> None:
    assert rta.verify_tiebreak_index(REPO_ROOT) == []
    index_txt = INDEX_PATH.read_text(encoding="utf-8")

    ledger = json.loads((REPO_ROOT / "results" / "tiebreak" / "experiment_ledger.json").read_text(encoding="utf-8"))
    addendum = json.loads((REPO_ROOT / "results" / "tiebreak" / "addendum_readiness.json").read_text(encoding="utf-8"))
    eb = json.loads((REPO_ROOT / "results" / "tiebreak" / "empirical_bayes" / "summary.json").read_text(encoding="utf-8"))
    mlp = json.loads((REPO_ROOT / "results" / "tiebreak" / "neural_mlp_dagger" / "mlp_summary.json").read_text(encoding="utf-8"))
    lin = json.loads((REPO_ROOT / "results" / "tiebreak" / "dagger_ablation" / "summary.json").read_text(encoding="utf-8"))

    assert ledger["summary_counts"]["historical_runs"] == 19
    hist_by_id = {r["run_id"]: r for r in ledger["historical_runs"]}
    assert hist_by_id["WS4-dagger-r1-8k-verda"]["after_mean_score"] == pytest.approx(-0.542, abs=1e-3)
    assert hist_by_id["WS4-dagger-r1-4k-verda"]["after_mean_score"] == pytest.approx(-0.101, abs=1e-3)
    assert "WS4-dagger-r1-8k-verda" in index_txt
    assert "WS4-dagger-r1-4k-verda" in index_txt

    t1_by_id = {r["run_id"]: r for r in addendum["track_1_runs"]}
    t2_by_id = {r["run_id"]: r for r in addendum["track_2_runs"]}
    assert f"{eb['after']['mean_score']:+.3f}" in index_txt
    assert f"{mlp['after']['mean_score']:+.3f}" in index_txt
    assert f"{lin['after']['mean_score']:+.3f}" in index_txt
    assert f"{t2_by_id['scaling-logistic-v14']['after_mean_score']:+.3f}" in index_txt
    assert t1_by_id["tiny-mlp-dagger-v14"]["criteria_passed_count"] == 5
    assert all(r["criteria_passed_count"] == 5 for r in addendum["track_2_runs"])

    bad_reports = tmp_path / "docs" / "reports"
    bad_reports.mkdir(parents=True, exist_ok=True)
    (bad_reports / "TIEBREAK_INDEX.md").write_text(
        "Pre-registered seeds 0..29 " + chr(0x2014) + "\n",
        encoding="utf-8",
    )
    bad_errs = rta.verify_tiebreak_index(tmp_path)
    assert any("em dash" in e for e in bad_errs)
    assert any("Panel Fix A" in e for e in bad_errs)


def test_source_and_doc_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    for py_path in (RUNNER_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT], f"comment in {py_path}"
        assert hash_char not in src, f"hash character in {py_path}"
        assert em_dash not in src, f"em dash in {py_path}"
        assert en_dash not in src, f"en dash in {py_path}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    idx_txt = INDEX_PATH.read_text(encoding="utf-8")
    assert em_dash not in idx_txt
    assert en_dash not in idx_txt
    assert idx_txt.isascii()
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules
