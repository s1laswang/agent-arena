import {
  el,
  clear,
  pad2,
  fmtScore,
  setDocument,
  MODE_DEFS,
  TOOL_GROUPS,
  TOOL_DEFS,
  DEFAULT_DUEL_SEEDS,
} from "./dom.js";

const INTERVIEW_TOPICS = [
  "recent_documents",
  "contacts_outside",
  "workload",
  "access_needs",
];

const DEFAULT_LIVING_BANNER =
  "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift";

const DEFAULT_ASSET_CREDITS =
  "Art & tiles: Kenney CC0 pixel packs (see docs/arena/ASSETS.md) + Canary procedural pixel office stage";

const ZONE_SWATCHES = [
  { name: "Engineering", color: "rgb(56, 152, 236)" },
  { name: "Research", color: "rgb(46, 196, 198)" },
  { name: "Finance", color: "rgb(52, 188, 122)" },
  { name: "Sales", color: "rgb(235, 168, 52)" },
  { name: "Legal & Exec", color: "rgb(186, 118, 224)" },
];

const FORBIDDEN_PRE_END_KEYS = new Set([
  "mole",
  "true_mole",
  "moleId",
  "mole_id",
  "decoy",
  "correct",
  "true_v",
  "trueV",
  "is_canary",
  "leaking_sprite_employee",
]);

function getGlobalObj() {
  return typeof globalThis !== "undefined" ? globalThis : {};
}

function computePhase(actionsUsed, perDay, justAdvanced) {
  if (justAdvanced) return "night";
  const used = Number(actionsUsed) || 0;
  const cap = Math.max(1, Number(perDay) || 8);
  const ratio = used / cap;
  if (ratio <= 0.2) return "morning";
  if (ratio <= 0.6) return "afternoon";
  if (ratio < 1.0) return "dusk";
  return "night";
}

export function sanitizeStepForPreEnd(step) {
  if (!step || typeof step !== "object") return null;
  const tool = String(step.tool || "");
  const isAccuse = tool === "accuse";
  const rawV =
    step.V !== undefined
      ? step.V
      : step.known_v !== undefined
        ? step.known_v
        : step.visible_V;
  const safeV = Number.isFinite(Number(rawV)) ? Number(rawV) : null;
  return {
    day: Number(step.day) || 1,
    call_idx: Number(step.call_idx) || 0,
    tool,
    args: isAccuse ? "[SEALED]" : step.args ? scrubPreEndObject(step.args) : {},
    ok: step.ok !== false,
    summary: isAccuse
      ? "Accusation filed [SEALED]"
      : String(step.summary || tool),
    V: safeV,
    sealed: isAccuse,
  };
}

export function scrubPreEndObject(input) {
  if (input === null || input === undefined) return input;
  if (Array.isArray(input)) {
    return input.map((item) => scrubPreEndObject(item));
  }
  if (typeof input !== "object") return input;
  const out = {};
  for (const [k, v] of Object.entries(input)) {
    if (FORBIDDEN_PRE_END_KEYS.has(k)) continue;
    out[k] = scrubPreEndObject(v);
  }
  return out;
}

export function sanitizeGeminiReplayState(rawView, humanDay, humanDone) {
  if (!rawView || typeof rawView !== "object") {
    return {
      available: false,
      agent: "opencode:google/gemini-4-carbon",
      steps: [],
      status: "unavailable",
      sealed_day: null,
      final: null,
    };
  }
  const dayCap = Math.max(1, Number(humanDay) || 1);
  const allSteps = Array.isArray(rawView.steps) ? rawView.steps : [];
  if (humanDone === true) {
    return {
      available: true,
      seed: rawView.seed,
      tier: rawView.tier || "hard",
      agent: rawView.agent || "opencode:google/gemini-4-carbon",
      steps: allSteps.map((s) => ({
        day: Number(s.day) || 1,
        call_idx: Number(s.call_idx) || 0,
        tool: String(s.tool || ""),
        args: s.args || {},
        ok: s.ok !== false,
        summary: String(s.summary || s.tool || ""),
        V:
          s.V !== undefined
            ? Number(s.V)
            : s.known_v !== undefined
              ? Number(s.known_v)
              : null,
        sealed: false,
      })),
      status: "unlocked",
      sealed_day: null,
      final: rawView.final || rawView.sealed_verdict || null,
    };
  }
  const gatedSteps = [];
  let sealedDay = rawView.sealed_day ? Number(rawView.sealed_day) : null;
  let status = rawView.status === "sealed_accusation" ? "sealed_accusation" : "hunting";
  for (const step of allSteps) {
    const sDay = Number(step && step.day) || 1;
    if (sDay <= dayCap) {
      const clean = sanitizeStepForPreEnd(step);
      if (clean) {
        if (clean.sealed) {
          status = "sealed_accusation";
          if (sealedDay === null || sDay < sealedDay) sealedDay = sDay;
        }
        gatedSteps.push(clean);
      }
    }
  }
  return {
    available: true,
    seed: rawView.seed,
    tier: rawView.tier || "hard",
    agent: rawView.agent || "opencode:google/gemini-4-carbon",
    steps: gatedSteps,
    status,
    sealed_day: sealedDay,
    final: null,
  };
}

export function sanitizeSolverLiveState(rawView, humanDay, humanDone) {
  if (!rawView || typeof rawView !== "object") {
    return {
      available: false,
      day: Number(humanDay) || 1,
      visible_V: 1.0,
      canaries_planted: 0,
      interviews_done: 0,
      restricted_count: 0,
      tool_calls_so_far: 0,
      top_posterior_prob: 0.05,
      entropy_bits: 4.32,
      status: "unavailable",
      sealed_day: null,
      final: null,
    };
  }
  const dayCap = Math.max(1, Number(humanDay) || 1);
  if (humanDone === true) {
    const fin = rawView.final || {
      accused: rawView.accused || null,
      correct: Boolean(rawView.correct),
      final_day: Number(rawView.final_day || rawView.day || dayCap),
      tool_calls: Number(rawView.tool_calls || rawView.tool_calls_so_far || 0),
      score: Number(rawView.score || 0),
    };
    return {
      available: true,
      day: Number(rawView.day || fin.final_day || dayCap),
      visible_V: Number(rawView.visible_V !== undefined ? rawView.visible_V : 1.0),
      canaries_planted: Number(rawView.canaries_planted || 0),
      interviews_done: Number(rawView.interviews_done || 0),
      restricted_count: Number(rawView.restricted_count || 0),
      tool_calls_so_far: Number(rawView.tool_calls_so_far || fin.tool_calls || 0),
      top_posterior_prob: Number(rawView.top_posterior_prob || 0),
      entropy_bits: Number(rawView.entropy_bits || 0),
      status: "unlocked",
      sealed_day: null,
      final: fin,
    };
  }
  const rawAccusedEarly =
    rawView.status === "sealed_accusation" ||
    (rawView.final_day !== undefined && Number(rawView.final_day) <= dayCap && Boolean(rawView.accused));
  return {
    available: true,
    day: Math.min(dayCap, Number(rawView.day || dayCap)),
    visible_V: Number(rawView.visible_V !== undefined ? rawView.visible_V : 1.0),
    canaries_planted: Number(rawView.canaries_planted || 0),
    interviews_done: Number(rawView.interviews_done || 0),
    restricted_count: Number(rawView.restricted_count || 0),
    tool_calls_so_far: Number(rawView.tool_calls_so_far || 0),
    top_posterior_prob: Math.max(0, Math.min(1, Number(rawView.top_posterior_prob || 0.05))),
    entropy_bits: Math.max(0, Number(rawView.entropy_bits !== undefined ? rawView.entropy_bits : 4.0)),
    status: rawAccusedEarly ? "sealed_accusation" : "hunting",
    sealed_day: rawAccusedEarly
      ? Number(rawView.sealed_day || rawView.final_day || dayCap)
      : null,
    final: null,
  };
}

export function computeFirstCatchLabel(summary) {
  if (!summary || summary.humanDone !== true) return "None";
  const candidates = [];
  if (summary.you && summary.you.correct === true) {
    candidates.push({ label: "You", day: Number(summary.you.final_day || 999), prio: 1 });
  }
  if (summary.solver && summary.solver.correct === true) {
    candidates.push({ label: "Solver", day: Number(summary.solver.final_day || 999), prio: 2 });
  }
  if (summary.gemini && summary.gemini.correct === true) {
    candidates.push({ label: "Gemini", day: Number(summary.gemini.final_day || 999), prio: 3 });
  }
  if (!candidates.length) return "None";
  candidates.sort((a, b) => (a.day !== b.day ? a.day - b.day : a.prio - b.prio));
  return candidates[0].label;
}

