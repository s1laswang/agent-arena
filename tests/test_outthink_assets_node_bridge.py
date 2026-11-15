from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tokenize
from typing import Any

import pytest

from tests.test_outthink_assets_qa import (
    DATA_URI_PREFIX,
    PNG_SIGNATURE,
    assert_region_has_nonblank_pixels,
    decode_png_rgba_zlib,
    parse_png_structure,
    parse_window_outthink_assets,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo" / "out-think-gemini"
ASSETS_DIR = DEMO_DIR / "assets"
SPRITES_DIR = ASSETS_DIR / "sprites"
MANIFEST_JS_PATH = ASSETS_DIR / "manifest.js"
EVIDENCE_CARDS_JS_PATH = DEMO_DIR / "evidence_cards.js"
ASSETS_MD_PATH = ROOT / "docs" / "demo" / "ASSETS.md"

HASH_CHAR = chr(35)
SLASH = chr(47)
STAR = chr(42)
UNICODE_DASH_CODES: tuple[int, ...] = (
    0x2010,
    0x2011,
    0x2012,
    0x2013,
    0x2014,
    0x2015,
    0x2212,
)

EXPECTED_WINDOW_EVIDENCE_HELPERS: tuple[str, ...] = (
    "getOutthinkEvidenceCard",
    "getOutthinkWorldEvidence",
    "getOutthinkEvidenceForCase",
    "listOutthinkEvidenceCards",
    "listOutthinkEvidenceStations",
)

EXPECTED_WINDOW_KEYS: frozenset[str] = frozenset(
    {"OUTTHINK_ASSETS", "OUTTHINK_EVIDENCE_CARDS", *EXPECTED_WINDOW_EVIDENCE_HELPERS}
)

STATION_SPRITE_FIELDS: tuple[str, ...] = (
    "prop_sprite",
    "icon_sprite",
    "analyst_sprite",
    "badge_sprite",
)

CARD_SPRITE_FIELDS: tuple[str, ...] = (
    "sprite_key",
    "prop_sprite_key",
    "analyst_sprite_key",
)

FORBIDDEN_JS_NETWORK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfetch\s*\("),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\bWebSocket\b"),
    re.compile(r"\bsendBeacon\s*\("),
    re.compile(r"\bimportScripts\s*\("),
    re.compile(r"""\brequire\s*\(\s*['"](?:node:)?(?:http|https|net|tls|dns|dgram|child_process)['"]\s*\)"""),
)


def _extract_balanced_json_object(js_text: str, marker: str) -> dict[str, Any]:
    idx = js_text.find(marker)
    assert idx != -1, f"Marker {marker!r} not found in JS bundle"
    start = js_text.find("{", idx)
    assert start != -1, f"Opening brace after {marker!r} not found"
    depth = 0
    in_str: str | None = None
    i = start
    n = len(js_text)
    while i < n:
        ch = js_text[i]
        if in_str is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        if ch in ('"', "'"):
            in_str = ch
            i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(js_text[start : i + 1])
                assert isinstance(parsed, dict)
                return parsed
        i += 1
    raise AssertionError(f"Unbalanced braces after {marker!r}")


def _find_unquoted_js_comments(source: str) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    n = len(source)
    i = 0
    line = 1
    in_quote: str | None = None
    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\" and i + 1 < n:
                if source[i + 1] == "\n":
                    line += 1
                i += 2
                continue
            if ch == "\n":
                line += 1
            elif ch == in_quote:
                in_quote = None
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
        if ch == SLASH and i + 1 < n:
            nxt = source[i + 1]
            if nxt == SLASH:
                hits.append((line, SLASH + SLASH))
                i += 2
                while i < n and source[i] != "\n":
                    i += 1
                continue
            if nxt == STAR:
                hits.append((line, SLASH + STAR))
                i += 2
                while i + 1 < n and not (source[i] == STAR and source[i + 1] == SLASH):
                    if source[i] == "\n":
                        line += 1
                    i += 1
                i += 2
                continue
        i += 1
    return hits


def _strip_js_string_literals(source: str) -> str:
    out: list[str] = []
    i = 0
    n = len(source)
    in_quote: str | None = None
    while i < n:
        ch = source[i]
        if in_quote is not None:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
            i += 1
            continue
        if ch in ("'", '"', "`"):
            in_quote = ch
            out.append('""')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _assert_zero_js_network_primitives(js_source: str, label: str) -> None:
    stripped = _strip_js_string_literals(js_source)
    for pat in FORBIDDEN_JS_NETWORK_PATTERNS:
        match = pat.search(js_source if "require" in pat.pattern else stripped)
        if match is not None:
            raise AssertionError(f"Forbidden network pattern {match.group(0)!r} in {label}")


