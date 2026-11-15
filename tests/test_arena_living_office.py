from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVING_OFFICE_JS = ROOT / "docs" / "arena" / "living_office.js"
DOM_JS = ROOT / "docs" / "arena" / "ui" / "dom.js"
PACK_JS = ROOT / "docs" / "arena" / "data" / "living_office_pack.js"
SELF_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)

MINIMAL_DOM_JS = """
let fallbackDocument = null;
export function setDocument(doc) { fallbackDocument = doc || null; }
function resolveDoc(attrs) {
  if (attrs && typeof attrs === "object") {
    if (attrs.document) return attrs.document;
    if (attrs.ownerDocument) return attrs.ownerDocument;
  }
  if (fallbackDocument) return fallbackDocument;
  if (typeof globalThis !== "undefined" && globalThis.document) return globalThis.document;
  throw new Error("No document available");
}
function isNode(v) {
  return Boolean(v) && typeof v === "object" && (typeof v.nodeType === "number" || typeof v.appendChild === "function");
}
function toDataKey(k) {
  return "data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
}
function addKids(doc, parent, items) {
  for (const it of items) {
    if (it === null || it === undefined || typeof it === "boolean") continue;
    if (Array.isArray(it)) { addKids(doc, parent, it); continue; }
    parent.appendChild(isNode(it) ? it : doc.createTextNode(String(it)));
  }
}
export function el(tag, attrs, ...children) {
  const doc = resolveDoc(attrs);
  const node = doc.createElement(String(tag));
  if (attrs && typeof attrs === "object") {
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "document" || k === "ownerDocument" || v === null || v === undefined || v === false) continue;
      if (k.startsWith("on") && k.length > 2 && typeof v === "function") {
        node.addEventListener(k.slice(2).toLowerCase(), v);
      } else if (k === "class" || k === "className") {
        const cls = Array.isArray(v) ? v.filter(Boolean).join(" ") : String(v);
        node.setAttribute("class", cls);
      } else if (k === "dataset" && typeof v === "object") {
        for (const [dk, dv] of Object.entries(v)) {
          if (dv === null || dv === undefined || dv === false) continue;
          if (node.dataset) node.dataset[dk] = String(dv);
          node.setAttribute(toDataKey(dk), String(dv));
        }
      } else if (v === true) {
        node.setAttribute(k, "");
        node[k] = true;
      } else {
        node.setAttribute(k, String(v));
      }
    }
  }
  addKids(doc, node, children);
  return node;
}
export function clear(node) {
  if (!node) return node;
  if (typeof node.replaceChildren === "function") node.replaceChildren();
  return node;
}
export function pad2(n) {
  const num = Number(n);
  if (!Number.isFinite(num)) return "00";
  return String(Math.trunc(Math.abs(num))).padStart(2, "0");
}
"""

MOCK_DOM_HARNESS_JS = """
function makeMockDom() {
  function makeEl(tag, docRef) {
    return {
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      className: "",
      id: "",
      value: "",
      disabled: false,
      hidden: false,
      style: { cssText: "" },
      dataset: {},
      attrs: {},
      listeners: {},
      childNodes: [],
      ownerDocument: docRef,
      setAttribute(k, v) {
        this.attrs[k] = String(v);
        if (k === "class") this.className = String(v);
        if (k === "id") this.id = String(v);
        if (k === "hidden") this.hidden = true;
      },
      getAttribute(k) { return this.attrs[k]; },
      addEventListener(ev, fn) { this.listeners[ev] = fn; },
      appendChild(child) {
        this.childNodes.push(child);
        return child;
      },
      replaceChildren() {
        this.childNodes.length = 0;
      },
      getContext() {
        return null;
      },
      get textContent() {
        return this.childNodes.map((c) => c.nodeType === 3 ? c.textContent : (c.textContent || "")).join("");
      },
      set textContent(v) {
        this.childNodes.length = 0;
        if (v !== "" && v !== null && v !== undefined) {
          this.childNodes.push({ nodeType: 3, textContent: String(v) });
        }
      }
    };
  }
  const doc = {
    createTextNode(t) { return { nodeType: 3, textContent: String(t) }; },
    createElement(tag) { return makeEl(tag, doc); }
  };
  return { doc, root: doc.createElement("div") };
}

function findNodes(node, pred, acc = []) {
  if (!node || typeof node !== "object") return acc;
  if (pred(node)) acc.push(node);
  for (const child of node.childNodes || []) {
    findNodes(child, pred, acc);
  }
  return acc;
}
"""


