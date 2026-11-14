// Canary Browser Game: Full Interactive UI over game/canary_game.py in Pyodide.
// Core Mandates:
// 1. All logic goes through Game (spec_json, call_json, reveal_json). Never re-implement rules in JS.
// 2. Never call a tool the player didn't trigger (no hidden calls, no automatic status calls).
// 3. Truth is revealed only after the episode is completed.
// 4. Honest labeling: gemini-4-carbon and codex numbers are BENCHMARK MEANS, not per-seed scores.
"use strict";

const $ = (id) => document.getElementById(id);

let py = null;
let game = null;
let callsSpent = 0;
let referenceData = {};
let tutorialStep = 0;

// Application and Episode State
const state = {
  seed: 3000,
  tier: "medium",
  tiersVersion: "v1.4",
  day: 1,
  maxDays: 14,
  knownV: 1.000,
  actionsLeftToday: 8,
  dailyCallsMax: 8,
  totalCallsLeft: 300,
  leaksCount: 0,
  employees: [], // populated ONLY after player triggers list_employees
  userTags: {}, // client-side notes: { [empId]: "suspect" | "cleared" | "unsure" }
  canaryAssignments: {}, // { [empId]: "A" | "B" | "C" }
  canaryHistory: [], // records of planted canaries
  restricted: new Set(),
  selectedEmpId: null,
  enteredCertainty: 60,
  chosenSuspect: null,
  playerAbstained: false,
  actionHistory: [], // [[tool, args, day], ...]
  feedFilter: "all"
};

const DEPT_COLORS = {
  Engineering: "var(--team-eng)",
  Finance: "var(--team-fin)",
  Sales: "var(--team-sales)",
  Legal: "var(--team-legal)",
  Research: "var(--team-res)"
};

function randomSeed() {
  return 3000 + Math.floor(Math.random() * 7000);
}

function fmt(x) {
  if (x === null || x === undefined) return "–";
  const n = Number(x);
  return (n >= 0 ? "+" : "") + n.toFixed(3);
}

// -----------------------------------------------------------------------------
// BOOT & PYODIDE INITIALIZATION
// -----------------------------------------------------------------------------
async function boot() {
  const urlParams = new URLSearchParams(location.search);
  const paramSeed = urlParams.get("seed");
  const isDemo = urlParams.get("demo") === "1" || urlParams.get("demo") === "true";

  if (isDemo) {
    document.body.classList.add("demo-mode");
    const demoBtn = $("demoToggleBtn");
    if (demoBtn) demoBtn.textContent = "📺 Standard View";
  }

  const initialSeed = paramSeed ? parseInt(paramSeed, 10) : randomSeed();
  state.seed = (initialSeed >= 3000 && initialSeed <= 9999) ? initialSeed : 3000;
  $("seedInput").value = state.seed;
  $("headerSeedDisplay").textContent = state.seed;

  setupGlobalEventListeners();

  try {
    updateLoader(10, "Initializing Pyodide sandbox environment...");
    py = await loadPyodide();

    updateLoader(45, "Loading benchmark package into virtual filesystem...");
    const manifestRes = await fetch("py/manifest.json");
    if (!manifestRes.ok) throw new Error("Could not find py/manifest.json. Run build.py first.");
    const manifest = await manifestRes.json();

    let loaded = 0;
    for (const rel of manifest.files) {
      const text = await (await fetch("py/" + rel)).text();
      const path = "/home/pyodide/" + rel;
      py.FS.mkdirTree(path.substring(0, path.lastIndexOf("/")));
      py.FS.writeFile(path, text);
      loaded++;
      const pct = 45 + Math.floor((loaded / manifest.files.length) * 45);
      updateLoader(pct, `Loading benchmark modules (${loaded}/${manifest.files.length})...`);
    }

    updateLoader(95, "Initializing canary_game module in Python...");
    py.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import canary_game");

    try {
      const refRes = await fetch("reference.json");
      if (refRes.ok) referenceData = await refRes.json();
    } catch (_) {
      referenceData = {};
    }

    updateLoader(100, "Benchmark runtime ready! Start your investigation.");
    $("playBtn").disabled = false;
    $("playBtn").textContent = "🚀 Start Investigation";
    $("startTutorialBtn").disabled = false;
  } catch (err) {
    $("loadMsg").textContent = "Failed to load engine: " + err.message;
    $("playBtn").textContent = "⚠️ Engine Initialization Failed";
    console.error("Boot error:", err);
  }
}

function updateLoader(percent, message) {
  $("loadPercent").textContent = percent + "%";
  $("loadBar").style.width = percent + "%";
  $("loadMsg").textContent = message;
}

// -----------------------------------------------------------------------------
// GAME START & RESET
// -----------------------------------------------------------------------------
function startGame(customSeed = null) {
  const seedVal = customSeed !== null ? customSeed : parseInt($("seedInput").value.trim(), 10);
  if (isNaN(seedVal) || seedVal < 3000 || seedVal > 9999) {
    alert("Please enter a valid public dev seed between 3000 and 9999.");
    return;
  }
  state.seed = seedVal;
  $("headerSeedDisplay").textContent = state.seed;

  try {
    game = py.runPython(`canary_game.Game(${state.seed})`);
    window.__canary_game = game;
  } catch (err) {
    alert("Engine error: " + err);
    return;
  }

  const spec = JSON.parse(game.spec_json());
  state.tier = spec.tier;
  state.tiersVersion = spec.tiers_version;
  $("tierChip").textContent = (spec.tier.charAt(0).toUpperCase() + spec.tier.slice(1)) + " Tier";
  $("benchmarkRulesText").textContent = spec.instruction;

  // Reset episode state
  callsSpent = 0;
  state.day = 1;
  state.maxDays = 14;
  state.knownV = 1.000;
  state.actionsLeftToday = 8;
  state.dailyCallsMax = 8;
  state.totalCallsLeft = 300;
  state.leaksCount = 0;
  state.employees = [];
  state.userTags = {};
  state.canaryAssignments = {};
  state.canaryHistory = [];
  state.restricted.clear();
  state.selectedEmpId = null;
  state.actionHistory = [];
  state.playerAbstained = false;

  refreshHUD();
  renderExpertTools(spec.tools);

  // Switch screens
  $("titleScreen").hidden = true;
  $("endScreen").hidden = true;
  $("investigationScreen").hidden = false;

  // Show unsurveyed notice initially
  $("officeUnsurveyedNotice").hidden = false;
  $("officeTeamsContainer").hidden = true;
  $("empDossierCard").hidden = true;

  // Clean evidence feed
  $("evidenceFeed").innerHTML = `
    <div class="feed-item system-entry" data-category="system">
      <div class="feed-head">
        <span class="feed-badge system-badge" style="background:var(--accent); color:#0b0f17;">OPERATIONS READY</span>
        <span class="mono muted font-small">Day 1 · Seed ${state.seed}</span>
      </div>
      <div class="feed-body">
        <p>Investigation initiated. Someone in the company is leaking secrets to rival firm.</p>
        <p class="muted font-small">First action: Survey personnel with <strong>Survey Office Personnel (1 action)</strong> or deploy marked traps via <strong>Plant Canaries [P]</strong>.</p>
      </div>
    </div>
  `;
}

