from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

from canary.env import Env

ROOT = Path(__file__).resolve().parents[1]
AI_DUEL_PANEL_JS = ROOT / "docs" / "arena" / "ui" / "ai_duel_panel.js"
DOM_JS = ROOT / "docs" / "arena" / "ui" / "dom.js"
ARENA_CSS = ROOT / "docs" / "arena" / "ui" / "arena.css"
COMMITTED_V14_HARD = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
)
SELF_TEST_FILE = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)


def _find_node() -> str:
    found = shutil.which("node")
    if found:
        return found
    for candidate in (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if candidate.is_file():
            return str(candidate)
    raise AssertionError("node binary is required for ESM runtime tests")


def _run_node_esm(js_body: str) -> dict[str, Any]:
    node_bin = _find_node()
    dom_helper = """
const makeDoc = () => ({
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
  createElement: (tag) => {
    const attrs = {};
    const listeners = {};
    const children = [];
    const elNode = {
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      className: "",
      dataset: {},
      style: { cssText: "" },
      attrs,
      listeners,
      childNodes: children,
      ownerDocument: null,
      setAttribute(k, v) {
        attrs[k] = String(v);
        if (k === "class") this.className = String(v);
      },
      getAttribute(k) {
        return attrs[k];
      },
      removeAttribute(k) {
        delete attrs[k];
      },
      addEventListener(ev, fn) {
        listeners[ev] = fn;
      },
      appendChild(c) {
        children.push(c);
        return c;
      },
      replaceChildren() {
        children.length = 0;
      }
    };
    return elNode;
  }
});

const attachOwner = (doc) => {
  const orig = doc.createElement;
  doc.createElement = (tag) => {
    const n = orig(tag);
    n.ownerDocument = doc;
    return n;
  };
  return doc;
};

const hasClass = (node, cls) => {
  if (!node || node.nodeType !== 1) return false;
  return String(node.className || "").split(/\\s+/).filter(Boolean).includes(cls);
};

const walk = (node, acc = []) => {
  if (!node) return acc;
  acc.push(node);
  if (Array.isArray(node.childNodes)) {
    for (const c of node.childNodes) walk(c, acc);
  }
  return acc;
};

const findByClass = (root, cls) => walk(root).filter((n) => hasClass(n, cls));

const textOf = (node) => {
  if (!node) return "";
  if (node.nodeType === 3) return String(node.textContent || "");
  return (node.childNodes || []).map(textOf).join("");
};
"""
    full_script = (
        f"import * as panelMod from {json.dumps(AI_DUEL_PANEL_JS.as_uri())};\n"
        f"import * as domMod from {json.dumps(DOM_JS.as_uri())};\n"
        + dom_helper
        + "\n"
        + js_body
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", full_script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"node failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    return json.loads(proc.stdout.strip())


def test_ai_duel_panel_and_test_file_hygiene_and_xss_safety() -> None:
    for target in (AI_DUEL_PANEL_JS, SELF_TEST_FILE):
        assert target.is_file(), f"missing file: {target}"
        src = target.read_text(encoding="utf-8")
        assert len(src.strip()) > 0
        assert src.isascii(), f"non-ASCII char in {target.name}"
        assert EM_DASH not in src, f"em dash in {target.name}"
        assert EN_DASH not in src, f"en dash in {target.name}"
        assert UNICODE_MINUS not in src, f"unicode minus in {target.name}"
        assert SLASH_SLASH not in src, f"line comment in {target.name}"
        assert SLASH_STAR not in src, f"block comment start in {target.name}"
        assert STAR_SLASH not in src, f"block comment end in {target.name}"
        assert HASH_CH not in src, f"hash char in {target.name}"

    js_src = AI_DUEL_PANEL_JS.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js_src, f"forbidden XSS sink {sink} in ai_duel_panel.js"

    py_src = SELF_TEST_FILE.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(py_src).readline))
    assert [tok for tok in tokens if tok.type == tokenize.COMMENT] == []


