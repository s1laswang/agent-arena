(function (root) {
  "use strict";

  var LADDER_LEVELS = ["minimal", "low", "medium", "high"];

  var LEVEL_ALIASES = {
    min: "minimal",
    minimal: "minimal",
    none: "minimal",
    low: "low",
    lo: "low",
    med: "medium",
    medium: "medium",
    mid: "medium",
    high: "high",
    hi: "high",
    xhigh: "xhigh",
    x_high: "xhigh",
    "x-high": "xhigh",
    extra_high: "xhigh",
    extrahigh: "xhigh",
    max: "xhigh"
  };

  var HIGHLIGHTED_FAILURE_TAGS = [
    "premature_accusation",
    "uninformative_canary",
    "ignored_delay",
    "over_restriction"
  ];

  var HIGHLIGHTED_TAG_DESCRIPTIONS = {
    premature_accusation: "Accused before evidence cleared break-even certainty",
    uninformative_canary: "Planted canary with poor suspect partitioning",
    ignored_delay: "Delayed past decisive evidence or acted while pending leak was in flight",
    over_restriction: "Restricted an employee unlikely to be the mole"
  };

  var BUILTIN_FAILURE_MODES = {
    premature_accusation: {
      name: "Premature Accusation",
      description: HIGHLIGHTED_TAG_DESCRIPTIONS.premature_accusation,
      decision: "commit_timing"
    },
    uninformative_canary: {
      name: "Uninformative Canary",
      description: HIGHLIGHTED_TAG_DESCRIPTIONS.uninformative_canary,
      decision: "canary_design"
    },
    ignored_delay: {
      name: "Ignored Leak Delay",
      description: HIGHLIGHTED_TAG_DESCRIPTIONS.ignored_delay,
      decision: "commit_timing"
    },
    over_restriction: {
      name: "Over-Restriction",
      description: HIGHLIGHTED_TAG_DESCRIPTIONS.over_restriction,
      decision: "restriction"
    },
    budget_waste: {
      name: "Action Budget Waste",
      description: "Repeated or failed call that spent daily quota without new information",
      decision: "budget_use"
    },
    decoy_chase: {
      name: "Decoy Chase",
      description: "Chased noisy surface cues from a framed innocent decoy",
      decision: "accusation_target"
    },
    no_accusation: {
      name: "No Accusation",
      description: "Episode ended without committing an accusation",
      decision: "commit_timing"
    }
  };

  var QUOTE_KIND_PRIORITY = {
    transcript: 1,
    thought: 2,
    thought_quote: 2,
    reasoning: 2,
    replay_showcase: 3,
    validation_context: 4,
    atlas_blind: 5,
    atlas: 6,
    atlas_v2: 7,
    episode_step: 8,
    analyst_summary: 9
  };

  var ESCAPE_MAP = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  };

  function isObject(val) {
    return val !== null && typeof val === "object" && !Array.isArray(val);
  }

  function isDomElement(val) {
    if (!isObject(val)) {
      return false;
    }
    if (typeof val.nodeType === "number" && val.nodeType === 1) {
      return true;
    }
    return (
      (typeof val.appendChild === "function" || typeof val.replaceChildren === "function") &&
      !("tier" in val) &&
      !("judgeChoice" in val) &&
      !("levelComparisons" in val) &&
      !("thinking_levels" in val) &&
      !("verdictLabel" in val)
    );
  }

  function getHostWindow(fallbackRoot) {
    if (typeof window !== "undefined" && window) {
      return window;
    }
    if (typeof globalThis !== "undefined" && globalThis && globalThis.window) {
      return globalThis.window;
    }
    if (typeof globalThis !== "undefined" && globalThis) {
      return globalThis;
    }
    return fallbackRoot || {};
  }

  function isUnicodeDashCode(code) {
    return (
      (code >= 0x2010 && code <= 0x2015) ||
      code === 0x2212 ||
      code === 0xfe58 ||
      code === 0xfe63 ||
      code === 0xff0d
    );
  }

  function sanitizeDashes(value) {
    if (value === null || value === undefined) {
      return "";
    }
    var str = String(value);
    var out = "";
    for (var i = 0; i < str.length; i += 1) {
      var code = str.charCodeAt(i);
      out += isUnicodeDashCode(code) ? "-" : str.charAt(i);
    }
    return out;
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) {
      return "";
    }
    var str = String(value);
    var out = "";
    for (var i = 0; i < str.length; i += 1) {
      var ch = str.charAt(i);
      out += ESCAPE_MAP[ch] || ch;
    }
    return out;
  }

  function safeSlug(value) {
    if (value === null || value === undefined) {
      return "none";
    }
    var raw = String(value).trim().toLowerCase();
    var out = "";
    for (var i = 0; i < raw.length; i += 1) {
      var code = raw.charCodeAt(i);
      var isAlpha = code >= 97 && code <= 122;
      var isDigit = code >= 48 && code <= 57;
      var ch = raw.charAt(i);
      if (isAlpha || isDigit || ch === "_" || ch === "-") {
        out += ch;
      }
    }
    return out || "custom";
  }

  function humanizeTag(tag) {
    var clean = sanitizeDashes(tag).trim();
    if (!clean) {
      return "Unknown Failure";
    }
    var words = clean.split("_");
    var out = [];
    for (var i = 0; i < words.length; i += 1) {
      var w = words[i].trim();
      if (w) {
        out.push(w.charAt(0).toUpperCase() + w.slice(1));
      }
    }
    return out.length > 0 ? out.join(" ") : clean;
  }

  function firstDefined(obj, keys) {
    if (!isObject(obj)) {
      return undefined;
    }
    for (var i = 0; i < keys.length; i += 1) {
      var k = keys[i];
      if (obj[k] !== undefined && obj[k] !== null) {
        return obj[k];
      }
    }
    return undefined;
  }

  function nonEmptyString(val) {
    if (typeof val !== "string") {
      return null;
    }
    var trimmed = val.trim();
    return trimmed.length > 0 ? trimmed : null;
  }

  function normalizeModelId(model) {
    var raw = model === null || model === undefined ? "" : String(model).trim();
    if (raw.toLowerCase().indexOf("gemini:") === 0) {
      return raw.slice(7).trim();
    }
    return raw;
  }

  function normalizeTier(tier) {
    var raw = tier === null || tier === undefined ? "" : String(tier).trim().toLowerCase();
    return raw || "hard";
  }

  function normalizeSeed(seed) {
    if (seed === null || seed === undefined || seed === "") {
      return "0";
    }
    return String(seed).trim();
  }

  function normalizeLevel(level) {
    var raw = level === null || level === undefined ? "" : String(level).trim().toLowerCase();
    if (Object.prototype.hasOwnProperty.call(LEVEL_ALIASES, raw)) {
      return LEVEL_ALIASES[raw];
    }
    return raw;
  }

  function toFiniteNumber(val) {
    if (val === null || val === undefined || val === "" || typeof val === "boolean") {
      return null;
    }
    var n = Number(val);
    return Number.isFinite(n) ? n : null;
  }

  function formatCostUsd(val) {
    var n = toFiniteNumber(val);
    if (n === null) {
      return "N/A";
    }
    if (n < 0) {
      return "-$" + Math.abs(n).toFixed(4);
    }
    return "$" + n.toFixed(4);
  }

  function formatScore(val) {
    var n = toFiniteNumber(val);
    if (n === null) {
      return "N/A";
    }
    var fixed2 = n.toFixed(2);
    var fixed4 = n.toFixed(4);
    if (Number(fixed2) === Number(fixed4)) {
      return fixed2;
    }
    var trimmed = fixed4;
    while (trimmed.length > 0 && trimmed.charAt(trimmed.length - 1) === "0") {
      trimmed = trimmed.slice(0, trimmed.length - 1);
    }
    if (trimmed.charAt(trimmed.length - 1) === ".") {
      trimmed += "00";
    }
    return trimmed;
  }

  function formatPct(val) {
    var n = toFiniteNumber(val);
    if (n === null) {
      return "N/A";
    }
    return (n * 100).toFixed(1) + "%";
  }

  function formatTokens(val) {
    var n = toFiniteNumber(val);
    if (n === null) {
      return "N/A";
    }
    var rounded = Math.round(n);
    var sign = rounded < 0 ? "-" : "";
    var digits = String(Math.abs(rounded));
    var out = "";
    var count = 0;
    for (var i = digits.length - 1; i >= 0; i -= 1) {
      if (count > 0 && count % 3 === 0) {
        out = "," + out;
      }
      out = digits.charAt(i) + out;
      count += 1;
    }
    return sign + out;
  }

  function isHighlightedFailureTag(tag) {
    if (!tag || typeof tag !== "string") {
      return false;
    }
    return HIGHLIGHTED_FAILURE_TAGS.indexOf(tag.trim()) !== -1;
  }

  function isAllDigits(str) {
    if (!str || str.length === 0) {
      return false;
    }
    for (var i = 0; i < str.length; i += 1) {
      var code = str.charCodeAt(i);
      if (code < 48 || code > 57) {
        return false;
      }
    }
    return true;
  }

  function parseRunIdentifier(runId) {
    if (typeof runId !== "string" || !runId.trim()) {
      return null;
    }
    var raw = runId.trim();
    var lastColon = raw.lastIndexOf(":");
    var tail = lastColon !== -1 ? raw.slice(lastColon + 1).trim() : raw;
    var parts = null;
    if (tail.indexOf("/") !== -1) {
      parts = tail.split("/");
    } else if (tail.indexOf("|") !== -1) {
      parts = tail.split("|");
    }
    if (!parts || parts.length !== 4) {
      return null;
    }
    var m = normalizeModelId(parts[0]);
    var lv = normalizeLevel(parts[1]);
    var tr = parts[2] ? String(parts[2]).trim().toLowerCase() : "";
    var sd = parts[3] !== undefined ? String(parts[3]).trim() : "";
    if (!m || !lv || !tr || !sd) {
      return null;
    }
    return {
      model: m,
      level: lv,
      tier: tr,
      seed: sd
    };
  }

  function parseCaseIdentifier(caseId) {
    if (typeof caseId !== "string" || !caseId.trim()) {
      return null;
    }
    var lower = caseId.trim().toLowerCase();
    var tokens = [];
    var current = "";
    for (var i = 0; i < lower.length; i += 1) {
      var ch = lower.charAt(i);
      if (ch === "-" || ch === "_" || ch === ":" || ch === "/" || ch === "|") {
        if (current) {
          tokens.push(current);
          current = "";
        }
      } else {
        current += ch;
      }
    }
    if (current) {
      tokens.push(current);
    }

    var foundTier = null;
    var tierIdx = -1;
    for (var t = 0; t < tokens.length; t += 1) {
      if (tokens[t] === "easy" || tokens[t] === "medium" || tokens[t] === "hard") {
        foundTier = tokens[t];
        tierIdx = t;
        break;
      }
    }
    if (!foundTier) {
      return null;
    }

    var foundSeed = null;
    for (var s = tokens.length - 1; s > tierIdx; s -= 1) {
      var cand = tokens[s];
      if (isAllDigits(cand)) {
        foundSeed = cand;
        break;
      }
      if (cand.length > 1 && cand.charAt(0) === "s" && isAllDigits(cand.slice(1))) {
        foundSeed = cand.slice(1);
        break;
      }
    }

    return {
      tier: foundTier,
      seed: foundSeed
    };
  }

  function findEntryInModeList(list, cleanTag) {
    if (!Array.isArray(list)) {
      return null;
    }
    var lower = cleanTag.toLowerCase();
    for (var i = 0; i < list.length; i += 1) {
      var item = list[i];
      if (!isObject(item)) {
        continue;
      }
      var idVal = firstDefined(item, ["tag", "id", "mode", "key", "slug", "failure_tag", "failureTag"]);
      if (typeof idVal === "string" && idVal.trim().toLowerCase() === lower) {
        return item;
      }
      if (Array.isArray(item.aliases)) {
        for (var a = 0; a < item.aliases.length; a += 1) {
          if (typeof item.aliases[a] === "string" && item.aliases[a].trim().toLowerCase() === lower) {
            return item;
          }
        }
      }
      if (Array.isArray(item.tags)) {
        for (var k = 0; k < item.tags.length; k += 1) {
          if (typeof item.tags[k] === "string" && item.tags[k].trim().toLowerCase() === lower) {
            return item;
          }
        }
      }
    }
    return null;
  }

  function lookupInFailureModesStore(rawStore, tag) {
    if (!rawStore || !tag) {
      return null;
    }
    var cleanTag = String(tag).trim();
    var lowerTag = cleanTag.toLowerCase();

    if (Array.isArray(rawStore)) {
      return findEntryInModeList(rawStore, cleanTag);
    }

    if (!isObject(rawStore)) {
      return null;
    }

    var directHit = rawStore[cleanTag] !== undefined ? rawStore[cleanTag] : rawStore[lowerTag];
    if (isObject(directHit)) {
      return directHit;
    }
    if (typeof directHit === "string" && directHit.trim()) {
      return directHit.trim();
    }

    var mapCandidates = [
      rawStore.by_tag,
      rawStore.byTag,
      rawStore.failure_modes,
      rawStore.failureModes,
      rawStore.modes,
      rawStore.tags,
      isObject(rawStore.taxonomy) ? rawStore.taxonomy.modes : null
    ];

    for (var m = 0; m < mapCandidates.length; m += 1) {
      var sub = mapCandidates[m];
      if (Array.isArray(sub)) {
        var arrHit = findEntryInModeList(sub, cleanTag);
        if (arrHit) {
          return arrHit;
        }
      } else if (isObject(sub)) {
        var subHit = sub[cleanTag] !== undefined ? sub[cleanTag] : sub[lowerTag];
        if (isObject(subHit)) {
          return subHit;
        }
        if (typeof subHit === "string" && subHit.trim()) {
          var deref = isObject(rawStore.modes) ? rawStore.modes[subHit.trim()] : null;
          return isObject(deref) ? deref : subHit.trim();
        }
      }
    }

    var aliasMap = rawStore.tag_to_mode || rawStore.tagToMode || rawStore.aliases;
    if (isObject(aliasMap)) {
      var mappedId = aliasMap[cleanTag] || aliasMap[lowerTag];
      if (typeof mappedId === "string" && mappedId.trim()) {
        return lookupInFailureModesStore(
          rawStore.modes || rawStore.failure_modes || rawStore.failureModes,
          mappedId.trim()
        );
      }
      if (isObject(mappedId)) {
        return mappedId;
      }
    }

    return null;
  }

  function lookupFailureMode(tag, opts) {
    if (tag === null || tag === undefined || typeof tag !== "string") {
      return null;
    }
    var cleanTag = tag.trim();
    if (!cleanTag || cleanTag.toLowerCase() === "none") {
      return null;
    }

    var options = isObject(opts) ? opts : {};
    var host = getHostWindow(root);
    var lowerTag = cleanTag.toLowerCase();
    var rawHit = null;
    var enriched = false;

    if (typeof options.getFailureMode === "function") {
      try {
        var customRes = options.getFailureMode(cleanTag);
        if (isObject(customRes) || (typeof customRes === "string" && customRes.trim())) {
          rawHit = customRes;
          enriched = true;
        }
      } catch (_err0) {
        rawHit = null;
      }
    }

    if (!rawHit && (isObject(options.failureModes) || Array.isArray(options.failureModes))) {
      var optModeHit = lookupInFailureModesStore(options.failureModes, cleanTag);
      if (optModeHit) {
        rawHit = optModeHit;
        enriched = true;
      }
    }

    var hasExplicitFailureModesOpt =
      isObject(options.failureModes) || Array.isArray(options.failureModes);

    if (!rawHit && !hasExplicitFailureModesOpt) {
      var globalFn =
        typeof host.getOutthinkFailureMode === "function"
          ? host.getOutthinkFailureMode
          : typeof host.getOutThinkFailureMode === "function"
          ? host.getOutThinkFailureMode
          : null;

      if (globalFn) {
        try {
          var fnRes = globalFn(cleanTag);
          if (!fnRes && cleanTag !== lowerTag) {
            fnRes = globalFn(lowerTag);
          }
          if (isObject(fnRes) || (typeof fnRes === "string" && fnRes.trim())) {
            rawHit = fnRes;
            enriched = true;
          }
        } catch (_err1) {
          rawHit = null;
        }
      }

      if (!rawHit) {
        var globalModesStore = host.OUTTHINK_FAILURE_MODES || host.OutthinkFailureModes || null;
        if (isObject(globalModesStore) || Array.isArray(globalModesStore)) {
          var storeHit = lookupInFailureModesStore(globalModesStore, cleanTag);
          if (storeHit) {
            rawHit = storeHit;
            enriched = true;
          }
        }
      }
    }

    var builtin = BUILTIN_FAILURE_MODES[lowerTag] || null;
    if (typeof rawHit === "string") {
      return {
        tag: cleanTag,
        id: sanitizeDashes(cleanTag),
        name: builtin ? builtin.name : humanizeTag(cleanTag),
        description: sanitizeDashes(rawHit.trim()),
        decision: builtin ? builtin.decision : null,
        mechanism: null,
        solverWould: null,
        count: null,
        rate: null,
        meanRegret: null,
        enriched: true
      };
    }

    var hitObj = isObject(rawHit) ? rawHit : {};
    var resolvedId = nonEmptyString(firstDefined(hitObj, ["id", "tag", "mode", "key", "slug"])) || cleanTag;
    var resolvedName =
      nonEmptyString(firstDefined(hitObj, ["name", "label", "title", "display_name", "displayName"])) ||
      (builtin ? builtin.name : humanizeTag(cleanTag));
    var resolvedDesc =
      nonEmptyString(firstDefined(hitObj, ["description", "summary", "why", "definition", "explanation"])) ||
      (builtin ? builtin.description : "");
    var resolvedDecision =
      nonEmptyString(firstDefined(hitObj, ["decision", "decision_type", "decisionType", "category"])) ||
      (builtin ? builtin.decision : null);
    var resolvedMechanism = nonEmptyString(
      firstDefined(hitObj, ["mechanism", "root_cause", "rootCause", "belief_error"])
    );
    var resolvedSolverWould = nonEmptyString(
      firstDefined(hitObj, ["solver_would", "solverWould", "countermeasure", "remedy", "reference_action"])
    );

    return {
      tag: cleanTag,
      id: sanitizeDashes(resolvedId),
      name: sanitizeDashes(resolvedName),
      description: sanitizeDashes(resolvedDesc),
      decision: resolvedDecision ? sanitizeDashes(resolvedDecision) : null,
      mechanism: resolvedMechanism ? sanitizeDashes(resolvedMechanism) : null,
      solverWould: resolvedSolverWould ? sanitizeDashes(resolvedSolverWould) : null,
      count: toFiniteNumber(firstDefined(hitObj, ["episode_count", "episodes_with", "count", "episodes"])),
      rate: toFiniteNumber(firstDefined(hitObj, ["rate", "episode_rate", "share"])),
      meanRegret: toFiniteNumber(firstDefined(hitObj, ["mean_regret", "regret_mean", "avg_regret", "regret_sum"])),
      enriched: enriched
    };
  }

  function extractEpisodesStore(rawAnnotations) {
    if (!isObject(rawAnnotations)) {
      return null;
    }
    if (isObject(rawAnnotations.episodes)) {
      return rawAnnotations.episodes;
    }
    return rawAnnotations;
  }

  function lookupInStore(rawAnnotations, model, level, tier, seed) {
    if (!isObject(rawAnnotations)) {
      return null;
    }
    var store = extractEpisodesStore(rawAnnotations);
    var cleanModel = normalizeModelId(model);
    var rawModel = model === null || model === undefined ? "" : String(model).trim();
    var lv = normalizeLevel(level);
    var tr = normalizeTier(tier);
    var sd = normalizeSeed(seed);

    var candidateKeys = [
      cleanModel + "/" + lv + "/" + tr + "/" + sd,
      rawModel + "/" + lv + "/" + tr + "/" + sd,
      cleanModel + "|" + lv + "|" + tr + "|" + sd,
      rawModel + "|" + lv + "|" + tr + "|" + sd,
      tr + ":" + sd + ":" + lv
    ];

    if (store) {
      for (var i = 0; i < candidateKeys.length; i += 1) {
        var key = candidateKeys[i];
        if (isObject(store[key])) {
          return store[key];
        }
      }
    }

    if (isObject(rawAnnotations.by_scenario)) {
      var scKey = tr + "/" + sd;
      var scMap = rawAnnotations.by_scenario[scKey];
      if (isObject(scMap)) {
        var modelMap = scMap[cleanModel] || scMap[rawModel];
        if (isObject(modelMap) && modelMap[lv]) {
          var mappedRef = modelMap[lv];
          if (isObject(mappedRef)) {
            return mappedRef;
          }
          if (typeof mappedRef === "string" && store && isObject(store[mappedRef])) {
            return store[mappedRef];
          }
        }
      }
    }

    return null;
  }

  function lookupEpisodeAnnotation(model, level, tier, seed, opts) {
    var options = isObject(opts) ? opts : {};
    var host = getHostWindow(root);
    var cleanModel = normalizeModelId(model);
    var lv = normalizeLevel(level);
    var tr = normalizeTier(tier);
    var sd = normalizeSeed(seed);

    if (typeof options.getAnnotation === "function") {
      try {
        var customHit = options.getAnnotation(cleanModel, lv, tr, sd);
        if (isObject(customHit)) {
          return customHit;
        }
        if (String(model || "") !== cleanModel) {
          var rawCustomHit = options.getAnnotation(model, level, tier, seed);
          if (isObject(rawCustomHit)) {
            return rawCustomHit;
          }
        }
      } catch (_err0) {}
    }

    if (isObject(options.annotations)) {
      var optHit = lookupInStore(options.annotations, model, level, tier, seed);
      if (isObject(optHit)) {
        return optHit;
      }
    }

    if (!isObject(options.annotations) && typeof host.getOutthinkAnnotation === "function") {
      try {
        var fnHit = host.getOutthinkAnnotation(cleanModel, lv, tr, sd);
        if (isObject(fnHit)) {
          return fnHit;
        }
        if (String(model || "") !== cleanModel) {
          var rawFnHit = host.getOutthinkAnnotation(model, level, tier, seed);
          if (isObject(rawFnHit)) {
            return rawFnHit;
          }
        }
      } catch (_err1) {}
    }

    if (!isObject(options.annotations) && isObject(host.OUTTHINK_ANNOTATIONS)) {
      var globalHit = lookupInStore(host.OUTTHINK_ANNOTATIONS, model, level, tier, seed);
      if (isObject(globalHit)) {
        return globalHit;
      }
    }

    return null;
  }

  function findCaseInPayload(payload, tier, seed, caseId) {
    if (!payload) {
      return null;
    }
    var list = Array.isArray(payload)
      ? payload
      : isObject(payload) && Array.isArray(payload.cases)
      ? payload.cases
      : isObject(payload) && Array.isArray(payload.scenarios)
      ? payload.scenarios
      : isObject(payload) && Array.isArray(payload.decision_points)
      ? payload.decision_points
      : null;
    var hasTierSeed = tier !== undefined && tier !== null && seed !== undefined && seed !== null;
    var tr = hasTierSeed ? normalizeTier(tier) : null;
    var sd = hasTierSeed ? normalizeSeed(seed) : null;
    var cid = nonEmptyString(caseId);

    if (list) {
      for (var i = 0; i < list.length; i += 1) {
        var item = list[i];
        if (!isObject(item)) {
          continue;
        }
        var itemId = nonEmptyString(firstDefined(item, ["id", "case_id", "caseId", "scenario_id"]));
        if (cid && itemId && itemId === cid) {
          return item;
        }
        if (hasTierSeed) {
          var itemTier = normalizeTier(firstDefined(item, ["tier", "difficulty"]));
          var itemSeed = normalizeSeed(firstDefined(item, ["seed", "world_seed", "worldSeed"]));
          if (itemTier === tr && itemSeed === sd) {
            return item;
          }
        }
      }
    }

    if (isObject(payload) && hasTierSeed) {
      var direct = payload[tr + "/" + sd] || payload[tr + ":" + sd] || payload[tr + "-" + sd];
      if (isObject(direct)) {
        return direct;
      }
    }

    return null;
  }

  function findMoleInCasesPayload(payload, tier, seed) {
    var item = findCaseInPayload(payload, tier, seed, null);
    if (!isObject(item)) {
      return null;
    }
    var found = firstDefined(item, [
      "true_mole",
      "trueMole",
      "ground_truth_mole",
      "groundTruthMole",
      "mole",
      "culprit"
    ]);
    return typeof found === "string" && found.trim() ? found.trim() : null;
  }

  function resolveTrueMole(tier, seed, judgeChoice, revealState, caseData, rawEpisodes, opts) {
    var options = isObject(opts) ? opts : {};
    var host = getHostWindow(root);
    var tr = normalizeTier(tier);
    var sd = normalizeSeed(seed);

    var explicitOptMole = firstDefined(options, [
      "trueMole",
      "true_mole",
      "groundTruthMole",
      "ground_truth_mole",
      "mole"
    ]);
    if (typeof explicitOptMole === "string" && explicitOptMole.trim()) {
      return explicitOptMole.trim();
    }

    if (isObject(revealState)) {
      var revMole = firstDefined(revealState, [
        "trueMole",
        "true_mole",
        "groundTruthMole",
        "ground_truth_mole",
        "mole",
        "culprit"
      ]);
      if (typeof revMole === "string" && revMole.trim()) {
        return revMole.trim();
      }
    }

    if (isObject(caseData)) {
      var caseMole = firstDefined(caseData, [
        "trueMole",
        "true_mole",
        "groundTruthMole",
        "ground_truth_mole",
        "mole",
        "culprit"
      ]);
      if (typeof caseMole === "string" && caseMole.trim()) {
        return caseMole.trim();
      }
    }

    if (isObject(judgeChoice)) {
      var judgeMole = firstDefined(judgeChoice, [
        "trueMole",
        "true_mole",
        "groundTruthMole",
        "ground_truth_mole",
        "mole"
      ]);
      if (typeof judgeMole === "string" && judgeMole.trim()) {
        return judgeMole.trim();
      }
    }

    for (var i = 0; i < rawEpisodes.length; i += 1) {
      var ep = rawEpisodes[i];
      if (!isObject(ep)) {
        continue;
      }
      var epMole = firstDefined(ep, [
        "true_mole",
        "trueMole",
        "ground_truth_mole",
        "groundTruthMole",
        "mole"
      ]);
      if (typeof epMole === "string" && epMole.trim()) {
        return epMole.trim();
      }
      if (ep.correct === true && typeof ep.accused === "string" && ep.accused.trim()) {
        return ep.accused.trim();
      }
    }

    var rawAnn = isObject(options.annotations) ? options.annotations : host.OUTTHINK_ANNOTATIONS;
    if (isObject(rawAnn)) {
      var store = extractEpisodesStore(rawAnn);
      if (isObject(rawAnn.by_scenario) && store) {
        var scEntry = rawAnn.by_scenario[tr + "/" + sd];
        if (isObject(scEntry)) {
          var modelKeys = Object.keys(scEntry);
          for (var mIdx = 0; mIdx < modelKeys.length; mIdx += 1) {
            var lvMap = scEntry[modelKeys[mIdx]];
            if (!isObject(lvMap)) {
              continue;
            }
            var lvKeys = Object.keys(lvMap);
            for (var lIdx = 0; lIdx < lvKeys.length; lIdx += 1) {
              var ref = lvMap[lvKeys[lIdx]];
              var cand = isObject(ref) ? ref : typeof ref === "string" ? store[ref] : null;
              if (isObject(cand)) {
                var cMole = firstDefined(cand, ["true_mole", "trueMole", "ground_truth_mole", "groundTruthMole", "mole"]);
                if (typeof cMole === "string" && cMole.trim()) {
                  return cMole.trim();
                }
                if (cand.correct === true && typeof cand.accused === "string" && cand.accused.trim()) {
                  return cand.accused.trim();
                }
              }
            }
          }
        }
      }

      if (store) {
        var suffixSlash = "/" + tr + "/" + sd;
        var suffixPipe = "|" + tr + "|" + sd;
        var allKeys = Object.keys(store);
        for (var kIdx = 0; kIdx < allKeys.length; kIdx += 1) {
          var k = allKeys[kIdx];
          var rec = store[k];
          if (!isObject(rec)) {
            continue;
          }
          var keyMatches =
            (k.length > suffixSlash.length && k.slice(k.length - suffixSlash.length).toLowerCase() === suffixSlash) ||
            (k.length > suffixPipe.length && k.slice(k.length - suffixPipe.length).toLowerCase() === suffixPipe) ||
            (normalizeTier(rec.tier) === tr && normalizeSeed(rec.seed) === sd);
          if (!keyMatches) {
            continue;
          }
          var rMole = firstDefined(rec, ["true_mole", "trueMole", "ground_truth_mole", "groundTruthMole", "mole"]);
          if (typeof rMole === "string" && rMole.trim()) {
            return rMole.trim();
          }
          if (rec.correct === true && typeof rec.accused === "string" && rec.accused.trim()) {
            return rec.accused.trim();
          }
        }
      }
    }

    var fromData =
      findMoleInCasesPayload(host.OUTTHINK_DATA, tr, sd) ||
      findMoleInCasesPayload(host.OUTTHINK_SCENARIOS, tr, sd) ||
      findMoleInCasesPayload(host.OUTTHINK_FALLBACK_DATA, tr, sd);
    if (fromData) {
      return fromData;
    }

    return null;
  }

  function normalizeJudgeChoice(judgeChoice, trueMole) {
    if (judgeChoice === null || judgeChoice === undefined || judgeChoice === "") {
      return {
        action: "none",
        suspectId: null,
        label: "No call",
        correct: null,
        optimal: null,
        score: null,
        verdictLabel: null,
        explanation: null
      };
    }

    if (typeof judgeChoice === "string") {
      var trimmed = judgeChoice.trim();
      if (!trimmed) {
        return {
          action: "none",
          suspectId: null,
          label: "No call",
          correct: null,
          optimal: null,
          score: null,
          verdictLabel: null,
          explanation: null
        };
      }
      var lower = trimmed.toLowerCase();
      if (
        lower === "hold_fire" ||
        lower === "hold-fire" ||
        lower === "hold fire" ||
        lower === "holdfire" ||
        lower === "hold" ||
        lower === "wait" ||
        lower === "pass" ||
        lower === "abstain" ||
        lower === "continue" ||
        lower === "defer" ||
        lower === "none"
      ) {
        return {
          action: "hold_fire",
          suspectId: null,
          label: "Hold Fire",
          correct: null,
          optimal: null,
          score: null,
          verdictLabel: null,
          explanation: null
        };
      }
      var suspectStr = trimmed;
      if (lower.indexOf("accuse:") === 0) {
        suspectStr = trimmed.slice(7).trim();
      } else if (lower.indexOf("accuse ") === 0) {
        suspectStr = trimmed.slice(7).trim();
      }
      var isRight = trueMole ? suspectStr === trueMole : null;
      return {
        action: "accuse",
        suspectId: suspectStr,
        label: "Accused " + suspectStr,
        correct: isRight,
        optimal: null,
        score: null,
        verdictLabel: null,
        explanation: null
      };
    }

    if (isObject(judgeChoice)) {
      var rawSuspect = firstDefined(judgeChoice, [
        "suspectId",
        "suspect_id",
        "accused",
        "employee",
        "choice",
        "suspect",
        "target"
      ]);
      var suspectId =
        rawSuspect !== undefined && rawSuspect !== null && String(rawSuspect).trim() !== ""
          ? String(rawSuspect).trim()
          : null;
      var rawAction = firstDefined(judgeChoice, ["action", "type", "call"]);
      var actionLower = rawAction ? String(rawAction).trim().toLowerCase() : "";
      var isHoldFire =
        actionLower === "hold_fire" ||
        actionLower === "hold-fire" ||
        actionLower === "hold fire" ||
        actionLower === "holdfire" ||
        actionLower === "hold" ||
        actionLower === "wait" ||
        actionLower === "abstain" ||
        actionLower === "continue" ||
        actionLower === "defer";

      var action = isHoldFire ? "hold_fire" : suspectId || actionLower === "accuse" ? "accuse" : "none";
      var explicitCorrect = typeof judgeChoice.correct === "boolean" ? judgeChoice.correct : null;
      var computedCorrect =
        explicitCorrect !== null
          ? explicitCorrect
          : action === "accuse" && suspectId && trueMole
          ? suspectId === trueMole
          : null;
      var optimal = typeof judgeChoice.optimal === "boolean" ? judgeChoice.optimal : null;
      var score = toFiniteNumber(judgeChoice.score);
      var rawVerdict = nonEmptyString(firstDefined(judgeChoice, ["verdictLabel", "verdict_label", "verdict"]));
      var rawExplanation = nonEmptyString(firstDefined(judgeChoice, ["explanation", "rationale", "reason"]));
      var label =
        action === "hold_fire"
          ? "Hold Fire"
          : action === "accuse"
          ? "Accused " + (suspectId || "none")
          : "No call";

      return {
        action: action,
        suspectId: suspectId,
        label: label,
        correct: computedCorrect,
        optimal: optimal,
        score: score,
        verdictLabel: rawVerdict ? sanitizeDashes(rawVerdict) : null,
        explanation: rawExplanation ? sanitizeDashes(rawExplanation) : null
      };
    }

    var fallbackStr = String(judgeChoice).trim();
    return {
      action: "accuse",
      suspectId: fallbackStr,
      label: "Accused " + fallbackStr,
      correct: trueMole ? fallbackStr === trueMole : null,
      optimal: null,
      score: null,
      verdictLabel: null,
      explanation: null
    };
  }

  function normalizeSolverSummary(rawSolver) {
    if (!isObject(rawSolver)) {
      return null;
    }
    var recRaw = nonEmptyString(
      firstDefined(rawSolver, ["recommended_call", "recommendedCall", "recommendation", "action", "call"])
    );
    var recLower = recRaw ? recRaw.toLowerCase() : "";
    var recommendedCall =
      recLower === "accuse"
        ? "accuse"
        : recLower === "hold_fire" || recLower === "hold-fire" || recLower === "hold" || recLower === "wait"
        ? "hold_fire"
        : recRaw;
    var topSuspect = nonEmptyString(firstDefined(rawSolver, ["top_suspect", "topSuspect", "best_suspect"]));
    var topProb = toFiniteNumber(firstDefined(rawSolver, ["top_prob", "topProb", "max_prob"]));
    var breakEvenProb = toFiniteNumber(firstDefined(rawSolver, ["break_even_prob", "breakEvenProb"]));
    var evAccuseTop = toFiniteNumber(firstDefined(rawSolver, ["ev_accuse_top", "evAccuseTop", "ev_accuse"]));
    var evHoldFire = toFiniteNumber(firstDefined(rawSolver, ["ev_hold_fire", "evHoldFire", "ev_wait"]));
    var finalAccused = nonEmptyString(firstDefined(rawSolver, ["final_accused", "finalAccused", "accused"]));
    var finalDay = toFiniteNumber(firstDefined(rawSolver, ["final_day", "finalDay", "accused_day"]));
    var finalScore = toFiniteNumber(firstDefined(rawSolver, ["final_score", "finalScore", "score"]));
    var correct = typeof rawSolver.correct === "boolean" ? rawSolver.correct : null;

    if (
      recommendedCall === null &&
      topSuspect === null &&
      topProb === null &&
      breakEvenProb === null &&
      finalScore === null
    ) {
      return null;
    }

    return {
      recommendedCall: recommendedCall || null,
      topSuspect: topSuspect,
      topProb: topProb,
      breakEvenProb: breakEvenProb,
      evAccuseTop: evAccuseTop,
      evHoldFire: evHoldFire,
      finalAccused: finalAccused,
      finalDay: finalDay,
      finalScore: finalScore,
      correct: correct
    };
  }

  function extractQuotes(ep, defaultSourceKind) {
    if (!isObject(ep)) {
      return [];
    }
    var runFallback = nonEmptyString(firstDefined(ep, ["run_id", "runId"]));
    var fallbackSource =
      typeof ep.quote_source_file === "string" && ep.quote_source_file.trim()
        ? ep.quote_source_file.trim()
        : typeof ep.source_file === "string" && ep.source_file.trim()
        ? ep.source_file.trim()
        : runFallback
        ? runFallback
        : "unlisted";

    var collected = [];

    if (Array.isArray(ep.quotes)) {
      for (var i = 0; i < ep.quotes.length; i += 1) {
        var q = ep.quotes[i];
        if (typeof q === "string" && q.trim()) {
          collected.push({
            quote: q,
            source_file: fallbackSource,
            source_kind: "quote",
            t: null,
            day: null,
            note: null,
            origIndex: i
          });
        } else if (isObject(q)) {
          var qText = firstDefined(q, ["quote", "text", "verbatim_quote", "thought", "excerpt"]);
          if (typeof qText === "string" && qText.length > 0) {
            var qSource = firstDefined(q, ["source_file", "sourceFile", "citation", "file"]);
            collected.push({
              quote: qText,
              source_file:
                typeof qSource === "string" && qSource.trim() ? qSource.trim() : fallbackSource,
              source_kind:
                typeof q.source_kind === "string" && q.source_kind.trim()
                  ? q.source_kind.trim()
                  : "quote",
              t: toFiniteNumber(firstDefined(q, ["t", "step"])),
              day: toFiniteNumber(q.day),
              note: typeof q.note === "string" && q.note.trim() ? sanitizeDashes(q.note.trim()) : null,
              origIndex: i
            });
          }
        }
      }
    }

    var directQuoteVal = firstDefined(ep, [
      "verbatim_quote",
      "reasoning_quote",
      "thought_quote",
      "quote",
      "analyst_quote",
      "analystQuote",
      "thought"
    ]);
    var directKind = defaultSourceKind || "transcript";
    if (typeof directQuoteVal === "string" && directQuoteVal.length > 0) {
      var alreadyPresent = false;
      for (var dIdx = 0; dIdx < collected.length; dIdx += 1) {
        if (collected[dIdx].quote === directQuoteVal) {
          alreadyPresent = true;
          break;
        }
      }
      if (!alreadyPresent) {
        collected.unshift({
          quote: directQuoteVal,
          source_file: fallbackSource,
          source_kind: directKind,
          t: null,
          day: null,
          note: null,
          origIndex: -1
        });
      }
    } else if (isObject(directQuoteVal)) {
      var dqText = firstDefined(directQuoteVal, ["quote", "text", "verbatim_quote"]);
      if (typeof dqText === "string" && dqText.length > 0) {
        var dqSrc = firstDefined(directQuoteVal, ["source_file", "sourceFile", "citation"]);
        collected.unshift({
          quote: dqText,
          source_file:
            typeof dqSrc === "string" && dqSrc.trim() ? dqSrc.trim() : fallbackSource,
          source_kind:
            typeof directQuoteVal.source_kind === "string"
              ? directQuoteVal.source_kind
              : directKind,
          t: toFiniteNumber(firstDefined(directQuoteVal, ["t", "step"])),
          day: toFiniteNumber(directQuoteVal.day),
          note: typeof directQuoteVal.note === "string" ? sanitizeDashes(directQuoteVal.note) : null,
          origIndex: -1
        });
      }
    }

    collected.sort(function (a, b) {
      var pa = QUOTE_KIND_PRIORITY[a.source_kind] || 6;
      var pb = QUOTE_KIND_PRIORITY[b.source_kind] || 6;
      if (pa !== pb) {
        return pa - pb;
      }
      return a.origIndex - b.origIndex;
    });

    return collected;
  }

  function extractFailureTags(ep) {
    if (!isObject(ep)) {
      return { primaryTag: null, highlightedTags: [], allTags: [] };
    }
    var rawPrimary = firstDefined(ep, [
      "primary_failure_tag",
      "primaryFailureTag",
      "failure_tag",
      "failureTag",
      "failure_mode",
      "failureMode"
    ]);
    var primaryTag =
      typeof rawPrimary === "string" && rawPrimary.trim() && rawPrimary.trim().toLowerCase() !== "none"
        ? rawPrimary.trim()
        : null;

    var highlightedPresent = [];
    if (primaryTag && isHighlightedFailureTag(primaryTag)) {
      highlightedPresent.push(primaryTag);
    }

    if (isObject(ep.highlighted_tags)) {
      for (var i = 0; i < HIGHLIGHTED_FAILURE_TAGS.length; i += 1) {
        var hTag = HIGHLIGHTED_FAILURE_TAGS[i];
        var hInfo = ep.highlighted_tags[hTag];
        var isPresent =
          (isObject(hInfo) && (hInfo.present === true || toFiniteNumber(hInfo.count) > 0)) ||
          hInfo === true;
        if (isPresent && highlightedPresent.indexOf(hTag) === -1) {
          highlightedPresent.push(hTag);
        }
      }
    }

    var extraArrayTags = Array.isArray(ep.tags)
      ? ep.tags
      : Array.isArray(ep.failure_tags)
      ? ep.failure_tags
      : null;

    if (extraArrayTags) {
      for (var aIdx = 0; aIdx < extraArrayTags.length; aIdx += 1) {
        var arrTag = extraArrayTags[aIdx];
        if (typeof arrTag === "string" && arrTag.trim() && arrTag.trim().toLowerCase() !== "none") {
          var cleanArrTag = arrTag.trim();
          if (isHighlightedFailureTag(cleanArrTag) && highlightedPresent.indexOf(cleanArrTag) === -1) {
            highlightedPresent.push(cleanArrTag);
          }
        }
      }
    } else if (isObject(ep.tags)) {
      for (var j = 0; j < HIGHLIGHTED_FAILURE_TAGS.length; j += 1) {
        var tName = HIGHLIGHTED_FAILURE_TAGS[j];
        var tEntry = ep.tags[tName];
        if (
          ((isObject(tEntry) && toFiniteNumber(tEntry.count) > 0) || tEntry === true) &&
          highlightedPresent.indexOf(tName) === -1
        ) {
          highlightedPresent.push(tName);
        }
      }
    }

    var allTags = [];
    if (primaryTag) {
      allTags.push(primaryTag);
    }
    for (var k = 0; k < highlightedPresent.length; k += 1) {
      if (allTags.indexOf(highlightedPresent[k]) === -1) {
        allTags.push(highlightedPresent[k]);
      }
    }
    if (extraArrayTags) {
      for (var m = 0; m < extraArrayTags.length; m += 1) {
        if (typeof extraArrayTags[m] === "string" && extraArrayTags[m].trim()) {
          var ct = extraArrayTags[m].trim();
          if (ct.toLowerCase() !== "none" && allTags.indexOf(ct) === -1) {
            allTags.push(ct);
          }
        }
      }
    }

    return {
      primaryTag: primaryTag,
      highlightedTags: highlightedPresent,
      allTags: allTags
    };
  }

  function mergeEpisodeRecords(engineEp, annotationEp) {
    if (!isObject(engineEp) && !isObject(annotationEp)) {
      return null;
    }
    if (!isObject(engineEp)) {
      return annotationEp;
    }
    if (!isObject(annotationEp)) {
      return engineEp;
    }

    var merged = {};
    var annKeys = Object.keys(annotationEp);
    for (var i = 0; i < annKeys.length; i += 1) {
      merged[annKeys[i]] = annotationEp[annKeys[i]];
    }

    var engAccused = nonEmptyString(firstDefined(engineEp, ["accused", "suspect_accused", "final_accused"]));
    var annAccused = nonEmptyString(firstDefined(annotationEp, ["accused", "suspect_accused", "final_accused"]));
    merged.accused = engAccused || annAccused || null;

    var engDay = toFiniteNumber(firstDefined(engineEp, ["accused_day", "accusedDay", "final_day", "finalDay"]));
    var annDay = toFiniteNumber(firstDefined(annotationEp, ["accused_day", "accusedDay", "final_day", "finalDay"]));
    merged.accused_day = engDay !== null ? engDay : annDay;

    var engCallAtT = nonEmptyString(firstDefined(engineEp, ["call_at_t", "callAtT"]));
    var annCallAtT = nonEmptyString(firstDefined(annotationEp, ["call_at_t", "callAtT"]));
    merged.call_at_t = engCallAtT || annCallAtT || null;

    var engEnd = nonEmptyString(firstDefined(engineEp, ["end_reason", "endReason"]));
    var annEnd = nonEmptyString(firstDefined(annotationEp, ["end_reason", "endReason"]));
    merged.end_reason = engEnd || annEnd || null;

    if (typeof engineEp.correct === "boolean") {
      merged.correct = engineEp.correct;
    } else if (typeof annotationEp.correct === "boolean") {
      merged.correct = annotationEp.correct;
    }

    var engScore = toFiniteNumber(firstDefined(engineEp, ["score", "episode_score", "final_score"]));
    if (engScore !== null) {
      merged.score = engScore;
    }

    var engCost = toFiniteNumber(firstDefined(engineEp, ["cost_usd", "costUsd", "cost"]));
    var annCost = toFiniteNumber(firstDefined(annotationEp, ["cost_usd", "costUsd", "cost"]));
    if (annCost !== null && (engCost === null || (engCost === 0 && annCost > 0))) {
      merged.cost_usd = annCost;
    } else if (engCost !== null) {
      merged.cost_usd = engCost;
    }

    var engThinking = toFiniteNumber(
      isObject(engineEp.tokens) && engineEp.tokens.thinking !== undefined
        ? engineEp.tokens.thinking
        : firstDefined(engineEp, ["thinking_tokens", "thinkingTokens", "thought_tokens"])
    );
    var annThinking = toFiniteNumber(
      isObject(annotationEp.tokens) && annotationEp.tokens.thinking !== undefined
        ? annotationEp.tokens.thinking
        : firstDefined(annotationEp, ["thinking_tokens", "thinkingTokens"])
    );
    var finalThinking =
      annThinking !== null && (engThinking === null || (engThinking === 0 && annThinking > 0))
        ? annThinking
        : engThinking !== null
        ? engThinking
        : annThinking;
    var isEstimate = Boolean(
      (isObject(annotationEp.tokens) && annotationEp.tokens.thinking_is_estimate === true) ||
        (isObject(engineEp.tokens) && engineEp.tokens.thinking_is_estimate === true)
    );
    merged.tokens = {
      thinking: finalThinking,
      thinking_is_estimate: isEstimate
    };

    var annTag = nonEmptyString(
      firstDefined(annotationEp, ["primary_failure_tag", "primaryFailureTag", "failure_tag", "failureTag"])
    );
    var engTag = nonEmptyString(
      firstDefined(engineEp, ["primary_failure_tag", "primaryFailureTag", "failure_tag", "failureTag"])
    );
    merged.primary_failure_tag =
      annTag && annTag.toLowerCase() !== "none"
        ? annTag
        : engTag && engTag.toLowerCase() !== "none"
        ? engTag
        : null;

    var mergedHighlighted = {};
    if (isObject(annotationEp.highlighted_tags)) {
      var ahKeys = Object.keys(annotationEp.highlighted_tags);
      for (var h = 0; h < ahKeys.length; h += 1) {
        mergedHighlighted[ahKeys[h]] = annotationEp.highlighted_tags[ahKeys[h]];
      }
    }
    if (isObject(engineEp.highlighted_tags)) {
      var ehKeys = Object.keys(engineEp.highlighted_tags);
      for (var eh = 0; eh < ehKeys.length; eh += 1) {
        if (!mergedHighlighted[ehKeys[eh]]) {
          mergedHighlighted[ehKeys[eh]] = engineEp.highlighted_tags[ehKeys[eh]];
        }
      }
    }
    if (engTag && isHighlightedFailureTag(engTag) && !mergedHighlighted[engTag]) {
      mergedHighlighted[engTag] = { present: true, count: 1 };
    }
    merged.highlighted_tags = mergedHighlighted;

    var annRegret = toFiniteNumber(firstDefined(annotationEp, ["regret_total", "regretTotal"]));
    var engRegret = toFiniteNumber(firstDefined(engineEp, ["regret_total", "regretTotal"]));
    merged.regret_total = annRegret !== null ? annRegret : engRegret;

    merged.run_id =
      nonEmptyString(firstDefined(engineEp, ["run_id", "runId"])) ||
      nonEmptyString(firstDefined(annotationEp, ["run_id", "runId"])) ||
      null;

    merged.source_file =
      nonEmptyString(firstDefined(annotationEp, ["source_file", "quote_source_file"])) ||
      nonEmptyString(firstDefined(engineEp, ["source_file", "quote_source_file"])) ||
      null;

    var annQuotes = extractQuotes(annotationEp, "transcript");
    var engQuotes = extractQuotes(engineEp, annQuotes.length > 0 ? "analyst_summary" : "transcript");
    var combinedQuotes = annQuotes.slice();
    for (var qIdx = 0; qIdx < engQuotes.length; qIdx += 1) {
      var eq = engQuotes[qIdx];
      var dup = false;
      for (var cIdx = 0; cIdx < combinedQuotes.length; cIdx += 1) {
        if (combinedQuotes[cIdx].quote === eq.quote) {
          dup = true;
          break;
        }
      }
      if (!dup) {
        combinedQuotes.push(eq);
      }
    }
    merged.quotes = combinedQuotes;
    delete merged.analyst_quote;
    delete merged.analystQuote;
    delete merged.verbatim_quote;
    delete merged.reasoning_quote;
    delete merged.thought_quote;
    delete merged.quote;
    delete merged.thought;

    return merged;
  }

  function normalizeRow(level, ep, trueMole, opts) {
    var lv = normalizeLevel(level);
    if (!isObject(ep)) {
      return {
        level: lv,
        available: false,
        accused: null,
        accusedDay: null,
        callAtT: null,
        endReason: null,
        correct: null,
        score: null,
        costUsd: null,
        thinkingTokens: null,
        thinkingIsEstimate: false,
        regretTotal: null,
        runId: null,
        primaryFailureTag: null,
        highlightedTags: [],
        allTags: [],
        failureMode: null,
        failureModes: {},
        quotes: [],
        sourceFile: null
      };
    }

    var rawAccused = firstDefined(ep, ["accused", "suspect_accused", "final_accused", "suspectId", "suspect_id"]);
    var accused =
      rawAccused !== undefined && rawAccused !== null && String(rawAccused).trim() !== ""
        ? String(rawAccused).trim()
        : null;

    var accusedDay = toFiniteNumber(firstDefined(ep, ["accused_day", "accusedDay", "final_day", "finalDay"]));
    var callAtT = nonEmptyString(firstDefined(ep, ["call_at_t", "callAtT"]));
    var endReason = nonEmptyString(firstDefined(ep, ["end_reason", "endReason"]));
    var regretTotal = toFiniteNumber(firstDefined(ep, ["regret_total", "regretTotal"]));
    var runId = nonEmptyString(firstDefined(ep, ["run_id", "runId"]));

    var correct =
      typeof ep.correct === "boolean"
        ? ep.correct
        : accused && trueMole
        ? accused === trueMole
        : trueMole
        ? false
        : null;

    var score = toFiniteNumber(firstDefined(ep, ["score", "episode_score", "final_score", "reward"]));
    var costUsd = toFiniteNumber(firstDefined(ep, ["cost_usd", "costUsd", "cost"]));

    var rawThinking =
      isObject(ep.tokens) && ep.tokens.thinking !== undefined
        ? ep.tokens.thinking
        : firstDefined(ep, ["thinking_tokens", "thinkingTokens", "thought_tokens"]);
    var thinkingTokens = toFiniteNumber(rawThinking);
    var thinkingIsEstimate = Boolean(isObject(ep.tokens) && ep.tokens.thinking_is_estimate === true);

    var tagInfo = extractFailureTags(ep);
    var resolvedModes = {};
    for (var tIdx = 0; tIdx < tagInfo.allTags.length; tIdx += 1) {
      var tagKey = tagInfo.allTags[tIdx];
      var fm = lookupFailureMode(tagKey, opts);
      if (fm) {
        resolvedModes[tagKey] = fm;
      }
    }
    var primaryFailureMode =
      tagInfo.primaryTag && resolvedModes[tagInfo.primaryTag]
        ? resolvedModes[tagInfo.primaryTag]
        : tagInfo.allTags.length > 0 && resolvedModes[tagInfo.allTags[0]]
        ? resolvedModes[tagInfo.allTags[0]]
        : null;

    var quotes = extractQuotes(ep);
    var sourceFile =
      quotes.length > 0 && quotes[0].source_file
        ? quotes[0].source_file
        : typeof ep.source_file === "string" && ep.source_file.trim()
        ? ep.source_file.trim()
        : null;

    return {
      level: lv,
      available: true,
      accused: accused,
      accusedDay: accusedDay,
      callAtT: callAtT,
      endReason: endReason,
      correct: correct,
      score: score,
      costUsd: costUsd,
      thinkingTokens: thinkingTokens,
      thinkingIsEstimate: thinkingIsEstimate,
      regretTotal: regretTotal,
      runId: runId,
      primaryFailureTag: tagInfo.primaryTag,
      highlightedTags: tagInfo.highlightedTags,
      allTags: tagInfo.allTags,
      failureMode: primaryFailureMode,
      failureModes: resolvedModes,
      quotes: quotes,
      sourceFile: sourceFile
    };
  }

  function looksLikeCaseObject(val) {
    if (!isObject(val)) {
      return false;
    }
    if (
      "judgeChoice" in val ||
      "judge_choice" in val ||
      "evalResult" in val ||
      "eval_result" in val ||
      "revealState" in val ||
      "reveal_state" in val
    ) {
      return false;
    }
    return (
      "thinking_levels" in val ||
      "thinkingLevels" in val ||
      "suspects" in val ||
      "canaries" in val ||
      "decision_day" in val ||
      "decisionDay" in val ||
      "value_at_decision" in val ||
      "valueAtDecision" in val
    );
  }

  function looksLikeRevealState(val) {
    if (!isObject(val)) {
      return false;
    }
    if (
      "judgeChoice" in val ||
      "judge_choice" in val ||
      "evalResult" in val ||
      "eval_result" in val ||
      "revealState" in val ||
      "reveal_state" in val
    ) {
      return false;
    }
    return (
      "levelComparisons" in val ||
      "level_comparisons" in val ||
      ("action" in val &&
        ("verdictLabel" in val ||
          "verdict_label" in val ||
          "explanation" in val ||
          "optimal" in val ||
          "solver" in val))
    );
  }

  function shallowCopyObject(src) {
    var out = {};
    if (!isObject(src)) {
      return out;
    }
    var keys = Object.keys(src);
    for (var i = 0; i < keys.length; i += 1) {
      out[keys[i]] = src[keys[i]];
    }
    return out;
  }

  function parseNonContainerArgs(a0, a1, a2, a3, a4) {
    if (isObject(a0)) {
      if (looksLikeCaseObject(a0)) {
        var cData = a0;
        var rState = null;
        var jChoice = null;
        var optsFromCaseCall = {};
        if (looksLikeRevealState(a1)) {
          rState = a1;
          jChoice = a1;
          optsFromCaseCall = isObject(a2) ? shallowCopyObject(a2) : {};
        } else if (a1 !== undefined) {
          jChoice = a1;
          optsFromCaseCall = isObject(a2) ? shallowCopyObject(a2) : {};
        }
        return {
          container: isDomElement(optsFromCaseCall.container) ? optsFromCaseCall.container : null,
          tier: optsFromCaseCall.tier !== undefined ? optsFromCaseCall.tier : firstDefined(cData, ["tier", "difficulty"]),
          seed:
            optsFromCaseCall.seed !== undefined
              ? optsFromCaseCall.seed
              : firstDefined(cData, ["seed", "world_seed", "worldSeed"]),
          model: optsFromCaseCall.model !== undefined ? optsFromCaseCall.model : cData.model,
          judgeChoice: jChoice,
          revealState: rState,
          caseData: cData,
          options: optsFromCaseCall
        };
      }

      if (looksLikeRevealState(a0)) {
        var revState = a0;
        var pairedCase = null;
        var optsFromRevCall = {};
        if (looksLikeCaseObject(a1)) {
          pairedCase = a1;
          optsFromRevCall = isObject(a2) ? shallowCopyObject(a2) : {};
        } else if (isObject(a1)) {
          optsFromRevCall = shallowCopyObject(a1);
          var nestedCase = firstDefined(optsFromRevCall, [
            "caseData",
            "case_data",
            "caseObj",
            "case_obj",
            "case",
            "scenario"
          ]);
          if (isObject(nestedCase)) {
            pairedCase = nestedCase;
          }
        }
        var chosenJudge =
          firstDefined(optsFromRevCall, ["judgeChoice", "judge_choice", "judgeCall", "judge_call"]) !== undefined
            ? firstDefined(optsFromRevCall, ["judgeChoice", "judge_choice", "judgeCall", "judge_call"])
            : revState;
        return {
          container: isDomElement(optsFromRevCall.container) ? optsFromRevCall.container : null,
          tier: optsFromRevCall.tier !== undefined ? optsFromRevCall.tier : revState.tier,
          seed: optsFromRevCall.seed !== undefined ? optsFromRevCall.seed : revState.seed,
          model: optsFromRevCall.model !== undefined ? optsFromRevCall.model : revState.model,
          judgeChoice: chosenJudge,
          revealState: revState,
          caseData: pairedCase,
          options: optsFromRevCall
        };
      }

      var cfg = shallowCopyObject(a0);
      if (isObject(a1)) {
        var extraKeys = Object.keys(a1);
        for (var eIdx = 0; eIdx < extraKeys.length; eIdx += 1) {
          var ek = extraKeys[eIdx];
          if (cfg[ek] === undefined) {
            cfg[ek] = a1[ek];
          }
        }
      }
      var cfgReveal = firstDefined(cfg, [
        "revealState",
        "reveal_state",
        "evalResult",
        "eval_result",
        "result",
        "reveal",
        "caseResult",
        "case_result"
      ]);
      var cfgCase = firstDefined(cfg, [
        "caseData",
        "case_data",
        "caseObj",
        "case_obj",
        "case",
        "scenario"
      ]);
      var cfgJudge = firstDefined(cfg, ["judgeChoice", "judge_choice", "judgeCall", "judge_call", "call"]);
      if (cfgJudge === undefined && isObject(cfgReveal)) {
        cfgJudge = cfgReveal;
      }

      return {
        container: isDomElement(cfg.container) ? cfg.container : null,
        tier: cfg.tier,
        seed: cfg.seed,
        model: cfg.model,
        judgeChoice: cfgJudge,
        revealState: isObject(cfgReveal) ? cfgReveal : null,
        caseData: isObject(cfgCase) ? cfgCase : null,
        options: cfg
      };
    }

    var posOpts = isObject(a4) ? shallowCopyObject(a4) : {};
    var posReveal = firstDefined(posOpts, [
      "revealState",
      "reveal_state",
      "evalResult",
      "eval_result",
      "result",
      "reveal"
    ]);
    var posCase = firstDefined(posOpts, [
      "caseData",
      "case_data",
      "caseObj",
      "case_obj",
      "case",
      "scenario"
    ]);
    return {
      container: isDomElement(posOpts.container) ? posOpts.container : null,
      tier: a0,
      seed: a1,
      model: a2,
      judgeChoice: a3,
      revealState: isObject(posReveal) ? posReveal : null,
      caseData: isObject(posCase) ? posCase : null,
      options: posOpts
    };
  }

  function parseCallArgs(arg0, arg1, arg2, arg3, arg4, arg5) {
    if (isDomElement(arg0)) {
      var inner = parseNonContainerArgs(arg1, arg2, arg3, arg4, arg5);
      inner.container = arg0;
      inner.returnContainer = true;
      return inner;
    }
    var res = parseNonContainerArgs(arg0, arg1, arg2, arg3, arg4);
    res.returnContainer = false;
    return res;
  }

  function extractRawEngineLevels(revealState, caseData, opts) {
    var sources = [
      isObject(opts) ? firstDefined(opts, ["levelComparisons", "level_comparisons", "thinking_levels", "thinkingLevels"]) : null,
      isObject(revealState)
        ? firstDefined(revealState, ["levelComparisons", "level_comparisons", "thinking_levels", "thinkingLevels"])
        : null,
      isObject(caseData)
        ? firstDefined(caseData, ["thinking_levels", "thinkingLevels", "levels", "runs", "gemini_runs"])
        : null
    ];

    for (var i = 0; i < sources.length; i += 1) {
      var src = sources[i];
      if (Array.isArray(src) && src.length > 0) {
        return src;
      }
      if (isObject(src)) {
        var keys = Object.keys(src);
        var converted = [];
        for (var k = 0; k < keys.length; k += 1) {
          var item = src[keys[k]];
          if (isObject(item)) {
            var copy = shallowCopyObject(item);
            if (!copy.thinking_level && !copy.level && !copy.key) {
              copy.thinking_level = keys[k];
            }
            converted.push(copy);
          }
        }
        if (converted.length > 0) {
          return converted;
        }
      }
    }
    return [];
  }

  function extractModelSpecificLevelsFromCase(caseData, targetModel) {
    if (!isObject(caseData) || !targetModel) {
      return [];
    }
    var out = [];
    if (isObject(caseData.ladder_matrix)) {
      var matrixEntry = caseData.ladder_matrix[targetModel] || caseData.ladder_matrix["gemini:" + targetModel];
      if (isObject(matrixEntry)) {
        var lvKeys = Object.keys(matrixEntry);
        for (var i = 0; i < lvKeys.length; i += 1) {
          var rec = matrixEntry[lvKeys[i]];
          if (isObject(rec)) {
            var copy = shallowCopyObject(rec);
            copy.model = targetModel;
            copy.thinking_level = lvKeys[i];
            out.push(copy);
          }
        }
        if (out.length > 0) {
          return out;
        }
      }
    }
    if (targetModel === "gemini-4-carbon" && Array.isArray(caseData.cross_model_carbon)) {
      for (var c = 0; c < caseData.cross_model_carbon.length; c += 1) {
        var item = caseData.cross_model_carbon[c];
        if (isObject(item)) {
          out.push(item);
        }
      }
    }
    return out;
  }

  function normalizeCrossModelCarbon(caseData, trueMole) {
    if (!isObject(caseData) || !Array.isArray(caseData.cross_model_carbon)) {
      return [];
    }
    var out = [];
    for (var i = 0; i < caseData.cross_model_carbon.length; i += 1) {
      var item = caseData.cross_model_carbon[i];
      if (!isObject(item)) {
        continue;
      }
      var acc = nonEmptyString(firstDefined(item, ["accused", "final_accused"]));
      var isRight =
        typeof item.correct === "boolean"
          ? item.correct
          : acc && trueMole
          ? acc === trueMole
          : null;
      out.push({
        model: normalizeModelId(item.model || "gemini-4-carbon") || "gemini-4-carbon",
        level: normalizeLevel(firstDefined(item, ["thinking_level", "level"]) || "low"),
        accused: acc,
        accusedDay: toFiniteNumber(firstDefined(item, ["accused_day", "final_day"])),
        score: toFiniteNumber(item.score),
        costUsd: toFiniteNumber(firstDefined(item, ["cost_usd", "cost"])),
        thinkingTokens: toFiniteNumber(firstDefined(item, ["thinking_tokens", "thought_tokens"])),
        correct: isRight
      });
    }
    return out;
  }

  function buildModel(arg0, arg1, arg2, arg3, arg4, arg5) {
    var parsed = parseCallArgs(arg0, arg1, arg2, arg3, arg4, arg5);
    var opts = parsed.options;
    var revealState = parsed.revealState;
    var caseData = parsed.caseData;
    var rawEngineLevels = extractRawEngineLevels(revealState, caseData, opts);

    var inferredFromRun = null;
    for (var rIdx = 0; rIdx < rawEngineLevels.length; rIdx += 1) {
      var rItem = rawEngineLevels[rIdx];
      if (!isObject(rItem)) {
        continue;
      }
      var parsedRun = parseRunIdentifier(firstDefined(rItem, ["run_id", "runId"]));
      if (parsedRun) {
        inferredFromRun = parsedRun;
        break;
      }
    }

    var rawCaseId =
      nonEmptyString(firstDefined(opts, ["caseId", "case_id"])) ||
      (isObject(revealState) ? nonEmptyString(firstDefined(revealState, ["caseId", "case_id", "id"])) : null) ||
      (isObject(caseData) ? nonEmptyString(firstDefined(caseData, ["id", "case_id", "caseId"])) : null);

    var inferredFromCaseId = parseCaseIdentifier(rawCaseId);

    var rawTierCandidate =
      parsed.tier !== undefined && parsed.tier !== null && String(parsed.tier).trim() !== ""
        ? parsed.tier
        : isObject(caseData) && firstDefined(caseData, ["tier", "difficulty"]) !== undefined
        ? firstDefined(caseData, ["tier", "difficulty"])
        : isObject(rawEngineLevels[0]) && firstDefined(rawEngineLevels[0], ["tier", "difficulty"]) !== undefined
        ? firstDefined(rawEngineLevels[0], ["tier", "difficulty"])
        : inferredFromRun
        ? inferredFromRun.tier
        : inferredFromCaseId
        ? inferredFromCaseId.tier
        : null;

    var rawSeedCandidate =
      parsed.seed !== undefined && parsed.seed !== null && String(parsed.seed).trim() !== ""
        ? parsed.seed
        : isObject(caseData) && firstDefined(caseData, ["seed", "world_seed", "worldSeed"]) !== undefined
        ? firstDefined(caseData, ["seed", "world_seed", "worldSeed"])
        : isObject(rawEngineLevels[0]) && firstDefined(rawEngineLevels[0], ["seed", "world_seed", "worldSeed"]) !== undefined
        ? firstDefined(rawEngineLevels[0], ["seed", "world_seed", "worldSeed"])
        : inferredFromRun
        ? inferredFromRun.seed
        : inferredFromCaseId && inferredFromCaseId.seed !== null
        ? inferredFromCaseId.seed
        : null;

    var host = getHostWindow(root);
    if (!caseData && (rawCaseId || (rawTierCandidate !== null && rawSeedCandidate !== null))) {
      var globalCase =
        findCaseInPayload(host.OUTTHINK_DATA, rawTierCandidate, rawSeedCandidate, rawCaseId) ||
        findCaseInPayload(host.OUTTHINK_FALLBACK_DATA, rawTierCandidate, rawSeedCandidate, rawCaseId);
      if (isObject(globalCase)) {
        caseData = globalCase;
        if (rawTierCandidate === null) {
          rawTierCandidate = firstDefined(caseData, ["tier", "difficulty"]);
        }
        if (rawSeedCandidate === null) {
          rawSeedCandidate = firstDefined(caseData, ["seed", "world_seed", "worldSeed"]);
        }
      }
    }

    var tier = normalizeTier(rawTierCandidate);
    var seed = normalizeSeed(rawSeedCandidate);

    var explicitModel =
      parsed.model !== undefined && parsed.model !== null && String(parsed.model).trim() !== ""
        ? normalizeModelId(parsed.model)
        : "";
    var inferredEngineModel = "";
    if (!explicitModel) {
      if (isObject(caseData) && nonEmptyString(caseData.model)) {
        inferredEngineModel = normalizeModelId(caseData.model);
      } else if (isObject(rawEngineLevels[0]) && nonEmptyString(rawEngineLevels[0].model)) {
        inferredEngineModel = normalizeModelId(rawEngineLevels[0].model);
      } else if (inferredFromRun && inferredFromRun.model) {
        inferredEngineModel = inferredFromRun.model;
      }
    }
    var model = explicitModel || inferredEngineModel || "gemini-3.5-flash";

    var engineByLevel = {};
    var extraLevelOrder = [];
    for (var e = 0; e < rawEngineLevels.length; e += 1) {
      var engItem = rawEngineLevels[e];
      if (!isObject(engItem)) {
        continue;
      }
      var itemModel = nonEmptyString(engItem.model) ? normalizeModelId(engItem.model) : "";
      if (explicitModel && itemModel && itemModel !== explicitModel) {
        continue;
      }
      var engLv = normalizeLevel(
        firstDefined(engItem, ["thinking_level", "thinkingLevel", "level", "key"])
      );
      if (!engLv) {
        continue;
      }
      engineByLevel[engLv] = engItem;
      if (LADDER_LEVELS.indexOf(engLv) === -1 && extraLevelOrder.indexOf(engLv) === -1) {
        extraLevelOrder.push(engLv);
      }
    }

    if (Object.keys(engineByLevel).length === 0 && explicitModel && isObject(caseData)) {
      var altLevels = extractModelSpecificLevelsFromCase(caseData, explicitModel);
      for (var a = 0; a < altLevels.length; a += 1) {
        var altItem = altLevels[a];
        var altLv = normalizeLevel(
          firstDefined(altItem, ["thinking_level", "thinkingLevel", "level", "key"])
        );
        if (altLv) {
          engineByLevel[altLv] = altItem;
          if (LADDER_LEVELS.indexOf(altLv) === -1 && extraLevelOrder.indexOf(altLv) === -1) {
            extraLevelOrder.push(altLv);
          }
        }
      }
    }

    var levels =
      Array.isArray(opts.levels) && opts.levels.length > 0
        ? opts.levels.map(normalizeLevel)
        : LADDER_LEVELS.concat(extraLevelOrder);

    var rawSolverObj =
      (isObject(opts) && isObject(opts.solver) ? opts.solver : null) ||
      (isObject(revealState) && isObject(revealState.solver) ? revealState.solver : null) ||
      (isObject(caseData) && isObject(caseData.solver) ? caseData.solver : null);
    var solverSummary = normalizeSolverSummary(rawSolverObj);

    var solverScore =
      toFiniteNumber(firstDefined(opts, ["solverScore", "solver_score"])) !== null
        ? toFiniteNumber(firstDefined(opts, ["solverScore", "solver_score"]))
        : solverSummary && solverSummary.finalScore !== null
        ? solverSummary.finalScore
        : null;

    var rawEpisodes = [];
    var mergedByLevel = {};

    for (var i = 0; i < levels.length; i += 1) {
      var lv = levels[i];
      var engRec = engineByLevel[lv] || null;
      var rowModel =
        engRec && nonEmptyString(engRec.model) ? normalizeModelId(engRec.model) : model;
      var annRec = lookupEpisodeAnnotation(rowModel, lv, tier, seed, opts);
      var combined = mergeEpisodeRecords(engRec, annRec);
      mergedByLevel[lv] = combined;
      if (isObject(combined)) {
        rawEpisodes.push(combined);
        if (solverScore === null && toFiniteNumber(combined.solver_score) !== null) {
          solverScore = toFiniteNumber(combined.solver_score);
        }
      }
    }

    var trueMole = resolveTrueMole(
      tier,
      seed,
      parsed.judgeChoice,
      revealState,
      caseData,
      rawEpisodes,
      opts
    );
    var judge = normalizeJudgeChoice(parsed.judgeChoice, trueMole);

    var rows = [];
    var summaryModesByTag = {};
    var summaryModesList = [];

    for (var j = 0; j < levels.length; j += 1) {
      var levelKey = levels[j];
      var normRow = normalizeRow(levelKey, mergedByLevel[levelKey], trueMole, opts);
      rows.push(normRow);
      for (var t = 0; t < normRow.allTags.length; t += 1) {
        var tKey = normRow.allTags[t];
        if (!summaryModesByTag[tKey] && normRow.failureModes[tKey]) {
          summaryModesByTag[tKey] = normRow.failureModes[tKey];
          summaryModesList.push(normRow.failureModes[tKey]);
        }
      }
    }

    var titleRaw =
      nonEmptyString(firstDefined(opts, ["title", "caseTitle"])) ||
      (isObject(caseData) ? nonEmptyString(firstDefined(caseData, ["title", "name", "headline"])) : null);
    var decisionDay = isObject(caseData)
      ? toFiniteNumber(firstDefined(caseData, ["decision_day", "decisionDay", "day"]))
      : null;
    var decisionStep = isObject(caseData)
      ? toFiniteNumber(firstDefined(caseData, ["decision_step", "decisionStep", "step", "t"]))
      : null;
    var valueAtDecision = isObject(caseData)
      ? toFiniteNumber(firstDefined(caseData, ["value_at_decision", "valueAtDecision", "value"]))
      : null;
    var focusedLevelRaw = nonEmptyString(
      firstDefined(opts, ["focusedLevel", "focusedPodLevel", "selectedPod"])
    );

    return {
      caseId: rawCaseId || tier + "-" + seed,
      title: titleRaw ? sanitizeDashes(titleRaw) : null,
      tier: tier,
      seed: seed,
      model: model,
      decisionDay: decisionDay,
      decisionStep: decisionStep,
      valueAtDecision: valueAtDecision,
      trueMole: trueMole,
      solverScore: solverScore,
      solver: solverSummary,
      judge: judge,
      levels: levels,
      focusedLevel: focusedLevelRaw ? normalizeLevel(focusedLevelRaw) : null,
      rows: rows,
      failureModesSummary: summaryModesList,
      crossModelCarbon: normalizeCrossModelCarbon(caseData, trueMole)
    };
  }

  function renderOutcomeBadge(correct, holdFireFallback) {
    if (correct === true) {
      return '<span class="outthink-badge outthink-badge-right" data-outcome="right">RIGHT</span>';
    }
    if (correct === false) {
      return '<span class="outthink-badge outthink-badge-wrong" data-outcome="wrong">WRONG</span>';
    }
    if (holdFireFallback) {
      return '<span class="outthink-badge outthink-badge-neutral" data-outcome="hold_fire">HOLD FIRE</span>';
    }
    return '<span class="outthink-badge outthink-badge-na" data-outcome="na">N/A</span>';
  }

  function renderFailureCell(row) {
    if (!row.available) {
      return '<span class="outthink-tag-badge outthink-tag-na" data-failure-tag="na">N/A</span>';
    }
    if (!row.allTags || row.allTags.length === 0) {
      return '<span class="outthink-tag-badge outthink-tag-clean" data-failure-tag="none">clean</span>';
    }
    var badges = [];
    for (var i = 0; i < row.allTags.length; i += 1) {
      var tag = row.allTags[i];
      var isHighlighted = isHighlightedFailureTag(tag);
      var isPrimary = tag === row.primaryFailureTag;
      var fm = row.failureModes && row.failureModes[tag] ? row.failureModes[tag] : null;
      var cls = "outthink-tag-badge";
      if (isPrimary) {
        cls += " outthink-tag-primary";
      } else {
        cls += " outthink-tag-secondary";
      }
      if (isHighlighted) {
        cls += " outthink-tag-highlighted outthink-tag-" + safeSlug(tag);
      }
      var desc = "";
      if (fm && fm.enriched && fm.name && fm.description) {
        desc = fm.name + ": " + fm.description;
      } else if (fm && fm.description) {
        desc = fm.description;
      } else {
        desc = HIGHLIGHTED_TAG_DESCRIPTIONS[tag] || "";
      }
      var decisionAttr =
        fm && fm.decision ? ' data-failure-decision="' + escapeHtml(fm.decision) + '"' : "";
      var titleAttr = desc ? ' title="' + escapeHtml(desc) + '"' : "";
      badges.push(
        '<span class="' +
          cls +
          '" data-failure-tag="' +
          escapeHtml(tag) +
          '"' +
          decisionAttr +
          titleAttr +
          ">" +
          escapeHtml(tag) +
          "</span>"
      );
    }

    if (row.regretTotal !== null && row.regretTotal > 0) {
      badges.push(
        '<span class="outthink-regret-pill" data-regret="' +
          escapeHtml(formatScore(row.regretTotal)) +
          '">Regret ' +
          escapeHtml(formatScore(row.regretTotal)) +
          "</span>"
      );
    }

    var html = '<div class="outthink-failure-badges">' + badges.join(" ") + "</div>";

    if (row.failureMode && row.failureMode.enriched) {
      var fmPrimary = row.failureMode;
      var detailParts = [];
      if (fmPrimary.name) {
        detailParts.push(
          '<strong class="outthink-failure-name">' + escapeHtml(fmPrimary.name) + "</strong>"
        );
      }
      if (fmPrimary.description) {
        detailParts.push(
          '<span class="outthink-failure-desc">' + escapeHtml(fmPrimary.description) + "</span>"
        );
      }
      if (fmPrimary.mechanism) {
        detailParts.push(
          '<span class="outthink-failure-mechanism">Mechanism: ' +
            escapeHtml(fmPrimary.mechanism) +
            "</span>"
        );
      }
      if (fmPrimary.solverWould) {
        detailParts.push(
          '<span class="outthink-failure-solver">Solver instead: ' +
            escapeHtml(fmPrimary.solverWould) +
            "</span>"
        );
      }
      if (detailParts.length > 0) {
        html +=
          '<div class="outthink-failure-detail" data-failure-mode="' +
          escapeHtml(fmPrimary.id || fmPrimary.tag) +
          '">' +
          detailParts.join(" - ") +
          "</div>";
      }
    }

    return html;
  }

  function renderQuoteCell(row) {
    if (!row.available || !row.quotes || row.quotes.length === 0) {
      if (row.available && row.sourceFile) {
        return (
          '<span class="outthink-quote-empty">No quote (' +
          "<code>" +
          escapeHtml(row.sourceFile) +
          "</code>)</span>"
        );
      }
      return '<span class="outthink-quote-empty">N/A</span>';
    }

    var primary = row.quotes[0];
    var summaryLabel =
      "Verbatim Gemini quote (" + escapeHtml(primary.source_file) + ")";

    var itemsHtml = [];
    for (var i = 0; i < row.quotes.length; i += 1) {
      var q = row.quotes[i];
      var metaParts = [];
      if (q.source_kind) {
        metaParts.push(escapeHtml(q.source_kind));
      }
      if (q.day !== null) {
        metaParts.push("day " + escapeHtml(q.day));
      }
      if (q.t !== null) {
        metaParts.push("t=" + escapeHtml(q.t));
      }
      var metaSuffix = metaParts.length > 0 ? " [" + metaParts.join(", ") + "]" : "";
      var noteHtml = q.note
        ? '<div class="outthink-quote-note">' + escapeHtml(q.note) + "</div>"
        : "";

      itemsHtml.push(
        '<div class="outthink-quote-entry" data-quote-index="' +
          String(i) +
          '">' +
          '<blockquote class="outthink-quote-text">' +
          escapeHtml(q.quote) +
          "</blockquote>" +
          noteHtml +
          '<cite class="outthink-quote-source" data-source-file="' +
          escapeHtml(q.source_file) +
          '">Source: <code>' +
          escapeHtml(q.source_file) +
          "</code>" +
          metaSuffix +
          "</cite>" +
          "</div>"
      );
    }

    return (
      '<details class="outthink-quote-details">' +
      '<summary class="outthink-quote-summary">' +
      summaryLabel +
      "</summary>" +
      '<div class="outthink-quote-body">' +
      itemsHtml.join("") +
      "</div>" +
      "</details>"
    );
  }

  function renderSolverBar(solver) {
    if (!isObject(solver)) {
      return "";
    }
    var parts = [];
    if (solver.recommendedCall) {
      var callDisplay =
        solver.recommendedCall === "accuse"
          ? "ACCUSE" + (solver.topSuspect ? " " + solver.topSuspect : "")
          : solver.recommendedCall === "hold_fire"
          ? "HOLD FIRE"
          : solver.recommendedCall.toUpperCase();
      parts.push(
        'Bayesian Solver: <strong class="outthink-solver-call">' +
          escapeHtml(callDisplay) +
          "</strong>"
      );
    }
    if (solver.topProb !== null) {
      var topLabel =
        (solver.topSuspect ? solver.topSuspect + " @ " : "") + formatPct(solver.topProb);
      parts.push("Top posterior: <code>" + escapeHtml(topLabel) + "</code>");
    }
    if (solver.breakEvenProb !== null) {
      parts.push("Break-even: <code>" + escapeHtml(formatPct(solver.breakEvenProb)) + "</code>");
    }
    if (solver.evAccuseTop !== null && solver.evHoldFire !== null) {
      parts.push(
        "EV accuse vs hold: <code>" +
          escapeHtml(formatScore(solver.evAccuseTop)) +
          " vs " +
          escapeHtml(formatScore(solver.evHoldFire)) +
          "</code>"
      );
    }
    if (parts.length === 0) {
      return "";
    }
    return (
      '<div class="outthink-solver-bar" data-solver-call="' +
      escapeHtml(solver.recommendedCall || "") +
      '">' +
      parts.join(" | ") +
      "</div>"
    );
  }

  function renderCarbonComparison(vm) {
    if (
      !Array.isArray(vm.crossModelCarbon) ||
      vm.crossModelCarbon.length === 0 ||
      vm.model === "gemini-4-carbon"
    ) {
      return "";
    }
    var pills = [];
    for (var i = 0; i < vm.crossModelCarbon.length; i += 1) {
      var item = vm.crossModelCarbon[i];
      var accTxt = item.accused
        ? item.accused + (item.accusedDay !== null ? " (d" + String(Math.round(item.accusedDay)) + ")" : "")
        : "none";
      var statusTxt = item.correct === true ? "RIGHT" : item.correct === false ? "WRONG" : "N/A";
      pills.push(
        '<span class="outthink-carbon-pill" data-carbon-level="' +
          escapeHtml(item.level) +
          '">' +
          "<code>" +
          escapeHtml(item.level) +
          "</code>: " +
          escapeHtml(accTxt) +
          " | " +
          escapeHtml(formatScore(item.score)) +
          " | " +
          escapeHtml(formatCostUsd(item.costUsd)) +
          " (" +
          escapeHtml(statusTxt) +
          ")</span>"
      );
    }
    return (
      '<div class="outthink-carbon-comparison">' +
      '<strong class="outthink-carbon-heading">Same World on gemini-4-carbon:</strong> ' +
      pills.join(" ") +
      "</div>"
    );
  }

  function buildInnerHtml(vm) {
    var judgeBadge = renderOutcomeBadge(
      vm.judge.correct,
      vm.judge.action === "hold_fire"
    );
    var judgeScoreSuffix =
      vm.judge.score !== null
        ? ' <span class="outthink-judge-score">(score: ' +
          escapeHtml(formatScore(vm.judge.score)) +
          ")</span>"
        : "";
    var judgeVerdictSuffix = vm.judge.verdictLabel
      ? ' <span class="outthink-judge-verdict">' +
        escapeHtml(vm.judge.verdictLabel) +
        "</span>"
      : "";
    var judgeExplanationHtml = vm.judge.explanation
      ? '<div class="outthink-judge-explanation">' +
        escapeHtml(vm.judge.explanation) +
        "</div>"
      : "";
    var solverMeta =
      vm.solverScore !== null
        ? ' | Solver benchmark: <strong class="outthink-solver-score">' +
          escapeHtml(formatScore(vm.solverScore)) +
          "</strong>"
        : "";
    var titleHtml = vm.title
      ? '<div class="outthink-reveal-scenario">' + escapeHtml(vm.title) + "</div>"
      : "";

    var trueMoleDisplay = vm.trueMole ? vm.trueMole : "Unknown";

    var headerHtml =
      '<header class="outthink-reveal-header">' +
      '<h3 class="outthink-reveal-title">Thinking Ladder Reveal Panel</h3>' +
      titleHtml +
      '<div class="outthink-reveal-meta">' +
      "Model: <code>" +
      escapeHtml(vm.model) +
      "</code> | Tier: <code>" +
      escapeHtml(vm.tier) +
      "</code> | Seed: <code>" +
      escapeHtml(vm.seed) +
      "</code>" +
      solverMeta +
      "</div>" +
      '<div class="outthink-judge-vs-mole">' +
      '<div class="outthink-call-box outthink-judge-call" data-judge-action="' +
      escapeHtml(vm.judge.action) +
      '">' +
      '<span class="outthink-call-heading">Judge&#39;s Call:</span> ' +
      '<strong class="outthink-judge-choice">' +
      escapeHtml(vm.judge.label) +
      "</strong> " +
      judgeBadge +
      judgeScoreSuffix +
      judgeVerdictSuffix +
      judgeExplanationHtml +
      "</div>" +
      '<div class="outthink-call-box outthink-ground-truth">' +
      '<span class="outthink-call-heading">Ground Truth Mole:</span> ' +
      '<strong class="outthink-true-mole" data-true-mole="' +
      escapeHtml(trueMoleDisplay) +
      '">' +
      escapeHtml(trueMoleDisplay) +
      "</strong>" +
      "</div>" +
      "</div>" +
      renderSolverBar(vm.solver) +
      "</header>";

    var rowsHtml = [];
    for (var i = 0; i < vm.rows.length; i += 1) {
      var row = vm.rows[i];
      var accusedText = !row.available
        ? "N/A"
        : row.accused
        ? row.accused
        : "none";
      var accusedDaySuffix =
        row.available && row.accused && row.accusedDay !== null
          ? ' <span class="outthink-accused-day">(d' +
            escapeHtml(String(Math.round(row.accusedDay))) +
            ")</span>"
          : "";
      var outcomeHtml = row.available
        ? renderOutcomeBadge(row.correct, false)
        : renderOutcomeBadge(null, false);
      var scoreText = row.available ? formatScore(row.score) : "N/A";
      var costText = row.available ? formatCostUsd(row.costUsd) : "N/A";
      var rawTokAttr =
        row.available && row.thinkingTokens !== null
          ? String(Math.round(row.thinkingTokens))
          : "";
      var tokText = row.available
        ? formatTokens(row.thinkingTokens) +
          (row.thinkingIsEstimate && row.thinkingTokens !== null ? " (est.)" : "")
        : "N/A";
      var rowCls =
        "outthink-ladder-row" +
        (vm.focusedLevel && vm.focusedLevel === row.level ? " is-pod-focused" : "");

      rowsHtml.push(
        '<tr class="' +
          rowCls +
          '" data-level-key="' +
          escapeHtml(row.level) +
          '" data-level="' +
          escapeHtml(row.level) +
          '" data-available="' +
          (row.available ? "true" : "false") +
          '">' +
          '<th scope="row" class="outthink-col-level"><code>' +
          escapeHtml(row.level) +
          "</code></th>" +
          '<td class="outthink-col-accused" data-accused="' +
          escapeHtml(accusedText) +
          '"><code>' +
          escapeHtml(accusedText) +
          "</code>" +
          accusedDaySuffix +
          "</td>" +
          '<td class="outthink-col-outcome">' +
          outcomeHtml +
          "</td>" +
          '<td class="outthink-col-score" data-score="' +
          escapeHtml(scoreText) +
          '">' +
          escapeHtml(scoreText) +
          "</td>" +
          '<td class="outthink-col-cost" data-cost-usd="' +
          escapeHtml(costText) +
          '"><code>' +
          escapeHtml(costText) +
          "</code></td>" +
          '<td class="outthink-col-thinking" data-thinking-tokens="' +
          escapeHtml(rawTokAttr) +
          '">' +
          escapeHtml(tokText) +
          "</td>" +
          '<td class="outthink-col-failure">' +
          renderFailureCell(row) +
          "</td>" +
          '<td class="outthink-col-quote">' +
          renderQuoteCell(row) +
          "</td>" +
          "</tr>"
      );
    }

    var tableHtml =
      '<div class="outthink-ladder-table-wrap">' +
      '<table class="outthink-ladder-table">' +
      "<thead>" +
      "<tr>" +
      '<th scope="col">Level</th>' +
      '<th scope="col">Accused</th>' +
      '<th scope="col">Outcome</th>' +
      '<th scope="col">Score</th>' +
      '<th scope="col">Cost</th>' +
      '<th scope="col">Thinking Tokens</th>' +
      '<th scope="col">Primary Failure Mode</th>' +
      '<th scope="col">Verbatim Gemini Reasoning &amp; Citation</th>' +
      "</tr>" +
      "</thead>" +
      "<tbody>" +
      rowsHtml.join("") +
      "</tbody>" +
      "</table>" +
      "</div>";

    return headerHtml + tableHtml + renderCarbonComparison(vm);
  }

  function wrapSectionHtml(vm, innerHtml) {
    return (
      '<section class="outthink-reveal-card" data-model="' +
      escapeHtml(vm.model) +
      '" data-tier="' +
      escapeHtml(vm.tier) +
      '" data-seed="' +
      escapeHtml(vm.seed) +
      '">' +
      innerHtml +
      "</section>"
    );
  }

  function renderHTML(arg0, arg1, arg2, arg3, arg4, arg5) {
    var vm = buildModel(arg0, arg1, arg2, arg3, arg4, arg5);
    return wrapSectionHtml(vm, buildInnerHtml(vm));
  }

  function renderDOM(arg0, arg1, arg2, arg3, arg4, arg5) {
    var parsed = parseCallArgs(arg0, arg1, arg2, arg3, arg4, arg5);
    var vm = buildModel(arg0, arg1, arg2, arg3, arg4, arg5);
    var inner = buildInnerHtml(vm);
    var full = wrapSectionHtml(vm, inner);
    var host = getHostWindow(root);
    var doc =
      (isObject(parsed.options) && parsed.options.document) ||
      (host && host.document) ||
      (typeof document !== "undefined" ? document : null);

    var el;
    if (doc && typeof doc.createElement === "function") {
      el = doc.createElement("section");
      el.className = "outthink-reveal-card";
      if (typeof el.setAttribute === "function") {
        el.setAttribute("data-model", vm.model);
        el.setAttribute("data-tier", vm.tier);
        el.setAttribute("data-seed", vm.seed);
      }
      el.innerHTML = inner;
    } else {
      el = {
        nodeType: 1,
        tagName: "SECTION",
        className: "outthink-reveal-card",
        dataset: {
          model: vm.model,
          tier: vm.tier,
          seed: vm.seed
        },
        innerHTML: inner,
        outerHTML: full
      };
    }

    if (parsed.container) {
      if (
        typeof parsed.container.replaceChildren === "function" &&
        doc &&
        typeof doc.createElement === "function"
      ) {
        parsed.container.replaceChildren(el);
      } else {
        parsed.container.innerHTML = full;
      }
    }

    return el;
  }

  function mount(container, arg1, arg2, arg3, arg4, arg5) {
    var html = renderHTML(arg1, arg2, arg3, arg4, arg5);
    if (container && typeof container === "object") {
      container.innerHTML = html;
    }
    return container;
  }

  function render(arg0, arg1, arg2, arg3, arg4, arg5) {
    var parsed = parseCallArgs(arg0, arg1, arg2, arg3, arg4, arg5);
    var vm = buildModel(arg0, arg1, arg2, arg3, arg4, arg5);
    var html = wrapSectionHtml(vm, buildInnerHtml(vm));
    if (parsed.container) {
      parsed.container.innerHTML = html;
      if (parsed.returnContainer) {
        return parsed.container;
      }
    }
    return html;
  }

  var OutthinkRevealCard = {
    LADDER_LEVELS: LADDER_LEVELS,
    HIGHLIGHTED_FAILURE_TAGS: HIGHLIGHTED_FAILURE_TAGS,
    escapeHtml: escapeHtml,
    escapeHTML: escapeHtml,
    sanitizeDashes: sanitizeDashes,
    formatCostUsd: formatCostUsd,
    formatScore: formatScore,
    formatTokens: formatTokens,
    lookupFailureMode: lookupFailureMode,
    resolveFailureMode: lookupFailureMode,
    lookupEpisodeAnnotation: lookupEpisodeAnnotation,
    buildModel: buildModel,
    getRevealData: buildModel,
    fromRevealState: buildModel,
    renderHTML: renderHTML,
    renderHtml: renderHTML,
    renderDOM: renderDOM,
    createElement: renderDOM,
    mount: mount,
    render: render
  };

  if (typeof window !== "undefined" && window) {
    window.OutthinkRevealCard = OutthinkRevealCard;
    window.OutThinkRevealCard = OutthinkRevealCard;
    window.OUTTHINK_REVEAL_CARD = OutthinkRevealCard;
    window.renderOutthinkRevealCard = render;
    window.renderOutThinkRevealCard = render;
  }
  if (typeof globalThis !== "undefined" && globalThis && globalThis.window) {
    globalThis.window.OutthinkRevealCard = OutthinkRevealCard;
    globalThis.window.OutThinkRevealCard = OutthinkRevealCard;
    globalThis.window.OUTTHINK_REVEAL_CARD = OutthinkRevealCard;
    globalThis.window.renderOutthinkRevealCard = render;
    globalThis.window.renderOutThinkRevealCard = render;
  }
  if (root && typeof root === "object") {
    root.OutthinkRevealCard = OutthinkRevealCard;
    root.OutThinkRevealCard = OutthinkRevealCard;
    root.OUTTHINK_REVEAL_CARD = OutthinkRevealCard;
    root.renderOutthinkRevealCard = render;
    root.renderOutThinkRevealCard = render;
  }
  if (typeof module !== "undefined" && module.exports) {
    module.exports = OutthinkRevealCard;
  }
})(typeof globalThis !== "undefined" ? globalThis : typeof window !== "undefined" ? window : this);
