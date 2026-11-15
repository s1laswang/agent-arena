from __future__ import annotations

from pathlib import Path
import posixpath
import re
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
AUDIT_REL_PATH = "docs/reports/submission_and_doc_sync_audit.md"
AUDIT_PATH = ROOT / AUDIT_REL_PATH

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

BACKTICK_FENCE_RE = re.compile(r"^\s*(`{3,})([^`]*)$")
TILDE_FENCE_RE = re.compile(r"^\s*(~{3,})(.*)$")
INLINE_CODE_RE = re.compile(r"(`+)([^`]+?)\1")
MD_LINK_RE = re.compile(r"\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(((?:[^()\s]|\([^()\s]*\)|[ \t])+)\)")
EXCLUDED_LINK_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:", "javascript:")

REQUIRED_AUDIT_TOKENS = (
    "58716742",
    "afterquery-final",
    "1bc3e281",
    "671ed96",
    "28 s",
    "post-hoc lock",
    "0424db8e",
    "763f22f2",
    "6a74d1a9",
    "6a638ea7",
    "39bbfe1c",
    "37091788",
    "170e80cb",
    "2/2 CI GREEN",
    "protected-paths",
    "test-and-reproduce",
    "PR #3",
    "PR #47",
    "PR #50",
    "PR #52",
    "PR #68",
    "PR #69",
    "PR #72",
    "PR #76",
    "fr8/afterquery/main",
    "docs/reports/frontier_ext30to59_trajectories.md",
    "accuse_ext8_combined.md",
    "tags_ext8_combined.json",
    "scripts/check_frontier_ext_replication.py",
    "tests/test_frontier_ext_combined_parity.py",
    "squash-merge cleanly together",
    "fr8/canary/arena",
    "fr8/afterquery/arena-solver-live",
    "fr8/afterquery/arena-e2e-qa",
    "docs/arena/ui/dom.js",
    "docs/arena/ui/arena.css",
    "docs/arena/index.html",
    "docs/arena/solver_live.py",
    "docs/arena/solver_live.js",
    "tests/test_arena_solver_live.py",
    "docs/arena/share_card.js",
    "scripts/verify_arena_bundle.py",
    "tests/test_arena_share_and_bundle.py",
)


def _extract_relative_md_links(md_rel_path: str, text: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    fence: tuple[str, int] | None = None
    md_dir = posixpath.dirname(md_rel_path)
    for idx, line in enumerate(text.splitlines(), start=1):
        if fence is not None:
            stripped = line.strip()
            fchar, flen = fence
            if len(stripped) >= flen and all(ch == fchar for ch in stripped):
                fence = None
            continue
        m_bt = BACKTICK_FENCE_RE.match(line)
        if m_bt:
            fence = ("`", len(m_bt.group(1)))
            continue
        m_tl = TILDE_FENCE_RE.match(line)
        if m_tl:
            fence = ("~", len(m_tl.group(1)))
            continue
        cleaned = INLINE_CODE_RE.sub(lambda m: " " * len(m.group(0)), line)
        for m_link in MD_LINK_RE.finditer(cleaned):
            raw_target = m_link.group(1).strip()
            if not raw_target:
                continue
            if raw_target.startswith("<") and ">" in raw_target:
                target = raw_target[1:raw_target.index(">")].strip()
            else:
                target = raw_target.split()[0]
            if not target or target.lower().startswith(EXCLUDED_LINK_SCHEMES):
                continue
            path_part = urllib.parse.unquote(target.split(HASH_CHAR, 1)[0].split("?", 1)[0].strip())
            if not path_part:
                continue
            if path_part.startswith("/"):
                resolved = posixpath.normpath(path_part.lstrip("/"))
            else:
                resolved = posixpath.normpath(posixpath.join(md_dir, path_part) if md_dir else path_part)
            out.append((idx, target, resolved))
    return out


def test_submission_doc_sync_audit_has_no_unicode_dashes():
    assert AUDIT_PATH.is_file()
    text = AUDIT_PATH.read_text(encoding="utf-8")
    bad_lines = [
        idx
        for idx, line in enumerate(text.splitlines(), start=1)
        if EM_DASH in line or EN_DASH in line
    ]
    assert bad_lines == []


def test_submission_doc_sync_audit_relative_markdown_links_resolve():
    text = AUDIT_PATH.read_text(encoding="utf-8")
    links = _extract_relative_md_links(AUDIT_REL_PATH, text)
    assert len(links) >= 10
    broken: list[str] = []
    for line_no, target, resolved in links:
        if resolved == ".." or resolved.startswith("../") or not (ROOT / resolved).exists():
            broken.append(f"{AUDIT_REL_PATH}:{line_no}: {target} -> {resolved}")
    assert broken == []


def test_submission_doc_sync_audit_pins_core_invariants():
    text = AUDIT_PATH.read_text(encoding="utf-8")
    missing = [token for token in REQUIRED_AUDIT_TOKENS if token not in text]
    assert missing == []
