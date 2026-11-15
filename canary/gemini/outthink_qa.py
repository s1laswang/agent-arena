"""Offline quality assurance, provenance verification, and static bundle checks for Out-Think Gemini."""
from __future__ import annotations

import argparse
import base64
import binascii
import gzip
import json
import math
import os
import re
import shutil
import struct
import subprocess
import zlib
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from canary.gemini.ladder_report import price as ladder_list_price
from canary.llm.pricing import cost as llm_pricing_cost

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DATA_URI_PNG_PREFIX = "data:image/png;base64,"
DEFAULT_DEMO_REL = "demo/out-think-gemini"
DEFAULT_ASSETS_DOC_REL = "docs/demo/ASSETS.md"
DEFAULT_MAX_PNG_BYTES = 15 * 1024 * 1024
MIN_LADDER_EPISODES = 150

HASH_CHAR = chr(35)
SLASH_CHAR = chr(47)
STAR_CHAR = chr(42)
FORBIDDEN_DASH_CODEPOINTS: tuple[int, ...] = (
    0x2010,
    0x2011,
    0x2012,
    0x2013,
    0x2014,
    0x2015,
    0x2212,
)
FORBIDDEN_DASHES: tuple[str, ...] = tuple(chr(cp) for cp in FORBIDDEN_DASH_CODEPOINTS)

PLACEHOLDER_AUTHORS = frozenset(
    {"", "-", "n/a", "na", "none", "unknown", "tbd", "todo", "null", "anonymous"}
)

APPROVED_PUBLIC_LICENSES = frozenset(
    {
        "cc0",
        "cc0-1.0",
        "cc0 1.0",
        "cc0 1.0 universal",
        "public domain",
        "pd",
        "unlicense",
        "0bsd",
        "mit",
        "isc",
        "bsd-2-clause",
        "bsd-3-clause",
        "apache-2.0",
        "zlib",
    }
)

FORBIDDEN_LICENSE_TOKENS: tuple[str, ...] = (
    "paid",
    "ripped",
    "proprietary",
    "all rights reserved",
    "unlicensed",
    "commercial",
    "non-commercial",
    "noncommercial",
    "cc-by-nc",
    "by-nc",
    "cc by-nc",
    "cc-by-nd",
    "by-nd",
    "cc by-nd",
    "no derivatives",
    "unknown",
    "tbd",
    "todo",
)

FORBIDDEN_SOURCE_DOMAINS: tuple[str, ...] = (
    "spriters-resource",
    "models-resource",
    "textures-resource",
    "sounds-resource",
    "shutterstock",
    "gettyimages",
    "stock.adobe",
    "craftpix",
    "graphicriver",
    "envato",
)

REQUIRED_ENGINE_EXPORTS: tuple[str, ...] = (
    "computeBreakEvenProb",
    "computeAccusationEv",
    "normalizeCase",
    "loadDataset",
    "evaluateCall",
    "createScoreboard",
)

OPTIONAL_ENRICHMENT_SCRIPTS: frozenset[str] = frozenset(
    {
        "fallback_cases.js",
        "personas.js",
        "annotations.js",
        "failure_modes.js",
        "reveal_card.js",
        "evidence_cards.js",
        "chatter.js",
        "assets/manifest.js",
    }
)

API_KEY_ENV_VARS = frozenset(
    {
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
    }
)


def find_forbidden_dashes(text: str) -> list[str]:
    found: list[str] = []
    for cp in FORBIDDEN_DASH_CODEPOINTS:
        ch = chr(cp)
        if ch in text:
            found.append(f"U+{cp:04X}")
    return found


