from __future__ import annotations

import ast
import base64
import io
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import tokenize
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
SCENE_PATH = DEMO_DIR / "scene.js"
MANIFEST_PATH = DEMO_DIR / "assets" / "manifest.js"
PROTECTED_PATHS_FILE = ROOT / ".github" / "protected-paths.txt"

EXPECTED_SPRITE_KEYS = [
    "floor_tile",
    "wall_tile",
    "window_night",
    "door",
    "desk",
    "chair",
    "evidence_board",
    "filing_cabinet",
    "terminal",
    "server_rack",
    "lamp",
    "detective",
    "suspect_0",
    "suspect_1",
    "suspect_2",
    "suspect_3",
    "suspect_4",
    "suspect_5",
    "suspect_6",
    "suspect_7",
    "agent_minimal",
    "agent_low",
    "agent_medium",
    "agent_high",
    "agent_xhigh",
    "pod_locked",
    "pod_unlocked",
    "icon_correct",
    "icon_wrong",
]

EXPECTED_PROP_KEYS = ["canaries", "leaks", "access", "comms", "steps"]
EXPECTED_POD_KEYS = ["minimal", "low", "medium", "high", "xhigh"]

KENNEY_SPRITE_SPECS: list[tuple[str, int, int, int, str]] = [
    ("floor_tile", 16, 16, 1, "kenney-roguelike-indoor"),
    ("wall_tile", 16, 16, 1, "kenney-roguelike-modern-city"),
    ("window_night", 16, 32, 1, "kenney-roguelike-modern-city"),
    ("door", 16, 16, 1, "kenney-roguelike-indoor"),
    ("desk", 48, 16, 1, "kenney-roguelike-indoor"),
    ("chair", 16, 16, 1, "kenney-roguelike-indoor"),
    ("evidence_board", 32, 32, 1, "kenney-roguelike-indoor"),
    ("filing_cabinet", 32, 32, 1, "kenney-roguelike-indoor"),
    ("terminal", 32, 32, 1, "kenney-roguelike-modern-city"),
    ("server_rack", 32, 32, 1, "kenney-roguelike-modern-city"),
    ("lamp", 16, 16, 1, "kenney-roguelike-indoor"),
    ("detective", 16, 16, 2, "kenney-roguelike-characters"),
    ("suspect_0", 16, 16, 4, "kenney-rpg-urban"),
    ("suspect_1", 16, 16, 4, "kenney-rpg-urban"),
    ("suspect_2", 16, 16, 4, "kenney-rpg-urban"),
    ("suspect_3", 16, 16, 4, "kenney-rpg-urban"),
    ("suspect_4", 16, 16, 4, "kenney-rpg-urban"),
    ("suspect_5", 16, 16, 4, "kenney-rpg-urban"),
    ("suspect_6", 16, 16, 2, "kenney-roguelike-characters"),
    ("suspect_7", 16, 16, 2, "kenney-roguelike-characters"),
    ("agent_minimal", 16, 24, 4, "kenney-roguelike-characters"),
    ("agent_low", 16, 24, 4, "kenney-roguelike-characters"),
    ("agent_medium", 16, 24, 4, "kenney-roguelike-characters"),
    ("agent_high", 16, 24, 4, "kenney-roguelike-characters"),
    ("agent_xhigh", 16, 24, 4, "kenney-roguelike-characters"),
    ("pod_locked", 16, 32, 1, "kenney-roguelike-modern-city"),
    ("pod_unlocked", 16, 32, 1, "kenney-roguelike-modern-city"),
    ("icon_correct", 16, 16, 1, "kenney-pixel-ui"),
    ("icon_wrong", 16, 16, 1, "kenney-pixel-ui"),
]

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
HTTP_SCHEME = "ht" + "tp:" + SLASH + SLASH
HTTPS_SCHEME = "ht" + "tps:" + SLASH + SLASH
WS_SCHEME = "w" + "s:" + SLASH + SLASH
WSS_SCHEME = "w" + "ss:" + SLASH + SLASH
PROTO_REL = SLASH + SLASH + "cdn"
CDNJS_TOKEN = "cdn" + "js"
UNPKG_TOKEN = "un" + "pkg"
JSDELIVR_TOKEN = "js" + "delivr"
GOOGLEAPIS_TOKEN = "google" + "apis"
FETCH_CALL = "fet" + "ch("
XHR_TOKEN = "XML" + "HttpRequest"
WEBSOCKET_TOKEN = "Web" + "Socket"
BEACON_TOKEN = "send" + "Beacon"
IMPORT_SCRIPTS_TOKEN = "import" + "Scripts"


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _make_png_data_uri(width: int, height: int, rgba: tuple[int, int, int, int]) -> str:
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    row = b"\x00" + bytes(rgba) * width
    raw = row * height
    idat = zlib.compress(raw, level=9)
    png_bytes = sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def _build_kenney_29_manifest_js() -> str:
    packs = [
        {"id": "kenney-roguelike-indoor", "name": "Roguelike Indoor pack", "author": "Kenney", "license": "CC0-1.0"},
        {"id": "kenney-rpg-urban", "name": "RPG Urban Pack", "author": "Kenney", "license": "CC0-1.0"},
        {"id": "kenney-roguelike-modern-city", "name": "Roguelike Modern City pack", "author": "Kenney", "license": "CC0-1.0"},
        {"id": "kenney-roguelike-characters", "name": "Roguelike Character pack", "author": "Kenney", "license": "CC0-1.0"},
        {"id": "kenney-pixel-ui", "name": "Pixel UI pack", "author": "Kenney", "license": "CC0-1.0"},
    ]
    sprites: dict[str, dict[str, object]] = {}
    for idx, (key, fw, fh, frames, pack_id) in enumerate(KENNEY_SPRITE_SPECS):
        total_w = fw * frames
        total_h = fh
        rgba = ((idx * 37 + 29) % 256, (idx * 73 + 61) % 256, (idx * 109 + 97) % 256, 255)
        sprites[key] = {
            "path": f"assets/sprites/{key}.png",
            "width": total_w,
            "height": total_h,
            "frameWidth": fw,
            "frameHeight": fh,
            "frames": frames,
            "x": 0,
            "y": 0,
            "pack": pack_id,
            "dataUri": _make_png_data_uri(total_w, total_h, rgba),
        }
    manifest_obj = {"version": 1, "packs": packs, "sprites": sprites}
    return "window.OUTTHINK_ASSETS = " + json.dumps(manifest_obj) + ";\n"


