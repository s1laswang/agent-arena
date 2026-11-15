from __future__ import annotations

import importlib.util
import io
import sys
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "integrity_submit2_rehearsal_and_freeze_audit.py"
REPORT_PATH = ROOT / "docs" / "reports" / "integrity_submit2_rehearsal_and_freeze_audit.md"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("integrity_submit2_rehearsal_and_freeze_audit", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


audit_mod = _load_audit_module()


@pytest.fixture(scope="module")
def audit_result(tmp_path_factory):
    scratch = tmp_path_factory.mktemp("w8_submit2_scratch")
    return audit_mod.run_audit(root=ROOT, scratch_dir=scratch)


def test_code_freeze_invariant_across_final_submit2_and_justsilas(audit_result):
    assert audit_result["passed"] is True
    cf = audit_result["code_freeze"]
    assert cf["passed"] is True
    assert cf["problems"] == []

    refs = cf["refs"]
    assert refs["afterquery_final"].startswith("1bc3e281")
    assert refs["afterquery_submit"].startswith("9225f2ad")
    assert refs["afterquery_submit_2"].startswith("aa1c679e")
    assert refs["justSilas"].startswith("5f9b3297")

    assert len(cf["diff_pairs"]) >= 3
    for dp in cf["diff_pairs"]:
        assert dp["frozen_changed_count"] == 0, dp
        assert dp["frozen_byte_changes"] == 0, dp

    assert tuple(cf["frozen_paths"]) == audit_mod.FROZEN_PATHS
    for fp in audit_mod.FROZEN_PATHS:
        per_rev = cf["object_hashes"][fp]
        assert len(per_rev) >= 3
        assert len(set(per_rev.values())) == 1, (fp, per_rev)

    assert sorted(cf["submit2_commit_files"]) == [
        "README.md",
        "docs/SUBMISSION.md",
        "docs/reports/gap.md",
        "results/harbor/rehearsal/TABLE.md",
    ]
    assert cf["justsilas_post_submit2_files"] == ["docs/reports/CEO.md"]
    assert cf["ceo_append_only"] is True
    assert cf["ceo_appended_lines"] == 4
    assert cf["tier_hashes"] == {
        "tiers_version": "v1.4",
        "v14": "a8f99c2537c91d72",
        "v13": "8df71cf570bb48bc",
    }


def test_rehearsal_final_and_docs_consistency(audit_result):
    rh = audit_result["rehearsal_and_docs"]
    assert rh["passed"] is True
    assert rh["problems"] == []
    assert rh["build_sha"].startswith("1bc3e281")
    assert rh["harbor_version"] == "0.26.0"
    assert rh["verifier_timeout_sec"] == 120.0
    assert rh["agent_timeout_sec"] == 10800.0

    snap = rh["snapshot_table"]
    assert snap["oracle_mean"] == 0.506
    assert snap["opencode-1"]["n_valid"] == 10 and snap["opencode-1"]["ratio_pct"] == 93
    assert snap["opencode-2"]["n_valid"] == 10 and snap["opencode-2"]["ratio_pct"] == 116
    assert snap["opencode-3"]["n_valid"] == 7 and snap["opencode-3"]["n_infra"] == 1
    assert snap["opencode-3"]["ratio_pct"] == 153

    s1 = rh["s1_rehearsal_final_git"]
    if s1.get("available"):
        assert s1["passed"] is True
        assert s1["commit"].startswith("d0ead011")
        assert s1["n_jobs"] == 6
        assert s1["n_trials"] == 60
        assert s1["shared_ledger_keys"] == 1
        assert s1["n_hmac_verified"] == 60
        assert s1["n_parity_ok"] == 60
        assert s1["n_distinct_tasks"] == 10
        assert s1["runs"]["opencode-1"]["ratio_pct"] == 93
        assert s1["runs"]["opencode-2"]["ratio_pct"] == 116
        assert s1["runs"]["opencode-3"]["ratio_pct"] == 131
        assert s1["runs"]["opencode-3"]["n_valid"] == 9
        assert s1["runs"]["opencode-3"]["n_infra"] == 1
        assert abs(s1["runs"]["opencode-3"]["mean"] - 0.625833) < 1e-3
        assert abs(s1["runs"]["opencode-3"]["mean_infra_as_zero"] - 0.56325) < 1e-3
        assert s1["valid_gemini_correct"] == 28
        assert s1["valid_gemini_accused"] == 29
        assert s1["run3_before_cutoff"] == 5
        assert s1["run3_after_cutoff"] == 5


def test_harbor_published_keys_parity_and_negative_control(audit_result):
    hb = audit_result["harbor_and_negative_control"]
    assert hb["passed"] is True
    assert hb["problems"] == []
    assert hb["rehearsal_dry"]["passed"] is True
    assert hb["rehearsal_dry"]["n_trials"] == 43
    assert hb["rehearsal_dry"]["n_hmac_verified"] == 43
    assert hb["harbor_total_jobs"] == 18
    assert hb["harbor_consistent_jobs"] == 18
    assert hb["harbor_total_trials"] == 80
    assert hb["harbor_consistent_trials"] == 80
    assert hb["published_key_jobs_count"] == 8
    assert hb["published_key_trials_count"] == 57
    assert hb["published_key_hmac_verified"] == 57
    assert hb["published_key_five_way_parity"] == 57
    assert hb["c1_signed_unpublished_key_trials"] == 3
    assert hb["legacy_unsigned_trials"] == 20
    assert hb["other_trials_four_way_parity"] == 23

    neg = hb["negative_control_c1_tamper"]
    assert neg["passed"] is True
    assert neg["tampered_ledger_score"] == 1.0
    assert neg["true_ledger_v"] == 0.5
    assert neg["recorded_reward"] == 0.0
    assert neg["reward_txt"] == "0"
    assert neg["verifier_ledger_copied"] is False
    assert "FAIL: bad ledger signature" in neg["verifier_stdout"]
    assert neg["frozen_verifier_recheck_rc"] != 0
    assert neg["frozen_verifier_recheck_reward_json"] == {"reward": 0.0}


def test_positive_tamper_controls_and_structured_issues(audit_result, tmp_path):
    pc = audit_result["positive_controls"]
    assert pc["passed"] is True
    assert pc["total"] == 6
    assert pc["caught"] == 6
    assert [c["id"] for c in pc["cases"]] == ["C01", "C02", "C03", "C04", "C05", "C06"]
    assert all(c["caught"] is True for c in pc["cases"])

    issues = audit_result["structured_issues"]
    issue_ids = [i["id"] for i in issues]
    assert issue_ids == [
        "ISSUE-W8-S2-1",
        "ISSUE-W8-S2-2",
        "ISSUE-W8-S2-3",
        "ISSUE-W8-S2-4",
        "ISSUE-W8-S2-5",
        "ISSUE-W8-S2-6",
    ]

    dup_json = tmp_path / "dup.json"
    dup_json.write_text('{"score": 0.0, "score": 1.0}', encoding="utf-8")
    _, dup_err = audit_mod._load_json_strict(dup_json)
    assert dup_err is not None and "duplicate JSON keys" in dup_err


def test_report_sync_hygiene_and_zero_protected_paths(audit_result):
    assert REPORT_PATH.is_file()
    rendered = audit_mod.render_markdown_report(audit_result)
    actual = REPORT_PATH.read_text(encoding="utf-8")
    assert actual == rendered

    em_dash = chr(0x2014)
    en_dash = chr(0x2013)
    minus_sign = chr(0x2212)
    hash_ch = chr(35)
    co_author = "-".join(("Co", "Authored", "By"))

    test_path = Path(__file__).resolve()
    for p in (SCRIPT_PATH, REPORT_PATH, test_path):
        txt = p.read_text(encoding="utf-8")
        assert em_dash not in txt, p
        assert en_dash not in txt, p
        assert minus_sign not in txt, p
        assert co_author.lower() not in txt.lower(), p

    for py_path in (SCRIPT_PATH, test_path):
        src = py_path.read_text(encoding="utf-8")
        assert hash_ch not in src, py_path
        comments = [
            tok for tok in tokenize.generate_tokens(io.StringIO(src).readline)
            if tok.type == tokenize.COMMENT
        ]
        assert comments == [], (py_path, comments)

    prot_file = ROOT / ".github" / "protected-paths.txt"
    prefixes = [
        line.strip()
        for line in prot_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(hash_ch)
    ]
    owned = (
        "scripts/integrity_submit2_rehearsal_and_freeze_audit.py",
        "docs/reports/integrity_submit2_rehearsal_and_freeze_audit.md",
        "tests/test_integrity_submit2_rehearsal_and_freeze_audit.py",
    )
    for rel in owned:
        for pref in prefixes:
            if pref.endswith("/"):
                assert not rel.startswith(pref), (rel, pref)
            else:
                assert rel != pref, (rel, pref)
