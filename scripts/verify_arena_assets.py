from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import struct
import subprocess
import sys
import time
import tokenize
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
SELF_PATH = Path(__file__).resolve()

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
IHDR_TAG = b"IHDR"
MAX_ARENA_ASSET_BYTES = 15_000_000
CANONICAL_TOTAL_PNG_BYTES = 56_875
EXPECTED_BADGE_COUNT = 8
TILE_BASE_PX = 16

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)

EMP_ID_RE = re.compile(r"^e(?:0[1-9]|[1-9]\d|\d{3})$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

GOOGLE_KEY_PREFIX = "AI" + "za"
SK_KEY_PREFIX = "s" + "k-"
OAUTH_PREFIX = "ya" + "29."
HF_PREFIX = "h" + "f_"
XAI_PREFIX = "xa" + "i-"
GH_PREFIX = "gh"
GOOG_HDR = "x-goog-" + "api-key"

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "google_api_key",
        re.compile(r"(?<![0-9A-Za-z+/_-])" + re.escape(GOOGLE_KEY_PREFIX) + r"[0-9A-Za-z_-]{20,}"),
    ),
    (
        "sk_api_key",
        re.compile(
            r"(?<![0-9A-Za-z+/_-])"
            + re.escape(SK_KEY_PREFIX)
            + r"(?:proj-|ant-|live-|test-|svcacct-)?[0-9A-Za-z_-]{16,}"
        ),
    ),
    ("google_oauth", re.compile(re.escape(OAUTH_PREFIX) + r"[0-9A-Za-z_-]{20,}")),
    ("hf_token", re.compile(re.escape(HF_PREFIX) + r"[A-Za-z0-9]{24,}")),
    ("xai_key", re.compile(re.escape(XAI_PREFIX) + r"[A-Za-z0-9_-]{24,}")),
    ("github_pat", re.compile(GH_PREFIX + r"[pousr]_[A-Za-z0-9]{24,}")),
    (
        "gateway_header_key",
        re.compile(r'"' + re.escape(GOOG_HDR) + r'"\s*:\s*"[^"\s]{8,}"', re.IGNORECASE),
    ),
)

SECRET_ENV_NAMES: tuple[str, ...] = (
    "CANARY_WORLD_" + "SECRET",
    "CANARY_LEDGER_" + "TOKEN",
    "CANARY_ADMIN_" + "TOKEN",
    "CANARY_LEDGER_" + "KEY",
    "GEMINI_API_" + "KEY",
    "GOOGLE_API_" + "KEY",
    "GOOGLE_GENERATIVE_AI_API_" + "KEY",
    "OPENAI_API_" + "KEY",
    "ANTHROPIC_API_" + "KEY",
    "OPENROUTER_API_" + "KEY",
)

ASSIGN_SECRET_NAMES: tuple[str, ...] = ("SA" + "LT", *SECRET_ENV_NAMES)

SECRET_ASSIGN_RE = re.compile(
    r"""(?:["']?(?:"""
    + "|".join(ASSIGN_SECRET_NAMES)
    + r""")["']?\s*[:=]\s*["'][A-Za-z0-9_./+=-]{6,}["'])"""
)
DOTENV_SECRET_RE = re.compile(
    r"(?:^|\n)\s*(?:" + "|".join(ASSIGN_SECRET_NAMES) + r")\s*=\s*[^\s\"']{6,}"
)
STRICT_LITERAL_NAMES_RE = re.compile(
    r"\b(?:" + "|".join(SECRET_ENV_NAMES) + r")\b|data/worlds/" + "judge/SA" + "LT"
)

STRICT_DOC_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".txt", ".json", ".jsonl", ".html", ".css", ".svg"}
)
BINARY_ASSET_SUFFIXES: frozenset[str] = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".mp4",
        ".webm",
        ".mp3",
        ".wav",
        ".ogg",
        ".wasm",
        ".zip",
    }
)
FORBIDDEN_SECRET_FILENAMES: frozenset[str] = frozenset(
    {"SA" + "LT", "ledger_" + "key", ".env"}
)
ALLOWED_ENV_TEMPLATES: frozenset[str] = frozenset(
    {".env.example", ".env.sample", ".env.template"}
)

PRE_END_SPRITE_LEAK_KEYS: tuple[str, ...] = (
    "mole",
    "true_mole",
    "mole_id",
    "decoy",
    "true_decoy",
    "decoy_id",
    "mole_sprite",
    "culprit_sprite",
    "leaker_employee",
    "is_mole",
)

PROTECTED_EXACT: frozenset[str] = frozenset(
    {
        "canary/env.py",
        "canary/rules.py",
        "canary/reproduce.py",
    }
)
PROTECTED_PREFIXES: tuple[str, ...] = (
    "canary/solver/",
    "harbor/",
)
PROTECTED_GIT_TARGETS: tuple[str, ...] = (
    "canary/env.py",
    "canary/rules.py",
    "canary/reproduce.py",
    "canary/solver",
    "harbor",
)
DEFAULT_BASE_CANDIDATES: tuple[str, ...] = (
    "origin/justSilas",
    "justSilas",
    "origin/fr8/canary/research-arena",
    "HEAD",
)

