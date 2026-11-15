from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import tokenize
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
INDEX_PATH = DEMO_DIR / "index.html"
STYLE_PATH = DEMO_DIR / "style.css"
ENGINE_PATH = DEMO_DIR / "engine.js"
SCENE_PATH = DEMO_DIR / "scene.js"
CHATTER_PATH = DEMO_DIR / "chatter.js"
GAME_PATH = DEMO_DIR / "game.js"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR
HTML_COMMENT_OPEN = "<" + "!--"
HTTP_PREFIX = "http" + ":" + SLASH + SLASH
HTTPS_PREFIX = "https" + ":" + SLASH + SLASH


class _ShellHTMLInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.scripts: list[str] = []
        self.links: list[str] = []
        self.imgs: list[str] = []
        self.tabs: list[str] = []
        self.comments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        if attr_map.get("id"):
            self.ids.append(attr_map["id"])
        if tag == "script" and "src" in attr_map:
            self.scripts.append(attr_map["src"])
        if tag == "link" and "href" in attr_map:
            self.links.append(attr_map["href"])
        if tag == "img" and "src" in attr_map:
            self.imgs.append(attr_map["src"])
        if "data-tab" in attr_map:
            self.tabs.append(attr_map["data-tab"])

    def handle_comment(self, data: str) -> None:
        self.comments.append(data)


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


