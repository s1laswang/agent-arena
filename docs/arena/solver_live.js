const ALLOWED_TIERS = Object.freeze(["easy", "medium", "hard"]);

const PRE_END_KEYS = Object.freeze([
  "seed",
  "tier",
  "day",
  "visible_V",
  "canaries_planted",
  "interviews_done",
  "restricted_count",
  "tool_calls_so_far",
  "top_posterior_prob",
  "entropy_bits",
  "status",
  "sealed_day",
]);

const FORBIDDEN_PRE_END_KEYS = Object.freeze([
  "mole",
  "true_mole",
  "decoy",
  "correct",
  "true_v",
  "is_canary",
  "accused",
  "score",
  "daily_trace",
]);

const SEALED_TARGET = "[SEALED]";
const EMPLOYEE_ID_PATTERN = new RegExp("\\be\\d{2}\\b");

let activePyodide = null;
let activeTier = null;
let activeSeed = null;
const loadedRuntimes = new WeakSet();

function validateTierAndSeed(tier, seed) {
  if (typeof tier !== "string" || !ALLOWED_TIERS.includes(tier)) {
    throw new RangeError("Invalid tier: expected easy, medium, or hard");
  }
  if (typeof seed !== "number" || !Number.isInteger(seed)) {
    throw new RangeError("Invalid seed: expected integer in 0..29 or 3000..9999");
  }
  const inDuel = seed >= 0 && seed <= 29;
  const inPublicDev = seed >= 3000 && seed <= 9999;
  if (!inDuel && !inPublicDev) {
    throw new RangeError("Seed out of allowed arena ranges (0..29 or 3000..9999)");
  }
  return { tier, seed };
}

function validateHumanDay(humanDay) {
  if (typeof humanDay !== "number" || !Number.isInteger(humanDay)) {
    throw new RangeError("Invalid humanDay: expected integer");
  }
  return humanDay;
}

function sanitizeSolverState(rawState, humanDone = false) {
  if (!rawState || typeof rawState !== "object") {
    throw new TypeError("Solver state must be a non-null object");
  }
  const unlocked = humanDone === true;
  if (!unlocked) {
    const clean = {};
    for (const key of PRE_END_KEYS) {
      if (!(key in rawState)) {
        throw new Error("Missing expected pre-end telemetry field: " + key);
      }
      clean[key] = rawState[key];
    }
    if (clean.status !== "hunting" && clean.status !== "sealed_accusation") {
      throw new Error("Invalid pre-end solver status: " + String(clean.status));
    }
    for (const badKey of FORBIDDEN_PRE_END_KEYS) {
      if (badKey in clean) {
        throw new Error("Forbidden pre-end field present: " + badKey);
      }
    }
    const serialized = JSON.stringify(clean);
    if (EMPLOYEE_ID_PATTERN.test(serialized)) {
      throw new Error("Pre-end zero-leak violation: employee identifier detected");
    }
    return clean;
  }
  const revealed = { ...rawState };
  if (Array.isArray(rawState.daily_trace)) {
    revealed.daily_trace = rawState.daily_trace.map((row) => ({
      ...row,
      actions: Array.isArray(row.actions) ? [...row.actions] : [],
    }));
  }
  return revealed;
}

function formatAccusedTarget(state, humanDone = false) {
  if (humanDone !== true) {
    return SEALED_TARGET;
  }
  if (!state || typeof state !== "object") {
    return "NONE";
  }
  return typeof state.accused === "string" && state.accused.length > 0
    ? state.accused
    : "NONE";
}

function normalizeBaseUrl(baseUrl) {
  if (typeof baseUrl !== "string" || baseUrl.length === 0) {
    return "./";
  }
  return baseUrl.endsWith("/") ? baseUrl : baseUrl + "/";
}

function ensureModuleLoadedSync(pyodide) {
  if (!pyodide || typeof pyodide.runPython !== "function") {
    throw new TypeError("A valid Pyodide runtime with runPython() is required");
  }
  if (loadedRuntimes.has(pyodide)) {
    return;
  }
  const ok = pyodide.runPython(
    [
      "import importlib.util, sys",
      "for _p in ('/tmp/canary_arena_py', '/home/pyodide/docs/arena', '/home/pyodide', 'docs/arena', '.'):",
      "    if _p not in sys.path:",
      "        sys.path.insert(0, _p)",
      "bool(importlib.util.find_spec('solver_live'))",
    ].join("\n")
  );
  if (ok) {
    pyodide.runPython("import solver_live");
    loadedRuntimes.add(pyodide);
    return;
  }
  throw new Error("solver_live.py is not loaded in Pyodide; await initSolverLive(pyodide) first");
}

function installPythonSource(pyodide, pythonSource) {
  if (pyodide.FS && typeof pyodide.FS.writeFile === "function") {
    if (typeof pyodide.FS.mkdirTree === "function") {
      pyodide.FS.mkdirTree("/tmp/canary_arena_py");
    }
    pyodide.FS.writeFile("/tmp/canary_arena_py/solver_live.py", pythonSource);
    pyodide.runPython(
      [
        "import importlib, sys",
        "if '/tmp/canary_arena_py' not in sys.path:",
        "    sys.path.insert(0, '/tmp/canary_arena_py')",
        "import solver_live",
        "importlib.reload(solver_live)",
      ].join("\n")
    );
  } else {
    const encoded = JSON.stringify(String(pythonSource));
    pyodide.runPython(
      [
        "import importlib, pathlib, sys",
        "_dir = pathlib.Path('/tmp/canary_arena_py')",
        "_dir.mkdir(parents=True, exist_ok=True)",
        "(_dir / 'solver_live.py').write_text(" + encoded + ", encoding='utf-8')",
        "if str(_dir) not in sys.path:",
        "    sys.path.insert(0, str(_dir))",
        "import solver_live",
        "importlib.reload(solver_live)",
      ].join("\n")
    );
  }
  loadedRuntimes.add(pyodide);
}

