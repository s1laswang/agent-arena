import { el, clear, pad2, fmtScore, setDocument, MODE_DEFS } from "./dom.js";
import { computeFirstCatchLabel, buildCanonicalShareLine } from "./arena_app.js";

export const LEADERBOARD_STORAGE_KEY = "canary_arena_leaderboard_v1";
export const LEADERBOARD_MAX_ENTRIES = 100;
export const LEADERBOARD_MODES = ["all", "duel", "solver", "mole", "living"];

const VALID_PLAY_MODES = new Set(["duel", "solver", "mole", "living"]);
const VALID_FILTER_MODES = new Set(LEADERBOARD_MODES);
const RIVAL_SKIP_KEYS = new Set([
  "tactical_debrief",
  "tacticalDebrief",
  "notes",
  "headline",
  "summary",
  "ok",
  "done",
  "seed",
  "tier",
]);

function getGlobalObj() {
  if (typeof globalThis !== "undefined") return globalThis;
  if (typeof window !== "undefined") return window;
  return {};
}

function resolveDoc(node, options) {
  if (options && options.document) return options.document;
  if (node && node.ownerDocument) return node.ownerDocument;
  const g = getGlobalObj();
  if (g && g.document) return g.document;
  return null;
}

function withDoc(doc, attrs = {}) {
  if (doc) {
    return Object.assign({ document: doc }, attrs);
  }
  return attrs;
}

function setHiddenState(node, hiddenFlag) {
  if (!node) return;
  const hide = Boolean(hiddenFlag);
  node.hidden = hide;
  if (hide) {
    if (typeof node.setAttribute === "function") {
      node.setAttribute("hidden", "");
    }
  } else {
    if (typeof node.removeAttribute === "function") {
      node.removeAttribute("hidden");
    } else if (node.attrs && typeof node.attrs === "object") {
      delete node.attrs.hidden;
    }
  }
}

function ensureClassName(node, requiredClass) {
  if (!node || !requiredClass) return;
  const raw = typeof node.className === "string" ? node.className : "";
  const tokens = raw
    .trim()
    .split(" ")
    .map((s) => s.trim())
    .filter(Boolean);
  if (!tokens.includes(requiredClass)) {
    tokens.push(requiredClass);
    const joined = tokens.join(" ");
    node.className = joined;
    if (typeof node.setAttribute === "function") {
      node.setAttribute("class", joined);
    }
  }
}

function normalizeMode(rawMode, fallback = "duel") {
  if (typeof rawMode !== "string") return fallback;
  const clean = rawMode.trim().toLowerCase();
  return VALID_PLAY_MODES.has(clean) ? clean : fallback;
}

function normalizeFilterMode(rawFilter) {
  if (typeof rawFilter !== "string") return "all";
  const clean = rawFilter.trim().toLowerCase();
  return VALID_FILTER_MODES.has(clean) ? clean : "all";
}

function getModeLabel(modeId) {
  if (modeId === "all") return "All Modes";
  if (MODE_DEFS && MODE_DEFS[modeId] && MODE_DEFS[modeId].label) {
    return String(MODE_DEFS[modeId].label);
  }
  if (Array.isArray(MODE_DEFS)) {
    const hit = MODE_DEFS.find((item) => item && item.id === modeId);
    if (hit && hit.label) return String(hit.label);
  }
  return String(modeId || "duel");
}

function toFiniteOrNull(val) {
  if (val === null || val === undefined || val === "" || typeof val === "boolean") {
    return null;
  }
  const num = Number(val);
  return Number.isFinite(num) ? num : null;
}

function round4(num) {
  return Math.round(num * 10000) / 10000;
}

function cleanAccused(raw) {
  if (typeof raw !== "string") return null;
  const trimmed = raw.trim();
  if (!trimmed || trimmed === "-" || trimmed.toLowerCase() === "none") {
    return null;
  }
  return trimmed;
}

function detectDefaultStorage() {
  try {
    const g = getGlobalObj();
    if (g && g.localStorage) {
      const candidate = g.localStorage;
      if (
        typeof candidate.getItem === "function" &&
        typeof candidate.setItem === "function"
      ) {
        return candidate;
      }
    }
  } catch (_) {
    return null;
  }
  return null;
}

