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

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
SCENE_PATH = DEMO_DIR / "scene.js"
ENGINE_PATH = DEMO_DIR / "engine.js"
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


JS_PRELUDE = """
const H = String.fromCharCode(35);

function createMockContext2D() {
  const stack = [];
  let currentPath = [];
  const ctx = {
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
  return ctx;
}

function setupSceneEnv(opts) {
  const options = opts || {};
  let nowVal = typeof options.initialNowMs === "number" ? options.initialNowMs : 1000;
  let nextRafId = 1;
  const rafQueue = {};
  const canceledRafs = [];
  const createdImages = [];
  const createdCanvases = [];

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

  const imageRules = options.imageRules || {};
  globalThis.Image = function MockImage() {
    const rec = {
      _src: "",
      onload: null,
      complete: options.defaultImageComplete !== false,
      naturalWidth: 32,
      naturalHeight: 32,
      width: 32,
      height: 32
    };
    Object.defineProperty(rec, "src", {
      get() {
        return this._src;
      },
      set(val) {
        this._src = String(val || "");
        const rule = imageRules[this._src];
        if (rule) {
          if (typeof rule.complete === "boolean") rec.complete = rule.complete;
          if (typeof rule.naturalWidth === "number") {
            rec.naturalWidth = rule.naturalWidth;
            rec.width = rule.naturalWidth;
          }
          if (typeof rule.naturalHeight === "number") {
            rec.naturalHeight = rule.naturalHeight;
            rec.height = rule.naturalHeight;
          }
        }
      }
    });
    createdImages.push(rec);
    return rec;
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
      setBoundingRect(nextRect) {
        boundingRect = nextRect;
      },
      addEventListener(type, fn) {
        if (!listeners[type]) listeners[type] = [];
        listeners[type].push(fn);
      },
      removeEventListener(type, fn) {
        if (!listeners[type]) return;
        listeners[type] = listeners[type].filter((item) => item !== fn);
      },
      dispatch(type, ev) {
        const list = (listeners[type] || []).slice();
        for (let i = 0; i < list.length; i += 1) {
          list[i](ev || {});
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

  globalThis.window = {
    document: globalThis.document
  };
  if (options.assets) {
    globalThis.window.OUTTHINK_ASSETS = options.assets;
  }
  if (options.phaser) {
    globalThis.window.Phaser = options.phaser;
  }
  delete globalThis.OUTTHINK_ASSETS;
  delete globalThis.Phaser;

  const scenePath = process.env.OUTTHINK_SCENE_PATH;
  delete require.cache[require.resolve(scenePath)];
  const SceneMod = require(scenePath);

  return {
    SceneMod,
    makeContainer,
    createdCanvases,
    createdImages,
    rafQueue,
    canceledRafs,
    setNow(ms) {
      nowVal = ms;
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
      cb(typeof ts === "number" ? ts : nowVal);
      return true;
    }
  };
}
"""


