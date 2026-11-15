from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tokenize
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEMO_DIR = ROOT / "demo" / "out-think-gemini"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

THINKING_LEVELS: tuple[str, ...] = ("minimal", "low", "medium", "high", "xhigh")
FORBIDDEN_DASH_CODEPOINTS: tuple[int, ...] = (
    0x2010,
    0x2011,
    0x2012,
    0x2013,
    0x2014,
    0x2015,
    0x2212,
)
API_KEY_ENV_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _live_demo_dir() -> Path:
    override = os.environ.get("OUTTHINK_QA_DEMO_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return DEFAULT_DEMO_DIR


@pytest.fixture(autouse=True)
def _block_python_network_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _blocked_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("OfflineGuardError: outbound Python socket is blocked in keyless QA")

    def _blocked_connect(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("OfflineGuardError: socket.create_connection is blocked in keyless QA")

    monkeypatch.setattr(socket, "socket", _blocked_socket)
    monkeypatch.setattr(socket, "create_connection", _blocked_connect)


def _resolve_js_cmd() -> tuple[list[str], dict[str, str]]:
    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in API_KEY_ENV_VARS
    }
    clean_env["NO_PROXY"] = "*"
    clean_env["HTTP_PROXY"] = ""
    clean_env["HTTPS_PROXY"] = ""

    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env

    opencode_candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
        "/root/momin/bin/opencode",
    ]
    for cand in opencode_candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env

    pytest.skip("no JavaScript runtime available")


VM_HARNESS_PRELUDE_JS = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");

