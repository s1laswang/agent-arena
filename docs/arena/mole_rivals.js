const TIER_FACTS = {
  easy: {
    n_employees: 12,
    n_days: 14,
    p_leak: 0.9,
    leak_window_days: 3,
    delay_choices: [1],
    leak_damage: 0.05,
    canaries_per_day: 1,
    max_variants: 3,
    low_recipient_threshold: 3,
    fingerprint_accuracy: 1.0,
    framing: false,
    careful_mole: false,
  },
  medium: {
    n_employees: 20,
    n_days: 14,
    p_leak: 0.75,
    leak_window_days: 3,
    delay_choices: [1, 2, 3],
    leak_damage: 0.04,
    canaries_per_day: 1,
    max_variants: 3,
    low_recipient_threshold: 3,
    fingerprint_accuracy: 1.0,
    framing: true,
    careful_mole: true,
  },
  hard: {
    n_employees: 40,
    n_days: 21,
    p_leak: 0.65,
    leak_window_days: 3,
    delay_choices: [2, 3],
    leak_damage: 0.05,
    canaries_per_day: 2,
    max_variants: 3,
    low_recipient_threshold: 3,
    fingerprint_accuracy: 0.95,
    framing: true,
    careful_mole: true,
  },
};

const RIVAL_PROFILES = [
  {
    strategy: "default_v0",
    label: "Default Mole (Baseline)",
    summary: "Picks eligible documents at random with careful-mole weighting and adds no peer framing.",
  },
  {
    strategy: "patient_wide_v1",
    label: "Patient Wide v1 (Dual-Tier Shield)",
    summary: "Routes early trap-heavy days into wide-recipient documents and frames restricted or random peers.",
  },
  {
    strategy: "frontier_synthesis_v14",
    label: "Frontier Synthesis v1.4 (Benchmark Rival)",
    summary: "Combines early low-recipient trap deflection, wide-doc preference, days 5-8 leak pacing, and non-decoy peer framing.",
  },
];

const initializedRuntimes = new WeakMap();
let cachedPyodide = null;

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function validateTier(tier) {
  const clean = typeof tier === "string" ? tier.trim() : "";
  if (!Object.prototype.hasOwnProperty.call(TIER_FACTS, clean)) {
    throw new Error(`unknown tier "${String(tier)}"; expected easy, medium, or hard`);
  }
  return clean;
}

function validateSeed(seed) {
  if (typeof seed === "boolean" || seed === null || seed === undefined) {
    throw new Error("seed must be an integer public dev seed in 3000..9999");
  }
  let parsed;
  if (typeof seed === "number") {
    if (!Number.isInteger(seed)) {
      throw new Error("seed must be an integer public dev seed in 3000..9999");
    }
    parsed = seed;
  } else if (typeof seed === "string") {
    const trimmed = seed.trim();
    if (!trimmed || !new RegExp("^-?\\d+$").test(trimmed)) {
      throw new Error("seed must be an integer public dev seed in 3000..9999");
    }
    parsed = Number(trimmed);
    if (!Number.isSafeInteger(parsed) || String(parsed) !== trimmed) {
      throw new Error("seed must be an integer public dev seed in 3000..9999");
    }
  } else {
    throw new Error("seed must be an integer public dev seed in 3000..9999");
  }
  if (parsed < 3000 || parsed > 9999) {
    throw new Error(`seed ${parsed} is outside public dev seeds 3000..9999 and cannot be inspected`);
  }
  return parsed;
}

function parseSummaryObject(summary) {
  if (typeof summary === "string") {
    let parsed;
    try {
      parsed = JSON.parse(summary);
    } catch (_err) {
      throw new Error("humanMoleSummary is not valid JSON");
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("humanMoleSummary JSON must decode to an object");
    }
    return parsed;
  }
  if (!summary || typeof summary !== "object" || Array.isArray(summary)) {
    throw new Error("humanMoleSummary must be an object or JSON string");
  }
  return { ...summary };
}