def _open_jsonl(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _resolve_demo_dir(root: str | Path, demo_rel: str | Path = DEFAULT_DEMO_REL) -> Path:
    root_path = Path(root)
    rel_path = Path(demo_rel)
    candidate = root_path / rel_path
    if candidate.is_dir() or (candidate / "index.html").is_file() or (candidate / "cases.js").is_file():
        return candidate
    if (
        (root_path / "index.html").is_file()
        or (root_path / "cases.js").is_file()
        or (root_path / "engine.js").is_file()
        or (root_path / "assets").is_dir()
    ):
        return root_path
    return candidate


def _strip_js_comments_keep_strings(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    line_open = SLASH_CHAR + SLASH_CHAR
    block_open = SLASH_CHAR + STAR_CHAR
    block_close = STAR_CHAR + SLASH_CHAR
    while i < n:
        ch = source[i]
        if ch in ("'", '"', "`"):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                c = source[i]
                out.append(c)
                if c == "\\" and i + 1 < n:
                    i += 1
                    out.append(source[i])
                elif c == quote:
                    i += 1
                    break
                i += 1
        elif source.startswith(line_open, i):
            i += 2
            while i < n and source[i] != "\n":
                i += 1
        elif source.startswith(block_open, i):
            end = source.find(block_close, i + 2)
            if end == -1:
                break
            out.append(" ")
            i = end + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _find_forbidden_js_network_calls(js_source: str) -> list[str]:
    stripped = _strip_js_comments_keep_strings(js_source)
    hits: list[str] = []
    patterns = (
        ("fetch()", re.compile(r"(?<![A-Za-z0-9_$])fetch\s*\(")),
        ("XMLHttpRequest", re.compile(r"\bXMLHttpRequest\b")),
        ("navigator.sendBeacon()", re.compile(r"\bnavigator\s*\.\s*sendBeacon\s*\(")),
        ("axios", re.compile(r"\baxios\s*\.\s*(?:get|post|request)\s*\(")),
    )
    for label, pat in patterns:
        if pat.search(stripped):
            hits.append(label)
    return hits


def _extract_js_global_json(js_text: str, global_names: tuple[str, ...]) -> Any:
    decoder = json.JSONDecoder()
    for name in global_names:
        pat = re.compile(
            rf"(?:(?:window|globalThis|root|self)\s*\.\s*{re.escape(name)}|(?:var|let|const)\s+{re.escape(name)})\s*=\s*"
        )
        for match in pat.finditer(js_text):
            rhs = js_text[match.end() :].lstrip()
            if rhs.startswith(("{", "[")):
                obj, _ = decoder.raw_decode(rhs)
                return obj
            ident_match = re.match(r"([A-Za-z_$][A-Za-z0-9_$]*)", rhs)
            if ident_match:
                ident = ident_match.group(1)
                var_pat = re.compile(rf"(?:var|let|const)\s+{re.escape(ident)}\s*=\s*")
                for var_match in var_pat.finditer(js_text):
                    var_rhs = js_text[var_match.end() :].lstrip()
                    if var_rhs.startswith(("{", "[")):
                        obj, _ = decoder.raw_decode(var_rhs)
                        return obj
    stripped = js_text.strip()
    if stripped.startswith(("{", "[")):
        obj, _ = decoder.raw_decode(stripped)
        return obj
    raise ValueError(f"Could not parse JSON payload for {global_names} from JS file")


def validate_png_bytes(raw: bytes) -> dict[str, int]:
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("PNG content must be bytes")
    if len(raw) < 33:
        raise ValueError(f"PNG data too short ({len(raw)} bytes)")
    if bytes(raw[:8]) != PNG_SIGNATURE:
        raise ValueError("Invalid PNG 8-byte signature")

    offset = 8
    width = 0
    height = 0
    bit_depth = 0
    color_type = 0
    saw_ihdr = False
    saw_iend = False
    idat_chunks: list[bytes] = []

    while offset < len(raw):
        if offset + 12 > len(raw):
            raise ValueError("Truncated PNG chunk header")
        length, chunk_type = struct.unpack(">I4s", raw[offset : offset + 8])
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(raw):
            raise ValueError(f"Truncated PNG chunk {chunk_type!r}")
        chunk_data = bytes(raw[data_start:data_end])
        (expected_crc,) = struct.unpack(">I", raw[data_end:crc_end])
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError(f"PNG CRC mismatch in chunk {chunk_type.decode('ascii', 'replace')}")

        if not saw_ihdr:
            if chunk_type != b"IHDR":
                raise ValueError("First PNG chunk must be IHDR")
            if length != 13:
                raise ValueError(f"Invalid IHDR length {length}")
            width, height, bit_depth, color_type, comp, filt, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            if width <= 0 or height <= 0:
                raise ValueError(f"Invalid PNG dimensions {width}x{height}")
            if comp != 0 or filt != 0 or interlace not in (0, 1):
                raise ValueError("Invalid PNG header flags")
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0:
                raise ValueError("Non-empty PNG IEND chunk")
            saw_iend = True
            if crc_end != len(raw):
                raise ValueError("Trailing bytes after PNG IEND chunk")
            break
        offset = crc_end

    if not saw_ihdr or not saw_iend or not idat_chunks:
        raise ValueError("Incomplete PNG stream (missing IHDR, IDAT, or IEND)")

    try:
        decompressed = zlib.decompress(b"".join(idat_chunks))
    except zlib.error as exc:
        raise ValueError(f"Corrupt PNG IDAT deflate stream: {exc}") from exc
    if not decompressed:
        raise ValueError("Empty decompressed PNG image data")

    return {
        "width": width,
        "height": height,
        "bit_depth": bit_depth,
        "color_type": color_type,
        "bytes": len(raw),
    }


def load_ladder_ground_truth(
    root: str | Path = ".",
    episodes_path: str | Path | None = None,
    ledger_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    ep_file = (
        Path(episodes_path)
        if episodes_path is not None
        else root_path / "results" / "gemini" / "ladder_episodes.jsonl.gz"
    )
    led_file = (
        Path(ledger_path)
        if ledger_path is not None
        else root_path / "results" / "gemini" / "ladder_ledger.jsonl.gz"
    )

    if not ep_file.is_file():
        raise FileNotFoundError(f"Missing committed ladder episodes archive: {ep_file}")

    ledger_by_run: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "cost_usd": 0.0, "in": 0, "out": 0, "thinking": 0, "cached": 0}
    )
    if led_file.is_file():
        with _open_jsonl(led_file) as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line:
                    continue
                row = json.loads(line)
                rid = row.get("run_id")
                if not rid:
                    continue
                slot = ledger_by_run[str(rid)]
                slot["calls"] += 1
                slot["cost_usd"] += float(row.get("cost_usd") or 0.0)
                slot["in"] += int(row.get("in") or 0)
                slot["out"] += int(row.get("out") or 0)
                slot["thinking"] += int(row.get("thinking") or 0)
                slot["cached"] += int(row.get("cached") or 0)

    episodes: list[dict[str, Any]] = []
    by_run_id: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str, str, int], dict[str, Any]] = {}

    with _open_jsonl(ep_file) as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line:
                continue
            raw_ep = json.loads(line)
            meta = raw_ep.get("meta") or {}
            if meta.get("valid") is False or raw_ep.get("end_reason") == "error":
                continue

            lad = meta.get("ladder") or {}
            model = str(lad.get("model") or raw_ep.get("model") or "")
            level = str(lad.get("level") or lad.get("thinking_level") or raw_ep.get("level") or "")
            tier = str(lad.get("tier") or raw_ep.get("tier") or "")
            seed_val = lad.get("seed") if lad.get("seed") is not None else raw_ep.get("seed", 0)
            seed = int(seed_val)
            run_id = str(lad.get("run_id") or raw_ep.get("run_id") or f"ladder:{model}/{level}/{tier}/{seed}")

            key = (model, level, tier, seed)
            if key in by_key:
                continue

            tok = lad.get("tokens") or {}
            led_slot = ledger_by_run.get(run_id, {})
            tin = int(tok.get("in") or led_slot.get("in") or 0)
            tout = int(tok.get("out") or led_slot.get("out") or 0)
            tthink = int(tok.get("thinking") or led_slot.get("thinking") or 0)
            tcached = int(tok.get("cached") or led_slot.get("cached") or 0)

            led_cost = float(led_slot.get("cost_usd") or 0.0)
            lp_cost = float(ladder_list_price(model, tin, tout + tthink, tcached))
            if math.isnan(lp_cost):
                lp_cost = 0.0
            pricing_res = llm_pricing_cost(model, tin, tout + tthink, tcached)
            pr_cost = float(pricing_res.get("cost_usd_est") or pricing_res.get("cost_usd") or 0.0)
            raw_cost = float(lad.get("cost_usd") or raw_ep.get("cost_usd") or 0.0)

            if led_cost > 0.0:
                resolved_cost = led_cost
            elif lp_cost > 0.0:
                resolved_cost = lp_cost
            elif pr_cost > 0.0:
                resolved_cost = pr_cost
            else:
                resolved_cost = raw_cost

            steps = list(raw_ep.get("steps") or [])
            accused_raw = raw_ep.get("accused")
            accused = str(accused_raw) if accused_raw is not None and str(accused_raw) != "" else None

            ep_record: dict[str, Any] = {
                "run_id": run_id,
                "model": model,
                "level": level,
                "tier": tier,
                "seed": seed,
                "accused": accused,
                "correct": bool(raw_ep.get("correct")),
                "score": float(raw_ep.get("score") or 0.0),
                "final_day": int(raw_ep.get("final_day") or 0),
                "end_reason": str(raw_ep.get("end_reason") or ""),
                "cost_usd": float(resolved_cost),
                "ledger_cost_usd": led_cost,
                "list_cost_usd": lp_cost,
                "thinking_tokens": tthink,
                "input_tokens": tin,
                "output_tokens": tout,
                "cached_tokens": tcached,
                "calls": int(tok.get("calls") or len(steps)),
                "ledger_calls": int(led_slot.get("calls") or 0),
                "steps": steps,
            }
            episodes.append(ep_record)
            by_run_id[run_id] = ep_record
            by_key[key] = ep_record

    return {
        "episodes": episodes,
        "by_run_id": by_run_id,
        "by_key": by_key,
        "ledger_by_run_id": dict(ledger_by_run),
    }


