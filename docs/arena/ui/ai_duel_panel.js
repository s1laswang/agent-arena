import { el, clear, pad2, fmtScore } from "./dom.js";

export const MANDATORY_LIVING_BANNER =
  "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift";

const VALID_MODES = new Set(["duel", "solver", "mole", "living"]);

const FORBIDDEN_PRE_END_KEYS = new Set([
  "mole",
  "true_mole",
  "mole_id",
  "moleId",
  "is_mole",
  "decoy",
  "true_decoy",
  "decoy_id",
  "decoyId",
  "is_decoy",
  "decoy_mood",
  "correct",
  "accused_correct",
  "true_v",
  "trueV",
  "true_V",
  "score",
  "is_canary",
  "isCanary",
  "leaking_sprite_employee",
  "world_seed",
  "_world",
  "_feed",
]);

const FORBIDDEN_LIVING_PRE_END_KEYS = new Set([
  "mole",
  "true_mole",
  "mole_id",
  "moleId",
  "is_mole",
  "decoy",
  "true_decoy",
  "decoy_id",
  "decoyId",
  "is_decoy",
  "decoy_mood",
  "correct",
  "accused_correct",
  "true_v",
  "trueV",
  "true_V",
  "is_canary",
  "isCanary",
  "leaking_sprite_employee",
  "world_seed",
  "_world",
  "_feed",
]);

function getGlobalObject() {
  return typeof globalThis !== "undefined" ? globalThis : {};
}

function withDoc(doc, attrs = {}) {
  if (doc) {
    return Object.assign({ document: doc }, attrs);
  }
  return attrs;
}

function ensureClass(node, clsName) {
  if (!node) return;
  const existing = typeof node.className === "string" ? node.className : "";
  const tokens = existing.split(/\s+/).filter(Boolean);
  if (!tokens.includes(clsName)) {
    tokens.push(clsName);
    const joined = tokens.join(" ");
    node.className = joined;
    if (typeof node.setAttribute === "function") {
      node.setAttribute("class", joined);
    }
  }
}

function toPositiveDay(val, fallback = 1) {
  const n = Number(val);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(1, Math.trunc(n));
}

function toFiniteOrNull(val) {
  if (val === null || val === undefined || val === "") return null;
  const n = Number(val);
  return Number.isFinite(n) ? n : null;
}

function toNonNegInt(val, fallback = 0) {
  const n = Number(val);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(0, Math.trunc(n));
}

function scrubObjectKeys(value, forbiddenSet) {
  if (value === null || value === undefined) return value;
  if (Array.isArray(value)) {
    return value.map((item) => scrubObjectKeys(item, forbiddenSet));
  }
  if (typeof value !== "object") return value;
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    if (forbiddenSet.has(k)) continue;
    out[k] = scrubObjectKeys(v, forbiddenSet);
  }
  return out;
}

function extractVisibleStepV(step) {
  if (!step || typeof step !== "object") return null;
  const resultV =
    step.result && typeof step.result === "object" && step.result.data && typeof step.result.data === "object"
      ? step.result.data.V
      : null;
  const candidates = [step.known_v, step.V, step.visible_V, step.visible_v, resultV];
  for (const cand of candidates) {
    const parsed = toFiniteOrNull(cand);
    if (parsed !== null) return parsed;
  }
  return null;
}

function extractStepCallIdx(step) {
  if (step.call_idx !== undefined) return toNonNegInt(step.call_idx, 0);
  if (step.callIdx !== undefined) return toNonNegInt(step.callIdx, 0);
  if (step.t !== undefined && Number.isFinite(Number(step.t))) {
    return Math.max(0, Math.trunc(Number(step.t)) + 1);
  }
  return 0;
}

function extractStepOk(step) {
  if (step.ok !== undefined) return step.ok !== false;
  if (step.result && typeof step.result === "object" && step.result.ok !== undefined) {
    return step.result.ok !== false;
  }
  return true;
}