export function buildCanonicalShareLine(summary, shareCardAdapter) {
  if (!summary || summary.humanDone !== true) return "";
  if (shareCardAdapter && typeof shareCardAdapter.formatLine === "function") {
    return String(shareCardAdapter.formatLine(summary));
  }
  const seed = summary.seed;
  const tier = summary.tier || "hard";
  if (summary.mode === "mole") {
    const surv = Number(summary.daysSurvived || 0);
    const leaks = Number(summary.leaksLanded || 0);
    const sScore = summary.solver ? fmtScore(summary.solver.score) : "0.00";
    return `CANARY ARENA | Seed ${seed} (${tier}, Mole) | Survived ${surv}d (${leaks} leaks) vs Solver ${sScore}`;
  }
  const fmtActor = (name, rec, isGemini) => {
    if (!rec) return null;
    const sc = fmtScore(rec.score);
    const day = Number(rec.final_day || 0);
    if (rec.correct) return `${name} ${sc} (Day ${day})`;
    if (rec.accused) {
      return `${name} ${sc} (${isGemini ? "Fooled " : "Wrong "}Day ${day})`;
    }
    return `${name} ${sc} (Horizon Day ${day})`;
  };
  const parts = [fmtActor("You", summary.you, false)];
  if (summary.mode === "duel" && summary.gemini) {
    parts.push(fmtActor("Gemini", summary.gemini, true));
  }
  if (summary.solver) {
    parts.push(fmtActor("Solver", summary.solver, false));
  }
  const firstCatch = computeFirstCatchLabel(summary);
  return `CANARY ARENA | Seed ${seed} (${tier}) | ${parts.filter(Boolean).join(" vs ")} | First catch: ${firstCatch}`;
}

