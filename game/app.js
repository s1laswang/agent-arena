// Canary Browser Game: Full Interactive UI over game/canary_game.py in Pyodide.
// Core Mandates:
// 1. All logic goes through Game (spec_json, call_json, reveal_json). Never re-implement rules in JS.
// 2. Never call a tool the player didn't trigger, except list_documents: it is free of daily
//    actions and is used only to show who held a leaked memo. It still counts toward the
//    global tool-call cap. Never auto-call status or investigative tools.
// 3. Truth is revealed only after the episode is completed.
// 4. Honest labeling: gemini-4-carbon and codex numbers are benchmark means, not per-seed scores.
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
  leakedItems: [],
  docTitles: {},
  employees: [], // populated ONLY after player triggers list_employees
  userTags: {}, // client-side notes: { [empId]: "suspect" | "cleared" | "unsure" }
  canaryAssignments: {}, // { [empId]: "A" | "B" | "C" }
  wizardAssignments: {},
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
  feedFilter: "all",
  docsById: {},          // doc_id -> list_documents record
  suspectIds: null,      // Set of employee ids still in the leak intersection; null = everyone
  highlightSuspects: false,
  lastVariantRecipients: [],  // names from the most recent canary-variant leak
  suspectCountAtLastPlant: null
};

// Tools that consume one of the 8 daily action slots (mirrors canary.types.INVESTIGATIVE_TOOLS).
const DAILY_ACTION_TOOLS = new Set([
  "read_access_logs", "search_messages", "read_message",
  "interview", "plant_canary", "check_leak_feed",
  "restrict_access", "unrestrict_access"
]);

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
  return FAMOUS_TECH_PEOPLE[id] || id;
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
    return FAMOUS_TECH_PEOPLE[match] || match;
  });
  return out;
}

