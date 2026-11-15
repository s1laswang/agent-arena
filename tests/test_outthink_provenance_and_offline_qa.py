from __future__ import annotations

import ast
import base64
import gzip
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import socket
import struct
import tokenize
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
LIVE_DEMO_DIR = ROOT / "demo" / "out-think-gemini"
LIVE_INDEX_HTML = LIVE_DEMO_DIR / "index.html"
LIVE_CASES_JS = LIVE_DEMO_DIR / "cases.js"
LIVE_MANIFEST_JS = LIVE_DEMO_DIR / "assets" / "manifest.js"
LIVE_ASSETS_MD = ROOT / "docs" / "demo" / "ASSETS.md"
LIVE_OUTTHINK_JSON = ROOT / "results" / "gemini" / "out_think_gemini.json"
LIVE_LADDER_EPISODES_GZ = ROOT / "results" / "gemini" / "ladder_episodes.jsonl.gz"
LIVE_LADDER_LEDGER_GZ = ROOT / "results" / "gemini" / "ladder_ledger.jsonl.gz"
LIVE_REFERENCE_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "reference"
LIVE_INPROC_CARBON_DIR = ROOT / "data" / "runs" / "committed" / "v1.4" / "inproc-gemini-4-carbon"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

HASH_CHAR = chr(35)
FORBIDDEN_DASHES: tuple[str, ...] = tuple(
    chr(cp) for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212)
)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_IEND_TRAILER = b"IEND\xaeB`\x82"
DATA_URI_IMAGE_RE = re.compile(
    r"data:image/(?:png|webp|gif|jpeg);base64,([A-Za-z0-9+/=]+)",
    re.IGNORECASE,
)

EXTERNAL_URL_START_RE = re.compile(
    r"^\s*(?:https?:|wss?:|ftp:|//|javascript:|vbscript:)",
    re.IGNORECASE,
)

ALLOWED_ATTRIBUTION_URL_PREFIXES: tuple[str, ...] = (
    "https://opengameart.org/",
    "https://creativecommons.org/",
    "https://kenney.nl/",
)

ALLOWED_XML_NAMESPACES: frozenset[str] = frozenset(
    {
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1999/xhtml",
        "http://www.w3.org/1999/xlink",
    }
)

EXECUTABLE_TAG_ATTRS: dict[str, tuple[str, ...]] = {
    "script": ("src",),
    "link": ("href", "imagesrcset"),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "track": ("src",),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data", "codebase", "archive"),
    "applet": ("code", "codebase", "archive"),
    "form": ("action",),
    "input": ("src", "formaction"),
    "button": ("formaction",),
    "base": ("href",),
    "image": ("href", "xlink:href"),
    "use": ("href", "xlink:href"),
}

FOOTER_CREDIT_TOKENS: tuple[str, ...] = (
    "footer",
    "provenance",
    "credit",
    "attribution",
    "license",
    "asset",
)

CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE | re.DOTALL)
CSS_IMPORT_RE = re.compile(
    r"@import\s+(?:url\(\s*)?(['\"]?)(.*?)\1\s*\)?",
    re.IGNORECASE | re.DOTALL,
)

JS_FETCH_RE = re.compile(
    r"(?<![A-Za-z0-9_$])(?:(?:window|globalThis|self)\s*\.\s*)?fetch\s*\("
)
JS_BRACKET_FETCH_RE = re.compile(
    r"(?:window|globalThis|self)\s*\[\s*['\"]fetch['\"]\s*\]"
)
JS_XHR_RE = re.compile(r"\bXMLHttpRequest\b")
JS_WEBSOCKET_RE = re.compile(r"\bWebSocket\s*\(|\bnew\s+WebSocket\b")
JS_EVENTSOURCE_RE = re.compile(r"\bEventSource\s*\(|\bnew\s+EventSource\b")
JS_SENDBEACON_RE = re.compile(r"\.sendBeacon\s*\(")
JS_DYNAMIC_IMPORT_EXT_RE = re.compile(
    r"\bimport\s*\(\s*['\"`]\s*(?:https?:|wss?:|//)",
    re.IGNORECASE,
)
JS_DOM_SRC_ASSIGN_RE = re.compile(
    r"\.(?:src|srcset|poster|data)\s*=\s*['\"`]\s*(?:https?:|wss?:|//)",
    re.IGNORECASE,
)
JS_SET_ATTR_EXT_RE = re.compile(
    r"\.setAttribute\s*\(\s*['\"](?:src|srcset|href|poster|data)['\"]\s*,\s*['\"`]\s*(?:https?:|wss?:|//)",
    re.IGNORECASE,
)
JS_PROTOCOL_REL_STR_RE = re.compile(
    r"(['\"`])\s*//[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[^\s'\"`<>)]*)?\1"
)
JS_WS_URL_RE = re.compile(r"\bwss?://[^\s'\"`<>)]+", re.IGNORECASE)
ANY_HTTP_URL_RE = re.compile(r"https?://[^\s'\"`<>)\]]+", re.IGNORECASE)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "google_api_key",
        re.compile(r"(?<![A-Za-z0-9+/])AI" + r"za[0-9A-Za-z_-]{20,}"),
    ),
    (
        "sk_secret_key",
        re.compile(r"(?<![A-Za-z0-9_-])s" + r"k-(?:proj-|ant-|live-|test-)?[0-9A-Za-z_-]{20,}"),
    ),
    (
        "google_oauth_ya29",
        re.compile(r"(?<![A-Za-z0-9_.-])ya" + r"29\.[0-9A-Za-z_.-]{20,}"),
    ),
    (
        "github_pat",
        re.compile(r"\b(?:gh" + r"p|gh" + r"o|gh" + r"u|gh" + r"s|gh" + r"r)_[0-9A-Za-z]{24,}\b"),
    ),
    (
        "aws_access_key",
        re.compile(r"\bAK" + r"IA[0-9A-Z]{16}\b"),
    ),
    (
        "private_key_pem",
        re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    ),
    (
        "hardcoded_api_env_key",
        re.compile(
            r"\b(?:GEMINI_API_KEY|GOOGLE_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
        ),
    ),
)

HARD_FORBIDDEN_ASSET_TERMS: tuple[str, ...] = (
    "spriters-resource",
    "spriters resource",
    "models-resource",
    "textures-resource",
    "shutterstock",
    "getty images",
    "adobe stock",
    "unity asset store",
    "unreal marketplace",
    "craftpix",
    "envato",
    "graphicriver",
    "all rights reserved",
    "cc-by-nc",
    "by-nc",
    "cc-by-nd",
    "by-nd",
)

PLACEHOLDER_AUTHORS: frozenset[str] = frozenset(
    {"", "tbd", "todo", "unknown", "n/a", "none", "placeholder", "author"}
)

MODEL_PRICES_PER_M: dict[str, tuple[float, float, float]] = {
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.5-flash": (0.75, 3.75, 0.075),
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-4-hydrogen": (1.50, 7.50, 0.075),
    "gemini-4-argon": (2.00, 10.00, 0.10),
    "gemini-4-carbon": (2.00, 10.00, 0.10),
}

VOID_HTML_TAGS: frozenset[str] = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


@pytest.fixture(autouse=True)
def _block_all_network_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Outbound network sockets are strictly blocked in offline QA")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(socket, "create_connection", _blocked_socket)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked_socket)


def _strip_validated_image_data_uris(text: str, label: str, violations: list[str]) -> str:
    def _repl(match: re.Match[str]) -> str:
        full_uri = match.group(0)
        b64_payload = match.group(1)
        try:
            raw = base64.b64decode(b64_payload, validate=True)
        except Exception as exc:
            violations.append(f"{label}: invalid base64 in image data URI ({exc})")
            return "data:image/invalid"
        if full_uri.lower().startswith("data:image/png;base64,") and not raw.startswith(PNG_SIGNATURE):
            violations.append(f"{label}: data:image/png;base64 payload missing PNG signature")
            return "data:image/non-png"
        return "data:image/validated"

    return DATA_URI_IMAGE_RE.sub(_repl, text)