function isHumanUnfinished(summaryObj) {
  const doneFlags = ["human_done", "humanDone", "done", "episode_over", "episodeOver"];
  for (const key of doneFlags) {
    if (key in summaryObj && !Boolean(summaryObj[key])) {
      return true;
    }
  }
  const status = String(summaryObj.status ?? "").trim().toLowerCase();
  if (["in_progress", "active", "running", "open", "pending"].includes(status)) {
    return true;
  }
  return false;
}

function delayText(delays) {
  const lo = Math.min(...delays);
  const hi = Math.max(...delays);
  return lo === hi ? `${lo} day` : `${lo}-${hi} days`;
}

function buildStaticBriefing(tier = "medium") {
  const cleanTier = validateTier(tier);
  const p = TIER_FACTS[cleanTier];
  const delayStr = delayText(p.delay_choices);
  return {
    tier: cleanTier,
    tier_facts: {
      ...p,
      delay_choices: [...p.delay_choices],
    },
    headline: `Mode 3 Tactical Briefing (${cleanTier} tier: ${p.n_employees} staff, ${p.n_days} days, up to ${p.canaries_per_day} canary trap(s)/day across ${p.max_variants} variants).`,
    rules: [
      {
        id: "recipient_width",
        title: "Recipient-set width controls Bayesian exposure",
        detail: `Every surfaced leak eliminates staff outside its recipient list. Wide department documents across ${p.n_employees} employees dilute likelihood across many holders, whereas narrow documents isolate you rapidly.`,
      },
      {
        id: "canary_traps",
        title: `Avoid 2-3 person surgical canary traps (up to ${p.max_variants} variants)`,
        detail: `Security splits suspects into up to ${p.max_variants} variant labels (A/B/C). Frontier investigators plant narrow <= ${p.low_recipient_threshold} recipient traps early; leaking one collapses the suspect pool in a single surface event.`,
      },
      {
        id: "freshness_and_delay",
        title: `${p.leak_window_days}-day freshness window and ${delayStr} surfacing lag`,
        detail: `You can only leak documents received within the last ${p.leak_window_days} days, and leaked items surface ${delayStr} later. Yesterday's risky leak detonates days later alongside newer traps.`,
      },
      {
        id: "framing_vs_canary",
        title: "Peer-framing noise distracts heuristics, not Bayesian canary math",
        detail: "Non-decoy peer framing shifts heuristic and LLM tie-breaks (+0.086 counterfactual EV drop, while angry decoys were dismissed in 100% of 159 frontier runs), whereas SolverPolicy downweights behavioral logs (temper=0.6) and hunts canary variants.",
      },
    ],
    rival_profiles: RIVAL_PROFILES.map((item) => ({ ...item })),
  };
}

function isPyodideLike(obj) {
  return Boolean(obj && typeof obj === "object" && typeof obj.runPython === "function");
}

function resolveCachedPyodide() {
  if (isPyodideLike(cachedPyodide)) {
    return cachedPyodide;
  }
  if (typeof globalThis !== "undefined") {
    if (isPyodideLike(globalThis.__pyodide)) {
      return globalThis.__pyodide;
    }
    if (isPyodideLike(globalThis.pyodide)) {
      return globalThis.pyodide;
    }
    if (isPyodideLike(globalThis.__canaryPyodide)) {
      return globalThis.__canaryPyodide;
    }
  }
  if (typeof window !== "undefined") {
    if (isPyodideLike(window.__pyodide)) {
      return window.__pyodide;
    }
    if (isPyodideLike(window.pyodide)) {
      return window.pyodide;
    }
    if (isPyodideLike(window.__canaryPyodide)) {
      return window.__canaryPyodide;
    }
  }
  return null;
}

function writePyodideFile(pyodide, path, text) {
  if (!pyodide.FS || typeof pyodide.FS.writeFile !== "function") {
    return;
  }
  const idx = path.lastIndexOf("/");
  if (idx > 0 && typeof pyodide.FS.mkdirTree === "function") {
    pyodide.FS.mkdirTree(path.slice(0, idx));
  }
  pyodide.FS.writeFile(path, text);
}