class _StaticHTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str]] = []
        self.inline_scripts: list[str] = []
        self.links: list[dict[str, str]] = []
        self.media: list[dict[str, str]] = []
        self._in_script = False
        self._script_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        t = tag.lower()
        if t == "script":
            if "src" in attr_map and attr_map["src"].strip():
                self.scripts.append(
                    {"src": attr_map["src"].strip(), "type": attr_map.get("type", "").strip()}
                )
            else:
                self._in_script = True
                self._script_buf = []
        elif t == "link":
            href = attr_map.get("href", "").strip()
            rel = attr_map.get("rel", "").strip().lower()
            if href:
                self.links.append({"href": href, "rel": rel})
        elif t in ("img", "audio", "video", "source"):
            src = attr_map.get("src", "").strip()
            if src:
                self.media.append({"tag": t, "src": src})

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self._script_buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_script:
            self._in_script = False
            self.inline_scripts.append("".join(self._script_buf))
            self._script_buf = []


def _strip_url_query_fragment(ref: str) -> str:
    clean = ref.split(HASH_CHAR, 1)[0]
    clean = clean.split("?", 1)[0]
    return clean.strip()


def check_static_page(
    root: str | Path = ".",
    demo_rel: str | Path = DEFAULT_DEMO_REL,
    *,
    allow_optional_scripts: bool = True,
) -> dict[str, Any]:
    demo_dir = _resolve_demo_dir(root, demo_rel)
    index_path = demo_dir / "index.html"
    errors: list[str] = []
    local_scripts: list[str] = []
    optional_missing_scripts: list[str] = []
    external_scripts: list[str] = []
    local_styles: list[str] = []
    local_images: list[str] = []

    if not index_path.is_file():
        errors.append(f"Missing index.html at {index_path}")
        return {
            "passed": False,
            "ok": False,
            "errors": errors,
            "demo_dir": str(demo_dir),
            "local_scripts": local_scripts,
            "optional_missing_scripts": optional_missing_scripts,
            "external_scripts": external_scripts,
            "local_styles": local_styles,
            "local_images": local_images,
        }

    html_text = index_path.read_text(encoding="utf-8")
    html_dashes = find_forbidden_dashes(html_text)
    if html_dashes:
        errors.append(f"Forbidden dash characters {html_dashes} in {index_path.name}")

    inspector = _StaticHTMLInspector()
    inspector.feed(html_text)

    for idx, inline_js in enumerate(inspector.inline_scripts):
        net_hits = _find_forbidden_js_network_calls(inline_js)
        if net_hits:
            errors.append(f"Forbidden offline network call {net_hits} in inline script {idx + 1}")

    demo_root_resolved = demo_dir.resolve()

    def _verify_local_ref(raw_ref: str, kind: str, bucket: list[str]) -> Path | None:
        clean_ref = _strip_url_query_fragment(raw_ref)
        if not clean_ref:
            return None
        if clean_ref.startswith("data:"):
            if clean_ref.startswith(DATA_URI_PNG_PREFIX):
                b64 = clean_ref[len(DATA_URI_PNG_PREFIX) :]
                try:
                    validate_png_bytes(base64.b64decode(b64, validate=True))
                except (ValueError, binascii.Error) as exc:
                    errors.append(f"Invalid inline PNG data URI in {kind}: {exc}")
            return None
        if clean_ref.startswith("https://"):
            if kind == "script":
                external_scripts.append(clean_ref)
            return None
        if clean_ref.startswith(("http://", "file://", "//")):
            errors.append(f"Non-portable {kind} URL '{raw_ref}' in index.html")
            return None
        if clean_ref.startswith("/"):
            errors.append(f"Root-relative {kind} path '{raw_ref}' breaks under file:// protocol")
            return None

        target = (demo_dir / clean_ref).resolve()
        try:
            target.relative_to(demo_root_resolved)
        except ValueError:
            errors.append(f"Local {kind} reference '{raw_ref}' escapes demo directory")
            return None

        if not target.is_file():
            if (
                kind == "script"
                and allow_optional_scripts
                and clean_ref in OPTIONAL_ENRICHMENT_SCRIPTS
            ):
                optional_missing_scripts.append(clean_ref)
                return None
            errors.append(f"Missing local {kind} file '{clean_ref}' referenced by index.html")
            return None
        bucket.append(clean_ref)
        return target

    checked_files: set[Path] = {index_path.resolve()}

    text_exts = {".js", ".mjs", ".cjs", ".css", ".html", ".svg"}

    for sc in inspector.scripts:
        sc_type = sc["type"].lower()
        if sc_type == "module" and not sc["src"].startswith("https://"):
            errors.append(f"ES module script '{sc['src']}' is blocked by CORS under file://")
        target = _verify_local_ref(sc["src"], "script", local_scripts)
        if target is not None and target.suffix.lower() in text_exts:
            checked_files.add(target)

    for lnk in inspector.links:
        rel = lnk["rel"]
        href = lnk["href"]
        if any(r in rel for r in ("preconnect", "dns-prefetch", "canonical")):
            continue
        target = _verify_local_ref(href, "stylesheet/link", local_styles)
        if target is not None:
            if target.suffix.lower() in text_exts:
                checked_files.add(target)
            elif target.suffix.lower() == ".png":
                try:
                    validate_png_bytes(target.read_bytes())
                except ValueError as exc:
                    errors.append(f"Invalid PNG icon '{href}': {exc}")

    for med in inspector.media:
        target = _verify_local_ref(med["src"], med["tag"], local_images)
        if target is not None:
            if target.suffix.lower() in text_exts:
                checked_files.add(target)
            elif target.suffix.lower() == ".png":
                try:
                    validate_png_bytes(target.read_bytes())
                except ValueError as exc:
                    errors.append(f"Invalid PNG image '{med['src']}': {exc}")

    for candidate in sorted(demo_dir.rglob("*")):
        if not candidate.is_file():
            continue
        if candidate.suffix.lower() in (".js", ".mjs", ".cjs", ".css", ".html"):
            checked_files.add(candidate.resolve())

    for file_path in sorted(checked_files):
        if file_path == index_path.resolve():
            continue
        rel_label = str(file_path.relative_to(demo_root_resolved))
        txt = file_path.read_text(encoding="utf-8")
        dashes = find_forbidden_dashes(txt)
        if dashes:
            errors.append(f"Forbidden dash characters {dashes} in {rel_label}")
        if file_path.suffix.lower() in (".js", ".mjs", ".cjs"):
            net_hits = _find_forbidden_js_network_calls(txt)
            if net_hits:
                errors.append(f"Forbidden offline network call {net_hits} in {rel_label}")

    passed = len(errors) == 0
    return {
        "passed": passed,
        "ok": passed,
        "errors": errors,
        "demo_dir": str(demo_dir),
        "local_scripts": local_scripts,
        "optional_missing_scripts": optional_missing_scripts,
        "external_scripts": external_scripts,
        "local_styles": local_styles,
        "local_images": local_images,
    }


def _strip_md_cell(cell: str) -> str:
    txt = cell.strip()
    if txt.startswith("`") and txt.endswith("`") and len(txt) >= 2:
        txt = txt[1:-1].strip()
    return txt


def _extract_url_from_cell(cell: str) -> str:
    txt = _strip_md_cell(cell)
    m = re.search(r"https?://[^\s)>`\"']+", txt)
    return m.group(0) if m else txt


