from __future__ import annotations

import io
import json
import math
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path
from typing import Any

from canary.env import Env

ROOT = Path(__file__).resolve().parents[1]
DOM_JS_PATH = ROOT / "docs" / "arena" / "ui" / "dom.js"
HUMAN_DESK_JS_PATH = ROOT / "docs" / "arena" / "ui" / "human_desk.js"
ACCUSE_MODAL_JS_PATH = ROOT / "docs" / "arena" / "ui" / "accuse_modal.js"
HYGIENE_SCRIPT_PATH = ROOT / "scripts" / "audit_arena_hygiene.py"
UI_CONTRACT_SCRIPT_PATH = ROOT / "scripts" / "verify_arena_ui_contract.py"
SELF_PATH = Path(__file__).resolve()
OPENCODE_TMP = Path("/tmp/opencode")

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
    raise AssertionError("node binary is required for accuse_modal.js ESM tests")


def _run_node_esm(js_body: str) -> dict[str, Any]:
    node_bin = _find_node()
    OPENCODE_TMP.mkdir(parents=True, exist_ok=True)
    dom_harness = """
function makeDoc() {
  return {
    createTextNode(text) {
      return { nodeType: 3, textContent: String(text) };
    },
    createElement(tag) {
      const attrs = {};
      const listeners = {};
      const children = [];
      const node = {
        nodeType: 1,
        tagName: String(tag).toUpperCase(),
        className: "",
        value: "",
        disabled: false,
        hidden: false,
        selected: false,
        dataset: {},
        style: { cssText: "" },
        attrs,
        listeners,
        childNodes: children,
        setAttribute(k, v) {
          attrs[k] = String(v);
          if (k === "class") this.className = String(v);
          if (k === "disabled") this.disabled = true;
          if (k === "hidden") this.hidden = true;
          if (k === "selected") this.selected = true;
          if (k === "value") this.value = String(v);
        },
        removeAttribute(k) {
          delete attrs[k];
          if (k === "disabled") this.disabled = false;
          if (k === "hidden") this.hidden = false;
          if (k === "selected") this.selected = false;
        },
        getAttribute(k) {
          return attrs[k];
        },
        addEventListener(ev, fn) {
          listeners[ev] = fn;
        },
        click() {
          if (this.disabled) return;
          if (typeof listeners.click === "function") {
            listeners.click({ preventDefault() {}, stopPropagation() {} });
          }
        },
        appendChild(child) {
          children.push(child);
          return child;
        },
        replaceChildren() {
          children.length = 0;
        }
      };
      return node;
    }
  };
}

function hasClass(node, cls) {
  if (!node || node.nodeType !== 1) return false;
  return String(node.className || "").split(" ").filter(Boolean).includes(cls);
}

function walk(node, out = []) {
  if (!node) return out;
  out.push(node);
  if (Array.isArray(node.childNodes)) {
    for (const ch of node.childNodes) walk(ch, out);
  }
  return out;
}

function findByClass(root, cls) {
  return walk(root).filter((n) => hasClass(n, cls));
}

function findByAttr(root, key, val) {
  return walk(root).filter(
    (n) => n.nodeType === 1 && n.attrs && (val === undefined ? key in n.attrs : n.attrs[key] === String(val))
  );
}

function textOf(node) {
  if (!node) return "";
  if (node.nodeType === 3) return String(node.textContent || "");
  return (node.childNodes || []).map(textOf).join("");
}
"""
    script_text = (
        f"import * as modalMod from {json.dumps(ACCUSE_MODAL_JS_PATH.as_uri())};\n"
        f"import * as deskMod from {json.dumps(HUMAN_DESK_JS_PATH.as_uri())};\n"
        f"import * as domMod from {json.dumps(DOM_JS_PATH.as_uri())};\n"
        + dom_harness
        + "\n"
        + js_body
    )
    with tempfile.TemporaryDirectory(dir=str(OPENCODE_TMP), prefix="test-accuse-modal-") as tmp_dir:
        runner_path = Path(tmp_dir) / "runner.mjs"
        runner_path.write_text(script_text, encoding="utf-8")
        proc = subprocess.run(
            [node_bin, str(runner_path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
    assert proc.returncode == 0, f"node failed ({proc.returncode}): {proc.stderr}\n{proc.stdout}"
    return json.loads(proc.stdout.strip())


def test_strict_hygiene_and_exports_contract() -> None:
    for path in (ACCUSE_MODAL_JS_PATH, SELF_PATH):
        assert path.is_file(), f"missing file: {path}"
        raw = path.read_text(encoding="utf-8")
        assert len(raw.strip()) > 0
        assert raw.isascii(), f"non-ASCII character in {path.name}"
        assert HASH_CH not in raw, f"hash character in {path.name}"
        assert EM_DASH not in raw, f"em dash in {path.name}"
        assert EN_DASH not in raw, f"en dash in {path.name}"
        assert UNICODE_MINUS not in raw, f"unicode minus in {path.name}"
        assert SLASH_SLASH not in raw, f"line comment marker in {path.name}"
        assert SLASH_STAR not in raw, f"block comment open in {path.name}"
        assert STAR_SLASH not in raw, f"block comment close in {path.name}"

    py_raw = SELF_PATH.read_text(encoding="utf-8")
    py_tokens = list(tokenize.generate_tokens(io.StringIO(py_raw).readline))
    assert [tok for tok in py_tokens if tok.type == tokenize.COMMENT] == []

    js_raw = ACCUSE_MODAL_JS_PATH.read_text(encoding="utf-8")
    assert 'import { el, clear, fmtScore } from "./dom.js";' in js_raw
    assert 'import { computeBreakEven, computeAccuseEV } from "./human_desk.js";' in js_raw
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in js_raw, f"forbidden XSS sink {sink} in accuse_modal.js"
    for net_api in ("fetch(", "XMLHttpRequest", "WebSocket"):
        assert net_api not in js_raw, f"forbidden live network call {net_api} in accuse_modal.js"

    for script_path in (HYGIENE_SCRIPT_PATH, UI_CONTRACT_SCRIPT_PATH):
        proc = subprocess.run(
            [sys.executable, str(script_path), "--check", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        report = json.loads(proc.stdout)
        assert report["passed"] is True


def test_ev_math_and_clamping_decision_summary() -> None:
    res = _run_node_esm(
        """
const sV1At50 = modalMod.computeAccuseDecisionSummary({ visibleV: 1.0, certaintyPct: 50 });
const sV1At75 = modalMod.computeAccuseDecisionSummary({ visibleV: 1.0, certaintyPct: 75 });
const sV06At625 = modalMod.computeAccuseDecisionSummary({ visibleV: 0.6, certaintyPct: 62.5 });
const sV06At80 = modalMod.computeAccuseDecisionSummary({ visibleV: 0.6, certaintyPct: 80 });
const sV06At40 = modalMod.computeAccuseDecisionSummary({ visibleV: 0.6, certaintyPct: 40 });
const sClampHigh = modalMod.computeAccuseDecisionSummary({ visibleV: 1.8, certaintyPct: 145 });
const sClampLow = modalMod.computeAccuseDecisionSummary({ visibleV: -0.4, certaintyPct: -20 });

console.log(JSON.stringify({
  wrongPenalty: modalMod.WRONG_ACCUSE_PENALTY,
  abstainReward: modalMod.ABSTAIN_REWARD,
  hasGlobal: Boolean(
    globalThis.CanaryAccuseModal &&
    globalThis.CanaryAccuseModal.createAccuseModal === modalMod.createAccuseModal
  ),
  sV1At50,
  sV1At75,
  sV06At625,
  sV06At80,
  sV06At40,
  sClampHigh,
  sClampLow,
}));
"""
    )

    assert res["wrongPenalty"] == -1
    assert res["abstainReward"] == 0
    assert res["hasGlobal"] is True

    expected_keys = {
        "p",
        "visibleV",
        "breakEvenP",
        "breakEvenPct",
        "ev",
        "positiveEV",
        "outcomeCorrect",
        "outcomeWrong",
        "outcomeAbstain",
    }
    assert set(res["sV1At50"].keys()) == expected_keys

    assert math.isclose(res["sV1At50"]["p"], 0.5, rel_tol=1e-9)
    assert math.isclose(res["sV1At50"]["visibleV"], 1.0, rel_tol=1e-9)
    assert math.isclose(res["sV1At50"]["breakEvenP"], 0.5, rel_tol=1e-9)
    assert math.isclose(res["sV1At50"]["breakEvenPct"], 50.0, rel_tol=1e-9)
    assert math.isclose(res["sV1At50"]["ev"], 0.0, abs_tol=1e-12)
    assert res["sV1At50"]["positiveEV"] is False
    assert res["sV1At50"]["outcomeCorrect"] == 1.0
    assert res["sV1At50"]["outcomeWrong"] == -1
    assert res["sV1At50"]["outcomeAbstain"] == 0

    assert math.isclose(res["sV1At75"]["ev"], 0.5, rel_tol=1e-9)
    assert res["sV1At75"]["positiveEV"] is True

    assert math.isclose(res["sV06At625"]["breakEvenP"], 0.625, rel_tol=1e-9)
    assert math.isclose(res["sV06At625"]["breakEvenPct"], 62.5, rel_tol=1e-9)
    assert math.isclose(res["sV06At625"]["ev"], 0.0, abs_tol=1e-12)
    assert res["sV06At625"]["positiveEV"] is False
    assert math.isclose(res["sV06At625"]["outcomeCorrect"], 0.6, rel_tol=1e-9)

    assert math.isclose(res["sV06At80"]["p"], 0.8, rel_tol=1e-9)
    assert math.isclose(res["sV06At80"]["ev"], 0.28, rel_tol=1e-9)
    assert res["sV06At80"]["positiveEV"] is True

    assert math.isclose(res["sV06At40"]["p"], 0.4, rel_tol=1e-9)
    assert math.isclose(res["sV06At40"]["ev"], -0.36, rel_tol=1e-9)
    assert res["sV06At40"]["positiveEV"] is False

    assert res["sClampHigh"]["visibleV"] == 1.0
    assert res["sClampHigh"]["p"] == 1.0
    assert math.isclose(res["sClampHigh"]["ev"], 1.0, rel_tol=1e-9)
    assert res["sClampHigh"]["positiveEV"] is True

    assert res["sClampLow"]["visibleV"] == 0.0
    assert res["sClampLow"]["p"] == 0.0
    assert math.isclose(res["sClampLow"]["breakEvenP"], 1.0, rel_tol=1e-9)
    assert math.isclose(res["sClampLow"]["breakEvenPct"], 100.0, rel_tol=1e-9)
    assert math.isclose(res["sClampLow"]["ev"], -1.0, rel_tol=1e-9)
    assert res["sClampLow"]["positiveEV"] is False


def test_modal_dom_interactions_slider_marks_and_callbacks() -> None:
    res = _run_node_esm(
        """
const doc = makeDoc();
const confirmed = [];
let abstainCount = 0;
let cancelCount = 0;

const employees = [
  { id: "e00", name: "Ada Lovelace", dept: "Eng", role: "Principal" },
  { id: "e01", name: "Ben Carter", dept: "Ops", role: "Analyst" },
  { id: "e02", name: "Cyra Diaz", dept: "Legal", role: "Counsel" },
];

const modal = modalMod.createAccuseModal({
  document: doc,
  employees,
  marks: { e00: "prime", e01: "cleared" },
  visibleV: 0.6,
  certaintyPct: 50,
  onConfirm: (payload) => confirmed.push(payload),
  onAbstain: () => { abstainCount += 1; },
  onCancel: () => { cancelCount += 1; },
});

const initialHidden = modal.element.hidden;
const initialRole = modal.element.getAttribute("role");
const initialAriaModal = modal.element.getAttribute("aria-modal");
const initialState = modal.getState();

const openState = modal.open();
const afterOpenHidden = modal.element.hidden;

const confirmBtn = findByAttr(modal.element, "data-accuse-action", "confirm")[0];
const confirmInitiallyDisabled = confirmBtn.disabled;
confirmBtn.click();
const confirmCountWhileDisabled = confirmed.length;

const warningText = textOf(findByClass(modal.element, "accuse-modal-warning")[0]);
const beNode = findByClass(modal.element, "accuse-breakeven")[0];
const evNode = findByClass(modal.element, "accuse-ev")[0];
const beInitialText = textOf(beNode);
const evInitialText = textOf(evNode);

const suspectBtns = findByClass(modal.element, "accuse-suspect-btn");
const marksRendered = suspectBtns.map((b) => [b.dataset.empId, b.dataset.mark]);

suspectBtns[0].click();
const afterBtnClickSelected = modal.getState().selectedEmployee;
const afterBtnClickDisabled = confirmBtn.disabled;

const selectNode = findByAttr(modal.element, "name", "employee")[0];
selectNode.value = "";
selectNode.listeners.change({});
const afterClearSelectDisabled = confirmBtn.disabled;

selectNode.value = "e01";
selectNode.listeners.change({});
const afterSelectE01Disabled = confirmBtn.disabled;

const slider = findByAttr(modal.element, "name", "certainty")[0];
slider.value = "62.5";
slider.listeners.input({});
const evAtBreakEven = Number(evNode.attrs["data-ev"]);
const posAtBreakEven = evNode.attrs["data-positive-ev"];

slider.value = "85";
slider.listeners.input({});
const evAt85Text = textOf(evNode);
const evAt85Attr = Number(evNode.attrs["data-ev"]);
const posAt85 = evNode.attrs["data-positive-ev"];

confirmBtn.click();
const closedAfterConfirm = modal.getState().open === false && modal.element.hidden === true;

modal.open({ visibleV: 1.0, certaintyPct: 40, initialEmployee: "e02", marks: { e02: "suspect" } });
const stateOnReopen = modal.getState();
const abstainBtn = findByAttr(modal.element, "data-accuse-action", "abstain")[0];
abstainBtn.click();
const closedAfterAbstain = modal.getState().open === false;

modal.open({ certaintyPct: 60 });
const cancelBtn = findByAttr(modal.element, "data-accuse-action", "cancel")[0];
cancelBtn.click();
const closedAfterCancel = modal.getState().open === false;

modal.open();
modal.element.listeners.keydown({ key: "Escape", preventDefault() {} });
const closedAfterEscape = modal.getState().open === false;

modal.open({ initialEmployee: "e00" });
const updatedState = modal.update({ visibleV: 0.25, certaintyPct: 90 });
const closedByMethod = modal.close();

console.log(JSON.stringify({
  initialHidden,
  initialRole,
  initialAriaModal,
  initialState,
  openState,
  afterOpenHidden,
  confirmInitiallyDisabled,
  confirmCountWhileDisabled,
  warningText,
  beInitialText,
  evInitialText,
  marksRendered,
  afterBtnClickSelected,
  afterBtnClickDisabled,
  afterClearSelectDisabled,
  afterSelectE01Disabled,
  evAtBreakEven,
  posAtBreakEven,
  evAt85Text,
  evAt85Attr,
  posAt85,
  confirmed,
  closedAfterConfirm,
  stateOnReopen,
  abstainCount,
  closedAfterAbstain,
  cancelCount,
  closedAfterCancel,
  closedAfterEscape,
  updatedState,
  closedByMethod,
}));
"""
    )

    assert res["initialHidden"] is True
    assert res["initialRole"] == "dialog"
    assert res["initialAriaModal"] == "true"
    assert res["initialState"]["open"] is False
    assert res["initialState"]["selectedEmployee"] is None
    assert res["openState"]["open"] is True
    assert res["afterOpenHidden"] is False

    assert res["confirmInitiallyDisabled"] is True
    assert res["confirmCountWhileDisabled"] == 0

    warning = res["warningText"]
    assert "ends the episode immediately" in warning
    assert "correct = +0.600 [+V]" in warning
    assert "wrong = -1.000" in warning
    assert "abstain = 0.000" in warning
    assert "pre-end" in warning

    assert res["beInitialText"] == "62.5%"
    assert "-0.20" in res["evInitialText"]
    assert res["marksRendered"] == [
        ["e00", "prime"],
        ["e01", "cleared"],
        ["e02", "unmarked"],
    ]

    assert res["afterBtnClickSelected"] == "e00"
    assert res["afterBtnClickDisabled"] is False
    assert res["afterClearSelectDisabled"] is True
    assert res["afterSelectE01Disabled"] is False

    assert math.isclose(res["evAtBreakEven"], 0.0, abs_tol=1e-6)
    assert res["posAtBreakEven"] == "false"
    assert "+0.36" in res["evAt85Text"]
    assert math.isclose(res["evAt85Attr"], 0.36, rel_tol=1e-6)
    assert res["posAt85"] == "true"

    assert len(res["confirmed"]) == 1
    payload = res["confirmed"][0]
    assert set(payload.keys()) == {"employee", "certaintyPct", "ev", "breakEvenP"}
    assert payload["employee"] == "e01"
    assert payload["certaintyPct"] == 85
    assert math.isclose(payload["ev"], 0.36, rel_tol=1e-9)
    assert math.isclose(payload["breakEvenP"], 0.625, rel_tol=1e-9)
    assert res["closedAfterConfirm"] is True

    assert res["stateOnReopen"]["selectedEmployee"] == "e02"
    assert res["stateOnReopen"]["marks"]["e02"] == "prime"
    assert math.isclose(res["stateOnReopen"]["breakEvenPct"], 50.0, rel_tol=1e-9)
    assert res["abstainCount"] == 1
    assert res["closedAfterAbstain"] is True
    assert res["cancelCount"] == 2
    assert res["closedAfterCancel"] is True
    assert res["closedAfterEscape"] is True

    assert math.isclose(res["updatedState"]["visibleV"], 0.25, rel_tol=1e-9)
    assert math.isclose(res["updatedState"]["breakEvenPct"], 80.0, rel_tol=1e-9)
    assert res["closedByMethod"]["open"] is False


def test_xss_safety_and_pre_end_hidden_truth_scrubbing_and_env_compat() -> None:
    live_env = Env("hard", 6)
    public_employees = live_env.call("list_employees", {}).data["employees"][:4]

    res = _run_node_esm(
        f"""
const doc = makeDoc();
const trapHits = [];
const forbiddenKeys = new Set([
  "mole",
  "true_mole",
  "decoy",
  "true_v",
  "trueV",
  "mole_id",
  "moleId",
  "is_mole",
  "isMole",
  "is_canary",
  "variant",
  "sealed_verdict",
]);

function guardHiddenReads(obj) {{
  return new Proxy(obj, {{
    get(target, prop) {{
      const name = String(prop);
      if (forbiddenKeys.has(name)) {{
        trapHits.push(name);
        throw new Error("Forbidden pre-end truth read: " + name);
      }}
      return target[prop];
    }}
  }});
}}

const baseEmployees = {json.dumps(public_employees)};
const hostileEmployees = [
  guardHiddenReads({{
    id: baseEmployees[0].id,
    name: "<script>window.__pwned=1</script>Ada",
    dept: "Eng <img src=x onerror=alert(1)>",
    role: "Lead \\" onclick=\\"evil()",
    mole: true,
    true_mole: baseEmployees[0].id,
    decoy: baseEmployees[1].id,
    true_v: 0.19,
  }}),
  {{
    id: baseEmployees[1].id,
    name: baseEmployees[1].name,
    dept: baseEmployees[1].dept,
    role: baseEmployees[1].role,
    mole: "SECRET_MOLE_ID_99",
    true_mole: "SECRET_TRUE_MOLE_99",
    decoy: "SECRET_DECOY_99",
    true_v: 0.19,
    trueV: 0.19,
  }},
];

const confirmed = [];
const modal = modalMod.createAccuseModal(guardHiddenReads({{
  document: doc,
  employees: hostileEmployees,
  marks: {{ [baseEmployees[0].id]: "true_mole", [baseEmployees[1].id]: "prime" }},
  visibleV: 0.8,
  certaintyPct: 70,
  initialEmployee: baseEmployees[0].id,
  mole: "SECRET_MOLE_ID_99",
  true_mole: "SECRET_TRUE_MOLE_99",
  decoy: "SECRET_DECOY_99",
  true_v: 0.19,
  trueV: 0.19,
  onConfirm: (payload) => confirmed.push(payload),
}}));

modal.open();
const allElementTags = walk(modal.element).filter((n) => n.nodeType === 1).map((n) => n.tagName);
const stateDump = JSON.stringify(modal.getState());
const domText = textOf(modal.element);

const confirmBtn = findByAttr(modal.element, "data-accuse-action", "confirm")[0];
confirmBtn.click();

console.log(JSON.stringify({{
  trapHits,
  allElementTags,
  stateOut: modal.getState(),
  stateDump,
  domText,
  confirmed,
}}));
"""
    )

    assert res["trapHits"] == []
    assert "SCRIPT" not in res["allElementTags"]
    assert "IMG" not in res["allElementTags"]
    assert "<script>window.__pwned=1</script>Ada" in res["domText"]
    assert "<img src=x onerror=alert(1)>" in res["domText"]

    assert res["stateOut"]["marks"][public_employees[0]["id"]] == "unmarked"
    assert res["stateOut"]["marks"][public_employees[1]["id"]] == "prime"
    for emp_entry in res["stateOut"]["employees"]:
        assert set(emp_entry.keys()) == {"id", "name", "dept", "role", "mark"}

    for forbidden_tok in (
        "SECRET_MOLE_ID_99",
        "SECRET_TRUE_MOLE_99",
        "SECRET_DECOY_99",
        "0.19",
        "true_mole",
        "true_v",
        "trueV",
        "decoy",
    ):
        assert forbidden_tok not in res["stateDump"]
        assert forbidden_tok not in res["domText"]

    assert len(res["confirmed"]) == 1
    accuse_call = live_env.call("accuse", {"employee": res["confirmed"][0]["employee"]})
    assert accuse_call.ok, accuse_call.error
    assert live_env.done is True
