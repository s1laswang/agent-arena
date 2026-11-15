from __future__ import annotations

import ast
import hashlib
import io
import json
import shutil
import sys
import tokenize
from pathlib import Path

import pytest

import scripts.build_tiebreak_viewer as btv
import scripts.reproduce_tiebreak_all as rta
import scripts.verify_tiebreak_submission as vts

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "build_tiebreak_viewer.py"
SELF_PATH = Path(__file__).resolve()
HTML_PATH = REPO_ROOT / btv.HTML_REL
MANIFEST_PATH = REPO_ROOT / btv.MANIFEST_REL


def _copy_nine_sources(dst_root: Path) -> None:
    for _, rel in btv.SOURCE_JSON_SPECS:
        src = REPO_ROOT / rel
        dst = dst_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def test_viewer_source_and_artifact_hygiene() -> None:
    hash_char = chr(35)
    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    forbidden_roots = {"torch", "transformers"}

    for py_path in (SCRIPT_PATH, SELF_PATH):
        src = py_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(py_path))
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert not [t for t in toks if t.type == tokenize.COMMENT], f"comment in {py_path}"
        assert hash_char not in src, f"hash char in {py_path}"
        assert em_dash not in src
        assert en_dash not in src
        assert src.isascii()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name.split(".")[0] not in forbidden_roots
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_roots

    assert HTML_PATH.is_file()
    assert MANIFEST_PATH.is_file()
    assert not (HTML_PATH.parent / "table.md").exists()
    assert not any(
        p.name == "summary.json" or p.name.endswith("_summary.json")
        for p in HTML_PATH.parent.glob("*.json")
    )

    for art_path in (HTML_PATH, MANIFEST_PATH):
        txt = art_path.read_text(encoding="utf-8")
        assert em_dash not in txt
        assert en_dash not in txt
        assert txt.isascii()

    html_txt = HTML_PATH.read_text(encoding="utf-8")
    assert btv.CDN_OR_REMOTE_RE.search(html_txt) is None

    total_bytes = sum(p.stat().st_size for p in (SCRIPT_PATH, SELF_PATH, HTML_PATH, MANIFEST_PATH))
    assert total_bytes < 150_000
    assert total_bytes < btv.MAX_TOTAL_BYTES
    assert "torch" not in sys.modules
    assert "transformers" not in sys.modules


