from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GUIDED_TOUR_JS = ROOT / "docs" / "arena" / "ui" / "guided_tour.js"
DOM_JS = ROOT / "docs" / "arena" / "ui" / "dom.js"
ARENA_INDEX_JS = ROOT / "docs" / "arena" / "ui" / "index.js"
WALKTHROUGH_MD = ROOT / "docs" / "arena" / "WALKTHROUGH.md"
UI_CONTRACT_VERIFIER = ROOT / "scripts" / "verify_arena_ui_contract.py"
COMMITTED_GEMINI_HARD = (
    ROOT / "data" / "runs" / "committed" / "v1.4" / "opencode-gemini-4-carbon" / "hard" / "episodes.jsonl"
)
SELF_PATH = Path(__file__).resolve()

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
    raise AssertionError("node binary is required for guided_tour.js ESM tests")


def _run_node_esm(js_body: str) -> dict[str, Any]:
    node_bin = _find_node()
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
        if (k === "disabled") this.disabled = true;
      },
      removeAttribute(k) {
        delete this.attrs[k];
        if (k === "hidden") this.hidden = false;
        if (k === "disabled") this.disabled = false;
      },
      getAttribute(k) {
        return this.attrs[k];
      },
      addEventListener(ev, fn) {
        this.listeners[ev] = fn;
      },
      click() {
        if (this.disabled) return;
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
      getContext() {
        return {
          fillStyle: "",
          strokeStyle: "",
          lineWidth: 1,
          fillRect() {},
          strokeRect() {}
        };
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
  return doc;
}

function walk(node, out = []) {
  if (!node) return out;
  out.push(node);
  if (Array.isArray(node.childNodes)) {
    for (const ch of node.childNodes) walk(ch, out);
  }
  return out;
}

function findButtonsByDataset(root, key, val) {
  return walk(root).filter(
    (n) =>
      n &&
      n.nodeType === 1 &&
      n.tagName === "BUTTON" &&
      n.dataset &&
      String(n.dataset[key]) === String(val)
  );
}

function hasClass(node, cls) {
  if (!node || node.nodeType !== 1) return false;
  return String(node.className || "").split(/\\s+/).filter(Boolean).includes(cls);
}
"""
    script = (
        f"import * as tourMod from {json.dumps(GUIDED_TOUR_JS.as_uri())};\n"
        f"import * as domMod from {json.dumps(DOM_JS.as_uri())};\n"
        f"import * as indexMod from {json.dumps(ARENA_INDEX_JS.as_uri())};\n"
        + dom_harness
        + "\n"
        + js_body
    )
    proc = subprocess.run(
        [node_bin, "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert proc.returncode == 0, f"node failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    return json.loads(proc.stdout.strip())


def test_guided_tour_and_test_hygiene_and_ui_contract_verifier() -> None:
    for fpath in (GUIDED_TOUR_JS, SELF_PATH):
        assert fpath.is_file(), f"missing {fpath}"
        src = fpath.read_text(encoding="utf-8")
        assert len(src.strip()) > 0
        assert src.isascii(), f"non-ASCII char in {fpath.name}"
        assert EM_DASH not in src, f"em dash in {fpath.name}"
        assert EN_DASH not in src, f"en dash in {fpath.name}"
        assert UNICODE_MINUS not in src, f"unicode minus in {fpath.name}"
        assert SLASH_SLASH not in src, f"line comment in {fpath.name}"
        assert SLASH_STAR not in src, f"block comment open in {fpath.name}"
        assert STAR_SLASH not in src, f"block comment close in {fpath.name}"
        assert HASH_CH not in src, f"hash char in {fpath.name}"

    js_src = GUIDED_TOUR_JS.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js_src, f"forbidden XSS sink {sink} in guided_tour.js"
    assert re.search(r"\bdocument\s*\.\s*write\b", js_src) is None
    assert re.search(r"\be\d{2}\b", js_src) is None, "employee ID token found in guided_tour.js"

    py_src = SELF_PATH.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(py_src).readline))
    assert [t for t in tokens if t.type == tokenize.COMMENT] == []

    proc = subprocess.run(
        [sys.executable, str(UI_CONTRACT_VERIFIER), "--check", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["passed"] is True
    assert all(r["status"] == "PASS" for r in report["results"])


def test_tour_steps_match_walkthrough_four_windows_and_committed_metrics() -> None:
    wt_text = WALKTHROUGH_MD.read_text(encoding="utf-8")
    episodes: dict[int, dict[str, Any]] = {}
    with COMMITTED_GEMINI_HARD.open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("seed") in (6, 26):
                episodes[int(row["seed"])] = row
    assert set(episodes.keys()) == {6, 26}
    assert round(float(episodes[6]["score"]), 2) == 0.73
    assert len(episodes[6]["steps"]) == 57
    assert int(episodes[6]["final_day"]) == 6
    assert round(float(episodes[26]["score"]), 2) == -1.00
    assert len(episodes[26]["steps"]) == 91
    assert int(episodes[26]["final_day"]) == 10

    res = _run_node_esm(
        """
const steps = tourMod.TOUR_STEPS;
const frozenOuter = Object.isFrozen(steps);
const frozenEach = steps.every((s) => Object.isFrozen(s) && Object.isFrozen(s.seeds));
const modeIds = domMod.MODE_DEFS.map((m) => m.id);
const modeBadges = domMod.MODE_DEFS.map((m) => m.badge);
console.log(JSON.stringify({
  totalSeconds: tourMod.TOUR_TOTAL_SECONDS,
  frozenOuter,
  frozenEach,
  steps,
  modeIds,
  modeBadges,
  hasGlobal: Boolean(globalThis.CanaryGuidedTour && globalThis.CanaryGuidedTour.createGuidedTourBar === tourMod.createGuidedTourBar)
}));
"""
    )
    assert res["totalSeconds"] == 90
    assert res["frozenOuter"] is True
    assert res["frozenEach"] is True
    assert res["hasGlobal"] is True

    steps = res["steps"]
    assert len(steps) == 4
    assert [s["window"] for s in steps] == ["0:00-0:30", "0:30-0:55", "0:55-1:15", "1:15-1:30"]
    assert [s["mode"] for s in steps] == res["modeIds"] == ["duel", "solver", "mole", "living"]
    assert [s["badge"] for s in steps] == res["modeBadges"]
    assert sum(int(s["durationSec"]) for s in steps) == 90
    assert [(s["startSec"], s["endSec"]) for s in steps] == [(0, 30), (30, 55), (55, 75), (75, 90)]

    assert steps[0]["seed"] == 26
    assert steps[0]["seeds"] == [26, 6]
    assert steps[0]["tier"] == "hard"
    assert steps[0]["offByDefault"] is False
    for tok in ("+0.73", "57", "+0.71", "52", "+0.69", "60", "-1.00", "91", "post-hoc lock", "[SEALED]"):
        assert tok in (steps[0]["action"] + " " + steps[0]["fact"])

    assert steps[1]["seed"] == 3000
    assert steps[1]["tier"] == "medium"
    assert "3000-9999" in steps[1]["action"]
    assert "+0.79" in steps[1]["fact"]

    assert steps[2]["seed"] == 3000
    assert "MoleView" in steps[2]["action"]
    assert "plant_canary" in steps[2]["fact"]

    assert steps[3]["seed"] == 26
    assert steps[3]["offByDefault"] is True
    assert "v1.6" in steps[3]["title"]
    assert "Did NOT pass Gate B" in steps[3]["fact"]
    assert "a8f99c2537c91d72" in steps[3]["fact"]

    for s in steps:
        assert s["window"] in wt_text
        assert s["modeLabel"] in wt_text
        combined = f"{s['title']} {s['action']} {s['fact']}"
        assert re.search(r"\be\d{2}\b", combined) is None


def test_optional_idle_mount_proxy_api_isolation_click_path_and_xss_guard() -> None:
    res = _run_node_esm(
        """
const doc = makeDom();
const container = doc.createElement("div");
const calls = [];
const accessedProps = [];

const rawApi = {
  setMode(mode) {
    calls.push({ fn: "setMode", args: [mode] });
  },
  loadSeed(seed, tier) {
    calls.push({ fn: "loadSeed", args: [seed, tier] });
  }
};

const strictArenaProxy = new Proxy(rawApi, {
  get(target, prop) {
    const name = String(prop);
    accessedProps.push(name);
    if (name !== "setMode" && name !== "loadSeed") {
      throw new Error("Forbidden property access on arenaApi: " + name);
    }
    return target[prop];
  }
});

const tour = tourMod.createGuidedTourBar(container, strictArenaProxy, {
  document: doc,
  title: "<img src=x onerror=alert(1)><script>bad()</script>"
});

const idleState = tour.getState();
const idleCallsCount = calls.length;
const idlePropsCount = accessedProps.length;
const idleTags = walk(container).filter((n) => n.nodeType === 1).map((n) => n.tagName);
const idleText = container.textContent;

const startBtn = findButtonsByDataset(container, "tourAction", "start")[0];
startBtn.click();
const step0State = tour.getState();
const prevBtnAt0 = findButtonsByDataset(container, "tourAction", "prev")[0];
const prevDisabledAt0 = Boolean(prevBtnAt0.disabled);

const seed6Btn = findButtonsByDataset(container, "tourSeed", "6")[0];
seed6Btn.click();
const step0Seed6State = tour.getState();

findButtonsByDataset(container, "tourAction", "next")[0].click();
const step1State = tour.getState();
const rejectedJudgeSeedSolver = tour.selectSeed(900000);
const rejectedLowSeedSolver = tour.selectSeed(6);
const acceptedPublicSeedSolver = tour.selectSeed(3042);
const step1AfterSeeds = tour.getState();

findButtonsByDataset(container, "tourAction", "next")[0].click();
const step2State = tour.getState();
const rejectedJudgeSeedMole = tour.selectSeed(900007);
const rejectedHeldoutSeedMole = tour.selectSeed(800001);

findButtonsByDataset(container, "tourAction", "next")[0].click();
const step3State = tour.getState();
const nextBtnAt3 = findButtonsByDataset(container, "tourAction", "next")[0];
const nextDisabledAt3 = Boolean(nextBtnAt3.disabled);
const step3PreviewBadges = walk(container).filter((n) => hasClass(n, "preview-badge")).length;
const step3LeakAlerts = walk(container).filter((n) => hasClass(n, "leak-alert")).length;
const step3Text = container.textContent;

findButtonsByDataset(container, "tourAction", "prev")[0].click();
const backToStep2State = tour.getState();

findButtonsByDataset(container, "tourAction", "dismiss")[0].click();
const dismissedState = tour.getState();
const openBtn = findButtonsByDataset(container, "tourAction", "open")[0];
openBtn.click();
const reopenedState = tour.getState();

findButtonsByDataset(container, "tourStep", "0")[0].click();
findButtonsByDataset(container, "tourAction", "stop")[0].click();
const stoppedState = tour.getState();

tour.destroy();
const afterDestroyChildren = container.childNodes.length;

console.log(JSON.stringify({
  idleState,
  idleCallsCount,
  idlePropsCount,
  idleTags,
  idleText,
  step0State,
  prevDisabledAt0,
  step0Seed6State,
  step1State,
  rejectedJudgeSeedSolver,
  rejectedLowSeedSolver,
  acceptedPublicSeedSolver,
  step1AfterSeeds,
  step2State,
  rejectedJudgeSeedMole,
  rejectedHeldoutSeedMole,
  step3State,
  nextDisabledAt3,
  step3PreviewBadges,
  step3LeakAlerts,
  step3Text,
  backToStep2State,
  dismissedState,
  reopenedState,
  stoppedState,
  afterDestroyChildren,
  calls,
  accessedProps
}));
"""
    )

    assert res["idleState"]["active"] is False
    assert res["idleState"]["dismissed"] is False
    assert res["idleCallsCount"] == 0
    assert res["idlePropsCount"] == 0
    assert "IMG" not in res["idleTags"]
    assert "SCRIPT" not in res["idleTags"]
    assert "<img src=x onerror=alert(1)>" in res["idleText"]

    assert res["step0State"]["active"] is True
    assert res["step0State"]["window"] == "0:00-0:30"
    assert res["step0State"]["mode"] == "duel"
    assert res["step0State"]["seed"] == 26
    assert res["prevDisabledAt0"] is True
    assert res["step0Seed6State"]["seed"] == 6

    assert res["step1State"]["window"] == "0:30-0:55"
    assert res["step1State"]["mode"] == "solver"
    assert res["step1State"]["seed"] == 3000
    assert res["rejectedJudgeSeedSolver"] is False
    assert res["rejectedLowSeedSolver"] is False
    assert res["acceptedPublicSeedSolver"] is True
    assert res["step1AfterSeeds"]["seed"] == 3042

    assert res["step2State"]["window"] == "0:55-1:15"
    assert res["step2State"]["mode"] == "mole"
    assert res["step2State"]["seed"] == 3000
    assert res["rejectedJudgeSeedMole"] is False
    assert res["rejectedHeldoutSeedMole"] is False

    assert res["step3State"]["window"] == "1:15-1:30"
    assert res["step3State"]["mode"] == "living"
    assert res["step3State"]["seed"] == 26
    assert res["step3State"]["offByDefault"] is True
    assert res["nextDisabledAt3"] is True
    assert res["step3PreviewBadges"] >= 1
    assert res["step3LeakAlerts"] == 1
    assert "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B" in res["step3Text"]

    assert res["backToStep2State"]["mode"] == "mole"
    assert res["dismissedState"]["dismissed"] is True
    assert res["dismissedState"]["active"] is False
    assert res["reopenedState"]["dismissed"] is False
    assert res["stoppedState"]["active"] is False
    assert res["afterDestroyChildren"] == 0

    assert set(res["accessedProps"]) <= {"setMode", "loadSeed"}
    assert res["calls"][:3] == [
        {"fn": "setMode", "args": ["duel"]},
        {"fn": "loadSeed", "args": [26, "hard"]},
        {"fn": "loadSeed", "args": [6, "hard"]},
    ]


def test_live_integration_with_mount_arena_ui_zero_budget_and_zero_pre_end_leak() -> None:
    res = _run_node_esm(
        """
const doc = makeDom();
const appRoot = doc.createElement("div");
const tourRoot = doc.createElement("div");
let envToolCalls = 0;

const fakeGame = {
  spec_json() {
    return JSON.stringify({
      tier: "hard",
      seed: 6,
      tiers_version: "v1.4",
      instruction: "Episode lasts at most 21 days. limit of 420 calls. one of your 8 actions per day. Use at most 3 different labels. If you accuse an innocent employee, your score is -1."
    });
  },
  call_json() {
    envToolCalls += 1;
    return JSON.stringify({ ok: true, data: {}, error: "", done: false });
  },
  reveal_json() {
    return JSON.stringify({ error: "the episode is not over yet" });
  }
};

const duelPack = {
  version: "v1.4",
  default_seeds: [6, 26],
  episodes: {
    "hard:6": {
      seed: 6,
      tier: "hard",
      steps: [
        { day: 1, call_idx: 1, tool: "accuse", args: { employee: "e34" }, ok: true, summary: "Accused e34", V: 1.0, mole: "e34" }
      ],
      sealed_verdict: { accused: "e34", mole: "e34", correct: true, final_day: 6, tool_calls: 57, score: 0.73 }
    },
    "hard:26": {
      seed: 26,
      tier: "hard",
      steps: [
        { day: 1, call_idx: 1, tool: "accuse", args: { employee: "e04" }, ok: true, summary: "Accused e04", V: 1.0, mole: "e08" }
      ],
      sealed_verdict: { accused: "e04", mole: "e08", correct: false, final_day: 10, tool_calls: 91, score: -1.0 }
    }
  }
};

const moleMode = {
  startSession({ tier, seed }) {
    return {
      getPublicState() {
        return {
          mode: "mole",
          tier,
          seed,
          day: 1,
          nDays: 14,
          visibleV: 1.0,
          done: false,
          moleEmployee: { id: "assigned", name: "Insider" },
          moleCandidateDocs: [
            { doc_id: "d01", title: "Spec", day: 1, recipient_count: 8, is_canary: true, mole: "e34" }
          ],
          leaksLanded: 0,
          daysSurvived: 0
        };
      },
      stepDay() {}
    };
  }
};

const livingOffice = {
  getAvailableSeeds() { return [6, 26]; },
  getDayState(seed, day) {
    return {
      day,
      mole: "e08",
      decoy: "e04",
      rumours: [{ day: 1, from: "staff_a", to: "office", text: "Printer queue", bias_type: "anchoring", true_mole: "e08" }],
      grudges: []
    };
  }
};

const app = indexMod.mountArenaUI(appRoot, {
  document: doc,
  initialMode: "duel",
  initialSeed: 6,
  game: fakeGame,
  duelPack,
  moleMode,
  livingOffice
});

const snapshots = [];
const tour = tourMod.createGuidedTourBar(tourRoot, app, {
  document: doc,
  autoStart: true,
  onStepChange(st) {
    snapshots.push({
      tour: st,
      arena: app.getState(),
      tourText: tourRoot.textContent,
      arenaText: appRoot.textContent
    });
  }
});

tour.selectSeed(6);
tour.next();
tour.next();
tour.next();

console.log(JSON.stringify({
  envToolCalls,
  snapshots
}));
"""
    )

    assert res["envToolCalls"] == 0
    snaps = res["snapshots"]
    assert len(snaps) == 5

    expected_pairs = [
        ("duel", "hard", 26),
        ("duel", "hard", 6),
        ("solver", "medium", 3000),
        ("mole", "medium", 3000),
        ("living", "hard", 26),
    ]
    for snap, (exp_mode, exp_tier, exp_seed) in zip(snaps, expected_pairs):
        assert snap["arena"]["mode"] == exp_mode
        assert snap["arena"]["tier"] == exp_tier
        assert snap["arena"]["seed"] == exp_seed
        assert snap["arena"]["done"] is False
        assert snap["arena"]["leakingSpriteEmployee"] is None
        assert re.search(r"\be\d{2}\b", snap["tourText"]) is None
        for secret in ("e34", "e04", "e08", "is_canary"):
            assert secret not in snap["tourText"]
            assert secret not in snap["arenaText"]
