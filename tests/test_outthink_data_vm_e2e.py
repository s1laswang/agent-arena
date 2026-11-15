from __future__ import annotations

import ast
import io
import json
import os
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
CASES_JS_PATH = DEMO_DIR / "cases.js"
JSON_PATH = ROOT / "results" / "gemini" / "out_think_gemini.json"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
HASH_CHAR = chr(35)
FORBIDDEN_NET = "fetch" + "("
SLASH = chr(47)
STAR = chr(42)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR

EXPECTED_CASE_IDS = [
    "carbon-hard-1",
    "flash-lite-hard-4",
    "flash38-hard-7",
    "carbon-medium-4",
    "flash-lite-medium-1",
    "hydrogen-hard-3",
    "flash38-medium-9",
    "flash35-hard-1",
    "argon-hard-18",
    "argon-medium-6",
    "hydrogen-medium-2",
    "flash35-medium-8",
]

EXPECTED_WORLD_PAIRS = [
    "hard:1",
    "hard:18",
    "hard:3",
    "hard:4",
    "hard:7",
    "medium:1",
    "medium:2",
    "medium:4",
    "medium:6",
    "medium:8",
    "medium:9",
]


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
    for cand in (
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
    ):
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env
    pytest.skip("no JavaScript runtime available")


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
            if ch == "[":
                in_regex_class = True
            elif ch == "]":
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
            if prev_sig in ("(", ",", "=", ":", "[", "!", "&", "|", "?", "{", "}", ";"):
                in_regex = True
                i += 1
                continue
        prev_sig = ch
        i += 1
    return hits


