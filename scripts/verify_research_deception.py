from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import time
import tokenize
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CHAR = chr(35)
EM_DASH = "\u2014"
EN_DASH = "\u2013"

EXPECTED_TIERS_VERSION = "v1.4"
EXPECTED_V14_HASH = "a8f99c2537c91d72"
EXPECTED_V13_HASH = "8df71cf570bb48bc"

FLAGSHIP_REL = "docs/research-deception.md"
RESEARCH_DIR_REL = "docs/research"
SELF_CODE_RELS: tuple[str, ...] = (
    "scripts/verify_research_deception.py",
    "tests/test_research_deception.py",
    "scripts/simulate_research_proposals.py",
    "tests/test_simulate_research_proposals.py",
    "scripts/audit_transcript_biases.py",
    "tests/test_audit_transcript_biases.py",
    "scripts/audit_blackwell_channel_capacity.py",
    "tests/test_audit_blackwell_channel_capacity.py",
    "scripts/benchmark_research_moles.py",
    "tests/test_benchmark_research_moles.py",
    "scripts/audit_redteam_and_reward_integrity.py",
    "tests/test_audit_redteam_and_reward_integrity.py",
    "scripts/audit_research_scorecard.py",
    "tests/test_audit_research_scorecard.py",
)

FENCE_RX = re.compile(r"^\s*(?:>\s*)*(`{3,}|~{3,})([^\n`]*)?$")
H1_RX = re.compile(r"^\x23\s+\S+")
H2_RX = re.compile(r"^\x23\x23\s+\S+")
SUBSEC_SPLIT_RX = re.compile(r"(?m)^\x23{3,4}\s+")
HEADING_ANCHOR_RX = re.compile(r"^\x23{1,6}\s+(.+?)\s*$")
MD_LINK_RX = re.compile(r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\(([^)\n]+)\)")
BARE_URL_RX = re.compile(r"https?://[^\s<>\"'`|\]]+")
PROPOSAL_ID_RX = re.compile(r"\bP\d+\.\d+\b")
HEX16_RX = re.compile(r"\b[0-9a-f]{16}\b")
CO_AUTHORED_RX = re.compile(r"(?im)^\s*Co-Authored-By\s*:")

PLACEHOLDER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("todo_marker", re.compile(r"\b(?:TODO|FIXME|XXX)\s*:")),
    ("lorem_ipsum", re.compile(r"\blorem\s+ipsum\b", re.IGNORECASE)),
    ("placeholder_doi", re.compile(r"10\.(?:xxxx|0000|1234/placeholder)\b", re.IGNORECASE)),
    ("placeholder_arxiv", re.compile(r"arxiv\.org/(?:abs|pdf)/0000\.00000", re.IGNORECASE)),
)

BOGUS_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "example.com",
        "www.example.com",
        "example.org",
        "www.example.org",
        "example.net",
        "test.invalid",
        "placeholder.invalid",
    }
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("google_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])AIza[0-9A-Za-z_-]{20,}")),
    ("sk_api_key", re.compile(r"(?<![0-9A-Za-z+/_-])sk-(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}")),
    ("google_oauth", re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}")),
    ("provider_token", re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|xai-[A-Za-z0-9_-]{20,})\b")),
    ("private_key_pem", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    (
        "secret_env_assignment",
        re.compile(
            r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|CANARY_WORLD_SECRET)"
            r"\s*=\s*['\"]?[A-Za-z0-9_-]{16,}"
        ),
    ),
    ("world_mole_dump", re.compile(r'"(?:mole|true_mole)"\s*:\s*"e\d{2}"')),
)

STALE_CLAIM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gap_not_established", re.compile(r"gap\s*(?:is\s+|:\s*)?not\s+established", re.IGNORECASE)),
    ("superseded_60_ci", re.compile(r"60%\s*\[\s*1%?\s*,\s*103%?\s*\]")),
    ("superseded_68_ci", re.compile(r"68%\s*\[\s*43%?\s*,\s*91%?\s*\]")),
    ("unapproved_flash_gap_row", re.compile(r"gemini-3\.[56]-flash", re.IGNORECASE)),
    ("preregistered_seeds_0_29", re.compile(r"pre-regist\w*[^.\n]{0,40}\b0\s*-\s*29\b|\b0\s*-\s*29\b[^.\n]{0,40}pre-regist", re.IGNORECASE)),
    ("false_tiebreak_win", re.compile(r"tiebreak\w*[^.\n]{0,40}beats?\s+(?:the\s+)?base", re.IGNORECASE)),
)

CANARY_GROUNDING_MARKERS: tuple[str, ...] = (
    "v1.4",
    "plant_canary",
    "interview",
    "SolverPolicy",
    "TierParams",
    "canary/rules.py",
    "canary/env.py",
    "canary/social",
    "canary/mole",
    "PublicDayFacts",
    "MoleStrategy",
    "fingerprint_accuracy",
    "interview_lr",
    "a8f99c2537c91d72",
    "0.322",
    "0.499",
)

CANARY_TARGET_SURFACES: tuple[str, ...] = (
    "canary/rules.py",
    "canary/env.py",
    "canary/social",
    "canary/mole",
    "canary/solver",
    "canary/text",
    "train/",
)

V14_HARD_NUMERIC_FIELDS: tuple[str, ...] = (
    "n_employees",
    "n_days",
    "p_leak",
    "leak_damage",
    "canary_cost",
    "canaries_per_day",
    "max_variants",
    "restrict_cost_per_day",
    "actions_per_day",
    "tool_call_cap",
    "interview_lr",
    "p_evasive_innocent",
    "fingerprint_accuracy",
    "framing_rate",
)