function normalizeStoredEntry(raw) {
  const src = raw && typeof raw === "object" ? raw : {};
  const mode = normalizeMode(src.mode, "duel");
  const tier =
    typeof src.tier === "string" && src.tier.trim()
      ? src.tier.trim()
      : mode === "solver"
        ? "medium"
        : "hard";

  let seed = 0;
  if (src.seed !== undefined && src.seed !== null && String(src.seed).trim() !== "") {
    const numSeed = toFiniteOrNull(src.seed);
    seed = numSeed !== null ? numSeed : String(src.seed).trim();
  }

  const youObj = src.you && typeof src.you === "object" ? src.you : null;
  const directScore = toFiniteOrNull(src.score);
  const nestedScore = youObj ? toFiniteOrNull(youObj.score) : null;
  const score = round4(directScore !== null ? directScore : nestedScore !== null ? nestedScore : 0);

  const correct = Boolean(
    src.correct === true ||
      (youObj && youObj.correct === true) ||
      (typeof src.status === "string" && src.status.trim().toLowerCase() === "caught")
  );

  const rawDay =
    src.final_day !== undefined
      ? src.final_day
      : src.finalDay !== undefined
        ? src.finalDay
        : src.day !== undefined
          ? src.day
          : youObj
            ? youObj.final_day !== undefined
              ? youObj.final_day
              : youObj.finalDay
            : 0;
  const dayNum = toFiniteOrNull(rawDay);
  const final_day = dayNum !== null ? Math.max(0, Math.trunc(dayNum)) : 0;

  const accused =
    cleanAccused(src.accused) ||
    cleanAccused(src.accused_id) ||
    (youObj ? cleanAccused(youObj.accused) : null);

  const rawCalls =
    src.tool_calls !== undefined
      ? src.tool_calls
      : src.toolCalls !== undefined
        ? src.toolCalls
        : src.calls !== undefined
          ? src.calls
          : youObj
            ? youObj.tool_calls !== undefined
              ? youObj.tool_calls
              : youObj.toolCalls
            : null;
  const callsNum = toFiniteOrNull(rawCalls);
  const tool_calls = callsNum !== null ? Math.max(0, Math.trunc(callsNum)) : null;

  let first_catch = "None";
  if (typeof src.first_catch === "string" && src.first_catch.trim()) {
    first_catch = src.first_catch.trim();
  } else if (typeof src.firstCatch === "string" && src.firstCatch.trim()) {
    first_catch = src.firstCatch.trim();
  } else if (src.humanDone === true) {
    first_catch = computeFirstCatchLabel(src);
  } else if (correct) {
    first_catch = "You";
  }

  const solverRaw =
    src.solver_score !== undefined
      ? src.solver_score
      : src.solverScore !== undefined
        ? src.solverScore
        : src.solver && typeof src.solver === "object"
          ? src.solver.score
          : null;
  const solverNum = toFiniteOrNull(solverRaw);

  const geminiRaw =
    src.gemini_score !== undefined
      ? src.gemini_score
      : src.geminiScore !== undefined
        ? src.geminiScore
        : src.gemini && typeof src.gemini === "object"
          ? src.gemini.score
          : null;
  const geminiNum = toFiniteOrNull(geminiRaw);

  const tsNum = toFiniteOrNull(src.ts !== undefined ? src.ts : src.timestamp);

  return {
    mode,
    tier,
    seed,
    score,
    correct,
    final_day,
    accused,
    tool_calls,
    first_catch,
    solver_score: solverNum !== null ? round4(solverNum) : null,
    gemini_score: geminiNum !== null ? round4(geminiNum) : null,
    ts: tsNum !== null ? tsNum : Date.now(),
  };
}