async function resolvePythonSource(pythonSourceOrUrl) {
  if (typeof pythonSourceOrUrl === "string") {
    if (pythonSourceOrUrl.includes("\n") || pythonSourceOrUrl.includes("def get_mole_briefing")) {
      return pythonSourceOrUrl;
    }
    if (typeof fetch === "function") {
      try {
        const res = await fetch(pythonSourceOrUrl);
        if (res && res.ok) {
          return await res.text();
        }
      } catch (_err) {
        void 0;
      }
    }
    const fsMod = await import("fs");
    return fsMod.readFileSync(pythonSourceOrUrl, "utf8");
  }
  if (typeof fetch === "function") {
    const res = await fetch("mole_rivals.py");
    if (!res || !res.ok) {
      throw new Error("failed to fetch mole_rivals.py");
    }
    return await res.text();
  }
  throw new Error("pythonSourceOrUrl is required when fetch is unavailable");
}

async function initMoleRivals(pyodide, pythonSourceOrUrl) {
  if (!isPyodideLike(pyodide)) {
    throw new Error("initMoleRivals requires a Pyodide runtime with runPython");
  }
  cachedPyodide = pyodide;
  if (initializedRuntimes.get(pyodide)) {
    return pyodide;
  }
  if (pythonSourceOrUrl === undefined || pythonSourceOrUrl === null) {
    try {
      const alreadyLoaded = pyodide.runPython(
        "import importlib.util, sys\n" +
          "bool('mole_rivals' in sys.modules or importlib.util.find_spec('mole_rivals') or importlib.util.find_spec('docs.arena.mole_rivals'))"
      );
      if (alreadyLoaded === true || alreadyLoaded === "True") {
        pyodide.runPython(
          "import importlib, sys\n" +
            "if 'mole_rivals' not in sys.modules:\n" +
            "    try:\n" +
            "        import mole_rivals\n" +
            "    except ImportError:\n" +
            "        sys.modules['mole_rivals'] = importlib.import_module('docs.arena.mole_rivals')"
        );
        initializedRuntimes.set(pyodide, true);
        return pyodide;
      }
    } catch (_err) {
      void 0;
    }
  }
  const source = await resolvePythonSource(pythonSourceOrUrl);
  writePyodideFile(pyodide, "/home/pyodide/mole_rivals.py", source);
  writePyodideFile(pyodide, "/home/pyodide/docs/arena/mole_rivals.py", source);
  const encodedSource = JSON.stringify(source);
  pyodide.runPython(
    "import sys, types\n" +
      "if '/home/pyodide' not in sys.path:\n" +
      "    sys.path.insert(0, '/home/pyodide')\n" +
      `_src = ${encodedSource}\n` +
      "_mod = types.ModuleType('mole_rivals')\n" +
      "_mod.__file__ = '/home/pyodide/docs/arena/mole_rivals.py'\n" +
      "sys.modules['mole_rivals'] = _mod\n" +
      "exec(compile(_src, _mod.__file__, 'exec'), _mod.__dict__)"
  );
  initializedRuntimes.set(pyodide, true);
  return pyodide;
}

function getMoleBriefing(pyodideOrTier = "medium", maybeTier = "medium") {
  if (isPyodideLike(pyodideOrTier)) {
    cachedPyodide = pyodideOrTier;
    const cleanTier = validateTier(maybeTier ?? "medium");
    if (initializedRuntimes.get(pyodideOrTier)) {
      const raw = pyodideOrTier.runPython(
        `import mole_rivals; mole_rivals.get_mole_briefing_json(${JSON.stringify(cleanTier)})`
      );
      return JSON.parse(String(raw));
    }
    return buildStaticBriefing(cleanTier);
  }
  const tierArg =
    typeof pyodideOrTier === "string"
      ? pyodideOrTier
      : typeof maybeTier === "string"
        ? maybeTier
        : "medium";
  return buildStaticBriefing(tierArg);
}