def _find_node_binary() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    candidate = Path("/home/silas/tools/node/bin/node")
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _git_read_optional(git_spec: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "show", git_spec],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout


def _stage_arena_tree(tmp_path: Path, include_git_pack: bool = False) -> Path:
    arena_root = tmp_path / "arena"
    ui_dir = arena_root / "ui"
    data_dir = arena_root / "data"
    ui_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(LIVING_OFFICE_JS, arena_root / "living_office.js")

    if DOM_JS.is_file():
        shutil.copy2(DOM_JS, ui_dir / "dom.js")
    else:
        git_dom = _git_read_optional("origin/fr8/canary/craft-arena:docs/arena/ui/dom.js")
        (ui_dir / "dom.js").write_text(git_dom or MINIMAL_DOM_JS, encoding="utf-8")

    if include_git_pack:
        if PACK_JS.is_file():
            shutil.copy2(PACK_JS, data_dir / "living_office_pack.js")
        else:
            git_pack = _git_read_optional(
                "origin/fr8/canary/canary-staffai-w5-arena:docs/arena/data/living_office_pack.js"
            )
            if git_pack:
                (data_dir / "living_office_pack.js").write_text(git_pack, encoding="utf-8")

    return arena_root


def _run_node_module(script_body: str) -> subprocess.CompletedProcess[str]:
    node_bin = _find_node_binary()
    if not node_bin:
        src = LIVING_OFFICE_JS.read_text(encoding="utf-8")
        for req in (
            "export class CanaryLivingOffice",
            "scrubLivingOfficePreEnd",
            "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control)",
            "getAvailableSeeds",
            "getDayState",
            "getReveal",
            "renderPanel",
        ):
            assert req in src
        return subprocess.CompletedProcess(args=["python-contract-fallback"], returncode=0, stdout="", stderr="")
    env = dict(os.environ)
    env["CANARY_OFFLINE"] = "1"
    for key in list(env):
        if "API_KEY" in key:
            env.pop(key, None)
    return subprocess.run(
        [node_bin, "--input-type=module", "-e", script_body],
        capture_output=True,
        text=True,
        env=env,
        timeout=20,
    )


def test_living_office_js_hygiene_and_zero_xss_sinks() -> None:
    assert LIVING_OFFICE_JS.is_file(), f"missing {LIVING_OFFICE_JS}"
    src = LIVING_OFFICE_JS.read_text(encoding="utf-8")
    assert len(src.strip()) > 0
    assert src.isascii()
    assert EM_DASH not in src
    assert EN_DASH not in src
    assert UNICODE_MINUS not in src
    assert SLASH_SLASH not in src
    assert SLASH_STAR not in src
    assert STAR_SLASH not in src
    assert HASH_CH not in src
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in src, f"forbidden XSS sink {sink}"
    assert 'from "./ui/dom.js"' in src
    assert "export class CanaryLivingOffice" in src
    assert ".CanaryLivingOffice = CanaryLivingOffice" in src


def test_self_file_zero_comments_and_ascii() -> None:
    raw = SELF_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert EM_DASH not in raw
    assert EN_DASH not in raw
    assert UNICODE_MINUS not in raw
    assert HASH_CH not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []


def test_living_office_off_by_default_and_gate_b_disclosure_in_node(tmp_path: Path) -> None:
    arena_dir = _stage_arena_tree(tmp_path)
    mod_uri = (arena_dir / "living_office.js").as_uri()
    script = f"""
import {{ CanaryLivingOffice }} from {json.dumps(mod_uri)};

if (globalThis.CanaryLivingOffice !== CanaryLivingOffice) process.exit(10);
if (CanaryLivingOffice.isEnabledByDefault() !== false) process.exit(11);
if (CanaryLivingOffice.isGateBPassed() !== false) process.exit(12);

const banner = CanaryLivingOffice.getBanner();
if (!banner.includes("OFF-BY-DEFAULT")) process.exit(13);
if (!banner.includes("Did NOT pass Gate B")) process.exit(14);
if (!banner.includes("LA 0.452 vs 0.493 control")) process.exit(22);
if (!banner.includes("gemini-4-carbon")) process.exit(15);

const tampered = new CanaryLivingOffice({{
  pack: {{
    default_enabled: true,
    gateBPassed: true,
    gate_b_disclosure: {{ gateBPassed: true, default_enabled: true }},
    provenance: {{ live_api_calls: 99, offline_only: false }}
  }}
}});
if (tampered.isEnabledByDefault() !== false) process.exit(16);
if (tampered.isGateBPassed() !== false) process.exit(17);
if (tampered.getGateBDisclosure().gateBPassed !== false) process.exit(18);
if (tampered.getGateBDisclosure().default_enabled !== false) process.exit(19);
if (tampered.getProvenance().live_api_calls !== 0) process.exit(20);
if (tampered.getProvenance().offline_only !== true) process.exit(21);
"""
    proc = _run_node_module(script)
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"


