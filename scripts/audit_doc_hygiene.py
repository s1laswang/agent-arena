from __future__ import annotations

import argparse
import fnmatch
import functools
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)

CHECK_ANCHORS = "Markdown Anchor Fragment Check"
CHECK_IMAGES = "HTML <img> & Markdown Image Asset Audit"
CHECK_TRACKED_TARGETS = "Tracked vs Gitignored Link Target Audit"
CHECK_STALE_PR41 = "Post-PR41 Stale Number Guard"
CHECK_PORTABILITY_AND_ENCODING = "Shell Portability, CRLF & Conflict-Marker Audit"
CHECK_MAKEFILE_DIFFUTILS = "Makefile diffutils Portability Audit"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_ANCHORS,
    CHECK_IMAGES,
    CHECK_TRACKED_TARGETS,
    CHECK_STALE_PR41,
    CHECK_PORTABILITY_AND_ENCODING,
)

ACTIVE_JUDGE_DOCS: tuple[str, ...] = (
    "README.md",
    "JUDGE_QUICKSTART.md",
    "docs/JUDGE-WALKTHROUGH.md",
    "docs/PEER-REVIEW-QA.md",
    "docs/REPRODUCIBILITY.md",
    "docs/DEMO.md",
    "docs/NUMBER-PROVENANCE-INDEX.md",
    "docs/EXPLOITS.md",
    "docs/SUBMISSION.md",
    "docs/gemini/SUBMISSION.md",
    "pitch/GEMINI.md",
)

TEXT_AUDIT_EXTENSIONS: frozenset[str] = frozenset(
    {".md", ".py", ".sh", ".toml", ".yml", ".yaml"}
)

SKIP_WALK_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".venv",
        "venv",
        "node_modules",
    }
)

EXTERNAL_SCHEMES: tuple[str, ...] = (
    "http://",
    "https://",
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    "//",
)

FENCE_OPEN_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})")
HTML_COMMENT_RX = re.compile(r"<!--[\s\S]*?-->")
INLINE_CODE_RX = re.compile(r"(`+)(?:(?!\1)[^\n])+\1")
ATX_HEADING_RX = re.compile(r"^\s{0,3}\x23{1,6}(?:[ \t]+(.*?))?(?:[ \t]+\x23+[ \t]*)?$")
SETEXT_UNDERLINE_RX = re.compile(r"^\s{0,3}(?:={3,}|-{3,})\s*$")
SETEXT_DISQUALIFY_RX = re.compile(r"^\s*(?:[|>*+-]|\d+[.)]|\x23|<)")
HEADING_MD_LINK_RX = re.compile(r"!?\[([^\[\]]*)\]\([^)]*\)")
HTML_TAG_RX = re.compile(r"<[^>]+>")
SLUG_STRIP_PUNCT_RX = re.compile(r"[^\w\s-]")
EXPLICIT_HTML_ID_RX = re.compile(
    r"<[A-Za-z][^>]*?\b(?:id|name)\s*=\s*(?:\"([^\"]+)\"|'([^']+)')",
    re.IGNORECASE,
)

MD_IMAGE_RX = re.compile(
    r"!\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\((?:<([^>\n]*)>(?:\s+[^)\n]*)?|((?:[^()\n]|\([^()\n]*\))*))\)"
)
MD_PLAIN_LINK_RX = re.compile(
    r"(?<!!)\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\((?:<([^>\n]*)>(?:\s+[^)\n]*)?|((?:[^()\n]|\([^()\n]*\))*))\)"
)
HTML_IMG_TAG_RX = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
HTML_IMG_SRC_RX = re.compile(
    r"\bsrc\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>\"']+))",
    re.IGNORECASE,
)
LINE_ANCHOR_RX = re.compile(r"^L([1-9]\d*)(?:-L([1-9]\d*))?$")

STALE_PR41_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "51-attacker",
        re.compile(r"(?<![0-9])51[*_`]*[-\s]+[*_`]*attacker\b", re.IGNORECASE),
    ),
    (
        "51-agent swarm",
        re.compile(r"(?<![0-9])51[*_`]*[-\s]+[*_`]*agent[*_`]*\s+[*_`]*swarm\b", re.IGNORECASE),
    ),
    (
        "35 whitebox",
        re.compile(r"(?<![0-9.,])35[*_`]*[-\s]+[*_`]*whitebox\b", re.IGNORECASE),
    ),
    (
        "1,789 tool calls",
        re.compile(r"(?<![0-9])1,?789[*_`]*\s+[*_`]*tool\s+calls?\b", re.IGNORECASE),
    ),
    (
        "68% of solver luck-adjusted",
        re.compile(
            r"(?<![0-9.])68%[*_`]*\s+of\s+(?:the\s+)?solver[*_`]*[\s,()]*luck[-\s]+adjusted\b",
            re.IGNORECASE,
        ),
    ),
    (
        "<PLACEHOLDER",
        re.compile(r"(?:<|\u27e8)\s*PLACEHOLDER\b"),
    ),
    (
        "Three retired builds publish their signing key",
        re.compile(r"Three\s+retired\s+builds\s+publish\s+their\s+signing\s+key", re.IGNORECASE),
    ),
    (
        "all 31 committed Harbor trials",
        re.compile(r"\ball\s+[*_`]*31[*_`]*\s+committed\s+Harbor\s+trials\b", re.IGNORECASE),
    ),
)

EXPLOITS_FULL_HISTORY_HEADING_RX = re.compile(
    r"^\s{0,3}\x23{1,6}\s+Full\s+history\b",
    re.IGNORECASE | re.MULTILINE,
)
EXPLOITS_ROW_49_RX = re.compile(r"^\s*\|\s*49\s*\|")