function buildRivalRowJs(label, policy, data) {
  const days = Number(data.days_survived ?? data.daysSurvived ?? 0);
  const leaks = Number(data.leaks_landed ?? data.leaksLanded ?? 0);
  const score = Number(data.solver_score ?? data.solverScore ?? 0);
  return {
    label: String(label),
    policy: String(policy),
    days_survived: days,
    daysSurvived: days,
    leaks_landed: leaks,
    leaksLanded: leaks,
    solver_score: score,
    solverScore: score,
    caught: Boolean(data.caught),
  };
}

function ensureComparisonContract(result) {
  if (!result || typeof result !== "object") {
    return result;
  }
  if (result.sealed || result.status === "[SEALED]") {
    return result;
  }
  const out = { ...result };
  const debrief = Array.isArray(out.tactical_debrief)
    ? out.tactical_debrief.map((x) => String(x))
    : Array.isArray(out.tacticalDebrief)
      ? out.tacticalDebrief.map((x) => String(x))
      : [];
  out.tactical_debrief = debrief;
  out.tacticalDebrief = [...debrief];
  if (Array.isArray(out.rivals)) {
    out.rivals = out.rivals
      .filter((r) => r && typeof r === "object")
      .map((r, idx) =>
        buildRivalRowJs(
          r.label || r.policy || `rival_${idx + 1}`,
          r.policy || r.strategy || r.label || `rival_${idx + 1}`,
          r
        )
      );
  } else {
    const pairs = [
      ["You (Human Mole)", "human", out.human],
      ["Default Mole (default_v0)", "default_v0", out.default_mole],
      ["Patient Wide v1 (patient_wide_v1)", "patient_wide_v1", out.patient_mole],
      ["Frontier Synthesis v1.4", "frontier_synthesis_v14", out.synthesis_mole],
    ];
    out.rivals = pairs
      .filter(([, , row]) => row && typeof row === "object")
      .map(([label, policy, row]) => buildRivalRowJs(label, policy, row));
  }
  return out;
}

function unpackCompareArgs(argCount, firstArg, secondArg, thirdArg, fourthArg) {
  if (isPyodideLike(firstArg) || argCount >= 4) {
    if (isPyodideLike(firstArg)) {
      cachedPyodide = firstArg;
    }
    return {
      pyodide: firstArg,
      tier: secondArg,
      seed: thirdArg,
      humanMoleSummary: fourthArg,
    };
  }
  return {
    pyodide: resolveCachedPyodide(),
    tier: firstArg,
    seed: secondArg,
    humanMoleSummary: thirdArg,
  };
}

function compareHumanMole(firstArg, secondArg, thirdArg, fourthArg) {
  const { pyodide, tier, seed, humanMoleSummary } = unpackCompareArgs(
    arguments.length,
    firstArg,
    secondArg,
    thirdArg,
    fourthArg
  );
  const cleanTier = validateTier(tier);
  const cleanSeed = validateSeed(seed);
  const summaryObj = parseSummaryObject(humanMoleSummary);
  if (isHumanUnfinished(summaryObj)) {
    throw new Error("human episode is not finished yet");
  }
  if (!isPyodideLike(pyodide)) {
    throw new Error("compareHumanMole requires an initialized Pyodide runtime");
  }
  const summaryJsonLiteral = JSON.stringify(JSON.stringify(summaryObj));
  const raw = pyodide.runPython(
    "import importlib, sys\n" +
      "if 'mole_rivals' in sys.modules:\n" +
      "    _mr = sys.modules['mole_rivals']\n" +
      "else:\n" +
      "    try:\n" +
      "        import mole_rivals as _mr\n" +
      "    except ImportError:\n" +
      "        _mr = importlib.import_module('docs.arena.mole_rivals')\n" +
      `_mr.compare_human_mole_json(${JSON.stringify(cleanTier)}, ${cleanSeed}, ${summaryJsonLiteral})`
  );
  return ensureComparisonContract(JSON.parse(String(raw)));
}