def _run_scene_js(js_body: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_SCENE_PATH"] = str(SCENE_PATH)
    run_env["OUTTHINK_ENGINE_PATH"] = str(ENGINE_PATH)
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        JS_PRELUDE
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


def test_create_exports_and_phaser_free_canvas2d_fallback():
    assert SCENE_PATH.is_file()
    res = _run_scene_js(
        """
        const env = setupSceneEnv();
        const winSame = globalThis.window.OutThinkScene === env.SceneMod;
        const container = env.makeContainer();
        const scene = env.SceneMod.create(container);
        const canvas = env.createdCanvases[0];
        const ctx = canvas._ctx;
        const drawnTexts = ctx.texts.map((t) => t.text);

        let phaserAttempts = 0;
        const brokenPhaserEnv = setupSceneEnv({
          phaser: {
            CANVAS: 1,
            Game: function BrokenGame() {
              phaserAttempts += 1;
              throw new Error("Phaser unavailable in headless canvas check");
            }
          }
        });
        const fallbackContainer = brokenPhaserEnv.makeContainer();
        const fallbackScene = brokenPhaserEnv.SceneMod.create(fallbackContainer);
        const fallbackCanvas = brokenPhaserEnv.createdCanvases[0];

        const containerlessEnv = setupSceneEnv();
        const containerlessScene = containerlessEnv.SceneMod.create(null);

        delete globalThis.window;
        delete globalThis.OutThinkScene;
        delete require.cache[require.resolve(process.env.OUTTHINK_SCENE_PATH)];
        const rootOnlyMod = require(process.env.OUTTHINK_SCENE_PATH);
        const rootSame = globalThis.OutThinkScene === rootOnlyMod;

        return {
          winSame,
          rootSame,
          createFnType: typeof env.SceneMod.create,
          mode: scene.mode,
          mountedCount: container.children.length,
          width: canvas.width,
          height: canvas.height,
          cssText: canvas.style.cssText,
          smoothMain: ctx.imageSmoothingEnabled,
          smoothWebkit: ctx.webkitImageSmoothingEnabled,
          smoothMoz: ctx.mozImageSmoothingEnabled,
          fillRectCount: ctx.fillRects.length,
          drawnTexts,
          phaserAttempts,
          brokenPhaserMode: fallbackScene.mode,
          brokenPhaserMounted: fallbackContainer.children.length,
          brokenPhaserTextsCount: fallbackCanvas._ctx.texts.length,
          containerlessMode: containerlessScene.mode
        };
        """
    )

    assert res["winSame"] is True
    assert res["rootSame"] is True
    assert res["createFnType"] == "function"
    assert res["mode"] == "canvas2d"
    assert res["mountedCount"] == 1
    assert res["width"] == 960
    assert res["height"] == 520
    assert "image-rendering:pixelated" in res["cssText"]
    assert res["smoothMain"] is False
    assert res["smoothWebkit"] is False
    assert res["smoothMoz"] is False
    assert res["fillRectCount"] > 200

    texts = set(res["drawnTexts"])
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
        "SELECT A DESK",
        "TAB: CANARIES",
        "NOIR GRID 960x520",
        "INVESTIGATION FLOOR BRIEFING",
        "GEMINI MINIMAL",
        "GEMINI LOW",
        "GEMINI MEDIUM",
        "GEMINI HIGH",
        "GEMINI XHIGH",
        "[LOCKED]",
        "SEALED UNTIL CALL",
    ):
        assert expected in texts

    assert res["phaserAttempts"] == 1
    assert res["brokenPhaserMode"] == "canvas2d"
    assert res["brokenPhaserMounted"] == 1
    assert res["brokenPhaserTextsCount"] > 15
    assert res["containerlessMode"] == "canvas2d"


def test_set_case_schema_normalization_eliminated_dimming_and_large_roster():
    res = _run_scene_js(
        """
        const env = setupSceneEnv();
        const container = env.makeContainer();
        const scene = env.SceneMod.create(container);
        const ctx = env.createdCanvases[0]._ctx;

        ctx.resetLog();
        scene.setCase({
          id: "case-hard-7",
          title: "Midnight Assay Leak",
          tier: "hard",
          suspects: [
            {
              id: "e01",
              name: "Sami Virtanen",
              dept: "Infra",
              role: "Principal SRE",
              eliminated: true,
              canary_hits: 0,
              after_hours_count: 1
            },
            {
              id: "e04",
              name: "Noora Laine",
              dept: "Strategy",
              role: "Director",
              eliminated: false,
              canary_hits: 2,
              after_hours_count: 3
            }
          ],
          comms: [
            { speaker: "e04", text: "Need the valuation annex before 07:30." }
          ]
        });

        const caseTexts = ctx.texts.map((t) => t.text);
        const dimmedRects = ctx.fillRects.filter((r) => Math.abs(r.globalAlpha - 0.36) < 0.001);
        const clrTexts = ctx.texts.filter((t) => t.text === "CLR");

        ctx.resetLog();
        scene.setCase({
          id: "alt-med-3",
          title: "Bioreactor Export",
          tier: "medium",
          employees: [
            {
              employeeId: "e02",
              full_name: "Aino Korhonen",
              department: "Assay Ops",
              title: "Scientist",
              is_eliminated: false,
              hits: 1,
              after_hours: 2
            },
            {
              employee_id: "e05",
              full_name: "Mikko Salo",
              team: "Clinical",
              title: "Analyst",
              ruled_out: true,
              hits: 0,
              after_hours: 0
            }
          ],
          chatter: [
            { from: "e02", message: "Batch calibration finished late Tuesday." }
          ]
        });
        scene.setSelectedSuspect("e02");
        const altTexts = ctx.texts.map((t) => t.text);

        const manySuspects = [];
        const depts = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"];
        for (let i = 0; i < 40; i += 1) {
          const id = "e" + String(i + 1).padStart(2, "0");
          manySuspects.push({
            id,
            name: "Staff " + id,
            dept: depts[i % depts.length],
            role: "Engineer"
          });
        }
        ctx.resetLog();
        scene.setCase({
          id: "crowded-40",
          title: "Forty Desk Audit",
          tier: "hard",
          suspects: manySuspects
        });
        const crowdedTexts = ctx.texts.map((t) => t.text);
        const stationTexts = ctx.texts.filter((t) => /^e[0-9][0-9]/.test(t.text));
        const stationYs = stationTexts.map((t) => t.y);

        return {
          caseTexts,
          dimmedRectCount: dimmedRects.length,
          clrCount: clrTexts.length,
          altTexts,
          crowdedHeaderFound: crowdedTexts.includes("TIER: HARD | SUSPECTS: 40"),
          crowdedStationTagCount: stationTexts.length,
          minStationTagY: Math.min.apply(null, stationYs),
          maxStationTagY: Math.max.apply(null, stationYs)
        };
        """
    )

    case_texts = set(res["caseTexts"])
    assert "Midnight Assay Leak" in case_texts
    assert "TIER: HARD | SUSPECTS: 2" in case_texts
    assert "INFRA" in case_texts
    assert "STR.." in case_texts
    assert res["dimmedRectCount"] >= 4
    assert res["clrCount"] == 1

    alt_texts = res["altTexts"]
    assert any("DOSSIER: Aino Korhonen (e02) | Scientist" in t for t in alt_texts)
    assert any("DEPT: Assay Ops | CANARY HITS: 1 | AFTER-HOURS: 2" in t for t in alt_texts)
    assert any("NOTE: Batch calibration finished late Tuesday." in t for t in alt_texts)

    assert res["crowdedHeaderFound"] is True
    assert res["crowdedStationTagCount"] == 40
    assert res["minStationTagY"] >= 100
    assert res["maxStationTagY"] <= 398


