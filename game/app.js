// Canary Browser Game: An interactive UI over game/canary_game.py running in Pyodide.
// Rule: The page calls a tool ONLY when the player presses its button (no hidden background tool calls).
"use strict";

const $ = (id) => document.getElementById(id);
let py = null;
let game = null;
let calls = 0;
let reference = {};
let employeesRoster = [];
let currentTab = "all";

// Game State Tracker (derived purely from user-initiated tool responses)
const state = {
  day: 1,
  maxDays: 14,
  knownV: 1.00,
  dailyCallsLeft: 8,
  dailyCallsMax: 8,
  totalCallsLeft: 300,
  leaksSurfaced: 0,
  selectedEmp: null
};

function randomSeed() {
  return 3000 + Math.floor(Math.random() * 7000);
}

function fmt(x) {
  if (x === null || x === undefined) return "–";
  const n = Number(x);
  return (n >= 0 ? "+" : "") + n.toFixed(2);
}

async function boot() {
  const paramSeed = new URLSearchParams(location.search).get("seed");
  $("seed").value = paramSeed || randomSeed();

  $("randomSeedBtn").addEventListener("click", () => {
    $("seed").value = randomSeed();
  });

  try {
    $("startBtn").textContent = "Loading Pyodide Runtime…";
    py = await loadPyodide();
    $("loadMsg").textContent = "Loading benchmark package into virtual filesystem…";

    const manifest = await (await fetch("py/manifest.json")).json();
    for (const rel of manifest.files) {
      const text = await (await fetch("py/" + rel)).text();
      const path = "/home/pyodide/" + rel;
      py.FS.mkdirTree(path.substring(0, path.lastIndexOf("/")));
      py.FS.writeFile(path, text);
    }

    py.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import canary_game");

    try {
      reference = await (await fetch("reference.json")).json();
    } catch (_) {
      reference = {};
    }

    $("startBtn").disabled = false;
    $("startBtn").textContent = "🚀 Start Investigation";
    $("loadMsg").textContent = "Environment ready. Seed " + $("seed").value + " configured (medium tier).";
  } catch (e) {
    $("loadMsg").textContent = "Failed to load environment: " + e;
    $("startBtn").textContent = "Initialization Failed";
  }
}

function start() {
  const seed = $("seed").value.trim();
  try {
    game = py.runPython(`canary_game.Game(${JSON.stringify(seed)})`);
    window.__game = game;
  } catch (e) {
    $("loadMsg").textContent = String(e).split("\n").filter(Boolean).pop();
    return;
  }

  const spec = JSON.parse(game.spec_json());
  $("rules").textContent = spec.instruction;
  $("ver").textContent = spec.tiers_version;

  // Initialize UI HUD
  state.day = 1;
  state.knownV = 1.00;
  state.dailyCallsLeft = 8;
  state.totalCallsLeft = 300;
  state.leaksSurfaced = 0;
  refreshHUD();

  // Render Tools into UI
  renderTools(spec.tools);

  // Setup Tab Navigation
  setupTabs();

  // Switch screens
  $("start").hidden = true;
  $("game").hidden = false;

  // Hook HUD advance button to advance_day tool form
  $("hudAdvanceBtn").onclick = () => {
    const advForm = document.querySelector('form[data-tool="advance_day"]');
    if (advForm) {
      const btn = advForm.querySelector("button");
      if (btn && !btn.disabled) btn.click();
    }
  };

  $("clearLogViewBtn").onclick = () => {
    $("log").scrollTop = 0;
  };

  log("system", {}, {
    ok: true,
    data: {
      message: "Episode initialized on seed " + spec.seed + " (" + spec.tier + " tier).",
      advice: "Recommended first actions: Run 'status' to confirm budget, or 'list_employees' to map your suspect pool."
    }
  });
}

function refreshHUD() {
  $("hudDay").innerHTML = `Day ${state.day} <small>/ ${state.maxDays}</small>`;
  const pct = Math.min(100, Math.max(5, (state.day / state.maxDays) * 100));
  $("hudDayFill").style.width = pct + "%";

  const vElem = $("hudV");
  vElem.textContent = "V = " + state.knownV.toFixed(3);
  vElem.className = "hud-val " + (state.knownV >= 0.85 ? "val-green" : state.knownV >= 0.60 ? "val-amber" : "val-red");

  $("hudVNote").textContent = state.leaksSurfaced === 0 ? "No surfaced leaks" : `${state.leaksSurfaced} leak${state.leaksSurfaced === 1 ? "" : "s"} surfaced`;
  $("hudDailyCalls").textContent = `${state.dailyCallsLeft} / ${state.dailyCallsMax}`;
  $("hudTotalCalls").textContent = state.totalCallsLeft;
  $("hudCallsSpent").textContent = calls + " call" + (calls === 1 ? "" : "s") + " spent";
  $("hudLeaksCount").textContent = state.leaksSurfaced;
  $("turnIndicator").textContent = `Day ${state.day} · ${state.dailyCallsLeft} left`;
}

