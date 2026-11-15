from __future__ import annotations

import hashlib
import io
import json
import struct
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS_MD = ROOT / "docs" / "arena" / "ASSETS.md"
ASSETS_DIR = ROOT / "docs" / "arena" / "assets"
MANIFEST_JSON = ASSETS_DIR / "sprite_pack_manifest.json"
LICENSE_TXT = ASSETS_DIR / "LICENSE-CC0-1.0.txt"
SELF_PATH = Path(__file__).resolve()

EM = "\u2014"
EN = "\u2013"
HASH_CH = chr(35)
PNG_SIG = b"\x89PNG\r\n\x1a\n"
MAX_BUDGET_BYTES = 15_000_000


def _png_dims(data: bytes) -> tuple[int, int]:
    assert data[:8] == PNG_SIG
    assert data[12:16] == b"IHDR"
    w, h = struct.unpack(">II", data[16:24])
    return w, h


def test_assets_markdown_and_cc0_license_provenance() -> None:
    assert ASSETS_MD.is_file()
    assert LICENSE_TXT.is_file()
    md = ASSETS_MD.read_text(encoding="utf-8")
    lic = LICENSE_TXT.read_text(encoding="utf-8")
    for text in (md, lic):
        assert EM not in text
        assert EN not in text
        assert all(ord(ch) < 128 for ch in text)
    for required in (
        "https://kenney.nl/assets/roguelike-indoors",
        "https://kenney.nl/assets/roguelike-characters",
        "https://kenney.nl/assets/rpg-urban-pack",
        "https://kenney.nl/assets/tiny-town",
        "https://kenney.nl/assets/ui-pack-pixel-adventure",
        "https://creativecommons.org/publicdomain/zero/1.0/",
        "CC0 1.0",
        "Kenney Vleugels",
        "assetCredits",
        "leaking_sprite_employee",
    ):
        assert required in md
    assert "https://creativecommons.org/publicdomain/zero/1.0/" in lic


def test_sprite_pack_manifest_contract_and_png_integrity() -> None:
    assert MANIFEST_JSON.is_file()
    raw = MANIFEST_JSON.read_text(encoding="utf-8")
    assert EM not in raw and EN not in raw
    assert all(ord(ch) < 128 for ch in raw)
    manifest = json.loads(raw)

    assert manifest["schema_version"] == "canary.arena.sprite_pack_manifest.v1"
    assert manifest["baseUrl"] == "./assets"
    assert manifest["tileSheet"] == "kenney_roguelike_indoor.png"
    assert manifest["charSheet"] == "kenney_roguelike_char.png"
    assert manifest["frameW"] == 16
    assert manifest["frameH"] == 16
    assert "Kenney" in manifest["creditsText"]
    assert "CC0" in manifest["creditsText"]
    assert manifest["attribution"]["license"] == "CC0-1.0"
    assert manifest["leaking_sprite_employee"] is None

    for banned in ("CANARY_WORLD_SECRET", '"true_mole"', '"mole": "e'):
        assert banned not in raw

    for key in ("desk", "employee", "chair", "plant", "meeting_table", "coffee_bar", "server_rack"):
        rect = manifest["sprites"][key]
        assert rect["w"] == 16 and rect["h"] == 16
        assert rect["x"] >= 0 and rect["y"] >= 0

    for item_key in ("canary_doc_A", "canary_doc_B", "canary_doc_C"):
        rect = manifest["item_sprites"][item_key]
        assert rect["w"] == 16 and rect["h"] == 16

    all_pngs = sorted(ASSETS_DIR.rglob("*.png"))
    assert len(all_pngs) == 12
    total_bytes = sum(p.stat().st_size for p in all_pngs)
    assert total_bytes == manifest["total_png_bytes"]
    assert 0 < total_bytes < MAX_BUDGET_BYTES
    assert total_bytes < 1_000_000

    for pack in manifest["packs"]:
        rel_path = ROOT / pack["file"]
        if pack["file"].endswith(".png"):
            assert rel_path.is_file()
            data = rel_path.read_bytes()
            assert len(data) == pack["bytes"]
            assert hashlib.sha256(data).hexdigest() == pack["sha256"]
            w, h = _png_dims(data)
            assert (w, h) == (pack["width"], pack["height"])
        else:
            assert rel_path.is_dir()
            badges = sorted(rel_path.glob("*.png"))
            assert len(badges) == 8
            assert sum(b.stat().st_size for b in badges) == pack["bytes"]
            assert hashlib.sha256(badges[0].read_bytes()).hexdigest() == pack["sha256"]
            for b in badges:
                assert _png_dims(b.read_bytes()) == (16, 16)


def test_self_hygiene_zero_comments_and_ascii() -> None:
    src = SELF_PATH.read_text(encoding="utf-8")
    assert EM not in src and EN not in src
    assert HASH_CH not in src
    assert all(ord(ch) < 128 for ch in src)
    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    assert not [t for t in tokens if t.type == tokenize.COMMENT]
