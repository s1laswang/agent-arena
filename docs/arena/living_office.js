import { el, clear, pad2, setDocument } from "./ui/dom.js";

export const DEFAULT_LIVING_OFFICE_BANNER =
  "OFF-BY-DEFAULT v1.6 PREVIEW: Did NOT pass Gate B gap gate (LA 0.452 vs 0.493 control); 100% offline cached gemini-4-carbon chatter, 0 score drift; v1.5 biased employees moved gemini-4-carbon 61% -> 108% of SolverPolicy on hard seeds 0-9.";

export const LIVING_OFFICE_RULES_NOTE =
  "Fairness disclosure: Mode 4 Living Office is an off-by-default v1.6 preview. Default judged Canary v1.4 uses template text; every cached gemini-4-carbon rumour, grudge, and workplace chat message is generated strictly from public roles, departments, and regular document recipient lists with zero hidden truth access and zero score drift.";

const MAX_PUBLIC_SEED = 9999;

export const FORBIDDEN_PRE_END_KEYS = new Set([
  "mole",
  "true_mole",
  "mole_id",
  "moleId",
  "mole_name",
  "is_mole",
  "decoy",
  "true_decoy",
  "decoy_id",
  "decoyId",
  "decoy_name",
  "is_decoy",
  "decoy_mood",
  "correct",
  "accused_correct",
  "solver_accused",
  "solver_correct",
  "world_seed",
  "is_canary",
  "true_v",
  "true_V",
  "trueV",
  "true_v_day21",
  "primary_focus_is_mole",
  "secondary_focus_is_mole",
  "leaking_sprite_employee",
  "mole_sprite",
  "culprit_sprite",
  "leaker_employee",
  "_world",
  "_feed",
  "sealed_reveal",
  "post_end_reveal",
]);

function getGlobalRoot() {
  return typeof globalThis !== "undefined" ? globalThis : {};
}

function isPlainObject(val) {
  return Boolean(val) && typeof val === "object" && !Array.isArray(val);
}

function isAllowedPublicSeed(seedVal) {
  const num = Number(seedVal);
  return Number.isInteger(num) && num >= 0 && num <= MAX_PUBLIC_SEED;
}

export function scrubLivingOfficePreEnd(input) {
  if (input === null || input === undefined) {
    return input;
  }
  if (Array.isArray(input)) {
    return input.map((item) => scrubLivingOfficePreEnd(item));
  }
  if (typeof input !== "object") {
    return input;
  }
  const clean = {};
  for (const [key, val] of Object.entries(input)) {
    if (FORBIDDEN_PRE_END_KEYS.has(key)) {
      continue;
    }
    clean[key] = scrubLivingOfficePreEnd(val);
  }
  return clean;
}

function cloneJsonSafe(input) {
  if (input === null || input === undefined) {
    return input;
  }
  if (Array.isArray(input)) {
    return input.map((item) => cloneJsonSafe(item));
  }
  if (typeof input !== "object") {
    return input;
  }
  const copy = {};
  for (const [k, v] of Object.entries(input)) {
    copy[k] = cloneJsonSafe(v);
  }
  return copy;
}

function sanitizeEmployeeRow(emp) {
  if (!isPlainObject(emp)) {
    return null;
  }
  const id = String(emp.id || "").trim();
  if (!id) {
    return null;
  }
  const out = {
    id,
    name: String(emp.name || id),
    dept: String(emp.dept || emp.department || "Engineering"),
    role: String(emp.role || "staff"),
  };
  if (emp.clearance !== undefined && Number.isFinite(Number(emp.clearance))) {
    out.clearance = Number(emp.clearance);
  }
  return out;
}

function normalizeRumourItem(raw, fallbackDay) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const scrubbed = scrubLivingOfficePreEnd(raw);
  const day = Math.max(1, Math.trunc(Number(scrubbed.day) || fallbackDay || 1));
  const from = String(scrubbed.from || scrubbed.sender || scrubbed.source || "");
  const to = String(scrubbed.to || scrubbed.about || scrubbed.target || "office");
  return {
    id: String(scrubbed.id || `r-d${day}-${from}-${to}`),
    day,
    from,
    from_name: String(scrubbed.from_name || scrubbed.sender_name || from || "Staff"),
    to,
    to_name: String(scrubbed.to_name || scrubbed.about_name || scrubbed.target_name || to),
    channel: String(scrubbed.channel || "general"),
    subject: String(scrubbed.subject || ""),
    text: String(scrubbed.text || scrubbed.body || ""),
    bias_type: String(scrubbed.bias_type || "rumour"),
    doc_title: String(scrubbed.doc_title || ""),
  };
}

