import { el, clear, fmtScore } from "./dom.js";
import { computeBreakEven, computeAccuseEV } from "./human_desk.js";

export const WRONG_ACCUSE_PENALTY = -1;
export const ABSTAIN_REWARD = 0;

function clampFinite(raw, minVal, maxVal, fallback) {
  if (raw === null || raw === undefined || raw === "" || typeof raw === "boolean") {
    return fallback;
  }
  const num = Number(raw);
  if (!Number.isFinite(num)) {
    return fallback;
  }
  return Math.min(maxVal, Math.max(minVal, num));
}

function formatPct(pct) {
  const num = Number(pct);
  if (!Number.isFinite(num)) return "50%";
  const rounded = Math.round(num * 10) / 10;
  if (Number.isInteger(rounded)) {
    return String(rounded) + "%";
  }
  return rounded.toFixed(1) + "%";
}

function formatSigned3(val) {
  const num = Number(val);
  if (!Number.isFinite(num)) return "0.000";
  const rounded = Math.round(num * 1000) / 1000;
  if (rounded === 0) return "0.000";
  const sign = rounded > 0 ? "+" : "-";
  return sign + Math.abs(rounded).toFixed(3);
}

function normalizeSuspectMark(rawMark) {
  if (typeof rawMark !== "string") return "unmarked";
  const clean = rawMark.trim().toLowerCase();
  if (clean === "prime" || clean === "suspect") return "prime";
  if (clean === "cleared") return "cleared";
  return "unmarked";
}

function sanitizePublicEmployee(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = String(raw.id === undefined || raw.id === null ? "" : raw.id).trim();
  if (!id) return null;
  const rawName = raw.name === undefined || raw.name === null ? "" : String(raw.name).trim();
  const name = rawName || id;
  const dept = raw.dept === undefined || raw.dept === null ? "" : String(raw.dept).trim();
  const role = raw.role === undefined || raw.role === null ? "" : String(raw.role).trim();
  return { id, name, dept, role };
}

function sanitizeEmployeeList(rawList) {
  if (!Array.isArray(rawList)) return [];
  const seen = new Set();
  const out = [];
  for (const item of rawList) {
    const clean = sanitizePublicEmployee(item);
    if (!clean || seen.has(clean.id)) continue;
    seen.add(clean.id);
    out.push(clean);
  }
  return out;
}

function readMarkForId(marksSource, empId) {
  if (!marksSource || typeof marksSource !== "object" || !empId) {
    return "unmarked";
  }
  if (typeof marksSource.get === "function") {
    return normalizeSuspectMark(marksSource.get(empId));
  }
  if (Object.prototype.hasOwnProperty.call(marksSource, empId)) {
    return normalizeSuspectMark(marksSource[empId]);
  }
  return "unmarked";
}

function resolveEmployeeIdCandidate(rawTarget) {
  if (typeof rawTarget === "string") {
    return rawTarget.trim();
  }
  if (rawTarget && typeof rawTarget === "object" && rawTarget.id !== undefined && rawTarget.id !== null) {
    return String(rawTarget.id).trim();
  }
  return "";
}

function resolveValidEmployeeId(rawTarget, employees) {
  const candidate = resolveEmployeeIdCandidate(rawTarget);
  if (!candidate) return null;
  for (const emp of employees) {
    if (emp.id === candidate) return candidate;
  }
  return null;
}

function withValue(node, val) {
  const str = String(val === null || val === undefined ? "" : val);
  try {
    node.value = str;
  } catch (_) {}
  if (typeof node.setAttribute === "function") {
    node.setAttribute("value", str);
  }
  return node;
}

function setDisabledState(node, disabledFlag) {
  if (!node) return;
  const off = Boolean(disabledFlag);
  try {
    node.disabled = off;
  } catch (_) {}
  if (off) {
    if (typeof node.setAttribute === "function") {
      node.setAttribute("disabled", "");
    }
  } else if (typeof node.removeAttribute === "function") {
    node.removeAttribute("disabled");
  }
}