function createDomSandbox(options) {
  const opts = options || {};
  const drawStats = {
    calls: 0,
    fillTextCalls: 0,
    drawImageCalls: 0,
    lastTexts: []
  };
  const elementsById = Object.create(null);
  let rafCounter = 1;

  function makeClassList(owner) {
    function syncFromClassName() {
      return String(owner.className || "")
        .split(/\s+/)
        .filter(Boolean);
    }
    function writeTokens(tokens) {
      owner.className = tokens.join(" ");
    }
    return {
      add: function () {
        const set = syncFromClassName();
        for (let i = 0; i < arguments.length; i += 1) {
          const cls = String(arguments[i] || "").trim();
          if (cls && set.indexOf(cls) === -1) {
            set.push(cls);
          }
        }
        writeTokens(set);
      },
      remove: function () {
        let set = syncFromClassName();
        for (let i = 0; i < arguments.length; i += 1) {
          const cls = String(arguments[i] || "").trim();
          set = set.filter(function (x) { return x !== cls; });
        }
        writeTokens(set);
      },
      toggle: function (cls, force) {
        const token = String(cls || "").trim();
        if (!token) {
          return false;
        }
        const set = syncFromClassName();
        const has = set.indexOf(token) >= 0;
        const shouldHave = force === undefined ? !has : Boolean(force);
        if (shouldHave && !has) {
          set.push(token);
          writeTokens(set);
        } else if (!shouldHave && has) {
          writeTokens(set.filter(function (x) { return x !== token; }));
        }
        return shouldHave;
      },
      contains: function (cls) {
        return syncFromClassName().indexOf(String(cls || "").trim()) >= 0;
      }
    };
  }

  function makeCanvas2DContext(canvasEl) {
    function recordText(txt) {
      drawStats.calls += 1;
      drawStats.fillTextCalls += 1;
      if (drawStats.lastTexts.length < 200) {
        drawStats.lastTexts.push(String(txt));
      }
    }
    return {
      canvas: canvasEl,
      fillStyle: "rgb(0,0,0)",
      strokeStyle: "rgb(0,0,0)",
      lineWidth: 1,
      globalAlpha: 1,
      font: "10px monospace",
      textAlign: "left",
      textBaseline: "alphabetic",
      imageSmoothingEnabled: false,
      save: function () { drawStats.calls += 1; },
      restore: function () { drawStats.calls += 1; },
      scale: function () { drawStats.calls += 1; },
      rotate: function () { drawStats.calls += 1; },
      translate: function () { drawStats.calls += 1; },
      transform: function () { drawStats.calls += 1; },
      setTransform: function () { drawStats.calls += 1; },
      clearRect: function () { drawStats.calls += 1; },
      fillRect: function () { drawStats.calls += 1; },
      strokeRect: function () { drawStats.calls += 1; },
      beginPath: function () { drawStats.calls += 1; },
      closePath: function () { drawStats.calls += 1; },
      moveTo: function () { drawStats.calls += 1; },
      lineTo: function () { drawStats.calls += 1; },
      arc: function () { drawStats.calls += 1; },
      arcTo: function () { drawStats.calls += 1; },
      quadraticCurveTo: function () { drawStats.calls += 1; },
      rect: function () { drawStats.calls += 1; },
      fill: function () { drawStats.calls += 1; },
      stroke: function () { drawStats.calls += 1; },
      clip: function () { drawStats.calls += 1; },
      setLineDash: function () { drawStats.calls += 1; },
      fillText: function (txt) { recordText(txt); },
      strokeText: function (txt) { recordText(txt); },
      measureText: function (txt) {
        return { width: String(txt == null ? "" : txt).length * 6 };
      },
      drawImage: function () {
        drawStats.calls += 1;
        drawStats.drawImageCalls += 1;
      },
      createLinearGradient: function () {
        return { addColorStop: function () {} };
      },
      createRadialGradient: function () {
        return { addColorStop: function () {} };
      },
      getImageData: function (_x, _y, w, h) {
        const len = Math.max(1, Number(w || 1) * Number(h || 1) * 4);
        return { data: new Uint8ClampedArray(len), width: w || 1, height: h || 1 };
      },
      putImageData: function () { drawStats.calls += 1; }
    };
  }

  function matchesSelector(node, selector) {
    if (!node || !selector) {
      return false;
    }
    const sel = String(selector).trim();
    const hashPrefix = String.fromCharCode(35);
    if (sel.indexOf(hashPrefix) === 0) {
      return node.id === sel.slice(1);
    }
    if (sel.indexOf(".") === 0) {
      return node.classList.contains(sel.slice(1));
    }
    const attrMatch = sel.match(/^\[([a-zA-Z0-9_-]+)(?:=["']?([^"'\]]*)["']?)?\]$/);
    if (attrMatch) {
      const attrName = attrMatch[1];
      const expected = attrMatch[2];
      const got = node.getAttribute(attrName);
      if (got === null || got === undefined) {
        return false;
      }
      return expected === undefined ? true : String(got) === expected;
    }
    return String(node.tagName || "").toLowerCase() === sel.toLowerCase();
  }

  function createElement(tagName) {
    const upperTag = String(tagName || "div").toUpperCase();
    const attrs = Object.create(null);
    const listeners = Object.create(null);
    let ownText = "";
    let idVal = "";
    let ctx2dInstance = null;

    const el = {
      tagName: upperTag,
      nodeType: 1,
      className: "",
      style: { cssText: "" },
      dataset: Object.create(null),
      children: [],
      parentNode: null,
      hidden: false,
      disabled: false,
      value: "",
      selected: false,
      type: "",
      width: upperTag === "CANVAS" ? 960 : 0,
      height: upperTag === "CANVAS" ? 520 : 0,
      get id() {
        return idVal;
      },
      set id(nextId) {
        if (idVal && elementsById[idVal] === el) {
          delete elementsById[idVal];
        }
        idVal = String(nextId || "");
        if (idVal) {
          elementsById[idVal] = el;
        }
      },
      get firstChild() {
        return el.children.length > 0 ? el.children[0] : null;
      },
      get textContent() {
        if (el.children.length === 0) {
          return ownText;
        }
        return ownText + el.children.map(function (c) { return c.textContent; }).join("");
      },
      set textContent(v) {
        el.children.forEach(function (c) { c.parentNode = null; });
        el.children = [];
        ownText = v === null || v === undefined ? "" : String(v);
      },
      get innerHTML() {
        return el.textContent;
      },
      set innerHTML(v) {
        el.textContent = v;
      },
      setAttribute: function (name, val) {
        const key = String(name);
        const sval = String(val);
        attrs[key] = sval;
        if (key === "id") {
          el.id = sval;
        } else if (key === "class") {
          el.className = sval;
        } else if (key.indexOf("data-") === 0) {
          const camel = key.slice(5).replace(/-([a-z])/g, function (_m, ch) {
            return ch.toUpperCase();
          });
          el.dataset[camel] = sval;
        }
      },
      getAttribute: function (name) {
        const key = String(name);
        if (key === "id") {
          return idVal || null;
        }
        if (key === "class") {
          return el.className || null;
        }
        return Object.prototype.hasOwnProperty.call(attrs, key) ? attrs[key] : null;
      },
      removeAttribute: function (name) {
        delete attrs[String(name)];
      },
      appendChild: function (child) {
        if (!child) {
          return child;
        }
        if (child.parentNode && typeof child.parentNode.removeChild === "function") {
          child.parentNode.removeChild(child);
        }
        child.parentNode = el;
        el.children.push(child);
        if (upperTag === "SELECT" && child.tagName === "OPTION") {
          if (child.selected || el.value === "") {
            el.value = child.value;
          }
        }
        return child;
      },
      removeChild: function (child) {
        const idx = el.children.indexOf(child);
        if (idx >= 0) {
          el.children.splice(idx, 1);
          child.parentNode = null;
        }
        return child;
      },
      addEventListener: function (type, fn) {
        const key = String(type);
        if (!listeners[key]) {
          listeners[key] = [];
        }
        if (typeof fn === "function") {
          listeners[key].push(fn);
        }
      },
      removeEventListener: function (type, fn) {
        const key = String(type);
        if (!listeners[key]) {
          return;
        }
        listeners[key] = listeners[key].filter(function (f) { return f !== fn; });
      },
      dispatchEvent: function (ev) {
        const eventObj = Object.assign({ target: el, currentTarget: el, preventDefault: function () {} }, ev || {});
        const list = listeners[String(eventObj.type || "")] || [];
        for (let i = 0; i < list.length; i += 1) {
          list[i].call(el, eventObj);
        }
        if (el.parentNode && eventObj.bubbles !== false && eventObj.type === "click") {
          const parentList = el.parentNode._getListeners ? el.parentNode._getListeners("click") : [];
          for (let p = 0; p < parentList.length; p += 1) {
            parentList[p].call(el.parentNode, Object.assign({}, eventObj, { currentTarget: el.parentNode }));
          }
        }
        return true;
      },
      _getListeners: function (type) {
        return listeners[String(type)] || [];
      },
      click: function () {
        if (el.disabled) {
          return;
        }
        el.dispatchEvent({ type: "click", bubbles: true, clientX: 48, clientY: 48 });
      },
      closest: function (selector) {
        let cur = el;
        while (cur) {
          if (matchesSelector(cur, selector)) {
            return cur;
          }
          cur = cur.parentNode;
        }
        return null;
      },
      querySelectorAll: function (selector) {
        const out = [];
        function walk(node) {
          for (let i = 0; i < node.children.length; i += 1) {
            const ch = node.children[i];
            if (matchesSelector(ch, selector)) {
              out.push(ch);
            }
            walk(ch);
          }
        }
        walk(el);
        return out;
      },
      querySelector: function (selector) {
        const hits = el.querySelectorAll(selector);
        return hits.length > 0 ? hits[0] : null;
      },
      scrollIntoView: function () {},
      getBoundingClientRect: function () {
        return { left: 0, top: 0, width: el.width || 960, height: el.height || 520 };
      },
      getContext: function (kind) {
        if (upperTag === "CANVAS" && String(kind) === "2d") {
          if (!ctx2dInstance) {
            ctx2dInstance = makeCanvas2DContext(el);
          }
          return ctx2dInstance;
        }
        return null;
      }
    };
    el.classList = makeClassList(el);
    return el;
  }

  const body = createElement("body");
  const defaultIds = [
    ["phaser-stage", "div"],
    ["stage-fallback", "div"],
    ["dataset-badge", "span"],
    ["case-select", "select"],
    ["btn-prev-case", "button"],
    ["btn-next-case", "button"],
    ["btn-reset-scores", "button"],
    ["scoreboard-bar", "section"],
    ["case-tier-badge", "span"],
    ["case-title", "h2"],
    ["case-company", "span"],
    ["case-seed-badge", "span"],
    ["case-day-badge", "strong"],
    ["case-step-badge", "span"],
    ["case-reward-badge", "strong"],
    ["case-status-pill", "strong"],
    ["btn-highlight-suspects", "button"],
    ["highlight-summary", "span"],
    ["suspect-roster", "div"],
    ["dossier-clearance", "span"],
    ["dossier-card", "div"],
    ["btn-accuse", "button"],
    ["btn-hold-fire", "button"],
    ["btn-filter-suspect", "button"],
    ["evidence-cutoff-note", "span"],
    ["evidence-tabs", "div"],
    ["evidence-list", "div"],
    ["reveal-panel", "section"],
    ["provenance-summary", "div"],
    ["asset-credits-list", "div"]
  ];

  for (let i = 0; i < defaultIds.length; i += 1) {
    const pair = defaultIds[i];
    const node = createElement(pair[1]);
    node.id = pair[0];
    if (pair[0] === "reveal-panel" || pair[0] === "stage-fallback") {
      node.hidden = true;
    }
    body.appendChild(node);
  }

  const tabsContainer = elementsById["evidence-tabs"];
  const tabNames = ["canaries", "leaks", "access", "comms", "steps"];
  for (let t = 0; t < tabNames.length; t += 1) {
    const tName = tabNames[t];
    const btn = createElement("button");
    btn.setAttribute("data-tab", tName);
    const cnt = createElement("span");
    cnt.id = "count-" + tName;
    cnt.textContent = "0";
    btn.appendChild(cnt);
    tabsContainer.appendChild(btn);
  }

  function throwOffline(apiName) {
    throw new Error("OfflineGuardError: " + apiName + " is blocked in offline QA sandbox");
  }

  function OfflineXMLHttpRequest() {
    throwOffline("XMLHttpRequest");
  }
  OfflineXMLHttpRequest.prototype.open = function () { throwOffline("XMLHttpRequest.open"); };
  OfflineXMLHttpRequest.prototype.send = function () { throwOffline("XMLHttpRequest.send"); };

  function OfflineImage() {
    this.width = 0;
    this.height = 0;
    this.naturalWidth = 0;
    this.naturalHeight = 0;
    this.complete = false;
    this.onload = null;
    this.onerror = null;
    let srcVal = "";
    const self = this;
    Object.defineProperty(this, "src", {
      get: function () { return srcVal; },
      set: function (nextSrc) {
        const s = String(nextSrc || "");
        if (/^https?:\/\//i.test(s) || /^\/\//.test(s)) {
          throwOffline("Image.src(" + s + ")");
        }
        srcVal = s;
        self.width = 16;
        self.height = 16;
        self.naturalWidth = 16;
        self.naturalHeight = 16;
        self.complete = true;
        if (typeof self.onload === "function") {
          self.onload();
        }
      }
    });
  }

  const documentObj = {
    readyState: opts.readyState || "complete",
    body: body,
    createElement: createElement,
    getElementById: function (id) {
      const key = String(id || "");
      return Object.prototype.hasOwnProperty.call(elementsById, key) ? elementsById[key] : null;
    },
    querySelectorAll: function (sel) {
      return body.querySelectorAll(sel);
    },
    querySelector: function (sel) {
      return body.querySelector(sel);
    },
    addEventListener: function (type, fn) {
      body.addEventListener(type, fn);
    }
  };

  const sandbox = {
    console: console,
    Math: Math,
    Date: Date,
    JSON: JSON,
    Object: Object,
    Array: Array,
    String: String,
    Number: Number,
    Boolean: Boolean,
    RegExp: RegExp,
    Error: Error,
    TypeError: TypeError,
    RangeError: RangeError,
    Uint8Array: Uint8Array,
    Uint8ClampedArray: Uint8ClampedArray,
    parseInt: parseInt,
    parseFloat: parseFloat,
    isNaN: isNaN,
    isFinite: isFinite,
    encodeURIComponent: encodeURIComponent,
    decodeURIComponent: decodeURIComponent,
    performance: { now: function () { return 1000; } },
    requestAnimationFrame: function () {
      rafCounter += 1;
      return rafCounter;
    },
    cancelAnimationFrame: function () {},
    setTimeout: function () { return 1; },
    clearTimeout: function () {},
    fetch: function () { throwOffline("fetch"); },
    XMLHttpRequest: OfflineXMLHttpRequest,
    WebSocket: function () { throwOffline("WebSocket"); },
    EventSource: function () { throwOffline("EventSource"); },
    Image: OfflineImage,
    navigator: {
      userAgent: "OutThinkOfflineQA/1.0",
      sendBeacon: function () { throwOffline("navigator.sendBeacon"); }
    },
    location: { protocol: "file:", href: "file:///demo/out-think-gemini/index.html" },
    document: documentObj
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;

  const ctx = vm.createContext(sandbox);
  return {
    ctx: ctx,
    sandbox: sandbox,
    document: documentObj,
    drawStats: drawStats,
    runCode: function (code, filename) {
      return vm.runInContext(code, ctx, { filename: filename || "inline.js", timeout: 15000 });
    },
    runFile: function (filePath) {
      const code = fs.readFileSync(filePath, "utf8");
      return vm.runInContext(code, ctx, { filename: filePath, timeout: 15000 });
    }
  };
}
"""


INLINE_REFERENCE_ENGINE_JS = r"""
(function (root) {
  "use strict";
  var THINKING_LEVELS = ["minimal", "low", "medium", "high", "xhigh"];
  var ALIASES = {
    min: "minimal",
    minimal: "minimal",
    low: "low",
    med: "medium",
    medium: "medium",
    high: "high",
    xhigh: "xhigh",
    "x-high": "xhigh",
    x_high: "xhigh"
  };

  function round4(x) {
    var n = Number(x);
    return Number.isFinite(n) ? Math.round(n * 10000) / 10000 : 0;
  }

  function round6(x) {
    var n = Number(x);
    return Number.isFinite(n) ? Math.round(n * 1000000) / 1000000 : 0;
  }

  function normLevel(raw) {
    var s = String(raw || "medium").trim().toLowerCase();
    return ALIASES[s] || s;
  }

  function normAction(raw) {
    var s = String(raw || "hold_fire").trim().toLowerCase();
    if (s === "hold_fire" || s === "hold-fire" || s === "wait" || s === "abstain" || s === "hold") {
      return "hold_fire";
    }
    if (s === "accuse" || s.indexOf("accuse:") === 0) {
      return "accuse";
    }
    return s;
  }

  function computeBreakEvenProb(valueAtDecision, holdFireOption) {
    var v = Number(valueAtDecision);
    if (!Number.isFinite(v) || v <= 0) {
      return 1.0;
    }
    var h = 0;
    if (holdFireOption && typeof holdFireOption === "object") {
      var cand = holdFireOption.ev_hold_fire !== undefined ? holdFireOption.ev_hold_fire : holdFireOption.evHoldFire;
      h = Number.isFinite(Number(cand)) ? Number(cand) : 0;
    } else if (holdFireOption !== undefined && holdFireOption !== null) {
      h = Number.isFinite(Number(holdFireOption)) ? Number(holdFireOption) : 0;
    }
    var baseline = h > 0 ? h : 0;
    return Math.min(1, Math.max(0, (1 + baseline) / (1 + v)));
  }

  function computeAccusationEv(prob, valueAtDecision) {
    var p = Math.min(1, Math.max(0, Number(prob) || 0));
    var v = Math.max(0, Number(valueAtDecision) || 0);
    return p * v - (1 - p);
  }

  function evaluateCall(caseObj, judgeCall) {
    var c = caseObj || {};
    var solver = c.solver || {};
    var v = Number.isFinite(Number(c.value_at_decision)) ? Number(c.value_at_decision) : 0.5;
    var trueMole = c.true_mole ? String(c.true_mole) : null;
    var topProb = Number(solver.top_prob) || 0;
    var breakEvenProb = Number.isFinite(Number(solver.break_even_prob))
      ? Number(solver.break_even_prob)
      : computeBreakEvenProb(v, solver);
    var recCall = normAction(solver.recommended_call || "hold_fire");
    var call = typeof judgeCall === "string" ? { action: judgeCall } : (judgeCall || {});
    var action = normAction(call.action || "hold_fire");
    var suspectId = call.suspectId || call.suspect_id || call.accused || null;

    var correct = false;
    var optimal = false;
    var score = 0;
    var verdictLabel = "";

    if (action === "accuse") {
      correct = Boolean(suspectId && trueMole && String(suspectId) === trueMole);
      score = correct ? v : -1.0;
      optimal = Boolean(correct && (recCall !== "hold_fire" || topProb >= breakEvenProb));
      verdictLabel = correct ? (optimal ? "OPTIMAL ACCUSATION" : "LUCKY GUESS") : "FALSE ACCUSATION (-1.00)";
    } else {
      action = "hold_fire";
      correct = Boolean(recCall === "hold_fire" || topProb < 0.95);
      optimal = Boolean(recCall === "hold_fire");
      if (topProb >= 0.98 && recCall !== "hold_fire") {
        score = Math.max(0, v - 0.12);
        verdictLabel = "OVER-CAUTIOUS DELAY";
      } else {
        score = Number.isFinite(Number(solver.ev_hold_fire))
          ? Number(solver.ev_hold_fire)
          : (Number(solver.final_score) || 0);
        verdictLabel = optimal ? "OPTIMAL HOLD FIRE" : "CAUTIOUS HOLD FIRE";
      }
    }

    return {
      action: action,
      suspectId: suspectId ? String(suspectId) : null,
      correct: Boolean(correct),
      optimal: Boolean(optimal),
      score: round4(score),
      verdictLabel: verdictLabel,
      explanation: verdictLabel,
      trueMole: trueMole,
      solver: solver,
      levelComparisons: Array.isArray(c.thinking_levels) ? c.thinking_levels : []
    };
  }

  function emptyBucket() {
    return {
      count: 0,
      scoreSum: 0,
      meanScore: 0,
      rightCount: 0,
      accuracy: 0,
      totalCostUsd: 0,
      totalThinkingTokens: 0,
      judgeOutscoredCount: 0
    };
  }

  function createScoreboard() {
    var order = [];
    var byId = Object.create(null);

    function record(caseId, evalRes, caseObj) {
      var cObj = caseObj || {};
      var ev = evalRes || {};
      var id = String(caseId != null ? caseId : (cObj.id || "case_" + (order.length + 1)));
      if (!Object.prototype.hasOwnProperty.call(byId, id)) {
        order.push(id);
      }
      var stored = Object.assign({}, ev, {
        caseId: id,
        solver: cObj.solver || ev.solver || {},
        levelComparisons: Array.isArray(cObj.thinking_levels) ? cObj.thinking_levels : (ev.levelComparisons || [])
      });
      byId[id] = stored;
      return stored;
    }

    function getCaseResult(caseId) {
      var id = caseId != null ? String(caseId) : "";
      return Object.prototype.hasOwnProperty.call(byId, id) ? byId[id] : null;
    }

    function getAllResults() {
      return order.map(function (id) { return byId[id]; });
    }

    function getSummary() {
      var n = order.length;
      var jSum = 0;
      var jRight = 0;
      var jOpt = 0;
      var sSum = 0;
      var sRight = 0;
      var byLevel = Object.create(null);
      for (var i = 0; i < THINKING_LEVELS.length; i += 1) {
        byLevel[THINKING_LEVELS[i]] = emptyBucket();
      }
      for (var r = 0; r < order.length; r += 1) {
        var rec = byId[order[r]];
        var js = Number(rec.score) || 0;
        jSum += js;
        if (rec.correct === true) jRight += 1;
        if (rec.optimal === true) jOpt += 1;
        var slv = rec.solver || {};
        var ss = Number.isFinite(Number(slv.final_score)) ? Number(slv.final_score) : 0;
        sSum += ss;
        if (slv.correct === true) sRight += 1;
        var lvs = Array.isArray(rec.levelComparisons) ? rec.levelComparisons : [];
        for (var k = 0; k < lvs.length; k += 1) {
          var lv = lvs[k] || {};
          var key = normLevel(lv.thinking_level || lv.key || "medium");
          if (!byLevel[key]) byLevel[key] = emptyBucket();
          var b = byLevel[key];
          var lScore = Number(lv.score) || 0;
          b.count += 1;
          b.scoreSum += lScore;
          if (lv.correct === true) b.rightCount += 1;
          b.totalCostUsd += Number(lv.cost_usd) || 0;
          b.totalThinkingTokens += Number(lv.thinking_tokens) || 0;
          if (js > lScore) b.judgeOutscoredCount += 1;
        }
      }
      var keys = Object.keys(byLevel);
      for (var m = 0; m < keys.length; m += 1) {
        var bk = byLevel[keys[m]];
        bk.scoreSum = round4(bk.scoreSum);
        bk.meanScore = bk.count > 0 ? round4(bk.scoreSum / bk.count) : 0;
        bk.accuracy = bk.count > 0 ? round4(bk.rightCount / bk.count) : 0;
        bk.totalCostUsd = round6(bk.totalCostUsd);
        bk.totalThinkingTokens = Math.round(bk.totalThinkingTokens);
      }
      return {
        casesPlayed: n,
        judge: {
          scoreSum: round4(jSum),
          meanScore: n > 0 ? round4(jSum / n) : 0,
          rightCount: jRight,
          optimalCount: jOpt,
          accuracy: n > 0 ? round4(jRight / n) : 0,
          optimalRate: n > 0 ? round4(jOpt / n) : 0,
          costUsd: 0
        },
        solver: {
          scoreSum: round4(sSum),
          meanScore: n > 0 ? round4(sSum / n) : 0,
          rightCount: sRight,
          accuracy: n > 0 ? round4(sRight / n) : 0
        },
        byLevel: byLevel
      };
    }

    function reset() {
      order = [];
      byId = Object.create(null);
      return getSummary();
    }

    return {
      record: record,
      getCaseResult: getCaseResult,
      getAllResults: getAllResults,
      getSummary: getSummary,
      reset: reset
    };
  }

  function loadDataset(rawData) {
    var payload = rawData || root.OUTTHINK_DATA || { cases: [] };
    var arr = Array.isArray(payload) ? payload : (payload.cases || []);
    var byId = Object.create(null);
    for (var i = 0; i < arr.length; i += 1) {
      byId[arr[i].id] = arr[i];
    }
    return {
      cases: arr,
      count: arr.length,
      byId: byId,
      source: "data",
      isFallback: false,
      isBootstrapFallback: Boolean(payload.isBootstrapFallback)
    };
  }

  root.OutThinkEngine = {
    THINKING_LEVELS: THINKING_LEVELS,
    round4: round4,
    computeBreakEvenProb: computeBreakEvenProb,
    computeAccusationEv: computeAccusationEv,
    loadDataset: loadDataset,
    evaluateCall: evaluateCall,
    createScoreboard: createScoreboard
  };
})(typeof window !== "undefined" ? window : globalThis);
"""


def _run_vm_script(js_body: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_VM_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        VM_HARNESS_PRELUDE_JS
        + "\nconst PAYLOAD = JSON.parse(process.env.OUTTHINK_VM_PAYLOAD);\n"
        + "const result = (() => {\n"
        + js_body
        + "\n})();\n"
        + "process.stdout.write(JSON.stringify(result));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"JS vm failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _inline_fixture_cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "fixture-hold-1",
            "title": "Split Canary Below Break-Even",
            "tier": "hard",
            "seed": 11,
            "company": "Aurora Logistics",
            "decision_day": 6,
            "decision_step": 18,
            "value_at_decision": 0.68,
            "true_mole": "e04",
            "suspects": [
                {"id": "e01", "name": "Sami Laine", "eliminated": True},
                {"id": "e04", "name": "Aino Niemi", "eliminated": False},
                {"id": "e07", "name": "Kalle Salo", "eliminated": False},
            ],
            "solver": {
                "top_suspect": "e04",
                "top_prob": 0.50,
                "break_even_prob": round(1.0 / (1.0 + 0.68), 4),
                "ev_accuse_top": round(0.50 * 0.68 - 0.50, 4),
                "ev_hold_fire": 0.49,
                "recommended_call": "hold_fire",
                "final_accused": "e04",
                "final_day": 9,
                "final_score": 0.52,
                "correct": True,
            },
            "thinking_levels": [
                {
                    "key": "minimal",
                    "thinking_level": "minimal",
                    "call_at_t": "accuse",
                    "accused": "e07",
                    "correct": False,
                    "score": -1.0,
                    "cost_usd": 0.012,
                    "thinking_tokens": 0,
                },
                {
                    "key": "low",
                    "thinking_level": "low",
                    "call_at_t": "accuse",
                    "accused": "e07",
                    "correct": False,
                    "score": -1.0,
                    "cost_usd": 0.045,
                    "thinking_tokens": 620,
                },
                {
                    "key": "medium",
                    "thinking_level": "medium",
                    "call_at_t": "hold_fire",
                    "accused": "e04",
                    "correct": True,
                    "score": 0.44,
                    "cost_usd": 0.130,
                    "thinking_tokens": 3100,
                },
                {
                    "key": "high",
                    "thinking_level": "high",
                    "call_at_t": "hold_fire",
                    "accused": "e04",
                    "correct": True,
                    "score": 0.52,
                    "cost_usd": 0.310,
                    "thinking_tokens": 8400,
                },
                {
                    "key": "xhigh",
                    "thinking_level": "xhigh",
                    "call_at_t": "hold_fire",
                    "accused": "e04",
                    "correct": True,
                    "score": 0.52,
                    "cost_usd": 0.540,
                    "thinking_tokens": 16200,
                },
            ],
        },
        {
            "id": "fixture-accuse-2",
            "title": "Unique Canary Pinpoint",
            "tier": "hard",
            "seed": 19,
            "company": "Boreal Biotech",
            "decision_day": 8,
            "decision_step": 27,
            "value_at_decision": 0.72,
            "true_mole": "e02",
            "suspects": [
                {"id": "e02", "name": "Venla Koski", "eliminated": False},
                {"id": "e05", "name": "Timo Virta", "eliminated": True},
            ],
            "solver": {
                "top_suspect": "e02",
                "top_prob": 0.99,
                "break_even_prob": round(1.0 / (1.0 + 0.72), 4),
                "ev_accuse_top": round(0.99 * 0.72 - 0.01, 4),
                "ev_hold_fire": 0.58,
                "recommended_call": "accuse",
                "final_accused": "e02",
                "final_day": 8,
                "final_score": 0.72,
                "correct": True,
            },
            "thinking_levels": [
                {
                    "key": "minimal",
                    "thinking_level": "minimal",
                    "call_at_t": "accuse",
                    "accused": "e05",
                    "correct": False,
                    "score": -1.0,
                    "cost_usd": 0.015,
                    "thinking_tokens": 0,
                },
                {
                    "key": "low",
                    "thinking_level": "low",
                    "call_at_t": "accuse",
                    "accused": "e02",
                    "correct": True,
                    "score": 0.72,
                    "cost_usd": 0.062,
                    "thinking_tokens": 810,
                },
                {
                    "key": "medium",
                    "thinking_level": "medium",
                    "call_at_t": "accuse",
                    "accused": "e02",
                    "correct": True,
                    "score": 0.72,
                    "cost_usd": 0.145,
                    "thinking_tokens": 2900,
                },
                {
                    "key": "high",
                    "thinking_level": "high",
                    "call_at_t": "accuse",
                    "accused": "e02",
                    "correct": True,
                    "score": 0.72,
                    "cost_usd": 0.295,
                    "thinking_tokens": 7700,
                },
                {
                    "key": "xhigh",
                    "thinking_level": "xhigh",
                    "call_at_t": "accuse",
                    "accused": "e02",
                    "correct": True,
                    "score": 0.72,
                    "cost_usd": 0.510,
                    "thinking_tokens": 14900,
                },
            ],
        },
        {
            "id": "fixture-hold-3",
            "title": "Three-Way Ambiguity on Medium Seed",
            "tier": "medium",
            "seed": 4,
            "company": "Saimaa Cloud",
            "decision_day": 5,
            "decision_step": 14,
            "value_at_decision": 0.80,
            "true_mole": "e09",
            "suspects": [
                {"id": "e03", "name": "Olli Salonen", "eliminated": False},
                {"id": "e06", "name": "Noora Heino", "eliminated": False},
                {"id": "e09", "name": "Petri Ranta", "eliminated": False},
            ],
            "solver": {
                "top_suspect": "e09",
                "top_prob": 0.34,
                "break_even_prob": round(1.0 / (1.0 + 0.80), 4),
                "ev_accuse_top": round(0.34 * 0.80 - 0.66, 4),
                "ev_hold_fire": 0.61,
                "recommended_call": "hold_fire",
                "final_accused": "e09",
                "final_day": 7,
                "final_score": 0.66,
                "correct": True,
            },
            "thinking_levels": [
                {
                    "key": "minimal",
                    "thinking_level": "minimal",
                    "call_at_t": "accuse",
                    "accused": "e03",
                    "correct": False,
                    "score": -1.0,
                    "cost_usd": 0.010,
                    "thinking_tokens": 0,
                },
                {
                    "key": "low",
                    "thinking_level": "low",
                    "call_at_t": "accuse",
                    "accused": "e06",
                    "correct": False,
                    "score": -1.0,
                    "cost_usd": 0.039,
                    "thinking_tokens": 500,
                },
                {
                    "key": "medium",
                    "thinking_level": "medium",
                    "call_at_t": "accuse",
                    "accused": "e03",
                    "correct": False,
                    "score": -1.0,
                    "cost_usd": 0.118,
                    "thinking_tokens": 2600,
                },
                {
                    "key": "high",
                    "thinking_level": "high",
                    "call_at_t": "hold_fire",
                    "accused": "e09",
                    "correct": True,
                    "score": 0.66,
                    "cost_usd": 0.260,
                    "thinking_tokens": 6800,
                },
                {
                    "key": "xhigh",
                    "thinking_level": "xhigh",
                    "call_at_t": "hold_fire",
                    "accused": "e09",
                    "correct": True,
                    "score": 0.66,
                    "cost_usd": 0.490,
                    "thinking_tokens": 13500,
                },
            ],
        },
    ]


def test_self_hygiene_zero_comments_zero_forbidden_dashes_and_unprotected() -> None:
    self_path = Path(__file__).resolve()
    source = self_path.read_text(encoding="utf-8")

    comment_tokens = [
        tok
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT
    ]
    assert comment_tokens == [], f"found Python comments: {comment_tokens}"
    assert chr(35) not in source, "raw hash character found in test source"

    bad_dashes = [
        (idx + 1, hex(ord(ch)))
        for idx, line in enumerate(source.splitlines())
        for ch in line
        if ord(ch) in FORBIDDEN_DASH_CODEPOINTS
    ]
    assert bad_dashes == [], f"forbidden dash codepoints found: {bad_dashes}"

    if PROTECTED_PATHS_FILE.is_file():
        rel_self = self_path.relative_to(ROOT).as_posix()
        prefixes: list[str] = []
        for raw_line in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith(chr(35)):
                continue
            prefixes.append(stripped)
        for prefix in prefixes:
            if prefix.endswith("/"):
                assert not rel_self.startswith(prefix), f"{rel_self} touches protected dir {prefix}"
            else:
                assert rel_self != prefix, f"{rel_self} touches protected file {prefix}"


def test_python_socket_guard_blocks_outbound_connections() -> None:
    with pytest.raises(RuntimeError, match="OfflineGuardError"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    with pytest.raises(RuntimeError, match="OfflineGuardError"):
        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=1)


def test_vm_sandbox_stubs_dom_canvas_and_blocks_fetch_and_xhr() -> None:
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        env.runCode(`
          const stage = document.getElementById("phaser-stage");
          const canvas = document.createElement("canvas");
          stage.appendChild(canvas);
          const ctx = canvas.getContext("2d");
          ctx.fillRect(0, 0, 960, 520);
          ctx.fillText("OUT-THINK GEMINI OFFLINE", 12, 24);

          const localImg = new Image();
          localImg.src = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";
          ctx.drawImage(localImg, 0, 0, 16, 16);

          function captureErr(fn) {
            try {
              fn();
              return null;
            } catch (err) {
              return String(err && err.message ? err.message : err);
            }
          }

          window.__sandboxReport = {
            canvasMounted: stage.children.length === 1 && stage.firstChild === canvas,
            localImgComplete: localImg.complete && localImg.naturalWidth === 16,
            fetchErr: captureErr(() => fetch("https://generativelanguage.googleapis.com/v1beta/models")),
            xhrErr: captureErr(() => new XMLHttpRequest()),
            wsErr: captureErr(() => new WebSocket("wss://example.com")),
            beaconErr: captureErr(() => navigator.sendBeacon("https://example.com", "{}")),
            remoteImgErr: captureErr(() => {
              const bad = new Image();
              bad.src = "https://example.com/sprite.png";
            })
          };
        `);
        return {
          report: env.sandbox.__sandboxReport,
          drawStats: env.drawStats
        };
        """
    )
    report = out["report"]
    assert report["canvasMounted"] is True
    assert report["localImgComplete"] is True
    for key in ("fetchErr", "xhrErr", "wsErr", "beaconErr", "remoteImgErr"):
        assert isinstance(report[key], str) and "OfflineGuardError" in report[key]
    assert out["drawStats"]["calls"] >= 3
    assert out["drawStats"]["fillTextCalls"] == 1
    assert out["drawStats"]["drawImageCalls"] == 1