OWNED_PYTHON_REL_PATHS: tuple[str, ...] = (
    "scripts/verify_arena_assets.py",
    "tests/test_verify_arena_assets.py",
    "tests/test_arena_assets_pack.py",
    "tests/test_arena_seeds_doc.py",
)
STRICT_NO_HASH_REL_PATHS: frozenset[str] = frozenset(
    {
        "scripts/verify_arena_assets.py",
        "tests/test_verify_arena_assets.py",
        "tests/test_arena_assets_pack.py",
    }
)


@dataclass
class CheckOutcome:
    check_id: str
    name: str
    passed: bool
    status: str
    summary: str
    metrics: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def is_protected_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").strip()
    while norm.startswith("./"):
        norm = norm[2:]
    if norm in PROTECTED_EXACT or norm in {"canary/solver", "harbor"}:
        return True
    return any(norm.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def parse_png_ihdr(data: bytes) -> tuple[int, int]:
    if len(data) < 24:
        raise ValueError(f"PNG truncated ({len(data)} bytes < 24)")
    if data[:8] != PNG_SIGNATURE:
        raise ValueError("invalid PNG binary signature")
    ihdr_len = struct.unpack(">I", data[8:12])[0]
    if ihdr_len != 13:
        raise ValueError(f"invalid IHDR chunk length ({ihdr_len} != 13)")
    if data[12:16] != IHDR_TAG:
        raise ValueError("first PNG chunk is not IHDR")
    width, height = struct.unpack(">II", data[16:24])
    if width <= 0 or height <= 0:
        raise ValueError(f"non-positive PNG IHDR dimensions ({width}x{height})")
    return width, height


def _load_manifest(root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    manifest_path = root / "docs" / "arena" / "assets" / "sprite_pack_manifest.json"
    if not manifest_path.is_file():
        return None, [f"missing manifest: {manifest_path}"]
    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"docs/arena/assets/sprite_pack_manifest.json: unreadable UTF-8 ({exc})"]
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [
            f"docs/arena/assets/sprite_pack_manifest.json: invalid JSON ({exc.msg} at line {exc.lineno})"
        ]
    if not isinstance(parsed, dict):
        return None, ["docs/arena/assets/sprite_pack_manifest.json: root JSON value must be an object"]
    return parsed, []


def _resolve_asset_file(root: Path, assets_dir: Path, ref: str) -> Path:
    norm = ref.strip()
    while norm.startswith("./"):
        norm = norm[2:]
    if norm.startswith("docs/"):
        return root / norm
    return assets_dir / norm


def check_png_ihdr_and_sha256(root: Path, strict: bool = False) -> CheckOutcome:
    name = "Check 1: PNG IHDR & SHA-256 Integrity"
    assets_dir = root / "docs" / "arena" / "assets"
    manifest, load_errors = _load_manifest(root)
    if manifest is None:
        return CheckOutcome(
            "C1",
            name,
            False,
            "FAIL",
            "sprite_pack_manifest.json missing or invalid",
            violations=load_errors,
        )

    violations: list[str] = []
    warnings: list[str] = []
    verified_png_paths: set[Path] = set()
    sheet_dims: dict[str, tuple[int, int]] = {}

    sheets = manifest.get("sheets")
    if not isinstance(sheets, dict) or not sheets:
        violations.append("manifest.sheets must be a non-empty object")
        sheets = {}

    sheet_refs: dict[str, str] = {}
    for alias, rel_file in sheets.items():
        if not isinstance(rel_file, str) or not rel_file.strip():
            violations.append(f"manifest.sheets.{alias}: sheet filename must be a non-empty string")
            continue
        sheet_refs[f"sheets.{alias}"] = rel_file

    for top_key in ("tileSheet", "charSheet"):
        top_val = manifest.get(top_key)
        if not isinstance(top_val, str) or not top_val.strip():
            violations.append(f"manifest.{top_key}: must be a non-empty string")
        else:
            sheet_refs[top_key] = top_val

    for label, rel_file in sorted(sheet_refs.items()):
        png_path = _resolve_asset_file(root, assets_dir, rel_file)
        if not png_path.is_file():
            violations.append(f"{label}: missing PNG file '{rel_file}'")
            continue
        try:
            w, h = parse_png_ihdr(png_path.read_bytes())
            sheet_dims[rel_file] = (w, h)
            verified_png_paths.add(png_path.resolve())
        except (OSError, ValueError) as exc:
            violations.append(f"{label} ({rel_file}): {exc}")

    badges_dir = assets_dir / "kenney_ui_badges"
    badge_files_ok = 0
    if not badges_dir.is_dir():
        violations.append("missing badge directory: docs/arena/assets/kenney_ui_badges")
    else:
        for idx in range(EXPECTED_BADGE_COUNT):
            bname = f"badge_{idx:02d}.png"
            bpath = badges_dir / bname
            if not bpath.is_file():
                violations.append(f"missing required UI badge: docs/arena/assets/kenney_ui_badges/{bname}")
                continue
            try:
                bw, bh = parse_png_ihdr(bpath.read_bytes())
                verified_png_paths.add(bpath.resolve())
                if (bw, bh) != (TILE_BASE_PX, TILE_BASE_PX):
                    violations.append(
                        f"kenney_ui_badges/{bname}: expected 16x16 IHDR, got {bw}x{bh}"
                    )
                else:
                    badge_files_ok += 1
            except (OSError, ValueError) as exc:
                violations.append(f"kenney_ui_badges/{bname}: {exc}")

    packs = manifest.get("packs")
    pack_bytes_sum = 0
    packs_verified = 0
    if not isinstance(packs, list) or not packs:
        violations.append("manifest.packs must be a non-empty list")
        packs = []

    for idx, pack in enumerate(packs):
        ploc = f"manifest.packs[{idx}]"
        if not isinstance(pack, dict):
            violations.append(f"{ploc}: pack entry must be an object")
            continue
        pid = str(pack.get("id") or f"pack_{idx}")
        pfile = pack.get("file")
        pbytes = pack.get("bytes")
        psha = pack.get("sha256")
        pw = pack.get("width")
        ph = pack.get("height")

        if not isinstance(pfile, str) or not pfile.strip():
            violations.append(f"{ploc} ({pid}): missing 'file'")
            continue
        if not _is_int(pbytes) or int(pbytes) <= 0:
            violations.append(f"{ploc} ({pid}): 'bytes' must be a positive integer")
            continue
        if not isinstance(psha, str) or not HEX64_RE.match(psha):
            violations.append(f"{ploc} ({pid}): 'sha256' must be a 64-char lowercase hex digest")
            continue
        if not _is_int(pw) or not _is_int(ph) or int(pw) <= 0 or int(ph) <= 0:
            violations.append(f"{ploc} ({pid}): 'width' and 'height' must be positive integers")
            continue

        pack_bytes_sum += int(pbytes)
        target = _resolve_asset_file(root, assets_dir, pfile)

        if pfile.endswith(".png"):
            if not target.is_file():
                violations.append(f"{ploc} ({pid}): missing PNG file '{pfile}'")
                continue
            try:
                raw_png = target.read_bytes()
                actual_w, actual_h = parse_png_ihdr(raw_png)
            except (OSError, ValueError) as exc:
                violations.append(f"{ploc} ({pid}, {pfile}): {exc}")
                continue
            verified_png_paths.add(target.resolve())
            if (actual_w, actual_h) != (int(pw), int(ph)):
                violations.append(
                    f"{ploc} ({pid}): IHDR {actual_w}x{actual_h} != manifest {pw}x{ph}"
                )
            if len(raw_png) != int(pbytes):
                violations.append(
                    f"{ploc} ({pid}): byte size {len(raw_png)} != manifest {pbytes}"
                )
            actual_sha = hashlib.sha256(raw_png).hexdigest()
            if actual_sha != psha:
                violations.append(
                    f"{ploc} ({pid}): sha256 {actual_sha} != manifest {psha}"
                )
            packs_verified += 1
        else:
            if not target.is_dir():
                violations.append(f"{ploc} ({pid}): missing pack directory '{pfile}'")
                continue
            dir_pngs = sorted(p for p in target.glob("*.png") if p.is_file())
            if len(dir_pngs) != EXPECTED_BADGE_COUNT:
                violations.append(
                    f"{ploc} ({pid}): expected {EXPECTED_BADGE_COUNT} badge PNGs in '{pfile}', found {len(dir_pngs)}"
                )
            dir_bytes = 0
            dir_ok = True
            for bpath in dir_pngs:
                try:
                    bdata = bpath.read_bytes()
                    bw, bh = parse_png_ihdr(bdata)
                except (OSError, ValueError) as exc:
                    violations.append(f"{ploc} ({pid}, {bpath.name}): {exc}")
                    dir_ok = False
                    continue
                verified_png_paths.add(bpath.resolve())
                dir_bytes += len(bdata)
                if (bw, bh) != (int(pw), int(ph)):
                    violations.append(
                        f"{ploc} ({pid}, {bpath.name}): IHDR {bw}x{bh} != manifest {pw}x{ph}"
                    )
            if dir_bytes != int(pbytes):
                violations.append(
                    f"{ploc} ({pid}): directory PNG bytes {dir_bytes} != manifest {pbytes}"
                )
            badge0 = target / "badge_00.png"
            if badge0.is_file():
                b0_sha = hashlib.sha256(badge0.read_bytes()).hexdigest()
                if b0_sha != psha:
                    violations.append(
                        f"{ploc} ({pid}): badge_00.png sha256 {b0_sha} != manifest {psha}"
                    )
            else:
                violations.append(f"{ploc} ({pid}): missing badge_00.png for pack sha256 anchor")
            if dir_ok:
                packs_verified += 1

    all_disk_pngs = sorted(p for p in assets_dir.rglob("*.png") if p.is_file()) if assets_dir.is_dir() else []
    disk_total_bytes = sum(p.stat().st_size for p in all_disk_pngs)
    declared_total = manifest.get("total_png_bytes")
    max_budget = manifest.get("max_budget_bytes", MAX_ARENA_ASSET_BYTES)

    if not _is_int(declared_total) or int(declared_total) <= 0:
        violations.append("manifest.total_png_bytes must be a positive integer")
    else:
        if disk_total_bytes != int(declared_total):
            violations.append(
                f"disk PNG bytes ({disk_total_bytes}) != manifest.total_png_bytes ({declared_total})"
            )
        if pack_bytes_sum != int(declared_total):
            violations.append(
                f"sum of pack bytes ({pack_bytes_sum}) != manifest.total_png_bytes ({declared_total})"
            )

    if not _is_int(max_budget) or int(max_budget) <= 0 or int(max_budget) > MAX_ARENA_ASSET_BYTES:
        violations.append(
            f"manifest.max_budget_bytes ({max_budget!r}) must be in 1..{MAX_ARENA_ASSET_BYTES}"
        )
    elif disk_total_bytes >= int(max_budget) or disk_total_bytes >= MAX_ARENA_ASSET_BYTES:
        violations.append(
            f"total PNG bytes ({disk_total_bytes}) exceeds Arena cap ({MAX_ARENA_ASSET_BYTES})"
        )

    if disk_total_bytes == 0:
        violations.append("0 PNG bytes found under docs/arena/assets")

    untracked_pngs = [
        p.relative_to(assets_dir).as_posix()
        for p in all_disk_pngs
        if p.resolve() not in verified_png_paths
    ]
    if untracked_pngs:
        msg = f"unreferenced PNG file(s) under docs/arena/assets: {', '.join(untracked_pngs)}"
        if strict:
            violations.append(msg)
        else:
            warnings.append(msg)

    passed = len(violations) == 0
    metrics = {
        "png_files_on_disk": len(all_disk_pngs),
        "packs_verified": packs_verified,
        "badges_verified": badge_files_ok,
        "total_png_bytes": disk_total_bytes,
        "canonical_expected_bytes": CANONICAL_TOTAL_PNG_BYTES,
        "max_budget_bytes": MAX_ARENA_ASSET_BYTES,
        "sheet_dimensions": sheet_dims,
    }
    summary = (
        f"png_files={len(all_disk_pngs)} packs={packs_verified} badges={badge_files_ok}/{EXPECTED_BADGE_COUNT} "
        f"total_png_bytes={disk_total_bytes} (< {MAX_ARENA_ASSET_BYTES})"
        if passed
        else f"{len(violations)} PNG/IHDR/SHA-256 violation(s)"
    )
    return CheckOutcome("C1", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations, warnings)


def check_sprite_coordinates_and_bounds(root: Path, strict: bool = False) -> CheckOutcome:
    name = "Check 2: Sprite Coordinate & Sheet Bounds"
    assets_dir = root / "docs" / "arena" / "assets"
    manifest, load_errors = _load_manifest(root)
    if manifest is None:
        return CheckOutcome(
            "C2",
            name,
            False,
            "FAIL",
            "sprite_pack_manifest.json missing or invalid",
            violations=load_errors,
        )

    violations: list[str] = []
    warnings: list[str] = []
    sheets = manifest.get("sheets") if isinstance(manifest.get("sheets"), dict) else {}
    dims_cache: dict[Path, tuple[int, int] | None] = {}

    def _dims_for(path: Path) -> tuple[int, int] | None:
        resolved = path.resolve()
        if resolved in dims_cache:
            return dims_cache[resolved]
        if not path.is_file():
            dims_cache[resolved] = None
            return None
        try:
            dims_cache[resolved] = parse_png_ihdr(path.read_bytes())
        except (OSError, ValueError):
            dims_cache[resolved] = None
        return dims_cache[resolved]

    sprites_checked = 0
    item_sprites_checked = 0

    for group_key in ("sprites", "item_sprites"):
        group = manifest.get(group_key)
        if not isinstance(group, dict) or not group:
            violations.append(f"manifest.{group_key} must be a non-empty object")
            continue

        for sprite_name, rect in sorted(group.items()):
            loc = f"manifest.{group_key}.{sprite_name}"
            if not isinstance(rect, dict):
                violations.append(f"{loc}: entry must be an object")
                continue

            target_path: Path | None = None
            if "sheet" in rect:
                sheet_alias = rect.get("sheet")
                if not isinstance(sheet_alias, str) or sheet_alias not in sheets:
                    violations.append(f"{loc}: unknown sheet alias {sheet_alias!r}")
                    continue
                sheet_rel = sheets[sheet_alias]
                if not isinstance(sheet_rel, str) or not sheet_rel.strip():
                    violations.append(f"{loc}: invalid sheet target for alias {sheet_alias!r}")
                    continue
                target_path = _resolve_asset_file(root, assets_dir, sheet_rel)
            elif "file" in rect:
                file_rel = rect.get("file")
                if not isinstance(file_rel, str) or not file_rel.strip():
                    violations.append(f"{loc}: 'file' must be a non-empty string")
                    continue
                target_path = _resolve_asset_file(root, assets_dir, file_rel)
            else:
                violations.append(f"{loc}: must specify either 'sheet' or 'file'")
                continue

            dims = _dims_for(target_path)
            if dims is None:
                violations.append(f"{loc}: target PNG missing or invalid IHDR ({target_path.name})")
                continue
            sheet_w, sheet_h = dims

            x = rect.get("x")
            y = rect.get("y")
            w = rect.get("w")
            h = rect.get("h")
            if not (_is_int(x) and _is_int(y) and _is_int(w) and _is_int(h)):
                violations.append(f"{loc}: x, y, w, h must all be integers")
                continue
            ix, iy, iw, ih = int(x), int(y), int(w), int(h)

            if ix < 0 or iy < 0:
                violations.append(f"{loc}: negative origin ({ix}, {iy})")
            if iw <= 0 or ih <= 0:
                violations.append(f"{loc}: non-positive size ({iw}x{ih})")
            if ix + iw > sheet_w:
                violations.append(
                    f"{loc}: x + w ({ix} + {iw} = {ix + iw}) exceeds sheet_width ({sheet_w})"
                )
            if iy + ih > sheet_h:
                violations.append(
                    f"{loc}: y + h ({iy} + {ih} = {iy + ih}) exceeds sheet_height ({sheet_h})"
                )

            if "col" in rect or "row" in rect:
                col = rect.get("col")
                row = rect.get("row")
                margin = rect.get("margin", 0)
                if not (_is_int(col) and _is_int(row) and _is_int(margin)):
                    violations.append(f"{loc}: col, row, margin must be integers when present")
                elif int(col) < 0 or int(row) < 0 or int(margin) < 0:
                    violations.append(f"{loc}: col, row, margin must be non-negative")
                else:
                    stride = TILE_BASE_PX + int(margin)
                    exp_x = int(col) * stride
                    exp_y = int(row) * stride
                    if ix != exp_x:
                        violations.append(
                            f"{loc}: x={ix} != col*(16+margin) ({col}*{stride}={exp_x})"
                        )
                    if iy != exp_y:
                        violations.append(
                            f"{loc}: y={iy} != row*(16+margin) ({row}*{stride}={exp_y})"
                        )

            if strict and (iw != TILE_BASE_PX or ih != TILE_BASE_PX):
                warnings.append(f"{loc}: non-16x16 sprite rect ({iw}x{ih})")

            if group_key == "sprites":
                sprites_checked += 1
            else:
                item_sprites_checked += 1

    if strict and warnings:
        violations.extend(warnings)

    passed = len(violations) == 0
    metrics = {
        "sprites_checked": sprites_checked,
        "item_sprites_checked": item_sprites_checked,
        "total_entries_checked": sprites_checked + item_sprites_checked,
    }
    summary = (
        f"sprites={sprites_checked} item_sprites={item_sprites_checked} all in-bounds & grid-aligned"
        if passed
        else f"{len(violations)} sprite coordinate/bounds violation(s)"
    )
    return CheckOutcome("C2", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations, warnings)


def check_cc0_license_and_attribution(root: Path, strict: bool = False) -> CheckOutcome:
    name = "Check 3: CC0-1.0 License & Attribution Parity"
    assets_dir = root / "docs" / "arena" / "assets"
    license_path = assets_dir / "LICENSE-CC0-1.0.txt"
    assets_md_path = root / "docs" / "arena" / "ASSETS.md"
    manifest, load_errors = _load_manifest(root)
    if manifest is None:
        return CheckOutcome(
            "C3",
            name,
            False,
            "FAIL",
            "sprite_pack_manifest.json missing or invalid",
            violations=load_errors,
        )

    violations: list[str] = []
    warnings: list[str] = []

    if not license_path.is_file():
        violations.append("missing bundled license file: docs/arena/assets/LICENSE-CC0-1.0.txt")
    else:
        try:
            lic_text = license_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"LICENSE-CC0-1.0.txt: unreadable UTF-8 ({exc})")
            lic_text = ""
        if not lic_text.strip():
            violations.append("LICENSE-CC0-1.0.txt is empty")
        elif not all(ord(ch) < 128 for ch in lic_text):
            violations.append("LICENSE-CC0-1.0.txt contains non-ASCII characters")
        if "creativecommons.org/publicdomain/zero/1.0/" not in lic_text:
            violations.append("LICENSE-CC0-1.0.txt missing CC0 1.0 canonical URL")

    credits_text = manifest.get("creditsText")
    if not isinstance(credits_text, str) or not credits_text.strip():
        violations.append("manifest.creditsText must be a non-empty string")
    elif not all(ord(ch) < 128 for ch in credits_text):
        violations.append("manifest.creditsText must be pure ASCII")

    attrib = manifest.get("attribution")
    if not isinstance(attrib, dict):
        violations.append("manifest.attribution must be an object")
    else:
        if attrib.get("license") != "CC0-1.0":
            violations.append(
                f"manifest.attribution.license must be 'CC0-1.0', got {attrib.get('license')!r}"
            )
        attr_credits = attrib.get("creditsText")
        if attr_credits is not None:
            if not isinstance(attr_credits, str) or not attr_credits.strip():
                violations.append("manifest.attribution.creditsText must be non-empty when present")
            elif not all(ord(ch) < 128 for ch in attr_credits):
                violations.append("manifest.attribution.creditsText must be pure ASCII")
            elif strict and isinstance(credits_text, str) and attr_credits != credits_text:
                violations.append("manifest.attribution.creditsText != manifest.creditsText")

    assets_md_text = ""
    if not assets_md_path.is_file():
        violations.append("missing asset provenance doc: docs/arena/ASSETS.md")
    else:
        try:
            assets_md_text = assets_md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            violations.append(f"docs/arena/ASSETS.md: unreadable UTF-8 ({exc})")

    packs = manifest.get("packs")
    packs_cc0 = 0
    sha_cited = 0
    if not isinstance(packs, list) or not packs:
        violations.append("manifest.packs must be a non-empty list")
        packs = []

    for idx, pack in enumerate(packs):
        ploc = f"manifest.packs[{idx}]"
        if not isinstance(pack, dict):
            violations.append(f"{ploc}: pack entry must be an object")
            continue
        pid = str(pack.get("id") or f"pack_{idx}")
        lic = pack.get("license")
        if lic != "CC0-1.0":
            violations.append(f"{ploc} ({pid}): license must be 'CC0-1.0', got {lic!r}")
        else:
            packs_cc0 += 1

        for field_name in ("title", "author", "url", "license_url"):
            fval = pack.get(field_name)
            if not isinstance(fval, str) or not fval.strip():
                violations.append(f"{ploc} ({pid}): '{field_name}' must be a non-empty string")
            elif not all(ord(ch) < 128 for ch in fval):
                violations.append(f"{ploc} ({pid}): '{field_name}' must be pure ASCII")

        psha = pack.get("sha256")
        if isinstance(psha, str) and HEX64_RE.match(psha):
            if assets_md_text and psha in assets_md_text:
                sha_cited += 1
            elif assets_md_path.is_file():
                violations.append(
                    f"{ploc} ({pid}): pack sha256 {psha} not cited in docs/arena/ASSETS.md"
                )
        else:
            violations.append(f"{ploc} ({pid}): invalid pack sha256 {psha!r}")

    passed = len(violations) == 0
    metrics = {
        "license_file_present": license_path.is_file(),
        "assets_md_present": assets_md_path.is_file(),
        "packs_cc0": f"{packs_cc0}/{len(packs)}",
        "pack_sha256_cited_in_assets_md": f"{sha_cited}/{len(packs)}",
    }
    summary = (
        f"license=CC0-1.0 packs={packs_cc0}/{len(packs)} sha256_cited={sha_cited}/{len(packs)} credits_ascii=True"
        if passed
        else f"{len(violations)} license/attribution violation(s)"
    )
    return CheckOutcome("C3", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations, warnings)