def test_ai_duel_panel_exports_and_css_selector_alignment() -> None:
    js_src = AI_DUEL_PANEL_JS.read_text(encoding="utf-8")
    assert re.search(
        r'import\s*\{\s*el\s*,\s*clear\s*,\s*pad2\s*,\s*fmtScore\s*\}\s*from\s*"\./dom\.js"',
        js_src,
    )
    for fn_name in (
        "sanitizeGeminiView",
        "sanitizeSolverView",
        "sanitizeLivingView",
        "createAiDuelPanel",
    ):
        assert re.search(rf"export\s+function\s+{re.escape(fn_name)}\s*\(", js_src)

    css_src = ARENA_CSS.read_text(encoding="utf-8")
    for selector in (
        ".pane-ai",
        ".ai-card.gemini-pane",
        ".ai-card.solver-pane",
        ".sync-lock-badge",
        ".step-feed",
        ".step-item",
        ".suspect-pool-bar",
        ".suspect-pool-fill",
        ".social-drawer",
        ".preview-badge",
        ".grudge-pill",
        ".rumour-item",
        ".leak-alert",
    ):
        assert selector in css_src, f"missing CSS selector {selector}"


def test_sanitize_gemini_solver_and_living_views_pre_and_post_end() -> None:
    res = _run_node_esm(
        """
const rawGeminiEngineSealed = {
  seed: 6,
  tier: "hard",
  agent: "opencode:google/gemini-4-carbon",
  mole: "e34",
  true_mole: "e34",
  decoy: "e20",
  correct: true,
  true_v: 0.73,
  score: 0.73,
  steps: [
    { day: 1, call_idx: 1, tool: "list_employees", args: {}, ok: true, summary: "40 staff", V: 1.0, mole: "e34" },
    { day: 2, call_idx: 5, tool: "advance_day", args: {}, ok: true, summary: "Day 2", known_v: 0.98, V: 0.93, true_v: 0.93 },
    { day: 6, call_idx: 57, tool: "accuse", args: { employee: "e34", mole: "e34" }, ok: true, summary: "Accused e34 (+0.73)", V: 0.73, correct: true, score: 0.73 },
    { day: 8, call_idx: 60, tool: "status", args: {}, ok: true, summary: "Future day", V: 0.70 }
  ],
  final: { sealed: true, final_day: 6 },
  sealed_verdict: { accused: "e34", correct: true, final_day: 6, tool_calls: 57, score: 0.73 }
};

const gemDay2 = panelMod.sanitizeGeminiView(rawGeminiEngineSealed, 2, false);
const gemDay6 = panelMod.sanitizeGeminiView(rawGeminiEngineSealed, 6, false);
const gemUnlocked = panelMod.sanitizeGeminiView(rawGeminiEngineSealed, 6, true);

const rawSolver = {
  day: 7,
  visible_V: 0.84,
  known_v: 0.88,
  true_v: 0.79,
  canaries_planted: 3,
  interviews_done: 5,
  restricted_count: 2,
  tool_calls_so_far: 31,
  top_posterior_prob: 0.94,
  entropy_bits: 0.41,
  top_suspect: "e34",
  restricted_ids: ["e20", "e34"],
  mole: "e34",
  accused: "e34",
  correct: true,
  final_day: 5,
  score: 0.83
};

const solDay3 = panelMod.sanitizeSolverView(rawSolver, 3, false);
const solDay5 = panelMod.sanitizeSolverView(rawSolver, 5, false);
const solUnlocked = panelMod.sanitizeSolverView(rawSolver, 5, true);

const rawLiving = {
  banner: "custom incomplete banner",
  mole: "e34",
  decoy: "e20",
  grudges: [
    { a: "e18", a_name: "Teemu", b: "e00", b_name: "Janne", reason: "Skipped review", since_day: 2, mole: "e34", decoy: "e20" },
    { a: "e03", a_name: "Kalle", b: "e09", b_name: "Sari", reason: "Future clash", since_day: 6, true_mole: "e34" }
  ],
  rumours: [
    { id: "r1", day: 2, from: "e04", to: "e29", text: "Early chatter", bias_type: "anchoring", mole: "e34", is_canary: true },
    { id: "r2", day: 5, from: "e11", to: "e12", text: "Future rumour", bias_type: "grudge", decoy: "e20" }
  ],
  chat_feed: [
    { id: "r1", day: 2, from: "e04", to: "e29", text: "Early chatter" },
    { id: "c3", day: 3, from: "e07", to: "office", text: "Day 3 note", true_v: 0.80 }
  ]
};

const livDay3 = panelMod.sanitizeLivingView(rawLiving, 3, false);

console.log(JSON.stringify({
  gemDay2,
  gemDay6,
  gemUnlocked,
  solDay3,
  solDay5,
  solUnlocked,
  livDay3
}));
"""
    )

    gem2 = res["gemDay2"]
    assert gem2["status"] == "hunting"
    assert gem2["sealed_day"] is None
    assert gem2["final"] is None
    assert [s["day"] for s in gem2["steps"]] == [1, 2]
    assert gem2["steps"][1]["V"] == 0.98
    assert "e34" not in json.dumps(gem2)

    gem6 = res["gemDay6"]
    assert gem6["status"] == "sealed_accusation"
    assert gem6["sealed_day"] == 6
    assert gem6["final"] is None
    assert [s["day"] for s in gem6["steps"]] == [1, 2, 6]
    accuse_step = gem6["steps"][2]
    assert accuse_step["sealed"] is True
    assert accuse_step["args"] == {"employee": "[SEALED]"}
    assert accuse_step["summary"] == "[SEALED]"
    assert "e34" not in json.dumps(gem6)
    assert "0.73" not in json.dumps(accuse_step["summary"])

    gem_done = res["gemUnlocked"]
    assert gem_done["status"] == "unlocked"
    assert gem_done["final"] == {
        "accused": "e34",
        "correct": True,
        "final_day": 6,
        "tool_calls": 57,
        "score": 0.73,
    }

    sol3 = res["solDay3"]
    assert sol3["day"] == 3
    assert sol3["visible_V"] == 0.88
    assert sol3["status"] == "hunting"
    assert sol3["sealed_day"] is None
    assert sol3["final"] is None
    assert re.search(r"\be\d{2}\b", json.dumps(sol3)) is None
    for forbidden_key in ("accused", "correct", "score", "mole", "true_v", "top_suspect", "restricted_ids"):
        assert forbidden_key not in sol3

    sol5 = res["solDay5"]
    assert sol5["status"] == "sealed_accusation"
    assert sol5["sealed_day"] == 5
    assert sol5["final"] is None
    assert re.search(r"\be\d{2}\b", json.dumps(sol5)) is None

    sol_done = res["solUnlocked"]
    assert sol_done["status"] == "unlocked"
    assert sol_done["final"] == {
        "accused": "e34",
        "correct": True,
        "final_day": 5,
        "tool_calls": 31,
        "score": 0.83,
    }

    liv3 = res["livDay3"]
    assert (
        liv3["banner"]
        == "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift"
    )
    assert liv3["preview_badge"] == "OFF-BY-DEFAULT V1.6 PREVIEW"
    assert len(liv3["grudges"]) == 1
    assert len(liv3["rumours"]) == 1
    assert len(liv3["chat_feed"]) == 2
    liv_dump = json.dumps(liv3)
    for leak_key in ("mole", "true_mole", "decoy", "is_canary", "true_v"):
        assert f'"{leak_key}"' not in liv_dump


