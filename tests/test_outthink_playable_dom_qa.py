from __future__ import annotations

import ast
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tokenize
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
LIVE_DEMO_DIR = ROOT / "demo" / "out-think-gemini"
LIVE_INDEX_HTML = LIVE_DEMO_DIR / "index.html"
LIVE_STYLE_CSS = LIVE_DEMO_DIR / "style.css"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
HYPHEN_UNI = chr(0x2010)
NB_HYPHEN = chr(0x2011)
MINUS_SIGN = chr(0x2212)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
LT_CHAR = chr(60)
BANG_CHAR = chr(33)
HTML_COMMENT_OPEN = LT_CHAR + BANG_CHAR + "-" + "-"

VOID_HTML_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

REQUIRED_DOM_IDS: tuple[str, ...] = (
    "dataset-badge",
    "btn-prev-case",
    "case-select",
    "btn-next-case",
    "btn-reset-scores",
    "scoreboard-bar",
    "case-tier-badge",
    "case-title",
    "case-company",
    "case-seed-badge",
    "case-day-badge",
    "case-step-badge",
    "case-reward-badge",
    "case-status-pill",
    "btn-highlight-suspects",
    "highlight-summary",
    "phaser-stage",
    "stage-fallback",
    "suspect-roster",
    "dossier-clearance",
    "dossier-card",
    "btn-accuse",
    "btn-hold-fire",
    "btn-filter-suspect",
    "evidence-cutoff-note",
    "evidence-tabs",
    "count-canaries",
    "count-leaks",
    "count-access",
    "count-comms",
    "count-steps",
    "evidence-list",
    "reveal-panel",
    "provenance-footer",
    "provenance-summary",
    "asset-credits-list",
)

REQUIRED_EVIDENCE_TABS: tuple[str, ...] = (
    "canaries",
    "leaks",
    "access",
    "comms",
    "steps",
)

REQUIRED_CSS_CLASSES: tuple[str, ...] = (
    ".sr-only",
    ".app-shell",
    ".workspace-grid",
    ".stage-frame",
    ".suspect-roster",
    ".dossier-card",
    ".evidence-tabs",
    ".evidence-list",
    ".reveal-panel",
    ".verdict-banner",
    ".level-card",
)

OPTIONAL_LOCAL_SCRIPTS = frozenset(
    {
        "assets/manifest.js",
        "fallback_cases.js",
        "cases.js",
        "annotations.js",
        "failure_modes.js",
        "personas.js",
        "chatter.js",
        "evidence_cards.js",
        "reveal_card.js",
    }
)


class _StrictPlayableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.saw_doctype = False
        self.saw_comments: list[str] = []
        self.root: dict[str, Any] = {"kind": "root", "tag": "document", "attrs": {}, "children": []}
        self._stack: list[dict[str, Any]] = [self.root]
        self.unclosed_tags: list[str] = []
        self.mismatched_closes: list[tuple[str, str]] = []
        self.ids_seen: list[str] = []
        self.duplicate_ids: list[str] = []
        self._id_set: set[str] = set()
        self.scripts: list[dict[str, str]] = []
        self.stylesheets: list[str] = []

    def handle_decl(self, decl: str) -> None:
        if decl.strip().lower().startswith("doctype html"):
            self.saw_doctype = True

    def handle_comment(self, data: str) -> None:
        self.saw_comments.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attr_map: dict[str, str] = {}
        for k, v in attrs:
            key = k.lower()
            attr_map[key] = "" if v is None else v

        el_id = attr_map.get("id", "")
        if el_id:
            self.ids_seen.append(el_id)
            if el_id in self._id_set:
                self.duplicate_ids.append(el_id)
            self._id_set.add(el_id)

        if tag_lower == "script" and "src" in attr_map:
            self.scripts.append({"src": attr_map["src"], "type": attr_map.get("type", "")})
        if tag_lower == "link" and "stylesheet" in attr_map.get("rel", "").lower():
            if "href" in attr_map:
                self.stylesheets.append(attr_map["href"])

        node: dict[str, Any] = {
            "kind": "element",
            "tag": tag_lower,
            "attrs": attr_map,
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        if tag_lower not in VOID_HTML_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attr_map: dict[str, str] = {k.lower(): ("" if v is None else v) for k, v in attrs}
        el_id = attr_map.get("id", "")
        if el_id:
            self.ids_seen.append(el_id)
            if el_id in self._id_set:
                self.duplicate_ids.append(el_id)
            self._id_set.add(el_id)
        if tag_lower == "link" and "stylesheet" in attr_map.get("rel", "").lower():
            if "href" in attr_map:
                self.stylesheets.append(attr_map["href"])
        node: dict[str, Any] = {
            "kind": "element",
            "tag": tag_lower,
            "attrs": attr_map,
            "children": [],
        }
        self._stack[-1]["children"].append(node)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower in VOID_HTML_TAGS:
            return
        if len(self._stack) <= 1:
            self.mismatched_closes.append(("<empty>", tag_lower))
            return
        top = self._stack[-1]["tag"]
        if top == tag_lower:
            self._stack.pop()
            return
        self.mismatched_closes.append((top, tag_lower))
        for idx in range(len(self._stack) - 1, 0, -1):
            if self._stack[idx]["tag"] == tag_lower:
                while len(self._stack) > idx:
                    popped = self._stack.pop()
                    if popped["tag"] != tag_lower:
                        self.unclosed_tags.append(popped["tag"])
                return

    def handle_data(self, data: str) -> None:
        if data:
            self._stack[-1]["children"].append({"kind": "text", "text": data})

    def finish(self) -> None:
        self.close()
        while len(self._stack) > 1:
            popped = self._stack.pop()
            self.unclosed_tags.append(popped["tag"])


def parse_html_dom_tree(html_src: str) -> _StrictPlayableHTMLParser:
    parser = _StrictPlayableHTMLParser()
    parser.feed(html_src)
    parser.finish()
    return parser


def _iter_elements(node: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if node.get("kind") == "element":
        out.append(node)
    for child in node.get("children", []):
        if isinstance(child, dict):
            out.extend(_iter_elements(child))
    return out


def _element_text(node: dict[str, Any]) -> str:
    if node.get("kind") == "text":
        return str(node.get("text", ""))
    parts: list[str] = []
    for child in node.get("children", []):
        if isinstance(child, dict):
            parts.append(_element_text(child))
    return "".join(parts)


def validate_index_html_contract(html_src: str) -> dict[str, Any]:
    assert HTML_COMMENT_OPEN not in html_src, "HTML comments are not permitted in index.html"
    assert EM_DASH not in html_src and EN_DASH not in html_src, "Forbidden dash in index.html"

    parsed = parse_html_dom_tree(html_src)
    assert parsed.saw_doctype, "index.html must declare <!DOCTYPE html>"
    assert parsed.duplicate_ids == [], f"Duplicate DOM IDs in index.html: {parsed.duplicate_ids}"
    assert parsed.mismatched_closes == [], f"Mismatched HTML closing tags: {parsed.mismatched_closes}"
    assert parsed.unclosed_tags == [], f"Unclosed HTML tags: {parsed.unclosed_tags}"

    elements = _iter_elements(parsed.root)
    by_id: dict[str, dict[str, Any]] = {
        el["attrs"]["id"]: el for el in elements if "id" in el.get("attrs", {})
    }
    missing_ids = [req_id for req_id in REQUIRED_DOM_IDS if req_id not in by_id]
    assert missing_ids == [], f"Missing required playable DOM IDs: {missing_ids}"

    html_tags = [el for el in elements if el["tag"] == "html"]
    assert len(html_tags) == 1 and html_tags[0]["attrs"].get("lang"), "html[lang] is required"

    titles = [el for el in elements if el["tag"] == "title"]
    assert len(titles) == 1 and _element_text(titles[0]).strip(), "Non-empty <title> is required"

    metas = [el for el in elements if el["tag"] == "meta"]
    has_charset = any(m["attrs"].get("charset", "").lower() == "utf-8" for m in metas)
    has_viewport = any(m["attrs"].get("name", "").lower() == "viewport" for m in metas)
    assert has_charset, "meta charset=utf-8 is required"
    assert has_viewport, "meta viewport is required"

    for landmark in ("header", "main", "footer"):
        assert any(el["tag"] == landmark for el in elements), f"Missing <{landmark}> landmark"

    assert "style.css" in parsed.stylesheets, "index.html must link style.css"

    reveal_el = by_id["reveal-panel"]
    assert "hidden" in reveal_el["attrs"], "reveal-panel must start hidden before decision"
    assert reveal_el["attrs"].get("aria-live") == "polite", "reveal-panel requires aria-live=polite"

    fallback_el = by_id["stage-fallback"]
    assert "hidden" in fallback_el["attrs"], "stage-fallback must start hidden in markup"

    tabs_container = by_id["evidence-tabs"]
    assert tabs_container["attrs"].get("role") == "tablist", "evidence-tabs requires role=tablist"
    tab_buttons = [
        el for el in _iter_elements(tabs_container) if el["tag"] == "button" and "data-tab" in el["attrs"]
    ]
    found_tabs = tuple(btn["attrs"]["data-tab"] for btn in tab_buttons)
    assert found_tabs == REQUIRED_EVIDENCE_TABS, f"Expected tabs {REQUIRED_EVIDENCE_TABS}, got {found_tabs}"

    assert by_id["evidence-list"]["attrs"].get("role") == "tabpanel", "evidence-list requires role=tabpanel"
    assert by_id["suspect-roster"]["attrs"].get("role") == "listbox", "suspect-roster requires role=listbox"
    assert "aria-pressed" in by_id["btn-highlight-suspects"]["attrs"], "btn-highlight-suspects needs aria-pressed"
    assert "aria-pressed" in by_id["btn-filter-suspect"]["attrs"], "btn-filter-suspect needs aria-pressed"

    local_scripts = [
        s["src"]
        for s in parsed.scripts
        if not s["src"].startswith(("http://", "https://", "//"))
    ]
    assert "engine.js" in local_scripts, "index.html must load engine.js"
    assert "game.js" in local_scripts, "index.html must load game.js"
    assert local_scripts.index("engine.js") < local_scripts.index("game.js"), (
        "engine.js must load before game.js"
    )

    return {
        "root": parsed.root,
        "ids": list(by_id.keys()),
        "scripts": parsed.scripts,
        "local_scripts": local_scripts,
        "stylesheets": parsed.stylesheets,
    }


def validate_stylesheet_contract(css_src: str) -> dict[str, Any]:
    assert EM_DASH not in css_src and EN_DASH not in css_src, "Forbidden dash in style.css"
    block_open = SLASH + STAR
    assert block_open not in css_src, "Block comments are not permitted in style.css"

    lower_css = css_src.lower()
    assert "@import" not in lower_css, "External @import rules are forbidden in offline style.css"
    assert "http://" not in lower_css and "https://" not in lower_css, (
        "External HTTP(S) URLs are forbidden in offline style.css"
    )

    depth = 0
    for ch in css_src:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            assert depth >= 0, "Unbalanced closing brace in style.css"
    assert depth == 0, f"Unclosed brace(s) in style.css: depth={depth}"

    missing_classes = [cls for cls in REQUIRED_CSS_CLASSES if cls not in css_src]
    assert missing_classes == [], f"Missing required CSS selectors in style.css: {missing_classes}"

    return {
        "byte_length": len(css_src.encode("utf-8")),
        "media_query_count": len(re.findall(r"@media\b", css_src)),
    }


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}
    }
    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env

    opencode_candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ]
    for cand in opencode_candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env

    pytest.skip("no JavaScript runtime available")