def test_vm_contract_break_even_formula_and_accusation_ev() -> None:
    live_engine = _live_demo_dir() / "engine.js"
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        if (PAYLOAD.liveEnginePath) {
          env.runFile(PAYLOAD.liveEnginePath);
        } else {
          env.runCode(PAYLOAD.inlineEngineCode, "inline_engine.js");
        }
        const E = env.sandbox.window.OutThinkEngine;
        const testValues = [0.10, 0.25, 0.44, 0.50, 0.68, 0.71, 0.72, 0.85, 1.00];
        const zeroBaselineRows = testValues.map(function (v) {
          const pStar = E.computeBreakEvenProb(v);
          const evAtStar = E.computeAccusationEv(pStar, v);
          const evAbove = E.computeAccusationEv(Math.min(1, pStar + 0.05), v);
          const evBelow = E.computeAccusationEv(Math.max(0, pStar - 0.05), v);
          return { v: v, pStar: pStar, evAtStar: evAtStar, evAbove: evAbove, evBelow: evBelow };
        });

        const posBaselinePairs = [
          { v: 0.72, h: 0.20 },
          { v: 0.80, h: 0.44 },
          { v: 0.68, h: 0.00 },
          { v: 0.68, h: -0.35 }
        ];
        const posBaselineRows = posBaselinePairs.map(function (pair) {
          const fromNum = E.computeBreakEvenProb(pair.v, pair.h);
          const fromObj = E.computeBreakEvenProb(pair.v, { ev_hold_fire: pair.h });
          const evAtThreshold = E.computeAccusationEv(fromObj, pair.v);
          return {
            v: pair.v,
            h: pair.h,
            fromNum: fromNum,
            fromObj: fromObj,
            evAtThreshold: evAtThreshold
          };
        });

        return {
          levels: E.THINKING_LEVELS,
          zeroOrNegValue: [E.computeBreakEvenProb(0), E.computeBreakEvenProb(-0.5)],
          zeroBaselineRows: zeroBaselineRows,
          posBaselineRows: posBaselineRows
        };
        """,
        payload={
            "liveEnginePath": str(live_engine) if live_engine.is_file() else "",
            "inlineEngineCode": INLINE_REFERENCE_ENGINE_JS,
        },
    )

    assert tuple(out["levels"]) == THINKING_LEVELS
    assert out["zeroOrNegValue"] == [1.0, 1.0]

    for row in out["zeroBaselineRows"]:
        v = float(row["v"])
        expected_p = 1.0 / (1.0 + v)
        assert math.isclose(float(row["pStar"]), expected_p, rel_tol=1e-9, abs_tol=1e-9)
        assert abs(float(row["evAtStar"])) < 1e-9
        assert float(row["evAbove"]) > 0.0
        assert float(row["evBelow"]) < 0.0

    for row in out["posBaselineRows"]:
        v = float(row["v"])
        h = float(row["h"])
        baseline = max(0.0, h)
        expected_p = min(1.0, (1.0 + baseline) / (1.0 + v))
        assert math.isclose(float(row["fromNum"]), expected_p, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(float(row["fromObj"]), expected_p, rel_tol=1e-9, abs_tol=1e-9)
        if 0.0 < h < v:
            assert math.isclose(float(row["evAtThreshold"]), h, rel_tol=1e-9, abs_tol=1e-9)


def test_vm_contract_evaluate_call_hold_fire_vs_accuse_and_scoreboard() -> None:
    live_engine = _live_demo_dir() / "engine.js"
    cases = _inline_fixture_cases()
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        if (PAYLOAD.liveEnginePath) {
          env.runFile(PAYLOAD.liveEnginePath);
        } else {
          env.runCode(PAYLOAD.inlineEngineCode, "inline_engine.js");
        }
        const E = env.sandbox.window.OutThinkEngine;
        const ds = E.loadDataset({ cases: PAYLOAD.cases });
        const cHold = ds.byId["fixture-hold-1"];
        const cPin = ds.byId["fixture-accuse-2"];
        const cAmb = ds.byId["fixture-hold-3"];

        const holdOptimal = E.evaluateCall(cHold, { action: "hold_fire" });
        const holdAlias = E.evaluateCall(cHold, "wait");
        const luckyAccuse = E.evaluateCall(cHold, { action: "accuse", suspectId: "e04" });
        const wrongAccuse = E.evaluateCall(cHold, { action: "accuse", suspectId: "e07" });

        const pinOptimal = E.evaluateCall(cPin, { action: "accuse", suspectId: "e02" });
        const pinOverCautious = E.evaluateCall(cPin, { action: "hold_fire" });

        const sb = E.createScoreboard();
        sb.record(cHold.id, wrongAccuse, cHold);
        const sumAfterBad = sb.getSummary();

        sb.record(cHold.id, holdOptimal, cHold);
        sb.record(cPin.id, pinOptimal, cPin);
        sb.record(cAmb.id, E.evaluateCall(cAmb, { action: "hold-fire" }), cAmb);
        const sumFull = sb.getSummary();
        const allResults = sb.getAllResults();
        const resetSummary = sb.reset();

        return {
          count: ds.count,
          holdOptimal: holdOptimal,
          holdAlias: holdAlias,
          luckyAccuse: luckyAccuse,
          wrongAccuse: wrongAccuse,
          pinOptimal: pinOptimal,
          pinOverCautious: pinOverCautious,
          sumAfterBad: sumAfterBad,
          sumFull: sumFull,
          allCountBeforeReset: allResults.length,
          afterResetLookup: sb.getCaseResult(cHold.id),
          afterResetListLen: sb.getAllResults().length,
          resetSummary: resetSummary
        };
        """,
        payload={
            "liveEnginePath": str(live_engine) if live_engine.is_file() else "",
            "inlineEngineCode": INLINE_REFERENCE_ENGINE_JS,
            "cases": cases,
        },
    )

    assert out["count"] == 3

    assert out["holdOptimal"]["action"] == "hold_fire"
    assert out["holdOptimal"]["correct"] is True
    assert out["holdOptimal"]["optimal"] is True
    assert math.isclose(out["holdOptimal"]["score"], 0.49, abs_tol=1e-4)
    assert out["holdAlias"]["action"] == "hold_fire"
    assert math.isclose(out["holdAlias"]["score"], 0.49, abs_tol=1e-4)

    assert out["luckyAccuse"]["action"] == "accuse"
    assert out["luckyAccuse"]["correct"] is True
    assert out["luckyAccuse"]["optimal"] is False
    assert math.isclose(out["luckyAccuse"]["score"], 0.68, abs_tol=1e-4)

    assert out["wrongAccuse"]["action"] == "accuse"
    assert out["wrongAccuse"]["correct"] is False
    assert out["wrongAccuse"]["optimal"] is False
    assert math.isclose(out["wrongAccuse"]["score"], -1.0, abs_tol=1e-4)

    assert out["pinOptimal"]["action"] == "accuse"
    assert out["pinOptimal"]["correct"] is True
    assert out["pinOptimal"]["optimal"] is True
    assert math.isclose(out["pinOptimal"]["score"], 0.72, abs_tol=1e-4)

    assert out["pinOverCautious"]["action"] == "hold_fire"
    assert out["pinOverCautious"]["optimal"] is False
    assert math.isclose(out["pinOverCautious"]["score"], 0.60, abs_tol=1e-4)

    assert out["sumAfterBad"]["casesPlayed"] == 1
    assert math.isclose(out["sumAfterBad"]["judge"]["scoreSum"], -1.0, abs_tol=1e-4)

    full = out["sumFull"]
    assert full["casesPlayed"] == 3
    assert out["allCountBeforeReset"] == 3
    expected_judge_sum = round(0.49 + 0.72 + 0.61, 4)
    assert math.isclose(full["judge"]["scoreSum"], expected_judge_sum, abs_tol=1e-4)
    assert math.isclose(full["judge"]["meanScore"], round(expected_judge_sum / 3.0, 4), abs_tol=1e-4)
    assert full["judge"]["rightCount"] == 3
    assert full["judge"]["optimalCount"] == 3
    assert math.isclose(full["judge"]["accuracy"], 1.0, abs_tol=1e-4)
    assert math.isclose(full["judge"]["optimalRate"], 1.0, abs_tol=1e-4)
    assert full["judge"]["costUsd"] == 0

    for lv in THINKING_LEVELS:
        bucket = full["byLevel"][lv]
        assert bucket["count"] == 3
        assert math.isfinite(bucket["meanScore"])
        assert 0.0 <= bucket["accuracy"] <= 1.0
        assert bucket["totalCostUsd"] > 0.0
        assert bucket["totalThinkingTokens"] >= 0

    assert full["byLevel"]["minimal"]["accuracy"] == 0.0
    assert full["byLevel"]["minimal"]["judgeOutscoredCount"] == 3
    assert full["byLevel"]["xhigh"]["accuracy"] == 1.0

    rst = out["resetSummary"]
    assert rst["casesPlayed"] == 0
    assert rst["judge"]["scoreSum"] == 0
    assert rst["judge"]["meanScore"] == 0
    assert out["afterResetLookup"] is None
    assert out["afterResetListLen"] == 0
    for lv in THINKING_LEVELS:
        assert rst["byLevel"][lv]["count"] == 0