def scan_text_for_secrets(text: str, label: str) -> list[str]:
    violations: list[str] = []
    scrubbed = _strip_validated_image_data_uris(text, label, violations)
    for secret_kind, pattern in SECRET_PATTERNS:
        for match in pattern.finditer(scrubbed):
            snippet = match.group(0)[:10] + "..."
            violations.append(f"{label}: leaked secret pattern ({secret_kind}: {snippet})")
    return violations


def scan_text_for_forbidden_dashes(text: str, label: str) -> list[str]:
    violations: list[str] = []
    for ch in FORBIDDEN_DASHES:
        if ch in text:
            violations.append(f"{label}: forbidden unicode dash U+{ord(ch):04X}")
    lower = text.lower()
    if "&mdash;" in lower or "&ndash;" in lower:
        violations.append(f"{label}: forbidden HTML dash entity")
    return violations


def _is_external_target(raw_target: str) -> bool:
    return bool(EXTERNAL_URL_START_RE.match(raw_target.strip()))


def _srcset_candidates(srcset_val: str) -> list[str]:
    out: list[str] = []
    for item in srcset_val.split(","):
        stripped = item.strip()
        if stripped:
            out.append(stripped.split()[0])
    return out


def scan_css_offline_violations(css_text: str, label: str) -> list[str]:
    violations: list[str] = []
    for match in CSS_URL_RE.finditer(css_text):
        target = match.group(2).strip()
        if not target or target.lower().startswith("data:"):
            continue
        if _is_external_target(target):
            violations.append(f"{label}: external CSS url({target!r}) is forbidden")
    for match in CSS_IMPORT_RE.finditer(css_text):
        target = match.group(2).strip()
        if _is_external_target(target):
            violations.append(f"{label}: external CSS @import {target!r} is forbidden")
    return violations


def _is_allowed_attribution_url(url: str) -> bool:
    clean = url.strip().rstrip(".,;:)")
    lower = clean.lower()
    if lower in ALLOWED_XML_NAMESPACES:
        return True
    return any(lower.startswith(prefix) for prefix in ALLOWED_ATTRIBUTION_URL_PREFIXES)


def scan_js_offline_violations(js_text: str, label: str) -> list[str]:
    violations: list[str] = []
    scrubbed = _strip_validated_image_data_uris(js_text, label, violations)

    if JS_FETCH_RE.search(scrubbed) or JS_BRACKET_FETCH_RE.search(scrubbed):
        violations.append(f"{label}: forbidden network fetch() call in JS")
    if JS_XHR_RE.search(scrubbed):
        violations.append(f"{label}: forbidden XMLHttpRequest usage in JS")
    if JS_WEBSOCKET_RE.search(scrubbed):
        violations.append(f"{label}: forbidden WebSocket() usage in JS")
    if JS_EVENTSOURCE_RE.search(scrubbed):
        violations.append(f"{label}: forbidden EventSource() usage in JS")
    if JS_SENDBEACON_RE.search(scrubbed):
        violations.append(f"{label}: forbidden navigator.sendBeacon() usage in JS")
    if JS_DYNAMIC_IMPORT_EXT_RE.search(scrubbed):
        violations.append(f"{label}: forbidden external dynamic import() in JS")
    if JS_DOM_SRC_ASSIGN_RE.search(scrubbed) or JS_SET_ATTR_EXT_RE.search(scrubbed):
        violations.append(f"{label}: forbidden external DOM src/href assignment in JS")

    for ws_match in JS_WS_URL_RE.finditer(scrubbed):
        violations.append(f"{label}: forbidden WebSocket URL {ws_match.group(0)!r} in JS")

    for pr_match in JS_PROTOCOL_REL_STR_RE.finditer(scrubbed):
        violations.append(f"{label}: forbidden protocol-relative URL {pr_match.group(0)!r} in JS")

    for html_snip in re.finditer(
        r"<\s*(?:script|link|img|iframe|source|video|audio|embed)\b[^>]*>",
        scrubbed,
        re.IGNORECASE,
    ):
        violations.extend(scan_html_offline_violations(html_snip.group(0), f"{label} inline-html"))

    for url_match in ANY_HTTP_URL_RE.finditer(scrubbed):
        candidate = url_match.group(0).rstrip(".,;:)")
        if not _is_allowed_attribution_url(candidate):
            violations.append(f"{label}: disallowed external URL {candidate!r} in JS")

    return violations


class _OfflineHTMLAuditor(HTMLParser):
    def __init__(self, label: str) -> None:
        super().__init__(convert_charrefs=True)
        self.label = label
        self.violations: list[str] = []
        self.tag_stack: list[tuple[str, dict[str, str]]] = []
        self._active_raw_tag: str | None = None
        self._raw_chunks: list[str] = []

    def _in_footer_or_attribution_context(self, self_attrs: dict[str, str]) -> bool:
        scopes = [*self.tag_stack, ("a", self_attrs)]
        for tag_name, attrs in scopes:
            if tag_name == "footer":
                return True
            meta_blob = " ".join(
                str(attrs.get(k, ""))
                for k in ("id", "class", "role", "aria-label", "data-section", "data-provenance")
            ).lower()
            if any(tok in meta_blob for tok in FOOTER_CREDIT_TOKENS):
                return True
        return False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t_low = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if t_low in EXECUTABLE_TAG_ATTRS:
            for attr_name in EXECUTABLE_TAG_ATTRS[t_low]:
                if attr_name not in attr_map:
                    continue
                raw_val = attr_map[attr_name].strip()
                targets = (
                    _srcset_candidates(raw_val)
                    if attr_name in ("srcset", "imagesrcset")
                    else ([raw_val] if raw_val else [])
                )
                for target in targets:
                    if _is_external_target(target):
                        self.violations.append(
                            f"{self.label}: external executable/render attribute <{t_low} {attr_name}={target!r}>"
                        )

        if t_low == "meta" and attr_map.get("http-equiv", "").strip().lower() == "refresh":
            content = attr_map.get("content", "")
            if re.search(r"(?:https?:|wss?:|//)", content, re.IGNORECASE):
                self.violations.append(f"{self.label}: external meta refresh {content!r}")

        if t_low in ("a", "area") and "href" in attr_map:
            href_val = attr_map["href"].strip()
            href_low = href_val.lower()
            if href_low.startswith(("javascript:", "vbscript:", "ws://", "wss://", "//")):
                self.violations.append(
                    f"{self.label}: forbidden scheme on <{t_low} href={href_val!r}>"
                )
            elif href_low.startswith(("http://", "https://")):
                if not self._in_footer_or_attribution_context(attr_map):
                    self.violations.append(
                        f"{self.label}: external <{t_low} href={href_val!r}> outside provenance footer"
                    )

        if "style" in attr_map and attr_map["style"].strip():
            self.violations.extend(
                scan_css_offline_violations(attr_map["style"], f"{self.label} <{t_low} style>")
            )

        for k_attr, v_attr in attr_map.items():
            if k_attr.startswith("on") and v_attr.strip():
                self.violations.extend(
                    scan_js_offline_violations(v_attr, f"{self.label} <{t_low} {k_attr}>")
                )

        if t_low not in VOID_HTML_TAGS:
            self.tag_stack.append((t_low, attr_map))

        if t_low in ("script", "style"):
            self._active_raw_tag = t_low
            self._raw_chunks = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t_low = tag.lower()
        self.handle_starttag(t_low, attrs)
        if t_low not in VOID_HTML_TAGS and self.tag_stack and self.tag_stack[-1][0] == t_low:
            self.tag_stack.pop()

    def handle_data(self, data: str) -> None:
        if self._active_raw_tag is not None:
            self._raw_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        t_low = tag.lower()
        if self._active_raw_tag == t_low:
            raw_body = "".join(self._raw_chunks)
            if t_low == "style":
                self.violations.extend(
                    scan_css_offline_violations(raw_body, f"{self.label} <style>")
                )
            elif t_low == "script":
                self.violations.extend(
                    scan_js_offline_violations(raw_body, f"{self.label} <script>")
                )
            self._active_raw_tag = None
            self._raw_chunks = []

        for idx in range(len(self.tag_stack) - 1, -1, -1):
            if self.tag_stack[idx][0] == t_low:
                del self.tag_stack[idx:]
                break