DOI_EXTRACT_RX = re.compile(
    r"^https?://(?:(?:dx\.)?doi\.org|api\.crossref\.org/works)/(10\.\d{4,9}/\S+)$",
    re.IGNORECASE,
)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) CanaryResearchVerifier/1.0"

HttpFetcher = Callable[[str, float], tuple[int, str]]


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class CodeFence:
    start_line: int
    lang: str
    content: str


def _rel_str(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _redact(token: str) -> str:
    if len(token) <= 8:
        return token[:3] + "..."
    return token[:6] + "..."


def discover_research_docs(root: Path, explicit_docs: list[Path] | None = None) -> list[Path]:
    if explicit_docs:
        out: list[Path] = []
        for p in explicit_docs:
            resolved = p if p.is_absolute() else (root / p)
            out.append(resolved.resolve())
        return out

    found: list[Path] = []
    flagship = root / FLAGSHIP_REL
    if flagship.is_file():
        found.append(flagship.resolve())
    research_dir = root / RESEARCH_DIR_REL
    if research_dir.is_dir():
        for md in sorted(research_dir.glob("*.md")):
            if md.is_file():
                found.append(md.resolve())
    return found


def _parse_markdown_fences(text: str) -> tuple[list[str], list[CodeFence], int | None]:
    prose_lines: list[str] = []
    fences: list[CodeFence] = []
    in_fence = False
    fence_marker = ""
    fence_lang = ""
    fence_start = 0
    fence_buf: list[str] = []

    for lineno, line in enumerate(text.splitlines(), 1):
        m = FENCE_RX.match(line)
        if not in_fence:
            if m is not None:
                in_fence = True
                fence_marker = m.group(1)
                fence_lang = (m.group(2) or "").strip().split()[0] if (m.group(2) or "").strip() else ""
                fence_start = lineno
                fence_buf = []
                prose_lines.append("")
            else:
                prose_lines.append(line)
        else:
            prose_lines.append("")
            if (
                m is not None
                and m.group(1)[0] == fence_marker[0]
                and len(m.group(1)) >= len(fence_marker)
                and not (m.group(2) or "").strip()
            ):
                fences.append(CodeFence(start_line=fence_start, lang=fence_lang, content="\n".join(fence_buf)))
                in_fence = False
                fence_marker = ""
                fence_lang = ""
                fence_buf = []
            else:
                fence_buf.append(line)

    unclosed = fence_start if in_fence else None
    return prose_lines, fences, unclosed


def _clean_extracted_url(raw_url: str) -> str:
    url = raw_url.strip()
    while url and url[-1] in ".,;:!?\"'":
        url = url[:-1]
    while url.endswith(")") and url.count(")") > url.count("("):
        url = url[:-1]
    while url.endswith("]") and url.count("]") > url.count("["):
        url = url[:-1]
    while url and url[-1] in ".,;:!?":
        url = url[:-1]
    return url


def _slugify_heading(heading_text: str) -> str:
    cleaned = re.sub(r"`+", "", heading_text.strip().lower())
    cleaned = re.sub(r"[^\w\s-]", "", cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned).strip("-")
    return cleaned


def _extract_heading_slugs(prose_lines: list[str]) -> set[str]:
    slugs: set[str] = set()
    counts: dict[str, int] = {}
    for line in prose_lines:
        m = HEADING_ANCHOR_RX.match(line)
        if m is None:
            continue
        base = _slugify_heading(m.group(1))
        if not base:
            continue
        idx = counts.get(base, 0)
        counts[base] = idx + 1
        slugs.add(base if idx == 0 else f"{base}-{idx}")
    return slugs


def _extract_blockquotes(prose_lines: list[str]) -> list[tuple[int, str]]:
    quotes: list[tuple[int, str]] = []
    cur_start = 0
    cur_parts: list[str] = []
    for lineno, line in enumerate(prose_lines, 1):
        stripped = line.lstrip()
        if stripped.startswith(">"):
            body = stripped.lstrip(">").strip()
            if not cur_parts:
                cur_start = lineno
            if body:
                cur_parts.append(body)
        else:
            if cur_parts:
                quotes.append((cur_start, " ".join(cur_parts)))
                cur_parts = []
    if cur_parts:
        quotes.append((cur_start, " ".join(cur_parts)))
    return quotes


def check_doc_structure(
    root: Path,
    docs: list[Path],
    require_flagship: bool = False,
    explicit_mode: bool = False,
) -> CheckResult:
    name = "Research Target & Markdown Structure Audit"
    if not docs:
        return CheckResult(name, "FAIL", f"no research markdown files found under {root}")

    failures: list[str] = []
    warnings: list[str] = []
    flagship_path = (root / FLAGSHIP_REL).resolve()

    if not explicit_mode and not flagship_path.is_file():
        msg = f"missing flagship synthesis {FLAGSHIP_REL}"
        if require_flagship:
            failures.append(msg)
        else:
            warnings.append(f"{msg} (only per-topic docs/research/*.md present so far)")

    total_fences = 0
    json_blocks = 0

    for doc in docs:
        rel = _rel_str(doc, root)
        if not doc.is_file():
            failures.append(f"{rel}: file does not exist")
            continue
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{rel}: unreadable UTF-8 ({exc})")
            continue

        if not text.strip():
            failures.append(f"{rel}: empty markdown file")
            continue

        prose_lines, fences, unclosed = _parse_markdown_fences(text)
        total_fences += len(fences)
        if unclosed is not None:
            failures.append(f"{rel}:{unclosed}: unclosed fenced code block")

        h1_count = sum(1 for ln in prose_lines if H1_RX.match(ln))
        h2_count = sum(1 for ln in prose_lines if H2_RX.match(ln))
        if h1_count == 0:
            failures.append(f"{rel}: missing top-level H1 heading")
        if h2_count < 2:
            failures.append(f"{rel}: expected at least 2 H2 sections, found {h2_count}")

        for fence in fences:
            if fence.lang.lower() == "json" and "..." not in fence.content:
                json_blocks += 1
                try:
                    json.loads(fence.content)
                except ValueError as exc:
                    failures.append(f"{rel}:{fence.start_line}: invalid JSON code block ({exc})")

    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} structure error(s) across {len(docs)} doc(s)", failures)
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"{len(docs)} doc(s) structurally valid ({total_fences} code fences, {json_blocks} JSON blocks); {len(warnings)} warning(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"{len(docs)} doc(s) structurally valid ({total_fences} code fences, {json_blocks} JSON blocks verified)",
    )