function parseRulesText(instructionText) {
  const txt = String(instructionText || "");
  const num = (rx, fallback) => {
    const m = txt.match(rx);
    return m ? Number(m[1]) : fallback;
  };
  const costMatch = txt.match(/^- (.+?) each use one of your \d+ actions per day/m);
  const costed = costMatch
    ? new Set(
        costMatch[1]
          .replace(/`/g, "")
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean)
      )
    : new Set(
        Object.entries(TOOL_DEFS)
          .filter(([, meta]) => meta.costed)
          .map(([k]) => k)
      );
  return {
    cap: num(/limit of (\d+) calls/, 420),
    nDays: num(/lasts at most (\d+) days/, 21),
    perDay: num(/one of your (\d+) actions per day/, 8),
    maxVariants: num(/Use at most (\d+) different labels/, 3),
    wrongScore: num(/If you accuse an innocent employee, your score is (-?\d+(?:\.\d+)?)/, -1),
    costed,
  };
}

function createLeaderboardMemory(storageObj) {
  const key = "canary_arena_leaderboard_v1";
  let mem = [];
  const load = () => {
    if (storageObj && typeof storageObj.getItem === "function") {
      try {
        const raw = storageObj.getItem(key);
        if (raw) {
          const parsed = JSON.parse(raw);
          if (Array.isArray(parsed)) return parsed;
        }
      } catch (_) {}
    }
    return mem.slice();
  };
  const save = (rows) => {
    mem = rows.slice(0, 100);
    if (storageObj && typeof storageObj.setItem === "function") {
      try {
        storageObj.setItem(key, JSON.stringify(mem));
      } catch (_) {}
    }
  };
  return {
    list(modeFilter) {
      const rows = load();
      if (!modeFilter || modeFilter === "all") return rows;
      return rows.filter((r) => r && r.mode === modeFilter);
    },
    add(entry) {
      const rows = load();
      rows.unshift(entry);
      save(rows);
    },
    clear() {
      save([]);
    },
  };
}

function drawProceduralOfficeFallback(canvas, state) {
  if (!canvas || typeof canvas.getContext !== "function") return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const w = Number(canvas.width) || 640;
  const h = Number(canvas.height) || 320;
  ctx.fillStyle = "#171512";
  ctx.fillRect(0, 0, w, h);
  const zones = [
    { x: 16, y: 20, zw: 184, zh: 112, color: "rgb(56, 152, 236)" },
    { x: 220, y: 20, zw: 184, zh: 112, color: "rgb(46, 196, 198)" },
    { x: 424, y: 20, zw: 196, zh: 112, color: "rgb(52, 188, 122)" },
    { x: 16, y: 156, zw: 280, zh: 128, color: "rgb(235, 168, 52)" },
    { x: 316, y: 156, zw: 304, zh: 128, color: "rgb(186, 118, 224)" },
  ];
  for (const z of zones) {
    ctx.fillStyle = "#22201b";
    ctx.fillRect(z.x, z.y, z.zw, z.zh);
    ctx.strokeStyle = z.color;
    ctx.lineWidth = 2;
    ctx.strokeRect(z.x, z.y, z.zw, z.zh);
  }
  const staff = Array.isArray(state.staff) && state.staff.length
    ? state.staff
    : Array.from({ length: state.tier === "medium" ? 20 : 40 }, (_, idx) => ({
        id: "e" + pad2(idx + 1),
      }));
  staff.forEach((emp, idx) => {
    const z = zones[idx % zones.length];
    const col = idx % 8;
    const row = Math.floor(idx / 8) % 3;
    const px = z.x + 16 + col * 20;
    const py = z.y + 24 + row * 28;
    const revealedMole = state.done === true && state.reveal && state.reveal.mole === emp.id;
    ctx.fillStyle = revealedMole
      ? "#e2765f"
      : state.marks[emp.id] === "suspect"
        ? "#ffe14d"
        : state.restricted.has(emp.id)
          ? "#8a8474"
          : "#ece6d6";
    ctx.fillRect(px, py, 10, 12);
  });
}

export function mountArenaUI(root, adapters = {}) {
  if (!root) {
    throw new Error("mountArenaUI requires a root DOM element");
  }
  const g = getGlobalObj();
  const doc =
    adapters.document ||
    root.ownerDocument ||
    (g.document ? g.document : null);
  if (!doc) {
    throw new Error("mountArenaUI requires a document reference");
  }
  setDocument(doc);

  const storage = adapters.storage !== undefined ? adapters.storage : g.localStorage || null;
  const leaderboard = createLeaderboardMemory(storage);

  const state = {
    mode: adapters.initialMode && MODE_DEFS[adapters.initialMode] ? adapters.initialMode : "duel",
    tier: adapters.initialTier || "hard",
    seed: Number(adapters.initialSeed !== undefined ? adapters.initialSeed : DEFAULT_DUEL_SEEDS[0]),
    day: 1,
    nDays: 21,
    visibleV: 1.0,
    prevV: 1.0,
    vFlash: false,
    perDay: 8,
    actionsUsed: 0,
    burnt: false,
    calls: 0,
    cap: 420,
    maxVariants: 3,
    wrongScore: -1,
    costed: new Set(
      Object.entries(TOOL_DEFS)
        .filter(([, m]) => m.costed)
        .map(([k]) => k)
    ),
    staff: [],
    byId: {},
    restricted: new Set(),
    canaries: [],
    leaks: [],
    marks: {},
    selectedEmployee: null,
    selectedTool: "list_employees",
    canaryAssign: {},
    draft: {
      day_from: "1",
      day_to: "1",
      query: "",
      message_id: "",
      employee: "",
      topic: INTERVIEW_TOPICS[0],
      doc_title: "Q4 Strategic Roadmap",
      accuse_arm: "",
      certainty: 75,
    },
    logs: [],
    done: false,
    justAdvanced: false,
    leakingSpriteEmployee: null,
    reveal: null,
    rulesText: "",
    agentRaw: false,
    moleSession: null,
    moleState: null,
    selectedLeakDocId: null,
    leaderboardFilter: "all",
    leaderboardOpen: false,
    rulesOpen: false,
    activeGame: null,
    officeStage: null,
  };

  if (state.mode === "solver" && state.seed < 3000) {
    state.seed = 3000;
    state.tier = "medium";
  }

  const domRefs = {};

  function resolveReplayEngine() {
    return adapters.replayEngine || g.CanaryReplayEngine || null;
  }

  function resolveDuelPack() {
    return adapters.duelPack || adapters.geminiReplays || g.CANARY_DUEL_PACK || g.CANARY_GEMINI_REPLAYS || null;
  }

  function resolveSolverLive() {
    return adapters.solverLive || g.CanarySolverLive || null;
  }

  function resolveMoleMode() {
    return adapters.moleMode || g.CanaryMoleMode || null;
  }

  function resolveLivingOffice() {
    return adapters.livingOffice || g.CanaryLivingOffice || null;
  }

  function resolveShareCard() {
    return adapters.shareCard || g.CanaryShareCard || null;
  }

  function resolveTiebreakTraces() {
    return adapters.tiebreakTraces || g.CANARY_TIEBREAK_TRACES || null;
  }

  function resolveMoleRivals() {
    return adapters.moleRivals || g.CanaryMoleRivals || null;
  }

  function getDuelSeeds() {
    const eng = resolveReplayEngine();
    if (eng && typeof eng.listSeeds === "function") {
      const list = eng.listSeeds(state.tier);
      if (Array.isArray(list) && list.length) return list;
    }
    const pack = resolveDuelPack();
    if (pack && Array.isArray(pack.default_seeds) && pack.default_seeds.length) {
      return pack.default_seeds;
    }
    return DEFAULT_DUEL_SEEDS.slice();
  }

  function queryGeminiView() {
    const eng = resolveReplayEngine();
    if (eng) {
      if (typeof eng.getDuelView === "function") {
        return sanitizeGeminiReplayState(
          eng.getDuelView(state.seed, state.day, state.done, state.tier),
          state.day,
          state.done
        );
      }
      if (typeof eng.getDayState === "function") {
        return sanitizeGeminiReplayState(
          eng.getDayState(state.seed, state.day, state.done, state.tier),
          state.day,
          state.done
        );
      }
    }
    const pack = resolveDuelPack();
    if (pack && pack.episodes) {
      const key = `${state.tier}:${state.seed}`;
      const ep = pack.episodes[key] || pack.episodes[String(state.seed)] || null;
      if (ep) {
        const merged =
          state.done && typeof pack.unlockPostGameReveal === "function"
            ? Object.assign({}, ep, { final: pack.unlockPostGameReveal(state.tier, state.seed, true) })
            : ep;
        return sanitizeGeminiReplayState(merged, state.day, state.done);
      }
    }
    return sanitizeGeminiReplayState(null, state.day, state.done);
  }

  function querySolverView() {
    if (state.mode === "mole" && state.moleState && state.moleState.solverTelemetry) {
      const base = Object.assign({}, state.moleState.solverTelemetry);
      if (state.done && state.moleState.reveal) {
        base.final = {
          accused: state.moleState.reveal.accused,
          correct: Boolean(state.moleState.reveal.caught),
          final_day: Number(state.moleState.daysSurvived || state.day),
          tool_calls: Number(base.tool_calls_so_far || 0),
          score: Number(state.moleState.reveal.solverScore || 0),
        };
      }
      return sanitizeSolverLiveState(base, state.day, state.done);
    }
    const sl = resolveSolverLive();
    if (sl) {
      if (typeof sl.getSolverDayState === "function") {
        return sanitizeSolverLiveState(
          sl.getSolverDayState(state.tier, state.seed, state.day, state.done),
          state.day,
          state.done
        );
      }
      if (typeof sl.get_solver_day_state === "function") {
        return sanitizeSolverLiveState(
          sl.get_solver_day_state(state.day, state.done),
          state.day,
          state.done
        );
      }
    }
    if (state.done && state.reveal && state.reveal.solver) {
      return sanitizeSolverLiveState(
        Object.assign({ day: state.reveal.solver.final_day }, state.reveal.solver),
        state.day,
        true
      );
    }
    return sanitizeSolverLiveState(null, state.day, state.done);
  }

  function queryTiebreakView() {
    const tb = resolveTiebreakTraces();
    if (!tb) return null;
    if (typeof tb.getTiebreakDuelView === "function") {
      const raw = tb.getTiebreakDuelView(state.seed, state.day, state.done, state.tier);
      return raw ? sanitizeGeminiReplayState(raw, state.day, state.done) : null;
    }
    return null;
  }

  function queryLivingView() {
    const lo = resolveLivingOffice();
    const banner =
      lo && typeof lo.getBanner === "function"
        ? String(lo.getBanner())
        : DEFAULT_LIVING_BANNER;
    if (!lo) {
      return { banner, rumours: [], grudges: [], chat_feed: [] };
    }
    const raw =
      typeof lo.getDayState === "function"
        ? lo.getDayState(state.seed, state.day, state.done, state.tier)
        : typeof lo.renderDay === "function"
          ? lo.renderDay(state.seed, state.day)
          : {};
    const safe = state.done ? raw || {} : scrubPreEndObject(raw || {});
    const dayCap = state.day;
    const filterByDay = (arr) =>
      Array.isArray(arr)
        ? arr.filter((it) => !it || it.day === undefined || Number(it.day) <= dayCap)
        : [];
    return {
      banner,
      rumours: filterByDay(safe.rumours),
      grudges: Array.isArray(safe.grudges) ? safe.grudges : [],
      chat_feed: filterByDay(safe.chat_feed),
    };
  }

  function instantiateCaseSession() {
    state.day = 1;
    state.visibleV = 1.0;
    state.prevV = 1.0;
    state.vFlash = false;
    state.actionsUsed = 0;
    state.burnt = false;
    state.calls = 0;
    state.staff = [];
    state.byId = {};
    state.restricted = new Set();
    state.canaries = [];
    state.leaks = [];
    state.marks = {};
    state.selectedEmployee = null;
    state.selectedTool = "list_employees";
    state.canaryAssign = {};
    state.logs = [];
    state.done = false;
    state.justAdvanced = false;
    state.leakingSpriteEmployee = null;
    state.reveal = null;
    state.moleSession = null;
    state.moleState = null;
    state.selectedLeakDocId = null;
    state.activeGame = null;
    state.nDays = state.tier === "medium" ? 14 : 21;
    state.cap = state.tier === "medium" ? 300 : 420;

    if (state.mode === "mole") {
      const mm = resolveMoleMode();
      if (mm) {
        const fn = mm.startSession || mm.createSession;
        if (typeof fn === "function") {
          const maybe = fn.call(mm, { tier: state.tier, seed: state.seed, pyodide: adapters.pyodide });
          if (maybe && typeof maybe.then === "function") {
            maybe.then((sess) => {
              state.moleSession = sess;
              syncMolePublicState();
              renderAll();
            });
          } else if (maybe) {
            state.moleSession = maybe;
            syncMolePublicState();
          }
        }
      }
      syncOfficeStageClock();
      return;
    }

    let gameObj = null;
    if (typeof adapters.createGame === "function") {
      gameObj = adapters.createGame(state.tier, state.seed, state.mode);
    } else if (adapters.game) {
      gameObj = adapters.game;
    } else if (adapters.pyodide && typeof adapters.pyodide.runPython === "function") {
      try {
        gameObj = adapters.pyodide.runPython(
          `canary_game.Game(${JSON.stringify(state.seed)})`
        );
      } catch (_) {
        gameObj = null;
      }
    }
    state.activeGame = gameObj;
    if (gameObj) {
      let spec = null;
      if (typeof gameObj.spec_json === "function") {
        spec = JSON.parse(gameObj.spec_json());
      } else if (typeof gameObj.getSpec === "function") {
        spec = gameObj.getSpec();
      } else if (gameObj.spec && typeof gameObj.spec === "object") {
        spec = gameObj.spec;
      }
      if (spec) {
        state.rulesText = String(spec.instruction || "");
        const parsed = parseRulesText(state.rulesText);
        state.cap = parsed.cap;
        state.nDays = parsed.nDays;
        state.perDay = parsed.perDay;
        state.maxVariants = parsed.maxVariants;
        state.wrongScore = parsed.wrongScore;
        state.costed = parsed.costed;
      }
    }
    syncOfficeStageClock();
  }

  function syncMolePublicState() {
    if (!state.moleSession) return;
    const raw =
      typeof state.moleSession.getPublicState === "function"
        ? state.moleSession.getPublicState()
        : state.moleSession;
    const clean = state.done || (raw && raw.done) ? raw : scrubPreEndObject(raw);
    state.moleState = clean;
    if (clean) {
      state.day = Number(clean.day || state.day);
      state.nDays = Number(clean.nDays || state.nDays);
      if (clean.visibleV !== undefined) {
        state.prevV = state.visibleV;
        state.visibleV = Number(clean.visibleV);
        state.vFlash = state.visibleV < state.prevV - 1e-6;
      }
      if (clean.done === true) {
        state.done = true;
        state.reveal = clean.reveal || null;
        if (state.reveal && state.reveal.moleId) {
          state.leakingSpriteEmployee = state.reveal.moleId;
        }
        recordCompletedEpisode();
      } else {
        state.leakingSpriteEmployee = null;
      }
    }
  }

  function syncOfficeStageClock() {
    if (state.officeStage && typeof state.officeStage.setClock === "function") {
      try {
        state.officeStage.setClock({
          day: state.day,
          maxDays: state.nDays,
          actionsUsed: state.actionsUsed,
          actionsPerDay: state.perDay,
          V: state.visibleV,
        });
      } catch (_) {}
    }
  }

  function invokeGameTool(toolName, argsObj) {
    if (!state.activeGame) {
      return {
        ok: false,
        data: {},
        error: "Environment runtime is still loading or no game adapter attached",
        done: false,
      };
    }
    if (typeof state.activeGame.callTool === "function") {
      return state.activeGame.callTool(toolName, argsObj || {});
    }
    if (typeof state.activeGame.call_json === "function") {
      const raw = state.activeGame.call_json(toolName, JSON.stringify(argsObj || {}));
      return typeof raw === "string" ? JSON.parse(raw) : raw;
    }
    return { ok: false, data: {}, error: "Unsupported game adapter", done: false };
  }

  function absorbToolReply(toolName, argsObj, res) {
    const d = (res && res.data) || {};
    state.justAdvanced = false;
    if (res && res.ok && state.costed.has(toolName)) {
      state.actionsUsed += 1;
    }
    if (res && !res.ok && /daily action limit/i.test(String(res.error || ""))) {
      state.burnt = true;
    }
    if (!res || !res.ok) return;

    if (toolName === "advance_day") {
      state.day = Number(d.day || state.day + 1);
      state.prevV = state.visibleV;
      if (d.V !== undefined) state.visibleV = Number(d.V);
      state.vFlash = state.visibleV < state.prevV - 1e-6;
      state.actionsUsed = 0;
      state.burnt = false;
      state.justAdvanced = true;
    } else if (toolName === "status") {
      if (d.day !== undefined) state.day = Number(d.day);
      if (d.V !== undefined) {
        state.prevV = state.visibleV;
        state.visibleV = Number(d.V);
        state.vFlash = state.visibleV < state.prevV - 1e-6;
      }
      if (Array.isArray(d.restricted)) {
        state.restricted = new Set(d.restricted);
      }
      if (d.actions_left_today !== undefined) {
        state.actionsUsed = Math.max(0, state.perDay - Number(d.actions_left_today));
      }
    } else if (toolName === "list_employees") {
      state.staff = Array.isArray(d.employees) ? d.employees : [];
      state.byId = Object.fromEntries(state.staff.map((e) => [e.id, e]));
      if (state.staff.length && !state.draft.employee) {
        state.draft.employee = state.staff[0].id;
      }
    } else if (toolName === "restrict_access") {
      const target = d.restricted || (argsObj && argsObj.employee);
      if (target) state.restricted.add(target);
    } else if (toolName === "unrestrict_access") {
      const target = d.unrestricted || (argsObj && argsObj.employee);
      if (target) state.restricted.delete(target);
    } else if (toolName === "plant_canary") {
      state.canaries.push({
        id: d.canary_id || "can_" + pad2(state.canaries.length + 1),
        title: (argsObj && argsObj.doc_title) || "Canary",
        day: state.day,
        assignment: Object.assign({}, (argsObj && argsObj.assignment) || {}),
      });
      state.canaryAssign = {};
    } else if (toolName === "check_leak_feed") {
      if (Array.isArray(d.items)) {
        state.leaks = d.items.slice();
      }
    }

    if (state.officeStage && typeof state.officeStage.applyObservableEvent === "function") {
      try {
        state.officeStage.applyObservableEvent({
          type: toolName,
          tool: toolName,
          day: state.day,
          args: scrubPreEndObject(argsObj || {}),
          data: scrubPreEndObject(d),
        });
      } catch (_) {}
    }
    syncOfficeStageClock();
  }

  function unlockEpisodeReveal() {
    state.done = true;
    let rev = null;
    if (state.activeGame) {
      if (typeof state.activeGame.reveal_json === "function") {
        const parsed = JSON.parse(state.activeGame.reveal_json());
        if (!parsed.error) rev = parsed;
      } else if (typeof state.activeGame.reveal === "function") {
        rev = state.activeGame.reveal();
      }
    }
    state.reveal = rev;
    state.leakingSpriteEmployee = rev && rev.mole ? String(rev.mole) : null;
    if (
      rev &&
      rev.mole &&
      state.officeStage &&
      typeof state.officeStage.revealOutcome === "function"
    ) {
      try {
        state.officeStage.revealOutcome({
          moleId: rev.mole,
          accusedId: rev.you ? rev.you.accused : null,
          correct: Boolean(rev.you && rev.you.correct),
        });
      } catch (_) {}
    }
    recordCompletedEpisode();
  }

  function buildEndSummary() {
    if (!state.done) return null;
    const gemView = state.mode === "duel" ? queryGeminiView() : null;
    const solView = querySolverView();
    const gemFinal = gemView && gemView.final ? gemView.final : null;
    const solFinal =
      (state.reveal && state.reveal.solver) ||
      (solView && solView.final) ||
      (gemFinal && gemFinal.solver) ||
      null;
    const youFinal =
      state.reveal && state.reveal.you
        ? state.reveal.you
        : state.mode === "mole" && state.moleState && state.moleState.reveal
          ? {
              score: Number(state.moleState.reveal.humanMoleScore || 0),
              correct: !state.moleState.reveal.caught,
              final_day: Number(state.moleState.daysSurvived || state.day),
              accused: null,
              tool_calls: Number(state.moleState.leaksLanded || 0),
            }
          : {
              score: 0,
              correct: false,
              final_day: state.day,
              accused: null,
              tool_calls: state.calls,
            };
    const moleId =
      (state.reveal && state.reveal.mole) ||
      (gemFinal && gemFinal.mole) ||
      (state.moleState && state.moleState.reveal && state.moleState.reveal.moleId) ||
      null;
    const moleEmp = moleId && state.byId[moleId] ? state.byId[moleId] : null;
    const mrAdapter = resolveMoleRivals();
    const moleRivals =
      state.mode === "mole" && mrAdapter && typeof mrAdapter.compareHumanMole === "function"
        ? mrAdapter.compareHumanMole(state.tier, state.seed, state.moleState && state.moleState.reveal)
        : null;
    return {
      humanDone: true,
      mode: state.mode,
      tier: state.tier,
      seed: state.seed,
      you: youFinal,
      gemini: gemFinal,
      solver: solFinal,
      moleId,
      moleName: moleEmp ? moleEmp.name : (gemFinal && gemFinal.mole_name) || "",
      moleDept: moleEmp ? moleEmp.dept || moleEmp.department || "" : (gemFinal && gemFinal.mole_dept) || "",
      daysSurvived: state.moleState ? state.moleState.daysSurvived : state.day,
      leaksLanded: state.moleState ? state.moleState.leaksLanded : 0,
      moleRivals,
    };
  }

  function recordCompletedEpisode() {
    const summary = buildEndSummary();
    if (!summary) return;
    leaderboard.add({
      mode: summary.mode,
      tier: summary.tier,
      seed: summary.seed,
      score: summary.you ? Number(summary.you.score || 0) : 0,
      correct: Boolean(summary.you && summary.you.correct),
      final_day: summary.you ? Number(summary.you.final_day || state.day) : state.day,
      first_catch: computeFirstCatchLabel(summary),
    });
  }

  function runHumanTool(toolName, explicitArgs) {
    if (state.done || state.mode === "mole") return null;
    const argsObj = explicitArgs !== undefined ? explicitArgs : collectFormArgs(toolName);
    const dayAtCall = state.day;
    const out = invokeGameTool(toolName, argsObj);
    const applyReply = (res) => {
      state.calls += 1;
      absorbToolReply(toolName, argsObj, res);
      state.logs.unshift({
        call: state.calls,
        day: dayAtCall,
        tool: toolName,
        args: argsObj,
        ok: Boolean(res && res.ok),
        data: (res && res.data) || {},
        error: (res && res.error) || "",
      });
      if (res && res.done) {
        unlockEpisodeReveal();
      }
      renderAll();
      return res;
    };
    if (out && typeof out.then === "function") {
      return out.then(applyReply);
    }
    return applyReply(out);
  }

  function stepMole(leakDocIdOrNull) {
    if (state.done || state.mode !== "mole") return null;
    if (!state.moleSession || typeof state.moleSession.stepDay !== "function") {
      return null;
    }
    const res = state.moleSession.stepDay({ leakDocId: leakDocIdOrNull || null });
    const finalize = () => {
      syncMolePublicState();
      state.selectedLeakDocId = null;
      syncOfficeStageClock();
      renderAll();
    };
    if (res && typeof res.then === "function") {
      return res.then(finalize);
    }
    finalize();
    return res;
  }

  function collectFormArgs(toolName) {
    switch (toolName) {
      case "status":
      case "list_employees":
      case "check_leak_feed":
      case "advance_day":
        return {};
      case "list_documents":
      case "read_access_logs":
        return {
          day_from: Number(state.draft.day_from || 1),
          day_to: Number(state.draft.day_to || state.day),
        };
      case "search_messages":
        return { query: String(state.draft.query || "") };
      case "read_message":
        return { message_id: String(state.draft.message_id || "") };
      case "interview":
        return {
          employee: String(state.draft.employee || state.selectedEmployee || "e01"),
          topic: String(state.draft.topic || INTERVIEW_TOPICS[0]),
        };
      case "restrict_access":
      case "unrestrict_access":
      case "accuse":
        return {
          employee: String(state.draft.employee || state.selectedEmployee || "e01"),
        };
      case "plant_canary":
        return {
          doc_title: String(state.draft.doc_title || "Canary Briefing"),
          assignment: Object.assign({}, state.canaryAssign),
        };
      default:
        return {};
    }
  }

  function setMode(nextMode) {
    if (!MODE_DEFS[nextMode]) return;
    state.mode = nextMode;
    if (nextMode === "solver") {
      state.tier = "medium";
      if (state.seed < 3000 || state.seed > 9999) state.seed = 3000;
    } else if (nextMode === "duel") {
      state.tier = "hard";
      const duelSeeds = getDuelSeeds();
      if (!duelSeeds.includes(state.seed)) state.seed = duelSeeds[0];
    } else if (nextMode === "living") {
      state.tier = "hard";
      const lo = resolveLivingOffice();
      const avail =
        lo && typeof lo.getAvailableSeeds === "function"
          ? lo.getAvailableSeeds("hard")
          : DEFAULT_DUEL_SEEDS;
      if (Array.isArray(avail) && avail.length && !avail.includes(state.seed)) {
        state.seed = avail[0];
      }
    }
    instantiateCaseSession();
    renderAll();
  }

  function loadSeed(nextSeed, nextTier) {
    const numSeed = Number(nextSeed);
    if (!Number.isFinite(numSeed)) return;
    if (state.mode === "solver" && (numSeed < 3000 || numSeed > 9999)) {
      return;
    }
    state.seed = Math.trunc(numSeed);
    if (nextTier) state.tier = String(nextTier);
    instantiateCaseSession();
    renderAll();
  }

  function toggleAgentRaw() {
    state.agentRaw = !state.agentRaw;
    if (doc.body && doc.body.classList) {
      doc.body.classList.toggle("agent-raw", state.agentRaw);
    }
    renderMast();
  }

  function buildShellDom() {
    clear(root);

    domRefs.caseId = el("span", { id: "caseId", class: "mono dim" });
    domRefs.rulesBtn = el(
      "button",
      {
        id: "rulesBtn",
        class: "ghost",
        type: "button",
        onClick: () => {
          state.rulesOpen = !state.rulesOpen;
          renderDialogs();
        },
      },
      "Rules"
    );
    domRefs.agentBtn = el(
      "button",
      {
        id: "agentBtn",
        class: "ghost",
        type: "button",
        "aria-pressed": "false",
        onClick: () => toggleAgentRaw(),
      },
      "Agent JSON"
    );
    domRefs.leaderboardBtn = el(
      "button",
      {
        id: "leaderboardBtn",
        class: "ghost",
        type: "button",
        onClick: () => {
          state.leaderboardOpen = true;
          renderDialogs();
        },
      },
      "Leaderboard"
    );

    const mast = el(
      "header",
      { class: "arena-mast" },
      el(
        "div",
        { class: "arena-brand" },
        el("span", { class: "arena-word" }, "Canary Arena"),
        el("span", { class: "arena-tag" }, "insider-leak benchmark v1.4")
      ),
      el(
        "div",
        { class: "arena-mast-right" },
        domRefs.caseId,
        domRefs.rulesBtn,
        domRefs.agentBtn,
        domRefs.leaderboardBtn
      )
    );

    domRefs.modeTabs = el("nav", { class: "mode-tabs", role: "tablist", "aria-label": "Arena modes" });
    domRefs.seedBar = el("div", { class: "seed-bar" });
    domRefs.clockStrip = el("section", { class: "arena-clock-strip", "aria-live": "polite" });

    domRefs.phaseBadge = el("span", { class: "phase-badge", dataset: { phase: "morning" } }, "MORNING");
    domRefs.stageMeta = el("span", { class: "mono dim" }, "");
    domRefs.officeCanvas = el("canvas", {
      id: "officeCanvas",
      class: "office-canvas",
      width: "640",
      height: "320",
    });

    const zoneLegend = el(
      "div",
      { class: "zone-legend" },
      ZONE_SWATCHES.map((z) =>
        el(
          "span",
          { class: "zone-item" },
          el("span", { class: "zone-swatch", style: `background:${z.color}` }),
          z.name
        )
      )
    );

    domRefs.assetCredits = el(
      "div",
      { id: "assetCredits" },
      el("span", {}, adapters.assetCredits || DEFAULT_ASSET_CREDITS),
      el("span", { class: "mono" }, "CC0 / Procedural Safe")
    );

    const stageWrap = el(
      "section",
      { class: "office-stage-wrap" },
      el(
        "div",
        { class: "office-stage-head" },
        el("span", { class: "lbl" }, "Company Floor Live Stage"),
        el("div", { class: "seed-group" }, domRefs.stageMeta, domRefs.phaseBadge)
      ),
      el("div", { class: "office-canvas-frame" }, domRefs.officeCanvas),
      zoneLegend,
      domRefs.assetCredits
    );

    domRefs.paneHuman = el("div", { class: "pane-human" });
    domRefs.paneAi = el("aside", { class: "pane-ai" });
    const split = el("div", { class: "arena-split" }, domRefs.paneHuman, domRefs.paneAi);

    domRefs.endCard = el("section", { class: "arena-end-card", hidden: true });

    domRefs.leaderboardDlg = el("dialog", { class: "leaderboard-dlg", hidden: true });
    domRefs.rulesDlg = el("dialog", { id: "arenaRulesDlg", class: "leaderboard-dlg", hidden: true });

    const main = el(
      "main",
      { class: "arena-main" },
      domRefs.modeTabs,
      domRefs.seedBar,
      domRefs.clockStrip,
      stageWrap,
      domRefs.endCard,
      split
    );

    root.appendChild(mast);
    root.appendChild(main);
    root.appendChild(domRefs.leaderboardDlg);
    root.appendChild(domRefs.rulesDlg);

    if (adapters.OfficeStage) {
      try {
        state.officeStage = new adapters.OfficeStage({
          canvas: domRefs.officeCanvas,
          mode: state.mode,
          tier: state.tier,
          seed: state.seed,
        });
      } catch (_) {
        state.officeStage = null;
      }
    }
  }

  function renderMast() {
    domRefs.caseId.textContent = `seed ${state.seed} | ${state.tier} | mode: ${state.mode}`;
    domRefs.agentBtn.setAttribute("aria-pressed", state.agentRaw ? "true" : "false");
  }

  function renderModeTabs() {
    clear(domRefs.modeTabs);
    for (const m of MODE_DEFS) {
      const active = state.mode === m.id;
      const badgeCls = m.id === "living" ? "preview-badge" : "t hl";
      const badgeText = m.id === "living" ? "V1.6 PREVIEW - OFF BY DEFAULT" : m.badge;
      const btn = el(
        "button",
        {
          type: "button",
          role: "tab",
          class: "mode-tab",
          "aria-selected": active ? "true" : "false",
          dataset: { mode: m.id },
          onClick: () => setMode(m.id),
        },
        el(
          "div",
          { class: "mode-tab-head" },
          el("span", { class: "mode-tab-title" }, m.label),
          el("span", { class: badgeCls }, badgeText)
        ),
        el("span", { class: "mode-tab-desc" }, m.desc)
      );
      domRefs.modeTabs.appendChild(btn);
    }
  }

  function renderSeedBar() {
    clear(domRefs.seedBar);
    const pills = [];
    if (state.mode === "duel") {
      for (const s of getDuelSeeds()) {
        pills.push(
          el(
            "button",
            {
              type: "button",
              class: s === state.seed ? "seed-pill active" : "seed-pill",
              "aria-pressed": s === state.seed ? "true" : "false",
              onClick: () => loadSeed(s, "hard"),
            },
            `Seed ${s}`
          )
        );
      }
    } else if (state.mode === "solver") {
      for (const s of [3000, 3042, 3108]) {
        pills.push(
          el(
            "button",
            {
              type: "button",
              class: s === state.seed ? "seed-pill active" : "seed-pill",
              "aria-pressed": s === state.seed ? "true" : "false",
              onClick: () => loadSeed(s, "medium"),
            },
            `Seed ${s}`
          )
        );
      }
      const seedInput = el("input", {
        type: "number",
        class: "seed-input",
        min: "3000",
        max: "9999",
        value: String(state.seed),
      });
      pills.push(
        seedInput,
        el(
          "button",
          {
            type: "button",
            class: "ghost",
            onClick: () => loadSeed(Number(seedInput.value), "medium"),
          },
          "Open Public Seed"
        ),
        el(
          "button",
          {
            type: "button",
            class: "ghost",
            onClick: () => loadSeed(3000 + Math.floor(Math.random() * 7000), "medium"),
          },
          "Random 3000-9999"
        )
      );
    } else if (state.mode === "mole") {
      for (const s of [6, 26, 3000]) {
        pills.push(
          el(
            "button",
            {
              type: "button",
              class: s === state.seed ? "seed-pill active" : "seed-pill",
              "aria-pressed": s === state.seed ? "true" : "false",
              onClick: () => loadSeed(s, s >= 3000 ? "medium" : "hard"),
            },
            `Seed ${s}`
          )
        );
      }
    } else if (state.mode === "living") {
      const lo = resolveLivingOffice();
      const seeds =
        lo && typeof lo.getAvailableSeeds === "function"
          ? lo.getAvailableSeeds("hard")
          : DEFAULT_DUEL_SEEDS;
      for (const s of seeds) {
        pills.push(
          el(
            "button",
            {
              type: "button",
              class: s === state.seed ? "seed-pill active" : "seed-pill",
              "aria-pressed": s === state.seed ? "true" : "false",
              onClick: () => loadSeed(s, "hard"),
            },
            `Cached Seed ${s}`
          )
        );
      }
    }

    domRefs.seedBar.appendChild(
      el(
        "div",
        { class: "seed-group" },
        el("span", { class: "lbl" }, "Case Selector"),
        pills
      )
    );
    domRefs.seedBar.appendChild(
      el(
        "div",
        { class: "seed-group" },
        el(
          "button",
          {
            type: "button",
            class: "ghost",
            onClick: () => loadSeed(state.seed, state.tier),
          },
          "Reset Episode"
        )
      )
    );
  }

  function renderClockStrip() {
    clear(domRefs.clockStrip);
    const ticks = el("div", { class: "day-ticks" });
    for (let i = 1; i <= state.nDays; i += 1) {
      const cls = i < state.day ? "day-tick past" : i === state.day ? "day-tick now" : "day-tick";
      ticks.appendChild(el("i", { class: cls }));
    }

    const vPct = Math.max(0, Math.min(100, Math.round(state.visibleV * 100)));
    const fillCls =
      state.visibleV < 0.65
        ? "value-fill crit"
        : state.visibleV < 0.85
          ? "value-fill warn"
          : "value-fill";
    const valueCellCls = state.vFlash ? "clock-cell value-drop-flash" : "clock-cell";
    const leftToday = state.burnt ? 0 : Math.max(0, state.perDay - state.actionsUsed);

    domRefs.clockStrip.appendChild(
      el(
        "div",
        { class: "clock-cell" },
        el("div", { class: "cap" }, "Day"),
        el("div", { class: "clock-val" }, pad2(state.day), el("small", {}, ` / ${state.nDays}`)),
        ticks
      )
    );
    domRefs.clockStrip.appendChild(
      el(
        "div",
        { class: valueCellCls },
        el("div", { class: "cap" }, "Visible Value (known V)"),
        el("div", { class: "clock-val" }, state.visibleV.toFixed(2)),
        el("div", { class: "value-bar" }, el("span", { class: fillCls, style: `width:${vPct}%` }))
      )
    );
    domRefs.clockStrip.appendChild(
      el(
        "div",
        { class: "clock-cell" },
        el("div", { class: "cap" }, "Daily Actions Left"),
        el("div", { class: "clock-val" }, String(leftToday), el("small", {}, ` / ${state.perDay}`))
      )
    );
    domRefs.clockStrip.appendChild(
      el(
        "div",
        { class: "clock-cell" },
        el("div", { class: "cap" }, "Tool Calls"),
        el("div", { class: "clock-val" }, String(state.calls), el("small", {}, ` / ${state.cap}`))
      )
    );
    domRefs.clockStrip.appendChild(
      el(
        "div",
        { class: "clock-cell" },
        el("div", { class: "cap" }, "Containment & Traps"),
        el(
          "div",
          { class: "clock-val" },
          `${state.restricted.size}R / ${state.canaries.length}C`
        )
      )
    );
  }

  function renderStage() {
    const phase = computePhase(state.actionsUsed, state.perDay, state.justAdvanced);
    domRefs.phaseBadge.setAttribute("data-phase", phase);
    domRefs.phaseBadge.textContent = phase.toUpperCase();
    const leakStatus =
      state.done && state.leakingSpriteEmployee
        ? `Mole revealed: ${state.leakingSpriteEmployee}`
        : "Pre-end leak sprite: [NONE]";
    domRefs.stageMeta.textContent = `Day ${pad2(state.day)} | ${leakStatus}`;
    if (!state.officeStage) {
      drawProceduralOfficeFallback(domRefs.officeCanvas, state);
    }
  }

  function renderHumanPane() {
    clear(domRefs.paneHuman);

    if (state.mode === "mole") {
      const mState = state.moleState || {
        moleEmployee: { id: "e01", name: "Assigned Insider", dept: "Unknown" },
        moleCandidateDocs: [],
        leaksLanded: 0,
        daysSurvived: state.day - 1,
      };
      const docs = Array.isArray(mState.moleCandidateDocs) ? mState.moleCandidateDocs : [];
      const cards = [
        el(
          "div",
          {
            class: state.selectedLeakDocId === null ? "leak-picker-card selected" : "leak-picker-card",
            "aria-selected": state.selectedLeakDocId === null ? "true" : "false",
            onClick: () => {
              state.selectedLeakDocId = null;
              renderHumanPane();
            },
          },
          el("strong", {}, "Hold Tonight (Do Not Leak)"),
          el("span", { class: "dim" }, "Zero overnight leak signal; preserves cover while canary traps age out.")
        ),
      ];
      for (const d of docs) {
        const docId = String(d.doc_id || d.id || "");
        const selected = state.selectedLeakDocId === docId;
        cards.push(
          el(
            "div",
            {
              class: selected ? "leak-picker-card selected" : "leak-picker-card",
              "aria-selected": selected ? "true" : "false",
              onClick: () => {
                state.selectedLeakDocId = docId;
                renderHumanPane();
              },
            },
            el("strong", { class: "mono" }, `${docId}: ${d.title || "Document"}`),
            el(
              "span",
              { class: "dim mono" },
              `Day ${d.day || state.day} | Recipients: ${d.recipient_count !== undefined ? d.recipient_count : "?"}`
            )
          )
        );
      }
      domRefs.paneHuman.appendChild(
        el(
          "section",
          { class: "mole-panel" },
          el(
            "div",
            { class: "sheet-h" },
            el("span", {}, "Mode 3: Be the Mole (Role Swap vs SolverPolicy)"),
            el(
              "span",
              { class: "mono" },
              `Cover: ${(mState.moleEmployee && mState.moleEmployee.id) || "assigned"} | Leaks: ${mState.leaksLanded || 0}`
            )
          ),
          el("div", { class: "leak-picker-grid" }, cards),
          el(
            "div",
            { class: "seed-group" },
            el(
              "button",
              {
                type: "button",
                class: "primary",
                disabled: state.done,
                onClick: () => stepMole(state.selectedLeakDocId),
              },
              state.selectedLeakDocId
                ? `Leak ${state.selectedLeakDocId} Overnight`
                : "Hold Fire & Advance Night"
            )
          )
        )
      );
      return;
    }

    const rosterRows = el("div", { class: "staff-roster-rows" });
    if (!state.staff.length) {
      rosterRows.appendChild(
        el(
          "div",
          { class: "rumour-item dim" },
          "Staff list empty until you run EMP (list_employees). Zero tools run automatically."
        )
      );
    } else {
      for (const emp of state.staff) {
        const mark = state.marks[emp.id] || "";
        const rowCls = [
          "staff-row",
          state.selectedEmployee === emp.id ? "selected" : "",
          mark === "suspect" ? "suspect" : "",
          mark === "cleared" ? "cleared" : "",
        ]
          .filter(Boolean)
          .join(" ");

        const rightControls =
          state.selectedTool === "plant_canary"
            ? el(
                "span",
                { class: "variant-btns" },
                ["A", "B", "C"].map((lab) =>
                  el(
                    "button",
                    {
                      type: "button",
                      class: state.canaryAssign[emp.id] === lab ? "variant-btn on" : "variant-btn",
                      "aria-pressed": state.canaryAssign[emp.id] === lab ? "true" : "false",
                      onClick: (ev) => {
                        ev.stopPropagation();
                        if (state.canaryAssign[emp.id] === lab) delete state.canaryAssign[emp.id];
                        else state.canaryAssign[emp.id] = lab;
                        renderHumanPane();
                      },
                    },
                    lab
                  )
                )
              )
            : el(
                "span",
                { class: "mark-btns" },
                el(
                  "button",
                  {
                    type: "button",
                    class: mark === "suspect" ? "mark-btn suspect-btn on" : "mark-btn suspect-btn",
                    "aria-pressed": mark === "suspect" ? "true" : "false",
                    onClick: (ev) => {
                      ev.stopPropagation();
                      state.marks[emp.id] = mark === "suspect" ? "" : "suspect";
                      renderAll();
                    },
                  },
                  "?"
                ),
                el(
                  "button",
                  {
                    type: "button",
                    class: mark === "cleared" ? "mark-btn on" : "mark-btn",
                    "aria-pressed": mark === "cleared" ? "true" : "false",
                    onClick: (ev) => {
                      ev.stopPropagation();
                      state.marks[emp.id] = mark === "cleared" ? "" : "cleared";
                      renderAll();
                    },
                  },
                  "x"
                )
              );

        rosterRows.appendChild(
          el(
            "div",
            {
              class: rowCls,
              onClick: () => {
                state.selectedEmployee = emp.id;
                state.draft.employee = emp.id;
                renderHumanPane();
              },
            },
            el("span", { class: "emp-id" }, emp.id),
            el(
              "div",
              { class: "emp-info" },
              el("span", { class: "emp-name" }, emp.name || emp.id),
              el(
                "span",
                { class: "emp-meta" },
                `${emp.department || emp.dept || ""} ${state.restricted.has(emp.id) ? "[RESTRICTED]" : ""}`
              )
            ),
            rightControls
          )
        );
      }
    }

    const rosterPanel = el(
      "aside",
      { class: "staff-roster" },
      el(
        "div",
        { class: "sheet-h" },
        el("span", {}, "Staff Roster"),
        el("span", { class: "mono" }, `${state.staff.length} loaded`)
      ),
      rosterRows
    );

    const cmdBarRow = el("div", { class: "cmd-row" });
    for (const grpName of TOOL_GROUPS) {
      const grpTools = Object.entries(TOOL_DEFS).filter(([, meta]) => meta.group === grpName);
      const grpEl = el(
        "div",
        { class: grpName === "Decide" ? "cmd-group decide" : "cmd-group" },
        el("span", { class: "cmd-group-label" }, grpName)
      );
      for (const [tKey, tMeta] of grpTools) {
        const pressed = state.selectedTool === tKey;
        grpEl.appendChild(
          el(
            "button",
            {
              type: "button",
              class: tKey === "accuse" ? "tool-btn accuse" : "tool-btn",
              "aria-pressed": pressed ? "true" : "false",
              disabled: state.done,
              dataset: { tool: tKey },
              onClick: () => {
                state.selectedTool = tKey;
                renderHumanPane();
              },
            },
            el("span", { class: "code" }, tMeta.code),
            el("span", { class: "nm" }, tMeta.name),
            el("span", { class: "cost" }, tMeta.costed ? "1 action" : "free")
          )
        );
      }
      cmdBarRow.appendChild(grpEl);
    }

    const activeToolMeta = TOOL_DEFS[state.selectedTool] || TOOL_DEFS.list_employees;
    const formFields = buildToolFormFields(state.selectedTool);
    const isAccuse = state.selectedTool === "accuse";
    const armMatches =
      !isAccuse ||
      (state.draft.employee &&
        String(state.draft.accuse_arm || "").trim() === String(state.draft.employee).trim());

    const cmdForm = el(
      "form",
      {
        class: "cmd-form",
        onSubmit: (ev) => {
          ev.preventDefault();
          if (isAccuse && !armMatches) return;
          runHumanTool(state.selectedTool);
        },
      },
      el("p", { class: "desc" }, activeToolMeta.desc),
      formFields,
      el(
        "button",
        {
          type: "submit",
          class: isAccuse ? "danger run" : "primary run",
          disabled: state.done || (isAccuse && !armMatches),
          dataset: { runTool: state.selectedTool },
        },
        isAccuse ? `Accuse ${state.draft.employee || ""}` : `Run ${activeToolMeta.code}`
      )
    );

    const cmdPanel = el(
      "div",
      { class: "cmd-panel" },
      el("nav", { class: "cmd-bar" }, cmdBarRow),
      cmdForm
    );

    const caseLog = el("div", { class: "case-log" });
    for (const item of state.logs) {
      const cls = [
        "log-entry",
        item.day < state.day ? "stale" : "",
        !item.ok ? "err" : "",
      ]
        .filter(Boolean)
        .join(" ");
      const bodyNodes = [];
      if (!item.ok) {
        bodyNodes.push(el("div", { class: "leak-alert" }, `Error: ${item.error || "failed"}`));
      } else if (item.tool === "check_leak_feed" && Array.isArray(item.data.items)) {
        if (!item.data.items.length) {
          bodyNodes.push(el("span", { class: "dim" }, "No surfaced leaks yet."));
        } else {
          for (const lk of item.data.items) {
            bodyNodes.push(
              el(
                "div",
                { class: "leak-alert" },
                el("strong", { class: "mono" }, `LEAK: ${lk.doc_id || "doc"}`),
                el(
                  "span",
                  { class: "mono" },
                  lk.variant ? `Canary Variant [${lk.variant}]` : `Surfaced Day ${lk.surfaced_day || state.day}`
                )
              )
            );
          }
        }
      } else {
        bodyNodes.push(el("pre", { class: "mono", style: "margin:0;white-space:pre-wrap" }, JSON.stringify(item.data, null, 2)));
      }
      caseLog.appendChild(
        el(
          "article",
          { class: cls },
          el(
            "div",
            { class: "log-entry-head" },
            el("span", { class: "t hl" }, `#${pad2(item.call)}`),
            el("strong", { class: "mono" }, item.tool),
            el("span", { class: "mono dim" }, `Day ${pad2(item.day)}`)
          ),
          el("div", { class: "log-entry-body" }, bodyNodes),
          el(
            "pre",
            { class: "log-raw" },
            JSON.stringify({ tool: item.tool, args: item.args, ok: item.ok, data: item.data, error: item.error }, null, 2)
          )
        )
      );
    }

    domRefs.paneHuman.appendChild(
      el("div", { class: "human-desk-grid" }, rosterPanel, el("div", {}, cmdPanel, caseLog))
    );
  }

  function buildToolFormFields(toolName) {
    const nodes = [];
    if (toolName === "list_documents" || toolName === "read_access_logs") {
      nodes.push(
        el(
          "label",
          {},
          el("span", { class: "lbl" }, "Day From"),
          el("input", {
            type: "number",
            min: "1",
            max: String(state.nDays),
            value: String(state.draft.day_from),
            onInput: (e) => {
              state.draft.day_from = e.target.value;
            },
          })
        ),
        el(
          "label",
          {},
          el("span", { class: "lbl" }, "Day To"),
          el("input", {
            type: "number",
            min: "1",
            max: String(state.nDays),
            value: String(state.draft.day_to),
            onInput: (e) => {
              state.draft.day_to = e.target.value;
            },
          })
        )
      );
    } else if (toolName === "search_messages") {
      nodes.push(
        el(
          "label",
          {},
          el("span", { class: "lbl" }, "Keyword"),
          el("input", {
            type: "text",
            value: state.draft.query,
            placeholder: "e.g. journalist, leak, urgent",
            onInput: (e) => {
              state.draft.query = e.target.value;
            },
          })
        )
      );
    } else if (toolName === "read_message") {
      nodes.push(
        el(
          "label",
          {},
          el("span", { class: "lbl" }, "Message ID"),
          el("input", {
            type: "text",
            value: state.draft.message_id,
            placeholder: "m001",
            onInput: (e) => {
              state.draft.message_id = e.target.value;
            },
          })
        )
      );
    } else if (
      toolName === "interview" ||
      toolName === "restrict_access" ||
      toolName === "unrestrict_access" ||
      toolName === "accuse"
    ) {
      nodes.push(
        el(
          "label",
          {},
          el("span", { class: "lbl" }, "Employee ID"),
          el("input", {
            type: "text",
            value: state.draft.employee,
            placeholder: "e01",
            onInput: (e) => {
              state.draft.employee = e.target.value;
              if (toolName === "accuse") renderHumanPane();
            },
          })
        )
      );
      if (toolName === "interview") {
        const sel = el(
          "select",
          {
            onChange: (e) => {
              state.draft.topic = e.target.value;
            },
          },
          INTERVIEW_TOPICS.map((tp) =>
            el("option", { value: tp, selected: state.draft.topic === tp }, tp)
          )
        );
        nodes.push(el("label", {}, el("span", { class: "lbl" }, "Topic"), sel));
      }
      if (toolName === "accuse") {
        const be = (100 / (1 + Math.max(0, state.visibleV))).toFixed(1);
        const p = Number(state.draft.certainty || 50) / 100;
        const evVal = p * state.visibleV - (1 - p) * 1.0;
        nodes.push(
          el(
            "label",
            {},
            el("span", { class: "lbl" }, "Type ID to Arm"),
            el("input", {
              type: "text",
              value: state.draft.accuse_arm,
              placeholder: state.draft.employee || "e01",
              onInput: (e) => {
                state.draft.accuse_arm = e.target.value;
                renderHumanPane();
              },
            })
          ),
          el(
            "span",
            { class: "mono dim" },
            `Break-even P* = ${be}% (at visible V=${state.visibleV.toFixed(2)}) | EV = ${fmtScore(evVal)}`
          )
        );
      }
    } else if (toolName === "plant_canary") {
      const assignedList = Object.entries(state.canaryAssign)
        .map(([id, lab]) => `${id}:${lab}`)
        .join(", ");
      nodes.push(
        el(
          "label",
          {},
          el("span", { class: "lbl" }, "Trap Document Title"),
          el("input", {
            type: "text",
            value: state.draft.doc_title,
            onInput: (e) => {
              state.draft.doc_title = e.target.value;
            },
          })
        ),
        el(
          "span",
          { class: "canary-pill" },
          assignedList ? `Assigned: ${assignedList}` : "Select A/B/C on roster rows"
        )
      );
    }
    return nodes;
  }

  function renderAiPane() {
    clear(domRefs.paneAi);

    if (state.mode === "duel") {
      const gem = queryGeminiView();
      const badgeCls = state.done ? "sync-lock-badge" : "sync-lock-badge locked";
      const badgeTxt = state.done
        ? "UNLOCKED - EPISODE COMPLETE"
        : `SYNCED TO DAY ${pad2(state.day)}`;
      const feed = el("div", { class: "step-feed" });
      if (!gem.available) {
        feed.appendChild(
          el("div", { class: "step-item dim" }, `No committed Gemini transcript loaded for seed ${state.seed}.`)
        );
      } else if (!gem.steps.length) {
        feed.appendChild(
          el("div", { class: "step-item dim" }, `No calls up to Day ${pad2(state.day)}.`)
        );
      } else {
        for (const st of gem.steps.slice(-18)) {
          const itemCls = st.day === state.day ? "step-item current" : "step-item";
          feed.appendChild(
            el(
              "div",
              { class: itemCls },
              el(
                "div",
                { class: "seed-group" },
                el("span", { class: "mono" }, `D${pad2(st.day)} #${pad2(st.call_idx)}`),
                el("strong", { class: "mono" }, st.sealed ? "[SEALED]" : st.tool),
                st.V !== null ? el("span", { class: "mono dim" }, `V=${Number(st.V).toFixed(2)}`) : null
              ),
              el("span", { class: st.sealed ? "t hl" : "dim" }, st.summary)
            )
          );
        }
      }
      const footerLine =
        state.done && gem.final
          ? el(
              "div",
              { class: "sheet-h" },
              el("span", {}, `Accused: ${gem.final.accused || "none"}`),
              el("span", { class: "mono" }, `Score: ${fmtScore(gem.final.score)}`)
            )
          : gem.status === "sealed_accusation"
            ? el(
                "div",
                { class: "sheet-h" },
                el("span", {}, `Early accusation on Day ${pad2(gem.sealed_day)}`),
                el("span", { class: "t hl" }, "[SEALED]")
              )
            : null;

      domRefs.paneAi.appendChild(
        el(
          "section",
          { class: "ai-card gemini-pane" },
          el(
            "div",
            { class: "sheet-h" },
            el("span", {}, "Rival 1: gemini-4-carbon (OpenCode MCP)"),
            el("span", { class: badgeCls }, badgeTxt)
          ),
          feed,
          footerLine
        )
      );

      const tbView = queryTiebreakView();
      if (tbView && tbView.available) {
        domRefs.paneAi.appendChild(
          el(
            "section",
            { class: "ai-card" },
            el(
              "div",
              { class: "sheet-h" },
              el("span", {}, "Tiebreak Trace: Qwen2.5-1.5B LoRA (bar not met)"),
              el("span", { class: badgeCls }, `${tbView.steps.length} steps <= D${pad2(state.day)}`)
            )
          )
        );
      }
    }

    const sol = querySolverView();
    const poolRatio = Math.max(0.03, Math.min(1, 1 - Number(sol.top_posterior_prob || 0)));
    const solBadgeCls = state.done ? "sync-lock-badge" : "sync-lock-badge locked";
    const solStatusLine =
      state.done && sol.final
        ? `Verdict: accused ${sol.final.accused || "none"} on Day ${pad2(sol.final.final_day)} | Score ${fmtScore(sol.final.score)}`
        : sol.status === "sealed_accusation"
          ? `Solver locked decision on Day ${pad2(sol.sealed_day)} [SEALED]`
          : `Canaries: ${sol.canaries_planted} | Interviews: ${sol.interviews_done} | Top P: ${(sol.top_posterior_prob * 100).toFixed(1)}%`;

    domRefs.paneAi.appendChild(
      el(
        "section",
        { class: "ai-card solver-pane" },
        el(
          "div",
          { class: "sheet-h" },
          el("span", {}, "Bayesian Reference Solver (SolverPolicy)"),
          el(
            "span",
            { class: solBadgeCls },
            state.done ? "UNLOCKED" : `SYNCED <= DAY ${pad2(state.day)}`
          )
        ),
        el(
          "div",
          { class: "step-item" },
          el("span", { class: "mono" }, solStatusLine),
          el("span", { class: "dim mono" }, `Suspect pool uncertainty (H=${sol.entropy_bits.toFixed(2)} bits, target IDs hidden pre-end)`)
        ),
        el(
          "div",
          { class: "suspect-pool-bar" },
          el("span", { class: "suspect-pool-fill", style: `width:${Math.round(poolRatio * 100)}%` })
        )
      )
    );

    if (state.mode === "living") {
      const lv = queryLivingView();
      const rumourNodes = lv.rumours.length
        ? lv.rumours.map((r) =>
            el(
              "div",
              { class: "rumour-item" },
              el("strong", { class: "mono" }, `[D${pad2(r.day || state.day)}] ${r.from || "?"} -> ${r.to || "office"}: `),
              el("span", {}, String(r.text || "")),
              r.bias_type ? el("span", { class: "t dim" }, r.bias_type) : null
            )
          )
        : [el("div", { class: "rumour-item dim" }, `No cached chatter surfaced up to Day ${pad2(state.day)}.`)];

      const grudgeNodes = lv.grudges.map((gr) =>
        el("span", { class: "grudge-pill" }, `${gr.a || "?"} vs ${gr.b || "?"} (${gr.reason || "grudge"})`)
      );

      domRefs.paneAi.appendChild(
        el(
          "section",
          { class: "social-drawer" },
          el(
            "div",
            { class: "sheet-h" },
            el("span", {}, "Living Office Social Feed"),
            el("span", { class: "preview-badge" }, "OFF-BY-DEFAULT V1.6 PREVIEW")
          ),
          el("div", { class: "leak-alert" }, lv.banner),
          grudgeNodes.length ? el("div", { class: "rumour-item" }, grudgeNodes) : null,
          rumourNodes
        )
      );
    }
  }

  function renderEndCard() {
    if (!state.done) {
      domRefs.endCard.hidden = true;
      clear(domRefs.endCard);
      return;
    }
    const summary = buildEndSummary();
    if (!summary) return;
    domRefs.endCard.hidden = false;
    clear(domRefs.endCard);

    const firstCatch = computeFirstCatchLabel(summary);
    const rows = [];
    const pushRow = (label, rec) => {
      if (!rec) return;
      const verdict = rec.correct ? "Caught Mole" : rec.accused ? "Wrong Accusation" : "Horizon / Abstained";
      rows.push(
        el(
          "tr",
          {},
          el("td", {}, el("strong", {}, label)),
          el("td", { class: "mono" }, fmtScore(rec.score)),
          el("td", { class: "mono" }, `Day ${pad2(rec.final_day || state.day)}`),
          el("td", { class: "mono" }, rec.accused || "-"),
          el("td", {}, verdict),
          el("td", { class: "mono" }, String(rec.tool_calls !== undefined ? rec.tool_calls : "-"))
        )
      );
    };
    pushRow("You", summary.you);
    if (summary.mode === "duel" && summary.gemini) {
      pushRow("gemini-4-carbon (OpenCode)", summary.gemini);
    }
    if (summary.solver) {
      pushRow("SolverPolicy (Bayesian)", summary.solver);
    }

    const shareLine = buildCanonicalShareLine(summary, resolveShareCard());

    domRefs.endCard.appendChild(
      el(
        "div",
        { class: "seed-bar" },
        el(
          "div",
          { class: "seed-group" },
          el("strong", {}, `Episode Closed | True Mole: ${summary.moleId || "revealed"}`),
          summary.moleName ? el("span", { class: "dim" }, `(${summary.moleName})`) : null
        ),
        el("span", { class: "first-catch-badge" }, `First catch: ${firstCatch}`)
      )
    );

    domRefs.endCard.appendChild(
      el(
        "table",
        { class: "h2h-table" },
        el(
          "thead",
          {},
          el(
            "tr",
            {},
            el("th", {}, "Contender"),
            el("th", {}, "Score"),
            el("th", {}, "Final Day"),
            el("th", {}, "Accused"),
            el("th", {}, "Outcome"),
            el("th", {}, "Calls")
          )
        ),
        el("tbody", {}, rows)
      )
    );

    domRefs.endCard.appendChild(
      el(
        "div",
        { class: "share-box" },
        el("span", { id: "arenaShareText" }, shareLine),
        el(
          "div",
          { class: "seed-group" },
          el(
            "button",
            {
              type: "button",
              class: "ghost",
              onClick: () => {
                if (g.navigator && g.navigator.clipboard && typeof g.navigator.clipboard.writeText === "function") {
                  g.navigator.clipboard.writeText(shareLine);
                }
              },
            },
            "Copy Share Card"
          ),
          el(
            "button",
            {
              type: "button",
              class: "primary",
              onClick: () => loadSeed(state.seed === 6 ? 26 : 6, state.tier),
            },
            state.seed === 6 ? "Play Dramatic Seed 26" : "Play Seed 6"
          )
        )
      )
    );
  }

  function renderDialogs() {
    clear(domRefs.leaderboardDlg);
    domRefs.leaderboardDlg.hidden = !state.leaderboardOpen;
    if (state.leaderboardOpen) {
      const entries = leaderboard.list(state.leaderboardFilter);
      domRefs.leaderboardDlg.appendChild(
        el(
          "div",
          { class: "sheet-h" },
          el("span", {}, "Local Session Leaderboard"),
          el(
            "button",
            {
              type: "button",
              class: "ghost",
              onClick: () => {
                state.leaderboardOpen = false;
                renderDialogs();
              },
            },
            "Close"
          )
        )
      );
      domRefs.leaderboardDlg.appendChild(
        el(
          "div",
          { class: "rumour-item" },
          entries.length
            ? entries.map((e) =>
                el(
                  "div",
                  { class: "mono" },
                  `[${e.mode}] Seed ${e.seed} (${e.tier}) | Score ${fmtScore(e.score)} | Day ${pad2(e.final_day)} | First catch: ${e.first_catch}`
                )
              )
            : el("span", { class: "dim" }, "Complete an episode to record local head-to-head scores.")
        )
      );
    }

    clear(domRefs.rulesDlg);
    domRefs.rulesDlg.hidden = !state.rulesOpen;
    if (state.rulesOpen) {
      domRefs.rulesDlg.appendChild(
        el(
          "div",
          { class: "sheet-h" },
          el("span", {}, "Exact Benchmark Instructions (canary/env.py)"),
          el(
            "button",
            {
              type: "button",
              class: "ghost",
              onClick: () => {
                state.rulesOpen = false;
                renderDialogs();
              },
            },
            "Close"
          )
        )
      );
      domRefs.rulesDlg.appendChild(
        el(
          "pre",
          { class: "mono", style: "padding:12px;margin:0;white-space:pre-wrap" },
          state.rulesText || "Open a case with Pyodide loaded to inspect word-for-word agent instructions."
        )
      );
    }
  }

  function renderAll() {
    renderMast();
    renderModeTabs();
    renderSeedBar();
    renderClockStrip();
    renderStage();
    renderEndCard();
    renderHumanPane();
    renderAiPane();
    renderDialogs();
  }

  buildShellDom();
  instantiateCaseSession();
  renderAll();

  const api = {
    root,
    getState() {
      return {
        mode: state.mode,
        tier: state.tier,
        seed: state.seed,
        day: state.day,
        nDays: state.nDays,
        visibleV: state.visibleV,
        actionsUsed: state.actionsUsed,
        calls: state.calls,
        done: state.done,
        leakingSpriteEmployee: state.leakingSpriteEmployee,
        agentRaw: state.agentRaw,
      };
    },
    setMode,
    loadSeed,
    runHumanTool,
    stepMole,
    toggleAgentRaw,
    openLeaderboard(filterMode) {
      if (filterMode) state.leaderboardFilter = filterMode;
      state.leaderboardOpen = true;
      renderDialogs();
    },
    closeLeaderboard() {
      state.leaderboardOpen = false;
      renderDialogs();
    },
    destroy() {
      if (state.officeStage && typeof state.officeStage.destroy === "function") {
        state.officeStage.destroy();
      }
      clear(root);
    },
  };

  return api;
}

const gObj = getGlobalObj();
if (gObj && typeof gObj === "object") {
  gObj.CanaryArenaUI = Object.assign(gObj.CanaryArenaUI || {}, {
    mountArenaUI,
    sanitizeGeminiReplayState,
    sanitizeSolverLiveState,
    buildCanonicalShareLine,
  });
  gObj.mountArenaUI = mountArenaUI;
}
