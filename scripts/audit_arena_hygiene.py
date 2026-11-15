from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)

MAX_ARENA_BYTES = 15 * 1024 * 1024

CHECK_SECRETS = "Arena Secret & Credential Firewall"
CHECK_OUTBOUND_LLM = "Arena Zero Outbound LLM Endpoints"
CHECK_MD_LINKS = "Arena Markdown Links & Image Refs"
CHECK_UI_HYGIENE = "Arena UI ASCII, Zero Em-Dash & Zero Comments"
CHECK_SIZE_BUDGET = "Arena Size Budget (<15 MB)"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_SECRETS,
    CHECK_OUTBOUND_LLM,
    CHECK_MD_LINKS,
    CHECK_UI_HYGIENE,
    CHECK_SIZE_BUDGET,
)

SKIP_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "node_modules",
    }
)

BINARY_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".wasm",
        ".whl",
        ".zip",
        ".gz",
        ".tgz",
        ".bz2",
        ".xz",
        ".mp4",
        ".webm",
        ".mp3",
        ".wav",
        ".ogg",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".pdf",
    }
)

ALLOWED_ENV_TEMPLATES: frozenset[str] = frozenset(
    {
        ".env.example",
        ".env.sample",
        ".env.template",
    }
)

FORBIDDEN_SECRET_FILENAMES: frozenset[str] = frozenset(
    {
        "SALT",
        "ledger_key",
        ".env",
        ".gateway_token",
        ".gateway.env",
    }
)

TOK_WORLD_SECRET = "CANARY_" + "WORLD_SECRET"
TOK_LEDGER_TOKEN = "CANARY_" + "LEDGER_TOKEN"
TOK_ADMIN_TOKEN = "CANARY_" + "ADMIN_TOKEN"
TOK_JUDGE_SALT_PATH = "data/worlds/" + "judge/SALT"

GOOGLE_KEY_PREFIX = "AI" + "za"
SK_KEY_PREFIX = "s" + "k-"
GH_KEY_PREFIX = "gh"
OAUTH_PREFIX = "ya" + "29."
HF_PREFIX = "h" + "f_"
XAI_PREFIX = "xa" + "i-"
GOOG_HDR = "x-goog-" + "api-key"

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "google_api_key",
        re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape(GOOGLE_KEY_PREFIX) + r"[0-9A-Za-z_-]{16,}"),
    ),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + re.escape(SK_KEY_PREFIX)
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{12,}"
        ),
    ),
    (
        "github_pat",
        re.compile(r"(?<![0-9A-Za-z+/_-])" + GH_KEY_PREFIX + r"[pousr]_[A-Za-z0-9]{16,}"),
    ),
    (
        "google_oauth",
        re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape(OAUTH_PREFIX) + r"[0-9A-Za-z_-]{20,}"),
    ),
    (
        "hf_token",
        re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape(HF_PREFIX) + r"[A-Za-z0-9]{20,}"),
    ),
    (
        "xai_key",
        re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape(XAI_PREFIX) + r"[A-Za-z0-9_-]{20,}"),
    ),
    (
        "gateway_header_key",
        re.compile(r"[\"']" + re.escape(GOOG_HDR) + r"[\"']\s*:\s*[\"'][^\"'\s]{8,}[\"']", re.IGNORECASE),
    ),
)

SECRET_ENV_NAMES: tuple[str, ...] = (
    "SALT",
    TOK_WORLD_SECRET,
    TOK_LEDGER_TOKEN,
    TOK_ADMIN_TOKEN,
    "CANARY_" + "LEDGER_KEY",
    "GEMINI_" + "API_KEY",
    "GOOGLE_" + "API_KEY",
    "GOOGLE_GENERATIVE_AI_" + "API_KEY",
    "OPENAI_" + "API_KEY",
    "ANTHROPIC_" + "API_KEY",
)

SECRET_ASSIGN_RX = re.compile(
    r"(?:[\"']?(?:"
    + "|".join(re.escape(k) for k in SECRET_ENV_NAMES)
    + r")[\"']?\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{6,})"
)

FORBIDDEN_DENYLIST_BLOCK_RX = re.compile(
    r"\bFORBIDDEN_[A-Z0-9_]*\s*=\s*(?:new\s+Set\s*\(\s*\[|frozenset\s*\(\s*[\[\(\{]|[\[\(\{])"
    r"[^\];\)\}]*?\b" + re.escape(TOK_WORLD_SECRET) + r"\b[^\];\)\}]*?[\]\)\}]",
    re.DOTALL,
)