export function createLeaderboardStore(storageObj) {
  let backing =
    arguments.length === 0 ? detectDefaultStorage() : storageObj || null;
  let mem = [];

  function loadRows() {
    if (backing && typeof backing.getItem === "function") {
      try {
        const raw = backing.getItem(LEADERBOARD_STORAGE_KEY);
        if (raw === null || raw === undefined || raw === "") {
          return mem.slice(0, LEADERBOARD_MAX_ENTRIES);
        }
        if (typeof raw === "string") {
          const parsed = JSON.parse(raw);
          const arr = Array.isArray(parsed)
            ? parsed
            : parsed && typeof parsed === "object" && Array.isArray(parsed.entries)
              ? parsed.entries
              : null;
          if (arr) {
            const clean = [];
            for (const item of arr) {
              if (item && typeof item === "object" && !Array.isArray(item)) {
                clean.push(normalizeStoredEntry(item));
                if (clean.length >= LEADERBOARD_MAX_ENTRIES) break;
              }
            }
            mem = clean.slice(0, LEADERBOARD_MAX_ENTRIES);
            return mem.slice();
          }
        }
      } catch (_) {
        return mem.slice(0, LEADERBOARD_MAX_ENTRIES);
      }
    }
    return mem.slice(0, LEADERBOARD_MAX_ENTRIES);
  }

  function saveRows(rows) {
    mem = rows.slice(0, LEADERBOARD_MAX_ENTRIES);
    if (backing && typeof backing.setItem === "function") {
      try {
        backing.setItem(LEADERBOARD_STORAGE_KEY, JSON.stringify(mem));
      } catch (_) {
        backing = null;
      }
    }
  }

  loadRows();

  return {
    list(modeFilter = "all") {
      const rows = loadRows();
      const filter = normalizeFilterMode(modeFilter);
      const selected =
        filter === "all" ? rows : rows.filter((row) => row && row.mode === filter);
      return selected.map((row) => Object.assign({}, row));
    },

    add(entry) {
      if (!entry || typeof entry !== "object" || Array.isArray(entry)) {
        return null;
      }
      const norm = normalizeStoredEntry(entry);
      const rows = loadRows();
      rows.unshift(norm);
      saveRows(rows);
      return Object.assign({}, norm);
    },

    clear() {
      mem = [];
      if (backing) {
        try {
          if (typeof backing.removeItem === "function") {
            backing.removeItem(LEADERBOARD_STORAGE_KEY);
          } else if (typeof backing.setItem === "function") {
            backing.setItem(LEADERBOARD_STORAGE_KEY, "[]");
          }
        } catch (_) {
          backing = null;
        }
      }
    },

    bestForSeed(mode, tier, seed) {
      let targetTier = tier;
      let targetSeed = seed;
      if (targetSeed === undefined && targetTier !== undefined && typeof targetTier === "number") {
        targetSeed = targetTier;
        targetTier = null;
      }
      if (targetSeed === undefined || targetSeed === null) return null;

      const rows = loadRows();
      const normMode =
        typeof mode === "string" && mode.trim() && mode.trim().toLowerCase() !== "all"
          ? normalizeMode(mode, "")
          : "";
      const normTier =
        targetTier !== null && targetTier !== undefined && String(targetTier).trim() !== ""
          ? String(targetTier).trim()
          : "";
      const seedStr = String(targetSeed);

      const matches = rows.filter((row) => {
        if (!row) return false;
        if (normMode && row.mode !== normMode) return false;
        if (normTier && String(row.tier) !== normTier) return false;
        return String(row.seed) === seedStr;
      });

      if (!matches.length) return null;

      matches.sort((a, b) => {
        if (a.score !== b.score) return b.score - a.score;
        const aC = a.correct ? 1 : 0;
        const bC = b.correct ? 1 : 0;
        if (aC !== bC) return bC - aC;
        const aDay = a.final_day > 0 ? a.final_day : Number.POSITIVE_INFINITY;
        const bDay = b.final_day > 0 ? b.final_day : Number.POSITIVE_INFINITY;
        if (aDay !== bDay) return aDay - bDay;
        const aCalls =
          a.tool_calls !== null && a.tool_calls !== undefined
            ? a.tool_calls
            : Number.POSITIVE_INFINITY;
        const bCalls =
          b.tool_calls !== null && b.tool_calls !== undefined
            ? b.tool_calls
            : Number.POSITIVE_INFINITY;
        return aCalls - bCalls;
      });

      return Object.assign({}, matches[0]);
    },
  };
}

function resolveMoleMetadata(summary) {
  const moleObj = summary.mole && typeof summary.mole === "object" ? summary.mole : null;
  const moleStr = typeof summary.mole === "string" ? summary.mole.trim() : "";
  const moleId = String(
    summary.moleId ||
      summary.mole_id ||
      (moleObj && (moleObj.id || moleObj.moleId || moleObj.mole_id)) ||
      moleStr ||
      ""
  ).trim();
  const moleName = String(
    summary.moleName || summary.mole_name || (moleObj && moleObj.name) || ""
  ).trim();
  const moleDept = String(
    summary.moleDept ||
      summary.mole_dept ||
      summary.moleDepartment ||
      (moleObj && (moleObj.dept || moleObj.department)) ||
      ""
  ).trim();
  return { moleId, moleName, moleDept };
}

function formatOutcomeText(rec) {
  if (!rec || typeof rec !== "object") return "Horizon / Abstained";
  if (rec.correct === true) return "Caught Mole";
  if (cleanAccused(rec.accused)) return "Wrong Accusation";
  return "Horizon / Abstained";
}

function buildContenderRow(doc, label, rec, fallbackDay) {
  if (!rec || typeof rec !== "object") return null;
  const scoreVal = toFiniteOrNull(rec.score);
  const dayVal = toFiniteOrNull(
    rec.final_day !== undefined ? rec.final_day : rec.finalDay
  );
  const displayDay = dayVal !== null ? dayVal : fallbackDay;
  const accused = cleanAccused(rec.accused) || "-";
  const outcome = formatOutcomeText(rec);
  const callsVal = toFiniteOrNull(
    rec.tool_calls !== undefined ? rec.tool_calls : rec.toolCalls
  );

  return el(
    "tr",
    withDoc(doc, { dataset: { contender: label } }),
    el("td", withDoc(doc), el("strong", withDoc(doc), label)),
    el("td", withDoc(doc, { class: "mono" }), fmtScore(scoreVal !== null ? scoreVal : 0)),
    el("td", withDoc(doc, { class: "mono" }), "Day " + pad2(displayDay)),
    el("td", withDoc(doc, { class: "mono" }), accused),
    el("td", withDoc(doc), outcome),
    el("td", withDoc(doc, { class: "mono" }), callsVal !== null ? String(callsVal) : "-")
  );
}

