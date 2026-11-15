from __future__ import annotations

import io
import json
from pathlib import Path
import tokenize
from typing import Any

import pytest

from canary.gemini import analyst_carbon as ac

REPO_ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _assert_no_unicode_dashes(text: str) -> None:
    for bad in (EM_DASH, EN_DASH, FIG_DASH, HORIZ_BAR):
        assert bad not in text


def test_dynamic_discovery_and_regeneration_in_tmp_path(tmp_path: Path) -> None:
    analyst_dir = tmp_path / "results" / "gemini" / "roles_carbon" / "failure_analyst"
    idx_out = analyst_dir / "index.json"
    doc_out = tmp_path / "docs" / "gemini" / "roles_carbon" / "analyst.md"

    run_a = analyst_dir / "alpha-corpus-carbon"
    _write_json(
        run_a / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "alpha_corpus_forensics",
            "model_id": "gemini-4-carbon",
            "commit": "112233445566",
            "timestamp": "2026-11-15T00:00:00+00:00",
            "n_episodes_packed": 40,
            "verified_quotes_pct": 100.0,
            "usage": {
                "calls": 2,
                "prompt_tokens": 50000,
                "out_tokens": 4000,
                "thinking_tokens": 8000,
                "cached_tokens": 0,
                "cost_usd": 0.22,
            },
        },
    )
    _write_json(
        run_a / "atlas.json",
        {
            "summary": f"Synthesized 40 episodes{EM_DASH}premature commits dominate.",
            "corpus": {"episodes": 40, "total_regret": 9.5},
            "modes": [{"id": "premature-accusation", "name": "Premature Accusation", "regret_share": 0.5}],
            "quote_verification": {"verified": 12, "total": 12, "pct": 100.0},
        },
    )

    run_b = analyst_dir / "claim-audit-carbon"
    _write_json(
        run_b / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "atlas_claim_audit_carbon",
            "model_id": "gemini-4-carbon",
            "thinking_level": "medium",
            "stub": False,
            "auditor": "gemini-4-carbon (automated LLM audit, not human)",
            "validation_sheet": "docs/gemini/validation.md",
            "commit": "aabbccddeeff",
            "timestamp": "2026-11-15T00:05:00+00:00",
            "n_episodes_packed": 30,
            "n_claims": 30,
            "verified_quotes": 30,
            "total_quotes": 30,
            "verified_quotes_pct": 100.0,
            "key_metric": "30/30 atlas claims audited (automated LLM, not human): 22 agree, 6 disagree, 2 unsure",
            "usage": {
                "calls": 4,
                "in": 36000,
                "out": 7000,
                "thinking": 25000,
                "cached": 0,
                "cost_usd": 0.39,
            },
        },
    )

    rc = ac.main(
        [
            "--root",
            str(tmp_path),
            "--analyst-dir",
            str(analyst_dir),
            "--index-out",
            str(idx_out),
            "--doc-out",
            str(doc_out),
        ]
    )
    assert rc == 0
    assert idx_out.is_file()
    assert doc_out.is_file()

    idx_1 = json.loads(idx_out.read_text(encoding="utf-8"))
    md_1 = doc_out.read_text(encoding="utf-8")
    _assert_no_unicode_dashes(idx_out.read_text(encoding="utf-8"))
    _assert_no_unicode_dashes(md_1)

    assert idx_1["verified"] is True
    assert idx_1["secret_hygiene_clean"] is True
    assert idx_1["totals"]["run_count"] == 2
    assert idx_1["totals"]["episodes_analyzed"] == 40
    assert idx_1["totals"]["claims_analyzed"] == 30
    assert idx_1["totals"]["verified_quotes"] == 42
    assert idx_1["totals"]["total_quotes"] == 42
    assert idx_1["totals"]["verified_quotes_pct"] == 100.0
    assert idx_1["totals"]["usage"]["calls"] == 6
    assert idx_1["totals"]["usage"]["in"] == 86000
    assert idx_1["totals"]["usage"]["out"] == 11000
    assert idx_1["totals"]["usage"]["thinking"] == 33000
    assert idx_1["totals"]["usage"]["cost_usd"] == pytest.approx(0.61)
    assert "docs/gemini/validation.md" in md_1
    assert "Ivar" in md_1
    assert "automated LLM" in md_1

    run_c = analyst_dir / "stopping-forensics-carbon"
    _write_json(
        run_c / "meta.json",
        {
            "role": "failure_analyst",
            "subrole": "stopping_forensics",
            "model_id": "gemini-4-carbon",
            "thinking_level": "high",
            "stub": False,
            "commit": "998877665544",
            "timestamp": "2026-11-15T00:10:00+00:00",
            "n_episodes": 18,
            "verified_quotes": 18,
            "total_quotes": 18,
            "verified_quotes_pct": 100.0,
            "usage": {
                "calls": 1,
                "in": 24000,
                "out": 3000,
                "thinking": 9000,
                "cached": 0,
                "cost_usd": 0.17,
            },
        },
    )

    rc2 = ac.main(
        [
            "--root",
            str(tmp_path),
            "--analyst-dir",
            str(analyst_dir),
            "--index-out",
            str(idx_out),
            "--doc-out",
            str(doc_out),
        ]
    )
    assert rc2 == 0
    idx_2 = json.loads(idx_out.read_text(encoding="utf-8"))
    md_2 = doc_out.read_text(encoding="utf-8")
    assert idx_2["totals"]["run_count"] == 3
    assert idx_2["totals"]["episodes_analyzed"] == 58
    assert idx_2["totals"]["claims_analyzed"] == 30
    assert idx_2["totals"]["verified_quotes"] == 60
    assert idx_2["totals"]["usage"]["calls"] == 7
    assert "stopping-forensics-carbon" in md_2


