from __future__ import annotations

import ast
import base64
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tokenize

from tests.test_outthink_assets_qa import (
    DATA_URI_PREFIX,
    PNG_SIGNATURE,
    REQUIRED_SPRITE_KEYS,
    assert_region_has_nonblank_pixels,
    decode_png_rgba_zlib,
    parse_png_structure,
    parse_window_outthink_assets,
)

ROOT = Path(__file__).resolve().parents[1]
ASSETS_MD_PATH = ROOT / "docs" / "demo" / "ASSETS.md"
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
ASSETS_DIR = DEMO_DIR / "assets"
SPRITES_DIR = ASSETS_DIR / "sprites"
MANIFEST_JS_PATH = ASSETS_DIR / "manifest.js"
SCENE_JS_PATH = DEMO_DIR / "scene.js"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)

SCENE_EXTRA_KEYS: tuple[str, ...] = (
    "window_night",
    "door",
    "lamp",
    "mug",
    "plant",
)

SCENE_JS_EXPECTED_KEYS: tuple[str, ...] = (
    "floor_tile",
    "wall_tile",
    "window_night",
    "door",
    "desk",
    "chair",
    "evidence_board",
    "filing_cabinet",
    "terminal",
    "server_rack",
    "lamp",
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
    "icon_correct",
    "icon_wrong",
)

ALL_39_SPRITE_KEYS: tuple[str, ...] = REQUIRED_SPRITE_KEYS + SCENE_EXTRA_KEYS
SUSPECT_KEYS: tuple[str, ...] = tuple(f"suspect_{idx}" for idx in range(8))
AGENT_KEYS: tuple[str, ...] = (
    "agent_minimal",
    "agent_low",
    "agent_medium",
    "agent_high",
    "agent_xhigh",
)
ICON_KEYS: tuple[str, ...] = (
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


def _load_manifest() -> dict[str, object]:
    assert MANIFEST_JS_PATH.is_file(), f"Missing manifest.js at {MANIFEST_JS_PATH}"
    raw_js = MANIFEST_JS_PATH.read_text(encoding="utf-8")
    return parse_window_outthink_assets(raw_js)


def _parse_assets_md_pack_summary() -> dict[str, dict[str, str]]:
    md_text = ASSETS_MD_PATH.read_text(encoding="utf-8")
    packs_by_id: dict[str, dict[str, str]] = {}
    for line in md_text.splitlines():
        sline = line.strip()
        if not sline.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in sline.strip("|").split("|")]
        if len(cells) < 5:
            continue
        pack_id, pack_name, author, lic, source_url = cells[:5]
        if pack_id.lower() in ("pack id", "---") or set(pack_id) <= {"-", ":"}:
            continue
        if source_url.startswith("https://opengameart.org/content/"):
            packs_by_id[pack_id] = {
                "id": pack_id,
                "name": pack_name,
                "author": author,
                "license": lic,
                "url": source_url,
            }
    return packs_by_id


def _assert_no_unquoted_js_comments(js_src: str) -> None:
    i = 0
    n = len(js_src)
    in_str: str | None = None
    while i < n:
        ch = js_src[i]
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
        if ch == "/" and i + 1 < n and js_src[i + 1] in ("/", "*"):
            raise AssertionError(f"Forbidden JS comment token at offset {i} in manifest.js")
        i += 1


