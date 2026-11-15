from __future__ import annotations

import ast
import base64
import io
import json
import os
from pathlib import Path
import re
import struct
import tokenize
import warnings
import zlib

import pytest

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None


ROOT = Path(__file__).resolve().parents[1]
LIVE_ASSETS_MD = ROOT / "docs" / "demo" / "ASSETS.md"
LIVE_DEMO_DIR = ROOT / "demo" / "out-think-gemini"
LIVE_ASSETS_DIR = LIVE_DEMO_DIR / "assets"
LIVE_MANIFEST_JS = LIVE_ASSETS_DIR / "manifest.js"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
DATA_URI_PREFIX = "data:image/png;base64,"
HARD_MAX_ASSETS_BYTES = 15 * 1024 * 1024
SOFT_WARN_ASSETS_BYTES = 2 * 1024 * 1024

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)

REQUIRED_SPRITE_KEYS: tuple[str, ...] = (
    "detective",
    "suspect_0",
    "suspect_1",
    "suspect_2",
    "suspect_3",
    "suspect_4",
    "suspect_5",
    "suspect_6",
    "suspect_7",
    "agent_minimal",
    "agent_low",
    "agent_medium",
    "agent_high",
    "agent_xhigh",
    "pod_locked",
    "pod_unlocked",
    "floor_tile",
    "wall_tile",
    "desk",
    "chair",
    "evidence_board",
    "filing_cabinet",
    "terminal",
    "server_rack",
    "icon_memo",
    "icon_log",
    "icon_chat",
    "icon_badge",
    "icon_magnifier",
    "icon_accuse",
    "icon_correct",
    "icon_wrong",
    "icon_coin",
    "icon_brain",
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
    "rpg maker",
    "rpgmaker",
)

CONTEXT_FORBIDDEN_ASSET_TERMS: tuple[str, ...] = (
    "paid",
    "ripped",
    "itch.io",
    "proprietary",
    "non-commercial",
    "noncommercial",
)

OGA_URL_RE = re.compile(r"https://opengameart\.org/[A-Za-z0-9._~:/?\[\]@!$&'()*+,;=%-]+")
ANY_HTTP_URL_RE = re.compile(r"https?://[^\s)>`\"']+")
PLACEHOLDER_AUTHORS = frozenset({"", "-", "n/a", "na", "none", "unknown", "tbd", "todo", "null"})


def _png_chunk(chunk_type: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + chunk_type + payload + struct.pack(">I", crc)


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def encode_rgba_png(
    width: int,
    height: int,
    pixels: list[tuple[int, int, int, int]],
    filter_type: int = 0,
) -> bytes:
    assert width > 0 and height > 0
    assert len(pixels) == width * height
    assert filter_type in (0, 1, 2, 3, 4)

    bpp = 4
    stride = width * bpp
    prev_row = bytes(stride)
    raw_scanlines = bytearray()

    for y in range(height):
        row = bytearray(stride)
        row_offset = y * width
        for x in range(width):
            r, g, b, a = pixels[row_offset + x]
            idx = x * 4
            row[idx] = r & 0xFF
            row[idx + 1] = g & 0xFF
            row[idx + 2] = b & 0xFF
            row[idx + 3] = a & 0xFF

        raw_scanlines.append(filter_type)
        if filter_type == 0:
            raw_scanlines.extend(row)
        elif filter_type == 1:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                raw_scanlines.append((row[i] - left) & 0xFF)
        elif filter_type == 2:
            for i in range(stride):
                raw_scanlines.append((row[i] - prev_row[i]) & 0xFF)
        elif filter_type == 3:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                raw_scanlines.append((row[i] - ((left + prev_row[i]) >> 1)) & 0xFF)
        elif filter_type == 4:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                raw_scanlines.append((row[i] - _paeth_predictor(left, up, up_left)) & 0xFF)

        prev_row = bytes(row)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw_scanlines), level=9)
    return PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def parse_png_structure(raw: bytes) -> dict[str, object]:
    assert isinstance(raw, (bytes, bytearray)), "PNG data must be bytes"
    assert len(raw) >= 33, f"PNG file too short ({len(raw)} bytes)"
    assert raw[:8] == PNG_SIGNATURE, "Invalid PNG 8-byte signature"

    offset = 8
    ihdr_info: dict[str, int] | None = None
    idat_parts: list[bytes] = []
    plte_bytes: bytes | None = None
    trns_bytes: bytes | None = None
    saw_iend = False

    while offset < len(raw):
        assert offset + 12 <= len(raw), "Truncated PNG chunk header"
        length, chunk_type = struct.unpack(">I4s", raw[offset : offset + 8])
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        assert crc_end <= len(raw), f"Truncated PNG chunk {chunk_type!r}"

        chunk_data = raw[data_start:data_end]
        (expected_crc,) = struct.unpack(">I", raw[data_end:crc_end])
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        assert actual_crc == expected_crc, f"CRC mismatch in PNG chunk {chunk_type!r}"

        if ihdr_info is None:
            assert chunk_type == b"IHDR", f"First PNG chunk must be IHDR, got {chunk_type!r}"
            assert length == 13, f"IHDR chunk must be 13 bytes, got {length}"
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", chunk_data
            )
            assert width > 0 and height > 0, f"Invalid PNG dimensions {(width, height)}"
            assert compression == 0 and filter_method == 0, "Invalid PNG compression/filter method"
            assert interlace in (0, 1), f"Invalid PNG interlace method {interlace}"
            ihdr_info = {
                "width": width,
                "height": height,
                "bit_depth": bit_depth,
                "color_type": color_type,
                "interlace": interlace,
            }
        elif chunk_type == b"PLTE":
            assert len(chunk_data) % 3 == 0 and 3 <= len(chunk_data) <= 768, "Invalid PLTE chunk length"
            plte_bytes = bytes(chunk_data)
        elif chunk_type == b"tRNS":
            trns_bytes = bytes(chunk_data)
        elif chunk_type == b"IDAT":
            idat_parts.append(bytes(chunk_data))
        elif chunk_type == b"IEND":
            assert length == 0, "IEND chunk must have 0-byte payload"
            saw_iend = True
            offset = crc_end
            break

        offset = crc_end

    assert ihdr_info is not None, "Missing IHDR chunk"
    assert idat_parts, "PNG has zero IDAT chunks"
    assert saw_iend, "PNG missing IEND chunk"
    assert offset == len(raw), f"Trailing bytes after PNG IEND ({len(raw) - offset} bytes)"

    return {
        **ihdr_info,
        "idat": b"".join(idat_parts),
        "plte": plte_bytes,
        "trns": trns_bytes,
    }