def test_select_suspect_bubble_placement_and_scaled_pointer_callbacks():
    res = _run_scene_js(
        """
        const clickedSuspects = [];
        const clickedTabs = [];
        const clickedPods = [];

        const env = setupSceneEnv({
          boundingRect: { left: 20, top: 10, width: 480, height: 260 }
        });
        const container = env.makeContainer();
        const canvasRef = () => env.createdCanvases[0];
        const scene = env.SceneMod.create(container, {
          onSelectSuspect(id) { clickedSuspects.push(id); },
          onSelectTab(tab) { clickedTabs.push(tab); },
          onSelectThinkingPod(pod) { clickedPods.push(pod); }
        });
        const canvas = canvasRef();
        const ctx = canvas._ctx;

        scene.setCase({
          id: "case-hit-test",
          title: "Pointer Grid Case",
          tier: "hard",
          suspects: [
            { id: "e01", name: "Sami Virtanen", dept: "Infra", role: "SRE", canary_hits: 0, after_hours_count: 1, quote: "Top row desk quote." },
            { id: "e02", name: "Aino Korhonen", dept: "Infra", role: "Lead", canary_hits: 1, after_hours_count: 0, quote: "Second top desk." },
            { id: "e03", name: "Timo Makinen", dept: "Strategy", role: "VP", canary_hits: 0, after_hours_count: 2, quote: "Lower row left desk." },
            { id: "e04", name: "Noora Laine", dept: "Strategy", role: "Director", canary_hits: 2, after_hours_count: 4, quote: "Lower row right desk." }
          ]
        });

        ctx.resetLog();
        scene.setSelectedSuspect("e01");
        const topBubbleHeader = ctx.texts.find((t) => t.text === "Sami Virtanen [Infra]");
        const topReticleCount = ctx.strokes.filter((s) => s.strokeStyle === H + "fde047" && s.lineWidth === 2).length;

        ctx.resetLog();
        scene.setSelectedSuspect("e04");
        const bottomBubbleHeader = ctx.texts.find((t) => t.text === "Noora Laine [Strategy]");
        const focusE04 = ctx.texts.some((t) => t.text === "FOCUS: e04");
        const dossierE04 = ctx.texts.some((t) => t.text === "DOSSIER: Noora Laine (e04) | Director");

        ctx.resetLog();
        scene.setSelectedSuspect(null);
        const clearedFocus = ctx.texts.some((t) => t.text === "SELECT A DESK");

        const toClient = (lx, ly) => ({ clientX: 20 + lx * 0.5, clientY: 10 + ly * 0.5 });

        canvas.dispatch("mousemove", toClient(274, 318));
        const cursorOverSuspect = canvas.style.cursor;
        ctx.resetLog();
        env.runNextRaf(1016);
        const hoverBorderDrawn = ctx.strokeRects.some((r) => r.strokeStyle === H + "94a3b8" && r.lineWidth === 1);

        canvas.dispatch("mousemove", toClient(650, 200));
        const cursorOverEmpty = canvas.style.cursor;
        canvas.dispatch("mouseleave", {});

        ctx.resetLog();
        canvas.dispatch("click", toClient(274, 318));
        const clickSuspectFocus = ctx.texts.some((t) => t.text === "FOCUS: e04");

        ctx.resetLog();
        canvas.dispatch("click", toClient(279, 47));
        const clickTabLabel = ctx.texts.some((t) => t.text === "TAB: LEAKS");

        ctx.resetLog();
        canvas.dispatch("click", toClient(832, 382));
        const podSelectedStroke = ctx.strokeRects.some(
          (r) => r.x === 719 && r.y === 345 && r.strokeStyle === H + "fde047" && r.lineWidth === 2
        );

        return {
          topBubbleY: topBubbleHeader ? topBubbleHeader.y : null,
          bottomBubbleY: bottomBubbleHeader ? bottomBubbleHeader.y : null,
          topReticleCount,
          focusE04,
          dossierE04,
          clearedFocus,
          cursorOverSuspect,
          hoverBorderDrawn,
          cursorOverEmpty,
          clickedSuspects,
          clickSuspectFocus,
          clickedTabs,
          clickTabLabel,
          clickedPods,
          podSelectedStroke
        };
        """
    )

    assert res["topBubbleY"] == 260
    assert res["bottomBubbleY"] == 221
    assert res["topReticleCount"] == 1
    assert res["focusE04"] is True
    assert res["dossierE04"] is True
    assert res["clearedFocus"] is True
    assert res["cursorOverSuspect"] == "pointer"
    assert res["hoverBorderDrawn"] is True
    assert res["cursorOverEmpty"] == "default"
    assert res["clickedSuspects"] == ["e04"]
    assert res["clickSuspectFocus"] is True
    assert res["clickedTabs"] == ["leaks"]
    assert res["clickTabLabel"] is True
    assert res["clickedPods"] == ["high"]
    assert res["podSelectedStroke"] is True