CONFLICT_FAST_TOKENS: tuple[str, ...] = ("<" * 7, "=" * 7, ">" * 7)
CONFLICT_MARKER_RX = re.compile(r"^(?:<{7} |={7}[ \t]*$|>{7} )")
SHEBANG_RX = re.compile(r"^\x23!\s*/\S+")
HEREDOC_START_RX = re.compile(
    r"(?<!<)<<(-?)(?!<)\s*(?:['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]|\\?([A-Za-z_][A-Za-z0-9_]*))"
)
SHELL_PKILL_RX = re.compile(r"\bpkill\b")
SHELL_DIFFUTILS_RX = re.compile(
    r"(?:^|[;|&({`]|\$\("
    r"|(?:^|[\s;|&({`])(?:if|then|else|elif|do|while|until|time|exec|env|nohup)\b"
    r"|(?:^|[\s;|&({`])!)"
    r"\s*(cmp|diff)(?=\s|[;|&)}`]|$)"
)
SHELL_IF_WORD_RX = re.compile(r"(?:^|[\s;|&({`])if(?=\s|$)")
SHELL_FI_WORD_RX = re.compile(r"(?:^|[\s;|&({`])fi(?=\s|[;|&)}`]|$)")


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class _LinkRef:
    md_file: Path
    md_rel: str
    lineno: int
    kind: str
    raw_target: str


@dataclass
class _ScanContext:
    root: Path
    md_files: list[Path]
    refs: list[_LinkRef]
    read_errors: list[str]
    slug_cache: dict[Path, set[str]] = field(default_factory=dict)


def _has_dot_git(root: Path) -> bool:
    dot_git = root / ".git"
    return dot_git.exists() or dot_git.is_symlink()


def _git_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    ceiling = str(root.resolve().parent)
    existing = env.get("GIT_CEILING_DIRECTORIES", "")
    env["GIT_CEILING_DIRECTORIES"] = f"{ceiling}{os.pathsep}{existing}" if existing else ceiling
    return env


def _git_ls_files(root: Path) -> list[str] | None:
    if not _has_dot_git(root):
        return None
    try:
        proc = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.decode("utf-8", errors="replace")
    return [entry for entry in raw.split("\0") if entry]


def _git_is_ignored(root: Path, rel_path: str) -> tuple[bool, bool]:
    if not _has_dot_git(root):
        return False, False
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "-q", rel_path],
            cwd=root,
            env=_git_env(root),
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False, False
    if proc.returncode not in (0, 1):
        return False, False
    return True, proc.returncode == 0