function sanitizePreEndReplayStep(step) {
  if (!step || typeof step !== "object") return null;
  const day = toPositiveDay(step.day, 1);
  const callIdx = extractStepCallIdx(step);
  const tool = String(step.tool || "");
  const isAccuse =
    tool === "accuse" ||
    step.sealed === true ||
    step.args === "[SEALED]" ||
    Boolean(step.args && typeof step.args === "object" && step.args.employee === "[SEALED]");
  const safeV = extractVisibleStepV(step);
  const stepOk = extractStepOk(step);
  if (isAccuse) {
    return {
      day,
      call_idx: callIdx,
      tool: tool || "accuse",
      args: { employee: "[SEALED]" },
      ok: stepOk,
      summary: "[SEALED]",
      V: safeV,
      sealed: true,
    };
  }
  const rawArgs =
    step.args && typeof step.args === "object" && !Array.isArray(step.args)
      ? scrubObjectKeys(step.args, FORBIDDEN_PRE_END_KEYS)
      : {};
  const cleanStep = {
    day,
    call_idx: callIdx,
    tool,
    args: rawArgs,
    ok: stepOk,
    summary: String(step.summary !== undefined && step.summary !== null ? step.summary : tool),
    V: safeV,
    sealed: false,
  };
  if (typeof step.commentary === "string" && step.commentary.length > 0) {
    cleanStep.commentary = step.commentary;
  }
  return cleanStep;
}

function normalizePostEndStep(step) {
  if (!step || typeof step !== "object") return null;
  const day = toPositiveDay(step.day, 1);
  const callIdx = extractStepCallIdx(step);
  const tool = String(step.tool || "");
  const safeV = extractVisibleStepV(step);
  const stepOk = extractStepOk(step);
  const rawArgs =
    step.args && typeof step.args === "object" && !Array.isArray(step.args)
      ? Object.assign({}, step.args)
      : {};
  const out = {
    day,
    call_idx: callIdx,
    tool,
    args: rawArgs,
    ok: stepOk,
    summary: String(step.summary !== undefined && step.summary !== null ? step.summary : tool),
    V: safeV,
    sealed: false,
  };
  if (typeof step.commentary === "string" && step.commentary.length > 0) {
    out.commentary = step.commentary;
  }
  return out;
}

function normalizeUnlockedFinal(rawFinal, rawView, steps, dayCap) {
  const merged = Object.assign(
    {},
    rawView && typeof rawView === "object" ? rawView : {},
    rawView && rawView.sealed_verdict && typeof rawView.sealed_verdict === "object"
      ? rawView.sealed_verdict
      : {},
    rawFinal && typeof rawFinal === "object" && !rawFinal.sealed ? rawFinal : {}
  );
  if (rawFinal && typeof rawFinal === "object" && rawFinal.sealed) {
    if (merged.final_day === undefined && rawFinal.final_day !== undefined) {
      merged.final_day = rawFinal.final_day;
    }
  }
  const lastStepDay = steps.length
    ? steps.reduce((mx, s) => (s.day > mx ? s.day : mx), 1)
    : dayCap;
  const rawAccused =
    merged.accused !== undefined && merged.accused !== null && merged.accused !== "[SEALED]"
      ? String(merged.accused).trim()
      : "";
  const fDay = toFiniteOrNull(merged.final_day !== undefined ? merged.final_day : merged.day);
  const calls = toFiniteOrNull(merged.tool_calls !== undefined ? merged.tool_calls : merged.calls);
  const sc = toFiniteOrNull(merged.score);
  return {
    accused: rawAccused ? rawAccused : null,
    correct: Boolean(merged.correct),
    final_day: fDay !== null ? Math.max(1, Math.trunc(fDay)) : lastStepDay,
    tool_calls: calls !== null ? Math.max(0, Math.trunc(calls)) : steps.length,
    score: sc !== null ? sc : 0,
  };
}