JS_HEADLESS_DOM_PRELUDE = """
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const H = String.fromCharCode(35);

function buildHeadlessBrowser(domSpec, options) {
  const opts = options || {};
  let networkAttempts = 0;
  const uncaughtErrors = [];
  const rafQueue = [];
  let nextRafId = 1;
  const canvasContexts = [];

  function createClassList(el) {
    function syncFromAttr() {
      const raw = el._attrs["class"] || "";
      return raw.split(/\\s+/).filter(Boolean);
    }
    function writeClasses(list) {
      if (list.length > 0) {
        el._attrs["class"] = list.join(" ");
      } else {
        delete el._attrs["class"];
      }
    }
    return {
      add: function () {
        const set = syncFromAttr();
        for (let i = 0; i < arguments.length; i += 1) {
          const c = String(arguments[i] || "").trim();
          if (c && set.indexOf(c) < 0) set.push(c);
        }
        writeClasses(set);
      },
      remove: function () {
        let set = syncFromAttr();
        for (let i = 0; i < arguments.length; i += 1) {
          const c = String(arguments[i] || "").trim();
          set = set.filter((x) => x !== c);
        }
        writeClasses(set);
      },
      contains: function (cls) {
        return syncFromAttr().indexOf(String(cls || "").trim()) >= 0;
      },
      toggle: function (cls, force) {
        const token = String(cls || "").trim();
        if (!token) return false;
        const set = syncFromAttr();
        const exists = set.indexOf(token) >= 0;
        const shouldHave = force !== undefined ? Boolean(force) : !exists;
        if (shouldHave && !exists) {
          set.push(token);
          writeClasses(set);
        } else if (!shouldHave && exists) {
          writeClasses(set.filter((x) => x !== token));
        }
        return shouldHave;
      }
    };
  }

  function createMockCanvas2D(canvasEl) {
    const drawTexts = [];
    let drawCallCount = 0;
    const ctx = {
      canvas: canvasEl,
      fillStyle: "",
      strokeStyle: "",
      lineWidth: 1,
      font: "10px monospace",
      textAlign: "left",
      textBaseline: "alphabetic",
      globalAlpha: 1,
      imageSmoothingEnabled: false,
      drawTexts: drawTexts,
      getDrawCallCount: function () { return drawCallCount; },
      save: function () { drawCallCount += 1; },
      restore: function () { drawCallCount += 1; },
      beginPath: function () { drawCallCount += 1; },
      closePath: function () { drawCallCount += 1; },
      moveTo: function () { drawCallCount += 1; },
      lineTo: function () { drawCallCount += 1; },
      arc: function () { drawCallCount += 1; },
      rect: function () { drawCallCount += 1; },
      clip: function () { drawCallCount += 1; },
      fill: function () { drawCallCount += 1; },
      stroke: function () { drawCallCount += 1; },
      fillRect: function () { drawCallCount += 1; },
      strokeRect: function () { drawCallCount += 1; },
      clearRect: function () { drawTexts.length = 0; drawCallCount += 1; },
      drawImage: function () { drawCallCount += 1; },
      setLineDash: function () {},
      translate: function () {},
      scale: function () {},
      rotate: function () {},
      measureText: function (txt) { return { width: String(txt == null ? "" : txt).length * 6 }; },
      createLinearGradient: function () { return { addColorStop: function () {} }; },
      createRadialGradient: function () { return { addColorStop: function () {} }; },
      fillText: function (txt, x, y) {
        drawCallCount += 1;
        if (drawTexts.length > 600) drawTexts.shift();
        drawTexts.push({ text: String(txt == null ? "" : txt), x: Number(x) || 0, y: Number(y) || 0 });
      },
      strokeText: function (txt) {
        drawCallCount += 1;
        drawTexts.push({ text: String(txt == null ? "" : txt), x: 0, y: 0 });
      }
    };
    canvasContexts.push(ctx);
    return ctx;
  }

  class DOMEvent {
    constructor(type, init) {
      this.type = String(type);
      const cfg = init || {};
      this.bubbles = cfg.bubbles !== undefined ? Boolean(cfg.bubbles) : true;
      this.cancelable = cfg.cancelable !== undefined ? Boolean(cfg.cancelable) : true;
      this.clientX = cfg.clientX !== undefined ? Number(cfg.clientX) : 0;
      this.clientY = cfg.clientY !== undefined ? Number(cfg.clientY) : 0;
      this.key = cfg.key || "";
      this.defaultPrevented = false;
      this.propagationStopped = false;
      this.target = null;
      this.currentTarget = null;
    }
    preventDefault() {
      if (this.cancelable) this.defaultPrevented = true;
    }
    stopPropagation() {
      this.propagationStopped = true;
    }
  }

  class DOMText {
    constructor(text, ownerDocument) {
      this.nodeType = 3;
      this.data = String(text == null ? "" : text);
      this.parentNode = null;
      this.ownerDocument = ownerDocument;
    }
    get textContent() {
      return this.data;
    }
    set textContent(val) {
      this.data = String(val == null ? "" : val);
    }
  }

  function matchesSimplePart(el, part) {
    if (!el || el.nodeType !== 1 || !part) return false;
    let rem = part.trim();
    if (!rem) return false;

    const attrRegex = /\\[([a-zA-Z0-9_-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\\]]*)))?\\]/g;
    const attrChecks = [];
    rem = rem.replace(attrRegex, function (_m, name, dq, sq, bare) {
      const expected = dq !== undefined ? dq : sq !== undefined ? sq : bare !== undefined ? bare : null;
      attrChecks.push({ name: name.toLowerCase(), expected: expected });
      return "";
    });

    const classChecks = [];
    rem = rem.replace(/\\.([a-zA-Z0-9_-]+)/g, function (_m, cls) {
      classChecks.push(cls);
      return "";
    });

    let idCheck = null;
    if (rem.indexOf(H) >= 0) {
      const idx = rem.indexOf(H);
      idCheck = rem.slice(idx + 1);
      rem = rem.slice(0, idx);
    }

    const tagCheck = rem.trim().toLowerCase();
    if (tagCheck && tagCheck !== "*" && el.tagName.toLowerCase() !== tagCheck) {
      return false;
    }
    if (idCheck !== null && el.id !== idCheck) {
      return false;
    }
    for (let i = 0; i < classChecks.length; i += 1) {
      if (!el.classList.contains(classChecks[i])) return false;
    }
    for (let j = 0; j < attrChecks.length; j += 1) {
      const chk = attrChecks[j];
      if (!el.hasAttribute(chk.name)) return false;
      if (chk.expected !== null && el.getAttribute(chk.name) !== chk.expected) return false;
    }
    return true;
  }

  function matchesSelectorChain(el, selector) {
    const groups = String(selector || "").split(",");
    for (let g = 0; g < groups.length; g += 1) {
      const tokens = groups[g].trim().split(/\\s+/).filter(Boolean);
      if (tokens.length === 0) continue;
      if (!matchesSimplePart(el, tokens[tokens.length - 1])) continue;
      let cur = el.parentNode;
      let ti = tokens.length - 2;
      while (ti >= 0 && cur) {
        if (cur.nodeType === 1 && matchesSimplePart(cur, tokens[ti])) {
          ti -= 1;
        }
        cur = cur.parentNode;
      }
      if (ti < 0) return true;
    }
    return false;
  }

  class DOMElement {
    constructor(tagName, ownerDocument) {
      this.nodeType = 1;
      this.tagName = String(tagName || "div").toUpperCase();
      this.ownerDocument = ownerDocument;
      this.parentNode = null;
      this.childNodes = [];
      this._attrs = {};
      this._listeners = {};
      this.style = { cssText: "", cursor: "default" };
      this.classList = createClassList(this);
      this.width = this.tagName === "CANVAS" ? 960 : 0;
      this.height = this.tagName === "CANVAS" ? 520 : 0;
      this._ctx2d = null;
      this._selected = false;
      this._value = undefined;
      this.scrollCalls = 0;
    }
    get id() {
      return this._attrs["id"] || "";
    }
    set id(v) {
      if (v === null || v === undefined || v === "") {
        delete this._attrs["id"];
      } else {
        this._attrs["id"] = String(v);
      }
    }
    get className() {
      return this._attrs["class"] || "";
    }
    set className(v) {
      const s = String(v == null ? "" : v).trim();
      if (s) this._attrs["class"] = s;
      else delete this._attrs["class"];
    }
    get hidden() {
      return Object.prototype.hasOwnProperty.call(this._attrs, "hidden");
    }
    set hidden(v) {
      if (v) this._attrs["hidden"] = "";
      else delete this._attrs["hidden"];
    }
    get disabled() {
      return Object.prototype.hasOwnProperty.call(this._attrs, "disabled");
    }
    set disabled(v) {
      if (v) this._attrs["disabled"] = "";
      else delete this._attrs["disabled"];
    }
    get type() {
      return this._attrs["type"] || (this.tagName === "BUTTON" ? "submit" : "");
    }
    set type(v) {
      this._attrs["type"] = String(v == null ? "" : v);
    }
    get selected() {
      return Boolean(this._selected || Object.prototype.hasOwnProperty.call(this._attrs, "selected"));
    }
    set selected(v) {
      const flag = Boolean(v);
      this._selected = flag;
      if (flag) this._attrs["selected"] = "";
      else delete this._attrs["selected"];
      if (flag && this.parentNode && this.parentNode.tagName === "SELECT") {
        const siblings = this.parentNode.children;
        for (let i = 0; i < siblings.length; i += 1) {
          if (siblings[i] !== this && siblings[i].tagName === "OPTION") {
            siblings[i]._selected = false;
            delete siblings[i]._attrs["selected"];
          }
        }
      }
    }
    get value() {
      if (this.tagName === "SELECT") {
        const optsList = this.children.filter((c) => c.tagName === "OPTION");
        for (let i = 0; i < optsList.length; i += 1) {
          if (optsList[i].selected) return optsList[i].value;
        }
        return optsList.length > 0 ? optsList[0].value : "";
      }
      if (this._value !== undefined) return this._value;
      if (Object.prototype.hasOwnProperty.call(this._attrs, "value")) return this._attrs["value"];
      return this.textContent;
    }
    set value(v) {
      const strVal = String(v == null ? "" : v);
      if (this.tagName === "SELECT") {
        const optsList = this.children.filter((c) => c.tagName === "OPTION");
        for (let i = 0; i < optsList.length; i += 1) {
          const match = optsList[i].value === strVal;
          optsList[i]._selected = match;
          if (match) optsList[i]._attrs["selected"] = "";
          else delete optsList[i]._attrs["selected"];
        }
        return;
      }
      this._value = strVal;
      this._attrs["value"] = strVal;
    }
    get children() {
      return this.childNodes.filter((n) => n.nodeType === 1);
    }
    get firstChild() {
      return this.childNodes.length > 0 ? this.childNodes[0] : null;
    }
    get textContent() {
      let acc = "";
      for (let i = 0; i < this.childNodes.length; i += 1) {
        acc += this.childNodes[i].textContent;
      }
      return acc;
    }
    set textContent(val) {
      for (let i = 0; i < this.childNodes.length; i += 1) {
        this.childNodes[i].parentNode = null;
      }
      this.childNodes = [];
      const str = String(val == null ? "" : val);
      if (str.length > 0) {
        const tn = new DOMText(str, this.ownerDocument);
        tn.parentNode = this;
        this.childNodes.push(tn);
      }
    }
    get innerHTML() {
      return this.textContent;
    }
    set innerHTML(val) {
      this.textContent = val;
    }
    setAttribute(name, val) {
      const k = String(name).toLowerCase();
      this._attrs[k] = String(val == null ? "" : val);
    }
    getAttribute(name) {
      const k = String(name).toLowerCase();
      return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
    }
    hasAttribute(name) {
      return Object.prototype.hasOwnProperty.call(this._attrs, String(name).toLowerCase());
    }
    removeAttribute(name) {
      delete this._attrs[String(name).toLowerCase()];
    }
    appendChild(child) {
      if (!child) return child;
      if (child.parentNode) {
        child.parentNode.removeChild(child);
      }
      child.parentNode = this;
      this.childNodes.push(child);
      if (this.tagName === "SELECT" && child.tagName === "OPTION" && child.selected) {
        for (let i = 0; i < this.children.length; i += 1) {
          if (this.children[i] !== child && this.children[i].tagName === "OPTION") {
            this.children[i]._selected = false;
            delete this.children[i]._attrs["selected"];
          }
        }
      }
      return child;
    }
    removeChild(child) {
      const idx = this.childNodes.indexOf(child);
      if (idx >= 0) {
        this.childNodes.splice(idx, 1);
        child.parentNode = null;
      }
      return child;
    }
    addEventListener(type, fn) {
      const k = String(type);
      if (!this._listeners[k]) this._listeners[k] = [];
      if (typeof fn === "function") this._listeners[k].push(fn);
    }
    removeEventListener(type, fn) {
      const k = String(type);
      if (!this._listeners[k]) return;
      this._listeners[k] = this._listeners[k].filter((f) => f !== fn);
    }
    dispatchEvent(ev) {
      const eventObj = ev instanceof DOMEvent ? ev : new DOMEvent(ev && ev.type ? ev.type : "custom", ev);
      eventObj.target = eventObj.target || this;
      let cur = this;
      while (cur) {
        eventObj.currentTarget = cur;
        const list = (cur._listeners && cur._listeners[eventObj.type]) ? cur._listeners[eventObj.type].slice() : [];
        for (let i = 0; i < list.length; i += 1) {
          list[i].call(cur, eventObj);
        }
        if (!eventObj.bubbles || eventObj.propagationStopped) break;
        cur = cur.parentNode;
      }
      return !eventObj.defaultPrevented;
    }
    click() {
      if (this.disabled) return;
      this.dispatchEvent(new DOMEvent("click", { bubbles: true, cancelable: true }));
    }
    closest(selector) {
      let cur = this;
      while (cur && cur.nodeType === 1) {
        if (matchesSelectorChain(cur, selector)) return cur;
        cur = cur.parentNode;
      }
      return null;
    }
    querySelectorAll(selector) {
      const out = [];
      function walk(node) {
        const kids = node.children || [];
        for (let i = 0; i < kids.length; i += 1) {
          const k = kids[i];
          if (matchesSelectorChain(k, selector)) out.push(k);
          walk(k);
        }
      }
      walk(this);
      return out;
    }
    querySelector(selector) {
      const all = this.querySelectorAll(selector);
      return all.length > 0 ? all[0] : null;
    }
    scrollIntoView() {
      this.scrollCalls += 1;
    }
    getBoundingClientRect() {
      return {
        left: 0,
        top: 0,
        width: this.width || 960,
        height: this.height || 520,
        right: this.width || 960,
        bottom: this.height || 520
      };
    }
    getContext(kind) {
      if (kind === "2d") {
        if (!this._ctx2d) this._ctx2d = createMockCanvas2D(this);
        return this._ctx2d;
      }
      return null;
    }
  }

  class DOMDocument {
    constructor() {
      this.nodeType = 9;
      this.readyState = "complete";
      this._listeners = {};
      this.documentElement = null;
      this.head = null;
      this.body = null;
    }
    createElement(tag) {
      return new DOMElement(tag, this);
    }
    createTextNode(txt) {
      return new DOMText(txt, this);
    }
    addEventListener(type, fn) {
      const k = String(type);
      if (!this._listeners[k]) this._listeners[k] = [];
      if (typeof fn === "function") this._listeners[k].push(fn);
    }
    removeEventListener(type, fn) {
      const k = String(type);
      if (!this._listeners[k]) return;
      this._listeners[k] = this._listeners[k].filter((f) => f !== fn);
    }
    getElementById(id) {
      const target = String(id || "");
      if (!target || !this.documentElement) return null;
      function find(el) {
        if (el.id === target) return el;
        const kids = el.children;
        for (let i = 0; i < kids.length; i += 1) {
          const hit = find(kids[i]);
          if (hit) return hit;
        }
        return null;
      }
      return find(this.documentElement);
    }
    querySelectorAll(selector) {
      return this.documentElement ? this.documentElement.querySelectorAll(selector) : [];
    }
    querySelector(selector) {
      return this.documentElement ? this.documentElement.querySelector(selector) : null;
    }
  }

  const document = new DOMDocument();

  function hydrateNode(spec) {
    if (spec.kind === "text") {
      return document.createTextNode(spec.text || "");
    }
    const el = document.createElement(spec.tag || "div");
    const attrs = spec.attrs || {};
    const keys = Object.keys(attrs);
    for (let i = 0; i < keys.length; i += 1) {
      el.setAttribute(keys[i], attrs[keys[i]]);
    }
    const children = spec.children || [];
    for (let c = 0; c < children.length; c += 1) {
      el.appendChild(hydrateNode(children[c]));
    }
    if (el.tagName === "HTML") document.documentElement = el;
    if (el.tagName === "HEAD") document.head = el;
    if (el.tagName === "BODY") document.body = el;
    return el;
  }

  const rootKids = (domSpec && domSpec.children) ? domSpec.children : [];
  for (let i = 0; i < rootKids.length; i += 1) {
    if (rootKids[i].kind === "element") {
      hydrateNode(rootKids[i]);
    }
  }

  function blockNetwork(apiName) {
    networkAttempts += 1;
    throw new Error("Blocked live network call in playable DOM QA: " + apiName);
  }

  class MockImage {
    constructor() {
      this._src = "";
      this.complete = false;
      this.width = 0;
      this.height = 0;
      this.naturalWidth = 0;
      this.naturalHeight = 0;
      this.onload = null;
      this.onerror = null;
    }
    get src() {
      return this._src;
    }
    set src(val) {
      const s = String(val == null ? "" : val);
      this._src = s;
      if (s.startsWith("http://") || s.startsWith("https://") || s.startsWith("//")) {
        blockNetwork("Image.src=" + s);
      }
      this.complete = true;
      this.width = 16;
      this.height = 16;
      this.naturalWidth = 16;
      this.naturalHeight = 16;
    }
  }

  const sandbox = {
    console: {
      log: function () {},
      info: function () {},
      warn: function () {},
      error: function (msg) { uncaughtErrors.push(String(msg)); }
    },
    document: document,
    Event: DOMEvent,
    CustomEvent: DOMEvent,
    Image: MockImage,
    navigator: {
      userAgent: "OutThinkPlayableDomQA/1.0",
      sendBeacon: function () { blockNetwork("navigator.sendBeacon"); }
    },
    location: { protocol: "file:", href: "file:///demo/out-think-gemini/index.html" },
    performance: { now: function () { return 1200; } },
    requestAnimationFrame: function (cb) {
      const id = nextRafId;
      nextRafId += 1;
      rafQueue.push({ id: id, cb: cb });
      return id;
    },
    cancelAnimationFrame: function (id) {
      for (let i = rafQueue.length - 1; i >= 0; i -= 1) {
        if (rafQueue[i].id === id) rafQueue.splice(i, 1);
      }
    },
    setTimeout: function (cb) {
      const id = nextRafId;
      nextRafId += 1;
      rafQueue.push({ id: id, cb: cb });
      return id;
    },
    clearTimeout: function () {},
    fetch: function () { blockNetwork("fetch"); },
    XMLHttpRequest: function () { blockNetwork("XMLHttpRequest"); },
    WebSocket: function () { blockNetwork("WebSocket"); },
    EventSource: function () { blockNetwork("EventSource"); },
    Math: Math,
    Number: Number,
    String: String,
    Boolean: Boolean,
    Array: Array,
    Object: Object,
    JSON: JSON,
    Date: Date,
    RegExp: RegExp,
    Error: Error,
    TypeError: TypeError,
    RangeError: RangeError,
    Map: Map,
    Set: Set,
    Promise: Promise,
    parseInt: parseInt,
    parseFloat: parseFloat,
    isNaN: isNaN,
    isFinite: isFinite,
    encodeURIComponent: encodeURIComponent,
    decodeURIComponent: decodeURIComponent
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;

  const context = vm.createContext(sandbox);
  const loadedScripts = [];
  const skippedExternalScripts = [];
  const missingOptionalScripts = [];
  const skipLocalSet = new Set(opts.skipLocalScripts || []);

  const scripts = opts.scripts || [];
  for (let i = 0; i < scripts.length; i += 1) {
    const src = scripts[i].src || "";
    if (!src) continue;
    if (src.startsWith("http://") || src.startsWith("https://") || src.startsWith("//")) {
      skippedExternalScripts.push(src);
      continue;
    }
    if (skipLocalSet.has(src)) {
      missingOptionalScripts.push(src);
      continue;
    }
    const fullPath = path.resolve(opts.demoDir, src);
    if (!fs.existsSync(fullPath)) {
      missingOptionalScripts.push(src);
      continue;
    }
    const code = fs.readFileSync(fullPath, "utf8");
    try {
      vm.runInContext(code, context, { filename: src });
      loadedScripts.push(src);
    } catch (err) {
      uncaughtErrors.push(src + ": " + String(err && err.stack ? err.stack : err));
    }
  }

  function visibleText(node) {
    if (!node) return "";
    if (node.nodeType === 3) return node.data || "";
    if (node.nodeType === 1 && node.hidden) return "";
    let out = "";
    const kids = node.childNodes || [];
    for (let i = 0; i < kids.length; i += 1) {
      out += visibleText(kids[i]);
    }
    return out;
  }

  return {
    window: sandbox,
    document: document,
    DOMEvent: DOMEvent,
    canvasContexts: canvasContexts,
    visibleText: visibleText,
    loadedScripts: loadedScripts,
    skippedExternalScripts: skippedExternalScripts,
    missingOptionalScripts: missingOptionalScripts,
    getNetworkAttempts: function () { return networkAttempts; },
    getUncaughtErrors: function () { return uncaughtErrors.slice(); }
  };
}
"""