function normalizeChatItem(raw, fallbackDay) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const scrubbed = scrubLivingOfficePreEnd(raw);
  const day = Math.max(1, Math.trunc(Number(scrubbed.day) || fallbackDay || 1));
  const channel = String(scrubbed.channel || "general");
  const sender = String(scrubbed.sender || scrubbed.from || "");
  const senderName = String(scrubbed.sender_name || scrubbed.from_name || sender || "Staff");
  const target = String(scrubbed.target || scrubbed.to || scrubbed.about || "");
  const targetName = String(scrubbed.target_name || scrubbed.to_name || target || channel);
  const body = String(scrubbed.body || scrubbed.text || "");
  return {
    id: String(scrubbed.id || `m-d${day}-${sender}`),
    day,
    channel,
    sender,
    sender_name: senderName,
    from: sender,
    from_name: senderName,
    target,
    target_name: targetName,
    to: target || channel,
    to_name: targetName,
    recipients: Array.isArray(scrubbed.recipients)
      ? scrubbed.recipients.map((r) => String(r))
      : [],
    subject: String(scrubbed.subject || ""),
    body,
    text: String(scrubbed.text || body),
    bias_type: String(scrubbed.bias_type || "chatter"),
  };
}

function normalizeGrudgeItem(raw) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const scrubbed = scrubLivingOfficePreEnd(raw);
  const pair = Array.isArray(scrubbed.pair) ? scrubbed.pair : [];
  const a = String(scrubbed.a || pair[0] || "");
  const b = String(scrubbed.b || pair[1] || "");
  if (!a && !b) {
    return null;
  }
  const firstDay =
    scrubbed.first_day !== undefined
      ? Math.max(1, Math.trunc(Number(scrubbed.first_day) || 1))
      : scrubbed.since_day !== undefined
        ? Math.max(1, Math.trunc(Number(scrubbed.since_day) || 1))
        : 1;
  const lastDay =
    scrubbed.last_day !== undefined
      ? Math.max(1, Math.trunc(Number(scrubbed.last_day) || firstDay))
      : firstDay;
  return {
    a,
    a_name: String(scrubbed.a_name || a),
    b,
    b_name: String(scrubbed.b_name || b),
    dept: String(scrubbed.dept || ""),
    reason: String(scrubbed.reason || "workplace friction"),
    incidents: Math.max(1, Math.trunc(Number(scrubbed.incidents || scrubbed.weight || 1))),
    since_day: firstDay,
    first_day: firstDay,
    last_day: lastDay,
  };
}

function normalizeEdgeItem(raw, fallbackDay) {
  if (!isPlainObject(raw)) {
    return null;
  }
  const scrubbed = scrubLivingOfficePreEnd(raw);
  const day = Math.max(1, Math.trunc(Number(scrubbed.day) || fallbackDay || 1));
  const source = String(scrubbed.source || scrubbed.from || "");
  const target = String(scrubbed.target || scrubbed.to || "");
  if (!source && !target) {
    return null;
  }
  return {
    day,
    source,
    source_name: String(scrubbed.source_name || scrubbed.from_name || source),
    target,
    target_name: String(scrubbed.target_name || scrubbed.to_name || target),
    channel: String(scrubbed.channel || "general"),
    bias_type: String(scrubbed.bias_type || "gossip"),
    weight: Math.max(1, Number(scrubbed.weight || 1)),
    message_id: String(scrubbed.message_id || ""),
  };
}

export class CanaryLivingOffice {
  constructor(options = {}) {
    const passedPackDirectly =
      isPlainObject(options) &&
      (isPlainObject(options.episodes) || isPlainObject(options.seeds)) &&
      options.pack === undefined;

    const opts = passedPackDirectly ? { pack: options } : options || {};
    this._pack = isPlainObject(opts.pack) ? opts.pack : null;
    this._tier = String(opts.tier || "hard");
    this._officeStage = opts.officeStage || null;
    this._onSelectEmployee =
      typeof opts.onSelectEmployee === "function" ? opts.onSelectEmployee : null;
    this._document = opts.document || null;
  }

  setPack(pack) {
    this._pack = isPlainObject(pack) ? pack : null;
    return this;
  }

  getPack() {
    if (this._pack) {
      return this._pack;
    }
    const g = getGlobalRoot();
    if (isPlainObject(g.CANARY_LIVING_OFFICE_PACK)) {
      return g.CANARY_LIVING_OFFICE_PACK;
    }
    return null;
  }

  async loadPack(moduleUrl = "./data/living_office_pack.js") {
    const existing = this.getPack();
    if (existing) {
      return existing;
    }
    const mod = await import(moduleUrl);
    const loaded = (mod && (mod.CANARY_LIVING_OFFICE_PACK || mod.default)) || null;
    if (isPlainObject(loaded)) {
      this._pack = loaded;
      const g = getGlobalRoot();
      if (isPlainObject(g) && !g.CANARY_LIVING_OFFICE_PACK) {
        g.CANARY_LIVING_OFFICE_PACK = loaded;
      }
    }
    return this.getPack();
  }

