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
  checkedLeaksToday: false,
  seenLeakDocIds: new Set(),
  docTitles: {},
  employees: [], // populated ONLY after player triggers list_employees
  userTags: {}, // client-side notes: { [empId]: "suspect" | "cleared" | "unsure" }
  canaryAssignments: {}, // { [empId]: "A" | "B" | "C" }
  canaryHistory: [], // records of planted canaries
  restricted: new Set(),
  selectedEmpId: null,
  enteredCertainty: 50,
  chosenSuspect: null,
  playerAbstained: false,
  decisionDay: null,
  decisionV: null,
  decisionBreakEvenP: null,
  actionHistory: [], // [[tool, args, day], ...]
  feedFilter: "all"
};

const DEPT_COLORS = {
  Engineering: "var(--muted)",
  Finance: "var(--muted)",
  Sales: "var(--muted)",
  Legal: "var(--muted)",
  Research: "var(--muted)"
};

// DISPLAY-ONLY mapping from engine employee IDs (e00, e01, ...) to famous tech pioneers
const FAMOUS_TECH_PEOPLE = {
  e00: "Ada Lovelace",
  e01: "Alan Turing",
  e02: "Grace Hopper",
  e03: "Steve Jobs",
  e04: "Steve Wozniak",
  e05: "Bill Gates",
  e06: "Linus Torvalds",
  e07: "Tim Berners-Lee",
  e08: "Margaret Hamilton",
  e09: "Dennis Ritchie",
  e10: "Ken Thompson",
  e11: "Satya Nadella",
  e12: "Lisa Su",
  e13: "Jensen Huang",
  e14: "Sam Altman",
  e15: "Demis Hassabis",
  e16: "Fei-Fei Li",
  e17: "Elon Musk",
  e18: "Larry Page",
  e19: "Sergey Brin",
  e20: "Mark Zuckerberg",
  e21: "Sheryl Sandberg",
  e22: "Susan Wojcicki",
  e23: "Guido van Rossum",
  e24: "John Carmack",
  e25: "Hedy Lamarr",
  e26: "Claude Shannon",
  e27: "Katherine Johnson",
  e28: "Jeff Bezos",
  e29: "Marissa Mayer",
  e30: "Barbara Liskov",
  e31: "Donald Knuth",
  e32: "Radia Perlman",
  e33: "Bjarne Stroustrup",
  e34: "Leslie Lamport",
  e35: "Geoffrey Hinton",
  e36: "Yann LeCun",
  e37: "Yoshua Bengio",
  e38: "Andrew Ng",
  e39: "Ilya Sutskever",
  e40: "Andrej Karpathy",
  e41: "John von Neumann",
  e42: "Gordon Moore",
  e43: "Andy Grove",
  e44: "Robert Noyce",
  e45: "Marc Andreessen",
  e46: "Peter Thiel",
  e47: "Vint Cerf",
  e48: "Bob Kahn",
  e49: "Douglas Engelbart"
};

const engineNameToFamous = {};

function registerEngineEmployees(emps) {
  for (const emp of emps) {
    if (emp.id && FAMOUS_TECH_PEOPLE[emp.id] && emp.name) {
      engineNameToFamous[emp.name] = FAMOUS_TECH_PEOPLE[emp.id];
    }
  }
}

function getEmployeeName(id) {
  return FAMOUS_TECH_PEOPLE[id] || id;
}

function getEmployeeDisplayName(id) {
  const name = FAMOUS_TECH_PEOPLE[id];
  return name ? `${name} (${id})` : id;
}

function mapTextNames(text) {
  if (!text || typeof text !== "string") return text;
  let out = text;
  for (const [engName, famName] of Object.entries(engineNameToFamous)) {
    if (engName && famName && engName !== famName) {
      out = out.split(engName).join(famName);
    }
  }
  out = out.replace(/\b(e\d{2})\b/g, (match) => {
    return FAMOUS_TECH_PEOPLE[match] ? `${FAMOUS_TECH_PEOPLE[match]} (${match})` : match;
  });
  return out;
}