def _iter_manifest_targets() -> list[tuple[str, str | None]]:
    targets: list[tuple[str, str | None]] = []
    if MANIFEST_PATH.is_file():
        targets.append(("disk_manifest_js", str(MANIFEST_PATH)))
    targets.append(("kenney_cc0_29_fixture", None))
    return targets


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


JS_BRIDGE_PRELUDE = """
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const H = String.fromCharCode(35);

function parsePngDimensionsFromSrc(src, demoDir) {
  const s = String(src || "");
  if (s.startsWith("data:image/png;base64,")) {
    const buf = Buffer.from(s.slice(22), "base64");
    if (buf.length >= 24 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
      return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
    }
  } else if (s && demoDir) {
    const candidate = path.resolve(demoDir, s);
    if (fs.existsSync(candidate)) {
      const buf = fs.readFileSync(candidate);
      if (buf.length >= 24 && buf[0] === 0x89 && buf[1] === 0x50 && buf[2] === 0x4e && buf[3] === 0x47) {
        return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
      }
    }
  }
  return null;
}

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
        naturalWidth: img ? img.naturalWidth : 0,
        naturalHeight: img ? img.naturalHeight : 0,
        sx,
        sy,
        sw,
        sh,
        dx,
        dy,
        dw,
        dh,
        globalAlpha: this.globalAlpha,
        smoothingMain: this.imageSmoothingEnabled,
        smoothingWebkit: this.webkitImageSmoothingEnabled,
        smoothingMoz: this.mozImageSmoothingEnabled
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
      this.arcs.push({ x, y, r, fillStyle: String(this.fillStyle), globalAlpha: this.globalAlpha });
    },
    fill() {
      this.fills.push({ fillStyle: String(this.fillStyle), globalAlpha: this.globalAlpha, ops: currentPath.slice() });
    },
    stroke() {
      this.strokes.push({ strokeStyle: String(this.strokeStyle), lineWidth: this.lineWidth, ops: currentPath.slice() });
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

function setupManifestSceneEnv(opts) {
  const options = opts || {};
  const demoDir = process.env.OUTTHINK_DEMO_DIR;
  let nowVal = typeof options.initialNowMs === "number" ? options.initialNowMs : 0;
  let nextRafId = 1;
  const rafQueue = {};
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
    delete rafQueue[id];
  };

  const imageRules = options.imageRules || {};
  globalThis.Image = function MockImage() {
    const rec = {
      _src: "",
      onload: null,
      complete: true,
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
        const parsed = parsePngDimensionsFromSrc(this._src, demoDir);
        if (parsed) {
          rec.naturalWidth = parsed.width;
          rec.naturalHeight = parsed.height;
          rec.width = parsed.width;
          rec.height = parsed.height;
          rec.complete = true;
        }
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
  delete globalThis.OUTTHINK_ASSETS;
  delete globalThis.Phaser;

  if (options.manifestPath) {
    const manifestCode = fs.readFileSync(options.manifestPath, "utf8");
    vm.runInThisContext(manifestCode, { filename: options.manifestPath });
  }
  if (options.extraSprites && globalThis.window.OUTTHINK_ASSETS && globalThis.window.OUTTHINK_ASSETS.sprites) {
    Object.assign(globalThis.window.OUTTHINK_ASSETS.sprites, options.extraSprites);
  }

  const scenePath = process.env.OUTTHINK_SCENE_PATH;
  delete require.cache[require.resolve(scenePath)];
  const SceneMod = require(scenePath);

  return {
    SceneMod,
    makeContainer,
    createdCanvases,
    createdImages,
    setNow(ms) {
      nowVal = ms;
    }
  };
}
"""