  isEnabledByDefault() {
    return false;
  }

  isGateBPassed() {
    const pack = this.getPack();
    if (pack && pack.gateBPassed === true) {
      return false;
    }
    return false;
  }

  getBanner() {
    const pack = this.getPack();
    if (pack && typeof pack.banner === "string" && pack.banner.trim()) {
      return pack.banner.trim();
    }
    return DEFAULT_LIVING_OFFICE_BANNER;
  }

  getRulesDisclosure() {
    const pack = this.getPack();
    if (pack && typeof pack.rules_disclosure === "string" && pack.rules_disclosure.trim()) {
      return pack.rules_disclosure.trim();
    }
    return LIVING_OFFICE_RULES_NOTE;
  }

  getGateBDisclosure() {
    const pack = this.getPack();
    const base =
      pack && isPlainObject(pack.gate_b_disclosure)
        ? scrubLivingOfficePreEnd(pack.gate_b_disclosure)
        : {};
    return Object.assign(
      {
        gateBPassed: false,
        gate_b_passed: false,
        default_enabled: false,
        shipped_benchmark_version: "v1.4",
        verdict: "GATE NOT MET - DO NOT SHIP AS DEFAULT",
      },
      base,
      {
        gateBPassed: false,
        gate_b_passed: false,
        default_enabled: false,
      }
    );
  }

  getProvenance() {
    const pack = this.getPack();
    const base =
      pack && isPlainObject(pack.provenance)
        ? scrubLivingOfficePreEnd(pack.provenance)
        : {};
    return Object.assign(
      {
        offline_only: true,
        live_api_calls: 0,
        model: "gemini-4-carbon",
        label: "REAL",
      },
      base,
      {
        offline_only: true,
        live_api_calls: 0,
      }
    );
  }

  getAvailableSeeds(tier = "hard") {
    const targetTier = String(tier || this._tier || "hard");
    const pack = this.getPack();
    if (!pack) {
      return [];
    }

    const found = new Set();

    if (isPlainObject(pack.episodes)) {
      for (const [key, ep] of Object.entries(pack.episodes)) {
        if (key.startsWith(`${targetTier}:`)) {
          const rawSeed = Number(key.slice(targetTier.length + 1));
          if (isAllowedPublicSeed(rawSeed)) {
            found.add(rawSeed);
          }
        } else if (
          isPlainObject(ep) &&
          String(ep.tier || "hard") === targetTier &&
          isAllowedPublicSeed(ep.seed)
        ) {
          found.add(Number(ep.seed));
        }
      }
    }

    if (found.size === 0 && isPlainObject(pack.available_seeds)) {
      const tierArr = pack.available_seeds[targetTier];
      if (Array.isArray(tierArr)) {
        for (const s of tierArr) {
          if (isAllowedPublicSeed(s)) {
            found.add(Number(s));
          }
        }
      }
    }

    if (found.size === 0 && targetTier === String(pack.tier || "hard")) {
      const list = Array.isArray(pack.default_seeds)
        ? pack.default_seeds
        : Array.isArray(pack.seeds)
          ? pack.seeds
          : [];
      for (const s of list) {
        if (isAllowedPublicSeed(s)) {
          found.add(Number(s));
        }
      }
    }

    if (found.size === 0 && isPlainObject(pack.seeds) && !Array.isArray(pack.seeds)) {
      for (const [k, ep] of Object.entries(pack.seeds)) {
        const num = Number(k);
        const epTier = isPlainObject(ep) ? String(ep.tier || "hard") : "hard";
        if (epTier === targetTier && isAllowedPublicSeed(num)) {
          found.add(num);
        }
      }
    }

    return Array.from(found).sort((a, b) => a - b);
  }

  _resolveEpisode(seed, tier = "hard") {
    const numSeed = Number(seed);
    if (!isAllowedPublicSeed(numSeed)) {
      return null;
    }
    const targetTier = String(tier || this._tier || "hard");
    const pack = this.getPack();
    if (!pack) {
      return null;
    }
    if (isPlainObject(pack.episodes)) {
      const keyed = pack.episodes[`${targetTier}:${numSeed}`];
      if (isPlainObject(keyed)) {
        return keyed;
      }
      const plain = pack.episodes[String(numSeed)];
      if (isPlainObject(plain) && String(plain.tier || "hard") === targetTier) {
        return plain;
      }
    }
    if (isPlainObject(pack.seeds) && !Array.isArray(pack.seeds)) {
      const bySeed = pack.seeds[String(numSeed)];
      if (isPlainObject(bySeed) && String(bySeed.tier || "hard") === targetTier) {
        return bySeed;
      }
    }
    return null;
  }