function normalizeMoleRivalRows(moleRivals) {
  if (!moleRivals) return { rows: [], debrief: [] };

  const debrief = [];
  const collectDebrief = (raw) => {
    if (typeof raw === "string" && raw.trim()) {
      debrief.push(raw.trim());
    } else if (Array.isArray(raw)) {
      for (const item of raw) {
        if (typeof item === "string" && item.trim()) {
          debrief.push(item.trim());
        } else if (item && typeof item === "object") {
          const txt = item.text || item.bullet || item.note || item.summary;
          if (typeof txt === "string" && txt.trim()) debrief.push(txt.trim());
        }
      }
    }
  };

  if (Array.isArray(moleRivals)) {
    return {
      rows: moleRivals
        .filter((r) => r && typeof r === "object")
        .map((r, idx) => ({
          label: String(r.label || r.name || r.policy || r.id || "rival_" + String(idx + 1)),
          days: toFiniteOrNull(r.daysSurvived ?? r.days_survived ?? r.final_day ?? r.days),
          leaks: toFiniteOrNull(r.leaksLanded ?? r.leaks_landed ?? r.leaks_count ?? r.leaks),
          solverScore: toFiniteOrNull(r.solverScore ?? r.solver_score ?? r.score),
        })),
      debrief,
    };
  }

  if (typeof moleRivals === "object") {
    collectDebrief(moleRivals.tactical_debrief || moleRivals.tacticalDebrief || moleRivals.notes);
    if (Array.isArray(moleRivals.rivals)) {
      const nested = normalizeMoleRivalRows(moleRivals.rivals);
      return { rows: nested.rows, debrief: debrief.concat(nested.debrief) };
    }
    const rows = [];
    for (const [key, val] of Object.entries(moleRivals)) {
      if (RIVAL_SKIP_KEYS.has(key)) continue;
      if (!val || typeof val !== "object" || Array.isArray(val)) continue;
      collectDebrief(val.tactical_debrief || val.tacticalDebrief);
      rows.push({
        label: String(val.label || val.name || val.policy || key),
        days: toFiniteOrNull(val.daysSurvived ?? val.days_survived ?? val.final_day ?? val.days),
        leaks: toFiniteOrNull(val.leaksLanded ?? val.leaks_landed ?? val.leaks_count ?? val.leaks),
        solverScore: toFiniteOrNull(val.solverScore ?? val.solver_score ?? val.score),
      });
    }
    return { rows, debrief };
  }

  return { rows: [], debrief: [] };
}

function renderMoleComparisonBlock(doc, summary) {
  const daysSurvived = toFiniteOrNull(
    summary.daysSurvived !== undefined ? summary.daysSurvived : summary.days_survived
  );
  const leaksLanded = toFiniteOrNull(
    summary.leaksLanded !== undefined ? summary.leaksLanded : summary.leaks_landed
  );

  const statsBar = el(
    "div",
    withDoc(doc, { class: "seed-bar mole-summary-stats" }),
    el(
      "div",
      withDoc(doc, { class: "seed-group" }),
      el("strong", withDoc(doc), "Mole Role Summary"),
      el(
        "span",
        withDoc(doc, { class: "mono" }),
        "Days survived: " + String(daysSurvived !== null ? daysSurvived : 0)
      ),
      el(
        "span",
        withDoc(doc, { class: "mono" }),
        "Leaks landed: " + String(leaksLanded !== null ? leaksLanded : 0)
      )
    )
  );

  const { rows, debrief } = normalizeMoleRivalRows(summary.moleRivals);
  if (!rows.length && !debrief.length) {
    return statsBar;
  }

  const wrapper = el("div", withDoc(doc, { class: "mole-rivals-section" }), statsBar);

  if (rows.length) {
    wrapper.appendChild(
      el(
        "table",
        withDoc(doc, { class: "h2h-table mole-rivals-table" }),
        el(
          "thead",
          withDoc(doc),
          el(
            "tr",
            withDoc(doc),
            el("th", withDoc(doc), "Mole Policy"),
            el("th", withDoc(doc), "Days Survived"),
            el("th", withDoc(doc), "Leaks Landed"),
            el("th", withDoc(doc), "Solver Score")
          )
        ),
        el(
          "tbody",
          withDoc(doc),
          rows.map((r) =>
            el(
              "tr",
              withDoc(doc, { dataset: { moleRival: r.label } }),
              el("td", withDoc(doc, { class: "mono" }), el("strong", withDoc(doc), r.label)),
              el(
                "td",
                withDoc(doc, { class: "mono" }),
                r.days !== null ? String(r.days) : "-"
              ),
              el(
                "td",
                withDoc(doc, { class: "mono" }),
                r.leaks !== null ? String(r.leaks) : "-"
              ),
              el(
                "td",
                withDoc(doc, { class: "mono" }),
                r.solverScore !== null ? fmtScore(r.solverScore) : "-"
              )
            )
          )
        )
      )
    );
  }

  if (debrief.length) {
    wrapper.appendChild(
      el(
        "ul",
        withDoc(doc, { class: "tactical-debrief" }),
        debrief.map((line) => el("li", withDoc(doc), line))
      )
    );
  }

  return wrapper;
}