function safeCompareHumanMole(firstArg, secondArg, thirdArg, fourthArg) {
  const { pyodide, tier, seed, humanMoleSummary } = unpackCompareArgs(
    arguments.length,
    firstArg,
    secondArg,
    thirdArg,
    fourthArg
  );
  const cleanTier = validateTier(tier);
  const cleanSeed = validateSeed(seed);
  const summaryObj = parseSummaryObject(humanMoleSummary);
  if (isHumanUnfinished(summaryObj)) {
    return { sealed: true, status: "[SEALED]" };
  }
  return compareHumanMole(pyodide, cleanTier, cleanSeed, summaryObj);
}

function formatScore(score) {
  const num = Number(score ?? 0);
  if (!Number.isFinite(num) || Math.abs(num) < 0.005) {
    return "0.00";
  }
  const sign = num > 0 ? "+" : "-";
  return `${sign}${Math.abs(num).toFixed(2)}`;
}

function resolveDoc(docOrOptions) {
  if (docOrOptions && typeof docOrOptions.createElement === "function") {
    return docOrOptions;
  }
  if (
    docOrOptions &&
    typeof docOrOptions === "object" &&
    docOrOptions.document &&
    typeof docOrOptions.document.createElement === "function"
  ) {
    return docOrOptions.document;
  }
  if (
    typeof globalThis !== "undefined" &&
    globalThis.document &&
    typeof globalThis.document.createElement === "function"
  ) {
    return globalThis.document;
  }
  throw new Error("DOM document with createElement is required");
}

function toKebabAttr(name) {
  let out = "";
  for (let i = 0; i < name.length; i += 1) {
    const ch = name[i];
    if (ch >= "A" && ch <= "Z") {
      out += "-" + ch.toLowerCase();
    } else {
      out += ch;
    }
  }
  return out;
}

function clearDomNode(node) {
  if (!node) {
    return;
  }
  if (typeof node.replaceChildren === "function") {
    node.replaceChildren();
    return;
  }
  while (node.firstChild) {
    node.removeChild(node.firstChild);
  }
}

function appendDomChild(doc, parent, child) {
  if (child === null || child === undefined || child === false) {
    return;
  }
  if (Array.isArray(child)) {
    for (const item of child) {
      appendDomChild(doc, parent, item);
    }
    return;
  }
  if (typeof child === "object" && ("nodeType" in child || typeof child.appendChild === "function")) {
    parent.appendChild(child);
    return;
  }
  parent.appendChild(doc.createTextNode(String(child)));
}

function domEl(doc, tag, attrs, ...children) {
  const elem = doc.createElement(tag);
  if (attrs && typeof attrs === "object") {
    for (const [key, val] of Object.entries(attrs)) {
      if (val === null || val === undefined || val === false) {
        continue;
      }
      if (key === "class" || key === "className") {
        elem.className = String(val);
        if (typeof elem.setAttribute === "function") {
          elem.setAttribute("class", String(val));
        }
      } else if (key === "dataset" && typeof val === "object") {
        for (const [dKey, dVal] of Object.entries(val)) {
          if (dVal === null || dVal === undefined) {
            continue;
          }
          if (elem.dataset && typeof elem.dataset === "object") {
            elem.dataset[dKey] = String(dVal);
          }
          if (typeof elem.setAttribute === "function") {
            elem.setAttribute(`data-${toKebabAttr(dKey)}`, String(dVal));
          }
        }
      } else if (key === "style" && typeof val === "string") {
        if (elem.style && typeof elem.style === "object") {
          elem.style.cssText = val;
        }
        if (typeof elem.setAttribute === "function") {
          elem.setAttribute("style", val);
        }
      } else if (key.startsWith("on") && typeof val === "function") {
        if (typeof elem.addEventListener === "function") {
          elem.addEventListener(key.slice(2).toLowerCase(), val);
        }
      } else if (val === true) {
        const attrVal = key.startsWith("aria-") ? "true" : "";
        if (typeof elem.setAttribute === "function") {
          elem.setAttribute(key, attrVal);
        }
      } else if (typeof elem.setAttribute === "function") {
        elem.setAttribute(key, String(val));
      }
    }
  }
  for (const child of children) {
    appendDomChild(doc, elem, child);
  }
  return elem;
}