def _git_ignored_batch(root: Path, rel_paths: list[str]) -> set[str] | None:
    if not _has_dot_git(root):
        return None
    if not rel_paths:
        return set()
    unique_paths = sorted(set(rel_paths))
    try:
        proc = subprocess.run(
            ["git", "check-ignore", "--stdin"],
            cwd=root,
            env=_git_env(root),
            input="\n".join(unique_paths) + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode in (0, 1):
        return {ln for ln in proc.stdout.splitlines() if ln}
    ignored: set[str] = set()
    for p in unique_paths:
        ok, is_ig = _git_is_ignored(root, p)
        if not ok:
            return None
        if is_ig:
            ignored.add(p)
    return ignored


def _parse_gitignore_fallback_rules(root: Path) -> list[tuple[bool, bool, bool, str]]:
    gi_path = root / ".gitignore"
    if not gi_path.is_file():
        return []
    try:
        lines = gi_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rules: list[tuple[bool, bool, bool, str]] = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        negated = stripped.startswith("!")
        body = stripped[1:].strip() if negated else stripped
        if not body:
            continue
        dir_only = body.endswith("/")
        pat = body.strip("/")
        if not pat:
            continue
        anchored = ("/" in pat) or raw.lstrip(" !").startswith("/")
        rules.append((negated, dir_only, anchored, pat))
    return rules


@functools.lru_cache(maxsize=512)
def _compile_anchored_gitignore_pat(pat: str) -> re.Pattern[str]:
    parts: list[str] = []
    i = 0
    n = len(pat)
    while i < n:
        if pat[i : i + 3] == "**/":
            parts.append("(?:.+/)?")
            i += 3
        elif pat[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif pat[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif pat[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(pat[i]))
            i += 1
    return re.compile("".join(parts))


def _gitignore_pat_matches(pat: str, rel_pos: str, name: str, anchored: bool) -> bool:
    if not anchored:
        return fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(rel_pos, pat)
    if "**/" in pat and _gitignore_pat_matches(pat.replace("**/", ""), rel_pos, name, True):
        return True
    return _compile_anchored_gitignore_pat(pat).fullmatch(rel_pos) is not None


def _fallback_is_ignored(
    rules: list[tuple[bool, bool, bool, str]],
    rel_path: str,
    is_dir: bool = False,
) -> bool:
    if not rules:
        return False
    clean = rel_path.strip("/")
    if not clean or clean == ".":
        return False
    segments = clean.split("/")
    total = len(segments)
    for depth in range(1, total + 1):
        sub = "/".join(segments[:depth])
        sub_name = segments[depth - 1]
        sub_is_dir = True if depth < total else is_dir
        ignored = False
        for negated, dir_only, anchored, pat in rules:
            if dir_only and not sub_is_dir:
                continue
            if _gitignore_pat_matches(pat, sub, sub_name, anchored):
                ignored = not negated
        if ignored and depth < total:
            return True
        if depth == total:
            return ignored
    return False


def _collect_markdown_files(root: Path) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []

    def _add(p: Path) -> None:
        if not p.is_file():
            return
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            ordered.append(p)

    _add(root / "README.md")
    _add(root / "JUDGE_QUICKSTART.md")
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for p in sorted(docs_dir.rglob("*.md")):
            _add(p)
    _add(root / "harbor" / "README.md")
    pitch_dir = root / "pitch"
    if pitch_dir.is_dir():
        for p in sorted(pitch_dir.rglob("*.md")):
            _add(p)
    results_dir = root / "results"
    if results_dir.is_dir():
        for p in sorted(results_dir.rglob("*.md")):
            if "latest" in p.relative_to(results_dir).parts:
                continue
            _add(p)
    return ordered


def _strip_fences_and_comments(md_text: str) -> str:
    cleaned_lines: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for raw_line in md_text.splitlines():
        m = FENCE_OPEN_RX.match(raw_line)
        if not in_fence:
            if m:
                marker = m.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                cleaned_lines.append("")
                continue
            cleaned_lines.append(raw_line)
        else:
            if m:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            cleaned_lines.append("")
    joined = "\n".join(cleaned_lines)
    return HTML_COMMENT_RX.sub(lambda match: "\n" * match.group(0).count("\n"), joined)


def _strip_code_preserving_lines(md_text: str) -> str:
    without_fences = _strip_fences_and_comments(md_text)
    return "\n".join(
        (INLINE_CODE_RX.sub("", line) if "`" in line else line)
        for line in without_fences.split("\n")
    )


def slugify_github_heading(raw_heading: str) -> str:
    txt = HEADING_MD_LINK_RX.sub(r"\1", raw_heading)
    txt = HTML_TAG_RX.sub("", txt)
    txt = txt.strip().lower()
    txt = SLUG_STRIP_PUNCT_RX.sub("", txt)
    return re.sub(r"[ \t]", "-", txt)


def extract_heading_slugs(md_text: str) -> set[str]:
    cleaned = _strip_fences_and_comments(md_text)
    lines = cleaned.split("\n")
    counts: dict[str, int] = {}
    used: set[str] = set()

    def _register(raw_heading: str) -> None:
        base = slugify_github_heading(raw_heading)
        if not base:
            return
        idx = counts.get(base, 0)
        candidate = base if idx == 0 else f"{base}-{idx}"
        while candidate in used:
            idx += 1
            candidate = f"{base}-{idx}"
        counts[base] = idx + 1
        used.add(candidate)

    prev_plain: str | None = None
    for line in lines:
        atx = ATX_HEADING_RX.match(line)
        if atx:
            _register(atx.group(1) or "")
            prev_plain = None
            continue
        if prev_plain is not None and SETEXT_UNDERLINE_RX.match(line):
            _register(prev_plain)
            prev_plain = None
            continue
        stripped = line.strip()
        if stripped and not SETEXT_DISQUALIFY_RX.match(line):
            prev_plain = stripped
        else:
            prev_plain = None

    explicit_ids: set[str] = set()
    for m in EXPLICIT_HTML_ID_RX.finditer(cleaned):
        anchor_id = (m.group(1) or m.group(2) or "").strip()
        if anchor_id:
            explicit_ids.add(anchor_id)
    return used | explicit_ids


def _parse_md_dest(angle_group: str | None, paren_group: str | None) -> str:
    if angle_group is not None:
        return angle_group.strip()
    raw = (paren_group or "").strip()
    if not raw:
        return ""
    return raw.split()[0].strip()


def _is_external_target(target: str) -> bool:
    lower = target.lower()
    return lower.startswith(EXTERNAL_SCHEMES)


def _scan_markdown_refs(root: Path) -> _ScanContext:
    root_resolved = root.resolve()
    md_files = _collect_markdown_files(root_resolved)
    refs: list[_LinkRef] = []
    read_errors: list[str] = []

    for md_file in md_files:
        md_rel = md_file.relative_to(root_resolved).as_posix()
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            read_errors.append(f"{md_rel}: unreadable markdown file ({type(exc).__name__})")
            continue

        stripped_text = _strip_code_preserving_lines(content)
        for m in HTML_IMG_TAG_RX.finditer(stripped_text):
            lineno = 1 + stripped_text.count("\n", 0, m.start())
            src_match = HTML_IMG_SRC_RX.search(m.group(0))
            if src_match is None:
                raw_src = ""
            else:
                raw_src = (
                    src_match.group(1)
                    if src_match.group(1) is not None
                    else (
                        src_match.group(2)
                        if src_match.group(2) is not None
                        else (src_match.group(3) or "")
                    )
                ).strip()
            refs.append(_LinkRef(md_file, md_rel, lineno, "html_img", raw_src))

        for lineno, line in enumerate(stripped_text.split("\n"), 1):
            if "(" not in line or "[" not in line:
                continue
            for img_m in MD_IMAGE_RX.finditer(line):
                dest = _parse_md_dest(img_m.group(1), img_m.group(2))
                refs.append(_LinkRef(md_file, md_rel, lineno, "md_img", dest))
            line_no_imgs = MD_IMAGE_RX.sub("img", line)
            for link_m in MD_PLAIN_LINK_RX.finditer(line_no_imgs):
                dest = _parse_md_dest(link_m.group(1), link_m.group(2))
                if not dest:
                    continue
                refs.append(_LinkRef(md_file, md_rel, lineno, "md_link", dest))

    return _ScanContext(
        root=root_resolved,
        md_files=md_files,
        refs=refs,
        read_errors=read_errors,
    )


def _slugs_for_file(path: Path, cache: dict[Path, set[str]]) -> set[str] | None:
    rp = path.resolve()
    if rp in cache:
        return cache[rp]
    if not rp.is_file():
        return None
    try:
        text = rp.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    slugs = extract_heading_slugs(text)
    cache[rp] = slugs
    return slugs


def check_markdown_anchors(root: Path = ROOT, *, _ctx: _ScanContext | None = None) -> CheckResult:
    name = CHECK_ANCHORS
    ctx = _ctx if _ctx is not None else _scan_markdown_refs(root)
    if not ctx.md_files:
        return CheckResult(name, "FAIL", "no markdown files found to scan")

    failures: list[str] = list(ctx.read_errors)
    anchor_count = 0

    for ref in ctx.refs:
        if ref.kind != "md_link":
            continue
        target = ref.raw_target
        if not target or _is_external_target(target) or HASH_CHAR not in target:
            continue

        anchor_count += 1
        path_raw, frag_raw = target.split(HASH_CHAR, 1)
        frag = unquote(frag_raw).strip()
        if not frag:
            failures.append(f"{ref.md_rel}:{ref.lineno}: empty anchor fragment in '{target}'")
            continue

        path_part = unquote(path_raw.split("?", 1)[0]).strip()
        if not path_part:
            target_file = ref.md_file.resolve()
            target_rel = ref.md_rel
        else:
            target_file = (ref.md_file.parent / path_part).resolve()
            try:
                target_rel = target_file.relative_to(ctx.root).as_posix()
            except ValueError:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: anchor link '{target}' resolves outside root"
                )
                continue

        if not target_file.is_file():
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: broken anchor link '{target}' (missing file '{target_rel}')"
            )
            continue

        suffix = target_file.suffix.lower()
        if suffix in {".md", ".markdown"}:
            slugs = _slugs_for_file(target_file, ctx.slug_cache)
            if slugs is None:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: unreadable anchor target file '{target_rel}'"
                )
                continue
            if frag not in slugs:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: broken anchor '{target}' "
                    f"(heading slug '{frag}' not found in {target_rel})"
                )
        elif suffix in {".html", ".htm"}:
            try:
                html_txt = target_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: unreadable HTML anchor target '{target_rel}'"
                )
                continue
            html_ids = {
                (m.group(1) or m.group(2) or "").strip()
                for m in EXPLICIT_HTML_ID_RX.finditer(html_txt)
            }
            if frag not in html_ids:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: broken HTML anchor '{target}' "
                    f"(id '{frag}' not found in {target_rel})"
                )
        else:
            lm = LINE_ANCHOR_RX.match(frag)
            if lm is None:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: unsupported anchor '{target}' on non-markdown file '{target_rel}'"
                )
                continue
            start_ln = int(lm.group(1))
            end_ln = int(lm.group(2)) if lm.group(2) is not None else start_ln
            try:
                total_lines = len(target_file.read_text(encoding="utf-8", errors="replace").splitlines())
            except OSError:
                failures.append(f"{ref.md_rel}:{ref.lineno}: unreadable target file '{target_rel}'")
                continue
            if start_ln > end_ln or end_ln > max(1, total_lines):
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: line anchor '{target}' out of range for '{target_rel}' ({total_lines} lines)"
                )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} broken markdown anchor(s) across {len(ctx.md_files)} file(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"scanned {len(ctx.md_files)} file(s), {anchor_count} anchor link(s); 0 broken",
    )