// -----------------------------------------------------------------------------
// ENGINE TOOL DISPATCH & STATE SYNC
// -----------------------------------------------------------------------------
function executeTool(toolName, args = {}) {
  if (!game) return;
  const rawRes = game.call_json(toolName, JSON.stringify(args));
  const res = JSON.parse(rawRes);

  callsSpent++;
  state.actionHistory.push({ tool: toolName, args, day: state.day, ok: res.ok });

  // Decrement client-side daily actions if call succeeded
  if (res.ok) {
    if (state.actionsLeftToday > 0) state.actionsLeftToday--;
    if (state.totalCallsLeft > 0) state.totalCallsLeft--;
  }

  // Sync state from engine response
  if (res.ok && res.data) {
    syncStateFromData(toolName, args, res.data);
  }

  refreshHUD();
  addEvidenceCard(toolName, args, res);

  // If episode has concluded
  if (res.done) {
    showEndScreen();
  }
}

function syncStateFromData(tool, args, data) {
  if (!data || typeof data !== "object") return;

  if (typeof data.day === "number") state.day = data.day;
  if (typeof data.known_v === "number") state.knownV = data.known_v;
  if (typeof data.V === "number") state.knownV = data.V;
  if (typeof data.actions_remaining_today === "number") state.actionsLeftToday = data.actions_remaining_today;
  if (typeof data.actions_remaining_total === "number") state.totalCallsLeft = data.actions_remaining_total;
  if (typeof data.actions_left_today === "number") state.actionsLeftToday = data.actions_left_today;

  if (tool === "advance_day") {
    // Reset daily actions for new day
    state.actionsLeftToday = state.dailyCallsMax;
  }

  if (tool === "check_leak_feed") {
    const items = data.items || [];
    state.leaksCount = items.length;
  }

  if (tool === "list_employees") {
    const emps = data.employees || (Array.isArray(data) ? data : []);
    if (Array.isArray(emps) && emps.length > 0) {
      state.employees = emps;
      renderOfficeDirectory(state.employees);
      populateAccuseDropdown(state.employees);
    }
  }

  if (tool === "restrict_access" && data.restricted) {
    state.restricted.add(data.restricted);
    updateEmployeeCardUI(data.restricted);
  }

  if (tool === "unrestrict_access" && data.unrestricted) {
    state.restricted.delete(data.unrestricted);
    updateEmployeeCardUI(data.unrestricted);
  }

  if (tool === "plant_canary") {
    const cid = data.canary_id || `c${state.day}`;
    state.canaryHistory.push({
      id: cid,
      day: state.day,
      doc_title: args.doc_title || "Confidential Memo",
      assignment: args.assignment || {}
    });
    // Merge new variant assignments
    if (args.assignment) {
      for (const [eId, variant] of Object.entries(args.assignment)) {
        state.canaryAssignments[eId] = variant;
        updateEmployeeCardUI(eId);
      }
    }
  }
}

// -----------------------------------------------------------------------------
// HUD RENDERING (Strictly derived from state)
// -----------------------------------------------------------------------------
function refreshHUD() {
  // Calendar
  $("hudDayText").innerHTML = `Day ${state.day} <small>/ ${state.maxDays}</small>`;
  const dayPct = Math.min(100, Math.max(7, (state.day / state.maxDays) * 100));
  $("hudCalendarFill").style.width = dayPct + "%";

  // Action Pips
  const pipsContainer = $("hudPips");
  pipsContainer.innerHTML = "";
  for (let i = 0; i < state.dailyCallsMax; i++) {
    const pip = document.createElement("span");
    pip.className = "pip " + (i < state.actionsLeftToday ? "active" : "spent");
    pipsContainer.appendChild(pip);
  }
  $("hudCallsLeftToday").textContent = state.actionsLeftToday;

  // Company Value V
  const vDisplay = $("hudVVal");
  vDisplay.textContent = "V = " + state.knownV.toFixed(3);
  const vFill = $("hudVFill");
  const vPct = Math.max(0, Math.min(100, state.knownV * 100));
  vFill.style.width = vPct + "%";

  if (state.knownV >= 0.85) {
    vDisplay.className = "hud-val mono val-green";
    vFill.className = "progress-fill val-green-bg";
    $("hudVSub").textContent = "Full enterprise value intact";
  } else if (state.knownV >= 0.60) {
    vDisplay.className = "hud-val mono val-amber";
    vFill.className = "progress-fill val-amber-bg";
    $("hudVSub").textContent = "Moderate leak degradation";
  } else {
    vDisplay.className = "hud-val mono val-red";
    vFill.className = "progress-fill val-red-bg";
    $("hudVSub").textContent = "Critical enterprise damage";
  }

  // Leaks
  $("hudLeaksCount").textContent = state.leaksCount;
  $("callCounterChip").textContent = `${callsSpent} call${callsSpent === 1 ? "" : "s"}`;

  // Next Day button indicator
  const nextBtn = $("hudNextDayBtn");
  if (state.actionsLeftToday > 0) {
    nextBtn.title = `End Day ${state.day} (${state.actionsLeftToday} action(s) remain today) [N]`;
  } else {
    nextBtn.title = `All actions spent. Advance to Day ${state.day + 1} [N]`;
  }
}

// -----------------------------------------------------------------------------
// OFFICE DIRECTORY & EMPLOYEE CARDS (Left Zone)
// -----------------------------------------------------------------------------
function renderOfficeDirectory(employees) {
  $("officeUnsurveyedNotice").hidden = true;
  const container = $("officeTeamsContainer");
  container.hidden = false;
  container.innerHTML = "";
  $("officeCountBadge").textContent = `${employees.length} Personnel`;

  // Group by department
  const byDept = {};
  for (const emp of employees) {
    const dept = emp.dept || "Operations";
    if (!byDept[dept]) byDept[dept] = [];
    byDept[dept].push(emp);
  }

  for (const [dept, members] of Object.entries(byDept)) {
    const deptColor = DEPT_COLORS[dept] || "var(--accent)";

    const section = document.createElement("div");
    section.className = "team-section";
    section.innerHTML = `
      <div class="team-header">
        <span class="team-name-badge" style="background:${deptColor}20; color:${deptColor}; border:1px solid ${deptColor}40;">
          🏢 ${dept}
        </span>
        <span>${members.length} Staff</span>
      </div>
      <div class="team-grid" id="dept-grid-${dept.replace(/\s+/g, '')}"></div>
    `;

    const grid = section.querySelector(".team-grid");
    for (const emp of members) {
      grid.appendChild(createEmployeeCard(emp));
    }
    container.appendChild(section);
  }
}

