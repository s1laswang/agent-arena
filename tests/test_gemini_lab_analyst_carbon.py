from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tokenize
from typing import Any

import pytest

from canary.gemini import analyst_carbon as ac
from canary.gemini import atlas_agreement

REPO_ROOT = Path(__file__).resolve().parents[1]
HASH_CH = chr(35)
MD_H2 = HASH_CH * 2
MD_H3 = HASH_CH * 3
UNICODE_DASHES = tuple(
    chr(cp)
    for cp in (
        0x2010,
        0x2011,
        0x2012,
        0x2013,
        0x2014,
        0x2015,
        0x2212,
        0xFE58,
        0xFE63,
        0xFF0D,
    )
)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)

ANALYST_PY_FILES = (
    Path("canary/gemini/analyst_carbon.py"),
    Path("canary/gemini/analyst_chatter_bias.py"),
    Path("canary/gemini/claim_audit_carbon.py"),
    Path("tests/test_gemini_lab_analyst_carbon.py"),
    Path("tests/test_gemini_lab_chatter_bias_carbon.py"),
    Path("tests/test_gemini_lab_claim_audit_carbon.py"),
)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_comma_int(raw: str) -> int:
    return int(raw.replace(",", "").strip())


def _assert_no_unicode_dashes(text: str) -> None:
    for bad in UNICODE_DASHES:
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
    assert idx["totals"]["run_count"] >= 5
    assert idx["totals"]["verified_quotes"] >= 145
    assert idx["totals"]["verified_quotes"] == idx["totals"]["total_quotes"]
    assert idx["totals"]["verified_quotes_pct"] == 100.0
    assert idx["totals"]["usage"]["calls"] >= 10
    assert idx["totals"]["usage"]["in"] >= 1114554
    assert idx["totals"]["usage"]["out"] >= 44068
    assert idx["totals"]["usage"]["thinking"] >= 95665
    assert idx["totals"]["usage"]["cost_usd"] >= 3.47

    run_ids = {r["run_id"] for r in idx["runs"]}
    required_core_runs = {
        "atlas-carbon",
        "calibration-ev-carbon",
        "carbon-longctx-corpus",
        "chatter-bias-forensics-carbon",
        "claim-audit-carbon",
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


def _git_blob_bytes(ref_and_path: str) -> bytes | None:
    res = subprocess.run(
        ["git", "show", ref_and_path],
        cwd=REPO_ROOT,
        capture_output=True,
        check=False,
        timeout=10,
    )
    return res.stdout if res.returncode == 0 else None


def test_validation_md_untouched_and_never_modified_by_suite(tmp_path: Path) -> None:
    val_path = REPO_ROOT / "docs" / "gemini" / "validation.md"
    ctx_path = REPO_ROOT / "docs" / "gemini" / "validation_context.md"
    assert val_path.is_file()
    assert ctx_path.is_file()

    val_bytes_before = val_path.read_bytes()
    val_sha_before = _sha256(val_path)
    ctx_sha_before = _sha256(ctx_path)

    rows = atlas_agreement.parse_sheet(val_bytes_before.decode("utf-8"))
    ha = atlas_agreement.agreement(rows)
    assert len(rows) == 30
    assert ha["n_claims"] == 30
    assert ha["labeller"] == "Ivar (human)"
    assert ha["sheet"] == "docs/gemini/validation.md"

    baseline_bytes = _git_blob_bytes("origin/justSilas:docs/gemini/validation.md")
    if baseline_bytes is None:
        baseline_bytes = _git_blob_bytes("justSilas:docs/gemini/validation.md")

    if baseline_bytes is not None:
        assert val_bytes_before == baseline_bytes
        base_rows = atlas_agreement.parse_sheet(baseline_bytes.decode("utf-8"))
        base_ha = atlas_agreement.agreement(base_rows)
        assert ha["n_labelled"] == base_ha["n_labelled"]
    else:
        assert ha["n_labelled"] == 0
        assert ha["status"] == "pending"

    ac.consolidate_analyst_carbon(
        root=REPO_ROOT,
        analyst_dir=REPO_ROOT / ac.DEFAULT_ANALYST_DIR,
        index_out=tmp_path / "index.json",
        doc_out=tmp_path / "analyst.md",
        strict=True,
    )
    assert _sha256(val_path) == val_sha_before
    assert _sha256(ctx_path) == ctx_sha_before


def _load_raw_meta_records(analyst_dir: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    meta_paths = sorted(
        p
        for p in analyst_dir.glob("*/meta.json")
        if p.parent.name not in ac.SKIP_DIRS and not p.parent.name.startswith(".")
    )
    assert len(meta_paths) >= 5

    for mp in meta_paths:
        run_dir = mp.parent
        run_id = run_dir.name
        meta = json.loads(mp.read_text(encoding="utf-8"))
        assert meta.get("role", "failure_analyst") == "failure_analyst"
        assert meta.get("model_id") == "gemini-4-carbon"
        assert meta.get("stub", False) is False
        assert meta.get("fake_env", False) is False
        assert meta.get("smoke", False) is False

        u = meta["usage"]
        calls = int(u["calls"])
        tin = int(u["in"] if "in" in u else u["prompt_tokens"])
        tout = int(u["out"] if "out" in u else u["out_tokens"])
        think = int(u["thinking"] if "thinking" in u else u["thinking_tokens"])
        cached = int(u["cached"] if "cached" in u else u.get("cached_tokens", 0))
        cost_usd = round(float(u["cost_usd"]), 6)
        assert calls > 0 and tin > 0 and tout > 0 and cost_usd > 0.0

        vq = int(meta["verified_quotes"] if "verified_quotes" in meta else meta["n_quotes_verified"])
        tq = int(meta["total_quotes"] if "total_quotes" in meta else meta["n_quotes_raw"])
        vpct = round(float(meta["verified_quotes_pct"]), 2)
        assert vq > 0
        assert vq == tq
        assert vpct == 100.0

        for sib_name in ("atlas.json", "diagnosis.json", "forensics.json", "audit.json"):
            sib_path = run_dir / sib_name
            if sib_path.is_file():
                sib_doc = json.loads(sib_path.read_text(encoding="utf-8"))
                qv = sib_doc.get("quote_verification")
                if isinstance(qv, dict):
                    sib_vq = int(qv["verified_quotes"] if "verified_quotes" in qv else qv["verified"])
                    sib_tq = int(qv["total_quotes"] if "total_quotes" in qv else qv["total"])
                    assert sib_vq == vq
                    assert sib_tq == tq

        claims = int(meta.get("n_claims", 0) or 0)
        if claims > 0 and ("auditor" in meta or "validation_sheet" in meta) and "n_episodes" not in meta:
            ep_analyzed = int(meta.get("n_unique_episodes", 0) or 0)
            ep_diagnosed = ep_analyzed
        elif "n_calibrated_episodes" in meta:
            ep_analyzed = int(meta["n_calibrated_episodes"])
            ep_diagnosed = int(meta["n_episodes"])
        else:
            ep_cands = [
                int(meta[k])
                for k in ("n_episodes_packed", "n_episodes", "episode_count", "n_samples", "count")
                if isinstance(meta.get(k), int) and not isinstance(meta.get(k), bool)
            ]
            ep_analyzed = max(ep_cands)
            ep_diagnosed = (
                int(meta["n_episodes"])
                if isinstance(meta.get("n_episodes"), int) and int(meta["n_episodes"]) > 0
                else ep_analyzed
            )

        raw_commit = str(meta.get("commit") or meta.get("git_sha") or "").strip()
        assert len(raw_commit) >= 7
        records[run_id] = {
            "run_id": run_id,
            "subrole": str(meta.get("subrole") or run_id.replace("-", "_")),
            "thinking_level": str(meta.get("thinking_level") or "default"),
            "commit": raw_commit[:12],
            "calls": calls,
            "in": tin,
            "out": tout,
            "thinking": think,
            "cached": cached,
            "cost_usd": cost_usd,
            "verified_quotes": vq,
            "total_quotes": tq,
            "verified_quotes_pct": vpct,
            "episodes_analyzed": ep_analyzed,
            "episodes_diagnosed": ep_diagnosed,
            "claims_analyzed": claims,
        }
    return records


def test_hostile_judge_analyst_md_cells_match_index_and_meta_sums() -> None:
    analyst_dir = REPO_ROOT / ac.DEFAULT_ANALYST_DIR
    idx_path = REPO_ROOT / ac.DEFAULT_INDEX_PATH
    doc_path = REPO_ROOT / ac.DEFAULT_DOC_PATH

    meta_by_id = _load_raw_meta_records(analyst_dir)
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    doc_text = doc_path.read_text(encoding="utf-8")

    meta_run_count = len(meta_by_id)
    meta_calls = sum(r["calls"] for r in meta_by_id.values())
    meta_in = sum(r["in"] for r in meta_by_id.values())
    meta_out = sum(r["out"] for r in meta_by_id.values())
    meta_thinking = sum(r["thinking"] for r in meta_by_id.values())
    meta_cached = sum(r["cached"] for r in meta_by_id.values())
    meta_cost = round(sum(r["cost_usd"] for r in meta_by_id.values()), 6)
    meta_vq = sum(r["verified_quotes"] for r in meta_by_id.values())
    meta_tq = sum(r["total_quotes"] for r in meta_by_id.values())
    meta_vpct = round(100.0 * meta_vq / meta_tq, 2)
    meta_ep_analyzed = sum(r["episodes_analyzed"] for r in meta_by_id.values())
    meta_ep_diagnosed = sum(r["episodes_diagnosed"] for r in meta_by_id.values())
    meta_claims = sum(r["claims_analyzed"] for r in meta_by_id.values())

    t = idx["totals"]
    tu = t["usage"]
    assert t["run_count"] == meta_run_count
    assert t["scanned_run_count"] == meta_run_count
    assert t["rejected_run_count"] == 0
    assert t["episodes_analyzed"] == meta_ep_analyzed
    assert t["episodes_diagnosed"] == meta_ep_diagnosed
    assert t["claims_analyzed"] == meta_claims
    assert t["verified_quotes"] == meta_vq
    assert t["total_quotes"] == meta_tq
    assert t["verified_quotes_pct"] == meta_vpct
    assert tu["calls"] == meta_calls
    assert tu["in"] == meta_in
    assert tu["out"] == meta_out
    assert tu["thinking"] == meta_thinking
    assert tu["cached"] == meta_cached
    assert tu["cost_usd"] == meta_cost

    idx_by_id = {r["run_id"]: r for r in idx["runs"]}
    assert set(idx_by_id) == set(meta_by_id)

    m_runs = re.search(
        r"\|\s*Verified `gemini-4-carbon` Runs\s*\|\s*`(\d+)`\s*\(rejected:\s*`(\d+)`,\s*secret leaks:\s*`(\d+)`\)\s*\|",
        doc_text,
    )
    assert m_runs is not None
    assert int(m_runs.group(1)) == meta_run_count == t["run_count"]
    assert int(m_runs.group(2)) == 0 == t["rejected_run_count"]
    assert int(m_runs.group(3)) == 0

    m_scope = re.search(
        r"\|\s*Corpus Scope Analyzed\s*\|\s*`(\d+)` episode-level evaluations \(`(\d+)` directly diagnosed\)"
        r"(?:\s*\+\s*`(\d+)` audited atlas claims \(automated LLM audit\))?\s*\|",
        doc_text,
    )
    assert m_scope is not None
    assert int(m_scope.group(1)) == meta_ep_analyzed == t["episodes_analyzed"]
    assert int(m_scope.group(2)) == meta_ep_diagnosed == t["episodes_diagnosed"]
    parsed_claims = int(m_scope.group(3)) if m_scope.group(3) is not None else 0
    assert parsed_claims == meta_claims == t["claims_analyzed"]

    m_quotes = re.search(
        r"\|\s*Verbatim Quote Verification\s*\|\s*`(\d+)/(\d+)`\s*\(`([0-9.]+)%` exact Python verification\)\s*\|",
        doc_text,
    )
    assert m_quotes is not None
    assert int(m_quotes.group(1)) == meta_vq == t["verified_quotes"]
    assert int(m_quotes.group(2)) == meta_tq == t["total_quotes"]
    assert float(m_quotes.group(3)) == pytest.approx(meta_vpct, abs=0.05)

    m_calls = re.search(r"\|\s*Gemini API Calls\s*\|\s*`(\d+)`\s*\|", doc_text)
    assert m_calls is not None
    assert int(m_calls.group(1)) == meta_calls == tu["calls"]

    m_toks = re.search(
        r"\|\s*Input / Output / Thinking Tokens\s*\|\s*`([0-9,]+)` in / `([0-9,]+)` out / `([0-9,]+)` thinking \(`([0-9,]+)` cached\)\s*\|",
        doc_text,
    )
    assert m_toks is not None
    assert _parse_comma_int(m_toks.group(1)) == meta_in == tu["in"]
    assert _parse_comma_int(m_toks.group(2)) == meta_out == tu["out"]
    assert _parse_comma_int(m_toks.group(3)) == meta_thinking == tu["thinking"]
    assert _parse_comma_int(m_toks.group(4)) == meta_cached == tu["cached"]

    m_cost = re.search(r"\|\s*Recorded Gemini API Cost\s*\|\s*`\$([0-9]+\.[0-9]{6})` USD\s*\|", doc_text)
    assert m_cost is not None
    assert m_cost.group(1) == f"{meta_cost:.6f}" == f"{tu['cost_usd']:.6f}"
    assert float(m_cost.group(1)) == meta_cost == tu["cost_usd"]

    runs_sec_hdr = f"{MD_H2} Committed `failure_analyst` Carbon Runs"
    prov_sec_hdr = f"{MD_H2} Per-Run Provenance & Decision Forensics Details"
    assert runs_sec_hdr in doc_text and prov_sec_hdr in doc_text

    runs_table_part = doc_text.split(runs_sec_hdr, 1)[1].split(prov_sec_hdr, 1)[0]
    table_lines = [ln for ln in runs_table_part.splitlines() if ln.strip().startswith("| `")]
    assert len(table_lines) == meta_run_count

    tbl_sum_calls = 0
    tbl_sum_in = 0
    tbl_sum_out = 0
    tbl_sum_think = 0
    tbl_sum_vq = 0
    tbl_sum_tq = 0
    tbl_seen_ids: list[str] = []

    for ln in table_lines:
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        assert len(cells) >= 10
        rid = cells[0].strip("`")
        subrole = cells[1].strip("`")
        thinking = cells[2].strip("`")
        commit = cells[3].strip("`")
        q_match = re.fullmatch(r"`(\d+)/(\d+)` \(`(\d+)%`\)", cells[5])
        assert q_match is not None
        row_vq = int(q_match.group(1))
        row_tq = int(q_match.group(2))
        row_qpct = int(q_match.group(3))
        row_calls = int(cells[6])
        tok_match = re.fullmatch(r"([0-9,]+)\s*/\s*([0-9,]+)\s*/\s*([0-9,]+)", cells[7])
        assert tok_match is not None
        row_in = _parse_comma_int(tok_match.group(1))
        row_out = _parse_comma_int(tok_match.group(2))
        row_think = _parse_comma_int(tok_match.group(3))
        cost_match = re.fullmatch(r"`\$([0-9]+\.[0-9]{4})`", cells[8])
        assert cost_match is not None
        row_cost_str = cost_match.group(1)

        mr = meta_by_id[rid]
        ir = idx_by_id[rid]
        assert subrole == mr["subrole"] == ir["subrole"]
        assert thinking == mr["thinking_level"] == ir["thinking_level"]
        assert commit == mr["commit"] == ir["commit"]
        assert row_vq == mr["verified_quotes"] == ir["verified_quotes"]
        assert row_tq == mr["total_quotes"] == ir["total_quotes"]
        assert row_qpct == round(mr["verified_quotes_pct"]) == round(ir["verified_quotes_pct"])
        assert row_calls == mr["calls"] == ir["usage"]["calls"]
        assert row_in == mr["in"] == ir["usage"]["in"]
        assert row_out == mr["out"] == ir["usage"]["out"]
        assert row_think == mr["thinking"] == ir["usage"]["thinking"]
        assert row_cost_str == f"{mr['cost_usd']:.4f}" == f"{ir['usage']['cost_usd']:.4f}"

        tbl_seen_ids.append(rid)
        tbl_sum_calls += row_calls
        tbl_sum_in += row_in
        tbl_sum_out += row_out
        tbl_sum_think += row_think
        tbl_sum_vq += row_vq
        tbl_sum_tq += row_tq

    assert tbl_seen_ids == sorted(meta_by_id)
    assert tbl_sum_calls == meta_calls
    assert tbl_sum_in == meta_in
    assert tbl_sum_out == meta_out
    assert tbl_sum_think == meta_thinking
    assert tbl_sum_vq == meta_vq
    assert tbl_sum_tq == meta_tq

    prov_part = doc_text.split(prov_sec_hdr, 1)[1]
    prov_blocks = re.split(rf"(?:^|\n){re.escape(MD_H3)} ", prov_part)
    prov_blocks = [b for b in prov_blocks if b.strip()]
    assert len(prov_blocks) == meta_run_count

    prov_cost_sum = 0.0
    for blk in prov_blocks:
        hdr_m = re.match(r"^\d+\.\s+`([^`]+)`\s+\(`([^`]+)`\)", blk)
        assert hdr_m is not None
        rid = hdr_m.group(1)
        mr = meta_by_id[rid]
        ir = idx_by_id[rid]
        assert hdr_m.group(2) == mr["subrole"] == ir["subrole"]

        pq_m = re.search(r"- \*\*Verbatim quotes:\*\* `(\d+)/(\d+)` \(`([0-9.]+)%`\)", blk)
        assert pq_m is not None
        assert int(pq_m.group(1)) == mr["verified_quotes"] == ir["verified_quotes"]
        assert int(pq_m.group(2)) == mr["total_quotes"] == ir["total_quotes"]
        assert float(pq_m.group(3)) == pytest.approx(mr["verified_quotes_pct"], abs=0.05)

        pu_m = re.search(
            r"- \*\*Gemini API usage:\*\* `calls=(\d+)`, `in=([0-9,]+)`, `out=([0-9,]+)`, "
            r"`thinking=([0-9,]+)`, `cached=([0-9,]+)`, `cost_usd=\$([0-9]+\.[0-9]{6})`",
            blk,
        )
        assert pu_m is not None
        assert int(pu_m.group(1)) == mr["calls"] == ir["usage"]["calls"]
        assert _parse_comma_int(pu_m.group(2)) == mr["in"] == ir["usage"]["in"]
        assert _parse_comma_int(pu_m.group(3)) == mr["out"] == ir["usage"]["out"]
        assert _parse_comma_int(pu_m.group(4)) == mr["thinking"] == ir["usage"]["thinking"]
        assert _parse_comma_int(pu_m.group(5)) == mr["cached"] == ir["usage"]["cached"]
        assert pu_m.group(6) == f"{mr['cost_usd']:.6f}" == f"{ir['usage']['cost_usd']:.6f}"
        prov_cost_sum += float(pu_m.group(6))

    assert round(prov_cost_sum, 6) == meta_cost == tu["cost_usd"]


def test_analyst_carbon_code_hygiene_zero_comments_zero_dashes() -> None:
    assert len(ANALYST_PY_FILES) == 6
    for rel_path in ANALYST_PY_FILES:
        path = REPO_ROOT / rel_path
        assert path.is_file(), f"missing analyst file {rel_path}"
        src = path.read_text(encoding="utf-8")
        assert len(src) > 100
        _assert_no_unicode_dashes(src)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment tokens in {rel_path}: {comments}"
        assert HASH_CH not in src, f"found literal hash character in {rel_path}"
        assert ac.scan_file_hygiene(path, REPO_ROOT) == []
