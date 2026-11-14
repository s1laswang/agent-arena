from __future__ import annotations

import io
import json
import re
import tokenize
from pathlib import Path

import pytest

from canary.gemini.provenance import (
    COMMIT_RE,
    REQUIRED_ROLES,
    TARGET_MODEL,
    audit_provenance,
    scan_file_secrets,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLES_DOC_PATH = REPO_ROOT / "docs" / "gemini" / "ROLES.md"
SUBMISSION_DOC_PATH = REPO_ROOT / "docs" / "gemini" / "SIX_ROLES_SUBMISSION.md"
PITCH_DOC_PATH = REPO_ROOT / "pitch" / "GEMINI_SIX_ROLES.md"
ALL_DOC_PATHS = (ROLES_DOC_PATH, SUBMISSION_DOC_PATH, PITCH_DOC_PATH)

SUMMARY_MAX_CHARS = 600
ANGLE_OPEN = "\u27e8"
ANGLE_CLOSE = "\u27e9"
EM_DASH = "\u2014"
EN_DASH = "\u2013"
DRAFT_RE = re.compile(r"\bDRAFT\b")
RUN_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.\-/])((?:results/gemini_roles|data/runs/committed)/[A-Za-z0-9_.\-/]+)"
)


def extract_platform_summary(md_text: str) -> str:
    lines = md_text.splitlines()
    start_idx: int | None = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().lower()
            if "platform summary" in heading or "short version" in heading:
                start_idx = idx + 1
                break
    if start_idx is None:
        raise ValueError("Platform Summary section heading not found")
    body_lines: list[str] = []
    for line in lines[start_idx:]:
        if line.strip().startswith("## "):
            break
        body_lines.append(line)
    summary = "\n".join(body_lines).strip()
    if not summary:
        raise ValueError("Platform Summary section is empty")
    return summary


def extract_cited_run_folders(md_text: str) -> list[str]:
    seen: dict[str, None] = {}
    file_exts = {".json", ".jsonl", ".md", ".html", ".png", ".jpg", ".jpeg", ".csv", ".txt", ".py"}
    for match in RUN_PATH_RE.finditer(md_text):
        cleaned = match.group(1).rstrip(".,;:)/")
        if cleaned in {"results/gemini_roles", "data/runs/committed", "data/runs/committed/v1.4/reference"}:
            continue
        if Path(cleaned).suffix.lower() in file_exts:
            continue
        if cleaned:
            seen[cleaned] = None
    return list(seen.keys())


def validate_markdown_cleanliness(doc_path: Path, root: Path) -> list[str]:
    text = doc_path.read_text(encoding="utf-8")
    errors: list[str] = []
    if ANGLE_OPEN in text or ANGLE_CLOSE in text:
        errors.append("angle_placeholder_found")
    if DRAFT_RE.search(text):
        errors.append("draft_marker_found")
    if EM_DASH in text:
        errors.append("em_dash_found")
    if EN_DASH in text:
        errors.append("en_dash_found")
    if "no api key yet" in text.lower():
        errors.append("outdated_no_api_key_note")
    leaks = scan_file_secrets(doc_path, root)
    if leaks:
        errors.append("secret_leak_found")
    return errors


def validate_submission_run_paths(md_text: str, root: Path) -> tuple[list[str], set[str], list[str]]:
    folders = extract_cited_run_folders(md_text)
    roles_seen: set[str] = set()
    errors: list[str] = []
    if not folders:
        errors.append("no_run_folders_cited")
        return folders, roles_seen, errors

    for rel in folders:
        run_dir = root / rel
        if not run_dir.is_dir():
            errors.append(f"missing_dir:{rel}")
            continue
        meta_path = run_dir / "meta.json"
        if not meta_path.is_file():
            errors.append(f"missing_meta:{rel}")
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            errors.append(f"invalid_meta_json:{rel}")
            continue
        if not isinstance(meta, dict):
            errors.append(f"non_dict_meta:{rel}")
            continue
        model_id = meta.get("model_id") or meta.get("model")
        if model_id != TARGET_MODEL:
            errors.append(f"wrong_model_id:{rel}:{model_id!r}")
            continue
        commit = str(meta.get("commit") or meta.get("git_sha") or "").strip()
        if not COMMIT_RE.match(commit):
            errors.append(f"invalid_commit:{rel}:{commit!r}")
            continue
        if commit not in md_text and commit[:7] not in md_text:
            errors.append(f"uncited_commit:{rel}:{commit[:10]}")
            continue
        role = meta.get("role")
        if isinstance(role, str) and role in REQUIRED_ROLES:
            roles_seen.add(role)
        elif rel.startswith("data/runs/committed/v1.4/gemini-4-carbon/"):
            roles_seen.add("investigators")

    return folders, roles_seen, errors


@pytest.mark.parametrize("doc_path", ALL_DOC_PATHS)
def test_docs_cleanliness(doc_path: Path) -> None:
    assert doc_path.is_file(), f"Missing expected document: {doc_path}"
    errs = validate_markdown_cleanliness(doc_path, REPO_ROOT)
    assert errs == [], f"{doc_path} failed cleanliness checks: {errs}"


def test_submission_platform_summary_char_limit() -> None:
    text = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")
    summary = extract_platform_summary(text)
    assert 100 <= len(summary) <= SUMMARY_MAX_CHARS, (
        f"Platform Summary length {len(summary)} outside [100, {SUMMARY_MAX_CHARS}]"
    )