export function sanitizeGeminiView(rawView, humanDay, humanDone) {
  const dayCap = toPositiveDay(humanDay, 1);
  const done = humanDone === true;
  if (!rawView || typeof rawView !== "object" || rawView.available === false) {
    return {
      available: false,
      seed: rawView && rawView.seed !== undefined ? rawView.seed : null,
      tier: rawView && rawView.tier ? String(rawView.tier) : "hard",
      agent: rawView && rawView.agent ? String(rawView.agent) : "opencode:google/gemini-4-carbon",
      steps: [],
      status: "unavailable",
      sealed_day: null,
      final: null,
    };
  }

  const seed = rawView.seed !== undefined ? rawView.seed : null;
  const tier = rawView.tier ? String(rawView.tier) : "hard";
  const agent = rawView.agent ? String(rawView.agent) : "opencode:google/gemini-4-carbon";
  const rawSteps = Array.isArray(rawView.steps) ? rawView.steps : [];

  if (done) {
    const unlockedSteps = rawSteps.map(normalizePostEndStep).filter(Boolean);
    const hasFinalSource =
      (rawView.final && typeof rawView.final === "object") ||
      (rawView.sealed_verdict && typeof rawView.sealed_verdict === "object") ||
      rawView.accused !== undefined ||
      rawView.score !== undefined;
    return {
      available: true,
      seed,
      tier,
      agent,
      steps: unlockedSteps,
      status: "unlocked",
      sealed_day: null,
      final: hasFinalSource
        ? normalizeUnlockedFinal(rawView.final, rawView, unlockedSteps, dayCap)
        : null,
    };
  }

  const gatedSteps = [];
  let stepSealedDay = null;
  for (const rawStep of rawSteps) {
    if (!rawStep || typeof rawStep !== "object") continue;
    const sDay = toPositiveDay(rawStep.day, 1);
    if (sDay > dayCap) continue;
    const clean = sanitizePreEndReplayStep(rawStep);
    if (!clean) continue;
    if (clean.sealed) {
      if (stepSealedDay === null || clean.day < stepSealedDay) {
        stepSealedDay = clean.day;
      }
    }
    gatedSteps.push(clean);
  }

  let status = "hunting";
  let sealedDay = null;

  if (stepSealedDay !== null) {
    status = "sealed_accusation";
    sealedDay = stepSealedDay;
  }

  const rawFinal = rawView.final && typeof rawView.final === "object" ? rawView.final : null;
  if (rawFinal && rawFinal.sealed === true) {
    const fDay = toFiniteOrNull(rawFinal.final_day);
    if (fDay === null || fDay <= dayCap) {
      status = "sealed_accusation";
      const resolvedDay = fDay !== null ? Math.max(1, Math.trunc(fDay)) : (sealedDay || dayCap);
      sealedDay = sealedDay !== null ? Math.min(sealedDay, resolvedDay) : resolvedDay;
    }
  } else if (rawFinal) {
    const fDay = toFiniteOrNull(rawFinal.final_day);
    if (fDay !== null && fDay <= dayCap && (rawFinal.accused || rawFinal.done)) {
      status = "sealed_accusation";
      const resolvedDay = Math.max(1, Math.trunc(fDay));
      sealedDay = sealedDay !== null ? Math.min(sealedDay, resolvedDay) : resolvedDay;
    }
  } else if (rawView.final_day !== undefined) {
    const topDay = toFiniteOrNull(rawView.final_day);
    if (topDay !== null && topDay <= dayCap && (rawView.accused || rawView.end_reason === "accused")) {
      status = "sealed_accusation";
      const resolvedDay = Math.max(1, Math.trunc(topDay));
      sealedDay = sealedDay !== null ? Math.min(sealedDay, resolvedDay) : resolvedDay;
    }
  }

  if (rawView.status === "sealed_accusation") {
    const explicitSealedDay = toFiniteOrNull(
      rawView.sealed_day !== undefined
        ? rawView.sealed_day
        : rawFinal
          ? rawFinal.final_day
          : null
    );
    if (explicitSealedDay === null || explicitSealedDay <= dayCap) {
      status = "sealed_accusation";
      sealedDay =
        explicitSealedDay !== null
          ? Math.max(1, Math.trunc(explicitSealedDay))
          : sealedDay || dayCap;
    }
  }

  return {
    available: true,
    seed,
    tier,
    agent,
    steps: gatedSteps,
    status,
    sealed_day: status === "sealed_accusation" ? (sealedDay || dayCap) : null,
    final: null,
  };
}