  getDayState(seed, day = 1, humanDone = false, tier = "hard") {
    const targetTier = String(tier || this._tier || "hard");
    const requestedDay = Math.max(1, Math.trunc(Number(day) || 1));
    const banner = this.getBanner();
    const ep = this._resolveEpisode(seed, targetTier);

    if (!ep) {
      return {
        available: false,
        tier: targetTier,
        seed: Number.isFinite(Number(seed)) ? Math.trunc(Number(seed)) : 0,
        company: "",
        day: requestedDay,
        max_day: 21,
        default_enabled: false,
        gateBPassed: false,
        banner,
        employees: [],
        focal_targets: null,
        rumours: [],
        new_rumours: [],
        grudges: [],
        chat_feed: [],
        new_chat_feed: [],
        gossip_edges: [],
        new_gossip_edges: [],
      };
    }

    const maxDay = Math.max(1, Math.trunc(Number(ep.max_day || ep.n_days || 21)));
    const clampedDay = Math.max(1, Math.min(maxDay, requestedDay));
    const employees = Array.isArray(ep.employees)
      ? ep.employees.map(sanitizeEmployeeRow).filter(Boolean)
      : [];

    const cumulativeRumours = [];
    const cumulativeChat = [];
    const cumulativeEdges = [];
    let dayRumours = [];
    let dayChat = [];
    let dayEdges = [];
    let activeGrudges = [];

    if (Array.isArray(ep.days)) {
      for (const dayEntry of ep.days) {
        if (!isPlainObject(dayEntry)) {
          continue;
        }
        const entryDay = Math.max(1, Math.trunc(Number(dayEntry.day) || 1));
        if (entryDay > clampedDay) {
          continue;
        }

        const rawNewRumours = Array.isArray(dayEntry.new_rumours)
          ? dayEntry.new_rumours
          : Array.isArray(dayEntry.rumours)
            ? dayEntry.rumours
            : [];
        const normRumours = rawNewRumours
          .map((item) => normalizeRumourItem(item, entryDay))
          .filter((item) => item && item.day <= clampedDay);

        const rawNewChat = Array.isArray(dayEntry.new_chat_feed)
          ? dayEntry.new_chat_feed
          : Array.isArray(dayEntry.chat_feed)
            ? dayEntry.chat_feed
            : [];
        const normChat = rawNewChat
          .map((item) => normalizeChatItem(item, entryDay))
          .filter((item) => item && item.day <= clampedDay);

        const rawNewEdges = Array.isArray(dayEntry.new_gossip_edges)
          ? dayEntry.new_gossip_edges
          : Array.isArray(dayEntry.gossip_edges)
            ? dayEntry.gossip_edges
            : [];
        const normEdges = rawNewEdges
          .map((item) => normalizeEdgeItem(item, entryDay))
          .filter((item) => item && item.day <= clampedDay);

        cumulativeRumours.push(...normRumours);
        cumulativeChat.push(...normChat);
        cumulativeEdges.push(...normEdges);

        if (entryDay === clampedDay) {
          dayRumours = normRumours;
          dayChat = normChat;
          dayEdges = normEdges;
          const rawGrudges = Array.isArray(dayEntry.active_grudges)
            ? dayEntry.active_grudges
            : Array.isArray(dayEntry.grudges)
              ? dayEntry.grudges
              : [];
          activeGrudges = rawGrudges.map(normalizeGrudgeItem).filter(Boolean);
        }
      }
    } else {
      if (Array.isArray(ep.rumours)) {
        for (const r of ep.rumours) {
          const norm = normalizeRumourItem(r, 1);
          if (norm && norm.day <= clampedDay) {
            cumulativeRumours.push(norm);
            if (norm.day === clampedDay) {
              dayRumours.push(norm);
            }
          }
        }
      }
      if (Array.isArray(ep.chat_feed)) {
        for (const c of ep.chat_feed) {
          const norm = normalizeChatItem(c, 1);
          if (norm && norm.day <= clampedDay) {
            cumulativeChat.push(norm);
            if (norm.day === clampedDay) {
              dayChat.push(norm);
            }
          }
        }
      }
      if (Array.isArray(ep.gossip_edges)) {
        for (const gEdge of ep.gossip_edges) {
          const norm = normalizeEdgeItem(gEdge, 1);
          if (norm && norm.day <= clampedDay) {
            cumulativeEdges.push(norm);
            if (norm.day === clampedDay) {
              dayEdges.push(norm);
            }
          }
        }
      }
    }

    if (activeGrudges.length === 0 && Array.isArray(ep.grudge_pairs)) {
      activeGrudges = ep.grudge_pairs
        .map(normalizeGrudgeItem)
        .filter((gItem) => gItem && gItem.first_day <= clampedDay);
    }

    const focalTargets = isPlainObject(ep.focal_targets)
      ? {
          primary: String(ep.focal_targets.primary || ""),
          secondary: String(ep.focal_targets.secondary || ""),
        }
      : null;

    return scrubLivingOfficePreEnd({
      available: true,
      tier: targetTier,
      seed: Math.trunc(Number(seed)),
      company: String(ep.company || ""),
      day: clampedDay,
      max_day: maxDay,
      human_done_ack: Boolean(humanDone === true),
      default_enabled: false,
      gateBPassed: false,
      banner,
      employees,
      focal_targets: focalTargets,
      rumours: cumulativeRumours,
      new_rumours: dayRumours,
      grudges: activeGrudges,
      chat_feed: cumulativeChat,
      new_chat_feed: dayChat,
      gossip_edges: cumulativeEdges,
      new_gossip_edges: dayEdges,
    });
  }

