import { el, clear, pad2, fmtScore, TOOL_GROUPS, TOOL_DEFS } from "./dom.js";

export const INTERVIEW_TOPICS = [
  { id: "recent_documents", label: "Recent documents" },
  { id: "contacts_outside", label: "Contacts outside" },
  { id: "workload", label: "Workload" },
  { id: "access_needs", label: "Access needs" },
];

export const VARIANT_LABELS = ["A", "B", "C"];

const VALID_MODES = new Set(["duel", "solver", "living", "mole"]);
const VALID_TOPIC_IDS = new Set(INTERVIEW_TOPICS.map((t) => t.id));
const ALWAYS_FORBIDDEN_KEYS = new Set([
  "mole",
  "mole_id",
  "moleId",
  "true_v",
  "trueV",
]);
const MOLE_MODE_FORBIDDEN_KEYS = new Set([
  "mole",
  "mole_id",
  "moleId",
  "true_v",
  "trueV",
  "is_canary",
  "isCanary",
  "variant",
  "variants",
]);

export function computeBreakEven(visibleV) {
  const v = Number.isFinite(Number(visibleV)) ? Math.max(0, Number(visibleV)) : 1.0;
  return 1 / (1 + v);
}

export function computeAccuseEV(p, visibleV) {
  const prob = Number.isFinite(Number(p)) ? Math.min(1, Math.max(0, Number(p))) : 0.5;
  const v = Number.isFinite(Number(visibleV)) ? Math.max(0, Number(visibleV)) : 1.0;
  return prob * v - (1 - prob);
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

function sanitizeEmployee(raw) {
  if (!raw || typeof raw !== "object") return null;
  const id = String(raw.id === undefined || raw.id === null ? "" : raw.id).trim();
  if (!id) return null;
  const clean = {
    id,
    name: String(raw.name === undefined || raw.name === null ? id : raw.name),
    dept: String(raw.dept === undefined || raw.dept === null ? "" : raw.dept),
    role: String(raw.role === undefined || raw.role === null ? "" : raw.role),
  };
  if (raw.clearance !== undefined && raw.clearance !== null) {
    const cl = Number(raw.clearance);
    if (Number.isFinite(cl)) {
      clean.clearance = Math.trunc(cl);
    }
  }
  return clean;
}

function sanitizeMoleCandidateDoc(raw, fallbackDay) {
  if (!raw || typeof raw !== "object") return null;
  const docId = String(raw.doc_id === undefined || raw.doc_id === null ? "" : raw.doc_id).trim();
  if (!docId) return null;
  const dayNum = Number(raw.day);
  const recNum = Number(raw.recipient_count);
  const recipientCount = Number.isFinite(recNum)
    ? Math.max(0, Math.trunc(recNum))
    : Array.isArray(raw.recipients)
      ? raw.recipients.length
      : 0;
  return {
    doc_id: docId,
    title: String(raw.title === undefined || raw.title === null ? docId : raw.title),
    day: Number.isFinite(dayNum) && dayNum >= 1 ? Math.trunc(dayNum) : fallbackDay,
    recipient_count: recipientCount,
  };
}

function normalizePlantedCanary(raw) {
  if (!raw || typeof raw !== "object") return null;
  const cid = String(raw.id || raw.canary_id || raw.doc_id || "").trim();
  if (!cid) return null;
  const groups = {};
  const srcGroups = raw.groups || raw.variants;
  if (srcGroups && typeof srcGroups === "object" && !Array.isArray(srcGroups)) {
    for (const [label, members] of Object.entries(srcGroups)) {
      if (Array.isArray(members)) {
        groups[String(label)] = members.map((m) => String(m));
      }
    }
  } else if (raw.assignment && typeof raw.assignment === "object") {
    for (const [empId, label] of Object.entries(raw.assignment)) {
      const lab = String(label);
      if (!groups[lab]) groups[lab] = [];
      groups[lab].push(String(empId));
    }
  }
  return { id: cid, groups };
}

function scrubLogValue(val, forbiddenSet) {
  if (val === null || val === undefined) return val;
  if (Array.isArray(val)) {
    return val.map((item) => scrubLogValue(item, forbiddenSet));
  }
  if (typeof val === "object") {
    const out = {};
    for (const [k, v] of Object.entries(val)) {
      if (forbiddenSet.has(k)) continue;
      out[k] = scrubLogValue(v, forbiddenSet);
    }
    return out;
  }
  return val;
}

function formatArgsSummary(args) {
  if (!args || typeof args !== "object") return "";
  const parts = [];
  for (const [k, v] of Object.entries(args)) {
    if (v === undefined) continue;
    const rendered = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
    parts.push(k + "=" + rendered);
  }
  return parts.join(" ");
}

export function createHumanDesk(opts = {}) {
  const doc = (opts && opts.document) || (typeof globalThis !== "undefined" ? globalThis.document : null);
  if (!doc) {
    throw new Error("No document available for createHumanDesk");
  }

  const onRunTool = typeof opts.onRunTool === "function" ? opts.onRunTool : null;
  const onMoleStep = typeof opts.onMoleStep === "function" ? opts.onMoleStep : null;
  const onSelectEmployee = typeof opts.onSelectEmployee === "function" ? opts.onSelectEmployee : null;
  const onMarkEmployee = typeof opts.onMarkEmployee === "function" ? opts.onMarkEmployee : null;

  function h(tag, attrs, ...children) {
    const nextAttrs = attrs && typeof attrs === "object" ? { ...attrs, document: doc } : { document: doc };
    return el(tag, nextAttrs, ...children);
  }

  function setText(node, text) {
    clear(node);
    const str = String(text === null || text === undefined ? "" : text);
    const tNode =
      doc && typeof doc.createTextNode === "function"
        ? doc.createTextNode(str)
        : { nodeType: 3, textContent: str, nodeValue: str, data: str };
    if (typeof node.appendChild === "function") {
      node.appendChild(tNode);
    } else if (Array.isArray(node.childNodes)) {
      node.childNodes.push(tNode);
    }
    return node;
  }

  const state = {
    seed: null,
    mode: "duel",
    day: 1,
    nDays: 14,
    visibleV: 1.0,
    done: false,
    maxVariants: 3,
    selectedTool: "list_employees",
    selectedEmployee: null,
    selectedLeakDocId: null,
    certaintyPct: 50,
    marks: {},
    canaryAssignment: {},
    restricted: new Set(),
    employees: [],
    plantedCanaries: [],
    moleCandidateDocs: [],
  };

  const draft = {
    day_from: null,
    day_to: null,
    log_day_from: null,
    log_day_to: null,
    log_employee: "",
    query: "",
    msg_id: "",
    topic: INTERVIEW_TOPICS[0].id,
    doc_title: "",
    confirm_employee: "",
  };

  let logEntries = [];
  let nextCallSeq = 1;
  let formControls = {};

  const rootEl = h("div", { class: "human-desk pane-human" });
  const workspaceHostEl = h("div", { class: "human-desk-workspace" });
  const caseLogEl = h("div", { class: "case-log" });
  rootEl.appendChild(workspaceHostEl);
  rootEl.appendChild(caseLogEl);

  function syncDraftFromControls() {
    if (formControls.doc_title && formControls.doc_title.value !== undefined) {
      draft.doc_title = String(formControls.doc_title.value);
    }
    if (formControls.query && formControls.query.value !== undefined) {
      draft.query = String(formControls.query.value);
    }
    if (formControls.msg_id && formControls.msg_id.value !== undefined) {
      draft.msg_id = String(formControls.msg_id.value);
    }
    if (formControls.topic && formControls.topic.value !== undefined) {
      const t = String(formControls.topic.value);
      if (VALID_TOPIC_IDS.has(t)) draft.topic = t;
    }
    if (formControls.confirm_employee && formControls.confirm_employee.value !== undefined) {
      draft.confirm_employee = String(formControls.confirm_employee.value);
    }
    if (formControls.certainty && formControls.certainty.value !== undefined) {
      const c = Number(formControls.certainty.value);
      if (Number.isFinite(c)) {
        state.certaintyPct = Math.min(100, Math.max(0, Math.round(c)));
      }
    }
  }

  function canaryPillsForEmployee(empId) {
    const pills = [];
    for (const c of state.plantedCanaries) {
      for (const [label, ids] of Object.entries(c.groups)) {
        if (ids.includes(empId)) {
          pills.push(c.id + ":" + label);
        }
      }
    }
    if (state.selectedTool === "plant_canary" && state.canaryAssignment[empId]) {
      pills.push(state.canaryAssignment[empId]);
    }
    return pills;
  }

  function defaultTargetEmployee() {
    if (state.selectedEmployee) return state.selectedEmployee;
    if (state.employees.length > 0) return state.employees[0].id;
    return "";
  }

  function buildEmployeeControl(fieldName, allowEmpty, initialVal, onChangeFn) {
    if (state.employees.length === 0) {
      const inp = withValue(
        h("input", {
          type: "text",
          name: fieldName,
          class: "mono",
          placeholder: allowEmpty ? "optional e00" : "e00",
          onInput: (ev) => {
            if (onChangeFn) onChangeFn(ev);
          },
        }),
        initialVal || ""
      );
      return inp;
    }

    const options = [];
    if (allowEmpty) {
      options.push(withValue(h("option", { value: "" }, "everyone"), ""));
    }
    let matched = false;
    for (const emp of state.employees) {
      const isSel = emp.id === initialVal;
      if (isSel) matched = true;
      options.push(
        withValue(
          h("option", { value: emp.id, selected: isSel }, emp.id + " - " + emp.name),
          emp.id
        )
      );
    }
    const effectiveVal = matched
      ? initialVal
      : allowEmpty
        ? ""
        : state.employees[0].id;
    const sel = withValue(
      h(
        "select",
        {
          name: fieldName,
          onChange: (ev) => {
            if (onChangeFn) onChangeFn(ev);
          },
          onInput: (ev) => {
            if (onChangeFn) onChangeFn(ev);
          },
        },
        options
      ),
      effectiveVal
    );
    return sel;
  }

  function buildDayInput(fieldName, initialVal, maxVal) {
    const clamped = Math.max(1, Math.min(maxVal, Math.trunc(Number(initialVal) || 1)));
    return withValue(
      h("input", {
        type: "number",
        name: fieldName,
        min: 1,
        max: maxVal,
        step: 1,
      }),
      clamped
    );
  }

  function wrapLabel(caption, controlNode) {
    return h("label", {}, h("span", { class: "lbl" }, caption), controlNode);
  }

  function applyEvenSplit() {
    if (state.done || state.employees.length === 0) return;
    syncDraftFromControls();
    const labels = VARIANT_LABELS.slice(0, Math.max(1, Math.min(3, state.maxVariants)));
    const pool = state.employees.filter((emp) => !state.restricted.has(emp.id));
    const nextAssign = {};
    pool.forEach((emp, idx) => {
      nextAssign[emp.id] = labels[idx % labels.length];
    });
    state.canaryAssignment = nextAssign;
    renderWorkspace();
  }

  function submitCurrentTool() {
    if (state.done || state.mode === "mole") return;
    const toolName = state.selectedTool;
    if (!toolName || !TOOL_DEFS[toolName]) return;

    switch (toolName) {
      case "status":
      case "list_employees":
      case "check_leak_feed":
      case "advance_day": {
        if (onRunTool) onRunTool(toolName, {});
        return;
      }
      case "list_documents": {
        const fromVal = Number(formControls.day_from ? formControls.day_from.value : 1);
        const toVal = Number(formControls.day_to ? formControls.day_to.value : state.day);
        const dayFrom = Number.isFinite(fromVal) ? Math.trunc(fromVal) : 1;
        const dayTo = Number.isFinite(toVal) ? Math.trunc(toVal) : state.day;
        draft.day_from = dayFrom;
        draft.day_to = dayTo;
        if (onRunTool) onRunTool("list_documents", { day_from: dayFrom, day_to: dayTo });
        return;
      }
      case "read_access_logs": {
        const closedDay = Math.max(1, state.day - 1);
        const fromVal = Number(formControls.day_from ? formControls.day_from.value : 1);
        const toVal = Number(formControls.day_to ? formControls.day_to.value : closedDay);
        const dayFrom = Number.isFinite(fromVal) ? Math.trunc(fromVal) : 1;
        const dayTo = Number.isFinite(toVal) ? Math.trunc(toVal) : closedDay;
        const empVal = String(formControls.employee ? formControls.employee.value : "").trim();
        draft.log_day_from = dayFrom;
        draft.log_day_to = dayTo;
        draft.log_employee = empVal;
        const args = { day_from: dayFrom, day_to: dayTo };
        if (empVal) args.employee = empVal;
        if (onRunTool) onRunTool("read_access_logs", args);
        return;
      }
      case "search_messages": {
        const query = String(formControls.query ? formControls.query.value : draft.query).trim();
        draft.query = query;
        if (!query) return;
        const fromVal = Number(formControls.day_from ? formControls.day_from.value : 1);
        const toVal = Number(formControls.day_to ? formControls.day_to.value : state.day);
        const dayFrom = Number.isFinite(fromVal) ? Math.trunc(fromVal) : 1;
        const dayTo = Number.isFinite(toVal) ? Math.trunc(toVal) : state.day;
        if (onRunTool) {
          onRunTool("search_messages", { query, day_from: dayFrom, day_to: dayTo });
        }
        return;
      }
      case "read_message": {
        const msgId = String(formControls.msg_id ? formControls.msg_id.value : draft.msg_id).trim();
        draft.msg_id = msgId;
        if (!msgId) return;
        if (onRunTool) onRunTool("read_message", { id: msgId });
        return;
      }
      case "interview": {
        const empVal = String(
          formControls.employee ? formControls.employee.value : defaultTargetEmployee()
        ).trim();
        const topicVal = String(
          formControls.topic ? formControls.topic.value : draft.topic
        ).trim();
        if (!empVal || !VALID_TOPIC_IDS.has(topicVal)) return;
        draft.topic = topicVal;
        if (onRunTool) onRunTool("interview", { employee: empVal, topic: topicVal });
        return;
      }
      case "plant_canary": {
        const titleVal = String(
          formControls.doc_title ? formControls.doc_title.value : draft.doc_title
        ).trim();
        draft.doc_title = titleVal;
        const assignment = {};
        for (const [empId, lab] of Object.entries(state.canaryAssignment)) {
          if (!state.restricted.has(empId) && lab) {
            assignment[empId] = String(lab);
          }
        }
        if (!titleVal || Object.keys(assignment).length === 0) return;
        if (onRunTool) {
          onRunTool("plant_canary", { doc_title: titleVal, assignment });
        }
        return;
      }
      case "restrict_access":
      case "unrestrict_access": {
        const empVal = String(
          formControls.employee ? formControls.employee.value : defaultTargetEmployee()
        ).trim();
        if (!empVal) return;
        if (onRunTool) onRunTool(toolName, { employee: empVal });
        return;
      }
      case "accuse": {
        const empVal = String(
          formControls.employee ? formControls.employee.value : defaultTargetEmployee()
        ).trim();
        const armVal = String(
          formControls.confirm_employee ? formControls.confirm_employee.value : draft.confirm_employee
        ).trim();
        draft.confirm_employee = armVal;
        if (!empVal || armVal !== empVal) return;
        if (onRunTool) onRunTool("accuse", { employee: empVal });
        return;
      }
      default:
        return;
    }
  }

  function renderStaffRoster() {
    const isCanaryMode = state.selectedTool === "plant_canary";
    const headChildren = [
      h(
        "span",
        {},
        state.employees.length > 0 ? "Staff (" + state.employees.length + ")" : "Staff"
      ),
    ];
    if (isCanaryMode) {
      headChildren.push(h("span", { class: "mono" }, "assign A / B / C"));
    }

    const rowsEl = h("div", { class: "staff-roster-rows" });
    const labels = VARIANT_LABELS.slice(0, Math.max(1, Math.min(3, state.maxVariants)));

    if (state.employees.length === 0) {
      rowsEl.appendChild(
        h(
          "div",
          { class: "staff-empty dim", style: "padding: 10px 12px; font-size: 12px;" },
          "No staff loaded yet. Select Staff list and press Run to pull employees."
        )
      );
    } else {
      for (const emp of state.employees) {
        const mark = state.marks[emp.id] || null;
        const isSelected = state.selectedEmployee === emp.id;
        const isRestricted = state.restricted.has(emp.id);
        const pills = canaryPillsForEmployee(emp.id);

        const metaParts = [];
        if (emp.dept) metaParts.push(emp.dept);
        if (emp.role) metaParts.push(emp.role);
        if (emp.clearance !== undefined) metaParts.push("L" + emp.clearance);

        const badgeRow = [];
        if (isRestricted) {
          badgeRow.push(h("span", { class: "t inv" }, "restricted"));
        }
        for (const pText of pills) {
          badgeRow.push(h("span", { class: "canary-pill" }, pText));
        }

        const suspectOn = mark === "suspect";
        const clearedOn = mark === "cleared";

        const markBtnsEl = h(
          "div",
          { class: "mark-btns" },
          h(
            "button",
            {
              type: "button",
              class: ["mark-btn", "suspect-btn", suspectOn ? "on" : ""],
              "aria-pressed": String(suspectOn),
              dataset: { mark: "suspect", empId: emp.id },
              title: "Toggle suspect note",
              onClick: (ev) => {
                if (ev && typeof ev.stopPropagation === "function") ev.stopPropagation();
                syncDraftFromControls();
                const nextMark = state.marks[emp.id] === "suspect" ? null : "suspect";
                if (nextMark) state.marks[emp.id] = nextMark;
                else delete state.marks[emp.id];
                if (onMarkEmployee) onMarkEmployee(emp.id, nextMark);
                renderWorkspace();
              },
            },
            "S"
          ),
          h(
            "button",
            {
              type: "button",
              class: ["mark-btn", "cleared-btn", clearedOn ? "on" : ""],
              "aria-pressed": String(clearedOn),
              dataset: { mark: "cleared", empId: emp.id },
              title: "Toggle cleared note",
              onClick: (ev) => {
                if (ev && typeof ev.stopPropagation === "function") ev.stopPropagation();
                syncDraftFromControls();
                const nextMark = state.marks[emp.id] === "cleared" ? null : "cleared";
                if (nextMark) state.marks[emp.id] = nextMark;
                else delete state.marks[emp.id];
                if (onMarkEmployee) onMarkEmployee(emp.id, nextMark);
                renderWorkspace();
              },
            },
            "X"
          )
        );

        const rightControls = [markBtnsEl];
        if (isCanaryMode) {
          const variantBtnsEl = h(
            "div",
            { class: "variant-btns" },
            labels.map((lab) => {
              const assigned = state.canaryAssignment[emp.id] === lab;
              return h(
                "button",
                {
                  type: "button",
                  class: ["variant-btn", assigned ? "on" : ""],
                  "aria-pressed": String(assigned),
                  disabled: isRestricted || state.done,
                  dataset: { variant: lab, empId: emp.id },
                  title: isRestricted
                    ? "Restricted employee cannot receive canary"
                    : "Assign variant " + lab + " to " + emp.id,
                  onClick: (ev) => {
                    if (ev && typeof ev.stopPropagation === "function") ev.stopPropagation();
                    if (isRestricted || state.done) return;
                    syncDraftFromControls();
                    if (state.canaryAssignment[emp.id] === lab) {
                      delete state.canaryAssignment[emp.id];
                    } else {
                      state.canaryAssignment[emp.id] = lab;
                    }
                    renderWorkspace();
                  },
                },
                lab
              );
            })
          );
          rightControls.push(variantBtnsEl);
        }

        const rowClasses = ["staff-row"];
        if (isSelected) rowClasses.push("selected");
        if (suspectOn) rowClasses.push("suspect");
        if (clearedOn) rowClasses.push("cleared");

        const rowEl = h(
          "div",
          {
            class: rowClasses,
            "aria-selected": String(isSelected),
            dataset: { empId: emp.id },
            onClick: () => {
              syncDraftFromControls();
              state.selectedEmployee = emp.id;
              if (onSelectEmployee) onSelectEmployee(emp.id);
              renderWorkspace();
            },
          },
          h("span", { class: "emp-id" }, emp.id),
          h(
            "span",
            { class: "emp-info" },
            h("span", { class: "emp-name" }, emp.name),
            h("span", { class: "emp-meta" }, metaParts.join(" / ")),
            badgeRow.length > 0 ? h("span", { class: "emp-badges" }, badgeRow) : null
          ),
          h("span", { class: "emp-actions" }, rightControls)
        );
        rowsEl.appendChild(rowEl);
      }
    }

    return h("div", { class: "staff-roster" }, h("div", { class: "sheet-h" }, headChildren), rowsEl);
  }

  function renderCmdBar() {
    const topRow = h("div", { class: "cmd-row" });
    const bottomRow = h("div", { class: "cmd-row" });

    for (const groupName of TOOL_GROUPS) {
      const groupTools = Object.entries(TOOL_DEFS).filter(([, meta]) => meta.group === groupName);
      if (groupTools.length === 0) continue;

      const groupButtons = groupTools.map(([toolName, meta]) => {
        const isCurrent = state.selectedTool === toolName;
        const costLabel =
          toolName === "accuse" ? "ends case" : meta.costed ? "1 action" : "free";
        return h(
          "button",
          {
            type: "button",
            class: ["tool-btn", toolName === "accuse" ? "accuse" : ""],
            "aria-pressed": String(isCurrent),
            disabled: state.done,
            dataset: { tool: toolName },
            onClick: () => {
              syncDraftFromControls();
              state.selectedTool = toolName;
              renderWorkspace();
            },
          },
          h("span", { class: "code" }, meta.code),
          h("span", { class: "nm" }, meta.name),
          h("span", { class: "cost" }, costLabel)
        );
      });

      const grpEl = h(
        "div",
        {
          class: ["cmd-group", groupName === "Decide" ? "decide" : ""],
          dataset: { group: groupName },
        },
        h("span", { class: "cmd-group-label" }, groupName),
        groupButtons
      );

      if (groupName === "Investigate" || groupName === "Trap") {
        topRow.appendChild(grpEl);
      } else {
        bottomRow.appendChild(grpEl);
      }
    }

    return h("div", { class: "cmd-bar" }, topRow, bottomRow);
  }

  function renderCmdForm() {
    formControls = {};
    const toolName = state.selectedTool;
    const meta = TOOL_DEFS[toolName];
    const formEl = h("form", {
      class: "cmd-form",
      dataset: { activeTool: toolName || "" },
      onSubmit: (ev) => {
        if (ev && typeof ev.preventDefault === "function") ev.preventDefault();
        submitCurrentTool();
      },
    });

    if (!meta) return formEl;

    formEl.appendChild(h("p", { class: "desc" }, meta.desc));

    switch (toolName) {
      case "status":
      case "list_employees":
      case "check_leak_feed":
        break;

      case "advance_day": {
        formEl.appendChild(
          h(
            "span",
            { class: "dim mono" },
            "Closes day " + pad2(state.day) + " of " + pad2(state.nDays) + "."
          )
        );
        break;
      }

      case "list_documents": {
        const fromInp = buildDayInput(
          "day_from",
          draft.day_from !== null ? draft.day_from : 1,
          state.nDays
        );
        const toInp = buildDayInput(
          "day_to",
          draft.day_to !== null ? draft.day_to : state.day,
          state.nDays
        );
        formControls.day_from = fromInp;
        formControls.day_to = toInp;
        formEl.appendChild(wrapLabel("From day", fromInp));
        formEl.appendChild(wrapLabel("To day", toInp));
        break;
      }

      case "read_access_logs": {
        const closedDay = Math.max(1, state.day - 1);
        const defaultFrom =
          draft.log_day_from !== null ? draft.log_day_from : Math.max(1, closedDay - 2);
        const defaultTo = draft.log_day_to !== null ? draft.log_day_to : closedDay;
        const fromInp = buildDayInput("day_from", defaultFrom, state.nDays);
        const toInp = buildDayInput("day_to", defaultTo, state.nDays);
        const empInp = buildEmployeeControl(
          "employee",
          true,
          state.selectedEmployee || draft.log_employee || ""
        );
        formControls.day_from = fromInp;
        formControls.day_to = toInp;
        formControls.employee = empInp;
        formEl.appendChild(wrapLabel("From day", fromInp));
        formEl.appendChild(wrapLabel("To day", toInp));
        formEl.appendChild(wrapLabel("Employee", empInp));
        if (state.day === 1) {
          formEl.appendChild(
            h("span", { class: "dim" }, "No day has closed yet; access logs start after day 1.")
          );
        }
        break;
      }

      case "search_messages": {
        const qInp = withValue(
          h("input", {
            type: "text",
            name: "query",
            maxlength: 200,
            placeholder: "board, Falcon, deadline",
            onInput: () => {
              draft.query = String(qInp.value || "");
            },
          }),
          draft.query
        );
        const fromInp = buildDayInput("day_from", 1, state.nDays);
        const toInp = buildDayInput("day_to", state.day, state.nDays);
        formControls.query = qInp;
        formControls.day_from = fromInp;
        formControls.day_to = toInp;
        formEl.appendChild(wrapLabel("Keyword", qInp));
        formEl.appendChild(wrapLabel("From day", fromInp));
        formEl.appendChild(wrapLabel("To day", toInp));
        break;
      }

      case "read_message": {
        const idInp = withValue(
          h("input", {
            type: "text",
            name: "id",
            class: "mono",
            placeholder: "m1-1",
            onInput: () => {
              draft.msg_id = String(idInp.value || "");
            },
          }),
          draft.msg_id
        );
        formControls.msg_id = idInp;
        formEl.appendChild(wrapLabel("Message id", idInp));
        break;
      }

      case "interview": {
        const empControl = buildEmployeeControl("employee", false, defaultTargetEmployee());
        const topicOptions = INTERVIEW_TOPICS.map((t) =>
          withValue(
            h("option", { value: t.id, selected: t.id === draft.topic }, t.label),
            t.id
          )
        );
        const topicSelect = withValue(
          h(
            "select",
            {
              name: "topic",
              onChange: () => {
                const v = String(topicSelect.value || "");
                if (VALID_TOPIC_IDS.has(v)) draft.topic = v;
              },
              onInput: () => {
                const v = String(topicSelect.value || "");
                if (VALID_TOPIC_IDS.has(v)) draft.topic = v;
              },
            },
            topicOptions
          ),
          draft.topic
        );
        formControls.employee = empControl;
        formControls.topic = topicSelect;
        formEl.appendChild(wrapLabel("Employee", empControl));
        formEl.appendChild(wrapLabel("Topic", topicSelect));
        break;
      }

      case "plant_canary": {
        const titleInp = withValue(
          h("input", {
            type: "text",
            name: "doc_title",
            maxlength: 120,
            placeholder: "Q3 board memo",
            onInput: () => {
              draft.doc_title = String(titleInp.value || "");
            },
          }),
          draft.doc_title
        );
        formControls.doc_title = titleInp;
        formEl.appendChild(wrapLabel("Document title", titleInp));

        const grouped = {};
        for (const [empId, lab] of Object.entries(state.canaryAssignment)) {
          if (state.restricted.has(empId)) continue;
          if (!grouped[lab]) grouped[lab] = [];
          grouped[lab].push(empId);
        }
        const groupKeys = Object.keys(grouped).sort();
        const summaryEl = h("div", { class: "canary-groups mono" });
        if (groupKeys.length === 0) {
          summaryEl.appendChild(
            h("span", { class: "dim" }, "Assign A / B / C on staff rows or press Even split.")
          );
        } else {
          for (const lab of groupKeys) {
            summaryEl.appendChild(
              h("span", { class: "canary-pill" }, lab + ": " + grouped[lab].sort().join(","))
            );
          }
        }
        formEl.appendChild(summaryEl);

        if (state.employees.length > 0) {
          formEl.appendChild(
            h(
              "button",
              {
                type: "button",
                class: "ghost even-split-btn",
                disabled: state.done,
                onClick: () => applyEvenSplit(),
              },
              "Even split"
            )
          );
        }
        break;
      }

      case "restrict_access":
      case "unrestrict_access": {
        const empControl = buildEmployeeControl("employee", false, defaultTargetEmployee());
        formControls.employee = empControl;
        formEl.appendChild(wrapLabel("Employee", empControl));
        break;
      }

      case "accuse": {
        const initialTarget = defaultTargetEmployee();
        const breakEven = computeBreakEven(state.visibleV);
        const initialP = state.certaintyPct / 100;
        const initialEv = computeAccuseEV(initialP, state.visibleV);

        const pTextNode = h("span", { class: "mono accuse-p" }, state.certaintyPct + "%");
        const visVNode = h(
          "span",
          { class: "mono accuse-visible-v" },
          state.visibleV.toFixed(2)
        );
        const beNode = h(
          "span",
          {
            class: "mono accuse-breakeven",
            dataset: { breakeven: breakEven.toFixed(6) },
          },
          (breakEven * 100).toFixed(1) + "%"
        );
        const evNode = h(
          "span",
          {
            class: "mono accuse-ev",
            dataset: { ev: initialEv.toFixed(6) },
          },
          fmtScore(initialEv)
        );

        let accuseBtn = null;
        let empControl = null;
        let armInp = null;

        const syncAccuseCalcAndArm = () => {
          const pctRaw = Number(
            formControls.certainty ? formControls.certainty.value : state.certaintyPct
          );
          if (Number.isFinite(pctRaw)) {
            state.certaintyPct = Math.min(100, Math.max(0, Math.round(pctRaw)));
          }
          const p = state.certaintyPct / 100;
          const be = computeBreakEven(state.visibleV);
          const ev = computeAccuseEV(p, state.visibleV);
          setText(pTextNode, state.certaintyPct + "%");
          setText(visVNode, state.visibleV.toFixed(2));
          setText(beNode, (be * 100).toFixed(1) + "%");
          if (typeof beNode.setAttribute === "function") {
            beNode.setAttribute("data-breakeven", be.toFixed(6));
          }
          if (beNode.dataset) beNode.dataset.breakeven = be.toFixed(6);
          setText(evNode, fmtScore(ev));
          if (typeof evNode.setAttribute === "function") {
            evNode.setAttribute("data-ev", ev.toFixed(6));
          }
          if (evNode.dataset) evNode.dataset.ev = ev.toFixed(6);

          const targetId = String(empControl ? empControl.value : "").trim();
          const armVal = String(armInp ? armInp.value : "").trim();
          draft.confirm_employee = armVal;
          const armed = !state.done && Boolean(targetId) && armVal === targetId;
          if (accuseBtn) {
            accuseBtn.disabled = !armed;
            if (typeof accuseBtn.setAttribute === "function") {
              if (!armed) accuseBtn.setAttribute("disabled", "");
              else if (typeof accuseBtn.removeAttribute === "function") {
                accuseBtn.removeAttribute("disabled");
              }
            }
            setText(accuseBtn, targetId ? "Accuse " + targetId : "Accuse");
          }
        };

        empControl = buildEmployeeControl("employee", false, initialTarget, () => {
          syncAccuseCalcAndArm();
        });

        const certaintyInp = withValue(
          h("input", {
            type: "range",
            name: "certainty",
            min: 0,
            max: 100,
            step: 1,
            onInput: () => syncAccuseCalcAndArm(),
            onChange: () => syncAccuseCalcAndArm(),
          }),
          state.certaintyPct
        );

        armInp = withValue(
          h("input", {
            type: "text",
            name: "confirm_employee",
            class: "mono accuse-arm-input",
            placeholder: initialTarget ? "type " + initialTarget + " to arm" : "type id to arm",
            onInput: () => syncAccuseCalcAndArm(),
            onChange: () => syncAccuseCalcAndArm(),
          }),
          draft.confirm_employee
        );

        const initiallyArmed =
          !state.done &&
          Boolean(initialTarget) &&
          draft.confirm_employee.trim() === initialTarget;

        accuseBtn = h(
          "button",
          {
            type: "button",
            class: "danger run accuse-submit",
            disabled: !initiallyArmed,
            onClick: () => submitCurrentTool(),
          },
          initialTarget ? "Accuse " + initialTarget : "Accuse"
        );

        formControls.employee = empControl;
        formControls.certainty = certaintyInp;
        formControls.confirm_employee = armInp;
        formControls.runBtn = accuseBtn;

        const calcBox = h(
          "div",
          { class: "accuse-calc", style: "flex: 1 1 100%; display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 12px;" },
          h("span", {}, "Visible V: ", visVNode),
          h("span", {}, "Break-even 1/(1+V): ", beNode),
          h("span", {}, "Certainty p: ", pTextNode),
          h("span", {}, "EV p*V-(1-p): ", evNode)
        );

        formEl.appendChild(wrapLabel("Suspect", empControl));
        formEl.appendChild(wrapLabel("Certainty (%)", certaintyInp));
        formEl.appendChild(wrapLabel("Type id to arm", armInp));
        formEl.appendChild(calcBox);
        formEl.appendChild(accuseBtn);
        return formEl;
      }

      default:
        break;
    }

    const costSuffix = meta.costed ? "1 action" : "free";
    const runBtn = h(
      "button",
      {
        type: "button",
        class: "primary run",
        disabled: state.done,
        onClick: () => submitCurrentTool(),
      },
      "Run " + meta.name.toLowerCase() + " (" + costSuffix + ")"
    );
    formControls.runBtn = runBtn;
    formEl.appendChild(runBtn);
    return formEl;
  }

  function renderInvestigatorGrid() {
    return h(
      "div",
      { class: "human-desk-grid" },
      renderStaffRoster(),
      h("div", { class: "cmd-panel" }, renderCmdBar(), renderCmdForm())
    );
  }

  function renderMolePanel() {
    const gridEl = h("div", { class: "leak-picker-grid", role: "listbox" });

    const holdSelected = state.selectedLeakDocId === null;
    const holdCard = h(
      "div",
      {
        class: "leak-picker-card hold-card",
        role: "option",
        tabindex: "0",
        "aria-selected": String(holdSelected),
        dataset: { leakDocId: "" },
        onClick: () => {
          if (state.done) return;
          state.selectedLeakDocId = null;
          renderWorkspace();
        },
      },
      h("div", { class: "mono dim" }, "HOLD"),
      h("strong", {}, "Hold Tonight (Do Not Leak)"),
      h("span", { class: "dim" }, "Stay quiet overnight while the Bayesian solver updates.")
    );
    gridEl.appendChild(holdCard);

    for (const cand of state.moleCandidateDocs) {
      const isSelected = state.selectedLeakDocId === cand.doc_id;
      const recLabel =
        cand.recipient_count === 1 ? "1 recipient" : cand.recipient_count + " recipients";
      const card = h(
        "div",
        {
          class: "leak-picker-card",
          role: "option",
          tabindex: "0",
          "aria-selected": String(isSelected),
          dataset: { leakDocId: cand.doc_id },
          onClick: () => {
            if (state.done) return;
            state.selectedLeakDocId = cand.doc_id;
            renderWorkspace();
          },
        },
        h(
          "div",
          { style: "display: flex; justify-content: space-between; gap: 6px;" },
          h("span", { class: "mono" }, cand.doc_id),
          h("span", { class: "t dim" }, "D" + pad2(cand.day))
        ),
        h("strong", {}, cand.title),
        h("span", { class: "dim mono" }, recLabel)
      );
      gridEl.appendChild(card);
    }

    const commitText = state.selectedLeakDocId
      ? "Commit Overnight Leak (" + state.selectedLeakDocId + ")"
      : "Commit Hold Tonight";

    const commitBtn = h(
      "button",
      {
        type: "button",
        class: [state.selectedLeakDocId ? "danger" : "primary", "mole-commit-btn"],
        disabled: state.done,
        onClick: () => {
          if (state.done) return;
          if (onMoleStep) {
            onMoleStep({ leakDocId: state.selectedLeakDocId });
          }
        },
      },
      commitText
    );

    return h(
      "div",
      { class: "mole-panel" },
      h(
        "div",
        { class: "sheet-h" },
        h("span", {}, "Be the Mole - Day " + pad2(state.day)),
        h("span", { class: "mono" }, state.moleCandidateDocs.length + " eligible docs")
      ),
      h(
        "p",
        { class: "dim", style: "margin: 0; font-size: 12.5px;" },
        "Pick one document you hold to leak overnight, or hold tonight."
      ),
      gridEl,
      h("div", { class: "mole-actions", style: "display: flex; justify-content: flex-end;" }, commitBtn)
    );
  }

  function renderWorkspace() {
    clear(workspaceHostEl);
    if (state.mode === "mole") {
      formControls = {};
      workspaceHostEl.appendChild(renderMolePanel());
    } else {
      workspaceHostEl.appendChild(renderInvestigatorGrid());
    }
  }

  function renderLogEntryBody(entry) {
    if (!entry.ok) {
      const detail =
        entry.data && typeof entry.data.detail === "string" ? " (" + entry.data.detail + ")" : "";
      return h("p", {}, h("strong", {}, "Rejected: "), String(entry.error || "invalid call") + detail);
    }

    const d = entry.data || {};
    switch (entry.tool) {
      case "check_leak_feed": {
        const items = Array.isArray(d.items) ? d.items : [];
        if (items.length === 0) {
          return h("p", {}, "Nothing has surfaced in the leak feed yet.");
        }
        return h(
          "div",
          { style: "display: flex; flex-direction: column; gap: 6px;" },
          items.map((it) => {
            const leftParts = [
              h("strong", { class: "mono" }, String(it.doc_id || "")),
              " ",
              String(it.title || ""),
            ];
            if (it.variant && state.mode !== "mole") {
              leftParts.push(" ");
              leftParts.push(h("span", { class: "canary-pill" }, "variant " + String(it.variant)));
            }
            const surfDay = it.surfaced_day !== undefined ? "surfaced D" + pad2(it.surfaced_day) : "surfaced";
            return h(
              "div",
              { class: "leak-alert" },
              h("span", {}, leftParts),
              h("span", { class: "mono" }, surfDay)
            );
          })
        );
      }

      case "status": {
        const restrictedList = Array.isArray(d.restricted) && d.restricted.length > 0
          ? d.restricted.join(", ")
          : "none";
        const canaryList = Array.isArray(d.canaries_planted) && d.canaries_planted.length > 0
          ? d.canaries_planted.join(", ")
          : "none";
        const visVal = Number.isFinite(Number(d.V)) ? Number(d.V).toFixed(2) : state.visibleV.toFixed(2);
        return h(
          "div",
          { class: "mono", style: "display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 12px;" },
          h("span", {}, "Day " + pad2(d.day !== undefined ? d.day : state.day)),
          h("span", {}, "V=" + visVal),
          h("span", {}, "Actions left=" + String(d.actions_left_today ?? "")),
          h("span", {}, "Calls left=" + String(d.tool_calls_left ?? "")),
          h("span", {}, "Restricted=" + restrictedList),
          h("span", {}, "Canaries=" + canaryList)
        );
      }

      case "list_employees": {
        const emps = Array.isArray(d.employees) ? d.employees : [];
        return h("p", {}, emps.length + " employees loaded into the staff roster.");
      }

      case "list_documents": {
        const docs = Array.isArray(d.documents) ? d.documents : [];
        if (docs.length === 0) return h("p", {}, "No documents published in that day range.");
        return h(
          "div",
          { style: "display: flex; flex-direction: column; gap: 4px;" },
          docs.map((docItem) => {
            const recips = Array.isArray(docItem.recipients) ? docItem.recipients : [];
            return h(
              "div",
              { style: "display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;" },
              h("span", { class: "mono" }, String(docItem.doc_id || "")),
              docItem.is_canary && state.mode !== "mole"
                ? h("span", { class: "canary-pill" }, "canary")
                : null,
              h("strong", {}, String(docItem.title || "")),
              h("span", { class: "mono dim" }, "D" + pad2(docItem.day) + " (" + recips.length + " to: " + recips.join(" ") + ")")
            );
          })
        );
      }

      case "read_access_logs": {
        const logs = Array.isArray(d.logs) ? d.logs : [];
        if (logs.length === 0) return h("p", {}, "No access log entries in that range.");
        const ahCount = logs.filter((r) => Boolean(r.after_hours)).length;
        return h(
          "div",
          { style: "display: flex; flex-direction: column; gap: 4px;" },
          h("div", { class: "dim" }, logs.length + " opens (" + ahCount + " after-hours)."),
          logs.map((row) =>
            h(
              "div",
              { class: "mono", style: "font-size: 12px;" },
              "D" + pad2(row.day) + " " + String(row.employee || "") + " -> " + String(row.doc_id || ""),
              row.after_hours ? " " : null,
              row.after_hours ? h("span", { class: "t red" }, "AH") : null
            )
          )
        );
      }

      case "search_messages": {
        const msgs = Array.isArray(d.messages) ? d.messages : [];
        if (msgs.length === 0) return h("p", {}, "No messages matched query.");
        return h(
          "div",
          { style: "display: flex; flex-direction: column; gap: 5px;" },
          msgs.map((m) =>
            h(
              "div",
              { style: "display: flex; flex-wrap: wrap; gap: 6px; align-items: baseline;" },
              h("span", { class: "mono dim" }, String(m.id || "")),
              h("span", { class: "mono" }, "D" + pad2(m.day)),
              h("span", { class: "mono dim" }, String(m.sender || "")),
              h("strong", {}, String(m.subject || "(no subject)")),
              h("span", { class: "dim" }, String(m.snippet || "")),
              h(
                "button",
                {
                  type: "button",
                  class: "ghost",
                  disabled: state.done,
                  onClick: () => {
                    syncDraftFromControls();
                    draft.msg_id = String(m.id || "");
                    state.selectedTool = "read_message";
                    renderWorkspace();
                  },
                },
                "Select id"
              )
            )
          )
        );
      }

      case "read_message": {
        const m = d.message && typeof d.message === "object" ? d.message : {};
        const recips = Array.isArray(m.recipients) ? m.recipients.join(", ") : "";
        return h(
          "div",
          { style: "display: flex; flex-direction: column; gap: 4px;" },
          h(
            "div",
            { class: "mono dim" },
            "From " + String(m.sender || "") + " to [" + recips + "] on D" + pad2(m.day) + " (" + String(m.channel || "mail") + ")"
          ),
          h("strong", {}, String(m.subject || "(no subject)")),
          h("p", { style: "margin: 0;" }, String(m.body || ""))
        );
      }

      case "interview": {
        return h(
          "div",
          {},
          h(
            "div",
            { class: "mono dim" },
            String(d.employee || entry.args.employee || "") + " / " + String(d.topic || entry.args.topic || "")
          ),
          h("p", { style: "margin: 4px 0 0;" }, String(d.answer || ""))
        );
      }

      case "plant_canary": {
        return h(
          "p",
          {},
          "Planted canary ",
          h("span", { class: "canary-pill" }, String(d.canary_id || "")),
          " (" + String(entry.args.doc_title || "") + ")."
        );
      }

      case "restrict_access": {
        return h(
          "p",
          {},
          "Restricted access for ",
          h("span", { class: "mono" }, String(d.restricted || entry.args.employee || "")),
          "."
        );
      }

      case "unrestrict_access": {
        return h(
          "p",
          {},
          "Lifted access restriction for ",
          h("span", { class: "mono" }, String(d.unrestricted || entry.args.employee || "")),
          "."
        );
      }

      case "advance_day": {
        if (d.episode_over) {
          return h("p", {}, "Day " + String(d.closed_day ?? state.day) + " closed. Horizon reached.");
        }
        const vStr = Number.isFinite(Number(d.V)) ? Number(d.V).toFixed(2) : state.visibleV.toFixed(2);
        const newDocs = Array.isArray(d.new_documents) ? d.new_documents.join(" ") : "";
        return h(
          "p",
          {},
          "Day " + String(d.closed_day ?? "") + " closed. Day " + String(d.day ?? state.day) + " opens at V=" + vStr + (newDocs ? " (" + newDocs + ")." : ".")
        );
      }

      case "accuse": {
        return h(
          "p",
          {},
          "Accused ",
          h("strong", { class: "mono" }, String(d.accused || entry.args.employee || "")),
          ". Episode closed."
        );
      }

      default: {
        if (Array.isArray(d.items) && d.items.length > 0) {
          return h(
            "div",
            { style: "display: flex; flex-direction: column; gap: 6px;" },
            d.items.map((it) =>
              h(
                "div",
                { class: "leak-alert" },
                h("span", {}, h("strong", { class: "mono" }, String(it.doc_id || "")), " ", String(it.title || "")),
                h("span", { class: "mono" }, "D" + pad2(it.surfaced_day || entry.day))
              )
            )
          );
        }
        return h("pre", { class: "mono", style: "margin: 0; white-space: pre-wrap;" }, JSON.stringify(d));
      }
    }
  }

  function renderCaseLog() {
    clear(caseLogEl);
    for (let i = logEntries.length - 1; i >= 0; i -= 1) {
      const entry = logEntries[i];
      const meta = TOOL_DEFS[entry.tool] || { code: "LOG", name: entry.tool, costed: false };
      const isStale = entry.day < state.day;
      const isErr = !entry.ok;
      const entryClasses = ["log-entry"];
      if (isStale) entryClasses.push("stale");
      if (isErr) entryClasses.push("err");

      const rawPayload = JSON.stringify(
        {
          call: { tool: entry.tool, arguments: entry.args },
          result: { ok: entry.ok, data: entry.data, error: entry.error },
        },
        null,
        2
      );

      const node = h(
        "article",
        {
          class: entryClasses,
          dataset: { day: entry.day, tool: entry.tool },
        },
        h(
          "div",
          { class: "log-entry-head" },
          h("span", { class: "mono dim" }, "D" + pad2(entry.day) + " : " + entry.seq),
          h("span", { class: "t inv" }, meta.code),
          h("strong", {}, meta.name),
          h("span", { class: "mono dim" }, formatArgsSummary(entry.args)),
          h(
            "span",
            { style: "margin-left: auto;" },
            entry.ok
              ? h("span", { class: "t dim" }, meta.costed ? "1 action" : "free")
              : h("span", { class: "t red" }, "rejected")
          )
        ),
        h("div", { class: "log-entry-body" }, renderLogEntryBody(entry)),
        h("pre", { class: "log-raw" }, rawPayload)
      );
      caseLogEl.appendChild(node);
    }
  }

  function update(rawState = {}) {
    if (!rawState || typeof rawState !== "object") {
      renderWorkspace();
      renderCaseLog();
      return;
    }

    syncDraftFromControls();

    if (rawState.seed !== undefined && rawState.seed !== null) {
      if (state.seed !== null && rawState.seed !== state.seed) {
        state.marks = {};
        state.canaryAssignment = {};
        state.plantedCanaries = [];
        state.selectedEmployee = null;
        state.selectedLeakDocId = null;
        draft.confirm_employee = "";
        draft.doc_title = "";
      }
      state.seed = rawState.seed;
    }

    if (rawState.done !== undefined) {
      state.done = Boolean(rawState.done);
    }

    if (typeof rawState.mode === "string" && VALID_MODES.has(rawState.mode)) {
      state.mode = rawState.mode;
      if (state.mode === "mole" && !state.done) {
        state.plantedCanaries = [];
        state.canaryAssignment = {};
      }
    }

    if (rawState.day !== undefined && Number.isFinite(Number(rawState.day))) {
      state.day = Math.max(1, Math.trunc(Number(rawState.day)));
    }

    if (rawState.nDays !== undefined && Number.isFinite(Number(rawState.nDays))) {
      state.nDays = Math.max(1, Math.trunc(Number(rawState.nDays)));
    }

    if (rawState.visibleV !== undefined && Number.isFinite(Number(rawState.visibleV))) {
      state.visibleV = Math.max(0, Number(rawState.visibleV));
    }

    if (rawState.maxVariants !== undefined && Number.isFinite(Number(rawState.maxVariants))) {
      state.maxVariants = Math.max(1, Math.min(3, Math.trunc(Number(rawState.maxVariants))));
    }

    if (typeof rawState.selectedTool === "string" && TOOL_DEFS[rawState.selectedTool]) {
      state.selectedTool = rawState.selectedTool;
    }

    if (rawState.certaintyPct !== undefined && Number.isFinite(Number(rawState.certaintyPct))) {
      state.certaintyPct = Math.min(100, Math.max(0, Math.round(Number(rawState.certaintyPct))));
    }

    const rawEmps = Array.isArray(rawState.employees)
      ? rawState.employees
      : Array.isArray(rawState.staff)
        ? rawState.staff
        : null;
    if (rawEmps !== null) {
      state.employees = rawEmps.map(sanitizeEmployee).filter(Boolean);
    }

    if (rawState.restricted !== undefined) {
      const items = rawState.restricted instanceof Set
        ? [...rawState.restricted]
        : Array.isArray(rawState.restricted)
          ? rawState.restricted
          : [];
      state.restricted = new Set(items.map((id) => String(id)));
      for (const rId of state.restricted) {
        delete state.canaryAssignment[rId];
      }
    }

    if (rawState.marks && typeof rawState.marks === "object") {
      const cleanMarks = {};
      for (const [empId, m] of Object.entries(rawState.marks)) {
        if (m === "suspect" || m === "cleared") {
          cleanMarks[String(empId)] = m;
        }
      }
      state.marks = cleanMarks;
    }

    if (rawState.canaryAssignment && typeof rawState.canaryAssignment === "object") {
      const cleanAsg = {};
      for (const [empId, lab] of Object.entries(rawState.canaryAssignment)) {
        const sLab = String(lab);
        if (VARIANT_LABELS.includes(sLab) && !state.restricted.has(empId)) {
          cleanAsg[String(empId)] = sLab;
        }
      }
      state.canaryAssignment = cleanAsg;
    }

    if (Array.isArray(rawState.canaries) && state.mode !== "mole") {
      state.plantedCanaries = rawState.canaries.map(normalizePlantedCanary).filter(Boolean);
    }

    if (rawState.selectedEmployee !== undefined) {
      state.selectedEmployee =
        rawState.selectedEmployee === null ? null : String(rawState.selectedEmployee);
    } else if (
      state.selectedEmployee &&
      state.employees.length > 0 &&
      !state.employees.some((e) => e.id === state.selectedEmployee)
    ) {
      state.selectedEmployee = null;
    }

    if (Array.isArray(rawState.moleCandidateDocs)) {
      state.moleCandidateDocs = rawState.moleCandidateDocs
        .map((d) => sanitizeMoleCandidateDoc(d, state.day))
        .filter(Boolean);
      if (
        state.selectedLeakDocId !== null &&
        !state.moleCandidateDocs.some((d) => d.doc_id === state.selectedLeakDocId)
      ) {
        state.selectedLeakDocId = null;
      }
    }

    if (rawState.selectedLeakDocId !== undefined) {
      const wanted = rawState.selectedLeakDocId === null ? null : String(rawState.selectedLeakDocId);
      if (wanted === null || state.moleCandidateDocs.some((d) => d.doc_id === wanted)) {
        state.selectedLeakDocId = wanted;
      } else {
        state.selectedLeakDocId = null;
      }
    }

    renderWorkspace();
    renderCaseLog();
  }

  function addLogEntry(rawEntry = {}) {
    if (!rawEntry || typeof rawEntry !== "object") return;
    const forbidden = !state.done
      ? state.mode === "mole"
        ? MOLE_MODE_FORBIDDEN_KEYS
        : ALWAYS_FORBIDDEN_KEYS
      : new Set();

    const callPart = rawEntry.call && typeof rawEntry.call === "object" ? rawEntry.call : null;
    const resPart = rawEntry.result && typeof rawEntry.result === "object" ? rawEntry.result : null;

    const tool = String(rawEntry.tool || (callPart && callPart.tool) || "status");
    const rawArgs = rawEntry.args || rawEntry.arguments || (callPart && callPart.arguments) || {};
    const ok =
      rawEntry.ok !== undefined
        ? Boolean(rawEntry.ok)
        : resPart && resPart.ok !== undefined
          ? Boolean(resPart.ok)
          : !rawEntry.error && !(resPart && resPart.error);
    const rawData = rawEntry.data !== undefined ? rawEntry.data : resPart && resPart.data ? resPart.data : {};
    const rawError =
      rawEntry.error !== undefined
        ? rawEntry.error
        : resPart && resPart.error !== undefined
          ? resPart.error
          : null;
    const entryDay =
      rawEntry.day !== undefined && Number.isFinite(Number(rawEntry.day))
        ? Math.max(1, Math.trunc(Number(rawEntry.day)))
        : state.day;

    const cleanArgs = forbidden.size > 0 ? scrubLogValue(rawArgs, forbidden) : rawArgs;
    const cleanData = forbidden.size > 0 ? scrubLogValue(rawData, forbidden) : rawData;

    const seq =
      rawEntry.seq !== undefined && Number.isFinite(Number(rawEntry.seq))
        ? Math.trunc(Number(rawEntry.seq))
        : nextCallSeq;
    nextCallSeq = Math.max(nextCallSeq + 1, seq + 1);

    if (ok && state.mode !== "mole") {
      if (tool === "plant_canary" && cleanData && cleanData.canary_id) {
        const planted = normalizePlantedCanary({
          canary_id: cleanData.canary_id,
          assignment: cleanArgs && cleanArgs.assignment ? cleanArgs.assignment : {},
        });
        if (planted && !state.plantedCanaries.some((c) => c.id === planted.id)) {
          state.plantedCanaries.push(planted);
        }
        state.canaryAssignment = {};
        draft.doc_title = "";
        renderWorkspace();
      } else if (
        tool === "list_employees" &&
        state.employees.length === 0 &&
        cleanData &&
        Array.isArray(cleanData.employees)
      ) {
        state.employees = cleanData.employees.map(sanitizeEmployee).filter(Boolean);
        renderWorkspace();
      }
    }

    logEntries.push({
      seq,
      day: entryDay,
      tool,
      args: cleanArgs && typeof cleanArgs === "object" ? cleanArgs : {},
      ok,
      data: cleanData && typeof cleanData === "object" ? cleanData : {},
      error: rawError === null || rawError === undefined ? null : String(rawError),
    });

    renderCaseLog();
  }

  function clearLog() {
    logEntries = [];
    nextCallSeq = 1;
    clear(caseLogEl);
  }

  function getState() {
    return {
      mode: state.mode,
      day: state.day,
      nDays: state.nDays,
      visibleV: state.visibleV,
      done: state.done,
      selectedTool: state.selectedTool,
      selectedEmployee: state.selectedEmployee,
      selectedLeakDocId: state.selectedLeakDocId,
      certaintyPct: state.certaintyPct,
      marks: { ...state.marks },
      canaryAssignment: { ...state.canaryAssignment },
      restricted: [...state.restricted],
      employees: state.employees.map((e) => ({ ...e })),
      moleCandidateDocs: state.moleCandidateDocs.map((d) => ({ ...d })),
      logCount: logEntries.length,
    };
  }

  renderWorkspace();
  renderCaseLog();

  return {
    element: rootEl,
    update,
    addLogEntry,
    clearLog,
    getState,
  };
}
