from __future__ import annotations

import ast
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tokenize

import pytest

from canary.agents.world_builder import TRUTH_WORDS
from canary.text.lint import lint_text

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
ENGINE_PATH = DEMO_DIR / "engine.js"
SCENE_PATH = DEMO_DIR / "scene.js"
CHATTER_PATH = DEMO_DIR / "chatter.js"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
FIG_DASH = chr(0x2012)
HORIZ_BAR = chr(0x2015)
HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
LT_CHAR = chr(60)
BANG_CHAR = chr(33)
LINE_COMMENT = SLASH + SLASH
BLOCK_COMMENT_OPEN = SLASH + STAR
HTML_COMMENT_OPEN = LT_CHAR + BANG_CHAR + "-" + "-"
FETCH_CALL = "fet" + "ch("
XHR_TOKEN = "XML" + "HttpRequest"


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


JS_BUNDLE_HARNESS = """
const H = String.fromCharCode(35);

function createMockContext2D() {
  const stack = [];
  let currentPath = [];
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
    fillRects: [],
    strokeRects: [],
    texts: [],
    drawImages: [],
    arcs: [],
    strokes: [],
    fills: [],
    save() {
      stack.push({
        fillStyle: this.fillStyle,
        strokeStyle: this.strokeStyle,
        lineWidth: this.lineWidth,
        font: this.font,
        textAlign: this.textAlign,
        globalAlpha: this.globalAlpha
      });
    },
    restore() {
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
    fillRect(x, y, w, h) {
      this.fillRects.push({
        x,
        y,
        w,
        h,
        fillStyle: String(this.fillStyle),
        globalAlpha: this.globalAlpha
      });
    },
    strokeRect(x, y, w, h) {
      this.strokeRects.push({
        x,
        y,
        w,
        h,
        strokeStyle: String(this.strokeStyle),
        lineWidth: this.lineWidth,
        globalAlpha: this.globalAlpha
      });
    },
    fillText(text, x, y) {
      this.texts.push({
        text: String(text),
        x,
        y,
        fillStyle: String(this.fillStyle),
        font: String(this.font),
        textAlign: String(this.textAlign),
        globalAlpha: this.globalAlpha
      });
    },
    drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh) {
      this.drawImages.push({
        src: img && img.src ? String(img.src) : "",
        sx,
        sy,
        sw,
        sh,
        dx,
        dy,
        dw,
        dh,
        globalAlpha: this.globalAlpha
      });
    },
    beginPath() {
      currentPath = [];
    },
    closePath() {
      currentPath.push({ op: "closePath" });
    },
    moveTo(x, y) {
      currentPath.push({ op: "moveTo", x, y });
    },
    lineTo(x, y) {
      currentPath.push({ op: "lineTo", x, y });
    },
    arc(x, y, r, startAngle, endAngle) {
      currentPath.push({ op: "arc", x, y, r, startAngle, endAngle });
      this.arcs.push({
        x,
        y,
        r,
        fillStyle: String(this.fillStyle),
        globalAlpha: this.globalAlpha
      });
    },
    fill() {
      this.fills.push({
        fillStyle: String(this.fillStyle),
        globalAlpha: this.globalAlpha,
        ops: currentPath.slice()
      });
    },
    stroke() {
      this.strokes.push({
        strokeStyle: String(this.strokeStyle),
        lineWidth: this.lineWidth,
        ops: currentPath.slice()
      });
    },
    resetLog() {
      this.fillRects = [];
      this.strokeRects = [];
      this.texts = [];
      this.drawImages = [];
      this.arcs = [];
      this.strokes = [];
      this.fills = [];
    }
  };
}

function bootBundleVm(opts) {
  const options = opts || {};
  let nowVal = typeof options.initialNowMs === "number" ? options.initialNowMs : 1000;
  let nextRafId = 1;
  const rafQueue = {};
  const canceledRafs = [];
  const createdCanvases = [];
  const createdImages = [];
  const runtimeErrors = [];

  const origConsoleError = console.error;
  console.error = function (...args) {
    runtimeErrors.push(args.map((a) => String(a)).join(" "));
  };

  globalThis.performance = {
    now() {
      return nowVal;
    }
  };

  globalThis.requestAnimationFrame = function (fn) {
    const id = nextRafId;
    nextRafId += 1;
    rafQueue[id] = fn;
    return id;
  };

  globalThis.cancelAnimationFrame = function (id) {
    canceledRafs.push(id);
    delete rafQueue[id];
  };

  globalThis.Image = function MockImage() {
    const img = {
      _src: "",
      onload: null,
      complete: true,
      naturalWidth: 32,
      naturalHeight: 32,
      width: 32,
      height: 32
    };
    Object.defineProperty(img, "src", {
      get() {
        return this._src;
      },
      set(v) {
        this._src = String(v || "");
      }
    });
    createdImages.push(img);
    return img;
  };

  function makeCanvas() {
    const ctx2d = createMockContext2D();
    const listeners = {};
    let boundingRect = options.boundingRect || null;
    const canvas = {
      tagName: "CANVAS",
      width: 0,
      height: 0,
      style: { cssText: "", cursor: "" },
      parentNode: null,
      getContext(kind) {
        return kind === "2d" ? ctx2d : null;
      },
      getBoundingClientRect() {
        return boundingRect || {
          left: 0,
          top: 0,
          width: this.width || 960,
          height: this.height || 520
        };
      },
      setBoundingRect(rect) {
        boundingRect = rect;
      },
      addEventListener(type, fn) {
        if (!listeners[type]) listeners[type] = [];
        listeners[type].push(fn);
      },
      removeEventListener(type, fn) {
        if (!listeners[type]) return;
        listeners[type] = listeners[type].filter((cb) => cb !== fn);
      },
      dispatch(type, ev) {
        const handlers = (listeners[type] || []).slice();
        for (let i = 0; i < handlers.length; i += 1) {
          try {
            handlers[i](ev || {});
          } catch (err) {
            runtimeErrors.push(String(err && err.stack ? err.stack : err));
          }
        }
      },
      listenerCount(type) {
        return (listeners[type] || []).length;
      },
      _ctx: ctx2d
    };
    createdCanvases.push(canvas);
    return canvas;
  }

  function makeContainer() {
    return {
      children: [],
      appendChild(child) {
        if (child) {
          child.parentNode = this;
          this.children.push(child);
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
      }
    };
  }

  globalThis.document = {
    createElement(tag) {
      if (String(tag).toLowerCase() === "canvas") {
        return makeCanvas();
      }
      return { tagName: String(tag).toUpperCase(), style: {}, children: [] };
    }
  };

  delete globalThis.Phaser;
  delete globalThis.OUTTHINK_DATA;
  delete globalThis.OUTTHINK_FALLBACK_DATA;
  delete globalThis.OUTTHINK_ANNOTATIONS;
  delete globalThis.OUTTHINK_PERSONAS;
  delete globalThis.OUTTHINK_ASSETS;
  delete globalThis.OUTTHINK_CHATTER;
  delete globalThis.getOutthinkChatter;
  delete globalThis.OutThinkEngine;
  delete globalThis.OutThinkScene;

  globalThis.window = {
    document: globalThis.document,
    onerror(msg) {
      runtimeErrors.push(String(msg));
    }
  };

  if (options.assets) {
    globalThis.window.OUTTHINK_ASSETS = options.assets;
  }
  if (options.data) {
    globalThis.window.OUTTHINK_DATA = options.data;
  }
  if (options.fallbackData) {
    globalThis.window.OUTTHINK_FALLBACK_DATA = options.fallbackData;
  }
  if (options.annotations) {
    globalThis.window.OUTTHINK_ANNOTATIONS = options.annotations;
  }
  if (options.personas) {
    globalThis.window.OUTTHINK_PERSONAS = options.personas;
  }

  const order = Array.isArray(options.loadOrder)
    ? options.loadOrder
    : ["chatter", "engine", "scene"];
  const pathByMod = {
    chatter: process.env.OUTTHINK_CHATTER_PATH,
    engine: process.env.OUTTHINK_ENGINE_PATH,
    scene: process.env.OUTTHINK_SCENE_PATH
  };

  if (Array.isArray(options.optionalPreloadPaths)) {
    for (let i = 0; i < options.optionalPreloadPaths.length; i += 1) {
      const optPath = options.optionalPreloadPaths[i];
      try {
        delete require.cache[require.resolve(optPath)];
        require(optPath);
      } catch (err) {
        runtimeErrors.push(String(err && err.stack ? err.stack : err));
      }
    }
  }

  const loaded = {};
  for (let i = 0; i < order.length; i += 1) {
    const key = order[i];
    const modPath = pathByMod[key];
    try {
      delete require.cache[require.resolve(modPath)];
      loaded[key] = require(modPath);
    } catch (err) {
      runtimeErrors.push(String(err && err.stack ? err.stack : err));
    }
  }

  function buildSafePreDecisionView(caseObj) {
    return {
      id: caseObj.id,
      title: caseObj.title,
      tier: caseObj.tier,
      seed: caseObj.seed,
      company: caseObj.company,
      decision_day: caseObj.decision_day,
      decision_step: caseObj.decision_step,
      value_at_decision: caseObj.value_at_decision,
      suspects: (caseObj.suspects || []).map((s) => ({
        id: s.id,
        name: s.name,
        dept: s.dept,
        role: s.role,
        clearance: s.clearance,
        eliminated: Boolean(s.eliminated),
        canary_hits: s.canary_hits,
        after_hours_count: s.after_hours_count,
        persona_note: s.persona_note
      })),
      canaries: caseObj.canaries || [],
      leaks: caseObj.leaks || [],
      access_logs: caseObj.access_logs || [],
      comms: caseObj.comms || [],
      tool_steps: caseObj.tool_steps || []
    };
  }

  return {
    Engine: loaded.engine,
    Scene: loaded.scene,
    Chatter: loaded.chatter,
    makeContainer,
    buildSafePreDecisionView,
    createdCanvases,
    createdImages,
    rafQueue,
    canceledRafs,
    runtimeErrors,
    restoreConsole() {
      console.error = origConsoleError;
    },
    advanceNow(deltaMs) {
      nowVal += deltaMs;
      return nowVal;
    },
    runNextRaf(ts) {
      const ids = Object.keys(rafQueue);
      if (ids.length === 0) return false;
      const id = ids[0];
      const cb = rafQueue[id];
      delete rafQueue[id];
      try {
        cb(typeof ts === "number" ? ts : nowVal);
      } catch (err) {
        runtimeErrors.push(String(err && err.stack ? err.stack : err));
      }
      return true;
    }
  };
}
"""