export function sanitizeSolverView(rawView, humanDay, humanDone) {
  const dayCap = toPositiveDay(humanDay, 1);
  const done = humanDone === true;
  if (!rawView || typeof rawView !== "object" || rawView.available === false) {
    return {
      available: false,
      day: dayCap,
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

  const visVCandidates = [rawView.known_v, rawView.visible_V, rawView.visible_v, rawView.V];
  let visibleV = 1.0;
  for (const cand of visVCandidates) {
    const parsed = toFiniteOrNull(cand);
    if (parsed !== null) {
      visibleV = Math.max(0, Math.min(1, parsed));
      break;
    }
  }

  const canariesPlanted = toNonNegInt(
    rawView.canaries_planted !== undefined ? rawView.canaries_planted : rawView.canariesPlanted,
    0
  );
  const interviewsDone = toNonNegInt(
    rawView.interviews_done !== undefined ? rawView.interviews_done : rawView.interviewsDone,
    0
  );
  const restrictedCount = toNonNegInt(
    rawView.restricted_count !== undefined
      ? rawView.restricted_count
      : rawView.restrictedCount !== undefined
        ? rawView.restrictedCount
        : rawView.total_staff_restricted,
    0
  );
  const toolCallsSoFar = toNonNegInt(
    rawView.tool_calls_so_far !== undefined
      ? rawView.tool_calls_so_far
      : rawView.toolCallsSoFar !== undefined
        ? rawView.toolCallsSoFar
        : rawView.tool_calls,
    0
  );
  const rawTopP = toFiniteOrNull(
    rawView.top_posterior_prob !== undefined
      ? rawView.top_posterior_prob
      : rawView.topPosteriorProb !== undefined
        ? rawView.topPosteriorProb
        : rawView.max_posterior
  );
  const topPosteriorProb = rawTopP !== null ? Math.max(0, Math.min(1, rawTopP)) : 0.05;
  const rawEntropy = toFiniteOrNull(
    rawView.entropy_bits !== undefined
      ? rawView.entropy_bits
      : rawView.entropyBits !== undefined
        ? rawView.entropyBits
        : rawView.entropy
  );
  const entropyBits = rawEntropy !== null ? Math.max(0, rawEntropy) : 4.0;

  if (done) {
    const fin = normalizeUnlockedFinal(rawView.final, rawView, [], dayCap);
    if (rawView.tool_calls_so_far !== undefined && rawView.tool_calls === undefined && (!rawView.final || rawView.final.tool_calls === undefined)) {
      fin.tool_calls = toolCallsSoFar;
    }
    return {
      available: true,
      day: toPositiveDay(rawView.day !== undefined ? rawView.day : fin.final_day, dayCap),
      visible_V: visibleV,
      canaries_planted: canariesPlanted,
      interviews_done: interviewsDone,
      restricted_count: restrictedCount,
      tool_calls_so_far: toolCallsSoFar || fin.tool_calls,
      top_posterior_prob: topPosteriorProb,
      entropy_bits: entropyBits,
      status: "unlocked",
      sealed_day: null,
      final: fin,
    };
  }

  const rawFinal = rawView.final && typeof rawView.final === "object" ? rawView.final : null;
  let sealedDay = null;
  let isSealedAccusation = false;

  if (rawView.status === "sealed_accusation") {
    const sDay = toFiniteOrNull(
      rawView.sealed_day !== undefined
        ? rawView.sealed_day
        : rawFinal
          ? rawFinal.final_day
          : rawView.final_day
    );
    if (sDay === null || sDay <= dayCap) {
      isSealedAccusation = true;
      sealedDay = sDay !== null ? Math.max(1, Math.trunc(sDay)) : dayCap;
    }
  } else if (rawFinal && rawFinal.sealed === true) {
    const fDay = toFiniteOrNull(rawFinal.final_day);
    if (fDay === null || fDay <= dayCap) {
      isSealedAccusation = true;
      sealedDay = fDay !== null ? Math.max(1, Math.trunc(fDay)) : dayCap;
    }
  } else {
    const candDay = toFiniteOrNull(
      rawFinal && rawFinal.final_day !== undefined ? rawFinal.final_day : rawView.final_day
    );
    const hasAccused = Boolean((rawFinal && rawFinal.accused) || rawView.accused);
    if (candDay !== null && candDay <= dayCap && hasAccused) {
      isSealedAccusation = true;
      sealedDay = Math.max(1, Math.trunc(candDay));
    }
  }

  const reportedDay = toPositiveDay(rawView.day !== undefined ? rawView.day : dayCap, dayCap);
  return {
    available: true,
    day: Math.min(dayCap, reportedDay),
    visible_V: visibleV,
    canaries_planted: canariesPlanted,
    interviews_done: interviewsDone,
    restricted_count: restrictedCount,
    tool_calls_so_far: toolCallsSoFar,
    top_posterior_prob: topPosteriorProb,
    entropy_bits: entropyBits,
    status: isSealedAccusation ? "sealed_accusation" : "hunting",
    sealed_day: isSealedAccusation ? (sealedDay || dayCap) : null,
    final: null,
  };
}

function sanitizeLivingEntry(item, dayCap, done) {
  if (!item || typeof item !== "object") return null;
  const rawDay =
    item.day !== undefined
      ? item.day
      : item.since_day !== undefined
        ? item.since_day
        : null;
  if (rawDay !== null) {
    const numDay = toFiniteOrNull(rawDay);
    if (numDay !== null && numDay > dayCap) return null;
  }
  if (done) {
    return Object.assign({}, item);
  }
  return scrubObjectKeys(item, FORBIDDEN_LIVING_PRE_END_KEYS);
}

export function sanitizeLivingView(rawView, humanDay, humanDone) {
  const dayCap = toPositiveDay(humanDay, 1);
  const done = humanDone === true;
  if (!rawView || typeof rawView !== "object") {
    return {
      available: false,
      preview_badge: "OFF-BY-DEFAULT V1.6 PREVIEW",
      banner: MANDATORY_LIVING_BANNER,
      rumours: [],
      grudges: [],
      chat_feed: [],
    };
  }

  const rawBanner = typeof rawView.banner === "string" ? rawView.banner.trim() : "";
  const banner = rawBanner.includes(MANDATORY_LIVING_BANNER)
    ? rawBanner
    : MANDATORY_LIVING_BANNER;

  const mapFiltered = (arr) => {
    if (!Array.isArray(arr)) return [];
    const out = [];
    for (const entry of arr) {
      const clean = sanitizeLivingEntry(entry, dayCap, done);
      if (clean) out.push(clean);
    }
    return out;
  };

  return {
    available: rawView.available !== false,
    preview_badge: "OFF-BY-DEFAULT V1.6 PREVIEW",
    banner,
    rumours: mapFiltered(rawView.rumours),
    grudges: mapFiltered(rawView.grudges),
    chat_feed: mapFiltered(rawView.chat_feed),
  };
}

function buildReplayCard(doc, opts) {
  const {
    cardClass,
    title,
    view,
    seed,
    humanDay,
    humanDone,
    emptyLabel,
  } = opts;

  const badgeCls = humanDone ? "sync-lock-badge" : "sync-lock-badge locked";
  const badgeText = humanDone ? "UNLOCKED" : "SYNCED TO DAY " + pad2(humanDay);

  const feed = el("div", withDoc(doc, { class: "step-feed" }));
  if (!view.available) {
    feed.appendChild(
      el(
        "div",
        withDoc(doc, { class: "step-item dim" }),
        emptyLabel || "No transcript loaded for seed " + String(seed !== undefined ? seed : "?") + "."
      )
    );
  } else if (view.steps.length === 0) {
    feed.appendChild(
      el(
        "div",
        withDoc(doc, { class: "step-item dim" }),
        "No tool calls up to Day " + pad2(humanDay) + "."
      )
    );
  } else {
    for (const step of view.steps) {
      const itemCls = step.day === humanDay ? "step-item current" : "step-item";
      const metaNodes = [
        el(
          "span",
          withDoc(doc, { class: "mono" }),
          "D" + pad2(step.day) + " C" + pad2(step.call_idx)
        ),
        el(
          "strong",
          withDoc(doc, { class: "mono" }),
          step.sealed ? "[SEALED]" : step.tool
        ),
      ];
      if (step.V !== null && step.V !== undefined) {
        metaNodes.push(
          el(
            "span",
            withDoc(doc, { class: "mono dim" }),
            "V=" + Number(step.V).toFixed(2)
          )
        );
      }
      if (!step.ok) {
        metaNodes.push(el("span", withDoc(doc, { class: "t red" }), "ERR"));
      }
      const stepChildren = [
        el("div", withDoc(doc, { class: "seed-group" }), metaNodes),
        el(
          "span",
          withDoc(doc, { class: step.sealed ? "t hl" : "dim" }),
          step.sealed ? "[SEALED]" : step.summary
        ),
      ];
      if (step.commentary && !step.sealed) {
        stepChildren.push(
          el("span", withDoc(doc, { class: "mono dim" }), step.commentary)
        );
      }
      feed.appendChild(el("div", withDoc(doc, { class: itemCls }), stepChildren));
    }
  }

  let footer = null;
  if (humanDone && view.final) {
    const verdictLabel = view.final.correct
      ? "Caught mole (correct)"
      : view.final.accused
        ? "Wrong accusation (incorrect)"
        : "Horizon / abstained (incorrect)";
    footer = el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el(
        "span",
        withDoc(doc),
        "Accused: " +
          String(view.final.accused || "none") +
          " | " +
          verdictLabel +
          " | Day " +
          pad2(view.final.final_day)
      ),
      el("span", withDoc(doc, { class: "mono" }), "Score: " + fmtScore(view.final.score))
    );
  } else if (!humanDone && view.status === "sealed_accusation") {
    footer = el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el("span", withDoc(doc), "Accusation filed on Day " + pad2(view.sealed_day)),
      el("span", withDoc(doc, { class: "t hl" }), "[SEALED]")
    );
  }

  return el(
    "section",
    withDoc(doc, { class: cardClass }),
    el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el("span", withDoc(doc), title),
      el("span", withDoc(doc, { class: badgeCls }), badgeText)
    ),
    feed,
    footer
  );
}

