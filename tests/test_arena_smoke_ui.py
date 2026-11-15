from __future__ import annotations

import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SMOKE_SCRIPT = ROOT / "scripts" / "smoke_arena_ui.py"
UI_SRC_DIR = ROOT / "docs" / "arena" / "ui"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
CO_AUTHORED_MARKER = "Co-" + "Authored-" + "By"


def _load_smoke_module():
    spec = importlib.util.spec_from_file_location("smoke_arena_ui", SMOKE_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


smoke_mod = _load_smoke_module()


@pytest.fixture()
def opencode_tmp() -> Iterator[Path]:
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-arena-smoke-ui-") as tmp_dir:
        yield Path(tmp_dir)


def _copy_ui_tree(dest_root: Path) -> Path:
    dest_ui = dest_root / "docs" / "arena" / "ui"
    dest_ui.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(UI_SRC_DIR, dest_ui)
    return dest_ui


def test_owned_files_strict_hygiene() -> None:
    for py_path in (SMOKE_SCRIPT, SELF_PATH):
        assert py_path.is_file(), f"missing {py_path}"
        raw = py_path.read_text(encoding="utf-8")
        assert raw.isascii(), f"non-ASCII char in {py_path.name}"
        assert EM_DASH not in raw, f"em dash in {py_path.name}"
        assert EN_DASH not in raw, f"en dash in {py_path.name}"
        assert UNICODE_MINUS not in raw, f"unicode minus in {py_path.name}"
        assert HASH_CH not in raw, f"forbidden hash character in {py_path.name}"
        assert SLASH_SLASH not in raw, f"forbidden double-slash marker in {py_path.name}"
        assert SLASH_STAR not in raw, f"forbidden block-comment open in {py_path.name}"
        assert STAR_SLASH not in raw, f"forbidden block-comment close in {py_path.name}"
        assert CO_AUTHORED_MARKER not in raw, f"forbidden trailer marker in {py_path.name}"
        tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
        comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
        assert comments == [], f"unexpected python comments in {py_path.name}: {comments}"


def test_real_repo_smoke_arena_ui_check_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    node_bin = smoke_mod.resolve_node_bin()
    assert node_bin is not None, "expected headless Node binary to be available"

    rc = smoke_mod.main(["--check", "--root", str(ROOT), "--require-node", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["passed"] is True
    assert payload["elapsed_s"] < 3.0
    assert payload["modes_expected"] == ["duel", "solver", "mole", "living"]

    by_name = {item["name"]: item for item in payload["results"]}
    for check_name in smoke_mod.CHECK_NAMES:
        assert check_name in by_name
        assert by_name[check_name]["status"] == "PASS", by_name[check_name]
        assert by_name[check_name]["details"] == []

    proc = subprocess.run(
        [sys.executable, str(SMOKE_SCRIPT), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "3 PASS, 0 WARN, 0 FAIL" in proc.stdout


def test_index_html_asset_check_standalone_and_integrated(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "arena_bundle"
    _copy_ui_tree(repo)

    rc_absent = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_absent = json.loads(capsys.readouterr().out)
    assert rc_absent == 0
    assert payload_absent["passed"] is True
    assert payload_absent["index_html_present"] is False
    static_absent = {r["name"]: r for r in payload_absent["results"]}[smoke_mod.CHECK_STATIC]
    assert "standalone craft-arena mode" in static_absent["summary"]

    ext_cdn = "https:" + SLASH_SLASH + "cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js"
    frag_suffix = HASH_CH + "boot"
    valid_html = (
        "<!doctype html>\n"
        "<html><head>\n"
        '<link rel="stylesheet" href="./ui/arena.css?v=1">\n'
        f'<script src="{ext_cdn}"></script>\n'
        f'<script type="module" src="./ui/index.js{frag_suffix}"></script>\n'
        "</head><body>\n"
        '<div id="arenaRoot"></div>\n'
        '<script type="module">\n'
        'import { createAiDuelPanel } from "./ui/ai_duel_panel.js";\n'
        "window._panelFactory = createAiDuelPanel;\n"
        "</script>\n"
        "</body></html>\n"
    )
    index_path = repo / "docs" / "arena" / "index.html"
    index_path.write_text(valid_html, encoding="utf-8")

    rc_valid = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_valid = json.loads(capsys.readouterr().out)
    assert rc_valid == 0
    assert payload_valid["passed"] is True
    assert payload_valid["index_html_present"] is True
    static_valid = {r["name"]: r for r in payload_valid["results"]}[smoke_mod.CHECK_STATIC]
    assert static_valid["status"] == "PASS"
    assert "index.html verified (3 relative asset(s))" in static_valid["summary"]

    broken_html = (
        "<!doctype html>\n"
        "<html><head>\n"
        '<link rel="stylesheet" href="./ui/missing_theme.css">\n'
        '<script type="module" src="./missing_boot.js"></script>\n'
        "</head><body></body></html>\n"
    )
    index_path.write_text(broken_html, encoding="utf-8")
    rc_broken = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_broken = json.loads(capsys.readouterr().out)
    assert rc_broken == 1
    assert payload_broken["passed"] is False
    static_broken = {r["name"]: r for r in payload_broken["results"]}[smoke_mod.CHECK_STATIC]
    assert static_broken["status"] == "FAIL"
    assert any("missing_theme.css" in d for d in static_broken["details"])
    assert any("missing_boot.js" in d for d in static_broken["details"])


def test_smoke_catches_ui_hygiene_and_xss_violations(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "hygiene_case"
    ui_dir = _copy_ui_tree(repo)
    dom_js = ui_dir / "dom.js"
    orig_dom = dom_js.read_text(encoding="utf-8")

    dom_js.write_text(orig_dom + "\nexport function bad(n, s) { n.innerHTML = s; }\n", encoding="utf-8")
    rc_xss = smoke_mod.main(["--check", "--root", str(repo), "--json"])
    payload_xss = json.loads(capsys.readouterr().out)
    assert rc_xss == 1
    static_xss = {r["name"]: r for r in payload_xss["results"]}[smoke_mod.CHECK_STATIC]
    assert static_xss["status"] == "FAIL"
    assert any("innerHTML" in d for d in static_xss["details"])

    dom_js.write_text(orig_dom + f"\nconst note = 1; {SLASH_SLASH} bad\n", encoding="utf-8")
    rc_comm = smoke_mod.main(["--check", "--root", str(repo), "--json"])
    payload_comm = json.loads(capsys.readouterr().out)
    assert rc_comm == 1
    static_comm = {r["name"]: r for r in payload_comm["results"]}[smoke_mod.CHECK_STATIC]
    assert static_comm["status"] == "FAIL"
    assert any("comment marker" in d for d in static_comm["details"])

    dom_js.write_text(orig_dom + f'\nexport const BAD_DASH = "{EM_DASH}";\n', encoding="utf-8")
    rc_dash = smoke_mod.main(["--check", "--root", str(repo), "--json"])
    payload_dash = json.loads(capsys.readouterr().out)
    assert rc_dash == 1
    static_dash = {r["name"]: r for r in payload_dash["results"]}[smoke_mod.CHECK_STATIC]
    assert static_dash["status"] == "FAIL"
    assert any("non-ASCII" in d or "dash" in d for d in static_dash["details"])


def test_smoke_catches_firewall_and_pre_end_seal_regressions(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "regression_case"
    ui_dir = _copy_ui_tree(repo)
    app_js = ui_dir / "arena_app.js"
    orig_app = app_js.read_text(encoding="utf-8")

    broken_firewall = orig_app.replace(
        'if (state.mode === "solver" && (numSeed < 3000 || numSeed > 9999)) {\n      return;\n    }',
        "",
    )
    assert broken_firewall != orig_app
    app_js.write_text(broken_firewall, encoding="utf-8")
    rc_fw = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_fw = json.loads(capsys.readouterr().out)
    assert rc_fw == 1
    mode_fw = {r["name"]: r for r in payload_fw["results"]}[smoke_mod.CHECK_MODES]
    assert mode_fw["status"] == "FAIL"
    assert any("solver firewall failed" in d for d in mode_fw["details"])

    broken_seal = orig_app.replace(
        'args: isAccuse ? "[SEALED]" : step.args ? scrubPreEndObject(step.args) : {},',
        "args: step.args || {},",
    ).replace(
        'summary: isAccuse\n      ? "Accusation filed [SEALED]"\n      : String(step.summary || tool),',
        "summary: String(step.summary || tool),",
    ).replace(
        "sealed: isAccuse,",
        "sealed: false,",
    )
    assert broken_seal != orig_app
    app_js.write_text(broken_seal, encoding="utf-8")
    rc_seal = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_seal = json.loads(capsys.readouterr().out)
    assert rc_seal == 1
    mode_seal = {r["name"]: r for r in payload_seal["results"]}[smoke_mod.CHECK_MODES]
    assert mode_seal["status"] == "FAIL"
    assert any("pre-end" in d or "[SEALED]" in d for d in mode_seal["details"])


def test_smoke_catches_living_banner_and_mole_leak_regressions(
    opencode_tmp: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo = opencode_tmp / "living_mole_regression"
    ui_dir = _copy_ui_tree(repo)
    panel_js = ui_dir / "ai_duel_panel.js"
    orig_panel = panel_js.read_text(encoding="utf-8")

    broken_banner = orig_panel.replace(
        "Did NOT pass Gate B",
        "Cleared every gate",
    )
    assert broken_banner != orig_panel
    panel_js.write_text(broken_banner, encoding="utf-8")
    rc_banner = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_banner = json.loads(capsys.readouterr().out)
    assert rc_banner == 1
    boot_banner = {r["name"]: r for r in payload_banner["results"]}[smoke_mod.CHECK_BOOT]
    assert boot_banner["status"] == "FAIL"
    assert any("Gate B" in d for d in boot_banner["details"])
    panel_js.write_text(orig_panel, encoding="utf-8")

    app_js = ui_dir / "arena_app.js"
    orig_app = app_js.read_text(encoding="utf-8")
    broken_mole = orig_app.replace('"is_canary",\n', "")
    assert broken_mole != orig_app
    app_js.write_text(broken_mole, encoding="utf-8")
    rc_mole = smoke_mod.main(["--check", "--root", str(repo), "--require-node", "--json"])
    payload_mole = json.loads(capsys.readouterr().out)
    assert rc_mole == 1
    mode_mole = {r["name"]: r for r in payload_mole["results"]}[smoke_mod.CHECK_MODES]
    assert mode_mole["status"] == "FAIL"
    assert any("is_canary" in d for d in mode_mole["details"])


def test_static_fallback_when_node_unavailable() -> None:
    fallback_results = smoke_mod.smoke_arena_ui(ROOT, node_bin="", require_node=False)
    assert not any(r.status == "FAIL" for r in fallback_results)
    by_name = {r.name: r for r in fallback_results}
    assert by_name[smoke_mod.CHECK_STATIC].status == "PASS"
    assert by_name[smoke_mod.CHECK_BOOT].status == "WARN"
    assert by_name[smoke_mod.CHECK_MODES].status == "WARN"

    strict_results = smoke_mod.smoke_arena_ui(ROOT, node_bin="", require_node=True)
    by_strict = {r.name: r for r in strict_results}
    assert by_strict[smoke_mod.CHECK_BOOT].status == "FAIL"
    assert by_strict[smoke_mod.CHECK_MODES].status == "FAIL"