def check_image_assets(root: Path = ROOT, *, _ctx: _ScanContext | None = None) -> CheckResult:
    name = CHECK_IMAGES
    ctx = _ctx if _ctx is not None else _scan_markdown_refs(root)
    if not ctx.md_files:
        return CheckResult(name, "FAIL", "no markdown files found to scan")

    failures: list[str] = list(ctx.read_errors)
    existing_candidates: list[tuple[_LinkRef, str]] = []
    image_count = 0

    for ref in ctx.refs:
        if ref.kind not in {"html_img", "md_img"}:
            continue
        target = ref.raw_target
        if not target:
            image_count += 1
            failures.append(f"{ref.md_rel}:{ref.lineno}: empty image src in {ref.kind}")
            continue
        if _is_external_target(target):
            continue

        image_count += 1
        path_part = unquote(target.split(HASH_CHAR, 1)[0].split("?", 1)[0]).strip()
        if not path_part:
            failures.append(f"{ref.md_rel}:{ref.lineno}: image src '{target}' has no file path")
            continue

        resolved = (ref.md_file.parent / path_part).resolve()
        try:
            rel_target = resolved.relative_to(ctx.root).as_posix()
        except ValueError:
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: image asset '{target}' resolves outside root"
            )
            continue

        if not resolved.exists() or not resolved.is_file():
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: missing image asset '{target}' ('{rel_target}')"
            )
            continue

        try:
            size = resolved.stat().st_size
        except OSError as exc:
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: unreadable image asset '{rel_target}' ({type(exc).__name__})"
            )
            continue

        if size <= 0:
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: empty image asset '{target}' ('{rel_target}', 0 bytes)"
            )
            continue

        existing_candidates.append((ref, rel_target))

    warnings: list[str] = []
    if existing_candidates:
        ignored_set = _git_ignored_batch(ctx.root, [rel for _, rel in existing_candidates])
        if ignored_set is not None:
            for ref, rel_target in existing_candidates:
                if rel_target in ignored_set:
                    warnings.append(
                        f"{ref.md_rel}:{ref.lineno}: image asset '{ref.raw_target}' is gitignored ('{rel_target}')"
                    )
        else:
            fallback_rules = _parse_gitignore_fallback_rules(ctx.root)
            for ref, rel_target in existing_candidates:
                if _fallback_is_ignored(fallback_rules, rel_target, is_dir=False):
                    warnings.append(
                        f"{ref.md_rel}:{ref.lineno}: image asset '{ref.raw_target}' matches .gitignore ('{rel_target}')"
                    )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} missing/empty image asset(s) across {len(ctx.md_files)} file(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"scanned {len(ctx.md_files)} file(s), {image_count} local image(s); 0 missing/empty, {len(warnings)} gitignored",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"scanned {len(ctx.md_files)} file(s), {image_count} local image asset(s); all exist, non-empty, not gitignored",
    )