function buildSolverCard(doc, sol, humanDay, humanDone) {
  const badgeCls = humanDone ? "sync-lock-badge" : "sync-lock-badge locked";
  const badgeText = humanDone ? "UNLOCKED" : "SYNCED TO DAY " + pad2(humanDay);
  const poolWidthPct = Math.max(
    3,
    Math.min(100, Math.round((1 - Number(sol.top_posterior_prob || 0)) * 100))
  );

  const telemetryText =
    "Visible V: " +
    sol.visible_V.toFixed(2) +
    " | Canaries: " +
    String(sol.canaries_planted) +
    " | Interviews: " +
    String(sol.interviews_done) +
    " | Restricted: " +
    String(sol.restricted_count) +
    " | Calls: " +
    String(sol.tool_calls_so_far);

  const posteriorText =
    "Top posterior: " +
    (sol.top_posterior_prob * 100).toFixed(1) +
    "% | Entropy H=" +
    sol.entropy_bits.toFixed(2) +
    " bits";

  let statusNode = null;
  if (humanDone && sol.final) {
    const verdictWord = sol.final.correct ? "Caught mole (correct)" : "Incorrect";
    statusNode = el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el(
        "span",
        withDoc(doc),
        "Accused: " +
          String(sol.final.accused || "none") +
          " | " +
          verdictWord +
          " | Day " +
          pad2(sol.final.final_day) +
          " | Calls: " +
          String(sol.final.tool_calls)
      ),
      el("span", withDoc(doc, { class: "mono" }), "Score: " + fmtScore(sol.final.score))
    );
  } else if (!humanDone && sol.status === "sealed_accusation") {
    statusNode = el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el("span", withDoc(doc), "Solver decision on Day " + pad2(sol.sealed_day)),
      el("span", withDoc(doc, { class: "t hl" }), "[SEALED]")
    );
  }

  return el(
    "section",
    withDoc(doc, { class: "ai-card solver-pane" }),
    el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el("span", withDoc(doc), "Bayesian Reference Solver (SolverPolicy)"),
      el("span", withDoc(doc, { class: badgeCls }), badgeText)
    ),
    el(
      "div",
      withDoc(doc, { class: "step-item" }),
      el("span", withDoc(doc, { class: "mono" }), telemetryText),
      el("span", withDoc(doc, { class: "dim mono" }), posteriorText)
    ),
    el(
      "div",
      withDoc(doc, { class: "suspect-pool-bar" }),
      el(
        "span",
        withDoc(doc, {
          class: "suspect-pool-fill",
          style: "width:" + String(poolWidthPct) + "%",
        })
      )
    ),
    statusNode
  );
}

