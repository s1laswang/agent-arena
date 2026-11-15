const COMMITTED_DEV_MIN = 0;
const COMMITTED_DEV_MAX = 59;
const PUBLIC_DEV_MIN = 3000;
const PUBLIC_DEV_MAX = 9999;
const JUDGE_MIN = 900000;
const JUDGE_MAX = 900039;
const HELDOUT_MIN = 800000;
const HELDOUT_MAX = 800199;
const TRAIN_MIN = 100000;
const TRAIN_MAX = 199999;

const ALLOWED_ARENA_MODES = new Set([
  "duel",
  "duel_gemini",
  "solver",
  "beat_solver",
  "mole",
  "be_the_mole",
  "living",
  "living_office",
  "investigator"
]);

const MOLE_MODES = new Set(["mole", "be_the_mole"]);

const BASE_TRUTH_KEYS = new Set([
  "mole",
  "true_mole",
  "mole_id",
  "moleId",
  "is_mole",
  "decoy",
  "true_decoy",
  "decoy_id",
  "correct",
  "accused_correct",
  "true_v",
  "true_V",
  "trueV",
  "world_seed",
  "_world",
  "mole_strategy",
  "mole_sprite",
  "culprit_sprite",
  "leaker_employee",
  "secret",
  "world_secret"
]);

const OPPONENT_STRIP_KEYS = new Set([
  ...BASE_TRUTH_KEYS,
  "accused",
  "score",
  "leaking_sprite_employee"
]);

const OFFICE_STRIP_KEYS = new Set([
  ...BASE_TRUTH_KEYS,
  "accused",
  "score",
  "leaking_sprite_employee"
]);

const MOLE_VIEW_STRIP_KEYS = new Set([
  ...BASE_TRUTH_KEYS,
  "score",
  "leaking_sprite_employee",
  "is_canary",
  "canary_variants",
  "variants",
  "raw_doc_id",
  "raw_title",
  "true_variant",
  "variant_recipients",
  "leaked_canaries",
  "caught_by_canary",
  "posterior",
  "mole_posterior",
  "posteriors",
  "posterior_curve",
  "top_suspect",
  "top_suspects",
  "top_posterior",
  "mole_rank"
]);

const ASSERT_STRICT_KEYS = new Set([
  ...BASE_TRUTH_KEYS,
  "accused",
  "score",
  "canary_variants",
  "posterior",
  "mole_posterior",
  "posteriors",
  "posterior_curve",
  "top_suspect",
  "top_suspects",
  "top_posterior",
  "mole_rank",
  "leaked_canaries",
  "caught_by_canary"
]);

const ACCUSE_REDACT_FIELDS = [
  "summary",
  "result",
  "rationale",
  "thought",
  "reasoning",
  "note",
  "commentary",
  "text",
  "message",
  "detail",
  "error"
];

const DIGITS_RE = new RegExp("^-?\\d+$");
const EMP_GLOBAL_RE = new RegExp("\\be\\d{2,3}\\b", "g");
const EMP_TEST_RE = new RegExp("\\be\\d{2,3}\\b");
const EMP_EXACT_RE = new RegExp("^e\\d{2,3}$");
const CANARY_DOC_RE = new RegExp("^c(?:\\d|an)", "i");
const CANARY_WORD_RE = new RegExp("canary", "i");
const BASE64_RE = new RegExp("^[A-Za-z0-9+/]+={0,2}$");

function isPlainObject(val) {
  return val !== null && typeof val === "object" && !Array.isArray(val);
}

function isFiniteNum(val) {
  return typeof val === "number" && Number.isFinite(val);
}

function deepClone(val) {
  if (val === null || val === undefined || typeof val !== "object") {
    return val;
  }
  if (Array.isArray(val)) {
    return val.map((item) => deepClone(item));
  }
  const out = {};
  const keys = Object.keys(val);
  for (let i = 0; i < keys.length; i += 1) {
    const k = keys[i];
    out[k] = deepClone(val[k]);
  }
  return out;
}