def check_tracked_link_targets(
    root: Path = ROOT,
    *,
    _ctx: _ScanContext | None = None,
    _tracked_list: list[str] | None = None,
    _tracked_loaded: bool = False,
) -> CheckResult:
    name = CHECK_TRACKED_TARGETS
    ctx = _ctx if _ctx is not None else _scan_markdown_refs(root)
    if not ctx.md_files:
        return CheckResult(name, "FAIL", "no markdown files found to scan")

    failures: list[str] = list(ctx.read_errors)
    warnings: list[str] = []
    local_items: list[tuple[_LinkRef, Path, str, bool]] = []

    for ref in ctx.refs:
        target = ref.raw_target
        if not target or _is_external_target(target) or target.startswith(HASH_CHAR):
            continue
        path_part = unquote(target.split(HASH_CHAR, 1)[0].split("?", 1)[0]).strip()
        if not path_part:
            continue

        had_trailing_slash = path_part.endswith("/")
        resolved = (ref.md_file.parent / path_part).resolve()
        try:
            rel_target = resolved.relative_to(ctx.root).as_posix()
        except ValueError:
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: local target '{target}' resolves outside root"
            )
            continue

        local_items.append((ref, resolved, rel_target, had_trailing_slash))

    total_targets = len(local_items)
    tracked_list = _tracked_list if _tracked_loaded else _git_ls_files(ctx.root)

    if tracked_list is not None:
        tracked_files = set(tracked_list)
        tracked_dirs: set[str] = set()
        for entry in tracked_files:
            parts = entry.split("/")
            for idx in range(1, len(parts)):
                tracked_dirs.add("/".join(parts[:idx]))

        untracked_candidates: list[tuple[_LinkRef, Path, str, list[str]]] = []
        for ref, resolved, rel_target, had_trailing_slash in local_items:
            if not had_trailing_slash and rel_target in tracked_files and resolved.is_file():
                continue
            is_tracked_dir = (
                rel_target in tracked_dirs or (rel_target == "." and bool(tracked_files))
            ) and resolved.is_dir()
            if is_tracked_dir:
                continue

            probes = [rel_target]
            if (had_trailing_slash or resolved.is_dir()) and not rel_target.endswith("/"):
                probes.append(rel_target + "/")
            untracked_candidates.append((ref, resolved, rel_target, probes))

        all_probes = [p for _, _, _, probes in untracked_candidates for p in probes]
        ignored_probes = _git_ignored_batch(ctx.root, all_probes)
        if ignored_probes is None:
            fallback_rules = _parse_gitignore_fallback_rules(ctx.root)
            ignored_probes = {
                p
                for p in all_probes
                if _fallback_is_ignored(fallback_rules, p.rstrip("/"), is_dir=p.endswith("/"))
            }

        for ref, resolved, rel_target, probes in untracked_candidates:
            if any(p in ignored_probes for p in probes):
                warnings.append(
                    f"{ref.md_rel}:{ref.lineno}: target '{ref.raw_target}' points to gitignored path '{rel_target}'"
                )
            elif resolved.exists():
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: target '{ref.raw_target}' points to untracked path '{rel_target}'"
                )
            else:
                failures.append(
                    f"{ref.md_rel}:{ref.lineno}: target '{ref.raw_target}' points to missing path '{rel_target}'"
                )

        if failures:
            return CheckResult(
                name,
                "FAIL",
                f"{len(failures)} untracked/missing local link or image target(s) across {len(ctx.md_files)} file(s)",
                failures + warnings,
            )
        if warnings:
            return CheckResult(
                name,
                "WARN",
                f"scanned {len(ctx.md_files)} file(s), {total_targets} local target(s); "
                f"{total_targets - len(warnings)} tracked, {len(warnings)} gitignored",
                warnings,
            )
        return CheckResult(
            name,
            "PASS",
            f"scanned {len(ctx.md_files)} file(s), {total_targets} local target(s); all tracked in git",
        )

    fallback_rules = _parse_gitignore_fallback_rules(ctx.root)
    for ref, resolved, rel_target, had_trailing_slash in local_items:
        treat_as_dir = had_trailing_slash or resolved.is_dir()
        exists_ok = resolved.is_dir() if had_trailing_slash else resolved.exists()
        if _fallback_is_ignored(fallback_rules, rel_target, is_dir=treat_as_dir):
            warnings.append(
                f"{ref.md_rel}:{ref.lineno}: gitless fallback: target '{ref.raw_target}' matches .gitignore ('{rel_target}')"
            )
        elif not exists_ok:
            failures.append(
                f"{ref.md_rel}:{ref.lineno}: gitless fallback: missing local target '{ref.raw_target}' ('{rel_target}')"
            )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"gitless fallback (.git absent): {len(failures)} missing local target(s) across {len(ctx.md_files)} file(s)",
            failures + warnings,
        )
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"gitless fallback (.git absent): scanned {len(ctx.md_files)} file(s), {total_targets} target(s); "
            f"{len(warnings)} gitignored, 0 missing",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"gitless fallback (.git absent): scanned {len(ctx.md_files)} file(s), {total_targets} local target(s) verified on disk",
    )


def _is_exempt_exploits_stale_match(
    rel: str,
    token_label: str,
    cleaned_text: str,
    match_start: int,
    line_text: str,
    history_start: int | None,
) -> bool:
    if rel != "docs/EXPLOITS.md" or token_label == "<PLACEHOLDER":
        return False
    if history_start is not None and match_start >= history_start:
        return True
    if EXPLOITS_ROW_49_RX.match(line_text):
        return True
    if token_label in {"35 whitebox", "1,789 tool calls"}:
        low = line_text.lower()
        if "wave 1 detail:" in low and "75 whitebox" in low and "4,325 tool calls" in low:
            return True
    return False