function renderMoleDebriefDom(comparison, docOrOptions) {
  const doc = resolveDoc(docOrOptions);
  const onCopyText =
    docOrOptions && typeof docOrOptions === "object" && typeof docOrOptions.onCopyText === "function"
      ? docOrOptions.onCopyText
      : null;

  if (!comparison || typeof comparison !== "object") {
    return domEl(
      doc,
      "section",
      {
        class: "arena-end-card mole-panel mole-rivals-panel mole-rivals-empty",
        "aria-label": "Mode 3 Benchmark Rivals and Forensics Coach",
      },
      domEl(doc, "p", {}, "No debrief available.")
    );
  }

  if (comparison.sealed || comparison.status === "[SEALED]") {
    return domEl(
      doc,
      "section",
      {
        class: "arena-end-card mole-panel mole-rivals-panel mole-rivals-sealed",
        "aria-live": "polite",
        "aria-label": "Sealed Mode 3 Benchmark Rivals",
      },
      domEl(
        doc,
        "div",
        { class: "leak-picker-card" },
        domEl(doc, "strong", { class: "sealed-badge" }, "[SEALED]"),
        domEl(doc, "span", {}, "Finish the episode to unlock benchmark rival forensics.")
      )
    );
  }

  const tier = String(comparison.tier ?? "medium");
  const seed = String(comparison.seed ?? "");
  const rows = [
    { label: "You (Human Mole)", data: comparison.human },
    { label: "Default Mole (default_v0)", data: comparison.default_mole },
    { label: "Patient Wide v1 (patient_wide_v1)", data: comparison.patient_mole },
    { label: "Frontier Synthesis v1.4", data: comparison.synthesis_mole },
  ].filter((entry) => entry.data && typeof entry.data === "object");

  const trNodes = rows.map(({ label, data }) => {
    const outcome = data.caught ? "Caught" : "Evaded";
    return domEl(
      doc,
      "tr",
      {},
      domEl(doc, "td", {}, domEl(doc, "strong", {}, label)),
      domEl(doc, "td", { class: "mono" }, String(data.days_survived ?? 0)),
      domEl(doc, "td", { class: "mono" }, String(data.leaks_landed ?? 0)),
      domEl(doc, "td", { class: "mono" }, formatScore(data.solver_score)),
      domEl(doc, "td", {}, outcome)
    );
  });

  const headerChildren = [
    domEl(doc, "h3", {}, `Benchmark Rivals and Forensics Coach (${tier} - seed ${seed})`),
  ];
  if (onCopyText) {
    headerChildren.push(
      domEl(
        doc,
        "button",
        {
          type: "button",
          class: "ghost",
          onClick: () => onCopyText(formatMoleDebriefText(comparison)),
        },
        "Copy Debrief"
      )
    );
  }

  const debriefList = Array.isArray(comparison.tactical_debrief)
    ? comparison.tactical_debrief
    : Array.isArray(comparison.tacticalDebrief)
      ? comparison.tacticalDebrief
      : [];
  const debriefItems = debriefList.map((line) =>
    domEl(doc, "li", { class: "leak-picker-card" }, String(line))
  );

  return domEl(
    doc,
    "section",
    {
      class: "arena-end-card mole-panel mole-rivals-panel",
      dataset: { tier, seed },
      "aria-label": "Mode 3 Benchmark Rivals and Forensics Coach",
      style: "margin-top: 8px",
    },
    domEl(doc, "header", { class: "mole-rivals-header" }, headerChildren),
    domEl(
      doc,
      "table",
      { class: "h2h-table mole-rivals-table" },
      domEl(
        doc,
        "thead",
        {},
        domEl(
          doc,
          "tr",
          {},
          domEl(doc, "th", {}, "Mole Policy"),
          domEl(doc, "th", {}, "Days Survived"),
          domEl(doc, "th", {}, "Leaks Landed"),
          domEl(doc, "th", {}, "Solver Score"),
          domEl(doc, "th", {}, "Outcome")
        )
      ),
      domEl(doc, "tbody", {}, trNodes)
    ),
    domEl(
      doc,
      "div",
      { class: "mole-rivals-coach" },
      domEl(doc, "h4", {}, "Post-Game Tactical Debrief"),
      domEl(doc, "ul", {}, debriefItems)
    )
  );
}