function buildLivingSocialDrawer(doc, living, humanDay) {
  const grudgeNodes = living.grudges.map((gr) => {
    const left = String(gr.a_name || gr.a || "staff");
    const right = String(gr.b_name || gr.b || "staff");
    const reason = gr.reason ? " (" + String(gr.reason) + ")" : "";
    return el("span", withDoc(doc, { class: "grudge-pill" }), left + " vs " + right + reason);
  });

  const combinedFeed = [];
  const seenIds = new Set();
  for (const r of living.rumours) {
    const key = r.id ? String(r.id) : null;
    if (key) seenIds.add(key);
    combinedFeed.push(r);
  }
  for (const c of living.chat_feed) {
    const key = c.id ? String(c.id) : null;
    if (key && seenIds.has(key)) continue;
    if (key) seenIds.add(key);
    combinedFeed.push(c);
  }

  const rumourNodes = combinedFeed.length
    ? combinedFeed.map((item) => {
        const dNum = toPositiveDay(item.day !== undefined ? item.day : humanDay, humanDay);
        const speaker = String(item.from_name || item.from || "staff");
        const target = String(item.to_name || item.to || item.channel || "office");
        const body = String(item.text || item.body || item.summary || "");
        return el(
          "div",
          withDoc(doc, { class: "rumour-item" }),
          el(
            "strong",
            withDoc(doc, { class: "mono" }),
            "[D" + pad2(dNum) + "] " + speaker + " -> " + target + ": "
          ),
          el("span", withDoc(doc), body),
          item.bias_type
            ? el("span", withDoc(doc, { class: "t dim" }), String(item.bias_type))
            : null
        );
      })
    : [
        el(
          "div",
          withDoc(doc, { class: "rumour-item dim" }),
          "No cached chatter surfaced up to Day " + pad2(humanDay) + "."
        ),
      ];

  return el(
    "section",
    withDoc(doc, { class: "social-drawer" }),
    el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el("span", withDoc(doc), "Living Office Social Feed"),
      el("span", withDoc(doc, { class: "preview-badge" }), living.preview_badge)
    ),
    el("div", withDoc(doc, { class: "leak-alert" }), living.banner),
    grudgeNodes.length > 0
      ? el("div", withDoc(doc, { class: "rumour-item" }), grudgeNodes)
      : null,
    rumourNodes
  );
}