function lookupCommentaryObject(mapObj, tier, seed) {
  if (!mapObj || typeof mapObj !== "object") return null;
  const compositeKey = String(tier) + ":" + String(seed);
  const seedKey = String(seed);
  const pools = [
    mapObj,
    mapObj.episodes,
    mapObj.entries,
    mapObj.forensics,
    mapObj.seeds,
  ];
  for (const pool of pools) {
    if (!pool || typeof pool !== "object") continue;
    if (pool[compositeKey] && typeof pool[compositeKey] === "object") {
      return pool[compositeKey];
    }
    if (pool[tier] && typeof pool[tier] === "object" && pool[tier][seedKey]) {
      return pool[tier][seedKey];
    }
    if (pool[seedKey] && typeof pool[seedKey] === "object") {
      const hit = pool[seedKey];
      if (!hit.tier || String(hit.tier) === String(tier)) {
        return hit;
      }
    }
  }
  if (
    (mapObj.headline || mapObj.story || mapObj.turning_point || mapObj.verbatim_quote || mapObj.quote) &&
    (mapObj.seed === undefined || String(mapObj.seed) === seedKey) &&
    (mapObj.tier === undefined || String(mapObj.tier) === String(tier))
  ) {
    return mapObj;
  }
  return null;
}

function resolvePostGameCommentary(summary, options) {
  if (!summary || summary.humanDone !== true) return null;
  const g = getGlobalObj();
  const tier = String(summary.tier || "hard");
  const seed = summary.seed;
  if (seed === undefined || seed === null) return null;
  const humanDay = toFiniteOrNull(
    summary.you && summary.you.final_day !== undefined
      ? summary.you.final_day
      : summary.daysSurvived
  );

  const candidates = [
    options && options.commentary,
    options && options.transcriptCommentary,
    g && g.CANARY_TRANSCRIPT_COMMENTARY,
    g && g.CanaryTranscriptCommentary,
  ];

  for (const src of candidates) {
    if (!src) continue;
    try {
      if (typeof src === "function") {
        const direct = src(seed, { tier, seed, humanDone: true });
        if (direct && typeof direct === "object") return direct;
        continue;
      }
      if (typeof src.getPostGameForensics === "function") {
        let res = src.getPostGameForensics(seed, { tier, humanDone: true });
        if (!res) {
          res = src.getPostGameForensics(tier, seed, true);
        }
        if (res && typeof res === "object") return res;
      }
      if (typeof src.getForensics === "function") {
        let res = src.getForensics(tier, seed, true);
        if (!res) {
          res = src.getForensics(seed, { tier, humanDone: true });
        }
        if (res && typeof res === "object") return res;
      }
      if (typeof src.getCommentaryView === "function") {
        const view = src.getCommentaryView({
          seed,
          tier,
          humanDay: humanDay !== null ? humanDay : 21,
          humanDone: true,
        });
        if (view && typeof view === "object") {
          if (view.forensics && typeof view.forensics === "object") return view.forensics;
          if (view.headline || view.story || view.turning_point || view.verbatim_quote || view.quote) {
            return view;
          }
        }
      }
      if (typeof src.getEntry === "function") {
        const entry = src.getEntry(tier, seed, true);
        if (entry && typeof entry === "object") return entry;
      }
      if (typeof src === "object") {
        const found = lookupCommentaryObject(src, tier, seed);
        if (found) return found;
      }
    } catch (_) {}
  }

  return null;
}

function formatActorRef(val) {
  if (!val) return "";
  if (typeof val === "string") return val.trim();
  if (typeof val === "object") {
    const id = val.id || val.employee || "";
    const name = val.name || "";
    if (id && name) return String(id) + " (" + String(name) + ")";
    return String(id || name || "").trim();
  }
  return "";
}