def _require_live_bundle() -> dict[str, Path]:
    demo_dir = _live_demo_dir()
    engine_js = demo_dir / "engine.js"
    if not engine_js.is_file():
        pytest.skip("demo/out-think-gemini/engine.js is not on disk")
    cases_js = demo_dir / "cases.js"
    annotations_js = demo_dir / "annotations.js"
    assert cases_js.is_file(), f"missing live cases.js at {cases_js}"
    assert annotations_js.is_file(), f"missing live annotations.js at {annotations_js}"
    return {
        "demo_dir": demo_dir,
        "cases_js": cases_js,
        "annotations_js": annotations_js,
        "engine_js": engine_js,
    }


def test_live_vm_loads_cases_annotations_and_engine_offline() -> None:
    paths = _require_live_bundle()
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        env.runFile(PAYLOAD.casesJs);
        env.runFile(PAYLOAD.annotationsJs);
        env.runFile(PAYLOAD.engineJs);

        const win = env.sandbox.window;
        const dsExplicit = win.OutThinkEngine.loadDataset(win.OUTTHINK_DATA);
        const dsAuto = win.OutThinkEngine.loadDataset();

        const annStore = win.OUTTHINK_ANNOTATIONS && win.OUTTHINK_ANNOTATIONS.episodes
          ? win.OUTTHINK_ANNOTATIONS.episodes
          : {};
        const sampleKey = Object.keys(annStore)[0] || "";
        const sampleLookup = sampleKey ? win.getOutthinkAnnotation(sampleKey) : null;

        const caseSummaries = dsExplicit.cases.map(function (c) {
          const suspectIds = (c.suspects || []).map(function (s) { return s.id; });
          const lvKeys = (c.thinking_levels || []).map(function (lv) { return lv.thinking_level; });
          return {
            id: c.id,
            tier: c.tier,
            seed: c.seed,
            decisionDay: c.decision_day,
            valueAtDecision: c.value_at_decision,
            suspectCount: suspectIds.length,
            moleInSuspects: suspectIds.indexOf(c.true_mole) >= 0,
            recommendedCall: c.solver ? c.solver.recommended_call : null,
            topProb: c.solver ? c.solver.top_prob : null,
            breakEvenProb: c.solver ? c.solver.break_even_prob : null,
            levelKeys: lvKeys,
            hasAllFiniteLevelScores: (c.thinking_levels || []).every(function (lv) {
              return Number.isFinite(lv.score) && Number.isFinite(lv.cost_usd) && lv.cost_usd >= 0;
            })
          };
        });

        return {
          hasOutthinkData: Boolean(win.OUTTHINK_DATA),
          hasOutthinkCases: Array.isArray(win.OUTTHINK_CASES),
          rawCasesLen: Array.isArray(win.OUTTHINK_CASES) ? win.OUTTHINK_CASES.length : -1,
          hasAnnotations: Boolean(win.OUTTHINK_ANNOTATIONS),
          hasGetAnnotationFn: typeof win.getOutthinkAnnotation === "function",
          annotationCount: Object.keys(annStore).length,
          sampleLookupMatched: Boolean(sampleLookup && sampleLookup.key === sampleKey),
          thinkingLevels: win.OutThinkEngine.THINKING_LEVELS,
          isBootstrapFallback: dsExplicit.isBootstrapFallback,
          isFallback: dsExplicit.isFallback,
          source: dsExplicit.source,
          count: dsExplicit.count,
          autoCount: dsAuto.count,
          caseSummaries: caseSummaries
        };
        """,
        payload={
            "casesJs": str(paths["cases_js"]),
            "annotationsJs": str(paths["annotations_js"]),
            "engineJs": str(paths["engine_js"]),
        },
    )

    assert out["hasOutthinkData"] is True
    assert out["hasOutthinkCases"] is True
    assert out["hasAnnotations"] is True
    assert out["hasGetAnnotationFn"] is True
    assert out["annotationCount"] >= 500
    assert out["sampleLookupMatched"] is True
    assert tuple(out["thinkingLevels"]) == THINKING_LEVELS

    assert out["isBootstrapFallback"] is False
    assert out["isFallback"] is False
    assert out["source"] == "data"
    assert out["count"] >= 8
    assert out["count"] == out["rawCasesLen"]
    assert out["autoCount"] == out["count"]

    seen_ids: set[str] = set()
    for item in out["caseSummaries"]:
        assert item["id"] and item["id"] not in seen_ids
        seen_ids.add(item["id"])
        assert item["tier"] in ("medium", "hard")
        assert isinstance(item["seed"], int)
        assert item["decisionDay"] >= 1
        assert 0.0 < float(item["valueAtDecision"]) <= 1.0
        assert item["suspectCount"] >= 2
        assert item["moleInSuspects"] is True
        assert item["recommendedCall"] in ("hold_fire", "accuse")
        assert 0.0 <= float(item["topProb"]) <= 1.0
        assert 0.0 < float(item["breakEvenProb"]) <= 1.0
        assert len(item["levelKeys"]) >= 2
        assert all(lv in THINKING_LEVELS for lv in item["levelKeys"])
        assert item["hasAllFiniteLevelScores"] is True


def test_live_vm_evaluate_call_every_case_hold_fire_and_accuse_across_levels() -> None:
    paths = _require_live_bundle()
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        env.runFile(PAYLOAD.casesJs);
        env.runFile(PAYLOAD.annotationsJs);
        env.runFile(PAYLOAD.engineJs);

        const E = env.sandbox.window.OutThinkEngine;
        const ds = E.loadDataset(env.sandbox.window.OUTTHINK_DATA);
        const levels = E.THINKING_LEVELS;
        const seenDatasetLevels = Object.create(null);

        const perCaseChecks = ds.cases.map(function (c) {
          const v = c.value_at_decision;
          const pZero = E.computeBreakEvenProb(v, 0);
          const holdRes = E.evaluateCall(c, { action: "hold_fire" });
          const moleRes = E.evaluateCall(c, { action: "accuse", suspectId: c.true_mole });
          const nonMole = (c.suspects || []).find(function (s) { return s.id !== c.true_mole; });
          const wrongRes = E.evaluateCall(c, {
            action: "accuse",
            suspectId: nonMole ? nonMole.id : "nonexistent_suspect"
          });

          const levelSweep = levels.map(function (lvName) {
            const recorded = (c.thinking_levels || []).find(function (r) {
              return r.thinking_level === lvName;
            });
            if (recorded) {
              seenDatasetLevels[lvName] = (seenDatasetLevels[lvName] || 0) + 1;
            }
            const callForLevel = recorded
              ? (recorded.call_at_t === "accuse"
                  ? { action: "accuse", suspectId: recorded.accused || c.true_mole }
                  : { action: "hold_fire" })
              : { action: "hold_fire" };
            const evHold = E.evaluateCall(c, { action: "hold_fire", level: lvName });
            const evAccuse = E.evaluateCall(c, {
              action: "accuse",
              suspectId: c.true_mole,
              level: lvName
            });
            const evReplay = E.evaluateCall(c, callForLevel);
            return {
              level: lvName,
              holdFinite: Number.isFinite(evHold.score) && evHold.action === "hold_fire",
              accuseFinite: Number.isFinite(evAccuse.score) && evAccuse.action === "accuse" && evAccuse.correct === true,
              replayFinite: Number.isFinite(evReplay.score) && typeof evReplay.verdictLabel === "string" && evReplay.verdictLabel.length > 0
            };
          });

          return {
            id: c.id,
            v: v,
            pZero: pZero,
            holdAction: holdRes.action,
            holdScore: holdRes.score,
            holdVerdict: holdRes.verdictLabel,
            moleScore: moleRes.score,
            moleCorrect: moleRes.correct,
            wrongScore: wrongRes.score,
            wrongCorrect: wrongRes.correct,
            wrongOptimal: wrongRes.optimal,
            levelComparisonsLen: holdRes.levelComparisons.length,
            levelSweep: levelSweep
          };
        });

        return {
          caseCount: ds.count,
          seenDatasetLevels: seenDatasetLevels,
          perCaseChecks: perCaseChecks
        };
        """,
        payload={
            "casesJs": str(paths["cases_js"]),
            "annotationsJs": str(paths["annotations_js"]),
            "engineJs": str(paths["engine_js"]),
        },
    )

    assert out["caseCount"] >= 8
    for row in out["perCaseChecks"]:
        v = float(row["v"])
        assert math.isclose(float(row["pZero"]), 1.0 / (1.0 + v), rel_tol=1e-9, abs_tol=1e-9)
        assert row["holdAction"] == "hold_fire"
        assert math.isfinite(float(row["holdScore"]))
        assert isinstance(row["holdVerdict"], str) and len(row["holdVerdict"]) > 0
        assert row["moleCorrect"] is True
        assert math.isclose(float(row["moleScore"]), round(v, 4), abs_tol=1e-4)
        assert row["wrongCorrect"] is False
        assert row["wrongOptimal"] is False
        assert math.isclose(float(row["wrongScore"]), -1.0, abs_tol=1e-4)
        assert row["levelComparisonsLen"] >= 2
        assert len(row["levelSweep"]) == len(THINKING_LEVELS)
        for lv_check in row["levelSweep"]:
            assert lv_check["level"] in THINKING_LEVELS
            assert lv_check["holdFinite"] is True
            assert lv_check["accuseFinite"] is True
            assert lv_check["replayFinite"] is True

    for lv in ("low", "medium", "high"):
        assert out["seenDatasetLevels"].get(lv, 0) >= 1


