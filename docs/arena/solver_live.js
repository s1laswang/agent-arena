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
const MAX_STATE_CACHE_ENTRIES = 256;

let activePyodide = null;
let activeTier = null;
let activeSeed = null;
const loadedRuntimes = new WeakSet();
const runtimeStateCache = new WeakMap();

function deepFreeze(value) {
  if (value === null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    for (let i = 0; i < value.length; i += 1) {
      deepFreeze(value[i]);
    }
  } else {
    const keys = Object.keys(value);
    for (let i = 0; i < keys.length; i += 1) {
      deepFreeze(value[keys[i]]);
    }
  }
  return Object.freeze(value);
}

function cloneDeep(value) {
  if (value === null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => cloneDeep(item));
  }
  const out = {};
  const keys = Object.keys(value);
  for (let i = 0; i < keys.length; i += 1) {
    const k = keys[i];
    out[k] = cloneDeep(value[k]);
  }
  return out;
}

function getRuntimeCacheMap(pyodide) {
  let map = runtimeStateCache.get(pyodide);
  if (!map) {
    map = new Map();
    runtimeStateCache.set(pyodide, map);
  }
  return map;
}

function setBoundedCacheEntry(map, key, value) {
  if (map.has(key)) {
    map.delete(key);
  } else if (map.size >= MAX_STATE_CACHE_ENTRIES) {
    const oldestKey = map.keys().next().value;
    if (oldestKey !== undefined) {
      map.delete(oldestKey);
    }
  }
  map.set(key, value);
}

function validateTierAndSeed(tier, seed) {
  if (typeof tier !== "string" || !ALLOWED_TIERS.includes(tier)) {
    throw new RangeError("Invalid tier: expected easy, medium, or hard");
  }
  if (typeof seed !== "number" || !Number.isInteger(seed)) {
    throw new RangeError("Invalid seed: expected integer in 0..29 or 3000..9999");
  }
  const normalizedSeed = seed === 0 ? 0 : seed;
  const inDuel = normalizedSeed >= 0 && normalizedSeed <= 29;
  const inPublicDev = normalizedSeed >= 3000 && normalizedSeed <= 9999;
  if (!inDuel && !inPublicDev) {
    throw new RangeError("Seed out of allowed arena ranges (0..29 or 3000..9999)");
  }
  return { tier, seed: normalizedSeed };
}

function validateHumanDay(humanDay) {
  if (typeof humanDay !== "number" || !Number.isInteger(humanDay)) {
    throw new RangeError("Invalid humanDay: expected integer");
  }
  return humanDay === 0 ? 0 : humanDay;
}