function formatActionPlainWords(tool, args = {}) {
  const empName = args.employee ? getEmployeeDisplayName(args.employee) : "";
  switch (tool) {
    case "check_leak_feed":
      return "Checked the leak feed";
    case "read_access_logs":
      if (args.day_from !== undefined && args.day_to !== undefined) {
        return `Read access logs, days ${args.day_from}–${args.day_to}${empName ? ' for ' + empName : ''}`;
      }
      return `Read access logs${empName ? ' for ' + empName : ''}`;
    case "interview": {
      const topicLabels = {
        workload: "workload",
        recent_documents: "recent documents",
        contacts_outside: "outside contacts",
        access_needs: "access needs"
      };
      const topicStr = topicLabels[args.topic] || args.topic || "general";
      return `Interviewed ${empName || 'staff'} (${topicStr})`;
    }
    case "plant_canary":
      return `Planted canary: "${args.doc_title || 'Memo'}"`;
    case "list_employees":
      return "Surveyed office personnel";
    case "search_messages":
      return `Searched staff messages for "${args.query || ''}"`;
    case "restrict_access":
      return `Restricted access for ${empName || 'employee'}`;
    case "unrestrict_access":
      return `Restored access for ${empName || 'employee'}`;
    case "advance_day":
      return "Advanced to next day";
    case "accuse":
      return `Accused ${empName || 'suspect'}`;
    default:
      return tool.replace(/_/g, " ");
  }
}

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
    if (demoBtn) demoBtn.textContent = "Standard View";
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

    updateLoader(100, "Benchmark runtime ready. Start investigation.");
    $("playBtn").disabled = false;
    $("playBtn").textContent = "Start Investigation";
    $("startTutorialBtn").disabled = false;
  } catch (err) {
    $("loadMsg").textContent = "Failed to load engine: " + err.message;
    $("playBtn").textContent = "Engine Initialization Failed";
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

  // Reset episode state
  callsSpent = 0;
  state.day = 1;
  state.maxDays = 14;
  state.knownV = 1.000;
  state.actionsLeftToday = 8;
  state.dailyCallsMax = 8;
  state.totalCallsLeft = 300;
  state.leaksCount = 0;
  state.checkedLeaksToday = false;
  state.seenLeakDocIds.clear();
  state.docTitles = {};
  state.employees = [];
  state.userTags = {};
  state.canaryAssignments = {};
  state.canaryHistory = [];
  state.restricted.clear();
  state.selectedEmpId = null;
  state.actionHistory = [];
  state.playerAbstained = false;
  state.decisionDay = null;
  state.decisionV = null;
  state.decisionBreakEvenP = null;

  refreshHUD();

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
        <p class="muted font-small">First action: Survey personnel with <strong>Survey Office (1 action)</strong> or deploy marked traps via <strong>Plant Canaries [P]</strong>.</p>
      </div>
    </div>
  `;

  // Auto-offer tutorial on first visit
  try {
    if (!localStorage.getItem("canary_tutorial_offered")) {
      localStorage.setItem("canary_tutorial_offered", "1");
      setTimeout(() => startTutorial(), 400);
    }
  } catch (_) {}
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
    state.checkedLeaksToday = false;
  }

  if (tool === "check_leak_feed") {
    const items = data.items || [];
    state.leaksCount = items.length;
    state.checkedLeaksToday = true;
    for (const item of items) {
      if (item.doc_id && item.title) {
        state.docTitles[item.doc_id] = item.title;
      }
    }
  }

  if (tool === "list_employees") {
    const emps = data.employees || (Array.isArray(data) ? data : []);
    if (Array.isArray(emps) && emps.length > 0) {
      registerEngineEmployees(emps);
      state.employees = emps.map(e => ({
        ...e,
        name: FAMOUS_TECH_PEOPLE[e.id] || e.name || e.id
      }));
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
    if (args.doc_title) {
      state.docTitles[cid] = args.doc_title;
    }
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

  // Leak check button indicator
  const leakBtn = $("checkLeaksFeedBtn");
  if (leakBtn) {
    if (state.checkedLeaksToday) {
      leakBtn.textContent = "Checked Today";
      leakBtn.title = "Already checked today. Leaks only surface when advancing days.";
    } else {
      leakBtn.textContent = "Check Leaks (1 action)";
      leakBtn.title = "Check rival wire for newly surfaced leaks (costs 1 action)";
    }
  }

  updateGuidance();
}

function updateGuidance() {
  const el = $("hudGuidanceText");
  if (!el) return;

  if (state.employees.length === 0) {
    el.textContent = "Survey office personnel to index staff across departments (1 action).";
    return;
  }

  if (state.actionsLeftToday === 0) {
    el.textContent = "All 8 actions spent today. Press Next Day [N] to advance time and let leaks surface.";
    return;
  }

  const plantedToday = state.canaryHistory.some(c => c.day === state.day);
  const totalCanaries = state.canaryHistory.length;

  if (plantedToday) {
    el.textContent = "Canaries planted. Leaks take 1–3 days, so press Next Day [N] and check the leak feed.";
    return;
  }

  if (state.day > 1 && !state.checkedLeaksToday) {
    el.textContent = `Day ${state.day} began. Press Check Leaks to see if any planted canaries surfaced at rival firm.`;
    return;
  }

  if (totalCanaries === 0) {
    el.textContent = "No canaries active yet. Press Plant Canaries [P] to distribute marked memos across cohorts.";
    return;
  }

  if (state.leaksCount > 0) {
    el.textContent = "Leaks detected! Match the leaked variant to assigned cohorts, interview suspects, or Accuse [A].";
    return;
  }

  el.textContent = "Canaries are out in the field. Review access logs, interview suspects, or advance to tomorrow [N].";
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
    const section = document.createElement("div");
    section.className = "team-section";
    section.innerHTML = `
      <div class="team-header">
        <span class="team-name-badge">${dept}</span>
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
    tagBadgeHtml = `<span class="tag-badge tag-suspect-bg">Suspect</span>`;
  } else if (tag === "cleared") {
    tagBadgeHtml = `<span class="tag-badge tag-cleared-bg">Cleared</span>`;
  } else {
    tagBadgeHtml = `<span class="tag-badge tag-unsure-bg">Unsure</span>`;
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

  let lockHtml = isLocked ? `<span class="locked-badge">Restricted</span>` : "";

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

  // Scroll into view below sticky HUD header
  const hud = $("hudBar");
  const headerOffset = hud ? hud.offsetHeight + 20 : 100;
  const rect = drawer.getBoundingClientRect();
  const targetTop = window.pageYOffset + rect.top - headerOffset;
  window.scrollTo({ top: Math.max(0, targetTop), behavior: "smooth" });
}