def _run_dom_harness(
    demo_dir: Path,
    js_action_body: str,
    *,
    skip_local_scripts: list[str] | None = None,
    extra_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index_path = demo_dir / "index.html"
    html_report = validate_index_html_contract(index_path.read_text(encoding="utf-8"))

    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    payload = {
        "domSpec": html_report["root"],
        "options": {
            "demoDir": str(demo_dir),
            "scripts": html_report["scripts"],
            "skipLocalScripts": skip_local_scripts or [],
        },
        "extra": extra_payload or {},
    }
    run_env["OUTTHINK_DOM_QA_PAYLOAD"] = json.dumps(payload)

    full_js = (
        JS_HEADLESS_DOM_PRELUDE
        + "\nconst QA_INPUT = JSON.parse(process.env.OUTTHINK_DOM_QA_PAYLOAD);\n"
        + "const env = buildHeadlessBrowser(QA_INPUT.domSpec, QA_INPUT.options);\n"
        + "const EXTRA = QA_INPUT.extra;\n"
        + "const result = (() => {\n"
        + js_action_body
        + "\n})();\n"
        + "process.stdout.write(JSON.stringify({\n"
        + "  loadedScripts: env.loadedScripts,\n"
        + "  skippedExternalScripts: env.skippedExternalScripts,\n"
        + "  missingOptionalScripts: env.missingOptionalScripts,\n"
        + "  networkAttempts: env.getNetworkAttempts(),\n"
        + "  uncaughtErrors: env.getUncaughtErrors(),\n"
        + "  result: result\n"
        + "}));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, full_js],
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, (
        f"DOM harness exited {proc.returncode}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    )
    return json.loads(proc.stdout)


def _write_synthetic_playable_demo(demo_dir: Path) -> Path:
    demo_dir.mkdir(parents=True, exist_ok=True)
    html_src = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Out-Think Gemini | Synthetic Playable DOM QA</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <div class="app-shell">
    <header class="top-bar">
      <div class="brand-cluster">
        <h1>OUT-THINK GEMINI</h1>
        <span id="dataset-badge" class="pill">Replay Corpus</span>
      </div>
      <div class="case-nav" role="navigation" aria-label="Scenario Navigation">
        <button id="btn-prev-case" type="button">Prev</button>
        <label class="sr-only" for="case-select">Select Scenario</label>
        <select id="case-select"></select>
        <button id="btn-next-case" type="button">Next</button>
        <button id="btn-reset-scores" type="button">Reset</button>
      </div>
    </header>
    <section id="scoreboard-bar" aria-label="Running Scoreboard"></section>
    <section class="case-briefing">
      <span id="case-tier-badge">HARD</span>
      <h2 id="case-title">Loading</h2>
      <span id="case-company">Company</span>
      <span id="case-seed-badge">Seed 0</span>
      <strong id="case-day-badge">Day 1</strong>
      <span id="case-step-badge">Step 0</span>
      <strong id="case-reward-badge">+0.50</strong>
      <strong id="case-status-pill">AWAITING CALL</strong>
    </section>
    <main class="workspace-grid">
      <section class="left-column">
        <div class="stage-panel">
          <span id="highlight-summary">Click a station</span>
          <button id="btn-highlight-suspects" type="button" aria-pressed="false">Highlight</button>
          <div class="stage-frame">
            <div id="phaser-stage" role="region" aria-label="Stage"></div>
            <div id="stage-fallback" hidden></div>
          </div>
          <div id="suspect-roster" class="suspect-roster" role="listbox" aria-label="Suspects"></div>
        </div>
        <div class="decision-panel">
          <span id="dossier-clearance">Standard</span>
          <div id="dossier-card" class="dossier-card"></div>
          <button id="btn-accuse" type="button">ACCUSE e01 NOW</button>
          <button id="btn-hold-fire" type="button">HOLD FIRE - KEEP INVESTIGATING</button>
        </div>
      </section>
      <section class="right-column">
        <span id="evidence-cutoff-note">Pre-decision</span>
        <button id="btn-filter-suspect" type="button" aria-pressed="false">Filter: All Staff</button>
        <div id="evidence-tabs" class="evidence-tabs" role="tablist">
          <button type="button" role="tab" data-tab="canaries" aria-selected="true">Canaries <span id="count-canaries">0</span></button>
          <button type="button" role="tab" data-tab="leaks" aria-selected="false">Leaks <span id="count-leaks">0</span></button>
          <button type="button" role="tab" data-tab="access" aria-selected="false">Access <span id="count-access">0</span></button>
          <button type="button" role="tab" data-tab="comms" aria-selected="false">Comms <span id="count-comms">0</span></button>
          <button type="button" role="tab" data-tab="steps" aria-selected="false">Steps <span id="count-steps">0</span></button>
        </div>
        <div id="evidence-list" class="evidence-list" role="tabpanel"></div>
      </section>
    </main>
    <section id="reveal-panel" class="reveal-panel" aria-live="polite" hidden></section>
    <footer id="provenance-footer">
      <div id="provenance-summary"></div>
      <div id="asset-credits-list"></div>
    </footer>
  </div>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/phaser/3.80.1/phaser.min.js"></script>
  <script src="cases.js"></script>
  <script src="engine.js"></script>
  <script src="scene.js"></script>
  <script src="game.js"></script>
</body>
</html>
"""
    css_src = """
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; }
.app-shell { display: flex; flex-direction: column; background: rgb(7, 11, 18); color: rgb(236, 242, 252); }
.workspace-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.stage-frame { min-height: 280px; }
.suspect-roster { display: flex; flex-wrap: wrap; gap: 6px; }
.dossier-card { padding: 10px; }
.evidence-tabs { display: flex; gap: 6px; }
.evidence-list { min-height: 200px; }
.reveal-panel { padding: 12px; }
.verdict-banner { display: flex; justify-content: space-between; }
.level-card { padding: 8px; }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } }
"""
    cases_payload = {
        "meta": {
            "title": "Synthetic Out-Think Suite",
            "tiers_version": "v1.4",
            "total_episodes": 24,
            "total_cost_usd": 4.25,
        },
        "cases": [
            {
                "id": "syn-hold-1",
                "title": "Ambiguous Canary Pair at Polar Bio",
                "tier": "medium",
                "seed": 11,
                "company": "Polar Bio",
                "decision_day": 4,
                "decision_step": 6,
                "value_at_decision": 0.70,
                "suspects": [
                    {
                        "id": "e01",
                        "name": "Aino Laine",
                        "dept": "Ops",
                        "role": "Lead",
                        "clearance": "high",
                        "eliminated": True,
                        "canary_hits": 0,
                        "after_hours_count": 0,
                        "persona_note": "Cleared by day-2 intersection.",
                    },
                    {
                        "id": "e02",
                        "name": "Mika Salo",
                        "dept": "Data",
                        "role": "Analyst",
                        "clearance": "high",
                        "eliminated": False,
                        "canary_hits": 1,
                        "after_hours_count": 1,
                        "persona_note": "On variant B distribution list.",
                    },
                    {
                        "id": "e03",
                        "name": "Noora Kivi",
                        "dept": "Sales",
                        "role": "Director",
                        "clearance": "high",
                        "eliminated": False,
                        "canary_hits": 1,
                        "after_hours_count": 2,
                        "persona_note": "Exported slide deck after hours.",
                    },
                ],
                "canaries": [
                    {
                        "canary_id": "c01",
                        "doc_id": "doc_trial",
                        "day_planted": 2,
                        "variants": [
                            {"variant": "A", "recipients": ["e01"]},
                            {"variant": "B", "recipients": ["e02", "e03"]},
                        ],
                        "leaked_variant": "B",
                    },
                    {
                        "canary_id": "c99_future",
                        "doc_id": "doc_future_spoiler",
                        "day_planted": 7,
                        "variants": [{"variant": "Z", "recipients": ["e03"]}],
                        "leaked_variant": "Z",
                    },
                ],
                "leaks": [
                    {
                        "day": 3,
                        "doc_id": "doc_trial",
                        "canary_id": "c01",
                        "leaked_variant": "B",
                        "channel": "newsletter",
                        "summary": "Pre-decision leak of variant B.",
                    },
                    {
                        "day": 7,
                        "doc_id": "doc_future_spoiler",
                        "canary_id": "c99_future",
                        "leaked_variant": "Z",
                        "channel": "wire",
                        "summary": "FUTURE_SPOILER_LEAK_DAY_7",
                    },
                ],
                "access_logs": [
                    {
                        "day": 3,
                        "employee": "e03",
                        "doc_id": "doc_trial",
                        "after_hours": True,
                        "action": "export",
                    },
                    {
                        "day": 7,
                        "employee": "e03",
                        "doc_id": "FUTURE_SPOILER_ACCESS_DAY_7",
                        "after_hours": True,
                        "action": "exfil",
                    },
                ],
                "comms": [
                    {
                        "day": 3,
                        "kind": "chat",
                        "speaker": "e02",
                        "target": "e03",
                        "topic": "readout",
                        "text": "Did you check the trial memo?",
                    },
                    {
                        "day": 7,
                        "kind": "chat",
                        "speaker": "e03",
                        "target": "e02",
                        "topic": "spoiler",
                        "text": "FUTURE_SPOILER_COMM_DAY_7",
                    },
                ],
                "tool_steps": [
                    {
                        "t": 4,
                        "day": 3,
                        "tool": "plant_canary",
                        "args": {"doc_id": "doc_trial"},
                        "summary": "Planted c01.",
                    },
                    {
                        "t": 19,
                        "day": 7,
                        "tool": "accuse",
                        "args": {"suspect": "e03"},
                        "summary": "FUTURE_SPOILER_STEP_DAY_7",
                    },
                ],
                "true_mole": "e03",
                "solver": {
                    "posterior": {"e01": 0.0, "e02": 0.48, "e03": 0.52},
                    "top_suspect": "e03",
                    "top_prob": 0.52,
                    "break_even_prob": 0.5882,
                    "ev_accuse_top": -0.116,
                    "ev_hold_fire": 0.55,
                    "recommended_call": "hold_fire",
                    "final_accused": "e03",
                    "final_day": 6,
                    "final_score": 0.58,
                    "correct": True,
                },
                "thinking_levels": [
                    {
                        "thinking_level": "low",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e02",
                        "accused_day": 4,
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.12,
                        "thinking_tokens": 900,
                        "failure_tag": "premature_accusation",
                        "analyst_quote": "SECRET_ANALYST_QUOTE_BEFORE_REVEAL",
                    },
                    {
                        "thinking_level": "high",
                        "model": "gemini-4-carbon",
                        "call_at_t": "hold_fire",
                        "accused": "e03",
                        "accused_day": 6,
                        "correct": True,
                        "score": 0.58,
                        "cost_usd": 0.44,
                        "thinking_tokens": 14200,
                        "failure_tag": None,
                        "analyst_quote": "Waited for second canary intersection.",
                    },
                ],
            },
            {
                "id": "syn-accuse-2",
                "title": "Pinpoint Leak at Boreal Tech",
                "tier": "hard",
                "seed": 22,
                "company": "Boreal Tech",
                "decision_day": 5,
                "decision_step": 12,
                "value_at_decision": 0.72,
                "suspects": [
                    {
                        "id": "e01",
                        "name": "Olli Virtanen",
                        "dept": "Infra",
                        "role": "SRE",
                        "clearance": "high",
                        "eliminated": True,
                        "canary_hits": 0,
                        "after_hours_count": 0,
                        "persona_note": "Cleared.",
                    },
                    {
                        "id": "e02",
                        "name": "Sari Niemi",
                        "dept": "Product",
                        "role": "PM",
                        "clearance": "high",
                        "eliminated": False,
                        "canary_hits": 2,
                        "after_hours_count": 3,
                        "persona_note": "Unique recipient of leaked variant C.",
                    },
                ],
                "canaries": [
                    {
                        "canary_id": "c02",
                        "doc_id": "doc_roadmap",
                        "day_planted": 4,
                        "variants": [
                            {"variant": "A", "recipients": ["e01"]},
                            {"variant": "C", "recipients": ["e02"]},
                        ],
                        "leaked_variant": "C",
                    }
                ],
                "leaks": [
                    {
                        "day": 5,
                        "doc_id": "doc_roadmap",
                        "canary_id": "c02",
                        "leaked_variant": "C",
                        "channel": "press",
                        "summary": "Unique variant C leaked.",
                    }
                ],
                "access_logs": [
                    {
                        "day": 5,
                        "employee": "e02",
                        "doc_id": "doc_roadmap",
                        "after_hours": True,
                        "action": "copy",
                    }
                ],
                "comms": [],
                "tool_steps": [],
                "true_mole": "e02",
                "solver": {
                    "posterior": {"e01": 0.02, "e02": 0.98},
                    "top_suspect": "e02",
                    "top_prob": 0.98,
                    "break_even_prob": 0.5814,
                    "ev_accuse_top": 0.6856,
                    "ev_hold_fire": 0.50,
                    "recommended_call": "accuse",
                    "final_accused": "e02",
                    "final_day": 5,
                    "final_score": 0.72,
                    "correct": True,
                },
                "thinking_levels": [
                    {
                        "thinking_level": "low",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e01",
                        "accused_day": 5,
                        "correct": False,
                        "score": -1.0,
                        "cost_usd": 0.09,
                        "thinking_tokens": 400,
                    },
                    {
                        "thinking_level": "high",
                        "model": "gemini-4-carbon",
                        "call_at_t": "accuse",
                        "accused": "e02",
                        "accused_day": 5,
                        "correct": True,
                        "score": 0.72,
                        "cost_usd": 0.39,
                        "thinking_tokens": 11500,
                    },
                ],
            },
        ],
    }

    engine_js = """