def test_set_highlight_candidates_and_case_reset_behavior():
    res = _run_scene_js(
        """
        const env = setupSceneEnv();
        const container = env.makeContainer();
        const scene = env.SceneMod.create(container);
        const ctx = env.createdCanvases[0]._ctx;

        const baseCase = {
          id: "case-hl-1",
          title: "Canary Filter Check",
          tier: "hard",
          suspects: [
            { id: "e01", name: "Sami Virtanen", dept: "Infra", role: "SRE" },
            { id: "e02", name: "Aino Korhonen", dept: "Infra", role: "Lead" },
            { id: "e03", name: "Timo Makinen", dept: "Strategy", role: "VP" },
            { id: "e04", name: "Noora Laine", dept: "Strategy", role: "Director" }
          ]
        };
        scene.setCase(baseCase);

        ctx.resetLog();
        scene.setHighlightCandidates(["e02", "e04"]);
        const cyanBorders = ctx.strokeRects.filter(
          (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
        );
        const goldInnerBorders = ctx.strokeRects.filter(
          (r) => r.strokeStyle === H + "fbbf24" && r.lineWidth === 1 && r.y >= 95 && r.y <= 395
        );

        ctx.resetLog();
        scene.setHighlightCandidates([]);
        const afterEmptyArr = ctx.strokeRects.filter(
          (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
        ).length;

        scene.setHighlightCandidates(["e01"]);
        scene.setSelectedSuspect("e01");
        ctx.resetLog();
        scene.setHighlightCandidates(null);
        const afterNull = ctx.strokeRects.filter(
          (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
        ).length;

        scene.setHighlightCandidates(["e03"]);
        ctx.resetLog();
        scene.setCase({
          id: "case-hl-2",
          title: "Fresh Scenario",
          tier: "easy",
          suspects: [{ id: "e03", name: "Timo Makinen", dept: "Strategy", role: "VP" }]
        });
        const resetHighlights = ctx.strokeRects.filter(
          (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
        ).length;
        const resetSelection = ctx.texts.some((t) => t.text === "SELECT A DESK");

        return {
          cyanCount: cyanBorders.length,
          cyanXs: cyanBorders.map((r) => r.x),
          goldCount: goldInnerBorders.length,
          afterEmptyArr,
          afterNull,
          resetHighlights,
          resetSelection
        };
        """
    )

    assert res["cyanCount"] == 2
    assert res["cyanXs"] == [217, 217]
    assert res["goldCount"] == 2
    assert res["afterEmptyArr"] == 0
    assert res["afterNull"] == 0
    assert res["resetHighlights"] == 0
    assert res["resetSelection"] is True