def check_stale_pr41_numbers(root: Path = ROOT) -> CheckResult:
    name = CHECK_STALE_PR41
    root_resolved = root.resolve()
    failures: list[str] = []
    scanned = 0

    for rel in ACTIVE_JUDGE_DOCS:
        doc_path = root_resolved / rel
        if not doc_path.is_file():
            continue
        scanned += 1
        try:
            text = doc_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            failures.append(f"{rel}: unreadable judge-facing doc ({type(exc).__name__})")
            continue

        cleaned = _strip_fences_and_comments(text)
        lines = cleaned.split("\n")
        history_start: int | None = None
        if rel == "docs/EXPLOITS.md":
            hm = EXPLOITS_FULL_HISTORY_HEADING_RX.search(cleaned)
            if hm is not None:
                history_start = hm.start()

        for token_label, rx in STALE_PR41_PATTERNS:
            for m in rx.finditer(cleaned):
                lineno = 1 + cleaned.count("\n", 0, m.start())
                line_text = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
                if _is_exempt_exploits_stale_match(
                    rel, token_label, cleaned, m.start(), line_text, history_start
                ):
                    continue
                matched = " ".join(m.group(0).split())
                failures.append(
                    f"{rel}:{lineno}: superseded pre-PR41 token '{token_label}' (matched '{matched}')"
                )

    if scanned == 0:
        return CheckResult(name, "FAIL", "no active judge-facing docs found to scan")
    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} superseded pre-PR41 token(s) across {scanned} judge-facing doc(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 superseded pre-PR41 tokens across {scanned} active judge-facing doc(s)",
    )


def _collect_text_audit_files(
    root: Path,
    tracked_list: list[str] | None,
) -> list[tuple[str, Path]]:
    by_rel: dict[str, Path] = {}
    if tracked_list is not None:
        for rel in sorted(set(tracked_list)):
            if Path(rel).suffix.lower() not in TEXT_AUDIT_EXTENSIONS:
                continue
            p = root / rel
            if p.is_file():
                by_rel[rel] = p
        return list(by_rel.items())

    fallback_rules = _parse_gitignore_fallback_rules(root)
    visited_dirs: set[tuple[int, int]] = set()
    for dirpath_str, dirnames, filenames in os.walk(root, topdown=True, followlinks=True):
        dirpath = Path(dirpath_str)
        try:
            st = dirpath.stat()
            dir_key = (st.st_dev, st.st_ino)
        except OSError:
            dirnames[:] = []
            continue
        if dir_key in visited_dirs:
            dirnames[:] = []
            continue
        visited_dirs.add(dir_key)

        rel_dir_path = dirpath.relative_to(root)
        rel_dir = "" if rel_dir_path == Path(".") else rel_dir_path.as_posix()

        kept_dirs: list[str] = []
        for d in sorted(dirnames):
            if d in SKIP_WALK_DIRS:
                continue
            d_rel = f"{rel_dir}/{d}" if rel_dir else d
            if _fallback_is_ignored(fallback_rules, d_rel, is_dir=True):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fname in sorted(filenames):
            if Path(fname).suffix.lower() not in TEXT_AUDIT_EXTENSIONS:
                continue
            f_rel = f"{rel_dir}/{fname}" if rel_dir else fname
            if _fallback_is_ignored(fallback_rules, f_rel, is_dir=False):
                continue
            full_p = dirpath / fname
            if full_p.is_file():
                by_rel[f_rel] = full_p

    return sorted(by_rel.items(), key=lambda item: item[0])


def _collect_scripts_sh(
    root: Path,
    tracked_list: list[str] | None,
) -> list[tuple[str, Path]]:
    scripts_dir = root / "scripts"
    if not scripts_dir.is_dir():
        return []
    candidates: list[tuple[str, Path]] = []
    for p in sorted(scripts_dir.glob("*.sh")):
        if p.is_file():
            candidates.append((f"scripts/{p.name}", p))
    if not candidates:
        return []
    rels = [rel for rel, _ in candidates]
    if tracked_list is not None:
        tracked_set = set(tracked_list)
        untracked = [rel for rel in rels if rel not in tracked_set]
        ignored = _git_ignored_batch(root, untracked) if untracked else set()
        if ignored is None:
            rules = _parse_gitignore_fallback_rules(root)
            ignored = {rel for rel in untracked if _fallback_is_ignored(rules, rel, is_dir=False)}
        return [(rel, p) for rel, p in candidates if rel not in ignored]
    rules = _parse_gitignore_fallback_rules(root)
    return [(rel, p) for rel, p in candidates if not _fallback_is_ignored(rules, rel, is_dir=False)]


def _sanitize_shell_line(line: str) -> str:
    out: list[str] = []
    i = 0
    n = len(line)
    in_single = False
    in_double = False
    cmd_sub_depth = 0
    while i < n:
        ch = line[i]
        if in_single:
            if ch == "'":
                in_single = False
                out.append("'")
            else:
                out.append(" ")
            i += 1
            continue
        if in_double and cmd_sub_depth == 0:
            if ch == "\\" and i + 1 < n:
                out.append("  ")
                i += 2
                continue
            if ch == '"':
                in_double = False
                out.append('"')
                i += 1
                continue
            if ch == "$" and i + 1 < n and line[i + 1] == "(":
                cmd_sub_depth = 1
                out.append("$(")
                i += 2
                continue
            if ch == "`":
                out.append("`")
                i += 1
                while i < n and line[i] != "`":
                    if line[i] == "\\" and i + 1 < n:
                        out.append(line[i : i + 2])
                        i += 2
                    else:
                        out.append(line[i])
                        i += 1
                if i < n:
                    out.append("`")
                    i += 1
                continue
            out.append(" ")
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            if i + 1 == n - 1:
                out.append("\\")
                i += 1
                continue
            out.append("  ")
            i += 2
            continue
        if ch == "'":
            in_single = True
            out.append("'")
            i += 1
            continue
        if ch == '"' and cmd_sub_depth == 0:
            in_double = True
            out.append('"')
            i += 1
            continue
        if ch == "$" and i + 1 < n and line[i + 1] == "(":
            if cmd_sub_depth > 0:
                cmd_sub_depth += 1
            out.append("$(")
            i += 2
            continue
        if ch == "(" and cmd_sub_depth > 0:
            cmd_sub_depth += 1
            out.append("(")
            i += 1
            continue
        if ch == ")" and cmd_sub_depth > 0:
            cmd_sub_depth -= 1
            out.append(")")
            i += 1
            continue
        if ch == HASH_CHAR and (i == 0 or line[i - 1] in " \t;|&("):
            break
        out.append(ch)
        i += 1
    return "".join(out)