function stripForbiddenRecursive(node, forbiddenSet) {
  if (node === null || node === undefined || typeof node !== "object") {
    return node;
  }
  if (Array.isArray(node)) {
    return node.map((item) => stripForbiddenRecursive(item, forbiddenSet));
  }
  const out = {};
  const keys = Object.keys(node);
  for (let i = 0; i < keys.length; i += 1) {
    const k = keys[i];
    if (forbiddenSet.has(k) || k.toLowerCase().includes("world_secret")) {
      continue;
    }
    out[k] = stripForbiddenRecursive(node[k], forbiddenSet);
  }
  return out;
}

function redactEmployeeIdsDeep(node) {
  if (typeof node === "string") {
    return node.replace(EMP_GLOBAL_RE, "[SEALED]");
  }
  if (Array.isArray(node)) {
    return node.map((item) => redactEmployeeIdsDeep(item));
  }
  if (isPlainObject(node)) {
    const out = {};
    const keys = Object.keys(node);
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      out[k] = redactEmployeeIdsDeep(node[k]);
    }
    return out;
  }
  return node;
}

function computeSensitivity(recipientCount, nStaff) {
  const count = Number(recipientCount) || 0;
  const total = Math.max(1, Number(nStaff) || 20);
  if (count <= 3) {
    return "restricted";
  }
  if (count <= Math.max(1, Math.floor(total / 2))) {
    return "confidential";
  }
  return "internal";
}