def test_all_39_sprite_keys_and_scene_compatibility() -> None:
    assert len(ALL_39_SPRITE_KEYS) == 39
    assert len(set(ALL_39_SPRITE_KEYS)) == 39
    assert set(SCENE_JS_EXPECTED_KEYS).issubset(set(ALL_39_SPRITE_KEYS))

    manifest = _load_manifest()
    assert manifest.get("version") == 1

    sprites = manifest.get("sprites")
    assert isinstance(sprites, dict)
    assert set(sprites.keys()) == set(ALL_39_SPRITE_KEYS)

    if SCENE_JS_PATH.is_file():
        scene_src = SCENE_JS_PATH.read_text(encoding="utf-8")
        arr_match = re.search(r"SPRITE_KEYS\s*=\s*\[([^\]]+)\]", scene_src)
        assert arr_match is not None
        parsed_scene_keys = re.findall(r'"([a-z0-9_]+)"', arr_match.group(1))
        assert parsed_scene_keys
        assert set(parsed_scene_keys).issubset(set(sprites.keys()))

    on_disk_pngs = sorted(p.name for p in SPRITES_DIR.glob("*.png"))
    expected_pngs = sorted(f"{key}.png" for key in ALL_39_SPRITE_KEYS)
    assert on_disk_pngs == expected_pngs

    for key in ALL_39_SPRITE_KEYS:
        entry = sprites[key]
        assert isinstance(entry, dict)
        assert entry.get("path") == f"assets/sprites/{key}.png"
        png_file = SPRITES_DIR / f"{key}.png"
        raw = png_file.read_bytes()

        info = parse_png_structure(raw)
        assert info["bit_depth"] == 8, f"{key}: expected 8-bit PNG, got {info['bit_depth']}"
        assert info["color_type"] == 6, f"{key}: expected RGBA color_type 6, got {info['color_type']}"
        assert info["interlace"] == 0, f"{key}: expected non-interlaced PNG, got {info['interlace']}"

        w, h, pixels = decode_png_rgba_zlib(raw)
        frames = entry.get("frames")
        fw = entry.get("frameWidth")
        fh = entry.get("frameHeight")
        assert isinstance(frames, int) and frames >= 1
        assert isinstance(fw, int) and fw >= 16
        assert isinstance(fh, int) and fh >= 16
        assert entry.get("width") == w
        assert entry.get("height") == h
        assert entry.get("x") == 0
        assert entry.get("y") == 0
        assert w == frames * fw, f"{key}: width {w} != frames({frames}) * frameWidth({fw})"
        assert h == fh, f"{key}: height {h} != frameHeight({fh})"

        for f_idx in range(frames):
            assert_region_has_nonblank_pixels(
                pixels,
                w,
                h,
                f_idx * fw,
                0,
                fw,
                fh,
                f"{key} frame[{f_idx}]",
            )

    total_bytes = sum(p.stat().st_size for p in ASSETS_DIR.rglob("*") if p.is_file())
    assert 0 < total_bytes < 1024 * 1024


def test_suspects_agents_pods_and_icons_have_distinct_png_payloads() -> None:
    manifest = _load_manifest()
    sprites = manifest["sprites"]
    assert isinstance(sprites, dict)

    suspect_bytes = [(SPRITES_DIR / f"{k}.png").read_bytes() for k in SUSPECT_KEYS]
    suspect_uris = [str(sprites[k]["dataUri"]) for k in SUSPECT_KEYS]
    suspect_pixels = [tuple(decode_png_rgba_zlib(b)[2]) for b in suspect_bytes]
    assert len(set(suspect_bytes)) == 8
    assert len(set(suspect_uris)) == 8
    assert len(set(suspect_pixels)) == 8

    detective_bytes = (SPRITES_DIR / "detective.png").read_bytes()
    assert detective_bytes not in set(suspect_bytes)

    agent_bytes = [(SPRITES_DIR / f"{k}.png").read_bytes() for k in AGENT_KEYS]
    agent_uris = [str(sprites[k]["dataUri"]) for k in AGENT_KEYS]
    agent_pixels = [tuple(decode_png_rgba_zlib(b)[2]) for b in agent_bytes]
    assert len(set(agent_bytes)) == 5
    assert len(set(agent_uris)) == 5
    assert len(set(agent_pixels)) == 5

    pod_locked_bytes = (SPRITES_DIR / "pod_locked.png").read_bytes()
    pod_unlocked_bytes = (SPRITES_DIR / "pod_unlocked.png").read_bytes()
    assert pod_locked_bytes != pod_unlocked_bytes

    icon_bytes = [(SPRITES_DIR / f"{k}.png").read_bytes() for k in ICON_KEYS]
    assert len(set(icon_bytes)) == len(ICON_KEYS)


def _parse_assets_md_coverage_map(md_text: str) -> dict[str, set[str]]:
    coverage: dict[str, set[str]] = {}
    range_re = re.compile(r"`([a-z_]+_)(\d+)`\.\.`\1(\d+)`")
    token_re = re.compile(r"`([a-z0-9_-]+)`")
    in_coverage = False
    for line in md_text.splitlines():
        sline = line.strip()
        if "Sprite Manifest Coverage" in sline:
            in_coverage = True
            continue
        if not in_coverage or not sline.startswith("|"):
            continue
        cells = [c.strip() for c in sline.strip("|").split("|")]
        if len(cells) < 3:
            continue
        keys_cell, packs_cell = cells[1], cells[2]
        if keys_cell.lower() == "sprite keys" or set(keys_cell) <= {"-", ":", " "}:
            continue
        row_packs = set(token_re.findall(packs_cell))
        row_keys: set[str] = set(token_re.findall(keys_cell))
        for prefix, start_s, end_s in range_re.findall(keys_cell):
            for num in range(int(start_s), int(end_s) + 1):
                row_keys.add(f"{prefix}{num}")
        for k in row_keys:
            coverage.setdefault(k, set()).update(row_packs)
    return coverage