def scan_html_offline_violations(html_text: str, label: str) -> list[str]:
    auditor = _OfflineHTMLAuditor(label)
    auditor.feed(html_text)
    auditor.close()
    return auditor.violations


def validate_png_bytes(raw: bytes, label: str) -> tuple[int, int]:
    assert len(raw) >= 33 and raw.startswith(PNG_SIGNATURE), (
        f"{label}: invalid PNG signature or truncated file"
    )
    assert raw[12:16] == b"IHDR", f"{label}: missing PNG IHDR header chunk"
    width, height = struct.unpack(">II", raw[16:24])
    assert width > 0 and height > 0, f"{label}: non-positive PNG dimensions ({width}x{height})"
    assert raw.endswith(PNG_IEND_TRAILER), f"{label}: missing PNG IEND trailer"
    return width, height


def audit_demo_directory_offline(demo_dir: Path) -> dict[str, Any]:
    root = demo_dir.resolve()
    assert root.is_dir(), f"Missing demo directory: {root}"

    scanned_files: list[str] = []
    png_files: list[str] = []
    violations: list[str] = []

    for fpath in sorted(root.rglob("*")):
        if not fpath.is_file():
            continue
        suffix = fpath.suffix.lower()
        rel = fpath.relative_to(root).as_posix()
        if suffix == ".png":
            png_files.append(rel)
            try:
                validate_png_bytes(fpath.read_bytes(), rel)
            except AssertionError as exc:
                violations.append(str(exc))
            continue
        if suffix not in {".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".json"}:
            continue
        scanned_files.append(rel)
        txt = fpath.read_text(encoding="utf-8")

        violations.extend(scan_text_for_secrets(txt, rel))
        violations.extend(scan_text_for_forbidden_dashes(txt, rel))

        if suffix in {".html", ".htm"}:
            violations.extend(scan_html_offline_violations(txt, rel))
        elif suffix == ".css":
            violations.extend(scan_css_offline_violations(txt, rel))
        elif suffix in {".js", ".mjs", ".cjs"}:
            violations.extend(scan_js_offline_violations(txt, rel))

    assert scanned_files, f"No HTML/CSS/JS files found under {root}"
    assert not violations, "Offline/secret QA violations:\n" + "\n".join(violations)
    return {
        "scanned_count": len(scanned_files),
        "png_count": len(png_files),
        "files": scanned_files,
    }


def _clean_md_cell(cell: str) -> str:
    cleaned = cell.strip()
    cleaned = re.sub(r"^`+|`+$", "", cleaned).strip()
    cleaned = re.sub(r"^\*\*+|\*\*+$", "", cleaned).strip()
    return cleaned


def validate_assets_md_provenance(md_text: str) -> list[dict[str, str]]:
    assert isinstance(md_text, str) and md_text.strip(), "ASSETS.md is empty"
    dash_errs = scan_text_for_forbidden_dashes(md_text, "docs/demo/ASSETS.md")
    assert not dash_errs, "; ".join(dash_errs)
    sec_errs = scan_text_for_secrets(md_text, "docs/demo/ASSETS.md")
    assert not sec_errs, "; ".join(sec_errs)

    lower_md = md_text.lower()
    for term in HARD_FORBIDDEN_ASSET_TERMS:
        assert term not in lower_md, f"ASSETS.md contains forbidden license/source term {term!r}"

    auditor = _OfflineHTMLAuditor("docs/demo/ASSETS.md")
    auditor.tag_stack.append(("footer", {"id": "provenance-assets-doc"}))
    auditor.feed(md_text)
    auditor.close()
    assert not auditor.violations, "; ".join(auditor.violations)

    packs: list[dict[str, str]] = []
    lines = md_text.splitlines()
    idx = 0
    while idx < len(lines):
        if lines[idx].lstrip().startswith("|"):
            block: list[str] = []
            while idx < len(lines) and lines[idx].lstrip().startswith("|"):
                block.append(lines[idx].strip())
                idx += 1
            if len(block) >= 3 and re.match(r"^\|[\s:|-]+\|$", block[1]):
                headers = [_clean_md_cell(c).lower() for c in block[0].strip("|").split("|")]
                author_col = next(
                    (i for i, h in enumerate(headers) if any(k in h for k in ("author", "creator", "artist"))),
                    None,
                )
                lic_col = next(
                    (i for i, h in enumerate(headers) if "licen" in h),
                    None,
                )
                url_col = next(
                    (i for i, h in enumerate(headers) if any(k in h for k in ("source url", "page url", "url", "source", "link"))),
                    None,
                )
                name_col = next(
                    (i for i, h in enumerate(headers) if any(k in h for k in ("pack id", "pack name", "pack", "name", "asset"))),
                    0,
                )
                if author_col is not None and lic_col is not None and url_col is not None:
                    for row_line in block[2:]:
                        if re.match(r"^\|[\s:|-]+\|$", row_line):
                            continue
                        cells = [c.strip() for c in row_line.strip("|").split("|")]
                        needed = max(author_col, lic_col, url_col)
                        assert len(cells) > needed, f"Malformed table row in ASSETS.md: {row_line!r}"
                        packs.append(
                            {
                                "name": _clean_md_cell(cells[name_col]) if name_col < len(cells) else "pack",
                                "author": _clean_md_cell(cells[author_col]),
                                "license": _clean_md_cell(cells[lic_col]),
                                "url": cells[url_col],
                                "context": " ".join(cells),
                            }
                        )
        else:
            idx += 1

    if not packs:
        sec_prefix = HASH_CHAR * 2
        sec_re = re.compile(rf"(?m)^({re.escape(sec_prefix)}{re.escape(HASH_CHAR)}?)\s+(.+)$")
        matches = list(sec_re.finditer(md_text))
        for m_idx, match in enumerate(matches):
            title = _clean_md_cell(match.group(2))
            end = matches[m_idx + 1].start() if m_idx + 1 < len(matches) else len(md_text)
            body = md_text[match.end() : end]
            kv: dict[str, str] = {}
            for ln in body.splitlines():
                bm = re.match(r"^[-*]\s+\*\*([^*:]+):?\*\*:?\s*(.*)$", ln.strip())
                if not bm:
                    bm = re.match(r"^[-*]\s+([A-Za-z][A-Za-z0-9 /_-]{1,30}):\s*(.*)$", ln.strip())
                if bm:
                    kv[bm.group(1).strip().lower()] = bm.group(2).strip()
            author_val = next((_clean_md_cell(kv[k]) for k in ("author", "creator", "artist") if k in kv), "")
            lic_val = next((_clean_md_cell(kv[k]) for k in ("license", "licence") if k in kv), "")
            url_val = next((kv[k] for k in ("direct page url", "page url", "source url", "url", "source", "link") if k in kv), "")
            if author_val or lic_val or url_val:
                packs.append(
                    {
                        "name": title,
                        "author": author_val,
                        "license": lic_val,
                        "url": url_val,
                        "context": body,
                    }
                )

    assert len(packs) >= 1, "ASSETS.md must document >= 1 asset pack with provenance"

    for pack in packs:
        plabel = f"ASSETS.md pack {pack['name']!r}"
        author = pack["author"].strip()
        assert author and author.lower() not in PLACEHOLDER_AUTHORS, f"{plabel}: missing author attribution"

        lic = pack["license"].strip()
        lic_low = lic.lower()
        assert lic, f"{plabel}: missing license"
        assert not re.search(r"\b(?:nc|nd|non-?commercial|no-?derivatives)\b", lic_low), (
            f"{plabel}: non-commercial or no-derivatives license {lic!r} is forbidden"
        )
        is_pd_or_cc0 = bool(re.search(r"\bcc0(?:\b|[- ]1\.0)|\bpublic\s+domain\b", lic_low))
        is_cc_by = bool(re.search(r"\b(?:cc|oga)[- ]by(?:[- ]sa)?(?:\b|[- ]\d)", lic_low))
        assert is_pd_or_cc0 or is_cc_by, (
            f"{plabel}: license must be CC0/Public-Domain or CC-BY, got {lic!r}"
        )
        if is_cc_by and not is_pd_or_cc0:
            ctx_low = pack["context"].lower()
            assert author.lower() in ctx_low and any(
                w in ctx_low for w in ("credit", "attribution", "credited", "attributed")
            ), f"{plabel}: CC-BY pack requires explicit credit naming {author!r}"

        urls = ANY_HTTP_URL_RE.findall(pack["url"])
        assert urls, f"{plabel}: missing https:// source attribution URL"
        for u in urls:
            clean_u = u.rstrip(".,;:)").rstrip("`")
            assert clean_u.startswith("https://"), f"{plabel}: source URL must use https://, got {clean_u!r}"
            assert _is_allowed_attribution_url(clean_u), (
                f"{plabel}: source URL {clean_u!r} must point to a verified open-asset source"
            )

    return packs


def _extract_balanced_json_object(text: str, start_pos: int) -> str:
    brace_start = text.find("{", start_pos)
    assert brace_start != -1, "Missing '{' in JS object assignment"
    depth = 0
    in_str: str | None = None
    i = brace_start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : i + 1]
        i += 1
    raise AssertionError("Unbalanced braces in JS data bundle")