def _extract_shell_statements(sh_text: str) -> list[tuple[str, list[tuple[int, str]]]]:
    raw_lines = sh_text.splitlines()
    statements: list[tuple[str, list[tuple[int, str]]]] = []
    current_segs: list[tuple[int, str]] = []
    heredoc_delim: str | None = None
    heredoc_strip_tabs = False
    pending_heredoc: tuple[str, bool] | None = None

    for lineno, raw_line in enumerate(raw_lines, 1):
        if lineno == 1 and raw_line.startswith(HASH_CHAR + "!"):
            continue
        if heredoc_delim is not None:
            candidate = raw_line.lstrip("\t") if heredoc_strip_tabs else raw_line
            if candidate.strip() == heredoc_delim and (
                heredoc_strip_tabs or raw_line.rstrip() == heredoc_delim
            ):
                heredoc_delim = None
                heredoc_strip_tabs = False
            continue

        sanitized = _sanitize_shell_line(raw_line)
        if "<<" in sanitized:
            for hm in HEREDOC_START_RX.finditer(raw_line):
                if hm.start() < len(sanitized) and sanitized[hm.start() : hm.start() + 2] == "<<":
                    delim = hm.group(2) or hm.group(3) or ""
                    if delim:
                        pending_heredoc = (delim, hm.group(1) == "-")
                        break

        stripped_r = sanitized.rstrip()
        continued = stripped_r.endswith("\\")
        seg_body = stripped_r[:-1] if continued else sanitized
        if seg_body.strip():
            current_segs.append((lineno, seg_body))

        if not continued:
            if current_segs:
                joined = " ".join(seg for _, seg in current_segs)
                statements.append((joined, current_segs))
                current_segs = []
            if pending_heredoc is not None:
                heredoc_delim, heredoc_strip_tabs = pending_heredoc
                pending_heredoc = None

    if current_segs:
        joined = " ".join(seg for _, seg in current_segs)
        statements.append((joined, current_segs))

    return statements


def _compute_if_guard_contexts(
    statements: list[tuple[str, list[tuple[int, str]]]],
) -> list[str]:
    n = len(statements)
    spans: list[tuple[int, int]] = []
    stack: list[int] = []
    for idx, (joined, _) in enumerate(statements):
        opens = len(SHELL_IF_WORD_RX.findall(joined))
        closes = len(SHELL_FI_WORD_RX.findall(joined))
        for _ in range(opens):
            stack.append(idx)
        for _ in range(closes):
            if stack:
                start_idx = stack.pop()
                if start_idx < idx:
                    spans.append((start_idx, idx))

    contexts: list[str] = []
    for idx, (joined, _) in enumerate(statements):
        enclosing = [s for s in spans if s[0] <= idx <= s[1]]
        if enclosing:
            outer_start = min(s[0] for s in enclosing)
            outer_end = max(s[1] for s in enclosing)
            contexts.append(" ; ".join(statements[k][0] for k in range(outer_start, outer_end + 1)))
        else:
            contexts.append(joined)
    return contexts


def _is_diffutils_tool_guarded(tool: str, guard_text: str) -> bool:
    if re.search(rf"\b(?:command\s+-v|type|hash)\s+{tool}\b", guard_text) is not None:
        return True
    fallback_rx = re.compile(
        rf"\b{tool}\b[^;&|\n]*\|\|\s*(?:[\{{(]\s*)?(?:\$\([A-Za-z0-9_]+\)\s+)?python3?\b"
    )
    return fallback_rx.search(guard_text) is not None


def _audit_conflict_markers(rel: str, text: str, *, is_markdown: bool) -> list[str]:
    if not any(tok in text for tok in CONFLICT_FAST_TOKENS):
        return []
    hits: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for lineno, line in enumerate(text.splitlines(), 1):
        if is_markdown:
            fm = FENCE_OPEN_RX.match(line)
            if not in_fence:
                if fm is not None:
                    marker = fm.group(1)
                    in_fence = True
                    fence_char = marker[0]
                    fence_len = len(marker)
                    continue
            else:
                if fm is not None:
                    marker = fm.group(1)
                    if marker[0] == fence_char and len(marker) >= fence_len:
                        in_fence = False
                        fence_char = ""
                        fence_len = 0
                continue
        if CONFLICT_MARKER_RX.match(line):
            hits.append(f"{rel}:{lineno}: git merge-conflict marker '{line[:16].strip()}'")
    return hits


def _audit_shell_script_portability(rel: str, sh_text: str) -> list[str]:
    issues: list[str] = []
    clean_text = sh_text.lstrip("\ufeff")
    lines = clean_text.splitlines()
    if not lines or SHEBANG_RX.match(lines[0]) is None:
        issues.append(f"{rel}:1: missing or invalid shebang in shell script")

    statements = _extract_shell_statements(clean_text)
    guard_contexts = _compute_if_guard_contexts(statements)
    for idx, (_, segs) in enumerate(statements):
        guard_text = guard_contexts[idx]
        for seg_lineno, seg_text in segs:
            if SHELL_PKILL_RX.search(seg_text) is not None:
                issues.append(f"{rel}:{seg_lineno}: forbidden 'pkill' invocation in shell script")
            for dm in SHELL_DIFFUTILS_RX.finditer(seg_text):
                tool = dm.group(1)
                if not _is_diffutils_tool_guarded(tool, guard_text):
                    issues.append(
                        f"{rel}:{seg_lineno}: bare '{tool}' without 'command -v {tool}' or Python fallback"
                    )
    return issues