function renderMoleBriefingDom(briefingOrTier = "medium", docOrOptions) {
  const doc = resolveDoc(docOrOptions);
  const briefing =
    typeof briefingOrTier === "string" || !briefingOrTier
      ? buildStaticBriefing(typeof briefingOrTier === "string" ? briefingOrTier : "medium")
      : briefingOrTier;
  const rules = Array.isArray(briefing.rules) ? briefing.rules : [];
  const profiles = Array.isArray(briefing.rival_profiles) ? briefing.rival_profiles : [];

  return domEl(
    doc,
    "section",
    {
      class: "mole-panel mole-rivals-briefing",
      dataset: { tier: String(briefing.tier ?? "medium") },
      "aria-label": "Mode 3 Tactical Briefing",
    },
    domEl(doc, "h3", {}, String(briefing.headline ?? "Mode 3 Tactical Briefing")),
    domEl(
      doc,
      "div",
      { class: "mole-briefing-rules" },
      rules.map((rule) =>
        domEl(
          doc,
          "div",
          { class: "leak-picker-card", dataset: { ruleId: String(rule.id ?? "") } },
          domEl(doc, "strong", {}, String(rule.title ?? "")),
          domEl(doc, "p", {}, String(rule.detail ?? ""))
        )
      )
    ),
    domEl(
      doc,
      "div",
      { class: "mole-briefing-rivals" },
      profiles.map((prof) =>
        domEl(
          doc,
          "div",
          { class: "leak-picker-card", dataset: { strategy: String(prof.strategy ?? "") } },
          domEl(doc, "strong", {}, String(prof.label ?? prof.strategy ?? "")),
          domEl(doc, "span", {}, String(prof.summary ?? ""))
        )
      )
    )
  );
}

function mountMoleDebrief(container, comparison, docOrOptions) {
  if (!container) {
    throw new Error("mountMoleDebrief requires a target container node");
  }
  const doc = resolveDoc(docOrOptions ?? container.ownerDocument);
  clearDomNode(container);
  const panel = renderMoleDebriefDom(comparison, docOrOptions ?? doc);
  container.appendChild(panel);
  return panel;
}