def _python_comment_violations(py_path: Path, rel: str) -> list[str]:
    errs: list[str] = []
    try:
        raw = py_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{rel}: unreadable Python file ({exc})"]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    except tokenize.TokenError as exc:
        return [f"{rel}: tokenize error ({exc})"]
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            lineno, col = tok.start
            errs.append(f"{rel}:{lineno}:{col + 1}: forbidden Python comment")
    return errs


def check_hygiene(root: Path, docs: list[Path], extra_py_files: list[Path] | None = None) -> CheckResult:
    name = "Typography, Comment & Secret Hygiene"
    targets: list[Path] = [p for p in docs if p.is_file()]
    py_targets: list[Path] = []
    if extra_py_files is not None:
        py_targets.extend(p for p in extra_py_files if p.is_file())
    else:
        for rel_py in SELF_CODE_RELS:
            cand = root / rel_py
            if cand.is_file():
                py_targets.append(cand.resolve())

    seen_paths: set[Path] = set()
    all_targets: list[Path] = []
    for p in [*targets, *py_targets]:
        rp = p.resolve()
        if rp not in seen_paths:
            seen_paths.add(rp)
            all_targets.append(rp)

    violations: list[str] = []

    for path in all_targets:
        rel = _rel_str(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"{rel}: unreadable UTF-8 ({exc})")
            continue

        for lineno, line in enumerate(text.splitlines(), 1):
            em_col = line.find(EM_DASH)
            if em_col != -1:
                violations.append(f"{rel}:{lineno}:{em_col + 1}: forbidden em-dash (U+2014); use ASCII '-'")
            en_col = line.find(EN_DASH)
            if en_col != -1:
                violations.append(f"{rel}:{lineno}:{en_col + 1}: forbidden en-dash (U+2013); use ASCII '-'")

        for m_co in CO_AUTHORED_RX.finditer(text):
            lineno = text.count("\n", 0, m_co.start()) + 1
            violations.append(f"{rel}:{lineno}: forbidden Co-Authored-By line")

        if path.suffix == ".md":
            for label, rx in PLACEHOLDER_PATTERNS:
                for m_ph in rx.finditer(text):
                    lineno = text.count("\n", 0, m_ph.start()) + 1
                    violations.append(f"{rel}:{lineno}: placeholder marker ({label}: {m_ph.group(0)!r})")

        for kind, rx in SECRET_PATTERNS:
            for m_sec in rx.finditer(text):
                tok = m_sec.group(0)
                if rel.startswith("tests/") and any(k in tok.lower() for k in ("fake", "fixture", "synthetic")):
                    continue
                lineno = text.count("\n", 0, m_sec.start()) + 1
                violations.append(f"{rel}:{lineno}: secret/leak pattern ({kind}: {_redact(tok)})")

        if path.suffix == ".py":
            violations.extend(_python_comment_violations(path, rel))

    if violations:
        return CheckResult(
            name,
            "FAIL",
            f"{len(violations)} hygiene violation(s) across {len(all_targets)} file(s)",
            violations,
        )
    return CheckResult(
        name,
        "PASS",
        f"{len(all_targets)} file(s) clean (0 em/en-dashes, 0 Python comments, 0 Co-Authored-By, 0 secrets)",
    )


def _validate_url_syntax(url: str) -> str | None:
    if any(ch.isspace() for ch in url) or "<" in url or ">" in url:
        return "contains whitespace or angle brackets"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return f"unsupported scheme {parsed.scheme!r}"
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        return f"invalid host {host!r}"
    if host in BOGUS_HOSTS or host.endswith((".invalid", ".example", ".localhost")):
        return f"placeholder/local host {host!r}"
    for label, rx in PLACEHOLDER_PATTERNS:
        if rx.search(url):
            return f"placeholder URL ({label})"
    return None


def _extract_doi(url: str) -> str | None:
    m = DOI_EXTRACT_RX.match(url)
    if m is None:
        return None
    doi = urllib.parse.unquote(m.group(1)).strip().rstrip("/")
    return doi if doi else None


def _verify_doi_handle(doi: str, timeout_s: float) -> tuple[int, str]:
    encoded = urllib.parse.quote(doi, safe="/")
    api_url = f"https://doi.org/api/handles/{encoded}"
    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            code = int(resp.getcode() or 200)
            raw = resp.read(65536).decode("utf-8", errors="replace")
            payload = json.loads(raw)
            rc = payload.get("responseCode")
            if code == 200 and rc == 1 and payload.get("values"):
                return 200, "doi-handle-verified"
            return 404, f"doi-handle-responseCode-{rc}"
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, "doi-not-found"
        return int(exc.code), f"doi-handle-http-{exc.code}"
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        return 0, f"doi-handle-error:{type(exc).__name__}"