def test_reveal_spotlight_posterior_pods_and_clear_reveal():
    res = _run_scene_js(
        """
        const env = setupSceneEnv({ initialNowMs: 2000 });
        const container = env.makeContainer();
        const scene = env.SceneMod.create(container);
        const ctx = env.createdCanvases[0]._ctx;

        const safePreCase = {
          id: "case-rev-1",
          title: "Helios Readout Leak",
          tier: "hard",
          suspects: [
            { id: "e01", name: "Sami Virtanen", dept: "Infra", role: "SRE" },
            { id: "e02", name: "Aino Korhonen", dept: "Infra", role: "Lead" },
            { id: "e03", name: "Timo Makinen", dept: "Strategy", role: "VP" },
            { id: "e04", name: "Noora Laine", dept: "Strategy", role: "Director" }
          ]
        };

        scene.setCase(safePreCase);
        scene.setSelectedSuspect("e04");
        scene.setHighlightCandidates(["e04"]);

        const preTexts = ctx.texts.map((t) => t.text);
        const preHasMoleTag = preTexts.some((t) => t.startsWith("MOLE "));
        const preHasBubble = preTexts.includes("Noora Laine [Strategy]");

        const fullCase = Object.assign({}, safePreCase, {
          true_mole: "e04",
          solver: {
            posterior: { e04: 0.91, e02: 0.06, e01: 0.02, e03: 0.01 }
          }
        });
        const evalResult = {
          trueMole: "e04",
          verdictLabel: "OPTIMAL ACCUSATION",
          levelComparisons: [
            { thinking_level: "minimal", accused: "e02", cost_usd: 0.0028, correct: false },
            { thinking_level: "low", accused: "e01", cost_usd: 0.0054, correct: false },
            { thinking_level: "medium", accused: null, cost_usd: 0.0112, correct: false },
            { thinking_level: "high", accused: "e04", cost_usd: 0.0245, correct: true },
            { thinking_level: "xhigh", accused: "e04", cost_usd: 0.0481, correct: true }
          ]
        };

        ctx.resetLog();
        scene.showReveal(evalResult, fullCase);
        const revealStartArc = ctx.arcs.find((a) => a.r === 34);

        ctx.resetLog();
        env.advanceNow(800);
        scene.resize();
        const revealEndArc = ctx.arcs.find((a) => a.r === 34);
        const revTexts = ctx.texts.map((t) => t.text);
        const highlightKept = ctx.strokeRects.some(
          (r) => r.strokeStyle === H + "22d3ee" && r.lineWidth === 2 && r.y >= 95 && r.y <= 395
        );

        ctx.resetLog();
        scene.clearReveal();
        const clearedTexts = ctx.texts.map((t) => t.text);

        return {
          preHasMoleTag,
          preHasBubble,
          spotStart: revealStartArc ? { x: revealStartArc.x, y: revealStartArc.y } : null,
          spotEnd: revealEndArc ? { x: revealEndArc.x, y: revealEndArc.y } : null,
          revTexts,
          highlightKept,
          clearedTexts
        };
        """
    )

    assert res["preHasMoleTag"] is False
    assert res["preHasBubble"] is True
    assert res["spotStart"] == {"x": 140, "y": 390}
    assert res["spotEnd"] == {"x": 274, "y": 318}
    assert res["highlightKept"] is True

    rev_texts = set(res["revTexts"])
    assert "STATUS: CASE REVEALED" in rev_texts
    assert "MOLE e04" in rev_texts
    assert "Noora Laine [Strategy]" not in rev_texts
    assert "FOCUS: e04" in rev_texts
    assert "SOLVER TOP-3 POSTERIOR | OPTIMAL ACCUSATION" in rev_texts
    assert "1. e04" in rev_texts
    assert "91.0%" in rev_texts
    assert "2. e02" in rev_texts
    assert "6.0%" in rev_texts
    assert "3. e01" in rev_texts
    assert "2.0%" in rev_texts
    assert "[LOCKED]" not in rev_texts
    assert "ACC: e04" in rev_texts
    assert "ACC: HOLD" in rev_texts
    assert "$0.0245" in rev_texts
    assert "RIGHT" in rev_texts
    assert "WRONG" in rev_texts

    cleared_texts = set(res["clearedTexts"])
    assert "STATUS: PODS SEALED" in cleared_texts
    assert "[LOCKED]" in cleared_texts
    assert "MOLE e04" not in cleared_texts
    assert "Noora Laine [Strategy]" in cleared_texts


