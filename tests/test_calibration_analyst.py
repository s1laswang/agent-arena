from __future__ import annotations

import copy
import dataclasses
import io
import json
from pathlib import Path
import struct
import tokenize

import pytest

from canary.baselines import DoNothing, StopEarly
from canary.env import Env
from canary.eval import run_episode
from canary.gemini import lab_client
from canary.gemini.provenance import audit_provenance, scan_file_secrets
from canary.llm import register_script
from canary.solver.policy import SolverPolicy
from scripts import run_calibration_analyst as rca

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows), encoding="utf-8")


def _png_dimensions(png_path: Path) -> tuple[int, int]:
    raw = png_path.read_bytes()
    assert raw[:8] == PNG_MAGIC
    assert raw[12:16] == b"IHDR"
    width, height = struct.unpack(">II", raw[16:24])
    return width, height


def _make_synthetic_runs(runs_dir: Path) -> None:
    ep_cal = dataclasses.asdict(run_episode(Env("easy", 0), SolverPolicy(None)))
    ep_cal["agent"] = "gemini:gemini-4-carbon"

    ep_prem_1 = dataclasses.asdict(run_episode(Env("medium", 1), StopEarly(seed=1)))
    ep_prem_1["agent"] = "openai:gpt-5.5"

    ep_prem_2 = dataclasses.asdict(run_episode(Env("medium", 2), StopEarly(seed=2)))
    ep_prem_2["agent"] = "codex:gpt-5.5"

    ep_abs = dataclasses.asdict(run_episode(Env("medium", 3), DoNothing(seed=3)))
    ep_abs["agent"] = "grok"

    ep_ref = dataclasses.asdict(run_episode(Env("medium", 1), StopEarly(seed=1)))
    ep_ref["agent"] = "stop_early"

    _write_jsonl(runs_dir / "v1.3" / "gemini" / "episodes.jsonl", [ep_cal])
    _write_jsonl(runs_dir / "v1.3" / "openai" / "episodes.jsonl", [ep_prem_1])
    _write_jsonl(runs_dir / "v1.3" / "codex" / "episodes.jsonl", [ep_prem_2])
    _write_jsonl(runs_dir / "v1.3" / "grok" / "episodes.jsonl", [ep_abs])
    _write_jsonl(runs_dir / "v1.3" / "reference" / "stop_early" / "episodes.jsonl", [ep_ref])


