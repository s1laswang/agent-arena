// Canary browser game: a case-file UI over game/canary_game.py running in Pyodide. Owner: HARNESS (WS6).
// Hard rule: the page calls a tool ONLY when the player presses its button. Everything shown in the vitals
// (day, V, actions, restrictions, leaks) comes from replies the player asked for, never from hidden calls.
"use strict";

const $ = (id) => document.getElementById(id);

/** Tiny DOM builder. Strings become text nodes (never HTML), so game data cannot inject markup. */
function h(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false) n.append(kid instanceof Node ? kid : String(kid));
  return n;
}
const pad2 = (n) => String(n).padStart(2, "0");
const fmt = (x) => (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(Number(x)).toFixed(2);

const TOOLS = {
  list_employees:    { code: "EMP", name: "Staff list",   group: "Investigate", desc: "Everyone in the company: id, name, department and role." },
  list_documents:    { code: "DOC", name: "Documents",    group: "Investigate", desc: "Sensitive documents published in a day range, and exactly who received each one." },
  read_access_logs:  { code: "LOG", name: "Access logs",  group: "Investigate", desc: "Who opened which document. Logs exist only for days that have ended. After-hours opens are marked [AH]." },
  search_messages:   { code: "MSG", name: "Messages",     group: "Investigate", desc: "Search internal email and chat by keyword. At most 20 results." },
  read_message:      { code: "RD",  name: "Read message", group: "Investigate", desc: "Open one message by id. Easiest: press Open on a search result." },
  interview:         { code: "INT", name: "Interview",    group: "Investigate", desc: "Ask one employee about one topic. Anyone can be evasive; the mole a little more often." },
  plant_canary:      { code: "CAN", name: "Canary",       group: "Trap",        desc: "Publish a trap document whose copy differs per group. If it leaks, the feed shows which variant." },
  check_leak_feed:   { code: "FED", name: "Leak feed",    group: "Trap",        desc: "Leaks that have surfaced so far. A leak surfaces 1 to 3 days after it happens." },
  restrict_access:   { code: "RST", name: "Restrict",     group: "Contain",     desc: "Stop one employee from receiving new documents. Costs value for every day that ends while it lasts." },
  unrestrict_access: { code: "UNR", name: "Unrestrict",   group: "Contain",     desc: "Lift a restriction." },
  status:            { code: "STA", name: "Status",       group: "Clock",       desc: "Day, visible value, actions and calls left, restrictions and canaries." },
  advance_day:       { code: "DAY", name: "End day",      group: "Clock",       desc: "Close the day. Overnight the mole may leak one document it received in the last 3 days." },
  accuse:            { code: "ACC", name: "Accuse",       group: "Decide",      desc: "Ends the case. Correct: you score the true value at this moment. Wrong: −1." },
};
const GROUPS = ["Investigate", "Trap", "Contain", "Clock", "Decide"];
const TOPICS = { recent_documents: "Recent documents", contacts_outside: "Contacts outside", workload: "Workload", access_needs: "Access needs" };

const S = {
  py: null, game: null, spec: null, seed: null, reference: {},
  calls: 0, cap: 300, nDays: 14, perDay: 8, maxVariants: 3, costed: new Set(),
  day: 1, V: 1, vHist: [[1, 1]], asof: null, used: [], burnt: false,
  staff: [], byId: {}, restricted: new Set(), canaries: [], leaks: new Map(),
  marks: {}, sel: null, tool: null, assign: {}, last: {}, over: false,
  draft: {}, wrongScore: -1, certainty: 50, trueVScore: false,
};
const LABELS = ["A", "B", "C", "D", "E"];

// ------------------------------------------------------------------ boot
function bootStep(text, cls) {
  const li = h("li", { class: cls || "" }, text);
  $("bootLog").append(li);
  return li;
}
function randomSeed() { return 3000 + Math.floor(Math.random() * 7000); }

async function boot() {
  $("seed").value = new URLSearchParams(location.search).get("seed") || randomSeed();
  const a = bootStep("Python runtime (Pyodide)");
  try {
    S.py = await loadPyodide();
    a.className = "done";
    const manifest = await (await fetch("py/manifest.json")).json();
    const b = bootStep(`canary package: ${manifest.files.length} files`);
    for (const rel of manifest.files) {
      const text = await (await fetch("py/" + rel)).text();
      const path = "/home/pyodide/" + rel;
      S.py.FS.mkdirTree(path.substring(0, path.lastIndexOf("/")));
      S.py.FS.writeFile(path, text);
    }
    S.py.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import canary_game");
    b.className = "done";
    try { const r = await fetch("reference.json"); S.reference = r.ok ? await r.json() : {}; } catch (_) { S.reference = {}; }
    bootStep("ready", "done");
    $("bootState").textContent = "ready";
    $("startBtn").disabled = false;
    $("startBtn").textContent = "Open the case file";
  } catch (e) {
    bootStep("could not load the environment: " + e, "err");
    $("bootState").textContent = "error";
  }
}

function parseRules(text) {
  const num = (re, d) => { const m = text.match(re); return m ? Number(m[1]) : d; };
  S.cap = num(/limit of (\d+) calls/, 300);
  S.nDays = num(/lasts at most (\d+) days/, 14);
  S.perDay = num(/one of your (\d+) actions per day/, 8);
  S.maxVariants = num(/Use at most (\d+) different labels/, 3);
  S.wrongScore = num(/If you accuse an innocent employee, your score is (-?\d+(?:\.\d+)?)/, -1);
  S.trueVScore = /Your score uses the true V/.test(text);
  const m = text.match(/^- (.+?) each use one of your \d+ actions per day/m);
  S.costed = new Set(m ? m[1].replace(/`/g, "").split(/,\s*/).map((s) => s.trim()) : []);
}

function start(ev) {
  if (ev) ev.preventDefault();
  const seed = $("seed").value.trim();
  try {
    S.game = S.py.runPython(`canary_game.Game(${JSON.stringify(seed)})`);
  } catch (e) {
    bootStep(String(e).split("\n").filter(Boolean).pop(), "err");
    return;
  }
  S.spec = JSON.parse(S.game.spec_json());
  S.seed = S.spec.seed;
  parseRules(S.spec.instruction);
  $("rules").textContent = S.spec.instruction;
  $("ver").textContent = S.spec.tiers_version;
  $("caseId").textContent = `case no. ${S.seed} · ${S.spec.tier} · tiers ${S.spec.tiers_version}`;
  $("rulesBtn").disabled = false;
  $("agentBtn").disabled = false;
  $("intro").hidden = true;
  $("desk").hidden = false;
  S.tool = "list_employees";
  renderAll();
  $("log").append(h("div", { class: "log-empty", id: "logEmpty" },
    "The case log is empty. Start with the staff list and the documents: no tool runs until you press it."));
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ calling tools
function run(tool, args) {
  if (S.over) return;
  const res = JSON.parse(S.game.call_json(tool, JSON.stringify(args)));
  S.calls += 1;
  const dayAtCall = S.day;
  absorb(tool, args, res);
  addEntry(tool, args, res, S.calls, dayAtCall);
  renderAll();
  if (res.done) finish();
}

function absorb(tool, args, res) {
  const d = res.data || {};
  if (res.ok && S.costed.has(tool)) S.used.push(TOOLS[tool] ? TOOLS[tool].code : "···");
  if (!res.ok && /daily action limit/.test(res.error || "")) S.burnt = true;
  if (!res.ok) return;
  S.last[tool] = args;
  switch (tool) {
    case "advance_day":
      S.day = d.day; S.V = d.V; S.vHist.push([d.day, d.V]);
      S.used = []; S.burnt = false; S.asof = { day: d.day, call: S.calls };
      for (const e of document.querySelectorAll(".entry, .day-div")) if (Number(e.dataset.day) < S.day) e.classList.add("stale");
      break;
    case "status":
      S.day = d.day; S.V = d.V; S.asof = { day: d.day, call: S.calls };
      S.restricted = new Set(d.restricted || []);
      if (S.vHist.length && S.vHist[S.vHist.length - 1][0] === d.day) S.vHist[S.vHist.length - 1][1] = d.V; else S.vHist.push([d.day, d.V]);
      while (S.used.length < S.perDay - d.actions_left_today) S.used.push("···");
      break;
    case "list_employees":
      S.staff = d.employees || [];
      S.byId = Object.fromEntries(S.staff.map((e) => [e.id, e]));
      break;
    case "restrict_access": S.restricted.add(d.restricted || args.employee); delete S.assign[d.restricted || args.employee]; break;
    case "unrestrict_access": S.restricted.delete(d.unrestricted || args.employee); break;
    case "plant_canary": {
      const groups = {};
      for (const [pid, lab] of Object.entries(args.assignment || {})) (groups[lab] = groups[lab] || []).push(pid);
      S.canaries.push({ id: d.canary_id, title: args.doc_title, day: S.day, groups });
      S.assign = {}; S.draft.doc_title = "";
      break;
    }
    case "check_leak_feed":
      for (const it of d.items || []) S.leaks.set(it.doc_id, it);
      break;
  }
}

// ------------------------------------------------------------------ rendering: vitals
function vital(cap, right, ...body) {
  return h("div", { class: "vital" }, h("div", { class: "cap" }, h("span", {}, cap), right ? h("span", {}, right) : null), ...body);
}
function spark() {
  const pts = S.vHist, w = 160, ht = 26;
  const lo = Math.min(0.6, ...pts.map((p) => p[1])) - 0.02, hi = 1.0;
  const x = (day) => ((day - 1) / Math.max(1, S.nDays - 1)) * (w - 2) + 1;
  const y = (v) => ht - 2 - ((v - lo) / (hi - lo)) * (ht - 4);
  let d = `M${x(pts[0][0])},${y(pts[0][1])}`;
  for (let i = 1; i < pts.length; i++) d += ` H${x(pts[i][0])} V${y(pts[i][1])}`;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${ht}`); svg.setAttribute("preserveAspectRatio", "none"); svg.setAttribute("class", "spark");
  svg.innerHTML = `<line class="base" x1="0" x2="${w}" y1="${y(1)}" y2="${y(1)}"></line><path d="${d}"></path>`;
  return svg;
}
function renderVitals() {
  const v = $("vitals");
  v.textContent = "";
  const ticks = h("div", { class: "ticks" });
  for (let i = 1; i <= S.nDays; i++) ticks.append(h("i", { class: i < S.day ? "past" : i === S.day ? "now" : "" }));
  v.append(vital("Day", `of ${S.nDays}`, h("div", { class: "val" }, pad2(S.day), h("small", {}, ` / ${S.nDays}`)), ticks));

  v.append(vital("Value (visible)", "starts 1.00",
    h("div", { class: "val" }, Number(S.V).toFixed(2)), spark(),
    h("div", { class: "asof" }, S.asof ? `as of day ${pad2(S.asof.day)} · call #${S.asof.call}` : "no reading yet: End day or Status")));

  const left = S.burnt ? 0 : Math.max(0, S.perDay - S.used.length);
  const punch = h("div", { class: "punch" });
  for (let i = 0; i < S.perDay; i++) {
    if (i < S.used.length) punch.append(h("i", { class: "used", title: S.used[i] }, S.used[i]));
    else punch.append(h("i", { class: S.burnt ? "burnt" : "" }));
  }
  v.append(vital("Actions today", `${left} left`, punch,
    h("div", { class: "asof" }, "free: staff, docs, status, end day")));

  const meter = h("div", { class: "meter" }, h("b", { style: `width:${Math.min(100, (100 * S.calls) / S.cap)}%` }));
  v.append(vital("Tool calls", `${S.cap - S.calls} left`, h("div", { class: "val" }, String(S.calls), h("small", {}, ` / ${S.cap}`)), meter));

  const leaks = h("div", { class: "chips" });
  for (const id of [...S.leaks.keys()].slice(-4)) leaks.append(h("span", { class: "t red" }, id));
  v.append(vital("Leaks seen", null, h("div", { class: "val" }, String(S.leaks.size)), leaks));

  const r = h("div", { class: "chips" });
  if (!S.restricted.size) r.append(h("span", { class: "t dim" }, "none"));
  for (const id of [...S.restricted].sort()) r.append(pidTag(id, "inv"));
  v.append(vital("Restricted", String(S.restricted.size), r));
}

// ------------------------------------------------------------------ rendering: roster
function pid(id) {
  const e = S.byId[id];
  return h("span", { class: "pid", "data-pid": id, title: e ? `${e.name} · ${e.dept}, ${e.role}` : null }, id);
}
function pidTag(id, cls) {
  const e = S.byId[id];
  return h("span", { class: `t ${cls || ""}`, "data-pid": id, title: e ? e.name : null }, id);
}
function canaryOf(id) {
  const out = [];
  for (const c of S.canaries) for (const [lab, ids] of Object.entries(c.groups)) if (ids.includes(id)) out.push(`${c.id}:${lab}`);
  return out;
}
function renderRoster() {
  const box = $("roster");
  box.textContent = "";
  box.classList.toggle("building", S.tool === "plant_canary");
  const head = h("div", { class: "sheet-h" }, h("span", {}, S.staff.length ? `Staff · ${S.staff.length}` : "Staff"));
  box.append(head);
  if (!S.staff.length) {
    box.append(h("div", { class: "roster-empty" },
      h("p", {}, "No staff list on file yet. Pulling it is free and does not use an action."),
      h("button", { class: "primary", type: "button", onclick: () => run("list_employees", {}) }, "Pull the staff list")));
    return;
  }
  if (S.tool === "plant_canary") head.append(h("span", { class: "mono" }, "assign A / B / C"));
  const rows = h("div", { class: "rows" });
  const labels = LABELS.slice(0, S.maxVariants);
  for (const e of S.staff) {
    const mark = S.marks[e.id];
    const tags = h("span", { class: "tags" });
    if (S.restricted.has(e.id)) tags.append(h("span", { class: "t inv" }, "restricted"));
    for (const c of canaryOf(e.id)) tags.append(h("span", { class: "t hl" }, c));
    const marks = h("div", { class: "marks" },
      h("button", { type: "button", class: `s ${mark === "suspect" ? "on" : ""}`, title: "Mark as suspect (only on this page)",
        onclick: (ev) => { ev.stopPropagation(); S.marks[e.id] = mark === "suspect" ? null : "suspect"; renderRoster(); } }, "S"),
      h("button", { type: "button", class: mark === "cleared" ? "on" : "", title: "Mark as cleared (only on this page)",
        onclick: (ev) => { ev.stopPropagation(); S.marks[e.id] = mark === "cleared" ? null : "cleared"; renderRoster(); } }, "×"));
    const variant = h("div", { class: "variant" }, labels.map((lab) =>
      h("button", { type: "button", class: S.assign[e.id] === lab ? "on" : "", disabled: S.restricted.has(e.id),
        title: S.restricted.has(e.id) ? "Restricted staff cannot receive a canary" : `Give ${e.id} variant ${lab}`,
        onclick: (ev) => { ev.stopPropagation(); if (S.assign[e.id] === lab) delete S.assign[e.id]; else S.assign[e.id] = lab; renderRoster(); renderForm(); } }, lab)));
    rows.append(h("div", {
      class: `row ${S.sel === e.id ? "sel" : ""} ${mark || ""}`, "data-pid": e.id,
      onclick: () => { S.sel = e.id; renderRoster(); renderForm(); },
    }, h("span", { class: "id" }, e.id),
       h("span", { class: "who" }, h("span", { class: "name" }, e.name), h("span", { class: "meta" }, `${e.dept} · ${e.role}`), tags),
       h("span", {}, marks, variant)));
  }
  box.append(rows);
  box.append(h("div", { class: "legend" },
    h("span", {}, "Click a row to use that person in the tool form."),
    h("span", {}, "S / × are your own notes; they never reach the game.")));
}

// ------------------------------------------------------------------ rendering: command bar + form
function renderBar() {
  const bar = $("cmdbar");
  bar.textContent = "";
  const names = (S.spec.tools || []).map((t) => t.name);
  const rows = [h("div", { class: "cmdrow" }), h("div", { class: "cmdrow" })];
  for (const g of GROUPS) {
    const tools = names.filter((n) => TOOLS[n] && TOOLS[n].group === g);
    if (!tools.length) continue;
    const grp = h("div", { class: `grp ${g === "Decide" ? "decide" : ""}` }, h("span", {}, g));
    for (const n of tools) {
      const t = TOOLS[n];
      grp.append(h("button", {
        type: "button", class: `tool ${n === "accuse" ? "accuse" : ""}`, "aria-pressed": String(S.tool === n), disabled: S.over,
        onclick: () => { S.tool = n; renderAll(); },
      }, h("span", { class: "code" }, t.code), h("span", { class: "nm" }, t.name),
         h("span", { class: "cost" }, n === "accuse" ? "ends the case" : S.costed.has(n) ? "1 action" : "free")));
    }
    rows[g === "Investigate" || g === "Trap" ? 0 : 1].append(grp);
  }
  bar.append(...rows);
}

function staffSelect(name, optional, value) {
  if (!S.staff.length) return h("input", { name, value: value || "", placeholder: "e07", class: "mono", size: 5 });
  const sel = h("select", { name });
  if (optional) sel.append(h("option", { value: "" }, "everyone"));
  for (const e of S.staff) {
    const o = h("option", { value: e.id }, `${e.id} · ${e.name}`);
    if (e.id === value) o.selected = true;
    sel.append(o);
  }
  return sel;
}
const num = (name, value, min, max) => h("input", { type: "number", name, value, min, max, step: 1 });
const lab = (text, input) => h("label", {}, h("span", { class: "lbl" }, text), input);

function renderForm() {
  const f = $("cmdform");
  f.textContent = "";
  const tool = S.tool, t = TOOLS[tool];
  if (!t) return;
  const last = S.last[tool] || {};
  f.append(h("p", { class: "desc" }, t.desc));
  const today = S.day;
  let ready = true;
  switch (tool) {
    case "list_documents":
      f.append(lab("From day", num("day_from", 1, 1, today)), lab("To day", num("day_to", today, 1, today)));
      break;
    case "read_access_logs": {
      const to = Math.max(1, today - 1);
      f.append(lab("From day", num("day_from", Math.max(1, to - 2), 1, to)), lab("To day", num("day_to", to, 1, to)),
               lab("Employee", staffSelect("employee", true, S.sel)));
      if (today === 1) f.append(h("span", { class: "note" }, "No day has ended yet, so there are no logs."));
      break;
    }
    case "search_messages":
      f.append(lab("Keyword", h("input", { name: "query", value: last.query || "", placeholder: "e.g. board, Falcon, deadline", class: "wide" })),
               lab("From day", num("day_from", 1, 1, today)), lab("To day", num("day_to", today, 1, today)));
      break;
    case "read_message":
      f.append(lab("Message id", h("input", { name: "id", value: last.id || "", placeholder: "m3-1", class: "mono" })));
      break;
    case "interview":
      f.append(lab("Employee", staffSelect("employee", false, S.sel)));
      f.append(lab("Topic", h("select", { name: "topic" }, Object.entries(TOPICS).map(([k, v]) => h("option", { value: k }, v)))));
      break;
    case "plant_canary": {
      const title = h("input", { name: "doc_title", value: S.draft.doc_title || "", placeholder: "Q3 board memo", class: "wide", maxlength: 120 });
      title.addEventListener("input", () => {
        S.draft.doc_title = title.value;
        const b = f.querySelector(".run");
        if (b) b.disabled = S.over || !title.value.trim() || !Object.keys(S.assign).length || !S.staff.length;
      });
      f.append(lab("Document title", title));
      const groups = {};
      for (const [p, l] of Object.entries(S.assign)) (groups[l] = groups[l] || []).push(p);
      const gl = h("div", { class: "groups" });
      if (!Object.keys(groups).length) gl.append(h("span", { class: "note" }, "Assign people in the staff list: press A, B or C on each row."));
      for (const l of Object.keys(groups).sort()) gl.append(h("span", {}, h("b", {}, l), groups[l].sort().join(" ")));
      f.append(gl);
      if (S.staff.length) f.append(h("button", { class: "ghost", type: "button", disabled: S.over, onclick: evenSplit,
        title: `Assign ${labels3()} in turn to the people assigned now, or to all staff if nobody is` }, "Even split"));
      ready = Object.keys(S.assign).length > 0 && !!(S.draft.doc_title || "").trim();
      if (!S.staff.length) { f.append(h("span", { class: "warn" }, "Pull the staff list first.")); ready = false; }
      break;
    }
    case "restrict_access":
    case "unrestrict_access":
      f.append(lab("Employee", staffSelect("employee", false, S.sel)));
      break;
    case "advance_day":
      f.append(h("span", { class: "note" }, `Ends day ${today} of ${S.nDays}. Unused actions are lost.`));
      break;
    case "accuse": {
      const sel = staffSelect("employee", false, S.sel);
      f.append(lab("Employee", sel), h("span", { class: "warn" }, "This ends the case. There is no second accusation."));
      f.append(h("button", { class: "danger run", type: "button", disabled: S.over,
        onclick: () => openAccuse(sel.value.trim()) }, "Accuse…"));
      return;
    }
    default:
      break;
  }
  f.append(h("button", { class: "primary run", type: "submit", disabled: !ready || S.over },
    `Run ${t.name.toLowerCase()} · ${S.costed.has(tool) ? "1 action" : "free"}`));
}

function readForm() {
  const args = {};
  for (const el of $("cmdform").querySelectorAll("input, select")) {
    if (el.name.startsWith("_")) continue;
    const v = el.value.trim();
    if (v === "") continue;
    args[el.name] = el.type === "number" ? Number(v) : v;
  }
  if (S.tool === "plant_canary") args.assignment = { ...S.assign };
  return args;
}

// ------------------------------------------------------------------ rendering: case log
function argSummary(args) {
  const parts = [];
  for (const [k, v] of Object.entries(args)) parts.push(`${k}=${typeof v === "object" ? JSON.stringify(v) : v}`);
  return parts.join("  ");
}

function addEntry(tool, args, res, call, day) {
  const empty = $("logEmpty");
  if (empty) empty.remove();
  const t = TOOLS[tool] || { code: "?", name: tool };
  const items = (res.data && res.data.items) || [];
  const art = h("article", { class: `entry ${res.ok ? "" : "err"} ${tool === "check_leak_feed" && res.ok && items.length ? "leak" : ""}`, "data-day": day },
    h("div", { class: "entry-h" },
      h("span", { class: "stamp" }, `D${pad2(day)} · #${call}`),
      h("span", { class: "t inv" }, t.code),
      h("span", { class: "what" }, t.name),
      h("span", { class: "args" }, argSummary(args)),
      h("span", { class: "right" }, res.ok ? h("span", { class: "t dim" }, S.costed.has(tool) ? "1 action" : "free") : h("span", { class: "t red" }, "rejected"))),
    h("div", { class: "entry-b" }, body(tool, args, res)),
    h("pre", { class: "raw" }, JSON.stringify({ call: { tool, arguments: args }, result: { ok: res.ok, data: res.data, error: res.error } }, null, 2)));
  const log = $("log");
  log.prepend(art);
  if (tool === "advance_day" && res.ok) {
    const d = res.data;
    log.prepend(h("div", { class: "day-div", "data-day": d.day },
      h("span", { class: "lab" }, `DAY ${pad2(d.day)} OPENS`), h("span", { class: "line" }),
      h("span", { class: "info" }, `value ${Number(d.V).toFixed(2)} · ${(d.new_documents || []).length} new documents`)));
  }
}

function body(tool, args, res) {
  if (!res.ok) {
    const hint = res.error === "invalid arguments" ? " " + badHint(tool, args) : "";
    return h("p", {}, h("b", {}, "Rejected: "), res.error + "." + hint);
  }
  const d = res.data || {};
  switch (tool) {
    case "list_employees": {
      const depts = {};
      for (const e of d.employees || []) depts[e.dept] = (depts[e.dept] || 0) + 1;
      return h("p", {}, `${(d.employees || []).length} people on file. `,
        Object.entries(depts).map(([k, v]) => `${k} ${v}`).join(" · "), ". The list is now in the staff panel.");
    }
    case "list_documents": {
      const docs = d.documents || [];
      if (!docs.length) return h("p", {}, "No documents in that range.");
      return h("div", { class: "scroll" }, h("table", { class: "tbl" },
        h("thead", {}, h("tr", {}, h("th", {}, "Doc"), h("th", {}, "Title"), h("th", { class: "num" }, "Day"), h("th", { class: "num" }, "To"), h("th", {}, "Recipients"))),
        h("tbody", {}, docs.map((x) => h("tr", {},
          h("td", { class: "mono" }, x.doc_id, x.is_canary ? h("span", {}, " ", h("span", { class: "t hl" }, "canary")) : null),
          h("td", {}, x.title), h("td", { class: "num" }, x.day), h("td", { class: "num" }, (x.recipients || []).length),
          h("td", {}, h("span", { class: "ids" }, (x.recipients || []).map(pid))))))));
    }
    case "read_access_logs": {
      const logs = d.logs || [];
      if (!logs.length) return h("p", {}, "No accesses in that range. Logs exist only for days that have ended.");
      const ah = logs.filter((x) => x.after_hours).length;
      return h("div", {}, h("p", { class: "dim" }, `${logs.length} opens, ${ah} after hours.`),
        h("div", { class: "scroll" }, h("table", { class: "tbl" },
          h("thead", {}, h("tr", {}, h("th", { class: "num" }, "Day"), h("th", {}, "Who"), h("th", {}, "Document"), h("th", {}, ""))),
          h("tbody", {}, logs.map((x) => h("tr", { class: x.after_hours ? "ah" : "" },
            h("td", { class: "num" }, x.day), h("td", {}, pid(x.employee)), h("td", { class: "mono" }, x.doc_id),
            h("td", {}, x.after_hours ? h("span", { class: "t" }, "AH") : "")))))));
    }
    case "search_messages": {
      const msgs = d.messages || [];
      if (!msgs.length) return h("p", {}, `No messages match “${args.query || ""}”.`);
      return h("div", {}, msgs.map((m) => h("div", { class: "msgrow" },
        h("span", { class: "mono dim" }, m.id), h("span", { class: "mono" }, `D${pad2(m.day)}`), h("span", { class: "ch dim" }, m.channel),
        h("span", {}, h("span", { class: "subj" }, m.subject || "(no subject)"), " ", pid(m.sender), h("span", { class: "snip" }, m.snippet)),
        h("button", { class: "link", type: "button", disabled: S.over, title: "Uses 1 action",
          onclick: () => { S.tool = "read_message"; S.last.read_message = { id: m.id }; renderAll(); run("read_message", { id: m.id }); } }, "open"))));
    }
    case "read_message": {
      const m = d.message || {};
      return h("div", { class: "memo" },
        h("dl", {},
          h("dt", { class: "lbl" }, "From"), h("dd", {}, pid(m.sender)),
          h("dt", { class: "lbl" }, "To"), h("dd", {}, h("span", { class: "ids" }, (m.recipients || []).map(pid))),
          h("dt", { class: "lbl" }, "Where"), h("dd", {}, `${m.channel}, day ${m.day}`),
          h("dt", { class: "lbl" }, "Subject"), h("dd", {}, m.subject || "(none)")),
        h("div", { class: "body" }, m.body));
    }
    case "interview":
      return h("div", {}, h("div", { class: "q" }, "Asked ", pid(d.employee || args.employee), " about ", (TOPICS[d.topic] || d.topic || "").toLowerCase(), ":"),
        h("p", { class: "quote" }, d.answer));
    case "plant_canary": {
      const c = S.canaries.find((x) => x.id === d.canary_id);
      return h("div", {}, h("p", {}, "Canary ", h("span", { class: "t hl" }, d.canary_id), ` planted as “${args.doc_title}”. If it leaks, the feed names the variant.`),
        h("div", { class: "groups" }, Object.entries(c ? c.groups : {}).sort().map(([l, ids]) => h("span", {}, h("b", {}, l), h("span", { class: "ids" }, ids.sort().map(pid))))));
    }
    case "check_leak_feed": {
      const items = d.items || [];
      if (!items.length) return h("p", {}, "Nothing has surfaced yet. Leaks show up 1 to 3 days after they happen.");
      return h("div", {}, items.map((it) => {
        const c = S.canaries.find((x) => x.id === it.doc_id);
        const grp = c && it.variant ? c.groups[it.variant] || [] : null;
        return h("div", { class: "leakcard" },
          h("span", { class: "when" }, `surfaced D${pad2(it.surfaced_day)}`),
          h("span", {}, h("span", { class: "mono" }, it.doc_id), " ", h("span", { class: "doc" }, it.title),
            it.variant ? h("span", {}, " ", h("span", { class: "t hl" }, `canary ${it.doc_id} · variant ${it.variant}`)) : null,
            grp ? h("div", { class: "dim" }, `Variant ${it.variant} went to: `, h("span", { class: "ids" }, grp.sort().map(pid))) : null));
      }));
    }
    case "restrict_access":
      return h("p", {}, pid(d.restricted || args.employee), " is restricted: no new documents, a small cost every day it lasts.");
    case "unrestrict_access":
      return h("p", {}, pid(d.unrestricted || args.employee), "'s restriction is lifted.");
    case "status":
      return h("div", { class: "kv" },
        [["Day", d.day], ["Value", Number(d.V).toFixed(2)], ["Actions left", d.actions_left_today], ["Calls left", d.tool_calls_left],
         ["Restricted", (d.restricted || []).join(" ") || "none"], ["Canaries", (d.canaries_planted || []).join(" ") || "none"]]
          .map(([k, v]) => h("div", {}, h("span", { class: "lbl" }, k), h("span", { class: "v" }, String(v)))));
    case "advance_day":
      return h("p", {}, `Day ${d.closed_day} closed. Day ${d.day} opens at value ${Number(d.V).toFixed(2)} with new documents `,
        h("span", { class: "mono" }, (d.new_documents || []).join(" ")), ".");
    case "accuse":
      return h("p", {}, "Accused ", pid(args.employee), ". The case is closed.");
    default:
      return h("pre", { class: "mono" }, JSON.stringify(d, null, 1));
  }
}

/** The engine answers every bad call with the same constant, so name the field from the arguments that were sent. */
function badHint(tool, args) {
  const ids = new Set(S.staff.map((e) => e.id));
  const emp = args.employee;
  if (emp !== undefined && S.staff.length && !ids.has(emp)) return `Employee: “${emp}” is not an id on the staff list (e.g. e07).`;
  if ("day_from" in args && "day_to" in args && args.day_from > args.day_to) return "Days: “from” is after “to”.";
  for (const k of ["day_from", "day_to"]) if (k in args && !(args[k] >= 1 && args[k] <= S.nDays)) return `Days: must be 1 to ${S.nDays}.`;
  switch (tool) {
    case "plant_canary": {
      const asg = args.assignment || {};
      if (!(args.doc_title || "").trim()) return "Document title: it is empty.";
      if (args.doc_title.length > 120) return "Document title: 120 characters at most.";
      if (!Object.keys(asg).length) return "Assignment: give at least one person a variant.";
      const r = Object.keys(asg).filter((p) => S.restricted.has(p));
      if (r.length) return `Assignment: ${r.join(" ")} restricted, and restricted staff cannot receive a canary.`;
      if (new Set(Object.values(asg)).size > S.maxVariants) return `Assignment: ${S.maxVariants} variants at most.`;
      return "Check the document title and the assignment.";
    }
    case "search_messages": return "Keyword: it is required, without * and at most 200 characters.";
    case "read_message": return "Message id: no message has that id (open one from a search result).";
    case "interview": return "Employee and topic: both are required.";
    case "read_access_logs": return "Days: both are required.";
    case "restrict_access": return "Employee: already restricted.";
    case "unrestrict_access": return "Employee: not restricted.";
    case "accuse": return "Employee: pick one id from the staff list.";
    default: return "Check the fields.";
  }
}

function labels3() { return LABELS.slice(0, S.maxVariants).join(" / "); }

/** Even split: A, B, C in turn over the people assigned now (or all staff if nobody is), in staff-list order. */
function evenSplit() {
  const labels = LABELS.slice(0, S.maxVariants);
  const picked = Object.keys(S.assign).length ? S.staff.filter((e) => e.id in S.assign) : S.staff;
  const pool = picked.filter((e) => !S.restricted.has(e.id));
  S.assign = {};
  pool.forEach((e, i) => { S.assign[e.id] = labels[i % labels.length]; });
  renderRoster(); renderForm();
}

// ------------------------------------------------------------------ accusation dialog
// The certainty is the player's own estimate. It stays on this page and is never sent to the game.
function openAccuse(preset) {
  const dlg = $("accuseDlg");
  if (!dlg || S.over) return;
  const sel = $("accWho"), arm = $("accArm"), slider = $("accP");
  sel.textContent = "";
  sel.append(h("option", { value: "" }, "choose…"));
  for (const e of S.staff) sel.append(h("option", { value: e.id }, `${e.id} · ${e.name}`));
  if (!S.staff.length && preset) sel.append(h("option", { value: preset }, preset));
  sel.value = preset && [...sel.options].some((o) => o.value === preset) ? preset : "";
  arm.value = "";
  slider.value = String(S.certainty);
  $("accFine").textContent = `Right: the company's ${S.trueVScore ? "true value at this moment, which also counts leaks that have not surfaced yet" : "value at this moment"}. `
    + `Wrong: ${fmt(S.wrongScore)}. No accusation by the last day: 0. There is no second accusation.`;
  updateAccuse();
  dlg.showModal();
  (sel.value ? arm : sel).focus();
}

function updateAccuse() {
  const sel = $("accWho"), arm = $("accArm"), slider = $("accP");
  const p = Number(slider.value) / 100, V = Number(S.V), w = S.wrongScore;
  S.certainty = Number(slider.value);
  const pStar = -w / (V - w);
  const ev = p * V + (1 - p) * w;
  const evR = Math.round(ev * 100) / 100;
  $("accPOut").textContent = `${slider.value}%`;
  $("accV").textContent = V.toFixed(2);
  $("accVAsof").textContent = S.asof ? `as of day ${pad2(S.asof.day)} · call #${S.asof.call}` : "start value, no reading yet";
  $("accBE").textContent = `${(100 * pStar).toFixed(1)}%`;
  $("accEV").textContent = evR === 0 ? "0.00" : fmt(ev);
  const verdict = $("accVerdict");
  verdict.textContent = evR === 0 ? "Accusing at this certainty is break-even on average."
    : `Accusing at this certainty ${evR > 0 ? "gains" : "loses"} value on average.`;
  verdict.classList.toggle("neg", evR < 0);
  const who = S.byId[sel.value];
  $("accGo").textContent = sel.value ? `Accuse ${sel.value}${who ? " · " + who.name : ""}` : "Accuse";
  $("accGo").disabled = S.over || !sel.value || arm.value.trim() !== sel.value;
}

// ------------------------------------------------------------------ case closed
function finish() {
  S.over = true;
  renderAll();
  const r = JSON.parse(S.game.reveal_json());
  const mole = S.byId[r.mole];
  const you = r.you;
  const ref = S.reference[String(r.seed)] || [];
  const youLine = you.end_reason === "accused"
    ? `You accused ${you.accused} on day ${you.final_day}, after ${you.tool_calls} tool calls. ${you.correct ? "That was the mole." : "That was the wrong person."}`
    : `The case ended on day ${you.final_day} (${you.end_reason}) without an accusation.`;
  const rows = [
    ["You", you.end_reason === "accused" ? (you.correct ? "correct" : "wrong") : you.end_reason, you.final_day, you.tool_calls, you.score],
    ["Reference solver (Bayesian canary trap)", r.solver.correct ? "correct" : "wrong or none", r.solver.final_day, r.solver.tool_calls, r.solver.score],
    ...ref.map((a) => [a.agent, a.note || "committed run, same seed", "–", "–", a.score]),
  ];
  const bar = (s) => {
    if (s === null || s === undefined) return h("span", { class: "dim" }, "–");
    const w = Math.min(50, Math.abs(s) * 50);
    return h("div", { class: "bar" }, h("span", { class: "zero" }),
      h("i", { class: s < 0 ? "neg" : "", style: s < 0 ? `right:50%;width:${w}%` : `left:50%;width:${w}%` }));
  };
  const sec = $("closed");
  sec.textContent = "";
  sec.append(
    h("div", { class: "sheet-h" }, h("span", {}, "Case closed"), h("span", { class: "mono" }, `case no. ${r.seed} · ${r.tier} · tiers ${r.tiers_version}`)),
    h("div", { class: "verdict" },
      h("div", {}, h("h2", {}, "The mole was ", h("span", { class: "mono" }, r.mole), mole ? `, ${mole.name}` : "", "."),
        h("p", { class: "lead" }, mole ? `${mole.dept}, ${mole.role}. ` : "", youLine)),
      h("div", {}, h("div", { class: "lbl" }, "Your score"), h("div", { class: `scoreline ${you.score < 0 ? "neg" : ""}` }, fmt(you.score)),
        h("p", { class: "dim" }, "Score = the company's true value at a correct accusation, −1 for a wrong one, 0 for none."))),
    h("div", { class: "cmp" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, h("th", {}, "Investigator"), h("th", {}, "Outcome"), h("th", { class: "num" }, "Day"), h("th", { class: "num" }, "Calls"), h("th", { class: "num" }, "Score"), h("th", {}, ""))),
      h("tbody", {}, rows.map(([who, out, day, calls, s]) => h("tr", {},
        h("td", {}, h("b", {}, who)), h("td", {}, out), h("td", { class: "num" }, day), h("td", { class: "num" }, calls),
        h("td", { class: "num" }, s === null || s === undefined ? "–" : fmt(s)), h("td", {}, bar(s))))))),
    h("div", { class: "actions" },
      h("button", { class: "primary", type: "button", onclick: () => { location.search = "?seed=" + randomSeed(); } }, "Open another case"),
      h("button", { class: "ghost", type: "button", onclick: download }, "Download my actions (JSON)")));
  if (!ref.length) sec.querySelector("tbody").append(h("tr", {}, h("td", {}, h("b", {}, "AI agents")), h("td", { class: "dim", colspan: 5 }, "no committed agent run on this seed")));
  sec.hidden = false;
  sec.scrollIntoView({ behavior: "smooth", block: "start" });
}

