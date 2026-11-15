from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tokenize
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEMO_DIR = ROOT / "demo" / "out-think-gemini"
SCENARIOS_JSON_PATH = ROOT / "results" / "gemini" / "outthink_scenarios.json"
THIS_TEST_FILE = Path(__file__).resolve()

API_KEY_ENV_VARS: tuple[str, ...] = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
)
UNICODE_DASH_CODEPOINTS: tuple[int, ...] = (0x2012, 0x2013, 0x2014, 0x2015)


@pytest.fixture(autouse=True)
def _block_python_sockets(monkeypatch: pytest.MonkeyPatch) -> None:
    def _deny(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("OfflineGuardError: outbound network socket disabled")

    monkeypatch.setattr(socket, "socket", _deny)
    monkeypatch.setattr(socket, "create_connection", _deny)


def _demo_dir() -> Path:
    override = os.environ.get("OUTTHINK_DEMO_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return DEFAULT_DEMO_DIR


def _resolve_node_cmd() -> tuple[list[str], dict[str, str]]:
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

    opencode_candidates = (
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
        "/root/momin/bin/opencode",
    )
    for cand in opencode_candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            return [cand, "-e"], bun_env

    pytest.skip("no JavaScript runtime available")


VM_PRELUDE_JS = r"""
const fs = require("fs");
const vm = require("vm");

function createAirgappedSandbox(withModuleExports) {
  let networkAttempts = 0;
  function denyNetwork() {
    networkAttempts += 1;
    throw new Error("OfflineGuardError: network disabled in vm sandbox");
  }

  function makeDummyElement(tag) {
    const el = {
      tagName: String(tag || "div").toUpperCase(),
      id: "",
      className: "",
      textContent: "",
      innerHTML: "",
      hidden: false,
      disabled: false,
      value: "",
      style: {},
      dataset: {},
      attributes: {},
      children: [],
      appendChild: function (child) {
        el.children.push(child);
        return child;
      },
      removeChild: function (child) {
        const idx = el.children.indexOf(child);
        if (idx >= 0) {
          el.children.splice(idx, 1);
        }
        return child;
      },
      setAttribute: function (k, v) {
        el.attributes[String(k)] = String(v);
      },
      getAttribute: function (k) {
        return Object.prototype.hasOwnProperty.call(el.attributes, k) ? el.attributes[k] : null;
      },
      addEventListener: function () {},
      removeEventListener: function () {},
      querySelector: function () { return null; },
      querySelectorAll: function () { return []; },
      getBoundingClientRect: function () {
        return { left: 0, top: 0, width: 640, height: 360 };
      },
      getContext: function () {
        return {
          clearRect: function () {},
          fillRect: function () {},
          strokeRect: function () {},
          beginPath: function () {},
          closePath: function () {},
          moveTo: function () {},
          lineTo: function () {},
          arc: function () {},
          fill: function () {},
          stroke: function () {},
          fillText: function () {},
          drawImage: function () {},
          save: function () {},
          restore: function () {},
          scale: function () {},
          translate: function () {},
          measureText: function (txt) { return { width: String(txt || "").length * 6 }; }
        };
      },
      classList: {
        add: function () {},
        remove: function () {},
        toggle: function () { return false; },
        contains: function () { return false; }
      }
    };
    return el;
  }

  const docStub = {
    readyState: "complete",
    body: makeDummyElement("body"),
    documentElement: makeDummyElement("html"),
    createElement: function (tag) { return makeDummyElement(tag); },
    createTextNode: function (txt) { return { nodeType: 3, textContent: String(txt || "") }; },
    createDocumentFragment: function () { return makeDummyElement("fragment"); },
    getElementById: function () { return null; },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    addEventListener: function () {},
    removeEventListener: function () {}
  };

  const sandbox = {
    Math: Math,
    Date: Date,
    JSON: JSON,
    Array: Array,
    Object: Object,
    String: String,
    Number: Number,
    Boolean: Boolean,
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
    decodeURIComponent: decodeURIComponent,
    setTimeout: function () { return 1; },
    clearTimeout: function () {},
    requestAnimationFrame: function () { return 1; },
    cancelAnimationFrame: function () {},
    fetch: denyNetwork,
    XMLHttpRequest: denyNetwork,
    WebSocket: denyNetwork,
    EventSource: denyNetwork,
    navigator: { userAgent: "OutThinkAnalystVM/1.0", sendBeacon: denyNetwork },
    document: docStub,
    console: {
      log: function () {},
      info: function () {},
      warn: function () {},
      error: function () {}
    }
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  if (withModuleExports) {
    sandbox.module = { exports: {} };
    sandbox.exports = sandbox.module.exports;
  }

  const context = vm.createContext(sandbox);
  return {
    sandbox: sandbox,
    context: context,
    runFile: function (filePath) {
      const code = fs.readFileSync(filePath, "utf8");
      return vm.runInContext(code, context, { filename: filePath, timeout: 15000 });
    },
    getNetworkAttempts: function () {
      return networkAttempts;
    }
  };
}
"""


def _run_js_vm(body_js: str, payload: dict[str, Any]) -> dict[str, Any]:
    cmd_prefix, env = _resolve_node_cmd()
    wrapper = (
        VM_PRELUDE_JS
        + "\nconst PAYLOAD = JSON.parse(fs.readFileSync(0, 'utf8'));\n"
        + "const RESULT = (function () {\n"
        + body_js
        + "\n})();\n"
        + "process.stdout.write(JSON.stringify(RESULT));\n"
    )
    proc = subprocess.run(
        [*cmd_prefix, wrapper],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, f"JS VM subprocess failed ({proc.returncode}): {proc.stderr}"
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def scenarios_doc() -> dict[str, Any]:
    assert SCENARIOS_JSON_PATH.is_file()
    return json.loads(SCENARIOS_JSON_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def annotations_js_path() -> Path:
    candidate = _demo_dir() / "annotations.js"
    if candidate.is_file():
        return candidate
    path = DEFAULT_DEMO_DIR / "annotations.js"
    assert path.is_file()
    return path


def test_annotations_vm_sandbox_exports_and_edge_cases(annotations_js_path: Path) -> None:
    res = _run_js_vm(
        r"""
        const browserEnv = createAirgappedSandbox(false);
        browserEnv.runFile(PAYLOAD.annotationsJs);
        const annBrowser = browserEnv.sandbox.window.OUTTHINK_ANNOTATIONS;
        const fnBrowser = browserEnv.sandbox.window.getOutthinkAnnotation;

        const cjsEnv = createAirgappedSandbox(true);
        cjsEnv.runFile(PAYLOAD.annotationsJs);
        const modExports = cjsEnv.sandbox.module.exports;

        let fetchBlocked = false;
        try {
          browserEnv.sandbox.window.fetch("https://example.com");
        } catch (err) {
          fetchBlocked = String(err).indexOf("OfflineGuardError") >= 0;
        }

        const edgeLookups = [
          fnBrowser(),
          fnBrowser(null),
          fnBrowser(undefined),
          fnBrowser(""),
          fnBrowser("   "),
          fnBrowser({}),
          fnBrowser("nonexistent-model/minimal/hard/999"),
          fnBrowser("nonexistent-model|minimal|hard|999"),
          fnBrowser("nonexistent-model", "minimal", "hard", 999)
        ];

        return {
          hasAnnotationsObj: Boolean(annBrowser && typeof annBrowser === "object"),
          hasGetterFn: typeof fnBrowser === "function",
          episodeKeysCount: Object.keys(annBrowser.episodes || {}).length,
          summaryEpisodes: annBrowser.summary ? annBrowser.summary.total_episodes : -1,
          summaryScenarios: annBrowser.summary ? annBrowser.summary.scenarios_count : -1,
          cjsMatchesWindowObj: modExports.OUTTHINK_ANNOTATIONS === cjsEnv.sandbox.window.OUTTHINK_ANNOTATIONS,
          cjsMatchesWindowFn: modExports.getOutthinkAnnotation === cjsEnv.sandbox.window.getOutthinkAnnotation,
          edgeAllNull: edgeLookups.every(function (v) { return v === null; }),
          networkAttemptsBeforeProbe: cjsEnv.getNetworkAttempts(),
          fetchBlocked: fetchBlocked
        };
        """,
        {"annotationsJs": str(annotations_js_path)},
    )
    assert res["hasAnnotationsObj"] is True
    assert res["hasGetterFn"] is True
    assert res["episodeKeysCount"] == 587
    assert res["summaryEpisodes"] == 587
    assert res["summaryScenarios"] == 62
    assert res["cjsMatchesWindowObj"] is True
    assert res["cjsMatchesWindowFn"] is True
    assert res["edgeAllNull"] is True
    assert res["networkAttemptsBeforeProbe"] == 0
    assert res["fetchBlocked"] is True


def test_get_outthink_annotation_resolves_all_587_episodes_across_all_conventions(
    annotations_js_path: Path,
) -> None:
    res = _run_js_vm(
        r"""
        const env = createAirgappedSandbox(false);
        env.runFile(PAYLOAD.annotationsJs);
        const win = env.sandbox.window;
        const episodes = win.OUTTHINK_ANNOTATIONS.episodes;
        const getAnn = win.getOutthinkAnnotation;

        const keys = Object.keys(episodes);
        let fourArgCount = 0;
        let prefixedFourArgCount = 0;
        let slashStringCount = 0;
        let pipeStringCount = 0;
        let objThinkingLevelCount = 0;
        let objLevelCount = 0;
        const failures = [];

        for (let i = 0; i < keys.length; i += 1) {
          const k = keys[i];
          const ep = episodes[k];
          const model = ep.model;
          const level = ep.level || ep.thinking_level;
          const tier = ep.tier;
          const seed = ep.seed;

          const slashKey = model + "/" + level + "/" + tier + "/" + String(seed);
          const pipeKey = model + "|" + level + "|" + tier + "|" + String(seed);

          const r4 = getAnn(model, level, tier, seed);
          const r4Prefixed = getAnn(
            "gemini:" + model,
            String(level).toUpperCase(),
            String(tier).toUpperCase(),
            String(seed)
          );
          const rSlash = getAnn(slashKey);
          const rSlashPadded = getAnn("  " + slashKey + "  ");
          const rPipe = getAnn(pipeKey);
          const rObjThinking = getAnn({
            model: model,
            thinking_level: level,
            tier: tier,
            seed: seed
          });
          const rObjLevel = getAnn({
            model: model,
            level: level,
            tier: tier,
            seed: seed
          });

          if (r4 === ep) {
            fourArgCount += 1;
          } else {
            failures.push("4arg:" + k);
          }
          if (r4Prefixed === ep) {
            prefixedFourArgCount += 1;
          } else {
            failures.push("4arg_prefixed:" + k);
          }
          if (rSlash === ep && rSlashPadded === ep) {
            slashStringCount += 1;
          } else {
            failures.push("slash:" + k);
          }
          if (rPipe === ep) {
            pipeStringCount += 1;
          } else {
            failures.push("pipe:" + k);
          }
          if (rObjThinking === ep) {
            objThinkingLevelCount += 1;
          } else {
            failures.push("obj_thinking_level:" + k);
          }
          if (rObjLevel === ep) {
            objLevelCount += 1;
          } else {
            failures.push("obj_level:" + k);
          }
        }

        return {
          totalEpisodes: keys.length,
          fourArgCount: fourArgCount,
          prefixedFourArgCount: prefixedFourArgCount,
          slashStringCount: slashStringCount,
          pipeStringCount: pipeStringCount,
          objThinkingLevelCount: objThinkingLevelCount,
          objLevelCount: objLevelCount,
          failures: failures.slice(0, 10),
          networkAttempts: env.getNetworkAttempts()
        };
        """,
        {"annotationsJs": str(annotations_js_path)},
    )
    assert res["totalEpisodes"] == 587
    assert res["fourArgCount"] == 587
    assert res["prefixedFourArgCount"] == 587
    assert res["slashStringCount"] == 587
    assert res["pipeStringCount"] == 587
    assert res["objThinkingLevelCount"] == 587
    assert res["objLevelCount"] == 587
    assert res["failures"] == []
    assert res["networkAttempts"] == 0


def test_all_62_scenarios_anchor_runs_and_aggregates_match_annotations_in_vm(
    annotations_js_path: Path,
    scenarios_doc: dict[str, Any],
) -> None:
    res = _run_js_vm(
        r"""
        const env = createAirgappedSandbox(false);
        env.runFile(PAYLOAD.annotationsJs);
        const win = env.sandbox.window;
        const ann = win.OUTTHINK_ANNOTATIONS;
        const episodes = ann.episodes;
        const getAnn = win.getOutthinkAnnotation;
        const scenDoc = PAYLOAD.scenariosDoc;
        const scenarios = scenDoc.scenarios;

        const byRunId = Object.create(null);
        const groupedByScenario = Object.create(null);
        const epKeys = Object.keys(episodes);
        for (let i = 0; i < epKeys.length; i += 1) {
          const ep = episodes[epKeys[i]];
          if (ep.run_id) {
            byRunId[ep.run_id] = ep;
          }
          const sk = String(ep.tier) + ":" + String(ep.seed);
          if (!groupedByScenario[sk]) {
            groupedByScenario[sk] = [];
          }
          groupedByScenario[sk].push(ep);
        }

        const scenarioKeys = Object.keys(scenarios);
        let anchorTotal = 0;
        let episodeCountSum = 0;
        const mismatches = [];

        for (let s = 0; s < scenarioKeys.length; s += 1) {
          const sk = scenarioKeys[s];
          const sc = scenarios[sk];
          const group = groupedByScenario[sk] || [];
          episodeCountSum += sc.episode_count;
          if (group.length !== sc.episode_count) {
            mismatches.push("episode_count:" + sk + ":" + group.length + "!=" + sc.episode_count);
          }

          const anchors = sc.anchor_runs || [];
          if (anchors.length < 1 || anchors.length > 3) {
            mismatches.push("anchor_len:" + sk + ":" + anchors.length);
          }

          for (let a = 0; a < anchors.length; a += 1) {
            anchorTotal += 1;
            const ar = anchors[a];
            const viaDirect = episodes[ar.key] || null;
            const via4Arg = getAnn(ar.model, ar.level, sc.tier, sc.seed);
            const viaSlash = getAnn(ar.key);
            const viaPipe = getAnn(ar.model + "|" + ar.level + "|" + sc.tier + "|" + String(sc.seed));
            const viaObj = getAnn({
              model: ar.model,
              thinking_level: ar.level,
              tier: sc.tier,
              seed: sc.seed
            });
            const viaRunId = ar.run_id ? (byRunId[ar.run_id] || null) : null;

            if (!viaDirect || via4Arg !== viaDirect || viaSlash !== viaDirect || viaPipe !== viaDirect || viaObj !== viaDirect) {
              mismatches.push("anchor_lookup:" + sk + ":" + ar.key);
              continue;
            }
            if (ar.run_id && viaDirect.run_id && viaRunId !== viaDirect) {
              mismatches.push("anchor_run_id:" + sk + ":" + ar.run_id);
            }
            if (!Object.prototype.hasOwnProperty.call(viaDirect, "primary_failure_tag")) {
              mismatches.push("anchor_missing_primary_tag_prop:" + sk + ":" + ar.key);
            }
            if (Math.abs(Number(viaDirect.score) - Number(ar.score)) > 1e-9) {
              mismatches.push("anchor_score:" + sk + ":" + ar.key);
            }
            if (Boolean(viaDirect.correct) !== Boolean(ar.correct)) {
              mismatches.push("anchor_correct:" + sk + ":" + ar.key);
            }
            if ((viaDirect.primary_failure_tag || null) !== (ar.primary_failure_tag || null)) {
              mismatches.push("anchor_tag:" + sk + ":" + ar.key);
            }
          }

          const ladderLevels = ["minimal", "low", "medium", "high", "xhigh"];
          for (let li = 0; li < ladderLevels.length; li += 1) {
            const lv = ladderLevels[li];
            const lvEps = group.filter(function (e) {
              return (e.level || e.thinking_level) === lv;
            });
            if (lvEps.length === 0) {
              continue;
            }
            const expAcc = lvEps.reduce(function (acc, e) { return acc + (e.correct ? 1 : 0); }, 0) / lvEps.length;
            const expMeanScore = lvEps.reduce(function (acc, e) { return acc + Number(e.score); }, 0) / lvEps.length;
            if (Math.abs(Number(sc.accuracy_by_level[lv]) - expAcc) > 1e-5) {
              mismatches.push("acc_by_level:" + sk + ":" + lv);
            }
            if (Math.abs(Number(sc.mean_score_by_level[lv]) - expMeanScore) > 1e-5) {
              mismatches.push("score_by_level:" + sk + ":" + lv);
            }
          }
        }

        return {
          scenarioCount: scenarioKeys.length,
          groupedScenarioCount: Object.keys(groupedByScenario).length,
          episodeCountSum: episodeCountSum,
          anchorTotal: anchorTotal,
          mismatches: mismatches.slice(0, 20),
          networkAttempts: env.getNetworkAttempts()
        };
        """,
        {
            "annotationsJs": str(annotations_js_path),
            "scenariosDoc": scenarios_doc,
        },
    )
    assert res["scenarioCount"] == 62
    assert res["groupedScenarioCount"] == 62
    assert res["episodeCountSum"] == 587
    assert res["anchorTotal"] >= 62
    assert res["mismatches"] == []
    assert res["networkAttempts"] == 0


def test_annotations_quotes_xss_dom_and_text_hygiene_in_vm(annotations_js_path: Path) -> None:
    raw_js = annotations_js_path.read_text(encoding="utf-8")
    low_js = raw_js.lower()
    assert "<script" not in low_js
    assert "javascript:" not in low_js
    for cp in UNICODE_DASH_CODEPOINTS:
        assert chr(cp) not in raw_js
        assert ("\\u" + f"{cp:04x}") not in low_js

    res = _run_js_vm(
        r"""
        const env = createAirgappedSandbox(false);
        env.runFile(PAYLOAD.annotationsJs);
        const ann = env.sandbox.window.OUTTHINK_ANNOTATIONS;
        const episodes = ann.episodes;
        const epKeys = Object.keys(episodes);

        const forbiddenSubstrings = [
          "<" + "script",
          "javascript" + ":",
          "<" + "iframe",
          "onerror" + "=",
          "onload" + "="
        ];
        const dashChars = [0x2012, 0x2013, 0x2014, 0x2015].map(function (cp) {
          return String.fromCharCode(cp);
        });

        function checkStringHygiene(str, pathLabel, violations) {
          const low = str.toLowerCase();
          for (let i = 0; i < forbiddenSubstrings.length; i += 1) {
            if (low.indexOf(forbiddenSubstrings[i]) >= 0) {
              violations.push("xss:" + forbiddenSubstrings[i] + "@" + pathLabel);
            }
          }
          for (let d = 0; d < dashChars.length; d += 1) {
            if (str.indexOf(dashChars[d]) >= 0) {
              violations.push("unicode_dash@" + pathLabel);
            }
          }
        }

        const violations = [];
        let episodesWithQuotes = 0;
        let totalQuotes = 0;

        for (let i = 0; i < epKeys.length; i += 1) {
          const k = epKeys[i];
          const ep = episodes[k];
          const quoteTexts = [];

          if (Array.isArray(ep.quotes)) {
            for (let q = 0; q < ep.quotes.length; q += 1) {
              const item = ep.quotes[q];
              if (typeof item === "string" && item.trim().length > 0) {
                quoteTexts.push(item);
              } else if (item && typeof item === "object") {
                if (typeof item.quote === "string" && item.quote.trim().length > 0) {
                  quoteTexts.push(item.quote);
                }
                if (typeof item.note === "string" && item.note.trim().length > 0) {
                  checkStringHygiene(item.note, k + ".quotes[" + q + "].note", violations);
                }
              }
            }
          }
          const aliasFields = ["analyst_quote", "thought_quote", "quote"];
          for (let af = 0; af < aliasFields.length; af += 1) {
            const fname = aliasFields[af];
            if (typeof ep[fname] === "string" && ep[fname].trim().length > 0) {
              quoteTexts.push(ep[fname]);
            }
          }

          if (quoteTexts.length > 0) {
            episodesWithQuotes += 1;
          } else {
            violations.push("missing_quote@" + k);
          }
          for (let qt = 0; qt < quoteTexts.length; qt += 1) {
            totalQuotes += 1;
            checkStringHygiene(quoteTexts[qt], k + ".quote[" + qt + "]", violations);
          }
        }

        let stringsVisited = 0;
        function walkAllStrings(node, pathLabel) {
          if (typeof node === "string") {
            stringsVisited += 1;
            checkStringHygiene(node, pathLabel, violations);
            return;
          }
          if (!node || typeof node !== "object") {
            return;
          }
          if (Array.isArray(node)) {
            for (let idx = 0; idx < node.length; idx += 1) {
              walkAllStrings(node[idx], pathLabel + "[" + idx + "]");
            }
            return;
          }
          const ks = Object.keys(node);
          for (let idx = 0; idx < ks.length; idx += 1) {
            const keyName = ks[idx];
            checkStringHygiene(keyName, pathLabel + ".<key>", violations);
            walkAllStrings(node[keyName], pathLabel + "." + keyName);
          }
        }
        walkAllStrings(ann, "OUTTHINK_ANNOTATIONS");

        return {
          episodeCount: epKeys.length,
          episodesWithQuotes: episodesWithQuotes,
          totalQuotes: totalQuotes,
          stringsVisited: stringsVisited,
          violations: violations.slice(0, 20)
        };
        """,
        {"annotationsJs": str(annotations_js_path)},
    )
    assert res["episodeCount"] == 587
    assert res["episodesWithQuotes"] == 587
    assert res["totalQuotes"] >= 587
    assert res["stringsVisited"] > 2000
    assert res["violations"] == []


def test_showcase_ranking_and_dominant_failure_tags_join_in_vm(
    annotations_js_path: Path,
    scenarios_doc: dict[str, Any],
) -> None:
    res = _run_js_vm(
        r"""
        const env = createAirgappedSandbox(false);
        env.runFile(PAYLOAD.annotationsJs);
        const ann = env.sandbox.window.OUTTHINK_ANNOTATIONS;
        const getAnn = env.sandbox.window.getOutthinkAnnotation;
        const scenDoc = PAYLOAD.scenariosDoc;
        const scenarios = scenDoc.scenarios;
        const best12 = scenDoc.summary.best_showcase_scenarios || [];
        const ranking = scenDoc.showcase_ranking || [];
        const errors = [];

        if (best12.length !== 12 || ranking.length !== 62) {
          errors.push("invalid_ranking_lengths");
        }
        for (let i = 0; i < best12.length; i += 1) {
          const sk = best12[i];
          if (ranking[i] !== sk) {
            errors.push("best12_rank_mismatch:" + i);
          }
          const sc = scenarios[sk];
          if (!sc) {
            errors.push("missing_best12_scenario:" + sk);
            continue;
          }
          for (let a = 0; a < sc.anchor_runs.length; a += 1) {
            const ar = sc.anchor_runs[a];
            if (!getAnn(ar.key)) {
              errors.push("missing_showcase_anchor:" + sk + ":" + ar.key);
            }
          }
        }

        const tagNames = [
          "premature_accusation",
          "uninformative_canary",
          "ignored_delay",
          "over_restriction"
        ];
        const summaryCounts = (ann.summary && ann.summary.highlighted_tag_episode_counts) || null;
        if (summaryCounts) {
          for (let t = 0; t < tagNames.length; t += 1) {
            const tg = tagNames[t];
            let scenSum = 0;
            const sks = Object.keys(scenarios);
            for (let s = 0; s < sks.length; s += 1) {
              scenSum += Number(scenarios[sks[s]].dominant_failure_tags[tg] || 0);
            }
            if (scenSum !== Number(summaryCounts[tg])) {
              errors.push("tag_total_mismatch:" + tg + ":" + scenSum + "!=" + summaryCounts[tg]);
            }
          }
        }

        return {
          best12Count: best12.length,
          rankingCount: ranking.length,
          errors: errors
        };
        """,
        {
            "annotationsJs": str(annotations_js_path),
            "scenariosDoc": scenarios_doc,
        },
    )
    assert res["best12Count"] == 12
    assert res["rankingCount"] == 62
    assert res["errors"] == []


def test_hygiene_scanner_rejects_injected_xss_and_unicode_dashes_in_vm() -> None:
    res = _run_js_vm(
        r"""
        const forbiddenSubstrings = ["<" + "script", "javascript" + ":"];
        const dashChars = [0x2012, 0x2013, 0x2014, 0x2015].map(function (cp) {
          return String.fromCharCode(cp);
        });
        function scanQuote(q) {
          const hits = [];
          const low = q.toLowerCase();
          for (let i = 0; i < forbiddenSubstrings.length; i += 1) {
            if (low.indexOf(forbiddenSubstrings[i]) >= 0) {
              hits.push("xss");
            }
          }
          for (let d = 0; d < dashChars.length; d += 1) {
            if (q.indexOf(dashChars[d]) >= 0) {
              hits.push("dash:" + (0x2012 + d).toString(16));
            }
          }
          return hits;
        }
        return {
          cleanHits: scanQuote("Planted 3-variant canary - waited for day 9 leak."),
          scriptHits: scanQuote("bad <" + "SCRIPT src=x> quote"),
          jsProtoHits: scanQuote("click JavaScript" + ":alert(1)"),
          dash2012Hits: scanQuote("a" + String.fromCharCode(0x2012) + "b"),
          dash2013Hits: scanQuote("a" + String.fromCharCode(0x2013) + "b"),
          dash2014Hits: scanQuote("a" + String.fromCharCode(0x2014) + "b"),
          dash2015Hits: scanQuote("a" + String.fromCharCode(0x2015) + "b")
        };
        """,
        {},
    )
    assert res["cleanHits"] == []
    assert res["scriptHits"] == ["xss"]
    assert res["jsProtoHits"] == ["xss"]
    assert res["dash2012Hits"] == ["dash:2012"]
    assert res["dash2013Hits"] == ["dash:2013"]
    assert res["dash2014Hits"] == ["dash:2014"]
    assert res["dash2015Hits"] == ["dash:2015"]


def test_playable_12_scenarios_join_with_annotations_in_vm(
    annotations_js_path: Path,
    scenarios_doc: dict[str, Any],
) -> None:
    res = _run_js_vm(
        r"""
        const env = createAirgappedSandbox(false);
        env.runFile(PAYLOAD.annotationsJs);
        const getAnn = env.sandbox.window.getOutthinkAnnotation;
        const scenarios = PAYLOAD.scenariosDoc.scenarios;
        const sks = Object.keys(scenarios);

        const playableKeys = [];
        let resolvedAnchors = 0;
        const errors = [];

        for (let i = 0; i < sks.length; i += 1) {
          const sc = scenarios[sks[i]];
          if (!sc.in_playable_12) {
            continue;
          }
          playableKeys.push(sks[i]);
          const anchors = sc.anchor_runs || [];
          for (let a = 0; a < anchors.length; a += 1) {
            const ar = anchors[a];
            const ep = getAnn(ar.model, ar.level, sc.tier, sc.seed);
            if (!ep) {
              errors.push("missing_playable_anchor:" + sks[i] + ":" + ar.key);
            } else {
              resolvedAnchors += 1;
            }
          }
        }

        return {
          playableCount: playableKeys.length,
          resolvedAnchors: resolvedAnchors,
          errors: errors
        };
        """,
        {
            "annotationsJs": str(annotations_js_path),
            "scenariosDoc": scenarios_doc,
        },
    )
    assert res["playableCount"] == 11
    assert res["resolvedAnchors"] >= 11
    assert res["errors"] == []


def test_conditional_fullstack_cases_and_engine_join_in_vm(
    annotations_js_path: Path,
    scenarios_doc: dict[str, Any],
) -> None:
    demo_dir = _demo_dir()
    cases_js = demo_dir / "cases.js"
    engine_js = demo_dir / "engine.js"
    if not (cases_js.is_file() and engine_js.is_file()):
        pytest.skip("demo/out-think-gemini/cases.js and engine.js not present in standalone worktree")

    ann_js = demo_dir / "annotations.js"
    if not ann_js.is_file():
        ann_js = annotations_js_path
    failure_modes_js = demo_dir / "failure_modes.js"
    reveal_card_js = demo_dir / "reveal_card.js"

    res = _run_js_vm(
        r"""
        function executeFullStackPass() {
          const env = createAirgappedSandbox(false);
          env.runFile(PAYLOAD.casesJs);
          env.runFile(PAYLOAD.annotationsJs);
          if (PAYLOAD.failureModesJs) {
            env.runFile(PAYLOAD.failureModesJs);
          }
          env.runFile(PAYLOAD.engineJs);
          if (PAYLOAD.revealCardJs) {
            env.runFile(PAYLOAD.revealCardJs);
          }

          const win = env.sandbox.window;
          const Engine = win.OutThinkEngine;
          const getAnn = win.getOutthinkAnnotation;
          const ds = Engine.loadDataset();

          const sbAccuseTrue = Engine.createScoreboard();
          const sbAccuseWrong = Engine.createScoreboard();
          const sbHoldFire = Engine.createScoreboard();

          const forbiddenSubstrings = ["<" + "script", "javascript" + ":"];
          const dashChars = [0x2012, 0x2013, 0x2014, 0x2015].map(function (cp) {
            return String.fromCharCode(cp);
          });

          let totalLevelRuns = 0;
          let populatedTagCount = 0;
          let populatedQuoteCount = 0;
          const errors = [];
          const perCaseDigest = [];

          for (let i = 0; i < ds.cases.length; i += 1) {
            const c = ds.cases[i];
            const scenKey = String(c.tier) + ":" + String(c.seed);
            const scenRec = PAYLOAD.scenariosDoc.scenarios[scenKey];
            if (!scenRec || !scenRec.in_playable_12) {
              errors.push("missing_playable_scenario:" + c.id + ":" + scenKey);
            }

            const wrongSuspectObj = c.suspects.find(function (s) { return s.id !== c.true_mole; });
            if (!wrongSuspectObj) {
              errors.push("no_wrong_suspect:" + c.id);
              continue;
            }

            const evalAccuseTrue = Engine.evaluateCall(c, {
              action: "accuse",
              suspectId: c.true_mole
            });
            const evalAccuseWrong = Engine.evaluateCall(c, {
              action: "accuse",
              suspectId: wrongSuspectObj.id
            });
            const evalHoldFire = Engine.evaluateCall(c, { action: "hold_fire" });

            if (evalAccuseTrue.action !== "accuse" || evalAccuseTrue.correct !== true) {
              errors.push("eval_accuse_true_failed:" + c.id);
            }
            if (Math.abs(evalAccuseTrue.score - Engine.round4(c.value_at_decision)) > 1e-6) {
              errors.push("eval_accuse_true_score:" + c.id);
            }
            if (evalAccuseWrong.action !== "accuse" || evalAccuseWrong.correct !== false || evalAccuseWrong.score !== -1.0) {
              errors.push("eval_accuse_wrong_failed:" + c.id);
            }
            if (evalHoldFire.action !== "hold_fire" || !Number.isFinite(evalHoldFire.score)) {
              errors.push("eval_hold_fire_failed:" + c.id);
            }

            sbAccuseTrue.record(c.id, evalAccuseTrue, c);
            sbAccuseWrong.record(c.id, evalAccuseWrong, c);
            sbHoldFire.record(c.id, evalHoldFire, c);

            if (!Array.isArray(c.thinking_levels) || c.thinking_levels.length < 2) {
              errors.push("insufficient_thinking_levels:" + c.id);
            }

            for (let k = 0; k < c.thinking_levels.length; k += 1) {
              totalLevelRuns += 1;
              const lv = c.thinking_levels[k];
              const annRec = getAnn(lv.model, lv.thinking_level, c.tier, c.seed);
              const annViaObj = getAnn({
                model: lv.model,
                thinking_level: lv.thinking_level,
                tier: c.tier,
                seed: c.seed
              });
              if (!annRec || annRec !== annViaObj) {
                errors.push("ann_join_missing:" + c.id + ":" + lv.thinking_level);
                continue;
              }
              if (Boolean(annRec.correct) !== Boolean(lv.correct)) {
                errors.push("ann_correct_mismatch:" + c.id + ":" + lv.thinking_level);
              }
              if (Math.abs(Number(annRec.score) - Number(lv.score)) > 1e-4) {
                errors.push("ann_score_mismatch:" + c.id + ":" + lv.thinking_level);
              }

              const effectiveTag = lv.failure_tag || annRec.primary_failure_tag || null;
              if (lv.failure_tag) {
                populatedTagCount += 1;
              }
              if (!lv.correct && !effectiveTag) {
                errors.push("wrong_run_missing_failure_tag:" + c.id + ":" + lv.thinking_level);
              }

              const quoteText = String(lv.analyst_quote || "").trim();
              if (quoteText.length > 0) {
                populatedQuoteCount += 1;
              } else {
                errors.push("empty_analyst_quote:" + c.id + ":" + lv.thinking_level);
              }

              const lowQ = quoteText.toLowerCase();
              for (let f = 0; f < forbiddenSubstrings.length; f += 1) {
                if (lowQ.indexOf(forbiddenSubstrings[f]) >= 0) {
                  errors.push("quote_xss:" + c.id + ":" + lv.thinking_level);
                }
              }
              for (let d = 0; d < dashChars.length; d += 1) {
                if (quoteText.indexOf(dashChars[d]) >= 0) {
                  errors.push("quote_dash:" + c.id + ":" + lv.thinking_level);
                }
              }
            }

            perCaseDigest.push({
              id: c.id,
              accuseTrueScore: evalAccuseTrue.score,
              accuseWrongScore: evalAccuseWrong.score,
              holdFireScore: evalHoldFire.score,
              holdFireOptimal: evalHoldFire.optimal
            });
          }

          return {
            source: ds.source,
            isBootstrapFallback: ds.isBootstrapFallback,
            caseCount: ds.count,
            totalLevelRuns: totalLevelRuns,
            populatedTagCount: populatedTagCount,
            populatedQuoteCount: populatedQuoteCount,
            summaryAccuseTrue: sbAccuseTrue.getSummary(),
            summaryAccuseWrong: sbAccuseWrong.getSummary(),
            summaryHoldFire: sbHoldFire.getSummary(),
            perCaseDigest: perCaseDigest,
            failureModesLoaded: PAYLOAD.failureModesJs
              ? Boolean(win.OUTTHINK_FAILURE_MODES || win.getOutthinkFailureMode)
              : true,
            networkAttempts: env.getNetworkAttempts(),
            errors: errors
          };
        }

        const pass1 = executeFullStackPass();
        const pass2 = executeFullStackPass();
        return {
          deterministicEqual: JSON.stringify(pass1) === JSON.stringify(pass2),
          pass1: pass1
        };
        """,
        {
            "casesJs": str(cases_js),
            "annotationsJs": str(ann_js),
            "engineJs": str(engine_js),
            "failureModesJs": str(failure_modes_js) if failure_modes_js.is_file() else "",
            "revealCardJs": str(reveal_card_js) if reveal_card_js.is_file() else "",
            "scenariosDoc": scenarios_doc,
        },
    )

    assert res["deterministicEqual"] is True
    p1 = res["pass1"]
    assert p1["errors"] == []
    assert p1["networkAttempts"] == 0
    assert p1["source"] == "data"
    assert p1["isBootstrapFallback"] is False
    assert p1["caseCount"] == 12
    assert p1["totalLevelRuns"] >= 24
    assert p1["populatedQuoteCount"] == p1["totalLevelRuns"]
    assert p1["populatedTagCount"] >= 10
    assert p1["failureModesLoaded"] is True

    acc_true = p1["summaryAccuseTrue"]
    assert acc_true["casesPlayed"] == 12
    assert acc_true["judge"]["rightCount"] == 12
    assert acc_true["judge"]["accuracy"] == 1.0
    assert acc_true["judge"]["scoreSum"] > 0.0

    acc_wrong = p1["summaryAccuseWrong"]
    assert acc_wrong["casesPlayed"] == 12
    assert acc_wrong["judge"]["rightCount"] == 0
    assert acc_wrong["judge"]["accuracy"] == 0.0
    assert acc_wrong["judge"]["scoreSum"] == -12.0

    hold_sum = p1["summaryHoldFire"]
    assert hold_sum["casesPlayed"] == 12
    assert 1 <= hold_sum["judge"]["rightCount"] <= 12


def test_self_hygiene_zero_comments_zero_unicode_dashes_zero_live_imports() -> None:
    src = THIS_TEST_FILE.read_text(encoding="utf-8")
    hash_char = chr(35)
    assert hash_char not in src

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    assert not [tok for tok in tokens if tok.type == tokenize.COMMENT]

    for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2212):
        assert chr(cp) not in src
        assert ("\\u" + f"{cp:04x}") not in src.lower()

    tree = ast.parse(src)
    forbidden = {"requests", "httpx", "urllib", "http", "google", "canary.gemini.sdk"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden and alias.name not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            assert top not in forbidden and node.module not in forbidden
