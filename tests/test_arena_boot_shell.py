from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tokenize
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML_PATH = ROOT / "docs" / "arena" / "index.html"
ARENA_BOOT_JS_PATH = ROOT / "docs" / "arena" / "arena_boot.js"
SELF_TEST_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
HTML_COMMENT_OPEN = "<" + "!--"


class _TagCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag.lower(), dict(attrs)))


def _extract_python_bridge_source(js_text: str) -> str:
    marker = "const PYTHON_BRIDGE_SOURCE = ["
    start = js_text.find(marker)
    assert start >= 0, "missing PYTHON_BRIDGE_SOURCE in arena_boot.js"
    arr_start = js_text.find("[", start)
    end_marker = '].join("\\n");'
    arr_end = js_text.find(end_marker, arr_start)
    assert arr_end > arr_start, "unterminated PYTHON_BRIDGE_SOURCE array"
    raw_arr = js_text[arr_start : arr_end + 1]
    clean_arr = re.sub(r",\s*\]", "]", raw_arr)
    lines = json.loads(clean_arr)
    assert isinstance(lines, list) and all(isinstance(x, str) for x in lines)
    return "\n".join(lines)


def test_boot_shell_files_hygiene_ascii_zero_comments_and_zero_xss_sinks() -> None:
    for path in (INDEX_HTML_PATH, ARENA_BOOT_JS_PATH):
        assert path.is_file(), f"missing expected file: {path}"
        text = path.read_text(encoding="utf-8")
        assert len(text.strip()) > 0
        assert text.isascii(), f"non-ASCII character in {path.name}"
        assert EM_DASH not in text, f"em dash in {path.name}"
        assert EN_DASH not in text, f"en dash in {path.name}"
        assert UNICODE_MINUS not in text, f"unicode minus in {path.name}"
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert sink not in text, f"forbidden XSS sink {sink} in {path.name}"

    boot_src = ARENA_BOOT_JS_PATH.read_text(encoding="utf-8")
    assert SLASH_SLASH not in boot_src, "line comment marker in arena_boot.js"
    assert SLASH_STAR not in boot_src, "block comment open in arena_boot.js"
    assert STAR_SLASH not in boot_src, "block comment close in arena_boot.js"
    assert HASH_CH not in boot_src, "hash character in arena_boot.js"
    assert re.search(r'(?:call_json|run)\s*\(\s*["\']status["\']', boot_src) is None
    assert 'from "./ui/index.js"' in boot_src
    assert "mountArenaUI" in boot_src
    assert "./assets/sprite_pack_manifest.json" in boot_src

    html_src = INDEX_HTML_PATH.read_text(encoding="utf-8")
    assert HTML_COMMENT_OPEN not in html_src, "HTML comment marker in index.html"
    assert "<!doctype html>" in html_src.lower()
    assert "Kenney" in html_src
    assert "CC0" in html_src

    parser = _TagCollector()
    parser.feed(html_src)

    css_links = [
        attrs
        for tag, attrs in parser.tags
        if tag == "link" and attrs.get("rel") == "stylesheet"
    ]
    assert any(a.get("href") == "./ui/arena.css" for a in css_links)

    arena_roots = [
        attrs for tag, attrs in parser.tags if tag == "div" and attrs.get("id") == "arenaRoot"
    ]
    assert len(arena_roots) == 1

    module_scripts = [
        attrs
        for tag, attrs in parser.tags
        if tag == "script"
        and attrs.get("type") == "module"
        and attrs.get("src") == "./arena_boot.js"
    ]
    assert len(module_scripts) == 1

    mode_buttons = [
        attrs for tag, attrs in parser.tags if tag == "button" and "data-mode" in attrs
    ]
    mode_map = {attrs["data-mode"]: attrs.get("aria-selected") for attrs in mode_buttons}
    assert mode_map == {
        "duel": "true",
        "solver": "false",
        "mole": "false",
        "living": "false",
    }


def test_self_boot_test_file_zero_comments_and_ascii() -> None:
    raw = SELF_TEST_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert EM_DASH not in raw
    assert EN_DASH not in raw
    assert UNICODE_MINUS not in raw
    assert HASH_CH not in raw
    assert SLASH_SLASH not in raw
    assert SLASH_STAR not in raw
    assert STAR_SLASH not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert comments == []