def _run_bundle_js(js_body: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_ENGINE_PATH"] = str(ENGINE_PATH)
    run_env["OUTTHINK_SCENE_PATH"] = str(SCENE_PATH)
    run_env["OUTTHINK_CHATTER_PATH"] = str(CHATTER_PATH)
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        JS_BUNDLE_HARNESS
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
    assert proc.returncode == 0, f"JS runtime failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
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
        if rule.endswith(SLASH):
            if rel_path.startswith(rule):
                return True
        elif rel_path == rule:
            return True
    return False


def test_bundle_boot_orders_phaser_undefined_canvas2d_and_zero_errors():
    assert ENGINE_PATH.is_file()
    assert SCENE_PATH.is_file()
    assert CHATTER_PATH.is_file()

    res = _run_bundle_js(
        """
        const vmHtmlOrder = bootBundleVm({ loadOrder: ["chatter", "engine", "scene"] });
        const winPhaserTypeA = typeof window.Phaser;
        const globPhaserTypeA = typeof globalThis.Phaser;
        const stageA = vmHtmlOrder.makeContainer();
        const sceneA = window.OutThinkScene.create(stageA);
        const canvasA = vmHtmlOrder.createdCanvases[0];
        const ctxA = canvasA._ctx;
        const textsA = ctxA.texts.map((t) => t.text);
        vmHtmlOrder.runNextRaf(1032);
        const errorsA = vmHtmlOrder.runtimeErrors.slice();
        const bindingsA = {
          engineSame: window.OutThinkEngine === vmHtmlOrder.Engine,
          sceneSame: window.OutThinkScene === vmHtmlOrder.Scene,
          chatterSame: window.OUTTHINK_CHATTER === vmHtmlOrder.Chatter,
          chatterFnSame: window.getOutthinkChatter === vmHtmlOrder.Chatter.getOutthinkChatter
        };
        sceneA.destroy();
        vmHtmlOrder.restoreConsole();

        const vmEngineFirst = bootBundleVm({ loadOrder: ["engine", "scene", "chatter"] });
        const winPhaserTypeB = typeof window.Phaser;
        const stageB = vmEngineFirst.makeContainer();
        const sceneB = window.OutThinkScene.create(stageB);
        const canvasB = vmEngineFirst.createdCanvases[0];
        const errorsB = vmEngineFirst.runtimeErrors.slice();
        sceneB.destroy();
        vmEngineFirst.restoreConsole();

        return {
          winPhaserTypeA,
          globPhaserTypeA,
          winPhaserTypeB,
          bindingsA,
          modeA: sceneA.mode,
          modeB: sceneB.mode,
          widthA: canvasA.width,
          heightA: canvasA.height,
          cssA: canvasA.style.cssText,
          smoothDisabled:
            ctxA.imageSmoothingEnabled === false &&
            ctxA.webkitImageSmoothingEnabled === false &&
            ctxA.mozImageSmoothingEnabled === false,
          fillRectCount: ctxA.fillRects.length,
          textsA,
          lockedCount: textsA.filter((t) => t === "[LOCKED]").length,
          sealedCount: textsA.filter((t) => t === "SEALED UNTIL CALL").length,
          widthB: canvasB.width,
          heightB: canvasB.height,
          errorsA,
          errorsB
        };
        """
    )

    assert res["winPhaserTypeA"] == "undefined"
    assert res["globPhaserTypeA"] == "undefined"
    assert res["winPhaserTypeB"] == "undefined"
    assert res["errorsA"] == []
    assert res["errorsB"] == []
    assert res["bindingsA"] == {
        "engineSame": True,
        "sceneSame": True,
        "chatterSame": True,
        "chatterFnSame": True,
    }
    assert res["modeA"] == "canvas2d"
    assert res["modeB"] == "canvas2d"
    assert res["widthA"] == 960 and res["heightA"] == 520
    assert res["widthB"] == 960 and res["heightB"] == 520
    assert "image-rendering:pixelated" in res["cssA"]
    assert res["smoothDisabled"] is True
    assert res["fillRectCount"] > 200

    texts = set(res["textsA"])
    for expected in (
        "OUT-THINK GEMINI",
        "TIER: READY | SUSPECTS: 0",
        "STATUS: PODS SEALED",
        "[CORKBOARD]",
        "[LEAK WIRE]",
        "[ACCESS]",
        "[COMMS CRT]",
        "[CABINET]",
        "LEAD DETECTIVE",
        "GEMINI MINIMAL",
        "GEMINI LOW",
        "GEMINI MEDIUM",
        "GEMINI HIGH",
        "GEMINI XHIGH",
    ):
        assert expected in texts
    assert res["lockedCount"] >= 5
    assert res["sealedCount"] >= 5


def test_chatter_enrichment_into_engine_and_canvas2d_rendering_with_non_leak():
    res = _run_bundle_js(
        """
        const vm = bootBundleVm();
        const stage = vm.makeContainer();
        const scene = window.OutThinkScene.create(stage);
        const canvas = vm.createdCanvases[0];
        const ctx = canvas._ctx;

        const rawCase = {
          id: "wt-e2e-medium-4",
          title: "Phase Annex Partition",
          tier: "medium",
          seed: 4,
          company: "Northstar Bio",
          decision_day: 5,
          decision_step: 8,
          value_at_decision: 0.68,
          true_mole: "e03",
          suspects: [
            {
              id: "e01",
              name: "Ari Lindholm",
              dept: "Assay Ops",
              role: "Lab Lead",
              eliminated: true,
              canary_hits: 0,
              after_hours_count: 0
            },
            {
              id: "e02",
              name: "Mina Korhonen",
              dept: "Clinical Data",
              role: "Biostatistician",
              eliminated: false,
              canary_hits: 1,
              after_hours_count: 1
            },
            {
              id: "e03",
              name: "Timo Salo",
              dept: "Partner Relations",
              role: "Alliances Manager",
              eliminated: false,
              canary_hits: 1,
              after_hours_count: 2
            }
          ],
          canaries: [
            {
              canary_id: "c_annex",
              doc_id: "doc_annex",
              day_planted: 3,
              variants: { A: ["e01"], B: ["e02", "e03"] },
              leaked_variant: "B"
            }
          ],
          leaks: [
            {
              day: 4,
              doc_id: "doc_annex",
              canary_id: "c_annex",
              leaked_variant: "B",
              channel: "newsletter",
              summary: "Variant B wording appeared in an industry brief."
            }
          ]
        };

        const chatterWithMoleE03 = window.getOutthinkChatter({
          tier: rawCase.tier,
          seed: rawCase.seed,
          suspectId: "e02",
          dept: "Clinical Data",
          role: "Biostatistician",
          afterHoursCount: 1,
          suspects: rawCase.suspects,
          true_mole: "e03",
          secret: "CANARY_SECRET_TOKEN_44"
        });

        const chatterWithMoleE01 = window.getOutthinkChatter({
          tier: rawCase.tier,
          seed: rawCase.seed,
          suspectId: "e02",
          dept: "Clinical Data",
          role: "Biostatistician",
          afterHoursCount: 1,
          suspects: rawCase.suspects,
          true_mole: "e01",
          secret: "DIFFERENT_SECRET_99"
        });

        const enrichedMessages = chatterWithMoleE03.chatter
          .map((item) => ({
            day: item.day,
            kind: item.kind,
            speaker: item.speaker_role,
            topic: item.topic,
            text: item.text
          }))
          .concat(
            chatterWithMoleE03.rumors.map((rum) => ({
              day: rum.day,
              kind: rum.kind,
              speaker: rum.speaker_role,
              topic: rum.topic,
              text: rum.text
            }))
          );

        const enrichedInterviews = rawCase.suspects.map((s) => {
          const iv = chatterWithMoleE03.interviews_by_suspect[s.id];
          return {
            day: rawCase.decision_day,
            employee: s.id,
            topic: iv.question,
            response: iv.response
          };
        });

        const dataset = window.OutThinkEngine.loadDataset({
          data: {
            cases: [
              Object.assign({}, rawCase, {
                comms: enrichedMessages,
                interviews: enrichedInterviews
              })
            ]
          },
          personas: {
            "medium:4": {
              e02: "Verifies trial sensitivity tables before morning standup.",
              e03: "Prepares external partner diligence decks on tight timelines."
            }
          }
        });

        const normCase = dataset.cases[0];
        const safeView = vm.buildSafePreDecisionView(normCase);

        ctx.resetLog();
        scene.setCase(safeView);
        const initialTexts = ctx.texts.map((t) => t.text);
        const dimmedRects = ctx.fillRects.filter((r) => Math.abs(r.globalAlpha - 0.36) < 0.001).length;

        ctx.resetLog();
        scene.setSelectedSuspect("e02");
        const e02Texts = ctx.texts.map((t) => t.text);

        ctx.resetLog();
        scene.setSelectedSuspect("e03");
        const e03Texts = ctx.texts.map((t) => t.text);

        const errors = vm.runtimeErrors.slice();
        scene.destroy();
        vm.restoreConsole();

        return {
          phaserUndefined: typeof window.Phaser === "undefined",
          counterfactualIdentical:
            JSON.stringify(chatterWithMoleE03) === JSON.stringify(chatterWithMoleE01),
          chatterBundle: chatterWithMoleE03,
          normCommsCount: normCase.comms.length,
          interviewCommsCount: normCase.comms.filter((m) => m.kind === "interview").length,
          rumorCommsCount: normCase.comms.filter((m) => m.kind === "rumor_distractor").length,
          personasMerged: normCase.suspects.map((s) => s.persona_note),
          initialTexts,
          dimmedRects,
          e02Texts,
          e03Texts,
          expectedE02Iv: chatterWithMoleE03.interviews_by_suspect.e02.response,
          expectedE03Iv: chatterWithMoleE03.interviews_by_suspect.e03.response,
          errors
        };
        """
    )

    assert res["phaserUndefined"] is True
    assert res["errors"] == []
    assert res["counterfactualIdentical"] is True
    assert res["normCommsCount"] == 9
    assert res["interviewCommsCount"] == 3
    assert res["rumorCommsCount"] == 2
    assert res["personasMerged"][1] == "Verifies trial sensitivity tables before morning standup."
    assert res["personasMerged"][2] == "Prepares external partner diligence decks on tight timelines."

    init_texts = set(res["initialTexts"])
    assert "Phase Annex Partition" in init_texts
    assert "TIER: MEDIUM | SUSPECTS: 3" in init_texts
    assert "STATUS: PODS SEALED" in init_texts
    assert "CLR" in init_texts
    assert res["dimmedRects"] >= 4
    assert not any(t.startswith("MOLE ") for t in init_texts)

    e02_iv = res["expectedE02Iv"]
    e03_iv = res["expectedE03Iv"]
    assert "one after-hours" in e02_iv
    assert "two after-hours" in e03_iv

    e02_bubble_clip = e02_iv[:30] + ".."
    e02_note_clip = "NOTE: " + e02_iv[:42] + ".."
    assert "Mina Korhonen [Clinical Data]" in res["e02Texts"]
    assert e02_bubble_clip in res["e02Texts"]
    assert "DOSSIER: Mina Korhonen (e02) | Biostatistician" in res["e02Texts"]
    assert "DEPT: Clinical Data | CANARY HITS: 1 | AFTER-HOURS: 1" in res["e02Texts"]
    assert e02_note_clip in res["e02Texts"]

    e03_bubble_clip = e03_iv[:30] + ".."
    e03_note_clip = "NOTE: " + e03_iv[:42] + ".."
    assert "Timo Salo [Partner Relations]" in res["e03Texts"]
    assert e03_bubble_clip in res["e03Texts"]
    assert "DOSSIER: Timo Salo (e03) | Alliances Manager" in res["e03Texts"]
    assert e03_note_clip in res["e03Texts"]

    bundle = res["chatterBundle"]
    checked_strings = [m["text"] for m in bundle["chatter"]] + [r["text"] for r in bundle["rumors"]]
    for iv in bundle["interviews_by_suspect"].values():
        checked_strings.append(iv["question"])
        checked_strings.append(iv["response"])
    for text_item in checked_strings:
        assert lint_text(text_item) == []
        assert TRUTH_WORDS.search(text_item) is None
        assert "CANARY_SECRET_TOKEN_44" not in text_item


def test_five_gemini_thinking_pods_reveal_spotlight_and_interactive_pod_selection():
    res = _run_bundle_js(
        """
        const clickedSuspects = [];
        const clickedTabs = [];
        const clickedPods = [];

        const vm = bootBundleVm({
          initialNowMs: 2000,
          boundingRect: { left: 10, top: 20, width: 480, height: 260 },
          annotations: {
            "run-min-7": {
              failure_tag: "premature_accusation",
              analyst_quote: "Accused first after-hours suspect before splitting variant holders."
            },
            "hard:7:low": {
              failure_tag: "rumor_distraction",
              analyst_quote: "Followed hallway schedule gossip instead of canary recipient set."
            }
          }
        });

        const stage = vm.makeContainer();
        const scene = window.OutThinkScene.create(stage, {
          onSelectSuspect(id) { clickedSuspects.push(id); },
          onSelectTab(tab) { clickedTabs.push(tab); },
          onSelectThinkingPod(pod) { clickedPods.push(pod); }
        });
        const canvas = vm.createdCanvases[0];
        const ctx = canvas._ctx;

        const chatterBundle = window.getOutthinkChatter({
          tier: "hard",
          seed: 7,
          suspectId: "e04",
          dept: "Strategy",
          role: "Director",
          afterHoursCount: 3
        });

        const ds = window.OutThinkEngine.loadDataset({
          data: {
            cases: [
              {
                id: "carbon-hard-7",
                title: "Helios Board Dossier Leak",
                tier: "hard",
                seed: 7,
                company: "Helios Genomics",
                decision_day: 6,
                decision_step: 11,
                value_at_decision: 0.72,
                true_mole: "e04",
                suspects: [
                  { id: "e01", name: "Sami Virtanen", dept: "Infra", role: "SRE", eliminated: true, canary_hits: 0, after_hours_count: 1 },
                  { id: "e02", name: "Aino Korhonen", dept: "Infra", role: "Lead", eliminated: false, canary_hits: 1, after_hours_count: 0 },
                  { id: "e03", name: "Mikko Salo", dept: "Strategy", role: "VP", eliminated: false, canary_hits: 0, after_hours_count: 2 },
                  { id: "e04", name: "Noora Laine", dept: "Strategy", role: "Director", eliminated: false, canary_hits: 2, after_hours_count: 3 }
                ],
                comms: chatterBundle.chatter.map((c) => ({
                  day: c.day,
                  kind: c.kind,
                  speaker: c.speaker_role,
                  topic: c.topic,
                  text: c.text
                })),
                interviews: [
                  {
                    day: 6,
                    employee: "e04",
                    topic: chatterBundle.interview.question,
                    response: chatterBundle.interview.response
                  }
                ],
                solver: {
                  posterior: { e04: 0.92, e02: 0.06, e03: 0.02, e01: 0.0 },
                  top_suspect: "e04",
                  top_prob: 0.92,
                  recommended_call: "accuse",
                  final_accused: "e04",
                  final_day: 6,
                  final_score: 0.72,
                  correct: true
                },
                thinking_levels: [
                  { thinking_level: "x_high", run_id: "run-xh-7", accused: "e04", score: 0.72, cost_usd: 0.0492, thinking_tokens: 5400, correct: true },
                  { thinking_level: "min", run_id: "run-min-7", accused: "e02", score: -1.0, cost_usd: 0.0024, thinking_tokens: 96, correct: false },
                  { thinking_level: "med", run_id: "run-med-7", accused: null, call_at_t: "hold_fire", score: 0.44, cost_usd: 0.0118, thinking_tokens: 1350, correct: false },
                  { thinking_level: "lo", run_id: "run-low-7", accused: "e01", score: -1.0, cost_usd: 0.0051, thinking_tokens: 380, correct: false },
                  { thinking_level: "hi", run_id: "run-high-7", accused: "e04", score: 0.72, cost_usd: 0.0264, thinking_tokens: 2950, correct: true }
                ]
              }
            ]
          }
        });

        const fullCase = ds.cases[0];
        const safeView = vm.buildSafePreDecisionView(fullCase);

        ctx.resetLog();
        scene.setCase(safeView);
        scene.setHighlightCandidates(["e02", "e04"]);
        const preTexts = ctx.texts.map((t) => t.text);
        const preLockedCount = preTexts.filter((t) => t === "[LOCKED]").length;
        const preCandidateStrokes = ctx.strokeRects.filter(
          (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
        ).length;

        const evalRes = window.OutThinkEngine.evaluateCall(fullCase, {
          action: "accuse",
          suspectId: "e04"
        });

        ctx.resetLog();
        scene.showReveal(evalRes, fullCase);
        const startSpot = ctx.arcs.find((a) => a.r === 34);

        ctx.resetLog();
        vm.advanceNow(800);
        vm.runNextRaf(2800);
        const endSpot = ctx.arcs.find((a) => a.r === 34);
        const revealTexts = ctx.texts.map((t) => t.text);
        const rightBadgeCount = revealTexts.filter((t) => t === "RIGHT").length;
        const wrongBadgeCount = revealTexts.filter((t) => t === "WRONG").length;

        const toClient = (lx, ly) => ({ clientX: 10 + lx * 0.5, clientY: 20 + ly * 0.5 });
        const podYs = [136, 218, 300, 382, 464];
        const podStrokeYs = [99, 181, 263, 345, 427];
        const podSelectionVerified = [];
        for (let i = 0; i < podYs.length; i += 1) {
          ctx.resetLog();
          canvas.dispatch("click", toClient(832, podYs[i]));
          const hasGoldBorder = ctx.strokeRects.some(
            (r) =>
              r.x === 719 &&
              r.y === podStrokeYs[i] &&
              r.strokeStyle === H + "fde047" &&
              r.lineWidth === 2
          );
          podSelectionVerified.push(hasGoldBorder);
        }

        const propXs = [153, 279, 405, 531, 655];
        const tabLabelsAfterClick = [];
        for (let i = 0; i < propXs.length; i += 1) {
          ctx.resetLog();
          canvas.dispatch("click", toClient(propXs[i], 47));
          const tabLine = ctx.texts.find((t) => t.text.startsWith("TAB: "));
          tabLabelsAfterClick.push(tabLine ? tabLine.text : "");
        }

        ctx.resetLog();
        scene.clearReveal();
        const resealedTexts = ctx.texts.map((t) => t.text);

        const errors = vm.runtimeErrors.slice();
        scene.destroy();
        vm.restoreConsole();

        return {
          phaserUndefined: typeof window.Phaser === "undefined",
          sortedLevels: fullCase.thinking_levels.map((lv) => lv.thinking_level),
          minTag: fullCase.thinking_levels[0].failure_tag,
          lowTag: fullCase.thinking_levels[1].failure_tag,
          preLockedCount,
          preCandidateStrokes,
          evalVerdict: evalRes.verdictLabel,
          evalScore: evalRes.score,
          evalOptimal: evalRes.optimal,
          startSpot: startSpot ? { x: startSpot.x, y: startSpot.y } : null,
          endSpot: endSpot ? { x: endSpot.x, y: endSpot.y } : null,
          revealTexts,
          rightBadgeCount,
          wrongBadgeCount,
          clickedPods,
          podSelectionVerified,
          clickedTabs,
          tabLabelsAfterClick,
          resealedLockedCount: resealedTexts.filter((t) => t === "[LOCKED]").length,
          resealedStatus: resealedTexts.includes("STATUS: PODS SEALED"),
          errors
        };
        """
    )

    assert res["phaserUndefined"] is True
    assert res["errors"] == []
    assert res["sortedLevels"] == ["minimal", "low", "medium", "high", "xhigh"]
    assert res["minTag"] == "premature_accusation"
    assert res["lowTag"] == "rumor_distraction"
    assert res["preLockedCount"] >= 5
    assert res["preCandidateStrokes"] == 2
    assert res["evalVerdict"] == "OPTIMAL ACCUSATION"
    assert res["evalScore"] == pytest.approx(0.72)
    assert res["evalOptimal"] is True
    assert res["startSpot"] == {"x": 140, "y": 390}
    assert res["endSpot"] == {"x": 274, "y": 318}

    rev_texts = set(res["revealTexts"])
    assert "[LOCKED]" not in rev_texts
    assert "STATUS: CASE REVEALED" in rev_texts
    assert "MOLE e04" in rev_texts
    assert "SOLVER TOP-3 POSTERIOR | OPTIMAL ACCUSATION" in rev_texts
    assert "1. e04" in rev_texts and "92.0%" in rev_texts
    assert "2. e02" in rev_texts and "6.0%" in rev_texts
    assert "3. e03" in rev_texts and "2.0%" in rev_texts

    for pod_label in ("MINIMAL", "LOW", "MEDIUM", "HIGH", "XHIGH"):
        assert pod_label in rev_texts
    for acc_text in ("ACC: e02", "ACC: e01", "ACC: HOLD", "ACC: e04"):
        assert acc_text in rev_texts
    for cost_text in ("$0.0024", "$0.0051", "$0.0118", "$0.0264", "$0.0492"):
        assert cost_text in rev_texts

    assert res["rightBadgeCount"] == 2
    assert res["wrongBadgeCount"] == 3
    assert res["clickedPods"] == ["minimal", "low", "medium", "high", "xhigh"]
    assert res["podSelectionVerified"] == [True, True, True, True, True]
    assert res["clickedTabs"] == ["canaries", "leaks", "access", "comms", "steps"]
    assert res["tabLabelsAfterClick"] == [
        "TAB: CANARIES",
        "TAB: LEAKS",
        "TAB: ACCESS",
        "TAB: COMMS",
        "TAB: STEPS",
    ]
    assert res["resealedLockedCount"] == 5
    assert res["resealedStatus"] is True


def test_multi_case_episode_loop_scoreboard_aggregation_and_clean_teardown():
    res = _run_bundle_js(
        """
        const vm = bootBundleVm();
        const stage = vm.makeContainer();
        const scene = window.OutThinkScene.create(stage);
        const canvas = vm.createdCanvases[0];
        const ctx = canvas._ctx;
        const scoreboard = window.OutThinkEngine.createScoreboard();

        const rawCases = [
          {
            id: "loop-easy-1",
            title: "Sprint Brief Leak",
            tier: "easy",
            seed: 1,
            value_at_decision: 0.8,
            true_mole: "e02",
            suspects: [
              { id: "e01", name: "Sami Virtanen", dept: "Infra", role: "SRE", eliminated: true },
              { id: "e02", name: "Mina Korhonen", dept: "Assay", role: "Lead", eliminated: false }
            ],
            solver: {
              posterior: { e02: 0.98, e01: 0.02 },
              top_suspect: "e02",
              top_prob: 0.98,
              recommended_call: "accuse",
              final_score: 0.8,
              correct: true
            },
            thinking_levels: [
              { thinking_level: "minimal", accused: "e01", correct: false, score: -1.0, cost_usd: 0.002, thinking_tokens: 80 },
              { thinking_level: "low", accused: "e02", correct: true, score: 0.8, cost_usd: 0.004, thinking_tokens: 300 },
              { thinking_level: "medium", accused: "e02", correct: true, score: 0.8, cost_usd: 0.009, thinking_tokens: 900 },
              { thinking_level: "high", accused: "e02", correct: true, score: 0.8, cost_usd: 0.021, thinking_tokens: 2200 },
              { thinking_level: "xhigh", accused: "e02", correct: true, score: 0.8, cost_usd: 0.041, thinking_tokens: 4400 }
            ]
          },
          {
            id: "loop-medium-6",
            title: "Ambiguous Dual-Recipient Split",
            tier: "medium",
            seed: 6,
            value_at_decision: 0.5,
            true_mole: "e04",
            suspects: [
              { id: "e03", name: "Timo Salo", dept: "Alliances", role: "Manager", eliminated: false },
              { id: "e04", name: "Noora Laine", dept: "Strategy", role: "Director", eliminated: false }
            ],
            solver: {
              posterior: { e04: 0.52, e03: 0.48 },
              top_suspect: "e04",
              top_prob: 0.52,
              break_even_prob: 0.6667,
              ev_hold_fire: 0.45,
              recommended_call: "hold_fire",
              final_score: 0.45,
              correct: true
            },
            thinking_levels: [
              { thinking_level: "minimal", accused: "e03", correct: false, score: -1.0, cost_usd: 0.003, thinking_tokens: 90 },
              { thinking_level: "low", accused: "e03", correct: false, score: -1.0, cost_usd: 0.005, thinking_tokens: 350 },
              { thinking_level: "medium", accused: "e03", correct: false, score: -1.0, cost_usd: 0.011, thinking_tokens: 1100 },
              { thinking_level: "high", call_at_t: "hold_fire", accused: "e04", correct: true, score: 0.45, cost_usd: 0.024, thinking_tokens: 2600 },
              { thinking_level: "xhigh", call_at_t: "hold_fire", accused: "e04", correct: true, score: 0.45, cost_usd: 0.046, thinking_tokens: 4900 }
            ]
          }
        ].map((rc) => {
          const wt = window.getOutthinkChatter({
            tier: rc.tier,
            seed: rc.seed,
            suspects: rc.suspects
          });
          return Object.assign({}, rc, {
            comms: wt.chatter.map((c) => ({
              day: c.day,
              kind: c.kind,
              speaker: c.speaker_role,
              topic: c.topic,
              text: c.text
            })),
            interviews: rc.suspects.map((s) => ({
              day: 4,
              employee: s.id,
              topic: wt.interviews_by_suspect[s.id].question,
              response: wt.interviews_by_suspect[s.id].response
            }))
          });
        });

        const ds = window.OutThinkEngine.loadDataset({ data: { cases: rawCases } });

        scene.setCase(vm.buildSafePreDecisionView(ds.cases[0]));
        scene.setSelectedSuspect("e02");
        scene.setHighlightCandidates(["e02"]);
        const res0 = window.OutThinkEngine.evaluateCall(ds.cases[0], {
          action: "accuse",
          suspectId: "e02"
        });
        scoreboard.record(ds.cases[0].id, res0, ds.cases[0]);
        scene.showReveal(res0, ds.cases[0]);

        ctx.resetLog();
        scene.setCase(vm.buildSafePreDecisionView(ds.cases[1]));
        const case2PreTexts = ctx.texts.map((t) => t.text);
        const case2HighlightsCleared =
          ctx.strokeRects.filter(
            (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
          ).length === 0;

        const res1 = window.OutThinkEngine.evaluateCall(ds.cases[1], {
          action: "hold_fire"
        });
        scoreboard.record(ds.cases[1].id, res1, ds.cases[1]);
        ctx.resetLog();
        scene.showReveal(res1, ds.cases[1]);
        const case2RevealTexts = ctx.texts.map((t) => t.text);

        const summary = scoreboard.getSummary();
        const resetSummary = scoreboard.reset();

        scene.destroy();
        ctx.resetLog();
        canvas.dispatch("click", { clientX: 200, clientY: 200 });
        const drawsAfterDestroy = ctx.fillRects.length + ctx.texts.length;
        const listenersAfterDestroy =
          canvas.listenerCount("mousemove") +
          canvas.listenerCount("mouseleave") +
          canvas.listenerCount("click");

        const errors = vm.runtimeErrors.slice();
        vm.restoreConsole();

        return {
          case2PreSealed: case2PreTexts.includes("STATUS: PODS SEALED"),
          case2ResetFocus: case2PreTexts.includes("SELECT A DESK"),
          case2HighlightsCleared,
          case2RevealMole: case2RevealTexts.includes("MOLE e04"),
          summary,
          resetCasesPlayed: resetSummary.casesPlayed,
          childrenAfterDestroy: stage.children.length,
          drawsAfterDestroy,
          listenersAfterDestroy,
          errors
        };
        """
    )

    assert res["errors"] == []
    assert res["case2PreSealed"] is True
    assert res["case2ResetFocus"] is True
    assert res["case2HighlightsCleared"] is True
    assert res["case2RevealMole"] is True

    summary = res["summary"]
    assert summary["casesPlayed"] == 2
    assert summary["judge"]["scoreSum"] == pytest.approx(1.25)
    assert summary["judge"]["rightCount"] == 2
    assert summary["judge"]["optimalCount"] == 2
    assert summary["solver"]["scoreSum"] == pytest.approx(1.25)

    by_lv = summary["byLevel"]
    assert by_lv["minimal"]["scoreSum"] == pytest.approx(-2.0)
    assert by_lv["minimal"]["judgeOutscoredCount"] == 2
    assert by_lv["low"]["judgeOutscoredCount"] == 1
    assert by_lv["medium"]["judgeOutscoredCount"] == 1
    assert by_lv["high"]["scoreSum"] == pytest.approx(1.25)
    assert by_lv["high"]["accuracy"] == pytest.approx(1.0)
    assert by_lv["high"]["totalCostUsd"] == pytest.approx(0.045)
    assert by_lv["xhigh"]["totalThinkingTokens"] == 9300

    assert res["resetCasesPlayed"] == 0
    assert res["childrenAfterDestroy"] == 0
    assert res["drawsAfterDestroy"] == 0
    assert res["listenersAfterDestroy"] == 0


def test_default_dataset_or_present_data_bundles_render_and_reveal_cleanly():
    optional_files = [
        DEMO_DIR / "assets" / "manifest.js",
        DEMO_DIR / "fallback_cases.js",
        DEMO_DIR / "cases.js",
        DEMO_DIR / "annotations.js",
        DEMO_DIR / "personas.js",
    ]
    present_paths = [str(p) for p in optional_files if p.is_file()]

    res = _run_bundle_js(
        """
        const vm = bootBundleVm({ optionalPreloadPaths: PAYLOAD.presentPaths });
        const stage = vm.makeContainer();
        const scene = window.OutThinkScene.create(stage);
        const ctx = vm.createdCanvases[0]._ctx;

        const dataset = window.OutThinkEngine.loadDataset();
        const checkedCases = [];

        for (let i = 0; i < dataset.cases.length; i += 1) {
          const c = dataset.cases[i];
          const firstSuspect = c.suspects[0] || { id: "e01", dept: "Ops", role: "Staff", after_hours_count: 0 };
          const wt = window.getOutthinkChatter({
            tier: c.tier,
            seed: c.seed,
            suspectId: firstSuspect.id,
            dept: firstSuspect.dept,
            role: firstSuspect.role,
            afterHoursCount: firstSuspect.after_hours_count,
            suspects: c.suspects
          });

          const safeView = vm.buildSafePreDecisionView(c);
          ctx.resetLog();
          scene.setCase(safeView);
          const preLocked = ctx.texts.filter((t) => t.text === "[LOCKED]").length;

          const call =
            c.solver && c.solver.recommended_call === "accuse" && c.solver.top_suspect
              ? { action: "accuse", suspectId: c.solver.top_suspect }
              : { action: "hold_fire" };
          const evalRes = window.OutThinkEngine.evaluateCall(c, call);

          ctx.resetLog();
          scene.showReveal(evalRes, c);
          const postTexts = ctx.texts.map((t) => t.text);
          const podBadges = postTexts.filter((t) => t === "RIGHT" || t === "WRONG").length;

          checkedCases.push({
            id: c.id,
            chatterCount: wt.chatter.length,
            rumorCount: wt.rumors.length,
            preLocked,
            revealedBanner: postTexts.includes("STATUS: CASE REVEALED"),
            podBadges
          });
        }

        const errors = vm.runtimeErrors.slice();
        scene.destroy();
        vm.restoreConsole();

        return {
          phaserUndefined: typeof window.Phaser === "undefined",
          source: dataset.source,
          count: dataset.count,
          checkedCases,
          errors
        };
        """,
        {"presentPaths": present_paths},
    )

    assert res["phaserUndefined"] is True
    assert res["errors"] == []
    assert res["count"] >= 1
    assert len(res["checkedCases"]) == res["count"]
    for item in res["checkedCases"]:
        assert item["chatterCount"] == 4
        assert item["rumorCount"] == 2
        assert item["preLocked"] >= 5
        assert item["revealedBanner"] is True
        assert item["podBadges"] == 5


def test_strict_hygiene_comments_dashes_offline_and_protected_paths():
    self_path = Path(__file__).resolve()
    targets = (ENGINE_PATH, SCENE_PATH, CHATTER_PATH, self_path)
    for target in targets:
        src = target.read_text(encoding="utf-8")
        assert EM_DASH not in src, f"em dash in {target}"
        assert EN_DASH not in src, f"en dash in {target}"
        assert FIG_DASH not in src, f"figure dash in {target}"
        assert HORIZ_BAR not in src, f"horizontal bar in {target}"
        assert LINE_COMMENT not in src, f"line comment token in {target}"
        assert BLOCK_COMMENT_OPEN not in src, f"block comment token in {target}"
        assert HTML_COMMENT_OPEN not in src, f"html comment token in {target}"
        assert FETCH_CALL not in src, f"network call token in {target}"
        assert XHR_TOKEN not in src, f"XHR token in {target}"

    for js_target in (ENGINE_PATH, SCENE_PATH, CHATTER_PATH):
        js_src = js_target.read_text(encoding="utf-8")
        assert _find_js_comments(js_src) == [], f"JS comment found in {js_target}"

    py_src = self_path.read_text(encoding="utf-8")
    assert HASH_CHAR not in py_src
    py_comments = [
        tok for tok in tokenize.generate_tokens(io.StringIO(py_src).readline) if tok.type == tokenize.COMMENT
    ]
    assert py_comments == []

    tree = ast.parse(py_src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "genai" not in alias.name and "google" not in alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert "genai" not in node.module and "google" not in node.module

    rules = _load_protected_rules()
    assert rules

    checked_paths = {p.relative_to(ROOT).as_posix() for p in targets}

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if status_proc.returncode == 0:
        for line in status_proc.stdout.splitlines():
            if len(line) > 3:
                entry = line[3:].strip()
                if " -> " in entry:
                    entry = entry.split(" -> ", 1)[1].strip()
                checked_paths.add(entry)

    base_proc = subprocess.run(
        ["git", "merge-base", "origin/justSilas", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if base_proc.returncode == 0 and base_proc.stdout.strip():
        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", f"{base_proc.stdout.strip()}..HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if diff_proc.returncode == 0:
            for rel in diff_proc.stdout.splitlines():
                if rel.strip():
                    checked_paths.add(rel.strip())

    violations = sorted(rel for rel in checked_paths if _matches_protected_rule(rel, rules))
    assert violations == [], f"protected-paths.txt violations: {violations}"