function createEmployeeCard(emp) {
  const card = document.createElement("div");
  card.className = "emp-card" + (state.selectedEmpId === emp.id ? " selected" : "");
  card.id = "emp-card-" + emp.id;
  card.dataset.id = emp.id;

  card.addEventListener("click", () => {
    selectEmployee(emp.id);
  });

  updateCardContent(card, emp);
  return card;
}

function updateCardContent(card, emp) {
  const tag = state.userTags[emp.id] || "unsure";
  const canaryVariant = state.canaryAssignments[emp.id];
  const isLocked = state.restricted.has(emp.id);

  let tagBadgeHtml = "";
  if (tag === "suspect") {
    tagBadgeHtml = `<span class="tag-badge tag-suspect-bg">🔴 Suspect</span>`;
  } else if (tag === "cleared") {
    tagBadgeHtml = `<span class="tag-badge tag-cleared-bg">🟢 Cleared</span>`;
  } else {
    tagBadgeHtml = `<span class="tag-badge tag-unsure-bg">⚪ Unsure</span>`;
  }

  let canaryBadgeHtml = "";
  if (canaryVariant) {
    const varClass = canaryVariant.toLowerCase();
    canaryBadgeHtml = `
      <span class="canary-pill canary-pill-${varClass}">
        <span class="canary-dot canary-dot-${varClass}"></span>Var ${canaryVariant}
      </span>
    `;
  }

  let lockHtml = isLocked ? `<span class="locked-badge">🔒 Locked</span>` : "";

  card.innerHTML = `
    <div class="emp-card-top">
      <span class="emp-id-label">${emp.id}</span>
      ${lockHtml}
    </div>
    <div class="emp-name-label" title="${emp.name}">${emp.name}</div>
    <div class="emp-role-label">${emp.role || 'Team Member'}</div>
    <div class="emp-card-badges">
      ${tagBadgeHtml}
      ${canaryBadgeHtml}
    </div>
  `;
}

function updateEmployeeCardUI(empId) {
  const card = $("emp-card-" + empId);
  const emp = state.employees.find(e => e.id === empId);
  if (card && emp) {
    updateCardContent(card, emp);
  }
  // If this employee is currently open in the dossier, update dossier view too
  if (state.selectedEmpId === empId) {
    updateDossierView(empId);
  }
}