def _unpack_packed_samples(row_bytes: bytes, width: int, bit_depth: int) -> list[int]:
    if bit_depth == 8:
        return list(row_bytes[:width])
    samples: list[int] = []
    mask = (1 << bit_depth) - 1
    per_byte = 8 // bit_depth
    for byte_val in row_bytes:
        for shift_idx in range(per_byte):
            shift = 8 - bit_depth * (shift_idx + 1)
            samples.append((byte_val >> shift) & mask)
            if len(samples) == width:
                return samples
    return samples


def decode_png_rgba_zlib(raw: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    info = parse_png_structure(raw)
    width = int(info["width"])
    height = int(info["height"])
    bit_depth = int(info["bit_depth"])
    color_type = int(info["color_type"])
    interlace = int(info["interlace"])
    assert interlace == 0, "Interlaced PNG requires PIL decoder fallback"
    assert bit_depth in (1, 2, 4, 8), f"Unsupported bit depth {bit_depth} for stdlib decoder"

    channels_map = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
    assert color_type in channels_map, f"Unsupported PNG color_type {color_type}"
    channels = channels_map[color_type]
    if color_type in (2, 4, 6):
        assert bit_depth == 8, f"Expected 8-bit samples for color_type {color_type}"

    bits_per_pixel = channels * bit_depth
    bpp = max(1, (bits_per_pixel + 7) // 8)
    row_bytes_len = (width * bits_per_pixel + 7) // 8

    decompressed = zlib.decompress(bytes(info["idat"]))
    expected_len = height * (1 + row_bytes_len)
    assert len(decompressed) == expected_len, (
        f"Decompressed IDAT length {len(decompressed)} != expected {expected_len}"
    )

    plte_raw = info["plte"]
    trns_raw = info["trns"]
    palette: list[tuple[int, int, int, int]] = []
    if color_type == 3:
        assert isinstance(plte_raw, bytes), "Indexed PNG missing PLTE chunk"
        n_entries = len(plte_raw) // 3
        for idx in range(n_entries):
            r = plte_raw[idx * 3]
            g = plte_raw[idx * 3 + 1]
            b = plte_raw[idx * 3 + 2]
            a = trns_raw[idx] if isinstance(trns_raw, bytes) and idx < len(trns_raw) else 255
            palette.append((r, g, b, a))

    prev_row = bytearray(row_bytes_len)
    pixels: list[tuple[int, int, int, int]] = []
    pos = 0
    max_sample = (1 << bit_depth) - 1

    for _ in range(height):
        ftype = decompressed[pos]
        filt = decompressed[pos + 1 : pos + 1 + row_bytes_len]
        pos += 1 + row_bytes_len
        recon = bytearray(row_bytes_len)

        if ftype == 0:
            recon[:] = filt
        elif ftype == 1:
            for i in range(row_bytes_len):
                left = recon[i - bpp] if i >= bpp else 0
                recon[i] = (filt[i] + left) & 0xFF
        elif ftype == 2:
            for i in range(row_bytes_len):
                recon[i] = (filt[i] + prev_row[i]) & 0xFF
        elif ftype == 3:
            for i in range(row_bytes_len):
                left = recon[i - bpp] if i >= bpp else 0
                recon[i] = (filt[i] + ((left + prev_row[i]) >> 1)) & 0xFF
        elif ftype == 4:
            for i in range(row_bytes_len):
                left = recon[i - bpp] if i >= bpp else 0
                up = prev_row[i]
                up_left = prev_row[i - bpp] if i >= bpp else 0
                recon[i] = (filt[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        else:
            raise AssertionError(f"Invalid PNG scanline filter type {ftype}")

        prev_row = recon

        if color_type == 6:
            for x in range(width):
                base = x * 4
                pixels.append((recon[base], recon[base + 1], recon[base + 2], recon[base + 3]))
        elif color_type == 2:
            trns_rgb: tuple[int, int, int] | None = None
            if isinstance(trns_raw, bytes) and len(trns_raw) == 6:
                trns_rgb = (trns_raw[1], trns_raw[3], trns_raw[5])
            for x in range(width):
                base = x * 3
                rgb = (recon[base], recon[base + 1], recon[base + 2])
                alpha = 0 if trns_rgb is not None and rgb == trns_rgb else 255
                pixels.append((rgb[0], rgb[1], rgb[2], alpha))
        elif color_type == 3:
            indices = _unpack_packed_samples(bytes(recon), width, bit_depth)
            for idx in indices:
                assert 0 <= idx < len(palette), f"Palette index {idx} out of range {len(palette)}"
                pixels.append(palette[idx])
        elif color_type == 0:
            samples = _unpack_packed_samples(bytes(recon), width, bit_depth)
            trns_gray = struct.unpack(">H", trns_raw)[0] if isinstance(trns_raw, bytes) and len(trns_raw) == 2 else None
            for s in samples:
                lum = (s * 255) // max_sample
                alpha = 0 if trns_gray is not None and s == trns_gray else 255
                pixels.append((lum, lum, lum, alpha))
        elif color_type == 4:
            for x in range(width):
                lum = recon[x * 2]
                alpha = recon[x * 2 + 1]
                pixels.append((lum, lum, lum, alpha))

    return width, height, pixels


def _pil_rgba_pixels(raw: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    assert _PILImage is not None
    with _PILImage.open(io.BytesIO(raw)) as img:
        rgba = img.convert("RGBA")
        w, h = rgba.size
        buf = rgba.tobytes()
        pixels = [(buf[i], buf[i + 1], buf[i + 2], buf[i + 3]) for i in range(0, len(buf), 4)]
        return w, h, pixels


def decode_png_rgba(raw: bytes) -> tuple[int, int, list[tuple[int, int, int, int]]]:
    info = parse_png_structure(raw)
    width = int(info["width"])
    height = int(info["height"])
    if info["interlace"] == 0 and info["bit_depth"] in (1, 2, 4, 8):
        return decode_png_rgba_zlib(raw)
    if _PILImage is not None:
        pil_w, pil_h, pil_pixels = _pil_rgba_pixels(raw)
        assert (pil_w, pil_h) == (width, height)
        return width, height, pil_pixels
    raise AssertionError("Unsupported interlaced/16-bit PNG without PIL installed")


def assert_region_has_nonblank_pixels(
    pixels: list[tuple[int, int, int, int]],
    img_width: int,
    img_height: int,
    rx: int,
    ry: int,
    rw: int,
    rh: int,
    label: str,
) -> None:
    assert 0 <= rx and 0 <= ry and rw > 0 and rh > 0, f"{label}: invalid crop {(rx, ry, rw, rh)}"
    assert rx + rw <= img_width and ry + rh <= img_height, (
        f"{label}: crop {(rx, ry, rw, rh)} exceeds PNG {(img_width, img_height)}"
    )

    norm_pixels: list[tuple[int, int, int, int]] = []
    visible_count = 0
    for dy in range(rh):
        row_start = (ry + dy) * img_width + rx
        for dx in range(rw):
            r, g, b, a = pixels[row_start + dx]
            if a == 0:
                norm_pixels.append((0, 0, 0, 0))
            else:
                norm_pixels.append((r, g, b, a))
                visible_count += 1

    assert visible_count > 0, f"{label}: 100% transparent blank sprite crop"
    distinct_pixels = set(norm_pixels)
    assert len(distinct_pixels) >= 2, (
        f"{label}: 100% uniform single solid pixel {next(iter(distinct_pixels))} (empty tile crop)"
    )


def _clean_md_cell(cell: str) -> str:
    cleaned = cell.strip()
    cleaned = re.sub(r"^`+|`+$", "", cleaned).strip()
    cleaned = re.sub(r"^\*\*+|\*\*+$", "", cleaned).strip()
    return cleaned


def _validate_pack_license_and_credit(license_text: str, author: str, credit_context: str, label: str) -> None:
    lic_clean = _clean_md_cell(license_text)
    assert lic_clean, f"{label}: missing license"
    lic_lower = lic_clean.lower()

    assert not re.search(r"\b(?:nc|nd|non-?commercial|no-?derivatives)\b", lic_lower), (
        f"{label}: restricted license {lic_clean!r} is forbidden"
    )

    is_cc0 = bool(re.search(r"\bcc0(?:\b|[- ]1\.0)", lic_lower))
    is_cc_by = bool(re.search(r"\bcc[- ]by(?:[- ]sa)?(?:\b|[- ]\d)", lic_lower))
    assert is_cc0 or is_cc_by, f"{label}: license must be CC0 or CC-BY, got {lic_clean!r}"

    if is_cc_by and not is_cc0:
        ctx_lower = credit_context.lower()
        has_explicit_credit = bool(
            re.search(r"\b(?:credit|attribution|credited|attributed)\b", ctx_lower)
            and author.lower() in ctx_lower
        )
        assert has_explicit_credit, (
            f"{label}: CC-BY pack must include explicit credit naming author {author!r}"
        )


def _assert_no_forbidden_keywords_in_pack(text: str, label: str) -> None:
    lower = text.lower()
    for term in HARD_FORBIDDEN_ASSET_TERMS:
        assert term not in lower, f"{label}: forbidden keyword {term!r} found"
    for term in CONTEXT_FORBIDDEN_ASSET_TERMS:
        pattern = r"\b" + re.escape(term) + r"\b"
        assert not re.search(pattern, lower), f"{label}: forbidden paid/ripped keyword {term!r} found"


def _assert_no_forbidden_keywords_in_document(md_text: str) -> None:
    lower_doc = md_text.lower()
    for term in HARD_FORBIDDEN_ASSET_TERMS:
        assert term not in lower_doc, f"ASSETS.md contains forbidden keyword {term!r}"

    for raw_line in md_text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("|"):
            continue
        for clause in re.split(r"[.!?;]+", stripped):
            clause_lower = clause.lower()
            for term in CONTEXT_FORBIDDEN_ASSET_TERMS:
                match = re.search(r"\b" + re.escape(term) + r"\b", clause_lower)
                if match:
                    prefix = clause_lower[: match.start()]
                    negated = bool(re.search(r"\b(?:zero|no|not|never|without|0)\b", prefix))
                    assert negated, f"ASSETS.md contains forbidden paid/ripped keyword {term!r} in {clause.strip()!r}"


def _parse_markdown_tables(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    tables: list[tuple[list[str], list[list[str]]]] = []
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
                rows: list[list[str]] = []
                for row_line in block[2:]:
                    if re.match(r"^\|[\s:|-]+\|$", row_line):
                        continue
                    cells = [c.strip() for c in row_line.strip("|").split("|")]
                    rows.append(cells)
                tables.append((headers, rows))
        else:
            idx += 1
    return tables


def _find_col(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for cand in candidates:
        for i, h in enumerate(headers):
            if h == cand or cand in h:
                return i
    return None


def parse_assets_md_packs(md_text: str) -> list[dict[str, str]]:
    packs: list[dict[str, str]] = []

    for headers, rows in _parse_markdown_tables(md_text):
        author_col = _find_col(headers, ("author", "creator", "artist"))
        license_col = _find_col(headers, ("license", "licence"))
        url_col = _find_col(headers, ("source url", "page url", "direct page url", "url", "source", "link"))
        if author_col is None or license_col is None or url_col is None:
            continue

        name_col = _find_col(headers, ("pack name", "pack", "name", "title", "pack id", "asset"))
        credit_col = _find_col(headers, ("attribution", "credit", "notes"))

        for row_idx, cells in enumerate(rows):
            max_needed = max(c for c in (author_col, license_col, url_col) if c is not None)
            assert len(cells) > max_needed, f"Malformed pack table row {row_idx + 1}: {cells!r}"
            name_val = _clean_md_cell(cells[name_col]) if name_col is not None and name_col < len(cells) else f"row_{row_idx + 1}"
            author_val = _clean_md_cell(cells[author_col])
            license_val = _clean_md_cell(cells[license_col])
            url_cell = cells[url_col]
            credit_val = cells[credit_col] if credit_col is not None and credit_col < len(cells) else ""
            raw_row = " | ".join(cells)
            packs.append(
                {
                    "name": name_val or f"row_{row_idx + 1}",
                    "author": author_val,
                    "license": license_val,
                    "url_field": url_cell,
                    "credit_context": f"{license_val} {credit_val}".strip(),
                    "raw": raw_row,
                }
            )

    heading_prefix = chr(35) * 2
    section_re = re.compile(rf"(?m)^({re.escape(heading_prefix)}{chr(35)}?)\s+(.+)$")
    matches = list(section_re.finditer(md_text))
    for m_idx, match in enumerate(matches):
        title = _clean_md_cell(match.group(2))
        start = match.end()
        end = matches[m_idx + 1].start() if m_idx + 1 < len(matches) else len(md_text)
        body = md_text[start:end]

        kv: dict[str, str] = {}
        for line in body.splitlines():
            sline = line.strip()
            bullet_match = re.match(r"^[-*]\s+\*\*([^*:]+):?\*\*:?\s*(.*)$", sline)
            if not bullet_match:
                bullet_match = re.match(r"^[-*]\s+([A-Za-z][A-Za-z0-9 /_-]{1,30}):\s*(.*)$", sline)
            if bullet_match:
                key = bullet_match.group(1).strip().lower()
                val = bullet_match.group(2).strip()
                kv[key] = val

        author_keys = ("author", "creator", "artist")
        license_keys = ("license", "licence")
        url_keys = ("direct page url", "page url", "source url", "url", "source", "link")
        credit_keys = ("attribution", "credit", "credits")

        has_author_key = any(k in kv for k in author_keys)
        has_license_key = any(k in kv for k in license_keys)
        has_url_key = any(k in kv for k in url_keys)

        is_pack_section = (has_author_key and (has_license_key or has_url_key)) or (
            not packs and (has_author_key or has_license_key or has_url_key)
        )
        if not is_pack_section:
            continue

        author_val = next((_clean_md_cell(kv[k]) for k in author_keys if k in kv), "")
        license_val = next((_clean_md_cell(kv[k]) for k in license_keys if k in kv), "")
        url_val = next((kv[k] for k in url_keys if k in kv), "")
        credit_val = next((kv[k] for k in credit_keys if k in kv), "")
        packs.append(
            {
                "name": title,
                "author": author_val,
                "license": license_val,
                "url_field": url_val,
                "credit_context": f"{license_val} {credit_val}".strip(),
                "raw": body,
            }
        )

    return packs


def validate_assets_md(md_text: str) -> list[dict[str, str]]:
    assert isinstance(md_text, str) and md_text.strip(), "ASSETS.md is empty"
    assert EM_DASH not in md_text, "ASSETS.md contains forbidden em dash"
    assert EN_DASH not in md_text, "ASSETS.md contains forbidden en dash"
    lower = md_text.lower()
    assert "&mdash;" not in lower and "&ndash;" not in lower, "ASSETS.md contains HTML em/en dash entity"

    _assert_no_forbidden_keywords_in_document(md_text)

    packs = parse_assets_md_packs(md_text)
    assert len(packs) >= 1, "ASSETS.md must specify >= 1 pack entries"

    for pack in packs:
        label = f"ASSETS.md pack {pack['name']!r}"
        _assert_no_forbidden_keywords_in_pack(pack["raw"], label)

        author = pack["author"].strip()
        assert author and author.lower() not in PLACEHOLDER_AUTHORS, f"{label}: missing or placeholder Author"

        oga_urls = OGA_URL_RE.findall(pack["url_field"])
        assert oga_urls, f"{label}: missing https://opengameart.org/... URL in {pack['url_field']!r}"
        for oga_url in oga_urls:
            path_part = oga_url[len("https://opengameart.org/") :].strip("/")
            assert path_part, f"{label}: bare https://opengameart.org/ URL without pack path"

        for any_url in ANY_HTTP_URL_RE.findall(pack["raw"]):
            clean_url = any_url.rstrip(".,;:)")
            allowed_url = clean_url.startswith("https://opengameart.org/") or clean_url.startswith(
                "https://creativecommons.org/"
            )
            assert allowed_url, f"{label}: non-OpenGameArt URL {clean_url!r} is not permitted"

        _validate_pack_license_and_credit(pack["license"], author, pack["credit_context"], label)

    return packs


def _strip_js_comments_and_trailing_commas(js_src: str) -> str:
    out: list[str] = []
    i = 0
    n = len(js_src)
    in_str: str | None = None

    while i < n:
        ch = js_src[i]
        if in_str is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(js_src[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue

        if ch in ('"', "'"):
            in_str = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and i + 1 < n and js_src[i + 1] == "/":
            i += 2
            while i < n and js_src[i] != "\n":
                i += 1
            continue

        if ch == "/" and i + 1 < n and js_src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (js_src[i] == "*" and js_src[i + 1] == "/"):
                i += 1
            i += 2
            continue

        out.append(ch)
        i += 1

    no_comments = "".join(out)
    cleaned: list[str] = []
    i = 0
    m = len(no_comments)
    in_str = None
    while i < m:
        ch = no_comments[i]
        if in_str is not None:
            cleaned.append(ch)
            if ch == "\\" and i + 1 < m:
                cleaned.append(no_comments[i + 1])
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            cleaned.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < m and no_comments[j] in " \t\r\n":
                j += 1
            if j < m and no_comments[j] in "}]":
                i += 1
                continue
        cleaned.append(ch)
        i += 1

    return "".join(cleaned)


def _extract_balanced_brace_object(text: str, start_pos: int) -> str:
    brace_start = text.find("{", start_pos)
    assert brace_start != -1, "Could not locate opening '{' for window.OUTTHINK_ASSETS"
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

    raise AssertionError("Unbalanced braces in window.OUTTHINK_ASSETS manifest.js")


def parse_window_outthink_assets(manifest_js: str) -> dict[str, object]:
    assert isinstance(manifest_js, str) and manifest_js.strip(), "manifest.js is empty"
    assert EM_DASH not in manifest_js and EN_DASH not in manifest_js, "manifest.js contains em/en dash"
    assert "OUTTHINK_ASSETS" in manifest_js and "window" in manifest_js, (
        "manifest.js must assign window.OUTTHINK_ASSETS"
    )

    cleaned = _strip_js_comments_and_trailing_commas(manifest_js)
    assign_match = re.search(
        r"(?:window\.OUTTHINK_ASSETS|window\[['\"]OUTTHINK_ASSETS['\"]\]|\.OUTTHINK_ASSETS)\s*=\s*(?:Object\.freeze\(\s*)?\{",
        cleaned,
    )
    if assign_match is not None:
        obj_str = _extract_balanced_brace_object(cleaned, assign_match.start())
    else:
        decl_match = re.search(
            r"\b(?:const|let|var)\s+OUTTHINK_ASSETS\s*=\s*(?:Object\.freeze\(\s*)?\{",
            cleaned,
        )
        assert decl_match is not None, "Could not find window.OUTTHINK_ASSETS object literal in manifest.js"
        assert re.search(r"OUTTHINK_ASSETS\s*=\s*OUTTHINK_ASSETS\b", cleaned), (
            "OUTTHINK_ASSETS constant declared but never assigned to window.OUTTHINK_ASSETS"
        )
        obj_str = _extract_balanced_brace_object(cleaned, decl_match.start())

    parsed = json.loads(obj_str)
    assert isinstance(parsed, dict), "window.OUTTHINK_ASSETS must be a JSON object"
    return parsed


def _is_strict_int(val: object) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def validate_outthink_manifest_and_assets(
    demo_dir: Path,
    *,
    hard_max_bytes: int = HARD_MAX_ASSETS_BYTES,
    soft_warn_bytes: int = SOFT_WARN_ASSETS_BYTES,
) -> dict[str, object]:
    demo_root = demo_dir.resolve()
    assets_dir = demo_root / "assets"
    manifest_path = assets_dir / "manifest.js"

    assert demo_root.is_dir(), f"Missing demo directory: {demo_root}"
    assert assets_dir.is_dir(), f"Missing assets directory: {assets_dir}"
    assert manifest_path.is_file(), f"Missing manifest.js: {manifest_path}"

    manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))

    packs_raw = manifest.get("packs")
    assert isinstance(packs_raw, (list, dict)) and len(packs_raw) >= 1, (
        "window.OUTTHINK_ASSETS.packs must be a non-empty list or object"
    )
    if isinstance(packs_raw, dict):
        pack_entries = []
        for k, v in packs_raw.items():
            assert isinstance(k, str) and k.strip() and isinstance(v, dict), f"Invalid pack entry {k!r}"
            pack_entries.append({**v, "_key": k})
    else:
        pack_entries = []
        for idx, v in enumerate(packs_raw):
            assert isinstance(v, dict), f"Invalid pack entry at index {idx}"
            pack_entries.append(v)

    known_pack_ids: set[str] = set()
    for idx, p in enumerate(pack_entries):
        plabel = f"manifest.packs[{p.get('id') or p.get('_key') or p.get('name') or idx}]"
        author = str(p.get("author") or p.get("creator") or "").strip()
        assert author and author.lower() not in PLACEHOLDER_AUTHORS, f"{plabel}: missing author"
        url = str(
            p.get("url")
            or p.get("sourceUrl")
            or p.get("pageUrl")
            or p.get("directPageUrl")
            or p.get("ogaUrl")
            or p.get("downloadUrl")
            or p.get("source")
            or ""
        ).strip()
        assert OGA_URL_RE.fullmatch(url), f"{plabel}: invalid OpenGameArt URL {url!r}"
        assert url[len("https://opengameart.org/") :].strip("/"), f"{plabel}: missing URL path"
        lic = str(p.get("license") or "").strip()
        credit = f"{lic} {p.get('attribution', '')} {p.get('credit', '')}".strip()
        _validate_pack_license_and_credit(lic, author, credit, plabel)
        _assert_no_forbidden_keywords_in_pack(json.dumps(p), plabel)
        for id_field in ("id", "_key", "name"):
            if isinstance(p.get(id_field), str) and p[id_field].strip():
                known_pack_ids.add(p[id_field].strip())

    sprites = manifest.get("sprites")
    assert isinstance(sprites, dict) and len(sprites) > 0, "window.OUTTHINK_ASSETS.sprites must be a non-empty object"

    missing_keys = sorted(set(REQUIRED_SPRITE_KEYS) - set(sprites.keys()))
    assert not missing_keys, f"Missing required sprite keys in manifest.js: {missing_keys}"

    sheets = manifest.get("sheets") if isinstance(manifest.get("sheets"), dict) else {}
    png_cache: dict[Path, tuple[bytes, int, int, list[tuple[int, int, int, int]]]] = {}

    for sprite_key, sprite in sprites.items():
        slabel = f"sprites[{sprite_key!r}]"
        assert isinstance(sprite, dict), f"{slabel}: entry must be an object"

        sheet_obj = sheets.get(sprite.get("sheet")) if isinstance(sprite.get("sheet"), str) else None
        raw_path = sprite.get("path") or (sheet_obj.get("path") if isinstance(sheet_obj, dict) else None)
        assert isinstance(raw_path, str) and raw_path.strip(), f"{slabel}: missing 'path'"
        assert not raw_path.startswith(("/", "\\")) and "://" not in raw_path, (
            f"{slabel}: path {raw_path!r} must be relative inside demo/out-think-gemini/"
        )

        rel_str = (
            raw_path[len("demo/out-think-gemini/") :]
            if raw_path.startswith("demo/out-think-gemini/")
            else raw_path
        )
        png_path = (demo_root / rel_str).resolve()
        assert png_path.is_relative_to(demo_root), (
            f"{slabel}: path {raw_path!r} escapes demo/out-think-gemini/"
        )
        if not png_path.is_file():
            alt_png_path = (assets_dir / rel_str).resolve()
            if alt_png_path.is_relative_to(demo_root) and alt_png_path.is_file():
                png_path = alt_png_path
        assert png_path.suffix.lower() == ".png", f"{slabel}: path {raw_path!r} must be a .png file"
        assert png_path.is_file(), f"{slabel}: PNG file does not exist at {png_path}"

        if png_path not in png_cache:
            png_bytes = png_path.read_bytes()
            ihdr_w, ihdr_h, pixels = decode_png_rgba(png_bytes)
            png_cache[png_path] = (png_bytes, ihdr_w, ihdr_h, pixels)
        else:
            png_bytes, ihdr_w, ihdr_h, pixels = png_cache[png_path]

        manifest_w = sprite.get("width", sheet_obj.get("width") if isinstance(sheet_obj, dict) else None)
        manifest_h = sprite.get("height", sheet_obj.get("height") if isinstance(sheet_obj, dict) else None)
        assert _is_strict_int(manifest_w) and _is_strict_int(manifest_h), (
            f"{slabel}: missing integer width/height in manifest.js"
        )
        assert (ihdr_w, ihdr_h) == (manifest_w, manifest_h), (
            f"{slabel}: PNG IHDR {(ihdr_w, ihdr_h)} != manifest {(manifest_w, manifest_h)}"
        )

        frame_w = sprite.get("frameWidth", sprite.get("w", manifest_w))
        frame_h = sprite.get("frameHeight", sprite.get("h", manifest_h))
        assert _is_strict_int(frame_w) and 1 <= frame_w <= ihdr_w, (
            f"{slabel}: invalid frameWidth {frame_w!r} for PNG width {ihdr_w}"
        )
        assert _is_strict_int(frame_h) and 1 <= frame_h <= ihdr_h, (
            f"{slabel}: invalid frameHeight {frame_h!r} for PNG height {ihdr_h}"
        )

        crop_x = sprite.get("x", 0)
        crop_y = sprite.get("y", 0)
        assert _is_strict_int(crop_x) and 0 <= crop_x and crop_x + frame_w <= ihdr_w, (
            f"{slabel}: invalid x={crop_x!r}, frameWidth={frame_w} for PNG width {ihdr_w}"
        )
        assert _is_strict_int(crop_y) and 0 <= crop_y and crop_y + frame_h <= ihdr_h, (
            f"{slabel}: invalid y={crop_y!r}, frameHeight={frame_h} for PNG height {ihdr_h}"
        )

        assert_region_has_nonblank_pixels(
            pixels, ihdr_w, ihdr_h, crop_x, crop_y, frame_w, frame_h, f"{slabel} frame0"
        )

        if crop_x == 0 and crop_y == 0 and (frame_w < ihdr_w or frame_h < ihdr_h):
            assert_region_has_nonblank_pixels(
                pixels, ihdr_w, ihdr_h, 0, 0, ihdr_w, ihdr_h, f"{slabel} full"
            )

        n_frames = sprite.get("frames")
        margin = sprite.get("margin", 0) if _is_strict_int(sprite.get("margin", 0)) else 0
        spacing = sprite.get("spacing", 0) if _is_strict_int(sprite.get("spacing", 0)) else 0
        step_x = frame_w + spacing
        step_y = frame_h + spacing
        if _is_strict_int(n_frames) and n_frames > 1 and crop_x == 0 and crop_y == 0:
            cols = max(1, (ihdr_w - margin + spacing) // step_x)
            rows = max(1, (ihdr_h - margin + spacing) // step_y)
            assert cols * rows >= n_frames, (
                f"{slabel}: {n_frames} frames of {frame_w}x{frame_h} do not fit in {ihdr_w}x{ihdr_h}"
            )
            for f_idx in range(n_frames):
                fx = margin + (f_idx % cols) * step_x
                fy = margin + (f_idx // cols) * step_y
                assert_region_has_nonblank_pixels(
                    pixels, ihdr_w, ihdr_h, fx, fy, frame_w, frame_h, f"{slabel} frame[{f_idx}]"
                )
        elif isinstance(n_frames, list) and n_frames:
            for f_idx, f_box in enumerate(n_frames):
                if isinstance(f_box, dict) and _is_strict_int(f_box.get("x")) and _is_strict_int(f_box.get("y")):
                    bw = f_box.get("w", f_box.get("width", frame_w))
                    bh = f_box.get("h", f_box.get("height", frame_h))
                    assert _is_strict_int(bw) and _is_strict_int(bh)
                    assert_region_has_nonblank_pixels(
                        pixels, ihdr_w, ihdr_h, int(f_box["x"]), int(f_box["y"]), int(bw), int(bh), f"{slabel} frame[{f_idx}]"
                    )

        pack_ref = sprite.get("pack") or sprite.get("packId")
        if isinstance(pack_ref, str) and pack_ref.strip() and known_pack_ids:
            assert pack_ref.strip() in known_pack_ids, (
                f"{slabel}: unknown pack reference {pack_ref!r} not in {sorted(known_pack_ids)}"
            )

        data_uri = sprite.get("dataUri") or (sheet_obj.get("dataUri") if isinstance(sheet_obj, dict) else None)
        assert isinstance(data_uri, str) and data_uri.startswith(DATA_URI_PREFIX), (
            f"{slabel}: dataUri must start with {DATA_URI_PREFIX!r}"
        )
        b64_payload = data_uri[len(DATA_URI_PREFIX) :]
        assert b64_payload, f"{slabel}: empty base64 payload in dataUri"
        try:
            decoded_bytes = base64.b64decode(b64_payload, validate=True)
        except Exception as exc:
            raise AssertionError(f"{slabel}: invalid base64 in dataUri: {exc}") from exc
        assert decoded_bytes == png_bytes, (
            f"{slabel}: dataUri decoded bytes ({len(decoded_bytes)} B) != on-disk PNG ({len(png_bytes)} B)"
        )

    asset_files = [p for p in assets_dir.rglob("*") if p.is_file()]
    total_bytes = sum(p.stat().st_size for p in asset_files)
    assert total_bytes > 0, "assets directory is empty"
    assert total_bytes < hard_max_bytes, (
        f"assets directory size {total_bytes} bytes >= hard limit {hard_max_bytes} bytes"
    )

    under_soft_limit = total_bytes < soft_warn_bytes
    if not under_soft_limit:
        warnings.warn(
            f"demo/out-think-gemini/assets/ is {total_bytes} bytes (>= {soft_warn_bytes} bytes soft target)",
            UserWarning,
            stacklevel=2,
        )

    return {
        "sprite_count": len(sprites),
        "pack_count": len(pack_entries),
        "total_bytes": total_bytes,
        "under_soft_limit": under_soft_limit,
    }


def _make_pixel_sprite_rgba(width: int, height: int, seed_num: int, *, opaque_tile: bool = False) -> bytes:
    fg = ((seed_num * 53 + 40) % 220 + 30, (seed_num * 97 + 70) % 220 + 30, (seed_num * 149 + 90) % 220 + 30, 255)
    accent = ((fg[0] ^ 0x55) | 0x20, (fg[1] ^ 0x33) | 0x20, (fg[2] ^ 0x66) | 0x20, 255)
    bg = (28, 32, 44, 255) if opaque_tile else (0, 0, 0, 0)
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(height):
        for x in range(width):
            lx = x % 16
            ly = y % 16
            if 3 <= lx <= 12 and 2 <= ly <= 13:
                pixels.append(accent if (lx + ly) % 3 == 0 else fg)
            else:
                pixels.append(bg)
    return encode_rgba_png(width, height, pixels)


def _build_synthetic_demo_fixture(base_dir: Path) -> tuple[Path, Path]:
    h1 = chr(35)
    h2 = chr(35) * 2
    h3 = chr(35) * 3
    md_path = base_dir / "docs" / "demo" / "ASSETS.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_content = (
        f"{h1} Out-Think Gemini: Pixel Detective Room Asset Provenance (CC0)\n\n"
        "Zero paid, ripped, commercial-game, or unlicensed sprites are used.\n\n"
        f"{h2} Pack Summary Table\n\n"
        "| Pack ID | Pack Name | Author | License | Source URL |\n"
        "|---|---|---|---|---|\n"
        "| `kenney-roguelike-indoor` | Roguelike Indoor pack | Kenney | CC0-1.0 | https://opengameart.org/content/roguelike-indoor-pack |\n"
        "| `oga-detective-items` | 16x16 Detective Items | ARoachIFoundOnMyPillow | CC0-1.0 | https://opengameart.org/content/16x16-detective-items |\n\n"
        f"{h2} Per-Pack Provenance\n\n"
        f"{h3} 1. `kenney-roguelike-indoor`\n"
        "- **Author:** Kenney\n"
        "- **License:** CC0-1.0 (https://creativecommons.org/publicdomain/zero/1.0/)\n"
        "- **Direct Page URL:** https://opengameart.org/content/roguelike-indoor-pack\n\n"
        f"{h3} 2. `oga-detective-items`\n"
        "- **Author:** ARoachIFoundOnMyPillow\n"
        "- **License:** CC0-1.0\n"
        "- **Direct Page URL:** https://opengameart.org/content/16x16-detective-items\n"
    )
    md_path.write_text(md_content, encoding="utf-8")

    demo_dir = base_dir / "demo" / "out-think-gemini"
    assets_dir = demo_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    sprites_manifest: dict[str, dict[str, object]] = {}
    for idx, key in enumerate(REQUIRED_SPRITE_KEYS):
        is_animated = key in ("detective", "suspect_0", "agent_high")
        is_tile = key in ("floor_tile", "wall_tile")
        frames = 4 if is_animated else 1
        w = 16 * frames
        h = 16
        png_bytes = _make_pixel_sprite_rgba(w, h, idx + 1, opaque_tile=is_tile)
        png_file = assets_dir / f"{key}.png"
        png_file.write_bytes(png_bytes)
        b64 = base64.b64encode(png_bytes).decode("ascii")
        sprites_manifest[key] = {
            "path": f"assets/{key}.png",
            "width": w,
            "height": h,
            "frameWidth": 16,
            "frameHeight": 16,
            "frames": frames,
            "pack": "kenney-roguelike-indoor" if idx % 2 == 0 else "oga-detective-items",
            "dataUri": f"{DATA_URI_PREFIX}{b64}",
        }

    manifest_obj = {
        "version": 1,
        "packs": [
            {
                "id": "kenney-roguelike-indoor",
                "name": "Roguelike Indoor pack",
                "author": "Kenney",
                "license": "CC0-1.0",
                "url": "https://opengameart.org/content/roguelike-indoor-pack",
            },
            {
                "id": "oga-detective-items",
                "name": "16x16 Detective Items",
                "author": "ARoachIFoundOnMyPillow",
                "license": "CC0-1.0",
                "url": "https://opengameart.org/content/16x16-detective-items",
            },
        ],
        "sprites": sprites_manifest,
    }
    manifest_js = "window.OUTTHINK_ASSETS = " + json.dumps(manifest_obj, indent=2) + ";\n"
    (assets_dir / "manifest.js").write_text(manifest_js, encoding="utf-8")
    return md_path, demo_dir


def test_synthetic_valid_bundle_passes(tmp_path: Path) -> None:
    md_path, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    packs = validate_assets_md(md_path.read_text(encoding="utf-8"))
    assert len(packs) >= 2

    report = validate_outthink_manifest_and_assets(demo_dir)
    assert report["sprite_count"] == len(REQUIRED_SPRITE_KEYS)
    assert report["pack_count"] == 2
    assert report["under_soft_limit"] is True
    assert int(report["total_bytes"]) < SOFT_WARN_ASSETS_BYTES


def test_assets_md_cc_by_requires_explicit_credit() -> None:
    h1 = chr(35)
    h2 = chr(35) * 2
    valid_cc_by = (
        f"{h1} Demo Assets\n\n"
        f"{h2} Sci-Fi Lab Tiles\n"
        "- Author: Buch\n"
        "- License: CC-BY 3.0\n"
        "- Attribution: Credit to Buch on OpenGameArt\n"
        "- URL: https://opengameart.org/content/sci-fi-interior-tiles\n"
    )
    parsed = validate_assets_md(valid_cc_by)
    assert len(parsed) == 1

    missing_credit_cc_by = (
        f"{h1} Demo Assets\n\n"
        f"{h2} Sci-Fi Lab Tiles\n"
        "- Author: Buch\n"
        "- License: CC-BY 3.0\n"
        "- URL: https://opengameart.org/content/sci-fi-interior-tiles\n"
    )
    with pytest.raises(AssertionError, match="explicit credit"):
        validate_assets_md(missing_credit_cc_by)


@pytest.mark.parametrize(
    ("bad_md", "expected_err"),
    [
        (
            f"{chr(35)} Assets\n\n| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney |  | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "missing license",
        ),
        (
            f"{chr(35)} Assets\n\n| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney | CC-BY-NC 4.0 | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "forbidden",
        ),
        (
            f"{chr(35)} Assets\n\n| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor |   | CC0 | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "Author",
        ),
        (
            f"{chr(35)} Assets\n\n| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney | CC0 | https://example.com/roguelike.zip |\n",
            "opengameart",
        ),
        (
            f"{chr(35)} Assets {EM_DASH} Provenance\n\n| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney | CC0 | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "em dash",
        ),
        (
            f"{chr(35)} Assets {EN_DASH} Provenance\n\n| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney | CC0 | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "en dash",
        ),
        (
            f"{chr(35)} Assets\nDownloaded paid sprite bundle from itch.io.\n\n"
            "| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney | CC0 | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "forbidden",
        ),
        (
            f"{chr(35)} Assets\nSprites ripped from spriters-resource.\n\n"
            "| Pack | Author | License | Source URL |\n|---|---|---|---|\n"
            "| Indoor | Kenney | CC0 | https://opengameart.org/content/roguelike-indoor-pack |\n",
            "forbidden",
        ),
        (
            f"{chr(35)} Assets\nJust prose and zero pack entries.\n",
            ">= 1 pack",
        ),
    ],
)
def test_assets_md_rejects_broken_provenance(bad_md: str, expected_err: str) -> None:
    with pytest.raises(AssertionError, match=re.escape(expected_err)):
        validate_assets_md(bad_md)


def test_manifest_rejects_blank_transparent_png(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    assets_dir = demo_dir / "assets"
    manifest_path = assets_dir / "manifest.js"
    manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))

    blank_pixels = [((i * 17) % 256, (i * 31) % 256, (i * 47) % 256, 0) for i in range(16 * 16)]
    blank_png = encode_rgba_png(16, 16, blank_pixels)
    (assets_dir / "icon_magnifier.png").write_bytes(blank_png)
    sprites = manifest["sprites"]
    assert isinstance(sprites, dict)
    sprites["icon_magnifier"]["dataUri"] = DATA_URI_PREFIX + base64.b64encode(blank_png).decode("ascii")
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(manifest) + ";\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="100% transparent blank sprite crop"):
        validate_outthink_manifest_and_assets(demo_dir)


def test_manifest_rejects_single_solid_background_pixel_crop(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    assets_dir = demo_dir / "assets"
    manifest_path = assets_dir / "manifest.js"
    manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))

    solid_png = encode_rgba_png(16, 16, [(36, 40, 52, 255)] * (16 * 16))
    (assets_dir / "floor_tile.png").write_bytes(solid_png)
    sprites = manifest["sprites"]
    assert isinstance(sprites, dict)
    sprites["floor_tile"]["dataUri"] = DATA_URI_PREFIX + base64.b64encode(solid_png).decode("ascii")
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(manifest) + ";\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="100% uniform single solid pixel"):
        validate_outthink_manifest_and_assets(demo_dir)


def test_manifest_rejects_empty_trailing_animation_frame(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    assets_dir = demo_dir / "assets"
    manifest_path = assets_dir / "manifest.js"
    manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))

    pixels: list[tuple[int, int, int, int]] = []
    for y in range(16):
        for x in range(64):
            if x < 48 and 4 <= (x % 16) <= 11 and 3 <= y <= 12:
                pixels.append((220, 180, 90, 255))
            else:
                pixels.append((0, 0, 0, 0))
    half_blank_strip = encode_rgba_png(64, 16, pixels)
    (assets_dir / "detective.png").write_bytes(half_blank_strip)
    sprites = manifest["sprites"]
    assert isinstance(sprites, dict)
    sprites["detective"]["dataUri"] = DATA_URI_PREFIX + base64.b64encode(half_blank_strip).decode("ascii")
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(manifest) + ";\n", encoding="utf-8")

    with pytest.raises(AssertionError, match=r"frame\[3\]: 100% transparent"):
        validate_outthink_manifest_and_assets(demo_dir)


def test_manifest_rejects_mismatched_data_uri(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    assets_dir = demo_dir / "assets"
    manifest_path = assets_dir / "manifest.js"
    manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))

    other_png = _make_pixel_sprite_rgba(16, 16, 999)
    sprites = manifest["sprites"]
    assert isinstance(sprites, dict)
    sprites["icon_coin"]["dataUri"] = DATA_URI_PREFIX + base64.b64encode(other_png).decode("ascii")
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(manifest) + ";\n", encoding="utf-8")

    with pytest.raises(AssertionError, match="dataUri decoded bytes"):
        validate_outthink_manifest_and_assets(demo_dir)


def test_manifest_rejects_missing_key_bad_dims_and_path_traversal(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    manifest_path = demo_dir / "assets" / "manifest.js"
    base_manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))

    m_missing = json.loads(json.dumps(base_manifest))
    del m_missing["sprites"]["icon_brain"]
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(m_missing) + ";\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="icon_brain"):
        validate_outthink_manifest_and_assets(demo_dir)

    m_bad_ihdr = json.loads(json.dumps(base_manifest))
    m_bad_ihdr["sprites"]["desk"]["width"] = 32
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(m_bad_ihdr) + ";\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="PNG IHDR"):
        validate_outthink_manifest_and_assets(demo_dir)

    m_bad_frame = json.loads(json.dumps(base_manifest))
    m_bad_frame["sprites"]["desk"]["frameWidth"] = 32
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(m_bad_frame) + ";\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="invalid frameWidth"):
        validate_outthink_manifest_and_assets(demo_dir)

    m_escape = json.loads(json.dumps(base_manifest))
    m_escape["sprites"]["desk"]["path"] = "../outside.png"
    manifest_path.write_text("window.OUTTHINK_ASSETS = " + json.dumps(m_escape) + ";\n", encoding="utf-8")
    with pytest.raises(AssertionError, match="escapes demo/out-think-gemini"):
        validate_outthink_manifest_and_assets(demo_dir)


def test_assets_directory_size_soft_warning_and_hard_limit(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    sparse_blob = demo_dir / "assets" / "_sparse_test.bin"
    try:
        with sparse_blob.open("wb") as fh:
            os.truncate(fh.fileno(), SOFT_WARN_ASSETS_BYTES + 4096)
        with pytest.warns(UserWarning, match="soft target"):
            report = validate_outthink_manifest_and_assets(demo_dir)
        assert report["under_soft_limit"] is False

        with sparse_blob.open("wb") as fh:
            os.truncate(fh.fileno(), HARD_MAX_ASSETS_BYTES)
        with pytest.raises(AssertionError, match="hard limit"):
            validate_outthink_manifest_and_assets(demo_dir)
    finally:
        sparse_blob.unlink(missing_ok=True)


@pytest.mark.parametrize("filter_type", [0, 1, 2, 3, 4])
def test_png_stdlib_decoder_all_scanline_filters(filter_type: int) -> None:
    src_pixels = [
        ((x * 37 + y * 13) % 256, (x * 19 + y * 59) % 256, (x * 71 + y * 23) % 256, 0 if (x + y) % 5 == 0 else 255)
        for y in range(8)
        for x in range(8)
    ]
    png_bytes = encode_rgba_png(8, 8, src_pixels, filter_type=filter_type)
    w, h, decoded = decode_png_rgba_zlib(png_bytes)
    assert (w, h) == (8, 8)
    assert decoded == src_pixels
    if _PILImage is not None:
        _, _, pil_decoded = _pil_rgba_pixels(png_bytes)
        assert pil_decoded == decoded


def test_manifest_js_supports_iife_comments_and_dict_packs(tmp_path: Path) -> None:
    _, demo_dir = _build_synthetic_demo_fixture(tmp_path)
    manifest_path = demo_dir / "assets" / "manifest.js"
    manifest = parse_window_outthink_assets(manifest_path.read_text(encoding="utf-8"))
    manifest["packs"] = {
        "kenney-roguelike-indoor": {
            "name": "Roguelike Indoor pack",
            "author": "Kenney",
            "license": "CC0-1.0",
            "sourceUrl": "https://opengameart.org/content/roguelike-indoor-pack",
        },
        "oga-detective-items": {
            "name": "16x16 Detective Items",
            "author": "ARoachIFoundOnMyPillow",
            "license": "CC0-1.0",
            "pageUrl": "https://opengameart.org/content/16x16-detective-items",
        },
    }
    iife_src = (
        "/* Offline pixel detective manifest */\n"
        "(function(g) {\n"
        "  // assign global bundle\n"
        "  g.OUTTHINK_ASSETS = " + json.dumps(manifest, indent=2)[:-2] + ",\n}\n;\n"
        "})(typeof window !== 'undefined' ? window : globalThis);\n"
    )
    manifest_path.write_text(iife_src, encoding="utf-8")
    report = validate_outthink_manifest_and_assets(demo_dir)
    assert report["pack_count"] == 2
    assert report["sprite_count"] == len(REQUIRED_SPRITE_KEYS)


def test_live_repo_assets_md() -> None:
    if not LIVE_ASSETS_MD.exists():
        pytest.skip("docs/demo/ASSETS.md not yet merged on this branch")
    packs = validate_assets_md(LIVE_ASSETS_MD.read_text(encoding="utf-8"))
    assert len(packs) >= 1


def test_live_repo_manifest_and_png_assets() -> None:
    if not LIVE_MANIFEST_JS.exists():
        pytest.skip("demo/out-think-gemini/assets/manifest.js not yet merged on this branch")
    report = validate_outthink_manifest_and_assets(LIVE_DEMO_DIR)
    assert int(report["sprite_count"]) >= len(REQUIRED_SPRITE_KEYS)


def test_zero_comments_zero_forbidden_dashes_and_zero_network_imports() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")

    assert EM_DASH not in src, "em dash found in test_outthink_assets_qa.py"
    assert EN_DASH not in src, "en dash found in test_outthink_assets_qa.py"
    assert chr(35) not in src, "hash character found in test_outthink_assets_qa.py"

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"comment tokens found: {comments}"

    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = ("google", "genai", "atlas_gemini", "gateway", "httpx", "requests", "urllib")
    for mod in imported:
        assert not any(f in mod for f in forbidden), f"forbidden module imported: {mod}"