def _resolve_js_runtime() -> tuple[list[str], dict[str, str]] | None:
    stripped_keys = {
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    }
    clean_env = {k: v for k, v in os.environ.items() if k not in stripped_keys}
    clean_env["GEMINI_API_KEY"] = ""
    clean_env["GOOGLE_GENERATIVE_AI_API_KEY"] = ""

    for binary in ("node", "nodejs", "bun"):
        found = shutil.which(binary)
        if found:
            return [found, "-e"], clean_env

    candidates = [
        shutil.which("opencode"),
        str(Path.home() / "momin" / "bin" / "opencode"),
        str(Path.home() / ".opencode" / "bin" / "opencode"),
        str(Path.home() / ".local" / "bin" / "opencode"),
        "/usr/local/bin/opencode",
    ]
    for cand in candidates:
        if cand and Path(cand).is_file() and os.access(cand, os.X_OK):
            bun_env = dict(clean_env)
            bun_env["BUN_BE_BUN"] = "1"
            probe = subprocess.run(
                [cand, "-e", "const vm = require('vm'); if (typeof vm.createContext !== 'function') process.exit(2);"],
                env=bun_env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if probe.returncode == 0:
                return [cand, "-e"], bun_env
    return None


def _pure_python_bundle_exports(js_source: str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    _assert_zero_js_network_primitives(js_source, label)
    window_writes: dict[str, Any] = {}
    cjs_exports: dict[str, Any] = {}

    for match in re.finditer(r"(?:\bwindow|\b_w|\bglobalThis)\.([A-Za-z0-9_$]+)\s*=", js_source):
        prop = match.group(1)
        if prop in ("OUTTHINK_ASSETS",):
            if prop in window_writes:
                raise AssertionError(f"Duplicate assignment to {prop!r} inside {label}")
            window_writes[prop] = parse_window_outthink_assets(js_source)
        elif prop == "OUTTHINK_EVIDENCE_CARDS":
            if prop not in window_writes:
                window_writes[prop] = _extract_balanced_json_object(js_source, "_w.OUTTHINK_EVIDENCE_CARDS")
        else:
            window_writes.setdefault(prop, f"<function:{prop}>")

    if "module.exports" in js_source:
        cjs_match = re.search(r"module\.exports\s*=\s*\{([^}]+)\}", js_source)
        assert cjs_match is not None, f"Malformed module.exports block in {label}"
        for entry in cjs_match.group(1).split(","):
            entry = entry.strip()
            if not entry:
                continue
            key_part = entry.split(":", 1)[0].strip()
            assert key_part in window_writes, f"Export {key_part!r} not bound on window in {label}"
            cjs_exports[key_part] = window_writes[key_part]

    return window_writes, cjs_exports


def load_bundles_pure_python(
    manifest_path: Path = MANIFEST_JS_PATH,
    evidence_path: Path = EVIDENCE_CARDS_JS_PATH,
    reverse_order: bool = False,
) -> dict[str, Any]:
    manifest_src = manifest_path.read_text(encoding="utf-8")
    evidence_src = evidence_path.read_text(encoding="utf-8")

    steps = [
        ("manifest.js", manifest_src),
        ("evidence_cards.js", evidence_src),
    ]
    if reverse_order:
        steps.reverse()

    shared_window: dict[str, Any] = {}
    cjs_modules: dict[str, dict[str, Any]] = {}
    write_owners: dict[str, str] = {}

    for name, src in steps:
        win_props, cjs_props = _pure_python_bundle_exports(src, name)
        for prop, val in win_props.items():
            if prop in shared_window:
                raise AssertionError(
                    f"Global window collision on {prop!r}: written by both {write_owners[prop]} and {name}"
                )
            shared_window[prop] = val
            write_owners[prop] = name
        cjs_modules[name] = cjs_props

    bundle = shared_window["OUTTHINK_EVIDENCE_CARDS"]

    def get_card(card_id: str) -> dict[str, Any] | None:
        if not isinstance(card_id, str):
            return None
        target = card_id.strip()
        for c in bundle.get("cards", []):
            if isinstance(c, dict) and c.get("card_id") == target:
                return c
        return None

    def get_world(case_or_tier: Any, seed: Any = None) -> dict[str, Any] | None:
        by_world = bundle.get("by_world", {})
        if case_or_tier is None:
            return None
        tier_val = ""
        seed_val = seed
        if isinstance(case_or_tier, dict):
            wk = case_or_tier.get("world_key")
            if wk and wk in by_world:
                return by_world[wk]
            tier_val = str(case_or_tier.get("tier") or case_or_tier.get("difficulty") or "")
            seed_val = case_or_tier.get("seed") if "seed" in case_or_tier else case_or_tier.get("worldSeed")
            if (not tier_val or seed_val is None) and isinstance(case_or_tier.get("id"), str):
                case_or_tier = case_or_tier["id"]
        if isinstance(case_or_tier, str) and seed_val is None:
            raw = case_or_tier.strip()
            if raw in by_world:
                return by_world[raw]
            for sep in ("/", "|", "_", "-"):
                if sep in raw:
                    parts = raw.split(sep)
                    if len(parts) >= 2:
                        tier_val = parts[-2]
                        seed_val = parts[-1]
                    break
        elif isinstance(case_or_tier, str):
            tier_val = case_or_tier
        key = f"{str(tier_val).strip().lower()}/{'' if seed_val is None else str(seed_val).strip()}"
        return by_world.get(key)

    def get_for_case(case_or_tier: Any, seed: Any = None, modality: str | None = None) -> dict[str, Any] | None:
        w = get_world(case_or_tier, seed)
        if w is None:
            return None
        if modality is None or not str(modality).strip():
            return w
        cid = (w.get("primary_card_ids") or {}).get(str(modality).strip().lower())
        return get_card(cid) if cid else None

    def list_cards(flt: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cards = list(bundle.get("cards", []))
        if not flt:
            return cards
        out: list[dict[str, Any]] = []
        for c in cards:
            if flt.get("modality") and c.get("modality") != str(flt["modality"]).lower():
                continue
            if flt.get("tier") and c.get("tier") != str(flt["tier"]).lower():
                continue
            if flt.get("seed") is not None and int(c.get("seed", -1)) != int(flt["seed"]):
                continue
            if flt.get("thinking_level") and c.get("thinking_level") != str(flt["thinking_level"]).lower():
                continue
            if flt.get("run_dir") and c.get("run_dir") != str(flt["run_dir"]):
                continue
            out.append(c)
        return out

    def list_stations() -> list[dict[str, Any]]:
        return list(bundle.get("room_stations", []))

    shared_window["getOutthinkEvidenceCard"] = get_card
    shared_window["getOutthinkWorldEvidence"] = get_world
    shared_window["getOutthinkEvidenceForCase"] = get_for_case
    shared_window["listOutthinkEvidenceCards"] = list_cards
    shared_window["listOutthinkEvidenceStations"] = list_stations

    return {
        "window": shared_window,
        "cjs": cjs_modules,
        "write_owners": write_owners,
    }


NODE_BRIDGE_HARNESS_JS = """
const fs = require("fs");
const path = require("path");
const vm = require("vm");
const crypto = require("crypto");

const manifestPath = process.env.OUTTHINK_MANIFEST_JS;
const evidencePath = process.env.OUTTHINK_EVIDENCE_JS;
const spritesDir = process.env.OUTTHINK_SPRITES_DIR;

const netGuard = () => {
  throw new Error("FORBIDDEN_NETWORK_CALL");
};

for (const modName of ["http", "https", "net", "tls", "dns"]) {
  try {
    const m = require(modName);
    for (const fn of ["request", "get", "connect", "createConnection", "lookup", "resolve"]) {
      if (typeof m[fn] === "function") {
        m[fn] = netGuard;
      }
    }
  } catch (_err) {}
}
globalThis.fetch = netGuard;

const manifestSrc = fs.readFileSync(manifestPath, "utf8");
const evidenceSrc = fs.readFileSync(evidencePath, "utf8");

function runSharedWindowVm(order, selfReferentialWindow) {
  const writeCounts = Object.create(null);
  const collisions = [];
  const rawWindow = Object.create(null);
  const trackedWindow = new Proxy(rawWindow, {
    set(target, prop, value) {
      if (typeof prop === "string" && prop !== "window" && prop !== "globalThis" && prop !== "self") {
        writeCounts[prop] = (writeCounts[prop] || 0) + 1;
        if (writeCounts[prop] > 1) {
          collisions.push(prop);
        }
      }
      target[prop] = value;
      return true;
    }
  });

  let sandbox;
  if (selfReferentialWindow) {
    rawWindow.fetch = netGuard;
    rawWindow.XMLHttpRequest = netGuard;
    rawWindow.WebSocket = netGuard;
    sandbox = trackedWindow;
    sandbox.window = trackedWindow;
    sandbox.self = trackedWindow;
    sandbox.globalThis = trackedWindow;
  } else {
    sandbox = {
      window: trackedWindow,
      fetch: netGuard,
      XMLHttpRequest: netGuard,
      WebSocket: netGuard
    };
    sandbox.globalThis = sandbox;
  }

  const ctx = vm.createContext(sandbox);
  for (const [label, code] of order) {
    vm.runInContext(code, ctx, { filename: label, timeout: 5000 });
  }

  const userKeys = Object.keys(rawWindow)
    .filter((k) => !["window", "self", "globalThis", "fetch", "XMLHttpRequest", "WebSocket", "_w"].includes(k))
    .sort();

  return {
    userKeys,
    collisions,
    rawWindow,
    sandbox
  };
}

const vmForward = runSharedWindowVm(
  [["manifest.js", manifestSrc], ["evidence_cards.js", evidenceSrc]],
  false
);
const vmReverse = runSharedWindowVm(
  [["evidence_cards.js", evidenceSrc], ["manifest.js", manifestSrc]],
  false
);
const vmBrowserSelf = runSharedWindowVm(
  [["manifest.js", manifestSrc], ["evidence_cards.js", evidenceSrc]],
  true
);

function runCommonJsRequire(reverse) {
  const resolvedManifest = require.resolve(manifestPath);
  const resolvedEvidence = require.resolve(evidencePath);
  delete require.cache[resolvedManifest];
  delete require.cache[resolvedEvidence];

  const writeCounts = Object.create(null);
  const collisions = [];
  const rawWin = Object.create(null);
  globalThis.window = new Proxy(rawWin, {
    set(target, prop, value) {
      if (typeof prop === "string") {
        writeCounts[prop] = (writeCounts[prop] || 0) + 1;
        if (writeCounts[prop] > 1) {
          collisions.push(prop);
        }
      }
      target[prop] = value;
      return true;
    }
  });

  let modManifest;
  let modEvidence;
  if (!reverse) {
    modManifest = require(resolvedManifest);
    modEvidence = require(resolvedEvidence);
  } else {
    modEvidence = require(resolvedEvidence);
    modManifest = require(resolvedManifest);
  }

  return {
    windowKeys: Object.keys(rawWin).sort(),
    collisions,
    evidenceExportKeys: Object.keys(modEvidence).sort(),
    manifestExportKeys: Object.keys(modManifest).sort(),
    sameEvidenceRef: modEvidence.OUTTHINK_EVIDENCE_CARDS === rawWin.OUTTHINK_EVIDENCE_CARDS,
    hasAssetsOnWindow: !!rawWin.OUTTHINK_ASSETS && rawWin.OUTTHINK_ASSETS.version === 1
  };
}

const cjsForward = runCommonJsRequire(false);
const cjsReverse = runCommonJsRequire(true);

const win = vmForward.rawWindow;
const assets = win.OUTTHINK_ASSETS || {};
const spriteMap = assets.sprites || {};
const packList = Array.isArray(assets.packs) ? assets.packs : [];
const evidence = win.OUTTHINK_EVIDENCE_CARDS;
const stations = win.listOutthinkEvidenceStations();
const cards = win.listOutthinkEvidenceCards();

const referencedSprites = new Set();
const missingSprites = [];

for (const st of stations) {
  for (const field of ["prop_sprite", "icon_sprite", "analyst_sprite", "badge_sprite"]) {
    const key = st[field];
    referencedSprites.add(key);
    if (!spriteMap[key]) {
      missingSprites.push(`station:${st.station_id}:${field}:${key}`);
    }
  }
}

for (const card of cards) {
  for (const field of ["sprite_key", "prop_sprite_key", "analyst_sprite_key"]) {
    const key = card[field];
    referencedSprites.add(key);
    if (!spriteMap[key]) {
      missingSprites.push(`card:${card.card_id}:${field}:${key}`);
    }
  }
}

const worldKeys = Object.keys(evidence.by_world);
let worldModalityLookups = 0;
for (const wk of worldKeys) {
  const wEntry = win.getOutthinkWorldEvidence(wk);
  if (!wEntry || wEntry.world_key !== wk) {
    throw new Error(`World lookup failed for ${wk}`);
  }
  for (const mod of wEntry.modalities) {
    const pCard = win.getOutthinkEvidenceForCase(wEntry.tier, wEntry.seed, mod);
    if (!pCard || !spriteMap[pCard.sprite_key] || !spriteMap[pCard.prop_sprite_key] || !spriteMap[pCard.analyst_sprite_key]) {
      throw new Error(`Case card sprite resolution failed for ${wk} ${mod}`);
    }
    worldModalityLookups += 1;
  }
}

const prefix = "data:image/png;base64,";
let verifiedByteExactCount = 0;
const byteMismatches = [];

for (const [key, entry] of Object.entries(spriteMap)) {
  if (typeof entry.dataUri !== "string" || !entry.dataUri.startsWith(prefix)) {
    byteMismatches.push(`${key}:bad_prefix`);
    continue;
  }
  const b64 = entry.dataUri.slice(prefix.length);
  const decoded = Buffer.from(b64, "base64");
  if (decoded.toString("base64") !== b64) {
    byteMismatches.push(`${key}:non_canonical_base64`);
    continue;
  }
  const diskPath = path.join(spritesDir, `${key}.png`);
  const diskBytes = fs.readFileSync(diskPath);
  if (Buffer.compare(decoded, diskBytes) !== 0) {
    byteMismatches.push(`${key}:byte_mismatch`);
    continue;
  }
  if (decoded.subarray(0, 8).toString("hex") !== "89504e470d0a1a0a") {
    byteMismatches.push(`${key}:bad_png_sig`);
    continue;
  }
  const ihdrWidth = decoded.readUInt32BE(16);
  const ihdrHeight = decoded.readUInt32BE(20);
  if (ihdrWidth !== entry.width || ihdrHeight !== entry.height) {
    byteMismatches.push(`${key}:dims_mismatch`);
    continue;
  }
  const sha = crypto.createHash("sha256").update(decoded).digest("hex");
  if (sha.length !== 64) {
    byteMismatches.push(`${key}:bad_sha`);
    continue;
  }
  verifiedByteExactCount += 1;
}

process.stdout.write(JSON.stringify({
  vmForwardKeys: vmForward.userKeys,
  vmReverseKeys: vmReverse.userKeys,
  vmBrowserSelfKeys: vmBrowserSelf.userKeys,
  vmCollisions: [
    ...vmForward.collisions,
    ...vmReverse.collisions,
    ...vmBrowserSelf.collisions
  ],
  globalThisMirrored: [
    "OUTTHINK_EVIDENCE_CARDS",
    "getOutthinkEvidenceCard",
    "getOutthinkWorldEvidence",
    "getOutthinkEvidenceForCase",
    "listOutthinkEvidenceCards",
    "listOutthinkEvidenceStations"
  ].every((k) => vmForward.sandbox[k] === vmForward.rawWindow[k]),
  cjsForward,
  cjsReverse,
  manifestVersion: assets.version,
  packCount: packList.length,
  spriteCount: Object.keys(spriteMap).length,
  stationCount: stations.length,
  cardCount: cards.length,
  worldCount: worldKeys.length,
  worldModalityLookups,
  referencedSpriteKeys: Array.from(referencedSprites).sort(),
  missingSprites,
  verifiedByteExactCount,
  byteMismatches,
  packs: packList
}));
"""


def run_node_vm_and_cjs_bridge(
    tmp_cwd: Path,
    manifest_path: Path = MANIFEST_JS_PATH,
    evidence_path: Path = EVIDENCE_CARDS_JS_PATH,
    sprites_dir: Path = SPRITES_DIR,
) -> dict[str, Any] | None:
    rt = _resolve_js_runtime()
    if rt is None:
        return None
    cmd_prefix, env = rt
    run_env = dict(env)
    run_env["OUTTHINK_MANIFEST_JS"] = str(manifest_path)
    run_env["OUTTHINK_EVIDENCE_JS"] = str(evidence_path)
    run_env["OUTTHINK_SPRITES_DIR"] = str(sprites_dir)
    proc = subprocess.run(
        [*cmd_prefix, NODE_BRIDGE_HARNESS_JS],
        cwd=tmp_cwd,
        env=run_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"Node/VM cross-bundle bridge failed ({proc.returncode}): {proc.stderr}"
    result = json.loads(proc.stdout)
    assert isinstance(result, dict)
    return result


def _collect_all_sprite_key_fields(obj: Any, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            path = f"{prefix}.{k}" if prefix else k
            if "sprite" in k.lower() and isinstance(v, str):
                found.append((path, v))
            else:
                found.extend(_collect_all_sprite_key_fields(v, path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            path = f"{prefix}[{idx}]"
            found.extend(_collect_all_sprite_key_fields(item, path))
    return found


def _parse_assets_md_summary_table(md_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in md_text.splitlines():
        sline = line.strip()
        if not sline.startswith("|"):
            continue
        cells = [c.strip().strip("`").strip() for c in sline.strip("|").split("|")]
        if len(cells) < 6:
            continue
        pack_id, pack_name, author, lic, source_url, download_url = cells[:6]
        if pack_id.lower() in ("pack id", "---") or set(pack_id) <= {"-", ":"}:
            continue
        if source_url.startswith("https://opengameart.org/content/"):
            rows.append(
                {
                    "id": pack_id,
                    "name": pack_name,
                    "author": author,
                    "license": lic,
                    "url": source_url,
                    "download_url": download_url,
                }
            )
    return rows


def _parse_assets_md_pack_subsections(md_text: str) -> list[dict[str, str]]:
    heading_prefix = HASH_CHAR * 3 + " "
    heading_re = re.compile(r"^" + re.escape(heading_prefix) + r"\d+\.\s+`([a-z0-9-]+)`\s*$")
    field_re = re.compile(r"^-\s+\*\*([^*]+):\*\*\s+(.+?)\s*$")

    sections: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in md_text.splitlines():
        line = raw_line.strip()
        h_match = heading_re.match(line)
        if h_match is not None:
            if current is not None:
                sections.append(current)
            current = {"id": h_match.group(1)}
            continue
        if line.startswith(HASH_CHAR * 2 + " ") and current is not None:
            sections.append(current)
            current = None
            continue
        if current is not None:
            f_match = field_re.match(line)
            if f_match is not None:
                label = f_match.group(1).strip()
                val = f_match.group(2).strip()
                if label == "Exact Pack Name":
                    current["name"] = val
                elif label == "Direct Page URL":
                    current["url"] = val
                elif label == "Direct Download URL":
                    current["download_url"] = val
                elif label == "Author":
                    current["author"] = val
                elif label == "License":
                    lic_tok = val.split()[0].strip("`")
                    current["license"] = lic_tok
                elif label == "Pixel Detective Room Elements Provided":
                    current["elements"] = val
    if current is not None:
        sections.append(current)
    return sections


def _parse_assets_md_sprite_coverage(md_text: str) -> dict[str, set[str]]:
    coverage: dict[str, set[str]] = {}
    range_re = re.compile(r"`([a-z_]+_)(\d+)`\.\.`\1(\d+)`")
    token_re = re.compile(r"`([a-z0-9_-]+)`")
    in_coverage = False
    for line in md_text.splitlines():
        sline = line.strip()
        if "Sprite Manifest Coverage" in sline:
            in_coverage = True
            continue
        if not in_coverage or not sline.startswith("|"):
            continue
        cells = [c.strip() for c in sline.strip("|").split("|")]
        if len(cells) < 3:
            continue
        keys_cell, packs_cell = cells[1], cells[2]
        if keys_cell.lower() == "sprite keys" or set(keys_cell) <= {"-", ":", " "}:
            continue
        row_packs = set(token_re.findall(packs_cell))
        row_keys = set(token_re.findall(keys_cell))
        for prefix, start_s, end_s in range_re.findall(keys_cell):
            for idx in range(int(start_s), int(end_s) + 1):
                row_keys.add(f"{prefix}{idx}")
        for key in row_keys:
            coverage.setdefault(key, set()).update(row_packs)
    return coverage


def test_both_bundles_load_cleanly_in_shared_window_and_commonjs_without_collisions_or_network(
    tmp_path: Path,
) -> None:
    assert MANIFEST_JS_PATH.is_file(), f"Missing {MANIFEST_JS_PATH}"
    assert EVIDENCE_CARDS_JS_PATH.is_file(), f"Missing {EVIDENCE_CARDS_JS_PATH}"

    py_forward = load_bundles_pure_python(reverse_order=False)
    py_reverse = load_bundles_pure_python(reverse_order=True)
    assert set(py_forward["window"].keys()) == EXPECTED_WINDOW_KEYS
    assert set(py_reverse["window"].keys()) == EXPECTED_WINDOW_KEYS
    assert py_forward["write_owners"]["OUTTHINK_ASSETS"] == "manifest.js"
    assert py_forward["write_owners"]["OUTTHINK_EVIDENCE_CARDS"] == "evidence_cards.js"
    for helper_name in EXPECTED_WINDOW_EVIDENCE_HELPERS:
        assert py_forward["write_owners"][helper_name] == "evidence_cards.js"
    assert set(py_forward["cjs"]["evidence_cards.js"].keys()) == {
        "OUTTHINK_EVIDENCE_CARDS",
        *EXPECTED_WINDOW_EVIDENCE_HELPERS,
    }
    assert py_forward["cjs"]["manifest.js"] == {}

    isolated_cwd = tmp_path / "offline_sandbox"
    isolated_cwd.mkdir()
    assert not (isolated_cwd / "assets").exists()

    vm_res = run_node_vm_and_cjs_bridge(isolated_cwd)
    if vm_res is not None:
        expected_sorted_keys = sorted(EXPECTED_WINDOW_KEYS)
        assert vm_res["vmForwardKeys"] == expected_sorted_keys
        assert vm_res["vmReverseKeys"] == expected_sorted_keys
        assert vm_res["vmBrowserSelfKeys"] == expected_sorted_keys
        assert vm_res["vmCollisions"] == []
        assert vm_res["globalThisMirrored"] is True

        for cjs_run in (vm_res["cjsForward"], vm_res["cjsReverse"]):
            assert cjs_run["windowKeys"] == expected_sorted_keys
            assert cjs_run["collisions"] == []
            assert cjs_run["evidenceExportKeys"] == sorted(
                ["OUTTHINK_EVIDENCE_CARDS", *EXPECTED_WINDOW_EVIDENCE_HELPERS]
            )
            assert cjs_run["manifestExportKeys"] == []
            assert cjs_run["sameEvidenceRef"] is True
            assert cjs_run["hasAssetsOnWindow"] is True

        assert vm_res["manifestVersion"] == 1
        assert vm_res["packCount"] == 11
        assert vm_res["spriteCount"] == 39
        assert vm_res["stationCount"] == 4
        assert vm_res["cardCount"] == 100
        assert vm_res["worldCount"] == 27
        assert vm_res["worldModalityLookups"] > 0
        assert vm_res["missingSprites"] == []
        assert vm_res["verifiedByteExactCount"] == 39
        assert vm_res["byteMismatches"] == []


def test_collision_and_network_guards_reject_rogue_bundles(tmp_path: Path) -> None:
    colliding_js = tmp_path / "colliding_evidence.js"
    colliding_js.write_text(
        'var _w = typeof window !== "undefined" ? window : globalThis;\n'
        '_w.OUTTHINK_ASSETS = {"clobbered": true};\n'
        '_w.OUTTHINK_EVIDENCE_CARDS = {"cards": [], "room_stations": [], "by_world": {}};\n'
        "_w.listOutthinkEvidenceStations = function() { return []; };\n"
        "_w.listOutthinkEvidenceCards = function() { return []; };\n"
        "_w.getOutthinkWorldEvidence = function() { return null; };\n"
        "_w.getOutthinkEvidenceForCase = function() { return null; };\n"
        "_w.getOutthinkEvidenceCard = function() { return null; };\n",
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="collision"):
        load_bundles_pure_python(MANIFEST_JS_PATH, colliding_js)

    network_js = tmp_path / "network_evidence.js"
    network_js.write_text(
        'var _w = typeof window !== "undefined" ? window : globalThis;\n'
        'fetch("https://example.com/leak.png");\n'
        '_w.OUTTHINK_EVIDENCE_CARDS = {"cards": [], "room_stations": [], "by_world": {}};\n',
        encoding="utf-8",
    )
    with pytest.raises(AssertionError, match="Forbidden network pattern"):
        load_bundles_pure_python(MANIFEST_JS_PATH, network_js)

    dangling_js = tmp_path / "dangling_sprite_evidence.js"
    dangling_js.write_text(
        'var _w = typeof window !== "undefined" ? window : globalThis;\n'
        '_w.OUTTHINK_EVIDENCE_CARDS = {\n'
        '  "cards": [{"card_id": "c0", "sprite_key": "ghost_missing_icon", "prop_sprite_key": "desk", "analyst_sprite_key": "agent_low"}],\n'
        '  "room_stations": [{"station_id": "s0", "prop_sprite": "desk", "icon_sprite": "icon_memo", "analyst_sprite": "agent_low", "badge_sprite": "missing_badge"}],\n'
        '  "by_world": {}\n'
        '};\n'
        "_w.listOutthinkEvidenceStations = function() { return _w.OUTTHINK_EVIDENCE_CARDS.room_stations; };\n"
        "_w.listOutthinkEvidenceCards = function() { return _w.OUTTHINK_EVIDENCE_CARDS.cards; };\n"
        "_w.getOutthinkWorldEvidence = function() { return null; };\n"
        "_w.getOutthinkEvidenceForCase = function() { return null; };\n"
        "_w.getOutthinkEvidenceCard = function() { return null; };\n",
        encoding="utf-8",
    )

    rt = _resolve_js_runtime()
    if rt is not None:
        cmd_prefix, env = rt
        run_env = dict(env)
        run_env["OUTTHINK_MANIFEST_JS"] = str(MANIFEST_JS_PATH)
        run_env["OUTTHINK_EVIDENCE_JS"] = str(network_js)
        run_env["OUTTHINK_SPRITES_DIR"] = str(SPRITES_DIR)
        proc = subprocess.run(
            [*cmd_prefix, NODE_BRIDGE_HARNESS_JS],
            cwd=tmp_path,
            env=run_env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode != 0
        assert "FORBIDDEN_NETWORK_CALL" in proc.stderr

        col_res = run_node_vm_and_cjs_bridge(tmp_path, MANIFEST_JS_PATH, colliding_js, SPRITES_DIR)
        assert col_res is not None
        assert "OUTTHINK_ASSETS" in col_res["vmCollisions"]
        assert "OUTTHINK_ASSETS" in col_res["cjsForward"]["collisions"]

        tampered_sprites = tmp_path / "tampered_sprites"
        shutil.copytree(SPRITES_DIR, tampered_sprites)
        desk_png = tampered_sprites / "desk.png"
        desk_bytes = bytearray(desk_png.read_bytes())
        desk_bytes[-1] ^= 0x01
        desk_png.write_bytes(bytes(desk_bytes))

        dang_res = run_node_vm_and_cjs_bridge(tmp_path, MANIFEST_JS_PATH, dangling_js, tampered_sprites)
        assert dang_res is not None
        assert "station:s0:badge_sprite:missing_badge" in dang_res["missingSprites"]
        assert "card:c0:sprite_key:ghost_missing_icon" in dang_res["missingSprites"]
        assert "desk:byte_mismatch" in dang_res["byteMismatches"]


def test_pure_python_fallback_contract_when_node_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "_resolve_js_runtime", lambda: None)
    assert run_node_vm_and_cjs_bridge(tmp_path) is None

    state = load_bundles_pure_python()
    win = state["window"]
    assets = win["OUTTHINK_ASSETS"]
    sprites = assets["sprites"]

    stations = win["listOutthinkEvidenceStations"]()
    assert len(stations) == 4
    for st in stations:
        for field in STATION_SPRITE_FIELDS:
            assert st[field] in sprites

    cards = win["listOutthinkEvidenceCards"]()
    assert len(cards) == 100
    for card in cards:
        for field in CARD_SPRITE_FIELDS:
            assert card[field] in sprites

    hard8 = win["getOutthinkWorldEvidence"]("hard", 8)
    assert hard8 is not None and hard8["true_mole"] == "e06"
    heat_card = win["getOutthinkEvidenceForCase"]({"difficulty": "HARD", "worldSeed": 8}, None, "heatmap")
    assert heat_card is not None
    assert heat_card["sprite_key"] in sprites
    assert heat_card["prop_sprite_key"] in sprites
    assert heat_card["analyst_sprite_key"] in sprites


def test_every_evidence_sprite_reference_resolves_to_byte_exact_on_disk_png() -> None:
    state = load_bundles_pure_python()
    win = state["window"]
    assets = win["OUTTHINK_ASSETS"]
    evidence = win["OUTTHINK_EVIDENCE_CARDS"]
    sprites = assets["sprites"]
    assert isinstance(sprites, dict) and len(sprites) == 39

    all_sprite_fields = _collect_all_sprite_key_fields(evidence)
    assert len(all_sprite_fields) == 4 * len(STATION_SPRITE_FIELDS) + 100 * len(CARD_SPRITE_FIELDS)

    stations_by_id: dict[str, dict[str, Any]] = {}
    referenced_keys: set[str] = set()

    for idx, st in enumerate(evidence["room_stations"]):
        sid = st["station_id"]
        assert sid not in stations_by_id
        stations_by_id[sid] = st
        for field in STATION_SPRITE_FIELDS:
            skey = st.get(field)
            assert isinstance(skey, str) and skey in sprites, (
                f"room_stations[{idx}].{field}={skey!r} missing from OUTTHINK_ASSETS.sprites"
            )
            referenced_keys.add(skey)

    assert len(stations_by_id) == 4

    thinking_analyst_map = {
        "minimal": "agent_minimal",
        "low": "agent_low",
        "medium": "agent_medium",
        "high": "agent_high",
        "xhigh": "agent_xhigh",
    }

    for idx, card in enumerate(evidence["cards"]):
        cid = card["card_id"]
        sid = card["station_id"]
        assert sid in stations_by_id, f"Card {cid} references unknown station_id {sid!r}"
        st = stations_by_id[sid]
        assert card["sprite_key"] == st["icon_sprite"], f"Card {cid} sprite_key != station icon_sprite"
        assert card["prop_sprite_key"] == st["prop_sprite"], f"Card {cid} prop_sprite_key != station prop_sprite"
        if card["modality"] == "heatmap":
            expected_analyst = thinking_analyst_map.get(card["thinking_level"], st["analyst_sprite"])
            assert card["analyst_sprite_key"] == expected_analyst
        else:
            assert card["analyst_sprite_key"] == st["analyst_sprite"], (
                f"Card {cid} analyst_sprite_key != station analyst_sprite"
            )
        for field in CARD_SPRITE_FIELDS:
            skey = card.get(field)
            assert isinstance(skey, str) and skey in sprites, (
                f"cards[{idx}] ({cid}).{field}={skey!r} missing from OUTTHINK_ASSETS.sprites"
            )
            referenced_keys.add(skey)

    for wk, wdata in evidence["by_world"].items():
        cmp_obj = wdata.get("thinking_comparison")
        if cmp_obj is not None:
            low_c = win["getOutthinkEvidenceCard"](cmp_obj["low_card_id"])
            high_c = win["getOutthinkEvidenceCard"](cmp_obj["high_card_id"])
            assert low_c is not None and high_c is not None, f"Missing paired cards for {wk}"
            assert low_c["analyst_sprite_key"] == "agent_low"
            assert high_c["analyst_sprite_key"] == "agent_high"
            assert sprites["agent_low"]["dataUri"] != sprites["agent_high"]["dataUri"]

    for path_label, skey in all_sprite_fields:
        assert skey in sprites, f"{path_label}={skey!r} missing from OUTTHINK_ASSETS.sprites"
        referenced_keys.add(skey)

    assert len(referenced_keys) == 16

    keys_to_verify = sorted(set(sprites.keys()) | referenced_keys)
    for skey in keys_to_verify:
        entry = sprites[skey]
        assert isinstance(entry, dict)
        expected_rel = f"assets/sprites/{skey}.png"
        assert entry.get("path") == expected_rel

        disk_png_path = DEMO_DIR / expected_rel
        assert disk_png_path.is_file(), f"Missing on-disk sprite PNG {disk_png_path}"
        disk_bytes = disk_png_path.read_bytes()
        assert len(disk_bytes) > 0

        data_uri = entry.get("dataUri")
        assert isinstance(data_uri, str) and data_uri.startswith(DATA_URI_PREFIX), (
            f"{skey}: invalid dataUri prefix"
        )
        b64_payload = data_uri[len(DATA_URI_PREFIX) :]
        decoded_bytes = base64.b64decode(b64_payload, validate=True)
        assert base64.b64encode(decoded_bytes).decode("ascii") == b64_payload, (
            f"{skey}: non-canonical base64 in dataUri"
        )
        assert decoded_bytes[:8] == PNG_SIGNATURE, f"{skey}: decoded dataUri missing PNG signature"
        assert decoded_bytes == disk_bytes, (
            f"{skey}: dataUri bytes ({len(decoded_bytes)} B, sha256={hashlib.sha256(decoded_bytes).hexdigest()}) "
            f"!= on-disk {disk_png_path.name} ({len(disk_bytes)} B, sha256={hashlib.sha256(disk_bytes).hexdigest()})"
        )

        png_info = parse_png_structure(decoded_bytes)
        assert png_info["bit_depth"] == 8
        assert png_info["color_type"] == 6
        assert png_info["interlace"] == 0

        w, h, pixels = decode_png_rgba_zlib(decoded_bytes)
        frames = int(entry["frames"])
        fw = int(entry["frameWidth"])
        fh = int(entry["frameHeight"])
        assert (w, h) == (entry["width"], entry["height"])
        assert w == frames * fw
        assert h == fh
        for frame_idx in range(frames):
            assert_region_has_nonblank_pixels(
                pixels,
                w,
                h,
                frame_idx * fw,
                0,
                fw,
                fh,
                f"{skey}[{frame_idx}]",
            )


def test_every_cc0_pack_and_attribution_in_outthink_assets_matches_assets_md(tmp_path: Path) -> None:
    assert ASSETS_MD_PATH.is_file(), f"Missing {ASSETS_MD_PATH}"
    md_text = ASSETS_MD_PATH.read_text(encoding="utf-8")

    summary_rows = _parse_assets_md_summary_table(md_text)
    subsections = _parse_assets_md_pack_subsections(md_text)
    coverage_map = _parse_assets_md_sprite_coverage(md_text)

    assert len(summary_rows) == 11
    assert len(subsections) == 11

    state = load_bundles_pure_python()
    assets = state["window"]["OUTTHINK_ASSETS"]
    evidence = state["window"]["OUTTHINK_EVIDENCE_CARDS"]
    manifest_packs = assets["packs"]
    sprites = assets["sprites"]

    vm_res = run_node_vm_and_cjs_bridge(tmp_path)
    if vm_res is not None:
        assert vm_res["packs"] == manifest_packs

    assert isinstance(manifest_packs, list) and len(manifest_packs) == 11
    seen_ids: set[str] = set()
    packs_by_id: dict[str, dict[str, Any]] = {}

    for idx, pack in enumerate(manifest_packs):
        assert isinstance(pack, dict)
        pid = pack["id"]
        assert pid not in seen_ids, f"Duplicate pack id {pid!r}"
        seen_ids.add(pid)
        packs_by_id[pid] = pack

        table_row = summary_rows[idx]
        sub_row = subsections[idx]
        assert pid == table_row["id"] == sub_row["id"]
        assert pack["name"] == table_row["name"] == sub_row["name"]
        assert pack["author"] == table_row["author"] == sub_row["author"]
        assert pack["license"] == "CC0-1.0"
        assert table_row["license"] == "CC0-1.0"
        assert sub_row["license"] == "CC0-1.0"
        assert pack["url"] == table_row["url"] == sub_row["url"]
        assert pack["url"].startswith("https://opengameart.org/content/")
        assert table_row["download_url"] == sub_row["download_url"]
        assert table_row["download_url"].startswith("https://opengameart.org/sites/default/files/")
        assert set(pack.keys()) == {"id", "name", "author", "license", "url"}

    assert set(coverage_map.keys()) == set(sprites.keys())

    used_packs: set[str] = set()
    for skey, entry in sprites.items():
        pack_id = entry.get("pack")
        assert isinstance(pack_id, str) and pack_id in packs_by_id, (
            f"Sprite {skey!r} references unknown pack {pack_id!r}"
        )
        assert pack_id in coverage_map[skey], (
            f"Sprite {skey!r} pack {pack_id!r} missing from ASSETS.md coverage row {sorted(coverage_map[skey])}"
        )
        used_packs.add(pack_id)

    assert used_packs == seen_ids

    for _, ref_skey in _collect_all_sprite_key_fields(evidence):
        ref_pack = sprites[ref_skey]["pack"]
        assert ref_pack in packs_by_id
        assert packs_by_id[ref_pack]["license"] == "CC0-1.0"


def test_bridge_file_hygiene_zero_comments_dashes_and_network_imports() -> None:
    self_path = Path(__file__).resolve()
    src = self_path.read_text(encoding="utf-8")

    assert HASH_CHAR not in src, f"Hash character found in {self_path.name}"
    for code in UNICODE_DASH_CODES:
        assert chr(code) not in src, f"Unicode dash U+{code:04X} found in {self_path.name}"

    tokens = list(tokenize.generate_tokens(io.StringIO(src).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == [], f"Python comments found in {self_path.name}: {comments}"

    tree = ast.parse(src)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    forbidden = ("google", "genai", "atlas_gemini", "gateway", "httpx", "requests", "urllib", "socket", "aiohttp")
    for mod in imported:
        assert not any(term in mod for term in forbidden), f"Forbidden import {mod!r} in {self_path.name}"

    for js_path in (MANIFEST_JS_PATH, EVIDENCE_CARDS_JS_PATH):
        js_src = js_path.read_text(encoding="utf-8")
        for code in UNICODE_DASH_CODES:
            assert chr(code) not in js_src, f"Unicode dash U+{code:04X} found in {js_path.name}"
        assert _find_unquoted_js_comments(js_src) == [], f"JS comments found in {js_path.name}"