function download() {
  const blob = new Blob([S.game.actions_json()], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `canary-case-${S.seed}-actions.json`;
  a.click();
}

// ------------------------------------------------------------------ global behaviour
function renderAll() { renderVitals(); renderRoster(); renderBar(); renderForm(); }

function setAgent(on) {
  document.body.classList.toggle("agent", on);
  $("agentBtn").setAttribute("aria-pressed", String(on));
}

const hlStyle = document.createElement("style");
document.head.append(hlStyle);
document.addEventListener("mouseover", (ev) => {
  const t = ev.target.closest && ev.target.closest("[data-pid]");
  const id = t ? t.getAttribute("data-pid") : null;
  hlStyle.textContent = id && /^[\w-]+$/.test(id)
    ? `.pid[data-pid="${id}"], .t[data-pid="${id}"] { background: var(--hl); color: var(--on-hl); } .row[data-pid="${id}"] { background: var(--sheet-h); }` : "";
});
document.addEventListener("keydown", (ev) => {
  if (ev.key.toLowerCase() === "j" && !/INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName) && !$("agentBtn").disabled) {
    setAgent(!document.body.classList.contains("agent"));
  }
});

$("openCase").addEventListener("submit", start);
$("cmdform").addEventListener("submit", (ev) => {
  ev.preventDefault();
  if (S.over || !S.tool) return;
  if (S.tool === "accuse") { openAccuse(($("cmdform").querySelector("[name=employee]") || {}).value || ""); return; }
  if (S.tool === "plant_canary" && (!Object.keys(S.assign).length || !(S.draft.doc_title || "").trim())) return;
  run(S.tool, readForm());
});
$("agentBtn").addEventListener("click", () => setAgent(!document.body.classList.contains("agent")));
$("rulesBtn").addEventListener("click", () => $("rulesDlg").showModal());
$("rulesClose").addEventListener("click", () => $("rulesDlg").close());
if ($("accuseDlg")) {
  for (const id of ["accWho", "accArm", "accP"]) $(id).addEventListener("input", updateAccuse);
  $("accWho").addEventListener("change", updateAccuse);
  $("accClose").addEventListener("click", () => $("accuseDlg").close());
  $("accCancel").addEventListener("click", () => $("accuseDlg").close());
  $("accForm").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const e = $("accWho").value;
    if (S.over || !e || $("accArm").value.trim() !== e) return;
    $("accuseDlg").close();
    S.tool = "accuse";
    run("accuse", { employee: e });
  });
}
boot();