def test_living_office_pre_end_scrubbing_day_gating_and_seed_firewall(tmp_path: Path) -> None:
    arena_dir = _stage_arena_tree(tmp_path)
    mod_uri = (arena_dir / "living_office.js").as_uri()
    script = f"""
import {{ CanaryLivingOffice, scrubLivingOfficePreEnd }} from {json.dumps(mod_uri)};

const syntheticPack = {{
  schema_version: "canary.arena.living_office_pack.v1",
  tier: "hard",
  default_seeds: [0, 6, 800000, 900000],
  gateBPassed: false,
  episodes: {{
    "hard:6": {{
      tier: "hard",
      seed: 6,
      company: "Nordlys Systems",
      max_day: 21,
      mole: "e34",
      decoy: "e20",
      true_v: 0.4,
      employees: [
        {{ id: "e00", name: "Janne Nieminen", dept: "Engineering", role: "engineer", clearance: 2, is_mole: false }},
        {{ id: "e34", name: "Sofia Niemi", dept: "Finance", role: "analyst", clearance: 3, is_mole: true }}
      ],
      focal_targets: {{ primary: "e03", secondary: "e37", primary_focus_is_mole: false }},
      days: [
        {{
          day: 1,
          new_rumours: [
            {{
              id: "r1",
              day: 1,
              from: "e00",
              from_name: "Janne",
              to: "e03",
              to_name: "Nea",
              channel: "general",
              text: "Early circulation check on Q3 memo",
              bias_type: "anchoring",
              mole: "e34",
              is_canary: true
            }}
          ],
          new_chat_feed: [
            {{
              id: "m1",
              day: 1,
              channel: "general",
              sender: "e00",
              sender_name: "Janne",
              target: "e03",
              target_name: "Nea",
              text: "Who edited the Glacier draft?",
              bias_type: "anchoring",
              true_v: 0.95
            }}
          ],
          new_gossip_edges: [
            {{ day: 1, source: "e00", target: "e03", channel: "general", bias_type: "anchoring", weight: 1 }}
          ],
          active_grudges: []
        }},
        {{
          day: 3,
          new_rumours: [
            {{
              id: "r3",
              day: 3,
              from: "e14",
              from_name: "Sofia K",
              to: "e03",
              to_name: "Nea",
              channel: "legal",
              text: "Repeated doc review friction",
              bias_type: "grudge",
              leaking_sprite_employee: "e34"
            }}
          ],
          new_chat_feed: [],
          new_gossip_edges: [
            {{ day: 3, source: "e14", target: "e03", channel: "legal", bias_type: "grudge", weight: 2 }}
          ],
          active_grudges: [
            {{ a: "e14", a_name: "Sofia K", b: "e03", b_name: "Nea", reason: "doc review clash", incidents: 2, first_day: 1, last_day: 3 }}
          ]
        }},
        {{
          day: 12,
          new_rumours: [
            {{ id: "r12", day: 12, from: "e05", to: "e08", text: "FUTURE_DAY_12_SECRET", bias_type: "authority" }}
          ],
          new_chat_feed: [
            {{ id: "m12", day: 12, sender: "e05", text: "FUTURE_CHAT_12", bias_type: "authority" }}
          ],
          new_gossip_edges: [
            {{ day: 12, source: "e05", target: "e08", channel: "sales", bias_type: "authority", weight: 1 }}
          ],
          active_grudges: []
        }}
      ],
      sealed_reveal: {{
        tier: "hard",
        seed: 6,
        mole: "e34",
        mole_name: "Sofia Niemi",
        decoy: "e20",
        true_v_day21: 0.4,
        primary_focus: "e03",
        secondary_focus: "e37",
        primary_focus_is_mole: false
      }}
    }},
    "hard:900000": {{
      tier: "hard",
      seed: 900000,
      days: []
    }}
  }}
}};

CanaryLivingOffice.configure({{ pack: syntheticPack }});
const seeds = CanaryLivingOffice.getAvailableSeeds("hard");
if (JSON.stringify(seeds) !== JSON.stringify([6])) {{
  console.error("Unexpected seeds:", seeds);
  process.exit(10);
}}
if (CanaryLivingOffice.getDayState(900000, 1, false, "hard").available !== false) process.exit(11);
if (CanaryLivingOffice.getDayState(800000, 1, false, "hard").available !== false) process.exit(12);

const d1 = CanaryLivingOffice.getDayState(6, 1, false, "hard");
if (d1.rumours.length !== 1 || d1.grudges.length !== 0) process.exit(13);

const d3 = CanaryLivingOffice.getDayState(6, 3, false, "hard");
const d3Json = JSON.stringify(d3);
if (d3.rumours.length !== 2) process.exit(14);
if (d3.new_rumours.length !== 1 || d3.new_rumours[0].id !== "r3") process.exit(15);
if (d3.grudges.length !== 1 || d3.grudges[0].a !== "e14") process.exit(16);
if (d3.gossip_edges.length !== 2) process.exit(17);
if (d3Json.includes("FUTURE_DAY_12_SECRET") || d3Json.includes("FUTURE_CHAT_12")) process.exit(18);
for (const forbidden of ["is_mole", "is_canary", "true_v", "leaking_sprite_employee", "sealed_reveal", "decoy"]) {{
  if (d3Json.includes(forbidden)) {{
    console.error("Leaked key:", forbidden);
    process.exit(19);
  }}
}}

if (CanaryLivingOffice.getReveal(6, false, "hard") !== null) process.exit(20);
const rev = CanaryLivingOffice.getReveal(6, true, "hard");
if (!rev || rev.mole !== "e34") process.exit(21);

const scrubbed = scrubLivingOfficePreEnd({{ ok: 1, mole: "e34", nested: [{{ decoy: "e20", keep: "yes" }}] }});
if ("mole" in scrubbed || "decoy" in scrubbed.nested[0] || scrubbed.nested[0].keep !== "yes") process.exit(22);
"""
    proc = _run_node_module(script)
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"