def test_live_vm_scoreboard_records_all_cases_and_resets_cleanly() -> None:
    paths = _require_live_bundle()
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        env.runFile(PAYLOAD.casesJs);
        env.runFile(PAYLOAD.annotationsJs);
        env.runFile(PAYLOAD.engineJs);

        const E = env.sandbox.window.OutThinkEngine;
        const ds = E.loadDataset(env.sandbox.window.OUTTHINK_DATA);
        const sb = E.createScoreboard();

        for (let i = 0; i < ds.cases.length; i += 1) {
          const c = ds.cases[i];
          const rec = c.solver && c.solver.recommended_call === "accuse"
            ? { action: "accuse", suspectId: c.solver.top_suspect || c.true_mole }
            : { action: "hold_fire" };
          const ev = E.evaluateCall(c, rec);
          sb.record(c.id, ev, c);
        }

        const summary = sb.getSummary();
        const allBeforeReset = sb.getAllResults().length;
        const firstId = ds.cases[0].id;
        const hadFirstBeforeReset = Boolean(sb.getCaseResult(firstId));
        const resetSummary = sb.reset();

        return {
          datasetCount: ds.count,
          summary: summary,
          allBeforeReset: allBeforeReset,
          hadFirstBeforeReset: hadFirstBeforeReset,
          afterResetFirst: sb.getCaseResult(firstId),
          afterResetAllLen: sb.getAllResults().length,
          resetSummary: resetSummary
        };
        """,
        payload={
            "casesJs": str(paths["cases_js"]),
            "annotationsJs": str(paths["annotations_js"]),
            "engineJs": str(paths["engine_js"]),
        },
    )

    summary = out["summary"]
    assert summary["casesPlayed"] == out["datasetCount"]
    assert out["allBeforeReset"] == out["datasetCount"]
    assert out["hadFirstBeforeReset"] is True

    judge = summary["judge"]
    assert math.isfinite(float(judge["scoreSum"]))
    assert math.isfinite(float(judge["meanScore"]))
    assert 0.0 <= float(judge["accuracy"]) <= 1.0
    assert math.isclose(float(judge["optimalRate"]), 1.0, abs_tol=1e-4)
    assert judge["costUsd"] == 0

    solver = summary["solver"]
    assert math.isfinite(float(solver["scoreSum"]))
    assert math.isfinite(float(solver["meanScore"]))
    assert 0.0 <= float(solver["accuracy"]) <= 1.0

    by_level = summary["byLevel"]
    total_level_runs = 0
    for lv in THINKING_LEVELS:
        assert lv in by_level
        bucket = by_level[lv]
        total_level_runs += int(bucket["count"])
        assert math.isfinite(float(bucket["scoreSum"]))
        assert math.isfinite(float(bucket["meanScore"]))
        assert 0.0 <= float(bucket["accuracy"]) <= 1.0
        assert math.isfinite(float(bucket["totalCostUsd"])) and float(bucket["totalCostUsd"]) >= 0.0
        assert int(bucket["totalThinkingTokens"]) >= 0
        assert 0 <= int(bucket["judgeOutscoredCount"]) <= int(bucket["count"])

    assert total_level_runs >= out["datasetCount"] * 2

    rst = out["resetSummary"]
    assert rst["casesPlayed"] == 0
    assert rst["judge"]["meanScore"] == 0
    assert rst["judge"]["accuracy"] == 0
    assert out["afterResetFirst"] is None
    assert out["afterResetAllLen"] == 0
    for lv in THINKING_LEVELS:
        assert rst["byLevel"][lv]["count"] == 0
        assert rst["byLevel"][lv]["meanScore"] == 0


def test_live_vm_full_index_html_playable_flow_offline() -> None:
    paths = _require_live_bundle()
    demo_dir = paths["demo_dir"]
    index_html = demo_dir / "index.html"
    game_js = demo_dir / "game.js"
    if not index_html.is_file() or not game_js.is_file():
        pytest.skip("demo/out-think-gemini/index.html or game.js not on disk")

    html_text = index_html.read_text(encoding="utf-8")
    script_srcs = re.findall(r'<script\s+[^>]*src=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE)
    local_scripts: list[str] = []
    for src in script_srcs:
        if src.startswith(("http://", "https://", "//")):
            continue
        candidate = (demo_dir / src).resolve()
        if candidate.is_file():
            local_scripts.append(str(candidate))

    assert any(Path(p).name == "cases.js" for p in local_scripts)
    assert any(Path(p).name == "annotations.js" for p in local_scripts)
    assert any(Path(p).name == "engine.js" for p in local_scripts)
    assert any(Path(p).name == "game.js" for p in local_scripts)

    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        for (let i = 0; i < PAYLOAD.scripts.length; i += 1) {
          env.runFile(PAYLOAD.scripts[i]);
        }

        const doc = env.document;
        const caseSelect = doc.getElementById("case-select");
        const revealPanel = doc.getElementById("reveal-panel");
        const scoreboardBar = doc.getElementById("scoreboard-bar");
        const btnHold = doc.getElementById("btn-hold-fire");
        const btnAccuse = doc.getElementById("btn-accuse");
        const btnNext = doc.getElementById("btn-next-case");
        const btnReset = doc.getElementById("btn-reset-scores");
        const stage = doc.getElementById("phaser-stage");

        const initialTitle = doc.getElementById("case-title").textContent;
        const initialRevealHidden = revealPanel.hidden;
        const initialOptionsCount = caseSelect.children.length;

        btnHold.click();
        const afterHoldHidden = revealPanel.hidden;
        const afterHoldRevealText = revealPanel.textContent;
        const afterHoldScoreboard = scoreboardBar.textContent;

        btnNext.click();
        const secondCaseTitle = doc.getElementById("case-title").textContent;
        const secondPreDecisionHidden = revealPanel.hidden;

        btnAccuse.click();
        const afterAccuseHidden = revealPanel.hidden;
        const afterTwoCallsScoreboard = scoreboardBar.textContent;

        btnReset.click();
        const afterResetHidden = revealPanel.hidden;
        const afterResetScoreboard = scoreboardBar.textContent;

        return {
          initialTitle: initialTitle,
          initialRevealHidden: initialRevealHidden,
          initialOptionsCount: initialOptionsCount,
          afterHoldHidden: afterHoldHidden,
          afterHoldHasVerdict: afterHoldRevealText.length > 20,
          afterHoldScoreboard: afterHoldScoreboard,
          secondCaseTitle: secondCaseTitle,
          secondPreDecisionHidden: secondPreDecisionHidden,
          afterAccuseHidden: afterAccuseHidden,
          afterTwoCallsScoreboard: afterTwoCallsScoreboard,
          afterResetHidden: afterResetHidden,
          afterResetScoreboard: afterResetScoreboard,
          stageChildren: stage.children.length,
          drawCalls: env.drawStats.calls
        };
        """,
        payload={"scripts": local_scripts},
    )

    assert out["initialOptionsCount"] >= 8
    assert out["initialTitle"] and out["initialTitle"] != "Loading Scenario..."
    assert out["initialRevealHidden"] is True

    assert out["afterHoldHidden"] is False
    assert out["afterHoldHasVerdict"] is True
    assert f"1/{out['initialOptionsCount']}" in out["afterHoldScoreboard"]

    assert out["secondCaseTitle"] != out["initialTitle"]
    assert out["secondPreDecisionHidden"] is True

    assert out["afterAccuseHidden"] is False
    assert f"2/{out['initialOptionsCount']}" in out["afterTwoCallsScoreboard"]

    assert out["afterResetHidden"] is True
    assert f"0/{out['initialOptionsCount']}" in out["afterResetScoreboard"]

    if (demo_dir / "scene.js").is_file():
        assert out["stageChildren"] >= 1
        assert out["drawCalls"] > 0