(function (root) {
  "use strict";
  function loadDataset() {
    var raw = root.OUTTHINK_DATA || { meta: {}, cases: [] };
    return { source: "data", meta: raw.meta || {}, cases: raw.cases || [], count: (raw.cases || []).length };
  }
  function evaluateCall(caseObj, call) {
    var action = call && call.action === "accuse" ? "accuse" : "hold_fire";
    var suspectId = action === "accuse" ? String(call.suspectId || "") : null;
    var trueMole = String(caseObj.true_mole || "");
    var rec = (caseObj.solver && caseObj.solver.recommended_call) || "hold_fire";
    var val = Number(caseObj.value_at_decision || 0.5);
    var correct = action === "accuse" ? suspectId === trueMole : rec === "hold_fire";
    var optimal = (action === "accuse" && rec === "accuse" && suspectId === trueMole) || (action === "hold_fire" && rec === "hold_fire");
    var score = action === "accuse" ? (suspectId === trueMole ? val : -1.0) : 0.0;
    return {
      action: action,
      suspectId: suspectId,
      trueMole: trueMole,
      correct: correct,
      optimal: optimal,
      score: score,
      verdictLabel: optimal ? "OPTIMAL CALL" : (correct ? "SAFE HOLD" : "FALSE ACCUSATION"),
      explanation: optimal ? "Matched Bayesian solver." : "Suboptimal decision.",
      solver: caseObj.solver || {},
      levelComparisons: caseObj.thinking_levels || []
    };
  }
  function createScoreboard() {
    var byId = {};
    var order = [];
    return {
      record: function (id, res) {
        if (!byId[id]) order.push(id);
        byId[id] = res;
      },
      getCaseResult: function (id) { return byId[id] || null; },
      reset: function () { byId = {}; order = []; },
      getSummary: function () {
        var n = order.length;
        var jSum = 0;
        var jRight = 0;
        var sSum = 0;
        var sRight = 0;
        var byLevel = {};
        for (var i = 0; i < n; i += 1) {
          var r = byId[order[i]];
          jSum += r.score;
          if (r.correct) jRight += 1;
          var fs = (r.solver && r.solver.final_score) || 0;
          sSum += fs;
          if (r.solver && r.solver.correct) sRight += 1;
          var lvs = r.levelComparisons || [];
          for (var k = 0; k < lvs.length; k += 1) {
            var lv = lvs[k];
            var key = lv.thinking_level || "medium";
            if (!byLevel[key]) byLevel[key] = { count: 0, scoreSum: 0, meanScore: 0, accuracy: 0, right: 0, totalCostUsd: 0, totalThinkingTokens: 0 };
            byLevel[key].count += 1;
            byLevel[key].scoreSum += Number(lv.score || 0);
            if (lv.correct) byLevel[key].right += 1;
            byLevel[key].totalCostUsd += Number(lv.cost_usd || 0);
            byLevel[key].totalThinkingTokens += Number(lv.thinking_tokens || 0);
          }
        }
        Object.keys(byLevel).forEach(function (k) {
          var b = byLevel[k];
          b.meanScore = b.count > 0 ? b.scoreSum / b.count : 0;
          b.accuracy = b.count > 0 ? b.right / b.count : 0;
        });
        return {
          casesPlayed: n,
          judge: { scoreSum: jSum, meanScore: n > 0 ? jSum / n : 0, accuracy: n > 0 ? jRight / n : 0 },
          solver: { scoreSum: sSum, meanScore: n > 0 ? sSum / n : 0, accuracy: n > 0 ? sRight / n : 0 },
          byLevel: byLevel
        };
      }
    };
  }
  root.OutThinkEngine = { loadDataset: loadDataset, evaluateCall: evaluateCall, createScoreboard: createScoreboard };
})(typeof window !== "undefined" ? window : globalThis);
"""

    scene_js = """
