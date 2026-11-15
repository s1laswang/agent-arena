from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote

import pytest

ROOT = Path(__file__).resolve().parents[1]
VERIFIER_PATH = ROOT / "scripts" / "verify_submission_doc.py"
AUDIT_DOC_PATH = ROOT / "docs" / "SUBMISSION-AUDIT.md"
SUBMISSION_DOC_PATH = ROOT / "docs" / "SUBMISSION.md"
GEMINI_SUBMISSION_PATH = ROOT / "docs" / "gemini" / "SUBMISSION.md"
DOC_CMD_SCRIPT = ROOT / "scripts" / "verify_doc_commands.py"
HYGIENE_SCRIPT = ROOT / "scripts" / "audit_doc_hygiene.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

H = chr(35)
EN_DASH = chr(0x2013)
EM_DASH = chr(0x2014)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


verifier = _load_module("verify_submission_doc", VERIFIER_PATH)
doc_cmd_mod = _load_module("verify_doc_commands_sub_audit", DOC_CMD_SCRIPT)
hygiene_mod = _load_module("audit_doc_hygiene_sub_audit", HYGIENE_SCRIPT)


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-submission-doc-") as tmp_dir:
        yield Path(tmp_dir)


def _make_overlay_root(base_dir: Path, case_name: str, overrides: dict[str, str]) -> Path:
    dst_root = base_dir / case_name
    dst_root.mkdir(parents=True, exist_ok=True)

    override_ancestors: set[str] = set()
    for rel_key in overrides:
        parts = Path(rel_key).parts
        for idx in range(1, len(parts)):
            override_ancestors.add("/".join(parts[:idx]))

    skip_names = {".git", "__pycache__", ".pytest_cache"}

    def _populate(src_dir: Path, dst_dir: Path, rel_prefix: str) -> None:
        for child in src_dir.iterdir():
            if child.name in skip_names:
                continue
            child_rel = f"{rel_prefix}/{child.name}" if rel_prefix else child.name
            target = dst_dir / child.name
            if child_rel in overrides:
                target.write_text(overrides[child_rel], encoding="utf-8")
            elif child_rel in override_ancestors and child.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                _populate(child, target, child_rel)
            else:
                target.symlink_to(child)

    _populate(ROOT, dst_root, "")

    for rel_key, content in overrides.items():
        out_path = dst_root / rel_key
        if not out_path.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(content, encoding="utf-8")

    return dst_root


def test_source_hygiene_zero_hash_and_zero_em_en_dashes():
    verifier_src = VERIFIER_PATH.read_text(encoding="utf-8")
    self_src = SELF_PATH.read_text(encoding="utf-8")
    audit_md = AUDIT_DOC_PATH.read_text(encoding="utf-8")
    sub_md = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")

    assert H not in verifier_src, f"unexpected {H!r} character in {VERIFIER_PATH.name}"
    assert H not in self_src, f"unexpected {H!r} character in {SELF_PATH.name}"

    for label, text in (
        ("scripts/verify_submission_doc.py", verifier_src),
        ("tests/test_submission_doc.py", self_src),
        ("docs/SUBMISSION-AUDIT.md", audit_md),
        ("docs/SUBMISSION.md", sub_md),
    ):
        assert EM_DASH not in text, f"unexpected em dash in {label}"
        assert EN_DASH not in text, f"unexpected en dash in {label}"


def test_real_repo_passes_cli_and_programmatic_api(capsys):
    assert verifier.audit_repo is verifier.verify_repo
    assert verifier.CHECK_POST_EDD4_ADVISORY == verifier.CHECK_POST_EDD4_SYNC

    results = verifier.verify_repo(ROOT)
    assert len(results) == 4
    by_name = {r.name: r for r in results}

    assert by_name[verifier.CHECK_AQ_STRUCTURE].status == "PASS"
    assert by_name[verifier.CHECK_AQ_NUMBERS].status == "PASS"
    assert by_name[verifier.CHECK_GEMINI_PROV].status == "PASS"
    assert by_name[verifier.CHECK_POST_EDD4_SYNC].status == "PASS"
    assert by_name[verifier.CHECK_POST_EDD4_SYNC].details == []

    rc_json = verifier.main(["--root", str(ROOT), "--json"])
    out_json = capsys.readouterr().out
    payload = json.loads(out_json)
    assert rc_json == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 2.0
    assert all(item["status"] == "PASS" for item in payload["results"])

    rc_txt = verifier.main(["--root", str(ROOT)])
    out_txt = capsys.readouterr().out
    assert rc_txt == 0
    assert "SUMMARY: 4 PASS, 0 WARN, 0 FAIL" in out_txt