def test_vm_contract_pre_decision_cutoff_and_bootstrap_resilience() -> None:
    live_engine = _live_demo_dir() / "engine.js"
    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        if (PAYLOAD.liveEnginePath) {
          env.runFile(PAYLOAD.liveEnginePath);
        } else {
          env.runCode(PAYLOAD.inlineEngineCode, "inline_engine.js");
        }
        const E = env.sandbox.window.OutThinkEngine;
        const emptyBoot = E.loadDataset({});

        const rawCase = {
          id: "cutoff-audit-case",
          title: "Cutoff Isolation Audit",
          tier: "hard",
          seed: 22,
          decision_day: 6,
          decision_step: 15,
          value_at_decision: 0.70,
          true_mole: "e02",
          suspects: [
            { id: "e01", name: "Ari Salo", eliminated: false },
            { id: "e02", name: "Mina Laine", eliminated: false }
          ],
          leaks: [
            { day: 4, doc_id: "d1", summary: "observed pre-decision leak" },
            { day: 9, doc_id: "d9", summary: "future leak after decision point" }
          ],
          tool_steps: [
            { t: 5, day: 3, tool: "plant_canary", summary: "early canary" },
            { t: 15, day: 6, tool: "check_leak_feed", summary: "decision turn check" },
            { t: 22, day: 8, tool: "accuse", summary: "post-decision step" }
          ],
          solver: {
            top_suspect: "e02",
            top_prob: 0.52,
            break_even_prob: E.computeBreakEvenProb(0.70, 0),
            ev_hold_fire: 0.55,
            recommended_call: "hold_fire",
            final_score: 0.62,
            correct: true
          },
          thinking_levels: []
        };

        const ds = E.loadDataset({ cases: [rawCase] });
        const c = ds.cases[0];
        const preLeaks = (c.leaks || []).filter(function (lk) { return lk.day <= c.decision_day; });
        const preSteps = (c.tool_steps || []).filter(function (st) {
          return st.day <= c.decision_day && st.t <= c.decision_step;
        });

        return {
          hasLiveEngine: Boolean(PAYLOAD.liveEnginePath),
          emptyBootIsBootstrap: Boolean(emptyBoot.isBootstrapFallback),
          emptyBootCount: emptyBoot.count,
          preLeaksCount: preLeaks.length,
          preStepsCount: preSteps.length,
          holdEval: E.evaluateCall(c, { action: "hold_fire" }),
          accuseEval: E.evaluateCall(c, { action: "accuse", suspectId: "e02" })
        };
        """,
        payload={
            "liveEnginePath": str(live_engine) if live_engine.is_file() else "",
            "inlineEngineCode": INLINE_REFERENCE_ENGINE_JS,
        },
    )

    if out["hasLiveEngine"]:
        assert out["emptyBootIsBootstrap"] is True
        assert out["emptyBootCount"] >= 1
    assert out["preLeaksCount"] == 1
    assert out["preStepsCount"] == 2
    assert out["holdEval"]["optimal"] is True
    assert math.isclose(float(out["holdEval"]["score"]), 0.55, abs_tol=1e-4)
    assert out["accuseEval"]["correct"] is True
    assert out["accuseEval"]["optimal"] is False


def test_live_vm_all_cases_pre_decision_spoiler_isolation_and_pod_locks() -> None:
    paths = _require_live_bundle()
    demo_dir = paths["demo_dir"]
    index_html = demo_dir / "index.html"
    game_js = demo_dir / "game.js"
    if not index_html.is_file() or not game_js.is_file():
        pytest.skip("demo/out-think-gemini/index.html or game.js not on disk")

    html_text = index_html.read_text(encoding="utf-8")
    script_srcs = re.findall(r'<script\s+[^>]*src=["\']([^"\']+)["\']', html_text, flags=re.IGNORECASE)
    local_scripts = [
        str((demo_dir / src).resolve())
        for src in script_srcs
        if not src.startswith(("http://", "https://", "//")) and (demo_dir / src).resolve().is_file()
    ]

    out = _run_vm_script(
        r"""
        const env = createDomSandbox();
        for (let i = 0; i < PAYLOAD.scripts.length; i += 1) {
          env.runFile(PAYLOAD.scripts[i]);
        }

        const doc = env.document;
        const caseSelect = doc.getElementById("case-select");
        const btnNext = doc.getElementById("btn-next-case");
        const btnHold = doc.getElementById("btn-hold-fire");
        const roster = doc.getElementById("suspect-roster");
        const reveal = doc.getElementById("reveal-panel");
        const tabsWrap = doc.getElementById("evidence-tabs");
        const evidenceList = doc.getElementById("evidence-list");
        const total = caseSelect.children.length;

        const preDecisionChecks = [];
        for (let idx = 0; idx < total; idx += 1) {
          env.drawStats.lastTexts.length = 0;
          if (idx > 0) {
            btnNext.click();
          }
          const tabBtns = tabsWrap.querySelectorAll("[data-tab]");
          const tabLengths = [];
          for (let t = 0; t < tabBtns.length; t += 1) {
            tabBtns[t].click();
            tabLengths.push(evidenceList.textContent.length);
          }
          const canvasTexts = env.drawStats.lastTexts.slice();
          preDecisionChecks.push({
            idx: idx,
            revealHidden: reveal.hidden,
            revealEmpty: reveal.textContent === "",
            rosterHasMoleBadge: roster.textContent.indexOf("MOLE") >= 0,
            tabsCount: tabBtns.length,
            anyTabRendered: tabLengths.some(function (n) { return n > 0; }),
            podVerdictLeakedOnCanvas: canvasTexts.some(function (txt) {
              return txt === "RIGHT" || txt === "WRONG";
            })
          });
        }

        btnHold.click();
        const postDecisionRosterHasMole = roster.textContent.indexOf("MOLE") >= 0;
        const postDecisionRevealHidden = reveal.hidden;

        return {
          total: total,
          preDecisionChecks: preDecisionChecks,
          postDecisionRosterHasMole: postDecisionRosterHasMole,
          postDecisionRevealHidden: postDecisionRevealHidden
        };
        """,
        payload={"scripts": local_scripts},
    )

    assert out["total"] >= 8
    for chk in out["preDecisionChecks"]:
        assert chk["revealHidden"] is True
        assert chk["revealEmpty"] is True
        assert chk["rosterHasMoleBadge"] is False
        assert chk["tabsCount"] == 5
        assert chk["anyTabRendered"] is True
        assert chk["podVerdictLeakedOnCanvas"] is False

    assert out["postDecisionRevealHidden"] is False
    assert out["postDecisionRosterHasMole"] is True