def _repo_secret_bytes(root: Path) -> list[bytes]:
    found: list[bytes] = []
    salt_rel = Path("data") / "worlds" / "judge" / ("SA" + "LT")
    salt_file = root / salt_rel
    if salt_file.is_file():
        try:
            raw = salt_file.read_bytes().strip()
            if len(raw) >= 8:
                found.append(raw)
        except OSError:
            pass
    for env_name in SECRET_ENV_NAMES[:4]:
        val = os.environ.get(env_name, "").strip()
        if len(val) >= 8:
            found.append(val.encode("utf-8"))
    return found


def _scan_manifest_leaks(manifest: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if "leaking_sprite_employee" not in manifest:
        violations.append("manifest missing required key 'leaking_sprite_employee': null")
    else:
        leak_emp = manifest["leaking_sprite_employee"]
        if leak_emp is not None:
            emp_note = (
                f" (employee ID {leak_emp!r})"
                if isinstance(leak_emp, str) and EMP_ID_RE.match(leak_emp)
                else f" ({leak_emp!r})"
            )
            violations.append(
                f"manifest.leaking_sprite_employee must be None, got non-null value{emp_note}"
            )

    def _walk(node: Any, loc: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                ks = str(k)
                cloc = f"{loc}.{ks}"
                if ks == "leaking_sprite_employee" and loc != "manifest" and v is not None:
                    violations.append(f"{cloc}: pre-end leaking_sprite_employee={v!r}")
                elif ks in PRE_END_SPRITE_LEAK_KEYS and v not in (None, False, ""):
                    violations.append(f"{cloc}: pre-end hidden-truth field {ks}={v!r}")
                _walk(v, cloc)
        elif isinstance(node, list):
            for idx, item in enumerate(node):
                _walk(item, f"{loc}[{idx}]")

    _walk(manifest, "manifest")
    return violations


def _check_python_file_hygiene(py_path: Path, rel_label: str, forbid_hash_char: bool) -> list[str]:
    violations: list[str] = []
    try:
        src = py_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"{rel_label}: unreadable UTF-8 ({exc})"]

    if EM_DASH in src or EN_DASH in src:
        violations.append(f"{rel_label}: contains forbidden em/en-dash")
    if not all(ord(ch) < 128 for ch in src):
        violations.append(f"{rel_label}: contains non-ASCII character (ord >= 128)")
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except tokenize.TokenError as exc:
        violations.append(f"{rel_label}: tokenize error ({exc})")
        tokens = []
    comment_lines = [tok.start[0] for tok in tokens if tok.type == tokenize.COMMENT]
    if comment_lines:
        violations.append(
            f"{rel_label}: contains {len(comment_lines)} Python comment(s) (first at line {comment_lines[0]})"
        )
    elif forbid_hash_char and HASH_CHAR in src:
        violations.append(f"{rel_label}: contains literal '{HASH_CHAR}' character")
    return violations


def _run_git(root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_protected_paths(root: Path, base_ref: str | None = None) -> list[str]:
    violations: list[str] = []
    rules_path = root / "canary" / "rules.py"
    if rules_path.is_file():
        try:
            rules_txt = rules_path.read_text(encoding="utf-8")
        except OSError as exc:
            violations.append(f"canary/rules.py: unreadable ({exc})")
            rules_txt = ""
        if rules_txt and 'TIERS_VERSION = "v1.4"' not in rules_txt:
            violations.append('canary/rules.py: missing frozen TIERS_VERSION = "v1.4"')

    if not (root / ".git").exists():
        return violations

    resolved_base: str | None = None
    if base_ref is not None:
        proc = _run_git(root, ["rev-parse", "--verify", f"{base_ref}^{{commit}}"])
        if proc is None or proc.returncode != 0:
            return [f"explicit --base-ref '{base_ref}' could not be resolved"]
        resolved_base = base_ref
    else:
        for candidate in DEFAULT_BASE_CANDIDATES:
            proc = _run_git(root, ["rev-parse", "--verify", f"{candidate}^{{commit}}"])
            if proc is not None and proc.returncode == 0:
                resolved_base = candidate
                break

    touched: dict[str, set[str]] = {}
    if resolved_base is not None:
        mb_proc = _run_git(root, ["merge-base", resolved_base, "HEAD"])
        diff_base = (
            mb_proc.stdout.strip()
            if (mb_proc is not None and mb_proc.returncode == 0 and mb_proc.stdout.strip())
            else resolved_base
        )
        c_proc = _run_git(root, ["diff", "--name-only", f"{diff_base}..HEAD"])
        if c_proc is not None and c_proc.returncode == 0:
            for line in c_proc.stdout.splitlines():
                p = line.strip()
                if p and is_protected_path(p):
                    touched.setdefault(p, set()).add(f"committed vs {resolved_base}")

    for label, git_args in (
        ("staged", ["diff", "--name-only", "--cached"]),
        ("worktree", ["diff", "--name-only"]),
        (
            "untracked",
            ["ls-files", "--others", "--exclude-standard", "--", *PROTECTED_GIT_TARGETS],
        ),
    ):
        proc = _run_git(root, git_args)
        if proc is not None and proc.returncode == 0:
            for line in proc.stdout.splitlines():
                p = line.strip()
                if p and is_protected_path(p):
                    touched.setdefault(p, set()).add(label)

    for path_key in sorted(touched):
        reasons = ", ".join(sorted(touched[path_key]))
        violations.append(f"protected path touched: {path_key} ({reasons})")
    return violations


def check_pre_end_zero_leak_and_hygiene(
    root: Path,
    strict: bool = False,
    base_ref: str | None = None,
) -> CheckOutcome:
    name = "Check 4: Pre-End Zero-Leak & Hygiene"
    arena_dir = root / "docs" / "arena"
    manifest, load_errors = _load_manifest(root)
    if manifest is None:
        return CheckOutcome(
            "C4",
            name,
            False,
            "FAIL",
            "sprite_pack_manifest.json missing or invalid",
            violations=load_errors,
        )

    violations: list[str] = _scan_manifest_leaks(manifest)
    warnings: list[str] = []
    repo_secrets = _repo_secret_bytes(root)

    arena_files_scanned = 0
    ascii_files_checked = 0

    if not arena_dir.is_dir():
        violations.append("missing directory: docs/arena")
    else:
        for fp in sorted(arena_dir.rglob("*")):
            if not fp.is_file():
                continue
            rel_arena = fp.relative_to(arena_dir).as_posix()
            parts = fp.relative_to(arena_dir).parts
            if any(part in {"node_modules", "__pycache__"} for part in parts):
                continue
            if fp.suffix.lower() in {".pyc", ".pyo"}:
                continue

            rel_root = f"docs/arena/{rel_arena}"
            arena_files_scanned += 1

            fname = fp.name
            if fname in FORBIDDEN_SECRET_FILENAMES or (
                fname.startswith(".env.") and fname not in ALLOWED_ENV_TEMPLATES
            ):
                violations.append(f"{rel_root}: forbidden secret file present")
                continue
            if fname.endswith(".world.json"):
                violations.append(f"{rel_root}: forbidden .world.json file present")
                continue

            try:
                raw_bytes = fp.read_bytes()
            except OSError as exc:
                violations.append(f"{rel_root}: unreadable file ({exc})")
                continue

            for sb in repo_secrets:
                if sb in raw_bytes:
                    violations.append(f"{rel_root}: contains raw repository secret bytes")
                    break

            suffix = fp.suffix.lower()
            if suffix in BINARY_ASSET_SUFFIXES or b"\x00" in raw_bytes:
                continue

            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError as exc:
                violations.append(f"{rel_root}: invalid UTF-8 at byte {exc.start}")
                continue

            for kind, rx in CREDENTIAL_PATTERNS:
                match = rx.search(text)
                if match is not None:
                    prefix = match.group(0)[:6] + "..."
                    violations.append(f"{rel_root}: credential leak ({kind}: {prefix})")

            if SECRET_ASSIGN_RE.search(text) or DOTENV_SECRET_RE.search(text):
                violations.append(f"{rel_root}: literal secret assignment detected")
            elif suffix in STRICT_DOC_SUFFIXES and STRICT_LITERAL_NAMES_RE.search(text):
                hit = STRICT_LITERAL_NAMES_RE.search(text)
                tok = hit.group(0) if hit else "secret_identifier"
                violations.append(f"{rel_root}: forbidden secret env-var/path literal '{tok}'")

            is_mirrored_engine = rel_arena.startswith("py/canary/")
            if not is_mirrored_engine:
                ascii_files_checked += 1
                if EM_DASH in text:
                    violations.append(f"{rel_root}: contains em-dash (U+2014)")
                if EN_DASH in text:
                    violations.append(f"{rel_root}: contains en-dash (U+2013)")
                if not all(ord(ch) < 128 for ch in text):
                    for lineno, line in enumerate(text.splitlines(), 1):
                        if not line.isascii():
                            violations.append(
                                f"{rel_root}:{lineno}: non-ASCII character (ord >= 128)"
                            )
                            break

    py_checked = 0
    for rel_py in OWNED_PYTHON_REL_PATHS:
        candidate = root / rel_py
        if candidate.is_file():
            py_checked += 1
            violations.extend(
                _check_python_file_hygiene(
                    candidate,
                    rel_py,
                    forbid_hash_char=(rel_py in STRICT_NO_HASH_REL_PATHS),
                )
            )

    if py_checked == 0 and SELF_PATH.is_file():
        py_checked += 1
        violations.extend(
            _check_python_file_hygiene(
                SELF_PATH,
                "scripts/verify_arena_assets.py",
                forbid_hash_char=True,
            )
        )

    prot_violations = _check_protected_paths(root, base_ref=base_ref)
    violations.extend(prot_violations)

    passed = len(violations) == 0
    metrics = {
        "leaking_sprite_employee": manifest.get("leaking_sprite_employee"),
        "arena_files_scanned": arena_files_scanned,
        "ascii_files_checked": ascii_files_checked,
        "python_files_hygiene_checked": py_checked,
        "protected_path_violations": len(prot_violations),
    }
    summary = (
        f"leaking_sprite_employee=None arena_scanned={arena_files_scanned} "
        f"ascii_checked={ascii_files_checked} py_zero_comments={py_checked} protected_touched=0"
        if passed
        else f"{len(violations)} leak/hygiene/protected-path violation(s)"
    )
    return CheckOutcome("C4", name, passed, "PASS" if passed else "FAIL", summary, metrics, violations, warnings)


def verify_arena_assets(
    root: Path = ROOT,
    strict: bool = False,
    base_ref: str | None = None,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    resolved_root = root.resolve()
    checks = [
        check_png_ihdr_and_sha256(resolved_root, strict=strict),
        check_sprite_coordinates_and_bounds(resolved_root, strict=strict),
        check_cc0_license_and_attribution(resolved_root, strict=strict),
        check_pre_end_zero_leak_and_hygiene(resolved_root, strict=strict, base_ref=base_ref),
    ]
    if strict:
        for chk in checks:
            if chk.warnings and chk.passed:
                chk.violations.extend(chk.warnings)
                chk.passed = False
                chk.status = "FAIL"

    elapsed_s = round(time.perf_counter() - t0, 4)
    passed = all(c.passed for c in checks)
    return {
        "passed": passed,
        "status": "PASS" if passed else "FAIL",
        "strict": strict,
        "root": str(resolved_root),
        "elapsed_s": elapsed_s,
        "live_api_calls": 0,
        "checks": [asdict(c) for c in checks],
    }


def format_report(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for chk in report["checks"]:
        lines.append(f"[{chk['status']}] {chk['name']}: {chk['summary']}")
        for v in chk["violations"]:
            lines.append(f"  - {v}")
        for w in chk.get("warnings", []):
            if w not in chk["violations"]:
                lines.append(f"  ! {w}")
    passed_count = sum(1 for c in report["checks"] if c["passed"])
    total_count = len(report["checks"])
    lines.append(
        f"{report['status']}: {passed_count}/{total_count} checks passed in {report['elapsed_s']:.3f}s"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Verify Canary Arena pixel-art PNG IHDR/SHA-256, sprite bounds, CC0-1.0 attribution, and zero-leak hygiene."
    )
    ap.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Repository or bundle root directory to verify",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON report to stdout",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Run strict verification mode (promote warnings to failures)",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="Run CI check mode and exit 0 on PASS, 1 on FAIL",
    )
    ap.add_argument(
        "--base-ref",
        default=None,
        help="Optional git base ref for protected-path verification",
    )
    ap.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional file path to write JSON report",
    )
    args = ap.parse_args(argv)

    report = verify_arena_assets(
        root=args.root,
        strict=args.strict,
        base_ref=args.base_ref,
    )
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
