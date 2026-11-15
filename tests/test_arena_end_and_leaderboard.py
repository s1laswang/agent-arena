from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import tokenize
from pathlib import Path

import pytest

from canary.env import Env

ROOT = Path(__file__).resolve().parents[1]
END_AND_LEADERBOARD_JS = ROOT / "docs" / "arena" / "ui" / "end_and_leaderboard.js"
GEMINI_HARD_EPISODES = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
)
SOLVER_HARD_0_19 = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-20261114-121126" / "episodes.jsonl"
)
SOLVER_HARD_20_29 = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "reference" / "solver-hard-seeds20to29" / "episodes.jsonl"
)
SELF_PATH = Path(__file__).resolve()

HASH_CH = chr(35)
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
UNICODE_MINUS = chr(0x2212)
SLASH_SLASH = chr(47) * 2
SLASH_STAR = chr(47) + chr(42)
STAR_SLASH = chr(42) + chr(47)


def _find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    for cand in (
        Path.home() / "tools" / "node" / "bin" / "node",
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
    ):
        if cand.is_file():
            return str(cand)
    return None


def _load_episode_by_seed(paths: list[Path], seed: int) -> dict:
    for p in paths:
        with p.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                obj = json.loads(line)
                if int(obj.get("seed", -1)) == seed:
                    return obj
    raise AssertionError(f"seed {seed} not found in {paths}")


