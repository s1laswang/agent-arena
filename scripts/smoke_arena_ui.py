from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HASH_CH = chr(35)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)

CHECK_STATIC = "Arena UI Hygiene, Assets & Zero XSS Sinks"
CHECK_BOOT = "Headless Boot: index.js, OfficeStage & ai_duel_panel.js"
CHECK_MODES = "Four-Mode Smoke: duel, solver, mole & living"

CHECK_NAMES: tuple[str, ...] = (
    CHECK_STATIC,
    CHECK_BOOT,
    CHECK_MODES,
)

FORBIDDEN_XSS_SINKS: tuple[str, ...] = (
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "document.writeln",
)

FORBIDDEN_EVAL_RXES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("eval()", re.compile(r"\beval\s*\(")),
    ("new Function()", re.compile(r"\bnew\s+Function\s*\(")),
)

FORBIDDEN_LIVE_API_TOKENS: tuple[str, ...] = (
    "generativelanguage.googleapis.com",
    "api.openai.com",
    "api.anthropic.com",
)

EXPECTED_MODE_IDS: tuple[str, ...] = ("duel", "solver", "mole", "living")

EXPECTED_TOOL_NAMES: tuple[str, ...] = (
    "status",
    "list_employees",
    "list_documents",
    "read_access_logs",
    "search_messages",
    "read_message",
    "interview",
    "plant_canary",
    "check_leak_feed",
    "restrict_access",
    "unrestrict_access",
    "advance_day",
    "accuse",
)