def test_python_bridge_embedded_in_arena_boot_runs_real_cpython_parity() -> None:
    boot_src = ARENA_BOOT_JS_PATH.read_text(encoding="utf-8")
    py_src = _extract_python_bridge_source(boot_src)
    ns: dict[str, Any] = {}
    exec(py_src, ns)

    validate_fn = ns["_validate_seed"]
    assert validate_fn(26, "duel") == 26
    assert validate_fn(3000, "solver") == 3000
    assert validate_fn(6, "mole") == 6

    rejected_inputs: list[tuple[Any, str]] = [
        (True, "duel"),
        (False, "duel"),
        (None, "duel"),
        (-1, "duel"),
        ("3000.0", "solver"),
        (6, "solver"),
        (55, "duel"),
        (800000, "duel"),
        (900000, "duel"),
        (900000, "solver"),
        (800005, "mole"),
    ]
    for bad_seed, mode_name in rejected_inputs:
        raised = False
        try:
            validate_fn(bad_seed, mode_name)
        except ValueError:
            raised = True
        assert raised, f"expected ValueError for seed={bad_seed!r} mode={mode_name}"

    case = ns["make_investigator_case"]("duel", "hard", 26)
    assert not hasattr(case, "env")
    actions_init = json.loads(case.actions_json())
    assert actions_init["actions"] == []

    spec = json.loads(case.spec_json())
    assert spec["tier"] == "hard"
    assert spec["seed"] == 26
    assert spec["tiers_version"] == "v1.4"
    assert len(spec["tools"]) == 13
    assert "mole" not in spec

    pre_reveal = json.loads(case.reveal_json())
    assert "error" in pre_reveal
    assert "mole" not in pre_reveal
    assert "solver" not in pre_reveal

    step_day = json.loads(case.call_json("advance_day", "{}"))
    assert step_day["ok"] is True
    assert step_day["done"] is False
    assert step_day["data"]["day"] == 2

    solver_pre = json.loads(ns["solver_day_state_json"]("hard", 26, 2, False))
    assert solver_pre["final"] is None
    assert "accused" not in solver_pre
    assert "mole" not in solver_pre
    assert solver_pre["status"] in ("hunting", "sealed_accusation")

    solver_post = json.loads(ns["solver_day_state_json"]("hard", 26, 10, True))
    assert solver_post["status"] == "unlocked"
    assert solver_post["final"]["correct"] is True
    assert solver_post["final"]["final_day"] == 7
    assert abs(float(solver_post["final"]["score"]) - 0.69) < 1e-6