DOM_HARNESS_JS = """
const fs = require("fs");
const vm = require("vm");

function createMockContext2D() {
  const stack = [];
  return {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    font: "10px monospace",
    textAlign: "left",
    globalAlpha: 1,
    imageSmoothingEnabled: true,
    webkitImageSmoothingEnabled: true,
    mozImageSmoothingEnabled: true,
    texts: [],
    fillRects: [],
    strokeRects: [],
    save: function () {
      stack.push({
        fillStyle: this.fillStyle,
        strokeStyle: this.strokeStyle,
        lineWidth: this.lineWidth,
        font: this.font,
        textAlign: this.textAlign,
        globalAlpha: this.globalAlpha
      });
    },
    restore: function () {
      const prev = stack.pop();
      if (prev) {
        this.fillStyle = prev.fillStyle;
        this.strokeStyle = prev.strokeStyle;
        this.lineWidth = prev.lineWidth;
        this.font = prev.font;
        this.textAlign = prev.textAlign;
        this.globalAlpha = prev.globalAlpha;
      }
    },
    fillRect: function (x, y, w, h) {
      this.fillRects.push({ x: x, y: y, w: w, h: h, fillStyle: String(this.fillStyle) });
    },
    strokeRect: function (x, y, w, h) {
      this.strokeRects.push({ x: x, y: y, w: w, h: h, strokeStyle: String(this.strokeStyle) });
    },
    fillText: function (txt, x, y) {
      this.texts.push(String(txt));
    },
    beginPath: function () {},
    moveTo: function () {},
    lineTo: function () {},
    closePath: function () {},
    stroke: function () {},
    fill: function () {},
    arc: function () {},
    drawImage: function () {}
  };
}

function createDomEnvironment(indexHtml) {
  function matchesSelector(node, sel) {
    if (!node || node.nodeType !== 1 || !sel) {
      return false;
    }
    const s = String(sel).trim();
    if (s.startsWith("[") && s.endsWith("]")) {
      const inner = s.slice(1, -1);
      const eqIdx = inner.indexOf("=");
      if (eqIdx === -1) {
        return Object.prototype.hasOwnProperty.call(node._attrs, inner);
      }
      const attrName = inner.slice(0, eqIdx).trim();
      const rawVal = inner.slice(eqIdx + 1).trim().replace(/^["']|["']$/g, "");
      return node.getAttribute(attrName) === rawVal;
    }
    if (s.startsWith(".")) {
      return node.classList.contains(s.slice(1));
    }
    return node.tagName.toLowerCase() === s.toLowerCase();
  }

  class MockElement {
    constructor(tagName) {
      this.nodeType = 1;
      this.tagName = String(tagName || "div").toUpperCase();
      this.id = "";
      this._classes = [];
      this._attrs = {};
      this._text = "";
      this._innerHTML = "";
      this.hidden = false;
      this.disabled = false;
      this.selected = false;
      this.value = "";
      this.type = "";
      this.alt = "";
      this.src = "";
      this.width = 0;
      this.height = 0;
      this.style = {};
      this.parentNode = null;
      this.childNodes = [];
      this._listeners = {};
      this._ctx2d = null;

      const self = this;
      this.classList = {
        add: function () {
          for (let i = 0; i < arguments.length; i += 1) {
            const c = String(arguments[i] || "").trim();
            if (c && self._classes.indexOf(c) === -1) {
              self._classes.push(c);
            }
          }
        },
        remove: function () {
          for (let i = 0; i < arguments.length; i += 1) {
            const c = String(arguments[i] || "").trim();
            const idx = self._classes.indexOf(c);
            if (idx >= 0) {
              self._classes.splice(idx, 1);
            }
          }
        },
        toggle: function (cls, force) {
          const c = String(cls || "").trim();
          const has = self._classes.indexOf(c) >= 0;
          const shouldHave = force !== undefined ? Boolean(force) : !has;
          if (shouldHave && !has) {
            self._classes.push(c);
          } else if (!shouldHave && has) {
            self._classes.splice(self._classes.indexOf(c), 1);
          }
          return shouldHave;
        },
        contains: function (cls) {
          return self._classes.indexOf(String(cls || "").trim()) >= 0;
        }
      };
    }

    get className() {
      return this._classes.join(" ");
    }

    set className(val) {
      this._classes = String(val || "")
        .split(/\\s+/)
        .map((x) => x.trim())
        .filter(Boolean);
    }

    get children() {
      return this.childNodes.filter((c) => c && c.nodeType === 1);
    }

    get firstChild() {
      return this.childNodes.length > 0 ? this.childNodes[0] : null;
    }

    get textContent() {
      let out = this._text || "";
      if (this._innerHTML) {
        out += this._innerHTML.replace(/<[^>]*>/g, "");
      }
      for (let i = 0; i < this.childNodes.length; i += 1) {
        out += this.childNodes[i].textContent;
      }
      return out;
    }

    set textContent(val) {
      this.childNodes = [];
      this._innerHTML = "";
      this._text = val === null || val === undefined ? "" : String(val);
    }

    get innerHTML() {
      return this._innerHTML;
    }

    set innerHTML(val) {
      this.childNodes = [];
      this._text = "";
      this._innerHTML = val === null || val === undefined ? "" : String(val);
    }

    getContext(kind) {
      if (this.tagName === "CANVAS" && kind === "2d") {
        if (!this._ctx2d) {
          this._ctx2d = createMockContext2D();
        }
        return this._ctx2d;
      }
      return null;
    }

    getBoundingClientRect() {
      return {
        left: 0,
        top: 0,
        width: this.width || 960,
        height: this.height || 520
      };
    }

    appendChild(child) {
      if (!child) {
        return child;
      }
      if (child.parentNode) {
        child.parentNode.removeChild(child);
      }
      child.parentNode = this;
      this.childNodes.push(child);
      if (this.tagName === "SELECT" && child.tagName === "OPTION") {
        if (child.selected || !this.value) {
          this.value = child.value;
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

    setAttribute(name, value) {
      const k = String(name);
      const v = String(value);
      this._attrs[k] = v;
      if (k === "id") {
        this.id = v;
      } else if (k === "class") {
        this.className = v;
      } else if (k === "hidden") {
        this.hidden = true;
      } else if (k === "disabled") {
        this.disabled = true;
      }
    }

    getAttribute(name) {
      const k = String(name);
      if (k === "id") {
        return this.id || null;
      }
      if (k === "class") {
        return this.className || null;
      }
      return Object.prototype.hasOwnProperty.call(this._attrs, k) ? this._attrs[k] : null;
    }

    hasAttribute(name) {
      return this.getAttribute(name) !== null;
    }

    addEventListener(type, fn) {
      if (!this._listeners[type]) {
        this._listeners[type] = [];
      }
      this._listeners[type].push(fn);
    }

    removeEventListener(type, fn) {
      const list = this._listeners[type];
      if (!Array.isArray(list)) {
        return;
      }
      const idx = list.indexOf(fn);
      if (idx >= 0) {
        list.splice(idx, 1);
      }
    }

    dispatchEvent(eventObj) {
      const ev = Object.assign({ type: "click", target: this }, eventObj || {});
      if (!ev.target) {
        ev.target = this;
      }
      let cur = this;
      while (cur) {
        const list = cur._listeners && cur._listeners[ev.type] ? cur._listeners[ev.type].slice() : [];
        for (let i = 0; i < list.length; i += 1) {
          list[i].call(cur, ev);
        }
        cur = cur.parentNode;
      }
      return true;
    }

    click() {
      if (this.disabled) {
        return;
      }
      this.dispatchEvent({ type: "click", target: this });
    }

    closest(selector) {
      let cur = this;
      while (cur) {
        if (matchesSelector(cur, selector)) {
          return cur;
        }
        cur = cur.parentNode;
      }
      return null;
    }

    querySelectorAll(selector) {
      const hits = [];
      function walk(n) {
        for (let i = 0; i < n.childNodes.length; i += 1) {
          const ch = n.childNodes[i];
          if (matchesSelector(ch, selector)) {
            hits.push(ch);
          }
          walk(ch);
        }
      }
      walk(this);
      return hits;
    }

    querySelector(selector) {
      const all = this.querySelectorAll(selector);
      return all.length > 0 ? all[0] : null;
    }

    scrollIntoView() {}
  }

  const body = new MockElement("body");
  const tagRegex = /<([a-zA-Z0-9]+)\\b([^>]*)>/g;
  let match;
  let tabsContainer = null;

  while ((match = tagRegex.exec(indexHtml)) !== null) {
    const tag = match[1].toLowerCase();
    const attrStr = match[2] || "";
    const idMatch = attrStr.match(/\\bid="([^"]+)"/);
    const tabMatch = attrStr.match(/\\bdata-tab="([^"]+)"/);
    const classMatch = attrStr.match(/\\bclass="([^"]+)"/);
    const hasHidden = /\\bhidden\\b/.test(attrStr);

    if (idMatch && idMatch[1] === "evidence-tabs") {
      tabsContainer = new MockElement(tag);
      tabsContainer.id = "evidence-tabs";
      if (classMatch) {
        tabsContainer.className = classMatch[1];
      }
      body.appendChild(tabsContainer);
      continue;
    }

    if (tabMatch && tabsContainer) {
      const btn = new MockElement("button");
      btn.setAttribute("data-tab", tabMatch[1]);
      if (classMatch) {
        btn.className = classMatch[1];
      }
      const countSpan = new MockElement("span");
      countSpan.id = "count-" + tabMatch[1];
      countSpan.className = "tab-count";
      countSpan.textContent = "0";
      btn.appendChild(countSpan);
      tabsContainer.appendChild(btn);
      continue;
    }

    if (idMatch) {
      const idVal = idMatch[1];
      if (idVal.indexOf("count-") === 0) {
        continue;
      }
      const node = new MockElement(tag);
      node.id = idVal;
      if (classMatch) {
        node.className = classMatch[1];
      }
      if (hasHidden) {
        node.hidden = true;
      }
      body.appendChild(node);
    }
  }

  const doc = {
    readyState: "complete",
    body: body,
    createElement: function (tag) {
      return new MockElement(tag);
    },
    getElementById: function (id) {
      let found = null;
      function search(n) {
        if (found) {
          return;
        }
        if (n.id === id) {
          found = n;
          return;
        }
        for (let i = 0; i < n.childNodes.length; i += 1) {
          search(n.childNodes[i]);
        }
      }
      search(body);
      return found;
    },
    querySelectorAll: function (sel) {
      return body.querySelectorAll(sel);
    },
    querySelector: function (sel) {
      return body.querySelector(sel);
    },
    addEventListener: function () {}
  };

  return { document: doc, MockElement: MockElement };
}

function bootShell(setupWindowFn, options) {
  const opts = options || {};
  const indexHtml = fs.readFileSync(process.env.OUTTHINK_INDEX_PATH, "utf8");
  const engineCode = fs.readFileSync(process.env.OUTTHINK_ENGINE_PATH, "utf8");
  const gameCode = fs.readFileSync(process.env.OUTTHINK_GAME_PATH, "utf8");
  const dom = createDomEnvironment(indexHtml);

  const win = {
    document: dom.document,
    console: console,
    Math: Math,
    Number: Number,
    String: String,
    Boolean: Boolean,
    Array: Array,
    Object: Object,
    JSON: JSON,
    Date: Date,
    Error: Error,
    isFinite: isFinite,
    parseInt: parseInt,
    parseFloat: parseFloat
  };
  win.window = win;
  win.globalThis = win;

  const ctx = vm.createContext(win);
  if (opts.loadChatter) {
    const chatterCode = fs.readFileSync(process.env.OUTTHINK_CHATTER_PATH, "utf8");
    vm.runInContext(chatterCode, ctx, { filename: "chatter.js" });
  }
  vm.runInContext(engineCode, ctx, { filename: "engine.js" });
  if (opts.loadScene) {
    const sceneCode = fs.readFileSync(process.env.OUTTHINK_SCENE_PATH, "utf8");
    vm.runInContext(sceneCode, ctx, { filename: "scene.js" });
  }
  if (typeof setupWindowFn === "function") {
    setupWindowFn(win, dom.document);
  }
  vm.runInContext(gameCode, ctx, { filename: "game.js" });
  return { window: win, document: dom.document };
}
"""