def default_http_fetcher(url: str, timeout_s: float = 10.0) -> tuple[int, str]:
    headers_head = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    }
    req_head = urllib.request.Request(url, headers=headers_head, method="HEAD")
    last_code = 0
    last_reason = "unreachable"
    try:
        with urllib.request.urlopen(req_head, timeout=timeout_s) as resp:
            code = int(resp.getcode() or 200)
            if 200 <= code < 400:
                return code, "ok"
            last_code = code
            last_reason = f"http-{code}"
    except urllib.error.HTTPError as exc:
        last_code = int(exc.code)
        last_reason = f"http-{exc.code}"
        if exc.code in {404, 410}:
            doi = _extract_doi(url)
            if doi is not None:
                return _verify_doi_handle(doi, timeout_s)
            return last_code, last_reason
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        last_code = 0
        last_reason = f"{type(exc).__name__}"

    headers_get = dict(headers_head)
    headers_get["Range"] = "bytes=0-4096"
    req_get = urllib.request.Request(url, headers=headers_get, method="GET")
    try:
        with urllib.request.urlopen(req_get, timeout=timeout_s) as resp:
            code = int(resp.getcode() or 200)
            resp.read(512)
            if 200 <= code < 400:
                return code, "ok"
            last_code = code
            last_reason = f"http-{code}"
    except urllib.error.HTTPError as exc:
        last_code = int(exc.code)
        last_reason = f"http-{exc.code}"
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        last_code = 0
        last_reason = f"{type(exc).__name__}"

    doi = _extract_doi(url)
    if doi is not None and last_code in {0, 400, 401, 403, 406, 429, 500, 502, 503}:
        doi_code, doi_reason = _verify_doi_handle(doi, timeout_s)
        if doi_code == 200 or doi_code == 404:
            return doi_code, doi_reason

    return last_code, last_reason


def extract_urls_and_quotes(root: Path, docs: list[Path]) -> tuple[dict[str, list[str]], int]:
    url_locations: dict[str, list[str]] = {}
    total_quotes = 0
    for doc in docs:
        if not doc.is_file():
            continue
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = _rel_str(doc, root)
        prose_lines, _, _ = _parse_markdown_fences(text)
        quotes = [q for q in _extract_blockquotes(prose_lines) if len(q[1].strip()) >= 20]
        total_quotes += len(quotes)
        for lineno, line in enumerate(prose_lines, 1):
            line_urls: list[str] = []
            for m_md in MD_LINK_RX.finditer(line):
                target = m_md.group(1).strip()
                if target.startswith(("http://", "https://")):
                    target = target.split()[0]
                    line_urls.append(_clean_extracted_url(target))
            for m_bare in BARE_URL_RX.finditer(line):
                line_urls.append(_clean_extracted_url(m_bare.group(0)))
            for u in line_urls:
                if u:
                    url_locations.setdefault(u, []).append(f"{rel}:{lineno}")
    return url_locations, total_quotes