function updateDossierView(empId) {
  const emp = state.employees.find(e => e.id === empId);
  if (!emp) return;

  $("dosId").textContent = emp.id;
  $("dosName").textContent = emp.name;
  $("dosRole").textContent = emp.role || "Member";
  $("dosDeptBadge").textContent = emp.dept || "Staff";
  if ($("msgQueryInput")) $("msgQueryInput").value = emp.id;

  const isLocked = state.restricted.has(emp.id);
  $("dosRestrictedBadge").hidden = !isLocked;
  $("dosRestrictBtn").textContent = isLocked ? "Restore Access" : "Restrict Access";

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
    const newItems = items.filter(it => !state.seenLeakDocIds.has(it.doc_id));

    if (!items.length) {
      bodyContent = `<p class="muted">No leaks detected on the rival firm wire as of Day ${state.day}.</p>`;
    } else if (!newItems.length) {
      bodyContent = `<p class="muted">No new leaks since last check (${items.length} total leaks previously detected on wire).</p>`;
    } else {
      let html = `<div style="font-weight:700; color:var(--err); margin-bottom:6px;">New Leaks Detected (${newItems.length} new, ${items.length} total):</div>`;
      for (const item of newItems) {
        state.seenLeakDocIds.add(item.doc_id);
        const isCanary = !!item.variant || (item.doc_id && item.doc_id.startsWith("c"));
        const v = item.variant;
        const vClass = v ? v.toLowerCase() : "";
        const minDay = Math.max(1, item.surfaced_day - 3);
        const maxDay = Math.max(1, item.surfaced_day - 1);

        let badgeHtml = "";
        let detailsHtml = "";

        if (isCanary && v) {
          badgeHtml = `<span class="canary-pill canary-pill-${vClass}">Canary Variant ${v}</span>`;
          // Find who was assigned Variant v for this canary doc
          const hist = state.canaryHistory.find(h => h.id === item.doc_id);
          const holderNames = [];
          if (hist && hist.assignment) {
            for (const [eId, varName] of Object.entries(hist.assignment)) {
              if (varName === v) {
                holderNames.push(getEmployeeDisplayName(eId));
              }
            }
          }
          detailsHtml = holderNames.length ? `<div class="muted font-small" style="margin-top:2px;">Staff given Var ${v}: ${holderNames.join(", ")}</div>` : '';
        } else if (isCanary) {
          badgeHtml = `<span class="canary-pill canary-pill-a">Canary Leak</span>`;
          detailsHtml = `<div class="muted font-small" style="margin-top:2px;">Planted canary leaked.</div>`;
        } else {
          badgeHtml = `<span class="regular-doc-pill">Regular Document</span>`;
          detailsHtml = `<div class="muted font-small" style="margin-top:2px;">Standard memo. Cross-reference access logs.</div>`;
        }

        html += `
          <div style="background:var(--panel-elevated); border:1px solid var(--line); border-radius:4px; padding:8px; margin-bottom:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; gap:8px; flex-wrap:wrap;">
              <div>
                <span class="chip" style="color:var(--ok); border-color:var(--ok); font-weight:700; margin-right:4px;">NEW</span>
                <strong>Doc: ${item.doc_id} · "${item.title || 'Memo'}"</strong>
              </div>
              ${badgeHtml}
            </div>
            ${detailsHtml}
            <div class="muted font-small" style="margin-top:2px;">Surfaced Day ${item.surfaced_day} (exfiltrated Days ${minDay}–${maxDay}).</div>
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
        <strong>Subject:</strong> ${getEmployeeDisplayName(args.employee)} &nbsp;|&nbsp; <strong>Topic:</strong> ${topicLabels[args.topic] || args.topic}
        <div class="interview-quote">
          "${mapTextNames(res.data.answer || res.data.statement || 'No statement provided.')}"
        </div>
        <div class="muted font-small">
          Evasive answers indicate higher mole probability.
        </div>
      </div>
    `;
  } else if (tool === "read_access_logs") {
    let logs = res.data.logs || [];
    if (typeof logs === "string") {
      logs = logs.trim().split("\n").filter(Boolean).map(line => {
        const p = line.split("\t");
        return { day: parseInt(p[0], 10), employee: p[1], doc_id: p[2], after_hours: p[3] === "true" || p[3] === "1" };
      });
    }

    if (!logs.length) {
      bodyContent = `<p class="muted">No access log entries recorded for this filter window.</p>`;
    } else {
      let html = `
        <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
          <span><strong>Access Logs:</strong> ${logs.length} entries (Day ${args.day_from} to ${args.day_to})</span>
        </div>
        <table class="log-table">
          <thead>
            <tr><th>Day</th><th>Staff</th><th>Document</th><th>Time</th></tr>
          </thead>
          <tbody>
      `;
      for (const log of logs.slice(-12)) {
        const title = state.docTitles[log.doc_id];
        const isLeaked = state.seenLeakDocIds.has(log.doc_id);
        const docLabel = title ? `${log.doc_id} ("${title}")` : log.doc_id;
        const leakedBadge = isLeaked ? ` <span class="chip" style="color:var(--err); border-color:var(--err); font-size:9px; padding:0 3px;">LEAKED</span>` : "";

        html += `
          <tr>
            <td>Day ${log.day}</td>
            <td><strong style="color:var(--accent);">${getEmployeeDisplayName(log.employee)}</strong></td>
            <td><span class="mono">${docLabel}</span>${leakedBadge}</td>
            <td>${log.after-hours ? '<span class="after-hours-tag">AFTER-HOURS</span>' : '<span class="muted">normal</span>'}</td>
          </tr>
        `;
      }
      html += `</tbody></table>`;
      if (logs.length > 12) html += `<div class="muted font-small" style="margin-top:4px;">Showing last 12 of ${logs.length} entries.</div>`;
      html += `
        <div class="muted font-small" style="margin-top:6px; color:var(--warn);">
          Note: Mole frames colleagues by fabricating after-hours logs.
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
              <strong>${getEmployeeDisplayName(m.sender)} ➔ ${m.channel || 'DM'}</strong>
              <span class="muted">Day ${m.day}</span>
            </div>
            <div style="font-weight:600; font-size:12px; color:var(--ink-bright);">${mapTextNames(m.subject || '')}</div>
            <div class="muted font-small">${mapTextNames(m.snippet || '')}</div>
          </div>
        `;
      }
      if (msgs.length > 4) html += `<div class="muted font-small">Showing first 4 of ${msgs.length} messages.</div>`;
      html += `<div class="muted font-small" style="margin-top:4px;">Note: An angry employee vents in chat, but is innocent.</div>`;
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
      <p>Access restricted for employee <strong>${getEmployeeDisplayName(args.employee)}</strong>.</p>
    `;
  } else if (tool === "unrestrict_access") {
    bodyContent = `
      <p>Access permissions restored for <strong>${getEmployeeDisplayName(args.employee)}</strong>.</p>
    `;
  } else {
    bodyContent = `<p class="muted">${tool} completed successfully.</p>`;
  }

  const toolBadge = formatActionPlainWords(tool, args);
  card.innerHTML = `
    <div class="feed-head">
      <span class="feed-badge">${toolBadge}</span>
      <span class="mono muted font-small">Day ${state.day} · #${callsSpent}</span>
    </div>
    <div class="feed-body">${bodyContent}</div>
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

  $("canaryDocTitle").value = `Board memo draft ${state.day}`;
  const hasAssignments = Object.values(state.canaryAssignments).some(v => !!v);
  if (!hasAssignments) {
    wizardSplitSolver();
  } else {
    renderWizardEmployees();
    updateWholeCompanyWarning();
  }
  $("canaryModal").hidden = false;
}

function closeCanaryWizard() {
  $("canaryModal").hidden = true;
}

function wizardSplitSolver() {
  // Solver style: balance cohorts across variants (A, B, C) while leaving a control group unassigned.
  // In Medium tier, careful moles will never leak a document sent to the whole company!
  const suspects = state.employees.filter(e => state.employeeTags[e.id] === "suspect" && !state.restricted.has(e.id));
  const pool = suspects.length >= 2 ? suspects : state.employees.filter(e => !state.restricted.has(e.id));

  for (const emp of state.employees) {
    state.canaryAssignments[emp.id] = "";
  }

  const variants = ["A", "B", "C"];
  if (suspects.length >= 2) {
    suspects.forEach((emp, idx) => {
      state.canaryAssignments[emp.id] = variants[idx % variants.length];
    });
  } else {
    // 8-9 staff across A/B/C (~40-45% of workforce), leaving control group
    const targetCount = Math.min(pool.length, Math.max(3, Math.min(9, Math.floor(pool.length * 0.45))));
    const selected = pool.slice(0, targetCount);
    selected.forEach((emp, idx) => {
      state.canaryAssignments[emp.id] = variants[idx % variants.length];
    });
  }

  renderWizardEmployees();
  updateWholeCompanyWarning();
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
      const cur = state.canaryAssignments[emp.id] || "";
      const nextIdx = (variants.indexOf(cur) + 1) % variants.length;
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
  if (assigned.length === state.employees.length && state.employees.length > 0 && unique.size === 1) {
    warn.style.display = "block";
    warn.innerHTML = "<strong>Warning:</strong> All employees are receiving this canary. Careful moles will not leak a full-company document. Leave some staff unassigned as a control group.";
  } else if (assigned.length > 0 && unique.size === 1) {
    warn.style.display = "block";
    warn.innerHTML = "<strong>Warning:</strong> All assigned staff received the same variant. Use multiple variants (A, B, C) to partition cohorts.";
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
  const confirmBtn = $("confirmAccuseBtn");
  const warnText = $("confirmWarningText");

  if (p < breakEvenP) {
    adviceBox.className = "math-advice-box advice-unfavorable";
    adviceText.innerHTML = `
      <strong>At this certainty (${state.enteredCertainty}%), not accusing scores better on average</strong>
      (EV = ${ev.toFixed(2)} vs 0.00).<br>
      This is the mistake frontier AI agents make: gambling at the deadline instead of having the sense to abstain.
    `;
    if (confirmBtn) confirmBtn.className = "btn-secondary btn-large btn-warn";
    if (warnText) warnText.style.display = "block";
  } else {
    adviceBox.className = "math-advice-box advice-favorable";
    adviceText.innerHTML = `
      <strong>Certainty (${state.enteredCertainty}%) exceeds break-even p* (${(breakEvenP * 100).toFixed(1)}%).</strong><br>
      Accusing has positive statistical expected value (EV = +${ev.toFixed(2)}).
    `;
    if (confirmBtn) confirmBtn.className = "btn-danger btn-large";
    if (warnText) warnText.style.display = "none";
  }
}

function confirmAccusation() {
  const empId = $("accuseSuspectSelect").value;
  if (!empId) {
    alert("Please select the suspect you wish to accuse.");
    return;
  }
  state.decisionDay = state.day;
  state.decisionV = state.knownV;
  state.decisionBreakEvenP = 1 / (1 + state.decisionV);
  state.chosenSuspect = empId;
  closeAccuseDialog();
  executeTool("accuse", { employee: empId });
}

function showConfirmDialog({ title, message, okText = "Confirm", isDanger = false, onConfirm }) {
  const modal = $("confirmModal");
  if (!modal) {
    if (confirm(message.replace(/<[^>]+>/g, ""))) onConfirm();
    return;
  }
  $("confirmModalTitle").textContent = title;
  $("confirmModalMessage").innerHTML = message;

  const okBtn = $("confirmModalOkBtn");
  okBtn.textContent = okText;
  okBtn.className = isDanger ? "btn-danger" : "btn-primary";

  modal.hidden = false;

  const cleanup = () => {
    modal.hidden = true;
    okBtn.onclick = null;
    $("confirmModalCancelBtn").onclick = null;
    $("closeConfirmModalBtn").onclick = null;
  };

  okBtn.onclick = () => {
    cleanup();
    onConfirm();
  };

  $("confirmModalCancelBtn").onclick = cleanup;
  $("closeConfirmModalBtn").onclick = cleanup;
}

function abstainAndClose() {
  showConfirmDialog({
    title: "Close Case Without Accusing (Abstain)",
    message: "You are choosing to abstain rather than making an uncertain accusation.<br><br>• Your final score will be exactly <strong>0.00</strong>.<br>• You avoid the <strong>-1.00 penalty</strong> for a false accusation.<br><br>End the investigation now?",
    okText: "Abstain & Close Case",
    isDanger: false,
    onConfirm: () => {
      state.playerAbstained = true;
      state.decisionDay = state.day;
      state.decisionV = state.knownV;
      state.decisionBreakEvenP = 1 / (1 + state.decisionV);
      closeAccuseDialog();

      // Advance through days until the episode horizon is reached
      while (game && !JSON.parse(game.call_json("advance_day", "{}")).done) {
        // Loop advances to horizon
      }
      showEndScreen();
    }
  });
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

  const moleDisplayName = getEmployeeDisplayName(moleId);
  const moleName = getEmployeeName(moleId);

  // Header Title
  const icon = $("endVerdictIcon");
  const title = $("endVerdictTitle");
  const sub = $("endVerdictSub");

  if (isWin) {
    icon.textContent = "";
    title.textContent = "INVESTIGATION SUCCESSFUL: MOLE CAPTURED";
    sub.textContent = `You accurately identified ${moleDisplayName} as the corporate mole and preserved ${Math.round(reveal.you.score * 100)}% of company value.`;
  } else if (isAbstain) {
    icon.textContent = "";
    title.textContent = "INVESTIGATION CLOSED: ABSTAINED";
    sub.textContent = `You closed the investigation without an accusation, preserving 0.00 score and avoiding the catastrophic -1.00 penalty.`;
  } else {
    icon.textContent = "";
    title.textContent = "INVESTIGATION FAILED: FALSE ACCUSATION";
    sub.textContent = `You accused ${getEmployeeDisplayName(reveal.you.accused)}, but the real mole was ${moleDisplayName}. A false accusation imposes a -1.00 penalty.`;
  }

  // Flipping Mole Card
  const moleEmp = state.employees.find(e => e.id === moleId) || { name: moleName, dept: "Unknown", role: "Mole" };
  $("moleNameDisplay").textContent = moleName;
  $("moleMetaDisplay").textContent = `${moleId} · ${moleEmp.dept} · ${moleEmp.role}`;

  const flipCard = $("moleFlipCard");
  flipCard.classList.remove("revealed");
  setTimeout(() => {
    flipCard.classList.add("revealed");
  }, 400);

  const decisionDay = state.decisionDay || reveal.you.final_day || state.day;
  const decisionV = state.decisionV !== null ? state.decisionV : (reveal.you.score > 0 ? reveal.you.score : state.knownV);
  const breakEvenP = state.decisionBreakEvenP !== null ? state.decisionBreakEvenP : (1 / (1 + decisionV));

  // Scoreboard Table (Honest Labeling)
  const scoreboard = $("scoreboardBody");
  scoreboard.innerHTML = "";

  const refEntries = referenceData[String(reveal.seed)] || [];
  const rows = [
    {
      who: "You (Human Operator)",
      score: reveal.you.score,
      telemetry: `${reveal.you.end_reason === "accused" ? "accused " + getEmployeeDisplayName(reveal.you.accused) + (reveal.you.correct ? " (CORRECT)" : " (WRONG)") : "abstained"}, day ${decisionDay}, ${reveal.you.tool_calls} calls`,
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
    $("fooledHeading").textContent = "Investigator Note";
    $("fooledMessage").textContent = `During the investigation, you tagged ${moleDisplayName} as 'Cleared'. The mole successfully maintained a low profile and deflected your suspicion.`;
  } else if (!isWin && reveal.you.accused) {
    fooledBox.hidden = false;
    const accusedEmp = state.employees.find(e => e.id === reveal.you.accused);
    const accusedDisp = accusedEmp ? `${accusedEmp.name} (${accusedEmp.id})` : getEmployeeDisplayName(reveal.you.accused);
    $("fooledHeading").textContent = "Investigator Note";
    $("fooledMessage").textContent = `You accused ${accusedDisp}. The true mole planted fabricated after-hours access logs and exploited delayed leaks to frame colleagues.`;
  } else {
    fooledBox.hidden = true;
  }

  // "Your Call" Regret Analysis
  const regretBox = $("regretAnalysisText");

  regretBox.innerHTML = `
    <p>You estimated certainty at <strong>${state.enteredCertainty}%</strong>. At the decision on Day ${decisionDay} (V = ${decisionV.toFixed(3)}), the break-even threshold was <strong>p* = ${(breakEvenP * 100).toFixed(1)}%</strong>.</p>
    <p>${
      isWin
        ? `Certainty (${state.enteredCertainty}%) exceeded break-even p*, making the accusation on Day ${decisionDay} optimal (+${reveal.you.score.toFixed(3)}).`
        : isAbstain
        ? `Closing the case on Day ${decisionDay} preserved 0.00 score. Frontier models lose 1.00 by gambling at deadlines; abstaining when p < p* is the dominant play.`
        : `At ${state.enteredCertainty}% certainty, accusing on Day ${decisionDay} resulted in a wrong accusation (-1.00). Closing the case (0.00) prevents devastating false accusations.`
    }</p>
  `;

  // Action Replay Timeline
  $("solverAccuseDayChip").textContent = `Reference Solver accused Day ${reveal.solver.final_day}`;
  const replayBox = $("replayTimeline");
  replayBox.innerHTML = "";

  for (const act of state.actionHistory) {
    const entry = document.createElement("div");
    entry.className = "replay-entry";
    const plainWords = formatActionPlainWords(act.tool, act.args);
    entry.innerHTML = `
      <span class="mono muted font-small">Day ${act.day}</span>
      <strong>${plainWords}</strong>
    `;
    replayBox.appendChild(entry);
  }

  // Reveal End Screen
  $("investigationScreen").hidden = true;
  $("endScreen").hidden = false;
  $("endScreen").scrollIntoView({ behavior: "smooth" });
}

// -----------------------------------------------------------------------------
// GUIDED TUTORIAL COACH MARKS
// -----------------------------------------------------------------------------
const TUTORIAL_STEPS = [
  {
    target: "titleScreen",
    title: "Welcome to Canary",
    message: "Find the mole leaking memos before company value hits zero, or abstain.",
  },
  {
    target: "hudBar",
    title: "Security HUD",
    message: "Calendar, 8 daily action pips, and Company Value (V). Leaks drain V.",
  },
  {
    target: "officeCard",
    title: "The Office",
    message: "Click any card to inspect dossier, interview, review access logs, or tag.",
  },
  {
    target: "hudPlantCanaryBtn",
    title: "Plant Canaries",
    message: "Distribute marked variants (A, B, C) to cohorts to partition suspects.",
  },
  {
    target: "hudNextDayBtn",
    title: "Advance Day",
    message: "Advance time. Leaks take 1–3 days to surface at the rival firm.",
  },
  {
    target: "hudAccuseBtn",
    title: "Accuse or Abstain",
    message: "Correct catch preserves +V. If uncertain, abstain (0.00) beats guessing (-1.00).",
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

  $("randomSeedBtn")?.addEventListener("click", () => {
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
      showConfirmDialog({
        title: "End Day Early?",
        message: `You still have <strong>${state.actionsLeftToday} action(s)</strong> left today.<br><br>Unused actions do not carry over to tomorrow. Are you sure you want to end Day ${state.day} and advance?`,
        okText: "Advance to Tomorrow",
        isDanger: false,
        onConfirm: () => executeTool("advance_day", {})
      });
      return;
    }
    executeTool("advance_day", {});
  });

  $("expertToggleBtn")?.addEventListener("click", () => {
    const consoleEl = $("expertConsole");
    if (consoleEl) {
      consoleEl.open = !consoleEl.open;
      if (consoleEl.open) consoleEl.scrollIntoView({ behavior: "smooth" });
    }
  });

  // Office & Dossier buttons
  $("surveyOfficeBtn").addEventListener("click", () => executeTool("list_employees", {}));
  $("surveyOfficeActionBtn").addEventListener("click", () => executeTool("list_employees", {}));
  $("checkLeaksFeedBtn").addEventListener("click", () => {
    if (state.checkedLeaksToday) {
      showConfirmDialog({
        title: "Re-Check Leak Wire?",
        message: "You already checked the leak feed today.<br><br>In this benchmark, new leaks only surface when advancing to a new day. Spend 1 action to re-check anyway?",
        okText: "Check Anyway (1 action)",
        isDanger: false,
        onConfirm: () => executeTool("check_leak_feed", {})
      });
      return;
    }
    executeTool("check_leak_feed", {});
  });

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
    const inputVal = $("msgQueryInput") ? $("msgQueryInput").value.trim() : "";
    const q = inputVal || state.selectedEmpId || "e00";
    executeTool("search_messages", { query: q, day_from: 1, day_to: state.day });
  });

  $("msgQueryInput")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      $("dosMessagesBtn")?.click();
    }
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
  $("wizardSplitSolverBtn")?.addEventListener("click", wizardSplitSolver);
  $("wizardSplitEvenBtn")?.addEventListener("click", wizardSplitSolver);
  $("wizardSplitTwoBtn")?.addEventListener("click", () => wizardSplit(2));
  $("wizardSplitDeptBtn")?.addEventListener("click", wizardSplitByDept);
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

  $("dlActionsBtn")?.addEventListener("click", () => {
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
    $("demoToggleBtn").textContent = isDemo ? "Standard View" : "Demo View";
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