function encodeBase64Utf8(str) {
  if (typeof Buffer !== "undefined" && typeof Buffer.from === "function") {
    return Buffer.from(str, "utf8").toString("base64");
  }
  const bytes = new TextEncoder().encode(str);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function decodeBase64Utf8(b64) {
  if (typeof b64 !== "string" || b64.length === 0 || b64.length % 4 !== 0 || !BASE64_RE.test(b64)) {
    throw new Error("Invalid base64 token");
  }
  if (typeof Buffer !== "undefined" && typeof Buffer.from === "function") {
    return Buffer.from(b64, "base64").toString("utf8");
  }
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}

export function checkArenaSeed(mode, seed) {
  let rawMode = mode;
  let rawSeed = seed;
  if (arguments.length === 1) {
    rawMode = "duel";
    rawSeed = mode;
  }

  if (typeof rawMode !== "string" || !ALLOWED_ARENA_MODES.has(rawMode)) {
    throw new Error("Unsupported arena mode: " + String(rawMode));
  }
  if (typeof rawSeed === "boolean" || rawSeed === null || rawSeed === undefined) {
    throw new Error("Seed must be an integer, not boolean or nullish");
  }

  let parsed;
  if (typeof rawSeed === "number") {
    if (!Number.isSafeInteger(rawSeed) || Object.is(rawSeed, -0)) {
      throw new Error("Seed number must be a safe canonical integer");
    }
    parsed = rawSeed;
  } else if (typeof rawSeed === "string") {
    if (rawSeed.length === 0 || rawSeed.trim() !== rawSeed || !DIGITS_RE.test(rawSeed)) {
      throw new Error("Seed string must be unpadded base-10 integer digits");
    }
    parsed = Number(rawSeed);
    if (!Number.isSafeInteger(parsed) || String(parsed) !== rawSeed) {
      throw new Error("Seed string is not a canonical safe integer");
    }
  } else {
    throw new Error("Seed must be an integer");
  }

  if (parsed < 0) {
    throw new Error("Negative seed refused: " + String(parsed));
  }
  if (
    (parsed >= JUDGE_MIN && parsed <= JUDGE_MAX) ||
    (parsed >= HELDOUT_MIN && parsed <= HELDOUT_MAX) ||
    (parsed >= TRAIN_MIN && parsed <= TRAIN_MAX)
  ) {
    throw new Error("Benchmark or training seed refused: " + String(parsed));
  }
  const inCommittedDev = parsed >= COMMITTED_DEV_MIN && parsed <= COMMITTED_DEV_MAX;
  const inPublicDev = parsed >= PUBLIC_DEV_MIN && parsed <= PUBLIC_DEV_MAX;
  if (!inCommittedDev && !inPublicDev) {
    throw new Error("Seed outside allowed arena dev ranges 0..59 and 3000..9999: " + String(parsed));
  }
  return parsed;
}

export function sanitizeOpponentStepForHud(step, humanDay, humanDone) {
  if (!isPlainObject(step)) {
    return null;
  }
  const stepDay = step.day !== undefined && step.day !== null ? Number(step.day) : 1;
  if (!Number.isFinite(stepDay)) {
    return null;
  }
  if (humanDay !== undefined && humanDay !== null) {
    if (typeof humanDay === "boolean" || !Number.isFinite(Number(humanDay))) {
      return null;
    }
    if (stepDay > Number(humanDay)) {
      return null;
    }
  }

  if (humanDone === true) {
    return deepClone(step);
  }

  const cleaned = stripForbiddenRecursive(step, OPPONENT_STRIP_KEYS);
  if (isFiniteNum(cleaned.known_v) && cleaned.V !== undefined) {
    cleaned.V = Number(cleaned.known_v);
  }

  const toolName = String(cleaned.tool || "");
  if (toolName === "accuse") {
    if (isPlainObject(cleaned.args)) {
      const nextArgs = redactEmployeeIdsDeep(cleaned.args);
      nextArgs.employee = "[SEALED]";
      cleaned.args = nextArgs;
    } else {
      cleaned.args = { employee: "[SEALED]" };
    }
    if (isPlainObject(cleaned.arguments)) {
      const nextArguments = redactEmployeeIdsDeep(cleaned.arguments);
      nextArguments.employee = "[SEALED]";
      cleaned.arguments = nextArguments;
    }
    for (let i = 0; i < ACCUSE_REDACT_FIELDS.length; i += 1) {
      const field = ACCUSE_REDACT_FIELDS[i];
      if (cleaned[field] !== undefined) {
        cleaned[field] = redactEmployeeIdsDeep(cleaned[field]);
      }
    }
    cleaned.sealed = true;
  }

  return cleaned;
}

export function sanitizeOpponentSteps(steps, humanDay, humanDone) {
  if (!Array.isArray(steps)) {
    return [];
  }
  if (typeof humanDay === "boolean" || !Number.isFinite(Number(humanDay))) {
    throw new Error("humanDay must be a finite number");
  }
  const limitDay = Number(humanDay);
  const unlocked = humanDone === true;
  const out = [];
  for (let i = 0; i < steps.length; i += 1) {
    const cleaned = sanitizeOpponentStepForHud(steps[i], limitDay, unlocked);
    if (cleaned !== null) {
      out.push(cleaned);
    }
  }
  return out;
}

export function sanitizeOfficeFrame(frame, humanDone) {
  if (!isPlainObject(frame)) {
    return null;
  }
  if (humanDone === true) {
    const unlockedFrame = deepClone(frame);
    if (unlockedFrame.leaking_sprite_employee === undefined && typeof unlockedFrame.mole === "string") {
      unlockedFrame.leaking_sprite_employee = unlockedFrame.mole;
    }
    return unlockedFrame;
  }

  const cleaned = stripForbiddenRecursive(frame, OFFICE_STRIP_KEYS);
  cleaned.leaking_sprite_employee = null;
  cleaned.done = false;
  if (isFiniteNum(cleaned.known_v) && cleaned.V !== undefined) {
    cleaned.V = Number(cleaned.known_v);
  }
  return cleaned;
}

export function sanitizeMoleView(view, humanDone) {
  if (!isPlainObject(view)) {
    return null;
  }
  if (humanDone === true) {
    return deepClone(view);
  }

  const cleaned = stripForbiddenRecursive(view, MOLE_VIEW_STRIP_KEYS);
  const usedIds = new Set();
  const maskMap = new Map();
  let counter = 0;

  function collectNonCanaryIds(node) {
    if (Array.isArray(node)) {
      for (let i = 0; i < node.length; i += 1) {
        collectNonCanaryIds(node[i]);
      }
      return;
    }
    if (isPlainObject(node)) {
      if (typeof node.doc_id === "string" && !CANARY_DOC_RE.test(node.doc_id)) {
        usedIds.add(node.doc_id);
      }
      const vals = Object.values(node);
      for (let i = 0; i < vals.length; i += 1) {
        collectNonCanaryIds(vals[i]);
      }
    }
  }

  collectNonCanaryIds(cleaned);

  function maskDocId(rawId) {
    if (!CANARY_DOC_RE.test(rawId)) {
      return rawId;
    }
    if (maskMap.has(rawId)) {
      return maskMap.get(rawId);
    }
    while (usedIds.has("doc_" + String(counter))) {
      counter += 1;
    }
    const masked = "doc_" + String(counter);
    counter += 1;
    usedIds.add(masked);
    maskMap.set(rawId, masked);
    return masked;
  }

  const currentDay = Number.isFinite(Number(cleaned.day)) ? Number(cleaned.day) : 1;
  const staffCount = Number.isFinite(Number(cleaned.n_staff)) ? Number(cleaned.n_staff) : 20;

  function scrubDocsRecursive(node) {
    if (Array.isArray(node)) {
      return node.map((item) => scrubDocsRecursive(item));
    }
    if (!isPlainObject(node)) {
      return node;
    }
    const out = {};
    const keys = Object.keys(node);
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      const v = node[k];
      if (k === "doc_id" && typeof v === "string") {
        out[k] = maskDocId(v);
      } else if (k === "title" && typeof v === "string" && CANARY_WORD_RE.test(v)) {
        out[k] = "Internal department memo";
      } else {
        out[k] = scrubDocsRecursive(v);
      }
    }
    if (typeof out.doc_id === "string" && (Array.isArray(out.recipients) || out.recipient_count !== undefined)) {
      const rc = Number.isFinite(Number(out.recipient_count))
        ? Number(out.recipient_count)
        : Array.isArray(out.recipients)
          ? out.recipients.length
          : 0;
      out.recipient_count = rc;
      if (out.days_old === undefined) {
        if (Number.isFinite(Number(out.age_days))) {
          out.days_old = Number(out.age_days);
        } else if (Number.isFinite(Number(out.day))) {
          out.days_old = Math.max(0, currentDay - Number(out.day));
        } else {
          out.days_old = 0;
        }
      }
      if (out.sensitivity === undefined) {
        out.sensitivity = computeSensitivity(rc, staffCount);
      }
    }
    return out;
  }

  const scrubbed = scrubDocsRecursive(cleaned);
  scrubbed.done = false;
  if (isFiniteNum(scrubbed.known_v) && scrubbed.V !== undefined) {
    scrubbed.V = Number(scrubbed.known_v);
  }
  return scrubbed;
}