def test_create_ai_duel_panel_four_modes_optional_tiebreak_and_xss_guard() -> None:
    res = _run_node_esm(
        """
const doc = attachOwner(makeDoc());
const panel = panelMod.createAiDuelPanel({ document: doc });

const geminiFixture = {
  seed: 26,
  tier: "hard",
  agent: "opencode:google/gemini-4-carbon",
  steps: [
    { day: 1, call_idx: 1, tool: "list_employees", args: {}, ok: true, summary: "<img src=x onerror=alert(1)>", V: 1.0 },
    { day: 4, call_idx: 19, tool: "plant_canary", args: { doc_title: "Memo" }, ok: true, summary: "Planted can_01", V: 0.93 },
    { day: 4, call_idx: 22, tool: "accuse", args: { employee: "e04" }, ok: true, summary: "Accused e04", V: 0.93 },
    { day: 7, call_idx: 40, tool: "status", args: {}, ok: true, summary: "Day 7 status", V: 0.80 }
  ],
  final: { sealed: true, final_day: 4 },
  sealed_verdict: { accused: "e04", correct: false, final_day: 4, tool_calls: 22, score: -1.0 }
};

const solverFixture = {
  day: 4,
  visible_V: 0.93,
  canaries_planted: 2,
  interviews_done: 3,
  restricted_count: 1,
  tool_calls_so_far: 18,
  top_posterior_prob: 0.75,
  entropy_bits: 1.42,
  status: "sealed_accusation",
  sealed_day: 4,
  final: { accused: "e08", correct: true, final_day: 4, tool_calls: 18, score: 0.88 }
};

const tiebreakFixture = {
  seed: 26,
  tier: "hard",
  agent: "qwen2.5-1.5b-lora",
  steps: [
    { day: 1, call_idx: 1, tool: "status", args: {}, ok: true, summary: "Checked status", V: 1.0 },
    { day: 3, call_idx: 9, tool: "accuse", args: { employee: "e19" }, ok: true, summary: "Accused e19", V: 1.0 },
    { day: 6, call_idx: 12, tool: "status", args: {}, ok: true, summary: "Late call", V: 0.87 }
  ],
  final: { accused: "e19", correct: false, final_day: 3, tool_calls: 9, score: -1.0 }
};

panel.update({
  mode: "duel",
  tier: "hard",
  seed: 26,
  humanDay: 4,
  humanDone: false,
  geminiView: geminiFixture,
  solverView: solverFixture
});
const duelNoTbCards = findByClass(panel.element, "ai-card").length;
const duelPreText = textOf(panel.element);
const duelCurrentItems = findByClass(panel.element, "current").length;
const duelLockedBadges = findByClass(panel.element, "locked").length;
const allElementTags = walk(panel.element).filter((n) => n.nodeType === 1).map((n) => n.tagName);

panel.update({
  mode: "duel",
  tier: "hard",
  seed: 26,
  humanDay: 4,
  humanDone: false,
  geminiView: geminiFixture,
  solverView: solverFixture,
  tiebreakView: tiebreakFixture
});
const duelWithTbCards = findByClass(panel.element, "ai-card").length;
const duelWithTbText = textOf(panel.element);

panel.update({
  mode: "duel",
  tier: "hard",
  seed: 26,
  humanDay: 4,
  humanDone: true,
  geminiView: geminiFixture,
  solverView: solverFixture,
  tiebreakView: tiebreakFixture
});
const duelPostText = textOf(panel.element);
const duelPostLockedBadges = findByClass(panel.element, "locked").length;

panel.update({
  mode: "solver",
  tier: "medium",
  seed: 3000,
  humanDay: 3,
  humanDone: false,
  solverView: solverFixture
});
const solverModeCards = findByClass(panel.element, "ai-card").length;
const solverModeGemini = findByClass(panel.element, "gemini-pane").length;
const solverModePoolBars = findByClass(panel.element, "suspect-pool-bar").length;
const solverModePreText = textOf(panel.element);

panel.update({
  mode: "mole",
  tier: "hard",
  seed: 6,
  humanDay: 2,
  humanDone: false,
  solverView: solverFixture
});
const moleModeCards = findByClass(panel.element, "ai-card").length;

panel.update({
  mode: "living",
  tier: "hard",
  seed: 6,
  humanDay: 2,
  humanDone: false,
  solverView: solverFixture,
  livingView: {
    grudges: [
      { a_name: "Teemu", b_name: "Janne", reason: "Doc skip", since_day: 1, mole: "e08" },
      { a_name: "FutureA", b_name: "FutureB", reason: "Day 5", since_day: 5 }
    ],
    rumours: [
      { id: "m1", day: 2, from_name: "Kalle", to_name: "Noora", text: "Odd timing", bias_type: "anchoring", true_mole: "e08" },
      { id: "m9", day: 6, from_name: "Late", to_name: "Office", text: "Day 6", bias_type: "grudge" }
    ]
  }
});
const livingDrawers = findByClass(panel.element, "social-drawer").length;
const livingBadges = findByClass(panel.element, "preview-badge").length;
const livingGrudgePills = findByClass(panel.element, "grudge-pill").length;
const livingRumourItems = findByClass(panel.element, "rumour-item").length;
const livingText = textOf(panel.element);

console.log(JSON.stringify({
  duelNoTbCards,
  duelPreText,
  duelCurrentItems,
  duelLockedBadges,
  allElementTags,
  duelWithTbCards,
  duelWithTbText,
  duelPostText,
  duelPostLockedBadges,
  solverModeCards,
  solverModeGemini,
  solverModePoolBars,
  solverModePreText,
  moleModeCards,
  livingDrawers,
  livingBadges,
  livingGrudgePills,
  livingRumourItems,
  livingText
}));
"""
    )

    assert res["duelNoTbCards"] == 2
    assert "gemini-4-carbon (OpenCode MCP)" in res["duelPreText"]
    assert "SYNCED TO DAY 04" in res["duelPreText"]
    assert "[SEALED]" in res["duelPreText"]
    assert "Day 7 status" not in res["duelPreText"]
    assert "e04" not in res["duelPreText"]
    assert "e08" not in res["duelPreText"]
    assert "<img src=x onerror=alert(1)>" in res["duelPreText"]
    assert "IMG" not in res["allElementTags"]
    assert res["duelCurrentItems"] >= 1
    assert res["duelLockedBadges"] == 2

    assert res["duelWithTbCards"] == 3
    assert "Small Model Tiebreak: Qwen2.5-1.5B LoRA (bar not met)" in res["duelWithTbText"]
    assert "e19" not in res["duelWithTbText"]
    assert "Late call" not in res["duelWithTbText"]

    assert res["duelPostLockedBadges"] == 0
    assert "e04" in res["duelPostText"]
    assert "-1.00" in res["duelPostText"]
    assert "e08" in res["duelPostText"]
    assert "+0.88" in res["duelPostText"]
    assert "e19" in res["duelPostText"]

    assert res["solverModeCards"] == 1
    assert res["solverModeGemini"] == 0
    assert res["solverModePoolBars"] == 1
    assert re.search(r"\be\d{2}\b", res["solverModePreText"]) is None

    assert res["moleModeCards"] == 1

    assert res["livingDrawers"] == 1
    assert res["livingBadges"] == 1
    assert res["livingGrudgePills"] == 1
    assert res["livingRumourItems"] >= 2
    assert (
        "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift"
        in res["livingText"]
    )
    assert "FutureA" not in res["livingText"]
    assert "Day 6" not in res["livingText"]
    assert "e08" not in res["livingText"]