def _run_shell_js(js_body: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_INDEX_PATH"] = str(INDEX_PATH)
    run_env["OUTTHINK_ENGINE_PATH"] = str(ENGINE_PATH)
    run_env["OUTTHINK_SCENE_PATH"] = str(SCENE_PATH)
    run_env["OUTTHINK_CHATTER_PATH"] = str(CHATTER_PATH)
    run_env["OUTTHINK_GAME_PATH"] = str(GAME_PATH)
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        DOM_HARNESS_JS
        + "\nconst PAYLOAD = JSON.parse(process.env.OUTTHINK_TEST_PAYLOAD);\n"
        + "const out = (() => {\n"
        + js_body
        + "\n})();\n"
        + "process.stdout.write(JSON.stringify(out));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS shell failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _find_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    in_regex = False
    in_regex_class = False
    prev_sig = "("

    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\":
                if i + 1 < n and source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
                prev_sig = '"'
            i += 1
            continue

        if in_regex:
            if ch == "\\":
                i += 2
                continue
            if ch == "\n":
                in_regex = False
                in_regex_class = False
                line += 1
                i += 1
                continue
            if ch == "[" and not in_regex_class:
                in_regex_class = True
            elif ch == "]" and in_regex_class:
                in_regex_class = False
            elif ch == SLASH and not in_regex_class:
                in_regex = False
                prev_sig = SLASH
            i += 1
            continue

        if ch in ("'", '"', "`"):
            in_quote = ch
            i += 1
            continue

        if ch == "\n":
            line += 1
            i += 1
            continue

        if ch.isspace():
            i += 1
            continue

        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, LINE_COMMENT))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, BLOCK_COMMENT_OPEN))
                i += 2
                while i < n:
                    if source[i] == "\n":
                        line += 1
                    if source[i] == STAR and i + 1 < n and source[i + 1] == SLASH:
                        i += 2
                        break
                    i += 1
                continue
            if prev_sig in " (,=:[!&|?{};+-*%<>^~":
                in_regex = True
                in_regex_class = False
                i += 1
                continue

        prev_sig = ch
        i += 1

    return hits


def _load_protected_rules() -> list[str]:
    assert PROTECTED_PATHS_FILE.is_file()
    rules: list[str] = []
    for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(HASH_CHAR):
            continue
        rules.append(stripped)
    return rules