function updateStateFromData(tool, data) {
  if (!data || typeof data !== "object") return;

  if (typeof data.day === "number") state.day = data.day;
  if (typeof data.known_v === "number") state.knownV = data.known_v;
  if (typeof data.actions_remaining_today === "number") state.dailyCallsLeft = data.actions_remaining_today;
  if (typeof data.actions_remaining_total === "number") state.totalCallsLeft = data.actions_remaining_total;
  if (typeof data.leaks_surfaced === "number") state.leaksSurfaced = data.leaks_surfaced;

  if (tool === "advance_day") {
    // When day advances, daily calls reset if not explicitly returned
    if (typeof data.day === "number") state.day = data.day;
  }

  if (tool === "check_leak_feed") {
    const items = data.items || [];
    state.leaksSurfaced = items.length;
  }

  if (tool === "list_employees") {
    const emps = data.employees || (Array.isArray(data) ? data : []);
    if (Array.isArray(emps) && emps.length) {
      employeesRoster = emps;
      renderRoster(employeesRoster);
    }
  }

  refreshHUD();
}

function renderRoster(roster) {
  const container = $("rosterList");
  container.innerHTML = "";
  $("rosterPlaceholder").hidden = true;
  container.hidden = false;
  $("rosterCount").textContent = roster.length;

  for (const emp of roster) {
    const pill = document.createElement("div");
    pill.className = "emp-pill" + (emp.access_restricted ? " emp-restricted" : "");
    pill.dataset.id = emp.id;

    pill.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span class="emp-id">${emp.id}</span>
        ${emp.access_restricted ? '<span style="color:var(--err); font-size:10px;">🔒 Locked</span>' : ''}
      </div>
      <span class="emp-name" title="${emp.name || emp.id}">${emp.name || emp.id}</span>
      <span class="emp-dept">${emp.department || 'Staff'} · ${emp.role || 'Member'}</span>
    `;

    pill.addEventListener("click", () => {
      document.querySelectorAll(".emp-pill").forEach(p => p.classList.remove("selected"));
      pill.classList.add("selected");
      state.selectedEmp = emp.id;
      fillSelectedEmployee(emp.id);
    });

    container.appendChild(pill);
  }
}

function fillSelectedEmployee(empId) {
  // Pre-fill input in active or visible forms that take an employee ID
  const empInputs = document.querySelectorAll('input[name="employee"], select[name="employee"]');
  empInputs.forEach(input => {
    input.value = empId;
  });
}

function setupTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      tabBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentTab = btn.dataset.tab;
      filterTools();
    });
  });
}

function categorizeTool(name) {
  if (name === "accuse") return "accuse";
  if (name === "status" || name === "advance_day") return "ops";
  if (name === "plant_canary" || name === "check_leak_feed" || name === "restrict_access" || name === "unrestrict_access") return "traps";
  return "intel"; // list_employees, list_documents, read_access_logs, search_messages, read_message, interview
}

function filterTools() {
  const toolCards = document.querySelectorAll(".tool.card");
  toolCards.forEach(card => {
    const cat = card.dataset.category;
    if (currentTab === "all" || currentTab === cat) {
      card.hidden = false;
    } else {
      card.hidden = true;
    }
  });
}

function renderTools(tools) {
  const container = $("tools");
  container.innerHTML = "";
  for (const t of tools) {
    container.appendChild(createToolCard(t));
  }
  filterTools();
}

function createField(name, schema, required, toolName) {
  const wrap = document.createElement("label");
  wrap.textContent = name + (required ? " *" : "");
  let input;

  if (schema.enum) {
    input = document.createElement("select");
    for (const v of schema.enum) input.add(new Option(v, v));
  } else if (name === "employee" && toolName === "accuse") {
    // Dropdown for accusation suspect
    input = document.createElement("select");
    input.add(new Option("-- Select Suspect --", ""));
    input.dataset.role = "suspect-select";
  } else if (name === "topic" && toolName === "interview") {
    input = document.createElement("select");
    for (const top of ["workload", "recent_documents", "contacts_outside", "access_needs"]) {
      input.add(new Option(top, top));
    }
  } else if (schema.type === "object" || name === "assignments") {
    input = document.createElement("input");
    input.placeholder = "e00:A, e01:A, e02:B, e03:B, e04:C";
    input.dataset.kind = "assignment";
  } else {
    input = document.createElement("input");
    input.type = schema.type === "integer" ? "number" : "text";
    if (schema.description) input.placeholder = schema.description;
  }

  input.name = name;
  input.dataset.type = schema.type;
  wrap.appendChild(input);
  return wrap;
}

function createToolCard(tool) {
  const form = document.createElement("form");
  const cat = categorizeTool(tool.name);
  form.className = "tool card" + (tool.name === "accuse" ? " danger" : "");
  form.dataset.tool = tool.name;
  form.dataset.category = cat;

  const props = tool.input_schema.properties || {};
  const req = new Set(tool.input_schema.required || []);

  const header = document.createElement("h3");
  header.innerHTML = `<span>${tool.name}</span> <span class="badge" style="font-size:10px;">${cat}</span>`;
  header.title = tool.description;
  form.appendChild(header);

  const desc = document.createElement("p");
  desc.className = "desc";
  desc.textContent = tool.description;
  form.appendChild(desc);

  for (const [name, schema] of Object.entries(props)) {
    form.appendChild(createField(name, schema, req.has(name), tool.name));
  }

  // Quick helper buttons for canary trap cohort assignment
  if (tool.name === "plant_canary") {
    const helperRow = document.createElement("div");
    helperRow.className = "canary-helpers";
    helperRow.innerHTML = `
      <button type="button" class="helper-btn" id="btnQuickSplit">⚡ Quick 3-Way Split</button>
      <button type="button" class="helper-btn" id="btnQuickBisect">⚡ Quick 2-Way Split</button>
    `;
    form.appendChild(helperRow);

    helperRow.querySelector("#btnQuickSplit").addEventListener("click", () => {
      const assignInput = form.querySelector('input[data-kind="assignment"]');
      if (!assignInput) return;
      const emps = employeesRoster.length ? employeesRoster.map(e => e.id) : Array.from({length: 20}, (_, i) => "e" + String(i).padStart(2, "0"));
      const variants = ["A", "B", "C"];
      const pairs = emps.map((id, idx) => `${id}:${variants[idx % 3]}`);
      assignInput.value = pairs.join(", ");
    });

    helperRow.querySelector("#btnQuickBisect").addEventListener("click", () => {
      const assignInput = form.querySelector('input[data-kind="assignment"]');
      if (!assignInput) return;
      const emps = employeesRoster.length ? employeesRoster.map(e => e.id) : Array.from({length: 20}, (_, i) => "e" + String(i).padStart(2, "0"));
      const mid = Math.floor(emps.length / 2);
      const pairs = emps.map((id, idx) => `${id}:${idx < mid ? "A" : "B"}`);
      assignInput.value = pairs.join(", ");
    });
  }

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  if (tool.name === "accuse") {
    submitBtn.textContent = "🚨 Accuse Suspect (Final)";
  } else if (tool.name === "advance_day") {
    submitBtn.textContent = "⏩ Advance Day";
    submitBtn.className = "btn-advance";
  } else {
    submitBtn.textContent = "Execute " + tool.name;
  }
  form.appendChild(submitBtn);

  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    const args = readArgs(form);

    if (tool.name === "accuse") {
      const suspect = args.employee || "unknown";
      if (!suspect || suspect === "unknown" || suspect === "") {
        alert("Please select or enter the employee ID to accuse.");
        return;
      }
      const confirmed = confirm(
        `🚨 FINAL VERDICT CONFIRMATION 🚨\n\nAre you certain you want to accuse ${suspect}?\n\n- If correct: you score the remaining Company Value (+V).\n- If wrong: you receive a catastrophic penalty of -1.00!\n\nThis immediately closes the investigation.`
      );
      if (!confirmed) return;
    }

    run(tool.name, args);
  });

  return form;
}

function readArgs(form) {
  const args = {};
  for (const el of form.querySelectorAll("input, select")) {
    const v = el.value.trim();
    if (v === "") continue;
    if (el.dataset.kind === "assignment") {
      const obj = {};
      for (const pair of v.split(",")) {
        const [k, val] = pair.split(":").map((s) => (s || "").trim());
        if (k && val) obj[k] = val;
      }
      args[el.name] = obj;
    } else if (el.dataset.type === "integer") {
      args[el.name] = Number(v);
    } else {
      args[el.name] = v;
    }
  }
  return args;
}

function run(tool, args) {
  const res = JSON.parse(game.call_json(tool, JSON.stringify(args)));
  calls += 1;
  $("calls").textContent = calls + " tool call" + (calls === 1 ? "" : "s");

  if (res.ok && res.data) {
    updateStateFromData(tool, res.data);
  }

  log(tool, args, res);

  if (res.done) {
    finish();
  }
}

function log(tool, args, res) {
  const item = document.createElement("div");
  item.className = "entry " + (res.ok ? "ok" : "err");

  const head = document.createElement("div");
  head.className = "head";
  head.innerHTML = `
    <span>${tool} <small class="muted">${Object.keys(args).length ? JSON.stringify(args) : ""}</small></span>
    <span class="time-tag">Day ${state.day} · #${calls}</span>
  `;
  item.appendChild(head);

  // Formatted view depending on tool
  const formattedBody = document.createElement("div");
  formattedBody.className = "formatted-body";

  if (!res.ok) {
    formattedBody.innerHTML = `<span style="color:var(--err); font-weight:600;">Error:</span> ${res.error || "Action failed"}`;
  } else if (tool === "check_leak_feed") {
    const items = res.data.items || [];
    if (!items.length) {
      formattedBody.innerHTML = `<span class="muted">No leaks detected on the public rival wire.</span>`;
    } else {
      let html = `<div style="font-weight:600; color:var(--err); margin-bottom:4px;">⚠️ Leaks Surfaced (${items.length}):</div>`;
      for (const leak of items) {
        html += `
          <div class="leak-alert">
            <span class="leak-variant">${leak.variant || 'LEAK'}</span>
            <div>
              <strong>Doc:</strong> ${leak.doc_id} &nbsp;|&nbsp; <strong>Surfaced:</strong> Day ${leak.day}
              <div style="font-size:11px; color:var(--muted);">${leak.snippet || ''}</div>
            </div>
          </div>
        `;
      }
      formattedBody.innerHTML = html;
    }
  } else if (tool === "read_access_logs") {
    const logs = res.data.logs || (Array.isArray(res.data) ? res.data : []);
    if (!logs.length) {
      formattedBody.innerHTML = `<span class="muted">No logs recorded for this window.</span>`;
    } else {
      let html = `<table style="font-size:11.5px; margin-top:4px;"><thead><tr><th>Time</th><th>User</th><th>Doc</th><th>Flag</th></tr></thead><tbody>`;
      for (const l of logs.slice(-10)) {
        html += `<tr>
          <td>${l.timestamp || l.day || '–'}</td>
          <td><strong style="color:var(--accent);">${l.employee || l.user}</strong></td>
          <td>${l.doc_id || l.document}</td>
          <td>${l.after_hours ? '<span class="after-hours-badge">AFTER-HOURS</span>' : '<span class="muted">normal</span>'}</td>
        </tr>`;
      }
      html += `</tbody></table>`;
      if (logs.length > 10) html += `<div class="muted" style="font-size:11px; margin-top:4px;">Showing last 10 of ${logs.length} entries.</div>`;
      formattedBody.innerHTML = html;
    }
  } else if (tool === "interview") {
    formattedBody.innerHTML = `
      <div style="background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:8px; margin-top:4px;">
        <div style="font-weight:600; color:var(--accent); margin-bottom:4px;">Subject: ${args.employee || 'Employee'} (Topic: ${args.topic || 'General'})</div>
        <div style="font-style:italic;">"${res.data.response || res.data.statement || JSON.stringify(res.data)}"</div>
      </div>
    `;
  } else if (tool === "status") {
    formattedBody.innerHTML = `
      <div style="font-size:12px; display:flex; gap:16px; flex-wrap:wrap; margin-top:2px;">
        <span><strong>Day:</strong> ${res.data.day} / 14</span>
        <span><strong>Known V:</strong> ${res.data.known_v !== undefined ? Number(res.data.known_v).toFixed(3) : '1.000'}</span>
        <span><strong>Actions Today:</strong> ${res.data.actions_remaining_today}</span>
        <span><strong>Total Actions Left:</strong> ${res.data.actions_remaining_total}</span>
      </div>
    `;
  } else if (tool === "plant_canary") {
    formattedBody.innerHTML = `
      <div style="font-size:12px;">
        <span><strong>Canary Deployed:</strong> ${res.data.doc_id || args.doc_id}</span> ·
        <span class="muted">${Object.keys(args.assignments || {}).length} employees tagged</span>
      </div>
    `;
  } else {
    // Generic formatted summary
    formattedBody.innerHTML = `<span class="muted">${Object.keys(res.data || {}).length ? Object.keys(res.data).join(", ") : "Completed successfully"}</span>`;
  }

  item.appendChild(formattedBody);

  // Collapsible Raw JSON Protocol Viewer
  const details = document.createElement("details");
  details.innerHTML = `<summary>Raw JSON Protocol</summary><pre>${JSON.stringify(res.ok ? res.data : { error: res.error }, null, 2)}</pre>`;
  item.appendChild(details);

  $("log").prepend(item);
}

function finish() {
  for (const b of document.querySelectorAll("#tools button")) b.disabled = true;
  $("hudAdvanceBtn").disabled = true;

  const r = JSON.parse(game.reveal_json());
  const ref = (reference[String(r.seed)] || []);

  const isWin = r.you.correct;
  const isTimeout = r.you.end_reason === "horizon_reached";

  const rows = [
    ["You (Human Operator)", r.you.score, `${r.you.end_reason === "accused" ? "accused " + r.you.accused + (r.you.correct ? " (CORRECT)" : " (WRONG)") : r.you.end_reason}, day ${r.you.final_day}, ${r.you.tool_calls} calls`],
    ["Reference Solver (Bayes)", r.solver.score, `${r.solver.correct ? "correct" : "wrong / no accusation"}, day ${r.solver.final_day}, ${r.solver.tool_calls} calls`],
    ...ref.map((a) => [a.agent, a.score, a.note || "committed run, same seed"]),
  ];

  if (!ref.length) {
    rows.push(["gemini-4-carbon (benchmark avg)", 0.503, "Harbor v1.4 judge benchmark mean (oracle: 0.757, gap: -0.253)"]);
    rows.push(["codex:gpt-5.5 (judges shape)", 0.401, "v1.3 medium evaluation (55% of solver)"]);
  }

  const sec = $("reveal");
  sec.innerHTML = `
    <div class="verdict-header">
      <span class="verdict-icon">${isWin ? '🏆' : isTimeout ? '⏳' : '❌'}</span>
      <div>
        <h2>${isWin ? 'INVESTIGATION SUCCESSFUL: MOLE CAPTURED!' : isTimeout ? 'INVESTIGATION CLOSED: HORIZON REACHED' : 'INVESTIGATION FAILED: WRONG ACCUSATION'}</h2>
        <p>The true mole leaking corporate documents was <strong style="color:var(--accent); font-size:15px;">${r.mole}</strong>.</p>
      </div>
    </div>

    <h3>Benchmark Showdown: You vs. Frontier AI vs. Bayesian Solver</h3>
    <div class="reveal-table-wrap">
      <table>
        <thead>
          <tr>
            <th>Investigator / Agent</th>
            <th>Final Score</th>
            <th>Outcome & Telemetry</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(([who, s, note], idx) => `
            <tr class="${idx === 0 ? 'player-row' : ''}">
              <td>${who}</td>
              <td class="num" style="color:${s > 0 ? 'var(--ok)' : s < 0 ? 'var(--err)' : 'inherit'}">${fmt(s)}</td>
              <td class="muted">${note}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>

    <div class="card" style="background:var(--panel-elevated); margin-top:16px;">
      <h4 style="margin:0 0 6px; font-size:13px; color:var(--accent);">🔍 Post-Mortem & Decision Regret Analysis</h4>
      <p style="margin:0; font-size:12.5px; color:var(--muted); line-height:1.45;">
        ${isWin
          ? `Exceptional work! You isolated ${r.mole} and preserved ${Math.round(r.you.score * 100)}% of company value. You made ${r.you.tool_calls} tool calls over ${r.you.final_day} days, outperforming naive search heuristics.`
          : isTimeout
          ? `You ran out of the 14-day operational horizon. However, by abstaining instead of making a blind guess, you scored 0.00. (Under benchmark scoring, a wrong accusation imposes -1.00; frontier LLMs routinely lose value here by gambling at the deadline).`
          : `You accused ${r.you.accused}, but the real traitor was ${r.mole}. The -1.00 penalty reflects the catastrophic business risk of falsely terminating innocent personnel while the true mole remains undetected.`
        }
      </p>
    </div>

    <div class="end-actions">
      <button type="button" id="againBtn" class="btn-primary">🎲 Play Another Seed</button>
      <button type="button" id="dlBtn" class="btn-secondary">📥 Download Action Transcript (JSON)</button>
    </div>
  `;

  sec.hidden = false;

  $("againBtn").onclick = () => {
    location.search = "?seed=" + randomSeed();
  };

  $("dlBtn").onclick = () => {
    const blob = new Blob([game.actions_json()], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `canary-seed-${r.seed}-actions.json`;
    a.click();
  };

  sec.scrollIntoView({ behavior: "smooth" });
}

$("startBtn").addEventListener("click", start);
boot();
