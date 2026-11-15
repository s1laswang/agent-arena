from __future__ import annotations

import ast
import importlib.util
import io
import json
import shutil
import struct
import sys
import tokenize
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_arena_assets.py"
SELF_PATH = Path(__file__).resolve()

_SPEC = importlib.util.spec_from_file_location("verify_arena_assets_mod", SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)

CANONICAL_TOTAL_PNG_BYTES = _MOD.CANONICAL_TOTAL_PNG_BYTES
MAX_ARENA_ASSET_BYTES = _MOD.MAX_ARENA_ASSET_BYTES
check_cc0_license_and_attribution = _MOD.check_cc0_license_and_attribution
check_png_ihdr_and_sha256 = _MOD.check_png_ihdr_and_sha256
check_pre_end_zero_leak_and_hygiene = _MOD.check_pre_end_zero_leak_and_hygiene
check_sprite_coordinates_and_bounds = _MOD.check_sprite_coordinates_and_bounds
is_protected_path = _MOD.is_protected_path
main = _MOD.main
parse_png_ihdr = _MOD.parse_png_ihdr
verify_arena_assets = _MOD.verify_arena_assets

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)


def _make_valid_png(width: int, height: int) -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + (b"\x00\x00\x00\xff" * width) for _ in range(height))
    idat = zlib.compress(raw_scanlines)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def _stage_arena_tree(tmp_path: Path) -> Path:
    dst_arena = tmp_path / "docs" / "arena"
    dst_arena.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "docs" / "arena", dst_arena)
    return tmp_path


def _load_staged_manifest(staged_root: Path) -> tuple[Path, dict]:
    mpath = staged_root / "docs" / "arena" / "assets" / "sprite_pack_manifest.json"
    return mpath, json.loads(mpath.read_text(encoding="utf-8"))


def test_real_repo_passes_default_and_strict() -> None:
    rep_default = verify_arena_assets(root=ROOT, strict=False)
    rep_strict = verify_arena_assets(root=ROOT, strict=True)
    for rep in (rep_default, rep_strict):
        assert rep["passed"] is True
        assert rep["status"] == "PASS"
        assert rep["live_api_calls"] == 0
        assert len(rep["checks"]) == 4
        assert all(c["passed"] is True for c in rep["checks"])

    by_id = {c["check_id"]: c for c in rep_strict["checks"]}
    assert by_id["C1"]["metrics"]["total_png_bytes"] == CANONICAL_TOTAL_PNG_BYTES == 56_875
    assert by_id["C1"]["metrics"]["total_png_bytes"] < MAX_ARENA_ASSET_BYTES
    assert by_id["C1"]["metrics"]["badges_verified"] == 8
    assert by_id["C2"]["metrics"]["sprites_checked"] == 10
    assert by_id["C2"]["metrics"]["item_sprites_checked"] == 6
    assert by_id["C3"]["metrics"]["packs_cc0"] == "5/5"
    assert by_id["C3"]["metrics"]["pack_sha256_cited_in_assets_md"] == "5/5"
    assert by_id["C4"]["metrics"]["leaking_sprite_employee"] is None
    assert by_id["C4"]["metrics"]["protected_path_violations"] == 0


def test_cli_json_and_strict_exit_zero_on_real_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_file = tmp_path / "report.json"
    rc = main(["--root", str(ROOT), "--strict", "--json", "--json-out", str(out_file)])
    assert rc == 0
    stdout_payload = json.loads(capsys.readouterr().out)
    file_payload = json.loads(out_file.read_text(encoding="utf-8"))
    assert stdout_payload["passed"] is True
    assert file_payload["passed"] is True
    assert stdout_payload["strict"] is True


def test_parse_png_ihdr_stdlib_struct_zero_pillow() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.add(node.module.split(".")[0])
    assert "PIL" not in imported_names
    assert "cv2" not in imported_names
    assert "imageio" not in imported_names

    sample = _make_valid_png(32, 48)
    assert parse_png_ihdr(sample) == (32, 48)

    assets_dir = ROOT / "docs" / "arena" / "assets"
    assert parse_png_ihdr((assets_dir / "kenney_roguelike_indoor.png").read_bytes()) == (458, 305)
    assert parse_png_ihdr((assets_dir / "kenney_roguelike_char.png").read_bytes()) == (918, 203)
    assert parse_png_ihdr((assets_dir / "kenney_rpg_urban_packed.png").read_bytes()) == (432, 288)
    assert parse_png_ihdr((assets_dir / "kenney_tiny_town_packed.png").read_bytes()) == (192, 176)
    for idx in range(8):
        bpath = assets_dir / "kenney_ui_badges" / f"badge_{idx:02d}.png"
        assert parse_png_ihdr(bpath.read_bytes()) == (16, 16)