function renderForensicsCard(doc, entry) {
  if (!entry || typeof entry !== "object") return null;

  const headline = String(entry.headline || entry.title || "").trim();
  const story = String(
    entry.story || entry.summary || entry.narrative || entry.body || ""
  ).trim();
  const tag = String(entry.verdict_tag || entry.archetype || "").trim();
  const tpDay = toFiniteOrNull(
    entry.turning_point_day !== undefined ? entry.turning_point_day : entry.turningPointDay
  );
  const tpText = String(entry.turning_point || entry.turningPoint || "").trim();
  const primaryQuote = String(entry.verbatim_quote || entry.quote || "").trim();

  const extraQuotes = [];
  if (Array.isArray(entry.transcript_quotes)) {
    for (const q of entry.transcript_quotes) {
      const qStr =
        typeof q === "string"
          ? q.trim()
          : q && typeof q === "object"
            ? String(q.quote || q.text || "").trim()
            : "";
      if (qStr && qStr !== primaryQuote) {
        const qDay = q && typeof q === "object" ? toFiniteOrNull(q.day) : null;
        extraQuotes.push(qDay !== null ? "[D" + pad2(qDay) + "] " + qStr : qStr);
      }
    }
  }

  const trueMoleStr = formatActorRef(entry.true_mole);
  const decoyStr = formatActorRef(entry.decoy);

  if (!headline && !story && !tpText && !primaryQuote && !extraQuotes.length) {
    return null;
  }

  const bodyNodes = [];
  if (headline) {
    bodyNodes.push(
      el("div", withDoc(doc, { class: "forensics-headline" }), el("strong", withDoc(doc), headline))
    );
  }
  if (story) {
    bodyNodes.push(
      el("p", withDoc(doc, { class: "forensics-story", style: "margin:6px 0;" }), story)
    );
  }
  if (tpText || tpDay !== null) {
    const tpPrefix =
      tpDay !== null ? "Turning point (Day " + pad2(tpDay) + "): " : "Turning point: ";
    bodyNodes.push(
      el(
        "div",
        withDoc(doc, { class: "forensics-turning-point mono" }),
        tpPrefix + (tpText || "recorded")
      )
    );
  }
  if (trueMoleStr || decoyStr) {
    const parts = [];
    if (trueMoleStr) parts.push("True mole: " + trueMoleStr);
    if (decoyStr) parts.push("Decoy: " + decoyStr);
    bodyNodes.push(
      el("div", withDoc(doc, { class: "forensics-cast mono dim" }), parts.join(" | "))
    );
  }
  if (primaryQuote) {
    bodyNodes.push(
      el(
        "blockquote",
        withDoc(doc, { class: "forensics-quote mono", style: "margin:8px 0 0;padding-left:10px;" }),
        primaryQuote
      )
    );
  }
  for (const eq of extraQuotes) {
    bodyNodes.push(
      el(
        "blockquote",
        withDoc(doc, { class: "forensics-quote mono dim", style: "margin:4px 0 0;padding-left:10px;" }),
        eq
      )
    );
  }

  return el(
    "section",
    withDoc(doc, { class: "ai-card forensics-card" }),
    el(
      "div",
      withDoc(doc, { class: "sheet-h" }),
      el("span", withDoc(doc), "Post-Game Transcript Forensics"),
      tag
        ? el("span", withDoc(doc, { class: "first-catch-badge" }), tag)
        : tpDay !== null
          ? el("span", withDoc(doc, { class: "mono dim" }), "Day " + pad2(tpDay))
          : null
    ),
    el("div", withDoc(doc, { class: "rumour-item" }), bodyNodes)
  );
}

function chooseNextSeedAndLabel(mode, currentSeed, options) {
  if (options && options.nextSeed !== undefined && options.nextSeed !== null) {
    const explicit = options.nextSeed;
    return {
      nextSeed: explicit,
      ctaLabel: "Play Seed " + String(explicit),
    };
  }
  const numSeed = toFiniteOrNull(currentSeed);
  if (mode === "solver" || mode === "mole") {
    const nextPublic =
      numSeed !== null && numSeed >= 3000 && numSeed < 9999 ? Math.trunc(numSeed) + 1 : 3000;
    return {
      nextSeed: nextPublic,
      ctaLabel: "Play Seed " + String(nextPublic),
    };
  }
  if (numSeed === 6) {
    return {
      nextSeed: 26,
      ctaLabel: "Play Dramatic Seed 26",
    };
  }
  return {
    nextSeed: 6,
    ctaLabel: "Play Seed 6",
  };
}