def test_sprite_data_uri_handling_async_onload_and_frame_animation():
    res = _run_scene_js(
        """
        const URI_FLOOR = "data:image/png;base64,RkxPT1JfVElMRQ==";
        const URI_DET = "data:image/png;base64,REVURUNUSVZF";
        const URI_SUS0 = "data:image/png;base64,U1VTUEVDVF8w";
        const URI_POD_LOCK = "data:image/png;base64,UE9EX0xPQ0tFRA==";
        const URI_POD_OPEN = "data:image/png;base64,UE9EX1VOTE9DS0VE";
        const URI_AGENT_HIGH = "data:image/png;base64,QUdFTlRfSElHSA==";
        const URI_RIGHT = "data:image/png;base64,SUNPTl9SSUdIVA==";
        const URI_WRONG = "data:image/png;base64,SUNPTl9XUk9ORw==";
        const URI_BROKEN = "data:image/png;base64,QlJPS0VO";

        const env = setupSceneEnv({
          initialNowMs: 0,
          assets: {
            sprites: {
              floor_tile: { dataUri: URI_FLOOR },
              detective: { dataUri: URI_DET, frames: 2, frameWidth: 16, frameHeight: 16 },
              suspect_0: { dataUri: URI_SUS0, frames: 2, frameWidth: 18, frameHeight: 20 },
              pod_locked: { dataUri: URI_POD_LOCK },
              pod_unlocked: { dataUri: URI_POD_OPEN },
              agent_high: { dataUri: URI_AGENT_HIGH },
              icon_correct: { dataUri: URI_RIGHT },
              icon_wrong: { dataUri: URI_WRONG },
              desk: { dataUri: URI_BROKEN }
            }
          },
          imageRules: {
            [URI_SUS0]: { complete: false, naturalWidth: 36, naturalHeight: 20 },
            [URI_DET]: { complete: true, naturalWidth: 32, naturalHeight: 16 },
            [URI_BROKEN]: { complete: true, naturalWidth: 0, naturalHeight: 0 }
          }
        });

        const container = env.makeContainer();
        const scene = env.SceneMod.create(container);
        const ctx = env.createdCanvases[0]._ctx;

        ctx.resetLog();
        scene.setCase({
          id: "sprite-case",
          title: "Sprite Bank Verification",
          tier: "hard",
          true_mole: "e01",
          suspects: [{ id: "e01", name: "Noora Laine", dept: "Strategy", role: "Director" }],
          thinking_levels: [
            { thinking_level: "high", accused: "e01", cost_usd: 0.021, correct: true },
            { thinking_level: "minimal", accused: "e02", cost_usd: 0.003, correct: false }
          ]
        });

        const beforeOnloadSrcs = Array.from(new Set(ctx.drawImages.map((d) => d.src)));
        const detFrame0 = ctx.drawImages.find((d) => d.src === URI_DET);

        const susImg = env.createdImages.find((img) => img.src === URI_SUS0);
        ctx.resetLog();
        susImg.complete = true;
        susImg.onload();
        const afterOnloadSusDraws = ctx.drawImages.filter((d) => d.src === URI_SUS0);

        ctx.resetLog();
        env.setNow(256);
        scene.resize();
        const detFrame1 = ctx.drawImages.find((d) => d.src === URI_DET);
        const susFrame1 = ctx.drawImages.find((d) => d.src === URI_SUS0);

        ctx.resetLog();
        scene.showReveal({ trueMole: "e01" });
        const revealSrcs = Array.from(new Set(ctx.drawImages.map((d) => d.src)));

        const lateAssetEnv = setupSceneEnv({ initialNowMs: 0 });
        const lateContainer = lateAssetEnv.makeContainer();
        const lateScene = lateAssetEnv.SceneMod.create(lateContainer);
        const lateCtx = lateAssetEnv.createdCanvases[0]._ctx;
        globalThis.window.OUTTHINK_ASSETS = {
          sprites: {
            detective: { dataUri: URI_DET }
          }
        };
        lateCtx.resetLog();
        lateScene.setCase({
          id: "late-sprite-case",
          title: "Lazy Asset Load",
          tier: "easy",
          suspects: []
        });
        const lateLoadedDet = lateCtx.drawImages.some((d) => d.src === URI_DET);

        return {
          beforeOnloadSrcs,
          detFrame0Sx: detFrame0 ? detFrame0.sx : null,
          afterOnloadSusCount: afterOnloadSusDraws.length,
          detFrame1Sx: detFrame1 ? detFrame1.sx : null,
          susFrame1Sx: susFrame1 ? susFrame1.sx : null,
          revealSrcs,
          lateLoadedDet
        };
        """
    )

    before_srcs = set(res["beforeOnloadSrcs"])
    assert "data:image/png;base64,RkxPT1JfVElMRQ==" in before_srcs
    assert "data:image/png;base64,REVURUNUSVZF" in before_srcs
    assert "data:image/png;base64,UE9EX0xPQ0tFRA==" in before_srcs
    assert "data:image/png;base64,U1VTUEVDVF8w" not in before_srcs
    assert "data:image/png;base64,QlJPS0VO" not in before_srcs

    assert res["detFrame0Sx"] == 0
    assert res["afterOnloadSusCount"] == 1
    assert res["detFrame1Sx"] == 16
    assert res["susFrame1Sx"] == 18

    reveal_srcs = set(res["revealSrcs"])
    assert "data:image/png;base64,UE9EX1VOTE9DS0VE" in reveal_srcs
    assert "data:image/png;base64,UE9EX0xPQ0tFRA==" not in reveal_srcs
    assert "data:image/png;base64,QUdFTlRfSElHSA==" in reveal_srcs
    assert "data:image/png;base64,SUNPTl9SSUdIVA==" in reveal_srcs
    assert "data:image/png;base64,SUNPTl9XUk9ORw==" in reveal_srcs
    assert res["lateLoadedDet"] is True