VM_HARNESS_JS = r"""
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const demoDir = process.env.OUTTHINK_DEMO_DIR;

const VALID_TOOLS = new Set([
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
  "accuse"
]);

function round4(n) {
  return Math.round(Number(n) * 10000) / 10000;
}

function round6(n) {
  return Math.round(Number(n) * 1000000) / 1000000;
}

function fallbackEvaluateCall(c, call) {
  const slv = c.solver || {};
  const val = Number(c.value_at_decision);
  const mole = String(c.true_mole);
  const topProb = Number(slv.top_prob || 0);
  const beProb = Number(slv.break_even_prob || (1 / (1 + val)));
  const rec = String(slv.recommended_call || "hold_fire");
  const action = call && call.action === "accuse" ? "accuse" : "hold_fire";
  const suspectId = call && call.suspectId ? String(call.suspectId) : null;
  if (action === "accuse") {
    const correct = Boolean(suspectId && suspectId === mole);
    const optimal = Boolean(correct && (rec !== "hold_fire" || topProb >= beProb));
    const score = correct ? round4(val) : -1;
    const verdictLabel = correct && optimal
      ? "OPTIMAL ACCUSATION"
      : correct
      ? "LUCKY GUESS (BELOW BREAK-EVEN)"
      : "FALSE ACCUSATION (-1.00)";
    return { action, suspectId, correct, optimal, score, verdictLabel, trueMole: mole };
  }
  const correct = Boolean(rec === "hold_fire" || topProb < 0.95);
  const optimal = Boolean(rec === "hold_fire");
  let score = 0;
  let verdictLabel = optimal ? "OPTIMAL HOLD FIRE" : "CAUTIOUS HOLD FIRE";
  if (topProb >= 0.98 && rec !== "hold_fire") {
    score = round4(Math.max(0, val - 0.12));
    verdictLabel = "OVER-CAUTIOUS DELAY";
  } else {
    const rawHold = slv.ev_hold_fire !== undefined && slv.ev_hold_fire !== null
      ? slv.ev_hold_fire
      : slv.final_score || 0;
    score = round4(Number(rawHold));
  }
  return { action: "hold_fire", suspectId: null, correct, optimal, score, verdictLabel, trueMole: mole };
}

function fallbackSummarize(records) {
  const levels = ["minimal", "low", "medium", "high", "xhigh"];
  const byLevel = {};
  for (const lk of levels) {
    byLevel[lk] = {
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
  let judgeScoreSum = 0;
  let judgeRight = 0;
  let judgeOptimal = 0;
  let solverScoreSum = 0;
  let solverRight = 0;
  for (const r of records) {
    const jScore = Number(r.evalRes.score);
    judgeScoreSum += jScore;
    if (r.evalRes.correct) judgeRight += 1;
    if (r.evalRes.optimal) judgeOptimal += 1;
    const slv = r.caseObj.solver || {};
    solverScoreSum += Number(slv.final_score || 0);
    if (slv.correct) solverRight += 1;
    for (const lv of r.caseObj.thinking_levels || []) {
      const b = byLevel[lv.thinking_level];
      const lvScore = Number(lv.score);
      b.count += 1;
      b.scoreSum += lvScore;
      if (lv.correct) b.rightCount += 1;
      b.totalCostUsd += Number(lv.cost_usd);
      b.totalThinkingTokens += Number(lv.thinking_tokens);
      if (jScore > lvScore) b.judgeOutscoredCount += 1;
    }
  }
  const n = records.length;
  for (const lk of levels) {
    const b = byLevel[lk];
    b.scoreSum = round4(b.scoreSum);
    b.meanScore = b.count > 0 ? round4(b.scoreSum / b.count) : 0;
    b.accuracy = b.count > 0 ? round4(b.rightCount / b.count) : 0;
    b.totalCostUsd = round6(b.totalCostUsd);
    b.totalThinkingTokens = Math.round(b.totalThinkingTokens);
  }
  return {
    casesPlayed: n,
    judge: {
      scoreSum: round4(judgeScoreSum),
      meanScore: n > 0 ? round4(judgeScoreSum / n) : 0,
      rightCount: judgeRight,
      optimalCount: judgeOptimal,
      accuracy: n > 0 ? round4(judgeRight / n) : 0,
      optimalRate: n > 0 ? round4(judgeOptimal / n) : 0,
      costUsd: 0
    },
    solver: {
      scoreSum: round4(solverScoreSum),
      meanScore: n > 0 ? round4(solverScoreSum / n) : 0,
      rightCount: solverRight,
      accuracy: n > 0 ? round4(solverRight / n) : 0
    },
    byLevel
  };
}

function createMockDom() {
  const elementsById = new Map();
  function makeClassList(el) {
    const set = new Set();
    return {
      syncFrom(cn) {
        set.clear();
        String(cn || "").split(/\s+/).filter(Boolean).forEach((c) => set.add(c));
      },
      syncTo() {
        el._className = Array.from(set).join(" ");
      },
      add(...cls) {
        cls.filter(Boolean).forEach((c) => set.add(c));
        this.syncTo();
      },
      remove(...cls) {
        cls.forEach((c) => set.delete(c));
        this.syncTo();
      },
      toggle(c, force) {
        const next = force !== undefined ? Boolean(force) : !set.has(c);
        if (next) set.add(c);
        else set.delete(c);
        this.syncTo();
        return next;
      },
      contains(c) {
        return set.has(c);
      }
    };
  }
  function makeCanvasCtx() {
    const ops = [];
    return {
      ops,
      fillStyle: "rgb(0,0,0)",
      strokeStyle: "rgb(0,0,0)",
      lineWidth: 1,
      font: "10px monospace",
      textAlign: "left",
      textBaseline: "alphabetic",
      globalAlpha: 1,
      imageSmoothingEnabled: false,
      fillRect(x, y, w, h) { ops.push(["fillRect", x, y, w, h]); },
      strokeRect(x, y, w, h) { ops.push(["strokeRect", x, y, w, h]); },
      clearRect(x, y, w, h) { ops.push(["clearRect", x, y, w, h]); },
      fillText(t, x, y) { ops.push(["fillText", String(t), x, y]); },
      beginPath() {},
      closePath() {},
      moveTo() {},
      lineTo() {},
      arc() {},
      fill() {},
      stroke() {},
      save() {},
      restore() {},
      translate() {},
      scale() {},
      drawImage() {},
      measureText(t) { return { width: String(t || "").length * 6 }; }
    };
  }
  function createElement(tag, id) {
    const listeners = {};
    const attrs = {};
    const el = {
      tagName: String(tag || "div").toUpperCase(),
      id: id || "",
      _className: "",
      _textContent: "",
      value: "",
      type: "",
      hidden: false,
      disabled: false,
      selected: false,
      width: 0,
      height: 0,
      style: { cssText: "", cursor: "default" },
      parentNode: null,
      children: [],
      get firstChild() {
        return this.children.length > 0 ? this.children[0] : null;
      },
      get className() {
        return this._className;
      },
      set className(v) {
        this._className = String(v || "");
        this.classList.syncFrom(this._className);
      },
      get textContent() {
        if (this.children.length === 0) return this._textContent;
        return this._textContent + this.children.map((c) => c.textContent).join("");
      },
      set textContent(v) {
        this.children = [];
        this._textContent = v == null ? "" : String(v);
      },
      appendChild(child) {
        if (!child) return child;
        if (child.parentNode) {
          const idx = child.parentNode.children.indexOf(child);
          if (idx >= 0) child.parentNode.children.splice(idx, 1);
        }
        child.parentNode = this;
        this.children.push(child);
        if (child.id) elementsById.set(child.id, child);
        if (this.tagName === "SELECT" && (child.selected || this.children.length === 1)) {
          this.value = child.value;
        }
        return child;
      },
      removeChild(child) {
        const idx = this.children.indexOf(child);
        if (idx >= 0) {
          this.children.splice(idx, 1);
          child.parentNode = null;
        }
        return child;
      },
      setAttribute(k, v) {
        attrs[k] = String(v);
        if (k === "id") {
          this.id = String(v);
          elementsById.set(this.id, this);
        }
      },
      getAttribute(k) {
        return Object.prototype.hasOwnProperty.call(attrs, k) ? attrs[k] : null;
      },
      addEventListener(type, fn) {
        if (!listeners[type]) listeners[type] = [];
        listeners[type].push(fn);
      },
      removeEventListener(type, fn) {
        if (!listeners[type]) return;
        listeners[type] = listeners[type].filter((f) => f !== fn);
      },
      dispatchEvent(ev) {
        const e = Object.assign({ target: this }, ev || {});
        for (const fn of (listeners[e.type] || []).slice()) fn.call(this, e);
      },
      click() {
        if (!this.disabled) this.dispatchEvent({ type: "click", target: this });
      },
      closest(selector) {
        const m = selector.match(/^\[([a-zA-Z0-9_-]+)\]$/);
        let cur = this;
        while (cur) {
          if (m && cur.getAttribute(m[1]) !== null) return cur;
          cur = cur.parentNode;
        }
        return null;
      },
      querySelectorAll(selector) {
        const out = [];
        const m = selector.match(/^\[([a-zA-Z0-9_-]+)\]$/);
        const cls = selector.startsWith(".") ? selector.slice(1) : null;
        function walk(node) {
          for (const ch of node.children) {
            if (m && ch.getAttribute(m[1]) !== null) out.push(ch);
            else if (cls && ch.classList.contains(cls)) out.push(ch);
            walk(ch);
          }
        }
        walk(this);
        return out;
      },
      scrollIntoView() {},
      getBoundingClientRect() {
        return { left: 0, top: 0, width: this.width || 960, height: this.height || 520 };
      },
      getContext(kind) {
        if (kind === "2d") {
          if (!this._ctx2d) this._ctx2d = makeCanvasCtx();
          return this._ctx2d;
        }
        return null;
      }
    };
    el.classList = makeClassList(el);
    if (id) elementsById.set(id, el);
    return el;
  }
  const ids = [
    "phaser-stage", "stage-fallback", "dataset-badge", "case-select",
    "btn-prev-case", "btn-next-case", "btn-reset-scores", "scoreboard-bar",
    "case-tier-badge", "case-title", "case-company", "case-seed-badge",
    "case-day-badge", "case-step-badge", "case-reward-badge", "case-status-pill",
    "btn-highlight-suspects", "highlight-summary", "suspect-roster",
    "dossier-clearance", "dossier-card", "btn-accuse", "btn-hold-fire",
    "btn-filter-suspect", "evidence-cutoff-note", "evidence-tabs",
    "evidence-list", "reveal-panel", "provenance-summary", "asset-credits-list",
    "count-canaries", "count-leaks", "count-access", "count-comms", "count-steps"
  ];
  for (const id of ids) {
    createElement(id === "case-select" ? "select" : "div", id);
  }
  const tabsEl = elementsById.get("evidence-tabs");
  for (const t of ["canaries", "leaks", "access", "comms", "steps"]) {
    const b = createElement("button");
    b.setAttribute("data-tab", t);
    tabsEl.appendChild(b);
  }
  return {
    elementsById,
    document: {
      readyState: "complete",
      createElement: (tag) => createElement(tag),
      getElementById: (id) => elementsById.get(id) || null,
      addEventListener() {}
    }
  };
}

const { document, elementsById } = createMockDom();
const sandbox = {
  console,
  Date,
  Math,
  Number,
  String,
  Boolean,
  Array,
  Object,
  JSON,
  Set,
  Map,
  RegExp,
  Error,
  TypeError,
  parseInt,
  parseFloat,
  isNaN,
  isFinite,
  performance: { now: () => 1000 },
  requestAnimationFrame: () => 1,
  cancelAnimationFrame: () => {},
  document
};
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;
vm.createContext(sandbox);

const scriptOrder = [
  ["assets/manifest.js", false],
  ["fallback_cases.js", false],
  ["cases.js", true],
  ["annotations.js", false],
  ["personas.js", false],
  ["chatter.js", false],
  ["engine.js", false],
  ["scene.js", false],
  ["game.js", false]
];

const loadedScripts = [];
const issues = [];

for (const [relPath, required] of scriptOrder) {
  const fullPath = path.join(demoDir, relPath);
  if (fs.existsSync(fullPath)) {
    vm.runInContext(fs.readFileSync(fullPath, "utf8"), sandbox, { filename: relPath });
    loadedScripts.push(relPath);
  } else if (required) {
    issues.push("missing required script: " + relPath);
  }
}

const rawData = sandbox.window.OUTTHINK_DATA;
const rawCases = sandbox.window.OUTTHINK_CASES;
if (!rawData || !Array.isArray(rawCases) || rawData.cases !== rawCases) {
  issues.push("window.OUTTHINK_DATA or window.OUTTHINK_CASES missing in browser vm");
}

let rawLevelCount = 0;
for (const rc of rawCases || []) {
  const suspectSet = new Set((rc.suspects || []).map((s) => s.id));
  if (!rc.true_mole || !suspectSet.has(rc.true_mole)) {
    issues.push("true_mole not in suspects on " + rc.id);
  }
  for (const lk of rc.leaks || []) {
    if (!(lk.day <= rc.decision_day) || !lk.doc_id || !lk.summary) {
      issues.push("invalid leak on " + rc.id);
    }
    if (lk.t !== undefined && lk.t !== null && !(lk.t < rc.decision_step)) {
      issues.push("post-decision leak t on " + rc.id);
    }
  }
  for (const can of rc.canaries || []) {
    if (!(can.day_planted <= rc.decision_day) || !Array.isArray(can.variants) || can.variants.length === 0) {
      issues.push("invalid canary on " + rc.id);
    }
    if (can.t !== undefined && can.t !== null && !(can.t < rc.decision_step)) {
      issues.push("post-decision canary t on " + rc.id);
    }
  }
  for (const al of rc.access_logs || []) {
    if (!(al.day <= rc.decision_day) || !al.employee || !al.doc_id) {
      issues.push("invalid access_log on " + rc.id);
    }
    if (al.t !== undefined && al.t !== null && !(al.t < rc.decision_step)) {
      issues.push("post-decision access_log t on " + rc.id);
    }
  }
  for (const cm of rc.comms || []) {
    if (!(cm.day <= rc.decision_day) || !cm.text || cm.text.trim().length === 0) {
      issues.push("invalid comm on " + rc.id);
    }
    if (cm.t !== undefined && cm.t !== null && !(cm.t < rc.decision_step)) {
      issues.push("post-decision comm t on " + rc.id);
    }
  }
  for (const st of rc.tool_steps || []) {
    if (
      !VALID_TOOLS.has(st.tool) ||
      st.tool === "accuse" ||
      !(st.t < rc.decision_step) ||
      !(st.day <= rc.decision_day) ||
      !st.summary
    ) {
      issues.push("invalid raw tool_step on " + rc.id);
    }
  }
  if (!Array.isArray(rc.cross_model_carbon) || rc.cross_model_carbon.length === 0) {
    issues.push("missing cross_model_carbon on " + rc.id);
  }
  for (const lv of rc.thinking_levels || []) {
    rawLevelCount += 1;
    if (!lv.analyst_quote || !lv.source_file || typeof lv.regret_total !== "number") {
      issues.push("missing inline forensic fields on " + rc.id + "/" + lv.thinking_level);
    }
    if (!lv.correct && !lv.failure_tag) {
      issues.push("missing inline failure_tag on wrong run " + rc.id + "/" + lv.thinking_level);
    }
  }
}

const Engine = sandbox.window.OutThinkEngine || null;
const ds = Engine
  ? Engine.loadDataset()
  : {
      source: "data",
      isFallback: false,
      isBootstrapFallback: Boolean(rawData && rawData.meta && rawData.meta.isBootstrapFallback),
      count: rawCases.length,
      cases: rawCases,
      meta: Object.assign({}, rawData.meta, { source: "data", count: rawCases.length })
    };

let annotationsMatched = 0;
if (typeof sandbox.window.getOutthinkAnnotation === "function") {
  for (const c of ds.cases) {
    for (const lv of c.thinking_levels) {
      const hit = sandbox.window.getOutthinkAnnotation({
        model: lv.model,
        level: lv.thinking_level,
        tier: c.tier,
        seed: c.seed
      });
      if (hit) annotationsMatched += 1;
    }
  }
}

const evalFn = Engine ? (c, call) => Engine.evaluateCall(c, call) : fallbackEvaluateCall;
const verdictsSeen = new Set();
const strategies = {
  optimal: { records: [], sb: Engine ? Engine.createScoreboard() : null },
  wrongAccuse: { records: [], sb: Engine ? Engine.createScoreboard() : null },
  oppositeSolver: { records: [], sb: Engine ? Engine.createScoreboard() : null },
  alwaysAccuseMole: { records: [], sb: Engine ? Engine.createScoreboard() : null },
  alwaysHoldFire: { records: [], sb: Engine ? Engine.createScoreboard() : null }
};

for (const c of ds.cases) {
  const suspectIds = c.suspects.map((s) => s.id);
  const wrongId = suspectIds.find((id) => id !== c.true_mole);
  const rec = c.solver.recommended_call;

  const callsByStrategy = {
    optimal: rec === "accuse" ? { action: "accuse", suspectId: c.true_mole } : { action: "hold_fire" },
    wrongAccuse: { action: "accuse", suspectId: wrongId },
    oppositeSolver: rec === "accuse" ? { action: "hold_fire" } : { action: "accuse", suspectId: c.solver.top_suspect },
    alwaysAccuseMole: { action: "accuse", suspectId: c.true_mole },
    alwaysHoldFire: { action: "hold_fire" }
  };

  for (const [k, callObj] of Object.entries(callsByStrategy)) {
    const evRes = evalFn(c, callObj);
    verdictsSeen.add(evRes.verdictLabel);
    strategies[k].records.push({ caseObj: c, evalRes: evRes });
    if (strategies[k].sb) {
      strategies[k].sb.record(c.id, evRes, c);
    }
  }
}

const summaries = {};
for (const [k, stObj] of Object.entries(strategies)) {
  summaries[k] = stObj.sb ? stObj.sb.getSummary() : fallbackSummarize(stObj.records);
}

let uiCheck = null;
const hasFullUi =
  loadedScripts.includes("engine.js") &&
  loadedScripts.includes("scene.js") &&
  loadedScripts.includes("game.js");

if (hasFullUi) {
  let lvCards = 0;
  let carbonStrips = 0;
  for (let i = 0; i < ds.cases.length; i += 1) {
    const sel = elementsById.get("case-select");
    sel.value = String(i);
    sel.dispatchEvent({ type: "change" });
    for (const tabBtn of elementsById.get("evidence-tabs").children) {
      elementsById.get("evidence-tabs").dispatchEvent({ type: "click", target: tabBtn });
    }
    const c = ds.cases[i];
    if (c.solver.recommended_call === "accuse") {
      const chip = elementsById
        .get("suspect-roster")
        .children.find((b) => b.textContent.startsWith(c.true_mole + " "));
      if (chip) chip.click();
      elementsById.get("btn-accuse").click();
    } else {
      elementsById.get("btn-hold-fire").click();
    }
    const rev = elementsById.get("reveal-panel");
    lvCards += rev.querySelectorAll("[data-level-key]").length;
    if (rev.querySelectorAll(".carbon-strip").length > 0) carbonStrips += 1;
  }
  const stageCanvas = elementsById.get("phaser-stage").children[0];
  const sbTextBeforeReset = elementsById.get("scoreboard-bar").textContent;
  elementsById.get("btn-reset-scores").click();
  uiCheck = {
    canvasDrawOps: stageCanvas && stageCanvas._ctx2d ? stageCanvas._ctx2d.ops.length : 0,
    datasetBadge: elementsById.get("dataset-badge").textContent,
    provenanceText: elementsById.get("provenance-summary").textContent,
    lvCards,
    carbonStrips,
    sbTextBeforeReset,
    sbTextAfterReset: elementsById.get("scoreboard-bar").textContent
  };
}

process.stdout.write(JSON.stringify({
  issues,
  loadedScripts,
  usedEngine: Boolean(Engine),
  rawLevelCount,
  annotationsMatched,
  source: ds.source,
  isFallback: ds.isFallback,
  isBootstrapFallback: ds.isBootstrapFallback,
  caseIds: ds.cases.map((c) => c.id),
  worldPairs: Array.from(new Set(ds.cases.map((c) => c.tier + ":" + c.seed))).sort(),
  meta: ds.meta,
  verdictsSeen: Array.from(verdictsSeen).sort(),
  summaries,
  uiCheck
}));
"""