  renderDay(seed, day = 1, tier = "hard") {
    return this.getDayState(seed, day, false, tier);
  }

  getReveal(seed, humanDone = false, tier = "hard") {
    if (humanDone !== true) {
      return null;
    }
    const ep = this._resolveEpisode(seed, tier);
    if (!ep) {
      return null;
    }
    const rawReveal = ep.sealed_reveal || ep.post_end_reveal || null;
    if (!isPlainObject(rawReveal)) {
      return null;
    }
    return cloneJsonSafe(rawReveal);
  }

  getStageEventsForDay(seed, day = 1, tier = "hard") {
    const state = this.getDayState(seed, day, false, tier);
    if (!state.available) {
      return [];
    }
    const events = [];
    for (const r of state.new_rumours) {
      if (r.from && r.to) {
        events.push({
          type: r.bias_type === "grudge" ? "social_grudge" : "social_rumour",
          day: state.day,
          from: r.from,
          to: r.to,
          channel: r.channel,
          bias_type: r.bias_type,
        });
      }
    }
    for (const gItem of state.grudges) {
      if (gItem.a && gItem.b && gItem.last_day === state.day) {
        events.push({
          type: "social_grudge",
          day: state.day,
          from: gItem.a,
          to: gItem.b,
          reason: gItem.reason,
        });
      }
    }
    return scrubLivingOfficePreEnd(events);
  }

  syncOfficeStage(officeStage, seed, day = 1, tier = "hard") {
    const stage = officeStage || this._officeStage;
    if (!stage || typeof stage.applyObservableEvent !== "function") {
      return 0;
    }
    const events = this.getStageEventsForDay(seed, day, tier);
    let applied = 0;
    for (const evt of events) {
      stage.applyObservableEvent(evt);
      applied += 1;
    }
    return applied;
  }

