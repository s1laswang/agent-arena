from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

from canary.env import Env
from canary.types import INVESTIGATIVE_TOOLS

ROOT = Path(__file__).resolve().parents[1]
DOM_JS_PATH = ROOT / "docs" / "arena" / "ui" / "dom.js"
ARENA_CSS_PATH = ROOT / "docs" / "arena" / "ui" / "arena.css"
SELF_TEST_PATH = Path(__file__).resolve()

HASH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
HASH_SPACE = HASH + " "


def _extract_js_const_literal(js_src: str, const_name: str) -> Any:
    pattern = re.compile(rf"export\s+const\s+{re.escape(const_name)}\s*=\s*([\[{{])")
    match = pattern.search(js_src)
    assert match is not None, f"missing export const {const_name} in dom.js"
    start = match.start(1)
    open_ch = match.group(1)
    close_ch = "]" if open_ch == "[" else "}"
    depth = 0
    in_str = False
    quote_ch = ""
    escaped = False
    end = -1
    for idx in range(start, len(js_src)):
        ch = js_src[idx]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_ch:
                in_str = False
            continue
        if ch in ('"', "'"):
            in_str = True
            quote_ch = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                end = idx + 1
                break
    assert end > start, f"unterminated literal for {const_name}"
    raw_lit = js_src[start:end]
    quoted_keys = re.sub(r'(?<=[{,\n])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'"\1":', raw_lit)
    clean_json = re.sub(r",\s*([\]}])", r"\1", quoted_keys)
    return json.loads(clean_json)


def test_arena_files_exist_ascii_clean_and_comment_free() -> None:
    for target in (DOM_JS_PATH, ARENA_CSS_PATH):
        assert target.is_file(), f"expected file to exist: {target}"
        raw = target.read_text(encoding="utf-8")
        assert len(raw.strip()) > 0, f"expected non-empty file: {target}"
        assert raw.isascii(), f"non-ASCII character found in {target.name}"
        assert EM_DASH not in raw, f"em dash found in {target.name}"
        assert EN_DASH not in raw, f"en dash found in {target.name}"
        assert UNICODE_MINUS not in raw, f"unicode minus found in {target.name}"
        assert SLASH_SLASH not in raw, f"line comment marker found in {target.name}"
        assert SLASH_STAR not in raw, f"block comment open marker found in {target.name}"
        assert STAR_SLASH not in raw, f"block comment close marker found in {target.name}"
        assert HASH_SPACE not in raw, f"hash-space comment marker found in {target.name}"


def test_self_python_file_has_zero_comments_and_zero_em_dashes() -> None:
    raw = SELF_TEST_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert EM_DASH not in raw
    assert HASH not in raw
    assert SLASH_SLASH not in raw
    assert SLASH_STAR not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []


def test_dom_js_exports_and_xss_safe_primitives() -> None:
    src = DOM_JS_PATH.read_text(encoding="utf-8")
    required_exports = (
        r"export\s+function\s+el\s*\(",
        r"export\s+function\s+clear\s*\(",
        r"export\s+function\s+pad2\s*\(",
        r"export\s+function\s+fmtScore\s*\(",
        r"export\s+const\s+MODE_DEFS\s*=",
        r"export\s+const\s+TOOL_DEFS\s*=",
        r"export\s+const\s+DEFAULT_DUEL_SEEDS\s*=",
    )
    for rx in required_exports:
        assert re.search(rx, src) is not None, f"missing expected export matching {rx}"

    for forbidden_sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert forbidden_sink not in src, f"XSS-unsafe sink {forbidden_sink} present in dom.js"

    for expected_dom_api in (
        "createElement",
        "createTextNode",
        "addEventListener",
        "setAttribute",
        "dataset",
        "aria-",
        "style",
        "replaceChildren",
        "globalThis.document",
    ):
        assert expected_dom_api in src, f"missing DOM support token {expected_dom_api} in dom.js"


def test_dom_js_mode_defs_and_default_duel_seeds() -> None:
    src = DOM_JS_PATH.read_text(encoding="utf-8")
    modes = _extract_js_const_literal(src, "MODE_DEFS")
    expected_modes = [
        {
            "id": "duel",
            "label": "Duel vs Gemini",
            "badge": "v1.4 hard",
            "desc": "Head to head vs committed gemini-4-carbon transcript + live solver on the same seed",
        },
        {
            "id": "solver",
            "label": "Beat the Solver",
            "badge": "public seeds",
            "desc": "Race the Bayesian canary-trap solver on the same world",
        },
        {
            "id": "mole",
            "label": "Be the Mole",
            "badge": "role swap",
            "desc": "Pick what to leak and when while the Bayesian solver hunts you",
        },
        {
            "id": "living",
            "label": "Living Office",
            "badge": "v1.6 preview",
            "desc": "Cached office chatter, rumours, and grudges across days (preview)",
        },
    ]
    assert modes == expected_modes

    seeds = _extract_js_const_literal(src, "DEFAULT_DUEL_SEEDS")
    assert seeds == [6, 26]


def test_dom_js_tool_defs_match_live_env_tools_spec_1_to_1() -> None:
    src = DOM_JS_PATH.read_text(encoding="utf-8")
    tool_defs = _extract_js_const_literal(src, "TOOL_DEFS")
    env_spec = Env("hard", 6).tools_spec()
    env_tool_names = [entry["name"] for entry in env_spec]
    assert len(env_tool_names) == 13
    assert list(tool_defs.keys()) == env_tool_names

    valid_groups = {"Investigate", "Trap", "Contain", "Clock", "Decide"}
    seen_codes: set[str] = set()
    for tool_name, meta in tool_defs.items():
        assert set(meta.keys()) == {"code", "name", "group", "costed", "desc"}
        assert isinstance(meta["code"], str) and 2 <= len(meta["code"]) <= 4
        assert meta["code"] not in seen_codes, f"duplicate tool code {meta['code']}"
        seen_codes.add(meta["code"])
        assert isinstance(meta["name"], str) and len(meta["name"]) > 0
        assert meta["group"] in valid_groups
        assert isinstance(meta["costed"], bool)
        assert meta["costed"] is (tool_name in INVESTIGATIVE_TOOLS)
        assert isinstance(meta["desc"], str) and len(meta["desc"]) >= 12


def test_dom_js_runtime_behavior_if_node_present() -> None:
    node_bin = shutil.which("node")
    if not node_bin:
        src = DOM_JS_PATH.read_text(encoding="utf-8")
        assert '"0.00"' in src
        assert '"+"' in src and '"-"' in src
        return

    probe = (
        f"import * as dom from {json.dumps(DOM_JS_PATH.as_uri())};"
        "const makeDoc = () => ({"
        "  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),"
        "  createElement: (tag) => {"
        "    const attrs = {}; const listeners = {}; const children = [];"
        "    return {"
        "      nodeType: 1, tagName: tag.toUpperCase(), className: '', dataset: {}, style: { cssText: '' },"
        "      attrs, listeners, childNodes: children,"
        "      setAttribute(k, v) { attrs[k] = String(v); },"
        "      addEventListener(ev, fn) { listeners[ev] = fn; },"
        "      appendChild(c) { children.push(c); return c; },"
        "      replaceChildren() { children.length = 0; }"
        "    };"
        "  }"
        "});"
        "const doc = makeDoc();"
        "let clicked = 0;"
        "const n = dom.el('button', {"
        "  document: doc, class: 'ghost active', dataset: { seedId: 6 },"
        "  'aria-selected': true, style: 'width: 40px', disabled: true, hidden: false,"
        "  onClick: () => { clicked += 1; }"
        "}, '<img src=x onerror=alert(1)>', dom.el('span', { document: doc }, 'ok'));"
        "n.listeners.click();"
        "if (clicked !== 1) process.exit(2);"
        "if (n.childNodes[0].nodeType !== 3) process.exit(3);"
        "if (dom.fmtScore(0.79) !== '+0.79') process.exit(4);"
        "if (dom.fmtScore(-1) !== '-1.00') process.exit(5);"
        "if (dom.fmtScore(0) !== '0.00' || dom.fmtScore(-0.001) !== '0.00') process.exit(6);"
        "if (dom.pad2(6) !== '06' || dom.pad2(14) !== '14') process.exit(7);"
        "dom.clear(n); if (n.childNodes.length !== 0) process.exit(8);"
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", probe],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr


def test_arena_css_balanced_braces_and_required_tokens() -> None:
    css = ARENA_CSS_PATH.read_text(encoding="utf-8")
    depth = 0
    for idx, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            assert depth >= 0, f"unmatched closing brace at offset {idx}"
    assert depth == 0, f"unbalanced braces in arena.css (final depth {depth})"
    assert css.count("(") == css.count(")")
    assert css.count("[") == css.count("]")

    required_vars = ("--paper:", "--sheet:", "--ink:", "--hl:", "--red:", "--ok:")
    for var_decl in required_vars:
        assert css.count(var_decl) >= 2, f"expected {var_decl} in both light and dark themes"

    assert "@media (prefers-color-scheme: dark)" in css
    assert "@media (min-width: 1024px)" in css
    assert "image-rendering: pixelated" in css
    assert "image-rendering: crisp-edges" in css

    office_canvas_id = HASH + "officeCanvas"
    asset_credits_id = HASH + "assetCredits"
    assert office_canvas_id in css
    assert asset_credits_id in css

    required_selectors = (
        ".arena-mast",
        ".mode-tabs",
        '.mode-tab[aria-selected="true"]',
        ".preview-badge",
        ".seed-bar",
        ".arena-clock-strip",
        ".day-ticks",
        ".value-bar",
        ".value-fill",
        ".value-drop-flash",
        ".office-stage-wrap",
        ".phase-badge",
        ".zone-legend",
        ".arena-split",
        ".pane-human",
        ".pane-ai",
        ".staff-roster",
        ".staff-row",
        ".suspect",
        ".cleared",
        ".canary-pill",
        ".variant-btn",
        ".cmd-bar",
        ".tool-btn",
        ".cmd-form",
        ".mole-panel",
        ".leak-picker-card",
        ".log-entry",
        ".leak-alert",
        "body.agent-raw",
        ".ai-card.gemini-pane",
        ".step-feed",
        ".sync-lock-badge",
        ".ai-card.solver-pane",
        ".suspect-pool-bar",
        ".social-drawer",
        ".rumour-item",
        ".grudge-pill",
        ".arena-end-card",
        ".h2h-table",
        ".first-catch-badge",
        ".share-box",
        ".leaderboard-dlg",
    )
    for sel in required_selectors:
        assert sel in css, f"missing required selector {sel} in arena.css"

    for phase in ("morning", "afternoon", "dusk", "night"):
        assert f'data-phase="{phase}"' in css, f"missing phase badge rule for {phase}"