def _matches_protected_rule(rel_path: str, rules: list[str]) -> bool:
    for rule in rules:
        if rule.endswith("/"):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def test_index_html_script_order_and_zero_external_urls():
    for path in (INDEX_PATH, STYLE_PATH, ENGINE_PATH, SCENE_PATH, CHATTER_PATH, GAME_PATH):
        assert path.is_file(), f"missing live shell file: {path}"
        content = path.read_text(encoding="utf-8")
        assert HTTP_PREFIX not in content, f"external http URL found in {path.name}"
        assert HTTPS_PREFIX not in content, f"external https URL found in {path.name}"

    html_txt = INDEX_PATH.read_text(encoding="utf-8")
    inspector = _ShellHTMLInspector()
    inspector.feed(html_txt)

    assert inspector.comments == []
    assert inspector.links == ["style.css"]
    assert inspector.imgs == []
    assert inspector.tabs == ["canaries", "leaks", "access", "comms", "steps"]

    required_ids = {
        "phaser-stage",
        "stage-fallback",
        "dataset-badge",
        "case-select",
        "btn-prev-case",
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
        "suspect-roster",
        "dossier-clearance",
        "dossier-card",
        "btn-accuse",
        "btn-hold-fire",
        "btn-filter-suspect",
        "evidence-cutoff-note",
        "evidence-tabs",
        "evidence-list",
        "reveal-panel",
        "provenance-footer",
        "provenance-summary",
        "asset-credits-list",
    }
    assert required_ids.issubset(set(inspector.ids))

    scripts = inspector.scripts
    for src in scripts:
        assert not src.startswith(SLASH)
        assert ":" not in src
        assert src.endswith(".js")

    for data_script in (
        "assets/manifest.js",
        "fallback_cases.js",
        "cases.js",
        "annotations.js",
        "personas.js",
        "evidence_cards.js",
        "chatter.js",
    ):
        assert data_script in scripts
        assert scripts.index(data_script) < scripts.index("engine.js")
        assert scripts.index(data_script) < scripts.index("scene.js")
        assert scripts.index(data_script) < scripts.index("game.js")

    assert scripts.index("engine.js") < scripts.index("scene.js")
    assert scripts.index("scene.js") < scripts.index("game.js")


def test_initial_render_graceful_degradation_and_pre_decision_non_leak():
    res = _run_shell_js(
        """
        const env = bootShell();
        const doc = env.document;

        const rosterChips = doc.getElementById("suspect-roster").children;
        const scoreTiles = doc.getElementById("scoreboard-bar").children;
        const fallbackEl = doc.getElementById("stage-fallback");
        const fallbackHidden = fallbackEl.hidden;
        const fallbackText = fallbackEl.textContent;
        const revealHidden = doc.getElementById("reveal-panel").hidden;
        const dossierText = doc.getElementById("dossier-card").textContent;
        const evidenceText = doc.getElementById("evidence-list").textContent;
        const provenanceText = doc.getElementById("provenance-summary").textContent;
        const creditsText = doc.getElementById("asset-credits-list").textContent;

        return {
          datasetBadge: doc.getElementById("dataset-badge").textContent,
          caseTitle: doc.getElementById("case-title").textContent,
          caseDay: doc.getElementById("case-day-badge").textContent,
          caseStep: doc.getElementById("case-step-badge").textContent,
          caseReward: doc.getElementById("case-reward-badge").textContent,
          caseStatus: doc.getElementById("case-status-pill").textContent,
          accuseBtn: doc.getElementById("btn-accuse").textContent,
          accuseDisabled: doc.getElementById("btn-accuse").disabled,
          holdDisabled: doc.getElementById("btn-hold-fire").disabled,
          rosterCount: rosterChips.length,
          scoreTileCount: scoreTiles.length,
          fallbackHidden: fallbackHidden,
          fallbackText: fallbackText,
          revealHidden: revealHidden,
          revealText: doc.getElementById("reveal-panel").textContent,
          dossierText: dossierText,
          evidenceText: evidenceText,
          provenanceText: provenanceText,
          creditsText: creditsText
        };
        """
    )

    assert res["datasetBadge"] == "Bootstrap Case (1)"
    assert "Bootstrap Canary Case" in res["caseTitle"]
    assert res["caseDay"] == "Day 4"
    assert res["caseStep"] == "Step 6"
    assert res["caseReward"] == "+0.72"
    assert res["caseStatus"] == "AWAITING CALL"
    assert res["accuseBtn"] == "ACCUSE e02 NOW"
    assert res["accuseDisabled"] is False
    assert res["holdDisabled"] is False
    assert res["rosterCount"] == 3
    assert res["scoreTileCount"] == 7
    assert res["fallbackHidden"] is False
    assert "Gemini Thinking Pods:" in res["fallbackText"]
    assert "XHIGH" in res["fallbackText"]
    assert res["revealHidden"] is True
    assert res["revealText"] == ""
    assert "0 live API calls in browser" in res["provenanceText"]
    assert "docs/demo/ASSETS.md" in res["creditsText"]
    assert "CONFIRMED MOLE" not in res["dossierText"]
    assert "True Mole" not in res["dossierText"]
    assert "CONFIRMED MOLE" not in res["evidenceText"]


