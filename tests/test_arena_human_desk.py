from __future__ import annotations

import io
import json
import math
import re
import shutil
import subprocess
import tokenize
from pathlib import Path
from typing import Any

from canary.env import INVESTIGATIVE_TOOLS, TOPICS, Env

ROOT = Path(__file__).resolve().parents[1]
DOM_JS_PATH = ROOT / "docs" / "arena" / "ui" / "dom.js"
ARENA_CSS_PATH = ROOT / "docs" / "arena" / "ui" / "arena.css"
HUMAN_DESK_JS_PATH = ROOT / "docs" / "arena" / "ui" / "human_desk.js"
SELF_TEST_PATH = Path(__file__).resolve()

HASH = chr(35)
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
    raise AssertionError("node binary is required for ESM behavioral tests")


def _run_node_module(js_body: str) -> dict[str, Any]:
    node_bin = _find_node()
    harness = """
const makeDoc = () => ({
  createTextNode: (t) => ({ nodeType: 3, textContent: String(t) }),
  createElement: (tag) => {
    const attrs = {};
    const listeners = {};
    const children = [];
    return {
      nodeType: 1,
      tagName: String(tag).toUpperCase(),
      className: "",
      value: "",
      disabled: false,
      dataset: {},
      style: { cssText: "" },
      attrs,
      listeners,
      childNodes: children,
      setAttribute(k, v) {
        attrs[k] = String(v);
        if (k === "class") this.className = String(v);
        if (k === "disabled") this.disabled = true;
      },
      removeAttribute(k) {
        delete attrs[k];
        if (k === "disabled") this.disabled = false;
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
  }
});

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

const findByAttr = (root, key, val) =>
  walk(root).filter(
    (n) => n.nodeType === 1 && n.attrs && (val === undefined ? key in n.attrs : n.attrs[key] === String(val))
  );

const textOf = (node) => {
  if (!node) return "";
  if (node.nodeType === 3) return String(node.textContent || "");
  return (node.childNodes || []).map(textOf).join("");
};
"""
    script = (
        f"import * as deskMod from {json.dumps(HUMAN_DESK_JS_PATH.as_uri())};\n"
        f"import * as domMod from {json.dumps(DOM_JS_PATH.as_uri())};\n"
        + harness
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


def test_strict_hygiene_ascii_zero_comments_and_xss_sinks() -> None:
    for target in (HUMAN_DESK_JS_PATH, SELF_TEST_PATH):
        assert target.is_file(), f"missing file: {target}"
        raw = target.read_text(encoding="utf-8")
        assert len(raw.strip()) > 0
        assert raw.isascii(), f"non-ASCII character in {target.name}"
        assert EM_DASH not in raw, f"em dash in {target.name}"
        assert EN_DASH not in raw, f"en dash in {target.name}"
        assert UNICODE_MINUS not in raw, f"unicode minus in {target.name}"
        assert SLASH_SLASH not in raw, f"line comment marker in {target.name}"
        assert SLASH_STAR not in raw, f"block comment open marker in {target.name}"
        assert STAR_SLASH not in raw, f"block comment close marker in {target.name}"
        assert HASH not in raw, f"hash character in {target.name}"

    py_raw = SELF_TEST_PATH.read_text(encoding="utf-8")
    tokens = list(tokenize.generate_tokens(io.StringIO(py_raw).readline))
    py_comments = [tok for tok in tokens if tok.type == tokenize.COMMENT]
    assert py_comments == []

    js_raw = HUMAN_DESK_JS_PATH.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js_raw, f"forbidden DOM sink {sink} in human_desk.js"
    for net_api in ("fetch(", "XMLHttpRequest", "WebSocket"):
        assert net_api not in js_raw, f"forbidden live network call {net_api} in human_desk.js"


def test_contract_imports_exports_and_css_alignment() -> None:
    js_raw = HUMAN_DESK_JS_PATH.read_text(encoding="utf-8")
    css_raw = ARENA_CSS_PATH.read_text(encoding="utf-8")

    expected_import = (
        'import { el, clear, pad2, fmtScore, TOOL_GROUPS, TOOL_DEFS } from "./dom.js";'
    )
    assert expected_import in js_raw
    assert re.search(r"export\s+function\s+createHumanDesk\s*\(", js_raw) is not None

    required_css_classes = (
        "human-desk-grid",
        "staff-roster",
        "staff-roster-rows",
        "staff-row",
        "emp-id",
        "emp-info",
        "emp-name",
        "emp-meta",
        "mark-btns",
        "mark-btn",
        "variant-btns",
        "variant-btn",
        "canary-pill",
        "cmd-panel",
        "cmd-bar",
        "cmd-group",
        "tool-btn",
        "accuse",
        "cmd-form",
        "mole-panel",
        "leak-picker-grid",
        "leak-picker-card",
        "case-log",
        "log-entry",
        "log-entry-head",
        "log-entry-body",
        "log-raw",
        "leak-alert",
    )
    for cls in required_css_classes:
        assert cls in js_raw, f"missing class {cls} in human_desk.js"
        assert "." + cls in css_raw, f"class .{cls} not styled in arena.css"


def test_investigator_modes_roster_marks_variants_and_no_auto_run_invariant() -> None:
    result = _run_node_module(
        """
const doc = makeDoc();
const runCalls = [];
const selectedEvents = [];
const markEvents = [];

const desk = deskMod.createHumanDesk({
  document: doc,
  onRunTool: (tool, args) => runCalls.push([tool, args]),
  onSelectEmployee: (id) => selectedEvents.push(id),
  onMarkEmployee: (id, mark) => markEvents.push([id, mark]),
});

const employees = [
  { id: "e00", name: "Ada <script>alert(1)</script>", dept: "Eng", role: "Lead", clearance: 3 },
  { id: "e01", name: "Ben Carter", dept: "Ops", role: "Analyst", clearance: 2 },
  { id: "e02", name: "Cyra Diaz", dept: "Legal", role: "Counsel", clearance: 1 },
];

const modeGrids = {};
for (const mode of ["duel", "solver", "living"]) {
  desk.update({
    mode,
    day: 2,
    visibleV: 0.92,
    employees,
    restricted: ["e02"],
    canaries: [{ id: "c1", groups: { A: ["e00"], B: ["e01"] } }],
  });
  modeGrids[mode] = findByClass(desk.element, "human-desk-grid").length;
}

const rows = findByClass(desk.element, "staff-row");
rows[1].listeners.click({});

const suspectBtn0 = findByAttr(desk.element, "data-mark", "suspect")[0];
suspectBtn0.listeners.click({ stopPropagation() {} });

const clearedBtn1 = findByAttr(desk.element, "data-mark", "cleared")[1];
clearedBtn1.listeners.click({ stopPropagation() {} });

const canaryToolBtn = findByAttr(desk.element, "data-tool", "plant_canary")[0];
canaryToolBtn.listeners.click({});

const variantBtnsAfterCanary = findByClass(desk.element, "variant-btn");
variantBtnsAfterCanary[0].listeners.click({ stopPropagation() {} });
variantBtnsAfterCanary[4].listeners.click({ stopPropagation() {} });

const scriptTags = walk(desk.element).filter((n) => n.nodeType === 1 && n.tagName === "SCRIPT");
const rowsNow = findByClass(desk.element, "staff-row");
const groupNodes = findByClass(desk.element, "cmd-group");
const toolBtns = findByClass(desk.element, "tool-btn");
const accuseBtnInBar = findByAttr(desk.element, "data-tool", "accuse")[0];

console.log(JSON.stringify({
  runCallsCount: runCalls.length,
  modeGrids,
  rosterCount: findByClass(desk.element, "staff-roster").length,
  rosterRowsCount: findByClass(desk.element, "staff-roster-rows").length,
  staffRowCount: rowsNow.length,
  empIdTexts: findByClass(desk.element, "emp-id").map(textOf),
  empNameCount: findByClass(desk.element, "emp-name").length,
  empMetaTexts: findByClass(desk.element, "emp-meta").map(textOf),
  row0Suspect: hasClass(rowsNow[0], "suspect"),
  row1Cleared: hasClass(rowsNow[1], "cleared"),
  row1Selected: hasClass(rowsNow[1], "selected"),
  variantBtnCount: findByClass(desk.element, "variant-btn").length,
  restrictedRowVariantDisabled: findByClass(rowsNow[2], "variant-btn").every((b) => b.disabled === true),
  canaryPillTexts: findByClass(desk.element, "canary-pill").map(textOf),
  groupCount: groupNodes.length,
  toolBtnCount: toolBtns.length,
  toolBtnCodeCount: findByClass(desk.element, "code").length,
  toolBtnNmCount: findByClass(desk.element, "nm").length,
  toolBtnCostCount: findByClass(desk.element, "cost").length,
  accuseHasClass: hasClass(accuseBtnInBar, "accuse"),
  selectedEvents,
  markEvents,
  scriptTagsCount: scriptTags.length,
  stateSnapshot: desk.getState(),
}));
"""
    )
    assert result["runCallsCount"] == 0
    assert result["modeGrids"] == {"duel": 1, "solver": 1, "living": 1}
    assert result["rosterCount"] == 1
    assert result["rosterRowsCount"] == 1
    assert result["staffRowCount"] == 3
    assert result["empIdTexts"] == ["e00", "e01", "e02"]
    assert result["empNameCount"] == 3
    assert result["empMetaTexts"][0] == "Eng / Lead / L3"
    assert result["row0Suspect"] is True
    assert result["row1Cleared"] is True
    assert result["row1Selected"] is True
    assert result["variantBtnCount"] == 9
    assert result["restrictedRowVariantDisabled"] is True
    assert "c1:A" in result["canaryPillTexts"]
    assert "c1:B" in result["canaryPillTexts"]
    assert result["groupCount"] == 5
    assert result["toolBtnCount"] == 13
    assert result["toolBtnCodeCount"] == 13
    assert result["toolBtnNmCount"] == 13
    assert result["toolBtnCostCount"] == 13
    assert result["accuseHasClass"] is True
    assert result["selectedEvents"] == ["e01"]
    assert result["markEvents"] == [["e00", "suspect"], ["e01", "cleared"]]
    assert result["scriptTagsCount"] == 0
    assert result["stateSnapshot"]["canaryAssignment"] == {"e00": "A", "e01": "B"}


def test_all_13_tools_and_4_interview_topics_execute_validly_against_live_env() -> None:
    probe_env = Env("hard", 6)
    emps = probe_env.call("list_employees", {}).data["employees"]
    probe_env.call("advance_day", {})
    sample_msgs = probe_env.call("search_messages", {"query": "a", "day_from": 1, "day_to": 2}).data["messages"]
    assert len(sample_msgs) > 0, "expected at least one day 1 message in hard seed 6"
    valid_msg_id = sample_msgs[0]["id"]

    result = _run_node_module(
        f"""
const doc = makeDoc();
const emitted = [];
const desk = deskMod.createHumanDesk({{
  document: doc,
  onRunTool: (tool, args) => emitted.push([tool, args]),
}});

const employees = {json.dumps(emps[:6])};
const validMsgId = {json.dumps(valid_msg_id)};

desk.update({{
  mode: "duel",
  day: 2,
  nDays: 14,
  visibleV: 0.95,
  employees,
}});

const clickToolTab = (name) => {{
  const btn = findByAttr(desk.element, "data-tool", name)[0];
  btn.listeners.click({{}});
}};

const clickRun = () => {{
  const form = findByClass(desk.element, "cmd-form")[0];
  const runBtn = findByClass(form, "run")[0];
  runBtn.listeners.click({{}});
}};

clickToolTab("status");
clickRun();

clickToolTab("list_employees");
clickRun();

clickToolTab("list_documents");
clickRun();

clickToolTab("advance_day");
clickRun();

clickToolTab("read_access_logs");
clickRun();

clickToolTab("search_messages");
const qInp = findByAttr(desk.element, "name", "query")[0];
qInp.value = "a";
qInp.listeners.input({{}});
clickRun();

clickToolTab("read_message");
const idInp = findByAttr(desk.element, "name", "id")[0];
idInp.value = validMsgId;
idInp.listeners.input({{}});
clickRun();

clickToolTab("interview");
const topicSel = findByAttr(desk.element, "name", "topic")[0];
const topicOptionValues = (topicSel.childNodes || []).map((o) => o.value);
for (const t of topicOptionValues) {{
  topicSel.value = t;
  topicSel.listeners.change({{}});
  clickRun();
}}

clickToolTab("plant_canary");
const titleInp = findByAttr(desk.element, "name", "doc_title")[0];
titleInp.value = "Q3 Strategic Plan";
titleInp.listeners.input({{}});
const evenBtn = findByClass(desk.element, "even-split-btn")[0];
evenBtn.listeners.click({{}});
clickRun();

clickToolTab("check_leak_feed");
clickRun();

clickToolTab("restrict_access");
const rstSel = findByAttr(desk.element, "name", "employee")[0];
rstSel.value = "e03";
rstSel.listeners.change({{}});
clickRun();

clickToolTab("unrestrict_access");
const unrSel = findByAttr(desk.element, "name", "employee")[0];
unrSel.value = "e03";
unrSel.listeners.change({{}});
clickRun();

clickToolTab("accuse");
const accSel = findByAttr(desk.element, "name", "employee")[0];
const armInp = findByAttr(desk.element, "name", "confirm_employee")[0];
const accRunBtn = findByClass(findByClass(desk.element, "cmd-form")[0], "run")[0];
const initiallyDisabled = accRunBtn.disabled;
clickRun();
armInp.value = "e05";
armInp.listeners.input({{}});
const wrongIdDisabled = accRunBtn.disabled;
clickRun();
accSel.value = "e01";
accSel.listeners.change({{}});
armInp.value = "e01";
armInp.listeners.input({{}});
const armedDisabled = accRunBtn.disabled;
clickRun();

console.log(JSON.stringify({{
  emitted,
  topicOptionValues,
  initiallyDisabled,
  wrongIdDisabled,
  armedDisabled,
}}));
"""
    )

    assert tuple(result["topicOptionValues"]) == TOPICS
    assert result["initiallyDisabled"] is True
    assert result["wrongIdDisabled"] is True
    assert result["armedDisabled"] is False

    emitted_tools = [pair[0] for pair in result["emitted"]]
    expected_13 = {entry["name"] for entry in Env("hard", 6).tools_spec()}
    assert set(emitted_tools) == expected_13
    assert emitted_tools.count("accuse") == 1
    assert emitted_tools.count("interview") == 4

    live_env = Env("hard", 6)
    for tool_name, args_obj in result["emitted"]:
        if tool_name in INVESTIGATIVE_TOOLS and live_env.peek_status()["actions_left_today"] == 0:
            adv = live_env.call("advance_day", {})
            assert adv.ok, adv.error
        res = live_env.call(tool_name, args_obj)
        assert res.ok, f"Env rejected UI call {tool_name}({args_obj}): {res.error} {res.data}"
    assert live_env.done is True


def test_accuse_breakeven_and_ev_use_only_visible_v_never_true_v() -> None:
    result = _run_node_module(
        """
const doc = makeDoc();
const desk = deskMod.createHumanDesk({ document: doc });
desk.update({
  mode: "duel",
  done: false,
  day: 4,
  visibleV: 0.80,
  true_v: 0.25,
  trueV: 0.25,
  mole: "e04",
  certaintyPct: 75,
  selectedTool: "accuse",
  employees: [
    { id: "e00", name: "Ada", dept: "Eng", role: "SWE" },
    { id: "e04", name: "Eve", dept: "Ops", role: "SRE" },
  ],
});

const beNode = findByClass(desk.element, "accuse-breakeven")[0];
const evNode = findByClass(desk.element, "accuse-ev")[0];
const visNode = findByClass(desk.element, "accuse-visible-v")[0];

const slider = findByAttr(desk.element, "name", "certainty")[0];
slider.value = "40";
slider.listeners.input({});
const evAt40Text = textOf(evNode);
const evAt40Attr = evNode.attrs["data-ev"];

console.log(JSON.stringify({
  visText: textOf(visNode),
  beText: textOf(beNode),
  beAttr: Number(beNode.attrs["data-breakeven"]),
  evAt75Initial: deskMod.computeAccuseEV(0.75, 0.80),
  evAt40Text,
  evAt40Attr: Number(evAt40Attr),
  stateSnapshot: desk.getState(),
  fullDomText: textOf(desk.element),
}));
"""
    )
    expected_be = 1.0 / (1.0 + 0.80)
    expected_ev_75 = 0.75 * 0.80 - 0.25
    expected_ev_40 = 0.40 * 0.80 - 0.60

    assert result["visText"] == "0.80"
    assert math.isclose(result["beAttr"], expected_be, rel_tol=1e-5)
    assert result["beText"] == "55.6%"
    assert math.isclose(result["evAt75Initial"], expected_ev_75, rel_tol=1e-9)
    assert math.isclose(result["evAt40Attr"], expected_ev_40, rel_tol=1e-5)
    assert result["evAt40Text"] == "-0.28"
    assert "0.25" not in result["fullDomText"]
    for forbidden_key in ("true_v", "trueV", "mole", "is_canary", "variant"):
        assert forbidden_key not in result["stateSnapshot"]


def test_case_log_stale_err_leak_alert_and_raw_json() -> None:
    result = _run_node_module(
        """
const doc = makeDoc();
const desk = deskMod.createHumanDesk({ document: doc });
desk.update({ mode: "duel", day: 1, visibleV: 1.0 });

desk.addLogEntry({
  day: 1,
  tool: "status",
  args: {},
  ok: true,
  data: { day: 1, V: 1.0, actions_left_today: 8, tool_calls_left: 299, restricted: [], canaries_planted: [] },
  mole: "e07",
  true_v: 0.6,
});

const staleBeforeAdvance = findByClass(desk.element, "stale").length;

desk.update({ day: 2, visibleV: 0.85 });
const staleAfterAdvance = findByClass(desk.element, "stale").length;

desk.addLogEntry({
  day: 2,
  tool: "check_leak_feed",
  args: {},
  ok: true,
  data: {
    items: [
      { doc_id: "c1", title: "Board <img src=x onerror=alert(1)>", surfaced_day: 2, variant: "B" }
    ]
  }
});

desk.addLogEntry({
  day: 2,
  tool: "read_message",
  args: { id: "bad" },
  ok: false,
  error: "invalid arguments",
  data: { detail: "unknown message id" },
});

const entries = findByClass(desk.element, "log-entry");
const heads = findByClass(desk.element, "log-entry-head");
const bodies = findByClass(desk.element, "log-entry-body");
const raws = findByClass(desk.element, "log-raw").map(textOf);
const leakAlerts = findByClass(desk.element, "leak-alert").map(textOf);
const errEntries = findByClass(desk.element, "err");
const imgTags = walk(desk.element).filter((n) => n.nodeType === 1 && n.tagName === "IMG");

const countBeforeClear = desk.getState().logCount;
desk.clearLog();
const countAfterClear = desk.getState().logCount;
const entriesAfterClear = findByClass(desk.element, "log-entry").length;

console.log(JSON.stringify({
  staleBeforeAdvance,
  staleAfterAdvance,
  entryCount: entries.length,
  headCount: heads.length,
  bodyCount: bodies.length,
  raws,
  leakAlerts,
  errCount: errEntries.length,
  imgTagsCount: imgTags.length,
  countBeforeClear,
  countAfterClear,
  entriesAfterClear,
}));
"""
    )
    assert result["staleBeforeAdvance"] == 0
    assert result["staleAfterAdvance"] == 1
    assert result["entryCount"] == 3
    assert result["headCount"] == 3
    assert result["bodyCount"] == 3
    assert len(result["leakAlerts"]) == 1
    assert "c1" in result["leakAlerts"][0]
    assert "variant B" in result["leakAlerts"][0]
    assert result["errCount"] == 1
    assert result["imgTagsCount"] == 0
    for raw_str in result["raws"]:
        parsed = json.loads(raw_str)
        assert "call" in parsed and "result" in parsed
        assert "e07" not in raw_str
        assert "true_v" not in raw_str
    assert result["countBeforeClear"] == 3
    assert result["countAfterClear"] == 0
    assert result["entriesAfterClear"] == 0


def test_mole_mode_leak_picker_hold_commit_and_secret_stripping() -> None:
    result = _run_node_module(
        """
const doc = makeDoc();
const moleSteps = [];
const runCalls = [];

const desk = deskMod.createHumanDesk({
  document: doc,
  onRunTool: (t, a) => runCalls.push([t, a]),
  onMoleStep: (payload) => moleSteps.push(payload),
});

desk.update({
  mode: "mole",
  done: false,
  day: 3,
  visibleV: 0.90,
  true_v: 0.55,
  mole: "e09",
  is_canary: true,
  variant: "C",
  moleCandidateDocs: [
    {
      doc_id: "d01",
      title: "Merger Term Sheet",
      day: 2,
      recipient_count: 9,
      is_canary: false,
      variant: "A",
      mole: "e09",
      true_v: 0.55,
    },
    {
      doc_id: "d02",
      title: "Executive Compensation",
      day: 3,
      recipient_count: 4,
      is_canary: true,
      variant: "B",
      mole: "e09",
      true_v: 0.55,
    },
  ],
});

const molePanels = findByClass(desk.element, "mole-panel");
const pickerGrids = findByClass(desk.element, "leak-picker-grid");
const cards = findByClass(desk.element, "leak-picker-card");
const cardTexts = cards.map(textOf);

const commitBtnInitial = findByClass(desk.element, "mole-commit-btn")[0];
const stepsBeforeClick = moleSteps.length;
commitBtnInitial.listeners.click({});

const d02Card = findByAttr(desk.element, "data-leak-doc-id", "d02")[0];
d02Card.listeners.click({});
const stepsAfterSelectOnly = moleSteps.length;

const commitBtnAfterSelect = findByClass(desk.element, "mole-commit-btn")[0];
commitBtnAfterSelect.listeners.click({});

const holdCard = findByAttr(desk.element, "data-leak-doc-id", "")[0];
holdCard.listeners.click({});
const commitBtnHoldAgain = findByClass(desk.element, "mole-commit-btn")[0];
commitBtnHoldAgain.listeners.click({});

desk.addLogEntry({
  day: 3,
  tool: "mole_step",
  ok: true,
  data: { leaked: "d02", is_canary: true, variant: "B", mole: "e09", true_v: 0.55 },
});

const stateOut = desk.getState();
const serializedState = JSON.stringify(stateOut);
const domDump = JSON.stringify(walk(desk.element).map((n) => ({
  tag: n.tagName || null,
  cls: n.className || "",
  attrs: n.attrs || {},
  text: n.nodeType === 3 ? n.textContent : "",
})));

console.log(JSON.stringify({
  molePanelCount: molePanels.length,
  investigatorGridCount: findByClass(desk.element, "human-desk-grid").length,
  pickerGridCount: pickerGrids.length,
  cardCount: cards.length,
  cardTexts,
  stepsBeforeClick,
  stepsAfterSelectOnly,
  moleSteps,
  runCallsCount: runCalls.length,
  stateOut,
  serializedState,
  domDump,
}));
"""
    )
    assert result["molePanelCount"] == 1
    assert result["investigatorGridCount"] == 0
    assert result["pickerGridCount"] == 1
    assert result["cardCount"] == 3
    assert any("Hold Tonight (Do Not Leak)" in t for t in result["cardTexts"])
    assert any("d01" in t and "Merger Term Sheet" in t and "9 recipients" in t for t in result["cardTexts"])
    assert any("d02" in t and "Executive Compensation" in t and "4 recipients" in t for t in result["cardTexts"])
    assert result["stepsBeforeClick"] == 0
    assert result["stepsAfterSelectOnly"] == 1
    assert result["moleSteps"] == [
        {"leakDocId": None},
        {"leakDocId": "d02"},
        {"leakDocId": None},
    ]
    assert result["runCallsCount"] == 0

    for cand in result["stateOut"]["moleCandidateDocs"]:
        assert set(cand.keys()) == {"doc_id", "title", "day", "recipient_count"}

    for secret_token in ("is_canary", "true_v", "e09", "0.55", '"variant"'):
        assert secret_token not in result["serializedState"]
        assert secret_token not in result["domDump"]