function setHiddenState(node, hiddenFlag) {
  if (!node) return;
  const hide = Boolean(hiddenFlag);
  try {
    node.hidden = hide;
  } catch (_) {}
  if (hide) {
    if (typeof node.setAttribute === "function") {
      node.setAttribute("hidden", "");
      node.setAttribute("aria-hidden", "true");
    }
  } else {
    if (typeof node.removeAttribute === "function") {
      node.removeAttribute("hidden");
    }
    if (typeof node.setAttribute === "function") {
      node.setAttribute("aria-hidden", "false");
    }
  }
}

function setDataAttr(node, key, attrName, val) {
  if (!node) return;
  const str = String(val);
  if (node.dataset && typeof node.dataset === "object") {
    node.dataset[key] = str;
  }
  if (typeof node.setAttribute === "function") {
    node.setAttribute(attrName, str);
  }
}

export function computeAccuseDecisionSummary(opts = {}) {
  const src = opts && typeof opts === "object" ? opts : {};
  const visibleV = clampFinite(src.visibleV, 0, 1, 1.0);
  const certaintyPct = clampFinite(src.certaintyPct, 0, 100, 50);
  const p = certaintyPct / 100;
  const breakEvenP = computeBreakEven(visibleV);
  const breakEvenPct = breakEvenP * 100;
  const rawEv = computeAccuseEV(p, visibleV);
  const ev = Math.abs(rawEv) < 1e-12 ? 0 : rawEv;
  const positiveEV = ev > 0;
  return {
    p,
    visibleV,
    breakEvenP,
    breakEvenPct,
    ev,
    positiveEV,
    outcomeCorrect: visibleV,
    outcomeWrong: WRONG_ACCUSE_PENALTY,
    outcomeAbstain: ABSTAIN_REWARD,
  };
}