def test_submission_audit_doc_links_commands_and_refresh_ledger():
    assert AUDIT_DOC_PATH.is_file()
    audit_txt = AUDIT_DOC_PATH.read_text(encoding="utf-8")

    for required_token in (
        "1bc3e281",
        "cf394894",
        "58716742",
        "aa1c679e",
        "5f9b3297",
        "266bca3b",
        "eadf970a",
        "afterquery-final",
        "afterquery-submit",
        "afterquery-submit-2",
        "a8f99c2537c91d72",
        "4bf5f8e8e48b",
        "587167429aab",
        "65% [24%, 98%]",
        "72% [52%, 91%]",
        "101% [79%, 140%]",
        "93%",
        "116%",
        "131%",
        "+0.626",
        "9 valid trials",
        "68% [32%, 100%]",
        "75% [56%, 93%]",
        "1,051 of 1,061",
        "53,889",
        "1,021 of 1,031",
        "51,814",
        "1,034",
        "80 of 80",
        "18 of 18",
        "587",
        "42",
        "29,150",
        "-0.050 +/- 0.049",
        "linux_x86_64_afterquery_final_1bc3e281.log.txt",
    ):
        assert required_token in audit_txt, f"docs/SUBMISSION-AUDIT.md missing '{required_token}'"

    stripped = hygiene_mod._strip_code_preserving_lines(audit_txt)
    for label, rx in hygiene_mod.STALE_PR41_PATTERNS:
        assert rx.search(stripped) is None, f"stale token {label!r} in docs/SUBMISSION-AUDIT.md"

    link_count = 0
    for m in hygiene_mod.MD_PLAIN_LINK_RX.finditer(stripped):
        raw_target = (m.group(1) or m.group(2) or "").strip()
        if any(raw_target.lower().startswith(s) for s in hygiene_mod.EXTERNAL_SCHEMES):
            continue
        link_count += 1
        path_part = unquote(raw_target.split(H, 1)[0]).strip()
        resolved = Path(os.path.normpath(str(AUDIT_DOC_PATH.parent / path_part)))
        assert resolved.exists(), f"broken link in docs/SUBMISSION-AUDIT.md: {raw_target}"
    assert link_count >= 25

    cmd_results = doc_cmd_mod.verify_repo(ROOT, docs=("docs/SUBMISSION-AUDIT.md", "docs/SUBMISSION.md"))
    failed_cmd = [r for r in cmd_results if r.status == "FAIL"]
    assert not failed_cmd, f"verify_doc_commands failed on submission docs: {failed_cmd}"


