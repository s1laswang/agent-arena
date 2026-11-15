import { el, clear, MODE_DEFS, DEFAULT_DUEL_SEEDS } from "./dom.js";

export const TOUR_TOTAL_SECONDS = 90;

export const TOUR_LIVING_GATE_B_BANNER =
  "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift";

export const TOUR_STEPS = Object.freeze([
  Object.freeze({
    index: 0,
    step: 1,
    id: "duel",
    window: "0:00-0:30",
    startSec: 0,
    endSec: 30,
    durationSec: 30,
    mode: "duel",
    modeLabel: MODE_DEFS.duel ? MODE_DEFS.duel.label : "Duel vs Gemini",
    badge: MODE_DEFS.duel ? MODE_DEFS.duel.badge : "v1.4 hard",
    tier: "hard",
    seed: 26,
    seeds: Object.freeze([26, 6]),
    offByDefault: false,
    title: "Mode 1: Duel vs Gemini (Seeds 26 & 6)",
    action:
      "Start on Seed 26 (or switch to Seed 6), plant a Day 1-2 plant_canary split (A/B/C), run advance_day and check_leak_feed, and verify the synchronized AI pane stays [SEALED] until you accuse.",
    fact:
      "Committed v1.4 hard (n=30, seeds 0-29 post-hoc lock: 65% [24%, 98%] raw, 72% [52%, 91%] luck-adjusted). Seed 6: both gemini-4-carbon (+0.73, 57 calls, 7 canaries) and SolverPolicy (+0.71, 52 calls, 9 canaries) catch the mole on Day 6. Seed 26: SolverPolicy wins on Day 7 (+0.69, 60 calls) while gemini-4-carbon gets fooled on Day 10 (-1.00, 91 calls).",
  }),
  Object.freeze({
    index: 1,
    step: 2,
    id: "solver",
    window: "0:30-0:55",
    startSec: 30,
    endSec: 55,
    durationSec: 25,
    mode: "solver",
    modeLabel: MODE_DEFS.solver ? MODE_DEFS.solver.label : "Beat the Solver",
    badge: MODE_DEFS.solver ? MODE_DEFS.solver.badge : "public seeds",
    tier: "medium",
    seed: 3000,
    seeds: Object.freeze([3000, 3042, 3108]),
    offByDefault: false,
    title: "Mode 2: Beat the Solver (Seed 3000, public seeds 3000-9999)",
    action:
      "Switch to Beat the Solver on public seed 3000 (range 3000-9999), run your canary traps with zero background status polling, and submit accuse to unlock same-seed SolverPolicy comparison.",
    fact:
      "Runs real Python Env and SolverPolicy in Pyodide (0 API keys, 0 live LLM calls). Seeds outside 3000-9999 (judge seeds 900000+, locked dev seeds 0-59, training seeds) are strictly refused; Medium seed 3000 reference solver scores +0.79 on Day 6.",
  }),
  Object.freeze({
    index: 2,
    step: 3,
    id: "mole",
    window: "0:55-1:15",
    startSec: 55,
    endSec: 75,
    durationSec: 20,
    mode: "mole",
    modeLabel: MODE_DEFS.mole ? MODE_DEFS.mole.label : "Be the Mole",
    badge: MODE_DEFS.mole ? MODE_DEFS.mole.badge : "role swap",
    tier: "medium",
    seed: 3000,
    seeds: Object.freeze([3000, 26, 6]),
    offByDefault: false,
    title: "Mode 3: Be the Mole (Insider Role Swap)",
    action:
      "Switch to Be the Mole on public seed 3000 (range 3000-9999), inspect your daily document inbox under MoleView, and decide what to leak or hold back each night.",
    fact:
      "Exact MoleView information boundary: you never see which inbox documents carry hidden plant_canary variant watermarks (A/B/C) while SolverPolicy plants splits, updates its Bayesian posterior, restricts suspects, and tries to accuse before V drains.",
  }),
  Object.freeze({
    index: 3,
    step: 4,
    id: "living",
    window: "1:15-1:30",
    startSec: 75,
    endSec: 90,
    durationSec: 15,
    mode: "living",
    modeLabel: MODE_DEFS.living ? MODE_DEFS.living.label : "Living Office",
    badge: MODE_DEFS.living ? MODE_DEFS.living.badge : "v1.6 preview",
    tier: "hard",
    seed: 26,
    seeds: Object.freeze([26, 6]),
    offByDefault: true,
    title: "Mode 4: Living Office (v1.6 Preview, Off by Default)",
    action:
      "Toggle the opt-in Living Office v1.6 preview drawer to inspect offline-cached multi-day workplace chatter, rumours, authority theories, and grudge threads.",
    fact:
      "Did NOT pass Gate B (off by default): LA 0.452 vs 0.493 control; neither v1.5-candidate (108% vs 61% on hard seeds 0-9) nor v1.6 passed Gate B. Replays offline-cached PublicDayFacts text (LR = 1.0, solver_calibration_diff = 0.0, 0 API calls); frozen v1.4 (SHA-256 a8f99c2537c91d72) is the sole judged environment.",
  }),
]);