def run_outthink_vm_e2e(demo_dir: Path = DEMO_DIR) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_DEMO_DIR"] = str(demo_dir)
    proc = subprocess.run(
        [*cmd_prefix, VM_HARNESS_JS],
        cwd=ROOT,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def vm_report() -> dict:
    return run_outthink_vm_e2e(DEMO_DIR)


def test_cases_js_browser_vm_globals_and_pre_decision_invariants(vm_report: dict):
    assert vm_report["issues"] == []
    assert "cases.js" in vm_report["loadedScripts"]
    assert vm_report["source"] == "data"
    assert vm_report["isFallback"] is False
    assert vm_report["isBootstrapFallback"] is False
    assert vm_report["caseIds"] == EXPECTED_CASE_IDS
    assert vm_report["worldPairs"] == EXPECTED_WORLD_PAIRS
    assert vm_report["rawLevelCount"] == 39

    meta = vm_report["meta"]
    assert meta["tiers_version"] == "v1.4"
    assert meta["total_episodes"] == 550
    assert meta["total_cost_usd"] == pytest.approx(262.7061, abs=1e-4)
    assert meta["hold_fire_cases"] == 8
    assert meta["accuse_cases"] == 4


def test_vm_evaluate_call_optimal_and_suboptimal_across_all_12_cases(vm_report: dict):
    assert set(vm_report["verdictsSeen"]) == {
        "CAUTIOUS HOLD FIRE",
        "FALSE ACCUSATION (-1.00)",
        "LUCKY GUESS (BELOW BREAK-EVEN)",
        "OPTIMAL ACCUSATION",
        "OPTIMAL HOLD FIRE",
        "OVER-CAUTIOUS DELAY",
    }

    summaries = vm_report["summaries"]

    opt = summaries["optimal"]["judge"]
    assert opt["scoreSum"] == pytest.approx(7.8, abs=1e-4)
    assert opt["meanScore"] == pytest.approx(0.65, abs=1e-4)
    assert opt["rightCount"] == 12
    assert opt["optimalCount"] == 12
    assert opt["accuracy"] == pytest.approx(1.0, abs=1e-4)
    assert opt["optimalRate"] == pytest.approx(1.0, abs=1e-4)
    assert opt["costUsd"] == 0

    wrong = summaries["wrongAccuse"]["judge"]
    assert wrong["scoreSum"] == pytest.approx(-12.0, abs=1e-4)
    assert wrong["meanScore"] == pytest.approx(-1.0, abs=1e-4)
    assert wrong["rightCount"] == 0
    assert wrong["optimalCount"] == 0

    opp = summaries["oppositeSolver"]["judge"]
    assert opp["scoreSum"] == pytest.approx(-2.49, abs=1e-4)
    assert opp["meanScore"] == pytest.approx(-0.2075, abs=1e-4)
    assert opp["rightCount"] == 2
    assert opp["optimalCount"] == 0

    mole_all = summaries["alwaysAccuseMole"]["judge"]
    assert mole_all["scoreSum"] == pytest.approx(7.98, abs=1e-4)
    assert mole_all["meanScore"] == pytest.approx(0.665, abs=1e-4)
    assert mole_all["rightCount"] == 12
    assert mole_all["optimalCount"] == 4

    hold_all = summaries["alwaysHoldFire"]["judge"]
    assert hold_all["scoreSum"] == pytest.approx(7.42, abs=1e-4)
    assert hold_all["meanScore"] == pytest.approx(0.6183, abs=1e-4)
    assert hold_all["rightCount"] == 8
    assert hold_all["optimalCount"] == 8


def test_vm_scoreboard_summary_and_monotonic_thinking_ladder(vm_report: dict):
    opt_summary = vm_report["summaries"]["optimal"]
    assert opt_summary["casesPlayed"] == 12

    solver = opt_summary["solver"]
    assert solver["scoreSum"] == pytest.approx(7.9, abs=1e-4)
    assert solver["meanScore"] == pytest.approx(0.6583, abs=1e-4)
    assert solver["rightCount"] == 12
    assert solver["accuracy"] == pytest.approx(1.0, abs=1e-4)

    by_lv = opt_summary["byLevel"]
    expected_levels = {
        "minimal": (4, -2.1, -0.525, 1, 0.25, 0.324639, 0, 3),
        "low": (12, -2.84, -0.2367, 6, 0.5, 3.863664, 37548, 11),
        "medium": (10, 3.07, 0.307, 8, 0.8, 3.454475, 157746, 6),
        "high": (11, 6.74, 0.6127, 10, 0.9091, 5.826949, 276139, 3),
        "xhigh": (2, 1.41, 0.705, 2, 1.0, 1.810582, 110471, 1),
    }
    for lv_key, (cnt, s_sum, m_score, right, acc, cost, tok, outscored) in expected_levels.items():
        b = by_lv[lv_key]
        assert b["count"] == cnt
        assert b["scoreSum"] == pytest.approx(s_sum, abs=1e-4)
        assert b["meanScore"] == pytest.approx(m_score, abs=1e-4)
        assert b["rightCount"] == right
        assert b["accuracy"] == pytest.approx(acc, abs=1e-4)
        assert b["totalCostUsd"] == pytest.approx(cost, abs=1e-5)
        assert b["totalThinkingTokens"] == tok
        assert b["judgeOutscoredCount"] == outscored

    assert (
        by_lv["minimal"]["meanScore"]
        < by_lv["low"]["meanScore"]
        < by_lv["medium"]["meanScore"]
        < by_lv["high"]["meanScore"]
        < by_lv["xhigh"]["meanScore"]
    )


def test_full_ui_and_annotations_bundle_vm_e2e_when_present(vm_report: dict):
    if "annotations.js" in vm_report["loadedScripts"]:
        assert vm_report["annotationsMatched"] == 39

    if "engine.js" in vm_report["loadedScripts"]:
        assert vm_report["usedEngine"] is True

    if vm_report["uiCheck"] is not None:
        ui = vm_report["uiCheck"]
        assert ui["canvasDrawOps"] > 50
        assert ui["datasetBadge"] == "Verified Corpus (12 Cases)"
        assert "550 recorded ladder episodes" in ui["provenanceText"]
        assert ui["lvCards"] == 39
        assert ui["carbonStrips"] == 12
        assert "+7.80" in ui["sbTextBeforeReset"]
        assert "0/12" in ui["sbTextAfterReset"]
    else:
        assert vm_report["usedEngine"] is False
        assert vm_report["loadedScripts"] == ["cases.js"]


def test_hygiene_zero_comments_dashes_network_keys_and_protected_paths():
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")
    assert HASH_CHAR not in src
    assert EM_DASH not in src
    assert EN_DASH not in src
    assert FORBIDDEN_NET not in src

    comments = [
        tok for tok in tokenize.generate_tokens(io.StringIO(src).readline) if tok.type == tokenize.COMMENT
    ]
    assert comments == []

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "genai" not in alias.name and "google" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "genai" not in node.module and "google" not in node.module

    assert _find_js_comments(VM_HARNESS_JS) == []
    assert _find_js_comments(CASES_JS_PATH.read_text(encoding="utf-8")) == []

    rules = [
        ln.strip()
        for ln in PROTECTED_PATHS_FILE.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith(HASH_CHAR)
    ]
    checked = {self_path.relative_to(ROOT).as_posix()}
    for rel in checked:
        for rule in rules:
            if rule.endswith("/"):
                assert not rel.startswith(rule), f"protected dir touched: {rel}"
            else:
                assert rel != rule, f"protected file touched: {rel}"