def _parse_assets_markdown_packs(md_text: str) -> list[dict[str, str]]:
    lines = md_text.splitlines()
    packs: list[dict[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and line.endswith("|") and i + 1 < len(lines):
            sep = lines[i + 1].strip()
            if sep.startswith("|") and "-" in sep:
                headers = [_strip_md_cell(c).lower() for c in line.strip("|").split("|")]
                lic_idx = next(
                    (idx for idx, h in enumerate(headers) if "licen" in h),
                    None,
                )
                auth_idx = next(
                    (
                        idx
                        for idx, h in enumerate(headers)
                        if any(k in h for k in ("author", "creator", "artist", "credit", "by"))
                    ),
                    None,
                )
                src_idx = next(
                    (
                        idx
                        for idx, h in enumerate(headers)
                        if "source" in h
                        or ("url" in h and "download" not in h)
                        or "link" in h
                        or "page" in h
                    ),
                    None,
                )
                if src_idx is None:
                    src_idx = next(
                        (idx for idx, h in enumerate(headers) if "url" in h),
                        None,
                    )
                id_idx = next(
                    (
                        idx
                        for idx, h in enumerate(headers)
                        if any(k in h for k in ("id", "pack", "asset", "name", "file", "sprite"))
                    ),
                    0,
                )
                name_idx = next(
                    (idx for idx, h in enumerate(headers) if "name" in h and idx != id_idx),
                    id_idx,
                )

                i += 2
                while i < len(lines):
                    row_line = lines[i].strip()
                    if not (row_line.startswith("|") and row_line.endswith("|")):
                        break
                    cells = [c.strip() for c in row_line.strip("|").split("|")]
                    if lic_idx is not None and lic_idx < len(cells):
                        pack_id = _strip_md_cell(cells[id_idx]) if id_idx < len(cells) else ""
                        pack_name = _strip_md_cell(cells[name_idx]) if name_idx < len(cells) else pack_id
                        author = (
                            _strip_md_cell(cells[auth_idx])
                            if auth_idx is not None and auth_idx < len(cells)
                            else ""
                        )
                        lic = _strip_md_cell(cells[lic_idx])
                        src = (
                            _extract_url_from_cell(cells[src_idx])
                            if src_idx is not None and src_idx < len(cells)
                            else ""
                        )
                        packs.append(
                            {
                                "pack_id": pack_id,
                                "pack_name": pack_name,
                                "author": author,
                                "license": lic,
                                "source_url": src,
                            }
                        )
                    i += 1
                continue
        i += 1
    return packs


def _classify_license(raw_license: str) -> tuple[str, str]:
    cleaned = raw_license.strip().strip("`").strip()
    norm = " ".join(cleaned.lower().split())
    if not norm:
        return "forbidden", "Empty license"
    for bad in FORBIDDEN_LICENSE_TOKENS:
        if bad in norm:
            return "forbidden", f"Forbidden license '{cleaned}'"
    if norm in APPROVED_PUBLIC_LICENSES or norm.startswith("cc0"):
        return "public", cleaned
    if any(
        norm.startswith(prefix)
        for prefix in ("cc-by", "cc by", "oga-by", "oga by")
    ):
        return "attribution", cleaned
    return "forbidden", f"Unapproved license '{cleaned}'"


def _collect_manifest_sprite_values(manifest_obj: Any) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if not isinstance(manifest_obj, dict):
        return found

    SKIP_META_KEYS = {"version", "meta", "packs", "credits", "license", "title", "generated_at"}

    def _walk(node: Any, prefix: str) -> None:
        if isinstance(node, str):
            s = node.strip()
            if s.startswith("data:") or s.lower().endswith(".png"):
                found.append((prefix or "sprite", s))
        elif isinstance(node, dict):
            for key_field in ("dataUri", "data_uri", "src", "url", "path", "png"):
                if key_field in node and isinstance(node[key_field], str):
                    found.append((prefix or key_field, node[key_field].strip()))
                    return
            for k, v in node.items():
                if not prefix and k in SKIP_META_KEYS:
                    continue
                next_prefix = f"{prefix}.{k}" if prefix else str(k)
                _walk(v, next_prefix)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                _walk(item, f"{prefix}[{idx}]")

    if "sprites" in manifest_obj and isinstance(manifest_obj["sprites"], dict):
        for section in ("sprites", "tilesets", "icons", "portraits"):
            if section in manifest_obj:
                _walk(manifest_obj[section], section)
    else:
        _walk(manifest_obj, "")
    return found


def check_assets_and_licenses(
    root: str | Path = ".",
    *,
    demo_rel: str | Path = DEFAULT_DEMO_REL,
    assets_doc_rel: str | Path = DEFAULT_ASSETS_DOC_REL,
    max_png_bytes: int = DEFAULT_MAX_PNG_BYTES,
) -> dict[str, Any]:
    root_path = Path(root)
    demo_dir = _resolve_demo_dir(root_path, demo_rel)
    assets_dir = demo_dir / "assets"
    index_path = demo_dir / "index.html"

    assets_doc = root_path / assets_doc_rel
    if not assets_doc.is_file() and (root_path / "ASSETS.md").is_file():
        assets_doc = root_path / "ASSETS.md"

    errors: list[str] = []
    packs: list[dict[str, str]] = []
    png_files: list[str] = []
    total_png_bytes = 0
    manifest_sprite_count = 0

    if not assets_doc.is_file():
        errors.append(f"Missing asset provenance ledger {assets_doc}")
    else:
        md_text = assets_doc.read_text(encoding="utf-8")
        md_dashes = find_forbidden_dashes(md_text)
        if md_dashes:
            errors.append(f"Forbidden dash characters {md_dashes} in {assets_doc.name}")

        lower_md = md_text.lower()
        for bad_domain in FORBIDDEN_SOURCE_DOMAINS:
            for line in lower_md.splitlines():
                if bad_domain in line and not any(
                    neg in line for neg in ("zero ", "no ", "never ", "not ", "forbidden")
                ):
                    errors.append(f"Forbidden asset source '{bad_domain}' referenced in ASSETS.md")
                    break

        packs = _parse_assets_markdown_packs(md_text)
        if not packs:
            errors.append("No licensed asset pack rows parsed from ASSETS.md table")

        index_text = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
        index_lower = index_text.lower()

        for pack in packs:
            label = pack["pack_id"] or pack["pack_name"] or "<unnamed>"
            author = pack["author"]
            src_url = pack["source_url"]
            lic_kind, lic_detail = _classify_license(pack["license"])

            if author.lower() in PLACEHOLDER_AUTHORS:
                errors.append(f"Missing or placeholder author '{author}' for pack '{label}'")

            if not src_url.startswith("https://"):
                errors.append(f"Pack '{label}' must have an https:// Source URL, got '{src_url}'")
            else:
                for bad_domain in FORBIDDEN_SOURCE_DOMAINS:
                    if bad_domain in src_url.lower():
                        errors.append(f"Forbidden source domain '{bad_domain}' in pack '{label}'")

            if lic_kind == "forbidden":
                errors.append(f"Pack '{label}': {lic_detail}")
            elif lic_kind == "attribution":
                if not index_path.is_file():
                    errors.append(
                        f"Pack '{label}' uses {lic_detail} requiring credit for '{author}' in index.html (index.html missing)"
                    )
                elif author.lower() not in index_lower:
                    errors.append(
                        f"Pack '{label}' uses {lic_detail} but author '{author}' is not credited in index.html"
                    )

    if assets_dir.is_dir():
        for png_path in sorted(assets_dir.rglob("*.png")):
            if not png_path.is_file():
                continue
            rel_name = str(png_path.relative_to(demo_dir))
            png_files.append(rel_name)
            raw = png_path.read_bytes()
            sz = len(raw)
            total_png_bytes += sz
            if sz > max_png_bytes:
                errors.append(
                    f"PNG file '{rel_name}' size {sz} bytes exceeds max_png_bytes ({max_png_bytes})"
                )
            try:
                validate_png_bytes(raw)
            except ValueError as exc:
                errors.append(f"Invalid PNG file '{rel_name}': {exc}")

        manifest_path = assets_dir / "manifest.js"
        if manifest_path.is_file():
            manifest_text = manifest_path.read_text(encoding="utf-8")
            m_dashes = find_forbidden_dashes(manifest_text)
            if m_dashes:
                errors.append(f"Forbidden dash characters {m_dashes} in assets/manifest.js")
            net_hits = _find_forbidden_js_network_calls(manifest_text)
            if net_hits:
                errors.append(f"Forbidden network call {net_hits} in assets/manifest.js")
            try:
                manifest_obj = _extract_js_global_json(manifest_text, ("OUTTHINK_ASSETS",))
            except (ValueError, json.JSONDecodeError) as exc:
                errors.append(f"Invalid window.OUTTHINK_ASSETS in assets/manifest.js: {exc}")
                manifest_obj = None

            if manifest_obj is not None:
                sprite_entries = _collect_manifest_sprite_values(manifest_obj)
                manifest_sprite_count = len(sprite_entries)
                if manifest_sprite_count == 0:
                    errors.append("window.OUTTHINK_ASSETS contains zero sprite entries")
                for sprite_key, sprite_val in sprite_entries:
                    if sprite_val.startswith("data:"):
                        if not sprite_val.startswith(DATA_URI_PNG_PREFIX):
                            errors.append(
                                f"Sprite '{sprite_key}' uses non-PNG data URI prefix"
                            )
                            continue
                        b64_payload = sprite_val[len(DATA_URI_PNG_PREFIX) :]
                        try:
                            png_bytes = base64.b64decode(b64_payload, validate=True)
                        except (ValueError, binascii.Error) as exc:
                            errors.append(f"Sprite '{sprite_key}' invalid base64 PNG: {exc}")
                            continue
                        sz = len(png_bytes)
                        total_png_bytes += sz
                        if sz > max_png_bytes:
                            errors.append(
                                f"Sprite '{sprite_key}' PNG bytes ({sz}) exceed max_png_bytes ({max_png_bytes})"
                            )
                        try:
                            validate_png_bytes(png_bytes)
                        except ValueError as exc:
                            errors.append(f"Sprite '{sprite_key}' corrupt PNG bytes: {exc}")
                    else:
                        clean_rel = _strip_url_query_fragment(sprite_val)
                        cand_a = demo_dir / clean_rel
                        cand_b = assets_dir / clean_rel
                        resolved_png = cand_a if cand_a.is_file() else cand_b
                        if not resolved_png.is_file():
                            errors.append(
                                f"Sprite '{sprite_key}' references missing local PNG '{sprite_val}'"
                            )
                        else:
                            try:
                                validate_png_bytes(resolved_png.read_bytes())
                            except ValueError as exc:
                                errors.append(
                                    f"Sprite '{sprite_key}' local PNG '{sprite_val}' invalid: {exc}"
                                )

    if total_png_bytes > max_png_bytes:
        errors.append(
            f"Total PNG asset bytes ({total_png_bytes}) exceed max_png_bytes ({max_png_bytes})"
        )

    passed = len(errors) == 0
    return {
        "passed": passed,
        "ok": passed,
        "errors": errors,
        "packs": packs,
        "png_files": png_files,
        "manifest_sprites": manifest_sprite_count,
        "total_png_bytes": total_png_bytes,
    }


def _resolve_cases_js(root: str | Path, demo_rel: str | Path = DEFAULT_DEMO_REL) -> Path:
    r = Path(root)
    if r.is_file():
        return r
    demo_dir = _resolve_demo_dir(r, demo_rel)
    if (demo_dir / "cases.js").is_file():
        return demo_dir / "cases.js"
    if (r / "cases.js").is_file():
        return r / "cases.js"
    return demo_dir / "cases.js"


def _load_cases_from_js_file(cases_path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    raw_text = cases_path.read_text(encoding="utf-8")
    dashes = find_forbidden_dashes(raw_text)
    if dashes:
        errors.append(f"Forbidden dash characters {dashes} in {cases_path.name}")
    net_hits = _find_forbidden_js_network_calls(raw_text)
    if net_hits:
        errors.append(f"Forbidden offline network call {net_hits} in {cases_path.name}")

    payload = _extract_js_global_json(raw_text, ("OUTTHINK_DATA", "OUTTHINK_CASES"))
    if isinstance(payload, dict):
        cases = payload.get("cases")
    elif isinstance(payload, list):
        cases = payload
    else:
        cases = None

    if not isinstance(cases, list) or len(cases) == 0:
        raise ValueError("window.OUTTHINK_DATA must contain a non-empty 'cases' list")
    return cases, errors


def _iter_case_step_lists(case_obj: dict[str, Any]) -> list[tuple[str, list[Any]]]:
    lists: list[tuple[str, list[Any]]] = []
    for field in ("tool_steps", "steps"):
        val = case_obj.get(field)
        if isinstance(val, list):
            lists.append((field, val))
    ev = case_obj.get("evidence")
    if isinstance(ev, list):
        lists.append(("evidence", ev))
    elif isinstance(ev, dict):
        for sub in ("steps", "tool_steps"):
            sval = ev.get(sub)
            if isinstance(sval, list):
                lists.append((f"evidence.{sub}", sval))
    return lists


def _iter_case_thinking_entries(case_obj: dict[str, Any]) -> list[tuple[str | None, dict[str, Any]]]:
    entries: list[tuple[str | None, dict[str, Any]]] = []
    sources: list[Any] = []
    if case_obj.get("thinking_levels") is not None:
        sources.append(case_obj.get("thinking_levels"))
    reveal = case_obj.get("reveal")
    if isinstance(reveal, dict) and reveal.get("thinking_levels") is not None:
        if reveal.get("thinking_levels") is not case_obj.get("thinking_levels"):
            sources.append(reveal.get("thinking_levels"))

    for src in sources:
        if isinstance(src, dict):
            for k, v in src.items():
                if isinstance(v, dict):
                    entries.append((str(k), v))
        elif isinstance(src, list):
            for item in src:
                if isinstance(item, dict):
                    lk = item.get("level") or item.get("thinking_level") or item.get("key")
                    entries.append((str(lk) if lk is not None else None, item))
    return entries


def check_ladder_provenance(
    root: str | Path = ".",
    ground_truth: dict[str, Any] | None = None,
    *,
    demo_rel: str | Path = DEFAULT_DEMO_REL,
    cost_tol: float = 1e-3,
    score_tol: float = 1e-3,
) -> dict[str, Any]:
    cases_path = _resolve_cases_js(root, demo_rel)
    if not cases_path.is_file():
        return {
            "passed": False,
            "ok": False,
            "errors": [f"Missing cases.js at {cases_path}"],
            "cases_checked": 0,
            "runs_checked": 0,
        }

    gt = ground_truth if ground_truth is not None else load_ladder_ground_truth(root)
    by_run_id: dict[str, dict[str, Any]] = gt["by_run_id"]
    by_key: dict[tuple[str, str, str, int], dict[str, Any]] = gt["by_key"]

    errors: list[str] = []
    try:
        cases, file_errors = _load_cases_from_js_file(cases_path)
        errors.extend(file_errors)
    except (ValueError, json.JSONDecodeError) as exc:
        return {
            "passed": False,
            "ok": False,
            "errors": [f"Failed to parse {cases_path.name}: {exc}"],
            "cases_checked": 0,
            "runs_checked": 0,
        }

    cases_checked = 0
    runs_checked = 0

    for idx, case_obj in enumerate(cases):
        if not isinstance(case_obj, dict):
            errors.append(f"Case at index {idx} is not an object")
            continue
        cases_checked += 1
        case_id = str(case_obj.get("id") or f"case_{idx}")
        decision_day = case_obj.get("decision_day")

        for list_label, step_list in _iter_case_step_lists(case_obj):
            for s_idx, step in enumerate(step_list):
                if not isinstance(step, dict):
                    continue
                tool_name = str(step.get("tool") or "").strip().lower()
                action_name = str(step.get("action") or "").strip().lower()
                if tool_name == "accuse" or action_name == "accuse":
                    errors.append(
                        f"Case '{case_id}' pre-decision {list_label}[{s_idx}] leaks 'accuse' step"
                    )
                if isinstance(decision_day, int) and isinstance(step.get("day"), int):
                    if int(step["day"]) > decision_day:
                        errors.append(
                            f"Case '{case_id}' pre-decision {list_label}[{s_idx}] day {step['day']} > decision_day {decision_day}"
                        )

        tl_entries = _iter_case_thinking_entries(case_obj)
        if not tl_entries:
            errors.append(f"Case '{case_id}' has no thinking_levels provenance entries")
            continue

        for level_hint, entry in tl_entries:
            runs_checked += 1
            run_id_raw = entry.get("run_id")
            model = str(entry.get("model") or case_obj.get("model") or "gemini-4-carbon")
            level = str(
                entry.get("level")
                or entry.get("thinking_level")
                or entry.get("key")
                or level_hint
                or ""
            )
            tier = str(entry.get("tier") or case_obj.get("tier") or "")
            seed_raw = entry.get("seed") if entry.get("seed") is not None else case_obj.get("seed")

            gt_ep: dict[str, Any] | None = None
            if run_id_raw is not None and str(run_id_raw).strip() != "":
                rid = str(run_id_raw).strip()
                gt_ep = by_run_id.get(rid)
                if gt_ep is None:
                    errors.append(f"Case '{case_id}' level '{level}': unknown run_id '{rid}'")
                    continue
                if seed_raw is not None and int(seed_raw) != gt_ep["seed"]:
                    errors.append(
                        f"Case '{case_id}' run_id '{rid}' seed mismatch: {seed_raw} != {gt_ep['seed']}"
                    )
                if tier and tier != gt_ep["tier"]:
                    errors.append(
                        f"Case '{case_id}' run_id '{rid}' tier mismatch: {tier} != {gt_ep['tier']}"
                    )
            else:
                if seed_raw is None or not model or not level or not tier:
                    errors.append(
                        f"Case '{case_id}' level '{level}': missing run_id and incomplete (model, level, tier, seed)"
                    )
                    continue
                lookup_key = (model, level, tier, int(seed_raw))
                gt_ep = by_key.get(lookup_key)
                if gt_ep is None:
                    errors.append(
                        f"Case '{case_id}': no ladder ground truth for key {lookup_key}"
                    )
                    continue

            raw_acc = entry.get("accused")
            norm_acc = str(raw_acc) if raw_acc is not None and str(raw_acc) != "" else None
            if "accused" not in entry or norm_acc != gt_ep["accused"]:
                errors.append(
                    f"Case '{case_id}' ({gt_ep['run_id']}) accused mismatch: got {norm_acc!r}, expected {gt_ep['accused']!r}"
                )

            if "correct" not in entry or bool(entry["correct"]) != bool(gt_ep["correct"]):
                errors.append(
                    f"Case '{case_id}' ({gt_ep['run_id']}) correct mismatch: got {entry.get('correct')!r}, expected {gt_ep['correct']!r}"
                )

            if "score" not in entry or entry["score"] is None:
                errors.append(f"Case '{case_id}' ({gt_ep['run_id']}) missing score")
            else:
                got_score = float(entry["score"])
                exp_score = float(gt_ep["score"])
                if abs(got_score - exp_score) > score_tol:
                    errors.append(
                        f"Case '{case_id}' ({gt_ep['run_id']}) score {got_score} != {exp_score} (tol={score_tol})"
                    )

            if "cost_usd" not in entry or entry["cost_usd"] is None:
                errors.append(f"Case '{case_id}' ({gt_ep['run_id']}) missing cost_usd")
            else:
                got_cost = float(entry["cost_usd"])
                exp_cost = float(gt_ep["cost_usd"])
                if got_cost <= 0.0:
                    errors.append(
                        f"Case '{case_id}' ({gt_ep['run_id']}) non-positive cost_usd {got_cost}"
                    )
                elif abs(got_cost - exp_cost) > cost_tol:
                    errors.append(
                        f"Case '{case_id}' ({gt_ep['run_id']}) cost_usd {got_cost} != {exp_cost} (tol={cost_tol})"
                    )

    passed = len(errors) == 0
    return {
        "passed": passed,
        "ok": passed,
        "errors": errors,
        "cases_checked": cases_checked,
        "runs_checked": runs_checked,
    }


def verify_case_math(
    case_or_root: dict[str, Any] | list[dict[str, Any]] | str | Path = ".",
    *,
    demo_rel: str | Path = DEFAULT_DEMO_REL,
    tol: float = 1e-3,
) -> dict[str, Any]:
    errors: list[str] = []
    cases: list[dict[str, Any]] = []

    if isinstance(case_or_root, (str, Path)):
        cases_path = _resolve_cases_js(case_or_root, demo_rel)
        if not cases_path.is_file():
            return {
                "passed": False,
                "ok": False,
                "errors": [f"Missing cases.js at {cases_path}"],
                "cases_checked": 0,
            }
        try:
            cases, file_errs = _load_cases_from_js_file(cases_path)
            errors.extend(file_errs)
        except (ValueError, json.JSONDecodeError) as exc:
            return {
                "passed": False,
                "ok": False,
                "errors": [f"Failed to parse {cases_path.name}: {exc}"],
                "cases_checked": 0,
            }
    elif isinstance(case_or_root, dict):
        if isinstance(case_or_root.get("cases"), list):
            cases = list(case_or_root["cases"])
        else:
            cases = [case_or_root]
    elif isinstance(case_or_root, list):
        cases = list(case_or_root)
    else:
        return {
            "passed": False,
            "ok": False,
            "errors": ["Unsupported input type for verify_case_math"],
            "cases_checked": 0,
        }

    cases_checked = 0
    for idx, c in enumerate(cases):
        if not isinstance(c, dict):
            errors.append(f"Case at index {idx} is not a dict")
            continue
        cases_checked += 1
        cid = str(c.get("id") or f"case_{idx}")
        v_raw = c.get("value_at_decision")
        if v_raw is None:
            errors.append(f"Case '{cid}' missing value_at_decision")
            continue
        v = float(v_raw)
        if not (0.0 < v <= 1.0):
            errors.append(f"Case '{cid}' value_at_decision {v} outside (0, 1]")
            continue

        solver = c.get("solver")
        if not isinstance(solver, dict):
            errors.append(f"Case '{cid}' missing solver object")
            continue

        posterior = solver.get("posterior")
        top_prob_raw = solver.get("top_prob")
        top_suspect = solver.get("top_suspect")
        if top_prob_raw is None:
            errors.append(f"Case '{cid}' solver missing top_prob")
            continue
        top_prob = float(top_prob_raw)
        if not (0.0 <= top_prob <= 1.0):
            errors.append(f"Case '{cid}' solver top_prob {top_prob} outside [0, 1]")

        if isinstance(posterior, dict) and posterior:
            probs = [float(pv) for pv in posterior.values()]
            if any(pv < -1e-6 or pv > 1.0 + 1e-6 for pv in probs):
                errors.append(f"Case '{cid}' posterior has probability outside [0, 1]")
            prob_sum = sum(probs)
            if abs(prob_sum - 1.0) > max(tol, 1e-2):
                errors.append(f"Case '{cid}' posterior sum {prob_sum:.4f} != 1.0")
            max_post = max(probs)
            if abs(max_post - top_prob) > max(tol, 2e-3):
                errors.append(
                    f"Case '{cid}' top_prob {top_prob} != max(posterior) {max_post}"
                )
            if top_suspect is not None and str(top_suspect) in posterior:
                if abs(float(posterior[str(top_suspect)]) - max_post) > max(tol, 2e-3):
                    errors.append(
                        f"Case '{cid}' top_suspect '{top_suspect}' does not have maximum posterior"
                    )

        ev_hold = float(solver.get("ev_hold_fire") or 0.0)
        baseline = ev_hold if ev_hold > 0.0 else 0.0
        exp_be = min(1.0, max(0.0, (1.0 + baseline) / (1.0 + v)))
        pure_be = 1.0 / (1.0 + v)

        if "break_even_prob" not in solver or solver["break_even_prob"] is None:
            errors.append(f"Case '{cid}' solver missing break_even_prob")
        else:
            got_be = float(solver["break_even_prob"])
            if min(abs(got_be - exp_be), abs(got_be - pure_be)) > tol:
                errors.append(
                    f"Case '{cid}' break_even_prob {got_be} != expected {exp_be:.4f} (tol={tol})"
                )

        exp_ev_accuse = top_prob * v - (1.0 - top_prob)
        if "ev_accuse_top" in solver and solver["ev_accuse_top"] is not None:
            got_ev = float(solver["ev_accuse_top"])
            if abs(got_ev - exp_ev_accuse) > max(tol, 2e-3):
                errors.append(
                    f"Case '{cid}' ev_accuse_top {got_ev} != expected {exp_ev_accuse:.4f}"
                )

        rec_call = solver.get("recommended_call")
        be_ref = float(solver.get("break_even_prob", pure_be))
        if rec_call is not None:
            norm_call = str(rec_call).strip().lower()
            if norm_call not in ("accuse", "hold_fire"):
                errors.append(f"Case '{cid}' invalid recommended_call '{rec_call}'")
            elif top_prob > be_ref + max(tol, 5e-3) and baseline <= 0.0 and norm_call != "accuse":
                errors.append(
                    f"Case '{cid}' top_prob {top_prob} > break_even_prob {be_ref} but recommended_call='{rec_call}'"
                )
            elif top_prob < be_ref - max(tol, 5e-3) and norm_call != "hold_fire":
                errors.append(
                    f"Case '{cid}' top_prob {top_prob} < break_even_prob {be_ref} but recommended_call='{rec_call}'"
                )

    passed = len(errors) == 0
    return {
        "passed": passed,
        "ok": passed,
        "errors": errors,
        "cases_checked": cases_checked,
    }


def _find_js_runtime() -> tuple[list[str], dict[str, str]] | None:
    clean_env = {k: v for k, v in os.environ.items() if k not in API_KEY_ENV_VARS}
    clean_env["NO_PROXY"] = "*"
    clean_env["HTTP_PROXY"] = ""
    clean_env["HTTPS_PROXY"] = ""
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env
    opencode_candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
        "/root/momin/bin/opencode",
    ]
    for cand in opencode_candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    return None


def audit_js_engine(
    root: str | Path = ".",
    *,
    demo_rel: str | Path = DEFAULT_DEMO_REL,
) -> dict[str, Any]:
    r = Path(root)
    if r.is_file():
        engine_path = r
    else:
        demo_dir = _resolve_demo_dir(r, demo_rel)
        engine_path = demo_dir / "engine.js" if (demo_dir / "engine.js").is_file() else r / "engine.js"

    errors: list[str] = []
    if not engine_path.is_file():
        return {
            "passed": False,
            "ok": False,
            "errors": [f"Missing engine.js at {engine_path}"],
            "engine_path": str(engine_path),
            "runtime_executed": False,
        }

    src = engine_path.read_text(encoding="utf-8")
    dashes = find_forbidden_dashes(src)
    if dashes:
        errors.append(f"Forbidden dash characters {dashes} in {engine_path.name}")
    net_hits = _find_forbidden_js_network_calls(src)
    if net_hits:
        errors.append(f"Forbidden offline network call {net_hits} in {engine_path.name}")

    for fn_name in REQUIRED_ENGINE_EXPORTS:
        if fn_name not in src:
            errors.append(f"engine.js missing required export '{fn_name}'")

    runtime_executed = False
    rt = _find_js_runtime()
    if rt is not None and not errors:
        cmd_prefix, env = rt
        run_env = dict(env)
        run_env["OUTTHINK_QA_ENGINE"] = str(engine_path.resolve())
        probe_script = (
            "const E = require(process.env.OUTTHINK_QA_ENGINE);\n"
            "const be = E.computeBreakEvenProb(0.6);\n"
            "const ev = E.computeAccusationEv(0.8, 0.6);\n"
            "const sample = {\n"
            "  id: 'qa-1', tier: 'hard', seed: 1, decision_day: 5, decision_step: 20,\n"
            "  value_at_decision: 0.6, true_mole: 'e02',\n"
            "  suspects: [{id: 'e01', name: 'A'}, {id: 'e02', name: 'B'}],\n"
            "  solver: {top_suspect: 'e02', top_prob: 0.85, break_even_prob: 0.625, recommended_call: 'accuse'},\n"
            "  thinking_levels: [{level: 'low', accused: 'e01', correct: false, score: -1.0, cost_usd: 0.5},\n"
            "                    {level: 'high', accused: 'e02', correct: true, score: 0.6, cost_usd: 1.0}]\n"
            "};\n"
            "const ds = E.loadDataset({cases: [sample]});\n"
            "const c0 = ds.cases[0];\n"
            "const hit = E.evaluateCall(c0, {action: 'accuse', suspectId: 'e02'});\n"
            "const miss = E.evaluateCall(c0, {action: 'accuse', suspectId: 'e01'});\n"
            "const sb = E.createScoreboard();\n"
            "sb.record(c0.id, hit, c0);\n"
            "process.stdout.write(JSON.stringify({be, ev, hitScore: hit.score, hitCorrect: hit.correct, missScore: miss.score, missCorrect: miss.correct, played: sb.getSummary().casesPlayed}));\n"
        )
        try:
            proc = subprocess.run(
                [*cmd_prefix, probe_script],
                env=run_env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode != 0:
                errors.append(f"engine.js runtime execution failed: {proc.stderr.strip()}")
            else:
                runtime_executed = True
                res = json.loads(proc.stdout)
                if abs(float(res["be"]) - (1.0 / 1.6)) > 1e-4:
                    errors.append(f"computeBreakEvenProb(0.6) returned {res['be']}, expected 0.625")
                if abs(float(res["ev"]) - (0.8 * 0.6 - 0.2)) > 1e-4:
                    errors.append(f"computeAccusationEv(0.8, 0.6) returned {res['ev']}, expected 0.28")
                if not res["hitCorrect"] or abs(float(res["hitScore"]) - 0.6) > 1e-4:
                    errors.append(f"evaluateCall correct accusation mismatch: {res}")
                if res["missCorrect"] or abs(float(res["missScore"]) - (-1.0)) > 1e-4:
                    errors.append(f"evaluateCall wrong accusation penalty mismatch: {res}")
                if int(res["played"]) != 1:
                    errors.append(f"createScoreboard casesPlayed={res['played']}, expected 1")
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            errors.append(f"engine.js runtime probe error: {exc}")

    passed = len(errors) == 0
    return {
        "passed": passed,
        "ok": passed,
        "errors": errors,
        "engine_path": str(engine_path),
        "runtime_executed": runtime_executed,
    }


def _skipped_check(reason: str) -> dict[str, Any]:
    return {"passed": True, "ok": True, "skipped": True, "reason": reason, "errors": []}


def audit_outthink_bundle(
    root: str | Path = ".",
    *,
    demo_rel: str | Path = DEFAULT_DEMO_REL,
    assets_doc_rel: str | Path = DEFAULT_ASSETS_DOC_REL,
    strict: bool = True,
) -> dict[str, Any]:
    root_path = Path(root)
    demo_dir = _resolve_demo_dir(root_path, demo_rel)
    assets_doc = root_path / assets_doc_rel
    if not assets_doc.is_file() and (root_path / "ASSETS.md").is_file():
        assets_doc = root_path / "ASSETS.md"
    assets_dir = demo_dir / "assets"
    index_path = demo_dir / "index.html"
    cases_path = demo_dir / "cases.js"
    engine_path = demo_dir / "engine.js"

    errors: list[str] = []
    checks: dict[str, Any] = {}
    gt_count = 0
    gt: dict[str, Any] | None = None

    try:
        gt = load_ladder_ground_truth(root_path)
        gt_count = len(gt["episodes"])
        gt_errors: list[str] = []
        if gt_count < MIN_LADDER_EPISODES:
            gt_errors.append(
                f"Expected >= {MIN_LADDER_EPISODES} ladder ground-truth episodes, got {gt_count}"
            )
        zero_cost = [ep["run_id"] for ep in gt["episodes"] if float(ep["cost_usd"]) <= 0.0]
        if zero_cost:
            gt_errors.append(
                f"{len(zero_cost)} ladder ground-truth episodes have non-positive cost_usd"
            )
        checks["ground_truth"] = {
            "passed": len(gt_errors) == 0,
            "ok": len(gt_errors) == 0,
            "errors": gt_errors,
            "episodes": gt_count,
        }
        errors.extend(gt_errors)
    except Exception as exc:
        msg = f"Ground-truth load failed: {exc}"
        checks["ground_truth"] = {"passed": False, "ok": False, "errors": [msg], "episodes": 0}
        errors.append(msg)

    if strict or index_path.is_file():
        res_static = check_static_page(root_path, demo_rel=demo_rel)
        checks["static_page"] = res_static
        errors.extend(res_static["errors"])
    else:
        checks["static_page"] = _skipped_check("index.html not present")

    if strict or assets_doc.is_file() or assets_dir.is_dir():
        res_assets = check_assets_and_licenses(
            root_path, demo_rel=demo_rel, assets_doc_rel=assets_doc_rel
        )
        checks["assets"] = res_assets
        errors.extend(res_assets["errors"])
    else:
        checks["assets"] = _skipped_check("ASSETS.md and assets/ not present")

    if strict or cases_path.is_file():
        if gt is not None:
            res_prov = check_ladder_provenance(root_path, gt, demo_rel=demo_rel)
        else:
            res_prov = {
                "passed": False,
                "ok": False,
                "errors": ["Cannot verify cases.js provenance without ladder ground truth"],
                "cases_checked": 0,
                "runs_checked": 0,
            }
        checks["provenance"] = res_prov
        errors.extend(res_prov["errors"])

        res_math = verify_case_math(root_path, demo_rel=demo_rel)
        checks["case_math"] = res_math
        errors.extend(res_math["errors"])
    else:
        checks["provenance"] = _skipped_check("cases.js not present")
        checks["case_math"] = _skipped_check("cases.js not present")

    if strict or engine_path.is_file():
        res_engine = audit_js_engine(root_path, demo_rel=demo_rel)
        checks["js_engine"] = res_engine
        errors.extend(res_engine["errors"])
    else:
        checks["js_engine"] = _skipped_check("engine.js not present")

    passed = len(errors) == 0
    return {
        "passed": passed,
        "ok": passed,
        "errors": errors,
        "checks": checks,
        "ground_truth_episodes": gt_count,
    }


def run_outthink_qa(
    root: str | Path = ".",
    *,
    strict: bool = False,
) -> dict[str, Any]:
    return audit_outthink_bundle(root, strict=strict)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline QA and provenance verifier for Out-Think Gemini"
    )
    parser.add_argument("--root", default=".", help="Repository root directory")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when optional demo bundle files are not yet present on disk",
    )
    args = parser.parse_args(argv)
    report = run_outthink_qa(args.root, strict=args.strict)
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "ground_truth_episodes": report["ground_truth_episodes"],
                "errors": report["errors"],
            },
            indent=2,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