export function sealReveal(obj) {
  const serialized = JSON.stringify(obj === undefined ? null : obj);
  return "sealed:" + encodeBase64Utf8(serialized);
}

export function unsealReveal(tokenOrObj, humanDone) {
  if (humanDone !== true) {
    throw new Error("Reveal payload is sealed until humanDone is strictly true");
  }
  if (typeof tokenOrObj === "string") {
    if (!tokenOrObj.startsWith("sealed:")) {
      throw new Error("Sealed reveal token must start with 'sealed:'");
    }
    const rawB64 = tokenOrObj.slice("sealed:".length);
    const jsonText = decodeBase64Utf8(rawB64);
    return JSON.parse(jsonText);
  }
  if (isPlainObject(tokenOrObj)) {
    if (typeof tokenOrObj.sealed === "string" && tokenOrObj.sealed.startsWith("sealed:") && Object.keys(tokenOrObj).length === 1) {
      return unsealReveal(tokenOrObj.sealed, true);
    }
    return deepClone(tokenOrObj);
  }
  throw new Error("Invalid sealed reveal token or object");
}

export function assertPreEndClean(node, label = "payload") {
  function walk(cur, path, inInvListDocs, inMoleContext) {
    if (cur === null || cur === undefined || typeof cur !== "object") {
      return;
    }
    if (Array.isArray(cur)) {
      for (let i = 0; i < cur.length; i += 1) {
        walk(cur[i], path + "[" + String(i) + "]", inInvListDocs, inMoleContext);
      }
      return;
    }

    const modeStr = typeof cur.mode === "string" ? cur.mode.trim().toLowerCase() : "";
    const nowMole = inMoleContext || MOLE_MODES.has(modeStr);
    const isInvListDocsStep = cur.tool === "list_documents" && !nowMole;

    if (cur.leaking_sprite_employee !== undefined && cur.leaking_sprite_employee !== null) {
      throw new Error(path + ".leaking_sprite_employee leaked pre-end sprite target: " + String(cur.leaking_sprite_employee));
    }

    const keys = Object.keys(cur);
    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      if (ASSERT_STRICT_KEYS.has(k) || k.toLowerCase().includes("world_secret")) {
        throw new Error(path + "." + k + ": forbidden pre-end truth key present");
      }
      if (k === "is_canary" && !inInvListDocs) {
        throw new Error(path + ".is_canary: forbidden pre-end canary flag");
      }
      if (nowMole && k === "doc_id" && typeof cur[k] === "string" && CANARY_DOC_RE.test(cur[k])) {
        throw new Error(path + ".doc_id: unmasked canary doc_id in mole view: " + cur[k]);
      }
    }

    if (isFiniteNum(cur.V) && isFiniteNum(cur.known_v)) {
      if (Math.abs(Number(cur.V) - Number(cur.known_v)) > 1e-9) {
        throw new Error(path + ".V diverges from known_v before episode end");
      }
    }

    if (cur.tool === "accuse") {
      const argsObj = isPlainObject(cur.args) ? cur.args : isPlainObject(cur.arguments) ? cur.arguments : null;
      const empVal = argsObj ? argsObj.employee : cur.args === "[SEALED]" ? "[SEALED]" : undefined;
      if (empVal !== "[SEALED]" || (typeof empVal === "string" && EMP_EXACT_RE.test(empVal))) {
        throw new Error(path + ".args.employee: unsealed opponent accuse target");
      }
      if (argsObj && EMP_TEST_RE.test(JSON.stringify(argsObj))) {
        throw new Error(path + ".args: unredacted employee id in accuse args");
      }
      for (let i = 0; i < ACCUSE_REDACT_FIELDS.length; i += 1) {
        const field = ACCUSE_REDACT_FIELDS[i];
        if (cur[field] !== undefined && EMP_TEST_RE.test(JSON.stringify(cur[field]))) {
          throw new Error(path + "." + field + ": unredacted employee id in accuse step");
        }
      }
    }

    for (let i = 0; i < keys.length; i += 1) {
      const k = keys[i];
      const nextInvDocs =
        inInvListDocs || (isInvListDocsStep && (k === "result" || k === "data" || k === "documents"));
      const nextMoleCtx = nowMole || k === "leakable_docs";
      walk(cur[k], path + "." + k, nextInvDocs, nextMoleCtx);
    }
  }

  walk(node, String(label || "payload"), false, false);
  return true;
}

export const sealPayload = sealReveal;
export const unsealPayload = unsealReveal;

export const CanaryArenaIntegrity = Object.freeze({
  checkArenaSeed,
  sanitizeOpponentSteps,
  sanitizeOpponentStepForHud,
  sanitizeOfficeFrame,
  sanitizeMoleView,
  sealReveal,
  unsealReveal,
  sealPayload,
  unsealPayload,
  assertPreEndClean
});

if (typeof globalThis !== "undefined") {
  globalThis.CanaryArenaIntegrity = CanaryArenaIntegrity;
}
if (typeof window !== "undefined") {
  window.CanaryArenaIntegrity = CanaryArenaIntegrity;
}