@pytest.mark.parametrize(
    ("case_id", "old_str", "new_str", "expected_detail_substr"),
    [
        ("missing_project_name", "Project name: Canary", "Project title: Canary", "Project name: Canary"),
        (
            "bad_tagline_count",
            "Tagline (58 chars):",
            "Tagline (99 chars):",
            "Tagline stated (99 chars)",
        ),
        (
            "bad_desc_count",
            "Description (591 chars):",
            "Description (400 chars):",
            "Description stated (400 chars)",
        ),
        (
            "desc_delta_over_5",
            "Description (591 chars):",
            "Description (585 chars):",
            "Description stated (585 chars)",
        ),
        (
            "missing_track",
            "Track: AfterQuery - Break the Agent (main track)",
            "Category: Break the Agent",
            "Track: AfterQuery",
        ),
        (
            "missing_section_5",
            f"{H}{H} 5. Rubric: Reward integrity (25)",
            f"{H}{H} Reward integrity",
            f"{H}{H} 5.",
        ),
        (
            "broken_relative_link",
            "[docs/DEMO.md](DEMO.md)",
            "[docs/MISSING.md](MISSING_DOES_NOT_EXIST.md)",
            "broken relative link",
        ),
        (
            "missing_backtick_file",
            "(`canary/env.py`)",
            "(`canary/nonexistent_module_xyz.py`)",
            "canary/nonexistent_module_xyz.py",
        ),
    ],
)
def test_tamper_afterquery_structure_and_links_fails(
    opencode_tmp: Path,
    capsys,
    case_id: str,
    old_str: str,
    new_str: str,
    expected_detail_substr: str,
):
    orig = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")
    assert old_str in orig
    tampered = orig.replace(old_str, new_str, 1)
    synth = _make_overlay_root(opencode_tmp, case_id, {"docs/SUBMISSION.md": tampered})

    res = verifier.check_afterquery_structure(synth)
    assert res.status == "FAIL"
    assert any(expected_detail_substr in d for d in res.details), res.details

    rc = verifier.main(["--root", str(synth), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


@pytest.mark.parametrize(
    ("case_id", "old_str", "new_str"),
    [
        ("tamper_raw_ratio", "65% [24%, 98%]", "69% [24%, 98%]"),
        ("tamper_la_ratio", "72% [52%, 91%]", "79% [52%, 91%]"),
        ("tamper_raw_ci", "65% [24%, 98%]", "65% [29%, 98%]"),
        ("tamper_paired_diff", "-0.177 \u00b1 0.194", "-0.199 \u00b1 0.194"),
        ("tamper_oc_mean", "0.322 \u00b1 0.199", "0.355 \u00b1 0.199"),
        ("tamper_empty_reply_alt", "56% [19%, 87%]", "59% [19%, 87%]"),
        ("tamper_oc_medium", "111% [99%, 127%]", "115% [99%, 127%]"),
        ("tamper_inproc_hard", "95% [62%, 140%]", "99% [62%, 140%]"),
        ("tamper_flash_hard", "22% [-23%, 63%]", "28% [-23%, 63%]"),
        ("tamper_pooled_n32", "68% [32%, 100%]", "71% [32%, 100%]"),
        ("tamper_judge_fp", "893b837616b9", "deadbeef0000"),
        ("tamper_judge_solver", "+0.553 \u00b1 0.093", "+0.653 \u00b1 0.093"),
        ("tamper_oracle_mean", "mean +0.569", "mean +0.619"),
        ("tamper_skill_ladder", "-0.371 \u00b1 0.032", "-0.471 \u00b1 0.032"),
        ("tamper_fa_penalty", "3.39 V", "4.39 V"),
        ("tamper_fa_canaries", "8.5 canaries", "9.5 canaries"),
        ("tamper_replay_count", "1,021 of 1,031", "1,019 of 1,031"),
        ("tamper_replay_steps", "51,814", "51,999"),
        ("tamper_harbor_trials", "80 of 80", "79 of 80"),
        ("tamper_swarm_calls", "4,325 tool calls", "4,999 tool calls"),
        ("tamper_ws4_v3", "-0.147 \u00b1 0.063", "-0.247 \u00b1 0.063"),
        ("tamper_seed_lock_sec", "28 s after", "99 s after"),
        ("tamper_gpt55_ratio", "101% [79%, 140%]", "109% [79%, 140%]"),
        ("tamper_rehearsal_oracle", "oracle +0.506", "oracle +0.606"),
        ("tamper_rehearsal_runs", "93%, 116% and 131%", "91%, 116% and 131%"),
        ("tamper_rehearsal_run3_valid", "9 valid trials", "6 valid trials"),
        ("tamper_behaviour_gpt55_canaries", "gpt-5.5's 17.2", "gpt-5.5's 19.2"),
        ("tamper_redteam_1034", "1,034-attack", "1,099-attack"),
    ],
)
def test_tamper_afterquery_numeric_provenance_fails(
    opencode_tmp: Path,
    capsys,
    case_id: str,
    old_str: str,
    new_str: str,
):
    orig = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")
    assert old_str in orig
    tampered = orig.replace(old_str, new_str)
    synth = _make_overlay_root(opencode_tmp, case_id, {"docs/SUBMISSION.md": tampered})

    res = verifier.check_afterquery_provenance(synth)
    assert res.status == "FAIL"
    assert res.details

    rc = verifier.main(["--root", str(synth), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_tamper_ground_truth_paired_json_triggers_fail(opencode_tmp: Path, capsys):
    paired_rel = "data/runs/committed/v1.4/paired_table_gemini.json"
    rows = json.loads((ROOT / paired_rel).read_text(encoding="utf-8"))
    for row in rows:
        if row.get("tier") == "hard" and row.get("group") == "v1.4/opencode-gemini-4-carbon" and "alternative" not in row.get("label", ""):
            row["ratio"] = 0.51
    synth = _make_overlay_root(
        opencode_tmp,
        "tamper_paired_json",
        {paired_rel: json.dumps(rows)},
    )

    res = verifier.check_afterquery_provenance(synth)
    assert res.status == "FAIL"
    assert any("51%" in d for d in res.details)

    rc = verifier.main(["--root", str(synth)])
    capsys.readouterr()
    assert rc == 1


@pytest.mark.parametrize(
    ("case_id", "old_str", "new_str"),
    [
        ("gem_ladder_eps", "587 paired episodes", "599 paired episodes"),
        ("gem_carbon_high", "106% [94, 126]", "109% [94, 126]"),
        ("gem_flash_high", "88% [51, 138]", "91% [51, 138]"),
        ("gem_sig_errors", "0/628 API errors", "2/628 API errors"),
        ("gem_cache_calls", "29,150 ledgered calls", "29,999 ledgered calls"),
        ("gem_blind_atlas", "Recovers 3 of 5", "Recovers 4 of 5"),
        ("gem_broken_img", "../../results/gemini/frontier.png", "../../results/gemini/missing_chart.png"),
    ],
)
def test_tamper_gemini_submission_provenance_fails(
    opencode_tmp: Path,
    capsys,
    case_id: str,
    old_str: str,
    new_str: str,
):
    orig = GEMINI_SUBMISSION_PATH.read_text(encoding="utf-8")
    assert old_str in orig
    tampered = orig.replace(old_str, new_str)
    synth = _make_overlay_root(opencode_tmp, case_id, {"docs/gemini/SUBMISSION.md": tampered})

    res = verifier.check_gemini_provenance(synth)
    assert res.status == "FAIL"
    assert res.details

    rc = verifier.main(["--root", str(synth), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_description_small_label_delta_tolerated_and_max_bound_enforced(opencode_tmp: Path):
    orig = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")
    small_delta = orig.replace("Description (591 chars):", "Description (595 chars):", 1)
    synth_ok = _make_overlay_root(opencode_tmp, "desc_delta_ok", {"docs/SUBMISSION.md": small_delta})
    res_ok = verifier.check_afterquery_structure(synth_ok)
    assert res_ok.status == "PASS", res_ok.details

    over_max = orig.replace(
        "Doing nothing scores 0; 1,000+ attacks found no exploit.",
        "Doing nothing scores 0; 1,000+ attacks found no exploit. " + ("x" * 450),
        1,
    )
    synth_long = _make_overlay_root(opencode_tmp, "desc_over_max", {"docs/SUBMISSION.md": over_max})
    res_long = verifier.check_afterquery_structure(synth_long)
    assert res_long.status == "FAIL"
    assert any("Description length" in d for d in res_long.details), res_long.details


@pytest.mark.parametrize(
    ("case_id", "old_str", "new_str", "expected_detail_substr"),
    [
        (
            "regress_missing_final_results_heading",
            f"{H}{H} Final results, Sun 15 Nov 09:00",
            f"{H}{H} Old notes",
            "Final results",
        ),
        (
            "regress_missing_supersedes_note",
            "supersedes older lines and TODOs below",
            "notes below",
            "superseding note",
        ),
        (
            "regress_drop_afterquery_final_tag",
            "`afterquery-final` (1bc3e281) is the code freeze",
            "`old-tag` (00000000) is the draft",
            "1bc3e281",
        ),
        (
            "regress_drop_afterquery_submit_tag",
            "`afterquery-submit` adds results and docs only.",
            "branch adds docs.",
            "afterquery-submit",
        ),
        (
            "regress_form_repo_stale_branch",
            "tree/afterquery-submit",
            "tree/justSilas",
            "afterquery-submit",
        ),
        (
            "regress_drop_rehearsal_table",
            "[results/harbor/rehearsal/TABLE.md](../results/harbor/rehearsal/TABLE.md)",
            "[docs/DEMO.md](DEMO.md)",
            "results/harbor/rehearsal/TABLE.md",
        ),
        (
            "regress_drop_rehearsal_ratios",
            "93%, 116% and 131%",
            "80%, 85% and 90%",
            "93%",
        ),
        (
            "regress_drop_judge_non_repro",
            "did not reproduce in the judge path",
            "reproduced in the judge path",
            "did not reproduce in the judge path",
        ),
        (
            "regress_drop_cf394894_sha",
            "cf394894",
            "00000000",
            "cf394894",
        ),
        (
            "regress_drop_gpt55_ratio",
            "101% [79%, 140%]",
            "85% [79%, 140%]",
            "101% [79%, 140%]",
        ),
        (
            "regress_drop_behaviour_compare",
            "8.5 canaries to gpt-5.5's 17.2",
            "many canaries",
            "17.2",
        ),
        (
            "regress_drop_judge_hunt_12_12",
            "12 of 12 held",
            "10 of 12 held",
            "12 of 12 held",
        ),
        (
            "regress_drop_redteam_1034",
            "1,034-attack",
            "500-attack",
            "1,034-attack",
        ),
        (
            "regress_tiebreak_bar_met",
            "is not met; see section 7",
            "is clearly met; see section 7",
            "is not met",
        ),
        (
            "regress_form_drop_harbor_range",
            "93-131%",
            "60-70%",
            "93-131%",
        ),
        (
            "regress_form_drop_gpt55_matches",
            "gpt-5.5 matches the solver",
            "gpt-5.5 trails the solver",
            "gpt-5.5 matches the solver",
        ),
        (
            "regress_em_dash",
            "Track: AfterQuery - Break the Agent",
            f"Track: AfterQuery {EM_DASH} Break the Agent",
            "em dash",
        ),
    ],
)
def test_post_edd4fe6d_sync_fails_on_synthetic_regressions(
    opencode_tmp: Path,
    capsys,
    case_id: str,
    old_str: str,
    new_str: str,
    expected_detail_substr: str,
):
    orig = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")
    assert old_str in orig
    tampered = orig.replace(old_str, new_str)
    synth = _make_overlay_root(opencode_tmp, case_id, {"docs/SUBMISSION.md": tampered})

    res = verifier.check_post_edd4fe6d_sync(synth)
    assert res.status == "FAIL"
    assert any(expected_detail_substr in d for d in res.details), res.details

    rc = verifier.main(["--root", str(synth), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["passed"] is False


def test_post_edd4fe6d_sync_fails_if_demo_md_loses_bar_not_met(opencode_tmp: Path, capsys):
    demo_orig = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    demo_tampered = demo_orig.replace("bar not met", "tiebreak solved").replace("bar NOT met", "tiebreak SOLVED")
    synth = _make_overlay_root(opencode_tmp, "regress_demo_tiebreak", {"docs/DEMO.md": demo_tampered})

    res = verifier.check_post_edd4fe6d_sync(synth)
    assert res.status == "FAIL"
    assert any("DEMO.md" in d for d in res.details), res.details

    rc = verifier.main(["--root", str(synth)])
    capsys.readouterr()
    assert rc == 1