def test_suspect_selection_highlight_filter_and_tab_switching():
    res = _run_shell_js(
        """
        const env = bootShell();
        const doc = env.document;

        const rosterBtns = doc.getElementById("suspect-roster").children;
        rosterBtns[2].click();
        const afterSelectAccuse = doc.getElementById("btn-accuse").textContent;
        const afterSelectDossier = doc.getElementById("dossier-card").textContent;

        doc.getElementById("btn-highlight-suspects").click();
        const highlightSummary = doc.getElementById("highlight-summary").textContent;

        const tabSnapshots = {};
        const tabBtns = doc.getElementById("evidence-tabs").querySelectorAll("[data-tab]");
        for (let i = 0; i < tabBtns.length; i += 1) {
          const tName = tabBtns[i].getAttribute("data-tab");
          tabBtns[i].click();
          tabSnapshots[tName] = {
            active: tabBtns[i].getAttribute("aria-selected"),
            text: doc.getElementById("evidence-list").textContent
          };
        }

        rosterBtns[0].click();
        doc.getElementById("btn-filter-suspect").click();
        const filterLabel = doc.getElementById("btn-filter-suspect").textContent;
        tabBtns[2].click();
        const accessFilteredE01 = doc.getElementById("evidence-list").textContent;

        return {
          afterSelectAccuse,
          afterSelectDossier,
          highlightSummary,
          tabSnapshots,
          filterLabel,
          accessFilteredE01
        };
        """
    )

    assert res["afterSelectAccuse"] == "ACCUSE e03 NOW"
    assert "e03 - Timo Salo" in res["afterSelectDossier"]
    assert "e02, e03" in res["highlightSummary"]

    snaps = res["tabSnapshots"]
    assert snaps["canaries"]["active"] == "true"
    assert "c01 | doc_phase2_readout" in snaps["canaries"]["text"]
    assert snaps["leaks"]["active"] == "true"
    assert "Variant B phrasing surfaced" in snaps["leaks"]["text"]
    assert snaps["access"]["active"] == "true"
    assert "export doc_phase2_readout" in snaps["access"]["text"]
    assert snaps["comms"]["active"] == "true"
    assert "Need the unredacted slide figures" in snaps["comms"]["text"]
    assert snaps["steps"]["active"] == "true"
    assert "plant_canary" in snaps["steps"]["text"]

    assert res["filterLabel"] == "Filter: e01 Only"
    assert "No audit access logs for current filter." in res["accessFilteredE01"]


def test_accuse_hold_fire_next_prev_case_and_reset_scores():
    dataset = {
        "cases": [
            {
                "id": "case-alpha",
                "title": "Alpha Export Trap",
                "tier": "hard",
                "seed": 11,
                "company": "Aegis Bio",
                "decision_day": 5,
                "decision_step": 8,
                "value_at_decision": 0.75,
                "true_mole": "e03",
                "suspects": [
                    {"id": "e01", "name": "Sami", "eliminated": True, "canary_hits": 0},
                    {"id": "e02", "name": "Mina", "eliminated": False, "canary_hits": 0},
                    {"id": "e03", "name": "Timo", "eliminated": False, "canary_hits": 2},
                ],
                "leaks": [
                    {"day": 4, "doc_id": "doc_a", "canary_id": "c1", "leaked_variant": "V2", "summary": "Pre-decision leak"},
                    {"day": 9, "doc_id": "doc_future", "canary_id": "c9", "leaked_variant": "V9", "summary": "FUTURE_LEAK_SPOILER"},
                ],
                "solver": {
                    "posterior": {"e02": 0.03, "e03": 0.97},
                    "top_suspect": "e03",
                    "top_prob": 0.97,
                    "break_even_prob": 0.5714,
                    "recommended_call": "accuse",
                    "final_accused": "e03",
                    "final_day": 5,
                    "final_score": 0.75,
                    "correct": True,
                },
                "thinking_levels": [
                    {"thinking_level": "minimal", "accused": "e02", "correct": False, "score": -1.0, "cost_usd": 0.002, "thinking_tokens": 64},
                    {"thinking_level": "high", "accused": "e03", "correct": True, "score": 0.75, "cost_usd": 0.021, "thinking_tokens": 2500},
                ],
            },
            {
                "id": "case-beta",
                "title": "Beta Split Ambiguity",
                "tier": "hard",
                "seed": 12,
                "company": "Polaris Labs",
                "decision_day": 3,
                "decision_step": 4,
                "value_at_decision": 0.4,
                "true_mole": "e04",
                "suspects": [
                    {"id": "e02", "name": "Noora", "eliminated": False, "canary_hits": 1},
                    {"id": "e04", "name": "Kari", "eliminated": False, "canary_hits": 1},
                ],
                "solver": {
                    "posterior": {"e02": 0.5, "e04": 0.5},
                    "top_suspect": "e04",
                    "top_prob": 0.5,
                    "break_even_prob": 0.7143,
                    "ev_hold_fire": 0.48,
                    "recommended_call": "hold_fire",
                    "final_accused": "e04",
                    "final_day": 6,
                    "final_score": 0.48,
                    "correct": True,
                },
                "thinking_levels": [
                    {"thinking_level": "minimal", "accused": "e02", "correct": False, "score": -1.0, "cost_usd": 0.003, "thinking_tokens": 80},
                    {"thinking_level": "high", "call_at_t": "hold_fire", "accused": "e04", "correct": True, "score": 0.48, "cost_usd": 0.025, "thinking_tokens": 3100},
                ],
            },
        ]
    }

    res = _run_shell_js(
        """
        const env = bootShell((win) => {
          win.OUTTHINK_DATA = PAYLOAD;
        });
        const doc = env.document;

        const tabBtns = doc.getElementById("evidence-tabs").querySelectorAll("[data-tab]");
        tabBtns[1].click();
        const leaksBeforeCall = doc.getElementById("evidence-list").textContent;

        const roster = doc.getElementById("suspect-roster").children;
        roster[2].click();
        doc.getElementById("btn-accuse").click();

        const revealAfterAccuseHidden = doc.getElementById("reveal-panel").hidden;
        const revealAfterAccuseText = doc.getElementById("reveal-panel").textContent;
        const accuseDisabledAfterCall = doc.getElementById("btn-accuse").disabled;
        const scoreAfterCase1 = doc.getElementById("scoreboard-bar").textContent;

        doc.getElementById("btn-next-case").click();
        const case2Title = doc.getElementById("case-title").textContent;
        const revealHiddenOnCase2 = doc.getElementById("reveal-panel").hidden;
        const nextDisabledOnLast = doc.getElementById("btn-next-case").disabled;

        doc.getElementById("btn-hold-fire").click();
        const revealAfterHoldHidden = doc.getElementById("reveal-panel").hidden;
        const revealAfterHoldText = doc.getElementById("reveal-panel").textContent;
        const scoreAfterCase2 = doc.getElementById("scoreboard-bar").textContent;

        doc.getElementById("btn-prev-case").click();
        const backToCase1Title = doc.getElementById("case-title").textContent;
        const case1PersistedReveal = !doc.getElementById("reveal-panel").hidden;

        doc.getElementById("btn-reset-scores").click();
        const scoreAfterReset = doc.getElementById("scoreboard-bar").textContent;
        const revealHiddenAfterReset = doc.getElementById("reveal-panel").hidden;
        const accuseEnabledAfterReset = !doc.getElementById("btn-accuse").disabled;

        return {
          leaksBeforeCall,
          revealAfterAccuseHidden,
          revealAfterAccuseText,
          accuseDisabledAfterCall,
          scoreAfterCase1,
          case2Title,
          revealHiddenOnCase2,
          nextDisabledOnLast,
          revealAfterHoldHidden,
          revealAfterHoldText,
          scoreAfterCase2,
          backToCase1Title,
          case1PersistedReveal,
          scoreAfterReset,
          revealHiddenAfterReset,
          accuseEnabledAfterReset
        };
        """,
        dataset,
    )

    assert "Pre-decision leak" in res["leaksBeforeCall"]
    assert "FUTURE_LEAK_SPOILER" not in res["leaksBeforeCall"]

    assert res["revealAfterAccuseHidden"] is False
    assert "OPTIMAL ACCUSATION" in res["revealAfterAccuseText"]
    assert "True Mole: e03" in res["revealAfterAccuseText"]
    assert res["accuseDisabledAfterCall"] is True
    assert "1/2" in res["scoreAfterCase1"]
    assert "+0.75" in res["scoreAfterCase1"]

    assert res["case2Title"] == "Beta Split Ambiguity"
    assert res["revealHiddenOnCase2"] is True
    assert res["nextDisabledOnLast"] is True

    assert res["revealAfterHoldHidden"] is False
    assert "OPTIMAL HOLD FIRE" in res["revealAfterHoldText"]
    assert "2/2" in res["scoreAfterCase2"]
    assert "+1.23" in res["scoreAfterCase2"]
    assert "OUT-THOUGHT" in res["scoreAfterCase2"]

    assert res["backToCase1Title"] == "Alpha Export Trap"
    assert res["case1PersistedReveal"] is True

    assert "0/2" in res["scoreAfterReset"]
    assert "No calls" in res["scoreAfterReset"]
    assert res["revealHiddenAfterReset"] is True
    assert res["accuseEnabledAfterReset"] is True