def parse_window_outthink_data(cases_js_text: str) -> dict[str, Any]:
    assert isinstance(cases_js_text, str) and cases_js_text.strip(), "cases.js is empty"
    assert "OUTTHINK_DATA" in cases_js_text and "window" in cases_js_text, (
        "cases.js must bind window.OUTTHINK_DATA"
    )

    direct = re.search(
        r"(?:window\.OUTTHINK_DATA|root\.OUTTHINK_DATA)\s*=\s*(?:Object\.freeze\(\s*)?\{",
        cases_js_text,
    )
    if direct is not None:
        raw_obj = _extract_balanced_json_object(cases_js_text, direct.start())
    else:
        decl = re.search(
            r"\b(?:var|let|const)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:Object\.freeze\(\s*)?\{",
            cases_js_text,
        )
        assert decl is not None, "Could not locate data object literal in cases.js"
        var_name = decl.group(1)
        assert re.search(rf"OUTTHINK_DATA\s*=\s*{re.escape(var_name)}\b", cases_js_text), (
            f"Variable {var_name!r} is never assigned to window.OUTTHINK_DATA"
        )
        raw_obj = _extract_balanced_json_object(cases_js_text, decl.start())

    parsed = json.loads(raw_obj)
    assert isinstance(parsed, dict), "window.OUTTHINK_DATA must be a JSON object"
    return parsed


def _list_price_usd(model: str, tin: int, tout: int, thinking: int, cached: int) -> float:
    rates = MODEL_PRICES_PER_M.get(model)
    if rates is None:
        return 0.0
    non_cached = max(0, int(tin) - int(cached))
    billable_out = max(0, int(tout)) + max(0, int(thinking))
    return ((non_cached * rates[0]) + (max(0, int(cached)) * rates[2]) + (billable_out * rates[1])) / 1_000_000.0