@pytest.mark.parametrize(
    ("doc_path", "min_folders"),
    [
        (ROLES_DOC_PATH, 55),
        (SUBMISSION_DOC_PATH, 6),
        (PITCH_DOC_PATH, 6),
    ],
)
def test_cited_run_folders_exist_use_carbon_and_cite_commits(doc_path: Path, min_folders: int) -> None:
    text = doc_path.read_text(encoding="utf-8")
    folders, roles_seen, errs = validate_submission_run_paths(text, REPO_ROOT)
    assert errs == [], f"Run folder validation errors in {doc_path.name}: {errs}"
    assert len(folders) >= min_folders
    missing_roles = [r for r in REQUIRED_ROLES if r not in roles_seen]
    assert missing_roles == [], f"Missing cited run folders in {doc_path.name} for roles: {missing_roles}"


def test_docs_cited_runs_match_provenance_entries() -> None:
    prov = audit_provenance(REPO_ROOT)
    assert prov["verified"] is True
    by_dir = {r["run_dir"]: r for r in prov["runs"] if r["verified"]}

    roles_txt = ROLES_DOC_PATH.read_text(encoding="utf-8")
    cited = extract_cited_run_folders(roles_txt)
    assert 55 <= len(cited) <= prov["totals"]["verified_runs"]
    for rel in cited:
        assert rel in by_dir, f"Cited run {rel} not verified in audit_provenance"
        entry = by_dir[rel]
        assert f"{entry['tokens_in']:,}" in roles_txt
        assert f"{entry['tokens_out']:,}" in roles_txt


def test_submission_and_pitch_required_sections_present() -> None:
    sub_text = SUBMISSION_DOC_PATH.read_text(encoding="utf-8")
    sub_lower = sub_text.lower()
    assert "## platform summary" in sub_lower
    assert "problem" in sub_lower and "why it matters" in sub_lower
    assert "how the gemini api is integrated" in sub_lower
    assert "innovative" in sub_lower
    assert "why gemini is essential" in sub_lower
    for doc_path in ALL_DOC_PATHS:
        txt = doc_path.read_text(encoding="utf-8")
        for role in REQUIRED_ROLES:
            assert role in txt, f"Missing required role identifier {role!r} in {doc_path.name}"
        assert TARGET_MODEL in txt
        assert "canary.gemini.provenance" in txt
        assert "canary.gemini.roles_dashboard" in txt


def test_validator_rejects_placeholders_dashes_keys_and_bad_runs(tmp_path: Path) -> None:
    good_sha = "f307290845c4a0040feebf4e146d2ec3aa1596c7"
    good_run = tmp_path / "results" / "gemini_roles" / "world_text" / "sample-carbon"
    good_run.mkdir(parents=True)
    (good_run / "meta.json").write_text(
        json.dumps({"role": "world_text", "model_id": TARGET_MODEL, "commit": good_sha}),
        encoding="utf-8",
    )
    uncited_sha_run = tmp_path / "results" / "gemini_roles" / "failure_analyst" / "uncited-sha"
    uncited_sha_run.mkdir(parents=True)
    (uncited_sha_run / "meta.json").write_text(
        json.dumps({"role": "failure_analyst", "model_id": TARGET_MODEL, "commit": "11111112222222"}),
        encoding="utf-8",
    )
    wrong_run = tmp_path / "results" / "gemini_roles" / "adaptive_mole" / "wrong-model"
    wrong_run.mkdir(parents=True)
    (wrong_run / "meta.json").write_text(
        json.dumps({"role": "adaptive_mole", "model_id": "gemini-3.8-flash", "commit": good_sha}),
        encoding="utf-8",
    )

    bad_doc = tmp_path / "SIX_ROLES_SUBMISSION.md"
    secret_tok = "AIza" + "Sy" + "DummyKeyValue0000000099"
    bad_doc.write_text(
        f"# Title\nDRAFT v0 {ANGLE_OPEN}N{ANGLE_CLOSE} {EM_DASH} {EN_DASH} no API key yet {secret_tok}\n\n"
        f"## Platform Summary\n{'x' * 601}\n\n"
        "## Runs\n"
        f"- `results/gemini_roles/world_text/sample-carbon` (`{good_sha}`)\n"
        "- `results/gemini_roles/failure_analyst/uncited-sha`\n"
        f"- `results/gemini_roles/adaptive_mole/wrong-model` (`{good_sha}`)\n"
        "- `results/gemini_roles/investigators/missing-folder`\n",
        encoding="utf-8",
    )

    clean_errs = validate_markdown_cleanliness(bad_doc, tmp_path)
    assert "angle_placeholder_found" in clean_errs
    assert "draft_marker_found" in clean_errs
    assert "em_dash_found" in clean_errs
    assert "en_dash_found" in clean_errs
    assert "outdated_no_api_key_note" in clean_errs
    assert "secret_leak_found" in clean_errs

    summary = extract_platform_summary(bad_doc.read_text(encoding="utf-8"))
    assert len(summary) == 601

    folders, roles_seen, run_errs = validate_submission_run_paths(
        bad_doc.read_text(encoding="utf-8"), tmp_path
    )
    assert len(folders) == 4
    assert roles_seen == {"world_text"}
    assert any(e.startswith("uncited_commit:") for e in run_errs)
    assert any(e.startswith("wrong_model_id:") for e in run_errs)
    assert "missing_dir:results/gemini_roles/investigators/missing-folder" in run_errs


def test_test_file_has_no_comments_dashes_or_keys() -> None:
    self_path = Path(__file__).resolve()
    text = self_path.read_text(encoding="utf-8")
    assert EM_DASH not in text
    assert EN_DASH not in text
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"Found comments in {self_path}: {comments}"
    assert scan_file_secrets(self_path, REPO_ROOT) == []