def check_makefile_diffutils_portability(root: Path = ROOT) -> CheckResult:
    name = CHECK_MAKEFILE_DIFFUTILS
    makefile_path = root.resolve() / "Makefile"
    if not makefile_path.is_file():
        return CheckResult(name, "FAIL", "Makefile not found", ["Makefile: missing file"])
    try:
        raw_text = makefile_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return CheckResult(
            name,
            "FAIL",
            f"unreadable Makefile ({type(exc).__name__})",
            [f"Makefile: unreadable ({type(exc).__name__})"],
        )

    recipes: list[tuple[str, list[tuple[int, str]]]] = []
    cur_segs: list[tuple[int, str]] = []
    in_recipe = False

    for lineno, raw_line in enumerate(raw_text.splitlines(), 1):
        if not in_recipe:
            if not raw_line.startswith("\t"):
                continue
            body = raw_line[1:].lstrip()
            while body and body[0] in "@-+":
                body = body[1:].lstrip()
            in_recipe = True
        else:
            body = raw_line.lstrip("\t")

        normalized = body.replace("$$", "$")
        sanitized = _sanitize_shell_line(normalized)
        stripped_r = sanitized.rstrip()
        continued = stripped_r.endswith("\\")
        seg_body = stripped_r[:-1] if continued else sanitized
        if seg_body.strip():
            cur_segs.append((lineno, seg_body))

        if not continued:
            if cur_segs:
                recipes.append((" ".join(seg for _, seg in cur_segs), cur_segs))
                cur_segs = []
            in_recipe = False

    if cur_segs:
        recipes.append((" ".join(seg for _, seg in cur_segs), cur_segs))

    failures: list[str] = []
    for recipe_text, segs in recipes:
        for seg_lineno, seg_text in segs:
            for dm in SHELL_DIFFUTILS_RX.finditer(seg_text):
                tool = dm.group(1)
                if not _is_diffutils_tool_guarded(tool, recipe_text):
                    failures.append(
                        f"Makefile:{seg_lineno}: bare '{tool}' without 'command -v {tool}' or Python fallback"
                    )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} bare diffutils invocation(s) in Makefile without 'command -v' or Python fallback",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"scanned {len(recipes)} Makefile recipe(s); all cmp/diff calls guarded or absent",
    )


def check_portability_and_encoding(
    root: Path = ROOT,
    *,
    _tracked_list: list[str] | None = None,
    _tracked_loaded: bool = False,
) -> CheckResult:
    name = CHECK_PORTABILITY_AND_ENCODING
    resolved = root.resolve()
    tracked_list = _tracked_list if _tracked_loaded else _git_ls_files(resolved)

    audit_files = _collect_text_audit_files(resolved, tracked_list)
    scripts_sh = _collect_scripts_sh(resolved, tracked_list)
    seen_rels = {rel for rel, _ in audit_files}
    for rel, p in scripts_sh:
        if rel not in seen_rels:
            audit_files.append((rel, p))
            seen_rels.add(rel)

    if not audit_files:
        return CheckResult(name, "FAIL", "no text or shell files found to scan")

    failures: list[str] = []
    decoded_scripts: dict[str, str] = {}
    sh_count = 0

    for rel, path in audit_files:
        suffix = path.suffix.lower()
        if suffix == ".sh":
            sh_count += 1
        try:
            raw = path.read_bytes()
        except OSError as exc:
            failures.append(f"{rel}: unreadable file ({type(exc).__name__})")
            continue

        if b"\x00" in raw:
            failures.append(f"{rel}: contains NUL byte(s)")
            continue

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            failures.append(f"{rel}: invalid UTF-8 encoding ({exc.reason} at byte {exc.start})")
            continue

        if raw.startswith(b"\xef\xbb\xbf") or "\ufeff" in text:
            bom_ln = 1 + text.count("\n", 0, text.find("\ufeff"))
            failures.append(f"{rel}:{bom_ln}: contains UTF-8 BOM (U+FEFF)")

        if suffix == ".sh" and b"\r\n" in raw:
            first_idx = raw.index(b"\r\n")
            crlf_ln = 1 + raw.count(b"\n", 0, first_idx)
            failures.append(f"{rel}:{crlf_ln}: CRLF (\\r\\n) line ending in shell script")

        failures.extend(_audit_conflict_markers(rel, text, is_markdown=(suffix == ".md")))

        if rel.startswith("scripts/") and suffix == ".sh" and "/" not in rel[len("scripts/") :]:
            decoded_scripts[rel] = text

    for rel, path in scripts_sh:
        sh_text = decoded_scripts.get(rel)
        if sh_text is None:
            continue
        failures.extend(_audit_shell_script_portability(rel, sh_text))

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} portability/encoding violation(s) across {len(audit_files)} file(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"scanned {len(audit_files)} text file(s) ({sh_count} .sh, {len(scripts_sh)} scripts/*.sh); "
        "UTF-8 clean, 0 BOM/NUL/CRLF/conflict markers, portable shell",
    )


def audit_doc_hygiene(root: Path = ROOT) -> list[CheckResult]:
    resolved = root.resolve()
    ctx = _scan_markdown_refs(resolved)
    tracked_list = _git_ls_files(resolved)
    return [
        check_markdown_anchors(resolved, _ctx=ctx),
        check_image_assets(resolved, _ctx=ctx),
        check_tracked_link_targets(
            resolved, _ctx=ctx, _tracked_list=tracked_list, _tracked_loaded=True
        ),
        check_stale_pr41_numbers(resolved),
        check_portability_and_encoding(
            resolved, _tracked_list=tracked_list, _tracked_loaded=True
        ),
    ]


audit_repo = audit_doc_hygiene


def format_report(results: list[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Keyless markdown anchor, image asset, git-tracking, post-PR41 stale-number, "
            "and shell portability/encoding hygiene audit."
        )
    )
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to check")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results = audit_doc_hygiene(root=args.root.resolve())
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items: list[dict[str, Any]] = [asdict(r) for r in results]
        payload = {
            "results": items,
            "checks": items,
            "elapsed_s": round(elapsed, 4),
            "passed": passed,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