def check_citations_and_quotes(
    root: Path,
    docs: list[Path],
    check_http: bool = False,
    strict_http: bool = False,
    timeout_s: float = 10.0,
    max_workers: int = 6,
    http_fetcher: HttpFetcher | None = None,
) -> CheckResult:
    name = "Citation URLs & Verbatim Quotes Grounding"
    failures: list[str] = []
    warnings: list[str] = []
    url_locations: dict[str, list[str]] = {}
    total_quotes = 0
    total_cit_blocks = 0

    slug_cache: dict[Path, set[str]] = {}

    def _slugs_for(md_file: Path) -> set[str]:
        rp = md_file.resolve()
        if rp not in slug_cache:
            try:
                p_lines, _, _ = _parse_markdown_fences(rp.read_text(encoding="utf-8"))
                slug_cache[rp] = _extract_heading_slugs(p_lines)
            except (OSError, UnicodeDecodeError):
                slug_cache[rp] = set()
        return slug_cache[rp]

    for doc in docs:
        if not doc.is_file():
            continue
        rel = _rel_str(doc, root)
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        prose_lines, _, _ = _parse_markdown_fences(text)
        prose_joined = "\n".join(prose_lines)

        doc_urls: list[str] = []
        for lineno, line in enumerate(prose_lines, 1):
            for m_md in MD_LINK_RX.finditer(line):
                raw_target = m_md.group(1).strip()
                if not raw_target or raw_target.startswith("mailto:"):
                    continue
                target_tok = raw_target.split()[0].strip("<>")
                if target_tok.startswith(("http://", "https://")):
                    u = _clean_extracted_url(target_tok)
                    doc_urls.append(u)
                    url_locations.setdefault(u, []).append(f"{rel}:{lineno}")
                elif target_tok.startswith(HASH_CHAR):
                    anchor = target_tok[1:].strip().lower()
                    if anchor and anchor not in _slugs_for(doc):
                        failures.append(f"{rel}:{lineno}: broken internal heading anchor {target_tok!r}")
                else:
                    path_part, _, frag = target_tok.partition(HASH_CHAR)
                    path_clean = urllib.parse.unquote(path_part)
                    cand_rel = (doc.parent / path_clean).resolve()
                    cand_root = (root / path_clean.lstrip("/")).resolve()
                    resolved_target = cand_rel if cand_rel.exists() else (cand_root if cand_root.exists() else None)
                    if resolved_target is None:
                        failures.append(f"{rel}:{lineno}: broken relative markdown link {target_tok!r}")
                    elif frag and resolved_target.is_file() and resolved_target.suffix == ".md":
                        if frag.lower() not in _slugs_for(resolved_target):
                            failures.append(f"{rel}:{lineno}: broken anchor {frag!r} in {path_part!r}")

            for m_bare in BARE_URL_RX.finditer(line):
                u = _clean_extracted_url(m_bare.group(0))
                if u:
                    doc_urls.append(u)
                    if f"{rel}:{lineno}" not in url_locations.get(u, []):
                        url_locations.setdefault(u, []).append(f"{rel}:{lineno}")

        quotes = [q for q in _extract_blockquotes(prose_lines) if len(q[1].strip()) >= 20]
        total_quotes += len(quotes)

        if not doc_urls:
            failures.append(f"{rel}: zero primary http(s) citation URLs found")
        if not quotes:
            failures.append(f"{rel}: zero substantive verbatim blockquotes ('> ...') found")

        subsections = SUBSEC_SPLIT_RX.split(prose_joined)
        for sub in subsections[1:]:
            title_line = sub.splitlines()[0].strip() if sub.splitlines() else "untitled"
            if "**Citation" in sub or "- Citation:" in sub:
                total_cit_blocks += 1
                has_url = bool(BARE_URL_RX.search(sub))
                sub_quotes = [q for q in _extract_blockquotes(sub.splitlines()) if len(q[1].strip()) >= 20]
                if not has_url:
                    failures.append(f"{rel}: citation subsection {title_line!r} missing http(s) URL")
                if not sub_quotes:
                    failures.append(f"{rel}: citation subsection {title_line!r} missing verbatim blockquote")

    for u, locs in sorted(url_locations.items()):
        err = _validate_url_syntax(u)
        if err is not None:
            failures.append(f"{locs[0]}: invalid URL {u!r} ({err})")

    http_checked = 0
    if check_http and url_locations:
        fetcher = http_fetcher if http_fetcher is not None else default_http_fetcher
        valid_urls = [u for u in sorted(url_locations) if _validate_url_syntax(u) is None]
        http_checked = len(valid_urls)

        def _probe(u: str) -> tuple[str, int, str]:
            code, reason = fetcher(u, timeout_s)
            return u, code, reason

        workers = max(1, min(max_workers, len(valid_urls)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for u, code, reason in pool.map(_probe, valid_urls):
                loc = url_locations[u][0]
                if 200 <= code < 400:
                    continue
                if code in {401, 403, 429} and not strict_http:
                    warnings.append(f"{loc}: HTTP {code} ({reason}) on {u}")
                else:
                    failures.append(f"{loc}: dead/unreachable URL {u} -> code={code} ({reason})")

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} citation/quote issue(s) ({len(url_locations)} unique URLs, {total_quotes} verbatim quotes)",
            failures,
        )
    http_note = f", {http_checked}/{len(url_locations)} live HTTP-verified" if check_http else ""
    if warnings:
        return CheckResult(
            name,
            "WARN",
            f"{len(url_locations)} unique URLs, {total_quotes} verbatim quotes, {total_cit_blocks} citation blocks{http_note}; {len(warnings)} HTTP warning(s)",
            warnings,
        )
    return CheckResult(
        name,
        "PASS",
        f"{len(url_locations)} unique URLs, {total_quotes} verbatim quotes, {total_cit_blocks} citation blocks verified{http_note}",
    )


def compute_tier_hash(tiers: dict[str, Any], known_v_mode: bool) -> str:
    obj = {"tiers": {k: v.to_dict() for k, v in tiers.items()}, "known_v_mode": known_v_mode}
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=list).encode()).hexdigest()[:16]


def interview_kl_nats(p0: float, lr: float) -> float:
    pm = min(0.999999, p0 * lr)
    return pm * math.log(pm / p0) + (1.0 - pm) * math.log((1.0 - pm) / (1.0 - p0))


def canary_mi_nats(accuracy: float, k_variants: int) -> float:
    flip = (1.0 - accuracy) / float(k_variants - 1)
    return math.log(float(k_variants)) + accuracy * math.log(accuracy) + (1.0 - accuracy) * math.log(flip)


def load_ground_truth_numbers(root: Path) -> dict[str, Any]:
    from canary import rules

    v14_hash = compute_tier_hash(rules.TIERS, rules.KNOWN_V_MODE)
    v13_hash = compute_tier_hash(rules.TIERS_V13, rules.KNOWN_V_MODE)
    hard = rules.TIERS["hard"]
    medium = rules.TIERS["medium"]
    easy = rules.TIERS["easy"]

    gt: dict[str, Any] = {
        "tiers_version": rules.TIERS_VERSION,
        "v14_hash": v14_hash,
        "v13_hash": v13_hash,
        "hard_params": hard.to_dict(),
        "kl_easy": interview_kl_nats(easy.p_evasive_innocent, easy.interview_lr),
        "kl_medium": interview_kl_nats(medium.p_evasive_innocent, medium.interview_lr),
        "kl_hard": interview_kl_nats(hard.p_evasive_innocent, hard.interview_lr),
        "canary_mi_hard": canary_mi_nats(hard.fingerprint_accuracy, hard.max_variants),
    }

    fa_path = root / "results" / "failure_analysis_v1.4.json"
    if fa_path.is_file():
        fa = json.loads(fa_path.read_text(encoding="utf-8"))
        summary = fa.get("summary") or {}
        gt["failure_analysis"] = summary
    return gt


