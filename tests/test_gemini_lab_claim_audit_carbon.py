from __future__ import annotations

from collections import Counter
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tokenize

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from canary.gemini import lab_client
from canary.llm import register_script
from scripts import run_claim_audit_carbon as rcac

SHEET_PATH = REPO_ROOT / "docs" / "gemini" / "validation.md"
CONTEXT_PATH = REPO_ROOT / "docs" / "gemini" / "validation_context.md"
ARTIFACT_DIR = REPO_ROOT / "results" / "gemini_roles" / "failure_analyst" / "claim-audit-carbon"
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_deterministic_parse_all_30_validation_claims_and_solver_steps() -> None:
    claims = rcac.load_and_verify_claims(SHEET_PATH, CONTEXT_PATH)
    assert len(claims) == 30
    assert [c["claim_id"] for c in claims] == list(range(1, 31))

    kind_counts = Counter(c["kind"] for c in claims)
    assert kind_counts == {
        "mode": 10,
        "label": 12,
        "counterfactual": 5,
        "localisation": 3,
    }

    for c in claims:
        assert c["sheet_quote_check"]["verified"] is True, f"claim {c['claim_id']} quote failed: {c['sheet_quote_check']}"
        assert c["consistency_signals"]["step_t_matches"] is True
        st = c["solver_step"]
        assert st["t"] == c["t"]
        assert st["top_employee"] is not None
        assert st["top_prob"] is not None
        assert st["mole_prob"] is not None
        assert "\u2014" not in c["clean_block"]
        assert "\u2013" not in c["clean_block"]

    by_id = {c["claim_id"]: c for c in claims}

    c1 = by_id[1]
    assert c1["episode"] == "gpt5.5.co.v13.h8"
    assert c1["solver_step"]["regret"] == pytest.approx(0.979)
    assert c1["solver_step"]["tags"] == ["premature_accusation"]
    assert c1["solver_step"]["top_employee"] == "e13"
    assert c1["solver_step"]["top_prob"] == pytest.approx(0.41)
    assert c1["solver_step"]["mole_prob"] == pytest.approx(0.41)

    c2 = by_id[2]
    assert c2["sheet_quote_check"]["match_mode"] == "table_pipe_escaped"
    assert c2["solver_step"]["regret"] == pytest.approx(0.073)
    assert c2["solver_step"]["tags"] == ["over_restriction"]
    assert c2["solver_step"]["top_employee"] == "e19"
    assert c2["solver_step"]["top_prob"] == pytest.approx(0.66)

    c4 = by_id[4]
    assert c4["episode"] == "g4carbon.in.v14.h6"
    assert c4["solver_step"]["regret"] == pytest.approx(0.501)
    assert c4["solver_step"]["tags"] == []
    assert c4["solver_step"]["top_employee"] == "e18"
    assert c4["solver_step"]["top_prob"] == pytest.approx(0.63)
    assert c4["solver_step"]["mole_prob"] == pytest.approx(0.01)
    assert c4["consistency_signals"]["accused_matches_solver_top"] is True
    assert c4["consistency_signals"]["solver_top_is_innocent"] is True

    c8 = by_id[8]
    assert c8["solver_step"]["tags"] == ["premature_accusation", "ignored_delay"]
    assert c8["consistency_signals"]["rationale_none"] is True

    c10 = by_id[10]
    assert c10["episode"] == "gpt5.5.co.v12.h0"
    assert c10["solver_step"]["top_employee"] == "e05"
    assert c10["solver_step"]["top_prob"] == pytest.approx(0.92)
    assert c10["solver_step"]["mole_prob"] == pytest.approx(0.08)

    c27 = by_id[27]
    assert c27["kind"] == "counterfactual"
    assert c27["solver_step"]["top_employee"] == "e01"
    assert c27["solver_step"]["top_prob"] == pytest.approx(0.29)
    assert c27["consistency_signals"]["solver_never_accuses_at_top_prob"] is True