def test_real_v14_hard_seeds_6_and_26_replay_zero_pre_end_leak() -> None:
    assert COMMITTED_V14_HARD.is_file()
    episodes_by_seed: dict[int, dict[str, Any]] = {}
    with COMMITTED_V14_HARD.open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("seed") in (6, 26):
                episodes_by_seed[int(row["seed"])] = row
    assert set(episodes_by_seed.keys()) == {6, 26}

    replayed_payloads: dict[str, Any] = {}
    for seed in (6, 26):
        ep = episodes_by_seed[seed]
        env = Env("hard", seed)
        true_mole = env._world.mole
        true_decoy = env._world.decoy
        steps: list[dict[str, Any]] = []
        current_day = 1
        current_known_v = 1.0
        for idx, entry in enumerate(ep["steps"], start=1):
            tool = entry["tool"]
            args = entry["args"]
            step_day = current_day
            reply = env.call(tool, args)
            true_v_now = float(env.V)
            if reply.ok and isinstance(reply.data, dict):
                if "V" in reply.data:
                    current_known_v = float(reply.data["V"])
                if tool == "advance_day" and "day" in reply.data:
                    current_day = int(reply.data["day"])
            steps.append(
                {
                    "day": step_day,
                    "call_idx": idx,
                    "tool": tool,
                    "args": args,
                    "ok": bool(reply.ok),
                    "summary": f"{tool} call {idx}",
                    "known_v": current_known_v,
                    "V": true_v_now,
                    "true_v": true_v_now,
                    "mole": true_mole,
                    "decoy": true_decoy,
                }
            )
        replayed_payloads[str(seed)] = {
            "seed": seed,
            "tier": "hard",
            "agent": ep.get("agent", "opencode:google/gemini-4-carbon"),
            "mole": true_mole,
            "decoy": true_decoy,
            "steps": steps,
            "final": {
                "accused": ep["accused"],
                "correct": bool(ep["correct"]),
                "final_day": int(ep["final_day"]),
                "tool_calls": len(steps),
                "score": float(ep["score"]),
            },
        }

    payload_json = json.dumps(replayed_payloads)
    res = _run_node_esm(
        f"""
const payloads = {payload_json};
const doc = attachOwner(makeDoc());
const panel = panelMod.createAiDuelPanel({{ document: doc }});

const report = {{}};
for (const seedKey of ["6", "26"]) {{
  const ep = payloads[seedKey];
  const finalDay = ep.final.final_day;
  const preDays = [];
  for (let d = 1; d <= finalDay; d += 1) {{
    const clean = panelMod.sanitizeGeminiView(ep, d, false);
    panel.update({{
      mode: "duel",
      tier: "hard",
      seed: Number(seedKey),
      humanDay: d,
      humanDone: false,
      geminiView: ep,
      solverView: {{ day: d, visible_V: 0.9, top_posterior_prob: 0.4, entropy_bits: 2.5 }}
    }});
    preDays.push({{
      day: d,
      status: clean.status,
      sealed_day: clean.sealed_day,
      final: clean.final,
      maxStepDay: clean.steps.reduce((m, s) => Math.max(m, s.day), 0),
      accuseSteps: clean.steps.filter((s) => s.tool === "accuse"),
      stepVs: clean.steps.filter((s) => s.day === d).map((s) => s.V),
      domText: textOf(panel.element)
    }});
  }}
  panel.update({{
    mode: "duel",
    tier: "hard",
    seed: Number(seedKey),
    humanDay: finalDay,
    humanDone: true,
    geminiView: ep,
    solverView: {{ day: finalDay, visible_V: 0.73, final: {{ accused: ep.mole, correct: true, final_day: 5, tool_calls: 29, score: 0.79 }} }}
  }});
  report[seedKey] = {{
    preDays,
    postDomText: textOf(panel.element),
    postState: panel.getState().gemini.final
  }};
}}
console.log(JSON.stringify(report));
"""
    )

    seed6_pre = res["6"]["preDays"]
    assert len(seed6_pre) == 6
    for entry in seed6_pre:
        assert entry["final"] is None
        assert entry["maxStepDay"] <= entry["day"]
        if entry["day"] < 6:
            assert entry["status"] == "hunting"
            assert entry["accuseSteps"] == []
        else:
            assert entry["status"] == "sealed_accusation"
            assert entry["sealed_day"] == 6
            assert len(entry["accuseSteps"]) == 1
            assert entry["accuseSteps"][0]["args"] == {"employee": "[SEALED]"}
            assert entry["accuseSteps"][0]["summary"] == "[SEALED]"
            assert "e34" not in entry["domText"]
            assert "+0.73" not in entry["domText"]

    day2_vs = seed6_pre[1]["stepVs"]
    assert 0.98 in day2_vs
    assert 0.93 not in day2_vs

    assert res["6"]["postState"] == {
        "accused": "e34",
        "correct": True,
        "final_day": 6,
        "tool_calls": 57,
        "score": 0.73,
    }
    assert "e34" in res["6"]["postDomText"]
    assert "+0.73" in res["6"]["postDomText"]

    seed26_pre = res["26"]["preDays"]
    assert len(seed26_pre) == 10
    assert seed26_pre[-1]["status"] == "sealed_accusation"
    assert seed26_pre[-1]["sealed_day"] == 10
    assert "e04" not in seed26_pre[-1]["domText"]
    assert "e08" not in seed26_pre[-1]["domText"]
    assert "-1.00" not in seed26_pre[-1]["domText"]

    assert res["26"]["postState"] == {
        "accused": "e04",
        "correct": False,
        "final_day": 10,
        "tool_calls": 91,
        "score": -1.0,
    }
    assert "e04" in res["26"]["postDomText"]
    assert "-1.00" in res["26"]["postDomText"]