function renderMoleDebriefHtml(comparison) {
  if (!comparison || typeof comparison !== "object") {
    return '<section class="arena-end-card mole-panel mole-rivals-panel mole-rivals-empty"><p>No debrief available.</p></section>';
  }
  if (comparison.sealed || comparison.status === "[SEALED]") {
    return '<section class="arena-end-card mole-panel mole-rivals-panel mole-rivals-sealed"><div class="leak-picker-card"><strong class="sealed-badge">[SEALED]</strong> <span>Finish the episode to unlock benchmark rival forensics.</span></div></section>';
  }

  const tier = escapeHtml(comparison.tier ?? "medium");
  const seed = escapeHtml(comparison.seed ?? "");
  const rows = [
    { label: "You (Human Mole)", data: comparison.human },
    { label: "Default Mole (default_v0)", data: comparison.default_mole },
    { label: "Patient Wide v1 (patient_wide_v1)", data: comparison.patient_mole },
    { label: "Frontier Synthesis v1.4", data: comparison.synthesis_mole },
  ].filter((entry) => entry.data && typeof entry.data === "object");

  const trs = rows
    .map(({ label, data }) => {
      const outcome = data.caught ? "Caught" : "Evaded";
      const days = escapeHtml(data.days_survived ?? 0);
      const leaks = escapeHtml(data.leaks_landed ?? 0);
      const score = escapeHtml(formatScore(data.solver_score));
      return (
        "<tr>" +
        `<td><strong>${escapeHtml(label)}</strong></td>` +
        `<td>${days}</td>` +
        `<td>${leaks}</td>` +
        `<td>${score}</td>` +
        `<td>${escapeHtml(outcome)}</td>` +
        "</tr>"
      );
    })
    .join("");

  const debriefList = Array.isArray(comparison.tactical_debrief)
    ? comparison.tactical_debrief
    : Array.isArray(comparison.tacticalDebrief)
      ? comparison.tacticalDebrief
      : [];
  const bullets = debriefList
    .map((line) => `<li class="leak-picker-card">${escapeHtml(line)}</li>`)
    .join("");

  return (
    `<section class="arena-end-card mole-panel mole-rivals-panel" data-tier="${tier}" data-seed="${seed}">` +
    `<header class="mole-rivals-header"><h3>Benchmark Rivals and Forensics Coach (${tier} - seed ${seed})</h3></header>` +
    '<table class="h2h-table mole-rivals-table">' +
    "<thead><tr><th>Mole Policy</th><th>Days Survived</th><th>Leaks Landed</th><th>Solver Score</th><th>Outcome</th></tr></thead>" +
    `<tbody>${trs}</tbody>` +
    "</table>" +
    `<div class="mole-rivals-coach"><h4>Post-Game Tactical Debrief</h4><ul>${bullets}</ul></div>` +
    "</section>"
  );
}

function formatMoleDebriefText(comparison) {
  if (!comparison || typeof comparison !== "object") {
    return "No debrief available.";
  }
  if (comparison.sealed || comparison.status === "[SEALED]") {
    return "[SEALED] Finish the episode to unlock benchmark rival forensics.";
  }
  const lines = [
    `Mode 3 Benchmark Rivals (${String(comparison.tier ?? "medium")}, seed ${String(comparison.seed ?? "")})`,
  ];
  const entries = [
    ["You", comparison.human],
    ["default_v0", comparison.default_mole],
    ["patient_wide_v1", comparison.patient_mole],
    ["frontier_synthesis_v14", comparison.synthesis_mole],
  ];
  for (const [label, row] of entries) {
    if (!row || typeof row !== "object") {
      continue;
    }
    const status = row.caught ? "caught" : "evaded";
    lines.push(
      `  ${label}: ${row.days_survived}d survived | ${row.leaks_landed} leak(s) | solver ${formatScore(row.solver_score)} | ${status}`
    );
  }
  const debriefList = Array.isArray(comparison.tactical_debrief)
    ? comparison.tactical_debrief
    : Array.isArray(comparison.tacticalDebrief)
      ? comparison.tacticalDebrief
      : [];
  if (debriefList.length > 0) {
    lines.push("Tactical Debrief:");
    for (const item of debriefList) {
      lines.push(`  - ${String(item)}`);
    }
  }
  return lines.join("\n");
}

const api = {
  RIVAL_PROFILES,
  TIER_FACTS,
  compareHumanMole,
  escapeHtml,
  formatMoleDebriefText,
  getMoleBriefing,
  initMoleRivals,
  mountMoleDebrief,
  renderMoleBriefingDom,
  renderMoleDebriefDom,
  renderMoleDebriefHtml,
  safeCompareHumanMole,
  validateSeed,
};

const CanaryMoleRivals = api;

if (typeof globalThis !== "undefined") {
  globalThis.CanaryMoleRivals = api;
}
if (typeof window !== "undefined") {
  window.CanaryMoleRivals = api;
}

export {
  CanaryMoleRivals,
  RIVAL_PROFILES,
  TIER_FACTS,
  compareHumanMole,
  escapeHtml,
  formatMoleDebriefText,
  getMoleBriefing,
  initMoleRivals,
  mountMoleDebrief,
  renderMoleBriefingDom,
  renderMoleDebriefDom,
  renderMoleDebriefHtml,
  safeCompareHumanMole,
  validateSeed,
};
export default api;