def _run_bridge_js(js_body: str, manifest_file: str, payload: dict | list | None = None) -> dict:
    cmd_prefix, env = _resolve_js_cmd()
    run_env = dict(env)
    run_env["OUTTHINK_DEMO_DIR"] = str(DEMO_DIR)
    run_env["OUTTHINK_SCENE_PATH"] = str(SCENE_PATH)
    run_env["OUTTHINK_MANIFEST_FILE"] = manifest_file
    run_env["OUTTHINK_TEST_PAYLOAD"] = json.dumps(payload if payload is not None else {})
    wrapper = (
        JS_BRIDGE_PRELUDE
        + "\nconst PAYLOAD = JSON.parse(process.env.OUTTHINK_TEST_PAYLOAD);\n"
        + "const MANIFEST_FILE = process.env.OUTTHINK_MANIFEST_FILE;\n"
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


def _extract_scene_sprite_keys(scene_src: str) -> list[str]:
    match = re.search(r"var\s+SPRITE_KEYS\s*=\s*(\[[^\]]+\])\s*;", scene_src)
    assert match is not None, "SPRITE_KEYS array missing in scene.js"
    parsed = json.loads(match.group(1))
    assert isinstance(parsed, list)
    return [str(x) for x in parsed]


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


def test_all_29_sprite_keys_resolve_without_fallback_glitches_and_smoothing_disabled():
    scene_src = SCENE_PATH.read_text(encoding="utf-8")
    scene_keys = _extract_scene_sprite_keys(scene_src)
    assert len(scene_keys) == 29
    assert scene_keys == EXPECTED_SPRITE_KEYS

    with tempfile.TemporaryDirectory() as tmp_dir:
        fixture_manifest_path = Path(tmp_dir) / "manifest.js"
        fixture_manifest_path.write_text(_build_kenney_29_manifest_js(), encoding="utf-8")

        for label, disk_path in _iter_manifest_targets():
            active_manifest_path = disk_path if disk_path is not None else str(fixture_manifest_path)
            res = _run_bridge_js(
                """
                const env = setupManifestSceneEnv({
                  initialNowMs: 0,
                  manifestPath: MANIFEST_FILE
                });
                const assets = globalThis.window.OUTTHINK_ASSETS;
                const sprites = assets && assets.sprites ? assets.sprites : {};
                const srcToKey = {};
                for (const key of PAYLOAD.expectedKeys) {
                  const meta = sprites[key];
                  if (meta) {
                    const src = meta.dataUri || meta.path || "";
                    if (src) srcToKey[src] = key;
                  }
                }

                const container = env.makeContainer();
                const scene = env.SceneMod.create(container);
                const canvas = env.createdCanvases[0];
                const ctx = canvas._ctx;

                const suspects = [];
                const depts = ["Infra", "Assay", "Strategy", "Clinical"];
                for (let i = 0; i < 16; i += 1) {
                  const id = "e" + String(i + 1).padStart(2, "0");
                  suspects.push({
                    id,
                    name: "Suspect " + id,
                    dept: depts[i % depts.length],
                    role: "Staff"
                  });
                }

                ctx.resetLog();
                scene.setCase({
                  id: "bridge-29-case",
                  title: "Manifest Bridge Case",
                  tier: "medium",
                  suspects
                });

                const preDrawnKeys = Array.from(
                  new Set(ctx.drawImages.map((d) => srcToKey[d.src]).filter(Boolean))
                );
                const preFallbackGlitches = ctx.fillRects.filter((r) => (
                  r.fillStyle === H + "131c31"
                  || r.fillStyle === H + "172033"
                  || r.fillStyle === H + "293548"
                  || r.fillStyle === H + "090d1a"
                  || r.fillStyle === H + "b45309"
                  || r.fillStyle === H + "052e16"
                  || r.fillStyle === H + "451a03"
                  || r.fillStyle === H + "92400e"
                  || r.fillStyle === H + "fed7aa"
                  || r.fillStyle === H + "a16207"
                )).length;
                const preAllUnsmoothed = ctx.drawImages.every(
                  (d) => d.smoothingMain === false && d.smoothingWebkit === false && d.smoothingMoz === false
                );

                ctx.imageSmoothingEnabled = true;
                ctx.webkitImageSmoothingEnabled = true;
                ctx.mozImageSmoothingEnabled = true;
                ctx.resetLog();

                scene.showReveal({
                  trueMole: "e04",
                  levelComparisons: [
                    { thinking_level: "minimal", accused: "e01", cost_usd: 0.0021, correct: false },
                    { thinking_level: "low", accused: "e02", cost_usd: 0.0048, correct: false },
                    { thinking_level: "medium", accused: null, cost_usd: 0.0095, correct: false },
                    { thinking_level: "high", accused: "e04", cost_usd: 0.0224, correct: true },
                    { thinking_level: "xhigh", accused: "e04", cost_usd: 0.0449, correct: true }
                  ]
                });

                const postDrawnKeys = Array.from(
                  new Set(ctx.drawImages.map((d) => srcToKey[d.src]).filter(Boolean))
                );
                const postFallbackGlitches = ctx.fillRects.filter((r) => (
                  r.fillStyle === H + "131c31"
                  || r.fillStyle === H + "172033"
                  || r.fillStyle === H + "293548"
                  || r.fillStyle === H + "090d1a"
                  || r.fillStyle === H + "b45309"
                  || r.fillStyle === H + "052e16"
                  || r.fillStyle === H + "451a03"
                  || r.fillStyle === H + "92400e"
                  || r.fillStyle === H + "fed7aa"
                  || r.fillStyle === H + "a16207"
                  || r.fillStyle === H + "0f2942"
                )).length;
                const fallbackBadgeChars = ctx.texts.filter((t) => t.text === "V" || t.text === "X").length;
                const postAllUnsmoothed = ctx.drawImages.every(
                  (d) => d.smoothingMain === false && d.smoothingWebkit === false && d.smoothingMoz === false
                );

                const unionKeys = Array.from(new Set(preDrawnKeys.concat(postDrawnKeys)));
                const loadedMetaSummary = PAYLOAD.expectedKeys.map((k) => {
                  const s = sprites[k] || null;
                  const img = env.createdImages.find((im) => s && im.src === (s.dataUri || s.path));
                  return {
                    key: k,
                    present: Boolean(s),
                    complete: Boolean(img && img.complete),
                    naturalWidth: img ? img.naturalWidth : 0,
                    naturalHeight: img ? img.naturalHeight : 0,
                    metaWidth: s ? s.width : 0,
                    metaHeight: s ? s.height : 0
                  };
                });

                const packs = Array.isArray(assets && assets.packs) ? assets.packs : [];
                const allPacksCc0 = packs.length > 0 && packs.every((p) => p.license === "CC0-1.0");

                scene.destroy();
                return {
                  label: PAYLOAD.label,
                  allPacksCc0,
                  loadedMetaSummary,
                  preDrawnKeys,
                  postDrawnKeys,
                  unionKeys,
                  preDrawImageCount: preDrawnKeys.length,
                  postDrawImageCount: ctx.drawImages.length,
                  preFallbackGlitches,
                  postFallbackGlitches,
                  fallbackBadgeChars,
                  preAllUnsmoothed,
                  postAllUnsmoothed,
                  ctxSmoothAfterReveal: ctx.imageSmoothingEnabled
                };
                """,
                manifest_file=active_manifest_path,
                payload={"expectedKeys": EXPECTED_SPRITE_KEYS, "label": label},
            )

            assert res["allPacksCc0"] is True, label
            for item in res["loadedMetaSummary"]:
                assert item["present"] is True, (label, item)
                assert item["complete"] is True, (label, item)
                assert item["naturalWidth"] == item["metaWidth"] > 0, (label, item)
                assert item["naturalHeight"] == item["metaHeight"] > 0, (label, item)

            assert len(res["preDrawnKeys"]) == 21, label
            assert set(res["unionKeys"]) == set(EXPECTED_SPRITE_KEYS), label
            assert len(res["unionKeys"]) == 29, label
            assert res["postDrawImageCount"] > 300, label
            assert res["preFallbackGlitches"] == 0, label
            assert res["postFallbackGlitches"] == 0, label
            assert res["fallbackBadgeChars"] == 0, label
            assert res["preAllUnsmoothed"] is True, label
            assert res["postAllUnsmoothed"] is True, label
            assert res["ctxSmoothAfterReveal"] is False, label


def test_multiframe_sprite_sheet_stepping_crops_exact_frame_rectangles():
    custom_3frame_uri = _make_png_data_uri(72, 28, (12, 188, 140, 255))
    inferred_3frame_uri = _make_png_data_uri(72, 28, (200, 90, 44, 255))

    with tempfile.TemporaryDirectory() as tmp_dir:
        fixture_manifest_path = Path(tmp_dir) / "manifest.js"
        fixture_manifest_path.write_text(_build_kenney_29_manifest_js(), encoding="utf-8")

        for label, disk_path in _iter_manifest_targets():
            active_manifest_path = disk_path if disk_path is not None else str(fixture_manifest_path)
            res = _run_bridge_js(
                """
                const env = setupManifestSceneEnv({
                  initialNowMs: 0,
                  manifestPath: MANIFEST_FILE
                });
                const sprites = globalThis.window.OUTTHINK_ASSETS.sprites;
                const srcToKey = {};
                for (const key of PAYLOAD.expectedKeys) {
                  const s = sprites[key];
                  srcToKey[s.dataUri || s.path] = key;
                }

                const container = env.makeContainer();
                const scene = env.SceneMod.create(container);
                const ctx = env.createdCanvases[0]._ctx;

                const suspects = [];
                for (let i = 0; i < 8; i += 1) {
                  const id = "e0" + String(i + 1);
                  suspects.push({ id, name: "Member " + id, dept: "Ops", role: "Analyst" });
                }

                scene.setCase({
                  id: "stepping-case",
                  title: "Frame Crop Verification",
                  tier: "easy",
                  true_mole: "e02",
                  suspects
                });
                scene.showReveal({
                  trueMole: "e02",
                  levelComparisons: [
                    { thinking_level: "minimal", accused: "e01", cost_usd: 0.002, correct: false },
                    { thinking_level: "low", accused: "e01", cost_usd: 0.004, correct: false },
                    { thinking_level: "medium", accused: "e02", cost_usd: 0.009, correct: true },
                    { thinking_level: "high", accused: "e02", cost_usd: 0.021, correct: true },
                    { thinking_level: "xhigh", accused: "e02", cost_usd: 0.041, correct: true }
                  ]
                });

                const sampleTimes = [0, 256, 512, 768, 1024];
                const cropsByKey = {};
                let outOfBoundsCount = 0;
                let nonZeroSyCount = 0;

                for (const tMs of sampleTimes) {
                  env.setNow(tMs);
                  ctx.resetLog();
                  scene.resize();
                  for (const d of ctx.drawImages) {
                    if (d.sx < 0 || d.sy < 0 || d.sx + d.sw > d.naturalWidth || d.sy + d.sh > d.naturalHeight) {
                      outOfBoundsCount += 1;
                    }
                    if (d.sy !== 0) {
                      nonZeroSyCount += 1;
                    }
                  }
                  for (const key of Object.keys(srcToKey)) {
                    const keyName = srcToKey[key];
                    const hit = ctx.drawImages.find((d) => d.src === key);
                    if (hit) {
                      if (!cropsByKey[keyName]) cropsByKey[keyName] = [];
                      cropsByKey[keyName].push({ sx: hit.sx, sy: hit.sy, sw: hit.sw, sh: hit.sh });
                    }
                  }
                }

                scene.destroy();

                const customEnv = setupManifestSceneEnv({
                  initialNowMs: 0,
                  manifestPath: MANIFEST_FILE,
                  extraSprites: {
                    detective: {
                      dataUri: PAYLOAD.custom3Uri,
                      width: 72,
                      height: 28,
                      frames: 3,
                      frameWidth: 24,
                      frameHeight: 28
                    },
                    suspect_0: {
                      dataUri: PAYLOAD.inferred3Uri,
                      width: 72,
                      height: 28,
                      frames: 3
                    }
                  }
                });
                const customContainer = customEnv.makeContainer();
                const customScene = customEnv.SceneMod.create(customContainer);
                const customCtx = customEnv.createdCanvases[0]._ctx;
                customScene.setCase({
                  id: "custom-3frame",
                  title: "Three Frame Sheet",
                  tier: "easy",
                  suspects: [{ id: "e01", name: "Solo", dept: "Ops", role: "Lead" }]
                });

                const customDetCrops = [];
                const inferredSusCrops = [];
                for (const tMs of [0, 256, 512, 768]) {
                  customEnv.setNow(tMs);
                  customCtx.resetLog();
                  customScene.resize();
                  const detHit = customCtx.drawImages.find((d) => d.src === PAYLOAD.custom3Uri);
                  const susHit = customCtx.drawImages.find((d) => d.src === PAYLOAD.inferred3Uri);
                  if (detHit) customDetCrops.push({ sx: detHit.sx, sy: detHit.sy, sw: detHit.sw, sh: detHit.sh });
                  if (susHit) inferredSusCrops.push({ sx: susHit.sx, sy: susHit.sy, sw: susHit.sw, sh: susHit.sh });
                }
                customScene.destroy();

                return {
                  outOfBoundsCount,
                  nonZeroSyCount,
                  cropsByKey,
                  customDetCrops,
                  inferredSusCrops
                };
                """,
                manifest_file=active_manifest_path,
                payload={
                    "expectedKeys": EXPECTED_SPRITE_KEYS,
                    "custom3Uri": custom_3frame_uri,
                    "inferred3Uri": inferred_3frame_uri,
                },
            )

            assert res["outOfBoundsCount"] == 0, label
            assert res["nonZeroSyCount"] == 0, label

            crops = res["cropsByKey"]
            expected_2frame_16x16 = [
                {"sx": 0, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 16, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 0, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 16, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 0, "sy": 0, "sw": 16, "sh": 16},
            ]
            for key_2f in ("detective", "suspect_6", "suspect_7"):
                assert crops[key_2f] == expected_2frame_16x16, (label, key_2f)

            expected_4frame_16x16 = [
                {"sx": 0, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 16, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 32, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 48, "sy": 0, "sw": 16, "sh": 16},
                {"sx": 0, "sy": 0, "sw": 16, "sh": 16},
            ]
            for idx in range(6):
                key_4f = f"suspect_{idx}"
                assert crops[key_4f] == expected_4frame_16x16, (label, key_4f)

            expected_4frame_16x24 = [
                {"sx": 0, "sy": 0, "sw": 16, "sh": 24},
                {"sx": 16, "sy": 0, "sw": 16, "sh": 24},
                {"sx": 32, "sy": 0, "sw": 16, "sh": 24},
                {"sx": 48, "sy": 0, "sw": 16, "sh": 24},
                {"sx": 0, "sy": 0, "sw": 16, "sh": 24},
            ]
            for lv in EXPECTED_POD_KEYS:
                agent_key = f"agent_{lv}"
                assert crops[agent_key] == expected_4frame_16x24, (label, agent_key)

            assert crops["desk"] == [{"sx": 0, "sy": 0, "sw": 48, "sh": 16}] * 5
            assert crops["window_night"] == [{"sx": 0, "sy": 0, "sw": 16, "sh": 32}] * 5
            assert crops["pod_unlocked"] == [{"sx": 0, "sy": 0, "sw": 16, "sh": 32}] * 5
            assert crops["evidence_board"] == [{"sx": 0, "sy": 0, "sw": 32, "sh": 32}] * 5
            assert crops["floor_tile"] == [{"sx": 0, "sy": 0, "sw": 16, "sh": 16}] * 5

            expected_3frame_24x28 = [
                {"sx": 0, "sy": 0, "sw": 24, "sh": 28},
                {"sx": 24, "sy": 0, "sw": 24, "sh": 28},
                {"sx": 48, "sy": 0, "sw": 24, "sh": 28},
                {"sx": 0, "sy": 0, "sw": 24, "sh": 28},
            ]
            assert res["customDetCrops"] == expected_3frame_24x28, label
            assert res["inferredSusCrops"] == expected_3frame_24x28, label


def test_zero_bbox_overlap_and_1_to_1_hit_testing_across_scales():
    with tempfile.TemporaryDirectory() as tmp_dir:
        fixture_manifest_path = Path(tmp_dir) / "manifest.js"
        fixture_manifest_path.write_text(_build_kenney_29_manifest_js(), encoding="utf-8")
        active_manifest_path = str(MANIFEST_PATH) if MANIFEST_PATH.is_file() else str(fixture_manifest_path)

        res = _run_bridge_js(
            """
            const env = setupManifestSceneEnv({
              initialNowMs: 0,
              manifestPath: MANIFEST_FILE
            });

            let lastSuspect = null;
            let lastTab = null;
            let lastPod = null;
            let totalCallbacks = 0;

            const container = env.makeContainer();
            const scene = env.SceneMod.create(container, {
              onSelectSuspect(id) { lastSuspect = id; totalCallbacks += 1; },
              onSelectTab(tab) { lastTab = tab; totalCallbacks += 1; },
              onSelectThinkingPod(pod) { lastPod = pod; totalCallbacks += 1; }
            });
            const canvas = env.createdCanvases[0];
            const ctx = canvas._ctx;

            function boxesOverlapOrTouch(a, b) {
              return !(a.x + a.w < b.x || b.x + b.w < a.x || a.y + a.h < b.y || b.y + b.h < a.y);
            }

            function extractSceneBoxes() {
              const deskRects = ctx.fillRects.filter(
                (r) => r.fillStyle === H + "0f172a" && r.x >= 56 && r.x + r.w <= 716 && r.y >= 98 && r.y + r.h <= 396
              );
              const desks = deskRects.map((r) => {
                const labelHit = ctx.texts.find(
                  (t) => t.x >= r.x && t.x <= r.x + r.w && t.y >= r.y && t.y <= r.y + r.h && /^e[0-9]{2}/.test(t.text)
                );
                const id = labelHit ? labelHit.text.split(" ")[0] : "";
                return { kind: "suspect", id, x: r.x, y: r.y, w: r.w, h: r.h };
              });

              const propOrder = ["canaries", "leaks", "access", "comms", "steps"];
              const propRects = ctx.fillRects
                .filter((r) => r.y === 10 && r.h === 74 && r.x >= 90 && r.x <= 712)
                .sort((a, b) => a.x - b.x);
              const props = propRects.map((r, idx) => ({
                kind: "tab",
                id: propOrder[idx],
                x: r.x,
                y: r.y,
                w: r.w,
                h: r.h
              }));

              const podOrder = ["minimal", "low", "medium", "high", "xhigh"];
              const podRects = ctx.fillRects
                .filter((r) => r.fillStyle === H + "0b1120" && r.x === 718 && r.w === 228 && r.h === 76 && r.y >= 98)
                .sort((a, b) => a.y - b.y);
              const pods = podRects.map((r, idx) => ({
                kind: "pod",
                id: podOrder[idx],
                x: r.x,
                y: r.y,
                w: r.w,
                h: r.h
              }));

              return { desks, props, pods, all: desks.concat(props).concat(pods) };
            }

            function buildSuspectRoster(count, deptCount) {
              const list = [];
              for (let i = 0; i < count; i += 1) {
                const id = "e" + String(i + 1).padStart(2, "0");
                list.push({
                  id,
                  name: "Employee " + id,
                  dept: "Dept" + String((i % deptCount) + 1),
                  role: "Analyst"
                });
              }
              return list;
            }

            function verifyWorldScenario(tierName, suspectCount, deptCounts, runHitTests) {
              const summary = [];
              const scales = [
                { factor: 0.5, left: 24, top: 16 },
                { factor: 1.0, left: 0, top: 0 },
                { factor: 1.5, left: 40, top: 28 }
              ];

              for (const deptCount of deptCounts) {
                const roster = buildSuspectRoster(suspectCount, deptCount);
                ctx.resetLog();
                scene.setCase({
                  id: tierName + "-" + suspectCount + "-d" + deptCount,
                  title: "Topology " + tierName,
                  tier: tierName,
                  suspects: roster
                });

                const boxes = extractSceneBoxes();
                let overlapPairs = 0;
                let outOfGridCount = 0;
                for (let i = 0; i < boxes.all.length; i += 1) {
                  const a = boxes.all[i];
                  if (a.x < 0 || a.y < 0 || a.x + a.w > 960 || a.y + a.h > 520 || a.w <= 0 || a.h <= 0) {
                    outOfGridCount += 1;
                  }
                  for (let j = i + 1; j < boxes.all.length; j += 1) {
                    if (boxesOverlapOrTouch(a, boxes.all[j])) {
                      overlapPairs += 1;
                    }
                  }
                }

                const scaleReports = [];
                if (runHitTests) {
                  for (const sc of scales) {
                    canvas.setBoundingRect({
                      left: sc.left,
                      top: sc.top,
                      width: 960 * sc.factor,
                      height: 520 * sc.factor
                    });
                    const toClient = (lx, ly) => ({
                      clientX: sc.left + lx * sc.factor,
                      clientY: sc.top + ly * sc.factor
                    });

                    let exactMatches = 0;
                    let cornerMatches = 0;
                    for (const box of boxes.all) {
                      const cx = box.x + box.w / 2;
                      const cy = box.y + box.h / 2;
                      lastSuspect = null;
                      lastTab = null;
                      lastPod = null;
                      const before = totalCallbacks;

                      canvas.dispatch("mousemove", toClient(cx, cy));
                      const hoverPointer = canvas.style.cursor === "pointer";
                      canvas.dispatch("click", toClient(cx, cy));
                      const delta = totalCallbacks - before;

                      const matchedCenter = delta === 1 && hoverPointer && (
                        (box.kind === "suspect" && lastSuspect === box.id && lastTab === null && lastPod === null)
                        || (box.kind === "tab" && lastTab === box.id && lastSuspect === null && lastPod === null)
                        || (box.kind === "pod" && lastPod === box.id && lastSuspect === null && lastTab === null)
                      );
                      if (matchedCenter) exactMatches += 1;

                      const corners = [
                        [box.x + 1, box.y + 1],
                        [box.x + box.w - 1, box.y + box.h - 1]
                      ];
                      let bothCornersOk = true;
                      for (const [kx, ky] of corners) {
                        lastSuspect = null;
                        lastTab = null;
                        lastPod = null;
                        const cBefore = totalCallbacks;
                        canvas.dispatch("click", toClient(kx, ky));
                        const cDelta = totalCallbacks - cBefore;
                        const ok = cDelta === 1 && (
                          (box.kind === "suspect" && lastSuspect === box.id)
                          || (box.kind === "tab" && lastTab === box.id)
                          || (box.kind === "pod" && lastPod === box.id)
                        );
                        if (!ok) bothCornersOk = false;
                      }
                      if (bothCornersOk) cornerMatches += 1;
                    }

                    const gapPoints = [
                      [216, 47],
                      [342, 47],
                      [468, 47],
                      [594, 47],
                      [400, 91],
                      [714, 220],
                      [832, 177],
                      [832, 259],
                      [832, 341],
                      [832, 423]
                    ];
                    let gapClean = 0;
                    for (const [gx, gy] of gapPoints) {
                      const gBefore = totalCallbacks;
                      canvas.dispatch("mousemove", toClient(gx, gy));
                      const cursorDefault = canvas.style.cursor === "default";
                      canvas.dispatch("click", toClient(gx, gy));
                      if (cursorDefault && totalCallbacks === gBefore) gapClean += 1;
                    }

                    scaleReports.push({
                      scale: sc.factor,
                      totalTargets: boxes.all.length,
                      exactMatches,
                      cornerMatches,
                      gapPointsChecked: gapPoints.length,
                      gapClean
                    });
                  }
                }

                summary.push({
                  deptCount,
                  deskCount: boxes.desks.length,
                  uniqueDeskIds: Array.from(new Set(boxes.desks.map((d) => d.id))).length,
                  propIds: boxes.props.map((p) => p.id),
                  podIds: boxes.pods.map((p) => p.id),
                  overlapPairs,
                  outOfGridCount,
                  scaleReports
                });
              }
              return summary;
            }

            const hard40WithHits = verifyWorldScenario("hard", 40, [8], true);
            const hard40Topologies = verifyWorldScenario("hard", 40, [1, 4, 6, 12], false);
            const medium20WithHits = verifyWorldScenario("medium", 20, [5], true);
            const medium20Topologies = verifyWorldScenario("medium", 20, [1, 3, 10], false);

            scene.destroy();
            return {
              hard40WithHits,
              hard40Topologies,
              medium20WithHits,
              medium20Topologies
            };
            """,
            manifest_file=active_manifest_path,
        )

        hard_main = res["hard40WithHits"][0]
        assert hard_main["deskCount"] == 40
        assert hard_main["uniqueDeskIds"] == 40
        assert hard_main["propIds"] == EXPECTED_PROP_KEYS
        assert hard_main["podIds"] == EXPECTED_POD_KEYS
        assert hard_main["overlapPairs"] == 0
        assert hard_main["outOfGridCount"] == 0
        assert [r["scale"] for r in hard_main["scaleReports"]] == [0.5, 1.0, 1.5]
        for rep in hard_main["scaleReports"]:
            assert rep["totalTargets"] == 50
            assert rep["exactMatches"] == 50
            assert rep["cornerMatches"] == 50
            assert rep["gapClean"] == rep["gapPointsChecked"] == 10

        for item in res["hard40Topologies"]:
            assert item["deskCount"] == 40
            assert item["uniqueDeskIds"] == 40
            assert item["overlapPairs"] == 0
            assert item["outOfGridCount"] == 0

        med_main = res["medium20WithHits"][0]
        assert med_main["deskCount"] == 20
        assert med_main["uniqueDeskIds"] == 20
        assert med_main["propIds"] == EXPECTED_PROP_KEYS
        assert med_main["podIds"] == EXPECTED_POD_KEYS
        assert med_main["overlapPairs"] == 0
        assert med_main["outOfGridCount"] == 0
        assert [r["scale"] for r in med_main["scaleReports"]] == [0.5, 1.0, 1.5]
        for rep in med_main["scaleReports"]:
            assert rep["totalTargets"] == 30
            assert rep["exactMatches"] == 30
            assert rep["cornerMatches"] == 30
            assert rep["gapClean"] == rep["gapPointsChecked"] == 10

        for item in res["medium20Topologies"]:
            assert item["deskCount"] == 20
            assert item["uniqueDeskIds"] == 20
            assert item["overlapPairs"] == 0
            assert item["outOfGridCount"] == 0


def test_scene_js_zero_external_urls_zero_comments_and_zero_dashes():
    self_path = Path(__file__).resolve()
    scene_src = SCENE_PATH.read_text(encoding="utf-8")
    py_src = self_path.read_text(encoding="utf-8")

    forbidden_external_tokens = (
        HTTP_SCHEME,
        HTTPS_SCHEME,
        WS_SCHEME,
        WSS_SCHEME,
        PROTO_REL,
        CDNJS_TOKEN,
        UNPKG_TOKEN,
        JSDELIVR_TOKEN,
        GOOGLEAPIS_TOKEN,
        FETCH_CALL,
        XHR_TOKEN,
        WEBSOCKET_TOKEN,
        BEACON_TOKEN,
        IMPORT_SCRIPTS_TOKEN,
    )

    for target_name, content in (("scene.js", scene_src), (self_path.name, py_src)):
        assert EM_DASH not in content, f"em dash in {target_name}"
        assert EN_DASH not in content, f"en dash in {target_name}"
        assert FIG_DASH not in content, f"figure dash in {target_name}"
        assert HORIZ_BAR not in content, f"horizontal bar in {target_name}"
        assert LINE_COMMENT not in content, f"line comment in {target_name}"
        assert BLOCK_COMMENT_OPEN not in content, f"block comment in {target_name}"
        assert HTML_COMMENT_OPEN not in content, f"html comment in {target_name}"
        for token in forbidden_external_tokens:
            assert token not in content, f"external/network token {token!r} in {target_name}"

    assert _find_js_comments(scene_src) == []

    for line_no, raw_line in enumerate(scene_src.splitlines(), start=1):
        assert not raw_line.lstrip().startswith(HASH_CHAR), f"hash comment on line {line_no}"

    hex_literal_pattern = re.compile(r'"' + re.escape(HASH_CHAR) + r'[0-9a-fA-F]{6}"')
    scrubbed_scene = hex_literal_pattern.sub('""', scene_src)
    assert HASH_CHAR not in scrubbed_scene

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
    rel_self = self_path.relative_to(ROOT).as_posix()
    rel_scene = SCENE_PATH.relative_to(ROOT).as_posix()
    assert not _matches_protected_rule(rel_self, rules)
    assert not _matches_protected_rule(rel_scene, rules)