def test_pack_premature_episodes_filters_and_numbers_steps(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _make_synthetic_runs(runs_dir)

    items = rca.collect_premature_episodes(runs_dir=runs_dir, include_reference=False)
    assert len(items) == 2
    for it in items:
        rec = it["calibration"]
        assert rec["did_accuse"] is True
        assert rec["premature_commit"] is True
        assert rec["p_accused"] < 1.0 / (1.0 + rec["v_true"])
        assert rec["family"] != "reference"

    corpus_text, blocks, step_lines_by_ep = rca.pack_premature_episodes(items)
    assert len(blocks) == 2
    for eid, block in blocks.items():
        assert f"=== EPISODE {eid} ===" in corpus_text
        assert "\u2014" not in block
        assert "\u2013" not in block
        lines = step_lines_by_ep[eid]
        assert len(lines) >= 2
        assert lines[0].startswith("[S000] d")
        assert any(" accuse(" in ln for ln in lines)
        for ln in lines:
            assert '"' not in ln
            assert "\n" not in ln


def test_verify_quote_strict_substring_and_step_marker(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _make_synthetic_runs(runs_dir)
    items = rca.collect_premature_episodes(runs_dir=runs_dir)
    _, blocks, step_lines_by_ep = rca.pack_premature_episodes(items)

    eid = items[0]["episode_id"]
    other_eid = items[1]["episode_id"]
    valid_line = step_lines_by_ep[eid][-1]

    ok = rca.verify_quote(eid, valid_line, blocks)
    assert ok["verified"] is True
    assert ok["matched_line"] == valid_line

    bad_ep = rca.verify_quote("v1.3:missing:medium:s99", valid_line, blocks)
    assert bad_ep["verified"] is False
    assert bad_ep["reason"] == "unknown_episode_id"

    header_line = blocks[eid].splitlines()[1]
    bad_hdr = rca.verify_quote(eid, header_line, blocks)
    assert bad_hdr["verified"] is False
    assert bad_hdr["reason"] == "missing_step_number_marker"

    tampered = valid_line + " extra"
    bad_sub = rca.verify_quote(eid, tampered, blocks)
    assert bad_sub["verified"] is False
    assert bad_sub["reason"] == "substring_not_in_episode_block"

    payload = rca.build_stub_diagnosis_payload(items, step_lines_by_ep)
    bad_payload = copy.deepcopy(payload)
    bad_payload["episode_diagnoses"][0]["trigger_quote"]["episode_id"] = other_eid
    ver = rca.verify_diagnosis_payload(bad_payload, blocks, items)
    assert ver["quote_verification"]["unverified_quotes"] == 1
    assert ver["quote_verification"]["verified_quotes_pct"] < 100.0


def test_repair_retry_recovers_100_pct_verified_quotes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    runs_dir = tmp_path / "runs"
    out_dir = tmp_path / "out"
    _make_synthetic_runs(runs_dir)

    items = rca.collect_premature_episodes(runs_dir=runs_dir)
    _, _, step_lines_by_ep = rca.pack_premature_episodes(items)
    good_payload = rca.build_stub_diagnosis_payload(items, step_lines_by_ep)
    flawed_payload = copy.deepcopy(good_payload)
    flawed_payload["clusters"][0]["quotes"][0]["quote"] = "[S999] d99 accuse(employee=e99) -> ok accused=e99"

    script_name = "test_calibration_repair_script"
    register_script(script_name, [{"json": flawed_payload}, {"json": good_payload}])
    client = lab_client(f"stub:{script_name}", feature="calibration_analyst", run_id="test-repair")

    res = rca.run_calibration_analyst(
        runs_dir=runs_dir,
        out_dir=out_dir,
        model_id="stub",
        stub=True,
        max_repair_retries=2,
        client=client,
    )
    assert res["meta"]["verified_quotes_pct"] == 100.0
    assert res["meta"]["usage"]["calls"] == 2
    assert res["diagnosis"]["quote_verification"]["unverified_quotes"] == 0


def test_cli_stub_end_to_end_keyless(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    runs_dir = tmp_path / "runs"
    out_dir = tmp_path / "out_stub"
    _make_synthetic_runs(runs_dir)

    rc = rca.main(["--runs-dir", str(runs_dir), "--out", str(out_dir), "--stub", "--bins", "5"])
    assert rc == 0

    expected_files = (
        "meta.json",
        "calibration.json",
        "calibration.md",
        "calibration_curve.png",
        "diagnosis.json",
        "summary.md",
    )
    for fname in expected_files:
        fp = out_dir / fname
        assert fp.is_file() and fp.stat().st_size > 50

    w, h = _png_dimensions(out_dir / "calibration_curve.png")
    assert w > 600 and h > 250

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "failure_analyst"
    assert meta["subrole"] == "bayesian_calibration_analyst"
    assert meta["n_calibrated_episodes"] == 4
    assert meta["n_episodes"] == 2
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0

    for fname in ("meta.json", "calibration.json", "calibration.md", "diagnosis.json", "summary.md"):
        txt = (out_dir / fname).read_text(encoding="utf-8")
        assert "\u2014" not in txt
        assert "\u2013" not in txt
        assert scan_file_secrets(out_dir / fname, tmp_path) == []


def test_committed_artifact_if_present_passes_provenance_and_reverification() -> None:
    artifact_dir = REPO_ROOT / "results" / "gemini_roles" / "failure_analyst" / "calibration-ev-carbon"
    if not (artifact_dir / "meta.json").is_file():
        pytest.skip("committed failure_analyst calibration-ev-carbon artifact not generated yet")

    for fname in (
        "meta.json",
        "calibration.json",
        "calibration.md",
        "calibration_curve.png",
        "diagnosis.json",
        "summary.md",
    ):
        fp = artifact_dir / fname
        assert fp.is_file() and fp.stat().st_size > 100

    w, h = _png_dimensions(artifact_dir / "calibration_curve.png")
    assert w > 600 and h > 250

    meta = json.loads((artifact_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "failure_analyst"
    assert meta["subrole"] == "bayesian_calibration_analyst"
    assert meta["model_id"] == "gemini-4-carbon"
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["n_episodes"] > 0
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0
    assert meta["usage"]["cost_usd"] > 0.0

    diag = json.loads((artifact_dir / "diagnosis.json").read_text(encoding="utf-8"))
    items = rca.collect_premature_episodes(runs_dir=REPO_ROOT / "data" / "runs" / "committed")
    _, blocks, _ = rca.pack_premature_episodes(items)
    assert len(diag["episode_diagnoses"]) == len(items)
    assert len(diag["clusters"]) >= 3

    rechecked = 0
    for cl in diag["clusters"]:
        for q in cl["quotes"]:
            chk = rca.verify_quote(q["episode_id"], q["quote"], blocks)
            assert chk["verified"] is True, f"cluster quote failed verification: {chk}"
            rechecked += 1
    for ed in diag["episode_diagnoses"]:
        tq = ed["trigger_quote"]
        assert tq["episode_id"] == ed["episode_id"]
        chk = rca.verify_quote(tq["episode_id"], tq["quote"], blocks)
        assert chk["verified"] is True, f"episode quote failed verification: {chk}"
        rechecked += 1
    assert rechecked == diag["quote_verification"]["total_quotes"]
    assert rechecked >= len(items)

    prov = audit_provenance(REPO_ROOT)
    assert prov["secret_leaks"] == []
    fa = prov["roles"]["failure_analyst"]
    assert fa["verified"] is True, f"failure_analyst provenance failed: {fa}"
    assert "results/gemini_roles/failure_analyst/calibration-ev-carbon" in fa["run_dirs"]


def test_no_comments_no_em_dashes_no_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_calibration_analyst.py",
        REPO_ROOT / "tests" / "test_calibration_analyst.py",
    ]
    for path in py_targets:
        src = path.read_text(encoding="utf-8")
        assert "\u2014" not in src
        assert "\u2013" not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment tokens in {path}: {comments}"
        assert scan_file_secrets(path, REPO_ROOT) == []

    artifact_dir = REPO_ROOT / "results" / "gemini_roles" / "failure_analyst" / "calibration-ev-carbon"
    if artifact_dir.is_dir():
        for fp in sorted(p for p in artifact_dir.rglob("*") if p.is_file()):
            assert scan_file_secrets(fp, REPO_ROOT) == []
            if fp.suffix in {".json", ".md"}:
                txt = fp.read_text(encoding="utf-8")
                assert "\u2014" not in txt
                assert "\u2013" not in txt