export function createAiDuelPanel(opts = {}) {
  const g = getGlobalObject();
  const doc =
    opts.document ||
    (opts.container && opts.container.ownerDocument) ||
    (g.document ? g.document : null);

  const rootEl = opts.container || el("aside", withDoc(doc, { class: "pane-ai" }));
  ensureClass(rootEl, "pane-ai");

  let lastSanitized = {
    mode: "duel",
    tier: "hard",
    seed: 6,
    humanDay: 1,
    humanDone: false,
    gemini: null,
    tiebreak: null,
    solver: null,
    living: null,
  };

  function resolveOptionalTiebreak(rawState, seed, humanDay, humanDone, tier) {
    if (rawState && "tiebreakView" in rawState) {
      if (!rawState.tiebreakView) return null;
      const sanitized = sanitizeGeminiView(rawState.tiebreakView, humanDay, humanDone);
      return sanitized.available ? sanitized : null;
    }
    const provider = opts.tiebreakTraces || g.CANARY_TIEBREAK_TRACES || null;
    if (provider && typeof provider.getTiebreakDuelView === "function") {
      const raw = provider.getTiebreakDuelView(seed, humanDay, humanDone, tier);
      if (!raw) return null;
      const sanitized = sanitizeGeminiView(raw, humanDay, humanDone);
      return sanitized.available ? sanitized : null;
    }
    return null;
  }

  function update(nextState = {}) {
    const rawMode = typeof nextState.mode === "string" ? nextState.mode.trim().toLowerCase() : "duel";
    const mode = VALID_MODES.has(rawMode) ? rawMode : "duel";
    const tier = nextState.tier ? String(nextState.tier) : mode === "solver" ? "medium" : "hard";
    const seed = nextState.seed !== undefined ? nextState.seed : 6;
    const humanDay = toPositiveDay(
      nextState.humanDay !== undefined ? nextState.humanDay : nextState.day,
      1
    );
    const humanDone = Boolean(
      nextState.humanDone !== undefined ? nextState.humanDone : nextState.done
    );

    clear(rootEl);

    let geminiClean = null;
    let tiebreakClean = null;
    if (mode === "duel") {
      geminiClean = sanitizeGeminiView(nextState.geminiView, humanDay, humanDone);
      rootEl.appendChild(
        buildReplayCard(doc, {
          cardClass: "ai-card gemini-pane",
          title: "gemini-4-carbon (OpenCode MCP)",
          view: geminiClean,
          seed,
          humanDay,
          humanDone,
          emptyLabel: "No committed Gemini transcript loaded for seed " + String(seed) + ".",
        })
      );

      tiebreakClean = resolveOptionalTiebreak(nextState, seed, humanDay, humanDone, tier);
      if (tiebreakClean) {
        rootEl.appendChild(
          buildReplayCard(doc, {
            cardClass: "ai-card tiebreak-pane",
            title: "Small Model Tiebreak: Qwen2.5-1.5B LoRA (bar not met)",
            view: tiebreakClean,
            seed,
            humanDay,
            humanDone,
            emptyLabel: "No tiebreak trace loaded for seed " + String(seed) + ".",
          })
        );
      }
    }

    const solverClean = sanitizeSolverView(nextState.solverView, humanDay, humanDone);
    rootEl.appendChild(buildSolverCard(doc, solverClean, humanDay, humanDone));

    let livingClean = null;
    if (mode === "living") {
      livingClean = sanitizeLivingView(nextState.livingView, humanDay, humanDone);
      rootEl.appendChild(buildLivingSocialDrawer(doc, livingClean, humanDay));
    }

    lastSanitized = {
      mode,
      tier,
      seed,
      humanDay,
      humanDone,
      gemini: geminiClean,
      tiebreak: tiebreakClean,
      solver: solverClean,
      living: livingClean,
    };

    return rootEl;
  }

  function getState() {
    return Object.assign({}, lastSanitized);
  }

  update(opts.initialState || {});

  return {
    element: rootEl,
    update,
    getState,
  };
}

const globalRef = getGlobalObject();
if (globalRef && typeof globalRef === "object") {
  globalRef.CanaryAiDuelPanel = {
    MANDATORY_LIVING_BANNER,
    sanitizeGeminiView,
    sanitizeSolverView,
    sanitizeLivingView,
    createAiDuelPanel,
  };
}