function selectEmployee(empId) {
  state.selectedEmpId = empId;

  document.querySelectorAll(".emp-card").forEach(c => {
    c.classList.toggle("selected", c.dataset.id === empId);
  });

  const emp = state.employees.find(e => e.id === empId);
  if (!emp) return;

  const drawer = $("empDossierCard");
  drawer.hidden = false;
  updateDossierView(empId);
  drawer.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function updateDossierView(empId) {
  const emp = state.employees.find(e => e.id === empId);
  if (!emp) return;

  $("dosId").textContent = emp.id;
  $("dosName").textContent = emp.name;
  $("dosRole").textContent = emp.role || "Member";
  $("dosDeptBadge").textContent = emp.dept || "Staff";
  $("dosDeptBadge").style.color = DEPT_COLORS[emp.dept] || "var(--accent)";

  const isLocked = state.restricted.has(emp.id);
  $("dosRestrictedBadge").hidden = !isLocked;
  $("dosRestrictBtn").textContent = isLocked ? "🔓 Restore Access" : "🔒 Restrict Access";

  const canaryVar = state.canaryAssignments[emp.id];
  const canaryBadge = $("dosCanaryBadge");
  if (canaryVar) {
    canaryBadge.hidden = false;
    canaryBadge.textContent = `Canary Variant ${canaryVar}`;
    canaryBadge.className = `canary-pill canary-pill-${canaryVar.toLowerCase()}`;
  } else {
    canaryBadge.hidden = true;
  }

  // Active tag buttons
  const currentTag = state.userTags[emp.id] || "unsure";
  document.querySelectorAll(".btn-tag").forEach(b => {
    b.classList.toggle("active", b.dataset.tag === currentTag);
  });
}

// -----------------------------------------------------------------------------
// EVIDENCE TIMELINE FEED (Right Zone)
// -----------------------------------------------------------------------------
function addEvidenceCard(tool, args, res) {
  const feed = $("evidenceFeed");
  const card = document.createElement("div");

  let category = "system";
  if (tool === "check_leak_feed") category = "leak";
  else if (tool === "interview") category = "interview";
  else if (tool === "read_access_logs") category = "logs";
  else if (tool === "plant_canary") category = "canary";
  else if (tool === "search_messages" || tool === "read_message") category = "messages";

  card.className = `feed-item ${category}-entry ${res.ok ? "" : "err"}`;
  card.dataset.category = category;

  let bodyContent = "";

  if (!res.ok) {
    bodyContent = `
      <div style="color:var(--err); font-weight:600;">
        ⚠️ Error executing ${tool}: ${res.error || "Action failed."}
      </div>
    `;
  } else if (tool === "check_leak_feed") {
    const items = res.data.items || [];
    if (!items.length) {
      bodyContent = `<p class="muted">No leaks detected on the rival firm wire as of Day ${state.day}.</p>`;
    } else {
      let html = `<div style="font-weight:700; color:var(--err); margin-bottom:6px;">⚠️ Leaked Memos Detected at Rival Firm (${items.length}):</div>`;
      for (const item of items) {
        const v = item.variant || "Unknown";
        const vClass = v.toLowerCase();
        const minDay = Math.max(1, item.surfaced_day - 3);
        const maxDay = Math.max(1, item.surfaced_day - 1);

        html += `
          <div style="background:rgba(239,68,68,0.12); border:1px solid rgba(239,68,68,0.3); border-radius:6px; padding:10px; margin-bottom:8px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
              <strong>Doc: ${item.doc_id} · "${item.title || 'Internal Memo'}"</strong>
              <span class="canary-pill canary-pill-${vClass}">Leaked Variant: ${v}</span>
            </div>
            <div class="muted font-small">${item.snippet || 'Proprietary corporate strategy data leaked.'}</div>
            <div class="leak-delay-warning">
              ⏱️ <strong>Delayed Leak Warning:</strong> Surfaced Day ${item.surfaced_day}. Leaks take 1–3 days to emerge.
              The mole exfiltrated this between <strong>Day ${minDay}</strong> and <strong>Day ${maxDay}</strong>!
            </div>
          </div>
        `;
      }
      bodyContent = html;
    }
  } else if (tool === "interview") {
    const topicLabels = {
      workload: "Workload & Stress",
      recent_documents: "Recent Documents",
      contacts_outside: "Contacts Outside",
      access_needs: "Access Needs"
    };
    bodyContent = `
      <div>
        <strong>Subject:</strong> ${args.employee} &nbsp;|&nbsp; <strong>Topic:</strong> ${topicLabels[args.topic] || args.topic}
        <div class="interview-quote">
          "${res.data.answer || res.data.statement || 'No statement provided.'}"
        </div>
        <div class="muted font-small">
          ℹ️ Evasive answers indicate higher mole probability, though innocent staff may also be evasive under stress.
        </div>
      </div>
    `;
  } else if (tool === "read_access_logs") {
    const logs = res.data.logs || [];
    if (!logs.length) {
      bodyContent = `<p class="muted">No access log entries recorded for this filter window.</p>`;
    } else {
      let html = `
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
          <span><strong>Access Logs:</strong> ${logs.length} entries (Day ${args.day_from} to ${args.day_to})</span>
        </div>
        <table class="log-table">
          <thead>
            <tr><th>Day</th><th>Staff</th><th>Document</th><th>Access Time</th></tr>
          </thead>
          <tbody>
      `;
      for (const log of logs.slice(-12)) {
        html += `
          <tr>
            <td>Day ${log.day}</td>
            <td><strong style="color:var(--accent);">${log.employee}</strong></td>
            <td>${log.doc_id}</td>
            <td>${log.after_hours ? '<span class="after-hours-tag">AFTER-HOURS</span>' : '<span class="muted">normal</span>'}</td>
          </tr>
        `;
      }
      html += `</tbody></table>`;
      if (logs.length > 12) html += `<div class="muted font-small" style="margin-top:4px;">Showing last 12 of ${logs.length} entries.</div>`;
      html += `
        <div class="muted font-small" style="margin-top:6px; color:var(--warn);">
          ⚠️ Warning: The mole frames innocent colleagues by fabricating after-hours logs!
        </div>
      `;
      bodyContent = html;
    }
  } else if (tool === "plant_canary") {
    const asg = args.assignment || {};
    const totalAssigned = Object.keys(asg).length;
    const variants = {};
    for (const v of Object.values(asg)) {
      variants[v] = (variants[v] || 0) + 1;
    }
    const varSummary = Object.entries(variants).map(([v, count]) => {
      const vClass = v.toLowerCase();
      return `<span class="canary-pill canary-pill-${vClass}">Var ${v}: ${count} staff</span>`;
    }).join(" ");

    bodyContent = `
      <div>
        <strong>Canary Deployed:</strong> "${args.doc_title || 'Memo'}" (ID: ${res.data.canary_id})
        <div style="margin: 6px 0; display:flex; gap:6px; flex-wrap:wrap;">${varSummary}</div>
        <div class="muted font-small">Total recipients tagged: ${totalAssigned} employees.</div>
      </div>
    `;
  } else if (tool === "search_messages") {
    const msgs = res.data.messages || [];
    if (!msgs.length) {
      bodyContent = `<p class="muted">No messages matching query "${args.query || ''}".</p>`;
    } else {
      let html = `<div style="font-weight:600; margin-bottom:4px;">Internal Chat Matches (${msgs.length}):</div>`;
      for (const m of msgs.slice(0, 4)) {
        html += `
          <div style="background:var(--bg); border:1px solid var(--line); border-radius:4px; padding:6px 8px; margin-bottom:4px;">
            <div style="display:flex; justify-content:space-between; font-size:11.5px;">
              <strong>${m.sender} ➔ ${m.channel || 'DM'}</strong>
              <span class="muted">Day ${m.day}</span>
            </div>
            <div style="font-weight:600; font-size:12px; color:var(--ink-bright);">${m.subject || ''}</div>
            <div class="muted font-small">${m.snippet || ''}</div>
          </div>
        `;
      }
      if (msgs.length > 4) html += `<div class="muted font-small">Showing first 4 of ${msgs.length} messages.</div>`;
      html += `<div class="muted font-small" style="margin-top:4px;">⚠️ Beware of the Decoy: An angry employee vents in chat, but is innocent!</div>`;
      bodyContent = html;
    }
  } else if (tool === "advance_day") {
    bodyContent = `
      <p>Advanced to <strong>Day ${state.day}</strong> of ${state.maxDays}. Daily actions reset to ${state.dailyCallsMax}.</p>
    `;
  } else if (tool === "list_employees") {
    bodyContent = `
      <p>Office personnel surveyed. Cataloged <strong>${(res.data.employees || []).length} employees</strong> across departments.</p>
    `;
  } else if (tool === "restrict_access") {
    bodyContent = `
      <p>🔒 Access restricted for employee <strong>${args.employee}</strong>.</p>
    `;
  } else if (tool === "unrestrict_access") {
    bodyContent = `
      <p>🔓 Access permissions restored for <strong>${args.employee}</strong>.</p>
    `;
  } else {
    bodyContent = `<p class="muted">${tool} completed successfully.</p>`;
  }

  const toolBadge = tool.toUpperCase().replace(/_/g, " ");
  card.innerHTML = `
    <div class="feed-head">
      <span class="feed-badge">${toolBadge}</span>
      <span class="mono muted font-small">Day ${state.day} · #${callsSpent}</span>
    </div>
    <div class="feed-body">${bodyContent}</div>
    <details>
      <summary>Raw JSON Protocol</summary>
      <pre>${JSON.stringify(res.ok ? res.data : { error: res.error }, null, 2)}</pre>
    </details>
  `;

  feed.prepend(card);
  filterFeed();
}

function filterFeed() {
  const items = document.querySelectorAll(".feed-item");
  items.forEach(item => {
    const cat = item.dataset.category;
    if (state.feedFilter === "all" || cat === state.feedFilter) {
      item.hidden = false;
    } else {
      item.hidden = true;
    }
  });
}

// -----------------------------------------------------------------------------
// CANARY PLANTING WIZARD (Screen 4)
// -----------------------------------------------------------------------------
function openCanaryWizard() {
  if (state.employees.length === 0) {
    alert("Please survey the office personnel first so staff IDs are indexed.");
    return;
  }

  $("canaryDocTitle").value = `Q${Math.min(4, Math.ceil(state.day / 3.5))} Confidential Strategy & Acquisition Memo`;
  renderWizardEmployees();
  updateWholeCompanyWarning();
  $("canaryModal").hidden = false;
}

function closeCanaryWizard() {
  $("canaryModal").hidden = true;
}

function renderWizardEmployees() {
  const grid = $("wizardEmpGrid");
  grid.innerHTML = "";

  for (const emp of state.employees) {
    const chip = document.createElement("div");
    chip.className = "wizard-emp-chip";
    chip.dataset.id = emp.id;

    const currentVar = state.canaryAssignments[emp.id] || "";
    if (currentVar) chip.classList.add(`assign-${currentVar.toLowerCase()}`);

    chip.innerHTML = `
      <span><strong>${emp.id}</strong> ${emp.name.split(" ")[0]}</span>
      <span class="mono font-small chip-var">${currentVar || '–'}</span>
    `;

    chip.addEventListener("click", () => {
      // Cycle: "" -> "A" -> "B" -> "C" -> ""
      const variants = ["", "A", "B", "C"];
      const nextIdx = (variants.indexOf(currentVar) + 1) % variants.length;
      const nextVar = variants[nextIdx];

      chip.classList.remove("assign-a", "assign-b", "assign-c");
      if (nextVar) chip.classList.add(`assign-${nextVar.toLowerCase()}`);
      chip.querySelector(".chip-var").textContent = nextVar || "–";
      state.canaryAssignments[emp.id] = nextVar;
      updateWholeCompanyWarning();
    });

    grid.appendChild(chip);
  }
}

function updateWholeCompanyWarning() {
  const chips = document.querySelectorAll(".wizard-emp-chip");
  const assigned = [];
  chips.forEach(c => {
    const v = c.querySelector(".chip-var").textContent.trim();
    if (v && v !== "–") assigned.push(v);
  });

  const unique = new Set(assigned);
  const warn = $("wholeCoWarning");
  if (assigned.length === state.employees.length && unique.size === 1) {
    warn.style.display = "block";
  } else {
    warn.style.display = "none";
  }
}

function wizardSplit(numWays) {
  const variants = numWays === 2 ? ["A", "B"] : ["A", "B", "C"];
  const chips = document.querySelectorAll(".wizard-emp-chip");
  chips.forEach((c, idx) => {
    const v = variants[idx % numWays];
    c.classList.remove("assign-a", "assign-b", "assign-c");
    c.classList.add(`assign-${v.toLowerCase()}`);
    c.querySelector(".chip-var").textContent = v;
    state.canaryAssignments[c.dataset.id] = v;
  });
  updateWholeCompanyWarning();
}

function wizardSplitByDept() {
  const deptMap = {
    Engineering: "A",
    Research: "A",
    Finance: "B",
    Sales: "B",
    Legal: "C"
  };
  const chips = document.querySelectorAll(".wizard-emp-chip");
  chips.forEach(c => {
    const emp = state.employees.find(e => e.id === c.dataset.id);
    const v = (emp && deptMap[emp.dept]) || "A";
    c.classList.remove("assign-a", "assign-b", "assign-c");
    c.classList.add(`assign-${v.toLowerCase()}`);
    c.querySelector(".chip-var").textContent = v;
    state.canaryAssignments[c.dataset.id] = v;
  });
  updateWholeCompanyWarning();
}

function submitCanaryWizard() {
  const title = $("canaryDocTitle").value.trim() || "Confidential Memo";
  const assignment = {};

  const chips = document.querySelectorAll(".wizard-emp-chip");
  chips.forEach(c => {
    const v = c.querySelector(".chip-var").textContent.trim();
    if (v && v !== "–") assignment[c.dataset.id] = v;
  });

  if (Object.keys(assignment).length === 0) {
    alert("Please assign at least one employee to a canary variant.");
    return;
  }

  const uniqueVariants = new Set(Object.values(assignment));
  if (uniqueVariants.size > 3) {
    alert("Maximum of 3 variants (A, B, C) allowed in medium tier.");
    return;
  }

  closeCanaryWizard();
  executeTool("plant_canary", { doc_title: title, assignment });
}

// -----------------------------------------------------------------------------
// ACCUSE DIALOG & BREAK-EVEN MATH (Screen 3: The Teaching Moment)
// -----------------------------------------------------------------------------
function openAccuseDialog(preselectEmpId = null) {
  if (state.employees.length === 0) {
    alert("Please survey the office personnel first so staff IDs are indexed.");
    return;
  }

  populateAccuseDropdown(state.employees);

  if (preselectEmpId) {
    $("accuseSuspectSelect").value = preselectEmpId;
  } else if (state.selectedEmpId) {
    $("accuseSuspectSelect").value = state.selectedEmpId;
  }

  updateAccuseTargetName();
  recalculateAccuseMath();
  $("accuseModal").hidden = false;
}

function closeAccuseDialog() {
  $("accuseModal").hidden = true;
}

function populateAccuseDropdown(employees) {
  const select = $("accuseSuspectSelect");
  const current = select.value;
  select.innerHTML = `<option value="">-- Choose Employee to Accuse --</option>`;
  for (const emp of employees) {
    const opt = document.createElement("option");
    opt.value = emp.id;
    opt.textContent = `${emp.id} - ${emp.name} (${emp.dept || 'Staff'}, ${emp.role || 'Member'})`;
    select.appendChild(opt);
  }
  if (current) select.value = current;
}

function updateAccuseTargetName() {
  const empId = $("accuseSuspectSelect").value;
  const emp = state.employees.find(e => e.id === empId);
  $("accuseTargetBtnName").textContent = emp ? `${emp.name} (${emp.id})` : "Suspect";
}

function recalculateAccuseMath() {
  const p = parseInt($("certaintySlider").value, 10) / 100;
  state.enteredCertainty = Math.round(p * 100);
  $("certaintyDisplay").textContent = state.enteredCertainty + "%";

  const V = state.knownV;
  const breakEvenP = 1 / (1 + V);
  const ev = (p * V) - ((1 - p) * 1.0);

  $("mathVDisplay").textContent = `V = ${V.toFixed(3)}`;
  $("mathBreakEvenDisplay").textContent = `p* = ${(breakEvenP * 100).toFixed(1)}%`;
  $("mathEVDisplay").textContent = (ev >= 0 ? "+" : "") + ev.toFixed(2);
  $("mathEVDisplay").style.color = ev >= 0 ? "var(--ok)" : "var(--warn)";

  const adviceBox = $("mathAdviceBox");
  const adviceText = $("mathAdviceText");

  if (p < breakEvenP) {
    adviceBox.className = "math-advice-box advice-unfavorable";
    adviceText.innerHTML = `
      ⚠️ <strong>At this certainty (${state.enteredCertainty}%), not accusing scores better on average</strong>
      (EV = ${ev.toFixed(2)} vs 0.00).<br>
      This is exactly the mistake frontier AI agents make: gambling at the deadline instead of having the sense to abstain!
    `;
  } else {
    adviceBox.className = "math-advice-box advice-favorable";
    adviceText.innerHTML = `
      ✓ <strong>Certainty (${state.enteredCertainty}%) exceeds break-even p* (${(breakEvenP * 100).toFixed(1)}%).</strong><br>
      Accusing has positive statistical expected value (EV = +${ev.toFixed(2)}).
    `;
  }
}

function confirmAccusation() {
  const empId = $("accuseSuspectSelect").value;
  if (!empId) {
    alert("Please select the suspect you wish to accuse.");
    return;
  }
  state.chosenSuspect = empId;
  closeAccuseDialog();
  executeTool("accuse", { employee: empId });
}

function abstainAndClose() {
  const confirmed = confirm(
    "🛡️ CLOSE CASE WITHOUT ACCUSING (ABSTAIN)\n\n" +
    "You are choosing to abstain rather than making an uncertain accusation.\n" +
    "- Your final score will be exactly 0.00.\n" +
    "- You avoid the catastrophic -1.00 penalty for a false accusation.\n\n" +
    "End the investigation now?"
  );
  if (!confirmed) return;

  state.playerAbstained = true;
  closeAccuseDialog();

  // Advance through days until the episode horizon is reached
  while (game && !JSON.parse(game.call_json("advance_day", "{}")).done) {
    // Loop advances to horizon
  }
  showEndScreen();
}

// -----------------------------------------------------------------------------
// END SCREEN & BENCHMARK SCOREBOARD (Screen 5)
// -----------------------------------------------------------------------------
function showEndScreen() {
  for (const b of document.querySelectorAll("button")) {
    if (b.id !== "playAgainBtn" && b.id !== "replaySameSeedBtn" && b.id !== "copyResultBtn" && b.id !== "dlActionsBtn" && b.id !== "demoToggleBtn") {
      b.disabled = true;
    }
  }

  const reveal = JSON.parse(game.reveal_json());
  const moleId = reveal.mole;
  const isWin = reveal.you.correct;
  const isAbstain = reveal.you.end_reason === "horizon" || state.playerAbstained;

  // Header Title
  const icon = $("endVerdictIcon");
  const title = $("endVerdictTitle");
  const sub = $("endVerdictSub");

  if (isWin) {
    icon.textContent = "🏆";
    title.textContent = "INVESTIGATION SUCCESSFUL: MOLE CAPTURED!";
    sub.textContent = `You accurately identified ${moleId} as the corporate mole and preserved ${Math.round(reveal.you.score * 100)}% of company value.`;
  } else if (isAbstain) {
    icon.textContent = "🛡️";
    title.textContent = "INVESTIGATION CLOSED: ABSTAINED";
    sub.textContent = `You closed the investigation without an accusation, preserving 0.00 score and avoiding the catastrophic -1.00 penalty.`;
  } else {
    icon.textContent = "❌";
    title.textContent = "INVESTIGATION FAILED: FALSE ACCUSATION";
    sub.textContent = `You accused ${reveal.you.accused}, but the real mole was ${moleId}. A false accusation imposes a -1.00 penalty.`;
  }

  // Flipping Mole Card
  const moleEmp = state.employees.find(e => e.id === moleId) || { name: moleId, dept: "Unknown", role: "Mole" };
  $("moleNameDisplay").textContent = moleEmp.name;
  $("moleMetaDisplay").textContent = `${moleId} · ${moleEmp.dept} · ${moleEmp.role}`;

  const flipCard = $("moleFlipCard");
  flipCard.classList.remove("revealed");
  setTimeout(() => {
    flipCard.classList.add("revealed");
  }, 400);

  // Scoreboard Table (Honest Labeling)
  const scoreboard = $("scoreboardBody");
  scoreboard.innerHTML = "";

  const refEntries = referenceData[String(reveal.seed)] || [];
  const rows = [
    {
      who: "You (Human Operator)",
      score: reveal.you.score,
      telemetry: `${reveal.you.end_reason === "accused" ? "accused " + reveal.you.accused + (reveal.you.correct ? " (CORRECT)" : " (WRONG)") : "abstained / horizon"}, day ${reveal.you.final_day}, ${reveal.you.tool_calls} calls`,
      isPlayer: true
    },
    {
      who: "Reference Solver (Bayes Policy)",
      score: reveal.solver.score,
      telemetry: `${reveal.solver.correct ? "correct" : "abstained"}, accused day ${reveal.solver.final_day}, ${reveal.solver.tool_calls} calls (live on this seed)`,
      isPlayer: false
    }
  ];

  if (refEntries.length > 0) {
    for (const r of refEntries) {
      rows.push({
        who: r.agent,
        score: r.score,
        telemetry: r.note || "benchmark average",
        isPlayer: false
      });
    }
  } else {
    rows.push({
      who: "gemini-4-carbon (benchmark avg)",
      score: 0.503,
      telemetry: "Harbor v1.4 judge benchmark mean (oracle: 0.757, gap: -0.253)",
      isPlayer: false
    });
    rows.push({
      who: "codex:gpt-5.5 (benchmark avg)",
      score: 0.401,
      telemetry: "v1.3 judges-harness shape (55% of solver, n=11)",
      isPlayer: false
    });
    rows.push({
      who: "heuristic baseline",
      score: 0.650,
      telemetry: "Canary bisection reference",
      isPlayer: false
    });
    rows.push({
      who: "logs_only baseline",
      score: -1.000,
      telemetry: "Audit logs only, no canaries (fooled by framing: -1.00)",
      isPlayer: false
    });
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    if (row.isPlayer) tr.className = "player-row";

    const scoreColor = row.score > 0 ? "var(--ok)" : row.score < 0 ? "var(--err)" : "inherit";
    tr.innerHTML = `
      <td>${row.who}</td>
      <td class="mono" style="color:${scoreColor}; font-weight:700;">${fmt(row.score)}</td>
      <td class="muted font-small">${row.telemetry}</td>
    `;
    scoreboard.appendChild(tr);
  }

  // "You Were Fooled" Callout
  const fooledBox = $("fooledCallout");
  const moleTag = state.userTags[moleId];
  if (moleTag === "cleared") {
    fooledBox.hidden = false;
    $("fooledHeading").textContent = "You Were Fooled: Cleared the Real Traitor";
    $("fooledMessage").textContent = `During the investigation, you tagged ${moleEmp.name} (${moleId}) as 'Cleared'. The mole successfully maintained a low profile and deflected your suspicion!`;
  } else if (!isWin && reveal.you.accused) {
    fooledBox.hidden = false;
    const accusedEmp = state.employees.find(e => e.id === reveal.you.accused);
    $("fooledHeading").textContent = "You Were Fooled: Innocent Suspect Framed";
    $("fooledMessage").textContent = `You accused ${accusedEmp ? accusedEmp.name : reveal.you.accused}. The true mole planted fabricated after-hours access logs and exploited the delayed leaks to frame colleagues!`;
  } else {
    fooledBox.hidden = true;
  }

  // "Your Call" Regret Analysis
  const regretBox = $("regretAnalysisText");
  const V = reveal.you.score > 0 ? reveal.you.score : state.knownV;
  const breakEvenP = 1 / (1 + V);

  regretBox.innerHTML = `
    <p>You estimated your certainty at <strong>${state.enteredCertainty}%</strong>. The mathematical break-even threshold for accusing on Day ${reveal.you.final_day} was <strong>p* = ${(breakEvenP * 100).toFixed(1)}%</strong>.</p>
    <p>${
      isWin
        ? `Because your certainty (${state.enteredCertainty}%) exceeded break-even, accusing was the optimal decision (+${reveal.you.score.toFixed(3)}). You beat naive heuristics and safely preserved company assets.`
        : isAbstain
        ? `By choosing to abstain, you scored 0.00. Frontier LLMs routinely lose 1.00 at the deadline by taking low-confidence gambles. Abstaining when p < p* is the mathematically dominant play.`
        : `At ${state.enteredCertainty}% certainty, taking the gamble resulted in a wrong accusation (-1.00). When uncertain, closing the case without an accusation (0.00) prevents devastating false-termination damages.`
    }</p>
  `;

  // Action Replay Timeline
  $("solverAccuseDayChip").textContent = `Reference Solver accused Day ${reveal.solver.final_day}`;
  const replayBox = $("replayTimeline");
  replayBox.innerHTML = "";

  for (const act of state.actionHistory) {
    const entry = document.createElement("div");
    entry.className = "replay-entry";
    entry.innerHTML = `
      <span class="mono muted font-small">Day ${act.day}</span>
      <strong>${act.tool}</strong>
      <span class="muted font-small">${act.tool === 'plant_canary' ? act.args.doc_title || 'Memo' : JSON.stringify(act.args)}</span>
    `;
    replayBox.appendChild(entry);
  }

  // Reveal End Screen
  $("investigationScreen").hidden = true;
  $("endScreen").hidden = false;
  $("endScreen").scrollIntoView({ behavior: "smooth" });
}

// -----------------------------------------------------------------------------
// EXPERT PROTOCOL CONSOLE (Raw 13 Tools)
// -----------------------------------------------------------------------------
function renderExpertTools(tools) {
  const container = $("toolsList");
  container.innerHTML = "";

  for (const t of tools) {
    const card = document.createElement("form");
    card.className = "tool-form-card";
    card.dataset.tool = t.name;

    let cat = "intel";
    if (t.name === "accuse") cat = "accuse";
    else if (t.name === "status" || t.name === "advance_day") cat = "ops";
    else if (t.name === "plant_canary" || t.name === "check_leak_feed" || t.name === "restrict_access" || t.name === "unrestrict_access") cat = "traps";
    card.dataset.category = cat;

    const props = t.input_schema.properties || {};
    let fieldsHtml = "";
    for (const [pName, pSchema] of Object.entries(props)) {
      fieldsHtml += `
        <label>${pName}:</label>
        <input name="${pName}" type="${pSchema.type === 'integer' ? 'number' : 'text'}" placeholder="${pSchema.description || ''}" data-type="${pSchema.type}">
      `;
    }

    card.innerHTML = `
      <h4>${t.name}</h4>
      <p class="desc">${t.description}</p>
      ${fieldsHtml}
      <button type="submit" class="btn-secondary btn-small" style="margin-top:6px; width:100%;">Call ${t.name}</button>
    `;

    card.addEventListener("submit", (e) => {
      e.preventDefault();
      const args = {};
      card.querySelectorAll("input").forEach(input => {
        const val = input.value.trim();
        if (val) {
          args[input.name] = input.dataset.type === "integer" ? parseInt(val, 10) : val;
        }
      });
      executeTool(t.name, args);
    });

    container.appendChild(card);
  }
}

// -----------------------------------------------------------------------------
// GUIDED TUTORIAL COACH MARKS
// -----------------------------------------------------------------------------
const TUTORIAL_STEPS = [
  {
    target: "titleScreen",
    title: "Canary Benchmark Field Guide",
    message: "Welcome to Canary! You are Head of Corporate Security. A rival firm is publishing your memos. Your mission is to find the mole while preserving Company Value (V = 1.00).",
  },
  {
    target: "hudBar",
    title: "The Security HUD",
    message: "Track your Calendar, Daily Action Pips (8 per day), Company Value (V), and Leaks Detected. Leaks diminish company value. Every action spends budget, so plan carefully!",
  },
  {
    target: "officeCard",
    title: "The Office Suspect Pool",
    message: "Personnel are grouped by department. Click any card to inspect their dossier, interview them, review their access logs, or tag them as Suspect (🔴) or Cleared (🟢).",
  },
  {
    target: "hudPlantCanaryBtn",
    title: "Plant Canary Traps",
    message: "Use Plant Canaries [P] to distribute marked variants (A, B, C) to cohorts. When a leak appears on the rival wire, the leaked variant reveals the mole's cohort!",
  },
  {
    target: "hudNextDayBtn",
    title: "Advance Day & Watch the Delay",
    message: "Advance Day [N] ends today and advances time. Crucial rule: leaks take 1–3 days to surface! Today's leak was stolen days ago. Beware of fabricated after-hours logs.",
  },
  {
    target: "hudAccuseBtn",
    title: "Accuse or Abstain: The Math",
    message: "When you're ready, accuse [A]. But heed the break-even math: if your certainty is below p* = 1 / (1 + V), closing the case without accusing (abstaining) scores 0.00 while guessing risks -1.00!",
  }
];

function startTutorial() {
  tutorialStep = 0;
  if ($("investigationScreen").hidden) {
    startGame(3000); // Fixed seed for tutorial
  }
  showTutorialStep(0);
}

function showTutorialStep(idx) {
  tutorialStep = idx;
  const overlay = $("tutorialOverlay");
  const step = TUTORIAL_STEPS[idx];

  document.querySelectorAll(".tut-highlight").forEach(el => el.classList.remove("tut-highlight"));

  $("tutStepBadge").textContent = `Step ${idx + 1} of ${TUTORIAL_STEPS.length}`;
  $("tutTitle").textContent = step.title;
  $("tutMessage").textContent = step.message;
  $("tutPrevBtn").disabled = idx === 0;
  $("tutNextBtn").textContent = idx === TUTORIAL_STEPS.length - 1 ? "Finish" : "Next";

  const targetEl = $(step.target);
  if (targetEl) {
    targetEl.classList.add("tut-highlight");
    targetEl.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  overlay.hidden = false;
}

function closeTutorial() {
  $("tutorialOverlay").hidden = true;
  document.querySelectorAll(".tut-highlight").forEach(el => el.classList.remove("tut-highlight"));
  try {
    localStorage.setItem("canary_tut_seen", "1");
  } catch (_) {}
}

// -----------------------------------------------------------------------------
// GLOBAL EVENT LISTENERS & SHORTCUTS
// -----------------------------------------------------------------------------
function setupGlobalEventListeners() {
  // Title Launch buttons
  $("playBtn").addEventListener("click", () => startGame());
  $("startTutorialBtn").addEventListener("click", () => startTutorial());

  $("randomSeedBtn").addEventListener("click", () => {
    const s = randomSeed();
    $("seedInput").value = s;
    state.seed = s;
    $("headerSeedDisplay").textContent = s;
  });

  // HUD Ops buttons
  $("hudPlantCanaryBtn").addEventListener("click", openCanaryWizard);
  $("hudPlantBtn") && $("hudPlantBtn").addEventListener("click", openCanaryWizard);
  $("hudAccuseBtn").addEventListener("click", () => openAccuseDialog());

  $("hudNextDayBtn").addEventListener("click", () => {
    if (state.actionsLeftToday > 0) {
      const ok = confirm(`You still have ${state.actionsLeftToday} action(s) left today. Are you sure you want to end Day ${state.day} and advance to tomorrow?`);
      if (!ok) return;
    }
    executeTool("advance_day", {});
  });

  $("expertToggleBtn").addEventListener("click", () => {
    const consoleEl = $("expertConsole");
    consoleEl.open = !consoleEl.open;
    if (consoleEl.open) consoleEl.scrollIntoView({ behavior: "smooth" });
  });

  // Office & Dossier buttons
  $("surveyOfficeBtn").addEventListener("click", () => executeTool("list_employees", {}));
  $("surveyOfficeActionBtn").addEventListener("click", () => executeTool("list_employees", {}));
  $("checkLeaksFeedBtn").addEventListener("click", () => executeTool("check_leak_feed", {}));

  $("closeDossierBtn").addEventListener("click", () => {
    $("empDossierCard").hidden = true;
    document.querySelectorAll(".emp-card").forEach(c => c.classList.remove("selected"));
    state.selectedEmpId = null;
  });

  // Dossier tag buttons
  document.querySelectorAll(".btn-tag").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!state.selectedEmpId) return;
      const tag = btn.dataset.tag;
      state.userTags[state.selectedEmpId] = tag;
      document.querySelectorAll(".btn-tag").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      updateEmployeeCardUI(state.selectedEmpId);
    });
  });

  // Dossier direct actions
  $("dosInterviewBtn").addEventListener("click", () => {
    if (!state.selectedEmpId) return;
    const topic = $("interviewTopicSelect").value;
    executeTool("interview", { employee: state.selectedEmpId, topic });
  });

  $("dosLogsBtn").addEventListener("click", () => {
    if (!state.selectedEmpId) return;
    executeTool("read_access_logs", { day_from: 1, day_to: state.day, employee: state.selectedEmpId });
  });

  $("dosMessagesBtn").addEventListener("click", () => {
    if (!state.selectedEmpId) return;
    executeTool("search_messages", { query: state.selectedEmpId, day_from: 1, day_to: state.day });
  });

  $("dosRestrictBtn").addEventListener("click", () => {
    if (!state.selectedEmpId) return;
    if (state.restricted.has(state.selectedEmpId)) {
      executeTool("unrestrict_access", { employee: state.selectedEmpId });
    } else {
      executeTool("restrict_access", { employee: state.selectedEmpId });
    }
  });

  $("dosAccuseSuspectBtn").addEventListener("click", () => {
    openAccuseDialog(state.selectedEmpId);
  });

  // Feed Filter Pills
  document.querySelectorAll(".filter-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".filter-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      state.feedFilter = pill.dataset.filter;
      filterFeed();
    });
  });

  // Accuse Dialog Events
  $("closeAccuseModalBtn").addEventListener("click", closeAccuseDialog);
  $("accuseSuspectSelect").addEventListener("change", updateAccuseTargetName);
  $("certaintySlider").addEventListener("input", recalculateAccuseMath);
  $("confirmAccuseBtn").addEventListener("click", confirmAccusation);
  $("abstainBtn").addEventListener("click", abstainAndClose);

  // Canary Wizard Events
  $("closeCanaryModalBtn").addEventListener("click", closeCanaryWizard);
  $("wizardSplitEvenBtn").addEventListener("click", () => wizardSplit(3));
  $("wizardSplitTwoBtn").addEventListener("click", () => wizardSplit(2));
  $("wizardSplitDeptBtn").addEventListener("click", wizardSplitByDept);
  $("wizardClearBtn").addEventListener("click", () => {
    document.querySelectorAll(".wizard-emp-chip").forEach(c => {
      c.classList.remove("assign-a", "assign-b", "assign-c");
      c.querySelector(".chip-var").textContent = "–";
      state.canaryAssignments[c.dataset.id] = "";
    });
    updateWholeCompanyWarning();
  });
  $("submitCanaryTrapBtn").addEventListener("click", submitCanaryWizard);

  // End Screen Navigation
  $("playAgainBtn").addEventListener("click", () => {
    location.search = "?seed=" + randomSeed();
  });
  $("replaySameSeedBtn").addEventListener("click", () => {
    location.search = "?seed=" + state.seed;
  });
  $("copyResultBtn").addEventListener("click", () => {
    const reveal = JSON.parse(game.reveal_json());
    const scoreStr = fmt(reveal.you.score);
    const solverStr = fmt(reveal.solver.score);
    const url = `${location.origin}${location.pathname}?seed=${state.seed}`;
    const text = `I scored ${scoreStr} on Canary seed ${state.seed}, the solver scored ${solverStr}, can you beat it? ${url}`;

    navigator.clipboard.writeText(text).then(() => {
      const orig = $("copyResultBtn").textContent;
      $("copyResultBtn").textContent = "✓ Copied to Clipboard!";
      setTimeout(() => { $("copyResultBtn").textContent = orig; }, 2000);
    });
  });

  $("dlActionsBtn").addEventListener("click", () => {
    const blob = new Blob([game.actions_json()], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `canary-seed-${state.seed}-actions.json`;
    a.click();
  });

  // Tutorial controls
  $("tutPrevBtn").addEventListener("click", () => {
    if (tutorialStep > 0) showTutorialStep(tutorialStep - 1);
  });
  $("tutNextBtn").addEventListener("click", () => {
    if (tutorialStep < TUTORIAL_STEPS.length - 1) {
      showTutorialStep(tutorialStep + 1);
    } else {
      closeTutorial();
    }
  });
  $("skipTutorialBtn").addEventListener("click", closeTutorial);

  // Shortcuts & Demo View
  $("helpShortcutBtn").addEventListener("click", () => {
    $("shortcutsModal").hidden = false;
  });
  $("closeShortcutsBtn").addEventListener("click", () => {
    $("shortcutsModal").hidden = true;
  });
  $("demoToggleBtn").addEventListener("click", () => {
    const isDemo = document.body.classList.toggle("demo-mode");
    $("demoToggleBtn").textContent = isDemo ? "📺 Standard View" : "📺 Demo View";
  });

  // Keyboard Shortcuts (N, P, A, ?, Escape)
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") {
      return;
    }
    const key = e.key.toUpperCase();
    if (key === "N") {
      e.preventDefault();
      $("hudNextDayBtn").click();
    } else if (key === "P") {
      e.preventDefault();
      openCanaryWizard();
    } else if (key === "A") {
      e.preventDefault();
      openAccuseDialog();
    } else if (key === "?") {
      e.preventDefault();
      $("shortcutsModal").hidden = !$("shortcutsModal").hidden;
    } else if (e.key === "Escape") {
      $("shortcutsModal").hidden = true;
      $("canaryModal").hidden = true;
      $("accuseModal").hidden = true;
      $("empDossierCard").hidden = true;
      closeTutorial();
    }
  });
}

// Start boot sequence
boot();