def test_rejects_stub_wrong_model_and_secret_leaks(tmp_path: Path) -> None:
    analyst_dir = tmp_path / "analyst_runs"

    _write_json(
        analyst_dir / "good-carbon" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": "gemini-4-carbon",
            "stub": False,
            "commit": "abcdef123456",
            "n_episodes": 10,
            "verified_quotes": 10,
            "total_quotes": 10,
            "usage": {"calls": 1, "in": 1000, "out": 200, "thinking": 300, "cost_usd": 0.01},
        },
    )
    _write_json(
        analyst_dir / "bad-stub" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": "gemini-4-carbon",
            "stub": True,
            "commit": "abcdef123456",
            "n_episodes": 10,
            "usage": {"calls": 1, "in": 1000, "out": 200, "cost_usd": 0.01},
        },
    )
    _write_json(
        analyst_dir / "bad-model" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": "gemini-3.8-flash",
            "stub": False,
            "commit": "abcdef123456",
            "n_episodes": 10,
            "usage": {"calls": 1, "in": 1000, "out": 200, "cost_usd": 0.01},
        },
    )
    fake_google_key = "AI" + "za" + "SyFakeFixtureKeyForTest012345"
    _write_json(
        analyst_dir / "bad-secret" / "meta.json",
        {
            "role": "failure_analyst",
            "model_id": "gemini-4-carbon",
            "stub": False,
            "commit": "abcdef123456",
            "note": fake_google_key,
            "n_episodes": 10,
            "usage": {"calls": 1, "in": 1000, "out": 200, "cost_usd": 0.01},
        },
    )

    with pytest.raises(ValueError, match="unverified failure_analyst run"):
        ac.consolidate_analyst_carbon(
            root=tmp_path,
            analyst_dir=analyst_dir,
            index_out=analyst_dir / "index.json",
            doc_out=tmp_path / "analyst.md",
            strict=True,
        )

    non_strict = ac.consolidate_analyst_carbon(
        root=tmp_path,
        analyst_dir=analyst_dir,
        index_out=analyst_dir / "index.json",
        doc_out=tmp_path / "analyst.md",
        strict=False,
    )
    assert non_strict["verified"] is False
    assert non_strict["secret_hygiene_clean"] is False
    assert non_strict["totals"]["run_count"] == 1
    assert non_strict["totals"]["rejected_run_count"] == 3
    rejected_by_id = {r["run_id"]: r["issues"] for r in non_strict["rejected_runs"]}
    assert "stub_or_synthetic_run" in rejected_by_id["bad-stub"]
    assert any(x.startswith("wrong_model:") for x in rejected_by_id["bad-model"])
    assert "secret_hygiene_violation" in rejected_by_id["bad-secret"]