def check_repo_numbers(root: Path, docs: list[Path]) -> CheckResult:
    name = "Exact Canary Repo & Information-Theoretic Numbers Audit"
    failures: list[str] = []

    try:
        gt = load_ground_truth_numbers(root)
    except Exception as exc:
        return CheckResult(name, "FAIL", f"failed loading Canary ground-truth rules/results ({exc})")

    if gt["tiers_version"] != EXPECTED_TIERS_VERSION:
        failures.append(f"canary.rules.TIERS_VERSION expected {EXPECTED_TIERS_VERSION!r}, got {gt['tiers_version']!r}")
    if gt["v14_hash"] != EXPECTED_V14_HASH:
        failures.append(f"canary.rules v1.4 hash expected {EXPECTED_V14_HASH}, got {gt['v14_hash']}")
    if gt["v13_hash"] != EXPECTED_V13_HASH:
        failures.append(f"canary.rules v1.3 hash expected {EXPECTED_V13_HASH}, got {gt['v13_hash']}")

    hard_params: dict[str, Any] = gt["hard_params"]
    fa_summary: dict[str, Any] = gt.get("failure_analysis") or {}
    opencode_sum: dict[str, Any] = fa_summary.get("opencode") or {}
    solver_sum: dict[str, Any] = fa_summary.get("solver") or {}
    gap_sum: dict[str, Any] = fa_summary.get("gap") or {}

    checked_claims = 0

    for doc in docs:
        if not doc.is_file():
            continue
        rel = _rel_str(doc, root)
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        prose_lines, _, _ = _parse_markdown_fences(text)
        prose_text = "\n".join(prose_lines)

        for label, rx in STALE_CLAIM_PATTERNS:
            for m_stale in rx.finditer(prose_text):
                lineno = prose_text.count("\n", 0, m_stale.start()) + 1
                failures.append(f"{rel}:{lineno}: stale claim ({label}: {m_stale.group(0)!r})")

        marker_hits = sum(1 for mk in CANARY_GROUNDING_MARKERS if mk in text)
        if marker_hits < 2:
            failures.append(f"{rel}: insufficient Canary repo grounding (matched {marker_hits} canonical markers, expected >= 2)")

        for lineno, line in enumerate(prose_lines, 1):
            low = line.lower()

            if (("v1.4" in low and "hash" in low) or "frozen hash" in low or "tier hash" in low) and "v1.3" not in low:
                for h_match in HEX16_RX.findall(line):
                    checked_claims += 1
                    if h_match != EXPECTED_V14_HASH:
                        failures.append(
                            f"{rel}:{lineno}: v1.4 tier hash mismatch (claimed {h_match}, expected {EXPECTED_V14_HASH})"
                        )

            if (
                "v1.4" in low
                and "hard" in low
                and not any(x in low for x in ("v1.3", "v1.2", "v1.5", "v1.6", "easy", "medium", "expert", "shrink"))
            ):
                for param in V14_HARD_NUMERIC_FIELDS:
                    pat = re.compile(rf"\b{re.escape(param)}\s*=\s*(-?\d+(?:\.\d+)?)\b")
                    for pm in pat.finditer(line):
                        claimed = float(pm.group(1))
                        expected = float(hard_params[param])
                        checked_claims += 1
                        if abs(claimed - expected) > 1e-6:
                            failures.append(
                                f"{rel}:{lineno}: v1.4 hard {param}={claimed} does not match canary.rules ({expected})"
                            )

            if line.lstrip().startswith("|") and "`interview`" in line and "nats" in line:
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 6:
                    first_cell = cells[0].lower()
                    kl_match = re.search(r"(\d+\.\d+)\s*`?\s*nats", cells[5])
                    if kl_match is not None:
                        claimed_kl = float(kl_match.group(1))
                        exp_kl = None
                        tier_lbl = ""
                        if "easy" in first_cell and "1.5" in first_cell:
                            exp_kl = gt["kl_easy"]
                            tier_lbl = "easy"
                        elif "medium" in first_cell and "1.3" in first_cell:
                            exp_kl = gt["kl_medium"]
                            tier_lbl = "medium"
                        elif "hard" in first_cell and "1.2" in first_cell:
                            exp_kl = gt["kl_hard"]
                            tier_lbl = "hard"
                        if exp_kl is not None:
                            checked_claims += 1
                            if abs(claimed_kl - exp_kl) > 1.5e-4:
                                failures.append(
                                    f"{rel}:{lineno}: interview ({tier_lbl}) KL claimed {claimed_kl:.5f} nats, expected {exp_kl:.5f}"
                                )

            if opencode_sum and solver_sum and gap_sum:
                for m_gem in re.finditer(r"\b(0\.\d{3})\s*(?:\+/-|\u00b1)\s*0\.199\b", line):
                    val = float(m_gem.group(1))
                    exp = float(opencode_sum["score"])
                    checked_claims += 1
                    if abs(val - exp) > 0.002:
                        failures.append(
                            f"{rel}:{lineno}: OpenCode gemini-4-carbon v1.4 hard score {val:.3f} != {exp:.3f}"
                        )
                for m_sol in re.finditer(r"\b(0\.\d{3})\s*(?:\+/-|\u00b1)\s*0\.119\b", line):
                    val = float(m_sol.group(1))
                    exp = float(solver_sum["score"])
                    checked_claims += 1
                    if abs(val - exp) > 0.002:
                        failures.append(
                            f"{rel}:{lineno}: SolverPolicy v1.4 hard score {val:.3f} != {exp:.3f}"
                        )
                for m_rg in re.finditer(r"raw(?:\s+paired)?\s+gap[^0-9\n]{0,25}(\d+\.\d+)\s*V\b", line, re.IGNORECASE):
                    val = float(m_rg.group(1))
                    exp = float(gap_sum["raw_gap"])
                    checked_claims += 1
                    if abs(val - exp) > 0.02:
                        failures.append(f"{rel}:{lineno}: raw paired gap {val:.2f} V != {exp:.2f} V")
                for m_lg in re.finditer(r"luck-adjusted\s+gap[^0-9\n]{0,25}(\d+\.\d+)\s*V\b", line, re.IGNORECASE):
                    val = float(m_lg.group(1))
                    exp = float(gap_sum["la_gap"])
                    checked_claims += 1
                    if abs(val - exp) > 0.02:
                        failures.append(f"{rel}:{lineno}: luck-adjusted gap {val:.2f} V != {exp:.2f} V")
                for m_days in re.finditer(r"`?(\d+)`?\s+of(?:\s+the)?\s+`?(\d+)`?\s+(?:under-planted\s+)?days", line):
                    d_full = int(m_days.group(1))
                    d_lt2 = int(m_days.group(2))
                    if d_lt2 == int(opencode_sum["days_lt2_canaries"]):
                        checked_claims += 1
                        if d_full != int(opencode_sum["days_lt2_full"]):
                            failures.append(
                                f"{rel}:{lineno}: full-budget under-planted days {d_full}/{d_lt2} != {opencode_sum['days_lt2_full']}/{opencode_sum['days_lt2_canaries']}"
                            )

    if failures:
        return CheckResult(
            name,
            "FAIL",
            f"{len(failures)} repo-number discrepancy/grounding error(s)",
            failures,
        )
    return CheckResult(
        name,
        "PASS",
        f"frozen v1.4 ({EXPECTED_V14_HASH}) & live Canary repo metrics verified ({checked_claims} quantitative claim checks)",
    )


