from __future__ import annotations

import io
import json
import shutil
import subprocess
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARENA_APP_JS = ROOT / "docs" / "arena" / "ui" / "arena_app.js"
ARENA_INDEX_JS = ROOT / "docs" / "arena" / "ui" / "index.js"
SELF_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)
HASH_SPACE = HASH_CH + " "


def test_arena_mount_files_hygiene_and_xss_safety() -> None:
    for js_file in (ARENA_APP_JS, ARENA_INDEX_JS):
        assert js_file.is_file(), f"missing {js_file}"
        src = js_file.read_text(encoding="utf-8")
        assert len(src.strip()) > 0
        assert src.isascii(), f"non-ASCII char in {js_file.name}"
        assert EM_DASH not in src
        assert EN_DASH not in src
        assert UNICODE_MINUS not in src
        assert SLASH_SLASH not in src
        assert SLASH_STAR not in src
        assert STAR_SLASH not in src
        assert HASH_SPACE not in src
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
            assert forbidden not in src, f"forbidden sink {forbidden} in {js_file.name}"


def test_self_test_file_zero_comments_and_ascii() -> None:
    raw = SELF_PATH.read_text(encoding="utf-8")
    assert raw.isascii()
    assert EM_DASH not in raw
    assert HASH_CH not in raw
    tokens = list(tokenize.generate_tokens(io.StringIO(raw).readline))
    comments = [t for t in tokens if t.type == tokenize.COMMENT]
    assert comments == []


