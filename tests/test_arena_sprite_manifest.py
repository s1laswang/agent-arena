from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

from canary.env import Env
from scripts import build_arena_sprite_manifest as builder

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PY = ROOT / "scripts" / "build_arena_sprite_manifest.py"
MANIFEST_JSON = ROOT / "docs" / "arena" / "data" / "sprite_manifest_40emp.json"
MANIFEST_JS = ROOT / "docs" / "arena" / "data" / "sprite_manifest_40emp.js"
CAST_MD = ROOT / "docs" / "arena" / "SPRITE_CAST_40.md"
THIS_TEST_PY = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

FORBIDDEN_KEYS: frozenset[str] = frozenset(
    {
        "mole",
        "true_mole",
        "mole_id",
        "moleId",
        "is_mole",
        "is_canary",
        "decoy",
        "true_decoy",
        "decoy_id",
        "leaking_sprite_employee",
        "mole_sprite",
        "culprit_sprite",
        "leaker_employee",
        "_world",
        "world_seed",
        "mole_strategy",
        "secret",
        "world_secret",
        "seed",
    }
)


def _find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    for cand in (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def _collect_all_dict_keys(obj: Any) -> set[str]:
    keys: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(str(k))
            keys.update(_collect_all_dict_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            keys.update(_collect_all_dict_keys(item))
    return keys


def test_owned_files_hygiene_ascii_zero_comments_and_zero_secret_literals() -> None:
    for path in (SCRIPT_PY, MANIFEST_JSON, MANIFEST_JS, CAST_MD, THIS_TEST_PY):
        assert path.is_file(), f"missing {path}"
        txt = path.read_text(encoding="utf-8")
        assert txt.isascii(), f"non-ASCII content in {path}"
        assert EM_DASH not in txt
        assert EN_DASH not in txt
        assert UNICODE_MINUS not in txt

    for py_path in (SCRIPT_PY, THIS_TEST_PY):
        py_src = py_path.read_text(encoding="utf-8")
        assert HASH_CH not in py_src
        tokens = list(tokenize.generate_tokens(io.StringIO(py_src).readline))
        assert [t for t in tokens if t.type == tokenize.COMMENT] == []

    forbidden_arena_strings = (
        "CANARY_" + "WORLD_SECRET",
        "CANARY_" + "LEDGER_TOKEN",
        "data/worlds/judge/" + "SALT",
    )
    for arena_file in (MANIFEST_JSON, MANIFEST_JS, CAST_MD):
        content = arena_file.read_text(encoding="utf-8")
        for forbidden_lit in forbidden_arena_strings:
            assert forbidden_lit not in content


def test_cli_check_and_write_determinism(tmp_path: Path) -> None:
    assert MANIFEST_JSON.stat().st_size < 120_000
    rc_check = builder.main(["--check", "--root", str(ROOT)])
    assert rc_check == 0

    out_json = tmp_path / "sprite_manifest_40emp.json"
    out_js = tmp_path / "sprite_manifest_40emp.js"
    out_md = tmp_path / "SPRITE_CAST_40.md"
    rc_write = builder.main(
        [
            "--write",
            "--out-json",
            str(out_json),
            "--out-js",
            str(out_js),
            "--out-md",
            str(out_md),
        ]
    )
    assert rc_write == 0
    assert out_json.read_text(encoding="utf-8") == MANIFEST_JSON.read_text(encoding="utf-8")
    assert out_js.read_text(encoding="utf-8") == MANIFEST_JS.read_text(encoding="utf-8")
    assert out_md.read_text(encoding="utf-8") == CAST_MD.read_text(encoding="utf-8")


def test_manifest_contract_40_employees_and_zero_truth_keys() -> None:
    manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
    js_raw = MANIFEST_JS.read_text(encoding="utf-8")
    prefix = "globalThis.CANARY_SPRITE_MANIFEST_40EMP = "
    assert js_raw.startswith(prefix)
    assert js_raw.endswith(";\n")
    js_payload = js_raw[len(prefix) : -2]
    assert js_payload == MANIFEST_JSON.read_text(encoding="utf-8").rstrip("\n")
    assert json.loads(js_payload) == manifest

    for req_key in (
        "baseUrl",
        "tileSheet",
        "charSheet",
        "frameW",
        "frameH",
        "creditsText",
        "sprites",
        "employees",
        "zones",
        "lighting",
    ):
        assert req_key in manifest

    assert manifest["baseUrl"] == "./assets"
    assert manifest["tileSheet"] == "kenney_roguelike_indoor.png"
    assert manifest["charSheet"] == "kenney_roguelike_char.png"
    assert manifest["frameW"] == 16
    assert manifest["frameH"] == 16
    assert "CC0" in manifest["creditsText"]

    all_keys = _collect_all_dict_keys(manifest)
    assert all_keys.isdisjoint(FORBIDDEN_KEYS)

    emps = manifest["employees"]
    expected_ids = [f"e{i:02d}" for i in range(40)]
    assert list(emps.keys()) == expected_ids
    assert manifest["employee_ids"] == expected_ids

    char_coords = set()
    desk_ids = set()
    chair_tiles = set()
    shirts = set()
    silhouettes = set()

    for emp_id in expected_ids:
        emp = emps[emp_id]
        assert emp["id"] == emp_id
        assert emp["public_inputs"] == ["id", "dept", "role"]
        col, row = emp["col"], emp["row"]
        assert 0 <= col < 54
        assert 0 <= row < 12
        assert emp["x"] == col * 17
        assert emp["y"] == row * 17
        char_coords.add((col, row))
        desk_ids.add(emp["home_desk_id"])
        chair_tiles.add(tuple(emp["spawn_tile"]))
        shirts.add(emp["palette"]["shirt"])
        sil = emp["silhouette"]
        silhouettes.add(
            (
                sil["hair_style"],
                sil["outfit_style"],
                sil["accessory"],
                emp["palette"]["shirt"],
            )
        )
        for anim_name in ("idle", "walk", "work", "interview"):
            assert anim_name in emp["animations"]
            assert len(emp["animations"][anim_name]["clips"]) >= 2

    assert len(char_coords) == 40
    assert len(desk_ids) == 40
    assert len(chair_tiles) == 40
    assert len(shirts) == 40
    assert len(silhouettes) == 40

    for zname in (
        "Engineering",
        "Finance",
        "Legal",
        "Research",
        "Sales",
        "Meeting Room A",
        "Meeting Room B",
        "Coffee Corner",
        "Server Room",
        "Security Desk",
    ):
        assert zname in manifest["zones"]

    assert manifest["tilemap"]["connectivity"]["fully_connected"] is True
    assert manifest["lighting"]["horizon_days"] == 21
    assert set(manifest["lighting"]["phases"].keys()) == {
        "morning",
        "afternoon",
        "dusk",
        "night",
    }


def test_public_only_roster_assignment_and_anti_leak_rejection() -> None:
    manifest = builder.build_manifest()
    for tier, expected_n in (("easy", 12), ("medium", 20), ("hard", 40)):
        env = Env(tier, 0)
        staff = env.call("list_employees", {}).data["employees"]
        assert len(staff) == expected_n
        seats = builder.assign_public_roster_seats(staff, manifest)
        assert len(seats) == expected_n
        assert len({s["desk_id"] for s in seats.values()}) == expected_n
        assert len({tuple(s["chair_tile"]) for s in seats.values()}) == expected_n

    roster_a = [
        {"id": "e00", "name": "Aino Virtanen", "dept": "Engineering", "role": "tech lead"},
        {"id": "e01", "name": "Mikko Korhonen", "dept": "Finance", "role": "analyst"},
    ]
    roster_b = list(reversed(roster_a))
    assert builder.assign_public_roster_seats(roster_a, manifest) == builder.assign_public_roster_seats(
        roster_b, manifest
    )

    for bad_key in ("mole", "true_mole", "mole_id", "moleId", "decoy", "_world", "world_seed", "leaking_sprite_employee"):
        with pytest.raises(ValueError, match="non-public"):
            builder.assign_public_roster_seats(
                [{"id": "e00", "dept": "Engineering", "role": "engineer", bad_key: "e00"}],
                manifest,
            )


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_offline_js_bundle_loads_cleanly_in_node() -> None:
    node_bin = _find_node()
    assert node_bin is not None
    probe = (
        f"import fs from 'node:fs';"
        f"import vm from 'node:vm';"
        f"const jsCode = fs.readFileSync({json.dumps(str(MANIFEST_JS))}, 'utf8');"
        f"const jsonObj = JSON.parse(fs.readFileSync({json.dumps(str(MANIFEST_JSON))}, 'utf8'));"
        f"const ctx = {{ globalThis: {{}} }};"
        f"ctx.globalThis = ctx;"
        f"vm.runInNewContext(jsCode, ctx);"
        f"const got = ctx.CANARY_SPRITE_MANIFEST_40EMP;"
        f"if (!got || Object.keys(got.employees).length !== 40) throw new Error('missing 40 employees');"
        f"if (JSON.stringify(got) !== JSON.stringify(jsonObj)) throw new Error('JS/JSON mismatch');"
        f"console.log('JS_BUNDLE_OK');"
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    assert "JS_BUNDLE_OK" in proc.stdout