def test_live_scene_chatter_personas_annotations_and_canvas_bridge():
    res = _run_shell_js(
        """
        const env = bootShell(
          (win) => {
            const cleanOut = win.getOutthinkChatter({
              tier: "medium",
              seed: 3001,
              suspectId: "e02",
              dept: "Clinical Data",
              role: "Biostatistician",
              afterHoursCount: 1
            });
            const taintedOut = win.getOutthinkChatter({
              tier: "medium",
              seed: 3001,
              suspectId: "e02",
              dept: "Clinical Data",
              role: "Biostatistician",
              afterHoursCount: 1,
              true_mole: "e02",
              is_mole: true,
              mole_strategy: "smuggle_secret",
              secret: "TOP_SECRET_TRUTH_TOKEN"
            });
            win.__chatterParityJsonMatch = JSON.stringify(cleanOut) === JSON.stringify(taintedOut);
            win.__chatterProv = win.OUTTHINK_CHATTER.getProvenanceSummary();

            const firstChat = cleanOut.chatter[0];
            const firstRumor = cleanOut.rumors[0];
            const ivLine = cleanOut.interview.response;

            win.OUTTHINK_DATA = {
              meta: {
                total_episodes: 300,
                total_cost_usd: 11.45
              },
              cases: [
                {
                  id: "live-medium-3001",
                  title: "Helix Readout Canary",
                  tier: "medium",
                  seed: 3001,
                  company: "Helix Dynamics",
                  decision_day: 4,
                  decision_step: 6,
                  value_at_decision: 0.72,
                  true_mole: "e03",
                  suspects: [
                    { id: "e01", name: "Sami Korhonen", dept: "IT Ops", role: "SysAdmin", clearance: "high", eliminated: true, canary_hits: 0, after_hours_count: 2 },
                    { id: "e02", name: "Mina Laine", dept: "Clinical Data", role: "Biostatistician", clearance: "elevated", eliminated: false, canary_hits: 1, after_hours_count: 1 },
                    { id: "e03", name: "Timo Salo", dept: "Strategy", role: "VP Partnerships", clearance: "executive", eliminated: false, canary_hits: 1, after_hours_count: 4 }
                  ],
                  canaries: [
                    {
                      canary_id: "c01",
                      doc_id: "doc_phase2_readout",
                      day_planted: 2,
                      leaked_variant: "B",
                      variants: [
                        { variant: "A", recipients: ["e01"] },
                        { variant: "B", recipients: ["e02", "e03"] }
                      ]
                    }
                  ],
                  leaks: [
                    { day: 3, doc_id: "doc_phase2_readout", canary_id: "c01", leaked_variant: "B", channel: "press", summary: "Variant B surfaced externally." }
                  ],
                  comms: [
                    { day: 2, kind: firstChat.kind, speaker: "e02", target: "all", topic: firstChat.topic, text: firstChat.text },
                    { day: 3, kind: "rumor", speaker: "e01", target: "all", topic: firstRumor.bias_type, text: firstRumor.text },
                    { day: 3, kind: "interview", speaker: "e02", target: "investigator", topic: "alibi", text: ivLine },
                    { day: 99, kind: "slack", speaker: "e03", target: "all", topic: "future", text: "POST_DECISION_COMMS_MUST_NOT_APPEAR" }
                  ],
                  solver: {
                    posterior: { e01: 0.0, e02: 0.5, e03: 0.5 },
                    top_suspect: "e03",
                    top_prob: 0.5,
                    break_even_prob: 0.5814,
                    ev_accuse_top: -0.14,
                    ev_hold_fire: 0.64,
                    recommended_call: "hold_fire",
                    final_accused: "e03",
                    final_day: 5,
                    final_score: 0.64,
                    correct: True_val()
                  },
                  thinking_levels: [
                    { thinking_level: "minimal", model: "gemini-3-flash-preview", call_at_t: "accuse", accused: "e02", accused_day: 4, correct: false, score: -1.0, cost_usd: 0.0019, thinking_tokens: 64 },
                    { thinking_level: "high", model: "gemini-3-flash-preview", call_at_t: "hold_fire", accused: "e03", accused_day: 5, correct: true, score: 0.64, cost_usd: 0.0148, thinking_tokens: 2420 }
                  ],
                  cross_model_carbon: [
                    { model: "gemini-4-carbon", thinking_level: "low", accused: "e02", accused_day: 4, correct: false, score: -1.0, cost_usd: 0.0041, thinking_tokens: 310 },
                    { model: "gemini-4-carbon", thinking_level: "high", accused: "e03", accused_day: 5, correct: true, score: 0.64, cost_usd: 0.0295, thinking_tokens: 2890 }
                  ]
                }
              ]
            };

            function True_val() {
              return true;
            }

            win.OUTTHINK_PERSONAS = {
              worlds: {
                "medium:3001": {
                  suspects: {
                    e03: {
                      persona_note: "Runs partner diligence calls across three time zones.",
                      bias_cue: "Late night calendar blocks before board updates"
                    }
                  }
                }
              }
            };

            win.OUTTHINK_ANNOTATIONS = {
              "medium:3001:minimal": {
                primary_failure_tag: "premature_accusation",
                regret_total: 1.54,
                quotes: [
                  {
                    quote: "Jumping straight to e02 without bisecting Variant B.",
                    source_file: "results/gemini/v2/atlas.json",
                    day: 4,
                    step: 6
                  }
                ]
              }
            };

            win.OUTTHINK_ASSETS = {
              packs: [
                { id: "noir-office", name: "Noir Pixel Office", author: "Kenney", license: "CC0-1.0" }
              ]
            };
          },
          { loadChatter: true, loadScene: true }
        );

        const win = env.window;
        const doc = env.document;
        const stageEl = doc.getElementById("phaser-stage");
        const canvases = stageEl.querySelectorAll("canvas");
        const canvas = canvases[0];
        const ctx2d = canvas.getContext("2d");

        const preTexts = ctx2d.texts.slice();

        canvas.dispatchEvent({ type: "click", clientX: 90, clientY: 330 });
        const accuseAfterCanvasStation = doc.getElementById("btn-accuse").textContent;
        const dossierAfterCanvasStation = doc.getElementById("dossier-card").textContent;

        canvas.dispatchEvent({ type: "click", clientX: 520, clientY: 40 });
        const commsTabBtn = doc.getElementById("evidence-tabs").querySelectorAll("[data-tab]")[3];
        const commsActiveFromCanvas = commsTabBtn.getAttribute("aria-selected");
        const commsText = doc.getElementById("evidence-list").textContent;
        const commsCount = doc.getElementById("count-comms").textContent;

        const loadedDataset = win.OutThinkEngine.loadDataset();
        const caseWithChatter = loadedDataset.cases[0];
        const caseWithoutChatter = Object.assign({}, caseWithChatter, { comms: [] });
        const evalWith = win.OutThinkEngine.evaluateCall(caseWithChatter, { action: "hold_fire" });
        const evalWithout = win.OutThinkEngine.evaluateCall(caseWithoutChatter, { action: "hold_fire" });
        const solverParityMatch = JSON.stringify(evalWith) === JSON.stringify(evalWithout);

        doc.getElementById("btn-hold-fire").click();
        const postRevealCanvasTexts = ctx2d.texts.slice();

        canvas.dispatchEvent({ type: "click", clientX: 800, clientY: 130 });
        const minimalCard = doc.getElementById("reveal-panel").querySelector('[data-level-key="minimal"]');
        const minimalPodFocused = minimalCard ? minimalCard.classList.contains("is-pod-focused") : false;

        return {
          chatterParityJsonMatch: win.__chatterParityJsonMatch,
          chatterRole: win.__chatterProv.role,
          chatterModel: win.__chatterProv.model_id,
          chatterCalls: win.__chatterProv.calls,
          chatterPersonas: win.__chatterProv.personas,
          chatterLeaksDetected: win.__chatterProv.leaks_detected,
          canvasCount: canvases.length,
          canvasWidth: canvas.width,
          canvasHeight: canvas.height,
          smoothingOff: ctx2d.imageSmoothingEnabled === false,
          fallbackHiddenWithScene: doc.getElementById("stage-fallback").hidden,
          preSealedStatusRendered: preTexts.some((t) => t.indexOf("STATUS: PODS SEALED") >= 0),
          accuseAfterCanvasStation,
          dossierAfterCanvasStation,
          commsActiveFromCanvas,
          commsText,
          commsCount,
          solverParityMatch,
          postRevealedStatusRendered: postRevealCanvasTexts.some((t) => t.indexOf("STATUS: CASE REVEALED") >= 0),
          revealText: doc.getElementById("reveal-panel").textContent,
          minimalPodFocused,
          provenanceSummary: doc.getElementById("provenance-summary").textContent,
          creditsText: doc.getElementById("asset-credits-list").textContent
        };
        """
    )

    assert res["chatterParityJsonMatch"] is True
    assert res["chatterRole"] == "world_text"
    assert res["chatterModel"] == "gemini-4-carbon"
    assert res["chatterCalls"] == 1637
    assert res["chatterPersonas"] == 648
    assert res["chatterLeaksDetected"] == 0

    assert res["canvasCount"] == 1
    assert res["canvasWidth"] == 960
    assert res["canvasHeight"] == 520
    assert res["smoothingOff"] is True
    assert res["fallbackHiddenWithScene"] is True
    assert res["preSealedStatusRendered"] is True

    assert res["accuseAfterCanvasStation"] == "ACCUSE e03 NOW"
    assert "Runs partner diligence calls across three time zones." in res["dossierAfterCanvasStation"]
    assert "Surface cue: Late night calendar blocks before board updates" in res["dossierAfterCanvasStation"]

    assert res["commsActiveFromCanvas"] == "true"
    assert res["commsCount"] == "3"
    assert "POST_DECISION_COMMS_MUST_NOT_APPEAR" not in res["commsText"]
    assert "TOP_SECRET_TRUTH_TOKEN" not in res["commsText"]
    assert res["solverParityMatch"] is True

    assert res["postRevealedStatusRendered"] is True
    assert res["minimalPodFocused"] is True
    assert "premature_accusation" in res["revealText"]
    assert "Regret 1.54" in res["revealText"]
    assert "Jumping straight to e02 without bisecting Variant B." in res["revealText"]
    assert "results/gemini/v2/atlas.json" in res["revealText"]
    assert "Day 4 | Step 6" in res["revealText"]
    assert "Same World on gemini-4-carbon (low vs high)" in res["revealText"]
    assert "300 recorded ladder episodes" in res["provenanceSummary"]
    assert "Noir Pixel Office by Kenney (CC0-1.0)" in res["creditsText"]