function resolveSearchQuery(query) {
  if (!query) return query;
  const raw = query.trim();
  const lower = raw.toLowerCase();

  if (/^e\d{2}$/i.test(raw)) {
    return raw.toLowerCase();
  }

  if (state.employees && state.employees.length > 0) {
    for (const emp of state.employees) {
      if (emp.name && emp.name.toLowerCase() === lower) {
        return emp.id;
      }
    }
    for (const emp of state.employees) {
      if (emp.name) {
        const parts = emp.name.toLowerCase().split(/\s+/);
        if (parts.includes(lower)) {
          return emp.id;
        }
      }
    }
  }

  for (const [id, famousName] of Object.entries(FAMOUS_TECH_PEOPLE)) {
    if (famousName.toLowerCase() === lower) {
      return id;
    }
  }
  for (const [id, famousName] of Object.entries(FAMOUS_TECH_PEOPLE)) {
    const parts = famousName.toLowerCase().split(/\s+/);
    if (parts.includes(lower)) {
      return id;
    }
  }

  for (const [engName, famName] of Object.entries(engineNameToFamous)) {
    if (engName.toLowerCase() === lower || famName.toLowerCase() === lower) {
      for (const [id, fName] of Object.entries(FAMOUS_TECH_PEOPLE)) {
        if (fName.toLowerCase() === famName.toLowerCase()) {
          return id;
        }
      }
    }
  }

  return raw;
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
      return `Searched staff messages for "${mapTextNames(args.query || '')}"`;
    case "restrict_access":
      return `Restricted access for ${empName || 'employee'}`;
    case "unrestrict_access":
      return `Restored access for ${empName || 'employee'}`;
    case "advance_day":
      return "Advanced to next day";
    case "accuse": {
      const targetName = args.employee ? getEmployeeDisplayName(args.employee) : (args.target ? getEmployeeDisplayName(args.target) : 'suspect');
      return `Accused ${targetName}`;
    }
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
  const urlParams = new URLSearchParams(window.location.search);
  const paramSeed = urlParams.get("seed");
  const isDemo = urlParams.get("demo") === "1" || urlParams.get("demo") === "true";

  if (isDemo) {
    document.body.classList.add("demo-mode");
    const demoBtn = $("demoToggleBtn");
    if (demoBtn) demoBtn.textContent = "Standard View";
  }

  if (paramSeed) {
    const parsed = parseInt(paramSeed.trim(), 10);
    state.seed = (!isNaN(parsed) && parsed >= 3000 && parsed <= 9999) ? parsed : 3000;
  } else {
    state.seed = 3000;
  }
  if ($("seedInput")) $("seedInput").value = state.seed;
  if ($("headerSeedDisplay")) $("headerSeedDisplay").textContent = state.seed;

  setupGlobalEventListeners();

  try {
    updateLoader(10, "Starting the game engine...");
    py = await loadPyodide();

    updateLoader(45, "Loading game files...");
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
      updateLoader(pct, `Loading game files (${loaded}/${manifest.files.length})...`);
    }

    updateLoader(95, "Initializing canary_game module in Python...");
    py.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import canary_game");

    try {
      const refRes = await fetch("reference.json");
      if (refRes.ok) referenceData = await refRes.json();
    } catch (_) {
      referenceData = {};
    }

    updateLoader(100, "Ready to play.");
    $("playBtn").disabled = false;
    $("playBtn").textContent = "Play";
    if ($("startTutorialBtn")) $("startTutorialBtn").disabled = false;
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
  const seedInputVal = $("seedInput") ? parseInt($("seedInput").value.trim(), 10) : NaN;
  const seedVal = customSeed !== null ? customSeed : (!isNaN(seedInputVal) ? seedInputVal : state.seed);
  if (isNaN(seedVal) || seedVal < 3000 || seedVal > 9999) {
    state.seed = 3000;
  } else {
    state.seed = seedVal;
  }
  if ($("headerSeedDisplay")) $("headerSeedDisplay").textContent = state.seed;

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
  if ($("tierChip")) $("tierChip").textContent = (spec.tier.charAt(0).toUpperCase() + spec.tier.slice(1)) + " Tier";

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
  state.leakedItems = [];
  state.docTitles = {};
  state.employees = [];
  state.userTags = {};
  state.canaryAssignments = {};
  state.wizardAssignments = {};
  state.canaryHistory = [];
  state.restricted.clear();
  state.selectedEmpId = null;
  state.actionHistory = [];
  state.docsById = {};
  state.suspectIds = null;
  state.highlightSuspects = false;
  state.lastVariantRecipients = [];
  state.suspectCountAtLastPlant = null;
  document.body.classList.remove("highlight-suspects");
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
        <p>Someone in the company is leaking secrets. Survey the office, then plant a canary to about half the staff.</p>
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

  if (res.ok) {
    if (DAILY_ACTION_TOOLS.has(toolName) && state.actionsLeftToday > 0) state.actionsLeftToday--;
    if (state.totalCallsLeft > 0) state.totalCallsLeft--;
  }

  // Sync state from engine response
  if (res.ok && res.data) {
    syncStateFromData(toolName, args, res.data);
  }

  if (res.ok && (toolName === "list_employees" || toolName === "plant_canary" ||
      toolName === "advance_day" || toolName === "check_leak_feed")) {
    fetchDocumentsSilent();
    recomputeSuspects();
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
    state.leakedItems = items;
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
    state.suspectCountAtLastPlant = getSuspectIds().length;
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
// DOCUMENT HOLDERS & SUSPECT INTERSECTION
// -----------------------------------------------------------------------------
// list_documents is free of daily actions (not in INVESTIGATIVE_TOOLS) but still
// counts toward the 300-call cap, so we call it sparingly and never via executeTool.
function fetchDocumentsSilent() {
  if (!game) return;
  try {
    const raw = game.call_json("list_documents", JSON.stringify({ day_from: 1, day_to: state.day }));
    const res = JSON.parse(raw);
    if (!res.ok || !res.data || !Array.isArray(res.data.documents)) return;
    const map = {};
    for (const d of res.data.documents) {
      if (!d || !d.doc_id) continue;
      map[d.doc_id] = d;
      if (d.title) state.docTitles[d.doc_id] = d.title;
    }
    state.docsById = map;
    if (state.totalCallsLeft > 0) state.totalCallsLeft--;
  } catch (_) {}
}

function holdersForLeak(item) {
  if (!item) return [];
  const doc = state.docsById[item.doc_id];
  if (item.variant) {
    if (doc && doc.variants && Array.isArray(doc.variants[item.variant])) {
      return doc.variants[item.variant].slice();
    }
    const hist = state.canaryHistory.find(h => h.id === item.doc_id);
    if (hist && hist.assignment) {
      return Object.entries(hist.assignment)
        .filter(([, v]) => v === item.variant)
        .map(([id]) => id);
    }
    return [];
  }
  if (doc && Array.isArray(doc.recipients)) return doc.recipients.slice();
  return [];
}

function joinNames(names) {
  if (!names || !names.length) return "";
  if (names.length === 1) return names[0];
  if (names.length === 2) return names[0] + " and " + names[1];
  return names.slice(0, -1).join(", ") + ", and " + names[names.length - 1];
}

function suspectsAfterLeaks(items) {
  let current = null;
  for (const item of items || []) {
    const holders = holdersForLeak(item);
    if (!holders.length) continue;
    const set = new Set(holders);
    current = current ? new Set([...current].filter(id => set.has(id))) : set;
  }
  return current;
}

function canaryDeductionLine(item, previousItems) {
  if (!item || !item.variant) return "";
  const holders = holdersForLeak(item);
  if (!holders.length) return "";
  const holderNames = holders.map(id => getEmployeeDisplayName(id));
  const prior = suspectsAfterLeaks(previousItems);
  const priorSet = prior || new Set(state.employees.map(e => e.id));
  const alreadyCleared = holders.filter(id => !priorSet.has(id));
  const remaining = holders.filter(id => priorSet.has(id));
  let line = `Variant ${item.variant} went to ${joinNames(holderNames)}.`;
  if (alreadyCleared.length && remaining.length) {
    const cleared = joinNames(alreadyCleared.map(id => getEmployeeDisplayName(id)));
    const verb = alreadyCleared.length === 1 ? "was" : "were";
    line += ` ${cleared} ${verb} cleared by earlier leaks, so: ${joinNames(remaining.map(id => getEmployeeDisplayName(id)))}.`;
  } else if (remaining.length === 1) {
    line += ` So: ${getEmployeeDisplayName(remaining[0])}.`;
  }
  return line;
}

function latestCanaryPlant() {
  if (!state.canaryHistory.length) return null;
  return state.canaryHistory[state.canaryHistory.length - 1];
}

function canaryRecipientCount(plant) {
  if (!plant || !plant.assignment) return 0;
  return Object.keys(plant.assignment).length;
}

function waitingOnCanary() {
  // A planted canary may take 1–3 days to surface. Don't nag for another plant
  // until then, unless the suspect set has since shrunk (a tighter trap is useful).
  if ((state.leakedItems || []).some(item => !!item.variant)) return false;
  const plant = latestCanaryPlant();
  if (!plant) return false;
  if ((state.day - plant.day) >= 3) return false;
  const n = getSuspectIds().length;
  if (state.suspectCountAtLastPlant != null && n < state.suspectCountAtLastPlant) return false;
  return true;
}

function getSuspectIds() {
  if (!state.employees.length) return [];
  if (!state.suspectIds) return state.employees.map(e => e.id);
  return state.employees.map(e => e.id).filter(id => state.suspectIds.has(id));
}

function recomputeSuspects() {
  if (!state.employees.length) {
    state.suspectIds = null;
    state.lastVariantRecipients = [];
    return;
  }
  let current = null;
  let lastVariant = [];
  for (const item of (state.leakedItems || [])) {
    const holders = holdersForLeak(item);
    if (!holders.length) continue;
    const set = new Set(holders);
    current = current ? new Set([...current].filter(id => set.has(id))) : set;
    if (item.variant) {
      lastVariant = holders.map(id => getEmployeeDisplayName(id));
    }
  }
  state.suspectIds = current;
  state.lastVariantRecipients = lastVariant;
  refreshSuspectHighlights();
}

function refreshSuspectHighlights() {
  const ids = new Set(getSuspectIds());
  document.querySelectorAll(".emp-card").forEach(c => {
    c.classList.toggle("in-suspect-set", ids.has(c.dataset.id));
  });
  document.body.classList.toggle("highlight-suspects", !!state.highlightSuspects);
  const btn = $("hudSuspectsBtn");
  if (btn) btn.classList.toggle("active", !!state.highlightSuspects);
}

function toggleSuspectHighlight() {
  if (!state.employees.length) return;
  state.highlightSuspects = !state.highlightSuspects;
  refreshSuspectHighlights();
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
  if ($("callCounterChip")) $("callCounterChip").textContent = `${callsSpent} call${callsSpent === 1 ? "" : "s"}`;

  const susCountEl = $("hudSuspectsCount");
  const susSubEl = $("hudSuspectsSub");
  if (susCountEl && susSubEl) {
    if (!state.employees.length) {
      susCountEl.textContent = "—";
      susSubEl.textContent = "survey first";
    } else {
      const n = getSuspectIds().length;
      susCountEl.textContent = String(n);
      susSubEl.textContent = n === 1 ? "1 person" : (state.leaksCount ? `${n} people` : "no leaks yet");
    }
  }

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

function getUntaggedEmployees() {
  const taggedIds = new Set();
  for (const h of state.canaryHistory) {
    if (h.assignment) {
      for (const [id, v] of Object.entries(h.assignment)) {
        if (v && v !== "–") taggedIds.add(id);
      }
    }
  }
  return state.employees.filter(e => !taggedIds.has(e.id) && !state.restricted.has(e.id));
}

function updateGuidance() {
  const el = $("hudGuidanceText");
  if (!el) return;

  if (state.employees.length === 0) {
    el.textContent = state.actionsLeftToday === 0
      ? "All daily actions spent. Press Next Day [N]."
      : "Survey the office, then plant a canary to about half the staff.";
    return;
  }

  const nSuspects = getSuspectIds().length;
  const plantedToday = state.canaryHistory.some(c => c.day === state.day);
  const hasVariantLeak = (state.leakedItems || []).some(item => !!item.variant);
  const waiting = waitingOnCanary();
  const waitHint = (() => {
    const plant = latestCanaryPlant();
    const n = canaryRecipientCount(plant);
    return n
      ? `Canary out to ${n} people. Leaks take 1–3 days. Advance the day.`
      : "Leaks take 1–3 days. Advance the day.";
  })();

  if (state.actionsLeftToday === 0) {
    el.textContent = "All daily actions spent. Press Next Day [N] so leaks can surface.";
    return;
  }

  if (state.day > 1 && !state.checkedLeaksToday) {
    el.textContent = "Check the leak feed.";
    return;
  }

  if (state.day >= state.maxDays && nSuspects > 1) {
    el.textContent = `${nSuspects} suspects remain on the last day. Accuse only if you are sure; otherwise close the case.`;
    return;
  }

  if (nSuspects === 1) {
    const name = getEmployeeDisplayName(getSuspectIds()[0]);
    el.textContent = hasVariantLeak
      ? `The leaked canary went only to ${name}. Accuse them.`
      : `Suspects narrowed to ${name}. Accuse them.`;
    return;
  }

  if (hasVariantLeak && state.lastVariantRecipients.length) {
    const names = joinNames(state.lastVariantRecipients);
    if (plantedToday || waiting) {
      el.textContent = `Canary variant holders: ${names}. Advance to tomorrow [N], or accuse if you are sure.`;
    } else {
      el.textContent = `Canary variant holders: ${names}. Plant a small canary among them, or accuse if only one remains.`;
    }
    return;
  }

  if (waiting) {
    el.textContent = waitHint;
    return;
  }

  if (state.leaksCount > 0) {
    if (plantedToday) {
      el.textContent = `Suspects narrowed to ${nSuspects}. Advance to tomorrow [N] so the canary can surface.`;
    } else {
      el.textContent = `Suspects narrowed to ${nSuspects}. Plant a small canary among them.`;
    }
    return;
  }

  if (!state.canaryHistory.length) {
    el.textContent = "Plant a canary to about half the staff. Leave the rest unassigned.";
    return;
  }

  if (plantedToday) {
    el.textContent = waitHint;
    return;
  }

  el.textContent = "Plant a small canary among the remaining suspects, then advance a day.";
}

function showInPageHint(message) {
  const el = $("hudGuidanceText");
  const bar = $("hudGuidanceBar");
  if (el) {
    el.textContent = message;
  }
  if (bar) {
    bar.classList.remove("guidance-pulse");
    void bar.offsetWidth;
    bar.classList.add("guidance-pulse");
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
  refreshSuspectHighlights();
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

  let lockHtml = isLocked ? `<div class="emp-card-top" style="justify-content:flex-end;"><span class="locked-badge">Restricted</span></div>` : "";

  card.innerHTML = `
    ${lockHtml}
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

  if ($("dosId")) $("dosId").textContent = "";
  $("dosName").textContent = emp.name;
  $("dosRole").textContent = emp.role || "Member";
  $("dosDeptBadge").textContent = emp.dept || "Staff";
  if ($("msgQueryInput")) $("msgQueryInput").value = "";

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
        const title = item.title || state.docTitles[item.doc_id] || "Memo";
        const holderNames = holdersForLeak(item).map(id => getEmployeeDisplayName(id));
        const prevItems = items.slice(0, items.indexOf(item));

        let badgeHtml = "";
        let detailsHtml = "";

        if (isCanary && v) {
          badgeHtml = `<span class="canary-pill canary-pill-${vClass}">Canary Variant ${v}</span>`;
          const deduction = canaryDeductionLine(item, prevItems);
          detailsHtml = deduction
            ? `<div class="muted font-small" style="margin-top:2px;">${deduction}</div>`
            : (holderNames.length
              ? `<div class="muted font-small" style="margin-top:2px;">Who had this memo (variant ${v}): ${joinNames(holderNames)}</div>`
              : "");
        } else if (isCanary) {
          badgeHtml = `<span class="canary-pill canary-pill-a">Canary Leak</span>`;
          detailsHtml = holderNames.length
            ? `<div class="muted font-small" style="margin-top:2px;">Who had this memo: ${joinNames(holderNames)}</div>`
            : `<div class="muted font-small" style="margin-top:2px;">Planted canary leaked.</div>`;
        } else {
          badgeHtml = `<span class="regular-doc-pill">Regular Document</span>`;
          detailsHtml = holderNames.length
            ? `<div class="muted font-small" style="margin-top:2px;">Who had this memo: ${joinNames(holderNames)}</div>`
            : `<div class="muted font-small" style="margin-top:2px;">Standard memo. Cross-reference who had access.</div>`;
        }

        html += `
          <div style="background:var(--panel-elevated); border:1px solid var(--line); border-radius:4px; padding:8px; margin-bottom:6px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px; gap:8px; flex-wrap:wrap;">
              <div>
                <span class="chip" style="color:var(--ok); border-color:var(--ok); font-weight:700; margin-right:4px;">NEW</span>
                <strong>${title}</strong>
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
        <strong>Canary deployed:</strong> "${args.doc_title || 'Memo'}"
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
    showInPageHint("Please survey office personnel first so staff IDs are indexed.");
    return;
  }

  const canaryNum = state.canaryHistory.length + 1;
  const sampleTitles = [
    `Board memo draft ${canaryNum}`,
    `Executive compensation review ${canaryNum}`,
    `Product roadmap strategy v${canaryNum}.0`,
    `M&A acquisition preliminary review ${canaryNum}`,
    `Q${Math.min(4, Math.floor(state.day / 3) + 1)} confidential earnings memo`
  ];
  $("canaryDocTitle").value = sampleTitles[(canaryNum - 1) % sampleTitles.length];

  // Never auto-cover untagged staff. Later plants retest a tight group of remaining suspects.
  if (state.canaryHistory.length > 0 || (state.suspectIds && state.suspectIds.size && state.suspectIds.size < state.employees.length)) {
    wizardRetestCohort();
  } else {
    wizardSplitSolver();
  }
  $("canaryModal").hidden = false;
}

function closeCanaryWizard() {
  $("canaryModal").hidden = true;
}

function wizardRetestCohort() {
  // Tight 2–6 person retest of people still in the leak intersection (or tagged suspects).
  const ids = new Set(getSuspectIds());
  const tagged = state.employees.filter(e => state.userTags[e.id] === "suspect" && !state.restricted.has(e.id) && ids.has(e.id));
  const pool = (tagged.length >= 2 ? tagged : state.employees.filter(e => !state.restricted.has(e.id) && ids.has(e.id)));

  state.wizardAssignments = {};
  for (const emp of state.employees) state.wizardAssignments[emp.id] = "";

  const variants = pool.length === 2 ? ["A", "B"] : ["A", "B", "C"];
  const targetCount = pool.length <= 6 ? pool.length : 6;
  // Rotate the 6-person window each plant so later-listed suspects are not skipped forever.
  const offset = pool.length ? (state.canaryHistory.length * targetCount) % pool.length : 0;
  for (let i = 0; i < targetCount; i++) {
    const emp = pool[(offset + i) % pool.length];
    state.wizardAssignments[emp.id] = variants[i % variants.length];
  }

  renderWizardEmployees();
  updateWholeCompanyWarning();
}

function wizardCoverUntagged() {
  const untagged = getUntaggedEmployees();
  state.wizardAssignments = {};
  for (const emp of state.employees) {
    state.wizardAssignments[emp.id] = "";
  }

  if (untagged.length === 0) {
    showInPageHint("All active personnel have already received canaries.");
    renderWizardEmployees();
    updateWholeCompanyWarning();
    return;
  }

  const variants = untagged.length === 2 ? ["A", "B"] : ["A", "B", "C"];
  untagged.forEach((emp, idx) => {
    state.wizardAssignments[emp.id] = variants[idx % variants.length];
  });

  renderWizardEmployees();
  updateWholeCompanyWarning();
}

function wizardSplitSolver() {
  // Solver style: balance cohorts across variants (A, B, C) while leaving a control group unassigned.
  // In Medium tier, careful moles will never leak a document sent to the whole company!
  const suspects = state.employees.filter(e => state.userTags[e.id] === "suspect" && !state.restricted.has(e.id));
  const pool = suspects.length >= 2 ? suspects : state.employees.filter(e => !state.restricted.has(e.id));

  state.wizardAssignments = {};
  for (const emp of state.employees) {
    state.wizardAssignments[emp.id] = "";
  }

  const variants = ["A", "B", "C"];
  if (suspects.length >= 2) {
    suspects.forEach((emp, idx) => {
      state.wizardAssignments[emp.id] = variants[idx % variants.length];
    });
  } else {
    // 8-9 staff across A/B/C (~40-45% of workforce), leaving control group
    const targetCount = Math.min(pool.length, Math.max(3, Math.min(9, Math.floor(pool.length * 0.45))));
    const selected = pool.slice(0, targetCount);
    selected.forEach((emp, idx) => {
      state.wizardAssignments[emp.id] = variants[idx % variants.length];
    });
  }

  renderWizardEmployees();
  updateWholeCompanyWarning();
}

function renderWizardEmployees() {
  const grid = $("wizardEmpGrid");
  grid.innerHTML = "";

  const untaggedSet = new Set(getUntaggedEmployees().map(e => e.id));

  for (const emp of state.employees) {
    const chip = document.createElement("div");
    chip.className = "wizard-emp-chip";
    chip.dataset.id = emp.id;

    const currentVar = state.wizardAssignments[emp.id] || "";
    if (currentVar) chip.classList.add(`assign-${currentVar.toLowerCase()}`);

    const isUntagged = untaggedSet.has(emp.id);
    const tagSub = isUntagged
      ? `<span class="chip-untagged-label">Untagged</span>`
      : `<span class="chip-tagged-label">Prior canary</span>`;

    chip.innerHTML = `
      <div style="display:flex; flex-direction:column; gap:1px; overflow:hidden;">
        <span style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap;"><strong>${emp.name}</strong></span>
        ${state.canaryHistory.length > 0 ? tagSub : ''}
      </div>
      <span class="mono font-small chip-var">${currentVar || '–'}</span>
    `;

    chip.addEventListener("click", () => {
      // Cycle: "" -> "A" -> "B" -> "C" -> ""
      const variants = ["", "A", "B", "C"];
      const cur = state.wizardAssignments[emp.id] || "";
      const nextIdx = (variants.indexOf(cur) + 1) % variants.length;
      const nextVar = variants[nextIdx];

      chip.classList.remove("assign-a", "assign-b", "assign-c");
      if (nextVar) chip.classList.add(`assign-${nextVar.toLowerCase()}`);
      chip.querySelector(".chip-var").textContent = nextVar || "–";
      state.wizardAssignments[emp.id] = nextVar;
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
  if (assigned.length === state.employees.length && state.employees.length > 0) {
    warn.style.display = "block";
    warn.innerHTML = "<strong>Warning:</strong> Careful moles will not leak a full-company document. Leave some staff unassigned.";
  } else if (assigned.length >= 10) {
    warn.style.display = "block";
    warn.innerHTML = `<strong>Note:</strong> ${assigned.length} recipients. Tighter traps (2–6 people) leak more often.`;
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
    state.wizardAssignments[c.dataset.id] = v;
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
    state.wizardAssignments[c.dataset.id] = v;
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
    showInPageHint("Please assign at least one employee to a canary variant.");
    return;
  }

  const uniqueVariants = new Set(Object.values(assignment));
  if (uniqueVariants.size > 3) {
    showInPageHint("Maximum of 3 variants (A, B, C) allowed in medium tier.");
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
    showInPageHint("Please survey office personnel first so staff IDs are indexed.");
    return;
  }

  populateAccuseDropdown(state.employees, { expandOthers: false });

  const select = $("accuseSuspectSelect");
  const suspects = getSuspectIds();
  if (suspects.length === 1) {
    select.value = suspects[0];
  } else if (preselectEmpId && suspects.includes(preselectEmpId)) {
    select.value = preselectEmpId;
  } else if (state.selectedEmpId && suspects.includes(state.selectedEmpId)) {
    select.value = state.selectedEmpId;
  } else if (preselectEmpId) {
    // Named preselect (e.g. from a dossier) even if already cleared; expand Others so it's visible.
    populateAccuseDropdown(state.employees, { expandOthers: true });
    select.value = preselectEmpId;
  }

  updateAccuseTargetName();
  recalculateAccuseMath();
  $("accuseModal").hidden = false;
}

function closeAccuseDialog() {
  $("accuseModal").hidden = true;
}

function accuseOption(emp) {
  const opt = document.createElement("option");
  opt.value = emp.id;
  opt.textContent = `${emp.name} (${emp.dept || 'Staff'}, ${emp.role || 'Member'})`;
  return opt;
}

function populateAccuseDropdown(employees, opts = {}) {
  const select = $("accuseSuspectSelect");
  if (!select) return;
  const expandOthers = !!opts.expandOthers;
  const current = (select.value && select.value !== "__others__") ? select.value : "";
  const suspectIds = new Set(getSuspectIds());
  const suspects = employees.filter(e => suspectIds.has(e.id));
  const others = employees.filter(e => !suspectIds.has(e.id));

  select.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "-- Choose someone --";
  select.appendChild(placeholder);

  if (suspects.length) {
    const group = document.createElement("optgroup");
    group.label = suspects.length === 1 ? "Still suspected" : `Still suspected (${suspects.length})`;
    for (const emp of suspects) group.appendChild(accuseOption(emp));
    select.appendChild(group);
  }

  if (others.length) {
    if (expandOthers) {
      const group = document.createElement("optgroup");
      group.label = "Others";
      for (const emp of others) group.appendChild(accuseOption(emp));
      select.appendChild(group);
    } else {
      const more = document.createElement("option");
      more.value = "__others__";
      more.textContent = `Others (${others.length})…`;
      select.appendChild(more);
    }
  }

  if (current && Array.from(select.options).some(o => o.value === current)) {
    select.value = current;
  }
}

function updateAccuseTargetName() {
  const select = $("accuseSuspectSelect");
  if (select && select.value === "__others__") {
    populateAccuseDropdown(state.employees, { expandOthers: true });
    select.value = "";
  }
  const empId = $("accuseSuspectSelect").value;
  const emp = state.employees.find(e => e.id === empId);
  if ($("accuseTargetBtnName")) $("accuseTargetBtnName").textContent = emp ? emp.name : "Suspect";
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

  const adviceBox = $("mathAdviceBox");
  const adviceText = $("mathAdviceText");
  const confirmBtn = $("confirmAccuseBtn");
  const warnText = $("confirmWarningText");

  const evRounded = Math.round(ev * 10000) / 10000;

  if (evRounded > 0) {
    $("mathEVDisplay").textContent = `+${ev.toFixed(2)}`;
    $("mathEVDisplay").style.color = "var(--ok)";
    if (adviceBox) adviceBox.className = "math-advice-box advice-favorable";
    if (adviceText) adviceText.textContent = "Accusing now gains value on average.";
    if (confirmBtn) confirmBtn.className = "btn-danger btn-large";
    if (warnText) warnText.style.display = "none";
  } else if (evRounded === 0) {
    $("mathEVDisplay").textContent = "0.00 (break-even)";
    $("mathEVDisplay").style.color = "var(--ink)";
    if (adviceBox) adviceBox.className = "math-advice-box advice-neutral";
    if (adviceText) adviceText.textContent = "Accusing now is break-even on average.";
    if (confirmBtn) confirmBtn.className = "btn-danger btn-large";
    if (warnText) warnText.style.display = "none";
  } else {
    $("mathEVDisplay").textContent = ev.toFixed(2);
    $("mathEVDisplay").style.color = "var(--warn)";
    if (adviceBox) adviceBox.className = "math-advice-box advice-unfavorable";
    if (adviceText) adviceText.textContent = "Accusing now loses value on average.";
    if (confirmBtn) confirmBtn.className = "btn-secondary btn-large btn-warn";
    if (warnText) warnText.style.display = "none";
  }
}

function confirmAccusation() {
  const empId = $("accuseSuspectSelect").value;
  if (!empId) {
    showInPageHint("Please select the suspect you wish to accuse.");
    return;
  }
  const emp = state.employees.find(e => e.id === empId);
  const targetName = emp ? emp.name : empId;

  const p = parseInt($("certaintySlider").value, 10) / 100;
  const V = state.knownV;
  const breakEvenP = 1 / (1 + V);

  const doAccuse = () => {
    state.decisionDay = state.day;
    state.decisionV = state.knownV;
    state.decisionBreakEvenP = breakEvenP;
    state.chosenSuspect = empId;
    closeAccuseDialog();
    executeTool("accuse", { employee: empId });
  };

  if (p < breakEvenP) {
    showConfirmDialog({
      title: "Confirm Low-Certainty Accusation",
      message: `Your certainty (<strong>${Math.round(p * 100)}%</strong>) is below the break-even threshold (<strong>${(breakEvenP * 100).toFixed(1)}%</strong>).<br><br>Accusing <strong>${targetName}</strong> loses value on average. A false accusation incurs a -1.00 penalty.<br><br>Are you sure you want to accuse <strong>${targetName}</strong>?`,
      okText: `Accuse ${targetName}`,
      isDanger: true,
      onConfirm: doAccuse
    });
    return;
  }

  doAccuse();
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
// END SCREEN
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
  if (icon) icon.textContent = "";

  if (isWin) {
    title.textContent = "INVESTIGATION SUCCESSFUL";
    sub.textContent = `You correctly identified ${moleName} as the mole and preserved company value.`;
  } else if (isAbstain) {
    title.textContent = "INVESTIGATION CLOSED: ABSTAINED";
    sub.textContent = `You closed the investigation without an accusation, preserving 0.00 score and avoiding the -1.00 false accusation penalty.`;
  } else {
    title.textContent = "INVESTIGATION FAILED";
    const accusedName = getEmployeeDisplayName(reveal.you.accused);
    sub.textContent = `You accused ${accusedName}, but the real mole was ${moleName}. False accusations incur a -1.00 penalty.`;
  }

  // Score Display
  const scoreDisplay = $("endScoreDisplay");
  if (scoreDisplay) {
    const scoreColor = reveal.you.score > 0 ? "var(--ok)" : reveal.you.score < 0 ? "var(--err)" : "inherit";
    scoreDisplay.innerHTML = `<span class="muted font-small">Final Score: </span><span class="mono" style="color:${scoreColor}; font-weight:700; font-size:20px;">${fmt(reveal.you.score)}</span>`;
  }

  // Flipping Mole Card
  const moleEmp = state.employees.find(e => e.id === moleId) || { name: moleName, dept: "Unknown", role: "Mole" };
  $("moleNameDisplay").textContent = moleName;
  $("moleMetaDisplay").textContent = `${moleEmp.dept} · ${moleEmp.role}`;

  const flipCard = $("moleFlipCard");
  if (flipCard) {
    flipCard.classList.remove("revealed");
    setTimeout(() => {
      flipCard.classList.add("revealed");
    }, 400);
  }

  const decisionDay = state.decisionDay || reveal.you.final_day || state.day;
  const decisionV = state.decisionV !== null ? state.decisionV : (reveal.you.score > 0 ? reveal.you.score : state.knownV);
  const breakEvenP = state.decisionBreakEvenP !== null ? state.decisionBreakEvenP : (1 / (1 + decisionV));

  // Scoreboard Table (Honest Labeling)
  const scoreboard = $("scoreboardBody");
  if (scoreboard) {
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
  }

  // "You Were Fooled" Callout
  const fooledBox = $("fooledCallout");
  if (fooledBox) {
    const moleTag = state.userTags[moleId];
    if (moleTag === "cleared") {
      fooledBox.hidden = false;
      if ($("fooledHeading")) $("fooledHeading").textContent = "Investigator Note";
      if ($("fooledMessage")) $("fooledMessage").textContent = `During the investigation, you tagged ${moleDisplayName} as 'Cleared'. The mole successfully maintained a low profile and deflected your suspicion.`;
    } else if (!isWin && reveal.you.accused) {
      fooledBox.hidden = false;
      const accusedEmp = state.employees.find(e => e.id === reveal.you.accused);
      const accusedDisp = accusedEmp ? accusedEmp.name : getEmployeeDisplayName(reveal.you.accused);
      if ($("fooledHeading")) $("fooledHeading").textContent = "Investigator Note";
      if ($("fooledMessage")) $("fooledMessage").textContent = `You accused ${accusedDisp}. The true mole planted fabricated after-hours access logs and exploited delayed leaks to frame colleagues.`;
    } else {
      fooledBox.hidden = true;
    }
  }

  // "Your Call" Regret Analysis
  const regretBox = $("regretAnalysisText");
  if (regretBox) {
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
  }

  // Action Replay Timeline
  if ($("solverAccuseDayChip")) $("solverAccuseDayChip").textContent = `Reference Solver accused Day ${reveal.solver.final_day}`;
  const replayBox = $("replayTimeline");
  if (replayBox) {
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
  $("startTutorialBtn")?.addEventListener("click", () => startTutorial());

  $("seedInput")?.addEventListener("input", (e) => {
    const s = parseInt(e.target.value.trim(), 10);
    if (!isNaN(s)) {
      state.seed = s;
      $("headerSeedDisplay").textContent = s;
    }
  });

  $("seedInput")?.addEventListener("change", (e) => {
    const s = parseInt(e.target.value.trim(), 10);
    if (!isNaN(s) && s >= 3000 && s <= 9999) {
      state.seed = s;
      $("headerSeedDisplay").textContent = s;
    }
  });

  $("randomSeedBtn")?.addEventListener("click", () => {
    const s = randomSeed();
    if ($("seedInput")) $("seedInput").value = s;
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
        message: "You already checked the leak feed today.<br><br>New leaks only surface when you advance to a new day. Spend 1 action to re-check anyway?",
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
    const q = inputVal ? resolveSearchQuery(inputVal) : (state.selectedEmpId || "");
    if (!q) return;
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
  $("hudSuspectsBtn")?.addEventListener("click", toggleSuspectHighlight);
  $("wizardCoverUntaggedBtn")?.addEventListener("click", wizardCoverUntagged);
  $("wizardSplitSolverBtn")?.addEventListener("click", wizardSplitSolver);
  $("wizardSplitEvenBtn")?.addEventListener("click", () => {
    if (state.canaryHistory.length > 0 || (state.suspectIds && state.suspectIds.size < state.employees.length)) {
      wizardRetestCohort();
    } else {
      wizardSplitSolver();
    }
  });
  $("wizardSplitTwoBtn")?.addEventListener("click", () => wizardSplit(2));
  $("wizardSplitDeptBtn")?.addEventListener("click", wizardSplitByDept);
  $("wizardClearBtn").addEventListener("click", () => {
    document.querySelectorAll(".wizard-emp-chip").forEach(c => {
      c.classList.remove("assign-a", "assign-b", "assign-c");
      c.querySelector(".chip-var").textContent = "–";
      state.wizardAssignments[c.dataset.id] = "";
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
  $("helpShortcutBtn")?.addEventListener("click", () => {
    $("shortcutsModal").hidden = false;
  });
  $("closeShortcutsBtn").addEventListener("click", () => {
    $("shortcutsModal").hidden = true;
  });
  $("demoToggleBtn")?.addEventListener("click", () => {
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