export function renderEndSummaryCard(container, summary, options = {}) {
  if (!container) return null;
  const doc = resolveDoc(container, options);
  if (doc) setDocument(doc);
  ensureClassName(container, "arena-end-card");

  if (!summary || typeof summary !== "object" || summary.humanDone !== true) {
    clear(container);
    setHiddenState(container, true);
    return container;
  }

  clear(container);
  setHiddenState(container, false);

  const mode = normalizeMode(summary.mode, "duel");
  const tier =
    typeof summary.tier === "string" && summary.tier.trim()
      ? summary.tier.trim()
      : mode === "solver"
        ? "medium"
        : "hard";
  const seed = summary.seed !== undefined && summary.seed !== null ? summary.seed : "?";
  const { moleId, moleName, moleDept } = resolveMoleMetadata(summary);
  const firstCatch = computeFirstCatchLabel(summary);

  const headerMetaParts = [];
  if (moleName) headerMetaParts.push(moleName);
  if (moleDept) headerMetaParts.push(moleDept);

  container.appendChild(
    el(
      "div",
      withDoc(doc, { class: "seed-bar end-summary-header" }),
      el(
        "div",
        withDoc(doc, { class: "seed-group" }),
        el(
          "strong",
          withDoc(doc),
          "Episode Closed | True Mole: " + (moleId || "revealed")
        ),
        headerMetaParts.length
          ? el("span", withDoc(doc, { class: "dim" }), "(" + headerMetaParts.join(", ") + ")")
          : null,
        el(
          "span",
          withDoc(doc, { class: "mono dim" }),
          "Seed " + String(seed) + " (" + tier + ", " + getModeLabel(mode) + ")"
        )
      ),
      el("span", withDoc(doc, { class: "first-catch-badge" }), "First catch: " + firstCatch)
    )
  );

  const fallbackDay = toFiniteOrNull(summary.daysSurvived) || 0;
  const youRecord =
    summary.you && typeof summary.you === "object"
      ? summary.you
      : mode === "mole"
        ? {
            score: toFiniteOrNull(summary.score) || 0,
            correct: !(summary.solver && summary.solver.correct === true),
            final_day: fallbackDay,
            accused: null,
            tool_calls: toFiniteOrNull(summary.leaksLanded) || 0,
          }
        : null;

  const h2hRows = [];
  const youRow = buildContenderRow(doc, "You", youRecord, fallbackDay);
  if (youRow) h2hRows.push(youRow);

  if (mode === "duel" && summary.gemini && typeof summary.gemini === "object") {
    const gemRow = buildContenderRow(doc, "gemini-4-carbon (OpenCode)", summary.gemini, fallbackDay);
    if (gemRow) h2hRows.push(gemRow);
  }

  if (summary.solver && typeof summary.solver === "object") {
    const solRow = buildContenderRow(doc, "SolverPolicy (Bayesian)", summary.solver, fallbackDay);
    if (solRow) h2hRows.push(solRow);
  }

  container.appendChild(
    el(
      "table",
      withDoc(doc, { class: "h2h-table" }),
      el(
        "thead",
        withDoc(doc),
        el(
          "tr",
          withDoc(doc),
          el("th", withDoc(doc), "Contender"),
          el("th", withDoc(doc), "Score"),
          el("th", withDoc(doc), "Final Day"),
          el("th", withDoc(doc), "Accused"),
          el("th", withDoc(doc), "Outcome"),
          el("th", withDoc(doc), "Calls")
        )
      ),
      el("tbody", withDoc(doc), h2hRows)
    )
  );

  if (mode === "mole") {
    container.appendChild(renderMoleComparisonBlock(doc, summary));
  }

  const forensicsEntry = resolvePostGameCommentary(summary, options);
  const forensicsNode = renderForensicsCard(doc, forensicsEntry);
  if (forensicsNode) {
    container.appendChild(forensicsNode);
  }

  const shareAdapter = options.shareCardAdapter || options.shareCard || null;
  const shareLine = buildCanonicalShareLine(summary, shareAdapter);
  const { nextSeed, ctaLabel } = chooseNextSeedAndLabel(mode, seed, options);

  const copyBtn = el(
    "button",
    withDoc(doc, {
      type: "button",
      class: "ghost copy-share-btn",
      onClick: () => {
        if (typeof options.onCopy === "function") {
          options.onCopy(shareLine, summary);
        } else if (typeof options.onCopyShare === "function") {
          options.onCopyShare(shareLine, summary);
        } else {
          const g = getGlobalObj();
          if (
            g &&
            g.navigator &&
            g.navigator.clipboard &&
            typeof g.navigator.clipboard.writeText === "function"
          ) {
            try {
              const p = g.navigator.clipboard.writeText(shareLine);
              if (p && typeof p.catch === "function") {
                p.catch(() => {});
              }
            } catch (_) {}
          }
        }
        if (copyBtn && copyBtn.dataset) {
          copyBtn.dataset.copied = "true";
        }
      },
    }),
    "Copy Share Card"
  );

  const replayBtn = el(
    "button",
    withDoc(doc, {
      type: "button",
      class: "primary replay-seed-btn",
      dataset: { playSeed: String(nextSeed) },
      onClick: () => {
        if (typeof options.onPlaySeed === "function") {
          options.onPlaySeed(nextSeed, tier, mode);
        }
      },
    }),
    ctaLabel
  );

  container.appendChild(
    el(
      "div",
      withDoc(doc, { class: "share-box" }),
      el("span", withDoc(doc, { id: "arenaShareText", class: "share-line" }), shareLine),
      el("div", withDoc(doc, { class: "seed-group" }), copyBtn, replayBtn)
    )
  );

  return container;
}