  renderPanel(container, options = {}) {
    if (!container) {
      throw new Error("CanaryLivingOffice.renderPanel requires a container element");
    }
    const doc =
      options.document ||
      this._document ||
      container.ownerDocument ||
      (getGlobalRoot().document || null);
    if (doc) {
      setDocument(doc);
    }

    const availSeeds = this.getAvailableSeeds(options.tier || this._tier);
    const initialSeed =
      options.seed !== undefined
        ? Number(options.seed)
        : availSeeds.length > 0
          ? availSeeds[0]
          : 0;

    const panelState = {
      tier: String(options.tier || this._tier || "hard"),
      seed: initialSeed,
      day: Math.max(1, Math.trunc(Number(options.day || 1))),
      maxDayCap:
        options.maxDayCap !== undefined
          ? Math.max(1, Math.trunc(Number(options.maxDayCap) || 21))
          : 21,
      humanDone: Boolean(options.humanDone === true),
      biasFilter: String(options.biasFilter || "all"),
      activeTab: String(options.activeTab || "rumours"),
    };

    const onSelectEmployee =
      typeof options.onSelectEmployee === "function"
        ? options.onSelectEmployee
        : this._onSelectEmployee;

    const renderView = () => {
      clear(container);
      const effectiveDay = Math.min(panelState.day, panelState.maxDayCap);
      const dayData = this.getDayState(
        panelState.seed,
        effectiveDay,
        panelState.humanDone,
        panelState.tier
      );
      const provenance = this.getProvenance();
      const gateB = this.getGateBDisclosure();

      const header = el(
        "div",
        { class: "sheet-h" },
        el("span", {}, "Living Office Social Layer (Mode 4)"),
        el(
          "span",
          { class: "preview-badge", dataset: { gateBPassed: "false" } },
          "V1.6 PREVIEW - OFF BY DEFAULT"
        )
      );

      const bannerBox = el(
        "div",
        { class: "leak-alert", dataset: { role: "living-office-banner" } },
        el("span", {}, dayData.banner),
        el(
          "span",
          { class: "t red" },
          gateB.gateBPassed ? "GATE B PASS" : "GATE B NOT MET"
        )
      );

      const metaStrip = el(
        "div",
        { class: "rumour-item mono dim", dataset: { role: "living-office-provenance" } },
        `Model: ${provenance.model} (${provenance.label}) | Live API calls: ${provenance.live_api_calls} | Default benchmark: v1.4 (0 drift)`
      );

      const seedButtons = availSeeds.map((s) =>
        el(
          "button",
          {
            type: "button",
            class: s === panelState.seed ? "seed-pill active" : "seed-pill",
            "aria-pressed": s === panelState.seed ? "true" : "false",
            dataset: { livingSeed: String(s) },
            onClick: () => {
              panelState.seed = s;
              renderView();
            },
          },
          `Cached Seed ${s}`
        )
      );

      const maxAllowedDay = Math.min(dayData.max_day || 21, panelState.maxDayCap);
      const prevBtn = el(
        "button",
        {
          type: "button",
          class: "ghost",
          disabled: effectiveDay <= 1,
          dataset: { livingDayStep: "prev" },
          onClick: () => {
            panelState.day = Math.max(1, effectiveDay - 1);
            renderView();
          },
        },
        "Prev Day"
      );
      const nextBtn = el(
        "button",
        {
          type: "button",
          class: "ghost",
          disabled: effectiveDay >= maxAllowedDay,
          dataset: { livingDayStep: "next" },
          onClick: () => {
            panelState.day = Math.min(maxAllowedDay, effectiveDay + 1);
            renderView();
          },
        },
        "Next Day"
      );

      const controlsRow = el(
        "div",
        { class: "rumour-item" },
        el(
          "div",
          { class: "seed-group" },
          seedButtons,
          prevBtn,
          el(
            "span",
            { class: "mono", dataset: { role: "living-day-indicator" } },
            `Day ${pad2(effectiveDay)} / ${pad2(maxAllowedDay)}`
          ),
          nextBtn
        )
      );

      const biasTypes = ["all", "anchoring", "authority", "grudge", "misforward", "availability"];
      const filterRow = el(
        "div",
        { class: "rumour-item" },
        el(
          "div",
          { class: "seed-group" },
          el("span", { class: "lbl" }, "Bias Filter"),
          biasTypes.map((bType) =>
            el(
              "button",
              {
                type: "button",
                class: "ghost",
                "aria-pressed": panelState.biasFilter === bType ? "true" : "false",
                dataset: { biasFilter: bType },
                onClick: () => {
                  panelState.biasFilter = bType;
                  renderView();
                },
              },
              bType
            )
          )
        )
      );

      const tabRow = el(
        "div",
        { class: "rumour-item" },
        el(
          "div",
          { class: "seed-group" },
          [
            { id: "rumours", label: `Rumours (${dayData.rumours.length})` },
            { id: "chat", label: `Office Chat (${dayData.chat_feed.length})` },
            { id: "graph", label: `Gossip Edges (${dayData.gossip_edges.length})` },
          ].map((tb) =>
            el(
              "button",
              {
                type: "button",
                class: "ghost",
                "aria-pressed": panelState.activeTab === tb.id ? "true" : "false",
                dataset: { livingTab: tb.id },
                onClick: () => {
                  panelState.activeTab = tb.id;
                  renderView();
                },
              },
              tb.label
            )
          )
        )
      );

      const grudgeSection = dayData.grudges.length
        ? el(
            "div",
            { class: "rumour-item", dataset: { role: "living-grudges" } },
            el("div", { class: "lbl" }, "Active Grudge Pairs"),
            dayData.grudges.map((gItem) =>
              el(
                "span",
                { class: "grudge-pill" },
                `${gItem.a_name} (${gItem.a}) vs ${gItem.b_name} (${gItem.b}) - ${gItem.reason}`
              )
            )
          )
        : el(
            "div",
            { class: "rumour-item dim", dataset: { role: "living-grudges" } },
            `No active workplace grudges recorded through Day ${pad2(effectiveDay)}.`
          );

      const feedWrap = el("div", { class: "step-feed", dataset: { role: "living-feed" } });

      const matchesFilter = (biasVal) =>
        panelState.biasFilter === "all" ||
        String(biasVal || "").toLowerCase() === panelState.biasFilter;

      if (panelState.activeTab === "rumours") {
        const filtered = dayData.rumours
          .filter((r) => matchesFilter(r.bias_type))
          .slice()
          .reverse();
        if (!filtered.length) {
          feedWrap.appendChild(
            el(
              "div",
              { class: "rumour-item dim" },
              `No cached rumours matching '${panelState.biasFilter}' up to Day ${pad2(effectiveDay)}.`
            )
          );
        } else {
          for (const r of filtered) {
            const isToday = r.day === effectiveDay;
            const actorBtn =
              r.to && r.to !== "office"
                ? el(
                    "button",
                    {
                      type: "button",
                      class: "ghost mono",
                      onClick: () => {
                        if (onSelectEmployee) {
                          onSelectEmployee(r.to);
                        }
                      },
                    },
                    `${r.to_name} (${r.to})`
                  )
                : el("span", { class: "mono" }, r.to_name || "office");

            feedWrap.appendChild(
              el(
                "div",
                {
                  class: isToday ? "rumour-item step-item current" : "rumour-item",
                  dataset: { day: String(r.day), biasType: r.bias_type },
                },
                el(
                  "div",
                  { class: "seed-group" },
                  el("strong", { class: "mono" }, `[D${pad2(r.day)}] ${r.from_name} (${r.from}) -> `),
                  actorBtn,
                  el("span", { class: "t dim" }, r.bias_type),
                  r.channel ? el("span", { class: "mono dim" }, `ch:${r.channel}`) : null
                ),
                el("div", {}, r.text)
              )
            );
          }
        }
      } else if (panelState.activeTab === "chat") {
        const filteredChat = dayData.chat_feed
          .filter((m) => matchesFilter(m.bias_type))
          .slice()
          .reverse();
        if (!filteredChat.length) {
          feedWrap.appendChild(
            el(
              "div",
              { class: "rumour-item dim" },
              `No cached chat messages matching '${panelState.biasFilter}' up to Day ${pad2(effectiveDay)}.`
            )
          );
        } else {
          for (const msg of filteredChat) {
            feedWrap.appendChild(
              el(
                "div",
                {
                  class: msg.day === effectiveDay ? "rumour-item step-item current" : "rumour-item",
                  dataset: { day: String(msg.day), biasType: msg.bias_type },
                },
                el(
                  "div",
                  { class: "seed-group" },
                  el("strong", { class: "mono" }, `[D${pad2(msg.day)}] ${msg.sender_name} (${msg.sender})`),
                  el("span", { class: "mono dim" }, `ch:${msg.channel}`),
                  el("span", { class: "t dim" }, msg.bias_type)
                ),
                msg.subject ? el("div", { class: "mono dim" }, msg.subject) : null,
                el("div", {}, msg.text)
              )
            );
          }
        }
      } else {
        const filteredEdges = dayData.gossip_edges
          .filter((edge) => matchesFilter(edge.bias_type))
          .slice()
          .reverse();
        if (!filteredEdges.length) {
          feedWrap.appendChild(
            el(
              "div",
              { class: "rumour-item dim" },
              `No gossip propagation edges matching '${panelState.biasFilter}' up to Day ${pad2(effectiveDay)}.`
            )
          );
        } else {
          for (const edge of filteredEdges) {
            feedWrap.appendChild(
              el(
                "div",
                { class: "rumour-item mono", dataset: { day: String(edge.day) } },
                `[D${pad2(edge.day)}] ${edge.source_name} (${edge.source}) ---> ${edge.target_name} (${edge.target}) `,
                el("span", { class: "t dim" }, edge.bias_type),
                ` via ${edge.channel}`
              )
            );
          }
        }
      }

      let postEndBox = null;
      if (panelState.humanDone === true) {
        const rev = this.getReveal(panelState.seed, true, panelState.tier);
        if (rev) {
          postEndBox = el(
            "div",
            { class: "rumour-item", dataset: { role: "living-post-end-audit" } },
            el("strong", { class: "mono" }, "Post-Episode Bias Audit Unlocked: "),
            el(
              "span",
              {},
              `True mole ${rev.mole_name || rev.mole} (${rev.mole}); Day 1 public rumour focal staff ${rev.primary_focus || "-"} / ${rev.secondary_focus || "-"} (primary_is_mole=${String(Boolean(rev.primary_focus_is_mole))}).`
            )
          );
        }
      }

      const drawer = el(
        "section",
        { class: "social-drawer", dataset: { mode: "living", seed: String(panelState.seed) } },
        header,
        bannerBox,
        metaStrip,
        controlsRow,
        filterRow,
        grudgeSection,
        tabRow,
        feedWrap,
        postEndBox
      );

      container.appendChild(drawer);

      if (this._officeStage) {
        this.syncOfficeStage(
          this._officeStage,
          panelState.seed,
          effectiveDay,
          panelState.tier
        );
      }
    };

    renderView();

    return {
      container,
      getState() {
        return {
          tier: panelState.tier,
          seed: panelState.seed,
          day: Math.min(panelState.day, panelState.maxDayCap),
          maxDayCap: panelState.maxDayCap,
          humanDone: panelState.humanDone,
          biasFilter: panelState.biasFilter,
          activeTab: panelState.activeTab,
        };
      },
      setSeed(nextSeed) {
        if (isAllowedPublicSeed(nextSeed)) {
          panelState.seed = Math.trunc(Number(nextSeed));
          renderView();
        }
      },
      setDay(nextDay, nextMaxCap) {
        if (nextMaxCap !== undefined) {
          panelState.maxDayCap = Math.max(1, Math.trunc(Number(nextMaxCap) || 21));
        }
        panelState.day = Math.max(1, Math.trunc(Number(nextDay) || 1));
        renderView();
      },
      setFilter(nextFilter) {
        panelState.biasFilter = String(nextFilter || "all");
        renderView();
      },
      setTab(nextTab) {
        panelState.activeTab = String(nextTab || "rumours");
        renderView();
      },
      setHumanDone(doneFlag) {
        panelState.humanDone = Boolean(doneFlag === true);
        renderView();
      },
      refresh: renderView,
      destroy() {
        clear(container);
      },
    };
  }