def test_tiebreak_traces_global_hook_and_set_document_support() -> None:
    res = _run_node_esm(
        """
const doc = attachOwner(makeDoc());
domMod.setDocument(doc);
let recordedArgs = null;
globalThis.CANARY_TIEBREAK_TRACES = {
  getTiebreakDuelView(seed, humanDay, humanDone, tier) {
    recordedArgs = { seed, humanDay, humanDone, tier };
    return {
      seed,
      tier,
      agent: "qwen2.5-1.5b-lora",
      steps: [
        { day: 1, call_idx: 1, tool: "list_employees", args: {}, ok: true, summary: "Pulled staff", V: 1.0 },
        { day: 2, call_idx: 4, tool: "accuse", args: { employee: "e12" }, ok: true, summary: "Accused e12", V: 0.98 },
        { day: 5, call_idx: 9, tool: "status", args: {}, ok: true, summary: "Future", V: 0.83 }
      ],
      final: { sealed: !humanDone, final_day: 2 },
      sealed_verdict: { accused: "e12", correct: false, final_day: 2, tool_calls: 4, score: -1.0 }
    };
  }
};

const panel = panelMod.createAiDuelPanel();
panel.update({
  mode: "duel",
  tier: "hard",
  seed: 6,
  humanDay: 2,
  humanDone: false,
  geminiView: { seed: 6, tier: "hard", steps: [] },
  solverView: { day: 2, visible_V: 0.98 }
});
const preCards = findByClass(panel.element, "ai-card").length;
const preText = textOf(panel.element);
const preArgs = recordedArgs;

panel.update({
  mode: "duel",
  tier: "hard",
  seed: 6,
  humanDay: 2,
  humanDone: true,
  geminiView: { seed: 6, tier: "hard", steps: [], final: { accused: "e34", correct: true, final_day: 6, tool_calls: 57, score: 0.73 } },
  solverView: { day: 2, visible_V: 0.73, final: { accused: "e34", correct: true, final_day: 5, tool_calls: 29, score: 0.79 } }
});
const postText = textOf(panel.element);
const postArgs = recordedArgs;
delete globalThis.CANARY_TIEBREAK_TRACES;

console.log(JSON.stringify({ preCards, preText, preArgs, postText, postArgs }));
"""
    )

    assert res["preCards"] == 3
    assert res["preArgs"] == {"seed": 6, "humanDay": 2, "humanDone": False, "tier": "hard"}
    assert "Small Model Tiebreak: Qwen2.5-1.5B LoRA (bar not met)" in res["preText"]
    assert "[SEALED]" in res["preText"]
    assert "e12" not in res["preText"]
    assert "Future" not in res["preText"]
    assert res["postArgs"] == {"seed": 6, "humanDay": 2, "humanDone": True, "tier": "hard"}
    assert "e12" in res["postText"]
    assert "-1.00" in res["postText"]