def test_mount_arena_ui_four_modes_and_zero_leak_in_node() -> None:
    node_bin = shutil.which("node")
    if not node_bin:
        src = ARENA_APP_JS.read_text(encoding="utf-8")
        assert "export function mountArenaUI" in src
        assert "[SEALED]" in src
        assert "OFF-BY-DEFAULT v1.6 PREVIEW" in src
        return

    script = f"""
import {{ mountArenaUI, buildCanonicalShareLine }} from {json.dumps(ARENA_INDEX_JS.as_uri())};

function makeDom() {{
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
          fillRect() {{}},
          strokeRect() {{}}
        }};
      }},
      get textContent() {{
        return this.childNodes.map((c) => c.nodeType === 3 ? c.textContent : (c.textContent || "")).join("");
      }},
      set textContent(v) {{
        this.childNodes.length = 0;
        if (v !== "" && v !== null && v !== undefined) {{
          this.childNodes.push({{ nodeType: 3, textContent: String(v) }});
        }}
      }}
    }};
    return node;
  }}
  const doc = {{
    body: {{
      classList: {{
        _set: new Set(),
        toggle(cls, force) {{
          if (force) this._set.add(cls); else this._set.delete(cls);
        }}
      }}
    }},
    createTextNode(t) {{ return {{ nodeType: 3, textContent: String(t) }}; }},
    createElement(tag) {{
      const el = makeEl(tag);
      el.ownerDocument = doc;
      return el;
    }}
  }};
  const root = doc.createElement("div");
  return {{ doc, root }};
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

const {{ doc, root }} = makeDom();
let toolCalls = 0;
let envDone = false;
let envDay = 1;

const fakeGame = {{
  spec_json() {{
    return JSON.stringify({{
      tier: "hard",
      seed: 26,
      tiers_version: "v1.4",
      instruction: "Episode lasts at most 21 days. limit of 420 calls. one of your 8 actions per day. Use at most 3 different labels. If you accuse an innocent employee, your score is -1."
    }});
  }},
  call_json(tool, argsJson) {{
    toolCalls += 1;
    const args = JSON.parse(argsJson || "{{}}");
    if (tool === "advance_day") {{
      envDay = 8;
      return JSON.stringify({{ ok: true, data: {{ day: 8, V: 0.74 }}, error: "", done: false }});
    }}
    if (tool === "accuse") {{
      envDone = true;
      return JSON.stringify({{ ok: true, data: {{ accused: args.employee }}, error: "", done: true }});
    }}
    return JSON.stringify({{ ok: true, data: {{ employees: [{{ id: "e01", name: "Ada", department: "Engineering" }}] }}, error: "", done: false }});
  }},
  reveal_json() {{
    if (!envDone) return JSON.stringify({{ error: "not over" }});
    return JSON.stringify({{
      seed: 26,
      tier: "hard",
      mole: "e29",
      you: {{ score: 0.74, accused: "e29", correct: true, final_day: 8, tool_calls: toolCalls }},
      solver: {{ score: 0.69, accused: "e29", correct: true, final_day: 7, tool_calls: 61 }}
    }});
  }}
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
        {{ day: 10, call_idx: 9, tool: "status", args: {{}}, ok: true, summary: "Future day step", V: 0.70 }}
      ],
      sealed_verdict: {{
        score: -1.0,
        accused: "e17",
        mole: "e29",
        mole_name: "Nora Mole",
        correct: false,
        final_day: 10,
        tool_calls: 94
      }}
    }}
  }},
  unlockPostGameReveal(tier, seed, humanDone) {{
    if (!humanDone) return null;
    return this.episodes[`${{tier}}:${{seed}}`].sealed_verdict;
  }}
}};

const solverLive = {{
  getSolverDayState(tier, seed, humanDay, humanDone) {{
    if (!humanDone) {{
      return {{
        day: humanDay,
        visible_V: 0.85,
        canaries_planted: 2,
        interviews_done: 0,
        restricted_count: 0,
        tool_calls_so_far: 12,
        top_posterior_prob: 0.42,
        entropy_bits: 2.1,
        accused: "e29",
        final_day: 1
      }};
    }}
    return {{
      accused: "e29",
      correct: true,
      final_day: 7,
      tool_calls: 61,
      score: 0.69
    }};
  }}
}};

let moleStepped = null;
const moleMode = {{
  startSession({{ tier, seed }}) {{
    return {{
      getPublicState() {{
        return {{
          mode: "mole",
          tier,
          seed,
          day: 2,
          nDays: 21,
          visibleV: 0.95,
          done: false,
          moleEmployee: {{ id: "e12", name: "Sam Cover" }},
          moleCandidateDocs: [
            {{ doc_id: "d04", title: "Pricing Memo", day: 2, recipient_count: 14, is_canary: true, true_v: 0.9 }}
          ],
          solverTelemetry: {{ day: 2, visible_V: 0.95, canaries_planted: 3, top_posterior_prob: 0.2, entropy_bits: 3.4 }},
          leaksLanded: 1,
          daysSurvived: 1
        }};
      }},
      stepDay(act) {{
        moleStepped = act.leakDocId;
      }}
    }};
  }}
}};

const livingOffice = {{
  getBanner() {{
    return "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift";
  }},
  getAvailableSeeds() {{ return [6, 26]; }},
  getDayState(seed, humanDay) {{
    return {{
      day: humanDay,
      mole: "e29",
      decoy: "e17",
      rumours: [
        {{ day: 1, from: "e02", to: "e05", text: "Late printer job", bias_type: "availability" }},
        {{ day: 9, from: "e03", to: "e04", text: "Future rumour", bias_type: "halo" }}
      ],
      grudges: [{{ a: "e02", b: "e08", reason: "audit clash" }}]
    }};
  }}
}};

const app = mountArenaUI(root, {{
  document: doc,
  initialSeed: 26,
  game: fakeGame,
  duelPack,
  solverLive,
  moleMode,
  livingOffice
}});

if (app.getState().mode !== "duel") process.exit(10);
if (toolCalls !== 0) process.exit(11);
if (app.getState().leakingSpriteEmployee !== null) process.exit(12);
if (!findById(root, "officeCanvas")) process.exit(13);
if (!findById(root, "assetCredits")) process.exit(14);

const preEndText = root.textContent;
if (!preEndText.includes("[SEALED]")) process.exit(15);
if (preEndText.includes("e17")) process.exit(16);
if (preEndText.includes("e29")) process.exit(17);
if (preEndText.includes("Future day step")) process.exit(18);

app.runHumanTool("advance_day", {{}});
if (app.getState().day !== 8) process.exit(19);
if (root.textContent.includes("e29")) process.exit(20);

app.runHumanTool("accuse", {{ employee: "e29" }});
if (!app.getState().done) process.exit(21);
if (app.getState().leakingSpriteEmployee !== "e29") process.exit(22);

const shareNode = findById(root, "arenaShareText");
const expectedShare = "CANARY ARENA | Seed 26 (hard) | You +0.74 (Day 8) vs Gemini -1.00 (Fooled Day 10) vs Solver +0.69 (Day 7) | First catch: Solver";
if (!shareNode || shareNode.textContent !== expectedShare) {{
  console.error("Share mismatch:", shareNode && shareNode.textContent);
  process.exit(23);
}}

app.setMode("solver");
if (app.getState().seed < 3000) process.exit(24);
app.loadSeed(6);
if (app.getState().seed < 3000) process.exit(25);

app.setMode("mole");
if (root.textContent.includes("is_canary")) process.exit(26);
app.stepMole("d04");
if (moleStepped !== "d04") process.exit(27);

app.setMode("living");
const livingTxt = root.textContent;
if (!livingTxt.includes("Did NOT pass Gate B")) process.exit(28);
if (livingTxt.includes("e29") || livingTxt.includes("e17")) process.exit(29);
if (livingTxt.includes("Future rumour")) process.exit(30);

const manualShare = buildCanonicalShareLine({{
  humanDone: true,
  mode: "duel",
  seed: 26,
  tier: "hard",
  you: {{ score: 0.74, correct: true, final_day: 8 }},
  gemini: {{ score: -1.0, correct: false, accused: "e17", final_day: 10 }},
  solver: {{ score: 0.69, correct: true, final_day: 7 }}
}});
if (manualShare !== expectedShare) process.exit(31);
""";

    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"