async function initSolverLive(pyodide, optionsOrBaseUrl = "./") {
  if (!pyodide || typeof pyodide.runPython !== "function") {
    throw new TypeError("A valid Pyodide runtime with runPython() is required");
  }
  activePyodide = pyodide;
  let baseUrl = "./";
  let pythonSource = null;
  if (typeof optionsOrBaseUrl === "string") {
    baseUrl = optionsOrBaseUrl;
  } else if (optionsOrBaseUrl && typeof optionsOrBaseUrl === "object") {
    if (typeof optionsOrBaseUrl.baseUrl === "string") {
      baseUrl = optionsOrBaseUrl.baseUrl;
    }
    if (typeof optionsOrBaseUrl.pythonSource === "string") {
      pythonSource = optionsOrBaseUrl.pythonSource;
    }
  }

  if (pythonSource !== null) {
    installPythonSource(pyodide, pythonSource);
    return CanarySolverLive;
  }

  try {
    ensureModuleLoadedSync(pyodide);
    return CanarySolverLive;
  } catch (_err) {
    const url = normalizeBaseUrl(baseUrl) + "solver_live.py";
    const resp = await fetch(url);
    if (!resp || !resp.ok) {
      const status = resp ? resp.status : "network_error";
      throw new Error("Failed to fetch " + url + " (" + String(status) + ")");
    }
    const text = await resp.text();
    installPythonSource(pyodide, text);
    return CanarySolverLive;
  }
}

function queryPyodideState(pyodide, tier, seed, humanDay, humanDone) {
  ensureModuleLoadedSync(pyodide);
  const checked = validateTierAndSeed(tier, seed);
  const dayInt = validateHumanDay(humanDay);
  const unlocked = humanDone === true;
  const pyBool = unlocked ? "True" : "False";
  const expr =
    "solver_live.get_solver_day_state_json(" +
    String(dayInt) +
    ", " +
    pyBool +
    ", tier=" +
    JSON.stringify(checked.tier) +
    ", seed=" +
    String(checked.seed) +
    ")";
  const rawJson = pyodide.runPython(expr);
  const parsed = typeof rawJson === "string" ? JSON.parse(rawJson) : rawJson;
  return sanitizeSolverState(parsed, unlocked);
}

function createSession(pyodide, tier, seed) {
  ensureModuleLoadedSync(pyodide);
  const checked = validateTierAndSeed(tier, seed);
  activePyodide = pyodide;
  activeTier = checked.tier;
  activeSeed = checked.seed;
  pyodide.runPython(
    "solver_live.start_solver_session(" +
      JSON.stringify(checked.tier) +
      ", " +
      String(checked.seed) +
      ")"
  );

  function sessionGetState(humanDay, humanDone = false) {
    return queryPyodideState(pyodide, checked.tier, checked.seed, humanDay, humanDone === true);
  }

  function sessionAccusedTarget(humanDay, humanDone = false) {
    const st = sessionGetState(humanDay, humanDone === true);
    return formatAccusedTarget(st, humanDone === true);
  }

  return Object.freeze({
    tier: checked.tier,
    seed: checked.seed,
    getSolverDayState: sessionGetState,
    get_solver_day_state: sessionGetState,
    formatAccusedTarget: sessionAccusedTarget,
  });
}

function getSolverDayState(pyodideOrHumanDay, humanDayOrDone = false, humanDoneOrTier = false, maybeTier = null, maybeSeed = null) {
  if (pyodideOrHumanDay && typeof pyodideOrHumanDay === "object" && typeof pyodideOrHumanDay.runPython === "function") {
    const py = pyodideOrHumanDay;
    const hDay = humanDayOrDone;
    const unlocked = humanDoneOrTier === true;
    const t = maybeTier !== null ? maybeTier : activeTier;
    const s = maybeSeed !== null ? maybeSeed : activeSeed;
    return queryPyodideState(py, t, s, hDay, unlocked);
  }
  if (!activePyodide || activeTier === null || activeSeed === null) {
    throw new Error("No active CanarySolverLive session; call createSession(pyodide, tier, seed) first");
  }
  return queryPyodideState(activePyodide, activeTier, activeSeed, pyodideOrHumanDay, humanDayOrDone === true);
}

const CanarySolverLive = Object.freeze({
  ALLOWED_TIERS,
  PRE_END_KEYS,
  SEALED_TARGET,
  validateTierAndSeed,
  validateHumanDay,
  sanitizeSolverState,
  formatAccusedTarget,
  initSolverLive,
  init_solver_live: initSolverLive,
  createSession,
  create_session: createSession,
  getSolverDayState,
  get_solver_day_state: getSolverDayState,
});

if (typeof window !== "undefined" && window !== null) {
  window.CanarySolverLive = CanarySolverLive;
}

export {
  ALLOWED_TIERS,
  PRE_END_KEYS,
  SEALED_TARGET,
  validateTierAndSeed,
  validateHumanDay,
  sanitizeSolverState,
  formatAccusedTarget,
  initSolverLive,
  createSession,
  getSolverDayState,
  CanarySolverLive,
};

export default CanarySolverLive;