  mount(container, options = {}) {
    return this.renderPanel(container, options);
  }
}

let defaultLivingOfficeInstance = null;

function getDefaultInstance() {
  if (!defaultLivingOfficeInstance) {
    defaultLivingOfficeInstance = new CanaryLivingOffice();
  }
  return defaultLivingOfficeInstance;
}

CanaryLivingOffice.configure = function configureLivingOffice(options = {}) {
  defaultLivingOfficeInstance = new CanaryLivingOffice(options);
  return defaultLivingOfficeInstance;
};

CanaryLivingOffice.setPack = function setDefaultPack(pack) {
  return getDefaultInstance().setPack(pack);
};

CanaryLivingOffice.getPack = function getDefaultPack() {
  return getDefaultInstance().getPack();
};

CanaryLivingOffice.loadPack = function loadDefaultPack(moduleUrl) {
  return getDefaultInstance().loadPack(moduleUrl);
};

CanaryLivingOffice.isEnabledByDefault = function isEnabledByDefaultStatic() {
  return false;
};

CanaryLivingOffice.isGateBPassed = function isGateBPassedStatic() {
  return getDefaultInstance().isGateBPassed();
};

CanaryLivingOffice.getBanner = function getBannerStatic() {
  return getDefaultInstance().getBanner();
};