const DUEL_SEED_SET = new Set(DEFAULT_DUEL_SEEDS);

function getGlobalObject() {
  return typeof globalThis !== "undefined" ? globalThis : {};
}

function resolveDoc(container, options) {
  if (options && options.document) return options.document;
  if (container && container.ownerDocument) return container.ownerDocument;
  const g = getGlobalObject();
  return g && g.document ? g.document : null;
}

function withDoc(doc, attrs = {}) {
  if (doc) {
    return Object.assign({ document: doc }, attrs);
  }
  return attrs;
}

function ensureClass(node, clsName) {
  if (!node || !clsName) return;
  const raw = typeof node.className === "string" ? node.className : "";
  const parts = raw.split(/\s+/).filter(Boolean);
  if (!parts.includes(clsName)) {
    parts.push(clsName);
    const nextCls = parts.join(" ");
    node.className = nextCls;
    if (typeof node.setAttribute === "function") {
      node.setAttribute("class", nextCls);
    }
  }
}

function clampStepIndex(rawIndex) {
  const n = Number(rawIndex);
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(TOUR_STEPS.length - 1, Math.trunc(n)));
}

function isAllowedSeedForMode(mode, rawSeed) {
  const n = Number(rawSeed);
  if (!Number.isInteger(n)) return false;
  if (mode === "solver") {
    return n >= 3000 && n <= 9999;
  }
  if (mode === "duel" || mode === "living") {
    return DUEL_SEED_SET.has(n);
  }
  if (mode === "mole") {
    return (n >= 3000 && n <= 9999) || DUEL_SEED_SET.has(n);
  }
  return false;
}

function resolveTierForStepSeed(stepDef, seedNum, tierOverride) {
  if (typeof tierOverride === "string" && tierOverride.trim()) {
    return tierOverride.trim();
  }
  if (stepDef.mode === "solver") return "medium";
  if (stepDef.mode === "duel" || stepDef.mode === "living") return "hard";
  return seedNum >= 3000 ? "medium" : "hard";
}

function driveArenaPublicApi(arenaApi, mode, seed, tier) {
  if (!arenaApi || typeof arenaApi !== "object") return;
  if (typeof arenaApi.setMode === "function") {
    arenaApi.setMode(mode);
  }
  if (typeof arenaApi.loadSeed === "function") {
    arenaApi.loadSeed(seed, tier);
  }
}