function sanitizeSolverState(rawState, humanDone = false) {
  if (!rawState || typeof rawState !== "object" || Array.isArray(rawState)) {
    throw new TypeError("Solver state must be a non-null object");
  }
  const unlocked = humanDone === true;
  if (!unlocked) {
    const clean = {};
    for (const key of PRE_END_KEYS) {
      if (!Object.prototype.hasOwnProperty.call(rawState, key)) {
        throw new Error("Missing expected pre-end telemetry field: " + key);
      }
      clean[key] = cloneDeep(rawState[key]);
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
    return deepFreeze(clean);
  }
  const revealed = cloneDeep(rawState);
  if (Array.isArray(rawState.daily_trace)) {
    revealed.daily_trace = rawState.daily_trace.map((row) => ({
      ...cloneDeep(row),
      actions: Array.isArray(row && row.actions) ? cloneDeep(row.actions) : [],
    }));
  }
  return deepFreeze(revealed);
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

function getDefaultSolverScriptUrl() {
  try {
    const href = new URL("./solver_live.py", import.meta.url).href;
    if (typeof href === "string" && href.length > 0) {
      return href;
    }
  } catch (_err) {
    return "./solver_live.py";
  }
  return "./solver_live.py";
}

function appendCacheBust(url, cacheBust) {
  if (cacheBust === null || cacheBust === undefined || cacheBust === false || cacheBust === "") {
    return url;
  }
  const token = cacheBust === true ? String(Date.now()) : encodeURIComponent(String(cacheBust));
  const sep = url.indexOf("?") >= 0 ? "&" : "?";
  return url + sep + "v=" + token;
}

function resolveSolverSourceUrl(baseUrl, cacheBust = null) {
  if (baseUrl === undefined) {
    return appendCacheBust(getDefaultSolverScriptUrl(), cacheBust);
  }
  let raw = "";
  if (typeof baseUrl === "string") {
    raw = baseUrl.trim();
  } else if (typeof URL === "function" && baseUrl instanceof URL) {
    raw = baseUrl.href;
  }
  const hashIdx = raw.indexOf("#");
  const withoutHash = hashIdx >= 0 ? raw.slice(0, hashIdx) : raw;
  const qIdx = withoutHash.indexOf("?");
  let pathPart = qIdx >= 0 ? withoutHash.slice(0, qIdx) : withoutHash;
  const queryPart = qIdx >= 0 ? withoutHash.slice(qIdx + 1) : "";
  const lastSlash = pathPart.lastIndexOf("/");
  const tail = lastSlash >= 0 ? pathPart.slice(lastSlash + 1) : pathPart;

  if (pathPart.length === 0) {
    pathPart = "./solver_live.py";
  } else if (tail === "solver_live.py") {
    pathPart = pathPart;
  } else if (pathPart.endsWith("/")) {
    pathPart = pathPart + "solver_live.py";
  } else if (
    tail.endsWith(".html") ||
    tail.endsWith(".htm") ||
    tail.endsWith(".js") ||
    tail.endsWith(".mjs")
  ) {
    const dir = lastSlash >= 0 ? pathPart.slice(0, lastSlash + 1) : "./";
    pathPart = dir + "solver_live.py";
  } else {
    pathPart = pathPart + "/solver_live.py";
  }

  const assembled = queryPart.length > 0 ? pathPart + "?" + queryPart : pathPart;
  return appendCacheBust(assembled, cacheBust);
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
  runtimeStateCache.delete(pyodide);
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

async function initSolverLive(pyodide, optionsOrBaseUrl) {
  if (!pyodide || typeof pyodide.runPython !== "function") {
    throw new TypeError("A valid Pyodide runtime with runPython() is required");
  }
  activePyodide = pyodide;
  let baseUrl = undefined;
  let pythonSource = null;
  let cacheBust = null;
  let forceReload = false;
  if (typeof optionsOrBaseUrl === "string") {
    baseUrl = optionsOrBaseUrl;
  } else if (typeof URL === "function" && optionsOrBaseUrl instanceof URL) {
    baseUrl = optionsOrBaseUrl.href;
  } else if (optionsOrBaseUrl && typeof optionsOrBaseUrl === "object") {
    if (typeof optionsOrBaseUrl.baseUrl === "string") {
      baseUrl = optionsOrBaseUrl.baseUrl;
    } else if (typeof URL === "function" && optionsOrBaseUrl.baseUrl instanceof URL) {
      baseUrl = optionsOrBaseUrl.baseUrl.href;
    } else if (optionsOrBaseUrl.baseUrl !== undefined) {
      baseUrl = "";
    }
    if (typeof optionsOrBaseUrl.pythonSource === "string") {
      pythonSource = optionsOrBaseUrl.pythonSource;
    }
    if ("cacheBust" in optionsOrBaseUrl) {
      cacheBust = optionsOrBaseUrl.cacheBust;
    }
    if (optionsOrBaseUrl.forceReload === true) {
      forceReload = true;
    }
  } else if (optionsOrBaseUrl !== undefined) {
    baseUrl = "";
  }

  if (pythonSource !== null) {
    installPythonSource(pyodide, pythonSource);
    return CanarySolverLive;
  }

  if (!forceReload) {
    try {
      ensureModuleLoadedSync(pyodide);
      return CanarySolverLive;
    } catch (_err) {
      forceReload = true;
    }
  }

  const url = resolveSolverSourceUrl(baseUrl, cacheBust);
  if (typeof fetch !== "function") {
    throw new Error("Global fetch() is unavailable to load " + url);
  }
  const resp = await fetch(url);
  if (!resp || !resp.ok) {
    const status = resp ? resp.status : "network_error";
    throw new Error("Failed to fetch " + url + " (" + String(status) + ")");
  }
  const text = await resp.text();
  installPythonSource(pyodide, text);
  return CanarySolverLive;
}

function resetSolverCache(pyodide = null) {
  if (pyodide !== null && pyodide !== undefined) {
    if (typeof pyodide !== "object" || typeof pyodide.runPython !== "function") {
      throw new TypeError("A valid Pyodide runtime with runPython() is required");
    }
  }
  const target = pyodide || activePyodide;
  if (!target || target === activePyodide) {
    activeTier = null;
    activeSeed = null;
  }
  if (!target) {
    return true;
  }
  runtimeStateCache.delete(target);
  target.runPython(
    [
      "import sys",
      "_sl = sys.modules.get('solver_live')",
      "if _sl is not None:",
      "    if hasattr(_sl, 'clear_solver_cache'):",
      "        _sl.clear_solver_cache()",
      "    else:",
      "        if hasattr(_sl, '_SESSION_CACHE') and hasattr(_sl._SESSION_CACHE, 'clear'):",
      "            _sl._SESSION_CACHE.clear()",
      "        if hasattr(_sl, '_ACTIVE_SESSION'):",
      "            _sl._ACTIVE_SESSION = None",
    ].join("\n")
  );
  return true;
}

function queryPyodideState(pyodide, tier, seed, humanDay, humanDone) {
  ensureModuleLoadedSync(pyodide);
  const checked = validateTierAndSeed(tier, seed);
  const dayInt = validateHumanDay(humanDay);
  const unlocked = humanDone === true;
  const cacheMap = getRuntimeCacheMap(pyodide);
  const cacheKey =
    checked.tier + ":" + String(checked.seed) + ":" + String(dayInt) + ":" + (unlocked ? "1" : "0");
  if (cacheMap.has(cacheKey)) {
    const hit = cacheMap.get(cacheKey);
    cacheMap.delete(cacheKey);
    cacheMap.set(cacheKey, hit);
    return hit;
  }
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
  let parsed = rawJson;
  if (typeof rawJson === "string") {
    parsed = JSON.parse(rawJson);
  } else if (rawJson && typeof rawJson.toJs === "function") {
    parsed = rawJson.toJs({ dict_converter: Object.fromEntries });
  }
  const frozen = sanitizeSolverState(parsed, unlocked);
  setBoundedCacheEntry(cacheMap, cacheKey, frozen);
  return frozen;
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
  deepFreeze,
  validateTierAndSeed,
  validateHumanDay,
  sanitizeSolverState,
  formatAccusedTarget,
  getDefaultSolverScriptUrl,
  get_default_solver_script_url: getDefaultSolverScriptUrl,
  resolveSolverSourceUrl,
  resolve_solver_source_url: resolveSolverSourceUrl,
  initSolverLive,
  init_solver_live: initSolverLive,
  resetSolverCache,
  reset_solver_cache: resetSolverCache,
  clearSolverCache: resetSolverCache,
  clear_solver_cache: resetSolverCache,
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
  deepFreeze,
  validateTierAndSeed,
  validateHumanDay,
  sanitizeSolverState,
  formatAccusedTarget,
  getDefaultSolverScriptUrl,
  resolveSolverSourceUrl,
  initSolverLive,
  resetSolverCache,
  createSession,
  getSolverDayState,
  CanarySolverLive,
};

export default CanarySolverLive;