def test_negative_corrupted_png_signature_fails_check1(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    sheet = staged / "docs" / "arena" / "assets" / "kenney_roguelike_indoor.png"
    raw = bytearray(sheet.read_bytes())
    raw[:8] = b"BADPNG\r\n"
    sheet.write_bytes(bytes(raw))

    c1 = check_png_ihdr_and_sha256(staged)
    assert c1.passed is False
    assert any("invalid PNG binary signature" in v for v in c1.violations)
    assert main(["--root", str(staged)]) == 1


def test_negative_corrupted_ihdr_and_sha256_mismatch_fails_check1(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    badge = staged / "docs" / "arena" / "assets" / "kenney_ui_badges" / "badge_00.png"
    badge.write_bytes(_make_valid_png(24, 16))

    c1 = check_png_ihdr_and_sha256(staged)
    assert c1.passed is False
    assert any("24x16" in v for v in c1.violations)
    assert any("sha256" in v for v in c1.violations)
    assert main(["--root", str(staged)]) == 1


def test_negative_missing_ui_badge_and_budget_cap_fails_check1(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    (staged / "docs" / "arena" / "assets" / "kenney_ui_badges" / "badge_07.png").unlink()
    mpath, manifest = _load_staged_manifest(staged)
    manifest["max_budget_bytes"] = MAX_ARENA_ASSET_BYTES + 1
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    c1 = check_png_ihdr_and_sha256(staged)
    assert c1.passed is False
    assert any("badge_07.png" in v for v in c1.violations)
    assert any("max_budget_bytes" in v for v in c1.violations)


def test_negative_out_of_bounds_sprite_rect_fails_check2(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    mpath, manifest = _load_staged_manifest(staged)
    manifest["sprites"]["desk"]["x"] = 450
    manifest["sprites"]["desk"].pop("col", None)
    manifest["sprites"]["desk"].pop("row", None)
    manifest["item_sprites"]["badge_alert"]["y"] = 4
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    c2 = check_sprite_coordinates_and_bounds(staged)
    assert c2.passed is False
    assert any("exceeds sheet_width" in v for v in c2.violations)
    assert any("exceeds sheet_height" in v for v in c2.violations)
    assert main(["--root", str(staged)]) == 1


def test_negative_col_row_formula_and_unknown_sheet_fails_check2(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    mpath, manifest = _load_staged_manifest(staged)
    manifest["sprites"]["chair"]["col"] = 17
    manifest["sprites"]["ghost_tile"] = {
        "sheet": "nonexistent_sheet",
        "x": 0,
        "y": 0,
        "w": 16,
        "h": 16,
    }
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    c2 = check_sprite_coordinates_and_bounds(staged)
    assert c2.passed is False
    assert any("col*(16+margin)" in v for v in c2.violations)
    assert any("unknown sheet alias" in v for v in c2.violations)


def test_negative_non_cc0_license_fails_check3(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    mpath, manifest = _load_staged_manifest(staged)
    manifest["packs"][0]["license"] = "CC-BY-4.0"
    manifest["attribution"]["license"] = "MIT"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    c3 = check_cc0_license_and_attribution(staged)
    assert c3.passed is False
    assert any("CC-BY-4.0" in v for v in c3.violations)
    assert any("MIT" in v for v in c3.violations)
    assert main(["--root", str(staged)]) == 1


def test_negative_missing_license_or_uncited_pack_sha256_fails_check3(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    (staged / "docs" / "arena" / "assets" / "LICENSE-CC0-1.0.txt").unlink()
    _, manifest = _load_staged_manifest(staged)
    target_sha = manifest["packs"][2]["sha256"]
    assets_md = staged / "docs" / "arena" / "ASSETS.md"
    assets_md.write_text(
        assets_md.read_text(encoding="utf-8").replace(target_sha, "0" * 64),
        encoding="utf-8",
    )

    c3 = check_cc0_license_and_attribution(staged)
    assert c3.passed is False
    assert any("LICENSE-CC0-1.0.txt" in v for v in c3.violations)
    assert any(target_sha in v for v in c3.violations)


def test_negative_non_null_leaking_sprite_employee_fails_check4(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    mpath, manifest = _load_staged_manifest(staged)
    manifest["leaking_sprite_employee"] = "e34"
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    c4 = check_pre_end_zero_leak_and_hygiene(staged)
    assert c4.passed is False
    assert any("leaking_sprite_employee" in v and "e34" in v for v in c4.violations)
    assert main(["--root", str(staged)]) == 1


def test_negative_secret_env_name_and_api_key_in_arena_fails_check4(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    assets_md = staged / "docs" / "arena" / "ASSETS.md"
    env_var_name = "CANARY_WORLD_" + "SECRET"
    fake_api_key = "AI" + "za" + "SyDummyArenaTestKey0123456789ab"
    assets_md.write_text(
        assets_md.read_text(encoding="utf-8") + f"\nRef: {env_var_name} and {fake_api_key}\n",
        encoding="utf-8",
    )

    c4 = check_pre_end_zero_leak_and_hygiene(staged)
    assert c4.passed is False
    assert any(env_var_name in v for v in c4.violations)
    assert any("google_api_key" in v for v in c4.violations)
    assert main(["--root", str(staged)]) == 1


def test_negative_non_ascii_or_em_dash_in_arena_fails_check4(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    seeds_md = staged / "docs" / "arena" / "SEEDS.md"
    seeds_md.write_text(
        seeds_md.read_text(encoding="utf-8") + f"\nBad punctuation {EM_DASH} here.\n",
        encoding="utf-8",
    )

    c4 = check_pre_end_zero_leak_and_hygiene(staged)
    assert c4.passed is False
    assert any("em-dash" in v or "non-ASCII" in v for v in c4.violations)


def test_negative_python_comment_in_script_fails_check4(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    scripts_dir = staged / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    bad_py = scripts_dir / "verify_arena_assets.py"
    bad_py.write_text(f"x = 1\n{HASH_CHAR} forbidden inline comment\n", encoding="utf-8")

    c4 = check_pre_end_zero_leak_and_hygiene(staged)
    assert c4.passed is False
    assert any("Python comment" in v for v in c4.violations)


def test_strict_mode_flags_unreferenced_orphan_png(tmp_path: Path) -> None:
    staged = _stage_arena_tree(tmp_path)
    orphan = staged / "docs" / "arena" / "assets" / "orphan_extra.png"
    orphan_bytes = _make_valid_png(16, 16)
    orphan.write_bytes(orphan_bytes)
    mpath, manifest = _load_staged_manifest(staged)
    manifest["total_png_bytes"] += len(orphan_bytes)
    manifest["packs"][0]["bytes"] += len(orphan_bytes)
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    rep_strict = verify_arena_assets(root=staged, strict=True)
    assert rep_strict["passed"] is False
    c1 = rep_strict["checks"][0]
    assert any("orphan_extra.png" in v for v in c1["violations"])


def test_self_and_script_hygiene_zero_comments_ascii_and_protected_matcher() -> None:
    co_author_marker = "Co-Authored-" + "By"
    for py_file in (SCRIPT_PATH, SELF_PATH):
        src = py_file.read_text(encoding="utf-8")
        assert EM_DASH not in src
        assert EN_DASH not in src
        assert HASH_CHAR not in src
        assert co_author_marker not in src
        assert all(ord(ch) < 128 for ch in src)
        tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
        assert [t for t in tokens if t.type == tokenize.COMMENT] == []

    for prot in (
        "canary/env.py",
        "canary/rules.py",
        "canary/reproduce.py",
        "canary/solver/policy.py",
        "harbor/task.yaml",
    ):
        assert is_protected_path(prot) is True

    for allowed in (
        "scripts/verify_arena_assets.py",
        "tests/test_verify_arena_assets.py",
        "docs/arena/ASSETS.md",
        "docs/arena/assets/sprite_pack_manifest.json",
    ):
        assert is_protected_path(allowed) is False