def test_check_cli_and_reproduce_discovery(capsys: pytest.CaptureFixture[str]) -> None:
    rc_json = btv.main(["--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["errors"] == []
    assert payload["sources_verified"] == 9
    assert payload["historical_runs"] == 19
    assert payload["compact_policies"] == 4

    rc_txt = btv.main(["--check"])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "PASS: tiebreak viewer verified" in out_txt

    discovered, _ = rta.discover_optional_gates(REPO_ROOT)
    discovered_ids = [gid for gid, _, _ in discovered]
    assert "build_tiebreak_viewer" in discovered_ids

    rc_gate = rta.main(["--only", "build_tiebreak_viewer", "--json"])
    gate_payload = json.loads(capsys.readouterr().out)
    assert rc_gate == 0
    assert gate_payload["passed"] is True
    assert gate_payload["gates"][0]["gate_id"] == "build_tiebreak_viewer"
    assert gate_payload["gates"][0]["passed"] is True


def test_manifest_and_html_reconcile_all_nine_sources() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    html_txt = HTML_PATH.read_text(encoding="utf-8")
    assert manifest["schema"] == btv.SCHEMA_ID

    for key, rel in btv.SOURCE_JSON_SPECS:
        raw = (REPO_ROOT / rel).read_bytes()
        expected_sha = hashlib.sha256(raw).hexdigest()[:16]
        assert manifest["source_artifacts"][key]["path"] == rel
        assert manifest["source_artifacts"][key]["sha256_16"] == expected_sha
        assert manifest["source_artifacts"][key]["bytes"] == len(raw)

    ts = manifest["track_separation"]
    assert ts["open_weight_llm_above_base_count"] == 0
    assert ts["open_weight_llm_total_runs"] == 19
    assert ts["open_weight_llm_n0_failure_count"] == 5
    assert ts["compact_non_llm_passing_count"] == 4
    assert ts["readme_qwen_addendum_eligible"] is False

    t1 = manifest["track1_open_weight_llm"]
    assert len(t1["historical_runs"]) == 19
    assert set(t1["n0_failure_run_ids"]) == {
        "J4-pilot-44200",
        "WS4-v3-44548-44550",
        "WS4-v3-44553",
        "WS4-v3-4k-s1-714d-spot",
        "Verda-base-backup-18ac",
    }
    hl = t1["highlights"]
    assert hl["v3_4k_s0"] == {"mean_score": -0.147, "ci95": 0.063, "n": 180}
    assert hl["v3_4k_s1"] == {"mean_score": -0.209, "ci95": 0.094, "n": 82}
    assert hl["v3_8k_s0"]["mean_score"] == pytest.approx(-0.060, abs=1e-3)
    assert hl["v3_8k_s2"]["mean_score"] == pytest.approx(-0.050, abs=1e-3)
    assert hl["v3_8k_s1"]["mean_score"] == pytest.approx(-0.777, abs=1e-3)
    assert hl["v3_8k_s3"]["mean_score"] == pytest.approx(-0.788, abs=1e-3)
    assert hl["paired_s0_minus_s3"] == {"mean_delta": 0.728, "ci95": 0.134, "n": 90}
    assert hl["confound_4k_at_8k"]["mean_score"] == pytest.approx(-0.716, abs=1e-3)
    assert hl["dagger_r1_8k"] == {"mean_score": -0.542, "ci95": 0.214, "n": 50}
    assert hl["dagger_r1_4k"] == {"mean_score": -0.101, "ci95": 0.112, "n": 41}

    by_cls = {p["policy_class"]: p for p in manifest["compact_non_llm_policies"]}
    assert set(by_cls) == {
        "CompactLinearDAggerPolicy",
        "TinyMLPPolicy",
        "ScalingLogisticPolicy",
        "EmpiricalBayesPolicy",
    }
    assert by_cls["CompactLinearDAggerPolicy"]["after_mean_score"] == pytest.approx(0.6267, abs=1e-3)
    assert by_cls["TinyMLPPolicy"]["after_mean_score"] == pytest.approx(0.6141, abs=1e-3)
    assert by_cls["ScalingLogisticPolicy"]["after_mean_score"] == pytest.approx(0.6107, abs=1e-3)
    assert by_cls["EmpiricalBayesPolicy"]["after_mean_score"] == pytest.approx(0.6073, abs=1e-3)
    for pol in by_cls.values():
        assert pol["is_open_weight_llm"] is False
        assert pol["gates_passed"] == 5
        assert pol["gates_total"] == 5
        assert pol["replay_verified"] is True

    sh = manifest["seed_hygiene_disclosure"]
    assert sh["train_seed_range"] == "100000..199999"
    assert sh["heldout_seed_range"] == "800000..800199"
    assert sh["dev_eval_seed_range"] == "0..29"
    assert sh["judge_episodes_touched"] == 0
    assert "never pre-registered" in sh["dev_protocol_disclosure"]

    for rid in t1["n0_failure_run_ids"]:
        assert rid in html_txt

    prov_outcome = vts.check_seed_and_secret_provenance(root=REPO_ROOT, strict=True)
    assert prov_outcome.passed is True, prov_outcome.errors


def test_generate_idempotence_and_tamper_rejections(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _copy_nine_sources(tmp_path)

    rc_missing = btv.main(["--check", "--root", str(tmp_path)])
    assert rc_missing == 1
    assert "missing" in capsys.readouterr().out

    rc_gen = btv.main(["--root", str(tmp_path), "--json"])
    gen_out = json.loads(capsys.readouterr().out)
    assert rc_gen == 0
    assert gen_out["verified"] is True

    gen_html = (tmp_path / btv.HTML_REL).read_text(encoding="utf-8")
    gen_manifest = (tmp_path / btv.MANIFEST_REL).read_text(encoding="utf-8")
    assert gen_html == HTML_PATH.read_text(encoding="utf-8")
    assert gen_manifest == MANIFEST_PATH.read_text(encoding="utf-8")
    assert btv.main(["--check", "--root", str(tmp_path)]) == 0
    capsys.readouterr()

    (tmp_path / btv.HTML_REL).write_text(
        gen_html.replace("</body>", '<script src="https://cdn.example.com/x.js"></script></body>'),
        encoding="utf-8",
    )
    assert btv.main(["--check", "--root", str(tmp_path)]) == 1
    cdn_err = capsys.readouterr().out
    assert "CDN" in cdn_err or "differs" in cdn_err

    (tmp_path / btv.HTML_REL).write_text(gen_html, encoding="utf-8")
    bad_tbl = tmp_path / btv.VIEWER_DIR_REL / "table.md"
    bad_tbl.write_text("| a | b |\n|---|---|\n| 1 | 2 |\n", encoding="utf-8")
    assert btv.main(["--check", "--root", str(tmp_path)]) == 1
    assert "table.md" in capsys.readouterr().out
    bad_tbl.unlink()

    bad_sum = tmp_path / btv.VIEWER_DIR_REL / "viewer_summary.json"
    bad_sum.write_text("{}\n", encoding="utf-8")
    assert btv.main(["--check", "--root", str(tmp_path)]) == 1
    assert "colliding summary filename" in capsys.readouterr().out
    bad_sum.unlink()

    (tmp_path / "results" / "tiebreak" / "scaling" / "scaling_summary.json").unlink()
    assert btv.main(["--check", "--root", str(tmp_path)]) == 1
    assert "missing required tiebreak JSON" in capsys.readouterr().out