MD_NEGATION_RX = re.compile(r"\b(?:never|zero|not|without|forbidden|no)\b", re.IGNORECASE)

OUTBOUND_LLM_ENDPOINTS: tuple[str, ...] = (
    "generativelanguage." + "googleapis.com",
    "api." + "openai.com",
    "api." + "anthropic.com",
    "api." + "x.ai",
)

OUTBOUND_LLM_RX: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (host, re.compile(r"(?<![A-Za-z0-9.-])" + re.escape(host) + r"(?![A-Za-z0-9.-])", re.IGNORECASE))
    for host in OUTBOUND_LLM_ENDPOINTS
)

UI_COMMENT_MARKERS: tuple[tuple[str, str], ...] = (
    ("line comment " + SLASH_SLASH, SLASH_SLASH),
    ("block comment open " + SLASH_STAR, SLASH_STAR),
    ("block comment close " + STAR_SLASH, STAR_SLASH),
)

EXTERNAL_SCHEMES: tuple[str, ...] = (
    "http" + ":" + SLASH_SLASH,
    "https" + ":" + SLASH_SLASH,
    "mailto:",
    "tel:",
    "javascript:",
    "data:",
    SLASH_SLASH,
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


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class _ArenaSnapshot:
    root: Path
    arena_dir: Path
    arena_exists: bool
    all_files: list[tuple[str, Path]]
    text_files: dict[str, str]
    ui_files: list[tuple[str, Path]]
    md_files: list[tuple[str, Path]]
    read_errors: list[str]
    decode_errors: list[str]


def _rel_posix(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _file_size_bytes(path: Path) -> int:
    return path.stat().st_size


def _build_snapshot(root: Path) -> _ArenaSnapshot:
    resolved_root = root.resolve()
    arena_dir = resolved_root / "docs" / "arena"
    if not arena_dir.is_dir():
        return _ArenaSnapshot(
            root=resolved_root,
            arena_dir=arena_dir,
            arena_exists=False,
            all_files=[],
            text_files={},
            ui_files=[],
            md_files=[],
            read_errors=[],
            decode_errors=[],
        )

    all_files: list[tuple[str, Path]] = []
    text_files: dict[str, str] = {}
    ui_files: list[tuple[str, Path]] = []
    md_files: list[tuple[str, Path]] = []
    read_errors: list[str] = []
    decode_errors: list[str] = []

    for p in sorted(arena_dir.rglob("*")):
        if not p.is_file():
            continue
        rel_arena_parts = p.relative_to(arena_dir).parts
        if any(part in SKIP_DIR_NAMES for part in rel_arena_parts):
            continue
        if p.suffix.lower() in {".pyc", ".pyo"}:
            continue

        rel = _rel_posix(resolved_root, p)
        all_files.append((rel, p))

        is_ui = len(rel_arena_parts) >= 2 and rel_arena_parts[0] == "ui"
        if is_ui:
            ui_files.append((rel, p))
        if p.suffix.lower() in {".md", ".markdown"}:
            md_files.append((rel, p))

        suffix = p.suffix.lower()
        if suffix in BINARY_EXTENSIONS and not is_ui:
            continue

        try:
            raw = p.read_bytes()
        except OSError as exc:
            read_errors.append(f"{rel}: unreadable file ({type(exc).__name__})")
            continue

        if b"\x00" in raw and not is_ui and suffix not in {".md", ".js", ".mjs", ".css", ".html", ".htm", ".py", ".json", ".jsonl", ".txt"}:
            continue

        if b"\x00" in raw:
            decode_errors.append(f"{rel}: contains NUL byte(s)")
            continue

        try:
            text_files[rel] = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            decode_errors.append(f"{rel}: invalid UTF-8 at byte {exc.start} ({exc.reason})")

    return _ArenaSnapshot(
        root=resolved_root,
        arena_dir=arena_dir,
        arena_exists=True,
        all_files=all_files,
        text_files=text_files,
        ui_files=ui_files,
        md_files=md_files,
        read_errors=read_errors,
        decode_errors=decode_errors,
    )


def _repo_secret_bytes(root: Path) -> list[bytes]:
    secrets_list: list[bytes] = []
    salt_path = root / TOK_JUDGE_SALT_PATH
    if salt_path.is_file():
        try:
            raw_salt = salt_path.read_bytes().strip()
            if len(raw_salt) >= 8:
                secrets_list.append(raw_salt)
        except OSError:
            pass
    for env_key in (TOK_WORLD_SECRET, TOK_LEDGER_TOKEN, TOK_ADMIN_TOKEN):
        val = os.environ.get(env_key, "").strip()
        if len(val) >= 8:
            secrets_list.append(val.encode("utf-8"))
    return secrets_list


def _is_exempt_world_secret_mention(rel: str, full_text: str, match_start: int, match_end: int, line: str) -> bool:
    suffix = Path(rel).suffix.lower()
    if any(tok in line for tok in ("environ", "getenv", "process.env")):
        return False
    if re.search(re.escape(TOK_WORLD_SECRET) + r"[\"']?\s*[:=]", line):
        return False

    if suffix in {".js", ".mjs", ".py"}:
        for block_m in FORBIDDEN_DENYLIST_BLOCK_RX.finditer(full_text):
            if block_m.start() <= match_start and match_end <= block_m.end():
                quoted_double = f'"{TOK_WORLD_SECRET}"'
                quoted_single = f"'{TOK_WORLD_SECRET}'"
                if quoted_double in line or quoted_single in line:
                    return True
        return False

    if suffix in {".md", ".markdown"}:
        if f"`{TOK_WORLD_SECRET}`" in line and MD_NEGATION_RX.search(line) is not None:
            return True
        return False

    return False


def check_arena_secrets(
    root: Path = ROOT,
    *,
    _snap: _ArenaSnapshot | None = None,
) -> CheckResult:
    name = CHECK_SECRETS
    snap = _snap if _snap is not None else _build_snapshot(root)
    if not snap.arena_exists:
        return CheckResult(name, "FAIL", "docs/arena directory does not exist", ["missing directory: docs/arena"])
    if not snap.all_files:
        return CheckResult(name, "FAIL", "docs/arena contains 0 files", ["expected files under docs/arena/**"])

    violations: list[str] = list(snap.read_errors)
    secret_bytes = _repo_secret_bytes(snap.root)

    for rel, fpath in snap.all_files:
        fname = fpath.name
        if fname in FORBIDDEN_SECRET_FILENAMES or (
            fname.startswith(".env.") and fname not in ALLOWED_ENV_TEMPLATES
        ):
            violations.append(f"{rel}: forbidden secret filename '{fname}'")
            continue
        if fname.endswith(".world.json"):
            violations.append(f"{rel}: forbidden answer-key world dump '{fname}'")
            continue

        if secret_bytes:
            try:
                raw = fpath.read_bytes()
            except OSError:
                raw = b""
            for sb in secret_bytes:
                if sb and sb in raw:
                    violations.append(f"{rel}: contains raw repository secret bytes")
                    break

        text = snap.text_files.get(rel)
        if text is None:
            continue

        lines = text.splitlines()
        for kind, rx in CREDENTIAL_PATTERNS:
            for m in rx.finditer(text):
                lineno = 1 + text.count("\n", 0, m.start())
                redacted = m.group(0)[:6] + "..."
                violations.append(f"{rel}:{lineno}: credential token '{kind}' ({redacted})")

        for m_assign in SECRET_ASSIGN_RX.finditer(text):
            lineno = 1 + text.count("\n", 0, m_assign.start())
            violations.append(f"{rel}:{lineno}: secret value assignment detected")

        for forbidden_tok in (TOK_LEDGER_TOKEN, TOK_JUDGE_SALT_PATH):
            start_pos = 0
            while True:
                idx = text.find(forbidden_tok, start_pos)
                if idx == -1:
                    break
                lineno = 1 + text.count("\n", 0, idx)
                violations.append(f"{rel}:{lineno}: forbidden secret token '{forbidden_tok}'")
                start_pos = idx + len(forbidden_tok)

        ws_pos = 0
        while True:
            idx = text.find(TOK_WORLD_SECRET, ws_pos)
            if idx == -1:
                break
            end_idx = idx + len(TOK_WORLD_SECRET)
            lineno = 1 + text.count("\n", 0, idx)
            line_str = lines[lineno - 1] if 1 <= lineno <= len(lines) else ""
            if not _is_exempt_world_secret_mention(rel, text, idx, end_idx, line_str):
                violations.append(f"{rel}:{lineno}: forbidden secret token '{TOK_WORLD_SECRET}'")
            ws_pos = end_idx

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} secret/credential violation(s) across {len(snap.all_files)} file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 secret/answer-key/credential tokens across {len(snap.all_files)} file(s) in docs/arena/**",
    )


def check_arena_outbound_endpoints(
    root: Path = ROOT,
    *,
    _snap: _ArenaSnapshot | None = None,
) -> CheckResult:
    name = CHECK_OUTBOUND_LLM
    snap = _snap if _snap is not None else _build_snapshot(root)
    if not snap.arena_exists:
        return CheckResult(name, "FAIL", "docs/arena directory does not exist", ["missing directory: docs/arena"])
    if not snap.all_files:
        return CheckResult(name, "FAIL", "docs/arena contains 0 files", ["expected files under docs/arena/**"])

    violations: list[str] = list(snap.read_errors)
    for rel in sorted(snap.text_files):
        text = snap.text_files[rel]
        for host, rx in OUTBOUND_LLM_RX:
            for m in rx.finditer(text):
                lineno = 1 + text.count("\n", 0, m.start())
                violations.append(f"{rel}:{lineno}: forbidden outbound LLM endpoint '{host}'")

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} outbound LLM endpoint reference(s) across {len(snap.text_files)} text file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"0 live outbound LLM API endpoints across {len(snap.text_files)} text file(s) in docs/arena/**",
    )


def _strip_fences_and_html_comments(md_text: str) -> str:
    cleaned_lines: list[str] = []
    in_fence = False
    fence_char = ""
    fence_len = 0
    for raw_line in md_text.splitlines():
        m = FENCE_OPEN_RX.match(raw_line)
        if not in_fence:
            if m is not None:
                marker = m.group(1)
                in_fence = True
                fence_char = marker[0]
                fence_len = len(marker)
                cleaned_lines.append("")
                continue
            cleaned_lines.append(raw_line)
        else:
            if m is not None:
                marker = m.group(1)
                if marker[0] == fence_char and len(marker) >= fence_len:
                    in_fence = False
                    fence_char = ""
                    fence_len = 0
            cleaned_lines.append("")
    joined = "\n".join(cleaned_lines)
    return HTML_COMMENT_RX.sub(lambda match: "\n" * match.group(0).count("\n"), joined)


def _strip_code_preserving_lines(md_text: str) -> str:
    without_fences = _strip_fences_and_html_comments(md_text)
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
    cleaned = _strip_fences_and_html_comments(md_text)
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
        if atx is not None:
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

    explicit_ids = {
        (m.group(1) or m.group(2) or "").strip()
        for m in EXPLICIT_HTML_ID_RX.finditer(cleaned)
        if (m.group(1) or m.group(2) or "").strip()
    }
    return used | explicit_ids


def _parse_md_dest(angle_group: str | None, paren_group: str | None) -> str:
    if angle_group is not None:
        return angle_group.strip()
    raw = (paren_group or "").strip()
    if not raw:
        return ""
    return raw.split()[0].strip()


def _is_external_target(target: str) -> bool:
    return target.lower().startswith(EXTERNAL_SCHEMES)


def _verify_fragment_on_target(
    md_rel: str,
    lineno: int,
    raw_target: str,
    frag: str,
    target_file: Path,
    target_rel: str,
    slug_cache: dict[Path, set[str]],
) -> str | None:
    suffix = target_file.suffix.lower()
    if suffix in {".md", ".markdown"}:
        rp = target_file.resolve()
        slugs = slug_cache.get(rp)
        if slugs is None:
            try:
                slugs = extract_heading_slugs(rp.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                return f"{md_rel}:{lineno}: unreadable markdown anchor target '{target_rel}'"
            slug_cache[rp] = slugs
        if frag not in slugs:
            return f"{md_rel}:{lineno}: broken anchor '{raw_target}' (slug '{frag}' not found in '{target_rel}')"
        return None

    if suffix in {".html", ".htm"}:
        try:
            html_txt = target_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return f"{md_rel}:{lineno}: unreadable HTML anchor target '{target_rel}'"
        html_ids = {
            (m.group(1) or m.group(2) or "").strip()
            for m in EXPLICIT_HTML_ID_RX.finditer(html_txt)
        }
        if frag not in html_ids:
            return f"{md_rel}:{lineno}: broken HTML anchor '{raw_target}' (id '{frag}' not found in '{target_rel}')"
        return None

    lm = LINE_ANCHOR_RX.match(frag)
    if lm is None:
        return f"{md_rel}:{lineno}: unsupported anchor '{raw_target}' on '{target_rel}'"
    start_ln = int(lm.group(1))
    end_ln = int(lm.group(2)) if lm.group(2) is not None else start_ln
    try:
        total_lines = len(target_file.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return f"{md_rel}:{lineno}: unreadable target file '{target_rel}'"
    if start_ln > end_ln or end_ln > max(1, total_lines):
        return f"{md_rel}:{lineno}: line anchor '{raw_target}' out of range for '{target_rel}' ({total_lines} lines)"
    return None


def check_arena_markdown_links(
    root: Path = ROOT,
    *,
    _snap: _ArenaSnapshot | None = None,
) -> CheckResult:
    name = CHECK_MD_LINKS
    snap = _snap if _snap is not None else _build_snapshot(root)
    if not snap.arena_exists:
        return CheckResult(name, "FAIL", "docs/arena directory does not exist", ["missing directory: docs/arena"])
    if not snap.md_files:
        return CheckResult(name, "FAIL", "no markdown files found under docs/arena/*.md", ["expected docs/arena/*.md"])

    violations: list[str] = []
    slug_cache: dict[Path, set[str]] = {}
    checked_refs = 0

    for md_rel, md_path in snap.md_files:
        md_text = snap.text_files.get(md_rel)
        if md_text is None:
            violations.append(f"{md_rel}: unreadable or invalid UTF-8 markdown file")
            continue

        stripped = _strip_code_preserving_lines(md_text)
        raw_refs: list[tuple[int, str, str]] = []

        for m_html in HTML_IMG_TAG_RX.finditer(stripped):
            ln = 1 + stripped.count("\n", 0, m_html.start())
            src_m = HTML_IMG_SRC_RX.search(m_html.group(0))
            if src_m is None:
                raw_src = ""
            else:
                raw_src = (
                    src_m.group(1)
                    if src_m.group(1) is not None
                    else (src_m.group(2) if src_m.group(2) is not None else (src_m.group(3) or ""))
                ).strip()
            raw_refs.append((ln, "html_img", raw_src))

        for ln, line in enumerate(stripped.split("\n"), 1):
            if "(" not in line or "[" not in line:
                continue
            for img_m in MD_IMAGE_RX.finditer(line):
                dest = _parse_md_dest(img_m.group(1), img_m.group(2))
                raw_refs.append((ln, "md_img", dest))
            line_no_imgs = MD_IMAGE_RX.sub("img", line)
            for link_m in MD_PLAIN_LINK_RX.finditer(line_no_imgs):
                dest = _parse_md_dest(link_m.group(1), link_m.group(2))
                raw_refs.append((ln, "md_link", dest))

        for ln, kind, target in raw_refs:
            if not target:
                checked_refs += 1
                violations.append(f"{md_rel}:{ln}: empty {kind} target")
                continue
            if _is_external_target(target):
                continue

            checked_refs += 1
            if HASH_CHAR in target:
                path_raw, frag_raw = target.split(HASH_CHAR, 1)
                frag = unquote(frag_raw).strip()
                if not frag:
                    violations.append(f"{md_rel}:{ln}: empty anchor fragment in '{target}'")
                    continue
            else:
                path_raw = target
                frag = ""

            path_part = unquote(path_raw.split("?", 1)[0]).strip()
            if not path_part:
                if kind in {"md_img", "html_img"}:
                    violations.append(f"{md_rel}:{ln}: image ref '{target}' has no file path")
                    continue
                err = _verify_fragment_on_target(md_rel, ln, target, frag, md_path, md_rel, slug_cache)
                if err is not None:
                    violations.append(err)
                continue

            resolved = (md_path.parent / path_part).resolve()
            try:
                rel_target = resolved.relative_to(snap.root).as_posix()
            except ValueError:
                violations.append(f"{md_rel}:{ln}: relative ref '{target}' resolves outside repository root")
                continue

            if kind in {"md_img", "html_img"}:
                if not resolved.is_file():
                    violations.append(f"{md_rel}:{ln}: missing image asset '{target}' ('{rel_target}')")
                    continue
                try:
                    sz = _file_size_bytes(resolved)
                except OSError as exc:
                    violations.append(f"{md_rel}:{ln}: unreadable image asset '{rel_target}' ({type(exc).__name__})")
                    continue
                if sz <= 0:
                    violations.append(f"{md_rel}:{ln}: empty image asset '{target}' ('{rel_target}', 0 bytes)")
                    continue
            else:
                had_slash = path_part.endswith("/")
                exists_ok = resolved.is_dir() if had_slash else resolved.exists()
                if not exists_ok:
                    violations.append(f"{md_rel}:{ln}: broken relative link '{target}' (missing '{rel_target}')")
                    continue
                if frag:
                    if not resolved.is_file():
                        violations.append(f"{md_rel}:{ln}: anchor link '{target}' points to directory '{rel_target}'")
                        continue
                    err = _verify_fragment_on_target(md_rel, ln, target, frag, resolved, rel_target, slug_cache)
                    if err is not None:
                        violations.append(err)

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} broken link/image ref(s) across {len(snap.md_files)} markdown file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"scanned {len(snap.md_files)} docs/arena/*.md file(s), {checked_refs} internal link/image ref(s); all resolve cleanly",
    )


def check_arena_ui_hygiene(
    root: Path = ROOT,
    *,
    _snap: _ArenaSnapshot | None = None,
) -> CheckResult:
    name = CHECK_UI_HYGIENE
    snap = _snap if _snap is not None else _build_snapshot(root)
    ui_dir = snap.arena_dir / "ui"
    if not snap.arena_exists or not ui_dir.is_dir():
        return CheckResult(
            name,
            "FAIL",
            "docs/arena/ui directory does not exist",
            ["missing directory: docs/arena/ui"],
        )
    if not snap.ui_files:
        return CheckResult(
            name,
            "FAIL",
            "docs/arena/ui contains 0 files",
            ["expected at least 1 file under docs/arena/ui/**"],
        )

    violations: list[str] = list(snap.read_errors) + list(snap.decode_errors)
    ui_rels = {rel for rel, _ in snap.ui_files}

    for rel, _ in snap.ui_files:
        text = snap.text_files.get(rel)
        if text is None:
            continue
        if not text.strip():
            violations.append(f"{rel}: empty UI file")
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                col = line.index(EM_DASH) + 1
                violations.append(f"{rel}:{lineno}:{col}: em dash (U+2014) in UI file")
            if EN_DASH in line:
                col = line.index(EN_DASH) + 1
                violations.append(f"{rel}:{lineno}:{col}: en dash (U+2013) in UI file")
            if UNICODE_MINUS in line:
                col = line.index(UNICODE_MINUS) + 1
                violations.append(f"{rel}:{lineno}:{col}: unicode minus (U+2212) in UI file")
            if not line.isascii():
                for col, ch in enumerate(line, 1):
                    if ord(ch) > 127 and ch not in {EM_DASH, EN_DASH, UNICODE_MINUS}:
                        violations.append(f"{rel}:{lineno}:{col}: non-ASCII character U+{ord(ch):04X}")
                        break
            for label, marker in UI_COMMENT_MARKERS:
                if marker in line:
                    col = line.index(marker) + 1
                    violations.append(f"{rel}:{lineno}:{col}: forbidden {label} in UI file")

    for rel in sorted(snap.text_files):
        if rel in ui_rels:
            continue
        text = snap.text_files[rel]
        for lineno, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                col = line.index(EM_DASH) + 1
                violations.append(f"{rel}:{lineno}:{col}: em dash (U+2014) in arena file")
            if not line.isascii():
                for col, ch in enumerate(line, 1):
                    if ord(ch) > 127 and ch != EM_DASH:
                        violations.append(f"{rel}:{lineno}:{col}: non-ASCII character U+{ord(ch):04X}")
                        break

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} ASCII/em-dash/comment violation(s) across docs/arena/**",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"pure ASCII, 0 em dashes across {len(snap.text_files)} text file(s), and 0 JS/CSS comments across {len(snap.ui_files)} docs/arena/ui/** file(s)",
    )


def _compute_arena_size(snap: _ArenaSnapshot) -> tuple[int, list[tuple[int, str]], list[str]]:
    total_bytes = 0
    sized: list[tuple[int, str]] = []
    errors: list[str] = []
    for rel, fpath in snap.all_files:
        try:
            sz = _file_size_bytes(fpath)
        except OSError as exc:
            errors.append(f"{rel}: stat failed ({type(exc).__name__})")
            continue
        total_bytes += sz
        sized.append((sz, rel))
    sized.sort(reverse=True)
    return total_bytes, sized, errors


def check_arena_size_budget(
    root: Path = ROOT,
    max_bytes: int = MAX_ARENA_BYTES,
    *,
    _snap: _ArenaSnapshot | None = None,
) -> CheckResult:
    name = CHECK_SIZE_BUDGET
    snap = _snap if _snap is not None else _build_snapshot(root)
    if not snap.arena_exists:
        return CheckResult(name, "FAIL", "docs/arena directory does not exist", ["missing directory: docs/arena"])
    if not snap.all_files:
        return CheckResult(name, "FAIL", "docs/arena contains 0 files", ["expected files under docs/arena/**"])

    total_bytes, sized, stat_errors = _compute_arena_size(snap)
    if stat_errors:
        return CheckResult(name, "FAIL", f"{len(stat_errors)} file stat error(s)", stat_errors)

    mb = total_bytes / (1024 * 1024)
    limit_mb = max_bytes / (1024 * 1024)
    if total_bytes >= max_bytes:
        top_contributors = [
            f"{rel}: {sz:,} bytes ({sz / (1024 * 1024):.2f} MB)"
            for sz, rel in sized[:5]
        ]
        return CheckResult(
            name,
            "FAIL",
            f"docs/arena/ total {total_bytes:,} bytes ({mb:.2f} MB) exceeds <{limit_mb:.2f} MB budget ({max_bytes:,} bytes)",
            top_contributors,
        )
    return CheckResult(
        name,
        "PASS",
        f"docs/arena/ total {total_bytes:,} bytes ({mb:.2f} MB) across {len(snap.all_files)} file(s), within <{limit_mb:.2f} MB budget",
    )


def audit_arena_hygiene(
    root: Path = ROOT,
    max_bytes: int = MAX_ARENA_BYTES,
) -> list[CheckResult]:
    snap = _build_snapshot(root)
    return [
        check_arena_secrets(snap.root, _snap=snap),
        check_arena_outbound_endpoints(snap.root, _snap=snap),
        check_arena_markdown_links(snap.root, _snap=snap),
        check_arena_ui_hygiene(snap.root, _snap=snap),
        check_arena_size_budget(snap.root, max_bytes=max_bytes, _snap=snap),
    ]


audit_repo = audit_arena_hygiene


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
        lines.append(f"[{res.status}] {res.name}: {res.summary}")
        for detail in res.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Audit docs/arena/** for zero secrets/credentials, zero live outbound LLM endpoints, "
            "clean relative markdown links and image refs, pure ASCII comment-free UI files, and <15 MB size budget."
        )
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Run strict arena hygiene checks and exit non-zero on any failure",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON hygiene audit report",
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository root directory containing docs/arena/",
    )
    ap.add_argument(
        "--max-bytes",
        type=int,
        default=MAX_ARENA_BYTES,
        help="Maximum allowed total byte budget for docs/arena/ (default: 15 MiB)",
    )
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    snap = _build_snapshot(args.root)
    results = [
        check_arena_secrets(snap.root, _snap=snap),
        check_arena_outbound_endpoints(snap.root, _snap=snap),
        check_arena_markdown_links(snap.root, _snap=snap),
        check_arena_ui_hygiene(snap.root, _snap=snap),
        check_arena_size_budget(snap.root, max_bytes=args.max_bytes, _snap=snap),
    ]
    total_bytes, _, _ = _compute_arena_size(snap) if snap.arena_exists else (0, [], [])
    elapsed = time.monotonic() - t0
    passed = not any(r.status == "FAIL" for r in results)

    if args.json:
        items: list[dict[str, Any]] = [asdict(r) for r in results]
        payload = {
            "check_mode": bool(args.check or True),
            "passed": passed,
            "elapsed_s": round(elapsed, 4),
            "arena_bytes": total_bytes,
            "max_arena_bytes": args.max_bytes,
            "results": items,
            "checks": items,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