def test_every_sprite_pack_cross_references_assets_md() -> None:
    md_packs = _parse_assets_md_pack_summary()
    assert len(md_packs) == 11

    md_text = ASSETS_MD_PATH.read_text(encoding="utf-8")
    coverage_map = _parse_assets_md_coverage_map(md_text)
    assert set(coverage_map.keys()) == set(ALL_39_SPRITE_KEYS)

    manifest = _load_manifest()
    packs_list = manifest.get("packs")
    assert isinstance(packs_list, list) and len(packs_list) == 11

    manifest_packs_by_id: dict[str, dict[str, object]] = {}
    for pack in packs_list:
        assert isinstance(pack, dict)
        pid = str(pack.get("id") or "").strip()
        assert pid in md_packs, f"Pack {pid!r} in manifest.js missing from docs/demo/ASSETS.md"
        md_entry = md_packs[pid]
        assert pack.get("name") == md_entry["name"]
        assert pack.get("author") == md_entry["author"]
        assert pack.get("license") == "CC0-1.0"
        assert md_entry["license"] == "CC0-1.0"
        assert pack.get("url") == md_entry["url"]
        manifest_packs_by_id[pid] = pack

    sprites = manifest["sprites"]
    assert isinstance(sprites, dict)
    used_packs: set[str] = set()
    for key in ALL_39_SPRITE_KEYS:
        entry = sprites[key]
        assert isinstance(entry, dict)
        pack_id = entry.get("pack")
        assert isinstance(pack_id, str) and pack_id in manifest_packs_by_id
        assert pack_id in md_packs
        assert pack_id in coverage_map[key], (
            f"Sprite {key!r} pack {pack_id!r} not in ASSETS.md coverage packs {sorted(coverage_map[key])}"
        )
        used_packs.add(pack_id)

    assert used_packs == set(md_packs.keys())


def test_manifest_js_works_offline_via_data_uri(tmp_path: Path) -> None:
    raw_js = MANIFEST_JS_PATH.read_text(encoding="utf-8")
    assert EM_DASH not in raw_js
    assert EN_DASH not in raw_js
    _assert_no_unquoted_js_comments(raw_js)

    isolated_js = tmp_path / "manifest.js"
    isolated_js.write_text(raw_js, encoding="utf-8")
    assert not (tmp_path / "sprites").exists()

    offline_manifest = parse_window_outthink_assets(isolated_js.read_text(encoding="utf-8"))
    sprites = offline_manifest["sprites"]
    assert isinstance(sprites, dict)

    for key in ALL_39_SPRITE_KEYS:
        entry = sprites[key]
        assert isinstance(entry, dict)
        data_uri = entry.get("dataUri")
        assert isinstance(data_uri, str) and data_uri.startswith(DATA_URI_PREFIX)
        decoded = base64.b64decode(data_uri[len(DATA_URI_PREFIX) :], validate=True)
        assert decoded[:8] == PNG_SIGNATURE
        assert decoded == (SPRITES_DIR / f"{key}.png").read_bytes()
        w, h, _ = decode_png_rgba_zlib(decoded)
        assert (w, h) == (entry["width"], entry["height"])

    node_bin = shutil.which("node")
    if node_bin is not None:
        script = (
            "const fs = require('fs'); const vm = require('vm');"
            "const ctx = { window: {} }; ctx.globalThis = ctx;"
            f"vm.runInNewContext(fs.readFileSync({json.dumps(str(isolated_js))}, 'utf8'), ctx);"
            "const a = ctx.window.OUTTHINK_ASSETS;"
            "const keys = Object.keys(a.sprites);"
            "const ok = keys.every(k => Buffer.from(a.sprites[k].dataUri.split(',')[1], 'base64').subarray(0, 4).toString('hex') === '89504e47');"
            "console.log(JSON.stringify({ version: a.version, count: keys.length, ok }));"
        )
        proc = subprocess.run([node_bin, "-e", script], cwd=tmp_path, check=True, capture_output=True, text=True)
        payload = json.loads(proc.stdout.strip())
        assert payload == {"version": 1, "count": 39, "ok": True}


def test_file_hygiene_zero_comments_dashes_and_network_imports() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")

    assert EM_DASH not in src
    assert EN_DASH not in src
    assert HASH_CHAR not in src

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comment_tokens = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comment_tokens == []

    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = ("google", "genai", "atlas_gemini", "gateway", "httpx", "requests", "urllib", "socket", "aiohttp")
    for mod in imported:
        assert not any(term in mod for term in forbidden), f"Forbidden import {mod!r}"