def test_destroy_cleanup_and_engine_e2e_compatibility():
    res = _run_scene_js(
        """
        const env = setupSceneEnv();
        const Engine = require(process.env.OUTTHINK_ENGINE_PATH);
        const dataset = Engine.loadDataset({ data: undefined, fallbackData: undefined });
        const bootCase = dataset.cases[0];

        const container = env.makeContainer();
        let callbackCount = 0;
        const scene = env.SceneMod.create(container, {
          onSelectSuspect() { callbackCount += 1; }
        });
        const canvas = env.createdCanvases[0];
        const ctx = canvas._ctx;

        const listenersBefore = {
          move: canvas.listenerCount("mousemove"),
          leave: canvas.listenerCount("mouseleave"),
          click: canvas.listenerCount("click")
        };
        const staleRafFn = Object.values(env.rafQueue)[0];

        scene.setCase(bootCase);
        scene.setSelectedSuspect(bootCase.true_mole);
        scene.setHighlightCandidates([bootCase.true_mole]);
        const evalRes = Engine.evaluateCall(bootCase, {
          action: "accuse",
          suspectId: bootCase.true_mole
        });
        scene.showReveal(evalRes, bootCase);
        const revealedMoleDrawn = ctx.texts.some((t) => t.text === "MOLE " + bootCase.true_mole);

        scene.destroy();
        const listenersAfter = {
          move: canvas.listenerCount("mousemove"),
          leave: canvas.listenerCount("mouseleave"),
          click: canvas.listenerCount("click")
        };

        ctx.resetLog();
        scene.setCase(bootCase);
        scene.setSelectedSuspect("e01");
        scene.setHighlightCandidates(["e01"]);
        scene.showReveal(evalRes, bootCase);
        scene.clearReveal();
        scene.resize();
        canvas.dispatch("click", { clientX: 100, clientY: 150 });
        if (typeof staleRafFn === "function") {
          staleRafFn(5000);
        }
        scene.destroy();

        return {
          revealedMoleDrawn,
          listenersBefore,
          listenersAfter,
          canceledCount: env.canceledRafs.length,
          childrenAfterDestroy: container.children.length,
          parentAfterDestroy: canvas.parentNode,
          drawsAfterDestroy: ctx.fillRects.length + ctx.texts.length + ctx.strokeRects.length,
          callbackCount
        };
        """
    )

    assert res["revealedMoleDrawn"] is True
    assert res["listenersBefore"] == {"move": 1, "leave": 1, "click": 1}
    assert res["listenersAfter"] == {"move": 0, "leave": 0, "click": 0}
    assert res["canceledCount"] == 1
    assert res["childrenAfterDestroy"] == 0
    assert res["parentAfterDestroy"] is None
    assert res["drawsAfterDestroy"] == 0
    assert res["callbackCount"] == 0