def test_committed_analyst_carbon_suite_index_and_doc() -> None:
    analyst_dir = REPO_ROOT / ac.DEFAULT_ANALYST_DIR
    idx_path = REPO_ROOT / ac.DEFAULT_INDEX_PATH
    doc_path = REPO_ROOT / ac.DEFAULT_DOC_PATH

    assert analyst_dir.is_dir()
    assert idx_path.is_file()
    assert doc_path.is_file()
    assert not (analyst_dir / "calibration-ev-carbon" / "calibration_curve.png").exists()

    for fp in sorted(p for p in analyst_dir.rglob("*") if p.is_file()):
        assert ac.scan_file_hygiene(fp, REPO_ROOT) == []
        if fp.suffix in {".json", ".md", ".svg"}:
            txt = fp.read_text(encoding="utf-8")
            _assert_no_unicode_dashes(txt)
            if fp.suffix == ".json":
                json.loads(txt)

    doc_text = doc_path.read_text(encoding="utf-8")
    _assert_no_unicode_dashes(doc_text)
    assert ac.scan_file_hygiene(doc_path, REPO_ROOT) == []

    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    discovered = ac.discover_analyst_runs(analyst_dir, root=REPO_ROOT)
    expected_idx = ac.build_analyst_index(discovered, strict=True, generated_at=idx["generated_at"])

    assert idx == expected_idx
    assert ac.render_analyst_md(idx) == doc_text

    assert idx["role"] == "failure_analyst"
    assert idx["target_model"] == "gemini-4-carbon"
    assert idx["verified"] is True
    assert idx["secret_hygiene_clean"] is True
    assert idx["totals"]["rejected_run_count"] == 0
    assert idx["totals"]["run_count"] >= 4
    assert idx["totals"]["verified_quotes"] >= 115
    assert idx["totals"]["verified_quotes"] == idx["totals"]["total_quotes"]
    assert idx["totals"]["verified_quotes_pct"] == 100.0
    assert idx["totals"]["usage"]["calls"] >= 6
    assert idx["totals"]["usage"]["in"] >= 1078133
    assert idx["totals"]["usage"]["out"] >= 36809
    assert idx["totals"]["usage"]["thinking"] >= 70034
    assert idx["totals"]["usage"]["cost_usd"] >= 3.07

    run_ids = {r["run_id"] for r in idx["runs"]}
    required_core_runs = {
        "atlas-carbon",
        "calibration-ev-carbon",
        "carbon-longctx-corpus",
        "chatter-bias-forensics-carbon",
    }
    assert required_core_runs.issubset(run_ids)
    for r in idx["runs"]:
        assert r["model_id"] == "gemini-4-carbon"
        assert r["stub"] is False
        assert r["verified"] is True
        assert r["secret_leaks"] == []
        assert r["run_id"] in doc_text

    assert "docs/gemini/validation.md" in doc_text
    assert "Ivar" in doc_text
    assert "automated LLM" in doc_text


def test_analyst_carbon_code_hygiene_zero_comments_zero_dashes() -> None:
    py_targets = [
        REPO_ROOT / "canary" / "gemini" / "analyst_carbon.py",
        REPO_ROOT / "tests" / "test_gemini_lab_analyst_carbon.py",
    ]
    for path in py_targets:
        src = path.read_text(encoding="utf-8")
        _assert_no_unicode_dashes(src)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment tokens in {path}: {comments}"
        assert ac.scan_file_hygiene(path, REPO_ROOT) == []