def test_shell_hygiene_zero_comments_dashes_fetch_xhr_and_protected_paths():
    for path in (INDEX_PATH, STYLE_PATH, GAME_PATH, ENGINE_PATH, SCENE_PATH, CHATTER_PATH):
        txt = path.read_text(encoding="utf-8")
        assert EM_DASH not in txt, f"em dash in {path}"
        assert EN_DASH not in txt, f"en dash in {path}"
        assert re.search(r"\bfetch\s*\(", txt) is None, f"fetch() in {path}"
        assert "XMLHttpRequest" not in txt, f"XMLHttpRequest in {path}"
        assert "WebSocket" not in txt, f"WebSocket in {path}"
        assert "EventSource" not in txt, f"EventSource in {path}"

    assert HTML_COMMENT_OPEN not in INDEX_PATH.read_text(encoding="utf-8")
    assert BLOCK_COMMENT_OPEN not in STYLE_PATH.read_text(encoding="utf-8")
    assert _find_js_comments(GAME_PATH.read_text(encoding="utf-8")) == []
    assert _find_js_comments(ENGINE_PATH.read_text(encoding="utf-8")) == []
    assert _find_js_comments(SCENE_PATH.read_text(encoding="utf-8")) == []
    assert _find_js_comments(CHATTER_PATH.read_text(encoding="utf-8")) == []

    self_path = Path(__file__).resolve()
    self_src = self_path.read_text(encoding="utf-8")
    assert EM_DASH not in self_src
    assert EN_DASH not in self_src
    assert HASH_CHAR not in self_src
    assert HTTP_PREFIX not in self_src
    assert HTTPS_PREFIX not in self_src
    py_comments = [
        tok for tok in tokenize.generate_tokens(io.StringIO(self_src).readline) if tok.type == tokenize.COMMENT
    ]
    assert py_comments == []

    tree = ast.parse(self_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "genai" not in alias.name and "google" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "genai" not in node.module and "google" not in node.module

    rules = _load_protected_rules()
    checked = {
        INDEX_PATH.relative_to(ROOT).as_posix(),
        STYLE_PATH.relative_to(ROOT).as_posix(),
        GAME_PATH.relative_to(ROOT).as_posix(),
        ENGINE_PATH.relative_to(ROOT).as_posix(),
        SCENE_PATH.relative_to(ROOT).as_posix(),
        CHATTER_PATH.relative_to(ROOT).as_posix(),
        self_path.relative_to(ROOT).as_posix(),
    }
    violations = sorted(rel for rel in checked if _matches_protected_rule(rel, rules))
    assert violations == []