def test_arena_boot_node_esm_orchestrator_four_modes_pyodide_and_pre_end_sealing() -> None:
    node_bin = shutil.which("node")
    if not node_bin:
        boot_src = ARENA_BOOT_JS_PATH.read_text(encoding="utf-8")
        assert "export function createArenaOrchestrator" in boot_src
        assert "export function validateArenaSeed" in boot_src
        return

    script = f"""
import {{
  createArenaOrchestrator,
  validateArenaSeed,
  scrubPreEndValue,
  SPRITE_PACK_MANIFEST_PATH,
}} from {json.dumps(ARENA_BOOT_JS_PATH.as_uri())};

function makeDom(searchStr = "") {{
  function makeEl(tag) {{
    const node = {{
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      className: "",
      id: "",
      hidden: false,
      disabled: false,
      value: "",
      dataset: {{}},
      style: {{ cssText: "" }},
      attrs: {{}},
      listeners: {{}},
      childNodes: [],
      ownerDocument: null,
      setAttribute(k, v) {{
        this.attrs[k] = String(v);
        if (k === "id") this.id = String(v);
        if (k === "class") this.className = String(v);
        if (k === "hidden") this.hidden = true;
      }},
      getAttribute(k) {{ return this.attrs[k]; }},
      addEventListener(ev, fn) {{ this.listeners[ev] = fn; }},
      appendChild(c) {{
        this.childNodes.push(c);
        return c;
      }},
      replaceChildren() {{
        this.childNodes.length = 0;
      }},
      getContext() {{
        return {{
          fillStyle: "",
          strokeStyle: "",
          lineWidth: 1,
          imageSmoothingEnabled: false,
          fillRect() {{}},
          strokeRect() {{}},
          clearRect() {{}},
          drawImage() {{}},
          beginPath() {{}},
          arc() {{}},
          fill() {{}},
          stroke() {{}},
          fillText() {{}},
          save() {{}},
          restore() {{}},
        }};
      }},
      get textContent() {{
        return this.childNodes
          .map((c) => (c.nodeType === 3 ? c.textContent : c.textContent || ""))
          .join("");
      }},
      set textContent(v) {{
        this.childNodes.length = 0;
        if (v !== "" && v !== null && v !== undefined) {{
          this.childNodes.push({{ nodeType: 3, textContent: String(v) }});
        }}
      }},
    }};
    return node;
  }}

  const root = makeEl("div");
  root.setAttribute("id", "arenaRoot");

  const doc = {{
    body: {{
      classList: {{
        _set: new Set(),
        toggle(cls, force) {{
          if (force) this._set.add(cls);
          else this._set.delete(cls);
        }},
      }},
    }},
    createTextNode(t) {{
      return {{ nodeType: 3, textContent: String(t) }};
    }},
    createElement(tag) {{
      const el = makeEl(tag);
      el.ownerDocument = doc;
      return el;
    }},
    getElementById(targetId) {{
      return findById(root, targetId);
    }},
  }};
  root.ownerDocument = doc;
  const globalObj = {{
    document: doc,
    location: {{ search: searchStr }},
    localStorage: null,
  }};
  return {{ doc, root, globalObj }};
}}

function findById(node, targetId) {{
  if (!node) return null;
  if (node.id === targetId || (node.attrs && node.attrs.id === targetId)) return node;
  for (const child of node.childNodes || []) {{
    const hit = findById(child, targetId);
    if (hit) return hit;
  }}
  return null;
}}

for (const bad of [800000, 900000, -1, "3000.5", true, null]) {{
  let caught = false;
  try {{ validateArenaSeed(bad, "duel"); }} catch (_) {{ caught = true; }}
  if (!caught) process.exit(2);
}}
let solverSeedCaught = false;
try {{ validateArenaSeed(26, "solver"); }} catch (_) {{ solverSeedCaught = true; }}
if (!solverSeedCaught) process.exit(3);

const scrubbed = scrubPreEndValue({{
  day: 2,
  mole: "e29",
  decoy: "e17",
  true_v: 0.85,
  is_canary: true,
  leaking_sprite_employee: "e29",
  visible_V: 0.95,
}});
if ("mole" in scrubbed || "decoy" in scrubbed || "true_v" in scrubbed || "is_canary" in scrubbed) {{
  process.exit(4);
}}

if (SPRITE_PACK_MANIFEST_PATH !== "./assets/sprite_pack_manifest.json") {{
  process.exit(5);
}}

const writtenFs = {{}};
let toolCalls = 0;
let envDone = false;

const fakeGame = {{
  spec_json() {{
    return JSON.stringify({{
      tier: "hard",
      seed: 26,
      tiers_version: "v1.4",
      instruction: "Episode lasts at most 21 days. limit of 420 calls. one of your 8 actions per day. Use at most 3 different labels. If you accuse an innocent employee, your score is -1.",
    }});
  }},
  call_json(tool, argsJson) {{
    toolCalls += 1;
    const args = JSON.parse(argsJson || "{{}}");
    if (tool === "advance_day") {{
      return JSON.stringify({{ ok: true, data: {{ day: 8, V: 0.74 }}, error: "", done: false }});
    }}
    if (tool === "accuse") {{
      envDone = true;
      return JSON.stringify({{ ok: true, data: {{ accused: args.employee }}, error: "", done: true }});
    }}
    return JSON.stringify({{ ok: true, data: {{}}, error: "", done: false }});
  }},
  reveal_json() {{
    if (!envDone) return JSON.stringify({{ error: "not over" }});
    return JSON.stringify({{
      seed: 26,
      tier: "hard",
      mole: "e29",
      you: {{ score: 0.74, accused: "e29", correct: true, final_day: 8, tool_calls: toolCalls }},
      solver: {{ score: 0.69, accused: "e29", correct: true, final_day: 7, tool_calls: 60 }},
    }});
  }},
}};

const fakePyodide = {{
  FS: {{
    mkdirTree() {{}},
    writeFile(p, content) {{ writtenFs[p] = content; }},
  }},
  runPython(code) {{
    if (String(code).includes("make_investigator_case")) return fakeGame;
    return null;
  }},
}};

const fakeFetch = async (url) => {{
  const s = String(url);
  if (s.endsWith("py/manifest.json")) {{
    return {{ ok: true, async json() {{ return {{ files: ["canary/__init__.py", "canary_game.py"] }}; }} }};
  }}
  if (s.includes("/py/")) {{
    return {{ ok: true, async text() {{ return "x = 1\\n"; }} }};
  }}
  return {{ ok: false }};
}};

const duelPack = {{
  version: "v1.4",
  default_seeds: [6, 26],
  episodes: {{
    "hard:26": {{
      seed: 26,
      tier: "hard",
      agent: "opencode:google/gemini-4-carbon",
      steps: [
        {{ day: 1, call_idx: 1, tool: "list_employees", args: {{}}, ok: true, summary: "Listed 40 staff", V: 1.0 }},
        {{ day: 1, call_idx: 2, tool: "accuse", args: {{ employee: "e17" }}, ok: true, summary: "Accused e17", V: 1.0, mole: "e29", true_v: 0.95 }},
        {{ day: 10, call_idx: 9, tool: "status", args: {{}}, ok: true, summary: "Future day step", V: 0.70 }},
      ],
      sealed_verdict: {{
        score: -1.0,
        accused: "e17",
        mole: "e29",
        mole_name: "Nora Mole",
        correct: false,
        final_day: 10,
        tool_calls: 91,
      }},
    }},
  }},
  unlockPostGameReveal(tier, seed, humanDone) {{
    if (!humanDone) return null;
    return this.episodes[`${{tier}}:${{seed}}`].sealed_verdict;
  }},
}};

let moleLeaked = null;
const moleMode = {{
  startSession({{ tier, seed }}) {{
    return {{
      getPublicState() {{
        return {{
          mode: "mole",
          tier,
          seed,
          day: 2,
          nDays: 14,
          visibleV: 0.96,
          done: false,
          mole_id: "e12",
          moleEmployee: {{ id: "e12", name: "Sam Cover", dept: "Finance", role: "Analyst" }},
          leakable_docs: [
            {{ doc_id: "doc-d2-1", title: "Q3 Finance Forecast", day: 2, recipient_count: 8, is_canary: true, true_v: 0.92 }},
          ],
          solverTelemetry: {{ day: 2, visible_V: 0.96, canaries_planted: 2, top_posterior_prob: 0.22, entropy_bits: 3.1 }},
        }};
      }},
      stepDay(act) {{
        moleLeaked = act.leakDocId;
      }},
    }};
  }},
}};

const livingPack = {{
  episodes: {{
    "hard:26": {{
      mole: "e29",
      decoy: "e17",
      rumours: [
        {{ day: 1, from: "e02", to: "e05", text: "Printer queue busy" }},
        {{ day: 9, from: "e03", to: "e04", text: "Day 9 rumour hidden on day 1" }},
      ],
      grudges: [{{ a: "e02", b: "e08", reason: "budget review" }}],
    }},
  }},
}};

const {{ doc, root, globalObj }} = makeDom("");
const orch = createArenaOrchestrator({{
  globalObject: globalObj,
  document: doc,
  importModule: async () => null,
  loadPyodide: async () => fakePyodide,
  fetch: fakeFetch,
  duelPack,
  moleMode,
  moduleOverrides: {{ livingOfficePack: {{ CANARY_LIVING_OFFICE_PACK: livingPack }} }},
}});

await orch.bootArena({{ root, document: doc, awaitPyodide: true, spriteManifest: null }});

const st0 = orch.getState();
if (st0.mode !== "duel" || st0.tier !== "hard" || st0.seed !== 26) process.exit(10);
if (st0.pyodideStatus !== "ready") process.exit(11);
if (toolCalls !== 0) process.exit(12);
if (st0.leakingSpriteEmployee !== null) process.exit(13);
if (!findById(root, "officeCanvas") || !findById(root, "assetCredits")) process.exit(14);
const pyBadge = findById(root, "pyodideStatus");
if (!pyBadge || pyBadge.textContent !== "pyodide live") process.exit(15);
if (!("/home/pyodide/canary/__init__.py" in writtenFs)) process.exit(16);

const preTxt = root.textContent;
if (!preTxt.includes("[SEALED]")) process.exit(17);
if (preTxt.includes("e17") || preTxt.includes("e29") || preTxt.includes("Future day step")) process.exit(18);

orch.callTool("advance_day", {{}});
if (orch.getState().day !== 8) process.exit(19);
if (root.textContent.includes("e29")) process.exit(20);

orch.callTool("accuse", {{ employee: "e29" }});
if (!orch.getState().done) process.exit(21);
const shareEl = findById(root, "arenaShareText");
const expectedShare = "CANARY ARENA | Seed 26 (hard) | You +0.74 (Day 8) vs Gemini -1.00 (Fooled Day 10) vs Solver +0.69 (Day 7) | First catch: Solver";
if (!shareEl || shareEl.textContent !== expectedShare) {{
  console.error("Share mismatch:", shareEl && shareEl.textContent);
  process.exit(22);
}}

orch.setMode("solver");
if (orch.getState().seed < 3000 || orch.getState().tier !== "medium") process.exit(23);

orch.setMode("mole");
if (root.textContent.includes("is_canary")) process.exit(24);
orch.stepMole("doc-d2-1");
if (moleLeaked !== "doc-d2-1") process.exit(25);

orch.setMode("living");
const livTxt = root.textContent;
if (!livTxt.includes("Did NOT pass Gate B")) process.exit(26);
if (livTxt.includes("e29") || livTxt.includes("e17") || livTxt.includes("Day 9 rumour hidden")) process.exit(27);

const urlEnv = makeDom("?mode=solver&seed=3042");
const urlOrch = createArenaOrchestrator({{
  globalObject: urlEnv.globalObj,
  document: urlEnv.doc,
  importModule: async () => null,
}});
await urlOrch.bootArena({{ root: urlEnv.root, document: urlEnv.doc, spriteManifest: null }});
if (urlOrch.getState().mode !== "solver" || urlOrch.getState().seed !== 3042) process.exit(28);
""";

    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"