def test_auditor_quote_verification_and_repair_loop_keyless(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    claims = rcac.load_and_verify_claims(SHEET_PATH, CONTEXT_PATH)
    c4 = claims[3]
    valid_q = rcac.verify_auditor_quote(c4, c4["solver_step"]["raw_line"])
    assert valid_q["verified"] is True
    assert valid_q["exact_line"] is True

    banner_line = c4["clean_block"].splitlines()[0]
    bad_banner = rcac.verify_auditor_quote(c4, banner_line)
    assert bad_banner["verified"] is False
    assert bad_banner["reason"] == "episode_banner_not_allowed"

    bad_dash = rcac.verify_auditor_quote(c4, "t150 d15 accuse \u2014 invalid em dash quote")
    assert bad_dash["verified"] is False
    assert bad_dash["reason"] == "contains_unicode_dash"

    bad_missing = rcac.verify_auditor_quote(c4, ">>> t999 d99 accuse(employee=e99) -> invented line")
    assert bad_missing["verified"] is False
    assert bad_missing["reason"] == "substring_not_in_context_block"

    good_payload = rcac.build_stub_audit_payload(claims)
    flawed_payload = copy.deepcopy(good_payload)
    flawed_payload["audits"][3]["verbatim_context_line"] = ">>> t999 d99 fabricated quote that is not in block"
    flawed_payload["audits"].pop()

    script_name = "test_claim_audit_repair_retry"
    register_script(script_name, [{"json": flawed_payload}, {"json": good_payload}])
    client = lab_client(f"stub:{script_name}", feature="claim_audit_carbon", run_id="test-claim-repair")

    out_dir = tmp_path / "repair_out"
    res = rcac.run_claim_audit(
        sheet_path=SHEET_PATH,
        context_path=CONTEXT_PATH,
        out_dir=out_dir,
        model_id="stub",
        stub=True,
        max_repair_retries=2,
        client=client,
    )
    assert res["meta"]["usage"]["calls"] == 2
    assert res["meta"]["verified_quotes_pct"] == 100.0
    assert res["audit"]["quote_verification"]["unverified_quotes"] == 0
    assert res["meta"]["n_claims"] == 30


def test_cli_stub_end_to_end_keyless_never_mutates_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GOOGLE_GENERATIVE_AI_API_KEY", "")
    monkeypatch.setenv("CANARY_GEMINI_LEDGER", str(tmp_path / "ledger.jsonl"))

    sheet_before = _sha256(SHEET_PATH)
    ctx_before = _sha256(CONTEXT_PATH)
    atlas_path = REPO_ROOT / "results" / "gemini" / "atlas.json"
    atlas_before = _sha256(atlas_path) if atlas_path.is_file() else None

    out_dir = tmp_path / "stub_out"
    rc = rcac.main([
        "--sheet",
        str(SHEET_PATH),
        "--context",
        str(CONTEXT_PATH),
        "--out",
        str(out_dir),
        "--stub",
    ])
    assert rc == 0

    assert _sha256(SHEET_PATH) == sheet_before
    assert _sha256(CONTEXT_PATH) == ctx_before
    if atlas_before is not None:
        assert _sha256(atlas_path) == atlas_before

    for fname in ("meta.json", "audit.json", "summary.md"):
        fp = out_dir / fname
        assert fp.is_file() and fp.stat().st_size > 100
        txt = fp.read_text(encoding="utf-8")
        assert "\u2014" not in txt
        assert "\u2013" not in txt
        assert rcac.scan_file_secrets(fp, tmp_path) == []

    meta = json.loads((out_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "failure_analyst"
    assert meta["subrole"] == "atlas_claim_audit_carbon"
    assert meta["stub"] is True
    assert meta["n_claims"] == 30
    assert meta["n_episodes_packed"] == 30
    assert meta["agree"] + meta["disagree"] + meta["unsure"] == 30
    assert meta["overclaims_flagged"] >= 3
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["sheet_quotes_verified_pct"] == 100.0
    assert meta["usage"]["in"] > 0
    assert meta["usage"]["out"] > 0

    summary_md = (out_dir / "summary.md").read_text(encoding="utf-8")
    assert rcac.validate_report_text(summary_md) == []

    batched_out = tmp_path / "stub_batched_out"
    rc_batch = rcac.main([
        "--sheet",
        str(SHEET_PATH),
        "--context",
        str(CONTEXT_PATH),
        "--out",
        str(batched_out),
        "--batch-size",
        "6",
        "--stub",
    ])
    assert rc_batch == 0
    meta_batch = json.loads((batched_out / "meta.json").read_text(encoding="utf-8"))
    assert meta_batch["usage"]["calls"] == 6
    assert meta_batch["n_claims"] == 30
    assert meta_batch["verified_quotes_pct"] == 100.0


def test_committed_claim_audit_carbon_artifact_provenance_and_reverification() -> None:
    if not (ARTIFACT_DIR / "meta.json").is_file():
        pytest.skip("committed failure_analyst claim-audit-carbon artifact not generated yet")

    for fname in ("meta.json", "audit.json", "summary.md"):
        fp = ARTIFACT_DIR / fname
        assert fp.is_file() and fp.stat().st_size > 100
        assert rcac.scan_file_secrets(fp, REPO_ROOT) == []

    meta = json.loads((ARTIFACT_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["role"] == "failure_analyst"
    assert meta["subrole"] == "atlas_claim_audit_carbon"
    assert meta["model_id"] == "gemini-4-carbon"
    assert isinstance(meta["commit"], str) and COMMIT_RE.fullmatch(meta["commit"]) is not None
    assert meta["stub"] is False
    assert meta["fake_env"] is False
    assert meta["smoke"] is False
    assert meta["source"] == "llm"
    assert meta["auditor"] == "gemini-4-carbon (automated LLM audit, not human)"
    assert meta["thinking_level"] in ("low", "medium", "high")
    assert meta["n_episodes_packed"] == 30
    assert meta["n_claims"] == 30
    assert isinstance(meta["agree"], int)
    assert isinstance(meta["disagree"], int)
    assert isinstance(meta["unsure"], int)
    assert meta["agree"] + meta["disagree"] + meta["unsure"] == 30
    assert 0.0 <= float(meta["agreement_rate"]) <= 1.0
    assert meta["verified_quotes_pct"] == 100.0
    assert meta["sheet_quotes_verified_pct"] == 100.0
    assert isinstance(meta["key_metric"], str) and len(meta["key_metric"]) >= 20

    u = meta["usage"]
    assert u["in"] > 0
    assert u["out"] > 0
    assert u["thinking"] > 0
    assert u["calls"] >= 1
    assert u["cost_usd"] > 0.0

    audit_doc = json.loads((ARTIFACT_DIR / "audit.json").read_text(encoding="utf-8"))
    assert audit_doc["auditor"] == "gemini-4-carbon (automated LLM audit, not human)"
    assert len(audit_doc["claims"]) == 30

    claims = rcac.load_and_verify_claims(SHEET_PATH, CONTEXT_PATH)
    by_id = {c["claim_id"]: c for c in claims}
    for row in audit_doc["claims"]:
        cid = row["claim_id"]
        assert row["verdict"] in ("agree", "disagree", "unsure")
        rechk = rcac.verify_auditor_quote(by_id[cid], row["verbatim_context_line"])
        assert rechk["verified"] is True, f"claim {cid} failed quote re-verification: {rechk}"

    summary_md = (ARTIFACT_DIR / "summary.md").read_text(encoding="utf-8")
    assert "gemini-4-carbon (automated LLM audit, not human)" in summary_md
    assert rcac.validate_report_text(summary_md) == []


def test_owned_files_have_no_comments_unicode_dashes_or_secrets() -> None:
    py_targets = [
        REPO_ROOT / "scripts" / "run_claim_audit_carbon.py",
        REPO_ROOT / "tests" / "test_gemini_lab_claim_audit_carbon.py",
    ]
    for path in py_targets:
        src = path.read_text(encoding="utf-8")
        assert "\u2014" not in src
        assert "\u2013" not in src
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"found comment tokens in {path}: {comments}"
        assert rcac.scan_file_secrets(path, REPO_ROOT) == []

    if ARTIFACT_DIR.is_dir():
        for fp in sorted(p for p in ARTIFACT_DIR.rglob("*") if p.is_file()):
            assert rcac.scan_file_secrets(fp, REPO_ROOT) == []
            txt = fp.read_text(encoding="utf-8")
            assert "\u2014" not in txt
            assert "\u2013" not in txt
