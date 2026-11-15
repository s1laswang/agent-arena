"""Tests for WS4 Gemini numbers QA (canary.gemini.qa)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from canary.gemini import qa


def test_code_verifier_parses_committed_artifacts():
    gt = qa.load_ground_truth(qa.ROOT)
    assert gt["results/gemini/ladder.json"]["episodes"] >= 357
    rows = qa.verify_structured_markdown_tables(qa.ROOT, gt) + qa.verify_submission_and_docs(qa.ROOT, gt)
    assert len(rows) >= 50
    assert all(r.match in ("y", "n") for r in rows)
    # Ladder cells must match ladder.json
    ladder_rows = [r for r in rows if r.file_line.startswith("results/gemini/ladder.md:")]
    assert len(ladder_rows) >= 34
    assert all(r.match == "y" for r in ladder_rows)


def test_replay_rebuilds_csv_md_and_json_with_zero_api_calls(tmp_path: Path, monkeypatch):
    cache_path = tmp_path / "argon_cache.json"
    cache_path.write_text(json.dumps({
        "generated_at": "2026-11-15T03:30:00+02:00",
        "model": "gemini-4-argon",
        "usage": {"in": 100, "out": 50, "cost_usd": 0.0},
        "located_claims": [
            {
                "claim": "100 Gemini red-team attacks found 0 verified exploits",
                "file_line": "docs/gemini/SUBMISSION.md:5",
                "source_file": "results/gemini/swarm.json",
                "source_key_or_value": "counts.attempts=100, counts.verified_exploits=0",
                "suspected_mismatch": False,
                "reason": "",
            }
        ],
    }))
    # Ensure no network/API client is invoked in --replay mode
    import canary.gemini.ledger as ledger_mod
    monkeypatch.setattr(ledger_mod, "lab_client", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("API called in --replay")))

    res = qa.run(root=qa.ROOT, out_dir=tmp_path, replay=True)
    assert res["total_claims"] >= 50
    assert res["matched"] + res["mismatches_count"] == res["total_claims"]

    csv_file = tmp_path / "claims.csv"
    assert csv_file.exists()
    with open(csv_file, newline="", encoding="utf-8") as f:
        parsed = list(csv.DictReader(f))
    assert len(parsed) == res["total_claims"]
    assert set(parsed[0].keys()) == {"claim", "file:line", "source file", "source value", "match"}
    assert all(r["match"] in ("y", "n") for r in parsed)

    assert (tmp_path / "qa.md").exists()
    assert json.loads((tmp_path / "qa.json").read_text())["total_claims"] == res["total_claims"]


def test_committed_ws4_qa_artifacts_valid():
    out_dir = qa.DEFAULT_OUT
    if not (out_dir / "claims.csv").exists():
        return
    with open(out_dir / "claims.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) >= 50
    qa_data = json.loads((out_dir / "qa.json").read_text())
    assert qa_data["total_claims"] == len(rows)
    assert qa_data["matched"] + qa_data["mismatches_count"] == len(rows)