export function createAccuseModal(opts = {}) {
  const options = opts && typeof opts === "object" ? opts : {};
  const doc = options.document || (typeof globalThis !== "undefined" ? globalThis.document : null);
  if (!doc) {
    throw new Error("No document available for createAccuseModal");
  }

  let onConfirmCb = typeof options.onConfirm === "function" ? options.onConfirm : null;
  let onAbstainCb = typeof options.onAbstain === "function" ? options.onAbstain : null;
  let onCancelCb = typeof options.onCancel === "function" ? options.onCancel : null;
  let lastMarksSource = options.marks !== undefined ? options.marks : null;

  function h(tag, attrs, ...children) {
    const nextAttrs = attrs && typeof attrs === "object" ? { ...attrs, document: doc } : { document: doc };
    return el(tag, nextAttrs, ...children);
  }

  function setText(node, text) {
    if (!node) return node;
    clear(node);
    const str = String(text === null || text === undefined ? "" : text);
    const textNode =
      typeof doc.createTextNode === "function"
        ? doc.createTextNode(str)
        : { nodeType: 3, textContent: str, nodeValue: str, data: str };
    if (typeof node.appendChild === "function") {
      node.appendChild(textNode);
    } else if (Array.isArray(node.childNodes)) {
      node.childNodes.push(textNode);
    }
    return node;
  }

  const state = {
    open: Boolean(options.open),
    employees: [],
    marks: {},
    visibleV: 1.0,
    certaintyPct: 50,
    selectedEmployee: null,
  };

  function rebuildMarksMap() {
    const nextMarks = {};
    for (const emp of state.employees) {
      nextMarks[emp.id] = readMarkForId(lastMarksSource, emp.id);
    }
    state.marks = nextMarks;
  }

  function applyStatePatch(patch) {
    if (!patch || typeof patch !== "object") return;

    if (typeof patch.onConfirm === "function") onConfirmCb = patch.onConfirm;
    if (typeof patch.onAbstain === "function") onAbstainCb = patch.onAbstain;
    if (typeof patch.onCancel === "function") onCancelCb = patch.onCancel;

    if (patch.marks !== undefined) {
      lastMarksSource = patch.marks;
    }

    if (patch.employees !== undefined) {
      state.employees = sanitizeEmployeeList(patch.employees);
    }

    if (patch.employees !== undefined || patch.marks !== undefined) {
      rebuildMarksMap();
    }

    if (patch.visibleV !== undefined) {
      state.visibleV = clampFinite(patch.visibleV, 0, 1, state.visibleV);
    }

    if (patch.certaintyPct !== undefined) {
      state.certaintyPct = clampFinite(patch.certaintyPct, 0, 100, state.certaintyPct);
    }

    const hasInitialEmp = Object.prototype.hasOwnProperty.call(patch, "initialEmployee");
    const hasSelectedEmp = Object.prototype.hasOwnProperty.call(patch, "selectedEmployee");
    if (hasInitialEmp || hasSelectedEmp) {
      const target = hasInitialEmp ? patch.initialEmployee : patch.selectedEmployee;
      state.selectedEmployee = resolveValidEmployeeId(target, state.employees);
    } else if (!resolveValidEmployeeId(state.selectedEmployee, state.employees)) {
      state.selectedEmployee = null;
    }
  }

  applyStatePatch(options);

  let refs = {
    warningText: null,
    select: null,
    optionById: new Map(),
    suspectBtnById: new Map(),
    selectedSummary: null,
    slider: null,
    certaintyVal: null,
    visibleVVal: null,
    breakEvenVal: null,
    evVal: null,
    recommendationBadge: null,
    outcomesLine: null,
    confirmBtn: null,
  };

  const rootEl = h("div", {
    class: "accuse-modal sheet",
    role: "dialog",
    "aria-modal": "true",
    "aria-labelledby": "accuse-modal-title",
    tabindex: "-1",
    onKeydown: (ev) => {
      if (ev && ev.key === "Escape") {
        if (typeof ev.preventDefault === "function") ev.preventDefault();
        handleCancel();
      }
    },
  });

  function syncOpenAttributes() {
    setHiddenState(rootEl, !state.open);
    setDataAttr(rootEl, "open", "data-open", state.open ? "true" : "false");
  }

  function findSelectedEmployeeRecord() {
    if (!state.selectedEmployee) return null;
    for (const emp of state.employees) {
      if (emp.id === state.selectedEmployee) return emp;
    }
    return null;
  }

  function formatEmployeeMeta(emp) {
    const parts = [];
    if (emp.dept) parts.push(emp.dept);
    if (emp.role) parts.push(emp.role);
    return parts.join(" / ");
  }

  function formatWarningMessage(summary) {
    return (
      "Final action warning: accuse ends the episode immediately (correct = +" +
      summary.visibleV.toFixed(3) +
      " [+V], wrong = -1.000, abstain = 0.000) and never reveals hidden truth pre-end."
    );
  }

  function formatOutcomesMessage(summary) {
    return (
      "Payoffs -> Correct: +" +
      summary.outcomeCorrect.toFixed(3) +
      " (+V) | Wrong: " +
      summary.outcomeWrong.toFixed(3) +
      " | Abstain / Hold: " +
      summary.outcomeAbstain.toFixed(3)
    );
  }

  function formatSelectedSummaryText() {
    const rec = findSelectedEmployeeRecord();
    if (!rec) {
      return "Selected suspect: none (choose a suspect to enable Confirm Accusation)";
    }
    const mark = state.marks[rec.id] || "unmarked";
    const meta = formatEmployeeMeta(rec);
    return (
      "Selected suspect: " +
      rec.id +
      " - " +
      rec.name +
      (meta ? " (" + meta + ")" : "") +
      " [" +
      mark +
      "]"
    );
  }

  function syncSelectionNodes() {
    const selId = state.selectedEmployee || "";
    if (refs.select) {
      withValue(refs.select, selId);
    }
    for (const [optKey, optNode] of refs.optionById.entries()) {
      const isSelected = optKey === selId;
      try {
        optNode.selected = isSelected;
      } catch (_) {}
      if (isSelected) {
        if (typeof optNode.setAttribute === "function") optNode.setAttribute("selected", "");
      } else if (typeof optNode.removeAttribute === "function") {
        optNode.removeAttribute("selected");
      }
    }
    for (const [empId, btnNode] of refs.suspectBtnById.entries()) {
      const isSelected = empId === selId;
      const mark = state.marks[empId] || "unmarked";
      const classes = ["seed-pill", "accuse-suspect-btn"];
      if (isSelected) classes.push("active");
      if (mark === "prime") classes.push("mark-prime");
      if (mark === "cleared") classes.push("mark-cleared");
      const clsStr = classes.join(" ");
      btnNode.className = clsStr;
      if (typeof btnNode.setAttribute === "function") {
        btnNode.setAttribute("class", clsStr);
        btnNode.setAttribute("aria-pressed", isSelected ? "true" : "false");
      }
    }
    if (refs.selectedSummary) {
      setText(refs.selectedSummary, formatSelectedSummaryText());
    }
    if (refs.confirmBtn) {
      const hasSuspect = Boolean(state.selectedEmployee);
      setDisabledState(refs.confirmBtn, !hasSuspect);
      setText(
        refs.confirmBtn,
        hasSuspect ? "Confirm Accusation (" + state.selectedEmployee + ")" : "Confirm Accusation"
      );
    }
  }

  function syncDecisionNodes() {
    const summary = computeAccuseDecisionSummary({
      visibleV: state.visibleV,
      certaintyPct: state.certaintyPct,
    });
    if (refs.slider) {
      withValue(refs.slider, state.certaintyPct);
    }
    if (refs.warningText) {
      setText(refs.warningText, formatWarningMessage(summary));
    }
    if (refs.certaintyVal) {
      setText(refs.certaintyVal, formatPct(state.certaintyPct));
      setDataAttr(refs.certaintyVal, "certaintyPct", "data-certainty-pct", state.certaintyPct);
      setDataAttr(refs.certaintyVal, "p", "data-p", summary.p.toFixed(6));
    }
    if (refs.visibleVVal) {
      setText(refs.visibleVVal, summary.visibleV.toFixed(3));
      setDataAttr(refs.visibleVVal, "visibleV", "data-visible-v", summary.visibleV.toFixed(6));
    }
    if (refs.breakEvenVal) {
      setText(refs.breakEvenVal, summary.breakEvenPct.toFixed(1) + "%");
      setDataAttr(refs.breakEvenVal, "breakeven", "data-breakeven", summary.breakEvenP.toFixed(6));
    }
    if (refs.evVal) {
      setText(refs.evVal, fmtScore(summary.ev) + " (" + formatSigned3(summary.ev) + ")");
      setDataAttr(refs.evVal, "ev", "data-ev", summary.ev.toFixed(6));
      setDataAttr(refs.evVal, "positiveEv", "data-positive-ev", summary.positiveEV ? "true" : "false");
    }
    if (refs.recommendationBadge) {
      const cls = summary.positiveEV
        ? "t ok accuse-recommendation"
        : "t red accuse-recommendation";
      refs.recommendationBadge.className = cls;
      if (typeof refs.recommendationBadge.setAttribute === "function") {
        refs.recommendationBadge.setAttribute("class", cls);
      }
      setDataAttr(
        refs.recommendationBadge,
        "recommendation",
        "data-recommendation",
        summary.positiveEV ? "accuse" : "abstain"
      );
      setText(
        refs.recommendationBadge,
        summary.positiveEV ? "POSITIVE EV vs ABSTAIN" : "HOLD / ABSTAIN FAVORED"
      );
    }
    if (refs.outcomesLine) {
      setText(refs.outcomesLine, formatOutcomesMessage(summary));
    }
  }

  function handleConfirm() {
    if (!state.selectedEmployee) return;
    const summary = computeAccuseDecisionSummary({
      visibleV: state.visibleV,
      certaintyPct: state.certaintyPct,
    });
    const payload = {
      employee: state.selectedEmployee,
      certaintyPct: state.certaintyPct,
      ev: summary.ev,
      breakEvenP: summary.breakEvenP,
    };
    state.open = false;
    syncOpenAttributes();
    if (typeof onConfirmCb === "function") {
      onConfirmCb(payload);
    }
  }

  function handleAbstain() {
    state.open = false;
    syncOpenAttributes();
    if (typeof onAbstainCb === "function") {
      onAbstainCb();
    }
  }

  function handleCancel() {
    state.open = false;
    syncOpenAttributes();
    if (typeof onCancelCb === "function") {
      onCancelCb();
    }
  }

  function render() {
    clear(rootEl);
    refs = {
      warningText: null,
      select: null,
      optionById: new Map(),
      suspectBtnById: new Map(),
      selectedSummary: null,
      slider: null,
      certaintyVal: null,
      visibleVVal: null,
      breakEvenVal: null,
      evVal: null,
      recommendationBadge: null,
      outcomesLine: null,
      confirmBtn: null,
    };

    const summary = computeAccuseDecisionSummary({
      visibleV: state.visibleV,
      certaintyPct: state.certaintyPct,
    });

    const headerEl = h(
      "div",
      { class: "sheet-h accuse-modal-head" },
      h("span", { id: "accuse-modal-title" }, "Confirm Final Accusation"),
      h("span", { class: "sync-lock-badge locked" }, "[SEALED] PRE-END")
    );

    const warningEl = h(
      "div",
      { class: "leak-alert accuse-modal-warning" },
      formatWarningMessage(summary)
    );
    refs.warningText = warningEl;

    const emptyOpt = withValue(
      h("option", { value: "", selected: !state.selectedEmployee }, "Select suspect..."),
      ""
    );
    refs.optionById.set("", emptyOpt);
    const optionNodes = [emptyOpt];

    const suspectButtons = [];
    for (const emp of state.employees) {
      const isSelected = state.selectedEmployee === emp.id;
      const mark = state.marks[emp.id] || "unmarked";
      const meta = formatEmployeeMeta(emp);
      const optLabel =
        emp.id +
        " - " +
        emp.name +
        (meta ? " (" + meta + ")" : "") +
        " [" +
        mark +
        "]";
      const optNode = withValue(
        h(
          "option",
          {
            value: emp.id,
            selected: isSelected,
            dataset: { mark },
          },
          optLabel
        ),
        emp.id
      );
      refs.optionById.set(emp.id, optNode);
      optionNodes.push(optNode);

      const markBadgeClass =
        mark === "prime" ? "t hl emp-mark" : mark === "cleared" ? "t dim emp-mark" : "t emp-mark";
      const btnClasses = ["seed-pill", "accuse-suspect-btn"];
      if (isSelected) btnClasses.push("active");
      if (mark === "prime") btnClasses.push("mark-prime");
      if (mark === "cleared") btnClasses.push("mark-cleared");

      const btnNode = h(
        "button",
        {
          type: "button",
          class: btnClasses,
          "aria-pressed": isSelected ? "true" : "false",
          dataset: { empId: emp.id, mark },
          onClick: () => {
            state.selectedEmployee = emp.id;
            syncSelectionNodes();
          },
        },
        h("span", { class: "mono emp-id" }, emp.id),
        " ",
        h("span", { class: "emp-name" }, emp.name),
        meta ? h("span", { class: "dim emp-meta" }, " (" + meta + ")") : null,
        " ",
        h("span", { class: markBadgeClass }, mark)
      );
      refs.suspectBtnById.set(emp.id, btnNode);
      suspectButtons.push(btnNode);
    }

    const selectEl = withValue(
      h(
        "select",
        {
          name: "employee",
          class: "accuse-suspect-select",
          "aria-label": "Suspect to accuse",
          onChange: () => {
            state.selectedEmployee = resolveValidEmployeeId(selectEl.value, state.employees);
            syncSelectionNodes();
          },
          onInput: () => {
            state.selectedEmployee = resolveValidEmployeeId(selectEl.value, state.employees);
            syncSelectionNodes();
          },
        },
        optionNodes
      ),
      state.selectedEmployee || ""
    );
    refs.select = selectEl;

    const selectedSummaryEl = h(
      "div",
      { class: "mono dim accuse-selected-summary" },
      formatSelectedSummaryText()
    );
    refs.selectedSummary = selectedSummaryEl;

    const suspectSection = h(
      "div",
      {
        class: "accuse-suspect-section",
        style: "padding: 12px; display: flex; flex-direction: column; gap: 8px;",
      },
      h(
        "label",
        { class: "accuse-field", style: "display: flex; flex-direction: column; gap: 4px;" },
        h("span", { class: "lbl" }, "Suspect"),
        selectEl
      ),
      suspectButtons.length > 0
        ? h(
            "div",
            {
              class: "seed-group accuse-suspect-list",
              role: "group",
              "aria-label": "Suspect roster",
            },
            suspectButtons
          )
        : h("div", { class: "dim mono accuse-empty-roster" }, "No employees loaded."),
      selectedSummaryEl
    );

    const sliderEl = withValue(
      h("input", {
        type: "range",
        name: "certainty",
        class: "accuse-certainty-slider",
        "aria-label": "Certainty percentage",
        min: "0",
        max: "100",
        step: "0.5",
        onInput: () => {
          state.certaintyPct = clampFinite(sliderEl.value, 0, 100, state.certaintyPct);
          syncDecisionNodes();
        },
        onChange: () => {
          state.certaintyPct = clampFinite(sliderEl.value, 0, 100, state.certaintyPct);
          syncDecisionNodes();
        },
      }),
      state.certaintyPct
    );
    refs.slider = sliderEl;

    const certaintyValEl = h(
      "span",
      {
        class: "mono accuse-certainty-val",
        dataset: { certaintyPct: String(state.certaintyPct), p: summary.p.toFixed(6) },
      },
      formatPct(state.certaintyPct)
    );
    refs.certaintyVal = certaintyValEl;

    const visibleVValEl = h(
      "span",
      {
        class: "mono accuse-visible-v",
        dataset: { visibleV: summary.visibleV.toFixed(6) },
      },
      summary.visibleV.toFixed(3)
    );
    refs.visibleVVal = visibleVValEl;

    const breakEvenValEl = h(
      "span",
      {
        class: "mono accuse-breakeven",
        dataset: { breakeven: summary.breakEvenP.toFixed(6) },
      },
      summary.breakEvenPct.toFixed(1) + "%"
    );
    refs.breakEvenVal = breakEvenValEl;

    const evValEl = h(
      "span",
      {
        class: "mono accuse-ev",
        dataset: {
          ev: summary.ev.toFixed(6),
          positiveEv: summary.positiveEV ? "true" : "false",
        },
      },
      fmtScore(summary.ev) + " (" + formatSigned3(summary.ev) + ")"
    );
    refs.evVal = evValEl;

    const recommendationEl = h(
      "span",
      {
        class: summary.positiveEV
          ? "t ok accuse-recommendation"
          : "t red accuse-recommendation",
        dataset: { recommendation: summary.positiveEV ? "accuse" : "abstain" },
      },
      summary.positiveEV ? "POSITIVE EV vs ABSTAIN" : "HOLD / ABSTAIN FAVORED"
    );
    refs.recommendationBadge = recommendationEl;

    const outcomesLineEl = h(
      "div",
      { class: "mono dim accuse-outcomes" },
      formatOutcomesMessage(summary)
    );
    refs.outcomesLine = outcomesLineEl;

    const calcSection = h(
      "div",
      {
        class: "accuse-calc-section",
        style: "padding: 0 12px 12px; display: flex; flex-direction: column; gap: 8px;",
      },
      h(
        "label",
        { class: "accuse-field", style: "display: flex; flex-direction: column; gap: 4px;" },
        h("span", { class: "lbl" }, "Certainty p (0..100%)"),
        sliderEl
      ),
      h(
        "div",
        { class: "share-box accuse-ev-summary" },
        h("span", {}, "Visible V: ", visibleVValEl),
        h("span", {}, "Break-even 1 / (1 + V): ", breakEvenValEl),
        h("span", {}, "Certainty p: ", certaintyValEl),
        h("span", {}, "EV p * V - (1 - p): ", evValEl),
        recommendationEl
      ),
      outcomesLineEl
    );

    const hasSuspect = Boolean(state.selectedEmployee);
    const confirmBtnEl = h(
      "button",
      {
        type: "button",
        class: "danger accuse-confirm-btn",
        disabled: !hasSuspect,
        dataset: { accuseAction: "confirm" },
        onClick: () => handleConfirm(),
      },
      hasSuspect ? "Confirm Accusation (" + state.selectedEmployee + ")" : "Confirm Accusation"
    );
    refs.confirmBtn = confirmBtnEl;

    const abstainBtnEl = h(
      "button",
      {
        type: "button",
        class: "ghost accuse-abstain-btn",
        dataset: { accuseAction: "abstain" },
        onClick: () => handleAbstain(),
      },
      "Abstain / Hold"
    );

    const cancelBtnEl = h(
      "button",
      {
        type: "button",
        class: "ghost accuse-cancel-btn",
        dataset: { accuseAction: "cancel" },
        onClick: () => handleCancel(),
      },
      "Cancel"
    );

    const actionsEl = h(
      "div",
      {
        class: "accuse-modal-actions",
        style: "padding: 10px 12px; border-top: 1px solid var(--hair); display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px;",
      },
      cancelBtnEl,
      abstainBtnEl,
      confirmBtnEl
    );

    rootEl.appendChild(headerEl);
    rootEl.appendChild(warningEl);
    rootEl.appendChild(suspectSection);
    rootEl.appendChild(calcSection);
    rootEl.appendChild(actionsEl);
    syncOpenAttributes();
    return rootEl;
  }

  function getState() {
    const summary = computeAccuseDecisionSummary({
      visibleV: state.visibleV,
      certaintyPct: state.certaintyPct,
    });
    const employeesOut = state.employees.map((emp) => ({
      id: emp.id,
      name: emp.name,
      dept: emp.dept,
      role: emp.role,
      mark: state.marks[emp.id] || "unmarked",
    }));
    const marksOut = {};
    for (const emp of state.employees) {
      marksOut[emp.id] = state.marks[emp.id] || "unmarked";
    }
    return {
      open: state.open,
      selectedEmployee: state.selectedEmployee,
      certaintyPct: state.certaintyPct,
      p: summary.p,
      visibleV: summary.visibleV,
      breakEvenP: summary.breakEvenP,
      breakEvenPct: summary.breakEvenPct,
      ev: summary.ev,
      positiveEV: summary.positiveEV,
      outcomeCorrect: summary.outcomeCorrect,
      outcomeWrong: summary.outcomeWrong,
      outcomeAbstain: summary.outcomeAbstain,
      employees: employeesOut,
      marks: marksOut,
    };
  }

  function open(nextState) {
    if (nextState && typeof nextState === "object") {
      applyStatePatch(nextState);
    }
    state.open = true;
    render();
    return getState();
  }

  function close() {
    state.open = false;
    syncOpenAttributes();
    return getState();
  }

  function update(nextState) {
    if (nextState && typeof nextState === "object") {
      applyStatePatch(nextState);
    }
    render();
    return getState();
  }

  render();

  return {
    element: rootEl,
    open,
    close,
    update,
    getState,
  };
}

if (typeof globalThis !== "undefined" && globalThis && typeof globalThis === "object") {
  globalThis.CanaryAccuseModal = {
    WRONG_ACCUSE_PENALTY,
    ABSTAIN_REWARD,
    computeAccuseDecisionSummary,
    createAccuseModal,
  };
}