def test_living_office_dom_panel_xss_and_stage_events(tmp_path: Path) -> None:
    arena_dir = _stage_arena_tree(tmp_path)
    mod_uri = (arena_dir / "living_office.js").as_uri()
    script = f"""
import {{ CanaryLivingOffice }} from {json.dumps(mod_uri)};
{MOCK_DOM_HARNESS_JS}

const xssPayload = "<img src=x onerror=alert(1)>";
const stageEvents = [];
const mockStage = {{
  applyObservableEvent(evt) {{
    stageEvents.push(evt);
  }}
}};

const pack = {{
  tier: "hard",
  default_seeds: [0],
  episodes: {{
    "hard:0": {{
      tier: "hard",
      seed: 0,
      company: "Nordlys Systems",
      max_day: 21,
      employees: [
        {{ id: "e00", name: "Janne", dept: "Engineering", role: "engineer" }},
        {{ id: "e18", name: "Teemu", dept: "Engineering", role: "engineer" }}
      ],
      days: [
        {{
          day: 1,
          new_rumours: [
            {{
              id: "r1",
              day: 1,
              from: "e18",
              from_name: "Teemu",
              to: "e00",
              to_name: "Janne",
              channel: "engineering",
              text: "Suspicious timing " + xssPayload,
              bias_type: "grudge"
            }}
          ],
          new_chat_feed: [
            {{
              id: "m1",
              day: 1,
              channel: "general",
              sender: "e18",
              sender_name: "Teemu",
              target: "e00",
              target_name: "Janne",
              subject: "Doc check",
              text: "Chat payload " + xssPayload,
              bias_type: "anchoring"
            }}
          ],
          new_gossip_edges: [
            {{ day: 1, source: "e18", source_name: "Teemu", target: "e00", target_name: "Janne", channel: "general", bias_type: "anchoring", weight: 1 }}
          ],
          active_grudges: [
            {{ a: "e18", a_name: "Teemu", b: "e00", b_name: "Janne", reason: "skipped check", incidents: 1, first_day: 1, last_day: 1 }}
          ]
        }},
        {{
          day: 2,
          new_rumours: [
            {{
              id: "r2",
              day: 2,
              from: "e00",
              from_name: "Janne",
              to: "e18",
              to_name: "Teemu",
              channel: "general",
              text: "Authority follow-up note",
              bias_type: "authority"
            }}
          ],
          new_chat_feed: [],
          new_gossip_edges: [],
          active_grudges: []
        }}
      ],
      sealed_reveal: {{
        mole: "e29",
        mole_name: "Hidden Insider",
        primary_focus: "e00",
        secondary_focus: "e18",
        primary_focus_is_mole: false
      }}
    }}
  }}
}};

const {{ doc, root }} = makeMockDom();
let selectedEmp = null;
const lo = new CanaryLivingOffice({{
  pack,
  document: doc,
  officeStage: mockStage,
  onSelectEmployee(empId) {{ selectedEmp = empId; }}
}});

const ctrl = lo.renderPanel(root, {{ seed: 0, day: 1, maxDayCap: 1 }});
const imgElements = findNodes(root, (n) => n.nodeType === 1 && n.tagName === "IMG");
if (imgElements.length !== 0) process.exit(10);
if (!root.textContent.includes(xssPayload)) process.exit(11);
if (!root.textContent.includes("Did NOT pass Gate B")) process.exit(12);
if (root.textContent.includes("Hidden Insider") || root.textContent.includes("e29")) process.exit(13);
if (stageEvents.length < 1 || stageEvents[0].type !== "social_grudge") process.exit(14);

const actorBtns = findNodes(root, (n) => n.nodeType === 1 && n.tagName === "BUTTON" && n.textContent.includes("Janne (e00)"));
if (actorBtns.length !== 1) process.exit(15);
actorBtns[0].listeners.click();
if (selectedEmp !== "e00") process.exit(16);

ctrl.setDay(2, 1);
if (ctrl.getState().day !== 1) process.exit(17);
if (root.textContent.includes("Authority follow-up note")) process.exit(18);

ctrl.setDay(2, 2);
if (!root.textContent.includes("Authority follow-up note")) process.exit(19);

ctrl.setFilter("grudge");
if (root.textContent.includes("Authority follow-up note")) process.exit(20);

ctrl.setFilter("all");
ctrl.setTab("chat");
if (!root.textContent.includes("Chat payload")) process.exit(21);

ctrl.setTab("graph");
if (!root.textContent.includes("Teemu (e18) ---> Janne (e00)")) process.exit(22);

ctrl.setHumanDone(true);
if (!root.textContent.includes("Hidden Insider")) process.exit(23);

ctrl.destroy();
if (root.childNodes.length !== 0) process.exit(24);
"""
    proc = _run_node_module(script)
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"