(function (root) {
  "use strict";
  var PROPS = [
    { key: "canaries", x: 96, y: 10, w: 114, h: 74 },
    { key: "leaks", x: 222, y: 10, w: 114, h: 74 },
    { key: "access", x: 348, y: 10, w: 114, h: 74 },
    { key: "comms", x: 474, y: 10, w: 114, h: 74 },
    { key: "steps", x: 600, y: 10, w: 110, h: 74 }
  ];
  function create(containerEl, hooks) {
    var canvas = document.createElement("canvas");
    canvas.width = 960;
    canvas.height = 520;
    containerEl.appendChild(canvas);
    var ctx = canvas.getContext("2d");
    var revealed = false;
    function paint() {
      ctx.clearRect(0, 0, 960, 520);
      ctx.fillText(revealed ? "SOLVER TOP-3 POSTERIOR" : "[LOCKED]", 760, 40);
    }
    canvas.addEventListener("click", function (ev) {
      var rect = canvas.getBoundingClientRect();
      var lx = ((ev.clientX - rect.left) * 960) / (rect.width || 960);
      var ly = ((ev.clientY - rect.top) * 520) / (rect.height || 520);
      for (var i = 0; i < PROPS.length; i += 1) {
        var p = PROPS[i];
        if (lx >= p.x && lx <= p.x + p.w && ly >= p.y && ly <= p.y + p.h) {
          if (hooks && hooks.onSelectTab) hooks.onSelectTab(p.key);
          return;
        }
      }
    });
    paint();
    return {
      mode: "canvas2d",
      setCase: function () { revealed = false; paint(); },
      setSelectedSuspect: function () { paint(); },
      setHighlightCandidates: function () { paint(); },
      showReveal: function () { revealed = true; paint(); },
      clearReveal: function () { revealed = false; paint(); }
    };
  }
  root.OutThinkScene = { create: create };
})(typeof window !== "undefined" ? window : globalThis);
"""

    game_js = """