def validate_outthink_corpus_provenance(
    *,
    outthink_json_path: Path,
    cases_js_path: Path,
    ladder_episodes_gz: Path,
    ladder_ledger_gz: Path,
    reference_dir: Path,
    inproc_carbon_dir: Path | None = None,
) -> dict[str, Any]:
    assert outthink_json_path.is_file(), f"Missing {outthink_json_path}"
    assert cases_js_path.is_file(), f"Missing {cases_js_path}"
    assert ladder_episodes_gz.is_file(), f"Missing {ladder_episodes_gz}"
    assert ladder_ledger_gz.is_file(), f"Missing {ladder_ledger_gz}"
    assert reference_dir.is_dir(), f"Missing {reference_dir}"

    json_payload = json.loads(outthink_json_path.read_text(encoding="utf-8"))
    js_payload = parse_window_outthink_data(cases_js_path.read_text(encoding="utf-8"))

    for src_label, bundle in (("out_think_gemini.json", json_payload), ("cases.js", js_payload)):
        meta = bundle.get("meta")
        assert isinstance(meta, dict), f"{src_label}: missing meta object"
        assert meta.get("isBootstrapFallback") is False, (
            f"{src_label}: meta.isBootstrapFallback must be False (got {meta.get('isBootstrapFallback')!r})"
        )
        cases = bundle.get("cases")
        assert isinstance(cases, list) and len(cases) >= 1, f"{src_label}: must contain >= 1 case"

    assert js_payload["meta"]["isBootstrapFallback"] is False
    assert [c["id"] for c in js_payload["cases"]] == [c["id"] for c in json_payload["cases"]], (
        "cases.js case IDs out of sync with out_think_gemini.json"
    )
    assert js_payload["cases"] == json_payload["cases"], (
        "cases.js window.OUTTHINK_DATA.cases differs from results/gemini/out_think_gemini.json"
    )

    episodes_by_cell: dict[tuple[str, str, str, int], dict[str, Any]] = {}
    episodes_by_run_id: dict[str, dict[str, Any]] = {}
    with gzip.open(ladder_episodes_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            ep = json.loads(line)
            ep_meta = ep.get("meta") or {}
            if ep_meta.get("valid") is False or ep.get("end_reason") == "error":
                continue
            lad = ep_meta.get("ladder") or {}
            model = str(lad.get("model") or "")
            level = str(lad.get("thinking_level") or lad.get("level") or "")
            tier = str(lad.get("tier") or ep.get("tier") or "")
            seed = int(lad.get("seed") if lad.get("seed") is not None else ep["seed"])
            rid = str(lad.get("run_id") or ep_meta.get("run_id") or "")
            if (model, level, tier, seed) not in episodes_by_cell:
                episodes_by_cell[(model, level, tier, seed)] = ep
            if rid and rid not in episodes_by_run_id:
                episodes_by_run_id[rid] = ep

    ledger_by_run: dict[str, dict[str, Any]] = {}
    with gzip.open(ladder_ledger_gz, "rt", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            rid = str(row.get("run_id") or "")
            if not rid:
                continue
            slot = ledger_by_run.setdefault(
                rid,
                {"calls": 0, "cost_usd": 0.0, "in": 0, "out": 0, "thinking": 0, "cached": 0},
            )
            slot["calls"] += 1
            slot["cost_usd"] += float(row.get("cost_usd") or 0.0)
            slot["in"] += int(row.get("in") or 0)
            slot["out"] += int(row.get("out") or 0)
            slot["thinking"] += int(row.get("thinking") or 0)
            slot["cached"] += int(row.get("cached") or 0)

    solver_by_world: dict[tuple[str, int], dict[str, Any]] = {}
    for solver_file in sorted(reference_dir.glob("solver-*/episodes.jsonl")):
        for raw_line in solver_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            if str(row.get("agent")) == "solver":
                solver_by_world[(str(row["tier"]), int(row["seed"]))] = row

    inproc_by_world: dict[tuple[str, int], dict[str, Any]] = {}
    if inproc_carbon_dir is not None and inproc_carbon_dir.is_dir():
        for tier_name in ("medium", "hard"):
            ep_file = inproc_carbon_dir / tier_name / "episodes.jsonl"
            if not ep_file.is_file():
                continue
            for raw_line in ep_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if (row.get("meta") or {}).get("valid") is False or row.get("end_reason") == "error":
                    continue
                inproc_by_world[(tier_name, int(row["seed"]))] = row

    verified_level_runs = 0
    for case in json_payload["cases"]:
        cid = str(case.get("id") or "")
        tier = str(case.get("tier") or "")
        assert isinstance(case.get("seed"), int), f"Case {cid!r}: seed must be an int"
        seed = int(case["seed"])
        case_model = str(case.get("model") or "")
        anchor_level = str(case.get("anchor_level") or "")

        if case_model and anchor_level:
            assert (case_model, anchor_level, tier, seed) in episodes_by_cell, (
                f"Case {cid!r}: anchor {(case_model, anchor_level, tier, seed)} missing from ladder_episodes.jsonl.gz"
            )

        assert (tier, seed) in solver_by_world, (
            f"Case {cid!r}: world {(tier, seed)} missing from data/runs/committed/v1.4/reference solver runs"
        )
        solver_ref = solver_by_world[(tier, seed)]
        solver_blk = case.get("solver")
        assert isinstance(solver_blk, dict), f"Case {cid!r}: missing solver block"
        assert float(solver_blk["final_score"]) == pytest.approx(float(solver_ref["score"]), abs=1e-3), (
            f"Case {cid!r}: solver.final_score {solver_blk['final_score']} != committed {solver_ref['score']}"
        )
        assert solver_blk.get("final_accused") == solver_ref.get("accused"), (
            f"Case {cid!r}: solver.final_accused mismatch vs committed reference"
        )
        assert bool(solver_blk.get("correct")) is bool(solver_ref.get("correct")), (
            f"Case {cid!r}: solver.correct mismatch vs committed reference"
        )

        t_levels = case.get("thinking_levels")
        assert isinstance(t_levels, list) and len(t_levels) >= 1, (
            f"Case {cid!r}: thinking_levels must be non-empty"
        )

        for lv in t_levels:
            lv_model = str(lv.get("model") or case_model)
            lv_key = str(lv.get("thinking_level") or lv.get("level") or lv.get("key") or "")
            cell_key = (lv_model, lv_key, tier, seed)
            assert cell_key in episodes_by_cell, (
                f"Case {cid!r}: level run {cell_key} not found in ladder_episodes.jsonl.gz"
            )
            ep = episodes_by_cell[cell_key]
            lad = (ep.get("meta") or {}).get("ladder") or {}
            toks = lad.get("tokens") or {}
            expected_rid = str(lad.get("run_id") or "")
            actual_rid = str(lv.get("run_id") or expected_rid)
            assert actual_rid == expected_rid and actual_rid in episodes_by_run_id, (
                f"Case {cid!r} ({lv_key}): run_id {actual_rid!r} != committed {expected_rid!r}"
            )
            assert actual_rid in ledger_by_run, (
                f"Case {cid!r} ({lv_key}): run_id {actual_rid!r} missing from ladder_ledger.jsonl.gz"
            )
            ledger_row = ledger_by_run[actual_rid]
            assert ledger_row["calls"] > 0

            assert float(lv["score"]) == pytest.approx(round(float(ep["score"]), 4), abs=1e-4), (
                f"Case {cid!r} ({lv_key}): score {lv['score']} != committed {ep['score']}"
            )
            assert bool(lv["correct"]) is bool(ep["correct"]), (
                f"Case {cid!r} ({lv_key}): correct flag mismatch"
            )
            expected_acc = str(ep["accused"]) if ep.get("accused") is not None else None
            assert lv.get("accused") == expected_acc, (
                f"Case {cid!r} ({lv_key}): accused {lv.get('accused')!r} != committed {expected_acc!r}"
            )
            assert int(lv["thinking_tokens"]) == int(toks.get("thinking") or 0), (
                f"Case {cid!r} ({lv_key}): thinking_tokens {lv['thinking_tokens']} != committed {toks.get('thinking')}"
            )
            if "input_tokens" in lv:
                assert int(lv["input_tokens"]) == int(toks.get("in") or 0)
            if "output_tokens" in lv:
                assert int(lv["output_tokens"]) == int(toks.get("out") or 0)
            if "cached_tokens" in lv:
                assert int(lv["cached_tokens"]) == int(toks.get("cached") or 0)
            if "ledger_calls" in lv:
                assert int(lv["ledger_calls"]) == int(ledger_row["calls"])

            expected_cost = (
                ledger_row["cost_usd"]
                if ledger_row["cost_usd"] > 0.0
                else _list_price_usd(
                    lv_model,
                    int(toks.get("in") or 0),
                    int(toks.get("out") or 0),
                    int(toks.get("thinking") or 0),
                    int(toks.get("cached") or 0),
                )
            )
            assert float(lv["cost_usd"]) == pytest.approx(expected_cost, abs=1e-3), (
                f"Case {cid!r} ({lv_key}): cost_usd {lv['cost_usd']} != committed {expected_cost}"
            )
            verified_level_runs += 1

        for cmc in case.get("cross_model_carbon") or []:
            assert cmc.get("model") == "gemini-4-carbon"
            cmc_rid = str(cmc.get("run_id") or "")
            cmc_lv = str(cmc.get("thinking_level") or "")
            if cmc_rid.startswith("inproc:") and (tier, seed) in inproc_by_world:
                in_ep = inproc_by_world[(tier, seed)]
                assert float(cmc["score"]) == pytest.approx(round(float(in_ep["score"]), 4), abs=1e-4)
                assert bool(cmc["correct"]) is bool(in_ep["correct"])
            else:
                c_cell = ("gemini-4-carbon", cmc_lv, tier, seed)
                assert c_cell in episodes_by_cell, f"Case {cid!r}: carbon cell {c_cell} missing"
                c_ep = episodes_by_cell[c_cell]
                c_toks = ((c_ep.get("meta") or {}).get("ladder") or {}).get("tokens") or {}
                assert float(cmc["score"]) == pytest.approx(round(float(c_ep["score"]), 4), abs=1e-4)
                assert int(cmc["thinking_tokens"]) == int(c_toks.get("thinking") or 0)

    return {
        "case_count": len(json_payload["cases"]),
        "verified_level_runs": verified_level_runs,
    }


def validate_manifest_and_sprites_provenance(
    *,
    manifest_js_path: Path,
    demo_dir: Path,
    assets_md_packs: list[dict[str, str]] | None = None,
) -> dict[str, int]:
    assert manifest_js_path.is_file(), f"Missing manifest.js: {manifest_js_path}"
    demo_root = demo_dir.resolve()
    manifest_txt = manifest_js_path.read_text(encoding="utf-8")
    assert "OUTTHINK_ASSETS" in manifest_txt, "manifest.js must bind window.OUTTHINK_ASSETS"

    raw_obj = _extract_balanced_json_object(manifest_txt, manifest_txt.find("OUTTHINK_ASSETS"))
    manifest = json.loads(raw_obj)
    assert isinstance(manifest, dict), "OUTTHINK_ASSETS must be an object"

    raw_packs = manifest.get("packs")
    if isinstance(raw_packs, dict):
        pack_list = [{"id": str(k), **v} for k, v in raw_packs.items() if isinstance(v, dict)]
    elif isinstance(raw_packs, list):
        pack_list = [p for p in raw_packs if isinstance(p, dict)]
    else:
        raise AssertionError("OUTTHINK_ASSETS.packs must be a non-empty list or object")
    assert len(pack_list) >= 1, "OUTTHINK_ASSETS.packs must contain >= 1 pack"

    manifest_pack_ids: set[str] = set()
    for pack in pack_list:
        pid = str(pack.get("id") or pack.get("name") or "").strip()
        assert pid, "Manifest pack missing id"
        manifest_pack_ids.add(pid)
        author = str(pack.get("author") or "").strip()
        assert author and author.lower() not in PLACEHOLDER_AUTHORS, (
            f"Manifest pack {pid!r}: missing author"
        )
        lic = str(pack.get("license") or "").strip()
        lic_low = lic.lower()
        assert not re.search(r"\b(?:nc|nd|non-?commercial|no-?derivatives)\b", lic_low), (
            f"Manifest pack {pid!r}: forbidden license {lic!r}"
        )
        assert re.search(r"\bcc0(?:\b|[- ]1\.0)|\bpublic\s+domain\b|\b(?:cc|oga)[- ]by", lic_low), (
            f"Manifest pack {pid!r}: unsupported license {lic!r}"
        )
        url = str(pack.get("url") or "").strip()
        assert url.startswith("https://") and _is_allowed_attribution_url(url), (
            f"Manifest pack {pid!r}: disallowed attribution URL {url!r}"
        )

    if assets_md_packs is not None:
        documented_ids = {p["name"] for p in assets_md_packs}
        missing_in_md = sorted(manifest_pack_ids - documented_ids)
        assert not missing_in_md, (
            f"Manifest pack IDs undocumented in docs/demo/ASSETS.md: {missing_in_md}"
        )

    sprites = manifest.get("sprites")
    assert isinstance(sprites, dict) and len(sprites) >= 1, (
        "OUTTHINK_ASSETS.sprites must be a non-empty object"
    )
    for sp_key, sp_val in sprites.items():
        assert isinstance(sp_val, dict), f"Sprite {sp_key!r}: entry must be an object"
        if "pack" in sp_val:
            sp_pack = str(sp_val["pack"]).strip()
            assert sp_pack in manifest_pack_ids, (
                f"Sprite {sp_key!r}: references undeclared pack {sp_pack!r}"
            )
        rel_path = str(sp_val.get("path") or "").strip()
        assert rel_path and not _is_external_target(rel_path), (
            f"Sprite {sp_key!r}: path {rel_path!r} must be a local relative path"
        )
        resolved = (demo_root / rel_path.lstrip("./")).resolve()
        assert str(resolved).startswith(str(demo_root)) and resolved.is_file(), (
            f"Sprite {sp_key!r}: missing local PNG file {rel_path!r}"
        )
        disk_bytes = resolved.read_bytes()
        validate_png_bytes(disk_bytes, f"sprite {sp_key}:{rel_path}")

        if "dataUri" in sp_val and sp_val["dataUri"]:
            d_uri = str(sp_val["dataUri"])
            assert d_uri.startswith("data:image/png;base64,"), (
                f"Sprite {sp_key!r}: dataUri must be data:image/png;base64"
            )
            uri_bytes = base64.b64decode(d_uri.split(",", 1)[1], validate=True)
            validate_png_bytes(uri_bytes, f"sprite {sp_key}:dataUri")
            assert uri_bytes == disk_bytes, (
                f"Sprite {sp_key!r}: inline dataUri bytes out of sync with {rel_path!r}"
            )

    return {"pack_count": len(manifest_pack_ids), "sprite_count": len(sprites)}


def _write_clean_synthetic_demo(base_dir: Path) -> Path:
    demo_dir = base_dir / "demo" / "out-think-gemini"
    assets_dir = demo_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    valid_1x1_png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    (assets_dir / "detective.png").write_bytes(valid_1x1_png)
    b64_png = base64.b64encode(valid_1x1_png).decode("ascii")

    (demo_dir / "index.html").write_text(
        "<!DOCTYPE html>\n"
        "<html lang=\"en\">\n"
        "<head>\n"
        "  <meta charset=\"utf-8\">\n"
        "  <title>Out-Think Gemini Offline Fixture</title>\n"
        "  <link rel=\"stylesheet\" href=\"style.css\">\n"
        "</head>\n"
        "<body>\n"
        "  <main><img src=\"assets/detective.png\" alt=\"Detective\"></main>\n"
        "  <footer id=\"provenance-footer\" class=\"provenance-footer\">\n"
        "    <a href=\"https://opengameart.org/content/roguelike-indoor-pack\">Kenney CC0</a>\n"
        "    <a href=\"https://creativecommons.org/publicdomain/zero/1.0/\">CC0 1.0</a>\n"
        "  </footer>\n"
        "  <script src=\"assets/manifest.js\"></script>\n"
        "  <script src=\"cases.js\"></script>\n"
        "  <script src=\"game.js\"></script>\n"
        "</body>\n"
        "</html>\n",
        encoding="utf-8",
    )
    (demo_dir / "style.css").write_text(
        ":root { --bg: rgb(7, 11, 18); }\n"
        ".tile { background-image: url(\"assets/detective.png\"); }\n"
        ".inline-icon { background-image: url(\"data:image/png;base64," + b64_png + "\"); }\n",
        encoding="utf-8",
    )
    (assets_dir / "manifest.js").write_text(
        "window.OUTTHINK_ASSETS = {\n"
        "  \"packs\": [\n"
        "    {\n"
        "      \"id\": \"kenney-roguelike-indoor\",\n"
        "      \"author\": \"Kenney\",\n"
        "      \"license\": \"CC0-1.0\",\n"
        "      \"url\": \"https://opengameart.org/content/roguelike-indoor-pack\"\n"
        "    }\n"
        "  ],\n"
        "  \"sprites\": {\n"
        "    \"detective\": {\n"
        "      \"pack\": \"kenney-roguelike-indoor\",\n"
        "      \"path\": \"assets/detective.png\",\n"
        "      \"dataUri\": \"data:image/png;base64," + b64_png + "\"\n"
        "    }\n"
        "  }\n"
        "};\n",
        encoding="utf-8",
    )
    (demo_dir / "cases.js").write_text(
        "(function (root) {\n"
        "  var data = {\"meta\": {\"isBootstrapFallback\": false}, \"cases\": []};\n"
        "  if (typeof window !== \"undefined\" && window) { window.OUTTHINK_DATA = data; }\n"
        "  if (root) { root.OUTTHINK_DATA = data; }\n"
        "})(typeof globalThis !== \"undefined\" ? globalThis : this);\n",
        encoding="utf-8",
    )
    (demo_dir / "game.js").write_text(
        "(function () {\n"
        "  var svgNs = \"http://www.w3.org/2000/svg\";\n"
        "  if (typeof window !== \"undefined\") { window.OUTTHINK_READY = Boolean(svgNs); }\n"
        "})();\n",
        encoding="utf-8",
    )
    return demo_dir


def _write_synthetic_corpus_fixture(base_dir: Path) -> dict[str, Path]:
    episodes_gz = base_dir / "ladder_episodes.jsonl.gz"
    ledger_gz = base_dir / "ladder_ledger.jsonl.gz"
    ref_dir = base_dir / "reference" / "solver-hard"
    ref_dir.mkdir(parents=True, exist_ok=True)
    out_json = base_dir / "out_think_gemini.json"
    cases_js = base_dir / "cases.js"

    run_low = "ladder:ladder-v14:gemini-4-carbon/low/hard/1"
    run_high = "ladder:ladder-v14:gemini-4-carbon/high/hard/1"

    ep_rows = [
        {
            "tier": "hard",
            "seed": 1,
            "score": -1.0,
            "correct": False,
            "accused": "e12",
            "final_day": 6,
            "end_reason": "accused",
            "meta": {
                "ladder": {
                    "run_id": run_low,
                    "model": "gemini-4-carbon",
                    "level": "low",
                    "thinking_level": "low",
                    "tier": "hard",
                    "seed": 1,
                    "tokens": {"in": 12000, "out": 200, "thinking": 450, "cached": 8000, "calls": 14},
                }
            },
        },
        {
            "tier": "hard",
            "seed": 1,
            "score": 0.69,
            "correct": True,
            "accused": "e33",
            "final_day": 9,
            "end_reason": "accused",
            "meta": {
                "ladder": {
                    "run_id": run_high,
                    "model": "gemini-4-carbon",
                    "level": "high",
                    "thinking_level": "high",
                    "tier": "hard",
                    "seed": 1,
                    "tokens": {"in": 24000, "out": 350, "thinking": 4800, "cached": 18000, "calls": 22},
                }
            },
        },
    ]
    with gzip.open(episodes_gz, "wt", encoding="utf-8") as fh:
        for row in ep_rows:
            fh.write(json.dumps(row) + "\n")

    ledger_rows = [
        {"run_id": run_low, "cost_usd": 0.0155, "in": 6000, "out": 100, "thinking": 200, "cached": 4000},
        {"run_id": run_low, "cost_usd": 0.0145, "in": 6000, "out": 100, "thinking": 250, "cached": 4000},
        {"run_id": run_high, "cost_usd": 0.0653, "in": 24000, "out": 350, "thinking": 4800, "cached": 18000},
    ]
    with gzip.open(ledger_gz, "wt", encoding="utf-8") as fh:
        for row in ledger_rows:
            fh.write(json.dumps(row) + "\n")

    solver_row = {
        "agent": "solver",
        "tier": "hard",
        "seed": 1,
        "accused": "e33",
        "final_day": 9,
        "score": 0.69,
        "correct": True,
    }
    (ref_dir / "episodes.jsonl").write_text(json.dumps(solver_row) + "\n", encoding="utf-8")

    bundle = {
        "meta": {
            "tiers_version": "v1.4",
            "isBootstrapFallback": False,
            "case_count": 1,
        },
        "cases": [
            {
                "id": "carbon-hard-1",
                "model": "gemini-4-carbon",
                "anchor_level": "high",
                "tier": "hard",
                "seed": 1,
                "true_mole": "e33",
                "solver": {
                    "top_suspect": "e33",
                    "top_prob": 0.97,
                    "break_even_prob": 0.58,
                    "recommended_call": "accuse",
                    "final_accused": "e33",
                    "final_day": 9,
                    "final_score": 0.69,
                    "correct": True,
                },
                "thinking_levels": [
                    {
                        "key": "low",
                        "model": "gemini-4-carbon",
                        "thinking_level": "low",
                        "tier": "hard",
                        "seed": 1,
                        "accused": "e12",
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.03,
                        "thinking_tokens": 450,
                        "input_tokens": 12000,
                        "output_tokens": 200,
                        "cached_tokens": 8000,
                        "calls": 14,
                        "ledger_calls": 2,
                        "run_id": run_low,
                    },
                    {
                        "key": "high",
                        "model": "gemini-4-carbon",
                        "thinking_level": "high",
                        "tier": "hard",
                        "seed": 1,
                        "accused": "e33",
                        "correct": True,
                        "score": 0.69,
                        "cost_usd": 0.0653,
                        "thinking_tokens": 4800,
                        "input_tokens": 24000,
                        "output_tokens": 350,
                        "cached_tokens": 18000,
                        "calls": 22,
                        "ledger_calls": 1,
                        "run_id": run_high,
                    },
                ],
                "cross_model_carbon": [
                    {
                        "model": "gemini-4-carbon",
                        "thinking_level": "high",
                        "accused": "e33",
                        "cost_usd": 0.0653,
                        "thinking_tokens": 4800,
                        "score": 0.69,
                        "correct": True,
                        "run_id": run_high,
                    }
                ],
            }
        ],
    }
    out_json.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
    cases_js.write_text(
        "(function (root) {\n"
        "  var data = " + json.dumps(bundle) + ";\n"
        "  if (typeof window !== \"undefined\" && window) { window.OUTTHINK_DATA = data; }\n"
        "  if (root) { root.OUTTHINK_DATA = data; }\n"
        "})(typeof globalThis !== \"undefined\" ? globalThis : this);\n",
        encoding="utf-8",
    )
    return {
        "outthink_json_path": out_json,
        "cases_js_path": cases_js,
        "ladder_episodes_gz": episodes_gz,
        "ladder_ledger_gz": ledger_gz,
        "reference_dir": base_dir / "reference",
    }


def test_network_sockets_are_strictly_blocked() -> None:
    with pytest.raises(RuntimeError, match="blocked"):
        socket.create_connection(("example.com", 443))
    with pytest.raises(RuntimeError, match="blocked"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def test_synthetic_clean_bundle_allows_footer_and_assets_md_attribution_links(tmp_path: Path) -> None:
    demo_dir = _write_clean_synthetic_demo(tmp_path)
    report = audit_demo_directory_offline(demo_dir)
    assert report["scanned_count"] == 5

    h1 = HASH_CHAR
    h2 = HASH_CHAR * 2
    assets_md = (
        f"{h1} Out-Think Gemini Asset Provenance (CC0)\n\n"
        f"{h2} Pack Summary Table\n\n"
        "| Pack ID | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| `kenney-roguelike-indoor` | Kenney | CC0-1.0 | "
        "<a href=\"https://opengameart.org/content/roguelike-indoor-pack\">https://opengameart.org/content/roguelike-indoor-pack</a> |\n"
        "| `oga-detective-items` | ARoachIFoundOnMyPillow | CC0-1.0 | https://opengameart.org/content/16x16-detective-items |\n"
    )
    packs = validate_assets_md_provenance(assets_md)
    assert len(packs) == 2


@pytest.mark.parametrize(
    ("target_file", "bad_snippet", "expected_match"),
    [
        (
            "index.html",
            "<script src=\"https://cdnjs.cloudflare.com/ajax/libs/phaser/3.80.1/phaser.min.js\"></script>",
            "script src=",
        ),
        (
            "index.html",
            "<link rel=\"stylesheet\" href=\"http://fonts.googleapis.com/css?family=Roboto\">",
            "link href=",
        ),
        (
            "index.html",
            "<img src=\"//cdn.example.com/sprites/detective.png\" alt=\"d\">",
            "img src=",
        ),
        (
            "index.html",
            "<img srcset=\"assets/local.png 1x, https://cdn.example.com/hi.png 2x\" alt=\"d\">",
            "img srcset=",
        ),
        (
            "index.html",
            "<main><a href=\"https://example.com/external-nav\">Leave</a></main>",
            "outside provenance footer",
        ),
        (
            "style.css",
            ".hero { background-image: url(https://cdn.example.com/bg.png); }",
            "external CSS url",
        ),
        (
            "style.css",
            "@import \"https://fonts.googleapis.com/css2?family=Inter\";",
            "external CSS @import",
        ),
        (
            "game.js",
            "window.loadRemote = function () { return fetch(\"https://generativelanguage.googleapis.com/v1beta/models\"); };",
            "fetch()",
        ),
        (
            "game.js",
            "window.openStream = function () { return new WebSocket(\"wss://stream.example.com/live\"); };",
            "WebSocket",
        ),
        (
            "game.js",
            "window.xhrCall = function () { return new XMLHttpRequest(); };",
            "XMLHttpRequest",
        ),
        (
            "game.js",
            "var img = {}; img.src = \"//cdn.example.com/remote.png\";",
            "DOM src/href assignment",
        ),
    ],
)
def test_offline_validator_catches_external_urls_fetch_and_websocket(
    tmp_path: Path,
    target_file: str,
    bad_snippet: str,
    expected_match: str,
) -> None:
    demo_dir = _write_clean_synthetic_demo(tmp_path)
    fpath = demo_dir / target_file
    if target_file == "index.html":
        orig = fpath.read_text(encoding="utf-8")
        fpath.write_text(orig.replace("</body>", f"  {bad_snippet}\n</body>"), encoding="utf-8")
    else:
        fpath.write_text(fpath.read_text(encoding="utf-8") + "\n" + bad_snippet + "\n", encoding="utf-8")

    with pytest.raises(AssertionError, match=re.escape(expected_match)):
        audit_demo_directory_offline(demo_dir)


@pytest.mark.parametrize(
    ("secret_builder", "expected_kind"),
    [
        (lambda: "AI" + "za" + ("B" * 35), "google_api_key"),
        (lambda: "s" + "k-" + ("C" * 32), "sk_secret_key"),
        (lambda: "ya" + "29." + ("D" * 40), "google_oauth_ya29"),
        (lambda: "gh" + "p_" + ("E" * 36), "github_pat"),
        (lambda: "AK" + "IA" + ("F" * 16), "aws_access_key"),
    ],
)
def test_secret_scanner_catches_api_keys_and_oauth_tokens(
    tmp_path: Path,
    secret_builder: Any,
    expected_kind: str,
) -> None:
    demo_dir = _write_clean_synthetic_demo(tmp_path)
    fake_token = secret_builder()
    (demo_dir / "game.js").write_text(
        f"window.DEBUG_TOKEN = \"{fake_token}\";\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match=re.escape(expected_kind)):
        audit_demo_directory_offline(demo_dir)


def test_assets_md_validator_rejects_bad_licenses_missing_authors_and_dashes() -> None:
    h1 = HASH_CHAR
    bad_nc_term = (
        f"{h1} Assets\n\n"
        "| Pack | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| PackA | Kenney | CC-BY-NC 4.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
    )
    with pytest.raises(AssertionError, match="cc-by-nc"):
        validate_assets_md_provenance(bad_nc_term)

    bad_nc_phrase = (
        f"{h1} Assets\n\n"
        "| Pack | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| PackA | Kenney | Non-Commercial 1.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
    )
    with pytest.raises(AssertionError, match="non-commercial"):
        validate_assets_md_provenance(bad_nc_phrase)

    bad_missing_author = (
        f"{h1} Assets\n\n"
        "| Pack | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| PackA | TBD | CC0-1.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
    )
    with pytest.raises(AssertionError, match="missing author"):
        validate_assets_md_provenance(bad_missing_author)

    bad_uncredited_by = (
        f"{h1} Assets\n\n"
        "| Pack | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| PackA | Buch | CC-BY 3.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
    )
    with pytest.raises(AssertionError, match="explicit credit"):
        validate_assets_md_provenance(bad_uncredited_by)

    bad_untrusted_url = (
        f"{h1} Assets\n\n"
        "| Pack | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| PackA | Kenney | CC0-1.0 | https://untrusted-rips.example.com/sprites.zip |\n"
    )
    with pytest.raises(AssertionError, match="verified open-asset source"):
        validate_assets_md_provenance(bad_untrusted_url)

    bad_dash = (
        f"{h1} Assets {FORBIDDEN_DASHES[4]} Provenance\n\n"
        "| Pack | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| PackA | Kenney | CC0-1.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
    )
    with pytest.raises(AssertionError, match="forbidden unicode dash"):
        validate_assets_md_provenance(bad_dash)


def test_png_and_manifest_provenance_validators_catch_corrupt_or_unsynced_sprites(tmp_path: Path) -> None:
    demo_dir = _write_clean_synthetic_demo(tmp_path)
    h1 = HASH_CHAR
    assets_md = (
        f"{h1} Assets\n\n"
        "| Pack ID | Author | License | Source URL |\n"
        "|---|---|---|---|\n"
        "| `kenney-roguelike-indoor` | Kenney | CC0-1.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
    )
    md_packs = validate_assets_md_provenance(assets_md)
    m_path = demo_dir / "assets" / "manifest.js"
    rep = validate_manifest_and_sprites_provenance(
        manifest_js_path=m_path,
        demo_dir=demo_dir,
        assets_md_packs=md_packs,
    )
    assert rep == {"pack_count": 1, "sprite_count": 1}

    orig_manifest = m_path.read_text(encoding="utf-8")
    m_path.write_text(
        orig_manifest.replace("kenney-roguelike-indoor", "undocumented-pack", 1),
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="undocumented|undeclared"):
        validate_manifest_and_sprites_provenance(
            manifest_js_path=m_path,
            demo_dir=demo_dir,
            assets_md_packs=md_packs,
        )
    m_path.write_text(orig_manifest, encoding="utf-8")

    (demo_dir / "assets" / "corrupt.png").write_bytes(b"not-a-valid-png")
    with pytest.raises(AssertionError, match="invalid PNG signature"):
        audit_demo_directory_offline(demo_dir)


def test_corpus_provenance_validator_passes_valid_and_catches_tampering(tmp_path: Path) -> None:
    paths = _write_synthetic_corpus_fixture(tmp_path)
    report = validate_outthink_corpus_provenance(**paths)
    assert report["case_count"] == 1
    assert report["verified_level_runs"] == 2

    base_bundle = json.loads(paths["outthink_json_path"].read_text(encoding="utf-8"))

    b_fallback = json.loads(json.dumps(base_bundle))
    b_fallback["meta"]["isBootstrapFallback"] = True
    paths["outthink_json_path"].write_text(json.dumps(b_fallback), encoding="utf-8")
    with pytest.raises(AssertionError, match="isBootstrapFallback"):
        validate_outthink_corpus_provenance(**paths)

    b_desync = json.loads(json.dumps(base_bundle))
    b_desync["cases"][0]["title"] = "Out of sync title"
    paths["outthink_json_path"].write_text(json.dumps(b_desync), encoding="utf-8")
    with pytest.raises(AssertionError, match="differs from"):
        validate_outthink_corpus_provenance(**paths)

    b_bad_score = json.loads(json.dumps(base_bundle))
    b_bad_score["cases"][0]["thinking_levels"][1]["score"] = 0.99
    paths["outthink_json_path"].write_text(json.dumps(b_bad_score), encoding="utf-8")
    paths["cases_js_path"].write_text(
        "window.OUTTHINK_DATA = " + json.dumps(b_bad_score) + ";\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="score"):
        validate_outthink_corpus_provenance(**paths)

    b_bad_tokens = json.loads(json.dumps(base_bundle))
    b_bad_tokens["cases"][0]["thinking_levels"][0]["thinking_tokens"] = 999999
    paths["outthink_json_path"].write_text(json.dumps(b_bad_tokens), encoding="utf-8")
    paths["cases_js_path"].write_text(
        "window.OUTTHINK_DATA = " + json.dumps(b_bad_tokens) + ";\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="thinking_tokens"):
        validate_outthink_corpus_provenance(**paths)

    b_bad_world = json.loads(json.dumps(base_bundle))
    b_bad_world["cases"][0]["seed"] = 999
    paths["outthink_json_path"].write_text(json.dumps(b_bad_world), encoding="utf-8")
    paths["cases_js_path"].write_text(
        "window.OUTTHINK_DATA = " + json.dumps(b_bad_world) + ";\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="missing from"):
        validate_outthink_corpus_provenance(**paths)


def test_live_demo_directory_strict_offline_and_zero_secrets() -> None:
    if not LIVE_DEMO_DIR.is_dir() or not LIVE_INDEX_HTML.is_file():
        pytest.skip("demo/out-think-gemini/ not yet merged on this branch")
    report = audit_demo_directory_offline(LIVE_DEMO_DIR)
    assert int(report["scanned_count"]) >= 1


def test_live_assets_md_cc0_provenance_and_manifest_sync() -> None:
    if not LIVE_ASSETS_MD.is_file():
        pytest.skip("docs/demo/ASSETS.md not yet merged on this branch")
    packs = validate_assets_md_provenance(LIVE_ASSETS_MD.read_text(encoding="utf-8"))
    assert len(packs) >= 1

    if LIVE_MANIFEST_JS.is_file():
        m_rep = validate_manifest_and_sprites_provenance(
            manifest_js_path=LIVE_MANIFEST_JS,
            demo_dir=LIVE_DEMO_DIR,
            assets_md_packs=packs,
        )
        assert m_rep["pack_count"] >= 1
        assert m_rep["sprite_count"] >= 1


def test_live_outthink_json_and_cases_js_provenance_against_committed_runs() -> None:
    if not LIVE_OUTTHINK_JSON.is_file() or not LIVE_CASES_JS.is_file():
        pytest.skip("results/gemini/out_think_gemini.json or demo/out-think-gemini/cases.js not yet merged")
    report = validate_outthink_corpus_provenance(
        outthink_json_path=LIVE_OUTTHINK_JSON,
        cases_js_path=LIVE_CASES_JS,
        ladder_episodes_gz=LIVE_LADDER_EPISODES_GZ,
        ladder_ledger_gz=LIVE_LADDER_LEDGER_GZ,
        reference_dir=LIVE_REFERENCE_DIR,
        inproc_carbon_dir=LIVE_INPROC_CARBON_DIR,
    )
    assert int(report["case_count"]) >= 1
    assert int(report["verified_level_runs"]) >= 2


def test_self_hygiene_zero_comments_zero_dashes_zero_sdk_and_protected_paths() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")

    assert HASH_CHAR not in src, "Forbidden hash comment character found in test file"
    for ch in FORBIDDEN_DASHES:
        assert ch not in src, f"Forbidden unicode dash U+{ord(ch):04X} found in test file"

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"Python comments found: {comments}"

    tree = ast.parse(src)
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    forbidden_imports = ("google", "genai", "httpx", "requests", "urllib", "aiohttp", "websockets")
    for mod in imported_modules:
        assert not any(f in mod for f in forbidden_imports), f"Forbidden network/SDK import: {mod}"

    assert PROTECTED_PATHS_FILE.is_file()
    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    assert rules

    checked_paths = {self_path.relative_to(ROOT).as_posix()}
    for pattern in (
        "demo/out-think-gemini/**/*",
        "canary/gemini/outthink*.py",
        "tests/test_*outthink*.py",
        "docs/demo/**/*",
    ):
        for path in ROOT.glob(pattern):
            if path.is_file():
                checked_paths.add(path.relative_to(ROOT).as_posix())

    for rel in sorted(checked_paths):
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"Protected path prefix violated: {rel} matches {rule}"
            else:
                assert rel != rule, f"Protected file violated: {rel}"