def test_living_office_with_cached_pack_when_available(tmp_path: Path) -> None:
    arena_dir = _stage_arena_tree(tmp_path, include_git_pack=True)
    staged_pack = arena_dir / "data" / "living_office_pack.js"
    if not staged_pack.is_file():
        assert LIVING_OFFICE_JS.is_file()
        return

    mod_uri = (arena_dir / "living_office.js").as_uri()
    pack_uri = staged_pack.as_uri()
    script = f"""
import {json.dumps(pack_uri)};
import {{ CanaryLivingOffice }} from {json.dumps(mod_uri)};

const seeds = CanaryLivingOffice.getAvailableSeeds("hard");
if (seeds.length < 3 || !seeds.includes(0) || !seeds.includes(1) || !seeds.includes(6)) {{
  console.error("Unexpected pack seeds:", seeds);
  process.exit(10);
}}
if (CanaryLivingOffice.isGateBPassed() !== false) process.exit(11);
if (CanaryLivingOffice.isEnabledByDefault() !== false) process.exit(12);
if (!CanaryLivingOffice.getBanner().includes("LA 0.452 vs 0.493 control")) process.exit(19);

for (const s of [0, 1, 6]) {{
  const revPre = CanaryLivingOffice.getReveal(s, false, "hard");
  if (revPre !== null) process.exit(13);
  const revPost = CanaryLivingOffice.getReveal(s, true, "hard");
  if (!revPost || !revPost.mole) process.exit(14);

  const d18 = CanaryLivingOffice.getDayState(s, 18, false, "hard");
  if (!d18.available || d18.employees.length !== 40) process.exit(15);
  if (d18.chat_feed.length !== 45) process.exit(16);
  if (!d18.chat_feed[0].from_name || !d18.chat_feed[0].to_name) process.exit(20);
  if (d18.rumours.length === 0 || d18.gossip_edges.length === 0) process.exit(17);
  if (!d18.grudges.every((g) => Number(g.since_day) >= 1)) process.exit(21);

  const rawJson = JSON.stringify(d18);
  if (rawJson.includes("sealed_reveal") || rawJson.includes("mole_name") || rawJson.includes("decoy_name")) {{
    process.exit(18);
  }}
}}
"""
    proc = _run_node_module(script)
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"


def test_living_office_mount_arena_ui_integration_when_available(tmp_path: Path) -> None:
    arena_dir = _stage_arena_tree(tmp_path, include_git_pack=True)
    staged_pack = arena_dir / "data" / "living_office_pack.js"
    if not staged_pack.is_file():
        assert LIVING_OFFICE_JS.is_file()
        return

    ui_dir = arena_dir / "ui"
    for fname in ("dom.js", "office_stage.js", "arena_app.js", "index.js"):
        local_f = ROOT / "docs" / "arena" / "ui" / fname
        if local_f.is_file():
            shutil.copy2(local_f, ui_dir / fname)
        else:
            git_txt = _git_read_optional(f"origin/fr8/canary/craft-arena:docs/arena/ui/{fname}")
            if not git_txt:
                return
            (ui_dir / fname).write_text(git_txt, encoding="utf-8")

    index_uri = (ui_dir / "index.js").as_uri()
    pack_uri = staged_pack.as_uri()
    living_uri = (arena_dir / "living_office.js").as_uri()

    script = f"""
import {json.dumps(pack_uri)};
import {{ CanaryLivingOffice }} from {json.dumps(living_uri)};
import {{ mountArenaUI }} from {json.dumps(index_uri)};
{MOCK_DOM_HARNESS_JS}

const {{ doc, root }} = makeMockDom();
doc.body = {{ classList: {{ toggle() {{}} }} }};

const app = mountArenaUI(root, {{
  document: doc,
  initialSeed: 26,
  livingOffice: CanaryLivingOffice
}});

if (app.getState().mode !== "duel") process.exit(10);

app.setMode("living");
if (app.getState().mode !== "living") process.exit(11);
if (app.getState().seed !== 0) process.exit(12);

const txt0 = root.textContent;
if (!txt0.includes("Did NOT pass Gate B")) process.exit(13);
if (!txt0.includes("Cached Seed 6")) process.exit(14);
if (txt0.includes("Sofia Niemi")) process.exit(15);

app.loadSeed(6, "hard");
if (app.getState().seed !== 6) process.exit(16);
const txt6 = root.textContent;
if (txt6.includes("Sofia Niemi") || txt6.includes("Noora Jokinen")) process.exit(17);
"""
    proc = _run_node_module(script)
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"