def check_proposals(root: Path, docs: list[Path]) -> CheckResult:
    name = "Concrete Proposals & Zero-Leakage Design Audit"
    failures: list[str] = []
    all_proposal_ids: set[str] = set()
    proposal_docs = 0

    for doc in docs:
        if not doc.is_file():
            continue
        rel = _rel_str(doc, root)
        try:
            text = doc.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        pids = set(PROPOSAL_ID_RX.findall(text))
        all_proposal_ids.update(pids)
        is_flagship = doc.resolve() == (root / FLAGSHIP_REL).resolve()
        declares_proposals = is_flagship or bool(pids) or bool(re.search(r"(?im)^\x23{2,3}\s+.*proposal", text))

        if not declares_proposals:
            continue

        proposal_docs += 1
        if not pids and not re.search(r"(?im)^\x23{3,4}\s+Proposal\b", text):
            failures.append(f"{rel}: proposal section found without concrete Proposal IDs (e.g. P1.1) or H3 Proposal headings")

        if not any(surf in text for surf in CANARY_TARGET_SURFACES):
            failures.append(f"{rel}: proposals do not reference any concrete Canary module path")

        low = text.lower()
        has_leakage_guard = any(
            kw in low
            for kw in (
                "zero-leakage",
                "zero leakage",
                "zero hidden mole leakage",
                "zero mole leakage",
                "zero-mole-info",
                "publicdayfacts",
                "catchability",
                "frozen hash",
            )
        )
        if not has_leakage_guard:
            failures.append(
                f"{rel}: proposals missing explicit zero-mole-leakage / catchability / frozen-hash invariant"
            )

        _, fences, _ = _parse_markdown_fences(text)
        for fence in fences:
            if fence.lang.lower() == "json" and "..." not in fence.content:
                try:
                    parsed = json.loads(fence.content)
                except ValueError:
                    continue
                if isinstance(parsed, dict) and {"name", "rules", "default"} <= set(parsed.keys()):
                    if not isinstance(parsed.get("name"), str) or not parsed["name"].strip():
                        failures.append(f"{rel}:{fence.start_line}: MoleStrategy JSON missing non-empty 'name'")
                    if not isinstance(parsed.get("rules"), list):
                        failures.append(f"{rel}:{fence.start_line}: MoleStrategy JSON 'rules' must be a list")
                    if not isinstance(parsed.get("default"), dict) or "leak" not in parsed["default"]:
                        failures.append(f"{rel}:{fence.start_line}: MoleStrategy JSON 'default' missing 'leak' key")

    if proposal_docs == 0:
        return CheckResult(name, "FAIL", "zero research documents define concrete Canary proposals")
    if failures:
        return CheckResult(name, "FAIL", f"{len(failures)} proposal specification issue(s)", failures)

    sorted_ids = ", ".join(sorted(all_proposal_ids)) if all_proposal_ids else "named proposals"
    return CheckResult(
        name,
        "PASS",
        f"{proposal_docs} proposal doc(s) verified ({sorted_ids}; module targets & leakage/catchability guards present)",
    )


def load_protected_prefixes(root: Path) -> list[str]:
    pf = root / ".github" / "protected-paths.txt"
    if not pf.is_file():
        return []
    prefixes: list[str] = []
    for raw in pf.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith(HASH_CHAR):
            continue
        prefixes.append(s)
    return prefixes


def is_protected_path(rel_path: str, prefixes: list[str]) -> str | None:
    norm = rel_path.strip().lstrip("./")
    for pref in prefixes:
        if pref.endswith("/"):
            if norm == pref[:-1] or norm.startswith(pref):
                return pref
        else:
            if norm == pref:
                return pref
    return None


