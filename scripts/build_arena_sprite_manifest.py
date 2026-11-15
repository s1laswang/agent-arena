"""Deterministic Canary Arena 40-employee CC0 sprite manifest and 40x24 office map builder.

    python scripts/build_arena_sprite_manifest.py --write
    python scripts/build_arena_sprite_manifest.py --check
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from canary.rules import TIERS, TIERS_VERSION

MAX_JSON_BYTES = 120_000
GRID_WIDTH = 40
GRID_HEIGHT = 24
TILE_SIZE = 16
CHAR_STRIDE = 17
INDOOR_STRIDE = 17
N_EMPLOYEES_MAX = 40
MD_H = chr(35)

PUBLIC_DEPARTMENTS: tuple[str, ...] = (
    "Engineering",
    "Finance",
    "Sales",
    "Legal",
    "Research",
)

CANONICAL_ROLES: dict[str, tuple[str, str, str]] = {
    "Engineering": ("engineer", "senior engineer", "tech lead"),
    "Finance": ("analyst", "controller", "accountant"),
    "Sales": ("account exec", "sales manager", "sales ops"),
    "Legal": ("counsel", "paralegal", "compliance officer"),
    "Research": ("scientist", "research lead", "lab analyst"),
}

ALLOWED_PUBLIC_EMPLOYEE_KEYS: frozenset[str] = frozenset(
    {"id", "name", "dept", "role", "clearance"}
)

CREDITS_TEXT = (
    "Pixel art and tiles: Kenney Vleugels (Kenney.nl) - "
    "Roguelike Indoors, Roguelike Characters, RPG Urban Pack, Tiny Town, "
    "UI Pack Pixel Adventure (CC0 1.0 Public Domain)."
)

DEPT_STYLE: dict[str, dict[str, Any]] = {
    "Engineering": {
        "index": 0,
        "code": "ENG",
        "glyph": "E",
        "accent_rgb": "rgb(56, 152, 236)",
        "floor_a_rgb": "rgb(26, 36, 52)",
        "floor_b_rgb": "rgb(30, 41, 58)",
        "badge_shape": "hex",
        "outfit_style": "hoodie",
        "bounds": {"x": 1, "y": 2, "w": 12, "h": 7},
        "doorways": [[5, 8], [6, 8], [12, 5]],
    },
    "Research": {
        "index": 4,
        "code": "RSC",
        "glyph": "R",
        "accent_rgb": "rgb(46, 196, 198)",
        "floor_a_rgb": "rgb(24, 40, 48)",
        "floor_b_rgb": "rgb(28, 45, 54)",
        "badge_shape": "square",
        "outfit_style": "labcoat",
        "bounds": {"x": 14, "y": 2, "w": 12, "h": 7},
        "doorways": [[19, 8], [20, 8], [14, 5], [25, 5]],
    },
    "Finance": {
        "index": 1,
        "code": "FIN",
        "glyph": "F",
        "accent_rgb": "rgb(52, 188, 122)",
        "floor_a_rgb": "rgb(24, 40, 36)",
        "floor_b_rgb": "rgb(28, 46, 41)",
        "badge_shape": "diamond",
        "outfit_style": "blazer",
        "bounds": {"x": 27, "y": 2, "w": 12, "h": 7},
        "doorways": [[32, 8], [33, 8], [27, 5]],
    },
    "Sales": {
        "index": 2,
        "code": "SLS",
        "glyph": "S",
        "accent_rgb": "rgb(238, 146, 54)",
        "floor_a_rgb": "rgb(42, 34, 28)",
        "floor_b_rgb": "rgb(48, 39, 32)",
        "badge_shape": "circle",
        "outfit_style": "vest",
        "bounds": {"x": 1, "y": 11, "w": 12, "h": 6},
        "doorways": [[6, 11], [7, 11], [6, 16], [7, 16], [12, 13]],
    },
    "Legal": {
        "index": 3,
        "code": "LGL",
        "glyph": "L",
        "accent_rgb": "rgb(166, 110, 228)",
        "floor_a_rgb": "rgb(36, 30, 48)",
        "floor_b_rgb": "rgb(42, 35, 55)",
        "badge_shape": "shield",
        "outfit_style": "turtleneck",
        "bounds": {"x": 14, "y": 11, "w": 12, "h": 6},
        "doorways": [[19, 11], [20, 11], [19, 16], [20, 16], [14, 13], [25, 13]],
    },
}

FACILITY_ZONES: tuple[dict[str, Any], ...] = (
    {
        "id": "coffee_corner",
        "name": "Coffee Corner",
        "kind": "facility",
        "x": 27,
        "y": 11,
        "w": 12,
        "h": 6,
        "doorways": [[32, 11], [33, 11], [32, 16], [33, 16], [27, 13], [27, 14]],
        "accent": "rgb(218, 162, 92)",
        "floorA": "rgb(48, 38, 30)",
        "floorB": "rgb(55, 44, 35)",
        "waypoints": [[30, 13], [31, 13], [31, 14], [32, 14], [35, 13], [36, 14]],
    },
    {
        "id": "meeting_room_a",
        "name": "Meeting Room A",
        "kind": "facility",
        "x": 1,
        "y": 18,
        "w": 9,
        "h": 5,
        "doorways": [[4, 18], [5, 18]],
        "accent": "rgb(102, 168, 224)",
        "floorA": "rgb(28, 36, 48)",
        "floorB": "rgb(33, 42, 56)",
        "waypoints": [[4, 19], [5, 19], [4, 21], [5, 21]],
    },
    {
        "id": "meeting_room_b",
        "name": "Meeting Room B",
        "kind": "facility",
        "x": 11,
        "y": 18,
        "w": 9,
        "h": 5,
        "doorways": [[14, 18], [15, 18]],
        "accent": "rgb(120, 184, 164)",
        "floorA": "rgb(28, 38, 44)",
        "floorB": "rgb(33, 44, 50)",
        "waypoints": [[14, 19], [15, 19], [14, 21], [15, 21]],
    },
    {
        "id": "security_desk",
        "name": "Security Desk",
        "kind": "facility",
        "x": 21,
        "y": 18,
        "w": 9,
        "h": 5,
        "doorways": [[24, 18], [25, 18]],
        "accent": "rgb(232, 94, 94)",
        "floorA": "rgb(38, 28, 34)",
        "floorB": "rgb(44, 33, 40)",
        "waypoints": [[25, 19], [25, 21], [23, 20], [27, 20]],
    },
    {
        "id": "server_room",
        "name": "Server Room",
        "kind": "facility",
        "x": 31,
        "y": 18,
        "w": 8,
        "h": 5,
        "doorways": [[34, 18], [35, 18]],
        "accent": "rgb(72, 214, 152)",
        "floorA": "rgb(18, 28, 34)",
        "floorB": "rgb(22, 34, 40)",
        "waypoints": [[34, 19], [35, 19], [34, 20], [35, 20], [34, 21]],
    },
)

SKIN_TONES: tuple[str, ...] = (
    "rgb(244, 206, 178)",
    "rgb(228, 184, 148)",
    "rgb(198, 146, 108)",
    "rgb(162, 110, 76)",
    "rgb(122, 78, 54)",
    "rgb(236, 196, 166)",
)

HAIR_SHADES: tuple[tuple[str, str], ...] = (
    ("raven", "rgb(36, 32, 38)"),
    ("chestnut", "rgb(88, 56, 38)"),
    ("copper", "rgb(152, 98, 52)"),
    ("golden", "rgb(212, 172, 92)"),
    ("auburn", "rgb(164, 62, 48)"),
    ("slate", "rgb(72, 82, 98)"),
    ("silver", "rgb(214, 218, 226)"),
)

SHIRT_PALETTE_40: tuple[str, ...] = (
    "rgb(14, 165, 233)", "rgb(16, 185, 129)", "rgb(249, 115, 22)", "rgb(139, 92, 246)", "rgb(236, 72, 153)",
    "rgb(2, 132, 199)", "rgb(5, 150, 105)", "rgb(234, 88, 12)", "rgb(124, 58, 237)", "rgb(219, 39, 119)",
    "rgb(56, 189, 248)", "rgb(52, 211, 153)", "rgb(251, 146, 60)", "rgb(167, 139, 250)", "rgb(244, 114, 182)",
    "rgb(37, 99, 235)", "rgb(20, 184, 166)", "rgb(245, 158, 11)", "rgb(99, 102, 241)", "rgb(225, 29, 72)",
    "rgb(29, 78, 216)", "rgb(13, 148, 136)", "rgb(217, 119, 6)", "rgb(79, 70, 229)", "rgb(190, 18, 60)",
    "rgb(6, 182, 212)", "rgb(34, 197, 94)", "rgb(239, 68, 68)", "rgb(147, 51, 234)", "rgb(251, 113, 133)",
    "rgb(8, 145, 178)", "rgb(22, 163, 74)", "rgb(220, 38, 38)", "rgb(168, 85, 247)", "rgb(244, 63, 94)",
    "rgb(96, 165, 250)", "rgb(74, 222, 128)", "rgb(253, 186, 116)", "rgb(192, 132, 252)", "rgb(253, 164, 175)",
)

TROUSER_TONES: tuple[str, ...] = (
    "rgb(30, 41, 59)",
    "rgb(51, 65, 85)",
    "rgb(31, 41, 55)",
    "rgb(41, 37, 36)",
    "rgb(23, 37, 84)",
)

ACCENT_TONES: tuple[str, ...] = (
    "rgb(255, 225, 77)",
    "rgb(253, 224, 71)",
    "rgb(226, 232, 240)",
    "rgb(125, 211, 252)",
    "rgb(110, 231, 183)",
    "rgb(253, 186, 116)",
    "rgb(216, 180, 254)",
    "rgb(249, 168, 212)",
)

HAIR_STYLES: tuple[str, ...] = (
    "short_part",
    "bun",
    "curly",
    "spiky",
    "bob",
    "buzz",
    "ponytail",
    "swept",
)

ACCESSORIES: tuple[str, ...] = (
    "lanyard",
    "glasses",
    "headset",
    "tie_clip",
    "id_pin",
    "wristwatch",
    "scarf",
    "clipboard_tab",
)

HAIR_ROWS_TOP: dict[str, tuple[str, str, str]] = {
    "short_part": (".HHHHH..", ".HHHHHH.", ".HS..SH."),
    "bun":        ("..HHH...", ".HHHHHH.", ".HS..SH."),
    "curly":      (".HHHHHH.", "HHHHHHHH", "HHS..SHH"),
    "spiky":      ("H.HH.HH.", ".HHHHHH.", ".HS..SH."),
    "bob":        (".HHHHHH.", "HHHHHHHH", "HHS..SHH"),
    "buzz":       ("..HHHH..", ".HHHHHH.", ".HS..SH."),
    "ponytail":   (".HHHHH..", ".HHHHHHH", ".HS..SHH"),
    "swept":      ("..HHHHH.", ".HHHHHH.", ".HS..SH."),
}

OUTFIT_TORSO_ROWS: dict[str, tuple[str, str, str, str]] = {
    "hoodie":     (".TTTTTT.", "TTTTTTTT", "TTBTTATT", ".TTTTTT."),
    "blazer":     (".TTATTT.", "TTTATTTT", "TTBTTATT", ".TT.ATT."),
    "vest":       (".STTTTS.", "STTAATTS", "STBTTATS", ".TTTTTT."),
    "turtleneck": ("..AAAA..", ".TTTTTT.", "TTBTTTTT", ".TTTTTT."),
    "labcoat":    (".TTATTT.", "TTTAATTT", "TTBTTATT", ".TT..TT."),
}


def default_json_path(root: Path = ROOT) -> Path:
    return root / "docs" / "arena" / "data" / "sprite_manifest_40emp.json"


def default_js_path(root: Path = ROOT) -> Path:
    return root / "docs" / "arena" / "data" / "sprite_manifest_40emp.js"


def default_md_path(root: Path = ROOT) -> Path:
    return root / "docs" / "arena" / "SPRITE_CAST_40.md"


def fnv1a_32(text: str) -> int:
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def role_badge_pips(role: str) -> int:
    rl = role.lower()
    if any(k in rl for k in ("lead", "manager", "controller", "counsel")):
        return 3
    if any(k in rl for k in ("senior", "scientist", "compliance")):
        return 2
    return 1


def compute_public_employee_visual(
    emp_id: str,
    dept: str,
    role: str,
) -> dict[str, Any]:
    clean_id = str(emp_id or "e00")
    clean_dept = dept if dept in DEPT_STYLE else "Engineering"
    clean_role = str(role or "staff")
    digest = fnv1a_32(f"{clean_id}|{clean_dept}|{clean_role}")
    dstyle = DEPT_STYLE[clean_dept]
    skin = SKIN_TONES[digest % len(SKIN_TONES)]
    hair_name, hair = HAIR_SHADES[(digest >> 3) % len(HAIR_SHADES)]
    hair_style_idx = (digest >> 7) % 4
    return {
        "id": clean_id,
        "dept": clean_dept,
        "role": clean_role,
        "jacket": dstyle["accent_rgb"],
        "skin": skin,
        "hair": hair,
        "hair_name": hair_name,
        "hairStyle": hair_style_idx,
        "badgePips": role_badge_pips(clean_role),
        "visual_hash": digest,
    }


def build_sheets() -> dict[str, str]:
    return {
        "tiles": "kenney_roguelike_indoor.png",
        "indoors": "kenney_roguelike_indoor.png",
        "tileSheet": "kenney_roguelike_indoor.png",
        "characters": "kenney_roguelike_char.png",
        "chars": "kenney_roguelike_char.png",
        "charSheet": "kenney_roguelike_char.png",
        "urban": "kenney_rpg_urban_packed.png",
        "tiny_town": "kenney_tiny_town_packed.png",
    }


def build_sheet_catalog() -> dict[str, dict[str, Any]]:
    return {
        "roguelike_indoors": {
            "id": "kenney-roguelike-indoors",
            "alias": "indoors",
            "title": "Roguelike Indoors",
            "file": "kenney_roguelike_indoor.png",
            "tile_w": TILE_SIZE,
            "tile_h": TILE_SIZE,
            "margin_px": 1,
            "cols": 27,
            "rows": 18,
            "license": "CC0-1.0",
            "source_url": "https://kenney.nl/assets/roguelike-indoors",
        },
        "roguelike_characters": {
            "id": "kenney-roguelike-characters",
            "alias": "characters",
            "title": "Roguelike Characters 2.0",
            "file": "kenney_roguelike_char.png",
            "tile_w": TILE_SIZE,
            "tile_h": TILE_SIZE,
            "margin_px": 1,
            "cols": 54,
            "rows": 12,
            "license": "CC0-1.0",
            "source_url": "https://kenney.nl/assets/roguelike-characters",
        },
        "rpg_urban": {
            "id": "kenney-rpg-urban-pack",
            "alias": "urban",
            "title": "RPG Urban Pack 1.0",
            "file": "kenney_rpg_urban_packed.png",
            "tile_w": TILE_SIZE,
            "tile_h": TILE_SIZE,
            "margin_px": 0,
            "cols": 27,
            "rows": 18,
            "license": "CC0-1.0",
            "source_url": "https://kenney.nl/assets/rpg-urban-pack",
        },
        "tiny_town": {
            "id": "kenney-tiny-town",
            "alias": "tiny_town",
            "title": "Tiny Town 1.1",
            "file": "kenney_tiny_town_packed.png",
            "tile_w": TILE_SIZE,
            "tile_h": TILE_SIZE,
            "margin_px": 0,
            "cols": 12,
            "rows": 11,
            "license": "CC0-1.0",
            "source_url": "https://kenney.nl/assets/tiny-town",
        },
    }


def build_attribution() -> dict[str, Any]:
    catalog = build_sheet_catalog()
    packs = [
        {
            "id": meta["id"],
            "title": meta["title"],
            "author": "Kenney Vleugels (Kenney.nl)",
            "source_url": meta["source_url"],
            "license": "CC0-1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "file": f"docs/arena/assets/{meta['file']}",
        }
        for meta in catalog.values()
    ]
    packs.append(
        {
            "id": "kenney-ui-pack-pixel-adventure",
            "title": "UI Pack - Pixel Adventure 2.0",
            "author": "Kenney Vleugels (Kenney.nl)",
            "source_url": "https://kenney.nl/assets/ui-pack-pixel-adventure",
            "license": "CC0-1.0",
            "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
            "file": "docs/arena/assets/kenney_ui_badges/",
        }
    )
    return {
        "target_element_id": "assetCredits",
        "author": "Kenney Vleugels (Kenney.nl)",
        "author_url": "https://kenney.nl/assets",
        "license": "CC0-1.0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "paid_or_commercial_assets": False,
        "ripped_assets": False,
        "creditsText": CREDITS_TEXT,
        "text": CREDITS_TEXT,
        "packs": packs,
    }


def _indoor_sprite(col: int, row: int) -> dict[str, Any]:
    return {
        "sheet": "indoors",
        "x": col * INDOOR_STRIDE,
        "y": row * INDOOR_STRIDE,
        "w": TILE_SIZE,
        "h": TILE_SIZE,
        "col": col,
        "row": row,
        "margin": 1,
    }


def _char_sprite(col: int, row: int) -> dict[str, Any]:
    return {
        "sheet": "characters",
        "x": col * CHAR_STRIDE,
        "y": row * CHAR_STRIDE,
        "w": TILE_SIZE,
        "h": TILE_SIZE,
        "col": col,
        "row": row,
        "margin": 1,
    }


def build_sprites() -> dict[str, dict[str, Any]]:
    return {
        "desk": _indoor_sprite(8, 0),
        "meeting_table": _indoor_sprite(12, 0),
        "bistro_table": _indoor_sprite(13, 0),
        "coffee_bar": _indoor_sprite(9, 0),
        "chair": _indoor_sprite(18, 0),
        "plant": _indoor_sprite(16, 0),
        "server_rack": _indoor_sprite(14, 0),
        "security_console": _indoor_sprite(15, 0),
        "canary_printer": _indoor_sprite(17, 0),
        "doc_archive": _indoor_sprite(11, 0),
        "leak_drop": _indoor_sprite(21, 0),
        "employee": _char_sprite(0, 5),
        "employee_alt": _char_sprite(1, 5),
        "investigator": _char_sprite(2, 0),
        "canary_doc_A": _indoor_sprite(19, 0),
        "canary_doc_B": _indoor_sprite(20, 0),
        "canary_doc_C": _indoor_sprite(23, 0),
    }


def build_item_sprites() -> dict[str, dict[str, Any]]:
    return {
        "canary_doc_A": {
            **_indoor_sprite(19, 0),
            "id": "canary_doc_A",
            "label": "Canary Trap Document (Variant A)",
            "variant": "A",
            "primary_rgb": "rgb(66, 184, 246)",
            "secondary_rgb": "rgb(12, 26, 42)",
        },
        "canary_doc_B": {
            **_indoor_sprite(20, 0),
            "id": "canary_doc_B",
            "label": "Canary Trap Document (Variant B)",
            "variant": "B",
            "primary_rgb": "rgb(246, 192, 68)",
            "secondary_rgb": "rgb(38, 26, 8)",
        },
        "canary_doc_C": {
            **_indoor_sprite(23, 0),
            "id": "canary_doc_C",
            "label": "Canary Trap Document (Variant C)",
            "variant": "C",
            "primary_rgb": "rgb(238, 98, 156)",
            "secondary_rgb": "rgb(42, 10, 24)",
        },
        "doc_regular": {
            **_indoor_sprite(10, 14),
            "id": "doc_regular",
            "label": "Sensitive Internal Document",
            "primary_rgb": "rgb(248, 250, 252)",
            "secondary_rgb": "rgb(239, 68, 68)",
        },
        "leaked_press_clipping": {
            "sheet": "urban",
            "x": 18 * TILE_SIZE,
            "y": 16 * TILE_SIZE,
            "w": TILE_SIZE,
            "h": TILE_SIZE,
            "col": 18,
            "row": 16,
            "margin": 0,
            "id": "leaked_press_clipping",
            "label": "Surfaced Press Feed Alert",
            "primary_rgb": "rgb(239, 68, 68)",
            "secondary_rgb": "rgb(254, 242, 242)",
        },
        "after_hours_ping": {
            "file": "kenney_ui_badges/badge_00.png",
            "x": 0,
            "y": 0,
            "w": TILE_SIZE,
            "h": TILE_SIZE,
            "id": "after_hours_ping",
            "label": "After-Hours Access Log Badge",
            "primary_rgb": "rgb(245, 158, 11)",
            "secondary_rgb": "rgb(30, 41, 59)",
        },
        "restriction_lock": {
            "file": "kenney_ui_badges/badge_01.png",
            "x": 0,
            "y": 0,
            "w": TILE_SIZE,
            "h": TILE_SIZE,
            "id": "restriction_lock",
            "label": "Restricted Clearance Lock",
            "primary_rgb": "rgb(249, 115, 22)",
            "secondary_rgb": "rgb(15, 23, 42)",
        },
        "badge_canary": {
            "file": "kenney_ui_badges/badge_02.png",
            "x": 0,
            "y": 0,
            "w": TILE_SIZE,
            "h": TILE_SIZE,
            "id": "badge_canary",
            "label": "Watermarked Canary Marker",
            "primary_rgb": "rgb(255, 225, 77)",
            "secondary_rgb": "rgb(26, 25, 21)",
        },
    }


def _tile_legend() -> dict[str, dict[str, Any]]:
    return {
        "W": {"name": "perimeter_wall", "walkable": False, **_indoor_sprite(1, 0), "rgb": "rgb(20, 26, 36)"},
        "=": {"name": "exterior_window", "walkable": False, **_indoor_sprite(5, 0), "rgb": "rgb(86, 168, 242)"},
        "|": {"name": "glass_partition", "walkable": False, **_indoor_sprite(5, 1), "rgb": "rgb(52, 64, 82)"},
        "+": {"name": "doorway_threshold", "walkable": True, **_indoor_sprite(3, 2), "rgb": "rgb(38, 46, 59)"},
        ".": {"name": "corridor_floor", "walkable": True, **_indoor_sprite(0, 3), "rgb": "rgb(34, 42, 54)"},
        ",": {"name": "zone_floor", "walkable": True, **_indoor_sprite(1, 3), "rgb": "rgb(28, 36, 48)"},
        "C": {"name": "task_chair", "walkable": True, **_indoor_sprite(18, 0), "rgb": "rgb(54, 64, 80)"},
        "D": {"name": "workstation_desk", "walkable": False, **_indoor_sprite(8, 0), "rgb": "rgb(82, 94, 114)"},
        "T": {"name": "meeting_table", "walkable": False, **_indoor_sprite(12, 0), "rgb": "rgb(74, 96, 122)"},
        "B": {"name": "bistro_table", "walkable": False, **_indoor_sprite(13, 0), "rgb": "rgb(146, 104, 68)"},
        "K": {"name": "coffee_bar", "walkable": False, **_indoor_sprite(9, 0), "rgb": "rgb(112, 74, 46)"},
        "S": {"name": "security_console", "walkable": False, **_indoor_sprite(15, 0), "rgb": "rgb(48, 56, 72)"},
        "P": {"name": "canary_printer", "walkable": False, **_indoor_sprite(17, 0), "rgb": "rgb(246, 192, 68)"},
        "A": {"name": "doc_archive", "walkable": False, **_indoor_sprite(11, 0), "rgb": "rgb(148, 163, 184)"},
        "R": {"name": "server_rack", "walkable": False, **_indoor_sprite(14, 0), "rgb": "rgb(24, 32, 42)"},
        "L": {"name": "leak_drop_relay", "walkable": False, **_indoor_sprite(21, 0), "rgb": "rgb(232, 94, 94)"},
    }


def _verify_walkable_connectivity(
    grid: list[list[str]],
    legend: dict[str, dict[str, Any]],
    required_walkable_points: list[tuple[int, int]],
) -> dict[str, Any]:
    walkable_syms = {sym for sym, meta in legend.items() if meta["walkable"]}
    start = (20, 10)
    if grid[start[1]][start[0]] not in walkable_syms:
        raise ValueError(f"central hub {start} is not walkable")
    seen: set[tuple[int, int]] = {start}
    q: deque[tuple[int, int]] = deque([start])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < GRID_WIDTH and 0 <= ny < GRID_HEIGHT:
                if (nx, ny) not in seen and grid[ny][nx] in walkable_syms:
                    seen.add((nx, ny))
                    q.append((nx, ny))
    for pt in required_walkable_points:
        if pt not in seen:
            raise ValueError(f"required walkable tile {pt} is unreachable from {start}")
    total_walkable = sum(
        1
        for y in range(GRID_HEIGHT)
        for x in range(GRID_WIDTH)
        if grid[y][x] in walkable_syms
    )
    if len(seen) != total_walkable:
        raise ValueError(
            f"disconnected walkable tiles: reached {len(seen)} of {total_walkable}"
        )
    return {
        "origin_tile": [start[0], start[1]],
        "reachable_walkable_tiles": len(seen),
        "total_walkable_tiles": total_walkable,
        "fully_connected": True,
    }


def build_zones_and_tilemap() -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    grid = [["W" for _ in range(GRID_WIDTH)] for _ in range(GRID_HEIGHT)]
    for x in range(1, GRID_WIDTH - 1):
        grid[1][x] = "="

    def mark_corridor(cx: int, cy: int) -> None:
        if 1 <= cx < GRID_WIDTH - 1 and 2 <= cy < GRID_HEIGHT - 1:
            grid[cy][cx] = "."

    for x in range(1, 39):
        mark_corridor(x, 9)
        mark_corridor(x, 10)
        mark_corridor(x, 17)
    for y in range(2, 18):
        mark_corridor(13, y)
        mark_corridor(26, y)
    for y in range(17, 23):
        mark_corridor(10, y)
        mark_corridor(20, y)
        mark_corridor(30, y)

    zones: dict[str, dict[str, Any]] = {}
    all_zone_defs: list[dict[str, Any]] = []
    for dept in ("Engineering", "Research", "Finance", "Sales", "Legal"):
        st = DEPT_STYLE[dept]
        b = st["bounds"]
        zdef = {
            "id": dept.lower(),
            "name": dept,
            "kind": "department",
            "x": b["x"],
            "y": b["y"],
            "w": b["w"],
            "h": b["h"],
            "doorways": [{"x": dx, "y": dy} for dx, dy in st["doorways"]],
            "accent": st["accent_rgb"],
            "floorA": st["floor_a_rgb"],
            "floorB": st["floor_b_rgb"],
        }
        zones[dept] = zdef
        all_zone_defs.append(zdef)

    for fz in FACILITY_ZONES:
        zdef = {
            "id": fz["id"],
            "name": fz["name"],
            "kind": fz["kind"],
            "x": fz["x"],
            "y": fz["y"],
            "w": fz["w"],
            "h": fz["h"],
            "doorways": [{"x": dx, "y": dy} for dx, dy in fz["doorways"]],
            "accent": fz["accent"],
            "floorA": fz["floorA"],
            "floorB": fz["floorB"],
            "waypoints": [{"x": wx, "y": wy} for wx, wy in fz["waypoints"]],
        }
        zones[fz["name"]] = zdef
        all_zone_defs.append(zdef)

    for z in all_zone_defs:
        door_set = {(d["x"], d["y"]) for d in z["doorways"]}
        zx, zy, zw, zh = z["x"], z["y"], z["w"], z["h"]
        for y in range(zy, zy + zh):
            for x in range(zx, zx + zw):
                on_left = x == zx and zx > 1
                on_right = x == zx + zw - 1 and zx + zw - 1 < 38
                on_top = y == zy and zy > 2
                on_bottom = y == zy + zh - 1 and zy + zh - 1 < 22
                if (x, y) in door_set:
                    grid[y][x] = "+"
                elif on_left or on_right or on_top or on_bottom:
                    grid[y][x] = "|"
                else:
                    grid[y][x] = ","
        for d in z["doorways"]:
            grid[d["y"]][d["x"]] = "+"

    for x in range(34, 38):
        grid[12][x] = "K"
    grid[13][29] = "B"
    grid[14][34] = "B"
    for x in range(3, 7):
        grid[20][x] = "T"
    for x in range(13, 17):
        grid[20][x] = "T"
    for x in range(24, 27):
        grid[20][x] = "S"
    grid[20][22] = "P"
    grid[20][28] = "A"
    for y in range(19, 22):
        grid[y][32] = "R"
        grid[y][37] = "R"
    grid[22][10] = "L"
    grid[22][30] = "L"

    zones["Canary Printer"] = {
        "id": "canary_printer",
        "name": "Canary Printer",
        "kind": "station",
        "x": 22,
        "y": 20,
        "w": 1,
        "h": 1,
        "doorways": [{"x": 22, "y": 19}],
        "accent": "rgb(246, 192, 68)",
        "variants_supported": ["A", "B", "C"],
    }
    zones["Doc Archive"] = {
        "id": "doc_archive",
        "name": "Doc Archive",
        "kind": "station",
        "x": 28,
        "y": 20,
        "w": 1,
        "h": 1,
        "doorways": [{"x": 28, "y": 19}],
        "accent": "rgb(148, 163, 184)",
    }
    zones["Leak Drop Relay"] = {
        "id": "leak_drop_relay",
        "name": "Leak Drop Relay",
        "kind": "station",
        "x": 10,
        "y": 22,
        "w": 21,
        "h": 1,
        "terminals": [{"x": 10, "y": 22}, {"x": 30, "y": 22}],
        "accent": "rgb(232, 94, 94)",
    }

    desks: list[dict[str, Any]] = []
    department_clusters: dict[str, dict[str, Any]] = {}
    desks_by_dept: dict[str, list[dict[str, Any]]] = {d: [] for d in PUBLIC_DEPARTMENTS}

    desk_counter = 0
    for dept in PUBLIC_DEPARTMENTS:
        st = DEPT_STYLE[dept]
        b = st["bounds"]
        zx, zy, zh = b["x"], b["y"], b["h"]
        row_offsets = (1, 4) if zh >= 7 else (1, 3)
        primary_cols = (1, 4, 7, 10)
        pod_desk_ids: list[str] = []
        slot_idx = 0
        for r_off in row_offsets:
            dy = zy + r_off
            cy = dy + 1
            for c_off in primary_cols:
                dx = zx + c_off
                cx = dx
                grid[dy][dx] = "D"
                grid[cy][cx] = "C"
                desk_id = f"desk_{desk_counter:02d}"
                emp_40 = f"e{slot_idx * 5 + st['index']:02d}"
                emp_20 = (
                    f"e{slot_idx * 4 + st['index']:02d}"
                    if st["index"] < 4 and slot_idx < 5
                    else None
                )
                emp_12 = (
                    f"e{slot_idx * 4 + st['index']:02d}"
                    if st["index"] < 4 and slot_idx < 3
                    else None
                )
                rec = {
                    "desk_id": desk_id,
                    "dept": dept,
                    "slot_in_dept": slot_idx,
                    "desk_tile": [dx, dy],
                    "chair_tile": [cx, cy],
                    "facing": "north",
                    "default_employee_40": emp_40,
                    "default_employee_20": emp_20,
                    "default_employee_12": emp_12,
                }
                desks.append(rec)
                desks_by_dept[dept].append(rec)
                pod_desk_ids.append(desk_id)
                desk_counter += 1
                slot_idx += 1

        department_clusters[dept] = {
            "dept": dept,
            "code": st["code"],
            "index": st["index"],
            "bounds": dict(b),
            "accent_rgb": st["accent_rgb"],
            "desk_ids": pod_desk_ids,
            "default_employees_40": [
                d["default_employee_40"] for d in desks_by_dept[dept]
            ],
            "default_employees_20": [
                d["default_employee_20"]
                for d in desks_by_dept[dept]
                if d["default_employee_20"] is not None
            ],
        }

    legend = _tile_legend()
    required_walkable = [tuple(d["chair_tile"]) for d in desks]
    for fz in FACILITY_ZONES:
        for wx, wy in fz["waypoints"]:
            required_walkable.append((wx, wy))
    required_walkable.extend([(22, 19), (28, 19), (10, 21), (30, 21)])
    connectivity = _verify_walkable_connectivity(grid, legend, required_walkable)

    hard_seats: dict[str, dict[str, Any]] = {}
    medium_seats: dict[str, dict[str, Any]] = {}
    easy_seats: dict[str, dict[str, Any]] = {}
    for d in desks:
        e40 = d["default_employee_40"]
        hard_seats[e40] = {
            "desk_id": d["desk_id"],
            "dept": d["dept"],
            "chair_tile": d["chair_tile"],
            "desk_tile": d["desk_tile"],
        }
        if d["default_employee_20"] is not None:
            medium_seats[d["default_employee_20"]] = {
                "desk_id": d["desk_id"],
                "dept": d["dept"],
                "chair_tile": d["chair_tile"],
                "desk_tile": d["desk_tile"],
            }
        if d["default_employee_12"] is not None:
            easy_seats[d["default_employee_12"]] = {
                "desk_id": d["desk_id"],
                "dept": d["dept"],
                "chair_tile": d["chair_tile"],
                "desk_tile": d["desk_tile"],
            }

    tier_layouts = {
        "hard_40": {
            "tier": "hard",
            "n_employees": TIERS["hard"].n_employees,
            "n_days": TIERS["hard"].n_days,
            "active_departments": list(PUBLIC_DEPARTMENTS),
            "seats": {f"e{i:02d}": hard_seats[f"e{i:02d}"] for i in range(40)},
        },
        "medium_20": {
            "tier": "medium",
            "n_employees": TIERS["medium"].n_employees,
            "n_days": TIERS["medium"].n_days,
            "active_departments": list(PUBLIC_DEPARTMENTS[:4]),
            "seats": {f"e{i:02d}": medium_seats[f"e{i:02d}"] for i in range(20)},
        },
        "easy_12": {
            "tier": "easy",
            "n_employees": TIERS["easy"].n_employees,
            "n_days": TIERS["easy"].n_days,
            "active_departments": list(PUBLIC_DEPARTMENTS[:4]),
            "seats": {f"e{i:02d}": easy_seats[f"e{i:02d}"] for i in range(12)},
        },
    }

    tilemap = {
        "width": GRID_WIDTH,
        "height": GRID_HEIGHT,
        "tile_size": TILE_SIZE,
        "pixel_width": GRID_WIDTH * TILE_SIZE,
        "pixel_height": GRID_HEIGHT * TILE_SIZE,
        "legend": legend,
        "rows": ["".join(r) for r in grid],
        "connectivity": connectivity,
        "department_clusters": department_clusters,
        "desks": desks,
        "tier_layouts": tier_layouts,
    }
    return zones, tilemap


def _build_silhouette_glyph(hair_style: str, outfit_style: str) -> list[str]:
    top0, top1, top2 = HAIR_ROWS_TOP[hair_style]
    torso0, torso1, torso2, torso3 = OUTFIT_TORSO_ROWS[outfit_style]
    return [
        top0,
        top1,
        top2,
        "..SSSS..",
        "..SEES..",
        torso0,
        torso1,
        torso2,
        torso3,
        "..PPPP..",
        "..PP.PP.",
        ".OO..OO.",
    ]


def _char_frame(col: int, row: int, dy: int, pose: str) -> dict[str, Any]:
    return {
        "x": col * CHAR_STRIDE,
        "y": row * CHAR_STRIDE,
        "w": TILE_SIZE,
        "h": TILE_SIZE,
        "col": col,
        "row": row,
        "dy": dy,
        "pose": pose,
    }


def _build_employee_animations(base_col: int, row: int) -> dict[str, dict[str, Any]]:
    c0 = base_col
    c1 = (base_col + 1) % 54
    c2 = (base_col + 2) % 54
    return {
        "idle": {
            "fps": 2,
            "loop": True,
            "clips": [_char_frame(c0, row, 0, "stand"), _char_frame(c0, row, -1, "breathe")],
        },
        "walk": {
            "fps": 8,
            "loop": True,
            "clips": [
                _char_frame(c0, row, 0, "stride_a"),
                _char_frame(c1, row, -1, "stride_l"),
                _char_frame(c0, row, 0, "stride_b"),
                _char_frame(c2, row, -1, "stride_r"),
            ],
        },
        "work": {
            "fps": 4,
            "loop": True,
            "clips": [_char_frame(c1, row, 0, "type_l"), _char_frame(c2, row, 0, "type_r")],
        },
        "interview": {
            "fps": 3,
            "loop": True,
            "clips": [_char_frame(c0, row, 0, "listen"), _char_frame(c2, row, -1, "reply")],
        },
    }


def build_employees(tilemap: dict[str, Any]) -> dict[str, dict[str, Any]]:
    hard_seats = tilemap["tier_layouts"]["hard_40"]["seats"]
    medium_seats = tilemap["tier_layouts"]["medium_20"]["seats"]
    easy_seats = tilemap["tier_layouts"]["easy_12"]["seats"]

    employees: dict[str, dict[str, Any]] = {}
    for i in range(N_EMPLOYEES_MAX):
        emp_id = f"e{i:02d}"
        dept = PUBLIC_DEPARTMENTS[i % len(PUBLIC_DEPARTMENTS)]
        roles_for_dept = CANONICAL_ROLES[dept]
        role = roles_for_dept[(i // len(PUBLIC_DEPARTMENTS)) % len(roles_for_dept)]
        dstyle = DEPT_STYLE[dept]

        pub_vis = compute_public_employee_visual(emp_id, dept, role)
        hair_style = HAIR_STYLES[i % len(HAIR_STYLES)]
        outfit_style = dstyle["outfit_style"]
        accessory = ACCESSORIES[(i * 3 + dstyle["index"]) % len(ACCESSORIES)]
        shirt_rgb = SHIRT_PALETTE_40[i]
        trouser_rgb = TROUSER_TONES[(i + dstyle["index"]) % len(TROUSER_TONES)]
        accent_rgb = ACCENT_TONES[i % len(ACCENT_TONES)]

        row = (i % 10) + 1
        col = (i // 10) * 12 + (i % 10)
        seat_40 = hard_seats[emp_id]

        employees[emp_id] = {
            "id": emp_id,
            "index": i,
            "label": emp_id.upper(),
            "dept": dept,
            "role": role,
            "public_inputs": ["id", "dept", "role"],
            "visual_hash": pub_vis["visual_hash"],
            "sheet": "characters",
            "x": col * CHAR_STRIDE,
            "y": row * CHAR_STRIDE,
            "w": TILE_SIZE,
            "h": TILE_SIZE,
            "col": col,
            "row": row,
            "margin": 1,
            "home_desk_id": seat_40["desk_id"],
            "spawn_tile": seat_40["chair_tile"],
            "desk_tile": seat_40["desk_tile"],
            "medium_seat": medium_seats.get(emp_id),
            "easy_seat": easy_seats.get(emp_id),
            "palette": {
                "skin": pub_vis["skin"],
                "hair": pub_vis["hair"],
                "hair_name": pub_vis["hair_name"],
                "jacket": pub_vis["jacket"],
                "shirt": shirt_rgb,
                "trouser": trouser_rgb,
                "accent": accent_rgb,
                "outline": "rgb(9, 13, 22)",
            },
            "badge": {
                "dept_code": dstyle["code"],
                "glyph": dstyle["glyph"],
                "number": f"{i:02d}",
                "pips": pub_vis["badgePips"],
                "color_rgb": dstyle["accent_rgb"],
                "shape": dstyle["badge_shape"],
            },
            "silhouette": {
                "width": 8,
                "height": 12,
                "hair_style": hair_style,
                "outfit_style": outfit_style,
                "accessory": accessory,
                "glyph_rows": _build_silhouette_glyph(hair_style, outfit_style),
            },
            "animations": _build_employee_animations(col, row),
        }

    return employees


def build_lighting() -> dict[str, Any]:
    phases = {
        "morning": {
            "phase": "morning",
            "ratio_range": [0.0, 0.25],
            "sky_top_rgb": "rgb(98, 162, 228)",
            "sky_bottom_rgb": "rgb(244, 198, 122)",
            "overlay_rgba": "rgba(255, 214, 150, 0.06)",
            "desk_lamp_intensity": 0.18,
        },
        "afternoon": {
            "phase": "afternoon",
            "ratio_range": [0.25, 0.625],
            "sky_top_rgb": "rgb(86, 168, 242)",
            "sky_bottom_rgb": "rgb(152, 208, 250)",
            "overlay_rgba": "rgba(255, 255, 255, 0.02)",
            "desk_lamp_intensity": 0.10,
        },
        "dusk": {
            "phase": "dusk",
            "ratio_range": [0.625, 0.875],
            "sky_top_rgb": "rgb(96, 68, 148)",
            "sky_bottom_rgb": "rgb(232, 122, 92)",
            "overlay_rgba": "rgba(176, 96, 148, 0.14)",
            "desk_lamp_intensity": 0.68,
        },
        "night": {
            "phase": "night",
            "ratio_range": [0.875, 1.0],
            "sky_top_rgb": "rgb(14, 22, 46)",
            "sky_bottom_rgb": "rgb(28, 40, 74)",
            "overlay_rgba": "rgba(14, 22, 54, 0.28)",
            "desk_lamp_intensity": 0.96,
        },
    }

    n_days = TIERS["hard"].n_days
    day_keyframes: list[dict[str, Any]] = []
    for day in range(1, n_days + 1):
        frac = (day - 1) / max(1, n_days - 1)
        if day <= 7:
            act = "Act I: Baseline Intake"
        elif day <= 14:
            act = "Act II: Canary Triangulation"
        else:
            act = "Act III: Horizon Reckoning"
        night_alpha = round(0.28 + 0.18 * frac, 3)
        day_keyframes.append(
            {
                "day_num": day,
                "act": act,
                "nordic_daylight_hours": round(7.8 - 1.7 * frac, 2),
                "ambient_lux": round(0.94 - 0.20 * frac, 3),
                "night_overlay_rgba": f"rgba(14, 22, 54, {night_alpha:.3f})",
                "desk_lamp_gain": round(0.24 + 0.62 * frac, 3),
            }
        )

    return {
        "horizon_days": n_days,
        "easy_medium_horizon_days": TIERS["medium"].n_days,
        "phases": phases,
        "day_keyframes": day_keyframes,
    }


def assign_public_roster_seats(
    public_employees: list[dict[str, Any]],
    manifest: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if manifest is None:
        manifest = build_manifest()

    for entry in public_employees:
        if not isinstance(entry, dict):
            raise ValueError("each employee entry must be a dict")
        unexpected = set(entry.keys()) - ALLOWED_PUBLIC_EMPLOYEE_KEYS
        if unexpected:
            raise ValueError(
                f"non-public employee fields rejected: {sorted(unexpected)}"
            )
        if "id" not in entry or "dept" not in entry:
            raise ValueError("public employee entry requires id and dept")
        if entry["dept"] not in DEPT_STYLE:
            raise ValueError(f"unknown public department: {entry['dept']}")

    desks = manifest["tilemap"]["desks"]
    employees_map = manifest["employees"]
    by_dept_desks: dict[str, list[dict[str, Any]]] = {
        d: [] for d in PUBLIC_DEPARTMENTS
    }
    for d in desks:
        by_dept_desks[d["dept"]].append(d)

    ordered = sorted(public_employees, key=lambda e: str(e["id"]))
    used_desk_ids: set[str] = set()
    assigned: dict[str, dict[str, Any]] = {}
    overflow_queue: list[dict[str, Any]] = []

    for emp in ordered:
        emp_id = str(emp["id"])
        dept = str(emp["dept"])
        role = str(emp.get("role", "staff"))
        if emp_id not in employees_map:
            raise ValueError(f"unknown public employee id: {emp_id}")
        vis = compute_public_employee_visual(emp_id, dept, role)
        picked = None
        for cand in by_dept_desks[dept]:
            if cand["desk_id"] not in used_desk_ids:
                picked = cand
                break
        if picked is not None:
            used_desk_ids.add(picked["desk_id"])
            assigned[emp_id] = {
                "employee_id": emp_id,
                "public_dept": dept,
                "public_role": role,
                "desk_id": picked["desk_id"],
                "desk_dept": picked["dept"],
                "chair_tile": picked["chair_tile"],
                "desk_tile": picked["desk_tile"],
                "sprite_index": employees_map[emp_id]["index"],
                "visual_hash": vis["visual_hash"],
                "badge_pips": vis["badgePips"],
                "jacket": vis["jacket"],
                "skin": vis["skin"],
                "hair": vis["hair"],
            }
        else:
            overflow_queue.append(emp)

    remaining_desks = [d for d in desks if d["desk_id"] not in used_desk_ids]
    for emp, fallback_desk in zip(overflow_queue, remaining_desks):
        emp_id = str(emp["id"])
        dept = str(emp["dept"])
        role = str(emp.get("role", "staff"))
        vis = compute_public_employee_visual(emp_id, dept, role)
        used_desk_ids.add(fallback_desk["desk_id"])
        assigned[emp_id] = {
            "employee_id": emp_id,
            "public_dept": dept,
            "public_role": role,
            "desk_id": fallback_desk["desk_id"],
            "desk_dept": fallback_desk["dept"],
            "chair_tile": fallback_desk["chair_tile"],
            "desk_tile": fallback_desk["desk_tile"],
            "sprite_index": employees_map[emp_id]["index"],
            "visual_hash": vis["visual_hash"],
            "badge_pips": vis["badgePips"],
            "jacket": vis["jacket"],
            "skin": vis["skin"],
            "hair": vis["hair"],
        }

    return assigned


def build_manifest() -> dict[str, Any]:
    sheets = build_sheets()
    sheet_catalog = build_sheet_catalog()
    attribution = build_attribution()
    sprites = build_sprites()
    item_sprites = build_item_sprites()
    zones, tilemap = build_zones_and_tilemap()
    employees = build_employees(tilemap)
    lighting = build_lighting()

    return {
        "schema_version": "canary.arena.sprite_manifest_40emp.v1",
        "manifest_id": "canary_office_40emp_cc0",
        "tiers_version": TIERS_VERSION,
        "baseUrl": "./assets",
        "tileSheet": "kenney_roguelike_indoor.png",
        "charSheet": "kenney_roguelike_char.png",
        "frameW": TILE_SIZE,
        "frameH": TILE_SIZE,
        "tile_size": TILE_SIZE,
        "grid_width": GRID_WIDTH,
        "grid_height": GRID_HEIGHT,
        "creditsText": CREDITS_TEXT,
        "public_determinism": {
            "inputs": ["id", "dept", "role"],
            "seed_independent": True,
            "hidden_state_encoded": False,
        },
        "sheets": sheets,
        "sheet_catalog": sheet_catalog,
        "attribution": attribution,
        "sprites": sprites,
        "item_sprites": item_sprites,
        "employee_ids": list(employees.keys()),
        "employees": employees,
        "zones": zones,
        "tilemap": tilemap,
        "lighting": lighting,
    }


def _dump_compact_json(value: Any, depth: int = 0) -> str:
    pad = "  " * depth
    child_pad = "  " * (depth + 1)
    if depth >= 2:
        return json.dumps(value, separators=(",", ":"))
    if isinstance(value, dict):
        if not value:
            return "{}"
        parts = [
            f"{child_pad}{json.dumps(str(k))}: {_dump_compact_json(v, depth + 1)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(parts) + "\n" + pad + "}"
    if isinstance(value, list):
        if not value:
            return "[]"
        if all(not isinstance(item, (dict, list)) for item in value):
            return json.dumps(value, separators=(", ", ": "))
        parts = [f"{child_pad}{_dump_compact_json(item, depth + 1)}" for item in value]
        return "[\n" + ",\n".join(parts) + "\n" + pad + "]"
    return json.dumps(value)


def serialize_manifest_json(manifest: dict[str, Any]) -> str:
    return _dump_compact_json(manifest) + "\n"


def serialize_manifest_js(manifest: dict[str, Any]) -> str:
    payload = _dump_compact_json(manifest)
    return f"globalThis.CANARY_SPRITE_MANIFEST_40EMP = {payload};\n"


def render_markdown(manifest: dict[str, Any]) -> str:
    tm = manifest["tilemap"]
    attr = manifest["attribution"]
    lighting = manifest["lighting"]
    h1 = MD_H
    h2 = MD_H * 2
    h3 = MD_H * 3
    lines: list[str] = [
        f"{h1} Canary Arena: 40-Employee Sprite Cast and 40x24 Office Map",
        "",
        "Deterministic CC0 sprite manifest and spatial floorplan for `OfficeStage.loadSpritePack(manifest)` "
        "in Canary Arena (`docs/arena/data/sprite_manifest_40emp.json` and offline `docs/arena/data/sprite_manifest_40emp.js`).",
        "",
        f"{h2} 1. Architecture and Public-Only Integrity Contract",
        "",
        f"- **Schema**: `{manifest['schema_version']}` (Canary tiers `{manifest['tiers_version']}`)",
        f"- **Stage Geometry**: `{tm['width']}x{tm['height']}` tiles at `{tm['tile_size']}px` "
        f"(`{tm['pixel_width']}x{tm['pixel_height']}` pixels)",
        f"- **Walkable Connectivity**: `{tm['connectivity']['reachable_walkable_tiles']}/"
        f"{tm['connectivity']['total_walkable_tiles']}` walkable tiles 4-directionally connected from hub `{tm['connectivity']['origin_tile']}`",
        "- **Tier Coverage**: `hard` (`e00..e39`, 40 staff, 5 departments, 21 days), "
        "`medium` (`e00..e19`, 20 staff, 4 departments, 14 days), and `easy` (`e00..e11`, 12 staff, 4 departments, 14 days)",
        "- **Public-Only Determinism**: Every sprite coordinate, desk seat, badge pip count, "
        "palette tint, and silhouette glyph is derived strictly from public employee fields (`id`, `dept`, `role`). "
        "Zero private state is ever read or stored.",
        "",
        f"{h2} 2. Office Floorplan (`40x24` Grid)",
        "",
        "```text",
    ]
    for y, row_str in enumerate(tm["rows"]):
        lines.append(f"{y:02d} {row_str}")
    lines.extend(
        [
            "```",
            "",
            f"{h3} Tile Legend",
            "",
            "| Symbol | Tile Name | Walkable | Sheet | `(col, row)` | Fallback RGB |",
            "| :---: | :--- | :---: | :--- | :---: | :--- |",
        ]
    )
    for sym, meta in tm["legend"].items():
        lines.append(
            f"| `{sym}` | `{meta['name']}` | `{'yes' if meta['walkable'] else 'no'}` | "
            f"`{meta['sheet']}` | `({meta['col']}, {meta['row']})` | `{meta['rgb']}` |"
        )

    lines.extend(
        [
            "",
            f"{h3} Zones and Investigation Facilities",
            "",
            "| Zone Name | Kind | Bounds `(x, y, w, h)` | Accent RGB |",
            "| :--- | :---: | :---: | :--- |",
        ]
    )
    for zname, zmeta in manifest["zones"].items():
        lines.append(
            f"| {zname} | `{zmeta['kind']}` | "
            f"`({zmeta['x']}, {zmeta['y']}, {zmeta['w']}, {zmeta['h']})` | `{zmeta['accent']}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 3. 40-Employee Animated Cast (`e00..e39`)",
            "",
            "| ID | Dept | Role | Home Desk | Chair `(x, y)` | Char `(col, row)` | Hair / Outfit / Accessory | Shirt RGB |",
            "| :---: | :--- | :--- | :---: | :---: | :---: | :--- | :--- |",
        ]
    )
    for emp_id in manifest["employee_ids"]:
        emp = manifest["employees"][emp_id]
        cx, cy = emp["spawn_tile"]
        sil = emp["silhouette"]
        lines.append(
            f"| `{emp['id']}` | {emp['dept']} | `{emp['role']}` | `{emp['home_desk_id']}` | `({cx}, {cy})` | "
            f"`({emp['col']}, {emp['row']})` | "
            f"`{sil['hair_style']}` / `{sil['outfit_style']}` / `{sil['accessory']}` | "
            f"`{emp['palette']['shirt']}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 4. Day/Night Lighting Phases and 21-Day Nordic Campaign",
            "",
            "| Phase | Action Ratio | Sky Top | Sky Bottom | Overlay RGBA |",
            "| :--- | :---: | :--- | :--- | :--- |",
        ]
    )
    for pname, pmeta in lighting["phases"].items():
        r0, r1 = pmeta["ratio_range"]
        lines.append(
            f"| `{pname}` | `{r0:.3f}..{r1:.3f}` | `{pmeta['sky_top_rgb']}` | `{pmeta['sky_bottom_rgb']}` | `{pmeta['overlay_rgba']}` |"
        )

    lines.extend(
        [
            "",
            f"{h2} 5. Verified CC0 1.0 Universal Attribution",
            "",
            f"- **Credits**: `{manifest['creditsText']}`",
            f"- **License**: `{attr['license']}` ({attr['license_url']})",
            f"- **Paid / Commercial / Ripped Assets**: `False`",
            "",
            "| Pack ID | Title | Asset File | Source URL |",
            "| :--- | :--- | :--- | :--- |",
        ]
    )
    for p in attr["packs"]:
        lines.append(
            f"| `{p['id']}` | {p['title']} | `{p['file']}` | {p['source_url']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Build or verify Canary Arena 40-employee CC0 sprite manifest and 40x24 office map."
    )
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out-json", default=None)
    ap.add_argument("--out-js", default=None)
    ap.add_argument("--out-md", default=None)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)

    if args.write and args.check:
        ap.error("pass either --write or --check, not both")

    root = Path(args.root).resolve()
    out_json = Path(args.out_json).resolve() if args.out_json else default_json_path(root)
    out_js = Path(args.out_js).resolve() if args.out_js else default_js_path(root)
    out_md = Path(args.out_md).resolve() if args.out_md else default_md_path(root)

    manifest = build_manifest()
    json_blob = serialize_manifest_json(manifest)
    js_blob = serialize_manifest_js(manifest)
    md_blob = render_markdown(manifest)

    json_bytes = len(json_blob.encode("utf-8"))
    if json_bytes > MAX_JSON_BYTES:
        print(
            f"generated manifest size {json_bytes} exceeds {MAX_JSON_BYTES} bytes",
            file=sys.stderr,
        )
        return 1

    if args.check:
        for target_path in (out_json, out_js, out_md):
            if not target_path.is_file():
                print(f"missing {target_path}", file=sys.stderr)
                return 1
        disk_size = out_json.stat().st_size
        if disk_size > MAX_JSON_BYTES:
            print(f"{out_json} size {disk_size} exceeds {MAX_JSON_BYTES} bytes", file=sys.stderr)
            return 1
        if out_json.read_text(encoding="utf-8") != json_blob:
            print(f"{out_json} differs from fresh build", file=sys.stderr)
            return 1
        if out_js.read_text(encoding="utf-8") != js_blob:
            print(f"{out_js} differs from fresh JS bundle build", file=sys.stderr)
            return 1
        if out_md.read_text(encoding="utf-8") != md_blob:
            print(f"{out_md} differs from fresh markdown render", file=sys.stderr)
            return 1
        print(
            f"arena sprite manifest verified: {len(manifest['employees'])} employees, "
            f"{manifest['grid_width']}x{manifest['grid_height']} grid, "
            f"{disk_size} bytes (< {MAX_JSON_BYTES})"
        )
        return 0

    if args.write:
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_js.parent.mkdir(parents=True, exist_ok=True)
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json_blob, encoding="utf-8")
        out_js.write_text(js_blob, encoding="utf-8")
        out_md.write_text(md_blob, encoding="utf-8")
        print(f"wrote {out_json} ({out_json.stat().st_size} bytes)")
        print(f"wrote {out_js} ({out_js.stat().st_size} bytes)")
        print(f"wrote {out_md} ({out_md.stat().st_size} bytes)")
        return 0

    print(md_blob, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