def _run_node_module(script_body: str) -> subprocess.CompletedProcess[str]:
    node_bin = _find_node()
    assert node_bin is not None
    dom_harness = """
function makeDom() {
  function makeEl(tag) {
    const node = {
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      className: "",
      id: "",
      hidden: false,
      disabled: false,
      value: "",
      dataset: {},
      style: { cssText: "" },
      attrs: {},
      listeners: {},
      childNodes: [],
      ownerDocument: null,
      setAttribute(k, v) {
        this.attrs[k] = String(v);
        if (k === "id") this.id = String(v);
        if (k === "class") this.className = String(v);
        if (k === "hidden") this.hidden = true;
      },
      removeAttribute(k) {
        delete this.attrs[k];
        if (k === "hidden") this.hidden = false;
      },
      getAttribute(k) {
        return this.attrs[k];
      },
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
      click() {
        if (typeof this.listeners.click === "function") {
          this.listeners.click({ preventDefault() {}, stopPropagation() {} });
        }
      },
      appendChild(c) {
        this.childNodes.push(c);
        return c;
      },
      replaceChildren() {
        this.childNodes.length = 0;
      },
      get textContent() {
        return this.childNodes
          .map((c) => (c.nodeType === 3 ? c.textContent : c.textContent || ""))
          .join("");
      },
      set textContent(v) {
        this.childNodes.length = 0;
        if (v !== "" && v !== null && v !== undefined) {
          this.childNodes.push({ nodeType: 3, textContent: String(v) });
        }
      }
    };
    return node;
  }
  const doc = {
    body: {
      classList: {
        _set: new Set(),
        toggle(cls, force) {
          if (force) this._set.add(cls);
          else this._set.delete(cls);
        }
      }
    },
    createTextNode(t) {
      return { nodeType: 3, textContent: String(t) };
    },
    createElement(tag) {
      const el = makeEl(tag);
      el.ownerDocument = doc;
      return el;
    }
  };
  return { doc };
}

function walkNodes(node, out = []) {
  if (!node) return out;
  out.push(node);
  for (const child of node.childNodes || []) {
    walkNodes(child, out);
  }
  return out;
}

function findById(node, targetId) {
  return walkNodes(node).find((n) => n.id === targetId || (n.attrs && n.attrs.id === targetId)) || null;
}

function findByClass(node, clsToken) {
  return walkNodes(node).filter((n) => {
    const raw = typeof n.className === "string" ? n.className : "";
    return raw.split(" ").filter(Boolean).includes(clsToken);
  });
}

function findByTag(node, tagName) {
  const upper = String(tagName).toUpperCase();
  return walkNodes(node).filter((n) => n.tagName === upper);
}
"""
    full_script = (
        f"import * as M from {json.dumps(END_AND_LEADERBOARD_JS.as_uri())};\n"
        + dom_harness
        + "\n"
        + script_body
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", full_script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
    return proc


def test_end_and_leaderboard_hygiene_ascii_zero_comments_zero_xss() -> None:
    assert END_AND_LEADERBOARD_JS.is_file()
    src = END_AND_LEADERBOARD_JS.read_text(encoding="utf-8")
    assert len(src.strip()) > 500
    assert src.isascii()
    assert SLASH_SLASH not in src
    assert SLASH_STAR not in src
    assert STAR_SLASH not in src
    assert HASH_CH not in src
    assert EM_DASH not in src
    assert EN_DASH not in src
    assert UNICODE_MINUS not in src

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in src

    assert 'from "./dom.js"' in src
    assert 'from "./arena_app.js"' in src
    for sym in (
        "LEADERBOARD_STORAGE_KEY",
        "createLeaderboardStore",
        "renderEndSummaryCard",
        "renderLeaderboardDialog",
    ):
        assert re.search(rf"\bexport\s+(?:const|function)\s+{re.escape(sym)}\b", src), sym

    self_src = SELF_PATH.read_text(encoding="utf-8")
    assert self_src.isascii()
    assert SLASH_SLASH not in self_src
    assert SLASH_STAR not in self_src
    assert STAR_SLASH not in self_src
    assert HASH_CH not in self_src
    assert EM_DASH not in self_src
    assert EN_DASH not in self_src
    assert UNICODE_MINUS not in self_src
    tokens = list(tokenize.generate_tokens(io.StringIO(self_src).readline))
    assert [t for t in tokens if t.type == tokenize.COMMENT] == []


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_pre_end_seal_guard_blocks_all_truth_accused_score_and_commentary_leaks() -> None:
    _run_node_module(
        """
const { doc } = makeDom();
const container = doc.createElement("section");
let commentaryCalls = 0;
const spyCommentary = {
  getPostGameForensics() {
    commentaryCalls += 1;
    return { headline: "LEAKED_HEADLINE", true_mole: "e08", decoy: "e38" };
  }
};

M.renderEndSummaryCard(
  container,
  {
    humanDone: true,
    mode: "duel",
    tier: "hard",
    seed: 26,
    moleId: "e08",
    moleName: "Old Mole",
    moleDept: "Finance",
    you: { score: 0.74, correct: true, accused: "e08", final_day: 8, tool_calls: 40 },
    gemini: { score: -1.0, correct: false, accused: "e04", final_day: 10, tool_calls: 91 },
    solver: { score: 0.69, correct: true, accused: "e08", final_day: 7, tool_calls: 60 }
  },
  { document: doc }
);
if (container.hidden !== false || !container.textContent.includes("e08")) {
  process.exit(10);
}

for (const unsealed of [
  null,
  undefined,
  {
    humanDone: false,
    mode: "duel",
    tier: "hard",
    seed: 26,
    moleId: "e08",
    moleName: "Secret Mole",
    moleDept: "Research",
    you: { score: 0.88, correct: true, accused: "e08", final_day: 5, tool_calls: 22 },
    gemini: { score: -1.0, correct: false, accused: "e04", final_day: 10, tool_calls: 91 },
    solver: { score: 0.69, correct: true, accused: "e08", final_day: 7, tool_calls: 60 }
  },
  {
    mode: "duel",
    tier: "hard",
    seed: 6,
    moleId: "e34",
    you: { score: 0.73, correct: true, accused: "e34", final_day: 6 }
  }
]) {
  M.renderEndSummaryCard(container, unsealed, { document: doc, commentary: spyCommentary });
  if (container.hidden !== true) process.exit(11);
  if (container.attrs.hidden === undefined) process.exit(12);
  if (container.childNodes.length !== 0) process.exit(13);
  if (container.textContent !== "") process.exit(14);
}

if (commentaryCalls !== 0) process.exit(15);
"""
    )


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_duel_seeds_6_and_26_h2h_table_share_line_copy_and_replay_cta() -> None:
    gem_6 = _load_episode_by_seed([GEMINI_HARD_EPISODES], 6)
    gem_26 = _load_episode_by_seed([GEMINI_HARD_EPISODES], 26)
    sol_6 = _load_episode_by_seed([SOLVER_HARD_0_19, SOLVER_HARD_20_29], 6)
    sol_26 = _load_episode_by_seed([SOLVER_HARD_0_19, SOLVER_HARD_20_29], 26)

    env_6 = Env("hard", 6)
    env_26 = Env("hard", 26)
    staff_6 = {e["id"]: e for e in env_6.call("list_employees", {}).data["employees"]}
    staff_26 = {e["id"]: e for e in env_26.call("list_employees", {}).data["employees"]}

    mole_6_id = env_6._world.mole
    mole_26_id = env_26._world.mole
    assert mole_6_id == gem_6["accused"] == sol_6["accused"] == "e34"
    assert mole_26_id == sol_26["accused"] == "e08"
    assert gem_26["accused"] == "e04"

    payload_6 = {
        "humanDone": True,
        "mode": "duel",
        "tier": "hard",
        "seed": 6,
        "moleId": mole_6_id,
        "moleName": staff_6[mole_6_id]["name"],
        "moleDept": staff_6[mole_6_id]["dept"],
        "you": {
            "score": 0.78,
            "correct": True,
            "accused": mole_6_id,
            "final_day": 7,
            "tool_calls": 48,
        },
        "gemini": {
            "score": gem_6["score"],
            "correct": gem_6["correct"],
            "accused": gem_6["accused"],
            "final_day": gem_6["final_day"],
            "tool_calls": len(gem_6["steps"]),
        },
        "solver": {
            "score": sol_6["score"],
            "correct": sol_6["correct"],
            "accused": sol_6["accused"],
            "final_day": sol_6["final_day"],
            "tool_calls": len(sol_6["steps"]),
        },
    }

    payload_26 = {
        "humanDone": True,
        "mode": "duel",
        "tier": "hard",
        "seed": 26,
        "moleId": mole_26_id,
        "moleName": staff_26[mole_26_id]["name"],
        "moleDept": staff_26[mole_26_id]["dept"],
        "you": {
            "score": 0.0,
            "correct": False,
            "accused": None,
            "final_day": 21,
            "tool_calls": 110,
        },
        "gemini": {
            "score": gem_26["score"],
            "correct": gem_26["correct"],
            "accused": gem_26["accused"],
            "final_day": gem_26["final_day"],
            "tool_calls": len(gem_26["steps"]),
        },
        "solver": {
            "score": sol_26["score"],
            "correct": sol_26["correct"],
            "accused": sol_26["accused"],
            "final_day": sol_26["final_day"],
            "tool_calls": len(sol_26["steps"]),
        },
    }

    _run_node_module(
        f"""
const s6 = {json.dumps(payload_6)};
const s26 = {json.dumps(payload_26)};
const {{ doc }} = makeDom();
const card = doc.createElement("section");

let copiedLine = null;
let playedArgs = null;

M.renderEndSummaryCard(card, s6, {{
  document: doc,
  onCopy(text) {{ copiedLine = text; }},
  onPlaySeed(nextSeed, tier, mode) {{ playedArgs = [nextSeed, tier, mode]; }}
}});

if (card.hidden !== false) process.exit(20);
const txt6 = card.textContent;
if (!txt6.includes("True Mole: e34")) process.exit(21);
if (!txt6.includes(s6.moleName) || !txt6.includes(s6.moleDept)) process.exit(22);
if (!txt6.includes("First catch: Solver")) process.exit(23);
if (!txt6.includes("gemini-4-carbon (OpenCode)")) process.exit(24);
if (!txt6.includes("SolverPolicy (Bayesian)")) process.exit(25);
if (!txt6.includes("Day 06") || !txt6.includes("+0.73") || !txt6.includes("+0.71")) process.exit(26);

const share6 = findById(card, "arenaShareText");
const expectedShare6 = "CANARY ARENA | Seed 6 (hard) | You +0.78 (Day 7) vs Gemini +0.73 (Day 6) vs Solver +0.71 (Day 6) | First catch: Solver";
if (!share6 || share6.textContent !== expectedShare6) {{
  console.error("s6 share mismatch:", share6 && share6.textContent);
  process.exit(27);
}}

const copyBtn6 = findByClass(card, "copy-share-btn")[0];
const replayBtn6 = findByClass(card, "replay-seed-btn")[0];
if (!copyBtn6 || !replayBtn6) process.exit(28);
copyBtn6.click();
if (copiedLine !== expectedShare6 || copyBtn6.dataset.copied !== "true") process.exit(29);
replayBtn6.click();
if (JSON.stringify(playedArgs) !== JSON.stringify([26, "hard", "duel"])) process.exit(30);

let clipText = null;
Object.defineProperty(globalThis, "navigator", {{
  configurable: true,
  value: {{
    clipboard: {{
      writeText(val) {{
        clipText = val;
        return Promise.resolve();
      }}
    }}
  }}
}});

M.renderEndSummaryCard(card, s26, {{
  document: doc,
  onPlaySeed(nextSeed, tier, mode) {{ playedArgs = [nextSeed, tier, mode]; }}
}});

const txt26 = card.textContent;
if (!txt26.includes("True Mole: e08")) process.exit(31);
if (!txt26.includes("Wrong Accusation")) process.exit(32);
if (!txt26.includes("Caught Mole")) process.exit(33);
if (!txt26.includes("Horizon / Abstained")) process.exit(34);
if (!txt26.includes("e04")) process.exit(35);

const share26 = findById(card, "arenaShareText");
const expectedShare26 = "CANARY ARENA | Seed 26 (hard) | You 0.00 (Horizon Day 21) vs Gemini -1.00 (Fooled Day 10) vs Solver +0.69 (Day 7) | First catch: Solver";
if (!share26 || share26.textContent !== expectedShare26) {{
  console.error("s26 share mismatch:", share26 && share26.textContent);
  process.exit(36);
}}

findByClass(card, "copy-share-btn")[0].click();
if (clipText !== expectedShare26) process.exit(37);
findByClass(card, "replay-seed-btn")[0].click();
if (JSON.stringify(playedArgs) !== JSON.stringify([6, "hard", "duel"])) process.exit(38);
"""
    )


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_mole_mode_summary_rivals_and_public_seed_cta() -> None:
    _run_node_module(
        """
const { doc } = makeDom();
const card = doc.createElement("section");
let nextArgs = null;

M.renderEndSummaryCard(
  card,
  {
    humanDone: true,
    mode: "mole",
    tier: "medium",
    seed: 3000,
    moleId: "e07",
    moleName: "Dana Insider",
    moleDept: "Engineering",
    daysSurvived: 9,
    leaksLanded: 4,
    you: { score: 0.38, correct: false, accused: null, final_day: 9, tool_calls: 4 },
    solver: { score: 0.62, correct: true, accused: "e07", final_day: 10, tool_calls: 48 },
    moleRivals: {
      human: { days_survived: 9, leaks_landed: 4, solver_score: 0.62 },
      default_mole: { days_survived: 6, leaks_landed: 2, solver_score: 0.79 },
      synthesis_mole: { days_survived: 12, leaks_landed: 5, solver_score: 0.44 },
      tactical_debrief: [
        "Avoided Day 2 canary split by holding Engineering memo.",
        "Exposed on Day 9 via 2-recipient trap."
      ]
    }
  },
  {
    document: doc,
    onPlaySeed(seed, tier, mode) {
      nextArgs = [seed, tier, mode];
    }
  }
);

const txt = card.textContent;
if (txt.includes("gemini-4-carbon")) process.exit(40);
if (!txt.includes("Days survived: 9")) process.exit(41);
if (!txt.includes("Leaks landed: 4")) process.exit(42);
if (!txt.includes("default_mole") || !txt.includes("synthesis_mole")) process.exit(43);
if (!txt.includes("Avoided Day 2 canary split")) process.exit(44);

const share = findById(card, "arenaShareText");
const expectedMoleShare = "CANARY ARENA | Seed 3000 (medium, Mole) | Survived 9d (4 leaks) vs Solver +0.62";
if (!share || share.textContent !== expectedMoleShare) {
  console.error("mole share mismatch:", share && share.textContent);
  process.exit(45);
}

findByClass(card, "replay-seed-btn")[0].click();
if (!nextArgs || nextArgs[0] < 3000 || nextArgs[0] !== 3001) process.exit(46);
"""
    )


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_post_game_commentary_and_forensics_hooks_and_xss_resistance() -> None:
    _run_node_module(
        """
const { doc } = makeDom();
const card = doc.createElement("section");

const portW5Adapter = {
  getPostGameForensics(seed, opts) {
    if (!opts || opts.humanDone !== true) {
      throw new Error("must pass humanDone: true");
    }
    return {
      seed,
      tier: opts.tier,
      archetype: "Noisy Channel Trap",
      verdict_tag: "FOOLED BY S1 NOISE",
      headline: "Gemini treated 95% fingerprint channel as 100% deterministic <img src=x onerror=alert(1)>",
      story: "43 demeanour interviews delayed canary partitioning until Day 4.",
      turning_point_day: 10,
      turning_point: "Corrupted S1 readout on c6-2 triggered immediate wrong accusation of e04.",
      verbatim_quote: "Variant S1 surfaced on c6-2; accusing e04 now. <script>evil()</script>",
      transcript_quotes: [
        { day: 8, quote: "Isolating e04 with single-recipient canary T1." }
      ],
      true_mole: { id: "e08", name: "True Insider" },
      decoy: { id: "e04", name: "Framed Decoy" }
    };
  }
};

M.renderEndSummaryCard(
  card,
  {
    humanDone: true,
    mode: "duel",
    tier: "hard",
    seed: 26,
    moleId: "e08",
    you: { score: 0.74, correct: true, accused: "e08", final_day: 8, tool_calls: 50 },
    gemini: { score: -1.0, correct: false, accused: "e04", final_day: 10, tool_calls: 91 },
    solver: { score: 0.69, correct: true, accused: "e08", final_day: 7, tool_calls: 60 }
  },
  { document: doc, commentary: portW5Adapter }
);

if (findByClass(card, "forensics-card").length !== 1) process.exit(50);
const txt = card.textContent;
if (!txt.includes("Post-Game Transcript Forensics")) process.exit(51);
if (!txt.includes("FOOLED BY S1 NOISE")) process.exit(52);
if (!txt.includes("Turning point (Day 10):")) process.exit(53);
if (!txt.includes("True mole: e08 (True Insider) | Decoy: e04 (Framed Decoy)")) process.exit(54);
if (!txt.includes("[D08] Isolating e04")) process.exit(55);
if (findByTag(card, "script").length !== 0) process.exit(56);
if (findByTag(card, "img").length !== 0) process.exit(57);

globalThis.CANARY_TRANSCRIPT_COMMENTARY = {
  "hard:6": {
    verdict_tag: "CALIBRATION CONTROL",
    headline: "Clean Day 6 convergence by both Gemini and SolverPolicy",
    story: "Immediate Day 1 canary splits isolated e34 by Day 6."
  }
};

M.renderEndSummaryCard(
  card,
  {
    humanDone: true,
    mode: "duel",
    tier: "hard",
    seed: 6,
    moleId: "e34",
    you: { score: 0.73, correct: true, accused: "e34", final_day: 6, tool_calls: 55 },
    gemini: { score: 0.73, correct: true, accused: "e34", final_day: 6, tool_calls: 57 },
    solver: { score: 0.71, correct: true, accused: "e34", final_day: 6, tool_calls: 52 }
  },
  { document: doc }
);

if (!card.textContent.includes("CALIBRATION CONTROL")) process.exit(58);
delete globalThis.CANARY_TRANSCRIPT_COMMENTARY;
"""
    )


@pytest.mark.skipif(_find_node() is None, reason="node runtime not found")
def test_leaderboard_store_persistence_cap_corrupt_json_best_for_seed_and_dialog() -> None:
    _run_node_module(
        """
if (M.LEADERBOARD_STORAGE_KEY !== "canary_arena_leaderboard_v1") process.exit(60);

const backingMap = new Map();
const mockStorage = {
  getItem(k) { return backingMap.has(k) ? backingMap.get(k) : null; },
  setItem(k, v) { backingMap.set(k, String(v)); },
  removeItem(k) { backingMap.delete(k); }
};

backingMap.set(M.LEADERBOARD_STORAGE_KEY, "{corrupt json!!!");
const storeCorrupt = M.createLeaderboardStore(mockStorage);
if (storeCorrupt.list().length !== 0) process.exit(61);

storeCorrupt.add({
  mode: "duel",
  tier: "hard",
  seed: 26,
  score: -1.0,
  correct: false,
  accused: "e04",
  final_day: 10,
  tool_calls: 91,
  first_catch: "Solver"
});
storeCorrupt.add({
  mode: "duel",
  tier: "hard",
  seed: 26,
  score: 0.74,
  correct: true,
  accused: "e08",
  final_day: 8,
  tool_calls: 52,
  first_catch: "Solver"
});
storeCorrupt.add({
  mode: "duel",
  tier: "hard",
  seed: 26,
  score: 0.74,
  correct: true,
  accused: "e08",
  final_day: 6,
  tool_calls: 44,
  first_catch: "You"
});
storeCorrupt.add({
  mode: "solver",
  tier: "medium",
  seed: 3000,
  score: 0.81,
  correct: true,
  accused: "e11",
  final_day: 5,
  tool_calls: 33,
  first_catch: "You"
});
storeCorrupt.add({
  mode: "mole",
  tier: "medium",
  seed: 3002,
  score: 0.45,
  correct: true,
  final_day: 14,
  first_catch: "None"
});
storeCorrupt.add({
  mode: "living",
  tier: "hard",
  seed: 6,
  score: 0.70,
  correct: true,
  accused: "e34",
  final_day: 7,
  first_catch: "Gemini"
});

const rehydrated = M.createLeaderboardStore(mockStorage);
if (rehydrated.list("all").length !== 6) process.exit(62);
if (rehydrated.list("duel").length !== 3) process.exit(63);
if (rehydrated.list("solver").length !== 1) process.exit(64);
if (rehydrated.list("mole").length !== 1) process.exit(65);
if (rehydrated.list("living").length !== 1) process.exit(66);

const best26 = rehydrated.bestForSeed("duel", "hard", 26);
if (!best26 || best26.score !== 0.74 || best26.final_day !== 6 || best26.first_catch !== "You") {
  console.error("best26 mismatch:", best26);
  process.exit(67);
}
if (rehydrated.bestForSeed("duel", "hard", 9999) !== null) process.exit(68);

const { doc } = makeDom();
const dlg = doc.createElement("dialog");
let closedCount = 0;

M.renderLeaderboardDialog(dlg, rehydrated, {
  document: doc,
  onClose() { closedCount += 1; }
});

const filterBtns = findByClass(dlg, "mode-filter-btn");
if (filterBtns.length !== 5) process.exit(69);
const modesSeen = filterBtns.map((b) => b.dataset.modeFilter);
if (JSON.stringify(modesSeen) !== JSON.stringify(["all", "duel", "solver", "mole", "living"])) {
  process.exit(70);
}

const solverBtn = filterBtns.find((b) => b.dataset.modeFilter === "solver");
solverBtn.click();
if (!dlg.textContent.includes("3000 (medium)") || dlg.textContent.includes("26 (hard)")) {
  process.exit(71);
}

findByClass(dlg, "leaderboard-close-btn")[0].click();
if (closedCount !== 1) process.exit(72);

findByClass(dlg, "leaderboard-clear-btn")[0].click();
if (rehydrated.list("all").length !== 0) process.exit(73);
if (!dlg.textContent.includes("Complete an episode to record local head-to-head scores.")) {
  process.exit(74);
}

const memOnly = M.createLeaderboardStore(null);
for (let i = 0; i < 115; i += 1) {
  memOnly.add({
    mode: "solver",
    tier: "medium",
    seed: 3000 + i,
    score: 0.5,
    correct: true,
    final_day: 7
  });
}
if (memOnly.list().length !== 100) process.exit(75);

const throwingStorage = {
  getItem() { throw new Error("SecurityError"); },
  setItem() { throw new Error("QuotaExceededError"); },
  removeItem() { throw new Error("SecurityError"); }
};
const resilient = M.createLeaderboardStore(throwingStorage);
resilient.add({ mode: "duel", tier: "hard", seed: 6, score: 0.73, correct: true, final_day: 6 });
if (resilient.list("duel").length !== 1) process.exit(76);
resilient.clear();
if (resilient.list("all").length !== 0) process.exit(77);
"""
    )