export function renderLeaderboardDialog(dialogEl, store, options = {}) {
  if (!dialogEl) return null;
  const doc = resolveDoc(dialogEl, options);
  if (doc) setDocument(doc);
  ensureClassName(dialogEl, "leaderboard-dlg");

  if (options.open === false) {
    clear(dialogEl);
    setHiddenState(dialogEl, true);
    return dialogEl;
  }

  const requestedFilter =
    options.modeFilter !== undefined
      ? options.modeFilter
      : options.filter !== undefined
        ? options.filter
        : dialogEl._activeModeFilter || "all";
  const activeFilter = normalizeFilterMode(requestedFilter);
  dialogEl._activeModeFilter = activeFilter;

  clear(dialogEl);
  setHiddenState(dialogEl, false);

  const entries =
    store && typeof store.list === "function" ? store.list(activeFilter) : [];

  const closeBtn = el(
    "button",
    withDoc(doc, {
      type: "button",
      class: "ghost leaderboard-close-btn",
      onClick: () => {
        if (typeof options.onClose === "function") {
          options.onClose();
        } else {
          setHiddenState(dialogEl, true);
        }
      },
    }),
    "Close"
  );

  const header = el(
    "div",
    withDoc(doc, { class: "sheet-h" }),
    el(
      "span",
      withDoc(doc),
      "Local Session Leaderboard (" + String(entries.length) + ")"
    ),
    closeBtn
  );

  const filterButtons = LEADERBOARD_MODES.map((modeKey) => {
    const selected = activeFilter === modeKey;
    return el(
      "button",
      withDoc(doc, {
        type: "button",
        class: selected ? "seed-pill mode-filter-btn active" : "seed-pill mode-filter-btn",
        "aria-pressed": selected ? "true" : "false",
        dataset: { modeFilter: modeKey },
        onClick: () => {
          dialogEl._activeModeFilter = modeKey;
          if (typeof options.onFilterChange === "function") {
            options.onFilterChange(modeKey);
          }
          renderLeaderboardDialog(
            dialogEl,
            store,
            Object.assign({}, options, { modeFilter: modeKey })
          );
        },
      }),
      getModeLabel(modeKey)
    );
  });

  const filterBar = el(
    "div",
    withDoc(doc, {
      class: "seed-group leaderboard-filters",
      style: "padding:10px 12px;",
    }),
    filterButtons
  );

  const bodyNode = entries.length
    ? el(
        "table",
        withDoc(doc, { class: "h2h-table leaderboard-table" }),
        el(
          "thead",
          withDoc(doc),
          el(
            "tr",
            withDoc(doc),
            el("th", withDoc(doc), "Rank"),
            el("th", withDoc(doc), "Mode"),
            el("th", withDoc(doc), "Seed"),
            el("th", withDoc(doc), "Score"),
            el("th", withDoc(doc), "Final Day"),
            el("th", withDoc(doc), "Outcome"),
            el("th", withDoc(doc), "First Catch")
          )
        ),
        el(
          "tbody",
          withDoc(doc),
          entries.map((entry, idx) => {
            const outcome = entry.correct
              ? "Caught Mole"
              : entry.accused
                ? "Wrong Accusation"
                : "Recorded";
            return el(
              "tr",
              withDoc(doc, {
                dataset: {
                  mode: String(entry.mode || "duel"),
                  seed: String(entry.seed),
                  rank: String(idx + 1),
                },
              }),
              el("td", withDoc(doc, { class: "mono" }), pad2(idx + 1)),
              el("td", withDoc(doc, { class: "mono" }), String(entry.mode || "duel")),
              el(
                "td",
                withDoc(doc, { class: "mono" }),
                String(entry.seed) + " (" + String(entry.tier || "hard") + ")"
              ),
              el("td", withDoc(doc, { class: "mono" }), fmtScore(entry.score)),
              el("td", withDoc(doc, { class: "mono" }), "Day " + pad2(entry.final_day || 0)),
              el("td", withDoc(doc), outcome),
              el(
                "td",
                withDoc(doc, { class: "mono" }),
                String(entry.first_catch || entry.firstCatch || "None")
              )
            );
          })
        )
      )
    : el(
        "div",
        withDoc(doc, { class: "rumour-item leaderboard-empty dim" }),
        "Complete an episode to record local head-to-head scores."
      );

  const clearBtn = el(
    "button",
    withDoc(doc, {
      type: "button",
      class: "ghost leaderboard-clear-btn",
      onClick: () => {
        if (store && typeof store.clear === "function") {
          store.clear();
        }
        if (typeof options.onClear === "function") {
          options.onClear();
        }
        renderLeaderboardDialog(
          dialogEl,
          store,
          Object.assign({}, options, { modeFilter: activeFilter })
        );
      },
    }),
    "Clear"
  );

  const footer = el(
    "div",
    withDoc(doc, {
      class: "leaderboard-footer",
      style: "display:flex;justify-content:space-between;align-items:center;padding:10px 12px;",
    }),
    el(
      "span",
      withDoc(doc, { class: "mono dim" }),
      "Max " + String(LEADERBOARD_MAX_ENTRIES) + " runs stored locally"
    ),
    clearBtn
  );

  dialogEl.appendChild(header);
  dialogEl.appendChild(filterBar);
  dialogEl.appendChild(bodyNode);
  dialogEl.appendChild(footer);
  return dialogEl;
}

const globalRef = getGlobalObj();
if (globalRef && typeof globalRef === "object") {
  globalRef.CanaryArenaUI = Object.assign(globalRef.CanaryArenaUI || {}, {
    LEADERBOARD_STORAGE_KEY,
    createLeaderboardStore,
    renderEndSummaryCard,
    renderLeaderboardDialog,
  });
}