def test_phaser_canvas_adapter_and_sprite_path_fallback():
    res = _run_scene_js(
        """
        const ptrEvents = {};
        let texRefreshCount = 0;
        let scaleRefreshCount = 0;
        let destroyArgs = [];
        let sceneUpdateFn = null;
        let texCtx = null;

        const env = setupSceneEnv({
          assets: {
            sprites: {
              lamp: { path: "assets/sprites/lamp.png" },
              custom_badge: { dataUri: "data:image/png;base64,Q1VTVE9N" }
            }
          },
          phaser: {
            CANVAS: 1,
            Game: function MockPhaserGame(cfg) {
              this.canvas = { style: { cssText: "" } };
              this.scale = {
                refresh() { scaleRefreshCount += 1; }
              };
              this.destroy = function (removeCanvas) {
                destroyArgs.push(removeCanvas);
              };
              texCtx = createMockContext2D();
              const sceneCtx = {
                textures: {
                  createCanvas(key, w, h) {
                    return {
                      key,
                      width: w,
                      height: h,
                      getContext() { return texCtx; },
                      refresh() { texRefreshCount += 1; }
                    };
                  }
                },
                add: {
                  image() { return {}; }
                },
                input: {
                  on(evName, fn) { ptrEvents[evName] = fn; }
                }
              };
              cfg.scene.create.call(sceneCtx);
              sceneUpdateFn = function (t) {
                cfg.scene.update.call(sceneCtx, t);
              };
            }
          }
        });

        const selectedTabs = [];
        const container = env.makeContainer();
        const scene = env.SceneMod.create(container, {
          onSelectTab(tab) { selectedTabs.push(tab); }
        });

        const lampDrawn = texCtx.drawImages.some((d) => d.src === "assets/sprites/lamp.png");
        const customLoaded = env.createdImages.some((img) => img.src === "data:image/png;base64,Q1VTVE9N");

        ptrEvents.pointermove({ x: 405, y: 47 });
        ptrEvents.pointerdown({ x: 405, y: 47 });
        scene.resize();
        const refreshBeforeUpdate = texRefreshCount;
        sceneUpdateFn(2048);
        const refreshAfterUpdate = texRefreshCount;

        scene.destroy();
        texCtx.resetLog();
        sceneUpdateFn(4096);

        return {
          mode: scene.mode,
          fallbackDomCanvases: env.createdCanvases.length,
          lampDrawn,
          customLoaded,
          selectedTabs,
          scaleRefreshCount,
          refreshBeforeUpdate,
          refreshAfterUpdate,
          destroyArgs,
          drawsAfterDestroy: texCtx.fillRects.length + texCtx.texts.length
        };
        """
    )

    assert res["mode"] == "phaser"
    assert res["fallbackDomCanvases"] == 0
    assert res["lampDrawn"] is True
    assert res["customLoaded"] is True
    assert res["selectedTabs"] == ["access"]
    assert res["scaleRefreshCount"] == 1
    assert res["refreshAfterUpdate"] == res["refreshBeforeUpdate"] + 1
    assert res["destroyArgs"] == [True]
    assert res["drawsAfterDestroy"] == 0


def test_strict_hygiene_comments_dashes_network_and_protected_paths():
    self_path = Path(__file__).resolve()
    for target in (SCENE_PATH, self_path):
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

    js_src = SCENE_PATH.read_text(encoding="utf-8")
    assert _find_js_comments(js_src) == []

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

    checked_paths = {
        SCENE_PATH.relative_to(ROOT).as_posix(),
        self_path.relative_to(ROOT).as_posix(),
    }

    violations = sorted(rel for rel in checked_paths if _matches_protected_rule(rel, rules))
    assert violations == [], f"protected-paths.txt violations: {violations}"