(function () {
  "use strict";
  var LEVELS = ["minimal", "low", "medium", "high", "xhigh"];
  function el(tag, cls, txt) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (txt !== undefined && txt !== null) n.textContent = String(txt);
    return n;
  }
  function clear(node) {
    while (node && node.firstChild) node.removeChild(node.firstChild);
  }
  function preEvidence(c) {
    var d = Number(c.decision_day || 999);
    var st = Number(c.decision_step || 0);
    return {
      canaries: (c.canaries || []).filter(function (x) { return Number(x.day_planted || 1) <= d; }),
      leaks: (c.leaks || []).filter(function (x) { return Number(x.day || 1) <= d; }),
      access: (c.access_logs || []).filter(function (x) { return Number(x.day || 1) <= d; }),
      comms: (c.comms || []).filter(function (x) { return Number(x.day || 1) <= d; }),
      steps: (c.tool_steps || []).filter(function (x) { return Number(x.day || 1) <= d && (st <= 0 || Number(x.t || 0) <= st); })
    };
  }
  function boot() {
    var stageEl = document.getElementById("phaser-stage");
    var fallbackEl = document.getElementById("stage-fallback");
    var selectEl = document.getElementById("case-select");
    var btnPrev = document.getElementById("btn-prev-case");
    var btnNext = document.getElementById("btn-next-case");
    var btnReset = document.getElementById("btn-reset-scores");
    var scoreBar = document.getElementById("scoreboard-bar");
    var rosterEl = document.getElementById("suspect-roster");
    var dossierEl = document.getElementById("dossier-card");
    var btnAccuse = document.getElementById("btn-accuse");
    var btnHold = document.getElementById("btn-hold-fire");
    var btnHighlight = document.getElementById("btn-highlight-suspects");
    var btnFilter = document.getElementById("btn-filter-suspect");
    var tabsEl = document.getElementById("evidence-tabs");
    var evListEl = document.getElementById("evidence-list");
    var revealEl = document.getElementById("reveal-panel");
    var provEl = document.getElementById("provenance-summary");

    var dataset = window.OutThinkEngine.loadDataset();
    var scoreboard = window.OutThinkEngine.createScoreboard();
    var idx = 0;
    var selectedId = null;
    var activeTab = "canaries";
    var highlightOn = false;
    var filterOn = false;
    var focusedPod = null;

    var scene = window.OutThinkScene ? window.OutThinkScene.create(stageEl, {
      onSelectSuspect: function (id) { selectedId = id; renderAll(); },
      onSelectTab: function (t) { activeTab = t; renderAll(); },
      onSelectThinkingPod: function (lv) { focusedPod = lv; renderAll(); }
    }) : null;

    provEl.textContent = "Deterministic Replay Benchmark (0 live API calls in browser) | Loaded " + dataset.count + " scenario(s)";

    function candidateIds(c, ev) {
      return (c.suspects || []).filter(function (s) { return !s.eliminated && Number(s.canary_hits || 0) > 0; }).map(function (s) { return s.id; });
    }

    function renderScore() {
      clear(scoreBar);
      var sum = scoreboard.getSummary();
      var you = el("div", "score-tile score-tile-you", "YOU (JUDGE) " + sum.casesPlayed + "/" + dataset.count + " " + sum.judge.scoreSum.toFixed(2) + " " + (sum.casesPlayed > 0 ? (sum.judge.accuracy * 100).toFixed(1) + "% acc" : "No calls") + " $0.0000");
      scoreBar.appendChild(you);
      scoreBar.appendChild(el("div", "score-tile score-tile-solver", "SOLVER " + sum.solver.scoreSum.toFixed(2)));
      LEVELS.forEach(function (lv) {
        var b = sum.byLevel[lv] || { count: 0, scoreSum: 0, totalCostUsd: 0 };
        var beaten = b.count > 0 && sum.judge.scoreSum > b.scoreSum;
        scoreBar.appendChild(el("div", "score-tile" + (beaten ? " score-tile-beaten" : ""), lv + (beaten ? " OUT-THOUGHT " : " ") + b.scoreSum.toFixed(2)));
      });
    }

    function renderAll() {
      var c = dataset.cases[idx];
      var ev = preEvidence(c);
      var res = scoreboard.getCaseResult(c.id);
      var cands = candidateIds(c, ev);

      clear(selectEl);
      dataset.cases.forEach(function (item, i) {
        var opt = el("option", "", (scoreboard.getCaseResult(item.id) ? "[DONE] " : "") + item.title);
        opt.value = String(i);
        if (i === idx) opt.selected = true;
        selectEl.appendChild(opt);
      });
      btnPrev.disabled = idx <= 0;
      btnNext.disabled = idx >= dataset.cases.length - 1;

      document.getElementById("case-tier-badge").textContent = c.tier.toUpperCase();
      document.getElementById("case-title").textContent = c.title;
      document.getElementById("case-company").textContent = c.company;
      document.getElementById("case-seed-badge").textContent = "Seed " + c.seed;
      document.getElementById("case-day-badge").textContent = "Day " + c.decision_day;
      document.getElementById("case-step-badge").textContent = "Step " + c.decision_step;
      document.getElementById("case-reward-badge").textContent = "+" + Number(c.value_at_decision).toFixed(2);
      document.getElementById("case-status-pill").textContent = res ? res.verdictLabel : "AWAITING CALL";

      btnHighlight.setAttribute("aria-pressed", highlightOn ? "true" : "false");
      btnHighlight.classList.toggle("is-active", highlightOn);

      clear(rosterEl);
      c.suspects.forEach(function (s) {
        var isSel = s.id === selectedId;
        var isHi = highlightOn && cands.indexOf(s.id) >= 0;
        var isMole = Boolean(res && res.trueMole === s.id);
        var b = el("button", "suspect-chip" + (isSel ? " is-selected" : "") + (isHi ? " is-canary-highlight" : "") + (s.eliminated ? " is-eliminated" : ""), s.id + " " + s.name + (isMole ? " MOLE" : ""));
        b.type = "button";
        b.setAttribute("role", "option");
        b.setAttribute("aria-selected", isSel ? "true" : "false");
        b.addEventListener("click", function () { selectedId = s.id; renderAll(); });
        rosterEl.appendChild(b);
      });

      if (!scene || stageEl.children.length === 0) {
        fallbackEl.hidden = false;
        clear(fallbackEl);
        c.suspects.forEach(function (s) {
          var fb = el("button", "fallback-desk" + (s.id === selectedId ? " is-selected" : ""), s.id + " " + s.name);
          fb.type = "button";
          fb.addEventListener("click", function () { selectedId = s.id; renderAll(); });
          fallbackEl.appendChild(fb);
        });
        var podsBar = el("div", "fallback-pods-bar");
        LEVELS.forEach(function (lv) {
          var pb = el("button", "emp-mini-btn", lv.toUpperCase());
          pb.type = "button";
          pb.addEventListener("click", function () { focusedPod = lv; renderAll(); });
          podsBar.appendChild(pb);
        });
        fallbackEl.appendChild(podsBar);
      } else {
        fallbackEl.hidden = true;
      }

      var sp = c.suspects.filter(function (s) { return s.id === selectedId; })[0] || c.suspects[0];
      selectedId = sp.id;
      clear(dossierEl);
      dossierEl.appendChild(el("div", "dossier-id-name", sp.id + " - " + sp.name));
      dossierEl.appendChild(el("span", "pill", (res && res.trueMole === sp.id) ? "CONFIRMED MOLE" : (sp.eliminated ? "RULED OUT" : "ACTIVE SUSPECT")));
      btnAccuse.textContent = "ACCUSE " + sp.id + " NOW";
      btnAccuse.disabled = Boolean(res);
      btnHold.disabled = Boolean(res);

      btnFilter.setAttribute("aria-pressed", filterOn ? "true" : "false");
      btnFilter.textContent = filterOn ? "Filter: " + selectedId + " Only" : "Filter: All Staff";
      document.getElementById("count-canaries").textContent = String(ev.canaries.length);
      document.getElementById("count-leaks").textContent = String(ev.leaks.length);
      document.getElementById("count-access").textContent = String(ev.access.length);
      document.getElementById("count-comms").textContent = String(ev.comms.length);
      document.getElementById("count-steps").textContent = String(ev.steps.length);

      tabsEl.querySelectorAll("[data-tab]").forEach(function (tb) {
        var act = tb.getAttribute("data-tab") === activeTab;
        tb.classList.toggle("is-active", act);
        tb.setAttribute("aria-selected", act ? "true" : "false");
      });

      clear(evListEl);
      var fid = filterOn ? selectedId : null;
      if (activeTab === "canaries") {
        ev.canaries.filter(function (cn) {
          if (!fid) return true;
          return cn.variants.some(function (v) { return (v.recipients || []).indexOf(fid) >= 0; });
        }).forEach(function (cn) {
          var card = el("div", "ev-card", cn.canary_id + " " + cn.doc_id);
          cn.variants.forEach(function (v) {
            (v.recipients || []).forEach(function (emp) {
              var eb = el("button", "emp-mini-btn", emp);
              eb.type = "button";
              eb.addEventListener("click", function () { selectedId = emp; renderAll(); });
              card.appendChild(eb);
            });
          });
          evListEl.appendChild(card);
        });
      } else if (activeTab === "leaks") {
        ev.leaks.forEach(function (lk) { evListEl.appendChild(el("div", "ev-card", lk.summary)); });
      } else if (activeTab === "access") {
        ev.access.filter(function (a) { return !fid || a.employee === fid; }).forEach(function (a) {
          evListEl.appendChild(el("div", "ev-card", a.employee + " " + a.doc_id));
        });
      } else if (activeTab === "comms") {
        ev.comms.filter(function (m) { return !fid || m.speaker === fid || m.target === fid; }).forEach(function (m) {
          evListEl.appendChild(el("div", "ev-card", m.speaker + ": " + m.text));
        });
      } else {
        ev.steps.forEach(function (st) { evListEl.appendChild(el("div", "ev-card", st.tool + " " + st.summary)); });
      }

      clear(revealEl);
      if (!res) {
        revealEl.hidden = true;
      } else {
        revealEl.hidden = false;
        var tone = res.optimal ? "verdict-optimal" : (res.correct ? "verdict-cautious" : "verdict-wrong");
        var banner = el("div", "verdict-banner " + tone, res.verdictLabel + " | True Mole: " + res.trueMole + " | Score " + res.score.toFixed(2));
        if (idx < dataset.cases.length - 1) {
          var nb = el("button", "btn-next-inline", "Next Scenario");
          nb.type = "button";
          nb.addEventListener("click", function () { selectCase(idx + 1); });
          banner.appendChild(nb);
        }
        revealEl.appendChild(banner);
        revealEl.appendChild(el("div", "solver-box", "Bayesian Reference Solver " + c.solver.top_suspect));
        (c.thinking_levels || []).forEach(function (lv) {
          var k = lv.thinking_level;
          var card = el("div", "level-card" + (focusedPod === k ? " is-pod-focused" : ""), k + " " + (lv.analyst_quote || ""));
          card.setAttribute("data-level-key", k);
          revealEl.appendChild(card);
        });
      }
      renderScore();
    }

    function selectCase(newIdx) {
      idx = newIdx;
      var c = dataset.cases[idx];
      var nonElim = c.suspects.filter(function (s) { return !s.eliminated; })[0];
      selectedId = (nonElim || c.suspects[0]).id;
      highlightOn = false;
      focusedPod = null;
      if (scene) {
        scene.setCase(c);
        var existing = scoreboard.getCaseResult(c.id);
        if (existing) scene.showReveal(existing, c);
      }
      renderAll();
    }

    function submit(call) {
      var c = dataset.cases[idx];
      if (scoreboard.getCaseResult(c.id)) return;
      var res = window.OutThinkEngine.evaluateCall(c, call);
      scoreboard.record(c.id, res);
      if (scene) scene.showReveal(res, c);
      renderAll();
    }

    selectEl.addEventListener("change", function () { selectCase(Number(selectEl.value || 0)); });
    btnPrev.addEventListener("click", function () { if (idx > 0) selectCase(idx - 1); });
    btnNext.addEventListener("click", function () { if (idx < dataset.cases.length - 1) selectCase(idx + 1); });
    btnReset.addEventListener("click", function () { scoreboard.reset(); selectCase(idx); });
    btnHighlight.addEventListener("click", function () { highlightOn = !highlightOn; renderAll(); });
    btnFilter.addEventListener("click", function () { filterOn = !filterOn; renderAll(); });
    tabsEl.addEventListener("click", function (ev) {
      var t = ev.target && ev.target.closest ? ev.target.closest("[data-tab]") : null;
      if (t) { activeTab = t.getAttribute("data-tab"); renderAll(); }
    });
    btnAccuse.addEventListener("click", function () { submit({ action: "accuse", suspectId: selectedId }); });
    btnHold.addEventListener("click", function () { submit({ action: "hold_fire" }); });

    selectCase(0);
  }
  boot();
})();
"""

    (demo_dir / "index.html").write_text(html_src, encoding="utf-8")
    (demo_dir / "style.css").write_text(css_src, encoding="utf-8")
    (demo_dir / "cases.js").write_text(
        "window.OUTTHINK_DATA = " + json.dumps(cases_payload) + ";\n",
        encoding="utf-8",
    )
    (demo_dir / "engine.js").write_text(engine_js, encoding="utf-8")
    (demo_dir / "scene.js").write_text(scene_js, encoding="utf-8")
    (demo_dir / "game.js").write_text(game_js, encoding="utf-8")
    return demo_dir


def test_html_parser_detects_duplicate_ids_and_unclosed_tags(tmp_path: Path) -> None:
    demo_dir = _write_synthetic_playable_demo(tmp_path / "demo")
    valid_html = (demo_dir / "index.html").read_text(encoding="utf-8")
    report = validate_index_html_contract(valid_html)
    assert len(report["ids"]) >= len(REQUIRED_DOM_IDS)

    no_doctype = valid_html.replace("<!DOCTYPE html>", "", 1)
    with pytest.raises(AssertionError, match="DOCTYPE"):
        validate_index_html_contract(no_doctype)

    dup_id_html = valid_html.replace(
        '<div id="evidence-list"',
        '<div id="dossier-card"></div><div id="evidence-list"',
        1,
    )
    with pytest.raises(AssertionError, match="Duplicate DOM IDs"):
        validate_index_html_contract(dup_id_html)

    unclosed_html = valid_html.replace("</main>", "", 1)
    with pytest.raises(AssertionError, match="Mismatched|Unclosed"):
        validate_index_html_contract(unclosed_html)

    unhidden_reveal = valid_html.replace(
        '<section id="reveal-panel" class="reveal-panel" aria-live="polite" hidden></section>',
        '<section id="reveal-panel" class="reveal-panel" aria-live="polite"></section>',
        1,
    )
    with pytest.raises(AssertionError, match="start hidden"):
        validate_index_html_contract(unhidden_reveal)


def test_css_validator_checks_balanced_braces_and_offline_rules(tmp_path: Path) -> None:
    demo_dir = _write_synthetic_playable_demo(tmp_path / "demo")
    valid_css = (demo_dir / "style.css").read_text(encoding="utf-8")
    css_report = validate_stylesheet_contract(valid_css)
    assert css_report["media_query_count"] >= 1

    with pytest.raises(AssertionError, match="brace"):
        validate_stylesheet_contract(valid_css + "\n.broken { color: red;\n")

    with pytest.raises(AssertionError, match="External"):
        validate_stylesheet_contract('@import url("https://fonts.example.com/x.css");\n' + valid_css)


def test_synthetic_dom_boot_and_strict_pre_decision_blindfold(tmp_path: Path) -> None:
    demo_dir = _write_synthetic_playable_demo(tmp_path / "demo")
    out = _run_dom_harness(
        demo_dir,
        """
        const doc = env.document;
        const reveal = doc.getElementById("reveal-panel");
        const tabTexts = {};
        const tabs = ["canaries", "leaks", "access", "comms", "steps"];
        for (const t of tabs) {
          doc.querySelector('[data-tab="' + t + '"]').click();
          tabTexts[t] = doc.getElementById("evidence-list").textContent;
        }
        doc.querySelector('[data-tab="canaries"]').click();
        const canvasTexts = env.canvasContexts.length > 0
          ? env.canvasContexts[0].drawTexts.map((d) => d.text)
          : [];
        return {
          revealHidden: reveal.hidden,
          revealChildren: reveal.children.length,
          statusText: doc.getElementById("case-status-pill").textContent,
          visibleBody: env.visibleText(doc.body),
          fullBody: doc.body.textContent,
          counts: {
            canaries: doc.getElementById("count-canaries").textContent,
            leaks: doc.getElementById("count-leaks").textContent,
            access: doc.getElementById("count-access").textContent,
            comms: doc.getElementById("count-comms").textContent,
            steps: doc.getElementById("count-steps").textContent
          },
          tabTexts: tabTexts,
          canvasTexts: canvasTexts
        };
        """,
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    assert len(out["skippedExternalScripts"]) == 1

    res = out["result"]
    assert res["revealHidden"] is True
    assert res["revealChildren"] == 0
    assert res["statusText"] == "AWAITING CALL"
    assert res["counts"] == {"canaries": "1", "leaks": "1", "access": "1", "comms": "1", "steps": "1"}

    for spoiler in (
        "CONFIRMED MOLE",
        "True Mole:",
        "Bayesian Reference Solver",
        "SECRET_ANALYST_QUOTE_BEFORE_REVEAL",
        "FUTURE_SPOILER_LEAK_DAY_7",
        "FUTURE_SPOILER_ACCESS_DAY_7",
        "FUTURE_SPOILER_COMM_DAY_7",
        "FUTURE_SPOILER_STEP_DAY_7",
    ):
        assert spoiler not in res["visibleBody"]
        assert spoiler not in res["fullBody"]
        for tab_content in res["tabTexts"].values():
            assert spoiler not in tab_content

    assert "[LOCKED]" in res["canvasTexts"]
    assert "SOLVER TOP-3 POSTERIOR" not in res["canvasTexts"]


def test_synthetic_dom_tabs_filter_highlight_and_inline_emp_selection(tmp_path: Path) -> None:
    demo_dir = _write_synthetic_playable_demo(tmp_path / "demo")
    out = _run_dom_harness(
        demo_dir,
        """
        const doc = env.document;
        const empBtns = doc.getElementById("evidence-list").querySelectorAll(".emp-mini-btn");
        const e01Btn = empBtns.filter((b) => b.textContent === "e01")[0];
        e01Btn.click();
        const dossierAfterInlineClick = doc.getElementById("dossier-card").textContent;
        const accuseLabelE01 = doc.getElementById("btn-accuse").textContent;

        const filterBtn = doc.getElementById("btn-filter-suspect");
        filterBtn.click();
        const filterPressed = filterBtn.getAttribute("aria-pressed");
        doc.querySelector('[data-tab="access"]').click();
        const accessForE01 = doc.getElementById("evidence-list").textContent;

        const rosterChips = doc.getElementById("suspect-roster").querySelectorAll(".suspect-chip");
        const e03Chip = rosterChips.filter((c) => c.textContent.indexOf("e03") >= 0)[0];
        e03Chip.click();
        const accessForE03 = doc.getElementById("evidence-list").textContent;

        const hiBtn = doc.getElementById("btn-highlight-suspects");
        hiBtn.click();
        const highlightedIds = doc
          .getElementById("suspect-roster")
          .querySelectorAll(".is-canary-highlight")
          .map((el) => el.textContent.split(" ")[0]);

        const canvas = doc.getElementById("phaser-stage").querySelector("canvas");
        canvas.dispatchEvent(new env.DOMEvent("click", { clientX: 279, clientY: 47, bubbles: true }));
        const leaksTabSelected = doc.querySelector('[data-tab="leaks"]').getAttribute("aria-selected");

        return {
          dossierAfterInlineClick,
          accuseLabelE01,
          filterPressed,
          accessForE01,
          accessForE03,
          hiPressed: hiBtn.getAttribute("aria-pressed"),
          highlightedIds,
          leaksTabSelected
        };
        """,
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    res = out["result"]
    assert "e01 - Aino Laine" in res["dossierAfterInlineClick"]
    assert res["accuseLabelE01"] == "ACCUSE e01 NOW"
    assert res["filterPressed"] == "true"
    assert res["accessForE01"] == ""
    assert "e03 doc_trial" in res["accessForE03"]
    assert res["hiPressed"] == "true"
    assert res["highlightedIds"] == ["e02", "e03"]
    assert res["leaksTabSelected"] == "true"


def test_synthetic_dom_accuse_hold_fire_reveal_pods_scoreboard_and_reset(tmp_path: Path) -> None:
    demo_dir = _write_synthetic_playable_demo(tmp_path / "demo")
    out = _run_dom_harness(
        demo_dir,
        """
        const doc = env.document;
        doc.getElementById("btn-hold-fire").click();
        const revealAfterCase0 = doc.getElementById("reveal-panel");
        const case0Banner = revealAfterCase0.querySelector(".verdict-banner").className;
        const case0RevealText = revealAfterCase0.textContent;
        const holdDisabledAfterCall = doc.getElementById("btn-hold-fire").disabled;
        const accuseDisabledAfterCall = doc.getElementById("btn-accuse").disabled;

        const nextInline = revealAfterCase0.querySelector("button");
        nextInline.click();
        const case1Title = doc.getElementById("case-title").textContent;
        const revealHiddenOnFreshCase = doc.getElementById("reveal-panel").hidden;

        const e02Chip = doc
          .getElementById("suspect-roster")
          .querySelectorAll(".suspect-chip")
          .filter((c) => c.textContent.indexOf("e02") >= 0)[0];
        e02Chip.click();
        doc.getElementById("btn-accuse").click();

        const scoreTextAfterBoth = doc.getElementById("scoreboard-bar").textContent;
        const beatenTiles = doc.getElementById("scoreboard-bar").querySelectorAll(".score-tile-beaten").length;
        const dossierConfirmedMole = doc.getElementById("dossier-card").textContent;

        const selectEl = doc.getElementById("case-select");
        selectEl.value = "0";
        selectEl.dispatchEvent(new env.DOMEvent("change", { bubbles: true }));
        const persistedRevealOnCase0 = !doc.getElementById("reveal-panel").hidden;

        doc.getElementById("btn-reset-scores").click();
        const revealHiddenAfterReset = doc.getElementById("reveal-panel").hidden;
        const statusAfterReset = doc.getElementById("case-status-pill").textContent;
        const scoreTextAfterReset = doc.getElementById("scoreboard-bar").textContent;

        return {
          case0Banner,
          case0RevealText,
          holdDisabledAfterCall,
          accuseDisabledAfterCall,
          case1Title,
          revealHiddenOnFreshCase,
          scoreTextAfterBoth,
          beatenTiles,
          dossierConfirmedMole,
          persistedRevealOnCase0,
          revealHiddenAfterReset,
          statusAfterReset,
          scoreTextAfterReset
        };
        """,
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    res = out["result"]
    assert "verdict-optimal" in res["case0Banner"]
    assert "True Mole: e03" in res["case0RevealText"]
    assert "SECRET_ANALYST_QUOTE_BEFORE_REVEAL" in res["case0RevealText"]
    assert res["holdDisabledAfterCall"] is True
    assert res["accuseDisabledAfterCall"] is True
    assert res["case1Title"] == "Pinpoint Leak at Boreal Tech"
    assert res["revealHiddenOnFreshCase"] is True
    assert "2/2" in res["scoreTextAfterBoth"]
    assert "100.0% acc" in res["scoreTextAfterBoth"]
    assert res["beatenTiles"] >= 1
    assert "CONFIRMED MOLE" in res["dossierConfirmedMole"]
    assert res["persistedRevealOnCase0"] is True
    assert res["revealHiddenAfterReset"] is True
    assert res["statusAfterReset"] == "AWAITING CALL"
    assert "0/2" in res["scoreTextAfterReset"]


def test_synthetic_dom_wrong_accusation_penalty_and_offline_stage_fallback(tmp_path: Path) -> None:
    demo_dir = _write_synthetic_playable_demo(tmp_path / "demo")
    out = _run_dom_harness(
        demo_dir,
        """
        const doc = env.document;
        const fallbackEl = doc.getElementById("stage-fallback");
        const fallbackHidden = fallbackEl.hidden;
        const deskButtons = fallbackEl.querySelectorAll(".fallback-desk");
        const e01Desk = deskButtons.filter((b) => b.textContent.indexOf("e01") >= 0)[0];
        e01Desk.click();
        const accuseBtnLabel = doc.getElementById("btn-accuse").textContent;
        doc.getElementById("btn-accuse").click();

        const bannerClass = doc.getElementById("reveal-panel").querySelector(".verdict-banner").className;
        const revealText = doc.getElementById("reveal-panel").textContent;
        const podButtons = fallbackEl.querySelectorAll(".emp-mini-btn");
        const highPodBtn = podButtons.filter((b) => b.textContent === "HIGH")[0];
        highPodBtn.click();
        const focusedCards = doc
          .getElementById("reveal-panel")
          .querySelectorAll(".is-pod-focused")
          .map((c) => c.getAttribute("data-level-key"));

        return {
          fallbackHidden,
          deskCount: deskButtons.length,
          accuseBtnLabel,
          bannerClass,
          revealText,
          focusedCards
        };
        """,
        skip_local_scripts=["scene.js"],
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    res = out["result"]
    assert res["fallbackHidden"] is False
    assert res["deskCount"] == 3
    assert res["accuseBtnLabel"] == "ACCUSE e01 NOW"
    assert "verdict-wrong" in res["bannerClass"]
    assert "-1.00" in res["revealText"]
    assert res["focusedCards"] == ["high"]


def test_live_demo_html_and_css_playable_dom_contract() -> None:
    if not LIVE_INDEX_HTML.exists():
        pytest.skip("demo/out-think-gemini/index.html not yet merged on this branch")

    html_report = validate_index_html_contract(LIVE_INDEX_HTML.read_text(encoding="utf-8"))
    assert LIVE_STYLE_CSS.exists(), "demo/out-think-gemini/style.css must exist alongside index.html"
    css_report = validate_stylesheet_contract(LIVE_STYLE_CSS.read_text(encoding="utf-8"))
    assert css_report["byte_length"] > 500

    for script_rel in html_report["local_scripts"]:
        script_path = LIVE_DEMO_DIR / script_rel
        if script_rel not in OPTIONAL_LOCAL_SCRIPTS:
            assert script_path.exists(), f"Required local script missing: {script_rel}"


def test_live_demo_offline_boot_and_pre_decision_blindfold_all_cases() -> None:
    if not LIVE_INDEX_HTML.exists():
        pytest.skip("demo/out-think-gemini/index.html not yet merged on this branch")

    out = _run_dom_harness(
        LIVE_DEMO_DIR,
        """
        const doc = env.document;
        const selectEl = doc.getElementById("case-select");
        const optionCount = selectEl.children.length;
        const perCaseChecks = [];

        for (let i = 0; i < optionCount; i += 1) {
          selectEl.value = String(i);
          selectEl.dispatchEvent(new env.DOMEvent("change", { bubbles: true }));

          const revealEl = doc.getElementById("reveal-panel");
          const vis = env.visibleText(doc.body);
          const full = doc.body.textContent;
          const stageCanvasCount = doc.getElementById("phaser-stage").querySelectorAll("canvas").length;
          const stageFallbackHidden = doc.getElementById("stage-fallback").hidden;
          const canvasTexts = env.canvasContexts.length > 0
            ? env.canvasContexts[0].drawTexts.map((d) => d.text)
            : [];

          for (const t of ["canaries", "leaks", "access", "comms", "steps"]) {
            doc.querySelector('[data-tab="' + t + '"]').click();
          }
          doc.querySelector('[data-tab="canaries"]').click();

          doc.getElementById("btn-highlight-suspects").click();
          const hiPressed = doc.getElementById("btn-highlight-suspects").getAttribute("aria-pressed");
          doc.getElementById("btn-highlight-suspects").click();

          doc.getElementById("btn-filter-suspect").click();
          const filterPressed = doc.getElementById("btn-filter-suspect").getAttribute("aria-pressed");
          doc.getElementById("btn-filter-suspect").click();

          perCaseChecks.push({
            index: i,
            title: doc.getElementById("case-title").textContent,
            status: doc.getElementById("case-status-pill").textContent,
            revealHidden: revealEl.hidden,
            revealChildren: revealEl.children.length,
            accuseEnabled: !doc.getElementById("btn-accuse").disabled,
            holdEnabled: !doc.getElementById("btn-hold-fire").disabled,
            rosterCount: doc.getElementById("suspect-roster").children.length,
            stageCanvasCount: stageCanvasCount,
            stageFallbackHidden: stageFallbackHidden,
            hiPressed: hiPressed,
            filterPressed: filterPressed,
            hasConfirmedMoleLeak: vis.indexOf("CONFIRMED MOLE") >= 0 || full.indexOf("True Mole:") >= 0,
            hasSolverBoxLeak: full.indexOf("Bayesian Reference Solver") >= 0,
            hasLadderHeaderLeak: full.indexOf("Gemini Thinking Ladder Showdown") >= 0,
            canvasHasLockedPods: canvasTexts.indexOf("[LOCKED]") >= 0,
            canvasHasRevealPosterior: canvasTexts.some((txt) => txt.indexOf("SOLVER TOP-3 POSTERIOR") >= 0)
          });
        }

        return {
          optionCount: optionCount,
          provenanceText: doc.getElementById("provenance-summary").textContent,
          perCaseChecks: perCaseChecks
        };
        """,
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    res = out["result"]
    assert res["optionCount"] >= 1
    assert "0 live API calls" in res["provenanceText"]

    for chk in res["perCaseChecks"]:
        assert chk["title"].strip() != ""
        assert chk["status"] == "AWAITING CALL"
        assert chk["revealHidden"] is True
        assert chk["revealChildren"] == 0
        assert chk["accuseEnabled"] is True
        assert chk["holdEnabled"] is True
        assert chk["rosterCount"] >= 3
        assert chk["hiPressed"] == "true"
        assert chk["filterPressed"] == "true"
        assert chk["hasConfirmedMoleLeak"] is False, f"Pre-decision mole leak on case {chk['index']}"
        assert chk["hasSolverBoxLeak"] is False, f"Pre-decision solver leak on case {chk['index']}"
        assert chk["hasLadderHeaderLeak"] is False, f"Pre-decision ladder leak on case {chk['index']}"
        if chk["stageCanvasCount"] > 0:
            assert chk["stageFallbackHidden"] is True
            assert chk["canvasHasLockedPods"] is True
            assert chk["canvasHasRevealPosterior"] is False


def test_live_demo_full_playthrough_optimal_calls_and_reveal_parity_all_cases() -> None:
    if not LIVE_INDEX_HTML.exists():
        pytest.skip("demo/out-think-gemini/index.html not yet merged on this branch")

    out = _run_dom_harness(
        LIVE_DEMO_DIR,
        """
        const doc = env.document;
        const win = env.window;
        const dataset = win.OutThinkEngine.loadDataset();
        const total = dataset.cases.length;
        const outcomes = [];

        for (let i = 0; i < total; i += 1) {
          const c = dataset.cases[i];
          const selectEl = doc.getElementById("case-select");
          selectEl.value = String(i);
          selectEl.dispatchEvent(new env.DOMEvent("change", { bubbles: true }));

          const rec = (c.solver && c.solver.recommended_call) || "hold_fire";
          if (rec === "accuse") {
            const targetId = c.true_mole || (c.solver && c.solver.top_suspect);
            const chips = doc.getElementById("suspect-roster").querySelectorAll(".suspect-chip");
            const targetChip = chips.filter((btn) => btn.textContent.indexOf(targetId) >= 0)[0];
            if (targetChip) targetChip.click();
            doc.getElementById("btn-accuse").click();
          } else {
            doc.getElementById("btn-hold-fire").click();
          }

          const revealEl = doc.getElementById("reveal-panel");
          const banner = revealEl.querySelector(".verdict-banner");
          const levelCards = revealEl.querySelectorAll("[data-level-key]");
          const solverBox = revealEl.querySelector(".solver-box");
          outcomes.push({
            id: c.id,
            rec: rec,
            expectedLevels: (c.thinking_levels || []).length,
            renderedLevels: levelCards.length,
            revealHidden: revealEl.hidden,
            bannerClass: banner ? banner.className : "",
            hasSolverBox: Boolean(solverBox),
            hasTrueMoleText: revealEl.textContent.indexOf("True Mole:") >= 0,
            buttonsLocked: doc.getElementById("btn-accuse").disabled && doc.getElementById("btn-hold-fire").disabled
          });
        }

        const scoreTiles = doc.getElementById("scoreboard-bar").querySelectorAll(".score-tile");
        const scoreSummaryText = doc.getElementById("scoreboard-bar").textContent;

        doc.getElementById("btn-reset-scores").click();
        const resetScoreText = doc.getElementById("scoreboard-bar").textContent;
        const resetRevealHidden = doc.getElementById("reveal-panel").hidden;

        return {
          total: total,
          source: dataset.source,
          outcomes: outcomes,
          scoreTileCount: scoreTiles.length,
          scoreSummaryText: scoreSummaryText,
          resetScoreText: resetScoreText,
          resetRevealHidden: resetRevealHidden
        };
        """,
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    res = out["result"]
    assert res["total"] >= 1
    if (LIVE_DEMO_DIR / "cases.js").exists():
        assert res["source"] == "data"
        assert res["total"] >= 10

    for item in res["outcomes"]:
        assert item["revealHidden"] is False
        assert "verdict-optimal" in item["bannerClass"], f"Expected optimal verdict on {item['id']}"
        assert item["hasSolverBox"] is True
        assert item["hasTrueMoleText"] is True
        assert item["buttonsLocked"] is True
        assert item["renderedLevels"] == item["expectedLevels"]
        assert item["renderedLevels"] >= 2

    assert res["scoreTileCount"] == 7
    assert f"{res['total']}/{res['total']}" in res["scoreSummaryText"]
    assert "$0.0000" in res["scoreSummaryText"]
    assert f"0/{res['total']}" in res["resetScoreText"]
    assert res["resetRevealHidden"] is True


def test_live_demo_fallback_stage_when_scene_disabled() -> None:
    if not LIVE_INDEX_HTML.exists():
        pytest.skip("demo/out-think-gemini/index.html not yet merged on this branch")

    out = _run_dom_harness(
        LIVE_DEMO_DIR,
        """
        const doc = env.document;
        const fallbackEl = doc.getElementById("stage-fallback");
        const desks = fallbackEl.querySelectorAll(".fallback-desk");
        if (desks.length > 1) {
          desks[1].click();
        }
        doc.getElementById("btn-hold-fire").click();
        return {
          fallbackHidden: fallbackEl.hidden,
          deskCount: desks.length,
          revealShown: !doc.getElementById("reveal-panel").hidden
        };
        """,
        skip_local_scripts=["scene.js"],
    )
    assert out["networkAttempts"] == 0
    assert out["uncaughtErrors"] == []
    res = out["result"]
    assert res["fallbackHidden"] is False
    assert res["deskCount"] >= 3
    assert res["revealShown"] is True


def test_no_protected_paths_and_self_hygiene_zero_comments_dashes_or_network() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")

    for forbidden_dash in (
        HYPHEN_UNI,
        NB_HYPHEN,
        FIG_DASH,
        EN_DASH,
        EM_DASH,
        HORIZ_BAR,
        MINUS_SIGN,
    ):
        assert forbidden_dash not in src, f"Forbidden dash {ord(forbidden_dash):x} found in {self_path.name}"
    assert HASH_CHAR not in src, f"Hash character found in {self_path.name}"

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"Comment tokens found: {comments}"

    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden_mods = (
        "google",
        "genai",
        "openai",
        "anthropic",
        "atlas_gemini",
        "gateway",
        "httpx",
        "requests",
        "urllib",
        "socket",
    )
    for mod in imported:
        assert not any(f in mod for f in forbidden_mods), f"Forbidden module imported: {mod}"

    if PROTECTED_PATHS_FILE.exists():
        protected_entries: list[str] = []
        for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith(HASH_CHAR):
                continue
            protected_entries.append(line)
        suite_candidates: set[str] = {Path(__file__).resolve().relative_to(ROOT).as_posix()}
        for pattern in (
            "demo/out-think-gemini/**/*",
            "canary/gemini/outthink*.py",
            "tests/test_*outthink*.py",
            "docs/demo/**/*",
        ):
            for path in ROOT.glob(pattern):
                if path.is_file():
                    suite_candidates.add(path.relative_to(ROOT).as_posix())
        for c in sorted(suite_candidates):
            for p in protected_entries:
                if p.endswith("/"):
                    assert not c.startswith(p), f"Protected directory modified: {c}"
                else:
                    assert c != p, f"Protected file modified: {c}"