CanaryLivingOffice.getRulesDisclosure = function getRulesDisclosureStatic() {
  return getDefaultInstance().getRulesDisclosure();
};

CanaryLivingOffice.getGateBDisclosure = function getGateBDisclosureStatic() {
  return getDefaultInstance().getGateBDisclosure();
};

CanaryLivingOffice.getProvenance = function getProvenanceStatic() {
  return getDefaultInstance().getProvenance();
};

CanaryLivingOffice.getAvailableSeeds = function getAvailableSeedsStatic(tier = "hard") {
  return getDefaultInstance().getAvailableSeeds(tier);
};

CanaryLivingOffice.getDayState = function getDayStateStatic(
  seed,
  day = 1,
  humanDone = false,
  tier = "hard"
) {
  return getDefaultInstance().getDayState(seed, day, humanDone, tier);
};

CanaryLivingOffice.renderDay = function renderDayStatic(seed, day = 1, tier = "hard") {
  return getDefaultInstance().renderDay(seed, day, tier);
};

CanaryLivingOffice.getReveal = function getRevealStatic(
  seed,
  humanDone = false,
  tier = "hard"
) {
  return getDefaultInstance().getReveal(seed, humanDone, tier);
};

CanaryLivingOffice.getStageEventsForDay = function getStageEventsForDayStatic(
  seed,
  day = 1,
  tier = "hard"
) {
  return getDefaultInstance().getStageEventsForDay(seed, day, tier);
};

CanaryLivingOffice.syncOfficeStage = function syncOfficeStageStatic(
  officeStage,
  seed,
  day = 1,
  tier = "hard"
) {
  return getDefaultInstance().syncOfficeStage(officeStage, seed, day, tier);
};

CanaryLivingOffice.renderPanel = function renderPanelStatic(container, options = {}) {
  return getDefaultInstance().renderPanel(container, options);
};

CanaryLivingOffice.mount = function mountStatic(container, options = {}) {
  return getDefaultInstance().mount(container, options);
};

export function createLivingOffice(options = {}) {
  return new CanaryLivingOffice(options);
}

const gRef = getGlobalRoot();
if (isPlainObject(gRef)) {
  gRef.CanaryLivingOffice = CanaryLivingOffice;
  if (
    typeof gRef.window !== "undefined" &&
    typeof gRef.document !== "undefined" &&
    !gRef.CANARY_LIVING_OFFICE_PACK
  ) {
    import("./data/living_office_pack.js").catch(() => null);
  }
}