export function createGuidedTourBar(container, arenaApi, options = {}) {
  const opts = options && typeof options === "object" ? options : {};
  const doc = resolveDoc(container, opts);
  const rootEl =
    container ||
    el("section", withDoc(doc, { class: "guided-tour-bar sheet", role: "region", "aria-label": "90-Second Judge Walkthrough" }));

  ensureClass(rootEl, "guided-tour-bar");
  if (typeof rootEl.setAttribute === "function") {
    if (!rootEl.getAttribute("role")) {
      rootEl.setAttribute("role", "region");
    }
    if (!rootEl.getAttribute("aria-label")) {
      rootEl.setAttribute("aria-label", "90-Second Judge Walkthrough");
    }
  }

  const headerLabel =
    typeof opts.title === "string" && opts.title.trim()
      ? opts.title.trim()
      : "90-Second Judge Walkthrough";

  let stepIndex = clampStepIndex(opts.initialStep !== undefined ? opts.initialStep : 0);
  let active = false;
  let dismissed = Boolean(opts.initiallyDismissed);
  let currentSeed = TOUR_STEPS[stepIndex].seed;
  let currentTier = TOUR_STEPS[stepIndex].tier;
  let destroyed = false;

  function emitChange() {
    if (typeof opts.onStepChange === "function") {
      opts.onStepChange(getState());
    }
  }

  function getState() {
    const stepDef = TOUR_STEPS[stepIndex];
    return {
      active,
      dismissed,
      stepIndex,
      step: stepDef.step,
      totalSteps: TOUR_STEPS.length,
      totalSeconds: TOUR_TOTAL_SECONDS,
      stepId: stepDef.id,
      window: stepDef.window,
      mode: stepDef.mode,
      badge: stepDef.badge,
      tier: currentTier,
      seed: currentSeed,
      offByDefault: stepDef.offByDefault,
      title: stepDef.title,
    };
  }

  function applyStep(nextIndex, stepOpts = {}) {
    if (destroyed) return getState();
    const targetIdx = clampStepIndex(nextIndex);
    const stepDef = TOUR_STEPS[targetIdx];
    const requestedSeed =
      stepOpts && stepOpts.seed !== undefined ? Number(stepOpts.seed) : stepDef.seed;
    const chosenSeed = isAllowedSeedForMode(stepDef.mode, requestedSeed)
      ? requestedSeed
      : stepDef.seed;
    const chosenTier = resolveTierForStepSeed(
      stepDef,
      chosenSeed,
      stepOpts ? stepOpts.tier : undefined
    );

    stepIndex = targetIdx;
    currentSeed = chosenSeed;
    currentTier = chosenTier;
    active = true;
    dismissed = false;

    const shouldSync = !stepOpts || stepOpts.syncArena !== false;
    if (shouldSync) {
      driveArenaPublicApi(arenaApi, stepDef.mode, currentSeed, currentTier);
    }

    render();
    emitChange();
    return getState();
  }

  function selectSeed(nextSeed, tierOverride) {
    if (destroyed) return false;
    const stepDef = TOUR_STEPS[stepIndex];
    const parsed = Number(nextSeed);
    if (!isAllowedSeedForMode(stepDef.mode, parsed)) {
      return false;
    }
    currentSeed = parsed;
    currentTier = resolveTierForStepSeed(stepDef, parsed, tierOverride);
    if (!active) {
      active = true;
      dismissed = false;
      driveArenaPublicApi(arenaApi, stepDef.mode, currentSeed, currentTier);
    } else if (arenaApi && typeof arenaApi.loadSeed === "function") {
      arenaApi.loadSeed(currentSeed, currentTier);
    }
    render();
    emitChange();
    return true;
  }

  function start(startIdx) {
    const idx = startIdx !== undefined ? clampStepIndex(startIdx) : 0;
    return applyStep(idx, { syncArena: true });
  }

  function stop() {
    if (destroyed) return getState();
    active = false;
    render();
    emitChange();
    return getState();
  }

  function dismiss() {
    if (destroyed) return getState();
    active = false;
    dismissed = true;
    render();
    emitChange();
    return getState();
  }

  function open() {
    if (destroyed) return getState();
    dismissed = false;
    render();
    emitChange();
    return getState();
  }

  function next() {
    if (!active) {
      return applyStep(stepIndex, { syncArena: true });
    }
    if (stepIndex >= TOUR_STEPS.length - 1) {
      return getState();
    }
    return applyStep(stepIndex + 1, { syncArena: true });
  }

  function prev() {
    if (!active) {
      return applyStep(stepIndex, { syncArena: true });
    }
    if (stepIndex <= 0) {
      return getState();
    }
    return applyStep(stepIndex - 1, { syncArena: true });
  }

  function buildWindowStepPills() {
    return TOUR_STEPS.map((st, idx) => {
      const isSelected = active && idx === stepIndex;
      const cls = isSelected ? "seed-pill active" : "seed-pill";
      const suffix = st.offByDefault ? " (v1.6 off-by-default)" : "";
      return el(
        "button",
        withDoc(doc, {
          type: "button",
          class: cls,
          "aria-pressed": isSelected ? "true" : "false",
          dataset: {
            tourStep: String(idx),
            tourWindow: st.window,
            tourMode: st.mode,
          },
          onClick: () => applyStep(idx, { syncArena: true }),
        }),
        st.window + " " + st.modeLabel + suffix
      );
    });
  }

  function render() {
    if (destroyed) return rootEl;
    clear(rootEl);

    if (dismissed) {
      rootEl.appendChild(
        el(
          "div",
          withDoc(doc, { class: "seed-bar tour-bar-dismissed" }),
          el(
            "div",
            withDoc(doc, { class: "seed-group" }),
            el("span", withDoc(doc, { class: "lbl" }), headerLabel),
            el("span", withDoc(doc, { class: "mono dim" }), "Optional 4-window click path (0 API calls, [SEALED] pre-end)")
          ),
          el(
            "button",
            withDoc(doc, {
              type: "button",
              class: "ghost",
              dataset: { tourAction: "open" },
              onClick: () => open(),
            }),
            "Show Judge Tour"
          )
        )
      );
      return rootEl;
    }

    if (!active) {
      rootEl.appendChild(
        el(
          "div",
          withDoc(doc, { class: "seed-bar tour-bar-idle" }),
          el(
            "div",
            withDoc(doc, { class: "seed-group" }),
            el("span", withDoc(doc, { class: "lbl" }), headerLabel),
            el("span", withDoc(doc, { class: "t hl" }), "OPTIONAL 90S"),
            buildWindowStepPills()
          ),
          el(
            "div",
            withDoc(doc, { class: "seed-group" }),
            el(
              "button",
              withDoc(doc, {
                type: "button",
                class: "primary",
                dataset: { tourAction: "start" },
                onClick: () => start(0),
              }),
              "Start 90s Tour"
            ),
            el(
              "button",
              withDoc(doc, {
                type: "button",
                class: "ghost",
                dataset: { tourAction: "dismiss" },
                onClick: () => dismiss(),
              }),
              "Dismiss"
            )
          )
        )
      );
      return rootEl;
    }

    const stepDef = TOUR_STEPS[stepIndex];
    const seedButtons = stepDef.seeds.map((s) => {
      const isCurrentSeed = s === currentSeed;
      return el(
        "button",
        withDoc(doc, {
          type: "button",
          class: isCurrentSeed ? "seed-pill active" : "seed-pill",
          "aria-pressed": isCurrentSeed ? "true" : "false",
          dataset: {
            tourSeed: String(s),
            tourTier: resolveTierForStepSeed(stepDef, s),
          },
          onClick: () => selectSeed(s),
        }),
        "Seed " + String(s)
      );
    });

    const headBadges = [
      el("span", withDoc(doc, { class: "t hl" }), stepDef.window),
      el(
        "span",
        withDoc(doc, { class: "mono" }),
        "Step " + String(stepDef.step) + "/" + String(TOUR_STEPS.length)
      ),
      el("strong", withDoc(doc, {}), stepDef.title),
    ];
    if (stepDef.offByDefault) {
      headBadges.push(
        el(
          "span",
          withDoc(doc, { class: "preview-badge" }),
          "OFF-BY-DEFAULT V1.6 PREVIEW"
        )
      );
    } else {
      headBadges.push(
        el("span", withDoc(doc, { class: "sync-lock-badge locked" }), "[SEALED] PRE-END")
      );
    }

    const navControls = el(
      "div",
      withDoc(doc, { class: "seed-group" }),
      el(
        "button",
        withDoc(doc, {
          type: "button",
          class: "ghost",
          disabled: stepIndex <= 0,
          dataset: { tourAction: "prev" },
          onClick: () => prev(),
        }),
        "Prev"
      ),
      el(
        "button",
        withDoc(doc, {
          type: "button",
          class: "ghost",
          disabled: stepIndex >= TOUR_STEPS.length - 1,
          dataset: { tourAction: "next" },
          onClick: () => next(),
        }),
        "Next"
      ),
      el(
        "button",
        withDoc(doc, {
          type: "button",
          class: "ghost",
          dataset: { tourAction: "stop" },
          onClick: () => stop(),
        }),
        "Exit Tour"
      ),
      el(
        "button",
        withDoc(doc, {
          type: "button",
          class: "ghost",
          dataset: { tourAction: "dismiss" },
          onClick: () => dismiss(),
        }),
        "Dismiss"
      )
    );

    const cardChildren = [
      el(
        "div",
        withDoc(doc, { class: "sheet-h" }),
        el("div", withDoc(doc, { class: "seed-group" }), headBadges),
        navControls
      ),
      el(
        "div",
        withDoc(doc, { class: "seed-bar" }),
        el("div", withDoc(doc, { class: "seed-group" }), buildWindowStepPills()),
        el(
          "div",
          withDoc(doc, { class: "seed-group" }),
          el("span", withDoc(doc, { class: "lbl" }), "Step Seeds"),
          seedButtons
        )
      ),
    ];

    if (stepDef.offByDefault) {
      cardChildren.push(
        el("div", withDoc(doc, { class: "leak-alert" }), TOUR_LIVING_GATE_B_BANNER)
      );
    }

    cardChildren.push(
      el(
        "div",
        withDoc(doc, { class: "rumour-item" }),
        el("strong", withDoc(doc, { class: "mono" }), "Click & Observe: "),
        el("span", withDoc(doc, {}), stepDef.action)
      ),
      el(
        "div",
        withDoc(doc, { class: "rumour-item dim" }),
        el("strong", withDoc(doc, { class: "mono" }), "Grounded Benchmark Fact: "),
        el("span", withDoc(doc, {}), stepDef.fact)
      )
    );

    rootEl.appendChild(
      el("div", withDoc(doc, { class: "sheet tour-bar-active" }), cardChildren)
    );
    return rootEl;
  }

  function destroy() {
    destroyed = true;
    active = false;
    clear(rootEl);
  }

  if (opts.autoStart === true) {
    applyStep(stepIndex, { syncArena: true });
  } else {
    render();
  }

  return {
    element: rootEl,
    steps: TOUR_STEPS,
    start,
    stop,
    dismiss,
    open,
    next,
    prev,
    goToStep: applyStep,
    selectSeed,
    render,
    getState,
    destroy,
  };
}

const globalRef = getGlobalObject();
if (globalRef && typeof globalRef === "object") {
  globalRef.CanaryGuidedTour = {
    TOUR_TOTAL_SECONDS,
    TOUR_LIVING_GATE_B_BANNER,
    TOUR_STEPS,
    createGuidedTourBar,
  };
}