HTML_COMMENT_RX = re.compile(r"<!--.*?-->", re.DOTALL)
SCRIPT_SRC_RX = re.compile(r"<script\b[^>]*?\bsrc\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE)
LINK_HREF_RX = re.compile(r"<link\b[^>]*?\bhref\s*=\s*([\"'])([^\"']+)\1", re.IGNORECASE)
INLINE_SCRIPT_RX = re.compile(
    r"<script\b(?![^>]*?\bsrc\s*=)[^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
ESM_IMPORT_FROM_RX = re.compile(
    r"(?:^|[;\n])\s*(?:import|export)\s+(?:[^\"';\n]+?\s+from\s+)?([\"'])([^\"']+)\1"
)
ESM_DYNAMIC_IMPORT_RX = re.compile(r"\bimport\s*\(\s*([\"'])([^\"']+)\1\s*\)")

NODE_ESM_SMOKE_JS = r"""
const cfg = JSON.parse(process.env.SMOKE_CONFIG_JSON || "{}");
const HASH_MARK = String.fromCharCode(35);

const xssAttempts = [];
const networkAttempts = [];

globalThis.fetch = async function forbiddenFetch(target) {
  networkAttempts.push("fetch:" + String(target));
  throw new Error("Forbidden network call in headless smoke check");
};
globalThis.WebSocket = function ForbiddenWebSocket(target) {
  networkAttempts.push("ws:" + String(target));
  throw new Error("Forbidden WebSocket in headless smoke check");
};
globalThis.XMLHttpRequest = function ForbiddenXHR() {
  networkAttempts.push("xhr");
  throw new Error("Forbidden XMLHttpRequest in headless smoke check");
};

function makeStorage() {
  const map = new Map();
  return {
    get length() { return map.size; },
    key(i) { return Array.from(map.keys())[i] ?? null; },
    getItem(k) { return map.has(String(k)) ? map.get(String(k)) : null; },
    setItem(k, v) { map.set(String(k), String(v)); },
    removeItem(k) { map.delete(String(k)); },
    clear() { map.clear(); }
  };
}

function makeCanvas2dContext() {
  let fillRectCalls = 0;
  let drawCalls = 0;
  return {
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    font: "10px monospace",
    textAlign: "left",
    textBaseline: "top",
    globalAlpha: 1,
    imageSmoothingEnabled: false,
    get _fillRectCalls() { return fillRectCalls; },
    get _drawCalls() { return drawCalls; },
    fillRect() { fillRectCalls += 1; drawCalls += 1; },
    strokeRect() { drawCalls += 1; },
    clearRect() { drawCalls += 1; },
    beginPath() {},
    closePath() {},
    moveTo() {},
    lineTo() {},
    arc() { drawCalls += 1; },
    rect() {},
    quadraticCurveTo() {},
    bezierCurveTo() {},
    fill() { drawCalls += 1; },
    stroke() { drawCalls += 1; },
    clip() {},
    save() {},
    restore() {},
    scale() {},
    translate() {},
    rotate() {},
    setTransform() {},
    resetTransform() {},
    setLineDash() {},
    getLineDash() { return []; },
    fillText() { drawCalls += 1; },
    strokeText() { drawCalls += 1; },
    measureText(txt) { return { width: String(txt || "").length * 6 }; },
    drawImage() { drawCalls += 1; },
    putImageData() { drawCalls += 1; },
    getImageData(_x, _y, w, h) {
      const cw = Math.max(1, Number(w) || 1);
      const ch = Math.max(1, Number(h) || 1);
      return { width: cw, height: ch, data: new Uint8ClampedArray(cw * ch * 4) };
    },
    createImageData(w, h) {
      const cw = Math.max(1, Number(w) || 1);
      const ch = Math.max(1, Number(h) || 1);
      return { width: cw, height: ch, data: new Uint8ClampedArray(cw * ch * 4) };
    },
    createLinearGradient() { return { addColorStop() {} }; },
    createRadialGradient() { return { addColorStop() {} }; }
  };
}

class SmokeBaseNode {}

class SmokeTextNode extends SmokeBaseNode {
  constructor(text, ownerDoc) {
    super();
    this.nodeType = 3;
    this.data = String(text);
    this.nodeValue = this.data;
    this.ownerDocument = ownerDoc || null;
    this.parentNode = null;
  }
  get textContent() { return this.data; }
  set textContent(v) {
    this.data = String(v ?? "");
    this.nodeValue = this.data;
  }
}

function matchesSimpleSelector(el, sel) {
  if (!el || el.nodeType !== 1 || !sel) return false;
  const trimmed = String(sel).trim();
  if (!trimmed) return false;
  if (trimmed.startsWith(HASH_MARK)) {
    return el.id === trimmed.slice(1);
  }
  if (trimmed.startsWith(".")) {
    const targetCls = trimmed.slice(1);
    const tokens = String(el.className || "").split(new RegExp("\\s+")).filter(Boolean);
    return tokens.includes(targetCls);
  }
  if (trimmed.startsWith("[") && trimmed.endsWith("]")) {
    const body = trimmed.slice(1, -1).trim();
    const eqIdx = body.indexOf("=");
    if (eqIdx < 0) return el.hasAttribute(body);
    const attrName = body.slice(0, eqIdx).trim();
    let rawVal = body.slice(eqIdx + 1).trim();
    if (
      (rawVal.startsWith('"') && rawVal.endsWith('"')) ||
      (rawVal.startsWith("'") && rawVal.endsWith("'"))
    ) {
      rawVal = rawVal.slice(1, -1);
    }
    return el.getAttribute(attrName) === rawVal;
  }
  return el.tagName === trimmed.toUpperCase();
}

class SmokeElement extends SmokeBaseNode {
  constructor(tag, ownerDoc) {
    super();
    this.nodeType = 1;
    this.tagName = String(tag || "div").toUpperCase();
    this.ownerDocument = ownerDoc || null;
    this.parentNode = null;
    this.id = "";
    this.className = "";
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.selected = false;
    this.open = false;
    this.value = "";
    this.width = 0;
    this.height = 0;
    this.attrs = {};
    this.dataset = {};
    this.listeners = {};
    this.childNodes = [];
    this._ctx2d = null;
    const self = this;
    this.style = {
      cssText: "",
      setProperty(k, v) { this[k] = String(v); },
      removeProperty(k) { delete this[k]; },
      getPropertyValue(k) { return this[k] || ""; }
    };
    this.classList = {
      _tokens() {
        return String(self.className || "").split(new RegExp("\\s+")).filter(Boolean);
      },
      _sync(list) {
        self.className = list.join(" ");
        self.attrs.class = self.className;
      },
      add(...clsList) {
        const cur = new Set(this._tokens());
        for (const c of clsList) { if (c) cur.add(String(c)); }
        this._sync(Array.from(cur));
      },
      remove(...clsList) {
        const drop = new Set(clsList.map(String));
        this._sync(this._tokens().filter((c) => !drop.has(c)));
      },
      toggle(cls, force) {
        const key = String(cls);
        const cur = new Set(this._tokens());
        const shouldHave = force !== undefined ? Boolean(force) : !cur.has(key);
        if (shouldHave) cur.add(key); else cur.delete(key);
        this._sync(Array.from(cur));
        return shouldHave;
      },
      contains(cls) {
        return this._tokens().includes(String(cls));
      }
    };
  }
  get children() {
    return this.childNodes.filter((c) => c && c.nodeType === 1);
  }
  get firstChild() {
    return this.childNodes.length ? this.childNodes[0] : null;
  }
  get lastChild() {
    return this.childNodes.length ? this.childNodes[this.childNodes.length - 1] : null;
  }
  setAttribute(k, v) {
    const key = String(k);
    const val = String(v);
    this.attrs[key] = val;
    if (key === "id") this.id = val;
    if (key === "class") this.className = val;
    if (key === "hidden") this.hidden = true;
    if (key === "disabled") this.disabled = true;
    if (key === "value") this.value = val;
    if (key === "width") this.width = Number(val) || 0;
    if (key === "height") this.height = Number(val) || 0;
  }
  getAttribute(k) {
    const key = String(k);
    return Object.prototype.hasOwnProperty.call(this.attrs, key) ? this.attrs[key] : null;
  }
  hasAttribute(k) {
    return Object.prototype.hasOwnProperty.call(this.attrs, String(k));
  }
  removeAttribute(k) {
    const key = String(k);
    delete this.attrs[key];
    if (key === "id") this.id = "";
    if (key === "class") this.className = "";
    if (key === "hidden") this.hidden = false;
    if (key === "disabled") this.disabled = false;
  }
  addEventListener(ev, fn) {
    const key = String(ev);
    if (!this.listeners[key]) this.listeners[key] = [];
    this.listeners[key].push(fn);
  }
  removeEventListener(ev, fn) {
    const key = String(ev);
    if (!this.listeners[key]) return;
    this.listeners[key] = this.listeners[key].filter((f) => f !== fn);
  }
  dispatchEvent(evObj) {
    const key = String(evObj && evObj.type ? evObj.type : "");
    const fns = this.listeners[key] || [];
    for (const fn of fns.slice()) {
      fn.call(this, evObj);
    }
    return true;
  }
  click() {
    if (this.disabled) return false;
    let prevented = false;
    this.dispatchEvent({
      type: "click",
      target: this,
      currentTarget: this,
      preventDefault() { prevented = true; },
      stopPropagation() {}
    });
    const btnType = String(this.attrs.type || "submit").toLowerCase();
    if (!prevented && this.tagName === "BUTTON" && btnType === "submit") {
      let cur = this.parentNode;
      while (cur) {
        if (cur.nodeType === 1 && cur.tagName === "FORM") {
          cur.dispatchEvent({
            type: "submit",
            target: cur,
            currentTarget: cur,
            preventDefault() {},
            stopPropagation() {}
          });
          break;
        }
        cur = cur.parentNode;
      }
    }
    return true;
  }
  appendChild(child) {
    if (!child) return child;
    if (child.nodeType === 11 && Array.isArray(child.childNodes)) {
      for (const grand of child.childNodes.slice()) {
        this.appendChild(grand);
      }
      child.childNodes.length = 0;
      return child;
    }
    if (child.parentNode && typeof child.parentNode.removeChild === "function") {
      child.parentNode.removeChild(child);
    }
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  append(...items) {
    for (const item of items) {
      if (item === null || item === undefined) continue;
      if (typeof item === "object" && item.nodeType) {
        this.appendChild(item);
      } else {
        this.appendChild(new SmokeTextNode(String(item), this.ownerDocument));
      }
    }
  }
  removeChild(child) {
    const idx = this.childNodes.indexOf(child);
    if (idx >= 0) {
      this.childNodes.splice(idx, 1);
      child.parentNode = null;
    }
    return child;
  }
  remove() {
    if (this.parentNode) this.parentNode.removeChild(this);
  }
  replaceChildren(...items) {
    for (const old of this.childNodes) {
      if (old) old.parentNode = null;
    }
    this.childNodes.length = 0;
    this.append(...items);
  }
  get textContent() {
    return this.childNodes.map((c) => c ? (c.textContent || "") : "").join("");
  }
  set textContent(v) {
    this.replaceChildren();
    if (v !== "" && v !== null && v !== undefined) {
      this.appendChild(new SmokeTextNode(String(v), this.ownerDocument));
    }
  }
  getContext() {
    if (!this._ctx2d) {
      this._ctx2d = makeCanvas2dContext();
    }
    return this._ctx2d;
  }
  getBoundingClientRect() {
    return { x: 0, y: 0, top: 0, left: 0, right: 640, bottom: 384, width: 640, height: 384 };
  }
  showModal() { this.open = true; this.hidden = false; }
  close() { this.open = false; this.hidden = true; }
  focus() {}
  blur() {}
  insertAdjacentHTML() {
    xssAttempts.push("insertAdjacentHTML");
    throw new Error("Forbidden XSS sink: insertAdjacentHTML");
  }
  querySelector(sel) {
    for (const child of this.childNodes) {
      if (child && child.nodeType === 1) {
        if (matchesSimpleSelector(child, sel)) return child;
        const sub = child.querySelector(sel);
        if (sub) return sub;
      }
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    for (const child of this.childNodes) {
      if (child && child.nodeType === 1) {
        if (matchesSimpleSelector(child, sel)) out.push(child);
        out.push(...child.querySelectorAll(sel));
      }
    }
    return out;
  }
}

Object.defineProperty(SmokeElement.prototype, "innerHTML", {
  get() { return ""; },
  set() {
    xssAttempts.push("innerHTML");
    throw new Error("Forbidden XSS sink: innerHTML");
  }
});

Object.defineProperty(SmokeElement.prototype, "outerHTML", {
  get() { return ""; },
  set() {
    xssAttempts.push("outerHTML");
    throw new Error("Forbidden XSS sink: outerHTML");
  }
});

function createSmokeDocument() {
  const doc = {
    body: null,
    head: null,
    documentElement: null,
    createElement(tag) {
      return new SmokeElement(tag, doc);
    },
    createElementNS(_ns, tag) {
      return new SmokeElement(tag, doc);
    },
    createTextNode(text) {
      return new SmokeTextNode(text, doc);
    },
    createDocumentFragment() {
      return {
        nodeType: 11,
        ownerDocument: doc,
        childNodes: [],
        appendChild(c) { this.childNodes.push(c); return c; }
      };
    },
    getElementById(id) {
      return doc.body ? doc.body.querySelector(HASH_MARK + String(id)) : null;
    },
    querySelector(sel) {
      return doc.body ? doc.body.querySelector(sel) : null;
    },
    querySelectorAll(sel) {
      return doc.body ? doc.body.querySelectorAll(sel) : [];
    },
    write() {
      xssAttempts.push("document.write");
      throw new Error("Forbidden XSS sink: document.write");
    },
    writeln() {
      xssAttempts.push("document.writeln");
      throw new Error("Forbidden XSS sink: document.writeln");
    }
  };
  doc.documentElement = new SmokeElement("html", doc);
  doc.head = new SmokeElement("head", doc);
  doc.body = new SmokeElement("body", doc);
  doc.documentElement.appendChild(doc.head);
  doc.documentElement.appendChild(doc.body);
  return doc;
}

function findById(node, targetId) {
  if (!node) return null;
  if (node.id === targetId || (node.attrs && node.attrs.id === targetId)) return node;
  for (const child of node.childNodes || []) {
    const hit = findById(child, targetId);
    if (hit) return hit;
  }
  return null;
}

function findButtonsByText(node, textSnippet) {
  const hits = [];
  if (!node || node.nodeType !== 1) return hits;
  if (node.tagName === "BUTTON" && node.textContent.includes(textSnippet)) {
    hits.push(node);
  }
  for (const child of node.childNodes || []) {
    if (child && child.nodeType === 1) {
      hits.push(...findButtonsByText(child, textSnippet));
    }
  }
  return hits;
}

function setInputValue(inputEl, nextVal) {
  inputEl.value = String(nextVal);
  inputEl.attrs.value = String(nextVal);
  inputEl.dispatchEvent({
    type: "input",
    target: inputEl,
    currentTarget: inputEl,
    preventDefault() {},
    stopPropagation() {}
  });
}

function serializeDomSurface(node, chunks = []) {
  if (!node) return chunks;
  if (node.nodeType === 3) {
    chunks.push(String(node.data || ""));
    return chunks;
  }
  if (node.nodeType === 1) {
    if (node.value) chunks.push(String(node.value));
    for (const [ak, av] of Object.entries(node.attrs || {})) {
      chunks.push(String(ak) + "=" + String(av));
    }
    for (const [dk, dv] of Object.entries(node.dataset || {})) {
      chunks.push("data:" + String(dk) + "=" + String(dv));
    }
    for (const child of node.childNodes || []) {
      serializeDomSurface(child, chunks);
    }
  }
  return chunks;
}

const bootDoc = createSmokeDocument();
globalThis.Node = SmokeBaseNode;
globalThis.Element = SmokeElement;
globalThis.HTMLElement = SmokeElement;
globalThis.document = bootDoc;
globalThis.window = globalThis;
globalThis.localStorage = makeStorage();
globalThis.sessionStorage = makeStorage();
globalThis.requestAnimationFrame = () => 1;
globalThis.cancelAnimationFrame = () => {};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
if (!globalThis.navigator) {
  globalThis.navigator = { clipboard: { writeText: async () => {} } };
}

const bootErrors = [];
const modeErrors = [];
const importedNames = [];
const modesExercised = [];

for (const item of cfg.ui_files || []) {
  try {
    const mod = await import(item.uri);
    if (!mod || typeof mod !== "object" || Object.keys(mod).length === 0) {
      bootErrors.push(item.name + ": exported 0 ESM symbols");
    } else {
      importedNames.push(item.name);
    }
  } catch (err) {
    bootErrors.push(item.name + ": ESM import failed (" + String(err && err.message ? err.message : err) + ")");
  }
}

let domMod = null;
let indexMod = null;
let stageMod = null;
let duelPanelMod = null;

try {
  domMod = await import(cfg.dom_uri);
} catch (err) {
  bootErrors.push("dom.js import error: " + String(err && err.message ? err.message : err));
}

if (cfg.index_uri) {
  try {
    indexMod = await import(cfg.index_uri);
  } catch (err) {
    bootErrors.push("index.js import error: " + String(err && err.message ? err.message : err));
  }
} else {
  bootErrors.push("missing docs/arena/ui/index.js");
}

if (cfg.office_stage_uri) {
  try {
    stageMod = await import(cfg.office_stage_uri);
  } catch (err) {
    bootErrors.push("office_stage.js import error: " + String(err && err.message ? err.message : err));
  }
} else {
  bootErrors.push("missing docs/arena/ui/office_stage.js");
}

if (cfg.ai_duel_panel_uri) {
  try {
    duelPanelMod = await import(cfg.ai_duel_panel_uri);
  } catch (err) {
    bootErrors.push("ai_duel_panel.js import error: " + String(err && err.message ? err.message : err));
  }
} else {
  bootErrors.push("missing docs/arena/ui/ai_duel_panel.js");
}

if (domMod) {
  for (const fnName of ["el", "clear", "pad2", "fmtScore"]) {
    if (typeof domMod[fnName] !== "function") {
      bootErrors.push("dom.js missing exported function " + fnName);
    }
  }
  if (!Array.isArray(domMod.MODE_DEFS)) {
    bootErrors.push("dom.js missing exported MODE_DEFS array");
  } else {
    const gotIds = domMod.MODE_DEFS.map((m) => m && m.id);
    const expIds = ["duel", "solver", "mole", "living"];
    if (JSON.stringify(gotIds) !== JSON.stringify(expIds)) {
      bootErrors.push("MODE_DEFS ids mismatch: " + JSON.stringify(gotIds));
    }
    for (const modeId of expIds) {
      if (!domMod.MODE_DEFS[modeId] || domMod.MODE_DEFS[modeId].id !== modeId) {
        bootErrors.push("MODE_DEFS missing non-enumerable lookup for " + modeId);
      }
    }
  }

  const expTools = [
    "status", "list_employees", "list_documents", "read_access_logs",
    "search_messages", "read_message", "interview", "plant_canary",
    "check_leak_feed", "restrict_access", "unrestrict_access", "advance_day", "accuse"
  ];
  if (!domMod.TOOL_DEFS || typeof domMod.TOOL_DEFS !== "object") {
    bootErrors.push("dom.js missing exported TOOL_DEFS object");
  } else {
    const gotTools = Object.keys(domMod.TOOL_DEFS);
    if (JSON.stringify(gotTools) !== JSON.stringify(expTools)) {
      bootErrors.push("TOOL_DEFS keys mismatch: " + JSON.stringify(gotTools));
    }
    for (const tName of gotTools) {
      const meta = domMod.TOOL_DEFS[tName];
      if (!meta || typeof meta.code !== "string" || typeof meta.name !== "string" || typeof meta.group !== "string" || typeof meta.costed !== "boolean" || typeof meta.desc !== "string") {
        bootErrors.push("TOOL_DEFS[" + tName + "] missing required metadata fields");
      }
    }
  }

  if (bootErrors.length === 0) {
    const testDoc = createSmokeDocument();
    let clicked = 0;
    const xssPayload = "<img src=x onerror=alert(1)>";
    const btn = domMod.el(
      "button",
      {
        document: testDoc,
        type: "button",
        class: ["ghost", "active"],
        dataset: { seedId: 26 },
        "aria-selected": true,
        style: "width: 48px",
        disabled: false,
        hidden: false,
        onClick: () => { clicked += 1; }
      },
      xssPayload,
      domMod.el("span", { document: testDoc }, "safe")
    );
    btn.click();
    if (clicked !== 1) bootErrors.push("dom.el onClick listener did not fire");
    if (!btn.childNodes[0] || btn.childNodes[0].nodeType !== 3 || btn.childNodes[0].textContent !== xssPayload) {
      bootErrors.push("dom.el did not neutralize HTML string child as text node");
    }
    if (btn.getAttribute("data-seed-id") !== "26") bootErrors.push("dom.el dataset attribute mismatch");
    if (btn.getAttribute("aria-selected") !== "true") bootErrors.push("dom.el aria-selected mismatch");
    domMod.clear(btn);
    if (btn.childNodes.length !== 0) bootErrors.push("dom.clear failed to empty childNodes");
    if (domMod.pad2(0) !== "00" || domMod.pad2(6) !== "06" || domMod.pad2(14) !== "14" || domMod.pad2(-4) !== "-04" || domMod.pad2(NaN) !== "00") {
      bootErrors.push("dom.pad2 formatting mismatch");
    }
    if (domMod.fmtScore(0.79) !== "+0.79" || domMod.fmtScore(-1) !== "-1.00" || domMod.fmtScore(0) !== "0.00" || domMod.fmtScore(-0.001) !== "0.00" || domMod.fmtScore(NaN) !== "0.00") {
      bootErrors.push("dom.fmtScore formatting mismatch");
    }
  }
}

if (indexMod) {
  for (const sym of ["mountArenaUI", "OfficeStage", "el", "MODE_DEFS", "TOOL_DEFS", "DEFAULT_DUEL_SEEDS", "sanitizeStepForPreEnd", "scrubPreEndObject", "buildCanonicalShareLine"]) {
    if (indexMod[sym] === undefined) {
      bootErrors.push("index.js missing expected re-export: " + sym);
    }
  }
  if (domMod && indexMod.el !== domMod.el) {
    bootErrors.push("index.js does not re-export el from dom.js");
  }
  if (stageMod && indexMod.OfficeStage !== stageMod.OfficeStage) {
    bootErrors.push("index.js does not re-export OfficeStage from office_stage.js");
  }
  if (typeof indexMod.sanitizeStepForPreEnd === "function") {
    const cleanedAccuse = indexMod.sanitizeStepForPreEnd({
      day: 1,
      call_idx: 2,
      tool: "accuse",
      args: { employee: "e17" },
      summary: "Accused e17",
      V: 1.0,
      mole: "e29",
      true_v: 0.9137
    });
    const rawAccuseJson = JSON.stringify(cleanedAccuse);
    if (!cleanedAccuse || cleanedAccuse.args !== "[SEALED]" || cleanedAccuse.sealed !== true) {
      modeErrors.push("sanitizeStepForPreEnd failed to seal pre-end accuse step");
    }
    for (const secretTok of ["e17", "e29", "0.9137", "true_v", "mole"]) {
      if (rawAccuseJson.includes(secretTok)) {
        modeErrors.push("sanitizeStepForPreEnd leaked token: " + secretTok);
      }
    }
  }
  if (typeof indexMod.scrubPreEndObject === "function") {
    const scrubbed = indexMod.scrubPreEndObject({
      safe: "visible",
      mole: "e29",
      true_mole: "e29",
      decoy: "e17",
      true_v: 0.9137,
      trueV: 0.9137,
      is_canary: true,
      nested: [{ doc_id: "doc_01", is_canary: true, true_v: 0.9137, moleId: "e29" }]
    });
    const scrubJson = JSON.stringify(scrubbed);
    for (const secretTok of ["e29", "e17", "0.9137", "true_v", "trueV", "is_canary", "mole", "decoy"]) {
      if (scrubJson.includes(secretTok)) {
        modeErrors.push("scrubPreEndObject leaked token: " + secretTok);
      }
    }
  }
}

if (indexMod && typeof indexMod.OfficeStage === "function") {
  try {
    const stageDoc = createSmokeDocument();
    const stageCanvas = stageDoc.createElement("canvas");
    stageCanvas.setAttribute("width", "640");
    stageCanvas.setAttribute("height", "384");
    const stage = new indexMod.OfficeStage(stageCanvas, { mode: "investigator", tier: "hard", seed: 6 });
    stage.applyObservableEvent({
      type: "list_employees",
      employees: [
        { id: "e01", name: "Ada Lovelace", dept: "Engineering", role: "Lead Engineer" },
        { id: "e02", name: "Alan Turing", dept: "Research", role: "Senior Scientist" },
        { id: "e03", name: "Grace Hopper", dept: "Finance", role: "Controller" }
      ]
    });
    stage.applyObservableEvent({
      type: "plant_canary",
      canary_id: "can_01",
      doc_title: "Roadmap",
      assignment: { e01: "A", e02: "B", e03: "C" }
    });
    stage.applyObservableEvent({
      type: "check_leak_feed",
      items: [{ doc_id: "can_01", variant: "C" }]
    });
    stage.step(16.67);
    stage.render();
    const ctx = stageCanvas.getContext("2d");
    if (!ctx || ctx._fillRectCalls < 50) {
      bootErrors.push("OfficeStage.render() issued insufficient 2D canvas draw calls: " + String(ctx && ctx._fillRectCalls));
    }
    let blockedPreEndReveal = false;
    try {
      stage.revealOutcome({ moleId: "e29", accusedId: "e29", correct: true });
    } catch (_) {
      blockedPreEndReveal = true;
    }
    if (!blockedPreEndReveal) {
      bootErrors.push("OfficeStage.revealOutcome failed to block pre-end culprit reveal");
    }
    stage.applyObservableEvent({ type: "episode_over", done: true });
    const revealed = stage.revealOutcome({ moleId: "e29", accusedId: "e29", correct: true });
    if (!revealed || revealed.moleId !== "e29") {
      bootErrors.push("OfficeStage.revealOutcome failed post-end reveal");
    }
  } catch (err) {
    bootErrors.push("OfficeStage boot error: " + String(err && err.message ? err.message : err));
  }
}

if (duelPanelMod && typeof duelPanelMod.createAiDuelPanel === "function") {
  try {
    const pDoc = createSmokeDocument();
    const pContainer = pDoc.createElement("aside");
    pDoc.body.appendChild(pContainer);
    const panel = duelPanelMod.createAiDuelPanel({ document: pDoc, container: pContainer });

    panel.update({
      mode: "duel",
      tier: "hard",
      seed: 26,
      humanDay: 2,
      humanDone: false,
      geminiView: {
        seed: 26,
        tier: "hard",
        steps: [
          { day: 1, call_idx: 1, tool: "list_employees", args: { mole: "e29", true_v: 0.9137 }, summary: "Listed staff", V: 1.0 },
          { day: 2, call_idx: 2, tool: "accuse", args: { employee: "e17" }, summary: "Accused e17", V: 0.94, mole: "e29", true_v: 0.9137 },
          { day: 9, call_idx: 8, tool: "status", args: {}, summary: "PANEL_FUTURE_LEAK", V: 0.72 }
        ],
        sealed_verdict: { accused: "e17", mole: "e29", correct: false, final_day: 2, score: -1.0 }
      },
      solverView: {
        day: 2,
        visible_V: 0.94,
        canaries_planted: 2,
        interviews_done: 1,
        restricted_count: 0,
        tool_calls_so_far: 9,
        top_posterior_prob: 0.38,
        entropy_bits: 2.4,
        accused: "e29",
        mole: "e29",
        true_v: 0.9137,
        final_day: 2
      }
    });
    const duelSurface = serializeDomSurface(pContainer).join("\n") + "\n" + JSON.stringify(panel.getState());
    if (!pContainer.textContent.includes("[SEALED]")) {
      bootErrors.push("ai_duel_panel duel pre-end missing [SEALED] badge");
    }
    for (const secretTok of ["e29", "e17", "0.9137", "PANEL_FUTURE_LEAK"]) {
      if (duelSurface.includes(secretTok)) {
        bootErrors.push("ai_duel_panel duel pre-end leaked token: " + secretTok);
      }
    }

    panel.update({
      mode: "solver",
      tier: "medium",
      seed: 3000,
      humanDay: 3,
      humanDone: false,
      solverView: { day: 3, visible_V: 0.92, canaries_planted: 2, top_posterior_prob: 0.5, entropy_bits: 1.9, mole: "e11", true_v: 0.8811 }
    });
    if (JSON.stringify(panel.getState()).includes("e11") || JSON.stringify(panel.getState()).includes("0.8811")) {
      bootErrors.push("ai_duel_panel solver pre-end leaked truth fields");
    }

    panel.update({
      mode: "mole",
      tier: "hard",
      seed: 6,
      humanDay: 2,
      humanDone: false,
      solverView: { day: 2, visible_V: 0.96, canaries_planted: 1, top_posterior_prob: 0.22, entropy_bits: 3.5, is_canary: true }
    });
    if (JSON.stringify(panel.getState()).includes("is_canary")) {
      bootErrors.push("ai_duel_panel mole pre-end leaked is_canary");
    }

    panel.update({
      mode: "living",
      tier: "hard",
      seed: 26,
      humanDay: 2,
      humanDone: false,
      livingView: {
        banner: "Forged banner without honesty notice",
        mole: "e29",
        decoy: "e17",
        true_v: 0.9137,
        rumours: [
          { day: 1, from: "e01", to: "e02", text: "Coffee machine jammed", bias_type: "availability", mole: "e29", true_v: 0.9137, is_canary: true },
          { day: 7, from: "e02", to: "e03", text: "PANEL_LIVING_FUTURE_RUMOUR" }
        ],
        grudges: [{ a: "e01", b: "e02", reason: "budget", decoy: "e17" }]
      }
    });
    const livingPanelSurface = serializeDomSurface(pContainer).join("\n") + "\n" + JSON.stringify(panel.getState());
    if (!pContainer.textContent.includes("Did NOT pass Gate B")) {
      bootErrors.push("ai_duel_panel living mode failed to enforce mandatory Gate B honesty banner");
    }
    for (const secretTok of ["e29", "e17", "0.9137", "is_canary", "PANEL_LIVING_FUTURE_RUMOUR"]) {
      if (livingPanelSurface.includes(secretTok)) {
        bootErrors.push("ai_duel_panel living mode leaked token: " + secretTok);
      }
    }
  } catch (err) {
    bootErrors.push("ai_duel_panel boot error: " + String(err && err.message ? err.message : err));
  }
}

if (indexMod && typeof indexMod.mountArenaUI === "function") {
  const doc = createSmokeDocument();
  const root = doc.createElement("div");
  doc.body.appendChild(root);
  const sharedStorage = makeStorage();

  let totalGameCalls = 0;
  let lastPlantedCanaryArgs = null;
  const createdSessions = [];

  const createGame = (tier, seed, mode) => {
    createdSessions.push({ tier, seed, mode });
    let epDone = false;
    let epCalls = 0;
    let curDay = 1;
    let curV = 1.0;
    const secretMole = Number(seed) === 6 ? "e19" : "e29";
    const humanFinalDay = Number(seed) === 6 ? 2 : 8;
    const humanFinalScore = Number(seed) === 6 ? 0.89 : 0.74;
    const solverFinalDay = Number(seed) === 6 ? 6 : 7;
    const solverFinalScore = Number(seed) === 6 ? 0.71 : 0.69;
    return {
      spec_json() {
        return JSON.stringify({
          tier,
          seed,
          tiers_version: "v1.4",
          instruction: "Episode lasts at most " + (tier === "medium" ? "14" : "21") + " days. limit of " + (tier === "medium" ? "300" : "420") + " calls. one of your 8 actions per day. Use at most 3 different labels. If you accuse an innocent employee, your score is -1."
        });
      },
      call_json(tool, argsJson) {
        totalGameCalls += 1;
        epCalls += 1;
        const args = JSON.parse(argsJson || "{}");
        if (tool === "list_employees") {
          return JSON.stringify({
            ok: true,
            data: {
              employees: [
                { id: "e01", name: "Ada Lovelace", dept: "Engineering", department: "Engineering", role: "Lead Engineer" },
                { id: "e02", name: "Alan Turing", dept: "Research", department: "Research", role: "Senior Scientist" },
                { id: "e03", name: "Grace Hopper", dept: "Finance", department: "Finance", role: "Controller" }
              ]
            },
            error: "",
            done: false
          });
        }
        if (tool === "plant_canary") {
          lastPlantedCanaryArgs = args;
          return JSON.stringify({
            ok: true,
            data: {
              canary_id: "can_01",
              variants: { A: ["e01"], B: ["e02"], C: ["e03"] }
            },
            error: "",
            done: false
          });
        }
        if (tool === "advance_day") {
          curDay = Number(seed) === 6 ? curDay + 1 : 8;
          curV = Number(seed) === 6 ? 0.89 : 0.74;
          return JSON.stringify({ ok: true, data: { day: curDay, V: curV }, error: "", done: false });
        }
        if (tool === "check_leak_feed") {
          return JSON.stringify({
            ok: true,
            data: { items: [{ doc_id: "can_01", variant: "C", surfaced_day: curDay }] },
            error: "",
            done: false
          });
        }
        if (tool === "accuse") {
          epDone = true;
          return JSON.stringify({ ok: true, data: { accused: args.employee, episode_over: true }, error: "", done: true });
        }
        return JSON.stringify({ ok: true, data: { day: curDay, V: curV }, error: "", done: false });
      },
      reveal_json() {
        if (!epDone) return JSON.stringify({ error: "not over" });
        return JSON.stringify({
          seed,
          tier,
          mole: secretMole,
          you: {
            score: humanFinalScore,
            accused: secretMole,
            correct: true,
            final_day: humanFinalDay,
            tool_calls: epCalls
          },
          solver: {
            score: solverFinalScore,
            accused: secretMole,
            correct: true,
            final_day: solverFinalDay,
            tool_calls: Number(seed) === 6 ? 52 : 60
          }
        });
      }
    };
  };

  const duelPack = {
    version: "v1.4",
    default_seeds: [6, 26],
    episodes: {
      "hard:6": {
        seed: 6,
        tier: "hard",
        agent: "opencode:google/gemini-4-carbon",
        steps: [
          {
            day: 1,
            call_idx: 1,
            tool: "list_employees",
            args: { mole: "e19", true_v: 0.9412, decoy: "e07" },
            ok: true,
            summary: "Listed 40 staff",
            V: 1.0,
            mole: "e19",
            true_v: 0.9412
          },
          {
            day: 1,
            call_idx: 2,
            tool: "accuse",
            args: { employee: "e19" },
            ok: true,
            summary: "Accused e19",
            V: 1.0,
            mole: "e19",
            true_v: 0.9412
          },
          {
            day: 6,
            call_idx: 57,
            tool: "status",
            args: {},
            ok: true,
            summary: "FUTURE_SEED6_STEP_LEAK",
            V: 0.73,
            mole: "e19",
            true_v: 0.9412
          }
        ],
        sealed_verdict: {
          score: 0.73,
          accused: "e19",
          mole: "e19",
          mole_name: "Victor SecretSix",
          correct: true,
          final_day: 6,
          tool_calls: 57
        }
      },
      "hard:26": {
        seed: 26,
        tier: "hard",
        agent: "opencode:google/gemini-4-carbon",
        steps: [
          {
            day: 1,
            call_idx: 1,
            tool: "list_employees",
            args: { mole: "e29", true_v: 0.9137, decoy: "e17" },
            ok: true,
            summary: "Listed 40 staff",
            V: 1.0,
            mole: "e29",
            true_v: 0.9137
          },
          {
            day: 1,
            call_idx: 2,
            tool: "accuse",
            args: { employee: "e17" },
            ok: true,
            summary: "Accused e17",
            V: 1.0,
            mole: "e29",
            true_v: 0.9137
          },
          {
            day: 10,
            call_idx: 91,
            tool: "status",
            args: {},
            ok: true,
            summary: "FUTURE_SEED26_STEP_LEAK",
            V: 0.70,
            mole: "e29",
            true_v: 0.9137
          }
        ],
        sealed_verdict: {
          score: -1.0,
          accused: "e17",
          mole: "e29",
          mole_name: "Nora SecretMole",
          correct: false,
          final_day: 10,
          tool_calls: 91
        }
      }
    },
    unlockPostGameReveal(tier, seed, humanDone) {
      if (!humanDone) return null;
      const ep = this.episodes[String(tier) + ":" + String(seed)];
      return ep ? ep.sealed_verdict : null;
    }
  };

  const solverLive = {
    getSolverDayState(_tier, seed, humanDay, humanDone) {
      const targetMole = Number(seed) === 6 ? "e19" : "e29";
      if (!humanDone) {
        return {
          day: humanDay,
          visible_V: 0.88,
          canaries_planted: 2,
          interviews_done: 1,
          restricted_count: 0,
          tool_calls_so_far: 12,
          top_posterior_prob: 0.42,
          entropy_bits: 2.1,
          accused: targetMole,
          mole: targetMole,
          true_v: 0.8841,
          final_day: 1
        };
      }
      return {
        accused: targetMole,
        correct: true,
        final_day: Number(seed) === 6 ? 6 : 7,
        tool_calls: Number(seed) === 6 ? 52 : 60,
        score: Number(seed) === 6 ? 0.71 : 0.69
      };
    }
  };

  const moleStepCalls = [];
  const moleMode = {
    startSession({ tier, seed }) {
      let moleDay = 1;
      let moleV = 1.0;
      let leaksLanded = 0;
      let daysSurvived = 0;
      return {
        getPublicState() {
          return {
            mode: "mole",
            tier,
            seed,
            day: moleDay,
            nDays: tier === "medium" ? 14 : 21,
            visibleV: moleV,
            done: false,
            moleEmployee: { id: "e12", name: "Sam Cover", dept: "Research" },
            moleCandidateDocs: [
              {
                doc_id: "doc_01",
                title: "Pricing Memo",
                day: moleDay,
                recipient_count: 14,
                is_canary: true,
                true_v: 0.9137,
                mole: "e12"
              },
              {
                doc_id: "doc_02",
                title: "Ops Roster",
                day: moleDay,
                recipient_count: 20,
                is_canary: false,
                true_v: 0.9137
              }
            ],
            solverTelemetry: {
              day: moleDay,
              visible_V: moleV,
              canaries_planted: moleDay,
              top_posterior_prob: Math.min(0.85, 0.14 * moleDay),
              entropy_bits: Math.max(1.2, 4.1 - 0.5 * moleDay),
              is_canary: true,
              true_v: 0.9137,
              mole: "e12"
            },
            leaksLanded,
            daysSurvived,
            is_canary: true,
            true_v: 0.9137
          };
        },
        stepDay(act) {
          const docId = act && act.leakDocId ? String(act.leakDocId) : null;
          moleStepCalls.push(docId);
          moleDay += 1;
          daysSurvived += 1;
          if (docId) {
            leaksLanded += 1;
            moleV = Math.max(0, Number((moleV - 0.05).toFixed(2)));
          }
          return { day: moleDay, leaked: docId };
        }
      };
    }
  };

  const livingOffice = {
    getBanner() {
      return "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift";
    },
    getAvailableSeeds() { return [6, 26]; },
    getDayState(_seed, humanDay) {
      return {
        day: humanDay,
        mole: "e29",
        true_mole: "e29",
        mole_id: "e29",
        moleId: "e29",
        decoy: "e17",
        correct: false,
        true_v: 0.9137,
        trueV: 0.9137,
        is_canary: true,
        leaking_sprite_employee: "e29",
        rumours: [
          {
            day: 1,
            from: "e01",
            to: "e02",
            text: "Printer queue spike near Finance",
            bias_type: "availability",
            mole: "e29",
            decoy: "e17",
            true_v: 0.9137,
            is_canary: true
          },
          {
            day: 9,
            from: "e02",
            to: "e01",
            text: "FUTURE_DAY9_RUMOUR_LEAK",
            bias_type: "halo"
          }
        ],
        grudges: [{ a: "e01", b: "e02", reason: "budget review", mole: "e29", decoy: "e17" }],
        chat_feed: [{ day: 1, from: "e03", to: "office", text: "Audit prep reminder", true_v: 0.9137 }]
      };
    }
  };

  const commonForbiddenPreEndTokens = [
    "true_v",
    "trueV",
    "is_canary",
    "0.9412",
    "0.9137",
    "0.8841",
    "FUTURE_SEED6_STEP_LEAK",
    "FUTURE_SEED26_STEP_LEAK",
    "FUTURE_DAY9_RUMOUR_LEAK"
  ];
  const seed6SecretTokens = [
    "e19",
    "Victor SecretSix",
    "e07",
    "Accused e19",
    ...commonForbiddenPreEndTokens
  ];
  const seed26SecretTokens = [
    "e29",
    "Nora SecretMole",
    "e17",
    "Accused e17",
    ...commonForbiddenPreEndTokens
  ];

  const assertZeroPreEndLeaks = (phaseLabel, appInstance, tokenList = seed26SecretTokens) => {
    const surface = serializeDomSurface(root).join("\n") + "\n" + JSON.stringify(appInstance.getState());
    for (const tok of tokenList) {
      if (surface.includes(tok)) {
        modeErrors.push(phaseLabel + ": pre-end leak of token '" + tok + "'");
      }
    }
    if (appInstance.getState().leakingSpriteEmployee !== null) {
      modeErrors.push(phaseLabel + ": leakingSpriteEmployee exposed pre-end");
    }
  };

  const armAndSubmitAccuseDom = (targetEmpId, phaseLabel) => {
    const accuseTabBtn = root.querySelector('[data-tool="accuse"]');
    if (!accuseTabBtn) {
      modeErrors.push(phaseLabel + ": missing accuse tool button");
      return;
    }
    accuseTabBtn.click();

    let formInputs = root.querySelectorAll("input");
    if (formInputs.length < 2) {
      modeErrors.push(phaseLabel + ": expected Employee ID and Type ID to Arm inputs");
      return;
    }
    setInputValue(formInputs[0], targetEmpId);

    let submitBtn = root.querySelector('[data-run-tool="accuse"]');
    if (!submitBtn || submitBtn.disabled !== true) {
      modeErrors.push(phaseLabel + ": accuse submit button must remain disabled until Type ID to Arm matches");
      return;
    }
    submitBtn.click();
    if (app.getState().done) {
      modeErrors.push(phaseLabel + ": disabled un-armed accuse button unexpectedly ended episode");
      return;
    }

    formInputs = root.querySelectorAll("input");
    setInputValue(formInputs[1], targetEmpId);

    submitBtn = root.querySelector('[data-run-tool="accuse"]');
    if (!submitBtn || submitBtn.disabled !== false) {
      modeErrors.push(phaseLabel + ": accuse submit button did not arm after matching ID entry");
      return;
    }
    submitBtn.click();
  };

  const app = indexMod.mountArenaUI(root, {
    document: doc,
    storage: sharedStorage,
    createGame,
    duelPack,
    solverLive,
    moleMode,
    livingOffice
  });

  if (app.getState().mode !== "duel") {
    modeErrors.push("initial mode expected 'duel', got '" + String(app.getState().mode) + "'");
  }
  if (app.getState().seed !== 6) {
    modeErrors.push("initial duel seed expected 6, got " + String(app.getState().seed));
  }
  const livingTab = root.querySelector('[data-mode="living"]');
  if (!livingTab || livingTab.getAttribute("aria-selected") !== "false" || root.querySelector(".social-drawer")) {
    modeErrors.push("Living Office must be off by default on initial mount");
  }
  if (totalGameCalls !== 0 || app.getState().calls !== 0) {
    modeErrors.push("expected 0 background tool calls on mount, got " + String(totalGameCalls));
  }
  const officeCanvas = findById(root, "officeCanvas");
  if (!officeCanvas || !officeCanvas.getContext("2d") || officeCanvas.getContext("2d")._fillRectCalls < 20) {
    modeErrors.push("mounted officeCanvas did not receive 2D stage draw calls");
  }
  if (!findById(root, "assetCredits")) {
    modeErrors.push("missing assetCredits in mounted DOM");
  }
  if (!root.textContent.includes("[SEALED]")) {
    modeErrors.push("duel Seed 6 pre-end DOM missing [SEALED] lock");
  }
  assertZeroPreEndLeaks("duel-seed6-mount", app, [...seed6SecretTokens, ...seed26SecretTokens]);

  const runEmpBtn = root.querySelector('[data-run-tool="list_employees"]');
  if (!runEmpBtn) {
    modeErrors.push("missing Run EMP submit button");
  } else {
    runEmpBtn.click();
  }
  if (root.querySelectorAll(".staff-row").length !== 3) {
    modeErrors.push("list_employees did not render 3 staff rows");
  }

  const canaryToolBtn = root.querySelector('[data-tool="plant_canary"]');
  if (!canaryToolBtn) {
    modeErrors.push("missing plant_canary tool button");
  } else {
    canaryToolBtn.click();
  }
  let staffRows = root.querySelectorAll(".staff-row");
  if (staffRows.length === 3) {
    const row0Btns = staffRows[0].querySelectorAll(".variant-btn");
    if (row0Btns.length !== 3) {
      modeErrors.push("expected 3 A/B/C variant buttons on staff row");
    } else {
      row0Btns[0].click();
    }
    staffRows = root.querySelectorAll(".staff-row");
    staffRows[1].querySelectorAll(".variant-btn")[1].click();
    staffRows = root.querySelectorAll(".staff-row");
    staffRows[2].querySelectorAll(".variant-btn")[2].click();
    staffRows = root.querySelectorAll(".staff-row");
    staffRows[2].querySelectorAll(".variant-btn")[2].click();
    staffRows = root.querySelectorAll(".staff-row");
    staffRows[2].querySelectorAll(".variant-btn")[2].click();
  }
  const canaryPill = root.querySelector(".canary-pill");
  if (!canaryPill || canaryPill.textContent !== "Assigned: e01:A, e02:B, e03:C") {
    modeErrors.push("plant_canary A/B/C toggle pill mismatch: " + String(canaryPill && canaryPill.textContent));
  }
  const runCanaryBtn = root.querySelector('[data-run-tool="plant_canary"]');
  if (!runCanaryBtn) {
    modeErrors.push("missing Run CAN submit button");
  } else {
    runCanaryBtn.click();
  }
  if (!lastPlantedCanaryArgs || JSON.stringify(lastPlantedCanaryArgs.assignment) !== JSON.stringify({ e01: "A", e02: "B", e03: "C" })) {
    modeErrors.push("plant_canary submission did not forward {e01:'A', e02:'B', e03:'C'}");
  }

  const advBtn = root.querySelector('[data-tool="advance_day"]');
  if (advBtn) advBtn.click();
  const runAdvBtn = root.querySelector('[data-run-tool="advance_day"]');
  if (runAdvBtn) runAdvBtn.click();
  if (app.getState().day !== 2 || app.getState().done !== false) {
    modeErrors.push("duel Seed 6 advance_day did not advance to Day 2");
  }

  const feedBtn = root.querySelector('[data-tool="check_leak_feed"]');
  if (feedBtn) feedBtn.click();
  const runFeedBtn = root.querySelector('[data-run-tool="check_leak_feed"]');
  if (runFeedBtn) runFeedBtn.click();
  if (!root.textContent.includes("Canary Variant [C]")) {
    modeErrors.push("check_leak_feed did not render surfaced Canary Variant [C]");
  }

  const agentBtn = findById(root, "agentBtn");
  if (!agentBtn) {
    modeErrors.push("missing agentBtn");
  } else {
    agentBtn.click();
    if (!app.getState().agentRaw || agentBtn.getAttribute("aria-pressed") !== "true" || !doc.body.classList.contains("agent-raw")) {
      modeErrors.push("Agent JSON toggle on failed");
    }
    agentBtn.click();
    if (app.getState().agentRaw || agentBtn.getAttribute("aria-pressed") !== "false" || doc.body.classList.contains("agent-raw")) {
      modeErrors.push("Agent JSON toggle off failed");
    }
  }

  const rulesBtn = findById(root, "rulesBtn");
  const rulesDlg = findById(root, "arenaRulesDlg");
  if (!rulesBtn || !rulesDlg || rulesDlg.hidden !== true) {
    modeErrors.push("Rules button/dialog missing or not initially hidden");
  } else {
    rulesBtn.click();
    if (rulesDlg.hidden !== false || !rulesDlg.textContent.includes("Episode lasts at most 21 days")) {
      modeErrors.push("Rules dialog failed to open with benchmark instructions");
    }
    const closeRulesBtns = findButtonsByText(rulesDlg, "Close");
    if (!closeRulesBtns.length) {
      modeErrors.push("Rules dialog missing Close button");
    } else {
      closeRulesBtns[0].click();
    }
    if (rulesDlg.hidden !== true) {
      modeErrors.push("Rules dialog failed to close");
    }
  }

  const lbBtn = findById(root, "leaderboardBtn");
  const lbDlg = root.querySelector(".leaderboard-dlg");
  if (!lbBtn || !lbDlg || lbDlg.hidden !== true) {
    modeErrors.push("Leaderboard button/dialog missing or not initially hidden");
  } else {
    lbBtn.click();
    if (lbDlg.hidden !== false || !lbDlg.textContent.includes("Local Session Leaderboard")) {
      modeErrors.push("Leaderboard dialog failed to open");
    }
    const closeLbBtns = findButtonsByText(lbDlg, "Close");
    if (!closeLbBtns.length) {
      modeErrors.push("Leaderboard dialog missing Close button");
    } else {
      closeLbBtns[0].click();
    }
    if (lbDlg.hidden !== true) {
      modeErrors.push("Leaderboard dialog failed to close");
    }
  }

  if (!root.textContent.includes("[SEALED]")) {
    modeErrors.push("duel Seed 6 pre-end lost [SEALED] lock");
  }
  assertZeroPreEndLeaks("duel-seed6-pre-accuse", app, [...seed6SecretTokens, ...seed26SecretTokens]);

  armAndSubmitAccuseDom("e19", "duel-seed6-accuse");
  if (!app.getState().done || app.getState().leakingSpriteEmployee !== "e19") {
    modeErrors.push("duel Seed 6 accuse did not finish and reveal e19");
  }
  const shareSeed6 = findById(root, "arenaShareText");
  const expectedShare6 = "CANARY ARENA | Seed 6 (hard) | You +0.89 (Day 2) vs Gemini +0.73 (Day 6) vs Solver +0.71 (Day 6) | First catch: You";
  if (!shareSeed6 || shareSeed6.textContent !== expectedShare6) {
    modeErrors.push("Seed 6 arenaShareText mismatch: " + String(shareSeed6 && shareSeed6.textContent));
  }
  const h2hSeed6 = root.querySelector(".h2h-table");
  if (!h2hSeed6 || h2hSeed6.querySelectorAll("tr").length < 4) {
    modeErrors.push("Seed 6 head-to-head table missing contender rows");
  }

  const playSeed26Btns = findButtonsByText(root, "Play Dramatic Seed 26");
  if (!playSeed26Btns.length) {
    modeErrors.push("missing Play Dramatic Seed 26 button after Seed 6 completion");
    app.loadSeed(26, "hard");
  } else {
    playSeed26Btns[0].click();
  }

  if (app.getState().seed !== 26 || app.getState().done !== false || app.getState().calls !== 0) {
    modeErrors.push("Seed 26 duel load did not reset episode state cleanly");
  }
  if (!root.textContent.includes("[SEALED]")) {
    modeErrors.push("duel Seed 26 pre-end DOM missing [SEALED] lock");
  }
  assertZeroPreEndLeaks("duel-seed26-day1", app);

  app.runHumanTool("list_employees", {});
  app.runHumanTool("advance_day", {});
  if (app.getState().day !== 8 || app.getState().done !== false) {
    modeErrors.push("duel Seed 26 advance_day did not reach Day 8");
  }
  assertZeroPreEndLeaks("duel-seed26-day8", app);

  armAndSubmitAccuseDom("e29", "duel-seed26-accuse");
  if (!app.getState().done || app.getState().leakingSpriteEmployee !== "e29") {
    modeErrors.push("duel Seed 26 accuse did not finish and reveal e29");
  }
  const shareSeed26 = findById(root, "arenaShareText");
  const expectedShare26 = "CANARY ARENA | Seed 26 (hard) | You +0.74 (Day 8) vs Gemini -1.00 (Fooled Day 10) vs Solver +0.69 (Day 7) | First catch: Solver";
  if (!shareSeed26 || shareSeed26.textContent !== expectedShare26) {
    modeErrors.push("Seed 26 arenaShareText mismatch: " + String(shareSeed26 && shareSeed26.textContent));
  }
  const h2hSeed26 = root.querySelector(".h2h-table");
  if (!h2hSeed26 || !h2hSeed26.textContent.includes("e17") || !h2hSeed26.textContent.includes("SolverPolicy")) {
    modeErrors.push("Seed 26 head-to-head table missing unlocked Gemini e17 or SolverPolicy row");
  }

  const rawLbJson = sharedStorage.getItem("canary_arena_leaderboard_v1");
  let parsedLb = [];
  try {
    parsedLb = JSON.parse(rawLbJson || "[]");
  } catch (_) {
    parsedLb = [];
  }
  if (!Array.isArray(parsedLb) || parsedLb.length !== 2 || parsedLb[0].seed !== 26 || parsedLb[1].seed !== 6) {
    modeErrors.push("session leaderboard storage did not persist Seeds 6 & 26: " + String(rawLbJson));
  }
  lbBtn.click();
  if (!lbDlg.textContent.includes("Seed 26 (hard)") || !lbDlg.textContent.includes("Seed 6 (hard)")) {
    modeErrors.push("Leaderboard dialog did not render persisted Seed 6 and Seed 26 rows");
  }
  app.closeLeaderboard();
  modesExercised.push("duel");

  const solverTab = root.querySelector('[data-mode="solver"]');
  if (solverTab) solverTab.click(); else app.setMode("solver");
  app.loadSeed(3042, "medium");
  if (app.getState().seed !== 3042 || app.getState().tier !== "medium") {
    modeErrors.push("solver loadSeed(3042, 'medium') failed");
  }
  const sessionsBefore3000 = createdSessions.length;
  app.loadSeed(3000, "medium");
  if (app.getState().seed !== 3000 || app.getState().tier !== "medium" || createdSessions.length !== sessionsBefore3000 + 1) {
    modeErrors.push("solver loadSeed(3000, 'medium') did not succeed");
  }
  const sessionsAfter3000 = createdSessions.length;
  app.loadSeed(6, "medium");
  if (app.getState().seed !== 3000 || createdSessions.length !== sessionsAfter3000) {
    modeErrors.push("solver firewall failed to reject private duel seed 6");
  }
  app.loadSeed(900000, "medium");
  if (app.getState().seed !== 3000 || createdSessions.length !== sessionsAfter3000) {
    modeErrors.push("solver firewall failed to reject judge seed 900000");
  }
  app.loadSeed(800000, "medium");
  app.loadSeed(2999, "medium");
  app.loadSeed(10000, "medium");
  if (app.getState().seed !== 3000 || createdSessions.length !== sessionsAfter3000) {
    modeErrors.push("solver firewall failed boundary checks (2999, 10000, 800000)");
  }
  assertZeroPreEndLeaks("solver-3000", app);
  modesExercised.push("solver");

  const moleTab = root.querySelector('[data-mode="mole"]');
  if (moleTab) moleTab.click(); else app.setMode("mole");
  if (app.getState().mode !== "mole" || app.getState().day !== 1) {
    modeErrors.push("mole mode failed to initialize at Day 1");
  }
  assertZeroPreEndLeaks("mole-day1", app);

  app.stepMole(null);
  if (app.getState().day !== 2 || moleStepCalls[0] !== null) {
    modeErrors.push("stepMole(null) did not advance cleanly to Day 2");
  }
  assertZeroPreEndLeaks("mole-day2-hold", app);

  app.stepMole("doc_01");
  if (app.getState().day !== 3 || app.getState().visibleV !== 0.95 || moleStepCalls[1] !== "doc_01") {
    modeErrors.push("stepMole('doc_01') did not advance cleanly to Day 3 with V=0.95");
  }
  assertZeroPreEndLeaks("mole-day3-leak", app);
  modesExercised.push("mole");

  const livingModeTab = root.querySelector('[data-mode="living"]');
  if (livingModeTab) livingModeTab.click(); else app.setMode("living");
  if (app.getState().mode !== "living") {
    modeErrors.push("failed switching to living mode");
  }
  if (!root.textContent.includes("Did NOT pass Gate B")) {
    modeErrors.push("living mode missing mandatory Gate B honesty banner");
  }
  if (!root.textContent.includes("Printer queue spike near Finance")) {
    modeErrors.push("living mode failed to render Day 1 cached rumour");
  }
  assertZeroPreEndLeaks("living-day1", app);
  modesExercised.push("living");

  app.destroy();
  if (root.childNodes.length !== 0) {
    modeErrors.push("app.destroy() did not clear mounted root");
  }

  const persistedRoot = doc.createElement("div");
  doc.body.appendChild(persistedRoot);
  const reloadedApp = indexMod.mountArenaUI(persistedRoot, {
    document: doc,
    storage: sharedStorage,
    createGame,
    duelPack,
    solverLive,
    moleMode,
    livingOffice
  });
  reloadedApp.openLeaderboard();
  const reloadedLbDlg = persistedRoot.querySelector(".leaderboard-dlg");
  if (!reloadedLbDlg || !reloadedLbDlg.textContent.includes("Seed 26 (hard)") || !reloadedLbDlg.textContent.includes("Seed 6 (hard)")) {
    modeErrors.push("reloaded mountArenaUI failed to restore session leaderboard from storage");
  }
  reloadedApp.destroy();
} else {
  modeErrors.push("mountArenaUI unavailable from docs/arena/ui/index.js");
}

if (xssAttempts.length > 0) {
  bootErrors.push("runtime XSS sink invoked: " + xssAttempts.join(", "));
}
if (networkAttempts.length > 0) {
  modeErrors.push("runtime network call invoked: " + networkAttempts.join(", "));
}

console.log(JSON.stringify({
  imported_modules: importedNames,
  boot_errors: bootErrors,
  modes_exercised: modesExercised,
  mode_errors: modeErrors
}));
"""


@dataclass
class CheckResult:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


def resolve_node_bin(explicit: str | None = None) -> str | None:
    if explicit is not None:
        cleaned = explicit.strip()
        if not cleaned:
            return None
        cand = Path(cleaned)
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
        return shutil.which(cleaned)

    env_node = os.environ.get("NODE_BIN", "").strip()
    if env_node:
        env_path = Path(env_node)
        if env_path.is_file() and os.access(env_path, os.X_OK):
            return str(env_path)
        looked_env = shutil.which(env_node)
        if looked_env:
            return looked_env

    for bin_name in ("node", "nodejs"):
        found = shutil.which(bin_name)
        if found:
            return found

    fallback_paths = (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/home/silas/tools/node/bin/node"),
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    )
    for fb in fallback_paths:
        if fb.is_file() and os.access(fb, os.X_OK):
            return str(fb)
    return None


def _extract_js_const_literal(js_src: str, const_name: str) -> Any:
    pattern = re.compile(rf"export\s+const\s+{re.escape(const_name)}\s*=\s*([\[{{])")
    match = pattern.search(js_src)
    if match is None:
        raise ValueError(f"missing export const {const_name}")
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
    if end <= start:
        raise ValueError(f"unterminated literal for {const_name}")
    raw_lit = js_src[start:end]
    quoted_keys = re.sub(r'(?<=[{,\n])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'"\1":', raw_lit)
    clean_json = re.sub(r",\s*([\]}])", r"\1", quoted_keys)
    return json.loads(clean_json)


def extract_index_html_relative_assets(html_src: str) -> list[str]:
    stripped = HTML_COMMENT_RX.sub("", html_src)
    raw_refs: list[str] = []
    for match in SCRIPT_SRC_RX.finditer(stripped):
        raw_refs.append(match.group(2))
    for match in LINK_HREF_RX.finditer(stripped):
        raw_refs.append(match.group(2))
    for inline_match in INLINE_SCRIPT_RX.finditer(stripped):
        script_body = inline_match.group(1)
        for imp_match in ESM_IMPORT_FROM_RX.finditer(script_body):
            raw_refs.append(imp_match.group(2))
        for dyn_match in ESM_DYNAMIC_IMPORT_RX.finditer(script_body):
            raw_refs.append(dyn_match.group(2))

    seen: set[str] = set()
    rel_assets: list[str] = []
    for raw_ref in raw_refs:
        ref = raw_ref.strip()
        if not ref or "${" in ref or "{{" in ref:
            continue
        if ref.startswith("/") or ref.startswith(SLASH_SLASH):
            continue
        lowered = ref.lower()
        if lowered.startswith(("http:", "https:", "data:", "blob:", "mailto:", "javascript:")):
            continue
        clean_path = unquote(ref.split(HASH_CH, 1)[0].split("?", 1)[0]).strip()
        if not clean_path.lower().endswith((".js", ".mjs", ".css")):
            continue
        if clean_path not in seen:
            seen.add(clean_path)
            rel_assets.append(clean_path)
    return rel_assets


def check_index_html_assets(root: Path) -> tuple[bool, int, list[str]]:
    resolved_root = Path(root).resolve()
    index_html = resolved_root / "docs" / "arena" / "index.html"
    if not index_html.exists():
        return False, 0, []
    if not index_html.is_file():
        return True, 0, ["docs/arena/index.html exists but is not a regular file"]
    try:
        html_src = index_html.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return True, 0, [f"docs/arena/index.html: unreadable UTF-8 ({exc})"]
    if not html_src.strip():
        return True, 0, ["docs/arena/index.html: empty file"]

    rel_assets = extract_index_html_relative_assets(html_src)
    missing: list[str] = []
    for asset_ref in rel_assets:
        resolved_asset = (index_html.parent / asset_ref).resolve()
        if not resolved_asset.is_relative_to(resolved_root):
            missing.append(
                f"docs/arena/index.html: referenced asset escapes root '{asset_ref}'"
            )
            continue
        if not resolved_asset.is_file():
            missing.append(
                f"docs/arena/index.html: missing referenced relative asset '{asset_ref}'"
            )
    return True, len(rel_assets), missing


def check_ui_static_hygiene_and_xss(root: Path = ROOT) -> CheckResult:
    resolved_root = Path(root).resolve()
    ui_dir = resolved_root / "docs" / "arena" / "ui"
    if not ui_dir.is_dir():
        return CheckResult(
            CHECK_STATIC,
            "FAIL",
            "missing docs/arena/ui directory",
            [str(ui_dir)],
        )

    ui_files = sorted(p for p in ui_dir.rglob("*") if p.is_file())
    js_files = sorted(ui_dir.glob("*.js"))
    if not js_files:
        return CheckResult(
            CHECK_STATIC,
            "FAIL",
            "no JavaScript modules found under docs/arena/ui",
        )

    required_js = ("dom.js", "office_stage.js", "arena_app.js", "index.js", "ai_duel_panel.js")
    missing_req = [name for name in required_js if not (ui_dir / name).is_file()]
    if missing_req:
        return CheckResult(
            CHECK_STATIC,
            "FAIL",
            f"missing required UI module(s): {', '.join(missing_req)}",
            [f"docs/arena/ui/{name}" for name in missing_req],
        )

    failures: list[str] = []
    for ui_path in ui_files:
        rel = ui_path.relative_to(resolved_root).as_posix()
        try:
            src = ui_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            failures.append(f"{rel}: unreadable UTF-8 ({exc})")
            continue
        if not src.strip():
            failures.append(f"{rel}: empty UI file")
            continue
        if not src.isascii():
            failures.append(f"{rel}: contains non-ASCII characters")
        if EM_DASH in src or EN_DASH in src or UNICODE_MINUS in src:
            failures.append(f"{rel}: contains forbidden dash or unicode minus character")
        if SLASH_SLASH in src or SLASH_STAR in src or STAR_SLASH in src:
            failures.append(f"{rel}: contains forbidden comment marker")
        for sink in FORBIDDEN_XSS_SINKS:
            if sink in src:
                failures.append(f"{rel}: contains forbidden XSS sink '{sink}'")
        for label, rx in FORBIDDEN_EVAL_RXES:
            if rx.search(src) is not None:
                failures.append(f"{rel}: contains forbidden dynamic code sink '{label}'")
        for api_tok in FORBIDDEN_LIVE_API_TOKENS:
            if api_tok in src:
                failures.append(f"{rel}: contains live API endpoint '{api_tok}'")

    dom_path = ui_dir / "dom.js"
    dom_src = dom_path.read_text(encoding="utf-8", errors="replace")
    try:
        tool_defs = _extract_js_const_literal(dom_src, "TOOL_DEFS")
        if tuple(tool_defs.keys()) != EXPECTED_TOOL_NAMES:
            failures.append(
                f"docs/arena/ui/dom.js: TOOL_DEFS keys {list(tool_defs.keys())} != {list(EXPECTED_TOOL_NAMES)}"
            )
        try:
            from canary.env import Env
            from canary.types import INVESTIGATIVE_TOOLS

            env_tools = [entry["name"] for entry in Env("hard", 6).tools_spec()]
            if list(tool_defs.keys()) != env_tools:
                failures.append("docs/arena/ui/dom.js: TOOL_DEFS keys out of sync with Env.tools_spec()")
            for t_name, meta in tool_defs.items():
                if isinstance(meta, dict) and meta.get("costed") is not (t_name in INVESTIGATIVE_TOOLS):
                    failures.append(
                        f"docs/arena/ui/dom.js: TOOL_DEFS[{t_name}].costed mismatch with INVESTIGATIVE_TOOLS"
                    )
        except Exception:
            pass
    except Exception as exc:
        failures.append(f"docs/arena/ui/dom.js: failed parsing TOOL_DEFS ({exc})")

    index_present, index_asset_count, index_errors = check_index_html_assets(resolved_root)
    failures.extend(index_errors)

    if failures:
        return CheckResult(
            CHECK_STATIC,
            "FAIL",
            f"{len(failures)} static hygiene, asset, or XSS issue(s)",
            failures,
        )

    index_note = (
        f"; index.html verified ({index_asset_count} relative asset(s))"
        if index_present
        else "; index.html absent (standalone craft-arena mode)"
    )
    return CheckResult(
        CHECK_STATIC,
        "PASS",
        f"verified {len(ui_files)} UI file(s): pure ASCII, 0 comments, 0 XSS sinks{index_note}",
    )


def _static_fallback_checks(ui_dir: Path) -> tuple[CheckResult, CheckResult]:
    dom_path = ui_dir / "dom.js"
    app_path = ui_dir / "arena_app.js"
    stage_path = ui_dir / "office_stage.js"
    panel_path = ui_dir / "ai_duel_panel.js"
    boot_failures: list[str] = []

    dom_src = dom_path.read_text(encoding="utf-8", errors="replace")
    for req_rx in (
        r"export\s+function\s+el\s*\(",
        r"export\s+function\s+clear\s*\(",
        r"export\s+function\s+pad2\s*\(",
        r"export\s+function\s+fmtScore\s*\(",
    ):
        if re.search(req_rx, dom_src) is None:
            boot_failures.append(f"dom.js missing export matching {req_rx}")
    try:
        modes = _extract_js_const_literal(dom_src, "MODE_DEFS")
        if [m.get("id") for m in modes] != list(EXPECTED_MODE_IDS):
            boot_failures.append("dom.js MODE_DEFS ids mismatch")
    except Exception as exc:
        boot_failures.append(f"dom.js MODE_DEFS parse error: {exc}")

    stage_src = stage_path.read_text(encoding="utf-8", errors="replace")
    if "export class OfficeStage" not in stage_src:
        boot_failures.append("office_stage.js missing export class OfficeStage")

    panel_src = panel_path.read_text(encoding="utf-8", errors="replace")
    if "export function createAiDuelPanel" not in panel_src:
        boot_failures.append("ai_duel_panel.js missing export function createAiDuelPanel")

    if boot_failures:
        boot_res = CheckResult(CHECK_BOOT, "FAIL", f"{len(boot_failures)} static boot error(s)", boot_failures)
    else:
        boot_res = CheckResult(
            CHECK_BOOT,
            "WARN",
            "node binary unavailable; verified index.js, OfficeStage, and ai_duel_panel.js exports statically",
        )

    app_src = app_path.read_text(encoding="utf-8", errors="replace")
    mode_failures: list[str] = []
    for req_tok in ("export function mountArenaUI", "[SEALED]", "Did NOT pass Gate B", "3000", "9999"):
        if req_tok not in app_src:
            mode_failures.append(f"arena_app.js missing expected token '{req_tok}'")
    if mode_failures:
        mode_res = CheckResult(CHECK_MODES, "FAIL", f"{len(mode_failures)} static arena_app.js error(s)", mode_failures)
    else:
        mode_res = CheckResult(
            CHECK_MODES,
            "WARN",
            "node binary unavailable; verified 4-mode guards statically",
        )
    return boot_res, mode_res


def smoke_arena_ui(
    root: Path = ROOT,
    *,
    node_bin: str | None = None,
    require_node: bool = False,
    max_seconds: float = 3.0,
) -> list[CheckResult]:
    t0 = time.monotonic()
    resolved_root = Path(root).resolve()
    static_res = check_ui_static_hygiene_and_xss(resolved_root)

    ui_dir = resolved_root / "docs" / "arena" / "ui"
    dom_path = ui_dir / "dom.js"
    index_path = ui_dir / "index.js"
    stage_path = ui_dir / "office_stage.js"
    panel_path = ui_dir / "ai_duel_panel.js"
    if not ui_dir.is_dir() or not all(p.is_file() for p in (dom_path, index_path, stage_path, panel_path)):
        return [
            static_res,
            CheckResult(CHECK_BOOT, "FAIL", "cannot run ESM boot smoke: missing required docs/arena/ui modules"),
            CheckResult(CHECK_MODES, "FAIL", "cannot run 4-mode smoke: missing required docs/arena/ui modules"),
        ]

    resolved_node = resolve_node_bin(node_bin)
    if resolved_node is None:
        if require_node:
            return [
                static_res,
                CheckResult(CHECK_BOOT, "FAIL", "node binary not found (required by --require-node)"),
                CheckResult(CHECK_MODES, "FAIL", "node binary not found (required by --require-node)"),
            ]
        boot_fb, mode_fb = _static_fallback_checks(ui_dir)
        return [static_res, boot_fb, mode_fb]

    js_files = sorted(ui_dir.glob("*.js"))
    cfg = {
        "ui_files": [{"name": p.name, "uri": p.resolve().as_uri()} for p in js_files],
        "dom_uri": dom_path.resolve().as_uri(),
        "index_uri": index_path.resolve().as_uri(),
        "office_stage_uri": stage_path.resolve().as_uri(),
        "ai_duel_panel_uri": panel_path.resolve().as_uri(),
    }
    env = dict(os.environ)
    for secret_key in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "CANARY_WORLD_SECRET",
    ):
        env.pop(secret_key, None)
    env["SMOKE_CONFIG_JSON"] = json.dumps(cfg)

    try:
        proc = subprocess.run(
            [resolved_node, "--input-type=module", "-e", NODE_ESM_SMOKE_JS],
            cwd=resolved_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=max(3.0, max_seconds * 2.0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [
            static_res,
            CheckResult(CHECK_BOOT, "FAIL", f"node execution failed: {exc}"),
            CheckResult(CHECK_MODES, "FAIL", f"node execution failed: {exc}"),
        ]

    if proc.returncode != 0:
        err_tail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()[-600:]
        details = [err_tail] if err_tail else []
        return [
            static_res,
            CheckResult(CHECK_BOOT, "FAIL", f"Node ESM smoke exited with {proc.returncode}", details),
            CheckResult(CHECK_MODES, "FAIL", f"Node ESM smoke exited with {proc.returncode}", details),
        ]

    try:
        payload = json.loads((proc.stdout or "").strip())
    except ValueError as exc:
        return [
            static_res,
            CheckResult(CHECK_BOOT, "FAIL", f"invalid JSON from Node ESM smoke: {exc}"),
            CheckResult(CHECK_MODES, "FAIL", f"invalid JSON from Node ESM smoke: {exc}"),
        ]

    boot_errors = [str(e) for e in payload.get("boot_errors") or []]
    mode_errors = [str(e) for e in payload.get("mode_errors") or []]
    imported_mods = [str(m) for m in payload.get("imported_modules") or []]
    modes_exercised = [str(m) for m in payload.get("modes_exercised") or []]

    if boot_errors:
        boot_res = CheckResult(
            CHECK_BOOT,
            "FAIL",
            f"{len(boot_errors)} boot failure(s) across index.js, OfficeStage, or ai_duel_panel.js",
            boot_errors,
        )
    else:
        boot_res = CheckResult(
            CHECK_BOOT,
            "PASS",
            f"booted {len(imported_mods)} ESM module(s) (index.js, OfficeStage 40x24 canvas, ai_duel_panel.js 4-mode sanitizer)",
        )

    if tuple(modes_exercised) != EXPECTED_MODE_IDS:
        mode_errors.append(
            f"expected modes {list(EXPECTED_MODE_IDS)}, exercised {modes_exercised}"
        )

    elapsed = time.monotonic() - t0
    if elapsed > max_seconds:
        mode_errors.append(f"smoke runtime {elapsed:.3f}s exceeded {max_seconds:.3f}s budget")

    if mode_errors:
        mode_res = CheckResult(
            CHECK_MODES,
            "FAIL",
            f"{len(mode_errors)} 4-mode UI smoke or pre-end leak failure(s)",
            mode_errors,
        )
    else:
        mode_res = CheckResult(
            CHECK_MODES,
            "PASS",
            f"exercised all 4 modes ({', '.join(modes_exercised)}): Seeds 6 & 26 duel, 3000-9999 firewall, mole steps, Gate B banner, 0 leaks ({elapsed:.2f}s)",
        )

    return [static_res, boot_res, mode_res]


run_smoke_checks = smoke_arena_ui
verify_repo = smoke_arena_ui
audit_repo = smoke_arena_ui


def format_report(results: Sequence[CheckResult], elapsed_s: float) -> str:
    lines: list[str] = []
    counts = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for res in results:
        counts[res.status] = counts.get(res.status, 0) + 1
        lines.append(f"[{res.status}] {res.name}: {res.summary}")
        for detail in res.details:
            lines.append(f"       - {detail}")
    lines.append(
        f"SUMMARY: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL ({elapsed_s:.2f}s)"
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Keyless headless Node ESM smoke verifier for Canary Arena UI."
    )
    ap.add_argument("--check", action="store_true", help="Run headless 4-mode UI, XSS, and zero-leak smoke checks")
    ap.add_argument("--root", type=Path, default=ROOT, help="Repository root containing docs/arena/ui")
    ap.add_argument("--node", type=str, default=None, help="Explicit path to Node binary")
    ap.add_argument("--require-node", action="store_true", help="Fail if Node binary is unavailable")
    ap.add_argument("--max-seconds", type=float, default=3.0, help="Maximum allowed runtime in seconds")
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    args = ap.parse_args(list(argv) if argv is not None else None)

    t0 = time.monotonic()
    resolved_root = args.root.resolve()
    results = smoke_arena_ui(
        root=resolved_root,
        node_bin=args.node,
        require_node=args.require_node,
        max_seconds=args.max_seconds,
    )
    elapsed = time.monotonic() - t0
    passed = (not any(r.status == "FAIL" for r in results)) and (elapsed <= args.max_seconds)

    if args.json:
        items: list[dict[str, Any]] = [asdict(r) for r in results]
        index_present = (resolved_root / "docs" / "arena" / "index.html").exists()
        payload = {
            "check_mode": bool(args.check or True),
            "passed": passed,
            "elapsed_s": round(elapsed, 4),
            "index_html_present": index_present,
            "modes_expected": list(EXPECTED_MODE_IDS),
            "results": items,
            "checks": items,
        }
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(results, elapsed))

    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