def check_protected_paths(root: Path, base_ref: str = "origin/justSilas") -> CheckResult:
    name = "Protected Paths & Git Diff Guard"
    prefixes = load_protected_prefixes(root)
    if not prefixes:
        return CheckResult(name, "WARN", "no .github/protected-paths.txt found to enforce")

    if not (root / ".git").exists():
        return CheckResult(name, "WARN", f"{len(prefixes)} protected rules loaded (git metadata absent)")

    changed: set[str] = set()
    proc_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc_status.returncode == 0:
        for ln in proc_status.stdout.splitlines():
            if len(ln) >= 4:
                entry = ln[3:].strip()
                if " -> " in entry:
                    left, right = entry.split(" -> ", 1)
                    changed.add(left.strip().strip('"'))
                    changed.add(right.strip().strip('"'))
                else:
                    changed.add(entry.strip('"'))

    if base_ref:
        proc_ref = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", base_ref],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc_ref.returncode == 0:
            proc_diff = subprocess.run(
                ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc_diff.returncode == 0:
                for ln in proc_diff.stdout.splitlines():
                    if ln.strip():
                        changed.add(ln.strip())

    violations: list[str] = []
    for rel in sorted(changed):
        matched = is_protected_path(rel, prefixes)
        if matched is not None:
            violations.append(f"protected path touched: {rel} (matches {matched!r})")

    if violations:
        return CheckResult(name, "FAIL", f"{len(violations)} protected-path violation(s)", violations)
    return CheckResult(
        name,
        "PASS",
        f"0 protected paths touched across {len(changed)} modified/branch path(s) ({len(prefixes)} guard rules)",
    )


def verify_research_repo(
    root: Path = ROOT,
    explicit_docs: list[Path] | None = None,
    check_http: bool = False,
    strict_http: bool = False,
    timeout_s: float = 10.0,
    max_workers: int = 6,
    require_flagship: bool = False,
    base_ref: str = "origin/justSilas",
    http_fetcher: HttpFetcher | None = None,
) -> tuple[list[CheckResult], dict[str, Any]]:
    resolved_root = root.resolve()
    docs = discover_research_docs(resolved_root, explicit_docs=explicit_docs)
    explicit_mode = bool(explicit_docs)

    results = [
        check_doc_structure(resolved_root, docs, require_flagship=require_flagship, explicit_mode=explicit_mode),
        check_hygiene(resolved_root, docs),
        check_citations_and_quotes(
            resolved_root,
            docs,
            check_http=check_http,
            strict_http=strict_http,
            timeout_s=timeout_s,
            max_workers=max_workers,
            http_fetcher=http_fetcher,
        ),
        check_repo_numbers(resolved_root, docs),
        check_proposals(resolved_root, docs),
        check_protected_paths(resolved_root, base_ref=base_ref),
    ]

    url_map, quote_count = extract_urls_and_quotes(resolved_root, docs)
    proposal_ids: set[str] = set()
    for d in docs:
        if d.is_file():
            try:
                proposal_ids.update(PROPOSAL_ID_RX.findall(d.read_text(encoding="utf-8")))
            except (OSError, UnicodeDecodeError):
                pass

    meta = {
        "docs_checked": [_rel_str(d, resolved_root) for d in docs],
        "unique_url_count": len(url_map),
        "verbatim_quote_count": quote_count,
        "proposal_ids": sorted(proposal_ids),
        "http_enabled": check_http,
    }
    return results, meta


def format_report(results: list[CheckResult], meta: dict[str, Any], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
        lines.append(f"[{r.status}] {r.name}: {r.summary}")
        for detail in r.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"DOCS: {len(meta['docs_checked'])} ({', '.join(meta['docs_checked']) or 'none'}) | "
        f"URLS: {meta['unique_url_count']} | QUOTES: {meta['verbatim_quote_count']} | "
        f"PROPOSALS: {', '.join(meta['proposal_ids']) or 'none'}"
    )
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify Canary deception research grounding, citations, quotes, numbers, and hygiene.")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root to verify")
    ap.add_argument("--docs", type=Path, nargs="*", default=None, help="Explicit markdown doc path(s) to verify")
    ap.add_argument("--http", "--check-urls", dest="check_http", action="store_true", help="Live-verify all extracted HTTP(S) URLs and DOIs")
    ap.add_argument("--strict-http", action="store_true", help="Fail on HTTP 401/403/429 anti-bot statuses")
    ap.add_argument("--timeout", type=float, default=10.0, help="Per-URL timeout in seconds when --http is set")
    ap.add_argument("--workers", type=int, default=6, help="Concurrent HTTP worker threads when --http is set")
    ap.add_argument("--require-flagship", action="store_true", help="Fail if docs/research-deception.md is absent")
    ap.add_argument("--strict", action="store_true", help="Return non-zero on WARN as well as FAIL")
    ap.add_argument("--base-ref", type=str, default="origin/justSilas", help="Base git ref for protected-paths diff check")
    ap.add_argument("--json", action="store_true", help="Print JSON verification report")
    ap.add_argument("--out-json", type=Path, default=None, help="Optional file path to write JSON report")
    args = ap.parse_args(argv)

    t0 = time.monotonic()
    results, meta = verify_research_repo(
        root=args.root,
        explicit_docs=args.docs,
        check_http=args.check_http,
        strict_http=args.strict_http,
        timeout_s=args.timeout,
        max_workers=args.workers,
        require_flagship=args.require_flagship,
        base_ref=args.base_ref,
    )
    elapsed = time.monotonic() - t0
    failed = any(r.status == "FAIL" for r in results) or (
        args.strict and any(r.status == "WARN" for r in results)
    )

    payload = {
        "passed": not failed,
        "elapsed_s": round(elapsed, 4),
        **meta,
        "results": [asdict(r) for r in results],
    }

    if args.out_json is not None:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, meta, elapsed))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
